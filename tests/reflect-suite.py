#!/usr/bin/env python3
"""attention/scripts/reflect.py（/reflect の機械の側）を固定する。本物の会話の記録・GitHub・VS Code には触らない。

固定するのは: 期間の読み方、人の会話と裏の会話の見分け（コマンドの行・貼り付けの囲み）、トークンを返答ごとに
1 回だけ数えること、裏の会話を起こした元ごとにまとめること、繰り返しの数え方、読む設定のフォルダの決め方、
commit を会話の作業フォルダから引くこと（git subrepo の ref を数えない）、GitHub の動きの絞り方、/insights の
控えと持ち物の拾い方、欄の検査、提案の並べ方と台帳（却下は落とす・状態は --decide だけが変える）、日記の節の
置き換え（手で書いた行に触らない）、配布物に持ち主の環境の値を書かないこと。
"""

import datetime as dt
import importlib.util
import json
import os
import pathlib
import re
import subprocess
import sys
import tempfile
import unittest

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

ROOT = pathlib.Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "attention" / "scripts"
sys.path.insert(0, str(SCRIPTS / "lib"))


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


rf = load("reflect", SCRIPTS / "reflect.py")

DAY = dt.date(2026, 10, 15)


def at(hour, minute=0, day=DAY):
    """手元の時刻帯のその時刻を、記録と同じ UTC の Z 形式で。"""
    t = dt.datetime.combine(day, dt.time(hour, minute)).astimezone()
    return t.astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def user(text, when, source="typed", **kw):
    return {"type": "user", "timestamp": when, "promptSource": source, "cwd": kw.pop("cwd", "/w"),
            "message": {"role": "user", "content": text}, **kw}


def reply(mid, out, when, model="m-big", tools=()):
    content = [{"type": "tool_use", "name": n, "input": i} for n, i in tools] or [{"type": "text", "text": "ok"}]
    return {"type": "assistant", "timestamp": when, "cwd": "/w",
            "message": {"id": mid, "model": model, "usage": {"output_tokens": out}, "content": content}}


def write_jsonl(path, entries):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(e, ensure_ascii=False) for e in entries) + "\n", encoding="utf-8")


def fields(**kw):
    base = {
        "headline": "レビューの日",
        "proposals": [
            {"id": "small-one", "kind": "automate", "title": "小", "evidence": "2 回", "count": 2, "minutes": 1,
             "where": "x", "existing": "", "action": "y"},
            {"id": "big-one", "kind": "stop", "title": "大", "evidence": "10 回", "count": 10, "minutes": 5,
             "where": "x", "action": "y"},
            {"id": "unknown-one", "kind": "fix", "title": "不明", "evidence": "?", "count": None, "minutes": None,
             "where": "x", "action": "y"},
        ],
        "insights": [{"title": "t", "body": "b", "evidence": "e"}],
        "unseen": [],
    }
    base.update(kw)
    return base


class Period(unittest.TestCase):
    def test_words_and_dates(self):
        self.assertEqual(rf.period("today", DAY), (DAY, DAY))
        self.assertEqual(rf.period("yesterday", DAY), (DAY - dt.timedelta(1), DAY - dt.timedelta(1)))
        self.assertEqual(rf.period("week", DAY), (DAY - dt.timedelta(6), DAY))
        self.assertEqual(rf.period(None, DAY), (DAY - dt.timedelta(6), DAY))
        self.assertEqual(rf.period("month", DAY), (DAY - dt.timedelta(29), DAY))
        self.assertEqual(rf.period("2026-10-01", DAY), (dt.date(2026, 10, 1),) * 2)
        self.assertEqual(rf.period("2026-10-01..2026-10-03", DAY), (dt.date(2026, 10, 1), dt.date(2026, 10, 3)))

    def test_bad_words_stop(self):
        for bad in ("lastweek", "2026-10-03..2026-10-01", "10/15"):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                rf.period(bad, DAY)

    def test_bounds_are_local_midnights(self):
        start, end = rf.bounds(DAY, DAY)
        self.assertEqual((start.hour, end - start), (0, dt.timedelta(days=1)))


