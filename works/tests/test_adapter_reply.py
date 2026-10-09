"""包み（.shared/core/claude-adapter）の旗 text-reply（adapter.py の頭の 21）: 返答の型を Claude の返答の道具に任せず、本流
review-graph と同じ契約（本文で返させ、受け取った後に型を確かめ、合わなければ同じ会話で理由を返して出し直させる）で受ける。

Archon v0.11.1 は節の output_format を SDK の outputFormat に渡し、SDK 0.3.282 は schema を argv の `--json-schema` と
stdin の initialize の `jsonSchema` の両方で Claude Code に渡す。Claude Code は schema を受けると返答の道具 StructuredOutput を
足し、fork で走る skill（/code-review）がそれを継いで所見を書いて終わるので、親に所見が届かなかった（0.2.46 の CHANGELOG）。
旗 text-reply の起動は、包みが両方から schema を外し（子と fork に返答の道具が無い）、返答の形を system prompt で渡し、
result の本文の JSON を schema で確かめ、合わなければ同じ子の stdin に理由の user の行を足して出し直させ（上限
replycontract.REASKS 回。本流の resume_on_reject と同じ 2）、合えば result の行に structured_output を置いて Archon へ写す。

偽の claude は一時の置き場の小さな python（stream-json の stdin を読み、initialize に答え、user の行ごとに決めた本文の result を
出し、stdin の終わりで抜ける）。包みを子で起こすだけで、git・Archon・決まった秒の待ちは無い。
"""
import json
import os
import pathlib
import queue
import stat
import subprocess
import sys
import tempfile
import threading
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
CORE = ROOT / ".shared" / "core"
ADAPTER = CORE / "claude-adapter"
sys.dont_write_bytecode = True
sys.path.insert(0, str(CORE))

import adapter  # noqa: E402
import node_marker  # noqa: E402
import replycontract  # noqa: E402

SANDBOX = '{"sandbox":{"enabled":true,"allowUnsandboxedCommands":false,"failIfUnavailable":true}}'
SCHEMA = {"type": "object", "required": ["verdict", "items"], "additionalProperties": False,
          "properties": {"verdict": {"type": "string", "enum": ["ok", "ng"]},
                         "items": {"type": "array", "items": {"type": "string"}}}}
GOOD = {"verdict": "ok", "items": ["a"]}


def marked(flags=("text-reply",), name="local-review"):
    return node_marker.mark(SCHEMA, name, flags=flags)


def sdk_argv(schema, *, input_stream=True):
    """SDK 0.3.282 の並び（test_adapter_spend.argv と同じ形）"""
    a = ["--output-format", "stream-json", "--verbose"]
    if input_stream:
        a += ["--input-format", "stream-json"]
    return a + ["--model", "sonnet", "--json-schema", json.dumps(schema, ensure_ascii=False), "--tools", "",
                "--setting-sources=project,user", "--permission-mode", "bypassPermissions", "--settings", SANDBOX]


def init_line(schema):
    """SDK が stdin の最初に書く initialize（jsonSchema を持つ。バンドルの y_t の initialize の形）"""
    return json.dumps({"type": "control_request", "request_id": "r1",
                       "request": {"subtype": "initialize", "hooks": None, "jsonSchema": schema,
                                   "appendSystemPrompt": None}}, ensure_ascii=False)


def user_line(text):
    """SDK が文字列の指示文で書く user の行（バンドルの Ejn の形）"""
    return json.dumps({"type": "user", "session_id": "", "message": {"role": "user", "content": [{"type": "text", "text": text}]},
                       "parent_tool_use_id": None}, ensure_ascii=False)


class MarkerCase(unittest.TestCase):
    def test_flag_is_known_to_both_readers(self):
        """旗 text-reply は印の文法（node_marker.parse）と包みの読み（adapter.parse_marker）の両方が読む"""
        self.assertIn("text-reply", node_marker.parse("works-node: local-review no-tree-write text-reply")["flags"])
        self.assertIn("text-reply", adapter.parse_marker("works-node: local-review no-tree-write text-reply").flags)


class PlanCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = pathlib.Path(self._tmp.name).resolve()
        self.home = self.tmp / "adapter-home"
        self.cwd = self.tmp / "wt"
        self.cwd.mkdir()

    def plan(self, args):
        return adapter.plan(args, self.cwd, self.home, "true", new_id=lambda: "new-id")

    def test_text_reply_drops_schema_flag_and_keeps_schema(self):
        """旗 text-reply の起動: 子の argv に --json-schema が無く（返答の道具を足させない）、plan が schema を持つ"""
        schema = marked()
        p = self.plan(sdk_argv(schema))
        self.assertEqual(p.mode, "merged", p.why)
        self.assertFalse(any(a == "--json-schema" or a.startswith("--json-schema=") for a in p.argv))
        self.assertEqual(p.reply, schema)

    def test_text_reply_puts_contract_in_system_prompt(self):
        """返答の形（schema の JSON と、最後の返答に JSON の object を 1 つ地の文で出せという決まり）を system prompt に足し、
        塊の sha を起動の記録の fence.text_reply に残す"""
        p = self.plan(sdk_argv(marked()))
        text = p.argv[p.argv.index("--append-system-prompt") + 1]
        self.assertIn(replycontract.instruction(marked()), text)
        self.assertIn('"enum": ["ok", "ng"]', text)
        self.assertNotIn("works-node:", text, "印は役に見せない（返答の型の注記でない）")
        self.assertRegex(p.fence["text_reply"], r"^[0-9a-f]{16}$")

    def test_other_marked_launches_keep_schema(self):
        """旗の無い印のある起動は今どおり --json-schema を渡す"""
        p = self.plan(sdk_argv(marked(flags=())))
        self.assertIn("--json-schema", p.argv)
        self.assertIsNone(p.reply)
        self.assertNotIn("text_reply", p.fence)

    def test_text_reply_needs_stream_json_input(self):
        """stdin の stream-json が無い起動では同じ会話に出し直させられないので起こさない（fail closed）"""
        p = self.plan(sdk_argv(marked(), input_stream=False))
        self.assertEqual(p.mode, "refused")
        self.assertIn("text-reply", p.why)


class StripInitCase(unittest.TestCase):
    def test_initialize_loses_json_schema(self):
        """initialize の jsonSchema を外す（Claude Code は argv に schema が無いと initialize の schema で返答の道具を足す）"""
        got = json.loads(replycontract.strip_init_schema(init_line(SCHEMA).encode("utf-8")))
        self.assertNotIn("jsonSchema", got["request"])
        self.assertEqual(got["request"]["subtype"], "initialize")
        self.assertEqual(got["request_id"], "r1")

    def test_other_lines_keep_bytes(self):
        for line in (user_line("やれ"), '{"type": "control_response"}', "not json", init_line(SCHEMA).replace("jsonSchema", "x")):
            with self.subTest(line=line[:30]):
                raw = line.encode("utf-8")
                self.assertEqual(replycontract.strip_init_schema(raw), raw)


class CheckCase(unittest.TestCase):
    def test_plain_fenced_and_wrapped_json(self):
        """本文の読み方は本流 commands.parse_output と同じ順（全文 → ``` の囲いの中 → 最初の { から最後の } まで）"""
        body = json.dumps(GOOD)
        for text in (body, f"```json\n{body}\n```", f"返す。\n{body}\n以上"):
            with self.subTest(text=text[:20]):
                self.assertEqual(replycontract.check(text, SCHEMA), (GOOD, []))

    def test_schema_errors_name_the_field(self):
        value, errs = replycontract.check(json.dumps({"verdict": "maybe", "items": []}), SCHEMA)
        self.assertEqual(value, {"verdict": "maybe", "items": []})
        self.assertTrue(errs and any("verdict" in e for e in errs), errs)

    def test_unparseable_and_empty(self):
        for text in ("所見は無い", "", None):
            with self.subTest(text=text):
                value, errs = replycontract.check(text, SCHEMA)
                self.assertIsNone(value)
                self.assertTrue(errs)


def result_doc(text, turn=1, **extra):
    return {"type": "result", "subtype": "success", "is_error": False, "num_turns": turn, "session_id": "s",
            "result": text, "total_cost_usd": 0.25 * turn, **extra}


