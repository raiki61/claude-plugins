#!/usr/bin/env python3
"""review-loop の engine を、役の返答を台本で差し替えて端から端まで回す（役割 agent も LLM も使わない）。

確かめるのは engine・rules・graph の噛み合わせと、周ごとの記録 rounds/round-<N>.json が
convergence-loops の検証器（scripts/review-record.py。ディレクトリ渡し）を通ること——
収束（連続 2 ラウンド）・前提不成立で人へ・保留の問いに帰属して人へ・答えを渡して続行・上限で停止・拒むべき返答の拒否。

使い方: python3 simulate_review.py
"""
import collections
import hashlib
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
import types

import fakeclaude  # 同じディレクトリ。--output-format json の包みを返す代役の claude
import parallel  # 同じディレクトリ。台本を同時に走らせる土台（検査の中身は変えない）

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from engine.advance import load_item  # noqa: E402 — 項目の正本（items/ のファイル）の読み方は engine が持つ
from engine.util import TERMINAL_STATUS  # noqa: E402 — 終端の status は engine が正本（台本で並べ直さない）

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
    # 件数と失敗一覧は台本をまたいで共有される。**`ran += 1` は不可分ではない**ので錠を掛ける
    # ——素で並列にすると数え落とし、件数の柵（run.sh の EXPECTED_CHECKS）が走るたび違う値になる。
    global ran
    with parallel.LOCK:
        ran += 1
        if not cond:
            fails.append(desc)
    parallel.line(("  ok   " if cond else "  FAIL ") + desc)


def rm(p):
    """作業場の掃除。Windows は git の object を読み取り専用で置き、素の rmtree が PermissionError で
    落ちる（実測: CI の windows-latest）。掃除の失敗で検査本体を落とさない。"""
    shutil.rmtree(p, ignore_errors=True)


def sh(cwd, *args):
    return subprocess.run(args, cwd=cwd, capture_output=True, text=True, encoding="utf-8", timeout=120)




# 台本が実際に返した判定語彙（(節, 欄) → 値の集合）。**「台本が 1 値固定」を件数でなく到達で測る。**
# 台本の本数も検査の件数も増え続けていたのに、役が返す値は筋書きに依らず 1 値のままで、直した分岐・
# 非 pass の値・有人の ask を端から端までの経路が 1 度も通っていなかった（実測 2026-09-13: graph の
# 判定語彙 185 値のうち到達は 63 値。p2.rejudge / p2.rejudge_third は 1 値も返っておらず、
# R1 / R3 / R4 の redesign-needed と unverifiable も 1 度も出ていなかった——**その値のための機構を
# 同じ周に足していた**）。件数の柵は「検査が消えた」を見るが、この柵は「筋書きが痩せた」を見る。
VOCAB_SEEN = collections.defaultdict(set)
# 到達した語彙の数。**`!=` で見る**——下限（`<`）だと筋書きを増やしても数が動かず、増やしたつもりの
# 周に誰も気づかない。上げるときは実測値を書く（減らすのは、語彙そのものを graph から消したときだけ）。
VOCAB_REACHED = 116


def record_vocab(node, output):
    """台本が返した値を集める。**既存の検査に相乗りするので、この測定のために 1 回も余計に回さない。**"""
    if not isinstance(output, dict):
        return
    nid = node.split("[")[0]

    def walk(v, p=""):
        if isinstance(v, dict):
            for k, x in v.items():
                walk(x, f"{p}.{k}" if p else k)
        elif isinstance(v, list):
            for x in v:
                walk(x, p + "[]")
        elif isinstance(v, (str, bool)):
            with parallel.LOCK:
                VOCAB_SEEN[(nid, p)].add(v)

    walk(output)


def vocab_coverage():
    """graph が宣言する判定語彙のうち、台本が返したものの数と、返していないものの一覧。"""
    sys.path.insert(0, str(PLUGIN))
    from engine.schema import expand_refs  # noqa: E402 — engine と同じく $ref を展開した形で数える（生の graph では $ref の先の語彙が数えられない）
    g = expand_refs(json.loads((PLUGIN / "graphs" / "review-loop.json").read_text(encoding="utf-8")))
    enums = {}

    sys.path.insert(0, str(PLUGIN))
    from engine.schema import walk_schema as engine_walk  # noqa: E402 — schema の走査は engine の 1 本（patternProperties の下にも降りる）

    def walk_schema(nid, sch):
        for p, s in engine_walk(sch):
            if "enum" in s:
                enums[(nid, p.removeprefix("$").removeprefix("."))] = set(s["enum"])

    # **無作為に引く扇の節は数えない**——引く物が run ごとに変わるので、そこから返る値は台本の性質ではない。
    # research 側で作った正本（rules の RANDOM_FAN）を review 側の測定器も読む。review graph に今 fan_out は
    # 無いので現状の数は変わらないが、扇を足した周に**片側だけラチェットが乱数で揺れる**のを止める
    # （実測 2026-09-14: RANDOM_FAN は research 側 2 か所にしか無く、review 側は 0 件だった）
    sys.path.insert(0, str(PLUGIN))
    from engine.rules import load_rules
    rules = load_rules(PLUGIN / "graphs" / "review-loop.json", g)
    random_fan = set(getattr(rules, "RANDOM_FAN", ()) or ())
    for nid, n in g["nodes"].items():
        if (n.get("fan_out") or {}).get("builtin") in random_fan:
            continue
        if n.get("schema"):
            walk_schema(nid, n["schema"])
    total = sum(len(v) for v in enums.values())
    reached = sum(len(v & VOCAB_SEEN.get(k, set())) for k, v in enums.items())
    unreached = sorted(f"{k[0]}.{k[1]}={v}" for k, vs in enums.items() for v in sorted(vs - VOCAB_SEEN.get(k, set())))
    return reached, total, unreached


class Run:
    def __init__(self, name, unattended=False, big=False, latin=False):
        self._td, self.tmp = parallel.workspace(f"gl-review-{name}-")
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
        record_vocab(node, output)
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


# 宣言したレンズ 7 本の綴り。**graph から引かずに手で書く**——引けば写しは自明に一致し、
# 宣言を増やした周に台本が黙って追従して、「1 本につき 1 行」を数える post_check が空振りする。
# graph の skills を触ったら、ここが赤くなって人が見る。
DECLARED_LENSES = ("/code-review", "pr-review-toolkit:code-reviewer", "/simplify", "/security-review",
                   "pr-review-toolkit:silent-failure-hunter", "pr-review-toolkit:type-design-analyzer",
                   "pr-review-toolkit:pr-test-analyzer")


# 前の周の R1 最小性が挙げる削除候補の綴り。**judge は逐語で写す**——照合の両側が同じ文字列になる形の台本
R1_DELETION = "src/a.py:12-13 の注記（models.py の docstring と同じ事実）"


def local_findings(rnd, drop=(), blank=()):
    """P1 の findings を宣言 7 本ぶん組む。drop の名前は行ごと落とし、blank の名前は items も failed も空にする。"""
    rows = []
    for name in DECLARED_LENSES:
        if name in drop:
            continue
        if name in blank:
            rows.append({"skill": name, "items": []})
        elif name == "/code-review" and rnd == 1:
            rows.append({"skill": name, "items": [{"where": "src/a.py", "text": "上限が片方の分岐だけ"}]})
        elif name == "/security-review":
            rows.append({"skill": name, "items": [], "failed": "認証・データ取扱い・外部 I/O に触れない差分（非該当）"})
        else:
            rows.append({"skill": name, "items": [], "failed": "起こしたが所見なし（差分の追加行すべてを見た）"})
    return rows


PROVEN_ARM = {"gate": "src/a.py", "arm": "上限の分岐", "red_confirmed": True, "control_green": True,
              "hit_evidence": "分岐が書く値を印に替えた写しで、印が出力に現れた（検査用）"}


