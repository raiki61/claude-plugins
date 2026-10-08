"""テストの段（tests/tiers.py の FAST・HEAVY）と、段を選ぶ入口 run.sh（WORKS_TESTS）の検査。

- 段の一覧: fast と heavy は重ならず、合わせると discover が拾う全部のモジュール。どのモジュールも明示で
  どちらかに書く（書き忘れた新しいモジュールは名前を挙げて赤。重いテストが黙って fast に入らない）
- 段の読み込み（TierLoader）: 段ごとの discover のテストを合わせると、ちょうど全部の discover のテスト
- run.sh: 既定は全部を tiers.py all で、fast・heavy は tiers.py で回し、unittest の引数（-k など）をそのまま渡す。
  知らない値は 1 行で終了コード 2。全部と heavy は枠の台本（WORKS_TESTSLOT）を TESTSLOT_N=4 で通し、fast は通さない。
  枠の約束の正本は .shared/core/slotwrap.sh で、run.sh はそこへ渡すだけ。置き場は台本の約束 TESTSLOT_DIR で、slotwrap.sh が
  そこを試し・祖先を探し・台本へ渡す（試験は一時フォルダに向ける）。
  台本が無い・枠の置き場に書けないときは 1 行出して枠なしで回し、祖先が枠を持っていれば取り直さない。
  uv と枠の台本は偽物に差し替える（本物のテスト一式は回さない）
- 試験の密閉（HermeticCase）: 親の環境を丸ごと写す 3 つの字面を拒み tests/hermetic.py を通させる・一時フォルダは実体のパス・
  /private の別名はファイルの仕組みから引く（見ない入口は hermetic.py の説明）
- run の口（RunSlotCase）: engine の既定の runner・test_cmd・blk-tests の _run も枠を通り、test_cmd が run.sh でも枠は 1 回。
  外の run の盤面（ARTIFACTS_DIR）の印には触れない
- 枠待ちの見え方（SlotWaitShownCase）: 待つ前の 1 行、印の waiting → held → 消去、状態の表示の 1 行、herdr の集計
"""
import ast
import contextlib
import importlib.util
import io
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

import tiers

TESTS = pathlib.Path(__file__).resolve().parent
RUN_SH = TESTS / "run.sh"

FAKE_UV = """#!/bin/sh
echo "uv DWB=${PYTHONDONTWRITEBYTECODE-} cwd=$(pwd) $*" >> "$FAKE_LOG"
exit "${FAKE_UV_RC:-0}"
"""

# 本物と同じ約束（置き場は TESTSLOT_DIR。その下の slot-1 に自分の pid を置いてからコマンドを回す）の偽物。
# 本物は TESTSLOT_DIR が無ければ自分の既定を使うが、偽物は無ければ止まる（run.sh が渡し忘れたら赤にする）
FAKE_SLOT = """#!/bin/sh
d="${TESTSLOT_DIR:?}/slot-1"
mkdir -p "$d" && echo $$ > "$d/pid"
echo "slot N=${TESTSLOT_N-} $*" >> "$FAKE_LOG"
"$@"
rc=$?
rm -f "$d/pid"; rmdir "$d"
exit $rc
"""

UV_ARGS = "run --no-project --with pyyaml python3"


def collect_ids(suite):
    out = set()
    for t in suite:
        if isinstance(t, unittest.TestSuite):
            out |= collect_ids(t)
        else:
            out.add(t.id())
    return out


class TierListCase(unittest.TestCase):
    def test_modules_found(self):
        # 数え間違いで空の集合を見て緑にならないように
        self.assertGreaterEqual(len(tiers.modules()), 10)
        self.assertIn("test_tiers", tiers.modules())

    def test_every_module_classified_once(self):
        found = set(tiers.modules())
        self.assertEqual(sorted(found - tiers.FAST - tiers.HEAVY), [], "段の一覧に無いモジュール（tiers.py に足す）")
        self.assertEqual(sorted(tiers.FAST & tiers.HEAVY), [])
        self.assertEqual(sorted((tiers.FAST | tiers.HEAVY) - found), [], "段の一覧に在るのにファイルが無い")
        self.assertEqual(tiers.problems(), [])

    def test_glob_matches_discover(self):
        # modules() の glob が discover の届く範囲と同じ（tests/ の下に package が在ると discover は潜る）
        self.assertEqual([p for p in TESTS.rglob("__init__.py")], [])
        mods = {tid.split(".")[0] for tid in collect_ids(unittest.TestLoader().discover(str(TESTS), tiers.PATTERN))}
        self.assertEqual(mods - set(tiers.modules()), set())

    def test_problems_names_each_fault(self):
        with mock.patch.object(tiers, "modules", return_value=sorted(tiers.FAST | tiers.HEAVY | {"test_new"})):
            got = tiers.problems()
            self.assertEqual(len(got), 1)
            self.assertIn("test_new", got[0])
        with mock.patch.object(tiers, "HEAVY", tiers.HEAVY | {"test_tiers"}):
            self.assertIn("両方", " ".join(tiers.problems()))
        with mock.patch.object(tiers, "HEAVY", tiers.HEAVY | {"test_gone"}):
            got = " ".join(tiers.problems())
            self.assertIn("test_gone", got)
            self.assertIn("ファイルが無い", got)

    def test_loader_splits_discover_exactly(self):
        full = collect_ids(unittest.TestLoader().discover(str(TESTS), tiers.PATTERN))
        fast = collect_ids(tiers.TierLoader(tiers.FAST).discover(str(TESTS), tiers.PATTERN))
        heavy = collect_ids(tiers.TierLoader(tiers.HEAVY).discover(str(TESTS), tiers.PATTERN))
        self.assertTrue(fast and heavy)
        self.assertEqual(fast & heavy, set())
        self.assertEqual(fast | heavy, full)
        self.assertEqual({t.split(".")[0] for t in fast} - tiers.FAST, set())
        self.assertEqual({t.split(".")[0] for t in heavy} - tiers.HEAVY, set())

    def test_main_refuses_unknown_tier_and_bad_list(self):
        with mock.patch("sys.stderr"):
            self.assertEqual(tiers.main(["tiers.py", "slow"]), 2)
            self.assertEqual(tiers.main(["tiers.py"]), 2)
        with mock.patch.object(tiers, "modules", return_value=sorted(tiers.FAST | tiers.HEAVY | {"test_new"})), \
                mock.patch("sys.stderr") as err:
            self.assertEqual(tiers.main(["tiers.py", "fast"]), 2)
            self.assertIn("test_new", "".join(c.args[0] for c in err.write.call_args_list))


