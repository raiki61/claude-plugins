"""engine が走らせる節 DiskBoard.run_engine と既定の runner tree_runner の試験（仕様 4.3・9.1 の 8）。

盤面は手本（tests/boards/golden-a1202d0/）の手の前の記憶とディスクとリポジトリを一時の場所に戻して組む（test_board_steps と
同じ道具）。engine_run の節の instance は、settle が出す最小の形（engine の計画の欄 mode・launch の無い物）に直してから当てる。
宣言（.review-checks.json）は戻したリポジトリの物を書き換え・消して使う。p0.parallel_pr は偽の gh（PATH の頭）と
GitHub の形の remote で当て、本物の gh・GitHub には触らない。
"""
import copy
import json
import os
import pathlib
import re
import signal
import subprocess
import sys
import unittest
from unittest import mock

sys.dont_write_bytecode = True
HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import boardreplay as R  # noqa: E402  （board と写しの engine を sys.path に足す）
from test_board_steps import TABLE, StepCase, first_step, kind_steps, tok, trace_ops, with_by  # noqa: E402
import entry  # noqa: E402
import gitkit  # noqa: E402
import tree_run  # noqa: E402
from board import CORE_DIR, BoardGap, tree_runner  # noqa: E402
from engine import declared  # noqa: E402
from engine.commands import engine_run_refusal  # noqa: E402
from engine.role_run import run_steps as engine_run_steps  # noqa: E402
from tree_run import Stopped  # noqa: E402

HELPER = CORE_DIR / "graphloops" / "scripts" / "parallel-pr.py"
DECL = ".review-checks.json"
GREEN = [{"name": "suite", "argv": ["python3", "-c", "print('1 passed')"]}]
RED = [{"name": "suite", "argv": ["python3", "-c", "import sys; print('1 failed'); sys.exit(3)"]}]
MINIMAL = ("id", "node", "run_by", "status", "emitted_at", "out_path")


def engine_run_step(node, nth=0):
    return [s for s in kind_steps("engine_run") if s["node"] == node][nth]


def minimal(*nodes):
    """記憶の edit: 節の instance を settle が出す最小の形にする（engine の計画の欄 mode・launch・engine_fallback を落とす）"""
    def edit(mem):
        insts = mem["state"]["rounds"][-1]["instances"]
        for nid in nodes:
            insts[nid] = {k: insts[nid][k] for k in MINIMAL}
            insts[nid]["status"] = "pending"
    return edit


def disk_bytes(board):
    return {n: (board.dir / n).read_bytes() for n in ("state.json", "record.json", "trace.jsonl")}


def never(*a, **kw):
    raise AssertionError(f"runner を呼んではいけない: {a}")


class EngineRunCase(StepCase):
    def repo(self, b):
        return b.dir.parent / "repo"

    def write_decl(self, b, steps):
        (self.repo(b) / DECL).write_text(json.dumps({"suite": steps}), encoding="utf-8")

    def ci_board(self, table=TABLE, decl=GREEN):
        """p4.ci が待っている盤面（手本の最初の p4.ci の engine_run の手の前。instance は最小の形）。decl=None なら宣言を消す"""
        b = self.board_before(engine_run_step("p4.ci"), table=table, edit=minimal("p4.ci"))
        if decl is None:
            (self.repo(b) / DECL).unlink()
        else:
            self.write_decl(b, decl)
        return b

    def pr_board(self, table=TABLE):
        """p0.parallel_pr が待っている盤面（手本の最初の p0.parallel_pr の受け付けの手の前。instance は最小の形。
        remote は GitHub の形）"""
        b = self.board_before(first_step("test_converges", "p0.parallel_pr"), table=table, edit=minimal("p0.parallel_pr"))
        subprocess.run(["git", "-C", str(self.repo(b)), "remote", "add", "origin", "git@github.com:o/r.git"], check=True)
        return b

    def fake_gh(self, prs, files):
        """PATH の頭に偽の gh を置く: pr list は prs、pr view <番号> は files[番号] の行を返す（他の語は exit 9）"""
        top = self.tmp / "fake-gh"
        (top / "bin").mkdir(parents=True, exist_ok=True)
        (top / "list.json").write_text(json.dumps(prs), encoding="utf-8")
        for num, paths in files.items():
            (top / f"view-{num}.txt").write_text("".join(p + "\n" for p in paths), encoding="utf-8")
        gh = top / "bin" / "gh"
        gh.write_text("#!/bin/sh\n"
                      f'if [ "$1" = pr ] && [ "$2" = list ]; then cat "{top}/list.json"; exit 0; fi\n'
                      f'if [ "$1" = pr ] && [ "$2" = view ]; then cat "{top}/view-$3.txt"; exit 0; fi\n'
                      'echo "fake gh: $*" >&2; exit 9\n', encoding="utf-8")
        gh.chmod(0o755)
        env = mock.patch.dict(os.environ, {"PATH": f"{top / 'bin'}{os.pathsep}{os.environ['PATH']}"})
        env.start()
        self.addCleanup(env.stop)


