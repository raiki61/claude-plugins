"""包み（.shared/core/claude-adapter）が、会話を Archon の思うのと違う所から開いた起動の result の費用の累計を、Archon の
引き算が本当の 1 起動の費用になる値に見せ直すこと（adapter.py の頭の 20）。

Archon v0.11.1 の claude の provider は、result の total_cost_usd（会話の累計）から、Archon が --resume に渡した会話の id で
覚えた前の result の累計を引いて節の費用にし、modelUsage の模型ごとの outputTokens の増えた物から一番多い模型を節の模型と
名乗る（バンドルの Ixt・F4n・tHo。下の ArchonSpend はその写し）。包みが会話を替えた起動（単位の切れ目で新しい会話・continue=X・
旗 self-resume）では引く元が違う会話の累計になり、run 01004d2e の tdd-lane-2 の 5 回目（費用が出ず not_reported、模型が
claude-haiku-4-5）・plan-answer（not_reported）・fix-ruled の 1 回目（修正役の会話の累計 1.87 ドルを丸ごと数えた）になった。
下の筋書きの数はその run の会話の記録（transcript の cost-state の行）の実物。

偽の claude は一時の置き場の小さな python（argv の --session-id か --resume の id を session_id にして、決めた累計の result を
出す）。包みを子で起こすだけで、git・Archon・決まった秒の待ちは無い。
"""
import json
import os
import pathlib
import stat
import subprocess
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
CORE = ROOT / ".shared" / "core"
ADAPTER = CORE / "claude-adapter"
sys.dont_write_bytecode = True
sys.path.insert(0, str(CORE))

import adapter  # noqa: E402

HAIKU, SONNET, OPUS = "claude-haiku-4-5-20251001", "claude-sonnet-5-5", "claude-opus-5-5"


class ArchonSpend:
    """Archon v0.11.1 の claude の provider の費用の引き算の写し（Ixt.baselineFor・record、F4n、tHo）。
    node(resume, result) は (節の costUsd（None は not_reported）, 名乗る模型)"""

    def __init__(self):
        self.latest = {}

    def node(self, resume, result):
        base = None if resume is None else self.latest.get(resume, "unknown")
        mu = result.get("modelUsage") or {}
        cost = result.get("total_cost_usd")
        got_cost, got_mu = None, mu
        if isinstance(cost, (int, float)):
            self.latest[result["session_id"]] = {"cost": cost, "mu": mu}
            if base is None:
                got_cost = cost
            elif base == "unknown":
                got_mu = mu if len(mu) == 1 else {}
            else:
                got_mu = {}
                for m, o in mu.items():
                    a = o["outputTokens"] - (base["mu"].get(m) or {}).get("outputTokens", 0)
                    if a > 0:
                        got_mu[m] = dict(o, outputTokens=a)
                r = cost - base["cost"]
                got_cost = r if r >= 0 else None
        model = None
        for m, o in got_mu.items():
            if model is None or o["outputTokens"] > got_mu[model]["outputTokens"]:
                model = m
        return got_cost, model


def result(sid, cost, **out):
    """claude の result の行の doc（累計の total_cost_usd と、模型ごとの累計の modelUsage）"""
    names = {"haiku": HAIKU, "sonnet": SONNET, "opus": OPUS}
    return {"type": "result", "subtype": "success", "is_error": False, "num_turns": 3, "session_id": sid,
            "total_cost_usd": cost,
            "modelUsage": {names[k]: {"inputTokens": 10, "outputTokens": v, "costUSD": 0.0} for k, v in out.items()}}


class RestateCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = pathlib.Path(self._tmp.name).resolve()
        self.home = self.tmp / "adapter-home"
        self.cwd = self.tmp / "wt"
        self.cwd.mkdir()
        self.archon = ArchonSpend()

    def launch(self, archon_from, real_from, doc):
        """包みが result の行を見せ直し（adapter.restate_result）、Archon の写しが読む。(節の費用, 模型)"""
        line = json.dumps(doc).encode("utf-8")
        shown = adapter.restate_result(line, doc, self.cwd, self.home,
                                       adapter.spend_bases(self.cwd, self.home, archon_from, real_from))
        return self.archon.node(archon_from, json.loads(shown))

    def restate(self, line, doc, archon_from, real_from):
        bases = adapter.spend_bases(self.cwd, self.home, archon_from, real_from)
        return adapter.restate_result(line, doc, self.cwd, self.home, bases)

    def test_two_results_use_the_same_bases(self):
        """1 つの起動に result が 2 つ来ても、引く元は起動の初めに読んだ物（Archon も問い合わせの初めに 1 回だけ決める）"""
        self.launch(None, None, result("s", 1.0, sonnet=100))
        bases = adapter.spend_bases(self.cwd, self.home, None, "s")
        for cost, want in ((1.5, 0.5), (1.75, 0.75)):
            doc = result("s", cost, sonnet=200)
            shown = json.loads(adapter.restate_result(json.dumps(doc).encode("utf-8"), doc, self.cwd, self.home, bases))
            self.assertAlmostEqual(shown["total_cost_usd"], want, places=9)

    def assert_spend(self, got, cost, model):
        self.assertIsNotNone(got[0], "Archon の引き算で費用が出ない（not_reported）")
        self.assertAlmostEqual(got[0], cost, places=6)
        self.assertEqual(got[1], model)

    def test_unit_cut_shows_new_conversation_cost(self):
        """単位の切れ目で新しい会話にした起動（Archon は前の会話を継いだと思う）: Archon の費用はその会話の費用で、模型は sonnet
        （run 01004d2e の tdd-lane-2 の 5 回目は not_reported・claude-haiku-4-5 だった）"""
        self.assert_spend(self.launch(None, None, result("dcd4", 0.2452746, haiku=19, sonnet=1598)), 0.2452746, SONNET)
        self.assert_spend(self.launch("dcd4", "dcd4", result("afd0", 0.321957, haiku=19, sonnet=2623)), 0.0766824, SONNET)
        self.assert_spend(self.launch("afd0", "afd0", result("601a", 0.4930156, haiku=19, sonnet=5859)), 0.1710586, SONNET)
        self.assert_spend(self.launch("601a", None, result("4ddc", 0.1751296, haiku=23, sonnet=1796)), 0.1751296, SONNET)

    def test_continued_conversations_show_their_own_delta(self):
        """continue=X・旗 self-resume で包みが別の会話を継いだ起動: Archon の費用はその起動で増えた分（run 01004d2e は
        plan-answer が not_reported、fix の 2 回目が 0.304（本当は 0.240）、fix-ruled の 1 回目が 1.874（本当は 0.900））"""
        self.assert_spend(self.launch(None, None, result("bbd6", 0.35833, haiku=19, opus=7498)), 0.35833, OPUS)
        self.assert_spend(self.launch(None, None, result("7fe0", 0.7339188, haiku=19, sonnet=20269)), 0.7339188, SONNET)
        # 答えの節（continue=fix-planner）: Archon は直前の修正役の会話を継いだと思う
        self.assert_spend(self.launch("7fe0", "bbd6", result("bbd6", 0.6702664, haiku=19, opus=8620)), 0.3119364, OPUS)
        # 修正役の 2 周目（旗 self-resume）: Archon は答えの節の会話を継いだと思う
        self.assert_spend(self.launch("bbd6", "7fe0", result("7fe0", 0.9738514, haiku=19, sonnet=27050)), 0.2399326, SONNET)
        # 裁定の後の修正役（continue=fix。YAML は context: fresh なので Archon は新しい会話と思う）
        self.assert_spend(self.launch(None, "7fe0", result("7fe0", 1.8738024, haiku=19, sonnet=39590)), 0.899951, SONNET)
        self.assert_spend(self.launch("7fe0", "7fe0", result("7fe0", 2.2189394, haiku=19, sonnet=46224)), 0.345137, SONNET)

    def test_fork_of_planner_shows_its_own_delta(self):
        """旗 fork（continue=fix-planner fork。修正役の並べの枝の答えの節）: 包みは修正案を書いた役の会話の写しを新しい id で起こす。
        Archon は直前の枝の役の会話を継いだと思う。写しの result は元の会話の累計を持つので、見せる費用は写しで増えた分で、
        元の会話の記録は変わらない（同時に走る 2 本の写しも、後の修正の輪の答えの節（continue=fix-planner）も元の累計から引く）"""
        self.assert_spend(self.launch(None, None, result("plan", 0.5, haiku=19, opus=8000)), 0.5, OPUS)
        self.assert_spend(self.launch(None, None, result("lane1", 0.3, sonnet=4000)), 0.3, SONNET)
        self.assert_spend(self.launch(None, None, result("lane2", 0.2, sonnet=3000)), 0.2, SONNET)
        before = adapter.spend_path(self.cwd, "plan", self.home).read_bytes()
        self.assert_spend(self.launch("lane1", "plan", result("fork1", 0.62, haiku=19, opus=9000)), 0.12, OPUS)
        self.assert_spend(self.launch("lane2", "plan", result("fork2", 0.65, haiku=19, opus=9500)), 0.15, OPUS)
        self.assertEqual(adapter.spend_path(self.cwd, "plan", self.home).read_bytes(), before, "写しは元の会話の記録を変えない")
        # 枝の役の 2 周目（旗 self-resume）: Archon は写しの会話を継いだと思う
        self.assert_spend(self.launch("fork1", "lane1", result("lane1", 0.45, sonnet=5000)), 0.15, SONNET)
        # 修正の輪の答えの節（continue=fix-planner。写しでない）: 元の会話の累計から引く
        self.assert_spend(self.launch(None, "plan", result("plan", 0.7, haiku=19, opus=10000)), 0.2, OPUS)

    def test_fork_without_carried_total_counts_as_new(self):
        """写しの result が元の累計を持たない（継いだ元の本当の累計より小さい）なら、新しい会話と同じに数える（負の費用にしない）"""
        self.launch(None, None, result("plan", 0.5, opus=8000))
        self.launch(None, None, result("lane1", 0.3, sonnet=4000))
        self.assert_spend(self.launch("lane1", "plan", result("fork1", 0.12, opus=1000)), 0.12, OPUS)

    def test_same_conversation_keeps_bytes(self):
        """Archon の思う元と包みが開いた元が同じ（見せ直しの差が無い）起動は、result の行をそのままのバイトで写す"""
        doc = result("a", 0.5, haiku=19, sonnet=100)
        line = json.dumps(doc, separators=(",", ":")).encode("utf-8")
        self.assertEqual(self.restate(line, doc, None, None), line)
        doc2 = result("b", 0.75, haiku=19, sonnet=200)
        line2 = json.dumps(doc2, separators=(",", ":")).encode("utf-8")
        self.assertEqual(self.restate(line2, doc2, "a", "a"), line2)

    def test_unknown_base_keeps_bytes(self):
        """引く元の記録が無い（包みの記録の前の会話・見せ直しの記録が読めない）起動は、決めずにそのままのバイトで写す"""
        doc = result("c", 0.9, haiku=19, sonnet=300)
        line = json.dumps(doc).encode("utf-8")
        self.assertEqual(self.restate(line, doc, "nope", "c"), line)
        self.assertEqual(self.restate(line, doc, None, "gone"), line)
        no_cost = {"type": "result", "session_id": "d", "num_turns": 1}
        raw = json.dumps(no_cost).encode("utf-8")
        self.assertEqual(self.restate(raw, no_cost, "a", None), raw)

    def test_bad_session_id_is_not_a_path(self):
        """result の session_id が id の形でなければ記録に書かない（置き場の外のパスにしない）"""
        doc = result("../x", 0.1, sonnet=1)
        line = json.dumps(doc).encode("utf-8")
        self.assertEqual(self.restate(line, doc, None, None), line)
        self.assertFalse((self.home / "spend").exists() and any((self.home / "spend").rglob("*.json")))