class Sessions(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.cfg = pathlib.Path(self.tmp.name) / "cfg"
        proj = self.cfg / "projects" / "p"
        write_jsonl(proj / "human.jsonl", [
            user("前の日の話", at(10, day=DAY - dt.timedelta(1))),
            user("どうぞ", at(9)),
            # コマンドの行には promptSource が付かない（実測）。コマンドの形で人の発言として拾う
            user("<command-message>attention:catchup</command-message>\n<command-name>/attention:catchup</command-name>\n"
                 "<command-args>1933</command-args>", at(9, 5), source=None),
            user('<pasted_content id="a">貼った本文</pasted_content> を見て', at(9, 10)),
            {"type": "user", "timestamp": at(9, 11), "isMeta": True, "message": {"content": "仕組みの差し込み"}},
            {"type": "user", "timestamp": at(9, 12), "message": {"content": [{"type": "tool_result", "content": "x"}]}},
            # 1 つの返答（同じ id）が 2 行に分かれ、行ごとに同じ使用量を持つ
            reply("r1", 100, at(9, 13), tools=[("Bash", {"command": "git commit -m x && git push"})]),
            reply("r1", 100, at(9, 13), tools=[("Read", {"file_path": "a"})]),
            reply("r2", 50, at(9, 14)),
            user("どうぞ", at(10)),
        ])
        for name, out in (("bg1", 10), ("bg2", 30), ("bg3", 20)):
            write_jsonl(proj / f"{name}.jsonl", [
                user("あなたはこの文章について何も知らない初見の読者です。会話の経緯もリポジトリも見ていません。本文: " + name, at(11), source="sdk", cwd="/gate"),
                reply(f"{name}-r", out, at(11, 1), model="m-small"),
            ])
        write_jsonl(proj / "old.jsonl", [user("昔の話", at(9, day=DAY - dt.timedelta(3)))])
        start, end = rf.bounds(DAY, DAY)
        self.human, self.background = rf.sessions([self.cfg], start, end)

    def tearDown(self):
        self.tmp.cleanup()

    def test_human_and_background_are_split(self):
        self.assertEqual([s["id"] for s in self.human], ["human"])
        self.assertEqual(sorted(s["id"] for s in self.background), ["bg1", "bg2", "bg3"])

    def test_asks_keep_commands_and_drop_paste_marks_and_meta(self):
        asks = self.human[0]["asks"]
        self.assertEqual(asks, ["どうぞ", "/attention:catchup 1933", "貼った本文 を見て", "どうぞ"])

    def test_tokens_count_each_reply_once(self):
        row = rf.human_rows(self.human)[0]
        self.assertEqual(row["output_tokens"], 150)
        self.assertEqual(sum(row["output_by_model"].values()), 150)
        self.assertEqual(row["marks"], {"commit": 1, "push": 1})
        self.assertEqual(row["tools"], {"Bash": 1, "Read": 1})

    def test_tokens_are_kept_apart_by_model(self):
        s = {"out": {"a": 10, "b": 20, "c": 5}, "models": {"a": "m-big", "b": "m-small"}}
        self.assertEqual(rf.tokens_by_model([s, s]), {"m-small": 40, "m-big": 20, "?": 10})

    def test_background_is_grouped_by_origin(self):
        rows = rf.background_rows(self.background)
        self.assertEqual(len(rows), 1)
        r = rows[0]
        self.assertEqual((r["runs"], r["output_tokens"], r["median_output_tokens"], r["max_output_tokens"]), (3, 60, 20, 30))
        self.assertEqual(r["models"], {"m-small": 60})
        self.assertEqual(r["cwd"], "/gate")

    def test_repeats_count_asks_and_commands_apart(self):
        asks, cmds = rf.repeats(self.human)
        self.assertEqual(cmds, {"/attention:catchup": 1})
        self.assertEqual([(a["text"], a["count"]) for a in asks], [("どうぞ", 2)])

    def test_long_periods_keep_fewer_asks(self):
        s = {**self.human[0], "asks": [f"発言 {i}" for i in range(30)]}
        self.assertEqual(len(rf.human_rows([s], days=1)[0]["asks"]), 2 * rf.ASKS_KEEP)
        self.assertLess(len(rf.human_rows([s], days=7)[0]["asks"]), 2 * rf.ASKS_KEEP)
        self.assertEqual(rf.human_rows([s], days=7)[0]["asks_total"], 30)


class ConfigDirs(unittest.TestCase):
    def test_current_then_added_without_duplicates_or_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            a, b = pathlib.Path(tmp) / "a", pathlib.Path(tmp) / "b"
            a.mkdir(), b.mkdir()
            env = {"CLAUDE_CONFIG_DIR": str(a), rf.DIRS_ENV: os.pathsep.join([str(b), str(a), str(pathlib.Path(tmp) / "none")])}
            self.assertEqual(rf.config_dirs(env), [a, b])

    def test_default_is_home_dot_claude(self):
        with tempfile.TemporaryDirectory() as tmp:
            (pathlib.Path(tmp) / ".claude").mkdir()
            self.assertEqual(rf.config_dirs({"HOME": tmp}), [pathlib.Path(tmp) / ".claude"])


def git(cwd, *args, env=None):
    subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True,
                   env={**os.environ, "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1", **(env or {})})


