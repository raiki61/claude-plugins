"""読んだ証拠（.shared/core/reads.py。線 A Task 6。仕様 5.2・〔輪〕5.3）の検査。

- 出どころは 2 つ: 包みの Read のフックの記録（<包みの家>/reads/<cwd の hash>/reads.jsonl。行は record-read.py を実物で起こして
  書く）と、Archon の tool_called の出来事（tests/events/verbose-reads.json。tool_called の行は推測。_note）
- 出来事の Read の形は P13（Task 18）で確かめるまで EVENTS_VERIFIED が偽。偽の間は出どころを unverified・各行の event を
  null にし、missing はフックだけで決める（審査 I6）。受け付けの条件にはしない（全部 missing でも ok 真）
- 包みの起動の記録（<包みの家>/launches/<cwd の hash>.jsonl。T5 の形）から、この run の役の起動を数える（adapter_seen）
- ブロックの <役>-reads の節（blk-fix・blk-delta・blk-pr の scripts/reads.py）が main_for を通して 1 行を出す
盤面は本物の darkfactory の表で linekit の種から entry.start で 1 回だけ作る（クラスに 1 回。git と子のプロセスを使うので heavy）
"""
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parents[1]
CORE = ROOT / ".shared" / "core"
TESTS = pathlib.Path(__file__).resolve().parent
EVENTS = TESTS / "events"
SEED = ROOT / "dev" / "target-seed"
RECORDER = CORE / "record-read.py"
sys.dont_write_bytecode = True
sys.path.insert(0, str(CORE))
sys.path.insert(0, str(CORE / "graphloops"))
sys.path.insert(0, str(TESTS))

import adapter  # noqa: E402
import engine.util as engine_util  # noqa: E402
import entry  # noqa: E402
import linekit  # noqa: E402
import reads  # noqa: E402
import refix  # noqa: E402

PLAN = reads.node_path("planning", "plan-loop", "plan")
FIX = reads.node_path("fixing", "fix-loop", "fix")
CLI_TAIL = ["workflow", "get", "run-6", "--verbose", "--events", "--json"]


def events_with(repo) -> list:
    """推測の見本の events（@REPO@ を repo に差し替える）"""
    text = (EVENTS / "verbose-reads.json").read_text(encoding="utf-8").replace("@REPO@", str(repo))
    return json.loads(text)["events"]


