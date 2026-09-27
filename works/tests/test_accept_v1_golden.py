"""v1 の受け付け（.shared/core/accept.py の check_*）の返りが、偽の盤面から DiskBoard.scratch に替えても変わらないかの検査
（仕様 7 節・9.4）。

手本は works/tests/boards/v1-accept-golden.json（移し替えの前の commit で dev/board-goldens/v1_accept_golden.py が撮った物）。
場面の表と回し方はその作り手のファイルが正本で、ここはそれを読み込んで同じ場面を回し、行ごとに比べる。
"""
import importlib.util
import json
import pathlib
import re
import sys
import tempfile
import unittest
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parents[1]
CORE = ROOT / ".shared" / "core"
GOLDEN = pathlib.Path(__file__).resolve().parent / "boards" / "v1-accept-golden.json"
MAKER = ROOT / "dev" / "board-goldens" / "v1_accept_golden.py"
sys.dont_write_bytecode = True
sys.path.insert(0, str(CORE))

import accept  # noqa: E402
from board import DiskBoard  # noqa: E402


def _maker():
    spec = importlib.util.spec_from_file_location("v1_accept_golden", MAKER)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


MAKE = _maker()


class _ReadKeys(dict):
    """読まれた鍵を控える dict（state.inputs に差す）。鍵を名指さない読み方（回す・写す）は '*' で控える"""

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.read = set()

    def __getitem__(self, k):
        self.read.add(k)
        return super().__getitem__(k)

    def get(self, k, default=None):
        self.read.add(k)
        return super().get(k, default)

    def __contains__(self, k):
        self.read.add(k)
        return super().__contains__(k)

    def setdefault(self, k, default=None):
        self.read.add(k)
        return super().setdefault(k, default)

    def __iter__(self):
        self.read.add("*")
        return super().__iter__()

    def keys(self):
        self.read.add("*")
        return super().keys()

    def items(self):
        self.read.add("*")
        return super().items()

    def values(self):
        self.read.add("*")
        return super().values()

    def copy(self):
        self.read.add("*")
        return super().copy()


class V1GoldenCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = pathlib.Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_v1_results_unchanged(self):
        # 全部の入力で ok・reason の全文・open_units・書いたファイルの名前（と中身）が同じ。
        # check_delta が偽の盤面に渡していた outputs={"p3.fix": {}} を外しても同じこと（delta_* の場面。仕様 7 節）を含む
        golden = json.loads(GOLDEN.read_text(encoding="utf-8"))
        self.assertEqual([g["name"] for g in golden], [c["name"] for c in MAKE.CASES], "手本と場面の表の並びが違う")
        for g, row in zip(golden, MAKE.run_all(self.tmp)):
            with self.subTest(case=g["name"]):
                self.assertEqual(row, g)

    def test_no_fake_board_left(self):
        src = (CORE / "accept.py").read_text(encoding="utf-8")
        self.assertIsNone(re.search(r"\b_Board\b", src), "accept.py に偽の盤面 _Board の名前が残っている")
        self.assertFalse(hasattr(accept, "_Board"))

    def test_check_request_writes_only_request(self):
        # 盤面のファイルは今までどおり: state.json（engine の盤面）を作らない
        board = self.tmp / "board"
        r = accept.check_request(MAKE.load("request_ok"), board, "持ち主")
        self.assertTrue(r["ok"], r["reason"])
        self.assertEqual(sorted(p.name for p in board.iterdir()), ["request.json"])

    def test_scratch_board_dir_used(self):
        # check_judge が規則に渡す入れ物は、渡した盤面の置き場を dir に持つ DiskBoard.scratch。数え直しが b.dir に書く
        # count-cache.json がその置き場に在る
        made = []
        orig = DiskBoard.scratch

        def spy(*a, **kw):
            b = orig(*a, **kw)
            made.append(b)
            return b

        work = self.tmp / "w"
        work.mkdir()
        with mock.patch.object(DiskBoard, "scratch", spy):
            row = MAKE.run_case(next(c for c in MAKE.CASES if c["name"] == "judge_ok_after_request"), work)
        self.assertTrue(row["result"]["ok"], row["result"]["reason"])
        board = work / "board"
        self.assertTrue((board / "count-cache.json").is_file())
        self.assertGreaterEqual(len(made), 2)   # 依頼（前の手）と判定
        for b in made:
            self.assertIsInstance(b, DiskBoard)
            self.assertEqual(b.dir, board)
            self.assertEqual(b.round, 1)
            self.assertEqual(b.rd["instances"], {})   # v1 の受け付けは instance を持たない（BL24）

    def test_scratch_reads_only_review_rev(self):
        # scratch の state.inputs は review_rev だけ（Task 3 の申し送り）。v1 の check_* が他の入力を読まないことを、
        # 全部の場面で読まれた鍵を控えて確かめる
        read = set()
        orig = DiskBoard.scratch

        def spy(*a, **kw):
            b = orig(*a, **kw)
            b.state["inputs"] = rec = _ReadKeys(b.state["inputs"])
            read_sets.append(rec)
            return b

        read_sets = []
        with mock.patch.object(DiskBoard, "scratch", spy):
            MAKE.run_all(self.tmp)
        self.assertTrue(read_sets)
        for rec in read_sets:
            read |= rec.read
        self.assertLessEqual(read, {"review_rev"}, f"scratch の inputs の review_rev の他が読まれた: {sorted(read)}")


if __name__ == "__main__":
    unittest.main()
