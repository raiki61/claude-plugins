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
- 座の skill の節は fixshape.SKILL_NODES と同じで、YAML で skills: と Skill を宣言する（prompt の座の節は skills: を持たない）
"""
import json
import pathlib
import re
import shutil
import sys
import tempfile
import unittest
from unittest import mock

import yaml

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.dont_write_bytecode = True   # 下の import が pack の中に __pycache__ を作らないように
sys.path.insert(0, str(ROOT / ".shared" / "core"))

import fixshape  # noqa: E402
import rolekit  # noqa: E402
import seat  # noqa: E402
import spseam  # noqa: E402

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

    def test_skill_seats_are_the_fenced_nodes(self):
        seams = spseam.load_seams()
        self.assertTrue(set(seat.SEATS.values()) <= set(seams))
        self.assertEqual({n for n, s in seat.SEATS.items() if seams[s]["use_as"] == "skill"}, fixshape.SKILL_NODES)

    def test_yaml_skill_seats_declare_the_skill(self):
        """座の skill の節は YAML で skills: にちょうどそのスキルを持ち、allowed_tools に Skill を持つ。prompt の座の節は skills: を持たない
        （direct の修正役に test-driven-development を宣言しない。事前審査 tdd-skill-on-direct-fix-node）"""
        seams = spseam.load_seams()
        nodes = yaml.safe_load((ROOT / "blk-fix" / "blk-fix.yaml").read_text(encoding="utf-8"))["nodes"]
        for nid, sid in seat.SEATS.items():
            with self.subTest(nid):
                node = find_node(nodes, nid)
                self.assertIsNotNone(node)
                if seams[sid]["use_as"] == "skill":
                    self.assertEqual(node.get("skills"), [seat.skill_of(seams[sid])])
                    self.assertIn("Skill", node["allowed_tools"])
                else:
                    self.assertNotIn("skills", node)
                    self.assertNotIn("Skill", node["allowed_tools"])


if __name__ == "__main__":
    unittest.main()
