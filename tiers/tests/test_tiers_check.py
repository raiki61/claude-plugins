"""tiers_check の試験。外のツールは起動せず、Probe の偽物で答える。"""

import io
import json
import pathlib
import subprocess
import sys
import unittest

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "lib"))
import tiers_check  # noqa: E402


class FakeProbe:
    """have: 在るコマンドの名前。runs: (コマンドの名前, 引数の頭) → (終了コード, 出力)。shell: シェルで見つかるコマンド。
    auth: 起動コマンド → auth status --json の (終了コード, 出力)。無い物はログイン済みと答える。"""

    def __init__(self, have=("claude", "gh", "herdr", "archon"), runs=None, shell=("claude",), platform="linux", auth=None):
        self.have = set(have)
        self.runs = {("claude", "--version"): (0, "2.1.301 (Claude Code)\n"),
                     ("gh", "--version"): (0, "gh version 2.102.0\n"),
                     ("gh", "auth"): (0, "github.com\n  ✓ Logged in\n"),
                     ("herdr", "--version"): (0, "herdr 0.9.3\n"),
                     ("herdr", "status"): (0, '{"status": "running", "running": true, "socket": "/tmp/h/herdr.sock"}'),
                     **(runs or {})}
        self.shell = set(shell)
        self.auth = auth or {}
        self.platform = platform
        self.called = []
        self.links, self.files, self.dirs = {}, {}, set()   # 設定のフォルダ → herdr integration status の出力・ファイル → 中身・在るフォルダ

    def which(self, cmd):
        return f"/bin/{cmd}" if cmd in self.have else None

    def run(self, argv):
        self.called.append(argv)
        return self.runs[(pathlib.PurePosixPath(argv[0]).name, argv[1])]

    def run_apart(self, argv):
        code, out = self.run(argv)
        return code, out, ""

    def shell_has(self, cmd):
        return cmd in self.shell

    def run_in(self, argv, config_dir):
        self.called.append((argv, config_dir))
        return (0, self.links.get(config_dir, "claude: current (v10) (/h/hooks/herdr-agent-state.sh)\n"), "")

    def read(self, path):
        return self.files.get(path)

    def isdir(self, path):
        return path in self.dirs

    def auth_status(self, cmd):
        return self.auth.get(cmd, (0, '{"loggedIn": true, "authMethod": "oauth_token"}'))


def names(result, ok=None):
    return [x["name"] for x in result["checks"] if ok is None or x["ok"] == ok]


