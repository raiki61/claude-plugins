"""起動の殻の共通の口 works/dev/launch.py の動詞 env・ledger と、殻が受ける口（guard.sh works_dev_launch_env・works_dev_launch_eval）の柵
（設計書 2.2・2.3・3 節）。

- 家の既定・claude の解決・包みの既定と入力 adapter の値は部品の 1 つの表が持ち、殻 3 本（use.sh・dogfood.sh・archon.sh）に写しを戻したら赤
- run の控えの形（版の欄 schema・欄の無い古い控え）と起動の後の結び方（盤面の依頼がこの起動の写しと一致する run がちょうど 1 本の時だけ）は
  ledger が持ち、2 本の殻（use.sh・dogfood.sh）は lib.sh の同じ 1 つの関数を通す
- 殻 3 本と lib.sh の埋め込みの Python（python3 に -c を渡す行）の数が今の上限を超えたら赤
- 部品は env の dict を渡して直に呼ぶ（子のプロセスを起こさない）。受け方だけは偽の部品を置いて sh で起こす
- 期待の字は殻の今の ${X:-…} の字から写す（空は未設定と同じ・TMPDIR の末尾の / を残して連ねる）
"""
import ast
import hashlib
import importlib.util
import io
import json
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
SHELLS = ("use.sh", "dogfood.sh", "archon.sh")
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
        for shell in ("dogfood.sh", "archon.sh"):
            with self.subTest(shell=shell):
                got = assigned(self, [f"--for={shell}"], {"HOME": "/h", "TMPDIR": "/var/x/T/"})
                self.assertEqual(got["WORKS_DEV_HOME"], "/var/x/T//works-dev")

    def test_empty_values_count_as_unset_like_sh(self):
        for shell in ("dogfood.sh", "archon.sh"):
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
    ARGS = {"use.sh": ["--for=use.sh", "--target", "/t"], "dogfood.sh": ["--for=dogfood.sh"], "archon.sh": ["--for=archon.sh"]}

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

    def test_archon_emits_nothing(self):
        for value in (None, "1", "0"):
            named = {} if value is None else {"WORKS_DEV_ADAPTER": value}
            self.assertEqual(self.adapter(self.ARGS["archon.sh"], **named), (None, None))

    def test_show_is_refused_for_other_shells(self):
        for shell in ("use.sh", "archon.sh"):
            with self.subTest(shell=shell):
                rc, out, err = run_env(self, [*self.ARGS[shell], "--show"], {"HOME": "/h"})
                self.assertEqual((rc, out), (2, ""))
                self.assertEqual(len(err.strip().splitlines()), 1, err)


class ClaudeResolution(unittest.TestCase):
    def test_not_resolved_without_claude_flag(self):
        with tempfile.TemporaryDirectory() as d:
            fake_claude(d)
            for shell in ("dogfood.sh", "archon.sh"):
                got = assigned(self, [f"--for={shell}"], {"HOME": "/h", "PATH": d})
                self.assertNotIn("WORKS_LAUNCH_CLAUDE", got)

    def test_explicit_then_path_then_empty(self):
        with tempfile.TemporaryDirectory() as d:
            claude = fake_claude(d)
            for shell, extra in (("dogfood.sh", []), ("use.sh", ["--target", "/t"])):
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
    INLINE_PYTHON_CAPS = {"use.sh": 5, "dogfood.sh": 0, "archon.sh": 0, "lib.sh": 7, "continue.sh": 0}

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


class BindFence(unittest.TestCase):
    """起動の後の結び方（設計書 2.3）: 3 本の殻は起動ごとの依頼の写しの絶対パスを Archon に渡し、同じ写しで同じ lib.sh の
    1 つの関数を通して run を結ぶ（一覧の一番新しい run を推定で採らない）"""
    REQUEST_INPUT = re.compile(r"--input request=(\S+)")

    def request_token(self, name):
        found = self.REQUEST_INPUT.findall((DEV / name).read_text())
        self.assertEqual(len(found), 1, f"{name}: --input request= の行 {found}")
        return found[0]

    def test_launchers_pass_a_per_launch_request_path_not_a_relative_file(self):
        for name in ("dogfood.sh", "use.sh"):
            with self.subTest(shell=name):
                self.assertRegex(self.request_token(name), r'^"\$[A-Z_]+"$')

    def bind_call(self, name):
        lines = [line.strip() for line in (DEV / name).read_text().splitlines() if "|| show_status=$?" in line]
        self.assertEqual(len(lines), 1, f"{name}: 起動の後に結ぶ行 {lines}")
        return lines[0]

    def test_post_start_binding_names_the_request_and_shares_one_function(self):
        funcs = set()
        for name in ("dogfood.sh",):
            with self.subTest(shell=name):
                line = self.bind_call(name)
                self.assertIn(self.request_token(name), line)
                funcs.add(line.split()[0])
        self.assertEqual(len(funcs), 1, funcs)
        func = funcs.pop()
        self.assertTrue(re.search(rf"^{func}\(\) {{", (DEV / "lib.sh").read_text(), re.M), f"lib.sh に {func} が無い")
        self.assertRegex((DEV / "use.sh").read_text(), rf'\b{func}\b[^\n]*"\$REQUEST"')


