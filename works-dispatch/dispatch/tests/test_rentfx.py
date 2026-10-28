"""借りるか買うかの部品が効いたかの集計（rentfx.py の --rent-effect）と、会話の記録を出来事に読む claudex.talk_files・talk_events と、
部品の prices・records・outcome への口（rentx）。"""

import json
import os
import pathlib
import tempfile
import time
import unittest

from . import DISPATCH
import rentfx
import rentx
import wake_hook
from nodes import role, wake
from ports import chat

RATES = {"input": 4e-6, "write_5m": 5e-6, "write_1h": 8e-6, "read": 2e-7, "output": 2e-5}
T0 = 1793000000.0


def stamp(t):
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(t)) + ".000Z"


def req(t, rid, read=0, w1=0, w5=0, out=10, model="claude-opus-5-5", inp=1):
    return {"type": "assistant", "timestamp": stamp(t), "requestId": rid,
            "message": {"id": rid, "model": model, "content": [{"type": "text", "text": "x"}],
                        "usage": {"input_tokens": inp, "cache_read_input_tokens": read, "cache_creation_input_tokens": w1 + w5,
                                  "cache_creation": {"ephemeral_1h_input_tokens": w1, "ephemeral_5m_input_tokens": w5},
                                  "output_tokens": out}}}


def said(t, text):
    return {"type": "user", "timestamp": stamp(t), "message": {"content": text}}


def hook(t, text, event="Stop"):
    return said(t, f'<task-notification>\n<task-id>b1</task-id>\n<system-reminder>\n{event} hook blocking error from command '
                   f'"{event}": {text}\n</system-reminder>')


def compact(t, pre, post, trigger="manual"):
    return {"type": "system", "subtype": "compact_boundary", "timestamp": stamp(t),
            "compactMetadata": {"trigger": trigger, "preTokens": pre, "postTokens": post}}


def write(rows, path=None):
    path = path or os.path.join(tempfile.mkdtemp(), "s1.jsonl")
    pathlib.Path(path).write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
    return path


def prices():
    return rentfx.Prices(ask=lambda model: ({"rates": RATES}, None))


class Marks(unittest.TestCase):
    def test_the_marks_are_in_the_texts_the_wake_hook_sends(self):
        # 印は、待ち受けが今送る文に含まれる（文を替えたら印も替える。昔の記録も読めるよう、印は文の一部だけにする）
        for text in wake_hook.CONSULT_TEXTS:
            self.assertIn(rentfx.ASK_MARK, text)
        self.assertTrue(role.KEEPALIVE_TEXT.lstrip("（(").startswith(rentfx.PING_HEAD))
        self.assertNotIn(rentfx.ASK_MARK, role.KEEPALIVE_TEXT)
        source = (DISPATCH / "wake_hook.py").read_text(encoding="utf-8")
        for mark in (rentfx.JUDGED_MARK, rentfx.CUT_MARK):
            self.assertIn(mark, source)


