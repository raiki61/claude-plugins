"""Claude の包み（.shared/core/claude-adapter と .shared/core/adapter.py）の検査。本物の AI は起こさない。

Archon は Claude Code の実行ファイルを `assistants.claude.claudeBinaryPath`（設定）か `CLAUDE_BIN_PATH`（env。設定より強い）
で差し替えられる。包みはそこに置かれ、SDK が組んだ argv を少しだけ直して本物の claude を exec する。
包みの形は 2 つの有料の試し（scratchpad の claude-adapter-probe.md〔包試〕・resume-probe-summary.md〔継試〕）で
本物の Archon v0.11.1・SDK 0.3.282・claude 2.1.283 と確かめた物で、ここでは偽の claude（tests/adapter/fake-claude）で縛る。

- 印（works-node）の無い起動（Archon の題の生成＝`--tools ""` など）は、網の閉じのほかは argv を 1 バイトも変えない
- 網の閉じ（印の有無に依らない）: sandbox.network.allowedDomains が `*` を含まない配列なら strictAllowlist: true を足す。
  `*` の網・網の一覧の無い sandbox は触らない。--settings が読めない起動は起こさない（NetworkCase）
- 印のある起動: `--settings` に PostToolUse:Read のフックを足す（SDK の鍵は上書きしない。3 つの綴り・無ければ足す）。
  `--setting-sources`・`--model` は触らない
- 見分けられない形（`--settings` が 2 つ・読めない JSON・値の無い旗・崩れた印・`--json-schema` が 2 つ）は
  足さずに素通しし、stderr に 1 行の警告
- フックは読んだファイルの sha を包みの家（WORKS_ADAPTER_HOME）の cwd ごとの `reads.jsonl` に書く（graphloops の形のまま）
- 判定役（`works-node: judge`）: 包みが `--session-id=<uuid>` を足して `sessions/<cwd の hash>/judge.id` に書く。
  SDK が付けた `--resume`・`--session-id` はそのまま記録する
- 再審（`works-node: rejudge continue=judge`）: SDK の会話の旗を外して `--resume <judge の id>`。id が無ければ子を起こさず
  stderr 1 行・終了コード 3（fail closed）
- 旗 no-tree-write（CI の任せ先の役）: 役の cwd の worktree の根を全部の綴りで柵に足す。sandbox の塊・切符が無い起動は
  起こさない（裁定 R56）
- 旗 isolated（独立の目の道具ゼロの役 blind-judge）: 子を Git の外の置き場（一時の置き場の works-isolated-<cwd の hash>）で起こす
  （git status と CLAUDE.md が役に入らない。graphloops の commands._isolated_cwd）。道具を持つ起動・置き場が Git の中なら起こさない
- 本物の claude が見つからない・包み自身を指す時は 1 行で止まる。名前は .js で終わらない（Archon が --no-env-file を足すため）
- dev の殻（archon.sh）の WORKS_DEV_ADAPTER=1 が設定の claudeBinaryPath で包みを入れる
"""
import hashlib
import json
import os
import pathlib
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
CORE = ROOT / ".shared" / "core"
ADAPTER = CORE / "claude-adapter"
RECORDER = CORE / "record-read.py"
FAKE = ROOT / "tests" / "adapter" / "fake-claude"
SAMPLES = ROOT / "tests" / "adapter" / "argv"
DEV = ROOT / "dev"
sys.dont_write_bytecode = True   # 下の import が pack の中に __pycache__ を作らないように
sys.path.insert(0, str(CORE))

import adapter  # noqa: E402
import hermetic  # noqa: E402

SANDBOX = '{"sandbox":{"enabled":true,"allowUnsandboxedCommands":false,"failIfUnavailable":true}}'
UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")


def schema(desc=None):
    s = {"type": "object", "additionalProperties": False, "required": ["a"], "properties": {"a": {"type": "string"}}}
    if desc is not None:
        s["description"] = desc
    return json.dumps(s)


def sdk_argv(desc=None, settings=SANDBOX, tools="", extra=()):
    """〔継試〕の実物の並び（SDK 0.3.282）。desc=None なら --json-schema を持たない（題の生成の形）"""
    a = ["--output-format", "stream-json", "--verbose", "--input-format", "stream-json"]
    if desc is not None:
        a += ["--max-budget-usd", "0.15"]
    a += ["--model", "opus"]
    if desc is not None:
        a += ["--json-schema", schema(desc if desc != "" else None)]
    a += ["--tools", tools, "--setting-sources=project,user"]
    if desc is not None:
        a += ["--strict-mcp-config"]
    a += ["--permission-mode", "bypassPermissions", "--allow-dangerously-skip-permissions", "--include-hook-events"]
    a += list(extra)
    if desc is not None and settings is not None:
        a += ["--settings", settings]
    return a


def opt(argv, name):
    """argv の中の --name の値（--name v と --name=v）の並び"""
    out = []
    for i, a in enumerate(argv):
        if a == name and i + 1 < len(argv):
            out.append(argv[i + 1])
        elif a.startswith(name + "="):
            out.append(a[len(name) + 1:])
    return out


class Env:
    """1 つの試験の置き場: 包みの家・run の worktree に見立てた cwd・偽の claude の記録"""

    def __init__(self, case):
        self.tmp = hermetic.tmpdir(case)
        self.home = self.tmp / "adapter-home"
        self.cwd = self.tmp / "wt"
        self.cwd.mkdir()
        self.log = self.tmp / "fake.jsonl"

    def run(self, argv, cwd=None, stdin="", exit_code=0, **env_over):
        env = {k: v for k, v in hermetic.child_env().items() if not k.startswith("WORKS_")}
        # 設定の置き場は既定で空の使い捨て（外の run の CLAUDE_CONFIG_DIR も、無い時に包みが落ちる本物の ~/.claude も読ませない）
        empty_config = self.tmp / "empty-claude-config"
        empty_config.mkdir(exist_ok=True)
        env.update(WORKS_ADAPTER_HOME=str(self.home), WORKS_REAL_CLAUDE=str(FAKE), FAKE_CLAUDE_LOG=str(self.log),
                   FAKE_CLAUDE_EXIT=str(exit_code), PYTHONDONTWRITEBYTECODE="1", CLAUDE_CONFIG_DIR=str(empty_config))
        for k, v in env_over.items():
            if v is None:
                env.pop(k, None)
            else:
                env[k] = v
        return subprocess.run([str(ADAPTER), *argv], cwd=str(cwd or self.cwd), env=env, input=stdin,
                              capture_output=True, text=True, encoding="utf-8")

    def child(self):
        """偽の claude が受けた最後の起動（起きていなければ None）"""
        if not self.log.exists():
            return None
        return json.loads(self.log.read_text(encoding="utf-8").splitlines()[-1])

    def launches(self, cwd=None):
        p = adapter.launches_path(cwd or self.cwd, self.home)
        if not p.exists():
            return []
        return [json.loads(ln) for ln in p.read_text(encoding="utf-8").splitlines()]

    def session_id(self, node, cwd=None):
        p = adapter.session_path(cwd or self.cwd, node, self.home)
        return p.read_text(encoding="utf-8").strip() if p.exists() else None


class MarkerCase(unittest.TestCase):
    def test_marker_text_round_trip(self):
        self.assertEqual(adapter.marker_text("judge"), "works-node: judge")
        self.assertEqual(adapter.marker_text("rejudge", cont="judge"), "works-node: rejudge continue=judge")
        m = adapter.parse_marker("works-node: rejudge continue=judge")
        self.assertEqual((m.name, m.cont, m.flags), ("rejudge", "judge", ()))
        m = adapter.parse_marker("works-node: pr-check no-post")
        self.assertEqual((m.name, m.cont, m.flags), ("pr-check", None, ("no-post",)))

    def test_not_ours_is_none(self):
        for d in (None, "", "判定役の返答", 3, "works-nodes: x"):
            self.assertIsNone(adapter.parse_marker(d), d)

    def test_malformed_marker_is_bad(self):
        # node_marker.parse（枝 wip/works-a2）が None を返す形は全部 BadMarker（包みは claude を起こさない）
        for d in ("works-node:", "works-node: ", "works-node:judge", "works-node: a b=c", "works-node: judge continue=",
                  "works-node: ../x", "works-node: a continue=b continue=c", "works-node: Judge",
                  "works-node:  judge", "works-node: judge ", "works-node: judge  continue=x", "works-node: judge foo",
                  "works-node: judge no-post no-post", "works-node: a_b", "works-node: judge continue=Judge",
                  "works-node: judge\ncontinue=x"):
            with self.assertRaises(adapter.BadMarker, msg=repr(d)):
                adapter.parse_marker(d)

    def test_marker_grammar_matches_node_marker(self):
        """枝 wip/works-a2 の node_marker.parse と、読める・読めないが同じ（引けなければ skip）"""
        src = subprocess.run(["git", "-C", str(ROOT), "show", "wip/works-a2:works/.shared/core/node_marker.py"],
                             capture_output=True, text=True, encoding="utf-8")
        if src.returncode != 0:
            self.skipTest("SKIP local-branch: wip/works-a2 を引けない: " + src.stderr.strip()[-200:])
        ns = {}
        exec(compile(src.stdout, "node_marker.py", "exec"), ns)
        cases = ["works-node: judge", "works-node: rejudge continue=judge", "works-node: pr-check no-post",
                 "works-node: x continue=y no-post", "works-node: no-post", "works-node: a-1 continue=b-2",
                 "works-node:", "works-node: Judge", "works-node:  judge", "works-node: judge foo",
                 "works-node: judge no-post no-post", "works-node: a_b", "works-node: judge ", "判定"]
        for d in cases:
            with self.subTest(d):
                want = ns["parse"](d)
                try:
                    got = adapter.parse_marker(d)
                except adapter.BadMarker:
                    got = "bad"
                if want is None:
                    self.assertIn(got, (None, "bad"))
                    self.assertEqual(got is None, not d.startswith("works-node:"))
                else:
                    self.assertEqual((got.name, got.cont, frozenset(got.flags)),
                                     (want["name"], want["cont"], want["flags"]))

    def test_flags_match_node_marker(self):
        """包みの FLAGS は core の node_marker.FLAGS と同じ（印を作る側と読む側で旗がずれない）"""
        sys.path.insert(0, str(CORE))
        import node_marker
        self.assertEqual(frozenset(adapter.FLAGS), node_marker.FLAGS)
        m = adapter.parse_marker("works-node: ci no-tree-write")
        self.assertEqual((m.name, m.flags), ("ci", ("no-tree-write",)))

    def test_marker_from_argv_both_spellings(self):
        a = ["--model", "opus", "--json-schema", schema("works-node: judge")]
        self.assertEqual(adapter.marker_from_argv(a).name, "judge")
        a = ["--model", "opus", "--json-schema=" + schema("works-node: rejudge continue=judge")]
        self.assertEqual(adapter.marker_from_argv(a).cont, "judge")
        self.assertIsNone(adapter.marker_from_argv(["--tools", ""]))

    def test_dangling_settings_on_marked_launch_is_refused(self):
        p = adapter.plan(sdk_argv("works-node: fix", settings=None) + ["--settings"], "/x", pathlib.Path("/h"), "H",
                         new_id=lambda: "u")
        self.assertEqual((p.mode, p.warn, p.hook, p.record), ("refused", True, False, []))

    def test_marker_from_argv_unrecognised_shapes(self):
        two = ["--json-schema", schema(), "--json-schema", schema()]
        for a in (two, ["--json-schema", "{not json"], ["--json-schema"], ["--json-schema", "[1]"]):
            with self.subTest(a):
                with self.assertRaises(adapter.Unrecognised) as cm:
                    adapter.marker_from_argv(a)
                self.assertNotIsInstance(cm.exception, adapter.BadMarker)

    def test_marker_traces_in_odd_shapes_are_bad(self):
        # 同じ規則を JSON として読める形にも読めない形にも当てる（M2）
        two = ["--json-schema", schema("works-node: a"), "--json-schema", schema("works-node: b")]
        nested = json.dumps({"type": "object", "properties": {"a": {"type": "string",
                                                                   "description": "works-node: rejudge continue=judge"}}})
        for a in (two, ["--json-schema", '{"description": "works-node: judge", '],
                  ["--json-schema", schema("works-node: judge x")],
                  ["--json-schema", schema(" works-node: rejudge continue=judge")],     # 頭に空白
                  ["--json-schema", nested],                                            # 入れ子の description
                  ["--json-schema", json.dumps({"title": "works-node: judge"})]):     # 一番上の別の鍵
            with self.subTest(a):
                with self.assertRaises(adapter.BadMarker):
                    adapter.marker_from_argv(a)


