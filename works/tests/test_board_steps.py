"""盤面の手本（tests/boards/golden-a1202d0/）を 1 手ずつ DiskBoard に当てる試験（仕様 9.3 の「1 手ずつ」・9.1 の 6）。

手の前の記憶とディスクとリポジトリを一時の場所に戻し、DiskBoard を記憶から組み（表は NodeTable.everything）、
同じ手を settle しない口で当て、手の後の記憶とディスクと比べる（boardreplay.compare。NOT_REPRODUCED の欄を除く）。
この Task（4a）で当てるのは役の返答の受け付け（kind=accept → DiskBoard.accept）。
"""
import contextlib
import copy
import dataclasses
import hashlib
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

import boardreplay as R  # noqa: E402  （board と写しの engine を sys.path に足す）
from board import GRAPH_PATH, GRAPH_SHA, BoardGap, NodeEntry, NodeTable  # noqa: E402
import engine.util as engine_util  # noqa: E402
from engine import commands as engine_commands  # noqa: E402
from engine import pointers as engine_pointers  # noqa: E402
from engine.board import Board as EngineBoard  # noqa: E402
from engine.util import AnswerReject, Reject  # noqa: E402
from engine.rules import validator_module  # noqa: E402

GRAPH = json.loads(GRAPH_PATH.read_text(encoding="utf-8"))
TABLE = NodeTable.everything(GRAPH, GRAPH_SHA)
# 本文を返す節（graph の text。engine は返答の置き場を .md にする）
TEXT_NODES = {nid for nid, n in GRAPH["nodes"].items() if n.get("text")}


def tree_shas(top):
    """盤面の state.json・record.json・trace.jsonl と out/ の下の全部のファイルの sha256（盤面を書かなかったかを見る。
    RL の post_check が数え直しの控え count-*.json などを書く分は、手本の engine の後の目録と比べる）"""
    top = pathlib.Path(top)
    return {p.relative_to(top).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(top.rglob("*")) if p.is_file()
            and (p.parent == top and p.name in ("state.json", "record.json", "trace.jsonl") or "out" in p.relative_to(top).parts[:1])}


def with_by(table, nid, **entry):
    nodes = dict(table.nodes)
    nodes[nid] = NodeEntry(**entry)
    return dataclasses.replace(table, nodes=nodes)


def accept_steps(raised=False):
    """再生に当てる Run の accept の手（raised=True なら拒まれた手だけ、False なら通った手だけ）"""
    for rs in R.every_run():
        for s in rs:
            if s["kind"] == "accept" and bool(s.get("raised")) == raised:
                yield s


def first_step(scenario, node, raised=False):
    for rs in R.load_runs(scenario).values():
        if not R.replayable(rs):
            continue
        for s in rs:
            if s["kind"] == "accept" and s["node"] == node and bool(s.get("raised")) == raised:
                return s
    raise AssertionError(f"{scenario} に {node} の accept の手が無い")


