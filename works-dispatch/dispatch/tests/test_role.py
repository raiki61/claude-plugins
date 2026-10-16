"""役の渡し方（会社の形の設計 4.7・4.8）: 会社の形の役の項目（role ノード）、部署を起こすときの --settings・--model と gh の
アカウントの属性（launch と入口の --task）、役の本文と GH_TOKEN の行を足す SessionStart のフック（role_hook）。git は一時のフォルダの本物、herdr・claude は偽物で回す。"""

import contextlib
import io
import json
import os
import pathlib
import re
import shlex
import tempfile
import unittest
import urllib.parse

from . import DISPATCH
from .test_dispatch import FakeHerdr, gitx_source
from .test_provision import git, make_world
from . import test_task
import gitx
import role_hook
from nodes import launch, provision, role

SHAPE = '''
name = "試しの会社"
gh_user = "gh-co"

[[roles]]
name = "調べ役"
instructions = "結論と原典の一句を返す。"
model = "haiku"
settings = { enabledPlugins = { "pr-review-toolkit@m" = false }, permissions = { deny = ["Artifact", "Workflow"] }, worktree = { bgIsolation = "auto" } }

[[roles]]
name = "出荷役"
'''


def write(path, text):
    pathlib.Path(path).parent.mkdir(parents=True, exist_ok=True)
    pathlib.Path(path).write_text(text, encoding="utf-8")
    return str(path)


