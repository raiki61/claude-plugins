"""会社の形（会社の形の設計 4.2・4.4・9.1）: 部署の属性（gitx）、ツリー図（tree ノードと --tree）、herdr の表示の付け直し（sync ノードと
--sync）、部署の片付け（clean.departments・retire と --clean）。git は一時のフォルダの本物、herdr・claude は偽物で回す。"""

import json
import os
import pathlib
import subprocess
import tempfile
import unittest
import urllib.parse

from . import DISPATCH  # noqa: F401
from . import schemacheck
from .test_dispatch import FakeHerdr, FakePorts, gitx_source, make_cfg, run_main
from .test_provision import git, make_world
import gitx
import herdr as real_herdr
from nodes import clean, provision, sync, tree


def fake_runner(out="", rc=0):
    calls = []

    def run(argv, env=None):
        calls.append(list(argv))
        return subprocess.CompletedProcess(argv, rc, out, "")
    run.calls = calls
    return run


class Attrs(unittest.TestCase):
    """部署の属性（git の worktree ごとの設定 company.*）と、.git/info/exclude。"""

    def setUp(self):
        self.src, self.root = make_world()
        self.place = str(pathlib.Path(self.root) / "dept")
        git("-C", self.src, "worktree", "add", "-q", "-b", "dept/a", self.place, "origin/main")

    def test_attrs_are_empty_before_the_extension_and_stay_in_their_own_worktree(self):
        self.assertEqual(gitx.worktree_attrs(self.place), {})
        self.assertEqual(gitx.enable_worktree_config(self.src), "enabled")
        self.assertEqual(gitx.enable_worktree_config(self.src), "already")
        provision.mark(self.place, self.src, {"role": "調べ役", "boss-account": "p1", "boss": None}, gitx)
        provision.mark(self.place, self.src, {"role": "調べ役"}, gitx)   # 同じ値をもう一度書いても同じ
        self.assertEqual(gitx.worktree_attrs(self.place), {"role": "調べ役", "boss-account": "p1"})
        self.assertEqual(gitx.worktree_attrs(self.src), {})
        # 値は元の clone の .git/worktrees/<部署>/config.worktree に入り、共有の設定には入らない
        self.assertNotIn("company", git("-C", self.src, "config", "--local", "--list"))

    def test_extension_is_not_enabled_over_core_worktree_or_bare(self):
        git("-C", self.src, "config", "--local", "core.worktree", self.src)
        with self.assertRaises(gitx.GitError) as e:
            gitx.enable_worktree_config(self.src)
        self.assertIn("core.worktree", str(e.exception))

    def test_exclude_adds_the_line_once(self):
        path = pathlib.Path(self.src) / ".git" / "info" / "exclude"
        path.write_text("# mine", encoding="utf-8")
        self.assertEqual(provision.hide_claude_dir(self.place, gitx), "added")   # worktree から打っても共有の exclude
        self.assertEqual(provision.hide_claude_dir(self.src, gitx), "already")
        self.assertEqual(path.read_text(encoding="utf-8"), "# mine\n.claude/\n")

    def test_common_dir_and_root_of_a_linked_worktree_are_the_source(self):
        self.assertEqual(os.path.realpath(gitx.root_of(gitx.common_dir(self.place))), os.path.realpath(self.src))
        self.assertIsNone(gitx.common_dir(tempfile.mkdtemp()))
        self.assertEqual(gitx.root_of(os.path.join("x", "bare.git")), os.path.join("x", "bare.git"))

    def test_is_merged_reads_the_target(self):
        self.assertTrue(gitx.is_merged(self.place, "refs/remotes/origin/main"))
        git("-C", self.place, "-c", "user.name=o", "-c", "user.email=o@o", "commit", "-q", "--allow-empty", "-m", "x")
        self.assertFalse(gitx.is_merged(self.place, "refs/remotes/origin/main"))


