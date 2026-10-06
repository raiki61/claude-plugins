"""textfmt.py の単体テスト。"""
import unittest

from textfmt import center, count_lines, initials, squeeze, strip_margin, words


class TestTextfmt(unittest.TestCase):
    def test_center(self):
        self.assertEqual(center("ab", 5, "."), ".ab..")

    def test_words(self):
        self.assertEqual(words(" a  b c "), ["a", "b", "c"])

    def test_initials(self):
        self.assertEqual(initials("dark factory line"), "DFL")

    def test_strip_margin(self):
        self.assertEqual(strip_margin("  |a\n  |b"), "a\nb")

    def test_count_lines(self):
        self.assertEqual(count_lines("a\nb\n"), 2)

    def test_squeeze(self):
        self.assertEqual(squeeze("a   b"), "a b")


if __name__ == "__main__":
    unittest.main()
