"""借りたスキルの座（.shared/core/seat.py。計画 220 Task 2）の検査。216 の写しと seams.json を読むだけ（FAST。盤面・git・子のプロセスなし）。

語:
- 節（seam）: .shared/borrow/seams.json の 1 項目。use_as が skill（スキル 1 本を Skill の道具で読ませる）か prompt（部品の型の穴を
  埋めて指示書に置く）。
- 座: 節を役に載せる口。seat.SEATS（印の節の名 → 節の名）が表で持ち、修正の形が g3 の時だけ文が出る。
- 読み替え: .shared/borrow/unattended.md。rolekit.skill_overlay() が頭の 1 行と全文を返し、座の末尾に載る。

見る物:
- g3 でない形・座の無い節は空
- skill の座はスキルの名・Skill の道具・効く所・効かない所・読み替えを持つ
- prompt の座は 216 の fill で穴を全部埋める（残りの検査は座の本文だけに当て、読み替えの全文には当てない）。値が無ければ ValueError
- 写しが固定（pin）と 1 バイトでも違えば ValueError（af の文へ黙って逃げない。Review Focus 5）
- 座の skill の節は fixshape.SKILL_NODES と同じで、YAML で skills: と Skill を宣言する（prompt の座の節は skills: を持たない）。
  YAML は blk-fix（tdd・fix・fix-ruled）・blk-delta（review）・blk-refix（refix・refix2）
- 差分の審査役（1 回目だけ）の座（task-review）は型の後ろに判定の語の欄の表（型の語がどの欄のどの値に当たるか。欄の値は
  指示書 delta-review.md の決まりで返答の行から決まる）を持ち、勝つ物の段落は指示書を名指す。型の読み方の決まり（差分の外を
  読むな・変わったファイルを別に読むな）は指示書の読む義務に負ける（読み替えの CRAWL。型の段落は錨で縛る）
- 申し出の種類の手引き（DIVERGENCE_HINT）: 型の状態の語 NEEDS_CONTEXT・BLOCKED（works の語 divergence）に当たる時にどの kind
  で申し出るかを、conflict.DIV_KINDS の 1 語に 1 行で持つ。座のうち語に divergence を持つ節（implementer。修正役の fix・fix-ruled）
  と g1 の修正役の節に載り、ほかの座には載らない
- 修正の形 g1 の節（g1_section）: 見出し・Agent・項目ごとの実装役と審査役のファイル・読み替えを持ち、読み替えの DISPATCH を
  名指して上書きする（Preflight F18）。下請けのファイルの型（g1_prompt）は穴を残さず、works の決まりと検索語の規律の塊を持つ
  （run 221 の R4 の 3）。YAML で Agent を持つ節は fixshape.AGENT_NODES と同じ
"""
import json
import pathlib
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

import yaml

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.dont_write_bytecode = True   # 下の import が pack の中に __pycache__ を作らないように
sys.path.insert(0, str(ROOT / ".shared" / "core"))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import adapter  # noqa: E402
import conflict  # noqa: E402
import deltamarks  # noqa: E402
import fixshape  # noqa: E402
import rolekit  # noqa: E402
import seat  # noqa: E402
import spseam  # noqa: E402
from gitkit import committed_copy, git  # noqa: E402

HOLE = re.compile(r"\[[A-Z][A-Z_]+\]")   # 埋めていない大文字の穴（[BRIEF_FILE] の類い）


def find_node(nodes, nid):
    """節の一覧（loop_group の中も辿る）から id が nid の節"""
    for n in nodes:
        if n.get("id") == nid:
            return n
        if "loop_group" in n:
            got = find_node(n["loop_group"]["nodes"], nid)
            if got is not None:
                return got
    return None


def all_nodes(nodes):
    """節の一覧（loop_group の中も）を平らにした並び"""
    for n in nodes:
        yield n
        if "loop_group" in n:
            yield from all_nodes(n["loop_group"]["nodes"])


def own_part(text: str) -> str:
    """座の文のうち読み替え（末尾の skill_overlay）を除いた本文"""
    overlay = rolekit.skill_overlay().strip()
    assert text.rstrip("\n").endswith(overlay), text[-200:]
    return text[:text.rindex(overlay)]


