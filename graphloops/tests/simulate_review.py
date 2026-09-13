#!/usr/bin/env python3
"""review-loop の engine を、役の返答を台本で差し替えて端から端まで回す（役割 agent も LLM も使わない）。

確かめるのは engine・rules・graph の噛み合わせと、周ごとの記録 rounds/round-<N>.json が
convergence-loops の検証器（scripts/review-record.py。ディレクトリ渡し）を通ること——
収束（連続 2 ラウンド）・前提不成立で人へ・保留の問いに帰属して人へ・答えを渡して続行・上限で停止・拒むべき返答の拒否。

使い方: python3 simulate_review.py
"""
import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import types

# Windows の既定の標準出力は cp1252（日本語 Windows なら cp932）で、日本語を print すると
# UnicodeEncodeError で落ちる。リポジトリの他の出力スクリプトと同じ型に揃える。
for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8")

HERE = pathlib.Path(__file__).resolve().parent
PLUGIN = HERE.parent
LOOP = PLUGIN / "scripts" / "loop.py"
VALIDATOR = PLUGIN.parent / "scripts" / "review-record.py"
PY = sys.executable
BIG_ROWS = 3000  # 「1 ファイルが大きい」材料の行数（約 180 KB。旧実装ならここで 4 片以上に割れていた）
fails, ran = [], 0


def check(cond, desc):
    global ran
    ran += 1
    print(("  ok   " if cond else "  FAIL ") + desc)
    if not cond:
        fails.append(desc)


def rm(p):
    """作業場の掃除。Windows は git の object を読み取り専用で置き、素の rmtree が PermissionError で
    落ちる（実測: CI の windows-latest）。掃除の失敗で検査本体を落とさない。"""
    shutil.rmtree(p, ignore_errors=True)


def sh(cwd, *args):
    return subprocess.run(args, cwd=cwd, capture_output=True, text=True, encoding="utf-8", timeout=120)


MADE = set()  # この プロセスが作った作業場だけを後始末する（接頭辞の列挙は他プロセスの盤面を巻き込む）


class Run:
    def __init__(self, name, unattended=False, big=False, latin=False):
        self.tmp = pathlib.Path(tempfile.mkdtemp(prefix=f"gl-review-{name}-"))
        MADE.add(self.tmp)
        self.repo = self.tmp / "repo"
        self.repo.mkdir()
        g = lambda *a: sh(self.repo, "git", "-c", "user.email=t@t", "-c", "user.name=t", *a)
        g("init", "-q")
        (self.repo / "src").mkdir()
        (self.repo / "src" / "a.py").write_text("def f(x):\n    return x\n", encoding="utf-8")
        (self.repo / "README.md").write_text("# demo\n", encoding="utf-8")
        g("add", "."); g("commit", "-q", "-m", "base")
        self.base = g("rev-parse", "HEAD").stdout.strip()
        (self.repo / "src" / "a.py").write_text("def f(x, limit=None):\n    return x if limit is None else min(x, limit)\n", encoding="utf-8")
        (self.repo / "src" / "b.py").write_text("def g(y):\n    return y * 2\n", encoding="utf-8")
        if big:  # 1 ファイル・1 hunk の大きな差分（実走で 186 KB が 1 塊のまま返った形）
            (self.repo / "src" / "big.py").write_text("".join(f"ROW_{i:05d} = {i}  # generated padding line for a long single hunk\n" for i in range(BIG_ROWS)), encoding="utf-8")
            # 日本語主体のファイルも足す——字数で割ると同じ字数がおよそ 3 倍のバイトになり、貼る先の上限を超える
            (self.repo / "docs.md").write_text("".join(f"- {i:05d} 行目。ここは日本語の説明で、字数とバイト数が一致しない入力を主経路に与えるためにある。\n" for i in range(900)), encoding="utf-8")
        if latin:  # UTF-8 でないテキスト（Latin-1 の é と単独の 0xFF）。git の出力と file: の読みが厳格な復号で落ちていた
            (self.repo / "src" / "latin.py").write_bytes(b"# caf\xe9 \xff legacy encoding\nX = 1\n")
        g("add", "."); g("commit", "-q", "-m", "change under review")
        self.dir = self.tmp / "state"
        args = ["init", "--loop", "review-loop", "--request", "この変更をレビュー", "--dir", str(self.dir), "--validator", str(VALIDATOR)]
        if unattended:
            args.append("--unattended")
        self.init = self.cmd(*args)

    def cmd(self, *args, env=None, input=None):
        extra = [] if args[0] == "init" else ["--dir", str(self.dir)]
        # timeout: 無限ループの退行が入ると CI が赤でなく止まる（engine 側は git 120 秒・検証器 600 秒の上限を持つ）
        return subprocess.run([PY, str(LOOP), *args, *extra], cwd=self.repo, capture_output=True, text=True, encoding="utf-8", env=env, input=input, timeout=600)

    def next(self):
        r = self.cmd("next")
        if r.returncode != 0:
            raise RuntimeError(f"next が {r.returncode}: {r.stderr[-800:]}")
        return json.loads(r.stdout)

    def done(self, node, output, agent_id=None):
        f = self.tmp / "out.txt"
        f.write_text(output if isinstance(output, str) else json.dumps(output, ensure_ascii=False), encoding="utf-8")
        return self.cmd("done", "--node", node, "--output", str(f), *(["--agent-id", agent_id] if agent_id else []))

    def record(self):
        # **記録は盤面のファイルを直読みする。** loop.py record は record.json の丸写しなのに、CLI 経由だと
        # 1 回ごとに python の起動と engine の import を払う（実測 2026-09-13: 2 本の台本で計 567 回・30.4 秒、
        # 直読みに替えると検査一式が 161 秒 → 132 秒で件数と失敗数は不変）。record サブコマンド自体の煙テストは
        # record_cli() に 1 か所だけ残す——全部を直読みにすると、そのコマンドが壊れても誰も気づかない
        return json.loads((self.dir / "record.json").read_text(encoding="utf-8"))

    def record_cli(self):
        """loop.py record が record.json の丸写しを返すことの煙テスト（呼ぶのは 1 か所だけ）。"""
        return json.loads(self.cmd("record").stdout)

    def state(self):
        return json.loads((self.dir / "state.json").read_text(encoding="utf-8"))

    def round_file(self, n):
        return json.loads((self.dir / "rounds" / f"round-{n}.json").read_text(encoding="utf-8"))


# ---------------------------------------------------------------- 台本
def M(status, **kw):
    return {"status": status, **kw}


CLEAN = lambda what: M("clean", checked=what)


