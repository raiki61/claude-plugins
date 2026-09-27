"""盤面の手本（tests/boards/golden-a1202d0/）を 1 手ずつ DiskBoard に当てる試験（仕様 9.3 の「1 手ずつ」・9.1 の 6）。

手の前の記憶とディスクとリポジトリを一時の場所に戻し、DiskBoard を記憶から組み（表は NodeTable.everything）、
同じ手を settle しない口で当て、手の後の記憶とディスクと比べる（boardreplay.compare。NOT_REPRODUCED の欄を除く）。
当てる手: 役の返答の受け付け（kind=accept → DiskBoard.accept。engine_run の中の受け付けは _accept_engine_reply）・
機械の節（kind=builtin → step_builtin）・周の開き（kind=open_round → 親の converge の手を step_builtin）・
条件の na（kind=na → _settle_node）・engine が走らせた節（kind=engine_run → 撮った計画と runs を差し込んで run_engine、
続く accept の手の後と比べる）・依頼（kind=add → add_request）・人の答え（kind=answer → _answer_record。答えの中の周の開きを含む）・
止める（kind=stop → stop）・仕上げ（kind=finalize → finalize）。省く（skip）の手は手本に無いので、engine の cmd_skip と比べる。
settle の単体（入口の止め方・壁・問い・周の止め・読んだ物の控え）もここに置く。
"""
import collections
import contextlib
import copy
import dataclasses
import hashlib
import io
import json
import os
import pathlib
import shutil
import sys
import tempfile
import types
import unittest
from unittest import mock

sys.dont_write_bytecode = True
HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import boardreplay as R  # noqa: E402  （board と写しの engine を sys.path に足す）
from board import GRAPH_PATH, GRAPH_SHA, BoardGap, DiskBoard, NodeEntry, NodeTable, RecordInvalid  # noqa: E402
import engine.util as engine_util  # noqa: E402
from engine import commands as engine_commands  # noqa: E402
from engine import pointers as engine_pointers  # noqa: E402
from engine.board import Board as EngineBoard  # noqa: E402
from engine.util import AnswerReject, BoardConflict, Reject  # noqa: E402
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


def kind_steps(kind):
    """再生に当てる Run の、種類 kind の手の全部（Run の中の順）"""
    for rs in R.every_run():
        for s in rs:
            if s["kind"] == kind:
                yield s


def parent_of(step):
    return next(x for x in step.run_steps if x["seq"] == step["parent"]) if step.get("parent") else None


def markable(board, nid):
    """ラインが起こした印を置ける形か（止めていない・待っている instance が在る・表で役の節か任せ先に落ちた engine_run の節）"""
    if board.state.get("halted") or nid not in board.nodes:
        return False
    inst = next((i for i in board.rd["instances"].values() if i["node"] == nid and i["status"] == "pending"), None)
    e = board.table.nodes.get(nid)
    return bool(inst) and e is not None and (e.by in ("role", "machine") or e.by == "engine_run" and bool(inst.get("engine_fallback")))


def under_engine_run(step):
    """engine_run の手の中の受け付け（launch_engine_run が組んだ返答の accept_output）か"""
    p = parent_of(step)
    return p is not None and p["kind"] == "engine_run"


def run_step(scenario, run, seq):
    rs = R.load_runs(scenario)[str(run)]
    return next(s for s in rs if s["seq"] == seq)


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

    def board_before(self, step, table=TABLE, edit=None, which="before", mark=True):
        """手の前（which="after" なら後）を一時の場所に戻し、記憶から DiskBoard を組む。edit(記憶) で組む前に記憶を書き換えられる。
        受け付けの手（engine_run の中でない）なら、ラインと同じくその節の待っている試行に起こした印を置く（mark=False で置かない。
        手本の台本は役を起こさずに done したが、盤面は印の無い返答を受けない。置けない形——止めた run・表で役でない節・待っている
        instance が無い——なら置かない）"""
        self.n += 1
        into = self.tmp / f"s{self.n}"
        d, _ = R.restore(step.run_steps, step["seq"], which, into)
        mem = R.memory_at(step.run_steps, step["seq"], which)
        if edit:
            edit(mem)
        b = R.board_from_memory(mem, d, table)
        if mark and which == "before" and step["kind"] == "accept" and not under_engine_run(step) and markable(b, step["node"]):
            R.mark(b, step["node"])
        return b

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
        done, bad, named, nested = 0, [], 0, 0
        for s in accept_steps():
            b = self.board_before(s)
            out = R.reply(s, b)
            named += out != R.reply(s, b, names=False)
            if under_engine_run(s):
                # engine_run の中の受け付け: ラインの accept は任せ先に落ちる前の engine_run の節を拒むので、run_engine の中の口で当てる
                b._accept_engine_reply(s["node"], out)
                nested += 1
            else:
                b.accept(s["node"], out)
            diffs = R.compare(b, s)
            done += 1
            if diffs:
                bad.append(f"{s.run_steps.scenario} run {s['run']} seq {s['seq']} {s['node']}: " + " / ".join(diffs[:5]))
            shutil.rmtree(b.dir.parents[3], ignore_errors=True)
        print(f"\n手本の accept の手: {done} 手を当て、{done - len(bad)} 手が手の後と同じ"
              f"（うち {named} 手は台本の役が番号で書いた欄を instance の控えで名前に直して当てた。"
              f"{nested} 手は engine_run の中の受け付けで _accept_engine_reply に当てた）", file=sys.stderr)
        self.assertGreater(done, 800)
        self.assertEqual(bad, [], "\n".join(bad[:20]))
        self.assertEqual(named, 1)   # 台本の役が番号で書いた手（p2.plan_review）。撮り直しで増えたら黙って通さない
        self.assertEqual(nested, 71)

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
                out = R.reply(s, b)   # 返答の読み取り（parse_output）の拒否を accept の拒否と数えない
                if s["raised"]["type"] == "Reject" and "deps" in text:
                    with self.assertRaises(BoardGap):
                        b.accept(s["node"], out)
                    counts["gap"] += 1
                else:
                    self.assertEqual(s["raised"]["type"], "AnswerReject")
                    with self.assertRaises(Reject) as cm:
                        b.accept(s["node"], out)
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
        self.assertEqual(set(inst), {"id", "node", "run_by", "status", "emitted_at", "out_path", "attempts"})
        self.assertEqual(inst["attempts"], 1)   # engine の emit_instance と同じく試行の数を持つ（比べる欄）
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
        R.mark(b, "p1.local_review")
        b.accept("p1.local_review", out)
        self.assertEqual(b.rd["instances"]["p1.local_review"]["status"], "done")
        # 対照: skills の無い instance は graph の生の宣言（applies が無い＝当てる側）に倒れて拒まれる
        b2 = self.board_before(s)
        b2.rd["instances"]["p1.local_review"].pop("skills", None)
        out2 = R.reply(s, b2)
        with self.assertRaises(Reject) as cm:
            b2.accept("p1.local_review", out2)
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
        R.mark(b, "p1.local_review")
        out = R.reply(s, b)
        with self.assertRaises(Reject) as cm:
            b.accept("p1.local_review", out)
        self.assertIn("invoked が true でない", str(cm.exception))

    def test_accept_on_halted_rejected(self):
        s = first_step("test_converges", "p0.base")

        def halt(mem):
            mem["state"]["halted"] = {"node": "p2.human_gate", "round": 1}
        b = self.board_before(s, edit=halt)
        before = tree_shas(b.dir)
        out = R.reply(s, b)
        with self.assertRaises(Reject) as want:
            engine_commands._refuse_halted(b)
        with self.assertRaises(Reject) as cm:
            b.accept("p0.base", out)
        self.assertEqual(str(cm.exception), str(want.exception))
        self.assertEqual(tree_shas(b.dir), before)

    def test_accept_absent_is_gap(self):
        s = first_step("test_converges", "p0.base")
        b = self.board_before(s, table=with_by(TABLE, "p0.base", by="absent", reason="このラインに無い（検査用）"))
        out = R.reply(s, b)
        with self.assertRaises(BoardGap):
            b.accept("p0.base", out)
        b = self.board_before(s)
        with self.assertRaises(BoardGap):
            b.accept("p1.worktree_before", {})     # 機械の節は受けない（step_builtin で回す）
        with self.assertRaises(BoardGap):
            b.accept("no.such.node", {})

    def test_accept_without_instance_is_gap(self):
        s = first_step("test_converges", "p0.base")
        b = self.board_before(s)
        del b.rd["instances"]["p0.base"]
        out = R.reply(s, b)
        with self.assertRaises(BoardGap):
            b.accept("p0.base", out)
        b = self.board_before(s)
        b.accept("p0.base", out)
        with self.assertRaises(BoardGap):   # 既に done
            b.accept("p0.base", out)

    def test_not_reproduced_listed(self):
        """比べない欄の表（名前と理由）を試験の出力に並べる"""
        self.assertTrue(R.NOT_REPRODUCED)
        for name, why in R.NOT_REPRODUCED.items():
            self.assertTrue(name.strip())
            self.assertGreater(len(why.strip()), 4, name)
        for name in ("at", "done_at", "emitted_at", "state.rev", "run_id", "instance.read_from", "instance.agent_id",
                     "instance.tree_before", "扇の被覆（fan_out.cover）", "段の昇格（thickness_from）", "disk:report.md",
                     "state.works", "disk:trace.jsonl", "trace の done の行の sha（schema の節）"):
            self.assertIn(name, R.NOT_REPRODUCED)
        print("\n比べない欄（NOT_REPRODUCED）:\n" + "\n".join(f"  {k}: {v}" for k, v in R.NOT_REPRODUCED.items()),
              file=sys.stderr)


