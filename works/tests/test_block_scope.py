"""部品の置き場（依頼 239）の適合: 同じブロックを 1 run で 2 度 include しても、2 度目が 1 度目のファイルを上書きしない。

線 darkfactory を本物のスクリプトで回し（tests/scriptline.py。役と関所だけを見本で置き換える）、線の最上段の include の節の
前後で盤面の全部のファイルの中身（sha256）と mtime を控える。1 度目の窓（planning・fixing）で作った・変えたファイルのうち、
共有の記録（core が書き、どの scope の窓でも変わってよい物）の外の物が、2 度目の窓（replanning・refitting）の前後で中身か
mtime が違えば上書き（同じ中身の書き直しも数える）。
盤面を開く口（entry.open_board）が include の名を scope にして部品の私物を <scope>/ の下に分けるので通る（0.2.20 では refitting が
fixing の fix-unit-rows.json・r1/brief-1.md・r1/briefs.json・r1/changes.json・r1/fix-gates.json・r1/rule-tree.json を上書きした）。
落ちた時の文は上書きしたファイルを全部名指す。
"""
import hashlib
import json
import pathlib
import subprocess
import sys
import tempfile
import types
import unittest

TESTS = pathlib.Path(__file__).resolve().parent
sys.dont_write_bytecode = True
sys.path.insert(0, str(TESTS))

import hermetic  # noqa: E402
import linekit  # noqa: E402
import scriptline  # noqa: E402
import report  # noqa: E402  （scriptline が core を sys.path に足す）
import scopes  # noqa: E402
import test_blk_fix_conflict as fc  # noqa: E402
import test_line_a as TL  # noqa: E402
import test_replan as tr  # noqa: E402
from test_script_contract import line_replies  # noqa: E402
import stopby  # noqa: E402  （止めの理由の住処）

# 共有の記録（core・engine・rules が書き、どの scope の窓でも変わってよい物）は照らしと同じ 1 つの組 scopes.SHARED（"/" で区切った
# 段ごとの fnmatch。* は段をまたがず、末尾の ** だけが下の全部の段に当たるので、r1/ の下の私物が *-r*.patch のような形の陰に隠れない）
SHARED = scopes.SHARED

# 2 度 include するブロックの (1 度目, 2 度目) の節
PAIRS = (("planning", "replanning"), ("fixing", "refitting"))


def snapshot(board: pathlib.Path) -> dict:
    """盤面の下の全部のファイルの相対パス → "<sha256>:<st_mtime_ns>"（同じ中身の書き直しも違いに数える）"""
    board = pathlib.Path(board)
    if not board.is_dir():
        return {}
    return {p.relative_to(board).as_posix(): f"{hashlib.sha256(p.read_bytes()).hexdigest()}:{p.stat().st_mtime_ns}"
            for p in sorted(board.rglob("*")) if p.is_file()}


def _shared(path: str, shared) -> bool:
    return any(scopes.matches(path, pat) for pat in shared)


def clobbered(snaps: dict, first: str, second: str, shared) -> list:
    """first の窓で作った・変えたファイルのうち、共有の記録の外で、second の窓の前後で中身か mtime が違う（消えたも含む）物の相対パス。
    名の順"""
    before, after = snaps[(first, "start")], snaps[(first, "done")]
    mine = [p for p, h in after.items() if before.get(p) != h and not _shared(p, shared)]
    s0, s1 = snaps[(second, "start")], snaps[(second, "done")]
    return sorted(p for p in mine if s0.get(p) != s1.get(p))


