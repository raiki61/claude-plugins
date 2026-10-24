"""モデル名の揃え（設計書 3.3）。実物の名前と、実物と確かめていない名前を分けて試す。"""
import json
import pathlib
import sys
import unittest

PLUGIN = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PLUGIN))
from prompt_cache import names, prices  # noqa: E402

KNOWN = set(json.loads((PLUGIN / "prompt_cache" / "snapshot.json").read_text(encoding="utf-8"))["models"])


class NamesTest(unittest.TestCase):
    def test_real_names(self):
        # 2026-10-24 に確かめた実物: 会話の記録の名前と、LiteLLM の値段表のクラウド経由の項目名
        for raw, want in [("claude-opus-5-5", "claude-opus-5-5"),
                          ("us.anthropic.claude-opus-5-5", "claude-opus-5-5"),
                          ("global.anthropic.claude-sonnet-5-5", "claude-sonnet-5-5"),
                          ("anthropic.claude-haiku-5-5", "claude-haiku-5-5"),
                          ("eu.anthropic.claude-fable-5-1", "claude-fable-5-1")]:
            self.assertEqual(names.normalize(raw), want)
            self.assertEqual(names.resolve(raw, KNOWN), want)

    def test_unverified_names(self):
        # 揃え方の規則の試し。これらの名前が実際に記録に出るかは確かめていない（見本が集まったら実物に替える）
        for raw, want in [("claude-opus-5-5[1m]", "claude-opus-5-5"),
                          ("claude-opus-5-5@20261001", "claude-opus-5-5"),
                          ("anthropic.claude-opus-5-5-v1:0", "claude-opus-5-5"),
                          ("Claude-Opus-5.5", "claude-opus-5-5"),
                          ("anthropic.claude-opus-5-5-20261001-v1:0", "claude-opus-5-5")]:
            self.assertEqual(names.normalize(raw), want)

    def test_no_fuzzy_match_and_aliases(self):
        self.assertIsNone(names.resolve("claude-opus-9", KNOWN))
        self.assertIsNone(names.resolve("opus", KNOWN))  # 名前を含む項目を拾わない
        self.assertEqual(names.resolve("proxy-big", KNOWN, {"proxy-big": "claude-opus-5-5"}), "claude-opus-5-5")
        self.assertEqual(names.parse_aliases("a=claude-opus-5-5, b=claude-sonnet-5-5"),
                         {"a": "claude-opus-5-5", "b": "claude-sonnet-5-5"})
        self.assertEqual(names.parse_aliases('{"a": "x"}'), {"a": "x"})
        with self.assertRaises(ValueError):
            names.parse_aliases("no-equals")

    def test_snapshot_is_valid(self):
        snap = json.loads((PLUGIN / "prompt_cache" / "snapshot.json").read_text(encoding="utf-8"))
        self.assertTrue(snap["commit"] and snap["fetched"] and snap["source"].startswith("https://"))
        self.assertTrue(all(k.startswith("claude-") and "/" not in k and prices.usable(v) for k, v in snap["models"].items()))
        opus = snap["models"]["claude-opus-5-5"]
        self.assertEqual([opus[prices.FIELDS[k]] for k in ("input", "write_5m", "write_1h", "read", "output")],
                         [4e-6, 5e-6, 8e-6, 2e-7, 2e-5])


if __name__ == "__main__":
    unittest.main()