class BoardCase(unittest.TestCase):
    """本物の表の盤面 1 つ（クラスに 1 回）と、試験ごとの包みの家・読むファイルの置き場"""

    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory(dir=linekit.work_home())
        cls.tmp = pathlib.Path(cls._tmp.name)
        cls._git_cwd = engine_util.GIT_CWD
        env = mock.patch.dict(os.environ, {"WORKS_ADAPTER_HOME": str(cls.tmp / "start-home")})
        env.start()
        try:
            cls.repo = linekit.seed_repo(cls.tmp / "repo", declared=True)
            req = cls.tmp / "request.json"
            req.write_text((SEED / "request_ok.json").read_text(encoding="utf-8"), encoding="utf-8")
            cls.board = cls.tmp / "art" / "board"
            entry.start(cls.board, cls.repo, {"request": str(req), "test_cmd": "", "thickness": "", "gates": "",
                                              "final_gate": "", "adapter": "", "policy_md": ""}, run_id="run-6")
        finally:
            env.stop()
            engine_util.GIT_CWD = cls._git_cwd

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def setUp(self):
        self._t = tempfile.TemporaryDirectory(dir=self.tmp)
        self.addCleanup(self._t.cleanup)
        self.t = pathlib.Path(self._t.name)
        self.home = self.t / "adapter-home"
        env = mock.patch.dict(os.environ, {"WORKS_ADAPTER_HOME": str(self.home)})
        env.start()
        self.addCleanup(env.stop)
        self.addCleanup(setattr, engine_util, "GIT_CWD", engine_util.GIT_CWD)
        self.docs = self.t / "docs"
        self.docs.mkdir()

    def doc(self, name, text="中身\n") -> str:
        p = self.docs / name
        p.write_text(text, encoding="utf-8")
        return str(p)

    def hook_read(self, path, **extra):
        """包みが足すフック（record-read.py）を実物で起こし、Read を 1 回記録させる（置き場は包みと同じ reads_dir）"""
        sink = adapter.reads_dir(self.repo)
        sink.mkdir(parents=True, exist_ok=True)
        payload = {"tool_name": "Read", "tool_input": {"file_path": path, **extra}, "cwd": str(self.repo),
                   "session_id": "s-1", "tool_use_id": "toolu_x"}
        subprocess.run([sys.executable, str(RECORDER), str(sink)], input=json.dumps(payload), text=True, encoding="utf-8", check=True,
                       env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"})

    def collect(self, role, node, must, events):
        return reads.collect(self.board, role, node, must, events, repo=self.repo)

    def written(self, got) -> dict:
        return json.loads(pathlib.Path(got["reads_file"]).read_text(encoding="utf-8"))


class CollectTest(BoardCase):
    def test_states_from_hook_and_events(self):
        brief, judged, notes, only_fix = (self.doc(n) for n in ("plan-brief.json", "judged.json", "notes.md", "fix-only.md"))
        self.hook_read(brief)
        self.hook_read(notes, offset=1, limit=5)
        with mock.patch.object(reads, "EVENTS_VERIFIED", True):
            got = self.collect("plan", PLAN, [brief, judged, notes, only_fix], events_with(self.docs))
        doc = self.written(got)
        self.assertEqual(pathlib.Path(got["reads_file"]), entry.open_board(self.board).work("reads-plan.json"))
        self.assertEqual({k: doc[k] for k in ("role", "node_path")}, {"role": "plan", "node_path": "planning__plan-loop.plan"})
        self.assertEqual(doc["rows"], [{"path": brief, "hook": "read", "event": True},
                                       {"path": judged, "hook": "absent", "event": True},
                                       {"path": notes, "hook": "partial", "event": False},
                                       {"path": only_fix, "hook": "absent", "event": False}])
        self.assertEqual(doc["sources"], {"hook": True, "events": "verified"})
        self.assertEqual(doc["missing"], [only_fix], "出来事は verified の時だけ数える: judged は出来事で読んだ")
        self.assertEqual(got, {"ok": True, "sources": doc["sources"], "missing": [only_fix], "reads_file": got["reads_file"]})

    def test_stale_when_file_changed(self):
        brief = self.doc("plan-brief.json", "前\n")
        self.hook_read(brief)
        pathlib.Path(brief).write_text("後\n", encoding="utf-8")
        got = self.collect("plan", PLAN, [brief], None)
        self.assertEqual(self.written(got)["rows"], [{"path": brief, "hook": "stale", "event": None}])
        self.assertEqual(got["missing"], [])

    def test_missing_sources_reported(self):
        a, b = self.doc("a.md"), self.doc("b.md")
        got = self.collect("fix", FIX, [a, b], None)   # フックの記録も出来事も無い
        doc = self.written(got)
        self.assertEqual(doc["sources"], {"hook": False, "events": "none"})
        self.assertEqual([r["hook"] for r in doc["rows"]], ["none", "none"])
        self.assertEqual([r["event"] for r in doc["rows"]], [None, None])
        self.assertEqual(got["missing"], [a, b])
        self.hook_read(a)                              # 記録は在る・出来事は無い
        got = self.collect("fix", FIX, [a, b], None)
        self.assertEqual(got["sources"], {"hook": True, "events": "none"})
        self.assertEqual(got["missing"], [b])

    def test_relative_must_resolves_against_repo(self):
        (self.repo / "brief-rel.md").write_text("相対\n", encoding="utf-8")
        self.addCleanup((self.repo / "brief-rel.md").unlink)
        self.hook_read(str(self.repo / "brief-rel.md"))
        got = self.collect("fix", FIX, ["brief-rel.md"], None)
        self.assertEqual(self.written(got)["rows"], [{"path": "brief-rel.md", "hook": "read", "event": None}])

    def test_included_node_path(self):
        self.assertEqual(reads.node_path("planning", "plan-loop", "plan"), "planning__plan-loop.plan")
        evs = events_with(self.docs)
        real = {str(pathlib.Path(os.path.realpath(self.docs / n))) for n in ("plan-brief.json", "judged.json")}
        self.assertEqual(reads._read_paths(evs, PLAN), real, "Bash と別の節（fix）の Read は数えない")
        self.assertEqual(reads._read_paths(evs, FIX), {os.path.realpath(self.docs / "fix-only.md")})
        self.assertEqual(reads._read_paths(evs, "judging__judge-loop.judge"), set())
        only_fix = self.doc("fix-only.md")
        with mock.patch.object(reads, "EVENTS_VERIFIED", True):
            got = self.collect("plan", PLAN, [only_fix], evs)
        self.assertEqual(self.written(got)["rows"][0]["event"], False)

    def test_outer_loop_prefix_counts(self):
        """周の輪（線 B）の中に置いた include は、出来事の上で rounds.<include>__<輪>.<節> になる（P10）。それも同じ節として数える"""
        def ev(step, path):
            return {"event_type": "tool_called", "step_name": step,
                    "data": {"tool_name": "Read", "tool_input": {"file_path": path}, "tool_call_id": "t"}}
        evs = [ev("rounds." + PLAN, "/a"), ev("x" + PLAN, "/b"), ev(PLAN + ".more", "/c"), {"event_type": "tool_called"},
               ev(PLAN, 7), "壊れた行"]
        self.assertEqual(reads._read_paths(evs, PLAN), {os.path.realpath("/a")})

    def test_not_an_acceptance_condition(self):
        must = [self.doc("x.md"), self.doc("y.md")]
        with mock.patch.object(reads, "EVENTS_VERIFIED", True):
            got = self.collect("plan", PLAN, must, [])
        self.assertIs(got["ok"], True)
        self.assertEqual(got["missing"], must)
        self.assertEqual(got["sources"], {"hook": False, "events": "verified"})

    def test_events_unverified_until_p13(self):
        self.assertIs(reads.EVENTS_VERIFIED, False)
        brief, judged = self.doc("plan-brief.json"), self.doc("judged.json")
        self.hook_read(brief)
        got = self.collect("plan", PLAN, [brief, judged], events_with(self.docs))
        doc = self.written(got)
        self.assertEqual(doc["sources"], {"hook": True, "events": "unverified"})
        self.assertEqual([r["event"] for r in doc["rows"]], [None, None], "未確認の出来事を「読んでいない」と書かない")
        self.assertEqual(doc["missing"], [judged], "missing はフックだけで決まる")


class EventsForTest(unittest.TestCase):
    def setUp(self):
        self._t = tempfile.TemporaryDirectory()
        self.addCleanup(self._t.cleanup)
        self.t = pathlib.Path(self._t.name)

    def fake_cli(self, body: str) -> str:
        """偽の CLI（受けた argv を argv.json に書き、body を走らせる小さなスクリプト）の ARCHON_CLI_COMMAND"""
        p = self.t / "fake-archon.py"
        p.write_text("import json, sys\n"
                     f"open({str(self.t / 'argv.json')!r}, 'w').write(json.dumps(sys.argv[1:]))\n" + body,
                     encoding="utf-8")
        return json.dumps([sys.executable, str(p)])

    def test_events_for_without_cli_is_none(self):
        env = {k: v for k, v in os.environ.items() if k != "ARCHON_CLI_COMMAND"}
        with mock.patch.dict(os.environ, env, clear=True):
            self.assertIsNone(reads.events_for("run-6"))
        for bad in ("", "not json", '"archon"', "[]", "[1]", json.dumps([str(self.t / "no-such-archon")])):
            with mock.patch.dict(os.environ, {"ARCHON_CLI_COMMAND": bad}):
                self.assertIsNone(reads.events_for("run-6"), bad)

    def test_events_for_calls_cli_with_verbose(self):
        sample = EVENTS / "verbose-p13.json"
        cmd = self.fake_cli(f"sys.stdout.write(open({str(sample)!r}, encoding='utf-8').read())\n"
                            "sys.stderr.write('{\"level\": 30}\\n')\n")
        with mock.patch.dict(os.environ, {"ARCHON_CLI_COMMAND": cmd}):
            got = reads.events_for("run-6")
        self.assertEqual(json.loads((self.t / "argv.json").read_text()), CLI_TAIL)
        self.assertEqual(len(got), 19)
        self.assertEqual(got, json.loads(sample.read_text(encoding="utf-8"))["events"])

    def test_events_for_without_events_is_none(self):
        """--verbose が効かない（events の欄が無い）・終了コードが 0 でない・JSON でない → None"""
        for body in ("print(json.dumps({'id': 'run-6'}))\n", "print(json.dumps({'events': 'x'}))\n",
                     "print(json.dumps({'events': []})); sys.exit(1)\n", "print('not json')\n"):
            with mock.patch.dict(os.environ, {"ARCHON_CLI_COMMAND": self.fake_cli(body)}):
                self.assertIsNone(reads.events_for("run-6"), body)
        with mock.patch.dict(os.environ, {"ARCHON_CLI_COMMAND": self.fake_cli("print(json.dumps({'events': []}))\n")}):
            self.assertEqual(reads.events_for("run-6"), [])
            self.assertIsNone(reads.events_for(""), "run の id が無ければ呼ばない")


class FailedNodesTest(unittest.TestCase):
    def test_last_state_failed_with_error(self):
        """最後の状態が node_failed の節だけを、誤りの文と一緒に（run 31 の出来事の形。出し直しで後に済んだ節は数えない）"""
        def ev(kind, step, error=None):
            return {"event_type": kind, "step_name": step, "data": {"error": error} if error else {}}
        events = [ev("workflow_started", None), ev("node_started", "a"), ev("node_failed", "a", "一度目"),
                  ev("node_started", "a"), ev("node_completed", "a"),
                  ev("node_started", "eyeing__r1-minimality-loop.r1-minimality-prep"),
                  ev("node_failed", "eyeing__r1-minimality-loop.r1-minimality-prep",
                     "Script node 'r1-minimality-prep' failed [exit 2]: BoardGap: …"),
                  ev("node_skipped", "report")]
        self.assertEqual(reads.failed_nodes(events),
                         [{"node": "eyeing__r1-minimality-loop.r1-minimality-prep",
                           "error": "Script node 'r1-minimality-prep' failed [exit 2]: BoardGap: …"}])
        self.assertEqual(reads.failed_nodes(None), [])


class AdapterSeenTest(BoardCase):
    def rows(self, cwd, *rows):
        p = adapter.launches_path(cwd)
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("a", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")

    def row(self, mode, *, at=None, why=None, tools_empty=False, node="fix"):
        return {"at": at or adapter.now(), "pid": 1, "cwd": str(self.repo), "node": node, "continue": None, "mode": mode,
                "why": why, "hook": mode == "merged", "tools_empty": tools_empty, "session": None, "fence": None}

    def test_adapter_seen_counts(self):
        self.rows(self.repo, self.row("merged"), self.row("merged", node="judge"),
                  self.row("passthrough", why="unmarked", node=None),
                  self.row("merged", at="2020-01-01T00:00:00.000000+00:00"),     # 盤面を作る前（前の run）
                  self.row("passthrough", why="題の生成", tools_empty=True, node=None))
        self.rows(self.t / "other-worktree", self.row("merged"))                   # 別の run の worktree
        got = reads.adapter_seen(self.board, "run-6", repo=self.repo)
        self.assertEqual(got, {"seen": True, "merged": 2, "passthrough": 1, "whys": ["unmarked"]})

    def test_adapter_not_seen(self):
        self.rows(self.repo, self.row("passthrough", why="題の生成", tools_empty=True, node=None))
        got = reads.adapter_seen(self.board, "run-6", repo=self.repo)
        self.assertEqual({k: got[k] for k in ("seen", "merged", "passthrough")}, {"seen": False, "merged": 0, "passthrough": 0})
        self.assertEqual(len(got["whys"]), 1)
        self.assertIn(str(adapter.launches_path(self.repo)), got["whys"][0])
        self.assertIn("run-6", got["whys"][0])


def run_block_script(block, repo, env):
    full = {"PATH": os.environ["PATH"], "PYTHONDONTWRITEBYTECODE": "1", **env}
    r = subprocess.run([sys.executable, str(ROOT / block / "scripts" / "reads.py")], cwd=str(repo), env=full,
                       capture_output=True, text=True, encoding="utf-8")
    return r.returncode, r.stdout, r.stderr


class MainForTest(BoardCase):
    def env(self, **over):
        cli = self.t / "fake-archon.py"
        cli.write_text("import sys\nsys.stdout.write(open(%r, encoding='utf-8').read())\n"
                       % str(EVENTS / "verbose-p13.json"), encoding="utf-8")
        base = {"ARTIFACTS_DIR": str(self.board.parent), "WORKFLOW_ID": "run-6", "WORKS_ADAPTER_HOME": str(self.home),
                "INPUTS_MUST": json.dumps([self.doc("brief.json")]),
                "ARCHON_CLI_COMMAND": json.dumps([sys.executable, str(cli)])}
        return {k: v for k, v in {**base, **over}.items() if v is not None}

    def test_block_scripts_write_reads_file(self):
        """blk-fix・blk-delta・blk-pr の <役>-reads の節が core の main_for を呼び、1 行を出して 0"""
        for block, role in (("blk-fix", "fix"), ("blk-delta", "review"), ("blk-pr", "pr-check")):
            code, out, err = run_block_script(block, self.repo, self.env())
            self.assertEqual(code, 0, (block, err))
            lines = out.splitlines()
            self.assertEqual(len(lines), 1, out)
            got = json.loads(lines[0])
            self.assertIs(got["ok"], True)
            self.assertEqual(got["sources"], {"hook": False, "events": "unverified"})
            self.assertEqual(pathlib.Path(got["reads_file"]).name, f"reads-{role}.json")
            doc = json.loads(pathlib.Path(got["reads_file"]).read_text(encoding="utf-8"))
            self.assertEqual(doc["role"], role)

    def test_block_script_reads_hook_log_from_cwd(self):
        """スクリプトは repo を渡さず cwd（役の worktree）から包みの置き場を引く: フックの記録が在れば行は read"""
        brief = self.doc("brief.json")
        self.hook_read(brief)
        code, out, err = run_block_script("blk-fix", self.repo, self.env(INPUTS_MUST=json.dumps([brief])))
        self.assertEqual(code, 0, err)
        got = json.loads(out)
        self.assertEqual((got["sources"]["hook"], got["missing"]), (True, []))
        doc = json.loads(pathlib.Path(got["reads_file"]).read_text(encoding="utf-8"))
        self.assertEqual(doc["rows"], [{"path": brief, "hook": "read", "event": None}])

    def test_main_for_missing_env_is_2(self):
        for name in ("ARTIFACTS_DIR", "WORKFLOW_ID", "INPUTS_MUST"):
            code, out, err = run_block_script("blk-fix", self.repo, self.env(**{name: None}))
            self.assertEqual((code, out), (2, ""), name)
            self.assertIn(name, err)
        for bad in ("not json", '"a.md"', "[1]"):
            code, out, err = run_block_script("blk-fix", self.repo, self.env(INPUTS_MUST=bad))
            self.assertEqual((code, out), (2, ""), bad)
            self.assertIn("INPUTS_MUST", err)

    def test_refix_reads_all_uses_core_interface(self):
        """blk-refix の reads_all（Task 13）が core の reads をそのまま受ける（この盤面はまだ手直しを受けていないので役は 0）"""
        self.assertEqual(refix.reads_all(self.board, reads, ""), {"ok": True, "reads_files": {}})


if __name__ == "__main__":
    unittest.main()