class TalkEvents(unittest.TestCase):
    def test_it_reads_requests_turn_starts_and_compacts_of_the_main_talk(self):
        rows = [said(T0, "直して"),
                req(T0 + 1, "r1", read=100, w1=50, out=5),
                req(T0 + 2, "r1", read=100, w1=50, out=40),   # 同じ要求の続きの行は、最後の行の使用量を採る
                {"type": "user", "timestamp": stamp(T0 + 3), "message": {"content": [{"type": "tool_result", "content": "r"}]}},
                {**req(T0 + 4, "r9", read=9), "isSidechain": True},
                {**req(T0 + 4, "r8"), "message": {**req(T0, "r8")["message"], "model": "<synthetic>"}},
                hook(T0 + 10, role.KEEPALIVE_TEXT),
                said(T0 + 20, "<command-name>/clear</command-name>\n<command-message>clear</command-message>"),
                said(T0 + 21, "<local-command-stdout></local-command-stdout>"),
                said(T0 + 22, "Stop hook feedback:\n古い形の文"),
                said(T0 + 23, "あ" * 500 + "前に見た「Stop hook blocking error from command \"Stop\": x」を引く"),   # 人の文の引用
                compact(T0 + 30, 1000, 100, "auto"),
                {"type": "user", chat.COMPACT_SUMMARY: True, "timestamp": stamp(T0 + 31), "message": {"content": "要約"}}]
        got = chat.talk_events(write(rows))
        self.assertEqual([(e["type"], e.get("by"), e.get("event")) for e in got],
                         [("said", "person", None), ("request", None, None), ("said", "hook", "Stop"),
                          ("said", "command", None), ("said", "hook", "Stop"), ("said", "person", None), ("compact", None, None)])
        r = got[1]
        self.assertEqual((r["at"], r["read"], r["write_1h"], r["write_5m"], r["output"]), (T0 + 1, 100, 50, 0, 40))
        self.assertEqual((got[2]["text"], got[3]["text"], got[4]["text"]), (role.KEEPALIVE_TEXT, "/clear", "古い形の文"))
        self.assertEqual((got[6]["trigger"], got[6]["pre"], got[6]["post"]), ("auto", 1000, 100))
        # 印のどれも無い記録は読まない（集計で関わりの無い会話を飛ばす）
        self.assertIsNone(chat.talk_events(write(rows[:2]), ("keepalive",)))
        self.assertIsNone(chat.talk_events("/none/s.jsonl"))

    def test_talk_files_picks_the_biggest_copy_of_each_talk_and_skips_old_ones(self):
        home = tempfile.mkdtemp()
        for folder, size in ((".claude", 10), (".claude-p1", 30)):
            (pathlib.Path(home) / folder / "plugins").mkdir(parents=True)
            (pathlib.Path(home) / folder / "plugins" / chat.PLUGINS_FILE).write_text("{}")
            place = pathlib.Path(home) / folder / "projects" / "-w"
            place.mkdir(parents=True)
            (place / "s1.jsonl").write_text("x" * size)
        old = pathlib.Path(home) / ".claude" / "projects" / "-w" / "s0.jsonl"
        old.write_text("x")
        os.utime(old, (T0, T0))
        got = chat.talk_files(home, since=T0 + 1)
        self.assertEqual(got, {"s1": os.path.join(home, ".claude-p1", "projects", "-w", "s1.jsonl")})
        self.assertIn("s0", chat.talk_files(home))


class Keepalive(unittest.TestCase):
    def test_a_warmed_wait_past_the_lifetime_counts_the_rewrite_it_avoided(self):
        rows = [said(T0, "直して"), req(T0, "a", read=90000, w1=10000),
                hook(T0 + 3000, role.KEEPALIVE_TEXT), req(T0 + 3000, "p", read=100000, w1=50, out=3),
                said(T0 + 5000, "続き"), req(T0 + 5000, "b", read=100000, w1=100),
                # 温めずに寿命を超え、書き直した待ち（下の端に掛ける割合 1/1）
                said(T0 + 9000, "次"), req(T0 + 9000, "c", w1=100000)]
        got, _ = rentfx.measure(T0, T0 + 86400, prices=prices(), files={"s1": write(rows)})
        row = got["keepalive"]["rows"]["1〜12時間・keepalive"]
        self.assertEqual((row["waits"], row["sent"]), (1, 1))
        self.assertAlmostEqual(row["sent_cost"], 1 * 4e-6 + 50 * 8e-6 + 100000 * 2e-7 + 3 * 2e-5)
        self.assertAlmostEqual(row["avoided"], 100000 * (8e-6 - 2e-7))
        self.assertEqual(got["keepalive"]["expired_without_warming"], {"rewrote": 1, "waits": 1, "share": 1.0})
        self.assertAlmostEqual(row["avoided_low"], row["avoided"])

    def test_a_warmed_wait_that_still_rewrote_counts_as_paying_both(self):
        rows = [said(T0, "直して"), req(T0, "a", w5=10000),
                hook(T0 + 200, role.KEEPALIVE_TEXT), req(T0 + 200, "p", read=10000, w5=10),
                said(T0 + 900, "続き"), req(T0 + 900, "b", w5=10100)]
        got, _ = rentfx.measure(T0, T0 + 86400, prices=prices(), files={"s1": write(rows)})
        row = got["keepalive"]["rows"]["5分〜1時間・keepalive"]
        self.assertEqual((row["failed"], row["avoided"]), (1, 0))
        self.assertAlmostEqual(row["failed_sent_cost"], row["sent_cost"])
        self.assertEqual(got["keepalive"]["expired_without_warming"]["share"], None)

    def test_a_wait_cut_by_a_compact_is_not_compared_with_the_lifetime(self):
        """待ちの間に compact が在れば、次の要求は作り直した文脈を書くので、送ったのに書き直した（両方払った）とは数えない。"""
        rows = [said(T0, "直して"), req(T0, "a", w5=10000),
                hook(T0 + 200, role.KEEPALIVE_TEXT), req(T0 + 200, "p", read=10000, w5=10),
                said(T0 + 400, "<command-name>/compact</command-name>"), compact(T0 + 401, 10010, 2000),
                said(T0 + 900, "続き"), req(T0 + 900, "b", w5=2100)]
        got, _ = rentfx.measure(T0, T0 + 86400, prices=prices(), files={"s1": write(rows)})
        row = got["keepalive"]["rows"]["5分〜1時間・keepalive"]
        self.assertEqual((row["waits"], row["sent"], row["failed"], row["avoided"]), (1, 1, 0, 0))


