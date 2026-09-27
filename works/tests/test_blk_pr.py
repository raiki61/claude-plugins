"""並行 PR の検査 p0.parallel_pr（線 A Task 21。仕様 3.8・裁定 TA8。持ち主の答え 2026-09-27: 案 (a)）の試験。

1〜5 段は盤面の層の run_engine が写しの parallel-pr.py を走らせ（prcheck.run_helper）、任せ先に落ちた時だけ読むだけの役
pr-check（ブロック blk-pr）が 6 段をする。申し送りは投稿せず、下書きを conflicts[].note に書き handed_over を false で返す。

盤面は本物のラインと同じ道で作る: 使い捨てのリポジトリに、1 本目のラインの本物の表（darkfactory/nodes.json。entry.load_table）で
DiskBoard.begin（判定から入る run。依頼 2 件）→ Progress.run_engine の節を run_engine（p0.parallel_pr は run_helper に残す）
→ settle。盤面は本物の entry.open_board で開く（prcheck の既定の口）。本物の gh・GitHub・網には触らない:
PATH の頭に偽の gh（何を打っても exit 9）を置き、engine の helper は偽の runner で差す。
"""
import ast
import hashlib
import importlib.util
import json
import os
import re
import pathlib
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

sys.dont_write_bytecode = True
HERE = pathlib.Path(__file__).resolve().parent
PACK = HERE.parent
sys.path.insert(0, str(HERE))

import boardreplay as R  # noqa: E402  （board と写しの engine を sys.path に足す）
from board import GRAPH_PATH, BoardGap, DiskBoard  # noqa: E402
import entry  # noqa: E402
import engine.util as engine_util  # noqa: E402
from engine.schema import validate_schema  # noqa: E402
from accept import role_schema  # noqa: E402
import prcheck  # noqa: E402
import script_io  # noqa: E402

REPLIES = HERE / "replies"
BLOCK = PACK / "blk-pr"
SCRIPTS = BLOCK / "scripts"
GRAPH = json.loads(GRAPH_PATH.read_text(encoding="utf-8"))

REQUEST = json.loads((REPLIES / "request_ok.json").read_text(encoding="utf-8"))
GREEN = {"suite": [{"name": "suite", "argv": [sys.executable, "-c", "print('1 passed')"]}]}


def reply(name):
    return json.loads((REPLIES / name).read_text(encoding="utf-8"))


LINE = "darkfactory"


def opener(d, **kw):
    """本物のラインが盤面を開く口（prcheck の既定と同じ entry.open_board）"""
    return entry.open_board(d, **kw)


def board_shas(d):
    # reject-*.txt は受け付けの出口（script_io.emit_result）が拒否の本文を書く reason_file で、盤面の層のファイルではない
    d = pathlib.Path(d)
    return {p.relative_to(d).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(d.rglob("*"))
            if p.is_file() and not p.name.startswith(("pr-snapshot", "pr-brief", script_io.REJECT_PREFIX))}


def helper_out(conflicts):
    """engine の helper（parallel-pr.py）の代わりに、決めた印字を返す runner（本物の gh を起こさない）"""
    calls = []

    def runner(steps, cwd, log_dir):
        calls.append(steps)
        log_dir.mkdir(parents=True, exist_ok=True)
        out, err = log_dir / "1.out", log_dir / "1.err"
        out.write_text(json.dumps({"repo": "o/r", "listed": 2, "truncated": False, "conflicts": conflicts}), encoding="utf-8")
        err.write_text("", encoding="utf-8")
        return [{"name": steps[0]["name"], "argv": steps[0]["argv"], "out": str(out), "err": str(err),
                 "exit": 0, "wall_s": 0.1, "tail": ""}]
    runner.calls = calls
    return runner


def never(*a, **kw):
    raise AssertionError(f"runner を呼んではいけない: {a}")


CROSSING = [{"pr": "7", "files": ["stats.py"]}]
GITHUB = "git@github.com:o/r.git"
_SEEDS = []


def _seeds():
    if not _SEEDS:
        _SEEDS.append(pathlib.Path(tempfile.mkdtemp(prefix="blk-pr-seeds-")))
    return _SEEDS[0]


def tearDownModule():
    for d in _SEEDS:
        shutil.rmtree(d, ignore_errors=True)


