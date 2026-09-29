"""works/dev の殻の全体の模型（WORKS_DEV_MODEL）が、明示された指定と既定を見分けたまま archon.sh まで届くかの検査。

- 入口の殻（use.sh・dogfood.sh・real-run.sh）は既定を埋めない。既定を解くのは archon.sh の 1 か所だけ。
- archon.sh は、既定を埋めた時と利用者が同じ opus を明示した時とで、出どころ（WORKS_MODEL_FROM）を違えて下へ渡す。
- use.sh は、模型を明示せずに start した run を Archon へ未設定のまま渡し、控えの model を空に残す。別の殻の show が組む続きの
  行も、その殻の WORKS_DEV_MODEL や既定の opus を明示として書かない。

Archon・claude・mise・shasum は偽物（sh の台本）。種の git は gitkit の型の写し。
"""
import json
import os
import pathlib
import re
import shutil
import subprocess
import tempfile
import unittest
from unittest import mock

from gitkit import committed_copy, git
import hermetic  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parents[1]
DEV = ROOT / "dev"
BASETEMP_PARENT = ROOT.parent / ".works-test-tmp"
_saved = {}


def setUpModule():
    """殻は /private/tmp の下（Claude Code の一時フォルダ）を拒むので、TMPDIR がそこならリポジトリの根の .works-test-tmp/ へ移す"""
    _saved["tempdir"] = tempfile.tempdir
    real = os.path.realpath(tempfile.gettempdir())
    if real == "/private/tmp" or real.startswith("/private/tmp/"):
        BASETEMP_PARENT.mkdir(exist_ok=True)
        _saved["base"] = tempfile.mkdtemp(prefix="model-", dir=str(BASETEMP_PARENT))
        tempfile.tempdir = _saved["base"]
        _saved["environ"] = mock.patch.dict(os.environ, {"TMPDIR": _saved["base"]})
        _saved["environ"].start()


def tearDownModule():
    environ = _saved.pop("environ", None)
    if environ:
        environ.stop()
    tempfile.tempdir = _saved.get("tempdir")
    base = _saved.pop("base", None)
    if base:
        shutil.rmtree(base, ignore_errors=True)
        try:
            BASETEMP_PARENT.rmdir()
        except OSError:
            pass


class EntryShells(unittest.TestCase):
    def test_entry_shells_do_not_fill_model_default(self):
        """埋めると archon.sh で明示と既定が見分けられない"""
        for name in ("use.sh", "dogfood.sh", "real-run.sh"):
            with self.subTest(name):
                body = (DEV / name).read_text(encoding="utf-8")
                self.assertEqual(re.findall(r"^\s*WORKS_DEV_MODEL=.*$", body, re.M), [])
                # start の時の既定の釘は控えからだけ受ける。利用者の殻に残った値は guard.sh を読む前に外す
                self.assertLess(body.index("\nunset WORKS_MODEL_PINNED\n"), body.index('. "$DEV_DIR/guard.sh"'))


class ArchonShModelFrom(unittest.TestCase):
    def exec_archon_sh(self, **overrides):
        """偽の shasum で確かめを通し、キャッシュの偽の実行ファイルまで exec させる。戻り値は (結果, config.yaml, WORKS_MODEL_FROM)"""
        expected = re.search(r'^ARCHON_SHA256="([0-9a-f]{64})"', (DEV / "archon.sh").read_text(), re.M).group(1)
        tmp = hermetic.tmpdir(self)
        dev_home = tmp / "dev-home"
        (dev_home / "bin").mkdir(parents=True)
        seen = tmp / "model-from.txt"
        fake_archon = dev_home / "bin" / "archon-darwin-arm64"
        self.pinned_seen = tmp / "pinned.txt"
        fake_archon.write_text("#!/bin/sh\n" f'printf \'%s\\n\' "${{WORKS_MODEL_FROM-(unset)}}" > "{seen}"\n'
                               f'printf \'%s\\n\' "${{WORKS_MODEL_PINNED-(unset)}}" > "{self.pinned_seen}"\n')
        fake_bin = tmp / "fake-bin"
        from test_toolset import make_user_config, write_fake_claude
        write_fake_claude(fake_bin)
        (fake_bin / "mise").write_text("#!/bin/sh\nexit 0\n")
        (fake_bin / "mise").chmod(0o755)
        (fake_bin / "shasum").write_text(f'#!/bin/sh\necho "{expected}  $3"\n')
        (fake_bin / "shasum").chmod(0o755)
        user_cfg = make_user_config(tmp / "user-claude-config")
        env = hermetic.child_env()
        for name in ("WORKS_KEYCHAIN_ITEM", "WORKS_MODEL_FROM", "TITLE_GENERATION_MODEL", "MISE_TRUSTED_CONFIG_PATHS"):
            env.pop(name, None)
        env.update(WORKS_DEV_HOME=str(dev_home), PATH=str(fake_bin) + os.pathsep + env.get("PATH", ""),
                   FAKE_CLAUDE_LOG=str(tmp / "claude-calls.jsonl"), CLAUDE_CONFIG_DIR=str(user_cfg),
                   CLAUDE_CODE_OAUTH_TOKEN="dummy-token-for-test")
        env.update(overrides)
        result = subprocess.run(["sh", str(DEV / "archon.sh"), "workflow", "run", "x"],
                                capture_output=True, text=True, encoding="utf-8", env=env)
        config = dev_home / "archon-home" / "config.yaml"
        return (result, config.read_text() if config.exists() else None,
                seen.read_text().strip() if seen.exists() else None)

    def test_archon_sh_tells_explicit_model_from_default(self):
        """書く模型はどちらも opus で、出どころだけが違う（明示か既定かの区別を下へ渡す）"""
        result, config, from_default = self.exec_archon_sh()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("    model: opus\n", config)
        result, config, from_explicit = self.exec_archon_sh(WORKS_DEV_MODEL="opus")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("    model: opus\n", config)
        for v in (from_default, from_explicit):
            self.assertNotIn(v, (None, "", "(unset)"))
        self.assertNotEqual(from_default, from_explicit)

    def test_default_is_not_overridable_and_pin_stays_out_of_archon(self):
        """既定の定数は環境で替わらない。start の時の既定の釘（WORKS_MODEL_PINNED）はその値で解いて出どころに名を残し、
        Archon（その下の殻・入れ子の run）には継がせない"""
        result, config, from_default = self.exec_archon_sh(WORKS_DEV_MODEL_DEFAULT="sonnet")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("    model: opus\n", config)
        result, config, from_pinned = self.exec_archon_sh(WORKS_DEV_MODEL="", WORKS_MODEL_PINNED="haiku")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("    model: haiku\n", config)
        self.assertIn("WORKS_MODEL_PINNED", from_pinned)
        self.assertNotEqual(from_pinned, from_default)
        self.assertEqual(self.pinned_seen.read_text().strip(), "(unset)")


