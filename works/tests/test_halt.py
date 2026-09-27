"""止め札（.shared/core/halt.py と dev/stop.sh）の検査（線 A の仕様 5.3・計画 Task 8）。

- halt.place: 理由が空・空白だけなら書かない。最初の理由が正（2 度目は上書きせず trace にだけ積む）。
  中身 {reason, by, at} を一時ファイルから書き、一時ファイルを残さない。trace の行は DiskBoard の trace と同じ形 {t, op, …}
- halt.seen: STOP の中身。無ければ None。人が手で置いた読めない STOP（OS の段で読めない物も）も「止める」と読み、例外を上げない。
  by が無ければ HAND_PLACED_BY。trace に積めなくても STOP を置けたら ok（警告付き）。同時に置いても最初の理由が正（R43 の os.link）
- halt.over: 盤面がもう止まった・終わった（cmd_stop の refuse_if_over と同じ判定）
- dev/stop.sh <run-id> <理由…>: 盤面の場所を `archon workflow get <run> --json` の output_root + artifacts/runs/<run-id>/board
  で組む（走っている run には $ARTIFACTS_DIR の欄が無い。試し P12）。理由が無い・board/ が無い・別の run が返った・
  終わった run（completed・cancelled）・盤面がもう止まった・終わった・get が失敗した、のどれも何も書かずに 2。Archon は WORKS_DEV_ARCHON の偽物を差す
"""
import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
CORE = ROOT / ".shared" / "core"
EVENTS = ROOT / "tests" / "events"
STOP_SH = ROOT / "dev" / "stop.sh"
sys.path.insert(0, str(CORE))

import halt  # noqa: E402

RUN_ID = json.loads((EVENTS / "get-running.json").read_text(encoding="utf-8"))["id"]


def trace_rows(board):
    p = board / "trace.jsonl"
    return [json.loads(line) for line in p.read_text(encoding="utf-8").splitlines()] if p.exists() else []


