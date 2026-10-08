"""stats.py・textfmt.py・units.py・money.py・slugs.py の単体テスト（README の決まり: テストはこの 1 本に、モジュールごとのクラスで置く）。"""
import unittest

import stats
import textfmt
import units
import money
import slugs


class TestStats(unittest.TestCase):
    """stats.py のテスト"""

    def test_mean(self):
        self.assertEqual(stats.mean([1, 2, 3]), 2)

    def test_median_odd(self):
        self.assertEqual(stats.median([3, 1, 2]), 2)

    def test_mode(self):
        self.assertEqual(stats.mode([1, 2, 2, 3, 3]), 2)


class TestTextfmt(unittest.TestCase):
    """textfmt.py のテスト"""

    def test_center(self):
        self.assertEqual(textfmt.center("ab", 5, "."), ".ab..")

    def test_pad_left_long(self):
        self.assertEqual(textfmt.pad_left("abc", 2), "abc")

    def test_words(self):
        self.assertEqual(textfmt.words(" a  b c "), ["a", "b", "c"])

    def test_squeeze(self):
        self.assertEqual(textfmt.squeeze("a   b"), "a b")


class TestUnits(unittest.TestCase):
    """units.py のテスト"""

    def test_c_to_f_freezing(self):
        self.assertEqual(units.c_to_f(0), 32)

    def test_f_to_c(self):
        self.assertEqual(units.f_to_c(212), 100)

    def test_km_to_miles(self):
        self.assertEqual(units.km_to_miles(1.609344), 1)


class TestMoney(unittest.TestCase):
    """money.py のテスト"""

    def test_split_even_remainder_first(self):
        self.assertEqual(money.split_even(10, 3), [4, 3, 3])

    def test_split_even_exact(self):
        self.assertEqual(money.split_even(9, 3), [3, 3, 3])

    def test_split_even_more_parts_than_total(self):
        self.assertEqual(money.split_even(1, 3), [1, 0, 0])

    def test_split_even_needs_parts(self):
        with self.assertRaises(ValueError):
            money.split_even(5, 0)

    def test_format_yen(self):
        self.assertEqual(money.format_yen(1234), "¥1,234")
        self.assertEqual(money.format_yen(-5), "-¥5")


class TestSlugs(unittest.TestCase):
    """slugs.py のテスト"""

    def test_slugify_words(self):
        self.assertEqual(slugs.slugify("Dark Factory Line!"), "dark-factory-line")

    def test_slugify_trims(self):
        self.assertEqual(slugs.slugify("  --A__b--  "), "a-b")

    def test_join_path(self):
        self.assertEqual(slugs.join_path("a/", "/b", "", "/", "c"), "a/b/c")


if __name__ == "__main__":
    unittest.main()