class Compact(unittest.TestCase):
    def test_a_judged_compact_saves_reads_until_the_base_world_reaches_its_auto_line(self):
        rows = [said(T0, "直して"), req(T0, "a", read=150000, w1=1000),
                hook(T0 + 600, wake_hook.CONSULT_TEXT), req(T0 + 600, "q", read=151000, w1=20),
                said(T0 + 610, "<command-name>/compact</command-name>"), compact(T0 + 611, 151000, 10000),
                hook(T0 + 612, "（待ちの間に、" + rentfx.JUDGED_MARK + "。焦点: x）", "SessionStart:compact"),
                req(T0 + 613, "f", w1=12000),
                said(T0 + 700, "続き"), req(T0 + 700, "b", read=12000, w1=100)]
        got, _ = rentfx.measure(T0, T0 + 86400, prices=prices(), files={"s1": write(rows)})
        for name in ("low", "high"):
            c = got["compact"][name]
            self.assertEqual(c["count"], {"judged": 1, "cut": 0, "auto": 0})
            self.assertAlmostEqual(c["summary"], 151000 * 2e-7 + 10000 * 2e-5)
            # 縮めた後の最初の要求（入力の側）: 基準は前の文脈 151000 を読み、新しい 2001 を書く
            self.assertAlmostEqual(c["first"], (151000 * 2e-7 + 2001 * 8e-6) - (1 * 4e-6 + 12000 * 8e-6))
        # 自動の compact が記録に無いので、線の下の端は 20 万と最大の文脈の大きい方、上の端は既定の線。どちらも着かない
        self.assertAlmostEqual(got["compact"]["high"]["kept"], 141000 * 2e-7)
        self.assertEqual(got["compact"]["low"]["base_auto"], 0)
        self.assertEqual(got["asks"]["turns"], 1)

    def test_the_base_world_compacts_by_itself_at_its_auto_line_and_then_runs_smaller(self):
        rows = [said(T0, "直して"), req(T0, "a", read=160000, w1=1000),
                compact(T0 + 10, 161000, 10000),
                hook(T0 + 11, "（区切り〔--compact〕で会話を compact した。…）", "SessionStart:compact"),
                req(T0 + 12, "f", w1=12000),
                said(T0 + 20, "続き"), req(T0 + 20, "b", read=12000, w1=8000),   # 基準は 20000 + 151000 で線 168000 に着く
                said(T0 + 30, "続き"), req(T0 + 30, "c", read=20000, w1=100)]
        sess = rentfx.Session("s1", rentfx.turns(chat.talk_events(write(rows))), prices(), T0, T0 + 86400)
        out = rentfx._comp_blank()
        sess.compacts(out, 168000, 5000)
        # 区切りの compact は、基準の文脈 161000 が COMPACT_FLOOR 以上なので基準でも打つ（差に数えない）
        self.assertEqual((out["shared"], out["count"]["cut"], out["base_auto"]), (1, 0, 0))
        rows[3] = hook(T0 + 11, "（待ちの間に、" + rentfx.JUDGED_MARK + "。）", "SessionStart:compact")
        sess = rentfx.Session("s1", rentfx.turns(chat.talk_events(write(rows))), prices(), T0, T0 + 86400)
        out = rentfx._comp_blank()
        sess.compacts(out, 168000, 5000)
        self.assertEqual((out["count"]["judged"], out["base_auto"]), (1, 1))
        self.assertAlmostEqual(out["base_summary"], (20001 + 151000) * 2e-7 + 5000 * 2e-5)
        # 基準は縮めた後 5000 + 新しい 8001 を全部書く。その後は基準が 20001 − 13001 = 7000 小さい（実際が読みに払う）
        self.assertAlmostEqual(out["base_first"], 13001 * 8e-6 - (1 * 4e-6 + 8000 * 8e-6 + 12000 * 2e-7))
        self.assertAlmostEqual(out["kept"], -7000 * 2e-7)


