"""launch ノード（作業場でアカウントの Claude Code を起こし、読み戻す）と turn ノード（ターンを送る）。偽物の herdr で回す。"""

import unittest

from . import DISPATCH  # noqa: F401
from . import schemacheck
import herdr as real_herdr
from nodes import launch, turn


class FakeHerdr:
    HerdrError = real_herdr.HerdrError

    def __init__(self, agent=None, run_error=None, prompts=None, prompt_error=None):
        self.calls = []
        self._agent = agent if agent is not None else {"agent": "claude", "agent_status": "idle"}
        self._run_error = run_error
        self._prompts = list(prompts or [])
        self._prompt_error = prompt_error

    def run(self, pane, command):
        self.calls.append(("run", pane, command))
        if self._run_error:
            raise real_herdr.HerdrError(["herdr", "pane", "run"], self._run_error)

    def wait_ready(self, pane):
        self.calls.append(("wait_ready", pane))
        return "idle"

    def agent(self, pane):
        self.calls.append(("agent", pane))
        return self._agent

    def prompt(self, target, text, wait):
        self.calls.append(("prompt", target, text, wait))
        if self._prompt_error:
            raise real_herdr.HerdrError(["herdr", "agent", "prompt"], self._prompt_error)
        return self._prompts.pop(0) if self._prompts else ("idle" if wait else "sent")


ROW = {"number": 7, "clone_path": "/c/r-pr-7", "account": {"name": "p1", "command": "claude-x"}}
SECOND = "1. 深掘り\n2. 世の中の解 'x' $y"


class Launch(unittest.TestCase):
    def test_runs_account_command_in_slot_pane_and_reads_back(self):
        h = FakeHerdr()
        got = launch.start(ROW, "wB:p1", h)
        self.assertEqual(got["status"], "ready")
        self.assertEqual(h.calls[0], ("run", "wB:p1", "claude-x"))
        self.assertIn(("agent", "wB:p1"), h.calls)

    def test_no_conversation_on_read_back_is_launch_failed(self):
        got = launch.start(ROW, "wB:p1", FakeHerdr(agent={"agent": None, "agent_status": "unknown"}))
        self.assertEqual(got["status"], "launch_failed")

    def test_herdr_error_is_launch_failed(self):
        got = launch.start(ROW, "wB:p1", FakeHerdr(run_error="pane_not_found"))
        self.assertEqual(got["status"], "launch_failed")
        self.assertIn("pane_not_found", got["detail"])

    def test_output_matches_schema(self):
        out = {"schema": 1, "launch": launch.start(ROW, "wB:p1", FakeHerdr())}
        self.assertEqual(schemacheck.check(out, schemacheck.schema("launch")), [])


class Turn(unittest.TestCase):
    def test_idle_after_catchup_sends_second_without_waiting(self):
        h = FakeHerdr(prompts=["idle", "sent"])
        self.assertEqual(turn.catchup_then_second(7, "wB:p1", SECOND, h), "sent")
        self.assertEqual(h.calls, [("prompt", "wB:p1", "/catchup 7", True), ("prompt", "wB:p1", SECOND, False)])

    def test_without_second_sends_only_catchup_and_does_not_wait(self):
        h = FakeHerdr(prompts=["sent"])
        self.assertEqual(turn.catchup_then_second(7, "wB:p1", None, h), "sent")
        self.assertEqual(h.calls, [("prompt", "wB:p1", "/catchup 7", False)])

    def test_done_also_sends_second(self):
        self.assertEqual(turn.catchup_then_second(7, "p", SECOND, FakeHerdr(prompts=["done", "sent"])), "sent")

    def test_blocked_does_not_send_second(self):
        h = FakeHerdr(prompts=["blocked"])
        self.assertEqual(turn.catchup_then_second(7, "p", SECOND, h), "blocked")
        self.assertEqual(len(h.calls), 1)

    def test_stalled_does_not_send_second(self):
        h = FakeHerdr(prompts=["stalled"])
        self.assertEqual(turn.catchup_then_second(7, "p", SECOND, h), "stalled")
        self.assertEqual(len(h.calls), 1)

    def test_herdr_error_is_send_failed(self):
        self.assertEqual(turn.catchup_then_second(7, "p", SECOND, FakeHerdr(prompt_error="boom")), "send_failed")

    def test_send_returns_schema_shaped_result(self):
        out = {"schema": 1, "turn": turn.send("p", "x", True, FakeHerdr(prompts=["blocked"]))}
        self.assertEqual(out["turn"]["status"], "blocked")
        self.assertEqual(schemacheck.check(out, schemacheck.schema("turn")), [])


if __name__ == "__main__":
    unittest.main()