def tok(board, obj):
    """盤面の置き場の実パスを手本の印に戻す（手本の文と比べるため）"""
    return R.Places.of_board(board.dir).tokenize(obj)


def trace_ops(board):
    return [json.loads(ln) for ln in (board.dir / "trace.jsonl").read_text(encoding="utf-8").splitlines() if ln.strip()]


# 手本の builtin の手が通る機械の節の中身（brief の 11 種）
BUILTINS_SEEN = {"worktree_snapshot", "worktree_compare", "human_gate", "lane_merge", "fix_delta", "delta_owed", "gates_cut",
                 "scalars", "assemble", "record_round", "converge"}


# 台本が手の環境を変えて回した手（手本は手の環境を撮らない）。再生は同じ環境を作って当てる（通しの再生と同じ表）
NO_GIT_STEPS = R.NO_GIT_STEPS


class MachineStepsCase(StepCase):
    """機械の節（builtin）・周の開き（open_round）・条件の na の手を 1 手ずつ当てる"""

    def no_git(self):
        empty = self.tmp / "empty-bin"
        empty.mkdir(exist_ok=True)
        return mock.patch.dict(os.environ, {"PATH": str(empty)})

    def test_builtin_steps(self):
        """kind=builtin の全部の手: 記憶から組む → step_builtin → 手の後と同じ、返りが手本の result と同じ"""
        done, bad, seen, no_git = 0, [], collections.Counter(), 0
        for s in kind_steps("builtin"):
            b = self.board_before(s)
            b.accept_tree_change = s["args"].get("accept_tree_change")   # settle が盤面に置く属性（手の引数）
            env = contextlib.nullcontext()
            if (s.run_steps.scenario, s.run_steps.run, s["seq"]) in NO_GIT_STEPS:
                env, no_git = self.no_git(), no_git + 1
            with env:
                got = b.step_builtin(s["node"])
            diffs = R.compare(b, s)
            if tok(b, got) != s["result"]:
                diffs.append(f"返り: 手本 {s['result']} ／ 盤面 {tok(b, got)}")
            done += 1
            seen[s["args"]["builtin"]] += 1
            if diffs:
                bad.append(f"{s.run_steps.scenario} run {s['run']} seq {s['seq']} {s['node']}: " + " / ".join(diffs[:5]))
            shutil.rmtree(b.dir.parents[3], ignore_errors=True)
        print(f"\n手本の builtin の手: {done} 手を当て、{done - len(bad)} 手が手の後と同じ（中身ごと: {dict(sorted(seen.items()))}。"
              f"うち {no_git} 手は台本と同じく git の無い場で当てた）", file=sys.stderr)
        self.assertGreater(done, 500)
        self.assertEqual(no_git, len(NO_GIT_STEPS))
        self.assertLessEqual(BUILTINS_SEEN, set(seen))
        self.assertEqual(bad, [], "\n".join(bad[:20]))

    def test_open_round_steps(self):
        """converge の手で周を開いた物（open_round の親が builtin）: step_builtin の後の round・新しい周の箱・loop・record・
        status・halted が open_round の手の後と同じ（on_new_round の持ち越しを含む）"""
        done, opened, bad = 0, 0, []
        for s in kind_steps("open_round"):
            parent = next(x for x in s.run_steps if x["seq"] == s["parent"])
            if parent["kind"] != "builtin":
                continue    # 人の答えの中の周の開き（answer の手）は LineStepsCase.test_answer_steps が answer の手の後と比べる
            b = self.board_before(parent)
            b.step_builtin(parent["node"])
            exp = R.normalize(R.memory_at(s.run_steps, s["seq"], "after"))
            got = R.normalize(tok(b, {"state": b.state, "record": b.record}))
            for key in ("round", "loop", "status", "halted"):
                if exp["state"].get(key) != got["state"].get(key):
                    bad.append(f"seq {s['seq']} state.{key}")
            if exp["state"]["rounds"][-1] != got["state"]["rounds"][-1]:
                bad.append(f"seq {s['seq']} 周の箱")
            if exp["record"] != got["record"]:
                bad.append(f"seq {s['seq']} record")
            done += 1
            opened += bool(s["result"]["opened"])
            shutil.rmtree(b.dir.parents[3], ignore_errors=True)
        print(f"\n手本の open_round の手（converge の中）: {done} 手を当て（開いた {opened}・止めた {done - opened}）、"
              f"{done - len(set(x.split()[1] for x in bad))} 手が同じ", file=sys.stderr)
        self.assertGreater(opened, 10)
        self.assertGreater(done - opened, 0)
        self.assertEqual(bad, [])

    def test_na_steps(self):
        """kind=na の全部の手: 手の前から組んで _settle_node(節) → 返りの理由 == 手の why、rd.na[節] == why。
        続く na の手（間に記憶を撮る手が無い＝同じ advance の中で続けて評価された物）は、同じ盤面で順に当てる
        （手の後＝次の手の前。1 つ目だけ記憶から組む）。限り: 間に engine が役の節を出しても（手として撮られない）盤面は
        その instance を持たない——手本も na の手ごとに記憶を撮らないので同じ近似。instance を読む条件はこの試験では見えない"""
        done, boards, bad = 0, 0, []
        for rs in R.every_run():
            b = None
            for s in rs:
                if s["kind"] != "na":
                    if b is not None:
                        shutil.rmtree(b.dir.parents[3], ignore_errors=True)
                        b = None
                    continue
                if b is None:
                    b = self.board_before(s)
                    boards += 1
                self.assertEqual(b.node_state(s["node"]), "pending")
                why = b._settle_node(s["node"])
                done += 1
                want = s["na"]["why"]
                if tok(b, why) != want or tok(b, b.rd["na"].get(s["node"])) != want:
                    bad.append(f"{rs.scenario} run {rs.run} seq {s['seq']} {s['node']}: 手本 {want!r} ／ 盤面 {tok(b, why)!r}")
            if b is not None:
                shutil.rmtree(b.dir.parents[3], ignore_errors=True)
        print(f"\n手本の na の手: {done} 手を当て（組んだ盤面 {boards}）、{done - len(bad)} 手が同じ理由", file=sys.stderr)
        self.assertGreater(done, 1100)
        self.assertEqual(bad, [], "\n".join(bad[:20]))

    def test_step_builtin_refuses_non_builtin(self):
        s = first_step("test_converges", "p0.base")
        b = self.board_before(s)
        with self.assertRaises(BoardGap):
            b.step_builtin("p0.base")          # 役の節
        with self.assertRaises(BoardGap):
            b.step_builtin("converge")         # 依存が済んでいない
        with self.assertRaises(BoardGap):
            b.step_builtin("no.such.node")


def builtin_step(scenario, node, nth=0):
    got = [s for rs in R.load_runs(scenario).values() if R.replayable(rs) for s in rs
           if s["kind"] == "builtin" and s["node"] == node]
    return got[nth]