class ShardCase(unittest.TestCase):
    """組（WORKS_SHARD=<番号>/<組の数>）: 組の和はちょうど全部で重ならない。CI の works の job は組ごとに別の runner で回すので、
    ここが緩むと試験が黙ってどの組からも落ちる"""

    def test_union_is_every_module_for_each_total(self):
        mods = tiers.modules()
        for total in range(1, 9):
            groups = tiers.shard_of(mods, total)
            self.assertEqual(sorted(groups), list(range(total)))
            got = [m for g in groups.values() for m in g]
            self.assertEqual(sorted(got), sorted(mods), f"組の数 {total} の和が全部のモジュールでない")
            self.assertEqual(len(got), len(set(got)), f"組の数 {total} で 2 つの組に入るモジュールが在る")
            if total <= 4:
                self.assertTrue(all(groups.values()), f"組の数 {total} で空の組が在る")

    def test_same_table_every_time(self):
        self.assertEqual(tiers.shard_of(tiers.modules(), 4), tiers.shard_of(list(reversed(tiers.modules())), 4))

    def test_new_module_lands_in_some_shard(self):
        names = ["test_a", "test_b", "test_new"]
        with mock.patch.object(tiers, "weight", side_effect=lambda m: 1.0):
            groups = tiers.shard_of(names, 2)
        self.assertEqual(sorted(m for g in groups.values() for m in g), names)

    def test_loader_shards_split_discover_exactly(self):
        # 名前の和だけでなく、discover が拾う試験の id の和が全部と同じ（組ごとの読み込みは TierLoader）
        full = collect_ids(unittest.TestLoader().discover(str(TESTS), tiers.PATTERN))
        parts = [collect_ids(tiers.TierLoader(set(g)).discover(str(TESTS), tiers.PATTERN))
                 for g in tiers.shard_of(tiers.modules(), 4).values()]
        self.assertEqual(set().union(*parts), full)
        self.assertEqual(sum(len(p) for p in parts), len(set().union(*parts)))

    def test_env_form(self):
        self.assertIsNone(tiers.shard_env({}))
        self.assertIsNone(tiers.shard_env({"WORKS_SHARD": ""}))
        self.assertEqual(tiers.shard_env({"WORKS_SHARD": "3/4"}), (3, 4))
        for bad in ("4/4", "1", "a/4", "1/0", "-1/4", "1/4/2"):
            with self.assertRaises(ValueError, msg=bad):
                tiers.shard_env({"WORKS_SHARD": bad})

    def test_main_lists_the_shard_and_drops_the_env(self):
        out = io.StringIO()
        with mock.patch.dict(os.environ, {"WORKS_SHARD": "1/4"}), contextlib.redirect_stdout(out), mock.patch("sys.stderr"):
            self.assertEqual(tiers.main(["tiers.py", "list", "all"]), 0)
            self.assertNotIn("WORKS_SHARD", os.environ, "中の試験に組が継がれる")
        self.assertEqual(out.getvalue().split(), tiers.shard_of(tiers.modules(), 4)[1])
        out = io.StringIO()
        with mock.patch.dict(os.environ, {"WORKS_SHARD": "0/2"}), contextlib.redirect_stdout(out), mock.patch("sys.stderr"):
            self.assertEqual(tiers.main(["tiers.py", "list", "fast"]), 0)
        self.assertEqual(set(out.getvalue().split()), set(tiers.shard_of(tiers.modules(), 2)[0]) & tiers.FAST)

    def test_main_refuses_bad_shard(self):
        with mock.patch.dict(os.environ, {"WORKS_SHARD": "4/4"}), mock.patch("sys.stderr") as err:
            self.assertEqual(tiers.main(["tiers.py", "all"]), 2)
        self.assertIn("WORKS_SHARD", "".join(c.args[0] for c in err.write.call_args_list))


