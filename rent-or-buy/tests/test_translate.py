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
        line(type="assistant", message={"id": "m2", "model": "claude-opus-5-5", "usage": usage(15000, 1000)}),
        line(type="assistant", message={"id": "m2", "model": "claude-opus-5-5", "usage": usage(15000, 5000)}),  # 同じ id は最後の行
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
        self.assertEqual((tr["model"], tr["context_tokens"]), ("claude-opus-5-5", 31002))
        # compact の後の最初の応答（m2 の最後の行）の書き込み（キャッシュに無い入力 2 を含む）と読み。postTokens は使わない
        self.assertEqual((tr["after_write_tokens"], tr["after_read_tokens"]), (5002, 15000))
        self.assertNotIn("post_tokens", tr)
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
        self.assertEqual((out["action"], out["next_at"], out["prices"]["source"]), ("rent", "2026-10-24T04:52:48Z", "snapshot"))
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

    def test_compact_tiers_use_after_for_write_and_n_for_output(self):
        haiku = prices.lookup("claude-haiku-5-5", env=self.env)
        out = translate.compact({"model": "claude-haiku-5-5", "lifetime": 300, "context_tokens": 150000, "spent": 0,
                                 "after_write_tokens": 20000, "after_read_tokens": 5000, "summary_tokens": 1000}, env=self.env)
        fixed = (20000 * haiku.rate("write_5m", 25000) + 5000 * haiku.rate("read", 25000)
                 + 1000 * haiku.rate("output", 150000))
        self.assertAlmostEqual(out["compact_cost"], fixed)
        self.assertAlmostEqual(out["rent"], 125000 * haiku.rate("read", 150000))
        self.assertAlmostEqual(out["buy"], fixed + out["rent"])
        self.assertNotEqual(haiku.rate("output", 150000), haiku.rate("output", 20000))
        # compact の後が 10 万を超えれば、書き込みと読みは上の段（文脈 99,000 なら出力は下の段）
        big = translate.compact({"model": "claude-haiku-5-5", "lifetime": 300, "context_tokens": 99000, "spent": 0,
                                 "after_write_tokens": 90000, "after_read_tokens": 20000, "summary_tokens": 1000}, env=self.env)
        self.assertAlmostEqual(big["compact_cost"], 90000 * haiku.rate("write_5m", 110000) + 20000 * haiku.rate("read", 110000)
                               + 1000 * haiku.rate("output", 99000))
        self.assertNotEqual(haiku.rate("read", 110000), haiku.rate("read", 99000))
        self.assertEqual(big["rent"], 0)

    def test_compact_buys_when_spent_reaches_fixed_cost_and_consult_cost(self):
        # 規則は spent ≥ F' + consult_cost（要約の要求が今の文脈を読むので、この 1 本の rent は浮かない）
        base = {"model": "claude-opus-5-5", "lifetime": 3600, "context_tokens": 130000, "consult_cost": 0.01}
        f = translate.compact({**base, "spent": 0}, env=self.env)["compact_cost"]
        below = translate.compact({**base, "spent": f + 0.01 - 1e-6}, env=self.env)
        at = translate.compact({**base, "spent": f + 0.01}, env=self.env)
        self.assertEqual((below["action"], at["action"]), ("rent", "buy"))

    def test_compact_defaults_come_from_prices_toml(self):
        d = prices.defaults()["compact"]
        opus = prices.lookup("claude-opus-5-5", env=self.env)
        out = translate.compact({"model": "claude-opus-5-5", "lifetime": 3600, "context_tokens": 130000, "spent": 0},
                                env=self.env)
        after = d["after_write_tokens"] + d["after_read_tokens"]
        self.assertEqual(translate.after_tokens({}), after)
        self.assertAlmostEqual(out["compact_cost"], d["after_write_tokens"] * opus.rate("write_1h", after)
                               + d["after_read_tokens"] * opus.rate("read", after)
                               + d["summary_tokens"] * opus.rate("output", 130000))

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
        self.assertAlmostEqual(out["rent"], (150000 - 37000 - 8000) * 2e-7)
        self.assertAlmostEqual(out["buy"], 37000 * 5e-6 + 8000 * 2e-7 + 9000 * 2e-5 + out["rent"])
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


    def test_spent_from_transcript_uses_the_first_request_after_compact(self):
        r = self.run_cli("compact", "--transcript", str(sample(self.tmp.name)), stdin=json.dumps({"lifetime": 300}))
        out = json.loads(r.stdout)
        read = prices.lookup("claude-opus-5-5", env=self.env).rate("read", 31002)
        # compact の後の文脈は m2 の書き込み 5002 + 読み 15000
        self.assertAlmostEqual(out["rent"], (31002 - 20002) * read)
        r = self.run_cli("compact", "--transcript", str(sample(self.tmp.name)),
                         stdin=json.dumps({"lifetime": 300, "after_read_tokens": 25000}))
        out = json.loads(r.stdout)  # 標準入力の値が勝ち、spent もその値で数える（m2 の 20002 は 30002 を下回り、m3 だけが 1000 余分）
        self.assertAlmostEqual(out["rent"], 1000 * read)
        self.assertAlmostEqual(out["compact_cost"] + out["rent"], out["buy"])

    def test_after_tokens_from_stdin_is_checked(self):
        path = sample(self.tmp.name)
        for key in ("after_write_tokens", "after_read_tokens"):
            for bad in (None, "5", -1, True):
                r = self.run_cli("compact", "--transcript", str(path), stdin=json.dumps({"lifetime": 300, key: bad}))
                self.assertEqual((r.returncode, json.loads(r.stdout)["error"]), (2, "invalid_input"), (key, bad))
        r = self.run_cli("compact", "--transcript", str(path), stdin=json.dumps({"lifetime": 300, "post_tokens": 5}))
        self.assertEqual(r.returncode, 2)  # 前の版の post_tokens は知らない鍵

    def test_override_is_validated_and_tiers_follow_base(self):
        for bad in ({"input_cost_per_token_above_100k_tokens": "x"}, {"output_cost_per_token_above_100k_tokens": float("inf")},
                    {"input_cost_per_token_above_100k_tokens": -1}):
            with self.assertRaises(prices.PricesError, msg=bad) as cm:
                prices.lookup("claude-haiku-5-5", {"claude-haiku-5-5": bad}, env=self.env)
            self.assertEqual((cm.exception.key, cm.exception.code), ("invalid_input", 2))
        base = prices.lookup("claude-haiku-5-5", env=self.env)
        self.assertIn("input_cost_per_token_above_100k_tokens", base.entry)
        tier = base.entry["input_cost_per_token_above_100k_tokens"]
        raised = {"input_cost_per_token": tier * 2, "cache_creation_input_token_cost": tier * 4,
                  "cache_creation_input_token_cost_above_1hr": tier * 4}  # 順序を保ったまま基を段の上へ
        got = prices.lookup("claude-haiku-5-5", {"claude-haiku-5-5": raised}, env=self.env)
        self.assertNotIn("input_cost_per_token_above_100k_tokens", got.entry)

    def test_latest_with_non_object_top_level_is_unusable(self):
        (pathlib.Path(self.tmp.name) / "latest.json").write_text("[1, 2]", encoding="utf-8")
        got = prices.lookup("claude-opus-5-5", env=self.env)
        self.assertEqual(got.source, "snapshot")

    def test_snapshot_write_failure_exits_1(self):
        # 書き込みを失敗させるため、取得を差し替えた台本を同じ口から呼ぶ（ネットワークには出ない）
        code = ("import runpy, sys, json\nfrom unittest import mock\nfrom prompt_cache import prices\n"
                "snap = {'models': {}, 'commit': 'c', 'fetched': 'd'}\n"
                "import pathlib\n"
                "with mock.patch.object(prices, 'fetch_snapshot', return_value=snap), "
                "mock.patch.object(pathlib.Path, 'write_text', side_effect=OSError('read-only')):\n"
                "    sys.argv = ['rent-or-buy', 'snapshot']\n"
                "    runpy.run_path(%r, run_name='__main__')\n" % str(PLUGIN / "bin" / "rent-or-buy"))
        r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, encoding="utf-8",
                           env=self.env, cwd=str(PLUGIN))
        self.assertEqual((r.returncode, json.loads(r.stdout)["error"]), (1, "write_failed"), r.stdout + r.stderr)


if __name__ == "__main__":
    unittest.main()
