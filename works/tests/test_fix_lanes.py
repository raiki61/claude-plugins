"""修正役の並べを Archon の節にする（blk-fix の fixlanes と並べの枝の部品 lanekit。設計 docs/plans/2026-10-07-fix-lane-nodes.md）の
検査。本物の盤面（test_blk_fix の BoardCase。種の git・修正案を 2 項目に分けた案・書き込みの記録）で回す。

- 枝を切る（fix-fork）: 形 g3・書き込みの記録の在る run で、範囲の在る修正案の項目が単位を共にしない 2 本以上の枝に分かれれば、
  単位の worktree を切り、枝の控え・項目の決まりのファイル（修正役の決まり・座・枝の役の節）・審査のファイルを書く。項目が 1 つ・
  記録の無い run（包みの無い起動）・入力 fix_lanes が off は切らない
- 枝の支度（fix-lane-prep-<n>）: 回ごとの指示書と包みが読む 2 つの印（項目ごとの単位の鍵・単位の worktree）
- 枝の確かめ（fix-lane-step-<n>）: 受け付けと同じ事実の確かめ（書き込みの出どころ・この項目の直す義務の単位・範囲）を単位の
  worktree に当てる。通れば次の項目へ、同じ項目の 3 回目の拒否で諦めて差分を控え木を戻す。範囲の相談の周は数えるだけ
- 締める（fix-join）: 通った枝の差分を run の作業ツリーへ 3 方向で当て（同じファイルの別の行は合う・同じ行の食い違いは後の枝を
  戻す）、書き込みの記録を写し、申し出を盤面に積み、結末を書いて単位の worktree を片付ける。回り切らなかった枝は戻す
- 修正の輪の支度（fix-prep）: 枝が当てた単位に下請けを起こさず、結末の節を指示書に載せる
- 節の script（fix_fork・fix_lane_prep・fix_lane_step・fix_join）を子で起こして 1 回通す
"""
import json
import os
import pathlib
import sys
import unittest
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parents[1]
TESTS = pathlib.Path(__file__).resolve().parent
sys.dont_write_bytecode = True
sys.path.insert(0, str(TESTS))

import test_blk_fix as tbf  # noqa: E402  （BoardCase・種の盤面・見本の返答）
from test_blk_fix import CLAMP, MEAN, BoardCase, load, run_script  # noqa: E402

for _p in (ROOT / "blk-fix" / "lib",):
    if str(_p) not in sys.path:
        sys.path.append(str(_p))

import adapter  # noqa: E402
import conflict  # noqa: E402
import entry  # noqa: E402
import fixlanes  # noqa: E402
import fixrules  # noqa: E402
import lanekit  # noqa: E402
import planbrief  # noqa: E402
import planmarks  # noqa: E402
import unittrees  # noqa: E402
import writes  # noqa: E402

MEAN_FIX = ("sum(xs) / (len(xs) - 1)", "sum(xs) / len(xs)")
CLAMP_FIX = ("    if x > hi:\n        return lo", "    if x > hi:\n        return hi")
_PLAN_REPLY = tbf.plan_reply   # 1 項目の案（2 単位）。差し替えの中から呼ぶ（差し替えた名を呼ぶと自分を呼ぶ）
FIELDS = {**tbf.PLAN_FIELDS[0], "route": "direct", "tests": [], "route_why": "見本。先にテストを書かない"}


def split_plan_reply(narrows=()):
    """修正案を単位ごとの 2 項目にした返答（項目 1 は mean、項目 2 は clamp）"""
    base = _PLAN_REPLY(narrows)["plan"][0]
    return {"plan": [{**base, "unit_keys": [MEAN], "approach": "mean の分母を len(xs) に直す"},
                     {**base, "unit_keys": [CLAMP], "approach": "clamp の上限の枝の戻り値を hi に直す"}]}


def one_item_reply(narrows=()):
    return _PLAN_REPLY(narrows)