class ContractCase(unittest.TestCase):
    def setUp(self):
        self.sent, self.rows, self.released = [], [], []
        self.c = replycontract.Contract(SCHEMA, log=self.rows.append)
        self.c.attach(lambda data: self.sent.append(data) or True, lambda: self.released.append(True))

    def test_valid_reply_becomes_structured_output(self):
        got = self.c.on_result(result_doc(json.dumps(GOOD)))
        self.assertEqual(got["structured_output"], GOOD)
        self.assertEqual(self.sent, [])
        self.assertEqual(self.released, [True])
        self.assertEqual(self.rows[-1]["kind"], "accepted")

    def test_invalid_reply_is_held_and_reasked_with_reason(self):
        """型に合わない返答は Archon へ写さず、同じ子の stdin に理由を載せた user の行を足す"""
        self.assertIsNone(self.c.on_result(result_doc(json.dumps({"verdict": "maybe", "items": []}))))
        self.assertEqual(len(self.sent), 1)
        doc = json.loads(self.sent[0])
        self.assertEqual(doc["type"], "user")
        text = doc["message"]["content"][0]["text"]
        self.assertIn("verdict", text)
        self.assertTrue(self.sent[0].endswith(b"\n"))
        self.assertEqual(self.released, [])
        self.assertEqual(self.rows[-1]["kind"], "reasked")

    def test_reasks_are_bounded_then_the_reply_goes_to_archon(self):
        """出し直しは REASKS 回まで（本流 review-graph の resume_on_reject と同じ 2）。使い切ったら最後の返答を写して Archon の
        検査に任せる（JSON として読めた値は structured_output に置き、Archon の ajv が拒めば節が落ちる。黙って通さない）"""
        self.assertEqual(replycontract.REASKS, 2)
        bad = json.dumps({"verdict": "maybe", "items": []})
        for _ in range(replycontract.REASKS):
            self.assertIsNone(self.c.on_result(result_doc(bad)))
        got = self.c.on_result(result_doc(bad, turn=3))
        self.assertEqual(got["structured_output"], {"verdict": "maybe", "items": []})
        self.assertEqual(len(self.sent), replycontract.REASKS)
        self.assertEqual(self.released, [True])
        self.assertEqual(self.rows[-1]["kind"], "gave_up")

    def test_unparseable_after_bound_has_no_structured_output(self):
        for _ in range(replycontract.REASKS):
            self.c.on_result(result_doc("散文"))
        got = self.c.on_result(result_doc("散文", turn=3))
        self.assertNotIn("structured_output", got)

    def test_error_result_passes_unchanged(self):
        """誤りで終わった result（上限・API の誤り）は出し直さずにそのまま写す（Archon が落とす。起こし直しは Archon の物）"""
        doc = dict(result_doc(""), subtype="error_max_turns", is_error=True)
        self.assertIs(self.c.on_result(doc), doc)
        self.assertEqual(self.sent, [])
        self.assertEqual(self.released, [True])

    def test_native_structured_output_passes_unchanged_and_is_logged(self):
        """子が返答の道具で返した（schema を外し損ねた）result はそのまま写し、記録に native と残す（外し損ねを大きく見せる）"""
        doc = result_doc("", structured_output=GOOD)
        self.assertIs(self.c.on_result(doc), doc)
        self.assertEqual(self.rows[-1]["kind"], "native")

    def test_failed_reask_write_passes_the_reply(self):
        """理由の行を子へ書けない（子が抜けた）なら持たずに写す（Archon が落とす）"""
        c = replycontract.Contract(SCHEMA)
        c.attach(lambda data: False, lambda: None)
        got = c.on_result(result_doc("散文"))
        self.assertIsNotNone(got)
        self.assertNotIn("structured_output", got)


FAKE = """#!/usr/bin/env python3
import json, os, sys
log = open(os.environ["FAKE_LOG"], "a", encoding="utf-8")
def rec(x):
    log.write(json.dumps(x, ensure_ascii=False) + "\\n")
    log.flush()
def out(x):
    sys.stdout.write(json.dumps(x, ensure_ascii=False) + "\\n")
    sys.stdout.flush()
argv = sys.argv[1:]
rec({"argv": argv})
sid = next((a.split("=", 1)[1] for a in argv if a.startswith("--session-id=")), "s")
replies = json.loads(os.environ["FAKE_REPLIES"])
turn = 0
for line in sys.stdin:
    d = json.loads(line)
    if d.get("type") == "control_request":
        rec({"init": d["request"]})
        out({"type": "control_response", "response": {"subtype": "success", "request_id": d["request_id"]}})
        continue
    if d.get("type") != "user":
        continue
    rec({"user": d["message"]["content"][0]["text"]})
    reply = replies[min(turn, len(replies) - 1)]
    turn += 1
    out({"type": "assistant", "message": {"content": [{"type": "text", "text": reply}]}})
    out({"type": "result", "subtype": "success", "is_error": False, "num_turns": 2 * turn, "session_id": sid,
         "result": reply, "total_cost_usd": 0.25 * turn,
         "modelUsage": {"claude-sonnet-5-5": {"inputTokens": 1, "outputTokens": 100 * turn}}})
rec({"eof": turn})
"""


