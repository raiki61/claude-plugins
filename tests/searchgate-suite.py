"""gates の searchgate(gates/hooks/search-gate.py): / やホームの全体から探すのを止め、それより下と作業場の中は通す。

フックを本物と同じく別のプロセスで起動し、PreToolUse の入力(JSON)を stdin に渡して、deny の JSON か空の出力かを見る。
HOME と設定のフォルダ(CLAUDE_CONFIG_DIR。止めた記録の置き場)は一時の物にする。HOME は Python から子に渡す
(Windows の Git Bash から渡すと / で始まる値が Windows の形に書き換わる)。
"""

import json
import os
import pathlib
import subprocess
import sys
import tempfile
import unittest

sys.dont_write_bytecode = True
HOOK = pathlib.Path(__file__).resolve().parents[1] / "gates" / "hooks" / "search-gate.py"
HOME = "/home/tester"
WORK = HOME + "/src/repo"


def run(tool, tool_input, cwd=WORK, raw=None):
    """フックを起動する → (deny の理由か None, 標準出力)。"""
    with tempfile.TemporaryDirectory() as cfg:
        env = dict(os.environ, HOME=HOME, CLAUDE_CONFIG_DIR=cfg)
        data = raw if raw is not None else json.dumps({"tool_name": tool, "tool_input": tool_input, "cwd": cwd})
        p = subprocess.run([sys.executable, str(HOOK)], input=data.encode("utf-8"), capture_output=True, env=env)
        out = p.stdout.decode("utf-8")
        if p.returncode != 0:
            raise AssertionError("フックが落ちた(rc=%d): %s" % (p.returncode, p.stderr.decode("utf-8", "replace")))
        if not out.strip():
            return None, out
        got = json.loads(out)["hookSpecificOutput"]
        assert got["permissionDecision"] == "deny", out
        return got["permissionDecisionReason"], out


class Bash(unittest.TestCase):
    STOP = [
        "find / -name dag-executor.ts -not -path '*/node_modules/*' 2>/dev/null | head -1",
        "f=$(find / -name dag-executor.ts -path '*archon*' 2>/dev/null | head -1)",
        "find ~ -name research.json",
        "find ~/ -name x",
        "find $HOME -name x",
        'find "${HOME}" -name x',
        "find /home/tester -name x",
        "find /home/tester/src/.. -name x",
        "find /Users -name x",
        "find /System/Volumes/Data -name x",
        "find /Volumes /tmp -name x",
        "find -L / -name x",
        "/usr/bin/find / -name x",
        "bfs -S dfs / -name x",
        "gfind / -name x",
        "cd a && find ~ -name x",
        "timeout 60 find / -name x",
        "nice -n 19 find / -name x",
        "sudo find / -name x",
        'echo "$(find / -name x)"',
        "a=`find / -name x`",
        'bash -c "find / -name x"',
        "sh -lc 'cd /tmp && find / -name x'",
        'eval "find / -name x"',
        "D=/; find $D -name x",
        "D=$HOME && find $D -name x",
        "if true; then find / -name x; fi",
        "fd research.json /",
        "fd -e ts dag ~",
        "fd --search-path / x",
        "rg -n pattern /",
        "rg -e pattern ~",
        "grep -rn needle /",
        "grep -R --include='*.json' needle ~",
        "xargs -0 find / -name x",
        "xargs -I {} find / -name {}",
        "find ~/* -name x",
        "grep -rn needle /Users/*",
        "rg needle /*",
        "bash -o pipefail -c 'find / -name x'",
        "bash -euo pipefail -c 'find ~ -name x'",
        # Linux の / の直下の大きいフォルダ
        "find /home -name x",
        "find /usr -name x",
        "rg needle /var",
        "fd x /mnt",
        "grep -rn needle /root",
        # Windows のドライブの根(どの書き方でも)とその下の大きいフォルダ。大文字と小文字は区別しない
        "find C:/ -name x",
        "find 'C:\\' -name x",
        "find /c/ -name x",
        "find /cygdrive/c -name x",
        "find /mnt/c -name x",
        "find /c/Users -name x",
        "find 'C:\\Users' -name x",
        "find /c/Windows -name x",
        "rg needle 'C:/Program Files'",
        "find /users -name x",
        "find /HOME -name x",
    ]
    PASS = [
        "find . -name x",
        "find ~/.cache/works-factory -name dag-executor.ts",
        "find $HOME/.cache -name x",
        "find /home/tester/src/repo -name x",
        "find /tmp -name x",
        "find /opt/homebrew -name x",
        "find src -name x",
        'grep -rn "find /" README.md',
        "echo 'find / -name x'",
        "git log --grep find",
        "grep needle /etc/hosts",
        "ls / | grep -r needle",
        "cat a | rg needle",
        "rg needle",
        "fd x",
        "fd -x rm / x",
        "find $UNKNOWN -name x",
        "git status",
        "cat <<'EOF'\nfind / -name x\nEOF",
        "find ~/src/* -name x",
        "git log | grep -i needle",
        "find /usr/local/lib -name x",
        "find /c/Users/tester/src -name x",
        "find 'C:\\Users\\tester\\src' -name x",
        "find /mnt/data -name x",
    ]
    # 作業場がホームのときも通す形(起点を取らない呼び出し)
    PASS_IN_HOME = [
        "rg --version",
        "fd --help",
        "find --version",
        "command -v rg",
        "nice -n 19 pytest -k find",
        "fd -V",
    ]

    def test_stops_wide_starts(self):
        for command in self.STOP:
            with self.subTest(command=command):
                reason, _ = run("Bash", {"command": command})
                self.assertIsNotNone(reason, "止まらなかった")
                self.assertIn("searchgate", reason)
                self.assertIn("逃げ道は無い", reason)

    def test_passes_narrow_starts(self):
        for command in self.PASS:
            with self.subTest(command=command):
                reason, out = run("Bash", {"command": command})
                self.assertIsNone(reason, out)

    def test_passes_calls_without_a_start(self):
        for command in self.PASS_IN_HOME:
            with self.subTest(command=command):
                reason, out = run("Bash", {"command": command}, cwd=HOME)
                self.assertIsNone(reason, out)

    def test_names_the_start_it_stopped(self):
        reason, _ = run("Bash", {"command": "find ~ -name x"})
        self.assertIn("find の起点 /home/tester は", reason)

    @unittest.skipIf(os.name == "nt", "cd の行き先は Windows では cygpath で Windows の形に直る(coldread と同じ読み方)")
    def test_relative_start_after_cd(self):
        self.assertIsNotNone(run("Bash", {"command": "cd / && find . -name x"})[0])
        self.assertIsNone(run("Bash", {"command": "cd /tmp && find . -name x"})[0])
        self.assertIsNotNone(run("Bash", {"command": "cd ~; find . -name x"})[0])
        self.assertIsNotNone(run("Bash", {"command": "cd /\nrg needle"})[0])
        self.assertIsNotNone(run("Bash", {"command": "cd && find . -name x"})[0])

    def test_drive_start_is_not_joined_to_cwd(self):
        # ドライブの形の起点(D:\)は絶対で、cwd に繋がない(繋ぐと /home/tester/src/repo/D: になって通っていた)
        self.assertIsNotNone(run("Bash", {"command": "find 'D:\\' -name x"})[0])

    @unittest.skipUnless(os.name == "nt", "C:\\… の cwd は Windows の Claude Code だけが渡す(ほかの OS では絶対のパスでないので cd の読み方が捨てる)")
    def test_relative_start_in_windows_cwd(self):
        self.assertIsNone(run("Bash", {"command": "find src -name x"}, cwd="C:\\Users\\tester\\repo")[0])
        self.assertIsNotNone(run("Bash", {"command": "find .. -name x"}, cwd="C:\\Users\\tester")[0])

    def test_relative_start_in_wide_cwd(self):
        self.assertIsNotNone(run("Bash", {"command": "find . -name x"}, cwd=HOME)[0])
        self.assertIsNotNone(run("Bash", {"command": "rg needle"}, cwd="/")[0])