SANDBOX = '{"sandbox":{"enabled":true,"allowUnsandboxedCommands":false,"failIfUnavailable":true}}'
FAKE = """#!/usr/bin/env python3
import json, os, sys
argv = sys.argv[1:]
sid = None
for i, a in enumerate(argv):
    if a.startswith("--session-id="):
        sid = a.split("=", 1)[1]
    elif a == "--resume" and sid is None:
        sid = argv[i + 1]
cost, out = json.loads(os.environ["FAKE_SPEND"])
sys.stdout.write(json.dumps({"type": "assistant", "message": {"content": []}}) + "\\n")
sys.stdout.write(json.dumps({"type": "result", "subtype": "success", "is_error": False, "num_turns": 2, "session_id": sid,
                             "total_cost_usd": cost,
                             "modelUsage": {"claude-sonnet-5-5": {"inputTokens": 1, "outputTokens": out}}}) + "\\n")
"""


def argv(marker, resume=None):
    """SDK 0.3.282 の並び（test_adapter_no_turn.argv と同じ形）に印と、Archon が継ぐ会話の --resume"""
    schema = {"type": "object", "description": marker, "properties": {"a": {"type": "string"}}}
    a = ["--output-format", "stream-json", "--verbose", "--input-format", "stream-json", "--model", "sonnet",
         "--json-schema", json.dumps(schema), "--tools", "", "--setting-sources=project,user",
         "--permission-mode", "bypassPermissions", "--settings", SANDBOX]
    return a + (["--resume", resume] if resume else [])


class AdapterSpendCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = pathlib.Path(self._tmp.name).resolve()
        self.home = self.tmp / "adapter-home"
        self.cwd = self.tmp / "wt"
        self.cwd.mkdir()
        self.fake = self.tmp / "fake-claude"
        self.fake.write_text(FAKE, encoding="utf-8")
        self.fake.chmod(self.fake.stat().st_mode | stat.S_IXUSR)

    def run_adapter(self, args, cost, out):
        env = {k: v for k, v in os.environ.items() if not k.startswith("WORKS_")}
        env.update(WORKS_ADAPTER_HOME=str(self.home), WORKS_REAL_CLAUDE=str(self.fake), PYTHONDONTWRITEBYTECODE="1",
                   FAKE_SPEND=json.dumps([cost, out]))
        r = subprocess.run([str(ADAPTER), *args], cwd=str(self.cwd), env=env, input="", capture_output=True, text=True,
                           encoding="utf-8", timeout=60)
        self.assertEqual(r.returncode, 0, (r.stdout, r.stderr))
        rows = [json.loads(ln) for ln in r.stdout.splitlines() if ln.strip()]
        return [x for x in rows if x.get("type") == "result"][-1]

    def test_continue_shows_delta_through_the_adapter(self):
        """包みを通した 2 起動: 修正役（新しい会話）の後の continue=fix の起動（Archon は新しい会話と思う）の result は、
        その起動で増えた分を累計として見せる（Archon が丸ごと数えない）。修正役の起動は Archon の思うとおりなのでそのまま"""
        first = self.run_adapter(argv("works-node: fix"), 0.75, 2000)
        self.assertEqual(first["total_cost_usd"], 0.75)
        sid = adapter.read_session_id(adapter.session_path(self.cwd, "fix", self.home))
        self.assertEqual(first["session_id"], sid)
        again = self.run_adapter(argv("works-node: fix-ruled continue=fix"), 1.0, 2600)
        self.assertEqual(again["session_id"], sid)
        self.assertAlmostEqual(again["total_cost_usd"], 0.25, places=9)
        self.assertEqual(again["modelUsage"]["claude-sonnet-5-5"]["outputTokens"], 600)
        # Archon が見せ直した累計の会話を継ぐ次の起動（包みも同じ会話を開く）: Archon の引き算が増えた分になる値
        third = self.run_adapter(argv("works-node: fix-ruled continue=fix", resume=sid), 1.5, 3000)
        self.assertAlmostEqual(third["total_cost_usd"] - again["total_cost_usd"], 0.5, places=9)


    def test_fork_shows_delta_through_the_adapter(self):
        """包みを通した旗 fork の起動: 子は --resume <元> --fork-session --session-id=<新しい id> で起き、result の session_id は
        新しい id。見せる累計は写しで増えた分で、元の会話の id の記録と会話の記録の名は変わらない"""
        first = self.run_adapter(argv("works-node: fix-planner"), 0.5, 8000)
        pid = adapter.read_session_id(adapter.session_path(self.cwd, "fix-planner", self.home))
        self.assertEqual(first["session_id"], pid)
        before = adapter.spend_path(self.cwd, pid, self.home).read_bytes()
        got = self.run_adapter(argv("works-node: plan-answer-lane-1 continue=fix-planner fork"), 0.6, 8400)
        fid = adapter.read_session_id(adapter.session_path(self.cwd, "plan-answer-lane-1", self.home))
        self.assertNotEqual(fid, pid)
        self.assertEqual(got["session_id"], fid)
        self.assertAlmostEqual(got["total_cost_usd"], 0.1, places=9)
        self.assertEqual(got["modelUsage"]["claude-sonnet-5-5"]["outputTokens"], 400)
        self.assertEqual(adapter.read_session_id(adapter.session_path(self.cwd, "fix-planner", self.home)), pid)
        self.assertEqual(adapter.spend_path(self.cwd, pid, self.home).read_bytes(), before)