class HerdrPorts(unittest.TestCase):
    def test_workspaces_take_the_repo_root_or_none(self):
        run = fake_runner(json.dumps({"result": {"workspaces": [
            {"workspace_id": "w1", "label": "r", "worktree": {"repo_root": "/s/r", "checkout_path": "/s/r"}},
            {"workspace_id": "w2", "label": "notes"}]}}))
        self.assertEqual(real_herdr.workspaces(runner=run), [
            {"workspace_id": "w1", "label": "r", "repo_root": os.path.normpath("/s/r")},
            {"workspace_id": "w2", "label": "notes", "repo_root": None}])

    def test_metadata_sets_and_clears_in_one_call(self):
        run = fake_runner("")
        real_herdr.report_pane_metadata("p", "company", "調べ役", None, {"role": "調べ役"}, ["boss"], runner=run)
        self.assertEqual(run.calls, [["herdr", "pane", "report-metadata", "p", "--source", "company", "--display-agent", "調べ役",
                                      "--clear-title", "--token", "role=調べ役", "--clear-token", "boss"]])

    def test_read_returns_the_screen_text(self):
        self.assertEqual(real_herdr.read("p", 3, runner=fake_runner("a\nb\n")), "a\nb\n")
        with self.assertRaises(real_herdr.HerdrError):
            real_herdr.read("p", 3, runner=fake_runner("", rc=1))


def write(path, text):
    pathlib.Path(path).parent.mkdir(parents=True, exist_ok=True)
    pathlib.Path(path).write_text(text, encoding="utf-8")
    return str(path)


class Info(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="company-")
        self.settings = tempfile.mkdtemp(prefix="company-settings-")

    def test_none_without_a_file(self):
        got = tree.read_info(self.root, self.settings)
        self.assertEqual((got["source"], got["skills"], got["problems"]), (None, [], []))

    def test_settings_file_is_read_when_the_repo_has_none(self):
        local = write(tree.settings_info_path(self.settings, self.root), 'name = "ノート"\n[[skills]]\nid = "r"\nname = "調べもの"\n')
        self.assertEqual(os.path.basename(local), urllib.parse.quote(os.path.realpath(self.root), safe="") + ".toml")
        got = tree.read_info(self.root, self.settings)
        self.assertEqual((got["source"], got["name"]), ("settings", "ノート"))
        self.assertEqual(got["skills"], [{"id": "r", "name": "調べもの", "description": None, "role": None}])

    def test_repo_file_wins_and_unknown_fields_are_skipped(self):
        write(tree.settings_info_path(self.settings, self.root), 'name = "手元"\n')
        write(os.path.join(self.root, ".claude", "company.toml"),
              'name = "会社"\ndescription = "説明"\nversion = "1"\n'
              '[[skills]]\nid = "r"\nname = "調べもの"\ndescription = "結論と原典の一句"\nrole = "調べ役"\ntags = ["x"]\n')
        got = tree.read_info(self.root, self.settings)
        self.assertEqual((got["source"], got["name"], got["description"]), ("repo", "会社", "説明"))
        self.assertEqual(got["skills"][0]["role"], "調べ役")

    def test_broken_file_is_a_problem_and_does_not_fall_back(self):
        write(os.path.join(self.root, ".claude", "company.toml"), "name = \n")
        write(tree.settings_info_path(self.settings, self.root), 'name = "手元"\n')
        got = tree.read_info(self.root, self.settings)
        self.assertEqual(got["source"], "repo")
        self.assertIsNone(got["name"])
        self.assertIn("TOML として読めない", got["problems"][0])

    def test_wrong_shapes_are_named(self):
        write(os.path.join(self.root, ".claude", "company.toml"), 'name = 3\nskills = [{ id = "x" }]\n')
        got = tree.read_info(self.root, None)
        self.assertEqual(len(got["problems"]), 2)


