"""accounts ノード: 使用率の控えから、選べるアカウントとその順を決める（設計書のセクション 2 の 3）。"""

import io
import json
import pathlib
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout

from . import DISPATCH  # noqa: F401
from . import schemacheck
import claudex
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


def hours(n):
    return n * 3600


def window(used, resets_at):
    return {"used_percentage": used, "resets_at": resets_at}


class Rank(unittest.TestCase):
    def test_without_a_near_weekly_reset_lower_peak_comes_first(self):
        # どれも週の切り替わりが 24 時間より先なので、5 時間と週の高い方の低い順（p1 38・p3 79・main 86・p2 86）。同じなら設定の順
        self.assertEqual(names(accounts.rank(ACCTS, limits(), 95, NOW)), ["p1", "p3", "main", "p2"])

    def test_owner_case_of_2026_10_16_does_not_pile_on_the_slightly_earlier_reset(self):
        # p2 は週の切り替わりが十数時間早いだけで、5 時間の枠が 74%。main（5 時間 2%・週 1%）を先に使う
        lim = {"main": {"seven_day": window(1, NOW + 7 * hours(24)), "five_hour": window(2, NOW + hours(3))},
               "p2": {"seven_day": window(35, NOW + 6 * hours(24)), "five_hour": window(74, NOW + hours(1))}}
        got = accounts.rank(ACCTS[0:1] + ACCTS[2:3], lim, 95, NOW)
        self.assertEqual(names(got), ["main", "p2"])
        self.assertEqual(by(got, "p2")["peak"], 74)

    def test_a_stale_snapshot_is_treated_as_unknown_and_goes_last(self):
        # 取り直しが何時間も止まった控えは、使い切っていても低く見える。古い値で選ばない
        lim = limits()
        lim["p1"]["five_hour"]["updated_at"] = NOW - hours(4)
        got = accounts.rank(ACCTS, lim, 95, NOW)
        self.assertEqual(names(got)[-1], "p1")
        self.assertTrue(by(got, "p1")["stale"])
        self.assertFalse(by(got, "p1")["known"])
        self.assertFalse(by(got, "p1")["stale_over"])   # 最後の値は上限の下（--move --if-limited は移さない）
        lim["p1"]["five_hour"]["used_percentage"] = 99
        self.assertTrue(by(accounts.rank(ACCTS, lim, 95, NOW), "p1")["stale_over"])

    def test_peak_is_the_higher_of_five_hour_and_weekly(self):
        lim = limits()
        lim["p1"]["five_hour"]["used_percentage"] = 80   # 週 38 でも 5 時間 80 なら高い方は 80
        got = accounts.rank(ACCTS, lim, 95, NOW)
        self.assertEqual(by(got, "p1")["peak"], 80)
        self.assertEqual(names(got), ["p3", "p1", "main", "p2"])

    def test_peak_uses_the_known_window_when_the_other_is_missing(self):
        lim = limits()
        lim["p1"]["five_hour"] = None
        self.assertEqual(by(accounts.rank(ACCTS, lim, 95, NOW), "p1")["peak"], 38)

    def test_weekly_reset_within_the_window_goes_first_even_with_a_higher_peak(self):
        lim = limits()
        lim["p2"]["seven_day"]["resets_at"] = NOW + hours(20)
        got = accounts.rank(ACCTS, lim, 95, NOW)
        self.assertEqual(names(got)[0], "p2")
        self.assertTrue(by(got, "p2")["soon"])
        self.assertFalse(by(got, "p1")["soon"])

    def test_exactly_the_window_counts_as_near_and_one_second_more_does_not(self):
        lim = limits()
        lim["p2"]["seven_day"]["resets_at"] = NOW + hours(24)
        self.assertEqual(names(accounts.rank(ACCTS, lim, 95, NOW))[0], "p2")
        lim["p2"]["seven_day"]["resets_at"] = NOW + hours(24) + 1
        self.assertEqual(names(accounts.rank(ACCTS, lim, 95, NOW))[0], "p1")

    def test_near_resets_are_nearest_first(self):
        lim = limits()
        lim["p3"]["seven_day"]["resets_at"] = NOW + hours(10)
        lim["main"]["seven_day"]["resets_at"] = NOW + hours(5)
        self.assertEqual(names(accounts.rank(ACCTS, lim, 95, NOW))[:3], ["main", "p3", "p1"])

    def test_near_reset_at_the_limit_is_not_used(self):
        # 切り替わりが近くても、上限ちょうど（95）に届いていれば選ばない
        lim = limits()
        lim["p2"]["seven_day"] = window(95, NOW + hours(2))
        got = accounts.rank(ACCTS, lim, 95, NOW)
        self.assertFalse(by(got, "p2")["eligible"])
        self.assertEqual(names(got)[0], "p1")

    def test_near_reset_with_five_hour_at_the_limit_is_not_used(self):
        lim = limits()
        lim["p2"]["seven_day"]["resets_at"] = NOW + hours(2)
        lim["p2"]["five_hour"]["used_percentage"] = 95
        self.assertFalse(by(accounts.rank(ACCTS, lim, 95, NOW), "p2")["eligible"])

    def test_the_window_comes_from_the_argument(self):
        lim = limits()   # main と p2 の週の切り替わりは 43 時間 20 分後
        self.assertEqual(names(accounts.rank(ACCTS, lim, 95, NOW, soon_hours=44))[:2], ["main", "p2"])
        self.assertEqual(names(accounts.rank(ACCTS, lim, 95, NOW, soon_hours=0))[0], "p1")

    def test_fewer_running_conversations_win_a_tie(self):
        # main と p2 は高い方が同じ 86。動いている会話の少ない p2 が先
        got = accounts.rank(ACCTS, limits(), 95, NOW, {"main": 3, "p2": 1})
        self.assertEqual(names(got)[2:], ["p2", "main"])
        self.assertEqual(by(got, "main")["running"], 3)
        self.assertEqual(by(got, "p1")["running"], 0)

    def test_same_running_count_falls_back_to_config_order(self):
        got = accounts.rank(ACCTS, limits(), 95, NOW, {"main": 2, "p2": 2})
        self.assertEqual(names(got)[2:], ["main", "p2"])

    def test_running_breaks_a_tie_between_near_resets(self):
        lim = limits()
        lim["main"]["seven_day"]["resets_at"] = lim["p2"]["seven_day"]["resets_at"] = NOW + hours(3)
        self.assertEqual(names(accounts.rank(ACCTS, lim, 95, NOW, {"main": 1}))[:2], ["p2", "main"])

    def test_running_does_not_beat_a_lower_peak(self):
        self.assertEqual(names(accounts.rank(ACCTS, limits(), 95, NOW, {"p1": 9}))[0], "p1")

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

    def test_reaching_limit_is_excluded(self):
        # 使用率は 1% 刻みの整数で届くので、95 は 95.0〜95.9% のどれか。上限に届いた物は外す
        lim = limits()
        lim["main"]["seven_day"]["used_percentage"] = 95
        row = by(accounts.rank(ACCTS, lim, 95, NOW), "main")
        self.assertFalse(row["eligible"])
        self.assertIn("seven_day が 95% で上限 95% に達した", row["reason"])

    def test_just_below_limit_is_eligible(self):
        lim = limits()
        lim["main"]["seven_day"]["used_percentage"] = 94
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

    def test_account_without_usage_window_is_eligible_after_measured_ones(self):
        # 使用率の枠の無いアカウント（Ollama・Foundry など）は控えを読まない。古い控えが残っていても使用率で外さない
        accts = ACCTS[:2] + (Account("local", "claude-ollama", None, None, False), Account("p9", "c9"))
        lim = limits()
        lim["local"] = {"seven_day": {"used_percentage": 99, "resets_at": NOW + 60}, "five_hour": None}
        got = accounts.rank(accts, lim, 95, NOW)
        self.assertEqual(names(got), ["p1", "main", "local", "p9"])
        self.assertTrue(by(got, "local")["eligible"])
        self.assertIsNone(by(got, "local")["seven_day"]["used"])

    def test_missing_limits_go_last_even_with_no_running_conversation(self):
        lim = limits()
        lim["p1"] = None
        self.assertEqual(names(accounts.rank(ACCTS, lim, 95, NOW, {"p3": 5, "main": 5, "p2": 5}))[-1], "p1")

    def test_output_matches_schema(self):
        out = {"schema": 1, "accounts": accounts.rank(ACCTS, limits(), 95, NOW, {"main": 1}), "notes": []}
        self.assertEqual(schemacheck.check(out, schemacheck.schema("accounts")), [])


