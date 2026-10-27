"""launch ノード（作業場でアカウントの Claude Code を起動し、読み戻す）と turn ノード（ターンを送る）。偽物の herdr で回す。"""

import json
import os
import pathlib
import tempfile
import unittest

from . import DISPATCH  # noqa: F401
from . import schemacheck
import herdr as real_herdr
from nodes import launch, turn


class FakeHerdr:
    Error = real_herdr.Error

    def __init__(self, agent=None, run_error=None, prompts=None, prompt_error=None, shell=True, ready="idle", rename_error=None):
        self.calls = []
        self._rename_error = rename_error
        self._shell = shell
        self._ready = ready
        self._agent = agent if agent is not None else {"agent": "claude", "agent_status": "idle"}
        self._run_error = run_error
        self._prompts = list(prompts or [])
        self._prompt_error = prompt_error

    def run(self, pane, command):
        self.calls.append(("run", pane, command))
        if self._run_error:
            raise real_herdr.Error(["herdr", "pane", "run"], self._run_error)

    def shell_in_front(self, pane):
        """shell が並びなら、呼ばれるたびに頭から 1 つずつ返す（最後の 1 つは返し続ける）。"""
        self.calls.append(("shell_in_front", pane))
        if isinstance(self._shell, list):
            return self._shell.pop(0) if len(self._shell) > 1 else self._shell[0]
        return self._shell

    def wait_ready(self, pane):
        self.calls.append(("wait_ready", pane))
        return self._ready

    def agent(self, pane):
        self.calls.append(("agent", pane))
        return self._agent

    def rename_pane(self, pane, label):
        self.calls.append(("rename_pane", pane, label))
        if self._rename_error:
            raise real_herdr.Error(["herdr", "pane", "rename"], self._rename_error)

    def prompt(self, target, text, wait, until=()):
        self.calls.append(("prompt", target, text, wait) + ((tuple(until),) if until else ()))
        if self._prompt_error:
            raise real_herdr.Error(["herdr", "agent", "prompt"], self._prompt_error)
        return self._prompts.pop(0) if self._prompts else ("idle" if wait else "sent")


ROW = {"number": 7, "clone_path": "/c/r-pr-7", "account": {"name": "p1", "command": "claude-x"}}
CATCHUP = "/attention:catchup"
SECOND = "1. 深掘り\n2. 世の中の解 'x' $y"


class Launch(unittest.TestCase):
    def test_runs_account_command_in_slot_pane_and_reads_back(self):
        h = FakeHerdr()
        got = launch.start(ROW, "wB:p1", h, posix=True, settings="/p/session settings.json")
        self.assertEqual(got["status"], "ready")
        self.assertEqual(h.calls[:2], [("shell_in_front", "wB:p1"),
                                       ("run", "wB:p1", "ATTENTION_CATCHUP_OPEN=0 claude-x --settings '/p/session settings.json'")])
        self.assertIn(("agent", "wB:p1"), h.calls)

    def test_without_a_posix_shell_the_command_is_typed_as_is(self):
        h = FakeHerdr()
        launch.start(ROW, "wB:p1", h, posix=False, settings="C:/p/session-settings.json")
        self.assertIn(("run", "wB:p1", 'claude-x --settings "C:/p/session-settings.json"'), h.calls)

    def test_the_settings_file_keeps_the_choice_prompt_tool_off(self):
        # PR の会話が選択肢の画面で止まると、窓を開いてキーを押すまで進まない（2026-10-23、guided-resolver の issue #1895）
        got = json.loads(pathlib.Path(launch.SESSION_SETTINGS).read_text(encoding="utf-8"))
        self.assertIn("AskUserQuestion", got["permissions"]["deny"])

    def test_no_conversation_on_read_back_is_launch_failed(self):
        got = launch.start(ROW, "wB:p1", FakeHerdr(agent={"agent": None, "agent_status": "unknown"}))
        self.assertEqual(got["status"], "launch_failed")

    def test_herdr_error_is_launch_failed(self):
        got = launch.start(ROW, "wB:p1", FakeHerdr(run_error="pane_not_found"))
        self.assertEqual(got["status"], "launch_failed")
        self.assertIn("pane_not_found", got["detail"])

    def test_pane_with_something_else_in_front_is_not_typed_into(self):
        # 使い直すペインに vim・dev server・別の会話が残っていれば、起動のコマンドをそこへ打ち込まない
        h = FakeHerdr(shell=False)
        got = launch.start(ROW, "wB:p1", h)
        self.assertEqual(got["status"], "pane_busy")
        self.assertNotIn("run", [c[0] for c in h.calls])

    def test_confirmation_screen_after_start_is_blocked_not_a_hang(self):
        # フォルダの信頼・ログインの画面で止まったら、待ち続けずに blocked で返す（そのペインで人が答える）
        got = launch.start(ROW, "wB:p1", FakeHerdr(ready="blocked"))
        self.assertEqual(got["status"], "blocked")
        self.assertIn("確認", got["detail"])

    def test_output_matches_schema(self):
        for h in (FakeHerdr(), FakeHerdr(shell=False), FakeHerdr(ready="blocked")):
            out = {"schema": 1, "launch": launch.start(ROW, "wB:p1", h)}
            self.assertEqual(schemacheck.check(out, schemacheck.schema("launch")), [])
        out = {"schema": 1, "launch": launch.start(ROW, "wB:p1", FakeHerdr())}
        self.assertEqual(schemacheck.check(out, schemacheck.schema("launch")), [])


