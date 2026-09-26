"""盤面の通しの再生（仕様 9.3 の「通し」）: 手本の Run を頭（init の手の後）の盤面から、撮った手の順に DiskBoard の口で当て続け、
盤面を engine の側から写し直さずに、周の終わり（rd・loop・record）と最後（state・record・ディスクの目録）が engine と同じかを見る。

再生は boardreplay.replay。Run ごとに 1 度だけ回して控え、場面ごとの試験はその控えを読む（全部の Run で数分かかるため）。
比べない欄（boardreplay.NOT_REPRODUCED）と、通しの再生を手の前で止める手（boardreplay.HAND_EDITED_STEPS）は、
test_replay_every_run が毎回理由つきで並べる（仕様 I12）。
"""
import contextlib
import dataclasses
import io
import json
import os
import pathlib
import shutil
import sys
import tempfile
import time
import types
import unittest
from unittest import mock

sys.dont_write_bytecode = True
HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import boardreplay as R  # noqa: E402  （board と写しの engine を sys.path に足す）
from board import GRAPH_PATH, GRAPH_SHA, BoardGap, DiskBoard, NodeTable  # noqa: E402
import engine.util as engine_util  # noqa: E402
from engine import commands as engine_commands  # noqa: E402
from engine.util import Reject  # noqa: E402

GRAPH = json.loads(GRAPH_PATH.read_text(encoding="utf-8"))
TABLE = NodeTable.everything(GRAPH, GRAPH_SHA)


@dataclasses.dataclass
class Outcome:
    got: dict           # 再生の ReplayResult
    exp: dict           # 手本の ReplayResult（golden_result）
    diffs: list         # result_diff（空なら同じ）
    disk: list          # 最後のディスクの目録の違い（空なら同じ）
    counts: dict
    seconds: float


_OUTCOMES = {}


@contextlib.contextmanager
def replay_env():
    """手本を撮った時と同じ git の名前・時刻（仕様 9.2 の 4）。engine の GIT_CWD は抜けるときに戻す"""
    cwd = engine_util.GIT_CWD
    try:
        with mock.patch.dict(os.environ, R.git_env()):
            yield
    finally:
        engine_util.GIT_CWD = cwd


def outcome(scenario, run) -> Outcome:
    """Run を 1 度だけ通しで再生して控える（一時の置き場は目録を取った後に消す）"""
    key = (scenario, str(run))
    if key not in _OUTCOMES:
        rs = R.load_runs(scenario)[str(run)]
        tmp = pathlib.Path(tempfile.mkdtemp(prefix="board-replay-"))
        counts = {}
        t0 = time.monotonic()
        try:
            with replay_env():
                got = R.replay(scenario, run, tmp, counts=counts)
            exp = R.golden_result(rs)
            disk = R.disk_diff(R.Places(tmp).board, R.golden_disk(rs))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        _OUTCOMES[key] = Outcome(got, exp, R.result_diff(exp, got), disk, counts, time.monotonic() - t0)
    return _OUTCOMES[key]


def runs_of(scenario):
    return [rs.run for rs in R.load_runs(scenario).values() if R.replayable(rs)]


def rd_parts(view):
    """周の箱の done・na・skipped の節と理由（done は節の名前だけ。時刻を持つので。手本の記憶は鍵を並べ直して撮ったので、
    順は比べない——順は done_order が盤面の側で見る）"""
    rd = view["rd"]
    return {"done": sorted(rd.get("done") or {}), "na": dict(rd.get("na") or {}), "skipped": dict(rd.get("skipped") or {})}


def done_order(view):
    """盤面の周の箱の done の順（済んだ順。手本の記憶は鍵を並べ直したので、engine の順は手の seq で見る）"""
    return list(view["rd"].get("done") or {})


def step_seq(scenario, run, kind, node):
    """手本の Run で、種類 kind・節 node の最初の通った手の seq（拒まれた手を除く）"""
    return next(s["seq"] for s in R.load_runs(scenario)[str(run)]
                if s["kind"] == kind and s.get("node") == node and not s.get("raised"))