class Tiers(unittest.TestCase):
    def test_tier_0_checks_only_claude(self):
        r = tiers_check.check(0, probe=FakeProbe())
        self.assertTrue(r["ok"])
        self.assertEqual(names(r), ["Claude Code", "Claude Code のログイン"])

    def test_upper_tier_includes_lower_ones(self):
        r = tiers_check.check(3, probe=FakeProbe())
        self.assertTrue(r["ok"], r)
        self.assertEqual([x["tier"] for x in r["checks"]], [0, 0, 1, 1, 2, 2, 2, 3])

    def test_missing_gh_gives_install_for_the_os_and_skips_login(self):
        for platform, word in (("darwin", "brew install gh"), ("win32", "winget"), ("linux", "apt")):
            r = tiers_check.check(1, probe=FakeProbe(have=("claude",), platform=platform))
            self.assertFalse(r["ok"])
            self.assertEqual(r["missing"], 1)
            gh = r["checks"][2]
            self.assertEqual(gh["name"], "gh")
            self.assertIn(word, gh["fix"][0])
            self.assertTrue(gh["manual"])
            self.assertNotIn("gh のログイン", names(r))

    def test_gh_not_logged_in_says_how_to_log_in(self):
        r = tiers_check.check(1, probe=FakeProbe(runs={("gh", "auth"): (1, "You are not logged into any GitHub hosts.\n")}))
        self.assertEqual(names(r, ok=False), ["gh のログイン"])
        bad = r["checks"][-1]
        self.assertEqual(bad["fix"], ["gh auth login"])
        self.assertIn("not logged", bad["problem"])

    def test_herdr_not_running(self):
        # 動いていない・起動の誤り・人向けの文（JSON でない）・running の無い JSON は、どれも通さない
        for answer in ((0, '{"status": "not_running", "running": false}'), (1, '{"status": "not_running", "running": false}'),
                       (1, "error: connect refused\n"),
                       (0, "server:\n  status: running\n"), (0, '{"status": "running"}')):
            probe = FakeProbe(runs={("herdr", "status"): answer})
            r = tiers_check.check(2, probe=probe)
            self.assertEqual(names(r, ok=False), ["herdr の動き"], answer)
            self.assertIn(["/bin/herdr", "status", "server", "--json"], probe.called)

    def test_launchers_are_looked_up_in_the_shell(self):
        r = tiers_check.check(2, ["claude-a", "claude-b"], probe=FakeProbe(shell=("claude-a",)))
        self.assertEqual(names(r, ok=False), ["起動コマンド claude-b"])
        self.assertIn("起動コマンド claude-a のログイン", names(r, ok=True))

    def test_without_launchers_claude_is_looked_up(self):
        r = tiers_check.check(2, probe=FakeProbe(shell=()))
        self.assertEqual(names(r, ok=False), ["起動コマンド claude"])

    def test_missing_herdr_guides_install_for_the_os_and_the_claude_link(self):
        for platform, words in (("win32", ("ARM64", "install.cmd", "herdr-windows-x86_64.zip", "$env:CLAUDE_CONFIG_DIR")),
                                ("darwin", ("HERDR_INSTALL_DIR", "mise use -g herdr", 'CLAUDE_CONFIG_DIR="$HOME/.claude-p2"')),
                                ("linux", ("HERDR_INSTALL_DIR", "herdr update"))):
            r = tiers_check.check(2, probe=FakeProbe(have=("claude", "gh"), platform=platform))
            herdr = r["checks"][4]
            self.assertEqual(herdr["name"], "herdr")
            self.assertIn("herdr.dev/install", herdr["fix"][0])
            text = "\n".join(herdr["guide"])
            self.assertIn("herdr integration install claude", text)
            for w in words:
                self.assertIn(w, text, platform)

    def test_herdr_not_running_guides_the_claude_link(self):
        r = tiers_check.check(2, probe=FakeProbe(runs={("herdr", "status"): (0, '{"status": "not_running", "running": false}')}))
        run = r["checks"][5]
        self.assertEqual(run["name"], "herdr の動き")
        self.assertIn("herdr integration install claude", "\n".join(run["guide"]))

    def test_missing_launcher_guides_one_account_first_then_three_shells(self):
        r = tiers_check.check(2, ["claude-work"], probe=FakeProbe(shell=()))
        guide = r["checks"][-1]["guide"]
        self.assertIn("アカウントが 1 つなら", guide[0])
        for head in ("bash:", "zsh:", "PowerShell:"):
            self.assertTrue(any(g.startswith(head) for g in guide), head)
        self.assertIn("CLAUDE_CONFIG_DIR", "\n".join(guide))

    def test_items_that_are_ok_have_no_guide(self):
        r = tiers_check.check(3, probe=FakeProbe())
        self.assertTrue(all(x["guide"] == [] for x in r["checks"]))

    def test_version_failure_is_a_problem(self):
        r = tiers_check.check(0, probe=FakeProbe(runs={("claude", "--version"): (1, "boom\n")}))
        self.assertFalse(r["ok"])
        self.assertIn("boom", r["checks"][0]["problem"])

    def test_archon_missing(self):
        r = tiers_check.check(3, probe=FakeProbe(have=("claude", "gh", "herdr"), platform="darwin"))
        self.assertEqual(names(r, ok=False), ["Archon"])
        self.assertIn("archon.diy", r["checks"][-1]["fix"][0])