class TestPlace(unittest.TestCase):
    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp)
        self.board = self.tmp / "board"
        self.board.mkdir()

    def test_place_requires_reason(self):
        for reason in ("", "  ", "\n\t"):
            self.assertEqual(halt.place(self.board, reason, "alice"), {"ok": False, "reason": "理由が要る"})
        self.assertFalse((self.board / halt.STOP_FILE).exists())
        self.assertEqual(trace_rows(self.board), [])
        self.assertIsNone(halt.seen(self.board))

    def test_place_requires_by(self):
        self.assertFalse(halt.place(self.board, "止めたい", " ")["ok"])
        self.assertFalse((self.board / halt.STOP_FILE).exists())

    def test_first_reason_wins(self):
        self.assertEqual(halt.place(self.board, "  依頼が変わった  ", "alice"), {"ok": True, "first": True})
        self.assertEqual(halt.place(self.board, "やっぱり別の理由", "bob"), {"ok": True, "first": False})
        got = halt.seen(self.board)
        self.assertEqual((got["reason"], got["by"]), ("依頼が変わった", "alice"))
        self.assertTrue(got["at"])
        rows = trace_rows(self.board)
        self.assertEqual([(r["op"], r["reason"], r["by"], r["first"]) for r in rows],
                         [("stop_flag", "依頼が変わった", "alice", True), ("stop_flag", "やっぱり別の理由", "bob", False)])
        for r in rows:   # DiskBoard の trace と同じ行の形（t と op が頭）
            self.assertEqual(list(r)[:2], ["t", "op"])

    def test_place_keeps_board_trace(self):
        (self.board / "trace.jsonl").write_text('{"t": "x", "op": "init"}\n', encoding="utf-8")
        halt.place(self.board, "止める", "alice")
        self.assertEqual([r["op"] for r in trace_rows(self.board)], ["init", "stop_flag"])

    def test_place_atomic(self):
        halt.place(self.board, "一度目", "alice")
        halt.place(self.board, "二度目", "alice")
        self.assertEqual(sorted(p.name for p in self.board.iterdir()), ["STOP", "trace.jsonl"])
        doc = json.loads((self.board / "STOP").read_text(encoding="utf-8"))
        self.assertEqual(set(doc), {"reason", "by", "at"})

    def test_place_does_not_overwrite_hand_placed_flag(self):
        (self.board / "STOP").write_text("手で置いた", encoding="utf-8")
        self.assertEqual(halt.place(self.board, "後から", "alice"), {"ok": True, "first": False})
        self.assertEqual((self.board / "STOP").read_text(encoding="utf-8"), "手で置いた")

    def test_seen(self):
        self.assertIsNone(halt.seen(self.board))
        halt.place(self.board, "理由", "alice")
        self.assertEqual(halt.seen(self.board)["reason"], "理由")

    def test_seen_unreadable_flag_still_stops(self):
        # 人が手で置いた STOP（試し P12 の形の手書きも含む）は、読めなくても「止める」と読む（黙って走り続けない）
        for text in ("{壊れた", "[]", '{"reason": "  "}'):
            (self.board / "STOP").write_text(text, encoding="utf-8")
            got = halt.seen(self.board)
            self.assertIsNotNone(got, text)
            self.assertTrue(got["reason"].strip(), text)
            self.assertIn("by", got)
            self.assertEqual(got["by"], halt.HAND_PLACED_BY, text)
        (self.board / "STOP").write_text('{"reason": "probe P12 stop", "by": "p12.py"}', encoding="utf-8")
        self.assertEqual(halt.seen(self.board), {"reason": "probe P12 stop", "by": "p12.py", "at": None})
        # by の無い・空の手書きの STOP も、境の節が DiskBoard.stop(理由, by) にそのまま渡せる by を持つ
        for text in ('{"reason": "手で止めた"}', '{"reason": "手で止めた", "by": "  "}', '{"reason": "手で止めた", "by": 3}'):
            (self.board / "STOP").write_text(text, encoding="utf-8")
            self.assertEqual(halt.seen(self.board)["by"], halt.HAND_PLACED_BY, text)

    def test_seen_never_raises_on_os_level_failure(self):
        # 中身が UTF-8 でない・ディレクトリ・読む権限が無い: どれも例外を上げず「止める」と読む
        stop = self.board / "STOP"
        stop.write_bytes(b"\xff\xfe\x00bad")
        self.assertTrue(halt.seen(self.board)["unreadable"])
        stop.unlink()
        stop.mkdir()
        self.assertTrue(halt.seen(self.board)["unreadable"])
        stop.rmdir()
        stop.write_text('{"reason": "x", "by": "y"}', encoding="utf-8")
        stop.chmod(0)
        self.addCleanup(stop.chmod, 0o644)
        if os.access(stop, os.R_OK):   # root で回すと読めてしまう
            self.skipTest("権限を外しても読める（root）")
        got = halt.seen(self.board)
        self.assertTrue(got["unreadable"])
        self.assertIn("PermissionError", got["reason"])
        self.assertEqual(got["by"], halt.HAND_PLACED_BY)

    def test_trace_failure_after_placing_is_a_warning(self):
        # 正は STOP。置いた後に trace へ積めなくても ok（警告付き）。2 度目は何も残らないので ok False
        (self.board / "trace.jsonl").mkdir()
        got = halt.place(self.board, "止める", "alice")
        self.assertEqual((got["ok"], got["first"]), (True, True))
        self.assertIn("trace", got["warning"])
        self.assertEqual(halt.seen(self.board)["reason"], "止める")
        got = halt.place(self.board, "二度目", "alice")
        self.assertFalse(got["ok"])
        self.assertEqual(halt.seen(self.board)["reason"], "止める")
        self.assertEqual(sorted(p.name for p in self.board.iterdir()), ["STOP", "trace.jsonl"])

    def test_concurrent_place_first_reason_wins(self):
        # 8 つのプロセスが同時に置く: first True はちょうど 1 つで、STOP の理由はその 1 つの物。全員 ok、trace は 8 行
        go = self.tmp / "go"
        code = ("import os, pathlib, sys, time, json\n"
                "sys.dont_write_bytecode = True\n"
                f"sys.path.insert(0, {str(CORE)!r})\n"
                "import halt\n"
                f"go = pathlib.Path({str(go)!r})\n"
                "while not go.exists():\n"
                "    time.sleep(0.001)\n"
                f"print(json.dumps(halt.place({str(self.board)!r}, sys.argv[1], 'p' + sys.argv[1])))\n")
        env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
        procs = [subprocess.Popen([sys.executable, "-c", code, f"理由{i}"], stdout=subprocess.PIPE, text=True, encoding="utf-8", env=env)
                 for i in range(8)]
        go.touch()
        outs = [(p.communicate()[0], p.returncode) for p in procs]
        self.assertEqual([rc for _, rc in outs], [0] * 8)
        got = [json.loads(o) for o, _ in outs]
        self.assertTrue(all(g["ok"] for g in got), got)
        winners = [i for i, g in enumerate(got) if g["first"]]
        self.assertEqual(len(winners), 1, got)
        self.assertEqual(halt.seen(self.board)["reason"], f"理由{winners[0]}")
        rows = trace_rows(self.board)
        self.assertEqual(sorted(r["reason"] for r in rows), sorted(f"理由{i}" for i in range(8)))
        self.assertEqual([r["reason"] for r in rows if r["first"]], [f"理由{winners[0]}"])
        self.assertEqual(sorted(p.name for p in self.board.iterdir()), ["STOP", "trace.jsonl"])

    def test_over(self):
        self.assertIsNone(halt.over(self.board))   # state.json が無い
        state = self.board / "state.json"
        for doc, word in (({"status": "stopped"}, "stopped"), ({"status": "converged"}, "converged"),
                          ({"status": "running", "halted": {"by": "gate", "node": "p2.human_gate"}}, "gate")):
            state.write_text(json.dumps(doc), encoding="utf-8")
            self.assertIn(word, halt.over(self.board) or "", doc)
        for text in ('{"status": "running"}', "{壊れた", "[]"):
            state.write_text(text, encoding="utf-8")
            self.assertIsNone(halt.over(self.board), text)