class Running(unittest.TestCase):
    def test_background_by_state_and_interactive_by_status(self):
        # 2026-10-16 に手元の 2.1.x で見た形: 背景の会話は state（status も付くことがある）、対話の会話は status だけ
        items = [
            {"kind": "background", "state": "working", "status": "busy"},
            {"kind": "background", "state": "blocked"},
            {"kind": "background", "state": "idle", "status": "busy"},
            {"kind": "interactive", "status": "busy"},
            {"kind": "interactive", "status": "idle"},
            {"kind": "interactive"},
        ]
        self.assertEqual([accounts.is_running(i) for i in items], [True, True, False, True, False, False])
        self.assertEqual(accounts.count_running({"a": items, "b": []}), {"a": 3, "b": 0})

    def test_unreadable_account_counts_as_zero_with_a_note(self):
        def list_sessions(cdir):
            if cdir == "bad":
                raise claudex.ClaudeError("claude agents --json（bad）: 読めない")
            if cdir == "gone":
                raise FileNotFoundError("claude")
            return [{"status": "busy"}]
        accts = (Account("a", "ca", "ok"), Account("b", "cb", "bad"), Account("c", "cc", "gone"))
        counts, notes = accounts.gather_running(accts, list_sessions)
        self.assertEqual(counts, {"a": 1, "b": 0, "c": 0})
        self.assertEqual(len(notes), 2)
        self.assertIn("アカウント b の動いている会話を数えられない", notes[0])
        self.assertIn("0 件とみなした", notes[0])


