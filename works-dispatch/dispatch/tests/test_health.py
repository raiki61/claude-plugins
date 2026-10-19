"""壊れても誰にも知らせが来ない所を、--tree と --todo の注記にする所（health.py）と、その元の片付け（clean.prune_kept）・
版に依らない入口（limits_entry.py）・待ち受けの印の処理の番号の使い回し（wake.alive と claudex.start_times）。
標準は docs/standards/breakage-detection.md。"""

import json
import os
import pathlib
import subprocess
import sys
import tempfile
import unittest

from . import DISPATCH
import claudex
import health
import limits_entry
from nodes import clean, wake

NOW = 1_800_000_000


def touch(path, text="", at=None):
    path = pathlib.Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    if at is not None:
        os.utime(path, (at, at))
    return path


class Background(unittest.TestCase):
    def setUp(self):
        self.inbox = pathlib.Path(tempfile.mkdtemp())

    def job(self, kind, at, done, out="出力"):
        log = touch(self.inbox / kind / f"co-{int(at)}.log", out, at)
        if done is not None:
            touch(log.with_suffix(".done"), done, at)
        return log

    def test_failed_and_unfinished_jobs_are_shown_and_fine_ones_are_not(self):
        self.job("takes", NOW - 60, "2\n", "Traceback 壊れた")
        self.job("moves", NOW - 60, "0\n")
        self.job("retires", NOW - 60, f"{wake.NOT_NOW}\n")
        self.job("moves", NOW - (health.UNFINISHED_MIN * 60 + 1), "")   # 途中で止められた
        self.job("moves", NOW - 60, "")   # 走っている
        self.job("moves", NOW - 60, None)   # 終わりが分からない
        notes = health.background(str(self.inbox), NOW)
        self.assertEqual(len(notes), 2, notes)
        self.assertIn("終わりの値 2", notes[0] + notes[1])
        self.assertIn("Traceback 壊れた", notes[0] + notes[1])
        self.assertIn("書いていない", notes[0] + notes[1])

    def test_old_output_is_removed(self):
        old = self.job("takes", NOW - (health.KEEP_DAYS * 86400 + 1), "2\n")
        self.assertEqual(health.background(str(self.inbox), NOW), [])
        self.assertFalse(old.exists())
        self.assertFalse(old.with_suffix(".done").exists())


class Queue(unittest.TestCase):
    def setUp(self):
        self.inbox = pathlib.Path(tempfile.mkdtemp())

    def test_old_waiting_asks_are_one_line_per_place_and_empty_folders_go(self):
        d = self.inbox / wake.QUEUE_DIR / "k1"
        for i, age in enumerate((health.QUEUE_STALE_MIN * 60 + 120, 60)):
            touch(d / f"{i}.json", json.dumps({"to": "co/調べ", "id": f"20261019-00000{i}-aaaaa{i}"}), NOW - age)
        touch(self.inbox / wake.QUEUE_DIR / ".DS_Store")
        empty = self.inbox / wake.QUEUE_DIR / "k2"
        empty.mkdir()
        os.utime(empty, (NOW - health.EMPTY_DAYS * 86400 - 1,) * 2)
        notes = health.stale_queue(str(self.inbox), NOW)
        self.assertEqual(len(notes), 1, notes)
        self.assertIn("co/調べ の順番待ちに 2 件", notes[0])
        self.assertIn("aaaaa0", notes[0])
        self.assertFalse(empty.exists())

    def test_fresh_queue_is_quiet(self):
        touch(self.inbox / wake.QUEUE_DIR / "k1" / "0.json", json.dumps({"to": "co/調べ", "id": "x"}), NOW - 60)
        self.assertEqual(health.stale_queue(str(self.inbox), NOW), [])


class Growth(unittest.TestCase):
    def test_large_ledgers_and_unreadable_lines_are_shown(self):
        inbox = pathlib.Path(tempfile.mkdtemp())
        touch(inbox / wake.LOG, '{"kind": "ask"}\n' + "切れた行\n")
        notes = health.growth(str(inbox))
        self.assertEqual(len(notes), 1, notes)
        self.assertIn("読めない行が 1 行", notes[0])
        with open(inbox / "due.log", "wb") as f:
            f.truncate(health.LEDGER_LIMIT + 1)
        self.assertTrue(any("due.log" in n for n in health.growth(str(inbox))))