class RunEngineCase(EngineRunCase):
    def test_ci_by_engine_recorded(self):
        """宣言（緑の 1 段）の在るリポジトリで run_engine("p4.ci")（既定の runner）→ process.checks["p4.ci"] が engine の形"""
        b = self.ci_board()
        got = b.run_engine("p4.ci")
        self.assertTrue(got["ok"], got)
        self.assertEqual(got["node"], "p4.ci")
        c = b.record["process"]["checks"]["p4.ci"]
        self.assertEqual(set(c), {"round", "by", "sha", "runs"})
        self.assertEqual((c["round"], c["by"]), (b.round, "engine"))
        self.assertEqual(c["sha"], declared.steps_sha(GREEN))
        self.assertEqual([(r["name"], r["argv"], r["exit"]) for r in c["runs"]], [("suite", GREEN[0]["argv"], 0)])
        log = b.dir / "runs" / f"r{b.round}" / "p4.ci.a1"
        self.assertEqual(c["runs"][0]["out"], str(log / "1.out"))
        self.assertEqual((log / "1.out").read_text(encoding="utf-8"), "1 passed\n")
        self.assertEqual(b.record["materials"]["local_checks"]["status"], "clean")
        inst = b.rd["instances"]["p4.ci"]
        self.assertEqual(inst["status"], "done")
        self.assertEqual(inst["mode"], "engine_run")
        self.assertEqual({k: inst["launch"][k] for k in ("kind", "builtin", "steps", "blocked")},
                         {"kind": "engine_run", "builtin": "declared_checks", "steps": GREEN, "blocked": None})
        # 保存した（ディスクも同じ）。settle はしない
        on_disk = json.loads((b.dir / "record.json").read_text(encoding="utf-8"))
        self.assertEqual(on_disk["process"]["checks"]["p4.ci"]["by"], "engine")
        self.assertIn("engine_run", [r["op"] for r in trace_ops(b)])

    def test_red_suite_found(self):
        """赤の段 → local_checks が found・count 1（p0.local_checks。素材は判定の前なので人待ちに化けない）"""
        b = self.board_before(engine_run_step("p0.local_checks"), edit=minimal("p0.local_checks"))
        self.write_decl(b, RED)
        got = b.run_engine("p0.local_checks")
        self.assertTrue(got["ok"], got)
        m = b.record["materials"]["local_checks"]
        self.assertEqual((m["status"], m["count"]), ("found", 1))
        self.assertIn("1 failed", m["detail"])
        self.assertEqual(b.record["process"]["checks"]["p0.local_checks"]["runs"][0]["exit"], 3)

    def reported_step(self, cases: str | None, code: int, name="suite"):
        """試験の報告 report.xml を宣言した段: cases（<testcase> の並び）を書いて code で終わる。cases が None なら何も書かずに終わる"""
        body = "" if cases is None else f"open('report.xml','w').write({f'<testsuite>{cases}</testsuite>'!r});"
        return {"name": name, "argv": ["python3", "-c", f"import sys;{body}sys.exit({code})"], "junit": "report.xml"}

    def local_checks_for(self, step, before=None):
        """p0.local_checks を既定の runner で走らせた素材。before は走らせる前に report.xml に置く（本文, 何秒前の更新か）"""
        b = self.board_before(engine_run_step("p0.local_checks"), edit=minimal("p0.local_checks"))
        self.write_decl(b, [step])
        if before:
            report = self.repo(b) / "report.xml"
            report.write_text(before[0], encoding="utf-8")
            old = report.stat().st_mtime - before[1]
            os.utime(report, (old, old))
        self.assertTrue(b.run_engine("p0.local_checks")["ok"])
        return b.record["materials"]["local_checks"]

    def test_unran_step_is_not_found(self):
        """報告（junit）を宣言した段が試験を走らせていない形——件数 0・全部 error・報告が無い・段より古い報告・XML が壊れている
        ——は、赤（found）でなく起こせない段と同じ awaiting_human（p0）。終了コードの数値でなく件数で分ける"""
        stale = "<testsuite><testcase name='t'><failure/></testcase></testsuite>"
        cases = [(self.reported_step("", 5), None, "試験が 0 件"),
                 (self.reported_step("<testcase name='t'><error/></testcase>", 1), None, "全部 error"),
                 (self.reported_step(None, 4), None, "report.xml が無い"),
                 (self.reported_step(None, 1), (stale, 3600), "段の起動より古い"),
                 (self.reported_step("<testcase", 2), None, "XML として読めない")]
        for step, before, want in cases:
            with self.subTest(want):
                m = self.local_checks_for(step, before)
                self.assertEqual(m["status"], "awaiting_human", m)
                self.assertIn("基準の検査が走らなかった", m["reason"])
                self.assertIn(want, m["reason"])
                self.assertNotIn("count", m)

    def test_ran_red_step_is_found(self):
        """報告に走った試験が在り failure が在る段は、終了コードが何でも found（走って落ちた赤）。走ったかを疑う文は添えない"""
        m = self.local_checks_for(self.reported_step("<testcase name='t'><failure/></testcase>", 5))
        self.assertEqual((m["status"], m["count"]), ("found", 1))
        self.assertNotIn("走ったかは確かめていない", m["detail"])

    def test_ran_green_step_is_clean(self):
        m = self.local_checks_for(self.reported_step("<testcase name='t'/>", 0))
        self.assertEqual(m["status"], "clean", m)

    def test_red_step_without_report_says_unverified(self):
        """報告を宣言していない段の赤は found のまま、段ごとに走ったかは確かめていないと detail に添える"""
        b = self.board_before(engine_run_step("p0.local_checks"), edit=minimal("p0.local_checks"))
        self.write_decl(b, RED)
        self.assertTrue(b.run_engine("p0.local_checks")["ok"])
        m = b.record["materials"]["local_checks"]
        self.assertEqual(m["status"], "found")
        self.assertIn("走ったかは確かめていない（試験の報告の宣言が無い段: suite）", m["detail"])

    def test_junit_key_is_checked_by_parse(self):
        step = {"name": "a", "argv": ["x"]}
        steps, err = declared.parse(json.dumps({"suite": [{**step, "junit": "out/r.xml"}]}))
        self.assertIsNone(err)
        self.assertEqual(steps, [{**step, "junit": "out/r.xml"}])
        for bad in ("", "/abs.xml", "../r.xml", 3):
            with self.subTest(bad):
                self.assertIsNotNone(declared.parse(json.dumps({"suite": [{**step, "junit": bad}]}))[1])
        self.assertIsNotNone(declared.parse(json.dumps({"suite": [{**step, "other": 1}]}))[1])

    def test_reused_steps_named_in_material_and_rows(self):
        """同じ run の中で p0.local_checks を同じ木で 2 度走らせると、2 度目の素材 local_checks の checked に『控えから使った段』と
        出どころの run が出る（1 度目には出ない）。entry.run_ci の返りの rows にも reused が通る"""
        env = {"ARTIFACTS_DIR": str(self.tmp / "arts" / "run-a"), "WORKS_TESTSLOT": ""}
        got = []
        with mock.patch.dict(os.environ, env):
            os.environ.pop("GRAPHLOOPS_RERUN_CHECKS", None)
            for _ in range(2):
                b = self.board_before(engine_run_step("p0.local_checks"), edit=minimal("p0.local_checks"))
                self.write_decl(b, GREEN)
                ci = entry.run_ci(b, "p0.local_checks", test_cmd="")
                got.append((ci, b.record["materials"]["local_checks"]))
        (ci1, m1), (ci2, m2) = got
        self.assertEqual((m1["status"], m2["status"]), ("clean", "clean"))
        self.assertNotIn("控えから使った段", m1["checked"])
        self.assertIn("控えから使った段: suite（run run-a・", m2["checked"])
        self.assertIn("・鍵 ", m2["checked"])
        self.assertNotIn("reused", ci1["runs"][0])
        self.assertEqual(set(ci2["runs"][0]), {"name", "exit", "how", "reused"})
        self.assertEqual(ci2["runs"][0]["reused"]["from"], "run-a")
        with self.subTest("reported_step"):
            self.check_reused_reported_step_still_counts_as_ran()

    def check_reused_reported_step_still_counts_as_ran(self):
        """試験の報告（junit）を宣言した段を同じ run の中で使い回した回は、報告が書き戻されて、走ったと数える（件数で見る
        checks_reply が『走らなかった段』に落とさない）。報告は .gitignore に当たる場所に書く段（当たらなければ木が変わり、控えない）"""
        step = self.reported_step("<testcase name='t'/>", 0)
        env = {"ARTIFACTS_DIR": str(self.tmp / "arts" / "run-a"), "WORKS_TESTSLOT": ""}
        got = []
        with mock.patch.dict(os.environ, env):
            os.environ.pop("GRAPHLOOPS_RERUN_CHECKS", None)
            for _ in range(2):
                b = self.board_before(engine_run_step("p0.local_checks"), edit=minimal("p0.local_checks"))
                ignore = self.repo(b) / ".gitignore"
                ignore.write_text((ignore.read_text(encoding="utf-8") if ignore.exists() else "") + "report.xml\n", encoding="utf-8")
                self.write_decl(b, [step])
                ci = entry.run_ci(b, "p0.local_checks", test_cmd="")
                got.append((ci, b.record["materials"]["local_checks"]))
        (ci1, m1), (ci2, m2) = got
        self.assertEqual((m1["status"], m2["status"]), ("clean", "clean"), got)
        self.assertNotIn("reused", ci1["runs"][0])
        self.assertIn("reused", ci2["runs"][0])

    def test_declaration_changed_refused(self):
        """撮った計画を差し込み、宣言を書き換えてから当てる → {ok: False, relaunch: True}、why は engine_run_refusal の文。
        何も走らず、盤面（state・record・trace）は前のまま、節は待ちのまま"""
        s = engine_run_step("p4.ci")
        b = self.board_before(s, edit=minimal("p4.ci"))
        plan = R.engine_run_plan(s, b)
        self.write_decl(b, GREEN + [{"name": "lint", "argv": ["python3", "-c", "pass"]}])
        want = engine_run_refusal({"launch": {"steps": plan["steps"], "sha": plan["sha"]}}, str(self.repo(b).resolve()))
        self.assertTrue(want)
        before = disk_bytes(b)
        got = b.run_engine("p4.ci", runner=never, plan=plan)
        self.assertEqual(got, {"ok": False, "node": "p4.ci", "why": want, "relaunch": True})
        self.assertEqual(disk_bytes(b), before)
        self.assertEqual(b.rd["instances"]["p4.ci"]["status"], "pending")
        self.assertNotIn("engine_fallback", b.rd["instances"]["p4.ci"])
        self.assertFalse((b.dir / "runs" / f"r{b.round}" / "p4.ci.a1").exists())
        # 呼び直す（計画し直す）と今の宣言で走る
        self.assertTrue(b.run_engine("p4.ci")["ok"])
        self.assertEqual([r["name"] for r in b.record["process"]["checks"]["p4.ci"]["runs"]], ["suite", "lint"])

    def test_reject_falls_back_from_disk(self):
        """reply は通るが受け付けが拒む返答 → 任せ先へ。読み直した盤面で by: role・instance.engine_fallback、他の欄は
        ディスクの前と同じ（拒まれた入れ物に reply が書いた by: engine は残らない）。入れ直した self で保存が衝突しない"""
        b = self.ci_board()
        state0 = json.loads((b.dir / "state.json").read_text(encoding="utf-8"))
        record0 = json.loads((b.dir / "record.json").read_text(encoding="utf-8"))
        er = b.rules.ENGINE_RUNS["declared_checks"]
        real = er["reply"]
        seen = {}

        def bad_reply(board, nid, launch, runs):
            got = real(board, nid, launch, runs)                   # by: engine を記憶に書く
            seen["by"] = board.record["process"]["checks"][nid]["by"]
            return {"reply": {"material": {"status": "no-such-status"}}}
        with mock.patch.dict(er, {"reply": bad_reply}):
            got = b.run_engine("p4.ci")
        self.assertEqual(seen["by"], "engine")
        self.assertFalse(got["ok"])
        self.assertIn("engine が組んだ返答を受け付けが拒んだ", got["fallback"])
        self.assertEqual([r["name"] for r in got["runs"]], ["suite"])
        # 記憶（self）もディスクも、読み直した盤面
        for rec in (b.record, json.loads((b.dir / "record.json").read_text(encoding="utf-8"))):
            self.assertEqual(rec["process"]["checks"]["p4.ci"], {"round": b.round, "by": "role", "why": got["fallback"]})
            want = copy.deepcopy(record0)
            want["process"]["checks"]["p4.ci"] = rec["process"]["checks"]["p4.ci"]
            self.assertEqual(rec, want)
        st = json.loads((b.dir / "state.json").read_text(encoding="utf-8"))
        self.assertEqual(st["rev"], state0["rev"] + 1)
        self.assertEqual(b.seen_rev, st["rev"])
        inst = st["rounds"][-1]["instances"]["p4.ci"]
        self.assertEqual((inst["status"], inst["engine_fallback"]), ("pending", got["fallback"]))
        self.assertNotIn("mode", inst)
        self.assertNotIn("launch", inst)
        for x in (st, state0):
            x.pop("rev")
            x.pop("works", None)
            x["rounds"][-1]["instances"].pop("p4.ci")
        self.assertEqual(st, state0)
        self.assertEqual(b.state["rounds"][-1]["instances"]["p4.ci"]["engine_fallback"], got["fallback"])
        b.save()   # 入れ直した版で保存できる（BoardConflict にならない）

    def test_stopped_writes_nothing(self):
        """runner が Stopped を投げる → 投げ直し、盤面（state・record・trace）は変わらず、節は待ちのまま"""
        b = self.ci_board()
        before = disk_bytes(b)

        def stopped(steps, cwd, log_dir):
            raise Stopped(signal.SIGTERM)
        with self.assertRaises(Stopped):
            b.run_engine("p4.ci", runner=stopped)
        self.assertEqual(disk_bytes(b), before)
        self.assertEqual(b.rd["instances"]["p4.ci"]["status"], "pending")
        self.assertNotIn("launch", b.rd["instances"]["p4.ci"])

    def test_rerun_keeps_earlier_logs(self):
        """止められた後に呼び直すと、ログは次の空いた番号の置き場（.a2）に書き、前の走りのログを上書きしない"""
        b = self.ci_board()

        def stopped(steps, cwd, log_dir):
            log_dir.mkdir(parents=True)
            (log_dir / "1.out").write_text("前の走り\n", encoding="utf-8")
            raise Stopped(signal.SIGTERM)
        with self.assertRaises(Stopped):
            b.run_engine("p4.ci", runner=stopped)
        got = b.run_engine("p4.ci")
        self.assertTrue(got["ok"], got)
        top = b.dir / "runs" / f"r{b.round}"
        self.assertEqual((top / "p4.ci.a1" / "1.out").read_text(encoding="utf-8"), "前の走り\n")
        self.assertEqual(got["runs"][0]["out"], str(top / "p4.ci.a2" / "1.out"))
        self.assertEqual((top / "p4.ci.a2" / "1.out").read_text(encoding="utf-8"), "1 passed\n")

    def test_no_declaration_falls_back(self):
        """宣言が無い → process.checks["p4.ci"].by == "role"、instance.engine_fallback、表の fallback=machine なら ready に残る"""
        b = self.ci_board(decl=None)
        got = b.run_engine("p4.ci", runner=never)
        self.assertFalse(got["ok"])
        self.assertIn(DECL, got["fallback"])
        self.assertNotIn("runs", got)
        c = b.record["process"]["checks"]["p4.ci"]
        self.assertEqual(c, {"round": b.round, "by": "role", "why": got["fallback"]})
        self.assertEqual(b.rd["instances"]["p4.ci"]["engine_fallback"], got["fallback"])
        self.assertEqual(TABLE.nodes["p4.ci"].fallback, "machine")
        self.assertIn("p4.ci", b._progress([])["ready"])

    def test_fallback_then_settle_same_board(self):
        """宣言の無いリポジトリで run_engine の後、同じ入れ物の settle が BoardConflict にならず、ready に p4.ci が残る"""
        b = self.ci_board(decl=None)
        b.run_engine("p4.ci")
        p = b.settle()
        self.assertIn("p4.ci", p["ready"])
        self.assertEqual(json.loads((b.dir / "state.json").read_text(encoding="utf-8"))["rev"], b.seen_rev)

    def test_fallback_absent_skips(self):
        """表の fallback=absent → 周の箱の skipped に表の理由、instance は skipped、ready に出ない"""
        reason = "このラインは CI の任せ先を持たない（検査用）"
        table = with_by(TABLE, "p4.ci", by="engine_run", fallback="absent", reason=reason)
        b = self.ci_board(table=table, decl=None)
        got = b.run_engine("p4.ci", runner=never)
        self.assertFalse(got["ok"])
        self.assertEqual(b.rd["skipped"]["p4.ci"], reason)
        self.assertEqual(b.node_state("p4.ci"), "skipped")
        self.assertEqual(b.rd["instances"]["p4.ci"]["status"], "skipped")
        self.assertEqual(b.state["done_ever"]["p4.ci"], b.round)
        self.assertEqual(b.record["process"]["checks"]["p4.ci"]["by"], "role")   # CI を engine が確かめていない印は残る
        self.assertNotIn("p4.ci", b._progress([])["ready"])

    def test_done_on_engine_run_refused(self):
        """engine_fallback の無い engine_run の節へのラインの accept・done → BoardGap。任せ先に落ちた後の done は受ける"""
        s = engine_run_step("p4.ci")
        acc = next(x for x in s.run_steps if x.get("parent") == s["seq"])
        b = self.ci_board(decl=None)
        out = R.reply(acc, b)
        before = disk_bytes(b)
        with self.assertRaises(BoardGap):
            b.done("p4.ci", out)
        with self.assertRaises(BoardGap):
            b.accept("p4.ci", out)
        self.assertEqual(disk_bytes(b), before)
        b.run_engine("p4.ci")
        R.mark(b, "p4.ci")        # 任せ先の役を起こす前の印（ラインと同じ）
        p = b.done("p4.ci", out)
        self.assertEqual(b.rd["instances"]["p4.ci"]["status"], "done")
        self.assertNotIn("p4.ci", p["ready"])
        # 任せ先に落ちた後は run_engine を拒む（ラインが done で渡す）
        b2 = self.ci_board(decl=None)
        b2.run_engine("p4.ci")
        with self.assertRaises(BoardGap):
            b2.run_engine("p4.ci")

    def test_run_engine_wiring_gap(self):
        """engine_run でない節・表で engine_run でない節・instance の無い節・依存が済んでいない節は BoardGap"""
        b = self.ci_board()
        with self.assertRaises(BoardGap):
            b.run_engine("p4.record")          # 機械の節
        with self.assertRaises(BoardGap):
            b.run_engine("p0.parallel_pr")     # この周の instance は受けて done
        del b.rd["instances"]["p4.ci"]
        with self.assertRaises(BoardGap):
            b.run_engine("p4.ci")
        b = self.ci_board(table=with_by(TABLE, "p4.ci", by="absent", reason="検査用"))
        with self.assertRaises(BoardGap):
            b.run_engine("p4.ci", runner=never)

    def test_blocked_builds_reply_without_running(self):
        """宣言が在るのに読めない → blocked: 走らせずに reply が返答を組む（p4.ci は not_run）"""
        b = self.ci_board()
        (self.repo(b) / DECL).write_text("{not json", encoding="utf-8")
        got = b.run_engine("p4.ci", runner=never)
        self.assertTrue(got["ok"], got)
        self.assertIn(DECL, got["blocked"])
        self.assertEqual(got["runs"], [])
        self.assertEqual(b.record["materials"]["local_checks"]["status"], "not_run")
        self.assertEqual(b.record["process"]["checks"]["p4.ci"]["blocked"], got["blocked"])

    def test_in_next_fallback_matches_neg_nodecl(self):
        """手本の neg-nodecl（宣言の無いリポジトリ。engine は next の中で p0.local_checks を任せ先に落とし、手としては撮れず
        Run の final の盤面にだけ見える）: init の後から settle → run_engine("p0.local_checks") の記録と周の箱が final と同じ"""
        rs = R.load_runs("test_rejections")["2"]
        self.assertIn("neg-nodecl", rs.meta["dir"])
        init = rs[0]
        self.assertEqual(init["kind"], "init")
        b = self.board_before(init, which="after")
        self.assertFalse((self.repo(b) / DECL).exists())
        b.settle()
        got = b.run_engine("p0.local_checks", runner=never)
        final = json.loads(R.blob(rs.meta["final"]["memory"]))
        mine = R.normalize(tok(b, {"state": b.state, "record": b.record}))
        want = R.normalize(final)
        self.assertEqual(mine["record"], want["record"])
        self.assertEqual(want["record"]["process"]["checks"]["p0.local_checks"]["by"], "role")
        rd, wrd = mine["state"]["rounds"][-1], want["state"]["rounds"][-1]
        for k in ("done", "na", "skipped", "stopped", "empty"):
            self.assertEqual(rd[k], wrd[k], k)
        self.assertEqual(sorted(rd["instances"]), sorted(wrd["instances"]))
        for nid, i in wrd["instances"].items():
            self.assertEqual(rd["instances"][nid]["status"], i["status"], nid)
            self.assertEqual(rd["instances"][nid].get("engine_fallback"), i.get("engine_fallback"), nid)
        self.assertEqual(got["fallback"], wrd["instances"]["p0.local_checks"]["engine_fallback"])


