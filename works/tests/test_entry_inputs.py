"""線 A の入口の入力（.shared/core/entry.py の check_inputs）のうち、変更（base の版）から入る入口の検査。

本線の既定の入口（依頼を積まない通常の run）と同じく、依頼が無くても変更を名指せば受け、差分の根は base と HEAD の
merge-base（GitHub の PR の three-dot と同じ）に解く。盤面は作らない。種の git は gitkit の型の写し。
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
        """依頼無し・base だけ → 拒まず、依頼は空、base_rev は base と HEAD の merge-base"""
        try:
            got = entry.check_inputs({"request": "", "base": "base"}, self.repo)
        except entry.InputRefused as e:
            self.fail(f"変更だけの入口を拒んだ: {e}")
        self.assertEqual(got["items"], [])
        self.assertEqual(got["base_rev"], self.fork)

    def test_request_and_change_resolves_base(self):
        """依頼と base の両方 → 依頼は読み、base_rev は merge-base（HEAD に固定しない）"""
        got = entry.check_inputs({"request": str(SEED / "request_ok.json"), "base": "base"}, self.repo)
        self.assertEqual(len(got["items"]), 2)
        self.assertEqual(got.get("base_rev"), self.fork)

    def test_needs_request_or_change_and_not_both_changes(self):
        """依頼も変更も無い・base と pr の両方・引けない base は拒む（盤面の前に 1 行）"""
        for raw, words in (({"request": ""}, "少なくとも 1 つ"), ({"request": "", "base": "base", "pr": "1"}, "両方"),
                           ({"request": "", "base": "no-such-branch"}, "引けない"), ({"request": "", "pr": "x"}, "番号でない")):
            with self.subTest(raw):
                with self.assertRaises(entry.InputRefused) as cm:
                    entry.check_inputs(raw, self.repo)
                self.assertIn(words, str(cm.exception))
                self.assertNotIn("\n", str(cm.exception))

    def fake_gh(self, doc: dict) -> None:
        """PATH の頭に、gh pr view の返りを doc にする偽の gh を置く（受けた引数を calls に書く）"""
        import json
        import os
        from unittest import mock
        bin_ = pathlib.Path(self._tmp.name) / "bin"
        bin_.mkdir(exist_ok=True)
        self.calls = bin_ / "calls"
        gh = bin_ / "gh"
        gh.write_text(f"#!/bin/sh\necho \"$@\" >> '{self.calls}'\ncat <<'EOF'\n{json.dumps(doc, ensure_ascii=False)}\nEOF\n",
                      encoding="utf-8")
        gh.chmod(0o755)
        env = mock.patch.dict("os.environ", {"PATH": f"{bin_}{os.pathsep}{os.environ.get('PATH', '')}"})
        env.start()
        self.addCleanup(env.stop)

    def test_pr_uses_github_base_oid_and_carries_description(self):
        """pr → gh pr view を 1 回読むだけ。差分の根は baseRefOid と HEAD の merge-base（ローカルの枝の名前で引かない）、
        PR の題と本文は change.text に"""
        head = git(self.repo, "rev-parse", "HEAD")
        self.fake_gh({"baseRefOid": self.fork, "headRefOid": head, "title": "題", "body": "本文"})
        got = entry.check_inputs({"request": "", "pr": "7"}, self.repo)
        self.assertEqual(got["base_rev"], self.fork)
        self.assertEqual(got["change"], {"from": "pr", "name": "7", "text": "題\n\n本文"})
        self.assertEqual(self.calls.read_text(encoding="utf-8").split(), ["pr", "view", "7", "--json", entry.PR_FIELDS])

    def test_pr_refused_when_head_differs_or_base_missing(self):
        """PR の head が対象の HEAD と違う・base の版が対象に無い → 拒む（別の版を黙って見ない）"""
        head = git(self.repo, "rev-parse", "HEAD")
        for doc, words in (({"baseRefOid": self.fork, "headRefOid": self.fork}, "HEAD"),
                           ({"baseRefOid": "1" * 40, "headRefOid": head}, "対象に無い")):
            with self.subTest(words):
                self.fake_gh(doc)
                with self.assertRaises(entry.InputRefused) as cm:
                    entry.check_inputs({"request": "", "pr": "7"}, self.repo)
                self.assertIn(words, str(cm.exception))


if __name__ == "__main__":
    unittest.main()
