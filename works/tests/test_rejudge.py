"""同じ周の再審の芯（.shared/core/rejudge.py）の検査。rejudge 設計の 23a（段 1＝写しの graphloops 0.21.0 の規則）。

- 形: 写しの規則の形（shape）・再審の節の並び（passes。数も名も写しから引く）・役の output_format の印
- 回す: route が盤面の ready だけで次の役を決める。判定役の会話を確かめられなければ役を起こす前に盤面を止める
- 描く・印: render は engine の描き方（node_prompt → ctx → pointers.snapshot → Renderer）。prep は起こした印を 1 度だけ置く
- 受け付け: take は写しの規則（schema → rejudge_output → writes → check_record）だけで受け、拒否は ok: False で盤面を書かない
- 単位の差分: 異議に名指されていない単位の変化・ラベルを下げた単位を記録する（柵は足さない）
- 出口: collect は回した後も再審の節が ready なら盤面を止める
- 費用: 継いだ起動の表示から判定役の会話の累積を引く
盤面は手本 test_rejudge_path から 1 本目のラインの本物の表で作り、rejudge は本物の entry.open_board で開く（tests/rejudgekit.py）。期待は写しの形ごとに EXPECT に置く——写し直しで形が
変われば test_shape_known が落ち、ここを書き換える所が目に入る。
"""
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import types
import unittest
from unittest import mock

sys.dont_write_bytecode = True
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import rejudgekit as kit  # noqa: E402
from rejudgekit import UNIT_A, UNIT_B, load  # noqa: E402

import rejudge  # noqa: E402
from accept import role_schema, snapshot_tree  # noqa: E402
from board import BoardGap, graph_expanded, rules_module  # noqa: E402
from engine import pointers  # noqa: E402
from engine.render import Renderer  # noqa: E402
from engine.util import dump, safe_name  # noqa: E402

GRAPH = graph_expanded()
EXPECT = {
    "0.21.0": {
        "passes": [{"node": "p2.rejudge", "role": "rejudge", "cont": "judge", "source": "p3.fix"},
                   {"node": "p2.rejudge_third", "role": "rejudge-third", "cont": None, "source": "p3.fix"}],
        "third_na": "cond rejudge_exhausted",
    },
}
BOARDS = None


def setUpModule():
    global BOARDS
    BOARDS = kit.Boards()


def tearDownModule():
    BOARDS.cleanup()


class _Case(unittest.TestCase):
    def setUp(self):
        self._home = tempfile.TemporaryDirectory()
        self.addCleanup(self._home.cleanup)
        env = mock.patch.dict(os.environ, {rejudge.ADAPTER_HOME_ENV: self._home.name})
        env.start()
        self.addCleanup(env.stop)

    def board(self, kind="objection", session=True):
        self.bd, self.repo = BOARDS.fresh(kind)
        if session:
            self.sid = kit.put_session(self.repo)
        return self.bd, self.repo

    def work(self, name):
        return self.bd / f"r{kit.state(self.bd)['round']}" / name

    def run_pass(self, reply, role="rejudge"):
        """route → snap → prep → take を 1 回。返りは take の返り"""
        got = rejudge.route(self.bd, self.repo)
        self.assertEqual(got["next"], role, got)
        rejudge.snap(self.bd, self.repo)
        rejudge.prep(self.bd, role, self.repo)
        return rejudge.take(self.bd, rejudge.node_of(role), reply, self.repo)


class ShapeCase(_Case):
    def test_shape_known(self):
        self.assertIn(rejudge.shape(), EXPECT, "写しの規則の形が知らない物——写し直した？ EXPECT と 23d の段を足す")

    def test_passes_from_copied_rules(self):
        self.assertEqual(rejudge.passes(), EXPECT[rejudge.shape()]["passes"])
        src = (kit.CORE / "rejudge.py").read_text(encoding="utf-8")
        for word in ('"p3.fix"', "REJUDGE_MAX =", '"p2.diagnose"', "rejudge_open"):
            self.assertNotIn(word, src, f"{word} は写しから引く（rejudge.py に書かない）")

    def test_passes_3_6_shape_from_table(self):
        """3-6 の形の規則（REJUDGE_PASSES・REJUDGE_THIRD）からも、表の順に 6 つ並ぶ（写し直しの前に形だけ見る）"""
        rules = types.SimpleNamespace(REJUDGE_PASSES={1: ("p3.fix", "p2.rejudge"), 2: ("p3.rejudge_reply", "p2.rejudge2"),
                                                      3: ("p3.rejudge_reply2", "p2.rejudge3")},
                                      REJUDGE_THIRD="p2.rejudge_third")
        judge = {"same_context_as": "p2.diagnose"}
        graph = {"nodes": {"p2.rejudge": judge, "p3.rejudge_reply": {}, "p2.rejudge2": judge, "p3.rejudge_reply2": {},
                           "p2.rejudge3": judge, "p2.rejudge_third": {"fresh_context": True}}}
        self.assertEqual(rejudge.shape(rules), "3-6")
        got = rejudge.passes(rules, graph)
        self.assertEqual([(p["node"], p["role"], p["cont"], p["source"]) for p in got],
                         [("p2.rejudge", "rejudge", "judge", "p3.fix"),
                          ("p3.rejudge_reply", "rejudge-reply", None, "p2.rejudge"),
                          ("p2.rejudge2", "rejudge2", "judge", "p3.rejudge_reply"),
                          ("p3.rejudge_reply2", "rejudge-reply2", None, "p2.rejudge2"),
                          ("p2.rejudge3", "rejudge3", "judge", "p3.rejudge_reply2"),
                          ("p2.rejudge_third", "rejudge-third", None, "p2.rejudge3")])

    def test_shape_unknown_is_gap(self):
        with self.assertRaises(BoardGap):
            rejudge.shape(types.SimpleNamespace())

    def test_role_of_covers_copy(self):
        g = json.loads(json.dumps(GRAPH))
        g["nodes"]["p2.rejudge_fourth"] = dict(g["nodes"]["p2.rejudge_third"])
        with self.assertRaises(BoardGap) as cm:
            rejudge.passes(graph=g)
        self.assertIn("p2.rejudge_fourth", str(cm.exception))

    def test_output_formats_marked(self):
        for p in rejudge.passes():
            with self.subTest(p["node"]):
                of = rejudge.output_format(p["node"])
                self.assertEqual(rejudge.strip_mark(of), role_schema(p["node"]))
                want = f"works-node: {p['role']}" + (f" continue={p['cont']}" if p["cont"] else "")
                self.assertEqual(of["description"], want)
        self.assertEqual(rejudge.output_format("p2.rejudge")["description"], "works-node: rejudge continue=judge")
        self.assertEqual(rejudge.output_format("p2.rejudge_third")["description"], "works-node: rejudge-third")

    def test_prompt_copies_verbatim(self):
        """描画に使う指示書の写し（gl-prompts）は、COPIED_FROM の 1 行目の commit の graphloops/ の下とバイト単位で同じ"""
        base = kit.CORE / "gl-prompts"
        lines = (base / "COPIED_FROM").read_text(encoding="utf-8").splitlines()
        commit = lines[0].split()[0]
        listed = [ln.split()[0] for ln in lines[1:] if ln.strip() and not ln.startswith("#")]
        self.assertEqual(sorted(listed), sorted(str(p.relative_to(base)) for p in base.rglob("*.md")))
        core = (kit.CORE / "COPIED_FROM").read_text(encoding="utf-8").splitlines()[0].split()[0]
        self.assertEqual(commit, core, "gl-prompts は写し（graphloops/）と同じ commit から写す——写し直しで一緒に写し直す")
        # 引けなければ落とす（test_core_copy の写しのバイト一致と同じく、飛ばさない）
        for rel in listed:
            with self.subTest(rel):
                src = subprocess.run(["git", "-C", str(kit.CORE), "show", f"{commit}:graphloops/{rel}"],
                                     capture_output=True, check=True).stdout
                self.assertEqual((base / rel).read_bytes(), src)