class EngineRunStepsCase(StepCase):
    """engine が走らせる節（kind=engine_run と、その中の accept）を 1 手ずつ当てる"""

    def test_engine_run_steps(self):
        """kind=engine_run の全部の手: 手の前から組む → 撮った計画と runs を差し込んで run_engine → 続く accept の手の後と同じ
        （process.checks・素材・instance・runs/ のログ。NOT_REPRODUCED を除く）。runner に渡る語と cwd は計画の語とリポジトリのルート"""
        done, bad, nodes = 0, [], collections.Counter()
        for s in kind_steps("engine_run"):
            b = self.board_before(s)
            seen = []
            plan = R.engine_run_plan(s, b)
            got = b.run_engine(s["node"], runner=R.captured_runner(s, b, seen), plan=plan)
            acc = [x for x in s.run_steps if x.get("parent") == s["seq"] and x["kind"] == "accept"]
            diffs = R.compare(b, acc[0]) if len(acc) == 1 else [f"続く accept の手が {len(acc)} 手"]
            if not got["ok"] or got.get("fallback") or s["result"]["ok"] is not True:
                diffs.append(f"返り {got}（手本 {s['result']}）")
            if [x[0] for x in seen] != [plan.get("steps", [])] or pathlib.Path(seen[0][1]).resolve() != (b.dir.parent / "repo").resolve():
                diffs.append(f"runner に渡った物 {seen}")
            done += 1
            nodes[s["node"]] += 1
            if diffs:
                bad.append(f"{s.run_steps.scenario} run {s['run']} seq {s['seq']} {s['node']}: " + " / ".join(diffs[:5]))
            shutil.rmtree(b.dir.parents[3], ignore_errors=True)
        print(f"\n手本の engine_run の手: {done} 手を当て、{done - len(bad)} 手が続く accept の手の後と同じ"
              f"（節ごと: {dict(sorted(nodes.items()))}）", file=sys.stderr)
        self.assertEqual(done, 71)
        self.assertEqual(bad, [], "\n".join(bad[:20]))


def file_items(step, board):
    """add の手の依頼の本文（台本が --file に書いた JSON）を、盤面の置き場の実パスに戻して読む"""
    return R.Places.of_board(board.dir).untokenize(json.loads(step["args"]["file_text"]))


def in_round_asking(board):
    return bool((board.state.get("pending_human") or {}).get("in_round"))


