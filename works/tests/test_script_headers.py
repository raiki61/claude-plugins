"""節のスクリプト（<pack>/<blk>/scripts/*.py）の頭の PEP 723 の書き込み（`# /// script` の塊）の検査。

Archon は script の節を `uv run <絶対パス>`（cwd は対象の worktree）で起こす。対象が pyproject.toml を持つと、
素の uv は対象の project を拾い、worktree に .venv と uv.lock を作って対象を sync・build する（uv.lock が
差分に未追跡で出て、受け付けの節の中で対象の build が走る）。PEP 723 の塊を持つスクリプトは、uv が対象の
project を見ずに自分の環境（~/.cache/uv）で起こす。

- 形: どのスクリプトも、頭（shebang の後ろなら可）にちょうど下の塊を 1 つだけ持つ
- 実物: pyproject.toml（依存と build-system 付き）を持つ使い捨ての対象で、Archon と同じ形でスクリプトを 1 本走らせ、
  対象に uv.lock も .venv もできないこと
"""
import os
import pathlib
import shutil
import subprocess
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
HEADER = [
    "# /// script",
    '# requires-python = ">=3.10"',
    "# dependencies = []",
    "# ///",
]
GIT_ID = ["-c", "user.email=t@t", "-c", "user.name=t", "-c", "commit.gpgsign=false", "-c", "core.hooksPath=/dev/null"]


def scripts():
    return sorted(ROOT.glob("*/scripts/*.py"))


class HeaderCase(unittest.TestCase):
    def test_scripts_exist(self):
        # 数え間違いで空の集合を見て緑にならないように
        self.assertGreaterEqual(len(scripts()), 10)

    def test_every_script_starts_with_pep723_block(self):
        for path in scripts():
            with self.subTest(script=str(path.relative_to(ROOT))):
                lines = path.read_text(encoding="utf-8").splitlines()
                if lines and lines[0].startswith("#!"):
                    lines = lines[1:]
                self.assertEqual(lines[:len(HEADER)], HEADER)
                opens = [ln for ln in lines if ln.startswith("# /// ")]
                self.assertEqual(opens, ["# /// script"], "PEP 723 の塊はちょうど 1 つ")


def git(repo, *args):
    return subprocess.run(["git", *GIT_ID, "-C", str(repo), *args], capture_output=True, text=True, check=True).stdout


@unittest.skipIf(shutil.which("uv") is None, "uv が無い（Archon の script の節と同じ形で回せない）")
class UvRunCase(unittest.TestCase):
    """Archon と同じ形（`uv run <絶対パス>`、cwd は対象）で、pyproject.toml を持つ対象を汚さないこと"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        tmp = pathlib.Path(self._tmp.name)
        self.repo, self.art = tmp / "target", tmp / "art"
        self.repo.mkdir()
        (self.repo / "pyproject.toml").write_text(
            '[project]\nname = "target"\nversion = "0.1.0"\nrequires-python = ">=3.9"\ndependencies = ["six"]\n\n'
            '[build-system]\nrequires = ["hatchling"]\nbuild-backend = "hatchling.build"\n', encoding="utf-8")
        (self.repo / "target").mkdir()
        (self.repo / "target" / "__init__.py").write_text("", encoding="utf-8")
        git(self.repo, "init", "-q")
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-q", "-m", "seed")

    def tearDown(self):
        self._tmp.cleanup()

    def test_uv_run_leaves_target_project_alone(self):
        uv = shutil.which("uv")
        env = {k: v for k, v in os.environ.items()
               if k not in ("VIRTUAL_ENV", "UV", "UV_RUN_RECURSION_DEPTH", "UV_NO_PROJECT", "UV_PROJECT")}
        # 網に出ない（依存の無い塊は網が要らない。対象の six・hatchling を取りに行けば、ここで落ちる）
        env.update(ARTIFACTS_DIR=str(self.art), INPUTS_REQUEST="無い依頼.json", UV_OFFLINE="1",
                   PYTHONDONTWRITEBYTECODE="1")
        r = subprocess.run([uv, "run", str(ROOT / "blk-judge" / "scripts" / "intake.py")], cwd=str(self.repo),
                           env=env, capture_output=True, text=True, timeout=300)
        # 依頼のファイルが無いので intake は理由を 1 行出して 1 で止まる（2 以上は起動そのものの失敗）
        self.assertEqual(r.returncode, 1, r.stderr)
        self.assertIn("依頼を受け付けない", r.stderr)
        self.assertEqual(git(self.repo, "status", "--porcelain", "--ignored", "--untracked-files=all"), "")
        self.assertFalse((self.repo / "uv.lock").exists())
        self.assertFalse((self.repo / ".venv").exists())


if __name__ == "__main__":
    unittest.main()
