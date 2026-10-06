"""修正役が範囲を修正案を書いた役に相談する道具（blk-fix/lib/askplan.py。設計 docs/plans/2026-10-06-ask-planner.md）の検査。

縛る事:
- 先の確かめ: 知らない項目・根の外のパス・out_of_scope に当たるパス・もう範囲の中のパスは、AI に聞かずに断る（記録は残す）
- 答えの確かめ: 許すのは頼んだ物の中だけ（足した物は捨てて記録）。形の崩れた答えは invalid で、許しを作らない
- 再開: 包みが記録した会話の id の transcript を run ごとの置き場の私物の設定の置き場へ写し、そこへ向けた CLAUDE_CONFIG_DIR と
  cwd（run の作業ツリー）で `--resume` する。元の transcript は変わらない。2 回目は写しの会話（返った会話の id）を継ぎ、元の id が
  替われば写し直す
- 認証: トークンは子の環境にだけ置き、標準出力と記録に出さない（出どころの名だけ）。修正役の環境が継いだ認証（修正役の claude
  自身の認証。Bash の子へ継がれる）を先に使い、keychain を読みに行かない（sandbox は keychain を読ませない。run 68f35d6b）。
  継いだ認証が無い時だけ auth_launch.resolve
- 子の書き込み: 子の HOME は置き場の下（sandbox が書ける所。HOME の下のキャッシュに書きに行って落ちない）、自動更新は止める
- 聞けない（会話の記録が無い・認証が無い・claude が落ちた）は unavailable で終了コード 3
- 盤面への写し（settle）: まだ写していない行だけを trace に写し、部品の窓の照らしで宣言の外にならない
本物の claude は起こさない（子は偽の claude の python3 1 本）。盤面は trace だけを持つ偽物。git は使わない。
"""
import contextlib
import io
import json
import os
import pathlib
import stat
import subprocess
import sys
import tempfile
import textwrap
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.dont_write_bytecode = True
sys.path.insert(0, str(ROOT / "blk-fix" / "lib"))
sys.path.insert(0, str(ROOT / ".shared" / "core"))

import askplan  # noqa: E402
import conflict  # noqa: E402
import scopes  # noqa: E402

SECRET = "sk-ant-oat01-test-secret-do-not-print"
SID = "11111111-2222-3333-4444-555555555555"
ITEMS = {"3": {"unit_keys": ["lens.py count_line: 落ちたレンズの数"], "allowed_paths": ["works/.shared/core/lens.py"],
               "out_of_scope": ["works/README.md"], "tests": ["works/tests/test_lens.py"]}}

FAKE = textwrap.dedent("""\
    #!{python}
    import glob, json, os, sys
    argv = sys.argv[1:]
    sid = argv[argv.index("--resume") + 1]
    cfg = os.environ["CLAUDE_CONFIG_DIR"]
    hits = glob.glob(os.path.join(cfg, "projects", "*", sid + ".jsonl"))
    prompt = sys.stdin.read()
    log = os.environ["FAKE_LOG"]
    with open(log, "a") as f:
        f.write(json.dumps({{"argv": argv, "cwd": os.getcwd(), "config": cfg, "found": hits,
                             "token": os.environ.get("CLAUDE_CODE_OAUTH_TOKEN") == "{secret}",
                             "home": os.environ.get("HOME"), "autoupdater": os.environ.get("DISABLE_AUTOUPDATER"),
                             "prompt": prompt}}) + "\\n")
    if os.environ.get("FAKE_FAIL"):
        sys.exit(1)
    new = os.environ.get("FAKE_NEW_SID") or sid
    for h in hits:
        with open(h, "a") as f:
            f.write(json.dumps({{"asked": prompt[:20]}}) + "\\n")
        if new != sid:
            os.rename(h, os.path.join(os.path.dirname(h), new + ".jsonl"))
    answer = json.load(open(os.environ["FAKE_ANSWER"]))
    print(json.dumps({{"type": "result", "subtype": "success", "result": json.dumps(answer), "session_id": new,
                      "structured_output": answer}}))
    """)


