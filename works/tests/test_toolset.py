"""選んだ物だけの隔離した Claude の設定（dev/toolset.py。P1 計画 Task 20 の R61 の範囲）の検査。

AI の節は全部 settingSources: [user] で、開発の殻（dev/archon.sh）が隔離した CLAUDE_CONFIG_DIR を読む。そこに置くのは
許す一覧（.shared/borrow/borrow.json）の物だけ。借りる物の取り元は 2 つに分かれる:
- superpowers: works に写した固定の版（.shared/borrow/superpowers/<版>/。VENDORED）だけから入れる。利用者の
  installed_plugins.json の superpowers の行は読まない（入っていなくても、別の版でも同じに組む）。写しが borrow.json の pin の
  sha256 と合わなければ、違うファイルを名指して何も写さずに止まる。5 つのスキルを skills/<名>/ へ、部品（parts）を
  works-parts/superpowers/<相対パス> へバイトのまま写す（プラグインとしては入れない。有効にすると SessionStart の hook が
  using-superpowers を差し込むため。裁定 P1-R8）。
- coldwrite・pr-review-toolkit: 利用者が Claude Code に入れたプラグインから取る（works は写しを持たない。版は Claude Code が
  今に保つ）。探す所は利用者の設定の置き場の plugins/installed_plugins.json の <名>@<marketplace> の行（user の行、次に
  projectPath が cwd の project・local の行）。入っていない・works が名前で頼る物（agent・hook）が無い借りる物は、1 物 1 行の
  理由と入れるコマンドを並べて止まる。中身・版・バイトは確かめない（試験が中身を見るのは、ここで作った偽のプラグインだけ）。
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
sys.path.insert(0, str(ROOT / ".shared" / "core"))
import toolset  # noqa: E402
import hermetic  # noqa: E402
import spseam  # noqa: E402
import copyledger  # noqa: E402

BORROW_SKILLS = ["test-driven-development", "systematic-debugging", "verification-before-completion",
                 "receiving-code-review", "requesting-code-review"]
# 隔離した設定の superpowers の取り元（works に写した固定の版。本物の写しを読む）
VENDORED = spseam.vendored_dir(toolset.load_borrow(ROOT)["superpowers"])
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
            _put(d / "LICENSE", "MIT License\n\nCopyright (c) 2025 Test\n")
            for f in ("SKILL.md", "implementer-prompt.md", "task-reviewer-prompt.md"):   # 部品（parts）は 2 本だけを借りる
                _put(d / "skills" / "subagent-driven-development" / f, f"偽の {f}\n")
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
                              env=hermetic.child_env(**{"CLAUDE_CONFIG_DIR": str(self.user), **env}))



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
        """works は coldwrite・pr-review-toolkit の写しを持たない（利用者が入れた版に従う）。superpowers の写しは VendorCase と
        test_sp_skills の VendoredCopyCase が縛る"""
        for name in ("pr-review-toolkit", "coldwrite"):
            self.assertFalse((ROOT / ".shared" / name).exists(), name)
        self.assertFalse((ROOT / "NOTICE").exists())


SHA = "a" * 40   # 偽の superpowers の commit（vendor は commit の分からない写しを拒む）


class VendorCase(Base):
    """vendor: 利用者のキャッシュの superpowers の 1 つの版から、包むファイルだけを .shared/borrow/superpowers/<版>/ へ写し、
    写しの台帳（COPIED_FROM）と borrow.json の pin を書き直す。偽の pack（borrow.json だけ）と偽の superpowers 9.9.0 で回す"""

    def setUp(self):
        super().setUp()
        self.pack = self.tmp / "pack"
        (self.pack / ".shared" / "borrow").mkdir(parents=True)
        shutil.copy2(ROOT / ".shared" / "borrow" / "borrow.json", self.pack / ".shared" / "borrow" / "borrow.json")

    def test_vendor_writes_copy_ledger_and_pin(self):
        src = installed_dir(self.user, "superpowers")
        pin = toolset.vendor(self.pack, src, "9.9.0", SHA, "2026-10-02")
        base = self.pack / ".shared" / "borrow" / "superpowers"
        item = json.loads((self.pack / ".shared/borrow/borrow.json").read_text())["superpowers"]
        self.assertEqual(item["pin"], pin)
        self.assertEqual(spseam.pin_problems(base / "9.9.0", item), [])
        self.assertIn("LICENSE", pin["files"])
        self.assertFalse((base / "9.9.0" / "skills" / "brainstorming").exists())        # 借りないスキルは写さない
        self.assertFalse((base / "9.9.0" / "skills" / "subagent-driven-development" / "SKILL.md").exists())   # 部品だけ
        led = copyledger.read(base / "COPIED_FROM")
        self.assertEqual(sorted(r for r, _ in led.rows), sorted(f"9.9.0/{f}" for f in pin["files"]))
        self.assertEqual(led.deviations, {})
        self.assertIn("Copyright (c) 2025 Test", led.head)

    def test_vendor_replaces_the_old_version(self):
        toolset.vendor(self.pack, installed_dir(self.user, "superpowers"), "9.9.0", SHA, "2026-10-02")
        newer = installed_dir(self.user, "superpowers").parent / "9.10.0"
        shutil.copytree(installed_dir(self.user, "superpowers"), newer)
        toolset.vendor(self.pack, newer, "9.10.0", "f" * 40, "2026-10-03")
        self.assertEqual(sorted(p.name for p in (self.pack / ".shared/borrow/superpowers").iterdir()), ["9.10.0", "COPIED_FROM"])

    def test_vendor_skips_markers(self):
        """Claude Code の印（.in_use/）と .DS_Store が借りるスキルの中に在っても、写さず固定にも数えない"""
        src = installed_dir(self.user, "superpowers")
        _put(src / "skills" / "test-driven-development" / ".in_use" / "1", "{}")
        _put(src / "skills" / "test-driven-development" / ".DS_Store", "x")
        pin = toolset.vendor(self.pack, src, "9.9.0", SHA, "2026-10-02")
        self.assertFalse(any(".in_use" in f or f.endswith(".DS_Store") for f in pin["files"]))
        copied = self.pack / ".shared/borrow/superpowers/9.9.0/skills/test-driven-development"
        self.assertEqual(sorted(p.name for p in copied.iterdir()), ["SKILL.md"])

    def test_vendor_refuses_without_mit_licence(self):
        (installed_dir(self.user, "superpowers") / "LICENSE").write_text("Proprietary\n", encoding="utf-8")
        before = (self.pack / ".shared/borrow/borrow.json").read_bytes()
        with self.assertRaises(toolset.ToolsetError):
            toolset.vendor(self.pack, installed_dir(self.user, "superpowers"), "9.9.0", SHA, "2026-10-02")
        self.assertEqual((self.pack / ".shared/borrow/borrow.json").read_bytes(), before)
        self.assertFalse((self.pack / ".shared/borrow/superpowers").exists())

    def test_cli_vendor_missing_version_is_2(self):
        r = self.cli("vendor", "0.0.1")
        self.assertEqual(r.returncode, 2)
        self.assertIn(str(installed_dir(self.user, "superpowers").parent / "0.0.1"), r.stderr)

    def test_vendor_refuses_unknown_commit_and_writes_nothing(self):
        """固定は写し元の commit を名指す。分からない（None・空・40 桁の 16 進でない）なら何も書かずに止まる"""
        before = (self.pack / ".shared/borrow/borrow.json").read_bytes()
        for commit in (None, "", "unknown", "abc"):
            with self.subTest(commit):
                with self.assertRaises(toolset.ToolsetError) as cm:
                    toolset.vendor(self.pack, installed_dir(self.user, "superpowers"), "9.9.0", commit, "2026-10-02")
                self.assertIn("commit", str(cm.exception))
                self.assertEqual((self.pack / ".shared/borrow/borrow.json").read_bytes(), before)
                self.assertFalse((self.pack / ".shared/borrow/superpowers").exists())

    def test_vendor_failure_leaves_no_empty_folder(self):
        """写している途中で落ちたら、初めての写しなら superpowers/ を残さず、borrow.json も変えない"""
        before = (self.pack / ".shared/borrow/borrow.json").read_bytes()
        with mock.patch.object(toolset.shutil, "copy2", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                toolset.vendor(self.pack, installed_dir(self.user, "superpowers"), "9.9.0", SHA, "2026-10-02")
        self.assertEqual((self.pack / ".shared/borrow/borrow.json").read_bytes(), before)
        self.assertFalse((self.pack / ".shared/borrow/superpowers").exists())

    def test_vendor_failure_keeps_the_old_version(self):
        """入れ替えの途中（borrow.json を書く所）で落ちても、前の版の写し・台帳・borrow.json はそのまま残る"""
        src = installed_dir(self.user, "superpowers")
        toolset.vendor(self.pack, src, "9.9.0", SHA, "2026-10-02")
        base = self.pack / ".shared/borrow/superpowers"
        snap = {p.relative_to(base).as_posix(): p.read_bytes() for p in base.rglob("*") if p.is_file()}
        before = (self.pack / ".shared/borrow/borrow.json").read_bytes()
        newer = src.parent / "9.10.0"
        shutil.copytree(src, newer)
        real = os.replace

        def fail_on_borrow(a, b):
            if pathlib.Path(b).name == "borrow.json":
                raise OSError("disk full")
            return real(a, b)
        with mock.patch.object(toolset.os, "replace", side_effect=fail_on_borrow):
            with self.assertRaises(OSError):
                toolset.vendor(self.pack, newer, "9.10.0", "f" * 40, "2026-10-03")
        self.assertEqual((self.pack / ".shared/borrow/borrow.json").read_bytes(), before)
        self.assertEqual({p.relative_to(base).as_posix(): p.read_bytes() for p in base.rglob("*") if p.is_file()}, snap)
        self.assertEqual(sorted(p.name for p in base.iterdir()), ["9.9.0", "COPIED_FROM"])

    @unittest.skipIf(os.name == "nt", "SKIP posix-mode: 実行の権限は POSIX だけ")
    def test_vendor_keeps_exec_bit(self):
        toolset.vendor(self.pack, installed_dir(self.user, "superpowers"), "9.9.0", SHA, "2026-10-02")
        sh = self.pack / ".shared/borrow/superpowers/9.9.0/skills/systematic-debugging/find-polluter.sh"
        self.assertTrue(os.access(sh, os.X_OK))
        self.assertFalse(os.access(sh.parent / "SKILL.md", os.X_OK))

    def test_commit_of_reads_the_row_of_the_install_path(self):
        """commit は installed_plugins.json の行のうち installPath が版のフォルダの行の gitCommitSha。無ければ None"""
        src = installed_dir(self.user, "superpowers")
        other = src.parent / "9.8.0"
        other.mkdir()
        rows = [{"scope": "user", "installPath": str(other), "version": "9.8.0", "gitCommitSha": "b" * 40},
                {"scope": "project", "projectPath": "/x", "installPath": str(src), "version": "9.9.0", "gitCommitSha": "c" * 40}]
        _put(self.user / "plugins" / "installed_plugins.json",
             json.dumps({"version": 2, "plugins": {"superpowers@superpowers-marketplace": rows}}))
        self.assertEqual(toolset._commit_of(self.user, src), "c" * 40)
        self.assertEqual(toolset._commit_of(self.user, other), "b" * 40)
        self.assertIsNone(toolset._commit_of(self.user, src.parent / "9.7.0"))

    def test_vendor_refuses_version_names_that_point_outside(self):
        for bad in ("../9.9.0", "9.9.0/x", ".hidden", ""):
            with self.subTest(bad):
                with self.assertRaises(toolset.ToolsetError) as cm:
                    toolset.vendor(self.pack, installed_dir(self.user, "superpowers"), bad, SHA, "2026-10-02")
                self.assertIn("版の名", str(cm.exception))
                self.assertFalse((self.pack / ".shared/borrow/superpowers").exists())

    def test_vendor_refuses_missing_part_or_symlink_and_writes_nothing(self):
        """部品が無い・包むファイルが symlink、のどちらでも名指して止まり、borrow.json も写しも書かない"""
        src = installed_dir(self.user, "superpowers")
        before = (self.pack / ".shared/borrow/borrow.json").read_bytes()
        part = src / "skills" / "subagent-driven-development" / "task-reviewer-prompt.md"
        cases = {"task-reviewer-prompt.md": lambda: part.unlink(),
                 "symlink": lambda: (src / "skills" / "test-driven-development" / "x.md").symlink_to(src / "LICENSE")}
        for said, breakit in cases.items():
            with self.subTest(said):
                breakit()
                with self.assertRaises(toolset.ToolsetError) as cm:
                    toolset.vendor(self.pack, src, "9.9.0", SHA, "2026-10-02")
                self.assertIn(said, str(cm.exception))
                self.assertEqual((self.pack / ".shared/borrow/borrow.json").read_bytes(), before)
                self.assertFalse((self.pack / ".shared/borrow/superpowers").exists())
                part.write_text("偽\n", encoding="utf-8")


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
        self.assertEqual(chosen, {n: installed_dir(user, n) for n in FAKE_INSTALLED if n != "superpowers"}
                         | {"superpowers": VENDORED, "context7": self.borrow["context7"]["url"]})
        self.assertEqual(versions, {n: v for n, (_, v) in FAKE_INSTALLED.items() if n != "superpowers"}
                         | {"superpowers": self.borrow["superpowers"]["pin"]["version"],
                            "context7": self.borrow["context7"]["version"]})

    def test_project_rows_count_only_for_their_project(self):
        target = self.tmp / "target"
        target.mkdir()
        user = make_user_config(self.tmp / "user", scope="project", project=target)
        chosen, _ = toolset.installed_sources(user, self.borrow, cwd=target)
        self.assertEqual(chosen["coldwrite"], installed_dir(user, "coldwrite"))
        with self.assertRaises(toolset.ToolsetError):
            toolset.installed_sources(user, self.borrow, cwd=self.tmp)

    def test_missing_tools_are_listed_one_line_each_with_install_commands(self):
        """何も入っていない利用者: 利用者の入れた物から借りる 2 つが 1 行ずつ、入れる marketplace と install のコマンドつきで並ぶ。
        superpowers は works の写しから入れるので並ばない"""
        user = self.tmp / "empty"
        user.mkdir()
        with self.assertRaises(toolset.ToolsetError) as cm:
            toolset.installed_sources(user, self.borrow)
        lines = str(cm.exception).splitlines()[1:]
        self.assertEqual(len(lines), 2, lines)
        self.assertNotIn("superpowers", str(cm.exception))
        for key, repo in (("coldwrite@raiki61", "raiki61/claude-plugins"),
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
        cases = {   # superpowers のスキルの欠けは写しの照合が名指す（test_tampered_vendored_copy_stops_before_writing）
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

    def test_superpowers_comes_from_the_vendored_copy(self):
        """利用者のキャッシュの superpowers が別の中身・別の版でも、取り元は works の写しで、版は pin の版"""
        user = make_user_config(self.tmp / "user")
        _put(installed_dir(user, "superpowers") / "skills" / "test-driven-development" / "SKILL.md", "新しい版\n")
        chosen, versions = toolset.installed_sources(user, self.borrow)
        self.assertEqual((chosen["superpowers"], versions["superpowers"]), (VENDORED, self.borrow["superpowers"]["pin"]["version"]))

    def test_plugins_content_is_not_checked(self):
        """coldwrite・pr-review-toolkit は今どおり名前だけ: 名前が在れば、中身が変わった新しい版でも通る（役は読むだけ）"""
        user = make_user_config(self.tmp / "user")
        _put(installed_dir(user, "pr-review-toolkit") / "agents" / "code-reviewer.md", "新しい版の文\n")
        chosen, _ = toolset.installed_sources(user, self.borrow)
        self.assertEqual(chosen["pr-review-toolkit"], installed_dir(user, "pr-review-toolkit"))

    def test_user_config_dir_follows_env(self):
        self.assertEqual(toolset.user_config_dir({"CLAUDE_CONFIG_DIR": "/x/cfg"}), pathlib.Path("/x/cfg"))
        self.assertEqual(toolset.user_config_dir({}), pathlib.Path(os.path.expanduser("~/.claude")))


class ScopeCase(unittest.TestCase):
    """同じプラグインが複数の scope に入っていれば、Claude Code と同じく local > project > user の行を取る
    （https://code.claude.com/docs/en/discover-plugins の Which scope wins）。enabledPlugins の無効は拒まずに借り、
    元が有効だったか無効だったかを記録に残す（人の答え: 利用者は借りる物のフックを普段効かせないために無効にしておく）"""

    FROM_USER = [n for n in FAKE_INSTALLED if n != "superpowers"]   # 利用者の入れた物から借りる物（superpowers は写しから）

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
        for n in self.FROM_USER:
            self.assertEqual(chosen[n], installed_dir(project, n), n)

    def test_local_row_wins_over_project_and_user_rows(self):
        self.add_rows("project")
        local = self.add_rows("local")
        chosen, _ = toolset.installed_sources(self.user, self.borrow, cwd=self.target)
        for n in self.FROM_USER:
            self.assertEqual(chosen[n], installed_dir(local, n), n)

    def test_disabled_plugin_is_borrowed_and_the_source_state_is_recorded(self):
        """利用者の settings.json で無効でも借りる。対象の .claude/settings.local.json・settings.json が利用者の値に勝つ。
        記録の source_enabled は、元で勝った enabledPlugins の値（どこにも鍵が無ければ null）。superpowers は写しから入れるので、
        利用者の側の有効・無効を載せない"""
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
                         {"coldwrite": False, "superpowers": "無い", "pr-review-toolkit": None})


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
        """一時の置き場に組んだ設定の中身が、ちょうど 5 つのスキル・2 つの部品・手元の marketplace の coldwrite と
        pr-review-toolkit・その入れた状態だけ。superpowers の写す元は works の写し、ほかは利用者が入れた置き場で、キャッシュの印は
        写さない"""
        rec = self.install()
        srcs = {"coldwrite": installed_dir(self.user, "coldwrite"), "pr-review-toolkit": installed_dir(self.user, "pr-review-toolkit")}
        sp = VENDORED
        want = sorted(
            [f"skills/{n}/{f}" for n in BORROW_SKILLS for f in files_under(sp / "skills" / n)]
            + [f"works-parts/superpowers/{rel}" for rel in self.borrow["superpowers"]["parts"]]
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
        # 記録: 版は installed_plugins.json の行の物、source は利用者が入れた置き場（versions.json の borrowed に載る）。
        # superpowers は pin の版と写しのフォルダ
        self.assertEqual(sorted(rec), ["coldwrite", "context7", "pr-review-toolkit", "superpowers"])
        self.assertEqual({k: (v["version"], v["source"], v["loaded"]) for k, v in rec.items()},
                         {n: (ver, str(installed_dir(self.user, n)), True) for n, (_, ver) in FAKE_INSTALLED.items()
                          if n != "superpowers"}
                         | {"superpowers": (self.borrow["superpowers"]["pin"]["version"], str(VENDORED), True)}
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
        sp = VENDORED
        self.install()
        tdd = self.cfg / "skills" / "test-driven-development"
        (tdd / "SKILL.md").write_text("古い\n", encoding="utf-8")
        (tdd / "extra.md").write_text("余分\n", encoding="utf-8")
        polluter = self.cfg / "skills" / "systematic-debugging" / "find-polluter.sh"
        polluter.chmod(0o644)
        part = self.borrow["superpowers"]["parts"][0]
        (self.cfg / "works-parts" / "superpowers" / part).write_text("古い\n", encoding="utf-8")
        self.install()
        self.assertEqual((self.cfg / "works-parts" / "superpowers" / part).read_bytes(), (sp / part).read_bytes())
        self.assertEqual(files_under(tdd), files_under(sp / "skills" / "test-driven-development"))
        self.assertEqual((tdd / "SKILL.md").read_bytes(), (sp / "skills" / "test-driven-development" / "SKILL.md").read_bytes())
        self.assertTrue(os.access(polluter, os.X_OK))
        self.assertEqual(sorted(p.name for p in (self.cfg / "skills").iterdir()), sorted(BORROW_SKILLS),
                         "作業の一時の置き場か、借りない物が残っている")

    def test_no_superpowers_installed_still_installs(self):
        """利用者が superpowers を入れていなくても組め、スキルは写しのバイトと同じ"""
        self.user = make_user_config(self.tmp / "user2", only={"coldwrite", "pr-review-toolkit"})
        rec = self.install()
        for s in self.borrow["superpowers"]["skills"]:
            for f in files_under(VENDORED / "skills" / s):
                self.assertEqual((self.cfg / "skills" / s / f).read_bytes(), (VENDORED / "skills" / s / f).read_bytes())
        self.assertEqual(rec["superpowers"]["source"], str(VENDORED))

    def test_tampered_vendored_copy_stops_before_writing(self):
        """写しのファイルが pin の sha256 と違えば、違うファイルを名指して何も写す前に止まる（写しを一時の置き場に写して向ける）"""
        copy = self.tmp / "vendored"
        shutil.copytree(VENDORED, copy)
        (copy / "skills" / "test-driven-development" / "SKILL.md").write_text("書き換え\n", encoding="utf-8")
        with mock.patch.object(toolset.spseam, "vendored_dir", return_value=copy), self.assertRaises(toolset.ToolsetError) as cm:
            toolset.installed_sources(self.user, self.borrow)
        self.assertIn("skills/test-driven-development/SKILL.md: 中身が固定と違う", str(cm.exception))
        self.assertEqual(files_under(self.cfg), [])

    def test_vendored_copy_breaks_are_named_in_one_group(self):
        """写しの壊れ方ごとに、superpowers のまとまりの中で該当の行を名指し、直し方を添えて、何も写す前に止まる"""
        def no_skill_dir(copy, item):
            shutil.rmtree(copy / "skills" / "verification-before-completion")
            return item

        def listed_but_not_pinned(copy, item):
            return dict(item, skills=[*item["skills"], "brainstorming"])

        def no_pin(copy, item):
            return {k: v for k, v in item.items() if k != "pin"}

        def no_copy_dir(copy, item):
            shutil.rmtree(copy)
            return item

        cases = {
            "skills/verification-before-completion/SKILL.md: 固定に在るのに手元に無い": no_skill_dir,
            "skills/brainstorming/SKILL.md: 借りる一覧に在るのに写しに無い": listed_but_not_pinned,
            "borrow.json の superpowers に pin が無い": no_pin,
            "写しのフォルダが無い": no_copy_dir,
        }
        for want, breakit in cases.items():
            with self.subTest(want):
                copy = self.tmp / f"vendored-{breakit.__name__}"
                shutil.copytree(VENDORED, copy)
                borrow = dict(self.borrow, superpowers=breakit(copy, dict(self.borrow["superpowers"])))
                with mock.patch.object(toolset.spseam, "vendored_dir", return_value=copy), \
                        self.assertRaises(toolset.ToolsetError) as cm:
                    toolset.installed_sources(self.user, borrow)
                msg = str(cm.exception)
                group = msg[msg.index("- superpowers の写し"):]
                self.assertIn("が borrow.json の pin と合わない:\n", group)
                self.assertTrue(any(ln.startswith("  - ") and want in ln for ln in group.splitlines()), msg)
                self.assertIn("claude plugin install works@raiki61", group)
                self.assertEqual(files_under(self.cfg), [])

    def test_vendored_copy_break_and_missing_plugins_join_in_one_error(self):
        """写しの食い違いと、入っていないプラグインの行は、同じ 1 つの ToolsetError に並ぶ"""
        copy = self.tmp / "vendored"
        shutil.copytree(VENDORED, copy)
        (copy / "skills" / "test-driven-development" / "SKILL.md").write_text("書き換え\n", encoding="utf-8")
        empty = self.tmp / "empty"
        empty.mkdir()
        with mock.patch.object(toolset.spseam, "vendored_dir", return_value=copy), self.assertRaises(toolset.ToolsetError) as cm:
            toolset.installed_sources(empty, self.borrow)
        heads = [ln for ln in str(cm.exception).splitlines() if ln.startswith("- ")]
        self.assertEqual(len(heads), 3, heads)
        self.assertTrue(heads[0].startswith("- superpowers の写し"), heads)
        self.assertIn("coldwrite が入っていない", heads[1])
        self.assertIn("pr-review-toolkit が入っていない", heads[2])
        self.assertIn("  - skills/test-driven-development/SKILL.md: 中身が固定と違う", str(cm.exception))

    def test_install_names_missing_part_before_writing(self):
        """install に渡した写しに部品が無ければ、名指して何も写さずに止まる"""
        found, vers = self.sources()
        copy = self.tmp / "vendored"
        shutil.copytree(VENDORED, copy)
        part = self.borrow["superpowers"]["parts"][0]
        (copy / part).unlink()
        with self.assertRaises(toolset.ToolsetError) as cm:
            toolset.install(self.cfg, dict(found, superpowers=copy), self.borrow, claude_bin=str(self.claude), versions=vers)
        self.assertIn(f"部品 {part}", str(cm.exception))
        self.assertEqual(files_under(self.cfg), [])

    def test_dropped_part_is_pruned_on_reinstall(self):
        """版上げで部品が一覧から外れても、入れ直しは柵に止まらずに通り、古い部品と空になったフォルダは消える"""
        self.install()
        dropped = self.borrow["superpowers"]["parts"][1]
        _put(self.cfg / "works-parts" / "superpowers" / "old" / "gone.md", "前の版の部品\n")
        smaller = dict(self.borrow, superpowers=dict(self.borrow["superpowers"], parts=self.borrow["superpowers"]["parts"][:1]))
        found, vers = self.sources()
        toolset.install(self.cfg, found, smaller, claude_bin=str(self.claude), versions=vers)
        self.assertFalse((self.cfg / "works-parts" / "superpowers" / dropped).exists())
        self.assertFalse((self.cfg / "works-parts" / "superpowers" / "old").exists())
        self.assertTrue((self.cfg / "works-parts" / "superpowers" / smaller["superpowers"]["parts"][0]).is_file())
        self.assertEqual(toolset.guard(self.cfg, smaller), [])

    def test_prune_does_not_follow_symlinks_outside_the_config(self):
        """works-parts・works-parts/superpowers が設定の外を指す symlink なら、外のファイルを消さずに柵が止める。
        works-parts/superpowers/ の下の symlink のファイルも消さず、柵が名指す"""
        def parts_dir_link(outside):
            _put(outside / "precious.md", "外の大事なファイル\n")
            (self.cfg / "works-parts").mkdir()
            (self.cfg / "works-parts" / "superpowers").symlink_to(outside)
            return outside / "precious.md"

        def root_link(outside):
            _put(outside / "superpowers" / "precious.md", "外の大事なファイル\n")
            (self.cfg / "works-parts").symlink_to(outside)
            return outside / "superpowers" / "precious.md"

        for make in (parts_dir_link, root_link):
            with self.subTest(make.__name__):
                shutil.rmtree(self.cfg)
                self.cfg.mkdir()
                precious = make(self.tmp / f"outside-{make.__name__}")
                with self.assertRaises(toolset.ToolsetError):
                    self.install()
                self.assertTrue(precious.is_file(), "設定の外のファイルを消した")
        shutil.rmtree(self.cfg)
        self.cfg.mkdir()
        _put(self.tmp / "outside-file.md", "外の大事なファイル\n")
        link = self.cfg / "works-parts" / "superpowers" / "link.md"
        link.parent.mkdir(parents=True)
        link.symlink_to(self.tmp / "outside-file.md")
        with self.assertRaises(toolset.ToolsetError):
            self.install()
        self.assertTrue(link.is_symlink() and (self.tmp / "outside-file.md").is_file())
        self.assertEqual(toolset.guard(self.cfg, self.borrow), ["works-parts/superpowers/link.md"])

    def test_parts_go_to_works_parts_and_record_has_commit(self):
        """部品は works-parts/superpowers/<相対パス> へバイトのまま写り、スキルとしては入らない。記録は pin の commit を持ち、
        source_enabled を持たない。works-parts/ の下の部品の外のファイルは柵が名指す"""
        rec = self.install()
        for rel in self.borrow["superpowers"]["parts"]:
            self.assertEqual((self.cfg / "works-parts" / "superpowers" / rel).read_bytes(), (VENDORED / rel).read_bytes())
        self.assertFalse((self.cfg / "skills" / "subagent-driven-development").exists())   # スキルとしては入れない
        self.assertEqual(rec["superpowers"]["commit"], self.borrow["superpowers"]["pin"]["commit"])
        self.assertNotIn("source_enabled", rec["superpowers"])
        self.assertEqual(toolset.guard(self.cfg, self.borrow), [])
        _put(self.cfg / "works-parts" / "superpowers" / "skills" / "subagent-driven-development" / "SKILL.md", "x\n")
        self.assertEqual(toolset.guard(self.cfg, self.borrow), ["works-parts/superpowers/skills/subagent-driven-development/SKILL.md"])

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

    def test_official_marketplace_is_not_outside(self):
        """Claude Code が起動の時に隔離した設定へ足す公式の marketplace（名と GitHub の repo が合う行）は、選んだ物の外に数えない
        （登録だけでプラグインは増えない。これを拒むと wait・show が全部落ちていた）"""
        self.put("plugins/known_marketplaces.json",
                 '{"claude-plugins-official": {"source": {"source": "github", "repo": "anthropics/claude-plugins-official"}}}')
        self.assertEqual(toolset.guard(self.cfg, self.borrow), [])

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
            "works-parts/other/a.md": lambda: self.put("works-parts/other/a.md"),
            "works-parts（フォルダでない）": lambda: self.put("works-parts"),
            "works-parts/superpowers/link": lambda: (self.put("target.md"),
                                                     (self.cfg / "works-parts" / "superpowers").mkdir(parents=True),
                                                     (self.cfg / "works-parts" / "superpowers" / "link").symlink_to(
                                                         self.cfg / "target.md")),
            "settings.json の鍵 permissions": lambda: self.put("settings.json", '{"permissions": {"allow": []}}'),
            "settings.json の鍵 hooks": lambda: self.put("settings.json", '{"hooks": {}}'),
            "有効なプラグイン other@x": lambda: self.put("settings.json", '{"enabledPlugins": {"other@x": true}}'),
            "marketplace x（settings.json）": lambda: self.put("settings.json", '{"extraKnownMarketplaces": {"x": {}}}'),
            "入れたプラグイン other@x": lambda: self.put("plugins/installed_plugins.json",
                                                        '{"version": 2, "plugins": {"other@x": []}}'),
            "marketplace x（plugins/known_marketplaces.json）": lambda: self.put("plugins/known_marketplaces.json",
                                                                                  '{"x": {}}'),
            "settings.json（JSON の表として読めない）": lambda: self.put("settings.json", "{"),
            # 公式の名でも repo が違えば外に数える（名だけで通さない）
            "marketplace claude-plugins-official（plugins/known_marketplaces.json）": lambda: self.put(
                "plugins/known_marketplaces.json",
                '{"claude-plugins-official": {"source": {"source": "github", "repo": "someone/claude-plugins-official"}}}'),
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
        --user-config が env の CLAUDE_CONFIG_DIR より勝つ。superpowers は works の写しから入れるので、入れるコマンドを出さない"""
        empty = self.tmp / "empty"
        empty.mkdir()
        for args, env in ((["--user-config", str(empty)], {}), ([], {"CLAUDE_CONFIG_DIR": str(empty)})):
            with self.subTest(args=args):
                r = self.cli("install", "--claude", str(self.claude), *args, str(self.cfg), **env)
                self.assertEqual(r.returncode, 2, r.stderr)
                self.assertEqual(len([ln for ln in r.stderr.splitlines() if ln.startswith("- ")]), 2, r.stderr)
                self.assertNotIn("superpowers@superpowers-marketplace", r.stderr)
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
                                   env=hermetic.child_env(**{"CLAUDE_CONFIG_DIR": str(self.user), **env}))
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
        for args in ([], ["install"], ["install", str(self.cfg)], ["bogus", str(self.cfg)], ["guard"], ["contract", "a", "b"]):
            with self.subTest(args):
                r = self.cli(*args)
                self.assertEqual(r.returncode, 2, r.stderr)
                self.assertIn("toolset.py", r.stderr)

    def test_cli_contract_on_the_vendored_copy_is_0(self):
        r = self.cli("contract")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("全部そろう", r.stdout)

    def test_cli_contract_on_a_cache_version_names_broken_anchors(self):   # 偽のキャッシュの 9.9.0 は錨の文を持たない
        r = self.cli("contract", "9.9.0")
        self.assertEqual(r.returncode, 1, r.stderr)
        self.assertIn("tdd: 錨 SUITE", r.stdout)


    def test_cli_contract_on_a_missing_version_is_2_and_names_it(self):
        r = self.cli("contract", "8.8.8")
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        self.assertIn("8.8.8", r.stderr)
        self.assertEqual(r.stdout, "")

    def test_cli_contract_without_pin_is_2_and_says_how_to_fix(self):
        """borrow.json に superpowers の pin が無ければ、写しの版が決まらない。版を名指しても名指さなくても、トレースバックで
        なく 1 行で 2（偽の pack を一時の置き場に組む）"""
        pack = self.tmp / "pack"
        shutil.copytree(ROOT / ".shared" / "borrow", pack / ".shared" / "borrow")
        (pack / ".shared" / "core").mkdir()
        shutil.copy2(ROOT / ".shared" / "core" / "spseam.py", pack / ".shared" / "core" / "spseam.py")   # toolset が import するのはこれだけ
        (pack / "dev").mkdir()
        shutil.copy2(TOOLSET, pack / "dev" / "toolset.py")
        bj = pack / ".shared" / "borrow" / "borrow.json"
        borrow = json.loads(bj.read_text(encoding="utf-8"))
        del borrow["superpowers"]["pin"]
        bj.write_text(json.dumps(borrow, ensure_ascii=False), encoding="utf-8")
        for args in ([], ["9.9.0"]):
            with self.subTest(args):
                r = subprocess.run([sys.executable, str(pack / "dev" / "toolset.py"), "contract", *args],
                                   capture_output=True, text=True, encoding="utf-8",
                                   env=hermetic.child_env(CLAUDE_CONFIG_DIR=str(self.user)))
                self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
                self.assertIn("toolset.py: borrow.json の superpowers に pin が無い（写しの版が決まらない。"
                              "dev/toolset.py vendor で写す）", r.stderr)
                self.assertNotIn("Traceback", r.stderr)