class Outcomes(unittest.TestCase):
    def test_a_keyed_keepalive_decision_gets_what_it_paid_and_what_the_other_hand_would_have_cost(self):
        rows = [said(T0, "直して"), req(T0, "a", read=90000, w1=10000),
                hook(T0 + 3000, role.KEEPALIVE_TEXT), req(T0 + 3000, "p", read=100000, w1=50, out=3),
                said(T0 + 5000, "続き"), req(T0 + 5000, "b", read=100000, w1=100)]
        p = prices()
        _, sessions = rentfx.measure(T0, T0 + 86400, prices=p, files={"s1": write(rows)})
        records = [{"scene": "keepalive", "ts": rentfx._stamp(T0 + 2990), "input": {"key": "s1/0000abcd"}, "output": {"action": "rent"}},
                   {"scene": "keepalive", "ts": rentfx._stamp(T0 + 2990), "input": {}, "output": {"action": "rent"}},
                   {"scene": "decide", "ts": rentfx._stamp(T0), "input": {"key": "s1/x"}, "output": {}}]
        got, keyless = rentfx.outcomes(sessions, records, p)
        self.assertEqual(keyless, 1)
        self.assertEqual([g["key"] for g in got], ["s1/0000abcd"])
        self.assertAlmostEqual(got[0]["paid"], 1 * 4e-6 + 50 * 8e-6 + 100000 * 2e-7 + 3 * 2e-5)
        self.assertAlmostEqual(got[0]["alternative"], 100000 * (8e-6 - 2e-7))


class PartCommands(unittest.TestCase):
    def test_the_real_part_keeps_outcomes_once_and_reads_them_back(self):
        # リポジトリの隣の部品を本当に起動する。記録は一時のファイルに書かせる
        env = dict(os.environ, RENT_OR_BUY_RECORD=os.path.join(tempfile.mkdtemp(), "d.jsonl"))
        got, why = rentx.prices("claude-opus-5-5", env=env)
        self.assertIsNone(why)
        self.assertEqual(set(got["rates"]), set(RATES))
        item = {"key": "s1/0000abcd", "paid": 0.1, "alternative": None}
        self.assertEqual(rentx.outcome([item], env=env), ({"recorded": 1, "duplicates": 0}, None))
        self.assertEqual(rentx.outcome([item], env=env), ({"recorded": 0, "duplicates": 1}, None))
        rows, why = rentx.records(since="2000-01-01T00:00:00Z", env=env)
        self.assertEqual(([r["scene"] for r in rows], why), (["outcome"], None))
        got, why = rentx.outcome([{"key": "", "paid": 0}], env=env)
        self.assertIsNone(got)
        self.assertIn("終了コード 2", why)


class Command(unittest.TestCase):
    def test_since_and_until_go_only_with_rent_effect(self):
        import dispatch
        self.assertEqual(dispatch.main(["--since", "2026-10-24T00:00:00Z"]), 2)
        self.assertEqual(rentfx.main("あした", None), 2)


if __name__ == "__main__":
    unittest.main()
