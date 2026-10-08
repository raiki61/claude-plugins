"""下請けの会話が親の節の返答の道具に書いた返答を拾う口（.shared/core/diverted.py・record-output.py・包みのフック）と、
局所レビューの受け付け（blk-material の take）がそれで /code-review の所見を戻す振る舞いの検査（FAST: 一時の置き場のファイルと
記録器を子で 1 本ずつ起こすだけ。git・盤面の再生を使わない）。

実測（2026-10-08、利用者の run f57a5374 ほか 6 つの works の家）: 組み込みの skill code-review は fork（下請けの会話）で走り、
節の --json-schema が足す道具 StructuredOutput を継いで、所見をそこに書いて終わる（19 本の全部。schema の検査も親と同じ）。
Skill の結果は『Skill execution completed』だけになり、局所レビューの役は /code-review の行を items 空で返していた
（run f57a5374 では 10 件の所見が消え、うち 1 件は 2 run 後に阻害になった）。本文で返せと args に書いた 6 本も同じだった。
"""
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parents[1]
CORE = ROOT / ".shared" / "core"
sys.dont_write_bytecode = True
sys.path.insert(0, str(CORE))
sys.path.insert(0, str(ROOT / "blk-material" / "lib"))

import adapter  # noqa: E402
import diverted  # noqa: E402
import hermetic  # noqa: E402
import material  # noqa: E402

RECORDER = CORE / "record-output.py"
SESSION = "fc9d63e1-0a5d-4134-99db-ba74d7716b4d"
LENSES = [{"skill": "/code-review", "required": True}, {"skill": "pr-review-toolkit:code-reviewer", "required": True},
          {"skill": "/simplify", "required": True},
          {"skill": "/security-review", "required": False, "applies_cond": "security_surface_touched"}]
ITEM = {"where": "app/compute_logs.py:27", "text": "親の __init__ を呼ばず _download_urls が未初期化",
        "mechanism": "親の download_url_for_type が self._download_urls を読む", "measured": "AttributeError を確かめた",
        "false_positive_if": "画面が capturedLogsMetadata を投げない版"}
ITEM2 = {"where": "deploy/values.yaml:174", "text": "常設環境に漏れる"}
LOST = "起こしたが fork 実行の結果が本文なし（Skill execution completed のみ）で、所見を受け取れなかった。"


def payload(items, label="code-review"):
    """fork が StructuredOutput に書いた形（節の schema のまま。実物の f57a5374 の形を縮めた物）"""
    return {"material": {"status": "found", "count": len(items), "detail": "8 観点で走査した"},
            "findings": [{"skill": label, "items": items}], "simplify_carried": False}


def reply(code_review_items=(), failed=LOST, status="clean"):
    rows = [{"skill": e["skill"], "items": [], "invoked": True, "failed": "起こしたが所見なし（差分を見た）"} for e in LENSES]
    rows[0].update(items=list(code_review_items), failed=failed)
    material_ = {"status": status, "checked": "差分を見た"} if status == "clean" else \
        {"status": status, "count": 3, "detail": "code-reviewer が 3 件"}
    return {"material": material_, "simplify_carried": False, "findings": rows}


