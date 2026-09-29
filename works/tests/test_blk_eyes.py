"""独立の目のブロック（blk-eyes。BLOCKS.md の R11）の検査。

中の節は写しの graph のまま: 入口の機械の節 p4.assemble・目 6 つ（r1.comment_candidates → r1.minimality・
r2.compare → stop.premise_check・r3.coherence・r4.hidden_scope）・関所の機械の節 r4.human_gate。どの目を回すか（条件・依存）は
盤面の settle だけが決め、ブロックは ready の目を起こして返答を盤面に渡し、出口を組むだけ。R2 の設計の半分（r2.design）は修正の前に
先に作られ（core の design）、ラインの境の節がこのブロックの前に盤面へ渡す——試験の盤面も同じ口（design.hand）で渡してから入る。

- 表: 6 つの目を absent から role（where blk-eyes）へ替える行（tests/boards/tables/eyes-rows.json。ラインの nodes.json に写す案）が
  表の縛りを通る。r1.comment_candidates だけ skippable（graph で optional。3 回とも拒まれたら省いて R1 の本体へ進む）
- 盤面: 手本（graphloops 0.21.0 の台本を engine の中で撮った物）の p4.assemble の後から、上の行に替えた表で作る。表の置き場は
  一時の pack（.shared と blk-eyes の写しと、試験のライン eyes-line/nodes.json）
- 描画: 指示書は engine と同じ描き方（写しの graph の reads だけ）。先に作る道具ゼロの r2.design には差分・リポジトリの置き場が
  届かない。r2.compare の頭には設計の後に分かった前提（前提のずれ・記録の制約）と『設計の前提が変わった』の指示が載る
- 設計が無い: 設計の役が 3 回とも拒まれた盤面では比較の目が残り、出口が『独立設計が取れなかった』を理由に止める
- 受け付け: 起こす前の作業ツリーの写しと比べ、盤面の done（schema・post_check・writes・記録の整合）。3 回拒まれたら諦めの印
- 並び: 目は並んで走る（Archon の同じ層の輪）。盤面の書き込みは 1 本の錠（board.lock）で順に並べる
- 出口: 入口の周の箱だけを見る（最後の目の受け付けの settle が周を進めても読み違えない）。欄は固定（EXIT_FIELDS）
- YAML: 役の output_format は写しの schema に印（道具ゼロの役は旗 isolated）・道具は役ごと・輪は done で抜ける・with: と
  スクリプトの INPUTS が同じ・筋書き（pass と give-up）
"""
import importlib.util
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

import yaml

