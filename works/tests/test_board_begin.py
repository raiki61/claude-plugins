"""盤面の入口 DiskBoard.begin と p0.base の返答を機械が組む base_output の試験（仕様 5 節）。

表は試験用の tests/boards/tables/entry-line.json（p0.base は machine、p0.local_checks・p4.ci は engine_run（fallback machine）、
判定・修正・差分の審査の 8 節は role、p2.history は role（skippable）、機械の節は builtin、他は absent）。
使い捨ての git リポジトリ（宣言 .review-checks.json の在る物と無い物）で回す。最後の試験は手本（test_request_entry の
最初の Run）の最初の手の前のリポジトリで begin し、同じ Run の役の返答で 1 周を記録まで回す。
"""
import dataclasses
import hashlib
import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

sys.dont_write_bytecode = True
HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import boardreplay as R  # noqa: E402  （board と写しの engine を sys.path に足す）
from board import (BoardGap, DiskBoard, NodeEntry, NodeTable, base_output, graph_expanded)  # noqa: E402
import engine.util as engine_util  # noqa: E402
from engine.board import Board as EngineBoard  # noqa: E402
from engine.schema import validate_schema  # noqa: E402
from engine.util import Reject  # noqa: E402

TABLES = HERE / "boards" / "tables"
ENTRY = NodeTable.load(TABLES / "entry-line.json")
GIT_ID = ["-c", "user.email=t@t", "-c", "user.name=t", "-c", "commit.gpgsign=false", "-c", "core.hooksPath=/dev/null"]
GREEN = {"suite": [{"name": "suite", "argv": [sys.executable, "-c", "print('1 passed')"]}]}
ITEMS = [{"where": "a.txt", "text": "上限を掛けたい（検査用の依頼）"}]
ORIGIN = "利用者の依頼（検査用）"
# 手本の Run の 1 周目で、表で role の節の受け付けの手と engine_run の手（どちらも通った物）
SINGLE_RUN = ("test_request_entry", "1")


def git(repo, *args):
    return subprocess.run(["git", *GIT_ID, "-C", str(repo), *args], capture_output=True, text=True, check=True).stdout.strip()


def read(p):
    return json.loads(pathlib.Path(p).read_text(encoding="utf-8"))


def make_repo(top, decl=True):
    """使い捨ての git リポジトリ: commit 2 つ（a.txt）、decl なら宣言（緑の 1 段）も commit、共通の git の置き場に方針の文書"""
    repo = pathlib.Path(top) / "repo"
    repo.mkdir(parents=True)
    git(repo, "init", "-q")
    (repo / "a.txt").write_text("a\n", encoding="utf-8")
    if decl:
        (repo / ".review-checks.json").write_text(json.dumps(GREEN), encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "seed")
    (repo / "a.txt").write_text("a\nb\n", encoding="utf-8")
    git(repo, "commit", "-q", "-am", "second")
    pol = repo / ".git" / "graphloops"
    pol.mkdir()
    (pol / "policy.md").write_text("方針（検査用）\n", encoding="utf-8")
    return repo


def with_entry(table, nid, **entry):
    nodes = dict(table.nodes)
    nodes[nid] = NodeEntry(**entry)
    return dataclasses.replace(table, nodes=nodes)


def pending(b, nid):
    return next((i for i in b.rd["instances"].values() if i["node"] == nid and i["status"] == "pending"), None)


