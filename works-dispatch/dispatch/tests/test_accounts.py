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
import config
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
                raise claudex.Error("claude agents --json（bad）: 読めない")
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
        ports = FakePorts(limits(), {None: [], "d1": [], "d2": claudex.Error("x"), "d3": []})
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


class Hours(unittest.TestCase):
    """使える時間帯（設定の hours）。CheapestInference の Europe 枠（UTC 08:00〜16:00、日本時間 17:00〜翌 1:00）。受付 c66192。"""

    # 日本時間の 2026-10-19 20:23（枠の中）・10-20 00:40（終わりの 20 分前）・01:00（終わり）・09:00（枠の外）
    inside, closing, end, outside = 1792408980, 1792424400, 1792425600, 1792454400
    cheap = Account("cheap", "claude-cheapest", limits=False, hours=config.parse_hours("17:00-25:00 Asia/Tokyo"))

    def test_the_window_opens_and_closes_across_midnight(self):
        utc = config.parse_hours("08:00-16:00 UTC")
        for at in (self.inside, self.closing):
            self.assertEqual(accounts.opening(self.cheap.hours, at), {"open": True, "closes_at": self.end, "opens_at": None})
            self.assertEqual(accounts.opening(utc, at), accounts.opening(self.cheap.hours, at))   # 同じ枠を日本時間と UTC で書いた
        self.assertEqual(accounts.opening(self.cheap.hours, self.end), {"open": False, "closes_at": None, "opens_at": self.end + 16 * 3600})
        self.assertFalse(accounts.opening(utc, self.outside)["open"])
        self.assertIsNone(accounts.shut(config.parse_hours("00:00-24:00 UTC"), 1792454400 - 600, 30))   # 一日中は日の境目の手前でも選ぶ

    def test_rank_skips_the_account_outside_or_near_the_end_of_its_hours(self):
        accts = (Account("p1", "c1"), self.cheap)
        lim = {"p1": {"seven_day": {"used_percentage": 99, "resets_at": self.inside + 86400 * 3}, "five_hour": {"used_percentage": 1}}}
        rows = accounts.rank(accts, lim, 95, self.inside)
        self.assertEqual(names(rows), ["cheap", "p1"])   # 使用率の分からないアカウントでも、時間帯の中なら上限のアカウントより前
        self.assertTrue(by(rows, "cheap")["eligible"])
        self.assertEqual((by(rows, "cheap")["hours"], by(rows, "cheap")["shut"]), ("17:00-25:00 Asia/Tokyo", False))
        for at, word in ((self.closing, "20 分後に終わる"), (self.outside, "外（次は 17:00 Asia/Tokyo に始まる）")):
            row = by(accounts.rank(accts, lim, 95, at), "cheap")
            self.assertEqual((row["eligible"], row["shut"]), (False, True))
            self.assertIn(word, row["reason"])
        self.assertTrue(by(accounts.rank(accts, lim, 95, self.closing, margin_minutes=10), "cheap")["eligible"])
        self.assertEqual(schemacheck.check({"schema": 1, "accounts": rows}, schemacheck.schema("accounts")), [])

    def test_eligible_at_and_the_next_look_of_a_waiting_move(self):
        # --move --if-limited が移る先も無く待つとき、選べないアカウントがまた選べるようになる時刻まで待つ（受付 e33748）
        accts = (Account("p1", "c1"), self.cheap)
        week = self.inside + 86400 * 3
        lim = {"p1": {"seven_day": {"used_percentage": 99, "resets_at": week}, "five_hour": {"used_percentage": 1}}}
        opens = self.end + 16 * 3600   # 次の日の 17:00 Asia/Tokyo
        for at in (self.closing, self.outside):
            rows = accounts.rank(accts, lim, 95, at)
            self.assertEqual((by(rows, "p1")["eligible_at"], by(rows, "cheap")["eligible_at"]), (week, opens))
            self.assertEqual(accounts.next_look(rows, at, 600), opens)   # 早く空く方
        rows = accounts.rank(accts, lim, 95, self.inside)
        self.assertIsNone(by(rows, "cheap")["eligible_at"])   # 選べる
        self.assertEqual(accounts.next_look(rows, self.inside, 600), self.inside + 600)   # 選べるアカウントが在れば最短の間
        unknown = {"p1": {"seven_day": {"used_percentage": 99}, "five_hour": {"used_percentage": 1}}}
        rows = accounts.rank(accts, unknown, 95, self.outside)
        self.assertIsNone(by(rows, "p1")["eligible_at"])   # 切り替わりの時刻が分からない
        self.assertEqual(accounts.next_look(rows, self.outside, 600), opens)
        self.assertEqual(accounts.next_look(accounts.rank(accts[:1], unknown, 95, self.outside), self.outside, 600), self.outside + 600)
        self.assertEqual(schemacheck.check({"schema": 1, "accounts": rows}, schemacheck.schema("accounts")), [])

    def test_early_moves_off_the_account_before_its_hours_end(self):
        accts = (Account("p1", "c1"), self.cheap)
        lim = {"p1": {"seven_day": {"used_percentage": 50}, "five_hour": {"used_percentage": 1}}}
        self.assertIsNone(accounts.early(accounts.rank(accts, lim, 95, self.inside), "cheap", 90, 1, self.inside))
        got = accounts.early(accounts.rank(accts, lim, 95, self.closing), "cheap", 90, 1, self.closing)
        self.assertEqual((got["to"], got["kind"]), ("p1", "hours"))
        self.assertIn("20 分後に終わる", got["why"])
        full = {"p1": {"seven_day": {"used_percentage": 99}, "five_hour": {"used_percentage": 1}}}
        got = accounts.early(accounts.rank(accts, full, 95, self.closing), "cheap", 90, 1, self.closing)
        self.assertEqual((got["to"], got["kind"]), (None, "hours_none"))
        got = accounts.early(accounts.rank(accts, lim, 95, self.outside), "p1", 90, 1, self.outside, wish="cheap")
        self.assertEqual((got["to"], got["kind"]), (None, "bad"))   # 名指しの先が時間帯の外
        self.assertIn("使える時間帯の外", got["why"])
        got = accounts.early(accounts.rank(accts, lim, 95, self.closing), "cheap", 90, 1, self.closing, wish="p9")
        self.assertEqual((got["to"], got["kind"]), ("p1", "hours"))   # 名指しが使えなくても、終わる手前ならほかへ移す


