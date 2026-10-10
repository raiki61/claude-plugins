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


class HomeCase(unittest.TestCase):
    def test_readers_live_only_in_cite(self):
        for owner, name in ((holeties, "lead_path"), (material, "CITE_IN_WHERE"),
                            (conflict, "CITE"), (conflict, "cite_problem")):
            self.assertFalse(hasattr(owner, name), f"{owner.__name__}.{name} が cite の外に在る")
        for name in ("lead_path", "where_cites", "CITE_IN_WHERE"):
            self.assertTrue(hasattr(cite, name), f"cite.{name} が無い")


if __name__ == "__main__":
    unittest.main()
