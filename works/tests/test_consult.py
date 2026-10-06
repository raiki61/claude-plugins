"""範囲の相談の節（blk-fix/lib/consult.py・scripts/consult_prep.py・consult_check.py。設計 docs/plans/2026-10-06-ask-planner.md）の検査。

縛る事:
- 先の確かめ（screen）: 知らない項目・頼む物が無い・理由が短い・根の外のパス・out_of_scope に当たるパス・全部がもう範囲の中の頼みは、
  答えの節に聞かずに断る（記録は残す）
- 答えの確かめ（judge）: 許すのは頼んだ物の中だけ（足した物は捨てて注記）。形の崩れた答えは invalid で、許しを作らない
- 頼みの節（ask）: 返答に consult が無ければ何もしない。在れば頼みごとに確かめて状態に積み、聞く頼みが在れば相手の会話の id を
  ブロックの中の名 PEER で包みの置き場に写して（alias）答えの節の指示書を書く。相手の会話が無ければ聞けない行にして答えの節を
  起こさない。枠（BUDGET）を使い切った後は consulted: false・spent: true（受け付けが拒む）
- 確かめの節（settle）: 1 頼み 1 行を盤面の trace（conflict.ASKED_OP）に書く（断った・聞けなかった行も）。allow の行は合意
  （conflict.agreed）として範囲とテストの許しに入る。部品の窓の照らしで宣言の外に書かない。答えのファイルを書き、支度（take）が
  1 度だけ引く
- 包みの旗 self-resume（adapter の 1）: SDK が会話を継ぐ起動（輪の 2 周目）は SDK の会話でなく自分の記録した会話を継ぐ。1 周目は
  新しい会話。自分の id が無ければ起こさない。答えの節（continue=PEER）は写した相手の会話を継ぐ
- YAML の形: 修正の輪と 2 回目の修正の輪の節の順・印・答えの節の出力・輪の上限（受け付けの 3 回と枠の和）・表 stage-models.json
- 指示書: 修正役の相談の節は consult の欄を言い、Bash で claude を起こすコマンドを持たない。下請けの節はまとめ役への報告を言う
盤面は trace と周の作業ファイルだけを持つ偽物（git・子のプロセスなし）。
"""
import importlib.util
import json
import pathlib
import sys
import tempfile
import unittest
from unittest import mock

import yaml

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.dont_write_bytecode = True
sys.path.insert(0, str(ROOT / "blk-fix" / "lib"))
sys.path.insert(0, str(ROOT / ".shared" / "core"))

import adapter  # noqa: E402
import conflict  # noqa: E402
import consult  # noqa: E402
import fixrules  # noqa: E402
import recount  # noqa: E402
import scopes  # noqa: E402

ITEMS = {"3": {"unit_keys": ["lens.py count_line: 落ちたレンズの数"], "allowed_paths": ["works/.shared/core/lens.py"],
               "out_of_scope": ["works/README.md"], "tests": ["works/tests/test_lens.py"]}}
WHY = "直しに伴って変更の記録を足す要がある"
SID = "11111111-2222-3333-4444-555555555555"


class FakeBoard:
    """trace と今の scope の周の作業ファイルだけを持つ盤面（DiskBoard の work・trace・round の形）"""

    def __init__(self, d, scope="fixing", round_=1):
        self.dir = pathlib.Path(d)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.scope, self.round, self.state = scope, round_, {}

    def work(self, name):
        p = self.dir / self.scope / f"r{self.round}" / name
        p.parent.mkdir(parents=True, exist_ok=True)
        return p

    def trace(self, op, **kw):
        with open(self.dir / "trace.jsonl", "a", encoding="utf-8") as f:
            f.write(json.dumps({"op": op, **kw, "scope": self.scope}, ensure_ascii=False) + "\n")


def reply(*asks):
    return {"changes": [], conflict.CONSULT_FIELD: list(asks)}


def ask_row(item=3, paths=("works/CHANGELOG.md",), tests=(), why=WHY):
    return {"item": item, "paths": list(paths), "tests": list(tests), "why": why}


