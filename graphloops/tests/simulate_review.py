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
import signal
import subprocess
import sys
import time
import types

import fakeclaude  # 同じディレクトリ。代役の claude（既定は --output-format json の包みを返す）
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



def _inject():
    """engine が rules に差し込む道具（engine/rules.py の INJECT が正本——写さず import する）"""
    sys.path.insert(0, str(PLUGIN))
    from engine.rules import INJECT
    return INJECT


def _fresh_rules(name):
    """review-loop の rules を新しい module として読む（台本が属性を差し替えても他の台本に漏れない）。条件の宣言（cond_reads）は
    読み込みの時点で要るので、engine と同じ道具を先に差し込む。git を repo に固定したいなら load_review_rules を使う"""
    import importlib.util
    spec = importlib.util.spec_from_file_location(name, PLUGIN / "rules" / "review-loop.py")
    mod = importlib.util.module_from_spec(spec)
    mod.__dict__.update(_inject())
    spec.loader.exec_module(mod)
    return mod


def cond_call(fn, ctx=None, validator=None, state=None, overlay=None):
    """条件の関数を、engine と同じ口（run_cond）で dict の文脈から呼ぶ ——(真偽, 理由)。
    文脈の既定は engine の ctx と同じ前置き（COND_HEADS）で、欠けた欄を読むと engine と同じく die する"""
    sys.path.insert(0, str(PLUGIN))
    from engine.board import COND_HEADS, run_cond
    base = {**{h: {} for h in COND_HEADS}, "round": 1, "thickness": None, **(ctx or {})}
    return run_cond(getattr(fn, "__name__", "cond"), fn, base, validator, state, overlay)

def check(cond, desc):
    # 件数と失敗一覧は台本をまたいで共有される。**`ran += 1` は不可分ではない**ので錠を掛ける
    # ——素で並列にすると数え落とし、件数の柵（run.sh の EXPECTED_CHECKS）が走るたび違う値になる。
    global ran
    with parallel.LOCK:
        ran += 1
        if not cond:
            fails.append(desc)
    parallel.line(("  ok   " if cond else "  FAIL ") + desc)


def skip(desc, capability, reason):
    """環境（OS・道具・権限）で走れない検査。件数には入れ（計画の件数は OS に依らず同じ）、合格と別の印で出す（parallel.skip_line）"""
    global ran
    with parallel.LOCK:
        ran += 1
    parallel.line(parallel.skip_line(desc, capability, reason))


def rm(p):
    """作業場の掃除。消してよいのは一時の置き場より深いパスだけ（外を指したら例外）——正本は parallel.rm"""
    parallel.rm(p)


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
VOCAB_REACHED = 120


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


CHECKS_OK = [{"name": "suite", "argv": [PY, "-c", "print('1 passed')"]}]   # 台本のリポジトリが宣言する走らせる語（緑）


class Run:
    def __init__(self, name, unattended=False, big=False, latin=False, loop="review-loop", inputs=(), init_args=(), graph=None,
                 checks=CHECKS_OK, before_init=None):
        """checks: 台本のリポジトリのルートに置く走らせる語の宣言（.review-checks.json の suite）。既定は緑の 1 段を置く（人の承認は
        要らない。p0.local_checks・p4.ci は engine が走らせる）。None なら宣言を置かない——任せ先の節として出て、台本の表が返答を書く"""
        self._td, self.tmp = parallel.workspace(f"gl-review-{name}-")
        self.env = None   # 全部の呼び出しに渡す環境（代役の gh を PATH の先頭に置く台本が使う）
        self.repo = self.tmp / "repo"
        self.repo.mkdir()
        g = lambda *a: sh(self.repo, "git", "-c", "user.email=t@t", "-c", "user.name=t", *a)
        g("init", "-q")
        (self.repo / "src").mkdir()
        (self.repo / "src" / "a.py").write_text("def f(x):\n    return x\n", encoding="utf-8")
        (self.repo / "README.md").write_text("# demo\n", encoding="utf-8")
        if checks is not None:
            (self.repo / ".review-checks.json").write_text(json.dumps({"suite": checks}), encoding="utf-8")
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
        if before_init:
            before_init(self)
        self.dir = self.tmp / "state"
        args = ["init", "--loop", loop, "--request", "この変更をレビュー", "--dir", str(self.dir), "--validator", str(VALIDATOR)]
        for kv in inputs:
            args += ["--input", kv]
        if unattended:
            args.append("--unattended")
        args += [*(["--graph", str(graph)] if graph else []), *init_args]
        self.init = self.cmd(*args)

    def launch(self, node):
        """engine が走らせる節（mode=engine_run）を launch で走らせる。返りは launch の 1 件の要約"""
        r = self.cmd("launch", "--node", node)
        if r.returncode != 0:
            raise RuntimeError(f"launch {node} が {r.returncode}: {r.stderr[-800:]}")
        return json.loads(r.stdout)["launched"][0]

    def cmd(self, *args, env=None, input=None):
        extra = [] if args[0] == "init" else ["--dir", str(self.dir)]
        # timeout: 無限ループの退行が入ると CI が赤でなく止まる（engine 側は git 120 秒・検証器 600 秒の上限を持つ）
        return subprocess.run([PY, str(LOOP), *args, *extra], cwd=self.repo, capture_output=True, text=True, encoding="utf-8", env=env or self.env, input=input, timeout=600)

    def next(self):
        r = self.cmd("next")
        if r.returncode != 0:
            raise RuntimeError(f"next が {r.returncode}: {r.stderr[-800:]}")
        return json.loads(r.stdout)

    def done(self, node, output, agent_id=None):
        """台本の返答を done で渡す。**engine が走らせる節（mode=engine_run）は done を拒むので launch に回す**——台本の返答は
        使わない（その節の結果は宣言の語の終了コードから engine が組む）。台本が節ごとに書いた駆動の輪をそのまま使えるように"""
        inst = self.state()["rounds"][-1]["instances"].get(node) or {}
        if inst.get("mode") == "engine_run" and inst.get("status") == "pending":
            r = self.cmd("launch", "--node", node)
            got = json.loads(r.stdout)["launched"][0] if r.returncode == 0 else {"ok": False, "why": r.stderr}
            if got["ok"]:
                record_vocab(node, json.loads(pathlib.Path(inst["out_path"]).read_text(encoding="utf-8")))
            return subprocess.CompletedProcess(r.args, 0 if got["ok"] else 1, r.stdout, r.stderr + ("" if got["ok"] else str(got.get("why"))))
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
            rows.append({"skill": name, "items": [], "failed": "applies_cond の条件が偽の周（applies: false）なので起こさなかった", "invoked": False})
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
                               "touches_security_surface": False,
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
                              # 2 つ以上の修正が触った面と、面ごとの修正は機械が changes[].files から出す——面を書き落とすと拒まれる
                              "interactions": ([{"surface": "src/a.py",
                                                 "checked": "上限を寄せる修正と定数を寄せる修正は同じ関数を触るが、当てる順序で結果は変わらない（どちらも共通経路に足すだけ）"}]
                                               if len(rec["units"]) >= 2 else []),
                              "fix_closure": CLEAN("退行を注入して赤→復元して緑") if rec["units"] else M("not_applicable", reason="本ラウンドに修正なし"),
                              # decision_records_changed は任意（リポジトリの外に書いた周だけ）——書かない返答が通ることをここで踏む
                              "mechanism_changed": scenario == "premise_resolved" and rnd == 2, "premise_drift": False, "gates_changed": False,
                              "seams_changed": False, "security_surface_changed": False, "path_changed": False,
                              "wrote_refs": [],
                              # 事前審査の穴と別案に key ごとに 1 行（事前審査が走らなかった周は空）
                              "plan_faces": [{"key": f["key"], "handled": face_how(f["key"])[0], "how": face_how(f["key"])[1]}
                                             for f in (plan_rv.get("faces") or []) + (plan_rv.get("shrink") or [])]},
        "p2.fix_plan": lambda it: {"plan": [{"unit_keys": opened, "approach": "上限を入口の関数 f の 1 か所で掛け、呼び元の分岐を消す（検査用）",
                                             "adds": [{"kind": "guard", "name": "f の上限", "canonical": "src/a.py の f が正本（新設。呼び元には写さない）"}],
                                             "removes": ["呼び元の上限の分岐"],
                                             "shrink_first": "呼び元の分岐を消すだけでは上限が掛からない経路が残るので、入口 1 か所に寄せる（検査用）",
                                             "narrows": []}]},
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
        "r4.hidden_scope": lambda it: ({"status": "unverifiable", "reason": "基準点の材料が取れない（検査用）", "capability_inventory": {"fired": False}, "policy_conflicts": [], "surfaced": []}
                                       if scenario == "rnonpass" else
                                       {"status": "pass", "reason": "導入・露呈した横断リスクなし", "capability_inventory": {"fired": False}, "policy_conflicts": [], "surfaced": []}),
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
        # TDD 版（graphs/review-loop-tdd.json）だけが出す節: [block] は先に落ちるテストで、do-now は理由つきで今の流れへ
        "p3.tdd_tests": lambda it: {"units": [{"unit_key": u["key"], "route": "tdd", "tests": ["tests/test_limit.py::test_limit_is_fixed"],
                                               "surface": "src/a.py の f（公開の関数）",
                                               "friction": {"setup_heavy": False, "reaches_internals": False, "name_unclear": False}}
                                              if u["label"] == "block" else
                                              {"unit_key": u["key"], "route": "direct", "why": "定数の重複をまとめる整理で、振る舞いが変わらない（検査用）"}
                                              for u in rec["units"]],
                                    "test_files": ["tests/test_limit.py"]},
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
    if scenario.startswith("spec"):  # 仕様の道（init --input flow=spec）の節。選ばない筋書きでは出ない
        table.update(spec_table(run, scenario))
    if scenario == "coldfail":  # 初見検査の非 pass は記録に残る（門ではない）
        table["report.cold_check"] = lambda it: {"verdict": "redesign-needed", "stops": ["2 段落目の『前提』が未定義"], "guessed": [], "decidable": False}
    return table


def settle(run, inst, make):
    """ready の 1 件を済ませる: engine が走らせる節（mode=engine_run）は launch、そうでなければ台本の返答を done"""
    if inst.get("mode") == "engine_run":
        got = run.launch(inst["id"])
        if not got["ok"]:
            raise RuntimeError(f"launch {inst['id']} が ok でない: {got.get('why')}")
        return got
    return run.done(inst["id"], make(load_item(inst)))


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
            if inst.get("mode") == "engine_run":
                got = run.launch(inst["id"])
                if got["ok"]:
                    record_vocab(inst["node"], json.loads(pathlib.Path(inst["out_path"]).read_text(encoding="utf-8")))
                elif not got.get("fell_back"):   # 任せ先に回した節は次の next に任せ先の節として出る
                    raise RuntimeError(f"launch {inst['id']} が ok でない: {got.get('why')}")
                continue
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
def test_engine_run_checks():
    """**走らせて写すだけの節は engine が走らせる。** 任せ先（haiku）が写していた頃、テスト 572 件の途中の 537 件で clean と書く・
    CI の 2 系統のうち 1 系統だけ走らせる、が 1 周目で止めた run の全部で出た（実測 2026-09-25）。宣言（.review-checks.json）が
    在れば engine が語を走らせて終了コードから返答を組み、回す側の done は拒む。"""
    print("走らせるだけの節: 宣言があれば承認なしで engine が走らせ、done は拒み、宣言と一致しない語・起こせない語・赤は engine が書き分ける")
    run = Run("engrun")
    nx = run.next()
    inst = next(i for i in nx["ready"] if i["node"] == "p0.local_checks")
    r = run.cmd("done", "--node", inst["id"], "--output", str(run.tmp / "x.json"))
    check(r.returncode == 1 and "engine が走らせる節" in r.stderr, f"engine が走らせる節の結果を回す側が done で書くと拒む（rc={r.returncode}: {r.stderr.strip()[-80:]}）")
    got = run.launch(inst["id"])
    rec = run.record()
    c = rec["process"]["checks"]["p0.local_checks"]
    m = rec["materials"]["local_checks"]
    check(got["ok"] and m["status"] == "clean" and "engine が宣言" in m.get("checked", "") and c["by"] == "engine"
          and c["runs"][0]["exit"] == 0 and pathlib.Path(c["runs"][0]["out"]).read_text(encoding="utf-8").strip() == "1 passed",
          f"launch が宣言の語を走らせ、終了コードで clean を書き、記録に by=engine と段ごとの終了コード・出力の置き場が残る（{m} / {c.get('by')}）")
    rows = [json.loads(x) for x in (run.dir / "trace.jsonl").read_text(encoding="utf-8").splitlines()]
    er = [x for x in rows if x.get("op") == "engine_run" and x.get("instance") == inst["id"]]
    check(len(er) == 1 and [(r_.get("name"), r_.get("exit")) for r_ in er[0].get("runs") or []] == [("suite", 0)],
          f"走らせた段の名前と終了コードは trace に engine_run の 1 行で残る（{er}）")
    check([x.get("instance") for x in rows if x.get("op") == "launch"] == [inst["id"]], "起こした印は trace に launch の 1 行で残る")
    rm(run.tmp)

    # emit の後に宣言を書き換えた——launch は固めた古い語を走らせず『一致しない』と言い、relaunch で今の宣言から計画し直すと新しい語で走る
    run = Run("engrun-changed")
    inst = next(i for i in run.next()["ready"] if i["node"] == "p0.local_checks")
    (run.repo / ".review-checks.json").write_text(json.dumps({"suite": [{"name": "suite", "argv": [PY, "-c", "print('changed')"]}]}), encoding="utf-8")
    got = run.launch(inst["id"])
    check(inst["mode"] == "engine_run" and not got["ok"] and "一致しない" in (got.get("why") or ""),
          f"emit の後に宣言が変わると、launch は固めた語を走らせず宣言と一致しないと言う（{inst['mode']} / {got}）")
    r = run.cmd("relaunch", "--node", inst["id"], "--reason", "検査: 宣言を書き換えた")
    got = run.launch(json.loads(r.stdout)["relaunched"]["id"])
    m = run.record()["materials"]["local_checks"]
    c = run.record()["process"]["checks"]["p0.local_checks"]
    check(got["ok"] and m["status"] == "clean" and pathlib.Path(c["runs"][0]["out"]).read_text(encoding="utf-8").strip() == "changed",
          f"relaunch は今の宣言から計画し直し、承認なしで新しい語を走らせる（{m} / {got}）")
    rm(run.tmp)

    # 盤面の手当てで語と置き場（launch.cwd）を別の場所の宣言に揃えても走らない——engine が突き合わせるのは run の対象リポジトリのルートの宣言だけ
    run = Run("engrun-tamper")
    inst = next(i for i in run.next()["ready"] if i["node"] == "p0.local_checks")
    elsewhere, marker = run.tmp / "elsewhere", run.tmp / "evil-ran"
    elsewhere.mkdir()
    evil = [{"name": "evil", "argv": [PY, "-c", f"open({str(marker)!r}, 'w').write('x')"]}]
    (elsewhere / ".review-checks.json").write_text(json.dumps({"suite": evil}), encoding="utf-8")
    st = run.state()
    at = f"state.rounds.{len(st['rounds']) - 1}.instances.{inst['id']}.launch"
    f = run.tmp / "evil-launch.json"
    f.write_text(json.dumps({**st["rounds"][-1]["instances"][inst["id"]]["launch"], "steps": evil, "cwd": str(elsewhere)}), encoding="utf-8")
    r = run.cmd("patch", "--path", at, "--file", str(f), "--reason", "検査: 盤面の語を差し替える")
    got = run.launch(inst["id"])
    check(r.returncode == 0 and not got["ok"] and "一致しない" in (got.get("why") or "") and not marker.exists(),
          f"盤面で語と launch.cwd を差し替えても、ルートの宣言に無い語は走らない（patch rc={r.returncode} / {got} / 走った={marker.exists()}）")
    rm(run.tmp)

    # 赤の段: 終了コードが 0 でない段を found で数え、出力の末尾を detail に載せる
    run = Run("engrun-red", checks=[CHECKS_OK[0], {"name": "red", "argv": [PY, "-c", "import sys; print('2 failed'); sys.exit(3)"]}])
    inst = next(i for i in run.next()["ready"] if i["node"] == "p0.local_checks")
    run.launch(inst["id"])
    m = run.record()["materials"]["local_checks"]
    check(m["status"] == "found" and m.get("count") == 1 and "red: exit 3" in m.get("detail", "") and "2 failed" in m.get("detail", ""),
          f"赤の段は found で数え、段の名前・終了コード・出力の末尾を detail に書く（{m}）")
    rm(run.tmp)

    # 宣言の語はレビュー対象のリポジトリのルートで走る——launch を下のディレクトリから起こしても段の作業場所はルート
    # （台本の語が場所に依らない 1 行だけだと、engine が作業場所を渡さない退行でも緑のまま）
    run = Run("engrun-cwd", checks=[{"name": "where", "argv": [PY, "-c", "import os; print(os.getcwd())"]}])
    inst = next(i for i in run.next()["ready"] if i["node"] == "p0.local_checks")
    r = subprocess.run([PY, str(LOOP), "launch", "--node", inst["id"], "--dir", str(run.dir)], cwd=run.repo / "src",
                       capture_output=True, text=True, encoding="utf-8", env=run.env, timeout=600)
    runs = run.record()["process"].get("checks", {}).get("p0.local_checks", {}).get("runs") or [{}]
    got = pathlib.Path(runs[0]["out"]).read_text(encoding="utf-8").strip() if runs[0].get("out") else ""
    check(r.returncode == 0 and got and os.path.realpath(got) == os.path.realpath(run.repo),
          f"宣言の語はレビュー対象のリポジトリのルートで走る（launch を起こした場所に依らない）（rc={r.returncode} / {got} / {run.repo}）")
    rm(run.tmp)

    # 起こせない語: P4 の再実行は人待ちを新しく立てず not_run（判定の後の規則）。起こし直しは今の宣言で計画し直す
    run = Run("engrun-p4")
    nx = drive(run, "std", stop_at=lambda n: any(i["node"] == "p4.ci" for i in n["ready"]))
    inst = next(i for i in nx["ready"] if i["node"] == "p4.ci")
    (run.repo / ".review-checks.json").write_text(json.dumps({"suite": [{"name": "suite", "argv": ["no-such-command-gl-test"]}]}), encoding="utf-8")
    r = run.cmd("relaunch", "--node", inst["id"], "--reason", "検査: 宣言を差し替えた")
    new = json.loads(r.stdout)["relaunched"]
    got = run.launch(new["id"])
    m = run.record()["materials"]["local_checks"]
    check(got["ok"] and m["status"] == "not_run" and "起こせない" in m.get("reason", ""),
          f"起こせない語は P4 では not_run（人待ちを新しく立てない）で理由を書く（{m}）")
    # 起こし直した試行（.a2）の置き場にも、engine が組んだ返答を書く（試行ごとに置き場が分かれ、周の出力の写しとは別の所）
    wrote = pathlib.Path(new["out_path"])
    check(".a2" in wrote.name and wrote.is_file() and json.loads(wrote.read_text(encoding="utf-8")).get("material", {}).get("status") == "not_run",
          f"engine が組んだ返答は起こし直した試行の置き場に書く（{new['out_path']}）")
    rm(run.tmp)

    # 宣言の無いリポジトリの clean は任せ先の自己申告——収束を名乗らず人に諮る（有人）。記録に by=role と理由が残る
    run = Run("engrun-role", checks=None)
    last = drive(run, "std")
    c = run.record()["process"]["checks"].get("p4.ci") or {}
    check(last["status"] == "awaiting_human" and "ci_unverified" in last["ask"]["kinds"] and "任せ先" in last["ask"]["question"]
          and c.get("by") == "role" and "が無い" in c.get("why", ""),
          f"任せ先が clean と書いた CI では収束せず ci_unverified で諮る（{last['status']} / {c}）")
    rm(run.tmp)


def test_engine_run_parallel_pr():
    """並行 PR の 1〜5 段は engine が同梱の parallel-pr.py で走らせる（gh -R・自分の PR の除外・打ち切り・交差）。
    交差が在れば 6 段（hunk を読んで申し送る）が要るので任せ先の節に回す。代役の gh で撃つ"""
    print("並行 PR: GitHub の remote と gh が在れば engine が交差を数え、交差 0 は clean、交差があれば任せ先に回す")
    for conflict in (False, True):
        run = Run("engpr-" + ("hit" if conflict else "none"))
        sh(run.repo, "git", "remote", "add", "origin", "git@github.com:t/demo.git")
        bindir = run.tmp / "fakegh"
        bindir.mkdir()
        body = ("import json, sys\n"
                "a = sys.argv[1:]\n"
                "if a[:2] == ['pr', 'list']:\n"
                "    assert a[a.index('-R') + 1] == 't/demo'\n"
                "    print(json.dumps([{'number': 7, 'headRefName': 'x', 'headRefOid': 'f' * 40}]))\n"
                "elif a[:2] == ['pr', 'view']:\n"
                f"    print({'src/a.py' if conflict else 'other.txt'!r})\n"
                "else:\n"
                "    sys.exit(9)\n")
        impl = bindir / "fake_gh.py"
        impl.write_text(body, encoding="utf-8")
        if os.name == "nt":
            (bindir / "gh.bat").write_text(f'@echo off\r\n"{sys.executable}" "{impl}" %*\r\n', encoding="utf-8")
        else:
            (bindir / "gh").write_text(f"#!{sys.executable}\n" + body, encoding="utf-8")
            (bindir / "gh").chmod(0o755)
        run.env = {**os.environ, "PATH": str(bindir) + os.pathsep + os.environ.get("PATH", "")}
        nx = drive(run, "std", stop_at=lambda n: any(i["node"] == "p0.parallel_pr" for i in n["ready"]))
        inst = next(i for i in nx["ready"] if i["node"] == "p0.parallel_pr")
        got = run.launch(inst["id"])
        if not conflict:
            m = run.record()["materials"]["parallel_pr"]
            pp = run.record()["process"].get("parallel_pr") or {}
            check(inst["mode"] == "engine_run" and got["ok"] and m["status"] == "clean" and pp.get("repo") == "t/demo" and pp.get("listed") == 1,
                  f"交差 0: engine が gh -R t/demo で 1 件引き、clean を書く（{inst['mode']} / {m} / {pp}）")
        else:
            again = next(i for i in run.next()["ready"] if i["node"] == "p0.parallel_pr")
            check(not got["ok"] and got.get("fell_back") and again["mode"] == "runner" and again.get("delegate", {}).get("model") == "sonnet"
                  and "交差" in (again.get("engine_fallback") or ""),
                  f"交差あり: 6 段の申し送りは役——同じ節を理由つきの任せ先の節として出し直す（{got.get('why')} / {again['mode']}）")
            rows = [json.loads(x) for x in (run.dir / "trace.jsonl").read_text(encoding="utf-8").splitlines()]
            fb = [x for x in rows if x.get("op") == "engine_fallback" and x.get("instance") == inst["id"]]
            check(len(fb) == 1 and "交差" in (fb[0].get("reason") or ""), f"任せ先に回したことは trace に理由つきで 1 行残る（{fb}）")
            check(got.get("fell_back") and "任せ先の節に回した" in (got.get("why") or "") and not got.get("superseded"),
                  f"任せ先に回した行は『起こし直された古い試行』に言い換えず、次の手（next）を言う（{got.get('why')}）")
        rm(run.tmp)


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
    # launch はレビュー対象の外（盤面の親）から呼ぶ——子は呼んだ場所でなく盤面の inputs.cwd で起きる
    flog = run.tmp / "fake.log"
    r = subprocess.run([PY, str(LOOP), "launch", "--node", inst["id"], "--dir", str(run.dir)], cwd=run.tmp,
                       capture_output=True, text=True, encoding="utf-8", timeout=600,
                       env={**env, "FAKE_MODE": "bad_then_answer", "FAKE_OUT": str(ans), "FAKE_SESSION": "sess-judge", "FAKE_LOG": str(flog)})
    got = json.loads(r.stdout)["launched"] if r.returncode == 0 else [{}]
    one = next((g for g in got if g.get("node") == "p2.diagnose"), {})
    check(one.get("ok") and one.get("resumes") == 1 and one.get("session_id") == "sess-judge",
          f"散文を返した judge に同じ会話で出し直させ、受け付けまで済ませる（{one.get('why') or r.stderr[-200:]}）")
    cwds = {os.path.realpath(json.loads(x)["cwd"]) for x in flog.read_text(encoding="utf-8").splitlines()} if flog.is_file() else set()
    check(cwds == {os.path.realpath(run.repo)},
          f"子はレビュー対象の作業ツリー（inputs.cwd）で起きる——launch を呼んだ場所ではない（{cwds}）")
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


def test_launch_delegate_fenced():
    """任せ先（delegate）を engine が sandbox の形で起こす: 作業ディレクトリは本物の写しで、終わったら消え、本物の作業ツリーも
    .git も変わらない。sandbox の名指しは起こす瞬間に git から組み直して突き合わせ、next の後に作業ツリーが足されたら起こさない。
    配布先で Agent ツールの任せ先が本物の作業ツリーで git reset --hard を打った事故（2026-09-25）への直し"""
    print("任せ先の柵: engine が写しの上で sandbox の形で起こし、名指しがずれたら起こさない")
    # p0.local_checks は宣言（.review-checks.json）が在れば engine が走らせる節（engine_run）なので、宣言を置かずに
    # 任せ先の節（engine_fallback）として出す
    run = Run("delegate", checks=None)
    g = lambda *a: sh(run.repo, "git", *a).stdout
    nx = run.next()
    inst = next(i for i in nx["ready"] if i["node"] == "p0.local_checks")
    argv = (inst.get("launch") or {}).get("argv") or []
    after = lambda flag: argv[argv.index(flag) + 1] if flag in argv else None
    deny = (json.loads(after("--settings") or "{}").get("sandbox") or {}).get("filesystem", {}).get("denyWrite") or []
    real = lambda p: os.path.realpath(p)
    check(inst["launch"].get("kind") == "delegate" and after("--permission-mode") == "default" and after("--permission-prompts") == "none"
          and after("--setting-sources") == "" and "Bash" in (after("--tools") or "").split(",")
          and "Bash" not in (after("--allowedTools") or "").split(",")
          and not {"Write", "Edit"} & set((after("--tools") or "").split(","))
          and all(real(p) in deny for p in (run.repo, run.repo / ".git", run.dir)),
          f"任せ先は launch を持ち、sandbox が本物の作業ツリー・.git・盤面を名指しし、Bash は先に許さず、書く道具を持たない（{argv[2:12]}）")
    bindir = run.tmp / "fakebin"
    bindir.mkdir()
    fakeclaude.install(bindir)
    env = {**os.environ, "PATH": str(bindir) + os.pathsep + os.environ.get("PATH", "")}
    r = run.cmd("relaunch", "--node", inst["id"], "--reason", "検査: 代役の claude に向ける", env=env)
    check(r.returncode == 0, f"relaunch できる（{r.stderr[-120:]}）")
    sh(run.repo, "git", "worktree", "add", "-q", str(run.tmp / "late"), "-b", "late")
    ans, log = run.tmp / "lc.json", run.tmp / "fake.log"
    ans.write_text(json.dumps({"material": CLEAN("python -m pytest（緑）")}, ensure_ascii=False), encoding="utf-8")
    fenv = {**env, "FAKE_OUT": str(ans), "FAKE_LOG": str(log)}
    r = run.cmd("launch", "--node", inst["id"], env=fenv)
    one = (json.loads(r.stdout)["launched"] if r.returncode == 0 else [{}])[0]
    check(not one.get("ok") and "--settings" in (one.get("why") or "") and not log.exists(),
          f"next の後に作業ツリーが足されたら、sandbox の名指しが今の守る場所と揃わないので起こさない（{(one.get('why') or r.stderr)[-120:]}）")
    r = run.cmd("relaunch", "--node", inst["id"], "--reason", "検査: 名指しを組み直す", env=env)
    (run.repo / "src" / "a.py").write_text("def f(x):\n    return x  # 未コミット\n", encoding="utf-8")
    (run.repo / "src" / "new.py").write_text("N = 1\n", encoding="utf-8")
    before = g("status", "--porcelain"), g("worktree", "list", "--porcelain"), g("rev-parse", "HEAD")
    r = run.cmd("launch", "--node", inst["id"], env=fenv)
    one = (json.loads(r.stdout)["launched"] if r.returncode == 0 else [{}])[0]
    seen = json.loads(log.read_text(encoding="utf-8").splitlines()[-1]) if log.exists() else {}
    cwd = pathlib.Path(seen.get("cwd") or "/nonexistent")
    check(one.get("ok") and seen and real(cwd) != real(run.repo) and not real(cwd).startswith(real(run.repo) + os.sep)
          and {"src", "README.md", ".git"} <= set(seen.get("cwd_files") or [])
          and real(seen.get("tmpdir") or "/").startswith(real(cwd.parent)),
          f"任せ先は本物の外の写しを作業ディレクトリにし、TMPDIR も同じ置き場に向けて起こす（{one.get('why')} {seen.get('cwd')}）")
    check(not cwd.parent.exists(), f"終わった任せ先の置き場（写しと TMPDIR）は消える（{cwd.parent}）")
    check((g("status", "--porcelain"), g("worktree", "list", "--porcelain"), g("rev-parse", "HEAD")) == before,
          "任せ先を起こしても本物の作業ツリー・index・worktree の登録・HEAD は変わらない")
    st = run.state()
    me = next((i for i in st["rounds"][0]["instances"].values() if i["node"] == "p0.local_checks" and i["status"] == "done"), {})
    check(me.get("status") == "done", "任せ先の返答は engine が受け付けまで済ませる（回す側の done は要らない）")
    rm(run.tmp)