def answers(run, scenario, rnd):
    """節ごとの返答。scenario と周で分岐する。"""
    base = run.base
    blocks_forever = scenario == "runaway"
    # 今の周に直す単位は覆いの母数（class_query）を持つ——名指しの 1 site だけ塞ぐ閉じ方を機械が止める
    CQ = lambda n=1: {"how": "grep -rn 'limit' src/ | wc -l", "total": n}
    unit_block = {"key": "src/a.py:f — 上限が効かない経路がある", "label": "block", "class_query": CQ()}  # 母数 1（sites 1 と揃う）
    unit_donow = {"key": "src/b.py:g — 定数の重複", "label": "suggest", "disposition": "do-now", "class_query": CQ(1)}
    rec = run.record()
    prev_q = run.state().get("loop", {}).get("prev_questions", [])

    def units_for(rnd):
        if blocks_forever:
            return [{"key": f"src/a.py:f — 周 {rnd} に見つかった新しい欠陥", "label": "block", "class_query": CQ()}]
        if scenario == "deferjudge" and rnd == 1:  # judge が defer を返す筋（以前の台本は一度も返さず、rules の defer の腕が観測できなかった）
            return [unit_block, {**unit_donow, "disposition": "defer", "reason": "処方が共有面（キャッシュ層）に及ぶ（検査用）"}]
        return [unit_block, unit_donow] if rnd == 1 else []

    def questions_for(rnd):
        if scenario == "premise_resolved":
            # 立った周は機械が held で載せる（検証器の要求）。次の周の judge が、回し直した R2 を見て resolved に確定する
            q = next((x for x in prev_q if x.get("kind") == "premise" and x.get("status") == "held"), None)
            if q:
                return [{"key": q["key"], "kind": "premise", "origin": "R2", "status": "resolved", "reason": q["reason"],
                         "resolution": "実測を制約に足して R2 を回し直し、問いは立った（premise-invalid は解けた）"}]
            return []
        if scenario == "nopurpose":
            # 1 周目は機械（record_round）が R2 unverifiable の行を立てる。2 周目の judge はそれを再審して人へ回す
            q = next((x for x in prev_q if x.get("kind") == "unverifiable" and x.get("origin") == "R2"), None)
            if q:
                return [{"key": q["key"], "kind": "unverifiable", "origin": "R2", "status": "escalate",
                         "reason": "目的の出典は人が示すしかない", "options": ["PR 説明に目的を書く", "未収束のまま報告で終える"]}]
            return []
        if scenario == "awaiting":
            q = {"key": "検索から結果表示までの主経路を誰がどこで動かすか", "kind": "awaiting", "origin": "main_path_observation", "status": "held",
                 "reason": "主経路の実行観測で dev サーバが起動できなかった"}
            if rec["materials"].get("main_path_observation", {}).get("status") == "awaiting_human":
                return [q]
            if any(x["key"] == q["key"] for x in prev_q):
                return [{**q, "status": "resolved", "resolution": "人が動かして観測した（human_answers）"}]
        return []

    def judge(rnd):
        us = units_for(rnd)
        return {"units": us, "questions": questions_for(rnd), "framing": "根本は上限の欠落", "one_shot": "上限を 1 箇所に寄せる",
                # 一撃は反証可能に——閉じると見込む key を名指しし、次の周が測る問いを添える
                "one_shot_closes": [u["key"] for u in us],
                "materials_missing": [], "router": [{"key": unit_block["key"], "route": "②閉じた", "note": "grep で確認"}] if rnd > 1 else []}

    awaiting_mp = scenario == "awaiting" and rnd < 3
    table = {
        "p0.base": lambda it: {"base_sha": base, "method": "3 HEAD~1", "commits": 1, "merge_commit": False, "intent_to_add": [],
                               "touches_gates": scenario == "gates", "touches_external_seams": False, "touches_user_path": scenario == "awaiting",
                               "material": CLEAN(f"HEAD~1 で決めた。BASE={base[:7]}。対象差分は 1 コミット分")},
        "p0.local_checks": lambda it: {"material": CLEAN("python -m pytest（緑）")},
        "p0.premises": lambda it: {"constraints": [{"text": "呼び出し元は 1 箇所", "measured_how": "grep -c 'f(' src/",
                                                    "measured_output": "src/a.py:1", "kind": "実測"}]},
        "p0.purpose": lambda it: ({"purpose_text": "（PR 説明も計画も無く目的を取れない）", "source": "目的不明", "known_weaknesses": [], "source_files": []} if scenario == "nopurpose" else
                                  {"purpose_text": "f に上限を付ける（writer の要約）", "source": "③writer の要約", "known_weaknesses": [], "source_files": ["README.md"]} if scenario == "narrowed" else
                                  {"purpose_text": "f に上限を付けて過大な値を抑える", "source": "①PR 説明", "known_weaknesses": [], "source_files": ["README.md"]}),
        "p0.purpose_review": lambda it: {"verdict": "狭めている" if scenario == "narrowed" else "問題なし",
                                          "reason": "目的が実装した範囲に合わせて狭い（検査用）", "findings": ["呼び出し元の上限に触れていない"] if scenario == "narrowed" else []},
        "p0.parallel_pr": lambda it: {"material": CLEAN("gh pr list 0 件（打ち切りなし）"), "repo": "t/demo", "listed": 0, "truncated": False, "conflicts": []},
        "p0.prior_decisions": lambda it: {"material": CLEAN("docs/ と closed issue を洗った。決着済みなし"), "checked": True, "searched": ["docs/", "gh issue list --state all"], "settled": []},
        "p1.local_review": lambda it: {"material": M("found", count=1, detail="review-pr: 上限の分岐が片方だけ") if rnd == 1 and not blocks_forever else CLEAN("review-pr・/simplify 再実行。新規なし"),
                                       "findings": [{"skill": "review-pr", "items": [{"where": "src/a.py", "text": "上限が片方の分岐だけ"}]}] if rnd == 1 else [], "simplify_carried": rnd > 1},
        "p1.consistency_bypass": lambda it: {"consistency": CLEAN("命名と設定の追従を Grep で突合"), "bypass": CLEAN("翻訳関数・共有ユーティリティの迂回なし"), "findings": [], "bypass_findings": [], "seen": "src/ 全部", "unseen": "なし"},
        "p1.hygiene": lambda it: {"findings": [], "seen": "差分の追加行すべて"},
        "p1.external_standards": lambda it: {"material": CLEAN("依存の組み込み機能と突合。再発明なし"), "findings": [], "seen": "import と宣言済み依存", "unseen": "なし", "web_refetched": True},
        "p1.procedure_trace": lambda it: {"material": CLEAN("手順書と実装の突合。宣言と実装の食い違いなし"), "findings": [], "unmeasured": []},
        "p1.gate_efficacy": lambda it: {"material": CLEAN("新設ゲートの腕ごとに写しの上で退行を注入して赤を確認"),
                                        "arms": [{"gate": "上限の検査", "arm": "limit=None の経路", "red_confirmed": True, "control_green": True, "hit_evidence": "分岐が書く理由文字列を一意の印に替えた写しで、印が記録に出ることを確認した"}]},
        "p1.test_double_fidelity": lambda it: {"material": M("not_applicable", reason="外部との継ぎ目に触れていない"), "mismatches": []},
        "p1.provenance": lambda it: {"material": CLEAN("事実の主張なし"), "claims": []},
        "p1.main_path_observation": lambda it: {"material": M("awaiting_human", reason="dev サーバが社内認証に繋がず起動しない") if awaiting_mp else CLEAN("人が用意した設定で 1 回動かし値を観測"), "observed": []},
        "p2.diagnose": lambda it: judge(rnd),
        "p2.history": lambda it: judge(rnd),
        "p3.fix": lambda it: {"changes": [{"unit_key": u["key"], "what": "上限を 1 箇所に", "files": ["src/a.py"], "closure": {"mechanism": "分岐で上限が漏れる", "fix_mechanism": "共通経路に寄せた", "verified_how": "退行注入で赤→緑", "sites": [{"site": "src/a.py:f", "red_seen": True}]},
                                                 "coverage": {"how": "grep -rn 'limit' src/ | wc -l", "total": 1},
                                                 # 壊さないか・根本か・破れないか——修正が次の周の欠陥を作らないための 3 欄
                                                 "root_or_symptom": {"kind": "root", "why": "上限の分散そのものを 1 箇所に寄せた"},
                                                 "bypass_tried": "修正を残したまま limit=0 と limit=-1 と分岐の両側を通した——どれも上限が効いた",
                                                 "breaks": {"how": "grep -rn 'min(' src/", "result": "同じ経路を使う 2 箇所とも既存の検査が緑"}} for u in rec["units"]],
                              "not_done": [],
                              # 2 つ以上の修正が触った面は機械が changes[].files から出す——書き落とすと拒まれる
                              "interactions": ([{"surface": "src/a.py", "changes": [u["key"] for u in rec["units"]],
                                                 "checked": "上限を寄せる修正と定数を寄せる修正は同じ関数を触るが、当てる順序で結果は変わらない（どちらも共通経路に足すだけ）"}]
                                               if len(rec["units"]) >= 2 else []),
                              "fix_closure": CLEAN("退行を注入して赤→復元して緑") if rec["units"] else M("not_applicable", reason="本ラウンドに修正なし"),
                              "mechanism_changed": scenario == "premise_resolved" and rnd == 2, "premise_drift": False, "deps_changed": False, "procedures_changed": False, "gates_changed": False,
                              "seams_changed": False, "path_changed": False, "claims_changed": False, "decision_records_changed": False},
        "p4.ci": lambda it: {"material": CLEAN("pytest 緑")},
        "p4.scalars": lambda it: {"scalars": {"comment_ratio_pct": 10, "doc_lines": 1}},
        "r1.comment_candidates": lambda it: {"candidates": [], "kept": []},
        "r1.minimality": lambda it: {"status": "pass", "reason": "累積差分は最小。台帳に逃げ道なし", "deletions": [], "ledger_audit": [], "increments": []},
        "r2.design": lambda it: ({"question_stands": False, "reason": "既存機構で自明", "premise_invalid_reason": "呼び出し元が既に上限を持つ", "design": ""} if (scenario == "premise" or (scenario == "premise_resolved" and rnd == 1)) else
                                 {"question_stands": True, "reason": "問いは立っている", "design": "上限は入口 1 箇所で掛ける"}),
        "r2.compare": lambda it: {"status": "pass", "reason": "構造は一致", "differences": []},
        "r3.coherence": lambda it: {"status": "pass", "reason": "横断で揃っている"},
        "r4.hidden_scope": lambda it: {"status": "pass", "reason": "導入・露呈した横断リスクなし", "capability_inventory": {"fired": False}, "surfaced": []},
        "stop.premise_check": lambda it: ({"key": "f の上限は既存機構で自明に満たされているか", "assumption": "呼び出し元が上限を持つ", "assumption_false": True, "evidence": "grep f( で 3 箇所中 2 箇所は上限を持たない",
                                           "verdict": "resolved", "reason": "仮定は実態で偽", "resolution": "呼び出し元 3 箇所中 2 箇所は上限を持たない（実測）",
                                           "facts_to_add": ["f の呼び出し元 3 箇所のうち 2 箇所は上限を持たない"]} if scenario == "premise_resolved" else
                                          {"key": "f の上限は既存機構で自明に満たされているか", "assumption": "呼び出し元が上限を持つ", "assumption_false": False, "evidence": "実態では持っていない箇所もあるが目的テキストの内側で閉じている",
                                           "verdict": "escalate", "reason": "人でないと決められない"}),
        "report.human_items": lambda it: "## 人が決めること\n\n無し。\n",
        "report.cold_check": lambda it: {"verdict": "pass", "stops": [], "guessed": [], "decidable": True},
        "report": lambda it: "# レビュー報告\n\n収束した。\n",
    }
    if scenario == "noci":  # CI を確かめていない周を緑と数えない（converge の腕）
        table["p0.local_checks"] = lambda it: {"material": M("not_applicable", reason="この環境に CI が無い（検査用）")}
        table["p4.ci"] = lambda it: {"material": M("not_applicable", reason="この環境に CI が無い（検査用）")}
    if scenario == "liar":  # 申告したファイルに実際は触らない writer（drive は実在するファイルしか編集しない）
        real = table["p3.fix"]
        table["p3.fix"] = lambda it: {**real(it), "changes": [{**c, "files": ["src/zzz.py"]} for c in real(it)["changes"]],
                                      "interactions": [{**i, "surface": "src/zzz.py"} for i in real(it)["interactions"]]}
    if scenario == "cired":  # 阻害なしでも CI が毎周赤——converged 分岐の早期 return が暴走ガードを飛ばしていた（実測 2026-09-13: round 9 / max 5 で running）
        table["p0.local_checks"] = lambda it: {"material": M("found", count=1, detail="CI が赤（検査用）")}
        table["p4.ci"] = lambda it: {"material": M("found", count=1, detail="CI が赤のまま（検査用）")}
    if scenario == "coldfail":  # 初見検査の非 pass は記録に残る（門ではない）
        table["report.cold_check"] = lambda it: {"verdict": "redesign-needed", "stops": ["2 段落目の『前提』が未定義"], "guessed": [], "decidable": False}
    return table