class RouteCase(_Case):
    def test_objection_makes_rejudge_ready(self):
        self.board("objection")
        got = rejudge.route(self.bd, self.repo)
        self.assertEqual((got["next"], got["stopped"]), ("rejudge", False), got)
        st = kit.state(self.bd)
        self.assertIn("p2.rejudge", st["rounds"][-1]["instances"])
        self.assertTrue(st["loop"]["rejudge_requested"]["text"].startswith("判定の単位"))

    def test_third_eye_na_in_021(self):
        self.board("objection")
        rejudge.route(self.bd, self.repo)
        na = kit.state(self.bd)["rounds"][-1]["na"]
        self.assertTrue(na["p2.rejudge_third"].startswith(EXPECT[rejudge.shape()]["third_na"]), na)

    def test_no_objection_no_rejudge(self):
        self.board("none")
        got = rejudge.route(self.bd, self.repo)
        self.assertEqual((got["next"], got["stopped"]), ("", False), got)
        na = kit.state(self.bd)["rounds"][-1]["na"]
        self.assertIn("p2.rejudge", na)
        self.assertIn("p2.rejudge_third", na)
        self.assertIn("p2.rejudge", got["why"])

    def _assert_stopped(self, got, why_part):
        self.assertEqual((got["next"], got["stopped"]), ("", True), got)
        self.assertIn(why_part, got["why"])
        st = kit.state(self.bd)
        self.assertEqual(st["stop"]["by"], rejudge.STOP_BY_SESSION)
        self.assertIn("判定役の会話", st["stop"]["reason"])
        inst = st["rounds"][-1]["instances"]["p2.rejudge"]
        self.assertNotIn("launched_at", inst)
        self.assertEqual(inst["status"], "stopped")
        self.assertFalse(self.work(rejudge.SESSION_NAME).exists())

    def test_session_missing_stops(self):
        self.board("objection", session=False)
        self._assert_stopped(rejudge.route(self.bd, self.repo), "judge.id")

    def test_session_not_uuid_stops(self):
        self.board("objection", session=False)
        kit.put_session(self.repo, sid="not-a-uuid")
        self._assert_stopped(rejudge.route(self.bd, self.repo), "UUID")

    def test_session_stale_stops(self):
        import datetime
        self.board("objection", session=False)
        kit.put_session(self.repo, at=datetime.datetime(2026, 9, 1, 0, 0))
        self._assert_stopped(rejudge.route(self.bd, self.repo), "盤面を作る前")

    def test_session_mismatch_stops(self):
        self.board("objection", session=False)
        kit.put_session(self.repo, row_id="00000000-0000-4000-8000-000000000001")
        self._assert_stopped(rejudge.route(self.bd, self.repo), "起動の記録")

    def test_session_no_launch_row_stops(self):
        self.board("objection", session=False)
        kit.put_session(self.repo, node="fix")
        self._assert_stopped(rejudge.route(self.bd, self.repo), "起動の記録")

    def test_session_ok_goes(self):
        self.board("objection")
        got = rejudge.route(self.bd, self.repo)
        self.assertEqual(got["next"], "rejudge")
        doc = json.loads(self.work(rejudge.SESSION_NAME).read_text(encoding="utf-8"))
        self.assertEqual(doc["id"], self.sid)
        self.assertEqual(doc["path"], str(rejudge.adapter_module().session_path(self.repo, "judge")))
        self.assertTrue(doc["launch_at"])

    def test_session_checked_every_route(self):
        """確かめは毎回（1 回目で通っても、id が途中で消えれば次の route が止める）"""
        self.board("objection")
        self.assertEqual(rejudge.route(self.bd, self.repo)["next"], "rejudge")
        rejudge.adapter_module().session_path(self.repo, "judge").unlink()
        self.assertTrue(rejudge.route(self.bd, self.repo)["stopped"])

    def test_stopped_board_routes_nothing(self):
        self.board("objection", session=False)
        rejudge.route(self.bd, self.repo)
        got = rejudge.route(self.bd, self.repo)
        self.assertEqual((got["next"], got["stopped"]), ("", True), got)

    def test_third_is_absent_in_the_line(self):
        """規則が第三の目を出した盤面（往復を今の周の 3 にした盤面）でも、ラインの表で p2.rejudge_third は absent なので盤面が
        省き、rejudge-third を回さない（段はブロックに無い。2026-10-09 の整理）。止めもしない"""
        self.board("exhausted", session=False)
        got = rejudge.route(self.bd, self.repo)
        self.assertEqual((got["next"], got["stopped"]), ("", False), got)
        self.assertNotIn("stop", kit.state(self.bd))
        import entry
        self.assertEqual(entry.open_board(pathlib.Path(self.bd)).node_state("p2.rejudge_third"), "skipped")


