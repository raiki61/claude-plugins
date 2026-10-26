"""tiers_statusline と、tiers_check の statusline の点検の試験。herdr は起動せず、一時のフォルダを HOME と設定のフォルダにする。"""

import io
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile
import tomllib
import unittest

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "lib"))
sys.path.insert(0, str(HERE))
import tiers_check  # noqa: E402
import tiers_statusline as sl  # noqa: E402
from test_tiers_check import FakeProbe  # noqa: E402

BASE = 'id = "claude"\nversion = "2026.10.11.1"\n\n[[rules]]\nid = "x"\nstate = "idle"\n'


class Base(unittest.TestCase):
    def setUp(self):
        self.home = pathlib.Path(tempfile.mkdtemp())
        self.env = {"HOME": str(self.home)}
        self.over, self.remote = sl.herdr_paths(self.env)
        self.ran = []

    def run_(self, argv, **kw):
        self.ran.append(argv)

    def put(self, path, text):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")


class Compose(Base):
    def test_puts_the_rule_after_the_handed_out_rules_and_reads_as_toml(self):
        got = sl.compose(BASE, sl.RULE.read_text(encoding="utf-8"))
        self.assertTrue(got.startswith(sl.MARK))
        ids = [r["id"] for r in tomllib.loads(got)["rules"]]
        self.assertEqual(ids, ["x", sl.RULE_ID])
        self.assertEqual(tomllib.loads(got)["version"], "2026.10.11.1", "版は herdr が配った物のまま")

    def test_broken_toml_is_refused(self):
        with self.assertRaises(ValueError):
            sl.compose(BASE + "[[rules]\n", sl.RULE.read_text(encoding="utf-8"))

    def test_the_mark_the_statusline_prints_is_what_the_rule_looks_for(self):
        # statusline.sh の printf の形と、claude-rule.toml の line_regex が食い違うと、印が出ても herdr は作業中と見分けない
        script = (sl.ROOT / "statusline" / "statusline.sh").read_text(encoding="utf-8")
        fmt = re.search(r"printf '(⧖ [^']*)\\n' \"\$bg_n\"", script).group(1)
        rule = next(r for r in tomllib.loads(sl.RULE.read_text(encoding="utf-8"))["rules"] if r["id"] == sl.RULE_ID)
        (pattern,) = rule["line_regex"]
        self.assertRegex(fmt % 3, pattern)
        self.assertNotRegex(fmt % 0, pattern)

    def test_the_statusline_tells_our_override_by_the_same_mark(self):
        # statusline.sh は tiers の作った上書きだけを作り直しに起動する。見分ける頭が MARK とずれると、作り直さなくなる
        script = (sl.ROOT / "statusline" / "statusline.sh").read_text(encoding="utf-8")
        head = re.search(r"grep -qF '([^']*)'", script).group(1)
        self.assertEqual(head, sl.MARK)

    def test_handed_out_rules_cut_short_are_refused(self):
        # herdr が書いている途中の配られたルールを読むと、TOML として読めたまま規則が欠けうる
        for base in ('id = "claude"\nversion = "1"\n', 'id = "codex"\n' + BASE.split("\n", 1)[1]):
            with self.assertRaises(ValueError):
                sl.compose(base, sl.RULE.read_text(encoding="utf-8"))


