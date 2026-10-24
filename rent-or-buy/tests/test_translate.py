"""翻訳・会話の記録・コマンドが、ネットワークと ~/.cache に触れずに動く最小の試験。

記録は手で作った見本で、実際の会話の記録の中身は写していない。行の形（type・subtype・compactMetadata・
message.usage など）は Claude Code 2.1.310 の記録で確かめた。
"""
import calendar
import time
from unittest import mock
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
        # 手元の上書き（値段のファイル・モデル名の対応表）が試験に入らないよう、継がない
        inherited = {k: v for k, v in os.environ.items() if k not in ("RENT_OR_BUY_PRICES", "RENT_OR_BUY_MODEL_ALIASES")}
        self.env = {**inherited, "RENT_OR_BUY_OFFLINE": "1", "RENT_OR_BUY_CACHE_DIR": self.tmp.name,
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
        self.assertEqual(out["reason"], "within_buy_cost")
        self.assertNotIn("guide", out)

    def test_bad_facts(self):
        ok = {"model": "claude-opus-5-5", "lifetime": 300, "context_tokens": 1000, "spent": 0, "certain": True}
        for bad in ({"model": 5}, {"last_request_at": "2026-10-24T04:48:48"},  # 時差が無い
                    {"context_tokens": float("nan")}, {"context_tokens": float("inf")}, {"turn_end_at": "2026-10-24T04:48:48"}):
            with self.assertRaises(translate.FactsError, msg=bad):
                translate.keepalive({**ok, **bad}, env=self.env)
        with self.assertRaises(translate.FactsError):
            translate.compact({"model": ["x"], "lifetime": 300, "context_tokens": 1, "spent": 0}, env=self.env)
        out = translate.keepalive({**ok, "turn_end_at": "2026-10-24T13:00:00+09:00"}, env=self.env)
        self.assertEqual(out["turn_end_at"], "2026-10-24T04:00:00Z")

    def test_compact_tiers_use_post_for_write_and_n_for_output(self):
        haiku = prices.lookup("claude-haiku-5-5", env=self.env)
        out = translate.compact({"model": "claude-haiku-5-5", "lifetime": 300, "context_tokens": 150000, "spent": 0,
                                 "post_tokens": 20000, "summary_tokens": 1000}, env=self.env)
        self.assertAlmostEqual(out["buy"], 20000 * haiku.rate("write_5m", 20000) + 1000 * haiku.rate("output", 150000))
        self.assertNotEqual(haiku.rate("output", 150000), haiku.rate("output", 20000))

    def test_tier_fields_are_validated(self):
        base = {"input_cost_per_token": 2e-6, "cache_creation_input_token_cost": 3e-6,
                "cache_creation_input_token_cost_above_1hr": 4e-6, "cache_read_input_token_cost": 1e-7,
                "output_cost_per_token": 1e-5}
        entry = {**base, "input_cost_per_token_above_100k_tokens": 1e-6,   # 基より低い
                 "output_cost_per_token_above_100k_tokens": float("inf"),  # 有限でない
                 "cache_read_input_token_cost_above_100k_tokens": 2e-7}    # 正しい
        cleaned = prices.pick({"claude-x-1": entry})["claude-x-1"]
        self.assertEqual(sorted(k for k in cleaned if k.endswith("_above_100k_tokens")), ["cache_read_input_token_cost_above_100k_tokens"])

    def test_latest_is_skipped_when_stale(self):
        d = pathlib.Path(self.tmp.name)
        fresh = {"fetched": "2026-10-24", "commit": "x", "models": {"claude-opus-5-5": {
            "input_cost_per_token": 4e-6, "cache_creation_input_token_cost": 5e-6, "cache_creation_input_token_cost_above_1hr": 8e-6,
            "cache_read_input_token_cost": 1e-7, "output_cost_per_token": 2e-5}}}
        now = calendar.timegm((2026, 10, 25, 0, 0, 0))
        (d / "latest.json").write_text(json.dumps(fresh), encoding="utf-8")
        got = prices.lookup("claude-opus-5-5", env=self.env, now=now)
        self.assertEqual((got.source, got.info().get("latest_skipped")), ("latest", None))
        for fetched, when in (("2026-10-01", now), ("2026-10-24", calendar.timegm((2026, 11, 5, 0, 0, 0)))):
            (d / "latest.json").write_text(json.dumps({**fresh, "fetched": fetched}), encoding="utf-8")
            got = prices.lookup("claude-opus-5-5", env=self.env, now=when)
            self.assertEqual((got.source, got.info()["latest_skipped"]), ("snapshot", "stale"))

    def test_refresh_latest_survives_any_failure(self):
        for bad in (ValueError("x"), RuntimeError("y"), ["not", "a", "dict"]):
            with mock.patch.object(prices, "_http_json", side_effect=bad if isinstance(bad, Exception) else None,
                                   return_value=None if isinstance(bad, Exception) else bad):
                env = {**self.env, "RENT_OR_BUY_OFFLINE": "0", "RENT_OR_BUY_CACHE_DIR": tempfile.mkdtemp(dir=self.tmp.name)}
                prices.refresh_latest(env, now=time.time())
                self.assertFalse((pathlib.Path(env["RENT_OR_BUY_CACHE_DIR"]) / "latest.json").exists())

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

    def run_cli(self, *args, stdin="{}", **env):
        return subprocess.run([sys.executable, str(PLUGIN / "bin" / "rent-or-buy"), *args], input=stdin,
                              capture_output=True, text=True, encoding="utf-8", env={**self.env, **env})

    def test_failures_are_recorded_with_input(self):
        log = pathlib.Path(self.tmp.name) / "log.jsonl"
        stdin = json.dumps({"model": "no-such-model", "lifetime": 300, "context_tokens": 1, "spent": 0, "certain": True})
        r = self.run_cli("keepalive", stdin=stdin, RENT_OR_BUY_RECORD=str(log))
        self.assertEqual(r.returncode, 3, r.stdout)
        row = json.loads(log.read_text(encoding="utf-8").splitlines()[-1])
        self.assertEqual((row["scene"], row["input"]["model"], row["output"]["error"]), ("keepalive", "no-such-model", "unknown_model"))
        self.assertTrue(row["output"]["why"].isascii())
        before = log.read_text(encoding="utf-8")
        self.run_cli("prices", "no-such-model", RENT_OR_BUY_RECORD=str(log))
        self.assertEqual(log.read_text(encoding="utf-8"), before)  # prices の失敗は記録しない
        r = self.run_cli("decide", stdin=json.dumps({"rent": 1, "buy": 1, "spent": 0, "certain": True, "prices": {}}))
        self.assertEqual(r.returncode, 2)  # decide は prices を受けない

    def test_transcript_without_needed_facts_exits_4(self):
        path = pathlib.Path(self.tmp.name) / "only-boundary.jsonl"
        path.write_text(line(type="system", subtype="compact_boundary",
                             compactMetadata={"preTokens": 9, "postTokens": 5}) + "\n", encoding="utf-8")
        r = self.run_cli("compact", "--transcript", str(path), stdin=json.dumps({"lifetime": 300}))
        self.assertEqual((r.returncode, json.loads(r.stdout)["error"]), (4, "transcript_unreadable"))
        r = self.run_cli("compact", "--transcript", str(path),
                         stdin=json.dumps({"lifetime": 300, "model": "claude-opus-5-5", "context_tokens": 9, "spent": 0}))
        self.assertEqual(r.returncode, 0, r.stdout)  # 標準入力で足りれば通る


if __name__ == "__main__":
    unittest.main()