def drive(run, scenario, max_steps=120, hook=None):
    last = None
    for _ in range(max_steps):
        nx = run.next()
        last = nx
        if nx.get("status") == "awaiting_human" or (not nx["ready"] and nx["status"] in ("converged", "stopped")):
            return nx
        if not nx["ready"]:
            raise RuntimeError("ready が空のまま進まない: " + json.dumps(nx, ensure_ascii=False)[:800])
        table = answers(run, scenario, nx["round"])
        for inst in nx["ready"]:
            out = table[inst["node"]](inst["item"])
            if hook:
                out = hook(run, inst, out) or out
            if inst["node"] == "p3.fix" and isinstance(out, dict):
                # 台本の writer は申告どおりに実際に手を入れる——前の周の P3 が触ったファイルは engine が diff の差から測り、
                # 申告は照合の片側でしかない（申告だけで触らないと測定 0 件＝持ち越しになる）
                for f in {f for c in out.get("changes", []) for f in c.get("files", [])}:
                    p = run.repo / f
                    if p.is_file():
                        p.write_text(p.read_text(encoding="utf-8") + f"# fixed in round {nx['round']}\n", encoding="utf-8")
            r = run.done(inst["id"], out, agent_id="judge-1" if inst["node"] == "p2.diagnose" else None)
            if r.returncode != 0:
                raise RuntimeError(f"done {inst['id']} が {r.returncode}: {r.stderr[-1200:]}")
    raise RuntimeError("max_steps に達した")


# ---------------------------------------------------------------- 検査
def test_new_guards():
    print("否定検査: 2 周目に塞いだ柵（実測の再現・cond の path・空返答・空差分・受理集合）")
    run = Run("guards")
    nx = run.next()
    by = {i["node"]: i for i in nx["ready"]}
    t = answers(run, "std", 1)
    # kind=実測 は再現の形（コマンドと出力）を持て——『実測』の札だけが検算なしで信頼値に昇格しない
    bad = {"constraints": [{"text": "呼び出し元は 1 箇所", "measured_how": "grep した", "kind": "実測"}]}
    r = run.done(by["p0.premises"]["id"], bad)
    check(r.returncode == 1 and "measured_output" in r.stderr, "kind=実測 に measured_output が無いと exit 1")
    r = run.done(by["p0.premises"]["id"], {"constraints": [{**bad["constraints"][0], "kind": "仮説"}]})
    check(r.returncode == 0, "仮説なら再現の形は要らない")
    rm(run.tmp)

    # 対象差分が空なら P1 の前で止まる（5 周まわして事実と逆の理由を書き続けない）
    run = Run("emptydiff")
    nx = run.next()
    by = {i["node"]: i for i in nx["ready"]}
    t = answers(run, "std", 1)
    head = sh(run.repo, "git", "rev-parse", "HEAD").stdout.strip()
    run.done(by["p0.base"]["id"], {**t["p0.base"](None), "base_sha": head})
    for n in ("p0.local_checks", "p0.premises"):
        run.done(by[n]["id"], t[n](None))
    nx = run.next()
    check(any("対象差分が空" in n for n in nx["notes"]) and not any(i["node"].startswith("p1.") for i in nx["ready"]), f"BASE=HEAD（差分ゼロ）は P1 の前で止まる: {nx.get('notes')}")
    rm(run.tmp)

    # git が取れない場では対象差分そのものが測れない——空文字に潰して「変化なし」にしない
    run = Run("nogit-snap")
    nx = run.next()
    by = {i["node"]: i for i in nx["ready"]}
    t = answers(run, "std", 1)
    for n in ("p0.base", "p0.local_checks", "p0.premises"):
        run.done(by[n]["id"], t[n](None))
    (run.tmp / "empty-bin").mkdir()
    r = run.cmd("next", env={**os.environ, "PATH": str(run.tmp / "empty-bin")})
    nx = json.loads(r.stdout) if r.returncode == 0 and r.stdout.strip().startswith("{") else {"ready": ["?"], "notes": [r.stderr]}
    check(any("git が取れない" in n or "取れない" in n for n in nx["notes"]), f"git が無い場では対象差分の取得で止まる（空文字に潰さない）: {str(nx.get('notes'))[:100]}")
    rm(run.tmp)

    # cond の path が解決できない graph は next で die（偽に倒して『条件に当たらない』に化けさせない）
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="gl-cond-"))
    g = json.loads((PLUGIN / "graphs" / "review-loop.json").read_text(encoding="utf-8"))
    g["nodes"]["p0.local_checks"]["cond"] = {"path": "loop.no_such_key", "op": "eq", "value": 1}  # 最初の波で評価される節に置く
    (tmp / "graphs").mkdir()
    for sub in ("prompts", "rules"):
        shutil.copytree(PLUGIN / sub, tmp / sub)
    (tmp / "graphs" / "badcond.json").write_text(json.dumps(g, ensure_ascii=False), encoding="utf-8")
    run = Run("badcond")
    r = run.cmd("init", "--loop", "review-loop", "--graph", str(tmp / "graphs" / "badcond.json"),
                "--request", "x", "--dir", str(run.tmp / "s2"), "--validator", str(VALIDATOR))
    r2 = subprocess.run([PY, str(LOOP), "next", "--dir", str(run.tmp / "s2")], cwd=run.repo, capture_output=True, text=True, encoding="utf-8", timeout=600)
    nxt = subprocess.run([PY, str(LOOP), "next", "--dir", str(run.tmp / "s2")], cwd=run.repo, capture_output=True, text=True, encoding="utf-8", timeout=600)
    check(r.returncode == 0 and ("解決できない" in r2.stderr + nxt.stderr or "解決できない" in r2.stdout), 
          f"解決できない cond の path は die（偽に倒さない）: {(r2.stderr + nxt.stderr)[-120:]}")
    rm(tmp); rm(run.tmp)


def test_empty_text_reply():
    print("否定検査: 本文を返す節の空返答（0 バイトの報告を残さない）")
    run = Run("emptytext")
    seen = {}

    def hook(run_, inst, out):
        if inst["node"] in ("report", "report.human_items") and inst["node"] not in seen:
            seen[inst["node"]] = True
            r = run_.done(inst["id"], "   \n  ")
            check(r.returncode == 1 and "空" in r.stderr, f"{inst['node']}: 空白だけの返答は exit 1")
            empty = run_.tmp / "empty.txt"  # /dev/null は Windows に無い（実測: CI の windows-latest で FileNotFoundError→exit 2）
            empty.write_text("", encoding="utf-8")
            r = run_.cmd("done", "--node", inst["id"], "--output", str(empty))
            check(r.returncode == 1, f"{inst['node']}: 0 バイトのファイルも exit 1")
        return out

    drive(run, "std", hook=hook)
    check(len(seen) >= 1 and (run.dir / "report.md").read_text(encoding="utf-8").strip(), "正しい本文なら通り、report.md は空でない")
    rm(run.tmp)


def test_converges():
    print("台本: 1 周目に [block] と do-now、直して 3 周で収束")
    run = Run("std")
    check(run.init.returncode == 0, "init が通る")
    last = drive(run, "std")
    st = run.state()
    check(last["status"] == "converged", f"status が converged（{last['status']}）")
    check(st["round"] == 3, f"3 周で収束（{st['round']}）")
    r1, r2, r3 = run.round_file(1), run.round_file(2), run.round_file(3)
    check(len(r1["materials"]) == 15 and all("status" in m for m in r1["materials"].values()), "周の記録に素材 15 欄が揃う")
    check(r1["materials"]["procedure_trace"]["status"] == "not_applicable" and r1["materials"]["fix_closure"]["status"] == "clean", "条件外は not_applicable、fix_closure は P3 の返答")
    check(r2["materials"]["parallel_pr"]["status"] == "carried_over" and r2["materials"]["parallel_pr"].get("from_round") == 1,
          f"再発火条件を持たない once の節は carried_over（実際に見た周付き。{r2['materials']['parallel_pr']}）")
    check(r2["materials"]["external_standards"]["status"] == "clean",
          f"差分全体を見る素材は、前の周の P3 が触ったので走り直す（{r2['materials']['external_standards']['status']}）")
    # 前の周の P3 が触ったファイルを見る素材は持ち越さない（閉じた欠陥が次の周に生き返らない）
    check(r2["materials"]["provenance"]["status"] != "carried_over",
          f"前の周の P3 が src/a.py を直したので provenance は持ち越さず走り直す（{r2['materials']['provenance']['status']}）")
    carried = [n for n, m in r3["materials"].items() if m["status"] == "carried_over"]
    check(all("確認:" in r3["materials"][n]["reason"] for n in carried), f"持ち越しの理由は確かめた対象を書く（{len(carried)} 件）")
    check(r1["reviews"]["R3"]["status"] == "not_applicable" and r2["reviews"]["R3"]["status"] == "pass",
          f"R3/R4 は『前の周の P3 が触った周』にも走る——引き金（前の周の修正）と材料（P1 が写した差分）が同じ周で揃う。"
          f"1 周目は前の修正が無いので走らない（r1={r1['reviews']['R3']['status']} / r2={r2['reviews']['R3']['status']}）")
    check(r2["reviews"]["R1"]["status"] == "carried_over" and r3["reviews"]["R1"]["from_round"] == 1, "R1 は再発火しない周に持ち越し、連鎖は round 1 を指す")
    v = subprocess.run([PY, str(VALIDATOR), str(run.dir / "rounds")], capture_output=True, text=True, encoding="utf-8", timeout=600)
    check(v.returncode == 0, "検証器がディレクトリで exit 0（連続 2 ラウンド）")
    check((run.dir / "report.md").is_file(), "report.md が保存された")
    inst = st["rounds"][1]["instances"]
    hist = next((i for i in inst.values() if i["node"] == "p2.history"), None)
    check(hist and hist.get("mode") == "agent_continue" and hist.get("agent_id") == "judge-1", "2 周目の履歴の突合は同じ judge を続ける（agent_continue）")
    check(st["rounds"][0]["na"].get("p2.history", "").startswith("cond"), "1 周目に履歴の突合は無い")
    check((run.dir / "diff-r1.patch").is_file() and "src/b.py" in (run.dir / "diff-r1.patch").read_text(encoding="utf-8"), "対象差分は機械が取って置く")
    rm(run.tmp)