def run_ledger(case, args, environ=None, stdin=""):
    """launch.main(["ledger", …]) を呼び、(終了コード, 標準出力, 標準エラー) を返す"""
    out, err = io.StringIO(), io.StringIO()
    rc = load(case).main(["ledger", *args], dict(environ or {}), out, err, io.StringIO(stdin))
    return rc, out.getvalue(), err.getvalue()


def sh_assigned(case, text, names):
    """代入の行を sh で 2 段に受けた（guard.sh works_dev_launch_eval）後の names の値を {名: 値} で返す"""
    probe = "".join(f'printf "%s=%s\\n" {n} "${{{n}-(unset)}}"\n' for n in names)
    done = subprocess.run(["/bin/sh", "-c", f'. "{DEV}/guard.sh"; works_dev_launch_eval t "$1" || exit $?\n{probe}', "sh",
                           text], capture_output=True, text=True, encoding="utf-8", env={"PATH": os.environ.get("PATH", "")})
    case.assertEqual(done.returncode, 0, done.stderr)
    return dict(line.split("=", 1) for line in done.stdout.splitlines())


class Ledger(unittest.TestCase):
    """控えの形と版（設計書 2.3 の ledger）。書く時はいつも今の版、欄の無い古い控えは元の形として読み、知らない版は止める"""
    LOAD_NAMES = ("WORKS_DEV_MODEL", "WORKS_MODEL_PINNED", "CLAUDE_BIN_PATH", "WORKS_KEYCHAIN_ITEM", "WORKS_DEV_ADAPTER")

    def setUp(self):
        self.dir = pathlib.Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.dir)

    def save(self, run_id="run-1", target="/t", value="opus", origin="既定（WORKS_DEV_MODEL_DEFAULT）", wrap_ref=None,
             **environ):
        rc, out, err = run_ledger(self, ["save", "--dir", str(self.dir), "--run-id", run_id, "--target", target,
                                         "--model-value", value, "--model-from", origin,
                                         *(["--wrap-ref", wrap_ref] if wrap_ref is not None else [])], environ)
        self.assertEqual((rc, out), (0, ""), err)
        return json.loads((self.dir / f"{run_id}.json").read_text(encoding="utf-8"))

    def test_save_writes_every_field_with_schema(self):
        doc = self.save(wrap_ref="refs/works/wraps/abc", WORKS_DEV_MODEL="", CLAUDE_BIN_PATH="/c",
                        WORKS_KEYCHAIN_ITEM="item", WORKS_DEV_ADAPTER="1", HERDR_ENV="1", HERDR_PANE_ID="pane-7",
                        HERDR_SOCKET_PATH="/s/herdr.sock", WORKS_CONTEXT7_KEYCHAIN_ITEM="c7-item", CONTEXT7_API_KEY="ctx7sk-secret")
        self.assertEqual(self.save(WRAP_REF="refs/works/wraps/from-env")["wrap_ref"], "")   # 環境からは読まない（旗だけ）
        self.assertEqual(doc["schema"], 1)
        self.assertEqual({k: doc[k] for k in ("run_id", "target", "model", "claude_bin", "keychain_item", "adapter",
                                              "wrap_ref", "herdr_pane", "herdr_socket")},
                         {"run_id": "run-1", "target": "/t", "model": "", "claude_bin": "/c", "keychain_item": "item",
                          "adapter": "1", "wrap_ref": "refs/works/wraps/abc",
                          "herdr_pane": "pane-7", "herdr_socket": "/s/herdr.sock"})
        # 隔離の前の読み出しのファイルはやめた（2026-10-09。PR・issue は run の中で読む）: 控えに欄を書かず、旗も受けない
        self.assertNotIn("github_reads", doc)
        rc, out, err = run_ledger(self, ["save", "--dir", str(self.dir), "--run-id", "x", "--target", "/t", "--model-value", "o",
                                         "--model-from", "f", "--github-reads", "/h/reads/1.json"])
        self.assertEqual((rc, out), (2, ""), err)
        # Context7 はやめた（持ち主 2026-10-09）: 前の版の鍵の項目の名が env に残っていても控えに書かない
        self.assertNotIn("context7_keychain_item", doc)
        self.assertNotIn("c7-item", json.dumps(doc))
        self.assertNotIn("ctx7sk-secret", json.dumps(doc))
        self.assertEqual(doc["model_resolved"], {"value": "opus", "from": "既定（WORKS_DEV_MODEL_DEFAULT）"})
        self.assertIsInstance(doc["started_at"], float)
        self.assertEqual(sorted(p.name for p in self.dir.iterdir()), ["run-1.json"])   # 途中の写しを残さない

    def test_save_leaves_pane_empty_outside_herdr(self):
        self.assertEqual(self.save(HERDR_PANE_ID="pane-7")["herdr_pane"], "")
        self.assertEqual(self.save(HERDR_SOCKET_PATH="/s/herdr.sock")["herdr_socket"], "")
        self.assertEqual(self.save(HERDR_ENV="0", HERDR_PANE_ID="pane-7")["herdr_pane"], "")

    def test_save_refuses_run_id_that_is_not_a_file_name(self):
        for run_id in ("", "../x", "a/b", ".hidden"):
            with self.subTest(run_id=run_id):
                rc, out, err = run_ledger(self, ["save", "--dir", str(self.dir), "--run-id", run_id, "--target", "/t",
                                                 "--model-value", "opus", "--model-from", "x"])
                self.assertEqual((rc, out), (2, ""))
                self.assertEqual(len(err.strip().splitlines()), 1, err)
        self.assertEqual(list(self.dir.iterdir()), [])

    def test_list_reads_old_ledgers_into_the_same_seven_columns(self):
        target = self.dir / "target"
        target.mkdir()
        (self.dir / "old.json").write_text(json.dumps({"run_id": "old", "target": str(target), "started_at": 1.5,
                                                       "wrap_ref": "refs/works/wraps/abc", "herdr_pane": "pane-7"}))
        (self.dir / "other.json").write_text(json.dumps({"run_id": "other", "wrap_ref": "refs/heads/main",
                                                         "github_reads": "/h/reads/1.json"}))   # 前の版の読み出しの欄は読まない
        self.save("new", str(target))
        rc, out, err = run_ledger(self, ["list", "--dir", str(self.dir)])
        self.assertEqual(rc, 0, err)
        rows = [line.split("\t") for line in out.splitlines()]
        self.assertEqual([r[0] for r in rows], ["new", "old", "other"])
        self.assertEqual(rows[1], ["old", str(target.resolve()), "1.5", "refs/works/wraps/abc", "pane-7", "", ""])
        self.assertEqual(rows[2], ["other", "", "0", "", "", "", ""])
        self.assertEqual(rows[0][1], str(target.resolve()))
        rc, out, err = run_ledger(self, ["list", "--dir", str(self.dir), "--run-id", "old"])
        self.assertEqual([line.split("\t")[0] for line in out.splitlines()], ["old"])

    def test_list_skips_broken_and_unknown_schema_quietly(self):
        (self.dir / "broken.json").write_text("{not json")
        (self.dir / "noid.json").write_text(json.dumps({"target": "/t"}))
        (self.dir / "newer.json").write_text(json.dumps({"schema": 2, "run_id": "newer"}))
        (self.dir / "odd.json").write_text(json.dumps({"schema": True, "run_id": "odd"}))
        self.save("ok")
        rc, out, err = run_ledger(self, ["list", "--dir", str(self.dir)])
        self.assertEqual((rc, err), (0, ""))
        self.assertEqual([line.split("\t")[0] for line in out.splitlines()], ["ok"])

    def loaded(self, run_id):
        rc, out, err = run_ledger(self, ["load", "--dir", str(self.dir), "--run-id", run_id])
        self.assertEqual(rc, 0, err)
        self.assertEqual(out.splitlines()[:1], ["WORKS_LAUNCH_FORMAT=1"], out)
        for line in out.splitlines()[1:]:
            self.assertIn(line.partition("=")[0], self.LOAD_NAMES, line)
        return sh_assigned(self, out, self.LOAD_NAMES)

    def test_load_pins_resolved_model_only_when_model_was_not_given(self):
        self.save("default", WORKS_DEV_MODEL="", CLAUDE_BIN_PATH="/c d/claude", WORKS_KEYCHAIN_ITEM="it's", WORKS_DEV_ADAPTER="")
        got = self.loaded("default")
        self.assertEqual(got, {"WORKS_DEV_MODEL": "", "WORKS_MODEL_PINNED": "opus", "CLAUDE_BIN_PATH": "/c d/claude",
                               "WORKS_KEYCHAIN_ITEM": "it's", "WORKS_DEV_ADAPTER": ""})
        self.save("explicit", value="sonnet", origin="env WORKS_DEV_MODEL", WORKS_DEV_MODEL="sonnet")
        got = self.loaded("explicit")
        self.assertEqual((got["WORKS_DEV_MODEL"], got["WORKS_MODEL_PINNED"]), ("sonnet", "(unset)"))
        self.assertEqual((got["CLAUDE_BIN_PATH"], got["WORKS_KEYCHAIN_ITEM"]), ("(unset)", "(unset)"))

    def test_load_does_not_export_a_context7_item_of_an_older_ledger(self):
        """前の版の控えに Context7 の鍵の項目の名（context7_keychain_item）が在っても、続きの殻に戻さない（読み飛ばすだけで止めない）"""
        (self.dir / "c7.json").write_text(json.dumps({"schema": 1, "run_id": "c7", "model": "opus", "claude_bin": "/c",
                                                      "context7_keychain_item": "c7-item"}))
        got = self.loaded("c7")
        self.assertEqual(got["CLAUDE_BIN_PATH"], "/c")

    def test_load_reads_old_ledger_without_schema(self):
        (self.dir / "old.json").write_text(json.dumps({"run_id": "old", "model": "", "claude_bin": "/c", "adapter": "1"}))
        got = self.loaded("old")
        self.assertEqual((got["WORKS_DEV_MODEL"], got["WORKS_MODEL_PINNED"], got["CLAUDE_BIN_PATH"], got["WORKS_DEV_ADAPTER"]),
                         ("", "(unset)", "/c", "1"))

    def test_load_with_broken_ledger_prints_only_the_format_line(self):
        (self.dir / "broken.json").write_text("{not json")
        rc, out, err = run_ledger(self, ["load", "--dir", str(self.dir), "--run-id", "broken"])
        self.assertEqual((rc, out), (0, "WORKS_LAUNCH_FORMAT=1\n"))
        self.assertEqual(len(err.strip().splitlines()), 1, err)

    def test_load_refuses_missing_and_unknown_schema_with_nothing_on_stdout(self):
        (self.dir / "newer.json").write_text(json.dumps({"schema": 2, "run_id": "newer", "model": "x"}))
        for run_id in ("newer", "missing"):
            with self.subTest(run_id=run_id):
                rc, out, err = run_ledger(self, ["load", "--dir", str(self.dir), "--run-id", run_id])
                self.assertEqual((rc, out), (2, ""))
                self.assertEqual(len(err.strip().splitlines()), 1, err)

    def test_env_and_ledger_keep_separate_name_lists(self):
        mod = load(self)
        self.assertFalse({"WORKS_DEV_MODEL", "WORKS_MODEL_PINNED", "CLAUDE_BIN_PATH", "WORKS_KEYCHAIN_ITEM"} & mod.ALLOWED_NAMES)
        self.assertFalse(mod.LEDGER_BIND_NAMES & (mod.ALLOWED_NAMES | mod.LEDGER_LOAD_NAMES))

    def test_unknown_verb_and_arguments_are_refused(self):
        for args in ([], ["drop"], ["list"], ["list", "--dir"], ["load", "--dir", "d", "--run-id", "x", "--extra", "y"]):
            with self.subTest(args=args):
                rc, out, err = run_ledger(self, args)
                self.assertEqual((rc, out), (2, ""))
                self.assertEqual(len(err.strip().splitlines()), 1, err)


