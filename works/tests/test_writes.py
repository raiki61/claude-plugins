"""書き込みの出どころの突き合わせ（.shared/core/writes.py・record-write.py・包みのフック）と、受け付けが選んだ試験を走らせる口
（tddloop.selected_problems）の検査。

- 包みの設定: hook_settings が書き込みのコマンドを受ければ PostToolUse:Edit|Write|NotebookEdit を足す
- 記録器: Edit・Write・NotebookEdit で 1 行（書いた後の sha）、ほかの道具・置き場の無い起動は 1 バイトも書かない
- 突き合わせ: 記録も申告も無い変更（追跡中・未追跡・消した物）を拒む。記録の後に中身が変わった物も拒む。理由つきの申告は通し、
  記録に残す（後ろの受け付けが同じ申告を求めない）。.archon/ の下は数えない。記録の無い run は知らせつきで通す
- 書く役の返答の形: blk-fix の書く役（tdd・fix・fix-ruled）は欄 bash_writes を持つ。blk-refix の手直しの役は写しの graph の
  schema のままで、記録の無い変更は拒まずに残す（strict=False）
- TDD の輪の段と受け付けの選んだ試験: 記録の無い書き込みで段を拒む。元で赤でなかった試験の赤だけを返す
"""
import hashlib
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

import yaml

ROOT = pathlib.Path(__file__).resolve().parents[1]
CORE = ROOT / ".shared" / "core"
TESTS = pathlib.Path(__file__).resolve().parent
sys.dont_write_bytecode = True
sys.path.insert(0, str(ROOT / "blk-fix" / "lib"))
sys.path.insert(0, str(CORE))
sys.path.insert(0, str(TESTS))

from gitkit import committed_copy, git  # noqa: E402
import adapter  # noqa: E402
import tddloop  # noqa: E402
import writes  # noqa: E402
from test_blk_fix_tdd import CLAMP, MEAN, NEW_TEST, OPEN, SEED, SUITE  # noqa: E402
import hermetic  # noqa: E402

RECORDER = CORE / "record-write.py"
WHY = "整形の道具で 40 ファイルを一度に書き換えた"


def sha(p):
    return hashlib.sha256(pathlib.Path(p).read_bytes()).hexdigest()


def record(log, path, tool="Edit"):
    with open(log, "a", encoding="utf-8") as f:
        f.write(json.dumps({"tool_name": tool, "path": os.path.realpath(str(path)), "file_sha": sha(path)}) + "\n")