class HookCase(unittest.TestCase):
    """記録器（PostToolUse:StructuredOutput）: 下請けの中の呼び出し（agent_id が在る）だけを、入力のまま 1 行残す"""

    def run_recorder(self, sink, event):
        return subprocess.run([sys.executable, str(RECORDER), str(sink)], input=json.dumps(event, ensure_ascii=False),
                              text=True, encoding="utf-8", capture_output=True,
                              env=hermetic.child_env(PYTHONDONTWRITEBYTECODE="1"))

    def test_subagent_structured_output_is_recorded_with_its_input(self):
        with tempfile.TemporaryDirectory() as td:
            sink = pathlib.Path(td)
            ev = {"tool_name": "StructuredOutput", "tool_input": payload([ITEM]), "session_id": SESSION,
                  "agent_id": "a66cd6043ee1315d6", "agent_type": "general-purpose", "tool_use_id": "toolu_01Fmxu3pa6z9"}
            r = self.run_recorder(sink, ev)
            self.assertEqual((r.returncode, r.stdout), (0, ""), r.stderr)
            rows = [json.loads(ln) for ln in (sink / diverted.OUTPUTS_LOG).read_text(encoding="utf-8").splitlines()]
            self.assertEqual(len(rows), 1)
            self.assertEqual({k: rows[0][k] for k in ("session_id", "agent_id", "tool_use_id", "input")},
                             {"session_id": SESSION, "agent_id": "a66cd6043ee1315d6", "tool_use_id": "toolu_01Fmxu3pa6z9",
                              "input": payload([ITEM])})
            self.assertTrue(rows[0]["ts"].endswith("+00:00"), rows[0]["ts"])

    def test_parent_call_other_tools_and_no_sink_write_nothing(self):
        with tempfile.TemporaryDirectory() as td:
            sink = pathlib.Path(td) / "sink"
            ev = {"tool_name": "StructuredOutput", "tool_input": payload([]), "session_id": SESSION, "agent_id": "a1"}
            self.assertEqual(self.run_recorder(sink, ev).returncode, 0)
            self.assertFalse(sink.exists(), "置き場が無ければ 1 バイトも書かない")
            sink.mkdir()
            for e in ({**ev, "agent_id": None}, {k: v for k, v in ev.items() if k != "agent_id"},
                      {**ev, "tool_name": "Read"}, {**ev, "tool_input": "not a dict"}, "not json"):
                self.assertEqual(self.run_recorder(sink, e).returncode, 0)
            self.assertEqual(list(sink.iterdir()), [], "親の自分の返答・ほかの道具・読めない入力は残さない")

    def test_wrapper_adds_the_hook(self):
        post = adapter.hook_settings("py r.py s", "py w.py s", output_command="py o.py s")["hooks"]["PostToolUse"]
        self.assertEqual([m["matcher"] for m in post], ["Read", "Edit|Write|NotebookEdit", "StructuredOutput"])
        self.assertEqual(post[2]["hooks"], [{"type": "command", "command": "py o.py s"}])
        self.assertEqual(diverted.log_path("/x", "/h"), adapter.reads_dir("/x", "/h") / diverted.OUTPUTS_LOG)
        src = (CORE / "claude-adapter").read_text(encoding="utf-8")
        self.assertIn('"record-output.py"', src, "包みが記録器のコマンドを渡す")
        self.assertIn("output_command=adapter.hook_command(sys.executable, OUTPUT_RECORDER, sink)", src)


class ReadCase(unittest.TestCase):
    def test_reads_only_this_session_since_the_launch(self):
        with tempfile.TemporaryDirectory() as td:
            home, repo = pathlib.Path(td) / "h", pathlib.Path(td) / "repo"
            p = diverted.log_path(repo, home)
            p.parent.mkdir(parents=True)
            rows = [{"ts": "2026-10-07T23:40:00+00:00", "session_id": SESSION, "agent_id": "a0", "input": payload([ITEM2])},
                    {"ts": "2026-10-08T00:30:17+00:00", "session_id": SESSION, "agent_id": "a1", "input": payload([ITEM])},
                    {"ts": "2026-10-08T00:30:18+00:00", "session_id": "other", "agent_id": "a2", "input": payload([ITEM2])},
                    {"ts": "2026-10-08T00:30:19+00:00", "session_id": SESSION, "agent_id": "a3", "input": "x"}]
            p.write_text("\n".join(json.dumps(r) for r in rows) + "\nnot json\n", encoding="utf-8")
            got = diverted.read_outputs(repo, SESSION, "2026-10-08T08:42:34+09:00", home)
            self.assertEqual(got, [payload([ITEM])], "前の周（起動より前）・別の会話・形の違う行は読まない")
            self.assertEqual(diverted.read_outputs(repo, None, None, home), [], "会話の id が分からなければ拾わない")
            self.assertEqual(diverted.read_outputs(pathlib.Path(td) / "none", SESSION, None, home), [])