class Main(unittest.TestCase):
    def run_main(self, argv, probe):
        out = io.StringIO()
        return tiers_check.main(argv, probe=probe, stdout=out), out.getvalue()

    def test_json_has_the_schema_and_exit_code(self):
        rc, out = self.run_main(["--tier", "1", "--json"], FakeProbe(have=("claude",)))
        self.assertEqual(rc, 1)
        got = json.loads(out)
        self.assertEqual((got["schema"], got["tier"], got["ok"], got["missing"]), (1, 1, False, 1))

    def test_human_lines_show_fix_and_how_to_rerun(self):
        rc, out = self.run_main(["--tier", "2", "--launcher", "claude-x"], FakeProbe(shell=()))
        self.assertEqual(rc, 1)
        self.assertIn(" NG  段 2 起動コマンド claude-x", out)
        self.assertIn("入れ方（手で）", out)
        self.assertIn("tiers --tier 2 --launcher claude-x", out)

    def test_human_lines_show_the_same_guide_as_json(self):
        probe = lambda: FakeProbe(have=("claude", "gh"), shell=(), platform="win32")
        rc, out = self.run_main(["--tier", "2", "--launcher", "claude-x"], probe())
        _, js = self.run_main(["--tier", "2", "--launcher", "claude-x", "--json"], probe())
        guides = [g for x in json.loads(js)["checks"] for g in x["guide"]]
        self.assertTrue(guides)
        for g in guides:
            self.assertIn(f"          - {g}", out)

    def test_all_good(self):
        rc, out = self.run_main(["--tier", "3"], FakeProbe())
        self.assertEqual(rc, 0)
        self.assertIn("足りない物は無い", out)

    def test_bad_tier_is_usage(self):
        rc, out = self.run_main(["--tier", "4"], FakeProbe())
        self.assertEqual(rc, 2)
        self.assertIn("0〜3", out)

    def test_entry_in_bin_runs_with_the_python(self):
        # bin/tiers は拡張子の無い Python の台本。Windows でも同じ解釈系で起動できる（外のツールは起動しない: 使い方の誤りで終わる）
        p = subprocess.run([sys.executable, str(HERE.parent / "bin" / "tiers"), "--tier", "9"],
                           capture_output=True, text=True, encoding="utf-8", errors="replace")
        self.assertEqual(p.returncode, 2, p.stdout + p.stderr)
        self.assertIn("0〜3", p.stdout)


class RealProbe(unittest.TestCase):
    def test_which_uses_the_given_path(self):
        probe = tiers_check.Probe(env={"PATH": ""}, platform="linux")
        self.assertIsNone(probe.which("tiers-no-such-command"))

    def test_shell_has_falls_back_to_which_on_windows(self):
        probe = tiers_check.Probe(env={"PATH": ""}, platform="win32")
        self.assertFalse(probe.shell_has("tiers-no-such-command"))

    def test_shell_has_looks_for_powershell_functions_on_windows(self):
        # $PROFILE に書いた関数は PATH に無いので、在る方の PowerShell に Get-Command で聞く
        calls = []

        def fake_run(argv):
            calls.append(argv)
            return (0 if pathlib.PurePath(argv[0]).name == "powershell" else 1), ""

        probe = tiers_check.Probe(env={"PATH": ""}, platform="win32")
        probe.which = lambda cmd: {"pwsh": "/ps/pwsh", "powershell": "/ps/powershell"}.get(cmd)
        orig = tiers_check._run
        tiers_check._run = fake_run
        try:
            self.assertTrue(probe.shell_has("claude-o'p"))
        finally:
            tiers_check._run = orig
        self.assertEqual([pathlib.PurePath(c[0]).name for c in calls], ["pwsh", "powershell"])
        self.assertIn("Get-Command -Name 'claude-o''p'", calls[-1][-1])



class Login(unittest.TestCase):
    def test_claude_logged_out_stops_tier_0(self):
        r = tiers_check.check(0, probe=FakeProbe(auth={"claude": (1, '{"loggedIn": false, "authMethod": "none"}')}))
        self.assertFalse(r["ok"])
        [item] = [x for x in r["checks"] if not x["ok"]]
        self.assertEqual(item["name"], "Claude Code のログイン")
        self.assertIn("claude auth login", item["fix"][0])

    def test_unreadable_answer_does_not_pass(self):
        for answer in ((127, "bash: claude: command not found"), (0, ""), (0, '{"loggedIn": "yes"}'), (0, "[]")):
            r = tiers_check.check(0, probe=FakeProbe(auth={"claude": answer}))
            self.assertEqual(names(r, ok=False), ["Claude Code のログイン"], answer)

    def test_each_launcher_is_checked_for_login(self):
        r = tiers_check.check(2, ["claude-a", "claude-b"], probe=FakeProbe(
            shell=("claude-a", "claude-b"), auth={"claude-b": (1, '{"loggedIn": false}')}))
        self.assertEqual(names(r, ok=False), ["起動コマンド claude-b のログイン"])

    def test_no_login_check_when_claude_cannot_start(self):
        r = tiers_check.check(0, probe=FakeProbe(have=()))
        self.assertEqual(names(r), ["Claude Code"])