class PathsCase(unittest.TestCase):
    def test_session_path_per_cwd(self):
        home = pathlib.Path("/h")
        a = adapter.session_path("/x/wt1", "judge", home)
        b = adapter.session_path("/x/wt2", "judge", home)
        self.assertNotEqual(a.parent, b.parent)
        self.assertEqual(a.name, "judge.id")
        self.assertEqual(a.parent.parent, home / "sessions")
        self.assertEqual(len(a.parent.name), 16)
        self.assertEqual(adapter.reads_dir("/x/wt1", home).parent.name, "reads")
        self.assertEqual(adapter.reads_dir("/x/wt1", home).name, a.parent.name)

    def test_cwd_key_follows_symlink(self):
        with tempfile.TemporaryDirectory() as t:
            real = pathlib.Path(t, "real")
            real.mkdir()
            link = pathlib.Path(t, "link")
            link.symlink_to(real)
            self.assertEqual(adapter.cwd_key(link), adapter.cwd_key(real))

    def test_paths_default_to_env_home(self):
        from unittest import mock
        with mock.patch.dict(os.environ, {"WORKS_ADAPTER_HOME": "/env/home"}):
            self.assertEqual(adapter.session_path("/x/wt", "judge"),
                             pathlib.Path("/env/home/sessions") / adapter.cwd_key("/x/wt") / "judge.id")
            self.assertEqual(adapter.launches_path("/x/wt"),
                             pathlib.Path("/env/home/launches") / (adapter.cwd_key("/x/wt") + ".jsonl"))
            self.assertEqual(adapter.reads_dir("/x/wt").parent, pathlib.Path("/env/home/reads"))

    def test_home_from_env_or_default(self):
        self.assertEqual(adapter.home({"WORKS_ADAPTER_HOME": "/a/b"}), pathlib.Path("/a/b"))
        # 切符（ticket.home）と同じ既定
        self.assertEqual(adapter.home({"HOME": "/u"}), pathlib.Path("/u/.local/state/works/adapter"))
        self.assertEqual(adapter.home({"HOME": "/u", "XDG_STATE_HOME": "/s"}), pathlib.Path("/s/works/adapter"))
        self.assertEqual(adapter.home({"HOME": "/u", "WORKS_ADAPTER_HOME": ""}), pathlib.Path("/u/.local/state/works/adapter"))

    def test_spellings_cover_private_aliases(self):
        self.assertEqual(adapter.spellings("/private/var/folders/x")[:2], ["/private/var/folders/x", "/var/folders/x"])
        self.assertIn("/private/tmp/y", adapter.spellings("/tmp/y"))
        self.assertIn("/tmp", adapter.spellings("/private/tmp"))
        self.assertEqual(adapter.spellings("/Users/u/.gitconfig"), ["/Users/u/.gitconfig"])
        self.assertNotIn("/var", adapter.spellings("/variable/z")[1:])

    def test_ticket_path_matches_ticket_module_formula(self):
        # 枝 wip/works-a4 の ticket.ticket_path と同じ式（home()/tickets/<cwd の realpath の sha256 の先頭 16 字>.json）
        want = hashlib.sha256(os.path.realpath("/x/wt").encode("utf-8")).hexdigest()[:16]
        self.assertEqual(adapter.ticket_path("/x/wt", "/h"), pathlib.Path("/h/tickets") / f"{want}.json")


class MergeCase(unittest.TestCase):
    def test_merge_never_overrides_sdk_keys(self):
        sdk = {"sandbox": {"enabled": True, "failIfUnavailable": True},
               "hooks": {"PostToolUse": [{"matcher": "Bash", "hooks": []}]}, "model": "opus"}
        ours = {"hooks": {"PostToolUse": [{"matcher": "Read", "hooks": [{"type": "command", "command": "x"}]}]},
                "model": "haiku", "sandbox": {"enabled": False, "extra": 1}}
        got = adapter.merge_settings(json.loads(json.dumps(sdk)), ours)
        self.assertEqual(got["model"], "opus")
        self.assertEqual(got["sandbox"], {"enabled": True, "failIfUnavailable": True, "extra": 1})
        self.assertEqual([m["matcher"] for m in got["hooks"]["PostToolUse"]], ["Bash", "Read"])


