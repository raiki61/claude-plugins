"""bin/tiers の入口（sh と Python の両方で読める台本）。Windows の python3 が Microsoft Store へ誘う代わりの物に当たっても、
次の候補の Python で起き直す。Python から起こす形（ほかのプラグインが sys.executable で起こす）も変わらず動く。"""

import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import unittest

ENTRY = pathlib.Path(__file__).resolve().parent.parent / "bin" / "tiers"


class Launcher(unittest.TestCase):
    def test_python_reads_the_entry_as_a_script(self):
        p = subprocess.run([sys.executable, str(ENTRY), "--tier", "0", "--json"], capture_output=True, text=True,
                           encoding="utf-8")
        self.assertEqual(json.loads(p.stdout)["schema"], 1, p.stderr)

    @unittest.skipIf(os.name == "nt" or not shutil.which("sh"), "sh で起こす形は Windows の外で確かめる")
    def test_sh_skips_a_python_that_does_not_run_and_uses_the_next(self):
        with tempfile.TemporaryDirectory() as d:
            stub = pathlib.Path(d) / "python3"   # Store へ誘う代わりの物の振る舞い: 案内を出して終わる
            stub.write_text("#!/bin/sh\necho 'Python was not found; run without arguments to install from the Microsoft Store'\n"
                            "exit 9009\n", encoding="utf-8")
            stub.chmod(0o755)
            (pathlib.Path(d) / "python").symlink_to(sys.executable)
            # sh だけを置いたフォルダを PATH に足す（sh の在るフォルダをそのまま足すと、Ubuntu の CI では /usr/bin の python が
            # 見つかり、Python が見つからない形を作れなかった）
            only_sh = pathlib.Path(d) / "only-sh"
            only_sh.mkdir()
            (only_sh / "sh").symlink_to(shutil.which("sh"))
            env = {**os.environ, "PATH": os.pathsep.join([d, str(only_sh)])}
            p = subprocess.run(["sh", str(ENTRY), "--tier", "0", "--json"], capture_output=True, text=True, encoding="utf-8", env=env)
            self.assertEqual(json.loads(p.stdout)["schema"], 1, p.stderr)
            stub.with_name("python").unlink()
            p = subprocess.run(["sh", str(ENTRY), "--tier", "0"], capture_output=True, text=True, encoding="utf-8", env=env)
            self.assertEqual(p.returncode, 1)
            self.assertIn("アプリ実行エイリアス", p.stderr)


if __name__ == "__main__":
    unittest.main()