class TestStopSh(unittest.TestCase):
    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp)
        self.root = self.tmp / "workspaces" / "proj"
        self.board = self.root / "artifacts" / "runs" / RUN_ID / "board"
        self.calls = self.tmp / "calls.txt"

    def fake_archon(self, sample="get-running.json", exit_code=0, **edit):
        """偽の Archon の殻: 引数を calls.txt に積み、見本の JSON（output_root をこの試験の置き場に替えた物）を出す"""
        doc = json.loads((EVENTS / sample).read_text(encoding="utf-8"))
        doc["output_root"] = str(self.root)
        doc.update(edit)
        out = self.tmp / "get.json"
        out.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
        fake = self.tmp / "fake-archon.sh"
        fake.write_text("#!/bin/sh\n"
                        f'printf \'%s|%s\\n\' "${{WORKS_DEV_NO_AUTH:-}}" "$*" >> "{self.calls}"\n'
                        f'cat "{out}"\nexit {exit_code}\n')
        return fake

    def run_stop(self, *args, fake=None, user="alice"):
        env = dict(os.environ, WORKS_DEV_ARCHON=str(fake or self.fake_archon()), USER=user, PYTHONDONTWRITEBYTECODE="1")
        return subprocess.run(["sh", str(STOP_SH), *args], capture_output=True, text=True, encoding="utf-8", env=env)

    def calls_made(self):
        return self.calls.read_text().splitlines() if self.calls.exists() else []

    def test_stop_sh_refuses_empty_reason(self):
        self.board.mkdir(parents=True)
        for args in ((RUN_ID,), (RUN_ID, ""), (RUN_ID, "  ", " "), ()):
            r = self.run_stop(*args)
            self.assertEqual(r.returncode, 2, (args, r.stdout, r.stderr))
            self.assertTrue(r.stderr.strip(), args)
        self.assertEqual(sorted(p.name for p in self.board.iterdir()), [])
        self.assertEqual(self.calls_made(), [])   # 理由が無ければ Archon も呼ばない

    def test_stop_sh_board_from_output_root(self):
        self.board.mkdir(parents=True)
        r = self.run_stop(RUN_ID, "依頼が", "変わった")
        self.assertEqual(r.returncode, 0, r.stderr)
        doc = json.loads((self.board / "STOP").read_text(encoding="utf-8"))
        self.assertEqual((doc["reason"], doc["by"]), ("依頼が 変わった", "alice"))
        self.assertIn(str(self.board / "STOP"), r.stdout)
        # 問い合わせは認証を読ませずに get --json
        self.assertEqual(self.calls_made(), [f"1|workflow get {RUN_ID} --json"])
        self.assertEqual(sorted(p.name for p in self.board.iterdir()), ["STOP", "trace.jsonl"])

    def test_stop_sh_second_reason_goes_to_trace(self):
        self.board.mkdir(parents=True)
        self.assertEqual(self.run_stop(RUN_ID, "一度目").returncode, 0)
        r = self.run_stop(RUN_ID, "二度目", user="bob")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("一度目", r.stdout)   # 正になっている最初の理由を見せる
        self.assertEqual(halt.seen(self.board)["reason"], "一度目")
        self.assertEqual([(x["reason"], x["by"], x["first"]) for x in trace_rows(self.board)],
                         [("一度目", "alice", True), ("二度目", "bob", False)])

    def test_stop_sh_refuses_missing_board(self):
        self.board.parent.mkdir(parents=True)   # run の置き場は在るが board/ が無い
        r = self.run_stop(RUN_ID, "止める")
        self.assertEqual(r.returncode, 2, r.stdout)
        self.assertIn(str(self.board), r.stderr)
        self.assertFalse(self.board.exists())
        self.assertEqual(sorted(p.name for p in self.board.parent.iterdir()), [])

    def test_stop_sh_refuses_board_already_over(self):
        # Archon ではまだ running でも、盤面がもう止まった・終わった（report の節が走っている間・関所で stop した後）なら置かない
        self.board.mkdir(parents=True)
        for doc in ({"status": "stopped"}, {"status": "converged"}, {"status": "running", "halted": {"by": "stop"}}):
            (self.board / "state.json").write_text(json.dumps(doc), encoding="utf-8")
            r = self.run_stop(RUN_ID, "止める")
            self.assertEqual(r.returncode, 2, (doc, r.stdout))
            self.assertEqual(len(r.stderr.strip().splitlines()), 1, r.stderr)
            self.assertIn("止める物が無い", r.stderr)
            self.assertEqual(sorted(p.name for p in self.board.iterdir()), ["state.json"])
        (self.board / "state.json").write_text('{"status": "running"}', encoding="utf-8")
        self.assertEqual(self.run_stop(RUN_ID, "止める").returncode, 0)
        self.assertTrue((self.board / "STOP").exists())

    def test_stop_sh_trace_failure_warns_but_succeeds(self):
        self.board.mkdir(parents=True)
        (self.board / "trace.jsonl").mkdir()
        r = self.run_stop(RUN_ID, "止める")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("警告", r.stderr)
        self.assertIn("止め札を置いた", r.stdout)
        self.assertEqual(halt.seen(self.board)["reason"], "止める")

    def test_stop_sh_refuses_without_output_root(self):
        self.board.mkdir(parents=True)
        for edit in ({"output_root": None}, {"output_root": "relative/root"}):
            r = self.run_stop(RUN_ID, "止める", fake=self.fake_archon(**edit))
            self.assertEqual(r.returncode, 2, (edit, r.stderr))
        self.assertEqual(list(self.board.iterdir()), [])

    def test_stop_sh_refuses_other_run(self):
        # get が別の run を返した・run id に / を含む: 組んだ場所を信じずに止まる
        self.board.mkdir(parents=True)
        r = self.run_stop(RUN_ID, "止める", fake=self.fake_archon(id="0000-other"))
        self.assertEqual(r.returncode, 2, r.stderr)
        r = self.run_stop(f"../{RUN_ID}", "止める", fake=self.fake_archon(id=f"../{RUN_ID}"))
        self.assertEqual(r.returncode, 2, r.stderr)
        self.assertEqual(list(self.board.iterdir()), [])

    def test_stop_sh_refuses_finished_run(self):
        # 終わった run（completed・cancelled）は止め札を見る境の節がもう来ない。failed は resume できるので置く
        self.board.mkdir(parents=True)
        for status in ("completed", "cancelled"):
            r = self.run_stop(RUN_ID, "止める", fake=self.fake_archon("get-finished.json", status=status))
            self.assertEqual(r.returncode, 2, (status, r.stdout))
            self.assertIn(status, r.stderr)
        self.assertEqual(list(self.board.iterdir()), [])
        r = self.run_stop(RUN_ID, "止める", fake=self.fake_archon("get-finished.json", status="failed"))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue((self.board / "STOP").exists())

    def test_stop_sh_refuses_when_get_fails(self):
        self.board.mkdir(parents=True)
        for fake in (self.fake_archon(exit_code=1), self._fake_text("not json")):
            r = self.run_stop(RUN_ID, "止める", fake=fake)
            self.assertEqual(r.returncode, 2, r.stderr)
        self.assertEqual(list(self.board.iterdir()), [])

    def _fake_text(self, text):
        fake = self.tmp / "fake-text.sh"
        fake.write_text(f"#!/bin/sh\necho '{text}'\n")
        return fake


class TestSamples(unittest.TestCase):
    def test_get_samples_have_output_root(self):
        # 走っている run には $ARTIFACTS_DIR の欄が無く output_root だけ。終わった run の artifacts.root は output_root から組んだ場所
        run = json.loads((EVENTS / "get-running.json").read_text(encoding="utf-8"))
        fin = json.loads((EVENTS / "get-finished.json").read_text(encoding="utf-8"))
        self.assertEqual(run["status"], "running")
        self.assertIsNone(run["terminal_record"])
        self.assertNotIn("/artifacts/runs/", json.dumps(run))
        self.assertEqual(fin["terminal_record"]["artifacts"]["root"],
                         os.path.join(fin["output_root"], "artifacts", "runs", fin["id"]))


if __name__ == "__main__":
    unittest.main()