class Refresh(Base):
    def test_without_the_handed_out_rules_it_says_how_to_get_them(self):
        ok, said = sl.refresh(self.env, run=self.run_)
        self.assertFalse(ok)
        self.assertIn("update-agent-manifests", said)
        self.assertFalse(self.over.exists())

    def test_writes_the_override_and_asks_herdr_to_reload(self):
        self.put(self.remote, BASE)
        ok, said = sl.refresh(self.env, run=self.run_)
        self.assertTrue(ok, said)
        self.assertIn(sl.RULE_ID, self.over.read_text(encoding="utf-8"))
        self.assertEqual(self.ran, [["herdr", "server", "reload-agent-manifests"]])

    def test_the_same_override_is_only_touched(self):
        self.put(self.remote, BASE)
        sl.refresh(self.env, run=self.run_)
        os.utime(self.over, (1, 1))
        ok, said = sl.refresh(self.env, run=self.run_)
        self.assertTrue(ok)
        self.assertEqual(len(self.ran), 1, "同じなら herdr に読み直させない")
        self.assertGreater(self.over.stat().st_mtime, 1, "statusline.sh が起動し続けないよう、時刻だけ進める")

    def test_new_handed_out_rules_rebuild_our_override(self):
        self.put(self.remote, BASE)
        sl.refresh(self.env, run=self.run_)
        self.put(self.remote, BASE.replace("2026.10.11.1", "2026.11.01.1"))
        sl.refresh(self.env, run=self.run_)
        self.assertIn("2026.11.01.1", self.over.read_text(encoding="utf-8"))

    def test_a_failure_waits_for_the_next_handed_out_rules(self):
        self.put(self.remote, BASE)
        sl.refresh(self.env, run=self.run_)
        os.utime(self.over, (1, 1))
        self.put(self.remote, 'id = "claude"\n')
        ok, said = sl.refresh(self.env, run=self.run_)
        self.assertFalse(ok)
        self.assertIn("規則が無い", said)
        self.assertIn(sl.RULE_ID, self.over.read_text(encoding="utf-8"), "壊れた上書きは書かない")
        self.assertGreater(self.over.stat().st_mtime, 1, "statusline.sh が 30 秒ごとに同じ失敗を繰り返さない")

    @unittest.skipIf(os.name == "nt", "リンクを張る権限が Windows では要る")
    def test_a_linked_override_is_written_through_the_link(self):
        self.put(self.remote, BASE)
        real = self.home / "dotfiles" / "claude.toml"
        self.put(real, "# 手で書いた\n" + BASE)
        self.over.parent.mkdir(parents=True, exist_ok=True)
        os.symlink(real, self.over)
        sl.refresh(self.env, force=True, run=self.run_)
        self.assertTrue(self.over.is_symlink())
        self.assertTrue(real.read_text(encoding="utf-8").startswith(sl.MARK))

    def test_someone_elses_override_is_kept_unless_forced(self):
        self.put(self.remote, BASE)
        self.put(self.over, "# 手で書いた\n" + BASE)
        ok, said = sl.refresh(self.env, run=self.run_)
        self.assertTrue(ok)
        self.assertIn("触らない", said)
        self.assertEqual(self.over.read_text(encoding="utf-8"), "# 手で書いた\n" + BASE)
        ok, said = sl.refresh(self.env, force=True, run=self.run_)
        self.assertTrue(ok)
        self.assertTrue(self.over.read_text(encoding="utf-8").startswith(sl.MARK))
        (saved,) = self.over.parent.glob("claude.toml.bak.*-tiers")
        self.assertEqual(saved.read_text(encoding="utf-8"), "# 手で書いた\n" + BASE)


