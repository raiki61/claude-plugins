"""report ノードと入口（dispatch.py）。herdr・claude・gh は偽物で、流れを回す。git は、流れの組（Main・Issue）は偽物（tests/fakegit.py）、
設定と元の clone の読み方を見る組（Preflight・Init・Check など）は一時のフォルダの本物。"""

import contextlib
import io
import json
import os
import pathlib
import subprocess
import tempfile
import unittest

from . import DISPATCH  # noqa: F401
from . import fakegit
from .test_provision import WorktreeHerdr, git, make_world
import claudex
import config
import dispatch
import wiring
import ghx
import gitx
import herdr as real_herdr
from nodes import clean
from nodes import provision
from nodes import launch
from nodes import prs as prs_node
from nodes import report
from nodes import turn


def typed(command):
    """launch がペインに打ち込む形（PR・issue の会話にだけ効く設定のファイルを付け、POSIX のシェルでは /catchup の窓を開かない前置きが付く）。"""
    command = f"{command} --settings {launch._quote(launch.SESSION_SETTINGS, os.name != 'nt')}"
    return command if os.name == "nt" else f"{launch.QUIET_CATCHUP} {command}"


class Report(unittest.TestCase):
    def test_no_prs_is_one_line(self):
        self.assertEqual(report.lines([], {}, []), ["自分の番の PR は無い"])

    def test_notes_come_first_and_one_line_per_pr(self):
        plan = [{"number": 7, "kind": "pr", "title": "直す", "head": "feat/7", "outcome": "assigned", "path": "/w/feat-7",
                 "account": {"name": "p1"}},
                {"number": 9, "kind": "pr", "title": "見る", "head": "feat/9", "outcome": "already_open", "path": None,
                 "account": None},
                {"number": 12, "kind": "issue", "title": "直したい", "head": "12-fix", "outcome": "assigned", "path": None,
                 "account": {"name": "p2"}}]
        got = report.lines(plan, {7: "sent", 12: "sent"}, ["使用率の控えが無い: p3"])
        self.assertEqual(got[0], "使用率の控えが無い: p3")
        self.assertEqual(len(got), 4)
        self.assertEqual(got[1], "#7 直す  feat/7  p1  sent")
        self.assertEqual(got[2], "#9 見る  feat/9  -  already_open")
        self.assertEqual(got[3], "issue #12 直したい  12-fix  p2  sent")


class Prs(unittest.TestCase):
    def test_read_runs_vendored_whose_turn_with_json(self):
        calls = []

        def runner(argv, env=None):
            calls.append(argv)
            return subprocess.CompletedProcess(argv, 0, json.dumps({"schema": 1, "prs": [{"number": 1}], "limited": [1, 7]}), "")

        self.assertEqual(prs_node.read("o/r", runner=runner), ([{"number": 1}], {1, 7}))
        self.assertTrue(pathlib.PurePath(calls[0][1]).as_posix().endswith("vendor/whose-turn.py"))
        self.assertEqual(calls[0][2:], ["--repo", "o/r", "--json"])

    def test_read_passes_env_to_whose_turn(self):
        seen = []

        def runner(argv, env=None):
            seen.append(env)
            return subprocess.CompletedProcess(argv, 0, json.dumps({"schema": 1, "prs": [], "limited": []}), "")

        self.assertEqual(prs_node.read("o/r", runner=runner, env={"GH_TOKEN": "t"}), ([], set()))
        self.assertEqual(seen, [{"GH_TOKEN": "t"}])

    def test_read_failure_raises(self):
        def runner(argv, env=None):
            return subprocess.CompletedProcess(argv, 1, "", "gh: not logged in")

        with self.assertRaises(prs_node.PrsError) as e:
            prs_node.read("o/r", runner=runner)
        self.assertIn("not logged in", str(e.exception))

    def test_read_without_a_list_of_numbers_in_limited_raises(self):
        # 無いのを空と読むと、取りこぼしの上の「自分の番でない」で会話を閉じる
        for limited in (None, "1", [1, "2"], [True]):
            with self.subTest(limited=limited):
                body = {"schema": 1, "prs": []} if limited is None else {"schema": 1, "prs": [], "limited": limited}

                def runner(argv, env=None, body=body):
                    return subprocess.CompletedProcess(argv, 0, json.dumps(body), "")

                with self.assertRaises(prs_node.PrsError) as e:
                    prs_node.read("o/r", runner=runner)
                self.assertIn("limited", str(e.exception))


def make_cfg(world=make_world):
    """(設定のパス, worktree の置き場) を返す。元の clone は gitx_source(設定のパス)。world は元の clone を作る関数（偽物の git の
    世界は fake_cfg）。"""
    src, root = world()
    return _write_cfg(src, root), root


def fake_cfg():
    """make_cfg と同じ形の設定を、偽物の git の世界（fakegit.world）の上に作る。(設定のパス, worktree の置き場, git の偽物)。"""
    g, src, root = fakegit.world()
    return _write_cfg(src, root), root, g


def _write_cfg(src, root):
    d = pathlib.Path(root).parent
    (d / "second.md").write_text("二手目", encoding="utf-8")
    (d / "c.toml").write_text(f"""
limits_dir = '{d}/limits'
accounts = [{{ name = "a1", command = "claude-a1", config_dir = '{d}/c1' }}]
[[repos]]
repo = "o/r"
second_prompt_file = '{d}/second.md'
source = '{src}'
copy_files = ["frontend/.env.local"]
""", encoding="utf-8")
    return str(d / "c.toml")


class FakeHerdr(WorktreeHerdr):
    """場所の口は本物の git worktree（WorktreeHerdr）、会話の口は手元の表。"""

    def __init__(self, fail_run_for=(), root=None, g=None):
        super().__init__(root, g)
        self._fail = set(fail_run_for)
        self.talking = set()   # 前に会話が居るペイン（/exit を受けるとシェルに戻る）
        self.busy = set()      # 前にシェルでない物（エディタ・dev server）が居るペイン
        self.exited = set()    # /exit を受けて会話が終わったペイン

    def run(self, pane, command):
        self.writes.append(("run", pane, command))
        if pane in self._fail:
            raise real_herdr.Error(["herdr", "pane", "run"], "pane_not_found")

    def shell_in_front(self, pane):
        return pane not in self.talking and pane not in self.busy

    def rename_pane(self, pane, label):
        self.writes.append(("rename_pane", pane, label))

    def rename_workspace(self, workspace, label):
        self.writes.append(("rename_workspace", workspace, label))

    def report_pane_metadata(self, pane, source, display_agent, title, tokens, clear_tokens=()):
        self.writes.append(("report_pane_metadata", pane, display_agent, title, dict(tokens), list(clear_tokens)))

    def report_workspace_metadata(self, workspace, source, tokens, clear_tokens=()):
        self.writes.append(("report_workspace_metadata", workspace, dict(tokens), list(clear_tokens)))

    def workspaces(self):
        return []   # 作業場の並びを見る試験は、並びを持つ偽物（test_company.CompanyHerdr など）で回す

    def move_workspace(self, workspace, index):
        self.writes.append(("move_workspace", workspace, index))

    screen = ""   # read が返す画面の終わり
    front = {}    # ペイン → 前で動いているコマンドの並び（foreground）。無ければ、会話が居ればその会話、居なければシェル

    def foreground(self, pane):
        return self.front.get(pane, ["claude"] if pane in self.talking else ["/bin/sh"])

    def send_keys(self, pane, *keys):
        self.writes.append(("send_keys", pane, *keys))

    def read(self, pane, lines, ansi=False):
        return self.screen

    def wait_ready(self, pane):
        return "idle"

    def agent(self, pane):
        return {"agent": "claude", "agent_status": "idle"}

    def prompt(self, target, text, wait, until=()):
        self.writes.append(("prompt", target, text, wait))
        if text == "/exit":
            self.talking.discard(target)
            self.exited.add(target)
            for p in self._panes:
                if p["pane_id"] == target:
                    p["agent"] = None
        return "idle" if wait else "sent"