def test_launch_delegate_background_lane():
    """背景の任せ先（p3.delta_gates）は受領を done した後にだけ、名指しで 1 回だけ起こせ、子の返答は engine が線の置き場に置く"""
    print("背景の任せ先: 受領の後に名指しで 1 回だけ起こし、返答は engine が線の置き場に置く")
    run = Run("delegatebg")
    nx = drive(run, "std", stop_at=lambda n: any(i["node"] == "p3.delta_gates" for i in n["ready"]))
    inst = next(i for i in nx["ready"] if i["node"] == "p3.delta_gates")
    cut = run.state()["loop"]["gates_cut"]
    check(inst["launch"].get("background") and inst["launch"].get("result_path") == cut["result"],
          f"背景の任せ先は launch に線の置き場を持つ（{inst['launch'].get('result_path')}）")
    bindir = run.tmp / "fakebin"
    bindir.mkdir()
    fakeclaude.install(bindir)
    env = {**os.environ, "PATH": str(bindir) + os.pathsep + os.environ.get("PATH", "")}
    run.cmd("relaunch", "--node", inst["id"], "--reason", "検査: 代役の claude に向ける", env=env)
    r = run.cmd("launch", "--node", inst["id"], env=env)
    check(r.returncode == 1 and "受領を done してから" in r.stderr, f"受領の前には起こさない（{r.stderr.strip()[-120:]}）")
    r = run.done(inst["id"], {"lane": cut["result"]})
    check(r.returncode == 0, f"受領は done で通る（{r.stderr[-120:]}）")
    lane = {"rev": cut["rev"], "arms": [PROVEN_ARM], "handled": [], "patch": "", "suite": {"command": "pytest（検査用）", "exit": 0}}
    ans = run.tmp / "lane.json"
    ans.write_text("```json\n" + json.dumps(lane, ensure_ascii=False) + "\n```", encoding="utf-8")   # 囲い付きの返答も解いて置く
    r = run.cmd("launch", "--node", inst["id"], env={**env, "FAKE_OUT": str(ans), "FAKE_KEEP": "lane.patch"})
    one = (json.loads(r.stdout)["launched"] if r.returncode == 0 else [{}])[0]
    placed = pathlib.Path(cut["result"])
    kept = pathlib.Path(one.get("kept") or "/nonexistent")
    check(one.get("ok") and placed.is_file() and json.loads(placed.read_text(encoding="utf-8")) == lane
          and not pathlib.Path(cut["result"] + ".tmp").exists(),
          f"子の返答は engine が線の置き場に置く（書きかけは残さない。{one.get('why') or r.stderr[-120:]}）")
    check((kept / "lane.patch").is_file() and not (kept.parent / "work").exists() and not (kept.parent / "tmp").exists(),
          f"任せ先が GRAPHLOOPS_KEEP に置いた物だけ残り、写しと TMPDIR は消える（{kept}）")
    r = run.cmd("launch", "--node", inst["id"], env={**env, "FAKE_OUT": str(ans)})
    two = (json.loads(r.stdout)["launched"] if r.returncode == 0 else [{}])[0]
    check(not two.get("ok") and "起こし済み" in (two.get("why") or ""), f"同じ線は 2 度起こさない（{two.get('why')}）")
    # 消すのは engine が返した置き場（…/graphloops-delegate-*/keep の親）だけ。launch が kept を返さずに落ちた回（腕が launch を
    # 壊した回を含む）に代わりの綴りの親を消すと、"/nonexistent" の親＝ "/" を rmtree する（実測 2026-09-26: 取りまとめの手元で 2 回踏んだ）
    if one.get("kept") and pathlib.Path(one["kept"]).name == "keep":
        rm(kept.parent)
    rm(run.tmp)


def test_unfenced_delegates_only_when_named():
    """柵を外すのは人が init --unfenced-delegates で明示した run だけ。外した事実は盤面と next の notes に残る"""
    print("柵を外す口: init --unfenced-delegates の run だけ任せ先が launch を持たず、外した事実と理由が盤面と notes に出る")
    run = Run("unfenced", checks=None)   # 宣言が無いので p0.local_checks は任せ先の節として出る（宣言が在れば engine_run）
    d2 = run.tmp / "s-unfenced"
    r = subprocess.run([PY, str(LOOP), "init", "--loop", "review-loop", "--request", "q", "--dir", str(d2),
                        "--validator", str(VALIDATOR), "--unfenced-delegates", "docker を使う CI（検査用）"],
                       cwd=run.repo, capture_output=True, text=True, encoding="utf-8", timeout=600)
    check(r.returncode == 0, f"柵を外した run を init できる（{r.stderr[-120:]}）")
    r = subprocess.run([PY, str(LOOP), "next", "--dir", str(d2)], cwd=run.repo, capture_output=True, text=True, encoding="utf-8", timeout=600)
    nx = json.loads(r.stdout) if r.returncode == 0 else {"ready": [], "notes": []}
    inst = next((i for i in nx["ready"] if i["node"] == "p0.local_checks"), {})
    st = json.loads((d2 / "state.json").read_text(encoding="utf-8"))
    trace = (d2 / "trace.jsonl").read_text(encoding="utf-8")
    check(not inst.get("launch") and (inst.get("unfenced") or {}).get("reason") == "docker を使う CI（検査用）"
          and st.get("unfenced_delegates", {}).get("reason") == "docker を使う CI（検査用）" and "unfenced_delegates" in trace
          and any("柵" in n for n in nx.get("notes") or []),
          f"外した run の任せ先は launch を持たず unfenced を持ち、外した事実が state・trace・notes に残る（{inst.get('launch')}）")
    r = subprocess.run([PY, str(LOOP), "launch", "--node", inst.get("id") or "p0.local_checks", "--dir", str(d2)], cwd=run.repo,
                       capture_output=True, text=True, encoding="utf-8", timeout=600)
    check(r.returncode == 1 and "起こせる節が無い" in r.stderr,
          f"launch を持たない節を名指しした launch は、例外で死なずに起こせる節が無いと断る（{r.returncode}: {r.stderr[-120:]}）")
    base = next(i for i in run.next()["ready"] if i["node"] == "p0.local_checks")
    check(base.get("launch", {}).get("kind") == "delegate" and "unfenced" not in base,
          "明示の無い run の任せ先は柵の形（launch）で起こす")
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
    print("否定検査: 2 周目に塞いだ柵（実測の再現・cond の名前・空返答・空差分・受理集合）")
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
        settle(run, by[n], t[n])
    nx = run.next()
    check(any("対象差分が空" in n for n in nx["notes"]) and not any(i["node"].startswith("p1.") for i in nx["ready"]), f"BASE=HEAD（差分ゼロ）は P1 の前で止まる: {nx.get('notes')}")
    # 止まった地点から入口へ行ける: 拒否文が --dir つきの add を案内し、案内どおりに打つと判定から入る
    check(any("loop.py add --file" in n and "--dir <DIR>" in n for n in nx["notes"]),
          f"空差分の拒否文は、1 周目の P1 の前なら判定から入る add を案内する: {nx.get('notes')}")
    f = run.tmp / "req.json"
    f.write_text(json.dumps([{"where": "src/a.py:f", "text": "人の依頼（検査用）"}], ensure_ascii=False), encoding="utf-8")
    r = run.cmd("add", "--file", str(f), "--reason", "利用者の依頼（検査用）")
    nx = run.next()
    check(r.returncode == 0 and run.record()["process"].get("request_entry") and not any("対象差分が空" in n for n in nx["notes"])
          and not any(i["node"].startswith("p1.") for i in nx["ready"]),
          f"案内どおりの add で入口が開き、空差分で止まらずに進む（{r.stdout[-160:]}{r.stderr[-160:]} / {nx.get('notes')}）")
    rm(run.tmp)

    # add しても入口が開かない所では案内しない（型の崩れた印が在る run——案内どおりに打っても P1 はいつもどおり走る）
    run = Run("emptydiff-noentry")
    f = run.tmp / "bad-entry.json"
    f.write_text(json.dumps("patch（検査）", ensure_ascii=False), encoding="utf-8")
    run.cmd("patch", "--path", "process.request_entry", "--file", str(f), "--reason", "検査")
    nx = run.next()
    by = {i["node"]: i for i in nx["ready"]}
    t = answers(run, "std", 1)
    head = sh(run.repo, "git", "rev-parse", "HEAD").stdout.strip()
    run.done(by["p0.base"]["id"], {**t["p0.base"](None), "base_sha": head})
    for n in ("p0.local_checks", "p0.premises"):
        run.done(by[n]["id"], t[n](None))
    nx = run.next()
    check(any("対象差分が空" in n for n in nx["notes"]) and not any("loop.py add" in n for n in nx["notes"]),
          f"add で入口が開かない所の空差分の拒否文は add を案内しない: {nx.get('notes')}")
    rm(run.tmp)

    # git が取れない場では対象差分そのものが測れない——空文字に潰して「変化なし」にしない
    run = Run("nogit-snap")
    nx = run.next()
    by = {i["node"]: i for i in nx["ready"]}
    t = answers(run, "std", 1)
    for n in ("p0.base", "p0.local_checks", "p0.premises"):
        settle(run, by[n], t[n])
    (run.tmp / "empty-bin").mkdir()
    r = run.cmd("next", env={**os.environ, "PATH": str(run.tmp / "empty-bin")})
    nx = json.loads(r.stdout) if r.returncode == 0 and r.stdout.strip().startswith("{") else {"ready": ["?"], "notes": [r.stderr]}
    check(any("git が取れない" in n or "取れない" in n for n in nx["notes"]), f"git が無い場では対象差分の取得で止まる（空文字に潰さない）: {str(nx.get('notes'))[:100]}")
    rm(run.tmp)

    # cond が rules の CONDS に無い名前の graph は init で止まる（以前の JSON の条件では loop. の葉の綴り違いが
    # 静的検査の外で、next まで進んでから die していた——宣言の検査は graphcheck が init の前に当てる）
    _td_tmp, tmp = parallel.workspace("gl-cond-")
    g = json.loads((PLUGIN / "graphs" / "review-loop.json").read_text(encoding="utf-8"))
    g["nodes"]["p0.local_checks"]["cond"] = "no_such_cond"
    (tmp / "graphs").mkdir()
    for sub in ("prompts", "rules"):
        shutil.copytree(PLUGIN / sub, tmp / sub)
    (tmp / "graphs" / "badcond.json").write_text(json.dumps(g, ensure_ascii=False), encoding="utf-8")
    run = Run("badcond")
    r = run.cmd("init", "--loop", "review-loop", "--graph", str(tmp / "graphs" / "badcond.json"),
                "--request", "x", "--dir", str(run.tmp / "s2"), "--validator", str(VALIDATOR))
    check(r.returncode != 0 and "CONDS の名前でない" in r.stderr and not (run.tmp / "s2" / "state.json").exists(),
          f"CONDS に無い条件の名前は init で止まる（盤面を作らない）: rc={r.returncode} {r.stderr[-120:]}")
    rm(tmp); rm(run.tmp)



def test_pointer_hole_dropped_after_init():
    """**番号を振る一覧の穴が指示書から消えたら、その節を役に出さずに止める。** graphcheck は init で『reads の欄を使う穴が在る』を
    見るが、init の後に指示書が書き換わる（run の途中の手直し）と、番号を振るはずの一覧が役に見えないまま出る——役は番号で
    指せず、受け付けは番号を名前に戻せない。engine は描いた時点で、貼った穴が pointers の from を覆うかを確かめる"""
    print("pointers の from を貼る穴が init の後に指示書から消えたら、その節を出す next で止まる")
    _td_tmp, tmp = parallel.workspace("gl-ptrhole-")
    for sub in ("graphs", "prompts", "rules"):
        shutil.copytree(PLUGIN / sub, tmp / sub)
    run = Run("ptrhole", graph=tmp / "graphs" / "review-loop.json")
    check(run.init.returncode == 0, f"写した graph で init が通る: {run.init.stderr[-200:]}")
    p = tmp / "prompts" / "review-loop" / "p2.diagnose.md"
    text = p.read_text(encoding="utf-8")
    check("{{?prev.r1.minimality.deletions}}" in text, "p2.diagnose の指示書に削除候補の一覧を貼る穴が在る（台本の前提）")
    p.write_text(text.replace("{{?prev.r1.minimality.deletions}}", ""), encoding="utf-8")
    try:
        drive(run, "std")
        err = ""
    except RuntimeError as e:
        err = str(e)
    check("p2.diagnose: pointers の from ['prev.r1.minimality.deletions'] を貼る穴がプロンプトに無い" in err,
          f"穴の消えた p2.diagnose は出さずに止める: {err[-300:]}")
    rm(tmp); rm(run.tmp)

def test_prev_fix_faces_scalar():
    """**前の周の修正が作った面を、規模の数値として周ごとに残す。** 判定役が再燃の原因に『前の周の修正』を選んだ
    件数を機械が数える——散文の note に逃がしていた頃は、収束をいちばんよく表す数が記録に残らなかった。"""
    print("再燃の原因: 『前の周の修正』の件数が、その周の記録の scalars に載る")
    run = Run("prevfix")

    def hook(run_, inst, out):
        if inst["node"] == "p2.history" and "history_prompt" not in prompts:
            prompts["history_prompt"] = pathlib.Path(inst["prompt_file"]).read_text(encoding="utf-8")
        if inst["node"] == "p2.history" and isinstance(out, dict) and out.get("router") and not seen:
            seen.append(inst["id"])   # 2 周目の 1 回だけ（3 周目は 0 件に戻ることも見る）
            k = out["router"][0]["key"]   # 同じ key を 2 度書いても 1 件と数える
            return {**out, "reburn_causes": [{"key": k, "cause": "前の周の修正", "note": "検査用"},
                                             {"key": k, "cause": "前の周の修正", "note": "検査用（重複）"},
                                             {"key": k + "（別）", "cause": "コード", "note": "原因が別なら数えない"}]}
    seen, prompts = [], {}
    drive(run, "std", hook=hook)
    own = prompts.get("history_prompt", "").split("前の周の修正役が自分で当たった先行例", 1)[-1][:600]
    check("https://example.invalid/limit" in own,
          "修正役が自分で当たった先行例（判定者の行を採っていない行）が、次の周の履歴の突合のプロンプトに出典つきで渡る")
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
    # 修正役が自分で当たった先行例は、p2.history を省いた周に渡っていた分を次の周へ持ち越す（上書きで消さない）
    run = Run("prevfix-ownskip")
    hist = []

    def hook_own(run_, inst, out):
        if inst["node"] == "p3.fix" and isinstance(out, dict):   # 周ごとに出典の印を変え、どの周の行が届いたかを見分ける
            mark = f"https://example.invalid/own-r{run_.state()['round']}"
            return {**out, "changes": [{**c, "precedent": {**c["precedent"], "source": mark}} for c in out.get("changes", [])]}
        if inst["node"] == "p2.history" and isinstance(out, dict):
            hist.append(pathlib.Path(inst["prompt_file"]).read_text(encoding="utf-8"))
            if len(hist) == 1:
                return {"__skip__": "検査用に省く"}
        return None
    drive(run, "std", hook=hook_own)
    own = [h.split("前の周の修正役が自分で当たった先行例", 1)[-1].split("——**1 件ずつ出典を開いて", 1)[0] for h in hist]
    check(len(own) >= 2 and "own-r1" in own[0] and "own-r1" in own[1],
          f"p2.history を省いた周に渡っていた修正役の先行例（1 周目の修正の行）は、次の周の p2.history へ持ち越される（{[o[-200:] for o in own[:2]]}）")
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
    """**規模の数値は engine が数え、その場で足す数値の名前は型で固定する。** 写す側が数えていた頃は、added_lines 0（実測 457）・
    1957（実測 9）・全部 0 と写し違えた（実測 2026-09-25）。写す側への『そのまま写せ』だけに頼っていた頃は、改名した名前でも
    型を通った（実走の申し送り: 3 回改名）。"""
    print("規模の数値: 固定の 4 つは engine が数え、p3.fix が足す x_ の名前は型で固定され、未知の名前は拒まれる")
    run = Run("scalarnames")
    nx = drive(run, "std", stop_at=lambda n: any(i["node"] == "p3.fix" for i in n["ready"]))
    inst = next(i for i in nx["ready"] if i["node"] == "p3.fix")
    good = answers(run, "std", 1)["p3.fix"](load_item(inst))
    r = run.done(inst["id"], {**good, "x_scalars": {"lines_added": 4}})
    check(r.returncode == 1 and "lines_added" in r.stderr, f"未知の名前（lines_added）は型で拒む（rc={r.returncode}: {r.stderr.strip()[-90:]}）")
    r = run.done(inst["id"], {**good, "x_scalars": {"x_arms_fired": "12"}})
    check(r.returncode == 1 and "x_arms_fired" in r.stderr, f"x_ の名前も値は数（文字列は型で拒む。rc={r.returncode}: {r.stderr.strip()[-90:]}）")
    for f in {f for c in good["changes"] for f in c.get("files", [])}:   # drive と同じく申告どおりに手を入れる
        (run.repo / f).write_text((run.repo / f).read_text(encoding="utf-8") + "# fixed in round 1\n", encoding="utf-8")
    # 修正の一部として文書にも足す——doc_lines は BASE からの .md の追加行（ファイル全体の行数ではない）
    (run.repo / "README.md").write_text("# demo\n\n追加 1\n追加 2\n", encoding="utf-8")
    r = run.done(inst["id"], {**good, "x_scalars": {"x_arms_fired": 12}})
    check(r.returncode == 0, f"x_ で始まる名前なら通る（その場で足す数値の口。rc={r.returncode}: {r.stderr.strip()[-90:]}）")
    drive(run, "std", stop_at=lambda n: n["round"] == 2)
    sc = run.round_file(1).get("scalars") or {}
    base = run.base
    want = sh(run.repo, "git", "diff", "--numstat", base, run.state()["loop"]["gates_cut"]["rev"], "--", "*.md").stdout.split()
    check(sc.get("x_arms_fired") == 12 and isinstance(sc.get("added_lines"), int) and sc["added_lines"] > 0
          and sc.get("doc_lines") == int(want[0]) == 3,
          f"固定の数値は engine が数え（added_lines・doc_lines=.md の追加行 3）、x_ は p3.fix の値が載る（{sc}）")
    rm(run.tmp)

    # comment-ratio.sh が落ちても周は止めない（scalar はゲートでない）——値を書かず、理由を残す
    run = Run("scalarbroken")
    drive(run, "std", stop_at=lambda n: any(i["node"] == "p3.fix" for i in n["ready"]))
    empty = run.tmp / "no-scripts"
    empty.mkdir()
    f = run.tmp / "sd.json"
    f.write_text(json.dumps(str(empty)), encoding="utf-8")
    r = run.cmd("patch", "--path", "state.inputs.scripts_dir", "--file", str(f), "--reason", "検査: comment-ratio.sh の無い置き場")
    check(r.returncode == 0, f"検査の前提: scripts_dir を差し替えられる（{r.stderr[-120:]}）")
    drive(run, "std", stop_at=lambda n: n["round"] == 2)
    rec = run.record()
    sc = run.round_file(1).get("scalars") or {}
    check(run.state()["round"] == 2 and "added_lines" not in sc and "doc_lines" in sc
          and "comment-ratio.sh" in (rec["process"].get("scalars_unmeasured") or {}).get("1", ""),
          f"測れなかった数値は書かず（0 にしない）、理由を process.scalars_unmeasured に残し、周は進む（{sc} / {rec['process'].get('scalars_unmeasured')}）")
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
          f"1 周目だけ走る節（判定から入る run でない）は carried_over（実際に見た周付き。{r2['materials']['parallel_pr']}）")
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
    head = (run.dir / "report.md").read_text(encoding="utf-8").splitlines()[0]
    check(re.fullmatch(r"graphloops \S+( \([0-9a-f]+\))? / review-loop run " + re.escape(st["run_id"]) + r" / round " + str(st["round"]) + r" / graph [0-9a-f]+", head),
          f"報告の 1 行目に engine が来歴（版・run の番号・周）を刻む——writer の本文に依らない（{head}）")
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


def test_patch_record_prefix_and_delete():
    """記録の手当ての綴り: record. 接頭は接頭なしと同じ場所を指し（入れ子を作らない）、--delete は在る鍵だけを消す。
    接頭をそのまま鍵にしていた頃、record.questions が記録の中に record の入れ子を作り、消す口が無いので
    null で上書きした鍵が記録の最上位に残った（実測 2026-09-26）"""
    print("記録の手当て: record. 接頭は同じ場所・--delete は在る鍵だけ・記録まるごとは受けない")
    run = Run("patchrec")
    run.next()
    f = run.tmp / "v.json"
    f.write_text(json.dumps("手当ての値"), encoding="utf-8")
    r1 = run.cmd("patch", "--path", "record.process.x_note", "--file", str(f), "--reason", "検査: 接頭つき")
    rec = run.record()
    check(r1.returncode == 0 and rec["process"].get("x_note") == "手当ての値" and "record" not in rec,
          f"record. 接頭は接頭なしと同じ場所に書き、記録の中に record の入れ子を作らない（rc={r1.returncode} {r1.stderr[-80:]}）")
    r2 = run.cmd("patch", "--path", "process.x_note", "--delete", "--reason", "検査: 消す")
    st = run.state()
    check(r2.returncode == 0 and "x_note" not in run.record()["process"] and st["patches"][-1].get("op") == "delete",
          f"--delete は在る鍵を消し、痕跡に op=delete を残す（rc={r2.returncode} {r2.stderr[-80:]}）")
    r3 = run.cmd("patch", "--path", "process.x_note", "--delete", "--reason", "検査: 無い鍵")
    r4 = run.cmd("patch", "--path", "record", "--file", str(f), "--reason", "検査: 記録まるごと")
    r5 = run.cmd("patch", "--path", "process.x_note", "--reason", "検査: どちらも無い")
    r6 = [run.cmd("patch", "--path", bad, "--file", str(f), "--reason", "検査: 空の区切り") for bad in ("record.", "record..x", "state.")]
    check(r3.returncode == 1 and "当たらない" in r3.stderr and r4.returncode == 1 and "記録まるごと" in r4.stderr
          and r5.returncode == 1 and "どちらか 1 つ" in r5.stderr and all(r.returncode == 1 and "空の区切り" in r.stderr for r in r6)
          and len(run.state()["patches"]) == 2 and "" not in run.record() and "" not in run.state(),
          f"無い鍵の消し・記録まるごと・書くか消すかの無い手当て・空の区切りの綴りは拒み、痕跡を残さない（{r3.returncode}/{r4.returncode}/{r5.returncode}/{[r.returncode for r in r6]}）")
    rm(run.tmp)


