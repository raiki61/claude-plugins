"""tiers_statusline と、tiers_check の statusline の点検の試験。herdr は起動せず、一時のフォルダを HOME と設定のフォルダにする。"""

import hashlib
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

    def test_a_failure_is_not_stamped_when_the_handed_out_rules_changed_while_reading(self):
        # herdr が書いている途中を読んで compose が落ち、そのあと herdr が書き終えた。そのあとで印（時刻）を付けると、完成した
        # 配られたルールより新しい印になり、次に herdr が配り直すまで作り直しを待たされる。変わっていたら印を付けず、次の描画で取り直す
        self.put(self.remote, 'id = "claude"\n')
        os.utime(self.remote, (1, 1))
        real = sl.read_file

        def read_then_finish_writing(path):
            text = real(path)
            if pathlib.Path(path) == self.remote:
                self.put(self.remote, BASE)   # 読んだあとに書き終わる
            return text
        sl.read_file = read_then_finish_writing
        try:
            ok, said = sl.refresh(self.env, run=self.run_)
        finally:
            sl.read_file = real
        self.assertFalse(ok)
        self.assertFalse(self.over.with_name(self.over.name + ".tiers-failed").exists(), "読んでいる間に変わったなら印を残さない")

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

    def starter(self):
        # statusline/ を写し、bin/tiers-statusline を、起動されたら印のファイルを書く偽物にする。(写した先, 起動したかを見る関数)
        top = self.home / "tiers"
        shutil.copytree(sl.ROOT / "statusline", top / "statusline")
        (top / "bin").mkdir()
        fake, called = top / "bin" / "tiers-statusline", self.home / "called"
        fake.write_text(f"#!/bin/sh\ntouch '{called}'\n", encoding="utf-8")
        fake.chmod(0o755)
        env = {**os.environ, "HERDR_ENV": "1", "HERDR_PANE_ID": "", "HOME": str(self.home), "XDG_CONFIG_HOME": str(self.home / ".config"),
               "XDG_STATE_HOME": str(self.home / ".local" / "state"), "XDG_CACHE_HOME": str(self.home / "cache"), "TMPDIR": str(self.home)}

        self.sh_env, self.sh_top = env, top

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
        return top, started

    @unittest.skipUnless(shutil.which("jq") and shutil.which("bash"), "jq と bash が要る")
    def test_the_statusline_starts_refresh_only_when_it_would_change_something(self):
        top, started = self.starter()
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

    @unittest.skipUnless(shutil.which("jq") and shutil.which("bash"), "jq と bash が要る")
    def test_a_failure_with_no_override_waits_for_new_rules(self):
        # 上書きが無いまま作れない（Python が 3.10 まで・配られたルールが壊れている）と、30 秒ごとにペインの数だけ失敗を繰り返し、
        # エラーの記録に書き足し続ける。失敗の印を残し、配られたルールか足す規則が新しくなるまで起動しない
        top, started = self.starter()
        self.put(self.remote, 'id = "claude"\n')
        os.utime(self.remote, (1, 1))
        os.utime(top / "statusline" / "claude-rule.toml", (1, 1))
        ok, said = sl.refresh(self.env, run=self.run_)
        self.assertFalse(ok)
        self.assertFalse(self.over.exists())
        stamp = self.over.with_name(self.over.name + ".tiers-failed")
        self.assertTrue(stamp.exists(), "失敗の印を残す")
        self.assertFalse(started(), "失敗の印の方が新しい")
        os.utime(top / "statusline" / "claude-rule.toml")
        self.assertTrue(started(), "足す規則が直れば作り直す")
        self.put(self.remote, BASE)
        self.assertTrue(sl.refresh(self.env, run=self.run_)[0])
        self.assertFalse(stamp.exists(), "作れたら失敗の印を消す")

    @unittest.skipUnless(shutil.which("jq") and shutil.which("bash"), "jq と bash が要る")
    def test_a_launcher_that_finds_no_python_3_11_still_leaves_the_failed_stamp(self):
        # PATH の python3 が 3.10 までだと、入口（bin/tiers-statusline）は Python を読み込む前に非ゼロで終わるので、refresh の
        # 失敗の印の書き込みまで行かない。statusline.sh の側で印を書かないと、30 秒ごとに入口を起動し直す
        top, _ = self.starter()
        shutil.copy(sl.ROOT / "bin" / "tiers-statusline", top / "bin" / "tiers-statusline")
        old = self.home / "oldpy"
        old.mkdir()
        for name in ["python3", "python", "py"] + [f"python3.{n}" for n in range(11, 21)]:
            (old / name).write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")   # 版の確かめ（3.11 以上か）に必ず落ちる Python
            (old / name).chmod(0o755)
        self.put(self.remote, BASE)
        env = {**self.sh_env, "PATH": f"{old}{os.pathsep}{os.environ['PATH']}"}
        stamp = self.over.with_name(self.over.name + ".tiers-failed")
        subprocess.run(["bash", str(top / "statusline" / "statusline.sh")], input='{"model": {"display_name": "Opus"}}',
                       env=env, capture_output=True, text=True, encoding="utf-8", check=True)
        for _ in range(50):   # 裏で起動するので、少し待つ
            if stamp.exists():
                break
            subprocess.run(["sleep", "0.1"])
        self.assertTrue(stamp.exists(), "入口が落ちたときも失敗の印を残す")
        self.assertFalse(self.over.exists())

    @unittest.skipUnless(shutil.which("jq") and shutil.which("bash"), "jq と bash が要る")
    def test_a_launcher_that_finds_no_python_3_11_ages_our_override_instead_of_stamping(self):
        # tiers の作った上書きが配られたルールより古いまま入口が落ちると、Python の refresh の失敗と同じに上書きの時刻を進めないと、
        # 30 秒ごとに入口を起動し直してエラーの記録に書き足し続ける
        top, _ = self.starter()
        shutil.copy(sl.ROOT / "bin" / "tiers-statusline", top / "bin" / "tiers-statusline")
        old = self.home / "oldpy"
        old.mkdir()
        for name in ["python3", "python", "py"] + [f"python3.{n}" for n in range(11, 21)]:
            (old / name).write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")
            (old / name).chmod(0o755)
        self.put(self.remote, BASE)
        os.utime(self.remote, (1000, 1000))
        os.utime(top / "statusline" / "claude-rule.toml", (1, 1))
        self.put(self.over, sl.MARK + "\n" + BASE)
        os.utime(self.over, (500, 500))
        env = {**self.sh_env, "PATH": f"{old}{os.pathsep}{os.environ['PATH']}"}
        subprocess.run(["bash", str(top / "statusline" / "statusline.sh")], input='{"model": {"display_name": "Opus"}}',
                       env=env, capture_output=True, text=True, encoding="utf-8", check=True)
        for _ in range(50):   # 裏で起動するので、少し待つ
            if self.over.stat().st_mtime > 1000:
                break
            subprocess.run(["sleep", "0.1"])
        self.assertGreater(self.over.stat().st_mtime, 1000, "上書きの時刻を進めて、次の描画で起動し直さない")
        self.assertFalse(self.over.with_name(self.over.name + ".tiers-failed").exists(), "上書きがあるときは印を書かない")

    @unittest.skipUnless(shutil.which("jq") and shutil.which("bash"), "jq と bash が要る")
    def test_a_refresh_that_failed_in_python_is_left_to_python(self):
        # refresh が Python で失敗した（終わりの値 1）ときの手当ては refresh が済ませている。herdr が書いている途中を読んだときは
        # わざと印を付けないので、statusline.sh が代わりに印を書くと、書き終わったルールを次に配り直すまで取り直さない
        top, _ = self.starter()
        done = self.home / "refresh-done"
        (top / "bin" / "tiers-statusline").write_text(f"#!/bin/sh\n: > '{done}'\nexit 1\n", encoding="utf-8")
        (top / "bin" / "tiers-statusline").chmod(0o755)
        self.put(self.remote, BASE)
        subprocess.run(["bash", str(top / "statusline" / "statusline.sh")], input='{"model": {"display_name": "Opus"}}',
                       env=self.sh_env, capture_output=True, text=True, encoding="utf-8", check=True)
        for _ in range(50):   # 裏で起動するので、少し待つ
            if done.exists():
                break
            subprocess.run(["sleep", "0.1"])
        subprocess.run(["sleep", "0.3"])
        self.assertTrue(done.exists())
        self.assertFalse(self.over.with_name(self.over.name + ".tiers-failed").exists(), "Python の失敗には印を書き足さない")