class Build(unittest.TestCase):
    PLACES = {"/s/r": [{"path": "/s/r", "branch": "main", "linked": False, "workspace": "w1"},
                       {"path": "/wt/r/a", "branch": "dept/a", "linked": True, "workspace": "w2"},
                       {"path": "/wt/r/b", "branch": "dept/b", "linked": True, "workspace": None},
                       {"path": "/wt/r/gone", "branch": "x", "linked": True, "prunable": True}]}
    ATTRS = {"/wt/r/a": {"role": "調べ役", "residency": "resident", "account": "p2", "name": "調べ", "session": "s-a",
                         "boss": "窓口"}}

    def build(self, panes=(), sessions=None):
        return tree.build(["/s/r"], self.PLACES, list(panes), lambda p: self.ATTRS.get(p, {}),
                          lambda root: {"source": None, "name": None, "skills": [], "problems": []}, sessions)

    def test_departments_carry_attrs_session_state_and_window(self):
        sessions = {"p2": [{"id": "a1", "sessionId": "s-a", "name": "調べ", "cwd": "/elsewhere", "kind": "background",
                            "state": "blocked", "startedAt": 2}],
                    "p1": [{"sessionId": "s-h", "name": "窓口", "cwd": "/s/r/sub", "kind": "interactive", "status": "busy"},
                           {"id": "b1", "sessionId": "s-b", "name": "古い", "cwd": "/wt/r/b", "kind": "background",
                            "state": "done", "startedAt": 1}]}
        panes = [{"pane_id": "w2:p1", "workspace_id": "w2", "cwd": "/wt/r/a", "agent": "claude", "label": "調べ p2"}]
        [c] = self.build(panes, sessions)
        self.assertEqual(c["name"], "r")
        head, a, b = c["departments"]
        self.assertTrue(head["head_office"])
        self.assertEqual((head["state"], head["account"], head["panes"]), ("working", "p1", []))
        # 部署の会話は属性の会話の id で結ぶ（会話の作業フォルダが部署の外でも）
        self.assertEqual((a["state"], a["role"], a["account"], a["boss"], a["session"]["id"]), ("blocked", "調べ役", "p2", "窓口", "a1"))
        self.assertEqual([p["pane_id"] for p in a["panes"]], ["w2:p1"])
        # 属性の無い部署は、会話の作業フォルダの場所で結び、アカウントと名前は会話から
        self.assertEqual((b["state"], b["account"], b["name"], b["role"]), ("done", "p1", "古い", None))
        self.assertEqual(len(c["departments"]), 3)   # prunable は並べない
        out = {"schema": 1, "companies": [c], "notes": []}
        self.assertEqual(schemacheck.check(out, schemacheck.schema("tree")), [])

    def test_lines_show_the_tree(self):
        sessions = {"p2": [{"id": "a1", "sessionId": "s-a", "cwd": "/wt/r/a", "kind": "background", "state": "working"}]}
        text = "\n".join(tree.lines(self.build((), sessions)))
        self.assertIn("r  /s/r  （会社の情報なし）", text)
        self.assertIn("  本社 main  会話なし", text)
        self.assertIn("  ├ dept/a  作業中  会話 調べ  役 調べ役（常駐）  アカウント p2  上役 窓口  窓 なし", text)
        self.assertIn("  └ dept/b  会話なし  役 -  アカウント -  上役 -  窓 なし", text)

    def test_roots_come_from_herdr_then_from_conversations(self):
        common = {"/notes": "/notes", "/wt/n/x": "/notes", "/r2/sub": "/r2"}
        got = tree.roots([{"workspace_id": "w1", "repo_root": "/s/r"}, {"workspace_id": "w9", "repo_root": None},
                          {"workspace_id": "w8", "repo_root": None}],
                         [{"workspace_id": "w9", "cwd": "/notes"}], common.get, ["/wt/n/x", "/r2/sub", "/nowhere"])
        self.assertEqual(got, ["/s/r", "/notes", "/r2"])


class Sync(unittest.TestCase):
    def company(self, *depts):
        return [{"name": "r", "departments": list(depts)}]

    def dept(self, attrs, panes, branch="dept/a"):
        return {"branch": branch, "path": "/wt", "attrs": attrs, "panes": panes}

    def test_plan_names_and_tags_the_conversation_pane_only_where_attrs_exist(self):
        attrs = {"role": "調べ役", "account": "p2", "name": "調べ", "boss": "窓口"}
        ops, notes = sync.plan(self.company(
            self.dept(attrs, [{"pane_id": "a", "agent": None}, {"pane_id": "b", "agent": "claude", "label": "x"}]),
            self.dept({}, [{"pane_id": "c", "agent": "claude"}])), many_accounts=True)
        self.assertEqual(ops, [{"pane": "b", "label": "調べ p2", "display_agent": "調べ役", "title": "調べ",
                                "tokens": {"role": "調べ役", "account": "p2", "boss": "窓口"}, "clear_tokens": []}])
        self.assertEqual(notes, [])

    def test_same_label_is_not_renamed_and_missing_values_are_cleared(self):
        op = sync.op("p", {"name": "調べ", "account": "p2"}, many_accounts=False, current_label="調べ")
        self.assertEqual((op["label"], op["display_agent"], op["clear_tokens"]), (None, None, ["role", "boss"]))

    def test_single_quiet_pane_is_used_and_none_is_noted(self):
        ops, notes = sync.plan(self.company(self.dept({"name": "a"}, [{"pane_id": "p", "agent": None}]),
                                            self.dept({"name": "b"}, [], branch="dept/b")), many_accounts=False)
        self.assertEqual([o["pane"] for o in ops], ["p"])
        self.assertIn("dept/b: 付ける先のペインが無い（作業場が開いていない）", notes[0])

    def test_apply_keeps_going_after_a_failure(self):
        class H:
            HerdrError = real_herdr.HerdrError
            calls = []

            def rename_pane(self, pane, label):
                if pane == "bad":
                    raise real_herdr.HerdrError(["herdr"], "pane_not_found")
                self.calls.append(("rename", pane, label))

            def report_pane_metadata(self, pane, source, display_agent, title, tokens, clear_tokens=()):
                self.calls.append(("meta", pane, source))

        ops = [sync.op("bad", {"name": "x"}, False), sync.op("ok", {"name": "y"}, False)]
        got = sync.apply(ops, H())
        self.assertEqual([g["status"] for g in got], ["failed", "done"])
        self.assertEqual(H.calls, [("rename", "ok", "y"), ("meta", "ok", "company")])


