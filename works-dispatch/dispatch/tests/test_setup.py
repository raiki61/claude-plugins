"""始めの手間を減らす所。部署の回（--task・--ask・--land・--tree）が設定の [[repos]] 無しで、代表の clone の場所から会社を決めること
（config.repo_at・dispatch._department_repo）と、会社の形の下書き（--init-company）。"""

import contextlib
import io
import os
import pathlib
import tempfile
import tomllib
import unittest

from . import DISPATCH  # noqa: F401
from . import test_deliver, test_land
from .test_dispatch import FakePorts, gitx_source, make_cfg, run_main
import config
import dispatch
import ghx
from nodes import land, role, tree


def drop_repos(cfg_path):
    """make_cfg の設定から [[repos]] を外す（アカウントと使用率の置き場だけの設定）。"""
    p = pathlib.Path(cfg_path)
    p.write_text(p.read_text(encoding="utf-8").split("[[repos]]")[0], encoding="utf-8")


class LoadWithoutRepos(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()

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
        self.cfg, self.root = make_cfg()
        self.src = gitx_source(self.cfg)
        drop_repos(self.cfg)
        self.brief = str(pathlib.Path(self.root).parent / "brief.md")
        pathlib.Path(self.brief).write_text("頼み", encoding="utf-8")
        self.ports = FakePorts([])
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


class AskWithoutRepos(test_deliver.Flow):
    """頼む・納品する（--ask・--deliver）の流れを、[[repos]] の無い設定で同じに回す。"""

    def setUp(self):
        super().setUp()
        drop_repos(self.cfg)


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
        self.cfg, self.root = make_cfg()
        self.src = gitx_source(self.cfg)
        self.ports = FakePorts([])
        self.ports.gh = type("Gh", (), {"login": staticmethod(lambda: "the-user")})()

    def init(self, *extra):
        return run_main(["--config", self.cfg, "--init-company", "--repo", self.src, *extra], self.ports)

    def read(self):
        info = tree.read_info(self.src, os.path.dirname(self.cfg), committed=lambda root: None)
        return info, role.load(info["path"], info["text"]), land.read_rules(info["path"], "作業役", info["text"])

    def test_writes_a_draft_the_readers_accept_and_does_not_overwrite_it(self):
        rc, out = self.init()
        self.assertEqual(rc, 0, out)
        path = pathlib.Path(self.src, ".claude", "company.toml")
        self.assertIn(f"書いた: {path}", out)
        info, shape, rules = self.read()
        self.assertEqual((info["source"], info["name"], info["problems"]), ("repo", os.path.basename(self.src), []))
        self.assertEqual((shape["gh_user"], list(shape["roles"]), shape["problems"]), ("the-user", ["<部の名前>の管理者", "作業者", "社長室"], []))
        # 組織は部＋役職: 部の役（管理者が受ける）と作業者は受ける仕事と組で、--role を省いたときの役は作業者
        self.assertEqual([s["role"] for s in info["skills"]], ["<部の名前>の管理者", "作業者"])
        self.assertIn(dispatch.DEFAULT_ROLE, shape["roles"])
        company = os.path.basename(self.src)
        self.assertIn(f"--ask {company}/<部の名前>の管理者", shape["roles"]["<部の名前>の管理者"]["instructions"])
        self.assertIn("管理者", shape["roles"]["<部の名前>の管理者"]["instructions"])
        self.assertIn(f"--ask {company}/<部の名前>の管理者", shape["roles"]["社長室"]["instructions"])
        for name in ("<部の名前>の管理者", "作業者"):
            self.assertIn("もう一度納品の命令で返す", shape["roles"][name]["instructions"])
        text = path.read_text(encoding="utf-8")
        for rule in ("会社・部・役職が分かる", f"{company}<部の名前>の管理者", f"{company}の社長室", "英小文字とハイフン",
                     f"--ask {company}/<部の名前>の管理者"):
            self.assertIn(rule, text)
        path.write_text("# 手で直した\n", encoding="utf-8")
        rc, out = self.init()
        self.assertEqual(rc, 1)
        self.assertIn("上書きしない", out)
        self.assertEqual(path.read_text(encoding="utf-8"), "# 手で直した\n")

    def test_local_goes_to_the_settings_place_that_is_not_committed(self):
        rc, out = self.init("--local")
        self.assertEqual(rc, 0, out)
        self.assertFalse(pathlib.Path(self.src, ".claude", "company.toml").exists())
        info, shape, _ = self.read()
        self.assertEqual((info["source"], info["path"]), ("settings", tree.settings_info_path(os.path.dirname(self.cfg), self.src)))
        self.assertEqual(list(shape["roles"]), ["<部の名前>の管理者", "作業者", "社長室"])

    def test_unreadable_gh_account_leaves_gh_user_commented_out(self):
        def broken():
            raise ghx.GhError("not logged in")
        self.ports.gh = type("Gh", (), {"login": staticmethod(broken)})()
        rc, out = self.init()
        self.assertEqual(rc, 0, out)
        raw = tomllib.loads(pathlib.Path(self.src, ".claude", "company.toml").read_text(encoding="utf-8"))
        self.assertNotIn("gh_user", raw)

    def test_outside_git_and_local_alone_stop(self):
        rc, out = run_main(["--config", self.cfg, "--init-company"], self.ports)   # 打った場所（FakePorts.cwd）は git の外
        self.assertEqual(rc, 2)
        self.assertIn("git のリポジトリでない", out)
        rc, out = run_main(["--config", self.cfg, "--local"], self.ports)
        self.assertEqual(rc, 2)
        self.assertIn("--init-company と一緒に", out)


if __name__ == "__main__":
    unittest.main()
