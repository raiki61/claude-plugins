"""人の関所と無人の方針の住処 gatepolicy（.shared/core/gatepolicy.py。考え human-gates）の語・入口の確かめ・始めの記録からの読み・
最後の関所を開くかの決め。一時の置き場のファイルだけ（FAST。git・子のプロセスなし）"""
import json
import sys
import tempfile
import pathlib
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.dont_write_bytecode = True
sys.path.insert(0, str(ROOT / ".shared" / "core"))

import gatepolicy as gp  # noqa: E402
import startrec  # noqa: E402


def record(d, **fields):
    p = startrec.path(d)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(fields), encoding="utf-8")


class WordsCase(unittest.TestCase):
    def test_words(self):
        """最後の関所の開き方は 3 つ（空の既定は always）、無人の語は true（空は人の居る run）"""
        self.assertEqual(gp.FINAL_GATES, ("always", "when_needed", "protected_only"))
        self.assertEqual(gp.FINAL_GATES[0], gp.ALWAYS)
        self.assertEqual(gp.UNATTENDED, "true")


class CheckCase(unittest.TestCase):
    def test_empty_is_default(self):
        self.assertEqual(gp.check("", "", spec=False), {gp.FINAL_KEY: gp.ALWAYS, gp.UNATTENDED_KEY: ""})

    def test_known_words_pass(self):
        for mode in gp.FINAL_GATES:
            self.assertEqual(gp.check(mode, gp.UNATTENDED, spec=False), {gp.FINAL_KEY: mode, gp.UNATTENDED_KEY: gp.UNATTENDED})

    def test_unknown_words_refused(self):
        for final, unattended_ in (("sometimes", ""), ("", "yes"), ("", "1")):
            with self.subTest(final=final, unattended_=unattended_), self.assertRaises(gp.Refused):
                gp.check(final, unattended_, spec=False)

    def test_spec_and_unattended_refused(self):
        """仕様の段の承認は人の関所なので、無人の run とは組めない"""
        with self.assertRaises(gp.Refused):
            gp.check("", gp.UNATTENDED, spec=True)
        self.assertEqual(gp.check("", "", spec=True)[gp.FINAL_KEY], gp.ALWAYS)


class ReadCase(unittest.TestCase):
    def test_reads_the_start_record(self):
        """読み手は始めの記録から読む（線の節に入力を写さない）。記録が無い・欄が空なら既定（always・人の居る run）"""
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(gp.final_mode(d), gp.ALWAYS)
            self.assertFalse(gp.unattended(d))
            record(d, **{gp.FINAL_KEY: "when_needed", gp.UNATTENDED_KEY: gp.UNATTENDED})
            self.assertEqual(gp.final_mode(d), "when_needed")
            self.assertTrue(gp.unattended(d))
            record(d, **{gp.FINAL_KEY: "", gp.UNATTENDED_KEY: ""})
            self.assertEqual(gp.final_mode(d), gp.ALWAYS)
            self.assertFalse(gp.unattended(d))

    def test_unknown_mode_in_record_is_an_error(self):
        """入口が確かめた語の外が記録に在れば配線の誤り（黙って always に倒さない）"""
        with tempfile.TemporaryDirectory() as d:
            record(d, **{gp.FINAL_KEY: "sometimes"})
            with self.assertRaises(ValueError):
                gp.final_mode(d)

    def test_head_words(self):
        """報告の頭の行の句: 記録に開き方が在れば「最後の関所: <語>」、無ければ空"""
        self.assertEqual(gp.head_words({gp.FINAL_KEY: "when_needed"}), "最後の関所: when_needed")
        self.assertEqual(gp.head_words({}), "")


class OpensCase(unittest.TestCase):
    def test_always_opens(self):
        self.assertTrue(gp.opens(gp.ALWAYS, reasons=[], guarded=False))

    def test_when_needed_opens_only_with_reasons(self):
        self.assertFalse(gp.opens("when_needed", reasons=[], guarded=False))
        self.assertTrue(gp.opens("when_needed", reasons=["赤"], guarded=False))

    def test_protected_only_opens_only_when_guarded(self):
        self.assertFalse(gp.opens("protected_only", reasons=["赤"], guarded=False))
        self.assertTrue(gp.opens("protected_only", reasons=[], guarded=True))


if __name__ == "__main__":
    unittest.main()
