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
from unittest import mock

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
from board import BoardGap, NodeTable, graph_expanded, GRAPH_SHA, rules_module  # noqa: E402
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


def commit_file(repo, rel: str, text: str) -> None:
    """作業ツリーに rel を書いて add と commit をする（固めた版 HEAD の追跡ファイルにする）"""
    f = pathlib.Path(repo) / rel
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(text, encoding="utf-8")
    for args in (["add", rel], ["-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", rel]):
        subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)


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
        # 軽量の深さで省ける目（持ち主の決定 2026-10-06。写しの graph で optional にした）。stop.premise_check は R2 が立てた時だけ
        self.assertEqual({nid for nid, r in ROWS.items() if r.get("skippable")},
                         {"r1.comment_candidates", "r1.minimality", "r2.compare", "r3.coherence", "r4.hidden_scope"})
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

    def test_route_skip_reason_skips_skippable_eyes(self):
        """入力 skip_optional に理由が在れば、表で skippable の目（コメントの削除候補と R1 の本体・R2 の比較。持ち主の決定 2026-10-06）は
        起こさずに盤面で省き（記録の省略した機構に理由）、筋の次の目が待つ。出口は止めずに ok"""
        self.board("r1r2")
        self.enter()
        why = "軽量で省いた（試し）"
        for role, nid in (("r1-comments", "r1.comment_candidates"), ("r1-minimality", "r1.minimality"),
                          ("r2-compare", "r2.compare")):
            with self.subTest(role):
                r = eyes.route(self.bd, role, self.rnd, skip=why)
                self.assertEqual((r["go"], r["stopped"]), (False, False))
                self.assertIn(why, r["why"])
                self.assertEqual(state(self.bd)["rounds"][self.rnd - 1]["skipped"].get(nid), why)   # 周が締まっても入口の周の箱で見る
        self.assertTrue(eyes.collect(self.bd, self.rnd)["ok"])

    def test_route_without_skip_reason_raises_skippable_eye(self):
        """理由が空なら skippable の目も今どおり起こす（標準の深さは今の振る舞い）"""
        self.board("r1r2")
        self.enter()
        self.assertTrue(eyes.route(self.bd, "r2-compare", self.rnd, skip="")["go"])
        self.assertEqual(entry.open_board(self.bd).rd["skipped"], {})


class SectionShapeCase(unittest.TestCase):
    """名指しの節を、当たった行そのものの形（前置き・下線）で切る。形式の名前も拡張子の表も使わない（依頼 238）"""
    slugs = staticmethod(rules_module()._md_slugs)

    def span(self, text, **kw):
        return design._section_lines(text, slugs=self.slugs, **kw)

    def test_atx_section_runs_to_same_or_shallower_heading(self):
        text = "# 設計書\n\n## 1 目的\n\nA\n\n## 2 上限\n\nB\n\n### 2.1 細目\n\nC\n\n## 3 撤収\n\nD\n"
        self.assertEqual(self.span(text, num="2"), (7, 13))
        self.assertEqual(self.span(text, anchor="2-上限"), (7, 13))

    def test_setext_and_rst_underlines_end_by_first_seen_order(self):
        text = "題\n=====\n\n一\n-----\n\nA\n\n二\n-----\n\nB\n\n次\n=====\n\nC\n"
        self.assertEqual(self.span(text, anchor="一"), (4, 7))
        self.assertEqual(self.span(text, anchor="二"), (9, 12))

    def test_adoc_equals_prefix(self):
        text = "= 文書\n\n== 1 目的\n\nA\n\n== 2 上限\n\nB\n\n=== 2.1 細目\n\nC\n\n== 3 撤収\n\nD\n"
        self.assertEqual(self.span(text, num="2"), (7, 13))

    def test_fenced_comment_does_not_end_section(self):
        text = "# 1 目的\n\n```py\n# コメント\nx = 1\n```\n\nA\n\n# 2 上限\n\nB\n"
        self.assertEqual(self.span(text, num="1"), (1, 8))

    def test_thematic_breaks_do_not_hide_headings(self):
        text = "## A\n\nA\n\n---\n\n## B\n\nB\n\n---\n\n## C\n\nC\n"
        self.assertEqual(self.span(text, anchor="b"), (7, 11))

    def test_list_and_table_rows_are_not_headings(self):
        text = "## 1 目的\n\n- 2 つ目\n- 3 つ目\n\n| 2 | x |\n| 3 | y |\n\n## 2 上限\n\nB\n"
        self.assertEqual(self.span(text, num="2"), (9, 11))

    def test_rst_overline_title_is_a_heading_not_a_fence(self):
        """上線と下線で 1 行を挟む題（reST）は見出しで、囲みに数えて節を隠さない"""
        text = "*****\n1 Intro\n*****\n\nA\n\n*****\n2 Next\n*****\n\nB\n"
        self.assertEqual(self.span(text, num="1"), (1, 5))
        self.assertEqual(self.span(text, num="2"), (7, 11))

    def md(self, text, **kw):
        return design._section_lines(text, slugs=self.slugs, md_lines=rules_module()._md_lines, **kw)

    def test_md_fence_with_spaced_info_string_hides_comment(self):
        """Markdown は写しの rules の _md_lines で囲いの外の ATX 見出しだけを数える（情報文字列に空白が在っても囲い）"""
        text = "# 1 目的\n\n```js title=x\n# comment\n```\n\nA\n\n# 2 上限\n\nB\n"
        self.assertEqual(self.md(text, num="1"), (1, 7))
        with self.assertRaisesRegex(ValueError, "見出しが無い"):
            self.md(text, anchor="comment")

    def test_md_fence_with_blank_line_after_opener(self):
        text = "# 1 目的\n\n```\n\n# 2 偽\n```\n\nA\n\n# 2 上限\n\nB\n"
        self.assertEqual(self.md(text, num="2"), (10, 12))

    def test_md_single_list_quote_table_rows_are_not_headings(self):
        text = "## 1 目的\n\n- 2 つ目\n\n> 2 引用\n\n| 2 | x |\n\n## 2 上限\n\nB\n"
        self.assertEqual(self.md(text, num="2"), (9, 11))

    def test_ambiguous_hit_names_candidate_lines(self):
        text = "## 上限 A\n\nA\n\n## 上限 B\n\nB\n"
        with self.assertRaisesRegex(ValueError, r"2 個あって決められない（行 1, 5）"):
            self.span(text, anchor="上限")

    def test_no_heading_is_value_error(self):
        with self.assertRaisesRegex(ValueError, "見出しが無い"):
            self.span("本文だけ\n", num="1")