class FakePorts:
    def __init__(self, lim, listed, now=NOW):
        self.lim, self.listed, self._now, self.probed = lim, listed, now, []

    def now(self):
        return self._now

    def refresh_limits(self, cfg, names, force=True):
        self.probed.append((tuple(names), force))

    def read_limits(self, limits_dir, names):
        return {n: self.lim.get(n) for n in names}

    def list_sessions(self, config_dir):
        got = self.listed[config_dir]
        if isinstance(got, Exception):
            raise got
        return got


class Pick(unittest.TestCase):
    def setUp(self):
        d = pathlib.Path(tempfile.mkdtemp())
        (d / "second.md").write_text("二手目", encoding="utf-8")
        (d / "c.toml").write_text(f"""
limits_dir = '{(d / "limits").as_posix()}'
accounts = [
  {{ name = "main", command = "claude" }},
  {{ name = "p1", command = "c1", config_dir = "d1" }},
  {{ name = "p2", command = "c2", config_dir = "d2" }},
  {{ name = "p3", command = "c3", config_dir = "d3" }},
]
[[repos]]
repo = "o/r"
second_prompt_file = '{(d / "second.md").as_posix()}'
source = "s"
""", encoding="utf-8")
        self.cfg = str(d / "c.toml")

    def run_main(self, args, ports):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = accounts.main(["--config", self.cfg, *args], env={}, ports=ports)
        return code, out.getvalue(), err.getvalue()

    def test_human_line_names_the_account_its_command_and_why(self):
        ports = FakePorts(limits(), {None: [], "d1": [{"status": "busy"}], "d2": [], "d3": []})
        code, out, err = self.run_main(["--pick"], ports)
        self.assertEqual(code, 0)
        self.assertEqual(out.count("\n"), 1)
        self.assertTrue(out.startswith("p1: c1 — "))
        self.assertIn("5 時間 1%・週 38%", out)
        self.assertIn("動いている会話 1 件", out)
        self.assertEqual(err, "")
        # 古い控えだけ取り直す（dispatch の始める前の取り直しと違い、新しい控えには問い合わせない）
        self.assertEqual(ports.probed, [(("main", "p1", "p2", "p3"), False)])

    def test_near_weekly_reset_is_explained(self):
        lim = limits()
        lim["p3"]["seven_day"]["resets_at"] = NOW + hours(5) + 30 * 60
        _, out, _ = self.run_main(["--pick", "--no-probe"], FakePorts(lim, {None: [], "d1": [], "d2": [], "d3": []}))
        self.assertTrue(out.startswith("p3: c3 — 週の枠が 5 時間 30 分後に切り替わる（24 時間以内"))

    def test_json_has_the_pick_every_row_and_notes(self):
        ports = FakePorts(limits(), {None: [], "d1": [], "d2": claudex.ClaudeError("x"), "d3": []})
        code, out, _ = self.run_main(["--pick", "--json", "--no-probe"], ports)
        got = json.loads(out)
        self.assertEqual(code, 0)
        self.assertEqual(ports.probed, [])
        self.assertEqual({k: got["pick"][k] for k in ("name", "command", "config_dir")},
                         {"name": "p1", "command": "c1", "config_dir": "d1"})
        self.assertEqual(names(got["accounts"]), ["p1", "p3", "main", "p2"])
        self.assertEqual(len(got["notes"]), 1)
        self.assertEqual(schemacheck.check(got, schemacheck.schema("accounts")), [])

    def test_unreadable_count_is_noted_on_stderr(self):
        ports = FakePorts(limits(), {None: [], "d1": OSError("no claude"), "d2": [], "d3": []})
        code, out, err = self.run_main(["--pick", "--no-probe"], ports)
        self.assertEqual(code, 0)
        self.assertIn("注記: アカウント p1 の動いている会話を数えられない", err)

    def test_nothing_eligible_exits_1_with_the_reasons(self):
        lim = {n: {"seven_day": window(99, NOW + hours(1)), "five_hour": window(1, NOW + hours(1))} for n in ("main", "p1", "p2", "p3")}
        ports = FakePorts(lim, {None: [], "d1": [], "d2": [], "d3": []})
        code, out, err = self.run_main(["--pick", "--no-probe"], ports)
        self.assertEqual((code, out), (1, ""))
        self.assertIn("選べるアカウントが無い", err)
        self.assertIn("p1（seven_day が 99% で上限 95% に達した）", err)
        code, out, _ = self.run_main(["--pick", "--json", "--no-probe"], ports)
        self.assertEqual(code, 1)
        self.assertIsNone(json.loads(out)["pick"])

    def test_without_pick_every_row_is_listed_and_nothing_is_probed(self):
        ports = FakePorts(limits(), {None: [{"state": "working"}], "d1": [], "d2": [], "d3": []})
        code, out, _ = self.run_main([], ports)
        got = json.loads(out)
        self.assertEqual(code, 0)
        self.assertEqual(ports.probed, [])
        self.assertEqual(by(got["accounts"], "main")["running"], 1)
        self.assertNotIn("pick", got)


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