class AdapterCase(unittest.TestCase):
    def setUp(self):
        self.e = Env(self)

    # --- 素通し ---------------------------------------------------------------------------------------------
    def test_unmarked_title_launch_untouched(self):
        argv = sdk_argv(None)   # 題の生成（title-generator.ts）: --tools "" で印なし
        self.assertIn("--tools", argv)
        r = self.e.run(argv)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stderr, "")
        self.assertEqual(self.e.child()["argv"], argv)
        self.assertFalse((self.e.home / "sessions").exists())
        row = self.e.launches()[-1]
        self.assertEqual((row["mode"], row["why"], row["tools_empty"], row["node"]),
                         ("passthrough", "unmarked", True, None))

    def test_unmarked_schema_launch_untouched(self):
        # 印の無い output_format（〔包試〕の --tools Read の節）も触らない
        argv = sdk_argv("", tools="Read")
        r = self.e.run(argv)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.e.child()["argv"], argv)

    def test_marked_launch_with_unreadable_settings_fails_closed(self):
        # 印のある起動は柵（フック・no-post・切符）なしで起こさない（裁定 I2）
        broken = [
            sdk_argv("works-node: judge", extra=["--settings", SANDBOX]),                       # --settings が 2 つ
            sdk_argv("works-node: judge", settings="{not json"),                                # 読めない JSON
            sdk_argv("works-node: judge", settings="/no/such/settings.json"),                   # 無いファイル
            sdk_argv("works-node: judge", settings="[1, 2]"),                                   # 辞書でない
            sdk_argv("works-node: pr-check no-post", settings='{"permissions": []}'),           # 混ぜられない
            sdk_argv("works-node: fix", settings='{"sandbox": {"filesystem": 1}}'),             # 混ぜられない（柵の口）
            sdk_argv("works-node: judge", settings=None) + ["--settings"],                      # 値の無い旗
        ]
        for argv in broken:
            with self.subTest(argv=argv[-2:]):
                if "filesystem" in argv[-1]:
                    t = adapter.ticket_path(self.e.cwd, self.e.home)
                    t.parent.mkdir(parents=True, exist_ok=True)
                    t.write_text(json.dumps({"protected": [str(self.e.tmp / "board")]}), encoding="utf-8")
                r = self.e.run(argv)
                self.assertEqual(r.returncode, 3, r.stderr)
                lines = r.stderr.splitlines()
                self.assertEqual(len(lines), 1, r.stderr)
                self.assertIn("起こさない", lines[0])
                self.assertIsNone(self.e.child())
                row = self.e.launches()[-1]
                self.assertEqual((row["mode"], row["session"]["mode"]), ("refused", "refused"))
                self.assertFalse(adapter.session_path(self.e.cwd, row["node"], self.e.home).exists())

    def test_unmarked_unknown_shapes_pass_through_with_warning(self):
        # 印の跡の無い見分けられない形は、1 バイトも変えずに素通しして警告を 1 行
        for argv in (sdk_argv("") + ["--json-schema", schema()], sdk_argv("") [:-2] + ["--json-schema", "{not json"]):
            with self.subTest(argv=argv[-1][:20]):
                r = self.e.run(argv)
                self.assertEqual(r.returncode, 0, r.stderr)
                self.assertEqual(len(r.stderr.strip().splitlines()), 1, r.stderr)
                self.assertIn("素通し", r.stderr)
                self.assertEqual(self.e.child()["argv"], argv)

    def test_judge_id_unwritable_fails_closed(self):
        # 判定役の id を記録できなければ起こさない（再審が古い id を継がないように。M6）
        key_dir = adapter.session_path(self.e.cwd, "judge", self.e.home).parent
        key_dir.parent.mkdir(parents=True)
        key_dir.write_text("ファイルで塞ぐ", encoding="utf-8")   # makedirs が失敗する
        r = self.e.run(sdk_argv("works-node: judge"))
        self.assertEqual(r.returncode, 3, r.stderr)
        self.assertEqual(len(r.stderr.splitlines()), 1, r.stderr)
        self.assertIn("記録できない", r.stderr)
        self.assertIsNone(self.e.child())
        self.assertEqual(self.e.launches()[-1]["mode"], "refused")

    def test_stale_judge_id_removed_when_new_id_unwritable(self):
        path = adapter.session_path(self.e.cwd, "judge", self.e.home)
        path.parent.mkdir(parents=True)
        path.write_text("dddddddd-0000-4000-8000-000000000001\n", encoding="utf-8")
        path.parent.chmod(0o500)   # 一時ファイルを置けない（古い id は消しに行く。消せなくても起こさない）
        self.addCleanup(path.parent.chmod, 0o700)
        r = self.e.run(sdk_argv("works-node: judge"))
        self.assertEqual(r.returncode, 3, r.stderr)
        self.assertIsNone(self.e.child())

    def test_bad_marker_fails_closed(self):
        # 印の跡が在るのに読めない起動は素通ししない（黙って新しい会話で再審させず、no-post の柵も落とさない）
        for desc, argv in (("works-node: rejudge continue=", sdk_argv("works-node: rejudge continue=")),
                           ("works-node: pr-check no-psot", sdk_argv("works-node: pr-check no-psot")),
                           ("works-node: Rejudge continue=judge", sdk_argv("works-node: Rejudge continue=judge")),
                           ("--json-schema が 2 つ", sdk_argv("works-node: judge")
                            + ["--json-schema", schema("works-node: fix")])):
            with self.subTest(desc):
                r = self.e.run(argv)
                self.assertEqual(r.returncode, 3)
                lines = r.stderr.splitlines()
                self.assertEqual(len(lines), 1, r.stderr)
                self.assertIn(desc, lines[0])
                self.assertIsNone(self.e.child())
                self.assertFalse((self.e.home / "sessions").exists())
                row = self.e.launches()[-1]
                self.assertEqual((row["mode"], row["session"]["mode"]), ("refused", "refused"))

    def _fake_gh_bin(self):
        """PATH に置く偽の本物の gh（受けた argv を FAKE_GH_LOG に 1 行ずつ）"""
        bindir = self.e.tmp / "gh-bin"
        bindir.mkdir(exist_ok=True)
        gh = bindir / "gh"
        gh.write_text("#!/bin/sh\nprintf '%s\\n' \"$*\" >> \"$FAKE_GH_LOG\"\n")
        gh.chmod(0o755)
        return bindir, gh

    def test_no_post_is_an_allowlist(self):
        # 読むだけの役の gh は許す物の一覧で組む（deny は allow に勝つので、gh を丸ごと拒み、読む口 works-gh を渡す）
        bindir, gh = self._fake_gh_bin()
        path = str(bindir) + os.pathsep + os.environ["PATH"]
        r = self.e.run(sdk_argv("works-node: pr-check no-post"), PATH=path)
        self.assertEqual(r.returncode, 0, r.stderr)
        child = self.e.child()
        s, _ = self._hook_settings(child["argv"])
        deny = s["permissions"]["deny"]
        self.assertIn("Bash(gh:*)", deny)
        self.assertIn("Bash(git push:*)", deny)
        self.assertIn(f"Bash({gh}:*)", deny)                                           # 本物の gh の絶対パス
        with self.subTest("/private の別名の綴り"):
            self.assertIn(f"Bash({hermetic.alias(self, gh)}:*)", deny)
        self.assertFalse([x for x in s.get("permissions", {}).get("allow", []) if "gh" in x], "allow では一部を許せない")
        # 子の env: PATH の頭に口、WORKS_GH は口、WORKS_REAL_GH は本物の gh
        env = child["env"]
        self.assertEqual(env["PATH"].split(os.pathsep)[0], str(adapter.NO_POST_BIN))
        self.assertEqual(env["WORKS_GH"], str(adapter.NO_POST_BIN / "works-gh"))
        self.assertEqual(env["WORKS_REAL_GH"], str(gh))
        self.assertEqual(env["WORKS_GH_ACTIVE"], "")
        # PATH の上の gh は全部（手元の本物の gh も）絶対パスで拒む
        self.assertEqual(self.e.launches()[-1]["fence"]["no_post"], len(adapter.no_post_rules(adapter.find_gh(path))))
        for g in adapter.find_gh(path):
            self.assertIn(f"Bash({g}:*)", deny)
        # 印に no-post の無い起動は、gh の柵も env の差し替えも無い
        r = self.e.run(sdk_argv("works-node: pr-check"), PATH=path)
        s, _ = self._hook_settings(self.e.child()["argv"])
        self.assertNotIn("permissions", s)
        self.assertEqual(self.e.child()["env"]["PATH"], path)
        self.assertNotIn("WORKS_GH", self.e.child()["env"])

    def test_works_gh_passes_only_read_forms(self):
        bindir, gh = self._fake_gh_bin()
        log = self.e.tmp / "gh.log"
        env = hermetic.child_env(WORKS_REAL_GH=str(gh), FAKE_GH_LOG=str(log), PYTHONDONTWRITEBYTECODE="1")
        allowed = [["pr", "list", "-R", "o/r"], ["pr", "list", "--repo=o/r", "--json", "number"],
                   ["pr", "view", "12", "-R", "o/r", "--comments"], ["pr", "diff", "12", "--repo", "github.com/o/r"],
                   ["repo", "view", "o/r", "--json", "name"]]
        refused = [[], ["api", "repos/o/r/issues", "-X", "POST"], ["api", "graphql", "-f", "query=x"],
                   ["pr", "comment", "12", "-R", "o/r", "-b", "x"], ["pr", "edit", "12", "-R", "o/r"],
                   ["pr", "update-branch", "12", "-R", "o/r"], ["pr", "checkout", "12", "-R", "o/r"],
                   ["pr", "view", "12"], ["pr", "list"], ["pr", "view", "12", "-R", "o/r", "--web"],
                   ["repo", "view"], ["repo", "view", "--web", "o/r"], ["repo", "set-default", "o/r"],
                   ["issue", "create"], ["label", "create", "x"], ["workflow", "run", "x"], ["secret", "set", "X"],
                   ["release", "delete", "v1"], ["alias", "set", "x", "y"], ["auth", "token"]]
        for shim in (adapter.NO_POST_BIN / "works-gh", adapter.NO_POST_BIN / "gh"):
            for args in allowed:
                with self.subTest(shim=shim.name, args=args):
                    r = subprocess.run([str(shim), *args], env=env, capture_output=True, text=True, encoding="utf-8")
                    self.assertEqual(r.returncode, 0, r.stderr)
                    self.assertEqual(log.read_text().splitlines()[-1], " ".join(args))
            for args in refused:
                with self.subTest(shim=shim.name, args=args):
                    before = log.read_text() if log.exists() else ""
                    r = subprocess.run([str(shim), *args], env=env, capture_output=True, text=True, encoding="utf-8")
                    self.assertEqual(r.returncode, 2, r.stderr)
                    self.assertEqual(len(r.stderr.splitlines()), 1, r.stderr)
                    self.assertEqual(log.read_text() if log.exists() else "", before)   # 本物の gh を起こさない

    def test_works_gh_refuses_without_real_gh(self):
        for real in ("", "/no/such/gh", str(adapter.NO_POST_BIN / "works-gh"), str(adapter.NO_POST_BIN / "gh")):
            with self.subTest(real):
                env = hermetic.child_env(WORKS_REAL_GH=real)
                r = subprocess.run([str(adapter.NO_POST_BIN / "works-gh"), "pr", "list", "-R", "o/r"], env=env,
                                   capture_output=True, text=True, encoding="utf-8")
                self.assertEqual(r.returncode, 2, r.stderr)
                self.assertIn("本物の gh", r.stderr)

    def test_works_gh_cannot_recurse(self):
        # 本物の gh と取り違えた物が、別の置き場から口（PATH の頭の gh）を起こし直しても輪にならない（期限に頼らず、
        # 2 度目に口へ入った所で拒む）。取り違えた物は起こされた回数を数え、4 回目で 99 を返して輪を自分で断つ（試験の底）
        fwd = self.e.tmp / "fwd-gh"
        count = self.e.tmp / "count"
        fwd.write_text("#!/bin/sh\necho x >> \"$COUNT\"\n"
                       "[ \"$(wc -l < \"$COUNT\")\" -ge 4 ] && exit 99\n"
                       f'exec "{adapter.NO_POST_BIN / "gh"}" "$@"\n')
        fwd.chmod(0o755)
        env = hermetic.child_env(WORKS_REAL_GH=str(fwd), COUNT=str(count))
        env.pop("WORKS_GH_ACTIVE", None)
        r = subprocess.run([str(adapter.NO_POST_BIN / "gh"), "pr", "list", "-R", "o/r"], env=env,
                           capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(r.returncode, 2, r.stderr)
        self.assertEqual(count.read_text().count("x"), 1)   # 取り違えた物は 1 度だけ起き、口の 2 度目で止まった
        self.assertIn("起こし直された", r.stderr)

    def test_find_gh_skips_the_shim(self):
        bindir, gh = self._fake_gh_bin()
        got = adapter.find_gh(os.pathsep.join([str(adapter.NO_POST_BIN), "relative", str(bindir), str(bindir)]))
        self.assertEqual(got, [str(gh)])

    # --- 設定のマージ ----------------------------------------------------------------------------------------
    def _hook_settings(self, argv):
        vals = opt(argv, "--settings")
        self.assertEqual(len(vals), 1, argv)
        s = json.loads(vals[0])
        hooks = [h for m in s["hooks"]["PostToolUse"] if m.get("matcher") == "Read" for h in m["hooks"]]
        self.assertEqual(len(hooks), 1, s)
        self.assertEqual(hooks[0]["type"], "command")
        self.assertNotIn("timeout", hooks[0])   # 期限を足さない
        return s, hooks[0]["command"]

    def test_settings_three_spellings_merged(self):
        f = self.e.tmp / "sdk-settings.json"
        f.write_text(SANDBOX, encoding="utf-8")
        base = sdk_argv("works-node: fix", settings=None)
        for tail, spelled in ((["--settings", SANDBOX], "split"), (["--settings=" + SANDBOX], "joined"),
                              (["--settings", str(f)], "file")):
            with self.subTest(spelled):
                r = self.e.run(base + tail)
                self.assertEqual(r.returncode, 0, r.stderr)
                self.assertEqual(r.stderr, "")
                got = self.e.child()["argv"]
                s, _ = self._hook_settings(got)
                self.assertEqual(s["sandbox"], json.loads(SANDBOX)["sandbox"])   # SDK の鍵はそのまま
                if spelled == "joined":
                    self.assertTrue(any(a.startswith("--settings=") for a in got))
                # 置き換えたのは --settings の値だけ（あとは --session-id を末尾に足しただけ）
                self.assertEqual(got[:len(base)], base)
                row = self.e.launches()[-1]
                self.assertEqual((row["mode"], row["hook"]), ("merged", True))

    def test_settings_merge_keeps_sdk_hooks_and_keys(self):
        sdk = {"sandbox": {"enabled": True}, "permissions": {"deny": ["Bash(rm:*)"]},
               "hooks": {"PostToolUse": [{"matcher": "Bash", "hooks": [{"type": "command", "command": "true"}]}],
                         "Stop": [{"hooks": [{"type": "command", "command": "true"}]}]}}
        r = self.e.run(sdk_argv("works-node: fix", settings=json.dumps(sdk)))
        self.assertEqual(r.returncode, 0, r.stderr)
        s, _ = self._hook_settings(self.e.child()["argv"])
        self.assertEqual(s["sandbox"], sdk["sandbox"])
        self.assertEqual(s["permissions"], sdk["permissions"])
        self.assertEqual(s["hooks"]["Stop"], sdk["hooks"]["Stop"])
        self.assertEqual([m["matcher"] for m in s["hooks"]["PostToolUse"]], ["Bash", "Read", "Edit|Write|NotebookEdit"])

    def test_no_settings_gets_hook_only(self):
        # sandbox の無い節は SDK が --settings を付けない（〔包試〕の (f)）
        argv = sdk_argv("works-node: fix", settings=None)
        self.assertEqual(opt(argv, "--settings"), [])
        r = self.e.run(argv)
        self.assertEqual(r.returncode, 0, r.stderr)
        s, _ = self._hook_settings(self.e.child()["argv"])
        self.assertEqual(set(s), {"hooks"})

    def test_setting_sources_untouched(self):
        for spelled in (["--setting-sources=project,user"], ["--setting-sources", ""], ["--setting-sources="]):
            with self.subTest(spelled):
                argv = [a for a in sdk_argv("works-node: fix") if not a.startswith("--setting-sources")]
                argv = argv[:6] + spelled + argv[6:]
                r = self.e.run(argv)
                self.assertEqual(r.returncode, 0, r.stderr)
                got = self.e.child()["argv"]
                i = got.index(spelled[0])
                self.assertEqual(got[i:i + len(spelled)], spelled)
                self.assertEqual(sum(a.startswith("--setting-sources") for a in got), 1)

    def test_model_preserved(self):
        for desc in (None, "works-node: judge", "works-node: rejudge continue=judge"):
            with self.subTest(desc):
                if desc and "continue" in desc:
                    self.e.run(sdk_argv("works-node: judge"))
                r = self.e.run(sdk_argv(desc))
                self.assertEqual(r.returncode, 0, r.stderr)
                self.assertEqual(opt(self.e.child()["argv"], "--model"), ["opus"])

    # --- Read のフック ---------------------------------------------------------------------------------------
    def test_read_hook_records_file_and_sha(self):
        r = self.e.run(sdk_argv("works-node: fix"))
        self.assertEqual(r.returncode, 0, r.stderr)
        _, command = self._hook_settings(self.e.child()["argv"])
        doc = self.e.cwd / "doc.md"
        doc.write_text("読む文書\n", encoding="utf-8")
        event = {"session_id": "s-1", "tool_name": "Read", "tool_input": {"file_path": str(doc)},
                 "tool_use_id": "toolu_x", "cwd": str(self.e.cwd), "hook_event_name": "PostToolUse"}
        # claude と同じく、フックのコマンドを sh で起こして出来事を標準入力に渡す（cwd は役の worktree）
        h = subprocess.run(["sh", "-c", command], cwd=str(self.e.cwd), input=json.dumps(event), text=True, encoding="utf-8",
                           capture_output=True, env=hermetic.child_env(PYTHONDONTWRITEBYTECODE="1"))
        self.assertEqual(h.returncode, 0, h.stderr)
        log = adapter.reads_dir(self.e.cwd, self.e.home) / "reads.jsonl"
        rows = [json.loads(ln) for ln in log.read_text(encoding="utf-8").splitlines()]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["path"], str(doc.resolve()))
        self.assertEqual(rows[0]["file_sha"], hashlib.sha256(doc.read_bytes()).hexdigest())
        self.assertEqual((rows[0]["session_id"], rows[0]["tool_use_id"], rows[0]["partial"]), ("s-1", "toolu_x", False))
        # 写しの engine が読む形（hook_evidence）のまま
        from graphloops.engine import util
        self.assertEqual(util.hook_evidence(log.parent, str(doc))[0], "read")
        doc.write_text("書き換えた\n", encoding="utf-8")
        self.assertEqual(util.hook_evidence(log.parent, str(doc))[0], "stale")

    def test_recorder_writes_nothing_without_sink(self):
        with tempfile.TemporaryDirectory() as t:
            doc = pathlib.Path(t, "d.txt")
            doc.write_text("x", encoding="utf-8")
            event = {"tool_name": "Read", "tool_input": {"file_path": str(doc)}, "cwd": t}
            for args in ([], [str(pathlib.Path(t, "missing-dir"))]):
                h = subprocess.run([sys.executable, str(RECORDER), *args], input=json.dumps(event), text=True, encoding="utf-8",
                                   capture_output=True, cwd=t)
                self.assertEqual(h.returncode, 0, h.stderr)
            self.assertEqual(sorted(p.name for p in pathlib.Path(t).iterdir()), ["d.txt"])

    def test_record_read_copy_differs_only_in_sink(self):
        """record-read.py は graphloops a1202d0:graphloops/hooks/record-read.py の写しで、書く先を決める boards() だけを替えた"""
        src = subprocess.run(["git", "-C", str(ROOT), "show", "a1202d0:graphloops/hooks/record-read.py"],
                             capture_output=True, text=True, encoding="utf-8")
        if src.returncode != 0:
            self.skipTest("SKIP git-history: a1202d0 を引けない（浅い clone か、graphloops の履歴を持たない）: " + src.stderr.strip()[-200:])

        def outside_boards(text):
            head, rest = text.split("\ndef boards(", 1)
            return head + rest[rest.index("\nREAD_CAP = "):]
        self.assertEqual(outside_boards(RECORDER.read_text(encoding="utf-8")), outside_boards(src.stdout))

    # --- 会話の継ぎ -------------------------------------------------------------------------------------------
    def test_judge_gets_session_id_and_records(self):
        argv = sdk_argv("works-node: judge")
        r = self.e.run(argv)
        self.assertEqual(r.returncode, 0, r.stderr)
        got = self.e.child()["argv"]
        added = [a for a in got if a.startswith("--session-id=")]
        self.assertEqual(len(added), 1)
        sid = added[0].split("=", 1)[1]
        self.assertRegex(sid, UUID_RE)
        self.assertEqual(self.e.session_id("judge"), sid)
        row = self.e.launches()[-1]
        self.assertEqual(row["session"], {"mode": "new", "id": sid})
        self.assertEqual(row["node"], "judge")

    def test_judge_sdk_ids_recorded_as_is(self):
        # Archon 自身が継いだ回（ブロックの出し直しの 2 周目）: SDK の id をそのまま記録し、argv は変えない
        for extra, mode, want in ((["--resume=aaaaaaaa-0000-4000-8000-000000000001"], "sdk-resume",
                                   "aaaaaaaa-0000-4000-8000-000000000001"),
                                  (["--resume", "aaaaaaaa-0000-4000-8000-000000000002"], "sdk-resume",
                                   "aaaaaaaa-0000-4000-8000-000000000002"),
                                  (["--session-id", "aaaaaaaa-0000-4000-8000-000000000003"], "sdk-session",
                                   "aaaaaaaa-0000-4000-8000-000000000003")):
            with self.subTest(extra):
                argv = sdk_argv("works-node: judge", extra=extra)
                r = self.e.run(argv)
                self.assertEqual(r.returncode, 0, r.stderr)
                got = self.e.child()["argv"]
                self.assertEqual([a for a in got if "session" in a or "resume" in a],
                                 [a for a in argv if "session" in a or "resume" in a])
                self.assertEqual(self.e.session_id("judge"), want)
                expect = {"mode": mode, "id": want}
                if mode == "sdk-resume":
                    expect["from"] = want
                self.assertEqual(self.e.launches()[-1]["session"], expect)

    def test_judge_sdk_fork_gets_new_session_id(self):
        # 出し直しの 2 周目を Archon が fork で継ぐ時: 新しい会話の id は SDK が知らせないので包みが決めて記録する
        argv = sdk_argv("works-node: judge", extra=["--resume", "aaaaaaaa-0000-4000-8000-000000000001",
                                                    "--fork-session"])
        r = self.e.run(argv)
        self.assertEqual(r.returncode, 0, r.stderr)
        got = self.e.child()["argv"]
        i = argv.index("--settings") + 1   # 変わるのはフックを足した --settings の値だけ
        self.assertEqual(got[:i] + got[i + 1:len(argv)], argv[:i] + argv[i + 1:])
        sid = got[-1].split("=", 1)[1]
        self.assertTrue(got[-1].startswith("--session-id="))
        self.assertNotEqual(sid, "aaaaaaaa-0000-4000-8000-000000000001")
        self.assertEqual(self.e.session_id("judge"), sid)
        # 費用の引き算（fork の会話は元の会話の合計を引き継ぐ）が元を辿れるように from を持つ
        self.assertEqual(self.e.launches()[-1]["session"],
                         {"mode": "sdk-fork", "id": sid, "from": "aaaaaaaa-0000-4000-8000-000000000001"})

    def test_continue_strips_sdk_session_flags_and_resumes(self):
        self.e.run(sdk_argv("works-node: judge"))
        judge = self.e.session_id("judge")
        sdk_flags = ["--resume=bbbbbbbb-0000-4000-8000-000000000001", "--fork-session",
                     "--session-id", "bbbbbbbb-0000-4000-8000-000000000002", "--continue"]
        argv = sdk_argv("works-node: rejudge continue=judge", extra=sdk_flags)
        r = self.e.run(argv)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stderr, "")
        got = self.e.child()["argv"]
        for f in sdk_flags:
            self.assertNotIn(f, got)
        self.assertFalse(any(a.startswith(("--session-id", "--resume=")) for a in got), got)
        self.assertEqual(got[-2:], ["--resume", judge])
        self.assertEqual(opt(got, "--resume"), [judge])
        self.assertEqual(self.e.session_id("rejudge"), judge)   # 再審も同じ会話（fork しない）
        row = self.e.launches()[-1]
        self.assertEqual(row["session"], {"mode": "continued", "id": judge, "of": "judge", "from": judge})

    def test_continue_keeps_settings_sources_and_model(self):
        # 〔継試〕の (3): 再開の起動にも sandbox の --settings と --setting-sources が残る
        self.e.run(sdk_argv("works-node: judge"))
        argv = sdk_argv("works-node: rejudge continue=judge")
        r = self.e.run(argv)
        self.assertEqual(r.returncode, 0, r.stderr)
        got = self.e.child()["argv"]
        s, _ = self._hook_settings(got)
        self.assertEqual(s["sandbox"], json.loads(SANDBOX)["sandbox"])
        self.assertIn("--setting-sources=project,user", got)
        self.assertEqual(opt(got, "--model"), ["opus"])
        self.assertEqual(opt(got, "--json-schema"), opt(argv, "--json-schema"))

    def test_rejudge_chain_resumes_same_session(self):
        # 本線 3-6 の形（再審 3 回）: どれも同じ判定役の会話を継ぐ
        self.e.run(sdk_argv("works-node: judge"))
        judge = self.e.session_id("judge")
        for name in ("rejudge", "rejudge2", "rejudge3"):
            r = self.e.run(sdk_argv(f"works-node: {name} continue=judge"))
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertEqual(self.e.child()["argv"][-2:], ["--resume", judge])

    def test_continue_missing_id_fails_closed(self):
        path = adapter.session_path(self.e.cwd, "judge", self.e.home)
        for prepare in ("missing", "empty", "broken"):
            with self.subTest(prepare):
                if prepare != "missing":
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text("" if prepare == "empty" else "two words\n", encoding="utf-8")
                r = self.e.run(sdk_argv("works-node: rejudge continue=judge"))
                self.assertEqual(r.returncode, 3)
                lines = r.stderr.splitlines()
                self.assertEqual(len(lines), 1, r.stderr)
                self.assertIn(str(path), lines[0])
                self.assertIn("judge", lines[0])
                self.assertIsNone(self.e.child())   # 子を起こさない
                row = self.e.launches()[-1]
                self.assertEqual((row["mode"], row["session"]["mode"], row["session"]["of"]),
                                 ("refused", "refused", "judge"))
                self.assertFalse(adapter.session_path(self.e.cwd, "rejudge", self.e.home).exists())

    def test_sessions_are_separated_by_cwd(self):
        other = self.e.tmp / "wt2"
        other.mkdir()
        self.e.run(sdk_argv("works-node: judge"))
        self.e.run(sdk_argv("works-node: judge"), cwd=other)
        a, b = self.e.session_id("judge"), self.e.session_id("judge", cwd=other)
        self.assertNotEqual(a, b)
        self.e.run(sdk_argv("works-node: rejudge continue=judge"), cwd=other)
        self.assertEqual(self.e.child()["argv"][-1], b)
        # 同じ cwd の後の判定役は前の id を書き直す（直近の判定役を継ぐ）
        self.e.run(sdk_argv("works-node: judge"))
        self.assertNotEqual(self.e.session_id("judge"), a)

    # --- 実物の argv ------------------------------------------------------------------------------------------
    def test_real_resume_probe_argv(self):
        """〔継試〕の 13 回の起動: 印の見分けが試しの包みと同じ。題の生成は触らない。再審は judge の id で継ぐ"""
        launches = json.loads((SAMPLES / "resume-probe.json").read_text(encoding="utf-8"))["launches"]
        self.assertEqual(len(launches), 13)
        home, cwd = self.e.home, self.e.cwd
        for n, s in enumerate(launches):
            with self.subTest(n=n, marker=s["marker"]):
                p = adapter.plan(s["argv"], cwd, home, "HOOK", new_id=lambda: "cccccccc-0000-4000-8000-%012d" % n)
                self.assertEqual((p.node, p.cont), (s["marker"], s["continue"]))
                if s["marker"] is None:
                    self.assertEqual((p.argv, p.mode, p.why, p.warn), (s["argv"], "passthrough", "unmarked", False))
                    continue
                self.assertEqual((p.mode, p.warn), ("merged", False))
                if s["continue"]:
                    self.assertEqual(p.argv[-2:], ["--resume", "cccccccc-0000-4000-8000-%012d" % (n - 2)])
                    self.assertEqual(p.session["mode"], "continued")
                else:
                    self.assertEqual(p.argv[-1], "--session-id=cccccccc-0000-4000-8000-%012d" % n)
                for path, sid in p.record:
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text(sid + "\n", encoding="utf-8")
                # 足したのは --settings の値と会話の旗だけ
                rest = [a for a in p.argv if not a.startswith(("--session-id=", "cccccccc"))
                        and a != "--resume"]
                i = s["argv"].index("--settings")
                self.assertEqual(rest[:i + 1] + rest[i + 2:], s["argv"][:i + 1] + s["argv"][i + 2:])

    def test_real_wrap_probe_argv_untouched(self):
        """〔包試〕の 6 回の起動は印を持たないので、どれも 1 バイトも変えない"""
        for s in json.loads((SAMPLES / "wrap-probe.json").read_text(encoding="utf-8"))["launches"]:
            p = adapter.plan(s["argv"], self.e.cwd, self.e.home, "HOOK")
            self.assertEqual((p.argv, p.mode, p.record), (s["argv"], "passthrough", []))

    # --- 起こし方 ---------------------------------------------------------------------------------------------
    def test_stdio_and_exit_code_pass_through(self):
        r = self.e.run(sdk_argv("works-node: fix"), stdin="1\n2\n3\n", exit_code=5)
        self.assertEqual(r.returncode, 5)
        self.assertEqual(r.stdout, "1\n2\n3\n")
        self.assertEqual(self.e.child()["stdin"], "1\n2\n3\n")

    def test_child_keeps_env_and_cwd(self):
        r = self.e.run(sdk_argv(None), CLAUDE_CODE_OAUTH_TOKEN="dummy-token-for-test")
        self.assertEqual(r.returncode, 0, r.stderr)
        c = self.e.child()
        self.assertEqual(c["cwd"], str(self.e.cwd))
        self.assertEqual(c["env"]["CLAUDE_CODE_OAUTH_TOKEN"], "dummy-token-for-test")
        self.assertEqual(c["argv0"], str(FAKE))

    def test_real_claude_from_path_when_env_unset(self):
        bindir = self.e.tmp / "bin"
        bindir.mkdir()
        (bindir / "claude").symlink_to(FAKE)
        r = self.e.run(sdk_argv(None), WORKS_REAL_CLAUDE=None, PATH=str(bindir) + os.pathsep + os.environ["PATH"])
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.e.child()["argv"], sdk_argv(None))

    def test_real_claude_missing_or_self_refused(self):
        emptybin = self.e.tmp / "empty-bin"
        emptybin.mkdir()
        (emptybin / "claude").symlink_to(ADAPTER)   # PATH の claude が包み自身（CLAUDE_BIN_PATH で差した時の取り違え）
        for over in ({"WORKS_REAL_CLAUDE": str(self.e.tmp / "nope")},
                     {"WORKS_REAL_CLAUDE": str(ADAPTER)},
                     {"WORKS_REAL_CLAUDE": None, "PATH": str(emptybin) + os.pathsep + "/usr/bin:/bin"}):
            with self.subTest(over):
                r = self.e.run(sdk_argv(None), **over)
                self.assertEqual(r.returncode, 127)
                self.assertEqual(len(r.stderr.splitlines()), 1, r.stderr)
                self.assertIsNone(self.e.child())

    def test_launch_rows_carry_time_and_last_judge(self):
        """再審の前の確かめ（rejudge の session_ready）が使う口: judge.id・最後の judge の行・その行の at"""
        import datetime
        before = datetime.datetime.now().astimezone()
        self.e.run(sdk_argv("works-node: judge"))
        first = self.e.session_id("judge")
        self.e.run(sdk_argv("works-node: fix"))
        self.e.run(sdk_argv("works-node: judge"))
        self.e.run(sdk_argv("works-node: rejudge continue=judge"))
        after = datetime.datetime.now().astimezone()
        rows = adapter.read_launches(self.e.cwd, self.e.home)
        self.assertEqual([r["node"] for r in rows], ["judge", "fix", "judge", "rejudge"])
        ats = [datetime.datetime.fromisoformat(r["at"]) for r in rows]
        for at in ats:
            self.assertIsNotNone(at.tzinfo)   # 盤面の state.created（時差つき）と比べられる
            self.assertTrue(before.replace(microsecond=0) <= at <= after, at)
        self.assertEqual(ats, sorted(ats))
        last = adapter.last_launch(self.e.cwd, "judge", self.e.home)
        self.assertEqual(last, rows[2])
        self.assertEqual(last["session"]["id"], self.e.session_id("judge"))
        self.assertNotEqual(last["session"]["id"], first)
        self.assertIsNone(adapter.last_launch(self.e.cwd, "plan", self.e.home))
        self.assertEqual(rows[3]["session"]["from"], last["session"]["id"])
        self.assertNotIn("ts", rows[0])

    def test_read_launches_skips_broken_lines(self):
        path = adapter.launches_path(self.e.cwd, self.e.home)
        path.parent.mkdir(parents=True)
        path.write_text('{"node": "judge", "at": "x"}\nnot json\n[1]\n{"node": "fix"}\n', encoding="utf-8")
        self.assertEqual([r["node"] for r in adapter.read_launches(self.e.cwd, self.e.home)], ["judge", "fix"])
        self.assertEqual(adapter.read_launches(self.e.tmp / "elsewhere", self.e.home), [])

    def test_relative_home_refused(self):
        r = self.e.run(sdk_argv("works-node: judge"), WORKS_ADAPTER_HOME="rel/home")
        self.assertEqual(r.returncode, 2)
        self.assertEqual(len(r.stderr.splitlines()), 1, r.stderr)
        self.assertIn("WORKS_ADAPTER_HOME", r.stderr)
        self.assertIsNone(self.e.child())
        self.assertFalse((self.e.cwd / "rel").exists())

    def test_name_not_js_and_executable(self):
        # Archon は .js で終わる実行ファイルを bun で起こして --no-env-file を足す（〔包試〕）
        for p in (ADAPTER, RECORDER):
            self.assertFalse(p.name.endswith((".js", ".mjs", ".cjs")), p)
        self.assertTrue(os.access(ADAPTER, os.X_OK))
        self.assertEqual(ADAPTER.read_text(encoding="utf-8").splitlines()[0], "#!/usr/bin/env python3")

    def test_no_pycache_in_pack(self):
        self.e.run(sdk_argv("works-node: fix"))
        self.assertEqual(list(CORE.rglob("__pycache__")), [])

    def test_state_dirs_are_private(self):
        self.e.run(sdk_argv("works-node: judge"))
        for p in (adapter.session_path(self.e.cwd, "judge", self.e.home).parent,
                  adapter.reads_dir(self.e.cwd, self.e.home)):
            self.assertEqual(p.stat().st_mode & 0o077, 0, p)


