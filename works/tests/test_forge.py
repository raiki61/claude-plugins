"""対象の remote が forge（PR を持つホスト。今は GitHub）かを git だけで決める口（.shared/core/forge.py）と、その決めを盤面へ
写す works の差し替え（entry.CORE_OVERRIDES の on_init・parallel_pr_due・fill_materials）の検査。

canary の run 5318f732 の事実: origin がローカルの bare リポジトリの run で、並行 PR の任せ先の役が素材 parallel_pr を
awaiting_human と書き、判定が問いの台帳に保留の問いを置いて、直しが済みテストも緑なのに結末が round_limit になった（同じ形の
run 1・2 は役が clean と書いて通った——役の判断で割れていた）。forge の無い remote（origin が無い・ローカルのパス・GitHub で
ないホスト）は機械が決めて並行 PR の節を条件外（not_applicable・reason は no_forge: <種類>）にし、役に聞かない。
GitHub の remote で gh が無い・未ログイン・API が落ちた時は今どおり（確かめる物が在るのに確かめられなかった）。

関数を直に呼ぶ・一時の置き場で git init と remote add を起こすだけ（盤面・子の実行器なし）。
"""
import pathlib
import subprocess
import sys
import tempfile
import unittest

TESTS = pathlib.Path(__file__).resolve().parent
CORE = TESTS.parent / ".shared" / "core"
sys.dont_write_bytecode = True
sys.path.insert(0, str(CORE))
sys.path.insert(0, str(TESTS))

import hermetic  # noqa: E402
import forge  # noqa: E402
import board  # noqa: E402
import entry  # noqa: E402
import prcheck  # noqa: E402
import report  # noqa: E402
from engine.rules import registry  # noqa: E402

SECRET = "ghp_SECRETVALUE"


def _git(repo, *args):
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)


class ClassifyCase(unittest.TestCase):
    """URL の形から forge の種類を決める（GitHub か・forge でない 3 つの種類のどれか）"""

    def test_github_forms(self):
        for url in ("https://github.com/o/r.git", "https://github.com/o/r", "git@github.com:o/r.git",
                    "ssh://git@github.com/o/r.git", "ssh://git@ssh.github.com:443/o/r.git", "https://GitHub.com/o/r",
                    f"https://x-access-token:{SECRET}@github.com/o/r.git", "git://github.com/o/r.git",
                    "https://acme.ghe.com/o/r.git", "git@github.com-work:o/r.git", "ssh://git@github.com-work/o/r.git"):
            with self.subTest(url):
                self.assertEqual(forge.classify(url)["kind"], forge.GITHUB)

    def test_local_paths(self):
        for url in ("/Users/x/canary/origin.git", "../origin.git", "origin.git", "file:///tmp/o.git", "file:/tmp/o.git",
                    "C:\\work\\o.git", "C:/work/o.git", "~/o.git"):
            with self.subTest(url):
                self.assertEqual(forge.classify(url)["kind"], forge.LOCAL_PATH)

    def test_other_hosts(self):
        for url, host in (("https://gitlab.com/o/r.git", "gitlab.com"), ("git@gitlab.example.com:o/r.git", "gitlab.example.com"),
                          ("ssh://git@git.example.com:2222/o/r.git", "git.example.com"),
                          ("https://bitbucket.org/o/r", "bitbucket.org"), ("https://notgithub.com/o/r", "notgithub.com"),
                          ("https://github.com.evil.example/o/r", "github.com.evil.example")):
            with self.subTest(url):
                got = forge.classify(url)
                self.assertEqual((got["kind"], got["where"]), (forge.OTHER_HOST, host))

    def test_unreadable_url_is_other_host_not_a_crash(self):
        """urlsplit が読めない URL（括弧の崩れた IPv6 の形）も落ちずに forge の無い側（理由に URL を載せない）"""
        got = forge.classify(f"https://u:{SECRET}@[abc/o/r")
        self.assertEqual(got["kind"], forge.OTHER_HOST)
        self.assertNotIn(SECRET, repr(got))

    def test_missing(self):
        for url in (None, "", "  "):
            with self.subTest(url):
                self.assertEqual(forge.classify(url)["kind"], forge.NO_REMOTE)

    def test_reason_never_carries_credentials(self):
        """URL の userinfo（トークン）は種類の理由にも where にも載せない"""
        for url in (f"https://u:{SECRET}@gitlab.com/o/r.git", f"https://{SECRET}@gitlab.com/o/r.git",
                    f"file://u:{SECRET}@localhost/tmp/o.git", f"https://u:{SECRET}@github.com/o/r.git"):
            with self.subTest(url):
                d = forge.classify(url)
                self.assertNotIn(SECRET, repr(d))
                self.assertNotIn(SECRET, forge.reason({**d, "remote": "origin"}))


