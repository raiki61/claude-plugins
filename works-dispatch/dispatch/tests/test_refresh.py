"""古い版のプラグインで動いている会話を、ターンの終わりの手の空いた時に新しい版へ替える（refresh_hook.py と nodes/refresh.py）。"""

import datetime
import json
import os
import pathlib
import subprocess
import tempfile
import unittest

from . import DISPATCH
from .test_provision import git
from .test_wake import Window
import claudex
import gitx
import refresh_hook
from nodes import deliver, provision, refresh, role

T0 = 1_792_200_000.0   # 会話の処理が起きた時刻


def iso(t):
    return datetime.datetime.fromtimestamp(t, datetime.timezone.utc).isoformat().replace("+00:00", "Z")


class Node(unittest.TestCase):
    def test_installed_file_is_beside_the_cache_the_plugin_was_read_from(self):
        root = os.path.join("/c", "plugins", "cache", "m", "works-dispatch", "0.34.0")
        self.assertEqual(refresh.installed_file(root), os.path.normpath(os.path.join("/c", "plugins", "installed_plugins.json")))
        self.assertIsNone(refresh.installed_file("/src/claude-plugins/works-dispatch"))   # リポジトリの checkout から読んだ物

    def test_newest_update_counts_user_plugins_and_projects_containing_the_place(self):
        d = tempfile.mkdtemp()
        path = os.path.join(d, "installed_plugins.json")
        here = os.path.join(d, "repo", "sub")
        os.makedirs(here)
        pathlib.Path(path).write_text(json.dumps({"plugins": {
            "a@m": [{"scope": "user", "lastUpdated": iso(T0 - 10)}],
            "b@m": [{"scope": "project", "projectPath": os.path.join(d, "repo"), "lastUpdated": iso(T0 + 5)},
                    {"scope": "project", "projectPath": os.path.join(d, "other"), "lastUpdated": iso(T0 + 99)}],
        }}), encoding="utf-8")
        self.assertEqual(refresh.newest_update(path, here), T0 + 5)   # ほかのプロジェクトの物は数えない
        self.assertIsNone(refresh.newest_update(os.path.join(d, "none.json"), here))

    def test_stale_only_when_something_was_updated_after_the_last_load(self):
        self.assertTrue(refresh.stale(T0 + 1, T0))
        self.assertFalse(refresh.stale(T0 - 1, T0))              # 起きた後に更新が無い
        self.assertFalse(refresh.stale(T0 + 1, T0, T0 + 2))      # 更新の後に打った
        self.assertTrue(refresh.stale(T0 + 3, T0, T0 + 2))       # 打った後にまた更新された
        self.assertFalse(refresh.stale(None, T0))
        self.assertFalse(refresh.stale(T0 + 1, None))            # 起きた時刻が分からなければ打たない

    def test_the_mark_belongs_to_one_process(self):
        self.assertEqual(refresh.reloaded_at(refresh.mark_value(42, T0), 42), int(T0))
        self.assertIsNone(refresh.reloaded_at(refresh.mark_value(41, T0), 42))   # 起動し直す前の会話の控え
        self.assertIsNone(refresh.reloaded_at(None, 42))

    def test_types_only_when_free_and_the_box_is_empty(self):
        w = Window("/x", status="idle")
        self.assertEqual(refresh.reload_when_free("p1", w, lambda: None), "sent")
        self.assertEqual(w.writes, [refresh.RELOAD])
        for window, status in ((Window("/x", status="working"), "busy"), (Window("/x", box="打ちかけ"), "typing")):
            self.assertEqual(refresh.reload_when_free("p1", window, lambda: None), status)
            self.assertEqual(window.writes, [])   # ターンの途中と、人が書いている途中は打たない

    def test_reload_talk_waits_until_the_command_leaves_the_box(self):
        # --nudge が 1 行を打つ前に読み直させる。入力フィールドに残ったまま次を打つと、/reload-plugins の後ろに続いて届く
        w = Window("/x", status="idle")
        self.assertEqual(deliver.reload_talk("p1", w, lambda: None), ("sent", None))
        self.assertEqual(w.writes, [refresh.RELOAD])
        stuck = Window("/x", status="idle", box=refresh.RELOAD)
        status, detail = deliver.reload_talk("p1", stuck, lambda: None)
        self.assertEqual((status, stuck.writes), ("failed", [refresh.RELOAD, ("enter",)]))   # Enter は 1 回だけ足す
        self.assertIn("入力フィールドから出たのを見られなかった", detail)

        class EnterTakes(Window):
            def send_keys(self, pane, *keys):
                super().send_keys(pane, *keys)
                self.box = ""   # 足した Enter で入力フィールドから出た
        late = EnterTakes("/x", status="idle", box=refresh.RELOAD)
        self.assertEqual(deliver.reload_talk("p1", late, lambda: None), ("sent", None))
        self.assertEqual(late.writes, [refresh.RELOAD, ("enter",)])

        class Unseen(Window):
            def read(self, pane, lines, ansi=False):
                return "形の見えない画面"   # 入力フィールドが最後まで見えない
        self.assertEqual(deliver.reload_talk("p1", Unseen("/x"), lambda: None)[0], "failed")

        class Refused(Window):
            def prompt(self, pane, text, wait):
                raise self.Error(["herdr"], "受け付けない")
        self.assertEqual(deliver.reload_talk("p1", Refused("/x"), lambda: None)[0], "failed")

    def test_waits_for_the_end_of_the_turn_to_show(self):
        w = Window("/x", status="working")
        seen = []

        def pause():
            seen.append(1)
            if len(seen) == 3:
                w.status = "done"
        self.assertEqual(refresh.reload_when_free("p1", w, pause), "sent")
        self.assertEqual(len(seen), 3)


    def test_waits_for_the_clear_typed_by_the_other_hook(self):
        # 待ち受けのフックが同じターンの終わりに /clear を打つ会話では、その後に打つ（2 つの打ち込みを重ねない）
        attrs = {"role": "担当", "ask": "a1", "delivered": "a1", "fresh": role.FRESH}
        self.assertTrue(refresh.clearing(attrs))
        self.assertTrue(refresh.clearing({"rest": "s1"}))
        self.assertFalse(refresh.clearing({**attrs, "cleared": "a1"}))
        self.assertFalse(refresh.clearing({**attrs, "delivered": "a0"}))   # 納品前は空にしない
        w = Window("/x", status="idle")
        looks = []

        def pause():
            looks.append(1)
            if len(looks) == 4:
                attrs["cleared"] = "a1"
        self.assertEqual(refresh.reload_when_free("p1", w, pause, lambda: refresh.clearing(attrs)), "sent")
        self.assertEqual(len(looks), 4)
        never = Window("/x", status="idle")
        self.assertEqual(refresh.reload_when_free("p1", never, lambda: None, lambda: True), "clearing")
        self.assertEqual(never.writes, [])


