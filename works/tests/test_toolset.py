"""選んだ物だけの隔離した Claude の設定（dev/toolset.py。P1 計画 Task 20 の R61 の範囲）の検査。

AI の節は全部 settingSources: [user] で、開発の殻（dev/archon.sh）が隔離した CLAUDE_CONFIG_DIR を読む。そこに置くのは
許す一覧（.shared/borrow/borrow.json）の物だけ:
- superpowers の 5 つのスキル（.shared/superpowers/<版>/skills/<名>/）を skills/<名>/ へバイトのまま写す（プラグインとしては入れない。
  有効にすると SessionStart の hook が using-superpowers を差し込むため。裁定 P1-R8）。
- coldwrite（このリポジトリの coldwrite/。marketplace raiki61 の同じ物）を、設定の中の手元の marketplace works-local
  （works-marketplace/）に写し、Claude Code の CLI（claude plugin marketplace add・install）で入れる。
柵（guard）は一覧の外（CLAUDE.md・rules/・agents/・commands/・output-styles/・settings.json 以外の settings*.json・
一覧の外のスキル・settings.json の許す鍵の外・一覧の外のプラグインと marketplace）を名前で並べ、CLI は終了コード 2 で止まる。
Claude Code が自分で書く状態（projects/・.claude.json・backups/・remote-settings.json など）は見ない。

本物の claude は起こさない。偽の claude（FAKE_CLAUDE。受けた argv を記録し、本物の 2.1.283 と同じ形で settings.json・
plugins/ の状態のファイルを書く）を渡す。形は本物の CLI で一時の置き場に入れて確かめた（報告 $S/r61/cfg-report.md）。
"""
import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parents[1]
DEV = ROOT / "dev"
REPO = ROOT.parent
TOOLSET = DEV / "toolset.py"
sys.dont_write_bytecode = True
sys.path.insert(0, str(DEV))
import toolset  # noqa: E402

SP = ROOT / ".shared" / "superpowers"
BORROW_SKILLS = ["test-driven-development", "systematic-debugging", "verification-before-completion",
                 "receiving-code-review", "requesting-code-review"]
COLDWRITE = REPO / "coldwrite"
PRT = ROOT / ".shared" / "pr-review-toolkit"   # pr-review-toolkit（Anthropic。Apache-2.0）の版を固めた写し .shared/pr-review-toolkit/<版>/
MP = "works-local"

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
if a[:3] == ["plugin", "marketplace", "add"]:
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


def pinned(base: pathlib.Path = SP) -> pathlib.Path:
    dirs = [p for p in base.iterdir() if p.is_dir()]
    assert len(dirs) == 1, dirs
    return dirs[0]


def plugin_version(src: pathlib.Path) -> str:
    """偽の claude がキャッシュの置き場に使う版（plugin.json に version が無ければ unknown）"""
    return json.loads((src / ".claude-plugin" / "plugin.json").read_text()).get("version") or "unknown"


PLUGINS = ("coldwrite", "pr-review-toolkit")   # 手元の marketplace に並ぶ名の順（sorted）


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

    def install(self, chosen=None):
        return toolset.install(self.cfg, chosen or toolset.fixed_sources(ROOT, self.borrow), self.borrow,
                               claude_bin=str(self.claude))

    def cli(self, *args, **env):
        return subprocess.run([sys.executable, str(TOOLSET), *args], capture_output=True, text=True,
                              env=dict(os.environ, **env))



class BorrowListCase(unittest.TestCase):
    def test_borrow_json_is_superpowers_skills_and_coldwrite(self):
        b = toolset.load_borrow(ROOT)
        self.assertEqual(sorted(b), ["coldwrite", "pr-review-toolkit", "superpowers"])
        # pr-review-toolkit は版を固めた写し（.shared/pr-review-toolkit/<版>/）から入れる。素材集めの局所レビューのレンズ（agent）
        self.assertEqual(b["pr-review-toolkit"], {"kind": "plugin", "pinned": True})
        self.assertEqual(b["superpowers"]["kind"], "skills")
        self.assertEqual(sorted(b["superpowers"]["skills"]), sorted(BORROW_SKILLS))
        self.assertEqual(b["coldwrite"], {"kind": "plugin", "marketplace": "raiki61"})

    def test_fixed_sources_are_the_pinned_copy_and_the_repo_plugin(self):
        chosen = toolset.fixed_sources(ROOT, toolset.load_borrow(ROOT))
        self.assertEqual(chosen, {"superpowers": pinned(), "coldwrite": COLDWRITE.resolve(), "pr-review-toolkit": pinned(PRT)})

    def test_pinned_plugin_copy_is_apache_and_complete(self):
        """写しは元のキャッシュの物をバイトのまま（COPIED_FROM が元と版を名指す）・使用許諾は Apache-2.0・agent のレンズが在る"""
        src = pinned(PRT)
        self.assertIn("Apache License", (src / "LICENSE").read_text(encoding="utf-8"))
        self.assertEqual(json.loads((src / ".claude-plugin" / "plugin.json").read_text())["name"], "pr-review-toolkit")
        for lens in ("code-reviewer", "silent-failure-hunter", "type-design-analyzer", "pr-test-analyzer", "comment-analyzer"):
            self.assertTrue((src / "agents" / f"{lens}.md").is_file(), lens)
        self.assertIn(src.name, (PRT / "COPIED_FROM").read_text(encoding="utf-8").splitlines()[0])
        self.assertIn("pr-review-toolkit", (ROOT / "NOTICE").read_text(encoding="utf-8"))