class TierPathsCase(unittest.TestCase):
    """dev/tdd-suite.sh（pytest で回す TDD の実行器）が段のファイルを引く口 `python3 tests/tiers.py paths <段>`"""

    def test_paths_are_the_tier_files_from_works_root(self):
        for tier, mods in tiers.TIERS.items():
            with self.subTest(tier):
                got = tiers.paths(tier)
                self.assertEqual(got, sorted(f"tests/{m}.py" for m in mods))
                for p in got:
                    self.assertTrue((TESTS.parent / p).is_file(), p)

    def test_main_paths_prints_one_per_line(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(tiers.main(["tiers.py", "paths", "fast"]), 0)
        self.assertEqual(out.getvalue().splitlines(), tiers.paths("fast"))

    def test_no_module_level_test_functions(self):
        """pytest は一番外の def test_* も試験として拾うが、unittest は拾わない（両方で数が揃うように、道具の関数は test_ で始めない）"""
        found = []
        for p in sorted(TESTS.glob(tiers.PATTERN)):
            for n in ast.parse(p.read_text(encoding="utf-8")).body:
                if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name.startswith("test"):
                    found.append(f"{p.name}:{n.name}")
        self.assertEqual(found, [])

    def test_main_paths_refuses_unknown_tier_and_bad_list(self):
        with mock.patch("sys.stderr"), contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertEqual(tiers.main(["tiers.py", "paths", "slow"]), 2)
            self.assertEqual(tiers.main(["tiers.py", "paths"]), 2)
        self.assertEqual(out.getvalue(), "")
        with mock.patch.object(tiers, "modules", return_value=sorted(tiers.FAST | tiers.HEAVY | {"test_new"})), \
                mock.patch("sys.stderr") as err, contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertEqual(tiers.main(["tiers.py", "paths", "fast"]), 2)
            self.assertIn("test_new", "".join(c.args[0] for c in err.write.call_args_list))
        self.assertEqual(out.getvalue(), "")


class RunShCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        tmp = pathlib.Path(self._tmp.name)
        bin_ = tmp / "bin"
        bin_.mkdir()
        (bin_ / "uv").write_text(FAKE_UV)
        (bin_ / "uv").chmod(0o755)
        self.slot = tmp / "ops" / "testslot.sh"
        self.slot.parent.mkdir()
        self.slot.write_text(FAKE_SLOT)
        self.slots = tmp / "slots"   # 台本の隣ではない所に置き、run.sh が TESTSLOT_DIR を見なければ外れるようにする
        self.log = tmp / "log"
        # 外の run の盤面（ARTIFACTS_DIR）と印（WORKS_SLOT_*）は継がない。継ぐと run の中で走った試験が外の run の印を書き換えて消す
        self.env = {k: v for k, v in os.environ.items()
                    if k not in ("WORKS_TESTS", "TESTSLOT_N", "TESTSLOT_DIR", "ARTIFACTS_DIR", "WORKS_SLOT_MARK", "WORKS_SLOT_NOTE")}
        self.env.update(PATH=f"{bin_}{os.pathsep}{os.environ.get('PATH', '')}", FAKE_LOG=str(self.log),
                        WORKS_TESTSLOT=str(self.slot), TESTSLOT_DIR=str(self.slots))

    def run_sh(self, *args, argv0=(), **env):
        e = dict(self.env)
        e.update(env)
        return subprocess.run([*argv0, "sh", str(RUN_SH), *args], env=e, capture_output=True, text=True, encoding="utf-8",
                              stdin=subprocess.DEVNULL)

    def calls(self):
        return self.log.read_text().splitlines() if self.log.exists() else []

    def assert_uv(self, line, tail):
        self.assertEqual(line, f"uv DWB=1 cwd={TESTS.parent} {UV_ARGS} {tail}")

    def test_unknown_value_exits_2_with_one_line(self):
        r = self.run_sh("-k", "x", WORKS_TESTS="slow")
        self.assertEqual(r.returncode, 2)
        self.assertEqual(len(r.stderr.splitlines()), 1, r.stderr)
        self.assertIn("slow", r.stderr)
        self.assertEqual(self.calls(), [])

    def test_fast_skips_slot_and_passes_args(self):
        r = self.run_sh("-k", "yaml", WORKS_TESTS="fast")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stderr, "")
        calls = self.calls()
        self.assertEqual(len(calls), 1, calls)
        self.assert_uv(calls[0], "tests/tiers.py fast -k yaml")

    def test_heavy_takes_slot_with_n4(self):
        r = self.run_sh("-k", "fix", WORKS_TESTS="heavy")
        self.assertEqual(r.returncode, 0, r.stderr)
        calls = self.calls()
        self.assertEqual(len(calls), 2, calls)
        self.assertTrue(calls[0].startswith(f"slot N=4 uv {UV_ARGS} tests/tiers.py heavy -k fix"), calls[0])
        self.assert_uv(calls[1], "tests/tiers.py heavy -k fix")

    def test_default_is_all_tier_through_slot(self):
        # 全部も段を選ぶ時と同じ入口（tiers.py）を通し、見送りの門（SkipGateRunner）に掛ける
        r = self.run_sh("-k", "x", TESTSLOT_N="9")
        self.assertEqual(r.returncode, 0, r.stderr)
        calls = self.calls()
        self.assertEqual(len(calls), 2, calls)
        self.assertTrue(calls[0].startswith("slot N=4 "), calls[0])   # 呼ぶ側の TESTSLOT_N に関わらず 4
        self.assert_uv(calls[1], "tests/tiers.py all -k x")

    def test_exit_code_passes_through(self):
        for tier in ("", "fast", "heavy"):
            with self.subTest(tier=tier):
                self.assertEqual(self.run_sh(WORKS_TESTS=tier, FAKE_UV_RC="7").returncode, 7)

    def test_missing_slot_script_runs_without_slot(self):
        r = self.run_sh(WORKS_TESTS="heavy", WORKS_TESTSLOT=str(self.slot.parent / "nope.sh"))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(len(r.stderr.splitlines()), 1, r.stderr)
        self.assertIn("nope.sh", r.stderr)
        calls = self.calls()
        self.assertEqual(len(calls), 1, calls)
        self.assert_uv(calls[0], "tests/tiers.py heavy")

    def test_unwritable_slot_dir_runs_all_tier_without_slot(self):
        geteuid = getattr(os, "geteuid", None)
        if geteuid is None or geteuid() == 0:
            self.skipTest("SKIP read-permission: root か geteuid の無い OS では書けない置き場を作れない")
        slots = self.slots
        slots.mkdir()
        slots.chmod(0o500)
        self.addCleanup(slots.chmod, 0o700)
        r = self.run_sh()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(len(r.stderr.splitlines()), 1, r.stderr)
        self.assertIn("書けない", r.stderr)
        calls = self.calls()
        self.assertEqual(len(calls), 1, calls)
        self.assert_uv(calls[0], "tests/tiers.py all")
        self.assertEqual(list(slots.iterdir()), [])   # 試しの跡を残さない

    def test_under_slot_holder_does_not_take_another(self):
        # 人が `bash testslot.sh sh works/tests/run.sh` と前に付けて打った形。2 枠目を待つと、枠が埋まった時に互いを待って止まる
        r = self.run_sh("-k", "x", argv0=("bash", str(self.slot)), WORKS_TESTS="heavy")
        self.assertEqual(r.returncode, 0, r.stderr)
        calls = self.calls()
        self.assertEqual(len(calls), 2, calls)
        self.assertTrue(calls[0].startswith("slot N="), calls[0])
        self.assert_uv(calls[1], "tests/tiers.py heavy -k x")
        self.assertFalse((self.slots / "slot-1").exists())
        self.assertEqual([x.name for x in self.slot.parent.iterdir()], ["testslot.sh"])   # 台本のフォルダには何も作らない

    def test_script_is_posix_sh(self):
        dash = shutil.which("dash")
        if dash is None:
            self.skipTest("SKIP dash: dash が無い")
        self.assertEqual(subprocess.run([dash, "-n", str(RUN_SH)], capture_output=True).returncode, 0)

    def test_archon_node_env_does_not_reach_tests(self):
        """線の試験の節（Archon の script の節）から起こすと、Archon は節ごとの ARCHON_NODE_EXECUTION（path に include の名）などを
        渡す。試験は同じプロセスで flow_adapter を読むので、継ぐと scope が付いて盤面の置き場がずれ、run の中でだけ赤くなる（dogfood 195g）"""
        (pathlib.Path(self._tmp.name) / "bin" / "uv").write_text(
            '#!/bin/sh\nenv | sed -n "s/^\\(ARCHON_[A-Za-z0-9_]*\\)=.*/\\1/p" >> "$FAKE_LOG"\n')
        r = self.run_sh(WORKS_TESTS="fast", ARCHON_NODE_EXECUTION='{"path":"testing__run"}',
                        ARCHON_CLI_COMMAND='["archon"]', ARCHON_HOME="/nonexistent")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.calls(), [])