class RepoDenyCase(unittest.TestCase):
    """対象の持ち主の禁止: 役は settingSources: [user] とこの隔離した設定で起きるので、対象リポジトリの .claude/settings.json・
    settings.local.json を読まない。包み（.shared/core/adapter.plan）は印のある起動で、役の cwd の worktree の根の 2 つの
    ファイルの permissions.deny だけを --settings の permissions.deny に足す（本流 role_run.repo_deny と同じ読み方）。
    読めない・形が違えば claude を起こさず、ファイルを名指しする（fail closed）"""

    SANDBOX = '{"sandbox":{"enabled":true,"allowUnsandboxedCommands":false,"failIfUnavailable":true}}'

    def setUp(self):
        sys.path.insert(0, str(ROOT / ".shared" / "core"))
        self.addCleanup(sys.path.remove, str(ROOT / ".shared" / "core"))
        import adapter
        self.adapter = adapter
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = pathlib.Path(tmp.name).resolve()
        self.wt = self.tmp / "wt"
        self.wt.mkdir()
        subprocess.run(["git", "-C", str(self.wt), "init", "-q"], check=True)
        (self.wt / ".claude").mkdir()
        self.guarded = str(self.tmp / "board")

    def write(self, name, doc):
        (self.wt / ".claude" / name).write_text(doc if isinstance(doc, str) else json.dumps(doc), encoding="utf-8")

    def plan(self, cwd=None):
        schema = json.dumps({"type": "object", "description": "works-node: fix", "properties": {}})
        argv = ["--output-format", "stream-json", "--json-schema", schema, "--tools", "Read,Edit,Bash",
                "--setting-sources=project,user", "--settings", self.SANDBOX]
        return self.adapter.plan(argv, cwd or self.wt, self.tmp / "home", "true", protected=lambda: [self.guarded],
                                 env={"PATH": "/usr/bin:/bin"})

    @staticmethod
    def deny(p):
        vals = [p.argv[i + 1] for i, a in enumerate(p.argv) if a == "--settings"]
        return json.loads(vals[0])["permissions"]["deny"]

    def test_both_files_deny_copied_beside_own_fences(self):
        self.write("settings.json", {"permissions": {"deny": ["Bash(bash tests/run.sh:*)"], "allow": ["Bash(ls:*)"]}})
        self.write("settings.local.json", {"permissions": {"deny": ["Bash(./tests/run.sh:*)"]}})
        p = self.plan()
        self.assertEqual(p.mode, "merged", p.why)
        deny = self.deny(p)
        self.assertIn("Bash(bash tests/run.sh:*)", deny)
        self.assertIn("Bash(./tests/run.sh:*)", deny)
        self.assertNotIn("Bash(ls:*)", deny)
        for r in self.adapter.deny_rules([self.guarded]):
            self.assertIn(r, deny, "包み自身の柵と並ぶ")

    def test_read_from_worktree_root_when_cwd_is_below(self):
        self.write("settings.json", {"permissions": {"deny": ["Bash(sh tests/run.sh:*)"]}})
        (self.wt / "sub").mkdir()
        p = self.plan(self.wt / "sub")
        self.assertEqual(p.mode, "merged", p.why)
        self.assertIn("Bash(sh tests/run.sh:*)", self.deny(p))

    def test_broken_json_refused_naming_the_file(self):
        for name in ("settings.json", "settings.local.json"):
            with self.subTest(name):
                for n in ("settings.json", "settings.local.json"):
                    (self.wt / ".claude" / n).unlink(missing_ok=True)
                self.write(name, "{")
                p = self.plan()
                self.assertEqual(p.mode, "refused")
                self.assertIn(name, p.why or "")

    def test_deny_not_a_string_list_refused(self):
        for doc in ({"permissions": {"deny": "Bash(x)"}}, {"permissions": {"deny": [1]}}, {"permissions": []}, []):
            with self.subTest(doc=doc):
                self.write("settings.json", doc)
                p = self.plan()
                self.assertEqual(p.mode, "refused")
                self.assertIn("settings.json", p.why or "")


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


