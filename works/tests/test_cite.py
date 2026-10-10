"""名指しの形と場所の文の読みの住処 cite の試験（本物の cite・holeties・conflict・material を直に呼ぶ。FAST）"""
import pathlib
import sys
import unittest

TESTS = pathlib.Path(__file__).resolve().parent
ROOT = TESTS.parent
sys.dont_write_bytecode = True
for _p in (str(ROOT / ".shared" / "core"), str(ROOT / "blk-material" / "lib")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import cite  # noqa: E402
import conflict  # noqa: E402
import holeties  # noqa: E402
import material  # noqa: E402


class WhereCase(unittest.TestCase):
    def test_where_cites_carries_previous_path(self):
        self.assertEqual(cite.where_cites("works/a.py:3 と :5-7、b.md:2"),
                         [("works/a.py", "3", None), ("works/a.py", "5", "7"), ("b.md", "2", None)])
        self.assertEqual(cite.where_cites(":4 の話"), [("", "4", None)])


class QuotedInCase(unittest.TestCase):
    def test_one_quote_by_norm(self):
        """引用 1 つの照らしは quoted_in 1 つ: 字数の下限は無く、空の引用は偽。寄せ方は norm（既定 flat。独立設計の引用は fold、
        依頼の引用は字のまま str）"""
        self.assertTrue(cite.quoted_in("上限", "上限は入口 1 箇所で掛ける", norm=cite.fold))
        self.assertFalse(cite.quoted_in("下限", "上限は入口 1 箇所で掛ける", norm=cite.fold))
        self.assertFalse(cite.quoted_in("", "上限", norm=cite.fold))
        self.assertFalse(cite.quoted_in("  ", "上限", norm=cite.fold))
        self.assertTrue(cite.quoted_in("入口 １  箇所", "上限は入口 1 箇所で掛ける", norm=cite.fold))
        self.assertFalse(cite.quoted_in("入口 １ 箇所", "上限は入口 1 箇所で掛ける", norm=str))
        self.assertFalse(cite.quoted_in("入口 １ 箇所", "上限は入口 1 箇所で掛ける"), "既定の flat は NFKC にしない")
        self.assertTrue(cite.quoted_in("入口 1\n箇所", "\x1b[31m上限は入口 1  箇所\x1b[0m"), "既定の flat は空白と色を寄せる")


class HomeCase(unittest.TestCase):
    def test_readers_live_only_in_cite(self):
        for owner, name in ((holeties, "lead_path"), (material, "CITE_IN_WHERE"),
                            (conflict, "CITE"), (conflict, "cite_problem")):
            self.assertFalse(hasattr(owner, name), f"{owner.__name__}.{name} が cite の外に在る")
        for name in ("lead_path", "where_cites", "CITE_IN_WHERE"):
            self.assertTrue(hasattr(cite, name), f"cite.{name} が無い")


if __name__ == "__main__":
    unittest.main()