BARE_ENVIRON = __import__("re").compile(r"(?<![\w.])dict\(os\.environ\b|os\.environ\.copy\(\)|\{\*\*os\.environ\b")


class HermeticCase(unittest.TestCase):
    """試験の子の環境と一時フォルダは、走らせた場（run の中の親が立てた名・macOS の /var→/private/var）に左右されない。
    外す名の一覧は試験の足場 tests/hermetic.py の 1 か所に置き、意図して継がせる名は child_env の overrides で名指しする"""

    def _hermetic(self):
        try:
            import hermetic
        except ImportError as e:
            self.fail(f"試験の足場 tests/hermetic.py が無い: {e}")
        return hermetic

    def test_no_bare_environ_copy_outside_hermetic(self):
        own = {"hermetic.py", pathlib.Path(__file__).name}
        found = [f"{p.name}:{i}" for p in sorted(TESTS.glob("*.py")) if p.name not in own
                 for i, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1) if BARE_ENVIRON.search(line)]
        self.assertEqual(found, [], "親の環境を丸ごと子へ渡す（hermetic.child_env を使う）")

    def test_hermetic_sh_drops_every_knob_the_dev_shells_read(self):
        """試験の入口が . で読む tests/hermetic.sh は、dev の殻が読む利用の旗（WORKS_USE_*・WORKS_DOGFOOD_*・WORKS_FEATURES_*・
        WORKS_DESIGN_*）を全部外す（外の run で立てた WORKS_USE_FEATURES_ON などが、既定を見る試験の子に継がれない）"""
        names = sorted({m for p in sorted((TESTS.parent / "dev").glob("*.sh"))
                        for m in re.findall(r"\$\{?(WORKS_(?:USE|DOGFOOD|FEATURES|DESIGN)_[A-Z0-9_]+)", p.read_text(encoding="utf-8"))})
        self.assertIn("WORKS_USE_FEATURES_ON", names)
        listed = set(re.findall(r"\bWORKS_[A-Z0-9_]+", (TESTS / "hermetic.sh").read_text(encoding="utf-8")))
        self.assertEqual([n for n in names if n not in listed], [], "tests/hermetic.sh の unset の一覧に足す")

    def test_child_env_drops_names_set_by_the_run(self):
        hermetic = self._hermetic()
        leaked = {"WORKS_DEV_ADAPTER": "x", "WORKS_DEV_CLAUDE_VERSION": "9.9.9", "CLAUDE_CODE_ENTRYPOINT": "cli",
                  "GRAPHLOOPS_ENGINE_CHILD": "1"}
        with mock.patch.dict(os.environ, leaked):
            env = hermetic.child_env()
        self.assertEqual(sorted(set(leaked) & set(env)), [])
        self.assertEqual(env.get("PATH"), os.environ.get("PATH"))

    def test_child_env_keeps_named_overrides(self):
        hermetic = self._hermetic()
        with mock.patch.dict(os.environ, {"WORKS_DEV_ADAPTER": "parent"}):
            env = hermetic.child_env(WORKS_DEV_ADAPTER="given", PYTHONDONTWRITEBYTECODE="1")
        self.assertEqual((env["WORKS_DEV_ADAPTER"], env["PYTHONDONTWRITEBYTECODE"]), ("given", "1"))

    def test_tmpdir_is_real_path(self):
        hermetic = self._hermetic()
        d = hermetic.tmpdir(self)
        self.assertEqual(pathlib.Path(d), pathlib.Path(os.path.realpath(d)))
        self.assertTrue(pathlib.Path(d).is_dir())

    def test_alias_is_same_place_or_skips(self):
        hermetic = self._hermetic()
        d = hermetic.tmpdir(self)
        with self.subTest("別名が無い綴りは skip"), self.assertRaises(unittest.SkipTest):
            hermetic.alias(self, "/nonexistent-top/x")
        with self.assertRaises(AssertionError):   # subTest の外では呼ばせない（skip が試験の残りを黙らせる）
            hermetic.alias(self, d)
        with self.subTest("別名は同じ場所"):
            pub = hermetic.alias(self, d)
            self.assertNotEqual(pub, str(d))
            self.assertEqual(os.path.realpath(pub), str(d))

    def test_fake_herdr_rejects_commands_real_herdr_lacks(self):
        # 偽の herdr は実物の CLI の形（pane の下の report-agent・release-agent）だけを受けて控え、最上位の形は実物と同じく
        # unknown command で rc=2 にする（誤った呼び出しを緑で通さない）
        hermetic = self._hermetic()
        fake_herdr = getattr(hermetic, "fake_herdr", None)
        self.assertIsNotNone(fake_herdr, "試験の足場 tests/hermetic.py に共通の偽の herdr（fake_herdr）が無い")
        bin_dir, log = fake_herdr(hermetic.tmpdir(self))
        herdr = str(pathlib.Path(bin_dir) / "herdr")
        for args in (["report-agent", "pane-7", "--source", "s", "--agent", "a", "--state", "working", "--seq", "1"],
                     ["release-agent", "pane-7", "--source", "s", "--agent", "a", "--seq", "2"]):
            with self.subTest(args=args[0]):
                r = subprocess.run([herdr, *args], capture_output=True, text=True, encoding="utf-8", env=hermetic.child_env())
                self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
                self.assertIn(f"unknown command: {args[0]}", r.stderr)
        self.assertFalse(pathlib.Path(log).exists(), "受けない形を控えた")
        for args in (["pane", "report-agent", "pane-7", "--source", "s", "--agent", "a", "--state", "working", "--seq", "3"],
                     ["pane", "release-agent", "pane-7", "--source", "s", "--agent", "a", "--seq", "4"]):
            r = subprocess.run([herdr, *args], capture_output=True, text=True, encoding="utf-8", env=hermetic.child_env())
            self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(pathlib.Path(log).read_text().splitlines(),
                         ["pane report-agent pane-7 --source s --agent a --state working --seq 3",
                          "pane release-agent pane-7 --source s --agent a --seq 4"])

    def test_failing_fake_herdr_keeps_the_accepted_forms(self):
        # 失敗させる偽の herdr（fail=True）も受ける形は同じ: 受ける形は控えてから server_not_running で rc=1、ほかは rc=2
        hermetic = self._hermetic()
        bin_dir, log = hermetic.fake_herdr(hermetic.tmpdir(self), fail=True)
        herdr = str(pathlib.Path(bin_dir) / "herdr")
        r = subprocess.run([herdr, "report-agent", "pane-7"], capture_output=True, text=True, encoding="utf-8",
                           env=hermetic.child_env())
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        self.assertFalse(pathlib.Path(log).exists(), "受けない形を控えた")
        r = subprocess.run([herdr, "pane", "release-agent", "pane-7", "--source", "s", "--agent", "a", "--seq", "5"],
                           capture_output=True, text=True, encoding="utf-8", env=hermetic.child_env())
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("server_not_running", r.stderr)
        self.assertEqual(pathlib.Path(log).read_text().splitlines(),
                         ["pane release-agent pane-7 --source s --agent a --seq 5"])