def test_premise():
    print("台本: R2 が premise-invalid → 立った周に judge が検算 → escalate で止めて聞く")
    run = Run("premise")
    last = drive(run, "premise")
    check(last["status"] == "awaiting_human" and last["ask"]["kinds"] == ["premise_escalate"], "前提不成立で人に聞く番になる（立った周）")
    r1 = run.round_file(1)
    check(r1["reviews"]["R2"]["status"] == "premise-invalid", "R2 は premise-invalid のまま記録される")
    check(any(q["kind"] == "premise" and q["status"] == "escalate" for q in r1["questions"]), "台帳に premise / escalate が載る")
    r = run.cmd("answer", "--text", "stop")
    check(r.returncode == 0, "stop で止める")
    last = drive(run, "premise")
    check(last["status"] == "stopped" and (run.dir / "report.md").is_file(), "止まった run でも報告は出る（検証器 exit 1 を受け付ける）")
    rm(run.tmp)


def test_awaiting():
    print("台本: 主経路が動かせず awaiting → 保留の問いに帰属して聞く → 答えを渡して続行 → 収束")
    run = Run("await")
    last = drive(run, "awaiting")
    check(last["status"] == "awaiting_human" and last["ask"]["kinds"] == ["work_exhausted"], f"残る阻害が保留の問いだけになった周に聞く（{last.get('ask', {}).get('kinds')}）")
    check(run.state()["round"] == 2, "立った周（1）には聞かず、2 周目に聞く")
    r = run.cmd("answer", "--text", "continue", "--note", "テスト用設定 config/dev.local.example で起動できる")
    check(r.returncode == 0, "答えを渡して続行")
    last = drive(run, "awaiting")
    st = run.state()
    check(last["status"] == "converged", f"答えの後に収束（{last['status']}）")
    r3 = run.round_file(3)
    check(r3["materials"]["main_path_observation"]["status"] == "clean" and any(q["status"] == "resolved" for q in r3["questions"]), "3 周目に観測して問いは resolved")
    check(any("config/dev.local.example" in (a.get("note") or "") for a in run.record()["process"]["human_answers"]), "人の答えが記録に残り次の周の judge に渡る")
    rm(run.tmp)


def test_runaway():
    print("台本: 毎周新しい [block] → 上限 5 で停止")
    run = Run("runaway", unattended=True)
    last = drive(run, "runaway")
    check(last["status"] == "stopped" and run.state()["round"] == 5, f"5 周で停止（{run.state()['round']}）")
    check("暴走ガード" in run.record()["process"].get("stop_reason", "") or run.state()["loop"].get("stop_reason") == "max_rounds", "停止の理由が上限")
    rm(run.tmp)