class RenderPrepCase(_Case):
    def test_render_matches_engine(self):
        self.board("objection")
        rejudge.route(self.bd, self.repo)
        b = rejudge.open_board(self.bd, repo=self.repo)
        path = rejudge.render(b, "p2.rejudge")
        n = b.nodes["p2.rejudge"]
        ctx = b.ctx()
        ctx["node"] = {"skills": []}
        snap, offsets = pointers.snapshot(ctx, n.get("pointers"))
        # 指示書の本文は試験の側で組む（写しの graph の prompt_file・prompt_append を gl-prompts の置き場で引いて改行でつなぐ。
        # engine の node_prompt と同じつなぎ方。rejudge の置き場の選び方は通さない）
        parts = [n["prompt_file"], *(n.get("prompt_append") or [])]
        self.assertTrue(all(p.startswith("../prompts/") for p in parts), parts)
        tpl = "\n".join((kit.CORE / "gl-prompts" / "prompts" / p.removeprefix("../prompts/")).read_text(encoding="utf-8")
                        for p in parts)
        want = Renderer(ctx, n.get("reads"), ref=b.ref, cap=None, numbered=offsets).render(tpl)
        want += ("\n\n---\n返答はこの JSON Schema に合う JSON だけ（前後に文を付けない）。"
                 '文字列値の中の " は必ず \\" にエスケープしろ——生のまま入れると返答まるごとが'
                 "読めずに捨てられる:\n" + dump(n["schema"]))
        got = path.read_text(encoding="utf-8")
        self.assertEqual(got, want)
        self.assertEqual(path, self.bd / "prompts" / f"r{b.round}" / (safe_name("p2.rejudge") + ".md"))
        self.assertIn("## 人の方針", got)              # policy-paste.md
        self.assertIn("方針が在るなら", got)            # policy.md
        self.assertIn("判定の単位 src/a.py:f", got)     # 異議の文（loop.rejudge_requested）
        self.assertIn(UNIT_B, got)

    def test_render_no_numbers_without_pointers(self):
        self.board("objection")
        rejudge.route(self.bd, self.repo)
        b = rejudge.open_board(self.bd, repo=self.repo)
        self.assertFalse(b.nodes["p2.rejudge"].get("pointers"))
        got = rejudge.render(b, "p2.rejudge").read_text(encoding="utf-8")
        self.assertNotIn('"no"', got.split("\n---\n")[0])
        self.assertNotIn("pointers", kit.state(self.bd)["rounds"][-1]["instances"]["p2.rejudge"])

    def test_render_gap_on_unreadable_hole(self):
        self.board("objection")
        rejudge.route(self.bd, self.repo)
        b = rejudge.open_board(self.bd, repo=self.repo)
        b.nodes["p2.rejudge"]["reads"] = ["record.units"]   # 穴 loop.rejudge_requested が reads に無い
        with self.assertRaises(BoardGap):
            rejudge.render(b, "p2.rejudge")

    def test_prep_marks_once(self):
        self.board("objection")
        rejudge.route(self.bd, self.repo)
        first = rejudge.prep(self.bd, "rejudge", self.repo)
        at = kit.state(self.bd)["rounds"][-1]["instances"]["p2.rejudge"]["launched_at"]
        before = self.work("rejudge-units-before-rejudge.json").read_bytes()
        second = rejudge.prep(self.bd, "rejudge", self.repo)
        self.assertEqual((first["attempt"], second["attempt"]), (1, 1))
        self.assertEqual((first["already"], second["already"]), (False, True))
        self.assertEqual(kit.state(self.bd)["rounds"][-1]["instances"]["p2.rejudge"]["launched_at"], at)
        self.assertEqual(self.work("rejudge-units-before-rejudge.json").read_bytes(), before)
        self.assertTrue(pathlib.Path(first["prompt_file"]).is_file())
        self.assertTrue(first["out_path"].endswith("p2.rejudge.json"))
        doc = json.loads(before)
        self.assertEqual([u["key"] for u in doc["units"]], [UNIT_A, UNIT_B])
        self.assertTrue(doc["objection"].startswith("判定の単位"))
        self.assertEqual(doc["numbered_keys"], [UNIT_A, UNIT_B])

    def test_prep_puts_last_rejection_in_prompt_file(self):
        """拒否の文は $LOOP_PREV で指示に貼らず（裁定 R44）、次の prep が描いた指示書の頭に置く。文の中の $<節>.output.<欄> も
        そのまま（役は Read で読むので Archon は置き換えない）。1 回目の指示書には無い"""
        self.board("objection")
        rejudge.route(self.bd, self.repo)
        first = pathlib.Path(rejudge.prep(self.bd, "rejudge", self.repo)["prompt_file"]).read_text(encoding="utf-8")
        self.assertNotIn(rejudge.REJECT_HEADING, first)
        rejudge.refuse(self.bd, "p2.rejudge", "返答が JSON として読めない（頭: '$rj-route1.output.next と $LOOP_PREV.x'）")
        got = pathlib.Path(rejudge.prep(self.bd, "rejudge", self.repo)["prompt_file"]).read_text(encoding="utf-8")
        self.assertTrue(got.startswith(rejudge.REJECT_HEADING), got[:200])
        self.assertIn("$rj-route1.output.next と $LOOP_PREV.x", got)
        self.assertTrue(got.endswith(first), "拒否の節の後ろは描き直した指示書そのまま（拒否の節を積み重ねない）")

    def test_prep_ends_with_the_lang_line(self):
        """再審・第三の目の文（異議への答えの reason）は関所と報告に載るので、prep は engine と同じ本文の末尾に盤面の inputs.lang の
        1 行を足す（出し直しでも 1 つだけ）"""
        self.board("objection")
        rejudge.route(self.bd, self.repo)
        b = rejudge.open_board(self.bd, repo=self.repo)
        line = rejudge.rolekit.lang_line(b.state.get("inputs"))
        for _ in range(2):
            got = pathlib.Path(rejudge.prep(self.bd, "rejudge", self.repo)["prompt_file"]).read_text(encoding="utf-8")
            self.assertTrue(got.endswith("\n\n" + line + "\n"), got[-300:])
            self.assertEqual(got.count(line), 1)

    def test_prep_marks_the_drawn_attempt(self):
        """prep は描いた instance の試行の番号で起こした印を置く（盤面は mark_launched(節, 試行) を求め、印の無い返答を受けない）"""
        self.board("objection")
        rejudge.route(self.bd, self.repo)
        got = rejudge.prep(self.bd, "rejudge", self.repo)
        inst = kit.state(self.bd)["rounds"][-1]["instances"]["p2.rejudge"]
        self.assertEqual(got["attempt"], inst["attempts"])
        self.assertEqual(got["out_path"], inst["out_path"])
        self.assertTrue(inst["launched_at"])

    def test_prep_without_pending_is_gap(self):
        self.board("none")
        rejudge.route(self.bd, self.repo)
        with self.assertRaises(BoardGap):
            rejudge.prep(self.bd, "rejudge", self.repo)