# 試験の Ports が本物の herdr とログインのシェルを呼ばないための偽物（試験の中で上書きするものはそちらが勝つ）
QUIET = {"herdr_integration": lambda cdir: "current (v10)", "login_config_dir": lambda: None, "worktrees": lambda source: [],
         "task_flags": lambda: [], "tier_check": lambda launchers: {"schema": 1, "tier": 2, "ok": True, "missing": 0, "checks": []}}


def quiet_ports(**kw):
    return dispatch.Ports(**{**QUIET, **kw})


class FakePorts(dispatch.Ports):
    """本物の Ports の読む口のうち、claude・gh・whose-turn を偽物にする。git は本物（一時のフォルダ。git に偽物〔fakegit.FakeGit〕を
    渡せばその偽物）、herdr は偽物。"""

    def __init__(self, prs, problems=(), herdr=None, git=None):
        super().__init__(herdr_methods=lambda: set(), shell_has=lambda c: True, gh_ok=lambda repo, env=None: True, **QUIET)
        self._prs = prs
        self._limited = set()   # whose-turn の limited
        self._problems = list(problems)
        self.term = herdr or FakeHerdr(g=git)
        self.git = git or gitx
        self.gh = FakeGh(self)
        self.issues = {}
        self.source = None   # 元の clone（FakeGh が origin にブランチを作るのに使う）
        self.spawned = []   # 切り離して走らせたコマンド（argv・場所・出力のファイル・環境）。試験では走らせない

    def spawn(self, argv, cwd, log, env):
        self.spawned.append((argv, cwd, log, env))

    def preflight(self, cfg, task=False):
        self.preflight_task = task
        return list(self._problems), []

    def fetch_prs(self, repo):
        return self._prs, self._limited

    agents = ()   # claude agents --json の並び（アカウントを問わない）

    def list_sessions(self, config_dir, include_done=False):
        # 会話の行に "pane" が有れば、そのペインが /exit を受けた後は一覧から消える
        return [x for x in self.agents if x.get("pane") not in self.term.exited]

    acts = {}   # 番号 → PR の動き（無ければレビュアーが居て、動きの無い PR）

    def activity(self, repo, number):
        return self.acts.get(number, {"reviewers": True, "last_other": None})

    branch_prs = {}   # ブランチ → そのブランチの PR（{number, state, head_sha}。片付け）。"unknown" は読めない＝消さない。無ければ PR が無い

    def pr_for_branch(self, repo, branch):
        got = self.branch_prs.get(branch)
        if got == "unknown":
            raise clean.Unknown("読めない")
        return got

    def places(self, repo):
        return self.term.worktrees(repo.source)

    def pr_info(self, repo, number):
        return {**pr(number), "state": "OPEN", "fork": False}

    # issues: issue の番号 → {title, branches, prs}（インスタンスごと）

    def issue_info(self, repo, number):
        i = self.issues[number]
        return {"number": number, "title": i["title"], "url": f"i{number}", "state": i.get("state", "OPEN"),
                "prs": i.get("prs", [])}

    def issue_branches(self, repo, number):
        return list(self.issues[number].get("branches", []))

    def default_branch(self, repo):
        return "main"

    limits_seq = None  # 読むたびに 1 つずつ返す控え（None なら全部「控え無し」）

    def read_limits(self, limits_dir, names):
        if self.limits_seq:
            return self.limits_seq.pop(0)
        return {n: None for n in names}

    def refresh_limits(self, cfg, names):
        self.refreshed = getattr(self, "refreshed", []) + [list(names)]

    cost_history = {"seven_day": [], "five_hour": []}

    def load_cost(self, limits_dir):
        return self.cost_history

    def save_cost(self, limits_dir, samples):
        self.saved_cost = samples

    def now(self):
        return 0

    def cwd(self):
        # 打った場所は git の外（部署の回は設定の最初の repo を使う）。試験を走らせた場所のリポジトリに部署を立てない
        if not hasattr(self, "_cwd"):
            self._cwd = tempfile.mkdtemp(prefix="dispatch-cwd-")
        return self._cwd

    def pause(self):
        pass

    on_sleep = None   # --move --if-limited の待ちの間に起きることを、試験が差し込む（呼ぶたびに待った秒を渡す）

    def sleep(self, seconds):
        self.slept = getattr(self, "slept", []) + [seconds]
        if len(self.slept) > 5:
            raise AssertionError(f"--move --if-limited の待ちが終わらない（待った秒: {self.slept}）")
        if self.on_sleep:
            self.on_sleep(seconds)

    trust_outcome = "inherited"
    opened = None   # open_pages に渡された番号（呼ばれなければ None）

    def open_pages(self, repo, numbers):
        self.opened = list(numbers)
        return f"開いた: {numbers}" if numbers else None

    def catchup_command(self, config_dir):
        return "/attention:catchup"

    def trust(self, account, source, clone, others=()):
        self.term.writes.append(("trust", account["name"], source, clone))
        return self.trust_outcome

    trusted_dirs = ()   # 信頼済みのフォルダ（サブエージェントを起動するフォルダの確かめ）

    def trusted(self, account, folder):
        return folder in self.trusted_dirs


class FakeGh:
    """issue にブランチを結ぶ書く口の偽物。結ぶと、ports.issues のその issue にブランチが 1 本増え、origin にもブランチができる。
    merged は GitHub で main にマージ済みの PR を持つ commit（merged_pr_of が答える。既定は無し）。"""
    GhError = ghx.GhError

    def __init__(self, ports):
        self.ports = ports
        self.developed = []
        self.merged = {}   # commit → マージ済みの PR

    def env_for(self, user, base_env):
        return {**base_env, "GH_TOKEN": f"token-of-{user}"}

    def merged_pr_of(self, repo, sha, base, env=None):
        return self.merged.get(sha)

    def issue_develop(self, repo, number, base, env=None):
        self.developed.append((repo, number, base))
        name = f"{number}-fix"
        self.ports.issues[number].setdefault("branches", []).append(name)
        src, g = self.ports.source, self.ports.git
        if isinstance(g, fakegit.FakeGit):   # 手元の origin/<base> を origin の新しいブランチに push した形
            g.origin[name] = g.tracking[base]
            return
        subprocess.run(["git", "-C", src, "push", "-q", "origin", f"refs/remotes/origin/{base}:refs/heads/{name}"],
                       check=True, capture_output=True)

    def issue_branches(self, repo, number, env=None):
        return self.ports.issue_branches(None, number)


def gitx_source(cfg_path):
    return config.load(cfg_path, env={}).repos[0].source


def pr(n):
    return {"number": n, "title": f"t{n}", "head": f"feat/{n}", "url": f"u{n}", "role": "implementer", "days": 0}


def run_main(argv, ports):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = dispatch.main(argv, ports=ports)
    return rc, buf.getvalue()


def by_number(out):
    return {l.split()[0]: l for l in out.splitlines() if l.startswith("#")}