SKIP_CALLS = {"skipTest": 0, "skip": 0, "SkipTest": 0, "skipIf": 1, "skipUnless": 1}


def reason_head(node):
    """見送りの理由の式の頭の文字列（組み立てた理由は左端の定数。読めなければ None）"""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr) and node.values:
        return reason_head(node.values[0])
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        return reason_head(node.left)
    return None


# 門を試すために名前の無い見送りをわざと起こす見本（この中は見ない）
SKIP_FIXTURES = {("test_tiers.py", "skipping_suite"), ("test_tiers.py", "test_class_level_skip_is_counted")}


def walk_outside_fixtures(fname, tree):
    todo = [tree]
    while todo:
        node = todo.pop()
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and (fname, node.name) in SKIP_FIXTURES:
            continue
        yield node
        todo.extend(ast.iter_child_nodes(node))


class SkipNamesCase(unittest.TestCase):
    """works の見送りは root の約束『SKIP <能力>: <理由>』で書く（SKIP_ALLOW で名前を許せるように）"""

    def test_every_skip_reason_names_a_capability(self):
        bad = []
        seen = 0
        for f in sorted(TESTS.glob("*.py")):
            for node in walk_outside_fixtures(f.name, ast.parse(f.read_text(encoding="utf-8"))):
                if not isinstance(node, ast.Call):
                    continue
                fn = node.func
                name = fn.attr if isinstance(fn, ast.Attribute) else fn.id if isinstance(fn, ast.Name) else None
                if name not in SKIP_CALLS:
                    continue
                if name == "skip" and not (isinstance(fn, ast.Attribute) and isinstance(fn.value, ast.Name)
                                           and fn.value.id == "unittest"):
                    continue   # 盤面の skip など unittest の外の同じ名前
                seen += 1
                i = SKIP_CALLS[name]
                head = reason_head(node.args[i]) if len(node.args) > i else None
                if head is None or not tiers.SKIP_DECL.match(head):
                    bad.append(f"{f.name}:{node.lineno} {head!r}")
        self.assertGreater(seen, 0)   # 引き間違いで空を見て緑にならないように
        self.assertEqual(bad, [], "『SKIP <能力>: 』で始まらない見送りの理由")


def skipping_suite():
    class Skips(unittest.TestCase):
        def test_named(self):
            self.skipTest("SKIP dash: dash が無い")

        def test_other(self):
            self.skipTest("SKIP uv: uv が無い")

        def test_unnamed(self):
            self.skipTest("名前の無い見送り")

        def test_pass(self):
            pass

    return unittest.defaultTestLoader.loadTestsFromTestCase(Skips)


