"""canary（dev/canary.sh・dev/canary-seed/・dev/canary-request.json・dev/canary_check.py）の検査（FAST）。

- 種: 種の写しで、種のテストは緑・依頼の 3 件のバグは在る（下の PROBES が赤）・試験の中だけに持つ参照の直し（FIXES）を当てると
  当てた件の PROBES だけが緑になり、全部当てれば全部緑で種のテストも緑のまま。textfmt.py の 2 つの直しは 3 方向で字の食い違い
  なしに合い、2 つの枝が test_textfmt.py の末尾に足すテストは挿しだけの食い違い（union で合う）になる（canary の (b) の前提）。
  依頼は入口の依頼の型（写しの RL の REQUEST_SCHEMA）を通り、where のファイルが種に在る。
- 確かめ役 canary_check.py: 一時の置き場に sqlite の偽の archon.db（Archon の 2 つの表の要る列だけ）と偽の盤面（trace.jsonl・
  plan-fields.json・tdd-<k>/state.json・run-place の相談の記録）を置き、(a)〜(d) の判じ・費用・時間・終了コードと、読むだけで
  何も書かないことを見る。
子のプロセスは python3（種のテストと PROBES）と git merge-file（リポジトリを作らない）だけ。
"""
import hashlib
import json
import pathlib
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.dont_write_bytecode = True   # 下の import が pack の中に __pycache__ を作らないように
sys.path.insert(0, str(ROOT / "dev"))
sys.path.insert(0, str(ROOT / ".shared" / "core"))

import canary_check  # noqa: E402
import entry  # noqa: E402
import hermetic  # noqa: E402

SEED = ROOT / "dev" / "canary-seed"
REQUEST = ROOT / "dev" / "canary-request.json"
TOOL = ROOT / "dev" / "canary_check.py"

# 依頼の 3 件の約束（依頼の text・measured のとおり）。種では全部赤、参照の直しの後は緑
PROBES = {
    "mean": "import calc; assert calc.mean([1, 2, 3]) == 2",
    "pad_left": "import textfmt; assert textfmt.pad_left('7', 3, '0') == '007'",
    "truncate": ("import textfmt; t = textfmt.truncate('abcdef', 4); assert len(t) == 4 and t.endswith(textfmt.ELLIPSIS); "
                 "assert textfmt.truncate('abc', 4) == 'abc'"),
    "changelog": ("import pathlib; s = pathlib.Path('CHANGELOG.md').read_text(encoding='utf-8'); "
                  "u = s.split('## [Unreleased]', 1)[1].split('\\n## ', 1)[0]; "
                  "assert any(l.startswith('- ') and 'mean' in l for l in u.splitlines())"),
}
# 参照の直し（件 → [(ファイル, 前, 後)]）。種には置かない（直しの答えを対象に渡さない）
FIXES = {
    "mean": [("calc.py", "return sum(xs) / (len(xs) - 1)", "return sum(xs) / len(xs)"),
             ("CHANGELOG.md", "## [Unreleased]\n", "## [Unreleased]\n\n- calc.mean: 分母を個数にした（算術平均を返す）\n")],
    "pad_left": [("textfmt.py", "return s + fill * (width - len(s))", "return fill * (width - len(s)) + s")],
    "truncate": [("textfmt.py", "return s[:limit] + ELLIPSIS", "return s[:limit - 1] + ELLIPSIS")],
}
FIX_PROBES = {"mean": {"mean", "changelog"}, "pad_left": {"pad_left"}, "truncate": {"truncate"}}
PROBE_RUN = """
import json, sys
out = {}
for name, src in json.loads(sys.argv[1]).items():
    try:
        exec(src, {})
        out[name] = True
    except Exception:
        out[name] = False
print(json.dumps(out))
"""


def _env():
    return hermetic.child_env(PYTHONDONTWRITEBYTECODE="1")