@unittest.skipIf(os.name == "nt", "statusline.sh は macOS と Linux だけで動く")
class BranchPrKey(unittest.TestCase):
    """statusline.sh の branch_pr_info が、作業場とブランチごとの PR の控えを読む所。"""

    def read(self, path):
        # 控えが新しいうちは gh を起動しないので、控えを置いて読むだけを見る。PATH は find と cat と（あれば）python3 だけ
        with tempfile.TemporaryDirectory() as d:
            tmp, bin_ = pathlib.Path(d, "tmp"), pathlib.Path(d, "bin")
            tmp.mkdir()
            bin_.mkdir()
            for cmd in path:
                (bin_ / cmd).symlink_to(shutil.which(cmd) if cmd != "python3" else sys.executable)
            key = hashlib.sha1("/w/日本語|feat/x".encode()).hexdigest()[:16]
            (tmp / f"herdr-pr-{key}").write_text("12\t題", encoding="utf-8")
            (tmp / "herdr-pr-").write_text("99\tほかのブランチ", encoding="utf-8")
            script = (sl.ROOT / "statusline" / "statusline.sh").read_text(encoding="utf-8")
            func = re.search(r"^branch_pr_info\(\) \{\n.*?^\}\n", script, re.M | re.S).group(0)
            return subprocess.run([shutil.which("bash"), "-c", func + 'branch_pr_info /w/日本語 feat/x'],
                                  env={"PATH": str(bin_), "TMPDIR": str(tmp)}, capture_output=True, text=True, encoding="utf-8").stdout

    def test_key_is_the_sha1_head_of_the_workspace_and_branch(self):
        # 0.11.0 までの shasum の鍵と同じ値なので、上げても控えを取り直さない
        self.assertEqual(self.read(["find", "cat", "python3"]), "12\t題")

    def test_no_key_shows_no_pr_rather_than_another_branchs(self):
        self.assertEqual(self.read(["find", "cat"]), "")

    def refetch(self, gh_exit):
        # 古い控え（15 分より前）を置き、gh の偽物（出力無しで gh_exit で終わる）に取り直させて、控えに残った物を返す
        with tempfile.TemporaryDirectory() as d:
            tmp, bin_, work = pathlib.Path(d, "tmp"), pathlib.Path(d, "bin"), pathlib.Path(d, "work")
            for p in (tmp, bin_, work):
                p.mkdir()
            for cmd in ("find", "cat", "mv", "touch"):
                (bin_ / cmd).symlink_to(shutil.which(cmd))
            (bin_ / "python3").symlink_to(sys.executable)
            (bin_ / "gh").write_text(f"#!/bin/sh\nexit {gh_exit}\n", encoding="utf-8")
            (bin_ / "gh").chmod(0o755)
            cache = tmp / f"herdr-pr-{hashlib.sha1(f'{work}|feat/x'.encode()).hexdigest()[:16]}"
            cache.write_text("12\t題", encoding="utf-8")
            os.utime(cache, (1, 1))
            script = (sl.ROOT / "statusline" / "statusline.sh").read_text(encoding="utf-8")
            func = re.search(r"^branch_pr_info\(\) \{\n.*?^\}\n", script, re.M | re.S).group(0)
            subprocess.run([shutil.which("bash"), "-c", func + f'branch_pr_info "{work}" feat/x >/dev/null; wait'],
                           env={"PATH": str(bin_), "TMPDIR": str(tmp)}, capture_output=True, check=True)
            self.assertGreater(cache.stat().st_mtime, 1, "失敗しても時刻は進め、30 秒ごとに gh を起動し直さない")
            return cache.read_text(encoding="utf-8")

    def test_a_failed_gh_keeps_the_cached_pr(self):
        # ネットワークの断・20 秒の打ち切り（124）・認証の誤りで、開いた PR を「PR 無し」で 15 分上書きしない
        for code in (1, 124):
            self.assertEqual(self.refetch(code), "12\t題", code)

    def test_no_open_pr_is_cached_as_none(self):
        self.assertEqual(self.refetch(0), "-")


