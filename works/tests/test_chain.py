"""周の鎖の住処 .shared/core/chain.py の検査（純粋な関数を直に呼ぶ。鎖の控えは一時の置き場のファイルだけ。git・Archon は使わない）。

見る物:
- decide: 見る順（周の数 → 結末の種 → 人が要る → 進みが無い → 費用）。止めの語 STOPS。起こした次の周の状態（pending）の読み
  （子の pid が生きていれば待ち、死んで起動の印を置いていれば launch_unbound、起動の前で死んでいれば起こし直す）
- next_request・held_rows: 次の周の依頼（前の周の下書きでない findings・prior_failures と、1 周目の answers・pr・issue）
- pick・render: 最後の差分に採る周と chain.md（読めない費用を 0 と書かない・R2 の作り直しが残る周を閉じたと言わない）
- 殻の口: init → launched → bound → step の 1 周と、同じ run を 2 度渡しても 2 本目を起こさないこと
"""
import ast
import contextlib
import fcntl
import io
import json
import os
import pathlib
import re
import subprocess
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
CORE = ROOT / ".shared" / "core"
sys.path.insert(0, str(CORE))

import carry  # noqa: E402


class _CoreChain:
    """chain.py を使う時に読み込む（無い版でも試験の収集は落ちず、使った試験の中で読み込みに落ちる）"""

    def __getattr__(self, name):
        import importlib
        return getattr(importlib.import_module("chain"), name)


core_chain = _CoreChain()

FINDING = {"where": "a.py:1", "text": "mean が空で落ちる"}


def row(n, kind=None, **kw):
    """周の行の見本（core_chain.build_row が書く欄のうち決めが読む物）。kind を省けば open"""
    kind = kind or core_chain.KIND_OPEN
    base = {"n": n, "run": f"run-{n}", "from": f"f{n}", "base_rev": "b0", "result": f"r{n}", "same_tree": False,
            "outcome": "x", "kind": kind, "minutes": 10.0, "cost": 1.0, "cost_read": True, "keys": [f"k{n}"], "held_rows": [],
            "files": 1, "r2": 0, "stopped": None, "diff": f"/d/{n}.diff", "report": "", "next_file": ""}
    base.update(kw)
    return base


def doc_of(rows, rounds_max=3, **kw):
    d = core_chain.new_doc("c-1", target="/t", rounds=rounds_max, budget=None, request="", test_cmd="", tdd_suite="", env=[],
                      use_sh="/u/use.sh", pid=1)
    d["pending"] = None
    d["rounds"] = rows
    d["original_base"] = "b0"
    d.update(kw)
    return d


def dead_pid() -> int:
    p = subprocess.Popen(["true"])
    p.wait()
    return p.pid