def gone(pid):
    """pid がもう居ない（ゾンビも居ないと数える）。待たずにその場で 1 度だけ見る。
    包みは tree_run.stop_group で数え直して仲間が消えたのを見てから抜けるので、抜けた後に見れば足りる"""
    r = subprocess.run(["ps", "-o", "stat=", "-p", str(pid)], capture_output=True, text=True, encoding="utf-8")
    return r.returncode != 0 or r.stdout.strip().startswith("Z") or not r.stdout.strip()


class StopCase(unittest.TestCase):
    """木ごと止める（試し P15）: 偽の claude は本物の Bash の道具と同じく、孫を新しいセッションで起こし、SIGTERM を
    受けると孫へ TERM だけ送って即抜ける。孫は SIGTERM を無視する。claude のグループへ送るだけの包みでは孫が残る"""

    @classmethod
    def setUpClass(cls):
        if not hasattr(os, "killpg"):
            raise unittest.SkipTest("SKIP process-group: この OS の os に killpg が無い（包みは孫をプロセスのグループで止める）")

    def setUp(self):
        self.e = Env(self)
        self.pidfile = self.e.tmp / "grandchild.pid"

    def start(self, stay, orphan=False):
        env = {k: v for k, v in hermetic.child_env().items() if not k.startswith("WORKS_")}
        env.update(WORKS_ADAPTER_HOME=str(self.e.home), WORKS_REAL_CLAUDE=str(FAKE), FAKE_CLAUDE_LOG=str(self.e.log),
                   FAKE_CLAUDE_GRANDCHILD=str(self.pidfile), PYTHONDONTWRITEBYTECODE="1")
        if stay:
            env["FAKE_CLAUDE_STAY"] = "1"
        if orphan:
            env["FAKE_CLAUDE_ORPHAN"] = "1"
        p = subprocess.Popen([str(ADAPTER), *sdk_argv("works-node: fix")], cwd=str(self.e.cwd), env=env,
                             stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True, encoding="utf-8")
        self.addCleanup(self._reap, p)
        while not self.pidfile.exists():
            self.assertIsNone(p.poll(), "包みが孫を起こす前に抜けた")
            time.sleep(0.05)
        self.grandchild = int(self.pidfile.read_text())
        return p

    def _reap(self, p):
        if p.poll() is None:
            p.kill()
            p.wait()
        if hasattr(self, "grandchild"):
            try:
                os.killpg(self.grandchild, signal.SIGKILL)   # 試験が赤の時の後片付け（自分が起こした孫のグループ）
            except OSError:
                pass

    def _stopped_by(self, sig, code):
        p = self.start(stay=True)
        time.sleep(0.5)   # 包みの見回り（POLL）が 1 回は回る
        t0 = time.monotonic()
        p.send_signal(sig)
        rc = p.wait()
        took = time.monotonic() - t0
        self.assertEqual(rc, code, p.stderr.read())
        self.assertTrue(gone(self.grandchild), "SIGTERM を無視する孫（別のセッション）が残った")
        self.assertLess(took, 5.0)                       # Archon の cancel の猶予より前に抜ける
        self.assertGreaterEqual(took, adapter.LINGER)    # すぐ死なない（Archon の run が running で固まる穴。試し P17）

    def test_sigterm_kills_grandchild_in_other_session(self):
        self._stopped_by(signal.SIGTERM, 143)

    def test_sigint_kills_grandchild_in_other_session(self):
        self._stopped_by(signal.SIGINT, 130)

    def test_leftover_grandchild_killed_after_claude_exits(self):
        # claude が普通に終わって孫を残した時も止める（見回りで覚えたグループ）
        p = self.start(stay=False)
        rc = p.wait()
        self.assertEqual(rc, 0, p.stderr.read())
        self.assertTrue(gone(self.grandchild), "claude が残した孫が残った")

    def test_constants_come_from_tree_run(self):
        import tree_run
        for name in ("KILL_GRACE", "POLL", "LINGER", "PS_TIMEOUT", "STOP_SIGNALS"):
            self.assertEqual(getattr(adapter, name), getattr(tree_run, name), name)   # 値を 2 か所に書かない（M9）
        self.assertEqual(adapter.KILL_GRACE, 2)
        # tree_run の上限の勘定（信号に気づくまで POLL、SIGKILL まで KILL_GRACE + PS_TIMEOUT、抜けるまで LINGER）が
        # Archon の cancel の猶予 5 秒より前
        self.assertLess(adapter.POLL + adapter.KILL_GRACE + adapter.PS_TIMEOUT + adapter.LINGER, 5)

    def test_stop_failure_is_reported_not_crashed(self):
        # tree_run.stop_group が止め切れない理由を返した時、包みは標準エラーに 1 行を出して続ける（NameError で落ちない）
        import io
        from unittest import mock
        err = io.StringIO()
        with mock.patch.object(adapter.tree_run, "stop_group", return_value="孫が SIGKILL の後も残っている"), \
                mock.patch("sys.stderr", err):
            adapter._stop(object(), {}, 0.0)
        self.assertEqual(err.getvalue().splitlines(), ["works claude-adapter: 木を止め切れない: 孫が SIGKILL の後も残っている"])

    def test_stop_uses_tree_run(self):
        # 止め方は tree_run.stop_group（数え上げ→送る→数え直し）。弱い写しを持たない（M4）
        import inspect
        src = inspect.getsource(adapter.supervise) + inspect.getsource(adapter._stop) + inspect.getsource(adapter.watch)
        self.assertIn("tree_run.stop_group", src)
        self.assertIn("tree_run._tree_members", src)
        self.assertFalse(hasattr(adapter, "stop_all") or hasattr(adapter, "remember") or hasattr(adapter, "_ps"))

    def test_orphan_in_claude_session_between_polls_killed(self):
        # 見回りの間（POLL より短い間）に親が抜けて孤児になった孫も、claude のセッションに居れば拾う（M3・M4）。
        # 孫は setpgid で別のグループ（本物の Bash の道具の形）、SIGTERM を無視、親はすぐ抜ける
        p = self.start(stay=False, orphan=True)
        rc = p.wait()
        self.assertEqual(rc, 0, p.stderr.read())
        self.assertTrue(gone(self.grandchild), "見回りの間に孤児になった孫が残った")


