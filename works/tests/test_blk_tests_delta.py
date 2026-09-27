"""ブロック blk-tests（テストのコマンド）と blk-delta（修正差分の審査）の検査。

- YAML に書いた審査役の返答の型が、受け付けの規則が前提にする型（graph の p3.delta_review）と同じか（設計書 5.4 節）
- blk-tests の節 run のスクリプト（scripts/run_tests.py）を、Archon を通さずに環境変数だけ与えて走らせ、緑も赤も ok: true で出るか。
  止められたらテストのコマンドが起こした孫まで止まるか（.shared/core/tree_run.py）
- blk-delta の cut・collect のスクリプトを、使い捨ての対象リポジトリで起こして盤面と出口を見る
- 作業ツリーの写し（snapshot_tree）が、未追跡のフォルダ（入れ子の git リポジトリ）で落ちないか
筋書き（fixtures/*.stubs.yaml）は dev/check.sh が Archon で回す。
"""
import importlib.util
import io
import json
import os
import pathlib
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

import yaml

ROOT = pathlib.Path(__file__).resolve().parents[1]
CORE = ROOT / ".shared" / "core"
REPLIES = pathlib.Path(__file__).resolve().parent / "replies"
SEED = ROOT / "dev" / "target-seed"
sys.path.insert(0, str(CORE))

from accept import check_delta, role_schema, snapshot_tree  # noqa: E402
from engine.schema import validate_schema  # noqa: E402

GIT_ID = ["-c", "user.email=t@t", "-c", "user.name=t", "-c", "commit.gpgsign=false", "-c", "core.hooksPath=/dev/null"]


def load(name):
    return json.loads((REPLIES / f"{name}.json").read_text(encoding="utf-8"))


def workflow(blk):
    return yaml.safe_load((ROOT / blk / f"{blk}.yaml").read_text(encoding="utf-8"))


def find_node(nodes, nid):
    """節の一覧から id の節を探す（loop_group の中も辿る）"""
    for n in nodes:
        if n.get("id") == nid:
            return n
        inner = (n.get("loop_group") or {}).get("nodes") or []
        hit = find_node(inner, nid) if inner else None
        if hit:
            return hit
    return None


def git(repo, *args):
    return subprocess.run(["git", *GIT_ID, "-C", str(repo), *args], capture_output=True, text=True, check=True).stdout.strip()


