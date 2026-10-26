#!/usr/bin/env python3
"""初見読みの使用量記録。実物の result の見本と、呼び出しの代役で照合する。"""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("coldread_usage", ROOT / "gates/hooks/coldread-gate.py")
g = importlib.util.module_from_spec(spec)
spec.loader.exec_module(g)


class UsageTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.log = Path(self.tmp.name) / "reader-usage.jsonl"
        self.original_log = g.READER_LOG
        g.READER_LOG = str(self.log)
        self.addCleanup(setattr, g, "READER_LOG", self.original_log)
        self.result = json.loads((ROOT / "tests/fixtures/coldread-result-2.1.307.json").read_text())
        g.READER_NOTICES.clear()
        self.addCleanup(g.READER_NOTICES.clear)

    def record(self, result, status="ok"):
        proc = subprocess.CompletedProcess([], 0, json.dumps(result).encode(), b"")
        g._reader_measure(proc, {"writer_session_id": "writer-full", "reader_session_id": "chosen"},
                          time.monotonic(), status)
        return json.loads(self.log.read_text().splitlines()[-1])

    def test_actual_result_and_privacy(self):
        self.result.update(result="会話本文の秘密", structured_output={"findings": [{"text": "秘密"}]})
        row = self.record(self.result)
        self.assertEqual(row["usage"]["thinking_tokens"], 6377)
        self.assertEqual(row["usage"]["nonthinking_output_tokens"], 904)
        self.assertEqual(row["usage"]["ephemeral_5m_input_tokens"], 2841)
        self.assertEqual(row["usage"]["ephemeral_1h_input_tokens"], 0)
        self.assertEqual(row["models"]["claude-haiku-5-5"]["outputTokens"], 7281)
        self.assertEqual(row["writer_session_id"], "writer-full")
        self.assertNotIn("秘密", self.log.read_text())
        if os.name != "nt":
            self.assertEqual(self.log.stat().st_mode & 0o777, 0o600)

    def test_missing_is_not_zero(self):
        row = self.record({})
        self.assertIsNone(row["usage"]["thinking_tokens"])
        self.assertIsNone(row["usage"]["output_tokens"])
        self.assertEqual(row["reader_session_id"], "chosen")
        self.assertEqual(self.record({"usage": {"output_tokens": 0, "output_tokens_details": {"thinking_tokens": 0}}})
                         ["usage"]["nonthinking_output_tokens"], 0)
        row = self.record({"usage": {"output_tokens": 1, "output_tokens_details": {"thinking_tokens": 2}}})
        self.assertIsNone(row["usage"]["nonthinking_output_tokens"])

    def test_shape_auth_timeout_and_launch_are_recorded(self):
        for raw, error in ((b'{"type":"result","is_error":false}', g.ReaderShape),
                           (b"Failed to authenticate: OAuth session expired", g.ReaderAuth)):
            with patch.object(g.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, raw, b"")):
                with self.assertRaises(error):
                    g._reader_attempt([], "秘密", 1, {"reader_session_id": "chosen"})
        for exc, status in ((subprocess.TimeoutExpired([], 1), "timeout"), (OSError("秘密"), "down")):
            with patch.object(g.subprocess, "run", side_effect=exc):
                with self.assertRaises(type(exc)):
                    g._reader_attempt([], "秘密", 1, {"reader_session_id": "chosen"})
            self.assertEqual(json.loads(self.log.read_text().splitlines()[-1])["status"], status)
        self.assertNotIn("秘密", self.log.read_text())

    def test_log_failure_is_visible_without_losing_result(self):
        with patch.object(g.os, "open", side_effect=PermissionError("書込できない")), \
             patch.object(g.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, json.dumps(self.result).encode(), b"")):
            self.assertEqual(g._reader_attempt([], "秘密", 1, {}), self.result["structured_output"])
        with patch.object(g, "_expiry_lines", return_value=[]):
            self.assertIn("使用量記録", g.owner_note()["systemMessage"])
            with patch.object(g, "_drop_snaps"), patch.object(g, "rewakes", return_value=False), \
                 patch.object(g, "_read_pending", return_value=([], {}, [], 0)), patch.object(g, "_left_behind", return_value=""), \
                 patch("builtins.print") as output:
                g.docs_check({"session_id": "writer", "hook_event_name": "Stop"})
            self.assertIn("使用量記録", json.loads(output.call_args.args[0])["hookSpecificOutput"]["additionalContext"])

    def test_invalid_counters_are_missing(self):
        row = self.record({"session_id": {"text": "秘密"}, "usage": {"output_tokens": float("inf"), "input_tokens": True},
                           "modelUsage": {"haiku": {"costUSD": float("nan"), "costBasis": "秘密"}}})
        self.assertIsNone(row["usage"]["output_tokens"])
        self.assertIsNone(row["usage"]["input_tokens"])
        self.assertIsNone(row["models"]["haiku"]["costUSD"])
        self.assertIsNone(row["models"]["haiku"]["costBasis"])
        self.assertEqual(row["reader_session_id"], "chosen")
        self.assertNotIn("秘密", self.log.read_text())

    def test_default_argv_and_cache(self):
        argv = g.reader_argv("claude", {})
        for flag in ("--no-session-persistence", "--disable-slash-commands", "--strict-mcp-config"):
            self.assertIn(flag, argv)
        self.assertEqual(argv[argv.index("--system-prompt") + 1], g.READER_SYSTEM)
        self.assertEqual(json.loads(argv[argv.index("--mcp-config") + 1]), {"mcpServers": {}})
        self.assertEqual(argv[argv.index("--output-format") + 1], "json")
        calls = []
        def fake(argv, **kwargs):
            calls.append((argv, kwargs))
            return subprocess.CompletedProcess(argv, 0, json.dumps(self.result).encode(), b"")
        with patch.object(g, "reader_envs", return_value=([({"CLAUDE_CONFIG_DIR": self.tmp.name}, "")], False)), \
             patch.object(g.subprocess, "run", side_effect=fake), patch.dict(os.environ, {}, clear=True):
            g.run_reader("秘密", {}, model="haiku", effort="high")
        argv, kwargs = calls[0]
        self.assertIn("--session-id", argv)
        self.assertEqual(kwargs["env"]["FORCE_PROMPT_CACHING_5M"], "1")
        self.assertEqual(kwargs["input"], "秘密".encode())

    def test_source_uses_session_environment_and_company_name(self):
        common = Path(self.tmp.name) / "alias-clone" / ".git"
        calls = []
        def fake(argv, **kwargs):
            calls.append(argv)
            if argv[1:3] == ["config", "--null"]:
                raw = b"company.name\nteam\0company.ask\nrequest\0company.session\nattribute-session\0"
            elif argv[1] == "rev-parse":
                raw = str(common).encode()
            elif "symbolic-ref" in argv:
                raw = b"refs/remotes/origin/main\n"
            else:
                raw = b'name = "configured-company"\n'
            return subprocess.CompletedProcess(argv, 0, raw, b"")
        with patch.object(g.subprocess, "run", side_effect=fake), \
             patch.dict(os.environ, {"CLAUDE_CODE_SESSION_ID": "environment-session"}, clear=True):
            source = g.reader_source(cwd=self.tmp.name)
        self.assertEqual(source["writer_session_id"], "environment-session")
        self.assertEqual(source["company"], "configured-company")
        self.assertEqual(source["request_id"], "request")

    def test_company_name_from_dispatch_settings(self):
        root = Path(self.tmp.name) / "alias-clone"
        settings = Path(self.tmp.name) / "settings"
        file = settings / "companies" / (g.urllib.parse.quote(os.path.realpath(root), safe="") + ".toml")
        file.parent.mkdir(parents=True)
        file.write_text('name = "external-company"\n')
        def fake(argv, **kwargs):
            if argv[1] == "config":
                return subprocess.CompletedProcess(argv, 1, b"", b"")
            if argv[1] == "rev-parse":
                return subprocess.CompletedProcess(argv, 0, str(root / ".git").encode(), b"")
            return subprocess.CompletedProcess(argv, 1, b"", b"")
        with patch.object(g.subprocess, "run", side_effect=fake), \
             patch.dict(os.environ, {"WORKS_DISPATCH_CONFIG": str(settings / "dispatch.toml")}, clear=True):
            self.assertEqual(g.reader_source(cwd=self.tmp.name)["company"], "external-company")

    def test_stage_uses_unique_branch_worktree(self):
        origin = str(Path(self.tmp.name) / "writer")
        def fake(argv, **kwargs):
            if argv[1] == "config":
                raw = b"company.name\nteam\0company.ask\nrequest\0company.session\nwriter-session\0" if kwargs["cwd"] == origin else b""
            elif "worktree" in argv:
                raw = ("worktree " + origin + "\0HEAD abc\0branch refs/heads/work/test\0\0").encode()
            elif argv[1] == "rev-parse":
                raw = str(ROOT / ".git").encode()
            else:
                return subprocess.CompletedProcess(argv, 1, b"", b"")
            return subprocess.CompletedProcess(argv, 0, raw, b"")
        with patch.object(g.subprocess, "run", side_effect=fake), patch.dict(os.environ, {}, clear=True):
            source = g.reader_source(cwd=self.tmp.name, branch="work/test")
        self.assertEqual(source["writer_session_id"], "writer-session")
        self.assertEqual(source["department"], "team")
        self.assertEqual(source["request_id"], "request")
        self.assertNotIn("cwd", source)

    def test_stage_rejects_ambiguous_worktrees(self):
        def fake(argv, **kwargs):
            if "worktree" in argv:
                raw = b"worktree /one\0branch refs/heads/work/test\0\0worktree /two\0branch refs/heads/work/test\0\0"
                return subprocess.CompletedProcess(argv, 0, raw, b"")
            return subprocess.CompletedProcess(argv, 1, b"", b"")
        with patch.object(g.subprocess, "run", side_effect=fake), patch.dict(os.environ, {}, clear=True):
            source = g.reader_source(cwd=self.tmp.name, branch="work/test")
        self.assertIsNone(source["request_id"])
        self.assertIsNone(source["department"])
        self.assertIsNone(source["writer_session_id"])

    def test_auth_switch_records_each_attempt(self):
        envs = [({"CLAUDE_CONFIG_DIR": str(Path(self.tmp.name) / name)}, "") for name in ("first", "second")]
        failed = subprocess.CompletedProcess([], 0, b"Failed to authenticate: OAuth session expired", b"")
        succeeded = subprocess.CompletedProcess([], 0, json.dumps(self.result).encode(), b"")
        with patch.object(g, "reader_envs", return_value=(envs, True)), \
             patch.object(g.subprocess, "run", side_effect=[failed, succeeded]), patch.dict(os.environ, {}, clear=True):
            self.assertEqual(g.run_reader("秘密", {}, model="haiku", effort="high"), self.result["structured_output"])
        rows = [json.loads(line) for line in self.log.read_text().splitlines()]
        self.assertEqual([row["attempt"] for row in rows], [1, 2])
        self.assertEqual([row["status"] for row in rows], ["auth", "ok"])
        self.assertEqual(rows[0]["call_id"], rows[1]["call_id"])
        self.assertNotEqual(rows[0]["reader_session_id"], rows[1]["reader_session_id"])
        self.assertIsNone(rows[0]["usage"]["output_tokens"])
        self.assertEqual(rows[1]["usage"]["output_tokens"], 7281)
        self.assertNotIn("秘密", self.log.read_text())
        # モデル照合で止まる回も、切替先の説明を残し、成功ではなく shape として記録する。
        envs = [(envs[0][0], "読み替えを外して first の keychain(item)")]
        for models in ({"gpt-6.1-sol": {}}, {"claude-sonnet-5-5": {}}, {}):
            result = dict(self.result, modelUsage=models)
            with patch.object(g, "reader_envs", return_value=(envs, True)), \
                 patch.object(g.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, json.dumps(result).encode(), b"")), \
                 patch.dict(os.environ, {}, clear=True):
                with self.assertRaisesRegex(g.ReaderShape, "読み替えを外して first"):
                    g.run_reader("秘密", {}, model="haiku", effort="high")
            row = json.loads(self.log.read_text().splitlines()[-1])
            self.assertEqual(row["status"], "shape")
            self.assertEqual(row["usage"]["output_tokens"], 7281)
        self.assertNotIn("秘密", self.log.read_text())

    def test_no_auth_points_to_login(self):
        # 鍵を環境変数でだけ渡す人: フックに鍵が届かず(段 none)、読み手が「Not logged in」で終わる。ログインへ導く 1 行を知らせに足す
        cfg = str(Path(self.tmp.name) / "cfg")
        for out, rc, err in ((b"Not logged in \xc2\xb7 Please run /login", 0, g.ReaderAuth),
                             (json.dumps({"type": "result", "is_error": True, "result": "Not logged in · Please run /login"}).encode(), 1, RuntimeError)):
            g.READER_NOTICES.clear()
            with patch.object(g, "reader_envs", return_value=([({"CLAUDE_CONFIG_DIR": cfg}, "none")], False)), \
                 patch.object(g.subprocess, "run", return_value=subprocess.CompletedProcess([], rc, out, b"")), \
                 patch.dict(os.environ, {}, clear=True):
                with self.assertRaises(err):
                    g.run_reader("秘密", {})
            self.assertEqual(len(g.READER_NOTICES), 1)
            note = next(iter(g.READER_NOTICES))
            self.assertIn("claude auth login", note)
            self.assertIn("claude setup-token", note)
            self.assertIn(cfg.replace("\\", "/") + "/.credentials.json", note)
            self.assertIn(note, g.notices())
        # 認証を足せた回と、ログインの保存先のファイルが在る回の失敗(切れた鍵・使用枠)には足さない
        os.makedirs(cfg)
        Path(cfg, ".credentials.json").write_text("{}")
        for note in ("inherited(ANTHROPIC_API_KEY)", "none"):
            g.READER_NOTICES.clear()
            with patch.object(g, "reader_envs", return_value=([({"CLAUDE_CONFIG_DIR": cfg}, note)], False)), \
                 patch.object(g.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, b"Claude AI usage limit reached", b"")), \
                 patch.dict(os.environ, {}, clear=True):
                with self.assertRaises(g.ReaderAuth):
                    g.run_reader("秘密", {})
            self.assertEqual(g.READER_NOTICES, set(), note)

    def test_read_command_goes_through_run_python(self):
        # 知らせの文が打たせる形。素の python3 は Windows で Microsoft Store へ誘う代わりの物に当たる(docs/standards/cross-os.md の決まり 1)
        cmd = g.read_cmd()
        self.assertTrue(cmd.startswith("bash "), cmd)
        self.assertTrue(cmd.endswith("coldread-gate.py read"), cmd)
        self.assertIn("/hooks/run-python.sh", cmd)
        self.assertNotIn("\\", cmd)
        source = (ROOT / "gates/hooks/coldread-gate.py").read_text(encoding="utf-8")
        self.assertNotRegex(source, r"python3 %s")

    def test_record_only_hook_does_not_read_company(self):
        payload = {"session_id": "writer"}
        with patch.object(g, "docs_off", return_value=False), patch.dict(os.environ, {}, clear=True), \
             patch.object(g.json, "load", return_value=payload), patch.object(g, "reader_source") as source, \
             patch.object(g, "docs_record") as record, patch.object(g, "docs_session_end") as ended:
            g.hook_main("docs-record")
            g.hook_main("docs-session-end")
        source.assert_not_called()
        record.assert_called_once_with(payload)
        ended.assert_called_once_with(payload)

    def test_source_uses_full_hook_identity(self):
        source = g.reader_source({"session_id": "full-writer-session", "agent_id": "full-agent", "cwd": str(ROOT)})
        self.assertEqual(source["writer_session_id"], "full-writer-session")
        self.assertEqual(source["writer_agent_id"], "full-agent")
        self.assertEqual(source["company"], "claude-plugins")
        self.assertNotIn("cwd", source)


if __name__ == "__main__":
    unittest.main()
