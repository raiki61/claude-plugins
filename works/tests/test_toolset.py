"""選んだ物だけの隔離した Claude の設定（dev/toolset.py。P1 計画 Task 20 の R61 の範囲）の検査。

AI の節は全部 settingSources: [user] で、開発の殻（dev/archon.sh）が隔離した CLAUDE_CONFIG_DIR を読む。そこに置くのは
許す一覧（.shared/borrow/borrow.json）の物だけ。借りる物は、利用者が Claude Code に入れたプラグインからだけ取る（works は写しを
持たない。本線と同じく、版は Claude Code が今に保つ）:
- 探す所: 利用者の設定の置き場の plugins/installed_plugins.json の <名>@<marketplace> の行（user の行、次に projectPath が
  cwd の project・local の行）。入っていない・works が名前で頼る物（スキル・agent・hook）が無い借りる物は、1 物 1 行の理由と
  入れるコマンドを並べて止まる。中身・版・バイトは確かめない（試験が中身を見るのは、ここで作った偽のプラグインだけ）。
- superpowers の 5 つのスキルを skills/<名>/ へバイトのまま写す（プラグインとしては入れない。有効にすると SessionStart の hook が
  using-superpowers を差し込むため。裁定 P1-R8）。
- coldwrite・pr-review-toolkit を、設定の中の手元の marketplace works-local（works-marketplace/）に写し、Claude Code の CLI
  （claude plugin marketplace add・install）で入れる。Claude Code のキャッシュの印（.in_use/・.orphaned_at）は写さない。
柵（guard）は一覧の外（CLAUDE.md・rules/・agents/・commands/・output-styles/・settings.json 以外の settings*.json・
一覧の外のスキル・settings.json の許す鍵の外・一覧の外のプラグインと marketplace）を名前で並べ、CLI は終了コード 2 で止まる。
Claude Code が自分で書く状態（projects/・.claude.json・backups/・remote-settings.json など）は見ない。

本物の claude も、利用者の本物の設定も使わない。偽の利用者の設定（make_user_config。偽のプラグインを入れた形）と、偽の claude
（FAKE_CLAUDE。受けた argv を記録し、本物の 2.1.283 と同じ形で settings.json・plugins/ の状態のファイルを書く）を渡す。
形は本物の CLI で一時の置き場に入れて確かめた（報告 $S/r61/cfg-report.md）。
"""
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parents[1]
DEV = ROOT / "dev"
TOOLSET = DEV / "toolset.py"
sys.dont_write_bytecode = True
sys.path.insert(0, str(DEV))
import toolset  # noqa: E402

BORROW_SKILLS = ["test-driven-development", "systematic-debugging", "verification-before-completion",
                 "receiving-code-review", "requesting-code-review"]
LENSES = ["code-reviewer", "silent-failure-hunter", "type-design-analyzer", "pr-test-analyzer", "comment-analyzer"]
MP = "works-local"
# 偽の利用者の設定に入れる偽のプラグイン: 名 → (marketplace, キャッシュの版の置き場の名・installed_plugins.json の version)
FAKE_INSTALLED = {"superpowers": ("superpowers-marketplace", "9.9.0"), "coldwrite": ("raiki61", "1.2.3"),
                  "pr-review-toolkit": ("claude-plugins-official", "abc123def456")}


def _put(p: pathlib.Path, body: str, mode=None) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(body, encoding="utf-8")
    if mode is not None:
        p.chmod(mode)


def make_user_config(base: pathlib.Path, only=None, scope="user", project=None) -> pathlib.Path:
    """偽の利用者の Claude の設定の置き場を base に作って返す（test_dev も使う）。plugins/installed_plugins.json に
    FAKE_INSTALLED の偽のプラグイン（only があればその名だけ）を scope の行で載せ、キャッシュの版の置き場に works が名前で頼る物
    （スキルの SKILL.md・agent の .md・hook）と、Claude Code の印（.in_use/・.orphaned_at）を置く"""
    base = pathlib.Path(base)
    rows = {}
    for name, (mp, ver) in FAKE_INSTALLED.items():
        if only is not None and name not in only:
            continue
        d = base / "plugins" / "cache" / mp / name / ver
        if name == "superpowers":
            _put(d / ".claude-plugin" / "plugin.json", json.dumps({"name": name, "version": ver}))
            for s in BORROW_SKILLS + ["brainstorming"]:
                _put(d / "skills" / s / "SKILL.md", f"---\nname: {s}\n---\n偽の {s}\n")
            _put(d / "skills" / "systematic-debugging" / "find-polluter.sh", "#!/bin/sh\n", 0o755)
        elif name == "coldwrite":
            _put(d / ".claude-plugin" / "plugin.json", json.dumps({"name": name, "version": ver}))
            _put(d / "hooks" / "hooks.json", json.dumps({"hooks": {"PreToolUse": [
                {"matcher": "Write", "hooks": [{"type": "prompt", "prompt": "偽の初見検査"}]}]}}))
        else:
            _put(d / ".claude-plugin" / "plugin.json", json.dumps({"name": name}))   # 本物と同じく version を持たない
            for a in LENSES + ["code-simplifier"]:
                _put(d / "agents" / f"{a}.md", f"---\nname: {a}\n---\n偽の {a}\n")
        _put(d / ".in_use" / "4242", "{}")
        _put(d / ".orphaned_at", "1790054446372")
        row = {"scope": scope, "installPath": str(d), "version": ver, "installedAt": "2026-09-28T00:00:00.000Z"}
        if project is not None:
            row["projectPath"] = str(project)
        rows[f"{name}@{mp}"] = [row]
    _put(base / "plugins" / "installed_plugins.json", json.dumps({"version": 2, "plugins": rows}, indent=2))
    return base


