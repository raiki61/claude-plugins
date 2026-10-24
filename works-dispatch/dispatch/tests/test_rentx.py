"""借りるか買うかの部品（rent-or-buy）への口 rentx.py と、会話の記録の最後の答えを読む claudex.last_reply。"""

import json
import os
import pathlib
import subprocess
import tempfile
import time
import unittest

from . import DISPATCH
import rentx
from ports import chat


class Locate(unittest.TestCase):
    def test_the_checkout_next_door_comes_first(self):
        found = rentx.locate()
        self.assertEqual(pathlib.Path(found), DISPATCH.parent.parent / "rent-or-buy" / "bin" / "rent-or-buy")

    def test_an_installed_copy_is_found_from_the_record_of_the_same_marketplace(self):
        d = pathlib.Path(tempfile.mkdtemp())
        here = d / "plugins" / "cache" / "m1" / "works-dispatch" / "1.0.0" / "dispatch" / "rentx.py"
        here.parent.mkdir(parents=True)
        here.write_text("")
        part = d / "plugins" / "cache" / "m1" / "rent-or-buy" / "0.1.0"
        (part / "bin").mkdir(parents=True)
        (part / "bin" / "rent-or-buy").write_text("")
        other = d / "elsewhere"
        record = {"plugins": {"rent-or-buy@m1": [{"scope": "project", "installPath": str(other)},
                                                  {"scope": "user", "installPath": str(part)}],
                              "rent-or-buy@m2": [{"scope": "user", "installPath": str(other)}]}}
        (d / "plugins" / chat.PLUGINS_FILE).write_text(json.dumps(record))
        self.assertEqual(rentx.locate(here), str(part / "bin" / "rent-or-buy"))
        (d / "plugins" / chat.PLUGINS_FILE).write_text("{")
        self.assertIsNone(rentx.locate(here))   # 控えが読めなければ無いと見る（呼ぶ側は決まった数で動く）

    def test_outside_the_cache_and_without_a_checkout_it_is_missing(self):
        here = pathlib.Path(tempfile.mkdtemp()) / "works-dispatch" / "dispatch" / "rentx.py"
        self.assertIsNone(rentx.locate(here))
        self.assertEqual(rentx.ask("keepalive", {}, here=here), (None, "借りるか買うかの部品（rent-or-buy）が入っていない"))


class Ask(unittest.TestCase):
    def run_with(self, stdout, code=0):
        seen = []

        def runner(argv, **kw):
            seen.append((argv, kw["input"]))
            return subprocess.CompletedProcess(argv, code, stdout, "")
        return seen, runner

    def test_it_returns_the_answer_or_a_reason(self):
        seen, runner = self.run_with(json.dumps({"action": "rent", "next_at": "2026-10-24T00:04:00Z"}))
        got, why = rentx.ask("keepalive", {"spent": 0}, transcript="/t.jsonl", runner=runner)
        self.assertEqual((got["action"], why), ("rent", None))
        self.assertEqual(seen[0][0][2:], ["keepalive", "--transcript", "/t.jsonl"])
        self.assertEqual(json.loads(seen[0][1]), {"spent": 0})
        for out, code, head in (("x", 0, "出力が JSON でない"), ("[]", 0, "出力が表でない"),
                                (json.dumps({"error": "bad_input", "why": "w"}), 2, "答えなかった（終了コード 2"),
                                (json.dumps({"action": "wait"}), 0, "action が rent・buy のどちらでもない")):
            got, why = rentx.ask("compact", {}, runner=self.run_with(out, code)[1])
            self.assertIsNone(got)
            self.assertIn(head, why)

    def test_the_real_part_answers_a_keepalive_with_its_next_time(self):
        # リポジトリの隣の部品を本当に起動する（試験は記録を書かせず、値段を取りに行かせない。tests/__init__.py）
        at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(0))
        got, why = rentx.ask("keepalive", {"model": "claude-opus-5-5", "lifetime": 300, "context_tokens": 100000, "spent": 0,
                                           "certain": True, "last_request_at": at})
        self.assertIsNone(why)
        self.assertEqual((got["action"], got["next_at"]), ("rent", "1970-01-01T00:04:00Z"))
        got, why = rentx.ask("keepalive", {"lifetime": 300})
        self.assertIsNone(got)
        self.assertIn("終了コード 2", why)


class LastReply(unittest.TestCase):
    def test_it_reads_the_last_answer_and_the_text_that_started_the_turn(self):
        path = os.path.join(tempfile.mkdtemp(), "t.jsonl")
        rows = [{"type": "user", "message": {"content": "前の文"}},
                {"type": "assistant", "message": {"content": [{"type": "text", "text": "前の答え"}]}},
                {"type": "user", "message": {"content": "問い"}},
                {"type": "assistant", "message": {"content": [{"type": "tool_use", "name": "x"}]}},
                {"type": "user", "message": {"content": [{"type": "tool_result", "content": "r"}]}},
                {"type": "assistant", "isSidechain": True, "message": {"content": [{"type": "text", "text": "下請け"}]}},
                {"type": "assistant", "message": {"content": [{"type": "text", "text": "答え"}]}},
                {"type": "system", "subtype": "stop_hook_summary"}]
        pathlib.Path(path).write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
        self.assertEqual(chat.last_reply({"transcript_path": path}), ("答え", "問い"))
        self.assertEqual(chat.last_reply({"transcript_path": "/none/t.jsonl"}), ("", ""))
        self.assertEqual(chat.last_reply({}), ("", ""))


if __name__ == "__main__":
    unittest.main()
