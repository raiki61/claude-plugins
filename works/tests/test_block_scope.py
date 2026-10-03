"""部品の置き場（依頼 239）の適合: 同じブロックを 1 run で 2 度 include しても、2 度目が 1 度目のファイルを上書きしない。

線 darkfactory を本物のスクリプトで回し（tests/scriptline.py。役と関所だけを見本で置き換える）、線の最上段の include の節の
前後で盤面の全部のファイルの中身（sha256）を控える。1 度目の窓（planning・fixing）で作った・変えたファイルのうち、共有の記録
（core が書き、どの scope の窓でも変わってよい物）の外の物が、2 度目の窓（replanning・refitting）の前後で中身が違えば上書き。
今は置き場を分けていないので落ちる（0.2.20 で refitting が fixing の fix-unit-rows.json・r1/brief-1.md・r1/briefs.json・
r1/changes.json・r1/fix-gates.json・r1/rule-tree.json を上書きする。replanning は planning の物を上書きしない）。落ちた時の文が
上書きしたファイルを全部名指すので、置き場の分けが進むにつれ一覧が縮むのを見られる。Task 5 で置き場の分けが効いたら
expectedFailure を外す。
"""
import fnmatch
import hashlib
import pathlib
import sys
import tempfile
import types
import unittest

TESTS = pathlib.Path(__file__).resolve().parent
sys.dont_write_bytecode = True
sys.path.insert(0, str(TESTS))

import linekit  # noqa: E402
import scriptline  # noqa: E402
import test_blk_fix_conflict as fc  # noqa: E402
import test_line_a as TL  # noqa: E402
import test_replan as tr  # noqa: E402
from test_script_contract import line_replies  # noqa: E402

# 共有の記録（Task 1 の M2 の class shared を fnmatch の形で字のまま。where が work の名は周の置き場 r<N>/ の下）。
# Task 9 で scopes の定数に替える
SHARED = ("state.json", "record.json", "trace.jsonl", "out/**", "runs/**", "rounds/**", "STOP", "query-examples.json",
          "prompts/**", "roles/**", "items/**", "policy/**", "lanes/**", "diff-r*.patch", "changed-r*.txt", "*-r*.patch",
          "count-cache.json", "count-budget.json",
          "r*/conflicts.json", "r*/libdocs.json", "r*/libdocs/**")

# 2 度 include するブロックの (1 度目, 2 度目) の節
PAIRS = (("planning", "replanning"), ("fixing", "refitting"))


def snapshot(board: pathlib.Path) -> dict:
    """盤面の下の全部のファイルの相対パス → sha256"""
    board = pathlib.Path(board)
    if not board.is_dir():
        return {}
    return {p.relative_to(board).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(board.rglob("*")) if p.is_file()}


def _shared(path: str, shared) -> bool:
    return any(fnmatch.fnmatchcase(path, pat) for pat in shared)


def clobbered(snaps: dict, first: str, second: str, shared) -> list:
    """first の窓で作った・変えたファイルのうち、共有の記録の外で、second の窓の前後で中身が違う（消えたも含む）物の相対パス。
    名の順"""
    before, after = snaps[(first, "start")], snaps[(first, "done")]
    mine = [p for p, h in after.items() if before.get(p) != h and not _shared(p, shared)]
    s0, s1 = snaps[(second, "start")], snaps[(second, "done")]
    return sorted(p for p in mine if s0.get(p) != s1.get(p))


