"""起動の殻の共通の口 works/dev/launch.py の動詞 env と、殻が受ける口（guard.sh works_dev_launch_env）の柵（設計書 2.2・2.3・3 節）。

- 家の既定・claude の解決・包みの既定と入力 adapter の値は部品の 1 つの表が持ち、殻 4 本（use.sh・dogfood.sh・real-run.sh・archon.sh）に写しを戻したら赤
- 殻 4 本と lib.sh の埋め込みの Python（python3 に -c を渡す行）の数が今の上限を超えたら赤
- 部品は env の dict を渡して直に呼ぶ（子のプロセスを起こさない）。受け方だけは偽の部品を置いて sh で起こす
- 期待の字は殻の今の ${X:-…} の字から写す（空は未設定と同じ・TMPDIR の末尾の / を残して連ねる）
"""
import ast
import hashlib
import importlib.util
import io
import os
import pathlib
import re
import shlex
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest

TESTS = pathlib.Path(__file__).resolve().parent
ROOT = TESTS.parent
DEV = ROOT / "dev"
LAUNCH = DEV / "launch.py"
SHELLS = ("use.sh", "dogfood.sh", "real-run.sh", "archon.sh")
ADAPTER = ROOT / ".shared" / "core" / "claude-adapter"
NAME = re.compile(r"[A-Z_][A-Z0-9_]*\Z")
sys.dont_write_bytecode = True   # 下の import が pack の中に __pycache__ を作らないように


