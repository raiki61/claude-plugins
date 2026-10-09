"""周の鎖の決め（.shared/core/chain.py。考え chain）の検査（計画 docs/plans/2026-10-09-chained-rounds.md の Task 3・6・7）。

鎖は `use.sh start --rounds N` が起こす、周ごとの普通の 1 周の run の並び。ここは殻を通さず、鎖の控え（chain.json の形の dict）
から止める条件の順・次の周の依頼・最後に採る周・鎖の報告の行を決める純粋な口と、周の行を盤面から組む口と、結末の種の表
（結末の住処 report の OUTCOME_KIND）・報告の結末の読み・費用の和を見る。関数を直に呼ぶだけ（一時の置き場のファイルのほか、
git・盤面・子のプロセスなし。柵の照らしは git ls-files を読む）。
"""
import json
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
sys.path.insert(0, str(ROOT / "dev"))

import carry  # noqa: E402
import report  # noqa: E402


def chain():
    import chain as m   # 住処（遅らせて読む。無ければその試験だけが落ちる）
    return m


def rnd(n, outcome="round_limit", *, cost=8.0, known=True, files=2, keys=("a.py\tk1",), held=0, result="r", stopped=False,
        minutes=20.0, diff_ok=True):
    """記録の済んだ周の行"""
    return {"n": n, "run_id": f"run-{n}", "base": f"b{n}", "result": result + str(n) if result else "", "outcome": outcome,
            "minutes": minutes, "cost_usd": cost if known else None, "cost_known": known, "open_keys": list(keys),
            "held": held, "held_rows": [], "files": files, "stopped": stopped, "diff_ok": diff_ok,
            "request_file": f"/c/round-{n}-request.json", "report_file": f"/b{n}/report.md", "diff_file": f"/d/run-run-{n}.diff"}


def doc(*rounds, n=3, budget=None):
    return {"id": "c-1", "target": "/t", "original_base": "b1", "rounds_max": n, "budget_usd": budget, "launch": {},
            "first_request": "", "rounds": list(rounds), "stop": None}


class OutcomeKind(unittest.TestCase):
    def test_every_outcome_has_kind(self):
        """結末の住処が、結末の語ごとに鎖が読む種（mended・closed・open・halted・waiting・broken）を持つ"""
        self.assertEqual(set(report.OUTCOME_KIND), set(report.OUTCOMES))
        self.assertLessEqual(set(report.OUTCOME_KIND.values()), set(report.OUTCOME_KINDS))
        self.assertEqual(report.OUTCOME_KIND["fixed"], "mended")
        self.assertEqual(report.OUTCOME_KIND["no_fix_needed"], "closed")
        self.assertEqual(report.OUTCOME_KIND["round_limit"], "open")
        self.assertEqual(report.OUTCOME_KIND["interrupted"], "broken")

    def test_read_outcome_from_the_report_head(self):
        """報告（report.md）の冒頭の起きたことの行の括弧の語を読む（無い・読めなければ空）。測りの殻も同じ口を引く"""
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(report.read_outcome(d), "")
            (pathlib.Path(d) / report.REPORT_FILE).write_text(
                "# 報告（run x）\n\n" + report.gatemarks.HAPPENED + ": 直しきれずに残った（round_limit）\n", encoding="utf-8")
            self.assertEqual(report.read_outcome(d), "round_limit")
        import canary_check
        self.assertFalse(hasattr(canary_check, "outcome"), "測りの殻が報告の結末の読みを自分で持たない（住処の口を引く）")

    def test_spent_sums_node_costs_and_says_when_unknown(self):
        """節の費用の和（輪の集計の行は数えない）。取れない節が 1 つでも在るか、出来事が無ければ和は言えない"""
        def ev(name, v, agg=False):
            data = {"spend": {"costUsd": {"source": "provider", "value": v}}} if v is not None else {
                "spend": {"costUsd": {"source": "unavailable", "reason": "not_reported"}}}
            if agg:
                data["accounting"] = "aggregate"
            return {"event_type": "node_completed", "step_name": name, "data": data}
        self.assertEqual(report.spent([ev("a", 1.5), ev("b", 2.0), ev("loop", 9.0, agg=True)]), (3.5, 0))
        self.assertEqual(report.spent([ev("a", 1.5), ev("b", None)]), (None, 1))
        self.assertEqual(report.spent(None), (None, 0))
        self.assertEqual(report.spent([]), (None, 0))


