"""線 A の入口の入力（.shared/core/entry.py の check_inputs・build_input と board.diff_of）の検査。

どの入口（依頼のファイル・base の版・PR）も 1 つの入力の形（差分の根・差分・依頼の行・PR の添え物）に揃える。差分の根は
base と HEAD の merge-base（GitHub の PR の three-dot と同じ）、名指しが無ければ HEAD。差分が空で依頼の行も空なら拒む
（盤面を作る前）。種の git は gitkit の型の写し。
"""
import pathlib
import sys
import tempfile
import unittest

TESTS = pathlib.Path(__file__).resolve().parent
ROOT = TESTS.parent
CORE = ROOT / ".shared" / "core"
sys.dont_write_bytecode = True
sys.path.insert(0, str(CORE))
sys.path.insert(0, str(TESTS))

import board  # noqa: E402
import entry  # noqa: E402
from gitkit import committed_copy, git  # noqa: E402

SEED = ROOT / "dev" / "target-seed"


class ChangeInputsCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.repo = pathlib.Path(self._tmp.name) / "repo"
        self.fork = committed_copy(self.repo, SEED)
        git(self.repo, "branch", "base")
        with (self.repo / "stats.py").open("a", encoding="utf-8") as f:
            f.write("\n# 変更\n")
        git(self.repo, "commit", "-q", "-am", "change")

    def tearDown(self):
        self._tmp.cleanup()

    def test_change_only_accepted_with_merge_base(self):
        """依頼無し・base だけ → 拒まず、依頼は空、base_rev は base と HEAD の merge-base、base は出どころの名札つき・pr は None"""
        try:
            got = entry.check_inputs({"request": "", "base": "base"}, self.repo)
        except entry.InputRefused as e:
            self.fail(f"変更だけの入口を拒んだ: {e}")
        self.assertEqual(got["items"], [])
        self.assertEqual(got["base_rev"], self.fork)
        self.assertEqual(got["base"], {"rev": self.fork, "from": "base", "name": "base"})
        self.assertIsNone(got["pr"])
        self.assertNotIn("change", got)

    def test_request_and_change_resolves_base(self):
        """依頼と base の両方 → 依頼は読み、base_rev は merge-base（HEAD に固定しない）"""
        got = entry.check_inputs({"request": str(SEED / "request_ok.json"), "base": "base"}, self.repo)
        self.assertEqual(len(got["items"]), 2)
        self.assertEqual(got.get("base_rev"), self.fork)
        self.assertEqual(got["base"]["rev"], self.fork)

    def test_needs_request_or_change_and_not_both_changes(self):
        """依頼も差分も無い・base と pr の両方・引けない base は拒む（盤面の前に 1 行）"""
        for raw, words in (({"request": ""}, entry.EMPTY_REFUSED), ({"request": "", "base": "base", "pr": "1"}, "両方"),
                           ({"request": "", "base": "no-such-branch"}, "引けない"), ({"request": "", "pr": "x"}, "番号でない")):
            with self.subTest(raw):
                with self.assertRaises(entry.InputRefused) as cm:
                    entry.check_inputs(raw, self.repo)
                self.assertIn(words, str(cm.exception))
                self.assertNotIn("\n", str(cm.exception))

    def test_empty_diff_and_no_requests_refused(self):
        """--base HEAD だけ（差分が空で依頼の行も空）→ EMPTY_REFUSED で始まる 1 行で拒む。盤面の置き場を作らない"""
        board = pathlib.Path(self._tmp.name) / "board"
        with self.assertRaises(entry.InputRefused) as cm:
            entry.start(board, self.repo, {"request": "", "base": "HEAD"}, run_id="t")
        self.assertTrue(str(cm.exception).startswith(entry.EMPTY_REFUSED), str(cm.exception))
        self.assertFalse(board.exists())

    def test_diff_of_clean_head_is_empty(self):
        """綺麗な作業ツリーを HEAD から測る → 空・0 ファイル"""
        got = board.diff_of(self.repo, git(self.repo, "rev-parse", "HEAD"))
        self.assertEqual((got["empty"], got["files"]), (True, 0))
        self.assertIsInstance(got["stat"], str)

    def test_diff_of_counts_untracked(self):
        """未追跡の新規ファイル 1 本は数える。.gitignore に当たる物は数えない（写しの核の _worktree_tree と同じ測り方）"""
        head = git(self.repo, "rev-parse", "HEAD")
        (self.repo / ".gitignore").write_text("ignored.txt\n", encoding="utf-8")
        git(self.repo, "add", ".gitignore")
        git(self.repo, "commit", "-q", "-m", "ignore")
        head = git(self.repo, "rev-parse", "HEAD")
        (self.repo / "ignored.txt").write_text("x\n", encoding="utf-8")
        self.assertTrue(board.diff_of(self.repo, head)["empty"])
        (self.repo / "new.py").write_text("x = 1\n", encoding="utf-8")
        got = board.diff_of(self.repo, head)
        self.assertEqual((got["empty"], got["files"]), (False, 1))
        self.assertIn("1 file", got["stat"])

    def test_diff_of_refuses_unknown_rev(self):
        """引けない版 → Reject（黙って空と言わない）"""
        with self.assertRaises(entry.Reject):
            board.diff_of(self.repo, "1" * 40)

    def test_build_input_from_each_entry(self):
        """入口ごとに 1 つの形: 依頼だけ → base は HEAD（from head）・差分は空、--base → from base・差分 1 ファイル以上、
        --pr → pr に番号と題（本文は控えに写さない）。後ろの段が読む欄はどの入口でも同じ鍵"""
        head = git(self.repo, "rev-parse", "HEAD")
        req = str(SEED / "request_ok.json")
        only = entry.build_input(entry.check_inputs({"request": req}, self.repo), self.repo)
        self.assertEqual(only["base"], {"rev": head, "from": "head", "name": ""})
        self.assertTrue(only["diff"]["empty"])
        self.assertEqual((only["requests"], only["request_file"], only["pr"], only["spec"]),
                         (2, str(pathlib.Path(req).resolve()), None, False))
        self.assertEqual(only["head_rev"], head)
        based = entry.build_input(entry.check_inputs({"request": "", "base": "base"}, self.repo), self.repo)
        self.assertEqual(based["base"]["from"], "base")
        self.assertGreaterEqual(based["diff"]["files"], 1)
        self.assertEqual(based["requests"], 0)
        doc = {"baseRefOid": self.fork, "headRefOid": head, "title": "題", "body": "本文"}
        pr = entry.build_input(entry.check_inputs({"request": "", "pr": "7"}, self.repo, reads=self.reads(doc)), self.repo)
        self.assertEqual(pr["pr"], {"number": "7", "title": "題"})
        self.assertEqual(pr["base"], {"rev": self.fork, "from": "pr", "name": "7"})
        self.assertEqual(set(only), set(based))
        self.assertEqual(set(only), set(pr))

    def test_request_text_carries_request_and_pr(self):
        """依頼のファイルと PR の両方 → 盤面の依頼の文は両方の見出しと本文を持つ（依頼の文が在っても PR の文を捨てない）。
        片方だけなら今の文のまま（固定材料の依頼の sha256 を変えない）"""
        head = git(self.repo, "rev-parse", "HEAD")
        doc = {"baseRefOid": self.fork, "headRefOid": head, "title": "題", "body": "本文"}
        req = str(SEED / "request_ok.json")
        both = entry._request_text(entry.check_inputs({"request": req, "pr": "7"}, self.repo, reads=self.reads(doc)))
        self.assertIn("## 依頼", both)
        self.assertIn("## PR #7 の題と本文", both)
        self.assertIn("題\n\n本文", both)
        self.assertIn((SEED / "request_ok.json").read_text(encoding="utf-8").strip(), both)
        only = entry.check_inputs({"request": req}, self.repo)
        self.assertEqual(entry._request_text(only), only["request_text"])
        pr_only = entry.check_inputs({"request": "", "pr": "7"}, self.repo, reads=self.reads(doc))
        self.assertEqual(entry._request_text(pr_only), "題\n\n本文")
        base_only = entry.check_inputs({"request": "", "base": "base"}, self.repo)
        self.assertEqual(entry._request_text(base_only), "変更（base base）の審査")

    @staticmethod
    def reads(doc: dict) -> dict:
        """start が run の中で読んだ読み出し（ghreads.read_named の返りの形）に PR #7 として doc を置いた物"""
        return {"version": 1, "pr": {"7": doc}, "issue": {}}

    def test_pr_uses_github_base_oid_and_carries_description(self):
        """pr → run の中で読んだ読み出しの base・head を使う。差分の根は baseRefOid と HEAD の merge-base（ローカルの枝の名前で
        引かない）、PR の題と本文は change.text に"""
        head = git(self.repo, "rev-parse", "HEAD")
        got = entry.check_inputs({"request": "", "pr": "7"}, self.repo,
                                 reads=self.reads({"baseRefOid": self.fork, "headRefOid": head, "title": "題", "body": "本文"}))
        self.assertEqual(got["base_rev"], self.fork)
        self.assertEqual(got["base"], {"rev": self.fork, "from": "pr", "name": "7"})
        self.assertEqual(got["pr"], {"number": "7", "title": "題", "body": "本文"})

    def test_pr_refused_when_head_differs_or_base_missing(self):
        """PR の head が対象の HEAD と違う・base の版が対象に無い → 拒む（別の版を黙って見ない）"""
        head = git(self.repo, "rev-parse", "HEAD")
        for doc, words in (({"baseRefOid": self.fork, "headRefOid": self.fork}, "HEAD"),
                           ({"baseRefOid": "1" * 40, "headRefOid": head}, "対象に無い")):
            with self.subTest(words):
                with self.assertRaises(entry.InputRefused) as cm:
                    entry.check_inputs({"request": "", "pr": "7"}, self.repo, reads=self.reads(doc))
                self.assertIn(words, str(cm.exception))


if __name__ == "__main__":
    unittest.main()