class Main(unittest.TestCase):
    """git（tests/fakegit.py）・herdr・claude・gh は偽物で回す。"""

    def setUp(self):
        self.cfg, self.root, self.g = fake_cfg()
        fakegit.forbid_real_git(self)

    def checkout(self, branch):
        """元の clone で git checkout -b <branch> origin/<branch> した形。"""
        self.g.local[branch] = self.g.tracking[branch]
        self.g.heads[self.g.source] = branch

    def test_usage_is_refreshed_before_and_after_and_the_cost_is_learned(self):
        # 全部の PR は同時に走るので、始める前の使用率で件数を決め、/catchup が終わった後の使用率との差で 1 件あたりを覚える
        ports = FakePorts([pr(1), pr(2)], git=self.g)
        win = lambda u: {"used_percentage": u, "resets_at": 10**10}
        ports.limits_seq = [{"a1": {"seven_day": win(40), "five_hour": win(5)}},
                            {"a1": {"seven_day": win(41), "five_hour": win(9)}}]
        rc, out = run_main(["--config", self.cfg], ports)
        self.assertEqual(rc, 0, out)
        self.assertEqual(ports.refreshed, [["a1"], ["a1"]])
        self.assertEqual(ports.saved_cost, {"seven_day": [1.0], "five_hour": [2.5]})
        self.assertIn("1 件あたりの使用率をまだ測っていない", out)

    def test_sent_pages_are_opened_once_after_all_are_sent(self):
        # 起動した会話には開かせない（ATTENTION_CATCHUP_OPEN=0）ので、送り終えた件のページを dispatch が 1 回開く
        ports = FakePorts([pr(1), pr(2)], git=self.g)
        rc, out = run_main(["--config", self.cfg], ports)
        self.assertEqual(rc, 0, out)
        self.assertEqual(sorted(ports.opened), [1, 2])
        self.assertIn("開いた: ", out)

    def test_dry_run_opens_nothing(self):
        ports = FakePorts([pr(1)], git=self.g)
        run_main(["--config", self.cfg, "--dry-run"], ports)
        self.assertIsNone(ports.opened)

    def test_measured_cost_is_named_in_the_report(self):
        ports = FakePorts([pr(1)], git=self.g)
        ports.cost_history = {"seven_day": [0.5, 0.7, 0.9], "five_hour": [2.0]}
        rc, out = run_main(["--config", self.cfg, "--dry-run"], ports)
        self.assertIn("1 件あたりの使用率の見積もり（3 回の測りの中央値）: 週 0.7%・5 時間 2.0%", out)

    def test_account_with_fewer_running_conversations_goes_first(self):
        # 使用率が同じ（ここでは控えが無い）なら、動いている会話の少ないアカウントに先に配る。a0 は設定の順では先だが、会話が 2 件動いている
        d = pathlib.Path(self.cfg).parent
        text = pathlib.Path(self.cfg).read_text(encoding="utf-8").replace(
            "accounts = [", f"accounts = [{{ name = \"a0\", command = \"claude-a0\", config_dir = '{d}/c0' }}, ", 1)
        pathlib.Path(self.cfg).write_text(text, encoding="utf-8")
        ports = FakePorts([pr(1)], git=self.g)
        busy = {f"{d}/c0": [{"cwd": "/elsewhere", "state": "working"}, {"cwd": "/elsewhere2", "status": "busy"}]}
        ports.list_sessions = lambda cdir: busy.get(cdir, [])
        ports.origin = ports.branch = lambda cwd: None
        rc, out = run_main(["--config", self.cfg, "--dry-run"], ports)
        self.assertEqual(rc, 0, out)
        self.assertIn(" a1 ", by_number(out)["#1"])

    def test_dry_run_does_not_ask_for_fresh_usage(self):
        ports = FakePorts([pr(1)], git=self.g)
        run_main(["--config", self.cfg, "--dry-run"], ports)
        self.assertFalse(hasattr(ports, "refreshed"))
        self.assertFalse(hasattr(ports, "saved_cost"))

    def test_dry_run_writes_nothing_and_says_create_or_reuse(self):
        src = gitx_source(self.cfg)
        self.g.add_worktree(f"{self.root}/feat-2", "feat/2", "origin/feat/2")
        self.checkout("feat/3")
        ports = FakePorts([pr(1), pr(2), pr(3)], git=self.g)
        rc, out = run_main(["--config", self.cfg, "--dry-run"], ports)
        self.assertEqual(rc, 0)
        self.assertEqual(ports.term.writes, [])
        self.assertEqual(len(ports.term.worktrees(src)), 2)
        lines = by_number(out)
        self.assertTrue(lines["#1"].endswith("create"))
        self.assertTrue(lines["#2"].endswith("reuse"))
        self.assertTrue(lines["#3"].endswith("branch_busy"))

    def test_preflight_problem_stops_before_anything(self):
        ports = FakePorts([pr(1)], problems=["herdr に届かない"], git=self.g)
        rc, out = run_main(["--config", self.cfg], ports)
        self.assertEqual(rc, 2)
        self.assertEqual(ports.term.writes, [])
        self.assertIn("herdr に届かない", out)

    def test_unreadable_prs_stop_with_one_line_not_a_traceback(self):
        ports = FakePorts([], git=self.g)

        def boom(repo):
            raise prs_node.PrsError("whose-turn --json（o/r）が読めない: Could not resolve")
        ports.fetch_prs = boom
        rc, out = run_main(["--config", self.cfg], ports)
        self.assertEqual(rc, 1)
        self.assertIn("止めた: whose-turn --json（o/r）が読めない", out)
        self.assertEqual(ports.term.writes, [])

    def test_no_prs_does_nothing(self):
        ports = FakePorts([], git=self.g)
        rc, out = run_main(["--config", self.cfg], ports)
        self.assertEqual((rc, ports.term.writes), (0, []))
        self.assertIn("自分の番の PR は無い", out)

    def test_creates_the_branch_place_then_launches_and_sends_two_turns(self):
        ports = FakePorts([pr(1)], git=self.g)
        rc, out = run_main(["--config", self.cfg], ports)
        self.assertEqual(rc, 0)
        place = [w for w in ports.term.worktrees(gitx_source(self.cfg)) if w["linked"]]
        self.assertEqual([w["branch"] for w in place], ["feat/1"])
        path = place[0]["path"]
        self.assertEqual(ports.term.writes, [
            ("create_worktree", "feat/1", "r/feat/1"),
            ("trust", "a1", gitx_source(self.cfg), path),
            ("run", "P0", typed("claude-a1")),
            ("prompt", "P0", "/attention:catchup 1", True),
            ("prompt", "P0", turn.with_carry("二手目", "/attention:catchup"), False),
        ])
        self.assertTrue(by_number(out)["#1"].endswith("sent"))

    def test_a_new_pr_place_drops_the_desk_attrs_git_copied_from_the_head_office(self):
        # git worktree add は本社の config.worktree を写す。残ると、PR の会話が窓口の役の本文を受けて窓口として振る舞った（3d3ccc）
        src = gitx_source(self.cfg)
        provision.mark(src, src, {"role": "窓口", "name": "窓口", "session": "s-desk", "pid": "777"}, self.g)
        ports = FakePorts([pr(1)], git=self.g)
        rc, out = run_main(["--config", self.cfg], ports)
        self.assertEqual(rc, 0, out)
        place = next(w["path"] for w in ports.term.worktrees(src) if w["linked"])
        self.assertEqual(self.g.worktree_attrs(place, copies=True), {})   # 写しは読み飛ばすだけでなく、消す
        self.assertEqual(self.g.worktree_attrs(src)["role"], "窓口")

    def test_untrusted_source_still_launches_and_says_the_dialog_will_show(self):
        ports = FakePorts([pr(1)], git=self.g)
        ports.trust_outcome = "source_untrusted"
        rc, out = run_main(["--config", self.cfg, "--no-second"], ports)
        self.assertEqual(rc, 0)
        self.assertIn("#1: どのアカウントも元の clone を信頼していないので、Claude Code がフォルダの信頼の確認を出す", out)
        self.assertIn(("run", "P0", typed("claude-a1")), ports.term.writes)

    def test_no_second_sends_only_catchup(self):
        ports = FakePorts([pr(1)], git=self.g)
        rc, out = run_main(["--config", self.cfg, "--no-second"], ports)
        self.assertEqual(rc, 0)
        self.assertEqual([w for w in ports.term.writes if w[0] == "prompt"], [("prompt", "P0", "/attention:catchup 1", False)])
        self.assertTrue(by_number(out)["#1"].endswith("sent"))

    def test_pr_opens_only_the_named_prs_without_whose_turn(self):
        ports = FakePorts([pr(1), pr(2)], git=self.g)
        ports.fetch_prs = lambda repo: self.fail("--pr では whose-turn を呼ばない")
        ports.pr_info = lambda repo, n: pr(n)
        rc, out = run_main(["--config", self.cfg, "--pr", "5", "--dry-run"], ports)
        self.assertEqual(rc, 0)
        self.assertEqual(list(by_number(out)), ["#5"])

    def test_pr_that_cannot_be_read_stops_with_one_line(self):
        ports = FakePorts([], git=self.g)

        def no_pr(repo, n):
            raise ghx.GhError(f"#{n} を読めない")
        ports.pr_info = no_pr
        rc, out = run_main(["--config", self.cfg, "--pr", "99999"], ports)
        self.assertEqual(rc, 1)
        self.assertIn("止めた: #99999 を読めない", out)
        self.assertEqual(ports.term.writes, [])

    def test_fork_pr_from_the_list_is_provision_failed_and_nothing_is_made(self):
        ports = FakePorts([pr(1)], git=self.g)
        ports.pr_info = lambda repo, n: {**pr(n), "state": "OPEN", "fork": True}
        rc, out = run_main(["--config", self.cfg], ports)
        self.assertTrue(by_number(out)["#1"].endswith("provision_failed"), out)
        self.assertIn("fork の PR", out)
        self.assertEqual(ports.term.writes, [])

    def test_branch_open_in_the_source_clone_is_branch_busy(self):
        src = gitx_source(self.cfg)
        self.checkout("feat/1")
        ports = FakePorts([pr(1)], git=self.g)
        rc, out = run_main(["--config", self.cfg], ports)
        self.assertTrue(by_number(out)["#1"].endswith("branch_busy"), out)
        self.assertEqual(ports.term.writes, [])
        self.assertEqual(self.g.branch(src), "feat/1")

    def test_one_launch_failure_does_not_stop_the_other(self):
        ports = FakePorts([pr(1), pr(2)], herdr=FakeHerdr(fail_run_for={"P0"}, g=self.g), git=self.g)
        rc, out = run_main(["--config", self.cfg], ports)
        self.assertEqual(rc, 0)
        lines = by_number(out)
        self.assertTrue(lines["#1"].endswith("launch_failed"))
        self.assertTrue(lines["#2"].endswith("sent"))
        self.assertIn(("prompt", "P1", "/attention:catchup 2", True), ports.term.writes)