class TestHook(unittest.TestCase):
    def test_hook_settings_record_edit_and_write(self):
        s = adapter.hook_settings("py record-read.py sink", "py record-write.py sink")
        post = s["hooks"]["PostToolUse"]
        self.assertEqual([m["matcher"] for m in post], ["Read", "Edit|Write|NotebookEdit"])
        self.assertEqual(post[1]["hooks"], [{"type": "command", "command": "py record-write.py sink"}])
        self.assertEqual([m["matcher"] for m in adapter.hook_settings("c")["hooks"]["PostToolUse"]], ["Read"])

    def test_writes_path_is_next_to_reads(self):
        self.assertEqual(adapter.writes_path("/x", "/h"), adapter.reads_dir("/x", "/h") / "writes.jsonl")

    def run_recorder(self, sink, event):
        return subprocess.run([sys.executable, str(RECORDER), str(sink)], input=json.dumps(event), text=True, encoding="utf-8",
                              capture_output=True, env=hermetic.child_env(**{"PYTHONDONTWRITEBYTECODE": "1"}))

    def test_recorder_writes_path_and_sha_after_write(self):
        with tempfile.TemporaryDirectory() as td:
            sink, f = pathlib.Path(td) / "sink", pathlib.Path(td) / "a.py"
            sink.mkdir()
            f.write_text("x = 1\n", encoding="utf-8")
            for tool in ("Edit", "Write"):
                r = self.run_recorder(sink, {"tool_name": tool, "tool_input": {"file_path": str(f)}, "session_id": "s",
                                             "tool_use_id": "toolu_1"})
                self.assertEqual(r.returncode, 0, r.stderr)
            self.run_recorder(sink, {"tool_name": "NotebookEdit", "tool_input": {"notebook_path": str(f)}})
            rows = [json.loads(ln) for ln in (sink / "writes.jsonl").read_text(encoding="utf-8").splitlines()]
            self.assertEqual([r["tool_name"] for r in rows], ["Edit", "Write", "NotebookEdit"])
            self.assertEqual({r["path"] for r in rows}, {os.path.realpath(str(f))})
            self.assertEqual({r["file_sha"] for r in rows}, {sha(f)})

    def test_subagent_write_lands_in_the_same_record(self):
        """修正の形 g1 の下請け（修正役が Agent で起こす子）の Edit・Write も、修正役と同じ記録に載り、突き合わせを通る（強み 5:
        書き込みの出どころ）。Claude Code は --settings で渡した PostToolUse のフックを subagent の道具の呼び出しでも起こし、入力に
        agent_id を載せる（本体 2.1.287 の hook の入力の定義『Present only when the hook fires from within a subagent (e.g., a tool
        called by an AgentTool worker)』と、record-read.py の docstring の 2026-09-22 の実測）。ここは、その形の入力を記録器が
        親の記録と同じ置き場に分けずに書き、受け付けが申告（bash_writes）なしに通すことを縛る"""
        with tempfile.TemporaryDirectory() as td:
            tmp = pathlib.Path(td)
            repo, sink = tmp / "repo", tmp / "sink"
            rev = committed_copy(repo, SEED)
            sink.mkdir()
            parent, child = repo / "stats.py", repo / "test_stats.py"
            parent.write_text("by the fix role\n", encoding="utf-8")
            child.write_text("by the subagent\n", encoding="utf-8")
            for path, agent in ((parent, None), (child, "a6562aad50ab27481")):
                ev = {"tool_name": "Edit" if agent is None else "Write", "tool_input": {"file_path": str(path)},
                      "session_id": "s-1", "tool_use_id": "toolu_1"}
                if agent:
                    ev.update(agent_id=agent, agent_type="general-purpose")
                self.assertEqual(self.run_recorder(sink, ev).returncode, 0)
            rows = [json.loads(ln) for ln in (sink / "writes.jsonl").read_text(encoding="utf-8").splitlines()]
            self.assertEqual([(r["path"], r["agent_id"]) for r in rows],
                             [(os.path.realpath(str(parent)), None), (os.path.realpath(str(child)), "a6562aad50ab27481")])
            got = writes.check({"changes": []}, repo, writes.changed(repo, rev), sink / "writes.jsonl")
            self.assertEqual((got["problems"], got["note"]), ([], ""), "申告なしに、記録だけで通る")

    def test_recorder_writes_nothing_without_sink_or_for_other_tools(self):
        with tempfile.TemporaryDirectory() as td:
            sink, f = pathlib.Path(td) / "sink", pathlib.Path(td) / "a.py"
            f.write_text("x\n", encoding="utf-8")
            self.assertEqual(self.run_recorder(sink, {"tool_name": "Write", "tool_input": {"file_path": str(f)}}).returncode, 0)
            self.assertFalse(sink.exists())
            sink.mkdir()
            for ev in ({"tool_name": "Read", "tool_input": {"file_path": str(f)}}, {"tool_name": "Bash"}, "not json"):
                self.run_recorder(sink, ev)
            self.assertEqual(list(sink.iterdir()), [])


class RepoCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = pathlib.Path(tmp.name)
        self.repo = self.tmp / "repo"
        self.rev = committed_copy(self.repo, SEED)
        self.log = self.tmp / "writes.jsonl"
        self.log.write_text("", encoding="utf-8")

    def check(self, reply=None, **kw):
        return writes.check(reply or {}, self.repo, writes.changed(self.repo, self.rev), self.log, **kw)