class Base(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = pathlib.Path(self._tmp.name).resolve()
        self.repo = self.root / "repo"
        self.repo.mkdir()
        self.home = self.root / "adapter-home"
        self.b = FakeBoard(self.root / "board")
        for rel in ("state.json", "r1/start.json", "trace.jsonl"):
            (self.b.dir / rel).parent.mkdir(parents=True, exist_ok=True)
            (self.b.dir / rel).write_text("" if rel.endswith(".jsonl") else "{}", encoding="utf-8")
        p = mock.patch.object(consult, "items_of", lambda b: ITEMS)
        p.start()
        self.addCleanup(p.stop)

    def plan_session(self, node="plan", sid=SID):
        path = adapter.session_path(self.repo, node, self.home)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(sid + "\n", encoding="utf-8")

    def ask(self, r, plan_session="plan", pass_="first"):
        return consult.ask(self.b, self.repo, r, plan_session, pass_, "plan-answer", home_dir=self.home)


class ScreenCase(unittest.TestCase):
    def test_refusals(self):
        self.assertIn("項目", consult.screen(ITEMS, "9", ["a.py"], [], WHY))
        self.assertIn("根の外", consult.screen(ITEMS, "3", ["../x.py"], [], WHY))
        self.assertIn("根の外", consult.screen(ITEMS, "3", ["/etc/x"], [], WHY))
        self.assertIn("out_of_scope", consult.screen(ITEMS, "3", ["works/README.md"], [], WHY))
        self.assertIn("範囲の中", consult.screen(ITEMS, "3", ["works/.shared/core/lens.py"], [], WHY))
        self.assertIn("何も", consult.screen(ITEMS, "3", [], [], WHY))
        self.assertIn("理由", consult.screen(ITEMS, "3", ["works/CHANGELOG.md"], [], "短い"))

    def test_passes(self):
        self.assertIsNone(consult.screen(ITEMS, "3", ["works/CHANGELOG.md"], [], WHY))
        self.assertIsNone(consult.screen(ITEMS, "3", [], ["works/tests/test_report.py:12"], WHY))
        self.assertIsNone(consult.screen(ITEMS, "3", ["works/.shared/core/lens.py", "works/CHANGELOG.md"], [], WHY),
                          "範囲の外を 1 本でも含む頼みは聞く")


class JudgeCase(unittest.TestCase):
    def test_grant_is_cut_to_what_was_asked(self):
        got, notes = consult.judge({"decision": "allow", "paths": ["a.md", "b.md"], "tests": ["t.py:3"], "spec": "",
                                    "reason": "変更の記録は直しに伴う"}, ["a.md"], ["t.py:3"])
        self.assertEqual((got["decision"], got["granted_paths"], got["granted_tests"]), ("allow", ["a.md"], ["t.py:3"]))
        self.assertTrue(any("b.md" in n for n in notes), notes)

    def test_malformed_answers_are_invalid(self):
        for bad in ({"decision": "maybe", "reason": "x" * 12}, {"decision": "allow", "paths": [], "tests": [], "reason": "x" * 12},
                    {"decision": "deny"}, "not a dict", None):
            got, notes = consult.judge(bad, ["a.md"], [])
            self.assertIsNone(got, bad)
            self.assertTrue(notes, bad)

    def test_deny_and_defer_grant_nothing(self):
        for d in ("deny", "defer"):
            got, _ = consult.judge({"decision": d, "paths": ["a.md"], "tests": [], "spec": "", "reason": "今の run の仕様の外"},
                                   ["a.md"], [])
            self.assertEqual((got["granted_paths"], got["granted_tests"]), ([], []), d)


class RequestsCase(unittest.TestCase):
    def test_shapes(self):
        self.assertIsNone(consult.requests({"changes": []}))
        self.assertIsNone(consult.requests({conflict.CONSULT_FIELD: []}))
        self.assertIsNone(consult.requests(None))
        got = consult.requests(reply(ask_row(paths=["a.md", " "], tests=["t.py:3"])))
        self.assertEqual(got, [{"item": "3", "paths": ["a.md"], "tests": ["t.py:3"], "why": WHY}])
        self.assertEqual(consult.requests({conflict.CONSULT_FIELD: ["x"]}), [{"item": "", "paths": [], "tests": [], "why": ""}],
                         "形の崩れた頼みは欄を空にして残す（screen が断る）")


class AliasCase(Base):
    def test_copies_the_peer_session(self):
        self.plan_session()
        err, sid = consult.alias(self.repo, "plan", self.home)
        self.assertEqual((err, sid), (None, SID))
        self.assertEqual(adapter.read_session_id(adapter.session_path(self.repo, consult.PEER, self.home)), SID)

    def test_missing_or_empty(self):
        self.assertEqual(consult.alias(self.repo, "", self.home), (consult.NO_PEER, None))
        err, sid = consult.alias(self.repo, "plan", self.home)
        self.assertIsNone(sid)
        self.assertIn("plan", err)


class FlowCase(Base):
    def test_no_consult_is_a_no_op(self):
        out = self.ask({"changes": []})
        self.assertEqual((out["consulted"], out["go"], out["spent"]), (False, False, False))
        self.assertEqual(consult.settle(self.b, None, "first", "plan-answer")["consulted"], False)
        self.assertIsNone(consult.take(self.b, "first"))
        self.assertEqual(conflict.plan_asks(self.b), [])

    def test_allow_round_trip(self):
        self.plan_session()
        window = {"scope": "fixing", "block": "blk-fix", "round": 1, "files": scopes.snapshot(self.b.dir)}
        out = self.ask(reply(ask_row(tests=["works/tests/test_report.py:12"]), ask_row(paths=["works/README.md"])))
        self.assertEqual((out["consulted"], out["go"], out["turn"], out["spent"]), (True, True, 1, False))
        q = pathlib.Path(out["prompt_file"]).read_text(encoding="utf-8")
        self.assertIn("相談 1", q)
        self.assertNotIn("相談 2", q, "断った頼みは答えの節に聞かない")
        self.assertIn("works/CHANGELOG.md", q)
        self.assertEqual(adapter.read_session_id(adapter.session_path(self.repo, consult.PEER, self.home)), SID)
        answer = {"answers": [{"ask": 1, "decision": "allow", "paths": ["works/CHANGELOG.md", "works/other.md"],
                               "tests": ["works/tests/test_report.py:12"], "spec": "1 行だけ足す",
                               "reason": "直しに伴う変更の記録と期待の書き換え"}]}
        got = consult.settle(self.b, answer, "first", "plan-answer")
        self.assertEqual((got["consulted"], got["turn"]), (True, 1))
        self.assertEqual(got["counts"], {"allow": 1, "refused": 1})
        rows = conflict.plan_asks(self.b)
        self.assertEqual([(r["id"], r["status"]) for r in rows], [(1, "answered"), (2, "refused")])
        self.assertIn("out_of_scope", rows[1]["why_refused"])
        self.assertEqual((rows[0]["pass"], rows[0]["round"], rows[0]["turn"], rows[0]["node"]), ("first", 1, 1, "plan-answer"))
        self.assertEqual(rows[0]["session"], {"of": "plan", "id": SID, "as": consult.PEER})
        (agreed,) = conflict.agreed(self.b)
        self.assertEqual((agreed["item"], agreed["granted_paths"]), ("3", ["works/CHANGELOG.md"]), "頼んでいない物は捨てる")
        (permit,) = conflict.agreed_permits([agreed])
        self.assertEqual((permit["limit"], permit["id"]), ("works/tests/test_report.py:12", f"{conflict.AGREED_TEST_ID}-3"))
        text = pathlib.Path(got["answer_file"]).read_text(encoding="utf-8")
        for w in ("allow", "works/CHANGELOG.md", "1 行だけ足す", "refused", "out_of_scope", "works/other.md"):
            self.assertIn(w, text)
        self.assertEqual(scopes.check_window(self.b.dir, window), [], "相談の節は宣言の外に書かない")
        took = consult.take(self.b, "first")
        self.assertEqual((took["turn"], took["answer_file"], took["left"]), (1, got["answer_file"], consult.BUDGET - 1))
        self.assertIsNone(consult.take(self.b, "first"), "答えは 1 度だけ渡す")
        # 次の相談は id を続け、周を数える
        out = self.ask(reply(ask_row()))
        self.assertEqual(out["turn"], 2)
        consult.settle(self.b, {"answers": [{"ask": 1, "decision": "deny", "paths": [], "tests": [], "spec": "",
                                             "reason": "範囲の中で直せる"}]}, "first", "plan-answer")
        self.assertEqual([r["id"] for r in conflict.plan_asks(self.b)], [1, 2, 3])
        self.assertEqual(len(conflict.agreed(self.b)), 1, "deny は合意にならない")

    def test_passes_are_separate(self):
        self.plan_session()
        self.ask(reply(ask_row()), pass_="first")
        self.assertEqual(consult.settle(self.b, None, "ruled", "plan-answer-ruled")["consulted"], False)
        self.assertEqual(consult.state(self.b, "ruled"), {"turns": 0})

    def test_no_peer_is_unavailable_without_asking(self):
        out = self.ask(reply(ask_row()), plan_session="plan")   # 包みの置き場に plan の id が無い
        self.assertEqual((out["consulted"], out["go"], out["prompt_file"]), (True, False, ""))
        got = consult.settle(self.b, None, "first", "plan-answer")
        self.assertEqual(got["counts"], {"unavailable": 1})
        (row,) = conflict.plan_asks(self.b)
        self.assertIn("plan", row["why_unavailable"])
        out = self.ask(reply(ask_row()), plan_session="")
        self.assertFalse(out["go"])

    def test_missing_or_broken_answer(self):
        self.plan_session()
        self.ask(reply(ask_row()))
        consult.settle(self.b, None, "first", "plan-answer")
        self.ask(reply(ask_row()))
        consult.settle(self.b, {"answers": [{"ask": 1, "decision": "allow", "paths": [], "tests": [], "spec": "",
                                             "reason": "全部よい（頼んだ物を名指さない）"}]}, "first", "plan-answer")
        self.ask(reply(ask_row()))
        consult.settle(self.b, {"answers": [{"ask": 2, "decision": "allow", "paths": ["works/CHANGELOG.md"], "tests": [],
                                             "spec": "", "reason": "番号の違う答え"}]}, "first", "plan-answer")
        self.assertEqual([r["status"] for r in conflict.plan_asks(self.b)], ["unavailable", "invalid", "invalid"])
        self.assertEqual(conflict.agreed(self.b), [])

    def test_budget(self):
        self.plan_session()
        for _ in range(consult.BUDGET):
            self.assertTrue(self.ask(reply(ask_row()))["consulted"])
            consult.settle(self.b, None, "first", "plan-answer")
            consult.take(self.b, "first")
        out = self.ask(reply(ask_row()))
        self.assertEqual((out["consulted"], out["go"], out["spent"]), (False, False, True))
        self.assertEqual(consult.left(self.b, "first"), 0)


class SelfResumeCase(unittest.TestCase):
    """包みの旗 self-resume と答えの節の continue=PEER（adapter.plan を直に呼ぶ）"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = pathlib.Path(self._tmp.name).resolve()
        self.cwd = self.tmp / "wt"
        self.cwd.mkdir()
        self.home = self.tmp / "adapter-home"

    def argv(self, marker, *extra):
        schema = {"type": "object", "description": marker, "properties": {"a": {"type": "string"}}}
        return ["--output-format", "json", "--model", "sonnet", "--effort", "high", "--json-schema", json.dumps(schema),
                "--tools", "", "--setting-sources=user", *extra]

    def plan(self, argv):
        return adapter.plan(argv, str(self.cwd), self.home, "true", new_id=lambda: "s-new",
                            env={"PATH": "/usr/bin:/bin"})

    def put(self, node, sid):
        p = adapter.session_path(self.cwd, node, self.home)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(sid + "\n", encoding="utf-8")

    def resumed(self, p):
        return [v for _, _, v, _ in adapter.find_opt(p.argv, "--resume")]

    def test_first_lap_is_a_new_conversation(self):
        p = self.plan(self.argv("works-node: fix self-resume"))
        self.assertEqual(p.mode, "merged", p.why)
        self.assertEqual((p.session["mode"], p.session["id"]), ("new", "s-new"))
        self.assertEqual(self.resumed(p), [])

    def test_later_lap_returns_to_own_conversation(self):
        self.put("fix", "fix-own")
        p = self.plan(self.argv("works-node: fix self-resume", "--resume", "planner-sid", "--fork-session"))
        self.assertEqual(p.mode, "merged", p.why)
        self.assertEqual(self.resumed(p), ["fix-own"], "SDK が継がせた相手の会話でなく自分の会話")
        self.assertNotIn("--fork-session", p.argv)
        self.assertEqual(p.session, {"mode": "continued", "id": "fix-own", "of": "fix", "from": "fix-own",
                                     "sdk": "planner-sid"})
        self.assertIn((adapter.session_path(self.cwd, "fix", self.home), "fix-own"), p.record)

    def test_later_lap_without_own_id_is_refused(self):
        p = self.plan(self.argv("works-node: fix self-resume", "--resume", "planner-sid"))
        self.assertEqual(p.mode, "refused")
        self.assertIn("self-resume", p.why)

    def test_without_flag_the_sdk_session_is_kept(self):
        p = self.plan(self.argv("works-node: fix", "--resume", "planner-sid"))
        self.assertEqual(self.resumed(p), ["planner-sid"], "旗の無い節の振る舞いは変えない")

    def test_answer_node_continues_the_peer(self):
        self.put(consult.PEER, "planner-sid")
        p = self.plan(self.argv(f"works-node: plan-answer continue={consult.PEER}", "--resume", "fix-own"))
        self.assertEqual(p.mode, "merged", p.why)
        self.assertEqual(self.resumed(p), ["planner-sid"])
        self.assertEqual(p.session["of"], consult.PEER)


def _find(nodes, nid):
    for n in nodes or []:
        if n.get("id") == nid:
            return n
        got = _find((n.get("loop_group") or {}).get("nodes"), nid)
        if got:
            return got
    return None


class YamlCase(unittest.TestCase):
    def setUp(self):
        self.doc = yaml.safe_load((ROOT / "blk-fix" / "blk-fix.yaml").read_text(encoding="utf-8"))
        spec = importlib.util.spec_from_file_location("blk_fix_accept_for_consult", ROOT / "blk-fix" / "scripts" / "accept.py")
        self.accept = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.accept)

    def check_loop(self, loop, prep, role, cons, ans, check, accept, pass_):
        g = _find(self.doc["nodes"], loop)["loop_group"]
        self.assertEqual([n["id"] for n in g["nodes"]][1:], [role, cons, ans, check, *([] if accept != "fix-accept" else
                                                                                         ["fix-units"]), accept])
        self.assertEqual(g["max_iterations"], self.accept.GIVE_UP_AFTER + consult.BUDGET)
        c, a, k, acc = (_find(g["nodes"], x) for x in (cons, ans, check, accept))
        self.assertEqual((c["script"], c["depends_on"]), ("consult_prep", [role]))
        self.assertEqual(c["with"], {"reply": {"from": f"${role}.output"}, "plan_session": "$INPUTS.plan_session",
                                     "pass": pass_, "answer_node": ans})
        self.assertEqual(a["output_format"], consult.answer_format(ans))
        self.assertEqual(a["output_format"]["description"], f"works-node: {ans} continue={consult.PEER}")
        self.assertEqual((a["depends_on"], a["when"]), ([cons], f"${cons}.output.go == true"))
        self.assertEqual(a["allowed_tools"], ["Read", "Grep", "Glob", "WebSearch", "WebFetch"], "修正案を書いた役と同じ読むだけの道具")
        self.assertIs(a["mutates_checkout"], False)
        self.assertNotIn("context", a, "会話を継ぐのは包み（continue=）で、節に context は書かない")
        self.assertIn(f"`${cons}.output.prompt_file`", a["prompt"])
        self.assertEqual((k["script"], k["depends_on"], k["trigger_rule"]),
                         ("consult_check", [cons, ans], "none_failed_min_one_success"))
        self.assertEqual(k["with"], {"answer": {"from": f"${ans}.output", "if_skipped": None}, "pass": pass_,
                                     "answer_node": ans})
        self.assertEqual(acc["with"]["consulted"], f"${check}.output.consulted")
        self.assertIn("consulted", acc["output_format"]["properties"])
        models = json.loads((ROOT / ".shared" / "core" / "stage-models.json").read_text(encoding="utf-8"))
        cls = models["classes"][models["stages"][f"blk-fix/{ans}"]]
        self.assertEqual((a["model"], a["effort"]), (cls["model"], cls["effort"]))
        self.assertEqual((cls["model"], cls["effort"]), ("opus", "medium"), "修正案を書く役と同じ組")

    def test_fix_loop(self):
        self.check_loop("fix-loop", "fix-prep", "fix", "fix-consult", "plan-answer", "fix-consult-check", "fix-accept", "first")
        units = _find(self.doc["nodes"], "fix-units")
        self.assertEqual((units["depends_on"], units["with"]),
                         (["fix-consult-check"], {"consulted": "$fix-consult-check.output.consulted"}))

    def test_ruled_loop(self):
        self.check_loop("fix-ruled-loop", "fix-ruled-prep", "fix-ruled", "fix-ruled-consult", "plan-answer-ruled",
                        "fix-ruled-consult-check", "fix-ruled-accept", "ruled")

    def test_role_markers(self):
        self.assertEqual(_find(self.doc["nodes"], "fix")["output_format"], recount.FIX_OUTPUT_FORMAT)
        self.assertEqual(recount.FIX_OUTPUT_FORMAT["description"], "works-node: fix self-resume")
        self.assertEqual(recount.RULED_OUTPUT_FORMAT["description"], "works-node: fix-ruled continue=fix")
        self.assertEqual(recount.FIX_OUTPUT_FORMAT["properties"][conflict.CONSULT_FIELD], conflict.CONSULT_SCHEMA)


class AcceptCase(unittest.TestCase):
    """受け付けの入口: 相談の周は返答も盤面も見ずに consulted の 1 行。done は立てない"""

    def test_consulted_out(self):
        spec = importlib.util.spec_from_file_location("blk_fix_accept_for_consult2", ROOT / "blk-fix" / "scripts" / "accept.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        out = mod.consulted_out()
        self.assertEqual((out["ok"], out["done"], out["consulted"], out["reason_file"], out["changes"]),
                         (False, False, True, "", []))
        self.assertIn("consult", mod.CHECKS)


class RulesTextCase(unittest.TestCase):
    def test_role_section_says_reply_field_not_command(self):
        text = fixrules.ask_text("/rp/fixing/consult/consult.json", "/py/bin/python3")
        for w in ("`consult`", "factchecks.py", "/rp/fixing/consult/consult.json", "--reply", str(consult.BUDGET), "下請け"):
            self.assertIn(w, text)
        for w in ("askplan", "--item", "--why", "claude"):
            self.assertNotIn(w, text, "役の Bash から相談のコマンドを走らせない")

    def test_sub_section_reports_to_coordinator(self):
        text = fixrules.ask_sub_text("/rp/fixing/consult/consult.json", "/py/bin/python3")
        self.assertIn("まとめ役", text)
        self.assertIn("factchecks.py /rp/fixing/consult/consult.json", text)
        self.assertNotIn("--reply", text)

    def test_reject_head_names_the_reply_field(self):
        import planscope
        self.assertIn("consult", planscope.REJECT_ASK)
        self.assertNotIn("コマンドで修正案を書いた役に聞け", planscope.REJECT_ASK)


if __name__ == "__main__":
    unittest.main()