class Prefer(unittest.TestCase):
    """会社の形の役か受け持ちが名指したアカウント（accounts.prefer）。my_notes の受付 20261020-084411-d23053 の、写しの後始末を
    cheapest の使える時間帯の中は cheapest で回す形。"""

    cheap = Hours.cheap
    accts = (Account("p1", "c1"), cheap)
    lim = {"p1": {"seven_day": {"used_percentage": 10, "resets_at": Hours.inside + 86400 * 3}, "five_hour": {"used_percentage": 1}}}

    def rows(self, at=Hours.inside):
        return accounts.rank(self.accts, self.lim, 95, at)

    def test_a_usable_wish_goes_first_even_without_limits(self):
        self.assertEqual(names(self.rows()), ["p1", "cheap"])   # 名指しが無ければ、控えの無い cheap は後
        got, note = accounts.prefer(self.rows(), "cheap", 0, "役 写しの後始末")
        self.assertEqual((names(got), note), (["cheap", "p1"], None))
        self.assertEqual(accounts.prefer(self.rows(), None, 0, None), (self.rows(), None))

    def test_an_unusable_wish_keeps_the_usage_order_and_says_why(self):
        for at, opened, why in ((Hours.outside, 0, "使える時間帯（17:00-25:00 Asia/Tokyo）の外"),
                                (Hours.closing, 0, "分後に終わる（終わりの 30 分前からは選ばない）"),
                                (Hours.inside, 1, "終わっていない会話が 1 件在り、設定の max_open（1）に達した")):
            got, note = accounts.prefer(self.rows(at), "cheap", opened, "役 写しの後始末")
            self.assertEqual(names(got)[0], "p1")
            self.assertIn("役 写しの後始末 が名指したアカウント cheap は", note)
            self.assertIn(why, note)
        got, note = accounts.prefer(self.rows(), "p9", 0, "受け持ち 写し")
        self.assertEqual(names(got), ["p1", "cheap"])
        self.assertIn("p9 は振れるアカウントの中に無い", note)

    def test_max_open_allows_that_many_open_conversations(self):
        got, note = accounts.prefer(self.rows(), "cheap", 2, "役 写しの後始末", max_open=3)
        self.assertEqual((names(got)[0], note), ("cheap", None))
        got, note = accounts.prefer(self.rows(), "cheap", 3, "役 写しの後始末", max_open=3)
        self.assertEqual(names(got)[0], "p1")
        self.assertIn("終わっていない会話が 3 件在り、設定の max_open（3）に達した", note)

    def test_an_account_over_its_limit_is_not_used_even_when_named(self):
        lim = {"p1": {"seven_day": {"used_percentage": 99, "resets_at": Hours.inside + 86400}, "five_hour": {"used_percentage": 1}}}
        got, note = accounts.prefer(accounts.rank(self.accts, lim, 95, Hours.inside), "p1", 0, "役 作業")
        self.assertEqual(names(got)[0], "cheap")
        self.assertIn("seven_day が 99% で上限 95% に達した", note)

    def test_open_conversations_count_idle_background_ones(self):
        items = [{"state": "idle"}, {"state": "done"}, {"state": "stopped"}, {"state": "failed"},
                 {"status": "idle"}, {"status": "busy"}, {"state": "working"}]
        self.assertEqual(accounts.count_open(items), 3)   # 待機中の裏の会話・動いている対話の会話・作業中の裏の会話
        self.assertEqual(accounts.count_open([]), 0)