class TestProvenance(RepoCase):
    def test_bash_write_without_record_is_rejected(self):
        (self.repo / "stats.py").write_text("changed\n", encoding="utf-8")
        got = self.check({"changes": []})
        self.assertEqual(len(got["problems"]), 1)
        self.assertIn("stats.py", got["problems"][0])
        self.assertIn("bash_writes", got["problems"][0])
        self.assertEqual(got["reply"], {"changes": []})

    def test_scope_is_stated_in_reject_and_readme(self):
        """射程（Bash で書いた後に同じ中身を Edit したものは区別しない）を、docstring・拒否文・README の 3 か所に書く"""
        scope = "Bashで書いた後に同じ中身をEditで書き直した物は区別しない"
        for where, text in (("docstring", writes.__doc__), ("REJECT", writes.REJECT),
                            ("README", (ROOT / "README.md").read_text(encoding="utf-8"))):
            self.assertIn(scope, "".join(text.split()), where)   # 折り返しと語の間の空白は見ない

    def test_edit_with_matching_record_passes(self):
        (self.repo / "stats.py").write_text("changed\n", encoding="utf-8")
        record(self.log, self.repo / "stats.py")
        self.assertEqual(self.check()["problems"], [])

    def test_carry_moves_a_unit_record_only_for_same_content(self):
        """単位の worktree で Edit が書いた中身と同じ中身の run の作業ツリーのファイルだけ、記録を写す（依頼 243 の並べ）。
        中身が違う・元に記録が無い物は写さず、受け付けは今どおり拒む"""
        unit = self.tmp / "unit"
        unit.mkdir()
        for name, text in (("stats.py", "changed\n"), ("other.py", "unit side\n"), ("bare.py", "no record\n")):
            (unit / name).write_text(text, encoding="utf-8")
        record(self.log, unit / "stats.py")
        record(self.log, unit / "other.py")
        (self.repo / "stats.py").write_text("changed\n", encoding="utf-8")
        (self.repo / "other.py").write_text("merged with another\n", encoding="utf-8")
        (self.repo / "bare.py").write_text("no record\n", encoding="utf-8")
        got = writes.carry(self.log, [(unit / n, self.repo / n) for n in ("stats.py", "other.py", "bare.py")])
        self.assertEqual(got, [str((self.repo / "stats.py").resolve())])
        problems = self.check()["problems"]
        self.assertEqual(len(problems), 1)
        self.assertNotIn("stats.py", problems[0])
        self.assertIn("other.py", problems[0])
        self.assertIn("bare.py", problems[0])

    def test_carry_merged_records_a_machine_merge_of_recorded_units(self):
        """TDD の輪の並べで機械が 2 つの単位の中身を合わせたファイル（依頼 243 の並べの 3 段目）: どちらの中身にも記録が在れば
        合わせた中身に 1 行を足し、受け付けが通る。片方に記録が無ければ足さない"""
        u1, u2 = self.tmp / "u1", self.tmp / "u2"
        for d, text in ((u1, "a\nB\n"), (u2, "A\nb\n")):
            d.mkdir()
            (d / "stats.py").write_text(text, encoding="utf-8")
        (self.repo / "stats.py").write_text("A\nB\n", encoding="utf-8")
        record(self.log, u1 / "stats.py")
        self.assertFalse(writes.carry_merged(self.log, self.repo / "stats.py", [u1 / "stats.py", u2 / "stats.py"]))
        self.assertTrue(self.check()["problems"])
        record(self.log, u2 / "stats.py")
        self.assertTrue(writes.carry_merged(self.log, self.repo / "stats.py", [u1 / "stats.py", u2 / "stats.py"]))
        self.assertEqual(self.check()["problems"], [])
        row = json.loads(self.log.read_text(encoding="utf-8").splitlines()[-1])
        self.assertEqual((row["tool_name"], row["from"]), (writes.CARRY_TOOL, [str((u1 / "stats.py").resolve()),
                                                                                 str((u2 / "stats.py").resolve())]))

    def test_overwritten_after_record_is_rejected(self):
        p = self.repo / "stats.py"
        p.write_text("by edit\n", encoding="utf-8")
        record(self.log, p)
        p.write_text("by bash\n", encoding="utf-8")
        self.assertTrue(self.check()["problems"])

    def test_restored_to_recorded_content_passes(self):
        """輪が単位の頭に戻した中身（前に編集の道具が書いた中身）は、最後の記録でなくても通す"""
        p = self.repo / "stats.py"
        p.write_text("first\n", encoding="utf-8")
        record(self.log, p)
        p.write_text("second\n", encoding="utf-8")
        record(self.log, p)
        p.write_text("first\n", encoding="utf-8")
        self.assertEqual(self.check()["problems"], [])

    def test_untracked_and_deleted_without_record_are_rejected(self):
        (self.repo / "new.py").write_text("n\n", encoding="utf-8")
        (self.repo / "stats.py").unlink()
        got = self.check()
        for name in ("new.py", "stats.py"):
            self.assertIn(name, got["problems"][0])
        self.assertEqual(got["left"], ["new.py", "stats.py"])

    def test_declared_bash_write_with_reason_passes_and_is_kept(self):
        (self.repo / "stats.py").write_text("formatted\n", encoding="utf-8")
        (self.repo / "test_stats.py").unlink()
        got = self.check({"x": 1, "bash_writes": [{"path": "stats.py", "why": WHY}, {"path": "./test_stats.py", "why": WHY}]})
        self.assertEqual((got["problems"], got["reply"]), ([], {"x": 1}))
        self.assertEqual(self.check()["problems"], [], "通った申告は記録に残り、後ろの受け付けが同じ申告を求めない")
        (self.repo / "stats.py").write_text("again\n", encoding="utf-8")
        self.assertTrue(self.check()["problems"], "申告の後に中身が変われば記録が無いのと同じ")

    def test_declaration_without_reason_is_rejected(self):
        (self.repo / "stats.py").write_text("x\n", encoding="utf-8")
        for bad in ([{"path": "stats.py", "why": "短い"}], [{"path": "/abs/stats.py", "why": WHY}], [{"why": WHY}], "stats.py"):
            with self.subTest(bad):
                self.assertTrue(self.check({"bash_writes": bad})["problems"])

    def test_symlink_needs_a_declaration(self):
        """Bash で作った symlink は、指し先の中身に記録が在っても通さない（編集の道具は symlink を作れない）"""
        p = self.repo / "stats.py"
        p.write_text("by edit\n", encoding="utf-8")
        record(self.log, p)
        os.symlink(p, self.repo / "link.py")
        self.assertEqual(self.check()["left"], ["link.py"])
        self.assertEqual(self.check({"bash_writes": [{"path": "link.py", "why": WHY}]})["problems"], [])

    def test_archon_dir_is_not_counted(self):
        d = self.repo / ".archon" / "workflows"
        d.mkdir(parents=True)
        (d / "copy.yaml").write_text("x: 1\n", encoding="utf-8")
        self.assertEqual(self.check()["problems"], [])

    def test_no_change_passes(self):
        got = self.check()
        self.assertEqual((got["problems"], got["note"], got["left"]), ([], "", []))

    def test_not_strict_keeps_the_change_for_the_report(self):
        (self.repo / "stats.py").write_text("x\n", encoding="utf-8")
        got = self.check(strict=False)
        self.assertEqual((got["problems"], got["left"]), ([], ["stats.py"]))