class AdapterReplyCase(unittest.TestCase):
    """包みを子で起こし、SDK の役（initialize と指示文を書き、最初の result を見たら stdin を閉じる。バンドルの
    isSingleUserTurn の形）を試験が演じる"""

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
        self.log = self.tmp / "fake.jsonl"

    def sdk(self, schema, replies, close_early=False):
        """(stdout の行の doc の全部, 終了コード)。最初の result を見たら stdin を閉じる（close_early なら指示文を書いた直後に
        閉じる。SDK が先に stdin を閉じる形でも、包みは契約が決まるまで子の stdin を閉じない）"""
        env = {k: v for k, v in os.environ.items() if not k.startswith("WORKS_")}
        env.update(WORKS_ADAPTER_HOME=str(self.home), WORKS_REAL_CLAUDE=str(self.fake), PYTHONDONTWRITEBYTECODE="1",
                   FAKE_LOG=str(self.log), FAKE_REPLIES=json.dumps(replies, ensure_ascii=False))
        p = subprocess.Popen([str(ADAPTER), *sdk_argv(schema)], cwd=str(self.cwd), env=env, stdin=subprocess.PIPE,
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        lines: "queue.Queue[bytes]" = queue.Queue()

        def pump():
            for ln in p.stdout:
                lines.put(ln)
            lines.put(b"")
        threading.Thread(target=pump, daemon=True).start()
        p.stdin.write((init_line(schema) + "\n" + user_line("局所レビューをせよ") + "\n").encode("utf-8"))
        p.stdin.flush()
        if close_early:
            p.stdin.close()
        docs = []
        while True:
            ln = lines.get(timeout=60)
            if not ln:
                break
            docs.append(json.loads(ln))
            if docs[-1].get("type") == "result" and not p.stdin.closed:
                p.stdin.close()
        err = p.stderr.read().decode("utf-8", "replace")
        p.stderr.close()
        rc = p.wait(timeout=60)
        return docs, rc, err

    def fake_rows(self):
        return [json.loads(x) for x in self.log.read_text(encoding="utf-8").splitlines()]

    def test_invalid_then_valid_in_the_same_process(self):
        """1 回目の返答が型に合わなければ、Archon には何も写さずに同じ子（同じ会話）へ理由を返し、2 回目の返答を
        structured_output にして 1 つの result で写す。子は schema を argv でも initialize でも受け取らない"""
        bad = json.dumps({"verdict": "maybe", "items": []})
        docs, rc, err = self.sdk(marked(), [bad, json.dumps(GOOD)])
        self.assertEqual(rc, 0, err)
        results = [d for d in docs if d.get("type") == "result"]
        self.assertEqual(len(results), 1, docs)
        self.assertEqual(results[0]["structured_output"], GOOD)
        rows = self.fake_rows()
        argv = rows[0]["argv"]
        self.assertFalse(any(a.startswith("--json-schema") for a in argv))
        self.assertNotIn("jsonSchema", [r for r in rows if "init" in r][0]["init"])
        users = [r["user"] for r in rows if "user" in r]
        self.assertEqual(len(users), 2)
        self.assertIn("verdict", users[1])
        self.assertEqual(rows[-1], {"eof": 2})

    def test_sdk_closing_stdin_early_still_reasks(self):
        """SDK が result より先に stdin を閉じても、子の stdin は契約が決まるまで開いたままで、出し直しが同じ子に届く。決まった後は
        閉じて子が抜ける（いつまでも待たない）"""
        bad = json.dumps({"verdict": "maybe", "items": []})
        docs, rc, err = self.sdk(marked(), [bad, json.dumps(GOOD)], close_early=True)
        self.assertEqual(rc, 0, err)
        results = [d for d in docs if d.get("type") == "result"]
        self.assertEqual([r.get("structured_output") for r in results], [GOOD])
        self.assertEqual(self.fake_rows()[-1], {"eof": 2})

    def test_sdk_closing_stdin_early_and_bound(self):
        docs, rc, err = self.sdk(marked(), ["散文"], close_early=True)
        self.assertEqual(rc, 0, err)
        self.assertEqual(self.fake_rows()[-1], {"eof": 1 + replycontract.REASKS})

    def test_spend_counts_all_turns_once(self):
        """出し直しを挟んだ起動の費用: 写した result の累計は子の全部の手の累計（0.25 × 2）で、会話の費用の記録は写した
        result の 1 回だけ（持った result では書かない）。Archon の引き算はこの起動の費用の全部になる"""
        bad = json.dumps({"verdict": "maybe", "items": []})
        docs, rc, err = self.sdk(marked(), [bad, json.dumps(GOOD)])
        self.assertEqual(rc, 0, err)
        res = [d for d in docs if d.get("type") == "result"][0]
        self.assertAlmostEqual(res["total_cost_usd"], 0.5, places=9)
        sid = res["session_id"]
        rec = json.loads(adapter.spend_path(self.cwd, sid, self.home).read_text(encoding="utf-8"))
        self.assertAlmostEqual(rec["real"]["cost"], 0.5, places=9)
        self.assertEqual(rec["real"]["out"], {"claude-sonnet-5-5": 200})

    def test_bound_then_archon_decides(self):
        """出し直しを使い切っても読めない返答は structured_output 無しで写す（Archon が output_contract で落とす）。子は
        最初の指示と REASKS 回の出し直しを受け、記録 replies/<cwd の hash>.jsonl に回ごとの 1 行が残る"""
        docs, rc, err = self.sdk(marked(), ["散文"])
        self.assertEqual(rc, 0, err)
        results = [d for d in docs if d.get("type") == "result"]
        self.assertEqual(len(results), 1)
        self.assertNotIn("structured_output", results[0])
        users = [r["user"] for r in self.fake_rows() if "user" in r]
        self.assertEqual(len(users), 1 + replycontract.REASKS)
        kinds = [r["kind"] for r in adapter.read_replies(self.cwd, self.home)]
        self.assertEqual(kinds, ["reasked"] * replycontract.REASKS + ["gave_up"])

    def test_unflagged_launch_keeps_schema_and_init(self):
        """旗の無い印のある起動は今どおり: 子は --json-schema と initialize の jsonSchema を受け、result はそのまま写る"""
        docs, rc, err = self.sdk(marked(flags=()), [json.dumps(GOOD)])
        self.assertEqual(rc, 0, err)
        rows = self.fake_rows()
        self.assertIn("--json-schema", rows[0]["argv"])
        self.assertIn("jsonSchema", [r for r in rows if "init" in r][0]["init"])
        self.assertNotIn("structured_output", [d for d in docs if d.get("type") == "result"][0])


class GateCase(unittest.TestCase):
    """子の stdin の口（adapter.InGate）と、stdout の中継（adapter.relay_out）が契約の例外でも口を放すこと"""

    def test_gate_holds_until_release(self):
        r, w = os.pipe()
        self.addCleanup(os.close, r)
        g = adapter.InGate(w, hold=True)
        g.end()
        self.assertTrue(g.write(b"a\n"), "SDK の stdin が終わっても、決まるまでは子へ書ける")
        self.assertFalse(g.closed)
        g.release()
        self.assertTrue(g.closed)
        self.assertFalse(g.write(b"b\n"))
        self.assertEqual(os.read(r, 100), b"a\n")
        self.assertEqual(os.read(r, 100), b"", "放した後は閉じている（子は stdin の終わりを見る）")

    def test_gate_without_hold_closes_on_end(self):
        r, w = os.pipe()
        self.addCleanup(os.close, r)
        g = adapter.InGate(w)
        g.end()
        self.assertTrue(g.closed)

    def test_contract_error_releases_logs_and_relays(self):
        """契約の決めが例外を投げても、result の行をそのまま写し、口を放し（子の stdin が閉じられる）、記録に error を残す"""
        rows, released = [], []

        class Boom(replycontract.Contract):
            def on_result(self, doc):
                raise RuntimeError("壊れた")
        c = Boom(SCHEMA, log=rows.append)
        c.attach(lambda data: True, lambda: released.append(True))
        src_r, src_w = os.pipe()
        dst_r, dst_w = os.pipe()
        line = json.dumps(result_doc("散文")).encode("utf-8")
        os.write(src_w, line + b"\n")
        os.close(src_w)
        adapter.relay_out(src_r, dst_w, adapter.OutWatch(None, c))
        got = os.read(dst_r, 65536)
        os.close(dst_r)
        self.assertEqual(got, line + b"\n")
        self.assertEqual(released, [True])
        self.assertEqual(rows[-1]["kind"], "error")
        self.assertIn("RuntimeError", rows[-1]["why"])


class PackCase(unittest.TestCase):
    def test_local_review_is_text_reply(self):
        """fork で走る skill（/code-review）を起こす局所レビューの役は旗 text-reply を持つ"""
        sys.path.insert(0, str(ROOT / "blk-material" / "lib"))
        import material  # noqa: E402
        self.assertIn("text-reply", node_marker.parse(material.output_format("local-review")["description"])["flags"])

    def test_text_reply_schemas_use_only_checked_words(self):
        """旗 text-reply の節の schema は、包みの検査（写しの engine の型検査）が読む語だけで書く（読まない語は Archon の ajv
        だけが見るので、包みが出し直させられない）"""
        sys.path.insert(0, str(ROOT / "blk-material" / "lib"))
        import material  # noqa: E402
        self.assertEqual(replycontract.unchecked(material.output_format("local-review")), [])


if __name__ == "__main__":
    unittest.main()
