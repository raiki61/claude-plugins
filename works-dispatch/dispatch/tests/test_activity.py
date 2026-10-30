"""サイドバーの作業内容のフック（activity.py）。Claude Code のフックの入力（JSON）から、herdr のサイドバーに出す 1 行を作る。"""

import json
import pathlib
import tempfile
import unittest

from . import DISPATCH  # noqa: F401
import activity  # noqa: E402
import windows  # noqa: E402


class Label(unittest.TestCase):
    def test_tool_in_progress_names_the_tool_and_its_target(self):
        self.assertEqual(activity.label({"hook_event_name": "PreToolUse", "tool_name": "Bash",
                                         "tool_input": {"command": "git status"}}), "Bash git status")
        self.assertEqual(activity.label({"hook_event_name": "PreToolUse", "tool_name": "Edit",
                                         "tool_input": {"file_path": "/r/src/app.py"}}), "Edit app.py")
        self.assertEqual(activity.label({"hook_event_name": "PreToolUse", "tool_name": "mcp__x__y"}), "mcp__x__y")

    def test_long_text_is_cut_and_flattened_to_one_line(self):
        got = activity.label({"hook_event_name": "PreToolUse", "tool_name": "Bash",
                              "tool_input": {"command": "for f in *; do\n  echo $f; done && make all"}})
        self.assertEqual(got, "Bash for f in *; do echo $f…")  # ツールの中身は 22 字で切る

    def test_ask_drops_text_the_machine_injected(self):
        prompt = "<system-reminder>x</system-reminder>\n#1737 のレビューの続き"
        self.assertEqual(activity.label({"hook_event_name": "UserPromptSubmit", "prompt": prompt}), "#1737 のレビューの続き")

    def test_other_events_have_no_label_of_their_own(self):
        self.assertIsNone(activity.label({"hook_event_name": "Stop"}))