class StartBackground(unittest.TestCase):
    """部署（入口の --task）の起動方法: ペインに名前を付け、裏の会話（--bg）を名前と設定と最初の文を付けて打ち込み、シェルが戻るのを待つ。"""

    def test_names_the_pane_then_types_the_background_start_and_waits_for_the_shell(self):
        h = FakeHerdr(shell=[True, False, True])
        got = launch.start_background({**ROW, "label": "直し p2"}, "w:p1", "直し 'a'", "/s/set.json", "頼み「x」", h, posix=True,
                                      pause=lambda: None)
        self.assertEqual(got["status"], "sent")
        self.assertEqual([c for c in h.calls if c[0] in ("rename_pane", "run")],
                         [("rename_pane", "w:p1", "直し p2"),
                          ("run", "w:p1", "claude-x --bg --name '直し '\"'\"'a'\"'\"'' --settings /s/set.json '頼み「x」'")])

    def test_without_a_posix_shell_words_are_double_quoted(self):
        h = FakeHerdr()
        launch.start_background(ROW, "w:p1", "直し", "C:\\s\\set.json", "頼み", h, posix=False, pause=lambda: None)
        self.assertEqual([c for c in h.calls if c[0] == "run"],
                         [("run", "w:p1", 'claude-x --bg --name "直し" --settings "C:\\s\\set.json" "頼み"')])

    def test_a_confirmation_screen_is_blocked_not_a_hang(self):
        h = FakeHerdr(shell=[True, False], agent={"agent": "claude", "agent_status": "blocked"})
        got = launch.start_background(ROW, "w:p1", "直し", "/s", "頼み", h, posix=True, pause=lambda: None)
        self.assertEqual(got["status"], "blocked")

    def test_a_pane_name_that_cannot_be_set_does_not_stop_the_start(self):
        h = FakeHerdr(rename_error="pane_not_found")
        got = launch.start_background({**ROW, "label": "x"}, "w:p1", "直し", "/s", "頼み", h, posix=True, pause=lambda: None)
        self.assertEqual(got["status"], "sent")
        self.assertIn("ペインに名前を付けられなかった", got["detail"])

    def test_busy_pane_is_neither_named_nor_typed_into(self):
        h = FakeHerdr(shell=False)
        got = launch.start_background({**ROW, "label": "x"}, "w:p1", "直し", "/s", "頼み", h, posix=True, pause=lambda: None)
        self.assertEqual(got["status"], "pane_busy")
        self.assertFalse([c for c in h.calls if c[0] in ("rename_pane", "run")])

    def test_herdr_error_is_launch_failed(self):
        got = launch.start_background(ROW, "w:p1", "直し", "/s", "頼み", FakeHerdr(run_error="pane_not_found"), posix=True,
                                      pause=lambda: None)
        self.assertEqual(got["status"], "launch_failed")

    def test_attach_types_the_account_command_with_the_id(self):
        h = FakeHerdr()
        self.assertEqual(launch.attach(ROW, "w:p1", "82fbd328", h)["status"], "attached")
        self.assertEqual(h.calls, [("run", "w:p1", "claude-x attach 82fbd328")])
        self.assertEqual(launch.attach(ROW, "w:p1", "x", FakeHerdr(run_error="boom"))["status"], "launch_failed")