def lane_reply(key):
    """見本の返答（fix2_ok）の key の行だけを changes に持つ枝の返答"""
    full = load("fix2_ok")
    row = next(c for c in full["changes"] if c["unit_key"] == key)
    return {**full, "changes": [row], "interactions": []}


class LaneBoard(BoardCase):
    SPLIT = True     # 修正案を 2 項目に分ける
    LOG = True       # 書き込みの記録の在る run（包みの起動）

    def setUp(self):
        super().setUp()
        with mock.patch.object(tbf, "plan_reply", split_plan_reply if self.SPLIT else one_item_reply):
            self.fix_ready(launched=False)
        b = entry.open_board(self.board)
        planmarks.save(self.board, b.round, [FIELDS, FIELDS] if self.SPLIT else [FIELDS])
        planbrief.cut_at(self.board)
        self.log = writes.sink(self.repo)
        if self.LOG:
            self.log.parent.mkdir(parents=True, exist_ok=True)
            self.log.write_text("", encoding="utf-8")
        self.addCleanup(unittrees.sweep, self.repo)

    def values(self):
        b = entry.open_board(self.board)
        return {"judgment_file": str(self.board / b.state["outputs"]["p2.diagnose"]["file"]),
                "open_units": json.dumps([MEAN, CLAMP], ensure_ascii=False), "plan_file": "", "policy_path": "",
                "notes_file": "", "summary_file": "", "base_rev": "", "plan_session": "", "ripple_file": "", "tdd_state": ""}

    def fork(self, **kw):
        return fixlanes.fork(self.board, self.repo, self.values(), **kw)

    def state(self, n):
        return json.loads(entry.open_board(self.board).work(fixlanes.LANE_STATE.format(n=n)).read_text(encoding="utf-8"))

    def tree(self, n):
        return pathlib.Path(self.state(n)["tree"])

    def edit(self, n, fix, record=True):
        p = self.tree(n) / "stats.py"
        text = p.read_text(encoding="utf-8")
        self.assertIn(fix[0], text)
        p.write_text(text.replace(fix[0], fix[1]), encoding="utf-8")
        if record:
            self.record(p)

    def record(self, path):
        with open(self.log, "a", encoding="utf-8") as f:
            f.write(json.dumps({"tool_name": "Edit", "path": os.path.realpath(path), "file_sha": writes._sha(str(path))}) + "\n")

    def step(self, n, reply, **kw):
        return fixlanes.lane_step(self.board, n, reply, self.repo, **kw)

    def forked(self):
        got = self.fork()
        self.assertTrue(got["go"], got)
        return got


class TestFork(LaneBoard):
    def test_two_items_get_two_lanes_and_their_files(self):
        got = self.forked()
        self.assertEqual(got, {"go": True, "lanes": 2, "lane_1": True, "lane_2": True, "lane_3": False, "why": ""})
        b = entry.open_board(self.board)
        man = json.loads(b.work(fixlanes.MANIFEST).read_text(encoding="utf-8"))
        self.assertEqual([(r["n"], r["items"]) for r in man["lanes"]], [(1, [1]), (2, [2])])
        self.assertEqual(man["expect"], [[1, 2]], "同じ stats.py を書いてよい 2 項目（重なりの見込み）")
        for n, key in ((1, MEAN), (2, CLAMP)):
            st = self.state(n)
            tree = pathlib.Path(st["tree"])
            self.assertTrue((tree / "stats.py").is_file())
            self.assertEqual(st["items"][0]["units"], [key])
            rules = pathlib.Path(st["items"][0]["rules"]).read_text(encoding="utf-8")
            for w in ("修正役の並べの枝（機械が書いた", str(tree), key, "審査の下請け", st["items"][0]["review"],
                      "借りたスキルの座（修正の形 g3）", "## 修正ごとに書くこと"):
                self.assertIn(w, rules)
            self.assertNotIn(CLAMP if key == MEAN else MEAN, rules.split("## 修正役の並べの枝")[1].split("## 修正ごとに")[0],
                             "枝の節はこの項目の単位だけを名指す")
            review = pathlib.Path(st["items"][0]["review"]).read_text(encoding="utf-8")
            self.assertIn(str(tree), review, "審査の下請けは枝の単位の worktree で読む")
        trace = [json.loads(ln) for ln in (self.board / "trace.jsonl").read_text(encoding="utf-8").splitlines() if ln.strip()]
        planted = [r for r in trace if r.get("op") == fixlanes.PLANTED_OP]
        self.assertEqual((planted[-1]["lanes"], planted[-1]["items"]), (2, {"1": [1], "2": [2]}))

    def test_no_writes_record_means_no_lanes(self):
        self.log.unlink()
        got = self.fork()
        self.assertFalse(got["go"])
        self.assertIn("書き込みの記録が無い", got["why"])
        self.assertEqual(unittrees._refs(self.repo), [], "単位の worktree を切らない")

    def test_off_and_green_units(self):
        self.assertEqual(self.fork(switch="off")["why"], fixlanes.OFF)
        got = self.fork(green={MEAN})
        self.assertFalse(got["go"], "TDD の輪が緑にした単位の項目は枝に入らない（残りは 1 項目）")
        self.assertIn("2 本に満たない", got["why"])