class FrozenReadCase(unittest.TestCase):
    """目の指示書の『版を指定して git show / git grep で読め』の文（写しの 4 本）は、Bash を持たない目には打てない（実測: R4 が
    読めなかったと申告した）。目の cwd の作業ツリーは入口で撮った版のまま（受け付けが入口の写しと比べて変われば拒む）なので、works は
    描く時にその文を『cwd をそのまま Read・Grep で読め』に替える（写しの指示書のファイルは 1 バイトも変えない）"""

    def raw(self, nid):
        p = eyes.PROMPTS_COPY / "prompts" / "review-loop" / f"{nid}.md"
        return p.read_text(encoding="utf-8") if p.is_file() else None

    def rendered(self, nid, raw):
        b = type("B", (), {"nodes": {nid: {}}})()
        with mock.patch.object(eyes.rolekit, "render_body", lambda b, n, prompts_dir: (raw, None)):
            return eyes.render(b, nid)

    def test_copy_still_says_git_show_in_the_four_eyes(self):
        """写し直しで文が替わったら、この試験が落ちて読み替えの見直しを促す"""
        have = sorted(n for n in eyes.ROLE_OF if eyes.GIT_SHOW_SENTENCE in (self.raw(n) or ""))
        self.assertEqual(have, ["r1.comment_candidates", "r1.minimality", "r3.coherence", "r4.hidden_scope"])

    def test_no_eye_without_bash_is_told_to_run_git(self):
        for nid in eyes.ROLE_OF:
            raw = self.raw(nid)
            if raw is None:
                continue
            with self.subTest(nid):
                self.assertNotIn("Bash", eyes.allowed_tools(nid), "目に shell を持たせない")
                text = self.rendered(nid, raw)
                self.assertNotIn("git -C", text)
                if eyes.GIT_SHOW_SENTENCE in raw:
                    self.assertIn(eyes.FROZEN_READ, text)
                    self.assertIn("Read", eyes.FROZEN_READ)