class Issue(unittest.TestCase):
    """--issue N: issue に結んだブランチの場所を開き、1 ターン目の /catchup N まで送って止める。git（tests/fakegit.py）も偽物で回す。"""

    def setUp(self):
        self.cfg, self.root, self.g = fake_cfg()
        fakegit.forbid_real_git(self)

    def ports(self, **issue):
        ports = FakePorts([], git=self.g)
        ports.fetch_prs = lambda repo: self.fail("--issue では whose-turn を呼ばない")
        ports.source = gitx_source(self.cfg)
        ports.issues = {12: {"title": "ログインを直す", **issue}}
        return ports

    def line(self, out):
        return next(l for l in out.splitlines() if l.startswith("issue #12 "))

    def test_linked_branch_is_opened_and_only_the_first_turn_is_sent(self):
        ports = self.ports(branches=["feat/5", "feat/6"])
        rc, out = run_main(["--config", self.cfg, "--issue", "12"], ports)
        self.assertEqual(rc, 0, out)
        self.assertEqual(self.line(out), "issue #12 ログインを直す  feat/5  a1  sent")
        self.assertEqual([w for w in ports.term.writes if w[0] == "prompt"], [("prompt", "P0", "/attention:catchup 12", False)])
        self.assertIn("ほかにも有る（使ったのは feat/5）: feat/6", out)
        self.assertEqual(ports.gh.developed, [])
        self.assertFalse(hasattr(ports, "saved_cost"))   # 待たずに送った件では 1 件あたりの使用率を測らない

    def test_without_a_linked_branch_one_is_made_from_the_default_branch_and_read_back(self):
        ports = self.ports()
        rc, out = run_main(["--config", self.cfg, "--issue", "12"], ports)
        self.assertEqual(ports.gh.developed, [("o/r", 12, "main")])
        self.assertEqual(self.line(out), "issue #12 ログインを直す  12-fix  a1  sent")
        self.assertIn(("create_worktree", "12-fix", "r/12-fix"), ports.term.writes)

    def test_branch_replaced_by_its_pr_is_found_through_the_pr(self):
        # issue に結んだブランチから PR を作ると、GitHub はブランチの結びつきを PR に置き換える。ブランチを作り直さず、PR のブランチを使う
        ports = self.ports(prs=[3])
        rc, out = run_main(["--config", self.cfg, "--issue", "12"], ports)
        self.assertEqual(ports.gh.developed, [])
        self.assertEqual(self.line(out), "issue #12 ログインを直す  feat/3  a1  sent")

    def test_dry_run_makes_no_branch(self):
        ports = self.ports()
        rc, out = run_main(["--config", self.cfg, "--issue", "12", "--dry-run"], ports)
        self.assertEqual(ports.gh.developed, [])
        self.assertEqual(ports.term.writes, [])
        self.assertEqual(self.line(out), "issue #12 ログインを直す  -  a1  create")
        self.assertIn("gh issue develop", out)

    def test_closed_issue_gets_no_branch_and_stops(self):
        ports = self.ports(state="CLOSED")
        rc, out = run_main(["--config", self.cfg, "--issue", "12"], ports)
        self.assertEqual(rc, 0)
        self.assertEqual(self.line(out), "issue #12 ログインを直す  -  -  issue_closed")
        self.assertEqual(ports.gh.developed, [])
        self.assertEqual(ports.term.writes, [])

    def test_issue_and_pr_together_stop(self):
        rc, out = run_main(["--config", self.cfg, "--issue", "12", "--pr", "1"], self.ports())
        self.assertEqual(rc, 2)
        self.assertIn("--issue と --pr は一緒に使えない", out)

    def test_issue_does_not_tidy(self):
        ports = self.ports(branches=["feat/5"])
        ports.pr_for_branch = lambda repo, b: self.fail("--issue では片付けない")
        rc, out = run_main(["--config", self.cfg, "--issue", "12"], ports)
        self.assertEqual(rc, 0, out)