def tree_review(board: pathlib.Path) -> dict:
    """1 度目の include（planning）の事前審査の束ね役の返答（2 項目の案なので、受け付けは開いた項目ごとの下請けの答えのファイルと
    相乗りの審査のファイルを求める。planblk.tree_merge）。下請けの代わりに linekit.tree_review が答えのファイルを書く（当たりは
    全部 no_effect）"""
    return linekit.tree_review(board)


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

    brief = f"{board / 'fixing' / 'r1' / 'brief-1.md'}:1"   # 1 回目の修正の段（include fixing）の scope の根の brief
    rulings = [{"id": "c1-1", "decision": "fix_plan_item", "text": tr.PLAN_TEXT, "limits": [], "grounds": [brief]},
               {"id": "c1-2", "decision": "fix_code_as", "text": "依頼が正しい。分母を len(xs) に直せ", "limits": ["stats.py:9"]}]
    replies = {**line_replies(),
               "plan": lambda n: {"plan": [tr._item(1), tr.clamp_item()]} if n == 1 else {"plan": [tr.wider_paths()]},
               "plan-review": lambda n: tree_review(board) if n == 1 else tr.no_faces(),
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

    def test_second_include_overwrites_nothing_of_first(self):
        for first, second in PAIRS:
            with self.subTest(first=first, second=second):
                got = clobbered(self.snaps, first, second, SHARED)
                self.assertEqual(got, [], f"{second} が {first} のファイルを上書きした: {', '.join(got)}")


class UndeclaredWriteCase(unittest.TestCase):
    """部品が宣言の外に書けば、次に盤面を開く節（entry.open_board の scopes.enter）が窓を照らして盤面を止め、報告は止めた後も書かれる"""

    def test_undeclared_write_stops_run(self):
        with tempfile.TemporaryDirectory(dir=linekit.work_home()) as t:
            board = pathlib.Path(t) / "run" / "art" / "board"

            def stray(repo):
                """修正役の節（include fixing の窓の中）が直すべき所を直し（受け付けを通る）、別の include の置き場にも書く"""
                TL.fix_tree(repo)
                p = board / "planning" / "r1" / "z.json"
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text("{}", encoding="utf-8")

            got = scriptline.ScriptLine(pathlib.Path(t) / "run", replies=line_replies(), edits={"fix": stray}).run()
            state = json.loads((board / "state.json").read_text(encoding="utf-8"))
            self.assertEqual(state["stop"]["by"], stopby.SCOPE_CHECK, got["failure"])   # 次に開いた節が盤面を止めた
            self.assertIn("planning/r1/z.json", state["stop"]["reason"])
            self.assertIn("scope fixing", state["stop"]["reason"])
            self.assertIn("darkfactory/reporting", got["trail"])   # 報告は止めた後も走る
            self.assertNotIn("blk-delta/review", got["trail"])     # 修正の後の段へは進まない
            self.assertIn("planning/r1/z.json", (board / report.REPORT_FILE).read_text(encoding="utf-8"))
            window = (board / scopes.WINDOW).read_bytes()
            report.build(board, judged=None, tests=None, start=None, run_id=scriptline.RUN_ID)   # run の外の dev/report.sh と同じ呼び
            self.assertEqual((board / scopes.WINDOW).read_bytes(), window)   # run の外の呼びは窓に触らない


# fan_out の子の節の代わり: 盤面を開き（entry.open_board が scope を登録し窓に入る）、自分の根に書き、盤面に印を足して保存する。
# 保存が BoardConflict なら開き直して当て直す（works の入れ物の当て直しと同じ）。標準出力に当て直した回数
CHILD = """
import json, os, sys
sys.path.insert(0, os.environ["CORE"])
sys.path.insert(0, os.path.join(os.environ["CORE"], "graphloops"))
import entry, script_io
from engine.util import BoardConflict
board, me = sys.argv[1], sys.argv[2]
sys.stdin.readline()   # 全部の子がそろってから同時に開く
tries = 0
while True:
    b = entry.open_board(board)
    (script_io.scope_dir(board) / "r1").mkdir(parents=True, exist_ok=True)
    (script_io.scope_dir(board) / "r1" / "notes.md").write_text(me, encoding="utf-8")
    b.state["works"].setdefault("fan_probe", []).append(me)
    try:
        b.save()
        break
    except BoardConflict:
        tries += 1
print(tries)
"""


class FanOutOpenCase(unittest.TestCase):
    """fan_out の子が同時に盤面を開いて保存しても、盤面（state.json・scopes.json・窓）が壊れない（子ごとの scope・1 つの窓・
    保存の錠 board.SAVE_LOCK で後勝ちの消えが無い）。本物の表で作った盤面（git なし）を、子の数だけ同時に起こした python で開く"""

    def test_concurrent_children_open_and_save(self):
        import entry
        from board import DiskBoard
        n = 6
        with tempfile.TemporaryDirectory(dir=linekit.work_home()) as t:
            t = pathlib.Path(t)
            (t / "repo").mkdir()
            board = t / "board"
            table = entry.load_table(entry.LINE)
            DiskBoard.create(board, repo=t / "repo", table=table, inputs={}, request_text="依頼",
                             **entry.open_kwargs(entry.LINE, table))
            rev = json.loads((board / "state.json").read_text(encoding="utf-8"))["rev"]
            script = t / "blk-fix" / "scripts" / "fan_child.py"   # scopes.running_block が blk-fix と読む置き場
            script.parent.mkdir(parents=True)
            script.write_text(CHILD, encoding="utf-8")
            marks = [hashlib.sha256(str(k).encode()).hexdigest()[:16] for k in range(n)]
            procs = []
            for m in marks:
                path = f"__archon_fan_out__fan__root__{m}__fan__{m}__work"
                env = hermetic.child_env(CORE=str(scriptline.CORE), ARCHON_NODE_EXECUTION=json.dumps({"path": path}))
                procs.append(subprocess.Popen([sys.executable, str(script), str(board), m], env=env, text=True, encoding="utf-8",
                                              stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE))
            for p in procs:
                p.stdin.write("go\n")
                p.stdin.flush()
            outs = [p.communicate() for p in procs]
            self.assertEqual([p.returncode for p in procs], [0] * n, [e for _, e in outs])
            state = json.loads((board / "state.json").read_text(encoding="utf-8"))
            self.assertEqual(sorted(state["works"]["fan_probe"]), sorted(marks))   # 後勝ちで消えた保存が無い
            self.assertEqual(state["rev"], rev + n)
            self.assertNotIn("stop", state)
            reg = json.loads((board / "r1" / "scopes.json").read_text(encoding="utf-8"))
            self.assertEqual(sorted(k for k in reg if k != scopes.OWNS), sorted(f"fan--{m[:8]}" for m in marks))
            self.assertTrue(all(v["block"] == "blk-fix" for k, v in reg.items() if k != scopes.OWNS))
            self.assertEqual(json.loads((board / scopes.WINDOW).read_text(encoding="utf-8"))["scope"], "fan--*")
            for m in marks:
                self.assertEqual((board / f"fan--{m[:8]}" / "r1" / "notes.md").read_text(encoding="utf-8"), m)
            self.assertEqual(scopes.enter(board, 1, "", "darkfactory"), [])   # 線が窓を閉じても誤りは無い

    def test_save_compare_and_write_under_one_lock(self):
        """engine の save は版の比べと書き込みの間に錠を持たないので、同じ版を読んだ 2 つの入れ物が両方とも比べを通ると後勝ちで
        先の保存が消える（上の同時の子の試験では間が短く、錠を外しても 6 回とも当たらなかった）。間を 0.3 秒に広げ、先の保存が
        書いている間の後の保存が、待ってから BoardConflict になることを縛る（錠を外すと後の保存が通って赤）"""
        import threading
        import time
        from unittest import mock
        import entry
        import engine.board as engine_board
        from board import DiskBoard
        from engine.util import BoardConflict
        with tempfile.TemporaryDirectory(dir=linekit.work_home()) as t:
            t = pathlib.Path(t)
            (t / "repo").mkdir()
            table = entry.load_table(entry.LINE)
            DiskBoard.create(t / "board", repo=t / "repo", table=table, inputs={}, request_text="依頼",
                             **entry.open_kwargs(entry.LINE, table))
            first, second = entry.open_board(t / "board"), entry.open_board(t / "board")
            real, writing = engine_board.write_json, threading.Event()

            def slow(path, obj):
                if threading.current_thread().name == "first" and pathlib.Path(path).name == "record.json":
                    writing.set()
                    time.sleep(0.3)
                real(path, obj)
            with mock.patch.object(engine_board, "write_json", slow):
                th = threading.Thread(target=first.save, name="first")
                th.start()
                writing.wait()
                with self.assertRaises(BoardConflict):
                    second.save()
                th.join()


if __name__ == "__main__":
    unittest.main()