def git(cwd, *args):
    return subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t", "-c", "commit.gpgsign=false",
                           "-C", str(cwd), *args], capture_output=True, text=True, encoding="utf-8", check=True).stdout


class FenceCase(unittest.TestCase):
    """起動ごとの柵: 切符の protected ＋ 起動の env の CLAUDE_CONFIG_DIR ＋ 切符の後に切られた worktree を、
    /var と /private/var の両方の綴りで permissions.deny（と sandbox の塊が在れば denyWrite）に足す"""

    def setUp(self):
        self.e = Env(self)
        # 元の作業ツリー repo と、役の cwd になる run の worktree（Archon が run ごとに切る物に見立てる）
        self.repo = self.e.tmp / "repo"
        self.repo.mkdir()
        git(self.repo, "init", "-q")
        git(self.repo, "commit", "-q", "--allow-empty", "-m", "seed")
        self.e.cwd.rmdir()
        git(self.repo, "worktree", "add", "-q", str(self.e.cwd))
        self.board = self.e.tmp / "board"
        self.board.mkdir()
        # 切符（ticket.write の形。protected は start の時点で git から引いた物）
        # ticket.protected_paths と同じく、役の worktree の `<cwd>/.git`（gitdir を指すファイル）も守る場所に入る（I1）
        self.ticket_protected = [str(self.repo / ".git"), str(self.repo), str(self.board), str(self.e.cwd / ".git")]
        t = adapter.ticket_path(self.e.cwd, self.e.home)
        t.parent.mkdir(parents=True)
        t.write_text(json.dumps({"run_id": "r1", "board": str(self.board), "cwd": str(self.e.cwd),
                                 "protected": self.ticket_protected, "written_at": "2026-09-27T00:00:00+09:00"}),
                     encoding="utf-8")

    def settings(self):
        return json.loads(opt(self.e.child()["argv"], "--settings")[0])

    def test_ticket_paths_denied_in_both_spellings(self):
        r = self.e.run(sdk_argv("works-node: fix"))
        self.assertEqual(r.returncode, 0, r.stderr)
        s = self.settings()
        deny = s["permissions"]["deny"]
        dw = s["sandbox"]["filesystem"]["denyWrite"]
        for tool in ("Edit", "Write"):
            self.assertIn(f"{tool}(/{self.board})", deny)
            self.assertIn(f"{tool}(/{self.board}/**)", deny)
        self.assertIn(str(self.board), dw)
        with self.subTest("/private の別名の綴り"):
            pub = hermetic.alias(self, self.board)   # macOS の一時フォルダの実体（/private の下）の別名
            for tool in ("Edit", "Write"):
                self.assertIn(f"{tool}(/{pub})", deny)
                self.assertIn(f"{tool}(/{pub}/**)", deny)
            self.assertIn(pub, dw)
            self.assertIn(f"Edit(/{hermetic.alias(self, self.e.cwd)}/.git/**)", deny)
        self.assertEqual({k: v for k, v in s["sandbox"].items() if k != "filesystem"}, json.loads(SANDBOX)["sandbox"])
        # 役の cwd の worktree 自身は守らない（役はそこに書く）。切符に在る cwd の中の `.git` は守る（I1）
        self.assertNotIn(f"Edit(/{self.e.cwd})", deny)
        self.assertNotIn(f"Edit(/{self.e.cwd}/**)", deny)
        self.assertIn(f"Write(/{self.e.cwd}/.git)", deny)
        self.assertIn(str(self.e.cwd / ".git"), dw)
        row = self.e.launches()[-1]
        self.assertGreater(row["fence"]["permissions_deny"], 0)
        self.assertGreater(row["fence"]["deny_write"], 0)

    def test_claude_config_dir_from_launch_env(self):
        cfg = self.e.tmp / "claude-config"
        r = self.e.run(sdk_argv("works-node: fix"), CLAUDE_CONFIG_DIR=str(cfg))
        self.assertEqual(r.returncode, 0, r.stderr)
        s = self.settings()
        self.assertIn(f"Write(/{cfg}/**)", s["permissions"]["deny"])
        self.assertIn(str(cfg), s["sandbox"]["filesystem"]["denyWrite"])
        with self.subTest("/private の別名の綴り"):
            self.assertIn(f"Write(/{hermetic.alias(self, cfg)}/**)", s["permissions"]["deny"])

    def test_worktree_added_after_ticket_is_denied(self):
        late = self.e.tmp / "late-wt"
        git(self.repo, "worktree", "add", "-q", str(late))   # 切符を書いた後に切られた worktree
        r = self.e.run(sdk_argv("works-node: fix"))
        self.assertEqual(r.returncode, 0, r.stderr)
        deny = self.settings()["permissions"]["deny"]
        self.assertIn(f"Edit(/{late}/**)", deny)
        with self.subTest("/private の別名の綴り"):
            self.assertIn(f"Edit(/{hermetic.alias(self, late)}/**)", deny)

    def test_sdk_deny_rules_kept(self):
        sdk = {"sandbox": {"enabled": True, "filesystem": {"denyWrite": ["/sdk/path"]}},
               "permissions": {"deny": ["Bash(rm:*)"]}}
        r = self.e.run(sdk_argv("works-node: fix", settings=json.dumps(sdk)))
        self.assertEqual(r.returncode, 0, r.stderr)
        s = self.settings()
        self.assertEqual(s["permissions"]["deny"][0], "Bash(rm:*)")
        self.assertEqual(s["sandbox"]["filesystem"]["denyWrite"][0], "/sdk/path")
        self.assertEqual(s["sandbox"]["enabled"], True)

    def test_no_sandbox_block_gets_permissions_only(self):
        r = self.e.run(sdk_argv("works-node: fix", settings=None))
        self.assertEqual(r.returncode, 0, r.stderr)
        s = self.settings()
        self.assertNotIn("sandbox", s)   # sandbox の無い節に sandbox の鍵を作らない
        self.assertIn(f"Edit(/{self.board}/**)", s["permissions"]["deny"])
        self.assertEqual(self.e.launches()[-1]["fence"]["deny_write"], 0)

    def test_no_ticket_no_fence(self):
        adapter.ticket_path(self.e.cwd, self.e.home).unlink()
        r = self.e.run(sdk_argv("works-node: fix"))
        self.assertEqual(r.returncode, 0, r.stderr)
        s = self.settings()
        self.assertNotIn("permissions", s)
        self.assertNotIn("filesystem", s["sandbox"])
        self.assertEqual(self.e.launches()[-1]["fence"], {"deny_write": 0, "permissions_deny": 0})

    def test_unreadable_ticket_fails_closed(self):
        # 切符のファイルが在るのに読めない時、印のある起動は柵なしで起こさない（M1）
        t = adapter.ticket_path(self.e.cwd, self.e.home)
        for body in ('{"protected": ["relative/path"]}', "{not json", '{"protected": "x"}', "[]"):
            with self.subTest(body):
                t.write_text(body, encoding="utf-8")
                r = self.e.run(sdk_argv("works-node: fix"))
                self.assertEqual(r.returncode, 3, r.stderr)
                self.assertEqual(len(r.stderr.splitlines()), 1, r.stderr)
                self.assertIn("切符", r.stderr)
                self.assertIsNone(self.e.child())
        # 印の無い起動は切符に依らずそのまま
        argv = sdk_argv(None)
        r = self.e.run(argv)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.e.child()["argv"], argv)

    def test_no_tree_write_denies_own_worktree(self):
        """旗 no-tree-write（CI の任せ先の役。sandbox は allowWrite ['/']）: 役の cwd の worktree の根を全部の綴りで
        denyWrite と permissions.deny に足す。切符の protected もそのまま（裁定 R56）"""
        r = self.e.run(sdk_argv("works-node: ci no-tree-write"))
        self.assertEqual(r.returncode, 0, r.stderr)
        s = self.settings()
        deny, dw = s["permissions"]["deny"], s["sandbox"]["filesystem"]["denyWrite"]
        def spelled(p):
            self.assertIn(p, dw)
            for tool in ("Edit", "Write"):
                self.assertIn(f"{tool}(/{p})", deny)
                self.assertIn(f"{tool}(/{p}/**)", deny)
        spelled(str(self.e.cwd))
        with self.subTest("/private の別名の綴り"):
            spelled(hermetic.alias(self, self.e.cwd))
        self.assertIn(str(self.board), dw)
        self.assertEqual(self.e.launches()[-1]["fence"]["no_tree_write"], str(self.e.cwd))
        # 旗の無い起動は役の cwd を守らない（書く役はそこに書く）
        self.e.run(sdk_argv("works-node: fix"))
        self.assertNotIn(str(self.e.cwd), self.settings()["sandbox"]["filesystem"]["denyWrite"])

    def test_no_tree_write_without_sandbox_refused(self):
        """SDK が sandbox の塊を渡さない・enabled でない・allowUnsandboxedCommands が false でない・failIfUnavailable が true でない
        起動は起こさない: 役の書く道は Bash だけで、守りは sandbox の denyWrite だけ"""
        for settings in (None, '{"permissions": {"deny": []}}', '{"sandbox": {"enabled": false}}',
                         # sandbox の外で Bash を走らせる道・sandbox が立たない場で素通しになる道が開いている（再審査 N2）
                         '{"sandbox": {"enabled": true, "allowUnsandboxedCommands": true, "failIfUnavailable": true}}',
                         '{"sandbox": {"enabled": true, "allowUnsandboxedCommands": false, "failIfUnavailable": false}}',
                         '{"sandbox": {"enabled": true, "failIfUnavailable": true}}',
                         '{"sandbox": {"enabled": true, "allowUnsandboxedCommands": false}}'):
            with self.subTest(settings):
                r = self.e.run(sdk_argv("works-node: ci no-tree-write", settings=settings))
                self.assertEqual(r.returncode, 3, r.stderr)
                self.assertEqual(len(r.stderr.splitlines()), 1, r.stderr)
                self.assertIn("sandbox", r.stderr)
                self.assertIsNone(self.e.child())
                self.assertEqual(self.e.launches()[-1]["mode"], "refused")

    def test_no_tree_write_without_ticket_refused(self):
        """切符が無い起動も起こさない: allowWrite ['/'] の下で盤面・pack・git の設定を守るのは切符だけ"""
        adapter.ticket_path(self.e.cwd, self.e.home).unlink()
        r = self.e.run(sdk_argv("works-node: ci no-tree-write"))
        self.assertEqual(r.returncode, 3, r.stderr)
        self.assertIn("切符", r.stderr)
        self.assertIsNone(self.e.child())
        # 旗の無い起動は今までどおり柵なしで起こす
        r = self.e.run(sdk_argv("works-node: fix"))
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_no_tree_write_outside_git_refused(self):
        """役の cwd の worktree の根が git から引けなければ、守る場所が決まらないので起こさない"""
        loose = self.e.tmp / "loose"
        loose.mkdir()
        t = adapter.ticket_path(loose, self.e.home)
        t.write_text(json.dumps({"protected": [str(self.board)]}), encoding="utf-8")
        r = self.e.run(sdk_argv("works-node: ci no-tree-write"), cwd=loose, GIT_CEILING_DIRECTORIES=str(self.e.tmp))
        self.assertEqual(r.returncode, 3, r.stderr)
        self.assertIn("worktree", r.stderr)
        self.assertIsNone(self.e.child())

    def test_unmarked_launch_gets_no_fence(self):
        argv = sdk_argv(None)
        r = self.e.run(argv)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.e.child()["argv"], argv)

    def test_continue_launch_also_fenced(self):
        self.e.run(sdk_argv("works-node: judge"))
        r = self.e.run(sdk_argv("works-node: rejudge continue=judge"))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn(f"Write(/{self.board}/**)", self.settings()["permissions"]["deny"])


