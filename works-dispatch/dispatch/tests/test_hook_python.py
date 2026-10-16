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