class LineStepsCase(StepCase):
    """依頼（add）・人の答え（answer）・省く（skip）・止める（stop）・仕上げ（finalize）の手を 1 手ずつ当てる。
    settle しない記録の部分（add_request・_answer_record・_skip_record・stop・finalize）に当て、手の後と比べる。
    拒まれた手は、engine と同じ文で拒み、盤面の置き場が前のまま"""

    def rejected_same(self, s, call):
        """拒まれた手: 同じ文の Reject、盤面の置き場（state・record・trace・out）と目録が前のまま"""
        b = self.board_before(s)
        before = tree_shas(b.dir)
        with self.assertRaises(Reject) as cm:
            call(b)
        self.assertEqual(tok(b, str(cm.exception)), s["raised"]["text"])
        self.assertEqual(tree_shas(b.dir), before)
        self.assertEqual(R.disk_diff(b.dir, R.manifest_at(s.run_steps, s["seq"], "after", "disk")), [])
        shutil.rmtree(b.dir.parents[3], ignore_errors=True)

    def test_add_steps(self):
        """kind=add の全部の手: add_request(依頼, 出どころ) → 手の後と同じ。拒まれた手（RL の add の拒否）は同じ文"""
        done, bad, rejected, redrawn = 0, [], 0, 0
        for s in kind_steps("add"):
            call = lambda b, s=s: b.add_request(file_items(s, b), s["args"]["reason"])
            if s.get("raised"):
                with self.subTest(scenario=s.run_steps.scenario, seq=s["seq"]):
                    self.rejected_same(s, call)
                rejected += 1
                continue
            b = self.board_before(s)
            got = call(b)
            self.assertEqual(set(got), {"msg", "redraw"})
            redrawn += len(got["redraw"])
            diffs = R.compare(b, s)
            done += 1
            if diffs:
                bad.append(f"{s.run_steps.scenario} run {s['run']} seq {s['seq']}: " + " / ".join(diffs[:5]))
            shutil.rmtree(b.dir.parents[3], ignore_errors=True)
        print(f"\n手本の add の手: 通った {done} 手を当て {done - len(bad)} 手が手の後と同じ（描き直した instance {redrawn}）・"
              f"拒まれた {rejected} 手は同じ文", file=sys.stderr)
        self.assertEqual((done, rejected, redrawn), (16, 6, 6))
        self.assertEqual(bad, [], "\n".join(bad[:20]))

    def test_answer_steps(self):
        """kind=answer の全部の手: _answer_record(答え, 一言) → 手の後と同じ（周の途中の問い human_gate への答えと、
        周の終わりの答えの中の周の開き open_round を含む）"""
        done, bad, in_round, opened = 0, [], 0, 0
        for s in kind_steps("answer"):
            b = self.board_before(s)
            in_round += in_round_asking(b)
            b._answer_record(s["args"]["text"], s["args"].get("note") or "")
            opened += any(x.get("parent") == s["seq"] and x["kind"] == "open_round" for x in s.run_steps)
            diffs = R.compare(b, s)
            done += 1
            if diffs:
                bad.append(f"{s.run_steps.scenario} run {s['run']} seq {s['seq']}: " + " / ".join(diffs[:5]))
            shutil.rmtree(b.dir.parents[3], ignore_errors=True)
        print(f"\n手本の answer の手: {done} 手を当て {done - len(bad)} 手が手の後と同じ（周の途中の問い {in_round}・"
              f"答えの中の周の開き {opened}）", file=sys.stderr)
        self.assertEqual(done, 6)
        self.assertGreaterEqual(in_round, 3)
        self.assertEqual(opened, 2)
        self.assertEqual(bad, [], "\n".join(bad[:20]))

    def test_answer_in_round_continue(self):
        """test_human_gate の p2.human_gate の問いに continue と一言: human_items に node・answer・note、pending_human が消え、
        続く settle で p3.fix が ready"""
        s = run_step("test_human_gate", 1, 31)
        self.assertEqual(s["kind"], "answer")
        b = self.board_before(s)
        self.assertEqual(b.state["pending_human"]["node"], "p2.human_gate")
        self.assertTrue(in_round_asking(b))
        p = b.answer("continue", "呼び元の経路は残せ（検査用）")
        row = b.record["process"]["human_items"][-1]
        self.assertEqual((row["node"], row["answer"], row["note"]), ("p2.human_gate", "continue", "呼び元の経路は残せ（検査用）"))
        self.assertNotIn("pending_human", b.state)
        self.assertIsNone(p["asking"])
        self.assertIn("p2.human_gate", b.rd["done"])
        self.assertIn("p3.fix", p["ready"])
        disk = json.loads((b.dir / "state.json").read_text(encoding="utf-8"))
        self.assertNotIn("pending_human", disk)

    def test_answer_in_round_stop_halts(self):
        """周の途中の問いに stop: halted.by == "answer"、status は stopped。以後の保存は allow_halted 無しで Reject
        （同じ入れ物も、開き直した入れ物も。engine は手ごとに盤面を読み直すので、止めた後の手は必ず拒まれる）"""
        s = run_step("test_human_gate", 2, 208)
        self.assertEqual((s["kind"], s["args"]["text"]), ("answer", "stop"))
        b = self.board_before(s)
        self.assertTrue(in_round_asking(b))
        p = b.answer("stop", "削らない向きで出し直す")
        self.assertEqual(b.state["halted"]["by"], "answer")
        self.assertEqual(p["halted"]["by"], "answer")
        self.assertEqual(b.state["status"], "stopped")
        self.assertEqual(p["ready"], [])
        with self.assertRaises(Reject):
            b.save()
        again = DiskBoard.open(b.dir, table=TABLE)
        with self.assertRaises(Reject):
            again.save()
        DiskBoard.open(b.dir, table=TABLE, allow_halted=True).save()

    def test_answer_without_question(self):
        """人に聞いていない盤面への答えは engine と同じ文で拒み、盤面を書かない"""
        s = first_step("test_converges", "p0.base")
        b = self.board_before(s)
        self.assertNotIn("pending_human", b.state)
        before = tree_shas(b.dir)
        with self.assertRaises(Reject) as cm:
            b.answer("continue")
        self.assertEqual(str(cm.exception), "人に聞いている節は無い")
        self.assertEqual(tree_shas(b.dir), before)

    def test_answer_bad_word(self):
        """選択肢に無い語・周の途中の問いに escalate は engine と同じく拒む"""
        s = run_step("test_human_gate", 1, 31)
        for word, part in (("maybe", "のどれか"), ("escalate", "")):
            b = self.board_before(s)
            b.state["pending_human"]["options"] = sorted(set(b.state["pending_human"]["options"]) | {"escalate"})
            with self.assertRaises(Reject) as cm:
                b._answer_record(word)
            self.assertIn(part or "周の途中の問い", str(cm.exception))

    def skip_board(self, table=None):
        """p2.history（graph で optional）が待っている盤面（test_converges の p2.history の手の前）"""
        s = first_step("test_converges", "p2.history")
        table = table or with_by(TABLE, "p2.history", by="role", skippable=True)
        return s, self.board_before(s, table=table)

    def test_skip_steps(self):
        """kind=skip の手は手本に無い（台本が loop.py skip を打たない。数を 0 に固め、撮り直しで増えたら手本に当てる）。
        代わりに engine の cmd_skip を同じ盤面の写しに当て、_skip_record の後の記憶と比べる（engine が正本）"""
        n = sum(1 for _ in kind_steps("skip"))
        print(f"\n手本の skip の手: {n}（engine の cmd_skip と同じ盤面で比べる）", file=sys.stderr)
        self.assertEqual(n, 0)
        s, b = self.skip_board()
        twin = self.tmp / "engine-twin"
        shutil.copytree(b.dir, twin)
        with contextlib.redirect_stdout(io.StringIO()):
            engine_commands.cmd_skip(types.SimpleNamespace(dir=str(twin), node="p2.history", reason="検査用に省く"))
        b._skip_record("p2.history", "検査用に省く")
        want = json.loads((twin / "state.json").read_text(encoding="utf-8"))
        got = json.loads((b.dir / "state.json").read_text(encoding="utf-8"))
        for d in (want, got):
            d.pop("works", None)
            d["inputs"]["cwd"] = None
        self.assertEqual(R.normalize({"state": want}), R.normalize({"state": got}))
        self.assertEqual(json.loads((twin / "record.json").read_text(encoding="utf-8")),
                         json.loads((b.dir / "record.json").read_text(encoding="utf-8")))
        self.assertEqual(b.rd["skipped"]["p2.history"], "検査用に省く")
        self.assertEqual(b.rd["instances"]["p2.history"]["status"], "skipped")
        # 拒みの文も engine の cmd_skip と同じ（二度目・待っていない節。表で skippable にした optional の節）
        na_opt = next(n for n in b.rd["na"] if GRAPH["nodes"][n].get("optional"))
        b.table = with_by(b.table, na_opt, by="role", skippable=True)
        for nid in ("p2.history", na_opt):
            with self.assertRaises(Reject) as want:
                engine_commands.cmd_skip(types.SimpleNamespace(dir=str(twin), node=nid, reason="拒まれる"))
            with self.assertRaises(Reject) as cm:
                b._skip_record(nid, "拒まれる")
            self.assertEqual(str(cm.exception), str(want.exception))

    def test_skip_then_settle(self):
        """skip は _skip_record → settle: 省いた節は ready に無く、依存する節（p3.fix の前の節）へ進む"""
        s, b = self.skip_board()
        waiting = [n for n, g in GRAPH["nodes"].items() if "p2.history" in g.get("deps", []) and b.node_state(n) == "pending"]
        self.assertTrue(waiting)
        self.assertFalse(any(b.deps_ok(n) for n in waiting), "p2.history を待つ節が既に進める（試験の前提が崩れた）")
        p = b.skip("p2.history", "検査用に省く")
        self.assertNotIn("p2.history", p["ready"])
        self.assertEqual(b.node_state("p2.history"), "skipped")
        moved = [n for n in waiting if b.node_state(n) != "pending" or n in p["ready"] or b.deps_ok(n)]
        self.assertTrue(moved, f"p2.history を待つ節 {waiting} が進んでいない（ready {p['ready']}）")

    def test_skip_optional_only(self):
        """省けるのは表で skippable（graph で optional の節だけに付く）の節だけ: p2.history は表しだい、
        p2.plan_review（optional でない）は表で skippable にできないので BoardGap"""
        s, b = self.skip_board(table=TABLE)
        with self.assertRaises(BoardGap):
            b._skip_record("p2.history", "表で skippable でない")
        with self.assertRaises(BoardGap):
            b._skip_record("p2.plan_review", "optional でない")
        with self.assertRaises(BoardGap):
            with_table = with_by(TABLE, "p2.plan_review", by="role", skippable=True)
            self.board_before(s, table=with_table)
        with self.assertRaises(BoardGap):
            b._skip_record("no.such.node", "無い節")
        s, b = self.skip_board()
        b._skip_record("p2.history", "表で skippable")
        with self.assertRaises(Reject):   # 既に省いた（engine と同じ文）
            b._skip_record("p2.history", "二度目")

    def test_skip_needs_reason(self):
        s, b = self.skip_board()
        before = tree_shas(b.dir)
        for reason in ("", "  ", None):
            with self.assertRaises(BoardGap):
                b.skip("p2.history", reason)
        self.assertEqual(tree_shas(b.dir), before)

    def test_stop_steps(self):
        """kind=stop の全部の手: stop(理由, "stop") → 手の後と同じ（state.stop・rd.stopped・process.halted・止めた周の記録）。
        拒まれた手（理由が空・止めた後の二度目）は engine と同じ文"""
        done, bad, rejected = 0, [], 0
        for s in kind_steps("stop"):
            call = lambda b, s=s: b.stop(s["args"]["reason"], "stop")
            if s.get("raised"):
                with self.subTest(scenario=s.run_steps.scenario, seq=s["seq"]):
                    self.rejected_same(s, call)
                rejected += 1
                continue
            b = self.board_before(s)
            got = call(b)
            self.assertEqual(got["stopped"], b.state["stop"])
            diffs = R.compare(b, s)
            done += 1
            if diffs:
                bad.append(f"{s.run_steps.scenario} run {s['run']} seq {s['seq']}: " + " / ".join(diffs[:5]))
            shutil.rmtree(b.dir.parents[3], ignore_errors=True)
        print(f"\n手本の stop の手: 通った {done} 手を当て {done - len(bad)} 手が手の後と同じ・拒まれた {rejected} 手は同じ文",
              file=sys.stderr)
        self.assertEqual((done, rejected), (4, 2))
        self.assertEqual(bad, [], "\n".join(bad[:20]))

    def test_stop_by(self):
        """by は止めた口の名前（engine の loop.py stop は "stop"）。state.stop・halted と記録の process.halted に残る。空は BoardGap"""
        s = next(x for x in kind_steps("stop") if not x.get("raised"))
        b = self.board_before(s)
        with self.assertRaises(BoardGap):
            b.stop("理由", "")
        got = b.stop("検査用の理由", "stopfile")
        self.assertEqual(got["stopped"]["by"], "stopfile")
        self.assertEqual(b.record["process"]["halted"]["by"], "stopfile")

    def test_finalize_steps(self):
        """kind=finalize の手（test_stop_after_round の止めた run。開くのは allow_halted）: finalize() → 手の後と同じ"""
        steps = list(kind_steps("finalize"))
        for s in steps:
            self.n += 1
            d, _ = R.restore(s.run_steps, s["seq"], "before", self.tmp / f"s{self.n}")
            b = R.board_from_memory(R.memory_at(s.run_steps, s["seq"], "before"), d, TABLE, allow_halted=True)
            self.assertTrue(b.state.get("halted"))
            self.assertIsNone(b.finalize())
            self.assertEqual(R.compare(b, s), [])
        print(f"\n手本の finalize の手: {len(steps)} 手を当て、手の後と同じ", file=sys.stderr)
        self.assertEqual(len(steps), 1)

    def test_finalize_copies_skipped(self):
        """表で absent の節: 条件に当たった（skipped）物は finalize の後の process.skipped に表の理由で在り、条件に当たらない（na）物は無い"""
        s = builtin_step("test_converges", "p4.record")
        b0 = self.board_before(s)
        na_node = next(n for n in GRAPH["nodes"] if n in b0.rd["na"])
        table = with_by(with_by(TABLE, "p4.record", by="absent", reason="記録はこのラインに無い（検査用）"),
                        na_node, by="absent", reason="条件に当たらない節（検査用）")
        b = self.board_before(s, table=table)
        b.settle()
        b.finalize()
        rows = {r["node"]: r["reason"] for r in b.record["process"]["skipped"]}
        self.assertEqual(rows.get("p4.record"), "記録はこのラインに無い（検査用）")
        self.assertNotIn(na_node, rows)
        disk = json.loads((b.dir / "record.json").read_text(encoding="utf-8"))
        self.assertEqual(disk["process"]["skipped"], b.record["process"]["skipped"])