def load_run_tests():
    """blk-tests の節のスクリプトを module として読む（main は __main__ の時だけ走る）。読むたびに新しく読む"""
    spec = importlib.util.spec_from_file_location("blk_tests_run_tests", ROOT / "blk-tests" / "scripts" / "run_tests.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class RepoCase(unittest.TestCase):
    """dev/target-seed/ を写した使い捨ての対象リポジトリと、run の成果物の置き場"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        tmp = pathlib.Path(self._tmp.name)
        self.repo = tmp / "repo"
        shutil.copytree(SEED, self.repo)
        git(self.repo, "init", "-q")
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-q", "-m", "seed")
        self.base = git(self.repo, "rev-parse", "HEAD")
        self.artifacts = tmp / "artifacts"
        self.artifacts.mkdir()
        self.board = self.artifacts / "board"

    def tearDown(self):
        self._tmp.cleanup()

    def run_script(self, blk, name, **inputs):
        env = {k: v for k, v in os.environ.items() if not k.startswith("INPUTS_")}
        env.update({f"INPUTS_{k.upper()}": v for k, v in inputs.items()})
        env["ARTIFACTS_DIR"] = str(self.artifacts)
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        return subprocess.run([sys.executable, str(ROOT / blk / "scripts" / f"{name}.py")], cwd=str(self.repo),
                              env=env, capture_output=True, text=True, timeout=120)


# ---------------------------------------------------------------- blk-delta の型
class TestDeltaSchema(unittest.TestCase):
    def test_delta_output_format_matches_role_schema(self):
        review = find_node(workflow("blk-delta")["nodes"], "review")
        self.assertEqual(review["output_format"], role_schema("p3.delta_review"))

    def test_delta_ok_sample_passes_yaml_output_format(self):
        review = find_node(workflow("blk-delta")["nodes"], "review")
        self.assertEqual(validate_schema(load("delta_ok"), review["output_format"]), [])

    def test_delta_bad_cite_sample_passes_yaml_output_format(self):
        # 悪い見本は型では通り、受け付け（cite の字列）でだけ拒まれる——筋書き bad-cite が輪で落ちる理由
        review = find_node(workflow("blk-delta")["nodes"], "review")
        self.assertEqual(validate_schema(load("delta_bad_cite"), review["output_format"]), [])

    def test_delta_prompt_asks_for_empty_checks(self):
        # 1 本目は修正役が「塞いだ」と言う穴を持たないので、checks の行は全部拒まれる
        body = (ROOT / "blk-delta" / "commands" / "delta-review.md").read_text(encoding="utf-8")
        self.assertIn("checks: []", body)
        self.assertNotIn("{{", body)

    def test_delta_prompt_reads_block_outputs(self):
        # Ruling R16: 指示書の本文は同じブロックの節の出力を直に読む（include が節の名を付け替える）。
        # 宣言していない $INPUTS.<名> は Archon 0.11.1 の include が読み込みで拒むので、節の with: で束ねない
        body = (ROOT / "blk-delta" / "commands" / "delta-review.md").read_text(encoding="utf-8")
        refs = re.findall(r"\$[A-Za-z_][A-Za-z0-9_.-]*", body)
        self.assertEqual(sorted(set(refs)), ["$LOOP_PREV.review-accept.output.reason", "$cut.output.diff_file",
                                             "$cut.output.files"])
        review = find_node(workflow("blk-delta")["nodes"], "review")
        self.assertNotIn("with", review)

    def test_delta_loop(self):
        # 輪の中の節の id はライン全体で一意にする（模擬実行は輪の中の節を名前空間なしの id で stub に引く）
        loop = find_node(workflow("blk-delta")["nodes"], "delta-loop")["loop_group"]
        self.assertEqual([n["id"] for n in loop["nodes"]], ["review", "review-accept"])
        self.assertEqual(loop["until_bash"], "test $review-accept.output.ok = true")

    def test_delta_review_sandbox(self):
        # Ruling R12: Bash を持たない役でも、サンドボックスの外へ出る道を閉じる
        review = find_node(workflow("blk-delta")["nodes"], "review")
        self.assertEqual(review["sandbox"], {"enabled": True, "allowUnsandboxedCommands": False})


# ---------------------------------------------------------------- blk-tests
class TestTestsBlock(RepoCase):
    def cmd_env(self, cmd, mode=None):
        # Archon の口と同じ: 節の with: が INPUTS_CMD（と INPUTS_MODE）に、盤面の置き場が ARTIFACTS_DIR に届く。
        # mode=None は INPUTS_MODE を渡さない（線 C の mutgate の include の形）。
        # PYTHONDONTWRITEBYTECODE は外す（スクリプトがテストのコマンドに立てるかを見るため）
        env = {k: v for k, v in os.environ.items() if not k.startswith("INPUTS_") and k != "PYTHONDONTWRITEBYTECODE"}
        env.update(INPUTS_CMD=cmd, ARTIFACTS_DIR=str(self.artifacts))
        if mode is not None:
            env["INPUTS_MODE"] = mode
        return env

    def run_tests(self, cmd, rc=0, mode=None):
        node = find_node(workflow("blk-tests")["nodes"], "run")
        r = subprocess.run([sys.executable, str(ROOT / "blk-tests" / "scripts" / "run_tests.py")], cwd=str(self.repo),
                           env=self.cmd_env(cmd, mode), capture_output=True, text=True, timeout=120)
        if rc:
            self.assertEqual(r.returncode, rc, r.stderr)
            self.assertEqual(r.stdout, "")
            return None
        self.assertEqual(r.returncode, 0, r.stderr)
        out = json.loads(r.stdout)
        self.assertEqual(validate_schema(out, node["output_format"]), [])
        return out

    def test_run_node_contract(self):
        wf = workflow("blk-tests")
        self.assertEqual(wf["returns"], "run")
        self.assertEqual(wf["outcome_field"], "ok")
        self.assertIn("cmd", wf["inputs"])
        node = find_node(wf["nodes"], "run")
        # 木ごと止める殻を pack の中から引くので、パスを持たない bash の節ではなく名前付きの script の節
        self.assertEqual((node.get("script"), node.get("runtime")), ("run_tests", "uv"))
        self.assertNotIn("bash", node)
        self.assertEqual(node["with"], {"cmd": "$INPUTS.cmd"})
        self.assertEqual(sorted(node["output_format"]["required"]), ["green", "log", "ok"])

    def test_green_command(self):
        out = self.run_tests("python3 -c 'print(\"走った\")' && test -f stats.py")   # cwd は対象リポジトリ
        self.assertEqual(out, {"ok": True, "green": True, "log": str(self.board / "tests.log")})
        self.assertIn("走った", (self.board / "tests.log").read_text(encoding="utf-8"))

    def test_command_runs_in_bash(self):
        # 入口の説明のとおり bash が 1 行を走らせる（sh に無い [[ ]] が通る）
        out = self.run_tests("[[ -f stats.py ]]")
        self.assertEqual(out["green"], True)

    def test_empty_command_fails_the_node(self):
        # 何も走らせずに緑と言わない（空白だけも空と同じ）
        for cmd in ("", "  \n"):
            with self.subTest(cmd=cmd):
                self.run_tests(cmd, rc=1)
                self.assertFalse((self.board / "tests.log").exists())

    def test_plain_mode_is_mutgate_contract(self):
        # 線 C の mutgate は `include: blk-tests`・`with: {cmd}` だけで使う（盤面なし・INPUTS_MODE なし）。既定の形 plain は
        # 1 本目のまま: 盤面を作らず（state.json が無い）、ログは <ARTIFACTS_DIR>/board/tests.log（線 C の筋書きの log の形）、
        # 出口の鍵は ok・green・log だけ（裁定 TA4・審査 I1）。INPUTS_MODE に plain を明示しても、空でも同じ
        for mode in (None, "plain", ""):
            with self.subTest(mode=mode):
                shutil.rmtree(self.board, ignore_errors=True)
                out = self.run_tests("test -f stats.py", mode=mode)
                self.assertEqual(out, {"ok": True, "green": True, "log": str(self.artifacts / "board" / "tests.log")})
                self.assertEqual(sorted(p.name for p in self.board.iterdir()), ["tests.log"])
                self.assertFalse((self.board / "state.json").exists())
                out = self.run_tests("exit 1", mode=mode)
                self.assertEqual(set(out), {"ok", "green", "log"})
                self.assertEqual((out["ok"], out["green"]), (True, False))

    def test_plain_mode_empty_cmd_fails(self):
        # plain で cmd が空なら 1 本目と同じく節を落とす（空の cmd を許すのは mid・final だけ）
        for mode in (None, "plain"):
            with self.subTest(mode=mode):
                self.run_tests(" ", rc=1, mode=mode)
                self.assertFalse(self.board.exists())

    def test_unknown_mode_refused(self):
        # 知らない形は回す側の配線の誤り（終了コード 2）。盤面もログも作らない
        self.run_tests("true", rc=2, mode="middle")
        self.assertFalse(self.board.exists())

    def test_inputs_constant(self):
        # 裁定 TA16: 読む INPUTS_* の名前の組を定数に持つ（Task 17 の試験が YAML の with: の鍵と突き合わせる）
        self.assertEqual(load_run_tests().INPUTS, ("INPUTS_CMD", "INPUTS_MODE"))

    def test_tests_leave_no_bytecode(self):
        # 種の .gitignore が無くても、テストが作業ツリーに __pycache__ を作らない（修正の差分に紛れ込まない）
        (self.repo / ".gitignore").unlink()
        out = self.run_tests("python3 -m unittest -q test_stats")
        self.assertEqual((out["ok"], out["green"]), (True, False))   # 種はバグ入りで赤
        self.assertEqual(list(self.repo.rglob("__pycache__")), [])
        self.assertEqual(list(ROOT.rglob("__pycache__")), [])         # pack の中にも作らない

    def test_red_command_is_still_ok(self):
        # 赤を人の関所に見せるのがこの段の仕事なので、赤でも節は通る。信号で死んだテストも赤
        out = self.run_tests("echo 赤 >&2; exit 3")
        self.assertEqual((out["ok"], out["green"]), (True, False))
        self.assertIn("赤", (self.board / "tests.log").read_text(encoding="utf-8"))
        out = self.run_tests("kill -SEGV $$")
        self.assertEqual((out["ok"], out["green"]), (True, False))

    def uv_run_tests(self, **extra_env):
        """Archon と同じ形（`uv run <パス>`、cwd は対象リポジトリ。Archon 0.11.1 の script の節）で節のスクリプトを走らせ、
        テストのコマンドから見えた python3・VIRTUAL_ENV・UV_RUN_RECURSION_DEPTH・UV_NO_CONFIG と、uv の外の bash から見えた
        python3 を返す。extra_env は uv run に渡す環境に足す（Archon の環境に利用者が立てた物の代わり）。
        外の環境は uv の外の姿にする（このテスト自身が run.sh の uv run の中で走るので、uv が足した物を外して PATH を決め打つ）"""
        uv = shutil.which("uv")
        self.assertTrue(uv, "uv が無い")
        cmd = ('echo "PY=$(command -v python3)"; echo "VENV=${VIRTUAL_ENV:-}"; echo "DEPTH=${UV_RUN_RECURSION_DEPTH:-}"; '
               'echo "NOCONF=${UV_NO_CONFIG:-}"')
        env = {k: v for k, v in self.cmd_env(cmd).items()
               if k not in ("VIRTUAL_ENV", "UV", "UV_RUN_RECURSION_DEPTH", "UV_NO_CONFIG")}
        env.update(PATH=f"{os.path.dirname(uv)}:/usr/bin:/bin", PYTHONDONTWRITEBYTECODE="1", **extra_env)   # Archon が立てる
        outside = subprocess.run(["bash", "-c", "command -v python3"], env=env, capture_output=True, text=True).stdout.strip()
        r = subprocess.run([uv, "run", str(ROOT / "blk-tests" / "scripts" / "run_tests.py")], cwd=str(self.repo), env=env,
                           capture_output=True, text=True, timeout=300)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(json.loads(r.stdout)["green"], True)
        seen = dict(line.split("=", 1) for line in (self.board / "tests.log").read_text().splitlines())
        return seen, outside

    def test_command_sees_outside_python_not_uvs(self):
        # 節は uv run の中で走るが、テストのコマンドは uv が PATH の頭に足した python を掴まない（掴むと偽の赤になる）
        seen, outside = self.uv_run_tests()
        self.assertTrue(outside)
        self.assertEqual(seen, {"PY": outside, "VENV": "", "DEPTH": "", "NOCONF": ""})

    def test_command_does_not_inherit_target_project_venv(self):
        # 対象が pyproject.toml を持っても、節のスクリプトは PEP 723 の塊で対象の .venv を使わない（test_script_headers）。
        # 塊が外れて対象の .venv で起きた回にも、テストのコマンドには uv の VIRTUAL_ENV を渡さない
        (self.repo / "pyproject.toml").write_text('[project]\nname = "seed"\nversion = "0"\nrequires-python = ">=3.9"\n')
        seen, outside = self.uv_run_tests()
        self.assertEqual(seen, {"PY": outside, "VENV": "", "DEPTH": "", "NOCONF": ""})

    def test_command_reads_target_uv_config(self):
        # 利用者が Archon の環境に UV_NO_CONFIG=1 を立てても、テストのコマンドには渡さない。渡すと対象の `uv run pytest` が
        # 対象の [tool.uv]（私的な index など）を読まずに公開の PyPI から解決する（偽の赤と依存の取り違えの口）
        seen, outside = self.uv_run_tests(UV_NO_CONFIG="1")
        self.assertEqual(seen, {"PY": outside, "VENV": "", "DEPTH": "", "NOCONF": ""})
        # uv run の外で起こされても外す
        with mock.patch.dict(os.environ, UV_NO_CONFIG="1"):
            out = self.run_tests('test -z "${UV_NO_CONFIG+x}"')
        self.assertEqual((out["ok"], out["green"]), (True, True))

    def test_stop_stops_the_test_tree(self):
        # run を止めた（節のスクリプトが SIGTERM を受けた）ら、テストが背景に起こした孫まで止まり、後から作業ツリーに書かない
        pidf, marker = self.artifacts / "pgid", self.repo / "late.txt"
        cmd = f"echo $$ > {pidf}; sleep 300 & (sleep 3; echo late > {marker}) & wait"
        p = subprocess.Popen([sys.executable, str(ROOT / "blk-tests" / "scripts" / "run_tests.py")], cwd=str(self.repo),
                             env=self.cmd_env(cmd), stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                             stderr=subprocess.PIPE, text=True)
        try:
            end = time.monotonic() + 10
            while not (pidf.exists() and pidf.read_text().strip()) and time.monotonic() < end:
                time.sleep(0.05)
            pgid = int(pidf.read_text())
            p.send_signal(signal.SIGTERM)
            out, err = p.communicate(timeout=10)
            self.assertEqual((p.returncode, out), (128 + signal.SIGTERM, ""))   # 止められた回は出口を出さない
            self.assertIn("止められた", err)
            end = time.monotonic() + 2
            while time.monotonic() < end:
                try:
                    os.killpg(pgid, 0)
                except ProcessLookupError:
                    break
                time.sleep(0.05)
            else:
                self.fail("テストの孫が残った")
            time.sleep(4)
            self.assertFalse(marker.exists(), "止めた後にテストの孫が書いた")
        finally:   # 落ちた回も、このテストが起こした物だけを片付ける
            if p.poll() is None:
                p.kill()
                p.wait()
            try:
                os.killpg(int(pidf.read_text()), signal.SIGKILL)
            except (OSError, ValueError):
                pass



# ---------------------------------------------------------------- blk-tests の明示の形 mid・final（仕様 3.5・裁定 TA4・TA5）
# 盤面は盤面の層の試験の道具（手本の盤面を p4.ci の手の前に戻す。読むだけ・import するだけ）で組み、節のスクリプトの main を
# Archon と同じ環境変数で同じプロセスの中で呼ぶ。盤面は 1 本目のラインの本物の表で組み、本物の entry（Task 3 の open_board）で開く。
# 偽物は Task 7 の run_ci・CiRefused だけ（この枝にまだ無い）: run_ci は Task 7 の約束（relaunch は 1 度だけ呼び直す・任せ先は
# 起こした印を置いてから cmd を走らせた素材を done・why だけの返りは CiRefused）をなぞる。run_ci そのものの試験は Task 7 の側
import contextlib  # noqa: E402

import entry as real_entry  # noqa: E402
import test_board_engine_run as ER  # noqa: E402
from engine import declared  # noqa: E402

DECL_BROKEN = {"suite": []}


class CiRefused(Exception):
    """entry.CiRefused の代わり"""


def ref_run_ci(b, nid, *, test_cmd, runner=None):
    """entry.run_ci（Task 7）の約束をなぞる偽物"""
    got = b.run_engine(nid, runner=runner)
    if got.get("relaunch"):
        got = b.run_engine(nid, runner=runner)
        if got.get("relaunch"):
            raise CiRefused(got["why"])
    if got["ok"]:
        runs = got.get("runs") or []
        return {"by": "engine", "log": runs[0]["out"] if runs else ""}
    if "fallback" not in got:
        raise CiRefused(got["why"])
    log = b.work("tests.log")
    with open(log, "wb") as f:
        code = subprocess.run(["bash", "-c", test_cmd], cwd=b.state["inputs"]["cwd"], stdin=subprocess.DEVNULL,
                              stdout=f, stderr=subprocess.STDOUT).returncode
    tail = log.read_text(encoding="utf-8", errors="replace")[-400:]
    # 任せ先の返答を出す側が、出す前に起こした印を置く（board.py の頭の決まり 2。印の無い instance の返答は受けない）
    inst = next(i for i in b.rd["instances"].values() if i["node"] == nid and i["status"] == "pending")
    b.mark_launched(nid, inst.get("attempts", 1))
    # clean には checked が要る（受け付けの記録の整合: 何を見たかを書け）
    b.done(nid, {"material": {"status": "clean", "count": 0, "detail": tail, "checked": f"bash -c {test_cmd}: exit 0"}
                 if code == 0 else {"status": "found", "count": 1, "detail": tail}})
    return {"by": "role", "log": str(log)}


def never_run_ci(*a, **kw):
    raise AssertionError("run_ci を呼んではいけない")


class TestTestsModes(ER.EngineRunCase):
    def mode_board(self, decl=ER.GREEN, nth=0):
        """p4.ci が待っている darkfactory の盤面（stop_after_round は今の周）。手本の盤面を 1 本目のラインの本物の表
        （Task 3 の darkfactory/nodes.json）で組み、state.works に line・table_sha を置いて、本物の entry.open_board で開き直す。
        表は p4.ci の後ろの役の節を「このラインに無い」にするので、p4.ci の後の settle が p4.record・converge まで回る。
        decl は宣言の suite（None なら宣言を消す、dict なら本文そのもの）"""
        table = real_entry.load_table("darkfactory")

        def edit(mem):
            ER.minimal("p4.ci")(mem)
            mem["state"]["stop_after_round"] = mem["state"]["round"]
        b = self.board_before(ER.engine_run_step("p4.ci", nth), table=table, edit=edit)
        state = json.loads((b.dir / "state.json").read_text(encoding="utf-8"))
        state["works"].update(line=table.line, table_sha=table.sha())
        (b.dir / "state.json").write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        p = self.repo(b) / ER.DECL
        if decl is None:
            p.unlink()
        elif isinstance(decl, dict):
            p.write_text(json.dumps(decl), encoding="utf-8")
        else:
            self.write_decl(b, decl)
        return real_entry.open_board(b.dir)

    def reopen(self, b):
        return real_entry.open_board(b.dir, allow_halted=True)

    def call(self, b, mode, cmd, run_ci=ref_run_ci, entry="real"):
        """節のスクリプトの main を Archon と同じ環境変数で呼ぶ → (終了コード, 出口の dict か None, stderr)。
        entry は本物（Task 3 の open_board）。Task 7 の run_ci・CiRefused だけはこの枝に無いので偽物を足す。
        entry=None は entry が import できない時"""
        opened = []
        real_open = real_entry.open_board

        def open_board(d, **kw):
            opened.append(pathlib.Path(d))
            return real_open(d, **kw)

        env = {"INPUTS_CMD": cmd, "INPUTS_MODE": mode, "ARTIFACTS_DIR": str(b.dir.parent)}
        out, err = io.StringIO(), io.StringIO()
        mod = load_run_tests()
        with contextlib.ExitStack() as stack:
            if entry is None:
                stack.enter_context(mock.patch.dict(sys.modules, {"entry": None}))
            else:
                stack.enter_context(mock.patch.dict(sys.modules, {"entry": real_entry}))
                stack.enter_context(mock.patch.object(real_entry, "open_board", open_board))
                stack.enter_context(mock.patch.object(real_entry, "run_ci", run_ci, create=True))
                stack.enter_context(mock.patch.object(real_entry, "CiRefused", CiRefused, create=True))
            stack.enter_context(mock.patch.dict(os.environ, env))
            stack.enter_context(contextlib.redirect_stdout(out))
            stack.enter_context(contextlib.redirect_stderr(err))
            rc = mod.main()
        self.assertIn(opened, ([], [b.dir]))   # 盤面は <ARTIFACTS_DIR>/board を開く
        text = out.getvalue()
        if rc:
            self.assertEqual(text, "")
            return rc, None, err.getvalue()
        self.assertEqual(text.count("\n"), 1)
        return rc, json.loads(text), err.getvalue()

    # -- mid
    def test_mid_runs_declared_suite_without_shell(self):
        # 宣言の段を 1 つずつ shell を通さずに走らせる（argv の $・; はそのまま字で届く）。cmd は走らせない。盤面の節には書かない
        steps = [{"name": "unit", "argv": ["python3", "-c", "import sys; print(sys.argv[1:])", "$HOME;", "|x"]},
                 {"name": "lint", "argv": ["python3", "-c", "import sys; sys.exit(4)"]}]
        b = self.mode_board(decl=steps)
        before = ER.disk_bytes(b)
        marker = self.repo(b) / "cmd-ran"
        rc, out, err = self.call(b, "mid", f"touch {marker}")
        self.assertEqual(rc, 0, err)
        log, res = b.work("mid-tests.log"), b.work("mid-tests.json")
        self.assertEqual(out, {"ok": True, "green": False, "log": str(log),
                               "suites": [{"name": "unit", "exit": 0}, {"name": "lint", "exit": 4}], "by": "mid"})
        self.assertIn("['$HOME;', '|x']", log.read_text(encoding="utf-8"))
        self.assertFalse(marker.exists())
        got = json.loads(res.read_text(encoding="utf-8"))
        self.assertEqual({k: got[k] for k in ("by", "source", "green", "suites", "log", "sha")},
                         {"by": "mid", "source": "declared", "green": False, "suites": out["suites"], "log": str(log),
                          "sha": declared.steps_sha(steps)})
        self.assertEqual(ER.disk_bytes(b), before)   # state・record・trace は 1 バイトも変わらない（process.checks も）
        self.assertEqual(self.reopen(b).rd["instances"]["p4.ci"]["status"], "pending")

    def test_mid_green_suite(self):
        b = self.mode_board(decl=ER.GREEN)
        rc, out, err = self.call(b, "mid", "")
        self.assertEqual(rc, 0, err)
        self.assertEqual((out["ok"], out["green"], out["suites"]), (True, True, [{"name": "suite", "exit": 0}]))

    def test_mid_runs_cmd_when_no_declaration(self):
        # 宣言が無ければ cmd を 1 本目と同じく bash で走らせる。赤でも ok: true
        b = self.mode_board(decl=None)
        before = ER.disk_bytes(b)
        rc, out, err = self.call(b, "mid", "[[ -d . ]] && echo 赤 >&2; exit 3")
        self.assertEqual(rc, 0, err)
        log = b.work("mid-tests.log")
        self.assertEqual(out, {"ok": True, "green": False, "log": str(log), "suites": [{"name": "cmd", "exit": 3}],
                               "by": "mid"})
        self.assertIn("赤", log.read_text(encoding="utf-8"))
        self.assertEqual(json.loads(b.work("mid-tests.json").read_text(encoding="utf-8"))["source"], "cmd")
        self.assertEqual(ER.disk_bytes(b), before)

    def test_mid_broken_declaration_not_run(self):
        # 在るのに読めない宣言は engine と同じく走らせない（cmd にも落とさない）。走れなかった回は green: false で理由を残す
        b = self.mode_board(decl=DECL_BROKEN)
        marker = self.repo(b) / "cmd-ran"
        rc, out, err = self.call(b, "mid", f"touch {marker}")
        self.assertEqual(rc, 0, err)
        self.assertEqual((out["ok"], out["green"], out["suites"], out["by"]), (True, False, [], "mid"))
        self.assertFalse(marker.exists())
        got = json.loads(b.work("mid-tests.json").read_text(encoding="utf-8"))
        self.assertEqual(got["source"], "none")
        self.assertIn(ER.DECL, got["reason"])
        self.assertIn(ER.DECL, pathlib.Path(out["log"]).read_text(encoding="utf-8"))

    def test_mid_nothing_to_run(self):
        # 宣言も cmd も無い（修正役が宣言を消した等）→ 走れなかった回として green: false・ok: true（中の関所に見せる）
        b = self.mode_board(decl=None)
        rc, out, err = self.call(b, "mid", "  ")
        self.assertEqual(rc, 0, err)
        self.assertEqual((out["ok"], out["green"], out["suites"]), (True, False, []))
        self.assertTrue(json.loads(b.work("mid-tests.json").read_text(encoding="utf-8"))["reason"])

    def test_mid_round_two(self):
        # 周 2 の盤面でも作業ファイルは今の周の置き場（b.work）。周の番号を仮定しない（裁定 TA17）
        b = self.mode_board(nth=1)
        self.assertGreaterEqual(b.round, 2)
        rc, out, err = self.call(b, "mid", "")
        self.assertEqual(rc, 0, err)
        self.assertEqual(out["log"], str(b.work("mid-tests.log")))
        self.assertTrue(b.work("mid-tests.json").exists())

    # -- final
    def test_final_by_engine(self):
        # 宣言が在れば engine が走らせる（cmd は空でよい）。process.checks["p4.ci"].by == "engine"、green は素材の clean
        b = self.mode_board(decl=ER.GREEN)
        rc, out, err = self.call(b, "final", "")
        self.assertEqual(rc, 0, err)
        self.assertEqual((out["ok"], out["green"], out["by"], out["suites"]), (True, True, "engine", [{"name": "suite", "exit": 0}]))
        after = self.reopen(b)
        self.assertEqual(after.record["process"]["checks"]["p4.ci"]["by"], "engine")
        self.assertEqual(after.record["materials"]["local_checks"]["status"], "clean")

    def test_final_red_suite_is_ok(self):
        b = self.mode_board(decl=ER.RED)
        rc, out, err = self.call(b, "final", "")
        self.assertEqual(rc, 0, err)
        self.assertEqual((out["ok"], out["green"], out["by"], out["suites"]), (True, False, "engine", [{"name": "suite", "exit": 3}]))

    def test_final_log_from_run_engine(self):
        # engine が走らせた時の log は run_engine の返りの runs[0].out（runs/r<N>/ を組み立てない）
        seen = {}

        def spy(b, nid, *, test_cmd, runner=None):
            orig = b.run_engine

            def run_engine(*a, **kw):
                seen["got"] = orig(*a, **kw)
                return seen["got"]
            b.run_engine = run_engine
            return ref_run_ci(b, nid, test_cmd=test_cmd, runner=runner)

        b = self.mode_board(decl=ER.GREEN)
        rc, out, err = self.call(b, "final", "", run_ci=spy)
        self.assertEqual(rc, 0, err)
        self.assertEqual(out["log"], seen["got"]["runs"][0]["out"])
        self.assertEqual(pathlib.Path(out["log"]).read_text(encoding="utf-8"), "1 passed\n")

    def test_final_fallback_runs_cmd(self):
        # 宣言が無ければ任せ先（by: role）: cmd を走らせた結果を素材で done。green は cmd の結果
        for cmd, green, status in (("echo 走った", True, "clean"), ("echo 赤; exit 2", False, "found")):
            with self.subTest(cmd=cmd):
                b = self.mode_board(decl=None)
                rc, out, err = self.call(b, "final", cmd)
                self.assertEqual(rc, 0, err)
                self.assertEqual((out["ok"], out["green"], out["by"], out["suites"]), (True, green, "role", []))
                self.assertEqual(out["log"], str(b.work("tests.log")))
                after = self.reopen(b)
                self.assertEqual(after.record["process"]["checks"]["p4.ci"]["by"], "role")
                self.assertEqual(after.record["materials"]["local_checks"]["status"], status)
                self.assertEqual(after.node_state("p4.ci"), "done")

    def test_final_empty_cmd_on_fallback_fails(self):
        # 宣言が無く cmd も空 → 任せ先に落とせない。終了コード 1・理由を stderr、盤面は書かない
        b = self.mode_board(decl=None)
        before = ER.disk_bytes(b)
        rc, out, err = self.call(b, "final", " ", run_ci=never_run_ci)
        self.assertEqual((rc, out), (1, None))
        self.assertIn(ER.DECL, err)
        self.assertEqual(ER.disk_bytes(b), before)

    def test_final_ci_refused(self):
        # run_ci が拒んだ（2 度とも relaunch・why だけの返り）→ 終了コード 1、stderr に why
        def refuse(*a, **kw):
            raise CiRefused("宣言が計画の後に 2 度変わった")

        b = self.mode_board(decl=ER.GREEN)
        rc, out, err = self.call(b, "final", "", run_ci=refuse)
        self.assertEqual((rc, out), (1, None))
        self.assertIn("宣言が計画の後に 2 度変わった", err)

    def test_final_settles_to_record(self):
        # final の後の盤面で p4.record と converge が済み、stop_after_round で止まっている
        b = self.mode_board(decl=ER.GREEN)
        rc, out, err = self.call(b, "final", "")
        self.assertEqual(rc, 0, err)
        after = self.reopen(b)
        self.assertEqual((after.node_state("p4.record"), after.node_state("converge")), ("done", "done"))
        self.assertEqual(after.state["halted"]["by"], "stop_after_round")

    def test_final_round_two(self):
        b = self.mode_board(nth=1)
        self.assertGreaterEqual(b.round, 2)
        rc, out, err = self.call(b, "final", "")
        self.assertEqual(rc, 0, err)
        after = self.reopen(b)
        self.assertEqual(out["log"], after.record["process"]["checks"]["p4.ci"]["runs"][0]["out"])
        self.assertEqual(after.state["halted"]["by"], "stop_after_round")

    # -- 共通
    def test_exit_keeps_v1_fields(self):
        # 出口は 1 本目の ok・green・log を全部残し、mid・final の時だけ suites・by を足す
        for mode in ("mid", "final"):
            with self.subTest(mode=mode):
                b = self.mode_board()
                rc, out, err = self.call(b, mode, "")
                self.assertEqual(rc, 0, err)
                self.assertEqual(set(out), {"ok", "green", "log", "suites", "by"})
                self.assertTrue(all(set(s) == {"name", "exit"} for s in out["suites"]))

    def test_modes_need_entry(self):
        # mid・final は盤面の口（entry）が要る。読めなければ回す側の誤り（終了コード 2）で、盤面を書かない
        for mode in ("mid", "final"):
            with self.subTest(mode=mode):
                b = self.mode_board()
                before = ER.disk_bytes(b)
                rc, out, err = self.call(b, mode, "true", entry=None)
                self.assertEqual((rc, out), (2, None))
                self.assertIn("entry", err)
                self.assertEqual(ER.disk_bytes(b), before)

# ---------------------------------------------------------------- blk-delta の cut
class TestCut(RepoCase):
    def fix(self):
        (self.repo / "stats.py").write_text((self.repo / "stats.py").read_text().replace("return lo\n    return x", "return hi\n    return x"))
        (self.repo / "helper.py").write_text("def helper():\n    return 1\n")

    def test_cut_writes_diff_snapshot_and_files(self):
        self.fix()
        r = self.run_script("blk-delta", "cut", base_rev=self.base)
        self.assertEqual(r.returncode, 0, r.stderr)
        out = json.loads(r.stdout)
        self.assertEqual(out, {"ok": True, "files": ["helper.py", "stats.py"], "diff_file": str(self.board / "fix.diff")})
        diff = (self.board / "fix.diff").read_text(encoding="utf-8")
        self.assertIn("+        return hi", diff)
        self.assertIn("+def helper():", diff)       # 未追跡のファイルも差分に載る
        self.assertEqual(json.loads((self.board / "delta-snapshot.json").read_text()), snapshot_tree(self.repo))
        # 切った直後の作業ツリーのままなら、受け付けは写しとの突き合わせを通る
        self.assertTrue(check_delta(load("delta_ok"), self.board, self.base, self.repo)["ok"])

    def test_cut_empty_base_rev_means_head(self):
        self.fix()
        r = self.run_script("blk-delta", "cut", base_rev="")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(json.loads(r.stdout)["files"], ["helper.py", "stats.py"])

    def test_cut_clean_tree(self):
        r = self.run_script("blk-delta", "cut", base_rev="")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(json.loads(r.stdout)["files"], [])
        self.assertEqual((self.board / "fix.diff").read_text(), "")

    def test_cut_skips_bytecode(self):
        # 種の .gitignore が無く、テストがバイトコードを作った作業ツリー。追跡している .pyc が変わっても差分に載せない
        git(self.repo, "rm", "-q", ".gitignore")
        (self.repo / "old.pyc").write_bytes(b"\x00old")
        git(self.repo, "add", "old.pyc")
        git(self.repo, "commit", "-q", "-m", "no ignore")
        base = git(self.repo, "rev-parse", "HEAD")
        (self.repo / "old.pyc").write_bytes(b"\x00new")
        env = {k: v for k, v in os.environ.items() if k != "PYTHONDONTWRITEBYTECODE"}
        subprocess.run([sys.executable, "-m", "unittest", "-q", "test_stats"], cwd=str(self.repo), env=env,
                       capture_output=True, timeout=120)
        self.assertTrue(list(self.repo.rglob("*.pyc")))                  # バイトコードは本当に出来た
        self.fix()
        r = self.run_script("blk-delta", "cut", base_rev=base)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(json.loads(r.stdout)["files"], ["helper.py", "stats.py"])
        diff = (self.board / "fix.diff").read_text(encoding="utf-8", errors="replace")
        self.assertNotIn(".pyc", diff)
        self.assertNotIn("__pycache__", diff)

    def test_seed_ignores_bytecode(self):
        env = {k: v for k, v in os.environ.items() if k != "PYTHONDONTWRITEBYTECODE"}
        subprocess.run([sys.executable, "-m", "unittest", "-q", "test_stats"], cwd=str(self.repo), env=env,
                       capture_output=True, timeout=120)
        self.assertEqual(git(self.repo, "status", "--porcelain", "--untracked-files=all"), "")

    def test_cut_and_accept_japanese_name(self):
        # 日本語の名前も git の引用（"\346\227\245..."）でなく、そのままの名前で files と受け付けに乗る
        (self.repo / "日本.py").write_text("def 日付():\n    return 1\n", encoding="utf-8")
        (self.repo / "stats.py").write_text((self.repo / "stats.py").read_text() + "\n# 直した\n")
        git(self.repo, "add", "日本.py")                                   # 追跡している側（diff --name-only）
        (self.repo / "未追跡.py").write_text("x = 1\n", encoding="utf-8")  # 未追跡の側（ls-files）
        r = self.run_script("blk-delta", "cut", base_rev=self.base)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(json.loads(r.stdout)["files"], sorted(["stats.py", "日本.py", "未追跡.py"]))
        self.assertIn("未追跡.py", (self.board / "fix.diff").read_text(encoding="utf-8"))
        for where, cite in (("日本.py", "def 日付():"), ("未追跡.py", "x = 1")):
            reply = {"faces": [{"key": f"{where} 使われない物", "kind": "dead_path", "where": where, "cite": cite,
                                "why": "どこからも呼ばれない物を修正が足している"}], "checks": []}
            res = check_delta(reply, self.board, self.base, self.repo)
            self.assertTrue(res["ok"], res["reason"])

    def test_cut_bad_base_rev_stops_the_run(self):
        r = self.run_script("blk-delta", "cut", base_rev="no-such-rev")
        self.assertEqual(r.returncode, 1)
        self.assertEqual(r.stdout, "")
        self.assertIn("no-such-rev", r.stderr)

    def test_cut_missing_env(self):
        env_less = {k: v for k, v in os.environ.items() if not k.startswith("INPUTS_") and k != "ARTIFACTS_DIR"}
        r = subprocess.run([sys.executable, str(ROOT / "blk-delta" / "scripts" / "cut.py")], cwd=str(self.repo),
                           env={**env_less, "PYTHONDONTWRITEBYTECODE": "1"}, capture_output=True, text=True, timeout=120)
        self.assertEqual(r.returncode, 2)
        self.assertEqual(r.stdout, "")


# ---------------------------------------------------------------- blk-delta の accept と collect
class TestAcceptCollect(RepoCase):
    def test_accept_then_collect_counts_faces(self):
        (self.repo / "stats.py").write_text((self.repo / "stats.py").read_text().replace("return lo\n    return x", "return hi + 1\n    return x"))
        reply = json.dumps(load("delta_bad_cite"), ensure_ascii=False)   # stats.py を触ったので cite は今の姿に在る
        r = self.run_script("blk-delta", "accept", reply=reply, base_rev=self.base)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(json.loads(r.stdout)["ok"], True, r.stdout)
        self.assertEqual(self.run_script("blk-delta", "cut", base_rev=self.base).returncode, 0)
        r = self.run_script("blk-delta", "collect")
        self.assertEqual(r.returncode, 0, r.stderr)
        out = json.loads(r.stdout)
        # 出口は穴の数と、run の後に人が見る審査の返答・修正の差分のパス（I4）
        self.assertEqual(out, {"ok": True, "faces": 1, "review_file": str(self.board / "delta-review.json"),
                               "diff_file": str(self.board / "fix.diff")})
        self.assertTrue(pathlib.Path(out["diff_file"]).exists())
        collect = find_node(workflow("blk-delta")["nodes"], "collect")
        self.assertEqual(validate_schema(out, collect["output_format"]), [])
        self.assertEqual(sorted(collect["output_format"]["required"]), ["diff_file", "faces", "ok", "review_file"])

    def test_accept_rejects_face_outside_touched_files(self):
        r = self.run_script("blk-delta", "accept", reply=json.dumps(load("delta_bad_cite")), base_rev="")
        self.assertEqual(r.returncode, 0, r.stderr)
        out = json.loads(r.stdout)
        self.assertFalse(out["ok"])
        self.assertTrue(out["reason"])
        self.assertFalse((self.board / "delta-review.json").exists())   # 拒んだ返答は盤面に残さない

    def test_collect_without_accepted_review_fails(self):
        r = self.run_script("blk-delta", "collect")
        self.assertEqual(r.returncode, 1)
        self.assertEqual(r.stdout, "")


# ---------------------------------------------------------------- snapshot_tree と未追跡のフォルダ
class TestSnapshotNestedRepo(RepoCase):
    def test_untracked_nested_repo_does_not_crash(self):
        sub = self.repo / "sub"
        sub.mkdir()
        (sub / "a.txt").write_text("a\n")
        git(sub, "init", "-q")
        git(sub, "add", "-A")
        git(sub, "commit", "-q", "-m", "sub")
        self.assertIn("?? sub/", git(self.repo, "status", "--porcelain", "--untracked-files=all"))
        before = snapshot_tree(self.repo)
        self.assertEqual(before, snapshot_tree(self.repo))   # 同じ姿なら同じ写し
        (sub / "a.txt").write_text("b\n")                    # 入れ子の中身が変われば写しも変わる
        self.assertNotEqual(before["diff_sha256"], snapshot_tree(self.repo)["diff_sha256"])

    def test_cut_and_accept_with_nested_repo(self):
        sub = self.repo / "sub"
        sub.mkdir()
        (sub / "a.txt").write_text("a\n")
        git(sub, "init", "-q")
        r = self.run_script("blk-delta", "cut", base_rev="")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("sub/", json.loads(r.stdout)["files"])
        self.assertTrue(check_delta(load("delta_ok"), self.board, "", self.repo)["ok"])


if __name__ == "__main__":
    unittest.main()
