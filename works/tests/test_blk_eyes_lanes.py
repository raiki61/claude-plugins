"""blk-eyes の筋の並びの振る舞い: YAML の depends_on・trigger_rule・when のとおりに節を起こし（Archon の約束は scriptline と
同じ）、同じ層で起こせる節は R4 の筋を先に起こす（並んで走る筋の一番悪い順）。スクリプトは lib/eyes の口を直に呼ぶ"""
import json
import pathlib
import sys
import unittest
from unittest import mock

import test_blk_eyes as TB
from test_blk_eyes import ROOT, eyes, entry, BoardGap

import gatemarks
import scriptline

setUpModule, tearDownModule = TB.setUpModule, TB.tearDownModule

LOST = "BASE の X が消える"
SCOPE_LOST = {**TB.SCOPE_OK, "capability_inventory": {"fired": True, "lost": [LOST]}}


def line_edge():
    lib = str(ROOT / "darkfactory" / "lib")
    if lib not in sys.path:
        sys.path.insert(0, lib)
    import line_edge as le
    return le


FAILED_UP = "failed_up"   # 上流の落ちで飛んだ節（Archon の skipped の cause upstream_failed）


def triggered(rule, states) -> bool:
    """Archon v0.11.1 の checkTriggerRule（packages/workflows/src/dag-executor.ts）の写し。直の上流の状態だけを見て、
    none_failed_min_one_success は落ちた節と、上流の落ちで飛んだ節（FAILED_UP）で飛ぶ"""
    if (rule or "all_success") == "all_done":
        return True
    if rule == scriptline.NFMOS:
        return not {"failed", FAILED_UP} & set(states) and (not states or "ok" in states)
    return all(s == "ok" for s in states)


def block_sinks(doc) -> list:
    """ブロックの中で後ろに節を持たない節。Archon の include の展開（v0.11.1 の include-expander.ts）は、線の depends_on: [<include>]
    をこの全部に付け替える"""
    used = {d for n in doc["nodes"] for d in n.get("depends_on") or []}
    return [n["id"] for n in doc["nodes"] if n["id"] not in used]


class LaneRun:
    """blk-eyes の上の節を YAML のとおりに回す。fail の節は落ちる（Archon の節の失敗）。drift の役の route は、盤面に待っている
    目が在っても go: false を返す（盤面の順と筋のずれ）。seen[<節>] は r4.human_gate が聞いた時点の目の状態"""

    def __init__(self, case, replies=None, fail=(), drift=()):
        self.case, self.replies, self.fail, self.drift = case, {**TB.REPLY, **(replies or {})}, set(fail), set(drift)
        self.status, self.out, self.seen, self.order = {}, {}, None, []
        self.failed_up = set()

    def joined(self, nid) -> str:
        """Archon の trigger_rule が見る節の状態（上流の落ちで飛んだ節は FAILED_UP）"""
        return FAILED_UP if self.status[nid] == "skipped" and nid in self.failed_up else self.status[nid]

    def _go(self, n):
        st = [self.joined(d) for d in n.get("depends_on") or []]
        go = triggered(n.get("trigger_rule"), st)
        if not go and {"failed", FAILED_UP} & set(st):
            self.failed_up.add(n["id"])
        if go and n.get("when"):
            nid, field, want = scriptline.WHEN.match(n["when"]).groups()
            go = self.status.get(nid) == "ok" and self.out[nid].get(field) is (want == "true")
        return go

    def _round(self):
        return self.out["eyes-enter"]["round"] if self.status.get("eyes-enter") == "ok" else ""

    def _loop(self, role):
        c = self.case
        for _ in range(eyes.GIVE_UP_AFTER):
            eyes.prep(c.bd, role, c.rnd, c.repo)
            got = eyes.accept(c.bd, role, json.dumps(self.replies[role], ensure_ascii=False), c.repo)
            if got["done"]:
                break
        b = entry.open_board(c.bd, allow_halted=True)
        if self.seen is None and b.state.get("pending_human"):
            self.seen = {r: eyes._node_state(b, c.rnd, n) for r, n in eyes.NODE_OF.items()}
        return got

    def _call(self, nid):
        c = self.case
        if nid == "eyes-enter":
            got = eyes.enter(c.bd, c.repo)
            c.rnd = got["round"]
            return got
        if nid == "eyes-collect":
            return eyes.collect(c.bd, self._round())
        role, kind = nid.rsplit("-", 1)
        if kind == "loop":
            return self._loop(role)
        if role in self.drift:
            with mock.patch.object(eyes, "_pending", return_value=None):
                return eyes.route(c.bd, role, self._round())
        return eyes.route(c.bd, role, self._round())

    def run(self):
        nodes = TB.workflow()["nodes"]
        todo = list(nodes)
        while todo:
            ready = [n for n in todo if all(d in self.status for d in n.get("depends_on") or [])]
            n = min(ready, key=lambda x: (not x["id"].startswith("r4-"), todo.index(x)))
            todo.remove(n)
            nid = n["id"]
            self.order.append(nid)
            if not self._go(n):
                self.status[nid] = "skipped"
            elif nid in self.fail:
                self.status[nid] = "failed"
            else:
                self.out[nid], self.status[nid] = self._call(nid), "ok"
        return self