def test_awaiting_origin_guards():
    """人待ちの問いの出どころは、今 awaiting_human の素材だけ——**判定の時点**（判定者が人待ちでない欄を借りる入口）と、
    **素材を書いた時点**（後の工程が人待ちの欄を上書きする入口）の両方で当てる。検証器は周の最後の 1 回しか見ず、
    実走では 5 周で 8 回、回す側が patch で書き戻した。人が実地で確かめるまで決まらない問いは field（出どころを持たない）"""
    print("人待ちの問いの出どころ: 判定の時点と書いた時点で拒み、実地の問いは field で立つ")
    run = Run("awaitorigin", checks=None)   # 任せ先の返答で人待ちの規則を撃つ（engine が組む側は test_engine_run_checks）
    seen = {}
    field = {"key": "Windows の実機で動かしたか", "kind": "field", "status": "held", "reason": "手元にも CI にも Windows の実機が無い（検査用）"}
    wait_ci = {"key": "CI をどこで走らせるか", "kind": "awaiting", "origin": "local_checks", "status": "held", "reason": "手元で CI を走らせられない（検査用）"}

    def hook(run, inst, out):
        if inst["node"] == "p0.local_checks":
            return {"material": M("awaiting_human", reason="CI 専用のジョブで手元では走らない（検査用）")}
        if inst["node"] == "p2.diagnose" and run.state()["round"] == 1:
            r = run.done(inst["id"], {**out, "questions": [field]}, agent_id="judge-1")
            seen["unlisted"] = (r.returncode, r.stderr)
            if r.returncode == 0:
                raise RuntimeError("人待ちの素材を台帳に載せない判定を受け付けた")
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
    rc, err = seen.get("unlisted", (None, ""))
    check(rc == 1 and "素材 'local_checks' が awaiting_human なのに台帳に kind=awaiting で無い" in err,
          f"判定の時点: 人待ちの素材を出どころにする問いを台帳に載せない判定は拒む（rc={rc} {err.strip()[-120:]}）")
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
        settle(run, by[n], t[n])
    nx = run.next()
    by = {i["node"]: i for i in nx["ready"]}
    for n in ("p0.purpose", "p0.parallel_pr", "p0.prior_decisions"):
        settle(run, by[n], t[n])
    nx = run.next()
    by = {i["node"]: i for i in nx["ready"]}
    lr = by["p1.local_review"]
    body = pathlib.Path(lr["prompt_file"]).read_text(encoding="utf-8")
    # 条件 1（正本を 1 か所に）——役が読む本文に正典の綴りが全部在り、かつ本数を焼き込んだ写しではない
    for name in DECLARED_LENSES:
        check(name in body, f"プロンプトに正典の綴りが埋まる: {name}")
    check('"required": false' in body and '"applies_cond": "security_surface_touched"' in body,
          "条件付きのレンズは required と条件の関数の名前で渡る（散文の『（該当時）』ではない）")
    # 当てるかは engine が節を出す時点に評価し、要素と instance に足す（p0.base の申告が全部偽の台本）
    sec = next(e for e in lr["skills"] if e["skill"] == "/security-review")
    check(sec["applies"] is False and "applies_why" in sec and '"applies": false' in body,
          f"申告が偽の周は applies が偽で、プロンプトと instance にその値が載る（{sec}）")
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
    check(by["p0.local_checks"]["mode"] == "engine_run" and "delegate" not in by["p0.local_checks"],
          f"宣言の在るリポジトリでは、走らせるだけの節は engine が走らせる節（mode=engine_run）で出て、任せ先は載らない（{by['p0.local_checks']['mode']}）")
    nodecl = Run("neg-nodecl", checks=None)
    by0 = {i["node"]: i for i in nodecl.next()["ready"]}
    check(by0["p0.local_checks"].get("delegate", {}).get("model") == "sonnet" and "delegate" not in by0["p0.base"]
          and "が無い" in (by0["p0.local_checks"].get("engine_fallback") or ""),
          f"任せ先: graph が delegate を宣言した回す側の節は ready に任せ先が載り、宣言の無い節には載らない（宣言の無いリポジトリの走らせる節は"
          f"理由つきで任せ先に落ちる。{by0['p0.local_checks'].get('delegate')} / {by0['p0.local_checks'].get('engine_fallback')}）")
    rm(nodecl.tmp)
    t = answers(run, "std", 1)
    r = run.done(by["p0.base"]["id"], {**t["p0.base"](None), "base_sha": "deadbeef"})
    check(r.returncode == 1 and "コミットでない" in r.stderr, "実在しない BASE は exit 1")
    for n in ("p0.base", "p0.local_checks", "p0.premises"):
        settle(run, by[n], t[n])
    nx = run.next()
    by = {i["node"]: i for i in nx["ready"]}
    check("p0.prior_decisions" in by and "p1.worktree_before" not in by, "機械の節（作業ツリーの写し）は ready に出ない")
    check(run.record_cli() == run.record(), "loop.py record は record.json の丸写し（直読みと同じ値。CLI の煙テストはここ 1 か所）")
    for n in ("p0.purpose", "p0.parallel_pr", "p0.prior_decisions"):
        settle(run, by[n], t[n])
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
    r = run.done(fx["id"], {**fix, "interactions": [{**fix["interactions"][0], "changes": [c["unit_key"] for c in fix["changes"]]}]})
    check(r.returncode == 1 and "型に合わない" in r.stderr, "面ごとの修正の一覧（changes）は役に書かせない——書けば型で拒む（写しの入口を残さない）")
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
    # 判定者が class_query を持つ単位は coverage を書かなくてよい（engine が判定者の how を補う）。**正しい返答で確かめると
    # 節が done になり後続の腕が撃てない**ので、後ろに在る拒否（wrote_refs の数え）で赤くして、coverage で赤くならないことを見る。
    # 補った値そのものは test_fix_counts_by_engine が post_check を直に呼んで見る
    nocov = {**fix, "wrote_refs": [{"kind": "text", "cite": "検査用に無い字列", "target": "README.md", "where": "src/a.py"}],
             # 省くのは判定者の how が台本の how と同じ単位だけ（もう 1 つの単位の判定者の how は engine が 0 件と数える問い）
             "changes": [{k: v for k, v in fix["changes"][0].items() if k != "coverage"}] + fix["changes"][1:]}
    r = run.done(fx["id"], nocov)
    check(r.returncode == 1 and "の中に無い" in r.stderr and "coverage" not in r.stderr,
          f"判定者が class_query を持つ単位は coverage を省いても coverage では拒まない（赤の理由は wrote_refs だけ。{r.stderr.strip()[-70:]}）")
    # how を書かずに remaining だけを書く返答も型で拒まない（coverage の中に必須の欄を残すと、残した理由を書く周に how の写しが戻る）
    remonly = {**nocov, "changes": [{**nocov["changes"][0], "coverage": {"remaining": "検査用に残した理由を書いた"}}] + nocov["changes"][1:]}
    r = run.done(fx["id"], remonly)
    check(r.returncode == 1 and "の中に無い" in r.stderr and "coverage" not in r.stderr,
          f"coverage に remaining だけを書いた返答も coverage では拒まない（赤の理由は wrote_refs だけ。{r.stderr.strip()[-70:]}）")
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
    # symlink のディレクトリを経由するリンクは実体で引いて届く（書かれた綴りのまま照合するのは symlink でない部品だけ）
    try:
        (tmp / "lnk").symlink_to("docs", target_is_directory=True)
        via_symlink = True
    except OSError:   # Windows は既定で symlink を作る権限を持たない
        via_symlink = False
    (tmp / "viasym.md").write_text("[symlink 経由](lnk/a.md#数える問いf1)\n", encoding="utf-8")
    subprocess.run(["git", "add", "-N", "viasym.md"], cwd=tmp, capture_output=True)
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
    if via_symlink:
        check("viasym.md" not in joined, f"リンク: symlink のディレクトリを経由するリンクは実体で引いて届く（{errs}）")
    else:
        skip("リンク: symlink のディレクトリを経由するリンクは実体で引いて届く", "symlink", "この環境では symlink を作れない（Windows は既定で権限を持たない）")
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
    # **判定者の how は写させない**: coverage を省いても、remaining だけを書いても、判定者の how が補われて out に残る
    # （out は post_check の後に保存され、process.fixes と R1 が読む値は今までと同じ how になる）
    for cov in (None, {"remaining": "検査用に残した理由を書いた"}):
        ch = {k: v for k, v in change.items() if k != "coverage"}
        if cov is not None:
            ch["coverage"] = dict(cov)
        got = run(ch)
        filled = ch.get("coverage") or {}
        check(got is None and filled.get("how") == how and filled.get("remaining") == (cov or {}).get("remaining"),
              f"修正の件数: coverage.how を書かなければ判定者の how を補って返答に書き戻す（{sorted(cov or {})}。{got} / {filled}）")
    b.record["process"]["diagnosis"]["units"] = [unit]   # 判定者が class_query を持たない単位では補う物が無い
    got = run({k: v for k, v in change.items() if k != "coverage"})
    check(got and "class_query が無い単位なのに coverage.how" in got,
          f"修正の件数: 判定者の class_query が無い単位で how を省けば拒む（{(got or '通った')[:80]}）")
    b.record["process"]["diagnosis"]["units"] = [{**unit, "class_query": {"how": how, "counts": "defects", "total": 2}}]
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
    broken(lambda b: b["nodes"]["p3.fix"]["schema"]["properties"]["x_scalars"].__setitem__("patternProperties", {"^x_[a-z0-9_+$": {"type": "number"}}),
           "正規表現", "graphcheck: 壊れた patternProperties の正規表現")
    # 数える問いの型は engine の 1 つの定義を $ref で引く——写しは無いので、崩れうるのは参照の側だけ
    broken(lambda b: cq(b, "p2.rejudge").__setitem__("how", {"$ref": "engine#/count_hwo"}), "が引けない", "graphcheck: 引けない $ref")
    broken(lambda b: b["nodes"]["p4.ci"]["delegate"].__setitem__("model", "hiku"), "delegate は", "graphcheck: 任せ先のモデルの綴り違い")
    broken(lambda b: b["nodes"]["p2.diagnose"].__setitem__("delegate", {"model": "haiku", "why": "検査用"}), "回す側の節（runners）にだけ",
           "graphcheck: 役の節に任せ先は書けない")
    broken(lambda b: b["nodes"]["p1.local_review"].__setitem__("delegate", {"model": "sonnet", "why": "検査用"}), "skills を持つ節に delegate は書けない",
           "graphcheck: skill を呼ぶ節を任せ先に渡せない（入れ子の委任は完了の知らせが届かない）")
    broken(lambda b: b["launch"].pop("delegate"), "launch.delegate.argv が無い", "graphcheck: 任せ先を縛って起こす語が無い graph は落ちる")
    broken(lambda b: b["nodes"]["p3.delta_gates"]["delegate"].pop("result_to"), "delegate.result_to",
           "graphcheck: 背景の任せ先が返答の置き場を名指ししない")
    broken(lambda b: b["launch"]["delegate"]["argv"].append("{sandbox_json}"), "を engine は埋められない",
           "graphcheck: 任せ先の起動の語の知らない穴")
    broken(lambda b: b["nodes"]["p3.delta_gates"]["delegate"].__setitem__("background", "yes"), "delegate.background は真偽",
           "graphcheck: 背景の任せ先の旗が真偽でない")
    broken(lambda b: b["nodes"]["p4.ci"]["deps"].append("p3.delta_gates"), "背景の節（delegate.background）を",
           "graphcheck: 背景の節（受領しか返さない線）を締めの節が待つ")
    # engine が埋める node の欄は skills だけ——他の欄の穴は next で埋められずに止まる
    (tmp / "prompts" / "review-loop" / "x-node-hole.md").write_text("{{node.deadline_at}}\n", encoding="utf-8")

    def node_hole(b):
        b["nodes"]["p4.final_gates"]["prompt_file"] = "../prompts/review-loop/x-node-hole.md"
        b["nodes"]["p4.final_gates"]["reads"] = ["node.deadline_at"]
    broken(node_hole, "engine が埋めない", "graphcheck: engine が埋めない node の欄の穴")
    broken(lambda b: cq(b, "p2.rejudge").__setitem__("how", {"$ref": "engine#/count_how", "type": "string"}), "他の語が並んでいる",
           "graphcheck: 定義を上書きする $ref")
    broken(lambda b: b["$defs"].__setitem__("loop", {"type": "object", "properties": {"x": {"$ref": "#/$defs/loop"}}})
           or b["nodes"]["p4.ci"]["schema"]["properties"].__setitem__("x", {"$ref": "#/$defs/loop"}), "自分を引いている",
           "graphcheck: 自分を引く $ref（展開が止まらない）")
    # 語の検査は patternProperties の値の schema の中まで降りる（走査は engine の walk_schema 1 本）
    broken(lambda b: b["nodes"]["p3.fix"]["schema"]["properties"]["x_scalars"]["patternProperties"]["^x_[a-z0-9_]+$"].__setitem__("minimun", 0),
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
    # record.<欄> の穴は条件の読みと同じく記録を書く宣言で照らす（必須の穴・省略可の穴の 1 本ずつ。reads も同じ綴りに揃え、
    # reads の照合でなく記録の宣言の照らしで落ちることを見る）
    for nid, good, bad in (("p0.parallel_pr", "{{record.base}}", "{{record.bsae}}"),
                           ("p4.ci", "{{?record.process.human_answers}}", "{{?record.process.human_answerz}}")):
        pp = tmp / "prompts" / "review-loop" / f"{nid}.md"
        porig = pp.read_text(encoding="utf-8")
        pp.write_text(porig.replace(good, bad), encoding="utf-8")
        field = bad.strip("{}?")
        broken(lambda b: b["nodes"][nid].__setitem__("reads", [field if x == good.strip("{}?") else x for x in b["nodes"][nid]["reads"]]),
               f"読む欄 '{field}' を書く宣言が無い", f"graphcheck: プロンプトの穴 {bad} の綴り違い")
        check(porig.count(good) == 1, f"graphcheck: 撃った穴 {good} は写しの {nid} に 1 つ在った")
        pp.write_text(porig, encoding="utf-8")
    # rules が読めない回は record. の穴を照らさない（init_record を引けず、正しい穴まで全部が偽の NG になる）
    rp.write_text(orig + "\nraise RuntimeError('読めない rules')\n", encoding="utf-8")
    pth.write_text(json.dumps(g, ensure_ascii=False), encoding="utf-8")
    r = subprocess.run([PY, str(gc), str(pth), str(VALIDATOR)], capture_output=True, text=True, encoding="utf-8", timeout=600)
    check(r.returncode == 1 and "読めない rules" in r.stdout and "書く宣言が無い" not in r.stdout,
          f"graphcheck: rules が読めない回は record. の穴を偽の NG で埋めない（{r.stdout.count('書く宣言が無い')} 件）")
    rp.write_text(orig, encoding="utf-8")
    rm(tmp)


def test_old_expression_graph_board():
    """条件を式で書いていた版の graph を指す盤面は、旧い形式だと言い、開く engine を名指して止まる（盤面は書かない）"""
    print("旧い形式の盤面: 式の条件の graph を指す盤面を開くと、形式と開く engine を言って止まり、盤面を 1 バイトも書かない")
    run = Run("oldgraph")
    st = run.dir / "state.json"
    orig = json.loads(st.read_text(encoding="utf-8"))
    g = json.loads(pathlib.Path(orig["graph"]).read_text(encoding="utf-8"))
    g["nodes"]["p1.gate_efficacy"]["cond"] = {"path": "round", "op": "eq", "value": 1}
    for with_engine in (False, True):
        plug = run.tmp / f"old-plugin-{with_engine}"
        (plug / "graphs").mkdir(parents=True)
        if with_engine:
            (plug / "scripts").mkdir()
            (plug / "scripts" / "loop.py").write_text("# 旧い engine の置き場\n", encoding="utf-8")
        gp = plug / "graphs" / "review-loop.json"
        gp.write_text(json.dumps(g, ensure_ascii=False), encoding="utf-8")
        st.write_text(json.dumps({**orig, "graph": str(gp)}, ensure_ascii=False, indent=1), encoding="utf-8")
        before = {p.name: p.read_bytes() for p in (st, run.dir / "record.json")}
        r = run.cmd("next")
        # engine は置き場を実体に解いて言う（Windows の一時の置き場は 8.3 の短い綴り RUNNER~1 で渡り、解くと長い綴りになる）
        want = ({str(plug / "scripts" / "loop.py"), str((plug / "scripts" / "loop.py").resolve())} if with_engine
                else {"この graph を作った版の engine"})
        check(r.returncode == 2 and "条件を式で書いていた版" in r.stderr and "p1.gate_efficacy" in r.stderr and any(w in r.stderr for w in want),
              f"旧い形式の盤面（置き場に engine が{'在る' if with_engine else '無い'}）: 開く engine を言って止まる（{r.stderr.strip()[-120:]}）")
        check(before == {p.name: p.read_bytes() for p in (st, run.dir / "record.json")}, "旧い形式の盤面: state.json と record.json を書かない")


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
    run = Run("noawait", checks=None)
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
        skip("開けない指し先は『数えられない』で拒む", "read-permission", "root か Windows では権限で読みを止められない")
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
        skip("FIFO に置き換わった指し先は開かずに拒む", "fifo", "この OS には FIFO（os.mkfifo）が無い")
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
    run = Run("noci", unattended=True, checks=None)   # 宣言の無いリポジトリ（任せ先が not_applicable を返す）
    last = drive(run, "noci")
    proc = run.record()["process"]
    asked = [a for h in proc.get("human_items", []) for a in (h.get("asked") or [])]
    check(last["status"] == "stopped" and any("local_checks" in a for a in asked), f"無人: converged でなく stopped、要人間判断に CI 未確認が載る（{last['status']}: {asked[:1]}）")
    check(proc.get("outcome") != "converged", f"記録の outcome が converged でない（{proc.get('outcome')}）")
    rm(run.tmp)
    run = Run("noci-attended", checks=None)
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
    mod = _fresh_rules("gl_rv2")
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
                               encoding="utf-8", errors="replace", env={**os.environ, **mod.SNAPSHOT_FALLBACK_IDENT})
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
        check(all(rev in s and str(run.repo.resolve()) in s for s in seen),
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
    mod = _fresh_rules("gl_unvetted")
    check("purpose_review_unvetted" in mod.purpose_review_due.reads or set(mod.purpose_review_unvetted.reads) <= set(mod.purpose_review_due.reads),
          "目的監査の条件（purpose_review_due）がこの部品の読む欄を宣言している")

    def b(findings, verdict="狭めている"):
        pr = {"verdict": verdict}
        if findings is not None:
            pr["findings"] = findings
        return {"record": {"process": {"purpose_review": pr}}}

    f = lambda ctx: cond_call(mod.purpose_review_unvetted, ctx)[0]
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

    mod = _fresh_rules("gl_freeze_real")
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
    mod = _fresh_rules("gl_freeze_ign")
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
    mod = _fresh_rules("gl_rv4")
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
    mod = _fresh_rules("gl_rv3")
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
    run = Run("carryable", unattended=True, checks=None)
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
        settle(run, by[n], t[n])
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
        ("inputs-undeclared-bare", lambda b: b["inputs"].pop("cwd", None),
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
                # 判定役の instance が出ていても、起こす前（launch していない・返答の置き場が空）の add は受け、プロンプトを描き直す
                f4 = run.tmp / "req4.json"
                f4.write_text(json.dumps([{"where": "src/a.py:f", "text": "起こす前の依頼（検査用の目印 REQ-4d1）"}], ensure_ascii=False), encoding="utf-8")
                late["before_launch"] = run.cmd("add", "--file", str(f4), "--reason", "判定役を起こす前（検査用）")
            if rnd == 1 and "after_judge" not in late and "p2.diagnose" in run.state()["rounds"][0]["done"]:
                # 判定役が済んだ後の add は拒む（その周の判定に届かない依頼を黙って積まない）
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
        bl = late.get("before_launch")
        st1 = run.state()["rounds"][0]["instances"]["p2.diagnose"]
        check(bl is not None and bl.returncode == 0 and "描き直した" in bl.stdout and "REQ-4d1" in prompt
              and st1["attempts"] == 2 and ".a2." in st1["out_path"] and "add で積んだ物" in st1["attempt_log"][-1]["reason"],
              f"入口: 判定役の instance が出ていても起こす前の add は受け、新しい試行として描き直したプロンプトに依頼が載る"
              f"（{(bl.stdout[-200:] + bl.stderr[-200:]) if bl else '呼ばれていない'}）（{scenario}）")
        ab = late.get("after_judge")
        check(ab is not None and ab.returncode == 1 and "既に起きている" in ab.stderr and "新しい run" in ab.stderr,
              f"入口: 判定役が起きた後の add は拒み、次の周が来ないときの行き先も言う（{(ab.stderr[-200:] if ab else '呼ばれていない')}）（{scenario}）")
        proc = run.record()["process"]
        check(proc.get("request_entry") == {"origin": "利用者の依頼（検査用）"} and not proc.get("procedure_findings"),
              f"入口: 印は 1 周目の P1 前の最初の add の出どころで立ち、手順トレースの欄を借りない（{proc.get('request_entry')}）（{scenario}）")
        batches = proc.get("request_history", []) + proc.get("request_findings", [])
        check(sorted((x["round"], x["origin"]) for x in batches) == sorted(
                  [(1, "利用者の依頼（検査用）"), (1, "2 回目の依頼（検査用）"), (1, "判定役を起こす前（検査用）")]
              + ([(2, "途中の周の依頼（検査用）")] if "r2" in late and late["r2"].returncode == 0 else [])),
              f"入口: どの周のバッチも周と出どころつきで記録に残る（{[(x['round'], x['origin']) for x in batches]}）（{scenario}）")
        # P0 の範囲: 差分が空の入口の周は、依頼の where を範囲として P0 の 2 節に渡す（差分が空だから対象外、と返させない）
        pd = (run.dir / "prompts" / "r1" / "p0.prior_decisions.md").read_text(encoding="utf-8")
        pp = (run.dir / "prompts" / "r1" / "p0.parallel_pr.md").read_text(encoding="utf-8")
        check(all('"src/a.py:f"' in x and '"src/b.py:g"' in x for x in (pd, pp)),
              f"入口: 1 周目の P0 の 2 節（先行議論・並行 PR）に、依頼の where が範囲として届く（{scenario}）")
        pr_rounds = sorted(n for n in seen if "p0.parallel_pr" in seen[n])
        if scenario == "std":
            check("p1.local_review" in seen[2], f"入口: 修正が入った次の周は P1 が修正差分を見る（2 周目に出た {sorted(seen[2] & roles)}）")
            check(pr_rounds == [1, 2], f"入口: 並行 PR の交差は 1 周目と、最初に修正が入った次の周に 1 度だけ見直す（走った周 {pr_rounds}）")
            pp2 = (run.dir / "prompts" / "r2" / "p0.parallel_pr.md").read_text(encoding="utf-8")
            check("依頼が指す場所（[]）" in pp2 and '"src/a.py:f"' not in pp2, "入口: 修正が入った後の周は依頼の where を範囲に足さない（差分が範囲）")
            r2 = late.get("r2")
            check(r2 is not None and r2.returncode == 0, f"入口: 2 周目の判定の前の add は受ける（{(r2.stderr[-200:] if r2 else '呼ばれていない')}）")
            p2 = (run.dir / "prompts" / "r2" / "p2.diagnose.md").read_text(encoding="utf-8")
            check("REQ-r2c" in p2 and "途中の周の依頼（検査用）" in p2 and "REQ-7f3" not in p2,
                  "入口: 2 周目の判定にはその周の依頼だけが届き、前の周の依頼は履歴に移る")
        else:
            check(all(not (seen[n] & roles) for n in seen), "入口: 修正 0 行の run は P1 を起こさないまま周を重ねる")
            check(pr_rounds == [1], f"入口: 修正が入らない run は並行 PR を 1 周目にだけ見る（走った周 {pr_rounds}）")
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
    # 入口で外れたか＝入口の周で、今は偽で、入口の印を外した文脈（重ね書き）なら真。同じ関数を 2 回評価する
    def fake(entry, now, off):
        return types.SimpleNamespace(cond=lambda c, overlay=None: ((entry if c == "request_entry" else (off if overlay else now)), "検査"))
    check(not rules._entry_skipped(fake(True, True, True), {"cond": "after_first_round"}),
          "入口: 入口の項を持たない節は、条件が真でも入口で外れたと数えない")
    check(rules._entry_skipped(fake(True, False, True), {"cond": "provenance_due"}),
          "入口: 入口の周に偽で、入口の印を外すと真になる節は、入口で外れたと数える")
    check(not rules._entry_skipped(fake(True, False, False), {"cond": "provenance_due"}),
          "入口: 入口の印を外しても偽なら、入口で外れたと数えない（通常の理由のまま）")
    check(not rules._entry_skipped(fake(False, False, True), {"cond": "provenance_due"}) and not rules._entry_skipped(fake(True, False, True), {}),
          "入口: 入口の周でない・条件を持たない節は、入口で外れたと数えない")
    # request_entry は印だけを見る——依頼の一覧が在っても印が無ければ偽（空差分の柵も P1 の cond も同じ 1 本を読む）
    batch = [{"round": 2, "origin": "途中", "findings": req}]
    ent = lambda proc, ls={}: cond_call(rules.request_entry, {"record": {"process": proc}, "loop": ls})[0]
    check(not ent({"request_findings": batch}), "入口: 依頼の一覧だけでは入口にならない（途中の周の依頼で空差分の柵と P1 を外さない）")
    check(ent({"request_entry": {"origin": "人"}}) and not ent({"request_entry": {"origin": "人"}}, {"request_fixed_at": 1}),
          "入口: 印が在れば修正が入るまで真、修正が入った後は偽")
    wh = lambda proc, ls={}: rules.request_wheres(types.SimpleNamespace(
        record={"process": proc}, loop_state=ls,
        cond=lambda c: cond_call(rules.CONDS[c], {"record": {"process": proc}, "loop": ls})))
    check(wh({"request_findings": batch, "request_entry": {"origin": "人"}}) == ["src/a.py:f"]
          and wh({"request_findings": batch}) == [] and wh({"request_findings": batch, "request_entry": {"origin": "人"}}, {"request_fixed_at": 1}) == [],
          "入口: 依頼の where を P0 の範囲にするのは入口の周だけ（印の無い run・修正が入った後の周は差分が範囲）")
    fix1 = lambda proc, ls, rnd: cond_call(rules.entry_first_fix, {"record": {"process": proc}, "loop": ls, "round": rnd})[0]
    check(fix1({"request_entry": {"origin": "人"}}, {"request_fixed_at": 1}, 2)
          and not fix1({"request_entry": {"origin": "人"}}, {"request_fixed_at": 1}, 3)
          and not fix1({"request_entry": {"origin": "人"}}, {}, 2) and not fix1({}, {"request_fixed_at": 1}, 2),
          "入口: 最初に修正が入った次の周だけ真（その後の周・修正の無い run・印の無い run は偽）")
    # P0 の節が出た後の add: 起こす前の節は描き直して依頼の where を範囲に入れ、起きた節は入らないと言う（黙って範囲外のまま clean を返させない）
    run = Run("entry-p0late")
    add_req(run)
    nx = drive(run, "std", stop_at=lambda nx: any(i["node"] == "p0.prior_decisions" for i in nx["ready"]))
    f = run.tmp / "req-late.json"
    f.write_text(json.dumps([{"where": "src/b.py:g", "text": "遅い依頼（検査用）"}], ensure_ascii=False), encoding="utf-8")
    r = run.cmd("add", "--file", str(f), "--reason", "P0 の後の依頼")
    pd = (run.dir / "prompts" / "r1" / "p0.prior_decisions.md").read_text(encoding="utf-8")
    check(r.returncode == 0 and "p0.prior_decisions を試行 2 として描き直した" in r.stdout and '"src/b.py:g"' in pd,
          f"入口: 起こす前の P0 の節は描き直し、遅い依頼の where が範囲に入る（{r.stdout[-200:]}{r.stderr[-160:]}）")
    # 起きた節（ここでは返答の置き場にファイルが在る）は描き直さず、依頼が入っていないと言う
    inst = run.state()["rounds"][0]["instances"]["p0.prior_decisions"]
    pathlib.Path(inst["out_path"]).write_text("{}", encoding="utf-8")
    f.write_text(json.dumps([{"where": "src/c.py:h", "text": "もっと遅い依頼（検査用）"}], ensure_ascii=False), encoding="utf-8")
    r = run.cmd("add", "--file", str(f), "--reason", "起きた後の依頼")
    check(r.returncode == 0 and "p0.prior_decisions" in r.stdout and "入っていない" in r.stdout
          and run.state()["rounds"][0]["instances"]["p0.prior_decisions"]["attempts"] == 2,
          f"入口: 起きた後の P0 の節は描き直さず、その範囲に依頼が入っていないと言う（{r.stdout[-200:]}{r.stderr[-160:]}）")
    rm(run.tmp)
    # 判定役を起こした後（launched_at が在る）・返答の置き場にファイルが在る間は、instance が待ちでも add を拒む
    for how in ("launched", "out_file"):
        run = Run(f"entry-started-{how}")
        add_req(run)
        drive(run, "std", stop_at=lambda nx: any(i["node"] == "p2.diagnose" for i in nx["ready"]))
        sp = run.dir / "state.json"
        st = json.loads(sp.read_text(encoding="utf-8"))
        inst = st["rounds"][0]["instances"]["p2.diagnose"]
        if how == "launched":
            inst.update(launched_at="2026-09-25T00:00:00+09:00", launch_state="running")
            sp.write_text(json.dumps(st, ensure_ascii=False), encoding="utf-8")
        else:
            pathlib.Path(inst["out_path"]).write_text("{}", encoding="utf-8")
        r = run.cmd("add", "--file", str(run.tmp / "req.json"), "--reason", "起きた後")
        check(r.returncode == 1 and "既に起きている" in r.stderr,
              f"入口: 判定役が起きた後（{how}）の add は、instance が待ちのままでも拒む（{r.stdout[-120:]}{r.stderr[-160:]}）")
        rm(run.tmp)
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


def test_stop_midround():
    """**人が途中で止める**（loop.py stop）。人に聞いていない時点でも止められ、止めた理由が記録に残り、報告の節だけが走って
    報告まで届く。止めた周の記録は、走らなかった R と素材を止めた事実（not_run と理由）で書く。宣言の無い graph は報告を出さずに止まる"""
    print("途中で止める: 修正案の前で止めて報告まで届く・理由が記録と周の記録に残る・宣言の無い graph は halted")
    run = Run("stop-mid")
    drive(run, "std", stop_at=lambda nx: any(i["node"] == "p2.fix_plan" for i in nx["ready"]))
    r = run.cmd("stop", "--reason", " ")
    check(r.returncode == 1 and "理由が空" in r.stderr, f"止める: 理由の空は拒む（{r.stderr[-120:]}）")
    r = run.cmd("stop", "--reason", "検査: 修正案の前で止める")
    got = json.loads(r.stdout) if r.returncode == 0 else {}
    st = run.state()
    check(r.returncode == 0 and got["stopped"]["report"] is True and st["status"] == "stopped" and "halted" not in st,
          f"止める: 宣言の在る graph では halted にせず報告へ進む（{r.stdout[-200:]}{r.stderr[-200:]}）")
    rd = st["rounds"][-1]
    check("p2.fix_plan" in rd["stopped"] and rd["instances"]["p2.fix_plan"]["status"] == "stopped" and "p2.fix_plan" not in rd["skipped"],
          f"止める: 待ちの節は止めた印（省いた印と別）になる（{sorted(rd['stopped'])[:5]}）")
    rf = run.round_file(1)
    check(all(rf["reviews"][k]["status"] == "not_run" and "人が止めた" in rf["reviews"][k]["reason"] for k in ("R1", "R2", "R3", "R4"))
          and rf["materials"]["fix_closure"]["status"] == "not_run" and "人が止めた" in rf["materials"]["fix_closure"]["reason"],
          f"止める: 止めた周の記録は、走らなかった R と素材を止めた事実で書く（{ {k: v['status'] for k, v in rf['reviews'].items()} }）")
    check(rf["units"] and run.record()["process"]["halted"]["reason"] == "検査: 修正案の前で止める",
          "止める: 止めた時点で記録に理由が入る（報告の節が読む）")
    f = run.tmp / "late.json"
    f.write_text("{}", encoding="utf-8")
    r = run.cmd("done", "--node", "p2.fix_plan", "--output", str(f))
    check(r.returncode == 1 and "stopped" in r.stderr, f"止める: 止めた節の返答は受け付けない（{r.stderr[-120:]}）")
    r = run.cmd("stop", "--reason", "二度目")
    check(r.returncode == 1 and "止める物が無い" in r.stderr, f"止める: 止まった run は二度止めない（{r.stderr[-120:]}）")
    nx = run.next()
    check([i["node"] for i in nx["ready"]] == ["report.human_items"], f"止める: 次の next は報告の節だけを出す（{[i['node'] for i in nx['ready']]}）")
    last = drive(run, "std")
    proc = run.record()["process"]
    check(last["status"] == "stopped" and (run.dir / "report.md").is_file() and proc["stop_reason"] == "stop" and proc["outcome"] == "stopped"
          and any(x["node"] == "p2.fix_plan" for x in proc["stopped_nodes"]) and not any(x["node"] == "p2.fix_plan" for x in proc["skipped"]),
          f"止める: 報告まで届き、仕上げた記録に止めた口と止めた節が残る（{proc.get('stop_reason')}・{proc.get('outcome')}）")
    rm(run.tmp)

    run = Run("stop-stale")
    drive(run, "std", stop_at=lambda nx: any(i["node"] == "p2.fix_plan" for i in nx["ready"]))
    (run.dir / "rounds").mkdir(exist_ok=True)
    (run.dir / "rounds" / "round-1.json").write_text('{"stale": true}', encoding="utf-8")
    r = run.cmd("stop", "--reason", "検査: 負けた試行の残したファイルの上で止める")
    rf, rec = run.round_file(1), run.record()
    check(r.returncode == 0 and "stale" not in rf and rf["reviews"] == rec["reviews"]
          and all(rec["reviews"][k]["status"] == "not_run" for k in ("R1", "R2", "R3", "R4")),
          f"止める: 残ったファイルを済んだと読まず、盤面から周の記録を組み直す（{r.stderr[-160:]}{sorted(rf)[:4]}）")
    rm(run.tmp)

    # 2 周目の判定より前に止める: 周の頭で空にした台帳と単位を前の周の姿に戻す（報告は record を読む）。周の記録は前の周まで
    run = Run("stop-r2")
    drive(run, "std", stop_at=lambda nx: nx["round"] == 2)
    prev = run.round_file(1)
    r = run.cmd("stop", "--reason", "検査: 2 周目の頭で止める")
    rec = run.record()
    check(r.returncode == 0 and rec["units"] == prev["units"] and rec["questions"] == prev["questions"]
          and not (run.dir / "rounds" / "round-2.json").is_file(),
          f"止める: 2 周目の判定より前なら前の周の単位と台帳を報告に残す（{r.stderr[-160:]}）")
    rm(run.tmp)

    # 人に聞いている最中に止める: 答えないまま外した問いを記録に残す（報告の節が読む）
    run = Run("stop-ask")
    last = drive(run, "premise")
    r = run.cmd("stop", "--reason", "検査: 人に聞いている最中に止める")
    proc = run.record()["process"]
    un = (proc.get("halted") or {}).get("unanswered") or {}
    hi = [h for h in proc.get("human_items") or [] if "答えないまま人が止めた" in (h.get("note") or "") and h.get("answer") is None]
    check(last["status"] == "awaiting_human" and r.returncode == 0 and un.get("question") and un.get("node") == last["ask"].get("node")
          and "pending_human" not in run.state() and len(hi) == 1,
          f"止める: 人に聞いている最中なら、答えないまま外した問いを記録（halted と要人間判断の欄）に残す"
          f"（{r.stderr[-160:]} {sorted(un)} 要人間判断 {len(hi)} 件）")
    rm(run.tmp)

    # 宣言の無い graph（init の版が古い run）: 報告を出さずに止め、そう言う
    _td, gtmp = parallel.workspace("gl-review-nostop-")
    for sub in ("prompts", "rules", "graphs"):
        shutil.copytree(PLUGIN / sub, gtmp / sub)
    gp = gtmp / "graphs" / "review-loop.json"
    g = json.loads(gp.read_text(encoding="utf-8"))
    g.pop("stop")
    gp.write_text(json.dumps(g, ensure_ascii=False), encoding="utf-8")
    run = Run("stop-nodecl", graph=gp)
    drive(run, "std", stop_at=lambda nx: any(i["node"] == "p2.fix_plan" for i in nx["ready"]))
    r = run.cmd("stop", "--reason", "検査: 宣言の無い graph")
    nx = run.next()
    check(r.returncode == 0 and "報告の節は出ない" in r.stdout and nx["halted"]["by"] == "stop" and not nx["ready"],
          f"止める: 宣言の無い graph は halted（by=stop）で後の節を出さない（{r.stdout[-160:]}）")
    r = run.cmd("stop", "--reason", "検査: 止まった run をもう一度止める")
    check(r.returncode == 1 and "もう止まっている" in r.stderr, f"止める: halted の run は『もう止まっている』で拒む（{r.stderr[-120:]}）")
    rm(run.tmp)


def test_stop_after_round():
    """**N 周目で止める**（init --stop-after-round N）。周の締め（記録・検証器・収束の判定）までは済ませ、次の周を開かない。
    止めたことは盤面（status・halted）と status の出力に出る。人の答えで周を開く口（answer continue）でも同じく止まる"""
    print("N 周で止める: 1 周目の締めの後で止まり、2 周目の節を 1 つも出さない・answer continue の口でも止まる")
    run = Run("stop1", init_args=["--stop-after-round", "1"])
    check(run.init.returncode == 0, f"init が --stop-after-round を受ける（{run.init.stderr[-200:]}）")
    last = drive(run, "std")
    st = run.state()
    check(last["status"] == "stopped" and (last.get("halted") or {}).get("by") == "stop_after_round" and not last["ready"],
          f"1 周目の締めの後の next が stopped と halted（by=stop_after_round）を返す（{last.get('status')}・{last.get('halted')}）")
    check(st["round"] == 1 and len(st["rounds"]) == 1 and "converge" in st["rounds"][0]["done"] and (run.dir / "rounds" / "round-1.json").is_file(),
          f"周の締め（周の記録・converge）は済み、2 周目は開いていない（round {st['round']}・周 {len(st['rounds'])}）")
    nx = run.next()
    check(nx["status"] == "stopped" and not nx["ready"] and nx["halted"]["by"] == "stop_after_round" and "stop_after_round" in nx["note"],
          f"止めた後の next は節を出さず、止めた口を言う（{nx.get('note')}）")
    s = json.loads(run.cmd("status").stdout)
    check(s["halted"]["by"] == "stop_after_round" and s["stop_after_round"] == 1 and s["status"] == "stopped",
          f"status に halted と stop_after_round が出る（{s.get('halted')}・{s.get('stop_after_round')}）")
    run.cmd("finalize")
    proc = run.record()["process"]
    check(proc.get("outcome") == "stopped" and proc.get("stop_reason") == "stop_after_round",
          f"仕上げた記録に止めた理由が残る（{proc.get('outcome')}・{proc.get('stop_reason')}）")
    halts = [json.loads(x) for x in (run.dir / "trace.jsonl").read_text(encoding="utf-8").splitlines() if '"halted"' in x]
    check([(x.get("op"), x.get("by"), x.get("round")) for x in halts] == [("halted", "stop_after_round", 1)],
          f"止めたことは trace にも 1 行残る（{halts}）")
    rm(run.tmp)
    # N より前の周は止めずに開く（3 周で収束する筋書きを 2 周目の締めの後で止める）
    run = Run("stop2", init_args=["--stop-after-round", "2"])
    last = drive(run, "std")
    st = run.state()
    check(last["status"] == "stopped" and st["halted"]["round"] == 2 and len(st["rounds"]) == 2,
          f"--stop-after-round 2 は 1 周目の後は次の周を開き、2 周目の締めの後で止まる（周 {len(st['rounds'])}・{st.get('halted')}）")
    rm(run.tmp)
    # 人に聞く番の continue（周を開くもう 1 つの口）でも止まる
    run = Run("stop1-answer", init_args=["--stop-after-round", "1"])
    last = drive(run, "premise")
    r = run.cmd("answer", "--text", "continue", "--note", "続けて（検査用）")
    st = run.state()
    check(last["status"] == "awaiting_human" and r.returncode == 0 and "halted" in r.stdout and st["status"] == "stopped"
          and st["halted"]["by"] == "stop_after_round" and len(st["rounds"]) == 1,
          f"answer continue でも次の周を開かずに止まる（{r.stdout[-160:]}{r.stderr[-160:]}・周 {len(st['rounds'])}）")
    rm(run.tmp)
    # 0 以下は置き場を作る前に拒む
    run = Run("stop0", init_args=["--stop-after-round", "0"])
    check(run.init.returncode == 2 and "1 以上" in run.init.stderr and not run.dir.exists(),
          f"--stop-after-round 0 は init が拒み、盤面を残さない（{run.init.stderr[-160:]}）")
    rm(run.tmp)


def test_gates_merge():
    """**変異の検算を合流でまとめる**（init --input gates=merge）。線と最後の関門は理由つきの条件外で閉じ、線は台帳に載らず、
    収束する筋書きでも converge は収束を名乗らずに止まる（stop_reason=gates_deferred）。知らない値は盤面を作る前に拒む"""
    print("合流でまとめる: 線と関門が理由つきの条件外・線の台帳が空・収束の手前で gates_deferred で止まる")
    run = Run("gmerge", inputs=["gates=merge"])
    check(run.init.returncode == 0, f"init が gates=merge を受ける（{run.init.stderr[-200:]}）")
    seen = set()

    def hook(run_, inst, out):
        seen.add(inst["node"])
        return None
    last = drive(run, "std", hook=hook)
    st = run.state()
    proc = run.record()["process"]
    check(last["status"] == "stopped" and proc.get("stop_reason") == "gates_deferred" and proc.get("outcome") == "stopped",
          f"収束する筋書きでも converge は収束を名乗らず gates_deferred で止まる（{last['status']}・{proc.get('stop_reason')}）")
    check(not {"p3.delta_gates", "p4.final_gates"} & seen and not st["loop"].get("lanes") and st["loop"].get("gates") == "merge",
          f"線と関門の instance は出ず、線の台帳は空（出た {sorted({'p3.delta_gates', 'p4.final_gates'} & seen)}・lanes {st['loop'].get('lanes')}）")
    na = [r["na"] for r in st["rounds"]]
    check(all("gates=merge" in n.get("p3.delta_gates", "") for n in na) and "gates=merge" in na[-1].get("p4.final_gates", ""),
          f"線と関門の na は合流でまとめる理由を運ぶ（{[n.get('p3.delta_gates', '')[:60] for n in na]}・{na[-1].get('p4.final_gates', '')[:60]}）")
    hi = next((run.dir / "prompts").glob("r*/report.human_items.md")).read_text(encoding="utf-8")
    check((run.dir / "report.md").is_file() and "gates_deferred" in hi and "gates=merge 無しの run で回し" in hi,
          "止まった run も報告まで届き、報告の冒頭の指示書が止めた理由と残る義務（合流した版で関門を撃つ）を渡す")
    rm(run.tmp)
    run = Run("gmerge-gates", inputs=["gates=merge"])
    seen = set()
    last = drive(run, "gates", hook=hook)
    proc = run.record()["process"]
    ge = run.record()["materials"].get("gate_efficacy") or {}
    check("p1.gate_efficacy" not in seen and last["status"] == "stopped" and proc.get("stop_reason") == "gates_deferred",
          f"ゲートを触った差分でも p1.gate_efficacy の instance は出ず、gates_deferred で止まる（{last['status']}・{proc.get('stop_reason')}）")
    check(ge.get("status") == "not_applicable" and "gates=merge" in ge.get("reason", "") and "P1 のゲートの検算" in ge.get("reason", ""),
          f"撃たなかった素材は合流でまとめる理由と残る義務を運ぶ not_applicable（{ge}）")
    hi = next((run.dir / "prompts").glob("r*/report.human_items.md")).read_text(encoding="utf-8")
    check("P1 のゲートの検算" in hi, "報告の冒頭の指示書は、合流した run に移った P1 のゲートの検算も残る義務に挙げさせる")
    rm(run.tmp)
    for kv in ("gates=all", "flow=other"):
        run = Run(f"gbad-{kv.split('=')[0]}", inputs=[kv])
        check(run.init.returncode == 1 and "知らない値" in run.init.stderr and not run.dir.exists(),
              f"--input {kv} は init が盤面を作る前に拒む（{run.init.stderr[-160:]}）")
        rm(run.tmp)
    run = Run("gbad-key", inputs=["gate=merge"])
    check(run.init.returncode == 1 and "綴り違い" in run.init.stderr and not run.dir.exists(),
          f"鍵の綴り違い（gate=merge）は既定に倒さず、init が盤面を作る前に拒む（{run.init.stderr[-160:]}）")
    rm(run.tmp)
    for kv in ("GATES=merge", "gates_mode=merge"):
        run = Run(f"gfar-{kv.split('=')[0]}", inputs=[kv, "gates=merge"])
        key = kv.split("=")[0]
        notes = run.state().get("notes") or [] if run.init.returncode == 0 else []
        out = json.loads(run.init.stdout) if run.init.returncode == 0 else {}
        check(run.init.returncode == 0 and f"--input {key}=" in run.init.stderr and "効かない" in run.init.stderr
              and any(key in n for n in notes) and any(key in n for n in out.get("notes") or []),
              f"宣言に無い鍵 {key} は受け付け、効かないことを stderr・init の返り・盤面の notes に出す（rc={run.init.returncode}・{run.init.stderr[-160:]}）")
        check(not any("gates=" in n for n in notes), f"宣言済みの鍵（gates）は知らせに載らない（{notes}）")
        rm(run.tmp)
    run = Run("gfar-drive", inputs=["gates_mode=merge", "review_md=/no/such.md", "gates=merge"])
    check(run.init.returncode == 0 and "--input review_md=" in run.init.stderr and "rules が埋める" in run.init.stderr,
          f"rules が埋める鍵（by: rules）を渡すと、受け付けて上書きされることを知らせる（rc={run.init.returncode}・{run.init.stderr[-200:]}）")
    drive(run, "std")
    got = run.record()["process"].get("notices") or []
    hi = next((run.dir / "prompts").glob("r*/report.human_items.md")).read_text(encoding="utf-8")
    check(any("gates_mode" in n for n in got) and any("review_md" in n for n in got) and "gates_mode" in hi and "review_md" in hi,
          f"init の知らせは記録の process.notices に組まれ、報告の人向けの項目の指示書に届く（{got}）")
    rm(run.tmp)
    # 選べる値の正本は graph の inputs の values、意味は rules の定数——2 つが割れると、engine が受けた値を rules が既定に倒す
    sys.path.insert(0, str(PLUGIN))
    from engine.rules import load_rules
    gp = PLUGIN / "graphs" / "review-loop.json"
    gj = json.loads(gp.read_text(encoding="utf-8"))
    rules = load_rules(gp, gj)
    check(gj["inputs"]["gates"]["values"] == [rules.GATES_MERGE] and gj["inputs"]["flow"]["values"] == [rules.SPEC_FLOW],
          f"graph の choice の values と rules の定数が一致する（{gj['inputs']['gates']['values']}・{gj['inputs']['flow']['values']}）")


def test_launch_wait_wording():
    """**launch の待ち方の案内**が完了の知らせに頼らせない（next の how・手順書 2 本・loop.py の使い方の 4 か所）。
    知らせを待った回す側が起こされずに止まった（実測 2026-09-25）。1 か所が戻ると回す側はそちらを読む"""
    print("launch の待ち方: 4 か所とも『手番を終えるな』で、完了の知らせを待てと書かない")
    run = Run("waitword")
    how = run.next()["how"]
    texts = {"next の how": how,
             "review-graph.md": (PLUGIN / "commands" / "review-graph.md").read_text(encoding="utf-8"),
             "research-graph.md": (PLUGIN / "commands" / "research-graph.md").read_text(encoding="utf-8"),
             "loop.py": (PLUGIN / "scripts" / "loop.py").read_text(encoding="utf-8")}
    for name, x in texts.items():
        check("手番を終え" in x and "知らせを待て" not in x and "必ず知らせる" not in x,
              f"{name}: launch を立てたら手番を終えずに見に行けと書き、完了の知らせを待てとは書かない")
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
    # 前の周から台帳に残る R2 の前提の行は外さない（外すと、判定の受け付けを通った後の記録の段で『前の周の問いが今の周の
    # 台帳に無い』に当たる）。同じ key の行は差し替える（重複の key は検証器が落とす）
    held = lambda k: {"key": k, "kind": "premise", "origin": "R2", "status": "held", "reason": "z"}
    b = types.SimpleNamespace(round=2, state={"validator": str(VALIDATOR)},
                              loop_state={"prev_questions": [held("引き継いだ前提"), held("差し替える前提")]},
                              record={"questions": [held("引き継いだ前提"), held("差し替える前提"), held("この周の古い前提")]})
    rules.premise_question(b, "stop.premise_check", {"key": "差し替える前提", "verdict": "escalate", "reason": "検算した"}, None)
    got = [(q["key"], q["status"]) for q in b.record["questions"]]
    check(sorted(got) == sorted([("引き継いだ前提", "held"), ("差し替える前提", "escalate")]),
          f"前の周から残る前提の行は残り、同じ key は差し替わり、この周の古い行は外れる（{got}）")

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
    # 土台の commit は author を要る——CI の git には既定の名前が無いので、この repo に置く（engine の版の固定は自分の名前を渡す）
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

    def holds(fn, ls, o=None):
        return cond_call(fn, {"round": 2, "loop": ls, "cur": dict(o or {})})[0]
    check(holds(rules.delta_review_due, {"fix_delta": {"round": 2, "files": ["a.py"]}}),
          "修正差分: 差分が在れば、『塞いだ』申告が無くても 1 回目の差分レビューを起こす")
    check(holds(rules.delta_review_due, {"fix_delta": {"round": 2, "files": []}}, {"p3.fix": {"plan_faces": [{"key": "k1", "handled": "absorbed"}]}}),
          "修正差分: 差分が空でも、『塞いだ』申告が在れば 1 回目の差分レビューを起こす（申告を誰も検算しない形を作らない）")
    check(not holds(rules.delta_review_due, {}) and not holds(rules.fix_delta_nonempty, {"fix_delta": {"round": 1, "files": ["a.py"]}}),
          "修正差分: 差分も申告も無い周・前の周の差分しか無い周は起こさない")
    check(holds(rules.delta_review2_due, {"fix_delta2": {"round": 2, "files": ["a.py"]}}),
          "修正差分: 手直しの差分が在れば 2 回目を起こす")
    check(holds(rules.delta_review2_due, {}, {"p3.delta_fix": {"handled": [{"key": "k1", "handled": "fixed"}]}}),
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
    # **版の作者は利用者の git が決め、決められない時だけ engine の名前で固める**（CI・新しい機械・コンテナ）。
    # git の設定と環境変数は、差し替えた git の子にだけ渡す——os.environ は並列の台本が共有するので書かない（parallel.py の前提）。
    # 走らせる機械の GIT_AUTHOR_* / EMAIL / 利用者の設定に左右されないよう、子の環境から外してから足す
    _td2, bare = parallel.workspace("gl-noident-")
    (bare / "a.py").write_text("A = 1\n", encoding="utf-8")
    for c in (["init", "-q"], ["add", "-A"], ["-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "x"]):
        subprocess.run(["git", *c], cwd=bare, capture_output=True)
    empty_cfg = bare / ".git" / "empty-global-config"
    empty_cfg.write_text("", encoding="utf-8")
    clean = {k: v for k, v in os.environ.items()
             if not k.startswith(("GIT_AUTHOR_", "GIT_COMMITTER_", "GIT_CONFIG")) and k != "EMAIL"}
    clean.update({"GIT_CONFIG_GLOBAL": str(empty_cfg), "GIT_CONFIG_NOSYSTEM": "1"})

    def ident_git(extra, cfg):
        """cfg（git の設定の組）と extra（環境変数）だけを持つ git。rules の env と why も実物と同じに扱う"""
        base = {**clean, **extra, "GIT_CONFIG_COUNT": str(len(cfg))}
        for i, (k, v) in enumerate(cfg):
            base.update({f"GIT_CONFIG_KEY_{i}": k, f"GIT_CONFIG_VALUE_{i}": v})

        def g(*a, env=None, why=None):
            q = subprocess.run(["git", "-C", str(bare), *a], capture_output=True, text=True, encoding="utf-8", errors="replace",
                               env={**base, **(env or {})})
            if q.returncode != 0 and why is not None:
                why.append(q.stderr.strip())
            return q.stdout if q.returncode == 0 else None
        return g
    brules = load_review_rules(bare)
    no_ident = [("user.useConfigOnly", "true")]

    def ident_of(g):
        brules.git = g
        try:
            return (g("log", "-1", "--format=%an|%ae|%cn|%ce", brules._snapshot("検査用")) or "").strip()
        except Exception as e:   # noqa: BLE001 — 止まった回は Reject の文を失敗の説明に出す
            return str(e)
    got = ident_of(ident_git({}, no_ident))
    check(got == "graphloops|graphloops@localhost|graphloops|graphloops@localhost",
          f"版の固定: 利用者の git に名前とメールが無くても、engine の名前で版を固める（{got[:70]}）")
    got = ident_of(ident_git({}, no_ident + [("user.name", "設定の人"), ("user.email", "set@example.invalid")]))
    check(got == "設定の人|set@example.invalid|設定の人|set@example.invalid",
          f"版の固定: 名前とメールを設定済みの利用者の版は、利用者の名前とメールでできる（engine の名前で上書きしない。{got[:70]}）")
    # user.useConfigOnly は EMAIL も拒むので外す（git の推し量りの順に git 自身が EMAIL を入れる形を見る）
    got = ident_of(ident_git({"EMAIL": "env@example.invalid"}, [("user.name", "設定の人")]))
    check(got == "設定の人|env@example.invalid|設定の人|env@example.invalid",
          f"版の固定: メールを環境変数 EMAIL で与えた利用者も、git が決めるとおりの作者でできる（{got[:70]}）")
    got = ident_of(ident_git({"GIT_COMMITTER_DATE": "日付でない"}, no_ident + [("user.name", "u"), ("user.email", "u@u")]))
    check("版を固定できない" in got and "git commit-tree" in got and "date" in got,
          f"版の固定: commit-tree が止まった回は、git が言った理由（標準エラー）を文に添える（{got[:160]}）")
    from engine import util as _util  # noqa: E402
    said = []
    none = _util.git("-C", str(bare), "rev-parse", "--verify", "無い版^{commit}", why=said)
    check(none is None and len(said) == 1 and "fatal" in said[0],
          f"util.git: 失敗の回は None のまま、why に git の標準エラーの末尾を足す（{said}）")
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
    try:
        rules.POST_CHECKS["delta_review_output"](at({}), "p3.delta_review2",
                                                 {"faces": [{"key": "出典が当たらない", "kind": "precedent", "where": "a.py", "cite": "x",
                                                             "why": "検査用"}], "checks": []}, None)
        got = "通った"
    except Reject as e:
        got = str(e)
    check("'precedent' は事前審査だけの語" in got, f"修正差分のレビュー: 先行例の出典の穴（precedent）は事前審査だけの語として拒む（{got[:90]}）")
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
    check("p4.final_gates" in nodes["converge"]["deps"] and nodes["p4.final_gates"]["cond"] == "final_gate_due",
          "最後の関門: converge は関門を待ち、関門は収束しうる周にだけ撃つ（合流でまとめる run は撃たない）")
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
    # テスト一式の緑は役の申告で受けない（p4.ci を engine が走らせた結果が正本）——suite は読まない欄
    check(E(good(head, suite={"command": "bash run.sh", "exit": 1})) == [] and E({k: v for k, v in good(head).items() if k != "suite"}) == [],
          "線の結果: テスト一式の申告（suite）は読まない——赤と書いても、書かなくても、それで結果を捨てない")
    for bad, want, desc in [
            (good(head, handled=[]), "に答えが無い", "見逃した腕に答えの無い結果"),
            (good(head, handled=good(head)["handled"] + [{"key": "arm:ok", "handled": "equivalent", "how": "見逃していない腕（検査用）"}]),
             "見逃した腕に無い", "見逃していない腕に答えた結果"),
            ({**good(head), "rev": "0" * 40}, "名指しの版", "名指しと違う版を撃った結果"),
            (good(head, handled=[{"key": "arm:miss", "handled": "tests_added", "how": "テストを足した（検査用）"}]), "patch", "テストを足したのに patch が無い結果"),
            (good(head, arms=[_lane_arm("nohit", hit_evidence="")], handled=[]), "arm:nohit", "当たりの証拠の無い腕を見逃しと数えない結果")]:
        got = "; ".join(E(bad))
        check(want in got, f"線の結果: {desc}は使わない（{got[:90]}）")
    got = "; ".join(E(good(head, handled=[{"key": "arm:miss", "handled": "tests_added", "how": "テストを足した（検査用）"}], patch="x.patch"), final=True))
    check("作業ツリーに書かない" in got, f"最後の関門: テストを足した（tests_added）と言う関門の返答は拒む（{got[:80]}）")
    check(E(good(head, arms=[], handled=[]), final=True) == [] and E(good(head, arms=[], handled=[])) == [],
          "撃った腕が 0 本の返答は型と整合では拒まない（関門を通すかは _final_gate_problems が人に諮る形で決める）")
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
    # 止めた線に後から届いた結果は、判定へ渡るはずの答え（defect）を持つ——止めた線だから渡さない、を見分けるため
    late_rows = [{"key": "arm:miss", "handled": "defect", "how": "止めた後に届いた結果の閉じない見逃し（検査用）"}]
    (board / "lanes" / "late.json").write_text(json.dumps(good("c" * 40, handled=late_rows, patch="")), encoding="utf-8")
    b.loop_state = {"lanes": {"c" * 40: {**lane("late"), "rev": "c" * 40, "state": "abandoned", "why": "回す側が止めた（検査用）"},
                              "b" * 40: {"state": "abandoned", "why": "丸ごと書いた（検査用）"},
                              "a" * 40: {**lane("x"), "state": "abandoned"}}}
    r = rules.lane_merge(b, "p3.lane_merge")
    check(r["ok"] and b.loop_state["lane_merge"]["merged"] == [] and b.loop_state["lanes"]["c" * 40]["state"] == "abandoned",
          f"止めた線: 後から届いた結果も重ねない（{b.loop_state['lane_merge']}）")
    rows = rules._lane_faces(b)
    check(sorted(x["key"][:13] for x in rows) == sorted(["線 @" + "a" * 10, "線 @" + "b" * 10]) and all("読めない" in x["key"] for x in rows),
          f"止めた線: 止めた線は判定へ渡さず、形の崩れた行（欄が無い・why が無い）だけを渡す（{[x['key'] for x in rows]}）")
    check(rules._lane_faces(b) == [], "止めた線: 形の崩れた行は 1 度だけ渡す")
    s = {x["rev"]: x for x in rules.lane_summary(b)}
    check(s["c" * 40]["state"] == "abandoned" and s["c" * 40]["why"] and s["c" * 40]["arms"] is None
          and s["a" * 40]["state"] == s["b" * 40]["state"] == "unreadable",
          f"止めた線: 要約は running と書かず abandoned と理由を、崩れた行は unreadable を書く（{ {k[:4]: v['state'] for k, v in s.items()} }）")
    (board / "lanes" / "zero.json").write_text(json.dumps(good(head, arms=[], handled=[])), encoding="utf-8")
    for declared_mut, want in ((True, 1), (False, 0)):
        b.loop_state = {"lanes": {head: lane("zero")}, "mutation_decl": {"declared": declared_mut, "text": "検査用"}}
        rows = rules._lane_faces(b)
        check(len(rows) == want and all("0 本" in x["key"] for x in rows),
              f"撃てた腕 0 本: 宣言に実行器が{'在る' if declared_mut else '無い'}なら判定へ {want} 行（{[x['key'] for x in rows]}）")
    check(rules.lane_summary(b)[0]["arms"] == 0, "撃てた腕 0 本: 要約に撃てた腕の本数 0 を書く（見逃し 0 本と読み分ける）")
    (tmp / "arms.json").write_text("{}", encoding="utf-8")
    for decl, want_declared, want in (
            ({"suite": [{"name": "s", "argv": ["x"]}], "mutation": {"argv": ["runner-gl"], "arms": "arms.json"}}, True, "runner-gl"),
            ({"suite": [{"name": "s", "argv": ["x"]}], "mutation": {"argv": ["runner-gl"], "arms": "no-such.json"}}, False, "読めない"),
            (None, False, "mutation の段が無い")):
        (tmp / ".review-checks.json").unlink(missing_ok=True)
        if decl:
            (tmp / ".review-checks.json").write_text(json.dumps(decl), encoding="utf-8")
        rules.mutation_decl(b)
        md = b.loop_state["mutation_decl"]
        check(md["declared"] is want_declared and want in md["text"], f"実行器の名指し: {want}（{md}）")
    (tmp / ".review-checks.json").write_text(json.dumps({"suite": [{"name": "s", "argv": ["x"]}], "mutations": {"argv": ["r"], "arms": "arms.json"}}),
                                             encoding="utf-8")
    b.loop_state = {}
    rules.mutation_decl(b)
    md = b.loop_state["mutation_decl"]
    check(md["unknown"] == ["mutations"] and "mutations" in md["text"] and not md["declared"],
          f"宣言の知らない段: 役に貼る名指しに、読まない段の名前を添える（{md}）")
    runs = [{"name": "s", "exit": 0, "wall_s": 1}]
    m = rules.checks_reply(b, "p0.local_checks", {"sha": "a" * 40}, runs)["reply"]["material"]
    check(m["status"] == "awaiting_human" and "mutations" in m["reason"] and "s: exit 0" in m["reason"],
          f"宣言の知らない段: 知っている段は走らせ、P0 は結果を添えて人待ちにする（{m}）")
    m = rules.checks_reply(b, "p4.ci", {"sha": "a" * 40}, runs)["reply"]["material"]
    check(m["status"] == "clean", f"宣言の知らない段: 判定の後（p4.ci）は人待ちを新しく立てない（{m}）")
    b.state["notes"] = ["--input GATES=… は効かない（検査用）"]
    b.loop_state["lanes"] = {"e" * 40: {**lane("never"), "rev": "e" * 40}}
    got = rules.notices(b)
    check(any(n.startswith("init: ") and "GATES" in n for n in got) and any("mutations" in n for n in got)
          and any("e" * 12 in n and "running" in n for n in got),
          f"機械の知らせ: init の効かない入力・宣言の知らない段・結果の来ない線を組む（{got}）")
    b.loop_state["outcome"] = "converged"
    check(not any("running" in n for n in rules.notices(b)), "機械の知らせ: 収束した run の最後の線は知らせない（最後の関門が撃ち直した）")
    b.state.pop("notes")
    (tmp / ".review-checks.json").unlink()
    for ran, want in ((True, 1), (False, 0)):
        b.loop_state = {}
        rules.mutation_decl(b)
        b.state["outputs"] = {"p1.gate_efficacy": {"round": 2}} if ran else {}
        got = [n for n in rules.notices(b) if "mutation の段が無い" in n]
        check(len(got) == want, f"機械の知らせ: 宣言外で探した実行器は、撃つ節が{'出た' if ran else '出ない'} run で {want} 件（{got}）")
    b.state.pop("outputs")
    (tmp / "arms.json").unlink()
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
    # 撃てた腕が 0 本の関門は通さず人に諮る（converge が聞く）。人が continue した同じ木なら通る
    (tmp / "a.py").write_text("A = 1\n", encoding="utf-8")
    b.loop_state = {"gates_cut": {"round": 2, "rev": snap, "files": []}}
    outs["p4.final_gates"] = good(snap, arms=[], handled=[])
    check(P() == rules.FINAL_GATE_EMPTY, f"最後の関門: 撃てた腕が 0 本なら通さず、人に諮る印だけを返す（{P()[:80]}）")
    tree = subprocess.run(["git", "rev-parse", f"{snap}^{{tree}}"], cwd=tmp, capture_output=True, text=True, encoding="utf-8").stdout.strip()
    b.loop_state["final_gate_empty_ok"] = tree
    check(P() == "", f"最後の関門: 人が 0 本で収束してよいと答えた木なら通る（{P()[:80]}）")
    b.loop_state["final_gate_empty_ok"] = "0" * 40
    check(P() == rules.FINAL_GATE_EMPTY, "最後の関門: 答えた木と違う木なら聞き直す")
    (tmp / "a.py").write_text("A = 2\n", encoding="utf-8")   # 下の線の範囲の台本が見る作業ツリーに戻す
    # 撃てた腕が 0 本の線は、線の要約で『撃っていない』（arms 0）と見える——見逃し 0 本（open が空）と区別できる
    (board / "lanes" / "empty.json").write_text(json.dumps(good(head, arms=[], handled=[]), ensure_ascii=False), encoding="utf-8")
    b.loop_state = {"lanes": {head: lane("empty")}}
    rows = rules.lane_summary(b)
    check(rows and rows[0].get("arms") == 0 and rows[0]["open"] == [], f"線の要約: 0 本の線は arms 0 を載せる（{rows}）")
    # 線の defect は次の周の判定に人の依頼の入口で届く（出どころは線）。依頼の欄が崩れていれば宣言の穴に落とす
    b.record = {"units": [], "questions": [], "materials": {}, "process": {}}
    b.loop_state = {}
    row = {"key": "線 r1@abc: arm:x", "from": "p3.delta_gates", "how": "defect: 変異した方が仕様に合う（検査用）", rules.LANE_DEFECT: True}
    rules._route_lane_defects(b, [row])
    batch = (b.record["process"].get("request_findings") or [{}])[-1]
    check(batch.get("origin") == rules.LANE_ORIGIN and batch["findings"][0]["where"] == row["key"]
          and batch["findings"][0]["text"].startswith(rules.LANE_PROVENANCE) and not b.loop_state.get("prev_declared_faces"),
          f"線の defect は人の依頼の入口（request_findings）に出どころつきで積む（{batch}）")
    b.record["process"]["request_findings"] = "型崩れ"
    rules._route_lane_defects(b, [row])
    check(b.record["process"]["request_findings"] == "型崩れ" and not b.loop_state.get("prev_declared_faces"),
          "依頼の欄が崩れていて積めない回は触らずに戻る（同じ行は on_new_round が宣言の穴に載せてある）")
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
    check(r["ok"] and "a.py" in cut["files"] and cut["rev"] in b.loop_state["lanes"] and cond_call(rules.gates_cut_nonempty, {"loop": b.loop_state, "round": b.round})[0]
          and cut["result"].startswith(str(board / "lanes")) and cut["reply_schema"].get("required"),
          f"線の範囲: 周の頭からこの版までの変更を置き、線の置き場と結果の型を渡す（{cut.get('files')}）")
    (tmp / "a.py").write_text("A = 1\n", encoding="utf-8")
    subprocess.run(["git", "checkout", "-q", "--", "."], cwd=tmp, capture_output=True)
    b.loop_state = {"head_revs": {"2": rules._snapshot("検査用")}}
    rules.gates_cut(b, "p3.gates_cut")
    check(not cond_call(rules.gates_cut_nonempty, {"loop": b.loop_state, "round": b.round})[0] and not b.loop_state.get("lanes"), "線の範囲: 周の頭から変わっていなければ線を立てない")
    b.loop_state["gates_cut"]["round"] = 1
    check(not cond_call(rules.gates_cut_nonempty, {"loop": b.loop_state, "round": b.round})[0], "線の範囲: 前の周に固めた範囲では線を立てない")
    rm(tmp)


def test_lane_end_to_end():
    """線を待たずに周が進み、線が後で書いた結果が合流し、最後の関門が収束を止める——端から端まで"""
    print("並行の線（端から端）: 線の結果が無くても周は進み、後で書いた結果の patch は修正の前に重なり、閉じなかった見逃しは次の判定へ、関門は収束を止める")
    run = Run("lane")
    seen = {"lane_written": False, "gate_calls": 0}

    def hook(run_, inst, out):
        st = run_.state()
        if inst["node"] == "p2.history" and st["round"] == 2 and not seen["lane_written"]:
            # 1 周目の線は 2 周目の判定の頃に書き終えた——patch は線の写しの側に、結果は置き場に書く（線の役と engine の代わり）
            lane = next(x for x in st["loop"]["lanes"].values() if x["round"] == 1)
            lane["patch"] = str(pathlib.Path(lane["result"]).with_suffix(".patch"))
            pathlib.Path(lane["patch"]).write_text(LANE_PATCH, encoding="utf-8")
            res = {"rev": lane["rev"], "arms": [PROVEN_ARM, _lane_arm("線の見逃し", red_confirmed=False), _lane_arm("線の欠陥", red_confirmed=False),
                                                _lane_arm("線のテスト不足", red_confirmed=False)],
                   "handled": [{"key": "arm:線の見逃し", "handled": "tests_added", "how": "テストを足してその腕の赤を見た（検査用）"},
                               {"key": "arm:線の欠陥", "handled": "defect", "how": "変異した方が仕様に合う（検査用）"},
                               {"key": "arm:線のテスト不足", "handled": "needs_test", "how": "テストの足場が無い（検査用）"}],
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
    pr = run.record()["process"]
    lane_batches = [x for x in (pr.get("request_history") or []) + (pr.get("request_findings") or []) if x.get("origin") == rules_lane_origin()]
    in_batch = [f["where"] for x in lane_batches for f in x["findings"]]
    check(any("arm:線の欠陥" in k for k in in_batch) and all(x["round"] == 3 for x in lane_batches)
          and not any("arm:線のテスト不足" in k or "arm:線の見逃し" in k for k in in_batch),
          f"合流: 線がテストで閉じられなかった見逃し（defect）だけが、書き終えた後の周の判定に依頼の入口（出どころは線）でも届く（{in_batch}）")
    check(any("arm:線のテスト不足" in k for k in routed) and any("arm:線の欠陥" in k for k in routed) and not any("arm:線の見逃し" in k for k in routed),
          f"合流: 閉じなかった見逃し（needs_test・defect）は宣言の穴として 1 件ずつ振り分けられる（{routed}）")
    hp = (run.dir / "prompts" / "r3" / "p2.history.md").read_text(encoding="utf-8")
    same = rules_lane_same_item()
    check(hp.count(same) == 1 and same in hp[hp.index("arm:線の欠陥"):],
          "合流: 依頼の入口にも積んだ defect は、宣言の穴の行に『同じ 1 件』と書かれて判定に届く（2 つの入口から別の単位を立てない）")
    last_r = st["round"]
    hl = json.loads((run.dir / "out" / f"r{last_r}" / "p2.history.json").read_text(encoding="utf-8"))
    check(any("最後の関門" in r["key"] for r in hl.get("declared_routed") or []),
          f"最後の関門: 関門が見つけた、テストの要る見逃しは次の周の判定に届く（{[r['key'] for r in hl.get('declared_routed') or []]}）")
    lanes = run.record()["process"].get("lanes") or []
    check(lanes and lanes[0]["state"] == "merged" and lanes[0]["open"] == ["arm:線の欠陥", "arm:線のテスト不足"],
          f"記録: 線の台帳の要約（合流したか・閉じなかった見逃し）が process.lanes に残る（{lanes[:2]}）")
    rm(run.tmp)


def rules_lane_origin():
    return load_review_rules(PLUGIN).LANE_ORIGIN


def rules_lane_same_item():
    return load_review_rules(PLUGIN).LANE_SAME_ITEM


TINYJUNIT = HERE / "tinyjunit.py"
TDD_RED = "import pathlib\n\n\ndef test_limit_is_fixed():\n    assert \"fixed\" in pathlib.Path(\"src/a.py\").read_text()\n"


def test_tdd_flow():
    """TDD の流れ（graphs/review-loop-tdd.json）を端から端まで: テストだけを書く段 → 赤の確認 → 実装（p3.fix のまま）→ 緑の確認。
    読み込みで落ちた赤と、実装の段がテストを書き換えた緑は機械が差し戻し、先にテストを書けない単位は理由つきで今の流れへ回る"""
    print("TDD の流れ: 赤は狙いどおりの失敗だけ、緑はテストを書き換えずに全部通る、direct は今の流れ、効き目は process.tdd に")
    bare = Run("tdd-noinput", loop="review-loop-tdd")
    check(bare.init.returncode != 0 and "tdd_suite" in bare.init.stderr and not bare.dir.exists(),
          f"TDD の流れはテスト一式の実行ファイル（--input tdd_suite）が無ければ、盤面を作る前に init で止まる（{bare.init.returncode}: {bare.init.stderr[-200:]}）")
    rm(bare.tmp)
    run = Run("tdd", loop="review-loop-tdd", inputs=(f"tdd_suite={TINYJUNIT}",))
    check(run.init.returncode == 0, f"TDD 版は init --loop review-loop-tdd で選ぶ（{run.init.stderr[-300:]}）")
    seen = {"tests": 0, "fix": 0, "red_why": [], "green_why": []}
    test_file = run.repo / "tests" / "test_limit.py"

    def hook(run_, inst, out):
        if inst["node"] == "p3.tdd_tests":
            seen["tests"] += 1
            test_file.parent.mkdir(exist_ok=True)
            impl = run_.repo / "src" / "b.py"
            if seen["tests"] == 1:   # 読み込みで落ちるテスト——赤でも狙いどおりの赤でない。ついでに実装のファイルにも触れる
                test_file.write_text("import no_such_module_for_red  # noqa\n\n\ndef test_limit_is_fixed():\n    assert False\n", encoding="utf-8")
                seen["impl"] = impl.read_text(encoding="utf-8")
                impl.write_text(seen["impl"] + "# テストの段で実装に触れた\n", encoding="utf-8")
            else:
                seen["red_why"] = (run_.state()["loop"].get("tdd") or {}).get("problems") or []
                test_file.write_text(TDD_RED, encoding="utf-8")
                impl.write_text(seen["impl"], encoding="utf-8")
                # 2 回目は単位を番号で指す（pointers）——プロンプトに貼られた no を読んで使う
                nos = {json.loads(f'"{s}"'): int(n) for n, s in NO_ROW.findall(pathlib.Path(inst["prompt_file"]).read_text(encoding="utf-8"))}
                out = {**out, "units": [{**u, "unit_key": nos.get(u["unit_key"], u["unit_key"])} for u in out["units"]]}
                seen["by_number"] = all(isinstance(u["unit_key"], int) for u in out["units"])
        if inst["node"] == "p3.fix" and run_.state()["round"] == 1:   # 2 周目からは直す単位が無く、TDD の段は走らない
            seen["fix"] += 1
            if seen["fix"] == 1:     # 実装の段がテストを弱める——緑の確認が拒む
                test_file.write_text("def test_limit_is_fixed():\n    assert True\n", encoding="utf-8")
            else:
                seen["green_why"] = (run_.state()["loop"].get("tdd") or {}).get("problems") or []
                test_file.write_text(TDD_RED, encoding="utf-8")
        return out
    last = drive(run, "std", hook=hook)
    check(last["status"] == "converged", f"TDD の流れでも収束まで届く（{last['status']}）")
    check(seen.get("by_number"), "テストだけを書く段も、単位を貼られた no で指せる（pointers）")
    na2 = run.state()["rounds"][1].get("na") or {}
    check("p3.tdd_start" in na2, f"直す単位が無い周は、テスト一式を走らせる p3.tdd_start も条件外（{sorted(k for k in na2 if k.startswith('p3.tdd'))}）")
    check(seen["tests"] == 2 and any("一式の結末に居ない" in w for w in seen["red_why"]),
          f"赤の確認: 読み込みで落ちたテストは赤と認めず、テストだけを書く段を差し戻す（{seen['tests']} 回・{seen['red_why'][:2]}）")
    check(any("申告したテストのファイルの外に触れた" in w and "src/b.py" in w for w in seen["red_why"]),
          f"赤の確認: テストだけを書く段が実装のファイル（test_files の外）に触れたら差し戻す（{seen['red_why'][:3]}）")
    check(seen["fix"] == 2 and any("書き換えた" in w for w in seen["green_why"]),
          f"緑の確認: 実装の段が名指しのテストのファイルを書き換えたら、通っていても差し戻す（{seen['fix']} 回・{seen['green_why'][:2]}）")
    row = ((run.record()["process"].get("tdd") or {}).get("rounds") or {}).get("1") or {}
    unit_block = next(u["key"] for u in run.round_file(1)["units"] if u["label"] == "block")
    check(row.get("named") == ["tests/test_limit.py::test_limit_is_fixed"] and row.get("red") == "ok" and row.get("green") == "ok"
          and len(row.get("direct") or []) == 1 and unit_block not in row["direct"],
          f"記録: TDD の周の振り分け（名指し・direct）と赤・緑の結果が process.tdd に残る（{row}）")
    check("lane_missed" in row and row.get("faces_created_by_this_fix") == run.round_file(2).get("scalars", {}).get("faces_created_by_prev_fix"),
          f"記録: 効き目の 2 つの量（変異の見逃しの本数・この周の修正が作った指摘の件数）の欄が在り、後者は次の周の記録から引く（{row}）")
    fix_prompt = next((run.dir / "prompts" / "r1").glob("p3.fix*.md")).read_text(encoding="utf-8")
    check("## TDD の流れ" in fix_prompt and "tests/test_limit.py::test_limit_is_fixed" in fix_prompt,
          "実装の段（p3.fix）の指示書の後ろに TDD の段落が足され、名指しのテストが渡る（元の指示書は写さない）")
    check("tdd" in (run.state().get("loop") or {}), "TDD の版の盤面は loop に tdd を書いた（形の照らしが空の盤面を見ていない）")
    loop_shape_held(run, "TDD の流れ")
    rm(run.tmp)


def test_tdd_gives_up_without_dead_end():
    """TDD の流れの出口: 周の頭で元から落ちているテストは『ほかは緑のまま』に数えず、赤の確認が上限まで通らなければ
    TDD を諦めて今の流れで進み（止まらない——止まると出口が patch しか無い）、理由は次の周の判定役に届く"""
    print("TDD の流れの出口: 元から赤いテストは問わず、上限で諦めても止まらず、理由は次の周の判定へ")
    run = Run("tdd-giveup", loop="review-loop-tdd", inputs=(f"tdd_suite={TINYJUNIT}",))
    (run.repo / "tests").mkdir()
    (run.repo / "tests" / "test_old_red.py").write_text("def test_was_red_before():\n    assert False\n", encoding="utf-8")
    seen = {"tests": 0}

    def hook(run_, inst, out):
        if inst["node"] == "p3.tdd_tests":
            seen["tests"] += 1   # 毎回、読み込みで落ちるテスト——狙いどおりの赤にならない
            (run_.repo / "tests" / "test_limit.py").write_text("import no_such_module_for_red  # noqa\n\n\ndef test_limit_is_fixed():\n    assert False\n", encoding="utf-8")
        return out
    last = drive(run, "std", hook=hook)
    row = ((run.record()["process"].get("tdd") or {}).get("rounds") or {}).get("1") or {}
    check(last["status"] == "converged" and seen["tests"] == 3 and row.get("red") == "failed" and "green" not in row,
          f"赤の確認が 3 回通らなければ TDD を諦めて今の流れで直し、緑の確認は撃たない（{last['status']}・{seen['tests']} 回・{row.get('red')}）")
    check(row.get("baseline_red") == ["tests.test_old_red::test_was_red_before"]
          and not any("test_was_red_before" in p for p in row.get("red_problems") or []),
          f"周の頭で元から落ちていたテストは記録に残し、赤の確認の『ほか』には数えない（{row.get('baseline_red')}・{(row.get('red_problems') or [])[:2]}）")
    h2 = json.loads((run.dir / "out" / "r2" / "p2.history.json").read_text(encoding="utf-8"))
    check(any("TDD の赤の確認が上限で通らなかった" in r["key"] for r in h2.get("declared_routed") or []),
          f"諦めた理由は次の周の判定役に穴の行として届く（{[r['key'] for r in h2.get('declared_routed') or []][:3]}）")
    check(bool((run.state().get("loop") or {}).get("tdd_gave_up")), "TDD を諦めた盤面は loop に tdd_gave_up を書いた")
    loop_shape_held(run, "TDD を諦めた流れ")
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


NO_ROW = re.compile(r'"no": (\d+),\s*"\w+": "((?:[^"\\]|\\.)*)"')


def by_number(converted):
    """drive の hook: 役が名前を写す代わりに、**プロンプトに貼られた no** で指す返答に書き換える。
    番号はプロンプトの本文から読む——台本が名前と番号の対応を知っている前提で書くと、番号が役に見えなくても緑になる"""
    from engine.pointers import _segs, _slots
    from engine.schema import load_graph
    nodes = load_graph(str(PLUGIN / "graphs" / "review-loop.json"))[0]["nodes"]

    def hook(run, inst, out):
        ptrs = nodes[inst["node"]].get("pointers")
        if not ptrs or not isinstance(out, dict):
            return out
        body = pathlib.Path(inst["prompt_file"]).read_text(encoding="utf-8")
        seen = {json.loads(f'"{s}"'): int(n) for n, s in NO_ROW.findall(body)}
        out = json.loads(json.dumps(out))
        for p in ptrs:
            for box, k in _slots(out, _segs(p["at"])):
                check(box[k] in seen, f"{inst['node']}: {p['at']} の名前『{str(box[k])[:30]}』の no がプロンプトに貼られている")
                if box[k] in seen:
                    box[k] = seen[box[k]]
                    converted.add(inst["node"])
        return out
    return hook


def test_pointers_by_number():
    """**役に写させない。** 判定の単位の key・事前審査の穴の key を役が一字一句写し、1 字違えば受け付けで拒んで返させ直していた
    （実測: run 20260924-081523 の 5 周目に 3 回の差し戻し）。engine が貼る一覧に no を振り、役は番号で指し、engine が名前に戻して記録する"""
    print("写させない: 役は貼られた一覧の no で指し、engine が名前に戻して記録する（範囲外と、固めていない instance の番号は拒む）")
    from engine.schema import expand_refs
    # 読み込みの入口（widen）: 宣言の誤りは graph を読んだ時点で落ちる
    base = {"reads": ["record.units"], "schema": {"type": "object", "properties": {"ks": {"type": "array", "items": {"type": "string"}}}}}
    def widen_says(ptr):
        try:
            expand_refs({"nodes": {"n": {**json.loads(json.dumps(base)), "pointers": [ptr]}}})
            return "（拒まなかった）"
        except Exception as e:   # ValueError 以外で落ちた（宣言の検査が抜けて先で壊れた）も赤にする
            return f"{type(e).__name__}: {e}"
    said = widen_says({"at": "nope[]", "from": ["record.units"]})
    check(said.startswith("ValueError") and "文字列の欄に無い" in said, f"widen: schema に無い位置の宣言は graph を読む時点で拒む（{said[:70]}）")
    said = widen_says({"at": "ks[]", "from": ["record.questions"]})
    check(said.startswith("ValueError") and "reads に無い" in said, f"widen: reads に無い一覧の宣言は graph を読む時点で拒む（{said[:70]}）")
    said = widen_says({"at": "ks[]", "form": ["record.units"]})
    check(said.startswith("ValueError") and "{at, from" in said, f"widen: 欄の綴り違いの宣言は graph を読む時点で拒む（{said[:70]}）")
    try:
        expand_refs({"nodes": {"n": {"reads": ["record.units"], "pointers": [{"at": "ks[]", "from": ["record.units"]}]}}})
        said = "（拒まなかった）"
    except Exception as e:
        said = f"{type(e).__name__}: {e}"
    check(said.startswith("ValueError") and "schema を持つ節" in said, f"widen: schema を持たない節の pointers は拒む（{said[:70]}）")
    two = {**json.loads(json.dumps(base)), "reads": ["record.units", "record.questions"]}
    two["schema"]["properties"]["js"] = {"type": "array", "items": {"type": "string"}}
    try:
        expand_refs({"nodes": {"n": {**two, "pointers": [{"at": "ks[]", "from": ["record.units"]},
                                                          {"at": "js[]", "from": ["record.questions", "record.units"]}]}}})
        said = "（拒まなかった）"
    except Exception as e:
        said = f"{type(e).__name__}: {e}"
    check(said.startswith("ValueError") and "別の連結" in said, f"widen: 同じ一覧を別の連結で指す宣言は拒む（{said[:70]}）")
    from engine.pointers import number
    rows = number([{"no": 12, "key": "a"}, {"key": "b"}], 0)
    check([r["no"] for r in rows] == [1, 2] and list(rows[0]) == ["no", "key"],
          f"number: 行が元から no を持っていても engine の番号で上書きする（{rows}）")
    g = expand_refs({"nodes": {"n": {**json.loads(json.dumps(base)), "pointers": [{"at": "ks[]", "from": ["record.units"]}]}}})
    leaf = g["nodes"]["n"]["schema"]["properties"]["ks"]["items"]
    check(leaf.get("type") == ["integer", "string"] and leaf.get("minimum") == 1, f"widen: 指す欄の型は宣言から番号か名前に広がる（{leaf}）")

    run = Run("ptrs")
    at = lambda node: (lambda nx: any(i["node"] == node for i in nx["ready"]))
    nx = drive(run, "planfaces", stop_at=at("p2.fix_plan"))
    item = next(i for i in nx["ready"] if i["node"] == "p2.fix_plan")
    good = answers(run, "planfaces", nx["round"])["p2.fix_plan"](load_item(item))
    r = run.done(item["id"], {"plan": [{**good["plan"][0], "unit_keys": [99]}]})
    check(r.returncode == 1 and "no に無い" in r.stderr, f"範囲外の番号は拒む（{r.stderr.strip()[-80:]}）")
    # 拒む種類は『役に返せば直る』（AnswerReject）——engine が起こした役なら launch が同じ会話に続きを頼む
    from engine.board import Board
    from engine.commands import accept_output
    from engine.util import AnswerReject
    try:
        accept_output(Board(run.dir), item["id"], json.dumps({"plan": [{**good["plan"][0], "unit_keys": [99]}]}, ensure_ascii=False), "検査用")
        kind = "受け付けた"
    except AnswerReject:
        kind = "AnswerReject"
    except Exception as e:
        kind = type(e).__name__
    check(kind == "AnswerReject", f"範囲外の番号は役に返せば直る拒否（AnswerReject）で上がる（{kind}）")
    st = run.state()
    snap = st["rounds"][-1]["instances"][item["id"]].pop("pointers", None)
    check(snap and snap[0]["names"], "emit の時点で、貼った一覧の名前の列を instance に固める")
    (run.dir / "state.json").write_text(json.dumps(st, ensure_ascii=False), encoding="utf-8")
    r = run.done(item["id"], {"plan": [{**good["plan"][0], "unit_keys": [1]}]})
    check(r.returncode == 1 and "固めていない" in r.stderr, f"名前の列を固めていない instance（出した後に graph が変わった）への番号は拒む（{r.stderr.strip()[-80:]}）")
    st["rounds"][-1]["instances"][item["id"]]["pointers"] = snap
    (run.dir / "state.json").write_text(json.dumps(st, ensure_ascii=False), encoding="utf-8")
    converted = set()
    last = drive(run, "planfaces", hook=by_number(converted))
    want = {"p2.fix_plan", "p2.plan_review", "p3.fix", "p3.delta_review", "p3.delta_fix", "p3.delta_review2", "p3.delta_fix2", "p2.history"}
    check(want <= converted, f"番号で指した節が揃う（足りない: {sorted(want - converted)}）")
    check(last["status"] in TERMINAL_STATUS, f"番号で指しても名前で指した筋書きと同じく終わりまで回る（{last['status']}）")
    pr = run.record()["process"]
    keys = lambda rows, f="key": [x[f] for x in rows or []]
    fp = json.loads((run.dir / "out" / "r1" / "p2.fix_plan.json").read_text(encoding="utf-8"))
    check(all(isinstance(k, str) for p in fp["plan"] for k in p["unit_keys"]), f"記録された修正案は名前（{fp['plan'][0]['unit_keys']}）")
    fixes = [f for f in pr.get("fixes") or [] if f.get("round") == 1]
    check(fixes and "別案: 定数を 1 つに" in keys(fixes[-1].get("plan_faces")),
          f"事前審査の別案（faces の後ろの通し番号）も名前に戻る（{keys(fixes[-1].get('plan_faces')) if fixes else None}）")
    h2 = json.loads((run.dir / "out" / "r2" / "p2.history.json").read_text(encoding="utf-8"))
    check({"別案: 定数を 1 つに", "手直しの穴（検査用）"} <= set(keys(h2.get("declared_routed"))),
          f"周をまたぐ振り分けは名前の字面で記録に残る（{keys(h2.get('declared_routed'))}）")
    body = (run.dir / "prompts" / "r1" / "p3.fix.md").read_text(encoding="utf-8")
    check('"no": 3,\n  "key": "別案: 定数を 1 つに"' in body, "連結した一覧（穴 2 件と別案）は通し番号で貼られる")
    rm(run.tmp)

    run = Run("ptrs-r1")
    converted = set()
    last = drive(run, "carryr1", hook=by_number(converted))
    check("p2.diagnose" in converted, f"前の周の R1 の削除候補も no で指せる（{sorted(converted)}）")
    d2 = json.loads((run.dir / "out" / "r2" / "p2.diagnose.json").read_text(encoding="utf-8"))
    check(keys(d2.get("carried_r1"), "where") == [R1_DELETION], f"削除候補は where の字面に戻って記録される（{d2.get('carried_r1')}）")
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
    part = rules.purpose_sources_changed   # 目的監査の条件（purpose_review_due）の部品

    def board(purpose, touched):
        return types.SimpleNamespace(round=3, state={"round": 3}, loop_state={"prev_fix_files": touched}, purpose=purpose)

    def fn(b):
        b.state["round"] = b.round
        return cond_call(part, {"round": b.round, "out": {"p0.purpose": b.purpose}, "loop": b.loop_state}, state=b.state)[0]

    # 欄が無い＝測れない。偽だが痕跡が残る
    b = board({"purpose_text": "x", "source": "③writer の要約"}, ["README.md"])
    check(fn(b) is False, "欄が無い周は発火しない（合格に倒さない）")
    un = b.state.get("unevaluable") or []
    check(len(un) == 1 and un[0]["trigger"] == "purpose_sources_changed", f"測れなかったことが痕跡に残る（{un}）")
    check("source_files" in un[0]["why"], f"何が無くて測れなかったかが書いてある（{un[0].get('why')}）")
    # 条件は 1 回の next で何度も評価される——同じ周で行が増えない
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
    held = lambda name, b: cond_call(conds[name], {"round": b.round, "loop": b.loop_state})[0]
    check(not held("rejudge_open", b) and not held("rejudge_exhausted", b),
          "異議が無ければ往復の節は開かない（常設しない）")
    b.loop_state["rejudge_requested"] = {"round": 2, "text": "前の周の異議"}
    check(not held("rejudge_open", b), "**前の周の**異議では開かない（同じ周の口であって持ち越しではない）")
    b.loop_state["rejudge_requested"] = {"round": 3, "text": "今の周の異議"}
    check(held("rejudge_open", b) and not held("rejudge_exhausted", b), "今の周の異議で往復の節が開く")

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
    check(not held("rejudge_open", b) and held("rejudge_exhausted", b),
          f"上限（{rules.REJUDGE_MAX}）に達すると往復の節は閉じ、第三の目が開く（常設でなくここでだけ立つ）")

    # **上限は run 全体でなく 1 周に掛かる。** 以前は回数が周をまたいで積まれたので、どこか 1 周で使い切ると
    # run の残り全部で往復の節が開かず、新しい異議は 1 回目からいきなり第三の目に行った（＝常設しないという
    # 名乗りが破れる）。**次の周に同じ盤面で異議を出すと、往復がまた開く**ことを見る
    b.round = 4
    b.loop_state["rejudge_requested"] = {"round": 4, "text": "次の周の新しい異議"}
    check(held("rejudge_open", b) and not held("rejudge_exhausted", b),
          "前の周で上限まで往復しても、次の周の異議では往復の節がまた開く（上限は周ごと）")
    checks["rejudge_output"](b, "p2.rejudge", {"verdict": "一部採る", "new_facts": "次の周の争点について現物に当たり、片方だけ確かめられた", "units": []}, None)
    check(b.loop_state["rejudge_rounds"] == {"round": 4, "n": 1}, "周が変わると往復の回数は 1 から数え直す")
    b.round, b.loop_state["rejudge_requested"] = 3, {"round": 3, "text": "今の周の異議"}
    b.loop_state["rejudge_rounds"] = {"round": 3, "n": rules.REJUDGE_MAX}

    # 決着する返答は異議を降ろす
    b2 = types.SimpleNamespace(round=3, loop_state={"rejudge_requested": {"round": 3, "text": "x"}})
    checks["rejudge_output"](b2, "p2.rejudge", {"verdict": "退ける", "new_facts": "現物に当たって再現を試みたが、回す側が挙げた事実は再現しなかったので退ける", "units": []}, None)
    check("rejudge_requested" not in b2.loop_state and not held("rejudge_open", b2),
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
    run = Run("cired", unattended=True, checks=[{"name": "suite", "argv": [PY, "-c", "import sys; print('1 failed'); sys.exit(1)"]}])   # engine が走らせて毎周赤
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
    # engine が起こさない役（graph に launch.tooled が無い）でも、役が自分でファイルを読む渡し方（deliver=path）なら貼る上限で
    # 切らない——上限は Agent ツールに本文を貼る経路の性質（advance.emit_instance の cap の注記）。道具つきの役の指示書に
    # 差分の本文の穴を足した graph の写しで、path の役の本文が末尾まで残るかを見る
    g = json.loads((PLUGIN / "graphs" / "review-loop.json").read_text(encoding="utf-8"))
    del g["launch"]["tooled"]
    g["nodes"]["p1.procedure_trace"]["reads"].append("file:loop.diff_file")
    _td_g, gtmp = parallel.workspace("gl-review-big-path-")
    for sub in ("prompts", "rules"):
        shutil.copytree(PLUGIN / sub, gtmp / sub)
    pt = gtmp / "prompts" / "review-loop" / "p1.procedure_trace.md"
    pt.write_text(pt.read_text(encoding="utf-8") + "\n\n{{file:loop.diff_file}}\n", encoding="utf-8")
    (gtmp / "graphs").mkdir()
    (gtmp / "graphs" / "review-loop.json").write_text(json.dumps(g, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    run = Run("big-path", big=True, graph=gtmp / "graphs" / "review-loop.json")
    seen = {}
    nx = run.next()
    for _ in range(3):
        t = answers(run, "std", 1)
        for i in nx["ready"]:
            seen[i["node"]] = i
            run.done(i["id"], t[i["node"]](load_item(i)))
        nx = run.next()
    pt_inst = seen.get("p1.procedure_trace") or {}
    body = pathlib.Path(pt_inst["prompt_file"]).read_text(encoding="utf-8") if pt_inst else ""
    check(pt_inst.get("deliver") == "path" and not pt_inst.get("launch") and f"ROW_{BIG_ROWS - 1:05d}" in body,
          f"engine が起こさない path の役は、差分の本文を末尾まで受け取る（deliver {pt_inst.get('deliver')}・{len(body.encode('utf-8'))} バイト）")
    rm(run.tmp)
    shutil.rmtree(gtmp, ignore_errors=True)



def test_cond_truth_tables():
    """**条件ごとの真偽表**（graph の cond / applies_cond が名前で指す rules の関数）。

    以前は条件が graph の JSON の上の式で、どの葉が効いているかは台本を通しで回さないと見えなかった。関数にしたので、
    engine と同じ口（run_cond）で文脈を手で組んで直に呼ぶ。表の行は（文脈, 期待）で、期待の "die" は宣言した欄が
    default 無しで解決できないときに落ちること（偽に倒さない）。**CONDS の名前が全部どこかの行に在る**ことも見る
    ——足した条件が表の外に出たら赤くなる"""
    print("条件の真偽表: CONDS の関数を 1 つずつ、真・偽・落ちるの行で当てる")
    import importlib.util  # noqa: E402
    import io  # noqa: E402
    from contextlib import redirect_stderr  # noqa: E402
    sys.path.insert(0, str(PLUGIN))
    from engine.rules import load_rules
    gp = PLUGIN / "graphs" / "review-loop.json"
    rules = load_rules(gp, json.loads(gp.read_text(encoding="utf-8")))
    spec = importlib.util.spec_from_file_location("gl_truth_v", str(VALIDATOR))
    V = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(V)

    def ev(name, ctx):
        buf = io.StringIO()
        try:
            with redirect_stderr(buf):
                return cond_call(rules.CONDS[name], ctx, validator=V, state={"round": ctx.get("round", 1)})[0]
        except SystemExit:
            return "die"

    E = {"request_entry": {"origin": "人の依頼（検査）"}}

    def c(rnd=1, entry=False, loop=None, fix=None, base=None, purpose=None, **extra):
        """文脈を組む: 入口の印・loop・前の周の p3.fix の申告・p0.base の申告・p0.purpose"""
        ctx = {"round": rnd, "record": {"process": dict(E) if entry else {}}, "loop": dict(loop or {}),
               "prev": {"p3.fix": dict(fix)} if fix else {}, "out": {}}
        if base is not None:
            ctx["out"]["p0.base"] = base
        if purpose is not None:
            ctx["out"]["p0.purpose"] = purpose
        for k, v in extra.items():
            ctx[k] = v
        return ctx
    touched = {"prev_fix_files": ["a.py"]}
    ENG = lambda rnd: {"process": {"checks": {"p4.ci": {"round": rnd, "by": "engine"}}}}   # その周の CI を engine が走らせた
    # **前の周の P3 の旗（deps・claims・procedures・gates・seams・path）だけでは起こさない**——旗が真の周は P3 がファイルを
    # 触った周で、prev_fix_touched（touched）が拾う。旗だけが真でファイルが空の行が False なのは、旗が死んだ入力として
    # 条件から外れたことの固定。例外は decision_records_changed（リポジトリの外に書いた周はファイルが空のまま真になりうる）
    quiet = {"touches_security_surface": False, "touches_external_seams": False}
    T = {
        "request_entry": [(c(), False), (c(entry=True), True), (c(entry=True, loop={"request_fixed_at": 1}), False),
                          ({"record": {"process": {"request_entry": "文字列"}}}, False)],
        "not_request_entry": [(c(), True), (c(entry=True), False), (c(entry=True, loop={"request_fixed_at": 1}), True)],
        "purpose_review_due": [(c(), "die"), (c(purpose={"source": "②計画・タスク記述"}), False),
                               (c(purpose={"source": "③writer の要約"}), True), (c(2, purpose={"source": "③writer の要約", "source_files": []}), False),
                               (c(2, loop={"prev_fix_files": ["d.md"]}, purpose={"source": "③writer の要約", "source_files": ["d.md"]}), True),
                               (c(2, purpose={"source": "③writer の要約", "source_files": []},
                                  record={"process": {"purpose_review": {"verdict": "狭めている", "findings": ["素の文字列"]}}}), True)],
        "prior_decisions_due": [(c(), True), (c(2), False), (c(2, fix={"decision_records_changed": True}), True),
                                (c(2, loop=touched), True), (c(2, loop={"escalated": {"round": 2}}), True), (c(2, loop={"escalated": []}), False)],
        "external_standards_due": [(c(), True), (c(entry=True), False), (c(2), False), (c(2, fix={"mechanism_changed": True}), True),
                                   (c(2, fix={"deps_changed": True}), False), (c(2, loop=touched), True), (c(2, entry=True, loop={**touched, "request_fixed_at": 1}), True)],
        "procedure_trace_due": [(c(loop={"changed_files": ["README.md"]}), True), (c(loop={"changed_files": ["a.py"]}), False),
                                (c(2, loop={"changed_files": ["README.md"]}), False),
                                (c(2, loop={"changed_files": ["README.md"]}, fix={"procedures_changed": True}), False),
                                (c(entry=True, loop={"changed_files": ["README.md"]}), False),
                                (c(entry=True, loop={"escalated": {"round": 1}}), True), (c(2, loop=touched), True)],
        "gate_efficacy_due": [(c(base={"touches_gates": True}), True), (c(base={"touches_gates": False}), False),
                              (c(2, base={"touches_gates": True}), False), (c(2, base={"touches_gates": False}, fix={"gates_changed": True}), False),
                              (c(entry=True, base={"touches_gates": True}), False), (c(entry=True, loop={"escalated": {"round": 1}}), True),
                              (c(), "die"), (c(entry=True), False), (c(base={"touches_gates": 1}), True),
                              # 合流でまとめる run（gates=merge）は、ゲートを触った初回の周・前の周の P3 が触った周・昇格した周のどれでも撃たない
                              (c(base={"touches_gates": True}, loop={"gates": "merge"}), False),
                              (c(2, loop={**touched, "gates": "merge"}), False),
                              (c(entry=True, loop={"escalated": {"round": 1}, "gates": "merge"}), False)],
        "test_double_fidelity_due": [(c(base={"touches_external_seams": True}), True), (c(base={"touches_external_seams": False}), False),
                                     (c(2, base={"touches_external_seams": False}, fix={"seams_changed": True}), False),
                                     (c(entry=True, base={"touches_external_seams": True}), False),
                                     (c(entry=True, loop={"escalated": {"round": 1}}), True)],
        "main_path_observation_due": [(c(base={"touches_user_path": True}), True), (c(2, base={"touches_user_path": True}), False),
                                      (c(2, base={"touches_user_path": True}, loop={"last_material": {"main_path_observation": {"status": "awaiting_human"}}}), True),
                                      (c(2, base={"touches_user_path": True}, loop={"last_material": {"main_path_observation": {"status": "clean"}}}), False),
                                      (c(2, base={"touches_user_path": False}, loop=touched), True),
                                      (c(entry=True, base={"touches_user_path": True}, loop={"escalated": {"round": 1}}), False)],
        "provenance_due": [(c(), True), (c(entry=True), False), (c(2), False), (c(2, fix={"claims_changed": True}), False), (c(2, loop=touched), True)],
        "after_first_round": [(c(), False), (c(2), True)],
        "parallel_pr_due": [(c(), True), (c(2), False), (c(2, entry=True, loop={"request_fixed_at": 1}), True),
                            (c(3, entry=True, loop={"request_fixed_at": 1}), False), (c(2, loop={"request_fixed_at": 1}), False)],
        "spec_flow": [(c(), False), (c(loop={"flow": "spec"}), True), (c(loop={"flow": "other"}), False)],
        "spec_revise_due": [(c(loop={"flow": "spec"}, out={"spec.review": {"faces": [{"key": "k"}]}}), True),
                            (c(loop={"flow": "spec"}, out={"spec.review": {"faces": []}}), False),
                            (c(loop={"flow": "spec"}), False), (c(out={"spec.review": {"faces": [{"key": "k"}]}}), False)],
        "gates_cut_nonempty": [(c(2, loop={"gates_cut": {"round": 2, "files": ["a.py"]}}), True),
                               (c(2, loop={"gates_cut": {"round": 1, "files": ["a.py"]}}), False),
                               (c(2, loop={"gates_cut": {"round": 2, "files": []}}), False), (c(2), False)],
        "would_converge": [(c(2, cur={"p4.record": {"branch": "converged"}}, record={"materials": {"local_checks": {"status": "clean"}}, **ENG(2)}), True),
                           (c(2, cur={"p4.record": {"branch": "converged"}}, record={"materials": {"local_checks": {"status": "clean"}}}), False),
                           (c(2, cur={"p4.record": {"branch": "converged"}}, record={"materials": {"local_checks": {"status": "clean"}},
                                                                                    "process": {"checks": {"p4.ci": {"round": 2, "by": "role"}}}}), False),
                           (c(2, cur={"p4.record": {"branch": "converged"}}, record={"materials": {"local_checks": {"status": "clean"}}, **ENG(1)}), False),
                           (c(2, cur={"p4.record": {"branch": "converged"}}, record={"materials": {"local_checks": {"status": "found"}}}), False),
                           (c(2, cur={"p4.record": {"branch": "next_round"}}, record={"materials": {"local_checks": {"status": "clean"}}}), False),
                           (c(2, record={"materials": {"local_checks": {"status": "clean"}}}), False),
                           (c(2, cur={"p4.record": {"branch": "converged"}}, record={"materials": {}}), False)],
        "gates_merge": [(c(), False), (c(loop={"gates": "merge"}), True), (c(loop={"gates": "other"}), False)],
        "lane_due": [(c(2, loop={"gates_cut": {"round": 2, "files": ["a.py"]}}), True),
                     (c(2, loop={"gates": "merge", "gates_cut": {"round": 2, "files": ["a.py"]}}), False),
                     (c(2, loop={"gates_cut": {"round": 2, "files": []}}), False)],
        "final_gate_due": [(c(2, cur={"p4.record": {"branch": "converged"}}, record={"materials": {"local_checks": {"status": "clean"}}, **ENG(2)}), True),
                           (c(2, loop={"gates": "merge"}, cur={"p4.record": {"branch": "converged"}},
                              record={"materials": {"local_checks": {"status": "clean"}}, **ENG(2)}), False),
                           (c(2, cur={"p4.record": {"branch": "next_round"}}, record={"materials": {"local_checks": {"status": "clean"}}}), False)],
        "units_open": [(c(record={"units": []}), False), (c(record={"units": [{"label": "block"}]}), True),
                       (c(record={"units": [{"label": "suggest", "disposition": "defer"}]}), False),
                       (c(record={"units": [{"label": "suggest", "disposition": "do-now"}]}), True)],
        "fix_delta_nonempty": [(c(2, loop={"fix_delta": {"round": 2, "files": ["a.py"]}}), True),
                               (c(2, loop={"fix_delta": {"round": 1, "files": ["a.py"]}}), False), (c(2), False)],
        "delta_review_due": [(c(2, loop={"fix_delta": {"round": 2, "files": ["a.py"]}}), True),
                             (c(2, cur={"p3.fix": {"plan_faces": [{"key": "k", "handled": "absorbed"}]}}), True),
                             (c(2, cur={"p3.fix": {"plan_faces": [{"key": "k", "handled": "declared"}]}}), False)],
        "delta_review2_due": [(c(2, loop={"fix_delta2": {"round": 2, "files": ["a.py"]}}), True),
                              (c(2, cur={"p3.delta_fix": {"handled": [{"key": "k", "handled": "fixed"}]}}), True), (c(2), False)],
        "delta_faces_open": [(c(2, loop={"delta_owed": {"round": 2, "rows": [{"key": "k"}]}}), True),
                             (c(2, loop={"delta_owed": {"round": 1, "rows": [{"key": "k"}]}}), False),
                             (c(2, loop={"delta_owed": {"round": 2, "rows": []}}), False)],
        "delta2_faces_open": [(c(2, loop={"delta_owed2": {"round": 2, "rows": [{"key": "k"}]}}), True), (c(2), False)],
        "delta_fixed": [(c(2, cur={"p3.delta_fix": {"handled": [{"key": "k", "handled": "fixed"}]}}), True),
                        (c(2, cur={"p3.delta_fix": {"handled": [{"key": "k", "handled": "declared"}]}}), False), (c(2), False)],
        "r1_refire": [(c(), True), (c(loop={"r1_refire": False}), False), (c(loop={"r1_refire": True}), True)],
        "r2_design_due": [(c(), True), (c(loop={"r2_refire": False}), False), (c(loop={"purpose_known": False}), False)],
        "r2_compare_due": [(c(), False), (c(out={"r2.design": {"question_stands": True}}), True),
                           (c(out={"r2.design": {"question_stands": True}}, loop={"r2_refire": False}), False),
                           (c(out={"r2.design": {"question_stands": True}}, loop={"purpose_known": False}), False)],
        "overview_due": [(c(), True), (c(loop={"open_units": 2}), False), (c(loop={"open_units": 2, **touched}), True)],
        "r2_premise_invalid": [(c(), False), (c(record={"reviews": {"R2": {"status": "premise-invalid"}}}), True),
                               (c(record={"reviews": {"R2": {"status": "pass"}}}), False)],
        "rejudge_open": [(c(3), False), (c(3, loop={"rejudge_requested": {"round": 3}}), True),
                         (c(3, loop={"rejudge_requested": {"round": 3}, "rejudge_rounds": {"round": 3, "n": 3}}), False)],
        "rejudge_exhausted": [(c(3, loop={"rejudge_requested": {"round": 3}}), False),
                              (c(3, loop={"rejudge_requested": {"round": 3}, "rejudge_rounds": {"round": 3, "n": 3}}), True)],
        "touches_procedures": [(c(loop={"changed_files": ["scripts/x.py"]}), True), (c(loop={"changed_files": ["a.py"]}), False), (c(), False)],
        "gates_touched": [(c(base={"touches_gates": True}), True), (c(base={"touches_gates": False}, fix={"gates_changed": True}), True),
                          (c(base={"touches_gates": False}), False)],
        "seams_touched": [(c(base={"touches_external_seams": True}), True), (c(base={"touches_external_seams": False}), False)],
        "user_path_touched": [(c(base={"touches_user_path": True}), True), (c(base={"touches_user_path": False}, fix={"path_changed": True}), True),
                              (c(base={"touches_user_path": False}), False)],
        # 申告の欄が無い盤面（欄を足す前に once の p0.base を終えた）は当てる側に倒す——落とさず、取りこぼしもしない。
        # 継ぎ目の申告だけが真でも、前の前の周の修正の申告でも当てる
        "security_surface_touched": [(c(base={**quiet, "touches_security_surface": True}), True),
                                     (c(base=quiet, fix={"security_surface_changed": True}), True),
                                     (c(base={**quiet, "touches_external_seams": True}), True),
                                     (c(3, base=quiet, record={"process": {"fixes": [{"round": 1, "seams_changed": True}, {"round": 2}]}}), True),
                                     (c(3, base=quiet, record={"process": {"fixes": [{"round": 1, "security_surface_changed": True}]}}), True),
                                     (c(base=quiet), False), (c(base={}), True)],
    }
    for name, rows in T.items():
        for i, (ctx, want) in enumerate(rows):
            got = ev(name, ctx)
            check(got == want, f"{name} の行 {i}: 期待 {want}・実際 {got}")
    check(set(rules.CONDS) <= set(T), f"CONDS の名前が全部真偽表に在る（表に無い: {sorted(set(rules.CONDS) - set(T))}）")
    st = {"round": 1}
    got = cond_call(rules.CONDS["security_surface_touched"], c(base={}), state=st)
    check(got[0] and "欄が無い" in got[1] and [u["trigger"] for u in st.get("unevaluable", [])] == ["security_surface_touched"],
          f"申告の欄が無い盤面は当てる側に倒し、倒したことを理由の文と測れなかった痕跡に残す（{got}・{st}）")
    # 理由の文は空でない（走らなかった節の素材の理由として判定役に渡る）——run_cond が空を拒むのと同じ所を、真偽の両側で踏む
    why = cond_call(rules.CONDS["provenance_due"], c(2), validator=V)[1]
    check("成り立たない" in why and "round=2" in why, f"理由の文は評価に使った事実を運ぶ（{why}）")
    # 入口の印を外す重ね書き（ENTRY_OFF）は、入口の周の文脈でも入口の項だけを外す（盤面の値は書き換えない）
    ctx = c(entry=True)
    f = rules.CONDS["external_standards_due"]
    before = json.dumps(ctx, sort_keys=True, default=str)
    check(not cond_call(f, ctx)[0] and cond_call(f, ctx, overlay=rules.ENTRY_OFF)[0] and json.dumps(ctx, sort_keys=True, default=str) == before,
          "入口の印を外した文脈では、入口の周でも残りの条件だけで真偽が決まる（文脈は書き換えない）")
    # 宣言の外を読めば落ちる・default 無しの未解決は落ちる・返りの形が違えば落ちる（engine の入れ物の規律）
    sys.path.insert(0, str(PLUGIN))
    from engine.rules import cond_reads
    buf = io.StringIO()
    for fn, want, desc in ((cond_reads("round")(lambda v: (bool(v("loop.x", 0)), "x")), "宣言していない欄", "入れ物: 宣言の外の欄を読むと落ちる"),
                           (cond_reads("loop.x")(lambda v: (bool(v("loop.x")), "x")), "解決できない", "入れ物: default 無しの未解決は落ちる"),
                           (cond_reads("round")(lambda v: True), "（真偽, 理由の文）でない", "入れ物: 返りが組でなければ落ちる"),
                           (cond_reads("round")(lambda v: (True, " ")), "（真偽, 理由の文）でない", "入れ物: 理由の文が空なら落ちる"),
                           (lambda v: (True, "x"), "読む欄を宣言していない", "入れ物: 読む欄の宣言が無ければ落ちる")):
        buf.seek(0), buf.truncate()
        try:
            with redirect_stderr(buf):
                cond_call(fn, c())
            got = "通った"
        except SystemExit:
            got = buf.getvalue()
        check(want in got, f"{desc}（{got.strip()[:80]}）")
    check(cond_call(cond_reads("loop.x")(lambda v: (v("loop.x.y", 7) == 7, "x")), c())[0], "宣言した欄の下の欄も読め、未解決なら default を返す")
    # 重ね書きした path の下の欄は重ね書きの値だけで引く——引けなければ default（盤面の本物の値へ落ちない）
    over = cond_reads("loop.x")(lambda v: (v("loop.x.b", "既定") == "既定", "x"))
    check(cond_call(over, c(loop={"x": {"a": 1, "b": 5}}), overlay={"loop.x": {"a": 2}})[0],
          "入れ物: 重ね書きの下で引けない欄は default を返し、盤面の値（b=5）を見せない")
    # 入れ物の内部の欄を自然な綴り（v._ctx 等）で直に読むと落ちる——宣言の検査をすり抜けない
    for attr in ("_ctx", "_state", "_overlay", "_validator", "_reads", "_name"):
        try:
            cond_call(cond_reads("round")(lambda v, a=attr: (bool(getattr(v, a)), "x")), c())
            got = "通った"
        except AttributeError:
            got = "AttributeError"
        check(got == "AttributeError", f"入れ物: 内部の欄 v.{attr} を直に読むと落ちる（{got}）")
    # 検証器は読むときに引く: 検証器の無い run で検証器を読む条件は Reject で落ち（loop.py が制御された拒否として出す）、
    # 読まない条件は評価できる。以前 V=None に倒していたとき、units_open が素の AttributeError で落ちた（2026-09-25 修正差分のレビュー）
    from engine.util import Reject

    def no_validator():
        raise Reject("検証器（scripts/<loop>-record.py）が見つからない（検査用）")
    try:
        cond_call(rules.CONDS["units_open"], c(record={"units": [{"label": "block"}]}), validator=no_validator)
        got = "通った"
    except Exception as e:  # noqa: BLE001 — 型名で見る（rules に差し込まれた Reject と同じ実体）
        got = type(e).__name__
    check(got == "Reject", f"検証器の無い run: 検証器を読む条件は Reject で落ちる（{got}）")
    check(cond_call(rules.CONDS["after_first_round"], c(2), validator=no_validator)[0], "検証器の無い run: 検証器を読まない条件は評価できる")


def test_final_gate_empty_asks_human():
    """最後の関門が撃てた腕 0 本を返したら、収束を言わずに人に諮る。continue の答えで次の周の同じ木の関門が通り、収束する"""
    print("最後の関門の 0 本: 人に諮り、continue なら同じ木で収束する")
    run = Run("gate-empty")

    def empty(run_, inst, out):
        if inst["node"] == "p4.final_gates":
            return {**out, "arms": [], "handled": []}
        return None
    last = drive(run, "std", hook=empty)
    check(last["status"] == "awaiting_human" and (last.get("ask") or {}).get("kinds") == ["final_gate_empty"],
          f"撃てた腕が 0 本の関門で収束を言わず人に諮る（{last['status']} {(last.get('ask') or {}).get('kinds')}）")
    check(run.state()["loop"].get("stop_reason") == "final_gate_empty",
          f"諮る前に止めた理由（stop_reason）を立てる——stop や無人の停止でも理由が残る（{run.state()['loop'].get('stop_reason')}）")
    asked_round = run.state()["round"]
    r = run.cmd("answer", "--text", "continue", "--note", "文書だけの差分と確かめた（検査用）")
    check(r.returncode == 0, f"continue を返す（{r.stderr[-160:]}）")
    last = drive(run, "std", hook=empty)
    check(last["status"] == "converged", f"人が認めた木なら、次の周の 0 本の関門で収束する（{last['status']}）")
    rm(run.tmp)
    # 上限の周で 0 本になった: continue は上限を 1 周だけ延ばし、同じ木の関門を撃つ次の周で収束する
    run = Run("gate-empty-max")
    mx = run.tmp / "max.json"
    mx.write_text(json.dumps(asked_round), encoding="utf-8")
    run.cmd("patch", "--path", "state.max_rounds", "--file", str(mx), "--reason", "台本: 上限の周で 0 本にする")
    last = drive(run, "std", hook=empty)
    check(last["status"] == "awaiting_human" and (last.get("ask") or {}).get("kinds") == ["final_gate_empty"],
          f"上限の周でも 0 本の関門は人に諮る（{(last.get('ask') or {}).get('kinds')}）")
    run.cmd("answer", "--text", "continue", "--note", "確かめた（検査用）")
    st = run.state()
    ans = (run.record()["process"].get("human_answers") or [{}])[-1]
    check(st["max_rounds"] == asked_round + 1 and ans.get("max_rounds") == {"from": asked_round, "to": asked_round + 1},
          f"上限の周の continue は上限を 1 周だけ延ばし、答えの記録に延ばした値を書く（{st['max_rounds']} {ans.get('max_rounds')}）")
    last = drive(run, "std", hook=empty)
    check(last["status"] == "converged", f"延ばした次の周で、同じ木の 0 本の関門が通って収束する（{last['status']}）")
    rm(run.tmp)


def test_relaunch_delegate():
    """任せ先の付いた節（delegate）は回す側の runner でも起こし直せる——任せ先が書かずに返った・落ちた回の出口。
    任せ先の無い runner（回す側の判断そのもの）は起こし直さない"""
    print("起こし直し: 任せ先の付いた節は起こし直せ、回す側が自分でやる節は拒む")
    run = Run("relaunch-delegate")
    nx = run.next()
    ids = {i["node"]: i["id"] for i in nx["ready"]}
    r = run.cmd("relaunch", "--node", ids["p0.local_checks"], "--reason", "任せ先が書かずに返った（検査用）")
    me = run.state()["rounds"][-1]["instances"][ids["p0.local_checks"]]
    check(r.returncode == 0 and me.get("attempts") == 2, f"任せ先の付いた節は起こし直せる（rc={r.returncode} {r.stderr.strip()[-100:]}）")
    r = run.cmd("relaunch", "--node", ids["p0.base"], "--reason", "検査用")
    check(r.returncode == 1 and "他へ渡して待っている" in r.stderr, f"任せ先の無い runner の節は起こし直さない（{r.stderr.strip()[-80:]}）")
    rm(run.tmp)


def loop_shape_held(run, what):
    """通しで回した盤面の loop が graph の state_schema から外れていない（engine が保存の時に照らした痕跡 loop_drift が 0 件）。
    0 件が照らさなかった結果でないことも見る: 盤面の graph が state_schema を持つ"""
    from engine.schema import load_graph
    st = run.state()
    g, _ = load_graph(st["graph"])
    check(isinstance((g or {}).get("state_schema"), dict) and not st.get("loop_drift"),
          f"{what}: 盤面の loop が state_schema の形に収まる（照らした graph に宣言が在る={isinstance((g or {}).get('state_schema'), dict)}・"
          f"外れ {[r.get('error') for r in st.get('loop_drift') or []][:3]}）")


def literal_loop_writes(*names):
    """rules の本文に字面で書かれた loop の鍵（ls["X"] = ・loop_state["X"] = ・setdefault("X")）"""
    src = "".join((PLUGIN / "rules" / f"{n}.py").read_text(encoding="utf-8") for n in names)
    return {a or b for a, b in re.findall(r'(?:ls|loop_state)(?:\[\s*"([a-z_0-9]+)"\s*\]\s*=[^=]|\.setdefault\(\s*"([a-z_0-9]+)")', src)}


def test_loop_keys_declared():
    """**rules が盤面の loop に書いた鍵は、全部 LOOP_KEYS に宣言されている。** graphcheck は条件の読む loop.<鍵> を
    この宣言と突き合わせるので、宣言が書く側から離れると、正しい条件が落ちるか綴り違いが通る。回した盤面の鍵で確かめる。
    形（graph の state_schema）も、回した盤面が外れていないことを engine の保存の時の痕跡で確かめる"""
    print("loop の鍵の宣言: 通しで回した盤面の loop の鍵が、全部 rules の LOOP_KEYS に在り、graph の state_schema の形に収まる")
    sys.path.insert(0, str(PLUGIN))
    from engine.rules import load_rules
    gp = PLUGIN / "graphs" / "review-loop.json"
    rules = load_rules(gp, json.loads(gp.read_text(encoding="utf-8")))
    run = Run("loopkeys")
    drive(run, "std")
    keys = set(run.state().get("loop") or {})
    check(len(keys) >= 20 and keys <= set(rules.LOOP_KEYS), f"盤面の loop の鍵 {len(keys)} 件が全部宣言に在る（宣言の外: {sorted(keys - set(rules.LOOP_KEYS))}）")
    loop_shape_held(run, "既定の流れ")
    # 照らしが効いていること: 形を外した値を盤面の手当てで書くと、保存の時に痕跡が出て、run は止まらない
    bad = run.tmp / "bad-gates.json"
    bad.write_text("5", encoding="utf-8")
    r = run.cmd("patch", "--path", "state.loop.gates", "--file", str(bad), "--reason", "検査: loop の形を外す")
    drift = [x.get("error", "") for x in run.state().get("loop_drift") or []]
    check(r.returncode == 0 and any("loop.gates" in e for e in drift), f"形を外した書き込みは保存の時に痕跡に残り、止めない（rc={r.returncode}・{drift[:2]}）")
    rm(run.tmp)
    # 仕様の道（flow=spec）の盤面も: 承認待ち・周の途中の答え・承認後のテストの改変の鍵
    run = Run("loopkeys-spec", init_args=("--input", "flow=spec"))
    drive(run, "spec")
    seen = set(run.state().get("loop") or {})
    run.cmd("answer", "--text", "continue")

    def weaken(run_, inst, out):
        if inst["node"] == "p3.fix" and run_.state()["round"] == 1:
            f = run_.repo / SPEC_TESTS["AC1"][0]
            f.write_text(f.read_text(encoding="utf-8") + "# 承認の後に変えた\n", encoding="utf-8")
            seen.update(run_.state().get("loop") or {})
        return None
    drive(run, "spec", hook=weaken)
    seen |= set(run.state().get("loop") or {})
    check({"spec_pending", "in_round_answers", "spec_changed"} <= seen and seen <= set(rules.LOOP_KEYS),
          f"仕様の道の盤面の loop の鍵も全部宣言に在る（宣言の外: {sorted(seen - set(rules.LOOP_KEYS))}）")
    loop_shape_held(run, "仕様の道")
    rm(run.tmp)
    # 逆向き: 宣言の鍵は全部 rules のどこかで書かれている（宣言だけ残った古い鍵を、条件が default 付きで読む形を残さない）。
    # 台本が通らない分岐（昇格・往復）で書く鍵もあるので、書く字面で見る。修正差分の往復の鍵は DELTA_PASSES から組む
    dyn = {k for p in rules.DELTA_PASSES.values() for k in (p.state_key, p.owed_key)}
    # 逆向きも字面で: rules の本文が書く鍵は全部宣言に在る（通しの台本が通らない分岐——人の方針の変化・昇格——で書いて消える鍵も拾う）。
    # TDD の版は元の rules に足すので元の本文も合わせて見る。research は周ごとに名前の変わる控え（sampled_r<周>）を state_schema の型で持つ
    for names, gname in ((("review-loop",), "review-loop"), (("review-loop", "review-loop-tdd"), "review-loop-tdd"), (("research-loop",), "research-loop")):
        gpath = PLUGIN / "graphs" / f"{gname}.json"
        r_ = load_rules(gpath, json.loads(gpath.read_text(encoding="utf-8")))
        wrote = literal_loop_writes(*names)
        declared = set(r_.LOOP_KEYS)
        unwritten = sorted(declared - wrote - dyn)
        check(not unwritten, f"{gname}: LOOP_KEYS の鍵は全部 rules が書いている（書く所の無い宣言: {unwritten}）")
        check(len(wrote) >= 4 and wrote <= declared, f"{gname}: rules が字面で書く loop の鍵 {len(wrote)} 件は全部 LOOP_KEYS に在る（宣言の外: {sorted(wrote - declared)}）")
# ---------------------------------------------------------------- 仕様の道（init --input flow=spec）
SPEC_TESTS = {  # 受け入れ条件のテスト（台本のリポジトリに書く）。修正（p3.fix の台本が src/a.py に足す 1 行）が入ると緑になる
    "AC1": ("tests/test_spec_entry.py", "ac_entry_starts_at_judge",
            "判定から入る run は、修正が入るまで P1 の役を起こさない"),
    "AC2": ("tests/test_spec_p1_returns.py", "ac_p1_runs_after_fix",
            "2 周目以降は P1 を通常どおり走らせる"),
}


def spec_row(run, key, req):
    """受け入れ条件 1 件——テストを台本のリポジトリに書き、置き場と呼び方だけを返す（本文は返答に写さない）"""
    rel, name, then = SPEC_TESTS[key]
    f = run.repo / rel
    f.parent.mkdir(exist_ok=True)
    # 走ったら作業ツリーの外（台本の一時ディレクトリ）に印を足す——承認の前に engine が走らせていないことを台本が見る
    ran = run.tmp / f"spec-ran-{key}"
    f.write_text(f"# {name}\n# Given 判定から入る run  When 修正が入った  Then {then}（検査用）\n"
                 f"import pathlib, sys\nopen({str(ran)!r}, 'a').write('ran\\n')\n"
                 "sys.exit(0 if 'fixed' in pathlib.Path('src/a.py').read_text(encoding='utf-8') else 1)\n",
                 encoding="utf-8")
    return {"key": key, "requirement": req, "file": rel, "name": name, "run": f'"{PY}" {rel}'}


def spec_table(run, scenario):
    """仕様の道の節の台本。最初の仕様は特別周（2026-09-25）の抜け——2 周目以降は P1 を通常どおり走らせる——を持たない"""
    v1 = lambda: {"requirements": [{"key": "R1", "text": "判定から入る run は修正が入るまで P1 を起こさない"}],
                  "acceptance": [spec_row(run, "AC1", "R1")], "out_of_scope": []}
    face = {"key": "p1-after-fix", "kind": "missing", "where": "requirements",
            "why": "2 周目以降は P1 を通常どおり走らせる、という条件が無い——入口が run の最後まで P1 を外したままでも全部の受け入れ条件が通る"}
    return {
        "spec.write": lambda it: v1(),
        "spec.review": lambda it: {"faces": [face], "reason": "要件を周をまたいだ振る舞いと突き合わせた（検査用）"},
        "spec.revise": lambda it: {"spec": {**v1(), "requirements": v1()["requirements"] + [{"key": "R2", "text": "2 周目以降は P1 を通常どおり走らせる"}],
                                            "acceptance": [spec_row(run, "AC1", "R1"), spec_row(run, "AC2", "R2")]},
                                   "handled": [{"key": face["key"], "handled": "absorbed", "how": "要件 R2 と受け入れ条件 AC2（tests/test_spec_p1_returns.py）を足した"}]},
    }


def test_spec_flow():
    """**仕様の道**（init --input flow=spec）: 仕様を書く → 審査が抜けを挙げる → 答えずに直すと拒まれる → 足して直す →
    承認の前に受け入れ条件のテストが赤と実測される → 人の承認（周の途中の問い）で同じ周のまま進む → 受け入れ条件が記録に
    固定され、判定のプロンプトに届く → 修正でテストが緑になり、検証器を通って収束する"""
    print("仕様の道: 審査が特別周の抜けを拾い、承認で同じ周のまま判定に届く")
    run = Run("spec", init_args=("--input", "flow=spec"))
    check(run.init.returncode == 0, f"仕様の道: init が通る（{run.init.stderr[-200:]}）")
    seen = {}

    def hook(run_, inst, out):
        if inst["node"] == "spec.write" and "write" not in seen:
            bad = {**out, "acceptance": [{**out["acceptance"][0], "file": "tests/no_such.py"}]}
            r = run_.done(inst["id"], bad)
            seen["write"] = (r.returncode, r.stderr)
            r = run_.done(inst["id"], {**out, "acceptance": [{**out["acceptance"][0], "file": "src/a.py", "name": "def f"}]})
            seen["gwt"] = (r.returncode, r.stderr)
        if inst["node"] == "spec.review" and "review" not in seen:
            r = run_.done(inst["id"], {"faces": [], "reason": "穴は無いと見た（検査用。何を確かめたかを書かない）"})
            seen["review"] = (r.returncode, r.stderr)
        if inst["node"] == "spec.revise" and "revise" not in seen:
            r = run_.done(inst["id"], {**out, "handled": []})
            seen["revise"] = (r.returncode, r.stderr)
        if inst["node"] == "p2.diagnose" and run_.state()["round"] == 1:
            seen["diagnose_prompt"] = pathlib.Path(inst["prompt_file"]).read_text(encoding="utf-8")
        return None
    # 柵が効かずに悪い返答が受理された回も、下の検査まで届かせる（drive の例外で台本ごと抜けると、どの柵かが検査の名前に出ない）
    try:
        last = drive(run, "spec", hook=hook)
    except RuntimeError as e:
        last = {"status": f"drive が例外で抜けた: {str(e)[:160]}", "ask": {}}
    check(seen.get("write", (0,))[0] == 1 and "読めない" in seen["write"][1],
          f"仕様の道: 受け入れ条件のテストのファイルが無い仕様は拒む（{seen.get('write', ('', ''))[1][-160:]}）")
    check(seen.get("gwt", (0,))[0] == 1 and "Given" in seen["gwt"][1],
          f"仕様の道: Given/When/Then を持たないテストを受け入れ条件にした仕様は拒む（{seen.get('gwt', ('', ''))[1][-160:]}）")
    check(seen.get("review", (0,))[0] == 1 and "faces_none" in seen["review"][1],
          f"仕様の道: 穴を挙げない審査は、何を確かめて無いと言えるかを書かないと拒む（{seen.get('review', ('', ''))[1][-160:]}）")
    check(seen.get("revise", (0,))[0] == 1 and "p1-after-fix" in seen["revise"][1],
          f"仕様の道: 審査の穴に答えない直しは拒む（{seen.get('revise', ('', ''))[1][-160:]}）")
    st = run.state()
    check(last["status"] == "awaiting_human" and last["ask"].get("in_round") and last["ask"]["kinds"] == ["spec_approval"],
          f"仕様の道: 承認で人に聞く（周の途中の問い。{last.get('ask', {}).get('kinds')}）")
    items = "\n".join(last.get("ask", {}).get("items") or [])
    check("AC2" in items and "承認の前には走らせていない" in items and SPEC_TESTS["AC2"][0] in items and "p1-after-fix" in items,
          f"仕様の道: 承認の問いに、足した受け入れ条件・走らせるコマンドの字面・審査の穴が載る（{items[:300]}）")
    check(not list(run.tmp.glob("spec-ran-*")),
          f"仕様の道: 受け入れ条件の run は承認の前に走らない（人が字面を見る前に engine の中で走らせない。{sorted(x.name for x in run.tmp.glob('spec-ran-*'))}）")
    check(not any(i["node"].startswith("p1.") or i["node"].startswith("p2.") for i in st["rounds"][0]["instances"].values()),
          "仕様の道: 承認の前に P1・P2 の節は出ない")
    opts = run.tmp / "opts.json"
    opts.write_text(json.dumps(["continue", "stop", "escalate"]), encoding="utf-8")
    run.cmd("patch", "--path", "state.pending_human.options", "--file", str(opts), "--reason", "台本: 手当てで escalate が混ざった問い")
    r = run.cmd("answer", "--text", "escalate")
    check(r.returncode == 1 and "周の途中の問い" in r.stderr,
          f"仕様の道: 周の途中の問いに escalate は無い——手当てで選択肢に混ざっても答えの側で拒む（{r.stderr[-120:]}）")
    r = run.cmd("answer", "--text", "continue", "--note", "承認（検査用の目印 APPROVE-5c1）")
    check(r.returncode == 0, f"仕様の道: 承認を返す（{r.stderr[-160:]}）")
    st = run.state()
    check(st["round"] == 1 and "spec.approve" in st["rounds"][0]["done"], f"仕様の道: 承認の後も同じ周のまま（round {st['round']}）")
    last = drive(run, "spec", hook=hook)
    rec = run.record()
    spec = rec["process"].get("spec") or {}
    acs = {a["key"]: a for a in spec.get("acceptance") or []}
    check(set(acs) == {"AC1", "AC2"} and all(a["exit_at_approval"] == 1 and len(a["sha256"] or "") == 64 for a in acs.values()),
          f"仕様の道: 受け入れ条件が置き場・sha・承認の時点（承認の直後に走らせた）の赤とともに記録に固定される（{sorted(acs)}）")
    check("APPROVE-5c1" in json.dumps(spec.get("approval"), ensure_ascii=False)
          and not any("APPROVE-5c1" in (a.get("note") or "") for a in rec["process"]["human_answers"]),
          "仕様の道: 承認の答えは仕様の記録に残り、CI への指示として読まれる human_answers には積まない")
    check(not any("Given" in json.dumps(a, ensure_ascii=False) for a in acs.values()),
          "仕様の道: 受け入れ条件の本文（Given/When/Then）は記録に写さない")
    prompt = seen.get("diagnose_prompt", "")
    check("tests/test_spec_p1_returns.py" in prompt and "仕様（人が承認した受け入れ条件" in prompt
          and prompt.count("テストの本文は writer が書き、人は承認しただけ") == 2,
          "仕様の道: 承認した受け入れ条件は、1 周目の判定のプロンプトの既存の穴（人の修正依頼）に、1 件ごとに出どころ（writer が書き人が承認）つきで載る")
    check(last["status"] == "converged", f"仕様の道: 修正で受け入れ条件が緑になり収束する（{last['status']}）")
    check(sum(1 for b_ in rec["process"].get("request_history", []) + rec["process"].get("request_findings", [])
              if b_["origin"].startswith("仕様")) == 1, "仕様の道: 受け入れ条件のバッチは承認の周に 1 度だけ積む")
    v = subprocess.run([PY, str(VALIDATOR), str(run.dir / "rounds")], capture_output=True, text=True, encoding="utf-8", timeout=600)
    check(v.returncode == 0 and (run.dir / "rounds" / "round-1.json").is_file(), "仕様の道: 承認で周を消費しない——round-1.json から連番で検証器を通る")
    rm(run.tmp)


def test_spec_stop_and_changes():
    """仕様の道の終わり方と改変: 承認を stop すると後の節を 1 つも出さない（halted）・無人でも承認で止まる・
    承認の後にテストのファイルが変わると、修正の後に人に諮り直す・知らない flow は init で拒む"""
    print("仕様の道: stop と無人で止まる・承認後のテストの改変を諮る・知らない flow を拒む")
    run = Run("spec-stop", init_args=("--input", "flow=spec"))
    drive(run, "spec")
    r = run.cmd("answer", "--text", "stop", "--note", "仕様を直してから")
    check(r.returncode == 0, "仕様の道: stop を返す")
    last = run.next()
    st = run.state()
    check(last["status"] == "stopped" and last.get("halted", {}).get("node") == "spec.approve" and not last["ready"],
          f"仕様の道: stop で run がその場で止まり、後の節を出さない（{last.get('halted')}）")
    check("p1.worktree_before" not in st["rounds"][0]["done"] and "spec" not in run.record()["process"],
          "仕様の道: 承認されていない仕様は固定されず、P1 は始まらない")
    req = run.tmp / "halted-req.json"
    req.write_text(json.dumps([{"where": "src/a.py", "text": "止めた run への依頼（検査用）"}], ensure_ascii=False), encoding="utf-8")
    r = run.cmd("launch")
    check(r.returncode == 1, f"仕様の道: stop で止めた run の launch は拒む（{r.stderr.strip()[-100:]}）")
    for args, desc in ((("done", "--node", "p0.base"), "done"), (("add", "--file", str(req), "--reason", "検査用"), "add"),
                       (("skip", "--node", "p1.gate_efficacy", "--reason", "検査用"), "skip")):
        r = run.cmd(*args)
        check(r.returncode == 1 and "halted" in r.stderr, f"仕様の道: stop で止めた run の {desc} は拒む（{r.stderr.strip()[-100:]}）")
    fix = run.tmp / "halted-note.json"
    fix.write_text(json.dumps("手当て（検査用）", ensure_ascii=False), encoding="utf-8")
    r = run.cmd("patch", "--path", "process.halted_note", "--file", str(fix), "--reason", "検査用")
    check(r.returncode == 0 and run.record()["process"].get("halted_note") == "手当て（検査用）",
          f"仕様の道: stop で止めた run でも手当て（patch）は通る（{r.stderr.strip()[-100:]}）")
    rm(run.tmp)

    # 承認の直後に走らせて既に緑の受け入れ条件は、赤を見ていないと判定役へ渡る
    run = Run("spec-green", init_args=("--input", "flow=spec"))
    drive(run, "spec")
    a_py = run.repo / "src" / "a.py"
    a_py.write_text(a_py.read_text(encoding="utf-8") + "# fixed（検査用: 承認の時点で緑）\n", encoding="utf-8")
    run.cmd("answer", "--text", "continue")
    run.next()
    texts = [f["text"] for x in run.record()["process"].get("request_findings") or [] for f in x["findings"]]
    check(texts and all("赤を見ていない" in s for s in texts), f"仕様の道: 承認の時点で緑の受け入れ条件は『赤を見ていない』と判定役へ渡る（{[s[-60:] for s in texts]}）")
    rm(run.tmp)

    # rules の入口が die（SystemExit）で抜けても、init は置き場を残さない
    _td3, gtmp = parallel.workspace("gl-review-initdie-")
    for sub in ("prompts", "rules", "graphs"):
        shutil.copytree(PLUGIN / sub, gtmp / sub)
    rp = gtmp / "rules" / "review-loop.py"
    rp.write_text(rp.read_text(encoding="utf-8").replace("    mutation_decl(b)\n", "    raise SystemExit(2)\n    mutation_decl(b)\n", 1), encoding="utf-8")
    run = Run("init-die", graph=gtmp / "graphs" / "review-loop.json")
    check(run.init.returncode == 2 and not run.dir.exists(), f"init: rules の入口が die で抜けても置き場を残さない（rc={run.init.returncode} {run.dir.exists()}）")
    rm(run.tmp)
    rm(gtmp)

    run = Run("spec-unattended", unattended=True, init_args=("--input", "flow=spec"))
    last = drive(run, "spec")
    st = run.state()
    check(last["status"] == "stopped" and (st.get("halted") or {}).get("by") == "unattended"
          and not any(i["node"].startswith("p1.") for i in st["rounds"][0]["instances"].values()),
          f"仕様の道: 無人では承認で止まり、P1 を出さない（{st.get('halted')}）")
    rm(run.tmp)

    run = Run("spec-changed", init_args=("--input", "flow=spec"))
    drive(run, "spec")
    run.cmd("answer", "--text", "continue")

    def weaken(run_, inst, out):
        if inst["node"] == "p3.fix" and run_.state()["round"] == 1:
            f = run_.repo / SPEC_TESTS["AC2"][0]
            f.write_text(f.read_text(encoding="utf-8").replace("else 1", "else 0"), encoding="utf-8")
        return None
    last = drive(run, "spec", hook=weaken)
    check(last["status"] == "awaiting_human" and last["ask"]["kinds"] == ["spec_changed"] and last["ask"].get("in_round")
          and SPEC_TESTS["AC2"][0] in "".join(last["ask"]["items"]),
          f"仕様の道: 承認の後に受け入れ条件のテストが変わると、修正の後に人に諮る（{last.get('ask', {}).get('kinds')}）")
    run.cmd("answer", "--text", "continue", "--note", "弱めた変更を確かめた（検査用）")
    spec = run.record()["process"]["spec"]
    check(len(spec.get("amendments") or []) == 1 and spec["amendments"][0]["file"] == SPEC_TESTS["AC2"][0],
          "仕様の道: 承認し直した改変は process.spec.amendments に残り、新しい sha が固定される")
    last = drive(run, "spec")
    check(last["status"] == "converged", f"仕様の道: 承認し直した後は進む（{last['status']}）")
    rm(run.tmp)

    run = Run("spec-typo", init_args=("--input", "flow=spce"))
    check(run.init.returncode != 0 and "flow" in run.init.stderr, f"仕様の道: 知らない flow は init で拒む（{run.init.stderr[-160:]}）")
    check(not run.dir.exists(), "仕様の道: 拒んだ init は置き場を残さない（残すと next がその run を既定の流れのまま回す）")
    # --dir を渡さない init（current を書く形）でも、拒んだ run を current が指さない
    r = subprocess.run([PY, str(LOOP), "init", "--loop", "review-loop", "--request", "x", "--validator", str(VALIDATOR), "--input", "flow=spce"],
                       cwd=run.repo, capture_output=True, text=True, encoding="utf-8", timeout=600)
    base = run.repo / ".git" / "graphloops" / "review-loop"
    left = sorted(x.name for x in base.iterdir()) if base.is_dir() else []
    check(r.returncode != 0 and not left, f"仕様の道: 拒んだ init は current も run の置き場も残さない（残った物 {left}）")
    rm(run.tmp)

    # 周の途中の問いに escalate を載せる rules は、問いを立てる時点で落とす（答える人を待ってから拒まない）
    _td2, gtmp = parallel.workspace("gl-review-inround-")
    for sub in ("prompts", "rules", "graphs"):
        shutil.copytree(PLUGIN / sub, gtmp / sub)
    rp = gtmp / "rules" / "review-loop.py"
    src = rp.read_text(encoding="utf-8")
    rp.write_text(src.replace('"items": items, "options": ["continue", "stop"]}}', '"items": items, "options": ["continue", "stop", "escalate"]}}', 1), encoding="utf-8")
    run = Run("spec-inround", init_args=("--input", "flow=spec"), graph=gtmp / "graphs" / "review-loop.json")
    try:
        drive(run, "spec")
        got = "落ちなかった"
    except RuntimeError as e:
        got = str(e)
    check("escalate" in got and "動けない語" in got and "pending_human" not in run.state(),
          f"仕様の道: 周の途中の問いの選択肢に escalate を載せた rules は、問いを立てる時点で落ちる（{got[-160:]}）")
    rm(run.tmp)
    rm(gtmp)

    # 固定の検査が拒んだ回は盤面を変えない: 依頼の欄が型崩れのまま承認すると spec.freeze が拒み、patch で直して next すれば進む
    run = Run("spec-freeze-retry", init_args=("--input", "flow=spec"))
    drive(run, "spec")
    bad = run.tmp / "bad.json"
    bad.write_text(json.dumps("型崩れ"), encoding="utf-8")
    run.cmd("patch", "--path", "process.request_findings", "--file", str(bad), "--reason", "台本: 依頼の欄の型崩れ")
    run.cmd("answer", "--text", "continue")
    r = run.cmd("next")
    held = run.state()["loop"].get("spec_pending")
    check(held is not None and "spec" not in run.record()["process"],
          f"仕様の道: 固定が拒んだ回は、承認待ちの仕様を消さず記録にも固定しない（{r.stdout[-200:]} {r.stderr[-200:]}）")
    good = run.tmp / "good.json"
    good.write_text("[]", encoding="utf-8")
    run.cmd("patch", "--path", "process.request_findings", "--file", str(good), "--reason", "台本: 型を直す")
    r = run.cmd("next")
    check(r.returncode == 0 and "spec" in run.record()["process"] and "spec_pending" not in run.state()["loop"],
          f"仕様の道: 直してから next すれば固定まで進む（{r.stderr[-200:]}）")
    rm(run.tmp)


def test_stop_signal_stops_test_runner_tree():
    """**loop.py が止める信号を受けたら、builtin が起こしたテストの実行器の木も止める**（全コマンドの信号の口）。
    仕様の固定（spec.freeze）が受け入れ条件を走らせている next に SIGTERM を送り、孫まで止まって exit 143 で抜けることを見る"""
    if os.name != "posix":
        skip("止める信号: next が止められたら、受け入れ条件の実行器の孫まで止めて 143 で抜ける", "process-group",
             "posix の信号とプロセスグループで孫の生死を見る台本の作り（SIGTERM を送って 128+信号で抜ける）に頼る")
        return
    print("止める信号: next の中で走るテストの実行器の木を孫まで止め、128+信号で抜ける")
    run = Run("spec-signal", init_args=("--input", "flow=spec"))
    drive(run, "spec")
    pidf = run.tmp / "runner-grandchild.pid"
    f = run.repo / SPEC_TESTS["AC1"][0]
    f.write_text(f.read_text(encoding="utf-8").replace("import pathlib, sys\n",
                 f"import pathlib, subprocess, sys, time\nc = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(120)'])\n"
                 f"open({str(pidf)!r}, 'w').write(str(c.pid))\ntime.sleep(120)\n", 1), encoding="utf-8")
    run.cmd("answer", "--text", "continue")
    proc = subprocess.Popen([PY, str(LOOP), "next", "--dir", str(run.dir)], cwd=run.repo, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    t0 = time.monotonic()
    while not (pidf.is_file() and pidf.read_text(encoding="utf-8").strip()) and proc.poll() is None and time.monotonic() - t0 < 60:
        time.sleep(0.05)
    gp = int(pidf.read_text(encoding="utf-8")) if pidf.is_file() and pidf.read_text(encoding="utf-8").strip() else None
    proc.send_signal(signal.SIGTERM)
    try:
        proc.wait(60)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()

    def gone(pid):
        t1 = time.monotonic()
        while time.monotonic() - t1 < 15:
            try:
                os.kill(pid, 0)
            except OSError:
                return True
            time.sleep(0.05)
        return False
    check(gp is not None and proc.returncode == 128 + signal.SIGTERM and gone(gp),
          f"止める信号: next が止められたら、受け入れ条件の実行器の孫まで止めて 143 で抜ける（rc={proc.returncode} pid {gp}）")
    rm(run.tmp)


def test_spec_default_unchanged():
    """**仕様の道を選ばない run は、仕様の道を足す前の graph と同じに回る**——節の並び（周ごとに出た instance）・
    役に渡るプロンプト・周の記録・報告が、正規化（一時ディレクトリ・sha・時刻・engine が走らせた段の所要時間）の後で 1 字も違わない。
    比べる相手は、今の graph から spec.* の節と、それを待つ依存 2 語を抜いた写し（台本の中で作る）"""
    print("仕様の道を選ばない run: 足す前の graph と、並び・プロンプト・記録・報告が同じ")
    g = json.loads((PLUGIN / "graphs" / "review-loop.json").read_text(encoding="utf-8"))
    spec_nodes = [k for k in g["nodes"] if k.startswith("spec.")]
    for k in spec_nodes:
        del g["nodes"][k]
    for n in g["nodes"].values():
        n["deps"] = [d for d in n.get("deps", []) if d not in spec_nodes]
    _td, gtmp = parallel.workspace("gl-review-spec-base-")
    for sub in ("prompts", "rules"):
        shutil.copytree(PLUGIN / sub, gtmp / sub)
    (gtmp / "graphs").mkdir()
    old_graph = gtmp / "graphs" / "review-loop.json"
    old_graph.write_text(json.dumps(g, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    runs = {"new": Run("spec-off-new"), "old": Run("spec-off-old", graph=old_graph)}
    for r_ in runs.values():
        drive(r_, "std")

    def norm(run_, text):
        # 長い綴り（/private/var…）から。JSON に書いた綴り（Windows では \\ が 2 つずつ）も同じ置き場として読む
        spell = {v for q in (str(run_.tmp), str(run_.tmp.resolve())) for v in (q, json.dumps(q)[1:-1])}
        for p_ in sorted(spell, key=len, reverse=True):
            text = text.replace(p_, "<TMP>")
        text = re.sub(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d[+\-Z0-9:.]*", "<T>", text)
        # engine が走らせた段（engine_run）の所要時間は実測で、負荷で 0.0 と 0.1 に割れる
        text = re.sub(r"（\d+(?:\.\d+)? 秒）", "（<S> 秒）", text)
        text = re.sub(r'"wall_s": \d+(?:\.\d+)?', '"wall_s": <S>', text)
        # 報告の 1 行目の来歴は run の番号（init の時刻）を持ち、2 つの run で秒が違う
        text = re.sub(r"run \d{8}-\d{6}(?:-\d+)?", "run <RUN>", text)
        return re.sub(r"\b[0-9a-f]{7,64}\b", "<H>", text)

    def shape(run_):
        st = run_.state()
        seq = [(rd["round"], list(rd["instances"])) for rd in st["rounds"]]
        prompts = {i["id"] + f"@r{rd['round']}": norm(run_, pathlib.Path(i["prompt_file"]).read_text(encoding="utf-8"))
                   for rd in st["rounds"] for i in rd["instances"].values()}
        recs = {f.name: norm(run_, f.read_text(encoding="utf-8")) for f in [run_.dir / "record.json", run_.dir / "report.md", *sorted((run_.dir / "rounds").glob("round-*.json"))]}
        return seq, prompts, recs
    new, old = shape(runs["new"]), shape(runs["old"])
    check(new[0] == old[0] and len(new[0]) == 3, f"選ばない run: 周ごとに出た節の並びが同じ（{[len(x[1]) for x in new[0]]} / {[len(x[1]) for x in old[0]]}）")
    def first_diff(a, b_):
        k = sorted(x for x in set(a) | set(b_) if a.get(x) != b_.get(x))
        if not k:
            return []
        la, lb = (a.get(k[0]) or "").splitlines(), (b_.get(k[0]) or "").splitlines()
        at = next((i for i, (x, y) in enumerate(zip(la, lb)) if x != y), min(len(la), len(lb)))
        return [*k[:3], (la[at:at + 1], lb[at:at + 1])]
    diff = first_diff(new[1], old[1])
    check(not diff, f"選ばない run: 役に渡るプロンプトが 1 字も違わない（違う節と最初の違い {diff}）")
    diff = first_diff(new[2], old[2])
    check(not diff, f"選ばない run: 記録（record.json・rounds/*）と報告が同じ（違う物と最初の違い {diff}）")
    na = runs["new"].state()["rounds"][0]["na"]
    check(all(na.get(k, "").startswith("cond") for k in spec_nodes) and all(k not in runs["old"].state()["rounds"][0]["na"] for k in spec_nodes),
          "選ばない run: 仕様の道の節は条件外（na）として盤面に残るだけ")
    for r_ in runs.values():
        rm(r_.tmp)
    rm(gtmp)


# ---------------------------------------------------------------- 人の方針と人の決定権の関所
POLICY_MARK = "POLICY-MARK-7f3（検査用の人の方針: 今ある能力を減らさない）"


def policy_default(run):
    return run.repo / ".git" / "graphloops" / "policy.md"


def put_policy(run, text=POLICY_MARK):
    f = policy_default(run)
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(text + "\n", encoding="utf-8")


def test_policy_reaches_roles():
    """**人の方針の文書**: 既定の置き場（作業ツリーの外）に在れば init が拾って sha を固定し、判定・審査・R には本文が貼られ、
    回す側の節（修正）には置き場が渡る。変わらなければ関所は聞かずに収束する。名指しした文書が無ければ init で止める"""
    print("人の方針: 既定の置き場の文書が判定・審査・R2 に貼られ、修正には置き場が渡る")
    run = Run("policy", before_init=put_policy)
    check(run.init.returncode == 0, f"人の方針: init が通る（{run.init.stderr[-200:]}）")
    seen = {}

    def hook(run_, inst, out):
        if inst["node"] in ("p2.diagnose", "p2.plan_review", "r2.design", "r4.hidden_scope", "p3.fix") and inst["node"] not in seen:
            seen[inst["node"]] = pathlib.Path(inst["prompt_file"]).read_text(encoding="utf-8")
        return None
    last = drive(run, "std", hook=hook)
    pol = run.record()["process"].get("policy") or {}
    check(pol.get("path") == str(policy_default(run).resolve()) and len(pol.get("sha256") or "") == 64 and pol.get("amendments") == []
          and pathlib.Path(pol.get("copy") or "/nonexistent").read_text(encoding="utf-8") == POLICY_MARK + "\n"
          and pathlib.Path(pol["copy"]).parent.resolve() == (run.dir / "policy").resolve(),
          f"人の方針: init が既定の置き場の文書を拾い、sha と盤面の写しを記録に固定する（{pol}）")
    pasted = [k for k in ("p2.diagnose", "p2.plan_review", "r2.design", "r4.hidden_scope") if POLICY_MARK in seen.get(k, "")]
    check(pasted == ["p2.diagnose", "p2.plan_review", "r2.design", "r4.hidden_scope"],
          f"人の方針: 判定・事前審査・R2（道具ゼロ）・R4 のプロンプトに本文が貼られる（貼られた節 {pasted}）")
    fixp = seen.get("p3.fix", "")
    check(str(policy_default(run).resolve()) in fixp and POLICY_MARK not in fixp,
          "人の方針: 回す側の節（修正）には本文でなく置き場が渡る")
    check(last["status"] == "converged" and not run.record()["process"]["human_items"] and "policy_change" not in run.record()["process"],
          f"人の方針: 文書が変わらず後退も並ばない run は、関所で聞かずに収束し、変化の欄も置かない（{last['status']}）")
    put_policy(run, POLICY_MARK + "\n最後の関所の後の書き足し（検査用 LATE-EDIT）")
    run.cmd("finalize")
    ch = run.record()["process"].get("policy_change") or {}
    check(ch.get("from") == pol["sha256"] and ch.get("to") and ch["to"] != ch["from"],
          f"人の方針: 最後の関所の後に文書が変わった run は、仕上げが変化を記録に置く（{ch}）")
    rm(run.tmp)

    run = Run("policy-missing", init_args=("--input", "policy_md=no/such/policy.md"))
    check(run.init.returncode != 0 and "policy_md" in run.init.stderr,
          f"人の方針: init で名指しした文書が無ければ止める（{run.init.stderr[-160:]}）")
    # 拒むのは置き場を作った後の入口（rules の on_init）——作った置き場ごと消す（flow の値の拒みは置き場を作る前の check_inputs）
    check(not run.dir.exists(), "人の方針: 拒んだ init は置き場を残さない（on_init が拒んでも、作った置き場を消す）")
    rm(run.tmp)


def test_human_gate():
    """**人の決定権の関所**: 修正案の狭め（narrows）・事前審査の後退の穴・R4 が BASE から消えたと見た能力・方針の文書の変更は、
    役が決めずに周の途中で人に聞く。continue の note は修正役に届き、同じ文の lost は聞き直さない。stop と無人は止まる。
    修正差分の審査は後退の語を使えない"""
    print("人の決定権の関所: 狭め・後退・方針の文書の変更を人に聞き、答えを修正役に届ける")
    run = Run("gate")
    seen = {}

    def hook(run_, inst, out):
        rnd = run_.state()["round"]
        if inst["node"] == "p2.diagnose" and "diagnose" not in seen:
            seen["diagnose"] = pathlib.Path(inst["prompt_file"]).read_text(encoding="utf-8")
        if inst["node"] == "p2.fix_plan" and rnd == 1:
            return {"plan": [{**out["plan"][0], "narrows": [{"what": "呼び元が上限なしで呼べる経路（検査用 NARROW-1）",
                                                              "why": "上限を入口 1 か所に寄せると呼び元の分岐が消える（検査用）"}]}]}
        if inst["node"] == "p3.fix" and rnd == 1:
            seen["fix"] = pathlib.Path(inst["prompt_file"]).read_text(encoding="utf-8")
            put_policy(run_, "修正役が書いた方針（検査用 WRITER-POLICY）")   # 役が方針の文書を書き換える形
        if inst["node"] == "p3.delta_review" and "delta" not in seen:
            bad = {**out, "faces": [{"key": "後退: 呼び元の経路", "kind": "regression", "where": "src/a.py", "cite": "limit",
                                     "why": "呼び元の上限なしの経路が消えた（検査用）"}]}
            r = run_.done(inst["id"], bad)
            seen["delta"] = (r.returncode, r.stderr)
        if inst["node"] == "r4.hidden_scope":
            return {**out, "capability_inventory": {"fired": True, "lost": ["呼び元の上限なしの経路（検査用 LOST-1）"]},
                    "policy_conflicts": ["期限を足した（検査用 CONFLICT-1）"]}
        return None

    last = drive(run, "std", hook=hook)
    check(last["status"] == "awaiting_human" and last["ask"].get("in_round") and last["ask"]["kinds"] == ["regression"]
          and "NARROW-1" in "".join(last["ask"]["items"]),
          f"関所: 修正案の narrows が 1 件でもあれば、修正の前に人に聞く（{last.get('ask', {}).get('kinds')}）")
    st = run.state()
    check(not any(i["node"] == "p3.fix" for i in st["rounds"][0]["instances"].values()), "関所: 人が答えるまで修正の節は出ない")
    check(run.record()["process"]["policy"]["path"] is None and "人の方針" in seen.get("diagnose", ""),
          "関所: 方針の文書が無い run では、固定する版は無く、判定のプロンプトには方針の段落だけが出る")
    r = run.cmd("answer", "--text", "continue", "--note", "呼び元の経路は残せ（検査用 KEEP-NOTE）")
    check(r.returncode == 0, f"関所: continue を返す（{r.stderr[-160:]}）")
    hi = run.record()["process"]["human_items"]
    check(len(hi) == 1 and hi[0]["node"] == "p2.human_gate" and hi[0]["answer"] == "continue" and "KEEP-NOTE" in hi[0]["note"],
          f"関所: 答えは人の答えの台帳（process.human_items）に残る（{hi}）")
    last = drive(run, "std", hook=hook)
    check("KEEP-NOTE" in seen.get("fix", ""), "関所: 人の答えの note が同じ周の修正役のプロンプトに届く")
    # 修正の入口は単位の短い行と義務の印（loop.fix_units）だけを貼り、判定の長い本文は記録の置き場を指す（同じ単位を 2 回貼らない）
    rows = (run.state()["loop"].get("fix_units") or {}).get("rows") or []
    refs = re.findall(r"置き場 (\S+?record\.json)（", seen.get("fix", ""))
    judged = [u for u in run.record()["process"]["diagnosis"]["units"] if u.get("class_query")]
    check([r["key"] for r in rows] == [u["key"] for u in run.record()["units"]] and any(r["owed"] for r in rows)
          and all(f'"key": {json.dumps(r["key"], ensure_ascii=False)}' in seen.get("fix", "") for r in rows),
          f"修正の入口: 単位の行は記録の単位と同じ順で全部載り、義務の印を持つ（{[(r['key'][:20], r['owed']) for r in rows]}）")
    check(judged and all(r["has_class_query"] for r in rows) and '"class_query"' not in seen.get("fix", "")
          and refs and all(pathlib.Path(x).is_file() for x in refs),
          f"修正の入口: 判定の長い本文（母数の問いなど）は貼らず印だけを載せ、盤面に在る記録の置き場を指す（{refs}）")
    check(seen.get("delta", (0,))[0] == 1 and "事前審査だけ" in seen["delta"][1],
          f"関所: 修正差分の審査は後退の語を使えない（手直しの義務に入れて役に決めさせない。{seen.get('delta', ('', ''))[1][-120:]}）")
    check(last["status"] == "awaiting_human" and last["ask"]["kinds"] == ["policy_changed"],
          f"関所: 方針の文書が init の後に変わった（役が書いた）なら、修正の後の関所で人に聞く（{last.get('ask', {}).get('kinds')}）")
    row = "".join(last["ask"]["items"])
    diff = row.split("差分 ", 1)[-1].split("・", 1)[0] if "差分 " in row else ""
    check("WRITER-POLICY" not in row and diff and "+修正役が書いた方針（検査用 WRITER-POLICY）" in pathlib.Path(diff).read_text(encoding="utf-8"),
          f"関所: 方針の文書の変化の行は差分のファイルの置き場を載せ（本文は載せない）、差分に変わった中身が在る（{row[-200:]}）")
    run.cmd("answer", "--text", "continue", "--note", "確かめた（検査用）")
    pol = run.record()["process"]["policy"]
    check(len(pol["amendments"]) == 1 and pol["path"] == str(policy_default(run).resolve()) and len(pol["sha256"] or "") == 64
          and run.state()["inputs"]["policy_md"] == pol["path"] and "WRITER-POLICY" in pathlib.Path(pol["copy"]).read_text(encoding="utf-8")
          and pol["amendments"][0]["diff_file"] == diff,
          "関所: 通した方針の文書の変更は新しい版（写しも）を固定し直し、以後の節に届く（履歴は amendments）")
    asked = {"LOST-1": 0, "CONFLICT-1": 0}
    kinds = set()
    for _ in range(6):
        last = drive(run, "std", hook=hook)
        if last["status"] != "awaiting_human":
            break
        for k in asked:
            asked[k] += k in "".join(last["ask"]["items"])
        kinds |= set(last["ask"]["kinds"])
        run.cmd("answer", "--text", "continue", "--note", "消えてよい（検査用）")
    check(asked == {"LOST-1": 1, "CONFLICT-1": 1} and {"regression", "policy"} <= kinds,
          f"関所: R4 の lost と方針とのぶつかり（policy_conflicts）は人に聞き、同じ文の行は通した後に聞き直さない（聞いた回数 {asked}・{sorted(kinds)}）")
    check(last["status"] == "converged", f"関所: 人が通した後は収束まで進む（{last['status']}）")
    rm(run.tmp)

    run = Run("gate-stop")

    def face(run_, inst, out):
        if inst["node"] == "p2.plan_review":
            return {**out, "faces": [{"key": "後退: 上限なしで呼べる経路が消える", "unit_keys": out["faces"][0]["unit_keys"] if out.get("faces") else [1],
                                      "kind": "regression", "where": "src/a.py", "why": "案が呼び元の分岐を消すと、上限なしの呼び出しができなくなる（検査用）",
                                      "severity": "block"}]}
        return None
    last = drive(run, "std", hook=face)
    check(last["status"] == "awaiting_human" and last["ask"]["kinds"] == ["regression"] and "事前審査の穴 [regression]" in "".join(last["ask"]["items"]),
          f"関所: 事前審査が後退の穴を挙げたら、修正の前に人に聞く（{last.get('ask', {}).get('kinds')}）")
    run.cmd("answer", "--text", "stop", "--note", "削らない向きで出し直す")
    last = run.next()
    check(last["status"] == "stopped" and last.get("halted", {}).get("node") == "p2.human_gate" and not last["ready"],
          f"関所: stop で run がその場で止まり、修正を出さない（{last.get('halted')}）")
    rm(run.tmp)

    # 人が関所で直す義務の単位を外す（answer --detail）: 形の誤りと義務に無い単位は拒んで盤面を変えず、受けた分は台帳に残り修正役に届く
    run = Run("gate-exclude")
    seen = {}

    def narrow(run_, inst, out):
        if inst["node"] == "p2.fix_plan":
            return {"plan": [{**out["plan"][0], "narrows": [{"what": "検査用の狭め", "why": "関所を立てるため（検査用）"}]}]}
        if inst["node"] == "p3.fix" and "fix" not in seen:
            seen["fix"] = pathlib.Path(inst["prompt_file"]).read_text(encoding="utf-8")
        return None
    last = drive(run, "std", hook=narrow)
    asked = last.get("ask", {}).get("question", "")
    bad, good = run.tmp / "bad.json", run.tmp / "good.json"
    bad.write_text(json.dumps({"exclude": [{"unit": "義務に無い単位（検査用）", "why": "外す（検査用）"}]}), encoding="utf-8")
    good.write_text(json.dumps({"exclude": [{"unit": 1, "why": "この周は触らない（検査用 EXCLUDE-WHY）"}]}), encoding="utf-8")
    r1 = run.cmd("answer", "--text", "continue", "--note", "通す（検査用）", "--detail", str(bad))
    hi0 = list(run.record()["process"]["human_items"])
    r2 = run.cmd("answer", "--text", "continue", "--note", "通す（検査用）", "--detail", str(good))
    hi = run.record()["process"]["human_items"]
    unit1 = run.record()["units"][0]["key"]
    check("--detail" in asked and "1. " in asked and r1.returncode == 1 and "直す義務の単位でない" in r1.stderr and not hi0
          and r2.returncode == 0 and hi and hi[-1].get("excluded") == [{"unit": unit1, "why": "この周は触らない（検査用 EXCLUDE-WHY）"}],
          f"関所: --detail で直す義務の単位を外せる（義務に無い単位は拒んで盤面を変えず、受けた分は台帳に key で残る）（{r1.returncode}/{r2.returncode} {r2.stderr[-100:]}）")
    fu = run.state()["loop"].get("fix_units") or {}
    check([r.get("owed") for r in fu.get("rows") or [] if r.get("key") == unit1] == [False],
          f"関所: 外した単位は修正の側に見せる義務の印（fix_units の owed）からも外れる——修正の受け付けはこの印から義務を引く（{fu.get('rows')}）")
    drive(run, "std", hook=narrow, stop_at=lambda n: "fix" in seen)
    check("EXCLUDE-WHY" in seen.get("fix", ""), "関所: 外した単位と理由が同じ周の修正役のプロンプトに届く")
    rm(run.tmp)

    run = Run("gate-unattended", unattended=True)
    last = drive(run, "std", hook=lambda r_, i, o: {"plan": [{**o["plan"][0], "narrows": [{"what": "検査用の狭め", "why": "無人で止まるか（検査用）"}]}]}
                 if i["node"] == "p2.fix_plan" else None)
    st = run.state()
    check(last["status"] == "stopped" and (st.get("halted") or {}).get("by") == "unattended"
          and not any(i["node"] == "p3.fix" for i in st["rounds"][0]["instances"].values()),
          f"関所: 無人では狭めの問いで止まり、修正を出さない（{st.get('halted')}）")
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