class ParallelPrCase(EngineRunCase):
    def test_helper_runs_copied_script(self):
        """p0.parallel_pr の helper の計画: runner に渡る argv が [今の Python, <写し>/graphloops/scripts/parallel-pr.py, …]、
        そのファイルが在る。既定の runner で写しを偽の gh に当てて走らせ（交差なし）、engine の返答で受ける"""
        self.assertTrue(HELPER.is_file())
        b = self.pr_board()
        self.fake_gh([{"number": 7, "headRefName": "other", "headRefOid": "0" * 40}], {7: ["docs/x.md"]})
        seen = []

        def runner(steps, cwd, log_dir):
            seen.append(steps)
            return tree_runner(steps, cwd, log_dir)
        got = b.run_engine("p0.parallel_pr", runner=runner)
        self.assertEqual(len(seen), 1)
        argv = seen[0][0]["argv"]
        self.assertEqual(argv[:2], [sys.executable, str(HELPER)])
        self.assertEqual(argv[2:4], ["--repo", "o/r"])
        self.assertTrue(got["ok"], got)
        self.assertEqual(got["runs"][0]["exit"], 0, got["runs"][0].get("tail"))
        m = b.record["materials"]["parallel_pr"]
        self.assertEqual(m["status"], "clean")
        self.assertEqual(b.record["process"]["parallel_pr"]["listed"], 1)
        self.assertNotIn("p0.parallel_pr", b.record["process"].get("checks", {}))

    def test_reply_fallback(self):
        """交差の在る印字を返す runner → reply の fallback で任せ先へ。表の fallback=role なら ready に残る"""
        b = self.pr_board()
        self.fake_gh([], {})
        materials0 = json.loads((b.dir / "record.json").read_text(encoding="utf-8"))["materials"]

        def crossing(steps, cwd, log_dir):
            log_dir.mkdir(parents=True, exist_ok=True)
            out, err = log_dir / "1.out", log_dir / "1.err"
            out.write_text(json.dumps({"repo": "o/r", "listed": 1, "truncated": False,
                                       "conflicts": [{"pr": "7", "files": ["src/a.py"]}]}), encoding="utf-8")
            err.write_text("", encoding="utf-8")
            return [{"name": steps[0]["name"], "argv": steps[0]["argv"], "out": str(out), "err": str(err),
                     "exit": 0, "wall_s": 0.1, "tail": ""}]
        got = b.run_engine("p0.parallel_pr", runner=crossing)
        self.assertFalse(got["ok"])
        self.assertIn("並行 PR と 1 件交差した", got["fallback"])
        inst = b.rd["instances"]["p0.parallel_pr"]
        self.assertEqual((inst["status"], inst["engine_fallback"]), ("pending", got["fallback"]))
        self.assertEqual(TABLE.nodes["p0.parallel_pr"].fallback, "role")
        self.assertEqual(b.record["materials"], materials0)   # 素材は任せ先が返すまで書かない
        self.assertIn("p0.parallel_pr", b._progress([])["ready"])

    def test_parallel_pr_table_both_ways(self):
        """試験用の表で p0.parallel_pr を absent にすると skipped に表の理由。engine_run（fallback=role）にすると、
        写しの helper が偽の gh で交差を見つけて任せ先へ落ち、settle の後も ready に残る（役は作らない）"""
        reason = "並行 PR の検査はこのラインに無い（検査用）"
        absent = with_by(TABLE, "p0.parallel_pr", by="absent", reason=reason)

        def unemitted(mem):
            mem["state"]["rounds"][-1]["instances"].pop("p0.parallel_pr")
        b = self.board_before(first_step("test_converges", "p0.parallel_pr"), table=absent, edit=unemitted)
        b.settle()
        self.assertEqual(b.rd["skipped"]["p0.parallel_pr"], reason)
        self.assertNotIn("p0.parallel_pr", b.rd["instances"])

        b = self.pr_board(table=with_by(TABLE, "p0.parallel_pr", by="engine_run", fallback="role"))
        self.fake_gh([{"number": 7, "headRefName": "other", "headRefOid": "0" * 40}], {7: ["src/a.py", "README.md"]})
        got = b.run_engine("p0.parallel_pr")
        self.assertIn("並行 PR と 1 件交差した", got["fallback"])
        self.assertEqual(got["runs"][0]["exit"], 0)
        p = b.settle()
        self.assertIn("p0.parallel_pr", p["ready"])
        self.assertEqual(b.rd["instances"]["p0.parallel_pr"]["status"], "pending")