class SeedTest(unittest.TestCase):
    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp(prefix="canary-seed-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def copy(self, fixes=()):
        d = self.tmp / ("seed-" + "-".join(fixes) if fixes else "seed")
        shutil.copytree(SEED, d)
        for name in fixes:
            for rel, old, new in FIXES[name]:
                p = d / rel
                text = p.read_text(encoding="utf-8")
                self.assertEqual(text.count(old), 1, f"参照の直し {name} の前の字が {rel} に 1 つだけ在る")
                p.write_text(text.replace(old, new), encoding="utf-8")
        return d

    def probes(self, d) -> dict:
        got = subprocess.run([sys.executable, "-c", PROBE_RUN, json.dumps(PROBES)], cwd=d, env=_env(),
                             capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(got.returncode, 0, got.stderr)
        return json.loads(got.stdout)

    def suite_green(self, d):
        got = subprocess.run([sys.executable, "-m", "unittest", "-q"], cwd=d, env=_env(), capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(got.returncode, 0, got.stderr[-2000:])
        self.assertIn("OK", got.stderr)

    def test_seed_suite_green_and_every_bug_present(self):
        """種のテストは緑（バグを突くテストはまだ無い）で、依頼の 3 件の約束と CHANGELOG の行は全部赤"""
        d = self.copy()
        self.suite_green(d)
        self.assertEqual(self.probes(d), {k: False for k in PROBES})

    def test_each_reference_fix_flips_only_its_own_probes(self):
        """参照の直しは件ごとに独立: 1 件を当てるとその件の約束だけが緑になる"""
        for name in FIXES:
            with self.subTest(name):
                got = self.probes(self.copy((name,)))
                self.assertEqual({k for k, v in got.items() if v}, FIX_PROBES[name])

    def test_all_reference_fixes_pass_and_keep_suite_green(self):
        d = self.copy(tuple(FIXES))
        self.assertEqual(self.probes(d), {k: True for k in PROBES})
        self.suite_green(d)

    def merge(self, base: str, ours: str, theirs: str, *flags) -> tuple:
        for n, text in (("base", base), ("ours", ours), ("theirs", theirs)):
            (self.tmp / n).write_text(text, encoding="utf-8")
        got = subprocess.run(["git", "merge-file", "-p", *flags, str(self.tmp / "ours"), str(self.tmp / "base"),
                              str(self.tmp / "theirs")], capture_output=True, text=True, encoding="utf-8")
        return got.returncode, got.stdout

    def test_same_file_fixes_merge_without_text_conflict(self):
        """(b) の前提: pad_left と truncate の直しは同じ textfmt.py の離れた塊で、3 方向で食い違わずに合う"""
        base = (SEED / "textfmt.py").read_text(encoding="utf-8")
        ours = base.replace(*FIXES["pad_left"][0][1:])
        theirs = base.replace(*FIXES["truncate"][0][1:])
        rc, merged = self.merge(base, ours, theirs)
        self.assertEqual(rc, 0, "字の食い違いが出た")
        self.assertEqual(merged, ours.replace(*FIXES["truncate"][0][1:]))

    def test_tests_appended_to_same_file_are_insertion_only_conflicts(self):
        """(b) の前提: 2 つの枝が test_textfmt.py の末尾（main の前）に足すテストは挿しだけの食い違いで、union で両方残る"""
        base = (SEED / "test_textfmt.py").read_text(encoding="utf-8")
        tail = '\n\nif __name__ == "__main__":'
        self.assertEqual(base.count(tail), 1)
        add = "\n\nclass Test{0}(unittest.TestCase):\n    def test_{1}(self):\n        self.assertTrue(True)\n"
        ours = base.replace(tail, add.format("PadLeft", "pad_left") + tail)
        theirs = base.replace(tail, add.format("Truncate", "truncate") + tail)
        rc, _ = self.merge(base, ours, theirs)
        self.assertGreater(rc, 0, "末尾の挿しが食い違わないなら union の道を通らない")
        rc, merged = self.merge(base, ours, theirs, "--union")
        self.assertEqual(rc, 0)
        self.assertIn("class TestPadLeft", merged)
        self.assertIn("class TestTruncate", merged)

    def test_request_passes_entry_schema_and_names_seed_files(self):
        """依頼は入口の型を通り、where のファイルが種に在り、別のファイルの件と同じファイルの 2 件を持つ。範囲の相談を
        通すため、mean の件は CHANGELOG.md を allowed_paths にも out_of_scope にも入れないと修正案に言う"""
        _, _, items, _, _ = entry._read_request(str(REQUEST), SEED, entry.board_rules())
        files = [it["where"].split(":", 1)[0] for it in items]
        for f in files:
            self.assertTrue((SEED / f).is_file(), f)
        self.assertEqual(sorted(files), ["calc.py", "textfmt.py", "textfmt.py"])
        mean = next(it for it in items if it["where"].startswith("calc.py"))
        for word in ("CHANGELOG.md", "allowed_paths", "out_of_scope", "範囲の相談"):
            self.assertIn(word, mean["text"])
        self.assertIn("## [Unreleased]", (SEED / "CHANGELOG.md").read_text(encoding="utf-8"))

    def test_seed_holds_no_request_pack_or_answers(self):
        """種は対象にそのまま写る: 依頼・pack の写し・参照の直しを持たない"""
        names = {p.relative_to(SEED).as_posix() for p in SEED.rglob("*") if p.is_file()}
        self.assertEqual(names, {".gitignore", "README.md", "CHANGELOG.md", "calc.py", "textfmt.py",
                                 "test_calc.py", "test_textfmt.py"})


# ---------------------------------------------------------------- 偽の archon.db と盤面
RUN = "run-canary"


def at(sec):
    """出来事の created_at（2026-10-07 の 10 時から sec 秒後。Archon の形の秒の粒）"""
    s = 10 * 3600 + sec
    return f"2026-10-07 {s // 3600:02d}:{s // 60 % 60:02d}:{s % 60:02d}"


def ev(kind, step, sec, **data):
    return (kind, step, data, at(sec))


def task(step, tid, start, end, kind="local_agent"):
    return [ev("task_activity", step, start, task_id=tid, activity="started", task_type=kind),
            ev("task_activity", step, end, task_id=tid, activity="completed")]


def node(step, start, end, usd=0.5, kind="agent"):
    cost = {"source": "provider", "value": usd} if usd is not None else {"source": "unavailable", "reason": "x"}
    return [ev("node_started", step, start, node={"id": step, "kind": kind}),
            ev("node_completed", step, end, node={"id": step, "kind": kind}, spend={"costUsd": cost})]


def make_db(path, output_root, events, run=RUN):
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE remote_agent_workflow_runs (id TEXT PRIMARY KEY, workflow_name TEXT, status TEXT, "
                "started_at TEXT, completed_at TEXT, output_root TEXT)")
    con.execute("CREATE TABLE remote_agent_workflow_events (id TEXT PRIMARY KEY, workflow_run_id TEXT, event_order INTEGER, "
                "event_type TEXT, step_index INTEGER, step_name TEXT, data TEXT, created_at TEXT)")
    con.execute("INSERT INTO remote_agent_workflow_runs VALUES (?, 'darkfactory', 'completed', ?, ?, ?)",
                (run, at(0), at(600), str(output_root)))
    for n, (kind, step, data, when) in enumerate(events, 1):
        con.execute("INSERT INTO remote_agent_workflow_events VALUES (?, ?, ?, ?, NULL, ?, ?, ?)",
                    (f"{run}-{n}", run, n, kind, step, json.dumps(data, ensure_ascii=False), when))
    con.commit()
    con.close()


def write(path, doc):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(doc if isinstance(doc, str) else json.dumps(doc, ensure_ascii=False), encoding="utf-8")


def make_board(board, *, lanes=None, units=None, asks=(), unsettled=(), replans=0):
    write(board / "plan-fields.json", {"round": 1, "fields": [
        {"route": "tdd", "allowed_paths": ["calc.py", "test_calc.py"]},
        {"route": "tdd", "allowed_paths": ["textfmt.py", "test_textfmt.py"]},
        {"route": "tdd", "allowed_paths": ["textfmt.py", "test_textfmt.py"]}]})
    trace = [{"t": "x", "op": "init"}]
    if units is not None:
        trace.append({"t": "x", "op": "units_settled", "node": "fix-units", "machine": [], "carried": 0, **units,
                      "scope": "fixing"})
    trace += [{"t": "x", "op": "plan_scope_asked", **a, "scope": "fixing"} for a in asks]
    trace += [{"t": "x", "op": "replan_state", "id": f"c1-{n}", "state": "amended"} for n in range(replans)]
    write(board / "trace.jsonl", "\n".join(json.dumps(r, ensure_ascii=False) for r in trace) + "\n{broken\n")
    if lanes is not None:
        write(board / "tdd-1" / "state.json", {"phase": "fix", "lanes": lanes})
    write(board / "tdd-2" / "state.json", {"phase": "route"})   # 並べなかった輪は数えない
    if unsettled:
        write(board.parent / "run-place" / "fixing" / "ask-plan" / "exchanges.jsonl",
              "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in unsettled))


FULL_LANES = {"rows": [{"n": 1}, {"n": 2}, {"n": 3}], "shared": ["test_textfmt.py", "textfmt.py"], "expect": [[2, 3]],
              "out": [{"unit_key": "u1", "outcome": "merged", "lane": 1, "merge": "clean"},
                      {"unit_key": "u2", "outcome": "merged", "lane": 2, "merge": "clean"},
                      {"unit_key": "u3", "outcome": "merged", "lane": 3, "merge": "union"}]}
ANSWERED = {"id": 1, "item": "1", "status": "answered", "decision": "allow", "paths": ["CHANGELOG.md"],
            "granted_paths": ["CHANGELOG.md"]}


def lane(n, start, end, usd=0.25):
    """枝の輪 n（輪の節と中の支度・役・確かめ。docs/plans/2026-10-07-lane-nodes.md）"""
    loop = f"fixing__tdd-lane-loop-{n}"
    return [*node(loop, start, end, usd=None, kind="loop_group"), *node(f"{loop}.tdd-lane-prep-{n}", start, start + 1, kind="exec"),
            *node(f"{loop}.tdd-lane-{n}", start + 1, end - 1, usd=usd), *node(f"{loop}.tdd-lane-step-{n}", end - 1, end, kind="exec")]


def full_events():
    tdd = "fixing__tdd-loop.tdd"
    fix = "fixing__fix-loop.fix"
    return [*node("start", 0, 5, kind="exec"), *node(tdd, 10, 15, usd=0.5),
            *lane(1, 20, 100), *lane(2, 21, 90), *lane(3, 22, 80),
            *node(fix, 210, 400, usd=2.0), *task(fix, "f1", 220, 300), *task(fix, "f2", 250, 380),
            *node("fixing__fix-loop", 205, 405, usd=3.25, kind="loop_group"), *node("report", 410, 420, usd=None),
            ev("tool_called", fix, 600)]


class CheckTest(unittest.TestCase):
    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp(prefix="canary-check-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.root = self.tmp / "canary"
        self.out_root = self.tmp / "origin"
        self.board = self.out_root / "artifacts" / "runs" / RUN / "board"
        self.db = self.root / "home" / "archon-home" / "archon.db"
        self.db.parent.mkdir(parents=True)

    def run_tool(self, *args):
        return subprocess.run([sys.executable, str(TOOL), *args], capture_output=True, text=True, encoding="utf-8", env=_env())

    def full(self):
        make_db(self.db, self.out_root, full_events())
        make_board(self.board, lanes=FULL_LANES, asks=[ANSWERED],
                   units={"applied": [1, 2], "conflict": [], "unmerged": [], "shared": [], "union": []})
        write(self.root / "home" / "runs" / f"{RUN}.json", {})
        write(self.root / "home" / "diffs" / f"run-{RUN}.diff",
              "diff --git a/calc.py b/calc.py\n--- a/calc.py\n+++ b/calc.py\n"
              "diff --git a/CHANGELOG.md b/CHANGELOG.md\n")

    def test_full_run_reports_every_feature_and_exits_zero(self):
        """canary の置き場の形（run-id は控えの一番新しい物・差分は home/diffs）から読み、(a)(b)(c) が yes なら 0"""
        self.full()
        got = self.run_tool(str(self.root), "--json")
        self.assertEqual(got.returncode, 0, got.stdout + got.stderr)
        doc = json.loads(got.stdout)
        f = doc["features"]
        self.assertEqual([f[k]["status"] for k in ("a_parallel", "b_overlap", "c_consult", "d_replan")],
                         ["yes", "yes", "yes", "no"])
        self.assertIn("TDD の輪の枝 3 本・枝の輪の同時の最大 3", f["a_parallel"]["why"])
        self.assertIn("修正役が当てた項目 2・修正役の下請けの同時の最大 2", f["a_parallel"]["why"])
        self.assertEqual(doc["agents"], {"fixing__fix-loop.fix": {"tasks": 2, "parallel": 2}})
        self.assertEqual(doc["lane_nodes"], {"lanes": 3, "parallel": 3}, "枝の輪と中の節は枝ごとに 1 本の区間")
        self.assertEqual([i["allowed_paths"][0] for i in doc["plan_items"]], ["calc.py", "textfmt.py", "textfmt.py"])
        # 費用は AI の節だけ（loop_group と exec は足さない）・報告の無い節は数える・時間は出来事の最初から最後まで
        self.assertEqual(doc["spend"], {"cost_usd": 3.25, "cost_missing_nodes": 1, "minutes": 10.0})
        self.assertEqual(doc["nodes"]["parallel"], 6, "22 秒: 枝の輪 3 本と中の役 2 つと支度 1 つ（輪の節と中の節を別に数える）")
        self.assertEqual(doc["diff_files"], ["calc.py", "CHANGELOG.md"])
        self.assertEqual(doc["tdd_lanes"][0]["loop"], "tdd-1")
        self.assertEqual(len(doc["tdd_lanes"]), 1)
        text = self.run_tool(str(self.root), RUN)
        self.assertEqual(text.returncode, 0)
        self.assertIn("(c) 範囲の相談: yes", text.stdout)
        self.assertIn("差分のファイル: calc.py・CHANGELOG.md", text.stdout)

    def test_reads_only(self):
        """db・盤面・置き場のどのファイルも書き換えない"""
        self.full()

        def snap():
            return {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(self.tmp.rglob("*")) if p.is_file()}

        before = snap()
        self.assertEqual(self.run_tool(str(self.root)).returncode, 0)
        self.assertEqual(snap(), before)

    def test_serial_lanes_and_unanswered_consults_are_not_yes(self):
        """枝が 2 本でも枝の輪が順（端が触れるだけ）なら (a) は no。見込みだけで字の食い違いで戻ったなら (b) は attempted。
        断った・聞けなかった相談だけなら (c) は attempted。終了コードは 1"""
        make_db(self.db, self.out_root, [*lane(1, 10, 50), *lane(2, 50, 90)])
        lanes = {"rows": [{"n": 1}, {"n": 2}], "shared": [], "expect": [[1, 2]],
                 "out": [{"lane": 1, "outcome": "merged", "merge": "clean"}, {"lane": 2, "outcome": "serial", "merge": "conflict"}]}
        make_board(self.board, lanes=lanes, asks=[{**ANSWERED, "status": "refused", "decision": ""}],
                   unsettled=[{"id": 2, "item": "1", "status": "unavailable"}], replans=1)
        got = self.run_tool("--db", str(self.db), "--run", RUN, "--json")
        self.assertEqual(got.returncode, 1, got.stderr)
        f = json.loads(got.stdout)["features"]
        self.assertEqual([f[k]["status"] for k in ("a_parallel", "b_overlap", "c_consult", "d_replan")],
                         ["no", "attempted", "attempted", "yes"])
        self.assertIn("refused・unavailable", f["c_consult"]["why"])

    def test_unsettled_consult_counts_and_trace_wins_on_same_id(self):
        """受け付けがまだ trace へ写していない run-place の答えも数える。同じ scope と id は trace の行だけ"""
        make_db(self.db, self.out_root, [])
        make_board(self.board, asks=[{**ANSWERED, "status": "refused"}],
                   unsettled=[{**ANSWERED}, {**ANSWERED, "id": 2, "decision": "deny", "granted_paths": []}])
        doc = canary_check.check(RUN, {"status": "completed"}, [], self.board)
        self.assertEqual([(r["id"], r["status"], r["settled"]) for r in doc["consults"]],
                         [(1, "refused", True), (2, "answered", False)])
        self.assertEqual(doc["features"]["c_consult"]["status"], "yes")
        self.assertEqual(doc["features"]["a_parallel"]["status"], "no")
        self.assertEqual(doc["features"]["b_overlap"]["status"], "no")
        self.assertEqual(doc["spend"], {"cost_usd": 0.0, "cost_missing_nodes": 0, "minutes": None})

    def test_fixer_union_counts_as_overlap(self):
        """修正役の締めの行の union（試験のファイルの挿しだけの合わせ）も (b) の yes"""
        make_db(self.db, self.out_root, [])
        make_board(self.board, units={"applied": [2, 3], "conflict": [], "unmerged": [], "shared": ["textfmt.py"],
                                      "union": ["test_textfmt.py"]})
        f = canary_check.check(RUN, {}, [], self.board)["features"]
        self.assertEqual(f["b_overlap"]["status"], "yes")
        self.assertIn("test_textfmt.py", f["b_overlap"]["why"])

    def test_refusals_exit_two_with_one_line(self):
        make_db(self.db, self.out_root, [])
        cases = {
            "引数なし": (),
            "--db と置き場の両方": ("--db", str(self.db), "--run", RUN, str(self.root)),
            "--db に --run が無い": ("--db", str(self.db)),
            "知らない旗": (str(self.root), RUN, "--nope"),
            "run が無い": ("--db", str(self.db), "--run", "missing"),
            "db が無い": ("--db", str(self.tmp / "none.db"), "--run", RUN),
            "控えが無い": (str(self.root),),
            "盤面が無い": ("--db", str(self.db), "--run", RUN),
        }
        for name, args in cases.items():
            with self.subTest(name):
                got = self.run_tool(*args)
                self.assertEqual(got.returncode, 2, got.stdout + got.stderr)
                self.assertEqual(got.stdout, "")
                self.assertEqual(len(got.stderr.strip().splitlines()), 1, got.stderr)
                self.assertTrue(got.stderr.startswith("canary_check.py: "))


if __name__ == "__main__":
    unittest.main()