class Fixture(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = pathlib.Path(self.tmp.name)
        self.root = root
        self.repo = root / "repo"
        self.repo.mkdir()
        self.config = root / "orig-config"
        self.proj = self.config / "projects" / "-tmp-repo"
        self.proj.mkdir(parents=True)
        self.transcript = self.proj / f"{SID}.jsonl"
        self.transcript.write_text('{"plan": "first"}\n', encoding="utf-8")
        self.session_file = root / "adapter" / "sessions" / "k" / "plan.id"
        self.session_file.parent.mkdir(parents=True)
        self.session_file.write_text(SID + "\n", encoding="utf-8")
        self.claude = root / "claude"
        self.claude.write_text(FAKE.format(python=sys.executable, secret=SECRET), encoding="utf-8")
        self.claude.chmod(self.claude.stat().st_mode | stat.S_IEXEC)
        self.place = root / "run-place" / "fixing" / askplan.PLACE
        self.log = root / "fake.jsonl"
        self.answer = root / "answer.json"
        self.cfg_path = askplan.write_config(self.place, {
            "board": str(root / "board"), "repo": str(self.repo), "session_file": str(self.session_file),
            "config_dir": str(self.config), "claude": str(self.claude), "model": "opus", "effort": "high",
            "items": ITEMS, "scope": "fixing"})
        self.env = {"PATH": os.environ.get("PATH", ""), "HOME": str(root), "CLAUDE_CODE_OAUTH_TOKEN": SECRET,
                    "FAKE_LOG": str(self.log), "FAKE_ANSWER": str(self.answer)}

    def say(self, **answer):
        self.answer.write_text(json.dumps(answer), encoding="utf-8")

    def calls(self):
        return [json.loads(line) for line in self.log.read_text(encoding="utf-8").splitlines()] if self.log.exists() else []

    def ask(self, paths=("works/CHANGELOG.md",), tests=(), why="直しに伴って変更の記録を足す要がある", env=None):
        cfg = askplan.load_config(self.cfg_path)
        return askplan.ask(cfg, "3", list(paths), list(tests), why, env={**self.env, **(env or {})})


class ScreenCase(Fixture):
    def test_out_of_scope_refused_without_asking(self):
        self.say(decision="allow", paths=["works/README.md"], tests=[], spec="", reason="足してよい（試しの答え）")
        row = self.ask(paths=["works/README.md"])
        self.assertEqual(row["status"], askplan.REFUSED)
        self.assertIn("out_of_scope", row["why_refused"])
        self.assertEqual(self.calls(), [], "AI に聞かない")
        self.assertEqual([r["id"] for r in askplan.exchanges(self.place)], [row["id"]], "断った相談も記録する")

    def test_unknown_item_and_climbing_path_refused(self):
        cfg = askplan.load_config(self.cfg_path)
        self.assertIn("項目", askplan.screen(cfg, "9", ["a.py"], []))
        self.assertIn("根の外", askplan.screen(cfg, "3", ["../x.py"], []))
        self.assertIn("範囲の中", askplan.screen(cfg, "3", ["works/.shared/core/lens.py"], []))
        self.assertIsNone(askplan.screen(cfg, "3", ["works/CHANGELOG.md"], []))
        self.assertIsNone(askplan.screen(cfg, "3", [], ["works/tests/test_report.py:12"]))
        self.assertIn("何も", askplan.screen(cfg, "3", [], []))


class JudgeCase(unittest.TestCase):
    def test_grant_is_cut_to_what_was_asked(self):
        got, notes = askplan.judge({"decision": "allow", "paths": ["a.md", "b.md"], "tests": ["t.py:3"], "spec": "",
                                    "reason": "変更の記録は直しに伴う"}, ["a.md"], ["t.py:3"])
        self.assertEqual((got["decision"], got["granted_paths"], got["granted_tests"]), ("allow", ["a.md"], ["t.py:3"]))
        self.assertTrue(any("b.md" in n for n in notes), notes)

    def test_malformed_answers_are_invalid(self):
        for bad in ({"decision": "maybe", "reason": "x" * 12}, {"decision": "allow", "paths": [], "tests": [], "reason": "x" * 12},
                    {"decision": "deny"}, "not a dict"):
            got, notes = askplan.judge(bad, ["a.md"], [])
            self.assertIsNone(got, bad)
            self.assertTrue(notes, bad)

    def test_deny_and_defer_grant_nothing(self):
        for d in ("deny", "defer"):
            got, _ = askplan.judge({"decision": d, "paths": ["a.md"], "tests": [], "spec": "", "reason": "今の run の仕様の外"},
                                   ["a.md"], [])
            self.assertEqual((got["granted_paths"], got["granted_tests"]), ([], []), d)


class AskCase(Fixture):
    def test_allow_resumes_a_copy_and_records(self):
        self.say(decision="allow", paths=["works/CHANGELOG.md"], tests=[], spec="Unreleased に 1 行", reason="直しに伴う変更の記録の更新")
        row = self.ask()
        self.assertEqual((row["status"], row["decision"], row["granted_paths"]), (askplan.ANSWERED, "allow", ["works/CHANGELOG.md"]))
        (call,) = self.calls()
        self.assertEqual(call["argv"][call["argv"].index("--resume") + 1], SID)
        self.assertNotEqual(pathlib.Path(call["config"]).resolve(), self.config.resolve(), "元の設定の置き場で再開しない")
        self.assertTrue(str(pathlib.Path(call["config"]).resolve()).startswith(str(self.place.resolve())))
        self.assertTrue(call["found"], "写しの transcript を引ける")
        self.assertEqual(pathlib.Path(call["cwd"]).resolve(), self.repo.resolve())
        self.assertTrue(call["token"], "子は認証を持つ")
        for flag in ("--json-schema", "--output-format", "--tools"):
            self.assertIn(flag, call["argv"])
        self.assertEqual(call["argv"][call["argv"].index("--model") + 1], "opus")
        self.assertIn("works/CHANGELOG.md", call["prompt"])
        self.assertEqual(self.transcript.read_text(encoding="utf-8"), '{"plan": "first"}\n', "元の会話は変わらない")
        (rec,) = askplan.exchanges(self.place)
        self.assertEqual(rec["id"], row["id"])
        self.assertNotIn(SECRET, json.dumps(rec))
        self.assertEqual(rec["auth"], "env:CLAUDE_CODE_OAUTH_TOKEN", "出どころの名だけ")

    def test_inherited_credential_is_used_before_keychain(self):
        """run 68f35d6b: WORKS_KEYCHAIN_ITEM を名指した run で、sandbox の中から keychain を読めずに unavailable になった。
        修正役の環境が継いだ認証が在れば、それで聞く（keychain に行かない）"""
        self.say(decision="allow", paths=["works/CHANGELOG.md"], tests=[], spec="", reason="直しに伴う変更の記録の更新")
        cfg = askplan.load_config(self.cfg_path)
        called = []

        def keychain_blocked(env, home, config):
            called.append(True)
            return None, None, "keychain の項目 claude-code-oauth-p3 を読めない: keychain-miss"
        row = askplan.ask(cfg, "3", ["works/CHANGELOG.md"], [], "直しに伴って変更の記録を足す要がある",
                          env={**self.env, "WORKS_KEYCHAIN_ITEM": "claude-code-oauth-p3"}, resolve=keychain_blocked)
        self.assertEqual(row["status"], askplan.ANSWERED, row.get("why_unavailable"))
        self.assertEqual(called, [], "継いだ認証が在れば keychain を読みに行かない")
        (call,) = self.calls()
        self.assertTrue(call["token"], "子は継いだ認証を持つ")
        self.assertEqual(row["auth"], "env:CLAUDE_CODE_OAUTH_TOKEN")
        self.assertNotIn(SECRET, json.dumps(askplan.exchanges(self.place)))

    def test_child_home_is_under_the_place(self):
        """子の claude は HOME の下（キャッシュ・自動更新）にも書く。修正役の sandbox は HOME に書かせないので、子の HOME を
        置き場の下へ向け、自動更新を止める"""
        self.say(decision="deny", paths=[], tests=[], spec="", reason="範囲の中で直せる（試しの答え）")
        self.ask()
        (call,) = self.calls()
        self.assertTrue(str(pathlib.Path(call["home"]).resolve()).startswith(str(self.place.resolve())), call["home"])
        self.assertTrue(pathlib.Path(call["home"]).is_dir())
        self.assertEqual(call["autoupdater"], "1")

    def test_second_ask_continues_the_copy(self):
        self.say(decision="deny", paths=[], tests=[], spec="", reason="範囲の中で直せる（試しの答え）")
        self.ask(env={"FAKE_NEW_SID": "new-1"})
        self.ask(env={"FAKE_NEW_SID": "new-2"})
        first, second = self.calls()
        self.assertEqual(second["argv"][second["argv"].index("--resume") + 1], "new-1", "返った会話を継ぐ")
        self.assertTrue(second["found"])

    def test_new_planner_session_is_copied_again(self):
        self.say(decision="defer", paths=[], tests=[], spec="", reason="次の run で決める（試しの答え）")
        self.ask(env={"FAKE_NEW_SID": "new-1"})
        other = "99999999-2222-3333-4444-555555555555"
        (self.proj / f"{other}.jsonl").write_text('{"plan": "again"}\n', encoding="utf-8")
        self.session_file.write_text(other, encoding="utf-8")
        self.ask()
        self.assertEqual(self.calls()[1]["argv"][self.calls()[1]["argv"].index("--resume") + 1], other)
        self.assertTrue(self.calls()[1]["found"])

    def test_unavailable_when_session_missing_or_claude_fails(self):
        self.say(decision="deny", paths=[], tests=[], spec="", reason="試しの答え（使われない）")
        self.session_file.unlink()
        row = self.ask()
        self.assertEqual(row["status"], askplan.UNAVAILABLE)
        self.session_file.write_text(SID, encoding="utf-8")
        row = self.ask(env={"FAKE_FAIL": "1"})
        self.assertEqual(row["status"], askplan.UNAVAILABLE)
        self.assertEqual(len(askplan.exchanges(self.place)), 2)

    def test_unavailable_without_auth(self):
        self.say(decision="deny", paths=[], tests=[], spec="", reason="試しの答え（使われない）")
        cfg = askplan.load_config(self.cfg_path)
        env = {k: v for k, v in self.env.items() if k != "CLAUDE_CODE_OAUTH_TOKEN"}
        row = askplan.ask(cfg, "3", ["works/CHANGELOG.md"], [], "理由の文を 10 字より長く", env=env,
                          resolve=lambda env, home, config: (None, None, "認証が無い（試し）"))
        self.assertEqual(row["status"], askplan.UNAVAILABLE)
        self.assertIn("認証が無い（試し）", row["why_unavailable"])
        self.assertEqual(self.calls(), [])

    def test_keychain_fallback_without_inherited_credential(self):
        """継いだ認証が無ければ auth_launch.resolve（keychain）で聞く。記録は出どころの名だけ"""
        self.say(decision="deny", paths=[], tests=[], spec="", reason="範囲の中で直せる（試しの答え）")
        cfg = askplan.load_config(self.cfg_path)
        env = {k: v for k, v in self.env.items() if k != "CLAUDE_CODE_OAUTH_TOKEN"}
        row = askplan.ask(cfg, "3", ["works/CHANGELOG.md"], [], "理由の文を 10 字より長く", env=env,
                          resolve=lambda env, home, config: ({"CLAUDE_CODE_OAUTH_TOKEN": SECRET}, "keychain の項目 x", None))
        self.assertEqual((row["status"], row["auth"]), (askplan.ANSWERED, "keychain の項目 x"))
        self.assertTrue(self.calls()[0]["token"])

    def test_cli_exit_3_when_no_auth(self):
        """認証が無い（継いだ物も keychain も）時は終了コード 3（修正役は食い違いの申し出の道へ戻る）"""
        self.say(decision="deny", paths=[], tests=[], spec="", reason="試しの答え（使われない）")
        env = {k: v for k, v in self.env.items() if k != "CLAUDE_CODE_OAUTH_TOKEN"}
        orig, out = askplan.ask, io.StringIO()
        try:
            askplan.ask = lambda *a, **k: orig(*a, **{**k, "env": env, "resolve": lambda e, h, c: (None, None, "無い（試し）")})
            with contextlib.redirect_stdout(out):
                rc = askplan.main([str(self.cfg_path), "--item", "3", "--paths", "works/CHANGELOG.md",
                                   "--why", "直しに伴って変更の記録を足す要がある"])
        finally:
            askplan.ask = orig
        self.assertEqual(rc, 3)
        self.assertEqual(json.loads(out.getvalue())["status"], askplan.UNAVAILABLE)
        self.assertEqual(self.calls(), [])

    def test_cli_prints_answer_and_exit_codes(self):
        self.say(decision="allow", paths=["works/CHANGELOG.md"], tests=[], spec="", reason="直しに伴う記録の更新")
        p = subprocess.run([sys.executable, str(ROOT / "blk-fix" / "lib" / "askplan.py"), str(self.cfg_path), "--item", "3",
                            "--paths", "works/CHANGELOG.md", "--why", "直しに伴って変更の記録を足す要がある"],
                           capture_output=True, text=True, encoding="utf-8", env={**self.env, "PYTHONDONTWRITEBYTECODE": "1"})
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(json.loads(p.stdout)["decision"], "allow")
        self.assertNotIn(SECRET, p.stdout + p.stderr)
        p = subprocess.run([sys.executable, str(ROOT / "blk-fix" / "lib" / "askplan.py"), str(self.cfg_path), "--item", "3",
                            "--paths", "works/CHANGELOG.md", "--why", "短い"], capture_output=True, text=True, encoding="utf-8", env=self.env)
        self.assertEqual(p.returncode, 2, "理由が短すぎるのは使い方の誤り")


class FakeBoard:
    def __init__(self, d):
        self.dir = pathlib.Path(d)
        self.dir.mkdir(parents=True, exist_ok=True)

    def trace(self, op, **kw):
        with open(self.dir / "trace.jsonl", "a", encoding="utf-8") as f:
            f.write(json.dumps({"op": op, **kw}, ensure_ascii=False) + "\n")


class SettleCase(Fixture):
    def test_settle_copies_new_rows_once_and_agreed_reads_them(self):
        self.say(decision="allow", paths=["works/CHANGELOG.md"], tests=["works/tests/test_report.py:12"], spec="",
                 reason="直しに伴う記録と期待の書き換え")
        self.ask(tests=["works/tests/test_report.py:12"])
        b = FakeBoard(self.root / "board")
        for rel in ("state.json", "r1/start.json"):
            (b.dir / rel).parent.mkdir(parents=True, exist_ok=True)
            (b.dir / rel).write_text("{}", encoding="utf-8")
        (b.dir / "trace.jsonl").write_text("", encoding="utf-8")
        window = {"scope": "fixing", "block": "blk-fix", "round": 1, "files": scopes.snapshot(b.dir)}
        self.assertEqual(len(askplan.settle(b, self.place)), 1)
        self.assertEqual(askplan.settle(b, self.place), [], "同じ行を 2 度写さない")
        self.assertEqual(scopes.check_window(b.dir, window), [], "盤面への写しは宣言の外に書かない")
        (row,) = conflict.agreed(b)
        self.assertEqual((row["item"], row["granted_paths"]), ("3", ["works/CHANGELOG.md"]))
        (permit,) = conflict.agreed_permits([row])
        self.assertEqual((permit["limit"], permit["id"]), ("works/tests/test_report.py:12", f"{conflict.AGREED_TEST_ID}-3"))
        self.assertIn(row["reason"], permit["why"])


if __name__ == "__main__":
    unittest.main()