def load(case):
    case.assertTrue(LAUNCH.is_file(), f"部品 {LAUNCH} が無い")
    spec = importlib.util.spec_from_file_location("works_launch_under_test", LAUNCH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def run_env(case, args, environ):
    """launch.main(["env", …], environ, out, err) を呼び、(終了コード, 標準出力, 標準エラー) を返す"""
    out, err = io.StringIO(), io.StringIO()
    rc = load(case).main(["env", *args], dict(environ), out, err)
    return rc, out.getvalue(), err.getvalue()


def assigned(case, args, environ):
    """成功した env の出力を 版の行を確かめて {名: 値} に読む"""
    rc, out, err = run_env(case, args, environ)
    case.assertEqual(rc, 0, err)
    lines = out.splitlines()
    case.assertEqual(lines[:1], ["WORKS_LAUNCH_FORMAT=1"], out)
    got = {}
    for line in lines[1:]:
        name, _, value = line.partition("=")
        case.assertRegex(name, NAME)
        words = shlex.split(value)
        case.assertEqual(len(words), 1, line)
        got[name] = words[0]
    return got


def fake_claude(folder):
    path = pathlib.Path(folder) / "claude"
    path.write_text("#!/bin/sh\nexit 0\n")
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return str(path)


class HomeDefaults(unittest.TestCase):
    def test_dev_home_joins_tmpdir_as_text_keeping_trailing_slash(self):
        for shell in ("dogfood.sh", "real-run.sh", "archon.sh"):
            with self.subTest(shell=shell):
                got = assigned(self, [f"--for={shell}"], {"HOME": "/h", "TMPDIR": "/var/x/T/"})
                self.assertEqual(got["WORKS_DEV_HOME"], "/var/x/T//works-dev")

    def test_empty_values_count_as_unset_like_sh(self):
        for shell in ("dogfood.sh", "real-run.sh", "archon.sh"):
            with self.subTest(shell=shell):
                got = assigned(self, [f"--for={shell}"], {"HOME": "/h", "TMPDIR": "", "WORKS_DEV_HOME": ""})
                self.assertEqual(got["WORKS_DEV_HOME"], "/tmp/works-dev")
                got = assigned(self, [f"--for={shell}"], {"HOME": "/h", "WORKS_DEV_HOME": "/named/home"})
                self.assertEqual(got["WORKS_DEV_HOME"], "/named/home")

    def test_use_home_is_per_clone_and_does_not_inherit_dev_home(self):
        target = "/src/some clone"
        mark = hashlib.sha256(target.encode()).hexdigest()[:8]
        got = assigned(self, ["--for=use.sh", "--target", target],
                       {"HOME": "/h", "XDG_STATE_HOME": "", "WORKS_DEV_HOME": "/inherited"})
        self.assertEqual(got["WORKS_STATE_ROOT"], "/h/.local/state/works")
        self.assertEqual(got["WORKS_USE_HOME"], f"/h/.local/state/works/use-{mark}")
        self.assertEqual(got["WORKS_DEV_HOME"], got["WORKS_USE_HOME"])
        got = assigned(self, ["--for=use.sh", "--target", target],
                       {"HOME": "/h", "XDG_STATE_HOME": "/xdg", "WORKS_USE_HOME": "/named"})
        self.assertEqual(got["WORKS_STATE_ROOT"], "/xdg/works")
        self.assertEqual((got["WORKS_USE_HOME"], got["WORKS_DEV_HOME"]), ("/named", "/named"))

    def test_only_allowed_names_per_shell(self):
        got = assigned(self, ["--for=dogfood.sh"], {"HOME": "/h"})
        self.assertEqual(set(got), {"WORKS_DEV_HOME", "WORKS_DEV_ADAPTER", "WORKS_LAUNCH_ADAPTER_MODE"})
        got = assigned(self, ["--for=use.sh", "--target", "/t"], {"HOME": "/h"})
        self.assertEqual(set(got), {"WORKS_STATE_ROOT", "WORKS_USE_HOME", "WORKS_DEV_HOME", "WORKS_DEV_ADAPTER",
                                    "WORKS_LAUNCH_ADAPTER_MODE"})


class AdapterDefaults(unittest.TestCase):
    """包みの既定: 期待の字は殻の前の ${WORKS_DEV_ADAPTER-1}（空の明示は残す）と ${WORKS_DEV_ADAPTER:-} = 1 から写す"""
    ARGS = {"use.sh": ["--for=use.sh", "--target", "/t"], "dogfood.sh": ["--for=dogfood.sh"],
            "real-run.sh": ["--for=real-run.sh"], "archon.sh": ["--for=archon.sh"]}

    def adapter(self, args, **named):
        got = assigned(self, args, {"HOME": "/h", **named})
        return got.get("WORKS_DEV_ADAPTER"), got.get("WORKS_LAUNCH_ADAPTER_MODE")

    def test_use_and_dogfood_default_on_only_when_unset(self):
        for shell in ("use.sh", "dogfood.sh"):
            with self.subTest(shell=shell):
                args = self.ARGS[shell]
                self.assertEqual(self.adapter(args), ("1", ""))
                self.assertEqual(self.adapter(args, WORKS_DEV_ADAPTER="1"), ("1", ""))
                self.assertEqual(self.adapter(args, WORKS_DEV_ADAPTER=""), ("", "optional"))
                self.assertEqual(self.adapter(args, WORKS_DEV_ADAPTER="0"), ("0", "optional"))
                self.assertEqual(self.adapter(args, WORKS_DEV_ADAPTER="yes"), ("yes", "optional"))

    def test_dogfood_show_defaults_off(self):
        args = ["--for=dogfood.sh", "--show"]
        self.assertEqual(self.adapter(args), ("", "optional"))
        self.assertEqual(self.adapter(args, WORKS_DEV_ADAPTER="1"), ("1", ""))

    def test_real_run_only_reads_and_archon_emits_nothing(self):
        args = self.ARGS["real-run.sh"]
        self.assertEqual(self.adapter(args), (None, "optional"))
        self.assertEqual(self.adapter(args, WORKS_DEV_ADAPTER="1"), (None, ""))
        self.assertEqual(self.adapter(args, WORKS_DEV_ADAPTER="0"), (None, "optional"))
        for value in (None, "1", "0"):
            named = {} if value is None else {"WORKS_DEV_ADAPTER": value}
            self.assertEqual(self.adapter(self.ARGS["archon.sh"], **named), (None, None))

    def test_show_is_refused_for_other_shells(self):
        for shell in ("use.sh", "real-run.sh", "archon.sh"):
            with self.subTest(shell=shell):
                rc, out, err = run_env(self, [*self.ARGS[shell], "--show"], {"HOME": "/h"})
                self.assertEqual((rc, out), (2, ""))
                self.assertEqual(len(err.strip().splitlines()), 1, err)


class ClaudeResolution(unittest.TestCase):
    def test_not_resolved_without_claude_flag(self):
        with tempfile.TemporaryDirectory() as d:
            fake_claude(d)
            for shell in ("dogfood.sh", "real-run.sh", "archon.sh"):
                got = assigned(self, [f"--for={shell}"], {"HOME": "/h", "PATH": d})
                self.assertNotIn("WORKS_LAUNCH_CLAUDE", got)

    def test_explicit_then_path_then_empty(self):
        with tempfile.TemporaryDirectory() as d:
            claude = fake_claude(d)
            for shell, extra in (("dogfood.sh", []), ("real-run.sh", []), ("use.sh", ["--target", "/t"])):
                with self.subTest(shell=shell):
                    args = [f"--for={shell}", "--claude", *extra]
                    got = assigned(self, args, {"HOME": "/h", "PATH": d, "CLAUDE_BIN_PATH": "/named/claude"})
                    self.assertEqual(got["WORKS_LAUNCH_CLAUDE"], "/named/claude")
                    got = assigned(self, args, {"HOME": "/h", "PATH": d, "CLAUDE_BIN_PATH": ""})
                    self.assertEqual(got["WORKS_LAUNCH_CLAUDE"], claude)
                    got = assigned(self, args, {"HOME": "/h", "PATH": "/nowhere"})
                    self.assertEqual(got["WORKS_LAUNCH_CLAUDE"], "")

    def test_relative_hit_on_path_is_not_an_executable_path(self):
        with tempfile.TemporaryDirectory() as d:
            (pathlib.Path(d) / "bin").mkdir()
            fake_claude(pathlib.Path(d) / "bin")
            here = os.getcwd()
            os.chdir(d)
            try:
                got = assigned(self, ["--for=dogfood.sh", "--claude"], {"HOME": "/h", "PATH": "bin"})
            finally:
                os.chdir(here)
            self.assertEqual(got["WORKS_LAUNCH_CLAUDE"], "")

    def test_archon_prefers_real_claude_and_skips_the_adapter(self):
        with tempfile.TemporaryDirectory() as d:
            claude = fake_claude(d)
            link = pathlib.Path(d) / "adapter-link"
            link.symlink_to(ADAPTER)
            args = ["--for=archon.sh", "--claude", "--adapter", str(ADAPTER)]
            got = assigned(self, args, {"HOME": "/h", "PATH": d, "WORKS_REAL_CLAUDE": "/real/claude",
                                        "CLAUDE_BIN_PATH": "/other/claude"})
            self.assertEqual(got["WORKS_LAUNCH_CLAUDE"], "/real/claude")
            got = assigned(self, args, {"HOME": "/h", "PATH": d, "CLAUDE_BIN_PATH": "/other/claude"})
            self.assertEqual(got["WORKS_LAUNCH_CLAUDE"], "/other/claude")
            got = assigned(self, args, {"HOME": "/h", "PATH": d, "CLAUDE_BIN_PATH": str(link)})
            self.assertEqual(got["WORKS_LAUNCH_CLAUDE"], claude)


class Failures(unittest.TestCase):
    def assert_refused(self, args, environ):
        rc, out, err = run_env(self, args, environ)
        self.assertEqual(rc, 2)
        self.assertEqual(out, "")
        self.assertEqual(len(err.strip().splitlines()), 1, err)

    def test_unknown_shell_missing_target_and_missing_home_print_nothing(self):
        self.assert_refused(["--for=other.sh"], {"HOME": "/h"})
        self.assert_refused([], {"HOME": "/h"})
        self.assert_refused(["--for=use.sh"], {"HOME": "/h"})
        self.assert_refused(["--for=use.sh", "--target", "/t"], {})


class Source(unittest.TestCase):
    def test_parses_as_python_39_and_imports_only_outside_the_pack(self):
        self.assertTrue(LAUNCH.is_file(), f"部品 {LAUNCH} が無い")
        tree = ast.parse(LAUNCH.read_text(), feature_version=(3, 9))
        for node in ast.walk(tree):
            names = []
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                self.assertEqual(node.level, 0, "相対の import")
                names = [node.module]
            for name in names:
                spec = importlib.util.find_spec(name.split(".")[0])
                self.assertIsNotNone(spec, name)
                origin = spec.origin or ""
                self.assertFalse(origin.startswith(str(ROOT)), f"{name} は pack の中の物（{origin}）")


class CopiesFence(unittest.TestCase):
    PATTERNS = ('/works-dev}"', "command -v claude", 'WORKS_STATE_ROOT="${XDG_STATE_HOME', "use_home_default")

    def test_shells_hold_no_copy_of_home_default_or_claude_resolution(self):
        hits = []
        for name in (*SHELLS, "guard.sh", "continue.sh"):
            for no, line in enumerate((DEV / name).read_text().splitlines(), 1):
                hits += [f"{name}:{no}: {line.strip()}" for p in self.PATTERNS if p in line]
        self.assertEqual(hits, [])

    # 設計書 3 節: 殻に埋めた Python は部品へ移す途中なので、数が増えたら赤（減っても赤にしない）
    INLINE_PYTHON = re.compile(r"\bpython3(\s+-[A-Za-z]+)*\s+-[A-Za-z]*c\b")
    INLINE_PYTHON_CAPS = {"use.sh": 8, "dogfood.sh": 1, "real-run.sh": 0, "archon.sh": 0, "lib.sh": 9, "continue.sh": 0}

    def test_inline_python_in_shells_does_not_grow(self):
        for name, cap in self.INLINE_PYTHON_CAPS.items():
            lines = [line for line in (DEV / name).read_text().splitlines() if self.INLINE_PYTHON.search(line)]
            with self.subTest(shell=name):
                self.assertLessEqual(len(lines), cap, "\n".join(lines))

    def test_inline_python_pattern_catches_joined_flags(self):
        for line in ("python3 -c 'x'", "x=$(python3 -I -c 'x')", "python3 -Ic 'x'", "python3 -S  -c \"x\""):
            self.assertRegex(line, self.INLINE_PYTHON)
        for line in ("python3 -I \"$D/auth_launch.py\" check", "python3 -m pytest", "python3 - <<'EOF'"):
            self.assertNotRegex(line, self.INLINE_PYTHON)

    # 包みの既定と adapter の入力の値は部品が決める。殻が包みの既定を入れる・入力の値を自分で組む行は赤
    ADAPTER_DEFAULT = re.compile(r"(?:^|[\s;])WORKS_DEV_ADAPTER=\"?\$\{WORKS_DEV_ADAPTER:?-")
    ADAPTER_INPUT = re.compile(r"--input adapter=|\bADAPTER_MODE=")

    def test_shells_do_not_decide_adapter_default_or_input(self):
        hits = []
        for name in (*SHELLS, "lib.sh"):
            for no, line in enumerate((DEV / name).read_text().splitlines(), 1):
                if self.ADAPTER_DEFAULT.search(line) or (
                        self.ADAPTER_INPUT.search(line) and 'adapter="$WORKS_LAUNCH_ADAPTER_MODE"' not in line):
                    hits.append(f"{name}:{no}: {line.strip()}")
        self.assertEqual(hits, [])

    def test_adapter_fence_patterns_catch_old_and_variant_forms(self):
        for line in ('WORKS_DEV_ADAPTER="${WORKS_DEV_ADAPTER-1}"', "WORKS_DEV_ADAPTER=${WORKS_DEV_ADAPTER:-1}",
                     'then WORKS_DEV_ADAPTER="${WORKS_DEV_ADAPTER-}"; fi'):
            self.assertRegex(line, self.ADAPTER_DEFAULT)
        self.assertNotRegex('echo "包み無し（WORKS_DEV_ADAPTER=${WORKS_DEV_ADAPTER:-空}）"', self.ADAPTER_DEFAULT)
        for line in ('then ADAPTER_MODE=""; else ADAPTER_MODE="optional"; fi', "  ADAPTER_MODE=optional",
                     '--input adapter="$ADAPTER_MODE"', "--input adapter=optional"):
            self.assertRegex(line, self.ADAPTER_INPUT)

    def test_every_shell_receives_through_the_guard_function_only(self):
        for name in SHELLS:
            text = (DEV / name).read_text()
            with self.subTest(shell=name):
                self.assertIn(f"works_dev_launch_env {name}", text)
                self.assertNotRegex(text, r'eval "\$\(python3[^\n]*launch\.py')


class Receiving(unittest.TestCase):
    """guard.sh の works_dev_launch_env: 2 段で受け、部品の失敗と版の違いで止まり、代入を 1 つも効かせない"""

    def run_shell(self, fake_body):
        with tempfile.TemporaryDirectory() as d:
            shutil.copy(DEV / "guard.sh", pathlib.Path(d) / "guard.sh")
            (pathlib.Path(d) / "launch.py").write_text(fake_body)
            script = pathlib.Path(d) / "shell.sh"
            script.write_text('. "$(cd "$(dirname "$0")" && pwd -P)/guard.sh"\n'
                              'WORKS_DEV_HOME=before\n'
                              'works_dev_launch_env dogfood.sh\n'
                              'echo "after WORKS_DEV_HOME=$WORKS_DEV_HOME"\n')
            return subprocess.run(["/bin/sh", str(script)], capture_output=True, text=True, encoding="utf-8",
                                  env={"PATH": os.environ.get("PATH", ""), "HOME": d})

    def test_receives_assignments_when_the_part_succeeds(self):
        done = self.run_shell("print('WORKS_LAUNCH_FORMAT=1')\nprint('WORKS_DEV_HOME=/from/part')\n")
        self.assertEqual((done.returncode, done.stdout), (0, "after WORKS_DEV_HOME=/from/part\n"), done.stderr)

    def test_stops_without_assigning_when_the_part_fails(self):
        done = self.run_shell("import sys\nprint('WORKS_LAUNCH_FORMAT=1')\nprint('WORKS_DEV_HOME=/half')\nsys.exit(3)\n")
        self.assertNotEqual(done.returncode, 0)
        self.assertNotIn("after", done.stdout)

    def test_stops_on_another_format_version(self):
        done = self.run_shell("print('WORKS_LAUNCH_FORMAT=2')\nprint('WORKS_DEV_HOME=/newer')\n")
        self.assertEqual(done.returncode, 2)
        self.assertNotIn("after", done.stdout)
        self.assertEqual(len(done.stderr.strip().splitlines()), 1, done.stderr)


if __name__ == "__main__":
    unittest.main()