@unittest.skipIf(os.name == "nt", "statusline は macOS と Linux だけ（リンクを張る権限も Windows では要る）")
class Setup(Base):
    def account(self, settings=None):
        conf = self.home / ".claude-x"
        root = self.home / "cache" / "tiers" / "0.9.0"
        root.mkdir(parents=True)
        self.put(conf / "plugins" / "installed_plugins.json", json.dumps(
            {"version": 2, "plugins": {sl.PLUGIN_ID: [{"scope": "project", "installPath": "/nowhere"},
                                                      {"scope": "user", "installPath": str(root)}]}}))
        if settings is not None:
            self.put(conf / "settings.json", json.dumps(settings))
        return str(conf), root

    def test_points_status_line_at_the_link_and_keeps_the_rest(self):
        conf, root = self.account({"model": "opus", "statusLine": {"type": "command", "command": "~/.claude/statusline.sh", "padding": 1}})
        ok, said = sl.setup_one(conf)
        self.assertTrue(ok, said)
        self.assertEqual(os.path.realpath(sl.data_link(conf)), os.path.realpath(root))
        got = json.loads(pathlib.Path(conf, "settings.json").read_text(encoding="utf-8"))
        self.assertEqual(got["model"], "opus")
        self.assertEqual(got["statusLine"], {"type": "command", "command": sl.command_for(conf), "padding": 1, "refreshInterval": 30})
        self.assertTrue(sl.uses_it(conf))
        (saved,) = pathlib.Path(conf).glob("settings.json.bak.*-tiers")
        self.assertIn("~/.claude/statusline.sh", saved.read_text(encoding="utf-8"))
        ok, said = sl.setup_one(conf)
        self.assertIn("前から", said)
        self.assertEqual(len(list(pathlib.Path(conf).glob("settings.json.bak.*"))), 1, "替えないときは残さない")

    def test_not_installed_says_how_to_install(self):
        conf = str(self.home / ".claude-y")
        ok, said = sl.setup_one(conf)
        self.assertFalse(ok)
        self.assertIn(f"claude plugin install {sl.PLUGIN_ID}", said)

    def test_main_setup_also_builds_the_override(self):
        conf, _ = self.account()
        self.put(self.remote, BASE)
        out = io.StringIO()
        real, sl.subprocess.run = sl.subprocess.run, self.run_
        try:
            rc = sl.main(["setup", "--config-dir", conf], stdout=out, env=self.env)
        finally:
            sl.subprocess.run = real
        self.assertEqual(rc, 0, out.getvalue())
        self.assertTrue(self.over.read_text(encoding="utf-8").startswith(sl.MARK))
        self.assertEqual(self.ran, [["herdr", "server", "reload-agent-manifests"]], "本物の herdr は起動しない")

    def test_a_failed_refresh_ends_with_1_on_stderr(self):
        out, err = io.StringIO(), io.StringIO()
        self.assertEqual(sl.main(["refresh"], stdout=out, env=self.env, stderr=err), 1)
        self.assertIn("できなかった", err.getvalue())
        self.assertEqual(out.getvalue(), "")

    def test_windows_stops_at_the_door_with_the_reason(self):
        conf, _ = self.account()
        settings = pathlib.Path(conf, "settings.json")
        out, err = io.StringIO(), io.StringIO()
        self.assertEqual(sl.main(["setup", "--config-dir", conf], stdout=out, env=self.env, stderr=err, platform="win32"), 1)
        self.assertIn("macOS と Linux だけ", err.getvalue())
        self.assertFalse(os.path.lexists(sl.data_link(conf)), "リンクを張らない")
        self.assertFalse(settings.exists() and "statusLine" in settings.read_text(encoding="utf-8"), "statusLine を書かない")

    def test_a_real_folder_at_the_link_is_not_replaced(self):
        conf, _ = self.account()
        sl.data_link(conf).mkdir(parents=True)
        ok, said = sl.setup_one(conf)
        self.assertFalse(ok)
        self.assertIn("リンクでない", said)
        self.assertTrue(sl.data_link(conf).is_dir() and not sl.data_link(conf).is_symlink())

    def test_unreadable_settings_are_not_overwritten(self):
        conf, _ = self.account()
        self.put(pathlib.Path(conf, "settings.json"), "{ 壊れた")
        ok, said = sl.setup_one(conf)
        self.assertFalse(ok)
        self.assertEqual(pathlib.Path(conf, "settings.json").read_text(encoding="utf-8"), "{ 壊れた")

    def test_wrong_usage_is_2(self):
        real, sys.stderr = sys.stderr, io.StringIO()
        try:
            self.assertEqual(sl.main(["nothing"], stdout=io.StringIO(), env=self.env), 2)
        finally:
            sys.stderr = real


