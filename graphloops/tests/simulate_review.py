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

HERE = pathlib.Path(__file__).resolve().parent
PLUGIN = HERE.parent
LOOP = PLUGIN / "scripts" / "loop.py"
VALIDATOR = PLUGIN.parent / "scripts" / "review-record.py"
PY = sys.executable
fails, ran = [], 0


def check(cond, desc):
    global ran
    ran += 1
    print(("  ok   " if cond else "  FAIL ") + desc)
    if not cond:
        fails.append(desc)


def sh(cwd, *args):
    return subprocess.run(args, cwd=cwd, capture_output=True, text=True, encoding="utf-8")


class Run:
    def __init__(self, name, unattended=False, big=False):
        self.tmp = pathlib.Path(tempfile.mkdtemp(prefix=f"gl-review-{name}-"))
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
        if big:  # 1 ファイル・1 hunk で差分の塊の上限（FILE_CHUNK）を大きく超える（実走で 186 KB が 1 塊のまま返った形）
            (self.repo / "src" / "big.py").write_text("".join(f"ROW_{i:05d} = {i}  # generated padding line for a long single hunk\n" for i in range(2500)), encoding="utf-8")
            # 日本語主体のファイルも足す——字数で割ると同じ字数がおよそ 3 倍のバイトになり、貼る先の上限を超える
            (self.repo / "docs.md").write_text("".join(f"- {i:05d} 行目。ここは日本語の説明で、字数とバイト数が一致しない入力を主経路に与えるためにある。\n" for i in range(900)), encoding="utf-8")
        g("add", "."); g("commit", "-q", "-m", "change under review")
        self.dir = self.tmp / "state"
        args = ["init", "--loop", "review-loop", "--request", "この変更をレビュー", "--dir", str(self.dir), "--validator", str(VALIDATOR)]
        if unattended:
            args.append("--unattended")
        self.init = self.cmd(*args)

    def cmd(self, *args, env=None):
        extra = [] if args[0] == "init" else ["--dir", str(self.dir)]
        return subprocess.run([PY, str(LOOP), *args, *extra], cwd=self.repo, capture_output=True, text=True, encoding="utf-8", env=env)

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
    unit_block = {"key": "src/a.py:f — 上限が効かない経路がある", "label": "block"}
    unit_donow = {"key": "src/b.py:g — 定数の重複", "label": "suggest", "disposition": "do-now"}
    rec = run.record()
    prev_q = run.state().get("loop", {}).get("prev_questions", [])

    def units_for(rnd):
        if blocks_forever:
            return [{"key": f"src/a.py:f — 周 {rnd} に見つかった新しい欠陥", "label": "block"}]
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
        return {"units": units_for(rnd), "questions": questions_for(rnd), "framing": "根本は上限の欠落", "one_shot": "上限を 1 箇所に寄せる",
                "materials_missing": [], "router": [{"key": unit_block["key"], "route": "②閉じた", "note": "grep で確認"}] if rnd > 1 else []}

    awaiting_mp = scenario == "awaiting" and rnd < 3
    return {
        "p0.base": lambda it: {"base_sha": base, "method": "3 HEAD~1", "commits": 1, "merge_commit": False, "intent_to_add": [],
                               "touches_gates": False, "touches_external_seams": False, "touches_user_path": scenario == "awaiting",
                               "material": CLEAN(f"HEAD~1 で決めた。BASE={base[:7]}。対象差分は 1 コミット分")},
        "p0.local_checks": lambda it: {"material": CLEAN("python -m pytest（緑）")},
        "p0.premises": lambda it: {"constraints": [{"text": "呼び出し元は 1 箇所", "measured_how": "grep -c 'f(' src/",
                                                    "measured_output": "src/a.py:1", "kind": "実測"}]},
        "p0.purpose": lambda it: ({"purpose_text": "（PR 説明も計画も無く目的を取れない）", "source": "目的不明", "known_weaknesses": []} if scenario == "nopurpose" else
                                  {"purpose_text": "f に上限を付けて過大な値を抑える", "source": "①PR 説明", "known_weaknesses": []}),
        "p0.parallel_pr": lambda it: {"material": CLEAN("gh pr list 0 件（打ち切りなし）"), "repo": "t/demo", "listed": 0, "truncated": False, "conflicts": []},
        "p0.prior_decisions": lambda it: {"material": CLEAN("docs/ と closed issue を洗った。決着済みなし"), "checked": True, "searched": ["docs/", "gh issue list --state all"], "settled": []},
        "p1.local_review": lambda it: {"material": M("found", count=1, detail="review-pr: 上限の分岐が片方だけ") if rnd == 1 and not blocks_forever else CLEAN("review-pr・/simplify 再実行。新規なし"),
                                       "findings": [{"skill": "review-pr", "items": [{"where": "src/a.py", "text": "上限が片方の分岐だけ"}]}] if rnd == 1 else [], "simplify_carried": rnd > 1},
        "p1.consistency_bypass": lambda it: {"consistency": CLEAN("命名と設定の追従を Grep で突合"), "bypass": CLEAN("翻訳関数・共有ユーティリティの迂回なし"), "findings": [], "bypass_findings": [], "seen": "src/ 全部", "unseen": "なし"},
        "p1.hygiene": lambda it: {"chunk": it["key"], "findings": [], "seen": "差分の追加行すべて"},
        "p1.external_standards": lambda it: {"material": CLEAN("依存の組み込み機能と突合。再発明なし"), "findings": [], "seen": "import と宣言済み依存", "unseen": "なし", "web_refetched": True},
        "p1.procedure_trace": lambda it: {"material": CLEAN("手順書と実装の突合。宣言と実装の食い違いなし"), "findings": [], "unmeasured": []},
        "p1.gate_efficacy": lambda it: {"material": CLEAN("新設ゲートの腕ごとに写しの上で退行を注入して赤を確認"),
                                        "arms": [{"gate": "上限の検査", "arm": "limit=None の経路", "red_confirmed": True, "control_green": True}]},
        "p1.test_double_fidelity": lambda it: {"material": M("not_applicable", reason="外部との継ぎ目に触れていない"), "mismatches": []},
        "p1.provenance": lambda it: {"material": CLEAN("事実の主張なし"), "claims": []},
        "p1.main_path_observation": lambda it: {"material": M("awaiting_human", reason="dev サーバが社内認証に繋がず起動しない") if awaiting_mp else CLEAN("人が用意した設定で 1 回動かし値を観測"), "observed": []},
        "p2.diagnose": lambda it: judge(rnd),
        "p2.history": lambda it: judge(rnd),
        "p3.fix": lambda it: {"changes": [{"unit_key": u["key"], "what": "上限を 1 箇所に", "files": ["src/a.py"], "closure": {"mechanism": "分岐で上限が漏れる", "fix_mechanism": "共通経路に寄せた", "verified_how": "退行注入で赤→緑", "sites": [{"site": "src/a.py:f", "red_seen": True}]}} for u in rec["units"]],
                              "not_done": [], "fix_closure": CLEAN("退行を注入して赤→復元して緑") if rec["units"] else M("not_applicable", reason="本ラウンドに修正なし"),
                              "mechanism_changed": False, "premise_drift": False, "deps_changed": False, "procedures_changed": False, "gates_changed": False,
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
    shutil.rmtree(run.tmp)

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
    shutil.rmtree(run.tmp)

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
    shutil.rmtree(run.tmp)

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
    r2 = subprocess.run([PY, str(LOOP), "next", "--dir", str(run.tmp / "s2")], cwd=run.repo, capture_output=True, text=True, encoding="utf-8")
    nxt = subprocess.run([PY, str(LOOP), "next", "--dir", str(run.tmp / "s2")], cwd=run.repo, capture_output=True, text=True, encoding="utf-8")
    check(r.returncode == 0 and ("解決できない" in r2.stderr + nxt.stderr or "解決できない" in r2.stdout), 
          f"解決できない cond の path は die（偽に倒さない）: {(r2.stderr + nxt.stderr)[-120:]}")
    shutil.rmtree(tmp); shutil.rmtree(run.tmp)


def test_empty_text_reply():
    print("否定検査: 本文を返す節の空返答（0 バイトの報告を残さない）")
    run = Run("emptytext")
    seen = {}

    def hook(run_, inst, out):
        if inst["node"] in ("report", "report.human_items") and inst["node"] not in seen:
            seen[inst["node"]] = True
            r = run_.done(inst["id"], "   \n  ")
            check(r.returncode == 1 and "空" in r.stderr, f"{inst['node']}: 空白だけの返答は exit 1")
            r = run_.cmd("done", "--node", inst["id"], "--output", "/dev/null")
            check(r.returncode == 1, f"{inst['node']}: /dev/null も exit 1")
        return out

    drive(run, "std", hook=hook)
    check(len(seen) >= 1 and (run.dir / "report.md").read_text(encoding="utf-8").strip(), "正しい本文なら通り、report.md は空でない")
    shutil.rmtree(run.tmp)


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
    check(r2["materials"]["external_standards"]["status"] in ("carried_over", "clean", "found"), "再発火しない周の素材は carried_over（実際に見た周付き）")
    # 前の周の P3 が触ったファイルを見る素材は持ち越さない（閉じた欠陥が次の周に生き返らない）
    check(r2["materials"]["provenance"]["status"] != "carried_over",
          f"前の周の P3 が src/a.py を直したので provenance は持ち越さず走り直す（{r2['materials']['provenance']['status']}）")
    carried = [n for n, m in r3["materials"].items() if m["status"] == "carried_over"]
    check(all("確認:" in r3["materials"][n]["reason"] for n in carried), f"持ち越しの理由は確かめた対象を書く（{len(carried)} 件）")
    check(r1["reviews"]["R3"]["status"] == "not_applicable" and r2["reviews"]["R3"]["status"] == "pass", "[block] が残る周は R3/R4 not_applicable、0 の周に走る")
    check(r2["reviews"]["R1"]["status"] == "carried_over" and r3["reviews"]["R1"]["from_round"] == 1, "R1 は再発火しない周に持ち越し、連鎖は round 1 を指す")
    v = subprocess.run([PY, str(VALIDATOR), str(run.dir / "rounds")], capture_output=True, text=True)
    check(v.returncode == 0, "検証器がディレクトリで exit 0（連続 2 ラウンド）")
    check((run.dir / "report.md").is_file(), "report.md が保存された")
    inst = st["rounds"][1]["instances"]
    hist = next((i for i in inst.values() if i["node"] == "p2.history"), None)
    check(hist and hist.get("mode") == "agent_continue" and hist.get("agent_id") == "judge-1", "2 周目の履歴の突合は同じ judge を続ける（agent_continue）")
    check(st["rounds"][0]["na"].get("p2.history", "").startswith("cond"), "1 周目に履歴の突合は無い")
    check((run.dir / "diff-r1.patch").is_file() and "src/b.py" in (run.dir / "diff-r1.patch").read_text(encoding="utf-8"), "対象差分は機械が取って置く")
    shutil.rmtree(run.tmp)


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
    shutil.rmtree(run.tmp)


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
    shutil.rmtree(run.tmp)


def test_runaway():
    print("台本: 毎周新しい [block] → 上限 5 で停止")
    run = Run("runaway", unattended=True)
    last = drive(run, "runaway")
    check(last["status"] == "stopped" and run.state()["round"] == 5, f"5 周で停止（{run.state()['round']}）")
    check("暴走ガード" in run.record()["process"].get("stop_reason", "") or run.state()["loop"].get("stop_reason") == "max_rounds", "停止の理由が上限")
    shutil.rmtree(run.tmp)


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
    for n in ("p0.purpose", "p0.parallel_pr", "p0.prior_decisions"):
        run.done(by[n]["id"], t[n](None))
    nx = run.next()
    by = {i["node"]: i for i in nx["ready"]}
    check({"p1.local_review", "p1.consistency_bypass", "p1.hygiene", "p1.external_standards", "p1.provenance"} <= set(by), f"P1 の役が同じ波に並ぶ: {sorted(by)}")
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
        assert r.returncode == 0, (n, r.stderr)
    r = run.done(hyg["id"], t["p1.hygiene"](hyg["item"]))
    assert r.returncode == 0, r.stderr
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
    (run.repo / "stray.txt").unlink()
    # git が効かない場では突合そのものができない——『一致』に倒さず止まる
    (run.tmp / "empty-bin").mkdir()
    r = run.cmd("next", env={**os.environ, "PATH": str(run.tmp / "empty-bin")})
    nx = json.loads(r.stdout) if r.returncode == 0 and r.stdout.strip().startswith("{") else {"ready": ["?"], "notes": [r.stderr]}
    check(not nx["ready"] and any("取れない" in n and "突き合わせられない" in n for n in nx["notes"]), "git が無い場では P1 の前後の突合が『測れない』で止まる（一致に倒さない）")
    nx = run.next()
    jd = next(i for i in nx["ready"] if i["node"] == "p2.diagnose")
    check(jd["mode"] == "agent" and "fix_closure" in json.dumps(run.record()["materials"]), "戻せば judge に進み、素材は 15 欄で渡る")
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
    r = run.done(jd["id"], good, agent_id="judge-1")
    check(r.returncode == 0, "正しい judge の返答は通る")
    nx = run.next()
    fx = next(i for i in nx["ready"] if i["node"] == "p3.fix")
    r = run.done(fx["id"], {**t["p3.fix"](None), "changes": [], "not_done": [{"unit_key": "src/a.py:f — 上限が効かない経路がある", "why": "面倒"}]})
    check(r.returncode == 1 and "直していない" in r.stderr, "[block] を直さない writer の返答は exit 1")
    shutil.rmtree(run.tmp)


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
    shutil.rmtree(run.tmp)


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
    shutil.rmtree(run.tmp)


def test_big_diff():
    print("台本: 1 ファイルが上限を超える差分——hunk と行の境目で割り、instance に本文を抱えない")
    run = Run("big", big=True)
    nx = run.next()
    t = answers(run, "std", 1)
    for i in nx["ready"]:
        r = run.done(i["id"], t[i["node"]](i["item"]))
        assert r.returncode == 0, (i["node"], r.stderr[-300:])
    nx = run.next()  # hygiene は差分だけに依存するので P0 の残りと同じ波に出る（pipeline）
    hyg = [i for i in nx["ready"] if i["node"] == "p1.hygiene"]
    check(len(hyg) >= 3, f"差分は 3 塊以上に割れる（{len(hyg)}）")
    check(all(len(i["item"].get("text", "")) <= 1000 for i in hyg) and all(i["item"].get("of") == len(hyg) for i in hyg), "next の出力と instance の item は長い本文を抱えない（1,000 字を超える text は items/ のファイルだけ）")
    check(all(i["item"]["files"] for i in hyg), "割った塊にも diff --git の見出しが付き、files が空にならない（役が場所を言える）")
    texts = [pathlib.Path(i["prompt_file"]).read_text(encoding="utf-8") for i in hyg]
    check(max(len(t) for t in texts) < 40000 + 20000, f"各塊のプロンプトは上限＋雛形の範囲（最大 {max(len(t) for t in texts)} 字）")
    # **バイトで見る**。字数で割ると日本語の塊が 2〜3 倍のバイトになり、貼る先（Agent の prompt）の上限を超える
    body = [len(t.split("返答はこの JSON Schema")[0].encode("utf-8")) for t in texts]
    check(max(body) <= 40000 + 20000, f"各塊の本文はバイトでも上限の範囲（最大 {max(body)} バイト）")
    check(any("日本語" in t for t in texts), "日本語主体のファイルも塊に入っている（バイトと字数がずれる入力）")
    st_size = (run.dir / "state.json").stat().st_size
    check(st_size < 200000, f"state.json は差分を複製しない（{st_size} バイト）")
    shutil.rmtree(run.tmp)


def main():
    test_rejections()
    test_new_guards()
    test_empty_text_reply()
    test_converges()
    test_premise()
    test_awaiting()
    test_runaway()
    test_premise_resolved()
    test_nopurpose()
    test_big_diff()
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