class UseShDefaultModel(unittest.TestCase):
    def setUp(self):
        self.tmp = hermetic.tmpdir(self)
        self.home = self.tmp / "use-home"
        self.request = self.tmp / "req.json"
        self.request.write_text('[{"where": "stats.py:1", "text": "mean が空で落ちる"}]\n')
        self.runs = self.tmp / "runs.json"
        self.runs.write_text(json.dumps({"runs": [{"id": "run-1", "workflow_name": "darkfactory", "status": "paused",
                                                   "working_path": "/wt/run-1", "output_root": "/out"}]}))
        self.models = self.tmp / "models.txt"
        self.fake = self.tmp / "fake-archon.sh"
        self.fake.write_text(
            "#!/bin/sh\n"
            f'case "$*" in "workflow runs --json") cat "{self.runs}" ;; esac\n'
            f'printf \'%s\\t%s\\n\' "$2" "${{WORKS_DEV_MODEL-(unset)}}" >> "{self.models}"\n'
            "exit 0\n")

    def use(self, *args, **env_kw):
        env = hermetic.child_env()
        for name in ("WORKS_KEYCHAIN_ITEM", "WORKS_USE_FINAL_GATE"):
            env.pop(name, None)
        env.update(WORKS_USE_HOME=str(self.home), WORKS_DEV_HOME=str(self.tmp / "dev-home"),
                   WORKS_DEV_ARCHON=str(self.fake), CLAUDE_CODE_OAUTH_TOKEN="dummy-token-for-test",
                   CLAUDE_BIN_PATH="/usr/bin/true", WORKS_DEV_ADAPTER="0")
        env.update(env_kw)
        return subprocess.run(["sh", str(DEV / "use.sh"), *args], capture_output=True, text=True, encoding="utf-8", env=env)

    def target(self):
        """use.sh は remote の origin の無い対象を拒むので、origin を持つ対象を作る"""
        t = self.tmp / "target"
        committed_copy(t, DEV / "target-seed")
        git(t, "remote", "add", "origin", str(self.tmp / "origin.git"))
        return t

    def test_start_without_model_keeps_it_unset_through_ledger(self):
        """既定を解くのは archon.sh。控えの model は空で、別の殻の show の続きの行もその殻の値や既定の opus を明示にしない"""
        t = self.target()
        r = self.use("start", str(t), str(self.request), "true", "")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("run\t(unset)", self.models.read_text().splitlines())
        self.assertEqual(json.loads((self.home / "runs" / "run-1.json").read_text())["model"], "")
        r = self.use("show", str(t), "run-1", WORKS_DEV_MODEL="haiku")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        for verb in ("approve", "resume"):
            line = next(l for l in r.stdout.splitlines() if f"workflow {verb} run-1" in l)
            self.assertNotIn("WORKS_DEV_MODEL=opus", line)
            self.assertNotIn("WORKS_DEV_MODEL=haiku", line)

    def test_stray_pin_in_caller_shell_does_not_change_default(self):
        """start の時の既定の釘は控えからだけ受ける。利用者の殻に残った WORKS_MODEL_PINNED は start にも、既定の控えの無い
        古い控えの show の続きの行にも届かない"""
        t = self.target()
        r = self.use("start", str(t), str(self.request), "true", "", WORKS_MODEL_PINNED="sonnet")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        led_path = self.home / "runs" / "run-1.json"
        led = json.loads(led_path.read_text())
        self.assertEqual(led["model_resolved"]["value"], "opus")
        self.assertNotIn("WORKS_MODEL_PINNED", led["model_resolved"]["from"])
        led.pop("model_resolved")
        led_path.write_text(json.dumps(led))
        r = self.use("show", str(t), "run-1", WORKS_MODEL_PINNED="sonnet")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        line = next(l for l in r.stdout.splitlines() if "workflow resume run-1" in l)
        self.assertIn("WORKS_MODEL_PINNED=opus ", line)


if __name__ == "__main__":
    unittest.main()