class TestNoRecordRun(RepoCase):
    def test_run_without_sink_passes_with_note(self):
        """包みの無い run（記録のファイルが無い）は拒否の理由にせず今どおり通し、知らせを返す（盤面の trace から報告に 1 行）"""
        (self.repo / "stats.py").write_text("changed\n", encoding="utf-8")
        self.log.unlink()
        got = self.check()
        self.assertEqual((got["problems"], got["note"]), ([], writes.NO_RECORD))
        self.assertIn("書き込みの記録が無い run", got["note"])

    def test_report_line(self):
        import report

        class B:
            dir = self.tmp
        rows = [{"op": writes.NO_RECORD_OP, "node": "fix"}, {"op": writes.LEFT_OP, "node": "refix", "paths": ["a.py"]}]
        (self.tmp / "trace.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
        lines = [x for x in report.anomaly_lines(B) if x.startswith(("書き込みの記録が無い run", "記録の無い変更"))]
        self.assertEqual(len(lines), 2)
        self.assertIn(": 1 件 fix", lines[0])
        self.assertIn(": 1 件 a.py", lines[1])
        (self.tmp / "trace.jsonl").write_text("", encoding="utf-8")
        zero = [x for x in report.anomaly_lines(B) if x.startswith(("書き込みの記録が無い run", "記録の無い変更"))]
        self.assertEqual([x.rsplit(": ", 1)[1] for x in zero], ["0 件", "0 件"])


def _nodes(nodes):
    for n in nodes:
        yield n
        yield from _nodes((n.get("loop_group") or {}).get("nodes") or [])


class TestReplyShape(unittest.TestCase):
    def test_every_blk_fix_writer_node_accepts_bash_writes(self):
        import recount
        doc = yaml.safe_load((ROOT / "blk-fix" / "blk-fix.yaml").read_text(encoding="utf-8"))
        seen = []
        for n in _nodes(doc["nodes"]):
            if {"Edit", "Write", "Bash"} <= set(n.get("allowed_tools") or []):
                seen.append(n["id"])
                self.assertEqual(n["output_format"]["properties"].get("bash_writes"), writes.BASH_WRITES_SCHEMA, n["id"])
        self.assertEqual(seen, ["tdd", "fix", "fix-ruled"])
        for fmt in (recount.FIX_OUTPUT_FORMAT, recount.RULED_OUTPUT_FORMAT):
            self.assertEqual(fmt["properties"]["bash_writes"], writes.BASH_WRITES_SCHEMA)

    def test_refix_accept_reports_without_rejecting(self):
        """手直しの役の返答は写しの graph の schema のまま（申告の欄が無い）ので、受け付けは strict=False で呼ぶ"""
        src = (CORE / "refix.py").read_text(encoding="utf-8")
        self.assertIn("writes.sink(repo), strict=False)", src)
        self.assertIn("writes.trace(", src)


class TestFixAccept(unittest.TestCase):
    """節 fix-accept（blk-fix/scripts/accept.py）を本物の盤面で子として起こす。盤面の作り方は test_blk_fix の BoardCase"""

    def setUp(self):
        import test_blk_fix as tb
        self.tb = tb
        self.case = tb.TestAccept("test_accepts_and_carries_changes")
        self.case.setUp()
        self.addCleanup(self.case.doCleanups)
        self.case.fix_ready()
        self.case.edit_tree(tb.FIXED)
        self.home = pathlib.Path(os.environ["WORKS_ADAPTER_HOME"])
        self.log = adapter.writes_path(self.case.repo, self.home)

    def ops(self):
        return [json.loads(ln)["op"] for ln in (self.case.board / "trace.jsonl").read_text(encoding="utf-8").splitlines()]

    def test_run_without_record_is_accepted_with_a_trace_row(self):
        code, out, err = self.case.run_it(self.tb.load("fix2_ok"))
        self.assertEqual(code, 0, err)
        self.assertTrue(json.loads(out)["ok"], out)
        self.assertIn(writes.NO_RECORD_OP, self.ops())

    def test_unrecorded_bash_write_is_rejected_and_board_kept(self):
        self.log.parent.mkdir(parents=True, exist_ok=True)
        self.log.write_text("", encoding="utf-8")
        r = self.case.assert_script_rejected(self.tb.load("fix2_ok"), "bash_writes", "stats.py")
        self.assertIn("Edit・Write", r["reason"])

    def test_recorded_or_declared_write_is_accepted_and_field_dropped(self):
        self.log.parent.mkdir(parents=True, exist_ok=True)
        self.log.write_text("", encoding="utf-8")
        reply = self.tb.load("fix2_ok")
        reply["bash_writes"] = [{"path": p, "why": WHY} for p in writes.changed(self.case.repo, "HEAD")]
        code, out, err = self.case.run_it(reply)
        self.assertEqual(code, 0, err)
        self.assertTrue(json.loads(out)["ok"], out)
        import entry
        b = entry.open_board(self.case.board, allow_halted=True)
        got = json.loads((b.dir / b.state["outputs"]["p3.fix"]["file"]).read_text(encoding="utf-8"))
        self.assertNotIn("bash_writes", got, "盤面に渡す返答から申告の欄を外す")
        self.assertNotIn(writes.NO_RECORD_OP, self.ops())


class TestTddStep(unittest.TestCase):
    """TDD の輪の段は、前の段の後から変わったファイルを突き合わせる（包みの家を試験の置き場に替える）"""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        tmp = self.tmp = pathlib.Path(tmp.name)
        self.repo = tmp / "repo"
        committed_copy(self.repo, SEED)
        suite = self.suite = tmp / "suite.py"
        suite.write_text(SUITE, encoding="utf-8")
        env = mock.patch.dict(os.environ, {adapter.ENV_HOME: str(tmp / "home")})
        env.start()
        self.addCleanup(env.stop)
        self.log = writes.sink(self.repo)
        self.log.parent.mkdir(parents=True)
        self.log.write_text("", encoding="utf-8")
        self.state = tddloop.start(tmp / "art" / "board", self.repo, str(suite), OPEN)["state_file"]
        rows = [{"unit_key": MEAN, "route": "tdd"}, {"unit_key": CLAMP, "route": "direct", "why": "文書の直しと同じで先に書けない"}]
        self.assertTrue(tddloop.step(self.state, {"phase": "route", "units": rows}, self.repo)["ok"])

    def add_test(self):
        p = self.repo / "test_stats.py"
        p.write_text(p.read_text(encoding="utf-8").replace("\n\nif __name__", NEW_TEST + "\n\nif __name__"), encoding="utf-8")
        return p

    def red(self, **extra):
        return tddloop.step(self.state, {"phase": "test", "unit_key": MEAN, "test_files": ["test_stats.py"],
                                         "tests": ["test_stats.py::TestStats::test_mean_of_two"], **extra}, self.repo)

    def test_unrecorded_write_rejects_the_step(self):
        self.add_test()
        got = self.red()
        self.assertFalse(got["ok"])
        self.assertIn("test_stats.py", got["reason"])
        self.assertEqual(json.loads(pathlib.Path(self.state).read_text(encoding="utf-8"))["tries"], 1)

    def test_resubmitted_reply_is_rejected_again(self):
        """拒まれた返答をそのまま出し直しても、記録の無い書き込みは流れない"""
        self.add_test()
        self.assertFalse(self.red()["ok"])
        got = self.red()
        self.assertFalse(got["ok"], got)
        self.assertIn("test_stats.py", got["reason"])

    def test_route_conflict_does_not_wash_an_unrecorded_write(self):
        """振り分けの段の申し出は木を戻さない。その前の記録の無い書き込みは次の振り分けで拒む"""
        state = tddloop.start(self.tmp / "art2" / "board", self.repo, str(self.suite), OPEN)["state_file"]
        self.add_test()
        conflict = {"phase": "conflict", "unit_key": MEAN, "between": ["stats.py:9", "test_stats.py:9"],
                    "why_both_cannot_hold": "テストは分母 len(xs) - 1 の値を期待しているが、依頼は算術平均を求めている",
                    "which_is_right": "request", "kind": "unnamed_test_broke"}
        self.assertTrue(tddloop.step(state, conflict, self.repo)["ok"])
        got = tddloop.step(state, {"phase": "route", "units": [{"unit_key": CLAMP, "route": "direct",
                                                                "why": "文書の直しと同じで先に書けない"}]}, self.repo)
        self.assertFalse(got["ok"], got)
        self.assertIn(writes.REJECT, got["reason"])

    def test_give_up_restore_does_not_blame_the_next_unit(self):
        """諦めて機械が単位の頭に戻した木は前の段の印になる（戻したファイルを次の単位の書き込みとして拒まない）"""
        state = tddloop.start(self.tmp / "art2" / "board", self.repo, str(self.suite), OPEN)["state_file"]
        rows = [{"unit_key": MEAN, "route": "tdd"}, {"unit_key": CLAMP, "route": "tdd"}]
        self.assertTrue(tddloop.step(state, {"phase": "route", "units": rows}, self.repo)["ok"])
        record(self.log, self.add_test(), "Write")
        red = {"phase": "test", "unit_key": MEAN, "test_files": ["test_stats.py"], "tests": ["test_stats.py::TestStats::nope"]}
        got = tddloop.step(state, red, self.repo)   # 突き合わせは通り、赤の確かめで拒まれる
        self.assertFalse(got["ok"])
        self.assertEqual(got["writes"]["problems"], [])
        p = self.repo / "test_stats.py"
        while got["phase"] == "test" and json.loads(pathlib.Path(state).read_text(encoding="utf-8"))["cur"] == 0:
            p.write_text(p.read_text(encoding="utf-8") + "\n", encoding="utf-8")   # 記録の無い書き込み
            got = tddloop.step(state, red, self.repo)
        got = tddloop.step(state, {"phase": "test", "unit_key": CLAMP, "direct_why": "文書の直しと同じで先に書けない"}, self.repo)
        self.assertTrue(got["ok"], got)

    def test_recorded_or_declared_write_passes(self):
        record(self.log, self.add_test(), "Write")
        self.assertTrue(self.red()["ok"])

    def test_declared_write_passes(self):
        self.add_test()
        got = self.red(bash_writes=[{"path": "test_stats.py", "why": WHY}])
        self.assertTrue(got["ok"], got)
        self.assertEqual(got["writes"]["problems"], [])


class TestSelectedTests(unittest.TestCase):
    """受け付けが版からの変更に当たる試験を走らせ、元で赤でなかった試験の赤だけを返す"""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        tmp = pathlib.Path(tmp.name)
        self.repo = tmp / "repo"
        self.rev = committed_copy(self.repo, SEED)
        suite = tmp / "suite.py"
        suite.write_text(SUITE, encoding="utf-8")
        self.state = tddloop.start(tmp / "art" / "board", self.repo, str(suite), OPEN)["state_file"]

    def test_no_state_runs_nothing(self):
        self.assertEqual(tddloop.selected_problems("", self.repo, self.rev), ([], tddloop.NO_SUITE))

    def test_baseline_red_is_not_counted(self):
        """種の test_mean_of_three は元から赤。触ったファイルに当たる試験を走らせても、新しい赤が無ければ通す"""
        p = self.repo / "stats.py"
        p.write_text(p.read_text(encoding="utf-8") + "\n", encoding="utf-8")
        red, note = tddloop.selected_problems(self.state, self.repo, self.rev)
        self.assertEqual(red, [])
        self.assertIn("新しい赤なし", note)

    def test_new_red_is_returned(self):
        p = self.repo / "stats.py"
        text = p.read_text(encoding="utf-8")
        self.assertIn("    return x\n", text)
        p.write_text(text.replace("    return x\n", "    return lo\n", 1), encoding="utf-8")
        red, _ = tddloop.selected_problems(self.state, self.repo, self.rev)
        self.assertEqual(len(red), 1, "行はテストのファイルごと")
        self.assertIn("test_clamp_within_range", red[0])
        self.assertNotIn("test_mean_of_three", red[0], "元から赤の試験は数えない")
        self.assertIn("元で赤でなかった試験が赤（ファイル test_stats.py）", red[0], "行はテストのファイルのパスを名指す")

    def test_nothing_selected_runs_nothing(self):
        (self.repo / "notes.txt").write_text("x\n", encoding="utf-8")
        self.assertEqual(tddloop.selected_problems(self.state, self.repo, self.rev), ([], tddloop.NO_SELECTED))


if __name__ == "__main__":
    unittest.main()