class Tools(unittest.TestCase):
    def test_glob(self):
        stop = [{"pattern": "**/research.json", "path": "/"},
                {"pattern": "/Users/**/x.ts"},
                {"pattern": "**/x.ts", "path": "~"},
                {"pattern": "/home/tester/**/x"},
                {"pattern": "C:/**/x"},
                {"pattern": "**/x", "path": "C:\\Users"},
                {"pattern": "**/x", "path": "D:\\"}]
        for args in stop:
            with self.subTest(args=args):
                self.assertIsNotNone(run("Glob", args)[0])
        self.assertIsNotNone(run("Glob", {"pattern": "**/x"}, cwd=HOME)[0])
        passes = [{"pattern": "**/*.py"},
                  {"pattern": "**/x", "path": "/home/tester/.cache/works-factory"},
                  {"pattern": "/home/tester/.cache/**/x"},
                  {"pattern": "src/a.py"},
                  {"pattern": "~/.zshrc"},
                  {"pattern": "/opt/homebrew"},
                  {"pattern": "C:/Users/tester/src/**/x"},
                  {"pattern": "**/x", "path": "C:\\Users\\tester\\src"}]
        for args in passes:
            with self.subTest(args=args):
                self.assertIsNone(run("Glob", args)[0])

    def test_grep(self):
        self.assertIsNotNone(run("Grep", {"pattern": "x", "path": "/"})[0])
        self.assertIsNotNone(run("Grep", {"pattern": "x", "path": "$HOME"})[0])
        self.assertIsNone(run("Grep", {"pattern": "x", "path": "/home/tester/src"})[0])
        self.assertIsNone(run("Grep", {"pattern": "/"})[0])

    def test_other_tools_pass(self):
        self.assertIsNone(run("Read", {"file_path": "/"})[0])


class FailClosed(unittest.TestCase):
    def test_unreadable_input_is_stopped(self):
        reason, _ = run(None, None, raw="not json")
        self.assertIn("検査自体に失敗した", reason)

    def test_stop_is_logged(self):
        with tempfile.TemporaryDirectory() as cfg:
            env = dict(os.environ, HOME=HOME, CLAUDE_CONFIG_DIR=cfg)
            data = json.dumps({"tool_name": "Bash", "tool_input": {"command": "find / -name x"}, "cwd": WORK})
            subprocess.run([sys.executable, str(HOOK)], input=data.encode("utf-8"), capture_output=True, env=env)
            log = pathlib.Path(cfg, "searchgate", "denies.log").read_text(encoding="utf-8")
            self.assertIn("deny find /", log)


if __name__ == "__main__":
    unittest.main(verbosity=1)