def test_rejections():
    print("否定検査: engine と rules が受け付けないもの")
    run = Run("neg")
    nx = run.next()
    by = {i["node"]: i for i in nx["ready"]}
    t = answers(run, "std", 1)
    r = run.done(by["p0.base"]["id"], {**t["p0.base"](None), "base_sha": "deadbeef"})
    check(r.returncode == 1 and "コミットでない" in r.stderr, "実在しない BASE は exit 1")
    for n in ("p0.base", "p0.local_checks", "p0.premises"):
        run.done(by[n]["id"], t[n](None))
    nx = run.next()
    by = {i["node"]: i for i in nx["ready"]}
    check("p0.prior_decisions" in by and "p1.worktree_before" not in by, "機械の節（作業ツリーの写し）は ready に出ない")
    check(run.record_cli() == run.record(), "loop.py record は record.json の丸写し（直読みと同じ値。CLI の煙テストはここ 1 か所）")
    for n in ("p0.purpose", "p0.parallel_pr", "p0.prior_decisions"):
        run.done(by[n]["id"], t[n](None))
    nx = run.next()
    by = {i["node"]: i for i in nx["ready"]}
    check({"p1.local_review", "p1.consistency_bypass", "p1.hygiene", "p1.external_standards", "p1.provenance"} <= set(by), f"P1 の役が同じ波に並ぶ: {sorted(by)}")
    # 今の周に走った節の素材が『前の周の流用』を名乗る——流用は走らなかった節に機械が書く（not_applicable の 1 値だけ
    # 塞いでいたとき carried_over で同じ穴が通り、検証器 exit 0 で converged した。実測 2026-09-13）
    r = run.done(by["p1.provenance"]["id"], {"material": M("carried_over", from_round=1, reason="確認: 前の周の流用（検査用の嘘）"), "claims": []})
    check(r.returncode == 1 and "carried_over" in r.stderr, f"今の周に走った節の素材が carried_over を名乗ると exit 1（rc={r.returncode}）")
    hyg = next(i for i in nx["ready"] if i["node"] == "p1.hygiene")
    body = pathlib.Path(hyg["prompt_file"]).read_text(encoding="utf-8")
    check("## コード衛生観点" in body and "diff --git a/src/b.py" in body and "上限を付けて" not in body, "cold-reader には観点の節と差分本文だけが貼られ、目的は貼られない")
    r = run.done(by["p1.local_review"]["id"], {**t["p1.local_review"](None), "material": {"status": "found"}})
    check(r.returncode == 1 and "count" in r.stderr, "found なのに count が無い素材は exit 1（検証器の表で先に見る）")
    # investigator の前後で作業ツリーが変わると、その instance の done を拒む
    (run.repo / "stray.txt").write_text("x", encoding="utf-8")
    r = run.done(by["p1.external_standards"]["id"], t["p1.external_standards"](None))
    check(r.returncode == 1 and "作業ツリーが変わっている" in r.stderr, "investigator の instance の前後で作業ツリーが変わると exit 1")
    (run.repo / "stray.txt").unlink()
    for n in ("p1.local_review", "p1.consistency_bypass", "p1.external_standards", "p1.provenance"):
        r = run.done(by[n]["id"], t[n](None))
        if r.returncode != 0:  # assert は -O で消える（台本の前提が黙って外れる）
            raise SystemExit(f"台本の前提が崩れた: {n} の done が {r.returncode}: {r.stderr[-200:]}")
    r = run.done(hyg["id"], t["p1.hygiene"](None), agent_id="cli-has-no-agent")
    check(r.returncode == 1 and "agent_id" in r.stderr, "cli で起こした遮断系の done に --agent-id を渡すと exit 1（別プロセスに続く context は無い）")
    r = run.done(hyg["id"], t["p1.hygiene"](None))
    if r.returncode != 0:
        raise SystemExit(f"台本の前提が崩れた: done が {r.returncode}: {r.stderr[-200:]}")
    # 既に ' M' のファイルの**中身の差し替え**も止める（porcelain は状態コードとパスしか見ないので diff の sha で見る）
    orig = (run.repo / "src" / "a.py").read_text(encoding="utf-8")
    (run.repo / "src" / "a.py").write_text(orig + "# 役が書き換えた\n", encoding="utf-8")
    nx = run.next()
    check(not nx["ready"] and any("diff_sha" in n for n in nx["notes"]), f"既に変更済みのファイルの中身を差し替えても止まる: {str(nx.get('notes'))[:120]}")
    (run.repo / "src" / "a.py").write_text(orig, encoding="utf-8")
    # P1 を抜ける時点の作業ツリー突合（機械の節）も汚れを止める
    (run.repo / "stray.txt").write_text("x", encoding="utf-8")
    nx = run.next()
    check(not nx["ready"] and any("作業ツリーが変わっている" in n for n in nx["notes"]), "P1 の前後で作業ツリーが変わると先へ進まない")
    gm0 = len(run.state().get("git_mismatches", []))
    run.next()  # 同じ止まり方でもう一度叩く
    check(len(run.state().get("git_mismatches", [])) == gm0, "同じ止まり方で next を叩き直しても git_mismatches は増えない")
    # stray.txt は残したまま——下で writer の変更として受け付ける
    # git が効かない場では突合そのものができない——『一致』に倒さず止まる
    (run.tmp / "empty-bin").mkdir()
    r = run.cmd("next", env={**os.environ, "PATH": str(run.tmp / "empty-bin")})
    nx = json.loads(r.stdout) if r.returncode == 0 and r.stdout.strip().startswith("{") else {"ready": ["?"], "notes": [r.stderr]}
    check(not nx["ready"] and any("取れない" in n and "突き合わせられない" in n for n in nx["notes"]), "git が無い場では P1 の前後の突合が『測れない』で止まる（一致に倒さない）")
    # writer 自身の変更（engine をその場で直した等）は、done と同じく理由を添えて通せる——痕跡は git_mismatches に
    # accepted。stash で退避しても stash の一覧が突合に入るので通らない。通す道が無いと engine を直しながら回す
    # run はここで永久に止まる（実測 2026-09-12: 同じ note を返す next が 10 回続いた）
    r = run.cmd("next", "--accept-tree-change", "writer の変更（検査用）")
    nx = json.loads(r.stdout) if r.returncode == 0 and r.stdout.strip().startswith("{") else {"ready": [], "notes": [r.stderr]}
    check(r.returncode == 0 and not any("作業ツリーが変わっている" in n for n in nx.get("notes", [])), f"自分の変更なら next --accept-tree-change で通る: {str(nx.get('notes'))[:120]}")
    gm = run.state().get("git_mismatches", [])
    check(bool(gm) and gm[-1].get("accepted") == "writer の変更（検査用）" and gm[-1].get("where") == "P1", "受け付けた理由が git_mismatches に残る")
    (run.repo / "stray.txt").unlink()
    nx = run.next()
    jd = next(i for i in nx["ready"] if i["node"] == "p2.diagnose")
    check(jd["mode"] == "agent" and "fix_closure" in json.dumps(run.record()["materials"]), "受け付ければ judge に進み、素材は 15 欄で渡る")
    bad = {**t["p2.diagnose"](None), "questions": [{"key": "q", "kind": "fork", "status": "held", "reason": "r", "origin": "無いユニット", "options": ["a", "b"]}]}
    r = run.done(jd["id"], bad)
    check(r.returncode == 1 and "units にも defer 台帳にも無い" in r.stderr, "台帳の出どころが無い judge の返答は exit 1")
    bad = {**t["p2.diagnose"](None), "questions": [{"key": "q", "kind": "split", "status": "held", "reason": "r", "origin": "src/a.py:f — 上限が効かない経路がある"}]}
    r = run.done(jd["id"], bad)
    check(r.returncode == 1 and "人に聞く前に直す義務" in r.stderr, "split の出どころが [block] の返答は exit 1")
    good = t["p2.diagnose"](None)
    r = run.done(jd["id"], {**good, "units": [{**good["units"][0], "label": "blocker"}]})
    check(r.returncode == 1 and "型に合わない" in r.stderr, "judge の label が語彙外（blocker）なら exit 1")
    r = run.done(jd["id"], {**good, "questions": [{"key": "q", "kind": "whatever", "status": "held", "reason": "r", "origin": good["units"][0]["key"]}]})
    check(r.returncode == 1 and "型に合わない" in r.stderr, "台帳の kind が語彙外なら exit 1")
    r = run.done(jd["id"], {**good, "units": [{**good["units"][0], "disposition": "later"}]})
    check(r.returncode == 1 and "型に合わない" in r.stderr, "disposition が語彙外なら exit 1")
    r = run.done(jd["id"], {**good, "questions": [{"key": "q", "kind": "fork", "status": "maybe", "reason": "r", "origin": good["units"][0]["key"], "options": ["a", "b"]}]})
    check(r.returncode == 1 and "型に合わない" in r.stderr, "台帳の status が語彙外なら exit 1")
    r = run.done(jd["id"], {**good, "verdict": "pass"})
    check(r.returncode == 1 and "型に合わない" in r.stderr, "judge の返答に知らない欄があれば exit 1（additionalProperties）")
    r = run.done(jd["id"], {**good, "units": [{**good["units"][0], "label": "suggest", "disposition": "defer"}]})
    check(r.returncode == 1 and "defer" in r.stderr, "defer に reason の無い judge の返答は exit 1（以前の台本は defer を一度も返さず、この腕を観測できなかった）")
    # 覆いの母数——今の周に直す単位（[block] / do-now）は「同じ形を全部引ける機械の問い」を持て。
    # 名指しの 1 site だけを塞ぐ閉じ方が 3 周続いた（実測 2026-09-13）
    r = run.done(jd["id"], {**good, "one_shot_closes": []})
    check(r.returncode == 1 and "one_shot_closes" in r.stderr, "一撃が閉じると見込む unit を名指ししない judge の返答は exit 1（効かなかったことを次の周が言えない）")
    r = run.done(jd["id"], {**good, "one_shot_closes": ["存在しないユニット"]})
    check(r.returncode == 1 and "units に無い key" in r.stderr, "one_shot_closes が今の周の units に無い key を指すと exit 1")
    nocq = {k: v for k, v in good["units"][0].items() if k != "class_query"}
    r = run.done(jd["id"], {**good, "units": [nocq]})
    check(r.returncode == 1 and "class_query" in r.stderr, "[block] に class_query（母数の問い）が無い judge の返答は exit 1")
    r = run.done(jd["id"], {**good, "units": [{**good["units"][0], "class_query": {"how": "grep ...", "total": True}}]})
    check(r.returncode == 1 and "型に合わない" in r.stderr, "class_query.total が数でなければ exit 1")
    # defer の単位には母数を求めない（今の周に直さないので問いが立たない）。**正しい返答で確かめると節が done になり
    # 後続の腕が撃てない**ので、別の理由（key の重複）で赤くして「class_query では赤くなっていない」ことを見る
    defer_only = {**nocq, "label": "suggest", "disposition": "defer", "reason": "共有面に及ぶ（検査用）"}
    r = run.done(jd["id"], {**good, "units": [defer_only, defer_only], "questions": []})
    check(r.returncode == 1 and "重複" in r.stderr and "class_query" not in r.stderr,
          f"defer の単位には母数を求めない（赤の理由は key の重複だけ。{r.stderr.strip()[-80:]}）")
    # 置き場に古い返答が残っていても、標準入力で渡した新しい返答が勝つ（以前は置き場が先に読まれ、古い方が黙って記録に入った）
    pathlib.Path(jd["out_path"]).parent.mkdir(parents=True, exist_ok=True)
    pathlib.Path(jd["out_path"]).write_text(json.dumps({**good, "framing": "STALE"}, ensure_ascii=False), encoding="utf-8")
    # 標準入力はバイトで読んで UTF-8 に決める——OS 既定の文字コード（Windows の cp1252）で復号すると日本語が JSON にならない。
    # PYTHONIOENCODING で cp1252 を強いて、3 OS のどこで走っても同じ入力で固定する（実測 2026-09-13: windows-latest だけ赤だった）
    r = run.cmd("done", "--node", jd["id"], "--stdin", "--agent-id", "judge-1", input=json.dumps({**good, "framing": "FRESH"}, ensure_ascii=False),
                env={**os.environ, "PYTHONIOENCODING": "cp1252"})
    check(r.returncode == 0 and "読んだ先: stdin" in r.stdout, f"正しい judge の返答は通り、どこから読んだかが返事に残る（stdin を cp1252 の環境で。rc={r.returncode} {(r.stdout + r.stderr).strip()[:160]}）")
    check(json.loads(pathlib.Path(jd["out_path"]).read_text(encoding="utf-8")).get("framing") == "FRESH", "標準入力の返答が置き場の古い返答より優先され、記録に入るのは新しい方")
    nx = run.next()
    fx = next(i for i in nx["ready"] if i["node"] == "p3.fix")
    r = run.done(fx["id"], {**t["p3.fix"](None), "changes": [], "not_done": [{"unit_key": "src/a.py:f — 上限が効かない経路がある", "why": "面倒"}]})
    check(r.returncode == 1 and "直していない" in r.stderr, "[block] を直さない writer の返答は exit 1")
    # 閉鎖の実証は自己申告——「赤を一度も見ていないのに clean」だけは機械が検算できるので拒む
    fix = answers(run, "std", nx["round"])["p3.fix"](None)
    nored = {**fix, "changes": [{**c, "closure": {**c["closure"], "sites": [{"site": s["site"], "red_seen": False} for s in c["closure"]["sites"]]}} for c in fix["changes"]]}
    r = run.done(fx["id"], nored)
    check(bool(fix["changes"]) and r.returncode == 1 and "赤を一度も見ていない" in r.stderr, f"閉鎖の実証で赤を見ていないのに fix_closure=clean の返答は exit 1（rc={r.returncode}）")
    r = run.done(fx["id"], {**fix, "fix_closure": M("not_applicable", reason="条件に当たらない（検査用の嘘）")})
    check(r.returncode == 1 and "not_applicable" in r.stderr, "修正が在るのに fix_closure=not_applicable の返答は exit 1（changes が非空という機械の事実と食い違う）")
    # 修正どうしの干渉——面の一覧は機械が changes[].files から出すので、書き落としは申告でなく突合で落ちる
    r = run.done(fx["id"], {**fix, "interactions": []})
    check(r.returncode == 1 and "interactions に無い" in r.stderr, "2 つ以上の修正が触った面を書き落とすと exit 1（機械が files から面を出す）")
    r = run.done(fx["id"], {**fix, "interactions": [{**fix["interactions"][0], "changes": fix["interactions"][0]["changes"] + ["触っていない修正"]}]})
    check(r.returncode == 1 and "触っていない修正" in r.stderr, "その面を触っていない修正を interactions に混ぜると exit 1")
    r = run.done(fx["id"], {**fix, "interactions": [{**fix["interactions"][0], "checked": "なし"}]})
    check(r.returncode == 1 and "checked が空同然" in r.stderr, "干渉を突き合わせた結果が空同然なら exit 1（bypass_tried と同じ空語検査）")
    # 壊さないか・根本か・破れないか——「修正を外したら赤くなった」は不在の検知であって完全性の証拠にならない
    r = run.done(fx["id"], {**fix, "changes": [{**c, "bypass_tried": "なし"} for c in fix["changes"]]})
    check(r.returncode == 1 and "bypass_tried" in r.stderr, "修正を残したまま破りに行った形跡が無い返答は exit 1")
    r = run.done(fx["id"], {**fix, "changes": [{**c, "breaks": {**c["breaks"], "result": "特になし"}} for c in fix["changes"]]})
    check(r.returncode == 1 and "breaks.result" in r.stderr, "壊しうる面を確かめた結果が空同然なら exit 1")
    r = run.done(fx["id"], {**fix, "changes": [{**c, "root_or_symptom": {"kind": "symptom", "why": "後で"}} for c in fix["changes"]]})
    check(r.returncode == 1 and "症状" in r.stderr, "症状を塞ぐ修正に「なぜ今それで止めるか」が無ければ exit 1")
    # 覆いの母数（coverage）——「1 か所直して終わり」を数字で見えるようにする。残すのは禁じないが黙って残すのは禁じる
    nocov = {**fix, "changes": [{k: v for k, v in c.items() if k != "coverage"} for c in fix["changes"]]}
    r = run.done(fx["id"], nocov)
    check(r.returncode == 1 and "coverage" in r.stderr, "修正に coverage（母数の問いと件数）が無い返答は exit 1")
    part = {**fix, "changes": [{**c, "coverage": {**c["coverage"], "total": 3}} for c in fix["changes"]]}
    r = run.done(fx["id"], part)
    check(r.returncode == 1 and "remaining" in r.stderr, "母数 3 のうち閉鎖を実証した site が 1 件で残りが在るのに remaining が無ければ exit 1")
    over = {**fix, "changes": [{**c, "coverage": {**c["coverage"], "total": 0}} for c in fix["changes"]]}
    r = run.done(fx["id"], over)
    check(r.returncode == 1 and "母数を超えて" in r.stderr, "closure.sites が母数を超える返答は exit 1（問いが対象を取りこぼしている）")
    # 残した理由を書けば部分的な覆いは通る。**正しい返答で確かめると節が done になり後続の腕が撃てない**ので、
    # 別の理由（fix_closure=not_applicable）で赤くして「coverage では赤くなっていない」ことを見る
    withrem = {**fix, "fix_closure": M("not_applicable", reason="検査用の嘘"),
               "changes": [{**c, "coverage": {**c["coverage"], "total": 3, "remaining": "残り 2 件は fork の出どころ（検査用）"}} for c in fix["changes"]]}
    r = run.done(fx["id"], withrem)
    check(r.returncode == 1 and "not_applicable" in r.stderr and "remaining" not in r.stderr,
          f"残した理由を書けば部分的な覆いは通る（赤の理由は fix_closure だけ。{r.stderr.strip()[-70:]}）")
    mixed = {**fix, "changes": [fix["changes"][0], {**fix["changes"][1], "closure": {**fix["changes"][1]["closure"], "sites": [{"site": "docs（赤を見られない）", "red_seen": False}]}}]}
    # 本番の主経路——運び手が out_path に書き、--output も --stdin も付けずに done（台本は --output しか通していなかった）
    pathlib.Path(fx["out_path"]).parent.mkdir(parents=True, exist_ok=True)
    pathlib.Path(fx["out_path"]).write_text(json.dumps(mixed, ensure_ascii=False), encoding="utf-8")
    r = run.cmd("done", "--node", fx["id"])
    check(len(fix["changes"]) >= 2 and r.returncode == 0 and "読んだ先: out_path" in r.stdout,
          f"赤を見た修正と見ていない修正（文書）が混じる周の clean は通る——周の全体で見る。返答は out_path から読む（rc={r.returncode}: {(r.stdout + r.stderr).strip()[-120:]}）")
    rm(run.tmp)


