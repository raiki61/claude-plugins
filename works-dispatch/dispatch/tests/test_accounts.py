"""accounts ノード: 使用率の控えから、選べるアカウントとその順を決める（設計書 2 節の 3）。"""

import json
import pathlib
import tempfile
import unittest

from . import DISPATCH  # noqa: F401
from . import schemacheck
from config import Account
from nodes import accounts

NOW = 1791963000
ACCTS = (Account("main", "claude"), Account("p1", "c1"), Account("p2", "c2"), Account("p3", "c3"))


def limits():
    # 2026-10-14 の持ち主の控えの値
    return {
        "main": {"seven_day": {"used_percentage": 86, "resets_at": 1792119600},
                 "five_hour": {"used_percentage": 1, "resets_at": 1791979200}},
        "p1": {"seven_day": {"used_percentage": 38, "resets_at": 1792155600},
               "five_hour": {"used_percentage": 1, "resets_at": 1791979200}},
        "p2": {"seven_day": {"used_percentage": 86, "resets_at": 1792119600},
               "five_hour": {"used_percentage": 0, "resets_at": 1791979200}},
        "p3": {"seven_day": {"used_percentage": 79, "resets_at": 1792382400},
               "five_hour": {"used_percentage": 24, "resets_at": 1791968400}},
    }


def names(rows):
    return [r["name"] for r in rows]


def by(rows, name):
    return next(r for r in rows if r["name"] == name)


class Rank(unittest.TestCase):
    def test_order_is_nearest_weekly_reset_then_lower_use_then_config_order(self):
        self.assertEqual(names(accounts.rank(ACCTS, limits(), 95, NOW)), ["main", "p2", "p1", "p3"])

    def test_lower_weekly_use_wins_a_tie_on_reset(self):
        lim = limits()
        lim["p2"]["seven_day"]["used_percentage"] = 50
        self.assertEqual(names(accounts.rank(ACCTS, lim, 95, NOW))[:2], ["p2", "main"])

    def test_over_limit_weekly_is_excluded(self):
        lim = limits()
        lim["main"]["seven_day"]["used_percentage"] = 96
        got = accounts.rank(ACCTS, lim, 95, NOW)
        self.assertFalse(by(got, "main")["eligible"])
        self.assertIn("seven_day", by(got, "main")["reason"])
        self.assertEqual(names(got)[-1], "main")

    def test_over_limit_five_hour_is_excluded(self):
        lim = limits()
        lim["p2"]["five_hour"]["used_percentage"] = 96
        got = accounts.rank(ACCTS, lim, 95, NOW)
        self.assertFalse(by(got, "p2")["eligible"])
        self.assertIn("five_hour", by(got, "p2")["reason"])

    def test_exactly_limit_is_eligible(self):
        lim = limits()
        lim["main"]["seven_day"]["used_percentage"] = 95
        self.assertTrue(by(accounts.rank(ACCTS, lim, 95, NOW), "main")["eligible"])

    def test_past_reset_counts_as_zero(self):
        lim = limits()
        lim["p3"]["seven_day"] = {"used_percentage": 99, "resets_at": NOW - 10}
        row = by(accounts.rank(ACCTS, lim, 95, NOW), "p3")
        self.assertTrue(row["eligible"])
        self.assertEqual(row["seven_day"]["used"], 0)

    def test_missing_or_broken_limits_go_last_but_eligible(self):
        lim = limits()
        lim["p1"] = None
        got = accounts.rank(ACCTS, lim, 95, NOW)
        self.assertEqual(names(got)[-1], "p1")
        self.assertTrue(by(got, "p1")["eligible"])
        self.assertFalse(by(got, "p1")["known"])

    def test_output_matches_schema(self):
        out = {"schema": 1, "accounts": accounts.rank(ACCTS, limits(), 95, NOW)}
        self.assertEqual(schemacheck.check(out, schemacheck.schema("accounts")), [])


class ReadLimits(unittest.TestCase):
    def test_reads_files_and_marks_missing_or_broken_as_none(self):
        d = pathlib.Path(tempfile.mkdtemp())
        (d / "main.json").write_text(json.dumps(limits()["main"]), encoding="utf-8")
        (d / "p2.json").write_text("{broken", encoding="utf-8")
        (d / "p3.json").write_text(json.dumps({"seven_day": "x"}), encoding="utf-8")
        got = accounts.read_limits(str(d), ["main", "p1", "p2", "p3"])
        self.assertEqual(got["main"]["seven_day"]["used_percentage"], 86)
        self.assertIsNone(got["p1"])
        self.assertIsNone(got["p2"])
        self.assertIsNone(got["p3"])


if __name__ == "__main__":
    unittest.main()