class Decide(unittest.TestCase):
    def go(self, rows, facts=None, **kw):
        facts = rows[-1] if facts is None else facts
        return core_chain.decide(doc_of(rows, **kw), facts, kw.get("budget"))

    def test_closed_round_stops_with_closed(self):
        """結末の種が closed の周の後は、周の数が残っていても止め、止めの語は closed になる"""
        got = self.go([row(1, core_chain.KIND_CLOSED)])
        self.assertEqual((got["act"], got["word"]), ("stop", "closed"))
        self.assertIn(got["word"], core_chain.STOPS)

    def test_open_round_below_limit_goes_on(self):
        """結末の種が open で周の数が残り、木が前と違い残りの鍵も前と違えば、次の周へ進む"""
        rows = [row(1, keys=["a"]), row(2, keys=["b"])]
        got = self.go(rows, {**rows[-1], "next": {"findings": [FINDING]}}, rounds_max=3)
        self.assertEqual(got["act"], "launch", got)

    def test_rounds_reached_stops(self):
        """周の数に達したら、結末の種に依らず rounds_reached で止める"""
        for kind in (core_chain.KIND_OPEN, core_chain.KIND_CLOSED):
            with self.subTest(kind=kind):
                got = self.go([row(1), row(2, kind)], rounds_max=2)
                self.assertEqual((got["act"], got["word"]), ("stop", "rounds_reached"))

    def test_halted_human_and_wait_kinds(self):
        """止まった周は halted、人が要る周は human で止まり、途中で落ちた周は止めずに待つ"""
        self.assertEqual(self.go([row(1, core_chain.KIND_HALTED)])["word"], "halted")
        self.assertEqual(self.go([row(1, core_chain.KIND_HUMAN)])["word"], "human")
        self.assertEqual(self.go([row(1, core_chain.KIND_WAIT)])["act"], "aborted")
        self.assertEqual(self.go([row(1, "読めない種")])["word"], "halted")

    def test_draft_rows_stop_for_human(self):
        """前の周の次の依頼に下書きの印の行が在れば human で止め、下書きを答えに替えない（findings の下書きも answers の下書きも）"""
        draft = carry.draft({"question": "q", "text": ""}, "gate")
        for nxt in ({"findings": [carry.draft(FINDING, "purpose")]}, {"findings": [FINDING], "answers": [draft]}):
            with self.subTest(nxt=nxt):
                got = self.go([row(1)], {**row(1), "next": nxt})
                self.assertEqual((got["act"], got["word"]), ("stop", "human"))
                self.assertIn("下書き", got["text"])

    def test_same_tree_and_same_items_stop(self):
        """result_k の木が from_k の木と同じなら、差分が累計で空でなくても no_change。残りの行の鍵の集合が前の周と同じなら same_items"""
        got = self.go([row(1, same_tree=True)])
        self.assertEqual(got["word"], "no_change")
        got = self.go([row(1, keys=["a", "b"]), row(2, keys=["b", "a"])])
        self.assertEqual(got["word"], "same_items")
        got = self.go([row(1, keys=["a", "b"]), row(2, keys=["a"])])
        self.assertEqual(got["act"], "launch")
        got = self.go([row(1, keys=[]), row(2, keys=[])])   # 鍵の無い残りは「同じ」と言えない
        self.assertEqual(got["act"], "launch")

    def test_budget_and_unreadable_cost(self):
        """上限が在る時だけ、累計＋最大の周の費用が上限を越えれば budget、読めない周が在れば cost_unread で止める。上限が無ければ費用で止めない"""
        rows = [row(1, cost=6.0), row(2, cost=8.0)]
        self.assertEqual(self.go(rows, budget_usd=20.0)["word"], "budget")      # 14 + 8 > 20
        self.assertEqual(self.go(rows, budget_usd=22.0)["act"], "launch")       # 14 + 8 = 22
        self.assertEqual(core_chain.decide(doc_of(rows), rows[-1], 20.0)["word"], "budget")   # 引数の上限が控えの値に勝つ
        unread = [row(1, cost=None, cost_read=False), row(2)]
        self.assertEqual(self.go(unread, budget_usd=100.0)["word"], "cost_unread")
        self.assertEqual(self.go(unread)["act"], "launch")                       # 上限が無ければ読めなくても止めない
        self.assertEqual(self.go(rows)["act"], "launch")

    def test_launched_pending_waits_while_child_lives(self):
        """pending が launched で run が無い時、子の pid が生きていれば待ち、死んでいれば launch_unbound で止める。launched でない pending だけ起こし直す"""
        def pend(pid, launched, run=""):
            return {"round": 2, "mark": "c-1-2", "pid": pid, "launched": launched, "run": run, "from": "f", "request": "", "log": ""}
        alive, dead = os.getpid(), dead_pid()
        for p, want in ((pend(alive, True), "wait"), (pend(alive, False), "wait"), (pend(dead, False), "launch"),
                        (pend(None, False), "launch"), (pend(dead, True), "stop"), (pend(dead, True, "run-2"), "follow")):
            with self.subTest(pending=p):
                got = core_chain.decide(doc_of([row(1)], pending=p), None)
                self.assertEqual(got["act"], want, got)
        got = core_chain.decide(doc_of([row(1)], pending=pend(dead, True)), None)
        self.assertEqual(got["word"], "launch_unbound")

    def test_relaunch_is_capped_and_names_the_child_log(self):
        """起動の印の前で死んだ子は 1 度だけ起こし直す。切り離して起こした回数 tries が LAUNCH_TRIES に達した後に死ねば、子の出力の
        置き場を添えて launch_failed で止める（wait を打つたびに際限なく起こし直さない）。生きている子は回数に依らず待つ"""
        def pend(pid, tries):
            return {"round": 2, "mark": "c-1-2", "pid": pid, "launched": False, "run": "", "from": "f", "request": "",
                    "log": "/h/chains/c-1/round-2.log", "tries": tries}
        dead = dead_pid()
        self.assertEqual(core_chain.decide(doc_of([row(1)], pending=pend(dead, 1)), None)["act"], "launch")
        got = core_chain.decide(doc_of([row(1)], pending=pend(dead, core_chain.LAUNCH_TRIES)), None)
        self.assertEqual((got["act"], got["word"]), ("stop", "launch_failed"))
        self.assertIn("/h/chains/c-1/round-2.log", got["text"])
        self.assertEqual(core_chain.decide(doc_of([row(1)], pending=pend(os.getpid(), core_chain.LAUNCH_TRIES)), None)["act"], "wait")
        self.assertEqual(core_chain.decide(doc_of([row(1)], stop={"word": "closed", "text": "t"}), None)["word"], "closed")

    def test_stops_table_is_not_stopby(self):
        """鎖の止めの語は run の中の止めの理由（stopby）とは別の表"""
        import stopby
        self.assertFalse(set(core_chain.STOPS) & set(getattr(stopby, "REASONS", {})))
        self.assertEqual(set(core_chain.STOPS), {"rounds_reached", "closed", "halted", "human", "no_change", "same_items", "budget",
                                            "cost_unread", "launch_unbound", "launch_failed"})