def installed_dir(user: pathlib.Path, name: str) -> pathlib.Path:
    mp, ver = FAKE_INSTALLED[name]
    return pathlib.Path(user) / "plugins" / "cache" / mp / name / ver


# 本物の claude 2.1.283 の `plugin marketplace add|update`・`plugin install|uninstall` が隔離した設定に残す形を真似る
FAKE_CLAUDE = r'''#!/usr/bin/env python3
import json, os, pathlib, shutil, sys
cfg = pathlib.Path(os.environ["CLAUDE_CONFIG_DIR"])
with open(os.environ["FAKE_CLAUDE_LOG"], "a", encoding="utf-8") as f:
    f.write(json.dumps({"argv": sys.argv[1:], "cfg": str(cfg)}) + "\n")
if os.environ.get("FAKE_CLAUDE_NOOP"):
    sys.exit(0)
def load(p, d):
    return json.loads(p.read_text()) if p.exists() else d
def save(p, v):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(v, indent=2))
st, km, ip = cfg / "settings.json", cfg / "plugins" / "known_marketplaces.json", cfg / "plugins" / "installed_plugins.json"
a = sys.argv[1:]
if a == ["--version"]:
    print("9.9.9 (Claude Code)")
elif a[:3] == ["plugin", "marketplace", "add"]:
    src = pathlib.Path(a[3])
    name = json.loads((src / ".claude-plugin" / "marketplace.json").read_text())["name"]
    s = load(st, {}); s.setdefault("extraKnownMarketplaces", {})[name] = {"source": {"source": "directory", "path": str(src)}}; save(st, s)
    k = load(km, {}); k[name] = {"source": {"source": "directory", "path": str(src)}, "installLocation": str(src)}; save(km, k)
elif a[:3] == ["plugin", "marketplace", "update"]:
    pass
elif a[:2] == ["plugin", "install"]:
    plugin, mp = a[2].split("@")
    src = pathlib.Path(load(km, {})[mp]["installLocation"])
    entry = next(p for p in json.loads((src / ".claude-plugin" / "marketplace.json").read_text())["plugins"] if p["name"] == plugin)
    psrc = (src / entry["source"]).resolve()
    ver = json.loads((psrc / ".claude-plugin" / "plugin.json").read_text()).get("version") or "unknown"
    dest = cfg / "plugins" / "cache" / mp / plugin / ver
    shutil.rmtree(dest, ignore_errors=True); shutil.copytree(psrc, dest)
    i = load(ip, {"version": 2, "plugins": {}}); i["plugins"][a[2]] = [{"scope": "user", "installPath": str(dest), "version": ver}]; save(ip, i)
    s = load(st, {}); s.setdefault("enabledPlugins", {})[a[2]] = True; save(st, s)
elif a[:2] == ["plugin", "uninstall"]:
    i = load(ip, {"version": 2, "plugins": {}}); i["plugins"].pop(a[2], None); save(ip, i)
    s = load(st, {}); s.setdefault("enabledPlugins", {}).pop(a[2], None); save(st, s)
else:
    print("fake claude: 知らない引数 " + " ".join(a), file=sys.stderr); sys.exit(1)
'''


def write_fake_claude(where: pathlib.Path) -> pathlib.Path:
    """偽の claude を where/claude に置いて返す（呼んだ記録は env の FAKE_CLAUDE_LOG へ）。test_dev も使う"""
    where.mkdir(parents=True, exist_ok=True)
    p = where / "claude"
    p.write_text(FAKE_CLAUDE, encoding="utf-8")
    p.chmod(0o755)
    return p


def files_under(base: pathlib.Path) -> list:
    return sorted(p.relative_to(base).as_posix() for p in base.rglob("*") if p.is_file())


def plugin_version(src: pathlib.Path) -> str:
    """偽の claude がキャッシュの置き場に使う版（plugin.json に version が無ければ unknown）"""
    return json.loads((src / ".claude-plugin" / "plugin.json").read_text()).get("version") or "unknown"


PLUGINS = ("coldwrite", "pr-review-toolkit")   # 手元の marketplace に並ぶ名の順（sorted）
CONTEXT7_URL = "https://mcp.context7.com/mcp"   # Context7 の MCP（upstash/context7 の README の手で入れる形。MIT）