class RecoverCase(unittest.TestCase):
    def test_lost_code_review_findings_come_back_from_the_fork_record(self):
        out, notes = diverted.recover(reply(), LENSES, [payload([ITEM, ITEM2]), payload([ITEM])])
        row = out["findings"][0]
        self.assertEqual(row["items"], [ITEM, ITEM2], "fork の所見を戻す（2 本の fork の重なりは 1 件に）")
        self.assertTrue(row["invoked"])
        self.assertIn("戻した", row["failed"])
        self.assertEqual(out["material"], {"status": "found", "count": 2, "detail": mock.ANY}, "clean のままにしない")
        self.assertIn("/code-review", out["material"]["detail"])
        self.assertEqual(notes["recovered"], [{"lens": "/code-review", "count": 2}])
        self.assertEqual(notes["unseen"], [])
        self.assertEqual(reply()["findings"][0]["items"], [], "受けた返答は書き換えない（写しを返す）")

    def test_found_material_counts_the_recovered_items(self):
        out, _ = diverted.recover(reply(status="found"), LENSES, [payload([ITEM])])
        self.assertEqual((out["material"]["status"], out["material"]["count"]), ("found", 4))

    def test_lost_without_record_is_marked_unseen_not_nothing_found(self):
        for failed in (LOST, "起こしたが所見なし（スキルは結果本文を返さずに完了）"):
            with self.subTest(failed):
                out, notes = diverted.recover(reply(failed=failed), LENSES, [])
                row = out["findings"][0]
                self.assertTrue(row["failed"].startswith(diverted.UNSEEN_TAG), row)
                self.assertIn(failed, row["failed"], "役の文は残す")
                self.assertEqual(notes["unseen"], ["/code-review"])
                self.assertIn(diverted.UNSEEN_TAG, out["material"]["checked"])

    def test_fork_that_found_nothing_is_confirmed_empty(self):
        out, notes = diverted.recover(reply(), LENSES, [payload([])])
        self.assertEqual(out["findings"][0]["items"], [])
        self.assertFalse(out["findings"][0]["failed"].startswith(diverted.UNSEEN_TAG))
        self.assertEqual((notes["unseen"], notes["empty"]), ([], ["/code-review"]))

    def test_fork_rows_for_inline_lenses_do_not_confirm_them(self):
        """fork が /simplify の行も items 空で書いても、親の会話で走った /simplify に『fork の記録で 0 件を確かめた』と付けない"""
        p = payload([ITEM])
        p["findings"].append({"skill": "simplify", "items": []})
        out, notes = diverted.recover(reply(), LENSES, [p])
        self.assertEqual(out["findings"][2]["failed"], "起こしたが所見なし（差分を見た）")
        self.assertEqual(notes["empty"], [])

    def test_fork_items_for_inline_lenses_do_not_fill_their_empty_rows(self):
        """fork が /simplify の行に所見を書いても、親の会話で走った /simplify の空の行は埋めない（戻すのは FORK_LENSES だけ。
        親の会話で走ったレンズの 0 件は役の申告のまま）"""
        p = payload([ITEM])
        p["findings"].append({"skill": "simplify", "items": [ITEM2]})
        out, notes = diverted.recover(reply(), LENSES, [p])
        self.assertEqual(out["findings"][2]["items"], [])
        self.assertEqual(out["findings"][2]["failed"], "起こしたが所見なし（差分を見た）")
        self.assertEqual(notes["recovered"], [{"lens": "/code-review", "count": 1}])
        self.assertEqual(out["material"]["count"], 1, "戻した /code-review の 1 件だけを数える")

    def test_rows_with_items_and_inline_lenses_are_left_alone(self):
        out, notes = diverted.recover(reply(code_review_items=[ITEM2], failed=""), LENSES, [payload([ITEM])])
        self.assertEqual(out["findings"][0]["items"], [ITEM2], "役が受け取った本文を差し替えない")
        self.assertEqual(out["findings"][2]["failed"], "起こしたが所見なし（差分を見た）", "/simplify は fork しない（0 件は 0 件）")
        self.assertEqual(notes, {"recovered": [], "empty": [], "unseen": [], "unmatched": []})

    def test_labels_name_the_lens_with_or_without_slash_and_others_are_unmatched(self):
        out, notes = diverted.recover(reply(), LENSES, [payload([ITEM], label="/code-review"), payload([ITEM2], label="review")])
        self.assertEqual(out["findings"][0]["items"], [ITEM])
        self.assertEqual(notes["unmatched"], ["review"])

    def test_items_keep_only_schema_keys(self):
        bad = [{**ITEM, "measured_note": "x"}, {"where": "a.py:1"}, "x"]
        out, _ = diverted.recover(reply(), LENSES, [payload(bad)])
        self.assertEqual(out["findings"][0]["items"], [ITEM], "型に無い鍵は落とし、where と text の無い項目は捨てる")