def net_settings(network, **sandbox):
    """sandbox の塊に network を持つ --settings の本文（Archon の YAML の sandbox を SDK がそのまま渡す形）"""
    sb = {"enabled": True, "allowUnsandboxedCommands": False, "failIfUnavailable": True, **sandbox}
    if network is not None:
        sb["network"] = network
    return json.dumps({"sandbox": sb})


class NetworkCase(unittest.TestCase):
    """網の閉じ（option A）。Archon は役を bypassPermissions で起こし、網の型から strictAllowlist を捨てる。bypassPermissions の
    下の Claude Code 2.1.283 は、allowedDomains に無い宛先への通信の問い合わせを自動で通す（strictAllowlist: true の時だけ拒む）。
    そこで包みが、網の許可の一覧が `*` でない sandbox の起動に sandbox.network.strictAllowlist: true を足す（印の有無に依らない）。
    `*` の網（任せ先）は触らない。--settings が読めない・書き換えられない起動は起こさない（fail closed）"""

    def setUp(self):
        self.e = Env(self)

    def net(self, argv):
        vals = opt(argv, "--settings")
        self.assertEqual(len(vals), 1, argv)
        return json.loads(vals[0])["sandbox"].get("network")

    def test_closed_network_gets_strict_allowlist(self):
        for allowed in ([], ["github.com", "api.github.com"], ["*.example.com"]):
            for desc in ("", "works-node: judge", "works-node: probe no-post"):
                with self.subTest(allowed=allowed, desc=desc):
                    network = {"allowedDomains": allowed, "allowLocalBinding": False}
                    r = self.e.run(sdk_argv(desc, settings=net_settings(network, excludedCommands=["works-gh:*"])))
                    self.assertEqual(r.returncode, 0, r.stderr)
                    got = self.e.child()["argv"]
                    self.assertEqual(self.net(got), dict(network, strictAllowlist=True))
                    sb = json.loads(opt(got, "--settings")[0])["sandbox"]
                    self.assertEqual(sb["excludedCommands"], ["works-gh:*"])   # ほかの鍵はそのまま
                    self.assertIs(self.e.launches()[-1]["strict_net"], True)

    def test_strict_false_is_forced_true(self):
        r = self.e.run(sdk_argv("", settings=net_settings({"allowedDomains": [], "strictAllowlist": False})))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIs(self.net(self.e.child()["argv"])["strictAllowlist"], True)

    def test_joined_and_file_spellings(self):
        text = net_settings({"allowedDomains": []})
        f = self.e.tmp / "sdk-settings.json"
        f.write_text(text, encoding="utf-8")
        base = sdk_argv("", settings=None)
        for tail, joined in ((["--settings=" + text], True), (["--settings", str(f)], False)):
            with self.subTest(joined=joined):
                r = self.e.run(base + tail)
                self.assertEqual(r.returncode, 0, r.stderr)
                got = self.e.child()["argv"]
                self.assertEqual(got[:len(base)], base)
                self.assertEqual(any(a.startswith("--settings=") for a in got), joined)
                self.assertIs(self.net(got)["strictAllowlist"], True)

    def test_wildcard_network_untouched(self):
        # 任せ先（blk-ci・素材集めの任せ先 4 本）は網 `*`。印の無い起動は 1 バイトも変えない
        for network in ({"allowedDomains": ["*"], "allowLocalBinding": True}, {"allowedDomains": ["github.com", "*"]}):
            with self.subTest(network=network):
                argv = sdk_argv("", settings=net_settings(network, enableWeakerNetworkIsolation=True))
                r = self.e.run(argv)
                self.assertEqual(r.returncode, 0, r.stderr)
                self.assertEqual(self.e.child()["argv"], argv)
                self.assertIs(self.e.launches()[-1]["strict_net"], False)
                r = self.e.run(sdk_argv("works-node: ci", settings=net_settings(network)))
                self.assertEqual(r.returncode, 0, r.stderr)
                self.assertEqual(self.net(self.e.child()["argv"]), network)

    def test_no_network_list_untouched(self):
        # 網の許可の一覧を持たない sandbox（読むだけの役・修正役）と sandbox の無い起動は網の鍵を作らない
        for settings in (SANDBOX, net_settings({"allowLocalBinding": True}), '{"permissions": {"deny": []}}'):
            with self.subTest(settings=settings):
                argv = sdk_argv("", settings=settings)
                r = self.e.run(argv)
                self.assertEqual(r.returncode, 0, r.stderr)
                self.assertEqual(self.e.child()["argv"], argv)
                self.assertIsNone(self.e.launches()[-1]["strict_net"])

    def test_unparseable_settings_refused_even_unmarked(self):
        # 網を閉じられるかが決まらない起動は、印が無くても起こさない（黙って網を開けたまま起こさない）
        broken = [
            sdk_argv("", extra=["--settings", SANDBOX]),                                   # --settings が 2 つ
            sdk_argv("", settings="{not json"),                                            # 読めない JSON
            sdk_argv("", settings="/no/such/settings.json"),                               # 無いファイル
            sdk_argv("", settings="[1, 2]"),                                               # 辞書でない
            sdk_argv("", settings='{"sandbox": 1}'),                                       # sandbox が object でない
            sdk_argv("", settings='{"sandbox": {"network": []}}'),                         # network が object でない
            sdk_argv("", settings='{"sandbox": {"network": {"allowedDomains": "x"}}}'),   # 一覧が配列でない
            sdk_argv("", settings='{"sandbox": {"network": {"allowedDomains": [1]}}}'),   # 一覧に文字列でない物
            sdk_argv("", settings=None) + ["--settings"],                                  # 値の無い旗
            sdk_argv(None) + ["--settings", "{not json"],                                  # 題の生成の形でも
        ]
        for argv in broken:
            with self.subTest(argv=argv[-2:]):
                r = self.e.run(argv)
                self.assertEqual(r.returncode, 3, r.stderr)
                lines = r.stderr.splitlines()
                self.assertEqual(len(lines), 1, r.stderr)
                self.assertIn("起こさない", lines[0])
                self.assertIn("網", lines[0])
                self.assertIsNone(self.e.child())
                self.assertEqual(self.e.launches()[-1]["mode"], "refused")

    def test_marked_launch_strict_and_fences_together(self):
        # 印のある起動: 網の閉じとフック・no-post の柵が同じ --settings に乗る
        r = self.e.run(sdk_argv("works-node: probe no-post", settings=net_settings({"allowedDomains": []})))
        self.assertEqual(r.returncode, 0, r.stderr)
        s = json.loads(opt(self.e.child()["argv"], "--settings")[0])
        self.assertIs(s["sandbox"]["network"]["strictAllowlist"], True)
        self.assertIn("Bash(gh:*)", s["permissions"]["deny"])
        self.assertTrue(s["hooks"]["PostToolUse"])
        self.assertEqual(self.e.launches()[-1]["mode"], "merged")


class IsolatedCase(unittest.TestCase):
    """旗 isolated: 道具ゼロの役を Git の外の置き場で起こす（graphloops の commands._isolated_cwd と同じ。子の cwd が Git の
    リポジトリの外なら、claude は git status の写しを system prompt に入れない。公式: 'Absent outside a Git repository'）"""

    def setUp(self):
        self.e = Env(self)
        git(self.e.cwd, "init", "-q")   # run の worktree（Git の中）

    def test_isolated_child_runs_outside_git(self):
        r = self.e.run(sdk_argv("works-node: r2-design isolated", tools=""))
        self.assertEqual(r.returncode, 0, r.stderr)
        child = self.e.child()
        want = pathlib.Path(tempfile.gettempdir()).resolve() / f"works-isolated-{adapter.cwd_key(self.e.cwd)}"
        self.assertEqual(pathlib.Path(child["cwd"]).resolve(), want)
        self.assertNotEqual(pathlib.Path(child["cwd"]).resolve(), self.e.cwd.resolve())
        inside = subprocess.run(["git", "-C", child["cwd"], "rev-parse", "--is-inside-work-tree"], capture_output=True,
                                text=True, encoding="utf-8")
        self.assertNotEqual(inside.stdout.strip(), "true", "置き場が Git の中")
        # 会話の id と起動の記録は run の worktree（Archon の cwd）の鍵のまま（出し直しの --resume は同じ置き場で起きる）
        self.assertIsNotNone(self.e.session_id("r2-design"))
        row = self.e.launches()[-1]
        self.assertEqual(row["fence"]["isolated"], str(want))
        # 2 回目も同じ置き場（claude の会話の置き場は cwd ごと。--resume が同じ会話を引ける）
        self.e.run(sdk_argv("works-node: r2-design isolated", tools=""))
        self.assertEqual(pathlib.Path(self.e.child()["cwd"]).resolve(), want)

    def test_isolated_with_tools_refused(self):
        r = self.e.run(sdk_argv("works-node: r2-design isolated", tools="Read"))
        self.assertEqual(r.returncode, 3, r.stderr)
        self.assertIsNone(self.e.child(), "道具を持つ役を Git の外で起こさない（道具ゼロの役だけの旗）")
        self.assertIn("isolated", r.stderr)

    def test_isolated_place_inside_git_refused(self):
        repo = self.e.tmp / "tmp-in-git"
        repo.mkdir()
        git(repo, "init", "-q")
        r = self.e.run(sdk_argv("works-node: r2-design isolated", tools=""), TMPDIR=str(repo))
        self.assertEqual(r.returncode, 3, r.stderr)
        self.assertIsNone(self.e.child())

    def test_unflagged_role_keeps_cwd(self):
        self.e.run(sdk_argv("works-node: r3-coherence", tools="Read,Grep,Glob"))
        self.assertEqual(pathlib.Path(self.e.child()["cwd"]).resolve(), self.e.cwd.resolve())