class Early(unittest.TestCase):
    """区切りで早めに移すか（accounts.early）。受付 215886 の 2026-10-19 09:05 の控え（p3 は 5 時間 77%・週 98%、週の枠は 3 時間 56 分で戻る）。"""

    now = 1792368333

    def rows(self, **more):
        lim = {"main": {"five_hour": {"used_percentage": 7, "resets_at": 1792375200}, "seven_day": {"used_percentage": 81, "resets_at": 1792724400}},
               "p1": {"five_hour": {"used_percentage": 9, "resets_at": 1792384200}, "seven_day": {"used_percentage": 85, "resets_at": 1792760400}},
               "p2": {"five_hour": {"used_percentage": 0, "resets_at": 1792383600}, "seven_day": {"used_percentage": 98, "resets_at": 1792670400}},
               "p3": {"five_hour": {"used_percentage": 77, "resets_at": 1792373400}, "seven_day": {"used_percentage": 98, "resets_at": 1792382400}},
               **more}
        return accounts.rank(ACCTS, lim, 95, self.now)

    def test_the_hot_account_moves_to_the_head_of_the_order_below_the_mark(self):
        got = accounts.early(self.rows(), "p3", 90, 1, self.now)
        self.assertEqual(got["to"], "main")   # p2 は上限、main（81%）と p1（85%）のうち使用率の順の頭
        self.assertIn("週の枠 98%", got["why"])

    def test_no_move_under_the_mark_or_when_the_hot_window_resets_soon_or_without_a_roomy_account(self):
        self.assertIsNone(accounts.early(self.rows(), "p1", 90, 1, self.now))   # 目安に届かない
        self.assertIsNone(accounts.early(self.rows(), "p9", 90, 1, self.now))   # 控えの無いアカウント
        got = accounts.early(self.rows(), "p3", 90, 4, self.now)   # 週の枠は 3 時間 56 分で戻る
        self.assertIsNone(got["to"])
        self.assertIn("4 時間以内に戻る", got["why"])
        got = accounts.early(self.rows(), "p3", 80, 1, self.now)   # main 81%・p1 85% も目安に達する
        self.assertIsNone(got["to"])
        self.assertIn("ほかのアカウントが無い", got["why"])

    def test_the_named_account_is_taken_unless_it_is_over_its_limit(self):
        self.assertEqual(accounts.early(self.rows(), "p3", 90, 1, self.now, wish="p1")["to"], "p1")
        self.assertEqual(accounts.early(self.rows(), "main", 90, 1, self.now, wish="p1")["to"], "p1")   # 目安を待たない
        self.assertIsNone(accounts.early(self.rows(), "p3", 90, 1, self.now, wish="p2")["to"])   # 上限に達した
        self.assertIsNone(accounts.early(self.rows(), "p3", 90, 1, self.now, wish="p9")["to"])