class Verdict(unittest.TestCase):
    def v(self, d, confirm=True):
        return chain().verdict(d, confirm=confirm)

    def test_stop_order(self):
        """決まった順: 周の数 → 結末の種 → 人の判断 → 進みの無さ → 費用 → 次へ"""
        c = chain()
        cases = [
            ("rounds_reached", doc(rnd(1), rnd(2), rnd(3, "fixed"), n=3)),
            ("halted", doc(rnd(1, "stopped_by_human"))),
            ("human", doc(rnd(1, "needs_human"))),
            ("human", doc(rnd(1, held=2))),
            ("no_change", doc(rnd(1, files=0))),
            ("same_items", doc(rnd(1), rnd(2))),
            ("budget", doc(rnd(1, cost=15.0), budget=20.0)),
            ("go", doc(rnd(1), rnd(2, keys=("b.py\tk2",)))),
        ]
        for word, d in cases:
            with self.subTest(word):
                got = self.v(d)
                self.assertEqual(got["word"], word, got)
                self.assertEqual(got["go"], "go" if word == "go" else "stop")
                if word != "go":
                    self.assertIn(word, c.STOPS)
                self.assertTrue(got["text"])

    def test_rounds_reached_wins_over_the_outcome(self):
        """N に達した周が fixed でも語は rounds_reached"""
        self.assertEqual(self.v(doc(rnd(1), rnd(2, "fixed"), n=2))["word"], "rounds_reached")

    def test_fixed_with_rounds_left_confirms(self):
        """fixed で周が残れば、直しを確かめる周（依頼の行を空にした周）を 1 回足す。確かめない形なら closed で止める。
        no_fix_needed はいつも closed"""
        got = self.v(doc(rnd(1, "fixed", keys=())))
        self.assertEqual((got["go"], got["next_empty"]), ("go", True))
        self.assertEqual(self.v(doc(rnd(1, "fixed", keys=())), confirm=False)["word"], "closed")
        self.assertEqual(self.v(doc(rnd(1, "fixed", keys=()), rnd(2, "no_fix_needed", keys=(), files=0)))["word"], "closed")

    def test_confirm_round_is_bounded_by_budget(self):
        self.assertEqual(self.v(doc(rnd(1, "fixed", keys=(), cost=15.0), budget=20.0))["word"], "budget")

    def test_drafts_stop_for_human(self):
        got = self.v(doc(rnd(1, held=1)))
        self.assertEqual((got["go"], got["word"]), ("stop", "human"))

    def test_unattended_gate_stop_with_drafts_is_human(self):
        """無人の run が関所で止めた周（結末は止まり）でも、答えの下書きが在れば語は human（人の判断が要る）"""
        got = self.v(doc(rnd(1, "stopped_by_human", held=2)))
        self.assertEqual((got["go"], got["word"]), ("stop", "human"))

    def test_empty_diff_is_no_change(self):
        self.assertEqual(self.v(doc(rnd(1, files=0)))["word"], "no_change")

    def test_same_keys_twice_stop(self):
        self.assertEqual(self.v(doc(rnd(1, keys=("x\t1", "y\t2")), rnd(2, keys=("y\t2", "x\t1"))))["word"], "same_items")
        self.assertEqual(self.v(doc(rnd(1, "fixed", keys=()), rnd(2, "fixed", keys=()), n=4))["go"], "go",
                         "空の残りどうしは同じと数えない（確かめの周が続けて直した時）")

    def test_budget_predicts_next_round(self):
        """上限 $20・累計 $15・最大の周 $8 → 次の周で越えうるので起こさない。累計 $10 なら起こす"""
        self.assertEqual(self.v(doc(rnd(1, cost=7.0), rnd(2, cost=8.0, keys=("z\t9",)), n=5, budget=20.0))["word"], "budget")
        self.assertEqual(self.v(doc(rnd(1, cost=4.0), rnd(2, cost=6.0, keys=("z\t9",)), n=5, budget=20.0))["go"], "go")

    def test_unknown_cost_stops_only_with_budget(self):
        self.assertEqual(self.v(doc(rnd(1, known=False), budget=20.0))["word"], "cost_unknown")
        self.assertEqual(self.v(doc(rnd(1, known=False)))["go"], "go")

    def test_interrupted_waits(self):
        got = self.v(doc(rnd(1, "interrupted")))
        self.assertEqual(got["go"], "wait")

    def test_unwritten_diff_stops(self):
        """周の差分を書けなかった（結果の版を作れない）周で止め、訳を言う"""
        got = self.v(doc(rnd(1, result="", diff_ok=False)))
        self.assertEqual((got["go"], got["word"]), ("stop", "no_result"))