def answers(run, scenario, rnd):
    """節ごとの返答。scenario と周で分岐する。"""
    base = run.base
    blocks_forever = scenario == "runaway"
    # 今の周に直す単位は覆いの母数（class_query）を持つ——名指しの 1 site だけ塞ぐ閉じ方を機械が止める
    # 問いは engine が走らせ、件数が違えば engine の数に置き換わる——台本の件数は、台本のリポジトリで実際に数えた値にしておく（置き換えの返事が出ない）
    CQ = lambda n=1: {"how": {"patterns": ["limit"], "paths": ["src"], "count": "files"}, "counts": "population", "total": n}
    unit_block = {"key": "src/a.py:f — 上限が効かない経路がある", "label": "block", "class_query": CQ()}  # 母数 1（sites 1 と揃う）
    unit_donow = {"key": "src/b.py:g — 定数の重複", "label": "suggest", "disposition": "do-now", "class_query": CQ(1)}
    rec = run.record()
    prev_q = run.state().get("loop", {}).get("prev_questions", [])

    def units_for(rnd):
        if blocks_forever:
            return [{"key": f"src/a.py:f — 周 {rnd} に見つかった新しい欠陥", "label": "block", "class_query": CQ()}]
        if scenario == "deferjudge" and rnd == 1:  # judge が defer を返す筋（以前の台本は一度も返さず、rules の defer の腕が観測できなかった）
            return [unit_block, {**unit_donow, "disposition": "defer", "reason": "処方が共有面（キャッシュ層）に及ぶ（検査用）"}]
        if scenario in ("forkhold", "forkesc"):
            return [unit_block]          # 同じ出どころを毎周開けたまま置く（免除の期限を見る筋書き）
        if scenario == "entry_reject":
            return []                    # 判定が人の依頼を全部却下する筋（修正 0 行の入口の run が報告まで届くか）
        return [unit_block, unit_donow] if rnd == 1 else []

    def questions_for(rnd):
        if scenario in ("forkhold", "forkesc"):
            # 同じ問いを毎周立て続ける。forkesc は 2 周目で escalate（人に届く形）へ上げる
            st = "escalate" if (scenario == "forkesc" and rnd > 1) else "held"
            return [{"key": "どちらに倒すか（検査用）", "kind": "fork", "status": st,
                     "reason": "人が決める分岐（検査用）", "origin": unit_block["key"], "options": ["a", "b"]}]
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
        us, qs = units_for(rnd), questions_for(rnd)
        # 先行例の行: 今の周に直す単位と、人へ回す問い（fork・escalate）の key ごとに 1 行
        prec = [{"key": u["key"], "problem": "値の上限を 1 か所で掛ける", "source": "https://example.invalid/limit（検査用）",
                 "verdict": "adopt", "reason": "定番の入口 1 か所で掛ける形をそのまま採る"}
                for u in us if u["label"] == "block" or u.get("disposition") == "do-now"]
        prec += [{"key": q["key"], "problem": "人が決める分岐", "source": "https://example.invalid/fork（検査用）", "verdict": "does_not_apply",
                  "reason": "世界の解は両方を許す", "undecided_because": "どちらに倒すかは利用者の運用で決まり、一次情報は決めない（検査用）"}
                 for q in qs if q["kind"] == "fork" or q["status"] == "escalate"]
        return {"units": us, "questions": qs, "precedents": prec, "framing": "根本は上限の欠落", "one_shot": "上限を 1 箇所に寄せる",
                # 一撃は反証可能に——閉じると見込む key を名指しし、次の周が測る問いを添える
                "one_shot_closes": [u["key"] for u in us],
                "materials_missing": [],
                # 前の周の R1 が挙げた削除候補は 1 件につき 1 行。台本の R1 は既定で deletions 空なので、
                # 既定の周は空配列——非空にするのは carryr1 の筋書きだけ（数える口が空振りしないよう分ける）
                "carried_r1": ([{"where": R1_DELETION, "disposition": "promote", "unit_key": us[0]["key"]} if us else
                                {"where": R1_DELETION, "disposition": "decline", "why": "同じ注記は今周の修正で既に消えた"}]
                               if (scenario == "carryr1" and rnd > 1) else []),
                "router": [{"key": unit_block["key"], "route": "②閉じた", "note": "grep で確認"}] if rnd > 1 else []}

    awaiting_mp = scenario == "awaiting" and rnd < 3
    # 修正案と事前審査・修正差分のレビューは、直す単位が在る周にだけ立つ（cond: units_open / fix_delta_nonempty）。
    # planfaces の筋書きだけが穴を挙げる——既定の周は穴 0 で、faces_none に確かめたことを書く
    opened = [u["key"] for u in rec["units"] if u["label"] == "block" or u.get("disposition") == "do-now"]
    faced = scenario == "planfaces"
    plan_rv = (rec["process"].get("plan_review") or {}) if opened else {}   # 走らなかった周の記録には前の周の値が残る
    # 事前審査の別案は残すと宣言する（planfaces）——次の周の p2.history が振り分ける経路を通すため
    # 入口の穴（no_add 付き）も宣言して次の周へ回す——absorbed に数えると差分レビューの検算の筋書きが 2 件に割れる
    face_how = lambda k: ("declared", "別案は次の周に回す（検査用。定数の寄せは別の単位で扱う）") if k.startswith(("別案", "入口: 呼び元が上限を迂回")) else \
        ("absorbed", "上限の値を定数 1 つにし、入口だけが引く形で書いた（検査用）")
    now_fix = [f for f in rec["process"].get("fixes") or [] if f.get("round") == rnd]
    absorbed = [r["key"] for r in (now_fix[-1].get("plan_faces") if now_fix else []) or [] if r["handled"] == "absorbed"]
    fixed_now = [r["key"] for r in rec["process"].get("delta_fix") or [] if r["handled"] == "fixed"] if opened else []
    prev_decl = run.state().get("loop", {}).get("prev_declared_faces") or []
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
        # **指摘は作業ツリーで引ける根拠を連れて来る**（cite を engine が数え直す）。この台本の repo に
        # 実在する字列（src/a.py の limit）を使う——実在しない字列を使う腕は test_purpose_cite が別に測る
        "p0.purpose_review": lambda it: {"verdict": "狭めている" if scenario == "narrowed" else "問題なし",
                                          "reason": "目的が実装した範囲に合わせて狭い（検査用）",
                                          "findings": [{"text": "呼び出し元の上限に触れていない", "cite": "min(x, limit)", "hits": 1}] if scenario == "narrowed" else []},
        "p0.parallel_pr": lambda it: {"material": CLEAN("gh pr list 0 件（打ち切りなし）"), "repo": "t/demo", "listed": 0, "truncated": False, "conflicts": []},
        "p0.prior_decisions": lambda it: {"material": CLEAN("docs/ と closed issue を洗った。決着済みなし"), "checked": True, "searched": ["docs/", "gh issue list --state all"], "settled": []},
        "p1.local_review": lambda it: {"material": M("found", count=1, detail="/code-review: 上限の分岐が片方だけ") if rnd == 1 and not blocks_forever else CLEAN("/code-review・/simplify 再実行。新規なし"),
                                       "findings": local_findings(rnd), "simplify_carried": rnd > 1},
        "p1.consistency_bypass": lambda it: {"consistency": CLEAN("命名と設定の追従を Grep で突合"), "bypass": CLEAN("翻訳関数・共有ユーティリティの迂回なし"), "findings": [], "bypass_findings": [], "seen": "src/ 全部", "unseen": "なし"},
        "p1.hygiene": lambda it: {"findings": [], "seen": "差分の追加行すべて"},
        "p1.external_standards": lambda it: {"material": CLEAN("依存の組み込み機能と突合。再発明なし"), "findings": [], "seen": "import と宣言済み依存", "unseen": "なし", "web_refetched": True, "rankings": [], "rankings_none": "差分に一般化した問題が無い（上限を 1 か所に寄せるだけ。検査用）"},
        "p1.procedure_trace": lambda it: {"material": CLEAN("手順書と実装の突合。宣言と実装の食い違いなし"), "findings": [], "unmeasured": []},
        "p1.gate_efficacy": lambda it: {"material": CLEAN("新設ゲートの腕ごとに写しの上で退行を注入して赤を確認"),
                                        "arms": [{"gate": "上限の検査", "arm": "limit=None の経路", "red_confirmed": True, "control_green": True, "hit_evidence": "分岐が書く理由文字列を一意の印に替えた写しで、印が記録に出ることを確認した"}]},
        "p1.test_double_fidelity": lambda it: {"material": M("not_applicable", reason="外部との継ぎ目に触れていない"), "mismatches": []},
        "p1.provenance": lambda it: {"material": CLEAN("事実の主張なし"), "claims": []},
        "p1.main_path_observation": lambda it: {"material": M("awaiting_human", reason="dev サーバが社内認証に繋がず起動しない") if awaiting_mp else CLEAN("人が用意した設定で 1 回動かし値を観測"), "observed": [] if awaiting_mp else [{"path": "検索 → 結果表示", "value": "上限 100 で 100 件（検査用）"}]},
        "p2.diagnose": lambda it: judge(rnd),
        # 履歴の突合は同じ judge が続けるが節の schema は別——carried_r1 は p2.diagnose だけが持つ欄
        "p2.history": lambda it: {**{k: v for k, v in judge(rnd).items() if k != "carried_r1"}, "reburn_causes": [],
                                  "declared_routed": [{"key": r["key"], "route": "accept", "reason": "残す理由を現物で確かめ、今の周の単位にしない（検査用）"}
                                                      for r in prev_decl]},
        "p3.fix": lambda it: {"changes": [{"unit_key": u["key"], "what": "上限を 1 箇所に", "files": ["src/a.py"], "closure": {"mechanism": "分岐で上限が漏れる", "fix_mechanism": "共通経路に寄せた", "verified_how": "退行注入で赤→緑", "sites": [{"site": "src/a.py:f", "red_seen": True}]},
                                                 "coverage": {"how": {"patterns": ["limit"], "paths": ["src"], "count": "files"}, "counts": "population"},
                                                 "precedent": {"problem": "値の上限を 1 か所で掛ける", "source": "https://example.invalid/limit（検査用）", "verdict": "adopt", "reason": "定番の形をそのまま採った（検査用）"},
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
                              "seams_changed": False, "path_changed": False, "claims_changed": False, "decision_records_changed": False,
                              "wrote_refs": [],
                              # 事前審査の穴と別案に key ごとに 1 行（事前審査が走らなかった周は空）
                              "plan_faces": [{"key": f["key"], "handled": face_how(f["key"])[0], "how": face_how(f["key"])[1]}
                                             for f in (plan_rv.get("faces") or []) + (plan_rv.get("shrink") or [])]},
        "p2.fix_plan": lambda it: {"plan": [{"unit_keys": opened, "approach": "上限を入口の関数 f の 1 か所で掛け、呼び元の分岐を消す（検査用）",
                                             "adds": [{"kind": "guard", "name": "f の上限", "canonical": "src/a.py の f が正本（新設。呼び元には写さない）"}],
                                             "removes": ["呼び元の上限の分岐"],
                                             "shrink_first": "呼び元の分岐を消すだけでは上限が掛からない経路が残るので、入口 1 か所に寄せる（検査用）"}]},
        "p2.plan_review": lambda it: ({"faces": [{"key": "写し: 上限の値を 2 か所に", "unit_keys": opened[:1], "kind": "copy", "where": "src/a.py",
                                                  "why": "上限の値を入口と呼び元の両方に書くと、片方だけ変わる（検査用）", "severity": "block"},
                                                 {"key": "入口: 呼び元が上限を迂回する", "unit_keys": opened[:1], "kind": "entrance", "where": "src/a.py",
                                                  "why": "呼び元の分岐が入口を通らずに値を渡せる（検査用）", "severity": "suggest",
                                                  "no_add": "呼び元の分岐を消して入口 1 本にする（柵は足さない。検査用）"}],
                                       "shrink": [{"key": "別案: 定数を 1 つに", "unit_keys": opened[:1], "alternative": "上限の値を定数 1 つにして両方から引く（検査用）",
                                                   "why": "値の写しそのものが消え、柵を足さずに閉じる（検査用）"}],
                                       "reason": "案の adds 1 件のうち写しになりうる物が 1 件（検査用）"} if faced else
                                      {"faces": [], "shrink": [], "faces_none": "案の adds は正本を持つ 1 件だけで、呼び元の分岐は消す側に在る（検査用）",
                                       "reason": "写しも塞がない入口も予測されない（検査用）"}),
        "p3.delta_review": lambda it: {**({"faces": [{"key": "入口: 呼び元の上限が残る", "kind": "entrance", "where": "src/a.py", "cite": "limit",
                                                      "why": "呼び元の分岐が上限を別に持ったまま残り、入口の上限を迂回できる（検査用）"}]} if faced else
                                          {"faces": [], "faces_none": "修正差分の src/a.py の追加行と呼び元を読み、写し・入口・ずれは無い（検査用）"}),
                                       "checks": [{"key": k, "closed": True, "why": "差分で上限の値が定数 1 つに寄っている（検査用）"} for k in absorbed]},
        "p3.delta_review2": lambda it: {**({"faces": [{"key": "手直しの穴（検査用）", "kind": "copy", "where": "src/a.py", "cite": "limit",
                                                       "why": "手直しが上限の値を呼び元にもう一度書いた（検査用）"}]} if faced else
                                           {"faces": [], "faces_none": "手直しの差分の src/a.py を読み、写し・入口・ずれは無い（検査用）"}),
                                        "checks": [{"key": k, "closed": True, "why": "手直しの差分で呼び元の分岐が消えている（検査用）"} for k in fixed_now]},
        "p3.delta_fix2": lambda it: {"handled": [{"key": "手直しの穴（検査用）", "handled": "fixed", "how": "手直しが呼び元に書いた上限の値を消し、定数だけを引く形に戻した（検査用）", "files": ["src/a.py"]}]
                                     + [{"key": c["key"], "handled": "declared", "how": "手直しで塞がっていなかった穴は次の周の判定に回す（検査用）"}
                                        for c in (rec["process"].get("delta_review2") or {}).get("checks") or [] if c["closed"] is False]},
        "p3.delta_fix": lambda it: {"handled": [{"key": "入口: 呼び元の上限が残る", "handled": "fixed", "how": "呼び元の分岐を消し、入口の上限だけにした（検査用）",
                                                 "files": ["src/a.py"]}]
                                    + [{"key": c["key"], "handled": "declared", "how": "塞がっていなかった写しは次の周の判定に回す（検査用）"}
                                       for c in (rec["process"].get("delta_review") or {}).get("checks") or [] if c["closed"] is False]},
        # 変異の検算の線: 回す側は受領（線の結果の置き場）だけを返して待たない。線の結果は台本が必要な周に置き場へ書く
        "p3.delta_gates": lambda it: {"lane": run.state()["loop"]["gates_cut"]["result"]},
        # 最後の関門: この周に固めた最終の版を撃ち、見逃しは無い（証拠のそろった腕 1 本）
        "p4.final_gates": lambda it: {"rev": run.state()["loop"]["gates_cut"]["rev"], "arms": [PROVEN_ARM], "handled": [], "patch": "",
                                      "suite": {"command": "pytest（検査用）", "exit": 0}},
        "p4.ci": lambda it: {"material": CLEAN("pytest 緑")},
        "p4.scalars": lambda it: {"scalars": {"comment_ratio_pct": 10, "doc_lines": 1}},
        "r1.comment_candidates": lambda it: {"candidates": [], "kept": []},
        # **R の非 pass は筋書きで出す。** 1 値固定にしていたとき、pass しか返らないので持ち越し・台帳の
        # 自動起票・諮りの腕が端から端までの経路で 1 度も通らなかった（実測 2026-09-13: 判定語彙 185 値中
        # 到達 63 値。redesign-needed と unverifiable は R1/R3/R4 とも 0 回）——**その値のための機構を
        # 同じ周に足していた**。R ごとに別の非 pass を返すのは、腕ごとに帰結が違うため（持ち越せる／諮る）。
        "r1.minimality": lambda it: ({"status": "redesign-needed", "reason": "増えた注記が既存の正本の写し（検査用）",
                                      "deletions": [{"where": R1_DELETION, "why": "同じ事実が models.py の docstring に在る"}],
                                      "ledger_audit": [], "increments": []}
                                     if scenario == "carryr1" else
                                     {"status": "redesign-needed", "reason": "台帳に逃げ道がある（検査用）", "deletions": [], "ledger_audit": [], "increments": []}
                                     if scenario == "rnonpass" else
                                     {"status": "pass", "reason": "累積差分は最小。台帳に逃げ道なし", "deletions": [], "ledger_audit": [], "increments": []}),
        "r2.design": lambda it: ({"question_stands": False, "reason": "既存機構で自明", "premise_invalid_reason": "呼び出し元が既に上限を持つ", "design": ""} if (scenario == "premise" or (scenario == "premise_resolved" and rnd == 1)) else
                                 {"question_stands": True, "reason": "問いは立っている", "design": "上限は入口 1 箇所で掛ける"}),
        "r2.compare": lambda it: ({"status": "redesign-needed", "reason": "独立設計と継ぎ目の置き方が違う（検査用）",
                                   "differences": [{"kind": "構造", "text": "上限を入口でなく各呼び出し元に置いている"},
                                                   {"kind": "表現", "text": "語が違うだけの差"}]}
                                  if scenario == "rnonpass" else
                                  {"status": "pass", "reason": "構造は一致", "differences": []}),
        "r3.coherence": lambda it: ({"status": "unverifiable", "reason": "横断の材料が取れない（検査用）"}
                                    if scenario == "rnonpass" else
                                    {"status": "pass", "reason": "横断で揃っている"}),
        "r4.hidden_scope": lambda it: ({"status": "unverifiable", "reason": "基準点の材料が取れない（検査用）", "capability_inventory": {"fired": False}, "surfaced": []}
                                       if scenario == "rnonpass" else
                                       {"status": "pass", "reason": "導入・露呈した横断リスクなし", "capability_inventory": {"fired": False}, "surfaced": []}),
        "stop.premise_check": lambda it: ({"key": "f の上限は既存機構で自明に満たされているか", "assumption": "呼び出し元が上限を持つ", "assumption_false": True, "evidence": "grep f( で 3 箇所中 2 箇所は上限を持たない",
                                           "verdict": "resolved", "reason": "仮定は実態で偽", "resolution": "呼び出し元 3 箇所中 2 箇所は上限を持たない（実測）",
                                           "facts_to_add": ["f の呼び出し元 3 箇所のうち 2 箇所は上限を持たない"]} if scenario == "premise_resolved" else
                                          {"key": "f の上限は既存機構で自明に満たされているか", "assumption": "呼び出し元が上限を持つ", "assumption_false": False, "evidence": "実態では持っていない箇所もあるが目的テキストの内側で閉じている",
                                           "verdict": "escalate", "reason": "人でないと決められない"}),
        # 同じ周の往復。**台本は 1 度も通していなかった**（p2.rejudge / p2.rejudge_third の判定語彙は
        # 12 値とも到達 0 回）——異議は engine の外の会話で起きていて、盤面を通る経路が検査されていなかった
        "p2.rejudge": lambda it: {"verdict": "一部採る", "new_facts": "回す側が挙げた行を自分で読み、片方の根拠だけ現物で確かめられた。もう片方は再現できず争点が残る",
                                  "reason": "片方は現物に当たって確かめた（検査用）",
                                  "units": [{"key": "f に上限が無い", "label": "block", "disposition": "do-now"}]},
        "p2.rejudge_third": lambda it: {"verdict": "退ける", "new_facts": "往復の材料を読み直したが、回す側が挙げた事実は現物で再現しなかった",
                                        "reason": "第三の目として判定した（検査用）",
                                        "units": [{"key": "f に上限が無い", "label": "suggest", "disposition": "defer"}]},
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


def drive(run, scenario, max_steps=120, hook=None, stop_at=None):
    last = None
    for _ in range(max_steps):
        nx = run.next()
        last = nx
        if stop_at and nx["ready"] and stop_at(nx):  # 途中の波を掴みたい腕のため（既定は最後まで回す）
            return nx
        if nx.get("status") == "awaiting_human" or (not nx["ready"] and nx["status"] in TERMINAL_STATUS):
            return nx
        if not nx["ready"]:
            raise RuntimeError("ready が空のまま進まない: " + json.dumps(nx, ensure_ascii=False)[:800])
        table = answers(run, scenario, nx["round"])
        for inst in nx["ready"]:
            out = table[inst["node"]](load_item(inst))
            if hook:
                out = hook(run, inst, out) or out
            if isinstance(out, dict) and "__skip__" in out:   # optional の節を省く腕（loop.py skip）
                r = run.cmd("skip", "--node", inst["id"], "--reason", out["__skip__"])
                if r.returncode != 0:
                    raise RuntimeError(f"skip {inst['id']} が {r.returncode}: {r.stderr[-600:]}")
                continue
            if inst["node"] in ("p3.fix", "p3.delta_fix", "p3.delta_fix2") and isinstance(out, dict):
                # 台本の writer は申告どおりに実際に手を入れる——前の周の P3 が触ったファイルは engine が diff の差から測り、
                # 申告は照合の片側でしかない（申告だけで触らないと測定 0 件＝持ち越しになる）。手直しも同じ（手直しの差分を切り出す）
                rows = out.get("changes", []) + [r for r in out.get("handled", []) if r.get("handled") == "fixed"]
                for f in {f for c in rows for f in c.get("files", [])}:
                    p = run.repo / f
                    if p.is_file():
                        p.write_text(p.read_text(encoding="utf-8") + f"# {'fixed' if inst['node'] == 'p3.fix' else inst['node']} in round {nx['round']}\n", encoding="utf-8")
            r = run.done(inst["id"], out, agent_id="judge-1" if inst["node"] == "p2.diagnose" else None)
            if r.returncode != 0:
                raise RuntimeError(f"done {inst['id']} が {r.returncode}: {r.stderr[-1200:]}")
    raise RuntimeError("max_steps に達した")


# ---------------------------------------------------------------- 検査
def test_launch_tooled_session():
    """道具つきの役（judge）を engine が起こし、受け付けまで済ませ、同じ役を続ける節（p2.history）がその会話の番号で
    --resume すること。拒まれたら同じ会話に出し直させ、起こし直しの理由が盤面に残ること。"""
    print("道具つきの役の起動: judge を launch で起こし、拒否は同じ会話で出し直させ、次の周の履歴の突合は --resume で続ける")
    run = Run("launchtool")
    # 2 周目の判定を engine に起こさせる——同じ周の履歴の突合（p2.history）がその会話を続ける
    nx = drive(run, "std", stop_at=lambda n: n["round"] == 2 and any(i["node"] == "p2.diagnose" for i in n["ready"]))
    inst = next(i for i in nx["ready"] if i["node"] == "p2.diagnose")
    argv = (inst.get("launch") or {}).get("argv") or []

    def after(flag):
        return argv[argv.index(flag) + 1] if flag in argv else None

    check(inst["mode"] == "agent" and after("--setting-sources") == "" and after("--permission-prompts") == "none"
          and after("--permission-mode") == "dontAsk" and after("--tools") == after("--allowedTools") == "Read,Glob,Grep,WebSearch,WebFetch"
          and "--agents" not in argv and pathlib.Path(after("--append-system-prompt-file") or "").is_file(),
          f"judge は道具つきの形で起こす: 設定を読まない・聞く先が無い・定義の道具を先に許す dontAsk・本文は system prompt（{argv[2:]}）")
    bindir = run.tmp / "fakebin"
    bindir.mkdir()
    fakeclaude.install(bindir)
    env = {**os.environ, "PATH": str(bindir) + os.pathsep + os.environ.get("PATH", "")}
    # next が解決した claude を代役に向けるため、この環境で試行を作り直す（relaunch も next と同じく起こす語を組む）
    r = run.cmd("relaunch", "--node", inst["id"], "--reason", "検査: 代役の claude に向ける", env=env)
    check(r.returncode == 0, f"relaunch できる（{r.stderr[-120:]}）")
    ans = run.tmp / "diag.json"
    ans.write_text(json.dumps(answers(run, "std", 2)["p2.diagnose"](None), ensure_ascii=False), encoding="utf-8")
    r = run.cmd("launch", "--node", inst["id"], env={**env, "FAKE_MODE": "bad_then_answer", "FAKE_OUT": str(ans), "FAKE_SESSION": "sess-judge"})
    got = json.loads(r.stdout)["launched"] if r.returncode == 0 else [{}]
    one = next((g for g in got if g.get("node") == "p2.diagnose"), {})
    check(one.get("ok") and one.get("resumes") == 1 and one.get("session_id") == "sess-judge",
          f"散文を返した judge に同じ会話で出し直させ、受け付けまで済ませる（{one.get('why') or r.stderr[-200:]}）")
    st = run.state()
    me = next((i for i in st["rounds"][1]["instances"].values() if i["node"] == "p2.diagnose" and i["status"] == "done"), {})
    check(me.get("session_id") == "sess-judge" and [x.get("kind") for x in me.get("attempt_log", []) if x.get("kind")] == ["resume"],
          f"会話の番号と、出し直させた理由が盤面に残る（{me.get('session_id')} {me.get('attempt_log')}）")
    last = drive(run, "std")
    check(last["status"] == "converged", f"残りは台本どおり回って収束する（{last['status']}）")
    hist = next((i for i in run.state()["rounds"][1]["instances"].values() if i["node"] == "p2.history"), {})
    hargv = (hist.get("launch") or {}).get("argv") or []
    check(hist.get("mode") == "agent_continue" and hist.get("session_id") == "sess-judge"
          and "--resume" in hargv and hargv[hargv.index("--resume") + 1] == "sess-judge",
          f"履歴の突合は、同じ周の判定を起こした会話の番号で --resume する（{hist.get('mode')} {hist.get('session_id')}）")
    rm(run.tmp)


def test_init_resolves_dir():
    """**盤面の綴りは入口で 1 度だけ解決する。** init だけが未解決の綴りで Board を作っていたとき、
    on_init が盤面から組み立てる値（rounds_dir）は相対のまま state に入り、別の cwd から読むと外れる。
    他の全コマンドは resolve_dir を通っているので、この形は init を相対で呼んだ run にしか出ない。"""
    print("入口の綴り: 相対の --dir で init しても、盤面から組み立てた値は絶対で入る")
    run = Run("initresolve")
    d2 = run.tmp / "s-rel"
    rel = os.path.relpath(d2, run.repo)
    check(not os.path.isabs(rel), f"相対の --dir を作れた（{rel}）")
    r = subprocess.run([PY, str(LOOP), "init", "--loop", "review-loop", "--request", "q",
                        "--dir", rel, "--validator", str(VALIDATOR)],
                       cwd=run.repo, capture_output=True, text=True, encoding="utf-8", timeout=600)
    check(r.returncode == 0, f"相対の --dir で init できる（{r.returncode}: {r.stderr[-160:]}）")
    st = json.loads((d2 / "state.json").read_text(encoding="utf-8"))
    built = {k: v for k, v in st["inputs"].items() if k in ("rounds_dir", "cwd") and v}
    check(built and all(os.path.isabs(v) for v in built.values()),
          f"on_init が盤面から組み立てた値は絶対（{built}）")
    rm(run.tmp)


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
    _td_tmp, tmp = parallel.workspace("gl-cond-")
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


def test_prev_fix_faces_scalar():
    """**前の周の修正が作った面を、規模の数値として周ごとに残す。** 判定役が再燃の原因に『前の周の修正』を選んだ
    件数を機械が数える——散文の note に逃がしていた頃は、収束をいちばんよく表す数が記録に残らなかった。"""
    print("再燃の原因: 『前の周の修正』の件数が、その周の記録の scalars に載る")
    run = Run("prevfix")

    def hook(run_, inst, out):
        if inst["node"] == "p2.history" and isinstance(out, dict) and out.get("router") and not seen:
            seen.append(inst["id"])   # 2 周目の 1 回だけ（3 周目は 0 件に戻ることも見る）
            k = out["router"][0]["key"]   # 同じ key を 2 度書いても 1 件と数える
            return {**out, "reburn_causes": [{"key": k, "cause": "前の周の修正", "note": "検査用"},
                                             {"key": k, "cause": "前の周の修正", "note": "検査用（重複）"},
                                             {"key": k + "（別）", "cause": "コード", "note": "原因が別なら数えない"}]}
    seen = []
    drive(run, "std", hook=hook)
    r2 = run.round_file(2)
    check((r2.get("scalars") or {}).get("faces_created_by_prev_fix") == 1,
          f"2 周目の記録に faces_created_by_prev_fix=1 が載る（同じ key の重複は 1 件、原因が『コード』の行は数えない。{r2.get('scalars')}）")
    check("comment_ratio_pct" in (r2.get("scalars") or {}),
          f"p4.scalars の数値は消えずに並ぶ（面の数は足すだけで、置き換えない。{r2.get('scalars')}）")
    r3 = run.round_file(3)
    check((r3.get("scalars") or {}).get("faces_created_by_prev_fix") == 0,
          f"次の周は、その周の判定役の申告どおり 0 に戻る（前の周の値を据え置かない。{r3.get('scalars')}）")
    rm(run.tmp)
    # **p2.history を省いた周は書かない**——outputs() は周を落として最新を返すので、省いた周に前の周の値が複製された
    run = Run("prevfix-skip")
    seen2 = []

    def hook2(run_, inst, out):
        if inst["node"] == "p2.history" and isinstance(out, dict):
            seen2.append(inst["id"])
            if len(seen2) == 1:
                return {**out, "reburn_causes": [{"key": out["router"][0]["key"], "cause": "前の周の修正", "note": "検査用"}]}
            return {"__skip__": "検査用に省く"}
    drive(run, "std", hook=hook2)
    r2, r3 = run.round_file(2), run.round_file(3)
    check((r2.get("scalars") or {}).get("faces_created_by_prev_fix") == 1 and "faces_created_by_prev_fix" not in (r3.get("scalars") or {}),
          f"p2.history を省いた周の記録には載らない（2 周目 {r2.get('scalars')} / 3 周目 {r3.get('scalars')}）")
    rm(run.tmp)
    # **次の周へ渡す一撃も、前の周に出した判定から読む**——最新を読むと、p2.history を省いた周の次に 2 周前の一撃が拾われた
    run = Run("prevfix-oneshot")
    cnt = {"p2.diagnose": 0, "p2.history": 0}

    def hook3(run_, inst, out):
        if inst["node"] in cnt and isinstance(out, dict):
            cnt[inst["node"]] += 1
            rnd = cnt[inst["node"]] + (1 if inst["node"] == "p2.history" else 0)
            if inst["node"] == "p2.history" and rnd == 3:
                return {"__skip__": "検査用に省く"}
            if out.get("one_shot"):
                return {**out, "one_shot": f"{inst['node']}-R{rnd}"}
    nx = drive(run, "runaway", hook=hook3, stop_at=lambda n: n["round"] == 4)
    pos = run.state()["loop"].get("prev_one_shot") or {}
    check(nx["round"] == 4 and pos.get("round") == 3 and pos.get("text") == "p2.diagnose-R3",
          f"p2.history を省いた周の次は、その周の p2.diagnose の一撃を渡す（{pos.get('round')} / {pos.get('text')}）")
    rm(run.tmp)


def test_scalar_names_fixed():
    """**規模の数値の名前は型で固定する。** 写す側への『そのまま写せ』だけに頼っていた頃は、改名した名前でも型を通った
    ——周ごとに同じ量が別の名前になり、推移が作れなかった（実走の申し送り: 3 回改名）。"""
    print("規模の数値: 名前は型で固定され、未知の名前は拒まれる")
    run = Run("scalarnames")
    nx = drive(run, "std", stop_at=lambda n: any(i["node"] == "p4.scalars" for i in n["ready"]))
    inst = next(i for i in nx["ready"] if i["node"] == "p4.scalars")
    r = run.done(inst["id"], {"scalars": {"lines_added": 4, "cmt_pct": 10}})
    check(r.returncode == 1 and "lines_added" in r.stderr, f"未知の名前（lines_added）は型で拒む（rc={r.returncode}: {r.stderr.strip()[-90:]}）")
    r = run.done(inst["id"], {"scalars": {"added_lines": 0, "x_arms_fired": "12"}})
    check(r.returncode == 1 and "x_arms_fired" in r.stderr, f"x_ の名前も値は数（文字列は型で拒む。rc={r.returncode}: {r.stderr.strip()[-90:]}）")
    r = run.done(inst["id"], {"scalars": {"added_lines": 0, "comment_lines": 0, "doc_lines": 3, "x_arms_fired": 12}})
    check(r.returncode == 0, f"決まった名前と x_ で始まる名前なら通る（その場で足す数値の口。追加行 0 の周は comment_ratio_pct が無くてよい。rc={r.returncode}: {r.stderr.strip()[-90:]}）")
    rm(run.tmp)


def test_text_reply_out_path():
    """**本文を返す節の置き場は .md で、そこへ Markdown を書けば --output 無しで通る。** 置き場が .json 固定だった頃は、
    Markdown を返す節で運び手が別名に書き、初回の done が『返答が無い』で必ず落ちた。"""
    print("本文を返す節: 置き場は .md、そこへ書いた本文を done が --output 無しで読む")
    run = Run("textout")
    nx = drive(run, "std", stop_at=lambda n: any(i["node"] == "report.human_items" for i in n["ready"]))
    inst = next((i for i in nx.get("ready") or [] if i["node"] == "report.human_items"), None)
    check(inst is not None and inst["out_path"].endswith(".md"), f"本文を返す節の置き場は .md（{inst and inst['out_path']}）")
    if inst:
        pathlib.Path(inst["out_path"]).parent.mkdir(parents=True, exist_ok=True)
        pathlib.Path(inst["out_path"]).write_text("## 人が決めること\n\n無し。\n", encoding="utf-8")
        r = run.cmd("done", "--node", inst["id"])
        check(r.returncode == 0 and "読んだ先: out_path" in r.stdout, f"置き場の Markdown を --output 無しで読む（rc={r.returncode}: {(r.stdout + r.stderr).strip()[-90:]}）")
    rm(run.tmp)


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
    check(run.record()["process"].get("baseline_checks", {}).get("status") == "clean",
          "修正前の CI の結果（P0）は process.baseline_checks に残る——素材の local_checks は P4 の再実行で書き直す")
    hist = json.loads((run.dir / "out" / "r3" / "p2.history.json").read_text(encoding="utf-8"))
    check(run.record()["process"]["diagnosis"].get("units") == hist.get("units") and "precedents" in run.record()["process"],
          "修正役が読む判定（process.diagnosis）は最新の判定——履歴の再審（p2.history）が書き直す")
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
    lied = {}

    def hook(run, inst, out):
        if inst["node"] == "p1.main_path_observation" and "rc" not in lied:
            r = run.done(inst["id"], {"material": CLEAN("画面は未観測だが異常なし（検査用の嘘）"), "observed": []})
            lied["rc"], lied["err"] = r.returncode, r.stderr
            r = run.done(inst["id"], {"material": CLEAN("画面は未観測だが異常なし（検査用の嘘）"), "observed": [{"path": " ", "value": " "}]})
            lied["blank_rc"], lied["blank_err"] = r.returncode, r.stderr
        return None
    # 柵が効かずに嘘が受理された回も、下の検査まで届かせる（drive の例外で台本ごと抜けると、どの柵かが検査の名前に出ない）
    try:
        last = drive(run, "awaiting", hook=hook)
    except RuntimeError:
        last = None
    check(lied.get("rc") == 1 and "observed" in lied.get("err", ""),
          f"主経路の観測: 見たと言う状態なのに観測した値が無ければ exit 1（本文の言い回しでなく欄で見る。{lied.get('err', '').strip()[-80:]}）")
    check(lied.get("blank_rc") == 1 and "observed" in lied.get("blank_err", ""),
          f"主経路の観測: 空白だけの観測の行も観測した値に数えない（{lied.get('blank_err', '').strip()[-80:]}）")
    if last is None:
        rm(run.tmp)
        return
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


def test_awaiting_origin_guards():
    """人待ちの問いの出どころは、今 awaiting_human の素材だけ——**判定の時点**（判定者が人待ちでない欄を借りる入口）と、
    **素材を書いた時点**（後の工程が人待ちの欄を上書きする入口）の両方で当てる。検証器は周の最後の 1 回しか見ず、
    実走では 5 周で 8 回、回す側が patch で書き戻した。人が実地で確かめるまで決まらない問いは field（出どころを持たない）"""
    print("人待ちの問いの出どころ: 判定の時点と書いた時点で拒み、実地の問いは field で立つ")
    run = Run("awaitorigin")
    seen = {}
    field = {"key": "Windows の実機で動かしたか", "kind": "field", "status": "held", "reason": "手元にも CI にも Windows の実機が無い（検査用）"}
    wait_ci = {"key": "CI をどこで走らせるか", "kind": "awaiting", "origin": "local_checks", "status": "held", "reason": "手元で CI を走らせられない（検査用）"}

    def hook(run, inst, out):
        if inst["node"] == "p0.local_checks":
            return {"material": M("awaiting_human", reason="CI 専用のジョブで手元では走らない（検査用）")}
        if inst["node"] == "p2.diagnose" and run.state()["round"] == 1:
            bad = {**out, "questions": [wait_ci, {"key": "Windows の実機で動かしたか", "kind": "awaiting", "origin": "main_path_observation",
                                                  "status": "held", "reason": "（検査用）"}]}
            r = run.done(inst["id"], bad, agent_id="judge-1")
            seen["judge"] = (r.returncode, r.stderr)
            if r.returncode == 0:   # 柵が効かずに通った——先へ進めずに下の検査で赤くする
                raise RuntimeError("判定の時点の柵が効かなかった")
            return {**out, "questions": [wait_ci, field]}
        if inst["node"] == "p4.ci" and run.state()["round"] == 1:
            seen["ci_prompt"] = pathlib.Path(inst["prompt_file"]).read_text(encoding="utf-8")
            r = run.done(inst["id"], {"material": CLEAN("pytest 緑（検査用）")})
            seen["ci"] = (r.returncode, r.stderr)
            if r.returncode == 0:
                raise RuntimeError("書いた時点の柵が効かなかった")
            return {"material": M("awaiting_human", reason="手元の pytest は緑。CI 専用のジョブは人待ち（検査用）")}
        return None

    # **柵が効かない回も、下の検査まで届かせる**——drive の例外で台本ごと抜けると、どの柵が効かなかったかが検査の名前に出ない
    try:
        drive(run, "std", hook=hook, stop_at=lambda nx: nx["round"] >= 2)
    except RuntimeError as e:
        seen["stopped"] = str(e)
    rc, err = seen.get("judge", (None, ""))
    check(rc == 1 and "awaiting の出どころは" in err and "main_path_observation" in err and "kind=field" in err,
          f"判定の時点: 人待ちでない素材を出どころにした awaiting は拒み、field を案内する（rc={rc} {err.strip()[-120:]}）")
    rc, err = seen.get("ci", (None, ""))
    check(rc == 1 and "local_checks" in err and "awaiting_human のまま書け" in err,
          f"書いた時点: 人に諮っている欄を後の工程が clean で上書きすると拒む（rc={rc} {err.strip()[-120:]}）")
    check(wait_ci["key"] in seen.get("ci_prompt", ""), "CI を再実行する節のプロンプトに、この周の問いの台帳が渡る（人に諮っている欄を知って書ける）")
    r1 = run.round_file(1) if (run.dir / "rounds" / "round-1.json").is_file() else {"questions": [], "materials": {}}
    check(any(q["kind"] == "field" and not q.get("origin") for q in r1["questions"])
          and r1["materials"].get("local_checks", {}).get("status") == "awaiting_human",
          "実地の問いは field で台帳に載り、人待ちの CI の欄は awaiting_human のまま周の記録に入る（検証器を通る）")
    rm(run.tmp)


def test_runaway():
    print("台本: 毎周新しい [block] → 上限 5 で停止")
    run = Run("runaway", unattended=True)
    last = drive(run, "runaway")
    check(last["status"] == "stopped" and run.state()["round"] == 5, f"5 周で停止（{run.state()['round']}）")
    check("暴走ガード" in run.record()["process"].get("stop_reason", "") or run.state()["loop"].get("stop_reason") == "max_rounds", "停止の理由が上限")
    rm(run.tmp)


def test_local_review_lens_rows():
    """宣言したレンズ 1 本につき findings の行 1 本。**沈黙では通らない。**

    直した面: 未起動が「見たが所見なし」と同じ形で受理され、3 周続けて型設計のレンズが起動されないまま
    記録のどこにも赤が出なかった（実測 2026-09-15）。あわせて、役に渡す一覧が正本そのものであること
    （プロンプトに写しを持たない）をここで見る——写しだけが古くなる面だった。
    """
    print("P1: 宣言したレンズと findings の行の 1 対 1")
    run = Run("lens")
    nx = run.next()
    by = {i["node"]: i for i in nx["ready"]}
    t = answers(run, "std", 1)
    for n in ("p0.base", "p0.local_checks", "p0.premises"):
        run.done(by[n]["id"], t[n](None))
    nx = run.next()
    by = {i["node"]: i for i in nx["ready"]}
    for n in ("p0.purpose", "p0.parallel_pr", "p0.prior_decisions"):
        run.done(by[n]["id"], t[n](None))
    nx = run.next()
    by = {i["node"]: i for i in nx["ready"]}
    lr = by["p1.local_review"]
    body = pathlib.Path(lr["prompt_file"]).read_text(encoding="utf-8")
    # 条件 1（正本を 1 か所に）——役が読む本文に正典の綴りが全部在り、かつ本数を焼き込んだ写しではない
    for name in DECLARED_LENSES:
        check(name in body, f"プロンプトに正典の綴りが埋まる: {name}")
    check('"required": false' in body, "条件付きのレンズは required で渡る（散文の『（該当時）』ではない）")
    check("pr-review-toolkit:review-pr" in body, "まとめ役を挟むなという禁止は残る")
    base = t["p1.local_review"](None)
    # 腕 1: 宣言した 1 本の行を落とす
    r = run.done(lr["id"], {**base, "findings": local_findings(1, drop=("pr-review-toolkit:type-design-analyzer",))})
    check(r.returncode == 1 and "type-design-analyzer" in r.stderr and "行が findings に無い" in r.stderr,
          f"宣言したレンズの行を落とすと exit 1（rc={r.returncode}）")
    # 腕 2: 行は在るが items も failed も空——「起こして 0 件」と「起こしていない」が区別できない
    r = run.done(lr["id"], {**base, "findings": local_findings(1, blank=("pr-review-toolkit:pr-test-analyzer",))})
    check(r.returncode == 1 and "items も failed も持たない" in r.stderr,
          f"items も failed も無い行は exit 1（rc={r.returncode}）")
    # 腕 3: 宣言に無い名前を役が足す——正本は graph の側
    r = run.done(lr["id"], {**base, "findings": local_findings(1) + [{"skill": "pr-review-toolkit:review-pr", "items": []}]})
    check(r.returncode == 1 and "宣言に無い" in r.stderr, f"宣言に無い skill 名は exit 1（rc={r.returncode}）")
    # 腕 4: 同じレンズを 2 行に割る——1 本につき 1 行でないと数えられない
    r = run.done(lr["id"], {**base, "findings": local_findings(1) + [{"skill": "/simplify", "items": []}]})
    check(r.returncode == 1 and "2 本" in r.stderr, f"同じ skill が 2 行あると exit 1（rc={r.returncode}）")
    # 対照: 7 本そろえば通る（非該当の 1 本も failed の行で在る）
    r = run.done(lr["id"], base)
    check(r.returncode == 0, f"宣言 7 本ぶんの行がそろえば通る（rc={r.returncode}: {r.stderr[-200:]})")


def test_carried_r1_counted():
    """前の周の R1 最小性が挙げた削除候補を、次の周の judge が 1 件につき 1 行で処理する。

    直した面: 配線（p2.diagnose と p3.fix の reads の prev.r1.minimality）は前から在り、**届いた上で
    黙って落とせた**——直す義務は record["units"] にしか掛からないので、judge が unit に上げなければ
    誰も赤くならない。実測 2026-09-16（別リポジトリの run）: 1 周目の最小性が挙げた 14 件が 2 周目の
    修正対象に 1 件も入らず、2 周目の最小性でそのまま再掲された。
    """
    print("台本: 前の周の R1 の削除候補を judge が 1 件 1 行で処理する")
    run = Run("carryr1")
    at = lambda node, rnd: (lambda nx: nx["round"] == rnd and any(i["node"] == node for i in nx["ready"]))
    drive(run, "carryr1", stop_at=at("p2.diagnose", 2))
    nx = run.next()
    jd = next(i for i in nx["ready"] if i["node"] == "p2.diagnose")
    t = answers(run, "carryr1", 2)
    good = t["p2.diagnose"](None)
    check(len(good["carried_r1"]) == 1, "台本の前提: 2 周目の judge は前の周の削除候補 1 件を持つ")
    dis = good["carried_r1"][0]["disposition"]
    # 腕 1: 行ごと落とす——「読んだ上で黙って落とす」形
    r = run.done(jd["id"], {**good, "carried_r1": []}, agent_id="judge-1")
    check(r.returncode == 1 and "carried_r1 に無い" in r.stderr, f"前の周の R1 の行を落とすと exit 1（rc={r.returncode}）")
    # 腕 2: 落とすなら理由が要る
    r = run.done(jd["id"], {**good, "carried_r1": [{"where": R1_DELETION, "disposition": "decline"}]}, agent_id="judge-1")
    check(r.returncode == 1 and "why が無い" in r.stderr, "decline に理由が無いと exit 1")
    # 腕 3: unit に上げると言いながら実在しない key を指す
    r = run.done(jd["id"], {**good, "carried_r1": [{"where": R1_DELETION, "disposition": "promote", "unit_key": "無い"}]}, agent_id="judge-1")
    check(r.returncode == 1 and ("units に無い" in r.stderr or "unit_key が無い" in r.stderr), "promote の unit_key が units に無いと exit 1")
    # 腕 4: 前の周に無い where を足す（正本は prev.r1.minimality の側）
    r = run.done(jd["id"], {**good, "carried_r1": good["carried_r1"] + [{"where": "でっちあげ", "disposition": "decline", "why": "x"}]}, agent_id="judge-1")
    check(r.returncode == 1 and "削除候補に無い" in r.stderr, "前の周の R1 に無い where を足すと exit 1")
    # 対照: 1 件を unit に上げれば通る
    r = run.done(jd["id"], good, agent_id="judge-1")
    check(r.returncode == 0, f"前の周の削除候補を unit に上げれば通る（rc={r.returncode}: {r.stderr[-200:]})")
    # **同じ post_check を共有する隣の節が巻き添えにならないこと。** judge_output は p2.diagnose と
    # p2.history の 2 節が使うが、carried_r1 を schema に持つのは前者だけ。節を見ずに当てていたとき、
    # 前の周の R1 が削除候補を 1 件でも挙げた周は p2.history が必ず落ち、しかも additionalProperties: false
    # なので役には直す術が無かった（P2 が二度と通らない＝周が進まない。実測 2026-09-16）
    nx = run.next()
    hs = next(i for i in nx["ready"] if i["node"] == "p2.history")
    r = run.done(hs["id"], {k: v for k, v in t["p2.history"](None).items() if k != "reburn_causes"}, agent_id="judge-1")
    check(r.returncode == 1 and "reburn_causes" in r.stderr,
          f"p2.history は reburn_causes を省けない（欄が無い周を『前の周の修正が作った面 0』と記録しない。rc={r.returncode}）")
    r = run.done(hs["id"], t["p2.history"](None), agent_id="judge-1")
    check(r.returncode == 0, f"carried_r1 を持たない隣の節（p2.history）は巻き添えで落ちない（rc={r.returncode}: {r.stderr[-200:]})")


def test_held_fork_stops_exempting():
    """fork が出どころの [block] を免除するのは 1 周だけ。2 周目からは escalate（人に実際に届く形）に上げる。

    直した面: fork の出どころと depends は fix_covers_open_units が無条件に免除していたので、
    held のまま持ち越せば [block] を何周でも未着手にできた（実測 2026-09-16、別リポジトリの run）。

    **柵は judge の手前に置く。** 最初これを P3 に置いたが、writer には questions を書く権限が無く、
    同じ周の p2 は既に done で再実行できず、p3.fix は optional でないので skip もできない——正本の
    プロンプトが「fork の出どころは実装するな」と言う所で機械が「実装しろ」と言い、writer の手が
    無くなった（実測 2026-09-16: judge が [block] として名指しした）。義務は動ける役の手前に置く。

    **持ち越しは機械（on_new_round）に作らせる。** 手で prev_questions を patch していたとき、それを
    書く経路を 1 度も通っておらず、その 1 行を消す退行が緑で通った（実測 2026-09-16）。
    """
    print("台本: held の fork の免除は 1 周で切れる（escalate なら続く）")
    at = lambda node, rnd: (lambda nx: nx["round"] == rnd and any(i["node"] == node for i in nx["ready"]))
    # forkhold は毎周 held、forkesc は 2 周目に escalate へ上げる。どちらも出どころは同じ unit
    run = Run("forkhold")
    drive(run, "forkhold", stop_at=at("p2.diagnose", 2))
    ls = run.state()["loop"]
    check(any(x.get("kind") == "fork" for x in (ls.get("prev_questions") or [])),
          "持ち越しは機械（on_new_round）が写した——台本が手で置いたのではない")
    nx = run.next()
    jd = next(i for i in nx["ready"] if i["node"] == "p2.diagnose")
    t = answers(run, "forkhold", 2)
    r = run.done(jd["id"], t["p2.diagnose"](None), agent_id="judge-1")
    check(r.returncode == 1 and "前の周も fork で免除されていた" in r.stderr,
          f"held のまま 2 周目に入った fork は judge に返させ直す（rc={r.returncode}: {r.stderr[-200:]})")
    # 対照: 同じ出どころでも escalate（人に実際に届く形）なら通る。**rc だけを要求する**
    # ——以前は否定の連言（rc==0 or 文言が無い）で書いていたので、別の理由で落ちても緑だった
    run2 = Run("forkesc")
    drive(run2, "forkesc", stop_at=at("p2.diagnose", 2))
    nx2 = run2.next()
    jd2 = next(i for i in nx2["ready"] if i["node"] == "p2.diagnose")
    t2 = answers(run2, "forkesc", 2)
    r = run2.done(jd2["id"], t2["p2.diagnose"](None), agent_id="judge-1")
    check(r.returncode == 0, f"escalate に上げれば通る（rc={r.returncode}: {r.stderr[-200:]})")
    # 履歴の再審の節は、同じ [block] が前の 2 周の記録に続けて在るのに振り分けの跡（その unit を origin に持つ問い）を落とした返答を
    # 判定の時点で拒む（周の記録の段まで持ち越さない）。筋書きは 3 周目まで回らないので、2 周目の前に 0 周目の記録を置いて 3 周続く形にする
    nx2 = drive(run2, "forkesc", stop_at=at("p2.history", 2))
    hs = next(i for i in nx2["ready"] if i["node"] == "p2.history")
    r1 = json.loads((run2.dir / "rounds" / "round-1.json").read_text(encoding="utf-8"))
    r0 = run2.dir / "rounds" / "round-0.json"
    r0.write_text(json.dumps({**r1, "round": 0}, ensure_ascii=False), encoding="utf-8")
    good = answers(run2, "forkesc", 2)["p2.history"](load_item(hs))
    r = run2.done(hs["id"], {**good, "questions": []}, agent_id="judge-1")
    r0.unlink()
    check(r.returncode == 1 and "3 周続けて在る" in r.stderr, f"3 周続く [block] の振り分けを落とした履歴の再審は拒む（{r.stderr.strip()[-120:]}）")


def test_rejections():
    print("否定検査: engine と rules が受け付けないもの")
    run = Run("neg")
    nx = run.next()
    by = {i["node"]: i for i in nx["ready"]}
    check(all(pathlib.Path(i["out_path"]).parent.is_dir() for i in nx["ready"]),
          "返答の置き場のディレクトリは engine が作る（最初の波の節も、運び手が mkdir せずに書ける）")
    check(by["p0.local_checks"].get("delegate", {}).get("model") == "haiku" and "delegate" not in by["p0.base"],
          f"任せ先: graph が delegate を宣言した回す側の節は ready に任せ先が載り、宣言の無い節には載らない（{by['p0.local_checks'].get('delegate')}）")
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
    check(by["p1.consistency_bypass"].get("deliver") == "paste" and by["p1.external_standards"].get("deliver") == "path",
          f"inspector は Read を持っても本文を貼る渡し方（ファイルの指示に従えの 1 文を拒むため）、investigator は path（{by['p1.consistency_bypass'].get('deliver')} / {by['p1.external_standards'].get('deliver')}）")
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
    r = run.done(by["p1.external_standards"]["id"], {k: v for k, v in t["p1.external_standards"](None).items() if k != "rankings_none"})
    check(r.returncode == 1 and "rankings_none" in r.stderr, f"順位（主経路）: 外部標準照合の done は、空の順位を付けられない理由なしで拒む（{r.stderr.strip()[-70:]}）")
    (run.repo / "stray.txt").write_text("x", encoding="utf-8")
    (run.repo / "stray.txt").unlink()
    for n in ("p1.local_review", "p1.consistency_bypass", "p1.external_standards", "p1.provenance"):
        r = run.done(by[n]["id"], t[n](None))
        if r.returncode != 0:  # assert は -O で消える（台本の前提が黙って外れる）
            raise SystemExit(f"台本の前提が崩れた: {n} の done が {r.returncode}: {r.stderr[-200:]}")
    r = run.done(hyg["id"], t["p1.hygiene"](None), agent_id="cli-has-no-agent")
    check(r.returncode == 1 and "agent_id" in r.stderr, "cli で起こした遮断系の done に --agent-id を渡すと exit 1（engine が起こす節に Agent の id は無い）")
    r = run.done(hyg["id"], t["p1.hygiene"](None))
    if r.returncode != 0:
        raise SystemExit(f"台本の前提が崩れた: done が {r.returncode}: {r.stderr[-200:]}")
    # 既に ' M' のファイルの**中身の差し替え**も止める（porcelain は状態コードとパスしか見ないので、固めた木の id で見る）
    orig = (run.repo / "src" / "a.py").read_text(encoding="utf-8")
    (run.repo / "src" / "a.py").write_text(orig + "# 役が書き換えた\n", encoding="utf-8")
    nx = run.next()
    check(not nx["ready"] and any("tree:" in n for n in nx["notes"]), f"既に変更済みのファイルの中身を差し替えても止まる: {str(nx.get('notes'))[:120]}")
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
    # 受け付けた回は、変更前の姿を見て書いた材料の節を撃ち直す（台本 test_worktree_guard_fires が性質を見る。ここは先へ進むために返すだけ）
    for i in nx.get("ready", []):
        r = run.done(i["id"], t[i["node"]](None))
        if r.returncode != 0:
            raise SystemExit(f"台本の前提が崩れた: 撃ち直した {i['node']} の done が {r.returncode}: {r.stderr[-200:]}")
    nx = run.next()
    (run.repo / "stray.txt").unlink()
    jd = next(i for i in nx["ready"] if i["node"] == "p2.diagnose")
    check(jd["mode"] == "agent" and "fix_closure" in json.dumps(run.record()["materials"]), "受け付ければ judge に進み、素材は 15 欄で渡る")
    bad = {**t["p2.diagnose"](None), "questions": [{"key": "q", "kind": "fork", "status": "held", "reason": "r", "origin": "無いユニット", "options": ["a", "b"]}]}
    r = run.done(jd["id"], bad)
    check(r.returncode == 1 and "units にも defer 台帳にも無い" in r.stderr, "台帳の出どころが無い judge の返答は exit 1")
    bad = {**t["p2.diagnose"](None), "questions": [{"key": "q", "kind": "split", "status": "held", "reason": "r", "origin": "src/a.py:f — 上限が効かない経路がある"}]}
    r = run.done(jd["id"], bad)
    check(r.returncode == 1 and "人に聞く前に直す義務" in r.stderr, "split の出どころが [block] の返答は exit 1")
    good = t["p2.diagnose"](None)
    # **先行例の行（世界の解）**: 直す単位と人へ回す問いの key ごとに 1 行、出典つき。人へ回す問いには決まらない理由
    r = run.done(jd["id"], {**good, "precedents": good["precedents"][1:]})
    check(r.returncode == 1 and "precedents に" in r.stderr and "の行が無い" in r.stderr,
          f"先行例: 直す単位の行が欠けた judge の返答は exit 1（{r.stderr.strip()[-80:]}）")
    r = run.done(jd["id"], {**good, "precedents": [{**good["precedents"][0], "source": ""}] + good["precedents"][1:]})
    check(r.returncode == 1 and "source（一次情報の出典）が無い" in r.stderr, f"先行例: 出典の無い行は exit 1（{r.stderr.strip()[-80:]}）")
    r = run.done(jd["id"], {**good, "precedents": [{**good["precedents"][0], "verdict": "not_found", "source": ""}] + good["precedents"][1:]})
    check(r.returncode == 1 and "searched（何をどう探したか）が無い" in r.stderr, f"先行例: 見つからないなら何を探したかが要る（{r.stderr.strip()[-80:]}）")
    r = run.done(jd["id"], {**good, "precedents": good["precedents"] + [good["precedents"][0]]})
    check(r.returncode == 1 and "key が重複" in r.stderr, f"先行例: 同じ key の行が 2 つある judge の返答は exit 1（{r.stderr.strip()[-70:]}）")
    eq = {"key": "人でないと決められない（検査用）", "kind": "stuck", "status": "escalate", "reason": "r", "origin": good["units"][0]["key"]}
    r = run.done(jd["id"], {**good, "questions": [eq]})
    check(r.returncode == 1 and "人でないと決められない（検査用）' の行が無い" in r.stderr,
          f"先行例: 人へ回す問い（escalate）にも先行例の行が要る（{r.stderr.strip()[-80:]}）")
    fq = {"key": "どちらに倒すか（検査用）", "kind": "fork", "status": "held", "reason": "r", "origin": good["units"][0]["key"], "options": ["a", "b"]}
    r = run.done(jd["id"], {**good, "questions": [fq], "precedents": good["precedents"] + [{"key": fq["key"], "problem": "人が決める分岐",
                                                                                            "source": "https://example.invalid/", "verdict": "adopt", "reason": "そのまま採れる形"}]})
    check(r.returncode == 1 and "undecided_because が無い" in r.stderr and "人に回さず" in r.stderr,
          f"先行例: 人へ回す問いに決まらない理由が無ければ exit 1（自明なので聞かない。{r.stderr.strip()[-80:]}）")
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
    r = run.done(jd["id"], {**good, "units": [{**good["units"][0], "class_query": {"how": {"patterns": ["limit"], "paths": ["src"], "count": "files"}, "counts": "population", "total": True}}]})
    check(r.returncode == 1 and "型に合わない" in r.stderr, "class_query.total が数でなければ exit 1")
    r = run.done(jd["id"], {**good, "units": [{**good["units"][0], "class_query": {"how": {"patterns": ["x"], "paths": ["nope/"], "count": "lines"}, "counts": "defects", "total": 1}}]})
    check(r.returncode == 1 and "走らせられない" in r.stderr and "units[0].class_query" in r.stderr,
          f"判定者の class_query も、走らせられない問いは exit 1（{r.stderr.strip()[-90:]}）")
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
    # 判定者が書いた件数（3）は、engine が how を走らせた件数（1）に置き換わって記録に入る——**拒否文で件数を教えて
    # 写させる往復にしない**（how を書く判定役は shell を持たない）
    zero = {"how": {"patterns": ["no-such-word"], "paths": ["src/a.py"], "count": "lines"}, "counts": "population", "total": 1}   # engine は 0 件を数える——置き換えずに note に残す
    fresh = {**good, "framing": "FRESH", "units": [{**good["units"][0], "class_query": {**good["units"][0]["class_query"], "total": 3}},
                                                   {**good["units"][1], "class_query": zero}] + good["units"][2:]}
    r = run.cmd("done", "--node", jd["id"], "--stdin", "--agent-id", "judge-1", input=json.dumps(fresh, ensure_ascii=False),
                env={**os.environ, "PYTHONIOENCODING": "cp1252"})
    check(r.returncode == 0 and "読んだ先: stdin" in r.stdout, f"正しい judge の返答は通り、どこから読んだかが返事に残る（stdin を cp1252 の環境で。rc={r.returncode} {(r.stdout + r.stderr).strip()[:160]}）")
    stored = json.loads(pathlib.Path(jd["out_path"]).read_text(encoding="utf-8"))
    check(stored.get("framing") == "FRESH", "標準入力の返答が置き場の古い返答より優先され、記録に入るのは新しい方")
    cq0 = stored["units"][0]["class_query"]
    check(cq0["total"] == 1 and "engine が how を走らせた 1 に置き換えた" in cq0.get("note", "") and "3 → 1" in r.stdout,
          f"判定者の書いた件数は engine が数えた件数に置き換わり、置き換えたことが note と返事に残る（{cq0} / {r.stdout.strip()[-120:]}）")
    cq1 = stored["units"][1]["class_query"]
    check(cq1["total"] == 1 and "0 件" in cq1.get("note", "") and "置き換えなかった" in r.stdout,
          f"engine が 0 件を数えた単位は置き換えず、0 だったことが note と返事に残る（{cq1} / {r.stdout.strip()[-120:]}）")
    ez = run.state().get("loop", {}).get("engine_zero") or {}
    check(ez.get("keys") == [good["units"][1]["key"]] and ez.get("round") == 1,
          f"engine が 0 件を数えた単位の key は、修正の側が読める値（engine_zero）にも残る（{ez}）")
    nx = run.next()
    for node in ("p2.fix_plan", "p2.plan_review"):   # 修正の前に、案とその事前審査が立つ
        it = next(i for i in nx["ready"] if i["node"] == node)
        r = run.done(it["id"], answers(run, "std", nx["round"])[node](None))
        if r.returncode != 0:
            raise RuntimeError(f"{node} が {r.returncode}: {r.stderr[-300:]}")
        nx = run.next()
    fx = next(i for i in nx["ready"] if i["node"] == "p3.fix")
    r = run.done(fx["id"], {**t["p3.fix"](None), "changes": [], "not_done": [{"unit_key": "src/a.py:f — 上限が効かない経路がある", "why": "面倒"}]})
    check(r.returncode == 1 and "直していない" in r.stderr and "理由: 面倒" in r.stderr,
          f"[block] を直さない writer の返答は exit 1 で、残した理由を拒否文に併記する（{r.stderr.strip()[-90:]}）")
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
    # 母数は engine が修正前の版で数える（修正役の total は使わない）——src に def は 2 行（a.py の f・b.py の g）
    part = {**fix, "changes": [{**c, "coverage": {**c["coverage"], "how": {"patterns": ["def"], "paths": ["src"], "count": "lines"}}} for c in fix["changes"]]}
    r = run.done(fx["id"], part)
    check(r.returncode == 1 and "remaining" in r.stderr, "母数 2 のうち閉鎖を実証した site が 1 件で残りが在るのに remaining が無ければ exit 1（母数は engine が修正前の版で数える）")
    r = run.done(fx["id"], {**fix, "changes": [{**c, "coverage": {**c["coverage"], "how": "git grep -l -e limit -- src | wc -l"}} for c in fix["changes"]]})
    check(r.returncode == 1 and "型に合わない" in r.stderr, f"1 行のコマンドの how は型で拒む（欄で書く。{r.stderr.strip()[-90:]}）")
    r = run.done(fx["id"], {**fix, "changes": [{**c, "coverage": {**c["coverage"], "how": {"patterns": ["x"], "paths": ["nope/"], "count": "lines"}}} for c in fix["changes"]]})
    check(r.returncode == 1 and "走らせられない" in r.stderr, f"走らせられない how は拒む（当たらないパス。{r.stderr.strip()[-90:]}）")
    # 判定者より狭い問い: 判定者が 1 と数えた単位を 0 と数える how に作り直すなら、理由（remaining）が要る
    narrow = {**fix, "changes": [{**c, "closure": {**c["closure"], "sites": []},
                                  "coverage": {**c["coverage"], "how": {"patterns": ["no-such-word"], "paths": ["src"], "count": "lines"}}} for c in fix["changes"]]}
    r = run.done(fx["id"], narrow)
    check(r.returncode == 1 and "問いを狭めている" in r.stderr, f"覆い: 判定者の母数より狭い how は理由なしで拒む（{r.stderr.strip()[-70:]}）")
    r = run.done(fx["id"], {**narrow, "changes": [{**c, "coverage": {**c["coverage"], "remaining": "なし"}} for c in narrow["changes"]]})
    check(r.returncode == 1 and "問いを狭めている" in r.stderr, f"覆い: 空語（『なし』）の remaining は理由に数えない（{r.stderr.strip()[-70:]}）")
    # 修正ごとの先行例: 判定者の行を採るなら、その行が在ること。自分で書くなら problem と source
    r = run.done(fx["id"], {**fix, "changes": [{**c, "precedent": {"verdict": "adopt", "reason": "採った（検査用）"}} for c in fix["changes"]]})
    check(r.returncode == 1 and "precedent に problem と source" in r.stderr, f"先行例: 修正の先行例に出典が無ければ exit 1（{r.stderr.strip()[-80:]}）")
    r = run.done(fx["id"], {**fix, "wrote_refs": [{"kind": "text", "cite": "検査用に無い字列", "target": "README.md", "where": "src/a.py"}],
                            "changes": [{**c, "precedent": {"verdict": "adopt", "from_judge_row": True, "reason": "判定者の行（検査用）"},
                                         # 修正役が向きを書いても使われない（判定者の値が勝つ）——ここでは population の判定者に defects と書く
                                         "coverage": {**c["coverage"], "counts": "defects"}} for c in fix["changes"]]})
    check(r.returncode == 1 and "の中に無い" in r.stderr and "from_judge_row なのに" not in r.stderr and "precedent に" not in r.stderr,
          f"先行例: 判定者の行が在る単位は from_judge_row で採れる（赤の理由は wrote_refs だけ。{r.stderr.strip()[-80:]}）")
    over = {**fix, "changes": [{**c, "coverage": {**c["coverage"], "how": {"patterns": ["no-such-word"], "paths": ["src"], "count": "lines"}}} for c in fix["changes"]]}
    r = run.done(fx["id"], over)
    check(r.returncode == 1 and "母数を超えて" in r.stderr, "closure.sites が母数を超える返答は exit 1（問いが対象を取りこぼしている）")
    # 残した理由を書けば部分的な覆いは通る。**正しい返答で確かめると節が done になり後続の腕が撃てない**ので、
    # 別の理由（fix_closure=not_applicable）で赤くして「coverage では赤くなっていない」ことを見る
    # **赤くする理由は coverage の検査より後ろに在るもの**（wrote_refs の数え）にする——前に在る拒否（fix_closure）で
    # 赤くすると coverage の検査に届かず、主張が偽のまま緑だった（2026-09-23 の gate_efficacy）
    # **差分が足した Markdown のリンクは、申告に依らず engine が拾って指し先と見出しまで引く**（申告を空にしても引かれる）
    readme = run.repo / "README.md"
    orig_readme = readme.read_text(encoding="utf-8")
    readme.write_text(orig_readme + "詳しくは [設計](docs/nowhere.md) と [見出し](README.md#no-such) と [在る](README.md#demo) を見よ。"
                      "`[例](x.md)` は書式の例\n", encoding="utf-8")
    r = run.done(fx["id"], fix)
    check(r.returncode == 1 and "Markdown のリンクが指し先に届かない" in r.stderr and "docs/nowhere.md" in r.stderr
          and "#no-such" in r.stderr and "#demo" not in r.stderr and "x.md" not in r.stderr,
          f"リンク: 申告が空でも、差分が足したリンクの指し先と見出しを引いて拒む（コードスパンの中は拾わない。{r.stderr.strip()[-120:]}）")
    readme.write_text(orig_readme, encoding="utf-8")
    withrem = {**fix, "wrote_refs": [{"kind": "text", "cite": "検査用に無い字列", "target": "README.md", "where": "src/a.py"}],
               "changes": [{**c, "coverage": {**c["coverage"], "remaining": "残り 2 件は fork の出どころ（検査用）"}} for c in fix["changes"]]}
    r = run.done(fx["id"], withrem)
    check(r.returncode == 1 and "の中に無い" in r.stderr and "remaining" not in r.stderr and "coverage" not in r.stderr,
          f"残した理由を書けば部分的な覆いは通る（赤の理由は wrote_refs だけ。{r.stderr.strip()[-70:]}）")
    # 修正が新しく書いた指しも、指摘の根拠と同じ裏取りを通る（理由は rules の _cite_errors の docstring）
    r = run.done(fx["id"], {**fix, "wrote_refs": [{"kind": "text", "cite": "Data Platform の責務", "target": "README.md", "where": "src/a.py"}]})
    check(r.returncode == 1 and "の中に無い" in r.stderr and "README.md" in r.stderr,
          f"指し先に無い字列は exit 1（どこかに在るかでなく、指し先に在るかを見る。rc={r.returncode}）")
    r = run.done(fx["id"], {**fix, "wrote_refs": [{"kind": "text", "cite": "# demo", "target": "docs/nowhere.md", "where": "README.md"}]})
    # **区別語まで見る。** 『指し先』『に無い』の 2 語は隣の拒否文（『指し先 … の中に無い』）にも在るので、
    # この枝を消して走査へ素通しさせても緑のまま通っていた
    check(r.returncode == 1 and "作業ツリーに無い" in r.stderr and "の中に無い" not in r.stderr,
          f"指し先のファイルが無ければ exit 1（『中に無い』とは別の拒否文。{r.stderr.strip()[-90:]}）")
    # **欄ごと落とした返答は型で拒む**（この腕が無かったとき、schema の required から外しても全件緑だった）
    r = run.done(fx["id"], {k: v for k, v in fix.items() if k != "wrote_refs"})
    check(r.returncode == 1 and "wrote_refs" in r.stderr, "wrote_refs を落とした返答は型で拒まれる（必須の欄）")
    # **別の文書に同じ字列が在っても通らない**（走査を target に絞っていることの腕）。
    # src/b.py に README.md と同じ字列を置き、target は README.md でないファイルを指す
    (run.repo / "src" / "b.py").write_text('# demo\ndef g(y):\n    return y * 2\n', encoding="utf-8")
    r = run.done(fx["id"], {**fix, "wrote_refs": [{"kind": "text", "cite": "# demo", "target": "src/a.py", "where": "README.md"}]})
    check(r.returncode == 1 and "の中に無い" in r.stderr,
          f"別のファイルに同じ字列が在っても、target に無ければ exit 1（rc={r.returncode}）")
    r = run.done(fx["id"], {**fix, "wrote_refs": [{"kind": "text", "cite": "def f(x, limit=None):\n\n    return x", "target": "src/a.py", "where": "README.md"}]})
    check(r.returncode == 1 and "指し先の 1 行から写す" in r.stderr and "git grep" not in r.stderr,
          "改行を含む cite は exit 1（修正側には 1 行 1 件の規律だけを言い、指摘側の git grep の理由を言わない）")
    # **この周に作った指し先が通る**（unit 1 の修正そのもの）。数えるのは作業ツリーなので、
    # p3.fix の中で書いたファイル・書き足した見出しを指す申告が通らなければならない——
    # 周の頭で固めた版を数えていたとき、**正直に申告した回だけが必ず落ちた**
    (run.repo / "docs").mkdir(exist_ok=True)
    (run.repo / "docs" / "made-this-round.md").write_text("# この周に書いた見出し\n", encoding="utf-8")
    mixed = {**fix, "changes": [fix["changes"][0], {**fix["changes"][1], "closure": {**fix["changes"][1]["closure"], "sites": [{"site": "docs（赤を見られない）", "red_seen": False}]}}],
             "wrote_refs": [{"kind": "text", "cite": "# demo", "target": "README.md", "where": "src/a.py"},
                            {"kind": "text", "cite": "# この周に書いた見出し", "target": "docs/made-this-round.md", "where": "README.md"}]}
    # **欠陥の形そのものを数える問いで全部直した正直な申告が通る**——修正で limit が消え、同じ how は修正後に 0 件を
    # 返す。total を修正前の母数と修正後の件数の両方で読んでいた頃は、total をどう書いても拒まれた
    (run.repo / "src" / "a.py").write_text("def f(x, cap=None):\n    return x if cap is None else min(x, cap)\n", encoding="utf-8")
    # 本番の主経路——運び手が out_path に書き、--output も --stdin も付けずに done（台本は --output しか通していなかった）
    pathlib.Path(fx["out_path"]).parent.mkdir(parents=True, exist_ok=True)
    pathlib.Path(fx["out_path"]).write_text(json.dumps(mixed, ensure_ascii=False), encoding="utf-8")
    r = run.cmd("done", "--node", fx["id"])
    after = json.loads((pathlib.Path(run.dir) / "state.json").read_text(encoding="utf-8")).get("loop", {}).get("coverage_after") or {}
    check(r.returncode == 0 and after.get("round") == nx["round"] and after.get("items")
          and all(x["total"] == 1 and x["after"] == 0 for x in after["items"]),
          f"修正前の母数 1・修正後に engine が数えた 0 が記録に残る（拒否には使わない。rc={r.returncode} / {after}）")
    check(len(fix["changes"]) >= 2 and r.returncode == 0 and "読んだ先: out_path" in r.stdout,
          f"赤を見た修正と見ていない修正（文書）が混じる周の clean は通る——周の全体で見る。返答は out_path から読む。"
          f"**この周に作ったばかりのファイルを指す申告も通る**（採点する版でなく作業ツリーを数えるため。rc={r.returncode}: {(r.stdout + r.stderr).strip()[-140:]}）")
    rm(run.tmp)


def load_review_rules(repo):
    """rules を読み、engine と同じ道具（INJECT）を差し込んだうえで、**git だけを repo に固定**して返す。

    読み込みは engine の load_rules そのもの（INJECT の差し込みも含む）で、台本の中で手順を組み直さない。
    engine の util.GIT_CWD はモジュールの大域なので、台本を同時に走らせるとここを書き換え合う
    （2 本の台本が別の repo を指すと、後から走った方が『git が動かない』で落ちる）。
    同ファイルの test_freeze_revision_on_real_intent_to_add と同じ作法で、呼び先だけを差し替える。
    道具を手で選んで写すと、rules が新しい道具を使った周に台本の中でだけ NameError になる。
    """
    sys.path.insert(0, str(PLUGIN))
    from engine.rules import load_rules  # noqa: E402
    gpath = PLUGIN / "graphs" / "review-loop.json"
    mod = load_rules(gpath, json.loads(gpath.read_text(encoding="utf-8")))

    def pinned_git(*a, **k):
        q = subprocess.run(["git", "-C", str(repo), *a], capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=60)
        return q.stdout if q.returncode == 0 else None
    mod.git = pinned_git
    return mod


def test_external_rankings():
    """外部標準照合の順位: 差分が乗る選択肢は一次情報の順位のどれかで、最上位でないなら上位を採れない理由が要る。
    特徴の一致だけで『定番と同型』と判定した形（実測 2026-09-24: 3 周続けて clean、実際は下位の順位）を塞ぐ"""
    print("外部標準照合の順位: 乗る順位を名指しし、下位なら理由")
    _td, tmp = parallel.workspace("gl-rank-")
    rules = load_review_rules(tmp)
    from engine.util import Reject  # noqa: E402
    chk = rules.POST_CHECKS["external_rankings"]
    row = {"problem": "役の書いた文字列からコマンドを組んで走らせる", "source": "https://cheatsheetseries.owasp.org/cheatsheets/OS_Command_Injection_Defense_Cheat_Sheet.html",
           "ranked": ["コマンドを呼ばない", "データとコマンドを構造で分ける", "文字列を検証する"]}

    def run(r):
        try:
            chk(None, "p1.external_standards", {"rankings": [r]}, None)
            return None
        except Reject as e:
            return str(e)
    check(run({**row, "diff_at": "コマンドを呼ばない"}) is None, "順位: 最上位に乗るなら理由は要らない")
    try:
        chk(None, "p1.external_standards", {"rankings": []}, None)
        got = None
    except Reject as e:
        got = str(e)
    check(got and "rankings_none" in got, f"順位: 空の順位は、付けられない理由（rankings_none）が無ければ拒む（{(got or '通った')[:60]}）")
    try:
        chk(None, "p1.external_standards", {"rankings": [], "rankings_none": "差分に一般化した問題が無い（上限を 1 か所に寄せるだけ）"}, None)
        got = None
    except Reject as e:
        got = str(e)
    check(got is None, f"順位: 空でも付けられない理由を書けば通る（{got}）")
    got = run({**row, "diff_at": "文字列を検証する"})
    check(got and "why_not_higher" in got, f"順位: 下位に乗るのに上位を採れない理由が無ければ拒む（{(got or '通った')[:60]}）")
    check(run({**row, "diff_at": "文字列を検証する", "why_not_higher": "外部のコマンドを呼ぶこと自体が目的で、構造で分ける API が無い（検査用）"}) is None,
          "順位: 下位でも理由を書けば通る")
    got = run({**row, "diff_at": "OWASP と同型"})
    check(got and "ranked に無い" in got, f"順位: 乗る選択肢を ranked の綴りで名指ししないと拒む（特徴の一致で『同型』と書かせない。{(got or '通った')[:60]}）")
    rm(tmp)


def test_md_links():
    """差分が足した Markdown のリンクの拾い方: コードブロックとコードスパンの外だけ・URL の scheme は引かない・見出しは GitHub の書き方"""
    print("リンク: 差分の追加行から拾い、ファイルと見出しまで引く")
    _td, tmp = parallel.workspace("gl-links-")
    (tmp / "docs").mkdir()
    (tmp / "docs" / "a.md").write_text("# 数える問い（F1）\n## 同じ見出し\n## 同じ見出し\n", encoding="utf-8")
    (tmp / "README.md").write_text("# 表題\n", encoding="utf-8")
    # 参照の定義が前から在る文書（定義の行は追加行でないので、足した参照から定義を引かないと指し先を見ない）
    (tmp / "docs" / "old.md").write_text("# 古い\n\n[r7]: 無い7.md\n", encoding="utf-8")
    for c in (["init", "-q"], ["add", "-A"], ["-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "x"]):
        subprocess.run(["git", *c], cwd=tmp, capture_output=True)
    base = subprocess.run(["git", "rev-parse", "HEAD"], cwd=tmp, capture_output=True, text=True, encoding="utf-8").stdout.strip()
    (tmp / "README.md").write_text("# 表題\n" + "\n".join([
        "[良い](docs/a.md#数える問いf1) [重複の 2 つ目](docs/a.md#同じ見出し-1) [ファイル](docs/a.md) [同じ文書](#表題)",
        "[無いファイル](docs/none.md) [無い見出し](docs/a.md#無い) [外](../outside.md) [url](https://example.invalid/x.md)",
        "`[コードスパン](nope.md)` ![画像は引かない](img.png)", "```", "[フェンスの中](nope2.md)", "```"]) + "\n", encoding="utf-8")
    # 日本語のファイル名の文書も拾う（git の既定は名前を引用符つきの 8 進表記にするので、+++ b/ の行で拾えない）
    (tmp / "docs" / "日本語.md").write_text("# 見出し\n[日本語の名前の文書から](a.md#無い2)\n", encoding="utf-8")
    subprocess.run(["git", "add", "-N", "docs/日本語.md"], cwd=tmp, capture_output=True)
    # 空白を含む名前（git は +++ の行末にタブを付ける）・git add -N していない未追跡・/ で始まるルート基準のリンク
    (tmp / "docs" / "with space.md").write_text("[空白の名前の文書から](a.md#無い3)\n", encoding="utf-8")
    subprocess.run(["git", "add", "-N", "docs/with space.md"], cwd=tmp, capture_output=True)
    (tmp / "notes.md").write_text("[未追跡の文書から](docs/無い4.md) [ルート基準の無い先](/無い5.md)\n", encoding="utf-8")
    # ルート基準のリンクはサブディレクトリの文書から引く（ルートの文書では / の有無で同じ先に解けて見分けられない）
    (tmp / "docs" / "sub.md").write_text("[ルート基準](/README.md#表題)\n", encoding="utf-8")
    # 利用者の diff.noprefix でも拾う・綴りの大小違い（大文字小文字を区別しない FS でも）・.gitignore の対象へのリンクは版に無い
    subprocess.run(["git", "config", "diff.noprefix", "true"], cwd=tmp, capture_output=True)
    (tmp / ".gitignore").write_text("secret.md\n", encoding="utf-8")
    (tmp / "secret.md").write_text("# 秘\n", encoding="utf-8")
    (tmp / "docs" / "case.md").write_text("[大小違い](A.md) [無視対象](../secret.md)\n", encoding="utf-8")
    subprocess.run(["git", "add", "-N", "docs/case.md"], cwd=tmp, capture_output=True)
    # 参照形式・定義の無い参照・index に残るだけの消したファイル・空のディレクトリ
    (tmp / "gone.md").write_text("x\n", encoding="utf-8")
    subprocess.run(["git", "add", "gone.md"], cwd=tmp, capture_output=True)
    (tmp / "gone.md").unlink()
    (tmp / "emptydir").mkdir()
    (tmp / "docs" / "ref.md").write_text("[参照][r1] と [定義なし][nodef] と [消した](../gone.md) と [空](../emptydir)\n\n[r1]: 無い6.md\n",
                                         encoding="utf-8")
    subprocess.run(["git", "add", "-N", "docs/ref.md"], cwd=tmp, capture_output=True)
    (tmp / "docs" / "old.md").write_text("# 古い\n\n[前から在る定義を引く][r7]\n\n[r7]: 無い7.md\n", encoding="utf-8")
    # 参照形式の残りの入口: 足した定義の行だけ（使う参照が無い）・畳んだ形 [文字][]・山括弧の指し先。
    # 拾ってはいけない形: GFM の脚注の定義・添字（x[0][1]）
    (tmp / "docs" / "more.md").write_text("[r8]: 無い8.md\n\n[ok][] と [空白](<a b.md>)\n\n[ok]: a.md\n\n[^1]: 脚注の文\n\n配列は x[0][1] と書く\n",
                                          encoding="utf-8")
    subprocess.run(["git", "add", "-N", "docs/more.md"], cwd=tmp, capture_output=True)
    rules = load_review_rules(tmp)
    errs = rules._md_link_errors(base, str(tmp))
    joined = " / ".join(errs)
    check("gone.md" in joined and "emptydir" in joined,
          f"リンク: index に残るだけの消したファイルと、版のファイルを含まないディレクトリは届かない（{[e for e in errs if 'ref.md' in e]}）")
    # 参照形式は拾わない（リポジトリに 0 件で、拾う入口を足すほど誤検知の面が増えた——4 周目の判定）。台本の文書には参照形式の
    # 定義・参照・畳んだ形・脚注・添字が在るので、拾えば下の字列が出る（否定の検査が恒真にならない）
    check(all(s not in joined for s in ("無い6.md", "[nodef]", "無い7.md", "無い8.md", "脚注の文", "の参照")),
          f"リンク: 参照形式は拾わない（定義・参照・畳んだ形・脚注・添字のどれも。{[e for e in errs if 'ref.md' in e or 'old.md' in e or 'more.md' in e]}）")
    more = " / ".join(e for e in errs if "docs/more.md" in e)
    check("a b.md" in more, f"リンク: 山括弧の指し先も引く（{more[:160]}）")
    errs = [e for e in errs if "docs/ref.md" not in e and "docs/old.md" not in e and "docs/more.md" not in e]
    joined = " / ".join(errs)
    check("docs/case.md:1 の (A.md)" in joined and "secret.md" in joined,
          f"リンク: 綴りの大小違いと .gitignore の対象は版に無い（diff.noprefix の設定でも拾う。{errs}）")
    errs = [e for e in errs if "docs/case.md" not in e]
    joined = " / ".join(errs)
    check(len(errs) == 7 and "docs/none.md" in joined and "#無い" in joined and "リポジトリの外" in joined,
          f"リンク: 届かない 7 件だけを挙げる（無いファイル・無い見出し・リポジトリの外・日本語の名前・空白の名前・未追跡の文書・ルート基準の無い先。{errs}）")
    check("docs/with space.md:1" in joined and "#無い3" in joined, f"リンク: 空白を含む名前の文書の追加行も拾う（{errs}）")
    check("notes.md:1" in joined and "無い4.md" in joined and "無い5.md" in joined and "README.md#表題" not in joined and "docs/sub.md" not in joined,
          f"リンク: git add -N していない未追跡の文書も拾い、/ で始まるリンクはリポジトリのルート基準で引く（{errs}）")
    check("docs/日本語.md:2" in joined and "#無い2" in joined, f"リンク: 日本語のファイル名の文書の追加行も拾う（{errs}）")
    check(not any(x in joined for x in ("nope.md", "nope2.md", "img.png", "example.invalid", "#表題", "同じ見出し-1")),
          "リンク: コードスパン・フェンス・画像・URL の scheme は拾わず、同じ文書の見出しと重複見出しの -1 は届く")
    rm(tmp)


def test_history_rewrites_diagnosis():
    """修正役が読む判定（process.diagnosis）は、履歴の再審（p2.history）が書き直した最新の判定。p2.diagnose だけが書いていた頃は、
    履歴の再審で開き直した単位の class_query を、修正役も母数の突合も読まなかった"""
    print("最新の判定: 履歴の再審が process.diagnosis を書き直す")
    run = Run("histdiag", unattended=True)
    MARK = "履歴の再審で書き直した（検査用）"

    def hook(run, inst, out):
        if inst["node"] == "p2.history":
            return {**out, "units": [{**u, "class_query": {**u["class_query"], "note": MARK}} for u in out["units"]]}
        return None
    drive(run, "runaway", hook=hook, stop_at=lambda nx: nx["round"] == 2 and any(i["node"] == "p3.fix" for i in nx["ready"]))
    units = (run.record()["process"].get("diagnosis") or {}).get("units") or []
    check(units and all(MARK in (u.get("class_query") or {}).get("note", "") for u in units),
          f"修正役が読む判定は、履歴の再審が書いた単位（{[(u.get('class_query') or {}).get('note', '')[:30] for u in units]}）")
    rm(run.tmp)


def test_fix_counts_by_engine():
    """修正の前後の件数は engine が数え、向きは判定者が決める——修正役の total と counts を入力にしていた頃は、counts を
    population に書き換えれば修正後の件数の拒否が外れ、修正後だけ未追跡を外して数えたので判定時 2・修正後 1 の数え違いで
    defects の柵をすり抜けた（2026-09-24 の review-graph 1 周目）"""
    print("修正の件数: engine が修正前（固定した版）と修正後（同じ世界）を数え、向きは判定者の値")
    _td, tmp = parallel.workspace("gl-fixcount-")
    (tmp / "t.py").write_text("BAD = 1\n", encoding="utf-8")
    for c in (["init", "-q"], ["add", "-A"], ["-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "x"]):
        subprocess.run(["git", *c], cwd=tmp, capture_output=True)
    (tmp / "u.py").write_text("BAD = 2\n", encoding="utf-8")   # 未追跡の欠陥（固定した版には入る）
    idx = tmp / ".git" / "gl-idx"   # 作業ツリーの外（add -A に拾われない）で、作業場と一緒に消える
    env = {**os.environ, "GIT_INDEX_FILE": str(idx)}
    subprocess.run(["git", "add", "-A"], cwd=tmp, env=env, capture_output=True)
    tree = subprocess.run(["git", "write-tree"], cwd=tmp, env=env, capture_output=True, text=True, encoding="utf-8").stdout.strip()
    snap = subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", "commit-tree", tree, "-p", "HEAD", "-m", "snap"],
                          cwd=tmp, capture_output=True, text=True, encoding="utf-8").stdout.strip()
    (tmp / "t.py").write_text("GOOD = 1\n", encoding="utf-8")   # 修正役は追跡中の側だけ直した
    rules = load_review_rules(tmp)
    from engine.util import Reject  # noqa: E402
    how = {"patterns": ["BAD"], "paths": ["."], "count": "lines"}
    unit = {"key": "k", "label": "block"}
    board = tmp / ".git" / "gl-board"   # 本物の run と同じく git dir の下（作業ツリーの外）——作業場と一緒に消える
    board.mkdir()
    b = types.SimpleNamespace(round=1, loop_state={}, dir=board, rd={"instances": {}}, nodes={}, output_of_round=lambda n, r: None,
                              state={"validator": str(VALIDATOR), "inputs": {"review_rev": snap}},
                              record={"units": [unit], "questions": [], "materials": {},
                                      "process": {"diagnosis": {"units": [{**unit, "class_query": {"how": how, "counts": "defects", "total": 2}}]}}})
    change = {"unit_key": "k", "what": "直した", "files": ["t.py"], "root_or_symptom": {"kind": "root", "why": "根に当てた（検査用）"},
              "bypass_tried": "修正を残したまま別の値でも確かめた（検査用）", "breaks": {"how": "grep", "result": "壊れていない（検査用）"},
              "precedent": {"problem": "検査用の問題", "source": "https://example.invalid/", "verdict": "adopt", "reason": "検査用に採った"},
              "closure": {"sites": [{"site": "t.py:1", "red_seen": True}, {"site": "u.py:1", "red_seen": True}]},
              "coverage": {"how": how, "counts": "population"}}

    def run(ch):
        try:
            rules.POST_CHECKS["fix_covers_open_units"](b, "p3.fix", {"changes": [ch], "fix_closure": {"status": "clean"}, "wrote_refs": []}, None)
            return None
        except Reject as e:
            return str(e)
    got = run(change)
    check(got and "counts: defects" in got and "1 件を数える" in got,
          f"修正の件数: 修正役が population と書いても判定者の defects で数え、未追跡の側の塞ぎ損ねを拒む（{(got or '通った')[:90]}）")
    b.record["process"]["diagnosis"]["units"] = [unit]   # 判定者が class_query を持たない単位
    got = run({**change, "coverage": {"how": how}})
    check(got and "向きが決まらない" in got, f"修正の件数: 判定者も修正役も向きを書かなければ拒む（柵が黙って外れない。{(got or '通った')[:70]}）")
    b.record["process"]["diagnosis"]["units"] = [{**unit, "class_query": {"how": how, "counts": "defects", "total": 2}}]
    (tmp / "u.py").write_text("GOOD = 2\n", encoding="utf-8")
    got = run(change)
    after = (b.loop_state.get("coverage_after") or {}).get("items") or [{}]
    check(got is None and after[0].get("total") == 2 and after[0].get("after") == 0 and after[0].get("counts") == "defects",
          f"修正の件数: 両方直せば通り、修正前の母数は固定した版で数えた 2・向きは判定者の defects（{got} / {after[0]}）")
    # 母数の一部だけ閉鎖を実証した修正は、残した理由（remaining）が在れば通る——黙って残すのだけを拒む
    got = run({**change, "closure": {"sites": [{"site": "t.py:1", "red_seen": True}]},
               "coverage": {**change["coverage"], "remaining": "u.py の側は別の単位で直す（検査用）"}})
    check(got is None, f"修正の件数: 母数 2 のうち 1 site だけ実証しても、残した理由が在れば通る（{(got or '通った')[:80]}）")
    # 判定者の問いを engine が 0 件と数えた単位（engine_zero）は、判定者の書いた数を母数の下限にしない。今の周の記録だけが効く
    b.record["process"]["diagnosis"]["units"] = [{**unit, "class_query": {"how": how, "counts": "defects", "total": 5}}]
    got = run(change)
    check(got and "判定者が数えた母数は 5" in got, f"修正の件数: 判定者の母数より狭い問いは、理由が無ければ拒む（{(got or '通った')[:80]}）")
    b.loop_state["engine_zero"] = {"round": 1, "keys": ["k"]}
    got = run(change)
    check(got is None, f"修正の件数: engine が判定時に 0 件と数えた単位は、判定者の数で狭めたと言わない（{(got or '通った')[:80]}）")
    b.loop_state["engine_zero"] = {"round": 0, "keys": ["k"]}
    got = run(change)
    check(got and "判定者が数えた母数は 5" in got, f"修正の件数: 前の周の engine_zero は今の周に効かない（{(got or '通った')[:80]}）")
    b.loop_state.pop("engine_zero")
    b.record["process"]["diagnosis"]["units"] = [{**unit, "class_query": {"how": how, "counts": "defects", "total": 2}}]
    # 修正前の数を engine が取れない回は、その理由で止める（数えられない件数で柵を通さない）
    real = rules._run_query
    for side in ("修正前", "修正後"):
        rules._run_query = lambda bb, where, *a, **k: (None, f"検査用: {side}を数えられない") if side in where else real(bb, where, *a, **k)
        try:
            got = run(change)
        finally:
            rules._run_query = real
        check(got == f"検査用: {side}を数えられない", f"修正の件数: {side}を数えられない回は、その理由で拒む（{(got or '通った')[:80]}）")
    # 削除で解く修正: 数える問いが名指ししたファイルを消しても、修正後の数え直しは下調べで拒まない（正当な 0 件）
    (tmp / "u.py").unlink()
    got = run({**change, "coverage": {"how": {**how, "paths": ["u.py", "t.py"]}},
               "closure": {"sites": [{"site": "u.py", "red_seen": True}, {"site": "t.py", "red_seen": True}]}})
    check(got is None, f"修正の件数: 修正で消したファイルを名指しした問いも、修正後は 0 件として数える（{(got or '通った')[:80]}）")
    for x in (board, idx):
        rm(x) if x.is_dir() else x.unlink()
    rm(tmp)


def test_graphcheck_review_shapes():
    """graphcheck が review-loop の graph で見る形: inspector を貼る渡し方の役名・schema の正規表現・数える問いの型の写し"""
    print("graphcheck（review-loop）: 役名の綴り・壊れた正規表現・数える問いの型の食い違いで落ちる")
    gc = PLUGIN / "scripts" / "graphcheck.py"
    g = json.loads((PLUGIN / "graphs" / "review-loop.json").read_text(encoding="utf-8"))
    _td, tmp = parallel.workspace("gl-gcr-")
    (tmp / "graphs").mkdir()
    shutil.copytree(PLUGIN / "prompts", tmp / "prompts")
    shutil.copytree(PLUGIN / "rules", tmp / "rules")

    def broken(mutate, want, desc):
        bad = json.loads(json.dumps(g))
        mutate(bad)
        pth = tmp / "graphs" / "review-loop.json"
        pth.write_text(json.dumps(bad, ensure_ascii=False), encoding="utf-8")
        r = subprocess.run([PY, str(gc), str(pth), str(VALIDATOR)], capture_output=True, text=True, encoding="utf-8", timeout=600)
        check(r.returncode == 1 and want in r.stdout and "Traceback" not in r.stderr, f"{desc}（NG『{want}』で exit 1。{r.stdout.strip()[-80:]}）")
    cq = lambda b, nid: b["$defs"]["class_query"]["properties"]   # 数える問いの外側の型は $defs の 1 定義（nid は使わない）
    broken(lambda b: b["deliver"].__setitem__("paste_roles", ["convergence-loops:inspecter"]), "agents/ に無い", "graphcheck: 貼る渡し方の役名の綴り違い")
    broken(lambda b: b["nodes"]["p4.scalars"]["schema"]["properties"]["scalars"].__setitem__("patternProperties", {"^x_[a-z0-9_+$": {"type": "number"}}),
           "正規表現", "graphcheck: 壊れた patternProperties の正規表現")
    # 数える問いの型は engine の 1 つの定義を $ref で引く——写しは無いので、崩れうるのは参照の側だけ
    broken(lambda b: cq(b, "p2.rejudge").__setitem__("how", {"$ref": "engine#/count_hwo"}), "が引けない", "graphcheck: 引けない $ref")
    broken(lambda b: b["nodes"]["p4.ci"]["delegate"].__setitem__("model", "hiku"), "delegate は", "graphcheck: 任せ先のモデルの綴り違い")
    broken(lambda b: b["nodes"]["p2.diagnose"].__setitem__("delegate", {"model": "haiku", "why": "検査用"}), "回す側の節（runners）にだけ",
           "graphcheck: 役の節に任せ先は書けない")
    broken(lambda b: b["nodes"]["p1.local_review"].__setitem__("delegate", {"model": "sonnet", "why": "検査用"}), "skills を持つ節に delegate は書けない",
           "graphcheck: skill を呼ぶ節を任せ先に渡せない（入れ子の委任は完了の知らせが届かない）")
    broken(lambda b: b["nodes"]["p1.gate_efficacy"].__setitem__("deadline_minutes", 0), "deadline_minutes は 1 以上の整数",
           "graphcheck: 期限は 1 以上の整数（分）")
    broken(lambda b: b["nodes"]["p3.delta_gates"]["delegate"].__setitem__("background", "yes"), "delegate.background は真偽",
           "graphcheck: 背景の任せ先の旗が真偽でない")
    broken(lambda b: b["nodes"]["p4.ci"]["deps"].append("p3.delta_gates"), "背景の節（delegate.background）を",
           "graphcheck: 背景の節（受領しか返さない線）を締めの節が待つ")
    broken(lambda b: b.pop("deadline_minutes") and b["nodes"]["p4.final_gates"].pop("deadline_minutes"), "期限（deadline_minutes）が節にも",
           "graphcheck: {{node.deadline_at}} を貼る節に期限が無い")
    broken(lambda b: b["nodes"]["p4.final_gates"].pop("delegate"), "任せ先（delegate）の無い回す側の節",
           "graphcheck: {{node.deadline_at}} を貼る回す側の節に任せ先が無い（自分でやる節に期限は付かない）")
    broken(lambda b: cq(b, "p2.rejudge").__setitem__("how", {"$ref": "engine#/count_how", "type": "string"}), "他の語が並んでいる",
           "graphcheck: 定義を上書きする $ref")
    broken(lambda b: b["$defs"].__setitem__("loop", {"type": "object", "properties": {"x": {"$ref": "#/$defs/loop"}}})
           or b["nodes"]["p4.ci"]["schema"]["properties"].__setitem__("x", {"$ref": "#/$defs/loop"}), "自分を引いている",
           "graphcheck: 自分を引く $ref（展開が止まらない）")
    # 語の検査は patternProperties の値の schema の中まで降りる（走査は engine の walk_schema 1 本）
    broken(lambda b: b["nodes"]["p4.scalars"]["schema"]["properties"]["scalars"]["patternProperties"]["^x_[a-z0-9_]+$"].__setitem__("minimun", 0),
           "'minimun'", "graphcheck: patternProperties の値の中の綴り違いの語")
    # 素材の宣言と書き先: 片方だけに在る素材を両向きで撃つ（書き先だけ＝柵をすり抜ける／宣言だけ＝誰も書かない）
    broken(lambda b: b["nodes"]["p4.ci"].__setitem__("materials", []), "が揃わない", "graphcheck: 書き先に在って宣言に無い素材")
    broken(lambda b: b["nodes"]["p4.scalars"].__setitem__("materials", ["scalars"]), "が揃わない", "graphcheck: 宣言に在って誰も書かない素材")
    broken(lambda b: b["nodes"]["p4.ci"]["writes"].append({"op": "set", "to": "materials", "from": "material"}), "materials そのもの",
           "graphcheck: 素材を丸ごと書く書き先（宣言と照合できない）")
    # op ごとの名乗り（writes_material）が無い op は落とす——名前の表を別に持つと、op を足した周に表への追記を忘れても通った
    rp = tmp / "rules" / "review-loop.py"
    orig = rp.read_text(encoding="utf-8")
    rp.write_text(orig.replace("premise_question.writes_material = False\n", ""), encoding="utf-8")
    pth = tmp / "graphs" / "review-loop.json"
    pth.write_text(json.dumps(g, ensure_ascii=False), encoding="utf-8")
    r = subprocess.run([PY, str(gc), str(pth), str(VALIDATOR)], capture_output=True, text=True, encoding="utf-8", timeout=600)
    check(orig.count("premise_question.writes_material = False\n") == 1 and r.returncode == 1 and "writes_material" in r.stdout,
          f"graphcheck: 素材を書くかを名乗らない rules の op（{r.stdout.strip()[-80:]}）")
    rp.write_text(orig, encoding="utf-8")
    rm(tmp)


def test_engine_rewind_and_guards():
    """engine の撃ち直し（Board.rewind）と、周を進める機械の柵のうち主経路から届きにくい入口を 1 本ずつ撃つ。
    撃ち直しは今の周に節が出した物だけを外し、set でない書き込み・前の周の出力には触らない"""
    print("撃ち直しの口: 機械の節は戻さない・set の欄だけ外す・append は残す・条件外の節は印だけ／偽の rewound は止める")
    sys.path.insert(0, str(PLUGIN))
    from engine.board import Board  # noqa: E402
    from engine.advance import run_driver_node  # noqa: E402
    run = Run("rewind")
    drive(run, "std", stop_at=lambda nx: nx["round"] == 2 and any(i["node"] == "p2.diagnose" for i in nx["ready"]))
    b = Board(run.dir)
    fixes_before = len(b.record["process"].get("fixes") or [])
    try:
        b.rewind(["p1.worktree_after"], by="検査")
        got = "通った"
    except SystemExit:
        got = "止まった"
    check(got == "止まった", f"撃ち直し: 機械の節は戻さない（{got}）")
    na = next((k for k, v in b.rd["na"].items()), None)
    out_na = dict(b.state["outputs"]).get(na)
    removed = b.rewind(["p1.external_standards"] + ([na] if na else []), by="検査")
    check("materials.external_standards" in removed["p1.external_standards"] and "external_standards" not in b.record["materials"]
          and "p1.external_standards" not in b.rd["done"],
          f"撃ち直し: 今の周に走った節の set の欄と done の印を外す（{sorted(removed['p1.external_standards'])}）")
    check(na is None or (na not in b.rd["na"] and b.state["outputs"].get(na) == out_na and removed[na] == {}),
          f"撃ち直し: 条件外の節は印だけを外し、前の周の出力には触らない（{na}）")
    b2 = Board(run.dir)
    removed = b2.rewind(["p3.fix"], by="検査")   # 前の周に走った節（この周はまだ）: 何も外さない
    check(len(b2.record["process"].get("fixes") or []) == fixes_before and removed["p3.fix"] == {},
          f"撃ち直し: append の書き込みと前の周の出力は外さない（fixes {fixes_before} 件のまま。{removed['p3.fix']}）")
    # この周に走った節（p3.fix を済ませた後）: set の欄は外し、append の process.fixes は外さない
    run2 = Run("rewind2")
    drive(run2, "std", stop_at=lambda nx: nx["round"] == 1 and any(i["node"] == "p4.ci" for i in nx["ready"]))
    b3 = Board(run2.dir)
    n_fixes = len(b3.record["process"].get("fixes") or [])
    removed = b3.rewind(["p3.fix"], by="検査")["p3.fix"]
    check(n_fixes >= 1 and len(b3.record["process"].get("fixes") or []) == n_fixes and "materials.fix_closure" in removed
          and "process.fixes" not in removed,
          f"撃ち直し: この周に走った節でも、外すのは set の欄だけ（append の process.fixes {n_fixes} 件は残す。{sorted(removed)}）")
    rm(run2.tmp)
    # 偽の rewound: 戻したと言うのに戻っていない返りは止める（同じ機械の節を回し続ける形）
    fake = types.SimpleNamespace(rules=types.SimpleNamespace(BUILTINS={"x": lambda b, nid: {"ok": False, "rewound": ["p0.base"]}}),
                                 dir=run.dir, round=b.round, state={"outputs": {}}, trace=lambda *a, **k: None,
                                 node_state=lambda nid: "done", deps_ok=lambda nid: False, nodes=b.nodes)
    try:
        run_driver_node(fake, "p1.worktree_after", {"builtin": "x"}, [])
        got = "通った"
    except SystemExit:
        got = "止まった"
    check(got == "止まった", f"機械の節: 戻したと言うのに戻っていない rewound の返りは止める（{got}）")
    fake.rules = types.SimpleNamespace(BUILTINS={"x": lambda b, nid: {"ok": False, "rewound": "p0.base"}})
    import contextlib  # noqa: E402
    import io  # noqa: E402
    err = io.StringIO()
    try:
        with contextlib.redirect_stderr(err):
            run_driver_node(fake, "p1.worktree_after", {"builtin": "x"}, [])
        got = "通った"
    except SystemExit:
        got = "止まった"
    except Exception as e:
        got = f"例外 {type(e).__name__}"
    # 止まった理由まで見る——型の柵を外しても、文字列を 1 文字ずつ節と読んだ先の『戻っていない』で止まる
    check(got == "止まった" and "節の名前の一覧で返せ" in err.getvalue(),
          f"機械の節: rewound が節の名前の一覧でない返り（文字列）は止める（{got}。{err.getvalue().strip()[:60]}）")
    # まだ書かれていない欄を指す writes は飛ばす（戻す節の set の書き先がこの周にまだ無い）
    b4 = Board(run.dir)
    b4.record["materials"].pop("external_standards", None)
    b4.record.pop("process", None)   # 書き先の途中（process）ごと無い——引く途中で KeyError になる経路
    try:
        removed = b4.rewind(["p1.external_standards"], by="検査")["p1.external_standards"]
        got = sorted(removed)
    except Exception as e:
        got = f"例外 {type(e).__name__}"
    check(isinstance(got, list) and "materials.external_standards" not in got,
          f"撃ち直し: まだ書かれていない欄は飛ばす（例外で止まらない。{got}）")
    rm(run.tmp)


def test_judge_output_needs_precedents_schema():
    """judge の返答を書く節の schema に precedents の宣言が無い graph は、先行例の行を数える口が消えるので拒む（fail-closed）。
    主経路では役の返答が先に型で落ちるので、ここは判定の口を直に呼ぶ"""
    print("判定の口: precedents を宣言しない graph を拒む")
    _td, tmp = parallel.workspace("gl-jprec-")
    for c in (["init", "-q"], ["-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "--allow-empty", "-m", "x"]):
        subprocess.run(["git", *c], cwd=tmp, capture_output=True)
    rules = load_review_rules(tmp)
    from engine.util import Reject  # noqa: E402
    b = types.SimpleNamespace(round=1, loop_state={}, dir=tmp, record={"materials": {}, "units": [], "questions": []},
                              state={"validator": str(VALIDATOR), "inputs": {}},
                              graph={"nodes": {"p2.diagnose": {"schema": {"properties": {}}, "reads": []}}})
    try:
        rules.POST_CHECKS["judge_output"](b, "p2.diagnose", {"units": [], "questions": [], "one_shot_closes": []}, None)
        got = "通った"
    except Reject as e:
        got = str(e)
    check("schema に precedents が無い" in got, f"判定の口: precedents を宣言しない節の返答は拒む（{got[:80]}）")
    rm(tmp)


def test_no_new_awaiting_after_judge():
    """判定の後の工程は人待ちを新しく立てない——人待ちの問いの無い素材を awaiting_human と書いた返答は、その節の done で拒む
    （検証器は周の最後に落とすだけで、書いた節に返らなかった。2026-09-24: 任せ先の p4.ci が、緑の CI を field の問いを
    理由に awaiting_human と書いた）"""
    print("判定の後の人待ち: 問いの無い awaiting_human は書いた時点で拒む")
    run = Run("noawait")
    seen = {}

    def hook(run, inst, out):
        if inst["node"] == "p4.ci" and "rc" not in seen:
            r = run.done(inst["id"], {"material": M("awaiting_human", reason="runner で確かめる話があるので（検査用の取り違え）")})
            seen["rc"], seen["err"] = r.returncode, r.stderr
            if r.returncode == 0:
                raise RuntimeError("柵が効かなかった")
        return None
    try:
        drive(run, "std", hook=hook, stop_at=lambda nx: nx["round"] >= 2)
    except RuntimeError:
        pass
    check(seen.get("rc") == 1 and "人待ちの問い（kind=awaiting）が無い" in seen.get("err", "") and "not_run" in seen.get("err", ""),
          f"判定の後の人待ち: 問いの無い awaiting_human を書いた p4.ci は拒む（{seen.get('err', '').strip()[-80:]}）")
    rm(run.tmp)


def test_count_budget():
    """1 周に数える問いを走らせる量の上限。1 回ごとの上限だけでは、差し戻しのたびに全単位を走らせ直す周の総量に天井が無い。
    差し戻し（Reject）の done は盤面を保存しないので、量は盤面の隣のファイルに刻む"""
    print("数える問いの量: 周ごとの上限・差し戻しも数える・周が変われば数え直す")
    _td, tmp = parallel.workspace("gl-budget-")
    (tmp / "a.txt").write_text("x\n", encoding="utf-8")
    for c in (["init", "-q"], ["add", "-A"], ["-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "x"]):
        subprocess.run(["git", *c], cwd=tmp, capture_output=True)
    rules = load_review_rules(tmp)
    b = types.SimpleNamespace(dir=tmp / "board", round=1, loop_state={})
    how = {"patterns": ["x"], "paths": ["a.txt"], "count": "lines"}
    got = rules._run_query(b, "t", how, str(tmp))
    bf = tmp / "board" / "count-budget.json"
    bud = json.loads(bf.read_text(encoding="utf-8")) if bf.is_file() else {}
    check(got == (1, "") and bud.get("calls") == 1 and bud.get("round") == 1,
          f"数える量: 走らせた回数は盤面の隣のファイルに残る（差し戻しの done でも数える。{got} / {bud}）")
    bf.write_text(json.dumps({"round": 1, "calls": rules.COUNT_BUDGET["calls"], "seconds": 0}), encoding="utf-8")
    got = rules._run_query(b, "t", how, str(tmp))
    check(got[0] is None and "上限" in got[1], f"数える量: 1 周の上限に達したら走らせない（{got[1][:60]}）")
    bf.write_text(json.dumps({"round": 1, "calls": 0, "seconds": rules.COUNT_BUDGET["seconds"]}), encoding="utf-8")
    got = rules._run_query(b, "t", how, str(tmp))
    check(got[0] is None and "上限" in got[1], f"数える量: 時間の上限でも止まる（{got[1][:60]}）")
    b.round = 2
    got = rules._run_query(b, "t", how, str(tmp))
    check(got == (1, ""), f"数える量: 周が変われば数え直す（{got}）")
    # 固定した版で数えた答えは盤面に取っておく——同じ問いの出し直しは上限を食わない
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=tmp, capture_output=True, text=True, encoding="utf-8").stdout.strip()
    got = [rules._run_query(b, "t", how, str(tmp), rev=head) for _ in range(3)]
    bud = json.loads(bf.read_text(encoding="utf-8"))
    check(got == [(1, "")] * 3 and bud.get("calls") == 2,
          f"数える量: 固定した版で数えた答えは取っておき、出し直しは上限を食わない（{got} / calls {bud.get('calls')}）")
    bad = {"patterns": ["x"], "paths": ["nope/"], "count": "lines"}
    for _ in range(2):
        rules._run_query(b, "t", bad, str(tmp), rev=head)
    bud = json.loads(bf.read_text(encoding="utf-8"))
    check(bud.get("calls") == 4, f"数える量: 走らせられなかった問いは取っておかない（一時的な失敗で出し直しが詰まらない。calls {bud.get('calls')}）")
    rm(tmp)


def test_wrote_refs_main_path():
    """**主経路（loop.py done）で、呼び元まで含めた性質を撃つ。**

    直に `_cite_errors` を呼ぶ腕は、呼び元 `fix_covers_open_units` のガードを通らないので、
    **呼び元に欠陥が入っても緑のまま**になる（読了の記録を盤面へ書くのは呼び元で、関数は盤面を触らない）。
    呼び元に `if refs:` を戻すと、この台本の『申告が空の周も、今の周の刻印で書かれる』腕だけが赤になる。
    主経路で撃てる性質はここに置く。
    """
    print("修正側の裏取り（主経路）: 空申告の周の刻印・ディレクトリ指しの文言・申告件数の上限")
    run = Run("mainpath")
    nx = drive(run, "std", stop_at=lambda n: any(i["node"] == "p3.fix" for i in n["ready"]))
    fx = next(i for i in nx["ready"] if i["node"] == "p3.fix")
    fix = answers(run, "std", nx["round"])["p3.fix"](None)
    board = pathlib.Path(run.dir)

    def loop_state():
        return json.loads((board / "state.json").read_text(encoding="utf-8")).get("loop", {})

    (run.repo / "docs").mkdir(exist_ok=True)
    (run.repo / "docs" / "d.md").write_text("# d" + chr(10), encoding="utf-8")
    r = run.done(fx["id"], {**fix, "wrote_refs": [{"kind": "text", "cite": "# d", "target": "docs", "where": "README.md"}]})
    check(r.returncode == 1 and "ディレクトリなど" in r.stderr and "に無い" not in r.stderr,
          f"主経路: 実在するディレクトリを指した回は『ファイルでない』（rc={r.returncode}: {r.stderr.strip()[-110:]}）")
    # **申告の件数は型で上限を持つ**（maxItems を外しても緑だった＝一度も効いたことがなかった）
    many = [{"kind": "text", "cite": "# demo", "target": "README.md", "where": "src/a.py"}] * 51
    r = run.done(fx["id"], {**fix, "wrote_refs": many})
    check(r.returncode == 1 and "wrote_refs" in r.stderr and "超え" in r.stderr,
          f"主経路: 申告 51 件は型で落ちる（rc={r.returncode}: {r.stderr.strip()[-110:]}）")
    # **1 件あたりの長さも型で縛る。** 上限が無いと、役の返答 1 つで走査語をいくらでも長くできる
    r = run.done(fx["id"], {**fix, "wrote_refs": [{"kind": "text", "cite": "x" * 501, "target": "README.md", "where": "src/a.py"}]})
    check(r.returncode == 1 and "字を超えている" in r.stderr,
          f"主経路: 501 字の cite は型で落ちる（rc={r.returncode}: {r.stderr.strip()[-90:]}）")
    r = run.done(fx["id"], {**fix, "wrote_refs": [{"kind": "text", "cite": "# demo", "target": "d/" * 151, "where": "README.md"}]})
    check(r.returncode == 1 and "target" in r.stderr and "字を超えている" in r.stderr,
          f"主経路: 301 字の target は型で落ちる（rc={r.returncode}: {r.stderr.strip()[-90:]}）")
    # **where は必須**——書いた場所を申告しないと、指し先と同じファイルかどうかを誰も見られない
    r = run.done(fx["id"], {**fix, "wrote_refs": [{"kind": "text", "cite": "# demo", "target": "README.md"}]})
    where_missing = r
    # 区別語は型の拒否文（『必須の欄』）——関数の側の空の where の拒否も同じ形を止めるので、『where』の一語では
    # 型の宣言を外しても緑だった（kind と同じく、型は役の入口・関数は直に呼ぶ入口を守る）
    check(where_missing.returncode == 1 and "必須の欄 'where'" in where_missing.stderr,
          f"主経路: where を落とした申告は型で落ちる（rc={where_missing.returncode}: {where_missing.stderr.strip()[-90:]}）")
    # **where も target と同じ規律で解く。** 理由を捨てて None に倒していたとき、綴りを変えた where は
    # target と同じファイルでも印（self）が付かずに黙って通った
    r = run.done(fx["id"], {**fix, "wrote_refs": [{"kind": "text", "cite": "# demo", "target": "README.md", "where": "./README.md"}]})
    check(r.returncode == 1 and "書いた場所" in r.stderr and "正規形で書け" in r.stderr,
          f"主経路: 正規形でない where は拒む（印が黙って消えない。rc={r.returncode}: {r.stderr.strip()[-90:]}）")
    # **指し先は次の周の版に入るファイルに限る。** .gitignore に当たるファイルは FS には在るが、周の頭に
    # add -A で固める版にもコミットにも入らない
    (run.repo / ".gitignore").write_text("ign.md" + chr(10), encoding="utf-8")
    (run.repo / "ign.md").write_text("# 無視指定の中の見出し" + chr(10), encoding="utf-8")
    r = run.done(fx["id"], {**fix, "wrote_refs": [{"kind": "text", "cite": "# 無視指定の中の見出し", "target": "ign.md", "where": "README.md"}]})
    check(r.returncode == 1 and "版の一覧に出ない" in r.stderr and "の中に無い" not in r.stderr,
          f"主経路: .gitignore に当たる指し先は『版に入らない』で拒む（rc={r.returncode}: {r.stderr.strip()[-90:]}）")
    r = run.done(fx["id"], {**fix, "wrote_refs": [{"kind": "text", "cite": "# demo", "target": "README.md", "where": "ign.md"}]})
    check(r.returncode == 1 and "書いた場所 'ign.md'" in r.stderr and "版の一覧に出ない" in r.stderr,
          f"主経路: .gitignore に当たる where も拒む（rc={r.returncode}: {r.stderr.strip()[-90:]}）")
    # **読了の記録が無い（none の）回は、拒否文に『読んだ記録が無い』を併記しない**——併記は absent の
    # 回だけ。条件を『read でない』に広げると、フックの入っていない環境の正直な申告に疑いが付く
    r = run.done(fx["id"], {**fix, "wrote_refs": [{"kind": "text", "cite": "Data Platform の責務", "target": "README.md", "where": "src/a.py"}]})
    check(r.returncode == 1 and "の中に無い" in r.stderr and "読んだ記録が無い" not in r.stderr,
          f"主経路: 記録の無い環境では拒否文に読了の疑いを併記しない（{r.stderr.strip()[-90:]}）")
    # **ファイルそのものを指した申告（kind=file）は、指し先が版に在るかだけを見る。** 字列の在る・無いの 1 種類で
    # 見ていた頃は、ファイル名の指しを正直に申告すると指し先の本文に自分のパスが無いので必ず落ちた
    r = run.done(fx["id"], {**fix, "wrote_refs": [{"kind": "file", "target": "docs/nowhere.md", "where": "README.md"}]})
    check(r.returncode == 1 and "作業ツリーに無い" in r.stderr and "の中に無い" not in r.stderr,
          f"主経路: 無いファイルを指した kind=file の申告は『作業ツリーに無い』で拒む（{r.stderr.strip()[-90:]}）")
    r = run.done(fx["id"], {**fix, "wrote_refs": [{"cite": "# demo", "target": "README.md", "where": "src/a.py"}]})
    check(r.returncode == 1 and "必須の欄 'kind'" in r.stderr,
          f"主経路: kind を落とした申告は型で落ちる（rc={r.returncode}: {r.stderr.strip()[-90:]}）")
    r = run.done(fx["id"], {**fix, "wrote_refs": [{"kind": "text", "cite": "# demo", "target": "README.md", "where": "d/" * 151}]})
    check(r.returncode == 1 and "where" in r.stderr and "字を超えている" in r.stderr,
          f"主経路: 301 字の where は型で落ちる（rc={r.returncode}: {r.stderr.strip()[-90:]}）")
    # **申告が空の周も読了の記録が今の周で書かれる**——呼び元のガードを通らない直呼びでは測れない性質
    r = run.done(fx["id"], {**fix, "wrote_refs": []})
    ls = loop_state()
    check(r.returncode == 0 and ls.get("wrote_refs_reads", {}).get("round") == nx["round"]
          and ls["wrote_refs_reads"]["items"] == [],
          f"主経路: **申告が空の周も、今の周の刻印で書かれる**（rc={r.returncode} / {ls.get('wrote_refs_reads')}）")
    # **申告は記録に届き、読み手が居る。** graph の p3.fix の writes が process.fixes へ積み、
    # r1.minimality がその欄を reads に宣言している——pick から落ちると独立の目が申告を見られなくなる
    rec = run.record()
    fixes = (rec.get("process") or {}).get("fixes") or []
    check(fixes and "wrote_refs" in fixes[-1],
          f"申告は記録の process.fixes に載る（r1.minimality が読む欄。keys={sorted(fixes[-1]) if fixes else None}）")
    rm(run.tmp)


def test_wrote_refs_reads_reach_next_prompt():
    """**読了の記録が、次の周の判定役のプロンプトに実際に描画される。** graph の reads・2 本のプロンプトの穴・
    rules が書く鍵は別々のファイルに在り、3 つを揃えてずらしても graphcheck も台本も緑のままだった
    （穴が黙って『この周には無い』に置き換わる）。描画した本文に値が入ることを見る。"""
    print("修正側の裏取り: 申告の読了の記録が、次の周の p2.diagnose の本文に描画される")
    run = Run("readsprompt")

    def hook(run, inst, out):
        if inst["node"] == "p3.fix" and isinstance(out, dict) and not out.get("wrote_refs"):
            return {**out, "wrote_refs": [{"kind": "text", "cite": "# demo", "target": "README.md", "where": "src/a.py"},
                                          {"kind": "file", "target": "src/b.py", "where": "README.md"}]}
    nx = drive(run, "std", hook=hook,
               stop_at=lambda n: n["round"] >= 2 and any(i["node"] == "p2.diagnose" for i in n["ready"]))
    pd = next((i for i in nx.get("ready") or [] if i["node"] == "p2.diagnose"), None)
    body = pathlib.Path(pd["prompt_file"]).read_text(encoding="utf-8") if pd else ""
    head = "修正役が書いた指しの指し先を、前の周の p3.fix を受理した時点で、この run の誰かが全文読んだ記録"
    tail = body.split(head, 1)[1][:1500] if head in body else ""
    check(pd is not None and "README.md" in tail and "src/a.py" in tail and "src/b.py" in tail and '"file"' in tail
          and '"round": 1' in tail.replace('"round":1', '"round": 1'),
          f"2 周目の p2.diagnose に 1 周目の申告の読了の記録が描画される（{tail[-200:]!r}）")
    # **記録の規則は検証器の表から貼る**（状態ごとに要る欄・開いたユニットを出どころにできない種類）。判定役が
    # これを知らずに書き、done の差し戻しで初めて知る往復が 10 周で 6 回あった
    check("decided（resolution が要る）" in body and "origin にも depends にもできない" in body and "{{" not in body,
          "描画した p2.diagnose に、問いの状態の表と出どころの規則が貼られ、穴が残らない")
    rm(run.tmp)


def test_scope_is_repo_root_based():
    """**走査範囲の `:(top)` は、サブディレクトリから起こした run で効く。**

    engine は `git -C <init した場所>` で打つので、裸のパスはその場所からの相対に解決される。
    `:(top)` を外しても全件緑だった——この pathspec magic は一度も効いたことがなかった。
    """
    print("修正側の裏取り: サブディレクトリから起こした run でも、指し先はリポジトリのルート基準で解ける")
    run = Run("subdir")
    sub = run.repo / "src"          # ここを cwd にすると、裸の 'README.md' は src/README.md を指す
    mod = load_review_rules(sub)
    board = run.tmp / "sb"; board.mkdir(parents=True, exist_ok=True)
    b = types.SimpleNamespace(dir=board, round=1, loop_state={})
    check(not (sub / "README.md").exists(), "前提: src/README.md は無い（ルートの README.md だけが在る）")
    errs, _ = mod._cite_errors(b, "p3.fix", [{"kind": "text", "cite": "# demo", "target": "README.md", "where": "src/a.py"}], None, "wrote_refs")
    check(errs == [], f"サブディレクトリから打っても、ルートの README.md を指せる（{errs}）")
    # **指摘側も同じルート基準で数える**（pathspec の無い grep は起点の配下しか数えなかった）
    rev = sh(run.repo, "git", "rev-parse", "HEAD").stdout.strip()
    errs, _ = mod._cite_errors(b, "p0.purpose_review", [{"cite": "# demo", "hits": 1}], rev, "findings")
    check(errs == [], f"サブディレクトリから打っても、指摘側はルートの README.md の字列を数える（{errs}）")
    rm(run.tmp)


def test_wrote_refs_direct_arms():
    """**主経路から届かない分岐を、直に呼んで撃つ**（素の文字列・target が空・外指し・バイナリ・NUL・盤面を触らないこと）。

    `loop.py done` を通すと graph の schema（type object / minLength 1）が先に当たるので、素の文字列と
    空の target の拒否文は主経路では出ない（主経路で同じ形を出すと型で落ちる——test_wrote_refs_main_path）。
    `_cite_errors` の docstring は「到達する経路が在る——検証器の台本はこの関数を直に呼ぶ」を柵を残す理由に
    挙げているので、**その主張を真にする腕をここに置く**（主張と検査のどちらかを消す、ではなく検査を足す側）。
    """
    print("修正側の裏取り: 主経路から届かない分岐を直に呼んで撃つ")
    run = Run("direct")
    mod = load_review_rules(run.repo)
    b = types.SimpleNamespace(dir=run.dir, round=1, loop_state={})
    errs, _ = mod._cite_errors(b, "p3.fix", ["# demo"], None, "wrote_refs")
    check(len(errs) == 1 and "素の文字列" in errs[0], f"素の文字列の行は errs に落ちる（{errs}）")
    errs, _ = mod._cite_errors(b, "p3.fix", [{"cite": "# demo", "target": "README.md"}], None, "wrote_refs")
    check(len(errs) == 1 and "kind" in errs[0] and "file" in errs[0], f"kind を欠いた行は errs に落ちる（{errs}）")
    errs, _ = mod._cite_errors(b, "p3.fix", [{"kind": "text", "cite": "# demo", "target": "README.md", "where": "  "}], None, "wrote_refs")
    check(len(errs) == 1 and "where" in errs[0] and "空" in errs[0], f"where が空白だけの行は errs に落ちる（印を 3 値にしない。{errs}）")
    try:
        mod._cite_errors(b, "p0.purpose_review", [{"cite": "# demo", "hits": 1}], None, "findings")
        check(False, "指摘側に版を渡さない呼び方は拒む（通った）")
    except Exception as e:
        check("版が固まっていない" in str(e), f"指摘側に版を渡さない呼び方は拒む（{str(e)[:60]}）")
    errs, _ = mod._cite_errors(b, "p0.purpose_review", [{"cite": "a" + chr(10) + "b", "hits": 1}], "HEAD", "findings")
    check(len(errs) == 1 and "行単位の git grep" in errs[0], f"指摘側の改行の拒否は git grep の理由を言う（{errs}）")
    errs, _ = mod._cite_errors(b, "p3.fix", [{"kind": "text", "cite": "# demo", "target": "  ", "where": "src/a.py"}], None, "wrote_refs")
    check(len(errs) == 1 and "target" in errs[0] and "空" in errs[0], f"target が空白だけの行は errs に落ちる（{errs}）")
    # **リポジトリの外を指す申告は、読む前に弾く。** `Path(root) / tgt` は tgt が絶対パスなら結合を捨てるので、
    # 閉じ込めが無いと hook_evidence が stat / read_bytes で柵の外のファイルを開いた（拒まれるのはその後）。
    opened = []
    _orig_hook = mod.hook_evidence
    mod.hook_evidence = lambda bd, doc, **k: (opened.append(doc), _orig_hook(bd, doc, **k))[1]
    try:
        (run.repo / "outlink").symlink_to("/etc/hosts")
        for tgt in ("/etc/hosts", "../../../../etc/hosts", "outlink"):
            opened.clear()
            errs, _ = mod._cite_errors(b, "p3.fix", [{"kind": "text", "cite": "# demo", "target": tgt, "where": "src/a.py"}], None, "wrote_refs")
            check(len(errs) == 1 and "リポジトリの外" in errs[0] and opened == [],
                  f"リポジトリの外を指す申告は**開く前に**弾く（{tgt}: errs={errs} opened={opened}）")
    finally:
        mod.hook_evidence = _orig_hook
    (run.repo / "blob.bin").write_bytes(b"\x00\x01MARKER_IN_BINARY\x00\x02")
    # **ファイルそのものを指した申告（kind=file）は中身を数えない**——バイナリの画像や生成物を指すのは正当な形
    errs, _ = mod._cite_errors(b, "p3.fix", [{"kind": "file", "target": "blob.bin", "where": "src/a.py"}], None, "wrote_refs")
    check(errs == [], f"kind=file の申告はバイナリの指し先でも、版に在れば通る（{errs}）")
    errs, _ = mod._cite_errors(b, "p3.fix", [{"kind": "text", "cite": "MARKER_IN_BINARY", "target": "blob.bin", "where": "src/a.py"}], None, "wrote_refs")
    check(len(errs) == 1 and "バイナリ" in errs[0],
          f"バイナリの指し先は『数えられない』で拒む（『中に無い』ではない。{errs}）")
    errs, _ = mod._cite_errors(b, "p3.fix", [{"kind": "text", "cite": "NOT_THERE", "target": "blob.bin", "where": "src/a.py"}], None, "wrote_refs")
    check(len(errs) == 1 and "バイナリ" in errs[0],
          f"バイナリは字列の有無に依らず『数えられない』（中を数えない指し先に『在る・無い』を言わない。{errs}）")
    # **NUL を含む字列は拒否文で返す（例外で落とさない）**——理由は rules の同じ分岐の注記
    errs, _ = mod._cite_errors(b, "p3.fix", [{"kind": "text", "cite": "# demo" + chr(0), "target": "README.md", "where": "src/a.py"}], None, "wrote_refs")
    check(len(errs) == 1 and "NUL" in errs[0], f"NUL を含む cite は errs に落ちる（例外にしない。{errs}）")
    errs, reads = mod._cite_errors(b, "p3.fix", [{"kind": "text", "cite": "# demo", "target": "READ" + chr(0) + "ME.md", "where": "src/a.py"}], None, "wrote_refs")
    check(len(errs) == 1 and "NUL" in errs[0], f"NUL を含む target も errs に落ちる（{errs}）")
    # **text の指しは cite が要る**（file の指しには要らない——種類で満たし方が分かれる）
    errs, _ = mod._cite_errors(b, "p3.fix", [{"kind": "text", "target": "README.md", "where": "src/a.py"}], None, "wrote_refs")
    check(len(errs) == 1 and "cite（作業ツリーで引ける字列）が空" in errs[0], f"cite の無い text の指しは errs に落ちる（{errs}）")
    # **版の一覧が引けない回は、合格にせず止める**（git が動かないのに『版に無い』とも『在る』とも言わない）
    _iv = mod._in_version
    try:
        mod._in_version = lambda rels: None
        try:
            mod._cite_errors(b, "p3.fix", [{"kind": "file", "target": "README.md", "where": "src/a.py"}], None, "wrote_refs")
            got = "通った"
        except Exception as e:
            got = str(e)
    finally:
        mod._in_version = _iv
    check("数え直せない（git が動かない）" in got, f"版の一覧が引けない回は止まる（{got[:80]}）")
    # **数えは上限の先まで読まない**（生成物を指した回に丸ごとメモリへ載せない）
    _cap = mod.READ_CAP
    try:
        mod.READ_CAP = 3
        errs, _ = mod._cite_errors(b, "p3.fix", [{"kind": "text", "cite": "# demo", "target": "README.md", "where": "src/a.py"}], None, "wrote_refs")
    finally:
        mod.READ_CAP = _cap
    check(len(errs) == 1 and "大きすぎて" in errs[0], f"上限を超える指し先は数えずに拒む（{errs}）")
    # **版には在るが作業ツリーで開けない指し先を、例外にせず拒む**（commit した後に消した・置き換えた）
    (run.repo / "gone.md").write_text("# gone" + chr(10), encoding="utf-8")
    sh(run.repo, "git", "add", "gone.md"); (run.repo / "gone.md").unlink()
    errs, _ = mod._cite_errors(b, "p3.fix", [{"kind": "text", "cite": "# gone", "target": "gone.md", "where": "src/a.py"}], None, "wrote_refs")
    check(len(errs) == 1 and "いまの作業ツリーに無い" in errs[0], f"index に在るが消した指し先は『作業ツリーに無い』で拒む（例外にしない。{errs}）")
    # **中を開かない kind=file も、消した指し先を通さない**——一覧は実物の index を引くので git rm せずに消したファイルが
    # 残り、周の頭に固める版（add -A）には入らないのに通っていた
    errs, _ = mod._cite_errors(b, "p3.fix", [{"kind": "file", "target": "gone.md", "where": "src/a.py"}], None, "wrote_refs")
    check(len(errs) == 1 and "いまの作業ツリーに無い" in errs[0], f"kind=file でも消した指し先は拒む（{errs}）")
    errs, _ = mod._cite_errors(b, "p3.fix", [{"kind": "file", "target": "README.md", "where": "gone.md"}], None, "wrote_refs")
    check(len(errs) == 1 and "書いた場所 'gone.md'" in errs[0] and "いまの作業ツリーに無い" in errs[0], f"消した where も拒む（{errs}）")
    # **版に在り作業ツリーにも在るが開けない指し先は『数えられない』で拒む**（権限で読めない。root と windows は権限で止められない）
    if os.name != "nt" and os.geteuid() != 0:
        locked = run.repo / "locked.md"; locked.write_text("# locked" + chr(10), encoding="utf-8")
        sh(run.repo, "git", "add", "locked.md"); locked.chmod(0)
        try:
            errs, _ = mod._cite_errors(b, "p3.fix", [{"kind": "text", "cite": "# locked", "target": "locked.md", "where": "src/a.py"}], None, "wrote_refs")
        finally:
            locked.chmod(0o644)
        check(len(errs) == 1 and "作業ツリーで数えられない" in errs[0], f"開けない指し先は『数えられない』で拒む（例外にしない。{errs}）")
    else:
        check(True, "開けない指し先の腕は root / windows では撃てない（権限で読みを止められない）")
    # **指し先が FIFO に置き換わっても、開いて止まらない**（上限付きの読みは通常のファイルだけを開く）。書き手を
    # 立てておくので、柵が外れた写しでは開いて読み、止まらずに別の文（中に無い）で赤になる
    if hasattr(os, "mkfifo"):
        import threading  # noqa: E402
        (run.repo / "pipe.md").write_text("# pipe" + chr(10), encoding="utf-8")
        sh(run.repo, "git", "add", "pipe.md"); (run.repo / "pipe.md").unlink(); os.mkfifo(run.repo / "pipe.md")

        def w():
            with open(run.repo / "pipe.md", "wb") as f:
                f.write(b"other bytes")
        threading.Thread(target=w, daemon=True).start()
        errs, _ = mod._cite_errors(b, "p3.fix", [{"kind": "text", "cite": "# pipe", "target": "pipe.md", "where": "src/a.py"}], None, "wrote_refs")
        check(len(errs) == 1 and "通常のファイルでない" in errs[0], f"FIFO に置き換わった指し先は開かずに拒む（{errs}）")
    else:
        check(True, "FIFO に置き換わった指し先は開かずに拒む（この OS には FIFO が無い）")
    # **symlink の輪を含む指し先を、例外にせず拒む**（3.12 以前の resolve は輪を RuntimeError で投げる）
    try:
        (run.repo / "loopa").symlink_to("loopb"); (run.repo / "loopb").symlink_to("loopa")
        errs, _ = mod._cite_errors(b, "p3.fix", [{"kind": "text", "cite": "x", "target": "loopa/x.md", "where": "src/a.py"}], None, "wrote_refs")
        check(len(errs) == 1, f"symlink の輪を含む指し先は拒否文で返る（例外にしない。{errs}）")
    except RuntimeError as e:
        check(False, f"symlink の輪を含む指し先は拒否文で返る（例外にしない。{e}）")
    # **数え直しの関数は盤面を触らない**——読了の記録を盤面へ書くのは呼び元（空の周の刻印は主経路の腕が見る）。
    # 関数の中で書いていた頃は、target を持つ呼び元が 2 本に増えた周に同じ鍵を黙って上書きする形だった
    check(reads == [] and b.loop_state == {},
          f"引けなかった申告は reads に載らず、関数は盤面（loop_state）を書かない（{reads} / {b.loop_state}）")
    rm(run.tmp)


def test_wrote_refs_reads_and_dir_target():
    """**読了の記録が在る盤面で、指し先の解決と版の問いの枝を撃つ**（併記・ディレクトリ・版を渡す誤り・
    ルートを引けない回・字面・.gitignore・正規形・大小違い・書いた場所の印・ルート基準）。
    """
    print("修正側の裏取り: 読了の記録が在る周の併記と、target にディレクトリを書いた回の拒否")
    run = Run("reads")
    mod = load_review_rules(run.repo)
    board = run.tmp / "board"; board.mkdir(parents=True, exist_ok=True)
    b = types.SimpleNamespace(dir=board, round=2, loop_state={})
    # フックが書く形の記録を 1 行（別の文書の読み）。この指し先の読みは無いので absent になる
    (board / "reads.jsonl").write_text(json.dumps(
        {"ts": "2026-09-22T00:00:00", "session_id": "s", "agent_id": None,
         "path": str((run.repo / "src" / "b.py").resolve()), "file_sha": "0" * 64,
         "bytes": 1, "partial": False, "tool_use_id": "toolu_x"}, ensure_ascii=False) + chr(10),
        encoding="utf-8")
    errs, reads = mod._cite_errors(b, "p3.fix", [{"kind": "text", "cite": "存在しない見出し", "target": "README.md", "where": "src/a.py"}], None, "wrote_refs")
    check(len(errs) == 1 and "読んだ記録が無い" in errs[0],
          f"記録は在るがこの指し先の読みが無い回は、拒否文に併記する（{errs}）")
    check(reads and reads[0]["state"] == "absent", f"引いた指しは読了の状態つきで返る（{reads}）")
    # **ディレクトリを target に書いても通さない**（存在だけを見ると配下全体を数える形になる）。
    # **文言まで見る。** 『無い』で拒んでいた頃は、実在するディレクトリに対して事実と違う診断を返していた
    errs, _ = mod._cite_errors(b, "p3.fix", [{"kind": "text", "cite": "def g", "target": "src", "where": "src/a.py"}], None, "wrote_refs")
    check(len(errs) == 1 and "ディレクトリなど" in errs[0] and "無い" not in errs[0],
          f"target にディレクトリを書いた回は『ファイルでない』で拒む（作業ツリー。{errs}）")
    # **指し先を持つ呼び元に版を渡すのは呼び方の誤り**（製品経路の呼び元は作業ツリーしか渡さない）。
    # 以前は版の枝が在り、直呼びの腕だけがそこを撃っていた——製品に無い組み合わせを腕が作っていた
    rev = sh(run.repo, "git", "rev-parse", "HEAD").stdout.strip()
    try:
        mod._cite_errors(b, "p3.fix", [{"kind": "text", "cite": "def g", "target": "src/a.py", "where": "src/a.py"}], rev, "wrote_refs")
        check(False, "指し先を持つ呼び元に版を渡すと止まる（止まらなかった）")
    except ValueError as e:
        check("作業ツリー" in str(e), f"指し先を持つ呼び元に版を渡すと止まる（{str(e)[:80]}）")
    opened = []
    _og, _oh = mod.git, mod.hook_evidence
    mod.git = lambda *a, **k: None
    mod.hook_evidence = lambda bd, doc, **k: (opened.append(doc), _oh(bd, doc, **k))[1]
    try:
        mod._cite_errors(types.SimpleNamespace(dir=board, round=3, loop_state={}), "p3.fix",
                         [{"kind": "text", "cite": "# demo", "target": "/etc/hosts"}], None, "wrote_refs")
        check(False, "ルートを引けない回は Reject で止まる（止まらなかった）")
    except Exception as e:
        check("ルートを引けない" in str(e) and opened == [],
              f"ルートを引けない回は**何も開かずに**止まる（{str(e)[:70]} / opened={opened}）")
    finally:
        mod.git, mod.hook_evidence = _og, _oh
    (run.repo / "a1.md").write_text("GLOB_ONLY_IN_A1" + chr(10), encoding="utf-8")
    (run.repo / "a[1].md").write_text("別の本文" + chr(10), encoding="utf-8")
    errs, _ = mod._cite_errors(b, "p3.fix", [{"kind": "text", "cite": "GLOB_ONLY_IN_A1", "target": "a[1].md", "where": "src/a.py"}], None, "wrote_refs")
    check(len(errs) == 1 and "の中に無い" in errs[0],
          f"glob のメタ文字を含む指し先は字面のファイルだけを数える（a1.md の中身で通らない。{errs}）")
    (run.repo / ".gitignore").write_text("ign.md" + chr(10), encoding="utf-8")
    (run.repo / "ign.md").write_text("# 無視指定の中の見出し" + chr(10), encoding="utf-8")
    errs, _ = mod._cite_errors(b, "p3.fix", [{"kind": "text", "cite": "# 無視指定の中の見出し", "target": "ign.md", "where": "src/a.py"}], None, "wrote_refs")
    check(len(errs) == 1 and "版の一覧に出ない" in errs[0] and "の中に無い" not in errs[0],
          f".gitignore に当たる指し先は、字列が在っても『版に入らない』で拒む（{errs}）")
    errs, _ = mod._cite_errors(b, "p3.fix", [{"kind": "text", "cite": "# demo", "target": "./README.md", "where": "src/a.py"}], None, "wrote_refs")
    check(len(errs) == 1 and "正規形で書け" in errs[0] and "'README.md'" in errs[0],
          f"'./' 付きの指し先は正規形を示して拒む（{errs}）")
    # **ファイルシステムと git で見え方が割れる回を「中に無い」に丸めない。** 大小を区別しない FS では
    # 'README.MD' が FS には在り、版には無い。区別する FS では単に『無い』。どちらの FS でも**事実どおりの
    # 理由**が返ることを見る（検査の本数は FS に依らず 1 本）
    folds = (run.repo / "readme.md").exists()   # README.md が在る repo で、小文字の綴りが見えるか
    errs, _ = mod._cite_errors(b, "p3.fix", [{"kind": "text", "cite": "# demo", "target": "README.MD", "where": "src/a.py"}], None, "wrote_refs")
    # Windows の resolve は実在ファイルの綴りをディスク上の綴りに直すので、先に『正規形で書け: README.md』に当たる
    # ——どちらも事実どおりなので両方を受ける（windows-latest で実際の文を見るまでは広く取る）
    want = ("版の一覧に出ない", "正規形で書け: 'README.md'") if folds else ("いまの作業ツリーに無い",)
    check(len(errs) == 1 and any(w in errs[0] for w in want),
          f"大文字小文字違いの指し先は、FS に応じた事実どおりの理由で拒む（{'大小を区別しない' if folds else '区別する'} FS: {errs}）")
    (run.repo / "NOTE.md").write_text("くわしくは docs/nowhere.md の「取り込みの段」を見よ" + chr(10), encoding="utf-8")
    b3 = types.SimpleNamespace(dir=board, round=4, loop_state={})
    errs, items = mod._cite_errors(b3, "p3.fix", [{"kind": "text", "cite": "「取り込みの段」", "target": "NOTE.md", "where": "NOTE.md"}], None, "wrote_refs")
    check(errs == [] and items[0]["self"] is True,
          f"where と target が同じ指しは通るが、印が付く（{errs} / {items[0].get('self') if items else None}）")
    errs, items = mod._cite_errors(b3, "p3.fix", [{"kind": "text", "cite": "# demo", "target": "README.md", "where": "NOTE.md"}], None, "wrote_refs")
    check(errs == [] and items[0]["self"] is False, f"where と target が別なら印は付かない（{items[0].get('self') if items else None}）")
    # **指し先はリポジトリのルート基準で解く。** プロセスの cwd に解決していたとき、
    # 読了の証拠が黙って none に落ちた（--dir を付けた run は cwd がリポジトリの外に在る）
    only = run.repo / "only-here.md"
    only.write_text("# ここにしか無い見出し" + chr(10), encoding="utf-8")
    with open(board / "reads.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps({"ts": "2026-09-22T00:00:01", "session_id": "s", "agent_id": "a1",
                            "path": str(only.resolve()),
                            "file_sha": hashlib.sha256(only.read_bytes()).hexdigest(),
                            "bytes": only.stat().st_size, "partial": False,
                            "tool_use_id": "toolu_y"}, ensure_ascii=False) + chr(10))
    errs, got = mod._cite_errors(b, "p3.fix", [{"kind": "text", "cite": "# ここにしか無い見出し", "target": "only-here.md", "where": "src/a.py"}], None, "wrote_refs")
    check(errs == [] and got and got[0]["state"] == "read",
          f"リポジトリのルート基準で解くので、読了の記録がこの指し先に当たる（errs={errs} state={got}）")
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


def test_frozen_review_revision():
    """**その周に採点する版をリビジョンで固定する。** 採点役が生きた作業ツリーを読んでいたとき、
    同じ周のうちに writer が直すと判定の行番号と母数が途中で腐った（実測 r6）。
    一度は写しを展開して渡したが、写しは .git を持たないので役が git を打てず、engine の数え直しだけが
    生きた木を見るという割れ方をした（実測 r8）——渡すのはリビジョン 1 つにする。"""
    print("台本: 周の頭と P3 の後に版を固定し、採点役には写しでなくリビジョンを渡す")
    run = Run("frozen", unattended=True)
    src = run.repo / "src" / "a.py"
    before = src.read_text(encoding="utf-8")
    for _ in range(20):                                   # 版が固まる所まで台本で進める
        nx = run.next()
        if not nx.get("ready"):
            break
        if run.state()["loop"].get("reviewed_revision"):
            break
        for inst in nx["ready"]:
            a = answers(run, "std", nx["round"])[inst["node"]]
            run.done(inst["id"], a(inst))
    rev = run.state()["loop"].get("reviewed_revision")
    check(rev and len(rev) == 40, f"周の頭で版が固まる（{rev}）")
    check(run.state()["inputs"].get("review_rev") == rev, "固定した版が役へ渡る入力に載る")
    show = lambda r: subprocess.run(["git", "show", f"{r}:src/a.py"], cwd=run.repo,
                                    capture_output=True, text=True, encoding="utf-8", timeout=120)
    check(show(rev).stdout == before, "固定した版は周の頭の中身を持つ（BASE でも HEAD でもない）")
    # **周の途中で writer が直しても、採点役が見る版は動かない**——これがこの節の目的
    src.write_text(before + "\n# 周の途中で writer が直した行\n", encoding="utf-8")
    check(show(rev).stdout == before, "周の途中の書き換えは固定した版に入らない（採点の足場が動かない）")
    check(src.read_text(encoding="utf-8") != before, "生きた作業ツリーの側はちゃんと変わっている（対照）")
    # **役は渡された場所で git を打てる**（写しを渡していた頃は .git が無くて打てなかった）
    r = subprocess.run(["git", "-C", str(run.repo), "grep", "-F", "-c", "--", "min(x, limit)", rev],
                       capture_output=True, text=True, encoding="utf-8", timeout=120)
    check(r.returncode == 0 and ":1" in r.stdout, f"固定した版に対して git grep が打てる（{r.stdout.strip()[:40]}）")
    src.write_text(before, encoding="utf-8")
    # **P3 の後にも取り直す。** 周の頭だけで固定していたとき、R1〜R4 は『修正後の差分』と
    # 『修正前の版』を同時に渡された（実測 r8: 局所レビューが現物で見つけた）
    first = rev
    src.write_text(before + "\n# P3 の修正に見立てた行\n", encoding="utf-8")
    # 取り直しは rules の _take_diff が呼ぶ——部品を直に呼んで、接尾辞に依らず固定が走ることを見る
    import importlib.util  # noqa: E402
    spec = importlib.util.spec_from_file_location("gl_rv2", PLUGIN / "rules" / "review-loop.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    calls = []
    # **手で組んだ値を置かない。** 代役は実物の git をそのまま通す（呼ばれた綴りだけ記録する）
    # ——決め打ちの 40 桁を置いていたとき、実装が一時 index の経路へ移っても代役は気づかず、
    # 呼ばれない綴りに答え続けた（実測 r10）。実物を通せば、綴りが変われば代役ごと壊れて見える
    def _passthrough(*a, **k):
        calls.append(a)
        env = {**os.environ, **k["env"]} if k.get("env") else None
        q = subprocess.run(["git", "-C", str(run.repo), "-c", "user.email=t@t", "-c", "user.name=t", *a],
                           capture_output=True, text=True, encoding="utf-8", errors="replace", env=env)
        return q.stdout if q.returncode == 0 else None
    mod.git = _passthrough
    class _B:
        loop_state, state, round, dir = {}, {"inputs": {}}, 1, run.tmp
    mod._freeze_revision(_B())
    check(_B.state["inputs"].get("review_rev"), "_freeze_revision は版を入力に載せる")
    src_rules = (PLUGIN / "rules" / "review-loop.py").read_text(encoding="utf-8")
    check("if not suffix:\n        _freeze_revision" not in src_rules,
          "版の固定は接尾辞で分岐しない（P3 の後の取り直しでも走る）")
    # **git の返り値を 1 組で済ませない。** 腕が『全部失敗』1 通りだけだったとき、
    # 失敗（None）と『変更が無い』（空文字）を同じ値に潰す実装が素通りした（実測 r9）——
    # このループの主経路（p0.base が git add -N を打つ）で必ず起きる形だった。
    # 実際に起きうる組を並べて、**どれが来ても「その周の作業を含まない版」に倒れない**ことを見る
    mod.Reject = RuntimeError

    # **腕が食わせる値は実物の git から取る。** 手で組んでいたとき『2 つとも成功して空を返した』
    # という実物には在りえない組を食わせ、実物が通る枝でなく別の枝を通って緑になっていた（実測 r10）。
    # ここでは本物のリポジトリを 3 状態作って、各副コマンドの終了コードを実測し、
    # util.git の契約（非 0 → None）に写してから腕に食わせる。
    def _real(state):
        """本物の git を 3 状態で打ち、{副コマンド: util.git が返す値} を作る。手順は _worktree_tree と同じ
        （本物の index の場所を引き、一時 index に写し、refresh・add -A・write-tree）。"""
        _td, r = parallel.workspace("gl-real-")   # 持ち手が例外の経路でも消す（関数の終わりまで _td を握る）
        sh(r, "git", "init", "-q", ".")
        sh(r, "git", "config", "user.email", "t@example.com")
        sh(r, "git", "config", "user.name", "t")
        if state != "no-commit":
            (r / "f.txt").write_text("a\n", encoding="utf-8")
            sh(r, "git", "add", "-A"); sh(r, "git", "commit", "-qm", "base")
        if state == "intent-to-add":
            (r / "n.txt").write_text("new\n", encoding="utf-8")
            sh(r, "git", "add", "-N", "n.txt")
        out = {}
        idx = r / ".git" / "gl-idx" / "index"   # 作業ツリーの外（add -A に拾われない）で、持ち手と一緒に消える
        idx.parent.mkdir()
        env = {**os.environ, "GIT_INDEX_FILE": str(idx)}
        q = subprocess.run(["git", "-C", str(r), "rev-parse", "--path-format=absolute", "--git-path", "index"],
                           capture_output=True, text=True, encoding="utf-8", errors="replace")
        out["git-path"] = q.stdout if q.returncode == 0 else None
        if pathlib.Path((out["git-path"] or "").strip()).is_file():
            shutil.copyfile(out["git-path"].strip(), idx)
        for name, argv, use_env in (("update-index", ["update-index", "-q", "--really-refresh"], True),
                                    ("add", ["add", "-A"], True), ("write-tree", ["write-tree"], True),
                                    ("rev-parse", ["rev-parse", "HEAD"], False)):
            q = subprocess.run(["git", "-C", str(r), *argv], capture_output=True, text=True,
                               encoding="utf-8", errors="replace", env=env if use_env else None)
            out[name] = q.stdout if q.returncode == 0 else None
        tree = (out.get("write-tree") or "").strip()
        if tree:
            head = (out.get("rev-parse") or "").strip()
            argv = ["commit-tree", tree] + (["-p", head] if head else []) + ["-m", "x"]
            q = subprocess.run(["git", "-C", str(r), *argv], capture_output=True, text=True,
                               encoding="utf-8", errors="replace")
            out["commit-tree"] = q.stdout if q.returncode == 0 else None
        else:
            out["commit-tree"] = None
        return out

    def _git(spec):
        # rev-parse は 2 つの問い（index の場所と HEAD）に使われるので、index の場所だけ別の鍵で答える
        return lambda *a, **k: spec.get("git-path" if "--git-path" in a else (a[0] if a else ""), spec.get("*"))

    real = {st: _real(st) for st in ("no-commit", "clean", "intent-to-add")}
    # **実物が返す形をそのまま記録に残す**（次に実装が変わった周、腕が古いことがここで分かる）
    check(real["intent-to-add"]["write-tree"] is not None,
          "実物: intent-to-add の index でも、一時 index への add -A → write-tree は木を返す")
    check(real["no-commit"]["rev-parse"] is None,
          "実物: commit が 1 つも無いと rev-parse HEAD は非 0（util.git は None）")
    cases = [
        ("commit が 1 つも無い（実物の値）", real["no-commit"], "親なしの版"),
        ("変更が無い（実物の値）", real["clean"], "版"),
        ("intent-to-add が在る（実物の値。主経路で必ず起きる）", real["intent-to-add"], "版"),
        ("git そのものが動かない", {"*": None}, "止まる"),
        ("一時 index への add が失敗", {**real["clean"], "add": None}, "止まる"),
        ("本物の index の場所が引けない", {**real["clean"], "git-path": None}, "止まる"),
        ("本物の index の場所が空で返る", {**real["clean"], "git-path": "\n"}, "止まる"),
        ("本物の index を写せない（場所がディレクトリ）", {**real["clean"], "git-path": str(run.tmp)}, "止まる"),
        ("一時 index の refresh が失敗", {**real["clean"], "update-index": None}, "止まる"),
        ("write-tree が木を返さない", {**real["clean"], "write-tree": None}, "止まる"),
        ("commit-tree が版を返さない", {**real["clean"], "commit-tree": None}, "止まる"),
    ]
    for name, spec, want in cases:
        mod.git = _git(spec)
        bb = type("_BB", (), {"loop_state": {}, "state": {"inputs": {}}, "round": 1, "dir": run.tmp})()
        try:
            mod._freeze_revision(bb)
            got = bb.state["inputs"].get("review_rev")
        except RuntimeError as e:
            got = "止まった: " + str(e)
        if want == "止まる":
            check(str(got).startswith("止まった") and "版を固定できない" in str(got),
                  f"{name} は理由を名乗って止まる（{str(got)[:60]}）")
        else:
            check(got and not str(got).startswith("止まった") and len(str(got)) == 40,
                  f"{name} は 40 桁の版を採る（{str(got)[:60]}）")
    src.write_text(before, encoding="utf-8")
    rev = first
    # 採点役のプロンプトが、生きた木のパスと読む版の両方を渡す
    nx = run.next()
    seen = [pathlib.Path(i["prompt_file"]).read_text(encoding="utf-8") for i in nx.get("ready") or []
            if i["node"] in ("p1.consistency_bypass", "p2.diagnose", "r3.coherence", "r4.hidden_scope")]
    if seen:
        check(all(rev in s and str(run.repo) in s for s in seen),
              f"採点役のプロンプトはリポジトリのパスと読む版の両方を渡す（{len(seen)} 件）")
    rm(run.tmp)

def test_purpose_review_reruns_when_unvetted():
    """**裏取りの柵より前に書かれた目的監査は、走り直す。**

    監査は 1 周目にしか走らないので、柵が後から入っても判定は作り直されない——旧形の findings が
    9 周にわたって材料に載り続けた（実測 r9-r10: 素の文字列 5 件が減らない）。assemble は
    「材料として使わない」ところまでやっていたが、**走り直しの引き金が無かった**。

    引き金は『柵を通っていない判定が記録に在る』——通った判定は二度と走らないので、
    不利な判定を引くたびに回し直す形にはならない。
    """
    print("目的監査: 裏取りの柵より前の形で凍った判定は走り直す（通った判定は走り直さない）")
    import importlib.util  # noqa: E402
    spec = importlib.util.spec_from_file_location("gl_unvetted", PLUGIN / "rules" / "review-loop.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    check("purpose_review_unvetted" in mod.CONDS, "cond の builtin として登録されている")

    def b(findings, verdict="狭めている"):
        pr = {"verdict": verdict}
        if findings is not None:
            pr["findings"] = findings
        return type("_B", (), {"record": {"process": {"purpose_review": pr}}})()

    f = mod.CONDS["purpose_review_unvetted"]
    check(f(b(["素の文字列の指摘", "もう 1 件"])), "旧形（素の文字列）の判定は走り直す")
    check(f(b([{"text": "x", "hits": 1}])), "dict でも cite が無ければ走り直す")
    check(f(b([{"text": "x", "cite": "a"}, {"text": "y", "hits": 2}])), "1 件でも柵を通っていなければ走り直す")
    check(not f(b([{"text": "x", "cite": "a", "hits": 1}])), "**柵を通った判定は走り直さない**（不利な判定の引き直しを作らない）")
    check(not f(b(None, verdict=None)), "まだ一度も走っていないなら、この引き金では走らせない（round==1 の側が拾う）")
    check(not f(b([], verdict="問題なし")), "findings が空の『問題なし』は走り直さない")
    # **式の正本は 1 か所**——assemble が別の式を持っていると、柵を締めた周に片方だけ古くなる
    src = (PLUGIN / "rules" / "review-loop.py").read_text(encoding="utf-8")
    check(src.count('r.get("cite") for r in rows') == 1,
          f"裏取り済みかを判定する式は 1 か所（{src.count('r.get(\"cite\") for r in rows')} か所）")


def test_loop_state_notes_have_readers():
    """**loop_state に溜める注記の欄には、記録へ写す行が在る。**

    書く所だけ在って読む所が無い欄は、書かれたまま誰の目にも入らない
    （実測 r10: purpose_review_stale が 2 周ぶん書かれ、リポジトリのどこからも読まれていなかった）。
    1 件を直すのでなく**クラスで見る**——次に同じ形の欄を足した周に、ここが赤くなる。

    射程は `ls.setdefault("<名前>", []).append(` の形に絞る（注記を溜める欄だけ）。
    単発の `ls["x"] = …` は返り値や cond から読まれる形が多く、同じ規則では縛れない。
    """
    print("loop_state: 注記を溜める欄には、記録へ写す行が在る（書いて誰も読まない欄を作らない）")
    src = (PLUGIN / "rules" / "review-loop.py").read_text(encoding="utf-8")
    names = sorted(set(re.findall(r'ls\.setdefault\(\s*"([a-z_]+)"\s*,\s*\[\]\s*\)\.append\(', src)))
    check(len(names) >= 2, f"注記を溜める欄が {len(names)} 件（{names}）")
    for n in names:
        check(f'proc["{n}"]' in src, f"{n} は記録へ写される（proc[\"{n}\"] が在る）")


def test_freeze_revision_on_real_intent_to_add():
    """**実物の git で、intent-to-add の index でも版が固定でき、新規ファイルがその版に載る。**

    代役を食わせる腕だけだったとき、本物の index を使う形に戻しても腕は全部緑のままだった
    （実測 r10: 一時 index の指定を落とす注入が赤にならない）——代役は env を見ないので、
    **どの index の上で組むかという肝心の違いが観測できない**。ここだけは実物の git を打つ。

    覆うのはこのループの主経路そのもの: p0.base が未追跡の新規ファイルに `git add -N` を指示し、
    その index では stash create も write-tree も非 0 で返る。
    """
    print("版の固定（実物の git）: intent-to-add の index でも止まらず、新規ファイルが版に載る")
    run = Run("freeze-real")
    g = lambda *a: sh(run.repo, "git", "-c", "user.email=t@t", "-c", "user.name=t", *a)
    (run.repo / "src" / "new.py").write_text("NEW_MARKER = 1" + chr(10), encoding="utf-8")
    g("add", "-N", "src/new.py")
    check(sh(run.repo, "git", "stash", "create").returncode != 0,
          "実物: intent-to-add の index では git stash create が非 0（この経路が使えない理由）")

    import importlib.util  # noqa: E402
    spec = importlib.util.spec_from_file_location("gl_freeze_real", PLUGIN / "rules" / "review-loop.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.Reject = RuntimeError

    def real_git(*a, **k):
        env = {**os.environ, **k["env"]} if k.get("env") else None
        q = subprocess.run(["git", "-C", str(run.repo), "-c", "user.email=t@t", "-c", "user.name=t", *a],
                           capture_output=True, text=True, encoding="utf-8", errors="replace", env=env)
        return q.stdout if q.returncode == 0 else None
    mod.git = real_git
    before_status = sh(run.repo, "git", "status", "--porcelain").stdout
    bb = type("_BB", (), {"loop_state": {}, "state": {"inputs": {}}, "round": 1, "dir": run.tmp})()
    mod._freeze_revision(bb)
    rev = bb.state["inputs"].get("review_rev")
    check(rev and len(rev) == 40, f"intent-to-add でも 40 桁の版を返す（{rev}）")
    listed = sh(run.repo, "git", "ls-tree", "-r", "--name-only", rev).stdout.split()
    check("src/new.py" in listed, f"**未追跡だった新規ファイルがその版に載る**（{listed}）")
    got = sh(run.repo, "git", "grep", "-F", "-cI", "-e", "NEW_MARKER", rev, "--")
    check(got.returncode == 0 and ":1" in got.stdout, f"その版に対して git grep が打てる（{got.stdout.strip()[:40]}）")
    blob = sh(run.repo, "git", "rev-parse", f"{rev}:src/new.py").stdout.strip()
    check(blob == sh(run.repo, "git", "hash-object", "src/new.py").stdout.strip(),
          "intent-to-add のファイルは作業ツリーの今の中身で版に載る（本物の index を写しても i-t-a の扱いは変わらない）")
    # **利用者の index を書き換えない。** 一時 index の指定を落としても版の固定自体は成功する
    # （本物の index への `add -A` が intent-to-add を普通の追加に変えてしまうため）ので、
    # 「止まらないこと」だけ見ていた腕は緑のままだった（実測 r10）。**害は成否でなく副作用の側に在る**
    # ——採点するだけの節が利用者の index を書き換え、その周の突合も p0.base の申告も狂う
    check(sh(run.repo, "git", "status", "--porcelain").stdout == before_status,
          "**版を固定しても利用者の index は動かない**（採点は読むだけ）")
    rm(run.tmp)



def test_freeze_revision_keeps_tracked_ignored():
    """**追跡中だが .gitignore に当たるファイルは、採点する版から落ちない。**

    空の一時 index に `add -A` していたとき、`git add -f` で追跡したファイルは `add -A` に拾われず、版から落ちて
    『削除』に見えた（実測 2026-09-25: 別のリポジトリの run で、判定役がこれを根拠に誤った [block] を出した）。
    本物の index を一時 index に写してから `add -A` する形を、実物の git で見る。写したことで生まれる経路
    （assume-unchanged の印の引き継ぎ・index の無いリポジトリ）も同じ台本で見る。
    """
    print("版の固定（実物の git）: 追跡中の .gitignore 対象は版に載り、利用者の index は動かない")
    import importlib.util  # noqa: E402
    spec = importlib.util.spec_from_file_location("gl_freeze_ign", PLUGIN / "rules" / "review-loop.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.Reject = RuntimeError
    _td, r = parallel.workspace("gl-ign-")
    g = lambda *a: sh(r, "git", "-c", "user.email=t@t", "-c", "user.name=t", *a)

    def real_git(*a, **k):
        env = {**os.environ, **k["env"]} if k.get("env") else None
        q = subprocess.run(["git", "-C", str(r), "-c", "user.email=t@t", "-c", "user.name=t", *a],
                           capture_output=True, text=True, encoding="utf-8", errors="replace", env=env)
        return q.stdout if q.returncode == 0 else None
    mod.git = real_git
    g("init", "-q", ".")
    # **index がまだ無いリポジトリでも固まる**（写す物が無ければ空から始める——追跡中のファイルが無いので落ちる物も無い）
    (r / "first.txt").write_text("first\n", encoding="utf-8")
    check(not (r / ".git" / "index").exists(), "前提: init の直後は index が無い")
    t0 = mod._worktree_tree()
    check("first.txt" in sh(r, "git", "ls-tree", "--name-only", t0).stdout, "index の無いリポジトリでも未追跡の新規ファイルが木に載る")
    (r / ".gitignore").write_text("secret*\n", encoding="utf-8")
    (r / "secret.cfg").write_text("old\n", encoding="utf-8")
    (r / "keep.txt").write_text("keep\n", encoding="utf-8")
    (r / "gone.txt").write_text("gone\n", encoding="utf-8")
    (r / "au.txt").write_text("au-old\n", encoding="utf-8")
    g("add", "first.txt", ".gitignore", "keep.txt", "gone.txt", "au.txt")
    g("add", "-f", "secret.cfg")
    g("commit", "-qm", "base")
    (r / "secret.cfg").write_text("new\n", encoding="utf-8")           # 追跡中の .gitignore 対象を書き換える
    (r / "untracked.txt").write_text("u\n", encoding="utf-8")          # 未追跡の新規
    (r / "secret-local.tmp").write_text("x\n", encoding="utf-8")       # 追跡していない .gitignore 対象
    (r / "gone.txt").unlink()                                          # 追跡中を消す
    g("update-index", "--assume-unchanged", "au.txt")
    (r / "au.txt").write_text("au-new-longer\n", encoding="utf-8")     # 印の付いた追跡中のファイルを書き換える（大きさを変え、同じ秒の racy git と切り分ける）
    idx_before = (r / ".git" / "index").read_bytes()
    status_before = sh(r, "git", "status", "--porcelain").stdout
    bb = type("_BB", (), {"loop_state": {}, "state": {"inputs": {}}, "round": 1, "dir": r / ".git"})()
    mod._freeze_revision(bb)
    rev = bb.state["inputs"].get("review_rev")
    names = sh(r, "git", "ls-tree", "-r", "--name-only", rev).stdout.split()
    blob = lambda path: sh(r, "git", "rev-parse", f"{rev}:{path}").stdout.strip()
    now = lambda path: sh(r, "git", "hash-object", path).stdout.strip()
    check("secret.cfg" in names and blob("secret.cfg") == now("secret.cfg"),
          f"**追跡中の .gitignore 対象は版に今の中身で載る**（削除に見えない。{names}）")
    check("untracked.txt" in names, "未追跡の新規ファイルは版に載り続ける")
    check("secret-local.tmp" not in names, "追跡していない .gitignore 対象は版に載らない")
    check("gone.txt" not in names, "追跡中を消したファイルは版から消える")
    check(blob("au.txt") == now("au.txt"), "assume-unchanged の印を付けたファイルも、書き換えた今の中身で版に載る（写しの印を外す）")
    check((r / ".git" / "index").read_bytes() == idx_before and sh(r, "git", "status", "--porcelain").stdout == status_before,
          "**版を固定しても利用者の index は 1 バイトも動かない**（写しの上だけで組む）")
    # 突合の側も同じ手続きを通る: 追跡中の .gitignore 対象だけを書き換えると、木の id が変わる
    t1 = mod._worktree_tree()
    (r / "secret.cfg").write_text("changed during P1\n", encoding="utf-8")
    check(mod._worktree_tree() != t1, "追跡中の .gitignore 対象だけの書き換えでも、前後の突合の木が変わる（見逃さない）")

def test_engine_provenance_recorded():
    """**どの engine がこの周を回したかを、盤面が毎周持つ。**

    graph は sha で追っているのに engine は誰も見ていなかった。盤面はリポジトリの中に在るので
    「対象を直しながら回す」形になるが、回っているのはインストール済みの版で、作業ツリーの直しは
    次にインストールするまで一度も走らない——『新機構が実走で動いていない』という指摘が 3 周
    出続け、原因（engine が別物）にたどり着くのに 9 周かかった（実測 r10）。
    """
    print("engine の痕跡: どの置き場・どの版の engine が回したかを盤面が持ち、次の周に知らせる")
    run = Run("gl-engine-prov-")
    nx = run.next()
    st = json.loads((run.dir / "state.json").read_text(encoding="utf-8"))
    eng = st.get("engine") or {}
    check(eng.get("root") == str(PLUGIN), f"盤面が engine の置き場を持つ（{eng.get('root')}）")
    check(eng.get("version"), f"盤面が engine の版を持つ（{eng.get('version')!r}）")
    check(any("この周を回した engine" in n for n in (nx.get("notes") or [])),
          "初回は notes で知らせる（記録を開かなくても分かる）")
    # **変わった周だけ痕跡を足す**（毎周足すと、読む側は差分を自分で取ることになる）
    st2 = json.loads((run.dir / "state.json").read_text(encoding="utf-8"))
    check(len(st2.get("engine_changes") or []) == 1,
          f"痕跡は変わった周だけ（{len(st2.get('engine_changes') or [])} 件）")
    nx2 = run.next()
    check(not any("この周を回した engine" in n for n in (nx2.get("notes") or [])),
          "同じ engine で続く周は黙る")
    rm(run.tmp)


def test_review_rev_paragraph_is_uniform():
    """**固定した版を読む節は、生きた木のパスを名乗るとき必ず同じ綴りで版を添える。**

    同じ段落を 7 枚へ手で貼っており、揃っているかを見る所が無かった（実測 r10）——
    1 枚だけ版の無い形に戻っても、残りが正しいので誰も気づかない。

    **射程は graph から導く**（手で並べた一覧にすると、節が増えた周に一覧だけ古くなる）。
    縛るのは `inputs.review_rev` を reads に持つ節だけ——修正・CI・規模の節は
    **生きた木を見るのが正しい**ので、同じ縛りを当てると直すべきでない所が赤くなる
    （最初に全プロンプトへ当てて 5 枚が赤くなった）。
    逐語でなく不変条件で見るのは、節ごとに違ってよい前後（観点の正本・差分の置き場）を固定しないため。
    """
    print("読む版: 固定した版を読む節は、生きた木のパスに必ず版を添える（射程は graph の reads から導く）")
    g = json.loads((PLUGIN / "graphs" / "review-loop.json").read_text(encoding="utf-8"))
    tail, hole = "（読む版: `{{inputs.review_rev}}`）", "{{inputs.cwd}}"
    nodes = [(k, v) for k, v in g["nodes"].items() if "inputs.review_rev" in (v.get("reads") or [])]
    check(len(nodes) >= 7, f"固定した版を読む節が {len(nodes)} 件（graph の reads から数えた）")
    for nid, v in sorted(nodes):
        md = (PLUGIN / "graphs" / v["prompt_file"]).resolve()
        text = md.read_text(encoding="utf-8")
        check(hole in text, f"{nid}: プロンプトが生きた木のパスを名乗る")
        at, n = 0, 0
        while (k := text.find(hole, at)) >= 0:
            at = k + len(hole); n += 1
            check(text[at:at + len(tail)] == tail,
                  f"{nid}: {hole} の直後に読む版が添う（{text[at:at + 24]!r}）")
        check(n == 1, f"{nid}: 生きた木のパスを名乗るのは 1 か所（{n} か所）")


def test_purpose_findings_cited():
    """**指摘は作業ツリーで引ける根拠を連れて来る。** 素の文字列だったとき、リポジトリに 1 件も無い字列を
    根拠にした指摘が 5 周再燃し、毎周ちがう判定者が 0 件を数えて棄却していた（棄却は出す側に返らないので止まらない）。
    境界で数え直し、合わない指摘を受け取らない。"""
    print("台本: 目的の監査の指摘は、作業ツリーで引ける根拠（cite）を連れて来る")
    run = Run("cite", unattended=True)
    target = None
    for _ in range(20):                                          # 監査の節が出る波まで台本で進める
        nx = run.next()
        if not nx.get("ready"):
            break
        for inst in nx["ready"]:
            if inst["node"] == "p0.purpose_review":
                target = inst["id"]
                break
            a = answers(run, "narrowed", nx["round"])[inst["node"]]
            run.done(inst["id"], a(inst))
        if target:
            break
    check(target is not None, "目的の監査の節が出る")
    base = {"verdict": "狭めている", "reason": "目的が実装した範囲に合わせて狭い（検査用）"}
    # ① 実在しない字列は受け取らない（棄却を判定者の手間として毎周繰り返さない）
    r = run.done(target, {**base, "findings": [
        {"text": "document_tail の自己申告が残っている", "cite": "document_tail", "hits": 4}]})
    check(r.returncode == 1 and "1 件も無い" in r.stderr,
          f"作業ツリーに 1 件も無い字列を根拠にした指摘は拒まれる（rc={r.returncode}: {r.stderr[-90:]}）")
    # ② 件数の申告が数え直しと違えば拒む（根拠は在るが、量の主張が現物と合わない）
    r = run.done(target, {**base, "findings": [
        {"text": "上限に触れていない", "cite": "min(x, limit)", "hits": 9}]})
    check(r.returncode == 1 and "数え直し" in r.stderr,
          f"件数の申告が数え直しと違えば拒まれる（rc={r.returncode}: {r.stderr[-90:]}）")
    # ④ **引用は字面として数える。** 既定の git grep は基本正規表現なので、-F を落とすと
    # メタ文字を含む引用が別の物に当たる——現物に在る引用が拒まれ、現物に無い字列が通る
    # （実測 2026-09-21: この腕を足す前は、メタ文字の解釈差が出ない標本しか踏んでいなかった）。
    # 'src/a.py' は現物に 0 件だが、`.` を任意の 1 字として読むと 'src.a.py' 等に当たりうる形
    r = run.done(target, {**base, "findings": [
        {"text": "正規表現として読むと当たる字列", "cite": "def f.x, limit=None.:", "hits": 1}]})
    check(r.returncode == 1 and "1 件も無い" in r.stderr,
          f"メタ文字を含む引用は字面として数える（正規表現なら当たる形が拒まれる。rc={r.returncode}: {r.stderr[-80:]}）")
    # ⑤ 角括弧が不均衡でも、git が落ちて『現物に無い』と逆の拒否文になったりしない
    r = run.done(target, {**base, "findings": [
        {"text": "角括弧が不均衡な引用", "cite": "limit[", "hits": 1}]})
    check(r.returncode == 1 and "Traceback" not in r.stderr,
          f"不均衡な角括弧の引用でも素の例外にならない（rc={r.returncode}: {r.stderr[-80:]}）")
    # ③ 合っていれば通る
    r = run.done(target, {**base, "findings": [
        {"text": "上限に触れていない", "cite": "min(x, limit)", "hits": 1}]})
    check(r.returncode == 0, f"現物と合う根拠なら通る（rc={r.returncode}: {r.stderr[-90:]}）")
    rm(run.tmp)


def test_purpose_cite_counts_frozen_revision():
    """**数えるのは採点役が読むのと同じ固定リビジョン**（生きた作業ツリーではない）。

    生きた木を数えると、周の途中で writer が直した瞬間に、役は自分では制御できない理由で
    返答ごと拒まれる——『行番号も件数も周の終わりまで有効』という名乗りが、まさに拒否の判定に使う
    件数について偽になる（実測 r8: 判定役が [block] として名指しした）。
    """
    print("台本: 根拠の数え直しは、生きた木でなく固定した版を数える")
    run = Run("cite-rev", unattended=True)
    target = None
    for _ in range(20):
        nx = run.next()
        if not nx.get("ready"):
            break
        for inst in nx["ready"]:
            if inst["node"] == "p0.purpose_review":
                target = inst["id"]
                break
            a = answers(run, "narrowed", nx["round"])[inst["node"]]
            run.done(inst["id"], a(inst))
        if target:
            break
    check(target is not None and run.state()["loop"].get("reviewed_revision"), "監査の節が出て、版が固まっている")
    # **周の途中で現物から引用を消す**——固定した版には残っているので、数え直しは通るはず
    src = run.repo / "src" / "a.py"
    src.write_text("def f(x):\n    return x\n", encoding="utf-8")
    live = subprocess.run(["git", "-C", str(run.repo), "grep", "-F", "-c", "--", "min(x, limit)"],
                          capture_output=True, text=True, encoding="utf-8", timeout=120)
    check(live.returncode != 0, f"生きた木からは引用が消えている（対照。rc={live.returncode}）")
    r = run.done(target, {"verdict": "狭めている", "reason": "検査用",
                          "findings": [{"text": "上限に触れていない", "cite": "min(x, limit)", "hits": 1}]})
    check(r.returncode == 0,
          f"固定した版に在る引用は、生きた木から消えていても通る（rc={r.returncode}: {r.stderr[-90:]}）")
    rm(run.tmp)


def test_purpose_verdict_needs_vetted_evidence():
    """**裏取りを通っていない判定は、R2 を止める根拠に使わない。**

    監査は 1 周目にしか走らない（cond）ので、裏取りの柵が入る前に書かれた判定は一度も数え直されないまま
    毎周の判定材料に載り続ける（実測 r9: findings が素の文字列 5 件、うち 4 件は現物に 0 件の字列に乗っていた）。
    あわせて、**根拠 0 件の『狭めている』**が柵を 0 回通って素通りしていた形も塞ぐ。
    """
    print("台本: 裏取りを通っていない『狭めている』は R2 を止めない／根拠 0 件の判定は受け取らない")
    import importlib.util  # noqa: E402 — rules の関数を直に呼ぶ腕
    spec = importlib.util.spec_from_file_location("gl_rv4", PLUGIN / "rules" / "review-loop.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.Reject = RuntimeError
    mod.git = lambda *a: "src/a.py:1\n"

    class _B:
        loop_state = {"reviewed_revision": "deadbeef"}
        state, round, dir = {"inputs": {}}, 1, pathlib.Path(".")

    # ① 根拠 0 件の『狭めている』は受け取らない
    try:
        mod.purpose_findings_cited(_B(), "p0.purpose_review", {"verdict": "狭めている", "findings": []}, None)
        got = "通った"
    except RuntimeError as e:
        got = str(e)
    check("findings が空" in got, f"根拠 0 件の『狭めている』は拒まれる（{got[:60]}）")
    # ② 旧形（素の文字列）の findings も受け取らない
    try:
        mod.purpose_findings_cited(_B(), "p0.purpose_review",
                                   {"verdict": "狭めている", "findings": ["document_tail が残っている"]}, None)
        got = "通った"
    except RuntimeError as e:
        got = str(e)
    check("素の文字列は受け取らない" in got, f"旧形の findings は拒まれる（{got[:60]}）")
    # ③ **rules に実際に判定させる**（台本側で判定を再現していたとき、rules の分岐を消しても緑だった
    #    ——実測 r9: 腕 i5。今周の判定 4 件目『腕が engine の返す値でなく手で組んだ 1 組を食わせる』そのもの）
    # **判定は本物のループに下させる**（台本側で再現していたとき、rules の分岐を消しても緑だった
    #  ——実測 r9: 腕 i5。今周の判定 4 件目『腕が engine の返す値でなく手で組んだ 1 組を食わせる』そのもの）。
    # 記録を古い形（裏取りを通っていない findings）に手当てしてから assemble を走らせる
    for rows, want in (([{"text": "上限に触れていない", "cite": "min(x, limit)", "hits": 1}], "狭めている"),
                       (["document_tail が残っている"], None)):
        run2 = Run("vetted", unattended=True)
        target = None
        for _ in range(30):
            nx = run2.next()
            if not nx.get("ready"):
                break
            target = next((i for i in nx["ready"] if i["node"] == "p3.fix"), None)
            if target:
                break
            for inst in nx["ready"]:
                a = answers(run2, "narrowed", nx["round"])[inst["node"]]
                run2.done(inst["id"], a(inst))
        check(target is not None, "p3.fix が出る所まで回る（この腕の前提）")
        # 記録の側を古い形に差し替える（engine の手当ての口を使う——痕跡が残る）
        f = run2.tmp / "pr.json"
        f.write_text(json.dumps({"verdict": "狭めている", "findings": rows}, ensure_ascii=False), encoding="utf-8")
        run2.cmd("patch", "--path", "process.purpose_review", "--file", str(f),
                 "--reason", "裏取りの有無で R2 の扱いが変わるかを測る（検査用）")
        run2.done(target["id"], answers(run2, "narrowed", run2.state()["round"])["p3.fix"](target))
        got = "（確定せず）"
        for _ in range(12):                    # assemble は p3.fix の後の波で走る
            nx = run2.next()
            st = run2.state()["loop"]
            if st.get("purpose_known") is not None:
                got = st.get("purpose_unusable")
                break
            if nx.get("status") == "awaiting_human" or not nx.get("ready"):
                break
            for inst in nx["ready"]:
                run2.done(inst["id"], answers(run2, "narrowed", nx["round"])[inst["node"]](inst))
        check(got == want,
              f"裏取りの有無で R2 を止めるかが本物の assemble で変わる（{str(rows)[:30]} → {got}、期待 {want}）")
        rm(run2.tmp)


def test_purpose_cite_git_unusable():
    """**git が動かない回を『現物に無い』と取り違えない。** 読めなかった数え直しを 0 件と取り違えると、
    拒否文が事実と逆（『現物に 1 件も無い』）になる——確かめられないものは合格にもしない。"""
    print("台本: 数え直しで git が動かない回は、事実と逆の拒否文を出さない")
    import importlib.util  # noqa: E402 — rules の関数を直に呼ぶ腕
    spec = importlib.util.spec_from_file_location("gl_rv3", PLUGIN / "rules" / "review-loop.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.Reject = RuntimeError
    sys.path.insert(0, str(PLUGIN))
    from engine.util import repo_root as _rr, sum_counts as _sc  # noqa: E402 — engine が差し込む道具のうち、この腕が通るもの
    mod.sum_counts, mod.repo_root = _sc, _rr
    # 数え直しは engine の grep（（出力, ""）か（None, 理由））で走る。git（rev-parse）と grep を別々に差し替えて世界を作る

    class _B:
        loop_state = {"reviewed_revision": "deadbeef"}
        state, round, dir = {"inputs": {}}, 1, pathlib.Path(".")

    out = {"findings": [{"text": "x", "cite": "abc", "hits": 1}]}
    mod.git = lambda *a: None                      # rev-parse も動かない＝git が使えない（ルートも引けない）
    mod.grep = lambda *a: (None, "走らせられない（FileNotFoundError）")
    try:
        mod.purpose_findings_cited(_B(), "p0.purpose_review", out, None)
        got = "止まらなかった"
    except RuntimeError as e:
        got = str(e)
    check("確かめられない" in got or "git が動かない" in got,
          f"git が動かない回は『確かめられない』として拒む（{got[:60]}）")
    check("1 件も無い" not in got, f"事実と逆（現物に無い）とは言わない（{got[:60]}）")
    mod.git = lambda *a: "true\n"   # git は動くが 0 件（一致なしの exit 1 は（"", ""））
    mod.grep = lambda *a: ("", "")
    try:
        mod.purpose_findings_cited(_B(), "p0.purpose_review", out, None)
        got = "止まらなかった"
    except RuntimeError as e:
        got = str(e)
    check("1 件も無い" in got, f"git は動くが 0 件の回は『現物に 1 件も無い』で拒む（{got[:60]}）")
    mod.grep = lambda *a: ("src/a.py:1\n本文だけの行\n", "")
    try:
        mod.purpose_findings_cited(_B(), "p0.purpose_review", out, None)
        got = "止まらなかった"
    except RuntimeError as e:
        got = str(e)
    check("`…:数` の形でない" in got, f"数でない行が混じった git grep -c の出力は、合計せずに止まる（{got[:70]}）")
    # **版が解決できない回を 0 件と取り違えない。** git は動くが、数える版が消えている run では
    # 『現物に 1 件も無い』は偽になる（数えられなかっただけ）——腕が『全部失敗』1 通りだけだったとき、
    # この分岐を消しても緑のまま通った（実測 r9: 腕 i2）
    mod.git = lambda *a: None if a[:2] == ("rev-parse", "--verify") else "true\n"
    mod.grep = lambda *a: (None, "git grep が exit 128——読めなかった問いは 0 件の証拠にならない")
    try:
        mod.purpose_findings_cited(_B(), "p0.purpose_review", out, None)
        got = "止まらなかった"
    except RuntimeError as e:
        got = str(e)
    check("採点する版" in got and "解決できない" in got,
          f"版が解決できない回は『現物に無い』でなく『数え直せない』で拒む（{got[:70]}）")
    check("1 件も無い" not in got, f"事実と逆のことは言わない（{got[:70]}）")


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
    _td_tmp, tmp = parallel.workspace("gl-accept-")
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
    # **入力の宣言の 3 分岐にも腕を置く。** 検査を書いただけでは覆いの証拠にならない——
    # 同じ周の測定で『書いただけの検査が空振りする』が 3 件出ている（f5・f8・f10 が最初は緑）
    for key, mutate, want in (
        ("inputs-missing", lambda b: b.pop("inputs", None), "inputs（どの入力がパスかの宣言）が無い"),
        ("inputs-not-dict", lambda b: b.__setitem__("inputs", ["document"]), "名前 → {kind: …} の辞書"),
        ("inputs-bad-kind", lambda b: b.__setitem__("inputs", {"document": {"kind": "知らない種類"}}),
         "を engine が知らない（使えるのは"),
        # **貼る穴に渡る入力は宣言を持つ**——実在検査の発火条件を『file: の接頭』から『宣言』へ
        # 移したので、宣言を書き忘れた入力は file: の穴に渡っていても実在検査から黙って外れる
        ("inputs-undeclared", lambda b: b["inputs"].pop("review_md", None),
         "の宣言が無い——宣言が無い入力は実在検査に当たらない"),
        # **裸の {{inputs.X}} も見る**——回す側の節は file: 接頭を書けない（別の柵）ので、
        # 接頭だけを見ていたとき、回す側だけが読むパス入力は宣言が無くても init を素通りした
        ("inputs-undeclared-bare", lambda b: b["inputs"].pop("scripts_dir", None),
         "の宣言が無い——宣言が無い入力は実在検査に当たらない"),
    ):
        bad = json.loads(json.dumps(g))
        mutate(bad)
        (tmp / "graphs" / f"bad-{key}.json").write_text(json.dumps(bad, ensure_ascii=False), encoding="utf-8")
        r = subprocess.run([PY, str(PLUGIN / "scripts" / "graphcheck.py"), str(tmp / "graphs" / f"bad-{key}.json"), str(VALIDATOR)],
                           capture_output=True, text=True, encoding="utf-8", timeout=600)
        check(r.returncode == 1 and want in r.stdout,
              f"入力の宣言が壊れた graph は落ち、理由を名指しする（{key}: exit {r.returncode} / {r.stdout[-90:].strip()}）")
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


def test_rejudge_path():
    """**同じ周の往復を、盤面を通る経路で 1 度通す。**

    `p2.rejudge` / `p2.rejudge_third` は graph に在るのに、台本が 1 度も発行していなかった
    （実測 2026-09-13: この 2 節の判定語彙 12 値は到達 0 回）。異議は実運用では engine の外の会話で
    起きており、**盤面を通る経路そのものが誰にも踏まれていなかった**——往復が記録に残ることを
    この節が担っているのに、その担いを検査していない状態だった。
    """
    print("同じ周の往復: 異議 → p2.rejudge が発行され、判定が記録に残る")
    run = Run("rejudge")
    fired = seen = False
    for _ in range(120):
        nx = run.next()
        if nx.get("status") == "awaiting_human" or (not nx["ready"] and nx["status"] in TERMINAL_STATUS):
            break
        if not nx["ready"]:
            raise RuntimeError("ready が空のまま進まない")
        table = answers(run, "std", nx["round"])
        for inst in nx["ready"]:
            out = table[inst["node"]](load_item(inst))
            if inst["node"] == "p3.fix" and isinstance(out, dict):
                for f in {f for c in out.get("changes", []) for f in c.get("files", [])}:
                    q = run.repo / f
                    if q.is_file():
                        q.write_text(q.read_text(encoding="utf-8") + f"# fixed in round {nx['round']}\n", encoding="utf-8")
            if inst["node"] in ("p2.rejudge", "p2.rejudge_third"):
                seen = True
            r = run.done(inst["id"], out, agent_id="judge-1" if inst["node"] == "p2.diagnose" else None)
            if r.returncode != 0:
                raise RuntimeError(f"done {inst['id']} が {r.returncode}: {r.stderr[-800:]}")
            if inst["node"] == "p3.fix" and not fired:
                # 回す側が今の周に異議を出す（実運用は loop.py patch。手当ての痕跡は state.patches に残る）
                f = run.tmp / "obj.json"
                f.write_text(json.dumps({"round": nx["round"], "text": "この修正は入口を 1 つしか塞いでいない"},
                                        ensure_ascii=False), encoding="utf-8")
                pr = run.cmd("patch", "--path", "state.loop.rejudge_requested", "--file", str(f), "--reason", "台本の異議")
                check(pr.returncode == 0, f"異議を盤面に置ける（{pr.returncode}: {pr.stderr[-120:]}）")
                fired = True
    check(seen, "異議を出した周に p2.rejudge が発行される（cond が発火する）")
    st = run.state()
    check(any(p["path"] == "state.loop.rejudge_requested" for p in st.get("patches", [])), "往復の起点が痕跡に残る")
    rj = (run.record().get("process") or {}).get("rejudge")
    check(rj, f"往復の判定が記録に残る（{str(rj)[:80]}）")
    rm(run.tmp)


def test_worktree_guard_fires():
    """**P1 の前後で作業ツリーが変わったら止まる。** この柵は検査で 1 度も踏まれていなかった。

    実測 2026-09-13: `porcelain()` を 1 プロセス 1 回に memo 化する「最適化」を注入すると、前後の写しが
    必ず一致して**この柵は常に緑**になる——にもかかわらず検査 457 件は全件緑だった。柵の本体（前後が
    違えば止まる・理由を添えれば通る・通した痕跡が残る）をどの腕も踏んでいない。

    速さのために前後の写しを共有する処方は採らない（実測: `git status --porcelain` は 1 回 15 ミリ秒で、
    1 周に 1 回ぶんしか浮かない）——**15 ミリ秒のために柵を常時緑にする**取引になる。
    この腕は、その取引を誰かが後でやったら赤くなる位置に置く。
    """
    print("作業ツリーの柵: 前後で変わったら止まり、理由を添えれば通る")
    run = Run("treeguard")
    stray = run.repo / "stray.txt"
    tracked = run.repo / "src" / "a.py"  # BASE から既に変わっているファイル（＝審査対象の内側）
    MARK = "# 受理の後に足した行（写しの取り直しの目印）"
    # **触るのは、P1 の節が全部 done になった後・突合が走る前。** 手前には instance ごとの柵
    # （investigator の前後）が在り、そこで止まると P1 の前後の突合まで届かない
    # ——**2 つの柵が別物であることも、この腕を書いて初めて分かった。**
    stopped = ""
    for _ in range(120):
        nx = run.next()
        if nx.get("status") == "awaiting_human" or (not nx["ready"] and nx["status"] in TERMINAL_STATUS):
            break
        if not nx["ready"]:
            stopped = json.dumps(nx.get("notes"), ensure_ascii=False)
            break
        table = answers(run, "std", nx["round"])
        for inst in nx["ready"]:
            r = run.done(inst["id"], table[inst["node"]](load_item(inst)))
            if r.returncode != 0:
                raise RuntimeError(f"done {inst['id']}: {r.stderr[-300:]}")
        # 前の写しは取れたが、後の突合はまだ——ここが「P1 の前後」のあいだ。deps を数えると、
        # 条件外（na）になった節が done_ever に入らないので永久に揃わない（実測: 4 節が na）
        ever = set(run.state()["done_ever"])
        if "p1.worktree_before" in ever and "p1.worktree_after" not in ever and not stray.exists():
            stray.write_text("役が触っていない変更\n", encoding="utf-8")
            # **追跡下のファイルも触る。** stray は未追跡なので porcelain にしか出ず、git diff <BASE>（＝審査対象）
            # は動かない。受理後に写しを取り直しているかは、対象差分が動く変更でないと見えない
            tracked.write_text(tracked.read_text(encoding="utf-8") + MARK + "\n", encoding="utf-8")
            # **手順のファイルも足す**（差分に載せる）——受理した変更が、条件外（na）にした節の条件を変える形
            (run.repo / "deploy.sh").write_text("#!/bin/sh\necho deploy\n", encoding="utf-8")
            subprocess.run(["git", "add", "-N", "deploy.sh"], cwd=run.repo, capture_output=True)
    check("作業ツリーが変わっている" in stopped, f"P1 の前後が変われば止まる（{stopped[:160]}）")
    gm = run.state().get("git_mismatches") or []
    check(any(g.get("where") == "P1" and not g.get("accepted") for g in gm), f"止まった事実が痕跡に残る（{gm[:1]}）")
    patch = run.dir / "diff-r1.patch"
    check(MARK not in patch.read_text(encoding="utf-8"), "止めた時点の写しには受理前の姿しか無い（この腕の前提）")
    graph = json.loads((PLUGIN / "graphs" / "review-loop.json").read_text(encoding="utf-8"))["nodes"]
    ran_before = sorted(d for d in graph["p1.worktree_after"]["deps"]
                        if graph[d]["run_by"] != "driver" and d in run.state()["rounds"][0]["done"])
    na_before = run.state()["rounds"][0]["na"]
    es = next(i for i in run.state()["rounds"][0]["instances"].values() if i["node"] == "p1.external_standards")
    r = run.cmd("next", "--accept-tree-change", "台本が作業ツリーを触った（検査用）")
    check(r.returncode == 0, f"理由を添えれば通る（{r.returncode}: {r.stderr[-160:]}）")
    again = sorted({i["node"] for i in json.loads(r.stdout).get("ready", [])})
    # **受理したら、変更前の姿を見て書いた材料を撃ち直す**——写しだけ取り直すと、古い材料が判定役に渡る
    check(ran_before and set(ran_before) <= set(again) and "p1.external_standards" in again,
          f"受理した回は、走り終えていた材料の節を同じ next で撃ち直す（走っていた {ran_before} / 出た {again}）")
    check(not (set(ran_before) & {k for k in run.state()["rounds"][0]["done"]}),
          "撃ち直す節は done から外れている（古い材料のまま P2 へ進まない）")
    st = run.state()
    check(not pathlib.Path(es["out_path"]).exists() and list(pathlib.Path(es["out_path"]).parent.glob(pathlib.Path(es["out_path"]).name + ".stale-*"))
          and "p1.external_standards" not in st["outputs"] and "external_standards" not in run.record()["materials"],
          "撃ち直し: 古い返答は .stale へ退け、盤面の出力の指しと記録の素材も外す（新しい返答を書かずに打った done が古い返答で通らない）")
    check("p1.procedure_trace" in na_before and "p1.procedure_trace" in again,
          f"撃ち直し: 条件外にした節も条件を測り直す（受理した変更が手順のファイル deploy.sh を足した。{sorted(na_before)} → {again}）")
    gm0 = [g for g in st.get("git_mismatches") or [] if g.get("refired")]
    check(gm0 and "external_standards" in (gm0[-1].get("stale_materials") or {}),
          "撃ち直し: 外した素材の中身は痕跡（git_mismatches の stale_materials）に残る")
    gm = run.state().get("git_mismatches") or []
    check(any(g.get("accepted") for g in gm), f"通した理由が痕跡に残る（{[g.get('accepted') for g in gm]}）")
    # **受理したら審査対象の写しを取り直す。** tree_before だけ置き直していたとき、P2 に渡る写しは P1 前のままで、
    # 写しを読む役と現物を読む役が同じ行に逆の結論を出した（実測 2026-09-14）
    check(MARK in patch.read_text(encoding="utf-8"), "受理後は diff-r1.patch が取り直されている（写しと現物が割れない）")
    check(any(g.get("retaken") for g in gm), f"取り直した事実が痕跡に残る（{[g.get('retaken') for g in gm]}）")
    check(any(g.get("refired") for g in gm), f"撃ち直した節が痕跡に残る（{[g.get('refired') for g in gm]}）")
    last = drive(run, "std")
    check(last["status"] == "converged", f"撃ち直した材料で P1 の後の突合を通り、収束まで進む（{last['status']}）")
    rm(run.tmp)


def test_request_entry():
    """**判定から入る入口**（loop.py add で人の修正依頼を置く。R12）。

    BASE=HEAD（差分ゼロ）でも止まらず、P1 の役を 1 つも起こさずに判定から始まり、素材は入口の理由つきの
    not_applicable で埋まり、依頼は専用の欄（process.request_findings）で判定に届く。修正が入った次の周からは
    通常の run と同じく P1 が修正差分を見る。依頼を全部却下した run も、修正 0 行のまま報告まで届く。
    **依頼を積むことと P1 を外すことは別の欄**: 依頼はその周の判定の前なら何周目でも何度でも積め、P1 を外すのは
    1 周目の P1 より前の add が立てる印（process.request_entry）だけ。"""
    print("判定から入る入口: add → P1 の役を起こさず判定へ → 修正の次の周から P1 が戻る・途中の周の add は P1 を外さない")
    graph = json.loads((PLUGIN / "graphs" / "review-loop.json").read_text(encoding="utf-8"))["nodes"]
    roles = {k for k, n in graph.items() if n.get("stage") == "P1" and n.get("run_by") != "driver"}
    req = [{"where": "src/a.py:f", "text": "上限を掛けたい（人の依頼・検査用の目印 REQ-7f3）", "measured": "手で確かめた"}]
    for scenario in ("std", "entry_reject"):
        run = Run(f"entry-{scenario}")
        f = run.tmp / "req.json"
        f.write_text(json.dumps(req, ensure_ascii=False), encoding="utf-8")
        bad = run.tmp / "bad.json"
        bad.write_text(json.dumps([{"where": "x", "text": "y", "severity": "block"}]), encoding="utf-8")
        r = run.cmd("add", "--file", str(bad), "--reason", "検査")
        check(r.returncode == 1 and "severity" in r.stderr, f"入口: findings の型に無い欄を持つ依頼は拒む（{r.stderr[-160:]}）")
        r = run.cmd("add", "--file", str(f), "--reason", "利用者の依頼（検査用）")
        check(r.returncode == 0, f"入口: init の直後の add は通る（{r.stderr[-160:]}）")
        f2 = run.tmp / "req2.json"
        f2.write_text(json.dumps([{"where": "src/b.py:g", "text": "2 本目の依頼（検査用の目印 REQ-2b9）"}], ensure_ascii=False), encoding="utf-8")
        r = run.cmd("add", "--file", str(f2), "--reason", "2 回目の依頼（検査用）")
        check(r.returncode == 0 and "判定から入る run" in r.stdout,
              f"入口: 同じ周の判定の前なら 2 回目の add も積める（{r.stdout[-160:]}{r.stderr[-160:]}）")
        head = sh(run.repo, "git", "rev-parse", "HEAD").stdout.strip()
        seen = collections.defaultdict(set)
        late = {}

        def hook(run, inst, out, seen=seen, head=head, late=late):
            rnd = run.state()["round"]
            seen[rnd].add(inst["node"])
            if inst["node"] == "p0.base":
                return {**out, "base_sha": head, "method": "4 依頼者の名指し", "commits": 0}
            if inst["node"] == "p2.diagnose" and rnd == 1:
                # 判定役が起きた後の add は拒む（その周の判定に届かない依頼を黙って積まない）
                late["after_judge"] = run.cmd("add", "--file", str(f2), "--reason", "判定の後")
            if rnd == 2 and "r2" not in late:
                # 2 周目の頭（判定の前）の add は受ける——途中の周の依頼の口。入口が続く周は最初に出るのが判定そのもので、そこでは拒まれる
                f3 = run.tmp / "req3.json"
                f3.write_text(json.dumps([{"where": "src/c.py:h", "text": "途中の周の依頼（検査用の目印 REQ-r2c）"}], ensure_ascii=False), encoding="utf-8")
                late["r2"] = run.cmd("add", "--file", str(f3), "--reason", "途中の周の依頼（検査用）")
            return None
        # 筋書きが途中で落ちても後ろの腕（他の条件が全部真の筋など）まで届かせる——落ちたことは検査の赤で残す
        try:
            last = drive(run, scenario, hook=hook)
        except RuntimeError as e:
            check(False, f"入口: 回し切れる（{scenario}）: {str(e)[-300:]}")
            rm(run.tmp)
            continue
        check(last["status"] == "converged", f"入口: BASE=HEAD の差分ゼロでも止まらず収束まで進む（{last['status']}: {last.get('notes')}）（{scenario}）")
        check(not (seen[1] & roles), f"入口: 1 周目は P1 の役を起こさない（出た {sorted(seen[1] & roles)}）（{scenario}）")
        r1 = run.round_file(1)["materials"]
        entry_mats = {m for k in roles for m in graph[k].get("materials", [])}
        off = {m: r1.get(m) for m in entry_mats if r1.get(m, {}).get("status") != "not_applicable"}
        by_entry = {m for m in entry_mats if "判定から入る run" in r1.get(m, {}).get("reason", "")}
        # 入口が無くても走らない節（手順書に触れない差分の procedure_trace 等）は、本当の条件外の理由のまま——入口の文で上書きしない
        own = {m for m in entry_mats - by_entry if r1.get(m, {}).get("reason")}
        check(not off and {"local_review", "consistency", "bypass", "hygiene", "external_standards", "provenance"} <= by_entry
              and "procedure_trace" in own,
              f"入口: 飛ばした P1 の素材は not_applicable——入口で外れた節は入口の理由、別の条件でも外れる節はその理由（外れ {off}・入口 {sorted(by_entry)}）（{scenario}）")
        prompt = (run.dir / "prompts" / "r1" / "p2.diagnose.md").read_text(encoding="utf-8")
        check(all(x in prompt for x in ("REQ-7f3", "利用者の依頼（検査用）", "REQ-2b9", "2 回目の依頼（検査用）")),
              f"入口: 判定のプロンプトに同じ周の 2 つのバッチが出どころつきで届く（{scenario}）")
        ab = late.get("after_judge")
        check(ab is not None and ab.returncode == 1 and "既に起きている" in ab.stderr and "新しい run" in ab.stderr,
              f"入口: 判定役が起きた後の add は拒み、次の周が来ないときの行き先も言う（{(ab.stderr[-200:] if ab else '呼ばれていない')}）（{scenario}）")
        proc = run.record()["process"]
        check(proc.get("request_entry") == {"origin": "利用者の依頼（検査用）"} and not proc.get("procedure_findings"),
              f"入口: 印は 1 周目の P1 前の最初の add の出どころで立ち、手順トレースの欄を借りない（{proc.get('request_entry')}）（{scenario}）")
        batches = proc.get("request_history", []) + proc.get("request_findings", [])
        check(sorted((x["round"], x["origin"]) for x in batches) == sorted(
                  [(1, "利用者の依頼（検査用）"), (1, "2 回目の依頼（検査用）")] + ([(2, "途中の周の依頼（検査用）")] if "r2" in late and late["r2"].returncode == 0 else [])),
              f"入口: どの周のバッチも周と出どころつきで記録に残る（{[(x['round'], x['origin']) for x in batches]}）（{scenario}）")
        if scenario == "std":
            check("p1.local_review" in seen[2], f"入口: 修正が入った次の周は P1 が修正差分を見る（2 周目に出た {sorted(seen[2] & roles)}）")
            r2 = late.get("r2")
            check(r2 is not None and r2.returncode == 0, f"入口: 2 周目の判定の前の add は受ける（{(r2.stderr[-200:] if r2 else '呼ばれていない')}）")
            p2 = (run.dir / "prompts" / "r2" / "p2.diagnose.md").read_text(encoding="utf-8")
            check("REQ-r2c" in p2 and "途中の周の依頼（検査用）" in p2 and "REQ-7f3" not in p2,
                  "入口: 2 周目の判定にはその周の依頼だけが届き、前の周の依頼は履歴に移る")
        else:
            check(all(not (seen[n] & roles) for n in seen), "入口: 修正 0 行の run は P1 を起こさないまま周を重ねる")
            p2 = run.dir / "prompts" / "r2" / "p2.diagnose.md"
            check(not p2.is_file() or "REQ-7f3" in p2.read_text(encoding="utf-8"),
                  "入口: 修正 0 行で入口が続く周は、1 周目の依頼を移さず判定役に渡し続ける")
        rm(run.tmp)

    def first_round(name, prep, base_patch):
        """init → prep(run) → 1 周目の判定の手前まで回し、1 周目に出た節の集合を返す"""
        run = Run(name)
        prep(run)
        seen1 = set()

        def hook(run, inst, out):
            seen1.add(inst["node"])
            return {**out, **base_patch(run)} if inst["node"] == "p0.base" else None
        try:
            drive(run, "std", hook=hook, stop_at=lambda nx: nx["round"] > 1 or any(i["node"] == "p2.diagnose" for i in nx["ready"]))
        except RuntimeError as e:
            print(f"  （{name} は途中で落ちた: {str(e)[-200:]}）")
        mats = run.record()["materials"]
        rm(run.tmp)
        return seen1, mats

    def add_req(run):
        f = run.tmp / "req.json"
        f.write_text(json.dumps(req, ensure_ascii=False), encoding="utf-8")
        run.cmd("add", "--file", str(f), "--reason", "利用者の依頼（検査用）")

    def put(run, path, value):
        f = run.tmp / "patch.json"
        f.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
        r = run.cmd("patch", "--path", path, "--file", str(f), "--reason", "検査")
        if r.returncode != 0:
            raise RuntimeError(f"patch {path}: {r.stderr[-300:]}")

    # 入口の項だけで外れる形: 差分が手順書に触れ、ゲート・継ぎ目・経路の申告も全部真（入口が無ければ 9 節とも走る）
    wide = {"touches_gates": True, "touches_external_seams": True, "touches_user_path": True}

    def touch_readme(run):
        add_req(run)
        (run.repo / "README.md").write_text("# demo\n手順を足した\n", encoding="utf-8")
    got, mats = first_round("entry-wide", touch_readme, lambda run: wide)
    check(not (got & roles), f"入口: 他の条件が全部真でも、入口の周は P1 の役を 1 つも起こさない（出た {sorted(got & roles)}）")
    entry_mats = {m for k in roles for m in graph[k].get("materials", [])}
    off = {m: mats.get(m) for m in entry_mats if "判定から入る run" not in (mats.get(m) or {}).get("reason", "") or mats[m]["status"] != "not_applicable"}
    check(not off, f"入口: 入口の項だけで外れた節は、どの cond の形（all・any の入れ子）でも入口の理由の not_applicable（外れ {off}）")
    # 昇格した run では、深さで切っている節は入口より昇格が勝つ（escalate_on_thrash の effects が名乗るとおり）
    deep = {"p1.procedure_trace", "p1.gate_efficacy", "p1.test_double_fidelity"}

    def escalated(run):
        add_req(run)
        put(run, "state.loop.escalated", {"round": 1, "why": "検査"})
    got, _ = first_round("entry-esc", escalated, lambda run: {})
    check(deep <= got and not ((got & roles) - deep), f"入口: 昇格した周は深さの 3 節だけ入口より昇格が勝つ（出た {sorted(got & roles)}）")
    # patch は手当ての口として印も依頼も書ける——印が型どおりなら入口、依頼の一覧だけでは入口にならない、型の崩れた印も入口にならない
    got, _ = first_round("entry-patch", lambda run: put(run, "process.request_entry", {"origin": "patch（検査）"}), lambda run: {})
    check(not (got & roles), f"入口: patch で置いた型どおりの印も入口になる（出た {sorted(got & roles)}）")
    got, _ = first_round("entry-patch-bad", lambda run: put(run, "process.request_entry", "patch（検査）"), lambda run: {})
    check("p1.local_review" in got, f"入口: 型の合わない印（出どころの dict でない）は入口にならず通常の run（出た {sorted(got & roles)}）")
    got, _ = first_round("entry-patch-list", lambda run: put(run, "process.request_findings", [{"round": 1, "origin": "patch（検査）", "findings": req}]),
                         lambda run: {})
    check("p1.local_review" in got, f"入口: 依頼の一覧だけを置いても P1 は外れない（出た {sorted(got & roles)}）")
    # 入口の項を持たない節は、cond が真でも入口の理由を書かない（素材の穴埋めが入口の文で上書きしない）
    sys.path.insert(0, str(PLUGIN))
    from engine.rules import load_rules
    gp = PLUGIN / "graphs" / "review-loop.json"
    rules = load_rules(gp, json.loads(gp.read_text(encoding="utf-8")))
    fake = types.SimpleNamespace(eval_cond=lambda c: True)
    check(not rules._entry_skipped(fake, {"cond": {"path": "round", "op": "eq", "value": 1}}),
          "入口: 入口の項を持たない節は、条件が真でも入口で外れたと数えない")
    # request_entry は印だけを見る——依頼の一覧が在っても印が無ければ偽（空差分の柵も P1 の cond も同じ 1 本を読む）
    batch = [{"round": 2, "origin": "途中", "findings": req}]
    ent = lambda proc, ls={}: rules.request_entry(types.SimpleNamespace(record={"process": proc}, loop_state=ls))
    check(not ent({"request_findings": batch}), "入口: 依頼の一覧だけでは入口にならない（途中の周の依頼で空差分の柵と P1 を外さない）")
    check(ent({"request_entry": {"origin": "人"}}) and not ent({"request_entry": {"origin": "人"}}, {"request_fixed_at": 1}),
          "入口: 印が在れば修正が入るまで真、修正が入った後は偽")
    # 型の崩れた依頼の一覧は読まない（patch は型を通らずに書けるので、読む口 1 か所で当てる）
    lst, why = rules._requests(types.SimpleNamespace(record={"process": {"request_findings": {"origin": "旧い形", "findings": req}}}), "request_findings")
    check(lst == [] and why and "request_findings" in why, f"入口: 型の崩れた依頼の一覧は読まずに理由を返す（{why}）")

    # 通常の run で P1 が走った後（判定の前）の add は受けるが、印は立てず P1 も外さない
    run = Run("entry-late")
    f = run.tmp / "req.json"
    f.write_text(json.dumps(req, ensure_ascii=False), encoding="utf-8")
    seen1, mid = set(), {}

    def mid_hook(run, inst, out):
        seen1.add(inst["node"])
        if inst["node"] in roles and "r" not in mid:
            mid["r"] = run.cmd("add", "--file", str(f), "--reason", "遅い依頼")
        return None
    try:
        drive(run, "std", hook=mid_hook, stop_at=lambda nx: nx["round"] > 1 or any(i["node"] == "p2.diagnose" for i in nx["ready"]))
    except RuntimeError as e:
        check(False, f"入口: 途中の add の筋が回し切れる: {str(e)[-300:]}")
    r = mid.get("r")
    check(r is not None and r.returncode == 0 and "いつもどおり" in r.stdout,
          f"入口: P1 が走った後でも判定の前の add は受け、P1 はいつもどおりと言う（{(r.stdout[-160:] + r.stderr[-160:]) if r else '呼ばれていない'}）")
    check("request_entry" not in run.record()["process"] and "p1.local_review" in seen1,
          f"入口: P1 が走った後の add は入口の印を立てない（出た {sorted(seen1 & roles)}）")
    rm(run.tmp)


def test_surviving_branches():
    """**退行注入で生き残った残りの分岐に腕を当てる**（どれも反転しても台本が全件緑だった腕）。

    ①差分の行数の数え方——`len(r) == 3 and r[1].isdigit()` の `and` を `or` にしても緑。バイナリの行は
    numstat が `-` を返すので、`isdigit` を外すと `int('-')` で落ちるか、行の形が違う入力を数えてしまう。
    ②前提の問いの差し替え——古い行を外す条件を反転しても緑。反転すると**外すべきでない問いを全部消す**。
    ③素材の必須欄の型検査——`or` を `and` にしても緑。空文字が「在る」として通る。
    """
    print("生存した分岐: 行数の数え方・前提の問いの差し替え・必須欄の型検査")
    sys.path.insert(0, str(PLUGIN))
    from engine.rules import load_rules
    gp = PLUGIN / "graphs" / "review-loop.json"
    rules = load_rules(gp, json.loads(gp.read_text(encoding="utf-8")))

    # ① numstat の数え方——**実装を呼ぶ。** 最初は同じ式を検査側に写していて、実装を壊しても
    # 全件緑だった（実測: `and`→`or` と `isdigit` 外しの 2 つとも生き残った）。**落ちようのない検査**で、
    # この周が狩っている「名乗りより射程が狭い」の、検査側の形そのものだった
    names, ins, dels, nfiles = rules.numstat_totals("3\t1\ta.py\n-\t-\tlogo.png\n2\t0\tb.py\nbroken")
    check((ins, dels) == (5, 1), f"バイナリ（-）と壊れた行を数えない（ins={ins} dels={dels}、期待 5/1）")
    check(names.splitlines() == ["a.py", "logo.png", "b.py"], f"欄が 3 つ揃った行の名前だけ並ぶ（{names.splitlines()}）")
    check(nfiles == 4, f"行数は壊れた行も数える（変更ファイル数の申告は git の行数）——{nfiles}")

    # ② 前提の問いの差し替え——外すのは kind=premise かつ origin=R2 の行だけ
    keep = [{"key": "他の問い", "kind": "fork", "origin": "u1", "status": "held", "reason": "x", "options": ["a", "b"]},
            {"key": "別の前提", "kind": "premise", "origin": "R1", "status": "held", "reason": "y"}]
    b = types.SimpleNamespace(round=2, loop_state={},
                              record={"questions": [dict(q) for q in keep]
                                      + [{"key": "古い前提", "kind": "premise", "origin": "R2", "status": "held", "reason": "z"}]})
    rules.premise_question(b, "stop.premise_check",
                           {"key": "新しい前提", "verdict": "resolved", "reason": "検算した", "resolution": "仮定は偽", "facts_to_add": []}, None)
    got = {q["key"] for q in b.record["questions"]}
    check("古い前提" not in got, f"kind=premise かつ origin=R2 の古い行は外れる（{sorted(got)}）")
    check({q["key"] for q in keep} <= got, f"他の問いは残る（{sorted(got)}）")

    # ③ 素材の必須欄——空文字・型違いのどちらも落とす
    def errs_for(value):
        bb = types.SimpleNamespace(
            round=1, nodes={}, rd={"instances": {}},
            state={"validator": str(VALIDATOR)},
            record={"materials": {"m": {"status": "found", "count": 1, "detail": value}}, "reviews": {}, "units": [], "questions": []})
        return [e for e in rules.check_record(bb) if "'detail'" in e]

    check(errs_for(""), "必須欄が空文字なら落とす（在ることと中身が在ることは別）")
    check(errs_for(5), "必須欄の型が違えば落とす")
    check(not errs_for("何を見たかを書いた"), f"中身が在れば通る（{errs_for('何を見たかを書いた')}）")


def test_open_unit_and_hit_arm():
    """**退行注入で生き残った 2 つの分岐に腕を当てる。**

    ①「この周に直す単位か」（検証器の `is_open`）——`label == "block"` を反転しても台本が全件緑だった
    （実測 2026-09-13）。つまり **run 全体の「何を直すべきか」の判定を、検査が一度も確かめていない**。
    ここがずれると、直す義務も一撃の名指しの母数も一緒にずれる。
    **当てる先は検証器の正本。** rules 側に同じ式の写しが在ったので、写しに腕を当てても正本の
    ずれは捕まらなかった（実測 2026-09-14: rules の写しを削って V.is_open 1 本に寄せた）。

    ②`gate_arms_all_red` の「status に依らず当てる腕」——`nohit and not (unred or nocontrol)` の
    `or` を `and` に変えても緑だった。この腕は**赤も control 緑も見た腕だけ**に当てるもので、まだ赤を
    見ていない腕は手前の腕が扱う。`and` にすると手前の腕の担当まで二重に拒み、理由が事実と食い違う。
    """
    print("生存した分岐: 直す単位の判定と、覆いの腕の切り分け")
    sys.path.insert(0, str(PLUGIN))
    import importlib.util
    from engine.rules import Reject, load_rules
    gp = PLUGIN / "graphs" / "review-loop.json"
    rules = load_rules(gp, json.loads(gp.read_text(encoding="utf-8")))
    spec = importlib.util.spec_from_file_location("vrec3", str(VALIDATOR))
    V = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(V)

    # ① 直す単位の判定——4 通りを全部踏む
    for u, want in (({"label": "block"}, True),
                    ({"label": "block", "disposition": "defer"}, True),
                    ({"label": "suggest", "disposition": "do-now"}, True),
                    ({"label": "suggest", "disposition": "defer"}, False),
                    ({"label": "suggest"}, False),
                    ({"label": "nit", "disposition": "do-now"}, False),
                    ({"label": "info"}, False)):
        got = V.is_open(u)
        check(got is want, f"直す単位の判定: {u} → {got}（期待 {want}）")

    # ② 覆いの腕の切り分け——st=found で手前の腕は黙る。この腕は「赤も緑も見た腕」にだけ当たる
    chk = rules.POST_CHECKS["gate_arms_all_red"]
    b = types.SimpleNamespace(round=2, loop_state={}, record={}, state={"validator": str(VALIDATOR)}, dir=PLUGIN)

    def arms_out(rows, st="found"):
        return {"arms": rows, "material": {"status": st, "count": 1, "detail": "x"}}

    def run(rows, st="found"):
        try:
            chk(b, "p1.gate_efficacy", arms_out(rows, st), None)
            return None
        except Reject as e:
            return str(e)

    both = {"arm": "A", "red_confirmed": True, "control_green": True, "hit_evidence": ""}
    check(run([both]), "赤も control 緑も見た腕が hit_evidence を持たないなら拒む")
    ok = {"arm": "A", "red_confirmed": True, "control_green": True, "hit_evidence": "分岐が書く値を印に替え、記録に現れた"}
    check(run([ok]) is None, f"3 つそろった腕は通る——{run([ok])}")
    # **まだ赤を見ていない腕は手前の腕の担当。** ここで二重に拒むと理由が事実と食い違う
    # （`or` を `and` に変えた退行がここで赤くなる）
    unred = {"arm": "B", "red_confirmed": False, "control_green": True, "hit_evidence": ""}
    check(run([unred]) is None, f"赤を見ていない腕は found なら通る（手前の腕の担当）——{run([unred])}")
    nocontrol = {"arm": "C", "red_confirmed": True, "control_green": False, "hit_evidence": ""}
    check(run([nocontrol]) is None, f"control の緑を見ていない腕も found なら通る——{run([nocontrol])}")
    check(run([unred], st="clean"), "found でなければ手前の腕が拒む")
    check(run([unred], st="awaiting_human") is None and "found" in (run([unred], st="not_run") or ""),
          "赤を見ていない腕の例外は人の起動待ちだけ——not_run には是正の文（found にして腕を書け）を返す")
    check(run([unred, both]), "撃てない腕が在っても、赤も control 緑も見た腕の印の欠けは腕ごとに拒む")
    check("腕が 0 行" in (run([], st="clean") or "") and run([], st="not_run") is None,
          "腕 0 行で見たと言う状態（clean）は拒み、撃てた腕が無い not_run は通す")
    # ③ R2 を回し直す行数の条件——増える向き（R1 の時点の 1.5 倍）と減る向き（前の周の 2/3 以下）
    mv = rules._lines_moved
    check(mv(1.6, 160, 150) == (True, False), f"R1 の時点の 1.5 倍を超えたら増えた（{mv(1.6, 160, 150)}）")
    check(mv(1.2, 100, 150) == (False, True), f"前の周の 2/3 以下に減ったら減った（{mv(1.2, 100, 150)}）")
    check(mv(1.2, 101, 150) == (False, False), f"2/3 を超えるなら動いていない（{mv(1.2, 101, 150)}）")
    check(mv(None, 100, None) == (False, False), f"前の周が無ければ減ったとは言わない（{mv(None, 100, None)}）")
    # 組み込み: 行数の動きが R2 の回し直しに届く（関数の腕だけでは、呼ぶ側の `or shrank` を消しても緑だった）
    rf = rules._r2_refire
    check(rf(2, {}, 0.7, 100, {"diff_lines_by_round": {"1": 150}}) is True, "2 周目に前の周の 2/3 以下へ減ったら R2 を回し直す")
    check(rf(2, {}, 1.6, 160, {"diff_lines_by_round": {"1": 150}}) is True, "R1 の時点の 1.5 倍を超えたら R2 を回し直す")
    check(rf(2, {}, 1.0, 150, {"diff_lines_by_round": {"1": 150}}) is False, "行数が動かず機構も前提も変わらなければ回し直さない")
    walk = {}
    rf(1, {}, None, 150, walk)
    check(rf(2, {}, 1.0, 100, walk) is True and walk["diff_lines_by_round"] == {"1": 150, "2": 100},
          f"周ごとの行数は _r2_refire 自身が盤面に書き、次の周がそれと比べる（空の盤面から 2 周。{walk}）")
    ls = {"diff_lines_by_round": {"1": 150}, "r2_refire_forced": True}
    check(rf(2, {}, 1.0, 150, ls) is True and "r2_refire_forced" not in ls, "強制の旗は効いて消費される")
    check(run([unred], st="awaiting_human") is None, f"赤を見ていない腕が在っても awaiting_human なら通る——{run([unred], st='awaiting_human')}")


def test_silent_status_derived():
    """**「黙って通る値」の集合を、検証器の表から引く（rules に写さない）。**

    役の自己申告を機械が持つ事実と突き合わせる柵が、素材の 6 値のうち 2 値（`not_applicable` /
    `carried_over`）を手で並べていた。値を足した周にその 1 値だけ柵の外に落ちるし、**同じ 2 語が
    rules の 2 か所に写されていた**。集合の定義は表が持つ——「自分で見たと主張せず（observed=False）、
    阻害要因にも出ない（blocks=False）」が『黙って通る値』の定義で、`not_run` / `awaiting_human` は
    blocks=True なので黙らない（人に出る）から、ここでは塞がない。
    """
    print("自己申告の突合: 塞ぐ値の集合は検証器の表から引く")
    sys.path.insert(0, str(PLUGIN))
    import importlib.util
    from engine.rules import Reject, load_rules
    spec = importlib.util.spec_from_file_location("vrec2", str(VALIDATOR))
    V = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(V)
    check(set(V.SILENT_STATUS) == {k for k, r in V.STATUS.items() if not r.observed and not r.blocks},
          f"集合は表から導かれる（{sorted(V.SILENT_STATUS)}）")
    check(all(V.STATUS[k].blocks for k in V.STATUS if not V.STATUS[k].observed and k not in V.SILENT_STATUS),
          "見ていない値のうち、黙って通らないものは必ず阻害要因に出る（blocks=True）")

    # git をこのリポジトリに固定して読む——engine の util.GIT_CWD はモジュールの大域で、並列の台本が Board を開くと別の
    # 一時リポジトリに書き換わる。固定しないと、修正の件数を数える先がその一時リポジトリに化けて落ちた（腕の写しの control で再現）
    rules = load_review_rules(PLUGIN.parent)
    chk = rules.POST_CHECKS["fix_covers_open_units"]
    ch = [{"unit_key": "k", "key": "k", "files": ["a.py"], "sites": [{"site": "a.py:1", "red_seen": True}],
           "root_or_symptom": {"kind": "root", "reason": "根に当たる"},
           "coverage": {"how": {"patterns": ["loop"], "paths": ["graphloops/graphs/review-loop.json"], "count": "files"}, "counts": "population"},
           "precedent": {"problem": "検査用の問題", "source": "https://example.invalid/（検査用）", "verdict": "adopt", "reason": "検査用に採った"},
           "closure": {"sites": [{"site": "a.py:1", "red_seen": True, "verified_how": "退行を注入して赤、戻して緑"}]},
           "bypass_tried": "修正を残したまま境界値 3 種で破りに行った。いずれも赤のまま破れなかった",
           "breaks": {"how": "grep -rn x .", "result": "同じ不変条件の 1 箇所が今も動くことを確認"}}]

    # 盤面の置き場は一時ディレクトリ——rules は盤面の隣に書く（数える量の記録）ので、プラグインの置き場を渡すと作業ツリーを汚す
    _td, board_dir = parallel.workspace("gl-fixboard-")

    def board():
        return types.SimpleNamespace(
            round=2, loop_state={"open_units": []},
            record={"units": [], "process": {}, "questions": [], "materials": {}},
            state={"validator": str(VALIDATOR)}, rd={"instances": {}}, nodes={}, dir=board_dir, output_of_round=lambda n, r: None)

    def try_status(st):
        try:
            chk(board(), "p3.fix", {"changes": ch, "fix_closure": {"status": st, "reason": "理由"}}, None)
            return None
        except Reject as e:
            return str(e)

    for st in V.SILENT_STATUS:
        msg = try_status(st)
        check(msg and st in msg, f"修正が在る周に '{st}' は拒む（黙って通る値）——{(msg or '通った')[:60]}")
    check(try_status("clean") is None, f"今の周に見た値（clean）は通る——{try_status('clean')}")
    try:
        chk(board(), "p3.fix", {"changes": [{**ch[0], "precedent": {"verdict": "adopt", "from_judge_row": True, "reason": "判定者の行（検査用）"}}],
                                "fix_closure": {"status": "clean"}}, None)
        msg = "通った"
    except Reject as e:
        msg = str(e)
    check("from_judge_row なのに" in msg, f"先行例: 判定者の行が無い単位を from_judge_row と言えば拒む（{msg[:70]}）")
    # 引用の数え直しが読めなかった回（時間切れ・上限超え・標準エラー）: git も版も生きていても 0 件にせず、理由つきで止める
    rules.grep = lambda *a, **k: (None, "git grep が 60 秒で終わらない")
    try:
        rules._count_in_version("n", "引用", "cites", 0, {"hits": 1}, "x", "HEAD", {}, [])
        msg = "通った"
    except Reject as e:
        msg = str(e)
    check("60 秒で終わらない" in msg, f"引用の数え直し: 読めなかった回は理由つきで止める（0 件と言わない。{msg[:70]}）")
    rm(board_dir)


def test_delta_conditions():
    """修正差分の段の条件と、git の失敗の倒れ方を盤面を手で組んで直に見る。筋書き（planfaces）は条件が全部真になる 1 本しか
    通らないので、片方だけ真の形・前の周の値・git が失敗する形はここで見る（実測 2026-09-24: 4 周目の修正差分の自動の腕が、
    この段の or / and の項と git の失敗の分岐を 1 本も殺せなかった）"""
    print("修正差分の条件: 差分と『塞いだ』申告の片方だけでも差分レビューを起こし、腕の証拠の欠けは 1 つずつ義務になり、git の失敗で止まる")
    _td, tmp = parallel.workspace("gl-delta-")
    (tmp / "a.py").write_text("A = 1\n", encoding="utf-8")
    # 版の固定（commit-tree）は author を要る——CI の git には既定の名前が無いので、この repo に置く
    for c in (["init", "-q"], ["config", "user.name", "t"], ["config", "user.email", "t@t"], ["add", "-A"], ["commit", "-qm", "x"]):
        subprocess.run(["git", *c], cwd=tmp, capture_output=True)
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=tmp, capture_output=True, text=True, encoding="utf-8").stdout.strip()
    rules = load_review_rules(tmp)
    from engine.util import Reject  # noqa: E402
    board = tmp / ".git" / "gl-board"   # 本物の run と同じく git dir の下（作業ツリーの外）——作業場と一緒に消える
    board.mkdir()
    outs = {}
    b = types.SimpleNamespace(round=2, loop_state={}, dir=board, state={"validator": str(VALIDATOR), "inputs": {}},
                              record={"units": [], "questions": []}, porcelain=lambda: "",
                              output_of_round=lambda n, r: outs.get(n) if r == 2 else None)

    def at(ls, o=None):
        b.loop_state = ls
        outs.clear()
        outs.update(o or {})
        return b
    check(rules.delta_review_due(at({"fix_delta": {"round": 2, "files": ["a.py"]}})),
          "修正差分: 差分が在れば、『塞いだ』申告が無くても 1 回目の差分レビューを起こす")
    check(rules.delta_review_due(at({"fix_delta": {"round": 2, "files": []}}, {"p3.fix": {"plan_faces": [{"key": "k1", "handled": "absorbed"}]}})),
          "修正差分: 差分が空でも、『塞いだ』申告が在れば 1 回目の差分レビューを起こす（申告を誰も検算しない形を作らない）")
    check(not rules.delta_review_due(at({})) and not rules.fix_delta_nonempty(at({"fix_delta": {"round": 1, "files": ["a.py"]}})),
          "修正差分: 差分も申告も無い周・前の周の差分しか無い周は起こさない")
    check(rules.delta_review2_due(at({"fix_delta2": {"round": 2, "files": ["a.py"]}})),
          "修正差分: 手直しの差分が在れば 2 回目を起こす")
    check(rules.delta_review2_due(at({}, {"p3.delta_fix": {"handled": [{"key": "k1", "handled": "fixed"}]}})),
          "修正差分: 手直しの差分が無くても、手直しが直したと言う穴が在れば 2 回目を起こす")
    check(rules._delta_owed(at({}), 1) == set() and rules._delta_owed(at({"delta_owed": {"round": 1, "rows": [{"key": "k"}]}}), 1) == set(),
          "手直しの義務: 義務の値が無い盤面・前の周の値しか無い盤面では、答える義務は空（起こさない）")
    # 周をまたぐ変更の検出: 前の周の頭の版が無ければ測れない（None）、在れば今の木との差（未追跡も入る）
    check(rules._files_changed_since(at({}), 1) is None, "周をまたぐ変更: 前の周の頭の版が無い周は『測れない』（None）")
    (tmp / "b.py").write_text("B = 1\n", encoding="utf-8")
    got = rules._files_changed_since(at({"head_revs": {"1": head}}), 1)
    check(got == ["b.py"], f"周をまたぐ変更: 前の周の頭の版と今の木の差に、未追跡の新規ファイルも入る（{got}）")
    real = rules.git
    try:
        rules.git = lambda *a, **k: None if a[0] == "diff" else real(*a, **k)
        got = rules._files_changed_since(at({"head_revs": {"1": head}}), 1)
        check(got is None, f"周をまたぐ変更: git diff が取れない回は『測れない』（None。空の一覧に潰さない。{got}）")
        rules.git = lambda *a, **k: "" if a[0] == "commit-tree" else real(*a, **k)
        try:
            rules._snapshot("検査用")
            got = "通った"
        except Reject as e:
            got = str(e)
        check("commit-tree が版を返さない" in got, f"版の固定: commit-tree が空を返す回は止める（{got[:70]}）")
    finally:
        rules.git = real
    snap = rules._snapshot("検査用")
    parent = subprocess.run(["git", "rev-parse", f"{snap}^"], cwd=tmp, capture_output=True, text=True, encoding="utf-8").stdout.strip()
    check(parent == head, f"版の固定: 履歴の在るリポジトリでは HEAD を親にする（根なしの版を採点しない。{parent[:10]} / {head[:10]}）")
    r = rules.fix_delta(at({}), "p3.fix_delta2")
    check(not r["ok"] and "差分の起点の版が無い" in " ".join(r["problems"]),
          f"修正差分: 1 回目の版が無い周の 2 回目は、起点が無いと名乗って止まる（{r}）")
    real_take = rules._take_diff
    try:
        rules._take_diff = lambda bb, suffix="": {"ok": True, "rev": "0" * 40, "raw": b"x", "diff_file": "", "changed_files": [], "stat": ""}
        r = rules.worktree_snapshot(at({}), "p1.worktree_before")
    finally:
        rules._take_diff = real_take
    check(not r["ok"] and "木の id が取れない" in " ".join(r["problems"]), f"作業ツリーの保護: 固めた版の木の id が取れない回は止める（{r}）")
    V = rules.validator_module(b)
    b.record = {"units": [{"key": u, "label": "block"} for u in ("u1", "u2", "u3")],
                "questions": [{"key": "q", "kind": "fork", "status": V.ASKING[0], "origin": "u1", "depends": ["u2"]}]}
    got = rules._owed_units(at({}))
    check(got == {"u3"}, f"直す義務: 人待ちの fork の出どころと depends は待ってよい（{sorted(got)}）")
    try:
        rules.POST_CHECKS["delta_review_output"](at({}), "p3.delta_review2",
                                                 {"faces": [], "checks": [], "faces_none": "差分が無く、検算する申告も無い（検査用の空の返答）"}, None)
        got = "通った"
    except Reject as e:
        got = str(e)
    check(got == "通った", f"修正差分のレビュー: 差分の記録が無い回も、空の返答は落ちずに受ける（{got[:70]}）")
    rm(tmp)


def _lane_arm(name, **k):
    return {**PROVEN_ARM, "arm": name, **k}


LANE_PATCH = ("diff --git a/tests/test_lane.py b/tests/test_lane.py\nnew file mode 100644\n--- /dev/null\n+++ b/tests/test_lane.py\n"
              "@@ -0,0 +1 @@\n+def test_lane(): pass\n")


def test_lane_graph_shape():
    """**変異の検算は周の締めを止めない。** p4.ci・p4.scalars・手直しの義務・R1〜R4・周の記録・converge のどれも、
    線（p3.delta_gates）を deps で（間接にも）待たない。待っていたとき、4 周目は検算 172 分と手直し 167 分を締めの前に待った"""
    print("並行の線: 締めの節は線を待たず、線は背景で立てる受領の節で、最後の関門だけが converge の前に在る")
    g = json.loads((PLUGIN / "graphs" / "review-loop.json").read_text(encoding="utf-8"))
    nodes = g["nodes"]

    def closure(nid, seen=None):
        seen = set() if seen is None else seen
        for d in nodes[nid].get("deps", []) + nodes[nid].get("instance_deps", []):
            if d not in seen:
                seen.add(d)
                closure(d, seen)
        return seen
    waiting = [n for n in ("p4.ci", "p4.scalars", "p3.delta_owed", "p3.delta_fix", "r1.minimality", "r2.compare", "r3.coherence",
                           "r4.hidden_scope", "p4.record", "converge", "report") if "p3.delta_gates" in closure(n)]
    check(waiting == [], f"並行の線: 締めの節は線を待たない（待っている節: {waiting}）")
    check(nodes["p3.delta_gates"]["delegate"].get("background") is True and "p3.gates_cut" in nodes["p3.delta_gates"]["deps"],
          "並行の線: 線は修正と手直しが済んだ版（p3.gates_cut）の後に、背景の任せ先で立てる")
    check("p4.final_gates" in nodes["converge"]["deps"] and nodes["p4.final_gates"]["cond"] == {"builtin": "would_converge"},
          "最後の関門: converge は関門を待ち、関門は収束しうる周にだけ撃つ")
    check("p3.lane_merge" in nodes["p3.fix"]["deps"], "合流: 線が足したテストは修正の前に重なる（この周の修正差分に載る）")


def test_lane_rules():
    """線の結果の読み方・判定への渡し方・合流・最後の関門を、盤面を手で組んで直に見る"""
    print("並行の線の規則: 見逃しに全部答えた結果だけを使い、閉じなかった見逃しは 1 度だけ判定へ、patch は当たる物だけ重ね、関門は最終の版だけを数える")
    _td, tmp = parallel.workspace("gl-lane-")
    (tmp / "a.py").write_text("A = 1\n", encoding="utf-8")
    for c in (["init", "-q"], ["config", "user.name", "t"], ["config", "user.email", "t@t"], ["add", "-A"], ["commit", "-qm", "x"]):
        subprocess.run(["git", *c], cwd=tmp, capture_output=True)
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=tmp, capture_output=True, text=True, encoding="utf-8").stdout.strip()
    rules = load_review_rules(tmp)
    from engine.schema import load_graph  # noqa: E402
    graph, _ = load_graph(PLUGIN / "graphs" / "review-loop.json")
    board = tmp / ".git" / "gl-board"
    (board / "lanes").mkdir(parents=True)
    outs = {}
    b = types.SimpleNamespace(round=2, loop_state={}, dir=board, nodes=graph["nodes"], graph=graph,
                              state={"validator": str(VALIDATOR), "inputs": {}},
                              record={"units": [], "questions": [], "materials": {}, "process": {}},
                              output_of_round=lambda n, r: outs.get(n) if r == 2 else None)
    good = lambda rev, **k: {"rev": rev, "arms": [_lane_arm("ok"), _lane_arm("miss", red_confirmed=False)],
                             "handled": [{"key": "arm:miss", "handled": "defect", "how": "変異した方が仕様に合う（検査用）"}],
                             "patch": "", "suite": {"command": "bash run.sh", "exit": 0}, **k}
    E = lambda out, final=False: rules._lane_errors(b, out, head, final)
    check(E(good(head)) == [], f"線の結果: 見逃しに全部答えた結果は通る（{E(good(head))}）")
    for bad, want, desc in [
            (good(head, handled=[]), "に答えが無い", "見逃した腕に答えの無い結果"),
            (good(head, handled=good(head)["handled"] + [{"key": "arm:ok", "handled": "equivalent", "how": "見逃していない腕（検査用）"}]),
             "見逃した腕に無い", "見逃していない腕に答えた結果"),
            ({**good(head), "rev": "0" * 40}, "名指しの版", "名指しと違う版を撃った結果"),
            (good(head, suite={"command": "bash run.sh", "exit": 1}), "緑でない", "テスト一式が赤の結果"),
            (good(head, handled=[{"key": "arm:miss", "handled": "tests_added", "how": "テストを足した（検査用）"}]), "patch", "テストを足したのに patch が無い結果"),
            (good(head, arms=[_lane_arm("nohit", hit_evidence="")], handled=[]), "arm:nohit", "当たりの証拠の無い腕を見逃しと数えない結果")]:
        got = "; ".join(E(bad))
        check(want in got, f"線の結果: {desc}は使わない（{got[:90]}）")
    got = "; ".join(E(good(head, handled=[{"key": "arm:miss", "handled": "tests_added", "how": "テストを足した（検査用）"}], patch="x.patch"), final=True))
    check("作業ツリーに書かない" in got, f"最後の関門: テストを足した（tests_added）と言う関門の返答は拒む（{got[:80]}）")
    # 判定への渡し方: 閉じなかった見逃し（defect・needs_test）だけ、線ごとに 1 度だけ。走っている線は渡さない
    lane = lambda tag, st="running": {"round": 1, "rev": head, "from": head, "result": str(board / "lanes" / f"{tag}.json"),
                                      "patch": str(board / "lanes" / f"{tag}.patch"), "state": st}
    b.loop_state = {"lanes": {head: lane("done"), "f" * 40: {**lane("pending"), "rev": "f" * 40}}}
    out = good(head, arms=[_lane_arm("miss", red_confirmed=False), _lane_arm("miss2", red_confirmed=False), _lane_arm("miss3", red_confirmed=False)],
               handled=[{"key": "arm:miss", "handled": "defect", "how": "変異した方が仕様に合う（検査用）"},
                        {"key": "arm:miss2", "handled": "needs_test", "how": "テストの足場が無い（検査用）"},
                        {"key": "arm:miss3", "handled": "equivalent", "how": "どの入力でも同じ値になる（検査用）"}])
    (board / "lanes" / "done.json").write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
    rows = rules._lane_faces(b)
    keys = sorted(r["key"].split(": ", 1)[1] for r in rows)
    check(keys == ["arm:miss", "arm:miss2"], f"判定への渡し方: 線の中で閉じなかった見逃し（defect・needs_test）だけが次の周の判定へ（{keys}）")
    check(rules._lane_faces(b) == [], "判定への渡し方: 同じ線の見逃しは 1 度だけ渡す")
    check(not b.loop_state["lanes"]["f" * 40].get("delivered"), "判定への渡し方: 結果を書き終えていない線は渡さない（走っている）")
    (board / "lanes" / "pending.json").write_text("{", encoding="utf-8")
    rows = rules._lane_faces(b)
    check(len(rows) == 1 and "結果が使えない" in rows[0]["key"], f"判定への渡し方: 読めない結果は『使えない』の 1 行で渡す（{[r['key'] for r in rows]}）")
    # 合流: 当たる patch は重ね、当たらない patch は重ねずに修正と次の判定へ
    (board / "lanes" / "ok.patch").write_text(LANE_PATCH, encoding="utf-8")
    (board / "lanes" / "ng.patch").write_text(LANE_PATCH.replace("new file mode 100644\n--- /dev/null", "--- a/tests/test_lane.py").replace("@@ -0,0 +1 @@", "@@ -1 +1 @@\n-nothing here"), encoding="utf-8")
    added = [{"key": "arm:miss", "handled": "tests_added", "how": "テストを足してその腕の赤を見た（検査用）"}]
    for tag, patch in (("ok", "ok.patch"), ("ng", "ng.patch")):
        (board / "lanes" / f"{tag}.json").write_text(json.dumps(good(head if tag == "ok" else "e" * 40, handled=added, patch=str(board / "lanes" / patch))), encoding="utf-8")
    b.loop_state = {"lanes": {head: lane("ok"), "e" * 40: {**lane("ng"), "rev": "e" * 40, "round": 2}, "d" * 40: {**lane("none"), "rev": "d" * 40}}}
    r = rules.lane_merge(b, "p3.lane_merge")
    lm = b.loop_state["lane_merge"]
    check(r["ok"] and (tmp / "tests" / "test_lane.py").is_file() and [m["rev"] for m in lm["merged"]] == [head],
          f"合流: 書き終えた線の patch を作業ツリーに重ねる（{lm}）")
    idx = subprocess.run(["git", "diff", "--cached", "--name-only"], cwd=tmp, capture_output=True, text=True, encoding="utf-8").stdout
    check(idx.strip() == "", f"合流: index は触らない（{idx.strip()!r}）")
    check([c["rev"] for c in lm["conflicts"]] == ["e" * 40] and b.loop_state["lanes"]["e" * 40]["state"] == "conflict",
          f"合流: 当たらない patch は重ねず、修正に見せる（{lm['conflicts']}）")
    check(b.loop_state["lanes"]["d" * 40]["state"] == "running", "合流: 結果を書き終えていない線はそのまま待つ")
    rows = rules._lane_faces(b)
    check(any("patch が当たらない" in x["key"] for x in rows), f"合流: 当たらなかった patch は次の周の判定にも渡る（{[x['key'] for x in rows]}）")
    r = rules.lane_merge(b, "p3.lane_merge")
    check(r["ok"] and b.loop_state["lane_merge"]["merged"] == [], "合流: 1 度重ねた線は重ね直さない")
    # 最後の関門: この周の最終の版を撃ち、見逃しが全部等価で、撃った後に作業ツリーが変わっていないときだけ通る
    subprocess.run(["git", "add", "-A"], cwd=tmp, capture_output=True)
    subprocess.run(["git", "commit", "-qm", "y"], cwd=tmp, capture_output=True)
    snap = rules._snapshot("検査用")
    b.loop_state = {"gates_cut": {"round": 2, "rev": snap, "files": []}}
    P = lambda: "; ".join(rules._final_gate_problems(b))
    check("撃っていない" in P(), f"最後の関門: 関門の結果が無い周は通らない（{P()[:60]}）")
    outs["p4.final_gates"] = good(snap, handled=[{"key": "arm:miss", "handled": "equivalent", "how": "どの入力でも同じ値になる（検査用）"}])
    check(P() == "", f"最後の関門: 見逃しが全部等価で、作業ツリーが撃った版のままなら通る（{P()[:80]}）")
    outs["p4.final_gates"] = good(snap, handled=[{"key": "arm:miss", "handled": "needs_test", "how": "テストが要る（検査用）"}])
    check("needs_test" in P(), f"最後の関門: テストが要る見逃しが残れば通らない（{P()[:80]}）")
    outs["p4.final_gates"] = good(snap, handled=[{"key": "arm:miss", "handled": "equivalent", "how": "どの入力でも同じ値になる（検査用）"}])
    (tmp / "a.py").write_text("A = 2\n", encoding="utf-8")
    check("古い" in P(), f"最後の関門: 撃った版の後にコードが変われば、関門の結果は古い（{P()[:80]}）")
    b.loop_state = {"gates_cut": {"round": 1, "rev": snap, "files": []}}
    check("撃っていない" in P(), "最後の関門: 前の周に固めた版の結果は数えない")
    # 受領: 名乗る置き場がこの周の線の置き場と違えば拒む（別の置き場に書いた線は誰も読まない）
    from engine.util import Reject  # noqa: E402
    b.loop_state = {"gates_cut": {"round": 2, "result": str(board / "lanes" / "r2.json")}}
    for lane_path, want in ((str(board / "lanes" / "r2.json"), "通った"), (str(board / "lanes" / "other.json"), "置き場")):
        try:
            rules.POST_CHECKS["lane_receipt"](b, "p3.delta_gates", {"lane": lane_path}, None)
            got = "通った"
        except Reject as e:
            got = str(e)
        check(want in got, f"受領: 線の置き場がこの周の置き場と{'同じなら通る' if want == '通った' else '違えば拒む'}（{got[:70]}）")
    # 線の範囲の切り出し: 周の頭の版が無ければ止まり、在れば版と置き場を置く。範囲が空なら線を台帳に載せない
    b.loop_state = {}
    r = rules.gates_cut(b, "p3.gates_cut")
    check(not r["ok"] and "頭の版が無い" in " ".join(r["problems"]), f"線の範囲: 周の頭の版が無い周は止まる（{r}）")
    b.loop_state = {"head_revs": {"2": head}}
    r = rules.gates_cut(b, "p3.gates_cut")
    cut = b.loop_state["gates_cut"]
    check(r["ok"] and "a.py" in cut["files"] and cut["rev"] in b.loop_state["lanes"] and rules.gates_cut_nonempty(b)
          and cut["result"].startswith(str(board / "lanes")) and cut["reply_schema"].get("required"),
          f"線の範囲: 周の頭からこの版までの変更を置き、線の置き場と結果の型を渡す（{cut.get('files')}）")
    (tmp / "a.py").write_text("A = 1\n", encoding="utf-8")
    subprocess.run(["git", "checkout", "-q", "--", "."], cwd=tmp, capture_output=True)
    b.loop_state = {"head_revs": {"2": rules._snapshot("検査用")}}
    rules.gates_cut(b, "p3.gates_cut")
    check(not rules.gates_cut_nonempty(b) and not b.loop_state.get("lanes"), "線の範囲: 周の頭から変わっていなければ線を立てない")
    b.loop_state["gates_cut"]["round"] = 1
    check(not rules.gates_cut_nonempty(b), "線の範囲: 前の周に固めた範囲では線を立てない")
    rm(tmp)


def test_lane_end_to_end():
    """線を待たずに周が進み、線が後で書いた結果が合流し、最後の関門が収束を止める——端から端まで"""
    print("並行の線（端から端）: 線の結果が無くても周は進み、後で書いた結果の patch は修正の前に重なり、閉じなかった見逃しは次の判定へ、関門は収束を止める")
    run = Run("lane")
    seen = {"lane_written": False, "gate_calls": 0}

    def hook(run_, inst, out):
        st = run_.state()
        if inst["node"] == "p2.history" and st["round"] == 2 and not seen["lane_written"]:
            # 1 周目の線は 2 周目の判定の頃に書き終えた——結果と patch を置き場に書く（線の役の代わり）
            lane = next(x for x in st["loop"]["lanes"].values() if x["round"] == 1)
            pathlib.Path(lane["patch"]).write_text(LANE_PATCH, encoding="utf-8")
            res = {"rev": lane["rev"], "arms": [PROVEN_ARM, _lane_arm("線の見逃し", red_confirmed=False), _lane_arm("線の欠陥", red_confirmed=False)],
                   "handled": [{"key": "arm:線の見逃し", "handled": "tests_added", "how": "テストを足してその腕の赤を見た（検査用）"},
                               {"key": "arm:線の欠陥", "handled": "defect", "how": "変異した方が仕様に合う（検査用）"}],
                   "patch": lane["patch"], "suite": {"command": "pytest（検査用）", "exit": 0}}
            pathlib.Path(lane["result"]).write_text(json.dumps(res, ensure_ascii=False), encoding="utf-8")
            seen["lane_written"] = True
            check(not any("線 r1" in r["key"] for r in st["loop"].get("prev_declared_faces") or []),
                  "並行の線: 2 周目の頭では 1 周目の線はまだ走っている——判定に渡る物は無い（周は線を待たずに進んだ）")
        if inst["node"] == "p4.final_gates":
            seen["gate_calls"] += 1
            if seen["gate_calls"] == 1:
                # 最初の関門はテストの要る見逃しを 1 本見つける——収束せず次の周の判定へ
                return {**out, "arms": [PROVEN_ARM, _lane_arm("関門の見逃し", red_confirmed=False)],
                        "handled": [{"key": "arm:関門の見逃し", "handled": "needs_test", "how": "この分岐を殺すテストが無い（検査用）"}]}
            # 2 回目の関門の見逃しは振る舞いの変わらない変異だけ——等価の宣言は関門を止めない
            return {**out, "arms": [PROVEN_ARM, _lane_arm("関門の等価", red_confirmed=False)],
                    "handled": [{"key": "arm:関門の等価", "handled": "equivalent", "how": "どの入力でも同じ値を返す変異（検査用）"}]}
        return out
    last = drive(run, "std", hook=hook)
    st = run.state()
    check(last["status"] == "converged" and seen["gate_calls"] == 2, f"最後の関門: 見逃しの残る関門は収束を止め、次の周で通って収束する（{last['status']}・関門 {seen['gate_calls']} 回・{st['round']} 周）")
    fd2 = (run.dir / "fix-delta-r2.patch")
    check(fd2.is_file() and "tests/test_lane.py" in fd2.read_text(encoding="utf-8"),
          "合流: 線が足したテストは 2 周目の修正の前に重なり、2 周目の修正差分に載る（差分レビューの目に入る）")
    h3 = json.loads((run.dir / "out" / "r3" / "p2.history.json").read_text(encoding="utf-8"))
    routed = [r["key"] for r in h3.get("declared_routed") or []]
    check(any("arm:線の欠陥" in k for k in routed) and not any("arm:線の見逃し" in k for k in routed),
          f"合流: 線がテストで閉じられなかった見逃し（defect）だけが、書き終えた後の周の判定に届く（{routed}）")
    last_r = st["round"]
    hl = json.loads((run.dir / "out" / f"r{last_r}" / "p2.history.json").read_text(encoding="utf-8"))
    check(any("最後の関門" in r["key"] for r in hl.get("declared_routed") or []),
          f"最後の関門: 関門が見つけた、テストの要る見逃しは次の周の判定に届く（{[r['key'] for r in hl.get('declared_routed') or []]}）")
    lanes = run.record()["process"].get("lanes") or []
    check(lanes and lanes[0]["state"] == "merged" and lanes[0]["open"] == ["arm:線の欠陥"],
          f"記録: 線の台帳の要約（合流したか・閉じなかった見逃し）が process.lanes に残る（{lanes[:2]}）")
    rm(run.tmp)


def test_stuck_routed_at_judge():
    """同じ [block] が 3 周続けて在るのに振り分けた跡（そのユニットを origin に持つ未決の stuck / fork）の無い履歴の再審は、
    判定の節で拒む——周の記録の段（p4.record）で初めて落ちると、その周の判定の節は done 済みで返させ直せない（実測 2026-09-24 の 4 周目）"""
    print("stuck の振り分け: 3 周続く [block] は履歴の再審の返答で振り分けを求める")
    _td, tmp = parallel.workspace("gl-stuck-")
    rules = load_review_rules(tmp)
    (tmp / "rounds").mkdir()
    blk = {"key": "a.py: 入口が残る（検査用）", "label": "block"}
    for n in (2, 3):
        (tmp / "rounds" / f"round-{n}.json").write_text(json.dumps({"round": n, "units": [blk], "questions": []}, ensure_ascii=False), encoding="utf-8")
    b = types.SimpleNamespace(round=4, dir=tmp, state={"validator": str(VALIDATOR)})
    V = rules.validator_module(b)
    got = rules._stuck_unrouted(b, V, {"units": [blk], "questions": []})
    check(len(got) == 1 and "stuck" in got[0], f"stuck の振り分け: 跡の無い 3 周目の [block] は拒む（{got}）")
    q = {"key": "処方か設計か（検査用）", "kind": "stuck", "status": "held", "reason": "検査用", "origin": blk["key"]}
    got = rules._stuck_unrouted(b, V, {"units": [blk], "questions": [q]})
    check(got == [], f"stuck の振り分け: そのユニットを origin に持つ未決の問いが在れば通る（{got}）")
    got = rules._stuck_unrouted(types.SimpleNamespace(round=3, dir=tmp, state=b.state), V, {"units": [blk], "questions": []})
    check(got == [], f"stuck の振り分け: 前の 2 周の記録が揃わない周は求めない（{got}）")
    rm(tmp)


def test_fix_plan_review():
    """**修正を書く前に案を別の目に叩かせ、書いた直後に修正だけの差分を見る。** 修正の良し悪しを見る段が全部『直した後』に
    在ったとき、修正が作った穴は次の周に新しい指摘として挙がった（実測 2026-09-24: 3 周目の指摘のうち 8 件が 2 周目の修正の産物）"""
    print("修正案の事前審査と修正差分のレビュー: 案は直す単位を全部入れ、予測された穴に P3 が答え、修正だけの差分の穴を同じ周で閉じる")
    run = Run("planfaces")
    at = lambda node: (lambda nx: any(i["node"] == node for i in nx["ready"]))

    def refused(node, mutate, want, desc):
        nx = drive(run, "planfaces", stop_at=at(node))
        item = next(i for i in nx["ready"] if i["node"] == node)
        good = answers(run, "planfaces", nx["round"])[node](load_item(item))
        r = run.done(item["id"], mutate(json.loads(json.dumps(good))))
        check(r.returncode == 1 and want in r.stderr, f"{desc}（{r.stderr.strip()[-90:]}）")
    refused("p2.fix_plan", lambda o: {"plan": [{**o["plan"][0], "unit_keys": o["plan"][0]["unit_keys"][:1]}]},
            "どの案にも入っていない単位", "修正案: 直す単位を書き落とした案は拒む")
    # 出した後に graph が変わって deps が増えた節（run の途中で前段を足した形）は、増えた deps を待つ——盤面に
    # 事前審査より先に出ていた p3.fix の instance を置き、事前審査の前の done を engine が拒むことを見る
    drive(run, "planfaces", stop_at=at("p2.plan_review"))
    st = run.state()
    st["rounds"][-1]["instances"]["p3.fix"] = {**st["rounds"][-1]["instances"]["p2.plan_review"], "id": "p3.fix", "node": "p3.fix", "run_by": "writer"}
    (run.dir / "state.json").write_text(json.dumps(st, ensure_ascii=False), encoding="utf-8")
    r = run.done("p3.fix", {"changes": []})
    check(r.returncode == 1 and "がまだ済んでいない" in r.stderr, f"engine: 増えた deps が済む前の done は拒む（{r.stderr.strip()[-90:]}）")
    st["rounds"][-1]["instances"].pop("p3.fix")
    (run.dir / "state.json").write_text(json.dumps(st, ensure_ascii=False), encoding="utf-8")
    refused("p2.plan_review", lambda o: {**o, "faces": [{**o["faces"][0], "unit_keys": ["案に無い単位（検査用）"]}]},
            "は修正案に無い", "事前審査: 案に無い単位を指す穴は拒む")
    refused("p2.plan_review", lambda o: {"faces": [], "shrink": [], "reason": o["reason"]},
            "faces_none", "事前審査: 穴も別案も挙げないなら、確かめたこと（faces_none）が要る")
    refused("p2.plan_review", lambda o: {**o, "faces": [{**o["faces"][0], "kind": "entrance"}]},
            "no_add", "事前審査: 入口の穴に『足さずに閉じる形』（no_add）の無い返答は拒む")
    refused("p3.fix", lambda o: {**o, "plan_faces": o["plan_faces"][:1]},
            "に応答が無い", "修正: 事前審査の別案に答えない修正は拒む")
    refused("p3.fix", lambda o: {**o, "plan_faces": o["plan_faces"] + [{**o["plan_faces"][0], "key": "事前審査に無い穴（検査用）"}]},
            "は事前審査に無い", "修正: 事前審査に無い key への応答は拒む")
    refused("p3.delta_review", lambda o: {**o, "faces": [{**o["faces"][0], "cite": "現物に無い字列（検査用）"}]},
            "の今の姿に無い", "修正差分のレビュー: 触ったファイルに無い字列を指す穴は拒む")
    refused("p3.delta_review", lambda o: {**o, "faces": [{**o["faces"][0], "where": "README.md"}]},
            "この周の修正が触ったファイルでない", "修正差分のレビュー: 修正が触っていないファイルを指す穴は拒む")
    refused("p3.delta_review", lambda o: {**o, "checks": []},
            "に検算が無い", "修正差分のレビュー: 修正が塞いだと言う事前審査の穴を 1 件ずつ検算しない返答は拒む")
    # 塞がっていない検算（closed=false）は faces に書き直さなくても、手直しの節が同じ key で答える義務になる
    nx = drive(run, "planfaces", stop_at=at("p3.delta_review"))
    item = next(i for i in nx["ready"] if i["node"] == "p3.delta_review")
    good = answers(run, "planfaces", nx["round"])["p3.delta_review"](load_item(item))
    r = run.done(item["id"], {**good, "checks": [{**good["checks"][0], "closed": False, "why": "差分で上限の値がまだ 2 か所に在る（検査用）"}]})
    check(r.returncode == 0, f"修正差分のレビュー: 塞がっていない検算は faces に書き直さずに通る（{r.stderr.strip()[-80:]}）")
    # **義務は描画された本文で役に届く**（台本が key を知っている前提で答えると、見せる道が無くても緑になる）。
    # 1 回目: 穴と塞がっていない検算の 2 成分が、手直しの役のプロンプトに全部載る。**変異の検算の見逃しは載らない**——
    # 検算は周の締めを止めない並行の線で、見逃しへの答えも線が持つ（載っていたとき、手直しが検算の終わりを待った）
    nx = drive(run, "planfaces", stop_at=at("p3.delta_fix"))
    item = next(i for i in nx["ready"] if i["node"] == "p3.delta_fix")
    body = pathlib.Path(item["prompt_file"]).read_text(encoding="utf-8")
    for k in ("入口: 呼び元の上限が残る", "写し: 上限の値を 2 か所に"):
        check(k in body, f"手直しの義務: 1 回目の手直しのプロンプトに key『{k}』が載る（穴・塞がっていない検算の 2 成分）")
    check("arm:" not in body.split("修正の差分:")[0], "手直しの義務: 変異の検算の見逃し（arm:<腕>）は手直しの義務に入らない（線が答える）")
    refused("p3.delta_fix", lambda o: {"handled": [h for h in o["handled"] if h["key"] != "写し: 上限の値を 2 か所に"]},
            "写し: 上限の値を 2 か所に", "修正差分の穴: 塞がっていない検算に答えない手直しは拒む")
    refused("p3.delta_fix", lambda o: {"handled": [{**o["handled"][0], "files": []}] + o["handled"][1:]},
            "files が空", "修正差分の穴: fixed なのに触ったファイルが無い応答は拒む")
    refused("p3.delta_fix", lambda o: {"handled": [{**o["handled"][0], "key": "レビューに無い穴（検査用）"}] + o["handled"][1:]},
            "に応答が無い", "修正差分の穴: 挙がった穴に答えない応答は拒む")
    refused("p3.delta_review2", lambda o: {**o, "checks": []},
            "に検算が無い", "手直しの差分のレビュー: 手直しが直したと言う穴を 1 件ずつ検算しない返答は拒む")
    # **義務は描画された本文で役に届く** 2 回目: 手直しの差分のレビューが塞がっていないと言った検算も、2 回目の手直しのプロンプトに載り、答えないと拒む
    nx = drive(run, "planfaces", stop_at=at("p3.delta_review2"))
    item = next(i for i in nx["ready"] if i["node"] == "p3.delta_review2")
    good = answers(run, "planfaces", nx["round"])["p3.delta_review2"](load_item(item))
    open_key = good["checks"][0]["key"]
    r = run.done(item["id"], {**good, "checks": [{**good["checks"][0], "closed": False, "why": "手直しの差分でも呼び元の分岐が残っている（検査用）"}]
                                                + good["checks"][1:]})
    check(r.returncode == 0, f"手直しの差分のレビュー: 塞がっていない検算は faces に書き直さずに通る（{r.stderr.strip()[-80:]}）")
    nx = drive(run, "planfaces", stop_at=at("p3.delta_fix2"))
    item = next(i for i in nx["ready"] if i["node"] == "p3.delta_fix2")
    body = pathlib.Path(item["prompt_file"]).read_text(encoding="utf-8")
    check(open_key in body and "手直しの穴（検査用）" in body,
          f"手直しの義務: 2 回目の手直しのプロンプトに、穴と塞がっていない検算の key が載る（{open_key}）")
    refused("p3.delta_fix2", lambda o: {"handled": [h for h in o["handled"] if h["key"] != open_key]},
            open_key[:20], "2 回目の手直し: 塞がっていない検算に答えない応答は拒む")
    refused("p2.history", lambda o: {**o, "declared_routed": []},
            "を振り分けていない", "次の周の判定: 前の周に残すと宣言された穴を振り分けない判定は拒む")
    refused("p2.history", lambda o: {**o, "declared_routed": [{**o["declared_routed"][0], "route": "to_unit", "unit_key": "今の周に無い単位（検査用）"}]
                                                             + o["declared_routed"][1:]},
            "to_unit なのに", "次の周の判定: 直す単位に上げたと言う穴は、今の周の units に在る単位を指す")
    nx = drive(run, "planfaces")
    pr = run.record()["process"]
    h2 = json.loads((run.dir / "out" / "r2" / "p2.history.json").read_text(encoding="utf-8"))   # process は最後の周の値に上書きされる
    routed = [r["key"] for r in h2.get("declared_routed") or []]
    check("写し: 上限の値を 2 か所に" in routed, f"1 回目の手直しが残すと宣言した穴も、次の周の判定者が振り分ける（{routed}）")
    check("入口: 呼び元が上限を迂回する" in routed, f"修正が残すと宣言した入口の穴（no_add 付き）も、次の周の判定者が振り分ける（{routed}）")
    fd2 = run.dir / "fix-delta2-r1.patch"
    body2 = fd2.read_text(encoding="utf-8") if fd2.is_file() else ""
    added2 = [l for l in body2.splitlines() if l.startswith("+") and not l.startswith("+++")]   # 文脈の行は数えない
    check(any("p3.delta_fix in round 1" in l for l in added2) and not any("fixed in round 1" in l for l in added2),
          f"2 回目の差分は手直しだけ（1 回目の修正後に固めた版からの差）を持つ（{body2[:80]!r}）")
    check("手直しの穴（検査用）" in routed, f"2 回目の手直しは直したと言っても検算されないので、次の周の判定者が振り分ける（{routed}）")
    # **検算していない手直しには旗が付く**——p2.history はこの旗で、直したと言うだけの行を現物で確かめさせる。旗が落ちると
    # 検算していない fixed が declared と同じ扱いになるのに、key の出入りだけを見る検査は緑のままだった（5 周目の判定）
    hp = (run.dir / "prompts" / "r2" / "p2.history.md").read_text(encoding="utf-8")   # 次の周の判定者に実際に貼られた値で見る
    at_decl = hp.index("無ければ []）: ") + len("無ければ []）: ")
    decl = {r["key"]: r for r in json.JSONDecoder().raw_decode(hp[at_decl:])[0]}
    check(decl.get("手直しの穴（検査用）", {}).get("unverified") is True, f"2 回目の手直しが fixed と言った行は unverified の旗を持つ（{decl.get('手直しの穴（検査用）')}）")
    check("unverified" not in decl.get("写し: 上限の値を 2 か所に", {"unverified": 1}),
          "declared の行（残すと宣言した穴）は旗を持たない（旗は検算していない fixed だけ）")
    check(pr.get("delta_review2") is not None and "別案: 定数を 1 つに" in routed,
          f"手直しにもう 1 回差分レビューが当たり、残すと宣言した穴は次の周の判定者が振り分ける（{h2.get('declared_routed')}）")   # process は周の記録（rounds/）に入らず、record.json に残る
    check(pr.get("fix_plan") and pr.get("plan_review", {}).get("faces") and pr.get("delta_fix"),
          f"1 周目の記録に修正案・事前審査の穴・修正差分の穴への応答が残る（{sorted(k for k in pr if k in ('fix_plan', 'plan_review', 'delta_review', 'delta_fix'))}）")
    fixes = [f for f in pr.get("fixes") or [] if f.get("round") == 1]
    check(fixes and len(fixes[-1].get("plan_faces") or []) == 3, f"修正の記録に事前審査への応答が 3 件（穴 2 と別案）残る（{fixes[-1].get('plan_faces') if fixes else None}）")
    fd = run.dir / "fix-delta-r1.patch"   # 最後の周の loop.fix_delta は修正の無い周の空になる——1 周目の写しを見る
    body = fd.read_text(encoding="utf-8") if fd.is_file() else ""
    # 審査対象の変更（src/b.py の新設と f の引数）は周の頭の版に既に在る——累積差分なら載る行が載らない
    check("src/a.py" in body and "fixed in round 1" in body and "src/b.py" not in body and "+def f(x, limit=None)" not in body,
          f"1 周目の修正だけの差分は、その周の修正（src/a.py）だけを持ち、周より前の変更を持たない（{body[:80]!r}）")
    rm(run.tmp)


def test_r_nonpass():
    """**R の非 pass を端から端までの経路で通す。** 台本は 6 周ぶん pass しか返していなかった。

    帰結: R が非 pass のときだけ動く機構——持ち越せない値の据え置き・unverifiable の台帳の自動起票・
    諮りの腕——が、部品を直に呼ぶ腕でしか踏まれていなかった（実測 2026-09-13: 判定語彙 185 値のうち
    到達 63 値で、redesign-needed と unverifiable は R1/R3/R4 とも 0 回）。**その値のための機構を
    同じ周に足していた。**
    """
    print("R の非 pass: redesign-needed と unverifiable を実物の経路で通す")
    run = Run("rnonpass")
    drive(run, "rnonpass")
    rec = run.record()
    rv = rec.get("reviews") or {}
    check(rv.get("R1", {}).get("status") == "redesign-needed", f"R1 の非 pass が記録に着く（{rv.get('R1', {}).get('status')}）")
    check(rv.get("R3", {}).get("status") == "unverifiable", f"R3 の unverifiable が記録に着く（{rv.get('R3', {}).get('status')}）")
    check(rv.get("R4", {}).get("status") == "unverifiable", f"R4 の unverifiable が記録に着く（{rv.get('R4', {}).get('status')}）")
    # unverifiable は「確かめられなかった」——**人に諮る行が機械の側から立つ**（役の申告を待たない）
    qs = [q for q in rec.get("questions", []) if q.get("kind") == "unverifiable"]
    check(qs, f"unverifiable の R には台帳の行が自動で立つ（{len(qs)} 件）")
    check({q.get("origin") for q in qs} >= {"R3", "R4"}, f"どの R が取れなかったかが行に残る（{sorted({q.get('origin') for q in qs})}）")
    rm(run.tmp)


def test_vocab_not_copied():
    """**役に渡す語彙の表は、検証器が組み立てて engine が渡す。プロンプトに写さない。**

    graph は `vocab_owner` で「ここに写さない。手順書も列挙を持たない」と宣言しているのに、
    p2.diagnose.md が問いの種類の表を手で写していた——しかも写しは既にずれていて、
    premise / stuck / rule の origin の要求が落ちていた（実測 2026-09-13）。役は写しの方を読む。

    この腕は**生成されていること**を見る——検証器に種類を足せば、プロンプトに何も書かなくても
    役に届く。写しに戻すと、足した種類が届かないので赤くなる。
    """
    print("語彙の正本: 問いの種類の表は検証器が組み立て、プロンプトは穴で受ける")
    sys.path.insert(0, str(PLUGIN))
    import importlib.util
    from engine.render import Renderer
    spec = importlib.util.spec_from_file_location("vrec", str(VALIDATOR))
    V = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(V)
    tpl = (PLUGIN / "prompts" / "review-loop" / "p2.diagnose.md").read_text(encoding="utf-8")
    check("{{validator.question_kinds}}" in tpl, "プロンプトは種類の表を穴で受ける")
    check("{{validator.question_fields}}" in tpl, "書ける欄の一覧も穴で受ける")

    def render(tables):
        return Renderer({"validator": tables}, ["validator"]).render(tpl[tpl.index("問いの台帳（questions）"):])

    got = render(V.PROMPT_TABLES)
    missing = [k for k in V.QUESTION_KINDS if k not in got]
    check(not missing, f"検証器が知る種類が 1 つ残らず役に届く（届かない: {missing}）")
    for k, v in V.QUESTION_KINDS.items():
        if v.domain == "review":
            check("R1〜R4" in got, f"{k} の origin の要求（R 名）が届く")
            break
    # **生成されている証拠**: 検証器に種類を 1 つ足すと、プロンプトを触らずに届く
    extra = dict(V.QUESTION_KINDS)
    extra["ficticious"] = V.Kind("none", (), "台本が足した架空の種類")
    grown = dict(V.PROMPT_TABLES)
    grown["question_kinds"] = "／".join(
        f"{k}（{V.ORIGIN_NOTE[x.domain]}）: {x.note}" for k, x in extra.items())
    check("ficticious" in render(grown), "検証器に足した種類が、プロンプトを触らずに役へ届く（写しなら届かない）")


def test_purpose_trigger_unevaluable():
    """**引き金が「測れなかった」のを「条件に当たらなかった」と同じ偽にしない。**

    `p0.purpose` は once なので出力は 1 周目で凍る。`source_files` は 5 周目に schema へ足した欄なので、
    凍った出力には無い。以前はここを `... or []` で受けて「触っていない」と同じ偽に畳んでいた
    ——帰結: 目的監査の走り直しが静かに永久に止まり、**R2 が 6 周とも走らなかった**（実測 2026-09-13。
    この run が収束できない本当の理由）。偽を返すのは同じでも、**測れなかったことを痕跡に残す**。

    欄が在って空（出典ファイルを持たない目的）は測れた上での偽なので、痕跡を残さない——
    ここを分けないと、正しい偽まで毎周 process.unevaluable に並んで、読む側が本物を見失う。
    """
    print("引き金の可評価性: 欄が無い（測れない）と、欄が空（測れた偽）を分ける")
    sys.path.insert(0, str(PLUGIN))
    from engine.rules import load_rules
    g = json.loads((PLUGIN / "graphs" / "review-loop.json").read_text(encoding="utf-8"))
    rules = load_rules(PLUGIN / "graphs" / "review-loop.json", g)
    fn = rules.CONDS["purpose_sources_changed"]

    def board(purpose, touched):
        b = types.SimpleNamespace(round=3, state={}, loop_state={"prev_fix_files": touched})
        b.outputs = lambda: {"p0.purpose": purpose}
        b.latest_output = lambda nid: {"p0.purpose": purpose}.get(nid)
        return b

    # 欄が無い＝測れない。偽だが痕跡が残る
    b = board({"purpose_text": "x", "source": "③writer の要約"}, ["README.md"])
    check(fn(b) is False, "欄が無い周は発火しない（合格に倒さない）")
    un = b.state.get("unevaluable") or []
    check(len(un) == 1 and un[0]["trigger"] == "purpose_sources_changed", f"測れなかったことが痕跡に残る（{un}）")
    check("source_files" in un[0]["why"], f"何が無くて測れなかったかが書いてある（{un[0].get('why')}）")
    # cond の葉は 1 回の next で何度も評価される——同じ周で行が増えない
    fn(b), fn(b)
    check(len(b.state["unevaluable"]) == 1, f"同じ周に同じ行を積まない（{len(b.state['unevaluable'])} 行）")
    # **周が変われば積む。** 引き金と周の両方で見ないと、次の周に同じ引き金が測れなかったことが記録から消える
    b.round = 4
    fn(b)
    check(len(b.state["unevaluable"]) == 2, f"周が変われば新しい行を積む（{[u['round'] for u in b.state['unevaluable']]}）")

    # 欄が在って空＝測れた上での偽。痕跡は残さない
    b = board({"purpose_text": "x", "source_files": []}, ["README.md"])
    check(fn(b) is False and not b.state.get("unevaluable"), "欄が在って空なら、測れた偽として痕跡を残さない")

    # 欄が在って、前の周の P3 が触った＝発火
    b = board({"purpose_text": "x", "source_files": ["docs/plan.md", "README.md"]}, ["README.md"])
    check(fn(b) is True and not b.state.get("unevaluable"), "触ったファイルが出典に在れば発火する")
    b = board({"purpose_text": "x", "source_files": ["docs/plan.md"]}, ["README.md"])
    check(fn(b) is False and not b.state.get("unevaluable"), "触ったファイルが出典に無ければ発火しない")


def test_escalate_ratchet():
    """一方向のラチェットの引き金を、**2 つとも実際に踏む**。

    以前は引き金が『一度 info と判定されたキーが後の周に [block] で戻る』の**完全一致**だけだった。
    再燃は毎周ちがうキー文字列で来る（判定者は同じクラスを別の site で立て直す）ので、この集合演算は
    原理的に 0 件——実測 2026-09-13: 6 周とも一度も発火せず、台本を thrash|reburn|escalated|closed_keys で
    grep しても 0 件だった。**名乗り（『同じクラスが戻ったら上げる』）より実装の射程が狭い**形そのもの。
    件数の引き金は**クラスを同定しない**ので、名前の付け方に依らない。
    """
    print("一方向のラチェット: キーの再燃と、件数が落ちないことの 2 つで上がる")
    sys.path.insert(0, str(PLUGIN))
    from engine.rules import load_rules
    g = json.loads((PLUGIN / "graphs" / "review-loop.json").read_text(encoding="utf-8"))
    rules = load_rules(PLUGIN / "graphs" / "review-loop.json", g)
    esc = rules.escalate_on_thrash

    def board(ls):
        return types.SimpleNamespace(round=6, loop_state=ls, record={"process": {}})

    b = board({})
    esc(b)
    check("escalated" not in b.loop_state, "引き金が無ければ上がらない")

    # (1) キーの再燃——完全一致で当たる場合は今も上がる
    b = board({"prev_units": [{"key": "X", "label": "block"}], "closed_keys": ["X"]})
    esc(b)
    check(b.loop_state.get("escalated", {}).get("reburn_count") == 1, "同じキーが info → block で戻ると上がる")

    # (2) **キーが毎周ちがっても、件数が落ちなければ上がる**——ここが以前は 0 件だった面
    stall = {"prev_units": [{"key": "別の site A", "label": "block"}], "closed_keys": ["別の site B"],
             "block_counts": [{"round": 4, "n": 13}, {"round": 5, "n": 13}, {"round": 6, "n": 16}]}
    b = board(stall)
    esc(b)
    e = b.loop_state.get("escalated") or {}
    check(e.get("reburn_count") == 0 and e.get("block_counts") == [13, 13, 16],
          f"キーが 1 件も重ならなくても、件数が {rules.STALL_ROUNDS} 周落ちなければ上がる")
    check("件数が落ちていない" in e.get("why", "") or "減っていない" in e.get("why", ""),
          "上がった理由に件数の推移が入る（自己申告でなく機械が数えた値）")

    # 落ちていれば上がらない——「減らないこと」を見ているのであって「多いこと」ではない
    b = board({"block_counts": [{"round": 4, "n": 13}, {"round": 5, "n": 13}, {"round": 6, "n": 9}]})
    esc(b)
    check("escalated" not in b.loop_state, "件数が 1 度でも落ちていれば上がらない")

    # ラチェットは下がらない（一度上げたら run の残り全部で効く）
    b = board({"escalated": {"round": 2}, "block_counts": [{"round": 4, "n": 1}, {"round": 5, "n": 1}, {"round": 6, "n": 0}]})
    esc(b)
    check(b.loop_state["escalated"]["round"] == 2, "一度上がったら、件数が落ちても下がらない（ラチェット）")


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
    check(b.loop_state["rejudge_rounds"] == {"round": 3, "n": 1} and "rejudge_requested" in b.loop_state,
          "決着しない返答は往復を 1 つ数え、異議は降りない（回数は周とセットで持つ）")
    for _ in range(2):
        checks["rejudge_output"](b, "p2.rejudge", {"verdict": "一部採る", "new_facts": "同じく現物に当たったが、片方の根拠だけが確かめられ、争点は解けないまま残った", "units": []}, None)
    check(not conds["rejudge_open"](b) and conds["rejudge_exhausted"](b),
          f"上限（{rules.REJUDGE_MAX}）に達すると往復の節は閉じ、第三の目が開く（常設でなくここでだけ立つ）")

    # **上限は run 全体でなく 1 周に掛かる。** 以前は回数が周をまたいで積まれたので、どこか 1 周で使い切ると
    # run の残り全部で往復の節が開かず、新しい異議は 1 回目からいきなり第三の目に行った（＝常設しないという
    # 名乗りが破れる）。**次の周に同じ盤面で異議を出すと、往復がまた開く**ことを見る
    b.round = 4
    b.loop_state["rejudge_requested"] = {"round": 4, "text": "次の周の新しい異議"}
    check(conds["rejudge_open"](b) and not conds["rejudge_exhausted"](b),
          "前の周で上限まで往復しても、次の周の異議では往復の節がまた開く（上限は周ごと）")
    checks["rejudge_output"](b, "p2.rejudge", {"verdict": "一部採る", "new_facts": "次の周の争点について現物に当たり、片方だけ確かめられた", "units": []}, None)
    check(b.loop_state["rejudge_rounds"] == {"round": 4, "n": 1}, "周が変わると往復の回数は 1 から数え直す")
    b.round, b.loop_state["rejudge_requested"] = 3, {"round": 3, "text": "今の周の異議"}
    b.loop_state["rejudge_rounds"] = {"round": 3, "n": rules.REJUDGE_MAX}

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
    # **痕跡の欄は、鳴ったら人に見える。** 以前は finalize が process へ写すだけで読む側が 1 つも無く、
    # 「測れなかった周」も静かに終われた（実測 2026-09-14: 検証器 4 本とも process を参照していない）
    sp = run.dir / "state.json"
    st = json.loads(sp.read_text(encoding="utf-8"))
    st["writes_skipped"] = [{"node": "p3.fix", "field": "units"}]
    sp.write_text(json.dumps(st, ensure_ascii=False), encoding="utf-8")
    r = run.cmd("finalize")
    check(r.returncode == 0, f"止まった run の finalize は exit 0（受理集合 [0, 1] は graph の宣言。stderr: {r.stderr[-80:]}）")
    tr = json.loads(r.stdout).get("traces") or {}
    check(tr.get("writes_skipped") == 1, f"非空の痕跡が finalize の出力に件数で出る（{tr}）")
    rm(run.tmp)


def test_reviews_see_the_fix():
    """**R1〜R4 は、P3 が直した後の姿を渡される。**

    差分の写しは P1 の頭で凍結される。P3 は必ず作業ツリーを変える段なので、凍結したままだと
    R は修正前の姿しか見られない——**同じ周で捕まえられるはずの回帰が、次の周まで漏れる**
    （実測 2026-09-16: 2 周とも R1 の judge が『渡された写しは古い』と自分で気づいて作業ツリーを
    直接読み、そのおかげで 1 周目の回帰を捕まえた。仕組みがそうさせたのではない。気づかなかった
    2 件は次の周の P1 が捕まえた）。

    同時に、**周の基準点（diff-r<N>.patch）は上書きしない**——あれは周をまたぐ比較の基準でもあり、
    上書きすると次の周の持ち越しの無効化が効かなくなる（その腕は test_std の carried_over が持つ）。
    """
    print("台本: P3 の後に写しを取り直す——R には修正後、周の基準点は修正前のまま")
    run = Run("retake")
    nx = drive(run, "std", stop_at=lambda nx: any(i["node"] == "r2.compare" for i in nx["ready"]))
    # **測るのは遮断系の側。** r2.compare は blind-judge（道具ゼロ）で、`file:loop.diff_file` として
    # 差分の本文ごと貼られる——古ければ逃げ道が無い。道具を持つ役（r1.minimality の judge）は
    # 自力で作業ツリーを読みに行けてしまうので、前後の差が出にくい（別セッションの実測 2026-09-16:
    # 同じ run で judge は自力で読んで修正後の行を挙げ、blind-judge は「中身が渡されていないので
    # 判定に数えていない。中身を渡して再判定されたい」と書いた）。
    r2 = [i for i in nx["ready"] if i["node"] == "r2.compare"][0]
    body = pathlib.Path(r2["prompt_file"]).read_text(encoding="utf-8")
    check("# fixed in round 1" in body,
          "遮断系（blind-judge）に貼られる本文に、P3 が実際に書いた行が入っている")
    ls = json.loads((run.dir / "state.json").read_text(encoding="utf-8"))["loop"]
    after = pathlib.Path(ls["diff_file"]).read_text(encoding="utf-8")
    check("after-fix" in ls["diff_file"], f"R に渡る写しが P3 の後のもの（{pathlib.Path(ls['diff_file']).name}）")
    check("# fixed in round 1" in after, "取り直した写しに、P3 が実際に書いた行が入っている")
    check(ls.get("retaken_for_reviews"), "取り直したことが盤面に残る（痕跡なしで差し替えない）")
    base = run.dir / "diff-r1.patch"
    check(base.is_file() and "# fixed in round 1" not in base.read_text(encoding="utf-8"),
          "周の基準点（diff-r1.patch）は上書きされていない（次の周の持ち越しの無効化がこれを読む）")
    check(str(base) != ls["diff_file"], "基準点と R 用の写しが別のファイル")
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
        r = run.done(i["id"], t[i["node"]](load_item(i)))
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
    # 一時ディレクトリ（git リポジトリを含む）の後始末は `parallel.workspace`（TemporaryDirectory）が持つ。
    # **消すのは自分が作った作業場だけ**——接頭辞で列挙して差分を消していたとき、実行中に他プロセスが作った
    # 作業場が差分に入り、そのプロセスの盤面が走行中に消えた（実測 2026-09-13: 退行注入と baseline が
    # 互いを殺し、落ちた台本が毎回違った）。持ち手を Run が握るので、台本を抜けた時点で消える
    # （main に届かない落ち方——import 時の例外・engine を壊して全体が落ちる・退行注入の試走——も
    # weakref.finalize がプロセス終了時に覆う。自作の集合 ＋ atexit はこれの再実装だった）。
    # **台本は名前で集めて同時に走らせる。** 手で並べると足した台本の呼び忘れに誰も気づかない
    # （呼ばれない台本は件数を増やさないので件数の柵をすり抜ける）。同時に走らせてよいのは、
    # 台本どうしが自分の作業場しか触らないから——時間はほぼ全部が子プロセスの終了待ちだった
    # （実測 2026-09-13: 94.7 秒のうち 93.8 秒が子プロセス 1,561 回ぶん）。
    # 直列に戻すのは GL_TEST_WORKERS=1——並列でだけ落ちる台本を切り分けるときに使う。
    tests = parallel.collect(globals())
    parallel.run_all(tests)
    reached, total, unreached = vocab_coverage()
    only = bool(os.environ.get("GL_TEST_ONLY"))
    if not only:   # 台本を絞った回は、全台本の到達を見る検査を当てない
        check(reached == VOCAB_REACHED,
              f"判定語彙の到達 {reached}/{total}（記録は {VOCAB_REACHED}）——筋書きを増やしたら数を上げろ。"
              f"未到達の頭: {unreached[:3]}")
    # **本数は「実際に集めて走らせた関数」を数える**（run.sh の grep ではなく）。text を grep すると、
    # 字面だけ変えた（インデントした・改名した）台本が消えても数が合ったままになる
    print(f"台本 {len(tests)} 本")
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