class NamedOnly(unittest.TestCase):
    """名指しのときだけ使うアカウント（設定の named_only）。my_notes の受付 20261021-031828-b45260 の、NIM（弱いモデルへ読み替わる中継）を
    Anthropic の口が全部上限のときにも自動で選ばない形。"""

    nim = Account("nim", "claude-nim", limits=False, named_only=True)
    accts = (Account("p1", "c1"), Account("cheap", "claude-cheapest", limits=False), nim)

    def rows(self, used=10):
        lim = {"p1": {"seven_day": window(used, NOW + 86400 * 3), "five_hour": window(1, NOW + 3600)}}
        return accounts.rank(self.accts, lim, 95, NOW)

    def test_it_is_never_picked_automatically_even_when_every_other_account_is_over(self):
        got = self.rows()
        self.assertEqual(names(got), ["p1", "cheap", "nim"])
        self.assertEqual((by(got, "nim")["eligible"], by(got, "nim")["named_ok"]), (False, True))
        self.assertEqual(by(got, "nim")["reason"], accounts.NAMED_ONLY)
        self.assertIsNone(by(got, "nim")["eligible_at"])
        self.assertEqual((by(got, "cheap")["named_only"], by(got, "cheap")["named_ok"]), (False, False))
        # Anthropic の口（p1）が上限で、使用率の枠の無い cheap も無い: nim は選ばれない
        only = accounts.rank(self.accts[:1] + (self.nim,), {"p1": {"seven_day": window(99, NOW + 86400), "five_hour": window(1, NOW + 3600)}},
                             95, NOW)
        self.assertFalse(any(r["eligible"] for r in only))
        self.assertIsNone(accounts.early(only, "p1", 90, 1, NOW)["to"])
        self.assertEqual(accounts.next_look(only, NOW, 600), NOW + 86400)   # nim を待たず、p1 の週の枠の切り替わりまで待つ

    def test_naming_it_from_the_company_shape_or_move_uses_it(self):
        got, note = accounts.prefer(self.rows(), "nim", 0, "役 下書き")
        self.assertEqual((names(got)[0], got[0]["eligible"], note), ("nim", True, None))
        self.assertEqual(names(accounts.named(self.rows(), "nim"))[0], "nim")
        self.assertTrue(accounts.named(self.rows(), "nim")[0]["eligible"])
        self.assertEqual(accounts.named(self.rows(), "cheap")[0], by(self.rows(), "cheap"))   # ふつうのアカウントの行は替えない
        self.assertEqual(accounts.early(self.rows(), "p1", 90, 1, NOW, wish="nim")["to"], "nim")

    def test_named_but_closed_or_busy_it_is_still_not_used(self):
        shut = Account("nim", "claude-nim", limits=False, named_only=True, hours=config.parse_hours("08:00-09:00 UTC"))
        rows = accounts.rank(self.accts[:2] + (shut,), {}, 95, NOW)   # NOW は UTC 07:30
        self.assertFalse(by(rows, "nim")["named_ok"])
        self.assertIn("使える時間帯（08:00-09:00 UTC）の外", by(rows, "nim")["reason"])
        got, note = accounts.prefer(rows, "nim", 0, "役 下書き")
        self.assertNotEqual(names(got)[0], "nim")
        self.assertIn("使える時間帯（08:00-09:00 UTC）の外", note)
        got, note = accounts.prefer(self.rows(), "nim", 1, "役 下書き")
        self.assertEqual(names(got)[0], "p1")
        self.assertIn("終わっていない会話が 1 件在り", note)
        # strict（名指しのときだけ使うアカウントの名指し）なら、ほかのアカウントへ回さず空の並び
        got, note = accounts.prefer(self.rows(), "nim", 1, "役 下書き", strict=True)
        self.assertEqual(got, [])
        self.assertIn("ほかのアカウントでは立てない", note)
        got, note = accounts.prefer(rows, "nim", 0, "役 下書き", strict=True)
        self.assertEqual(got, [])
        self.assertIn("使える時間帯（08:00-09:00 UTC）の外", note)
        got, note = accounts.prefer(self.rows(), "nim", 1, "役 下書き", max_open=2, strict=True)
        self.assertEqual((names(got)[0], note), ("nim", None))
        self.assertIsNone(accounts.early(rows, "p1", 90, 1, NOW, wish="nim")["to"])

    def test_output_matches_schema(self):
        self.assertEqual(schemacheck.check({"schema": 1, "accounts": self.rows(), "notes": []}, schemacheck.schema("accounts")), [])


