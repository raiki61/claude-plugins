"""works の周の添え書き rounds/works/round-<N>.json（仕様 4.5・9.1 の 9）。

周の記録（p4.record）が済んだ settle と、止めた周の記録を書いた stop が、表の absent の全部（このラインに無い節）と
その周での終わり方・素材の状態、省いた節、engine が確かめた CI かを書く。写しの検証器（RR）は rounds/ の下の
ディレクトリを読み飛ばすので、添え書きは周の記録の判定を変えない。
"""
import dataclasses
import json
import os
import pathlib
import shutil
import sys
import tempfile
import unittest
from unittest import mock

sys.dont_write_bytecode = True
HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import boardreplay as R  # noqa: E402
from board import GRAPH_PATH, GRAPH_SHA, NodeEntry, NodeTable  # noqa: E402
import engine.util as engine_util  # noqa: E402

GRAPH = json.loads(GRAPH_PATH.read_text(encoding="utf-8"))
EVERYTHING = NodeTable.everything(GRAPH, GRAPH_SHA)
# 表の absent: p1.procedure_trace（素材を持つ）・r3.coherence（test_converges の 1 周目はどちらも条件に当たらない na）・
# p4.final_gates（p4.record の後。条件に当たれば skipped）
ABSENT = {"p1.procedure_trace": ("手続きの追跡はこのラインに無い（検査用）", ""),
          "r3.coherence": ("R3 はこのラインに無い（検査用）", "R 系のブロック（未定）"),
          "p4.final_gates": ("最後の関門はこのラインに無い（検査用）", "")}
TABLE = dataclasses.replace(EVERYTHING, line="note-test", nodes={
    **EVERYTHING.nodes, **{n: NodeEntry(by="absent", reason=r, comes_with=c) for n, (r, c) in ABSENT.items()}})


def step_of(scenario, kind, node=None, nth=0, raised=False):
    got = [s for rs in R.load_runs(scenario).values() if R.replayable(rs) for s in rs
           if s["kind"] == kind and (node is None or s.get("node") == node) and bool(s.get("raised")) == raised]
    return got[nth]