@unittest.skipIf(os.name == "nt", "フックと statusline は macOS と Linux だけ")
class Shell(Base):
    """SessionStart のフックと、statusline.sh が refresh を起動する条件。"""

    def hook(self, data, root):
        (command,) = [h["command"] for g in json.loads((sl.ROOT / "hooks" / "hooks.json").read_text(encoding="utf-8"))["hooks"]["SessionStart"]
                      for h in g["hooks"]]
        subprocess.run(["sh", "-c", command], env={**os.environ, "CLAUDE_PLUGIN_DATA": str(data), "CLAUDE_PLUGIN_ROOT": str(root)}, check=True)

    def test_the_hook_moves_only_a_link_setup_made(self):
        data, old, new = self.home / "data", self.home / "v1", self.home / "v2"
        for d in (data, old, new):
            d.mkdir()
        self.hook(data, new)
        self.assertFalse(os.path.lexists(data / "current"), "setup を打っていないアカウントには張らない")
        os.symlink(old, data / "current")
        self.hook(data, new)
        self.assertEqual(os.readlink(data / "current"), str(new))
        os.unlink(data / "current")
        (data / "current").mkdir()
        self.hook(data, new)
        self.assertEqual(list((data / "current").iterdir()), [], "リンクでない物の中にリンクを作らない")

    def test_the_hook_makes_the_link_the_statusline_points_to(self):
        # 写した settings.json で、statusLine がこのアカウントのリンクを指すのにリンクが無い（新しい設定のフォルダ）
        config, root = self.home / "config", self.home / "v2"
        data = config / "plugins" / "data" / sl.DATA_NAME
        data.mkdir(parents=True)
        root.mkdir()
        (config / "settings.json").write_text(json.dumps({"statusLine": {"type": "command", "command": sl.command_for(config)}}), encoding="utf-8")
        self.hook(data, root)
        self.assertEqual(os.readlink(data / "current"), str(root))
        os.unlink(data / "current")
        (config / "settings.json").write_text(json.dumps({"statusLine": {"type": "command", "command": "/elsewhere/statusline.sh"}}), encoding="utf-8")
        self.hook(data, root)
        self.assertFalse(os.path.lexists(data / "current"), "statusLine がほかを指すアカウントには張らない")

    @unittest.skipUnless(shutil.which("jq") and shutil.which("bash"), "jq と bash が要る")
    def test_the_statusline_starts_refresh_only_when_it_would_change_something(self):
        # statusline/ を写し、bin/tiers-statusline を、起動されたら印のファイルを書く偽物にする
        top = self.home / "tiers"
        shutil.copytree(sl.ROOT / "statusline", top / "statusline")
        (top / "bin").mkdir()
        fake, called = top / "bin" / "tiers-statusline", self.home / "called"
        fake.write_text(f"#!/bin/sh\ntouch '{called}'\n", encoding="utf-8")
        fake.chmod(0o755)
        env = {**os.environ, "HERDR_ENV": "1", "HERDR_PANE_ID": "", "HOME": str(self.home), "XDG_CONFIG_HOME": str(self.home / ".config"),
               "XDG_STATE_HOME": str(self.home / ".local" / "state"), "XDG_CACHE_HOME": str(self.home / "cache"), "TMPDIR": str(self.home)}

        def started():
            if called.exists():
                called.unlink()
            subprocess.run(["bash", str(top / "statusline" / "statusline.sh")], input='{"model": {"display_name": "Opus"}}',
                           env=env, capture_output=True, text=True, encoding="utf-8", check=True)
            for _ in range(50):   # 裏で起動するので、少し待つ
                if called.exists():
                    return True
                subprocess.run(["sleep", "0.1"])
            return False
        self.assertFalse(started(), "配られたルールがまだ無い")
        self.put(self.remote, BASE)
        self.assertTrue(started(), "上書きが無い")
        self.put(self.over, sl.MARK + "\n" + BASE)
        os.utime(self.remote, (1, 1))
        os.utime(top / "statusline" / "claude-rule.toml", (1, 1))
        self.assertFalse(started(), "tiers の上書きの方が新しい")
        os.utime(self.over, (0, 0))
        self.assertTrue(started(), "配られたルールの方が新しい")
        self.put(self.over, "# 手で書いた\n" + BASE)
        os.utime(self.over, (0, 0))
        self.assertFalse(started(), "手で書いた上書きは起動しても変わらない")


