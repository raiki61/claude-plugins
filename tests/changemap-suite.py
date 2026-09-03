#!/usr/bin/env python3
"""attention/scripts/lib/changemap.py（変更の地図の部品）の規則を固定する。GitHub にも git にも触らない。

固定するのは「材料 → 出力」の規則だけ: diff の分解（引用形の日本語 path・改名・' b/' を含む path・
削除・バイナリ）、先頭コメント / docstring の取り方と切れの申告、骨組みの正規表現、名前の言及、
変更の枠（今の姿に帯）、木の描画と周辺の選び方、git status --porcelain の読み方。
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


FRAME_DIFF = """diff --git a/src/a.py b/src/a.py
--- a/src/a.py
+++ b/src/a.py
@@ -1,9 +1,11 @@ def f():
 def f():
     x = 1
+    y = 2
     return x


 def g(a,
-      b):
+      b, c):
+    z = 3
     return a
@@ -40,3 +42,3 @@ def h():
 def h():
-    old = 1
+    new = 1
     return 0
diff --git a/web/app.ts b/web/app.ts
--- a/web/app.ts
+++ b/web/app.ts
@@ -1,3 +1,3 @@
 const a = 1;
-const b = 2;
+const b = 3;
 export {a, b};
diff --git a/docs/new.md b/docs/new.md
new file mode 100644
--- /dev/null
+++ b/docs/new.md
@@ -0,0 +1,2 @@
+# t
+body
diff --git a/docs/d.md b/docs/d.md
--- a/docs/d.md
+++ b/docs/d.md
@@ -1,3 +1,3 @@
 # t
-old text
+new text
 same
