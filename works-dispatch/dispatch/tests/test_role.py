"""役の渡し方（会社の形の設計 4.7・4.8）: 会社の形の役の項目（role ノード）、部署を起こすときの --settings・--model・--effort と gh の
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
from unittest import mock

from . import DISPATCH
from .test_dispatch import FakeHerdr, gitx_source
from .test_provision import git, make_world
from . import test_task
import claudex
import gitx
import orders
import role_hook
from nodes import deliver, launch, provision, role

SHAPE = '''
name = "試しの会社"
gh_user = "gh-co"

[[roles]]
name = "調べ役"
instructions = "結論と原典の一句を返す。"
model = "haiku"
effort = "low"
deliver = ["結論", "差分", "試験"]
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
        self.assertEqual(got["roles"]["調べ役"]["deliver"], ["結論", "差分", "試験"])
        self.assertEqual(got["roles"]["調べ役"]["effort"], "low")
        self.assertEqual(got["roles"]["出荷役"], {"name": "出荷役", "instructions": None, "model": None, "effort": None, "settings": None,
                                                 "deliver": None, "deliver_check": None, "resident": False, "fresh": False, "machine": False, "tools": []})

    def test_no_file_is_empty_and_broken_shapes_are_problems_but_others_are_read(self):
        self.assertEqual(role.load(None), {"roles": {}, "gh_user": None, "default_role": None, "desk_role": None,
                                                 "former": {}, "problems": []})
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

    def test_roles_by_name_and_misplaced_deliver_are_problems_not_silence(self):
        got = role.load(write(f"{self.d}/old.toml", '[roles."作業役"]\ndeliver = ["結論"]\n'))
        self.assertEqual(got["roles"], {})
        self.assertIn('[roles."役"] の形で書いている（作業役）', got["problems"][0])
        self.assertIn("[[roles]] の項目", got["problems"][0])
        got = role.load(write(f"{self.d}/c.toml", '''[[roles]]
name = "a"
deliver = "結論"
[[roles]]
name = "b"
[roles.settings]
deliver = ["結論"]
deliver_check = "x"
[[roles]]
name = "c"
deliver_check = ""
'''))
        self.assertEqual(list(got["roles"]), ["b"])
        self.assertIn("deliver の形が違う", got["problems"][0])
        self.assertIn("deliver が [roles.settings] の中に入っている", got["problems"][1])
        self.assertIn("deliver_check が [roles.settings] の中に入っている", got["problems"][2])
        self.assertIn("deliver_check の形が違う", got["problems"][3])
        self.assertIsNone(got["roles"]["b"]["deliver_check"])

    def test_pick_stops_only_on_an_explicit_role_missing_from_a_shape_that_has_roles(self):
        shape = role.load(write(f"{self.d}/c.toml", SHAPE))
        self.assertEqual(role.pick(shape, "調べ役", True)[0]["name"], "調べ役")
        self.assertIn("在る役: 調べ役, 出荷役", role.pick(shape, "調べやく", True)[1])
        self.assertEqual(role.pick(shape, "作業役", False), (None, None))
        self.assertEqual(role.pick(role.load(None), "何か", True), (None, None))

    def test_default_role_and_resident_are_read_and_checked(self):
        got = role.load(write(f"{self.d}/d.toml", 'default_role = "b"\n[[roles]]\nname = "a"\nresident = true\n[[roles]]\nname = "b"\n'))
        self.assertEqual((got["default_role"], got["roles"]["a"]["resident"], got["roles"]["b"]["resident"], got["problems"]),
                         ("b", True, False, []))
        self.assertEqual(role.default(got, "作業"), ("b", None))
        got = role.load(write(f"{self.d}/e.toml", 'default_role = "無い"\n[[roles]]\nname = "a"\nresident = "yes"\n'
                                                  '[[roles]]\nname = "c"\n'))
        self.assertIsNone(got["default_role"])
        self.assertEqual(list(got["roles"]), ["c"])
        self.assertIn("resident の形が違う", got["problems"][0])
        self.assertIn("default_role の役 無い が [[roles]] に無い", got["problems"][1])
        name, note = role.default(got, "作業")
        self.assertEqual(name, "作業")
        self.assertIn("在る役: c", note)
        self.assertEqual(role.default(role.load(None), "作業"), ("作業", None))   # 役を書いていない会社では注記を出さない

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


class Seat(unittest.TestCase):
    def test_fresh_is_read_and_shown_with_residency(self):
        d = tempfile.mkdtemp()
        got = role.load(write(f"{d}/c.toml", '[[roles]]\nname = "担当"\nresident = true\nfresh = true\n'
                                             '[[roles]]\nname = "相談"\nresident = true\n[[roles]]\nname = "変"\nfresh = "yes"\n'))
        self.assertEqual((got["roles"]["担当"]["fresh"], got["roles"]["相談"]["fresh"]), (True, False))
        self.assertNotIn("変", got["roles"])
        self.assertIn("resident・fresh・machine は true か false", got["problems"][0])
        # herdr の作業場の印 kind に、常設か都度かと、会話を持ち越すか毎回空にするかを出す。ペインの表示名は役だけ
        from nodes import sync
        self.assertEqual(sync.kind({"role": "担当", "residency": "resident", "fresh": "true"}), "常設・毎回空")
        self.assertEqual(sync.kind({"role": "相談", "residency": "resident"}), "常設・持ち越し")
        self.assertEqual(sync.kind({"role": "作業", "residency": "per-task"}), "都度")
        self.assertIsNone(sync.kind({}))
        self.assertEqual(sync.op("p", {"role": "担当", "residency": "resident", "name": "割り振り"}, False)["display_agent"], "担当")


class ModelAndEffort(unittest.TestCase):
    """役の model と effort: 省けばアカウントの既定、値を書けばその値、effort の inherit は呼んだ会話の今の effort（CLAUDE_EFFORT）。"""

    def roles(self, body):
        d = tempfile.mkdtemp()
        return role.load(write(f"{d}/c.toml", body))

    def test_effort_values_are_checked_and_unknown_ones_drop_the_role(self):
        # claude は知らない --effort を注意だけで既定に戻す（裏の会話では黙って）ので、書き損じは読むときに弾く
        got = self.roles('[[roles]]\nname = "a"\neffort = "xhigh"\n[[roles]]\nname = "b"\neffort = "hihg"\n'
                         '[[roles]]\nname = "c"\neffort = "inherit"\n')
        self.assertEqual((got["roles"]["a"]["effort"], got["roles"]["c"]["effort"]), ("xhigh", "inherit"))
        self.assertNotIn("b", got["roles"])
        [problem] = got["problems"]
        self.assertIn("effort は low・medium・high・xhigh・max・ultracode・inherit のどれか", problem)

    def test_model_inherit_is_not_made(self):
        # 頼み元の会話の今のモデルを外から読む口が無いので、model の inherit は作らず、書き損じと同じに役を外して知らせる
        got = self.roles('[[roles]]\nname = "a"\nmodel = "inherit"\n')
        self.assertNotIn("a", got["roles"])
        self.assertIn("model の inherit は作っていない", got["problems"][0])

    def test_launch_flags(self):
        r = {"name": "担当", "model": "opus", "effort": "max"}
        self.assertEqual(role.launch_flags(r, {"CLAUDE_EFFORT": "low"}), ("opus", "max", None))
        self.assertEqual(role.launch_flags(None, {"CLAUDE_EFFORT": "low"}), (None, None, None))
        self.assertEqual(role.launch_flags({**r, "effort": "inherit"}, {"CLAUDE_EFFORT": "low"}), ("opus", "low", None))
        model, effort, note = role.launch_flags({**r, "effort": "inherit"}, {})
        self.assertEqual((model, effort), ("opus", None))
        self.assertIn("CLAUDE_EFFORT が無い", note)

    def test_launch_key_keeps_inherit_unresolved_and_takes_the_duty_first(self):
        # 毎回空にする部署の待ち受けが比べる字。inherit は解かない（呼んだ会話の effort が替わっても起こし直さない）
        r = {"name": "担当", "model": "opus", "effort": "inherit"}
        self.assertEqual(json.loads(role.launch_key(r)), {"model": "opus", "effort": "inherit"})
        self.assertEqual(json.loads(role.launch_key(r, {"name": "割り振り", "model": "sonnet", "effort": None})),
                         {"model": "sonnet", "effort": "inherit"})
        self.assertEqual(json.loads(role.launch_key(None)), {"model": None, "effort": None})

    def test_launch_flags_take_the_duty_before_the_role(self):
        # 決める順は欄ごとに、部署（受け持ち）・役・アカウントの既定。受け持ちに無い欄は役の値
        r = {"name": "担当", "model": "opus", "effort": "max"}
        self.assertEqual(role.launch_flags(r, {}, {"name": "割り振り", "model": "sonnet", "effort": "low"}), ("sonnet", "low", None))
        self.assertEqual(role.launch_flags(r, {}, {"name": "割り振り", "model": None, "effort": "low"}), ("opus", "low", None))
        self.assertEqual(role.launch_flags(None, {}, {"name": "割り振り", "model": "haiku", "effort": None}), ("haiku", None, None))
        self.assertEqual(role.launch_flags(r, {"CLAUDE_EFFORT": "xhigh"}, {"name": "割り振り", "model": None, "effort": "inherit"}),
                         ("opus", "xhigh", None))
        _, effort, note = role.launch_flags(r, {}, {"name": "割り振り", "model": None, "effort": "inherit"})
        self.assertIsNone(effort)
        self.assertIn("部署 割り振り の effort は inherit", note)


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

    def test_effort_is_put_after_the_model(self):
        _, command = self.started(True, model="haiku", effort="low")
        self.assertEqual(shlex.split(command), ["claude-a1", "--bg", "--name", "直し", "--settings", "s.json", "--model", "haiku",
                                                "--effort", "low", "頼み"])
        _, command = self.started(True, effort="max")
        self.assertEqual(shlex.split(command)[-3:], ["--effort", "max", "頼み"])

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
        self.env = {"WORKS_DISPATCH_CONFIG": str(pathlib.Path(root).parent / "conf" / "dispatch.toml"),
                    "TMPDIR": tempfile.mkdtemp()}   # 会話に足した文の控えの置き場

    def test_clear_compact_and_resume_rewrite_the_department_session_and_keep_the_job(self):
        # /clear で会話の id が変わる。古い id のままだと --ask が動き出しを見られず、Stop フックが部署の会話を見分けなかった。
        # 裏の会話の短い id（attach に渡す）は /clear の後も変わらないので、前の版の部署は古い id の頭を job に残す
        provision.mark(self.place, self.src, {"role": "担当", "session": "8c4a1102-aaaa", "ask": "X", "boss": "窓口"}, gitx)
        role_hook.main(io.StringIO(json.dumps({"cwd": self.place, "session_id": "a5b0bc07-bbbb", "source": "clear"})), self.env)
        attrs = gitx.worktree_attrs(self.place)
        self.assertEqual((attrs["session"], attrs["job"]), ("a5b0bc07-bbbb", "8c4a1102"))
        # 書き直した後は、Stop フックがこの会話を部署の会話と見て、納品していない頼みを差し戻す
        self.assertIsNotNone(deliver.stop_verdict({"session_id": "a5b0bc07-bbbb"}, attrs, 0, "run"))
        for source in ("compact", "resume"):
            role_hook.main(io.StringIO(json.dumps({"cwd": self.place, "session_id": f"s-{source}", "source": source})), self.env)
            attrs = gitx.worktree_attrs(self.place)
            self.assertEqual((attrs["session"], attrs["job"]), (f"s-{source}", "8c4a1102"))

    def test_new_talks_and_the_head_office_keep_the_department_session(self):
        # 部署の場所で人が別の会話を起こしても（startup）、本社で持ち主の会話が /clear しても、部署の会話の id は替えない
        provision.mark(self.place, self.src, {"role": "担当", "session": "s-dept"}, gitx)
        role_hook.main(io.StringIO(json.dumps({"cwd": self.place, "session_id": "s-other", "source": "startup"})), self.env)
        self.assertEqual(gitx.worktree_attrs(self.place)["session"], "s-dept")
        provision.mark(self.src, self.src, {"role": "窓口", "session": "s-desk"}, gitx)
        role_hook.main(io.StringIO(json.dumps({"cwd": self.src, "session_id": "s-mine", "source": "clear"})), self.env)
        self.assertEqual(gitx.worktree_attrs(self.src)["session"], "s-desk")

    def test_department_gets_its_role_text_and_other_places_get_nothing(self):
        write(pathlib.Path(self.src) / ".claude" / "company.toml", SHAPE)
        self.assertIsNone(role_hook.text_for(self.place, self.env))   # 役の属性が無い
        provision.mark(self.place, self.src, {"role": "調べ役"}, gitx)
        self.assertEqual(role_hook.text_for(self.place, self.env), "この会話は会社「試しの会社」の部署で、役は「調べ役」。\n結論と原典の一句を返す。")
        self.assertIsNone(role_hook.text_for(self.src, self.env))      # 本社
        provision.mark(self.src, self.src, {"role": "窓口"}, gitx)     # --desk で名付けた本社の窓口は、部署と書かない
        self.assertEqual(role_hook.text_for(self.src, self.env), "この会話は会社「試しの会社」の本社の会話で、役は「窓口」。")
        self.assertIsNone(role_hook.text_for(tempfile.mkdtemp(), self.env))   # git でない

    def test_role_text_comes_from_the_default_branch_when_the_head_office_is_on_an_old_branch(self):
        from .test_company import publish
        publish(self.src, SHAPE)
        git("-C", self.src, "checkout", "-q", "-b", "old")   # 元の clone はほかの会話が古い枝で使っている（会社の形を持たない）
        provision.mark(self.place, self.src, {"role": "調べ役"}, gitx)
        self.assertEqual(role_hook.text_for(self.place, self.env), "この会話は会社「試しの会社」の部署で、役は「調べ役」。\n結論と原典の一句を返す。")
        # --ask・--deliver の読み方（orders.shape_role）も同じ物を読む
        got, problems = orders.shape_role(self.src, None, "調べ役")
        self.assertEqual((got["instructions"], problems), ("結論と原典の一句を返す。", []))

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
        envfile.write_bytes(b"export A=1\n")   # write_text は Windows で \r\n にする
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

    def test_the_head_office_desk_session_follows_a_clear_in_the_same_process_only(self):
        # 段取り（--desk の会話）は区切りで /clear する。--desk が書いた会話の処理の番号の処理なら、新しい id に書き直す
        provision.mark(self.src, self.src, {"role": "窓口", "session": "s-desk", "pid": "999999999"}, gitx)
        role_hook.main(io.StringIO(json.dumps({"cwd": self.src, "session_id": "s-other", "source": "clear"})), self.env)
        self.assertEqual(gitx.worktree_attrs(self.src)["session"], "s-desk")   # 持ち主のほかの会話の /clear
        provision.mark(self.src, self.src, {"pid": str(os.getpid())}, gitx)   # フックは会話の処理の子で走る（ここではこの処理）
        with contextlib.redirect_stdout(io.StringIO()):
            role_hook.main(io.StringIO(json.dumps({"cwd": self.src, "session_id": "s-new", "source": "clear"})), self.env)
        self.assertEqual(gitx.worktree_attrs(self.src)["session"], "s-new")

    def test_only_the_desk_seat_gets_the_head_office_role(self):
        # 代表の clone で起きた試しの claude -p（名前が無い）や、窓口が動いている間に起きた会話は、窓口として振る舞わない（53d5d1・6be241）
        write(pathlib.Path(self.src) / ".claude" / "company.toml", '[[roles]]\nname = "段取り"\ninstructions = "頼みを配る。"\n')
        provision.mark(self.src, self.src, {"role": "段取り", "name": "段取り", "session": "s-desk", "pid": "999999999"}, gitx)

        def told(payload, running):
            out = io.StringIO()
            with mock.patch.object(claudex, "running_claude", lambda pid: running), contextlib.redirect_stdout(out):
                role_hook.main(io.StringIO(json.dumps({"cwd": self.src, "source": "startup", **payload})), self.env)
            return "頼みを配る。" in out.getvalue()
        self.assertTrue(told({"session_id": "s-desk"}, True))                                  # 窓口の会話
        self.assertFalse(told({"session_id": "s-probe"}, True))                                # 試しの claude -p
        self.assertFalse(told({"session_id": "s-two", "session_title": "段取り"}, True))       # 窓口が動いている間の 2 つ目
        self.assertTrue(told({"session_id": "s-next", "session_title": "段取り"}, False))      # 窓口を終えて起こし直した会話
        self.assertFalse(told({"session_id": "s-probe"}, False))                               # 名前の無い会話は席に座らない
        out = io.StringIO()
        with contextlib.redirect_stdout(out):   # 部署の worktree は今までどおり
            provision.mark(self.place, self.src, {"role": "段取り"}, gitx)
            role_hook.main(io.StringIO(json.dumps({"cwd": self.place, "session_id": "s-x", "source": "startup"})), self.env)
        self.assertIn("頼みを配る。", out.getvalue())

    def test_running_claude_reads_the_command_of_the_process(self):
        import subprocess
        def runner(out, rc=0):
            return lambda argv: subprocess.CompletedProcess(argv, rc, out, "")
        self.assertTrue(claudex.running_claude("12", runner("/Users/x/.local/share/claude/versions/2.1.302 --name 段取り\n")))
        self.assertFalse(claudex.running_claude("12", runner("/usr/bin/python3 x.py\n")))   # 番号が使い回された別の処理
        self.assertFalse(claudex.running_claude("12", runner("", rc=1)))                     # もう居ない
        self.assertFalse(claudex.running_claude(None, runner("claude")))

    def test_a_former_role_name_reads_as_the_current_role_and_is_rewritten(self):
        write(pathlib.Path(self.src) / ".claude" / "company.toml",
              'name = "co"\ndesk_role = "窓口"\n[[roles]]\nname = "段取り"\nformer_names = ["窓口"]\ninstructions = "頼みを配る。"\n')
        provision.mark(self.src, self.src, {"role": "窓口", "session": "s-desk"}, gitx)
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            role_hook.main(io.StringIO(json.dumps({"cwd": self.src, "session_id": "s-desk", "source": "startup"})), self.env)
        self.assertIn("役は「段取り」。\n頼みを配る。", json.loads(out.getvalue())["hookSpecificOutput"]["additionalContext"])
        self.assertEqual(gitx.worktree_attrs(self.src)["role"], "段取り")
        shape = role.load("x", (pathlib.Path(self.src) / ".claude" / "company.toml").read_text(encoding="utf-8"))
        self.assertEqual((shape["desk_role"], role.current(shape, "窓口"), role.current(shape, "作業")), ("段取り", "段取り", "作業"))

    def test_a_running_talk_gets_the_new_role_text_once_on_its_next_prompt(self):
        shape = pathlib.Path(self.src) / ".claude" / "company.toml"
        write(shape, '[[roles]]\nname = "相談"\ninstructions = "持ち主と話す。"\n')
        provision.mark(self.place, self.src, {"role": "相談", "session": "s1"}, gitx)
        with contextlib.redirect_stdout(io.StringIO()):
            role_hook.main(io.StringIO(json.dumps({"cwd": self.place, "session_id": "s1", "source": "startup"})), self.env)

        def prompt(sid="s1"):
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                role_hook.prompt(io.StringIO(json.dumps({"cwd": self.place, "session_id": sid})), self.env)
            return json.loads(out.getvalue())["hookSpecificOutput"]["additionalContext"] if out.getvalue() else None
        self.assertIsNone(prompt())   # 会話の始まりに足した物のまま
        write(shape, '[[roles]]\nname = "相談"\ninstructions = "持ち主と話し、頼みは段取りに渡す。"\n')
        got = prompt()
        self.assertTrue(got.startswith(role_hook.CHANGED_HEAD), got)
        self.assertIn("頼みは段取りに渡す。", got)
        self.assertIsNone(prompt())   # 足すのは替わった後の 1 度だけ
        self.assertIsNone(prompt("s-other"))   # 場所の属性の会話でない会話には足さない

    def test_plugin_declares_the_prompt_hook_in_sync(self):
        hooks = json.loads((pathlib.Path(DISPATCH).parent / "hooks" / "hooks.json").read_text(encoding="utf-8"))["hooks"]
        [h] = [h for grp in hooks["UserPromptSubmit"] for h in grp["hooks"] if "role_hook.py" in h["command"]]
        self.assertTrue(h["command"].endswith('role_hook.py" --prompt'))
        self.assertFalse(h.get("async"))   # 裏で走るフックの返す文は会話に入らない

    def test_plugin_declares_the_hook_on_the_existing_script(self):
        hooks = json.loads((pathlib.Path(DISPATCH).parent / "hooks" / "hooks.json").read_text(encoding="utf-8"))["hooks"]
        [command] = [h["command"] for grp in hooks["SessionStart"] for h in grp["hooks"] if not h.get("asyncRewake")]
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

    def test_role_model_is_read_from_the_default_branch_when_the_head_office_is_on_an_old_branch(self):
        from .test_company import publish
        src = gitx_source(self.cfg)
        publish(src, SHAPE)
        write(pathlib.Path(src) / ".claude" / "company.toml", 'name = "古い形"\n')   # 元の clone の作業ツリーは古い（役が無い）
        ports = self.ports()
        rc, out = self.run_task(ports, "--role", "調べ役")
        self.assertEqual(rc, 0, out)
        [command] = [w[2] for w in ports.herdr.writes if w[0] == "run" and BG.search(w[2])]
        self.assertIn("haiku", command)

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
            self.assertEqual(shlex.split(command)[:10], ["claude-a1", "--bg", "--name", "直し", "--settings", settings, "--model", "haiku",
                                                         "--effort", "low"])
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
        self.assertNotIn("--effort", command)
        self.assertEqual(gitx.worktree_attrs(self.place(ports))["gh-user"], "me")
        self.assertIn("gh-co", out)

    def test_duty_model_and_effort_come_before_the_roles(self):
        # 部署の名前（--task）と同じ name の受け持ちに書いた値が、役の値より先に効く。ほかの名前の部署は役の値のまま
        self.shape(SHAPE + '\n[[skills]]\nname = "直し"\nrole = "調べ役"\nmodel = "sonnet"\neffort = "high"\n')
        ports = self.ports()
        rc, out = self.run_task(ports, "--role", "調べ役", "--dry-run")
        self.assertEqual(rc, 0, out)
        self.assertIn("モデル sonnet、effort high", out)
        rc, out = self.run_task(ports, "--role", "調べ役", "--dry-run", name="別の直し")
        self.assertEqual(rc, 0, out)
        self.assertIn("モデル haiku、effort low", out)
        rc, out = self.run_task(ports, "--role", "調べ役")
        self.assertEqual(rc, 0, out)
        [command] = [w[2] for w in ports.herdr.writes if w[0] == "run" and BG.search(w[2])]
        self.assertRegex(command, r'--model "?sonnet\b.*--effort "?high\b')

    def test_bad_duty_effort_is_said_at_launch_and_the_role_value_is_used(self):
        self.shape(SHAPE + '\n[[skills]]\nname = "直し"\neffort = "hihg"\n')
        rc, out = self.run_task(self.ports(), "--role", "調べ役", "--dry-run")
        self.assertEqual(rc, 0, out)
        self.assertIn("外して、役の effort で起こす", out)
        self.assertIn("モデル haiku、effort low", out)

    def test_effort_inherit_takes_the_callers_effort(self):
        self.shape(SHAPE.replace('effort = "low"', 'effort = "inherit"'))
        ports = self.ports()
        ports.env = {**ports.env, "CLAUDE_EFFORT": "xhigh"}
        rc, out = self.run_task(ports, "--role", "調べ役", "--dry-run")
        self.assertEqual(rc, 0, out)
        self.assertIn("モデル haiku、effort xhigh", out)
        rc, out = self.run_task(ports, "--role", "調べ役")
        self.assertEqual(rc, 0, out)
        [command] = [w[2] for w in ports.herdr.writes if w[0] == "run" and BG.search(w[2])]
        self.assertRegex(command, r'--effort "?xhigh\b')

    def test_effort_inherit_without_the_callers_effort_starts_at_the_default_and_says_so(self):
        self.shape(SHAPE.replace('effort = "low"', 'effort = "inherit"'))
        ports = self.ports()
        rc, out = self.run_task(ports, "--role", "調べ役")
        self.assertEqual(rc, 0, out)
        [command] = [w[2] for w in ports.herdr.writes if w[0] == "run" and BG.search(w[2])]
        self.assertNotIn("--effort", command)
        self.assertIn("CLAUDE_EFFORT が無い", out)

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
        self.assertIn("モデル haiku、effort low、--settings の鍵 enabledPlugins, permissions, worktree", out)
        self.assertIn("gh のアカウント: gh-co（会話の Bash がコマンドごとに鍵を取り出し", out)
        self.assertEqual(ports.herdr.writes, [])