class Turn(unittest.TestCase):
    def test_idle_after_catchup_sends_second_without_waiting(self):
        h = FakeHerdr(prompts=["idle", "sent"])
        self.assertEqual(turn.catchup_then_second(7, "wB:p1", SECOND, h, catchup=CATCHUP), "sent")
        self.assertEqual(h.calls, [("prompt", "wB:p1", "/attention:catchup 7", True),
                                   ("prompt", "wB:p1", turn.with_carry(SECOND, CATCHUP), False)])

    def test_second_ends_with_the_carry_line_on_the_same_line(self):
        # 2 ターン目の文はそのまま先に置き、後ろに引き継ぎの一言を空白 1 つでつなぐ（改行を足すとペインで途中送信になる）
        got = turn.with_carry("/attention:my-turn\n", "/watch:catchup")
        self.assertEqual(got, "/attention:my-turn この会話の前のターン（/watch:catchup）で調べた物は、材料として引き継いでよい。"
                              "取り直すのは、前のターンの後に変わった物と、前のターンで調べていない物だけ。"
                              "前のターンで問うた事と、いま問う事が違えば調べ直す。")
        self.assertNotIn("\n", got)
        self.assertNotIn("my-turn", turn.CARRY)

    def test_the_earlier_report_line_follows_on_the_same_line_only_when_there_is_one(self):
        got = turn.with_carry("/attention:my-turn\n", "/watch:catchup", "/g/works-dispatch/reports/s1.md")
        self.assertEqual(got, turn.with_carry("/attention:my-turn", "/watch:catchup")
                         + " 前にこの PR を開いた会話の報告（GitHub に出していない発見を含みうる）を /g/works-dispatch/reports/s1.md に"
                           "残した。前の回の発見として読んでよい。")
        self.assertNotIn("\n", got)
        self.assertNotIn("my-turn", turn.EARLIER)
        h = FakeHerdr(prompts=["idle", "sent"])
        self.assertEqual(turn.catchup_then_second(7, "wB:p1", SECOND, h, catchup=CATCHUP, earlier="/r.md"), "sent")
        self.assertEqual(h.calls[1][2], turn.with_carry(SECOND, CATCHUP, "/r.md"))

    def test_keep_report_writes_the_last_answer_of_each_turn_after_catchup(self):
        d = tempfile.mkdtemp()
        folder = os.path.join(d, "reports")
        def talk(name, *rows):
            path = os.path.join(d, name)
            pathlib.Path(path).write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
            return path
        said = lambda text, **k: {"type": "user", "message": {"role": "user", "content": text}, **k}
        answer = lambda *content, **k: {"type": "assistant", "message": {"role": "assistant", "content": list(content)}, **k}
        text = lambda t: {"type": "text", "text": t}
        catchup = said(f"<command-message>attention:catchup</command-message>\n<command-name>{CATCHUP}</command-name>\n<command-args>7</command-args>")
        first = talk("s1.jsonl",
                     catchup, answer(text("PR の今")),
                     said("<task-notification>\n<task-id>b1</task-id>\n</task-notification>"), answer(text("catchup の続き")),
                     said(f"/attention:my-turn この会話の前のターン（{CATCHUP}）で調べた物は…"),
                     answer({"type": "tool_use", "id": "t1", "name": "Bash", "input": {}}),
                     said([{"type": "tool_result", "tool_use_id": "t1", "content": "out"}]),
                     answer(text("途中の字")), answer(text("報告: helm test に寄せれば写しも守りも消える")),
                     said("Caveat: …", isMeta=True), answer(text("サブエージェントの答え"), isSidechain=True),
                     said("<command-name>/exit</command-name>"),
                     said("続けて"), answer(text("追加の発見")),
                     said("<local-command-stdout>done</local-command-stdout>"), answer(text("続きの答え")),
                     said(f"{CATCHUP} 7"), answer(text("後から打った catchup の答え")))
        kept = turn.keep_report(first, folder, CATCHUP)
        self.assertEqual(kept, os.path.join(folder, "s1.md"))
        body = pathlib.Path(kept).read_text(encoding="utf-8")
        self.assertIn(f"会話の記録: {first}", body)
        self.assertIn("## /attention:my-turn", body)
        self.assertLess(body.index("報告: helm test"), body.index("## 続けて"))
        self.assertLess(body.index("## 続けて"), body.index("続きの答え"))
        self.assertNotIn("追加の発見", body, "スラッシュコマンドの出力の行は前のターンの続きで、その答えが最後の答えになる")
        self.assertIn("後から打った catchup の答え", body, "落とすのは最初の /catchup のターンだけ")
        for gone in ("PR の今", "catchup の続き", "task-notification", "途中の字", "サブエージェントの答え", "/exit"):
            self.assertNotIn(gone, body)
        self.assertIsNone(turn.keep_report(talk("s2.jsonl", catchup, answer(text("PR の今"))), folder, CATCHUP),
                          "/catchup だけで終えた会話には報告が無い")
        typed = pathlib.Path(turn.keep_report(talk("s3.jsonl", said("<task-notification>x</task-notification>"), answer(text("先頭の知らせ")),
                                                   said(f"{CATCHUP} 7"), answer(text("PR の今")),
                                                   said(f"{CATCHUP}-foo"), answer(text("別のコマンド"))), folder, CATCHUP)).read_text(encoding="utf-8")
        self.assertNotIn("PR の今", typed, "打った字のままの /catchup も見分ける")
        self.assertIn("別のコマンド", typed, "名前が /catchup で始まるだけの別のコマンドは残す")
        self.assertNotIn("先頭の知らせ", typed, "続ける前のターンの無い知らせの行は捨てる")
        self.assertEqual(sorted(os.listdir(folder)), ["s1.md", "s3.md"])
        self.assertIn("catchup の続き", pathlib.Path(turn.keep_report(first, folder, None)).read_text(encoding="utf-8"),
                      "コマンドの名前が分からなければ見分けずに残す")
        self.assertIsNone(turn.keep_report(os.path.join(d, "none.jsonl"), folder, CATCHUP))

    def test_without_second_sends_only_catchup_and_does_not_wait(self):
        h = FakeHerdr(prompts=["sent"])
        self.assertEqual(turn.catchup_then_second(7, "wB:p1", None, h, catchup=CATCHUP), "sent")
        self.assertEqual(h.calls, [("prompt", "wB:p1", "/attention:catchup 7", False)])

    def test_sends_the_catchup_command_it_is_given(self):
        h = FakeHerdr(prompts=["sent"])
        turn.catchup_then_second(7, "p", None, h, catchup="/watch:catchup")
        self.assertEqual(h.calls, [("prompt", "p", "/watch:catchup 7", False)])

    def test_done_also_sends_second(self):
        self.assertEqual(turn.catchup_then_second(7, "p", SECOND, FakeHerdr(prompts=["done", "sent"]), catchup=CATCHUP), "sent")

    def test_blocked_does_not_send_second(self):
        h = FakeHerdr(prompts=["blocked"])
        self.assertEqual(turn.catchup_then_second(7, "p", SECOND, h, catchup=CATCHUP), "blocked")
        self.assertEqual(len(h.calls), 1)

    def test_stalled_does_not_send_second(self):
        h = FakeHerdr(prompts=["stalled"])
        self.assertEqual(turn.catchup_then_second(7, "p", SECOND, h, catchup=CATCHUP), "stalled")
        self.assertEqual(len(h.calls), 1)

    def test_herdr_error_is_send_failed(self):
        self.assertEqual(turn.catchup_then_second(7, "p", SECOND, FakeHerdr(prompt_error="boom"), catchup=CATCHUP), "send_failed")

    def test_send_returns_schema_shaped_result(self):
        out = {"schema": 1, "turn": turn.send("p", "x", True, FakeHerdr(prompts=["blocked"]))}
        self.assertEqual(out["turn"]["status"], "blocked")
        self.assertEqual(schemacheck.check(out, schemacheck.schema("turn")), [])


if __name__ == "__main__":
    unittest.main()