class LaunchMarkCase(StepCase):
    """起こした印（mark_launched。裁定 BL-R3）: ラインが役を起こす前に instance に launched_at を置き、RL の _started が engine と同じく
    読む（依頼の締め・描き直しの外し）。版の突き合わせで保存し、衝突は読み直して当て直す。新しい試行は印を持たない"""

    def hand_step(self, run, seq):
        s = run_step("test_request_entry", run, seq)
        self.assertEqual(s["kind"], "add")
        return s

    def unmarked(self, s, node):
        """手の前の盤面から、台本が手で書いた印（launched_at・返答の置き場のファイル）を外した盤面"""
        def edit(mem):
            mem["state"]["rounds"][-1]["instances"][node].pop("launched_at", None)
        b = self.board_before(s, edit=edit)
        pathlib.Path(b.rd["instances"][node]["out_path"]).unlink(missing_ok=True)
        return b

    def test_mark_refuses_add_like_engine(self):
        """判定役に印を置いた後の依頼は、engine と同じ文で拒む（test_request_entry run 9 seq 482・run 10 seq 509 の手）。印が無ければ通る"""
        for run, seq in ((9, 482), (10, 509)):
            s = self.hand_step(run, seq)
            items = file_items(s, self.board_before(s))
            b = self.unmarked(s, "p2.diagnose")
            self.assertEqual(set(b.add_request(items, s["args"]["reason"])), {"msg", "redraw"})   # 印が無い: 通る
            b = self.unmarked(s, "p2.diagnose")
            got = R.mark(b, "p2.diagnose")
            self.assertEqual((got["node"], got["attempt"]), ("p2.diagnose", 1))
            self.assertEqual(got["out_path"], b.rd["instances"]["p2.diagnose"]["out_path"])
            disk = json.loads((b.dir / "state.json").read_text(encoding="utf-8"))
            self.assertEqual(disk["rounds"][-1]["instances"]["p2.diagnose"]["launched_at"], got["launched_at"])
            before = tree_shas(b.dir)
            with self.assertRaises(Reject) as cm:
                b.add_request(items, s["args"]["reason"])
            self.assertEqual(tok(b, str(cm.exception)), s["raised"]["text"])
            self.assertEqual(tree_shas(b.dir), before)

    def test_mark_keeps_started_reader(self):
        """起こした印の在る読み手は描き直さない（test_request_entry run 8 seq 455: engine は返答の置き場のファイルで起きたと読む）"""
        s = self.hand_step(8, 455)
        items = file_items(s, self.board_before(s))
        b = self.unmarked(s, "p0.prior_decisions")
        self.assertIn("p0.prior_decisions", b.add_request(items, s["args"]["reason"])["redraw"])
        b = self.unmarked(s, "p0.prior_decisions")
        R.mark(b, "p0.prior_decisions")
        got = b.add_request(items, s["args"]["reason"])
        self.assertNotIn("p0.prior_decisions", got["redraw"])
        self.assertEqual(b.rd["instances"]["p0.prior_decisions"]["attempts"], 2)

    def test_new_attempt_drops_mark(self):
        """新しい試行（描き直し _reissue・任せ先への出し直し _emit）は印を持たない。印は試行ごと"""
        s = first_step("test_converges", "p1.hygiene")
        b = self.board_before(s, mark=False)
        R.mark(b, "p1.hygiene")
        prev = b.rd["instances"]["p1.hygiene"]
        self.assertTrue(prev["launched_at"])
        new = b._reissue(prev, "検査")
        self.assertNotIn("launched_at", new)
        self.assertEqual(new["attempts"], 2)
        self.assertNotIn("launched_at", b._emit("p1.hygiene"))

    def test_mark_is_per_attempt_and_idempotent(self):
        """同じ試行への二度目の印は前の時刻を返して保存しない（Archon の起こし直しで止めない）。起こせなかった試行も印は残り、
        その周の依頼の締めは閉じたまま（fail-closed。印を外す口は持たない——開き直すのは新しい試行）"""
        s = first_step("test_converges", "p1.hygiene")
        b = self.board_before(s, mark=False)
        first = R.mark(b, "p1.hygiene")
        rev = json.loads((b.dir / "state.json").read_text(encoding="utf-8"))["rev"]
        again = R.mark(b, "p1.hygiene")
        self.assertEqual(again["launched_at"], first["launched_at"])
        self.assertEqual(json.loads((b.dir / "state.json").read_text(encoding="utf-8"))["rev"], rev)
        self.assertFalse(hasattr(b, "unmark_launched"))

    def test_mark_retries_on_conflict(self):
        """別の入れ物が先に保存していたら、盤面を読み直して印を当て直す（engine の _board_update と同じ）。相手の書き込みは残る。
        当て直しの回数（engine の CONFLICT_RETRIES）まで負け続けたら BoardConflict を上げる"""
        s = first_step("test_converges", "p1.hygiene")
        b1 = self.board_before(s, mark=False)
        b2 = DiskBoard.open(b1.dir, table=TABLE)
        R.mark(b2, "p1.provenance")
        R.mark(b1, "p1.hygiene")
        disk = json.loads((b1.dir / "state.json").read_text(encoding="utf-8"))["rounds"][-1]["instances"]
        self.assertTrue(disk["p1.provenance"]["launched_at"] and disk["p1.hygiene"]["launched_at"])
        rows = [r for r in trace_ops(b1) if r["op"] == "launch"]
        self.assertEqual([r["instance"] for r in rows], ["p1.provenance", "p1.hygiene"])
        b3 = DiskBoard.open(b1.dir, table=TABLE)
        with mock.patch.object(DiskBoard, "save", side_effect=BoardConflict("検査")) as save:
            with self.assertRaises(BoardConflict):
                R.mark(b3, "p0.prior_decisions")
        self.assertEqual(save.call_count, engine_commands.CONFLICT_RETRIES)

    def test_mark_wiring(self):
        """印を置けるのは表で role・machine の待っている instance だけ（engine_run は run_engine が置く・機械の節・無い節は BoardGap）。
        止めた run は engine の Reject"""
        s = first_step("test_converges", "p1.hygiene")
        b = self.board_before(s, mark=False)
        for nid in ("p1.worktree_after", "no.such.node", "p2.diagnose"):
            with self.assertRaises(BoardGap):
                b.mark_launched(nid, 1)
        s = next(x for x in kind_steps("engine_run"))
        b = self.board_before(s)
        with self.assertRaises(BoardGap):
            b.mark_launched(s["node"], 1)
        s = run_step("test_human_gate", 2, 208)
        b = self.board_before(s)
        b.answer("stop", "止める")
        with self.assertRaises(Reject):
            b.mark_launched("p3.fix", 1)      # 止めた run は、節を見る前に engine の文で拒む

    def test_run_engine_marks_launched(self):
        """engine が走らせる節も engine の launch と同じく起こした印を持つ（受けた instance に launched_at。在否は再生で比べる）"""
        s = next(x for x in kind_steps("engine_run"))
        b = self.board_before(s, edit=lambda m: m["state"]["rounds"][-1]["instances"][s["node"]].pop("launched_at", None))
        self.assertNotIn("launched_at", b.rd["instances"][s["node"]])
        b.run_engine(s["node"], runner=R.captured_runner(s, b), plan=R.engine_run_plan(s, b))
        self.assertTrue(b.rd["instances"][s["node"]]["launched_at"])

    def test_mark_fallen_back_engine_run(self):
        """任せ先に落ちた engine_run の節（表の fallback が role・machine）は、ラインが役を起こすので印を置ける（engine は任せ先に
        launch を持たせて印を付ける）: test_converges run 1 seq 20 の p0.parallel_pr（審査の再現の手）。印の後の依頼は、その instance を
        描き直さない（判定から入る run の周で依頼が loop.request_wheres を書き直す test_request_entry run 1 seq 23）。
        落ちる前の engine_run の節は BoardGap のまま（run_engine が置く）"""
        s = run_step("test_converges", 1, 20)
        self.assertEqual((s["kind"], s["node"]), ("accept", "p0.parallel_pr"))
        b = self.board_before(s, mark=False)
        self.assertTrue(b.rd["instances"]["p0.parallel_pr"]["engine_fallback"])
        got = R.mark(b, "p0.parallel_pr")
        self.assertEqual((got["already"], got["attempt"]), (False, 1))
        s = run_step("test_request_entry", 1, 23)
        self.assertEqual((s["kind"], s["node"]), ("accept", "p0.parallel_pr"))
        items = [{"where": "src/a.py:f", "text": "上限を掛けたい（検査用）"}]
        b = self.board_before(s, mark=False)
        self.assertIn("p0.parallel_pr", b.add_request(items, "検査用")["redraw"])       # 印が無ければ描き直す
        b = self.board_before(s, mark=False)
        R.mark(b, "p0.parallel_pr")
        self.assertNotIn("p0.parallel_pr", b.add_request(items, "検査用")["redraw"])
        e = next(x for x in kind_steps("engine_run"))
        b = self.board_before(e)
        self.assertFalse(b.rd["instances"][e["node"]].get("engine_fallback"))
        with self.assertRaises(BoardGap):
            b.mark_launched(e["node"], 1)

    def test_accept_needs_mark(self):
        """起こした印の無い instance の返答は受けない（BoardGap。ラインが mark_launched を呼ばずに役を起こした）。盤面は書かない。
        任せ先に落ちた engine_run の節の done も同じ。印の後は受ける"""
        s = first_step("test_converges", "p0.base")
        b = self.board_before(s, mark=False)
        before = tree_shas(b.dir)
        with self.assertRaises(BoardGap) as cm:
            b.accept("p0.base", R.reply(s, b))
        self.assertIn("mark_launched", str(cm.exception))
        with self.assertRaises(BoardGap):
            b.done("p0.base", R.reply(s, b))
        self.assertEqual(tree_shas(b.dir), before)
        R.mark(b, "p0.base")
        b.accept("p0.base", R.reply(s, b))
        s = run_step("test_converges", 1, 20)
        b = self.board_before(s, mark=False)
        with self.assertRaises(BoardGap):
            b.accept("p0.parallel_pr", R.reply(s, b))
        R.mark(b, "p0.parallel_pr")
        b.accept("p0.parallel_pr", R.reply(s, b))

    def test_mark_refuses_other_attempt(self):
        """印は、ラインが描いて起こす試行にだけ置く: 描いた後・印の前に依頼が描き直した（試行が進んだ）なら、前の試行の番号での印は
        Reject（今の試行で描き直して起こす）で、盤面は書かない。返りの out_path と attempt が、ラインが起こす試行（test_request_entry
        run 8 seq 454 の add が p0.prior_decisions を描き直す手）"""
        s = run_step("test_request_entry", 8, 454)
        self.assertEqual(s["kind"], "add")
        b = self.board_before(s)
        drawn = dict(b.rd["instances"]["p0.prior_decisions"])        # ラインが描いた試行（1）
        self.assertEqual(drawn["attempts"], 1)
        got = b.add_request(file_items(s, b), s["args"]["reason"])
        self.assertIn("p0.prior_decisions", got["redraw"])
        before = tree_shas(b.dir)
        with self.assertRaises(Reject) as cm:
            b.mark_launched("p0.prior_decisions", drawn["attempts"])
        self.assertIn("描き直", str(cm.exception))
        self.assertEqual(tree_shas(b.dir), before)
        now = b.rd["instances"]["p0.prior_decisions"]
        got = b.mark_launched("p0.prior_decisions", now["attempts"])
        self.assertEqual((got["attempt"], got["out_path"]), (2, now["out_path"]))
        self.assertTrue(got["out_path"].endswith("p0.prior_decisions.a2.json"))
        with self.assertRaises(BoardGap):
            b.mark_launched("p0.prior_decisions", "2")      # 試行の番号は整数


