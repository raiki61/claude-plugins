#!/usr/bin/env python3
"""attention/scripts/lib/changemap.py（変更の地図の部品）の規則を固定する。GitHub にも git にも触らない。

固定するのは「材料 → 出力」の規則だけ: diff の分解（引用形の日本語 path・改名・' b/' を含む path・
削除・バイナリ）、先頭コメント / docstring の取り方と切れの申告、骨組みの正規表現、名前の言及、
大きい変更の縮め方、木の描画と周辺の選び方、git status --porcelain の読み方。
"""

import importlib.util
import pathlib
import sys
import unittest

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

ROOT = pathlib.Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location(
    "changemap", ROOT / "attention" / "scripts" / "lib" / "changemap.py")
cm = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cm)


DIFF = '''diff --git "a/docs/\\346\\227\\245\\346\\234\\254.md" "b/docs/\\346\\227\\245\\346\\234\\254.md"
new file mode 100644
--- /dev/null
+++ "b/docs/\\346\\227\\245\\346\\234\\254.md"
@@ -0,0 +1,2 @@
+# 見出し
+本文
diff --git a/old/name.py b/new/name.py
similarity index 90%
rename from old/name.py
rename to new/name.py
--- a/old/name.py
+++ b/new/name.py
@@ -1,2 +1,2 @@
-x = 1
+x = 2
 y
diff --git a/weird b/dir/f.txt b/weird b/dir/f.txt
--- a/weird b/dir/f.txt
+++ b/weird b/dir/f.txt
@@ -1 +1 @@
-a
+b
diff --git a/gone.txt b/gone.txt
deleted file mode 100644
--- a/gone.txt
+++ /dev/null
@@ -1 +0,0 @@
-bye
diff --git a/img.png b/img.png
Binary files a/img.png and b/img.png differ
'''


class Diff(unittest.TestCase):
    def test_unquote_octal_utf8(self):
        self.assertEqual(cm.unquote_git_path('"docs/\\346\\227\\245\\346\\234\\254.md"'), "docs/日本.md")
        self.assertEqual(cm.unquote_git_path("plain/x.py"), "plain/x.py")

    def test_split_handles_quoted_rename_space_deleted_binary(self):
        files, renames = cm.split_diff(DIFF)
        self.assertEqual(set(files), {"docs/日本.md", "new/name.py", "weird b/dir/f.txt", "gone.txt", "img.png"})
        self.assertEqual(cm.added_lines(files["docs/日本.md"]), ["# 見出し", "本文"])
        self.assertEqual(renames, {"new/name.py": "old/name.py"})
        self.assertEqual(files["weird b/dir/f.txt"], ["@@ -1 +1 @@", "-a", "+b"])
        self.assertEqual(files["gone.txt"], ["@@ -1 +0,0 @@", "-bye"])
        self.assertEqual(files["img.png"], [])

    def test_hunk_line_starting_with_dashes_is_not_a_header(self):
        d = "diff --git a/q.sql b/q.sql\n--- a/q.sql\n+++ b/q.sql\n@@ -1 +1 @@\n--- old comment\n+-- new comment\n"
        files, _ = cm.split_diff(d)
        self.assertEqual(files["q.sql"], ["@@ -1 +1 @@", "--- old comment", "+-- new comment"])


class Head(unittest.TestCase):
    def test_py_docstring_after_coding_line_and_prefix(self):
        h, cut = cm.file_head("a.py", ['#!/usr/bin/env python3', '# -*- coding: utf-8 -*-', 'r"""Doc 1', 'line 2"""', 'x=1'])
        self.assertEqual(h, ['# -*- coding: utf-8 -*-', 'r"""Doc 1', 'line 2"""'])
        self.assertFalse(cut)

    def test_py_one_liner_and_comment_only(self):
        self.assertEqual(cm.file_head("b.py", ['"""one"""', 'def f(): pass']), (['"""one"""'], False))
        self.assertEqual(cm.file_head("d.py", ['# only', '# here', '', 'import os']), (['# only', '# here'], False))

    def test_truncation_is_reported(self):
        h, cut = cm.file_head("c.py", ['"""long'] + [f"l{i}" for i in range(12)])
        self.assertEqual(len(h), cm.HEAD_LINES)
        self.assertTrue(cut)
        h, cut = cm.file_head("w2.yml", ["# " + str(i) for i in range(10)])
        self.assertEqual((len(h), cut), (cm.HEAD_LINES, True))

    def test_yaml_comment_block_after_name(self):
        self.assertEqual(cm.file_head("w.yml", ["name: X", "# c1", "# c2", "on:"]), (["# c1", "# c2"], False))
        self.assertEqual(cm.file_head("w.yml", ["on:", "  push:", "jobs:"]), ([], False))