class ReasonCase(unittest.TestCase):
    def test_no_forge_reason_names_the_kind(self):
        for kind in forge.NO_FORGE:
            with self.subTest(kind):
                why = forge.reason({"kind": kind, "remote": "origin", "where": "x"})
                self.assertTrue(why.startswith(f"no_forge: {kind}"), why)

    def test_github_and_unknown_are_not_no_forge(self):
        """GitHub は forge（今どおり確かめる）。盤面に決めが無い（前の版の盤面）・形が崩れた値も今どおり（空の理由）"""
        for d in ({"kind": forge.GITHUB, "remote": "origin", "where": "github.com"}, None, {}, {"kind": "weird"}, "x"):
            with self.subTest(d):
                self.assertEqual(forge.reason(d), "")


class DetectCase(unittest.TestCase):
    """本物の git で remote を引く（upstream の remote を先に、無ければ origin。写しの _github_repo と同じ選び方）"""

    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.repo = pathlib.Path(self._td.name) / "r"
        self.repo.mkdir()
        _git(self.repo, "init", "-q")

    def tearDown(self):
        self._td.cleanup()

    def test_no_origin(self):
        got = forge.detect(self.repo)
        self.assertEqual((got["kind"], got["remote"]), (forge.NO_REMOTE, "origin"))

    def test_local_bare_origin(self):
        _git(self.repo, "remote", "add", "origin", str(self.repo.parent / "origin.git"))
        self.assertEqual(forge.detect(self.repo)["kind"], forge.LOCAL_PATH)

    def test_github_origin(self):
        _git(self.repo, "remote", "add", "origin", "git@github.com:o/r.git")
        self.assertEqual(forge.detect(self.repo)["kind"], forge.GITHUB)

    def test_other_host_origin(self):
        _git(self.repo, "remote", "add", "origin", "https://gitlab.com/o/r.git")
        got = forge.detect(self.repo)
        self.assertEqual((got["kind"], got["where"]), (forge.OTHER_HOST, "gitlab.com"))

    def test_upstream_remote_wins(self):
        """枝の upstream の remote が在ればそれを見る（origin が GitHub でも upstream が GitLab なら forge でない）"""
        _git(self.repo, "remote", "add", "origin", "git@github.com:o/r.git")
        _git(self.repo, "remote", "add", "up", "https://gitlab.com/o/r.git")
        _git(self.repo, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "--allow-empty", "-m", "s")
        _git(self.repo, "update-ref", "refs/remotes/up/main", "HEAD")
        br = subprocess.run(["git", "-C", str(self.repo), "branch", "--show-current"], capture_output=True, text=True, encoding="utf-8").stdout.strip()
        _git(self.repo, "branch", "--set-upstream-to=up/main", br)
        got = forge.detect(self.repo)
        self.assertEqual((got["kind"], got["remote"]), (forge.OTHER_HOST, "up"))

    def test_not_a_repo_is_unknown(self):
        """git が remote を引けない（リポジトリでない）は決めない: 種類 unknown・理由は空（今どおり役の道へ。forge が無いとは言わない）"""
        got = forge.detect(pathlib.Path(self._td.name) / "missing")
        self.assertEqual(got["kind"], forge.UNKNOWN)
        self.assertEqual(forge.reason(got), "")


LOCAL = {"kind": forge.LOCAL_PATH, "remote": "origin", "where": "/x/origin.git"}
GH = {"kind": forge.GITHUB, "remote": "origin", "where": "github.com"}


def _rl():
    """写しの RL を新しく読み、works の核の差し替え（entry.CORE_OVERRIDES）を当てた物"""
    holder = type("H", (), {})()
    holder.rules, holder.state = board.rules_module(), {}
    board.DiskBoard._apply_overrides(holder, entry.CORE_OVERRIDES)
    return holder.rules