class CompanyHerdr(FakeHerdr):
    """FakeHerdr に、作業場の並び（元の clone の作業場と、git の印の無いノートの作業場）を足す。"""

    def __init__(self, source):
        super().__init__()
        self.source = source

    def workspaces(self):
        seen = {p["workspace_id"] for p in self._panes}
        return [{"workspace_id": w, "label": w, "repo_root": self.source if w in self._wt.values() else None} for w in sorted(seen)]


class Entry(unittest.TestCase):
    """入口の --tree・--json・--sync。dispatch の設定のアカウントの会話の一覧も偽物で渡す。"""

    def setUp(self):
        self.cfg, self.root = make_cfg()
        self.src = gitx_source(self.cfg)
        self.place = str(pathlib.Path(self.root) / "dept")
        git("-C", self.src, "worktree", "add", "-q", "-b", "dept/a", self.place, "origin/main")
        provision.mark(self.place, self.src, {"role": "調べ役", "account": "a1", "name": "調べ", "session": "s-a"}, gitx)
        self.ports = FakePorts([])
        self.ports.herdr = CompanyHerdr(self.src)
        self.ports.herdr.open_at(self.src)
        self.pane = self.ports.herdr.open_at(self.place, agent="claude")["pane_id"]
        self.ports.list_sessions = lambda cdir, include_done=False: [
            {"id": "a", "sessionId": "s-a", "name": "調べ", "cwd": self.place, "kind": "background", "state": "working"}]

    def main(self, *argv):
        return run_main(["--config", self.cfg, *argv], self.ports)

    def test_tree_prints_the_company_and_its_departments(self):
        rc, out = self.main("--tree")
        self.assertEqual(rc, 0, out)
        self.assertIn(f"{os.path.basename(self.src)}  {self.src}  （会社の情報なし）", out)
        self.assertIn("  本社 main  会話なし", out)
        self.assertIn("  └ dept/a  作業中  会話 調べ  役 調べ役  アカウント a1  上役 -  窓 あり", out)

    def test_tree_json_matches_the_schema(self):
        rc, out = self.main("--tree", "--json")
        self.assertEqual(rc, 0, out)
        got = json.loads(out)
        self.assertEqual(schemacheck.check(got, schemacheck.schema("tree")), [])
        self.assertEqual(got["companies"][0]["departments"][1]["attrs"]["session"], "s-a")

    def test_tree_works_without_a_config(self):
        rc, out = run_main(["--config", str(pathlib.Path(self.root).parent / "none.toml"), "--tree"], self.ports)
        self.assertEqual(rc, 0, out)
        self.assertNotIn("設定を読めない", out)
        self.assertIn("dept/a", out)

    def test_sync_tags_the_department_pane_and_dry_run_writes_nothing(self):
        rc, out = self.main("--sync", "--dry-run")
        self.assertEqual(rc, 0, out)
        self.assertEqual(self.ports.herdr.writes, [])
        self.assertIn(f"ペイン {self.pane}: 名前 調べ  表示名 調べ役  題名 調べ  札 role=調べ役、account=a1", out)
        rc, out = self.main("--sync")
        self.assertEqual(rc, 0, out)
        self.assertEqual(self.ports.herdr.writes, [
            ("rename_pane", self.pane, "調べ"),
            ("report_pane_metadata", self.pane, "調べ役", "調べ", {"role": "調べ役", "account": "a1"}, ["boss"])])

    def test_flags_go_together(self):
        for argv in (["--tree", "--sync"], ["--json"], ["--sync", "--json"], ["--tree", "--dry-run"]):
            with self.subTest(argv=argv):
                rc, out = self.main(*argv)
                self.assertEqual(rc, 2, out)

    def test_herdr_that_cannot_be_read_stops_with_one_line(self):
        def broken():
            raise real_herdr.HerdrError(["herdr", "pane", "list"], "no socket")
        self.ports.herdr.panes = broken
        rc, out = self.main("--tree")
        self.assertEqual(rc, 1)
        self.assertIn("止めた: herdr を読めない", out)