class InstallCase(Base):
    def test_install_builds_exactly_the_chosen_config(self):
        """一時の置き場に組んだ設定の中身が、ちょうど 5 つのスキル・手元の marketplace の coldwrite・その入れた状態だけ"""
        rec = self.install()
        srcs = {"coldwrite": COLDWRITE, "pr-review-toolkit": pinned(PRT)}
        cw_files = files_under(COLDWRITE)
        ver = plugin_version(COLDWRITE)
        want = sorted(
            [f"skills/{n}/{f}" for n in BORROW_SKILLS for f in files_under(pinned() / "skills" / n)]
            + [f"works-marketplace/{n}/{f}" for n, s in srcs.items() for f in files_under(s)]
            + ["works-marketplace/.claude-plugin/marketplace.json", "settings.json", ".works-toolset.json",
               "plugins/known_marketplaces.json", "plugins/installed_plugins.json"]
            + [f"plugins/cache/{MP}/{n}/{plugin_version(s)}/{f}" for n, s in srcs.items() for f in files_under(s)])
        self.assertEqual(files_under(self.cfg), want)
        # スキルと coldwrite の写しはバイトのまま・権限つき・symlink でない
        for n in BORROW_SKILLS:
            for rel in files_under(pinned() / "skills" / n):
                a, b = self.cfg / "skills" / n / rel, pinned() / "skills" / n / rel
                self.assertEqual(a.read_bytes(), b.read_bytes(), rel)
                self.assertFalse(a.is_symlink())
                self.assertEqual(os.access(a, os.X_OK), os.access(b, os.X_OK), rel)
        for n, s in srcs.items():
            for rel in files_under(s):
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
        self.assertEqual(sorted(rec), ["coldwrite", "pr-review-toolkit", "superpowers"])
        self.assertEqual({k: (v["version"], v["loaded"]) for k, v in rec.items()},
                         {"superpowers": (pinned().name, True), "coldwrite": (ver, True),
                          "pr-review-toolkit": (pinned(PRT).name, True)})
        self.assertEqual(json.loads((self.cfg / ".works-toolset.json").read_text()), rec)
        self.assertEqual(toolset.guard(self.cfg, self.borrow), [])

    def test_second_install_calls_nothing_and_changes_nothing(self):
        self.install()
        before = {f: (self.cfg / f).read_bytes() for f in files_under(self.cfg)}
        self.log.unlink()
        self.install()
        self.assertEqual(self.calls(), [])
        self.assertEqual({f: (self.cfg / f).read_bytes() for f in files_under(self.cfg)}, before)

    def test_changed_plugin_is_recopied_and_reinstalled(self):
        src = self.tmp / "cw"
        shutil.copytree(COLDWRITE, src)
        chosen = dict(toolset.fixed_sources(ROOT, self.borrow), coldwrite=src)
        self.install(chosen)
        self.log.unlink()
        (src / "hooks" / "hooks.json").write_text('{"hooks": {}}\n', encoding="utf-8")
        self.install(chosen)
        key = f"coldwrite@{MP}"
        self.assertEqual(self.calls(), [["plugin", "marketplace", "update", MP], ["plugin", "uninstall", key],
                                        ["plugin", "install", key]])
        self.assertEqual((self.cfg / "works-marketplace" / "coldwrite" / "hooks" / "hooks.json").read_text(),
                         '{"hooks": {}}\n')

    def test_stale_skill_copy_and_exec_bit_are_fixed(self):
        self.install()
        tdd = self.cfg / "skills" / "test-driven-development"
        (tdd / "SKILL.md").write_text("古い\n", encoding="utf-8")
        (tdd / "extra.md").write_text("余分\n", encoding="utf-8")
        polluter = self.cfg / "skills" / "systematic-debugging" / "find-polluter.sh"
        polluter.chmod(0o644)
        self.install()
        self.assertEqual(files_under(tdd), files_under(pinned() / "skills" / "test-driven-development"))
        self.assertEqual((tdd / "SKILL.md").read_bytes(),
                         (pinned() / "skills" / "test-driven-development" / "SKILL.md").read_bytes())
        self.assertTrue(os.access(polluter, os.X_OK))
        self.assertEqual(sorted(p.name for p in (self.cfg / "skills").iterdir()), sorted(BORROW_SKILLS),
                         "作業の一時の置き場が残っている")

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
        with self.assertRaises(toolset.ToolsetError) as cm:
            toolset.install(self.cfg, toolset.fixed_sources(ROOT, self.borrow), self.borrow, claude_bin=str(bad))
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

    def test_cli_usage(self):
        for args in ([], ["install"], ["install", str(self.cfg)], ["bogus", str(self.cfg)], ["guard"]):
            with self.subTest(args):
                r = self.cli(*args)
                self.assertEqual(r.returncode, 2, r.stderr)
                self.assertIn("toolset.py", r.stderr)


if __name__ == "__main__":
    unittest.main()