class TestOneItem(LaneBoard):
    SPLIT = False

    def test_one_item_stays_serial(self):
        got = self.fork()
        self.assertFalse(got["go"], got)
        self.assertIn("枝 1", got["why"])


class TestLane(LaneBoard):
    def test_prep_writes_the_turn_and_the_two_marks(self):
        self.forked()
        got = fixlanes.lane_prep(self.board, 1)
        text = pathlib.Path(got["prompt_file"]).read_text(encoding="utf-8")
        st = self.state(1)
        self.assertIn(st["items"][0]["rules"], text)
        self.assertIn("この項目の最初の回", text)
        key = pathlib.Path(adapter.session_key_path(str(self.board), "fix-lane-1")).read_text(encoding="utf-8").strip()
        self.assertTrue(key.endswith(":lane-1:item-1"), key)
        mark = pathlib.Path(adapter.lane_tree_path(str(self.board), "fix-lane-1")).read_text(encoding="utf-8").strip()
        self.assertEqual(mark, st["tree"])

    def test_good_reply_is_accepted_and_the_lane_is_done(self):
        self.forked()
        self.edit(1, MEAN_FIX)
        got = self.step(1, lane_reply(MEAN))
        self.assertEqual((got["ok"], got["done"], got["item"]), (True, True, 1), got)
        st = self.state(1)
        self.assertEqual(st["results"][0]["outcome"], fixlanes.ACCEPTED)
        self.assertEqual(st["results"][0]["changed"], [MEAN])
        self.assertTrue(pathlib.Path(st["results"][0]["reply"]).is_file())

    def test_rejects_name_the_check_and_give_up_on_the_third(self):
        self.forked()
        self.edit(1, MEAN_FIX, record=False)   # 書き込みの記録の無い変更
        got = self.step(1, lane_reply(MEAN))
        self.assertFalse(got["ok"])
        self.assertIn("確かめ writes", got["reason"])
        wrong = lane_reply(CLAMP)
        got = self.step(1, wrong)
        self.assertIn("この項目の直す義務の単位でない", got["reason"])
        self.assertIn(f"直す義務の単位 {MEAN} が changes にも", got["reason"])
        prompt = pathlib.Path(fixlanes.lane_prep(self.board, 1)["prompt_file"]).read_text(encoding="utf-8")
        self.assertIn("前の回の返答を機械が拒んだ理由", prompt)
        got = self.step(1, wrong)
        self.assertEqual((got["ok"], got["done"]), (False, True), "3 回目の拒否で項目を諦め、枝の項目が尽きた")
        r = self.state(1)["results"][0]
        self.assertEqual(r["outcome"], fixlanes.GAVE_UP)
        self.assertIn("sum(xs) / len(xs)", pathlib.Path(r["patch"]).read_text(encoding="utf-8"), "直しを捨てずに控える")
        self.assertIn("(len(xs) - 1)", (self.tree(1) / "stats.py").read_text(encoding="utf-8"), "木は項目の頭に戻す")

    def test_consult_turn_is_counted_but_not_checked(self):
        self.forked()
        got = self.step(1, {"anything": 1}, consulted=True)
        self.assertEqual((got["ok"], got["done"], got["consulted"]), (False, False, True))
        st = self.state(1)
        self.assertEqual((st["tries"], st["iterations"]), (0, 1))
        got = self.step(1, {**lane_reply(MEAN), "consult": [{"item": 1, "paths": ["x"], "tests": [], "why": "x" * 20}]})
        self.assertIn("範囲の相談の枠", got["reason"], "相談の周でない consult は枠を使い切った後の頼み")

    def test_iteration_cap_stops_the_lane(self):
        self.forked()
        for _ in range(fixlanes.MAX_ITERATIONS - 1):
            self.assertFalse(self.step(1, {}, consulted=True)["done"])
        self.edit(1, MEAN_FIX)   # 書きかけ
        got = self.step(1, {}, consulted=True)
        self.assertTrue(got["done"], "回数の上限で済みにする（max_iterations で落とさない。R50）")
        r = self.state(1)["results"][0]
        self.assertEqual(r["outcome"], fixlanes.GAVE_UP, "書きかけは控えて戻す")
        self.assertIn("sum(xs) / len(xs)", pathlib.Path(r["patch"]).read_text(encoding="utf-8"))

    def test_broken_tree_ends_the_lane_and_join_sends_it_back(self):
        self.forked()
        (self.tree(2) / ".git").write_text("gitdir: /elsewhere\n", encoding="utf-8")
        got = self.step(2, lane_reply(CLAMP))
        self.assertEqual((got["ok"], got["done"]), (False, True))
        self.assertEqual(self.state(2)["results"][0]["outcome"], fixlanes.NOT_RUN)
        self.edit(1, MEAN_FIX)
        self.assertTrue(self.step(1, lane_reply(MEAN))["ok"])
        out = fixlanes.join(self.board, self.repo)
        self.assertEqual((out["merged"], out["back"]), ([1], [2]))
        doc = json.loads(entry.open_board(self.board).work(fixrules.LANES_RECORD).read_text(encoding="utf-8"))
        self.assertIn(".git の指し", next(i for i in doc["items"] if i["item"] == 2)["why"])