class NextRequest(unittest.TestCase):
    def test_carries_findings_prior_and_first_answers(self):
        """前の周の下書きでない findings・prior_failures と、1 周目の answers・pr・issue を持ち、carry.parts で解ける。下書きは運ばない"""
        prior = [{"where": "受け付け x", "text": "R2 が redesign-needed: 作り直し"}]
        prev = {"findings": [FINDING, carry.draft({"where": "b.py", "text": "目的の外"}, "purpose")], "prior_failures": prior,
                "answers": [carry.draft({"question": "q2", "text": ""}, "gate")]}
        first = {"findings": [{"where": "z", "text": "1 周目の所見"}], "pr": [12], "issue": [3],
                 "answers": [{"question": "q1", "text": "依頼者の答え"}], "prior_failures": [{"where": "w", "text": "t"}]}
        got = core_chain.next_request(prev, first)
        parts = carry.parts(got)
        self.assertEqual(parts["findings"], [FINDING])
        self.assertEqual(parts["prior_failures"], prior)
        self.assertEqual((parts["pr"], parts["issue"]), ([12], [3]))
        self.assertEqual(parts["answers"], first["answers"])
        self.assertEqual(len(core_chain.held_rows(prev)), 2)

    def test_without_first_request(self):
        """1 周目の依頼が無い（変更だけ）鎖は、前の周の残りだけで組む。1 周目の答えは無い"""
        got = core_chain.next_request({"findings": [FINDING], "prior_failures": []}, None)
        self.assertEqual(carry.parts(got)["answers"], [])
        self.assertEqual(got["findings"], [FINDING])
        self.assertEqual(core_chain.next_request(None, None), {"findings": [], "prior_failures": []})