class Departments(unittest.TestCase):
    """部署の片付け: 会話が終わり、手元の作業が無く、枝が本流に入った部署だけを、claude rm と一緒に消す。"""

    def setUp(self):
        self.cfg, self.root = make_cfg()
        self.src = gitx_source(self.cfg)
        self.ports = FakePorts([])
        self.place = self.dept("dept/a", "s-a")
        self.state = {"s-a": "done"}
        self.removed = []
        self.ports.list_sessions = lambda cdir, include_done=False: [
            {"id": sid[-1], "sessionId": sid, "state": st} for sid, st in self.state.items()] if include_done else []

    def dept(self, branch, session):
        path = self.ports.herdr.create_worktree(self.src, branch, "origin/main", branch)["path"]
        self.ports.herdr.writes.clear()
        provision.mark(path, self.src, {"name": branch, "session": session}, gitx)
        return path

    def clean(self, *extra):
        import dispatch
        real = dispatch.claudex.remove_session
        dispatch.claudex.remove_session = lambda cdir, sid, **kw: (self.removed.append((cdir, sid)) or (True, "removed"))
        try:
            return run_main(["--config", self.cfg, "--clean", *extra], self.ports)
        finally:
            dispatch.claudex.remove_session = real

    def test_finished_merged_department_is_listed_then_removed_with_its_session(self):
        rc, out = self.clean()
        self.assertEqual(rc, 0, out)
        self.assertIn("部署 dept/a dept/a  done  消せる", out)
        self.assertNotIn("no_pr", out)   # 部署は PR の片付けの並びに出さない
        self.assertIn("消すには --clean --apply を付けて打ち直す", out)
        rc, out = self.clean("--apply")
        self.assertEqual(rc, 0, out)
        self.assertIn("部署 dept/a 消した", out)
        self.assertEqual(self.removed, [(f"{pathlib.Path(self.cfg).parent}/c1", "a")])
        self.assertFalse(os.path.exists(self.place))

    def test_running_unpushed_and_unmerged_departments_are_kept(self):
        self.state["s-a"] = "working"
        git("-C", self.dept("dept/b", "s-b"), "-c", "user.name=o", "-c", "user.email=o@o", "commit", "-q", "--allow-empty", "-m", "x")
        self.state["s-b"] = "done"
        rc, out = self.clean("--apply")
        self.assertIn("部署 dept/a dept/a  working  残す（会話がまだ動いている）", out)
        self.assertIn("部署 dept/b dept/b  done  残す（手元にしか無い commit か stash が有る）", out)
        self.assertEqual(self.removed, [])

    def test_resident_department_is_never_removed(self):
        provision.mark(self.place, self.src, {"residency": "resident"}, gitx)
        rc, out = self.clean("--apply")
        self.assertIn("部署 dept/a dept/a  done  残す（常駐の部署は畳まない）", out)
        self.assertEqual(self.removed, [])
        self.assertTrue(os.path.exists(self.place))

    def test_retire_stops_when_rm_refuses(self):
        class C:
            @staticmethod
            def remove_session(cdir, sid):
                return False, "kept a — its worktree has unpushed commits"
        got = clean.retire({"path": self.place, "branch": "dept/a", "session": "a", "config_dir": "/c", "pr_head": None},
                           self.src, "x", self.ports.herdr, gitx, C)
        self.assertFalse(got["removed"])
        self.assertIn("claude rm が断った", got["detail"])
        self.assertTrue(os.path.exists(self.place))

    def test_department_whose_session_is_gone_is_still_judged_by_git(self):
        rows = clean.departments(self.ports.herdr.worktrees(self.src), gitx.worktree_attrs, lambda attrs: None, gitx.is_clean,
                                 gitx.unpushed, lambda p: True, gitx.head_sha, source=self.src)
        self.assertEqual([(r["state"], r["removable"], r["session"]) for r in rows], [("gone", True, None)])


if __name__ == "__main__":
    unittest.main()