class SettleCase(StepCase):
    """settle（仕様 4.1 の 1〜3・5）と、settle まで回す口（done・run_builtin）"""

    def test_settle_entry_halted(self):
        """止めた run の盤面は何もしない: 盤面（記憶もディスクも）が前のまま、halted を返し、ready は空"""
        s = builtin_step("test_converges", "p1.worktree_after")
        halted = {"node": "p2.human_gate", "round": 1, "by": "stop", "reason": "検査用"}
        b = self.board_before(s, edit=lambda m: m["state"].__setitem__("halted", halted))
        mem = copy.deepcopy({"state": b.state, "record": b.record})
        disk = tree_shas(b.dir)
        p = b.settle()
        self.assertEqual(p["halted"], halted)
        self.assertEqual(p["ready"], [])
        self.assertEqual({"state": b.state, "record": b.record}, mem)
        self.assertEqual(tree_shas(b.dir), disk)
        self.assertTrue(p["notes"])

    def test_settle_entry_pending_human(self):
        """人に聞いている間（r4.human_gate の周の途中の問い）に別の節を done: 受け付けは済むが、settle は進めない
        ——r4.human_gate を走らせ直さず、pending_human が同じ、ready は空（engine の cmd_next と同じ）"""
        ask = run_step("test_human_gate", 1, 54)
        self.assertEqual((ask["kind"], ask["node"]), ("builtin", "r4.human_gate"))
        acc = run_step("test_human_gate", 1, 56)
        self.assertEqual((acc["kind"], acc["node"]), ("accept", "r1.comment_candidates"))
        b = self.board_before(ask, which="after")
        ph = copy.deepcopy(b.state["pending_human"])
        self.assertEqual(b.rd["instances"]["r1.comment_candidates"]["status"], "pending")
        R.mark(b, "r1.comment_candidates")
        p = b.done("r1.comment_candidates", R.reply(acc, b))
        self.assertEqual(b.rd["instances"]["r1.comment_candidates"]["status"], "done")
        self.assertEqual(b.state["pending_human"], ph)
        self.assertEqual(p["asking"], ph)
        self.assertEqual(p["ready"], [])
        self.assertNotIn("r4.human_gate", b.rd["done"])
        self.assertFalse([r for r in trace_ops(b) if r["op"] == "builtin"])
        disk = json.loads((b.dir / "state.json").read_text(encoding="utf-8"))
        self.assertEqual(disk["pending_human"], ph)
        self.assertEqual(disk["rounds"][-1]["instances"]["r1.comment_candidates"]["status"], "done")

    def test_settle_stops_at_ask(self):
        """周の途中の問い（p2.human_gate）で止まる: asking に kinds・items、human_gate は done でない、ready は空、保存した"""
        s = run_step("test_human_gate", 1, 30)
        self.assertEqual((s["kind"], s["node"]), ("builtin", "p2.human_gate"))
        b = self.board_before(s)
        p = b.settle()
        self.assertEqual(p["asking"]["node"], "p2.human_gate")
        self.assertEqual(p["asking"]["kinds"], ["regression"])
        self.assertTrue(p["asking"]["items"])
        self.assertNotIn("p2.human_gate", b.rd["done"])
        self.assertEqual(p["ready"], [])
        self.assertIsNone(p["halted"])
        self.assertTrue(any("p2.human_gate: ask" in x for x in p["notes"]))
        disk = json.loads((b.dir / "state.json").read_text(encoding="utf-8"))
        self.assertEqual(disk["pending_human"], b.state["pending_human"])
        # 手本の engine の手の後と同じ記憶
        self.assertEqual(R.compare(b, s), [])

    def test_settle_stop_after_round(self):
        """stop_after_round の周の converge の後: halted.by == stop_after_round、round は増えない、ready は空"""
        s = builtin_step("test_stop_after_round", "converge")
        b = self.board_before(s)
        self.assertEqual(b.state["stop_after_round"], b.round)
        rnd = b.round
        p = b.settle()
        self.assertEqual(p["halted"]["by"], "stop_after_round")
        self.assertEqual(b.state["halted"]["by"], "stop_after_round")
        self.assertEqual(b.round, rnd)
        self.assertEqual(p["round"], rnd)
        self.assertEqual(len(b.state["rounds"]), rnd)
        self.assertEqual(p["ready"], [])
        self.assertEqual(b.state["status"], "stopped")
        disk = json.loads((b.dir / "state.json").read_text(encoding="utf-8"))
        self.assertEqual(disk["halted"]["by"], "stop_after_round")
        # 止めた後の settle は何もしない
        self.assertEqual(b.settle()["halted"]["by"], "stop_after_round")

    def test_settle_passes_accept_tree_change(self):
        """P1 の後に作業ツリーが変わった盤面（手本 test_rejections の手の前）: 理由なしの settle は worktree_compare で止まり、
        accept_tree_change="理由" の settle は通って git_mismatches に accepted で残り、撃ち直す材料の節を出す"""
        s = run_step("test_rejections", 1, 34)
        self.assertEqual(s["node"], "p1.worktree_after")
        atc = s["args"]["accept_tree_change"]
        b = self.board_before(s)
        p = b.settle()
        self.assertTrue(any("P1 の前後で作業ツリーが変わっている" in x for x in p["notes"]), p["notes"])
        self.assertIsNone(b.state["git_mismatches"][-1]["accepted"])
        self.assertNotIn("p1.worktree_after", b.rd["done"])
        b = self.board_before(s)
        p = b.settle(accept_tree_change=atc)
        gm = b.state["git_mismatches"][-1]
        self.assertEqual(gm["accepted"], atc)
        self.assertTrue(gm["refired"])
        self.assertTrue(set(gm["refired"]) & set(p["ready"]), (gm["refired"], p["ready"]))
        disk = json.loads((b.dir / "state.json").read_text(encoding="utf-8"))
        self.assertEqual(disk["git_mismatches"][-1]["accepted"], atc)

    def test_explicit_is_wall(self):
        """p4.record を explicit にした表と auto の表で同じ盤面（p4.record の手の前）を settle: explicit 側は p4.record で止まり
        （待ちのまま ready に出し、graph の順で後ろの節を評価しない）、run_builtin の後の盤面（converge 以降の na を含む）が auto 側と同じ"""
        s = builtin_step("test_converges", "p4.record")
        explicit = with_by(TABLE, "p4.record", by="builtin", run="explicit")
        auto = self.board_before(s)
        pa = auto.settle()
        wall = self.board_before(s, table=explicit)
        order = list(GRAPH["nodes"])
        after = order[order.index("p4.record") + 1:]
        states = {n: wall.node_state(n) for n in after}
        pw = wall.settle()
        self.assertIn("p4.record", pw["ready"])
        self.assertEqual(wall.node_state("p4.record"), "pending")
        before_na = dict(wall.rd["na"])
        self.assertEqual({n: wall.node_state(n) for n in after}, states, "壁の後ろを評価した")
        self.assertIn("pending", states.values())
        self.assertFalse([r for r in trace_ops(wall) if r["op"] == "builtin"], "壁で止まる settle が機械の節を回した")
        rnd = wall.round
        pr = wall.run_builtin("p4.record")
        self.assertIn("p4.record", wall.state["rounds"][rnd - 1]["done"])
        norm = lambda b: R.normalize(tok(b, {"state": {k: v for k, v in b.state.items() if k != "works"}, "record": b.record}))
        self.assertEqual(norm(wall), norm(auto))
        self.assertEqual(pr["round"], pa["round"])
        self.assertEqual(sorted(pr["ready"]), sorted(pa["ready"]))
        # converge 以降の na が付いた（壁の前には付いていなかった）
        first = wall.state["rounds"][rnd - 1]["na"]
        self.assertTrue(set(first) - set(before_na) & set(after), "壁の後ろの na が run_builtin の後に付いていない")

    def test_run_builtin_only_explicit(self):
        s = builtin_step("test_converges", "p4.record")
        b = self.board_before(s)
        with self.assertRaises(BoardGap):
            b.run_builtin("p4.record")          # auto の節は settle が回す
        with self.assertRaises(BoardGap):
            b.run_builtin("p0.base")            # 機械の節でない
        b = self.board_before(s, table=with_by(TABLE, "converge", by="builtin", run="explicit"))
        with self.assertRaises(BoardGap):
            b.run_builtin("converge")           # 依存が済んでいない

    def test_run_builtin_na(self):
        """explicit の節の条件が偽なら、走らせずに na（engine の applicable の理由）にしてから settle"""
        s = next(x for x in kind_steps("na") if GRAPH["nodes"][x["node"]].get("run_by") == "driver")
        table = with_by(TABLE, s["node"], by="builtin", run="explicit")
        b = self.board_before(s, table=table)
        rnd = b.round
        p = b.run_builtin(s["node"])
        self.assertEqual(tok(b, b.state["rounds"][rnd - 1]["na"][s["node"]]), s["na"]["why"])
        self.assertFalse([r for r in trace_ops(b) if r["op"] == "builtin" and r["node"] == s["node"]])
        self.assertNotIn(s["node"], p["ready"])

    def test_settle_clears_read_caches(self):
        """rewind の後に同じ out のパスへ書いた出力を、同じ入れ物の settle が新しい中身で読む（読んだ物の控えを消す。仕様 4.1 の 2）。
        p0.base を touches_security_surface: true で受け直し、p1.local_review を出し直させると、レンズの条件が新しい中身で真になる"""
        base = first_step("test_converges", "p0.base")
        s = first_step("test_converges", "p1.local_review")
        b = self.board_before(s)
        self.assertFalse(b.cond("security_surface_touched")[0])     # p0.base の出力を読んで控えに持つ
        path = b.dir / b.state["outputs"]["p0.base"]["file"]
        b.rewind(["p0.base"], "検査用")
        b._emit("p0.base")
        R.mark(b, "p0.base")
        out = R.reply(base, b)
        out["touches_security_surface"] = True
        b.accept("p0.base", out)
        self.assertEqual(b.dir / b.state["outputs"]["p0.base"]["file"], path)   # 同じ置き場に書いた
        self.assertFalse(b.cond("security_surface_touched")[0], "控えが効いていない（試験の前提が崩れた）")
        del b.rd["instances"]["p1.local_review"]
        b.settle()
        lens = next(e for e in b.rd["instances"]["p1.local_review"]["skills"] if e["skill"] == "/security-review")
        self.assertIs(lens["applies"], True)

    def test_settle_absent_goes_to_skipped(self):
        """表で absent の節は、条件に当たれば周の箱の skipped に表の理由（done_ever も engine の skip と同じく書く）"""
        s = builtin_step("test_converges", "p4.record")
        b = self.board_before(s, table=with_by(TABLE, "p4.record", by="absent", reason="このラインに無い（検査用）"))
        b.settle()
        first = b.state["rounds"][0]
        self.assertEqual(first["skipped"]["p4.record"], "このラインに無い（検査用）")
        self.assertEqual(b.state["done_ever"]["p4.record"], 1)
        self.assertNotIn("p4.record", first["done"])

    def pre_finalize_board(self, validator_runner=None):
        """report.cold_check の手の前の盤面（test_converges。次の settle で pre: finalize の節 report に当たる）"""
        s = run_step("test_converges", 1, 172)
        self.assertEqual((s["kind"], s["node"]), ("accept", "report.cold_check"))
        self.assertEqual(GRAPH["nodes"]["report"].get("pre"), "finalize")
        b = self.board_before(s)
        b.validator_runner = validator_runner
        return s, b

    def test_settle_pre_finalize_emits_after_validator(self):
        """pre: finalize の節（report）は、engine の emit_instance と同じく記録を仕上げ（finalize）→ 保存 → 検証器（self.run_validator。
        Track B の包みが効く口）→ 受理集合（report_accepts_exit）に入れば出す"""
        seen = []

        def runner(b, target):
            seen.append(target)
            return super(DiskBoard, b).run_validator(target)   # engine と同じ検証器を、盤面の口を通して回す
        s, b = self.pre_finalize_board(runner)
        p = b.done("report.cold_check", R.reply(s, b))
        self.assertEqual(seen, [None])
        self.assertEqual(b.rd["instances"]["report"]["status"], "pending")
        self.assertIn("report", p["ready"])
        # 仕上げが記録に写した（engine の validator.finalize の process.skipped など）。保存もした
        self.assertIn("skipped", b.record["process"])
        disk = json.loads((b.dir / "record.json").read_text(encoding="utf-8"))
        self.assertEqual(disk["process"]["skipped"], b.record["process"]["skipped"])
        self.assertFalse([r for r in trace_ops(b) if r["op"] == "validator_failed"])

    def test_settle_pre_finalize_validator_fails(self):
        """検証器が受理集合の外（exit 2・None）なら report を出さず、settle の最後の保存の後に RecordInvalid（BoardGap の子。
        engine は trace に validator_failed を書いて exit 1 で止まる——fail closed）。仕上げと settle の保存は残る。呼び直しても同じ"""
        for code in (2, None):
            with self.subTest(exit=code):
                s, b = self.pre_finalize_board(lambda b, target: {"exit": code, "out": "検査用の不合格"})
                with self.assertRaises(RecordInvalid) as cm:
                    b.done("report.cold_check", R.reply(s, b))
                self.assertIsInstance(cm.exception, BoardGap)
                self.assertEqual((cm.exception.node, cm.exception.exit, cm.exception.out), ("report", code, "検査用の不合格"))
                self.assertIn("検証器を通らない", str(cm.exception))
                self.assertNotIn("report", b.rd["instances"])
                fails = [r for r in trace_ops(b) if r["op"] == "validator_failed"]
                self.assertEqual([(r["exit"], r["out"]) for r in fails], [(code, "検査用の不合格")])
                disk = json.loads((b.dir / "state.json").read_text(encoding="utf-8"))
                self.assertEqual(disk["rounds"][-1]["instances"]["report.cold_check"]["status"], "done")
                self.assertNotIn("report", disk["rounds"][-1]["instances"])
                self.assertEqual(disk.get("rev"), b.seen_rev, "settle の最後の保存の後に投げていない")
                rec = json.loads((b.dir / "record.json").read_text(encoding="utf-8"))
                self.assertIn("skipped", rec["process"])
                with self.assertRaises(RecordInvalid):   # 呼び直しても関所をやり直して同じ（engine の next と同じ）
                    b.settle()
                self.assertNotIn("report", b.rd["instances"])

    def test_settle_unknown_pre_is_gap(self):
        """finalize でない pre は持たない（a1202d0 の graph に無い）: 黙って出さず BoardGap"""
        s, b = self.pre_finalize_board()
        b.nodes["report"]["pre"] = "somethingelse"
        with self.assertRaises(BoardGap):
            b.done("report.cold_check", R.reply(s, b))

    def test_run_builtin_fresh_reads(self):
        """run_builtin は前の settle の読んだ物の控え（git status の写し）と accept_tree_change を使わない:
        worktree_compare を explicit にした表で、前の settle に渡した理由では通らず、新しい git status で突き合わせる"""
        s = run_step("test_rejections", 1, 34)
        self.assertEqual(s["node"], "p1.worktree_after")
        table = with_by(TABLE, "p1.worktree_after", by="builtin", run="explicit")
        b = self.board_before(s, table=table)
        p = b.settle(accept_tree_change="前の settle の理由（検査用）")
        self.assertIn("p1.worktree_after", p["ready"])
        b.__dict__["_porcelain"] = ["?? 古い写し（検査用）"]
        p = b.run_builtin("p1.worktree_after")
        gm = b.state["git_mismatches"][-1]
        self.assertIsNone(gm["accepted"])
        self.assertIn("stray.txt", " ".join(gm["diff"]))
        self.assertNotIn("古い写し", " ".join(gm["diff"]))
        self.assertTrue(any("作業ツリーが変わっている" in x for x in p["notes"]), p["notes"])
        p = b.run_builtin("p1.worktree_after", accept_tree_change=s["args"]["accept_tree_change"])
        self.assertEqual(b.state["git_mismatches"][-1]["accepted"], s["args"]["accept_tree_change"])

    def test_settle_on_scratch_is_gap(self):
        """v1 の受け付けの入れ物（scratch。表も instance も持たない）は settle・機械の節を回さない"""
        s = builtin_step("test_converges", "p4.record")
        b = self.board_before(s)
        sc = DiskBoard.scratch(b.dir, review_rev="HEAD")
        with self.assertRaises(BoardGap):
            sc.settle()
        with self.assertRaises(BoardGap):
            sc.step_builtin("p1.worktree_before")

    def test_settle_refuses_fan_out(self):
        """扇の節（fan_out）は持たない（a1202d0 の graph に無い）: 出会ったら黙って進めず BoardGap"""
        s = builtin_step("test_converges", "p4.record")
        b = self.board_before(s)
        b.nodes["converge"]["fan_out"] = {"builtin": "x"}
        with self.assertRaises(BoardGap):
            b.settle()


