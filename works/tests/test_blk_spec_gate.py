"""仕様の関所の文（blk-spec/lib/specblk.py の gate_text）の検査。盤面・git・子のプロセスなしで関数を直に呼ぶ。

- 答え方の行は core の answer.line で組む。同じファイルの口 answer（block の動詞）がモジュールの名前を上書きしても組める
"""
import importlib.util
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.dont_write_bytecode = True   # 下の import が pack の中に __pycache__ を作らないように
sys.path.insert(0, str(ROOT / ".shared" / "core"))

import answer as core_answer  # noqa: E402


def lib():
    spec = importlib.util.spec_from_file_location("_blk_spec_gate_lib", ROOT / "blk-spec" / "lib" / "specblk.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class GateTextCase(unittest.TestCase):
    def test_gate_text_answer_lines_use_core_answer(self):
        asking = {"node": "spec.approve", "kinds": ["declared"], "question": "承認するか", "items": ["A1"]}
        try:
            text = lib().gate_text(asking, run_id="run-x")
        except AttributeError as e:
            self.fail(f"gate_text が答えの行を組めない（モジュール answer が口 answer に上書きされている）: {e}")
        for verb, note in (("continue", "<通す範囲と条件>"), ("stop", "<理由>")):
            self.assertIn(core_answer.line("run-x", verb, note), text)

    def test_gate_text_subjects_are_plain(self):
        """仕様の関所の文も平易な名を主語にし、節の名・記録の欄は括弧の中の『記録の名』の後ろにだけ置く（線 A の関所と同じ検査）"""
        sys.path.insert(0, str(ROOT / "tests"))
        from test_plan_gate import internal_subjects
        asking = {"node": "spec.approve", "kinds": ["declared"], "question": "承認するか", "items": ["A1"]}
        self.assertEqual(internal_subjects(lib().gate_text(asking, run_id="run-x")), [])

    def test_gate_text_quotes_mainline_question(self):
        """仕様の関所も、本線の答え方で書かれた問いの文を引用として載せ、読み替えの 1 行を添え、答え方は 1 通りだけ"""
        sys.path.insert(0, str(ROOT / "tests"))
        from test_plan_gate import MAINLINE_Q, QuotedQuestionCase
        asking = {"node": "spec.approve", "kinds": ["declared"], "question": MAINLINE_Q, "items": ["A1"]}
        QuotedQuestionCase.check_gate(self, lib().gate_text(asking, run_id="run-x"),
                                      core_answer.line("run-x", "continue", "<通す範囲と条件>"))


if __name__ == "__main__":
    unittest.main()