class Shape(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()

    def test_roles_and_gh_user_are_read(self):
        got = role.load(write(f"{self.d}/c.toml", SHAPE))
        self.assertEqual(got["problems"], [])
        self.assertEqual(got["gh_user"], "gh-co")
        self.assertEqual(got["roles"]["調べ役"]["model"], "haiku")
        self.assertEqual(got["roles"]["調べ役"]["instructions"], "結論と原典の一句を返す。")
        self.assertEqual(got["roles"]["出荷役"], {"name": "出荷役", "instructions": None, "model": None, "settings": None})

    def test_no_file_is_empty_and_broken_shapes_are_problems_but_others_are_read(self):
        self.assertEqual(role.load(None), {"roles": {}, "gh_user": None, "problems": []})
        got = role.load(write(f"{self.d}/c.toml", '''gh_user = 3
[[roles]]
instructions = "名前が無い"
[[roles]]
name = "a"
settings = "文字"
[[roles]]
name = "b"
[[roles]]
name = "b"
model = "x"
'''))
        self.assertEqual(list(got["roles"]), ["b"])
        self.assertIsNone(got["roles"]["b"]["model"])   # 2 度目は使わない
        self.assertEqual(len(got["problems"]), 4, got["problems"])
        self.assertIn("TOML", role.load(write(f"{self.d}/bad.toml", "[[roles]"))["problems"][0])

    def test_pick_stops_only_on_an_explicit_role_missing_from_a_shape_that_has_roles(self):
        shape = role.load(write(f"{self.d}/c.toml", SHAPE))
        self.assertEqual(role.pick(shape, "調べ役", True)[0]["name"], "調べ役")
        self.assertIn("在る役: 調べ役, 出荷役", role.pick(shape, "調べやく", True)[1])
        self.assertEqual(role.pick(shape, "作業役", False), (None, None))
        self.assertEqual(role.pick(role.load(None), "何か", True), (None, None))

    def test_settings_keep_the_role_keys_and_the_fixed_keys_win(self):
        r = role.load(write(f"{self.d}/c.toml", SHAPE))["roles"]["調べ役"]
        self.assertEqual(role.settings_for(r), {"enabledPlugins": {"pr-review-toolkit@m": False},
                                                "permissions": {"deny": ["Artifact", "Workflow"]},
                                                "worktree": {"bgIsolation": "none"}})
        self.assertEqual(role.settings_for(None), {"worktree": {"bgIsolation": "none"}})
        path = role.write_settings(self.d, role.settings_for(r))
        self.assertEqual(json.loads(pathlib.Path(path).read_text(encoding="utf-8")), role.settings_for(r))

    def test_users_own_gh_user_comes_first(self):
        self.assertEqual(role.gh_user(None, {"gh_user": "co"}), ("co", None))
        self.assertEqual(role.gh_user("me", {"gh_user": None}), ("me", None))
        user, note = role.gh_user("me", {"gh_user": "co"})
        self.assertEqual(user, "me")
        self.assertIn("co", note)

    def test_turning_this_plugin_off_is_warned(self):
        r = {"name": "x", "settings": {"enabledPlugins": {"works-dispatch@m": False, "other@m": False}}}
        self.assertEqual(len(role.warnings(r)), 1)
        self.assertEqual(role.warnings({"name": "x", "settings": {"enabledPlugins": {"works-dispatch@m": True}}}), [])
        self.assertEqual(role.warnings(None), [])

    def test_env_line_fetches_the_key_each_time_and_never_holds_it(self):
        self.assertEqual(role.env_line("gh-co"), 'export GH_TOKEN="$(gh auth token --user gh-co || echo gh-user-not-logged-in)"')
        self.assertEqual(shlex.split(role.env_line("a b")),
                         ["export", "GH_TOKEN=$(gh auth token --user 'a b' || echo gh-user-not-logged-in)"])

    def test_context_is_one_line_when_the_role_has_no_text(self):
        self.assertEqual(role.context("調べ役", {"instructions": "短く"}, "会社"), "この会話は会社「会社」の部署で、役は「調べ役」。\n短く")
        self.assertEqual(role.context("x", None, "会社"), "この会話は会社「会社」の部署で、役は「x」。")


class Launch(unittest.TestCase):
    ROW = {"account": {"command": "claude-a1"}, "label": None}

    def started(self, posix, **kw):
        h = FakeHerdr()
        got = launch.start_background(self.ROW, "P0", "直し", "s.json", "頼み", h, posix=posix, pause=lambda: None, **kw)
        return got, [w[2] for w in h.writes if w[0] == "run"][0]

    def test_model_is_put_before_the_first_text(self):
        got, command = self.started(True, model="haiku")
        self.assertEqual(got["status"], "sent")
        self.assertEqual(shlex.split(command), ["claude-a1", "--bg", "--name", "直し", "--settings", "s.json", "--model", "haiku", "頼み"])

    def test_without_model_the_command_is_as_before(self):
        _, command = self.started(True)
        self.assertEqual(shlex.split(command), ["claude-a1", "--bg", "--name", "直し", "--settings", "s.json", "頼み"])
        _, command = self.started(False, model="haiku")
        self.assertIn('--model "haiku"', command)


class Hook(unittest.TestCase):
    def setUp(self):
        self.src, root = make_world()
        self.place = str(pathlib.Path(root) / "dept")
        git("-C", self.src, "worktree", "add", "-q", "-b", "dept/a", self.place, "origin/main")
        self.env = {"WORKS_DISPATCH_CONFIG": str(pathlib.Path(root).parent / "conf" / "dispatch.toml")}

    def test_department_gets_its_role_text_and_other_places_get_nothing(self):
        write(pathlib.Path(self.src) / ".claude" / "company.toml", SHAPE)
        self.assertIsNone(role_hook.text_for(self.place, self.env))   # 役の属性が無い
        provision.mark(self.place, self.src, {"role": "調べ役"}, gitx)
        self.assertEqual(role_hook.text_for(self.place, self.env), "この会話は会社「試しの会社」の部署で、役は「調べ役」。\n結論と原典の一句を返す。")
        self.assertIsNone(role_hook.text_for(self.src, self.env))      # 本社
        self.assertIsNone(role_hook.text_for(tempfile.mkdtemp(), self.env))   # git でない

    def test_shape_outside_the_repo_is_read_and_a_missing_role_gets_only_the_head_line(self):
        conf = pathlib.Path(self.env["WORKS_DISPATCH_CONFIG"]).parent
        write(conf / "companies" / (urllib.parse.quote(os.path.realpath(self.src), safe="") + ".toml"), SHAPE)
        provision.mark(self.place, self.src, {"role": "出荷役"}, gitx)
        self.assertEqual(role_hook.text_for(self.place, self.env), "この会話は会社「試しの会社」の部署で、役は「出荷役」。")
        provision.mark(self.place, self.src, {"role": "無い役"}, gitx)
        self.assertEqual(role_hook.text_for(self.place, self.env), "この会話は会社「試しの会社」の部署で、役は「無い役」。")

    def test_shape_beside_the_departments_own_config_is_read(self):
        other = pathlib.Path(tempfile.mkdtemp()) / "mine.toml"
        write(other.parent / "companies" / (urllib.parse.quote(os.path.realpath(self.src), safe="") + ".toml"), SHAPE)
        provision.mark(self.place, self.src, {"role": "調べ役", "config": str(other)}, gitx)
        self.assertIn("結論と原典の一句", role_hook.text_for(self.place, self.env))

    def test_gh_user_is_put_into_the_env_file_once_without_the_key(self):
        provision.mark(self.place, self.src, {"role": "調べ役", "gh-user": "gh-co"}, gitx)
        envfile = pathlib.Path(tempfile.mkdtemp()) / "env.sh"
        envfile.write_text("export A=1\n", encoding="utf-8")
        env = {**self.env, "CLAUDE_ENV_FILE": str(envfile)}
        for _ in range(2):   # resume で 2 度走っても 1 行
            with contextlib.redirect_stdout(io.StringIO()):
                role_hook.main(io.StringIO(json.dumps({"cwd": self.place})), env)
        self.assertEqual(envfile.read_bytes().decode("utf-8"), "export A=1\n" + role.env_line("gh-co") + "\n")   # Windows でも \r 無し
        # 属性が無い・ファイルの場所が無いなら書かない
        role_hook.put_env({"role": "x"}, env)
        role_hook.put_env({"gh-user": "gh-co"}, self.env)
        self.assertEqual(len(envfile.read_text(encoding="utf-8").splitlines()), 2)

    def test_broken_shape_does_not_stop_the_conversation(self):
        write(pathlib.Path(self.src) / ".claude" / "company.toml", "[[roles]")
        provision.mark(self.place, self.src, {"role": "調べ役"}, gitx)
        self.assertIn("読めない所がある", role_hook.text_for(self.place, self.env))

    def test_main_prints_the_hook_output_only_for_a_department(self):
        provision.mark(self.place, self.src, {"role": "調べ役"}, gitx)
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            role_hook.main(io.StringIO(json.dumps({"cwd": self.place, "hook_event_name": "SessionStart"})), self.env)
        got = json.loads(out.getvalue())["hookSpecificOutput"]
        self.assertEqual(got["hookEventName"], "SessionStart")
        self.assertIn("調べ役", got["additionalContext"])
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            role_hook.main(io.StringIO(json.dumps({"cwd": self.src})), self.env)
        self.assertEqual(out.getvalue(), "")

    def test_plugin_declares_the_hook_on_the_existing_script(self):
        hooks = json.loads((pathlib.Path(DISPATCH).parent / "hooks" / "hooks.json").read_text(encoding="utf-8"))["hooks"]
        [command] = [h["command"] for grp in hooks["SessionStart"] for h in grp["hooks"]]
        self.assertIn("${CLAUDE_PLUGIN_ROOT}/dispatch/role_hook.py", command)
        self.assertTrue((pathlib.Path(DISPATCH) / "role_hook.py").is_file())


BG = re.compile(r"^(claude-a\d) --bg --name ")


class TaskWithRole(unittest.TestCase):
    """入口の --task が、会社の形の役の項目から --settings・--model・GH_TOKEN を渡す。場の作りは --task の試験のものを借りる
    （継ぐと、その試験が二度走る）。"""

    setUp, run_task, place = test_task.Task.setUp, test_task.Task.run_task, test_task.Task.place

    def ports(self, sessions=None, starts=True):
        ports = test_task.Task.ports(self, sessions, starts)
        d = pathlib.Path(self.cfg).parent
        dirs = {"claude-a1": f"{d}/c1"}

        def listed(cdir, include_done=False):
            got = []
            for i, w in enumerate(x for x in ports.herdr.writes if x[0] == "run" and BG.search(x[2])):
                if dirs[BG.search(w[2]).group(1)] == cdir:
                    cwd = next(p["cwd"] for p in ports.herdr.panes() if p["pane_id"] == w[1])
                    got.append({"id": f"bg{i}", "sessionId": f"bg{i}-full", "name": "直し", "cwd": cwd, "kind": "background",
                                "state": "working", "startedAt": i})
            return got

        ports.list_sessions = listed
        return ports

    def shape(self, text=SHAPE):
        write(pathlib.Path(gitx_source(self.cfg)) / ".claude" / "company.toml", text)

    def test_reused_place_drops_the_attrs_of_the_previous_run(self):
        src = gitx_source(self.cfg)
        place = str(pathlib.Path(self.root) / "reused")
        git("-C", src, "worktree", "add", "-q", "-b", "task/fix", place, "origin/main")
        provision.mark(place, src, {"gh-user": "old", "config": "old.toml", "boss": "old-boss"}, gitx)
        rc, out = self.run_task(self.ports())   # 会社の形も gh_user も無い回
        self.assertEqual(rc, 0, out)
        attrs = gitx.worktree_attrs(place)
        self.assertNotIn("gh-user", attrs)
        self.assertNotIn("boss", attrs)
        self.assertEqual(attrs["config"], self.cfg)

    def test_role_settings_model_and_gh_user_reach_the_department(self):
        self.shape()
        ports = self.ports()
        rc, out = self.run_task(ports, "--role", "調べ役")
        self.assertEqual(rc, 0, out)
        [command] = [w[2] for w in ports.herdr.writes if w[0] == "run" and BG.search(w[2])]
        path = self.place(ports)
        settings = os.path.join(gitx.git_dir(path), role.SETTINGS_FILE)
        self.assertEqual(json.loads(pathlib.Path(settings).read_text(encoding="utf-8"))["worktree"], {"bgIsolation": "none"})
        if os.name != "nt":
            self.assertEqual(shlex.split(command)[:8], ["claude-a1", "--bg", "--name", "直し", "--settings", settings, "--model", "haiku"])
        self.assertNotIn("GH_TOKEN", command)
        # gh のアカウントは名前だけを部署の属性に書く（鍵はフックが会話の Bash に入れる）。既定の設定の置き場でないので、その場所も
        attrs = gitx.worktree_attrs(path)
        self.assertEqual((attrs["gh-user"], attrs["config"]), ("gh-co", self.cfg))
        self.assertIn("started", out)
        # 設定のファイルは部署の .git の場所に在り、作業場の git status に出ない
        self.assertEqual(gitx.is_clean(path), True)

    def test_users_own_gh_user_comes_before_the_company_one(self):
        self.shape()
        p = pathlib.Path(self.cfg)
        p.write_text(p.read_text(encoding="utf-8") + 'gh_user = "me"\n', encoding="utf-8")
        ports = self.ports()
        rc, out = self.run_task(ports, "--role", "出荷役")
        self.assertEqual(rc, 0, out)
        [command] = [w[2] for w in ports.herdr.writes if w[0] == "run" and BG.search(w[2])]
        if os.name != "nt":
            # 役に設定が無ければ、いつもの部署の設定のファイル
            self.assertEqual(shlex.split(command)[5], ports.department_settings())
        self.assertNotIn("--model", command)
        self.assertEqual(gitx.worktree_attrs(self.place(ports))["gh-user"], "me")
        self.assertIn("gh-co", out)

    def test_unknown_explicit_role_stops_before_anything(self):
        self.shape()
        ports = self.ports()
        rc, out = self.run_task(ports, "--role", "調べやく")
        self.assertEqual(rc, 2)
        self.assertIn("在る役: 調べ役, 出荷役", out)
        self.assertEqual(ports.herdr.writes, [])

    def test_dry_run_shows_the_role_settings_and_the_gh_account(self):
        self.shape()
        ports = self.ports()
        rc, out = self.run_task(ports, "--role", "調べ役", "--dry-run")
        self.assertEqual(rc, 0, out)
        self.assertIn("モデル haiku、--settings の鍵 enabledPlugins, permissions, worktree", out)
        self.assertIn("gh のアカウント: gh-co（会話の Bash がコマンドごとに鍵を取り出し", out)
        self.assertEqual(ports.herdr.writes, [])