class TakeCase(_Case):
    def test_settled_drops_objection(self):
        self.board("objection")
        got = self.run_pass(load("rejudge_settled"))
        self.assertTrue(got["ok"], got)
        self.assertEqual(got["verdict"], "採る")
        st = kit.state(self.bd)
        self.assertNotIn("rejudge_requested", st["loop"])
        self.assertEqual(st["loop"]["rejudge_rounds"], {"round": 1, "n": 1})
        self.assertEqual(len(kit.record(self.bd)["process"]["rejudge"]), 1)
        b = rejudge.open_board(self.bd, repo=self.repo)
        self.assertEqual(rejudge.unsettled(b), {"text": "", "settled": True})
        self.assertEqual(rejudge.route(self.bd, self.repo)["next"], "")

    def test_partial_keeps_objection_021(self):
        self.board("objection")
        self.assertTrue(self.run_pass(load("rejudge_partial"))["ok"])
        st = kit.state(self.bd)
        self.assertIn("rejudge_requested", st["loop"])
        got = rejudge.route(self.bd, self.repo)
        self.assertEqual(got["next"], "", got)     # 0.21.0: 1 周に 1 回。第三の目は na のまま（穴）
        b = rejudge.open_board(self.bd, repo=self.repo)
        u = rejudge.unsettled(b)
        self.assertFalse(u["settled"])
        self.assertEqual(u["text"], load("fix2_rejudge_requested")["rejudge_requested"])

    def test_empty_facts_rejected(self):
        self.board("objection")
        rejudge.route(self.bd, self.repo)
        rejudge.snap(self.bd, self.repo)
        rejudge.prep(self.bd, "rejudge", self.repo)
        before = kit.board_files(self.bd)
        got = rejudge.take(self.bd, "p2.rejudge", load("rejudge_empty_facts"), self.repo)
        self.assertFalse(got["ok"])
        self.assertIn("new_facts", got["reason"])        # 写しの型（minLength 20）が空同然を拒む
        self.assertEqual(kit.board_files(self.bd), before)
        self.assertFalse(self.work(rejudge.DIFF_NAME).exists())
        rows = json.loads(self.work(rejudge.REJECTS_NAME).read_text(encoding="utf-8"))
        self.assertEqual([r["node"] for r in rows], ["p2.rejudge"])

    def test_give_up_on_third_rejection(self):
        """拒否の数がこの周のこの節で GIVE_UP_AFTER に達したら done（輪を抜ける印）。それまでは done が偽"""
        self.board("objection")
        rejudge.route(self.bd, self.repo)
        rejudge.snap(self.bd, self.repo)
        got = []
        for _ in range(rejudge.GIVE_UP_AFTER):
            rejudge.prep(self.bd, "rejudge", self.repo)
            r = rejudge.take(self.bd, "p2.rejudge", load("rejudge_empty_facts"), self.repo)
            got.append((r["ok"], r["done"], r["give_up"]))
        self.assertEqual(got, [(False, False, False)] * (rejudge.GIVE_UP_AFTER - 1) + [(False, True, True)])
        row = json.loads((pathlib.Path(self.bd) / "accept-last.json").read_text(encoding="utf-8"))["rejudge_p2_rejudge"]
        self.assertEqual((row["ok"], row["reason"]), (False, r["reason"]))   # 受け付けの最後の結果の控え（script_io.note_last）

    def test_type_rejected(self):
        self.board("objection")
        rejudge.route(self.bd, self.repo)
        rejudge.snap(self.bd, self.repo)
        rejudge.prep(self.bd, "rejudge", self.repo)
        got = rejudge.take(self.bd, "p2.rejudge", {"verdict": "採る"}, self.repo)
        self.assertFalse(got["ok"])
        self.assertIn("型に合わない", got["reason"])

    def test_reopened_defer_rejected(self):
        self.board("objection")
        kit.patch_state(self.bd, lambda st: st["loop"].__setitem__(
            "defer_ledger", {UNIT_B: {"reason": "構造の理由で先送り", "round": 1}}))
        rejudge.route(self.bd, self.repo)
        rejudge.snap(self.bd, self.repo)
        rejudge.prep(self.bd, "rejudge", self.repo)
        got = rejudge.take(self.bd, "p2.rejudge", load("rejudge_reopen_defer"), self.repo)
        self.assertFalse(got["ok"])
        self.assertIn("reopen_evidence が無い", got["reason"])

    def test_tree_changed_rejected(self):
        self.board("objection")
        rejudge.route(self.bd, self.repo)
        rejudge.snap(self.bd, self.repo)
        rejudge.prep(self.bd, "rejudge", self.repo)
        (self.repo / "src" / "a.py").write_text("x = 1\n", encoding="utf-8")
        before = kit.board_files(self.bd)
        got = rejudge.take(self.bd, "p2.rejudge", load("rejudge_settled"), self.repo)
        self.assertFalse(got["ok"])
        self.assertIn("作業ツリーを変えた", got["reason"])
        self.assertEqual(kit.board_files(self.bd), before)

    def test_snap_is_tree_state(self):
        # 役を起こす前の写しは共通の姿 tree_state（R47。HEAD・枝も持つ）
        import accept
        self.board("objection")
        rejudge.route(self.bd, self.repo)
        got = rejudge.snap(self.bd, self.repo)
        self.assertEqual(set(json.loads(pathlib.Path(got["snapshot_file"]).read_text(encoding="utf-8"))), set(accept.TREE_KEYS))

    def test_branch_switch_and_ignored_named(self):
        # 中身の同じ枝の切り替え（ref だけ変わる）も拒み、拒否の文は変わった欄（ref・git が無視するパス）を名指す（R47）
        self.board("objection")
        rejudge.route(self.bd, self.repo)
        rejudge.snap(self.bd, self.repo)
        rejudge.prep(self.bd, "rejudge", self.repo)
        git = ["git", "-C", str(self.repo), "-c", "core.hooksPath=/dev/null"]
        subprocess.run([*git, "switch", "-q", "-c", "役が切った枝"], check=True, capture_output=True)
        got = rejudge.take(self.bd, "p2.rejudge", load("rejudge_settled"), self.repo)
        self.assertFalse(got["ok"])
        self.assertIn("作業ツリーを変えた", got["reason"])
        self.assertIn("refs/heads/役が切った枝", got["reason"])
        subprocess.run([*git, "switch", "-q", "-"], check=True, capture_output=True)
        (self.repo / ".git" / "info").mkdir(exist_ok=True)
        with open(self.repo / ".git" / "info" / "exclude", "a", encoding="utf-8") as f:
            f.write("\n*.役の残り\n")
        (self.repo / "x.役の残り").write_text("役が書いた\n", encoding="utf-8")
        got = rejudge.take(self.bd, "p2.rejudge", load("rejudge_settled"), self.repo)
        self.assertFalse(got["ok"])
        self.assertIn("git が無視するパス: 増えた ['x.役の残り'] 消えた []", got["reason"])

    def test_take_without_snapshot_is_gap(self):
        self.board("objection")
        rejudge.route(self.bd, self.repo)
        rejudge.prep(self.bd, "rejudge", self.repo)
        with self.assertRaises(BoardGap):
            rejudge.take(self.bd, "p2.rejudge", load("rejudge_settled"), self.repo)

    def test_take_on_stopped_board_is_not_a_reply_error(self):
        self.board("objection")
        rejudge.route(self.bd, self.repo)
        rejudge.snap(self.bd, self.repo)
        rejudge.prep(self.bd, "rejudge", self.repo)
        b = rejudge.open_board(self.bd, repo=self.repo)
        b.stop("試験で止めた", by="test")
        from engine.util import Reject
        with self.assertRaises((Reject, BoardGap)):   # 回す側の誤り（スクリプトは終了コード 2）。ok: False にしない
            rejudge.take(self.bd, "p2.rejudge", load("rejudge_settled"), self.repo)

    def test_unnamed_change_recorded(self):
        self.board("objection")
        self.assertTrue(self.run_pass(load("rejudge_partial"))["ok"])
        rows = json.loads(self.work(rejudge.DIFF_NAME).read_text(encoding="utf-8"))
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual((row["pass"], row["node"], row["verdict"]), ("rejudge", "p2.rejudge", "一部採る"))
        self.assertEqual(row["unnamed_changed"], [UNIT_B])
        self.assertEqual(row["lowered"], [])
        named = {(c["key"], c["field"]): c["named"] for c in row["changed"]}
        self.assertEqual(named[(UNIT_B, "label")], False)
        self.assertEqual(named[(UNIT_A, "reason")], True)