class Base(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = pathlib.Path(self._tmp.name)
        self.cfg = self.tmp / "claude-config"
        self.cfg.mkdir()
        self.claude = write_fake_claude(self.tmp / "bin")
        self.log = self.tmp / "claude-calls.jsonl"
        self._env = mock.patch.dict(os.environ, {"FAKE_CLAUDE_LOG": str(self.log)})
        self._env.start()
        self.borrow = toolset.load_borrow(ROOT)
        self.user = make_user_config(self.tmp / "user")

    def tearDown(self):
        self._env.stop()
        self._tmp.cleanup()

    def calls(self):
        """偽の claude が受けた argv の一覧（どれも隔離した設定の置き場で起きたこと）"""
        if not self.log.exists():
            return []
        rows = [json.loads(ln) for ln in self.log.read_text().splitlines()]
        for r in rows:
            self.assertEqual(r["cfg"], str(self.cfg))
        return [r["argv"] for r in rows]

    def sources(self):
        return toolset.installed_sources(self.user, self.borrow)

    def install(self, chosen=None, versions=None):
        found, vers = self.sources()
        return toolset.install(self.cfg, chosen or found, self.borrow, claude_bin=str(self.claude),
                               versions=vers if versions is None else versions)

    def cli(self, *args, **env):
        """CLI を子で起こす。利用者の設定の置き場は env の CLAUDE_CONFIG_DIR（既定は偽の利用者の設定）"""
        return subprocess.run([sys.executable, str(TOOLSET), *args], capture_output=True, text=True, encoding="utf-8",
                              env=dict(os.environ, **{"CLAUDE_CONFIG_DIR": str(self.user), **env}))



def plain_files(base: pathlib.Path) -> list:
    """files_under から Claude Code のキャッシュの印（.in_use/・.orphaned_at）を除いた物（隔離した設定に写る物）"""
    return [f for f in files_under(base) if not toolset.MARKERS & set(f.split("/"))]


class BorrowListCase(unittest.TestCase):
    def test_borrow_json_names_installed_plugins(self):
        """借りる物は利用者が入れたプラグインの <名>@<marketplace> で名指し、入れるコマンドの marketplace の元（GitHub）を持つ。
        works が名前で頼る物（スキル・agent・hook）だけを並べる。写しを示す印（pinned）は無い"""
        b = toolset.load_borrow(ROOT)
        self.assertEqual(sorted(b), ["coldwrite", "context7", "pr-review-toolkit", "superpowers"])
        self.assertEqual(sorted(b["superpowers"]["skills"]), sorted(BORROW_SKILLS))
        want = {"superpowers": ("superpowers-marketplace", "obra/superpowers-marketplace"),
                "coldwrite": ("raiki61", "raiki61/claude-plugins"),
                "pr-review-toolkit": ("claude-plugins-official", "anthropics/claude-plugins-official")}
        for name, (mp, repo) in want.items():
            with self.subTest(name):
                self.assertEqual((b[name]["marketplace"], b[name]["marketplace_repo"]), (mp, repo))
                self.assertNotIn("pinned", b[name])
        self.assertEqual(b["superpowers"]["kind"], "skills")
        self.assertEqual(b["coldwrite"], {"kind": "plugin", "marketplace": "raiki61", "marketplace_repo": "raiki61/claude-plugins",
                                          "hooks": {"PreToolUse": ["Write"]}})
        self.assertEqual(b["pr-review-toolkit"]["agents"], LENSES)

    def test_lens_names_cover_what_the_graph_calls(self):
        """局所レビューと独立の目が名指しで起こす pr-review-toolkit の agent（写しの graph の skill・agent_type）は、全部
        borrow.json の agents に在る（まとめ役 review-pr は起こさない）"""
        g = (ROOT / ".shared" / "core" / "graphloops" / "graphs" / "review-loop.json").read_text(encoding="utf-8")
        used = set(re.findall(r'"(?:skill|agent_type)": "pr-review-toolkit:([a-z-]+)"', g))
        self.assertTrue(used)
        self.assertEqual(sorted(used - set(toolset.load_borrow(ROOT)["pr-review-toolkit"]["agents"])), [])

    def test_no_vendored_copies(self):
        """works は借りる物の写しを持たない（利用者が入れた版に従う）"""
        for name in ("superpowers", "pr-review-toolkit", "coldwrite"):
            self.assertFalse((ROOT / ".shared" / name).exists(), name)
        self.assertFalse((ROOT / "NOTICE").exists())


class ResolveCase(unittest.TestCase):
    """installed_sources: 利用者が入れたプラグインからだけ取る。無ければ 1 物 1 行の理由と入れるコマンドで止まる"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = pathlib.Path(self._tmp.name)
        self.borrow = toolset.load_borrow(ROOT)

    def tearDown(self):
        self._tmp.cleanup()

    def test_user_scope_rows_are_used(self):
        user = make_user_config(self.tmp / "user")
        chosen, versions = toolset.installed_sources(user, self.borrow)
        self.assertEqual(chosen, {n: installed_dir(user, n) for n in FAKE_INSTALLED}
                         | {"context7": self.borrow["context7"]["url"]})
        self.assertEqual(versions, {n: v for n, (_, v) in FAKE_INSTALLED.items()} | {"context7": self.borrow["context7"]["version"]})

    def test_project_rows_count_only_for_their_project(self):
        target = self.tmp / "target"
        target.mkdir()
        user = make_user_config(self.tmp / "user", scope="project", project=target)
        chosen, _ = toolset.installed_sources(user, self.borrow, cwd=target)
        self.assertEqual(chosen["coldwrite"], installed_dir(user, "coldwrite"))
        with self.assertRaises(toolset.ToolsetError):
            toolset.installed_sources(user, self.borrow, cwd=self.tmp)

    def test_missing_tools_are_listed_one_line_each_with_install_commands(self):
        """何も入っていない利用者: 借りる 3 つが 1 行ずつ、入れる marketplace と install のコマンドつきで並ぶ"""
        user = self.tmp / "empty"
        user.mkdir()
        with self.assertRaises(toolset.ToolsetError) as cm:
            toolset.installed_sources(user, self.borrow)
        lines = str(cm.exception).splitlines()[1:]
        self.assertEqual(len(lines), 3, lines)
        for key, repo in (("superpowers@superpowers-marketplace", "obra/superpowers-marketplace"),
                          ("coldwrite@raiki61", "raiki61/claude-plugins"),
                          ("pr-review-toolkit@claude-plugins-official", "anthropics/claude-plugins-official")):
            line = next(ln for ln in lines if key in ln)
            self.assertIn(f"claude plugin marketplace add {repo}", line)
            self.assertIn(f"claude plugin install {key}", line)

    def test_only_the_missing_one_is_named(self):
        user = make_user_config(self.tmp / "user", only={"superpowers", "coldwrite"})
        with self.assertRaises(toolset.ToolsetError) as cm:
            toolset.installed_sources(user, self.borrow)
        lines = str(cm.exception).splitlines()[1:]
        self.assertEqual(len(lines), 1, lines)
        self.assertIn("pr-review-toolkit が入っていない", lines[0])

    def test_install_path_that_is_gone_counts_as_not_installed(self):
        user = make_user_config(self.tmp / "user")
        shutil.rmtree(installed_dir(user, "coldwrite"))
        with self.assertRaises(toolset.ToolsetError) as cm:
            toolset.installed_sources(user, self.borrow)
        self.assertIn("coldwrite が入っていない", str(cm.exception))

    def test_missing_names_stop_with_the_name(self):
        """works が名前で頼る物が無い版は止める（名前が API）。無い名前を出す"""
        cases = {
            "スキル verification-before-completion": lambda u: shutil.rmtree(
                installed_dir(u, "superpowers") / "skills" / "verification-before-completion"),
            "agent comment-analyzer": lambda u: (installed_dir(u, "pr-review-toolkit") / "agents" / "comment-analyzer.md").unlink(),
            "hook PreToolUse:Write": lambda u: _put(installed_dir(u, "coldwrite") / "hooks" / "hooks.json",
                                                    json.dumps({"hooks": {"PreToolUse": [{"matcher": "Edit"}]}})),
        }
        for want, breakit in cases.items():
            with self.subTest(want):
                user = make_user_config(self.tmp / want.split()[1])
                breakit(user)
                with self.assertRaises(toolset.ToolsetError) as cm:
                    toolset.installed_sources(user, self.borrow)
                lines = str(cm.exception).splitlines()[1:]
                self.assertEqual(len(lines), 1, lines)
                self.assertIn(want, lines[0])

    def test_content_and_version_are_not_checked(self):
        """名前が在れば、中身が変わった新しい版でも通る（役は読むだけ）"""
        user = make_user_config(self.tmp / "user")
        _put(installed_dir(user, "superpowers") / "skills" / "test-driven-development" / "SKILL.md", "まったく別の文\n")
        _put(installed_dir(user, "pr-review-toolkit") / "agents" / "code-reviewer.md", "新しい版の文\n")
        chosen, _ = toolset.installed_sources(user, self.borrow)
        self.assertEqual(chosen["superpowers"], installed_dir(user, "superpowers"))

    def test_user_config_dir_follows_env(self):
        self.assertEqual(toolset.user_config_dir({"CLAUDE_CONFIG_DIR": "/x/cfg"}), pathlib.Path("/x/cfg"))
        self.assertEqual(toolset.user_config_dir({}), pathlib.Path(os.path.expanduser("~/.claude")))


class ScopeCase(unittest.TestCase):
    """同じプラグインが複数の scope に入っていれば、Claude Code と同じく local > project > user の行を取る
    （https://code.claude.com/docs/en/discover-plugins の Which scope wins）。enabledPlugins の無効は拒まずに借り、
    元が有効だったか無効だったかを記録に残す（人の答え: 利用者は借りる物のフックを普段効かせないために無効にしておく）"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = pathlib.Path(self._tmp.name)
        self.borrow = toolset.load_borrow(ROOT)
        self.target = self.tmp / "target"
        self.target.mkdir()
        self.user = make_user_config(self.tmp / "user")

    def tearDown(self):
        self._tmp.cleanup()

    def add_rows(self, scope: str) -> pathlib.Path:
        """scope の行（projectPath は対象）を、別の置き場に入れた物として利用者の installed_plugins.json に足す"""
        other = make_user_config(self.tmp / scope, scope=scope, project=self.target)
        ip_path = self.user / "plugins" / "installed_plugins.json"
        ip = json.loads(ip_path.read_text())
        for key, rows in json.loads((other / "plugins" / "installed_plugins.json").read_text())["plugins"].items():
            ip["plugins"][key] = ip["plugins"].get(key, []) + rows
        ip_path.write_text(json.dumps(ip, indent=2))
        return other

    def test_project_row_wins_over_user_row(self):
        project = self.add_rows("project")
        chosen, _ = toolset.installed_sources(self.user, self.borrow, cwd=self.target)
        for n in FAKE_INSTALLED:
            self.assertEqual(chosen[n], installed_dir(project, n), n)

    def test_local_row_wins_over_project_and_user_rows(self):
        self.add_rows("project")
        local = self.add_rows("local")
        chosen, _ = toolset.installed_sources(self.user, self.borrow, cwd=self.target)
        for n in FAKE_INSTALLED:
            self.assertEqual(chosen[n], installed_dir(local, n), n)

    def test_disabled_plugin_is_borrowed_and_the_source_state_is_recorded(self):
        """利用者の settings.json で無効でも借りる。対象の .claude/settings.local.json・settings.json が利用者の値に勝つ。
        記録の source_enabled は、元で勝った enabledPlugins の値（どこにも鍵が無ければ null）"""
        _put(self.user / "settings.json", json.dumps({"enabledPlugins": {
            "coldwrite@raiki61": False, "superpowers@superpowers-marketplace": False}}))
        _put(self.target / ".claude" / "settings.json", json.dumps({"enabledPlugins": {
            "superpowers@superpowers-marketplace": True}}))
        cfg = self.tmp / "claude-config"
        cfg.mkdir()
        r = subprocess.run([sys.executable, str(TOOLSET), "install", "--no-plugins", "--user-config", str(self.user), str(cfg)],
                           capture_output=True, text=True, encoding="utf-8", cwd=self.target,
                           env={k: v for k, v in os.environ.items() if k != "CLAUDE_CONFIG_DIR"})
        self.assertEqual(r.returncode, 0, r.stderr)
        rec = json.loads((cfg / toolset.RECORD).read_text())
        self.assertEqual(rec["coldwrite"]["source"], str(installed_dir(self.user, "coldwrite")))
        self.assertEqual({n: rec[n].get("source_enabled", "無い") for n in FAKE_INSTALLED},
                         {"coldwrite": False, "superpowers": True, "pr-review-toolkit": None})


class InstalledShapeCase(unittest.TestCase):
    """installed_plugins.json は Claude Code の内部の状態で、形の約束（文書）が無い。知らない形は『入っていない』に潰さず、
    形を知らないと名指しして止まる（入れ直しても直らない install のコマンドを勧めない）"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = pathlib.Path(self._tmp.name)
        self.borrow = toolset.load_borrow(ROOT)

    def tearDown(self):
        self._tmp.cleanup()

    def test_unknown_shape_stops_with_named_reason_not_as_missing(self):
        def reshape(ip, how):
            if how == "version 1":
                ip["version"] = 1
            elif how == "version 無し":
                del ip["version"]
            elif how == "行が表（古い 1 行の形）":
                ip["plugins"] = {k: rows[0] for k, rows in ip["plugins"].items()}
            elif how == "plugins が一覧":
                ip["plugins"] = [dict(r, key=k) for k, rows in ip["plugins"].items() for r in rows]
            return ip
        for how in ("version 1", "version 無し", "行が表（古い 1 行の形）", "plugins が一覧"):
            with self.subTest(how):
                user = make_user_config(self.tmp / f"u{len(how)}{how[:3]}")
                p = user / "plugins" / "installed_plugins.json"
                p.write_text(json.dumps(reshape(json.loads(p.read_text()), how)))
                try:
                    toolset.installed_sources(user, self.borrow)
                except toolset.ToolsetError as e:
                    msg = str(e)
                except Exception as e:   # 形を確かめずに読んで落ちるのも、名指しの理由で止まらない欠陥
                    self.fail(f"ToolsetError でなく {type(e).__name__}: {e}")
                else:
                    self.fail("知らない形なのに止まらなかった")
                self.assertIn("知らない", msg)
                self.assertIn(str(p), msg)
                self.assertNotIn("入っていない", msg)
                self.assertNotIn("claude plugin install", msg)


class InstallCase(Base):
    def test_install_builds_exactly_the_chosen_config(self):
        """一時の置き場に組んだ設定の中身が、ちょうど 5 つのスキル・手元の marketplace の coldwrite と pr-review-toolkit・
        その入れた状態だけ。写す元は利用者が入れた置き場で、キャッシュの印は写さない"""
        rec = self.install()
        srcs = {"coldwrite": installed_dir(self.user, "coldwrite"), "pr-review-toolkit": installed_dir(self.user, "pr-review-toolkit")}
        sp = installed_dir(self.user, "superpowers")
        want = sorted(
            [f"skills/{n}/{f}" for n in BORROW_SKILLS for f in files_under(sp / "skills" / n)]
            + [f"works-marketplace/{n}/{f}" for n, s in srcs.items() for f in plain_files(s)]
            + ["works-marketplace/.claude-plugin/marketplace.json", "settings.json", ".works-toolset.json", toolset.MCP_FILE,
               "plugins/known_marketplaces.json", "plugins/installed_plugins.json"]
            + [f"plugins/cache/{MP}/{n}/{plugin_version(s)}/{f}" for n, s in srcs.items() for f in plain_files(s)])
        self.assertEqual(files_under(self.cfg), want)
        # スキルとプラグインの写しはバイトのまま・権限つき・symlink でない
        for n in BORROW_SKILLS:
            for rel in files_under(sp / "skills" / n):
                a, b = self.cfg / "skills" / n / rel, sp / "skills" / n / rel
                self.assertEqual(a.read_bytes(), b.read_bytes(), rel)
                self.assertFalse(a.is_symlink())
                self.assertEqual(os.access(a, os.X_OK), os.access(b, os.X_OK), rel)
        for n, s in srcs.items():
            for rel in plain_files(s):
                self.assertEqual((self.cfg / "works-marketplace" / n / rel).read_bytes(), (s / rel).read_bytes(), rel)
        self.assertEqual(json.loads((self.cfg / "works-marketplace" / ".claude-plugin" / "marketplace.json").read_text()),
                         {"name": MP, "owner": {"name": "works"},
                          "plugins": [{"name": n, "source": f"./{n}", "strict": False} for n in PLUGINS]})
        self.assertEqual(json.loads((self.cfg / "settings.json").read_text()),
                         {"extraKnownMarketplaces": {MP: {"source": {"source": "directory",
                                                                     "path": str(self.cfg / "works-marketplace")}}},
                          "enabledPlugins": {f"{n}@{MP}": True for n in PLUGINS}})
        self.assertEqual(self.calls(), [["plugin", "marketplace", "add", str(self.cfg / "works-marketplace")]]
                         + [["plugin", "install", f"{n}@{MP}"] for n in PLUGINS])
        # 記録: 版は installed_plugins.json の行の物、source は利用者が入れた置き場（versions.json の borrowed に載る）
        self.assertEqual(sorted(rec), ["coldwrite", "context7", "pr-review-toolkit", "superpowers"])
        self.assertEqual({k: (v["version"], v["source"], v["loaded"]) for k, v in rec.items()},
                         {n: (ver, str(installed_dir(self.user, n)), True) for n, (_, ver) in FAKE_INSTALLED.items()}
                         | {"context7": (self.borrow["context7"]["version"], self.borrow["context7"]["url"], True)})
        self.assertEqual(json.loads((self.cfg / ".works-toolset.json").read_text()), rec)
        self.assertEqual(toolset.guard(self.cfg, self.borrow), [])

    def test_second_install_calls_nothing_and_changes_nothing(self):
        """キャッシュの印が変わっても（Claude Code が pid を書き換える）、入れ直さない"""
        self.install()
        before = {f: (self.cfg / f).read_bytes() for f in files_under(self.cfg)}
        self.log.unlink()
        _put(installed_dir(self.user, "coldwrite") / ".in_use" / "9999", "{}")
        self.install()
        self.assertEqual(self.calls(), [])
        self.assertEqual({f: (self.cfg / f).read_bytes() for f in files_under(self.cfg)}, before)

    def test_changed_plugin_is_recopied_and_reinstalled(self):
        """利用者のプラグインが新しい版になれば（Claude Code が今に保つ）、写し直して入れ直す"""
        src = installed_dir(self.user, "coldwrite")
        self.install()
        self.log.unlink()
        (src / "hooks" / "hooks.json").write_text('{"hooks": {"PreToolUse": [{"matcher": "Write"}]}}\n', encoding="utf-8")
        self.install()
        key = f"coldwrite@{MP}"
        self.assertEqual(self.calls(), [["plugin", "marketplace", "update", MP], ["plugin", "uninstall", key],
                                        ["plugin", "install", key]])
        self.assertEqual((self.cfg / "works-marketplace" / "coldwrite" / "hooks" / "hooks.json").read_text(),
                         '{"hooks": {"PreToolUse": [{"matcher": "Write"}]}}\n')

    def test_stale_skill_copy_and_exec_bit_are_fixed(self):
        sp = installed_dir(self.user, "superpowers")
        self.install()
        tdd = self.cfg / "skills" / "test-driven-development"
        (tdd / "SKILL.md").write_text("古い\n", encoding="utf-8")
        (tdd / "extra.md").write_text("余分\n", encoding="utf-8")
        polluter = self.cfg / "skills" / "systematic-debugging" / "find-polluter.sh"
        polluter.chmod(0o644)
        self.install()
        self.assertEqual(files_under(tdd), files_under(sp / "skills" / "test-driven-development"))
        self.assertEqual((tdd / "SKILL.md").read_bytes(), (sp / "skills" / "test-driven-development" / "SKILL.md").read_bytes())
        self.assertTrue(os.access(polluter, os.X_OK))
        self.assertEqual(sorted(p.name for p in (self.cfg / "skills").iterdir()), sorted(BORROW_SKILLS),
                         "作業の一時の置き場か、借りない物が残っている")

    def test_plugin_not_enabled_after_cli_fails_closed(self):
        """CLI が 0 で終わっても coldwrite が有効になっていなければ、入ったことにしない（フックの効かない役を起こさない）"""
        with mock.patch.dict(os.environ, {"FAKE_CLAUDE_NOOP": "1"}):
            with self.assertRaises(toolset.ToolsetError) as cm:
                self.install()
        self.assertIn("coldwrite", str(cm.exception))

    def test_cli_error_is_reported(self):
        bad = self.tmp / "bin" / "claude-bad"
        bad.write_text("#!/bin/sh\necho 'boom' >&2\nexit 7\n", encoding="utf-8")
        bad.chmod(0o755)
        chosen, versions = self.sources()
        with self.assertRaises(toolset.ToolsetError) as cm:
            toolset.install(self.cfg, chosen, self.borrow, claude_bin=str(bad), versions=versions)
        self.assertIn("boom", str(cm.exception))


class GuardCase(Base):
    def put(self, rel, body="x\n"):
        p = self.cfg / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body, encoding="utf-8")

    def test_guard_refuses_foreign(self):
        """一覧の外を 1 つずつ置くと、そのたびにちょうど 1 つ、名前つきで並ぶ"""
        cases = {
            "CLAUDE.md": lambda: self.put("CLAUDE.md"),
            "settings.local.json": lambda: self.put("settings.local.json", "{}"),
            "rules/": lambda: self.put("rules/a.md"),
            "agents/": lambda: self.put("agents/a.md"),
            "commands/": lambda: self.put("commands/a.md"),
            "output-styles/": lambda: self.put("output-styles/a.md"),
            "skills/mine/": lambda: self.put("skills/mine/SKILL.md"),
            "settings.json の鍵 permissions": lambda: self.put("settings.json", '{"permissions": {"allow": []}}'),
            "settings.json の鍵 hooks": lambda: self.put("settings.json", '{"hooks": {}}'),
            "有効なプラグイン other@x": lambda: self.put("settings.json", '{"enabledPlugins": {"other@x": true}}'),
            "marketplace x（settings.json）": lambda: self.put("settings.json", '{"extraKnownMarketplaces": {"x": {}}}'),
            "入れたプラグイン other@x": lambda: self.put("plugins/installed_plugins.json",
                                                        '{"version": 2, "plugins": {"other@x": []}}'),
            "marketplace x（plugins/known_marketplaces.json）": lambda: self.put("plugins/known_marketplaces.json",
                                                                                  '{"x": {}}'),
            "settings.json（JSON の表として読めない）": lambda: self.put("settings.json", "{"),
        }
        for name, make in cases.items():
            with self.subTest(name):
                shutil.rmtree(self.cfg)
                self.cfg.mkdir()
                make()
                found = toolset.guard(self.cfg, self.borrow)
                self.assertEqual(found, [name])
                r = self.cli("guard", str(self.cfg))
                self.assertEqual(r.returncode, 2, r.stderr)
                self.assertIn(name, r.stderr)
                self.assertEqual(len(r.stderr.strip().splitlines()), 1, r.stderr)

    def test_guard_ignores_claude_state(self):
        for rel in ("projects/p/s.jsonl", ".claude.json", "backups/.claude.json.backup.1", "remote-settings.json",
                    "policy-limits.json", "plugins/cache/x/y/1/a", "plugins/marketplaces/x/a", "skills/.DS_Store"):
            self.put(rel)
        self.assertEqual(toolset.guard(self.cfg, self.borrow), [])
        self.assertEqual(self.cli("guard", str(self.cfg)).returncode, 0)

    def test_install_refuses_before_writing(self):
        self.put("CLAUDE.md")
        r = self.cli("install", "--claude", str(self.claude), str(self.cfg))
        self.assertEqual(r.returncode, 2, r.stderr)
        self.assertIn("CLAUDE.md", r.stderr)
        self.assertEqual(files_under(self.cfg), ["CLAUDE.md"], "止まる前に写した")
        self.assertEqual(self.calls(), [])


class CliCase(Base):
    def test_cli_install_matches_api(self):
        r = self.cli("install", "--claude", str(self.claude), str(self.cfg))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(toolset.guard(self.cfg, self.borrow), [])
        self.assertEqual(json.loads((self.cfg / "settings.json").read_text())["enabledPlugins"],
                         {f"{n}@{MP}": True for n in PLUGINS})
        self.assertEqual(sorted(p.name for p in (self.cfg / "skills").iterdir()), sorted(BORROW_SKILLS))

    def test_cli_no_plugins_copies_skills_and_calls_no_claude(self):
        """認証の要らない道（validate・テスト）は claude を起こさない。スキルは写す（Archon の validate も同じ置き場で探す）"""
        r = self.cli("install", "--no-plugins", str(self.cfg))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.calls(), [])
        self.assertEqual(sorted(p.name for p in (self.cfg / "skills").iterdir()), sorted(BORROW_SKILLS))
        self.assertFalse((self.cfg / "settings.json").exists())
        self.assertFalse((self.cfg / "works-marketplace").exists())

    def test_cli_missing_tools_stop_before_writing(self):
        """借りる物が入っていなければ、1 物 1 行の理由と入れるコマンドを出して終了コード 2。何も写さず claude も起こさない。
        --user-config が env の CLAUDE_CONFIG_DIR より勝つ"""
        empty = self.tmp / "empty"
        empty.mkdir()
        for args, env in ((["--user-config", str(empty)], {}), ([], {"CLAUDE_CONFIG_DIR": str(empty)})):
            with self.subTest(args=args):
                r = self.cli("install", "--claude", str(self.claude), *args, str(self.cfg), **env)
                self.assertEqual(r.returncode, 2, r.stderr)
                self.assertEqual(len([ln for ln in r.stderr.splitlines() if ln.startswith("- ")]), 3, r.stderr)
                self.assertIn("claude plugin install superpowers@superpowers-marketplace", r.stderr)
                self.assertEqual(files_under(self.cfg), [])
                self.assertEqual(self.calls(), [])
        r = self.cli("install", "--no-plugins", str(self.cfg), CLAUDE_CONFIG_DIR=str(empty))
        self.assertEqual(r.returncode, 2, r.stderr)
        self.assertIn("coldwrite@raiki61", r.stderr)

    def test_cli_refuses_relative_user_config(self):
        """利用者の設定の置き場は絶対パスだけを受ける（相対は殻が cd の前に直す。cd の後に対象から解くと別の置き場を読む）。
        --user-config も env の CLAUDE_CONFIG_DIR も、相対なら何も写さずに名指しで止まる（読める置き場が cwd に在っても）"""
        for args, env in ((["--user-config", "user"], {}), ([], {"CLAUDE_CONFIG_DIR": "user"})):
            with self.subTest(args=args, env=env):
                r = subprocess.run([sys.executable, str(TOOLSET), "install", "--no-plugins", *args, str(self.cfg)],
                                   capture_output=True, text=True, encoding="utf-8", cwd=self.tmp,
                                   env=dict(os.environ, **{"CLAUDE_CONFIG_DIR": str(self.user), **env}))
                self.assertEqual(r.returncode, 2, r.stderr)
                self.assertIn("絶対", r.stderr)
                self.assertEqual(files_under(self.cfg), [])

    def test_cli_refuses_user_config_that_is_the_isolated_config(self):
        """殻の中から入れ子で打つと、利用者の設定の置き場が隔離した置き場そのものになる。『入っていない』でなく、それを名指しして
        止まる（symlink を挟んでも同じ置き場と見る）"""
        link = self.tmp / "cfg-link"
        link.symlink_to(self.cfg)
        for where in (self.cfg, link):
            for args, env in ((["--user-config", str(where)], {}), ([], {"CLAUDE_CONFIG_DIR": str(where)})):
                with self.subTest(where=where.name, args=args):
                    r = self.cli("install", "--no-plugins", *args, str(self.cfg), **env)
                    self.assertEqual(r.returncode, 2, r.stderr)
                    self.assertIn("隔離", r.stderr)
                    self.assertNotIn("入っていない", r.stderr)
                    self.assertEqual(files_under(self.cfg), [])

    def test_cli_usage(self):
        for args in ([], ["install"], ["install", str(self.cfg)], ["bogus", str(self.cfg)], ["guard"]):
            with self.subTest(args):
                r = self.cli(*args)
                self.assertEqual(r.returncode, 2, r.stderr)
                self.assertIn("toolset.py", r.stderr)


if __name__ == "__main__":
    unittest.main()


class McpCase(Base):
    """借りる MCP（kind "mcp"。Context7）: 使用許諾が MIT・Apache-2.0・BSD の時だけ、隔離した設定の置き場の works-mcp.json に
    載せる（Archon の役の節は周りの MCP を読まない——strictMcpConfig——ので、包みがこのファイルを --mcp-config で渡す）"""

    def test_borrow_entry_is_the_remote_context7_server(self):
        c7 = self.borrow["context7"]
        self.assertEqual(c7["kind"], "mcp")
        self.assertEqual(c7["transport"], "http")
        self.assertEqual(c7["url"], CONTEXT7_URL)
        self.assertEqual(c7["licence"], "MIT")
        self.assertIn("upstash/context7", c7["source"])

    def test_install_writes_the_mcp_file_when_licence_ok(self):
        rec = self.install()
        doc = json.loads((self.cfg / toolset.MCP_FILE).read_text())
        self.assertEqual(doc, {"mcpServers": {"context7": {"type": "http", "url": CONTEXT7_URL}}})
        self.assertEqual(rec["context7"]["source"], CONTEXT7_URL)
        self.assertEqual(toolset.guard(self.cfg, self.borrow), [])

    def test_licence_not_ok_refuses_and_writes_nothing(self):
        for lic in ("SSPL-1.0", "", None, "proprietary"):
            with self.subTest(lic):
                bad = {"context7": dict(self.borrow["context7"], licence=lic)}   # 借りる物は MCP だけ（リポジトリの外の置き場に依らない）
                with self.assertRaises(toolset.ToolsetError) as cm:
                    toolset.install(self.cfg, {"context7": CONTEXT7_URL}, bad, claude_bin=str(self.claude), plugins=False)
                self.assertIn("使用許諾", str(cm.exception))
                self.assertFalse((self.cfg / toolset.MCP_FILE).exists())

    def test_licence_ok_writes_the_file_without_other_borrowings(self):
        good = {"context7": self.borrow["context7"]}
        rec = toolset.install(self.cfg, {"context7": CONTEXT7_URL}, good, claude_bin=str(self.claude), plugins=False)
        self.assertEqual(sorted(rec), ["context7"])
        self.assertEqual(json.loads((self.cfg / toolset.MCP_FILE).read_text())["mcpServers"],
                         {"context7": {"type": "http", "url": CONTEXT7_URL}})

    def test_guard_refuses_unlisted_mcp_server(self):
        (self.cfg / toolset.MCP_FILE).write_text(json.dumps({"mcpServers": {"context7": {"type": "http", "url": CONTEXT7_URL},
                                                                          "evil": {"command": "sh"}}}))
        self.assertEqual(toolset.guard(self.cfg, self.borrow), [f"{toolset.MCP_FILE} の MCP evil"])
        (self.cfg / toolset.MCP_FILE).write_text("[]")
        self.assertEqual(toolset.guard(self.cfg, self.borrow), [f"{toolset.MCP_FILE}（JSON の表として読めない）"])

    def test_changed_url_is_rewritten(self):
        self.install()
        (self.cfg / toolset.MCP_FILE).write_text(json.dumps({"mcpServers": {"context7": {"type": "http", "url": "https://x.invalid"}}}))
        self.install()
        self.assertEqual(json.loads((self.cfg / toolset.MCP_FILE).read_text())["mcpServers"]["context7"]["url"], CONTEXT7_URL)