class Elapsed(unittest.TestCase):
    def test_reads_ps_etime(self):
        self.assertEqual(claudex._elapsed("05:07"), 307)
        self.assertEqual(claudex._elapsed("01:00:00"), 3600)
        self.assertEqual(claudex._elapsed("2-00:00:01"), 2 * 86400 + 1)
        self.assertIsNone(claudex._elapsed("?"))

    @unittest.skipIf(os.name == "nt", "ps の無い所では見ない")
    def test_host_is_the_claude_process_above_the_hook(self):
        class P:
            returncode = 0
            stdout = "10 1 01:00 /bin/zsh\n20 10 00:30 claude --model x\n30 20 00:01 bash -c hook\n40 30 00:01 python3 h.py\n"
        self.assertEqual(claudex.host(lambda argv: P, me=40, now=T0), (20, T0 - 30))
        P.stdout = "40 1 00:01 python3 h.py\n"
        self.assertEqual(claudex.host(lambda argv: P, me=40, now=T0), (None, None))


class Elsewhere(Window):
    """この会話の窓が見つからない herdr（ペインの場所が違う）。"""

    def panes(self):
        return [{"pane_id": "p9", "cwd": "/somewhere/else", "agent": "claude"}]


class Hook(unittest.TestCase):
    def setUp(self):
        d = pathlib.Path(tempfile.mkdtemp())
        self.src = str(d / "co")
        git("init", "-q", "-b", "main", self.src)
        git("-C", self.src, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "--allow-empty", "-m", "init")
        self.place = str(d / "dept")
        git("-C", self.src, "worktree", "add", "-q", "-b", "dept/a", self.place)
        self.cfg = d / "cfg" / "plugins"
        self.root = str(self.cfg / "cache" / "m" / "works-dispatch" / "0.34.0")
        os.makedirs(self.root)
        self.updated(T0 + 60)
        self.env = {}

    def updated(self, t):
        (self.cfg / "installed_plugins.json").write_text(
            json.dumps({"plugins": {"works-dispatch@m": [{"scope": "user", "lastUpdated": iso(t)}]}}), encoding="utf-8")

    def run_hook(self, cwd=None, window=None, pid=20, same=lambda pid: False, now=T0 + 100):
        w = window or Window(cwd or self.place, status="done", front=[{"pid": pid, "argv": ["claude"]}])   # 窓の前にこの会話の処理
        got = refresh_hook.run({"cwd": cwd or self.place, "session_id": "s1"}, self.env, h=w, host=lambda: (pid, T0), same=same,
                               pause=lambda: None, now=lambda: now, plugin_root=self.root)
        return got, w.writes

    def test_reloads_a_department_running_plugins_older_than_the_installed_ones_once(self):
        provision.mark(self.place, self.src, {"role": "担当", "name": "調べ"}, gitx)
        self.assertEqual(self.run_hook(), ("sent", [refresh.RELOAD]))
        self.assertEqual(gitx.worktree_attrs(self.place)[refresh.ATTR], refresh.mark_value(20, T0 + 100))
        self.assertEqual(self.run_hook(), (None, []))              # 同じ更新では打ち直さない
        self.updated(T0 + 200)
        self.assertEqual(self.run_hook(now=T0 + 300), ("sent", [refresh.RELOAD]))   # 次の更新では打つ
        self.assertEqual(self.run_hook(pid=21, now=T0 + 400), ("sent", [refresh.RELOAD]))   # 控えはほかの処理の物

    def test_leaves_fresh_conversations_and_busy_or_typed_windows(self):
        provision.mark(self.place, self.src, {"role": "担当", "name": "調べ"}, gitx)
        self.updated(T0 - 1)
        self.assertEqual(self.run_hook(), (None, []))              # 起きた後に更新が無い
        self.updated(T0 + 60)
        self.assertEqual(self.run_hook(window=Window(self.place, status="working", front=[{"pid": 20, "argv": ["claude"]}])), ("busy", []))
        self.assertEqual(self.run_hook(window=Window(self.place, box="打ちかけ", front=[{"pid": 20, "argv": ["claude"]}])), ("typing", []))
        self.assertNotIn(refresh.ATTR, gitx.worktree_attrs(self.place))   # 打てなければ控えず、次のターンの終わりに見直す

    def test_does_nothing_outside_a_department_herdr_or_the_plugin_cache(self):
        self.assertEqual(self.run_hook(), (None, []))              # 部署でない（持ち主の作業の会話）
        provision.mark(self.place, self.src, {"role": "担当"}, gitx)
        self.assertEqual(self.run_hook(window=Elsewhere(self.place)), (None, []))   # herdr の外（窓が決まらない）
        got = refresh_hook.run({"cwd": self.place}, self.env, h=Window(self.place), host=lambda: (20, T0),
                               pause=lambda: None, plugin_root="/src/claude-plugins/works-dispatch")
        self.assertIsNone(got)                                     # リポジトリの checkout から読んだ物

    def test_a_window_where_another_talk_is_in_front_is_not_reloaded(self):
        # 打ち先は、窓の前のプロセスにこの会話が居ると確かめた窓だけ（/clear と同じ確かめ方。c52730 の 5）
        provision.mark(self.place, self.src, {"role": "担当", "name": "調べ"}, gitx)
        other = Window(self.place, status="done", front=[{"pid": 99, "argv": ["claude"]}])
        self.assertEqual(self.run_hook(window=other), (None, []))
        attached = Window(self.place, status="done", front=[{"pid": 99, "argv": ["claude", "attach", "s1"]}])
        self.assertEqual(self.run_hook(window=attached), ("sent", [refresh.RELOAD]))   # この会話へ attach した窓

    def test_the_desk_reloads_only_its_own_conversation(self):
        provision.mark(self.src, self.src, {"role": "段取り", "pid": "20"}, gitx)
        self.assertEqual(self.run_hook(cwd=self.src), (None, []))  # 代表の clone の、持ち主のほかの会話
        self.assertEqual(self.run_hook(cwd=self.src, same=lambda pid: pid == "20"), ("sent", [refresh.RELOAD]))

    def test_plugin_declares_the_refresh_hook_in_the_background_at_stop(self):
        hooks = json.loads((pathlib.Path(DISPATCH).parent / "hooks" / "hooks.json").read_text(encoding="utf-8"))["hooks"]
        [h] = [h for grp in hooks["Stop"] for h in grp["hooks"] if "refresh_hook.py" in h["command"]]
        self.assertIn('"${CLAUDE_PLUGIN_ROOT}/dispatch/refresh_hook.py"', h["command"])
        self.assertTrue(h.get("async"))   # ターンの終わりを待たせない

    def test_main_never_stops_the_conversation(self):
        p = subprocess.run(["python3", str(pathlib.Path(DISPATCH) / "refresh_hook.py")], input="not json",
                           capture_output=True, text=True, encoding="utf-8", cwd=tempfile.mkdtemp())
        self.assertEqual(p.returncode, 0, p.stderr)


if __name__ == "__main__":
    unittest.main()