class R4AfterR1R2Case(TB._Case):
    def test_r1_minimality_is_out_before_r4_asks(self):
        """R4 が lost を返して r4.human_gate が人に聞く周でも、聞いた時点で r1.minimality は出し切っていて、出口の R1 と最後の
        関所の R1 の行に結果が在る"""
        self.board("all4")
        run = LaneRun(self, replies={"r4-scope": SCOPE_LOST}).run()
        self.assertIsNotNone(run.seen, "r4.human_gate が聞いた（この試験の前提）")
        self.assertIn(run.seen["r1-minimality"], ("done", "na", "skipped", "stopped"), run.seen)
        out = run.out["eyes-collect"]
        self.assertTrue(out["asking"], out)
        self.assertIsInstance(out["reviews"]["R1"], dict, out["reviews"])
        rows = line_edge()._eyes(entry.open_board(self.bd, allow_halted=True)).rows
        self.assertFalse([r for r in rows if "（R1）" in r and "結果が無い" in r], rows)

    def test_h_look_not_go_leaves_eyes_unstarted(self):
        """h-look が go でない時は blk-eyes を丸ごと起こさない（R4 も走らない）"""
        eyeing = next(n for n in scriptline.flow("darkfactory")["nodes"] if n.get("include") == "blk-eyes")
        scope = scriptline.Scope("darkfactory", {})
        scope.status.update({d: "ok" for d in eyeing["depends_on"]})
        scope.out.update({d: {"go": False} for d in eyeing["depends_on"]})
        self.assertFalse(scriptline.ScriptLine._runs(None, scope, eyeing, False))


class FallenLaneCase(TB._Case):
    def _fell(self, fail, lane):
        self.board("all4")
        run = LaneRun(self, fail=fail).run()
        self.assertEqual(run.status["r4-scope-route"], "ok", "前の筋が落ちても R4 の筋は飛ばされない")
        self.assertTrue(run.out["r4-scope-route"]["go"])
        self.assertIn(f"{lane} の筋が落ちたまま R4 を回した", run.out["r4-scope-route"]["why"])
        self.assertEqual(run.status["r4-scope-loop"], "ok")
        self.assertEqual(run.status["eyes-collect"], "ok", "出口も飛ばされない")
        out = run.out["eyes-collect"]
        self.assertTrue(out["ok"], "落ちた筋だけが残った周は止めずに理由を返す（include を失敗にしない）")
        self.assertIn(f"{lane} の筋が落ち", out["reason"])
        self.assertNotIn("stop", TB.state(self.bd))
        self.assertIs(eyes.LANES_NAME, gatemarks.LANES_NAME, "書き手と最後の関所の読み手は同じ名前の正本を引く")
        rows = line_edge()._eyes(entry.open_board(self.bd, allow_halted=True)).rows
        self.assertTrue([r for r in rows if r.startswith("  - 落ちた筋: ") and f"{lane} の筋が落ちたまま R4 を回した" in r], rows)
        # 線の最後の関所の境 h-final は、include eyeing をブロックの sink 全部として待つ。落ちた筋の失敗がそこへ連鎖しない
        h_final = next(n for n in scriptline.flow("darkfactory")["nodes"] if n["id"] == "h-final")
        states = [run.joined(s) if d == "eyeing" else "ok" for d in h_final["depends_on"]
                  for s in (block_sinks(TB.workflow()) if d == "eyeing" else [d])]
        self.assertTrue(triggered(h_final.get("trigger_rule"), states),
                        f"h-final（{h_final.get('trigger_rule')}）が飛ぶ: sink の状態 "
                        f"{ {s: run.joined(s) for s in block_sinks(TB.workflow())} }")

    def test_r1_lane_fails_r4_still_runs_and_reason_reaches_final_gate(self):
        self._fell({"r1-minimality-route"}, "R1")

    def test_r2_lane_fails_r4_still_runs_and_reason_reaches_final_gate(self):
        self._fell({"r2-compare-route"}, "R2")

    def test_drift_stops_board_as_before_and_does_not_claim_a_fall(self):
        """route が go: false を返して目が残った周（盤面の順と筋のずれ）は落ちた筋と名乗らず、今どおり盤面を止める"""
        self.board("all4")
        run = LaneRun(self, drift={"r1-minimality"}).run()
        self.assertNotIn("落ちた", run.out["r4-scope-route"]["why"])
        out = run.out["eyes-collect"]
        self.assertFalse(out["ok"])
        self.assertIn("盤面の順とブロックの筋がずれた", out["reason"])
        self.assertNotIn("落ちた", out["reason"])
        self.assertEqual(TB.state(self.bd)["stop"]["by"], eyes.STOP_BY)
        self.assertFalse((pathlib.Path(self.bd) / f"r{self.rnd}" / eyes.LANES_NAME).exists())

    def test_enter_failed_does_not_start_r4(self):
        """入口が落ちた周: all_done で起きた R4 の route は目を起こさず、出口は入口の落ちを名指す"""
        self.board("all4")
        run = LaneRun(self, fail={"eyes-enter"})
        with self.assertRaises(BoardGap) as cm:
            run.run()
        self.assertIn("eyes-enter", str(cm.exception))
        self.assertEqual(run.status["r4-scope-route"], "ok")
        self.assertFalse(run.out["r4-scope-route"]["go"])
        self.assertEqual(run.status["r4-scope-loop"], "skipped")


if __name__ == "__main__":
    unittest.main()