class DiffCase(unittest.TestCase):
    BEFORE = [{"key": "k1", "label": "block"}, {"key": "k2", "label": "suggest", "disposition": "do-now"},
              {"key": "k3", "label": "info"}]

    def test_named_by_number(self):
        after = [{"key": "k1", "label": "block"}, {"key": "k2", "label": "nit"}, {"key": "k3", "label": "info"}]
        for text in ("#2 の判定を見直せ", "no 2 は誤り", "No.2 は誤り", "2 番の単位", "２番の単位"):
            with self.subTest(text):
                got = rejudge.diff_units(self.BEFORE, after, text, ["k1", "k2", "k3"])
                self.assertEqual(got["unnamed_changed"], [], got)
                self.assertTrue(all(c["named"] for c in got["changed"]))
        got = rejudge.diff_units(self.BEFORE, after, "#12 と #1 を見直せ", ["k1", "k2", "k3"])
        self.assertEqual(got["unnamed_changed"], ["k2"])

    def test_named_by_key(self):
        after = [{"key": "k1", "label": "block"}, {"key": "k2", "label": "nit"}, {"key": "k3", "label": "info"}]
        got = rejudge.diff_units(self.BEFORE, after, "k2 の判定がおかしい", [])
        self.assertEqual(got["unnamed_changed"], [])

    def test_no_names_all_unnamed(self):
        after = [{"key": "k1", "label": "suggest", "disposition": "do-now"}, {"key": "k2", "label": "nit"},
                 {"key": "k3", "label": "info", "reason": "足した"}]
        got = rejudge.diff_units(self.BEFORE, after, "判定がおかしい", ["k1", "k2", "k3"])
        self.assertEqual(got["unnamed_changed"], ["k1", "k2", "k3"])
        self.assertEqual(got["lowered"], ["k1"])

    def test_removed_and_lowered(self):
        after = [{"key": "k1", "label": "suggest", "disposition": "do-now"}, {"key": "k4", "label": "block"}]
        got = rejudge.diff_units(self.BEFORE, after, "k1 は block でない", [])
        kinds = {(c["key"], c["kind"]) for c in got["changed"]}
        self.assertIn(("k2", "removed"), kinds)
        self.assertIn(("k3", "removed"), kinds)
        self.assertIn(("k4", "added"), kinds)
        self.assertIn(("k1", "changed"), kinds)
        self.assertEqual(got["lowered"], ["k1"])
        self.assertEqual(got["unnamed_changed"], ["k2", "k3", "k4"])

    def test_fields_are_the_writes_pick(self):
        after = [dict(self.BEFORE[0], origin_analysis="書き足した"), self.BEFORE[1], self.BEFORE[2]]
        self.assertEqual(rejudge.diff_units(self.BEFORE, after, "", [])["changed"], [])
        self.assertEqual(rejudge.unit_fields(), ["key", "label", "disposition", "reason", "reopen_evidence"])