class TestJoin(LaneBoard):
    def both(self, second=CLAMP_FIX):
        self.forked()
        self.edit(1, MEAN_FIX)
        self.assertTrue(self.step(1, lane_reply(MEAN))["ok"])
        self.edit(2, second)
        return self.step(2, lane_reply(CLAMP))

    def test_both_lanes_merge_into_the_run_tree(self):
        self.assertTrue(self.both()["ok"])
        trees = [self.tree(1), self.tree(2)]
        got = fixlanes.join(self.board, self.repo)
        self.assertEqual((got["merged"], got["back"], got["shared"]), ([1, 2], [], ["stats.py"]))
        text = (self.repo / "stats.py").read_text(encoding="utf-8")
        self.assertIn(MEAN_FIX[1], text)
        self.assertIn(CLAMP_FIX[1], text)
        self.assertEqual(writes.check({}, self.repo, ["stats.py"], self.log)["problems"], [], "合わせた中身に記録を写す")
        self.assertFalse(any(t.exists() for t in trees), "単位の worktree を片付ける")
        b = entry.open_board(self.board)
        self.assertEqual(fixrules.lanes_merged(b), {MEAN, CLAMP})
        summary = b.work(fixrules.LANES_SUMMARY).read_text(encoding="utf-8")
        self.assertIn("項目 1（枝 1）", summary)
        self.assertIn("重なりのファイル", summary)

    def test_clashing_lane_goes_back_with_its_patch(self):
        self.both(second=(MEAN_FIX[0], "sum(xs) / max(len(xs), 1)"))
        got = fixlanes.join(self.board, self.repo)
        self.assertEqual((got["merged"], got["back"]), ([1], [2]))
        doc = json.loads(entry.open_board(self.board).work(fixrules.LANES_RECORD).read_text(encoding="utf-8"))
        back = next(i for i in doc["items"] if i["item"] == 2)
        self.assertIn("当たらない", back["why"])
        self.assertIn("max(len(xs), 1)", pathlib.Path(back["patch"]).read_text(encoding="utf-8"))
        self.assertEqual(fixrules.lanes_merged(entry.open_board(self.board)), {MEAN}, "戻した項目の単位は直す義務のまま")

    def test_unfinished_lane_goes_back(self):
        self.forked()
        self.edit(1, MEAN_FIX)
        self.assertTrue(self.step(1, lane_reply(MEAN))["ok"])
        self.edit(2, CLAMP_FIX)   # 枝 2 の輪は確かめまで届かなかった
        got = fixlanes.join(self.board, self.repo)
        self.assertEqual((got["merged"], got["back"]), ([1], [2]))
        self.assertNotIn(CLAMP_FIX[1], (self.repo / "stats.py").read_text(encoding="utf-8"), "書きかけを当てない")

    def test_stray_write_in_the_run_tree_is_reverted(self):
        self.both()
        (self.repo / "stray.txt").write_text("x\n", encoding="utf-8")
        fixlanes.join(self.board, self.repo)
        self.assertFalse((self.repo / "stray.txt").exists())

    def test_lane_claim_is_rechecked_and_parked(self):
        self.forked()
        self.edit(1, MEAN_FIX)
        self.assertTrue(self.step(1, lane_reply(MEAN))["ok"])
        claim = {"unit_key": CLAMP, "between": ["stats.py:8", "stats.py:9"], "why_both_cannot_hold": "上限の扱いが判定と食い違う" * 2,
                 "which_is_right": "unknown", "kind": "needs_context"}
        reply = {**lane_reply(CLAMP), "changes": [], "conflicts": [claim]}
        got = self.step(2, reply)
        self.assertTrue(got["ok"], got)
        out = fixlanes.join(self.board, self.repo)
        self.assertEqual(out["parked"], 1)
        items = conflict.unruled(entry.open_board(self.board))
        self.assertEqual([i["unit_key"] for i in items], [CLAMP])


