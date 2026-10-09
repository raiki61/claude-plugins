"""始めの記録の住処 startrec（.shared/core/startrec.py）の読み口と入口の文。一時の置き場のファイルだけ（FAST。git・子のプロセスなし）"""
import json
import pathlib
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.dont_write_bytecode = True
sys.path.insert(0, str(ROOT / ".shared" / "core"))

import startrec  # noqa: E402


def shape(empty=True, requests=2, label="HEAD", spec=False):
    return {"base": {"rev": "a" * 40, "from": "head", "name": "", "label": label}, "head_rev": "b" * 40,
            "diff": {"empty": empty, "files": 0 if empty else 3, "stat": ""}, "requests": requests, "request_file": "",
            "pr": None, "spec": spec}


class StartRecCase(unittest.TestCase):
    def test_place(self):
        """置き場は盤面の根の r1/start.json（周の置き場の中の名は start.json）"""
        self.assertEqual(startrec.REL, "r1/start.json")
        self.assertEqual(startrec.NAME, "start.json")
        self.assertEqual(startrec.path("/b"), pathlib.Path("/b/r1/start.json"))

    def test_read_missing_or_broken_is_empty(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(startrec.read(d), {})
            p = startrec.path(d)
            p.parent.mkdir()
            for text in ("{", "[1]"):
                p.write_text(text, encoding="utf-8")
                self.assertEqual(startrec.read(d), {})
            p.write_text(json.dumps({"input": shape(), "test_cmd": "x"}), encoding="utf-8")
            self.assertEqual(startrec.read(d)["test_cmd"], "x")

    def test_shape_readers(self):
        """入口の入力の形の欄の読み。形の無い前の版の控えは None（分からない。0 や偽と読まない）"""
        doc = {"input": shape(empty=False, requests=0)}
        self.assertEqual((startrec.diff_empty(doc), startrec.requests(doc)), (False, 0))
        for old in ({}, {"input": None}, {"input": {"diff": "x"}}, {"entry": "change"}):
            with self.subTest(old):
                self.assertIsNone(startrec.diff_empty(old))
                self.assertIsNone(startrec.requests(old))

    def test_words_shapes(self):
        """入口の文の 3 形（差分なし・差分あり・仕様の段あり）。出どころは base.label のまま"""
        self.assertEqual(startrec.words(shape()), "差分なし（HEAD）・依頼 2 件——P1 の役は起こさない")
        self.assertEqual(startrec.words(shape(empty=False, requests=0, label="PR #12「題」")),
                         "差分 aaaaaaaaaaaa..HEAD（3 ファイル・PR #12「題」）・依頼 0 件")
        self.assertEqual(startrec.words(shape(empty=False, label="base main", spec=True)),
                         "差分 aaaaaaaaaaaa..HEAD（3 ファイル・base main）・依頼 2 件・仕様の段あり")


if __name__ == "__main__":
    unittest.main()