def scenario(board: pathlib.Path) -> dict:
    """修正役が mean を申し出 → 裁定 fix_plan_item → 案の直し（replanning）→ 関所 replan-gate は continue → 2 回目の修正
    （refitting）→ 報告、の ScriptLine の引数。返答は test_replan の組み手（案の直しの試験と同じ 2 項目の案・控え・2 回目の返答）。
    2 回目の修正役も mean を申し出て裁定の輪を回す（fix_code_as）ので、裁定の輪の作業ファイル（r1/rule-tree.json）も 2 度書かれる"""
    claim = {"unit_key": tr.MEAN, "between": ["stats.py:9", "test_stats.py:9"], "which_is_right": "request",
             "why_both_cannot_hold": "テストは分母 len(xs) - 1 の値を期待しているが、依頼は算術平均を求めている",
             "kind": "unnamed_test_broke"}
    again = {**claim, "why_both_cannot_hold": "2 回目の段でも、直した項目の受け入れのテストの赤の理由が今のコードと合わない"}

    def edit_tree(repo, subs):
        stats = repo / "stats.py"
        text = stats.read_text(encoding="utf-8")
        for old, new in subs.items():
            text = text.replace(old, new)
        stats.write_text(text, encoding="utf-8")

    def add_test(repo):
        """直した項目 1 の受け入れのテスト test_mean_of_two を足す（test_replan の TestSecondPass.fix_mean の、分母を直す手前まで。
        TestLineReplay と同じ借り方）。足してあれば何もしない（出し直しで 2 度足さない）"""
        if "test_mean_of_two" not in (repo / "test_stats.py").read_text(encoding="utf-8"):
            tr.TestSecondPass.fix_mean(types.SimpleNamespace(repo=repo, edit_tree=lambda subs: None))

    calls = {"fix": 0, "fix-ruled": 0}

    def by_pass(key, first, second):
        """役の節 key の作業ツリーの直しを、1 回目の修正の段（fixing）と 2 回目（refitting）で分ける（役の数えは段をまたいで続く）"""
        def edit(repo):
            calls[key] += 1
            (first if calls[key] == 1 else second)(repo)
        return edit

    # 1 回目: 修正役は clamp だけを直して mean を申し出、裁定の後の修正役は控えられる返答だけ（木を変えない）。
    # 2 回目: 修正役は受け入れのテストを足して mean を再び申し出（裁定の輪の前の木の姿 rule-tree.json が 1 回目と違う）、
    # 裁定 fix_code_as の後の修正役が mean の分母を直す
    edits = {"fix": by_pass("fix", lambda repo: edit_tree(repo, fc.CLAMP_FIX), add_test),
             "fix-ruled": by_pass("fix-ruled", lambda repo: None, lambda repo: edit_tree(repo, fc.MEAN_FIX))}

    brief = f"{board / 'r1' / 'brief-1.md'}:1"
    rulings = [{"id": "c1-1", "decision": "fix_plan_item", "text": tr.PLAN_TEXT, "limits": [], "grounds": [brief]},
               {"id": "c1-2", "decision": "fix_code_as", "text": "依頼が正しい。分母を len(xs) に直せ", "limits": ["stats.py:9"]}]
    replies = {**line_replies(),
               "plan": lambda n: {"plan": [tr._item(1), tr.clamp_item()]} if n == 1 else {"plan": [tr.wider_paths()]},
               "plan-review": lambda n: tr.no_faces(),
               "fix": lambda n: tr.only_clamp_reply([claim]) if n == 1 else {**tr.only_mean_reply(), "changes": [],
                                                                             "conflicts": [again]},
               "rule": lambda n: {"rulings": [rulings[min(n, 2) - 1]]},
               "fix-ruled": lambda n: tr.only_clamp_reply() if n == 1 else tr.only_mean_reply(),
               "review": {**TL.CLEAN_DELTA_REVIEW, "checks": []}}
    return dict(replies=replies, edits=edits,
                gates={"replan-gate": {"decision": "continue", "text": "README も触ってよい"}})


class TwoIncludesCase(unittest.TestCase):
    """同じブロックを 1 run で 2 度 include する偽の run（線 darkfactory を本物のスクリプトで回す）。
    修正役が申し出を返し → 裁定 fix_plan_item → 案の直し（replanning）→ 関所 replan-gate は continue → 2 回目の修正（refitting）→ 報告"""

    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory(dir=linekit.work_home())
        tmp = pathlib.Path(cls._tmp.name) / "run"
        board = tmp / "art" / "board"   # ScriptLine の盤面（裁定の根拠の brief の行を返答に書くので、回す前に要る）
        cls.snaps = {}

        def watch(nid, when):
            cls.snaps[(nid, when)] = snapshot(board)

        line = scriptline.ScriptLine(tmp, watch=watch, **scenario(board))
        assert line.board == board, line.board
        cls.got = line.run()

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def test_run_reaches_report(self):
        self.assertTrue(self.got["completed"], self.got["failure"])
        self.assertIn("darkfactory/reporting", self.got["trail"])
        self.assertEqual(self.got["out"]["result"]["outcome"], "fixed")   # 2 度目の修正の段も受け付けを通った（諦めで抜けていない）
        self.assertIn(("refitting", "done"), self.snaps)      # 2 度目の blk-fix まで走った
        self.assertIn(("replanning", "done"), self.snaps)     # 2 度目の blk-plan まで走った

    @unittest.expectedFailure   # Task 5 で外す（置き場の分けが効くまでは rule-tree.json などを上書きする）
    def test_second_include_overwrites_nothing_of_first(self):
        for first, second in PAIRS:
            with self.subTest(first=first, second=second):
                got = clobbered(self.snaps, first, second, SHARED)
                self.assertEqual(got, [], f"{second} が {first} のファイルを上書きした: {', '.join(got)}")


if __name__ == "__main__":
    unittest.main()
