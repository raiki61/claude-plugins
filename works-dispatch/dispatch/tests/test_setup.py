"""始めの手間を減らす所。部署の回（--task・--ask・--land・--tree）が設定の [[repos]] 無しで、代表の clone の場所から会社を決めること
（config.repo_at・dispatch._department_repo）と、会社の形の下書き（--init-company）。git は偽物（tests/fakegit.py）で回す
（--land の組 LandGhUser は test_land の World の本物）。"""

import os
import pathlib
import tomllib
import unittest

from . import DISPATCH, fakegit  # noqa: F401
from . import test_deliver, test_land
from .worlds import FlowWorld
from .test_dispatch import FakePorts, fake_cfg, gitx_source, run_main
import config
import dispatch
import ghx
from nodes import land, role, tree
from . import scratch


def drop_repos(cfg_path):
    """make_cfg の設定から [[repos]] を外す（アカウントと使用率の置き場だけの設定）。"""
    p = pathlib.Path(cfg_path)
    p.write_text(p.read_text(encoding="utf-8").split("[[repos]]")[0], encoding="utf-8")


class LoadWithoutRepos(unittest.TestCase):
    def setUp(self):
        self.d = scratch()

    def write(self, body):
        path = os.path.join(self.d, "c.toml")
        pathlib.Path(path).write_text(body, encoding="utf-8")
        return path

    def test_accounts_only_is_read_and_pick_repo_points_to_init(self):
        cfg = config.load(self.write('accounts = [{ name = "a", command = "claude-a" }]\n'), env={})
        self.assertEqual((cfg.repos, cfg.accounts[0].name), ((), "a"))
        with self.assertRaises(config.ConfigError) as e:
            config.pick_repo(cfg, None)
        self.assertIn("--init", str(e.exception))

    def test_missing_file_is_the_default_only_when_asked(self):
        missing = os.path.join(self.d, "none.toml")
        cfg = config.load(missing, env={}, missing_ok=True)
        self.assertEqual((cfg.repos, [a.command for a in cfg.accounts]), ((), ["claude"]))
        with self.assertRaises(config.ConfigError):
            config.load(missing, env={})

    def test_second_prompt_file_may_be_left_out_but_not_mistyped(self):
        cfg = config.load(self.write('[[repos]]\nrepo = "o/r"\nsource = "s"\n'), env={})
        self.assertEqual(cfg.repos[0].second_prompt, "")
        with self.assertRaises(config.ConfigError) as e:
            config.load(self.write('[[repos]]\nrepo = "o/r"\nsource = "s"\nsecond_prompt_file = 1\n'), env={})
        self.assertIn("second_prompt_file", str(e.exception))

    def test_repo_at_prefers_the_configured_repo_then_makes_a_small_one(self):
        root = os.path.join(self.d, "clone")
        os.makedirs(root)
        own = config.Repo("o/r", "", root, (), None, "me")
        cfg = config.Config(95, self.d, (config.Account("a", "claude"),), (own,))
        self.assertIs(config.repo_at(cfg, root + os.sep, lambda r: "x/y"), own)
        self.assertEqual(config.repo_at(cfg._replace(repos=()), root, lambda r: "x/y"), config.Repo("x/y", "", root))
        self.assertEqual(config.repo_at(cfg._replace(repos=()), root, lambda r: None).repo, "clone")