class Pick(unittest.TestCase):
    def test_skips_stopped_last_round_and_names_it(self):
        """採る周は最後から戻って止まりでない最初の周で、止まった最後の周は採らずに名指す"""
        rows = [row(1), row(2, stopped=["w", "by", "text"])]
        kept, skipped = core_chain.pick(rows)
        self.assertEqual(kept["n"], 1)
        self.assertEqual([r["n"] for r in skipped], [2])
        self.assertEqual(core_chain.pick([row(1)])[0]["n"], 1)
        self.assertEqual(core_chain.pick([row(1, stopped=["w", "b", "t"])]), (None, [rows[0] | {"stopped": ["w", "b", "t"]}]))
        self.assertIsNone(core_chain.pick([row(1, result="")])[0])   # 結果を作れなかった周は採れない


class Render(unittest.TestCase):
    def test_unreadable_cost_is_named_not_zero(self):
        """chain.md は、読めない費用の周を 0 と書かず「読めない」と名指し、頭の 3 行と周ごとの表（分を含む）と合計を出す"""
        rows = [row(1, cost=7.7, minutes=21.0), row(2, cost=None, cost_read=False, minutes=24.0)]
        text = core_chain.render(doc_of(rows, rounds_max=2, stop={"word": "rounds_reached", "text": core_chain.STOPS["rounds_reached"]}))
        lines = text.splitlines()
        self.assertTrue(lines[2].startswith("- 何が起きたか"), lines[:5])
        self.assertTrue(lines[3].startswith("- 止めた訳"))
        self.assertTrue(lines[4].startswith("- 人が見る物"))
        table = [l for l in lines if l.startswith("|")]
        self.assertIn("分", table[0])
        self.assertEqual(len(table), 4)
        self.assertIn("7.70", table[2])
        self.assertIn("読めない", table[3])
        self.assertNotIn("0.00", text)
        total = next(l for l in lines if l.startswith("合計"))
        self.assertIn("45 分", total)
        self.assertIn("$7.70", total)
        self.assertIn("読めない周 1 本", total)

    def test_open_r2_redesign_is_said_in_head(self):
        """最後に採った周の種が open で R2 の作り直しが残れば、頭に「閉じていない（独立の目 R2 の作り直しが残る）」を出す"""
        rows = [row(1), row(2, r2=1)]
        text = core_chain.render(doc_of(rows, rounds_max=2, stop={"word": "rounds_reached", "text": "t"}))
        self.assertIn("閉じていない（独立の目 R2 の作り直しが残る）", "\n".join(text.splitlines()[:6]))
        self.assertNotIn("閉じていない", core_chain.render(doc_of([row(1), row(2)], rounds_max=2, stop={"word": "x", "text": "t"})))
        closed = core_chain.render(doc_of([row(1, core_chain.KIND_CLOSED, r2=1)], stop={"word": "closed", "text": "t"}))
        self.assertNotIn("閉じていない", closed)

    def test_human_stop_says_how_to_restart_without_resume(self):
        """人が要るで止めた鎖は、続けずに下書きを見直して新しい鎖を起こす手順を書く（保留して続ける口は無い）"""
        rows = [row(1, held_rows=[carry.draft(FINDING, "purpose")], next_file="/b/next-request.json")]
        text = core_chain.render(doc_of(rows, stop={"word": "human", "text": core_chain.STOPS["human"]}))
        self.assertIn("新しい鎖を起こす", text)
        self.assertIn("/b/next-request.json", text)
        self.assertIn("運ばなかった下書きの行 1 件", text)

    def test_stopped_round_is_named_with_its_diff(self):
        text = core_chain.render(doc_of([row(1), row(2, stopped=["w", "by", "text"])], stop={"word": "halted", "text": "t"}))
        self.assertIn("止まった周 周 2", text)
        self.assertIn("/d/2.diff", text)


