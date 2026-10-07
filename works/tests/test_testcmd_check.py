"""use.sh start が test_cmd を Archon に渡す前に出す知らせ（dev/testcmd_check.py）の検査。

run の worktree と単位の worktree は commit から切るので、対象の git が無視する物（.venv・node_modules など）は無い。
test_cmd がそれを相対で指せば worktree で走らず、絶対で指すか対象の外で立てた環境（VIRTUAL_ENV）を使えば、worktree の直しで
なく対象の手元のコードを試すことがある（editable で入れた対象）。知らせは止めない（終了コード 0）。
種の git は gitkit の型の写し。子のプロセスは知らせの殻（python3 -I）とその中の git check-ignore だけ。
"""
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import unittest

sys.dont_write_bytecode = True
ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
import gitkit  # noqa: E402

TOOL = ROOT / "dev" / "testcmd_check.py"
SEED = ROOT / "dev" / "target-seed"


class TestCmdCheck(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        self.repo = pathlib.Path(self._td.name).resolve() / "repo"
        gitkit.committed_copy(self.repo, SEED)
        with open(self.repo / ".gitignore", "a", encoding="utf-8") as f:
            f.write(".venv\nnode_modules/\nbuild/\n")
        py = self.repo / ".venv" / "bin" / "python"
        py.parent.mkdir(parents=True)
        py.write_text("#!/bin/sh\n")
        (py.parent / "pytest").write_text("#!/bin/sh\n")
        (self.repo / "node_modules" / ".bin").mkdir(parents=True)
        (self.repo / "node_modules" / ".bin" / "jest").write_text("#!/bin/sh\n")

    def check(self, cmd, **env_kw):
        env = {k: v for k, v in os.environ.items() if k not in ("VIRTUAL_ENV",)}
        env.update(env_kw)
        r = subprocess.run([sys.executable, "-I", str(TOOL), str(self.repo), cmd], capture_output=True, text=True,
                           encoding="utf-8", env=env)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stderr, "")
        return r.stdout.splitlines()

    def test_relative_ignored_path_is_named(self):
        for cmd, path in ((".venv/bin/python -m pytest -q", ".venv/bin/python"),
                          ("./node_modules/.bin/jest --ci", "./node_modules/.bin/jest"),
                          ("PYTHONPATH=src .venv/bin/python -m pytest", ".venv/bin/python"),
                          (".venv/bin/python -m pytest && echo done", ".venv/bin/python")):
            with self.subTest(cmd):
                lines = self.check(cmd)
                self.assertEqual(len(lines), 1, lines)
                self.assertIn(path, lines[0])
                self.assertIn("worktree に無い", lines[0])

    def test_path_through_symlink_and_outside_word_do_not_hide_others(self):
        """リンクの先のパス（git check-ignore が 128 で落ちる形）と根の外のパスが、同じ行のほかの知らせを消さない"""
        outside = self.repo.parent / "outside-venv"
        (outside / "bin").mkdir(parents=True)
        (outside / "bin" / "python").write_text("#!/bin/sh\n")
        (self.repo / ".venv").rename(self.repo.parent / "moved")
        (self.repo / ".venv").symlink_to(outside)
        other = self.repo.parent / "other" / ".venv"
        other.mkdir(parents=True)
        (other / "x").write_text("")
        lines = self.check("./node_modules/.bin/jest ../other/.venv/x .venv/bin/python")
        self.assertEqual(len(lines), 2, lines)
        self.assertIn("./node_modules/.bin/jest", lines[0])
        self.assertIn(".venv/bin/python", lines[1])

    def test_path_in_submodule_does_not_hide_others(self):
        """サブモジュールの中のパス（git check-ignore が 128 で落ちる形）が、同じ行のほかの知らせを消さない"""
        (self.repo / "sub").mkdir()
        (self.repo / "sub" / "y").write_text("")
        gitkit.git(self.repo, "update-index", "--add", "--cacheinfo", f"160000,{'1' * 40},sub")
        lines = self.check("./node_modules/.bin/jest sub/y")
        self.assertEqual(len(lines), 1, lines)
        self.assertIn("./node_modules/.bin/jest", lines[0])

    def test_absolute_path_into_target_ignored_dir_is_named(self):
        link = self.repo.parent / "link"
        link.symlink_to(self.repo)
        for root in (self.repo, link):
            with self.subTest(root=str(root)):
                cmd = f"{root}/.venv/bin/python -m pytest -q"
                lines = self.check(cmd)
                self.assertEqual(len(lines), 1, lines)
                self.assertIn(f"{root}/.venv/bin/python", lines[0])
                self.assertIn("対象の手元", lines[0])

    def test_quiet_for_tracked_missing_outside_made_or_option_paths(self):
        for cmd in ("python3 -m pytest -q test_stats.py",   # 追跡するファイルは worktree にも在る
                    "make && build/run-tests",              # 無視するが対象に無い（コマンドが作る）
                    "/usr/bin/env python3 -m pytest",       # 対象の外
                    "uv sync && .venv/bin/pytest -q",       # 先の段が worktree の中で作る
                    "npm ci; node_modules/.bin/jest",       # 同じ
                    "pytest --junitxml=node_modules/.bin/jest",  # 旗の値（書き先が多い）は見ない
                    "pytest -q 'unclosed"):                 # 割れない行は空白で割る
            with self.subTest(cmd):
                self.assertEqual(self.check(cmd), [])

    def _site(self, venv):
        site = pathlib.Path(venv) / "lib" / "python3.12" / "site-packages"
        site.mkdir(parents=True, exist_ok=True)
        return site

    def test_activated_virtualenv_with_editable_target_is_named_unless_uv_run(self):
        venv = self.repo.parent / "venvs" / "proj"   # 対象の外の環境（poetry・virtualenvwrapper の形）
        info = self._site(venv) / "stats-0.1.dist-info"
        info.mkdir()
        (info / "direct_url.json").write_text(json.dumps({"url": self.repo.as_uri(), "dir_info": {"editable": True}}))
        path = f"{venv}/bin{os.pathsep}{os.environ.get('PATH', '')}"
        lines = self.check("pytest -q", VIRTUAL_ENV=str(venv), PATH=path)
        self.assertEqual(len(lines), 1, lines)
        self.assertIn(f"VIRTUAL_ENV（{venv}）", lines[0])
        for cmd in ("uv run pytest -q", "UV_FROZEN=1 uv run pytest -q"):
            with self.subTest(cmd):
                self.assertEqual(self.check(cmd, VIRTUAL_ENV=str(venv), PATH=path), [])
        self.assertEqual(self.check("pytest -q"), [])

    def test_activated_virtualenv_with_editable_pth_is_named(self):
        venv = self.repo / ".venv"
        (self._site(venv) / "_editable_impl_stats.pth").write_text(f"{self.repo}\n")
        path = f"{venv}/bin{os.pathsep}{os.environ.get('PATH', '')}"
        self.assertEqual(len(self.check("python3 -m pytest -q", VIRTUAL_ENV=str(venv), PATH=path)), 1)

    def test_activated_virtualenv_without_target_is_quiet(self):
        """uv run の使い捨ての環境・依存だけの環境は対象の手元のコードを試さない（試験の殻が uv run の下で回る形もこれ）"""
        venv = self.repo.parent / "ephemeral"
        (self._site(venv) / "_virtualenv.pth").write_text("import _virtualenv\n")
        info = self._site(venv) / "pyyaml-6.0.dist-info"
        info.mkdir()
        (info / "direct_url.json").write_text(json.dumps({"url": "https://example.invalid/pyyaml.whl"}))
        path = f"{venv}/bin{os.pathsep}{os.environ.get('PATH', '')}"
        self.assertEqual(self.check("pytest -q", VIRTUAL_ENV=str(venv), PATH=path), [])

    def test_empty_command_is_quiet(self):
        self.assertEqual(self.check(""), [])


if __name__ == "__main__":
    unittest.main()