class RoundNoteCase(unittest.TestCase):
    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp(prefix="board-note-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        env = mock.patch.dict(os.environ, R.git_env())
        env.start()
        self.addCleanup(env.stop)
        cwd = engine_util.GIT_CWD
        self.addCleanup(setattr, engine_util, "GIT_CWD", cwd)
        self.n = 0

    def board_before(self, step, table=TABLE):
        self.n += 1
        d, _ = R.restore(step.run_steps, step["seq"], "before", self.tmp / f"s{self.n}")
        return R.board_from_memory(R.memory_at(step.run_steps, step["seq"], "before"), d, table)

    def recorded(self):
        """p4.record の手の前（test_converges の 1 周目）から settle した盤面"""
        b = self.board_before(step_of("test_converges", "builtin", "p4.record"))
        self.assertFalse((b.dir / "rounds" / "works").exists())
        b.settle()
        self.assertIn("p4.record", b.state["rounds"][0]["done"])
        return b

    def note(self, b, n):
        return json.loads((b.dir / "rounds" / "works" / f"round-{n}.json").read_text(encoding="utf-8"))

    def test_note_after_record(self):
        """p4.record の後に rounds/works/round-1.json。not_in_line が表の absent の全部（条件で na の節も in_round="na" で）"""
        b = self.recorded()
        doc = self.note(b, 1)
        self.assertEqual(set(doc), {"round", "line", "table_sha", "not_in_line", "skipped_optional", "checks"})
        self.assertEqual((doc["round"], doc["line"], doc["table_sha"]), (1, "note-test", TABLE.sha()))
        rows = {r["node"]: r for r in doc["not_in_line"]}
        self.assertEqual(set(rows), set(ABSENT))
        self.assertEqual([r["node"] for r in doc["not_in_line"]], [a["node"] for a in TABLE.absent()])
        for nid, (reason, comes) in ABSENT.items():
            self.assertEqual((rows[nid]["reason"], rows[nid]["comes_with"]), (reason, comes))
        self.assertEqual(rows["r3.coherence"]["in_round"], "na")
        self.assertEqual(rows["p1.procedure_trace"]["in_round"], "na")
        first = b.state["rounds"][0]
        want = "skipped" if "p4.final_gates" in first["skipped"] else "na"
        self.assertEqual(rows["p4.final_gates"]["in_round"], want)
        # 素材: その節が書く素材（graph の materials）の、周の記録の状態
        rnd = json.loads((b.dir / "rounds" / "round-1.json").read_text(encoding="utf-8"))
        for nid in ABSENT:
            mats = GRAPH["nodes"][nid].get("materials", [])
            self.assertEqual(rows[nid]["materials"], {m: (rnd["materials"].get(m) or {}).get("status") for m in mats})
        self.assertTrue(any(rows[n]["materials"] for n in ABSENT), "素材を持つ absent の節が無い（試験の前提が崩れた）")
        # na でない absent は engine の skip と同じく周の箱の skipped に在り、添え書きの skipped_optional には出ない
        self.assertEqual(doc["skipped_optional"], [])

    def test_note_skipped_optional(self):
        """ラインが skip で省いた節（graph で optional）は skipped_optional に理由つきで出る（absent の節は出ない）"""
        table = dataclasses.replace(TABLE, nodes={**TABLE.nodes, "p2.history": NodeEntry(by="role", skippable=True)})
        b = self.board_before(step_of("test_converges", "accept", "p2.history"), table=table)
        b._skip_record("p2.history", "検査用に省く")
        b.rd["skipped"]["p4.final_gates"] = "最後の関門はこのラインに無い（検査用）"
        doc = json.loads(b._write_round_note(b.round).read_text(encoding="utf-8"))
        self.assertEqual(doc["round"], b.round)
        self.assertEqual(doc["skipped_optional"], [{"node": "p2.history", "reason": "検査用に省く"}])

    def test_note_checks(self):
        """checks は process.checks のその周の分（CI を engine が確かめたか・役の自己申告か）"""
        b = self.recorded()
        doc = self.note(b, 1)
        self.assertEqual(doc["checks"], {"p0.local_checks": {"by": "engine"}, "p4.ci": {"by": "engine"}})
        # 任せ先に落ちた節は by: role と理由
        b.record["process"]["checks"]["p4.ci"] = {"round": 1, "by": "role", "why": "宣言が無い（検査用）"}
        b.record["process"]["checks"]["old"] = {"round": 0, "by": "engine"}
        b._write_round_note(1)
        self.assertEqual(self.note(b, 1)["checks"]["p4.ci"], {"by": "role", "why": "宣言が無い（検査用）"})
        self.assertNotIn("old", self.note(b, 1)["checks"])

    def test_note_after_stop(self):
        """止めた周にも添え書き（stop が止めた周の記録を書いた後）"""
        s = step_of("test_stop_midround", "stop")
        b = self.board_before(s)
        rnd = b.round
        self.assertFalse((b.dir / "rounds" / "works" / f"round-{rnd}.json").exists())
        b.stop(s["args"]["reason"], "stop")
        self.assertTrue((b.dir / "rounds" / f"round-{rnd}.json").exists())
        doc = self.note(b, rnd)
        self.assertEqual({r["node"] for r in doc["not_in_line"]}, set(ABSENT))
        self.assertTrue(all(r["in_round"] in ("na", "skipped", "stopped", "pending") for r in doc["not_in_line"]))

    def test_validator_ignores_note_dir(self):
        """写しの RR に rounds/ を渡しても、works/ の下（添え書き）は読み飛ばす: 添え書きの有無で exit と出力が変わらない"""
        b = self.recorded()
        self.assertTrue((b.dir / "rounds" / "works" / "round-1.json").exists())
        bare = self.tmp / "bare-rounds"
        shutil.copytree(b.dir / "rounds", bare, ignore=shutil.ignore_patterns("works"))
        self.assertFalse((bare / "works").exists())
        got = b.run_validator(b.dir / "rounds")
        want = b.run_validator(bare)
        self.assertIn(got["exit"], (0, 1))
        self.assertEqual(got["exit"], want["exit"])
        self.assertEqual(got["out"].replace(str(b.dir / "rounds"), "@R@"), want["out"].replace(str(bare), "@R@"))


if __name__ == "__main__":
    unittest.main()