class PlanSpendCase(unittest.TestCase):
    """plan が見せ直しに渡す (Archon が --resume に渡した会話, 包みが開いた会話)"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = pathlib.Path(self._tmp.name).resolve()
        self.home = self.tmp / "adapter-home"
        self.cwd = self.tmp / "wt"
        self.cwd.mkdir()

    def plan(self, args):
        return adapter.plan(args, self.cwd, self.home, "true", new_id=lambda: "new-id")

    def test_spend_from(self):
        self.assertEqual(self.plan(argv("works-node: fix")).spend_from, (None, None))
        self.assertEqual(self.plan(argv("works-node: fix", resume="r1") + ["--fork-session"]).spend_from, ("r1", "r1"))
        p = adapter.session_path(self.cwd, "fix", self.home)
        p.parent.mkdir(parents=True)
        p.write_text("fix-id\n", encoding="utf-8")
        self.assertEqual(self.plan(argv("works-node: fix-ruled continue=fix")).spend_from, (None, "fix-id"))
        self.assertEqual(self.plan(argv("works-node: fix-ruled continue=fix", resume="r2")).spend_from, ("r2", "fix-id"))
        self.assertEqual(self.plan(argv("works-node: fix self-resume", resume="r3")).spend_from, ("r3", "fix-id"))
        # 旗 fork: 子の会話は新しい id（写し）で、本当に継いだ元は X の会話
        q = adapter.session_path(self.cwd, "fix-planner", self.home)
        q.write_text("plan-id\n", encoding="utf-8")
        fork = self.plan(argv("works-node: plan-answer-lane-1 continue=fix-planner fork", resume="r4"))
        self.assertEqual(fork.session["id"], "new-id")
        self.assertEqual(fork.spend_from, ("r4", "plan-id"))

    def test_unmarked_has_no_spend_from(self):
        a = ["--output-format", "stream-json", "--tools", "", "--resume", "x"]
        self.assertIsNone(adapter.plan(a, self.cwd, self.home, "true").spend_from)


if __name__ == "__main__":
    unittest.main()