class TaskWithoutRepos(unittest.TestCase):
    """部署の回は、設定に [[repos]] が無くても、--repo のパスか打った場所から会社を決める。"""

    def setUp(self):
        self.cfg, self.root, self.g = fake_cfg()
        fakegit.forbid_real_git(self)
        self.src = gitx_source(self.cfg)
        drop_repos(self.cfg)
        self.brief = str(pathlib.Path(self.root).parent / "brief.md")
        pathlib.Path(self.brief).write_text("頼み", encoding="utf-8")
        self.ports = FakePorts([], git=self.g)
        self.seen = []
        places = self.ports.places
        self.ports.places = lambda repo: self.seen.append(repo) or places(repo)

    def task(self, *extra):
        return run_main(["--config", self.cfg, "--task", "直し", "--branch", "task/fix", "--brief", self.brief, "--dry-run",
                         *extra], self.ports)

    def test_repo_path_decides_the_company(self):
        rc, out = self.task("--repo", self.src)
        self.assertEqual(rc, 0, out)
        self.assertIn("部署 直し  task/fix  a1  create", out)
        self.assertEqual(os.path.realpath(self.seen[0].source), os.path.realpath(self.src))
        self.assertEqual(self.seen[0].second_prompt, "")

    def test_a_folder_inside_the_clone_decides_the_company_too(self):
        self.ports._cwd = os.path.join(self.src, "frontend")
        os.makedirs(self.ports._cwd, exist_ok=True)
        rc, out = self.task()
        self.assertEqual(rc, 0, out)
        self.assertEqual(os.path.realpath(self.seen[0].source), os.path.realpath(self.src))

    def test_without_a_place_to_decide_it_stops(self):
        rc, out = self.task()   # 打った場所（FakePorts.cwd）は git の外
        self.assertEqual(rc, 2)
        self.assertIn("会社（代表の clone）を決められない", out)
        rc, out = self.task("--repo", "o/elsewhere")
        self.assertEqual(rc, 2)
        self.assertIn("--repo の o/elsewhere", out)
        self.assertEqual(self.seen, [])

    def test_no_config_file_at_all_still_starts_a_department(self):
        os.remove(self.cfg)
        rc, out = self.task("--repo", self.src)
        self.assertEqual(rc, 0, out)
        self.assertIn("部署 直し  task/fix  default  create", out)

    def test_land_finds_the_company_the_same_way(self):
        rc, out = run_main(["--config", self.cfg, "--land", "無い部署", "--repo", self.src], self.ports)
        self.assertEqual(rc, 1)
        self.assertIn("部署 無い部署 が無い", out)

    def test_opening_prs_still_needs_repos(self):
        rc, out = run_main(["--config", self.cfg, "--dry-run"], self.ports)
        self.assertEqual(rc, 2)
        self.assertIn("[[repos]]", out)


class AskWithoutRepos(FlowWorld, unittest.TestCase):
    """頼む・納品する（--ask・--deliver）の流れを、[[repos]] の無い設定で回す。--ask・--deliver の道で設定の [[repos]] が効くのは、
    新しい部署を立てるときに会社の repo を決める所（orders.ask の config.repo_at。最小の repo になり、source は代表の clone）だけなので、
    test_deliver.Flow のうちその道を通る本と、設定を読んで打った場所から会社を決めて頼んで納品するひと回りの本だけを回し直す（ほかの本は
    [[repos]] を読まず、同じ入力・同じ結論になる）。"""

    def setUp(self):
        super().setUp()
        drop_repos(self.cfg)