class TestChainedItems(LaneBoard):
    """1 本の枝が 2 項目を順に直す（枝 1 に項目 1・2。枝 2 は配線のための写し）: 諦めた項目の直しは木から消え、次の項目は新しい鍵で
    新しい会話になり、枝の差分は次の項目の直しだけ"""

    def test_second_item_follows_a_given_up_first(self):
        with mock.patch.object(fixlanes, "assign", return_value=([[1, 2], [2]], [])):
            self.forked()
        first = fixlanes.lane_prep(self.board, 1)
        key = pathlib.Path(adapter.session_key_path(str(self.board), "fix-lane-1"))
        self.assertTrue(key.read_text(encoding="utf-8").strip().endswith("item-1"))
        self.assertIn("1 番目の項目", pathlib.Path(first["prompt_file"]).read_text(encoding="utf-8"))
        self.edit(1, MEAN_FIX, record=False)
        for _ in range(fixlanes.GIVE_UP_AFTER):
            got = self.step(1, lane_reply(MEAN))
        self.assertEqual((got["ok"], got["done"]), (False, False), "項目 1 を諦めて項目 2 へ")
        rules = self.state(1)["items"][0]["rules"]
        self.assertIn("この枝の後の項目", pathlib.Path(rules).read_text(encoding="utf-8"), "項目 1 の決まりは後の項目を名指す")
        second = fixlanes.lane_prep(self.board, 1)
        self.assertTrue(key.read_text(encoding="utf-8").strip().endswith("item-2"), "項目が替われば鍵が替わる（包みが会話を切る）")
        self.assertIn("2 番目の項目", pathlib.Path(second["prompt_file"]).read_text(encoding="utf-8"))
        self.edit(1, CLAMP_FIX)
        got = self.step(1, lane_reply(CLAMP))
        self.assertEqual((got["ok"], got["done"], got["item"]), (True, True, 2))
        st = self.state(1)
        self.assertEqual([r["outcome"] for r in st["results"]], [fixlanes.GAVE_UP, fixlanes.ACCEPTED])
        diff = unittrees.diff(self.tree(1), st["base"])
        self.assertIn("return hi", diff)
        self.assertNotIn("len(xs)\n", diff.replace("(len(xs) - 1)", ""), "諦めた項目の直しは枝の差分に入らない")

    def test_consult_answer_resumes_the_same_item(self):
        self.forked()
        b = entry.open_board(self.board)
        answer = b.work("consult-lane-1-1.md")
        answer.write_text("# 答え\n", encoding="utf-8")
        b.work("consult-lane-1.json").write_text(json.dumps({"turns": 1, "turn_state": "answered", "answer_file": str(answer)}),
                                                 encoding="utf-8")
        got = fixlanes.lane_prep(self.board, 1)
        text = pathlib.Path(got["prompt_file"]).read_text(encoding="utf-8")
        self.assertIn(str(answer), text)
        self.assertIn(self.state(1)["items"][0]["rules"], text, "前に読んだ項目の決まりを名指す続きの指示書")
        self.assertIsNone(__import__("consult").take(entry.open_board(self.board), "lane-1"), "渡した答えは 1 度だけ")


