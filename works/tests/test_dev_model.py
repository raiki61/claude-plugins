"""works/dev の殻の全体の模型（WORKS_DEV_MODEL）が、明示された指定と既定を見分けたまま archon.sh まで届くかの検査。

- 入口の殻（use.sh・dogfood.sh）は既定を埋めない。既定を解くのは archon.sh の 1 か所だけ。
- archon.sh は、既定を埋めた時と利用者が既定と同じ値を明示した時とで、出どころ（WORKS_MODEL_FROM）を違えて下へ渡す。
- use.sh は、模型を明示せずに start した run を Archon へ未設定のまま渡し、控えの model を空に残す。別の殻の show が組む続きの
  行も、その殻の WORKS_DEV_MODEL や既定を明示として書かない。
既定の値は試験に写さず hermetic.dev_model_default() で guard.sh から読み、探りの値は hermetic.other_model() で既定と違う値にする。

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
        for name in ("use.sh", "dogfood.sh"):
            with self.subTest(name):
                body = (DEV / name).read_text(encoding="utf-8")
                self.assertEqual(re.findall(r"^\s*WORKS_DEV_MODEL=.*$", body, re.M), [])
                # start の時の既定の釘は控えからだけ受ける。利用者の殻に残った値は guard.sh を読む前に外す
                self.assertLess(body.index("\nunset WORKS_MODEL_PINNED\n"), body.index('. "$DEV_DIR/guard.sh"'))


class ModelDefault(unittest.TestCase):
    def test_default_is_sonnet(self):
        """前付けに模型の無い段は sonnet で走らせる（持ち主 2026-10-01。費用を先に取る）。前付けに模型の在る役は段の model: が縛る"""
        self.assertEqual(hermetic.dev_model_default(), "sonnet")

    def test_probe_differs_from_default(self):
        """探りの値が既定と重なると、上書きできないことを見る試験が空振りする"""
        self.assertNotEqual(hermetic.other_model(), hermetic.dev_model_default())
        self.assertNotIn(hermetic.other_model("opus"), ("opus", hermetic.dev_model_default()))


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
        self.dev_model_seen = tmp / "dev-model.txt"
        self.testslot_seen = tmp / "testslot.txt"
        fake_archon.write_text("#!/bin/sh\n" f'printf \'%s\\n\' "${{WORKS_MODEL_FROM-(unset)}}" > "{seen}"\n'
                               f'printf \'%s|%s\\n\' "${{WORKS_TESTSLOT-(unset)}}" "$HOME" > "{self.testslot_seen}"\n'
                               f'printf \'%s\\n\' "${{WORKS_MODEL_PINNED-(unset)}}" > "{self.pinned_seen}"\n'
                               f'printf \'%s\\n\' "${{WORKS_DEV_MODEL:-(empty)}}" > "{self.dev_model_seen}"\n')
        fake_bin = tmp / "fake-bin"
        from test_toolset import make_user_config, write_fake_claude
        write_fake_claude(fake_bin)
        (fake_bin / "mise").write_text("#!/bin/sh\nexit 0\n")
        (fake_bin / "mise").chmod(0o755)
        (fake_bin / "shasum").write_text(f'#!/bin/sh\necho "{expected}  $3"\n')
        (fake_bin / "shasum").chmod(0o755)
        user_cfg = make_user_config(tmp / "user-claude-config")
        env = hermetic.child_env()
        for name in ("WORKS_KEYCHAIN_ITEM", "WORKS_MODEL_FROM", "TITLE_GENERATION_MODEL", "MISE_TRUSTED_CONFIG_PATHS", "WORKS_TESTSLOT"):
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
        """書く模型はどちらも既定の値で、出どころだけが違う（明示か既定かの区別を下へ渡す）"""
        default = hermetic.dev_model_default()
        result, config, from_default = self.exec_archon_sh()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(f"    model: {default}\n", config)
        result, config, from_explicit = self.exec_archon_sh(WORKS_DEV_MODEL=default)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(f"    model: {default}\n", config)
        for v in (from_default, from_explicit):
            self.assertNotIn(v, (None, "", "(unset)"))
        self.assertNotEqual(from_default, from_explicit)

    def test_default_is_not_overridable_and_pin_stays_out_of_archon(self):
        """既定の定数は環境で替わらない。start の時の既定の釘（WORKS_MODEL_PINNED）はその値で解いて出どころに名を残し、
        Archon（その下の殻・入れ子の run）には継がせない"""
        default, probe = hermetic.dev_model_default(), hermetic.other_model()
        result, config, from_default = self.exec_archon_sh(WORKS_DEV_MODEL_DEFAULT=probe)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(f"    model: {default}\n", config)
        result, config, from_pinned = self.exec_archon_sh(WORKS_DEV_MODEL="", WORKS_MODEL_PINNED=probe)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(f"    model: {probe}\n", config)
        self.assertIn("WORKS_MODEL_PINNED", from_pinned)
        self.assertNotEqual(from_pinned, from_default)
        self.assertEqual(self.pinned_seen.read_text().strip(), "(unset)")


    def test_only_explicit_model_reaches_archon(self):
        """包みは Archon の下で WORKS_DEV_MODEL が空でない時だけ前付けの無い段を明示の模型で起こす（adapter.py の頭の 19）ので、
        archon.sh は明示の値だけを Archon へ継ぎ、既定・start の時の既定の釘を WORKS_DEV_MODEL に書き戻さない"""
        default, probe = hermetic.dev_model_default(), hermetic.other_model()
        for kw, want in (({}, "(empty)"), ({"WORKS_DEV_MODEL": "", "WORKS_MODEL_PINNED": probe}, "(empty)"),
                         ({"WORKS_DEV_MODEL": probe}, probe), ({"WORKS_DEV_MODEL": default}, default)):
            with self.subTest(**kw):
                result, _config, _from = self.exec_archon_sh(**kw)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(self.dev_model_seen.read_text().strip(), want)

    def test_testslot_default_is_named_before_home_is_isolated(self):
        """機械全体の試験の枠の台本の既定は利用者の家のキャッシュから引く（式の正本は slotwrap.sh --default）。archon.sh は HOME・XDG を
        隔離する前にそれを引いて WORKS_TESTSLOT に名指す（隔離の後の run の中の試験も同じ台本を通る）。台本が無ければ空（枠なし）、
        利用者の名指しはそのまま"""
        user_home = hermetic.tmpdir(self) / "user-home"
        script = user_home / ".cache" / "works" / "testslot.sh"
        script.parent.mkdir(parents=True)
        script.write_text("#!/bin/sh\n\"$@\"\n")
        env = {"HOME": str(user_home), "XDG_CACHE_HOME": ""}
        for kw, want in (({}, str(script)), ({"WORKS_TESTSLOT": "/named/slot.sh"}, "/named/slot.sh"),
                         ({"WORKS_TESTSLOT": ""}, "")):
            with self.subTest(**kw):
                result, _config, _from = self.exec_archon_sh(**env, **kw)
                self.assertEqual(result.returncode, 0, result.stderr)
                slot, home = self.testslot_seen.read_text().strip().split("|")
                self.assertEqual(slot, want)
                self.assertNotEqual(home, str(user_home))   # Archon の下は隔離した家
        script.unlink()
        result, _config, _from = self.exec_archon_sh(**env)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.testslot_seen.read_text().strip().split("|")[0], "")

    def test_explicit_model_without_adapter_says_so(self):
        """包みを外した run（WORKS_DEV_ADAPTER が空・0）では明示の模型が段に届かない。黙らずに 1 行で言う。明示しない run は言わない"""
        probe = hermetic.other_model()
        result, _config, _from = self.exec_archon_sh(WORKS_DEV_MODEL=probe)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(f"WORKS_DEV_MODEL={probe}", result.stderr)
        self.assertIn("WORKS_DEV_ADAPTER=1", result.stderr)
        result, _config, _from = self.exec_archon_sh()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("WORKS_DEV_ADAPTER=1", result.stderr)


class UseShDefaultModel(unittest.TestCase):
    def setUp(self):
        self.tmp = hermetic.tmpdir(self)
        self.home = self.tmp / "use-home"
        self.request = self.tmp / "req.json"
        self.request.write_text('[{"where": "stats.py:1", "text": "mean が空で落ちる"}]\n')
        self.runs = self.tmp / "runs.json"
        self.runs.write_text(json.dumps({"runs": [{"id": "run-1", "workflow_name": "darkfactory", "status": "paused",
                                                   "working_path": "/wt/run-1", "output_root": str(self.tmp / "out")}]}))
        self.models = self.tmp / "models.txt"
        self.fake = self.tmp / "fake-archon.sh"
        # workflow run は run の盤面 r1/start.json に request= の値を残す（線の start と同じ。起動の後に結ぶ材料）
        board = self.tmp / "out" / "artifacts" / "runs" / "run-1" / "board" / "r1"
        self.fake.write_text(
            "#!/bin/sh\n"
            f'case "$*" in "workflow runs --json") cat "{self.runs}" ;; esac\n'
            f'printf \'%s\\t%s\\n\' "$2" "${{WORKS_DEV_MODEL-(unset)}}" >> "{self.models}"\n'
            f'case "$1 $2" in "workflow run") mkdir -p "{board}"; for a in "$@"; do case "$a" in request=*)\n'
            f'  printf \'{{"request_file": "%s"}}\' "${{a#request=}}" > "{board}/start.json" ;; esac; done ;; esac\n'
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
        """use.sh は remote の origin の無い対象・origin の既定の枝が分からない対象を拒むので、origin と追跡の枝 origin/main を
        持つ対象を作る（網には出ない）"""
        t = self.tmp / "target"
        committed_copy(t, DEV / "target-seed")
        git(t, "remote", "add", "origin", str(self.tmp / "origin.git"))
        git(t, "update-ref", "refs/remotes/origin/main", "HEAD")
        return t

    def test_start_without_model_keeps_it_unset_through_ledger(self):
        """既定を解くのは archon.sh。控えの model は空で、別の殻の show の続きの行もその殻の値や既定を明示にしない"""
        default, probe = hermetic.dev_model_default(), hermetic.other_model()
        t = self.target()
        r = self.use("start", str(t), str(self.request), "true", "")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("run\t(unset)", self.models.read_text().splitlines())
        self.assertEqual(json.loads((self.home / "runs" / "run-1.json").read_text())["model"], "")
        r = self.use("show", str(t), "run-1", WORKS_DEV_MODEL=probe)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        for verb in ("approve", "resume"):
            line = next(l for l in r.stdout.splitlines() if f"workflow {verb} run-1" in l)
            self.assertNotIn(f"WORKS_DEV_MODEL={default}", line)
            self.assertNotIn(f"WORKS_DEV_MODEL={probe}", line)

    def test_stray_pin_in_caller_shell_does_not_change_default(self):
        """start の時の既定の釘は控えからだけ受ける。利用者の殻に残った WORKS_MODEL_PINNED は start にも、既定の控えの無い
        古い控えの show の続きの行にも届かない"""
        default, stray = hermetic.dev_model_default(), hermetic.other_model()
        t = self.target()
        r = self.use("start", str(t), str(self.request), "true", "", WORKS_MODEL_PINNED=stray)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        led_path = self.home / "runs" / "run-1.json"
        led = json.loads(led_path.read_text())
        self.assertEqual(led["model_resolved"]["value"], default)
        self.assertNotIn("WORKS_MODEL_PINNED", led["model_resolved"]["from"])
        led.pop("model_resolved")
        led_path.write_text(json.dumps(led))
        r = self.use("show", str(t), "run-1", WORKS_MODEL_PINNED=stray)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        line = next(l for l in r.stdout.splitlines() if "workflow resume run-1" in l)
        self.assertIn(f"WORKS_MODEL_PINNED={default} ", line)


if __name__ == "__main__":
    unittest.main()
