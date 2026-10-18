"""cost ノード: 1 件の PR を開くと、アカウントの使用率がどれだけ増えるかを、実行の前後の控えから測って覚える。"""

import pathlib
import tempfile
import unittest

from . import DISPATCH  # noqa: F401
from nodes import cost


def snap(seven, five, reset7=1000, reset5=100):
    return {"seven_day": {"used_percentage": seven, "resets_at": reset7},
            "five_hour": {"used_percentage": five, "resets_at": reset5}}


class Samples(unittest.TestCase):
    def test_change_plus_one_divided_by_the_prs_opened(self):
        # 使用率は 1% 刻みで届くので、本当の増えは「見えた差 + 1」より小さい。少なく見積もらないよう上の端を採る
        got = cost.samples({"p1": snap(40, 8)}, {"p1": snap(42, 20)}, {"p1": 4})
        self.assertEqual(got, {"seven_day": [0.75], "five_hour": [3.25]})

    def test_no_visible_change_still_counts_the_resolution(self):
        got = cost.samples({"p1": snap(40, 8)}, {"p1": snap(40, 8)}, {"p1": 10})
        self.assertEqual(got, {"seven_day": [0.1], "five_hour": [0.1]})

    def test_window_that_reset_during_the_run_is_not_measured(self):
        got = cost.samples({"p1": snap(40, 90, reset5=100)}, {"p1": snap(41, 3, reset5=200)}, {"p1": 2})
        self.assertEqual(got, {"seven_day": [1.0], "five_hour": []})

    def test_accounts_without_prs_or_records_are_skipped(self):
        got = cost.samples({"p1": snap(40, 8), "p2": None}, {"p1": snap(41, 9), "p2": snap(1, 1)}, {"p1": 0, "p2": 3})
        self.assertEqual(got, {"seven_day": [], "five_hour": []})


class Estimate(unittest.TestCase):
    def test_none_until_measured(self):
        self.assertIsNone(cost.estimate({"seven_day": [], "five_hour": []}))

    def test_median_of_each_window(self):
        got = cost.estimate({"seven_day": [0.5, 3.0, 0.7], "five_hour": [2.0, 4.0]})
        self.assertEqual(got, {"seven_day": 0.7, "five_hour": 3.0, "runs": 3})

    def test_window_without_samples_is_left_out(self):
        self.assertEqual(cost.estimate({"seven_day": [0.4], "five_hour": []}), {"seven_day": 0.4, "runs": 1})


class Store(unittest.TestCase):
    def test_missing_file_is_empty_and_a_broken_one_is_not_overwritten(self):
        d = pathlib.Path(tempfile.mkdtemp())
        self.assertEqual(cost.load(d / "none.json"), {"seven_day": [], "five_hour": []})
        for raw in ("{", "[1]", '{"seven_day": 3}'):
            (d / "bad.json").write_text(raw, encoding="utf-8")
            with self.assertRaises(cost.CostError):   # 空として読まない
                cost.load(d / "bad.json")
            with self.assertRaises(cost.CostError):   # 壊れたまま上書きしない
                cost.save(d / "bad.json", {"seven_day": [1.0], "five_hour": []})
            self.assertEqual((d / "bad.json").read_text(encoding="utf-8"), raw)

    def test_save_appends_and_keeps_only_the_newest(self):
        d = pathlib.Path(tempfile.mkdtemp())
        path = d / "sub" / "dispatch-cost.json"
        for i in range(cost.KEEP + 3):
            cost.save(path, {"seven_day": [float(i)], "five_hour": []})
        got = cost.load(path)
        self.assertEqual(got["seven_day"], [float(i) for i in range(3, cost.KEEP + 3)])
        self.assertEqual(got["five_hour"], [])


if __name__ == "__main__":
    unittest.main()