class Commits(unittest.TestCase):
    def test_commits_come_from_session_folders_and_skip_other_refs(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = pathlib.Path(tmp) / "repo"
            repo.mkdir()
            git(repo, "init", "-q", "-b", "main")
            git(repo, "config", "user.email", "me@example.com")
            git(repo, "config", "user.name", "me")
            when = dt.datetime.combine(DAY, dt.time(12)).astimezone().isoformat()
            stamp = {"GIT_AUTHOR_DATE": when, "GIT_COMMITTER_DATE": when}
            git(repo, "commit", "-q", "--allow-empty", "-m", "mine", env=stamp)
            git(repo, "commit", "-q", "--allow-empty", "-m", "theirs", "--author", "x <x@example.com>", env=stamp)
            # 取り込んだ先の履歴を抱える別の ref（git subrepo の形）。同じ author でも数えない
            git(repo, "checkout", "-q", "--orphan", "other")
            git(repo, "commit", "-q", "--allow-empty", "-m", "subrepo side", env=stamp)
            git(repo, "update-ref", "refs/subrepo/x/fetch", "HEAD")
            git(repo, "checkout", "-q", "main")
            git(repo, "branch", "-q", "-D", "other")
            start, end = rf.bounds(DAY, DAY)
            out = rf.commits([str(repo), str(repo / "missing")], start, end)
            self.assertEqual(len(out), 1)
            self.assertEqual([c["subject"] for c in out[0]["commits"]], ["mine"])


class GitHub(unittest.TestCase):
    def test_events_are_filtered_to_the_period_per_login(self):
        status = json.dumps({"hosts": {"github.com": [
            {"login": "a", "state": "success"}, {"login": "b", "state": "failure"}, {"login": "a", "state": "success"}]}})
        inside, before = at(12), at(12, day=DAY - dt.timedelta(1))
        events = [
            {"type": "PullRequestEvent", "created_at": inside, "repo": {"name": "o/r"},
             "payload": {"action": "opened", "pull_request": {"number": 7, "title": "t"}}},
            {"type": "PushEvent", "created_at": before, "repo": {"name": "o/r"}, "payload": {}},
        ]
        calls = []

        def fake(args, cwd=None, env=None):
            calls.append(args)
            if args[:3] == ["gh", "auth", "status"]:
                return status
            if args[:3] == ["gh", "auth", "token"]:
                return "tok"
            return json.dumps(events)

        orig = rf.run
        rf.run = fake
        try:
            start, end = rf.bounds(DAY, DAY)
            out = rf.github(start, end)
        finally:
            rf.run = orig
        self.assertEqual([g["login"] for g in out], ["a"])
        self.assertEqual(out[0]["count"], 1)
        self.assertEqual(out[0]["events"][0]["number"], 7)
        self.assertEqual(out[0]["kinds"], {"PullRequest": 1})
        self.assertFalse(out[0]["truncated"])


class Privacy(unittest.TestCase):
    """非公開のリポジトリの名前・番号は、AI の文に書かせない。公開のリポジトリは書いてよい。"""

    def material(self):
        gh = [{"events": [
            {"repo": "corp/secret-app", "number": 1971, "private": True},
            {"repo": "me/open-tool", "number": 42, "private": False},
        ]}]
        rows = [{"repo": "corp/secret-app", "commits": [{"subject": "fix: x (#1665)"}]},
                {"repo": "corp/unknown", "commits": [{"subject": "feat: y (#7)"}]},
                {"repo": "me/open-tool", "commits": [{"subject": "z (#43)"}]}]
        asked = []
        priv = rf.privacy(rows, gh, ask=lambda label: asked.append(label) or True)
        return rows, priv, asked

    def test_flags_from_events_first_and_unknown_is_private(self):
        rows, priv, asked = self.material()
        self.assertEqual(asked, ["corp/unknown"])  # 動きの記録に印の無いものだけ問い合わせる
        self.assertEqual(priv["repos"], ["corp/secret-app", "corp/unknown"])
        self.assertEqual(priv["numbers"], [7, 1665, 1971])
        self.assertEqual([r["private"] for r in rows], [True, True, False])

    def test_leaks_are_caught_and_public_refs_pass(self):
        _, priv, _ = self.material()
        data = {"private": priv}
        ok = fields(headline="me/open-tool の #42 と PR 43 を直した。レビュー 14 件")
        self.assertEqual(rf.leaks(ok, data), [])
        for bad in ("#1971 をレビュー", "PR 1665 を直した", "secret-app の検索を直した", "corp/secret-app で"):
            with self.subTest(bad=bad):
                self.assertTrue(rf.leaks(fields(diary=bad), data))

    def test_render_stops_on_a_leak(self):
        with tempfile.TemporaryDirectory() as tmp:
            d, f = pathlib.Path(tmp) / "d.json", pathlib.Path(tmp) / "f.json"
            d.write_text(json.dumps({"schema": rf.SCHEMA, "period": {"start": "2026-10-15", "end": "2026-10-15"},
                                     "private": {"repos": ["corp/secret-app"], "numbers": [1971]}}), encoding="utf-8")
            f.write_text(json.dumps(fields(headline="#1971 のレビュー")), encoding="utf-8")
            code, lines = rf.render(d, f, env={"XDG_STATE_HOME": tmp, "ATTENTION_CATCHUP_OPEN": "0"}, root=pathlib.Path(tmp) / "out")
            self.assertEqual(code, 2)
            self.assertTrue(any("#1971" in line for line in lines))
            self.assertFalse((pathlib.Path(tmp) / "out").exists())


class InsightsAndAssets(unittest.TestCase):
    def test_facets_of_the_period_and_plugin_commands(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = pathlib.Path(tmp) / "cfg"
            (cfg / "usage-data" / "facets").mkdir(parents=True)
            (cfg / "usage-data" / "facets" / "s1.json").write_text(json.dumps({"session_id": "s1", "brief_summary": "要約", "outcome": "ok"}), encoding="utf-8")
            (cfg / "usage-data" / "facets" / "s2.json").write_text("{壊れた", encoding="utf-8")
            (cfg / "usage-data" / "report.html").write_text("<html>", encoding="utf-8")
            plug = pathlib.Path(tmp) / "plug"
            (plug / "commands").mkdir(parents=True)
            (plug / "commands" / "go.md").write_text("---\ndescription: 行く命令\n---\n本文", encoding="utf-8")
            (plug / "skills" / "s").mkdir(parents=True)
            (plug / "skills" / "s" / "SKILL.md").write_text("---\nname: s\ndescription: 技\n---\n", encoding="utf-8")
            (cfg / "plugins").mkdir()
            (cfg / "plugins" / "installed_plugins.json").write_text(json.dumps(
                {"plugins": {"p@m": [{"version": "1.0.0", "installPath": str(plug)}]}}), encoding="utf-8")
            (cfg / "CLAUDE.md").write_text("x", encoding="utf-8")
            ins = rf.insights([cfg], {"s1", "s2", "s3"})
            self.assertEqual([f["brief_summary"] for f in ins["facets"]], ["要約"])
            self.assertEqual(len(ins["reports"]), 1)
            a = rf.assets([cfg], [])
            self.assertEqual(a["plugins"][0]["commands"], [{"name": "go", "about": "行く命令"}])
            self.assertEqual(a["plugins"][0]["skills"], [{"name": "s", "about": "技"}])
            self.assertEqual(len(a["instructions"]), 1)


class Fields(unittest.TestCase):
    def test_good_fields_pass(self):
        self.assertEqual(rf.validate_fields(fields()), [])

    def test_bad_fields_are_listed(self):
        bad = fields(proposals=[{"id": "X", "kind": "maybe", "title": "", "evidence": "e", "where": "w",
                                 "action": "a", "count": -1, "extra": 1}], insights="x", surprise=1)
        errs = rf.validate_fields(bad)
        for want in ("知らない key: surprise", "proposals[0].id", "proposals[0].kind", "proposals[0].title",
                     "proposals[0].count", "proposals[0] の知らない key", "insights は"):
            with self.subTest(want=want):
                self.assertTrue(any(want in e for e in errs), errs)

    def test_rank_puts_bigger_cost_first_and_unknown_last(self):
        self.assertEqual([p["id"] for p in rf.rank(fields()["proposals"])], ["big-one", "small-one", "unknown-one"])


class LedgerAndRender(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = pathlib.Path(self.tmp.name)
        self.env = {"XDG_STATE_HOME": str(self.dir / "state"), "ATTENTION_CATCHUP_OPEN": "0"}
        self.data = {"schema": rf.SCHEMA, "period": {"spec": "today", "start": "2026-10-15", "end": "2026-10-15", "days": 1},
                     "counts": {}, "unseen": []}

    def tearDown(self):
        self.tmp.cleanup()

    def render(self, flds, data=None, env=None):
        d, f = self.dir / "d.json", self.dir / "f.json"
        d.write_text(json.dumps(data or self.data, ensure_ascii=False), encoding="utf-8")
        f.write_text(json.dumps(flds, ensure_ascii=False), encoding="utf-8")
        return rf.render(d, f, env={**self.env, **(env or {})}, root=self.dir / "out", today=DAY)

    def test_page_ledger_and_dismissed_proposals(self):
        code, lines = self.render(fields(headline="</script><b>"))
        self.assertEqual(code, 0)
        page = (self.dir / "out" / "2026-10-15_2026-10-15.html").read_text(encoding="utf-8")
        self.assertNotIn(rf.DATA_SLOT, page)
        self.assertNotIn("</script><b>", page)  # 欄の文字で script を閉じない
        led = rf.ledger_path(self.env)
        self.assertEqual({p["id"]: p["status"] for p in rf.read_ledger(led)["proposals"]},
                         {"small-one": "open", "big-one": "open", "unknown-one": "open"})
        rf.decide(led, "big-one", "dismissed", "要らない", today=DAY)
        with self.assertRaises(ValueError):
            rf.decide(led, "nothing", "dismissed")
        with self.assertRaises(ValueError):
            rf.decide(led, "big-one", "maybe")
        code, lines = self.render(fields())
        self.assertIn("却下済みなので落とした提案: big-one", lines)
        payload = json.loads(re.search(r'id="data">(.*?)</script>', (self.dir / "out" / "2026-10-15_2026-10-15.html").read_text(encoding="utf-8"), re.S).group(1))
        self.assertEqual([p["id"] for p in payload["fields"]["proposals"]], ["small-one", "unknown-one"])
        self.assertEqual(rf.read_ledger(led)["proposals"][1]["status"], "dismissed")  # render は状態を変えない

    def test_bad_fields_and_old_materials_stop_before_writing(self):
        code, lines = self.render({"headline": ""})
        self.assertEqual(code, 2)
        code, lines = self.render(fields(), data={"schema": 0})
        self.assertEqual(code, 2)
        self.assertFalse((self.dir / "out").exists())
        self.assertFalse(rf.ledger_path(self.env).exists())

    def test_a_broken_ledger_stops_instead_of_being_overwritten(self):
        led = rf.ledger_path(self.env)
        led.parent.mkdir(parents=True)
        led.write_text("{壊れた", encoding="utf-8")
        code, lines = self.render(fields())
        self.assertEqual(code, 2)
        self.assertIn("台帳", lines[0])
        self.assertEqual(led.read_text(encoding="utf-8"), "{壊れた")  # 却下の記録を空で上書きしない
        self.assertFalse((self.dir / "out").exists())
        with self.assertRaises(ValueError):
            rf.decide(led, "big-one", "dismissed")

    def test_diary_section_is_replaced_and_hand_lines_kept(self):
        diary = self.dir / "diary"
        diary.mkdir()
        (diary / "2026-10-15.md").write_text("# 2026-10-15\n\n手で書いた行\n", encoding="utf-8")
        env = {rf.DIARY_ENV: str(diary)}
        self.render(fields(diary="一回目"), env=env)
        self.render(fields(diary="二回目"), env=env)
        text = (diary / "2026-10-15.md").read_text(encoding="utf-8")
        self.assertIn("手で書いた行", text)
        self.assertEqual(text.count(rf.DIARY_START), 1)
        self.assertIn("二回目", text)
        self.assertNotIn("一回目", text)

    def test_diary_is_written_only_for_one_day(self):
        diary = self.dir / "diary"
        diary.mkdir()
        week = {**self.data, "period": {"spec": "week", "start": "2026-10-09", "end": "2026-10-15", "days": 7}}
        code, lines = self.render(fields(diary="週"), data=week, env={rf.DIARY_ENV: str(diary)})
        self.assertEqual(list(diary.iterdir()), [])
        self.assertTrue(any("1 日の期間のときだけ" in line for line in lines))


class NoOwnerValues(unittest.TestCase):
    """配布物に持ち主の環境の値（置き場・アカウント・鍵の名前）を書かない。"""
    BANNED = re.compile(r"/Users/|\.claude-p\d|claude-code-oauth-|my_notes|raiki61|190578_")

    def test_reflect_files_have_no_owner_values(self):
        for p in (SCRIPTS / "reflect.py", ROOT / "attention" / "templates" / "reflect.html",
                  ROOT / "attention" / "commands" / "reflect.md", ROOT / "attention" / "docs" / "reflect-spec.md"):
            with self.subTest(file=p.name):
                hits = [i for i, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1) if self.BANNED.search(line)]
                self.assertEqual(hits, [], f"{p.name} の {hits} 行目")


if __name__ == "__main__":
    unittest.main(verbosity=1)
