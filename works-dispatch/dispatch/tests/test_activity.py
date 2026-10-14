"""サイドバーの作業内容のフック（activity.py）。Claude Code のフックの入力（JSON）から、herdr のサイドバーに出す 1 行を作る。"""

import json
import pathlib
import tempfile
import unittest

from . import DISPATCH  # noqa: F401
import activity


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
        self.sent = []
        self.env = {"HERDR_ENV": "1", "HERDR_PANE_ID": "w1:p1", "TMPDIR": str(self.dir)}

    def handle(self, payload, env=None):
        activity.handle(json.dumps(payload), self.env if env is None else env,
                        send=lambda pane, text, ttl: self.sent.append((pane, text)))

    def test_turn_end_goes_back_to_what_was_asked(self):
        self.handle({"hook_event_name": "UserPromptSubmit", "prompt": "テストを直して"})
        self.handle({"hook_event_name": "PreToolUse", "tool_name": "Read", "tool_input": {"file_path": "/a/b.py"}})
        self.handle({"hook_event_name": "Stop"})
        self.assertEqual(self.sent, [("w1:p1", "テストを直して"), ("w1:p1", "Read b.py"), ("w1:p1", "テストを直して")])

    def test_outside_herdr_does_nothing(self):
        self.handle({"hook_event_name": "UserPromptSubmit", "prompt": "x"}, env={"TMPDIR": str(self.dir)})
        self.assertEqual(self.sent, [])

    def test_broken_input_does_nothing(self):
        activity.handle("{not json", self.env, send=lambda *a: self.sent.append(a))
        self.assertEqual(self.sent, [])


class Settings(unittest.TestCase):
    def test_prints_the_hooks_block_for_settings_json(self):
        got = activity.settings("/p/dispatch/activity.py")
        hooks = got["hooks"]
        self.assertEqual(sorted(hooks), ["Notification", "PreToolUse", "Stop", "UserPromptSubmit"])
        for rows in hooks.values():
            self.assertEqual(rows[0]["hooks"], [{"type": "command", "command": "python3 /p/dispatch/activity.py"}])
        self.assertEqual(hooks["PreToolUse"][0]["matcher"], "")


if __name__ == "__main__":
    unittest.main()
