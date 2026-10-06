"""単位の worktree（.shared/core/unittrees.py）の検査。種の git は gitkit の型の写し。

縛る事:
- 2 つの単位が別のファイルを直す → 両方が run の作業ツリーに当たる
- 2 つの単位が同じ行を直す → 2 つ目は当たらず (False, 理由)、作業ツリーは 1 つ目を当てたまま
- run の作業ツリーの未 commit の直し（tracked の変更・untracked の新しいファイル）が単位の worktree に見える
- どの口も本物の index・HEAD・枝を動かさない
- index を切ったのと同じ秒に同じ大きさで書き換えたファイルも、次の秒に取った差分に入る（git の racy な行の読み直し）
- remove・sweep が worktree と守りの参照を片付け、同じリポジトリのほかの作業ツリーの単位には触らない
- objects（新しい object の一時の置き場）を渡せば、共通の .git が書けなくても diff・apply が回る（役の sandbox の中の当てる口）
- applied は差分が既に当たっているか（逆向きに当たるか）を作業ツリーを変えずに言う
- union の中のファイルで両方が同じ所（末尾）に行を足しただけの食い違いは、作業ツリーの側の行の後に patch の側の行を置いて
  当たる（unioned に積む）。行を変えた塊・union の外のファイルは今どおり当たらず、作業ツリーは前のまま
"""
import pathlib
import shutil
import sys
import tempfile
import time
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / ".shared" / "core"))

import unittrees  # noqa: E402
from gitkit import committed_copy, git  # noqa: E402

SEED = {"a.txt": "a1\na2\na3\n", "b.txt": "b1\nb2\nb3\n", "bin.dat": None, ".gitignore": "ignored.log\n"}
_SRC = None


def setUpModule():
    global _SRC
    _SRC = pathlib.Path(tempfile.mkdtemp(prefix="works-unittrees-src-"))
    for rel, text in SEED.items():
        p = _SRC / rel
        if text is None:
            p.write_bytes(bytes(range(256)))
        else:
            p.write_text(text, encoding="utf-8")


def tearDownModule():
    shutil.rmtree(_SRC, ignore_errors=True)