@unittest.skipIf(os.name == "nt", "bg-count.sh は macOS と Linux だけで動く")
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


@unittest.skipUnless(sys.platform == "darwin", "日本語のロケールの ps で Claude のプロセスの経過時間を読む所（macOS の ps で確かめる）")
class BgAgentsBorn(unittest.TestCase):
    """bg-count.sh が、Claude のプロセスより前に最後の行を書いた背景のサブエージェントを数えない所。"""

    def test_a_subagent_from_before_the_process_is_not_counted_under_a_japanese_locale(self):
        # 起きた時刻が読めないと、知らせ無しに終わった下請けを 6 時間走っていると数える。LC_TIME が日本語だと date が
        # C の言葉の ps の lstart（"Fri Oct 30 …"）を読めない。今の bash を Claude と見なし、2020 年に止まった下請けを置く
        with tempfile.TemporaryDirectory() as d:
            t = pathlib.Path(d, "s.jsonl")
            t.write_text("", encoding="utf-8")
            sub = pathlib.Path(d, "s", "subagents")
            sub.mkdir(parents=True)
            (sub / "agent-a1.meta.json").write_text('{"requestShape": "background"}', encoding="utf-8")
            (sub / "agent-a1.jsonl").write_text(json.dumps({"type": "user", "timestamp": "2020-01-01T00:00:00.000Z",
                                                            "message": {"content": "x"}}) + "\n", encoding="utf-8")
            script = (sl.ROOT / "statusline" / "bg-count.sh").read_text(encoding="utf-8")
            func = re.search(r"^bg_agents\(\) \{\n.*?^\}\n", script, re.M | re.S).group(0)
            born = re.search(r"^born=\"\"\n.*?(?=^echo )", script, re.M | re.S).group(0)
            got = subprocess.run(["bash", "-c", func + "claude_pid=$$\n" + born + 'bg_agents "$1" "$born"', "_", str(t)],
                                 env={**os.environ, "LC_ALL": "ja_JP.UTF-8", "LANG": "ja_JP.UTF-8"},
                                 capture_output=True, text=True, encoding="utf-8").stdout.strip()
            self.assertEqual(got, "0")