class NextRequest(unittest.TestCase):
    ROUND = {"findings": [{"where": "a.py", "text": "残り"},
                          carry.draft({"where": "b.py", "text": "外の所見"}, "前の run の判定が目的の外とした所見")],
             "prior_failures": [{"where": "受け付け fix", "text": "理由"}],
             "answers": [{"question": "q-1", "text": "run r の関所で人が決めた: 例外"},
                         carry.draft({"question": "q-2", "text": ""}, "台帳の問い", "選ぶ")]}

    def test_next_request_drops_drafts_and_keeps_first_answers(self):
        first = {"findings": [{"where": "x", "text": "y"}], "pr": [3], "answers": [{"question": "q-0", "text": "最初の決め"},
                                                                                 {"question": "q-1", "text": "古い"}]}
        req, held = chain().next_request(self.ROUND, first)
        self.assertEqual(req["findings"], [{"where": "a.py", "text": "残り"}])
        self.assertEqual(req["pr"], [3])
        self.assertEqual(req["prior_failures"], self.ROUND["prior_failures"])
        self.assertEqual({a["question"]: a["text"] for a in req["answers"]},
                         {"q-0": "最初の決め", "q-1": "run r の関所で人が決めた: 例外"})
        self.assertEqual([r.get("where") or r.get("question") for r in held], ["b.py", "q-2"])
        carry.parts(req)   # 依頼の入口が受ける

    def test_next_request_without_first_request(self):
        """1 周目の依頼が -（--base か --pr だけ）でも、前の周の残りだけで組む"""
        req, _ = chain().next_request(self.ROUND, None)
        self.assertEqual(req["findings"], [{"where": "a.py", "text": "残り"}])
        self.assertNotIn("pr", req)
        carry.parts(req)

    def test_confirm_round_has_no_lines(self):
        req, _ = chain().next_request(self.ROUND, None, empty=True)
        self.assertEqual(req["findings"], [])
        self.assertTrue(req["answers"])


class Record(unittest.TestCase):
    def test_round_record_reads_the_board(self):
        """周の行は盤面の報告の結末・次の依頼の下書きの残りの鍵と下書きの数・止まりかを読み、差分のファイルの数を数える"""
        c = chain()
        with tempfile.TemporaryDirectory() as d:
            board = pathlib.Path(d) / "board"
            board.mkdir()
            (board / report.REPORT_FILE).write_text(f"{report.gatemarks.HAPPENED}: x（round_limit）\n", encoding="utf-8")
            carry.write(board / carry.NEXT_REQUEST_FILE, self_round())
            diff = pathlib.Path(d) / "run.diff"
            diff.write_text("diff --git a/a.py b/a.py\n--- a/a.py\n+++ b/a.py\ndiff --git a/b.py b/b.py\n", encoding="utf-8")
            row = c.recorded(c.round_row(1, "run-1", "b1"), board=board, diff=diff, result="r1", minutes=12.5,
                             cost=(3.0, 0), diff_ok=True)
            self.assertEqual(row["outcome"], "round_limit")
            self.assertEqual(row["open_keys"], [carry.row_key({"where": "a.py", "text": "残り"})])
            self.assertEqual(row["held"], 2)
            self.assertEqual(len(row["held_rows"]), 2)
            self.assertEqual(row["files"], 2)
            self.assertEqual((row["cost_usd"], row["cost_known"]), (3.0, True))
            self.assertFalse(row["stopped"])
            self.assertEqual(row["report_file"], str(board / report.REPORT_FILE))
            self.assertEqual(c.recorded(c.round_row(1, "run-1", "b1"), board=board, diff=None, result="r1", minutes=None,
                                        cost=(None, 2), diff_ok=True)["cost_known"], False)


def self_round():
    return NextRequest.ROUND


