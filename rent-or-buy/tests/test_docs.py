"""同梱の設計書の約束: 英語の正本（docs/design.md）と日本語の訳（docs/design.ja.md）の見出しの数と並び・引く URL がそろう。"""
import pathlib
import re
import unittest

DOCS = pathlib.Path(__file__).resolve().parent.parent / "docs"
HEADING = re.compile(r"^(#{2,6})\s+(\d+(?:\.\d+)*)\.?\s", re.M)
URL = re.compile(r"https?://[^\s)>\]`]+")
FENCE = re.compile(r"^```.*?^```", re.M | re.S)


def outline(text):
    """番号の付いた見出しの (段, 番号) の並び。コードブロックの中は見ない。"""
    return [(len(h), n) for h, n in HEADING.findall(FENCE.sub("", text))]


class DesignDocsTest(unittest.TestCase):
    def setUp(self):
        self.en = (DOCS / "design.md").read_text(encoding="utf-8")
        self.ja = (DOCS / "design.ja.md").read_text(encoding="utf-8")

    def test_same_headings_in_same_order(self):
        en, ja = outline(self.en), outline(self.ja)
        self.assertTrue(en, "design.md に番号の付いた見出しが無い（検査が空振りしている）")
        self.assertEqual(en, ja)
        self.assertEqual(len(re.findall(r"^#{2,6}\s", FENCE.sub("", self.en), re.M)), len(en),
                         "design.md に番号の無い見出しがある（訳とそろえる手がかりが無い）")

    def test_same_sources(self):
        self.assertEqual(sorted(set(URL.findall(self.en))), sorted(set(URL.findall(self.ja))))

    def test_outline_catches_a_missing_section(self):
        # 検査がセクションの抜けで赤になることを、違反の見本で確かめる
        broken = re.sub(r"^### 3\.5 .*$", "", self.ja, flags=re.M)
        self.assertNotEqual(outline(self.en), outline(broken))


if __name__ == "__main__":
    unittest.main()