class Handle(unittest.TestCase):
    def setUp(self):
        self.dir = pathlib.Path(tempfile.mkdtemp())
        self.sent, self.looked = [], []
        # 裏の会話は控えの処理の HERDR_PANE_ID を継ぎ、別のペインを指すことがある（2026-10-17 に見た）。印はそこへ送らない
        self.env = {"HERDR_ENV": "1", "HERDR_PANE_ID": "w9:p9", "TMPDIR": str(self.dir)}
        self.panes = [{"pane_id": "w9:p9", "agent": "claude", "cwd": "/other", "agent_session": "s-other"},
                      {"pane_id": "w1:p1", "agent": "claude", "cwd": "/a", "agent_session": "s1"}]

    def find(self, cwd, sid):
        self.looked.append(sid)
        return windows.own_pane(cwd, sid, self.panes)

    def handle(self, payload, env=None):
        activity.handle(json.dumps({"session_id": "s1", "cwd": "/a", **payload}), self.env if env is None else env,
                        send=lambda pane, text, ttl: self.sent.append((pane, text)), find=self.find)

    def test_turn_end_goes_back_to_what_was_asked(self):
        self.handle({"hook_event_name": "UserPromptSubmit", "prompt": "テストを直して"})
        self.handle({"hook_event_name": "PreToolUse", "tool_name": "Read", "tool_input": {"file_path": "/a/b.py"}})
        self.handle({"hook_event_name": "Stop"})
        self.assertEqual(self.sent, [("w1:p1", "テストを直して"), ("w1:p1", "Read b.py"), ("w1:p1", "テストを直して")])
        self.assertEqual(self.looked, ["s1", "s1"])   # ツールの呼び出しは控えだけを見て、herdr を読み直さない

    def test_the_pane_is_looked_up_again_when_the_conversation_moves(self):
        # 同じ会話の id が --resume などで別のペインに出る。控えのペインは前のペイン（今は別の会話）を指したままになる
        self.handle({"hook_event_name": "UserPromptSubmit", "prompt": "前のターン"})
        self.panes = [{"pane_id": "w1:p1", "agent": "claude", "cwd": "/a", "agent_session": "s-other"},
                      {"pane_id": "w2:p2", "agent": "claude", "cwd": "/a", "agent_session": "s1"}]
        self.handle({"hook_event_name": "UserPromptSubmit", "prompt": "次のターン"})
        self.handle({"hook_event_name": "PreToolUse", "tool_name": "Read", "tool_input": {"file_path": "/a/b.py"}})
        self.assertEqual(self.sent[1:], [("w2:p2", "次のターン"), ("w2:p2", "Read b.py")])
        # 確かめられなくなったら、控えの前のペインへ送らない
        self.panes = [{"pane_id": "w9:p9", "agent": "claude", "cwd": "/other", "agent_session": "s-other"}]
        self.handle({"hook_event_name": "Stop"})
        self.handle({"hook_event_name": "PreToolUse", "tool_name": "Read", "tool_input": {"file_path": "/a/b.py"}})
        self.assertEqual(len(self.sent), 3)

    def test_the_memo_is_dropped_when_herdr_cannot_be_asked(self):
        # --resume で別のペインに出た直後に herdr に問い合わせられないと、控えの前のペイン（今はほかの会話の物かもしれない）が残り、
        # その後のツールの呼び出しの印をそこへ送っていた
        self.handle({"hook_event_name": "UserPromptSubmit", "prompt": "前のターン"})

        def down(cwd, sid):
            raise activity.herdr.HerdrError(["herdr", "pane", "list"], "herdr に繋がらない")
        self.find = down
        self.handle({"hook_event_name": "UserPromptSubmit", "prompt": "次のターン"})
        self.handle({"hook_event_name": "PreToolUse", "tool_name": "Read", "tool_input": {"file_path": "/a/b.py"}})
        self.assertEqual(self.sent, [("w1:p1", "前のターン")])

    def test_tool_calls_do_not_wait_for_herdr_before_the_pane_is_known(self):
        self.handle({"hook_event_name": "PreToolUse", "tool_name": "Read", "tool_input": {"file_path": "/a/b.py"}})
        self.assertEqual((self.sent, self.looked), ([], []))

    def test_no_label_when_the_pane_is_not_settled(self):
        self.panes = [p for p in self.panes if p["pane_id"] != "w1:p1"]
        self.handle({"hook_event_name": "UserPromptSubmit", "prompt": "x"})
        self.handle({"hook_event_name": "UserPromptSubmit", "prompt": "y"})
        self.assertEqual(self.sent, [])
        self.assertEqual(self.looked, ["s1", "s1"])   # 決まらない間は控えず、次のターンで引き直す

    def test_outside_herdr_does_nothing(self):
        self.handle({"hook_event_name": "UserPromptSubmit", "prompt": "x"}, env={"TMPDIR": str(self.dir)})
        self.assertEqual(self.sent, [])

    def test_broken_input_does_nothing(self):
        activity.handle("{not json", self.env, send=lambda *a: self.sent.append(a), find=self.find)
        self.assertEqual(self.sent, [])


class Settings(unittest.TestCase):
    def test_prints_the_hooks_block_for_settings_json(self):
        got = activity.settings("/p/dispatch/activity.py")
        base = pathlib.Path("/p").resolve().as_posix()   # Windows では解くとドライブ名が付く（D:/p）
        hooks = got["hooks"]
        self.assertEqual(sorted(hooks), ["Notification", "PreToolUse", "Stop", "UserPromptSubmit"])
        for rows in hooks.values():
            # Python はフックと同じ hooks/run-python.sh で選ぶ（Windows の Store へ誘う代わりの物を飛ばす。TOML を読まないので下限 3.9）
            self.assertEqual(rows[0]["hooks"], [{"type": "command",
                                                 "command": f"bash {base}/hooks/run-python.sh --min 3.9 {base}/dispatch/activity.py"}])
        self.assertEqual(hooks["PreToolUse"][0]["matcher"], "")


if __name__ == "__main__":
    unittest.main()