class KeptTmp(unittest.TestCase):
    def setUp(self):
        self.kept = pathlib.Path(tempfile.mkdtemp())

    def copy(self, name, age, size=10):
        d = self.kept / name
        touch(d / "f", "x" * size)
        os.utime(d, (NOW - age,) * 2)
        return d

    def test_old_copies_are_pruned_and_ones_left_behind_are_shown(self):
        old = self.copy("old", clean.KEPT_DAYS * 86400 + 1)
        new = self.copy("new", 60)
        self.assertEqual(len(health.kept_tmp(str(self.kept), NOW)), 1)
        self.assertEqual(clean.prune_kept(str(self.kept), NOW), 1)
        self.assertFalse(old.exists())
        self.assertTrue(new.exists())
        self.assertEqual(health.kept_tmp(str(self.kept), NOW), [])

    def test_over_the_size_limit_the_oldest_go_first_but_kept_ones_stay(self):
        first, second, third = (self.copy(n, age) for n, age in (("a", 300), ("b", 200), ("c", 100)))
        limit = clean.KEPT_LIMIT
        clean.KEPT_LIMIT = 25   # 3 つで 30。古い 1 つを消せば収まる
        try:
            clean.prune_kept(str(self.kept), NOW, keep=(str(third),))
        finally:
            clean.KEPT_LIMIT = limit
        self.assertEqual([p.exists() for p in (first, second, third)], [False, True, True])


class Due(unittest.TestCase):
    def test_last_and_next_start_are_added_and_late_ones_are_shown(self):
        skills = [{"name": "点検", "start": {"every": "1d"}}, {"name": "週", "start": {"every": "7d"}},
                  {"name": "新しい", "start": {"every": "1d"}}, {"name": "手", "start": None}]
        records = [{"kind": "start", "skill": "点検", "status": "sent", "at": NOW - 86400 - health.DUE_LATE_MIN * 60 - 1},
                   {"kind": "start", "skill": "週", "status": "sent", "at": NOW - 86400}]
        notes = health.due(skills, records, NOW)
        self.assertEqual(len(notes), 2, notes)
        self.assertIn("点検", notes[0])
        self.assertIn("新しい の周期（1d ごと）が一度も起動した記録が無い", notes[1])
        self.assertEqual(skills[1]["next_start"], NOW - 86400 + 7 * 86400)
        self.assertIsNone(skills[2]["last_started"])
        self.assertIsNone(skills[2]["next_start"])
        self.assertNotIn("next_start", skills[3])


class Entry(unittest.TestCase):
    """タブバーが呼ぶ入口は、今入っている版の limits.py を探す。前の版（.orphaned_at）は飛ばす。"""

    def setUp(self):
        self.home = pathlib.Path(tempfile.mkdtemp())
        self.cfg = self.home / ".claude-a"
        cache = self.cfg / "plugins" / "cache" / "m" / "works-dispatch"
        self.old, self.new = cache / "0.1.3", cache / "0.2.0"
        for v in (self.old, self.new):
            touch(v / "dispatch" / "limits.py", "import sys; print('動いた', sys.argv[1:])")
        touch(self.old / limits_entry.ORPHANED, "1")
        self.snapshot = touch(self.home / "accounts.json", json.dumps({"accounts": [{"name": "a", "config_dir": str(self.cfg)}]}))

    def installed(self, *roots):
        touch(self.cfg / "plugins" / "installed_plugins.json", json.dumps({"version": 2, "plugins": {
            "works-dispatch@m": [{"scope": s, "installPath": str(r)} for s, r in roots]}}))

    def test_the_installed_version_without_orphaned_mark_is_picked(self):
        self.installed(("project", self.old), ("user", self.new))
        self.assertEqual(limits_entry.target(str(self.snapshot)), str(self.new / "dispatch" / "limits.py"))
        self.installed(("user", self.old))
        self.assertIsNone(limits_entry.target(str(self.snapshot)))   # 前の版しか無い

    def test_it_runs_the_found_script_with_the_same_arguments(self):
        self.installed(("user", self.new))
        p = subprocess.run([sys.executable, str(DISPATCH / "limits_entry.py"), "--accounts", str(self.snapshot), "show", "a"],
                           capture_output=True, text=True, encoding="utf-8", env={**os.environ, "PYTHONIOENCODING": "utf-8"})
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn("動いた", p.stdout)
        self.assertIn("show", p.stdout)

    def test_nothing_installed_says_so_on_the_tab_bar(self):
        p = subprocess.run([sys.executable, str(DISPATCH / "limits_entry.py"), "--accounts", str(self.snapshot), "show", "a"],
                           capture_output=True, text=True, encoding="utf-8")
        self.assertEqual((p.returncode, p.stdout.strip()), (1, "works-dispatch ?"))
        self.assertIn("見つからない", p.stderr)