class CollectCase(_Case):
    def test_collect_settled(self):
        self.board("objection")
        self.assertTrue(self.run_pass(load("rejudge_settled"))["ok"])
        self.assertEqual(rejudge.route(self.bd, self.repo)["next"], "")
        got = rejudge.collect(self.bd)
        self.assertTrue(got["ok"], got)
        self.assertEqual((got["passes"], got["verdicts"]), (1, ["採る"]))
        self.assertEqual(got["unsettled"], {"text": "", "settled": True})
        self.assertEqual(got["diff_file"], str(self.work(rejudge.DIFF_NAME)))
        self.assertEqual(got["reads_file"], "")
        self.assertEqual(json.loads(self.work(rejudge.EXIT_NAME).read_text(encoding="utf-8")), got)

    def test_new_open_units(self):
        self.board("objection")
        reply = load("rejudge_settled")
        reply["units"].append({"key": "src/c.py:h — 上限の抜け道がもう 1 つ", "label": "block"})
        reply["units"].append({"key": "src/d.py:i — 読みにくい名前", "label": "nit"})
        self.assertTrue(self.run_pass(reply)["ok"])
        got = rejudge.collect(self.bd)
        self.assertEqual(got["new_open_units"], ["src/c.py:h — 上限の抜け道がもう 1 つ"])
        self.assertEqual(got["unnamed_changed"], ["src/c.py:h — 上限の抜け道がもう 1 つ", "src/d.py:i — 読みにくい名前"])

    def test_collect_stops_if_still_ready(self):
        self.board("objection")
        rejudge.route(self.bd, self.repo)
        got = rejudge.collect(self.bd)
        self.assertFalse(got["ok"])
        self.assertIn("p2.rejudge", got["reason"])
        st = kit.state(self.bd)
        self.assertEqual(st["stop"]["by"], rejudge.STOP_BY)

    def test_collect_names_last_rejection(self):
        self.board("objection")
        rejudge.route(self.bd, self.repo)
        rejudge.snap(self.bd, self.repo)
        for _ in range(3):
            rejudge.prep(self.bd, "rejudge", self.repo)
            self.assertFalse(rejudge.take(self.bd, "p2.rejudge", load("rejudge_empty_facts"), self.repo)["ok"])
        got = rejudge.collect(self.bd)
        self.assertFalse(got["ok"])
        self.assertIn("3 回", got["reason"])
        self.assertIn("$.new_facts", got["reason"])
        self.assertIn("$.new_facts", kit.state(self.bd)["stop"]["reason"])

    def test_collect_after_session_stop(self):
        self.board("objection", session=False)
        self.assertTrue(rejudge.route(self.bd, self.repo)["stopped"])
        got = rejudge.collect(self.bd)
        self.assertTrue(got["ok"], got)
        self.assertEqual(got["passes"], 0)
        self.assertEqual(kit.state(self.bd)["stop"]["by"], rejudge.STOP_BY_SESSION)
        self.assertFalse(got["unsettled"]["settled"])

    def test_collect_nothing_to_do(self):
        self.board("none")
        rejudge.route(self.bd, self.repo)
        got = rejudge.collect(self.bd)
        self.assertTrue(got["ok"], got)
        self.assertEqual((got["passes"], got["verdicts"], got["diff_file"]), (0, [], ""))

    def test_collect_exit_has_lowered_and_objection(self):
        """block から suggest に下げた単位は出口と rejudge-exit.json の lowered に、再審にかけた異議の文は objection に出る"""
        self.board("objection")
        reply = load("rejudge_settled")
        reply["units"][0] = {**reply["units"][0], "label": "suggest", "disposition": "do-now"}
        self.assertTrue(self.run_pass(reply)["ok"])
        got = rejudge.collect(self.bd)
        self.assertEqual(got["lowered"], [UNIT_A])
        self.assertIn(UNIT_A, got["objection"])
        self.assertEqual(json.loads(self.work(rejudge.EXIT_NAME).read_text(encoding="utf-8")), got)

    def test_collect_nothing_lowered(self):
        self.board("objection")
        self.assertTrue(self.run_pass(load("rejudge_settled"))["ok"])
        self.assertEqual(rejudge.collect(self.bd)["lowered"], [])


