"""守りのファイルの一覧（works/.shared/core/protected.json）と、その確かめ（works/.shared/core/protect.py）の検査。

ASF の .factory/locks/floor.json に倣う: 工場（darkfactory の自分食い）は自分の試験・柵・受け付けの口を緩めない。一覧に当たる
ファイルを run が触ったら、最後の人の関所を必ず開いて頭に並べる（関所そのものは test_edge の ProtectedGateCase）。
- 一覧の行はどれも、このリポジトリで追跡しているファイルに 1 本以上当たる（当たらない行は古い行で赤。KNOWN の表と同じ扱い）
- 一覧の読み（match）は git の :(glob) と同じ当たり方をする（行ごとに git ls-files と突き合わせる）
- 一覧そのもの・確かめの模块・この試験は一覧に入っている
- 形の崩れた一覧（id の重なり・理由の無い行・絶対パス・.. ・空）は読み込みで拒む
- 差分の確かめ（touched）は数える版からの変更・消した物・未追跡を拾い、行数と当たった行を返す。触っていなければ空
"""
import hashlib
import json
import pathlib
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

TESTS = pathlib.Path(__file__).resolve().parent
ROOT = TESTS.parent                 # works/
REPO = ROOT.parent                  # リポジトリの根（一覧のパスはここからの相対）
CORE = ROOT / ".shared" / "core"
sys.dont_write_bytecode = True
sys.path.insert(0, str(CORE))
sys.path.insert(0, str(TESTS))

import protect  # noqa: E402
from gitkit import committed_copy, git  # noqa: E402

SEED = ROOT / "dev" / "target-seed"


def tracked() -> list:
    out = subprocess.run(["git", "-C", str(REPO), "-c", "core.quotePath=false", "ls-files", "-z"], capture_output=True,
                         check=True).stdout.decode("utf-8")
    return [x for x in out.split("\0") if x]


def git_glob(pattern: str) -> set:
    out = subprocess.run(["git", "-C", str(REPO), "-c", "core.quotePath=false", "ls-files", "-z", "--", f":(top,glob){pattern}"],
                         capture_output=True, check=True).stdout.decode("utf-8")
    return {x for x in out.split("\0") if x}


class ManifestCase(unittest.TestCase):
    def setUp(self):
        self.doc = protect.load()
        self.files = tracked()

    def rel(self, p: pathlib.Path) -> str:
        return p.resolve().relative_to(REPO).as_posix()

    def test_every_rule_matches_a_tracked_file(self):
        """古い行（どの追跡ファイルにも当たらない）は赤。ファイルを動かした・消した時は一覧も直す"""
        stale = [r["id"] for r in self.doc["rules"] if not any(protect.match(f, r["glob"]) for f in self.files)]
        self.assertEqual(stale, [], "一覧の行がどの追跡ファイルにも当たらない（古い行）。行を直すか消す")

    def test_match_agrees_with_git_glob(self):
        """一覧の読みは git の :(glob) と同じ（** は 0 個以上のフォルダ・* と ? は / を跨がない）。フォルダの名前だけの行
        （git は中身に当てる）はここで食い違って赤になる——フォルダは /** で書く"""
        for r in self.doc["rules"]:
            with self.subTest(rule=r["id"]):
                mine = {f for f in self.files if protect.match(f, r["glob"])}
                self.assertEqual(mine, git_glob(r["glob"]))

    def test_manifest_and_checker_are_protected(self):
        for p in (protect.MANIFEST, CORE / "protect.py", pathlib.Path(__file__)):
            with self.subTest(path=p.name):
                self.assertTrue(protect.hits([self.rel(p)], self.doc), f"{self.rel(p)} が一覧に当たらない")

    def test_named_guards_are_protected(self):
        """持ち主が名指した守り（受け付け・入口の take・ブロックの受け付け・柵・包み・道具の柵・層の試験・YAML の決まりの試験・
        最後の関所）が一覧に当たる"""
        for rel in ("works/.shared/core/accept.py", "works/.shared/core/entry.py", "works/blk-fix/scripts/accept.py",
                    "works/blk-refix/scripts/accept_refix.py", "works/.shared/core/adapter.py", "works/.shared/core/ticket.py",
                    "works/dev/toolset.py", "works/tests/test_layers.py", "works/tests/test_yaml_rules.py",
                    "works/tests/tiers.py", "works/darkfactory/lib/line_edge.py", "works/darkfactory/darkfactory.yaml"):
            with self.subTest(rel=rel):
                self.assertIn(rel, self.files)
                self.assertTrue(protect.hits([rel], self.doc))

    def test_ordinary_files_are_not_protected(self):
        for rel in ("works/README.md", "works/blk-fix/commands/fix.md", "works/tests/test_blk_plan.py"):
            with self.subTest(rel=rel):
                self.assertEqual(protect.hits([rel], self.doc), [])

    def test_copies_are_made_where_named(self):
        """run の作業ツリーの中の pack の写し（自分食いの .archon/workflows/works）は、このリポジトリでは追跡していないので、
        写しを作る殻（made_by）が今もその置き場の字を書いていることで古くないと見る"""
        self.assertTrue(self.doc["copies"])
        for r in self.doc["copies"]:
            with self.subTest(rule=r["id"]):
                self.assertTrue(r["glob"].endswith("/**"))
                body = (REPO / r["made_by"]).read_text(encoding="utf-8")
                self.assertIn(r["glob"][:-len("/**")], body)
                self.assertTrue(protect.hits([r["glob"][:-len("**")] + "darkfactory/lib/line_edge.py"], self.doc))