class RealPorts(unittest.TestCase):
    def test_real_trust_writes_in_the_accounts_config_file(self):
        d = pathlib.Path(tempfile.mkdtemp())
        (d / ".claude.json").write_text(json.dumps({"projects": {"/s": {"hasTrustDialogAccepted": True}}}))
        ports = dispatch.Ports(env={"HOME": "/nowhere"})
        self.assertEqual(ports.trust({"name": "p2", "config_dir": str(d)}, "/s", "/s-pr-1"), "inherited")
        # 鍵は記号のリンクを解いた形を、元の鍵（/s）の区切りに揃えた物（Windows では解くとドライブ名が付き D:/s-pr-1 になる）
        key = os.path.realpath("/s-pr-1").replace(os.sep, "/")
        self.assertTrue(json.loads((d / ".claude.json").read_text())["projects"][key]["hasTrustDialogAccepted"])

    def test_real_trust_carries_the_source_mark_over_from_another_account(self):
        mine, other = pathlib.Path(tempfile.mkdtemp()), pathlib.Path(tempfile.mkdtemp())
        (mine / ".claude.json").write_text(json.dumps({"projects": {}}))
        (other / ".claude.json").write_text(json.dumps({"projects": {"/s": {"hasTrustDialogAccepted": True}}}))
        ports = dispatch.Ports(env={"HOME": "/nowhere"})
        others = [config.Account("p1", "claude-p1", str(other)), config.Account("p2", "claude-p2", str(mine))]
        self.assertEqual(ports.trust({"name": "p2", "config_dir": str(mine)}, "/s", "/s-pr-1", others), "inherited")
        self.assertTrue(claudex.is_trusted(str(mine / ".claude.json"), "/s"))
        self.assertTrue(claudex.is_trusted(str(mine / ".claude.json"), "/s-pr-1"))

    def test_account_without_config_dir_follows_a_fresh_login_shell_not_this_session(self):
        # dispatch はふつう、別のアカウントの Claude Code の会話の中から走る。その会話の CLAUDE_CONFIG_DIR は、
        # 作業場のペインで起動する config_dir 無しのアカウントのフォルダではない。ペインの新しいログインのシェルが持つ値を使う
        session = {"HOME": "/h", "CLAUDE_CONFIG_DIR": "/h/.claude-p2"}
        ports = quiet_ports(env=session, login_config_dir=lambda: None)
        self.assertEqual(claudex.trust_file(None, ports.account_env), os.path.join("/h", ".claude.json"))
        self.assertEqual(config.effective_config_dir(config.Account("main", "claude"), ports.account_env),
                         str(pathlib.Path("/h", ".claude")))
        ports = quiet_ports(env=session, login_config_dir=lambda: "/h/.claude-mine")
        self.assertEqual(config.effective_config_dir(config.Account("main", "claude"), ports.account_env), "/h/.claude-mine")
        self.assertEqual(session["CLAUDE_CONFIG_DIR"], "/h/.claude-p2")  # 渡した環境は壊さない

    def test_login_config_dir_reads_only_the_marked_value(self):
        # ログインのシェルは、起動のときに挨拶などを出すことがある。印で挟んだ所だけを読む。今の会話の値は渡さない
        seen = []

        def run(argv, **kw):
            seen.append(kw["env"])
            return subprocess.CompletedProcess(argv, 0, "welcome!\n@@CLAUDE_CONFIG_DIR=/h/.claude-x@@\n", "")
        argv = []

        def run2(a, **kw):
            argv.append(a)
            return run(a, **kw)
        self.assertEqual(wiring._login_config_dir({"SHELL": "/bin/zsh", "CLAUDE_CONFIG_DIR": "/h/.claude-p2"}, run2, posix=True),
                         "/h/.claude-x")
        self.assertNotIn("CLAUDE_CONFIG_DIR", seen[0])
        # ペインのシェルと同じく、ログインのシェルの設定（.zprofile・.bash_profile）も、対話のシェルの設定も読ませる
        self.assertEqual(argv[0][:2], ["/bin/zsh", "-lic"])

        def empty(argv, **kw):
            return subprocess.CompletedProcess(argv, 0, "@@CLAUDE_CONFIG_DIR=@@\n", "")
        self.assertIsNone(wiring._login_config_dir({}, empty))

    def test_without_a_posix_shell_commands_are_looked_up_on_path(self):
        # Windows（herdr の native 版）には -lic で起動する POSIX のシェルが無い。PATH の上で探す
        def boom(*a, **kw):
            raise AssertionError("シェルを起動した")
        self.assertTrue(wiring._shell_has("claude-p1", env={}, runner=boom, which=lambda c: "C:/bin/" + c, posix=False))
        self.assertFalse(wiring._shell_has("claude-p1", env={}, runner=boom, which=lambda c: None, posix=False))

    def test_without_a_posix_shell_the_pane_uses_the_default_folder(self):
        def boom(*a, **kw):
            raise AssertionError("シェルを起動した")
        self.assertIsNone(wiring._login_config_dir({"CLAUDE_CONFIG_DIR": "/h/.claude-p2"}, boom, posix=False))

    def test_gone_plugin_paths_with_backslashes_are_found(self):
        gone = r"C:\Users\me\.claude\plugins\cache\m\works-dispatch\0.1.0\dispatch\limits.py"
        self.assertEqual(wiring.gone_plugin_paths([f'command = "py {gone} --accounts x show a"']), [(gone, "もう無い")])

    def test_gone_plugin_paths_inside_escaped_json_and_toml_strings_are_read_unescaped(self):
        # settings.json と herdr の TOML は、文字列の中の \ を \\ と書く。書かれた形のままでは、パスが別物になる
        gone = r"C:\Users\me\.claude\plugins\cache\m\works-dispatch\0.1.0\dispatch\activity.py"
        d = pathlib.Path(tempfile.mkdtemp())
        (d / "settings.json").write_text(json.dumps({"hooks": {"Stop": [{"hooks": [{"command": f"py {gone}"}]}]}}), encoding="utf-8")
        (d / "config.toml").write_text('[ui]\ntab_bar_right = [{ command = "py %s" }]\n' % gone.replace("\\", "\\\\"), encoding="utf-8")
        for f in ("settings.json", "config.toml"):
            with self.subTest(f=f):
                self.assertEqual(wiring.gone_plugin_paths(wiring.setting_strings(d / f)), [(gone, "もう無い")])
        (d / "broken.toml").write_text(f'{{ command = "py {gone}" }},\n', encoding="utf-8")
        self.assertEqual(wiring.gone_plugin_paths(wiring.setting_strings(d / "broken.toml")), [(gone, "もう無い")])  # 読めない形はそのまま
        self.assertEqual(wiring.setting_strings(d / "missing.json"), [])

    def test_plugin_notes_name_install_records_pointing_at_gone_folders(self):
        # 2026-10-18、~/.claude-p2 の控えに、消えた置き場（gates 0.7.0・attention 0.10.1）を指す project の範囲の項目が残っていた
        cfg = pathlib.Path(tempfile.mkdtemp())
        here = cfg / "plugins" / "cache" / "m" / "gates" / "0.8.0"
        here.mkdir(parents=True)
        (cfg / "plugins" / "installed_plugins.json").write_text(json.dumps({"version": 2, "plugins": {
            "gates@m": [{"scope": "user", "installPath": str(here)},
                        {"scope": "project", "projectPath": "/r/x", "installPath": str(cfg / "plugins" / "cache" / "m" / "gates" / "0.7.0")}]}}),
            encoding="utf-8")
        notes = wiring.plugin_notes(cfg / "none.toml", [str(cfg)])
        self.assertEqual(len(notes), 1, notes)
        self.assertIn("gates@m（project）", notes[0])

    def test_plugin_notes_name_a_tab_bar_entry_that_was_removed(self):
        # ~/.cache が掃除されて写した入口が消えると、タブバーの表示と使用率の取り直しが黙って止まる
        d = pathlib.Path(tempfile.mkdtemp())
        (d / "run-python.sh").write_text("")
        toml = d / "config.toml"
        toml.write_text(f'command = "sh {d / "run-python.sh"} {d / "limits-entry.py"} show a"\n', encoding="utf-8")
        notes = wiring.plugin_notes(toml, [])
        self.assertEqual(len(notes), 1, notes)
        self.assertIn(f"入口 {d / 'limits-entry.py'} が無い", notes[0])

    def test_gone_plugin_paths_finds_orphaned_and_not_installed_versions(self):
        # 2026-10-18、herdr のタブバーが .orphaned_at の付いた 0.1.3 を呼び続けていた。在るうちは「もう無い」で見つからない
        cache = pathlib.Path(tempfile.mkdtemp()) / "plugins" / "cache" / "m" / "works-dispatch"
        for v in ("0.1.3", "0.2.0", "0.3.0"):
            (cache / v / "dispatch").mkdir(parents=True)
            (cache / v / "dispatch" / "limits.py").write_text("")
        (cache / "0.1.3" / ".orphaned_at").write_text("1")
        texts = [f"py {cache / v / 'dispatch' / 'limits.py'}" for v in ("0.1.3", "0.2.0", "0.3.0")]
        got = dict(wiring.gone_plugin_paths(texts, installed=[str(cache / "0.3.0")]))
        self.assertIn("前の版", got[str(cache / "0.1.3" / "dispatch" / "limits.py")])
        self.assertEqual(got[str(cache / "0.2.0" / "dispatch" / "limits.py")], "今入っていない版")
        self.assertNotIn(str(cache / "0.3.0" / "dispatch" / "limits.py"), got)
        self.assertEqual([p for p, _ in wiring.gone_plugin_paths(texts)], [str(cache / "0.1.3" / "dispatch" / "limits.py")])  # 入っている場所が分からなければ版では比べない

    def test_real_ports_carry_the_herdr_and_git_modules(self):
        # 偽物の Ports は herdr と git を自分で持つので、本物から消えても Main の試験は通ってしまう
        ports = dispatch.Ports()
        self.assertIs(ports.term, real_herdr)
        self.assertIs(ports.git, gitx)