class TestMade(LaneBoard):
    def test_runner_made_files_stay_out_of_the_patch(self):
        """枝の実行器が作ったファイル（記録が無い）は拒まず、差分にも入れない"""
        self.forked()
        self.edit(1, MEAN_FIX)
        (self.tree(1) / "junit-out.txt").write_text("runner\n", encoding="utf-8")
        st = self.state(1)
        got = lanekit.merge(self.repo, st["tree"], since=st["base"], base=st["base"], log=self.log, made=["junit-out.txt"],
                            kept=self.tmp / "lane-1.patch")
        self.assertEqual(got.why, "", got)
        self.assertEqual(got.names, ["stats.py"])
        self.assertFalse((self.repo / "junit-out.txt").exists())
        got2 = lanekit.merge(self.repo, st["tree"], since=st["base"], base=st["base"], log=self.log, made=[],
                             kept=self.tmp / "lane-1b.patch", earlier=["stats.py"])
        self.assertEqual(got2.names, ["stats.py"], "戻した後は作った物が残らない")


class TestSerialAfterLanes(LaneBoard):
    def test_fix_prep_skips_merged_units_and_names_the_summary(self):
        self.forked()
        self.edit(1, MEAN_FIX)
        self.assertTrue(self.step(1, lane_reply(MEAN))["ok"])
        self.edit(2, CLAMP_FIX)
        self.assertTrue(self.step(2, lane_reply(CLAMP))["ok"])
        fixlanes.join(self.board, self.repo)
        env = {"ARTIFACTS_DIR": str(self.art), "WORKS_ADAPTER_HOME": os.environ["WORKS_ADAPTER_HOME"], "INPUTS_PASS": "first",
               **{f"INPUTS_{k.upper()}": v for k, v in self.values().items() if k != "tdd_state"}}
        code, out, err = run_script("fix_prep", self.repo, env)
        self.assertEqual(code, 0, err)
        text = pathlib.Path(json.loads(out)["prompt_file"]).read_text(encoding="utf-8")
        self.assertIn(str(entry.open_board(self.board).work(fixrules.LANES_SUMMARY)), text)
        self.assertNotIn("## 下請けを回す", text, "枝が全部の単位を当てた周は下請けを起こさない（座のまま）")
        self.assertIn("直す義務の単位 0 件", text, "座の型も枝が当てた単位を今直す単位に数えない")
        code, out, err = run_script("fix_prep", self.repo, env)   # 出し直しの周（受け付けが拒んだ後）
        self.assertEqual(code, 0, err)
        again = pathlib.Path(json.loads(out)["prompt_file"]).read_text(encoding="utf-8")
        self.assertIn("## 下請けを回す", again, "出し直しの周は枝が当てた単位も下請けを起こし直せる")


