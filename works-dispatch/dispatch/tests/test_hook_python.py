"""フックの Python の選び方（hooks/run-python.sh）。Windows の python3 が Microsoft Store へ誘う代わりの物に当たっても、
macOS 付属の python3 が 3.9 でも、次の候補の 3.11 以上で台本を起こす。選べなければ、直し方を 1 行で出して終了の値 1。"""

import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import unittest

from . import DISPATCH

PICK = DISPATCH.parent / "hooks" / "run-python.sh"


@unittest.skipIf(os.name == "nt" or not shutil.which("bash"), "偽の Python を PATH に置く形は Windows の外で確かめる")
class HookPython(unittest.TestCase):
    def run_pick(self, folder, script):
        env = {**os.environ, "PATH": os.pathsep.join([folder, os.path.dirname(shutil.which("bash")), "/usr/bin", "/bin"])}
        return subprocess.run([shutil.which("bash"), str(PICK), script], capture_output=True, text=True, encoding="utf-8", env=env)

    def test_a_stub_and_an_old_python_are_skipped(self):
        with tempfile.TemporaryDirectory() as d:
            stub = pathlib.Path(d) / "python3"
            stub.write_text("#!/bin/sh\necho 'Python was not found'\nexit 9009\n", encoding="utf-8")
            stub.chmod(0o755)
            (pathlib.Path(d) / "python").symlink_to(sys.executable)
            script = pathlib.Path(d) / "s.py"
            script.write_text("import sys; print(sys.version_info >= (3, 11))\n", encoding="utf-8")
            p = self.run_pick(d, str(script))
            self.assertEqual((p.returncode, p.stdout.strip()), (0, "True"), p.stderr)

    def test_the_floor_can_be_lowered_or_raised(self):
        # タブ欄とサイドバーの台本は TOML を読まないので --min 3.9。下限より古い物しか無ければ、その版を言って止まる
        with tempfile.TemporaryDirectory() as d:
            script = pathlib.Path(d) / "s.py"
            script.write_text("print('ok')\n", encoding="utf-8")
            (pathlib.Path(d) / "python3").symlink_to(sys.executable)
            env = {**os.environ, "PATH": os.pathsep.join([d, os.path.dirname(shutil.which("bash"))])}
            p = subprocess.run([shutil.which("bash"), str(PICK), "--min", "3.9", str(script)], capture_output=True, text=True,
                               encoding="utf-8", env=env)
            self.assertEqual((p.returncode, p.stdout.strip()), (0, "ok"), p.stderr)
            p = subprocess.run([shutil.which("bash"), str(PICK), "--min", "99.0", str(script)], capture_output=True, text=True,
                               encoding="utf-8", env=env)
            self.assertEqual(p.returncode, 1)
            self.assertIn("Python 99.0 以上", p.stderr)

    def test_once_tells_only_the_first_time_in_a_conversation(self):
        # 止まる前のフックはターンごとに走る。選べないときの知らせは、会話ごとに 1 回だけ誤り（終了の値 1）として出す
        with tempfile.TemporaryDirectory() as d, tempfile.TemporaryDirectory() as tmp:
            stub = pathlib.Path(d) / "python3"
            stub.write_text("#!/bin/sh\nexit 9009\n", encoding="utf-8")
            stub.chmod(0o755)
            env = {**os.environ, "PATH": d, "TMPDIR": tmp}
            runs = [subprocess.run([shutil.which("bash"), str(PICK), "--once", "x.py"], input='{"session_id": "s-1"}',
                                   capture_output=True, text=True, encoding="utf-8", env=env) for _ in range(2)]
            self.assertEqual([r.returncode for r in runs], [1, 0])
            self.assertIn("アプリ実行エイリアス", runs[0].stderr)
            self.assertEqual(runs[1].stderr, "")

    def test_nothing_to_pick_says_how_to_fix_it(self):
        with tempfile.TemporaryDirectory() as d:
            for name in ("python3", "python"):
                stub = pathlib.Path(d) / name
                stub.write_text("#!/bin/sh\nexit 9009\n", encoding="utf-8")
                stub.chmod(0o755)
            env_path = os.pathsep.join([d, os.path.dirname(shutil.which("bash"))])
            p = subprocess.run([shutil.which("bash"), str(PICK), "x.py"], capture_output=True, text=True, encoding="utf-8",
                               env={**os.environ, "PATH": env_path})
            self.assertEqual(p.returncode, 1)
            self.assertIn("アプリ実行エイリアス", p.stderr)


if __name__ == "__main__":
    unittest.main()