class McpCase(unittest.TestCase):
    """10. 借りる MCP（Context7）: Archon の役の節は周りの MCP を読まない（--strict-mcp-config）。隔離した設定の置き場の
    works-mcp.json（dev/toolset.py が使用許諾を確かめて書く）を、web を持つ（--tools に WebFetch が在る）印のある起動にだけ
    --mcp-config で渡す。道具ゼロ・web を持たない役・SDK が自分の --mcp-config を渡した起動・印の無い起動には渡さない。
    渡すのは env の WORKS_CONTEXT7_MCP=on の時だけ（既定は渡さない。役の書く問いが対象のコードの字を外へ運びうる。controller の裁定）"""

    WEB = "Read,Grep,Glob,WebSearch,WebFetch"

    def setUp(self):
        self.e = Env(self)
        self.cfg = self.e.tmp / "claude-config"
        self.cfg.mkdir()
        self.file = self.cfg / adapter.MCP_FILE
        self.file.write_text(json.dumps({"mcpServers": {"context7": {"type": "http", "url": "https://mcp.context7.com/mcp"}}}),
                             encoding="utf-8")

    def run_(self, desc, tools, extra=(), switch="on"):
        r = self.e.run(sdk_argv(desc, tools=tools, extra=extra), CLAUDE_CONFIG_DIR=str(self.cfg), WORKS_CONTEXT7_MCP=switch)
        self.assertEqual(r.returncode, 0, r.stderr)
        return self.e.child()["argv"]

    def test_web_role_gets_the_mcp_file(self):
        argv = self.run_("works-node: judge", self.WEB)
        self.assertEqual(opt(argv, "--mcp-config"), [str(self.file)])
        self.assertIn("--strict-mcp-config", argv)
        self.assertEqual(self.e.launches()[-1]["fence"]["mcp"], {"file": str(self.file), "servers": ["context7"]})

    def test_off_by_default(self):
        for switch in (None, "", "off", "1", "yes"):
            with self.subTest(switch=switch):
                argv = self.run_("works-node: judge", self.WEB, switch=switch)
                self.assertEqual(opt(argv, "--mcp-config"), [])
                self.assertIn("WORKS_CONTEXT7_MCP=on", self.e.launches()[-1]["fence"]["mcp"]["skipped"])

    def test_roles_without_web_do_not(self):
        for desc, tools in (("works-node: review", "Read,Grep,Glob"), ("works-node: r2-design isolated", "")):
            with self.subTest(desc):
                if "isolated" in desc:
                    git(self.e.cwd, "init", "-q")
                argv = self.run_(desc, tools)
                self.assertEqual(opt(argv, "--mcp-config"), [])
                self.assertIn("web を持たない", self.e.launches()[-1]["fence"]["mcp"]["skipped"])

    def test_sdk_mcp_config_is_left_alone(self):
        argv = self.run_("works-node: judge", self.WEB, extra=("--mcp-config", '{"mcpServers":{"archon":{}}}'))
        self.assertEqual(opt(argv, "--mcp-config"), ['{"mcpServers":{"archon":{}}}'])
        self.assertIn("--mcp-config", self.e.launches()[-1]["fence"]["mcp"]["skipped"])

    def test_no_file_no_change(self):
        self.file.unlink()
        argv = self.run_("works-node: judge", self.WEB)
        self.assertEqual(opt(argv, "--mcp-config"), [])
        self.assertNotIn("mcp", self.e.launches()[-1]["fence"])

    def test_unreadable_file_is_declared_not_passed(self):
        self.file.write_text("[]", encoding="utf-8")
        argv = self.run_("works-node: judge", self.WEB)
        self.assertEqual(opt(argv, "--mcp-config"), [])
        self.assertIn("読めない", self.e.launches()[-1]["fence"]["mcp"]["skipped"])

    def test_unmarked_launch_untouched(self):
        argv = self.run_(None, self.WEB)
        self.assertEqual(opt(argv, "--mcp-config"), [])


class FencedLaunchCase(unittest.TestCase):
    """節の起動が包みを通り、柵 no_tree_write（役の cwd の worktree の根）が掛かったか（fenced_launch。起動の記録から）"""

    def setUp(self):
        self.e = Env(self)
        git(self.e.cwd, "init", "-q")
        self.top = os.path.realpath(self.e.cwd)
        self.since = adapter.now()

    def row(self, **over):
        r = {"at": adapter.now(), "node": "ci", "mode": "merged", "fence": {"no_tree_write": self.top}}
        r.update(over)
        p = adapter.launches_path(self.e.cwd, self.e.home)
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "a", encoding="utf-8") as f:
            f.write(json.dumps(r) + "\n")

    def why(self):
        return adapter.fenced_launch(self.e.cwd, "ci", self.since, self.e.home)

    def test_fenced_launch_ok(self):
        self.row(at="2000-01-01T00:00:00.000000+00:00", fence={})   # 試行より前の起動は見ない
        self.row(mode="refused", fence=None)                         # 起こさなかった起動は害が無い
        self.row()
        self.assertIsNone(self.why())

    def test_missing_launch(self):
        self.assertIn("起動が無い", self.why())
        self.row(node="judge")
        self.assertIn("起動が無い", self.why())

    def test_unfenced_or_wrong_root(self):
        for bad in ({"fence": {"deny_write": 3}}, {"fence": {"no_tree_write": "/elsewhere"}}, {"mode": "passthrough"}):
            with self.subTest(bad):
                p = adapter.launches_path(self.e.cwd, self.e.home)
                if p.exists():
                    p.unlink()
                self.row()
                self.row(**bad)
                self.assertIn("柵", self.why())

    def test_only_refused(self):
        self.row(mode="refused", fence=None)
        self.assertIn("起こされていない", self.why())


def user_line(text):
    """SDK 0.3.282 が prompt の文字列を stdin に書く 1 行（sdk.mjs の Gx。initialize の後に来る）"""
    return json.dumps({"type": "user", "session_id": "", "message": {"role": "user", "content": [
        {"type": "text", "text": text}]}, "parent_tool_use_id": None}, ensure_ascii=False) + "\n"


INIT_LINE = json.dumps({"request_id": "r0", "type": "control_request",
                        "request": {"subtype": "initialize", "systemPrompt": []}}) + "\n"
FULL = "# 共有の規則\n規則の本文 1\n\n# 今の回\n全文版の今の回\n"
DELTA = "# 今の回\n差分版の今の回\n"


class PromptVariantCase(unittest.TestCase):
    """全文版と差分版（トークンの節約。持ち主の承認）: 輪の中で同じ会話を継ぐ役に、共有の規則を毎回送り直さない。
    支度のスクリプトが <stem>.full.md・<stem>.delta.md・<stem>.variants.json を書き、指示書（prompt_file）は全文版の写し。
    包みは印のある起動の指示文（stdin の user の 1 行）から指示書のパスを読み、会話がこの規則（rules_sha）の全文版を
    前に受け取って読み切った同じ会話（か、その fork）を継ぐ起動にだけ差分版を書く。疑いがあれば全文版"""

    def setUp(self):
        self.e = Env(self)
        self.board = self.e.tmp / "board" / "work"
        self.board.mkdir(parents=True)
        self.config = self.e.tmp / "claude-config"
        (self.config / "projects" / "-wt").mkdir(parents=True)

    def prep(self, stem="prompt-judge", rules_sha="r1", iteration=1, full=FULL, delta=DELTA, relative=True):
        """支度のスクリプトの代わり: 全文版・差分版・variants.json を書き、指示書に全文版を写す"""
        prompt = self.board / f"{stem}.md"
        (self.board / f"{stem}.full.md").write_text(full, encoding="utf-8")
        (self.board / f"{stem}.delta.md").write_text(delta, encoding="utf-8")
        names = (f"{stem}.full.md", f"{stem}.delta.md") if relative else \
            (str(self.board / f"{stem}.full.md"), str(self.board / f"{stem}.delta.md"))
        (self.board / f"{stem}.variants.json").write_text(json.dumps(
            {"full": names[0], "delta": names[1], "rules_sha": rules_sha, "iteration": iteration,
             "sections": ["rules", "turn"]}), encoding="utf-8")
        prompt.write_text(full, encoding="utf-8")
        return prompt

    def launch(self, desc, prompt, extra=(), text=None, **env):
        argv = sdk_argv(desc, extra=extra)
        stdin = INIT_LINE + user_line(text if text is not None else
                                      f"指示書 `{prompt}` を Read で読み、その指示に従え。返すのは JSON だけ。")
        r = self.e.run(argv, stdin=stdin, FAKE_CLAUDE_READ=str(prompt), CLAUDE_CONFIG_DIR=str(self.config), **env)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.e.child()["stdin"], stdin)   # 中継しても 1 バイトも変えない
        return self.e.child(), self.e.launches()[-1]

    def read_evidence(self, sid, prompt, content=FULL, partial=False, agent=None):
        """Read のフック（record-read.py）が書く 1 行の代わり: 会話 sid が prompt を content の sha で読んだ"""
        sink = adapter.reads_dir(self.e.cwd, self.e.home)
        sink.mkdir(parents=True, exist_ok=True)
        with open(sink / "reads.jsonl", "a", encoding="utf-8") as f:
            f.write(json.dumps({"ts": "x", "session_id": sid, "agent_id": agent, "path": os.path.realpath(prompt),
                                "file_sha": hashlib.sha256(content.encode("utf-8")).hexdigest(),
                                "bytes": len(content.encode("utf-8")), "partial": partial,
                                "partial_why": "range" if partial else None, "tool_use_id": "toolu_x"}) + "\n")

    def transcript(self, sid, text='{"type":"user"}\n'):
        (self.config / "projects" / "-wt" / f"{sid}.jsonl").write_text(text, encoding="utf-8")

    def first(self, desc="works-node: judge", stem="prompt-judge", rules_sha="r1"):
        """1 回目の起動（新しい会話）で全文版を受け取り、読み切った会話の id"""
        prompt = self.prep(stem, rules_sha=rules_sha)
        child, row = self.launch(desc, prompt)
        sid = row["session"]["id"]
        self.read_evidence(sid, prompt)
        self.transcript(sid)
        return prompt, sid

    def expect(self, row, child, prompt, variant, reason, rules_sha="r1"):
        self.assertEqual(row["prompt"]["variant"], variant, row["prompt"])
        self.assertEqual(row["prompt"]["reason"], reason, row["prompt"])
        self.assertEqual(row["prompt"]["rules_sha"], rules_sha)
        self.assertEqual(row["prompt"]["file"], os.path.realpath(prompt))
        want = FULL if variant == "full" else adapter.delta_text(DELTA, self.board / (prompt.stem + ".full.md"))
        self.assertEqual(child["read"], want)                      # 役が起きた時の指示書の中身
        self.assertEqual(prompt.read_text(encoding="utf-8"), want)

    def test_first_launch_gets_full(self):
        prompt = self.prep()
        child, row = self.launch("works-node: judge", prompt)
        self.expect(row, child, prompt, "full", "new-session")
        self.assertEqual(row["prompt"]["iteration"], 1)
        self.assertEqual(row["prompt"]["full_sha"], hashlib.sha256(FULL.encode("utf-8")).hexdigest())

    def test_resume_of_same_session_gets_delta(self):
        # Archon の輪（fresh_context: false）の 2 周目: --resume <前の会話> --fork-session。包みが新しい id を決める
        prompt, sid = self.first()
        self.prep()   # 支度は周ごとに指示書を全文版で書き直す
        child, row = self.launch("works-node: judge", prompt, extra=["--resume", sid, "--fork-session"])
        self.assertEqual((row["session"]["mode"], row["session"]["from"]), ("sdk-fork", sid))
        self.expect(row, child, prompt, "delta", "same-session")
        # 3 周目: 2 周目の fork をさらに継ぐ（全文版を読んだのは 1 周目の会話。fork の鎖で辿る）
        second = row["session"]["id"]
        self.transcript(second)
        self.prep()
        child, row = self.launch("works-node: judge", prompt, extra=["--resume", second, "--fork-session"])
        self.expect(row, child, prompt, "delta", "same-session")
        # SDK が fork せずに同じ会話を再開する形も同じ
        self.prep()
        child, row = self.launch("works-node: judge", prompt, extra=["--resume", sid])
        self.expect(row, child, prompt, "delta", "same-session")

    def test_continue_of_session_with_same_rules_gets_delta(self):
        # 再審（continue=judge）: 判定役の会話がこの規則の全文版を読んでいれば、再審の指示書も差分版でよい
        _, sid = self.first()
        prompt = self.prep("prompt-rejudge")
        child, row = self.launch("works-node: rejudge continue=judge", prompt)
        self.assertEqual(row["session"]["mode"], "continued")
        self.expect(row, child, prompt, "delta", "same-session")

    def test_resume_of_other_session_gets_full(self):
        prompt, sid = self.first()
        self.prep()
        other = "dddddddd-0000-4000-8000-000000000001"
        self.transcript(other)
        child, row = self.launch("works-node: judge", prompt, extra=["--resume", other, "--fork-session"])
        self.expect(row, child, prompt, "full", "no-full-record")

    def test_rules_changed_gets_full(self):
        prompt, sid = self.first()
        self.prep(rules_sha="r2")
        child, row = self.launch("works-node: judge", prompt, extra=["--resume", sid, "--fork-session"])
        self.expect(row, child, prompt, "full", "rules-changed", rules_sha="r2")

    def test_full_not_read_gets_full(self):
        prompt = self.prep()
        _, row = self.launch("works-node: judge", prompt)
        sid = row["session"]["id"]
        self.transcript(sid)
        cases = {"no-read": None, "partial": dict(partial=True), "subagent": dict(agent="a1"),
                 "other-content": dict(content=DELTA), "other-session": dict(sid="eeeeeeee-0000-4000-8000-000000000001")}
        for why, kw in cases.items():
            with self.subTest(why):
                if kw is not None:
                    kw = dict(kw)
                    self.read_evidence(kw.pop("sid", sid), prompt, **kw)
                self.prep()
                child, row = self.launch("works-node: judge", prompt, extra=["--resume", sid, "--fork-session"])
                self.expect(row, child, prompt, "full", "full-not-read")

    def test_record_missing_gets_full(self):
        # 包みの記録が無い会話（前の起動が包みを通っていない・記録が消えた）は、読んだ跡が在っても全文版
        prompt, sid = self.first()
        adapter.launches_path(self.e.cwd, self.e.home).unlink()
        self.prep()
        child, row = self.launch("works-node: judge", prompt, extra=["--resume", sid, "--fork-session"])
        self.expect(row, child, prompt, "full", "no-full-record")

    def test_compacted_or_unseen_transcript_gets_full(self):
        # 会話が要約された・古い道具の結果が消された（Claude Code 2.1.283 の microcompact）・会話の記録が見えない時は全文版
        prompt, sid = self.first()
        marks = {"compacted": '{"type":"system","subtype":"compact_boundary"}\n',
                 "microcompacted": '{"type":"system","subtype":"microcompact_boundary"}\n',
                 "cleared": '{"type":"user","message":{"content":[{"type":"tool_result",'
                            '"content":"[Old tool result content cleared]"}]}}\n'}
        for why, text in marks.items():
            with self.subTest(why):
                self.transcript(sid, text)
                self.prep()
                child, row = self.launch("works-node: judge", prompt, extra=["--resume", sid, "--fork-session"])
                self.expect(row, child, prompt, "full", "compacted")
        (self.config / "projects" / "-wt" / f"{sid}.jsonl").unlink()
        self.prep()
        child, row = self.launch("works-node: judge", prompt, extra=["--resume", sid, "--fork-session"])
        self.expect(row, child, prompt, "full", "transcript-missing")

    def test_retry_after_delta_rewrites_full(self):
        # 差分版を書いた後に、支度を通らずに同じ指示書で新しい会話が起きたら（節の起こし直し）、全文版に戻す
        prompt, sid = self.first()
        self.prep()
        self.launch("works-node: judge", prompt, extra=["--resume", sid, "--fork-session"])
        child, row = self.launch("works-node: judge", prompt)
        self.expect(row, child, prompt, "full", "new-session")

    def test_unmarked_launch_untouched(self):
        prompt, sid = self.first()
        self.prep()
        argv = sdk_argv(None, extra=["--resume", sid])
        stdin = INIT_LINE + user_line(f"指示書 `{prompt}` を Read で読め")
        r = self.e.run(argv, stdin=stdin, FAKE_CLAUDE_READ=str(prompt), CLAUDE_CONFIG_DIR=str(self.config))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.e.child()["stdin"], stdin)
        self.assertEqual(prompt.read_text(encoding="utf-8"), FULL)
        self.assertNotIn("prompt", self.e.launches()[-1])

    def test_no_variants_untouched(self):
        prompt = self.board / "prompt-plain.md"
        prompt.write_text("そのままの指示書\n", encoding="utf-8")
        before = os.stat(prompt)
        child, row = self.launch("works-node: judge", prompt)
        self.assertNotIn("prompt", row)
        self.assertEqual(set(row), {"at", "pid", "cwd", "node", "continue", "mode", "why", "hook", "tools_empty",
                                    "session", "fence", "strict_net", "model", "effort"})
        self.assertEqual(child["read"], "そのままの指示書\n")
        after = os.stat(prompt)
        self.assertEqual((before.st_ino, before.st_mtime_ns), (after.st_ino, after.st_mtime_ns))

    def test_doubtful_shapes_leave_prompt_alone(self):
        """variants.json が読めない・指示書が 2 つ・指示書が全文版とも差分版とも違う: 指示書に触らず、理由だけを残す"""
        prompt, sid = self.first()
        cases = {
            "variants-bad": lambda: (self.board / "prompt-judge.variants.json").write_text("{", encoding="utf-8"),
            "variants-bad-shape": lambda: (self.board / "prompt-judge.variants.json").write_text(
                json.dumps({"full": "prompt-judge.full.md", "delta": "nope.md", "rules_sha": "r1"}), encoding="utf-8"),
            "prompt-unexpected": lambda: prompt.write_text("手で書き換えた指示書\n", encoding="utf-8"),
        }
        for why, spoil in cases.items():
            with self.subTest(why):
                self.prep()
                spoil()
                before = prompt.read_text(encoding="utf-8")
                child, row = self.launch("works-node: judge", prompt, extra=["--resume", sid, "--fork-session"])
                self.assertIsNone(row["prompt"]["variant"], row["prompt"])
                self.assertTrue(row["prompt"]["reason"].startswith(why.split("-shape")[0]), row["prompt"])
                self.assertEqual(prompt.read_text(encoding="utf-8"), before)
        with self.subTest("several"):
            self.prep()
            other = self.prep("prompt-other")
            child, row = self.launch("works-node: judge", prompt, extra=["--resume", sid, "--fork-session"],
                                     text=f"`{prompt}` と `{other}` を読め")
            self.assertEqual((row["prompt"]["variant"], row["prompt"]["reason"]), (None, "several-prompts"))
            self.assertEqual(prompt.read_text(encoding="utf-8"), FULL)

    def test_relay_forwards_bytes_and_handles_first_user_line_only(self):
        seen = []
        src_r, src_w = os.pipe()
        dst_r, dst_w = os.pipe()
        data = (INIT_LINE + "raw non-json\n" + user_line("一つ目") + user_line("二つ目") + "tail-no-newline").encode()
        os.write(src_w, data)
        os.close(src_w)
        adapter.relay(src_r, dst_w, lambda line: seen.append(line) or not line.startswith(b'{"type": "user"'))
        os.close(src_r)
        got = b""
        while True:
            chunk = os.read(dst_r, 65536)
            if not chunk:
                break
            got += chunk
        os.close(dst_r)
        self.assertEqual(got, data)
        self.assertEqual(len(seen), 3)   # initialize・生の行・1 つ目の user（2 つ目の user からは見ない）

    def test_relay_survives_hook_error(self):
        src_r, src_w = os.pipe()
        dst_r, dst_w = os.pipe()
        os.write(src_w, b"a\nb\n")
        os.close(src_w)

        def boom(_line):
            raise RuntimeError("x")
        adapter.relay(src_r, dst_w, boom)
        os.close(src_r)
        self.assertEqual(os.read(dst_r, 100), b"a\nb\n")
        os.close(dst_r)