class HerdrSocket(unittest.TestCase):
    def test_not_running_names_the_socket_it_looked_at(self):
        text = '{"status": "not_running", "running": false, "socket": "/tmp/h/.config/herdr/herdr.sock"}'
        r = tiers_check.check(2, probe=FakeProbe(runs={("herdr", "status"): (0, text)}))
        [item] = [x for x in r["checks"] if x["name"] == "herdr の動き"]
        self.assertIn("見た socket: /tmp/h/.config/herdr/herdr.sock", item["problem"])

if __name__ == "__main__":
    unittest.main()


class ConfigDirs(unittest.TestCase):
    """--config-dir を渡したときの、フォルダごとの点検（プラグインの控えの置き場・herdr の連携）。"""

    def test_without_config_dirs_nothing_more_is_checked(self):
        self.assertEqual(names(tiers_check.check(2, probe=FakeProbe())), names(tiers_check.check(2, probe=FakeProbe(), config_dirs=[])))

    def test_install_records_pointing_at_gone_folders_are_named_with_how_to_remove(self):
        probe = FakeProbe()
        probe.files["/h/.claude-p2/plugins/installed_plugins.json"] = json.dumps({"version": 2, "plugins": {
            "gates@m": [{"scope": "user", "installPath": "/c/gates/0.8.0"},
                        {"scope": "project", "projectPath": "/r/x", "installPath": "/c/gates/0.7.0"}]}})
        probe.dirs.update({"/c/gates/0.8.0", "/c/gates/0.6.0", "/h/.claude-p1", "/h/.claude-p2"})
        r = tiers_check.check(0, probe=probe, config_dirs=["/h/.claude-p1", "/h/.claude-p2"])
        self.assertEqual(names(r, ok=False), ["プラグインの控え（/h/.claude-p2）"])
        bad = r["checks"][-1]
        self.assertIn("gates@m（project、/r/x）/c/gates/0.7.0", bad["problem"])
        self.assertIn("claude plugin uninstall gates@m --scope project", bad["fix"][0])
        # 前の版の印の付いた置き場（まだ在る）も、消える物として出す
        probe.files["/h/.claude-p1/plugins/installed_plugins.json"] = json.dumps({"version": 2, "plugins": {
            "gates@m": [{"scope": "user", "installPath": "/c/gates/0.6.0"}]}})
        probe.files["/c/gates/0.6.0/.orphaned_at"] = "1"
        self.assertIn("/c/gates/0.6.0", tiers_check.check(0, probe=probe, config_dirs=["/h/.claude-p1"])["checks"][-1]["problem"])
        self.assertIn("が無い", tiers_check.check(0, probe=probe, config_dirs=["/h/typo"])["checks"][-1]["problem"])
        probe.files["/h/.claude-p1/plugins/installed_plugins.json"] = "{"
        self.assertIn("読めない", tiers_check.check(0, probe=probe, config_dirs=["/h/.claude-p1"])["checks"][-1]["problem"])

    def test_herdr_link_is_checked_per_folder_and_unknown_lines_are_not_passed(self):
        probe = FakeProbe()
        probe.links["/h/.claude-o"] = "claude: not installed (/h/.claude-o/hooks/herdr-agent-state.sh)\n"
        probe.links["/h/.claude-x"] = "claude: broken-ish (v11)\n"
        probe.dirs.update({"/h/.claude-p1", "/h/.claude-o", "/h/.claude-x"})
        r = tiers_check.check(2, probe=probe, config_dirs=["/h/.claude-p1", "/h/.claude-o", "/h/.claude-x"])
        self.assertEqual(names(r, ok=False), ["herdr の連携（/h/.claude-o）", "herdr の連携（/h/.claude-x）"])
        got = {x["name"]: x for x in r["checks"]}
        self.assertIn("CLAUDE_CONFIG_DIR=/h/.claude-o herdr integration install claude", got["herdr の連携（/h/.claude-o）"]["fix"])
        self.assertIn("読めない", got["herdr の連携（/h/.claude-x）"]["problem"])
        self.assertIn((["/bin/herdr", "integration", "status"], "/h/.claude-o"), probe.called)

    def test_the_command_line_takes_config_dirs_and_says_them_again(self):
        out = io.StringIO()
        probe = FakeProbe()
        probe.dirs.add("/h/.claude-p1")
        self.assertEqual(tiers_check.main(["--tier", "0", "--config-dir", "/h/.claude-p1"], probe=probe, stdout=out), 0)
        self.assertIn("プラグインの控え（/h/.claude-p1）", out.getvalue())