class FindClaude(unittest.TestCase):
    """bg-count.sh の find_claude が、背景の Bash の親の Claude を探す所。ps と readlink は PATH の偽物で答える。"""

    def find(self, comm, exe):
        # 処理 50（背景の Bash）の親が 100（Claude）。100 の名前を comm、実行ファイルのパスを exe で答える
        with tempfile.TemporaryDirectory() as d:
            bin_ = pathlib.Path(d)
            (bin_ / "ps").write_text(
                '#!/bin/sh\ncase "$*" in\n'
                f'  "-o comm= -p 100") echo "{comm}" ;;\n  "-o comm= -p 50") echo bash ;;\n'
                '  "-o ppid= -p 50") echo " 100" ;;\n  "-o ppid= -p 100") echo " 1" ;;\nesac\n', encoding="utf-8")
            (bin_ / "readlink").write_text(f'#!/bin/sh\n[ "$1" = /proc/100/exe ] && echo "{exe}"\n', encoding="utf-8")
            for f in bin_.iterdir():
                f.chmod(0o755)
            script = (sl.ROOT / "statusline" / "bg-count.sh").read_text(encoding="utf-8")
            func = re.search(r"^find_claude\(\) \{\n.*?^\}\n", script, re.M | re.S).group(0)
            return subprocess.run(["bash", "-c", func + "find_claude 50"], env={**os.environ, "PATH": f"{d}:{os.environ['PATH']}"},
                                  capture_output=True, text=True, encoding="utf-8").stdout.strip()

    def test_linux_versions_binary_is_found_by_its_executable_path(self):
        # Linux の comm はパスを持たず版の数字だけになる（2026-10-26 に python:3.14-slim で見た）
        self.assertEqual(self.find("2.1.302", "/home/u/.local/share/claude/versions/2.1.302"), "100")

    def test_macos_versions_binary_is_found_by_its_name(self):
        self.assertEqual(self.find("/Users/u/.local/share/claude/versions/2.1.302", ""), "100")

    def test_other_processes_are_not_taken_for_claude(self):
        self.assertEqual(self.find("2.1.302", "/usr/bin/node"), "")


class Check(Base):
    def probe(self, uses=True, link=True, over=None):
        p = FakeProbe()
        p.env = self.env
        conf = "/c"
        if uses:
            p.files[os.path.join(conf, "settings.json")] = json.dumps({"statusLine": {"type": "command", "command": sl.command_for(conf)}})
        if link:
            p.dirs.add(str(sl.data_link(conf)))
        p.files[str(self.remote)] = BASE
        if over is not None:
            p.files[str(self.over)] = over
        return p, conf

    def one(self, p, conf):
        (item,) = tiers_check.check_statusline(p, [conf])
        return item

    def test_not_used_is_ok_and_says_how_to_start(self):
        item = self.one(*self.probe(uses=False))
        self.assertTrue(item["ok"])
        self.assertIn("tiers-statusline setup", item["found"])

    def test_missing_link_or_override_points_to_setup(self):
        for kw in ({"link": False}, {"over": None}, {"over": "# 手で書いた\n" + BASE}):
            item = self.one(*self.probe(**kw))
            self.assertFalse(item["ok"], kw)
            self.assertIn("tiers-statusline setup --config-dir /c", item["fix"], kw)

    def test_rules_that_cannot_be_composed_point_to_refresh(self):
        p, conf = self.probe(over=sl.MARK + "\n")
        p.files[str(self.remote)] = 'id = "claude"\n'
        item = self.one(p, conf)
        self.assertFalse(item["ok"])
        self.assertIn("作れない", item["problem"])

    def test_an_old_override_points_to_refresh_and_a_fresh_one_is_ok(self):
        want = sl.compose(BASE, sl.RULE.read_text(encoding="utf-8"))
        item = self.one(*self.probe(over=want.replace("2026.10.11.1", "2026.09.11.1")))
        self.assertEqual(item["fix"], ["tiers-statusline refresh"])
        self.assertTrue(self.one(*self.probe(over=want))["ok"])


if __name__ == "__main__":
    # 試験の失敗の訳が日本語なので、Windows の既定のコードページ（cp1252 など）に依らず UTF-8 で書く
    for _s in (sys.stdout, sys.stderr):
        if hasattr(_s, "reconfigure"):
            _s.reconfigure(encoding="utf-8")
    unittest.main()
