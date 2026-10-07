"""calc.py と textfmt.py の単体テスト（README の決まり: テストはこの 1 本に、モジュールごとのクラスで置く）。"""
import unittest

import calc
import textfmt


class TestCalc(unittest.TestCase):
    """calc.py のテスト"""

    def test_median_odd(self):
        self.assertEqual(calc.median([3, 1, 2]), 2)

    def test_median_even(self):
        self.assertEqual(calc.median([4, 1, 3, 2]), 2.5)

    def test_clamp_within(self):
        self.assertEqual(calc.clamp(5, 0, 10), 5)

    def test_clamp_below(self):
        self.assertEqual(calc.clamp(-1, 0, 10), 0)

    def test_clamp_above(self):
        self.assertEqual(calc.clamp(15, 0, 10), 10)


class TestTextfmt(unittest.TestCase):
    """textfmt.py のテスト"""

    def test_center(self):
        self.assertEqual(textfmt.center("ab", 5, "."), ".ab..")

    def test_words(self):
        self.assertEqual(textfmt.words(" a  b c "), ["a", "b", "c"])

    def test_initials_capitalized(self):
        self.assertEqual(textfmt.initials("Dark Factory"), "DF")

    def test_strip_margin(self):
        self.assertEqual(textfmt.strip_margin("  |a\n  |b"), "a\nb")

    def test_count_lines(self):
        self.assertEqual(textfmt.count_lines("a\nb\n"), 2)

    def test_squeeze(self):
        self.assertEqual(textfmt.squeeze("a   b"), "a b")


if __name__ == "__main__":
    unittest.main()