class Preflight(unittest.TestCase):
    def test_reports_missing_herdr_methods_command_attention_source_and_notes_limits(self):
        cfg_path, root = make_cfg()
        cfg = config.load(cfg_path, env={})
        ports = quiet_ports(herdr_methods=lambda: {"pane.list"}, shell_has=lambda cmd: False, gh_ok=lambda repo, env=None: True)
        problems, notes = ports.preflight(cfg)
        text = "\n".join(problems)
        self.assertIn("agent.prompt", text)
        self.assertIn("claude-a1", text)
        self.assertIn("アカウント a1", text)
        self.assertIn("catchup", text)
        self.assertNotIn("元の clone", text)  # 元の clone は o/r の clone なので通る
        self.assertIn("a1", "\n".join(notes))  # 控えが無いのは止めずに 1 行

    def test_task_needs_pane_names_and_background_flags_but_not_catchup(self):
        # 部署の回は /catchup と 2 ターン目の文を見ず、ペインの名前と札（pane.rename・pane.report_metadata）と、裏の会話を起動する
        # claude の旗（--name・--bg・--settings）を見る。ほかの回では、それらは注記にとどめる（PR を開くのには要らない）
        cfg_path, root = make_cfg()
        cfg = config.load(cfg_path, env={})
        cfg = cfg._replace(repos=tuple(r._replace(second_prompt="") for r in cfg.repos))
        ports = quiet_ports(herdr_methods=lambda: wiring.HERDR_METHODS, shell_has=lambda c: True,
                            gh_ok=lambda repo, env=None: True, task_flags=lambda: ["--bg"])
        problems, notes = ports.preflight(cfg, task=True)
        text = "\n".join(problems)
        for word in ("pane.rename", "pane.report_metadata", "--bg"):
            self.assertIn(word, text)
        self.assertNotIn("catchup", text)
        self.assertNotIn("2 ターン目", text)
        problems, notes = ports.preflight(cfg)
        self.assertNotIn("--bg", "\n".join(problems))
        self.assertIn("--bg", "\n".join(notes))
        self.assertIn("pane.rename", "\n".join(notes))
        self.assertIn("catchup", "\n".join(problems))

    def test_spaces_rows_without_kind_stop_the_department_run_with_the_rows_to_add(self):
        # 部署の作業場の行に永続か tmp かの印（$kind）を出すのは herdr の設定の前提。無ければ部署の回は止め、足す行を出す。
        # ほかの回（PR を開く）では注記にとどめる
        cfg_path, root = make_cfg()
        cfg = config.load(cfg_path, env={})
        home = pathlib.Path(root).parent / "home"
        herdr_cfg = home / ".config" / "herdr" / "config.toml"
        herdr_cfg.parent.mkdir(parents=True)
        ports = quiet_ports(herdr_methods=lambda: wiring.HERDR_METHODS | wiring.TASK_HERDR_METHODS, shell_has=lambda c: True,
                            gh_ok=lambda repo, env=None: True, env={"HOME": str(home)})
        for text in ("", '[ui.sidebar.spaces]\nrows = [["state_icon", "workspace"]]\n'):
            herdr_cfg.write_text(text, encoding="utf-8")
            problems, notes = ports.preflight(cfg, task=True)
            self.assertIn(wiring.SPACES_ROWS, "\n".join(problems))
            problems, notes = ports.preflight(cfg)
            self.assertNotIn("$kind", "\n".join(problems))
            self.assertIn("$kind", "\n".join(notes))
        for row in ('"$kind"', '{ token = "$kind", fg = "#a6e3a1" }'):
            herdr_cfg.write_text(f'[ui.sidebar.spaces]\nrows = [["state_icon", "workspace", {row}], ["branch"]]\n', encoding="utf-8")
            problems, notes = ports.preflight(cfg, task=True)
            self.assertNotIn("$kind", "\n".join(problems + notes))
        # 足す行は、そのまま足せば前提を満たす
        herdr_cfg.write_text(wiring.SPACES_ROWS + "\n", encoding="utf-8")
        self.assertTrue(wiring.spaces_show_kind(herdr_cfg))
        self.assertFalse(wiring.spaces_show_kind(home / "missing.toml"))

    def test_account_without_usage_window_gets_no_missing_limits_note(self):
        cfg_path, root = make_cfg()
        cfg = config.load(cfg_path, env={})
        cfg = cfg._replace(accounts=tuple(a._replace(limits=False) for a in cfg.accounts))
        ports = quiet_ports(herdr_methods=lambda: {"pane.list"}, shell_has=lambda cmd: False, gh_ok=lambda repo, env=None: True)
        problems, notes = ports.preflight(cfg)
        self.assertNotIn("使用率の控え", "\n".join(notes))

    def test_missing_herdr_integration_is_a_note_with_the_install_command(self):
        # Claude Code の作業中の判定は herdr が画面から読むので、連携のフックが無くても動く。フックは会話の識別子を herdr に渡し、
        # herdr を立ち上げ直したときの会話の再開に使われる。止めずに、入れるコマンドを 1 行出す
        cfg_path, root = make_cfg()
        cfg = config.load(cfg_path, env={})
        cfg = cfg._replace(accounts=cfg.accounts + (config.Account("a2", "claude-a2", f"{root}/c2"),))
        ports = quiet_ports(herdr_methods=lambda: {"pane.list"}, shell_has=lambda cmd: True, gh_ok=lambda repo, env=None: True,
                               herdr_integration=lambda cdir: "current (v10)" if cdir.endswith("c2") else "not installed")
        problems, notes = ports.preflight(cfg)
        text = "\n".join(notes)
        cdir = config.effective_config_dir(cfg.accounts[0], {})
        self.assertIn(wiring.env_command("CLAUDE_CONFIG_DIR", cdir, "herdr integration install claude"), text)
        self.assertNotIn("integration", "\n".join(problems))
        self.assertEqual(text.count("integration install"), 1)

    def test_herdr_and_hook_settings_pointing_at_a_gone_plugin_folder_are_noted(self):
        # タブバーの行とサイドバーのフックは、プラグインの入った場所（版ごとのフォルダ）を指す。更新で消えると、
        # herdr はフィールドを黙って消し、フックは黙って何もしなくなるので、始める前の確かめで見つける
        cfg_path, root = make_cfg()
        cfg = config.load(cfg_path, env={})
        home = pathlib.Path(root).parent / "home"
        live = pathlib.Path(root) / "plugin" / "1.1.0" / "dispatch"
        live.mkdir(parents=True)
        (live / "limits.py").write_text("")
        gone = pathlib.Path(root) / "plugin" / "1.0.0" / "dispatch"
        herdr_cfg = home / ".config" / "herdr" / "config.toml"
        herdr_cfg.parent.mkdir(parents=True)
        herdr_cfg.write_text(f'{{ command = "python3 {live}/limits.py --config x show a" }},\n'
                             f'{{ command = "python3 {gone}/limits.py --config x probe" }},\n')
        settings = pathlib.Path(cfg.accounts[0].config_dir) / "settings.json"
        settings.parent.mkdir(parents=True, exist_ok=True)
        settings.write_text(json.dumps({"hooks": {"Stop": [{"hooks": [{"command": f"python3 {gone}/activity.py"}]}]}}))
        ports = quiet_ports(herdr_methods=lambda: wiring.HERDR_METHODS, shell_has=lambda c: True,
                            gh_ok=lambda repo, env=None: True, env={"HOME": str(home)})
        problems, notes = ports.preflight(cfg)
        text = "\n".join(notes)
        self.assertIn(f"{gone}/limits.py", text)
        self.assertIn(f"{gone}/activity.py", text)
        self.assertNotIn(f"{live}/limits.py", text)

    def test_single_account_user_is_checked_in_the_default_folder(self):
        cfg_path, root = make_cfg()
        cfg = config.load(cfg_path, env={})
        home = pathlib.Path(root).parent / "home"
        plugin = home / ".claude" / "plugins" / "cache" / "attention" / "1.0.0"
        (plugin / ".claude-plugin").mkdir(parents=True)
        (plugin / ".claude-plugin" / "plugin.json").write_text(json.dumps({"name": "attention"}))
        (plugin / "skills" / "catchup").mkdir(parents=True)
        (plugin / "skills" / "catchup" / "SKILL.md").write_text("")
        (home / ".claude" / "plugins" / "installed_plugins.json").write_text(
            json.dumps({"plugins": {"attention@x": [{"scope": "user", "installPath": str(plugin)}]}}))
        cfg = cfg._replace(accounts=(config.Account("default", "claude", None),))
        ports = quiet_ports(herdr_methods=lambda: wiring.HERDR_METHODS, shell_has=lambda c: True, gh_ok=lambda repo, env=None: True,
                               env={"HOME": str(home)})
        problems, notes = ports.preflight(cfg)
        self.assertNotIn("catchup", "\n".join(problems))
        self.assertNotIn("catchup", "\n".join(notes))

    def test_repo_that_gh_cannot_read_is_a_problem(self):
        cfg_path, root = make_cfg()
        cfg = config.load(cfg_path, env={})
        asked = []
        ports = quiet_ports(herdr_methods=lambda: wiring.HERDR_METHODS, shell_has=lambda c: True,
                               gh_ok=lambda repo, env=None: asked.append(repo) or False)
        problems, _ = ports.preflight(cfg)
        self.assertEqual(asked, ["o/r"])
        self.assertIn("gh が o/r を読めない", "\n".join(problems))

    def test_gh_check_uses_the_repos_gh_user_token(self):
        cfg_path, root = make_cfg()
        cfg = config.load(cfg_path, env={})
        cfg = cfg._replace(repos=(cfg.repos[0]._replace(gh_user="me-at-work"),))
        seen = []
        ports = quiet_ports(herdr_methods=lambda: wiring.HERDR_METHODS, shell_has=lambda c: True,
                               gh_ok=lambda repo, env=None: seen.append(env) or True,
                               gh_env=lambda repo: {"GH_TOKEN": f"token-of-{repo.gh_user}"})
        problems, _ = ports.preflight(cfg)
        self.assertEqual(seen, [{"GH_TOKEN": "token-of-me-at-work"}])
        # 一時のフォルダの名前に gh の 2 文字が混ざることがあるので、gh の問題の文の形で見る
        self.assertEqual([p for p in problems if p.startswith("gh ") or "gh が" in p or "gh のアカウント" in p], [])

    def test_gh_user_without_a_token_is_a_problem(self):
        cfg_path, root = make_cfg()
        cfg = config.load(cfg_path, env={})

        def no_token(repo):
            raise ghx.GhError("gh のアカウント me-at-work の鍵を取り出せない")
        ports = quiet_ports(herdr_methods=lambda: wiring.HERDR_METHODS, shell_has=lambda c: True,
                               gh_ok=lambda repo, env=None: True, gh_env=no_token)
        problems, _ = ports.preflight(cfg)
        self.assertIn("gh のアカウント me-at-work の鍵を取り出せない", "\n".join(problems))

    def test_source_trusted_by_no_account_is_noted(self):
        cfg_path, root = make_cfg()
        cfg = config.load(cfg_path, env={})
        cfg = cfg._replace(accounts=cfg.accounts + (config.Account("a2", "claude-a2", f"{root}/c2"),))
        cdirs = [pathlib.Path(a.config_dir) for a in cfg.accounts]
        for cdir in cdirs:
            cdir.mkdir(parents=True, exist_ok=True)
            (cdir / ".claude.json").write_text(json.dumps({"projects": {}}))
        ports = quiet_ports(herdr_methods=lambda: wiring.HERDR_METHODS, shell_has=lambda c: True,
                               gh_ok=lambda repo, env=None: True)
        _, notes = ports.preflight(cfg)
        self.assertIn(f"どのアカウントも {cfg.repos[0].source} を信頼していない", "\n".join(notes))
        # 画面で起動できない会話にも手を示す: 手で書く信頼の印の置き場と鍵（Claude Code の文書の形。works-factory の会社の受付 6ea42d）。
        # 置き場は設定の字に足した形のまま出す（Windows では / と \ が混じる）
        self.assertIn(f'{os.path.join(cfg.accounts[0].config_dir, ".claude.json")} の projects["{os.path.realpath(cfg.repos[0].source)}"].hasTrustDialogAccepted を true にする',
                      "\n".join(notes))
        # どれか 1 つのアカウントが信頼していれば、ほかのアカウントには作業場を作るときに広げるので知らせない
        (cdirs[-1] / ".claude.json").write_text(json.dumps({"projects": {cfg.repos[0].source: {"hasTrustDialogAccepted": True}}}))
        _, notes = ports.preflight(cfg)
        self.assertNotIn("信頼していない", "\n".join(notes))

    def test_copy_files_are_looked_for_in_copy_from(self):
        cfg_path, root = make_cfg()
        cfg = config.load(cfg_path, env={})
        empty = pathlib.Path(root).parent / "keep"
        empty.mkdir()
        cfg = cfg._replace(repos=(cfg.repos[0]._replace(copy_from=str(empty)),))
        ports = quiet_ports(herdr_methods=lambda: wiring.HERDR_METHODS, shell_has=lambda c: True, gh_ok=lambda repo, env=None: True)
        _, notes = ports.preflight(cfg)
        self.assertIn(f"写すファイルが {empty} に無い: frontend/.env.local", "\n".join(notes))

    def test_herdr_that_cannot_list_the_sources_worktrees_is_a_problem(self):
        cfg_path, root = make_cfg()
        cfg = config.load(cfg_path, env={})

        def broken(source):
            raise real_herdr.Error(["herdr", "worktree", "list"], "not_a_git_repository")
        ports = quiet_ports(herdr_methods=lambda: wiring.HERDR_METHODS, shell_has=lambda c: True,
                            gh_ok=lambda repo, env=None: True, worktrees=broken)
        problems, _ = ports.preflight(cfg)
        self.assertIn("worktree を並べられない（herdr worktree list: not_a_git_repository）", "\n".join(problems))

    def test_source_that_is_a_linked_worktree_is_a_problem(self):
        cfg_path, root = make_cfg()
        cfg = config.load(cfg_path, env={})
        linked = str(pathlib.Path(root, "feat-1"))
        subprocess.run(["git", "-C", cfg.repos[0].source, "worktree", "add", "-q", "-b", "feat/1", linked, "origin/feat/1"],
                       check=True, capture_output=True)
        cfg = cfg._replace(repos=(cfg.repos[0]._replace(source=linked),))
        ports = quiet_ports(herdr_methods=lambda: wiring.HERDR_METHODS, shell_has=lambda c: True, gh_ok=lambda repo, env=None: True)
        problems, _ = ports.preflight(cfg)
        self.assertIn("linked worktree で、本体の checkout でない", "\n".join(problems))

    def test_source_of_another_repo_is_a_problem(self):
        cfg_path, root = make_cfg()
        cfg = config.load(cfg_path, env={})
        cfg = cfg._replace(repos=(cfg.repos[0]._replace(repo="o/other"),))
        ports = quiet_ports(herdr_methods=lambda: wiring.HERDR_METHODS, shell_has=lambda c: True, gh_ok=lambda repo, env=None: True)
        problems, _ = ports.preflight(cfg)
        self.assertIn("元の clone", "\n".join(problems))


