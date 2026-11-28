"""launch ノード（作業場でアカウントの Claude Code を起動し、読み戻す）と turn ノード（ターンを送る）。偽物の herdr で回す。"""

import json
import os
import pathlib
import unittest

from . import DISPATCH  # noqa: F401
from . import schemacheck
import herdr as real_herdr
from nodes import launch, turn
from . import scratch


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

    def test_a_conversation_herdr_has_not_found_yet_is_looked_at_again(self):
        # 打ち込んだ直後は herdr がまだ会話を見つけておらず、agent get が agent_not_found で落ちる。会話はそのまま始まるので、
        # launch_failed にせず（持ち主の居ない会話が残る）、待って見直す
        h = FakeHerdr(shell=[True, False, False, True])
        answers = [real_herdr.Error(["herdr", "agent", "get"], "agent_not_found"), {"agent": "claude", "agent_status": "working"}]

        def agent(pane):
            h.calls.append(("agent", pane))
            got = answers.pop(0) if len(answers) > 1 else answers[0]
            if isinstance(got, Exception):
                raise got
            return got
        h.agent = agent
        got = launch.start_background(ROW, "w:p1", "直し", "/s", "頼み", h, posix=True, pause=lambda: None)
        self.assertEqual(got["status"], "sent")
        self.assertEqual(len([c for c in h.calls if c[0] == "agent"]), 2)

    def test_other_herdr_errors_while_waiting_are_launch_failed(self):
        h = FakeHerdr(shell=[True, False, True])

        def agent(pane):
            raise real_herdr.Error(["herdr", "agent", "get"], "pane_not_found")
        h.agent = agent
        got = launch.start_background(ROW, "w:p1", "直し", "/s", "頼み", h, posix=True, pause=lambda: None)
        self.assertEqual(got["status"], "launch_failed")
        self.assertIn("pane_not_found", got["detail"])

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
        # 2 ターン目の文はそのまま先に置き、後ろに引き継ぎの一言を空白 1 つでつなぐ（改行を足すとペインで途中送信になる）。一言の言い回しは
        # 会話だけが読むので見ず、2 ターン目の文が先に来ること・同じ行につなぐこと・1 ターン目のコマンドの名前が届くことを見る
        got = turn.with_carry("/attention:my-turn\n", "/watch:catchup")
        self.assertTrue(got.startswith("/attention:my-turn "), got)
        self.assertNotIn("\n", got)
        carry = got[len("/attention:my-turn "):]
        self.assertIn("/watch:catchup", carry)
        self.assertNotEqual(carry.strip(), "/watch:catchup")   # 名前だけでなく一言が足されている
        self.assertNotIn("my-turn", turn.CARRY)

    def test_the_earlier_report_line_follows_on_the_same_line_only_when_there_is_one(self):
        base = turn.with_carry("/attention:my-turn", "/watch:catchup")
        self.assertEqual(turn.with_carry("/attention:my-turn\n", "/watch:catchup", None), base)   # 報告が無ければ足さない
        self.assertNotIn("/g/works-dispatch/reports/s1.md", base)
        got = turn.with_carry("/attention:my-turn\n", "/watch:catchup", "/g/works-dispatch/reports/s1.md")
        self.assertTrue(got.startswith(base + " "), got)   # 引き継ぎの一言の後ろに、同じ行で続ける
        self.assertIn("/g/works-dispatch/reports/s1.md", got[len(base):])
        self.assertNotIn("\n", got)
        self.assertNotIn("my-turn", turn.EARLIER)
        h = FakeHerdr(prompts=["idle", "sent"])
        self.assertEqual(turn.catchup_then_second(7, "wB:p1", SECOND, h, catchup=CATCHUP, earlier="/r.md"), "sent")
        self.assertEqual(h.calls[1][2], turn.with_carry(SECOND, CATCHUP, "/r.md"))
        self.assertIn("/r.md", h.calls[1][2])

    def test_keep_report_writes_the_last_answer_of_each_turn_after_catchup(self):
        d = scratch()
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

    def test_the_second_goes_only_after_a_first_turn_that_ends(self):
        # 1 ターン目の結末の表。終わった（idle・done）なら 2 ターン目を送り、確かめの画面（blocked）か止まった（stalled）なら送らずに返す
        for first, want, sends in (("idle", "sent", 2), ("done", "sent", 2), ("blocked", "blocked", 1), ("stalled", "stalled", 1)):
            with self.subTest(first=first):
                h = FakeHerdr(prompts=[first, "sent"])
                self.assertEqual(turn.catchup_then_second(7, "p", SECOND, h, catchup=CATCHUP), want)
                self.assertEqual(len([c for c in h.calls if c[0] == "prompt"]), sends)

    def test_herdr_error_is_send_failed(self):
        self.assertEqual(turn.catchup_then_second(7, "p", SECOND, FakeHerdr(prompt_error="boom"), catchup=CATCHUP), "send_failed")

    BOX = "─" * 20 + "\n❯ \n" + "─" * 20

    def boxed(self, screens, statuses=None, prompts=None):
        """入力フィールドの画面（read）と herdr の見立て（agent）を、呼ばれるたびに頭から 1 つずつ返す偽物（最後の 1 つは返し続ける）。"""
        h = FakeHerdr(prompts=prompts)
        seq = {"read": list(screens), "agent": [{"agent": "claude", "agent_status": x} for x in (statuses or ["idle"])]}

        def take(kind, pane):
            h.calls.append((kind, pane))
            got = seq[kind]
            return got.pop(0) if len(got) > 1 else got[0]
        h.read = lambda pane, lines, ansi=False: take("read", pane)
        h.agent = lambda pane: take("agent", pane)
        return h

    def test_in_order_types_the_next_command_only_after_the_turn_ends(self):
        # 頼み 96bf89。1 本目のターンが終わる（Claude Code が idle を返す）まで、2 本目を打たない
        h = self.boxed([self.BOX], prompts=["working", "sent"])
        seen = []

        def state():
            seen.append(len([c for c in h.calls if c[0] == "prompt"]))
            return "busy" if len(seen) < 3 else "idle"
        self.assertEqual(turn.in_order("p", ["/a", "/b"], h, state=state, pause=lambda: None), ("sent", 2))
        prompts = [c for c in h.calls if c[0] == "prompt"]
        self.assertEqual(prompts, [("prompt", "p", "/a", True, ("working", "blocked")), ("prompt", "p", "/b", False)])
        self.assertEqual(seen, [1, 1, 1])   # 2 本目を打つ前に、1 本目の終わりを 3 回問うた

    def test_in_order_trusts_claude_code_idle_over_a_herdr_working_left_by_a_background_wait(self):
        # 会話が裏に待ちのコマンドを残すと、herdr はターンが終わっても working と見続ける（#2003）。Claude Code が idle を返したら 2 本目を打つ
        h = self.boxed([self.BOX], statuses=["idle", "working"], prompts=["working", "sent"])
        self.assertEqual(turn.in_order("p", ["/a", "/b"], h, state=lambda: "idle", pause=lambda: None), ("sent", 2))

    def test_in_order_stops_before_a_command_when_text_is_typed_or_the_box_is_not_seen(self):
        typed = "─" * 20 + "\n❯ 打ちかけ\n" + "─" * 20
        for screens, want in (([self.BOX, typed], ("typing", 1)), ([typed], ("typing", 0)), ([""], ("typing", 0))):
            with self.subTest(screens=screens):
                h = self.boxed(screens)
                self.assertEqual(turn.in_order("p", ["/a", "/b"], h, state=lambda: "idle", pause=lambda: None), want)
                self.assertEqual(len([c for c in h.calls if c[0] == "prompt"]), want[1])

    def test_in_order_does_not_type_into_a_working_conversation(self):
        h = self.boxed([self.BOX], statuses=["working"])
        self.assertEqual(turn.in_order("p", ["/a"], h), ("busy", 0))
        self.assertNotIn("prompt", [c[0] for c in h.calls])

    def test_in_order_stops_after_a_blocked_or_stalled_command(self):
        for word in ("blocked", "stalled"):
            with self.subTest(word):
                h = self.boxed([self.BOX], prompts=[word])
                self.assertEqual(turn.in_order("p", ["/a", "/b"], h, state=lambda: "idle", pause=lambda: None), (word, 1))

    def test_in_order_herdr_error_is_send_failed_with_what_was_typed(self):
        h = self.boxed([self.BOX])
        h._prompt_error = "boom"
        self.assertEqual(turn.in_order("p", ["/a", "/b"], h), ("send_failed", 0))

    def test_send_returns_schema_shaped_result(self):
        out = {"schema": 1, "turn": turn.send("p", "x", True, FakeHerdr(prompts=["blocked"]))}
        self.assertEqual(out["turn"]["status"], "blocked")
        self.assertEqual(schemacheck.check(out, schemacheck.schema("turn")), [])


if __name__ == "__main__":
    unittest.main()