class PrCase(unittest.TestCase):
    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp(prefix="blk-pr-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        env = mock.patch.dict(os.environ, R.git_env())
        env.start()
        self.addCleanup(env.stop)
        cwd = engine_util.GIT_CWD
        self.addCleanup(setattr, engine_util, "GIT_CWD", cwd)
        # 偽の gh を PATH の頭に（本物の gh・GitHub に触らない。何を打っても exit 9）
        bin_dir = self.tmp / "fake-bin"
        bin_dir.mkdir()
        gh = bin_dir / "gh"
        gh.write_text('#!/bin/sh\necho "fake gh: $*" >&2\nexit 9\n', encoding="utf-8")
        gh.chmod(0o755)
        path = mock.patch.dict(os.environ, {"PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}"})
        path.start()
        self.addCleanup(path.stop)

    def git(self, *args):
        return subprocess.run(["git", "-C", str(self.repo), *args], check=True, capture_output=True, text=True).stdout

    def build(self, root):
        """p0.parallel_pr が待っている盤面を root に作る（判定から入る run。p0.base・p0.local_checks は済み、p0.premises は待ち）"""
        self.repo, self.art = root / "repo", root / "art"
        self.repo.mkdir(parents=True)
        self.git("init", "-q")
        (self.repo / "stats.py").write_text("def mean(xs):\n    return sum(xs)\n", encoding="utf-8")
        (self.repo / ".review-checks.json").write_text(json.dumps(GREEN), encoding="utf-8")
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "seed")
        self.git("remote", "add", "origin", GITHUB)
        table = entry.load_table(LINE)
        b, p = DiskBoard.begin(self.art / "board", repo=self.repo, table=table, items=REQUEST, origin="works/darkfactory",
                               base_rev="", request_text="依頼", stop_after_round=1, **entry.hook_kwargs(LINE, table))
        # ラインの約束 1: Progress.run_engine の節を全部走らせて settle、を空になるまで（p0.parallel_pr は start が run_helper で回す）
        while [n for n in p["run_engine"] if n != prcheck.NODE]:
            for nid in p["run_engine"]:
                if nid != prcheck.NODE:
                    self.assertTrue(b.run_engine(nid)["ok"], nid)
            p = b.settle()
        self.assertEqual(p["run_engine"], [prcheck.NODE])
        self.assertIn(prcheck.NODE, p["ready"])

    def restore(self, kind):
        """盤面の種（ready: p0.parallel_pr が待っている・fallen: engine が交差 1 件を見て任せ先に落ちた）を、1 度だけ作って
        写しておいた物から同じ場所に戻す（盤面は絶対パスを持つので場所を変えない。1 つ作るのに git を何十回も呼ぶため）"""
        live = _seeds() / "live"
        pristine = _seeds() / kind
        if not pristine.exists():
            shutil.rmtree(live, ignore_errors=True)
            self.build(live)
            if kind == "fallen":
                got = prcheck.run_helper(opener(live / "art" / "board"), runner=helper_out(CROSSING))
                self.assertTrue(got["role_needed"], got)
            shutil.copytree(live, pristine, symlinks=True)
        shutil.rmtree(live, ignore_errors=True)
        shutil.copytree(pristine, live, symlinks=True)
        self.repo, self.art = live / "repo", live / "art"
        return opener(self.art / "board")

    def pr_ready(self, remote=GITHUB):
        """p0.parallel_pr が待っている盤面。remote を替えれば origin の URL を替える（plan は走らせる時に remote を読む）"""
        b = self.restore("ready")
        if remote != GITHUB:
            self.git("remote", "set-url", "origin", remote)
        return b

    def fallen(self):
        """任せ先に落ちた盤面（engine が交差 1 件を見た）"""
        return self.restore("fallen")


class HelperCase(PrCase):
    def test_helper_by_engine_when_no_crossing(self):
        """交差 0 → engine の返答で済む（by engine・役は要らない）。素材は clean、節は済み、runner は 1 度だけ"""
        b = self.pr_ready()
        runner = helper_out([])
        got = prcheck.run_helper(b, runner=runner)
        self.assertEqual(got, {"by": "engine", "role_needed": False, "why": ""})
        self.assertEqual(len(runner.calls), 1)
        self.assertEqual(b.rd["instances"][prcheck.NODE]["status"], "done")
        self.assertEqual(b.record["materials"]["parallel_pr"]["status"], "clean")
        # 写しの RL は p0.parallel_pr を process.checks に書かない（書くのは CI の節だけ）。by は run_helper の返りで見る
        self.assertNotIn(prcheck.NODE, b.record["process"].get("checks", {}))
        self.assertNotIn(prcheck.NODE, b.settle()["ready"])

    def test_fallback_on_crossing_sets_role_needed(self):
        """交差 1 件 → 任せ先へ（by role・role_needed）。節は待ちのまま engine_fallback を持ち、settle の後も ready に残る"""
        b = self.pr_ready()
        got = prcheck.run_helper(b, runner=helper_out(CROSSING))
        self.assertEqual((got["by"], got["role_needed"]), ("role", True))
        self.assertIn("交差", got["why"])
        inst = b.rd["instances"][prcheck.NODE]
        self.assertEqual((inst["status"], inst["engine_fallback"]), ("pending", got["why"]))
        self.assertIn(prcheck.NODE, b.settle()["ready"])
        self.assertNotIn("parallel_pr", b.record["materials"])   # 素材は任せ先が返すまで書かない

    def test_fallback_on_non_github_remote_without_running(self):
        """remote が GitHub でない → 何も走らせずに任せ先へ（同等のコマンドへの読み替えは役）"""
        b = self.pr_ready(remote="https://git.example.com/o/r.git")
        got = prcheck.run_helper(b, runner=never)
        self.assertEqual((got["by"], got["role_needed"]), ("role", True))
        self.assertIn("GitHub でない", got["why"])

    def test_fallback_when_gh_missing(self):
        """gh が無い → 何も走らせずに任せ先へ"""
        b = self.pr_ready()
        real = shutil.which
        with mock.patch("shutil.which", lambda name, *a, **kw: None if name == "gh" else real(name, *a, **kw)):
            got = prcheck.run_helper(b, runner=never)
        self.assertEqual((got["by"], got["role_needed"]), ("role", True))
        self.assertIn("gh", got["why"])

    def test_run_helper_again_after_fallback_does_not_rerun(self):
        """任せ先に落ちた後に呼び直す（線 B の境の節も同じ関数を呼ぶ）→ 走らせず、同じ答え"""
        b = self.fallen()
        why = b.rd["instances"][prcheck.NODE]["engine_fallback"]
        self.assertEqual(prcheck.run_helper(b, runner=never), {"by": "role", "role_needed": True, "why": why})

    def test_not_ready_returns_empty(self):
        """ready に無い（済んだ・instance が無い・人に聞いている間）→ {by: "", role_needed: False}、走らせない"""
        b = self.pr_ready()
        prcheck.run_helper(b, runner=helper_out([]))
        self.assertEqual(prcheck.run_helper(b, runner=never), {"by": "", "role_needed": False, "why": ""})
        b = self.pr_ready()
        b.state["pending_human"] = {"node": "p2.human_gate"}
        self.assertEqual(prcheck.run_helper(b, runner=never), {"by": "", "role_needed": False, "why": ""})
        del b.rd["instances"][prcheck.NODE]
        b.state.pop("pending_human")
        self.assertEqual(prcheck.run_helper(b, runner=never), {"by": "", "role_needed": False, "why": ""})

    def test_run_helper_relaunch_once(self):
        """1 度目 relaunch・2 度目通る → 通る。2 度とも relaunch → Refused（文に why）。why だけの返り → Refused"""
        b = self.pr_ready()
        relaunch = {"ok": False, "node": prcheck.NODE, "why": "宣言が変わった", "relaunch": True}
        ok = {"ok": True, "node": prcheck.NODE, "runs": []}
        with mock.patch.object(b, "run_engine", side_effect=[relaunch, ok]) as m:
            self.assertEqual(prcheck.run_helper(b), {"by": "engine", "role_needed": False, "why": ""})
        self.assertEqual(m.call_count, 2)
        with mock.patch.object(b, "run_engine", side_effect=[relaunch, relaunch]) as m:
            with self.assertRaises(prcheck.Refused) as cm:
                prcheck.run_helper(b)
        self.assertEqual(m.call_count, 2)
        self.assertIn("宣言が変わった", str(cm.exception))
        with mock.patch.object(b, "run_engine", return_value={"ok": False, "node": prcheck.NODE, "why": "根が引けない"}) as m:
            with self.assertRaises(prcheck.Refused) as cm:
                prcheck.run_helper(b)
        self.assertEqual(m.call_count, 1)
        self.assertIn("根が引けない", str(cm.exception))

    def test_blocked_is_engine_with_reason(self):
        """交差を取る集合が空（依頼の where が追跡中のパスを名指さない）→ engine が not_run で済ませ、why に理由"""
        b = self.pr_ready()
        for batch in b.record["process"]["request_findings"]:
            for f in batch["findings"]:
                f["where"] = "nowhere.py"
        got = prcheck.run_helper(b, runner=never)
        self.assertEqual((got["by"], got["role_needed"]), ("engine", False))
        self.assertIn("空", got["why"])
        self.assertEqual(b.record["materials"]["parallel_pr"]["status"], "not_run")