if __name__ == "__main__":
    unittest.main()


class Init(unittest.TestCase):
    def setUp(self):
        self.src, self.root = make_world()
        self.cfg = str(pathlib.Path(self.root).parent / "conf" / "dispatch.toml")

    def test_writes_a_config_that_loads_with_the_sources_local_files(self):
        rc, out = run_main(["--config", self.cfg, "--init", "--repo", "o/r", "--source", self.src], FakePorts([]))
        self.assertEqual(rc, 0, out)
        cfg = config.load(self.cfg, env={})
        repo = cfg.repos[0]
        self.assertEqual((repo.repo, repo.source), ("o/r", self.src))
        self.assertNotIn("clone_root", pathlib.Path(self.cfg).read_text(encoding="utf-8"))  # 置き場は herdr の既定に任せる
        self.assertEqual(repo.copy_files, ("frontend/.env.local",))
        self.assertTrue(pathlib.Path(self.cfg).with_name("dispatch-second-prompt.md").is_file())
        self.assertIn("--check", out)
        text = pathlib.Path(self.cfg).read_text(encoding="utf-8")
        self.assertIn("skills/dispatch/references/setup.md", text.splitlines()[1])   # フィールドの書き方はスキルの別ファイルに在る（README でない）
        self.assertIn("CLAUDE_CONFIG_DIR をシェルの環境でだけ入れて", text)

    def test_repo_that_is_not_the_origin_of_the_source_stops_before_writing(self):
        rc, out = run_main(["--config", self.cfg, "--init", "--repo", "o/other", "--source", self.src], FakePorts([]))
        self.assertEqual(rc, 2)
        self.assertIn("origin が o/r の clone で、--repo の o/other と合わない", out)
        self.assertFalse(pathlib.Path(self.cfg).exists())

    def test_never_overwrites_an_existing_config(self):
        run_main(["--config", self.cfg, "--init", "--repo", "o/r", "--source", self.src], FakePorts([]))
        before = pathlib.Path(self.cfg).read_text(encoding="utf-8")
        rc, out = run_main(["--config", self.cfg, "--init", "--repo", "o/x", "--source", self.src], FakePorts([]))
        self.assertEqual(rc, 1)
        self.assertIn("上書きしない", out)
        self.assertEqual(pathlib.Path(self.cfg).read_text(encoding="utf-8"), before)

    def test_needs_repo_and_source(self):
        rc, out = run_main(["--config", self.cfg, "--init"], FakePorts([]))
        self.assertEqual(rc, 2)
        self.assertIn("--repo", out)


