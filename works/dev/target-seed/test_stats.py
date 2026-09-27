"""stats.py の単体テスト。仕込んだ 2 つのバグのせいで 3 件中 2 件が赤になる。"""
import unittest

from stats import clamp, mean


class TestStats(unittest.TestCase):
    def test_mean_of_three(self):
        self.assertEqual(mean([1, 2, 3]), 2)

    def test_clamp_within_range(self):
        self.assertEqual(clamp(5, 0, 10), 5)

    def test_clamp_above_range(self):
        self.assertEqual(clamp(15, 0, 10), 10)


if __name__ == "__main__":
    unittest.main()