class Overview(unittest.TestCase):
    """--tree と --check に出すアカウントの一覧（accounts.overview）。読み替え先は settings.json の env から読む。"""

    def test_aliases_come_from_the_settings_of_each_account(self):
        with tempfile.TemporaryDirectory() as d:
            nim, plain = pathlib.Path(d, "nim"), pathlib.Path(d, "plain")
            nim.mkdir(), plain.mkdir()
            (nim / "settings.json").write_text(json.dumps({"env": {
                "ANTHROPIC_DEFAULT_OPUS_MODEL": "glm-5.3-flash", "ANTHROPIC_DEFAULT_SONNET_MODEL": "glm-5.3-flash",
                "ANTHROPIC_DEFAULT_HAIKU_MODEL": "nemotron-3.5-super-vl", "ANTHROPIC_BASE_URL": "http://127.0.0.1:4011"}}))
            (plain / "settings.json").write_text(json.dumps({"model": "opus"}))
            accts = (Account("p1", "c1", str(plain)), Account("nim", "claude-nim", str(nim), limits=False, named_only=True, max_open=3),
                     Account("gone", "c9", str(pathlib.Path(d, "gone"))))
            got = accounts.overview(accts, {"HOME": d})
            self.assertEqual([x["models"] for x in got],
                             [{"default": "opus"}, {"opus": "glm-5.3-flash", "sonnet": "glm-5.3-flash", "haiku": "nemotron-3.5-super-vl"}, {}])
            lines = accounts.overview_lines(got)
            self.assertEqual(lines[1:], ["  p1  自動  モデル 既定 → opus",
                                         "  nim  名指しだけ  名指しで同時 3 件まで  使用率の枠なし  モデル opus・sonnet → glm-5.3-flash、haiku → nemotron-3.5-super-vl",
                                         "  gone  自動"])
            self.assertEqual(schemacheck.check({"schema": 1, "companies": [], "accounts": got, "notes": []}, schemacheck.schema("tree")), [])

    def test_unreadable_settings_give_no_aliases(self):
        with tempfile.TemporaryDirectory() as d:
            pathlib.Path(d, "settings.json").write_text("{not json")
            self.assertEqual(claudex.model_aliases(d, {}), {})
            pathlib.Path(d, "settings.json").write_text(json.dumps({"env": {"ANTHROPIC_MODEL": "", "CLAUDE_CODE_SUBAGENT_MODEL": "x"}}))
            self.assertEqual(claudex.model_aliases(d, {}), {"subagent": "x"})
