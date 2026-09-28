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


if __name__ == "__main__":
    unittest.main()