class AnchorCase(unittest.TestCase):
    """問いが立たない根拠の名指し（パス:行）の拾い方（依頼 238）"""

    def test_path_line_and_range_are_anchors(self):
        self.assertEqual(design.anchors("design.py:70 と works/.shared/core/design.py:70-75 を見よ"),
                         [("design.py", 70, 70), ("works/.shared/core/design.py", 70, 75)])

    def test_host_port_and_dotted_names_are_not_anchors(self):
        """拡張子がコード・文書・設定の物（impact の表）でないドット付きの名と番号（host:port など）は名指しに数えない"""
        self.assertEqual(design.anchors("db.internal:5432 と foo.bar:12 に繋ぐ"), [])

    def test_url_and_time_are_not_anchors(self):
        self.assertEqual(design.anchors("https://example.com:443/a の応答の時刻 10:15 を使う"), [])
        self.assertEqual(design.anchor_note("https://example.com:443/a"), f"（{design.UNANCHORED}）")


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
        self.assertIn(eyes.FROZEN_READ, text, "道具に無い git show でなく、版のまま止めた cwd を Read で読ませる")
        self.assertNotIn("git -C", text)
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
        commit_file(self.repo, "docs/spec.md", self.SPEC)
        self._request(self.NAMED_REQUEST)

    def _request(self, text):
        """盤面の依頼の文（inputs.request）を text に差し替える"""
        p = pathlib.Path(self.bd) / "state.json"
        st = json.loads(p.read_text(encoding="utf-8"))
        st["inputs"]["request"] = text
        p.write_text(json.dumps(st, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    def _named(self):
        return design.named_sections(entry.open_board(self.bd), self.repo)

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

    def test_named_section_cap_is_engine_file_cap(self):
        """名指しの節 1 本の上限は engine が役に貼る本文の上限 FILE_CAP と同じ（独自の上限を置かない）。
        FILE_CAP 以内の節は切らずに全部貼り、withheld にも載せない"""
        from engine.render import FILE_CAP
        long = "長い本文の行。" * 1000   # 21000 バイト（FILE_CAP 以内）
        self.assertLess(len(long.encode("utf-8")) + 1000, FILE_CAP)
        self.SPEC = f"# 設計書\n\n## 1 目的\n\nSECTION-1-BODY\n\n## 2 上限\n\n{long}TAIL-OF-SECTION-2\n\n## 3 撤収\n\nSECTION-3-BODY\n"
        self.board("r1r2", made=None)
        self._with_named_section()
        text, given, withheld = design.named_sections(entry.open_board(self.bd), self.repo)
        self.assertIn("TAIL-OF-SECTION-2", text, "FILE_CAP 以内の節は末尾まで貼る")
        self.assertEqual([g["kind"] for g in given], ["named_section"])
        self.assertEqual(withheld, [], "FILE_CAP 以内の節を渡していない物に数えない")

    def test_named_section_over_cap_names_cut_lines(self):
        """FILE_CAP を超えた節は切り、切った残りを出どころの行の範囲で withheld に名指す。貼る見出しにも出どころの行の範囲を添える"""
        from engine.render import FILE_CAP
        long = "長い本文の行。\n" * 4000
        self.assertGreater(len(long.encode("utf-8")), FILE_CAP)
        self.SPEC = f"# 設計書\n\n## 1 目的\n\nSECTION-1-BODY\n\n## 2 上限\n\n{long}TAIL-OF-SECTION-2\n\n## 3 撤収\n\nSECTION-3-BODY\n"
        self.board("r1r2", made=None)
        self._with_named_section()
        text, given, withheld = design.named_sections(entry.open_board(self.bd), self.repo)
        self.assertEqual(len(withheld), 1, withheld)
        self.assertTrue(withheld[0]["why"].startswith(f"{FILE_CAP} バイトを超えた残り（docs/spec.md:"), withheld)
        self.assertIn("（docs/spec.md:", text.split("#### ", 1)[1].splitlines()[0])

    def test_design_head_rereads_copy_inputs_sentence(self):
        """人の答えを貼る run では、写しの指示書の『渡すのは元の目的と実測した制約だけ』を、貼った節も渡していると読み替える
        1 文を頭の節に置く（写しは 1 バイトも変えない）。比べる役・事前審査が読む前置きも、渡した物を『制約だけ』と言わない"""
        self.board("r1r2", made=None)
        self._with_human_item()
        entry.snapshot(pathlib.Path(self.bd), design.SNAPSHOT_NAME, pathlib.Path(self.repo))
        text = design.prep(self.bd, self.repo)["prompt"]
        start = text.index(design.DESIGN_PREMISE_HEAD)
        head = text[start:text.index("\n\n---\n\n", start)]
        self.assertIn("渡すのは元の目的と実測した制約だけ", head, "写しの文を名指して読み替える")
        self.assertIn("読み替え", head)
        lib = str(ROOT / "blk-plan" / "lib")
        if lib not in sys.path:
            sys.path.insert(0, lib)
        import planblk
        for said in (eyes.PREMISE_ASK, planblk.DESIGN_HEAD):
            self.assertNotIn("実測した制約だけ", said)

    def test_bare_section_number_binds_to_the_one_named_doc(self):
        """パスの無い「§N」「N 節」は、依頼が別の所で名指した設計書のパスがただ 1 本ならそれに結び付けて節の本文を貼る"""
        self.NAMED_REQUEST = "[docs/spec.md の 2 節](docs/spec.md#2-上限) のとおりに直し、§3 の撤収も合わせる"
        self.board("r1r2", made=None)
        self._with_named_section()
        text, given, withheld = design.named_sections(entry.open_board(self.bd), self.repo)
        self.assertIn("SECTION-3-BODY", text, "パスの無い §3 が名指した設計書の 3 節に結び付く")
        self.assertIn("docs/spec.md 3 節", [g["what"] for g in given])
        self.assertEqual(withheld, [])

    def test_bare_section_number_without_doc_is_withheld(self):
        """結び付ける設計書のパスが依頼に無ければ、パスの無い「N 節」は推測で貼らず、理由つきで withheld に載せる（黙って落とさない）"""
        self.NAMED_REQUEST = "設計書の 3 節のとおりに直す"
        self.board("r1r2", made=None)
        self._with_named_section()
        text, given, withheld = design.named_sections(entry.open_board(self.bd), self.repo)
        self.assertNotIn("SECTION-3-BODY", text)
        self.assertEqual(given, [])
        self.assertTrue([w for w in withheld if w["kind"] == "named_section" and "3 節" in w["what"] and w["why"]],
                        withheld)

    def test_adoc_link_section_is_given(self):
        """文書の拡張子（impact.DOC_EXT）のリンクなら .md でなくても名指しに数え、当たった行の形で節を切る"""
        self.board("r1r2", made=None)
        commit_file(self.repo, "docs/spec.adoc",
                    "= 文書\n\n== 1 目的\n\nA\n\n== 2 上限\n\nADOC-2-BODY\n\n=== 2.1 細目\n\nC\n\n== 3 撤収\n\nD\n")
        self._request("[上限](docs/spec.adoc#上限) のとおり")
        text, given, withheld = self._named()
        self.assertIn("ADOC-2-BODY", text)
        self.assertEqual([g["what"] for g in given], ["docs/spec.adoc#上限"])
        self.assertEqual(withheld, [])

    def test_pathless_name_resolves_dated_spec(self):
        """パスの無い「<名前> N 節」は、拡張子を除いた名が名前で終わる追跡の文書（日付を頭に付けた設計書）に解く"""
        self.board("r1r2", made=None)
        commit_file(self.repo, "docs/specs/2026-09-29-structure-block-design.md", "## 7 隔て\n\nSEVEN-BODY\n\n## 8 次\n\nX\n")
        self._request("structure-block-design 7 節 を崩さない")
        text, given, withheld = self._named()
        self.assertIn("SEVEN-BODY", text)
        self.assertEqual([g["what"] for g in given], ["docs/specs/2026-09-29-structure-block-design.md 7 節"])

    def test_pathless_name_after_japanese_text(self):
        """日本語の地の文に続けて書いた名前（「詳しくはstructure-design 2 節」）は、地の文を名に混ぜずに引く"""
        self.board("r1r2", made=None)
        commit_file(self.repo, "docs/specs/2026-09-29-structure-design.md", "## 2 隔て\n\nTWO-BODY\n\n## 3 次\n\nX\n")
        self._request("詳しくはstructure-design 2 節を見よ")
        text, given, withheld = self._named()
        self.assertIn("TWO-BODY", text)
        self.assertEqual([g["what"] for g in given], ["docs/specs/2026-09-29-structure-design.md 2 節"])

    def test_md_named_section_skips_fence_with_info_string(self):
        """.md の名指しの節は囲いの中の # 行で切れない（情報文字列に空白が在っても）"""
        self.board("r1r2", made=None)
        commit_file(self.repo, "docs/spec.md", "## 2 上限\n\n```js title=x\n## 3 偽\n```\n\nBODY-2-TAIL\n\n## 3 撤収\n\nS3\n")
        self._request("`docs/spec.md` 2 節 のとおり")
        text, given, withheld = self._named()
        self.assertIn("BODY-2-TAIL", text)
        self.assertNotIn("S3", text)

    def test_pathless_name_with_two_candidates_is_withheld(self):
        """名の一致する追跡の文書が 2 本以上なら推測せず、候補を並べて withheld に載せる"""
        self.board("r1r2", made=None)
        commit_file(self.repo, "a/notes.md", "## 1 x\n")
        commit_file(self.repo, "b/notes.adoc", "## 1 x\n")
        self._request("notes 1 節")
        text, given, withheld = self._named()
        self.assertEqual(given, [])
        self.assertEqual(len(withheld), 1, withheld)
        self.assertIn("2 本あって決められない", withheld[0]["why"])
        for c in ("a/notes.md", "b/notes.adoc"):
            self.assertIn(c, withheld[0]["why"])

    def test_pathless_name_without_candidates_falls_back_to_bare_number(self):
        """名の一致する文書が無い名前は名指しに数えず、「N 節」は今どおりパスの無い番号として 1 本の設計書に結ぶ"""
        self.NAMED_REQUEST = "[docs/spec.md の 2 節](docs/spec.md#2-上限) と nothing-here 3 節"
        self.board("r1r2", made=None)
        self._with_named_section()
        text, given, withheld = self._named()
        self.assertIn("docs/spec.md 3 節", [g["what"] for g in given])
        self.assertEqual(withheld, [])

    def test_code_link_is_not_a_named_doc(self):
        """コードへのリンクは設計書に数えない（実装を独立設計に貼らない・パスの無い番号の結び付けを外さない）"""
        self.NAMED_REQUEST = "[x](works/.shared/core/design.py#L70) と `docs/spec.md` 2 節、§3 も"
        self.board("r1r2", made=None)
        self._with_named_section()
        text, given, withheld = self._named()
        self.assertNotIn("def premises", text)
        self.assertEqual([g["what"] for g in given], ["docs/spec.md 2 節", "docs/spec.md 3 節"])
        self.assertEqual(withheld, [])

    def test_design_prompt_carries_repo_map(self):
        """対象のリポジトリの根の ARCHITECTURE.md を地図として、出どころのパス:行つきで独立設計に貼り、控えの given に載せる"""
        self.board("r1r2", made=None)
        commit_file(self.repo, "ARCHITECTURE.md", "# 全体\n\nMAP-BODY 信用の起点は署名\n")
        entry.snapshot(pathlib.Path(self.bd), design.SNAPSHOT_NAME, pathlib.Path(self.repo))
        text = design.prep(self.bd, self.repo)["prompt"]
        self.assertIn("MAP-BODY", text)
        self.assertIn("ARCHITECTURE.md:1-3", text)
        self.assertIn(design.MAP_HEAD, text)
        ledger = json.loads((pathlib.Path(self.bd) / design.PREMISES_FILE).read_text(encoding="utf-8"))
        self.assertIn({"kind": "repo_map", "what": "ARCHITECTURE.md:1-3"}, ledger["given"])

    def test_compare_prompt_carries_repo_map(self):
        """突き合わせ（r2.compare）にも同じ地図を貼る"""
        self.board("r1r2")
        commit_file(self.repo, "ARCHITECTURE.md", "# 全体\n\nMAP-BODY 信用の起点は署名\n")
        self.enter()
        self.assertIn("MAP-BODY", eyes.prep(self.bd, "r2-compare", self.rnd, self.repo)["prompt"])

    def test_no_map_is_named_not_silent(self):
        """地図が 1 つも無ければ『地図なし』を貼り、渡していない物に理由を残す（黙って落とさない）"""
        self.board("r1r2", made=None)
        text, given, withheld = design.repo_map(self.repo)
        self.assertIn("地図なし", text)
        self.assertEqual(given, [])
        self.assertEqual(withheld, [{"kind": "repo_map", "what": "ARCHITECTURE.md・AGENTS.md",
                                     "why": "対象のリポジトリの根に追跡されていない"}])

    def test_map_only_from_root(self):
        """地図は根のパスだけを読む（docs/AGENTS.md は地図にしない）"""
        self.board("r1r2", made=None)
        commit_file(self.repo, "docs/AGENTS.md", "SUBDIR-MAP\n")
        text, _, _ = design.repo_map(self.repo)
        self.assertNotIn("SUBDIR-MAP", text)
        self.assertIn("地図なし", text)

    STRUCTURE_MARK = "STRUCTURE-MARK-u-417"
    DESIGN_ROW_MARK = "DESIGN-ROW-MARK-u-417"

    def test_design_prompt_is_built_only_from_allowed_kinds_without_structure_outputs(self):
        """独立設計に貼る前提は明示の一覧（design.PREMISE_KINDS）の種類だけで組み、構造のブロックの出力（structure.json・design.jsonl）の
        パスも中身も渡さない（設計書 structure-block-design 7 節の隔て）。名指しの節の本文に名が出るのは赤にしない"""
        self.board("r1r2", made=None)
        self._with_human_item()
        planted = []
        for d in (pathlib.Path(self.bd), pathlib.Path(self.bd) / "structure", pathlib.Path(self.bd).parent / "structure"):
            d.mkdir(parents=True, exist_ok=True)
            s, j = d / "structure.json", d / "design.jsonl"
            s.write_text(json.dumps({"status": "ok", "units": [{"id": self.STRUCTURE_MARK, "paths": ["a.py"]}]}),
                         encoding="utf-8")
            j.write_text(json.dumps({"unit_id": self.DESIGN_ROW_MARK, "verdict": "汚れる"}) + "\n", encoding="utf-8")
            planted += [str(s), str(j)]
        entry.snapshot(pathlib.Path(self.bd), design.SNAPSHOT_NAME, pathlib.Path(self.repo))
        text = design.prep(self.bd, self.repo)["prompt"]
        ledger = json.loads((pathlib.Path(self.bd) / design.PREMISES_FILE).read_text(encoding="utf-8"))
        kinds = getattr(design, "PREMISE_KINDS", None)
        self.assertIsNotNone(kinds, "独立設計に渡す入力の種類の一覧（design.PREMISE_KINDS）が無い")
        self.assertEqual(set(kinds), {"human_answer", "named_section", "repo_map"})
        self.assertLessEqual({g["kind"] for g in ledger["given"]}, set(kinds))
        self.assertIn(self.HUMAN_ITEM["note"], text, "一覧の中の種類（人の答え）は届く")
        dumped = json.dumps(ledger, ensure_ascii=False)
        for leak in (self.STRUCTURE_MARK, self.DESIGN_ROW_MARK, *planted):
            self.assertNotIn(leak, text, f"独立設計の役に {leak!r} が届いた")
            self.assertNotIn(leak, dumped, f"控えに {leak!r} が載った")

    R2_DESIGN_INPUTS = {
        "reads": ["out.p0.purpose.purpose_text", "record.process.constraints", "loop.drift_notes",
                  "loop.purpose_review_stale", "inputs.policy_md"],
        "prompt_file": "../prompts/review-loop/r2.design.md",
        "prompt_append": ["../prompts/policy-paste.md", "../prompts/policy.md"],
        "fresh_context": True,
        "cond": "r2_design_due",
    }

    def test_r2_design_inputs_are_exactly_the_allowlist(self):
        """写しの graph の r2.design に本文が入る欄（reads・prompt_file・prompt_append・fresh_context・cond）は許可の一覧と等しい。
        graphloops の版の差し替えで入口が増えれば、名前が構造のブロックの出力と違っても赤になる（design.PREMISE_KINDS の柵の外の半分）"""
        graph = json.loads((CORE / "graphloops" / "graphs" / "review-loop.json").read_text(encoding="utf-8"))
        node = graph["nodes"]["r2.design"]
        self.assertEqual({k: node.get(k) for k in self.R2_DESIGN_INPUTS}, self.R2_DESIGN_INPUTS)
        for leak in ("structure", "design_file", "design.jsonl"):
            for v in (*node["reads"], node["prompt_file"], *node["prompt_append"]):
                self.assertNotIn(leak, v, f"独立設計の役の入力 {v!r} が構造のブロックの出力を名指す")

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
        b = entry.open_board(self.bd, allow_halted=True)
        self.assertEqual(eyes._gave_up(eyes._read_json(eyes._work(b, self.rnd, eyes.REJECTS_NAME), [])), ["r2-compare"])
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
        self.assertEqual(eyes._node_state(entry.open_board(self.bd, allow_halted=True), self.rnd, "r2.compare"), "stopped",
                         "比較の目は残ったまま盤面と一緒に止まる")
        self.assertEqual(state(self.bd)["stop"]["by"], eyes.STOP_BY)

    def _premise_reply(self, why):
        """設計書 docs/spec.md（3 行）を固めた版に置き、問いが立たない返答を premise_invalid_reason=why で受け付けに通す"""
        self.board("r1r2", made=None)
        commit_file(self.repo, "docs/spec.md", "一\n二\n三\n")
        entry.snapshot(pathlib.Path(self.bd), design.SNAPSHOT_NAME, pathlib.Path(self.repo))
        reply = {**DESIGN_INVALID, "premise_invalid_reason": why} if why is not None else DESIGN_INVALID
        return design.accept_reply(self.bd, json.dumps(reply, ensure_ascii=False), self.repo)

    def test_premise_anchor_in_range_is_accepted(self):
        got = self._premise_reply("docs/spec.md:2-3 に既に在る")
        self.assertTrue(got["ok"], got)

    def test_premise_anchor_out_of_range_is_rejected(self):
        got = self._premise_reply("docs/spec.md:9 に既に在る")
        self.assertFalse(got["ok"])
        self.assertIn(design.PREMISE_MISS, got["reason"])
        self.assertIn("docs/spec.md:9（行の範囲の外（ファイルは 3 行））", got["reason"])

    def test_premise_anchor_untracked_is_rejected(self):
        got = self._premise_reply("nowhere.md:1 に在る")
        self.assertFalse(got["ok"])
        self.assertIn("固めた版にファイルが無い", got["reason"])

    def test_premise_host_port_is_not_rejected(self):
        """host:port は根拠の名指しでないので拒まない（拒み続けて設計を諦めない）"""
        got = self._premise_reply("db.internal:5432 の接続は既に在る")
        self.assertTrue(got["ok"], got)

    def test_premise_without_anchor_is_accepted(self):
        """名指しの無い根拠は拒まない（事前審査と報告が「根拠の実物の名指しなし」と名指す）"""
        got = self._premise_reply(None)
        self.assertTrue(got["ok"], got)

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

    def test_unpassed_claim_is_matched_with_given_inputs(self):
        """R2 が『渡されていない』と書いた文を控えの given と機械で突き合わせ、実は渡していた行を最後の関所に並べる。
        当たらない文（渡していない設計書の節）は並べない。拒まず、verdict も書き換えない"""
        got, out = self._compare_with({"status": "redesign-needed", "reason": f"{self.UNPASSED}。古い縛りのまま比べた",
                                       "differences": [{"kind": "構造", "text": self.UNPASSED_DIFF}]})
        self.assertTrue(got["ok"], got)
        self.assertEqual(out["reviews"]["R2"]["status"], "redesign-needed", "verdict は書き換えない")
        lib = str(ROOT / "darkfactory" / "lib")
        if lib not in sys.path:
            sys.path.insert(0, lib)
        import line_edge
        lines = [s for s in line_edge._r2_inputs(entry.open_board(self.bd)) if "渡していた" in s]
        self.assertTrue([s for s in lines if self.UNPASSED in s and self.GATE_NOTE in s],
                        f"渡されていないと書いた文と、実は渡していた人の関所の答えが 1 行に並ぶ: {lines}")
        self.assertFalse([s for s in lines if self.UNPASSED_DIFF in s], "渡していない物の文は突き合わせに当たらない")

    def test_named_section_claim_matches_only_by_path_or_number(self):
        """貼った設計書の節には、『渡されていない』の文がそのパスか節番号を含む時だけ当てる。「設計書」の一般語だけの文
        （別の設計書の節のことかもしれない）や、番号の違う節の文は当てない"""
        given = [{"kind": "named_section", "what": "docs/spec.md#2-上限"},
                 {"kind": "named_section", "what": "docs/spec.md 3 節"}]
        hit = ["docs/spec.md の本文が渡されていない", "§3 の撤収が渡っていない", "2 節の上限が渡されていない"]
        miss = ["別の設計書の節が渡されていない", "設計書が渡っていない", "12 節が渡されていない", "§3.1 が渡っていない"]
        got = {c for c in hit + miss if design.claims_given([c], given)}
        self.assertEqual(got, set(hit))

    def test_unpassed_map_claim_matches_repo_map(self):
        """『地図が渡されていない』の文は、貼った地図（kind repo_map）の行に当たる"""
        self.assertEqual(len(design.claims_given(["地図が渡されていない"], [{"kind": "repo_map", "what": "ARCHITECTURE.md:1-3"}])), 1)

    def test_no_unpassed_claim_leaves_claims_empty(self):
        _, out = self._compare_with(COMPARE_OK)
        self.assertIn("premise_inputs", out)
        self.assertEqual(out["premise_inputs"]["claims"], [])

    def test_answers_after_design_are_listed_apart(self):
        """独立設計が見た人の答えの境目を控えに印し、その後に来た答え（比べる時点の答えまで読むので compare にだけ渡る）を
        突き合わせの控えと最後の関所に分けて並べる。拒まず、verdict も変えない"""
        early, late = "EARLY-設計の前の答え", "LATE-設計の後の答え"
        self.board("r1r2", made=None)
        rp = pathlib.Path(self.bd) / "record.json"

        def add(rnd, note):
            rec = json.loads(rp.read_text(encoding="utf-8"))
            rec.setdefault("process", {}).setdefault("human_items", []).append(
                {"round": rnd, "kinds": ["policy"], "asked": ["ASKED-本文"], "answer": "continue", "note": note})
            rp.write_text(json.dumps(rec, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

        add(1, early)
        entry.snapshot(pathlib.Path(self.bd), design.SNAPSHOT_NAME, pathlib.Path(self.repo))
        design.prep(self.bd, self.repo)
        self.assertTrue(design.accept_reply(self.bd, json.dumps(DESIGN_OK, ensure_ascii=False), self.repo)["ok"])
        self.assertTrue(design.hand(entry.open_board(self.bd), self.bd, self.repo)["handed"])
        add(2, late)
        self.enter()
        for role in ("r1-comments", "r1-minimality"):
            self.run_eye(role, REPLY[role])
        self.run_eye("r2-compare", COMPARE_OK)
        pi = eyes.collect(self.bd, self.rnd)["premise_inputs"]
        self.assertTrue(set(pi["design"]) - {"node", "given", "withheld"},
                        f"独立設計の控えに、見た人の答えの境目の印が在る: {pi['design']}")
        after = json.dumps({k: v for k, v in pi["compare"].items() if k not in ("node", "given", "withheld")},
                           ensure_ascii=False)
        self.assertIn(late, after, "突き合わせの控えに、独立設計の後に来た答えが別の欄で載る")
        self.assertNotIn(early, after, "独立設計が見た答えは後から来た答えに数えない")
        lib = str(ROOT / "darkfactory" / "lib")
        if lib not in sys.path:
            sys.path.insert(0, lib)
        import line_edge
        lines = [s for s in line_edge._r2_inputs(entry.open_board(self.bd)) if "独立設計の後に来た人の答え" in s]
        self.assertTrue(lines and late in lines[0] and early not in lines[0], lines)

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
        self.assertTrue(out["ok"], out)
        b = entry.open_board(self.bd, allow_halted=True)
        self.assertEqual({eyes.ROLE_OF[n]: eyes._node_state(b, self.rnd, n) for n in eyes.ROLE_OF},
                         {"r1-comments": "done", "r1-minimality": "done", "r2-compare": "done", "r3-coherence": "na",
                          "r4-scope": "na", "premise-check": "na"})
        self.assertEqual(out["reviews"]["R1"]["status"], "pass")
        self.assertEqual(out["reviews"]["R2"]["status"], "pass")
        # 同じ物を入口の周の eyes-exit.json に書く（最後の関所の文が premise_inputs を読む）
        self.assertEqual(eyes._read_json(eyes._work(b, self.rnd, eyes.EXIT_NAME), None), out)

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
        self.assertTrue(out["ok"], out)
        self.assertTrue(state(self.bd).get("pending_human"))
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
            self.assertTrue(self.ok("route", role=role, round=rnd, skip="")["go"], role)
            exited, rounds = self.run_loop(role, REPLY[role], rnd)
            self.assertEqual(exited, 1, rounds)
            self.assertEqual(rounds[0][1]["reason_file"], "")
        self.assertFalse(self.ok("route", role="premise-check", round=rnd, skip="")["go"])
        out = self.ok("collect", round=rnd)
        self.assertTrue(out["ok"], out)
        self.assertEqual((out["reviews"]["R1"]["status"], out["reviews"]["R2"]["status"]), ("pass", "pass"))

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
            self.assertTrue(self.ok("route", role=role, round=rnd, skip="")["go"], role)
            prep(role, rnd)
        # R2 が premise-invalid の盤面（設計が問いは立たないと返した）: stop.premise_check
        self.board("r1r2", made=DESIGN_INVALID)
        rnd = self.ok("enter")["round"]
        self.assertTrue(self.ok("route", role="premise-check", round=rnd, skip="")["go"])
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
        rc, out, err = self.run_script("route", role="no-such", round=1, skip="")
        self.assertEqual((rc, out), (2, ""), err)
        rc, out, err = self.run_script("route", role="r1-comments", round="一", skip="")
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
        self.assertEqual(set(self.y.get("inputs") or {}), {"skip_optional"})
        self.assertEqual(self.y["inputs"]["skip_optional"]["default"], "")
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
                self.assertEqual(self.top[f"{role}-route"]["with"]["skip"], "$INPUTS.skip_optional")
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
        """筋ごとに route → 輪 を縦に並べ、筋の頭の route は入口と、その筋が待つ筋（eyes.LANE_AFTER）の最後の route・輪の後。
        collect は全部の筋の最後を待つ"""
        for lane in eyes.LANES:
            prev = None
            for nid in lane:
                role = eyes.ROLE_OF[nid]
                r = self.top[f"{role}-route"]
                with self.subTest(role):
                    if prev is None:
                        after = eyes.LANE_AFTER.get(nid, ())
                        self.assertEqual(r["depends_on"], ["eyes-enter"] + [f"{eyes.ROLE_OF[w[-1]]}-{k}" for w in after
                                                                            for k in ("route", "loop")])
                        self.assertEqual(r.get("trigger_rule"), "all_done" if after else None)
                    else:
                        # 前の輪は飛ばされうる（条件で na の目）。いつも走る前の route も待てば「1 つは成功」が満ちる
                        self.assertEqual(r["depends_on"], [f"{prev}-route", f"{prev}-loop"])
                        self.assertEqual(r.get("trigger_rule"), "none_failed_min_one_success")
                    self.assertEqual(r["with"], {"role": role, "round": "$eyes-enter.output.round", "skip": "$INPUTS.skip_optional"})
                prev = role
        c = self.top["eyes-collect"]
        want = {f"{eyes.ROLE_OF[lane[-1]]}-{k}" for lane in eyes.LANES for k in ("route", "loop")}
        self.assertEqual(set(c["depends_on"]), want)
        self.assertEqual(c["trigger_rule"], "all_done")

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

    def test_minimality_knows_where_handoffs_go(self):
        """R1 の指示は、修正の返答の breaks.accepted の行が機械で人の口（報告の人が決めること・最後の関所）に
        載ることを知る（役・段の語は使わない）——台帳に無いことだけで逃げ道と数えない（実の利用者の run 97fd532f の R1 の (2)）。中身で見るのは残す"""
        text = (BLK / "commands" / "r1-minimality.md").read_text(encoding="utf-8")
        for w in ("`breaks.accepted`", "人に見せる一覧", "台帳に無いことだけ", "中身で見よ"):
            self.assertIn(w, text)

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