def test_premise_resolved():
    print("台本: R2 が premise-invalid → judge の検算で仮定が偽 → 実測を制約に足し、次の周で R2 を回し直す（止めない）")
    run = Run("premise-resolved")
    last = drive(run, "premise_resolved")
    st = run.state()
    check(last["status"] == "converged", f"人に聞かずに続き、収束する（{last['status']}）")
    r1, r2 = run.round_file(1), run.round_file(2)
    check(r1["reviews"]["R2"]["status"] == "premise-invalid" and any(q["kind"] == "premise" and q["status"] == "held" and "仮定は偽" in q["reason"] for q in r1["questions"]), "1 周目: R2 は premise-invalid、台帳の premise は held で検算の実測を理由に持つ（検証器は未決の行を要求する）")
    check(any(i["node"] == "r2.design" for i in st["rounds"][1]["instances"].values()) and r2["reviews"]["R2"]["status"] == "pass", f"2 周目: R2 が回し直され pass（{r2['reviews']['R2']['status']}）")
    check(any(q["kind"] == "premise" and q["status"] == "resolved" for q in r2["questions"]), "2 周目: judge が回し直した R2 を見て premise を resolved に確定")
    cons = run.record()["process"].get("constraints", [])
    check(any("上限を持たない" in c["text"] and c["kind"] == "実測" for c in cons), "検算の実測が制約に足されている（facts_to_add の行き先）")
    # 強制再発火の旗は使ったら消える——以前は条件式の最右に pop を置いていたので、周 2 で機構が変わる（左が真）と
    # 短絡で pop に届かず、周 3（何も変わらない）でも R2 を回し直した
    check("r2_refire_forced" not in st.get("loop", {}), "強制再発火の旗は周 2 で消費される（機構の変化で短絡しても残らない）")
    r3 = run.round_file(3)
    check(r3["reviews"]["R2"]["status"] == "carried_over", f"3 周目: 何も変わらないので R2 は持ち越し（{r3['reviews']['R2']['status']}）")
    rm(run.tmp)


def test_noci():
    print("台本: CI を確かめていない周（local_checks が not_applicable）は収束を名乗らず諮る——無人なら停止")
    run = Run("noci", unattended=True)
    last = drive(run, "noci")
    proc = run.record()["process"]
    asked = [a for h in proc.get("human_items", []) for a in (h.get("asked") or [])]
    check(last["status"] == "stopped" and any("local_checks" in a for a in asked), f"無人: converged でなく stopped、要人間判断に CI 未確認が載る（{last['status']}: {asked[:1]}）")
    check(proc.get("outcome") != "converged", f"記録の outcome が converged でない（{proc.get('outcome')}）")
    rm(run.tmp)
    run = Run("noci-attended")
    last = drive(run, "noci")
    check(last["status"] == "awaiting_human" and "ci_unverified" in json.dumps(last.get("ask", {})), f"有人: awaiting_human で kinds に ci_unverified（{last['status']}）")
    n0 = len(run.state()["rounds"][-1]["instances"])
    run.next()
    nx3 = run.next()
    check(nx3["status"] == "awaiting_human" and len(run.state()["rounds"][-1]["instances"]) == n0, "人に聞いている間は next を叩いても先へ進まず、新しい節も出ない（以前は advance が先に走り report.human_items が出た）")
    rm(run.tmp)


def test_coldfail():
    print("台本: 初見検査が非 pass でも報告は出る（門ではない）が、verdict と件数は記録の process.cold_check に残る")
    run = Run("coldfail", unattended=True)
    drive(run, "coldfail")
    proc = run.record()["process"]
    cc = proc.get("cold_check") or {}
    check(cc.get("verdict") == "redesign-needed" and cc.get("stops") == 1, f"process.cold_check に非 pass と件数が残る（{cc}）")
    check((run.dir / "report.md").is_file(), "報告は出る（詰まりを直したかは writer の申告——機械は見ない）")
    rm(run.tmp)


def test_gates_not_applicable():
    print("否定検査: ゲートを触った差分（applies_cond が真）で gate_efficacy が not_applicable を名乗ると exit 1")
    run = Run("gates", unattended=True)
    seen = {}

    def hook(run_, inst, out):
        if inst["node"] == "p1.gate_efficacy" and "tried" not in seen:
            seen["tried"] = True
            r = run_.done(inst["id"], {"material": M("not_applicable", reason="検証ゲートを触っていない（検査用の嘘）"),
                                       "arms": [{"gate": "x", "arm": "y", "red_confirmed": True, "control_green": True, "hit_evidence": "分岐が書く理由文字列を一意の印に替えた写しで、印が記録に出ることを確認した"}]})
            check(r.returncode == 1 and "applies_cond" in r.stderr, "applies_cond が真で走った gate_efficacy の not_applicable は exit 1（機械が持つ事実と食い違う）")
            # 赤を見ていない腕が在るのに found 以外を名乗る——clean だけ見ていたとき carried_over は腕ゼロのまま通った（実測 2026-09-13）
            unred = [{"gate": "x", "arm": "y", "red_confirmed": False, "control_green": True, "hit_evidence": "分岐が書く理由文字列を一意の印に替えた写しで、印が記録に出ることを確認した"}]
            r = run_.done(inst["id"], {"material": CLEAN("柵 1 本"), "arms": unred})
            check(r.returncode == 1 and "赤を見ていない腕" in r.stderr, "赤を見ていない腕が在るのに clean は exit 1")
            r = run_.done(inst["id"], {"material": M("carried_over", from_round=1, reason="確認: 流用（検査用の嘘）"), "arms": unred})
            check(r.returncode == 1 and "赤を見ていない腕" in r.stderr, "赤を見ていない腕が在るのに carried_over も exit 1（status に依らず当てる）")
            # **赤は「柵が無ければ落ちる」ことしか言わない。** その腕がその柵を通ったことは別に測る（実測 2026-09-13:
            # 持ち越しの可否の柵は退行を注入しても検査が緑のままで、分岐が書く理由を一意の印に替えても記録に印が出なかった
            # ＝筋書きがその行を通っていない）。赤と control の緑がそろっていても、通った証拠が無ければ覆いに数えない
            nohit = [{"gate": "x", "arm": "y", "red_confirmed": True, "control_green": True, "hit_evidence": "—"}]
            r = run_.done(inst["id"], {"material": CLEAN("柵 1 本"), "arms": nohit})
            check(r.returncode == 1 and "守る行を通ったこと" in r.stderr,
                  f"赤も control の緑も見た腕が、守る行を通ったことを測っていなければ exit 1（rc={r.returncode}）")
            r = run_.done(inst["id"], {"material": M("found", count=1, detail="柵 1 本（検査用）"), "arms": nohit})
            check(r.returncode == 1 and "守る行を通ったこと" in r.stderr,
                  "found でも同じ——覆いの証拠にならない腕は status に依らず拒む")
        return out
    drive(run, "gates", hook=hook)
    check("tried" in seen, "ゲートを触った台本で gate_efficacy が走った")
    rm(run.tmp)