class BeginCase(unittest.TestCase):
    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp(prefix="board-begin-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        cwd = engine_util.GIT_CWD
        self.addCleanup(setattr, engine_util, "GIT_CWD", cwd)
        self.repo = make_repo(self.tmp)

    def begin(self, name="board", repo=None, table=ENTRY, items=ITEMS, **kw):
        kw.setdefault("base_rev", "")
        kw.setdefault("request_text", "この変更をレビュー")
        return DiskBoard.begin(self.tmp / "art" / name, repo=repo or self.repo, table=table, items=items, origin=ORIGIN, **kw)

    def to_judge(self, b, p):
        """ready の engine_run の節（Progress.run_engine）を全部 run_engine して settle する、を run_engine が空になるまで
        （線 A・B の start と同じ）。最後の Progress を返す"""
        while p["run_engine"]:
            for nid in p["run_engine"]:
                self.assertTrue(b.run_engine(nid)["ok"], nid)
            p = b.settle()
        return p

    # -- 入口
    def test_begin_ready_local_checks_then_judge(self):
        b, p = self.begin()
        self.assertEqual(p["ready"], ["p0.local_checks"])
        self.assertEqual(p["run_engine"], ["p0.local_checks"])
        self.assertIsNone(p["asking"])
        self.assertIsNone(p["halted"])
        self.assertEqual(b.node_state("p0.base"), "done")
        got = b.run_engine("p0.local_checks")
        self.assertTrue(got["ok"], got)
        self.assertEqual(b.record["process"]["checks"]["p0.local_checks"]["by"], "engine")
        p = b.settle()
        self.assertEqual(p["ready"], ["p2.diagnose"])
        self.assertEqual(p["run_engine"], [])
        # ディスクから開き直しても同じ
        again = DiskBoard.open(b.dir, table=ENTRY)
        self.assertEqual(again._progress([])["ready"], ["p2.diagnose"])

    def test_begin_p1_na_like_engine(self):
        b, p = self.begin()
        self.to_judge(b, p)
        # 手本（engine）の同じ Run の na の理由と同じ文
        rs = R.load_runs(*SINGLE_RUN[:1])[SINGLE_RUN[1]]
        golden = {s["na"]["node"]: s["na"]["why"] for s in rs if s["kind"] == "na" and s["seq"] < 30}
        for nid in ("p1.local_review", "p1.hygiene", "p1.consistency_bypass"):
            why = b.rd["na"].get(nid)
            self.assertTrue(why and why.startswith("cond not_request_entry:"), (nid, why))
            self.assertEqual(why, golden[nid], nid)
        self.assertEqual(b.record["process"]["request_entry"], {"origin": ORIGIN})

    def test_begin_absent_skipped_and_listed(self):
        b, p = self.begin()
        self.to_judge(b, p)
        self.assertEqual(b.state["works"]["not_in_line"], ENTRY.absent())
        self.assertEqual({a["node"] for a in ENTRY.absent()},
                         {n for n, e in ENTRY.nodes.items() if e.by == "absent"})
        # 判定の前に評価される absent の節は、どれも周の箱の skipped（表の理由）か na（条件の理由）
        before_judge = [n for n in ENTRY.nodes if ENTRY.nodes[n].by == "absent" and (n.startswith("p0.") or n.startswith("p1."))]
        self.assertTrue(before_judge)
        for nid in before_judge:
            self.assertTrue(nid in b.rd["skipped"] or nid in b.rd["na"], nid)
            if nid in b.rd["skipped"]:
                self.assertEqual(b.rd["skipped"][nid], ENTRY.nodes[nid].reason)
        self.assertIn("p0.premises", b.rd["skipped"])   # 条件の無い absent の節は必ず skipped

    def test_begin_freezes_revision(self):
        # 作業ツリーを汚す（追跡中の変更と未追跡の新規）。版は作業ツリーの今の姿を丸ごと固める
        (self.repo / "a.txt").write_text("a\nb\nc\n", encoding="utf-8")
        (self.repo / "new.txt").write_text("新規\n", encoding="utf-8")
        b, p = self.begin()
        self.assertNotIn("review_rev", b.state["inputs"])   # 版を固める p1.worktree_before は spec の節を通して修正前の CI を待つ
        self.to_judge(b, p)
        rev = b.state["inputs"]["review_rev"]
        self.assertTrue(rev)
        self.assertEqual(rev, b.loop_state["head_revs"]["1"])
        idx = self.tmp / "index"
        shutil.copy2(self.repo / ".git" / "index", idx)
        env = {**os.environ, "GIT_INDEX_FILE": str(idx)}
        subprocess.run(["git", "-C", str(self.repo), "add", "-A"], env=env, check=True)
        tree = subprocess.run(["git", "-C", str(self.repo), "write-tree"], env=env, capture_output=True, text=True,
                              check=True).stdout.strip()
        self.assertEqual(git(self.repo, "rev-parse", f"{rev}^{{tree}}"), tree)
        patch = b.dir / "diff-r1.patch"
        self.assertTrue(patch.is_file())
        self.assertIn(b"new.txt", patch.read_bytes())

    def test_begin_records_request(self):
        b, _ = self.begin()
        proc = read(b.dir / "record.json")["process"]
        self.assertEqual(len(proc["request_findings"]), 1)
        self.assertEqual(proc["request_findings"][0]["findings"], ITEMS)
        self.assertEqual(proc["request_findings"][0]["origin"], ORIGIN)
        self.assertEqual(proc["request_entry"], {"origin": ORIGIN})
        self.assertEqual(read(b.dir / "state.json")["inputs"]["request"], "この変更をレビュー")

    def test_begin_policy_fixed(self):
        b, _ = self.begin()
        pol = read(b.dir / "record.json")["process"]["policy"]
        src = self.repo / ".git" / "graphloops" / "policy.md"
        self.assertEqual(pol["sha256"], hashlib.sha256(src.read_bytes()).hexdigest())
        copy = pathlib.Path(pol["copy"])
        self.assertEqual(copy.parent, b.dir / "policy")
        self.assertEqual(copy.read_bytes(), src.read_bytes())

    def test_begin_idempotent(self):
        b1, p1 = self.begin()
        rec = read(b1.dir / "record.json")
        b2, p2 = self.begin()
        self.assertEqual(b2.dir, b1.dir)
        self.assertEqual(sorted(x.name for x in (self.tmp / "art").iterdir()), ["board"])
        self.assertEqual(len(b2.record["process"]["request_findings"]), 1)
        self.assertEqual(p2["ready"], p1["ready"])
        self.assertEqual(read(b2.dir / "record.json"), rec)   # 2 度目は作らず・積まず・進めない（settle は進む物が無い）
        with self.assertRaises(BoardGap) as cm:
            self.begin(items=[{"where": "b.txt", "text": "違う依頼"}])
        self.assertIn("依頼", str(cm.exception))
        self.assertEqual(len(read(b1.dir / "record.json")["process"]["request_findings"]), 1)
        # 違う表で作った盤面は開き直さない
        with self.assertRaises(BoardGap):
            self.begin(table=with_entry(ENTRY, "p2.history", by="role"))

    def test_begin_resumes_after_bad_request(self):
        # 依頼の形が悪くて止まった begin は、置き場を残す（engine の init と add と同じ）。直した依頼で呼び直せば続きから
        with self.assertRaises(Reject):
            self.begin(items=[{"where": "x", "text": "y", "severity": "block"}])
        self.assertTrue((self.tmp / "art" / "board" / "state.json").is_file())
        b, p = self.begin()
        self.assertEqual(len(b.record["process"]["request_findings"]), 1)
        self.assertEqual(p["ready"], ["p0.local_checks"])

    def test_begin_stop_after_round(self):
        b, _ = self.begin(stop_after_round=1, max_rounds=3)
        st = read(b.dir / "state.json")
        self.assertEqual(st["stop_after_round"], 1)
        self.assertEqual(st["max_rounds"], 3)
        with self.assertRaises(BoardGap):
            self.begin("b2", stop_after_round=0)
        self.assertFalse((self.tmp / "art" / "b2").exists())

    def test_begin_needs_machine_base(self):
        with self.assertRaises(BoardGap):
            self.begin(table=with_entry(ENTRY, "p0.base", by="role"))
        self.assertFalse((self.tmp / "art" / "board").exists())

    def test_begin_without_declaration(self):
        repo = make_repo(self.tmp / "nodecl", decl=False)
        b, p = self.begin(repo=repo)
        self.assertEqual(p["run_engine"], ["p0.local_checks"])
        got = b.run_engine("p0.local_checks")
        self.assertFalse(got["ok"])
        self.assertIn("fallback", got)
        self.assertEqual(b.record["process"]["checks"]["p0.local_checks"]["by"], "role")
        p = b.settle()
        # 任せ先に落ちた節は ready に残るが、run_engine の一覧には無い（表の fallback の持ち主が done で渡す）
        self.assertEqual(p["ready"], ["p0.local_checks"])
        self.assertEqual(p["run_engine"], [])
        inst = pending(b, "p0.local_checks")
        b.mark_launched("p0.local_checks", inst["attempts"])
        p = b.done("p0.local_checks", {"material": {"status": "clean", "count": 0, "checked": "test_cmd を走らせた（検査用）"}})
        self.assertEqual(p["ready"], ["p2.diagnose"])
        self.assertEqual(p["run_engine"], [])

    def test_begin_ready_with_parallel_pr(self):
        # p0.parallel_pr は p1.worktree_before の後（版を固める節は spec の節を通して p0.local_checks を待つ）。start は
        # run_engine が空になるまで「全部 run_engine → settle」を繰り返す
        table = with_entry(ENTRY, "p0.parallel_pr", by="engine_run", fallback="role")
        b, p = self.begin(table=table)
        self.assertEqual(p["run_engine"], ["p0.local_checks"])
        self.assertTrue(b.run_engine("p0.local_checks")["ok"])
        p = b.settle()
        self.assertIn("p0.parallel_pr", p["ready"])
        self.assertEqual(p["run_engine"], ["p0.parallel_pr"])
        # remote が GitHub でないので計画が任せ先へ落ちる。落ちた節は ready に残り、run_engine には無い（役が done で渡す）
        got = b.run_engine("p0.parallel_pr")
        self.assertFalse(got["ok"])
        self.assertIn("fallback", got)
        p = b.settle()
        self.assertEqual(p["ready"], ["p0.parallel_pr"])
        self.assertEqual(p["run_engine"], [])
        self.assertNotIn("p2.diagnose", p["ready"])   # p1.consistency_bypass（na）が p0.parallel_pr を待つ

    def test_absent_cond_reading_absent_output(self):
        # p0.purpose_review の条件は、このラインに無い p0.purpose の出力を default 無しで読む（engine なら die）——測らずに省く
        b, p = self.begin()
        self.assertTrue(b.run_engine("p0.local_checks")["ok"])
        p = b.settle()
        self.assertEqual(b.rd["skipped"]["p0.purpose_review"], ENTRY.nodes["p0.purpose_review"].reason)
        self.assertNotIn("p0.purpose_review", b.rd["na"])
        self.assertTrue(any(n.startswith("p0.purpose_review: 条件 purpose_review_due は、このラインに無い節 p0.purpose")
                            for n in p["notes"]), p["notes"])
        rows = [json.loads(ln) for ln in (b.dir / "trace.jsonl").read_text(encoding="utf-8").splitlines()]
        self.assertIn({"node": "p0.purpose_review", "unmeasured": ["p0.purpose"]},
                      [{k: r[k] for k in ("node", "unmeasured")} for r in rows if r.get("op") == "skip" and "unmeasured" in r])
        # 表で p0.purpose が役なら（出力が在りうる）、条件は engine と同じく測る（absent の節でも）
        self.assertEqual(b._blind_reads("p0.purpose_review"), ["p0.purpose"])
        other = DiskBoard.open(b.dir, table=with_entry(ENTRY, "p0.purpose", by="role"))
        self.assertEqual(other._blind_reads("p0.purpose_review"), [])

    # -- 盤面の口の足し算（線 A・B への申し送り）
    def test_validator_hook_declared(self):
        calls = []

        def hook_runner(b, target):
            calls.append(target)
            return EngineBoard.run_validator(b, target)

        b, _ = self.begin(validator_runner=hook_runner)
        self.assertTrue(b.state["works"]["validator_hook"])
        self.assertEqual(read(b.dir / "state.json")["works"]["validator_hook"], b.state["works"]["validator_hook"])
        with self.assertRaises(BoardGap) as cm:
            DiskBoard.open(b.dir, table=ENTRY)
        self.assertIn("validator_runner", str(cm.exception))
        again = DiskBoard.open(b.dir, table=ENTRY, validator_runner=hook_runner)
        self.assertIs(again.validator_runner, hook_runner)
        # 包みの無い盤面は宣言を持たず、渡さずに開ける
        plain, _ = self.begin("plain")
        self.assertNotIn("validator_hook", plain.state["works"])
        DiskBoard.open(plain.dir, table=ENTRY)

    def test_context_of(self):
        b, p = self.begin()
        self.to_judge(b, p)
        self.assertIsNone(b.context_of("p2.diagnose"))
        self.assertEqual(b.context_of("p2.history"), {"same_context_as": "p2.diagnose", "continue_of": None})
        with self.assertRaises(BoardGap):
            b.context_of("no.such")


class BaseOutputCase(unittest.TestCase):
    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp(prefix="board-base-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.repo = make_repo(self.tmp)

    def test_base_output_shape(self):
        schema = graph_expanded()["nodes"]["p0.base"]["schema"]
        out = base_output(self.repo, "HEAD~1")
        self.assertEqual(validate_schema(out, schema), [])
        self.assertEqual(out["method"], "4 依頼者の名指し")
        for k in ("touches_gates", "touches_external_seams", "touches_user_path", "touches_security_surface"):
            self.assertIs(out[k], True, k)
        self.assertEqual(out["base_sha"], git(self.repo, "rev-parse", "HEAD~1"))
        self.assertEqual(out["commits"], 1)
        self.assertIs(out["merge_commit"], False)
        self.assertEqual(out["intent_to_add"], [])
        self.assertEqual(out["material"]["status"], "found")
        self.assertEqual(out["material"]["count"], 1)
        self.assertIn("HEAD~1", out["material"]["detail"])

    def test_base_output_counts_merges(self):
        git(self.repo, "checkout", "-q", "-b", "side", "HEAD~1")
        (self.repo / "s.txt").write_text("s\n", encoding="utf-8")
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-q", "-m", "side")
        git(self.repo, "checkout", "-q", "-")
        git(self.repo, "merge", "-q", "--no-ff", "-m", "merge", "side")
        out = base_output(self.repo, "HEAD~1")
        self.assertIs(out["merge_commit"], True)
        self.assertEqual(out["commits"], 2)

    def test_base_output_empty_rev_is_head(self):
        out = base_output(self.repo, "")
        self.assertEqual(out["base_sha"], git(self.repo, "rev-parse", "HEAD"))
        self.assertEqual(out["commits"], 0)
        self.assertEqual(out["material"]["count"], 0)
        self.assertIn("HEAD", out["material"]["detail"])

    def test_base_output_bad_rev(self):
        for bad in ("no-such-rev", "HEAD~9"):
            with self.assertRaises(Reject) as cm:
                base_output(self.repo, bad)
            self.assertIn(bad, str(cm.exception))


class SingleRoundCase(unittest.TestCase):
    """手本の同じ Run の役の返答で、begin から 1 周を記録まで回す（stop_after_round=1。線 A の 1 周の run の形）"""

    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp(prefix="board-begin-run-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        env = mock.patch.dict(os.environ, R.git_env())
        env.start()
        self.addCleanup(env.stop)
        cwd = engine_util.GIT_CWD
        self.addCleanup(setattr, engine_util, "GIT_CWD", cwd)

    def test_single_round_runs_to_record(self):
        rs = R.load_runs(SINGLE_RUN[0])[SINGLE_RUN[1]]
        places = R.Places(self.tmp)
        repo = R.restore_repo(rs, rs[0]["seq"], self.tmp)
        first_add = next(s for s in rs if s["kind"] == "add" and not s.get("raised"))
        items = places.untokenize(json.loads(first_add["args"]["file_text"]))
        b, p = DiskBoard.begin(places.board, repo=repo, table=ENTRY, items=items, origin=first_add["args"]["reason"],
                               base_rev="", request_text=rs[0]["args"]["request"], stop_after_round=1)
        self.assertEqual(p["run_engine"], ["p0.local_checks"])
        end = next(s["seq"] for s in rs if s["kind"] == "open_round")
        done, ran = [], []
        for s in rs:
            if s["seq"] >= end or s.get("parent") or s.get("raised"):
                continue
            nid = s.get("node")
            if s["kind"] == "engine_run":
                R.restore_repo(rs, s["seq"], self.tmp)
                self.assertIn(nid, b._progress([])["run_engine"], nid)
                got = b.run_engine(nid, runner=R.captured_runner(s, b))
                self.assertTrue(got["ok"], got)
                p = b.settle()
                ran.append(nid)
            elif s["kind"] == "accept" and ENTRY.nodes[nid].by == "role":
                R.restore_repo(rs, s["seq"], self.tmp)
                self.assertIn(nid, p["ready"], (s["seq"], nid, p))
                R.mark(b, nid)
                p = b.done(nid, R.reply(s, b))
                done.append(nid)
        self.assertEqual(ran, ["p0.local_checks", "p4.ci"])
        self.assertEqual(done, ["p2.diagnose", "p2.fix_plan", "p2.plan_review", "p3.fix", "p3.delta_review"])
        self.assertEqual((p["halted"] or {}).get("by"), "stop_after_round", p)
        self.assertEqual(p["ready"], [])
        for nid in ("p4.record", "converge"):
            self.assertEqual(b.node_state(nid), "done", nid)
        self.assertTrue((b.dir / "rounds" / "round-1.json").is_file())
        note = read(b.dir / "rounds" / "works" / "round-1.json")
        self.assertEqual([r["node"] for r in note["not_in_line"]], [a["node"] for a in ENTRY.absent()])
        self.assertEqual(note["checks"]["p4.ci"]["by"], "engine")
        self.assertIn(read(b.dir / "out" / "r1" / "p4.record.json")["exit"], (0, 1))
        self.assertEqual(b.record["process"]["checks"]["p4.ci"]["by"], "engine")
        self.assertEqual(read(b.dir / "state.json")["halted"]["by"], "stop_after_round")
        # 同じ役の会話を続ける節の続け先は、今の周の済んだ判定役の instance
        self.assertEqual(b.context_of("p2.history"), {"same_context_as": "p2.diagnose", "continue_of": "p2.diagnose"})


if __name__ == "__main__":
    unittest.main()