class ShapeCase(unittest.TestCase):
    def load(self, doc):
        with tempfile.TemporaryDirectory() as tmp:
            p = pathlib.Path(tmp) / "m.json"
            p.write_text(json.dumps(doc) if not isinstance(doc, str) else doc, encoding="utf-8")
            return protect.load(p)

    def test_bad_shapes_refused(self):
        good = {"id": "a", "glob": "a/*.py", "why": "理由"}
        for name, doc in (("json でない", "{"), ("rules が無い", {"copies": []}), ("rules が空", {"rules": []}),
                          ("id の重なり", {"rules": [good, {**good, "glob": "b.py"}]}),
                          ("glob の重なり", {"rules": [good, {**good, "id": "b"}]}),
                          ("理由が無い", {"rules": [{**good, "why": ""}]}),
                          ("絶対パス", {"rules": [{**good, "glob": "/etc/x"}]}),
                          ("..", {"rules": [{**good, "glob": "a/../b.py"}]}),
                          ("末尾の /", {"rules": [{**good, "glob": "a/"}]}),
                          ("知らない鍵", {"rules": [{**good, "x": 1}]}),
                          ("copies の made_by が無い", {"rules": [good], "copies": [{"id": "c", "glob": "c/**", "why": "理由"}]})):
            with self.subTest(name):
                with self.assertRaises(protect.Broken):
                    self.load(doc)

    def test_good_shape_loads(self):
        doc = self.load({"rules": [{"id": "a", "glob": "a/*.py", "why": "理由"}]})
        self.assertEqual([r["id"] for r in protect.rules(doc)], ["a"])


class MatchCase(unittest.TestCase):
    def test_glob_words(self):
        for pattern, path, want in (("a/*.py", "a/x.py", True), ("a/*.py", "a/b/x.py", False),
                                    ("a/**", "a/b/c.py", True), ("a/**/c.py", "a/c.py", True), ("a/**/c.py", "a/b/d/c.py", True),
                                    ("blk-*/scripts/accept*.py", "blk-fix/scripts/accept_refix.py", True),
                                    ("blk-*/scripts/accept*.py", "blk-fix/scripts/x/accept.py", False),
                                    ("a/?.py", "a/xy.py", False), ("a/[xy].py", "a/y.py", True), ("a.py", "b/a.py", False),
                                    ("a+b(1).py", "a+b(1).py", True)):
            with self.subTest(pattern=pattern, path=path):
                self.assertEqual(protect.match(path, pattern), want)