sys.dont_write_bytecode = True
HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent
CORE = ROOT / ".shared" / "core"
BLK = ROOT / "blk-eyes"
for _p in (str(HERE), str(CORE), str(BLK / "lib")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import accept  # noqa: E402
import boardreplay as br  # noqa: E402
import design  # noqa: E402
import entry  # noqa: E402
import eyes  # noqa: E402
from accept import role_schema  # noqa: E402
from board import BoardGap, NodeTable, graph_expanded, GRAPH_SHA  # noqa: E402
from engine.schema import validate_schema  # noqa: E402
import node_marker  # noqa: E402

LINE = "eyes-line"
ROWS = json.loads((HERE / "boards" / "tables" / "eyes-rows.json").read_text(encoding="utf-8"))
DEADLINE = 1728000000

COMMENTS_OK = {"candidates": [], "kept": []}
DESIGN_OK = {"question_stands": True, "reason": "問いは立っている", "design": "上限は入口 1 箇所で掛ける"}
DESIGN_INVALID = {"question_stands": False, "reason": "問いが立たない",
                  "premise_invalid_reason": "1 デプロイ＝1 リポジトリなので識別子は既にある", "design": ""}
MINIMALITY_OK = {"status": "pass", "reason": "累積差分は最小。台帳に逃げ道なし", "deletions": [], "ledger_audit": [],
                 "increments": []}
COMPARE_OK = {"status": "pass", "reason": "構造は一致", "differences": []}
COHERENCE_OK = {"status": "pass", "reason": "横断で揃っている"}
SCOPE_OK = {"status": "pass", "reason": "導入・露呈した横断リスクなし", "capability_inventory": {"fired": False},
            "policy_conflicts": [], "surfaced": []}
PREMISE_ESCALATE = {"key": "識別子を別に持つか", "assumption": "1 デプロイ＝1 リポジトリ", "assumption_false": False,
                    "evidence": "README に複数デプロイの記述が無い", "verdict": "escalate", "reason": "実測で反証できない"}
BAD = {"candidates": "一覧でない", "kept": []}   # r1-comments の schema に合わない
REPLY = {"r1-comments": COMMENTS_OK, "r1-minimality": MINIMALITY_OK, "r2-compare": COMPARE_OK,
         "r3-coherence": COHERENCE_OK, "r4-scope": SCOPE_OK, "premise-check": PREMISE_ESCALATE}


def table_doc():
    """1 本目のラインの表の目の 6 行を eyes-rows.json に替えた表（試験のライン eyes-line）"""
    doc = json.loads((ROOT / "darkfactory" / "nodes.json").read_text(encoding="utf-8"))
    doc["line"] = LINE
    doc["nodes"].update(ROWS)
    return doc


class Pack:
    """一時の pack: .shared と blk-eyes の写しと eyes-line/nodes.json。スクリプトは写しから起こす（entry.PACK が写しの置き場になる）"""

    def __init__(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self._tmp.name) / "works"
        skip = shutil.ignore_patterns("__pycache__")
        shutil.copytree(ROOT / ".shared", self.root / ".shared", ignore=skip)
        shutil.copytree(BLK, self.root / "blk-eyes", ignore=skip)
        (self.root / LINE).mkdir()
        (self.root / LINE / "nodes.json").write_text(json.dumps(table_doc(), ensure_ascii=False, indent=1) + "\n",
                                                   encoding="utf-8")
        self.table = NodeTable.load(self.root / LINE / "nodes.json")

    def cleanup(self):
        self._tmp.cleanup()


def _open_units_zero(mem):
    mem["state"]["loop"]["open_units"] = 0   # overview_due が真（r3.coherence・r4.hidden_scope も出る）


# 盤面の種類 → (手本の台本, 手, 記憶の手当て, settle するか)
KINDS = {
    "r1r2": ("test_converges", 49, None, True),     # p4.assemble の後。r1.comment_candidates・r2.design が出る（r3・r4 は na）
                                                    # r2.design は board() が先に作った設計として渡す（r2.compare が出る）
    "all4": ("test_converges", 49, _open_units_zero, True),   # 目 4 つが同時に出る
    "asking": ("test_human_gate", 51, None, True),  # r4.human_gate が人に聞く（出た目の後ろは答えるまで出ない）
    "before": ("test_converges", 48, None, False),  # p4.ci を受けた後・p4.assemble の前
}


class Boards:
    def __init__(self, pack):
        self.pack = pack
        self._tmp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self._tmp.name)
        self.made = {}

    def _build(self, kind, into):
        sc, seq, tweak, settle = KINDS[kind]
        rs = br.load_runs(sc)["1"]
        board_dir, repo = br.restore(rs, seq, "after", into)
        mem = br.memory_at(rs, seq, "after")
        if tweak:
            tweak(mem)
        b = br.board_from_memory(mem, board_dir, self.pack.table)
        if settle:
            b.settle()
        p = pathlib.Path(board_dir) / "state.json"
        st = json.loads(p.read_text(encoding="utf-8"))
        st["works"].update(line=LINE, table_sha=self.pack.table.sha())
        p.write_text(json.dumps(st, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return board_dir, repo

    def fresh(self, kind):
        into = self.root / kind
        snap = self.root / f"{kind}.snap"
        if kind not in self.made:
            self.made[kind] = self._build(kind, into)
            shutil.copytree(into / "work", snap, symlinks=True)
        else:
            shutil.rmtree(into / "work")
            shutil.copytree(snap, into / "work", symlinks=True)
        return self.made[kind]

    def cleanup(self):
        self._tmp.cleanup()


PACK = BOARDS = None
_PACK_BEFORE = None


def setUpModule():
    global PACK, BOARDS, _PACK_BEFORE
    PACK = Pack()
    _PACK_BEFORE = entry.PACK
    entry.PACK = PACK.root          # このプロセスの entry.open_board が試験のラインの表を読む
    BOARDS = Boards(PACK)


def tearDownModule():
    entry.PACK = _PACK_BEFORE
    BOARDS.cleanup()
    PACK.cleanup()


def state(board_dir):
    return json.loads((pathlib.Path(board_dir) / "state.json").read_text(encoding="utf-8"))


def record(board_dir):
    return json.loads((pathlib.Path(board_dir) / "record.json").read_text(encoding="utf-8"))


def fake_plugin(root: pathlib.Path):
    """役の定義の置き場（convergence-loops の agents/）の偽物。engine の agent_def が CONVERGENCE_LOOPS_ROOT から読む"""
    (root / "agents").mkdir(parents=True, exist_ok=True)
    for role, tools in (("judge", "Read, Glob, Grep, WebSearch, WebFetch"), ("blind-judge", "[]"),
                        ("inspector", "Read, Glob, Grep")):
        (root / "agents" / f"{role}.md").write_text(
            f"---\nname: {role}\nmodel: opus\neffort: high\ntools: {tools}\n---\n\nお前は {role}。偽の定義 ROLE-{role}\n",
            encoding="utf-8")
    return root


class _Case(unittest.TestCase):
    def setUp(self):
        self._plug = tempfile.TemporaryDirectory()
        self.addCleanup(self._plug.cleanup)
        self.plugin = fake_plugin(pathlib.Path(self._plug.name))
        self._env = {k: os.environ.get(k) for k in ("CONVERGENCE_LOOPS_ROOT", "CLAUDE_CONFIG_DIR")}
        os.environ["CONVERGENCE_LOOPS_ROOT"] = str(self.plugin)
        # 役の定義はこの偽の置き場だけから引く（利用者の plugin のキャッシュを読まない）
        os.environ["CLAUDE_CONFIG_DIR"] = str(pathlib.Path(self._plug.name) / "no-config")
        self.addCleanup(self._restore_env)

    def _restore_env(self):
        for k, v in self._env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    def board(self, kind="r1r2", made=DESIGN_OK):
        """盤面を作り、修正の前に先に作った設計 made を、ラインの境の節と同じ口（design.hand）で渡す（None なら渡さない）"""
        self.bd, self.repo = BOARDS.fresh(kind)
        if made is not None:
            accept.write_board(self.bd, design.DESIGN_FILE, made)
            got = design.hand(entry.open_board(self.bd), self.bd, self.repo)
            self.assertTrue(got["handed"], got)
        return self.bd

    def enter(self):
        got = eyes.enter(self.bd, self.repo)
        self.rnd = got["round"]
        return got

    def run_eye(self, role, reply):
        """prep → 返答 → accept を 1 回"""
        prep = eyes.prep(self.bd, role, self.rnd, self.repo)
        got = eyes.accept(self.bd, role, json.dumps(reply, ensure_ascii=False), self.repo)
        return prep, got


class TableCase(unittest.TestCase):
    def test_rows_turn_absent_eyes_into_roles(self):
        """案の行は 6 つの目を role（where blk-eyes）にし、表の縛りを通る。ラインの表はこの行をそのまま当てた（計画 P1 Task 33）。
        入口と関所は機械の節のまま"""
        now = json.loads((ROOT / "darkfactory" / "nodes.json").read_text(encoding="utf-8"))["nodes"]
        self.assertEqual(set(ROWS), set(eyes.ROLE_OF))
        for nid in ROWS:
            with self.subTest(nid):
                self.assertEqual(now[nid], ROWS[nid], "ラインの表は案の行と同じ")
                self.assertEqual((ROWS[nid]["by"], ROWS[nid]["where"]), ("role", "blk-eyes"))
        self.assertEqual({nid for nid, r in ROWS.items() if r.get("skippable")}, {"r1.comment_candidates"})
        self.assertNotEqual(now[design.NODE]["where"], "blk-eyes", "設計の半分は修正の前に作る（目のブロックで起こさない）")
        for nid in (eyes.ENTRY_NODE, eyes.GATE_NODE):
            self.assertEqual(now[nid]["by"], "builtin")
        doc = table_doc()
        with tempfile.TemporaryDirectory() as d:
            p = pathlib.Path(d) / "nodes.json"
            p.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
            t = NodeTable.load(p)
        self.assertEqual(t.check(graph_expanded(), GRAPH_SHA), [])

    def test_block_nodes_match_blocks_md(self):
        """R11 の中の節（BLOCKS.md 3.3）: 入口 p4.assemble・目 6 つ・関所 r4.human_gate。目の依存は写しの graph のまま"""
        g = graph_expanded()["nodes"]
        self.assertEqual(eyes.ENTRY_NODE, "p4.assemble")
        self.assertEqual(eyes.GATE_NODE, "r4.human_gate")
        self.assertEqual(set(eyes.ROLE_OF), {"r1.comment_candidates", "r1.minimality", "r2.compare",
                                             "r3.coherence", "r4.hidden_scope", "stop.premise_check"})
        inside = set(eyes.ROLE_OF) | {eyes.ENTRY_NODE, eyes.GATE_NODE}

        def reach(nid):
            deps = set(g[nid]["deps"])
            return deps | {x for d in deps if d in eyes.ROLE_OF for x in reach(d)}
        for nid in eyes.ROLE_OF:
            with self.subTest(nid):
                self.assertIn(eyes.ENTRY_NODE, reach(nid), "目は入口の後")
                # ブロックの外から読むのは目的（R1 の出口）と、修正の前に作って渡された設計だけ
                self.assertLessEqual(set(g[nid]["deps"]) - inside, {"p0.purpose", "p0.purpose_review", design.NODE})
        self.assertEqual(g[eyes.GATE_NODE]["deps"], ["r4.hidden_scope"])

    def test_lanes_follow_graph_deps(self):
        """筋（YAML で縦に並べる目）は graph の依存の順: 筋の中の目の依存に入る目は同じ筋の前に在る。筋をまたぐ依存は無い"""
        g = graph_expanded()["nodes"]
        self.assertEqual(sorted(n for lane in eyes.LANES for n in lane), sorted(eyes.ROLE_OF))
        for lane in eyes.LANES:
            for i, nid in enumerate(lane):
                with self.subTest(nid):
                    self.assertLessEqual({d for d in g[nid]["deps"] if d in eyes.ROLE_OF}, set(lane[:i]))


class EnterRouteCase(_Case):
    def test_enter_lists_ready_eyes_and_snaps_tree(self):
        self.board("r1r2")
        got = self.enter()
        self.assertEqual((got["ok"], got["stopped"], got["asking"]), (True, False, False), got)
        self.assertEqual(got["round"], 1)
        self.assertEqual(sorted(got["ready"]), ["r1-comments", "r2-compare"])
        snap = json.loads(pathlib.Path(got["snapshot_file"]).read_text(encoding="utf-8"))
        self.assertTrue({"porcelain", "diff_sha256", "ignored", "head", "ref"} <= set(snap))

    def test_enter_refuses_before_assemble(self):
        """入口の機械の節が今の周に済んでいない盤面は配線の誤り（目を起こさない）"""
        self.board("before", made=None)
        with self.assertRaises(BoardGap) as cm:
            eyes.enter(self.bd, self.repo)
        self.assertIn("p4.assemble", str(cm.exception))

    def test_route_follows_board_ready(self):
        self.board("r1r2")
        self.enter()
        self.assertTrue(eyes.route(self.bd, "r1-comments", self.rnd)["go"])
        r = eyes.route(self.bd, "r1-minimality", self.rnd)
        self.assertEqual((r["go"], r["stopped"]), (False, False))
        self.assertIn("r1.minimality", r["why"])
        self.assertFalse(eyes.route(self.bd, "r3-coherence", self.rnd)["go"])   # na（cond overview_due）
        self.assertFalse(eyes.route(self.bd, "r1-comments", self.rnd + 1)["go"], "入口の周でない周の目は起こさない")


class PrepCase(_Case):
    def test_prep_renders_engine_prompt_with_role_definition(self):
        self.board("r1r2")
        self.enter()
        got = eyes.prep(self.bd, "r1-comments", self.rnd, self.repo)
        text = pathlib.Path(got["prompt_file"]).read_text(encoding="utf-8")
        self.assertEqual(got["prompt"], text)
        self.assertEqual((got["node"], got["attempt"], got["already"]), ("r1.comment_candidates", 1, False))
        # 写しの graph の reads で描いた本文（穴が盤面の値で埋まる）と、返す JSON Schema
        self.assertIn("コメントの削除候補を取る", text)
        self.assertNotIn("{{", text)
        self.assertIn(state(self.bd)["loop"]["diff_file"], text)
        tail = text.rsplit("JSON Schema に合う JSON だけ", 1)[1]
        self.assertIn('"same_content_at"', tail, "返す JSON Schema を後ろに付ける")
        inst = state(self.bd)["rounds"][-1]["instances"]["r1.comment_candidates"]
        self.assertTrue(inst.get("launched_at"), "起こした印を置く")
        # 別 plugin（pr-review-toolkit）の役の定義はこの試験の置き場に無い: 止めずに無いことを出口に残す（engine と同じ）
        self.assertEqual(got["role_def"], "")
        self.assertIn("pr-review-toolkit:comment-analyzer", got["role_def_missing"])

    def test_prep_blind_role_sees_only_its_reads(self):
        """先に作る道具ゼロの r2.design の指示書（core の design.prep）には、graph の reads（目的・制約・方針）だけが載る。
        差分・変更ファイル・リポジトリの置き場は載らない"""
        self.board("r1r2", made=None)
        entry.snapshot(pathlib.Path(self.bd), design.SNAPSHOT_NAME, pathlib.Path(self.repo))
        got = design.prep(self.bd, self.repo)
        text = got["prompt"]
        st = state(self.bd)
        self.assertIn("ROLE-blind-judge", text, "役の定義（graph の plugin の agents/<役>.md）を頭に置く")
        self.assertEqual(pathlib.Path(got["role_def"]).resolve(), (self.plugin / "agents" / "blind-judge.md").resolve())
        purpose = json.loads((pathlib.Path(self.bd) / st["outputs"]["p0.purpose"]["file"]).read_text(encoding="utf-8"))
        self.assertIn(purpose["purpose_text"], text, "目的の文（graph の reads）は届く")
        # 変更ファイルの名前は、graph の reads の制約（実測の出力）が運ぶことがあるので見ない（本線と同じ）
        for leak in (st["loop"]["diff_file"], str(self.repo), st["inputs"]["cwd"], "diff-r1"):
            self.assertNotIn(leak, text, f"遮断の役に {leak!r} が届いた")

    def test_compare_prompt_carries_premises_found_after_design(self):
        """人の条件 (1): 設計は修正の前に作るので、r2.compare の頭に修正の中の前提のずれ（loop.drift_notes）と記録の制約を貼り、
        それが設計の前提を崩していれば『設計の前提が変わった』と理由つきで言わせる（古い設計と黙って比べさせない）"""
        self.board("r1r2")
        p = pathlib.Path(self.bd) / "state.json"
        st = json.loads(p.read_text(encoding="utf-8"))
        st["loop"]["drift_notes"] = [{"round": 1, "text": "上限は呼び手ごとに違うと分かった"}]
        p.write_text(json.dumps(st, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        self.enter()
        text = eyes.prep(self.bd, "r2-compare", self.rnd, self.repo)["prompt"]
        self.assertIn(eyes.PREMISE_HEAD, text)
        self.assertIn("周 1: 上限は呼び手ごとに違うと分かった", text)
        self.assertIn(f"『{eyes.PREMISE_CHANGED}: 』", text)
        cons = record(self.bd)["process"].get("constraints") or []
        for c in cons:
            self.assertIn(c["text"], text)
        self.assertLess(text.index(eyes.PREMISE_HEAD), text.index("独立設計（目的だけから別の目が導いたもの）"),
                        "比較の指示書の本文の前に置く")
        self.assertIn(DESIGN_OK["design"], text, "比較の本文には先に作った設計が載る")

    HUMAN_ITEM = {"round": 1, "kinds": ["plan_review"], "asked": ["ASKED-本文-上限を呼び手ごとに持つか"],
                  "answer": "continue", "note": "呼び手ごとの上限の要求は取り下げる"}

    def _with_human_item(self):
        p = pathlib.Path(self.bd) / "record.json"
        rec = json.loads(p.read_text(encoding="utf-8"))
        rec.setdefault("process", {}).setdefault("human_items", []).append(dict(self.HUMAN_ITEM))
        p.write_text(json.dumps(rec, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    def test_compare_prompt_carries_human_gate_answers(self):
        """人の関所の答え（record.process.human_items）は r2.compare の頭に、前提のずれより前に載る。
        取り下げた要求を固定の契約として比べさせない。聞いた項目の本文（asked）は写さない"""
        self.board("r1r2")
        self._with_human_item()
        self.enter()
        text = eyes.prep(self.bd, "r2-compare", self.rnd, self.repo)["prompt"]
        self.assertIn(self.HUMAN_ITEM["note"], text, "人の答えの一言が比較の目に届く")
        self.assertNotIn(self.HUMAN_ITEM["asked"][0], text, "聞いた項目の本文は貼らない")
        self.assertLess(text.index(self.HUMAN_ITEM["note"]), text.index("### 前提のずれ（修正の中の申告）"),
                        "人の答えは前提のずれより前に読ませる")

    def test_design_prompt_carries_human_gate_answers(self):
        """修正の前に作る独立設計（design.prep）にも、その時点で在る人の関所の答えが載る。asked は写さない"""
        self.board("r1r2", made=None)
        self._with_human_item()
        entry.snapshot(pathlib.Path(self.bd), design.SNAPSHOT_NAME, pathlib.Path(self.repo))
        text = design.prep(self.bd, self.repo)["prompt"]
        self.assertIn(self.HUMAN_ITEM["note"], text, "人の答えの一言が独立設計の役に届く")
        self.assertNotIn(self.HUMAN_ITEM["asked"][0], text, "聞いた項目の本文は貼らない")

    SPEC = ("# 設計書\n\n## 1 目的\n\nSECTION-1-BODY\n\n## 2 上限\n\nSECTION-2-BODY 上限は呼び手ごとに持つ\n\n"
            "### 2.1 細目\n\nSECTION-2-1-BODY\n\n## 3 撤収\n\nSECTION-3-BODY\n")
    NAMED_REQUEST = "[docs/spec.md の 2 節](docs/spec.md#2-上限) のとおりに直す"

    def _with_named_section(self):
        """依頼が設計書の節を名指す盤面: 作業ツリーに設計書を commit し、盤面の依頼の文をそれを名指す文にする"""
        doc = pathlib.Path(self.repo) / "docs" / "spec.md"
        doc.parent.mkdir(parents=True, exist_ok=True)
        doc.write_text(self.SPEC, encoding="utf-8")
        for args in (["add", "docs/spec.md"], ["-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "spec"]):
            subprocess.run(["git", "-C", str(self.repo), *args], check=True, capture_output=True)
        p = pathlib.Path(self.bd) / "state.json"
        st = json.loads(p.read_text(encoding="utf-8"))
        st["inputs"]["request"] = self.NAMED_REQUEST
        p.write_text(json.dumps(st, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    def _assert_only_named_section(self, text):
        self.assertIn("SECTION-2-BODY 上限は呼び手ごとに持つ", text, "依頼が名指した節の本文が道具ゼロの役に届く")
        self.assertIn("SECTION-2-1-BODY", text, "名指した節の下の深い節も同じ節の本文")
        for other in ("SECTION-1-BODY", "SECTION-3-BODY"):
            self.assertNotIn(other, text, "名指していない節は貼らない")

    def test_compare_prompt_carries_named_design_section(self):
        """依頼が設計書の節を名指していれば、道具ゼロの r2.compare の頭にその節の本文が貼られる（『渡されていない』にしない）"""
        self.board("r1r2")
        self._with_named_section()
        self.enter()
        self._assert_only_named_section(eyes.prep(self.bd, "r2-compare", self.rnd, self.repo)["prompt"])

    def test_design_prompt_carries_named_design_section(self):
        """修正の前に作る独立設計（design.prep）にも、依頼が名指した設計書の節の本文が貼られる"""
        self.board("r1r2", made=None)
        self._with_named_section()
        entry.snapshot(pathlib.Path(self.bd), design.SNAPSHOT_NAME, pathlib.Path(self.repo))
        self._assert_only_named_section(design.prep(self.bd, self.repo)["prompt"])

    def test_prep_refuses_eye_not_waiting(self):
        self.board("r1r2")
        self.enter()
        with self.assertRaises(BoardGap):
            eyes.prep(self.bd, "r1-minimality", self.rnd, self.repo)

    def test_prep_missing_own_plugin_role_is_wiring_error(self):
        """graph の plugin の役（judge・blind-judge・inspector）の定義が見つからなければ起こさない（engine の die と同じ）"""
        self.board("r1r2")
        self.enter()
        os.environ["CONVERGENCE_LOOPS_ROOT"] = str(pathlib.Path(self._plug.name) / "no-such")
        with self.assertRaises(BoardGap) as cm:
            eyes.prep(self.bd, "r2-compare", self.rnd, self.repo)
        self.assertIn("convergence-loops:blind-judge", str(cm.exception))


class AcceptCase(_Case):
    def test_accept_then_next_eye_in_lane(self):
        self.board("r1r2")
        self.enter()
        _, got = self.run_eye("r1-comments", COMMENTS_OK)
        self.assertEqual((got["ok"], got["done"], got["give_up"]), (True, True, False), got)
        self.assertTrue(eyes.route(self.bd, "r1-minimality", self.rnd)["go"])

    def test_three_rejections_give_up_and_comments_are_skipped(self):
        """r1.comment_candidates は 3 回拒まれたら省いて（skippable）R1 の本体を出す（graph: 取れなくても R1 を not_run に倒さない）"""
        self.board("r1r2")
        self.enter()
        outs = []
        for i in range(eyes.GIVE_UP_AFTER):
            prep, got = self.run_eye("r1-comments", BAD)
            outs.append(got)
            if i:
                self.assertTrue(prep["prompt"].startswith(eyes.REJECT_HEADING), "前の拒否の文を本文の頭に置く")
                self.assertIn(outs[i - 1]["reason"].splitlines()[0], prep["prompt"])
            self.assertEqual(prep["attempt"], 1)
        self.assertEqual([(o["ok"], o["done"], o["give_up"]) for o in outs],
                         [(False, False, False)] * (eyes.GIVE_UP_AFTER - 1) + [(False, True, True)])
        self.assertTrue(outs[-1]["skipped"])
        st = state(self.bd)
        self.assertIn("r1.comment_candidates", st["rounds"][-1]["skipped"])
        self.assertTrue(eyes.route(self.bd, "r1-minimality", self.rnd)["go"])

    def test_give_up_on_other_eye_stops_board_at_collect(self):
        self.board("r1r2")
        self.enter()
        for _ in range(eyes.GIVE_UP_AFTER):
            _, got = self.run_eye("r2-compare", {"reason": "型に合わない"})
        self.assertEqual((got["done"], got["give_up"], got["skipped"]), (True, True, False))
        self.assertIn("r2.compare", state(self.bd)["rounds"][-1]["instances"])
        out = eyes.collect(self.bd, self.rnd)
        self.assertFalse(out["ok"])
        self.assertIn("3 回とも", out["reason"])
        self.assertEqual(out["gave_up"], ["r2-compare"])
        self.assertEqual(state(self.bd)["stop"]["by"], eyes.STOP_BY)

    def test_design_gave_up_before_fix_stops_at_eyes_with_reason(self):
        """修正の前の設計が 3 回とも拒まれた run（人の条件 (2)）: 設計は盤面へ渡らず、ほかの目は回り、比較の目が残る。出口は
        『独立設計が取れなかった』と設計の最後の拒否を理由に盤面を止める（今までと同じく目の層で止まる）"""
        self.board("r1r2", made=None)
        entry.snapshot(pathlib.Path(self.bd), design.SNAPSHOT_NAME, pathlib.Path(self.repo))
        for _ in range(design.GIVE_UP_AFTER):
            got = design.accept_reply(self.bd, json.dumps({"reason": "型に合わない"}, ensure_ascii=False), self.repo)
        self.assertEqual((got["ok"], got["done"], got["give_up"]), (False, True, True))
        self.assertFalse(design.due(entry.open_board(self.bd))[0], "諦めた設計は起こし直さない（設計を 2 度作らない）")
        self.assertFalse(design.hand(entry.open_board(self.bd), self.bd, self.repo)["handed"])
        self.enter()
        for role in ("r1-comments", "r1-minimality"):
            self.assertTrue(eyes.route(self.bd, role, self.rnd)["go"], role)
            self.run_eye(role, REPLY[role])
        self.assertFalse(eyes.route(self.bd, "r2-compare", self.rnd)["go"])
        out = eyes.collect(self.bd, self.rnd)
        self.assertFalse(out["ok"])
        self.assertTrue(out["reason"].startswith(f"独立の目 R2: {design.MISSING}"), out["reason"])
        self.assertIn("3 回とも受け付けで拒まれた", out["reason"])
        self.assertIn("question_stands", out["reason"], "設計の最後の拒否の文を運ぶ")
        self.assertEqual(out["eyes"]["r2-compare"], "waiting")
        self.assertEqual(state(self.bd)["stop"]["by"], eyes.STOP_BY)

    def test_tree_change_is_rejected(self):
        self.board("r1r2")
        self.enter()
        f = next(p for p in pathlib.Path(self.repo).rglob("*.py") if ".git" not in p.parts)
        f.write_text(f.read_text(encoding="utf-8") + "\n# 目が書いた\n", encoding="utf-8")
        _, got = self.run_eye("r1-comments", COMMENTS_OK)
        self.assertFalse(got["ok"])
        self.assertTrue(got["reason"].startswith(entry.READONLY_MOVED), got["reason"])

    def test_unreadable_reply_is_rejected_and_counted(self):
        self.board("r1r2")
        self.enter()
        eyes.prep(self.bd, "r1-comments", self.rnd, self.repo)
        got = eyes.accept(self.bd, "r1-comments", "{JSON でない", self.repo)
        self.assertEqual((got["ok"], got["done"]), (False, False))
        self.assertIn("JSON", got["reason"])
        got = eyes.accept(self.bd, "r1-comments", "[1]", self.repo)
        self.assertFalse(got["ok"])
        got = eyes.accept(self.bd, "r1-comments", "null", self.repo)
        self.assertEqual((got["done"], got["give_up"]), (True, True))


class PathCase(_Case):
    GATE_NOTE = "Python 3.9 の縛りは取り下げる"
    UNPASSED = "関所の答えは渡されていない"
    UNPASSED_DIFF = "設計書の 2 節の本文が渡っていない"

    def _compare_with(self, reply):
        """人の関所の答えの在る盤面で目を全部回し、r2.compare に reply を返させて出口を取る。返り (r2.compare の受け付け, 出口)"""
        self.board("r1r2")
        p = pathlib.Path(self.bd) / "record.json"
        rec = json.loads(p.read_text(encoding="utf-8"))
        rec.setdefault("process", {}).setdefault("human_items", []).append(
            {"round": 1, "kinds": ["policy"], "asked": ["ASKED-本文"], "answer": "continue", "note": self.GATE_NOTE})
        p.write_text(json.dumps(rec, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        self.enter()
        for role in ("r1-comments", "r1-minimality"):
            self.run_eye(role, REPLY[role])
        _, got = self.run_eye("r2-compare", reply)
        return got, eyes.collect(self.bd, self.rnd)

    def test_unpassed_claim_is_listed_with_given_inputs(self):
        """R2 が『渡されていない』と書いた返答も受け付けは通し（拒まない・verdict を書き換えない）、出口の premise_inputs に
        その文と、支度の時に R2 へ渡した入力の控え（ここでは人の関所の答え）を並べる——最後の関所で人が突き合わせられる"""
        got, out = self._compare_with({"status": "redesign-needed", "reason": f"{self.UNPASSED}。古い縛りのまま比べた",
                                       "differences": [{"kind": "構造", "text": self.UNPASSED_DIFF}]})
        self.assertTrue(got["ok"], got)
        self.assertIn("premise_inputs", out, "出口に R2 へ渡した入力の控えと R2 の『渡されていない』の文が載る")
        pi = out["premise_inputs"]
        self.assertTrue(any(self.UNPASSED in c for c in pi["claims"]), pi)
        self.assertTrue(any(self.UNPASSED_DIFF in c for c in pi["claims"]), pi)
        self.assertTrue(any(self.GATE_NOTE in g["what"] for g in pi["compare"]["given"]),
                        "r2.compare の控えに、貼った人の関所の答えが載る")
        self.assertEqual(out["reviews"]["R2"]["status"], "redesign-needed", "verdict は書き換えない")

    def test_no_unpassed_claim_leaves_claims_empty(self):
        _, out = self._compare_with(COMPARE_OK)
        self.assertIn("premise_inputs", out)
        self.assertEqual(out["premise_inputs"]["claims"], [])

    def test_premise_invalid_runs_premise_check(self):
        """R2 が premise-invalid（question_stands 偽）: r2.compare は条件で na、stop.premise_check が出る（条件は盤面の r2_premise_invalid）"""
        self.board("r1r2", made=DESIGN_INVALID)
        self.enter()
        self.assertFalse(eyes.route(self.bd, "r2-compare", self.rnd)["go"])
        self.assertTrue(eyes.route(self.bd, "premise-check", self.rnd)["go"])
        _, got = self.run_eye("premise-check", PREMISE_ESCALATE)
        self.assertTrue(got["ok"], got)
        q = [x for x in record(self.bd)["questions"] if x.get("kind") == "premise"]
        self.assertEqual([(x["key"], x["status"]) for x in q], [("識別子を別に持つか", "escalate")])

    def test_all_eyes_then_collect(self):
        self.board("r1r2")
        self.enter()
        for role in ("r1-comments", "r1-minimality", "r2-compare"):
            self.assertTrue(eyes.route(self.bd, role, self.rnd)["go"], role)
            _, got = self.run_eye(role, REPLY[role])
            self.assertTrue(got["ok"], got)
        self.assertFalse(eyes.route(self.bd, "premise-check", self.rnd)["go"])
        out = eyes.collect(self.bd, self.rnd)
        self.assertEqual(tuple(out), eyes.EXIT_FIELDS, "出口の欄は固定")
        self.assertEqual((out["ok"], out["complete"], out["asking"], out["stopped"]), (True, True, False, False), out)
        self.assertEqual(out["eyes"], {"r1-comments": "done", "r1-minimality": "done",
                                       "r2-compare": "done", "r3-coherence": "na", "r4-scope": "na",
                                       "premise-check": "na"})
        self.assertEqual(out["reviews"]["R1"]["status"], "pass")
        self.assertEqual(out["reviews"]["R2"]["status"], "pass")
        self.assertTrue(pathlib.Path(out["after_fix"]["diff_file"]).is_file())
        self.assertEqual(set(out["after_fix"]), {"rev", "diff_file", "changed_files", "diff_lines"})
        self.assertTrue(out["after_fix"]["rev"])
        self.assertIsInstance(out["open_units"], int)
        self.assertEqual(out["retaken_for_reviews"], out["after_fix"]["diff_file"])
        self.assertTrue(pathlib.Path(out["exit_file"]).is_file())

    def test_four_eyes_in_parallel_processes(self):
        """同じ層の目 4 つの受け付けを別のプロセスで同時に走らせても、盤面は 4 つとも受ける（錠が書き込みを並べる）"""
        self.board("all4")
        self.enter()
        roles = ["r1-comments", "r2-compare", "r3-coherence", "r4-scope"]
        for role in roles:
            self.assertTrue(eyes.route(self.bd, role, self.rnd)["go"], role)
            eyes.prep(self.bd, role, self.rnd, self.repo)
        procs = [subprocess.Popen([sys.executable, str(PACK.root / "blk-eyes" / "scripts" / "accept.py")], cwd=str(self.repo),
                                  env=script_env(self.bd, role=role, reply=json.dumps(REPLY[role], ensure_ascii=False)),
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8") for role in roles]
        outs = [p.communicate() for p in procs]
        for role, p, (out, err) in zip(roles, procs, outs):
            with self.subTest(role):
                self.assertEqual(p.returncode, 0, err)
                self.assertTrue(json.loads(out)["ok"], out)
        done = state(self.bd)["rounds"][0]["done"]
        self.assertLessEqual({eyes.NODE_OF[r] for r in roles}, set(done))

    def test_asking_gate_leaves_block_reenterable(self):
        """r4.human_gate が人に聞いている間は、出ていた目の返答は受けるが後ろの目は出ない。出口は止めずに asking（答えた後に入り直す）"""
        self.board("asking")
        got = self.enter()
        self.assertTrue(got["asking"])
        for role in ("r1-comments",):
            self.assertTrue(eyes.route(self.bd, role, self.rnd)["go"], role)
            _, a = self.run_eye(role, REPLY[role])
            self.assertTrue(a["ok"], a)
        self.assertFalse(eyes.route(self.bd, "r1-minimality", self.rnd)["go"])
        out = eyes.collect(self.bd, self.rnd)
        self.assertEqual((out["ok"], out["complete"], out["asking"], out["stopped"]), (True, False, True, False), out)
        self.assertNotIn("stop", state(self.bd))
        # 人が continue で答えた後、入り直すと残りの目が出る
        b = entry.open_board(self.bd)
        b.answer("continue", "試験: 通す")
        again = eyes.enter(self.bd, self.repo)
        self.assertIn("r1-minimality", again["ready"])


def script_env(board_dir, **inputs):
    env = {k: v for k, v in os.environ.items() if not k.startswith("INPUTS_")}
    env.update({"ARTIFACTS_DIR": str(pathlib.Path(board_dir).parent), "PYTHONDONTWRITEBYTECODE": "1"})
    env.update({f"INPUTS_{k.upper()}": str(v) for k, v in inputs.items()})
    return env


class ScriptCase(_Case):
    def run_script(self, name, drop=(), **inputs):
        env = script_env(self.bd, **inputs)
        for k in drop:
            env.pop(k, None)
        r = subprocess.run([sys.executable, str(PACK.root / "blk-eyes" / "scripts" / f"{name}.py")], cwd=str(self.repo),
                           env=env, capture_output=True, text=True, encoding="utf-8")
        if r.returncode == 0:
            lines = r.stdout.splitlines()
            self.assertEqual(len(lines), 1, r.stdout + r.stderr)
            return 0, json.loads(lines[0]), r.stderr
        return r.returncode, r.stdout, r.stderr

    def ok(self, name, **inputs):
        rc, out, err = self.run_script(name, **inputs)
        self.assertEqual(rc, 0, err)
        return out

    def run_loop(self, role, reply, rnd):
        """Archon の輪と同じ順に回す: prep → 役（返答は reply）→ accept → until_bash を sh で評価"""
        g = find(workflow()["nodes"], f"{role}-loop")["loop_group"]
        rounds = []
        for i in range(1, g["max_iterations"] + 1):
            prep = self.ok("prep", role=role, round=rnd)
            got = self.ok("accept", role=role, reply=json.dumps(reply, ensure_ascii=False))
            rounds.append((prep, got))

            def value(m):
                self.assertEqual(m.group(1), f"{role}-accept", "until_bash は同じ輪の受け付けの欄だけを読む")
                return json.dumps(got[m.group(2)])
            cond = re.sub(r"\$([A-Za-z0-9_-]+)\.output\.([A-Za-z0-9_]+)", value, g["until_bash"])
            if subprocess.run(["sh", "-c", cond]).returncode == 0:
                return i, rounds
        return None, rounds

    def test_block_path_by_scripts(self):
        self.board("r1r2")
        ent = self.ok("enter")
        rnd = ent["round"]
        for role in ("r1-comments", "r1-minimality", "r2-compare"):
            self.assertTrue(self.ok("route", role=role, round=rnd)["go"], role)
            exited, rounds = self.run_loop(role, REPLY[role], rnd)
            self.assertEqual(exited, 1, rounds)
            self.assertEqual(rounds[0][1]["reason_file"], "")
        self.assertFalse(self.ok("route", role="premise-check", round=rnd)["go"])
        out = self.ok("collect", round=rnd)
        self.assertEqual((out["ok"], out["complete"]), (True, True), out)

    def test_loop_gives_up_after_three_rejections(self):
        self.board("r1r2")
        rnd = self.ok("enter")["round"]
        exited, rounds = self.run_loop("r2-compare", {"reason": "型に合わない"}, rnd)
        self.assertEqual(exited, eyes.GIVE_UP_AFTER, "輪が上限まで抜けない（Archon は run を落とす）")
        for _, a in rounds:
            self.assertTrue(pathlib.Path(a["reason_file"]).is_file(), "拒否の理由の本文は reason_file に（裁定 R44）")
        out = self.ok("collect", round=rnd)
        self.assertFalse(out["ok"])

    def test_prep_every_eye_without_plugins(self):
        """dogfood の隔離（plugin の無い CLAUDE_CONFIG_DIR・<PLUGIN>_ROOT なし）でも、6 つの目の支度（prep のスクリプト）が
        全部通る。graph の plugin の役の定義は pack の写し（core/agents/）から引いて頭に置く（run 31: r2.design・r1.minimality が
        BoardGap の exit 2 で落ちた）。別 plugin の r1.comment_candidates は engine と同じく止めずに無いことを残す"""
        os.environ.pop("CONVERGENCE_LOOPS_ROOT", None)
        empty = pathlib.Path(self._plug.name) / "empty-config"
        empty.mkdir()
        os.environ["CLAUDE_CONFIG_DIR"] = str(empty)
        agents = PACK.root / ".shared" / "core" / "agents"
        own = {"r1-minimality": "judge", "r2-compare": "blind-judge", "r3-coherence": "inspector",
               "r4-scope": "inspector", "premise-check": "judge"}
        seen = set()

        def prep(role, rnd):
            got = self.ok("prep", role=role, round=rnd)
            seen.add(role)
            if role in own:
                d = agents / f"{own[role]}.md"
                self.assertEqual(pathlib.Path(got["role_def"]).resolve(), d.resolve(), role)
                self.assertEqual(got["role_def_missing"], "", role)
                body = d.read_text(encoding="utf-8").split("---", 2)[2].strip()
                self.assertIn(body.splitlines()[0], got["prompt"], f"{role}: 役の定義の本文を頭に置く")
            else:
                self.assertEqual(got["role_def"], "")
                self.assertIn("pr-review-toolkit:comment-analyzer", got["role_def_missing"])
            return got

        # 目 4 つが同時に出る盤面: 先頭の 4 つ → 受けた後の r1.minimality
        self.board("all4")
        rnd = self.ok("enter")["round"]
        for role in ("r1-comments", "r2-compare", "r3-coherence", "r4-scope"):
            prep(role, rnd)
            self.ok("accept", role=role, reply=json.dumps(REPLY[role], ensure_ascii=False))
        for role in ("r1-minimality",):
            self.assertTrue(self.ok("route", role=role, round=rnd)["go"], role)
            prep(role, rnd)
        # R2 が premise-invalid の盤面（設計が問いは立たないと返した）: stop.premise_check
        self.board("r1r2", made=DESIGN_INVALID)
        rnd = self.ok("enter")["round"]
        self.assertTrue(self.ok("route", role="premise-check", round=rnd)["go"])
        prep("premise-check", rnd)
        self.assertEqual(seen, set(eyes.NODE_OF), "目の全部を支度した")

    def test_scripts_exit_two_on_wiring(self):
        self.board("r1r2")
        rc, _, err = self.run_script("enter", drop=("ARTIFACTS_DIR",))
        self.assertEqual(rc, 2, err)
        self.assertIn("ARTIFACTS_DIR", err)
        rc, _, err = self.run_script("prep", round=1)                  # INPUTS_ROLE が無い
        self.assertEqual(rc, 2)
        self.assertIn("INPUTS_ROLE", err)
        self.ok("enter")
        rc, out, err = self.run_script("prep", role="r1-minimality", round=1)   # 待っていない目（BoardGap）
        self.assertEqual((rc, out), (2, ""), err)
        rc, out, err = self.run_script("route", role="no-such", round=1)
        self.assertEqual((rc, out), (2, ""), err)
        rc, out, err = self.run_script("route", role="r1-comments", round="一")
        self.assertEqual((rc, out), (2, ""), err)


# ---------------------------------------------------------------- YAML
def workflow():
    return yaml.safe_load((BLK / "blk-eyes.yaml").read_text(encoding="utf-8"))


def walk(nodes, inside=None):
    for n in nodes or []:
        yield n, inside
        if "loop_group" in n:
            yield from walk(n["loop_group"].get("nodes"), n)


def find(nodes, nid):
    return next((n for n, _ in walk(nodes) if n.get("id") == nid), None)


def script_inputs(name):
    spec = importlib.util.spec_from_file_location(f"_blk_eyes_{name}", BLK / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.INPUTS


class YamlCase(unittest.TestCase):
    def setUp(self):
        self.y = workflow()
        self.top = {n["id"]: n for n in self.y["nodes"]}

    def test_exit_and_inputs(self):
        self.assertEqual((self.y["returns"], self.y["outcome_field"]), ("eyes-collect", "ok"))
        self.assertEqual(set(self.y.get("inputs") or {}), {"base_rev"})
        of = self.top["eyes-collect"]["output_format"]
        self.assertEqual(of["required"], list(eyes.EXIT_FIELDS))
        self.assertEqual(set(of["properties"]), set(eyes.EXIT_FIELDS))

    def test_one_loop_per_eye_with_role_output_format(self):
        roles = {}
        for nid, role in eyes.ROLE_OF.items():
            with self.subTest(role):
                loop = self.top[f"{role}-loop"]
                g = loop["loop_group"]
                self.assertEqual(g["max_iterations"], eyes.GIVE_UP_AFTER)
                self.assertEqual(g["until_bash"], f"test ${role}-accept.output.done = true")
                self.assertIs(g["fresh_context"], False, "出し直しは同じ会話（graphloops の --resume と同じ）")
                self.assertEqual(loop["when"], f"${role}-route.output.go == true")
                self.assertEqual(loop["depends_on"], [f"{role}-route"])
                ids = [m["id"] for m in g["nodes"]]
                self.assertEqual(ids, [f"{role}-prep", role, f"{role}-accept"])
                ai = g["nodes"][1]
                self.assertEqual(ai["command"], role)
                self.assertEqual(ai["output_format"], eyes.output_format(nid))
                self.assertEqual(sorted(ai["allowed_tools"]), sorted(eyes.allowed_tools(nid)))
                self.assertEqual(ai["settingSources"], ["user"])
                self.assertEqual(ai["idle_timeout"], DEADLINE)
                self.assertNotIn("context", ai, "1 回目は輪が新しい会話で起こす（書き手の会話を継がない）")
                roles[role] = ai
        self.assertEqual(node_marker.parse(roles["r2-compare"]["output_format"]["description"])["flags"],
                         frozenset({"isolated"}))
        self.assertEqual(roles["r2-compare"]["allowed_tools"], [])
        self.assertEqual(node_marker.parse(roles["r3-coherence"]["output_format"]["description"])["flags"], frozenset())

    def test_lanes_in_yaml(self):
        """筋ごとに route → 輪 を縦に並べ、筋の頭の route は入口の後。collect は全部の筋の最後を待つ"""
        for lane in eyes.LANES:
            prev = None
            for nid in lane:
                role = eyes.ROLE_OF[nid]
                r = self.top[f"{role}-route"]
                with self.subTest(role):
                    if prev is None:
                        self.assertEqual(r["depends_on"], ["eyes-enter"])
                    else:
                        # 前の輪は飛ばされうる（条件で na の目）。いつも走る前の route も待てば「1 つは成功」が満ちる
                        self.assertEqual(r["depends_on"], [f"{prev}-route", f"{prev}-loop"])
                        self.assertEqual(r.get("trigger_rule"), "none_failed_min_one_success")
                    self.assertEqual(r["with"], {"role": role, "round": "$eyes-enter.output.round"})
                prev = role
        c = self.top["eyes-collect"]
        want = {f"{eyes.ROLE_OF[lane[-1]]}-{k}" for lane in eyes.LANES for k in ("route", "loop")}
        self.assertEqual(set(c["depends_on"]), want)
        self.assertEqual(c["trigger_rule"], "none_failed_min_one_success")

    def test_with_matches_script_inputs(self):
        for n, _ in walk(self.y["nodes"]):
            if "script" in n:
                with self.subTest(n["id"]):
                    want = {k[len("INPUTS_"):].lower() for k in script_inputs(n["script"])}
                    self.assertEqual(set(n.get("with") or {}), want)
                    self.assertEqual(n["timeout"], DEADLINE)
                    self.assertEqual(n["runtime"], "uv")
        wired = {n["script"] for n, _ in walk(self.y["nodes"]) if "script" in n}
        self.assertEqual(wired, {p.stem for p in (BLK / "scripts").glob("*.py")})

    def test_commands_paste_rendered_prompt_only(self):
        for role in eyes.ROLE_OF.values():
            text = (BLK / "commands" / f"{role}.md").read_text(encoding="utf-8")
            with self.subTest(role):
                self.assertEqual(text.count(f"${role}-prep.output.prompt"), 1)
                self.assertEqual(re.findall(r"\$[A-Za-z_][A-Za-z0-9_-]*\.output\.[A-Za-z_]+", text),
                                 [f"${role}-prep.output.prompt"], "描いた本文 1 つだけを直の参照で貼る")
                self.assertNotIn("$LOOP_PREV", text)
                self.assertNotIn("$INPUTS", text)
                self.assertNotIn("{{", text, "指示書を写さない（本文は engine の描画）")
        self.assertEqual({p.stem for p in (BLK / "commands").glob("*.md")}, set(eyes.ROLE_OF.values()))

    def test_fixtures(self):
        fx = {p.name: yaml.safe_load(p.read_text(encoding="utf-8")) for p in (BLK / "fixtures").glob("*.stubs.yaml")}
        self.assertEqual(set(fx), {"pass.stubs.yaml", "give-up.stubs.yaml"})
        p = fx["pass.stubs.yaml"]
        self.assertEqual(p["fixture"]["expect"], "completed")
        self.assertIs(p["eyes-collect"]["ok"], True)
        g = fx["give-up.stubs.yaml"]
        self.assertIs(g["eyes-collect"]["ok"], False)
        head = (BLK / "fixtures" / "give-up.stubs.yaml").read_text(encoding="utf-8")
        self.assertIn("dry-run は until_bash を回さず", head)
        for name, f in fx.items():
            for key, out in f.items():
                nid = eyes.NODE_OF.get(key)
                if nid:
                    with self.subTest(f"{name}:{key}"):
                        self.assertEqual(validate_schema(out, eyes.output_format(nid)), [])
                if key == "eyes-collect":
                    self.assertEqual(list(out), list(eyes.EXIT_FIELDS))


if __name__ == "__main__":
    unittest.main()