class DevWiringCase(unittest.TestCase):
    """dev の殻 archon.sh の WORKS_DEV_ADAPTER=1: 隔離した Archon の設定に claudeBinaryPath（包み）を書き、
    本物の claude は WORKS_REAL_CLAUDE で包みに渡し、env の CLAUDE_BIN_PATH（設定より強い）を外す"""

    def _exec(self, **overrides):
        expected = re.search(r'^ARCHON_SHA256="([0-9a-f]{64})"', (DEV / "archon.sh").read_text(), re.M).group(1)
        with tempfile.TemporaryDirectory() as t:
            tmp = pathlib.Path(t).resolve()
            dev_home = tmp / "dev-home"
            (dev_home / "bin").mkdir(parents=True)
            seen = tmp / "seen.json"
            fake_archon = dev_home / "bin" / "archon-darwin-arm64"
            fake_archon.write_text(
                "#!/bin/sh\n"
                "python3 -c 'import json, os, sys; json.dump({k: os.environ.get(k) for k in "
                "(\"CLAUDE_BIN_PATH\", \"WORKS_REAL_CLAUDE\", \"WORKS_ADAPTER_HOME\")}, open(sys.argv[1], \"w\"))' "
                f'"{seen}"\n')
            fake_bin = tmp / "fake-bin"
            fake_bin.mkdir()
            (fake_bin / "shasum").write_text(f'#!/bin/sh\necho "{expected}  $3"\n')
            (fake_bin / "shasum").chmod(0o755)
            # archon.sh は同じ claude で隔離した設定に coldwrite を入れる（dev/toolset.py）ので、plugin の CLI を真似る偽物。
            # 借りる物を取る利用者の設定（隔離の前の CLAUDE_CONFIG_DIR）も偽物
            from test_toolset import make_user_config, write_fake_claude
            write_fake_claude(fake_bin)
            env = {k: v for k, v in hermetic.child_env().items() if not k.startswith("WORKS_")}
            env.update(WORKS_DEV_HOME=str(dev_home), PATH=str(fake_bin) + os.pathsep + env.get("PATH", ""),
                       CLAUDE_CODE_OAUTH_TOKEN="dummy-token-for-test", FAKE_CLAUDE_LOG=str(tmp / "claude-calls.jsonl"),
                       CLAUDE_CONFIG_DIR=str(make_user_config(tmp / "user-claude-config")))
            for k, v in overrides.items():
                if v is None:
                    env.pop(k, None)
                else:
                    env[k] = v.replace("@TMP", str(tmp))
            r = subprocess.run(["sh", str(DEV / "archon.sh"), "workflow", "run", "x"], capture_output=True,
                               text=True, encoding="utf-8", env=env, cwd=str(tmp))
            config = dev_home / "archon-home" / "config.yaml"
            self.assertNotIn("dummy-token-for-test", r.stdout + r.stderr)
            return (r, config.read_text() if config.exists() else None,
                    json.loads(seen.read_text()) if seen.exists() else None, tmp)

    def test_adapter_enabled_by_config(self):
        r, config, seen, tmp = self._exec(WORKS_DEV_ADAPTER="1", CLAUDE_BIN_PATH="@TMP/fake-bin/claude")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn(f"    claudeBinaryPath: {ADAPTER}\n", config)
        self.assertIn(f"    model: {hermetic.dev_model_default()}\n", config)
        self.assertIsNone(seen["CLAUDE_BIN_PATH"])   # env は設定より強いので外す
        self.assertEqual(seen["WORKS_REAL_CLAUDE"], str(tmp / "fake-bin" / "claude"))
        self.assertEqual(seen["WORKS_ADAPTER_HOME"], str(tmp / "dev-home" / "adapter"))

    def test_adapter_finds_real_claude_on_path(self):
        r, config, seen, tmp = self._exec(WORKS_DEV_ADAPTER="1")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(seen["WORKS_REAL_CLAUDE"], str(tmp / "fake-bin" / "claude"))
        # CLAUDE_BIN_PATH が包み自身を差していても、本物の claude は PATH から引く
        r, config, seen, tmp = self._exec(WORKS_DEV_ADAPTER="1", CLAUDE_BIN_PATH=str(ADAPTER))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(seen["WORKS_REAL_CLAUDE"], str(tmp / "fake-bin" / "claude"))

    def test_adapter_off_by_default(self):
        r, config, seen, tmp = self._exec(CLAUDE_BIN_PATH="@TMP/fake-bin/claude")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertNotIn("claudeBinaryPath", config)
        self.assertEqual(seen["CLAUDE_BIN_PATH"], str(tmp / "fake-bin" / "claude"))
        self.assertIsNone(seen["WORKS_REAL_CLAUDE"])

    def test_adapter_home_relative_refused(self):
        r, config, seen, tmp = self._exec(WORKS_DEV_ADAPTER="1", WORKS_ADAPTER_HOME="rel/adapter")
        self.assertEqual(r.returncode, 2)
        self.assertIn("絶対パス", r.stderr)
        self.assertIsNone(seen)

    def test_adapter_home_in_claude_tmp_refused(self):
        r, config, seen, tmp = self._exec(WORKS_DEV_ADAPTER="1", WORKS_ADAPTER_HOME="/private/tmp/claude-0/x")
        self.assertEqual(r.returncode, 2)
        self.assertIn("WORKS_ADAPTER_HOME", r.stderr)
        self.assertIsNone(seen)

    def test_adapter_bad_value_refused(self):
        r, config, seen, tmp = self._exec(WORKS_DEV_ADAPTER="yes")
        self.assertEqual(r.returncode, 2)
        self.assertIn("WORKS_DEV_ADAPTER", r.stderr)
        self.assertIsNone(seen)

    def test_show_run_carries_adapter_switch(self):
        # 承認・続きのコマンドも包みを通す（archon.sh は認証を使う実行のたびに設定を書き直すので、付け忘れると外れる）
        with tempfile.TemporaryDirectory() as t:
            fake = pathlib.Path(t, "archon.sh")
            fake.write_text("#!/bin/sh\necho '{\"runs\": [{\"workflow_name\": \"darkfactory\", \"id\": \"r1\"}]}'\n")
            env = hermetic.child_env(WORKS_DEV_HOME=t, WORKS_DEV_MODEL="opus", CLAUDE_BIN_PATH="/x/claude",
                       WORKS_DEV_ADAPTER="1")
            r = subprocess.run(["sh", "-c", f'. "{DEV}/lib.sh" && works_dev_show_run t "{fake}" "{t}"'],
                               capture_output=True, text=True, encoding="utf-8", env=env)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn("WORKS_DEV_ADAPTER=1 ", r.stdout)
            env.pop("WORKS_DEV_ADAPTER")
            r = subprocess.run(["sh", "-c", f'. "{DEV}/lib.sh" && works_dev_show_run t "{fake}" "{t}"'],
                               capture_output=True, text=True, encoding="utf-8", env=env)
            self.assertNotIn("WORKS_DEV_ADAPTER", r.stdout)


class LaunchRowModelCase(unittest.TestCase):
    def test_launch_row_carries_requested_model_from_argv(self):
        """起動の行の model は Archon が渡した --model（CLI と同じく後の指定が勝つ。無ければ None）。argv は読むだけ"""
        for argv, want in ((["-p", "--model", "sonnet", "--output-format", "json"], "sonnet"),
                           (["-p", "--model=opus"], "opus"),
                           (["-p", "--model", "haiku", "--model=opus"], "opus"),
                           (["-p", "--output-format", "json"], None)):
            with self.subTest(argv=argv):
                p = adapter.Plan(argv=list(argv), mode="merged", why=None, warn=False, node="judge", cont=None,
                                 hook=True, tools_empty=False, session={"mode": "new", "id": "s-1"}, record=[])
                row = adapter.launch_row(p, "/", 1, "2026-09-29T00:00:00+00:00")
                self.assertIn("model", row)
                self.assertEqual(row["model"], want)
                self.assertEqual(p.argv, list(argv))


if __name__ == "__main__":
    unittest.main()