class UnitTrees(unittest.TestCase):
    def setUp(self):
        self.home = pathlib.Path(tempfile.mkdtemp(prefix="works-unittrees-"))
        self.addCleanup(shutil.rmtree, self.home, True)
        self.repo = self.home / "run"
        committed_copy(self.repo, _SRC)
        self.places = self.home / "units"

    def real_state(self):
        """本物の index・HEAD・枝（動いていないことを見る）"""
        return (git(self.repo, "rev-parse", "HEAD"), git(self.repo, "symbolic-ref", "-q", "HEAD"),
                git(self.repo, "ls-files", "-s"), git(self.repo, "diff", "--cached", "--name-only"))

    def unit(self, base, name, edits):
        path = unittrees.add(self.repo, base, self.places / name)
        for rel, text in edits.items():
            (path / rel).write_text(text, encoding="utf-8")
        return path, unittrees.diff(path, base)

    def test_two_units_different_files_both_apply(self):
        state = self.real_state()
        base = unittrees.snapshot(self.repo)
        _, p1 = self.unit(base, "u1", {"a.txt": "a1\nA2\na3\n"})
        _, p2 = self.unit(base, "u2", {"b.txt": "b1\nb2\nB3\n", "new.txt": "new\n"})
        self.assertEqual(unittrees.apply(self.repo, p1), (True, ""))
        self.assertEqual(unittrees.apply(self.repo, p2), (True, ""))
        self.assertEqual((self.repo / "a.txt").read_text(), "a1\nA2\na3\n")
        self.assertEqual((self.repo / "b.txt").read_text(), "b1\nb2\nB3\n")
        self.assertEqual((self.repo / "new.txt").read_text(), "new\n")
        self.assertEqual(self.real_state(), state)

    def test_same_second_same_size_edit_reaches_diff_next_second(self):
        """index の写しが mtime を今にすると、git は同じ秒に書いたファイルを stat で信じて直しを落とした（1 回に 1 度ほどの赤）"""
        base = unittrees.snapshot(self.repo)
        path, _ = self.unit(base, "u1", {"a.txt": "a1\nA2\na3\n"})
        wrote = int((path / "a.txt").stat().st_mtime)
        while int(time.time()) <= wrote:   # 書いた秒を跨いでから差分を取る（長くて 1 秒）
            time.sleep(0.05)
        self.assertIn("+A2", unittrees.diff(path, base))

    def test_same_line_second_does_not_apply_and_tree_keeps_first(self):
        state = self.real_state()
        base = unittrees.snapshot(self.repo)
        _, p1 = self.unit(base, "u1", {"a.txt": "a1\nX\na3\n"})
        _, p2 = self.unit(base, "u2", {"a.txt": "a1\nY\na3\n", "b.txt": "b1\nb2\nB3\n"})
        self.assertEqual(unittrees.apply(self.repo, p1), (True, ""))
        ok, why = unittrees.apply(self.repo, p2)
        self.assertFalse(ok)
        self.assertTrue(why)
        self.assertEqual((self.repo / "a.txt").read_text(), "a1\nX\na3\n")
        self.assertEqual((self.repo / "b.txt").read_text(), "b1\nb2\nb3\n")   # 全部か無し
        self.assertNotIn("<<<<<<<", (self.repo / "a.txt").read_text())
        self.assertEqual(self.real_state(), state)

    def test_insert_only_conflict_in_a_union_file_is_merged_in_order(self):
        state = self.real_state()
        base = unittrees.snapshot(self.repo)
        _, p1 = self.unit(base, "u1", {"a.txt": "a1\na2\na3\n\nclass B:\n    pass\n"})
        _, p2 = self.unit(base, "u2", {"a.txt": "a1\na2\na3\n\nclass C:\n    pass\n", "b.txt": "b1\nb2\nB3\n"})
        self.assertEqual(unittrees.apply(self.repo, p1), (True, ""))
        self.assertFalse(unittrees.apply(self.repo, p2)[0])   # union を渡さなければ今どおり当たらない
        got = []
        self.assertEqual(unittrees.apply(self.repo, p2, union=["a.txt"], unioned=got), (True, ""))
        self.assertEqual((self.repo / "a.txt").read_text(), "a1\na2\na3\n\nclass B:\n    pass\n\nclass C:\n    pass\n")
        self.assertEqual((self.repo / "b.txt").read_text(), "b1\nb2\nB3\n")
        self.assertEqual(got, ["a.txt"])
        self.assertEqual(self.real_state(), state)

    def test_union_refuses_a_conflict_that_changed_lines(self):
        base = unittrees.snapshot(self.repo)
        _, p1 = self.unit(base, "u1", {"a.txt": "a1\nX\na3\n"})
        _, p2 = self.unit(base, "u2", {"a.txt": "a1\nY\na3\n"})
        self.assertEqual(unittrees.apply(self.repo, p1), (True, ""))
        got = []
        ok, why = unittrees.apply(self.repo, p2, union=["a.txt"], unioned=got)
        self.assertFalse(ok)
        self.assertTrue(why)
        self.assertEqual((self.repo / "a.txt").read_text(), "a1\nX\na3\n")
        self.assertEqual(got, [])

    def test_union_refuses_files_outside_the_list(self):
        base = unittrees.snapshot(self.repo)
        _, p1 = self.unit(base, "u1", {"a.txt": "a1\na2\na3\nB\n", "b.txt": "b1\nb2\nb3\nB\n"})
        _, p2 = self.unit(base, "u2", {"a.txt": "a1\na2\na3\nC\n", "b.txt": "b1\nb2\nb3\nC\n"})
        self.assertEqual(unittrees.apply(self.repo, p1), (True, ""))
        self.assertFalse(unittrees.apply(self.repo, p2, union=["a.txt"])[0])   # b.txt は並びの外
        self.assertEqual((self.repo / "a.txt").read_text(), "a1\na2\na3\nB\n")

    def test_union_with_scratch_objects_writes_nothing_in_git(self):
        base = unittrees.snapshot(self.repo)
        _, p1 = self.unit(base, "u1", {"a.txt": "a1\na2\na3\nB\n"})
        tree2 = unittrees.add(self.repo, base, self.places / "u2")
        (tree2 / "a.txt").write_text("a1\na2\na3\nC\n", encoding="utf-8")
        self.assertEqual(unittrees.apply(self.repo, p1), (True, ""))
        common = pathlib.Path(git(self.repo, "rev-parse", "--path-format=absolute", "--git-common-dir")) / "objects"
        before = sorted(str(x) for x in common.rglob("*"))
        with tempfile.TemporaryDirectory() as objects:
            p2 = unittrees.diff(tree2, base, objects=objects)
            self.assertEqual(unittrees.apply(self.repo, p2, objects=objects, union=["a.txt"]), (True, ""))
        self.assertEqual(sorted(str(x) for x in common.rglob("*")), before)
        self.assertEqual((self.repo / "a.txt").read_text(), "a1\na2\na3\nB\nC\n")

    def test_uncommitted_run_edits_visible_in_unit(self):
        (self.repo / "a.txt").write_text("a1\nrun\na3\n", encoding="utf-8")
        (self.repo / "fresh.txt").write_text("untracked\n", encoding="utf-8")
        (self.repo / "ignored.log").write_text("noise\n", encoding="utf-8")
        (self.repo / "bin.dat").unlink()
        state = self.real_state()
        base = unittrees.snapshot(self.repo)
        self.assertEqual(git(self.repo, "rev-parse", f"{base}^"), state[0])   # 親は HEAD
        path, _ = self.unit(base, "u1", {})
        self.assertEqual((path / "a.txt").read_text(), "a1\nrun\na3\n")
        self.assertEqual((path / "fresh.txt").read_text(), "untracked\n")
        self.assertFalse((path / "ignored.log").exists())
        self.assertFalse((path / "bin.dat").exists())
        self.assertEqual(self.real_state(), state)
        self.assertIn("?? fresh.txt", git(self.repo, "status", "--porcelain"))   # untracked のまま

    def test_untracked_and_binary_in_unit_diff(self):
        base = unittrees.snapshot(self.repo)
        path, _ = self.unit(base, "u1", {"fresh.txt": "unit new\n"})
        (path / "bin.dat").write_bytes(bytes(reversed(range(256))))
        (path / "b.txt").unlink()
        patch = unittrees.diff(path, base)
        self.assertIn("GIT binary patch", patch)
        self.assertEqual(unittrees.apply(self.repo, patch), (True, ""))
        self.assertEqual((self.repo / "fresh.txt").read_text(), "unit new\n")
        self.assertEqual((self.repo / "bin.dat").read_bytes(), bytes(reversed(range(256))))
        self.assertFalse((self.repo / "b.txt").exists())

    def test_empty_patch_is_ok(self):
        base = unittrees.snapshot(self.repo)
        path, patch = self.unit(base, "u1", {})
        self.assertEqual(patch, "")
        self.assertEqual(unittrees.apply(self.repo, patch), (True, ""))

    def test_remove_and_sweep_clean_only_this_tree(self):
        base = unittrees.snapshot(self.repo)
        p1, _ = self.unit(base, "u1", {})
        p2, _ = self.unit(base, "u2", {})
        other = self.home / "other-run"
        git(self.repo, "worktree", "add", "--detach", "-q", str(other), "HEAD")
        obase = unittrees.snapshot(other)
        op = unittrees.add(other, obase, self.places / "o1")
        unittrees.remove(self.repo, p1)
        self.assertFalse(p1.exists())
        mine = f"{unittrees.REF_ROOT}/{unittrees._mark(self.repo)}/"
        refs = git(self.repo, "for-each-ref", "--format=%(refname)", mine).splitlines()
        self.assertEqual(len(refs), 2)   # base と u2
        shutil.rmtree(p2)   # 止まった run の残り（置き場だけ消えた）も片付く
        unittrees.sweep(self.repo)
        self.assertEqual(git(self.repo, "for-each-ref", "--format=%(refname)", mine), "")
        listed = {str(pathlib.Path(ln[len("worktree "):]).resolve())
                  for ln in git(self.repo, "worktree", "list", "--porcelain").splitlines()
                  if ln.startswith("worktree ")}
        self.assertIn(str(self.repo.resolve()), listed)   # 切り出しが空振りしていない
        self.assertNotIn(str(p2.resolve()), listed)
        self.assertTrue(op.exists())   # ほかの作業ツリーの単位は残る
        self.assertNotEqual(git(other, "for-each-ref", "--format=%(refname)", f"{unittrees.REF_ROOT}/"), "")
        self.assertEqual(sorted(unittrees.sweep(other)), sorted([str(op.resolve())]))
        self.assertFalse(op.exists())

    def test_diff_and_apply_with_scratch_objects_write_nothing_in_git(self):
        base = unittrees.snapshot(self.repo)
        path = unittrees.add(self.repo, base, self.places / "u1")
        (path / "a.txt").write_text("a1\nA2\na3\n", encoding="utf-8")
        (path / "fresh.txt").write_text("new\n", encoding="utf-8")
        common = pathlib.Path(git(self.repo, "rev-parse", "--path-format=absolute", "--git-common-dir"))
        dirs = [common, *[d for d in common.rglob("*") if d.is_dir()]]
        before = sorted(str(f) for f in common.rglob("*"))
        for d in dirs:
            d.chmod(0o555)
        self.addCleanup(lambda: [d.chmod(0o755) for d in dirs])
        scratch = self.home / "scratch"
        scratch.mkdir()
        patch = unittrees.diff(path, base, objects=str(scratch))
        self.assertIn("+A2", patch)
        self.assertEqual(unittrees.apply(self.repo, patch, objects=str(scratch)), (True, ""))
        self.assertEqual((self.repo / "a.txt").read_text(), "a1\nA2\na3\n")
        self.assertEqual((self.repo / "fresh.txt").read_text(), "new\n")
        self.assertEqual(sorted(str(f) for f in common.rglob("*")), before, "共通の .git に何も足さない")

    def test_applied_says_whether_the_patch_is_already_in(self):
        base = unittrees.snapshot(self.repo)
        _, patch = self.unit(base, "u1", {"a.txt": "a1\nA2\na3\n", "fresh.txt": "new\n"})
        self.assertFalse(unittrees.applied(self.repo, patch))
        self.assertEqual(unittrees.apply(self.repo, patch), (True, ""))
        self.assertTrue(unittrees.applied(self.repo, patch))
        self.assertTrue(unittrees.applied(self.repo, ""))
        self.assertEqual((self.repo / "a.txt").read_text(), "a1\nA2\na3\n", "作業ツリーを変えない")

    def test_sweep_clears_a_tree_whose_git_pointer_was_rewritten(self):
        """役が単位の worktree の .git を書き換えても（git の worktree remove は断る）、片付けは消して登録を外す"""
        base = unittrees.snapshot(self.repo)
        path, _ = self.unit(base, "u1", {})
        (path / ".git").write_text("gitdir: /elsewhere\n", encoding="utf-8")
        self.assertEqual(unittrees.sweep(self.repo), [str(path.resolve())])
        self.assertFalse(path.exists())
        self.assertNotIn(str(path.resolve()), git(self.repo, "worktree", "list", "--porcelain"))


if __name__ == "__main__":
    unittest.main()