class ReplayCase(unittest.TestCase):
    maxDiff = None

    def same(self, scenario, run):
        """通しの再生が engine と同じ（周ごとの rd・loop・record、最後の state・record・ディスクの目録）。Outcome を返す"""
        o = outcome(scenario, run)
        self.assertEqual(o.diffs, [], f"{scenario} run {run}:\n" + "\n".join(o.diffs[:30]))
        self.assertEqual(o.disk, [], f"{scenario} run {run}:\n" + "\n".join(o.disk[:30]))
        for n in o.exp["rounds"]:
            self.assertEqual(rd_parts(o.got["rounds"][n]), rd_parts(o.exp["rounds"][n]), f"{scenario} run {run} 周 {n}")
        return o

    def test_replay_every_run(self):
        """再生に当てる Run の全部を通しで当て、全部が engine と同じ。比べない欄と、手の前で止めた手を理由つきで並べる"""
        t0 = time.monotonic()
        total, bad, counts = 0, [], {}
        for rs in R.every_run():
            o = outcome(rs.scenario, rs.run)
            total += 1
            for k, v in o.counts.items():
                counts[k] = counts.get(k, 0) + v
            if o.diffs or o.disk:
                bad.append(f"{rs.scenario} run {rs.run}: " + " / ".join((o.diffs + o.disk)[:5]))
        lines = [f"\n通しの再生: {total} 本の Run のうち {total - len(bad)} 本が engine と同じ（{time.monotonic() - t0:.0f} 秒。"
                 f"当てた手 {counts.get('steps')}・settle {counts.get('settle')}・next の中の計画の落ち {counts.get('fallback')}・"
                 f"同じ文の拒み {counts.get('reject')}・BoardGap {counts.get('gap')}・当てない作業ツリーの突合 {counts.get('tree')}・"
                 f"手の前で止めた Run {counts.get('cut')}）",
                 "比べない欄（NOT_REPRODUCED）:"]
        lines += [f"  - {k}: {v}" for k, v in R.NOT_REPRODUCED.items()]
        lines.append("通しの再生を手の前で止めた手（HAND_EDITED_STEPS）:")
        lines += [f"  - {s} run {r} seq {q}: {why}" for (s, r, q), (_, _, why) in R.HAND_EDITED_STEPS.items()]
        print("\n".join(lines), file=sys.stderr)
        self.assertEqual(bad, [], "\n".join(bad))
        self.assertEqual(total, 33)             # 39 本 − init で拒まれた 5 本 − graph を手で直した stop-nodecl
        self.assertEqual(counts.get("cut"), len(R.HAND_EDITED_STEPS))

    def test_replay_converges(self):
        """test_converges: 各周の終わりの rd（done・na・skipped の節と理由）・loop・record と、最後の status == converged"""
        o = self.same("test_converges", 1)
        self.assertEqual(sorted(o.got["rounds"]), [1, 2, 3])
        self.assertEqual(o.got["final"]["state"]["status"], "converged")
        for n in (1, 2):   # 周を開く前の loop は次の周が読む物
            self.assertEqual(R.normalize(o.got["rounds"][n]["loop"]), R.normalize(o.exp["rounds"][n]["loop"]))

    def test_replay_runaway(self):
        """test_runaway（無人）: 周の上限まで回り、上限の問い（max_rounds）を無人の既定で止める"""
        o = self.same("test_runaway", 1)
        st = o.got["final"]["state"]
        self.assertEqual((st["round"], st["max_rounds"], st["status"]), (5, 5, "stopped"))
        hi = o.got["final"]["record"]["process"]["human_items"]
        self.assertEqual([(h["kinds"], h["answer"]) for h in hi], [(["max_rounds"], None)])

    def test_replay_awaiting(self):
        """test_awaiting: 周の終わりの問い（work_exhausted）→ continue と一言 → 次の周を開いて収束"""
        o = self.same("test_awaiting", 1)
        hi = o.got["final"]["record"]["process"]["human_items"]
        self.assertEqual([(h["kinds"], h["answer"], h["round"]) for h in hi], [(["work_exhausted"], "continue", 2)])
        self.assertEqual(hi[0]["note"], "テスト用設定 config/dev.local.example で起動できる")
        self.assertEqual(o.got["final"]["state"]["status"], "converged")
        self.assertEqual(sorted(o.got["rounds"]), [1, 2, 3, 4])

    def test_replay_request_entry(self):
        """test_request_entry の全部の Run: 判定から入る周の P1 の na の理由の文と、修正の後に入口が終わる周（run 1 の周 2）"""
        for run in runs_of("test_request_entry"):
            with self.subTest(run=run):
                self.same("test_request_entry", run)
        o = outcome("test_request_entry", 1)
        na1 = rd_parts(o.got["rounds"][1])["na"]
        self.assertTrue(na1["p1.gate_efficacy"].startswith("cond gate_efficacy_due: 判定から入る run の周"), na1["p1.gate_efficacy"])
        self.assertEqual(sum(k.startswith("p1.") for k in na1), 9)
        r2 = rd_parts(o.got["rounds"][2])
        self.assertFalse([k for k in r2["na"] if k.startswith("p1.")])
        self.assertIn("p1.local_review", r2["done"])
        self.assertEqual(o.got["rounds"][2]["loop"]["request_fixed_at"], 1)

    def test_replay_fix_plan(self):
        """test_fix_plan_review: 修正案 → 事前審査 → 関所 → 修正の順（周 1 の done の並び）と human_items"""
        o = self.same("test_fix_plan_review", 1)
        done = done_order(o.got["rounds"][1])
        order = [done.index(n) for n in ("p2.fix_plan", "p2.plan_review", "p2.human_gate", "p3.fix")]
        self.assertEqual(order, sorted(order))
        seqs = [step_seq("test_fix_plan_review", 1, k, n) for k, n in
                (("accept", "p2.fix_plan"), ("accept", "p2.plan_review"), ("builtin", "p2.human_gate"), ("accept", "p3.fix"))]
        self.assertEqual(seqs, sorted(seqs))    # engine も同じ順
        self.assertEqual(o.got["final"]["record"]["process"]["human_items"], o.exp["final"]["record"]["process"]["human_items"])
        self.assertEqual(o.counts["gap"], 1)       # 依存の済んでいない p3.fix の返答（engine は Reject、盤面は BoardGap）

    def test_replay_human_gate(self):
        """test_human_gate の全部の Run: 周の途中の問い → continue の一言が human_items に残り、同じ周の修正へ。
        stop は halted.by == answer、無人は halted.by == unattended"""
        for run in runs_of("test_human_gate"):
            with self.subTest(run=run):
                self.same("test_human_gate", run)
        o = outcome("test_human_gate", 1)
        first = o.got["final"]["record"]["process"]["human_items"][0]
        self.assertEqual((first["node"], first["answer"], first["note"], first["round"]),
                         ("p2.human_gate", "continue", "呼び元の経路は残せ（検査用 KEEP-NOTE）", 1))
        done = done_order(o.got["rounds"][1])
        self.assertLess(done.index("p2.human_gate"), done.index("p3.fix"))
        self.assertEqual(outcome("test_human_gate", 2).got["final"]["state"]["halted"]["by"], "answer")
        self.assertEqual(outcome("test_human_gate", 3).got["final"]["state"]["halted"]["by"], "unattended")

    def test_replay_policy(self):
        """方針の文書の固定（process.policy）と、変化を関所で通した後の amendments（test_human_gate の run 1）"""
        o = self.same("test_policy_reaches_roles", 1)
        pol = o.got["final"]["record"]["process"]["policy"]
        self.assertEqual(pol, o.exp["final"]["record"]["process"]["policy"])
        self.assertEqual((pol["path"], pol["amendments"]), ("@REPO@/.git/graphloops/policy.md", []))
        self.assertTrue(pol["sha256"] and pol["copy"].startswith("@BOARD@/policy/"))
        g = outcome("test_human_gate", 1)
        am = g.got["final"]["record"]["process"]["policy"]["amendments"]
        self.assertEqual(am, g.exp["final"]["record"]["process"]["policy"]["amendments"])
        self.assertEqual([(a["round"], a["from"], a["note"]) for a in am], [(1, None, "確かめた（検査用）")])

    def test_replay_stop(self):
        """test_stop_midround（graph の同じ Run）・test_stop_after_round の全部の Run: state.stop・halted が engine と同じ"""
        for scen in ("test_stop_midround", "test_stop_after_round"):
            for run in runs_of(scen):
                with self.subTest(scenario=scen, run=run):
                    o = self.same(scen, run)
                    got, exp = R.normalize(o.got["final"])["state"], R.normalize(o.exp["final"])["state"]
                    self.assertEqual(got.get("stop"), exp.get("stop"))
                    self.assertEqual(got.get("halted"), exp.get("halted"))
                    self.assertEqual(got["status"], "stopped")
        self.assertEqual(outcome("test_stop_midround", 1).counts["reject"], 2)   # 理由の空の stop と、止めた後の二度目
        self.assertEqual(outcome("test_stop_after_round", 2).got["final"]["state"]["halted"]["by"], "stop_after_round")

    def test_replay_gates_merge(self):
        """test_gates_merge の全部の Run: gates=merge の run は収束の判定が gates_deferred で止まる（init だけの Run も同じ）"""
        for run in runs_of("test_gates_merge"):
            with self.subTest(run=run):
                self.same("test_gates_merge", run)
        for run in (1, 2):
            fin = outcome("test_gates_merge", run).got["final"]
            self.assertEqual((fin["state"]["status"], fin["state"]["loop"]["stop_reason"]), ("stopped", "gates_deferred"))

    def test_replay_rejudge(self):
        """test_rejudge_path: 異議（patch）の周だけ p2.rejudge が走り、後の周は条件で na"""
        o = self.same("test_rejudge_path", 1)
        self.assertIn("p2.rejudge", rd_parts(o.got["rounds"][1])["done"])
        for n in (2, 3):
            self.assertTrue(rd_parts(o.got["rounds"][n])["na"]["p2.rejudge"].startswith("cond rejudge_open:"))
        self.assertEqual(o.got["final"]["state"]["status"], "converged")

    def test_replay_patch_steps(self):
        """patch の手（test_rejudge_path・test_request_entry）: 撮った差分を当てた後の続き（p2.rejudge が出る等）が engine と同じ。
        patch の手は next を打たずに挟まるので、done の後に毎回 settle すると p2.rejudge が異議の前に na になる（再生は台本の
        next の所で settle する）"""
        seen = 0
        for scen in ("test_rejudge_path", "test_request_entry"):
            for rs in R.load_runs(scen).values():
                if R.replayable(rs) and any(s["kind"] == "patch" for s in rs):
                    with self.subTest(scenario=scen, run=rs.run):
                        o = self.same(scen, rs.run)
                        self.assertEqual(o.got["final"]["state"]["patches"], o.exp["final"]["state"]["patches"])
                    seen += 1
        self.assertEqual(seen, 5)
        o = outcome("test_rejudge_path", 1)
        self.assertEqual(o.got["rounds"][1]["loop"]["rejudge_requested"]["text"], "この修正は入口を 1 つしか塞いでいない")

    def test_replay_finalize(self):
        """test_stop_after_round の finalize の手の後の record（process.skipped・halted など）が engine と同じ"""
        o = self.same("test_stop_after_round", 1)
        self.assertEqual(R.normalize(o.got["final"])["record"], R.normalize(o.exp["final"])["record"])
        proc = o.got["final"]["record"]["process"]
        self.assertEqual(proc["halted"]["by"], "stop_after_round")
        self.assertEqual(proc["skipped"], [])
        self.assertIn("finalize", {s["kind"] for s in R.load_runs("test_stop_after_round")["1"]})

    def test_replay_rejections(self):
        """test_rejections: 拒まれた返答（50 手）は同じ文で拒み、作業ツリーの突合の 1 手は当てない。宣言の無いリポジトリの run
        （neg-nodecl。init だけの Run）は、最後の next の中で engine が p0.local_checks を任せ先に落とした記録（checks_fallback）が
        手本の final と同じ——盤面は run_engine の中で書くが、周の終わりの値は同じ"""
        o = self.same("test_rejections", 1)
        self.assertEqual((o.counts["reject"], o.counts["tree"]), (50, 1))
        o = self.same("test_rejections", 2)
        self.assertEqual(o.got["final"]["record"]["process"]["checks"]["p0.local_checks"]["by"], "role")
        self.assertTrue(o.got["final"]["state"]["rounds"][0]["instances"]["p0.local_checks"]["engine_fallback"])
        self.assertEqual(o.counts["fallback"], 1)

    def test_hand_edited_steps_are_hand_edits(self):
        """HAND_EDITED_STEPS の手の前に、台本が engine を通さずに書いた物が本当に在る（手の前の手の後には無く、この手の前に在る）"""
        for (scen, run, seq), (kind, node, _) in R.HAND_EDITED_STEPS.items():
            with self.subTest(scenario=scen, run=run, seq=seq):
                rs = R.load_runs(scen)[run]
                i = next(i for i, s in enumerate(rs) if s["seq"] == seq)
                self.assertEqual(rs[i]["kind"], "add")
                prev = rs[i - 1]["seq"]
                inst = R.memory_at(rs, seq, "before")["state"]["rounds"][-1]["instances"][node]
                was = R.memory_at(rs, prev, "after")["state"]["rounds"][-1]["instances"].get(node) or {}
                if kind == "launched_at":
                    self.assertTrue(inst.get("launched_at"))
                    self.assertFalse(was.get("launched_at"))
                else:
                    rel = inst["out_path"].removeprefix("@BOARD@/")
                    self.assertIn(rel, R.manifest_at(rs, seq, "before", "disk"))
                    self.assertNotIn(rel, R.manifest_at(rs, prev, "after", "disk"))
                    self.assertEqual(inst["status"], "pending")

    def test_replay_init_matches_create(self):
        """全部の init の手（graph を手で直した stop-nodecl を除く）: 同じ入力の create の state・record が手の後と同じ
        （NOT_REPRODUCED を除く）。拒まれた init は create が同じ文で拒む"""
        done, rejected = 0, 0
        for scen in R.manifest()["scenarios"]:
            for rs in R.load_runs(scen).values():
                s = rs[0]
                if s["args"].get("graph"):
                    continue    # 台本が手で直した graph（stop-nodecl）
                with self.subTest(scenario=scen, run=rs.run), tempfile.TemporaryDirectory(prefix="board-init-") as tmp, replay_env():
                    places = R.Places(tmp)
                    repo = R.restore_repo(rs, s["seq"], tmp)
                    a = places.untokenize(s["args"])
                    kw = dict(repo=repo, table=TABLE, inputs=dict(kv.partition("=")[::2] for kv in a["input"] or []),
                              request_text=a["request"], stop_after_round=a["stop_after_round"], unattended=a["unattended"])
                    self.assertEqual((a["thickness"], a["decider"], a["lang"], a["document"], a["unfenced_delegates"]),
                                     (None, None, None, None, None))
                    if s.get("raised"):
                        with self.assertRaises((Reject, BoardGap)) as cm:
                            DiskBoard.create(places.board, **kw)
                        self.assertEqual(places.tokenize(str(cm.exception)), s["raised"]["text"])
                        self.assertFalse(places.board.exists())
                        rejected += 1
                        continue
                    b = DiskBoard.create(places.board, **kw)
                    out = []
                    R._diff(R.normalize(R.memory_at(rs, s["seq"], "after")),
                            R.normalize(places.tokenize({"state": b.state, "record": b.record})), "", out)
                    self.assertEqual(out, [])
                    self.assertEqual(R.disk_diff(places.board, R.manifest_at(rs, s["seq"], "after", "disk")), [])
                    done += 1
        print(f"\n手本の init の手: 通った {done} 手を create に当て手の後と同じ・拒まれた {rejected} 手は同じ文", file=sys.stderr)
        self.assertEqual((done, rejected), (33, 5))

    def test_replay_never_resyncs(self):
        """replay の中で盤面の置き場へ手本を書く道が無い: boardreplay の書き込みは頭の restore（盤面と対象リポジトリ）と
        board_from_memory の 1 度ずつ、後はリポジトリだけ。手本の記憶から盤面を組むのも頭の init の手の後だけ"""
        writes, built = [], []
        real_write, real_build = R._write_tree, R.board_from_memory

        def write_tree(top, files, places):
            writes.append(pathlib.Path(top))
            return real_write(top, files, places)

        def build(mem, board_dir, table, allow_halted=False):
            built.append(mem)
            return real_build(mem, board_dir, table, allow_halted)
        scen, run = "test_stop_midround", "1"      # accept・engine_run・stop（拒みを含む）・next の中の手が揃う短い Run
        rs = R.load_runs(scen)[run]
        with tempfile.TemporaryDirectory(prefix="board-resync-") as tmp, replay_env(), \
                mock.patch.object(R, "_write_tree", write_tree), mock.patch.object(R, "board_from_memory", build):
            got = R.replay(scen, run, tmp)
            places = R.Places(tmp)
            self.assertEqual(R.result_diff(R.golden_result(rs), got), [])
        self.assertEqual(len(built), 1)
        self.assertEqual(built[0], R.memory_at(rs, rs[0]["seq"], "after"))
        self.assertEqual(writes.count(places.board), 1)
        self.assertEqual(writes[0], places.board)
        self.assertEqual(set(writes[1:]), {places.repo})
        self.assertGreater(len(writes), 10)

    def test_blocked_plan_record_same_as_engine(self):
        """走らせない計画（blocked）: engine の launch_engine_run（空の runs）と盤面の run_engine で、記録（process.checks・素材）と
        周の箱が同じ。engine だけが trace の engine_run の行と runs/ の空の置き場を作る（盤面は走らせないので作らない）"""
        s = next(x for x in R.load_runs("test_converges")["1"] if x["kind"] == "engine_run" and x["node"] == "p4.ci")
        why = "宣言の書式が読めない（検査用）"
        with tempfile.TemporaryDirectory(prefix="board-blocked-") as tmp, replay_env():
            d, _ = R.restore(s.run_steps, s["seq"], "before", tmp)
            b = R.board_from_memory(R.memory_at(s.run_steps, s["seq"], "before"), d, TABLE)
            twin = pathlib.Path(tmp) / "twin"
            shutil.copytree(d, twin)
            got = b.run_engine("p4.ci", plan={"blocked": why}, runner=R._refuse_runner)
            self.assertEqual((got["ok"], got["blocked"]), (True, why))
            with contextlib.redirect_stdout(io.StringIO()):
                eb = engine_commands.Board(twin)
                inst = eb.rd["instances"]["p4.ci"]
                inst["launch"] = {"kind": "engine_run", "builtin": "declared_checks", "steps": [], "sha": None, "blocked": why}
                eb.save()
                engine_commands.launch_engine_run(str(twin), inst)
            want = {"state": json.loads((twin / "state.json").read_text(encoding="utf-8")),
                    "record": json.loads((twin / "record.json").read_text(encoding="utf-8"))}
            have = {"state": json.loads((d / "state.json").read_text(encoding="utf-8")),
                    "record": json.loads((d / "record.json").read_text(encoding="utf-8"))}
            self.assertEqual(R.normalize(have["record"]), R.normalize(want["record"]))
            self.assertEqual(have["record"]["process"]["checks"]["p4.ci"]["blocked"], why)
            self.assertEqual(R.normalize(have)["state"]["rounds"], R.normalize(want)["state"]["rounds"])
            self.assertTrue((twin / "runs" / f"r{b.round}" / "p4.ci.a1").is_dir())
            self.assertFalse((d / "runs" / f"r{b.round}" / "p4.ci.a1").exists())
            ops = lambda p: [json.loads(x)["op"] for x in (p / "trace.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()]
            self.assertIn("engine_run", ops(twin))
            self.assertNotIn("engine_run", ops(d))


if __name__ == "__main__":
    unittest.main()