class TestScripts(LaneBoard):
    def env(self, **kw):
        return {"ARTIFACTS_DIR": str(self.art), "WORKS_ADAPTER_HOME": os.environ["WORKS_ADAPTER_HOME"], **kw}

    def test_scripts_run_one_lanes_turn(self):
        vals = {f"INPUTS_{k.upper()}": v for k, v in self.values().items() if k != "tdd_state"}
        code, out, err = run_script("fix_fork", self.repo, self.env(**vals, INPUTS_FIX_LANES=""))
        self.assertEqual(code, 0, err)
        self.assertTrue(json.loads(out)["go"], out)
        for n, key, fix in ((1, MEAN, MEAN_FIX), (2, CLAMP, CLAMP_FIX)):
            code, out, err = run_script("fix_lane_prep", self.repo, self.env(INPUTS_LANE=str(n)))
            self.assertEqual(code, 0, err)
            self.edit(n, fix)
            code, out, err = run_script("fix_lane_step", self.repo, self.env(
                INPUTS_REPLY=json.dumps(lane_reply(key), ensure_ascii=False), INPUTS_LANE=str(n), INPUTS_CONSULTED="false",
                INPUTS_BASE_REV="", INPUTS_TDD_STATE=""))
            self.assertEqual(code, 0, err)
            got = json.loads(out)
            self.assertEqual((got["ok"], got["done"], got["reason_file"]), (True, True, ""), got)
        code, out, err = run_script("fix_join", self.repo, self.env())
        self.assertEqual(code, 0, err)
        self.assertEqual(json.loads(out)["merged"], [1, 2])

    def test_fork_script_reads_the_switch(self):
        vals = {f"INPUTS_{k.upper()}": v for k, v in self.values().items() if k != "tdd_state"}
        code, out, err = run_script("fix_fork", self.repo, self.env(**vals, INPUTS_FIX_LANES="off"))
        self.assertEqual(code, 0, err)
        self.assertEqual(json.loads(out)["why"], fixlanes.OFF)
        code, out, err = run_script("fix_fork", self.repo, self.env(**vals, INPUTS_FIX_LANES="maybe"))
        self.assertEqual(code, 2)
        self.assertEqual(out.strip(), "")

    def test_rejected_step_writes_a_reason_file(self):
        self.forked()
        code, out, err = run_script("fix_lane_step", self.repo, self.env(
            INPUTS_REPLY=json.dumps({"changes": []}), INPUTS_LANE="1", INPUTS_CONSULTED="", INPUTS_BASE_REV="", INPUTS_TDD_STATE=""))
        self.assertEqual(code, 0, err)
        got = json.loads(out)
        self.assertFalse(got["ok"])
        self.assertIn("この項目の直す義務の単位", pathlib.Path(got["reason_file"]).read_text(encoding="utf-8"))


class TestKit(unittest.TestCase):
    """並べの枝の部品の純粋な口"""

    def test_fork_out(self):
        self.assertEqual(lanekit.fork_out([]), {"go": False, "lanes": 0, "lane_1": False, "lane_2": False, "lane_3": False})
        self.assertEqual(lanekit.fork_out([1, 2])["lane_2"], True)
        for bad in ([2], [1, 2, 3, 4]):
            with self.assertRaises(ValueError):
                lanekit.fork_out(bad)


if __name__ == "__main__":
    unittest.main()