class TouchedCase(unittest.TestCase):
    """種の git で: 数える版からの変更・消した物・未追跡・commit した物を拾い、行数と当たった行を返す"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.repo = pathlib.Path(self._tmp.name) / "repo"
        self.rev = committed_copy(self.repo, SEED)
        self.doc = {"rules": [{"id": "stats", "glob": "stats.py", "why": "種の芯"},
                              {"id": "tests", "glob": "test_*.py", "why": "種の試験"},
                              {"id": "new", "glob": "guards/**", "why": "新しい柵"}], "copies": []}

    def tearDown(self):
        self._tmp.cleanup()

    def test_untouched_is_empty(self):
        self.assertEqual(protect.touched(self.repo, self.rev, self.doc), [])
        (self.repo / "other.txt").write_text("x\n", encoding="utf-8")
        self.assertEqual(protect.touched(self.repo, self.rev, self.doc), [])

    def test_changed_deleted_untracked_committed(self):
        src = (self.repo / "stats.py").read_text(encoding="utf-8")
        (self.repo / "stats.py").write_text(src + "# a\n# b\n", encoding="utf-8")
        (self.repo / "test_stats.py").unlink()
        (self.repo / "guards").mkdir()
        (self.repo / "guards" / "日本語.py").write_text("x = 1\ny = 2\nz = 3\n", encoding="utf-8")
        rows = protect.touched(self.repo, self.rev, self.doc)
        got = {r["path"]: (r["id"], r["added"], r["deleted"]) for r in rows}
        n_test = len((SEED / "test_stats.py").read_text(encoding="utf-8").splitlines())
        self.assertEqual(got, {"stats.py": ("stats", 2, 0), "test_stats.py": ("tests", 0, n_test),
                               "guards/日本語.py": ("new", 3, 0)})
        self.assertEqual([r["path"] for r in rows], sorted(got))
        self.assertTrue(all(r["why"] and r["glob"] for r in rows))
        # commit して HEAD を動かしても、数える版からの差分として残る
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-q", "-m", "hide")
        again = {r["path"]: (r["id"], r["added"], r["deleted"]) for r in protect.touched(self.repo, self.rev, self.doc)}
        self.assertEqual(again, got)

    def test_lines_name_file_stat_and_rule(self):
        (self.repo / "stats.py").write_text("x\n", encoding="utf-8")
        rows = protect.touched(self.repo, self.rev, self.doc)
        line = protect.lines(rows)[0]
        for want in ("stats.py", "+1", "−", "stats", "種の芯"):
            self.assertIn(want, line)

    def test_default_manifest_used(self):
        """doc を渡さなければ MANIFEST を読む（試験は MANIFEST を差し替えて見る）"""
        with tempfile.TemporaryDirectory() as tmp:
            p = pathlib.Path(tmp) / "m.json"
            p.write_text(json.dumps({"rules": [{"id": "stats", "glob": "stats.py", "why": "種の芯"}]}), encoding="utf-8")
            (self.repo / "stats.py").write_text("x\n", encoding="utf-8")
            with mock.patch.object(protect, "MANIFEST", p):
                self.assertEqual([r["id"] for r in protect.touched(self.repo, self.rev)], ["stats"])


QUERY_RULE_FIRST = "検索語に対象の名前を載せるな"            # 塊の頭の行（judge.md の 16 行目）に在る字
QUERY_RULE_LAST = "対象を既に預かっている所への問い合わせ"   # 塊の終わりの行（judge.md の 22 行目。6 つ目の下位の箇条）


def query_rule_block() -> str:
    """写しの agents/judge.md の検索語の規律の塊を、頭の行と終わりの行の字で縛って取る（adapter.query_rule の切り出しの
    手続きを写さない——同じ手続きで作った期待値は、切り出しの範囲の誤りを捉えない）"""
    lines = (CORE / "agents" / "judge.md").read_text(encoding="utf-8").splitlines()
    start = next(i for i, ln in enumerate(lines) if QUERY_RULE_FIRST in ln)
    last = next(i for i, ln in enumerate(lines) if QUERY_RULE_LAST in ln)
    assert last - start == 6, (start, last)   # 頭の行と下位の箇条 6 つ（judge.md の 16〜22 行）
    return "\n".join(lines[start:last + 1])


class QueryRuleCase(unittest.TestCase):
    """検索語の規律: 包み（adapter.plan）が印のある道具を持つ起動の system prompt に、写しの agents/judge.md の
    『検索語に対象の名前を載せるな』の塊を字のまま重ね書きする（works の役は agents/*.md を読まないので、規律が役に届く道が
    包みの 1 か所しか無い）"""

    WEB = "Read,Grep,Glob,WebSearch,WebFetch"

    def setUp(self):
        import adapter
        self.adapter = adapter
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = pathlib.Path(tmp.name).resolve()
        (self.tmp / "wt").mkdir()
        self.block = query_rule_block()

    def plan(self, extra=()):
        schema = json.dumps({"type": "object", "description": "works-node: judge", "properties": {}})
        argv = ["--output-format", "stream-json", "--json-schema", schema, "--tools", self.WEB,
                "--setting-sources=project,user", *extra]
        return self.adapter.plan(argv, self.tmp / "wt", self.tmp / "home", "true", env={"PATH": "/usr/bin:/bin"})

    @staticmethod
    def values(argv, name):
        return [argv[i + 1] for i, a in enumerate(argv) if a == name and i + 1 < len(argv)] + \
            [a[len(name) + 1:] for a in argv if a.startswith(name + "=")]

    def test_web_role_gets_the_rule_in_system_prompt(self):
        p = self.plan()
        self.assertEqual(p.mode, "merged", p.why)
        vals = self.values(p.argv, "--append-system-prompt")
        self.assertEqual(len(vals), 1, vals)
        self.assertTrue(vals[0].endswith("\n" + self.block), vals[0][-80:])   # 塊の後ろに judge.md の他の行を運ばない

    def test_sdk_append_kept_and_rule_joined(self):
        p = self.plan(["--append-system-prompt", "SDK の本文"])
        self.assertEqual(p.mode, "merged", p.why)
        vals = self.values(p.argv, "--append-system-prompt")
        self.assertEqual(len(vals), 1, "旗を 2 つにしない")
        self.assertTrue(vals[0].startswith("SDK の本文"), vals[0][:40])
        self.assertIn(self.block, vals[0])

    def test_sdk_append_file_refused(self):
        f = self.tmp / "sp.md"
        f.write_text("x", encoding="utf-8")
        p = self.plan(["--append-system-prompt-file", str(f)])
        self.assertEqual(p.mode, "refused")

    def test_fence_records_rule_digest(self):
        p = self.plan()
        want = hashlib.sha256(self.block.encode("utf-8")).hexdigest()[:16]
        self.assertEqual((p.fence or {}).get("query_rule"), want)


if __name__ == "__main__":
    unittest.main()
