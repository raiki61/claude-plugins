"""部署の回を GitHub 無しで動かす所（2 回目のまっさらな環境での試し docs/trials/2026-10-16-clean-env-2.md の 3・4・6・8）。
メインブランチの名前を手元の git から取る・部署の回の確かめで GitHub を読まない・--check が gh の足りない物を注記にとどめる・返し方の文が
項目の決まりを言う・手元の検証が部署の場所に作ったファイルを消す。"""

import os
import pathlib
import subprocess
import tempfile
import unittest

from . import DISPATCH  # noqa: F401
from .test_dispatch import FakePorts, make_cfg, quiet_ports, run_main
from .test_provision import git
import config
import wiring
import gitx
import landing
import tierx
from nodes import deliver


def bare_world(branch="master"):
    """(手元の bare の origin, その clone)。origin の既定のブランチは branch。clone は origin/HEAD を持つ。"""
    t = pathlib.Path(tempfile.mkdtemp(prefix="dispatch-local-")).resolve()
    bare, seed, clone = t / "o.git", t / "seed", t / "c"
    env = {**os.environ, "GIT_CONFIG_GLOBAL": str(t / "gc"), "GIT_CONFIG_NOSYSTEM": "1"}
    (t / "gc").write_text("", encoding="utf-8")

    def run(*args):
        subprocess.run(["git", *args], check=True, capture_output=True, env=env)
    run("init", "-q", "--bare", f"--initial-branch={branch}", str(bare))
    run("init", "-q", f"--initial-branch={branch}", str(seed))
    (seed / "README.md").write_text("x\n", encoding="utf-8")
    run("-C", str(seed), "add", ".")
    run("-C", str(seed), "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "first")
    run("-C", str(seed), "push", "-q", str(bare), f"{branch}:{branch}")
    run("clone", "-q", str(bare), str(clone))
    return str(bare), str(clone)


class DefaultBranch(unittest.TestCase):
    def test_comes_from_origin_head_then_from_the_origin_and_works_with_a_local_bare(self):
        _, clone = bare_world("master")
        self.assertEqual(gitx.default_branch(clone), "master")
        git("-C", clone, "remote", "set-head", "origin", "-d")   # 空の bare を clone した直後などの、origin/HEAD の無い形
        self.assertIsNone(gitx.origin_head(clone))
        self.assertEqual(gitx.default_branch(clone), "master", "origin に HEAD を問うて決める")

    def test_nothing_to_go_on_says_how_to_fix_it(self):
        t = tempfile.mkdtemp(prefix="dispatch-local-")
        git("init", "-q", t)
        with self.assertRaises(gitx.GitError) as e:
            gitx.default_branch(t)
        self.assertIn("remote set-head origin --auto", str(e.exception))

    def test_ports_read_the_mainline_from_git_not_from_github(self):
        _, clone = bare_world("trunk")
        ports = quiet_ports()
        ports.gh = None   # GitHub に問えば落ちる
        self.assertEqual(ports.default_branch(config.Repo("x/y", "", clone, (), None, None)), "trunk")


class DepartmentPreflight(unittest.TestCase):
    def test_department_run_does_not_read_github_but_the_pr_run_does(self):
        cfg, _ = make_cfg()
        asked = []
        ports = quiet_ports(herdr_methods=lambda: wiring.HERDR_METHODS | wiring.TASK_HERDR_METHODS, shell_has=lambda c: True,
                            gh_ok=lambda repo, env=None: asked.append(repo) or False)
        loaded = config.load(cfg, {})
        problems, _ = ports.preflight(loaded, task=True)
        self.assertEqual(asked, [])
        self.assertFalse([p for p in problems if "gh が" in p], problems)
        problems, _ = ports.preflight(loaded)
        self.assertEqual(asked, ["o/r"])
        self.assertTrue([p for p in problems if "whose-turn" in p])

    def test_check_without_repos_keeps_gh_as_a_note(self):
        result = {"schema": 1, "tier": 2, "ok": False, "missing": 1, "checks": [
            {"tier": 0, "name": "Claude Code", "ok": True},
            {"tier": 1, "name": "gh のログイン", "ok": False, "problem": "gh auth status が通らない", "fix": ["gh auth login"]},
            {"tier": 2, "name": "herdr", "ok": True}]}
        kept, gone = tierx.without_gh(result)
        self.assertTrue(kept["ok"])
        self.assertEqual(len(gone), 1)
        self.assertIn("gh のログイン", gone[0])
        result["checks"][2]["ok"] = False
        self.assertFalse(tierx.without_gh(result)[0]["ok"], "gh 以外の足りない物は止める")

    def test_check_command_without_repos_passes_without_gh(self):
        d = pathlib.Path(tempfile.mkdtemp(prefix="dispatch-local-"))
        cfg = d / "none.toml"
        result = {"schema": 1, "tier": 2, "ok": False, "missing": 1, "checks": [
            {"tier": 1, "name": "gh のログイン", "ok": False, "problem": "gh auth status が通らない", "fix": ["gh auth login"]}]}
        ports = FakePorts([])
        ports._tier_check = lambda launchers: result
        ports.list_sessions = lambda cdir, include_done=False: []
        rc, out = run_main(["--config", str(cfg), "--check"], ports)
        self.assertEqual(rc, 0, out)
        self.assertIn("部署の回には要らない", out)


class ReturnText(unittest.TestCase):
    def test_the_return_text_names_the_rules_of_the_items(self):
        got = deliver.tail(list(deliver.DEFAULT_ITEMS), "py d.py")
        self.assertIn("決め手には原典の http(s) の URL が要る", got)
        self.assertIn("結論は 3 行以内", got)
        got = deliver.tail(["結論", "差分", "試験", "残った疑問", "ブランチ"], "py d.py")
        self.assertNotIn("URL", got)


class Sweep(unittest.TestCase):
    def test_files_the_check_made_are_removed_and_others_are_kept(self):
        _, clone = bare_world("master")
        pathlib.Path(clone, ".gitignore").write_text("keep.env\n", encoding="utf-8")
        git("-C", clone, "add", ".gitignore")
        git("-C", clone, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "ignore")
        pathlib.Path(clone, "keep.env").write_text("x", encoding="utf-8")   # .gitignore に当たる物は触らない
        before = gitx.untracked(clone)
        cache = pathlib.Path(clone, "src", "__pycache__")
        cache.mkdir(parents=True)
        (cache / "calc.cpython-314.pyc").write_bytes(b"x")
        landing._sweep(clone, gitx.untracked(clone) - before)
        self.assertFalse(pathlib.Path(clone, "src").exists(), "空になったフォルダも消す")
        self.assertTrue(pathlib.Path(clone, "keep.env").exists())
        self.assertTrue(gitx.is_clean(clone))


if __name__ == "__main__":
    unittest.main()