class AcceptStrictCase(StepCase):
    def test_text_node_only_text_key(self):
        """本文を返す節の返答は {text} だけ（engine は本文から {text} を組むので他の鍵は届かない。余分な鍵はラインの配線の誤り）"""
        s = next(x for x in accept_steps() if x["node"] in TEXT_NODES)
        b = self.board_before(s)
        out = R.reply(s, b)
        self.assertEqual(set(out), {"text"})
        before = tree_shas(b.dir)
        with self.assertRaises(BoardGap):
            b.accept(s["node"], {**out, "extra": 1})
        self.assertEqual(tree_shas(b.dir), before)
        b.accept(s["node"], out)

    def test_accept_refuses_fan_out_and_thickness_from(self):
        """扇の被覆・段の昇格は持たない（NOT_REPRODUCED）: そういう節の受け付けは黙って受けず BoardGap"""
        s = first_step("test_converges", "p0.base")
        for key, val in (("fan_out", {"builtin": "x"}), ("thickness_from", "x")):
            b = self.board_before(s)
            b.nodes["p0.base"][key] = val
            out = R.reply(s, b)
            with self.assertRaises(BoardGap):
                b.accept("p0.base", out)


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

    def test_compile_cache_fresh_module(self):
        """再生の中だけの compile の控え（boardreplay が入れる）: 同じ RL を 2 度読むと code は使い回すが module は盤面ごとに
        新しく exec する（大域の差し替えが他へ漏れない）。鍵はパスと元のバイトの sha256。bytecode のファイルは書かない"""
        from board import rules_module
        a, b = rules_module(), rules_module()
        self.assertIsNot(a, b)
        self.assertIs(a.converge.__code__, b.converge.__code__)       # 控えの code を使い回した
        self.assertIsNot(a.converge, b.converge)                        # 関数は exec のたびに新しい
        a.check_record = None
        self.assertIsNotNone(b.check_record)
        rl = (R.CORE_DIR / "graphloops" / "rules" / "review-loop.py").resolve()
        sha = hashlib.sha256(rl.read_bytes()).hexdigest()
        self.assertTrue(any(k[0] == str(rl) and k[1] == sha for k in R.CODE_CACHE))
        self.assertFalse(list((R.CORE_DIR / "graphloops").rglob("__pycache__")))

    def test_normalize_drops_listed(self):
        mem = {"state": {"rev": 3, "works": {}, "round": 1, "rounds": [{"instances": {"x": {
            "status": "done", "read_from": "stdin", "done_at": "t", "launch": {"steps": [1], "sha": "s", "argv": []}}}}]},
            "record": {"process": {"checks": {"p4.ci": {"runs": [{"exit": 0, "wall_s": 1.0, "out": "o", "err": "e"}]}}}}}
        got = R.normalize(mem)
        self.assertEqual(got, {"state": {"round": 1, "rounds": [{"instances": {"x": {
            "status": "done", "launch": {"steps": [1], "sha": "s"}}}}]},
            "record": {"process": {"checks": {"p4.ci": {"runs": [{"exit": 0}]}}}}})

    def test_normalize_drops_launch_traces(self):
        """通しの再生で足した比べない欄: instance の launch_state・continue_of・role_def_missing と、盤面・記録の role_def_missing
        （記録は process の下のその 1 か所だけ。他の欄と、別の所の同じ名前は比べる）"""
        miss = [{"agent_type": "a:b", "instance": "x", "round": 1}]
        mem = {"state": {"role_def_missing": miss, "rounds": [{"instances": {"x": {
            "status": "done", "launch_state": "ended", "continue_of": "y", "role_def_missing": "定義が無い"}}}]},
            "record": {"process": {"role_def_missing": miss, "human_items": []}, "role_def_missing": 1}}
        self.assertEqual(R.normalize(mem), {"state": {"rounds": [{"instances": {"x": {"status": "done"}}}]},
                                            "record": {"process": {"human_items": []}, "role_def_missing": 1}})


if __name__ == "__main__":
    unittest.main()
