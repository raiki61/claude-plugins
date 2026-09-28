"""包み（.shared/core/claude-adapter）が子の終わりを種分けすること: 1 手も進まずに終わった即時の死（assistant の行が無く、
result の num_turns が 0）は result の行を Archon へ渡さず、起動の失敗（終了コード 75）で返して Archon の起こし直しに乗せ、
result の中身は包みの終わりの記録（<家>/exits/<cwd の hash>.jsonl）に全文で残す。手が進んだ起動の result は、子の終わりを
待たずにすぐ、そのままのバイトで写す（run 43 の fix-ruled・run 54 の tdd の 5 回目: numTurns 0 が output_contract に落ちた）。

偽の claude は試験ごとに一時の置き場に書く小さな python（決めた stream-json の行を出し、FAKE_WAIT_STDIN なら標準入力の
終わりまで待つ）。包みを子で起こすだけで、git・Archon・決まった秒の待ちは無い。
"""
import json
import os
import pathlib
import select
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

SANDBOX = '{"sandbox":{"enabled":true,"allowUnsandboxedCommands":false,"failIfUnavailable":true}}'
FAKE = """#!/usr/bin/env python3
import json, os, sys
for line in json.loads(os.environ["FAKE_LINES"]):
    sys.stdout.write(line + "\\n")
    sys.stdout.flush()
if os.environ.get("FAKE_WAIT_STDIN"):
    sys.stdin.read()
"""
INIT = json.dumps({"type": "system", "subtype": "init", "session_id": "s-1"})
ASSISTANT = json.dumps({"type": "assistant", "message": {"content": [{"type": "text", "text": "考えた"}]}})
NO_TURN_TEXT = "API Error: 529 overloaded（即時の死の本文）\n2 行目"
NO_TURN_RESULT = json.dumps({"type": "result", "subtype": "error_during_execution", "is_error": True, "num_turns": 0,
                             "result": NO_TURN_TEXT, "total_cost_usd": 1.148829}, ensure_ascii=False)
DONE_RESULT = json.dumps({"type": "result", "subtype": "success", "is_error": False, "num_turns": 3,
                          "result": "答え", "structured_output": {"a": "x"}}, ensure_ascii=False)


def argv(marked: bool):
    """SDK 0.3.282 の並び（test_adapter.sdk_argv と同じ形）。marked なら役の節の印を持つ"""
    a = ["--output-format", "stream-json", "--verbose", "--input-format", "stream-json", "--model", "opus"]
    if marked:
        schema = {"type": "object", "description": "works-node: fix", "properties": {"a": {"type": "string"}}}
        a += ["--json-schema", json.dumps(schema)]
    a += ["--tools", "", "--setting-sources=project,user", "--permission-mode", "bypassPermissions"]
    if marked:
        a += ["--settings", SANDBOX]
    return a


def strings(doc):
    """doc の中の文字列を全部（入れ子の JSON の文字列も開いて）"""
    if isinstance(doc, str):
        yield doc
        try:
            inner = json.loads(doc)
        except ValueError:
            return
        if not isinstance(inner, str):
            yield from strings(inner)
    elif isinstance(doc, dict):
        for v in doc.values():
            yield from strings(v)
    elif isinstance(doc, list):
        for v in doc:
            yield from strings(v)


class NoTurnCase(unittest.TestCase):
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

    def env(self, lines, **kw):
        env = {k: v for k, v in os.environ.items() if not k.startswith("WORKS_")}
        env.update(WORKS_ADAPTER_HOME=str(self.home), WORKS_REAL_CLAUDE=str(self.fake), FAKE_LINES=json.dumps(lines),
                   PYTHONDONTWRITEBYTECODE="1", **kw)
        return env

    def run_adapter(self, lines, marked):
        return subprocess.run([str(ADAPTER), *argv(marked)], cwd=str(self.cwd), env=self.env(lines), input="",
                              capture_output=True, text=True, encoding="utf-8", timeout=60)

    def exits(self):
        p = self.home / "exits" / f"{adapter.cwd_key(self.cwd)}.jsonl"
        if not p.exists():
            return []
        return [json.loads(ln) for ln in p.read_text(encoding="utf-8").splitlines()]

    def assert_no_turn(self, marked):
        r = self.run_adapter([INIT, NO_TURN_RESULT], marked)
        self.assertEqual(r.returncode, 75, (r.stdout, r.stderr))
        self.assertNotIn('"type": "result"', r.stdout, "即時の死の result を Archon へ渡した（散文の答えと同じ output_contract に落ちる）")
        self.assertIn(INIT, r.stdout)
        rows = self.exits()
        self.assertEqual(len(rows), 1, rows)
        self.assertEqual(rows[0].get("kind"), "no_turn", rows[0])
        self.assertIn(NO_TURN_TEXT, list(strings(rows[0])), "result の全文を終わりの記録に残していない")

    def test_no_turn_unmarked_exits_75_and_records(self):
        """印の無い起動でも、1 手も進まずに終わった子は 75 で返し、result の行を写さず、終わりの記録に全文を残す"""
        self.assert_no_turn(marked=False)

    def test_no_turn_marked_exits_75_and_records(self):
        """役の節（印のある起動）の即時の死も 75 で返す（Archon の transient の起こし直しに乗る）"""
        self.assert_no_turn(marked=True)

    def test_progressed_result_passes_through_before_child_ends(self):
        """手が進んだ起動は、result の行を子の終わりを待たずにすぐ・そのままのバイトで写し、子の終了コードを返す
        （子は result の後も標準入力の終わりを待つ。result を子の終わりまで留めると、SDK が stdin を閉じずに互いを待つ）"""
        lines = [INIT, ASSISTANT, DONE_RESULT]
        p = subprocess.Popen([str(ADAPTER), *argv(False)], cwd=str(self.cwd), env=self.env(lines, FAKE_WAIT_STDIN="1"),
                             stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        try:
            got = b""
            while b'"type": "result"' not in got:
                ready, _, _ = select.select([p.stdout], [], [], 20)
                self.assertTrue(ready, f"result の行が 20 秒で届かない（子の終わりまで留めている）: {got!r}")
                chunk = os.read(p.stdout.fileno(), 65536)
                self.assertTrue(chunk, f"result の前に出力が閉じた: {got!r}")
                got += chunk
            p.stdin.close()
            rest = p.stdout.read()
            self.assertEqual(p.wait(30), 0, p.stderr.read())
        finally:
            if p.poll() is None:
                p.kill()
                p.wait()
            p.stdout.close()
            p.stderr.close()
        self.assertEqual((got + rest).decode("utf-8"), "".join(line + "\n" for line in lines))
        self.assertEqual(self.exits(), [])


if __name__ == "__main__":
    unittest.main()