# ---------------------------------------------------------------- 任せ先の役の受け付け
def load_script(name):
    spec = importlib.util.spec_from_file_location(f"blk_pr_{name}", SCRIPTS / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def run_script(name, env, cwd=None):
    full = {k: v for k, v in os.environ.items() if not k.startswith("INPUTS_") and k != "ARTIFACTS_DIR"}
    full.update(env, PYTHONDONTWRITEBYTECODE="1")
    return subprocess.run([sys.executable, str(SCRIPTS / f"{name}.py")], env=full, capture_output=True, text=True,
                          encoding="utf-8", stdin=subprocess.DEVNULL, cwd=str(cwd) if cwd else None)


class AcceptCase(PrCase):
    def test_reply_samples_fit_schema(self):
        """見本の 3 つは役の output_format に合い、excluded を外せば写しの p0.parallel_pr の schema に合う
        （handed_over true も型は通る。拒むのは works の検査）"""
        works = {k: v for k, v in prcheck.OUTPUT_FORMAT.items() if k != "description"}
        for name in ("pr_ok.json", "pr_handed_over.json", "pr_no_conflicts.json"):
            r = reply(name)
            self.assertEqual(validate_schema(r, works), [], name)
            self.assertEqual(validate_schema({k: v for k, v in r.items() if k != "excluded"}, role_schema(prcheck.NODE)), [], name)

    def test_check_no_post(self):
        acc = load_script("accept")
        self.assertEqual(acc.check_no_post(reply("pr_handed_over.json")), ["7"])
        self.assertEqual(acc.check_no_post(reply("pr_ok.json")), [])
        self.assertEqual(acc.check_no_post(reply("pr_no_conflicts.json")), [])
        two = reply("pr_ok.json")
        two["conflicts"] += [{"pr": "9", "files": ["a"], "handed_over": True}, {"pr": "11", "files": ["b"], "handed_over": True}]
        self.assertEqual(acc.check_no_post(two), ["9", "11"])
        self.assertEqual(acc.check_no_post({"conflicts": "x"}), [])

    def test_handed_over_true_rejected(self):
        """handed_over true が 1 件 → 受け付けのスクリプトが 0 で ok false を 1 行、文に pr と「投稿しない」。盤面は前のまま"""
        b = self.fallen()
        prcheck.snapshot(b.dir, self.repo, opener=opener)
        before = board_shas(b.dir)
        r = run_script("accept", {"INPUTS_REPLY": json.dumps(reply("pr_handed_over.json")), "ARTIFACTS_DIR": str(self.art)})
        self.assertEqual(r.returncode, 0, r.stderr)
        lines = r.stdout.splitlines()
        self.assertEqual(len(lines), 1)
        got = json.loads(lines[0])
        self.assertFalse(got["ok"])
        self.assertIn("投稿しない", got["reason"])
        self.assertIn("持ち主の決定 2026-09-27", got["reason"])
        self.assertTrue(got["reason"].endswith(": 7"), got["reason"])
        # 次の周へは本文でなく reason_file（盤面のファイル。中身は本文と字のまま同じ）を渡す
        self.assertEqual(pathlib.Path(got["reason_file"]).read_text(encoding="utf-8"), got["reason"])
        self.assertEqual(pathlib.Path(got["reason_file"]).parent, (self.art / "board").resolve())
        self.assertEqual(board_shas(b.dir), before)

    def test_handover_draft_accepted(self):
        """handed_over false・note つき → 通る。節は済み、ラインの次の段（前提の実測 p0.premises）が待つ。
        p1.consistency_bypass（p0.parallel_pr に依存する P1 の節）の依存で残るのは、前提の後に表の absent で済む p0.purpose だけ"""
        b = self.fallen()
        prcheck.snapshot(b.dir, self.repo, opener=opener)
        got = prcheck.take(b.dir, reply("pr_ok.json"), self.repo, opener=opener)
        self.assertEqual({k: got[k] for k in ("ok", "reason", "ready", "asking", "halted")},
                         {"ok": True, "reason": "", "ready": ["p0.premises"], "asking": False, "halted": False})
        self.assertTrue((b.dir / got["out_file"]).is_file())
        b2 = opener(b.dir)
        self.assertEqual(b2.node_state(prcheck.NODE), "done")
        wait = [d for d in GRAPH["nodes"]["p1.consistency_bypass"]["deps"] if b2.node_state(d) == "pending"]
        self.assertEqual(wait, ["p0.purpose"])
        self.assertEqual(b2.record["process"]["parallel_pr"]["conflicts"][0]["note"], reply("pr_ok.json")["conflicts"][0]["note"])
        self.assertEqual(b2.record["materials"]["parallel_pr"]["status"], "found")
        self.assertNotIn("excluded", json.loads((b.dir / got["out_file"]).read_text(encoding="utf-8")))

    def test_excluded_hunks_leave_scope(self):
        """review-graph の 6 段の「本ループのスコープから外す」: 受けた外す hunk は今の周の pr-excluded.json に置かれ、
        collect の excluded_file が指す（後の役に触らせない範囲として渡す）"""
        b = self.fallen()
        prcheck.snapshot(b.dir, self.repo, opener=opener)
        self.assertTrue(prcheck.take(b.dir, reply("pr_ok.json"), self.repo, opener=opener)["ok"])
        got = prcheck.collect(b.dir, opener=opener)
        self.assertEqual((got["ok"], got["excluded"]), (True, 1))
        self.assertEqual(pathlib.Path(got["excluded_file"]), opener(b.dir).work(prcheck.EXCLUDED))
        doc = json.loads(pathlib.Path(got["excluded_file"]).read_text(encoding="utf-8"))
        self.assertEqual(doc["node"], prcheck.NODE)
        self.assertEqual([{k: h[k] for k in ("pr", "file", "start", "end", "why")} for h in doc["excluded"]],
                         reply("pr_ok.json")["excluded"])

    def test_malformed_reply_bounced_not_crashed(self):
        """型の崩れた返答（conflicts の pr が配列・note が数）→ 例外でなく ok false（型の文）で役に返す。盤面は前のまま。
        外す hunk の検査より先に写しの schema を当てる"""
        b = self.fallen()
        prcheck.snapshot(b.dir, self.repo, opener=opener)
        before = board_shas(b.dir)
        base = reply("pr_ok.json")
        row = base["conflicts"][0]
        for bad in (dict(base, conflicts=[dict(row, pr=["7"])], excluded=[]),
                    dict(base, conflicts=[dict(row, note=5)]),
                    dict(base, conflicts=[dict(row, files="stats.py")])):
            got = prcheck.take(b.dir, bad, self.repo, opener=opener)
            self.assertFalse(got["ok"], bad)
            self.assertIn("型", got["reason"])
            self.assertEqual(board_shas(b.dir), before)

    def test_excluded_carries_content_anchor(self):
        """外す hunk ごとに、受け付けた時の行の中身（text）とその sha256 と、写しの HEAD を pr-excluded.json に残す
        （後の周の修正で行がずれても、後の役が中身で引き直せる）"""
        b = self.fallen()
        prcheck.snapshot(b.dir, self.repo, opener=opener)
        self.assertTrue(prcheck.take(b.dir, reply("pr_ok.json"), self.repo, opener=opener)["ok"])
        doc = json.loads(opener(b.dir).work(prcheck.EXCLUDED).read_text(encoding="utf-8"))
        text = "def mean(xs):\n    return sum(xs)\n"
        self.assertEqual(doc["head"], self.git("rev-parse", "HEAD").strip())
        h = doc["excluded"][0]
        self.assertEqual({k: h[k] for k in ("pr", "file", "start", "end")}, {"pr": "7", "file": "stats.py", "start": 1, "end": 2})
        self.assertEqual(h["text"], text)
        self.assertEqual(h["sha256"], hashlib.sha256(text.encode("utf-8")).hexdigest())

    def test_unborn_head_after_role_is_reply_reject(self):
        """役が HEAD を生まれていない枝にした（checkout --orphan）→ 回す側の誤り（例外）でなく ok false"""
        b = self.fallen()
        prcheck.snapshot(b.dir, self.repo, opener=opener)
        before = board_shas(b.dir)
        self.git("checkout", "-q", "--orphan", "newroot")
        got = prcheck.take(b.dir, reply("pr_ok.json"), self.repo, opener=opener)
        self.assertFalse(got["ok"])
        self.assertIn("作業ツリーを変えた", got["reason"])
        self.assertEqual(board_shas(b.dir), before)

    def test_excluded_checked(self):
        """外す hunk の誤り → ok false（役に返す）、盤面は前のまま: 欄が無い・PR が conflicts に無い・ファイルが交差に無い・
        start > end・end がファイルの行の数を超える・下書き（note）の無い PR の hunk"""
        b = self.fallen()
        prcheck.snapshot(b.dir, self.repo, opener=opener)
        before = board_shas(b.dir)
        base = reply("pr_ok.json")
        hunk = base["excluded"][0]
        cases = {"excluded が無い": {k: v for k, v in base.items() if k != "excluded"},
                 "conflicts に無い": dict(base, excluded=[dict(hunk, pr="99")]),
                 "交差したファイル": dict(base, excluded=[dict(hunk, file="other.py")]),
                 "より大きい": dict(base, excluded=[dict(hunk, start=2, end=1)]),
                 "行の数 2 を超える": dict(base, excluded=[dict(hunk, end=3)]),
                 "note": dict(base, conflicts=[{k: v for k, v in base["conflicts"][0].items() if k != "note"}]),
                 "型": dict(base, excluded=[dict(hunk, start=0)])}
        for word, bad in cases.items():
            got = prcheck.take(b.dir, bad, self.repo, opener=opener)
            self.assertFalse(got["ok"], word)
            self.assertIn(word, got["reason"], word)
            self.assertEqual(board_shas(b.dir), before, word)

    def test_fallback_role_reads_only(self):
        """pr-snap の後に作業ツリーを変えて受け付け → ok false、文に「作業ツリーを変えた」、盤面は前のまま"""
        b = self.fallen()
        prcheck.snapshot(b.dir, self.repo, opener=opener)
        before = board_shas(b.dir)
        (self.repo / "stats.py").write_text("changed\n", encoding="utf-8")
        got = prcheck.take(b.dir, reply("pr_ok.json"), self.repo, opener=opener)
        self.assertFalse(got["ok"])
        self.assertIn("作業ツリーを変えた", got["reason"])
        self.assertEqual(board_shas(b.dir), before)
        (self.repo / "new.txt").write_text("x\n", encoding="utf-8")   # 未追跡のファイルを足すのも同じ
        (self.repo / "stats.py").write_text("def mean(xs):\n    return sum(xs)\n", encoding="utf-8")
        self.assertFalse(prcheck.take(b.dir, reply("pr_ok.json"), self.repo, opener=opener)["ok"])

    def test_ignored_paths_added_or_removed_rejected(self):
        """pr-snap の後に git が無視するパスを足す・消す（porcelain は綺麗なまま）→ ok false、文に増えた・消えたパス。
        作業ツリーの写しは accept.tree_state（blk-ci の受け付けと同じ 1 本）"""
        b = self.fallen()
        (self.repo / ".git" / "info" / "exclude").write_text("build/\nold.cache\n", encoding="utf-8")
        (self.repo / "old.cache").write_text("x\n", encoding="utf-8")
        prcheck.snapshot(b.dir, self.repo, opener=opener)
        before = board_shas(b.dir)
        (self.repo / "build").mkdir()
        (self.repo / "build" / "out.o").write_text("x\n", encoding="utf-8")
        self.assertEqual(self.git("status", "--porcelain"), "")
        got = prcheck.take(b.dir, reply("pr_ok.json"), self.repo, opener=opener)
        self.assertFalse(got["ok"])
        self.assertIn("作業ツリーを変えた", got["reason"])
        self.assertIn("build/", got["reason"])
        self.assertEqual(board_shas(b.dir), before)
        shutil.rmtree(self.repo / "build")
        aside = self.repo / ".git" / "old.cache.aside"   # 名前を戻すだけなら stat の印（mtime・ino）も元のまま
        (self.repo / "old.cache").rename(aside)
        got = prcheck.take(b.dir, reply("pr_ok.json"), self.repo, opener=opener)
        self.assertFalse(got["ok"])
        self.assertIn("old.cache", got["reason"])
        aside.rename(self.repo / "old.cache")
        self.assertTrue(prcheck.take(b.dir, reply("pr_ok.json"), self.repo, opener=opener)["ok"])

    def test_head_move_rejected(self):
        """pr-snap の後に別の commit へ checkout（gh pr checkout と同じ動き。作業ツリーは綺麗なまま）→ ok false、
        文に HEAD の動き。枝だけ替える（同じ commit の別の枝・切り離した HEAD）も拒む。元に戻せば通る"""
        b = self.fallen()
        main = self.git("symbolic-ref", "--short", "HEAD").strip()
        self.git("switch", "-q", "-c", "other")
        self.git("commit", "-q", "--allow-empty", "-m", "other")
        self.git("switch", "-q", main)
        prcheck.snapshot(b.dir, self.repo, opener=opener)
        before = board_shas(b.dir)
        for move in (["checkout", "-q", "other"], ["checkout", "-q", "-b", "same-commit", main], ["checkout", "-q", "--detach", main]):
            self.git(*move)
            self.assertEqual(self.git("status", "--porcelain"), "")
            got = prcheck.take(b.dir, reply("pr_ok.json"), self.repo, opener=opener)
            self.assertFalse(got["ok"], move)
            self.assertIn("作業ツリーを変えた", got["reason"])
            self.assertIn("head" if move[2] == "other" else "ref", got["reason"])
            self.assertEqual(board_shas(b.dir), before, move)
            self.git("checkout", "-q", main)
        self.assertTrue(prcheck.take(b.dir, reply("pr_ok.json"), self.repo, opener=opener)["ok"])

    def test_content_reject_leaves_board(self):
        """型の崩れた返答 → ok false（写しの型の文）、盤面は前のまま"""
        b = self.fallen()
        prcheck.snapshot(b.dir, self.repo, opener=opener)
        before = board_shas(b.dir)
        bad = reply("pr_ok.json")
        del bad["listed"]
        got = prcheck.take(b.dir, bad, self.repo, opener=opener)
        self.assertFalse(got["ok"])
        self.assertIn("型", got["reason"])
        self.assertEqual(board_shas(b.dir), before)

    def test_take_without_snapshot_is_gap(self):
        """pr-snap が走っていない（写しが無い）→ BoardGap（回す側の誤り。役に返しても直らない）"""
        b = self.fallen()
        with self.assertRaises(BoardGap):
            prcheck.take(b.dir, reply("pr_ok.json"), self.repo, opener=opener)

    def test_accept_script_exit_2_on_wiring_error(self):
        """盤面の無い置き場・環境変数の欠け → 2、標準出力は空（回す側の誤り。TA19）"""
        empty = self.tmp / "empty-art"
        empty.mkdir()
        r = run_script("accept", {"INPUTS_REPLY": json.dumps(reply("pr_ok.json")), "ARTIFACTS_DIR": str(empty)})
        self.assertEqual((r.returncode, r.stdout), (2, ""), r.stderr)
        r = run_script("accept", {"ARTIFACTS_DIR": str(empty)})
        self.assertEqual((r.returncode, r.stdout), (2, ""))
        self.assertIn("INPUTS_REPLY", r.stderr)

    def test_accept_script_unreadable_reply(self):
        """返答が JSON でない・オブジェクトでない → 0 で ok false（中身の誤り。役に返す）。本文（返答の頭の生の字。$ が入りうる）は
        reason_file に字のまま書く"""
        for raw in ("not json $judge.output.pass", '["$ARTIFACTS_DIR"]'):
            with self.subTest(raw):
                r = run_script("accept", {"INPUTS_REPLY": raw, "ARTIFACTS_DIR": str(self.tmp)})
                self.assertEqual(r.returncode, 0, r.stderr)
                got = json.loads(r.stdout)
                self.assertFalse(got["ok"])
                self.assertEqual(pathlib.Path(got["reason_file"]).read_text(encoding="utf-8"), got["reason"])

    def test_accept_script_reject_writes_reason_file(self):
        """take の拒否（作業ツリーの変化）も reason_file を出し、中身は本文と字のまま同じ。通れば reason_file は空"""
        b = self.fallen()
        env = {"ARTIFACTS_DIR": str(self.art)}
        self.assertEqual(run_script("snap", env, cwd=self.repo).returncode, 0)
        (self.repo / "new.txt").write_text("x\n", encoding="utf-8")
        r = run_script("accept", {**env, "INPUTS_REPLY": json.dumps(reply("pr_ok.json"))}, cwd=self.repo)
        self.assertEqual(r.returncode, 0, r.stderr)
        got = json.loads(r.stdout)
        self.assertFalse(got["ok"])
        self.assertIn("作業ツリーを変えた", got["reason"])
        self.assertEqual(pathlib.Path(got["reason_file"]).read_text(encoding="utf-8"), got["reason"])
        (self.repo / "new.txt").unlink()
        r = run_script("accept", {**env, "INPUTS_REPLY": json.dumps(reply("pr_ok.json"))}, cwd=self.repo)
        self.assertEqual(r.returncode, 0, r.stderr)
        got = json.loads(r.stdout)
        self.assertEqual((got["ok"], got["reason_file"]), (True, ""))
        self.assertTrue(b.dir.is_dir())

    def test_accept_script_dollar_board_stops(self):
        """盤面を解決した後のパスが $ を含む → 2、標準出力は空（reason_file のパスが置き換えに通る）。handed_over の早い拒否も同じ"""
        art = self.tmp / "a$WORKFLOW_ID"
        art.mkdir()
        for name in ("pr_ok.json", "pr_handed_over.json"):
            with self.subTest(name):
                r = run_script("accept", {"INPUTS_REPLY": json.dumps(reply(name)), "ARTIFACTS_DIR": str(art)})
                self.assertEqual((r.returncode, r.stdout), (2, ""), r.stderr)
                self.assertIn("ARTIFACTS_DIR", r.stderr)

    def test_tree_change_names_the_changed_field(self):
        """porcelain の行が前後で同じ変化も、拒否の文が変わった欄を名指す（無視されるパスの増えた／消えた・中身だけの変化）"""
        b = self.fallen()
        (self.repo / ".git" / "info").mkdir(exist_ok=True)
        (self.repo / ".git" / "info" / "exclude").write_text("*.log\n", encoding="utf-8")
        (self.repo / "stats.py").write_text("def mean(xs):\n    return 0\n", encoding="utf-8")   # 起こす前から変更済み
        prcheck.snapshot(b.dir, self.repo, opener=opener)
        (self.repo / "run.log").write_text("x\n", encoding="utf-8")
        got = prcheck.take(b.dir, reply("pr_ok.json"), self.repo, opener=opener)
        self.assertFalse(got["ok"])
        self.assertIn("git が無視するパス: 増えた ['run.log'] 消えた []", got["reason"])
        self.assertNotIn("git status --porcelain: 役を起こす前", got["reason"])
        (self.repo / "run.log").unlink()
        (self.repo / "stats.py").write_text("def mean(xs):\n    return 1\n", encoding="utf-8")
        got = prcheck.take(b.dir, reply("pr_ok.json"), self.repo, opener=opener)
        self.assertFalse(got["ok"])
        self.assertIn("中身が変わった", got["reason"])
        self.assertNotIn("git status --porcelain: 役を起こす前", got["reason"])

    def test_no_conflicts_reply_accepted(self):
        """任せ先の役が同等のコマンドで見て交差 0（GitHub でない remote）→ 通る、素材は clean"""
        b = self.pr_ready(remote="https://git.example.com/o/r.git")
        self.assertTrue(prcheck.run_helper(b)["role_needed"])
        prcheck.snapshot(b.dir, self.repo, opener=opener)
        got = prcheck.take(b.dir, reply("pr_no_conflicts.json"), self.repo, opener=opener)
        self.assertTrue(got["ok"], got)
        self.assertEqual(opener(b.dir).record["materials"]["parallel_pr"]["status"], "clean")


# ---------------------------------------------------------------- 写し・渡す物・集める節
class SnapCollectCase(PrCase):
    def test_snapshot_and_brief_in_round_work_dir(self):
        """pr-snap: 作業ツリーの写しと役への渡し物を今の周の作業ファイル（b.work）に書く。渡し物に交差を取る集合と落ちた理由"""
        b = self.fallen()
        got = prcheck.snapshot(b.dir, self.repo, opener=opener)
        self.assertTrue(got["ok"])
        self.assertEqual(pathlib.Path(got["snapshot_file"]), b.work(prcheck.SNAPSHOT))
        self.assertEqual(pathlib.Path(got["brief_file"]), b.work(prcheck.BRIEF))
        brief = json.loads(pathlib.Path(got["brief_file"]).read_text(encoding="utf-8"))
        self.assertEqual(brief["changed_files"], ["stats.py"])
        self.assertEqual(brief["cwd"], str(self.repo.resolve()))
        self.assertEqual(brief["base"], self.git("rev-parse", "HEAD").strip())
        self.assertEqual(brief["fallback"], b.rd["instances"][prcheck.NODE]["engine_fallback"])
        self.assertEqual(brief["node"], prcheck.NODE)

    def test_snapshot_marks_launched(self):
        """pr-snap は役を起こす前の最後の節なので、起こした印（mark_launched。盤面の T8 の決まり）を今の試行に置き、試行と
        役が書く置き場を返す。2 度呼んでも印は同じ（Archon の再開で pr-snap が走り直しても）"""
        b = self.fallen()
        attempt = b.rd["instances"][prcheck.NODE]["attempts"]
        got = prcheck.snapshot(b.dir, self.repo)
        inst = opener(b.dir).rd["instances"][prcheck.NODE]
        self.assertTrue(inst.get("launched_at"))
        self.assertEqual((got["attempt"], got["out_path"]), (attempt, inst["out_path"]))
        again = prcheck.snapshot(b.dir, self.repo)
        self.assertEqual(opener(b.dir).rd["instances"][prcheck.NODE]["launched_at"], inst["launched_at"])
        self.assertEqual(again["attempt"], attempt)

    def test_snapshot_refuses_when_not_fallen(self):
        """任せ先に落ちていない節に pr-snap → BoardGap（start が pr_go を偽にした run では blk-pr を開かない）"""
        b = self.pr_ready()
        with self.assertRaises(BoardGap):
            prcheck.snapshot(b.dir, self.repo, opener=opener)

    def test_collect_counts_and_drafts(self):
        b = self.fallen()
        prcheck.snapshot(b.dir, self.repo, opener=opener)
        two = reply("pr_ok.json")
        two["conflicts"].append({"pr": "9", "files": ["stats.py"], "handed_over": False})
        self.assertTrue(prcheck.take(b.dir, two, self.repo, opener=opener)["ok"])
        got = prcheck.collect(b.dir, opener=opener)
        self.assertEqual({k: got[k] for k in ("ok", "conflicts", "drafts", "material_status", "excluded", "reads_file")},
                         {"ok": True, "conflicts": 2, "drafts": 1, "material_status": "found", "excluded": 1, "reads_file": ""})
        self.assertTrue(pathlib.Path(got["pr_file"]).is_file())
        self.assertEqual(prcheck.drafts(b.dir, opener=opener),
                         [{"pr": "7", "files": ["stats.py"], "note": two["conflicts"][0]["note"]}])
        reads = opener(b.dir).work("reads-pr-check.json")
        reads.write_text("{}", encoding="utf-8")
        self.assertEqual(prcheck.collect(b.dir, opener=opener)["reads_file"], str(reads))

    def test_collect_not_taken(self):
        """受けていない盤面の collect は ok false（件数は 0・パスは空）"""
        got = prcheck.collect(self.fallen().dir, opener=opener)
        self.assertEqual((got["ok"], got["conflicts"], got["excluded_file"]), (False, 0, ""))

    def test_scripts_success_path(self):
        """本物の entry.open_board で、スクリプトを子で起こす: pr-snap → pr-accept（cwd は対象のリポジトリ）→ collect が
        ok true・drafts 1・excluded 1 を 1 行で出す"""
        b = self.fallen()
        env = {"ARTIFACTS_DIR": str(self.art)}
        r = run_script("snap", env, cwd=self.repo)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(json.loads(r.stdout)["ok"])
        r = run_script("accept", {**env, "INPUTS_REPLY": json.dumps(reply("pr_ok.json"))}, cwd=self.repo)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(json.loads(r.stdout)["ready"], ["p0.premises"])
        r = run_script("collect", env)
        self.assertEqual(r.returncode, 0, r.stderr)
        got = json.loads(r.stdout)
        self.assertEqual((got["ok"], got["drafts"], got["excluded"]), (True, 1, 1))
        self.assertTrue(pathlib.Path(got["excluded_file"]).is_file())

    def test_collect_script_wiring_errors(self):
        """集める節のスクリプト: ARTIFACTS_DIR が無い・盤面を開けない → 2、標準出力は空"""
        r = run_script("collect", {})
        self.assertEqual((r.returncode, r.stdout), (2, ""))
        empty = self.tmp / "empty-art"
        empty.mkdir()
        r = run_script("collect", {"ARTIFACTS_DIR": str(empty)})
        self.assertEqual((r.returncode, r.stdout), (2, ""), r.stderr)


# ---------------------------------------------------------------- 印・指示書・下げた物の宣言・スクリプトの形
class DeclaredCase(unittest.TestCase):
    def test_output_format_marked_no_post(self):
        """役の output_format は写しの schema に works だけの欄 excluded（必須）を足し、印 works-node: pr-check no-post を
        付けた物（TA20）。excluded と印を外せば写しの schema そのもの"""
        fmt = prcheck.OUTPUT_FORMAT
        self.assertEqual(fmt["description"], "works-node: pr-check no-post")
        self.assertIn("excluded", fmt["required"])
        self.assertEqual(fmt["properties"]["excluded"], prcheck.EXCLUDED_SCHEMA)

        def unworks(f):
            f = json.loads(json.dumps(f))
            f.pop("description", None)
            del f["properties"]["excluded"]
            f["required"].remove("excluded")
            return f
        self.assertEqual(unworks(fmt), role_schema(prcheck.NODE))
        try:
            import node_marker   # 線 A Task 2。入った後は印の読み方でも確かめる
        except ModuleNotFoundError:
            return
        self.assertEqual(unworks(node_marker.strip(fmt)), role_schema(prcheck.NODE))
        self.assertEqual(node_marker.parse(fmt["description"])["flags"], frozenset({"no-post"}))

    def test_prompt_step6_no_post(self):
        """指示書は 6 段を持ち、6 段目は投稿せずに下書きを note に・handed_over false。gh は -R、書き込みの gh を打つな"""
        text = (BLOCK / "commands" / "pr-check.md").read_text(encoding="utf-8")
        steps = [ln for ln in text.splitlines() if ln[:2] in {f"{i}." for i in range(1, 10)}]
        self.assertEqual([s[:2] for s in steps], ["1.", "2.", "3.", "4.", "5.", "6."])
        six = steps[5]
        for word in ("投稿せず", "note", "`handed_over: false`"):
            self.assertIn(word, six)
        self.assertIn("スコープから外し", six)
        self.assertIn("`excluded`", six)
        forbid = [ln for ln in text.splitlines() if "打つな" in ln]
        self.assertEqual(len(forbid), 1, forbid)
        for word in prcheck.GH_DENY + prcheck.GIT_DENY:
            self.assertIn(f"`{word}`", forbid[0])
        self.assertIn("`gh api`（読むだけの形も含めて丸ごと", forbid[0])
        # 読む gh は包みの許す物の口（"$WORKS_GH"。素の gh は包みが拒む）を通す。指示書の "$WORKS_GH" のコマンドは全部、
        # GH_READ の語で -R <owner/repo> つき（2・5・6 段と、打ってよい物の一覧の 3 つ）。素の `gh …` は禁じる語か、使うなと名指した gh repo view だけ
        self.assertEqual((prcheck.GH_ENV, prcheck.GH_WRAPPER), ("WORKS_GH", '"$WORKS_GH"'))
        wrapped = re.findall(r'`("\$WORKS_GH" [^`]*)`', text)
        self.assertEqual(len(wrapped), 6, wrapped)
        for cmd in wrapped:
            self.assertTrue(cmd.startswith(tuple(f"{prcheck.GH_WRAPPER} {w} " for w in prcheck.GH_READ)), cmd)
            self.assertIn(" -R <owner/repo>", cmd, cmd)
        for cmd in re.findall(r"`(gh [^`]*)`", text):
            self.assertTrue(cmd in prcheck.GH_DENY or cmd == "gh repo view", cmd)
        self.assertIn("素の `gh`", text)
        self.assertIn("$pr-snap.output.brief_file", text)
        # 理由の本文は貼らない（Archon は $LOOP_PREV で貼った中身をもう一度置き換えに通す）。パスだけを貼って Read させる
        self.assertEqual(re.findall(r"\$LOOP_PREV\.[\w.-]*", text), ["$LOOP_PREV.pr-accept.output.reason_file"])

    def test_downgrades_declared(self):
        """darkfactory/downgrades.json はちょうど 1 行（p0.parallel_pr）。頭の行の部品は「下げている所: 1 個」"""
        rows = json.loads((PACK / "darkfactory" / "downgrades.json").read_text(encoding="utf-8"))
        self.assertEqual(rows, [{"node": "p0.parallel_pr",
                                 "what": "担当の PR へ申し送りを投稿しない（下書きを報告の冒頭 1 に載せる）",
                                 "versus": "review-graph は任せ先の役が gh で投稿する"}])
        self.assertEqual(prcheck.downgrades(), rows)
        self.assertEqual(prcheck.head_downgrades(), "下げている所: 1 個")
        self.assertIn(rows[0]["node"], GRAPH["nodes"])

    def test_downgrades_shape_checked(self):
        tmp = pathlib.Path(tempfile.mkdtemp(prefix="blk-pr-dg-"))
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        (tmp / "l").mkdir()
        self.assertEqual(prcheck.downgrades("l", pack=tmp), [])
        self.assertEqual(prcheck.head_downgrades("l", pack=tmp), "下げている所: 0 個")
        for bad in ([{"node": "p0.parallel_pr"}], [{"node": "no.such", "what": "w", "versus": "v"}], {"x": 1},
                    [{"node": "p0.parallel_pr", "what": "", "versus": "v"}]):
            (tmp / "l" / "downgrades.json").write_text(json.dumps(bad), encoding="utf-8")
            with self.assertRaises(BoardGap, msg=bad):
                prcheck.downgrades("l", pack=tmp)

    def test_scripts_declare_inputs(self):
        """各スクリプトは読む INPUTS_* の名前の組を定数 INPUTS に持つ（TA16。Task 17 が YAML の with: と突き合わせる）"""
        want = {"snap": (), "accept": ("INPUTS_REPLY",), "reads": ("INPUTS_MUST",), "collect": ()}
        self.assertEqual(sorted(p.stem for p in SCRIPTS.glob("*.py")), sorted(want))
        for name, inputs in want.items():
            tree = ast.parse((SCRIPTS / f"{name}.py").read_text(encoding="utf-8"))
            got = [ast.literal_eval(n.value) for n in tree.body if isinstance(n, ast.Assign)
                   and [getattr(t, "id", None) for t in n.targets] == ["INPUTS"]]
            self.assertEqual(got, [inputs], name)

    def test_reads_script_names(self):
        """読んだ証拠の節（pr-reads）が渡す名前: 役 pr-check・include pr-checking・輪 pr-loop・節 pr-check"""
        self.assertEqual(prcheck.READS, ("pr-check", "pr-checking", "pr-loop", "pr-check"))
        self.assertIn("reads.main_for(*prcheck.READS)", (SCRIPTS / "reads.py").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