@unittest.skipIf(os.name == "nt", "bg-count.sh は macOS と Linux だけで動く（Windows の bash は WSL の bash.exe に当たることもある）")
class BgAgentsBornEtime(unittest.TestCase):
    """bg-count.sh が、Claude のプロセスの起きた時刻を BSD の date に頼らず ps の経過時間で出す所。"""

    def born(self, etime):
        # 偽の ps は経過時間 etime を答える。偽の date は GNU の物（-j を知らず、illegal option で落ちる）のふりをする
        with tempfile.TemporaryDirectory() as d:
            bin_ = pathlib.Path(d)
            (bin_ / "ps").write_text(f'#!/bin/sh\ncase "$*" in\n  "-o etime= -p 77") echo "  {etime}" ;;\nesac\n', encoding="utf-8")
            (bin_ / "date").write_text('#!/bin/sh\nfor a in "$@"; do [ "$a" = -j ] && { echo "date: illegal option -- j" >&2; exit 1; }; done\n'
                                       f'exec {shutil.which("date")} "$@"\n', encoding="utf-8")
            for f in bin_.iterdir():
                f.chmod(0o755)
            script = (sl.ROOT / "statusline" / "bg-count.sh").read_text(encoding="utf-8")
            born = re.search(r"^born=\"\"\n.*?(?=^echo )", script, re.M | re.S).group(0)
            now = int(subprocess.run(["date", "+%s"], capture_output=True, text=True, encoding="utf-8").stdout)
            out = subprocess.run(["bash", "-c", "claude_pid=77\n" + born + 'echo "$born"'], env={**os.environ, "PATH": f"{d}:{os.environ['PATH']}"},
                                 capture_output=True, text=True, encoding="utf-8").stdout.strip()
            return now, out

    def test_the_born_time_comes_from_etime_in_every_format_even_with_a_gnu_date(self):
        # macOS で GNU coreutils の date が先に PATH に在る（Homebrew の gnubin）と、date -j は落ちて起きた時刻が空になり、
        # 知らせ無しに終わった下請けを 6 時間走っていると数える
        for etime, secs in (("05:09", 5 * 60 + 9), ("03:05:09", 3 * 3600 + 5 * 60 + 9), ("2-03:05:09", 2 * 86400 + 3 * 3600 + 5 * 60 + 9),
                            ("08:08", 8 * 60 + 8)):
            now, out = self.born(etime)
            self.assertTrue(out.isdigit(), (etime, out))
            self.assertAlmostEqual(int(out), now - secs, delta=5, msg=etime)


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
