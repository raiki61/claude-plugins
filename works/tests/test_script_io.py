"""受け付けのスクリプトの入口（.shared/core/script_io.py）の検査。

環境変数の読み・盤面の置き場・1 行の JSON・終了コード（拒否も 0、入力が読めないときだけ 2）と、
ブロックのスクリプトが写す前置き（script_io の docstring の ```python の塊）が pack の中に __pycache__ を作らないことを見る。
"""
import contextlib
import io
import json
import os
import pathlib
import re
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parents[1]
CORE = ROOT / ".shared" / "core"
sys.path.insert(0, str(CORE))

import script_io  # noqa: E402

TRICKY = '判定は拒む: "二重" と \'一重\' と\n改行と \\ と \t タブ'


def run_main(fn, env, **kw):
    """script_io.main を環境変数を差し替えて呼ぶ。(終了コード, 標準出力, 標準エラー)"""
    out, err = io.StringIO(), io.StringIO()
    with mock.patch.dict(os.environ, env, clear=True), contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = script_io.main(fn, **kw)
    return code, out.getvalue(), err.getvalue()


class ScriptIoCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = pathlib.Path(self._tmp.name)
        self.env = {"INPUTS_REPLY": json.dumps({"units": []}), "INPUTS_BASE_REV": "abc123",
                    "ARTIFACTS_DIR": str(self.tmp / "artifacts")}

    def tearDown(self):
        self._tmp.cleanup()

    def test_accept_script_reason_roundtrip(self):
        want = {"ok": False, "reason": TRICKY, "open_units": ["u-1"]}
        code, out, _ = run_main(lambda *a: want, self.env)
        self.assertEqual(code, 0)
        self.assertEqual(out.count("\n"), 1, "出力はちょうど 1 行")
        self.assertEqual(json.loads(out), want)
        self.assertIn("判定は拒む", out, "ensure_ascii=False（日本語をそのまま出す）")

    def test_fn_receives_reply_board_rev_repo(self):
        seen = []
        code, out, _ = run_main(lambda *a: seen.append(a) or {"ok": True, "reason": ""}, self.env)
        self.assertEqual(code, 0)
        reply, board, rev, repo = seen[0]
        self.assertEqual(reply, {"units": []})
        self.assertEqual(board, self.tmp / "artifacts" / "board")
        self.assertTrue(board.is_dir(), "盤面のフォルダを作る")
        self.assertEqual(rev, "abc123")
        self.assertEqual(repo, pathlib.Path.cwd())
        self.assertEqual(json.loads(out), {"ok": True, "reason": ""})

    def test_empty_base_rev_is_passed_through(self):
        # Ruling R2: 空の INPUTS_BASE_REV は「HEAD を使う」の意味で、欠けではない
        seen = []
        code, _, _ = run_main(lambda *a: seen.append(a) or {"ok": True, "reason": ""}, {**self.env, "INPUTS_BASE_REV": ""})
        self.assertEqual(code, 0)
        self.assertEqual(seen[0][2], "")

    def test_reply_env_name(self):
        seen = []
        env = {**self.env, "INPUTS_JUDGMENT": json.dumps({"x": 1})}
        del env["INPUTS_REPLY"]
        code, _, _ = run_main(lambda *a: seen.append(a) or {"ok": True, "reason": ""}, env, reply_env="INPUTS_JUDGMENT")
        self.assertEqual(code, 0)
        self.assertEqual(seen[0][0], {"x": 1})

    def test_script_io_non_json_reply(self):
        called = []
        code, out, _ = run_main(lambda *a: called.append(a), {**self.env, "INPUTS_REPLY": "not json"})
        self.assertEqual(code, 0)
        got = json.loads(out)
        self.assertIs(got["ok"], False)
        self.assertTrue(got["reason"].startswith("返答が JSON として読めない: "), got["reason"])
        self.assertEqual(called, [], "読めない返答で中身を呼ばない")

    def test_reply_not_object(self):
        code, out, _ = run_main(lambda *a: self.fail("呼ばない"), {**self.env, "INPUTS_REPLY": "[1, 2]"})
        self.assertEqual(code, 0)
        self.assertIs(json.loads(out)["ok"], False)

    def test_script_io_missing_env(self):
        for name in ("INPUTS_REPLY", "INPUTS_BASE_REV", "ARTIFACTS_DIR"):
            with self.subTest(name):
                env = dict(self.env)
                del env[name]
                code, out, err = run_main(lambda *a: self.fail("呼ばない"), env)
                self.assertEqual(code, 2)
                self.assertIn(name, err)
                self.assertEqual(out, "", "欠けのときは標準出力に何も出さない")

    def test_empty_artifacts_dir_is_missing(self):
        # 空の ARTIFACTS_DIR を通すと盤面が cwd（対象リポジトリ）の board/ になるので、欠けと同じく 2
        code, _, err = run_main(lambda *a: self.fail("呼ばない"), {**self.env, "ARTIFACTS_DIR": ""})
        self.assertEqual(code, 2)
        self.assertIn("ARTIFACTS_DIR", err)


class PreambleCase(unittest.TestCase):
    """docstring に書いた前置きを、ブロックの形（<pack>/blk-x/scripts/accept.py）に置いて別のプロセスで回す"""

    def preamble(self):
        m = re.search(r"```python\n(.*?)```", script_io.__doc__, re.S)
        self.assertIsNotNone(m, "script_io の docstring に ```python の前置きが無い")
        return m.group(1)

    def pycaches(self):
        return sorted(str(p.relative_to(CORE)) for p in CORE.rglob("__pycache__"))

    def test_block_preamble_writes_no_pycache(self):
        self.assertEqual(self.pycaches(), [], "回す前から core の下に __pycache__ が在る（消してから回す）")
        with tempfile.TemporaryDirectory() as tmp:
            pack = pathlib.Path(tmp) / "pack"
            (pack / "blk-x" / "scripts").mkdir(parents=True)
            (pack / ".shared").symlink_to(ROOT / ".shared")
            # 名前を accept.py にする: 前置きが sys.path の頭に core を入れないと、自分自身を import してしまう（Ruling R7）
            script = pack / "blk-x" / "scripts" / "accept.py"
            script.write_text(self.preamble(), encoding="utf-8")
            repo = pathlib.Path(tmp) / "repo"
            repo.mkdir()
            env = {k: v for k, v in os.environ.items() if k != "PYTHONDONTWRITEBYTECODE"}
            env.update(INPUTS_REPLY="not json", INPUTS_BASE_REV="", ARTIFACTS_DIR=str(pathlib.Path(tmp) / "art"))
            r = subprocess.run([sys.executable, str(script)], cwd=repo, env=env, capture_output=True, text=True,
                               timeout=120)
            self.assertEqual(r.returncode, 0, r.stderr)
            got = json.loads(r.stdout)
            self.assertIs(got["ok"], False)
            self.assertIn("JSON として読めない", got["reason"])
        self.assertEqual(self.pycaches(), [], "前置きの後の import が pack の中に __pycache__ を作った")


if __name__ == "__main__":
    unittest.main()
