"""canary（dev/canary.sh・dev/canary-seed/・dev/canary-request.json・dev/canary_check.py）の検査（FAST）。

- 種: 種の写しで、種のテストは緑・依頼の 2 件のバグと CHANGELOG の行の欠けは在る（下の PROBES が赤）・試験の中だけに持つ参照の
  直し（FIXES）を当てると当てた件の PROBES だけが緑になり、全部当てれば全部緑で種のテストも緑のまま。
- (b) の前提: 種のテストのファイルは test_lib.py の 1 本で、README の決まりがテストをモジュールごとのクラスに足させる。2 件の
  受け入れのテストの参照（LANE_TESTS。各クラスの末尾に足す）は、種では自分の件だけ赤（TDD の赤）で、2 つの枝の test_lib.py は
  3 方向で字の食い違いなしに合い、合わせた木は全部の直しの後に緑。2 つの枝が同じ末尾（main の前）に足しても挿しだけの食い違い
  （union で合う）。依頼の 2 件は別のコードのファイルを名指す（修正案の項目がモジュールごとに分かれ、重なりはテストのファイルだけ）。
- 依頼は入口の依頼の型（写しの RL の REQUEST_SCHEMA）を通り、where のファイルが種に在る。
- 確かめ役 canary_check.py: 一時の置き場に sqlite の偽の archon.db（Archon の 2 つの表の要る列だけ）と偽の盤面（trace.jsonl・
  plan-fields.json・tdd-<k>/state.json と枝の差分の控え・run-place の相談の記録・report.md）を置き、(a)〜(d) の判じ・案の重なり・
  項目ごとのファイル・費用と取れない節・結末・時間・終了コードと、読むだけで何も書かないことを見る。
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
TESTS = "test_lib.py"   # 種のただ 1 本のテストのファイル（README の決まり）


def _changelog_has(name):
    return ("import pathlib; s = pathlib.Path('CHANGELOG.md').read_text(encoding='utf-8'); "
            "u = s.split('## [Unreleased]', 1)[1].split('\\n## ', 1)[0]; "
            f"assert any(l.startswith('- ') and {name!r} in l for l in u.splitlines())")


# 依頼の 2 件の約束（依頼の text・measured のとおり）と CHANGELOG の行。種では全部赤、参照の直しの後は緑
PROBES = {
    "mean": "import calc; assert calc.mean([1, 2, 3]) == 2 and calc.mean([5]) == 5",
    "initials": "import textfmt; assert textfmt.initials('dark factory line') == 'DFL' and textfmt.initials('') == ''",
    "changelog_mean": _changelog_has("mean"),
    "changelog_initials": _changelog_has("initials"),
}
# 参照の直し（件 → [(ファイル, 前, 後)]）。種には置かない（直しの答えを対象に渡さない）
FIXES = {
    "mean": [("calc.py", "return sum(xs) / (len(xs) - 1)", "return sum(xs) / len(xs)"),
             ("CHANGELOG.md", "## [Unreleased]\n", "## [Unreleased]\n\n- mean: 分母を個数にした（算術平均を返す）\n")],
    "initials": [("textfmt.py", 'return "".join(w[0] for w in words(s))', 'return "".join(w[0].upper() for w in words(s))'),
                 ("CHANGELOG.md", "## [Unreleased]\n", "## [Unreleased]\n\n- initials: 頭の字を大文字にした\n")],
}
FIX_PROBES = {"mean": {"mean", "changelog_mean"}, "initials": {"initials", "changelog_initials"}}
# 枝ごとの受け入れのテストの参照（件 → (足す所の後ろの字, 足すテスト)）。README の決まりどおりモジュールのクラスの末尾に足す
CLASS_END = {"mean": "\n\n\nclass TestTextfmt(", "initials": '\n\n\nif __name__ == "__main__":'}
LANE_TESTS = {
    "mean": "\n\n    def test_mean_arithmetic(self):\n        self.assertEqual(calc.mean([1, 2, 3]), 2)\n",
    "initials": "\n\n    def test_initials_lowercase(self):\n        self.assertEqual(textfmt.initials(\"dark factory line\"), \"DFL\")\n",
}
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


def with_lane_tests(text: str, *names) -> str:
    """test_lib.py の中身に、件ごとの受け入れのテストを各クラスの末尾に足した物"""
    for name in names:
        anchor = CLASS_END[name]
        assert text.count(anchor) == 1, anchor
        text = text.replace(anchor, LANE_TESTS[name].rstrip("\n") + anchor)
    return text


class SeedTest(unittest.TestCase):
    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp(prefix="canary-seed-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def copy(self, fixes=(), tests=()):
        d = self.tmp / "-".join(["seed", *fixes, "t", *tests])
        shutil.copytree(SEED, d)
        for name in fixes:
            for rel, old, new in FIXES[name]:
                p = d / rel
                text = p.read_text(encoding="utf-8")
                self.assertEqual(text.count(old), 1, f"参照の直し {name} の前の字が {rel} に 1 つだけ在る")
                p.write_text(text.replace(old, new), encoding="utf-8")
        if tests:
            p = d / TESTS
            p.write_text(with_lane_tests(p.read_text(encoding="utf-8"), *tests), encoding="utf-8")
        return d

    def probes(self, d) -> dict:
        got = subprocess.run([sys.executable, "-c", PROBE_RUN, json.dumps(PROBES)], cwd=d, env=_env(),
                             capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(got.returncode, 0, got.stderr)
        return json.loads(got.stdout)

    def suite(self, d) -> tuple:
        got = subprocess.run([sys.executable, "-m", "unittest", "-v"], cwd=d, env=_env(), capture_output=True, text=True,
                             encoding="utf-8")
        failed = sorted(line.split(" ", 1)[0] for line in got.stderr.splitlines()
                        if line.endswith(" ... FAIL") or line.endswith(" ... ERROR"))
        return got.returncode, failed, got.stderr

    def suite_green(self, d):
        rc, failed, err = self.suite(d)
        self.assertEqual((rc, failed), (0, []), err[-2000:])
        self.assertIn("OK", err)

    def test_seed_suite_green_and_every_bug_present(self):
        """種のテストは緑（バグを突くテストはまだ無い）で、依頼の 2 件の約束と CHANGELOG の行は全部赤"""
        d = self.copy()
        self.suite_green(d)
        self.assertEqual(self.probes(d), {k: False for k in PROBES})

    def test_each_reference_fix_flips_only_its_own_probes(self):
        """参照の直しは件ごとに独立: 1 件を当てるとその件の約束と CHANGELOG の行だけが緑になる"""
        for name in FIXES:
            with self.subTest(name):
                got = self.probes(self.copy((name,)))
                self.assertEqual({k for k, v in got.items() if v}, FIX_PROBES[name])

    def test_all_reference_fixes_pass_and_keep_suite_green(self):
        d = self.copy(tuple(FIXES))
        self.assertEqual(self.probes(d), {k: True for k in PROBES})
        self.suite_green(d)

    def test_lane_tests_are_red_on_seed_only_for_their_own_bug(self):
        """TDD の赤: 件ごとの受け入れのテストは種では自分のテストだけ落ち、自分の件の直しで緑になる"""
        for name, test in (("mean", "test_mean_arithmetic"), ("initials", "test_initials_lowercase")):
            with self.subTest(name):
                rc, failed, err = self.suite(self.copy(tests=(name,)))
                self.assertEqual((rc != 0, failed), (True, [test]), err[-2000:])
                self.suite_green(self.copy((name,), (name,)))

    def merge(self, base: str, ours: str, theirs: str, *flags) -> tuple:
        for n, text in (("base", base), ("ours", ours), ("theirs", theirs)):
            (self.tmp / n).write_text(text, encoding="utf-8")
        got = subprocess.run(["git", "merge-file", "-p", *flags, str(self.tmp / "ours"), str(self.tmp / "base"),
                              str(self.tmp / "theirs")], capture_output=True, text=True, encoding="utf-8")
        return got.returncode, got.stdout

    def test_two_lanes_tests_merge_cleanly_in_one_test_file(self):
        """(b) の前提: 2 つの枝が test_lib.py の別々のクラスの末尾に足すテストは、3 方向で字の食い違いなしに合い（重なりの
        ファイル）、合わせた test_lib.py は全部の直しの後に緑"""
        base = (SEED / TESTS).read_text(encoding="utf-8")
        ours, theirs = with_lane_tests(base, "mean"), with_lane_tests(base, "initials")
        rc, merged = self.merge(base, ours, theirs)
        self.assertEqual(rc, 0, "字の食い違いが出た")
        self.assertEqual(merged, with_lane_tests(base, "mean", "initials"))
        d = self.copy(tuple(FIXES))
        (d / TESTS).write_text(merged, encoding="utf-8")
        self.suite_green(d)

    def test_tests_appended_to_same_tail_are_insertion_only_conflicts(self):
        """(b) の前提の続き: 2 つの枝が test_lib.py の同じ末尾（main の前）に足すテストは挿しだけの食い違いで、union で両方残る"""
        base = (SEED / TESTS).read_text(encoding="utf-8")
        tail = '\n\n\nif __name__ == "__main__":'
        self.assertEqual(base.count(tail), 1)
        add = "\n\n\nclass Test{0}(unittest.TestCase):\n    def test_{1}(self):\n        self.assertTrue(True)"
        ours = base.replace(tail, add.format("Mean", "mean") + tail)
        theirs = base.replace(tail, add.format("Initials", "initials") + tail)
        rc, _ = self.merge(base, ours, theirs)
        self.assertGreater(rc, 0, "末尾の挿しが食い違わないなら union の道を通らない")
        rc, merged = self.merge(base, ours, theirs, "--union")
        self.assertEqual(rc, 0)
        self.assertIn("class TestMean", merged)
        self.assertIn("class TestInitials", merged)

    def test_request_passes_entry_schema_and_names_separate_modules(self):
        """依頼は入口の型を通り、where は種に在る別々のコードのファイルを名指す（項目はモジュールごと・重なりはテストのファイル）。
        種のテストのファイルは 1 本で README がその置き方を決める。範囲の相談を通すため、各件は CHANGELOG.md を allowed_paths にも
        out_of_scope にも入れないと修正案に言う"""
        _, _, items, _, _ = entry._read_request(str(REQUEST), SEED, entry.board_rules())
        files = [it["where"].split(":", 1)[0] for it in items]
        for f in files:
            self.assertTrue((SEED / f).is_file(), f)
        self.assertEqual(sorted(files), ["calc.py", "textfmt.py"])
        self.assertEqual(sorted(p.name for p in SEED.glob("test*.py")), [TESTS])
        readme = (SEED / "README.md").read_text(encoding="utf-8")
        for word in (TESTS, "TestCalc", "TestTextfmt", "CHANGELOG.md"):
            self.assertIn(word, readme)
        for it in items:
            for word in ("CHANGELOG.md", "allowed_paths", "out_of_scope", "範囲の相談", TESTS):
                self.assertIn(word, it["text"], it["where"])
        self.assertIn("## [Unreleased]", (SEED / "CHANGELOG.md").read_text(encoding="utf-8"))

    def test_seed_holds_no_request_pack_or_answers(self):
        """種は対象にそのまま写る: 依頼・pack の写し・参照の直しを持たない"""
        names = {p.relative_to(SEED).as_posix() for p in SEED.rglob("*") if p.is_file()}
        self.assertEqual(names, {".gitignore", "README.md", "CHANGELOG.md", "calc.py", "textfmt.py", TESTS})


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


U_MEAN, U_INITIALS = "calc.py:mean 分母", "textfmt.py:initials 大文字"
ITEMS = [{"route": "tdd", "unit_keys": [U_MEAN], "allowed_paths": ["calc.py"],
          "tests": [{"id": "test_lib.py::TestCalc::test_mean_arithmetic"}]},
         {"route": "tdd", "unit_keys": [U_INITIALS], "allowed_paths": ["textfmt.py"],
          "tests": [{"id": "test_lib.py::TestTextfmt::test_initials_lowercase"}]}]


def make_board(board, *, lanes=None, units=None, asks=(), unsettled=(), replans=0, items=ITEMS, patches=None, report=None):
    write(board / "plan-fields.json", {"round": 1, "fields": items})
    trace = [{"t": "x", "op": "init"}]
    if units is not None:
        trace.append({"t": "x", "op": "units_settled", "node": "fix-units", "machine": [], "carried": 0, **units,
                      "scope": "fixing"})
    trace += [{"t": "x", "op": "plan_scope_asked", **a, "scope": "fixing"} for a in asks]
    trace += [{"t": "x", "op": "replan_state", "id": f"c1-{n}", "state": "amended"} for n in range(replans)]
    write(board / "trace.jsonl", "\n".join(json.dumps(r, ensure_ascii=False) for r in trace) + "\n{broken\n")
    if lanes is not None:
        write(board / "tdd-1" / "state.json", {"phase": "fix", "lanes": lanes})
    for n, files in (patches or {}).items():
        write(board / "tdd-1" / "lanes" / f"item-{n}.patch", "".join(f"diff --git a/{f} b/{f}\n--- a/{f}\n+++ b/{f}\n"
                                                                      for f in files))
    if report is not None:
        write(board / "report.md", report)
    write(board / "tdd-2" / "state.json", {"phase": "route"})   # 並べなかった輪は数えない
    if unsettled:
        write(board.parent / "run-place" / "fixing" / "ask-plan" / "exchanges.jsonl",
              "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in unsettled))


FULL_LANES = {"rows": [{"n": 1, "unit_keys": [U_MEAN]}, {"n": 2, "unit_keys": [U_INITIALS]}, {"n": 3, "unit_keys": ["u3"]}],
              "shared": ["test_lib.py"], "expect": [[1, 2]],
              "out": [{"unit_key": U_MEAN, "outcome": "merged", "lane": 1, "merge": "clean"},
                      {"unit_key": U_INITIALS, "outcome": "merged", "lane": 2, "merge": "clean"},
                      {"unit_key": "u3", "outcome": "merged", "lane": 3, "merge": "union"}]}
FULL_PATCHES = {1: ["calc.py", "test_lib.py"], 2: ["test_lib.py", "textfmt.py"]}
FULL_REPORT = "# 報告（run x）\n\n起きたこと: 直した（fixed）\n決めてほしいこと: 無い\n"
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
        make_board(self.board, lanes=FULL_LANES, asks=[ANSWERED], patches=FULL_PATCHES, report=FULL_REPORT,
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
        self.assertEqual([(i["item"], i["files"], i["test_files"]) for i in doc["plan_items"]],
                         [(1, ["calc.py", "test_lib.py"], ["test_lib.py"]), (2, ["test_lib.py", "textfmt.py"], ["test_lib.py"])])
        self.assertEqual(doc["planned_overlap"], {"test_lib.py": [1, 2]}, "項目はモジュールごと・重なりはテストのファイル")
        self.assertIn("案の重なり test_lib.py 項目 [1, 2]", f["b_overlap"]["why"])
        self.assertEqual([(r["lane"], r["items"], r["files"]) for r in doc["tdd_lanes"][0]["rows"]],
                         [(1, [1], ["calc.py", "test_lib.py"]), (2, [2], ["test_lib.py", "textfmt.py"]), (3, [], None)])
        self.assertEqual(doc["outcome"], "fixed")
        # 費用は AI の節だけ（loop_group と exec は足さない）・報告の無い節は名と理由つきで数える・時間は出来事の最初から最後まで
        missing = doc["spend"].pop("cost_missing")
        self.assertEqual(doc["spend"], {"cost_usd": 3.25, "cost_missing_nodes": 1, "minutes": 10.0})
        self.assertEqual([m["node"] for m in missing], ["report"])
        self.assertIn("unavailable", missing[0]["why"])
        self.assertEqual(doc["nodes"]["parallel"], 6, "22 秒: 枝の輪 3 本と中の役 2 つと支度 1 つ（輪の節と中の節を別に数える）")
        self.assertEqual(doc["diff_files"], ["calc.py", "CHANGELOG.md"])
        self.assertEqual(doc["tdd_lanes"][0]["loop"], "tdd-1")
        self.assertEqual(len(doc["tdd_lanes"]), 1)
        text = self.run_tool(str(self.root), RUN)
        self.assertEqual(text.returncode, 0)
        self.assertIn("(c) 範囲の相談: yes", text.stdout)
        self.assertIn("差分のファイル: calc.py・CHANGELOG.md", text.stdout)
        self.assertIn("結末 fixed", text.stdout)
        self.assertIn("  1 tdd 範囲 ['calc.py']・テスト ['test_lib.py']・枝の差分 tdd-1 枝 1 ['calc.py', 'test_lib.py']", text.stdout)
        self.assertIn("取れない節 1: report", text.stdout)

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
        self.assertEqual(doc["features"]["b_overlap"]["status"], "attempted", "案の重なりだけで合わせの記録が無い")
        self.assertIn("案の重なり test_lib.py 項目 [1, 2]", doc["features"]["b_overlap"]["why"])
        self.assertEqual(doc["spend"], {"cost_usd": 0.0, "cost_missing_nodes": 0, "cost_missing": [], "minutes": None})
        self.assertEqual(doc["outcome"], "", "報告が無い")

    def test_plan_without_shared_file_is_no_overlap(self):
        """計画役が同じファイルの単位を 1 項目にまとめ、項目どうしがファイルを共にしなければ (b) は no で、そう言う
        （run 01004d2e の形: calc の項目と textfmt の 2 単位の項目。テストも別のファイル）"""
        make_db(self.db, self.out_root, [])
        merged = [{"route": "tdd", "unit_keys": [U_MEAN], "allowed_paths": ["calc.py", "test_calc.py"]},
                  {"route": "tdd", "unit_keys": [U_INITIALS, "u3"], "allowed_paths": ["textfmt.py", "test_textfmt.py"]}]
        make_board(self.board, items=merged, report="起きたこと: 決めた周の数のうちに直しきれずに止まった（round_limit）\n")
        doc = canary_check.check(RUN, {}, [], self.board)
        self.assertEqual(doc["planned_overlap"], {})
        self.assertEqual(doc["features"]["b_overlap"]["status"], "no")
        self.assertIn("1 項目にまとめた", doc["features"]["b_overlap"]["why"])
        self.assertEqual(doc["outcome"], "round_limit")

    def test_fixer_union_counts_as_overlap(self):
        """修正役の締めの行の union（試験のファイルの挿しだけの合わせ）も (b) の yes"""
        make_db(self.db, self.out_root, [])
        make_board(self.board, units={"applied": [1, 2], "conflict": [], "unmerged": [], "shared": ["test_lib.py"],
                                      "union": ["test_lib.py"]})
        f = canary_check.check(RUN, {}, [], self.board)["features"]
        self.assertEqual(f["b_overlap"]["status"], "yes")
        self.assertIn("union ['test_lib.py']", f["b_overlap"]["why"])

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