def _view(values):
    def v(path, *default):
        return values[path] if path in values else (default[0] if default else None)
    return v


class FakeBoard:
    def __init__(self, cwd=None, forge_d=None, na=True):
        self.state = {"inputs": {"cwd": str(cwd) if cwd else ""}}
        self.loop_state = {} if forge_d is None else {forge.LOOP_KEY: forge_d}
        self.record = {"materials": {}}
        self.nodes = {prcheck.NODE: {"materials": ["parallel_pr"]}}
        self._na = na

    def node_state(self, nid):
        return "na" if (nid == prcheck.NODE and self._na) else "done"


class OverrideCase(unittest.TestCase):
    """works の核の差し替え: 決めは run の初め（on_init）に盤面の loop へ、並行 PR の節の条件はその値を読み、素材は機械が埋める"""

    def test_cond_is_false_on_no_forge_and_reads_the_loop_field(self):
        cond = registry(_rl(), "CONDS")["parallel_pr_due"]
        self.assertIn(f"loop.{forge.LOOP_KEY}", cond.reads)
        ok, why = cond(_view({"round": 1, f"loop.{forge.LOOP_KEY}": LOCAL}))
        self.assertFalse(ok)
        self.assertTrue(why.startswith("no_forge: local_path"), why)

    def test_cond_keeps_the_copy_rule_on_github_and_on_old_boards(self):
        """GitHub の remote・決めの無い盤面（前の版）では写しの条件のまま（1 周目は真）"""
        cond = registry(_rl(), "CONDS")["parallel_pr_due"]
        for d in (GH, None):
            with self.subTest(d):
                vals = {"round": 1} if d is None else {"round": 1, f"loop.{forge.LOOP_KEY}": d}
                self.assertEqual(cond(_view(vals))[0], True)

    def test_on_init_records_the_forge_on_the_board(self):
        with tempfile.TemporaryDirectory() as td:
            repo = pathlib.Path(td) / "r"
            repo.mkdir()
            _git(repo, "init", "-q")
            _git(repo, "remote", "add", "origin", str(pathlib.Path(td) / "origin.git"))
            calls = []
            rl = type("RL", (), {"on_init": staticmethod(lambda b, a: calls.append(a))})
            b = FakeBoard(cwd=repo)
            entry.on_init_forge(rl)(b, None)
            self.assertEqual(calls, [None], "写しの on_init を先に呼ぶ")
            self.assertEqual(b.loop_state[forge.LOOP_KEY]["kind"], forge.LOCAL_PATH)

    def test_fill_writes_not_applicable_for_the_skipped_node(self):
        seen = []
        rl = type("RL", (), {"fill_materials": staticmethod(lambda b: seen.append(dict(b.record["materials"])))})
        b = FakeBoard(forge_d=LOCAL)
        entry.fill_materials_forge(rl)(b)
        m = b.record["materials"]["parallel_pr"]
        self.assertEqual(m["status"], "not_applicable")
        self.assertTrue(m["reason"].startswith("no_forge: local_path"), m)
        self.assertEqual(seen, [{"parallel_pr": m}], "写しの fill_materials は埋めた後に呼ぶ（埋めた素材を上書きしない）")

    def test_fill_leaves_github_and_ran_nodes_to_the_copy(self):
        for b in (FakeBoard(forge_d=GH), FakeBoard(forge_d=LOCAL, na=False), FakeBoard()):
            with self.subTest(b.loop_state):
                rl = type("RL", (), {"fill_materials": staticmethod(lambda b: None)})
                entry.fill_materials_forge(rl)(b)
                self.assertNotIn("parallel_pr", b.record["materials"])

    def test_copy_fallback_reason_never_carries_the_token(self):
        """写しの _github_repo は形の合わない remote の URL を任せ先に落ちた理由（盤面の engine_fallback・役への渡し物）に
        書く。userinfo（トークン）を持つ GitHub の URL でも、差し替えがトークンを伏せる"""
        import engine.util as eu
        with tempfile.TemporaryDirectory() as td:
            repo = pathlib.Path(td) / "r"
            repo.mkdir()
            _git(repo, "init", "-q")
            _git(repo, "remote", "add", "origin", f"https://x-access-token:{SECRET}@github.com/o/r.git")
            old, eu.GIT_CWD = eu.GIT_CWD, str(repo)
            try:
                rl = _rl()
                got, why = rl._github_repo()
            finally:
                eu.GIT_CWD = old
        self.assertIsNone(got)
        self.assertNotIn(SECRET, why)
        self.assertIn("github.com/o/r", why)

    def test_overrides_are_registered(self):
        for name in ("on_init", "parallel_pr_due", "fill_materials", "_github_repo"):
            with self.subTest(name):
                self.assertIn(name, entry.CORE_OVERRIDES)