class SettledOutcomeCase(_Case):
    """決着した再審の結果（判定・再審が開いた単位・block から下げた単位）は、決着で loop.rejudge_requested が消えた後も、
    最後の関所の文・報告の冒頭 1・次の run の依頼の 3 か所に出る（読み手は rejudge-exit.json を名前で読む）"""
    NEW = "src/c.py:h — 上限の抜け道がもう 1 つ"

    def settled(self, verdict, *, new=(), lower=()):
        self.board("objection")
        reply = load("rejudge_settled")
        reply["verdict"] = verdict
        reply["units"] = [{**u, "label": "suggest", "disposition": "do-now"} if u["key"] in lower else u for u in reply["units"]]
        reply["units"] += [{"key": k, "label": "block"} for k in new]
        self.assertTrue(self.run_pass(reply)["ok"])
        self.assertTrue(rejudge.collect(self.bd)["ok"])
        b = rejudge.open_board(self.bd, repo=self.repo, allow_halted=True)
        self.assertEqual(rejudge.unsettled(b), {"text": "", "settled": True})
        return b

    def three(self, b):
        sys.path.insert(0, str(kit.CORE.parents[1] / "darkfactory" / "lib"))
        import line_edge
        import report
        head = "\n".join(report.head_decisions(b, {"accepted": True, "round_closed": True}))
        gate = line_edge.final_edge(b, self.repo, run_id="run-1", mode="always", tests=None)["gate_text"]
        return head, gate, report.next_request(b)

    def test_taken_shown_in_three_places(self):
        b = self.settled("採る", new=[self.NEW], lower=[UNIT_A])
        head, gate, items = self.three(b)
        for where, text in (("冒頭 1", head), ("最後の関所", gate)):
            with self.subTest(where):
                self.assertIn("再審の結果（r1・1 往復）: 採る", text)
                self.assertIn(self.NEW, text)
                self.assertIn(f"block から suggest に下げた（拒まずに見せる——人が確かめる）: {UNIT_A}", text)
                self.assertIn("異議: 判定の単位 src/a.py:f", text)
        wheres = [i["where"] for i in items]
        self.assertIn(self.NEW, wheres, items)
        self.assertIn(UNIT_A, wheres, items)
        self.assertTrue(any(i["where"] == "判定（再審の結果）" and "採る" in i["text"] for i in items), items)

    def test_settled_units_not_doubled_with_validator_rows(self):
        """再審が開いた・下げた単位は、検証器の単位の行（[block] 未解消・[suggest] do-now 未対応）を次の run に二重に渡さない"""
        import report
        b = self.settled("採る", new=[self.NEW], lower=[UNIT_A])
        left = [{"where": report.VALIDATOR_WHERE, "text": f"[block] 未解消: {self.NEW}"},
                {"where": report.VALIDATOR_WHERE, "text": f"[suggest] do-now 未対応: {UNIT_A}"},
                {"where": report.VALIDATOR_WHERE, "text": "[block] 未解消: ほかの単位"}]
        items = report.next_request(b, left=left)
        for k in (self.NEW, UNIT_A):   # 異議の文が key を含む判定の行は数えない
            self.assertEqual(sum(k in i["text"] for i in items if i["where"] != report.REJUDGE_WHERE), 1, items)
        self.assertIn(left[2], items)

    def test_rejected_shown_without_unit_rows(self):
        b = self.settled("退ける")
        head, gate, items = self.three(b)
        for text in (head, gate):
            self.assertIn("再審の結果（r1・1 往復）: 退ける", text)
            self.assertNotIn("直す単位にした", text)
        self.assertEqual([i["where"] for i in items], ["判定（再審の結果）"], items)

    def test_no_rejudge_says_none(self):
        self.board("none")
        b = rejudge.open_board(self.bd, repo=self.repo, allow_halted=True)
        head, gate, items = self.three(b)
        self.assertIn("- 再審: 無い", gate)
        self.assertNotIn("再審の結果", head)
        self.assertEqual(items, [])

    def test_units_shown_when_verdict_missing(self):
        """判定の欄が無い往復（collect が "" を入れる）でも、同じ出口の開いた・下げた単位を 3 か所から落とさない"""
        b = self.settled("採る", new=[self.NEW], lower=[UNIT_A])
        p = self.work(rejudge.EXIT_NAME)
        doc = json.loads(p.read_text(encoding="utf-8"))
        p.write_text(json.dumps({**doc, "verdicts": [""]}, ensure_ascii=False), encoding="utf-8")
        head, gate, items = self.three(b)
        for where, text in (("冒頭 1", head), ("最後の関所", gate)):
            with self.subTest(where):
                self.assertIn("再審の結果（r1・1 往復）: （判定の欄が無い）", text)
                self.assertIn(self.NEW, text)
                self.assertIn(f"に下げた（拒まずに見せる——人が確かめる）: {UNIT_A}", text)
        self.assertNotIn("- 再審: 無い", gate)
        wheres = [i["where"] for i in items]
        self.assertIn(self.NEW, wheres, items)
        self.assertIn(UNIT_A, wheres, items)

    def test_unreadable_exit_is_shown(self):
        b = self.settled("採る")
        self.work(rejudge.EXIT_NAME).write_text("{壊れた", encoding="utf-8")
        head, gate, items = self.three(b)
        for text in (head, gate, json.dumps(items, ensure_ascii=False)):
            self.assertIn("再審の記録が読めない", text)

    def test_named_removed_unit_shown(self):
        """異議に名指された単位を再審が消した変化も冒頭 1 に出る（争点でない変化だけを出さない）"""
        import report
        self.board("objection")
        reply = load("rejudge_settled")
        reply["units"] = [u for u in reply["units"] if u["key"] != UNIT_A]
        self.assertTrue(self.run_pass(reply)["ok"])
        rejudge.collect(self.bd)
        b = rejudge.open_board(self.bd, repo=self.repo, allow_halted=True)
        head = report.head_decisions(b, {"accepted": True, "round_closed": True})
        self.assertIn(f"再審（rejudge）で異議に名指された単位が消えた: {UNIT_A}", head)