PIN_V = toolset.load_borrow(ROOT)["superpowers"]["pin"]["version"]    # 6.4.2


class NewerCase(Base):
    """newer（開発の再開の確かめ）: 利用者のキャッシュの superpowers の版のフォルダ・installed_plugins.json の行・marketplace の
    一覧の版を、写した固定の版と数の組で比べ、新しい版には固定との違いと節の契約の破れと、増えた人に聞く文を出す。何も書かず、
    読めない物は 1 行で名指して続け、終了コードは 0（使い方の誤りだけ 2）。偽の利用者の設定には偽の superpowers 9.9.0 を置かない"""

    def setUp(self):
        super().setUp()
        shutil.rmtree(self.tmp / "user")   # Base の偽の superpowers 9.9.0 のフォルダも消す（版のフォルダは候補に数える）
        self.user = make_user_config(self.tmp / "user", only={"coldwrite", "pr-review-toolkit"})
        self.item = toolset.load_borrow(ROOT)["superpowers"]

    def add_version(self, v, edit=None):
        """写しを <user>/plugins/cache/superpowers-marketplace/superpowers/<v>/ に写し、edit の相対パスを書き換え、
        installed_plugins.json に user の行を足す"""
        d = self.user / "plugins" / "cache" / self.item["marketplace"] / "superpowers" / v
        shutil.copytree(spseam.vendored_dir(self.item), d)
        for rel, body in (edit or {}).items():
            _put(d / rel, body)
        ip = self.user / "plugins" / "installed_plugins.json"
        doc = json.loads(ip.read_text(encoding="utf-8"))
        doc["plugins"].setdefault(f"superpowers@{self.item['marketplace']}", []).append(
            {"scope": "user", "installPath": str(d), "version": v, "installedAt": "2026-10-02T00:00:00.000Z"})
        ip.write_text(json.dumps(doc, indent=2), encoding="utf-8")
        return d

    def put_marketplace_raw(self, text):
        loc = self.tmp / "marketplaces" / self.item["marketplace"]
        _put(self.user / "plugins" / "known_marketplaces.json",
             json.dumps({self.item["marketplace"]: {"source": {"source": "github", "repo": self.item["marketplace_repo"]},
                                                    "installLocation": str(loc)}}))
        _put(loc / ".claude-plugin" / "marketplace.json", text)

    def put_marketplace(self, doc):
        self.put_marketplace_raw(json.dumps(doc))

    def test_newer_compares_numerically_and_applies_the_contract(self):
        self.add_version("6.10.0", edit={"skills/test-driven-development/SKILL.md": "Ask your human partner now.\n"})
        self.add_version("6.3.0")
        r = self.cli("newer")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("superpowers 6.10.0", r.stdout)
        self.assertNotIn("superpowers 6.3.0", r.stdout)
        self.assertIn("skills/test-driven-development/SKILL.md: 中身が固定と違う", r.stdout)
        self.assertIn("人に聞く文が増えた: skills/test-driven-development/SKILL.md: Ask your human partner now.", r.stdout)
        self.assertIn("tdd: 錨", r.stdout)
        self.assertIn("版を上げるかは人が決める", r.stdout)

    def test_newer_reports_same_version_with_other_content(self):
        self.add_version(PIN_V, edit={"skills/receiving-code-review/SKILL.md": "x\n"})
        self.assertIn("写しと同じ版なのに中身が違う", self.cli("newer").stdout)

    def test_newer_lists_marketplace_only_versions(self):
        self.add_version(PIN_V)
        self.put_marketplace({"plugins": [{"name": "superpowers", "version": "7.0.0"}]})
        self.assertIn("superpowers 7.0.0: marketplace の一覧に在る", self.cli("newer").stdout)

    def test_newer_with_nothing_newer_says_one_line(self):
        self.add_version(PIN_V)
        r = self.cli("newer")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("より新しい版・違う中身は、手元にも marketplace の一覧にも無い", r.stdout)

    def test_newer_names_unparsable_versions(self):
        self.add_version("latest")
        r = self.cli("newer")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("latest", r.stdout)

    def test_newer_without_superpowers_installed(self):
        r = self.cli("newer")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("superpowers が入っていない", r.stdout)

    def test_newer_unreadable_marketplace_is_named_not_fatal(self):
        self.add_version(PIN_V)
        self.put_marketplace_raw("{壊れた")
        r = self.cli("newer")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("marketplace の一覧を読めない", r.stdout)

    def test_newer_writes_nothing(self):
        self.add_version("6.10.0")
        before = {p: p.read_bytes() for p in self.user.rglob("*") if p.is_file()}
        pack = {p: p.read_bytes() for p in (ROOT / ".shared" / "borrow").rglob("*") if p.is_file()}
        r = self.cli("newer")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("superpowers 6.10.0", r.stdout)
        self.assertEqual({p: p.read_bytes() for p in self.user.rglob("*") if p.is_file()}, before)
        self.assertEqual({p: p.read_bytes() for p in (ROOT / ".shared" / "borrow").rglob("*") if p.is_file()}, pack)

    def test_dogfood_start_runs_newer_once(self):
        rows = (DEV / "dogfood.sh").read_text(encoding="utf-8").splitlines()
        hits = [i for i, ln in enumerate(rows) if 'toolset.py" newer' in ln]
        self.assertEqual(len(hits), 1)
        show_end = next(i for i, ln in enumerate(rows) if "works_dev_show_synced dogfood.sh" in ln)   # --show の分岐の終わり
        clone = next(i for i, ln in enumerate(rows) if ln.startswith("g clone "))                     # clone の行
        self.assertTrue(show_end < hits[0] < clone)
        self.assertIn("|| echo", rows[hits[0]])   # 落ちても起動を止めない

    def test_newer_takes_no_version(self):
        """newer は版を名指さない（比べる元は写し）。版を渡すのは使い方の誤りで 2"""
        r = self.cli("newer", "6.10.0")
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        self.assertIn("toolset.py", r.stderr)
        self.assertEqual(r.stdout, "")

    def test_newer_unreadable_installed_plugins_is_named_not_fatal(self):
        """installed_plugins.json が JSON として読めなくても、1 行で名指して版のフォルダの確かめを続ける"""
        self.add_version("6.10.0")
        (self.user / "plugins" / "installed_plugins.json").write_text("{壊れた", encoding="utf-8")
        r = self.cli("newer")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("installed_plugins.json", r.stdout)
        self.assertIn("superpowers 6.10.0", r.stdout)

    def test_newer_names_added_asks_whatever_the_case(self):
        """人に聞く文は大文字・小文字を問わずに拾う（原文には行頭の Human partner が在る）"""
        self.add_version("6.10.0", edit={"skills/receiving-code-review/SKILL.md": "Human partner decides this.\n"})
        r = self.cli("newer")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("人に聞く文が増えた: skills/receiving-code-review/SKILL.md: Human partner decides this.", r.stdout)

    def test_newer_unlistable_version_folders_still_exit_0(self):
        """版のフォルダの一覧を読めない（権限が無い）時も、1 行で名指して最後の行を出し、終了コード 0"""
        base = self.add_version(PIN_V).parent
        base.chmod(0)
        try:
            r = self.cli("newer")
        finally:
            base.chmod(0o755)   # tearDown が一時の置き場を消せるように、ここで戻す
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("読めない物に当たった", r.stdout)
        self.assertIn("版を上げるかは人が決める", r.stdout)
        self.assertNotIn("Traceback", r.stderr)