class MatBoard:
    """material.take が触る欄だけを持つ盤面の偽物（節 p1.local_review が待っている周 1。起こした印は利用者の run の時刻）"""

    def __init__(self, root: pathlib.Path):
        self.dir = root / "board"
        self.round = 1
        self.graph = {"nodes": {"p1.local_review": {"skills": LENSES}}}
        self.rd = {"instances": {"p1.local_review": {"node": "p1.local_review", "status": "pending", "attempts": 1,
                                                     "skills": LENSES, "launched_at": "2026-10-08T08:42:34+09:00"}}}
        self.loop_state = {}
        self.taken = []

    def work(self, name):
        p = self.dir / f"r{self.round}" / name
        p.parent.mkdir(parents=True, exist_ok=True)
        return p

    def output_of_round(self, nid, rnd):
        return None

    def done(self, nid, reply_):
        self.taken.append((nid, reply_))


class TakeCase(unittest.TestCase):
    """局所レビューの受け付けが、/code-review の消えた所見を包みの記録から戻して盤面に渡し、戻せなければ見ていないと書く"""

    def setUp(self):
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        self.tmp = pathlib.Path(td.name)
        self.home, self.repo = self.tmp / "adapter-home", self.tmp / "repo"
        self.b = MatBoard(self.tmp)
        self.b.work(material.SNAPSHOT).write_text(json.dumps({k: None for k in material.TREE_KEYS}), encoding="utf-8")
        cfg = self.tmp / "cfg"
        (cfg / "plugins").mkdir(parents=True)
        (cfg / "plugins" / "installed_plugins.json").write_text(json.dumps({"plugins": {"pr-review-toolkit@x": []}}),
                                                                encoding="utf-8")
        for name, value in (("_locked", lambda *a, **k: mock.MagicMock()), ("_open", lambda *a, **k: self.b),
                            ("_stopped", lambda b: None), ("_refuse_halted", lambda b: None),
                            ("_waiting", lambda b, nid: None), ("tree_moved", lambda *a, **k: [])):
            p = mock.patch.object(material, name, value)
            p.start()
            self.addCleanup(p.stop)
        env = mock.patch.dict(os.environ, {"WORKS_ADAPTER_HOME": str(self.home), "CLAUDE_CONFIG_DIR": str(cfg)})
        env.start()
        self.addCleanup(env.stop)

    def launched(self, session, at="2026-10-08T08:42:34.500000+09:00", node="local-review"):
        """包みの起動の記録の 1 行と、会話の id の記録（包みは起動ごとに上書きする）"""
        sid = adapter.session_path(self.repo, node, self.home)
        sid.parent.mkdir(parents=True, exist_ok=True)
        sid.write_text(session + "\n", encoding="utf-8")
        p = adapter.launches_path(self.repo, self.home)
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "a", encoding="utf-8") as f:
            f.write(json.dumps({"at": at, "node": node, "mode": "merged", "session": {"mode": "new", "id": session}}) + "\n")

    def record(self, *payloads, session=SESSION, writer=SESSION):
        self.launched(session)
        p = diverted.log_path(self.repo, self.home)
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "a", encoding="utf-8") as f:
            f.write("".join(json.dumps({"ts": "2026-10-08T00:30:17+00:00", "session_id": writer, "agent_id": f"a{i}",
                                        "input": x}) + "\n" for i, x in enumerate(payloads)))

    def take(self, r):
        return material.take(self.b.dir, "local-review", r, self.repo, "optional")

    def test_recovered_findings_reach_the_board(self):
        self.record(payload([ITEM]))
        out = self.take(reply())
        self.assertTrue(out["ok"], out)
        (_, got), = self.b.taken
        self.assertEqual(got["findings"][0]["items"], [ITEM])
        doc = json.loads(self.b.work(diverted.LENS_FILE).read_text(encoding="utf-8"))
        self.assertEqual(doc["recovered"], [{"lens": "/code-review", "count": 1}])

    def test_unrecovered_loss_is_taken_but_said_unseen(self):
        out = self.take(reply())
        self.assertTrue(out["ok"], "起こし直しても同じ形で落ちる（実測）ので拒まない")
        (_, got), = self.b.taken
        self.assertTrue(got["findings"][0]["failed"].startswith(diverted.UNSEEN_TAG))
        doc = json.loads(self.b.work(diverted.LENS_FILE).read_text(encoding="utf-8"))
        self.assertEqual(doc["unseen"], ["/code-review"])
        lines = diverted.report_lines(self.b.dir)
        self.assertEqual(len(lines), 1, lines)
        self.assertIn("/code-review", lines[0])
        self.assertIn("見ていない", lines[0])

    def test_other_session_records_are_not_used(self):
        """別の役・前の周の会話（この周に起こしたこの役の会話でない）の行は拾わない"""
        self.launched(SESSION, at="2026-10-08T08:00:00.000000+09:00")   # 前の周の起動（起こした印より前）。所見はこの会話の物
        self.record(payload([ITEM]), session="another-session")          # この周の起動は別の会話
        self.launched("judge-session", node="judge")
        self.take(reply())
        (_, got), = self.b.taken
        self.assertEqual(got["findings"][0]["items"], [])

    def test_retry_in_a_forked_session_still_recovers_the_first_attempt(self):
        """拒まれて起こし直された 2 回目は、Archon の輪が --resume --fork-session で起こすので会話の id が替わる（包みが新しい
        id を記録を上書きする）。1 回目の fork が書いた所見も、この周に起こしたこの役の会話の分として戻す（審査で見つけた穴）"""
        self.record(payload([ITEM]))                            # 1 回目の会話 SESSION の fork が書いた
        bad = reply()
        bad["findings"] = bad["findings"][1:]                   # /code-review の行が無い → 受け付けが拒む
        self.assertFalse(self.take(bad)["done"])
        self.assertFalse(self.b.work(diverted.LENS_FILE).exists(), "拒んだ返答の控えは書かない")
        self.launched("second-session", at="2026-10-08T08:50:00.000000+09:00")
        out = self.take(reply())
        self.assertTrue(out["ok"], out)
        (_, got), = self.b.taken
        self.assertEqual(got["findings"][0]["items"], [ITEM])

    def test_report_lines_name_recovered_counts(self):
        self.record(payload([ITEM, ITEM2]))
        self.take(reply())
        self.assertEqual(diverted.report_lines(self.b.dir),
                         ["局所レビュー（周 1）の /code-review: fork が親の返答の道具（StructuredOutput）に書いた所見 2 件を、"
                          "包みの記録から戻した"])

    def test_prompt_note_tells_role_not_to_rerun_and_not_to_spell_flags(self):
        for word in ("Skill execution completed", "起こし直すな", "--fix", "invoked: true"):
            self.assertIn(word, material.LENS_FORK_NOTE)


if __name__ == "__main__":
    unittest.main()