class ShimCase(unittest.TestCase):
    def test_shim_home_matches_adapter(self):
        """包みの代わりの家の既定は本物の包みと同じ ${WORKS_ADAPTER_HOME:-${XDG_STATE_HOME:-~/.local/state}/works/adapter}"""
        S = rejudge._AdapterShim
        with mock.patch.dict(os.environ, {"XDG_STATE_HOME": "/x/state", "HOME": "/h"}):
            os.environ.pop(rejudge.ADAPTER_HOME_ENV, None)
            self.assertEqual(S.session_path("/w", "judge").parents[2], pathlib.Path("/x/state/works/adapter"))
            os.environ.pop("XDG_STATE_HOME")
            self.assertEqual(S.launches_path("/w").parents[1], pathlib.Path("/h/.local/state/works/adapter"))
            os.environ[rejudge.ADAPTER_HOME_ENV] = "/a"
            self.assertEqual(S.launches_path("/w").parents[1], pathlib.Path("/a"))


class CostCase(unittest.TestCase):
    J = "aaaaaaaa-0000-4000-8000-000000000001"
    F = "bbbbbbbb-0000-4000-8000-000000000002"

    @staticmethod
    def row(node, mode, sid, at, **kw):
        return {"at": f"2026-09-27T10:00:{at:02d}.000000+09:00", "node": node, "session": {"mode": mode, "id": sid, **kw}}

    def test_actual_costs_subtract(self):
        launches = [self.row("judge", "new", self.J, 1), self.row("rejudge", "continued", self.J, 2, of="judge", **{"from": self.J})]
        shown = [{"node": "judge", "cost_usd": 0.0284}, {"node": "rejudge", "cost_usd": 0.0615}]
        got = rejudge.actual_costs(launches, shown)
        self.assertEqual([r["node"] for r in got], ["judge", "rejudge"])
        self.assertAlmostEqual(got[0]["actual"], 0.0284)
        self.assertAlmostEqual(got[1]["actual"], 0.0331)
        self.assertIn("引いた", got[1]["note"])
        self.assertEqual(got[0]["note"], "")

    def test_actual_costs_chain_and_fork(self):
        launches = [self.row("rejudge2", "continued", self.J, 5, of="judge", **{"from": self.J}),   # 時刻の順に並べ直す
                    self.row("judge", "new", self.J, 1),
                    self.row("rejudge", "continued", self.J, 2, of="judge", **{"from": self.J}),
                    self.row("fix", "sdk-fork", self.F, 3, **{"from": self.J}),
                    self.row("rejudge-third", "new", "cccccccc-0000-4000-8000-000000000003", 4)]
        shown = [{"node": "judge", "cost_usd": 0.0284}, {"node": "rejudge", "cost_usd": 0.0615},
                 {"node": "fix", "cost_usd": 0.0952}, {"node": "rejudge-third", "cost_usd": 0.02},
                 {"node": "rejudge2", "cost_usd": 0.0900}]
        got = {r["node"]: r["actual"] for r in rejudge.actual_costs(launches, shown)}
        self.assertAlmostEqual(got["rejudge"], 0.0331)
        self.assertAlmostEqual(got["fix"], 0.0952 - 0.0615)
        self.assertAlmostEqual(got["rejudge-third"], 0.02)
        self.assertAlmostEqual(got["rejudge2"], 0.0900 - 0.0615)

    def test_actual_costs_missing(self):
        launches = [self.row("judge", "new", self.J, 1)]
        for shown in ([], None, [{"node": "judge", "cost_usd": None}]):
            with self.subTest(shown):
                got = rejudge.actual_costs(launches, shown)
                self.assertEqual(len(got), 1)
                self.assertIsNone(got[0]["actual"])
                self.assertIn("取れない", got[0]["note"])

    def test_actual_costs_unknown_base(self):
        """継いだ会話の元の費用が取れなければ、引けないので取れない（表示をそのまま実額にしない）"""
        launches = [self.row("judge", "new", self.J, 1), self.row("rejudge", "continued", self.J, 2, of="judge", **{"from": self.J})]
        got = rejudge.actual_costs(launches, [{"node": "rejudge", "cost_usd": 0.0615}])
        self.assertEqual([r["actual"] for r in got], [None, None])

    def test_refused_launch_has_no_cost(self):
        launches = [self.row("judge", "new", self.J, 1),
                    {"at": "2026-09-27T10:00:02.000000+09:00", "node": "rejudge", "session": {"mode": "refused", "id": None, "of": "judge"}},
                    self.row("rejudge", "continued", self.J, 3, of="judge", **{"from": self.J})]
        got = rejudge.actual_costs(launches, [{"node": "judge", "cost_usd": 0.0284}, {"node": "rejudge", "cost_usd": 0.0615}])
        self.assertEqual([r["node"] for r in got], ["judge", "rejudge"])
        self.assertAlmostEqual(got[1]["actual"], 0.0331)


if __name__ == "__main__":
    unittest.main()