def test_narrowed():
    print("台本: writer 自書の目的を inspector が『狭めている』→ R2 は目的を使えない（unverifiable）→ 台帳に載る")
    run = Run("narrowed", unattended=True)
    drive(run, "narrowed")
    r1 = run.round_file(1)
    check(r1["reviews"].get("R2", {}).get("status") == "unverifiable", f"R2 は unverifiable（{r1['reviews'].get('R2')}）——狭められた目的で独立設計を回さない")
    check(any(q["kind"] == "unverifiable" and q["origin"] == "R2" for q in r1["questions"]), "台帳に R2 の unverifiable の行が立つ")
    check(run.record()["process"].get("purpose_review", {}).get("verdict") == "狭めている", "inspector の判定は記録の process.purpose_review に残る（以前は誰も読まなかった）")
    # R2 を走らせない原因は 2 つ（目的不明／狭めている）——bool 1 つに畳んでいたとき、理由文が事実と逆（目的不明）になった
    reason = r1["reviews"]["R2"].get("reason", "")
    check("狭めている" in reason and "目的不明" not in reason, f"R2 の理由は実際の原因（狭めている）を書き、目的不明と混同しない（{reason[:50]}）")
    rm(run.tmp)


def test_claim_mismatch():
    print("台本: P3 が触っていないファイルを申告しても、再発火は engine が測った差分で決まる（申告は照合の片側）")
    run = Run("liar", unattended=True)
    drive(run, "liar")
    r2 = run.round_file(2)
    check(r2["materials"]["provenance"]["status"] == "carried_over",
          f"申告だけで実際に触っていなければ provenance は持ち越し（{r2['materials']['provenance']['status']}）——以前は申告の 1 語で全素材が再発火した")
    mm = run.record()["process"].get("fix_claim_mismatch")
    check(mm == [{"round": 1, "claimed_not_in_diff": ["src/zzz.py"]}], f"申告と差分の食い違いは記録の process に周付きで残る（{mm}）")
    rm(run.tmp)


def test_proxy_to_source():
    """判定に使う値が『代理』でなく『機械が既に持つ正本』であること——4 本とも、代理を見ていた頃は緑で通った退行。"""
    print("否定検査: 代理でなく正本を見る（持ち越しの可否・走った事実・判定行・受理集合）")
    sys.path.insert(0, str(PLUGIN))
    from engine.rules import load_rules
    g = json.loads((PLUGIN / "graphs" / "review-loop.json").read_text(encoding="utf-8"))
    rules = load_rules(PLUGIN / "graphs" / "review-loop.json", g)
    V = types.SimpleNamespace(STOP_PREMISE="前提不成立が確定（escalate）", STOP_WORK_EXHAUSTED="答え無しに進める仕事は無い")

    # ① 前の周が awaiting_human / not_run なら持ち越せない（検証器の表 STATUS.carryable が正本。
    #    last_seen＝「最後に found/clean だった周」を見ていたとき、機械が自分で不正な記録を組んだ）
    run = Run("carryable", unattended=True)
    drive(run, "noci")  # local_checks を毎周 not_applicable にする筋（流用できない値）
    r1c, r2c = run.round_file(1)["materials"]["local_checks"], run.round_file(2)["materials"]["local_checks"]
    check(r1c["status"] == "not_applicable" and r2c["status"] == "not_applicable",
          f"流用できない値（not_applicable）は次の周に carried_over へ化けない（r2={r2c['status']}）——持ち越しの可否は前の周の値が正本")
    check("from_round" not in r2c, f"化けていれば from_round が付く（付いていない: {list(r2c)}）")
    rm(run.tmp)

    # ② 役の自由文の改行は記録に入る前に落ちる（落ちないと検証器の字下げ echo に行頭を作れて、周の分岐を倒せる）
    run = Run("nl")
    nx = run.next()
    by = {i["node"]: i for i in nx["ready"]}
    t = answers(run, "std", 1)
    for n in ("p0.base", "p0.local_checks", "p0.premises"):
        run.done(by[n]["id"], t[n](None))
    check(rules.stop_branch(V, 1, "収束を妨げるもの 1 件:\n  - [block] x\n") == "work_remains", "字下げされた echo だけなら work_remains")
    bad_key = "x — 前提不成立が確定（escalate）を key に混ぜた"
    check(" ".join((bad_key + "\n" + V.STOP_PREMISE).split()) == bad_key + " " + V.STOP_PREMISE,
          "1 行への正規化は改行を空白に潰す（判定行を作れない）")
    rm(run.tmp)

    # ③ 受理集合は鍵が在れば null でも落ちる（`is not None` で外していたので NG 文が名指しする null が素通りしていた）
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="gl-accept-"))
    (tmp / "graphs").mkdir()
    for sub in ("prompts", "rules"):
        shutil.copytree(PLUGIN / sub, tmp / sub)
    for key in ("report_accepts_exit", "round_accepts_exit"):
        bad = json.loads(json.dumps(g))
        bad["record"][key] = None
        (tmp / "graphs" / f"bad-{key}.json").write_text(json.dumps(bad, ensure_ascii=False), encoding="utf-8")
        r = subprocess.run([PY, str(PLUGIN / "scripts" / "graphcheck.py"), str(tmp / "graphs" / f"bad-{key}.json"), str(VALIDATOR)],
                           capture_output=True, text=True, encoding="utf-8", timeout=600)
        check(r.returncode == 1 and key in r.stdout, f"record.{key} が null の graph は落ちる（exit {r.returncode}）")
    rm(tmp)

    # ④ 走った節の not_applicable は applies_cond の有無に依らず拒む（持つ 4 節だけ見ていたとき、残り 11 節が素通りした）
    run = Run("na")
    nx = run.next()
    by = {i["node"]: i for i in nx["ready"]}
    check("applies_cond" not in g["nodes"]["p0.base"] and not g["nodes"]["p0.base"].get("na_self_ok"),
          "p0.base は applies_cond も na_self_ok も持たない（この腕の前提）")
    tn = answers(run, "std", 1)
    r = run.done(by["p0.base"]["id"], {**tn["p0.base"](None), "material": M("not_applicable", reason="条件に当たらない（検査用の嘘）")})
    check(r.returncode == 1 and "走ったのに not_applicable" in r.stderr,
          f"applies_cond を持たない節が走って not_applicable を名乗ると exit 1（rc={r.returncode}: {r.stderr[-90:]}）")
    rm(run.tmp)


def test_rejudge_edge():
    """同じ周の擦り合わせの辺: 異議が立つと開き、上限で第三の目へ移り、確かめずに採る返答は拒む。"""
    print("否定検査: 同じ周の擦り合わせ（往復の口・上限・新しい事実の要求）")
    sys.path.insert(0, str(PLUGIN))
    from engine.rules import load_rules
    g = json.loads((PLUGIN / "graphs" / "review-loop.json").read_text(encoding="utf-8"))
    rules = load_rules(PLUGIN / "graphs" / "review-loop.json", g)
    conds, checks = rules.CONDS, rules.POST_CHECKS

    b = types.SimpleNamespace(round=3, loop_state={})
    check(not conds["rejudge_open"](b) and not conds["rejudge_exhausted"](b),
          "異議が無ければ往復の節は開かない（常設しない）")
    b.loop_state["rejudge_requested"] = {"round": 2, "text": "前の周の異議"}
    check(not conds["rejudge_open"](b), "**前の周の**異議では開かない（同じ周の口であって持ち越しではない）")
    b.loop_state["rejudge_requested"] = {"round": 3, "text": "今の周の異議"}
    check(conds["rejudge_open"](b) and not conds["rejudge_exhausted"](b), "今の周の異議で往復の節が開く")

    # 確かめずに採る／退ける返答は拒む（依頼者の条件 1: 反論は新しい事実を伴うときだけ）
    for bad in ("", "なし", "確認した"):
        try:
            checks["rejudge_output"](b, "p2.rejudge", {"verdict": "採る", "new_facts": bad, "units": []}, None)
            check(False, f"new_facts が空同然（{bad!r}）でも通った")
        except Exception as e:  # rules に差し込まれた Reject は別の module 実体になりうる——型名で見る
            check(type(e).__name__ == "Reject" and "new_facts" in str(e),
                  f"new_facts が空同然（{bad!r}）なら拒む（{type(e).__name__}）")
    check(int(b.loop_state.get("rejudge_rounds") or 0) == 0, "拒まれた返答は往復に数えない")

    # 決着しない返答（一部採る）は異議を降ろさず、往復だけ数える
    checks["rejudge_output"](b, "p2.rejudge", {"verdict": "一部採る", "new_facts": "該当行を自分で読み、片方の根拠だけ現物で確かめられた。もう片方は再現できず争点が残る", "units": []}, None)
    check(b.loop_state["rejudge_rounds"] == 1 and "rejudge_requested" in b.loop_state,
          "決着しない返答は往復を 1 つ数え、異議は降りない")
    for _ in range(2):
        checks["rejudge_output"](b, "p2.rejudge", {"verdict": "一部採る", "new_facts": "同じく現物に当たったが、片方の根拠だけが確かめられ、争点は解けないまま残った", "units": []}, None)
    check(not conds["rejudge_open"](b) and conds["rejudge_exhausted"](b),
          f"上限（{rules.REJUDGE_MAX}）に達すると往復の節は閉じ、第三の目が開く（常設でなくここでだけ立つ）")

    # 決着する返答は異議を降ろす
    b2 = types.SimpleNamespace(round=3, loop_state={"rejudge_requested": {"round": 3, "text": "x"}})
    checks["rejudge_output"](b2, "p2.rejudge", {"verdict": "退ける", "new_facts": "現物に当たって再現を試みたが、回す側が挙げた事実は再現しなかったので退ける", "units": []}, None)
    check("rejudge_requested" not in b2.loop_state and not conds["rejudge_open"](b2),
          "採る／退けるで決着すれば異議は降り、往復の節は閉じる")