class SkipGateCase(unittest.TestCase):
    """全段の終わりの見送りの門（tiers.SkipGateRunner）: FAIL_ON_SKIP=1 のとき、SKIP_ALLOW に無い能力と名前の無い見送りを失敗に数える"""

    def run_gate(self, suite, **env):
        runner_cls = getattr(tiers, "SkipGateRunner", None)
        self.assertIsNotNone(runner_cls, "tiers に見送りの門 SkipGateRunner が無い")
        out = io.StringIO()
        clean = {k: v for k, v in os.environ.items() if k not in ("FAIL_ON_SKIP", "SKIP_ALLOW")}
        clean.update(env)
        with mock.patch.dict(os.environ, clean, clear=True):
            result = runner_cls(stream=out, verbosity=0).run(suite)
        return result, out.getvalue()

    def test_unnamed_skip_fails_when_fail_on_skip(self):
        result, out = self.run_gate(skipping_suite(), FAIL_ON_SKIP="1", SKIP_ALLOW="dash uv")
        self.assertFalse(result.wasSuccessful(), out)
        self.assertIn("名前の無い見送り", out)

    def test_skip_not_in_allow_fails_when_fail_on_skip(self):
        suite = unittest.TestSuite(t for t in skipping_suite() if not t.id().endswith("test_unnamed"))
        result, out = self.run_gate(suite, FAIL_ON_SKIP="1", SKIP_ALLOW="dash")
        self.assertFalse(result.wasSuccessful(), out)
        self.assertIn("SKIP uv", out)

    def test_allowed_skips_pass_and_are_listed(self):
        suite = unittest.TestSuite(t for t in skipping_suite() if not t.id().endswith("test_unnamed"))
        for allow in ("dash uv", "dash,uv"):
            with self.subTest(allow=allow):
                result, out = self.run_gate(suite, FAIL_ON_SKIP="1", SKIP_ALLOW=allow)
                self.assertTrue(result.wasSuccessful(), out)
                self.assertIn("SKIP dash", out)
                self.assertIn("SKIP uv", out)

    def test_without_fail_on_skip_lists_but_passes(self):
        result, out = self.run_gate(skipping_suite())
        self.assertTrue(result.wasSuccessful(), out)
        self.assertIn("名前の無い見送り", out)

    def test_class_level_skip_is_counted(self):
        class Whole(unittest.TestCase):
            @classmethod
            def setUpClass(cls):
                raise unittest.SkipTest("クラスごとの名前の無い見送り")

            def test_x(self):
                pass

        suite = unittest.defaultTestLoader.loadTestsFromTestCase(Whole)
        result, out = self.run_gate(unittest.TestSuite([suite]), FAIL_ON_SKIP="1", SKIP_ALLOW="dash")
        self.assertFalse(result.wasSuccessful(), out)

    def test_main_runs_tiers_through_gate_including_all(self):
        runner_cls = getattr(tiers, "SkipGateRunner", None)
        self.assertIsNotNone(runner_cls, "tiers に見送りの門 SkipGateRunner が無い")
        for tier in ("fast", "all"):
            with self.subTest(tier=tier), mock.patch.object(tiers.unittest, "main") as um, \
                    mock.patch.object(tiers.sys, "path", list(tiers.sys.path)):
                self.assertEqual(tiers.main(["tiers.py", tier, "-k", "x"]), 0)
                self.assertEqual(um.call_count, 1)
                self.assertIs(um.call_args.kwargs.get("testRunner"), runner_cls)


# Windows の os に無い POSIX のプロセスの API（Python の公式文書で Availability: Unix）
POSIX_ONLY = ("geteuid", "killpg", "setsid", "getpgid", "getsid")


@contextlib.contextmanager
def without_posix_process_api():
    """os から POSIX だけの API を外した間（Windows の os を模す）"""
    saved = {n: getattr(os, n) for n in POSIX_ONLY if hasattr(os, n)}
    for n in saved:
        delattr(os, n)
    try:
        yield
    finally:
        for n, f in saved.items():
            setattr(os, n, f)