"""
# 空の文脈行は実物（git / GitHub）では " "（空白 1 文字）。ここの "" は frame_hunk が許容する形で、
# 実物の " " は tests/what-am-i-doing-case.py の frames（本物の git）が通す


class Frame(unittest.TestCase):
    """変更の枠: 今の姿に帯を入れる。今の行は 1 文字も変えない。"""

    def setUp(self):
        self.fr = cm.framed_diff(FRAME_DIFF)

    def test_bands_wrap_changes_and_old_lines_become_aligned_comments(self):
        block = self.fr["src/a.py"]["blocks"][0]
        self.assertEqual(block[0], "def f():")                       # 今の行はそのまま
        self.assertTrue(block[2].startswith("    # ┏━━ 追加 ━━"))     # y = 2 の前に帯（字下げは区間の最浅）
        self.assertEqual(block[3], "    y = 2")
        self.assertTrue(block[4].startswith("    # ┗━━━"))
        i = block.index("      b, c):")
        self.assertEqual(block[i - 1], "#│    b):")                 # 前の行は #│ の印で桁を揃えて薄く
        self.assertTrue(block[i - 2].startswith("    # ┏━━ 変更 ━━"))    # 帯は区間で一番浅い行に合わせる
        self.assertEqual(block[i + 1], "    z = 3")                  # 隣り合う変更は同じ枠（間 0 行）
        self.assertTrue(block[i + 2].startswith("    # ┗━━━"))
        self.assertEqual({cm.width(l) for l in block if "━" in l or "┅" in l}, {78})  # 帯の幅は 78 に揃う

    def test_old_line_mark_differs_from_added_comment_line(self):
        """前の行の印は専用——コメント記号だけだと、今足したコメント行と同じ字面になり読み方が 2 つになる。"""
        out = cm.frame_hunk("a.py", [" import os", "-x = 1", "+# x = 1", "+x = 2", " z = 3"])
        self.assertEqual(out[2], "#│ x = 1")                        # 前
        self.assertEqual(out[3], "# x = 1")                         # 今足したコメント行（そのまま）
        self.assertNotEqual(out[2], out[3])
        shallow = cm.old_line(("#", ""), "  foo")                   # 字下げが印より浅い行は 1 桁だけずれる
        self.assertEqual(shallow, "#│ foo")

    def test_delete_only_and_other_languages(self):
        h = self.fr["src/a.py"]["blocks"][1]
        self.assertTrue(h[1].startswith("    # ┏━━ 変更 ━━"))
        self.assertEqual(h[2], "#│  old = 1")
        self.assertEqual(h[3], "    new = 1")
        ts = self.fr["web/app.ts"]["blocks"][0]
        self.assertTrue(ts[1].startswith("// ┏━━ 変更 ━━"))
        self.assertEqual(ts[2], "//│ const b = 2;")
        self.assertEqual(ts[3], "const b = 3;")
        deleted = cm.frame_hunk("x.py", [" a", "-b", " c"])
        self.assertTrue(deleted[1].startswith("# ┏━━ 削除 ━━"))
        self.assertEqual(deleted[2], "#│ b")
        md = self.fr["docs/d.md"]["blocks"][0]                       # markup は <!-- --> で前後を挟む
        self.assertTrue(md[1].startswith("<!-- ┏━━ 変更 ━━") and md[1].endswith(" -->"))
        self.assertEqual(cm.width(md[1]), 78)
        self.assertEqual(md[2], "<!--│ old text -->")
        css = cm.frame_hunk("a.css", [" a {", "-  color: red;", "+  color: blue;", " }"])
        self.assertTrue(css[1].startswith("  /* ┏━━ 変更 ━━") and css[1].endswith(" */"))
        self.assertEqual(css[2], "/*│ color: red; */")
        go = cm.frame_hunk("m.go", [" func f() {", "-\tx := 1", "+\tx := 2", " }"])
        self.assertTrue(go[1].startswith("    // ┏━━ 変更 ━━"))       # 帯の字下げの tab は空白 4 つ
        self.assertEqual(cm.width(go[1].expandtabs(8)), 78)
        self.assertEqual(go[2], "//│ \tx := 1")

    def test_new_file_has_no_bands_and_gaps_between_hunks(self):
        new = self.fr["docs/new.md"]
        self.assertTrue(new["new"])
        self.assertEqual(new["blocks"], [["# t", "body"]])
        self.assertEqual(self.fr["src/a.py"]["gaps"], [42 - 12])    # 2 つ目の hunk までの行数

    def test_join_caps_at_function_boundary_and_separates_hunks(self):
        rows = cm.join_frames("src/a.py", self.fr["src/a.py"], cap=None)
        texts = [t for _, t in rows]
        self.assertTrue(any(t.startswith("# ┅┅┅ 30 行省略") for t in texts))  # hunk の間は点線
        capped = cm.join_frames("src/a.py", self.fr["src/a.py"], cap=5)
        self.assertEqual(capped[-1][0], "")                          # 関数の切れ目で止めて申告
        self.assertIn("--frame src/a.py", capped[-1][1])
        self.assertTrue(all(p == "| " for p, _ in capped[:-1]))
        self.assertEqual(capped[0][1], "def f():")                   # cap を超えても最初の関数は必ず出る
        self.assertIn("残り 1 関数 6 行", capped[-1][1])                # 申告の数字は残りの関数数と行数

    def test_long_function_folds_unchanged_runs_and_caps_old_lines(self):
        body = [" line%d" % i for i in range(60)] + ["-o", "+n"] + [" tail%d" % i for i in range(60)]
        out = cm.frame_hunk("x.py", body)
        folds = [l for l in out if "行省略" in l]
        self.assertEqual(len(folds), 2)                              # 前後の長い区間を畳む
        self.assertIn("line59", "\n".join(out))                      # 変更の前 FOLD_KEEP 行は残る
        self.assertNotIn("line20", "\n".join(out))
        many = cm.frame_hunk("x.py", ["-o%d" % i for i in range(20)] + ["+n"])
        self.assertTrue(any("前の行 17 行省略" in l for l in many))
        self.assertEqual(sum(1 for l in many if l.startswith("#│ o")), 3)

    def test_gap_rule_splits_far_changes(self):
        near = cm.frame_hunk("x.py", ["+a", " 1", " 2", " 3", "+b"])
        far = cm.frame_hunk("x.py", ["+a", " 1", " 2", " 3", " 4", "+b"])
        self.assertEqual(sum(1 for l in near if "┏" in l), 1)
        self.assertIn("追加（変わっていない 3 行を挟む）", near[0])          # 挟まった行の数を帯に書く
        self.assertEqual(sum(1 for l in far if "┏" in l), 2)
        self.assertNotIn("挟む", far[0])


if __name__ == "__main__":
    unittest.main(verbosity=1)