class ReportLineCase(unittest.TestCase):
    """報告の冒頭 2 に 1 行: forge の無い run は並行 PR の確かめが条件外だと言う（GitHub の run と前の版の盤面には出さない）"""

    def board(self, d, forge_d):
        b = type("B", (), {})()
        b.dir, b.round, b.table = pathlib.Path(d), 1, None
        b.state = {"works": {}, "loop": {} if forge_d is None else {forge.LOOP_KEY: forge_d}}
        b.loop_state = b.state["loop"]
        b.record = {"process": {}, "materials": {}}
        return b

    def test_head_entry_has_one_line_on_no_forge(self):
        with tempfile.TemporaryDirectory() as td:
            lines = report.head_entry(self.board(td, LOCAL), {})
            hits = [x for x in lines if x.startswith(report.FORGE_HEAD)]
            self.assertEqual(len(hits), 1, lines)
            self.assertIn("no_forge: local_path", hits[0])
            self.assertIn("not_applicable", hits[0])

    def test_no_line_on_github_or_old_boards(self):
        for d in (GH, None):
            with self.subTest(d), tempfile.TemporaryDirectory() as td:
                lines = report.head_entry(self.board(td, d), {})
                self.assertFalse([x for x in lines if x.startswith(report.FORGE_HEAD)], lines)


