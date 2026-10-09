"""判断の 1 軸と考えの住処の観点の文・地図の探し方（.shared/core/concepthome.py。計画 2026-10-09-clean-whole の Task 2.1）。
文字列と名前の一覧だけを見る（git は差し替える）"""
import pathlib
import sys
import unittest
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.dont_write_bytecode = True
sys.path.insert(0, str(ROOT / ".shared" / "core"))
import concepthome as ch  # noqa: E402


class PickCase(unittest.TestCase):
    def test_pick_root_and_nested(self):
        self.assertEqual(ch.pick_maps(["docs/x.md", "works/docs/concepts.md", "docs/concepts.md", "a/docs/concepts.md.bak"]),
                         (["docs/concepts.md", "works/docs/concepts.md"], 2))

    def test_pick_caps(self):
        names = [f"p{i}/docs/concepts.md" for i in range(7)]
        self.assertEqual(ch.pick_maps(names), (names[:5], 7))

    def test_pick_tables_and_base(self):
        got = ch.pick_tables(["works/docs/concepts.json", "docs/concepts.json", "x/concepts.json"])
        self.assertEqual(got, ["docs/concepts.json", "works/docs/concepts.json"])
        self.assertEqual([ch.base_of(n) for n in got], ["", "works"])


class SectionCase(unittest.TestCase):
    def test_section_without_map(self):
        with mock.patch.object(ch, "tracked_names", return_value=([], "")):
            s = ch.section(pathlib.Path("/x"))
        self.assertIn("無い", s)
        self.assertIn(ch.MAP_NAME, s)

    def test_section_lists_maps_and_rest(self):
        names = [f"p{i}/docs/concepts.md" for i in range(7)]
        with mock.patch.object(ch, "tracked_names", return_value=(names, "")):
            s = ch.section(pathlib.Path("/x"))
        self.assertIn("ほか 2 件", s)
        self.assertIn("- p0/docs/concepts.md", s)

    def test_section_names_unreadable_tree(self):
        with mock.patch.object(ch, "tracked_names", return_value=([], "not a git repository")):
            s = ch.section(pathlib.Path("/x"))
        self.assertIn("木を読めなかった: not a git repository", s)


class TextCase(unittest.TestCase):
    def test_texts_carry_prefix_and_slot(self):
        for t in (ch.PLAN_RULE, ch.REVIEW_ASK, ch.R1_HEAD, ch.R3_HEAD):
            self.assertIn(ch.PREFIX.strip(), t)
        for t in (ch.R1_HEAD, ch.R3_HEAD):
            self.assertEqual(t.count("{section}"), 1)

    def test_axis_heads_every_text(self):
        """1 軸の文は、役に配るどの文にも在る（1 か所の文を配る）"""
        for t in (ch.PLAN_RULE, ch.REVIEW_ASK, ch.R1_HEAD, ch.R3_HEAD, ch.EYE_ASK):
            self.assertIn(ch.AXIS, t)


if __name__ == "__main__":
    unittest.main()
