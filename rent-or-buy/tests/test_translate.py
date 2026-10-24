"""翻訳・会話の記録・コマンドが、ネットワークと ~/.cache に触れずに動く最小の試験。記録は手で作った見本。"""
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import unittest

PLUGIN = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PLUGIN))
from prompt_cache import prices, transcript, translate  # noqa: E402


def usage(read, write=0, inp=2):
    return {"input_tokens": inp, "cache_read_input_tokens": read, "cache_creation_input_tokens": write, "output_tokens": 9}


def line(**kw):
    return json.dumps(kw)


def sample(tmp):
    rows = [
        line(type="api-request", timestamp="2026-10-24T04:00:00.000Z", querySource="repl_main_thread"),
        line(type="assistant", message={"id": "m1", "model": "claude-opus-5-5", "usage": usage(90000)}),
        line(type="system", subtype="compact_boundary", compactMetadata={"trigger": "auto", "preTokens": 90000, "postTokens": 10000}),
        line(type="api-request", timestamp="2026-10-24T04:48:48.895Z", querySource="repl_main_thread"),
        line(type="api-request", timestamp="2026-10-24T04:49:00.000Z", querySource="other"),
        line(type="assistant", message={"id": "m2", "model": "claude-opus-5-5", "usage": usage(20000)}),
        line(type="assistant", message={"id": "m2", "model": "claude-opus-5-5", "usage": usage(20000)}),  # 同じ id は 1 つ
        line(type="assistant", message={"id": "m3", "model": "claude-opus-5-5", "usage": usage(30000, 1000)}),
        "{壊れた行",
    ]
    path = pathlib.Path(tmp) / "t.jsonl"
    path.write_text("\n".join(rows) + "\n", encoding="utf-8")
    return path


class TranslateTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.env = {**os.environ, "RENT_OR_BUY_OFFLINE": "1", "RENT_OR_BUY_CACHE_DIR": self.tmp.name,
                    "RENT_OR_BUY_RECORD": "off"}
        self.addCleanup(self.tmp.cleanup)

    def test_transcript_facts(self):
        tr = transcript.read(sample(self.tmp.name))
        self.assertEqual((tr["model"], tr["context_tokens"], tr["post_tokens"]), ("claude-opus-5-5", 31002, 10000))
        self.assertEqual(tr["last_request_at"], "2026-10-24T04:48:48.895Z")
        self.assertEqual(tr["contexts_after_compact"], [20002, 31002])
        self.assertEqual(tr["skipped_lines"], 1)
        empty = pathlib.Path(self.tmp.name) / "e.jsonl"
        empty.write_text("{}\n", encoding="utf-8")
        with self.assertRaises(transcript.TranscriptError):
            transcript.read(empty)

    def test_keepalive_numbers(self):
        out = translate.keepalive({"model": "claude-opus-5-5", "lifetime": 300, "context_tokens": 100000, "spent": 0,
                                   "certain": True, "last_request_at": "2026-10-24T04:48:48.895Z"}, env=self.env)
        self.assertAlmostEqual(out["rent"], 2e-7 * 100000 + 5e-6 * 380 + 2e-5 * 5)
        self.assertAlmostEqual(out["buy"], (5e-6 - 2e-7) * 100000)
        self.assertEqual((out["action"], out["next_at"], out["prices"]["source"]), ("rent", "2026-10-24T04:52:18Z", "snapshot"))
        self.assertFalse(out["consult"])

    def test_compact_numbers_and_haiku_tier(self):
        facts = {"model": "claude-opus-5-5", "lifetime": 300, "context_tokens": 150000, "spent": 0}
        out = translate.compact(facts, env=self.env)
        self.assertAlmostEqual(out["rent"], 125000 * 2e-7)
        self.assertAlmostEqual(out["buy"], 25000 * 5e-6 + 5000 * 2e-5)
        haiku = prices.lookup("claude-haiku-5-5", env=self.env)
        self.assertEqual((haiku.rate("read", 100000), haiku.rate("read", 100001)), (1e-8, 5e-8))

    def test_cli_smoke(self):
        path = sample(self.tmp.name)
        for cmd, stdin in (("keepalive", {"lifetime": 300, "spent": 0, "certain": True}), ("compact", {"lifetime": 300})):
            r = subprocess.run([sys.executable, str(PLUGIN / "bin" / "rent-or-buy"), cmd, "--transcript", str(path)],
                               input=json.dumps(stdin), capture_output=True, text=True, encoding="utf-8", env=self.env)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            out = json.loads(r.stdout)
            self.assertIn(out["action"], ("rent", "buy"))
            self.assertEqual(out["version"], json.loads((PLUGIN / ".claude-plugin" / "plugin.json").read_text())["version"])
        r = subprocess.run([sys.executable, str(PLUGIN / "bin" / "rent-or-buy"), "prices", "no-such-model"],
                           capture_output=True, text=True, encoding="utf-8", env=self.env)
        self.assertEqual((r.returncode, json.loads(r.stdout)["error"]), (3, "unknown_model"))


if __name__ == "__main__":
    unittest.main()
