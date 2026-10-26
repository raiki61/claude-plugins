"""bin/rent-or-buy の入口（sh と Python の両方で読める台本）。PATH の python3 が要る版より古く、3.11 以上の Python が
python3.14 のような版の付いた名前でだけ PATH に在っても、その Python で起き直す（docs/standards/cross-os.md の決まり 1。
uv で入れた Python はこの形になる）。選べなければ、試した物と、入れ方と、PATH の直し方を 1 行で出して終了の値 1。"""

import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import unittest

ENTRY = pathlib.Path(__file__).resolve().parent.parent / "bin" / "rent-or-buy"


@unittest.skipIf(os.name == "nt" or not shutil.which("sh"), "sh で起動する形は Windows の外で確かめる")
class Launcher(unittest.TestCase):
    def test_sh_finds_a_versioned_name_when_python3_is_too_old(self):
        with tempfile.TemporaryDirectory() as d:
            stub = pathlib.Path(d) / "python3"   # 古い Python の振る舞い: 版の確かめに 1 で答える
            stub.write_text('#!/bin/sh\ncase "$2" in *version_info*) exit 1 ;; esac\nexit 0\n', encoding="utf-8")
            stub.chmod(0o755)
            named = pathlib.Path(d) / f"python3.{sys.version_info.minor}"
            named.symlink_to(sys.executable)
            # sh だけを置いたフォルダを PATH に足す（sh の在るフォルダをそのまま足すと、Ubuntu の CI では /usr/bin の Python が見つかる）
            only_sh = pathlib.Path(d) / "only-sh"
            only_sh.mkdir()
            (only_sh / "sh").symlink_to(shutil.which("sh"))
            env = {**os.environ, "PATH": os.pathsep.join([d, str(only_sh)])}
            p = subprocess.run(["sh", str(ENTRY), "prices", "no-such-model"], capture_output=True, text=True, encoding="utf-8",
                               env=env)
            self.assertEqual(json.loads(p.stdout)["error"], "unknown_model", p.stderr)
            named.unlink()
            p = subprocess.run(["sh", str(ENTRY), "prices", "no-such-model"], capture_output=True, text=True, encoding="utf-8",
                               env=env)
            self.assertEqual(p.returncode, 1)
            self.assertIn("python3.20 down to python3.11", p.stderr)
            self.assertIn("add the folder it was installed in to PATH", p.stderr)


if __name__ == "__main__":
    unittest.main()