class StepCase(unittest.TestCase):
    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp(prefix="board-steps-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        env = mock.patch.dict(os.environ, R.git_env())
        env.start()
        self.addCleanup(env.stop)
        cwd = engine_util.GIT_CWD
        self.addCleanup(setattr, engine_util, "GIT_CWD", cwd)
        self.n = 0

    def board_before(self, step, table=TABLE, edit=None):
        """手の前を一時の場所に戻し、記憶から DiskBoard を組む。edit(記憶) で組む前に記憶を書き換えられる"""
        self.n += 1
        into = self.tmp / f"s{self.n}"
        d, _ = R.restore(step.run_steps, step["seq"], "before", into)
        mem = R.memory_at(step.run_steps, step["seq"], "before")
        if edit:
            edit(mem)
        return R.board_from_memory(mem, d, table)

    def engine_reject_text(self, step, edit_output):
        """同じ手の前の盤面を別に戻し、手の返答を edit_output で書き換えて engine の accept_output に当て、拒みの文を取る"""
        b = self.board_before(step)
        out = R.reply(step, b)
        edit_output(out)
        with self.assertRaises(Reject) as cm:
            engine_commands.accept_output(EngineBoard(b.dir), step["node"], json.dumps(out, ensure_ascii=False), "test")
        return str(cm.exception)


class AcceptStepsCase(StepCase):
    def test_accept_steps(self):
        """kind=accept の通った手の全部: 戻す → 記憶から組む → accept → 手の後と同じ（NOT_REPRODUCED を除く）"""
        done, bad, named = 0, [], 0
        for s in accept_steps():
            b = self.board_before(s)
            out = R.reply(s, b)
            named += out != R.reply(s, b, names=False)
            b.accept(s["node"], out)
            diffs = R.compare(b, s)
            done += 1
            if diffs:
                bad.append(f"{s.run_steps.scenario} run {s['run']} seq {s['seq']} {s['node']}: " + " / ".join(diffs[:5]))
            shutil.rmtree(b.dir.parents[3], ignore_errors=True)
        print(f"\n手本の accept の手: {done} 手を当て、{done - len(bad)} 手が手の後と同じ"
              f"（うち {named} 手は台本の役が番号で書いた欄を instance の控えで名前に直して当てた）", file=sys.stderr)
        self.assertGreater(done, 800)
        self.assertEqual(bad, [], "\n".join(bad[:20]))

    def test_accept_reject_leaves_board(self):
        """拒まれた accept の手: accept が Reject、文が手本の文と同じ、盤面の置き場の全部のファイルが前のまま。
        engine の役の返答でない拒み（作業ツリーの突合・依存）は、突合を持たない（NOT_REPRODUCED）・配線の誤り（BoardGap）"""
        counts = {"reject": 0, "gap": 0, "tree": 0}
        for s in accept_steps(raised=True):
            with self.subTest(scenario=s.run_steps.scenario, seq=s["seq"], node=s["node"]):
                text = s["raised"]["text"]
                if s["raised"]["type"] == "Reject" and "作業ツリーが変わっている" in text:
                    counts["tree"] += 1   # instance.tree_before（NOT_REPRODUCED）
                    continue
                b = self.board_before(s)
                before = tree_shas(b.dir)
                if s["raised"]["type"] == "Reject" and "deps" in text:
                    with self.assertRaises(BoardGap):
                        b.accept(s["node"], R.reply(s, b))
                    counts["gap"] += 1
                else:
                    self.assertEqual(s["raised"]["type"], "AnswerReject")
                    with self.assertRaises(Reject) as cm:
                        b.accept(s["node"], R.reply(s, b))
                    self.assertEqual(str(cm.exception), text)
                    counts["reject"] += 1
                self.assertEqual(tree_shas(b.dir), before)
                self.assertEqual(R.disk_diff(b.dir, R.manifest_at(s.run_steps, s["seq"], "after", "disk")), [])
        print(f"\n手本の拒まれた accept の手: Reject {counts['reject']}・BoardGap（依存） {counts['gap']}・"
              f"当てない（作業ツリーの突合） {counts['tree']}", file=sys.stderr)
        self.assertGreater(counts["reject"], 60)
        self.assertEqual(counts["gap"], 1)
        self.assertEqual(counts["tree"], 1)

    def test_awaiting_after_judge_rejected(self):
        """判定を受けた後に、台帳に無い人待ちの素材（fix_closure を awaiting_human）を書く p3.fix を engine と同じ文で拒む（仕様 C1）"""
        s = first_step("test_converges", "p3.fix")
        b = self.board_before(s)
        self.assertTrue(any(i["node"] == "p2.diagnose" and i["status"] == "done" for i in b.rd["instances"].values()))
        V = validator_module(b)

        def awaiting(out):
            out["fix_closure"] = {"status": "awaiting_human",
                                  **{f: "人が実地で確かめる（検査用）" for f in V.STATUS["awaiting_human"].fields}}
        want = self.engine_reject_text(s, awaiting)
        out = R.reply(s, b)
        awaiting(out)
        self.assertIn("台帳にこの素材を出どころにする人待ちの問い（kind=awaiting）が無い", want)
        before = tree_shas(b.dir)
        with self.assertRaises(Reject) as cm:
            b.accept("p3.fix", out)
        self.assertEqual(str(cm.exception), want)
        self.assertEqual(tree_shas(b.dir), before)

    def test_pointer_integer_rejected(self):
        """p2.fix_plan の plan[].unit_keys を番号で書いた返答は、一覧を固めた控えが無いので engine の番号の文で拒む（仕様 BL17）"""
        s = first_step("test_converges", "p2.fix_plan")
        b = self.board_before(s)
        out = R.reply(s, b)
        out["plan"][0]["unit_keys"] = [1]
        errs = engine_pointers.resolve(copy.deepcopy(out), GRAPH["nodes"]["p2.fix_plan"]["pointers"], None)
        self.assertTrue(errs)
        before = tree_shas(b.dir)
        with self.assertRaises(Reject) as cm:
            b.accept("p2.fix_plan", out)
        self.assertEqual(str(cm.exception), "p2.fix_plan: " + "; ".join(errs))
        self.assertEqual(tree_shas(b.dir), before)

    def test_instance_done_and_output_link(self):
        s = first_step("test_converges", "p0.base")
        b = self.board_before(s)
        msg = b.accept("p0.base", R.reply(s, b))
        self.assertIn("p0.base", msg)
        inst = b.rd["instances"]["p0.base"]
        self.assertEqual(inst["status"], "done")
        self.assertEqual(inst["output_file"], "out/r1/p0.base.json")
        self.assertTrue(inst["done_at"])
        self.assertEqual(b.state["outputs"]["p0.base"], {"file": "out/r1/p0.base.json", "round": 1, "instance": "p0.base"})
        self.assertEqual(b.rd["done"]["p0.base"]["instance"], "p0.base")
        self.assertEqual(b.state["done_ever"]["p0.base"], 1)
        self.assertEqual(json.loads((b.dir / "out/r1/p0.base.json").read_text(encoding="utf-8")), R.reply(s, b))
        # 保存した: ディスクの盤面も受けた後
        disk = json.loads((b.dir / "state.json").read_text(encoding="utf-8"))
        self.assertEqual(disk["rounds"][-1]["instances"]["p0.base"]["status"], "done")
        self.assertIn('"op": "done"', (b.dir / "trace.jsonl").read_text(encoding="utf-8"))

    def test_emit_skills_like_engine(self):
        """手本の accept の手の前の instance の skills（applies・applies_why）と、_emit が組む skills が同じ"""
        with_skills = {nid for nid, n in GRAPH["nodes"].items() if n.get("skills")}
        n, applied = 0, set()
        for s in accept_steps():
            if s["node"] not in with_skills:
                continue
            b = self.board_before(s)
            want = b.rd["instances"][s["node"]].get("skills")
            del b.rd["instances"][s["node"]]
            inst = b._emit(s["node"])
            with self.subTest(scenario=s.run_steps.scenario, seq=s["seq"], node=s["node"]):
                self.assertEqual(inst.get("skills"), want)
                self.assertIs(b.rd["instances"][s["node"]], inst)
                self.assertLessEqual({"id", "node", "run_by", "status", "emitted_at", "out_path"}, set(inst))
                self.assertEqual(inst["status"], "pending")
                self.assertEqual(inst["out_path"], str(b.dir / "out" / f"r{b.round}" / f"{s['node']}.json"))
            applied.update(e.get("applies") for e in want or [] if isinstance(e, dict) and "applies_cond" in e)
            n += 1
            shutil.rmtree(b.dir.parents[3], ignore_errors=True)
        print(f"\n_emit の skills を engine と比べた手: {n}（applies の値: {sorted(map(str, applied))}）", file=sys.stderr)
        self.assertGreater(n, 10)
        self.assertIn(False, applied)

    def test_emit_minimal_instance(self):
        """skills の無い節の _emit は skills の鍵を持たない（engine の emit_instance と同じ）。本文を返す節の置き場は .md"""
        s = first_step("test_converges", "p0.base")
        b = self.board_before(s)
        del b.rd["instances"]["p0.base"]
        inst = b._emit("p0.base")
        self.assertEqual(set(inst), {"id", "node", "run_by", "status", "emitted_at", "out_path"})
        self.assertEqual((inst["id"], inst["node"], inst["run_by"]), ("p0.base", "p0.base", "writer"))
        text = sorted(TEXT_NODES)[0]
        self.assertTrue(b._emit(text)["out_path"].endswith(f"/out/r{b.round}/{text}.md"))

    def test_lens_not_applied_passes(self):
        """security_surface_touched が偽の盤面で、/security-review を invoked: false・failed で返した p1.local_review を通す
        （_emit が置いた skills[].applies が効く。skills の無い instance は graph の生の宣言に倒して拒む）"""
        s = first_step("test_converges", "p1.local_review")
        b = self.board_before(s)
        out = R.reply(s, b)
        row = next(r for r in out["findings"] if r["skill"] == "/security-review")
        self.assertIs(row.get("invoked"), False)
        self.assertTrue(row["failed"])
        self.assertFalse(b.cond("security_surface_touched")[0])
        del b.rd["instances"]["p1.local_review"]
        inst = b._emit("p1.local_review")
        lens = next(e for e in inst["skills"] if e["skill"] == "/security-review")
        self.assertIs(lens["applies"], False)
        b.accept("p1.local_review", out)
        self.assertEqual(b.rd["instances"]["p1.local_review"]["status"], "done")
        # 対照: skills の無い instance は graph の生の宣言（applies が無い＝当てる側）に倒れて拒まれる
        b2 = self.board_before(s)
        b2.rd["instances"]["p1.local_review"].pop("skills", None)
        with self.assertRaises(Reject) as cm:
            b2.accept("p1.local_review", R.reply(s, b2))
        self.assertIn("/security-review", str(cm.exception))

    def test_lens_applied_needs_invoked(self):
        """対照: 条件が真の盤面（p0.base が touches_security_surface: true）では、_emit が applies: true を置き、
        invoked: false の /security-review を拒む（手本の Run には条件が真の周が無いので、手の前の盤面を書き換えて見る）"""
        s = first_step("test_converges", "p1.local_review")
        b = self.board_before(s)
        base = b.dir / b.state["outputs"]["p0.base"]["file"]
        doc = json.loads(base.read_text(encoding="utf-8"))
        doc["touches_security_surface"] = True
        base.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
        b._out_cache = {}
        del b.rd["instances"]["p1.local_review"]
        lens = next(e for e in b._emit("p1.local_review")["skills"] if e["skill"] == "/security-review")
        self.assertIs(lens["applies"], True)
        self.assertEqual(lens["applies_why"], b.cond("security_surface_touched")[1])
        with self.assertRaises(Reject) as cm:
            b.accept("p1.local_review", R.reply(s, b))
        self.assertIn("invoked が true でない", str(cm.exception))

    def test_accept_on_halted_rejected(self):
        s = first_step("test_converges", "p0.base")

        def halt(mem):
            mem["state"]["halted"] = {"node": "p2.human_gate", "round": 1}
        b = self.board_before(s, edit=halt)
        before = tree_shas(b.dir)
        with self.assertRaises(Reject) as want:
            engine_commands._refuse_halted(b)
        with self.assertRaises(Reject) as cm:
            b.accept("p0.base", R.reply(s, b))
        self.assertEqual(str(cm.exception), str(want.exception))
        self.assertEqual(tree_shas(b.dir), before)

    def test_accept_absent_is_gap(self):
        s = first_step("test_converges", "p0.base")
        b = self.board_before(s, table=with_by(TABLE, "p0.base", by="absent", reason="このラインに無い（検査用）"))
        with self.assertRaises(BoardGap):
            b.accept("p0.base", R.reply(s, b))
        b = self.board_before(s)
        with self.assertRaises(BoardGap):
            b.accept("p1.worktree_before", {})     # 機械の節は受けない（step_builtin で回す）
        with self.assertRaises(BoardGap):
            b.accept("no.such.node", {})

    def test_accept_without_instance_is_gap(self):
        s = first_step("test_converges", "p0.base")
        b = self.board_before(s)
        del b.rd["instances"]["p0.base"]
        with self.assertRaises(BoardGap):
            b.accept("p0.base", R.reply(s, b))
        b = self.board_before(s)
        b.accept("p0.base", R.reply(s, b))
        with self.assertRaises(BoardGap):   # 既に done
            b.accept("p0.base", R.reply(s, b))

    def test_not_reproduced_listed(self):
        """比べない欄の表（名前と理由）を試験の出力に並べる"""
        self.assertTrue(R.NOT_REPRODUCED)
        for name, why in R.NOT_REPRODUCED.items():
            self.assertTrue(name.strip())
            self.assertGreater(len(why.strip()), 4, name)
        for name in ("at", "done_at", "emitted_at", "state.rev", "run_id", "instance.read_from", "instance.agent_id",
                     "instance.tree_before", "扇の被覆（fan_out.cover）", "段の昇格（thickness_from）", "disk:report.md",
                     "state.works"):
            self.assertIn(name, R.NOT_REPRODUCED)
        print("\n比べない欄（NOT_REPRODUCED）:\n" + "\n".join(f"  {k}: {v}" for k, v in R.NOT_REPRODUCED.items()),
              file=sys.stderr)


class ReplayToolCase(unittest.TestCase):
    """boardreplay の組み立ての検算（手本の検査 test_board_goldens_fixture と同じ答えに戻るか）"""

    def test_memory_at_matches_last(self):
        for rs in R.load_runs("test_converges").values():
            last = rs[-1]
            got = R.memory_at(rs, last["seq"], "after")
            if got is None or last["kind"] == "na":
                continue
            self.assertEqual(got, json.loads(R.blob(rs.meta["last"]["memory"])))
            self.assertEqual(R.manifest_at(rs, last["seq"], "after", "disk"), json.loads(R.blob(rs.meta["last"]["disk"])))
            self.assertEqual(R.manifest_at(rs, last["seq"], "before", "repo"), json.loads(R.blob(rs.meta["last"]["repo"])))

    def test_na_before_and_after(self):
        rs = R.load_runs("test_converges")["1"]
        na = next(s for s in rs if s["kind"] == "na")
        before = R.memory_at(rs, na["seq"], "before")
        after = R.memory_at(rs, na["seq"], "after")
        self.assertNotIn(na["node"], before["state"]["rounds"][-1]["na"])
        self.assertEqual(after["state"]["rounds"][-1]["na"][na["node"]], na["na"]["why"])

    def test_normalize_drops_listed(self):
        mem = {"state": {"rev": 3, "works": {}, "round": 1, "rounds": [{"instances": {"x": {
            "status": "done", "read_from": "stdin", "done_at": "t", "launch": {"steps": [1], "sha": "s", "argv": []}}}}]},
            "record": {"process": {"checks": {"p4.ci": {"runs": [{"exit": 0, "wall_s": 1.0, "out": "o", "err": "e"}]}}}}}
        got = R.normalize(mem)
        self.assertEqual(got, {"state": {"round": 1, "rounds": [{"instances": {"x": {
            "status": "done", "launch": {"steps": [1], "sha": "s"}}}}]},
            "record": {"process": {"checks": {"p4.ci": {"runs": [{"exit": 0}]}}}}})


if __name__ == "__main__":
    unittest.main()
