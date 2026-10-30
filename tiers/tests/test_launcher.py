"""bin/tiers の入口（sh と Python の両方で読める台本）。Windows の python3 が Microsoft Store へ誘う代わりの物に当たっても、
次の候補の Python で起き直す。Python から起動する形（ほかのプラグインが sys.executable で起動する）も変わらず動く。"""

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

    @unittest.skipIf(os.name == "nt" or not shutil.which("sh"), "sh で起動する形は Windows の外で確かめる")
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

    @unittest.skipIf(os.name == "nt" or not shutil.which("sh"), "sh で起動する形は Windows の外で確かめる")
    def test_sh_skips_a_python_older_than_the_floor(self):
        with tempfile.TemporaryDirectory() as d:
            # 古い Python の振る舞い: 版の確かめ（version_info を比べる -c）には 1 で答え、ほかの -c は通り、台本は読めずに落ちる
            stub = pathlib.Path(d) / "python3"
            stub.write_text('#!/bin/sh\ncase "$2" in *version_info*) exit 1 ;; esac\n[ "$1" = -c ] && exit 0\n'
                            "echo 'SyntaxError: invalid syntax' >&2\nexit 1\n", encoding="utf-8")
            stub.chmod(0o755)
            (pathlib.Path(d) / "python").symlink_to(sys.executable)
            only_sh = pathlib.Path(d) / "only-sh"
            only_sh.mkdir()
            (only_sh / "sh").symlink_to(shutil.which("sh"))
            env = {**os.environ, "PATH": os.pathsep.join([d, str(only_sh)])}
            for name in ("tiers", "tiers-settings", "tiers-statusline"):
                with self.subTest(name):
                    p = subprocess.run(["sh", str(ENTRY.with_name(name)), "--help"], capture_output=True, text=True, encoding="utf-8",
                                       env=env)
                    self.assertEqual(p.returncode, 0, p.stderr)
                    self.assertNotIn("SyntaxError", p.stderr)

    @unittest.skipIf(os.name == "nt" or not shutil.which("sh"), "sh で起動する形は Windows の外で確かめる")
    def test_sh_finds_a_versioned_name_when_python3_is_too_old(self):
        # uv で入れた Python は python3.14 のような版の付いた名前でだけ PATH に在り、PATH の python3 は macOS 付属の 3.9 のことがある
        # （docs/standards/cross-os.md の決まり 1）
        with tempfile.TemporaryDirectory() as d:
            stub = pathlib.Path(d) / "python3"   # 古い Python の振る舞い: 版の確かめに 1 で答える
            stub.write_text('#!/bin/sh\ncase "$2" in *version_info*) exit 1 ;; esac\nexit 0\n', encoding="utf-8")
            stub.chmod(0o755)
            named = pathlib.Path(d) / f"python3.{sys.version_info.minor}"
            named.symlink_to(sys.executable)
            only_sh = pathlib.Path(d) / "only-sh"
            only_sh.mkdir()
            (only_sh / "sh").symlink_to(shutil.which("sh"))
            env = {**os.environ, "PATH": os.pathsep.join([d, str(only_sh)])}
            for name in ("tiers", "tiers-settings", "tiers-statusline"):
                with self.subTest(name):
                    p = subprocess.run(["sh", str(ENTRY.with_name(name)), "--help"], capture_output=True, text=True, encoding="utf-8",
                                       env=env)
                    self.assertEqual(p.returncode, 0, p.stderr)
            named.unlink()
            # tiers-statusline だけ 127（statusline.sh が refresh の失敗の 1 と分ける）
            for name, floor, code in (("tiers", 8, 1), ("tiers-settings", 8, 1), ("tiers-statusline", 11, 127)):
                with self.subTest(name):
                    p = subprocess.run(["sh", str(ENTRY.with_name(name)), "--help"], capture_output=True, text=True, encoding="utf-8",
                                       env=env)
                    self.assertEqual(p.returncode, code)
                    self.assertIn(f"python3.20〜python3.{floor}", p.stderr)
                    self.assertIn("入れた場所を PATH に足す", p.stderr)


if __name__ == "__main__":
    unittest.main()