class Bind(unittest.TestCase):
    """起動の後の結び方: 盤面の依頼がこの起動の写しと一致する run がちょうど 1 本の時だけ結んで控えを書く（設計書 2.3）"""

    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp)
        self.out = self.tmp / "out"
        self.runs = self.tmp / "runs"
        self.target = self.tmp / "target"
        self.target.mkdir()
        self.request = self.tmp / "request.json"
        self.request.write_text("[]\n")

    def row(self, run_id, request=None, board="r1/start.json", **extra):
        if request is not None:
            path = self.out / "artifacts" / "runs" / run_id / "board" / board
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps({"request_file": request} if board == "r1/start.json"
                                       else {"inputs": {"request": request}}))
        return {"id": run_id, "workflow_name": "darkfactory", "status": "paused", "output_root": str(self.out), **extra}

    def bind(self, rows, request=None):
        return run_ledger(self, ["bind", "--for", "use.sh", "--dir", str(self.runs), "--target", str(self.target),
                                 "--request", str(self.request) if request is None else request,
                                 "--model-value", "opus", "--model-from", "既定"],
                          {"WORKS_DEV_MODEL": ""}, json.dumps({"runs": rows}))

    def test_binds_the_one_run_whose_board_names_this_request(self):
        for board in ("r1/start.json", "state.json"):
            with self.subTest(board=board):
                shutil.rmtree(self.runs, ignore_errors=True)
                rows = [self.row("other", str(self.tmp / "other.json"), board), self.row("mine", str(self.request), board),
                        self.row("no-board")]
                rc, out, err = self.bind(rows)
                self.assertEqual(rc, 0, err)
                got = sh_assigned(self, out, ("WORKS_RUN_ID", "WORKS_RUN_STATUS", "WORKS_RUN_ROW"))
                self.assertEqual((got["WORKS_RUN_ID"], got["WORKS_RUN_STATUS"]), ("mine", "paused"))
                self.assertEqual(json.loads(got["WORKS_RUN_ROW"])["id"], "mine")
                led = json.loads((self.runs / "mine.json").read_text())
                self.assertEqual((led["schema"], led["run_id"], led["target"]), (1, "mine", str(self.target)))
                self.assertEqual(sorted(p.name for p in self.runs.iterdir()), ["mine.json"])

    def test_binds_a_run_still_at_the_launch_gate_by_archons_recorded_input(self):
        """起動の直後は最初の関所（launch）で止まり、start の節がまだ走らず盤面が無い。Archon が run に残した入力
        （runs --json の metadata.inputs.request。dict でも JSON の文字列でも）で結ぶ（実測 2026-10-01: 盤面だけを見て 0 本になった）"""
        for meta in ({"inputs": {"request": str(self.request)}}, json.dumps({"inputs": {"request": str(self.request)}})):
            with self.subTest(meta=type(meta).__name__):
                shutil.rmtree(self.runs, ignore_errors=True)
                rows = [self.row("mine", metadata=meta),
                        self.row("other", metadata={"inputs": {"request": str(self.tmp / "other.json")}})]
                rc, out, err = self.bind(rows)
                self.assertEqual(rc, 0, err)
                self.assertEqual(sh_assigned(self, out, ("WORKS_RUN_ID",))["WORKS_RUN_ID"], "mine")

    def assert_unbound(self, rc, out, err, *says):
        self.assertEqual((rc, out), (1, ""))
        for text in says:
            self.assertIn(text, err)
        self.assertFalse(self.runs.exists(), "結べないのに控えを書いた")

    def test_does_not_bind_a_run_without_board(self):
        rc, out, err = self.bind([self.row("no-board"), self.row("other", str(self.tmp / "other.json"))])
        self.assert_unbound(rc, out, err, "候補が 0 本", "推定では選ばない")

    def test_two_matching_runs_list_candidates_and_do_not_bind(self):
        rc, out, err = self.bind([self.row("a", str(self.request)), self.row("b", str(self.request))])
        self.assert_unbound(rc, out, err, "候補が 2 本", f"候補 a（paused）: use.sh show {self.target.resolve()} a",
                            f"候補 b（paused）: use.sh show {self.target.resolve()} b")

    def test_launch_without_request_copy_does_not_bind(self):
        """起動の印も依頼の写しも渡さない起動（前の版の殻）は目印が無いので結ばない"""
        rc, out, err = self.bind([self.row("change-only", "")], request="")
        self.assert_unbound(rc, out, err, "起動の印も依頼の写しも無い起動", "候補 change-only")

    def bind_mark(self, rows, mark):
        """依頼を省いた起動（--pr）の結び方: --request は空、--launch-mark にこの起動の印"""
        return run_ledger(self, ["bind", "--for", "use.sh", "--dir", str(self.runs), "--target", str(self.target),
                                 "--request", "", "--launch-mark", mark,
                                 "--model-value", "opus", "--model-from", "既定"],
                          {"WORKS_DEV_MODEL": ""}, json.dumps({"runs": rows}))

    def test_launch_without_request_binds_by_its_launch_mark(self):
        """依頼の写しが無くても、起動の印（起動ごとに一意。Archon が残した metadata.inputs.launch_mark）が
        この起動の物と一致する run がちょうど 1 本なら結ぶ（dict でも JSON の文字列でも）"""
        for wrap in (lambda m: m, json.dumps):
            with self.subTest(meta=type(wrap({})).__name__):
                shutil.rmtree(self.runs, ignore_errors=True)
                rows = [self.row("mine", metadata=wrap({"inputs": {"request": "", "launch_mark": "20261009-1"}})),
                        self.row("other", metadata={"inputs": {"request": "", "launch_mark": "20261009-2"}}),
                        self.row("no-mark", metadata={"inputs": {"request": ""}})]
                rc, out, err = self.bind_mark(rows, "20261009-1")
                self.assertEqual(rc, 0, err)
                self.assertEqual(sh_assigned(self, out, ("WORKS_RUN_ID",))["WORKS_RUN_ID"], "mine")
                self.assertNotIn("github_reads", json.loads((self.runs / "mine.json").read_text()))

    def test_launch_with_request_and_mark_binds_by_either(self):
        """殻はどの入口の起動にも印を付ける（段 4.1）。印と依頼の写しはどちらもこの起動だけを指す目印で、どちらかが一致する run を
        結ぶ: 印だけが一致する run（盤面がまだ無い起動の直後）も、写しだけが一致する run（印を残さない前の版の Archon）も結ぶ"""
        args = lambda mark: ["bind", "--for", "use.sh", "--dir", str(self.runs), "--target", str(self.target),
                             "--request", str(self.request), "--launch-mark", mark, "--model-value", "opus", "--model-from", "既定"]
        for name, rows in (("mark", [self.row("mine", metadata={"inputs": {"launch_mark": "20261009-1"}}),
                                     self.row("other", metadata={"inputs": {"launch_mark": "20261009-2"}})]),
                           ("request", [self.row("mine", str(self.request)), self.row("other", "/elsewhere.json")])):
            with self.subTest(name):
                shutil.rmtree(self.runs, ignore_errors=True)
                rc, out, err = run_ledger(self, args("20261009-1"), {"WORKS_DEV_MODEL": ""}, json.dumps({"runs": rows}))
                self.assertEqual(rc, 0, err)
                self.assertEqual(sh_assigned(self, out, ("WORKS_RUN_ID",))["WORKS_RUN_ID"], "mine")

    def test_launch_without_request_and_not_one_run_with_its_mark_does_not_bind(self):
        """起動の印の一致する run が 0 本・2 本なら結ばない（推定では選ばない）"""
        same = {"inputs": {"request": "", "launch_mark": "20261009-1"}}
        for rows, says in (([self.row("a", metadata=same), self.row("b", metadata=same)],
                            ("候補が 2 本", f"候補 a（paused）: use.sh show {self.target.resolve()} a", "候補 b")),
                           ([self.row("other", metadata={"inputs": {"launch_mark": "20261009-2"}})],
                            ("候補が 0 本",))):
            with self.subTest(n=len(rows)):
                rc, out, err = self.bind_mark(rows, "20261009-1")
                self.assert_unbound(rc, out, err, "起動の印", "推定では選ばない", *says)

    def test_no_run_and_other_target_and_other_workflow_are_not_found(self):
        mine = str(self.request)
        rows = [self.row("x", mine, metadata={"workflow_source": {"origin": str(self.tmp)}}),
                dict(self.row("y", mine), workflow_name="other")]
        for listed in ([], rows):
            with self.subTest(n=len(listed)):
                rc, out, err = self.bind(listed)
                self.assert_unbound(rc, out, err, "use.sh: darkfactory の run が見つからない")
        rc, out, err = run_ledger(self, ["bind", "--for", "use.sh", "--dir", str(self.runs), "--target", str(self.target),
                                         "--request", mine, "--model-value", "o", "--model-from", "f"], {}, "not json")
        self.assert_unbound(rc, out, err, "JSON として読めない")

    def test_launch_without_marks_lists_only_runs_without_request_and_mark(self):
        """印の無い起動の結べない文の候補は、依頼の写しも起動の印も持たない run だけ（印の在る run は自分の起動が結ぶ）"""
        rows = [self.row("bare"), self.row("asked", str(self.request)),
                self.row("read", metadata={"inputs": {"launch_mark": "20261009-1"}})]
        rc, out, err = self.bind(rows, request="")
        self.assert_unbound(rc, out, err, "候補 bare")
        self.assertNotIn("候補 asked", err)
        self.assertNotIn("候補 read", err)

    def unbound_save(self, listed, stamp="20261002-1", wrap_ref="refs/works/wraps/abc"):
        return run_ledger(self, ["unbound-save", "--dir", str(self.tmp / "unbound"), "--target", str(self.target),
                                 "--stamp", stamp, "--wrap-ref", wrap_ref], {}, listed)

    def unbound_release(self, run_id, target=None, rows=()):
        return run_ledger(self, ["unbound-release", "--dir", str(self.tmp / "unbound"), "--target",
                                 str(target or self.target), "--run-id", run_id], {}, json.dumps({"runs": list(rows)}))

    def test_unbound_save_keeps_paths_with_unmarked_candidates_and_release_returns_them(self):
        """結べなかった起動の包んだ基を、印の無い候補と一緒に控えに残し、候補の run id と対象で引ける"""
        rows = [self.row("bare"), self.row("asked", str(self.request)),
                self.row("elsewhere", metadata={"workflow_source": {"origin": str(self.tmp)}})]
        rc, out, err = self.unbound_save(json.dumps({"runs": rows}))
        self.assertEqual((rc, out), (0, "bare\n"), err)
        path = self.tmp / "unbound" / "20261002-1.json"
        self.assertEqual(json.loads(path.read_text()), {"wrap_ref": "refs/works/wraps/abc",
                                                        "candidates": ["bare"], "target": str(self.target.resolve())})
        for run_id, target in (("asked", None), ("bare", self.tmp)):
            with self.subTest(run_id=run_id, target=str(target)):
                self.assertEqual(self.unbound_release(run_id, target), (0, "", ""))
        self.assertEqual(self.unbound_release("bare"), (0, f"{path}\trefs/works/wraps/abc\t\n", ""))

    def test_unbound_release_keeps_paths_while_another_candidate_lives(self):
        """ほかの候補が生きて（running・paused・pending）いる間は包んだ基を返さず、控えの候補からその run だけを
        外して書き戻す（生きた run の使う物を消さない）。最後の候補で返す。一覧に無い・終わった候補は生きていない"""
        self.unbound_save(json.dumps({"runs": [self.row("a"), self.row("b"), self.row("c")]}))
        path = self.tmp / "unbound" / "20261002-1.json"
        for status in ("running", "paused", "pending"):
            with self.subTest(status=status):
                rows = [dict(self.row("a"), status="completed"), dict(self.row("b"), status=status)]
                self.assertEqual(self.unbound_release("a", rows=rows), (0, f"{path}\t\tb\n", ""))
                self.assertEqual(json.loads(path.read_text())["candidates"], ["b", "c"])
                doc = json.loads(path.read_text())
                path.write_text(json.dumps(dict(doc, candidates=["a", "b", "c"])))
        rows = [dict(self.row("a"), status="completed"), dict(self.row("b"), status="failed")]
        self.assertEqual(self.unbound_release("a", rows=rows),
                         (0, f"{path}\trefs/works/wraps/abc\t\n", ""))

    def test_unbound_release_handles_every_control_naming_the_run(self):
        """同じ run を候補に持つ控えが 2 つ在れば全部回り、控えごとに 1 行を出す（最初の 1 つで返らない）"""
        self.unbound_save(json.dumps({"runs": [self.row("a")]}), stamp="1-A", wrap_ref="refs/works/wraps/a")
        self.unbound_save(json.dumps({"runs": [self.row("a"), self.row("b")]}), stamp="2-B", wrap_ref="refs/works/wraps/b")
        a, b = self.tmp / "unbound" / "1-A.json", self.tmp / "unbound" / "2-B.json"
        rows = [self.row("a"), dict(self.row("b"), status="completed")]
        self.assertEqual(self.unbound_release("b", rows=rows), (0, f"{b}\t\ta\n", ""))
        self.assertEqual(json.loads(b.read_text())["candidates"], ["a"])
        rows = [dict(self.row("a"), status="completed"), dict(self.row("b"), status="completed")]
        self.assertEqual(self.unbound_release("a", rows=rows),
                         (0, f"{a}\trefs/works/wraps/a\t\n{b}\trefs/works/wraps/b\t\n", ""))

    def test_unbound_save_lists_only_live_candidates(self):
        """控えの候補は生きた状態（LIVE_STATUSES）の印の無い run だけ。終わった run は候補に載せず、生きた候補が 0 本なら書かない"""
        rows = [self.row("live"), dict(self.row("done"), status="completed"), dict(self.row("broke"), status="failed")]
        self.assertEqual(self.unbound_save(json.dumps({"runs": rows}))[:2], (0, "live\n"))
        self.assertEqual(json.loads((self.tmp / "unbound" / "20261002-1.json").read_text())["candidates"], ["live"])
        shutil.rmtree(self.tmp / "unbound")
        self.assertEqual(self.unbound_save(json.dumps({"runs": rows[1:]})), (0, "", ""))
        self.assertFalse((self.tmp / "unbound").exists())

    def test_live_tells_whether_a_status_is_live(self):
        """生きた状態の一覧は LIVE_STATUSES の 1 か所。ledger live は生きた状態なら 1 を出す（use.sh clean の拒みが読む）"""
        mod = load(self)
        self.assertEqual(set(mod.LIVE_STATUSES), {"running", "paused", "pending"})
        for status, want in (("running", "1\n"), ("paused", "1\n"), ("pending", "1\n"), ("completed", ""), ("", "")):
            with self.subTest(status=status):
                self.assertEqual(run_ledger(self, ["live", "--status", status]), (0, want, ""))

    def test_unbound_release_refuses_unreadable_list(self):
        """一覧が読めなければほかの候補が生きているか分からないので、何も返さず控えも書き換えずに止める"""
        self.unbound_save(json.dumps({"runs": [self.row("a"), self.row("b")]}))
        rc, out, err = run_ledger(self, ["unbound-release", "--dir", str(self.tmp / "unbound"), "--target",
                                         str(self.target), "--run-id", "a"], {}, "not json")
        self.assertEqual((rc, out), (2, ""))
        self.assertIn("JSON として読めない", err)
        self.assertEqual(json.loads((self.tmp / "unbound" / "20261002-1.json").read_text())["candidates"], ["a", "b"])

    def test_unbound_save_refuses_unreadable_list_and_keeps_paths_in_unknown_control(self):
        """一覧が読めない（JSON でない・空・runs が無い・null・dict・文字列）時は、読めた 0 本（空を返して呼び手が消す）と同じに畳まず、
        2 で止めて、候補の無い控え（unknown）に包んだ基を残す。読めた 0 本は今までどおり何も書かずに空を返す"""
        path = self.tmp / "unbound" / "20261002-1.json"
        for listed in ("not json", "", "{}", "[]", '{"runs": null}', '{"runs": {}}', '{"runs": "x"}'):
            with self.subTest(listed=listed):
                shutil.rmtree(self.tmp / "unbound", ignore_errors=True)
                rc, out, err = self.unbound_save(listed)
                self.assertEqual((rc, out), (2, ""))
                self.assertIn("JSON として読めない", err)
                self.assertIn(str(path), err)
                self.assertEqual(json.loads(path.read_text()),
                                 {"wrap_ref": "refs/works/wraps/abc", "target": str(self.target.resolve()),
                                  "candidates": [], "unknown": True})
        shutil.rmtree(self.tmp / "unbound")
        self.assertEqual(self.unbound_save('{"runs": []}'), (0, "", ""))
        self.assertFalse((self.tmp / "unbound").exists())

    def test_unbound_release_returns_unknown_control_only_when_no_run_lives(self):
        """一覧が読めずに残した控え（unknown。どの run の物か分からない）は、clean が一覧を読めた時にこの対象の生きた run が 1 本でも
        在れば返さず、1 本も無ければ（clean する run 自身は生きていない）返す。ほかの対象の控えは触らない"""
        self.unbound_save("not json")
        path = self.tmp / "unbound" / "20261002-1.json"
        self.assertEqual(self.unbound_release("a", rows=[self.row("b")]), (0, "", ""))
        self.assertTrue(path.exists())
        rows = [dict(self.row("a"), status="completed")]
        self.assertEqual(self.unbound_release("a", target=self.tmp, rows=rows), (0, "", ""))
        self.assertEqual(self.unbound_release("a", rows=rows),
                         (0, f"{path}\trefs/works/wraps/abc\t\n", ""))

    def test_unbound_release_hands_back_only_safe_paths(self):
        """控えの参照は refs/works/wraps/ の下の時だけ返す（手で書き換えた控えで別の物を消さない）"""
        self.unbound_save(json.dumps({"runs": [self.row("bare")]}), wrap_ref="refs/heads/main")
        self.assertEqual(self.unbound_release("bare"), (0, f"{self.tmp / 'unbound' / '20261002-1.json'}\t\t\n", ""))

    def test_unbound_stamp_must_be_a_file_name(self):
        for stamp in ("", "a/b", ".x"):
            with self.subTest(stamp=stamp):
                rc, out, err = self.unbound_save(json.dumps({"runs": [self.row("bare")]}), stamp=stamp)
                self.assertEqual((rc, out), (2, ""))
                self.assertIn("印", err)


