"""食い違いの申し出の種類の欄 kind（conflict.DIV_KINDS の 6 つ）と、which_is_right との対の確かめ（依頼 211）。

- kind は申し出の必須の欄（conflict.FIELDS の末尾）。語の外の値は拒み、文に種類の名を並べる
- 対: kind query_hits_fixed ⇔ which_is_right query、kind needs_context なら which_is_right unknown。外れは両方の欄を名指して拒む
- 語の定数 conflict.WORD（216 の seams.json の words と同じ綴り）・TDD の輪の申し出の見本と決まりの節が種類を全部言う
- 控えの行と trace の行に kind が載り、種類の内訳（kind_counts）が数える。kind の無い前の形の行も読めて「無し」と出る
盤面・git・子のプロセスは使わない（関数を直に呼ぶ。一時の置き場に種のファイルと控えを書くだけ）。
"""
import json
import pathlib
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
BLK = ROOT / "blk-fix"
CORE = ROOT / ".shared" / "core"
sys.dont_write_bytecode = True
sys.path.insert(0, str(BLK / "lib"))
sys.path.insert(0, str(CORE))

import conflict  # noqa: E402
import fixrules  # noqa: E402
import tddloop  # noqa: E402

KEY = "stats.py clamp: 上限を超えた値に lo を返す"
ITEM = {"unit_key": KEY, "between": ["stats.py:3", "test_stats.py:2"],
        "why_both_cannot_hold": "テストは上限 hi を期待し、今のコードは lo を返す——両方は成り立たない",
        "which_is_right": "request", "kind": "unnamed_test_broke"}


def seed(repo: pathlib.Path) -> None:
    """名指しの種（stats.py は 4 行・test_stats.py は 2 行）"""
    (repo / "stats.py").write_text("def clamp(x, lo, hi):\n    if x > hi:\n        return lo\n    return x\n",
                                   encoding="utf-8")
    (repo / "test_stats.py").write_text("def test_clamp():\n    assert clamp(11, 0, 10) == 10\n", encoding="utf-8")


class KindCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.repo = pathlib.Path(tmp.name)
        seed(self.repo)

    def errs(self, **over):
        return conflict.problems([{**ITEM, **over}], repo=self.repo, board_dir=self.repo, owed={KEY})

    def test_kind_is_a_required_field(self):
        self.assertEqual(conflict.FIELDS[-1], "kind")
        self.assertIn("kind", conflict.ITEM_SCHEMA["required"])
        item = dict(ITEM)
        item.pop("kind")
        got = conflict.problems([item], repo=self.repo, board_dir=self.repo, owed={KEY})
        self.assertTrue(any("kind" in e for e in got), got)

    def test_design_kinds_and_two_kept(self):
        self.assertEqual(conflict.DIV_KINDS, ("brief_vs_judgment", "unnamed_test_broke", "not_red", "scope_needed",
                                              "query_hits_fixed", "needs_context"))
        self.assertEqual(self.errs(), [])
        got = self.errs(kind="other")
        self.assertTrue(any("kind" in e and "needs_context" in e for e in got), got)

    def test_kind_and_which_must_pair(self):
        for over in ({"which_is_right": "query", "correct_lines": ["        return hi"]},   # kind が query_hits_fixed でない
                     {"kind": "query_hits_fixed"},                                          # which_is_right が query でない
                     {"kind": "needs_context", "which_is_right": "request"}):
            got = self.errs(**over)
            self.assertTrue(any("kind" in e and "which_is_right" in e for e in got), (over, got))
        self.assertEqual(self.errs(kind="needs_context", which_is_right="unknown"), [])

    def test_word_names_the_outlet(self):
        self.assertEqual(conflict.WORD, "divergence")

    def test_return_conflict_lists_every_kind(self):
        for k in conflict.DIV_KINDS:
            self.assertIn(k, tddloop.RETURN_CONFLICT)

    def test_rules_name_the_kinds(self):
        sec = fixrules.sections(fixrules.SHARED)["core-conflict"]
        for k in conflict.DIV_KINDS:
            self.assertIn(f"`{k}`", sec)
        self.assertIn('"kind"', fixrules.sections(fixrules.TDD)["tdd-remap"])


class FakeBoard:
    """盤面の代わり: work(name) は一時の置き場のファイル、round は 1、trace(op, **kw) は (op, kw) を traced に貯める"""

    def __init__(self, root: pathlib.Path):
        self.root = root
        self.round = 1
        self.traced = []

    def work(self, name) -> pathlib.Path:
        return self.root / name

    def trace(self, op, **kw):
        self.traced.append((op, kw))


class KindRowsCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.b = FakeBoard(pathlib.Path(tmp.name))

    def write_items(self, rows):
        self.b.work(conflict.FILE).write_text(json.dumps({"items": rows}, ensure_ascii=False), encoding="utf-8")

    def test_park_keeps_kind_and_traces_it(self):
        conflict.park(self.b, [ITEM], source="fix")
        self.assertEqual(conflict.items(self.b)[0]["kind"], "unnamed_test_broke")
        self.assertEqual(self.b.traced[0][1]["kind"], "unnamed_test_broke")
        self.assertEqual(conflict.kind_counts(self.b)["unnamed_test_broke"], 1)

    def test_rows_without_kind_still_read(self):
        legacy = {k: ITEM[k] for k in ("unit_key", "between", "why_both_cannot_hold", "which_is_right")}
        self.write_items([{"id": "c1-1", "round": 1, "source": "fix", **legacy, "status": "ruled",
                           "ruling": {"decision": "ask_human", "text": "方針の変更で人が決める", "limits": [], "by": "x"}}])
        self.assertEqual(conflict.kind_counts(self.b)["unset"], 1)
        self.assertIn("種類 無し", conflict.human_lines(self.b)[0])
        self.assertIn("申し出の種類: （無し）", conflict.write_rulings(self.b).read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