class Outline(unittest.TestCase):
    def test_yaml_steps_including_uses_and_id(self):
        o = cm.outline("w.yml", ["jobs:", "  build:", "    steps:", "      - uses: actions/checkout@v4",
                                 "      - name: Build", "        uses: docker/bake-action@v7",
                                 "      - id: detect", "        run: echo"])
        self.assertEqual(o, ["jobs:", "  build:", "      - uses: actions/checkout@v4", "      - name: Build",
                             "        uses: docker/bake-action@v7", "      - id: detect"])

    def test_python_shell_bats_hcl_adoc(self):
        self.assertEqual(cm.outline("a.py", ["async def f():", "def g():", "class C:", "    async def m(self):", "x = 1"]),
                         ["async def f():", "def g():", "class C:", "    async def m(self):"])
        self.assertEqual(cm.outline("s.sh", ["my-func() {", "function other-one {", "x=1"]), ["my-func() {", "function other-one {"])
        self.assertEqual(cm.outline("t.bats", ['@test "a" {', "  run x"]), ['@test "a" {'])
        self.assertEqual(cm.outline("b.hcl", ['target "x" {', "  tags = []", 'group "default" {']), ['target "x" {', 'group "default" {'])
        self.assertEqual(cm.outline("d.adoc", ["== 節", "本文", "=== 小節"]), ["== 節", "=== 小節"])
        self.assertEqual(cm.outline("z.unknown", ["a", "b"]), [])


class Refs(unittest.TestCase):
    def test_mentions_with_lines_and_action_dir_name(self):
        hunks = {
            "a.yml": ["@@", "+  run: python3 deploy/x.py go", "+# x.py is nice", "+  uses: ./.github/actions/setup-thing"],
            "deploy/x.py": ["@@", "+print(1)"],
            ".github/actions/setup-thing/action.yml": ["@@", "+name: t"],
        }
        rel = cm.call_refs(list(hunks), hunks)
        self.assertEqual(rel["a.yml"], [
            (".github/actions/setup-thing/action.yml", ["  uses: ./.github/actions/setup-thing"]),
            ("deploy/x.py", ["  run: python3 deploy/x.py go", "# x.py is nice"]),
        ])
        self.assertNotIn("deploy/x.py", rel)

    def test_modified_hunks_small_full_large_outline_or_body(self):
        small = ["@@ -1 +1 @@", "-a", "+b"]
        self.assertEqual(cm.modified_hunks("f.txt", small, 1, 1), [("| ", ln) for ln in small])
        big = ["@@ -1,5 +1,50 @@ x"] + [f"+    - name: step {i}" for i in range(3)] + [f"+  k{i}: v" for i in range(30)]
        out = cm.modified_hunks("w.yml", big, 33, 0)
        self.assertEqual(out[0], ("| ", "@@ -1,5 +1,50 @@ x"))
        self.assertIn(("", "追加行の骨組み:"), out)
        self.assertIn(("| ", "+    - name: step 0"), out)
        plain = ["@@ -1,20 +1,20 @@"] + ["-# c"] * 10 + ["-helm 3.16.4", "+helm 3.21.4"] + ["+# d"] * 10
        out = cm.modified_hunks(".tool-versions", plain, 11, 11)
        self.assertIn(("", "コメントでない変更行:"), out)
        self.assertEqual([t for p, t in out if p == "| "][1:], ["-helm 3.16.4", "+helm 3.21.4"])


