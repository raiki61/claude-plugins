#!/usr/bin/env python3
"""attention/scripts/reflect.py（/reflect の機械の側）を固定する。本物の会話の記録・GitHub・VS Code には触らない。

固定するのは: 期間の読み方、人の会話と裏の会話の見分け（コマンドの行・貼り付けの囲み）、トークンを返答ごとに
1 回だけ数えること、裏の会話を起動した元ごとにまとめること、繰り返しの数え方、読む設定のフォルダの決め方、
commit を会話の作業フォルダから引くこと（git subrepo の ref を数えない）、GitHub の動きの絞り方、/insights の
控えと持ち物の拾い方、フィールドの検査、提案の並べ方と台帳（却下は落とす・状態は --decide だけが変える）、日記のセクションの
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
from unittest import mock

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

    def test_unreadable_gh_is_said_not_shown_as_empty(self):
        """gh が失敗したら、空の結果に見せずに unseen へ訳を書く（「読めなかった」と「何も無かった」を分ける）。"""
        status = json.dumps({"hosts": {"github.com": [{"login": "a", "state": "success"}]}})

        def fake(args, cwd=None, env=None):
            if args[:3] == ["gh", "auth", "status"]:
                return fake.status
            if args[:3] == ["gh", "auth", "token"]:
                return "tok"
            return None  # gh api が失敗

        orig = rf.run
        rf.run = fake
        try:
            start, end = rf.bounds(DAY, DAY)
            fake.status = status
            page_unseen = []
            out = rf.github(start, end, page_unseen)
            fake.status = None
            auth_unseen = []
            none = rf.github(start, end, auth_unseen)
        finally:
            rf.run = orig
        self.assertEqual(out[0]["count"], 0)
        self.assertTrue(any("a の 1 ページ目を読めなかった" in u for u in page_unseen), page_unseen)
        self.assertEqual(none, [])
        self.assertTrue(any("gh auth status が失敗した" in u for u in auth_unseen), auth_unseen)


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
            (plug / "commands" / "go.md").write_text("---\ndescription: 行くコマンド\n---\n本文", encoding="utf-8")
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
            self.assertEqual(a["plugins"][0]["commands"], [{"name": "go", "about": "行くコマンド"}])
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
        self.assertNotIn("</script><b>", page)  # フィールドの文字で script を閉じない
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



class Description(unittest.TestCase):
    """スキル・コマンドの説明を frontmatter から読む。無いときと読めないときを分けて出す"""

    def test_folded_value_is_joined(self):
        text = "---\nname: x\ndescription: >\n  一行目\n  二行目\n---\n本文\n"
        self.assertEqual(rf.frontmatter_description(text), "一行目 二行目")

    def test_bom_before_the_frontmatter_is_skipped(self):
        self.assertEqual(rf.frontmatter_description("\ufeff---\ndescription: 説明\n---\n"), "説明")

    def test_description_in_the_body_is_not_read(self):
        self.assertIsNone(rf.frontmatter_description("---\nname: x\n---\ndescription: 本文\n"))

    def test_missing_and_unreadable_are_told_apart(self):
        with tempfile.TemporaryDirectory() as d:
            p = pathlib.Path(d) / "SKILL.md"
            p.write_text("---\nname: x\n---\n", encoding="utf-8")
            self.assertIn("説明が無い", rf.first_line(p))
            self.assertIn("読めなかった", rf.first_line(pathlib.Path(d) / "none.md"))


FIXTURE = ROOT / "tests" / "fixtures" / "reflect-prompt-sources.jsonl"


def real_lines(**change):
    """実物の会話の記録から採った行（2026-10-19。id・文・作業フォルダだけ差し替えた）を、DAY の時刻にして返す。
    promptSource は typed・queued・suggestion_accepted（人）と sdk・system（人でない）の 5 つ、最後の行は返答"""
    rows = [json.loads(line) for line in FIXTURE.read_text(encoding="utf-8").splitlines() if line.strip()]
    for i, r in enumerate(rows):
        r["timestamp"] = at(9, i)
        for key, value in change.items():
            if key in r:
                if value is None:
                    del r[key]
                elif r["type"] == "user":
                    r[key] = value
    return rows


class PromptSources(unittest.TestCase):
    """人の発言の見分けは promptSource の値で決める。外の形（Claude Code が足した値・消した印）が変わったら知らせる"""

    def run_on(self, rows):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = pathlib.Path(tmp) / "cfg"
            write_jsonl(cfg / "projects" / "p" / "s.jsonl", rows)
            start, end = rf.bounds(DAY, DAY)
            human, background = rf.sessions([cfg], start, end)
            return human, background, rf.source_notes(human, background)

    def test_the_real_record_counts_three_human_asks_and_says_nothing(self):
        human, _, notes = self.run_on(real_lines())
        self.assertEqual(human[0]["asks"], ["typed の発言", "queued の発言", "suggestion_accepted の発言"])
        self.assertEqual(notes, [])

    def test_an_unknown_value_is_counted_apart_and_told(self):
        rows = real_lines()
        rows[2]["promptSource"] = "voice_input"
        human, _, notes = self.run_on(rows)
        self.assertEqual(human[0]["asks"], ["typed の発言", "queued の発言"])
        self.assertTrue(any("voice_input 1 件" in n for n in notes), notes)

    def test_a_record_without_any_prompt_source_is_told(self):
        _, background, notes = self.run_on(real_lines(promptSource=None))
        self.assertEqual(len(background), 1)
        self.assertTrue(any("1 つも無い" in n for n in notes), notes)

    def test_renamed_human_values_are_told_even_as_unknown(self):
        rows = real_lines()
        for r in rows[:3]:
            r["promptSource"] = "keyboard"
        _, _, notes = self.run_on(rows)
        self.assertTrue(any("keyboard 3 件" in n for n in notes), notes)
        self.assertTrue(any("人の発言が 0 件" in n for n in notes), notes)


class Coverage(unittest.TestCase):
    """見た範囲の欠け（消えた会話の記録・読んでいない設定のフォルダ）を、黙って飛ばさずに出す"""

    def test_records_newer_than_the_period_start_are_told(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = pathlib.Path(tmp) / "cfg"
            write_jsonl(cfg / "projects" / "p" / "s.jsonl", [user("x", at(9))])
            newest = dt.datetime.combine(DAY, dt.time(9)).astimezone().timestamp()
            os.utime(cfg / "projects" / "p" / "s.jsonl", (newest, newest))
            rows, notes = rf.records_from([cfg], rf.bounds(DAY - dt.timedelta(29), DAY)[0])
            self.assertEqual(rows[0]["from"][:10], DAY.isoformat())
            self.assertTrue(any(f"{DAY.isoformat()} 09:00 から" in n for n in notes), notes)
            _, none = rf.records_from([cfg], rf.bounds(DAY, DAY)[1])
            self.assertEqual(none, [])

    def test_unreadable_records_are_counted_not_dropped_silently(self):
        """開けない会話の記録は、黙ってふり返りから外さずに、フォルダごとの件数を 1 行出す。0 件なら出さない"""
        with tempfile.TemporaryDirectory() as tmp:
            cfg = pathlib.Path(tmp) / ".claude"
            write_jsonl(cfg / "projects" / "p" / "ok.jsonl", [user("どうぞ", at(9))])
            start, end = rf.bounds(DAY, DAY)
            notes = []
            rf.sessions([cfg], start, end, notes)
            self.assertEqual(notes, [])
            (cfg / "projects" / "p" / "broken.jsonl").mkdir()  # 開くと IsADirectoryError（OSError）
            human, _ = rf.sessions([cfg], start, end, notes)
            self.assertEqual(len(human), 1)
            self.assertEqual(len(notes), 1, notes)
            self.assertIn(cfg.name, notes[0])  # 一時の場所がホームの下なら ~ に縮むので、フォルダの名前だけを見る
            self.assertRegex(notes[0], r" 1 ")
            env = {"HOME": tmp, rf.DIRS_ENV: str(cfg)}
            data = rf.collect(DAY.isoformat(), env, with_github=False, today=DAY)
            self.assertIn(notes[0], data["coverage"]["notes"])  # ページの頭（見た範囲の欠け）に届く

    def test_missing_and_unread_config_dirs_are_told(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = pathlib.Path(tmp)
            for name in (".claude", ".claude-a", ".claude-b"):
                (home / name / "projects").mkdir(parents=True)
            (home / ".claude-empty").mkdir()  # 会話の記録を持たないフォルダは数えない
            env = {"HOME": tmp, rf.DIRS_ENV: os.pathsep.join([str(home / ".claude-a"), str(home / ".claude-gone")])}
            dirs = rf.config_dirs(env)
            notes = rf.dir_notes(env, dirs)
            self.assertEqual(dirs, [home / ".claude", home / ".claude-a"])
            self.assertTrue(any(".claude-gone" in n and "無い" in n for n in notes), notes)
            unread = [n for n in notes if "読んでいない" in n]
            self.assertEqual(len(unread), 1)
            self.assertIn(".claude-b", unread[0])
            self.assertNotIn(".claude-empty", unread[0])

    def test_config_dir_that_cannot_be_checked_is_told(self):
        """読んでいるかを確かめる途中で OSError になったフォルダは、黙って落とさずに注記に出す"""
        with tempfile.TemporaryDirectory() as tmp:
            home = pathlib.Path(tmp)
            for name in (".claude", ".claude-b"):
                (home / name / "projects").mkdir(parents=True)
            env = {"HOME": tmp}
            dirs = rf.config_dirs(env)
            real = pathlib.Path.resolve

            def resolve(self, *a, **k):
                if self.name == ".claude-b":
                    raise PermissionError(self)
                return real(self, *a, **k)

            with mock.patch.object(pathlib.Path, "resolve", resolve):
                notes = rf.dir_notes(env, dirs)
            self.assertEqual(len(notes), 1, notes)
            self.assertIn(".claude-b", notes[0])
            self.assertNotIn(rf.DIRS_ENV, notes[0])  # 「読んでいない」の注記（足し方の案内付き）でない


class GitHubSearch(unittest.TestCase):
    """events が期間の頭まで届かなければ、取れた時刻を出し、検索の API で期間の PR・issue を補う"""

    def fake(self, search_raw):
        status = json.dumps({"hosts": {"github.com": [{"login": "a", "state": "success"}]}})
        late = at(20)
        page = [{"type": "PushEvent", "created_at": late, "repo": {"name": "o/r"}, "payload": {}, "public": True}] * 100
        calls = []

        def fake(args, cwd=None, env=None):
            calls.append(args)
            if args[:3] == ["gh", "auth", "status"]:
                return status
            if args[:3] == ["gh", "auth", "token"]:
                return "tok"
            if "search/issues" in args:
                return search_raw
            return json.dumps(page)
        return fake, calls

    def collect(self, search_raw):
        fake, calls = self.fake(search_raw)
        orig = rf.run
        rf.run = fake
        try:
            start, end = rf.bounds(DAY, DAY)
            unseen = []
            out = rf.github(start, end, unseen)
        finally:
            rf.run = orig
        return out, unseen, calls

    def test_cut_events_are_told_and_searched(self):
        found = {"total_count": 2, "incomplete_results": False, "items": [
            {"number": 5, "title": "t", "state": "open", "updated_at": at(8), "pull_request": {},
             "repository_url": "https://api.github.com/repos/o/r"},
            {"number": 6, "title": "u", "state": "closed", "updated_at": at(7),
             "repository_url": "https://api.github.com/repos/o/s"}]}
        out, unseen, calls = self.collect(json.dumps(found))
        g = out[0]
        self.assertTrue(g["truncated"])
        self.assertEqual(g["from"][:16], dt.datetime.combine(DAY, dt.time(20)).astimezone().isoformat()[:16])
        self.assertEqual([(i["kind"], i["repo"], i["number"]) for i in g["search"]["items"]],
                         [("pr", "o/r", 5), ("issue", "o/s", 6)])
        q = next(a for a in calls if "search/issues" in a)
        self.assertTrue(any(x.startswith("q=involves:a updated:") for x in q), q)
        notes = rf.github_notes(out)
        self.assertEqual(len(notes), 1)
        self.assertIn("検索で 2 件補った", notes[0])
        self.assertEqual(unseen, [])
        priv = rf.privacy([], out, ask=lambda label: label == "o/s")
        self.assertEqual((priv["repos"], priv["numbers"]), (["o/s"], [6]))

    def test_an_unreadable_search_is_said(self):
        out, unseen, _ = self.collect(None)
        self.assertIsNone(out[0]["search"])
        self.assertTrue(any("検索" in u and "読めなかった" in u for u in unseen), unseen)
        self.assertEqual(len(rf.github_notes(out)), 1)


class CoverageOnThePage(unittest.TestCase):
    def test_the_template_shows_the_gaps_at_the_top(self):
        html = (ROOT / "attention" / "templates" / "reflect.html").read_text(encoding="utf-8")
        self.assertIn("(data.coverage || {}).notes", html)
        self.assertLess(html.index("(data.coverage || {}).notes"), html.index("// 改善の提案"))


if __name__ == "__main__":
    unittest.main(verbosity=1)
