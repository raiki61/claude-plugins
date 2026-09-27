"""試験の道具 tests/gitkit.py（種の git を、1 回だけ作った型の写しで配る）の検査。

- 写しは型と同じ commit を持ち、写した直後の作業ツリーは、index の stat を信じる plumbing（diff-files・diff-index）から
  見ても綺麗（git init から作った時と同じ）。写した index は型のファイルの stat を持つので、何もしなければ全部が変わって見える
"""
import pathlib
import subprocess
import tempfile
import unittest

from gitkit import committed_copy, git

SEED = pathlib.Path(__file__).resolve().parents[1] / "dev" / "target-seed"


class TestCommittedCopy(unittest.TestCase):
    def test_copy_is_clean_for_plumbing(self):
        with tempfile.TemporaryDirectory() as tmp:
            for name in ("first", "second"):   # 1 本目は型を作ってから写し、2 本目は型を写すだけ
                with self.subTest(name):
                    repo = pathlib.Path(tmp) / name
                    head = committed_copy(repo, SEED)
                    self.assertEqual(git(repo, "rev-parse", "HEAD"), head)
                    for cmd in (["diff-files", "--quiet"], ["diff-index", "--quiet", "HEAD"]):
                        r = subprocess.run(["git", "-C", str(repo), *cmd], capture_output=True, text=True, encoding="utf-8")
                        self.assertEqual(r.returncode, 0, f"git {' '.join(cmd)} が写した直後に差分を見た: {r.stdout}")


if __name__ == "__main__":
    unittest.main()
