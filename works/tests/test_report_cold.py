"""報告の書き手の出した物を初見の読み手が確かめ、redesign-needed なら書き手に戻す輪（blk-report の report-write-loop）。
初見の読み手が redesign-needed を返したのに、書き手に戻らずそのまま報告が出ていた（run 973869ae の判定）。

- YAML: report-write-loop の中に、書き手の返答の後で道具を持たない初見の読み手が居て、その返答が書き手の受け付けに渡る
- 受け付け（report_roles.accept）: 初見の読み手の redesign-needed は、書き手の返答を盤面へ渡さずに拒み、止まった所と推測で
  埋めた所を理由にする。上限の回（GIVE_UP_AFTER 回目）は受け取り、『初見の確かめを通っていない』印を残す
- 出口（report_roles.collect）: 印が在れば、報告の来歴の 1 行の直後に『初見の確かめを通っていない: <理由>』を出す
盤面は偽の盤面（作業ファイルの置き場と instance だけ）。entry.take は mock（盤面・git・子のプロセスなし。FAST）
"""
import importlib.util
import json
import pathlib
import sys
import tempfile
import types
import unittest
from unittest import mock

import yaml

sys.dont_write_bytecode = True
TESTS = pathlib.Path(__file__).resolve().parent
ROOT = TESTS.parent
BLK = ROOT / "blk-report"
for _p in (str(ROOT / ".shared" / "core"), str(BLK / "lib")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import report_roles as rr  # noqa: E402

WRITE_NODE = rr.NODE_OF[rr.WRITE]
COLD_NODE = rr.NODE_OF[rr.COLD]
STOP = "冒頭 3 行で何の話かが言えない（『さっきの件』が何を指すか本文に無い）"
GUESS = "『R3』が何かを推測で埋めた"
NOT_PASSED = "初見の確かめを通っていない"
WRITER_TEXT = "結論: 直した。\n\n人が決めること: 無い。\n"


def cold(verdict, stops=(), guessed=()):
    return json.dumps({"verdict": verdict, "stops": list(stops), "guessed": list(guessed),
                       "decidable": verdict == "pass"}, ensure_ascii=False)


def fake_board(tmp) -> types.SimpleNamespace:
    """報告の書き手の節（report）が待っている盤面。初見検査（report.cold_check）は済んでいる"""
    d = pathlib.Path(tmp)
    b = types.SimpleNamespace(dir=d, round=1, table=None,
                              state={"outputs": {}, "run_id": "run-1", "works": {"line": "darkfactory"}},
                              rd={"instances": {WRITE_NODE: {"attempts": 1, "status": "pending"}}, "done": {COLD_NODE: {}}})
    b.work = lambda name: d / "r1" / name
    (d / "r1").mkdir(parents=True, exist_ok=True)
    return b


def workflow():
    return yaml.safe_load((BLK / "blk-report.yaml").read_text(encoding="utf-8"))


class WriteLoopYamlCase(unittest.TestCase):
    def test_cold_reader_checks_writer_in_write_loop(self):
        """report-write-loop の中で、書き手の後に道具を持たない初見の読み手が走り、その返答が書き手の受け付けに渡る"""
        grp = next(n for n in workflow()["nodes"] if n["id"] == "report-write-loop")
        nodes = {n["id"]: n for n in grp["loop_group"]["nodes"]}
        readers = [n for n in nodes.values() if ("command" in n or "prompt" in n) and n["id"] != rr.WRITE]
        self.assertEqual(len(readers), 1, "書き手の輪に初見の読み手が居ない")
        reader = readers[0]
        self.assertEqual(reader.get("allowed_tools"), [], "初見の読み手は道具を持たない（X3）")
        self.assertIn(rr.WRITE, reader.get("depends_on") or [], "初見の読み手は書き手の返答の後に読む")
        self.assertEqual(set(reader["output_format"]["properties"]), {"verdict", "stops", "guessed", "decidable"})
        acc = nodes[f"{rr.WRITE}-accept"]
        self.assertIn(reader["id"], acc.get("depends_on") or [])
        self.assertIn(f"${reader['id']}.output", json.dumps(acc.get("with"), ensure_ascii=False),
                      "初見の読み手の返答が書き手の受け付けに渡らない")


class WriteAcceptColdCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.b = fake_board(self._tmp.name)
        self.take = mock.Mock(return_value={"ok": True, "reason": ""})
        for p in (mock.patch.object(rr, "open_board", return_value=self.b), mock.patch.object(rr.entry, "take", self.take)):
            p.start()
            self.addCleanup(p.stop)

    def tearDown(self):
        self._tmp.cleanup()

    def accept(self, verdict):
        try:
            return rr.accept(self._tmp.name, rr.WRITE, json.dumps({"text": WRITER_TEXT}, ensure_ascii=False), self._tmp.name,
                             cold=cold(verdict, [STOP], [GUESS]))
        except TypeError as e:
            self.fail(f"書き手の受け付けが初見の読み手の返答を受けない: {e}")

    def reject_before(self, n):
        rows = [{"node": WRITE_NODE, "attempt": i + 1, "at": "t", "reason": "前の拒否"} for i in range(n)]
        self.b.work(rr.REJECTS_NAME).write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")

    def marked(self) -> str:
        return "\n".join(p.read_text(encoding="utf-8") for p in pathlib.Path(self._tmp.name).rglob("*") if p.is_file())

    def test_redesign_needed_returns_writer(self):
        """redesign-needed → 書き手の返答を盤面へ渡さずに拒み、止まった所と推測で埋めた所が理由に在る"""
        got = self.accept("redesign-needed")
        self.assertIs(got["ok"], False, got)
        self.assertIs(got["done"], False)
        self.assertIn(STOP, got["reason"])
        self.assertIn(GUESS, got["reason"])
        self.take.assert_not_called()

    def test_script_empty_cold_is_not_passed(self):
        """scripts/accept.py: 書き手の輪で初見の読み手の返答が空で届いても確かめを飛ばさない（読めない返答として書き手に返す）。
        ほかの輪の空（cold: ""）は確かめない"""
        spec = importlib.util.spec_from_file_location("_report_cold_accept", BLK / "scripts" / "accept.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        env = {"INPUTS_ROLE": rr.WRITE, "INPUTS_REPLY": json.dumps({"text": WRITER_TEXT}, ensure_ascii=False), "INPUTS_COLD": ""}
        got = mod.run(self._tmp.name, self._tmp.name, env)
        self.assertIs(got["ok"], False, got)
        self.take.assert_not_called()
        self.assertIsNone(rr._cold_block(cold("pass")))
        with mock.patch.object(rr, "_cold_block", side_effect=AssertionError("ほかの輪で確かめた")):
            got = mod.run(self._tmp.name, self._tmp.name, {**env, "INPUTS_ROLE": rr.COLD,
                                                           "INPUTS_REPLY": cold("pass")})
        self.assertIs(got["ok"], True, got)

    def test_pass_is_taken(self):
        got = self.accept("pass")
        self.assertIs(got["ok"], True, got)
        self.take.assert_called_once()
        self.assertNotIn(NOT_PASSED, self.marked())

    def test_last_attempt_takes_and_marks(self):
        """上限の回（前に GIVE_UP_AFTER - 1 回拒んだ）の redesign-needed → 受け取って輪を抜け、印と理由を作業ファイルに残す"""
        self.reject_before(rr.GIVE_UP_AFTER - 1)
        got = self.accept("redesign-needed")
        self.assertEqual((got["ok"], got["done"]), (True, True), got)
        self.take.assert_called_once()
        self.assertIn(STOP, self.marked())

    def test_collect_heads_report_with_mark(self):
        """印が在れば、出口の報告の来歴の 1 行の直後に『初見の確かめを通っていない: <理由>』"""
        self.reject_before(rr.GIVE_UP_AFTER - 1)
        self.accept("redesign-needed")
        self.b.rd["done"][WRITE_NODE] = {}
        self.b.state["outputs"][WRITE_NODE] = {"round": 1, "file": "out/r1/report.json"}
        self.b.output_of_round = lambda nid, rnd: ({"text": WRITER_TEXT} if nid == WRITE_NODE else
                                                   json.loads(cold("redesign-needed", [STOP], [GUESS])))
        self.b.work(rr.FACTS_NAME).write_text("- 周: 1\n", encoding="utf-8")
        out = rr.collect(self._tmp.name)
        lines = [x for x in pathlib.Path(out["report_file"]).read_text(encoding="utf-8").splitlines() if x.strip()]
        self.assertEqual(lines[0], rr.stamp(self.b))
        self.assertTrue(lines[1].startswith(NOT_PASSED), lines[:3])
        self.assertIn(STOP, lines[1])


if __name__ == "__main__":
    unittest.main()