class SeatCase(unittest.TestCase):
    def values(self):
        return {p: f"<{i}>" for i, p in enumerate(spseam.load_seams()["implementer"]["placeholders"])}

    def test_section_empty_unless_g3(self):
        for shape in ("current", "af", "g1"):
            self.assertEqual(seat.section("tdd", shape), "")
            self.assertEqual(seat.section("fix", shape, self.values()), "")
        self.assertEqual(seat.section("rule", "g3"), "")              # 座の無い節

    def test_tdd_seat_names_skill_applies_and_overlay(self):
        text = seat.section("tdd", "g3")
        s = spseam.load_seams()["tdd"]
        for w in (seat.HEAD, "Skill", "test-driven-development", *s["applies"], *s["not_applies"],
                  rolekit.skill_overlay().strip()):
            self.assertIn(w, text)
        self.assertTrue(text.startswith(seat.HEAD))
        self.assertEqual(seat.skill_of(s), "test-driven-development")

    def test_both_seat_kinds_share_the_wins_paragraph(self):
        """借りた文に何が勝つかの段落は skill の座と prompt の座で同じ 1 つ。skill の座はその前に Skill の道具で読めの 1 文だけを足す"""
        self.assertEqual(seat.WINS, "この指示書の段の約束（返す JSON・機械の関門・段の順）と下の読み替えは、借りた文に勝つ")
        tdd = own_part(seat.section("tdd", "g3"))
        self.assertIn(f"Skill の道具で `test-driven-development` を読み、その手順で進めよ。{seat.WINS}", tdd)
        fix = own_part(seat.section("fix", "g3", self.values()))
        self.assertEqual(fix.split("\n\n")[1], seat.WINS, "prompt の座は見出しの次がその段落")
        for text in (tdd, fix):
            self.assertEqual(text.count(seat.WINS), 1)

    def test_fix_seat_fills_implementer(self):
        text = seat.section("fix", "g3", self.values())
        self.assertIn("<1>", text)
        own = own_part(text)   # 残りの検査は座の本文だけに当てる（読み替えの全文には当てない。Preflight F8）
        self.assertNotRegex(own, HOLE)
        self.assertNotIn("[task name]", own)
        self.assertIn("implementer-prompt.md", own)
        self.assertEqual(seat.section("fix-ruled", "g3", self.values()), text, "2 回目の修正役も同じ型")
        with self.assertRaises(ValueError):
            seat.section("fix", "g3", None)

    def test_fix_seat_refuses_broken_pin(self):
        with mock.patch.object(seat.spseam, "fill", side_effect=ValueError("implementer-prompt.md: 中身が固定と違う")):
            with self.assertRaises(ValueError):
                seat.section("fix", "g3", {"[BRIEF_FILE]": "x"})

    def test_one_byte_off_the_pin_refuses_every_seat(self):
        """本物の写しを一時の置き場に写し、1 バイトだけ変えると、座は名指して ValueError（Preflight F9）"""
        for rel, node in (("skills/subagent-driven-development/implementer-prompt.md", "fix"),
                          ("skills/test-driven-development/SKILL.md", "tdd")):
            with self.subTest(node), tempfile.TemporaryDirectory() as d:
                borrow = pathlib.Path(d) / "borrow"
                shutil.copytree(spseam.BORROW_DIR, borrow)
                item = json.loads((borrow / "borrow.json").read_text(encoding="utf-8"))["superpowers"]
                p = spseam.vendored_dir(item, borrow) / rel
                raw = bytearray(p.read_bytes())
                raw[-2] = ord("x") if raw[-2] != ord("x") else ord("y")
                p.write_bytes(bytes(raw))
                with mock.patch.object(spseam, "BORROW_DIR", borrow):
                    with self.assertRaisesRegex(ValueError, re.escape(rel)):
                        seat.section(node, "g3", self.values())

    def review_values(self):
        return {p: f"<{i}>" for i, p in enumerate(spseam.load_seams()["task-review"]["placeholders"])}

    def test_verdict_words_cover_task_review_words(self):
        """task-review の型の出口の語（216 の works の語）は全部、差分の審査の返答の 2 判定の欄（deltamarks）の欄と語に読む"""
        self.assertEqual(set(spseam.load_seams()["task-review"]["words"].values()), set(seat.VERDICT_WORDS))
        for word, (key, value) in seat.VERDICT_WORDS.items():
            with self.subTest(word):
                self.assertIn(key, deltamarks.KEYS)
                self.assertIn(value, deltamarks.FIELD_SCHEMA[key]["properties"]["verdict"]["enum"])

    def test_words_table_rows_and_refusal(self):
        """語の対応の表は型の語・works の語・欄の値の 3 列で、型の語ごとに 1 行。対応に無い語を持つ節は ValueError"""
        table = seat.words_table("task-review")
        rows = [r for r in table.splitlines() if r.startswith("| ") and "---" not in r]
        line = next(r for r in rows if "✅ Spec compliant" in r)
        self.assertIn("compliance_pass", line)
        self.assertIn("`compliance.verdict`", line)
        self.assertIn("`pass`", line)
        # 表は型の語の欄を示すだけ。欄の値は返答の行から決まり、指示書が勝つ（項目の無い run の not_applicable・結ばれない穴の fail）
        self.assertIn("delta-review.md", seat.WORDS_HEAD)
        self.assertIn("指示書が勝つ", seat.WORDS_HEAD)
        self.assertIn("`compliance.verdict`: `not_applicable`", table)
        self.assertIn("`quality.verdict`: `fail`", table)
        self.assertEqual(len(rows), 1 + len(seat.VERDICT_WORDS) + len(seat.NOTE_ROWS))
        with self.assertRaises(ValueError):
            seat.words_table("implementer")   # 出口の語が判定の欄でない節

    def test_review_seat_has_filled_part_and_table(self):
        """差分の審査役の座（g3）は task-review の型の 6 つの穴を埋めた文と、その後ろの語の対応の表を持つ。2 回目の審査役も同じ型"""
        text = seat.section("review", "g3", self.review_values())
        own = own_part(text)
        self.assertNotRegex(own, HOLE)
        self.assertIn("task-reviewer-prompt.md", own)
        self.assertIn("✅ Spec compliant", own)
        self.assertIn(seat.words_table("task-review"), own)
        self.assertLess(own.index("<5>"), own.index(seat.words_table("task-review")), "表は型の後ろ")
        self.assertEqual(seat.section("review2", "g3", self.review_values()), "", "2 回目の審査役には座が無い（返答に判定の欄が無い）")
        wins = own.split("\n\n")[1]
        self.assertIn("commands/delta-review.md", wins, "勝つ物の段落は座のファイルの外の指示書を名指す")
        self.assertIn(seat.WINS_OF["review"], own)

    def test_review_seat_yields_template_reading_rules_to_the_command(self):
        """型の『差分の外を読むな』『変わったファイルを別に読むな』は、指示書の読む義務（読む側・呼び元・今の姿）に負ける。
        読み替えの決まり CRAWL が言い、型のその段落は task-review の錨で縛る（版を上げて段落が変われば固定の試験が赤）。
        指示書の座の行も同じことを言う"""
        overlay = rolekit.skill_overlay()
        m = re.search(r"^## CRAWL .*?(?=^## |\Z)", overlay, re.M | re.S)
        self.assertIsNotNone(m)
        for w in ("Do not crawl the broader codebase", "delta-review.md", "呼び元"):
            self.assertIn(w, m.group(0))
        anchors = {a["rule"]: a for a in spseam.load_seams()["task-review"]["anchors"]}
        self.assertEqual(anchors["CRAWL"]["quote"], "Do not crawl the broader codebase")
        line = next(x for x in (ROOT / "blk-delta" / "commands" / "delta-review.md").read_text(encoding="utf-8").splitlines()
                    if "`seat_file`" in x)
        for w in ("Do not crawl", "呼び元", "このコマンドが勝つ", "not_applicable"):
            self.assertIn(w, line)
        with tempfile.TemporaryDirectory() as d:   # 型の錨の段落を 1 語変えると、節の契約の破れに CRAWL が出る
            borrow = pathlib.Path(d) / "borrow"
            shutil.copytree(spseam.BORROW_DIR, borrow)
            item = json.loads((borrow / "borrow.json").read_text(encoding="utf-8"))["superpowers"]
            src = spseam.vendored_dir(item, borrow)
            p = src / anchors["CRAWL"]["file"]
            p.write_text(p.read_text(encoding="utf-8").replace("Inspect code outside", "Inspect any code outside"), encoding="utf-8")
            got = spseam.seam_problems(src, item, spseam.load_seams(), overlay)
            self.assertTrue(any("CRAWL" in g for g in got), got)
        for shape in ("current", "af", "g1"):
            self.assertEqual(seat.section("review", shape, self.review_values()), "")

    def test_divergence_hint_names_every_kind(self):
        """手引きは状態の語 NEEDS_CONTEXT・BLOCKED と works の語 divergence を名指し、211 の種類（conflict.DIV_KINDS）の 1 語に 1 行
        （行の頭がその語。並びも DIV_KINDS の順）"""
        hint = seat.DIVERGENCE_HINT
        for w in ("NEEDS_CONTEXT", "BLOCKED", conflict.WORD, "conflicts", conflict.KIND_FIELD):
            self.assertIn(w, hint)
        rows = [line for line in hint.splitlines() if line.startswith("- ")]
        self.assertEqual([r.split("`")[1] for r in rows], list(conflict.DIV_KINDS))
        for k in conflict.DIV_KINDS:
            self.assertEqual(hint.count(f"`{k}`"), 1, k)

    def test_divergence_hint_rides_the_implementer_seats_only(self):
        """手引きは語に divergence を持つ座（implementer。修正役の fix・fix-ruled）の本文に 1 度、読み替えの前に載る。ほかの座と
        g3 でない形には載らない"""
        for node in ("fix", "fix-ruled"):
            with self.subTest(node):
                text = seat.section(node, "g3", self.values())
                own = own_part(text)
                self.assertEqual(own.count(seat.DIVERGENCE_HINT), 1)
                self.assertLess(own.index("implementer-prompt.md"), own.index(seat.DIVERGENCE_HINT))
        for node, values in (("tdd", None), ("review", self.review_values()), ("refix", None), ("refix2", None)):
            with self.subTest(node):
                self.assertNotIn(seat.DIVERGENCE_HINT, seat.section(node, "g3", values))
        for shape in ("current", "af", "g1"):
            self.assertNotIn(seat.DIVERGENCE_HINT, seat.section("fix", shape, self.values()))

    def test_refix_seat_names_receiving_review(self):
        """手直しの役の座（g3）は receiving-code-review を Skill の道具で読ませ、効く所・効かない所と読み替えを持つ"""
        s = spseam.load_seams()["receiving-review"]
        for node in ("refix", "refix2"):
            with self.subTest(node):
                text = seat.section(node, "g3")
                for w in (seat.HEAD, "Skill", "receiving-code-review", *s["applies"], *s["not_applies"]):
                    self.assertIn(w, text)
                self.assertEqual(seat.section(node, "af"), "")

    def test_skill_seats_are_the_fenced_nodes(self):
        seams = spseam.load_seams()
        self.assertTrue(set(seat.SEATS.values()) <= set(seams))
        self.assertEqual({n for n, s in seat.SEATS.items() if seams[s]["use_as"] == "skill"}, fixshape.SKILL_NODES)

    def test_yaml_skill_seats_declare_the_skill(self):
        """座の skill の節は YAML で skills: にちょうどそのスキルを持ち、allowed_tools に Skill を持つ。prompt の座の節は skills: を持たない
        （direct の修正役に test-driven-development を宣言しない。事前審査 tdd-skill-on-direct-fix-node）"""
        seams = spseam.load_seams()
        nodes = yaml.safe_load((ROOT / "blk-fix" / "blk-fix.yaml").read_text(encoding="utf-8"))["nodes"]
        blocks = [nodes] + [yaml.safe_load((ROOT / blk / f"{blk}.yaml").read_text(encoding="utf-8"))["nodes"]
                            for blk in ("blk-delta", "blk-refix")]   # 差分の審査役（review）と手直し・2 回目の審査（refix・review2・refix2）
        for nid, sid in seat.SEATS.items():
            with self.subTest(nid):
                node = next((n for ns in blocks if (n := find_node(ns, nid)) is not None), None)
                self.assertIsNotNone(node)
                if seams[sid]["use_as"] == "skill":
                    self.assertEqual(node.get("skills"), [seat.skill_of(seams[sid])])
                    self.assertIn("Skill", node["allowed_tools"])
                else:
                    self.assertNotIn("skills", node)
                    self.assertNotIn("Skill", node["allowed_tools"])
        # 修正役の節（fix・fix-ruled）は Agent を持ち（g1 の下請け）、輪の役の節（tdd）も持つ（g3 の並べの周の単位の下請け）。
        # Agent を持つ節の集まりは柵の表 AGENT_NODES と LANE_NODES の和と同じ
        for nid in ("fix", "fix-ruled", "tdd"):
            self.assertIn("Agent", find_node(nodes, nid)["allowed_tools"], nid)
        self.assertEqual({n["id"] for n in all_nodes(nodes) if "Agent" in (n.get("allowed_tools") or [])},
                         set(fixshape.AGENT_NODES | fixshape.LANE_NODES))