class Reused(unittest.TestCase):
    """待ち受けの印の会話の処理の番号を、終わった後に別の処理が使い回すと、os.kill だけでは生きて見える。"""

    def test_a_process_born_after_the_mark_is_not_the_conversation(self):
        mark = {"owner": os.getpid(), "since": NOW}
        self.assertTrue(wake.alive(mark, posix=True, starts={os.getpid(): NOW - 100}))
        self.assertFalse(wake.alive(mark, posix=True, starts={os.getpid(): NOW + wake.SLACK + 1}))
        self.assertTrue(wake.alive({"owner": os.getpid(), "since": 0}, posix=True, starts={os.getpid(): NOW}))   # 前の版の印

    @unittest.skipIf(os.name == "nt", "ps の無い Windows では start_times は ps を読まずに空を返す")
    def test_start_times_read_ps_elapsed(self):
        out = "  1 10-02:03:04\n 42 05:06\n bad\n"
        got = claudex.start_times(lambda argv: subprocess.CompletedProcess(argv, 0, out, ""), now=NOW)
        self.assertEqual(got, {1: NOW - (10 * 86400 + 2 * 3600 + 3 * 60 + 4), 42: NOW - 306})
        self.assertEqual(claudex.start_times(lambda argv: subprocess.CompletedProcess(argv, 1, "", "")), {})



class Agents(unittest.TestCase):
    """claude agents --json の形（claudex）。本物の見本で、知っている値だけが出ることと、知らない値を数えることを確かめる。"""

    def test_the_real_list_has_only_known_values(self):
        sample = json.loads((pathlib.Path(__file__).parent / "samples" / "claude-agents.json").read_text(encoding="utf-8"))
        self.assertEqual(claudex.unknown_values(sample), {})
        self.assertEqual({x.get("state") for x in sample} - set(claudex.KNOWN_STATE), set())

    def test_unknown_values_are_counted(self):
        listed = [{"status": "busy"}, {"status": "paused"}, {"status": "paused", "state": "queued"}]
        self.assertEqual(claudex.unknown_values(listed), {"status=paused": 2, "state=queued": 1})

    @unittest.skipIf(os.name == "nt", "見本は macOS のパス（Windows では abspath がドライブを足す）")
    def test_the_talk_folder_name_matches_what_claude_code_makes(self):
        # 2026-10-19 に 2.1.303 の projects/ に在った名前（. と _ も - になる）
        for cwd, name in (("/Users/p03623/.herdr/worktrees/claude-plugins/work-breakage-detection",
                           "-Users-p03623--herdr-worktrees-claude-plugins-work-breakage-detection"),
                          ("/Users/p03623/src/my_notes", "-Users-p03623-src-my-notes")):
            home = pathlib.Path(tempfile.mkdtemp())
            touch(home / "projects" / name / "a.jsonl", "{}\n", NOW)
            with self.subTest(cwd=cwd):
                self.assertEqual(claudex.newest_talk(str(home), cwd), ("a.jsonl", NOW))


if __name__ == "__main__":
    unittest.main()
