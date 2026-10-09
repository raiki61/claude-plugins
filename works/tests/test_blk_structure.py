"""実測の script（blk-structure/scripts/measure.py）の数え方の決定的な試験（設計書 structure-block-design の 3 節・9 節）。

fixture のリポジトリはクラスに 1 回、日時を固定して作る（マージ 1 本・改名 1 本・写し・入口・環境変数・skipped の種）。
窓の始まりは --since 2020-06-01 で、その前の commit は c0 だけ。数はこの fixture で git を直に引いて確かめた値:
- a.txt: side と main の両方で書き換え、マージで第 3 の中身に解く。--follow 2（git の --follow はマージを出さない）・素の値 3・--no-merges 2
- new.txt: c0 で old.txt として 10 行 → c0b で 1 行足す → c1 で改名 → c2 で 5 行足す。--follow 3・素の値 2・--no-merges 2
- 和集合（a.txt と new.txt）: --follow は 1 本ずつの和で 5（c0b を含む）・素の値 5・--no-merges 4
"""
import json
import pathlib
import subprocess
import sys
import tempfile
import unittest

from gitkit import GIT_ID
from hermetic import child_env

ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "blk-structure" / "scripts" / "measure.py"
SINCE = "2020-06-01"

BLOCK = ["alpha = compute(1)", "beta = compute(2)", "gamma = alpha + beta", "delta = gamma * 2",
         "emit(delta)", "close()"]


def _git(repo, *args, date=None, check=True):
    env = child_env()
    if date:
        env.update(GIT_AUTHOR_DATE=date + "T12:00:00+0000", GIT_COMMITTER_DATE=date + "T12:00:00+0000")
    return subprocess.run(["git", *GIT_ID, "-C", str(repo), *args], env=env, capture_output=True, text=True,
                          encoding="utf-8", check=check).stdout.strip()


def _write(repo, rel, text, mode=None):
    p = repo / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    if mode:
        p.chmod(mode)