class BindShell(unittest.TestCase):
    """lib.sh works_dev_ledger_bind: 一覧を引いて部品で結び、結べた時だけ控えと WORKS_RUN_* を置く。結べなければ 1 行で 1"""

    def run_bind(self, start_json):
        with tempfile.TemporaryDirectory() as d:
            tmp = pathlib.Path(d)
            out = tmp / "out"
            request = tmp / "request.json"
            request.write_text("[]\n")
            if start_json is not None:
                board = out / "artifacts" / "runs" / "run-1" / "board" / "r1"
                board.mkdir(parents=True)
                (board / "start.json").write_text(json.dumps({"request_file": start_json or str(request)}))
            listed = json.dumps({"runs": [{"id": "run-1", "workflow_name": "darkfactory", "status": "paused",
                                           "output_root": str(out)}]})
            fake = tmp / "archon.sh"
            fake.write_text(f"#!/bin/sh\ncat <<'EOF'\n{listed}\nEOF\n")
            # use.sh の WRAP_REF は export しない殻の変数
            script = (f'. "{DEV}/guard.sh"; . "{DEV}/lib.sh"\nWRAP_REF=refs/works/wraps/abc\n'
                      f'if works_dev_ledger_bind use.sh "{fake}" "{tmp}" "{request}"; then\n'
                      '  echo "bound $WORKS_RUN_ID $WORKS_RUN_STATUS"\nelse\n  echo "status $?"\nfi\n')
            done = subprocess.run(["/bin/sh", "-c", script], capture_output=True, text=True, encoding="utf-8",
                                  env={"PATH": os.environ.get("PATH", ""), "DEV_DIR": str(DEV), "WORKS_DEV_HOME": str(tmp)})
            ledgers = {p.name: json.loads(p.read_text()) for p in (tmp / "runs").iterdir()} if (tmp / "runs").exists() else {}
            return done, ledgers

    def test_binds_and_writes_ledger_when_board_names_the_request(self):
        done, ledgers = self.run_bind("")
        self.assertEqual(done.stdout, "bound run-1 paused\n", done.stderr)
        self.assertEqual(list(ledgers), ["run-1.json"])
        self.assertEqual(ledgers["run-1.json"]["wrap_ref"], "refs/works/wraps/abc")

    def test_unbound_prints_one_line_and_writes_nothing(self):
        for start_json in (None, "/elsewhere/request.json"):
            with self.subTest(start_json=start_json):
                done, ledgers = self.run_bind(start_json)
                self.assertEqual(done.stdout.splitlines()[-1], "status 1", done.stdout + done.stderr)
                self.assertIn("この起動の run を結べなかった", done.stdout)
                self.assertNotIn("bound", done.stdout)
                self.assertEqual(ledgers, {})

    def test_use_sh_receives_ledger_load_in_two_steps(self):
        text = (DEV / "use.sh").read_text()
        self.assertNotRegex(text, r'eval "\$\(python3')
        body = re.search(r"^load_ledger\(\) \{\n(.*?)^\}", text, re.M | re.S).group(1)
        self.assertRegex(body, r"\$\(works_dev_launch ledger load [^\n]*\) \|\| exit \$\?")
        self.assertIn("works_dev_launch_eval use.sh", body)


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