class SaveLoad(unittest.TestCase):
    def test_save_then_load(self):
        c = chain()
        with tempfile.TemporaryDirectory() as d:
            p = pathlib.Path(d) / "chain.json"
            got = c.new("c-1", "/t", "b1", 3, None, {"test_cmd": "", "tdd_suite": "", "env": {}}, "")
            got["rounds"].append(c.round_row(1, "run-1", "b1"))
            c.save(p, got)
            self.assertEqual(c.load(p), got)
            self.assertFalse(list(pathlib.Path(d).glob("*.tmp")))


class Final(unittest.TestCase):
    def test_final_round_skips_a_stopped_last_round(self):
        c = chain()
        self.assertEqual(c.final_round(doc(rnd(1), rnd(2))), 2)
        self.assertEqual(c.final_round(doc(rnd(1), rnd(2, "stopped_by_human", stopped=True))), 1)
        self.assertIsNone(c.final_round(doc(rnd(1, "stopped_by_line", stopped=True))))
        self.assertEqual(c.final_round(doc(rnd(1), rnd(2, result="", diff_ok=False))), 1)


class Report(unittest.TestCase):
    def stopped(self, *rounds, word="rounds_reached"):
        d = doc(*rounds)
        d["stop"] = {"word": word, "text": chain().STOPS[word]}
        return d

    def test_report_head_three_lines(self):
        lines = chain().report_lines(self.stopped(rnd(1), rnd(2, keys=("b\t2",)), rnd(3, "fixed", keys=())),
                                     final_diff="/c/final.diff", apply_line="sh use.sh apply /t c-1")
        self.assertIn("3 周", lines[0])
        self.assertIn(chain().STOPS["rounds_reached"], lines[1])
        self.assertTrue(lines[2])

    def test_report_rows_per_round_and_totals(self):
        lines = chain().report_lines(self.stopped(rnd(1, cost=7.7, minutes=21.0), rnd(2, "fixed", cost=8.1, minutes=24.0, keys=())),
                                     final_diff="/c/final.diff", apply_line="sh use.sh apply /t c-1")
        text = "\n".join(lines)
        self.assertIn("| 1 | run-1 | round_limit | 21 | 7.70 | 1 | 2 |", text)
        self.assertIn("| 2 | run-2 | fixed | 24 | 8.10 | 0 | 2 |", text)
        self.assertIn("45 分", text)
        self.assertIn("15.80", text)
        self.assertIn("/c/final.diff", text)
        self.assertIn("sh use.sh apply /t c-1", text)
        self.assertIn("/b1/report.md", text)

    def test_report_names_held_drafts(self):
        r = {**rnd(1, held=1), "held_rows": ["q-2: 選ぶ"]}
        text = "\n".join(chain().report_lines(self.stopped(r, word="human"), final_diff="", apply_line=""))
        self.assertIn("q-2: 選ぶ", text)

    def test_report_cost_unknown_is_named(self):
        text = "\n".join(chain().report_lines(self.stopped(rnd(1, known=False), rnd(2, cost=8.0)), final_diff="",
                                              apply_line=""))
        self.assertIn("取れない", text)
        self.assertNotIn("| 1 | run-1 | round_limit | 20 | 0.00", text)

    def test_report_names_the_excluded_stopped_round(self):
        text = "\n".join(chain().report_lines(self.stopped(rnd(1), rnd(2, "stopped_by_human", stopped=True), word="halted"),
                                              final_diff="/c/final.diff", apply_line=""))
        self.assertIn("/d/run-run-2.diff", text)


class Fence(unittest.TestCase):
    def test_chain_words_live_in_chain(self):
        """柵の表の chain（鎖の止めの語・控えの名）が住処の外に漏れない。結末の語は鎖が字で持たない（柵 outcome）"""
        import conceptfence as m
        table = m.load(ROOT)
        row = table["concepts"]["chain"]
        self.assertEqual(row["status"], "住処あり")
        paths = m.tracked(ROOT)
        for f in row["fences"] + table["concepts"]["outcome"]["fences"]:
            self.assertEqual(m.verdict(m.scan(ROOT, paths, f, table["exclude"]), f["known"]), [], f["what"])
        self.assertIn(".shared/core/chain.py", row["fences"][0]["allowed"])


if __name__ == "__main__":
    unittest.main()