class Tree(unittest.TestCase):
    def test_tree_marks_notes_siblings_and_rest_counts(self):
        entries = [
            {"path": ".github/workflows/kind-deploy-check.yml", "mark": "+", "note": "+526"},
            {"path": ".github/workflows/helm-chart-check.yml", "mark": "~", "note": "+5/-1"},
            {"path": "docker-bake.hcl", "mark": "+", "note": "+81"},
            {"path": "gone.txt", "mark": "-", "note": "-3"},
        ]
        siblings = {
            ".": ["README.md", ".github", "docker-bake.hcl", "skaffold.yaml", "backend", "gone.txt"],
            ".github/workflows": ["lint.yml", "helm-chart-check.yml", "container-build-check.yml",
                                  "release-pr.yml", "docs-check.yml", "frontend-checks.yml", "a.yml"],
            ".github": ["workflows", "actions"],
        }
        lines = cm.render_tree(entries, siblings, root_label="repo")
        text = "\n".join(lines)
        self.assertEqual(lines[0], " repo/")
        self.assertTrue(any(ln.startswith("+") and "kind-deploy-check.yml" in ln and ln.rstrip().endswith("+526") for ln in lines))
        self.assertTrue(any(ln.startswith("~") and "helm-chart-check.yml" in ln for ln in lines))
        self.assertTrue(any(ln.startswith("-") and "gone.txt" in ln and ln.rstrip().endswith("-3") for ln in lines))
        # 周辺は名前の近いものから 4 件（-check を共有するもの）。残りは「… ほか N」
        self.assertIn("container-build-check.yml", text)
        self.assertIn("docs-check.yml", text)
        self.assertIn("frontend-checks.yml", text)   # checks / check を同じ語に数える
        self.assertRegex(text, r"workflows/  … ほか 2")  # 7 − 変更 1 − 表示 4
        # 途中の階層（.github）も周辺（actions）を薄く出す。根は 6 件全部が出るので「ほか」が無い
        self.assertIn("actions", text)
        self.assertNotRegex(text, r"repo/  … ほか")

    def test_tree_long_name_moves_note_to_next_line(self):
        long = "deploy/scripts/tests/release_verify_notify_with_long_suffix_name.bats"
        lines = cm.render_tree([{"path": long, "mark": "+", "note": "+327"}], None)
        self.assertTrue(all(cm.width(l) <= 60 for l in lines), lines)
        self.assertEqual(lines[-1].strip(), "+327")
        self.assertTrue(lines[-2].startswith("+") and lines[-2].endswith(".bats"))

    def test_tree_sibling_dirs_keep_slash_and_are_not_double_counted(self):
        entries = [{"path": "a/x.py", "mark": "~", "note": "+1"}]
        lines = cm.render_tree(entries, {".": ["a/", "b/", "c.txt"], "a": ["x.py", "y.py", "sub/"]})
        text = "\n".join(lines)
        self.assertIn("b/", text)
        self.assertIn("sub/", text)
        self.assertNotRegex(text, r"\./  … ほか")   # a/ は木に出ているので残りに数えない

    def test_tree_without_siblings(self):
        lines = cm.render_tree([{"path": "a/b.py", "mark": "~", "note": "+1"}], None)
        self.assertEqual(lines, [" ./", "   a/", "~    b.py" + " " * (cm.TREE_NOTE_COL - len("~    b.py")) + "+1"])

    def test_rank_siblings_prefers_shared_tokens_then_extension(self):
        names = ["zeta.py", "kind-tests.bats", "verify-values.py", "readme.md", "ci-kind-checks.py"]
        picked = cm.rank_siblings(names, {"ci-kind-checks.py"}, shown=2)
        self.assertEqual(picked, ["kind-tests.bats", "verify-values.py"])


class Porcelain(unittest.TestCase):
    def test_entries_from_porcelain_and_numstat(self):
        por = (" M a/b.py\n?? new.txt\nD  gone.txt\nR  old.md -> new.md\nMM \"docs/\\346\\227\\245.md\"\n"
               "R  docs/o.md -> docs/r.md\n?? newdir/\n")
        num = cm.parse_numstat(
            "3\t1\ta/b.py\n0\t4\tgone.txt\n-\t-\timg.png\n2\t2\t\"docs/\\346\\227\\245.md\"\n"
            "1\t0\tdocs/{o.md => r.md}\n5\t0\told.md => new.md\n1\t0\tsrc/{a => b}/x.py\n")
        ent = cm.entries_from_porcelain(por, num)
        got = {e["path"]: (e["mark"], e["note"]) for e in ent}
        self.assertEqual(got["a/b.py"], ("~", "+3/-1"))
        self.assertEqual(got["new.txt"], ("+", "新規"))
        self.assertEqual(got["gone.txt"], ("-", "-4"))
        self.assertEqual(got["new.md"], ("~", "+5  旧: old.md"))
        self.assertEqual(got["docs/日.md"], ("~", "+2/-2"))       # numstat の引用形を戻して突き合わせる
        self.assertEqual(got["docs/r.md"], ("~", "+1  旧: docs/o.md"))  # {old => new} 形
        self.assertEqual(num["src/b/x.py"], (1, 0))
        self.assertEqual(num["img.png"], (None, None))
        self.assertEqual(got["newdir"][0], "+")                   # 階層ごと新規。名前の無い行にしない
        self.assertIn("階層ごと", got["newdir"][1])


if __name__ == "__main__":
    unittest.main(verbosity=1)