class TreeRunnerCase(StepCase):
    def test_tree_runner_shape(self):
        """tree_runner の行の鍵 == engine の run_steps の行の鍵（起こせない argv では exit None と error）。機械の試験の枠は
        取らせない（枠を取った段は wait_s と枠の文が付き、機械の空き具合で行が変わる）"""
        steps = [{"name": "ok", "argv": [sys.executable, "-c", "import sys; print('out'); print('err', file=sys.stderr)"]},
                 {"name": "red", "argv": [sys.executable, "-c", "import sys; sys.exit(4)"]},
                 {"name": "gone", "argv": [str(self.tmp / "no-such-command")]}]
        with mock.patch.dict(os.environ, {"WORKS_TESTSLOT": ""}):
            mine = tree_runner(steps, self.tmp, self.tmp / "mine")
        theirs = engine_run_steps(steps, self.tmp, self.tmp / "theirs")
        self.assertEqual([list(r) for r in mine], [list(r) for r in theirs])
        for a, b in zip(mine, theirs):
            self.assertEqual({k: a[k] for k in ("name", "argv", "exit")}, {k: b[k] for k in ("name", "argv", "exit")})
            self.assertEqual(pathlib.Path(a["out"]).read_bytes(), pathlib.Path(b["out"]).read_bytes())
        self.assertEqual(mine[0]["tail"], theirs[0]["tail"])
        self.assertEqual((mine[0]["exit"], mine[1]["exit"], mine[2]["exit"]), (0, 4, None))
        self.assertIn("no-such-command", mine[2]["error"])
        self.assertEqual(pathlib.Path(mine[0]["out"]), self.tmp / "mine" / "1.out")

    def test_tree_runner_strips_uv_env(self):
        """VIRTUAL_ENV（uv が起こした環境）・UV_RUN_RECURSION_DEPTH が子に渡らない（台帳 R23 と同じ）"""
        env = {"VIRTUAL_ENV": sys.prefix, "UV_RUN_RECURSION_DEPTH": "1", "UV_NO_CONFIG": "1"}
        show = [sys.executable, "-c", "import os, json; print(json.dumps({k: os.environ.get(k) for k in "
                "('VIRTUAL_ENV', 'UV_RUN_RECURSION_DEPTH', 'UV_NO_CONFIG', 'PYTHONDONTWRITEBYTECODE')}))"]
        with mock.patch.dict(os.environ, env):
            rows = tree_runner([{"name": "env", "argv": show}], self.tmp, self.tmp / "logs")
        self.assertEqual(rows[0]["exit"], 0, rows[0]["tail"])
        seen = json.loads(pathlib.Path(rows[0]["out"]).read_text(encoding="utf-8"))
        self.assertEqual(seen, {"VIRTUAL_ENV": None, "UV_RUN_RECURSION_DEPTH": None, "UV_NO_CONFIG": None,
                                "PYTHONDONTWRITEBYTECODE": "1"})

    def reuse_env(self, run="run-a"):
        """結果の使い回しを使える環境（run の置き場だけ。包みの家は要らない）。枠の台本は使わない"""
        return {"ARTIFACTS_DIR": str(self.tmp / "arts" / run), "WORKS_TESTSLOT": ""}

    def test_reused_step_row_has_mainline_shape(self):
        """同じ run の中で、同じ木の同じ段を 2 度走らせる。2 度目は子を起こさず、行の reused が本流の行と同じ形
        {at, took_s, key, entry, from}（from は run の名）で、段の junit は書き戻されている。行の鍵は使い回さない回の鍵に reused を足すだけ"""
        tree = self.tmp / "tree"
        tree.mkdir()
        (tree / ".gitignore").write_text("report.xml\n", encoding="utf-8")
        gitkit.git(tree, "init", "-q")
        gitkit.git(tree, "add", "-A")
        gitkit.git(tree, "commit", "-q", "-m", "seed")
        count = self.tmp / "count"
        step = {"name": "suite", "junit": "report.xml",
                "argv": [sys.executable, "-c", f"open({str(count)!r}, 'a').write('1'); open('report.xml', 'w').write('<r/>')"]}
        with mock.patch.dict(os.environ, self.reuse_env()):
            os.environ.pop("GRAPHLOOPS_RERUN_CHECKS", None)
            first = tree_runner([step], tree, self.tmp / "logs1")
            (tree / "report.xml").unlink()
            second = tree_runner([step], tree, self.tmp / "logs2")
        self.assertEqual(count.read_text(encoding="utf-8"), "1")
        self.assertNotIn("reused", first[0])
        self.assertEqual(second[0]["exit"], 0)
        self.assertEqual(set(second[0]) - set(first[0]), {"reused"})
        self.assertEqual(set(second[0]["reused"]), {"at", "took_s", "key", "entry", "from"})
        self.assertEqual(second[0]["reused"]["from"], "run-a")
        self.assertEqual((tree / "report.xml").read_text(encoding="utf-8"), "<r/>")
        self.assertTrue(pathlib.Path(second[0]["out"]).is_file())

    def git_tree(self, ignore="", files=None):
        """git の木を作って commit する（.gitignore と files）。返りは木のパス"""
        tree = self.tmp / "tree"
        tree.mkdir()
        (tree / ".gitignore").write_text(ignore, encoding="utf-8")
        for name, text in (files or {}).items():
            (tree / name).write_text(text, encoding="utf-8")
        gitkit.git(tree, "init", "-q")
        gitkit.git(tree, "add", "-A")
        gitkit.git(tree, "commit", "-q", "-m", "seed")
        return tree

    def counting_step(self, name, code=0, body=""):
        """走るたびに自分の数えのファイルへ 1 行足す段（終了コード code）。argv に段の印 MARK-<name> を持つ"""
        count = self.tmp / f"count-{name}"
        script = f"'MARK-{name}'; open({str(count)!r}, 'a').write('1\\n'); {body + '; ' if body else ''}import sys; sys.exit({code})"
        return {"name": name, "argv": [sys.executable, "-c", script]}

    def times(self, name):
        count = self.tmp / f"count-{name}"
        return len(count.read_text(encoding="utf-8").split()) if count.exists() else 0

    def test_earlier_step_side_effect_is_not_reused_alone(self):
        """.gitignore の下の dist/ に書く build の段と、dist を読んで src が good でなければ exit 1 の test の段を、同じ run の中で
        src=bad→good→bad と 3 度通すと、3 度目の test の段は赤。build の段だけを 1 度目の控えから使うと dist が書かれず、
        good の dist が残ったまま test の段が緑になる（前の段の副作用を飛ばして後の段が走る）"""
        tree = self.git_tree(ignore="dist/\n", files={"src.txt": "seed"})
        build = {"name": "build", "argv": [sys.executable, "-c",
                                           "import os, shutil; os.makedirs('dist', exist_ok=True); shutil.copy('src.txt', 'dist/out.txt')"]}
        check = {"name": "test", "argv": [sys.executable, "-c",
                                          "import sys; sys.exit(0 if open('dist/out.txt').read() == 'good' else 1)"]}
        seen = []
        with mock.patch.dict(os.environ, self.reuse_env()):
            os.environ.pop("GRAPHLOOPS_RERUN_CHECKS", None)
            for i, text in enumerate(("bad", "good", "bad")):
                (tree / "src.txt").write_text(text, encoding="utf-8")
                gitkit.git(tree, "add", "-A")
                gitkit.git(tree, "commit", "-q", "-m", f"src {text} {i}")
                rows = tree_runner([build, check], tree, self.tmp / f"logs{i}")
                seen.append([(r["name"], r["exit"]) for r in rows])
        self.assertEqual(seen, [[("build", 0), ("test", 1)], [("build", 0), ("test", 0)], [("build", 0), ("test", 1)]])

    def test_row_carries_reuse_off(self):
        """使い回しの置き場が在る run で、1 度目（一式が控えに無い回）の行には控えに無い段の名と鍵の頭が載り、
        終了コード 1 の段の行には赤を控えない理由が載る"""
        tree = self.git_tree()
        lint, suite = self.counting_step("lint"), self.counting_step("suite", code=1)
        with mock.patch.dict(os.environ, self.reuse_env()):
            os.environ.pop("GRAPHLOOPS_RERUN_CHECKS", None)
            rows = tree_runner([lint, suite], tree, self.tmp / "logs")
        self.assertEqual([r["exit"] for r in rows], [0, 1])
        for r in rows:
            self.assertIn("reuse_off", r, r["name"])
        self.assertIn("lint", rows[0]["reuse_off"])
        self.assertRegex(rows[0]["reuse_off"], "同じ指紋の控えが無い（鍵 [0-9a-f]{12}）")
        self.assertIn("終了コード 1", rows[1]["reuse_off"])

    def test_rerun_flag_reason_reaches_rows(self):
        """1 度走らせて一式を控えた後、GRAPHLOOPS_RERUN_CHECKS を立てて同じ一式を通すと、全段が走り、各行の reuse_off が
        旗の名を名指す（控えに無い、とは言わない）"""
        tree = self.git_tree()
        steps = [self.counting_step("lint"), self.counting_step("suite")]
        with mock.patch.dict(os.environ, self.reuse_env()):
            os.environ.pop("GRAPHLOOPS_RERUN_CHECKS", None)
            tree_runner(steps, tree, self.tmp / "logs1")
            with mock.patch.dict(os.environ, {"GRAPHLOOPS_RERUN_CHECKS": "1"}):
                rows = tree_runner(steps, tree, self.tmp / "logs2")
        self.assertEqual((self.times("lint"), self.times("suite")), (2, 2))
        for r in rows:
            self.assertNotIn("reused", r)
            self.assertIn("reuse_off", r, r["name"])
            self.assertIn("GRAPHLOOPS_RERUN_CHECKS", r["reuse_off"])
            self.assertNotIn("控えが無い", r["reuse_off"])

    def test_broken_group_entry_reason_reaches_rows(self):
        """一式を控えた後、2 段目の控えの JSON の out を壊れた base64 に書き換えて同じ一式を通すと、全段が走り、
        行の reuse_off がその控えの壊れを名指す"""
        tree = self.git_tree()
        steps = [self.counting_step("lint"), self.counting_step("suite")]
        with mock.patch.dict(os.environ, self.reuse_env()):
            os.environ.pop("GRAPHLOOPS_RERUN_CHECKS", None)
            tree_runner(steps, tree, self.tmp / "logs1")
            hurt = []
            for path in self.tmp.rglob("*.json"):
                try:
                    doc = json.loads(path.read_text(encoding="utf-8"))
                except ValueError:
                    continue
                if isinstance(doc, dict) and doc.get("schema") == tree_run.REUSE_SCHEMA and "MARK-suite" in json.dumps(doc["material"]):
                    doc["out"] = "!!broken!!"
                    path.write_text(json.dumps(doc), encoding="utf-8")
                    hurt.append(path)
            self.assertEqual(len(hurt), 1, hurt)
            rows = tree_runner(steps, tree, self.tmp / "logs2")
        self.assertEqual((self.times("lint"), self.times("suite")), (2, 2))
        for r in rows:
            self.assertNotIn("reused", r)
            self.assertIn("reuse_off", r, r["name"])
            self.assertIn("base64", r["reuse_off"])

    def test_single_command_entries_do_not_complete_group(self):
        """一式の 2 段と同じ argv・環境・木を slotted_run で 1 つずつ（一式の外で）緑で走らせて控えても、
        その後の tree_runner は使い回さずに全段を走らせる"""
        tree = self.git_tree()
        steps = [self.counting_step("lint"), self.counting_step("suite")]
        with mock.patch.dict(os.environ, self.reuse_env()):
            os.environ.pop("GRAPHLOOPS_RERUN_CHECKS", None)
            env = tree_run.outside_env(os.environ)
            for i, s in enumerate(steps):
                with open(self.tmp / f"alone{i}.out", "wb") as out, open(self.tmp / f"alone{i}.err", "wb") as err:
                    rc, _ = tree_run.slotted_run(list(s["argv"]), env, outputs=(), note={}, stdin=subprocess.DEVNULL,
                                                 stdout=out, stderr=err, cwd=str(tree))
                self.assertEqual(rc, 0)
            self.assertEqual((self.times("lint"), self.times("suite")), (1, 1))
            rows = tree_runner(steps, tree, self.tmp / "logs")
        self.assertEqual((self.times("lint"), self.times("suite")), (2, 2))
        for r in rows:
            self.assertNotIn("reused", r)

    def test_partial_red_group_is_not_kept(self):
        """1 段目が赤・2 段目が緑の一式を通した後、同じ木で同じ一式を通すと 2 段目も走る（赤の混じった一式は置かれない）"""
        tree = self.git_tree()
        steps = [self.counting_step("lint", code=1), self.counting_step("suite")]
        with mock.patch.dict(os.environ, self.reuse_env()):
            os.environ.pop("GRAPHLOOPS_RERUN_CHECKS", None)
            tree_runner(steps, tree, self.tmp / "logs1")
            rows = tree_runner(steps, tree, self.tmp / "logs2")
        self.assertEqual((self.times("lint"), self.times("suite")), (2, 2))
        self.assertEqual([r["exit"] for r in rows], [1, 0])
        for r in rows:
            self.assertNotIn("reused", r)
            self.assertIn("一式を控えない: 終了コード 1", r["reuse_off"])


if __name__ == "__main__":
    unittest.main()