class Check(unittest.TestCase):
    def setUp(self):
        self.cfg, self.root = make_cfg()

    def test_without_config_checks_the_department_needs_and_points_to_init(self):
        missing = str(pathlib.Path(self.root).parent / "none.toml")
        ports = FakePorts([])
        rc, out = run_main(["--config", missing, "--check"], ports)
        self.assertEqual(rc, 0, out)
        self.assertTrue(ports.preflight_task)
        self.assertIn("--init", out)

    def test_all_good_says_so_and_writes_nothing(self):
        ports = FakePorts([])
        rc, out = run_main(["--config", self.cfg, "--check"], ports)
        self.assertEqual(rc, 0)
        self.assertIn("足りない物は無い", out)
        self.assertEqual(ports.term.writes, [])

    def test_clone_not_in_the_settings_checks_the_department_needs_instead_of_stopping(self):
        # 2026-10-19 の works-factory の会社で「設定の repos に無い」で止まり、要らない [[repos]] を手で書いた
        other = str(pathlib.Path(self.root).parent / "other")
        git("clone", "-q", str(pathlib.Path(self.root).parent / "o" / "r.git"), other)
        ports = FakePorts([])
        rc, out = run_main(["--config", self.cfg, "--check", "--repo", other], ports)
        self.assertEqual(rc, 0, out)
        self.assertTrue(ports.preflight_task)
        self.assertIn(f"{other} は設定の [[repos]] に無いので、部署の回（--task・--ask・--land）の前提だけを確かめた", out)
        # [[repos]] に有る clone の中のフォルダは、その clone として今まで通りに確かめる（無いとは言わない）
        sub = pathlib.Path(gitx_source(self.cfg), "sub")
        sub.mkdir()
        ports = FakePorts([])
        rc, out = run_main(["--config", self.cfg, "--check", "--repo", str(sub)], ports)
        self.assertEqual(rc, 0, out)
        self.assertFalse(ports.preflight_task)
        self.assertNotIn("[[repos]] に無いので", out)
        # 名前の打ち間違い（在るフォルダでない）は今まで通り止める
        rc, out = run_main(["--config", self.cfg, "--check", "--repo", "o/nope"], FakePorts([]))
        self.assertEqual(rc, 2, out)

    def test_clone_without_origin_head_is_a_note_with_the_fix(self):
        src = gitx_source(self.cfg)
        git("-C", src, "remote", "set-head", "origin", "--delete")
        rc, out = run_main(["--config", self.cfg, "--check"], FakePorts([]))
        self.assertEqual(rc, 0, out)   # 止めない（会社の形を使わない会社もある）
        self.assertIn(f"git -C {src} remote set-head origin --auto", out)

    def test_problems_and_notes_are_listed(self):
        rc, out = run_main(["--config", self.cfg, "--check"], FakePorts([], problems=["herdr に届かない"]))
        self.assertEqual(rc, 2)
        self.assertIn("- herdr に届かない", out)

    def test_claude_agents_failure_is_a_problem(self):
        ports = FakePorts([])

        def broken(config_dir):
            raise claudex.Error("claude agents --json（x）: unknown command")
        ports.list_sessions = broken
        rc, out = run_main(["--config", self.cfg, "--check"], ports)
        self.assertEqual(rc, 2)
        self.assertIn("claude agents --json", out)