def test_stop_branch():
    print("周の分岐: 検証器の判定行だけを見る（台帳の echo に停止文言が載っても分岐が化けない）")
    sys.path.insert(0, str(PLUGIN))
    from engine.rules import load_rules
    rules = load_rules(PLUGIN / "graphs" / "review-loop.json", json.loads((PLUGIN / "graphs" / "review-loop.json").read_text(encoding="utf-8")))
    V = types.SimpleNamespace(STOP_PREMISE="前提不成立が確定（escalate）", STOP_WORK_EXHAUSTED="答え無しに進める仕事は無い")
    echo = "収束を妨げるもの 1 件:\n  - [block] x — judge の key に『前提不成立が確定（escalate）』と書いた\n  - 台帳: 答え無しに進める仕事は無い、と書いた reason\n"
    check(rules.stop_branch(V, 1, echo) == "work_remains", "字下げされた echo の行に停止文言が在っても work_remains（以前は全文の部分一致で premise_escalate に化けた）")
    check(rules.stop_branch(V, 1, echo + V.STOP_PREMISE + "——残る仕事は全てその答えに従属する。\n") == "premise_escalate", "行頭の判定行なら premise_escalate")
    check(rules.stop_branch(V, 1, echo + "残る阻害要因は保留の問いに帰属するものだけ（1 件）——" + V.STOP_WORK_EXHAUSTED + "。\n") == "work_exhausted", "行頭の判定行なら work_exhausted")
    check(rules.stop_branch(V, 0, echo) == "converged", "exit 0 は出力に依らず converged")


def test_ci_red_runaway():
    print("台本: 阻害なしでも CI が毎周赤 → 上限 5 で停止（converged 分岐の早期 return が暴走ガードを飛ばさない）")
    run = Run("cired", unattended=True)
    last = drive(run, "cired")
    check(last["status"] == "stopped" and run.state()["round"] == 5, f"CI が赤のままの run は 5 周で止まる（{last['status']} r{run.state()['round']}）")
    check(run.state()["loop"].get("stop_reason") == "max_rounds", "停止の理由が上限")
    rm(run.tmp)


def test_non_utf8_file():
    print("台本: 対象差分に UTF-8 でないファイルが在っても next は落ちない（git の出力と file: の読みは置換して読む）")
    run = Run("latin", unattended=True, latin=True)
    seen = {}

    def hook(run_, inst, out):
        if inst["node"] == "p1.hygiene" and "body" not in seen:
            seen["body"] = pathlib.Path(inst["prompt_file"]).read_text(encoding="utf-8")
        return out

    last = drive(run, "std", hook=hook)
    check(last["status"] == "converged", f"UTF-8 でないファイルを含む差分でも収束まで通る（{last['status']}）——以前は 2 回目の next が UnicodeDecodeError で exit 2")
    check("src/latin.py" in seen.get("body", "") and "�" in seen.get("body", ""), "UTF-8 でないファイルの差分も置換文字で役に渡る（欠けない）")
    rm(run.tmp)


def test_deferjudge():
    print("台本: judge が defer を返す筋——理由付きは通り、defer 台帳に載る")
    run = Run("defer", unattended=True)
    last = drive(run, "deferjudge")
    proc = run.record()["process"]
    check(last["status"] == "converged" and any("定数の重複" in k for k in proc.get("defer_ledger", {})), f"理由付きの defer は受理され defer_ledger に残る（{last['status']}: {list(proc.get('defer_ledger', {}))[:2]}）")
    rm(run.tmp)


def test_nopurpose():
    print("台本: 目的不明 → 機械が R2 unverifiable と台帳の行を書き、周は進む → 次の周の judge が人へ回す → stop → finalize")
    run = Run("nopurpose")
    last = drive(run, "nopurpose")
    r1 = run.round_file(1)
    check(r1["reviews"]["R2"]["status"] == "unverifiable", "1 周目の R2 は unverifiable（機械が書く）")
    check(any(q["kind"] == "unverifiable" and q["origin"] == "R2" and q["status"] == "held" for q in r1["questions"]), "同じ周の台帳に kind=unverifiable / origin=R2 の行が立つ（judge を出し直さない）")
    check(last["status"] == "awaiting_human" and run.state()["round"] == 2, f"周は詰まらず 2 周目に進み、judge の escalate で人に聞く（{last['status']} r{run.state()['round']}）")
    r = run.cmd("answer", "--text", "stop")
    last = drive(run, "nopurpose")
    check(last["status"] == "stopped" and (run.dir / "report.md").is_file(), "stop で止まり報告は出る")
    r = run.cmd("finalize")
    check(r.returncode == 0, f"止まった run の finalize は exit 0（受理集合 [0, 1] は graph の宣言。stderr: {r.stderr[-80:]}）")
    rm(run.tmp)


def test_big_diff():
    """大きな差分でも hygiene は 1 節のまま、全部を欠けずに受け取る。

    以前はバイト上限で割っていて、**読み手の人数が差分の大きさで決まっていた**（実測: 750 KB の差分が hunk 境界で 23 片に割れた）。
    遮断系を標準入力で受ける CLI 起動に変えたので貼る上限が消え、割る理由も消えた。入り切らなければ
    API が落とすので、割りは安全柵でもない（静かに切る経路だけが事故だった）。
    """
    print("台本: 1 ファイルが大きい差分——hygiene は割らず、全体を 1 人が受け取る")
    run = Run("big", big=True)
    nx = run.next()
    t = answers(run, "std", 1)
    for i in nx["ready"]:
        r = run.done(i["id"], t[i["node"]](i["item"]))
        if r.returncode != 0:
            raise SystemExit(f"台本の前提が崩れた: {i['node']} の done が {r.returncode}: {r.stderr[-300:]}")
    nx = run.next()  # hygiene は差分だけに依存するので P0 の残りと同じ波に出る（pipeline）
    hyg = [i for i in nx["ready"] if i["node"] == "p1.hygiene"]
    check(len(hyg) == 1, f"hygiene は割れず 1 節のまま（{len(hyg)}）")
    check(hyg[0]["mode"] == "cli" and hyg[0].get("launch"), "遮断系なので別プロセスの CLI で起こす")
    body = pathlib.Path(hyg[0]["prompt_file"]).read_text(encoding="utf-8")
    # 先頭と末尾の両方を見る。片方だけだと、切られた本文でも通る
    check(f"ROW_{0:05d}" in body and f"ROW_{BIG_ROWS - 1:05d}" in body,
          f"差分の先頭行と末尾行が両方入っている（切られていない。{len(body.encode('utf-8'))} バイト）")
    check(len(body.encode("utf-8")) > 150_000, f"旧上限 40,000 バイトを大きく超える本文がそのまま渡る（{len(body.encode('utf-8'))} バイト）")
    check("@@ " in body, "hunk の見出しが残る（役が何行目かを言える）")
    check("日本語" in body, "日本語主体のファイルも入っている（字数とバイト数がずれる入力で切れない）")
    st_size = (run.dir / "state.json").stat().st_size
    check(st_size < 200000, f"state.json は差分を複製しない（{st_size} バイト）")
    rm(run.tmp)


def main():
    # simulate.py と同じ 1 行。find_plugin_path は <PLUGIN>_ROOT を同梱より先に見るので、この環境変数が
    # 立っている機械では、落としていない側の台本だけが別の場所の検証器・役定義を掴む（片方だけ揃っていた）
    os.environ.pop("CONVERGENCE_LOOPS_ROOT", None)
    # 一時ディレクトリ（git リポジトリを含む）は各検査の末尾で消すが、例外で抜けた周回はそこへ届かない。
    # 走らせる側で後始末を保証する——確保は Run.__init__ の中で暗黙に起き、解放は呼び出し側の平文に在る非対称
    import tempfile as _t
    # **消すのは自分が作った作業場だけ。** 接頭辞で列挙して差分を消していたとき、実行中に他プロセスが作った
    # 作業場が差分に入り、そのプロセスの盤面が走行中に消えた（実測 2026-09-13: 退行注入と baseline が
    # 互いを殺し、落ちた台本が毎回違った）。Run が自分の tmp を持っているので、それを集めて消す
    try:
        test_rejections()
        test_new_guards()
        test_empty_text_reply()
        test_converges()
        test_premise()
        test_awaiting()
        test_runaway()
        test_premise_resolved()
        test_noci()
        test_coldfail()
        test_deferjudge()
        test_gates_not_applicable()
        test_narrowed()
        test_claim_mismatch()
        test_proxy_to_source()
        test_rejudge_edge()
        test_stop_branch()
        test_ci_red_runaway()
        test_non_utf8_file()
        test_nopurpose()
        test_big_diff()
    finally:
        for _d in sorted(MADE):
            rm(_d)
    print(f"\n{ran} 件中 {len(fails)} 件失敗")
    if ran == 0:  # 台本が 1 本も走らないと「0 件中 0 件失敗」が緑に見える——母数 0 は赤
        print("  - 検査が 1 件も走っていない")
        sys.exit(1)
    if fails:
        for f in fails:
            print("  - " + f)
        sys.exit(1)


if __name__ == "__main__":
    main()