class Shell(unittest.TestCase):
    """殻の口（init → launched → bound → step）。core_chain.main を直に呼ぶ"""

    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        self.tmp = pathlib.Path(self._td.name)
        self.dir = self.tmp / "chains" / "c-1"
        self.first = self.tmp / "first.json"
        self.first.write_text(json.dumps({"findings": [FINDING], "answers": [{"question": "q1", "text": "答え"}], "pr": [12]}))

    def call(self, *argv):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            rc = core_chain.main(list(argv))
        self.assertEqual(rc, 0, argv)
        return out.getvalue().rstrip("\n")

    def init(self, rounds=2, env=("WORKS_USE_THICKNESS=2",)):
        self.call("init", f"--dir={self.dir}", "--id=c-1", f"--target={self.tmp}", f"--rounds={rounds}", "--budget=",
                  f"--request={self.first}", "--test-cmd=pytest -q", "--tdd-suite=/s.sh", "--use-sh=/u/use.sh", f"--pid={os.getpid()}",
                  *[f"--env={e}" for e in env])

    def finish(self, n, run, kind, *, result="r" * 40, diff=True, next_doc=None, same=False):
        """周 n の run の終わりを step に渡す（周の事実・差分・結果の木）"""
        board = self.tmp / f"board-{n}"
        board.mkdir(exist_ok=True)
        nxt = board / carry.NEXT_REQUEST_FILE
        nxt.write_text(json.dumps(next_doc or {"findings": [FINDING], "prior_failures": []}))
        facts = self.tmp / f"facts-{n}.json"
        facts.write_text(json.dumps({"outcome": "x", "kind": kind, "cost": 2.0, "cost_read": True, "minutes": 5.0,
                                     "stopped": None, "base_rev": "b" * 40, "r2": 0, "next_file": str(nxt)}))
        d = self.tmp / f"run-{run}.diff"
        if diff:
            d.write_text("diff --git a/x b/x\n+x\n")
        return self.call("--held", "step", f"--dir={self.dir}", f"--run={run}", f"--facts={facts}", f"--diff={d}",
                         f"--result={result}", "--result-tree=t1", f"--from-tree={'t1' if same else 't0'}")

    def test_one_round_then_launch_and_idempotent_step(self):
        """1 周目の終わりに次の周を起こす行を返し、控えに pending（起動の基は周の結果）と次の依頼を残す。同じ run を 2 度渡しても 2 本目を起こさない"""
        self.init()
        self.call("launched", f"--dir={self.dir}", "--from=" + "f" * 40)
        self.call("bound", f"--dir={self.dir}", "--run=run-1")
        out = self.finish(1, "run-1", core_chain.KIND_OPEN)
        self.assertEqual(out, "launch\t2\tc-1-2")
        doc = core_chain.load(self.dir)
        self.assertEqual(doc["original_base"], "b" * 40)
        self.assertEqual([r["run"] for r in doc["rounds"]], ["run-1"])
        pend = doc["pending"]
        self.assertEqual((pend["round"], pend["mark"], pend["from"], pend["run"]), (2, "c-1-2", "r" * 40, ""))
        req = json.loads(pathlib.Path(pend["request"]).read_text())
        parts = carry.parts(req)
        self.assertEqual((parts["findings"], parts["pr"], parts["answers"][0]["question"]), ([FINDING], [12], "q1"))
        # 子の pid を控えた後に同じ run の step を打ち直しても、生きている子を待つだけ
        self.call("--held", "pid", f"--dir={self.dir}", f"--pid={os.getpid()}", "--log=/l")
        self.assertEqual(self.finish(1, "run-1", core_chain.KIND_OPEN).split("\t")[0], "wait")
        self.assertEqual(len(core_chain.load(self.dir)["rounds"]), 1)
        self.call("bound", f"--dir={self.dir}", "--run=run-2")
        self.assertEqual(self.finish(1, "run-1", core_chain.KIND_OPEN), "follow\trun-2")
        self.assertTrue(self.call("pending", f"--dir={self.dir}").startswith("run-2\t"))

    def test_two_dead_launches_stop_with_launch_failed(self):
        """殻の口 pid は切り離して起こすたびに tries を 1 足す。起動の印の前で 2 度死ねば、打ち直した step は launch_failed で止まって
        pending を外し、chain.md に子の出力の置き場と新しい鎖を起こす手順が出る"""
        self.init()
        self.call("launched", f"--dir={self.dir}", "--from=" + "f" * 40)
        self.call("bound", f"--dir={self.dir}", "--run=run-1")
        self.assertEqual(self.finish(1, "run-1", core_chain.KIND_OPEN), "launch\t2\tc-1-2")
        log = str(self.tmp / "round-2.log")
        self.call("--held", "pid", f"--dir={self.dir}", f"--pid={dead_pid()}", f"--log={log}")
        self.assertEqual(core_chain.load(self.dir)["pending"]["tries"], 1)
        self.assertEqual(self.finish(1, "run-1", core_chain.KIND_OPEN), "launch\t2\tc-1-2")   # 1 度目の死は起こし直す
        self.call("--held", "pid", f"--dir={self.dir}", f"--pid={dead_pid()}", f"--log={log}")
        self.assertEqual(core_chain.load(self.dir)["pending"]["tries"], 2)
        out = self.finish(1, "run-1", core_chain.KIND_OPEN)
        self.assertTrue(out.startswith("stop\tlaunch_failed\t"), out)
        self.assertIn(log, out)
        doc = core_chain.load(self.dir)
        self.assertIsNone(doc["pending"])
        self.assertEqual(doc["stop"]["word"], "launch_failed")
        text = self.call("render", f"--dir={self.dir}")
        self.assertIn(log, text)
        self.assertIn("start --rounds", text)

    def test_last_round_stops_and_records_stop(self):
        """周の数に達した周の step は stop を返して控えに止めの語を残し、pending を外す。pick は最後の周を返す"""
        self.init(rounds=2)
        self.call("bound", f"--dir={self.dir}", "--run=run-1")
        self.finish(1, "run-1", core_chain.KIND_OPEN)
        self.call("--held", "pid", f"--dir={self.dir}", f"--pid={os.getpid()}", "--log=")
        self.call("bound", f"--dir={self.dir}", "--run=run-2")
        out = self.finish(2, "run-2", core_chain.KIND_OPEN, result="s" * 40, next_doc={"findings": [{"where": "k", "text": "別の残り"}]})
        self.assertEqual(out.split("\t")[:2], ["stop", "rounds_reached"])
        doc = core_chain.load(self.dir)
        self.assertEqual((doc["stop"]["word"], doc["pending"]), ("rounds_reached", None))
        self.assertEqual(self.call("pick", f"--dir={self.dir}"), f"2\trun-2\t{'s' * 40}\t{'b' * 40}")
        text = self.call("render", f"--dir={self.dir}")
        self.assertTrue((self.dir / core_chain.REPORT).is_file())
        self.assertIn("rounds_reached", text)

    def test_empty_diff_is_no_change(self):
        """差分が無い周は結果を作らず、周の頭の版のまま no_change で止める（採れる周が無い）"""
        self.init()
        self.call("bound", f"--dir={self.dir}", "--run=run-1")
        out = self.finish(1, "run-1", core_chain.KIND_OPEN, result="", diff=False)
        self.assertEqual(out.split("\t")[:2], ["stop", "no_change"])
        self.assertEqual(self.call("pick", f"--dir={self.dir}"), "")

    def test_unwritten_diff_halts(self):
        """差分を書けなかった周（show_run の終了コードが 4）は結果を作らず halted で止め、理由を残す"""
        self.init()
        self.call("bound", f"--dir={self.dir}", "--run=run-1")
        facts = self.tmp / "facts.json"
        facts.write_text(json.dumps({"kind": core_chain.KIND_OPEN, "base_rev": "b" * 40}))
        out = self.call("--held", "step", f"--dir={self.dir}", "--run=run-1", f"--facts={facts}", "--unwritten=差分を書けなかった")
        self.assertEqual(out.split("\t")[:2], ["stop", "halted"])
        self.assertIn("差分を書けなかった", out)

    def test_launch_unbound_stop_clears_pending_so_clean_can_remove_the_chain(self):
        """Archon を起こした後で死に run が結ばれないまま終わった起動（launched で pid が死んでいる）は launch_unbound で止め、pending を外す
        （残すと clean が名指す run の無い拒みで二度と片付けられない）"""
        self.init()
        self.call("bound", f"--dir={self.dir}", "--run=run-1")
        self.assertEqual(self.finish(1, "run-1", core_chain.KIND_OPEN).split("\t")[0], "launch")
        self.call("--held", "pid", f"--dir={self.dir}", f"--pid={dead_pid()}", "--log=")
        self.call("launched", f"--dir={self.dir}", "--from=" + "f" * 40)
        out = self.finish(1, "run-1", core_chain.KIND_OPEN)
        self.assertEqual(out.split("\t")[:2], ["stop", "launch_unbound"])
        doc = core_chain.load(self.dir)
        self.assertEqual((doc["pending"], doc["stop"]["word"]), (None, "launch_unbound"))

    def test_interrupted_round_is_not_recorded(self):
        """途中で落ちた周（種が wait）は周に足さず、pending も変えない。次の周が結ばれたと読ませる行（follow・launch）を返さない"""
        self.init()
        self.call("bound", f"--dir={self.dir}", "--run=run-1")
        before = core_chain.load(self.dir)
        out = self.finish(1, "run-1", core_chain.KIND_WAIT)
        self.assertEqual(out.split("\t")[0], "aborted")
        self.assertEqual(core_chain.load(self.dir), before)

    def test_facts_error_halts_and_other_run_is_none(self):
        self.init()
        self.call("bound", f"--dir={self.dir}", "--run=run-1")
        facts = self.tmp / "facts.json"
        facts.write_text(json.dumps({"error": "周の事実を読めない（x）"}))
        out = self.call("--held", "step", f"--dir={self.dir}", "--run=run-9", f"--facts={facts}")
        self.assertTrue(out.startswith("none\t"), out)
        out = self.call("--held", "step", f"--dir={self.dir}", "--run=run-1", f"--facts={facts}")
        self.assertEqual(out.split("\t")[:2], ["stop", "halted"])

    def test_plan_exports_env_and_ids_and_of_run(self):
        """次の周の起動が読む plan は、控えの環境を export 行にし、対象・依頼・起動の基・印を変数に置く。of-run は run から鎖の id を引く"""
        self.init(env=("WORKS_USE_THICKNESS=a b", "WORKS_DESIGN_ONLY="))
        self.call("bound", f"--dir={self.dir}", "--run=run-1")
        self.finish(1, "run-1", core_chain.KIND_OPEN)
        plan = self.call("plan", f"--dir={self.dir}")
        self.assertIn("export WORKS_USE_THICKNESS='a b'", plan)
        self.assertIn(f"CN_FROM={'r' * 40}", plan)
        self.assertIn("CN_MARK=c-1-2", plan)
        self.assertIn("CN_TDD_SUITE=/s.sh", plan)
        self.assertEqual(self.call("of-run", f"--home={self.tmp}", "--run=run-1"), "c-1")
        rc = core_chain.main(["of-run", f"--home={self.tmp}", "--run=run-none"])
        self.assertEqual(rc, 1)

    def test_first_pr_is_carried_in_the_request_not_the_input(self):
        """1 周目に名指した PR（init の --first-pr）は、次の周の依頼の pr 欄に載り（1 周目の依頼の pr と重ねても 1 本）、1 周目の依頼が
        無い鎖でも運ぶ"""
        for first in (str(self.first), ""):
            with self.subTest(first_request=bool(first)):
                self.call("init", f"--dir={self.dir}", "--id=c-1", f"--target={self.tmp}", "--rounds=2", "--budget=", f"--request={first}",
                          "--test-cmd=", "--tdd-suite=", "--use-sh=/u", "--pid=1", "--first-pr=7")
                self.call("bound", f"--dir={self.dir}", "--run=run-1")
                self.finish(1, "run-1", core_chain.KIND_OPEN)
                req = json.loads(pathlib.Path(core_chain.load(self.dir)["pending"]["request"]).read_text())
                self.assertEqual(carry.parts(req)["pr"], [7, 12] if first else [7])
                for stale in self.dir.glob("*"):
                    stale.unlink()

    def test_env_must_be_launch_names(self):
        """鎖の控えに持つ起動の環境は WORKS_USE_* か WORKS_DESIGN_ONLY の KEY=VALUE だけ（中身は読まない）"""
        for bad in ("PATH=/x", "WORKS_USE_X;touch y=1", "WORKS_USE_=1", "WORKS_USE_lower=1"):
            with self.subTest(env=bad), self.assertRaises(ValueError):
                core_chain.new_doc("c", target="/t", rounds=2, budget=None, request="", test_cmd="", tdd_suite="", env=[bad], use_sh="/u", pid=1)
        # 殻が eval する plan は、控えが書き換わっていても名の形を外した行を出さない
        self.init()
        doc = core_chain.load(self.dir)
        doc["env"] = ["WORKS_USE_X;touch y=1"]
        doc["pending"] = {"round": 2, "mark": "m", "pid": None, "launched": False, "run": "", "from": "f", "request": "", "log": ""}
        core_chain.save(self.dir, doc)
        err = io.StringIO()
        with contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(core_chain.main(["plan", f"--dir={self.dir}"]), 2)
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            rc = core_chain.main(["init", f"--dir={self.dir}", "--id=c-1", "--target=/t", "--rounds=2", "--request=", "--test-cmd=", "--tdd-suite=",
                             "--use-sh=/u", "--pid=1", "--env=HOME=/x"])
        self.assertEqual(rc, 2)

    def test_held_flag_does_not_retake_the_lock(self):
        """殻が錠を持ったまま呼ぶ口（--held）は錠を取り直さず、持ち手が自分でも固まらない。錠は別の持ち手を待たせる"""
        self.init()
        self.call("bound", f"--dir={self.dir}", "--run=run-1")
        with open(self.dir / core_chain.LOCK, "a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            self.call("--held", "pid", f"--dir={self.dir}", "--pid=7", "--log=/l")
            probe = open(self.dir / core_chain.LOCK, "a")
            try:
                with self.assertRaises(BlockingIOError):
                    fcntl.flock(probe, fcntl.LOCK_EX | fcntl.LOCK_NB)
            finally:
                probe.close()
        self.assertEqual(core_chain.load(self.dir)["pending"]["pid"], 7)


class Fences(unittest.TestCase):
    def test_chain_names_no_outcome_word(self):
        """結末の語を字で持てるのは結末の住処 report.py だけ。鎖は種（OUTCOME_KINDS）だけを引く"""
        import report
        text = (CORE / "chain.py").read_text(encoding="utf-8")
        for word in report.OUTCOMES:
            self.assertIsNone(re.search(rf"[\"']{word}[\"']", text), word)

    def test_layer_one_imports(self):
        """chain は標準ライブラリと同じ層 L1 の carry・promptsection（報告の見出しの宣言）だけを import する（層 L1）"""
        tree = ast.parse((CORE / "chain.py").read_text(encoding="utf-8"))
        names = {a.name.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
        names |= {n.module.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module}
        self.assertLessEqual(names - set(sys.stdlib_module_names), {"carry", "promptsection"})


if __name__ == "__main__":
    unittest.main()