# AskWithoutRepos が回し直す test_deliver.Flow の本。新しい部署を立てる道（orders.ask の config.repo_at を通る。retire.spread も
# orders.take からこの道を通る）と、設定を読み（orders.survey）打った場所から会社と受付箱を決めて頼んで納品するひと回り
ASK_WITHOUT_REPOS = (
    "test_ask_to_a_role_without_a_resident_department_starts_one_through_the_task_path",
    "test_a_new_department_on_the_askers_own_branch_stops_and_says_to_go_on_here",
    "test_a_new_department_that_does_not_start_leaves_why_in_the_ledger",
    "test_an_ask_typed_from_the_head_office_by_a_department_records_the_departments_place",
    "test_a_department_that_failed_to_launch_keeps_the_reason_from_before_the_summary",
    "test_ask_to_a_duty_raised_only_when_asked_starts_its_department_with_a_branch_of_its_own",
    "test_ask_to_a_duty_raised_only_when_asked_moves_off_a_branch_name_that_clashes_with_one_in_the_repo",
    "test_ask_to_a_duty_taken_per_ask_starts_a_department_of_its_own_for_each_ask",
    "test_an_ask_to_a_per_ask_duty_skips_a_stray_department_of_the_bare_name",
    "test_retire_spreads_the_queue_of_a_stray_department_into_departments_of_their_own",
    "test_ask_that_started_a_department_without_its_talk_id_is_still_delivered",
    "test_ask_whose_department_did_not_start_is_not_delivered_even_with_its_ask_attr",
    "test_ask_that_starts_a_department_reads_the_items_from_the_fetched_shape",
    "test_deliver_sends_the_summary_to_the_asker_and_marks_it_delivered",
    "test_ask_typed_in_another_clone_returns_to_the_askers_own_inbox",
    "test_deliver_brings_the_main_clone_up_to_a_push_that_skipped_land",
)
for _name in ASK_WITHOUT_REPOS:
    setattr(AskWithoutRepos, _name, getattr(test_deliver.Flow, _name))


class LandGhUser(test_land.LandCase):
    def test_company_gh_user_is_used_when_the_repo_has_none(self):
        w = test_land.World(self.tmp, {".claude/company.toml": 'gh_user = "company-user"\n[land]\nmode = "pr"\n'})
        w.work()
        ports = test_land.Ports(w)
        users = []
        ports.gh_env = lambda repo: users.append(repo.gh_user)
        code, out = self.land(w, ports)
        self.assertEqual(code, 0, out)
        self.assertEqual(users, ["company-user"])