class GhReadsCase(unittest.TestCase):
    """run の中の読み出し（ghreads.read_named）は、forge の無い対象でも利用者が名指した PR・issue を gh で読み（GH_REPO・
    別の remote・自前のドメインの GitHub Enterprise Server なら gh は読める）、gh も GitHub のホストを見つけなかった項だけを条件外
    （not_applicable、reason は no_forge: <種類>）と書く。gh が読みに行って読めなかった項は unreadable（理由は gh の言葉、欄 forge に
    no_forge の決め）。入力 pr は base・head が読めなければ、条件外なら no_forge の理由で、読めないならログインしてから回せと
    線の入口（entry._change_base）が止める"""

    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.tmp = pathlib.Path(self._td.name).resolve()
        self.addCleanup(self._td.cleanup)
        self.repo = self.tmp / "repo"
        self.repo.mkdir()
        _git(self.repo, "init", "-q")
        _git(self.repo, "remote", "add", "origin", str(self.tmp / "origin.git"))
        self.bin = self.tmp / "bin"
        self.bin.mkdir()
        self.called = self.tmp / "gh-called"
        gh = self.bin / "gh"
        gh.write_text(f'#!/bin/sh\necho "$*" >> "{self.called}"\nexit 4\n', encoding="utf-8")
        gh.chmod(0o755)

    def read(self, prs, issues=(), **env_kw):
        """偽の gh を PATH の頭に置き、利用者の gh の設定の置き場を外した env（env_kw を上に置く）で read_named を呼ぶ"""
        import os
        from unittest import mock
        import ghreads
        env = hermetic.child_env(PATH=f"{self.bin}{os.pathsep}{os.environ.get('PATH', '')}", HOME=str(self.tmp / "home"),
                                 XDG_CONFIG_HOME=str(self.tmp / "xdg"), **env_kw)
        if "GH_CONFIG_DIR" not in env_kw:
            env.pop("GH_CONFIG_DIR", None)
        with mock.patch.dict("os.environ", env, clear=True):
            return ghreads.read_named(self.repo, list(prs), list(issues))

    @staticmethod
    def refusal(doc):
        """読み出し doc で入力 pr=7 を解いた時の線の入口の拒みの文"""
        import entry
        try:
            entry._change_base({"pr": "7"}, pathlib.Path("/nonexistent"), doc)
        except entry.InputRefused as e:
            return str(e)
        raise AssertionError("拒まなかった")

    def test_named_items_gh_cannot_read_are_not_applicable(self):
        """gh が読めない（偽の gh は exit 4）名指しの項は unreadable でなく not_applicable（reason は no_forge: <種類>）。
        確かめる物が無いので人待ちにしない"""
        doc = self.read([7], [9])
        self.assertTrue(self.called.exists(), "利用者が名指した項を gh で読みに行かなかった")
        for got in (doc["pr"]["7"], doc["issue"]["9"]):
            self.assertEqual(got["status"], "not_applicable")
            self.assertTrue(got["reason"].startswith("no_forge: local_path"), got)
            self.assertIn("exit 4", got["reason"])   # gh が読めなかった理由も残す

    def test_pr_on_no_forge_refuses_with_the_reason(self):
        """入力 pr の base・head を gh が読めなければ、線の入口が no_forge の理由と base を名指す案内で止める"""
        text = self.refusal(self.read([7]))
        self.assertIn("no_forge: local_path", text)
        self.assertIn("base を名指して回す", text)

    def _reading_gh(self):
        """利用者のログインが見え、PR #7・issue #9 を返す偽の gh（test_ghreads.fake_gh）に替える"""
        from test_ghreads import fake_gh
        self.bin, calls, login = fake_gh(self.tmp)
        return {"GH_CONFIG_DIR": str(login)}

    def test_named_items_gh_can_read_are_kept_on_no_forge(self):
        """forge の無い対象でも、gh が読める名指しの項（GH_REPO・別の remote・自前のドメインの GHES）は読んだ中身を載せる
        （名指した物を黙って落とさない。条件外にするのは並行 PR の確かめと、gh が読めなかった項だけ）"""
        doc = self.read([7], [9], **self._reading_gh())
        self.assertEqual(doc["pr"]["7"]["body"], "非公開の本文")
        self.assertEqual(doc["issue"]["9"]["body"], "課題の本文")

    def test_pr_gh_can_read_runs_on_no_forge(self):
        """forge の無い対象でも、gh が PR の base・head を読めれば読み出しに載る"""
        got = self.read([7], **self._reading_gh())["pr"]["7"]
        self.assertEqual((got["baseRefOid"], got["headRefOid"]), ("b" * 40, "h" * 40))

    def test_pr_gh_reads_without_base_head_refuses_with_gh_words_on_no_forge(self):
        """forge の無い対象で gh が PR を読めたのに base・head の欄が欠けた時は、線の入口が 1 行で止める。読めた項を『ホストが
        無い』と言わず、forge の在る対象と同じ文で止まる"""
        from test_ghreads import fake_gh
        self.bin, _, login = fake_gh(self.tmp, base="", head="")
        text = self.refusal(self.read([7], GH_CONFIG_DIR=str(login)))
        self.assertIn("PR #7 の base・head を読めない", text)
        self.assertNotIn("PR を持つホストが無い", text)
        self.assertNotIn("\n", text)

    def _scripted_gh(self, rows):
        """引数の頭（"pr view 7"・"issue view 9"・"api … pulls/7/comments"）ごとに (exit, 標準出力, 標準エラー) を返す偽の gh に替える。
        当たらない呼び出しは exit 1 と GraphQL の見つからない文"""
        import json
        lines = ["#!/bin/sh", 'case "$*" in']
        for i, (pat, (code, out, err)) in enumerate(rows.items()):
            o, e = self.tmp / f"gh-out-{i}", self.tmp / f"gh-err-{i}"
            o.write_text(json.dumps(out, ensure_ascii=False) if out is not None else "", encoding="utf-8")
            e.write_text(err, encoding="utf-8")
            lines.append(f'  {pat}) cat "{o}"; cat "{e}" >&2; exit {code} ;;')
        lines += ['  *) echo "GraphQL: Could not resolve to a PullRequest" >&2; exit 1 ;;', "esac", ""]
        gh = self.bin / "gh"
        gh.write_text("\n".join(lines), encoding="utf-8")
        gh.chmod(0o755)

    PR = {"baseRefOid": "b" * 40, "headRefOid": "h" * 40, "title": "題", "body": "本文", "comments": [], "reviews": []}
    NO_HOST = ("none of the git remotes configured for this repository point to a known GitHub host. To tell gh about a "
               "new GitHub host, please use `gh auth login`\n")
    EXPIRED = "HTTP 401: Bad credentials (https://ghe.example.com/api/graphql)\nTry authenticating with:  gh auth login\n"

    def _ghes_target(self):
        """対象の remote を自前のドメインのホストにする（形からは GitHub でない＝forge の無い側。GitHub Enterprise Server でもありうる）"""
        _git(self.repo, "remote", "set-url", "origin", "https://ghe.example.com/o/r.git")

    def test_ghes_with_expired_login_is_unreadable_not_not_applicable(self):
        """forge の無い対象（形からは GitHub でないホスト）でも、gh が GitHub のホストとして読みに行って読めなかった項（自前のドメインの
        GHES でログインが切れた: HTTP 401）は not_applicable でなく unreadable で、理由は gh の言葉。forge の無い決めは別の欄 forge に
        残す（本当に条件外の項と見分ける）"""
        self._ghes_target()
        self._scripted_gh({"pr\\ view\\ 7*": (1, None, self.EXPIRED), "issue\\ view\\ 9*": (1, None, self.EXPIRED)})
        doc = self.read([7], [9])
        for got in (doc["pr"]["7"], doc["issue"]["9"]):
            self.assertEqual(got["status"], "unreadable", got)
            self.assertIn("HTTP 401: Bad credentials", got["reason"])
            self.assertFalse(got["reason"].startswith("no_forge"), got)
            self.assertTrue(got["forge"].startswith("no_forge: other_host"), got)
            self.assertNotIn("_no_host", got)   # 内側の印は読み出しに残さない

    def test_ghes_with_expired_login_pr_asks_to_log_in(self):
        """入力 pr でも同じ: gh が読みに行って読めなかったら『ホストが無い』でなく gh でログインしてから回せと言って止まる"""
        self._ghes_target()
        self._scripted_gh({"pr\\ view\\ 7*": (1, None, self.EXPIRED)})
        text = self.refusal(self.read([7]))
        self.assertIn("HTTP 401", text)
        self.assertIn("ログインしてから回す", text)
        self.assertNotIn("PR を持つホストが無い", text)

    def test_gh_sees_no_github_host_is_not_applicable(self):
        """gh 自身が対象の remote を GitHub のホストと見ない（none of the git remotes … known GitHub host）項は今どおり
        not_applicable（理由は no_forge: <種類> と gh の言葉）"""
        self._ghes_target()
        self._scripted_gh({"pr\\ view\\ 7*": (1, None, self.NO_HOST)})
        got = self.read([7])["pr"]["7"]
        self.assertEqual(got["status"], "not_applicable", got)
        self.assertTrue(got["reason"].startswith("no_forge: other_host"), got)
        self.assertIn("known GitHub host", got["reason"])

    def test_mixed_named_items_on_no_forge(self):
        """forge の無い対象で、読める項・行コメントだけ読めない項（partial）・gh が GitHub と見ない項・gh が読みに行って読めない項を
        1 つの依頼に混ぜても、項ごとに分けて書く（読めた項を落とさない・partial は partial のまま・条件外と読めないを混ぜない）"""
        self._ghes_target()
        self._scripted_gh({
            "pr\\ view\\ 7*": (0, self.PR, ""),
            "api*pulls/7/comments": (0, [{"path": "a.py", "line": 1, "body": "行"}], ""),
            "pr\\ view\\ 8*": (0, self.PR, ""),
            "api*pulls/8/comments": (1, None, "HTTP 502: Bad Gateway\n"),
            "pr\\ view\\ 5*": (1, None, self.NO_HOST),
            "issue\\ view\\ 9*": (1, None, self.EXPIRED),
        })
        doc = self.read([7, 8, 5], [9])
        self.assertEqual((doc["pr"]["7"]["status"], doc["pr"]["7"]["review_comments"][0]["body"]), ("ok", "行"))
        self.assertEqual(doc["pr"]["8"]["status"], "partial")
        self.assertEqual(doc["pr"]["8"]["body"], "本文")
        self.assertIn("HTTP 502", doc["pr"]["8"]["reason"])
        self.assertEqual(doc["pr"]["5"]["status"], "not_applicable")
        self.assertEqual(doc["issue"]["9"]["status"], "unreadable")
        self.assertIn("HTTP 401", doc["issue"]["9"]["reason"])
        for n in ("7", "8"):
            self.assertNotIn("forge", doc["pr"][n])   # 読めた項に forge の欄は足さない

if __name__ == "__main__":
    unittest.main()