def load_fresh(name):
    """tests/<name>.py を別の名前で読み込み直す（sys.modules の物を使わずに、モジュールの頭とクラスの定義を今の os で評価する）"""
    spec = importlib.util.spec_from_file_location(f"_portability_{name}", TESTS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class PortabilityCase(unittest.TestCase):
    """macOS／POSIX の前提が無い OS（Linux・Windows）で、works の試験が読み込みで落ちず、できない物は能力の名前で見送る。
    段の全部を 3 OS で回す前に、手元の macOS で os の API と /private/tmp の綴りを外して確かめる（読み込むだけで、木は起こさない）"""

    def test_modules_load_without_posix_process_api(self):
        bad = []
        with without_posix_process_api():
            for name in ("test_tiers", "test_tree_run", "test_adapter", "test_blk_tests_delta"):
                try:
                    load_fresh(name)
                except Exception as e:   # noqa: BLE001 — 読み込みの失敗を全部集めて名指す
                    bad.append(f"{name}: {type(e).__name__}: {e}")
        self.assertEqual(bad, [], "POSIX のプロセスの API が無いと読み込みで落ちる")

    def test_tree_run_cases_skip_as_process_group_without_killpg(self):
        with without_posix_process_api():
            cls = load_fresh("test_tree_run").TreeRunCase
            if getattr(cls, "__unittest_skip__", False):
                reason = cls.__unittest_skip_why__
            else:
                try:
                    cls.setUpClass()
                except unittest.SkipTest as e:
                    reason = str(e)
                else:
                    self.fail("os.killpg が無くても TreeRunCase が見送られない（木を起こして落ちる）")
        self.assertRegex(reason, r"^SKIP process-group: ")

    def test_cwd_in_claude_tmp_does_not_skip_unnamed_without_private_tmp(self):
        real = tempfile.mkdtemp

        def mkdtemp(*args, **kwargs):
            d = kwargs.get("dir", args[2] if len(args) > 2 else None)
            if d is not None and str(d).startswith("/private/"):
                raise FileNotFoundError(2, "No such file or directory", str(d))
            return real(*args, **kwargs)

        test_dev = load_fresh("test_dev")
        result = unittest.TestResult()
        with mock.patch.object(tempfile, "mkdtemp", mkdtemp):
            test_dev.TestDevShell("test_archon_sh_refuses_cwd_in_claude_tmp").run(result)
        self.assertEqual((result.errors, result.failures), ([], []))
        for _, reason in result.skipped:
            self.assertRegex(reason, tiers.SKIP_DECL)


# 試験を走らせる run（dogfood.sh・use.sh・包み）が export する変数。試験の子に届くと、既定の振る舞いを見る試験が外の run に左右される
LEAKY_ENV = {"WORKS_DEV_ADAPTER": "1", "WORKS_CONTEXT7_MCP": "on", "WORKS_CONTEXT7": "off"}

FAKE_UV_ENV = """#!/bin/sh
for n in WORKS_DEV_ADAPTER WORKS_CONTEXT7_MCP WORKS_CONTEXT7; do
  eval "v=\\${$n-(unset)}"
  echo "$n=$v" >> "$FAKE_ENV_LOG"
done
"""


class RunEnvLeakCase(unittest.TestCase):
    """試験の入口（run.sh の全部・段、TDD の実行器 dev/tdd-suite.sh）は、走らせる run の env を試験の子に継がせない。
    置き場と偽の枠の台本は RunShCase と同じ（RunShCase の試験を継がないように、setUp と run_sh だけを借りる）"""
    run_sh = RunShCase.run_sh

    def setUp(self):
        RunShCase.setUp(self)
        uv = pathlib.Path(self.env["PATH"].split(os.pathsep)[0]) / "uv"
        uv.write_text(FAKE_UV_ENV)
        self.env_log = pathlib.Path(self._tmp.name) / "env-log"
        self.env.update(FAKE_ENV_LOG=str(self.env_log), **LEAKY_ENV)

    def seen(self):
        return set(self.env_log.read_text().splitlines())

    def assert_not_leaked(self):
        want = {f"{n}=(unset)" for n in LEAKY_ENV}
        self.assertEqual(self.seen(), want)

    def test_run_sh_does_not_pass_run_env_to_tests(self):
        for tier in ("", "fast", "heavy"):
            with self.subTest(tier=tier or "全部"):
                if self.env_log.exists():
                    self.env_log.unlink()
                r = self.run_sh(WORKS_TESTS=tier)
                self.assertEqual(r.returncode, 0, r.stderr)
                self.assert_not_leaked()

    def test_tdd_suite_does_not_pass_run_env_to_tests(self):
        out = pathlib.Path(self._tmp.name) / "junit.xml"
        r = subprocess.run(["sh", str(TESTS.parent / "dev" / "tdd-suite.sh"), str(out)], env=self.env, capture_output=True,
                           text=True, encoding="utf-8", stdin=subprocess.DEVNULL)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assert_not_leaked()


class RunSlotCase(unittest.TestCase):
    """run の中で試験を起こす 3 つの口（engine の既定の runner・任せ先の test_cmd・blk-tests の _run）も、run.sh と同じ
    約束で枠の台本を通る。test_cmd が run.sh の時は、口が取った枠の下で run.sh が取り直さない（枠は 1 回だけ）。
    偽の uv・枠の台本・置き場は RunShCase の物を使い回す。外の run の中で走った形にし、外の盤面の印に触れないことも見る"""

    calls = RunShCase.calls

    def setUp(self):
        outer = tempfile.TemporaryDirectory()
        self.addCleanup(outer.cleanup)
        mark = pathlib.Path(outer.name) / "board" / "testslot.json"
        mark.parent.mkdir()
        mark.write_text('{"state": "held"}')
        self.addCleanup(lambda: self.assertEqual(mark.read_text() if mark.exists() else None, '{"state": "held"}',
                                                 "外の run の印を書き換えた・消した"))
        with mock.patch.dict(os.environ, ARTIFACTS_DIR=outer.name):
            RunShCase.setUp(self)
        core = str(TESTS.parent / ".shared" / "core")
        if core not in sys.path:
            sys.path.insert(0, core)
        self.tmp = pathlib.Path(self._tmp.name)
        patched = mock.patch.dict(os.environ, self.env, clear=True)
        patched.start()
        self.addCleanup(patched.stop)

    def assert_one_slot(self, needle):
        slots = [c for c in self.calls() if c.startswith("slot ")]
        self.assertEqual(len(slots), 1, self.calls())
        self.assertTrue(slots[0].startswith("slot N=4 "), slots[0])
        self.assertIn(needle, slots[0])

    def test_tree_runner_step_takes_slot(self):
        from board import tree_runner
        runs = tree_runner([{"name": "suite", "argv": ["sh", "-c", "echo ran-step"]}], self.tmp, self.tmp / "logs")
        self.assertEqual(runs[0]["exit"], 0, runs)
        self.assertEqual(runs[0]["argv"], ["sh", "-c", "echo ran-step"])   # 記録は包む前の形
        self.assert_one_slot("echo ran-step")

    def test_local_checks_material_takes_slot(self):
        from entry import local_checks_material
        got = local_checks_material(self.tmp, "echo ran-cmd", self.tmp / "lc.log")
        self.assertEqual(got["material"]["status"], "clean", got)
        self.assert_one_slot("echo ran-cmd")

    def test_blk_tests_run_takes_slot(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location("blk_tests_run_tests_slot",
                                                      TESTS.parent / "blk-tests" / "scripts" / "run_tests.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        with open(self.tmp / "t.log", "wb") as f:
            self.assertEqual(mod._run(["sh", "-c", "echo ran-blk"], f, cwd=str(self.tmp)), 0)
        self.assert_one_slot("echo ran-blk")

    def test_test_cmd_run_sh_takes_slot_once(self):
        from board import tree_runner
        os.environ["WORKS_TESTS"] = "heavy"
        runs = tree_runner([{"name": "test_cmd", "argv": ["sh", str(RUN_SH), "-k", "x"]}], self.tmp, self.tmp / "logs")
        self.assertEqual(runs[0]["exit"], 0, runs)
        self.assert_one_slot("run.sh -k x")   # 枠を取るのは口で、中の run.sh は祖先の枠を見て取り直さない
        self.assertIn(f"uv DWB=1 cwd={TESTS.parent} {UV_ARGS} tests/tiers.py heavy -k x", self.calls())


# 枠の台本が走り出した時に、待ちの印（WORKS_SLOT_MARK）の中身を記録へ写す偽物（本物は枠が空くまでここで待つ）
MARK_SLOT = """#!/bin/sh
{ cat "${WORKS_SLOT_MARK:?}"; echo; } >> "$FAKE_LOG"
""" + FAKE_SLOT.split("\n", 1)[1]

# 枠の中で走るコマンドの時点の印の中身を記録へ写す
MARK_CMD = """#!/bin/sh
{ cat "${1:?}"; echo; } >> "$FAKE_LOG"
"""


class SlotWaitShownCase(unittest.TestCase):
    """枠が空くのを期限なしで待つ間、待っていることが見える: 枠の口は待つ前に標準エラーへ 1 行出し、WORKS_SLOT_MARK（run の中では
    盤面の testslot.json）に待ち（waiting）→ 枠の中（held）を書き、終われば消す。状態の表示（works_dev_show_run）は印から
    『試験の枠: 待っている（N 分…）』の 1 行を出し、herdr の集計は枠待ちの run を走る run のうちに数える（blocked にしない）"""

    calls = RunShCase.calls

    def setUp(self):
        RunShCase.setUp(self)
        self.tmp = pathlib.Path(self._tmp.name)
        self.slot.write_text(MARK_SLOT)
        self.mark_cmd = self.tmp / "mark-cmd.sh"
        self.mark_cmd.write_text(MARK_CMD)

    def marks(self):
        return [json.loads(c) for c in self.calls() if c.startswith("{")]

    def test_run_sh_says_waiting_before_slot(self):
        e = dict(self.env, WORKS_TESTS="heavy", WORKS_SLOT_MARK=str(self.tmp / "m.json"))
        r = subprocess.run(["sh", str(RUN_SH)], env=e, capture_output=True, text=True, encoding="utf-8",
                           stdin=subprocess.DEVNULL)
        self.assertEqual(r.returncode, 0, r.stderr)
        lines = r.stderr.splitlines()
        self.assertEqual(len(lines), 1, r.stderr)
        self.assertIn("枠を待つ", lines[0])
        self.assertIn(str(self.slots), lines[0])

    def test_mark_goes_waiting_then_held_then_is_cleared(self):
        core = str(TESTS.parent / ".shared" / "core")
        if core not in sys.path:
            sys.path.insert(0, core)
        from board import tree_runner
        art = self.tmp / "art"
        mark = art / "board" / "testslot.json"
        with mock.patch.dict(os.environ, dict(self.env, ARTIFACTS_DIR=str(art)), clear=True):
            runs = tree_runner([{"name": "suite", "argv": ["sh", str(self.mark_cmd), str(mark)]}], self.tmp,
                               self.tmp / "logs")
        self.assertEqual(runs[0]["exit"], 0, runs)
        got = self.marks()
        self.assertEqual([m.get("state") for m in got], ["waiting", "held"], self.calls())
        self.assertEqual(got[0].get("slots"), str(self.slots))
        self.assertIsInstance(got[0].get("pid"), int)
        self.assertIsInstance(got[0].get("since"), (int, float))
        self.assertFalse(mark.exists(), "終わった段の印が残っている")

    def show(self, row):
        fake = self.tmp / "archon.sh"
        fake.write_text("#!/bin/sh\necho '{\"events\": []}'\n")
        env = dict(os.environ, WORKS_DEV_HOME=str(self.tmp), WORKS_DEV_MODEL="opus", CLAUDE_BIN_PATH="/x/claude",
                   WORKS_RUN_ROW=json.dumps(row))
        dev = TESTS.parent / "dev"
        return subprocess.run(["sh", "-c", f'DEV_DIR="{dev}"; . "{dev}/lib.sh" && works_dev_show_run t "{fake}" "{self.tmp}"'],
                              capture_output=True, text=True, encoding="utf-8", env=env)

    def put_mark(self, rid, **doc):
        board = self.tmp / "out" / "artifacts" / "runs" / rid / "board"
        board.mkdir(parents=True, exist_ok=True)
        (board / "testslot.json").write_text(json.dumps(doc))

    def test_show_run_prints_slot_wait(self):
        import time
        row = {"id": "r1", "status": "running", "output_root": str(self.tmp / "out"), "working_path": "/wt/r1"}
        r = self.show(row)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertNotIn("試験の枠", r.stdout)   # 印が無ければ出さない
        self.put_mark("r1", state="waiting", since=time.time() - 180, slots=str(self.slots), pid=os.getpid())
        r = self.show(row)
        self.assertEqual(r.returncode, 0, r.stderr)
        line = [x for x in r.stdout.splitlines() if x.startswith("試験の枠:")]
        self.assertEqual(len(line), 1, r.stdout)
        self.assertIn("待っている（3 分", line[0])
        self.assertIn(str(self.slots), line[0])

    def test_herdr_counts_slot_wait_as_working(self):
        import time
        runs_dir = self.tmp / "runs"
        runs_dir.mkdir()
        (runs_dir / "r1.json").write_text(json.dumps({"run_id": "r1", "herdr_pane": "pane-7"}))
        (runs_dir / "r2.json").write_text(json.dumps({"run_id": "r2", "herdr_pane": "pane-7"}))
        listed = {"runs": [{"id": "r1", "status": "running", "output_root": str(self.tmp / "out")},
                           {"id": "r2", "status": "running", "output_root": str(self.tmp / "out")}]}
        fake = self.tmp / "archon.sh"
        fake.write_text(f"#!/bin/sh\necho '{json.dumps(listed)}'\n")
        herdr_bin, herdr_log = importlib.import_module("hermetic").fake_herdr(self.tmp)
        self.put_mark("r1", state="waiting", since=time.time() - 60, slots=str(self.slots), pid=os.getpid())
        dev = TESTS.parent / "dev"
        # lib.sh は . で読まれ自分の場所を知れないので、控えを読む部品 launch.py の dir を殻と同じく DEV_DIR で渡す
        env = dict(os.environ, PATH=f"{herdr_bin}{os.pathsep}{os.environ.get('PATH', '')}", HERDR_ENV="1",
                   HERDR_PANE_ID="pane-7", DEV_DIR=str(dev))
        r = subprocess.run(["sh", "-c", f'. "{dev}/lib.sh" && works_dev_herdr_sync "{fake}" "{runs_dir}"'],
                           capture_output=True, text=True, encoding="utf-8", env=env)
        self.assertEqual(r.returncode, 0, r.stderr)
        calls = herdr_log.read_text().splitlines() if herdr_log.exists() else []
        reports = [c for c in calls if c.startswith("pane report-agent")]
        self.assertEqual(len(reports), 1, calls)
        self.assertIn("--state working", reports[0])
        self.assertIn("走る 2（うち枠待ち 1）", reports[0])


if __name__ == "__main__":
    unittest.main()