def build_fixture(repo):
    """日時を固定した fixture のリポジトリを作り、窓の始まりの commit（c0）の版を返す"""
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "symbolic-ref", "HEAD", "refs/heads/main")
    _write(repo, "old.txt", "".join("o%d\n" % i for i in range(1, 11)))
    _write(repo, "a.txt", "base\n")
    _write(repo, "b.txt", "b\n")
    # 写し: dup1 と dup2 は同じ 6 行（空行・空白の揺れだけ違う）、five は 5 行だけ同じ
    _write(repo, "src/dup1.txt", "\n".join(BLOCK) + "\n")
    _write(repo, "src/dup2.txt", "\n".join("   " + ln.replace(" ", "  ") + "\n" for ln in BLOCK[:3]) + "\n\n"
           + "\n".join("\t" + ln for ln in BLOCK[3:]) + "\n")
    _write(repo, "src/five.txt", "\n".join(BLOCK[:5]) + "\nsomething_else()\n")
    # 入口: tool.sh を名指すのは実行できる bin/run と README.md の 2 本
    _write(repo, "tool.sh", "echo tool\n")
    _write(repo, "bin/run", "#!/bin/sh\nexec sh ./tool.sh\n", mode=0o755)
    _write(repo, "README.md", "Run tool.sh to start.\n")
    # 環境変数: AAA_ と BBB_ が 2 つずつ（同数）、CCC_ が 3 つ・DDD_ が 1 つ
    _write(repo, "src/env.sh", 'export AAA_X=1\necho "$AAA_Y"\necho "$BBB_X ${BBB_Y}"\nunset AAA_X\n')
    _write(repo, "src/more.sh", 'echo "$CCC_A $CCC_B $CCC_C $DDD_A"\n')
    _write(repo, "src/note.txt", "see AAA_X\n")
    _write(repo, "tests/t.sh", "echo AAA_X\n")
    _write(repo, "docs/d.md", "AAA_X sets the thing.\n")
    # skipped の種: utf-8 で読めない物と、上限（--max-bytes 100）を超える物
    (repo / "bin.dat").write_bytes(b"\xff\xfe\x00\x81bad\n")
    _write(repo, "big.txt", "x" * 999 + "\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "c0", date="2020-01-01")
    base = _git(repo, "rev-parse", "HEAD")
    with (repo / "old.txt").open("a", encoding="utf-8") as f:
        f.write("o11\n")
    _git(repo, "commit", "-q", "-am", "c0b", date="2020-06-15")
    _git(repo, "mv", "old.txt", "new.txt")
    _git(repo, "commit", "-q", "-m", "c1", date="2020-07-01")
    with (repo / "new.txt").open("a", encoding="utf-8") as f:
        f.write("".join("n%d\n" % i for i in range(1, 6)))
    _git(repo, "commit", "-q", "-am", "c2", date="2020-07-02")
    _git(repo, "checkout", "-q", "-b", "side")
    _write(repo, "a.txt", "side\n")
    _git(repo, "commit", "-q", "-am", "c3", date="2020-07-03")
    _git(repo, "checkout", "-q", "main")
    _write(repo, "a.txt", "main\n")
    _git(repo, "commit", "-q", "-am", "c4", date="2020-07-04")
    _git(repo, "merge", "-q", "--no-ff", "side", "-m", "c5", date="2020-07-05", check=False)   # a.txt でぶつかる
    _write(repo, "a.txt", "merged\n")
    _git(repo, "add", "a.txt")
    _git(repo, "commit", "-q", "--no-edit", date="2020-07-05")
    _write(repo, "loose.txt", "not tracked\n")
    return base


GROW_PATCH = """diff --git a/a.txt b/a.txt
--- a/a.txt
+++ b/a.txt
@@ -1 +1,3 @@
 merged
+x
+y
diff --git a/bin/go b/bin/go
new file mode 100755
--- /dev/null
+++ b/bin/go
@@ -0,0 +1,2 @@
+#!/bin/sh
+exec sh ./tool.sh
diff --git a/src/dup3.txt b/src/dup3.txt
new file mode 100644
--- /dev/null
+++ b/src/dup3.txt
@@ -0,0 +1,6 @@
""" + "".join("+" + ln + "\n" for ln in BLOCK)

BAD_PATCH = """diff --git a/a.txt b/a.txt
--- a/a.txt
+++ b/a.txt
@@ -1 +1,2 @@
 not the current line
+x
"""

PLAIN_PATCH = """--- a/a.txt
+++ b/a.txt
@@ -1 +1,2 @@
 merged
+x
"""


class MeasureCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        cls.repo = pathlib.Path(cls._tmp.name) / "repo"
        cls.base = build_fixture(cls.repo)

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def run_measure(self, *args, cwd=None, since=SINCE):
        env = child_env(PYTHONDONTWRITEBYTECODE="1")
        window = ["--since", since] if since else []
        return subprocess.run([sys.executable, str(SCRIPT), *window, *args], cwd=str(cwd or self.repo), env=env,
                              capture_output=True, text=True, encoding="utf-8", timeout=120)

    def measure(self, *args, cwd=None, since=SINCE):
        r = self.run_measure(*args, cwd=cwd, since=since)
        self.assertEqual(r.returncode, 0, "measure.py が 0 で終わらない: " + r.stderr)
        return json.loads(r.stdout)

    @staticmethod
    def entry(out, path):
        return next(p for p in out["paths"] if p["path"] == path)

    def test_same_output_twice(self):
        # --since を渡さない既定の窓（90 日）で 2 度走らせる。窓は HEAD（c5・2020-07-05）の日時から遡り、今の時計に依らない
        args = ("--paths", "a.txt", "new.txt", "src/dup1.txt", "src/env.sh", "tool.sh")
        first, second = self.run_measure(*args, since=None), self.run_measure(*args, since=None)
        self.assertEqual(first.returncode, 0, first.stderr)
        self.assertEqual(first.stdout, second.stdout)
        out = json.loads(first.stdout)
        self.assertTrue(out["rules"], "数え方の規則が出力に無い")
        self.assertEqual(out["window"], {"since": "2020-04-06", "base": self.base})

    def test_window_days_counts_back_from_head(self):
        out = self.measure("--window-days", "5", "--paths", "a.txt", since=None)
        self.assertEqual(out["window"]["since"], "2020-06-30")
        self.assertEqual(out["window"]["base"], _git(self.repo, "rev-parse", "HEAD~4"))   # c0b（2020-06-15）

    def test_follow_raw_no_merges_per_path(self):
        out = self.measure("--paths", "a.txt", "new.txt")
        self.assertEqual(self.entry(out, "a.txt")["frequency"], {"follow": 2, "raw": 3, "no_merges": 2})
        self.assertEqual(self.entry(out, "new.txt")["frequency"], {"follow": 3, "raw": 2, "no_merges": 2})

    def test_union_follow_is_sum_of_single_file_sets(self):
        out = self.measure("--paths", "a.txt", "new.txt")
        self.assertEqual(out["union"], {"follow": 5, "raw": 5, "no_merges": 4})

    def test_raw_minus_no_merges_is_merge_count(self):
        out = self.measure("--paths", "a.txt")
        freq = self.entry(out, "a.txt")["frequency"]
        merges = _git(self.repo, "log", "--merges", "--since=" + SINCE, "--format=%H", "--", "a.txt").split()
        self.assertEqual(len(merges), 1)
        self.assertEqual(freq["raw"] - freq["no_merges"], len(merges))

    def test_growth_counts_base_under_old_name(self):
        out = self.measure("--paths", "new.txt")
        e = self.entry(out, "new.txt")
        self.assertEqual(e["lines"], 16)
        self.assertEqual(e["growth"]["base_name"], "old.txt")
        self.assertEqual(e["growth"]["base_lines"], 10)
        self.assertEqual(e["growth"]["delta"], 6)

    def test_shallow_clone_is_unmeasurable(self):
        clone = pathlib.Path(self._tmp.name) / "shallow"
        if not clone.exists():
            subprocess.run(["git", *GIT_ID, "clone", "-q", "--depth", "1", "file://" + str(self.repo), str(clone)],
                           check=True, capture_output=True)
        out = self.measure("--paths", "new.txt", "a.txt", cwd=clone)
        self.assertIs(out["shallow"], True)
        e = self.entry(out, "new.txt")
        self.assertEqual(e["lines"], 16)
        self.assertEqual(e["growth"]["status"], "測れない")
        self.assertEqual(e["frequency"]["status"], "測れない")
        self.assertEqual(out["union"]["status"], "測れない")
        for key in ("follow", "raw", "no_merges"):
            self.assertNotIn(key, e["frequency"])
            self.assertNotIn(key, out["union"])

    def test_env_prefix_tie_is_broken_by_name_order(self):
        out = self.measure("--paths", "src/env.sh")
        self.assertEqual(out["env"]["prefix"], {"top": "AAA_", "tied": ["AAA_", "BBB_"]})

    def test_env_prefix_without_tie(self):
        out = self.measure("--paths", "src/more.sh")
        self.assertEqual(out["env"]["prefix"], {"top": "CCC_", "tied": ["CCC_"]})

    def test_env_three_counts_and_writes(self):
        out = self.measure("--paths", "src/env.sh")
        name = out["env"]["names"]["AAA_X"]
        # 追跡ファイル全体 4（env.sh・note.txt・tests/t.sh・docs/d.md）・試験と文書を除く 2・読み書きの形 1（env.sh）
        self.assertEqual(name["counts"], {"all": 4, "excluding_tests_docs": 2, "access": 1})
        self.assertEqual(name["writes"], 2)   # export AAA_X=1 と unset AAA_X
        self.assertEqual(sorted(out["env"]["names"]), ["AAA_X", "AAA_Y", "BBB_X", "BBB_Y"])

    def test_six_line_copy_found_five_line_not(self):
        out = self.measure("--paths", "src/dup1.txt")
        found = {d["path"] for d in self.entry(out, "src/dup1.txt")["duplicates"]}
        self.assertEqual(found, {"src/dup2.txt"})

    def test_entrypoints(self):
        out = self.measure("--paths", "tool.sh")
        self.assertEqual(self.entry(out, "tool.sh")["entrypoints"], {"named_by": 2, "executable": 1})

    def test_skipped_with_reasons_and_continue(self):
        out = self.measure("--max-bytes", "100", "--paths", "bin.dat", "big.txt", "loose.txt", "a.txt")
        self.assertEqual(sorted((s["path"], s["reason"]) for s in out["skipped"]),
                         [("big.txt", "too_large"), ("bin.dat", "unreadable"), ("loose.txt", "untracked")])
        self.assertEqual([p["path"] for p in out["paths"]], ["a.txt"])
        self.assertEqual(out["rules"]["max_bytes"], 100)

    def diff_file(self, name, text):
        p = pathlib.Path(self._tmp.name) / name
        p.write_text(text, encoding="utf-8")
        return str(p)

    @staticmethod
    def diff_entry(out, path):
        return next(p for p in out["diff"]["paths"] if p["path"] == path)

    def snapshot(self):
        return {args: _git(self.repo, *args) for args in
                (("status", "--porcelain"), ("rev-parse", "HEAD"), ("symbolic-ref", "HEAD"), ("ls-files", "-s"))}

    def test_patch_before_after_delta(self):
        out = self.measure("--paths", "a.txt", "src/dup1.txt", "tool.sh",
                           "--diff", self.diff_file("grow.patch", GROW_PATCH))
        self.assertEqual(out["diff"]["kind"], "patch")
        self.assertEqual(self.diff_entry(out, "a.txt")["lines"], {"before": 1, "after": 3, "delta": 2})
        self.assertEqual(self.diff_entry(out, "src/dup1.txt")["duplicates"], {"before": 1, "after": 2, "delta": 1})
        self.assertEqual(self.diff_entry(out, "tool.sh")["entrypoints"],
                         {"named_by": {"before": 2, "after": 3, "delta": 1},
                          "executable": {"before": 1, "after": 2, "delta": 1}})
        self.assertEqual(self.diff_entry(out, "src/dup3.txt")["lines"], {"before": None, "after": 6, "delta": None})
        self.assertEqual(sorted(out["diff"]["touched"]), ["a.txt", "bin/go", "src/dup3.txt"])
        self.assertIn("diff", out["rules"])

    def test_without_diff_output_has_no_diff_rule_or_section(self):
        out = self.measure("--paths", "a.txt")
        self.assertNotIn("diff", out)
        self.assertNotIn("diff", out["rules"])

    def test_patch_that_does_not_apply_stops_with_reason(self):
        r = self.run_measure("--paths", "a.txt", "--diff", self.diff_file("bad.patch", BAD_PATCH))
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("git apply", r.stderr)
        self.assertEqual(r.stdout, "")

    def test_names_list_has_only_names(self):
        out = self.measure("--paths", "src/env.sh", "--diff", self.diff_file("names.txt", "NEW_ONE\n\n  NEW_TWO  \n"))
        self.assertEqual(out["diff"]["kind"], "names")
        self.assertEqual(sorted(out["diff"]), ["kind", "names"])
        self.assertEqual(sorted(n["name"] for n in out["diff"]["names"]), ["NEW_ONE", "NEW_TWO"])

    def test_new_name_through_reader_vs_scattered_over_shells(self):
        # lib/conf.sh は殻 2 本から名指される共通の読み手、lib/solo.sh は殻 1 本（と文書）からだけ名指される
        repo = pathlib.Path(self._tmp.name) / "readers"
        repo.mkdir()
        _git(repo, "init", "-q")
        _write(repo, "lib/conf.sh", 'OLD_A="${OLD_A:-1}"\n')
        _write(repo, "lib/solo.sh", "echo solo\n")
        _write(repo, "bin/one", "#!/bin/sh\n. ./lib/conf.sh\n. ./lib/solo.sh\n", mode=0o755)
        _write(repo, "bin/two", "#!/bin/sh\n. ./lib/conf.sh\n", mode=0o755)
        _write(repo, "tests/t.sh", ". ./lib/conf.sh\n")
        _write(repo, "docs/usage.md", "Source lib/conf.sh or lib/solo.sh.\n")
        _git(repo, "add", "-A")
        _git(repo, "commit", "-q", "-m", "r0", date="2020-07-01")
        for rel, row in (("lib/conf.sh", 'echo "$NEW_VIA"'), ("lib/solo.sh", 'echo "$NEW_VIA"'),
                         ("bin/one", 'echo "$NEW_SHELL"'), ("bin/two", 'echo "$NEW_SHELL"'),
                         ("tests/t.sh", 'echo "$NEW_VIA $NEW_SHELL"')):
            with (repo / rel).open("a", encoding="utf-8") as f:
                f.write(row + "\n")
        patch = _git(repo, "diff") + "\n"
        _git(repo, "checkout", "-q", "--", ".")
        out = self.measure("--paths", "lib/conf.sh", "--diff", self.diff_file("readers.patch", patch), cwd=repo)
        names = {n["name"]: n for n in out["diff"]["names"]}
        self.assertEqual(sorted(names), ["NEW_SHELL", "NEW_VIA"])
        for n in names.values():
            self.assertEqual(sorted(n), ["name", "shell_sites", "sites", "via_readers"])
        through = names["NEW_VIA"]
        self.assertEqual(through["via_readers"], [{"path": "lib/conf.sh", "line": 2}])
        self.assertEqual(through["shell_sites"], [])
        scattered = names["NEW_SHELL"]
        self.assertEqual(scattered["via_readers"], [])
        self.assertEqual(scattered["shell_sites"], [{"path": "bin/one", "line": 4}, {"path": "bin/two", "line": 3}])

    def test_before_and_after_images_keep_symlinks_alike(self):
        repo = pathlib.Path(self._tmp.name) / "links"
        repo.mkdir()
        _git(repo, "init", "-q")
        _write(repo, "tool.sh", "echo tool\n")
        _write(repo, "other.sh", "echo other\n")
        _write(repo, "bin/run", "#!/bin/sh\nexec sh ./tool.sh\n", mode=0o755)
        _write(repo, "a.txt", "a\n")
        (repo / "alias").symlink_to("tool.sh")
        _git(repo, "add", "-A")
        _git(repo, "commit", "-q", "-m", "l0", date="2020-07-01")
        with (repo / "a.txt").open("a", encoding="utf-8") as f:
            f.write("b\n")
        plain = _git(repo, "diff") + "\n"
        _git(repo, "checkout", "-q", "--", ".")
        (repo / "alias").unlink()
        (repo / "alias").symlink_to("other.sh")
        relink = _git(repo, "diff") + "\n"
        _git(repo, "checkout", "-q", "--", ".")
        out = self.measure("--paths", "alias", "tool.sh", "--diff", self.diff_file("links.patch", plain), cwd=repo)
        self.assertEqual(self.diff_entry(out, "alias")["lines"]["delta"], 0)
        out = self.measure("--paths", "tool.sh", "--diff", self.diff_file("relink.patch", relink), cwd=repo)
        self.assertEqual(out["diff"]["touched"], ["alias"])

    def test_tracked_file_turned_symlink_is_copied_as_content(self):
        repo = pathlib.Path(self._tmp.name) / "turned"
        repo.mkdir()
        _git(repo, "init", "-q")
        _write(repo, "bin/go", "#!/bin/sh\n", mode=0o755)
        _write(repo, "note.txt", "n\n")
        _write(repo, "a.txt", "a\n")
        _git(repo, "add", "-A")
        _git(repo, "commit", "-q", "-m", "t0", date="2020-07-01")
        with (repo / "a.txt").open("a", encoding="utf-8") as f:
            f.write("b\n")
        plain = _git(repo, "diff") + "\n"
        _git(repo, "checkout", "-q", "--", ".")
        _write(repo, "untracked/real.sh", "#!/bin/sh\necho real\n")
        for rel, target in (("bin/go", "../untracked/real.sh"), ("note.txt", "untracked/real.sh")):
            (repo / rel).unlink()
            (repo / rel).symlink_to(target)
        out = self.measure("--paths", "bin/go", "note.txt", "--diff", self.diff_file("turned.patch", plain), cwd=repo)
        for rel in ("bin/go", "note.txt"):
            self.assertEqual(self.diff_entry(out, rel)["lines"], {"before": 2, "after": 2, "delta": 0})

    def test_target_repo_does_not_move(self):
        before = self.snapshot()
        index = (self.repo / ".git" / "index").read_bytes()
        self.measure("--paths", "a.txt", "--diff", self.diff_file("grow2.patch", GROW_PATCH))
        self.run_measure("--paths", "a.txt", "--diff", self.diff_file("bad2.patch", BAD_PATCH))
        self.assertEqual((self.repo / ".git" / "index").read_bytes(), index)
        self.assertEqual(self.snapshot(), before)

    def test_patch_without_git_header_is_patch(self):
        out = self.measure("--paths", "a.txt", "--diff", self.diff_file("plain.patch", PLAIN_PATCH))
        self.assertEqual(out["diff"]["kind"], "patch")
        self.assertEqual(self.diff_entry(out, "a.txt")["lines"], {"before": 1, "after": 2, "delta": 1})


BLOCK_DIR = ROOT / "blk-structure"
BLOCK_YAML = BLOCK_DIR / "blk-structure.yaml"
CONTRACT = {"units", "root", "policy_path", "base_rev"}   # base_rev は直しの後の段（計画 clean-whole の Task 2.5）
OUTPUT_FILES = {"structure_file", "design_file", "after_file"}


def _found(v, key):
    """入れ子の JSON の中の key の値を全部"""
    if isinstance(v, dict):
        for k, x in v.items():
            if k == key:
                yield x
            yield from _found(x, key)
    elif isinstance(v, list):
        for x in v:
            yield from _found(x, key)


class BlockCase(unittest.TestCase):
    """ブロックの骨（設計書 1 節・8 節・10 節の S2a）: 入力の契約 4 つ（直しの後の段の base_rev を含む）・段 A の実測・出力 3 本・節の時間・落ちても止めない"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = pathlib.Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def doc(self):
        if not BLOCK_YAML.is_file():
            self.fail(f"ブロックの YAML が無い: {BLOCK_YAML.relative_to(ROOT)}")
        import yaml
        return yaml.safe_load(BLOCK_YAML.read_text(encoding="utf-8"))

    def run_block(self, units, root, reply=None, base_rev=""):
        """Archon と同じ形で節を並びの順に回す（scriptline と同じ読み方: trigger_rule・when・loop_group の until_bash と
        max_iterations）。script の節は子で起こし（with: → INPUTS_<大文字>・ARTIFACTS_DIR・cwd は対象の根）、終了コード 0 と
        標準出力の JSON が output_format に合うことを確かめる。AI の節は構造の目の輪の中のちょうど 1 つだけで、目のほかの節は
        script だけ。目の返答は reply（既定は実測できた単位ごとに根拠つきの 1 行）。returns の節の出力を返す"""
        import scriptline
        from engine.schema import validate_schema
        doc = self.doc()
        art = self.tmp / "art"
        art.mkdir(exist_ok=True)
        inputs = {"units": str(units), "root": str(root), "policy_path": "", "base_rev": base_rev}
        scope = scriptline.Scope("blk-structure", inputs)
        env = {k: v for k, v in child_env().items() if not k.startswith("INPUTS_")}
        env.update(ARTIFACTS_DIR=str(art), WORKFLOW_ID="run-structure", PYTHONDONTWRITEBYTECODE="1")
        loops = [n for n in doc["nodes"] if "loop_group" in n]
        inner = [m for lp in loops for m in lp["loop_group"]["nodes"]]
        ai = [m for m in inner if any(k in m for k in scriptline.AI_KEYS)]
        self.assertEqual(len(ai), 1, "AI の節は構造の目の輪の中のちょうど 1 つだけ")
        for n in doc["nodes"] + inner:
            if n is not ai[0] and "loop_group" not in n:
                self.assertIn("script", n, f"構造の目のほかの節は script だけ: {n.get('id')}")

        def eye_reply():
            if reply is not None:
                return reply
            got = json.loads(pathlib.Path(scope.out["stage-a"]["structure_file"]).read_text(encoding="utf-8"))
            return {"rows": [{"unit_id": u["id"], "verdict": "汚れない", "faces": [], "evidence": [f"/units/{i}/measure"],
                              "reason": "足す形が増えない"} for i, u in enumerate(got["units"]) if u["status"] == "measured"]}

        def script(n):
            e = dict(env)
            e.update({f"INPUTS_{k.upper()}": scope.value(v) for k, v in (n.get("with") or {}).items()})
            p = subprocess.run([sys.executable, str(BLOCK_DIR / "scripts" / f"{n['script']}.py")], cwd=str(root), env=e,
                               capture_output=True, text=True, encoding="utf-8", stdin=subprocess.DEVNULL)
            self.assertEqual(p.returncode, 0, f"節 {n['id']} が落ちた: {p.stderr[-1500:]}")
            out = json.loads(p.stdout)
            if "output_format" in n:
                self.assertEqual(validate_schema(out, n["output_format"]), [], n["id"])
            return out

        def walk(nodes):
            for n in nodes:
                if not scriptline.ScriptLine._runs(None, scope, n, False):
                    scope.status[n["id"]] = "skipped"
                    continue
                if "loop_group" in n:
                    lg = n["loop_group"]
                    nid, field, want = scriptline.UNTIL.match(lg["until_bash"].split("#")[0].strip()).groups()
                    for _ in range(lg["max_iterations"]):
                        walk(lg["nodes"])
                        if scope.status.get(nid) == "ok" and scriptline._text(scope.out[nid].get(field)) == want:
                            break
                    else:
                        self.fail(f"輪 {n['id']} が max_iterations {lg['max_iterations']} に当たった")
                    out = scope.out[lg["nodes"][-1]["id"]]
                else:
                    out = eye_reply() if n is ai[0] else script(n)
                scope.out[n["id"]], scope.status[n["id"]] = out, "ok"
        walk(doc["nodes"])
        return scope.out[doc["returns"]]

    def repo(self):
        repo = self.tmp / "repo"
        repo.mkdir()
        _git(repo, "init", "-q")
        _write(repo, "a.txt", "one\ntwo\n")
        _write(repo, "b.txt", "b\n")
        _git(repo, "add", "-A")
        _git(repo, "commit", "-q", "-m", "c0", date="2020-01-01")
        return repo

    def units(self, rows):
        f = self.tmp / "units.json"
        f.write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")
        return f

    def test_inputs_are_the_three_of_the_contract(self):
        inputs = self.doc().get("inputs") or {}
        self.assertEqual(set(inputs), CONTRACT)
        self.assertEqual((inputs["policy_path"] or {}).get("default"), "")

    def test_declares_only_two_output_files(self):
        doc = self.doc()
        self.assertEqual(doc.get("returns"), "collect")
        self.assertEqual(doc.get("outcome_field"), "ok")
        ret = next(n for n in doc["nodes"] if n["id"] == doc["returns"])
        props = ret["output_format"]["properties"]
        self.assertIn("ok", ret["output_format"].get("required", []))
        self.assertEqual({k for k in props if k.endswith("_file")}, OUTPUT_FILES)

    def test_measures_units_and_writes_design_rows_and_timing(self):
        from engine.schema import validate_schema
        reply = {"rows": [{"unit_id": "u-7", "verdict": "汚れる", "faces": [5], "evidence": ["/units/0/measure", "/timing/wall_s"],
                           "reason": "骨組みの無い口が増える", "chosen": "既存の口に寄せる", "chosen_reason": "骨組みが在る"}]}
        out = self.run_block(self.units([{"id": "u-7", "paths": ["a.txt"], "summary": "直す所"}]), self.repo(), reply=reply)
        self.assertIs(out["ok"], True)
        self.assertEqual(out["status"], "ok", out)
        structure = json.loads(pathlib.Path(out["structure_file"]).read_text(encoding="utf-8"))
        self.assertIn("u-7", json.dumps(structure, ensure_ascii=False))
        self.assertIn("a.txt", json.dumps(structure, ensure_ascii=False))
        walls = list(_found(structure, "wall_s"))
        self.assertTrue(walls and all(isinstance(w, (int, float)) for w in walls), structure)
        design = pathlib.Path(out["design_file"])
        self.assertTrue(design.is_file())
        rows = [json.loads(x) for x in design.read_text(encoding="utf-8").splitlines()]   # JSON Lines は空行を許さない
        schema = json.loads((BLOCK_DIR / "design-row.schema.json").read_text(encoding="utf-8"))
        self.assertEqual([validate_schema(r, schema) for r in rows], [[]], rows)
        self.assertEqual([(r["unit_id"], r["verdict"], r["evidence"]) for r in rows],
                         [(x["unit_id"], x["verdict"], x["evidence"]) for x in reply["rows"]])

    def test_measure_failure_does_not_stop_the_line(self):
        plain = self.tmp / "not-git"
        plain.mkdir()
        _write(plain, "a.txt", "x\n")
        out = self.run_block(self.units([{"id": "u-1", "paths": ["a.txt"], "summary": "s"}]), plain)
        self.assertIs(out["ok"], True)
        structure = json.loads(pathlib.Path(out["structure_file"]).read_text(encoding="utf-8"))
        reasons = [r for r in _found(structure, "reason") if isinstance(r, str) and r.strip()]
        self.assertTrue(reasons, structure)
        self.assertEqual(pathlib.Path(out["design_file"]).stat().st_size, 0)

    def test_unreadable_units_does_not_stop_the_line(self):
        out = self.run_block(self.tmp / "missing-units.json", self.repo())
        self.assertIs(out["ok"], True)
        structure = json.loads(pathlib.Path(out["structure_file"]).read_text(encoding="utf-8"))
        self.assertTrue([r for r in _found(structure, "reason") if isinstance(r, str) and r.strip()], structure)

    def test_design_row_schema_is_readable(self):
        self.doc()
        schemas = sorted(BLOCK_DIR.rglob("*.schema.json"))
        self.assertEqual(len(schemas), 1, schemas)
        s = json.loads(schemas[0].read_text(encoding="utf-8"))
        self.assertEqual(s.get("type"), "object")
        self.assertTrue(s.get("properties"))


class EyeInputsCase(unittest.TestCase):
    """目に見せる物（計画 2026-10-09-clean-whole の Task 2.3）: 段 A が単位のパスに当たる考えの地図の行・知る場所の数と、方針の文書・
    根の地図の文書を structure.json に置き、目の支度がそれを指示書に貼る。入力の契約は 3 つのまま（地図と表は root から探す）"""

    setUp, tearDown, units = BlockCase.setUp, BlockCase.tearDown, BlockCase.units
    MAP = ("# 地図\n\n### `outcome` run の結末\n\n- 状態: 住処あり\n- 住処: `src/report.py`\n\n"
           "### `halt` 止め札\n\n- 状態: 住処あり\n- 住処: `src/halt.py`\n")
    TABLE = {"exclude": ["docs/**"], "concepts": {
        "outcome": {"status": "住処あり", "fences": [{"what": "結末の語", "pattern": "\"round_limit\"",
                                                     "allowed": ["src/report.py"], "known": {}}]},
        "halt": {"status": "住処あり", "fences": [{"what": "止め札", "pattern": "\"STOP\"", "allowed": ["src/halt.py"],
                                                  "known": {}}]}}}

    def target(self, with_table=True):
        repo = self.tmp / "target"
        repo.mkdir()
        _git(repo, "init", "-q")
        _write(repo, "src/report.py", 'OUT = "round_limit"\n')
        _write(repo, "src/edge.py", 'x = "round_limit"\n')
        _write(repo, "src/halt.py", 'S = "STOP"\n')
        _write(repo, "POLICY.md", "決まり: 結末の語は report.py だけが持つ\n")
        _write(repo, "AGENTS.md", "# 対象の決まり\n\n層は下へだけ依存する\n")
        if with_table:
            _write(repo, "docs/concepts.md", self.MAP)
            _write(repo, "docs/concepts.json", json.dumps(self.TABLE, ensure_ascii=False))
        _git(repo, "add", "-A")
        _git(repo, "commit", "-q", "-m", "c0", date="2020-01-01")
        return repo

    def stage_and_prep(self, repo, policy=""):
        art = self.tmp / "art"
        art.mkdir(exist_ok=True)
        units = self.units([{"id": "u-1", "paths": ["src/edge.py"], "summary": "境の節が結末の語を書く"}])
        env = {k: v for k, v in child_env().items() if not k.startswith("INPUTS_")}
        env.update(ARTIFACTS_DIR=str(art), PYTHONDONTWRITEBYTECODE="1", INPUTS_UNITS=str(units), INPUTS_ROOT=str(repo),
                   INPUTS_POLICY_PATH=policy)
        p = subprocess.run([sys.executable, str(BLOCK_DIR / "scripts" / "stage_a.py")], cwd=str(repo), env=env,
                           capture_output=True, text=True, encoding="utf-8", stdin=subprocess.DEVNULL)
        self.assertEqual(p.returncode, 0, p.stderr)
        sf = json.loads(p.stdout)["structure_file"]
        env["INPUTS_STRUCTURE_FILE"] = sf
        q = subprocess.run([sys.executable, str(BLOCK_DIR / "scripts" / "eye_prep.py")], cwd=str(repo), env=env,
                           capture_output=True, text=True, encoding="utf-8", stdin=subprocess.DEVNULL)
        self.assertEqual(q.returncode, 0, q.stderr)
        return json.loads(pathlib.Path(sf).read_text(encoding="utf-8")), json.loads(q.stdout)["prompt"]

    def test_eye_sees_concept_rows_for_unit_paths(self):
        doc, prompt = self.stage_and_prep(self.target())
        unit = doc["units"][0]
        self.assertEqual([r["id"] for r in unit["concepts"]["rows"]], ["outcome"])   # 止め札の行は単位に当たらない
        self.assertEqual([(x["concept"], x["path"], x["home"], x["known_places"]) for x in unit["concepts"]["places"]],
                         [("outcome", "src/edge.py", False, 2)])
        self.assertIn("### `outcome` run の結末", prompt)
        self.assertNotIn("### `halt`", prompt)
        self.assertIn("known_places", prompt)

    def test_eye_sees_policy_text(self):
        doc, prompt = self.stage_and_prep(self.target(), policy="POLICY.md")
        self.assertEqual(doc["rules"]["policy"]["path"], "POLICY.md")
        self.assertIn("結末の語は report.py だけが持つ", prompt)
        self.assertIn("層は下へだけ依存する", prompt)   # 根の地図の文書（AGENTS.md）

    def test_no_map_no_table_measures_only(self):
        """地図も表も無い対象は実測だけで判じる（作らない）。concepts は空の並び"""
        repo = self.target(with_table=False)
        doc, prompt = self.stage_and_prep(repo)
        self.assertEqual(doc["units"][0]["concepts"], {"rows": [], "places": []})
        self.assertFalse((repo / "docs").exists())


class AfterCase(unittest.TestCase):
    """直しの後の段（計画 2026-10-09-clean-whole の Task 2.5）: 入力 base_rev が在る周は、単位を測らず目も起こさず、直しの前の版と
    今の作業ツリーの差分を測って after.json に書く（柵の表が在れば知る場所の増え・新しい名・増えた写しの塊）"""

    setUp, tearDown, units, run_block, doc = (BlockCase.setUp, BlockCase.tearDown, BlockCase.units, BlockCase.run_block,
                                              BlockCase.doc)
    target = EyeInputsCase.target
    MAP, TABLE = EyeInputsCase.MAP, EyeInputsCase.TABLE

    def after(self, repo, base):
        out = self.run_block(self.tmp / "no-units.json", repo, base_rev=base)
        self.assertIs(out["ok"], True)
        self.assertEqual(pathlib.Path(out["design_file"]).stat().st_size, 0)
        return json.loads(pathlib.Path(out["after_file"]).read_text(encoding="utf-8"))

    def test_after_stage_counts_real_diff(self):
        repo = self.target()
        base = _git(repo, "rev-parse", "HEAD")
        _write(repo, "src/edge.py", 'x = "round_limit"\ny = "round_limit"\nNEW_KNOB_NAME = 1\n')   # 住処の外に 1 行・新しい名
        _write(repo, "src/fresh.py", 'z = "round_limit"\n')                                            # 追跡前の新しいファイル
        _write(repo, "src/report.py", 'OUT = "round_limit"\nOTHER = "round_limit"\n')                 # 住処の中は数えない
        got = self.after(repo, base)
        self.assertEqual(got["status"], "ok", got)
        self.assertEqual(sorted((f["path"], f["before"], f["after"]) for f in got["fence_up"]),
                         [("src/edge.py", 1, 2), ("src/fresh.py", 0, 1)])
        self.assertIn("NEW_KNOB_NAME", [n["name"] for n in got["new_names"]])
        self.assertEqual(got["tables"], ["docs/concepts.json"])
        self.assertEqual(_git(repo, "status", "--porcelain", "--untracked-files=no").count("\n") + 1, 2)   # 対象の index を動かさない

    def test_no_table_reports_only(self):
        """表の無い対象は柵を数えない（fence_up は空。作らない）が、差分の実測は出す"""
        repo = self.target(with_table=False)
        base = _git(repo, "rev-parse", "HEAD")
        _write(repo, "src/edge.py", 'x = "round_limit"\ny = "round_limit"\n')
        got = self.after(repo, base)
        self.assertEqual((got["status"], got["fence_up"], got["tables"]), ("ok", [], []))
        self.assertEqual(got["changed"], ["src/edge.py"])
        self.assertFalse((repo / "docs").exists())

    def test_after_stage_keeps_first_eye_rows(self):
        """直しの後の段は、同じ置き場の 1 度目の構造の目の行（design.jsonl）と目の控えを消さない（報告と最後の関所が読む）"""
        repo = self.target()
        reply = {"rows": [{"unit_id": "u-1", "verdict": "汚れる", "faces": [2], "evidence": ["/units/0/measure"],
                           "reason": "責務を割る", "chosen": "1 か所に固める", "chosen_reason": "読み直しを割らない"}]}
        first = self.run_block(self.units([{"id": "u-1", "paths": ["src/edge.py"], "summary": "s"}]), repo, reply=reply)
        design = pathlib.Path(first["design_file"])
        before = design.read_text(encoding="utf-8")
        self.assertTrue(before.strip())
        self.after(repo, _git(repo, "rev-parse", "HEAD"))
        self.assertEqual(design.read_text(encoding="utf-8"), before)

    def test_non_utf8_diff_is_measured(self):
        repo = self.target()
        base = _git(repo, "rev-parse", "HEAD")
        (repo / "src" / "latin.txt").write_bytes("caf\xe9 round_limit\n".encode("latin-1"))
        _write(repo, "src/edge.py", 'x = "round_limit"\ny = "round_limit"\n')
        got = self.after(repo, base)
        self.assertEqual(got["status"], "ok", got)
        self.assertIn("src/latin.txt", got["changed"])
        self.assertEqual([f["path"] for f in got["fence_up"]], ["src/edge.py"])

    def test_archon_copy_is_not_measured(self):
        """run の作業ツリーに置かれた .archon/ の写し（未追跡）は直しの差分に数えない"""
        repo = self.target()
        base = _git(repo, "rev-parse", "HEAD")
        _write(repo, ".archon/workflows/x/src/y.py", 'z = "round_limit"\n')
        got = self.after(repo, base)
        self.assertEqual((got["changed"], got["fence_up"]), ([], []))

    def test_table_widened_by_fix_still_counts(self):
        """直しが柵の表の知ってよい所を広げても、数えは直しの前の版の表で行い、表が変わったことを名指す"""
        repo = self.target()
        base = _git(repo, "rev-parse", "HEAD")
        wide = json.loads(json.dumps(self.TABLE))
        wide["concepts"]["outcome"]["fences"][0]["allowed"].append("src/edge.py")
        _write(repo, "docs/concepts.json", json.dumps(wide, ensure_ascii=False))
        _write(repo, "src/edge.py", 'x = "round_limit"\ny = "round_limit"\n')
        got = self.after(repo, base)
        self.assertEqual([f["path"] for f in got["fence_up"]], ["src/edge.py"])
        self.assertEqual(got["tables_changed"], ["docs/concepts.json"])

    def test_unknown_base_does_not_stop_the_line(self):
        got = self.after(self.target(), "0" * 40)
        self.assertEqual(got["status"], "failed")
        self.assertTrue(got["reason"].strip())


class EyeCase(unittest.TestCase):
    """構造の目（設計書 10 節の S2b）: 段 A の後の輪（prep → 道具ゼロの役 → 受け付け）が判定を確かめ、design.jsonl に行を書く。
    evidence の各行は structure.json の欄を指す JSON Pointer（RFC 6901）"""

    setUp, tearDown, doc, repo, units = BlockCase.setUp, BlockCase.tearDown, BlockCase.doc, BlockCase.repo, BlockCase.units

    def eye_loop(self):
        doc = self.doc()
        loops = [n for n in doc["nodes"] if "loop_group" in n]
        self.assertEqual(len(loops), 1, "段 A の後に構造の目の輪が 1 つ要る")
        return doc, loops[0]

    def ai_node(self, loop):
        ai = [m for m in loop["loop_group"]["nodes"] if "prompt" in m or "command" in m]
        self.assertEqual(len(ai), 1, "輪の AI の節は構造の目の 1 つだけ")
        return ai[0]

    def test_eye_loop_follows_stage_a_and_feeds_collect(self):
        doc, loop = self.eye_loop()
        self.assertIn("stage-a", loop.get("depends_on") or [])
        g = loop["loop_group"]
        self.assertEqual((g.get("max_iterations"), g.get("fresh_context")), (3, False))
        self.assertIn(".output.done", g.get("until_bash", ""))
        ai = self.ai_node(loop)
        self.assertEqual(ai.get("allowed_tools"), [], "見せるのは structure.json と単位の要約だけ（道具ゼロ）")
        self.assertEqual(ai.get("effort"), "high")
        self.assertEqual(ai.get("model"), "opus", "前付け（core/agents/blind-judge.md）の model を段に書く（run の既定に頼らない）")
        after = [m for m in g["nodes"] if "script" in m and ai["id"] in (m.get("depends_on") or [])]
        self.assertEqual(len(after), 1, "役の後に受け付けの script の節が 1 つ要る")
        collect = next(n for n in doc["nodes"] if n["id"] == doc["returns"])
        self.assertIn(loop["id"], collect.get("depends_on") or [])

    def run_eye(self, reply):
        """段 A を走らせ、輪の script の節を並びの順に起こす（AI の節は reply を出力に置く）。受け付けの出力と design.jsonl を返す"""
        import scriptline
        doc, loop = self.eye_loop()
        ai = self.ai_node(loop)
        repo = self.repo()
        units = self.units([{"id": "u-7", "paths": ["a.txt"], "summary": "直す所"}])
        art = self.tmp / "art"
        art.mkdir(exist_ok=True)
        scope = scriptline.Scope("blk-structure", {"units": str(units), "root": str(repo), "policy_path": ""})
        env = {k: v for k, v in child_env().items() if not k.startswith("INPUTS_")}
        env.update(ARTIFACTS_DIR=str(art), WORKFLOW_ID="run-structure", PYTHONDONTWRITEBYTECODE="1")
        stage = next(n for n in doc["nodes"] if n["id"] == "stage-a")
        last = None
        for n in [stage, *loop["loop_group"]["nodes"]]:
            if n is ai:
                scope.out[n["id"]], scope.status[n["id"]] = reply, "ok"
                continue
            e = dict(env)
            e.update({f"INPUTS_{k.upper()}": scope.value(v) for k, v in (n.get("with") or {}).items()})
            p = subprocess.run([sys.executable, str(BLOCK_DIR / "scripts" / f"{n['script']}.py")], cwd=str(repo), env=e,
                               capture_output=True, text=True, encoding="utf-8", stdin=subprocess.DEVNULL)
            self.assertEqual(p.returncode, 0, f"節 {n['id']} が落ちた: {p.stderr[-1500:]}")
            last = scope.out[n["id"]] = json.loads(p.stdout)
            scope.status[n["id"]] = "ok"
        design = pathlib.Path(scope.out["stage-a"]["design_file"])
        return last, design

    def test_accepted_reply_becomes_design_row(self):
        from engine.schema import validate_schema
        reply = {"rows": [{"unit_id": "u-7", "verdict": "汚れる", "faces": [2], "evidence": ["/units/0/measure"],
                           "reason": "責務を 2 か所に割る", "chosen": "1 か所に固める", "chosen_reason": "読み直しを割らない"}]}
        _, loop = self.eye_loop()
        self.assertEqual(validate_schema(reply, self.ai_node(loop).get("output_format") or {}), [])
        out, design = self.run_eye(reply)
        self.assertEqual((out["ok"], out["done"]), (True, True), out)
        rows = [json.loads(x) for x in design.read_text(encoding="utf-8").splitlines()]
        self.assertEqual(len(rows), 1, rows)
        schema = json.loads((BLOCK_DIR / "design-row.schema.json").read_text(encoding="utf-8"))
        self.assertEqual(validate_schema(rows[0], schema), [], rows[0])
        self.assertEqual((rows[0]["unit_id"], rows[0]["route"], rows[0]["chosen"]), ("u-7", "自分で決める", "1 か所に固める"))

    def test_bad_reply_is_rejected_and_writes_no_row(self):
        good = {"unit_id": "u-7", "verdict": "汚れない", "faces": [1], "evidence": ["/timing/wall_s"], "reason": "形が増えない"}
        for name, bad in (("無い単位", {"unit_id": "u-99"}), ("形の番号の外", {"faces": [7]}),
                          ("無い欄", {"evidence": ["/units/0/measure/no_such_field"]}),
                          ("汚れないで根拠が空", {"evidence": [], "reason": ""})):
            with self.subTest(name):
                self.tearDown()
                self.setUp()
                out, design = self.run_eye({"rows": [{**good, **bad}]})
                self.assertEqual((out["ok"], out["done"]), (False, False), out)
                self.assertTrue(out["reason"].strip(), out)
                self.assertEqual(design.stat().st_size, 0)


if __name__ == "__main__":
    unittest.main()
