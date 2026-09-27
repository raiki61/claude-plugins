"""節のスクリプト（<pack>/<blk>/scripts/*.py）の頭の PEP 723 の書き込み（`# /// script` の塊）の検査。

Archon は script の節を `uv run <絶対パス>`（cwd は対象の worktree）で起こす。対象が pyproject.toml を持つと、
素の uv は対象の project を拾い、worktree に .venv と uv.lock を作って対象を sync・build する（uv.lock が
差分に未追跡で出て、受け付けの節の中で対象の build が走る）。PEP 723 の塊を持つスクリプトは、uv が対象の
project を見ずに自分の環境（~/.cache/uv）で起こす。

- 形: どのスクリプトも、頭（shebang の後ろなら可）にちょうど下の塊を 1 つだけ持つ
- 実物: pyproject.toml（依存と build-system 付き）を持つ使い捨ての対象で、Archon と同じ形でスクリプトを 1 本走らせ、
  対象に uv.lock も .venv もできないこと
- 既知の限界の記録: 塊があっても対象の uv の設定（[tool.uv]・uv.toml）は読まれ、満たせない required-version で節が
  起動前に大きな音で止まる（終了コード 2）。pack は UV_NO_CONFIG=1 を立てない（立てると Archon の子のテストのコマンドや
  修正役の Bash にも漏れ、対象の `uv run pytest` が私的な index を読まずに公開の PyPI から解決する。設計書 §7・README）
"""
import os
import pathlib
import shutil
import subprocess
import tempfile
import unittest

from gitkit import git

ROOT = pathlib.Path(__file__).resolve().parents[1]
HEADER = [
    "# /// script",
    '# requires-python = ">=3.10"',
    "# dependencies = []",
    "# ///",
]


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


UV_ENV_DROP = ("VIRTUAL_ENV", "UV", "UV_RUN_RECURSION_DEPTH", "UV_NO_PROJECT", "UV_PROJECT", "UV_NO_CONFIG",
               "UV_CONFIG_FILE")


@unittest.skipIf(shutil.which("uv") is None, "uv が無い（Archon の script の節と同じ形で回せない）")
class UvRunCase(unittest.TestCase):
    """Archon と同じ形（`uv run <絶対パス>`、cwd は対象）で、pyproject.toml を持つ対象を汚さないこと。
    塊は対象の project（依存・.venv・uv.lock）を拾わせないだけで、対象の uv の設定（[tool.uv]・uv.toml）は読む（既知の限界）"""

    def setUp(self):
        self.uv = shutil.which("uv")
        # 網に出ない（依存の無い塊は網が要らない。対象の six・hatchling を取りに行けば、ここで落ちる）
        self.env = {k: v for k, v in os.environ.items() if k not in UV_ENV_DROP}
        self.env.update(UV_OFFLINE="1", PYTHONDONTWRITEBYTECODE="1")
        found = subprocess.run([self.uv, "python", "find", ">=3.10"], env=self.env, capture_output=True, text=True,
                               timeout=60)
        if found.returncode != 0:
            self.skipTest("uv が 3.10 以上の python を手元に見つけられない（網に出ずには塊の requires-python を満たせない）: "
                          + " ".join(found.stderr.split()))
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        tmp = pathlib.Path(self._tmp.name)
        self.repo, self.art = tmp / "target", tmp / "art"

    def seed(self, extra=""):
        """依存（six）と build-system を持つ対象を作って commit する。extra は pyproject.toml の後ろに足す"""
        self.repo.mkdir()
        (self.repo / "pyproject.toml").write_text(
            '[project]\nname = "target"\nversion = "0.1.0"\nrequires-python = ">=3.9"\ndependencies = ["six"]\n\n'
            '[build-system]\nrequires = ["hatchling"]\nbuild-backend = "hatchling.build"\n' + extra, encoding="utf-8")
        (self.repo / "target").mkdir()
        (self.repo / "target" / "__init__.py").write_text("", encoding="utf-8")
        git(self.repo, "init", "-q")
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-q", "-m", "seed")

    def run_intake(self, **extra_env):
        env = dict(self.env, ARTIFACTS_DIR=str(self.art), INPUTS_REQUEST="無い依頼.json", **extra_env)
        return subprocess.run([self.uv, "run", str(ROOT / "blk-judge" / "scripts" / "intake.py")], cwd=str(self.repo),
                              env=env, capture_output=True, text=True, timeout=300)

    def assert_started_and_clean(self, r):
        # 依頼のファイルが無いので intake は理由を 1 行出して 1 で止まる（2 は uv の起動そのものの失敗）
        self.assertEqual(r.returncode, 1, r.stderr)
        self.assertIn("依頼を受け付けない", r.stderr)
        self.assertEqual(git(self.repo, "status", "--porcelain", "--ignored", "--untracked-files=all"), "")
        self.assertFalse((self.repo / "uv.lock").exists())
        self.assertFalse((self.repo / ".venv").exists())

    def test_uv_run_leaves_target_project_alone(self):
        self.seed()
        self.assert_started_and_clean(self.run_intake())

    def test_target_uv_config_stops_nodes_loudly(self):
        # 既知の限界: 塊があっても uv は対象の [tool.uv] を読む。満たせない required-version で、どの節も起動の前に
        # 終了コード 2 で止まる（黙って進まない）。直すのは対象か uv の設定
        self.seed('\n[tool.uv]\nrequired-version = ">=99"\n')
        r = self.run_intake()
        self.assertEqual(r.returncode, 2, "対象の [tool.uv] が効いていない: " + r.stderr)
        self.assertNotIn("依頼を受け付けない", r.stderr)
        self.assertIn("required", r.stderr.lower())
        # 止まった理由が設定であることの確かめ（UV_NO_CONFIG=1 で設定を読まなければ起きる）。
        # pack はこれを立てない（Archon の子全部に漏れて対象の uv の動きまで変わる。設計書 §7）
        self.assert_started_and_clean(self.run_intake(UV_NO_CONFIG="1"))


if __name__ == "__main__":
    unittest.main()