class G1Case(unittest.TestCase):
    """修正の形 g1: 修正役が SDD の型で下請けを回す節と、下請けに渡すファイルの型"""

    def test_g1_section_lists_files_and_overlay(self):
        rows = [{"item": 1, "impl_file": "/b/r1/g1-impl-1.md", "review_file": "/b/r1/g1-review-1.md", "base": "abc123", "patch": "/a/run-place/g1-1.patch"}]
        text = seat.g1_section(rows)
        for w in (seat.G1_HEAD, "Agent", "/b/r1/g1-impl-1.md", "/b/r1/g1-review-1.md", rolekit.skill_overlay().strip()):
            self.assertIn(w, text)
        self.assertTrue(text.startswith(seat.G1_HEAD))

    def test_g1_section_overrides_dispatch_by_name(self):
        """読み替えは『下請けを起こさない。ほかの役の道具に Agent は無い』と言う。g1 の節は読み替えの前で、その決まりを名指して
        修正役には効かないと書く（216 の読み替えは変えない。Preflight F18）"""
        text = seat.g1_section([{"item": 2, "impl_file": "i", "review_file": "r", "base": "abc123", "patch": "/a/run-place/g1-1.patch"}])
        self.assertIn(seat.G1_OVERRIDES, text)
        for name in ("DISPATCH", "DELEGATE"):
            self.assertIn(name, seat.G1_OVERRIDES)
        self.assertLess(text.index(seat.G1_OVERRIDES), text.index(rolekit.skill_overlay().splitlines()[0]))

    def test_g3_section_names_its_shape_and_the_loop_units(self):
        """既定の形 g3 の修正役も同じ下請けの節で単位ごとに新しい会話を起こす（依頼 243 の 2）。見出しと読み替えの上書きは形を
        名指し、輪で直した単位には下請けを起こさない旨（G1_LOOP_NOTE）を持つ。g1 の節は前と同じ見出しで、その旨を持たない"""
        rows = [{"item": 1, "impl_file": "i", "review_file": "r", "base": "abc123", "patch": "/a/run-place/g1-1.patch"}]
        g3 = seat.g1_section(rows, "g3")
        self.assertTrue(g3.startswith("## 下請けを回す（修正の形 g3）"))
        self.assertIn("修正の形 g3 のこの修正役", g3)
        self.assertNotRegex(g3, r"修正の形 g1(?!・g3)")   # 読み替えの「g1・g3」の外に g1 を名指さない
        self.assertIn(seat.G1_LOOP_NOTE, g3)
        g1 = seat.g1_section(rows)
        self.assertEqual(g1, seat.g1_section(rows, "g1"))
        self.assertTrue(g1.startswith(seat.G1_HEAD))
        self.assertNotIn(seat.G1_LOOP_NOTE, g1)
        with self.assertRaises(ValueError):
            seat.g1_section(rows, "af")   # 下請けを起こさない形（包みが Agent を拒む）には組まない

    def test_g1_section_hands_off_earlier_items(self):
        """2 つ目からの項目の実装役には、前の項目の実装役の報告から変えたファイルと緑にしたテストを渡す（会話の履歴でなく引き継ぎ）"""
        text = seat.g1_section([{"item": 1, "impl_file": "i", "review_file": "r", "base": "abc123", "patch": "/a/g1-1.patch"}])
        self.assertIn(seat.G1_HANDOFF_HEAD, text)

    def test_g3_prompts_name_their_shape(self):
        values = {p: "x" for p in spseam.load_seams()["implementer"]["placeholders"]}
        self.assertIn("修正の形 g3 の下請け", seat.g1_prompt("implementer", values, "g3"))
        self.assertEqual(seat.g1_prompt("implementer", values), seat.g1_prompt("implementer", values, "g1"))

    def test_g1_section_items_in_order(self):
        rows = [{"item": n, "impl_file": f"/b/i{n}", "review_file": f"/b/r{n}", "base": "abc123", "patch": f"/a/g1-{n}.patch"}
                for n in (2, 5)]
        text = seat.g1_section(rows)
        self.assertLess(text.index("/b/i2"), text.index("/b/r2"))
        self.assertLess(text.index("/b/r2"), text.index("/b/i5"))

    def test_g1_prompts_fill_holes_and_carry_the_rules(self):
        """下請けのファイルは型の穴を全部埋め、works の決まり（commit しない・人に聞かない・報告は最後のメッセージ）と、検索語の
        規律の塊（包みが役の system prompt に足す物と字が同じ。Agent の子には届かないので、prompt に載せる）を持つ"""
        seams = spseam.load_seams()
        for sid in ("implementer", "task-review"):
            with self.subTest(sid):
                values = {p: f"<{i}>" for i, p in enumerate(seams[sid]["placeholders"])}
                text = seat.g1_prompt(sid, values)
                self.assertNotRegex(text, HOLE)
                self.assertIn("<1>", text)
                self.assertIn(seat.G1_SUB_HEAD, text)
                self.assertIn(adapter.query_rule(), text)
                self.assertLess(text.index("<1>"), text.index(seat.G1_SUB_HEAD), "型の後ろに決まり")
        with self.assertRaises(ValueError):
            seat.g1_prompt("implementer", {"[BRIEF_FILE]": "x"})   # 穴の値が足りない

    def test_g1_review_diffs_the_working_tree(self):
        """works は commit しないので、審査役の型の git diff は base と作業ツリーの差分（`git diff <base>`）。[HEAD_SHA] の行は
        作業ツリーと書き、範囲の `<base>..` はコマンドに残さない（Preflight F20 の続き）。修正役が書く差分のファイルが主の材料で、
        前の項目の直しも入ると審査役に書く"""
        values = {p: f"<{i}>" for i, p in enumerate(spseam.load_seams()["task-review"]["placeholders"])}
        text = seat.g1_prompt("task-review", {**values, "[BASE_SHA]": "abc123", "[HEAD_SHA]": seat.G1_HEAD_SHA})
        self.assertIn("`git diff abc123`", text)
        self.assertIn("`git diff --stat abc123`", text)
        self.assertNotIn("abc123..", text)
        self.assertIn(f"**Head:** {seat.G1_HEAD_SHA}", text)
        for rule in seat.G1_EXTRA["task-review"]:
            self.assertIn(rule, text)
        self.assertIn("前の項目", " ".join(seat.G1_EXTRA["task-review"]))
        impl = seat.g1_prompt("implementer", {p: "x" for p in spseam.load_seams()["implementer"]["placeholders"]})
        self.assertNotIn(seat.G1_EXTRA["task-review"][0], impl, "審査役だけの決まり")
        # 差分のファイルが無い時の手: git diff <base> の後に未追跡の新しいファイルの名を引き、それぞれを Read で読む
        for w in ("git diff <Base の版>", "git ls-files --others --exclude-standard", "Read"):
            self.assertIn(w, seat.G1_EXTRA["task-review"][0])
        # 下請けの決まりは型にも読み替え（unattended.md。GIT-RANGE の『審査役は Bash を持たない』を含む）にも勝つ
        for w in ("unattended.md", "GIT-RANGE"):
            self.assertIn(w, seat.G1_SUB_HEAD + " ".join(seat.G1_SUB_RULES))
        self.assertIn("unattended.md", seat.G1_SUB_HEAD)

    def test_g1_section_builds_the_patch_with_new_files(self):
        """手順の差分のファイル: リポジトリの根で git diff <base> と、未追跡の新しいファイルごとの git diff --no-index /dev/null を、
        支度が決めた run ごとの置き場の絶対パスに書く（並ぶ run が同じ $TMPDIR の名でぶつからない・Read が展開を要らない）"""
        text = seat.g1_section([{"item": 3, "impl_file": "i", "review_file": "r", "base": "abc123",
                                 "patch": "/a b/run-place/g1-3.patch"}])
        cmd = seat.G1_PATCH.format(base="abc123", patch="'/a b/run-place/g1-3.patch'")
        self.assertIn(cmd, text)
        for w in ("p='/a b/run-place/g1-3.patch'", 'top="$(git rev-parse --show-toplevel)"',
                  'git -C "$top" -c core.quotePath=false diff abc123 > "$p"',
                  'git -C "$top" -c core.quotePath=false ls-files --others --exclude-standard',
                  'git -C "$top" -c core.quotePath=false diff --no-index /dev/null "$f" >> "$p"'):
            self.assertIn(w, cmd)
        for t in (text, *seat.G1_EXTRA["task-review"]):
            self.assertNotIn("TMPDIR", t)

    def test_g1_patch_exits_zero_with_new_files(self):
        """差分のコマンドは、未追跡の新しいファイルが在っても 0 で終わり、最後に差分のファイルのパスを出す（最後の
        git diff --no-index は差分が在ると 1 を返す。修正役が Bash の失敗と読まないように。Task 7 の持ち越し）"""
        with tempfile.TemporaryDirectory() as td:
            repo, patch = pathlib.Path(td) / "repo", pathlib.Path(td) / "run place" / "g1-1.patch"
            base = committed_copy(repo, ROOT / "dev" / "target-seed")
            patch.parent.mkdir()
            (repo / "stats.py").write_text((repo / "stats.py").read_text(encoding="utf-8") + "\n# 直した\n", encoding="utf-8")
            (repo / "test_new.py").write_text("def test_new():\n    assert True\n", encoding="utf-8")
            cmd = seat.G1_PATCH.format(base=base, patch=shlex.quote(str(patch)))
            got = subprocess.run(["sh", "-c", cmd], cwd=repo, capture_output=True, text=True, encoding="utf-8")
            self.assertEqual(got.returncode, 0, got.stderr)
            self.assertEqual(got.stdout.strip(), str(patch))
            text = patch.read_text(encoding="utf-8")
            for w in ("stats.py", "# 直した", "test_new.py", "def test_new"):
                self.assertIn(w, text)
            self.assertEqual(git(repo, "rev-parse", "HEAD"), base, "commit しない")
            bad = subprocess.run(["sh", "-c", seat.G1_PATCH.format(base="0" * 40, patch=shlex.quote(str(patch)))], cwd=repo,
                                 capture_output=True, text=True, encoding="utf-8")
            self.assertNotEqual(bad.returncode, 0, "base の版が無ければ差分のファイルを作れず、失敗で終わる")
            self.assertNotIn(str(patch), bad.stdout)

    def test_g1_overrides_the_overlay_head_line(self):
        """読み替えの頭の行は『Agent で下請けを起こすなら、その prompt に unattended.md を Read せよと書け』と言う。g1 の修正役には
        下請けのファイルの決まりが代わりに持つと名指す"""
        self.assertIn("Read せよと書け", seat.G1_OVERRIDES)
        self.assertIn("Read せよと書け", rolekit.skill_overlay().splitlines()[0])

    def test_g1_steps_keep_failed_items_in_changes_and_redo_only_named(self):
        """3 回の審査を通らなかった項目の直す義務の単位も、どの形とも同じく changes に載せ、残った指摘は root_or_symptom（symptom）
        の why に書く。受け付けの最後の回がその単位に結べる拒否で、その単位の直しだけを戻して止める（強み 4。not_done に置くと
        拒否が単位に結べず、返答全体が拒まれる）。受け付けの出し直しと裁定の後は、拒否・裁定が名指す項目だけを起こし直す"""
        failed = next(t for t in seat.G1_STEPS if "3 回目の審査" in t)
        for w in ("changes に載せる", "root_or_symptom", "symptom", "why", "最後の回", "戻して止める", "conflicts"):
            self.assertIn(w, failed)
        self.assertNotIn("not_done", failed)
        steps = " ".join(seat.G1_STEPS)
        for w in ("出し直し", "裁定", "名指す項目だけ"):
            self.assertIn(w, steps)

    def test_g1_section_carries_the_divergence_hint(self):
        """g1 の修正役は実装役の下請けが NEEDS_CONTEXT・BLOCKED を返した時に申し出る。手引きは手順の後・読み替えの上書きの前に 1 度"""
        text = seat.g1_section([{"item": 1, "impl_file": "i", "review_file": "r", "base": "abc123", "patch": "/a/run-place/g1-1.patch"}])
        self.assertEqual(text.count(seat.DIVERGENCE_HINT), 1)
        self.assertLess(text.index(seat.G1_STEPS[-1]), text.index(seat.DIVERGENCE_HINT))
        self.assertLess(text.index(seat.DIVERGENCE_HINT), text.index(seat.G1_OVERRIDES))

    def test_g1_section_says_diffs_include_earlier_items(self):
        self.assertIn("前の項目", seat.g1_section([{"item": 1, "impl_file": "i", "review_file": "r", "base": "abc123", "patch": "/a/run-place/g1-1.patch"}]))

    def test_g3_section_runs_tree_items_side_by_side_then_merges(self):
        """機械が単位の worktree を切った項目（行に tree）は、1 つのメッセージで同時に起こし、済んだら機械の当てるコマンドを 1 回
        走らせ、conflict の項目を作業ツリーで直し直させてから順の項目へ進む（依頼 243 の並べ）。差分のコマンドはその worktree の差分"""
        rows = [{"item": 1, "impl_file": "i1", "review_file": "r1", "base": "b1", "patch": "/p/g1-1.patch", "tree": "/rp/units/item-1"},
                {"item": 2, "impl_file": "i2", "review_file": "r2", "base": "b1", "patch": "/p/g1-2.patch", "tree": "/rp/units/item-2"},
                {"item": 3, "impl_file": "i3", "review_file": "r3", "base": "b0", "patch": "/p/g1-3.patch"}]
        text = seat.g1_section(rows, "g3", merge="python3 /pack/unitlanes.py /b/units.json")
        para = seat.G1_PARALLEL_OF.format(merge="python3 /pack/unitlanes.py /b/units.json")
        self.assertIn(para, text)
        for w in ("1 つのメッセージ", "conflict", "differ", "bash_writes", "捨てない"):
            self.assertIn(w, para)
        self.assertLess(text.index(seat.G1_STEPS[-1]), text.index(para))
        self.assertIn("項目 1（並べる。単位の worktree /rp/units/item-1）", text)
        self.assertIn("項目 3: ", text, "順の項目は今の書き方のまま")
        self.assertIn("top=/rp/units/item-1;", text)
        self.assertEqual(text.count('top="$(git rev-parse --show-toplevel)"'), 1, "順の項目だけ cwd の根")
        plain = seat.g1_section([rows[2]], "g3")
        self.assertNotIn(seat.G1_PARALLEL_OF.split("{")[0], plain, "並べる項目が無ければ段落は載らない")

    def test_tree_prompts_keep_the_sub_inside_its_worktree(self):
        values = {p: "x" for p in spseam.load_seams()["implementer"]["placeholders"]}
        text = seat.g1_prompt("implementer", values, "g3", tree="/rp/units/item-1")
        self.assertIn(seat.G1_TREE_RULE_OF.format(tree="/rp/units/item-1"), text)
        self.assertNotIn("/rp/units", seat.g1_prompt("implementer", values, "g3"))

    def test_g1_prompt_refuses_unreadable_query_rule(self):
        with mock.patch.object(seat.adapter, "query_rule", side_effect=adapter.Unrecognised("頭の行が無い")):
            with self.assertRaisesRegex(ValueError, "検索語の規律"):
                seat.g1_prompt("implementer", {p: "x" for p in spseam.load_seams()["implementer"]["placeholders"]})


if __name__ == "__main__":
    unittest.main()