class InitCompany(unittest.TestCase):
    def setUp(self):
        self.cfg, self.root, self.g = fake_cfg()
        fakegit.forbid_real_git(self)
        self.src = gitx_source(self.cfg)
        self.ports = FakePorts([], git=self.g)
        self.ports.gh = self.gh()

    @staticmethod
    def gh(login=lambda: "the-user", env_for=lambda user, env: {**env, "GH_TOKEN": "t"}):
        return type("Gh", (), {"login": staticmethod(login), "env_for": staticmethod(env_for)})()

    def init(self, *extra):
        return run_main(["--config", self.cfg, "--init-company", "--repo", self.src, *extra], self.ports)

    def read(self):
        info = tree.read_info(self.src, os.path.dirname(self.cfg), self.g, committed=lambda root: None)
        return info, role.load(info["path"], info["text"]), land.read_rules(info["path"], "サブエージェント", info["text"])

    def test_writes_a_draft_the_readers_accept_and_does_not_overwrite_it(self):
        rc, out = self.init()
        self.assertEqual(rc, 0, out)
        path = pathlib.Path(self.src, ".claude", "company.toml")
        self.assertIn(str(path), out)
        info, shape, rules = self.read()
        # 名前は origin（o/r）の NAME、gh_user は origin の持ち主（鍵を取り出せるとき）
        self.assertEqual((info["source"], info["name"], info["problems"]), ("repo", "r", []))
        self.assertEqual((shape["gh_user"], list(shape["roles"]), shape["problems"]), ("o", ["担当", "作業", "窓口"], []))
        # 担当と作業はコードの直しなので、納品は差分と試験を返す（決め手の原典の URL を求めない）
        for name in ("担当", "作業"):
            self.assertEqual(shape["roles"][name]["deliver"], ["結論", "差分", "試験", "残った疑問", "ブランチ"])
        # 役の本文は役ごとの雛形（dispatch.DRAFT_*）で、会社の名前 r が --ask の例に入る。文の言い回しは雛形の側で決め、ここでは
        # どの役にどの雛形が届くかと、本文に出るコマンドが dispatch の引数に在るか（部署が打って断られない）を見る
        company = "r"
        drafts = {"担当": dispatch.DRAFT_DUTY.format(company=company), "作業": dispatch.DRAFT_WORK,
                  "窓口": dispatch.DRAFT_DESK.format(company=company)}
        for name, draft in drafts.items():
            self.assertEqual(shape["roles"][name]["instructions"], draft.strip())
        self.assertIn(f"--ask {company}/作業 ", shape["roles"]["担当"]["instructions"])
        self.assertIn(f"--ask {company}/担当 ", shape["roles"]["窓口"]["instructions"])
        self.assertIn(f"--ask {company}/作業 ", shape["roles"]["窓口"]["instructions"])
        flags = {f for act in dispatch._parser()._actions for f in act.option_strings}
        # 担当と作業は納品し直し（--deliver --again）と、止められた --land を窓口に頼む（--ask）こと、作業は --done で畳むこと、
        # 窓口は --land で入れて --retire で畳むことを、役の本文で受ける
        commands = {"担当": ("--ask", "--deliver", "--again", "--task", "--branch"),
                    "作業": ("--ask", "--deliver", "--again", "--done"),
                    "窓口": ("--ask", "--task", "--branch", "--text", "--land", "--retire")}
        for name, wanted in commands.items():
            for flag in wanted:
                with self.subTest(role=name, flag=flag):
                    self.assertIn(flag, flags)
                    self.assertIn(flag, shape["roles"][name]["instructions"])
        # --land は自動の権限の判定（auto mode）に「Merge Without Review」で止められうる。担当と作業の設定で例外を文で書く
        for name in ("担当", "作業"):
            self.assertEqual(shape["roles"][name]["settings"]["autoMode"]["allow"], ["$defaults", dispatch.DRAFT_LAND_ALLOW])
            # 部署の画面は誰も見ていないので、画面で問うツールと作業場を出るツールを外す
            self.assertEqual(shape["roles"][name]["settings"]["permissions"]["deny"], ["AskUserQuestion", "EnterWorktree"])
        # 役は担当（受け持ちごとに always）と作業（一度きり。--role を省いたときの役）。受け持ちは受ける仕事の項目で、役は担当
        self.assertEqual([(s["name"], s["role"]) for s in info["skills"]], [("<受け持ち>", "担当"), ("一度きりの作業", "作業")])
        self.assertEqual((shape["default_role"], dispatch.DEFAULT_ROLE), ("作業", "作業"))
        self.assertEqual([(shape["roles"][n]["lifetime"], shape["roles"][n]["context"]) for n in ("担当", "作業")], [("always", "new"), (None, None)])
        # 前の役の名前は下書きに戻さない
        text = path.read_text(encoding="utf-8")
        for gone in ("管理者", "社長室", "作業者"):
            self.assertNotIn(gone, text)
        path.write_text("# 手で直した\n", encoding="utf-8")
        rc, out = self.init()
        self.assertEqual(rc, 1)
        self.assertEqual(path.read_text(encoding="utf-8"), "# 手で直した\n")

    def test_local_goes_to_the_settings_place_that_is_not_committed(self):
        rc, out = self.init("--local")
        self.assertEqual(rc, 0, out)
        self.assertFalse(pathlib.Path(self.src, ".claude", "company.toml").exists())
        info, shape, _ = self.read()
        self.assertEqual((info["source"], info["path"]), ("settings", tree.settings_info_path(os.path.dirname(self.cfg), self.src)))
        self.assertEqual(list(shape["roles"]), ["担当", "作業", "窓口"])

    def test_unreadable_gh_account_leaves_gh_user_commented_out_and_the_draft_stays_toml(self):
        # gh の誤りの文は複数行になる。注記に入れても 1 行に畳み、下書きは TOML として読める
        def broken():
            raise ghx.GhError("gh のログイン名を読めない: To get started with GitHub CLI, please run:  gh auth login\n"
                              "Alternatively, populate the GH_TOKEN environment variable with a GitHub API authentication token.")
        def no_key(user, env):
            raise ghx.GhError(f"gh のアカウント {user} の鍵を取り出せない")
        self.ports.gh = self.gh(login=broken, env_for=no_key)
        rc, out = self.init()
        self.assertEqual(rc, 0, out)
        text = pathlib.Path(self.src, ".claude", "company.toml").read_text(encoding="utf-8")
        raw = tomllib.loads(text)
        self.assertNotIn("gh_user", raw)
        self.assertIn("Alternatively, populate", next(line for line in text.splitlines() if line.startswith("# gh_user")))

    def test_account_whose_key_cannot_be_taken_out_is_not_written(self):
        # 鍵を GH_TOKEN で渡しているとき: gh api user は通るが、gh auth token --user では取り出せない。部署を立てるときに止まるので書かない
        def no_key(user, env):
            raise ghx.GhError(f"gh のアカウント {user} の鍵を取り出せない: no oauth token found for github.com account {user}")
        self.ports.gh = self.gh(env_for=no_key)
        rc, out = self.init()
        self.assertEqual(rc, 0, out)
        text = pathlib.Path(self.src, ".claude", "company.toml").read_text(encoding="utf-8")
        self.assertNotIn("gh_user", tomllib.loads(text))
        self.assertIn("GH_TOKEN", text)

    def test_gh_user_prefers_the_configured_account_then_the_origin_owner_then_the_current_one(self):
        # 2026-10-19 の works-factory の会社で、gh の今のアカウント（会社の仕事のアカウント）が入り、リポジトリの持ち主に手で直した
        with open(self.cfg, "a", encoding="utf-8") as f:
            f.write('gh_user = "cfg-user"\n')   # 設定の [[repos]]（o/r）の最後の項目に足す
        rc, out = self.init()
        self.assertEqual(rc, 0, out)
        text = pathlib.Path(self.src, ".claude", "company.toml").read_text(encoding="utf-8")
        self.assertEqual(tomllib.loads(text)["gh_user"], "cfg-user")
        self.assertIn("[[repos]] の gh_user", text)

    def test_origin_owner_whose_key_cannot_be_taken_out_falls_back_to_the_current_account(self):
        # origin の持ち主が組織なら、その名前の gh のアカウントは無い
        def only_current(user, env):
            if user != "the-user":
                raise ghx.GhError(f"gh のアカウント {user} の鍵を取り出せない")
            return {**env, "GH_TOKEN": "t"}
        self.ports.gh = self.gh(env_for=only_current)
        rc, out = self.init()
        self.assertEqual(rc, 0, out)
        text = pathlib.Path(self.src, ".claude", "company.toml").read_text(encoding="utf-8")
        self.assertEqual(tomllib.loads(text)["gh_user"], "the-user")
        self.assertIn("リポジトリの持ち主のアカウントと違うなら直す", text)

    def test_without_origin_the_name_is_the_folder_and_gh_user_the_current_account(self):
        self.ports.origin = lambda cwd: None
        rc, out = self.init()
        self.assertEqual(rc, 0, out)
        raw = tomllib.loads(pathlib.Path(self.src, ".claude", "company.toml").read_text(encoding="utf-8"))
        self.assertEqual((raw["name"], raw["gh_user"]), (os.path.basename(self.src), "the-user"))
        self.assertNotIn("違うなら直す", pathlib.Path(self.src, ".claude", "company.toml").read_text(encoding="utf-8"))

    def test_outside_git_and_local_alone_stop(self):
        rc, out = run_main(["--config", self.cfg, "--init-company"], self.ports)   # 打った場所（FakePorts.cwd）は git の外
        self.assertEqual(rc, 2)
        self.assertIn("git のリポジトリでない", out)
        rc, out = run_main(["--config", self.cfg, "--local"], self.ports)
        self.assertEqual(rc, 2)
        self.assertIn("--init-company と一緒に", out)


if __name__ == "__main__":
    unittest.main()
