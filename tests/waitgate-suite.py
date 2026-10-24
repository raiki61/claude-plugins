"""gates の waitgate(gates/hooks/wait-gate.py): 手で書いた待ちのループを止め、待ちでないループと 1 回の探しは通す。

フックを本物と同じく別のプロセスで起動し、PreToolUse の入力(JSON)を stdin に渡して、deny の JSON か空の出力かを見る。
設定のフォルダ(CLAUDE_CONFIG_DIR。止めた記録の置き場)は一時の物にする。止める形と通す形は、写した元の
my_notes の tools/tests/test_no_wait_loop.py(master 2d951aab)の表と同じ。
"""

import json
import os
import pathlib
import subprocess
import sys
import tempfile
import unittest

sys.dont_write_bytecode = True
HOOK = pathlib.Path(__file__).resolve().parents[1] / "gates" / "hooks" / "wait-gate.py"


def run(command, tool="Bash", background=False, raw=None, cfg=None):
    """フックを起動する → (deny の理由か None, 標準出力)。"""
    with tempfile.TemporaryDirectory() as tmp:
        env = dict(os.environ, CLAUDE_CONFIG_DIR=cfg or tmp)
        tool_input = {"command": command}
        if background:
            tool_input["run_in_background"] = True
        data = raw if raw is not None else json.dumps({"tool_name": tool, "tool_input": tool_input, "cwd": tmp})
        p = subprocess.run([sys.executable, str(HOOK)], input=data.encode("utf-8"), capture_output=True, env=env)
        out = p.stdout.decode("utf-8")
        if p.returncode != 0:
            raise AssertionError("フックが落ちた(rc=%d): %s" % (p.returncode, p.stderr.decode("utf-8", "replace")))
        if not out.strip():
            return None, out
        got = json.loads(out)["hookSpecificOutput"]
        assert got["permissionDecision"] == "deny", out
        return got["permissionDecisionReason"], out


class FullCommandLine(unittest.TestCase):
    """コマンド行の全体から探す待ち(pgrep -f・pkill -0・ps | grep)。"""

    STOP = [
        # 2026-10-24 に 11 時間止まった形
        'sleep 20; while pgrep -f "research.py theme" >/dev/null; do sleep 5; done; echo done',
        'while pgrep -f "research.py (theme|respond)" >/dev/null; do sleep 5; done',
        'until ! pgrep -fl "research.py" >/dev/null; do sleep 5; done',
        'while pgrep -af "x.py" >/dev/null; do sleep 5; done',
        'while pgrep --full "x.py" >/dev/null; do sleep 5; done',
        "while pgrep -f x.py\ndo\n  sleep 5\ndone",
        'while true; do pgrep -f "x.py" || break; sleep 5; done',
        "for i in 1 2 3; do pgrep -f x.py || break; sleep 5; done",
        "(while pgrep -f x.py >/dev/null; do sleep 5; done; echo done) &",
        "while ps aux | grep -v grep | grep -q x.py; do sleep 5; done",
        "bash -c 'while pgrep -f \"x.py\"; do sleep 5; done'",
        "while ps aux 2>&1 | grep -q x.py; do sleep 5; done",
        "while ps aux |& grep -q x.py; do sleep 5; done",
        "while ps aux | egrep -q x.py; do sleep 5; done",
        "while ps aux | rg -q x.py; do sleep 5; done",
        "while pkill -0 -f x.py; do sleep 5; done",
        "while pidwait -f x.py; do sleep 5; done",
        "while pgrep -f x.py 2>&1 >/dev/null; do sleep 5; done",
        # 待ち(while・until、sleep を回す for)と同じコマンドに在れば止める
        "pgrep -fl research.py; while true; do sleep 5; done",
        # sleep の無い for でも pgrep -f は止める
        "pgrep -fl research.py; for f in /tmp/*.log; do tail -1 $f; done",
        "for i in 1 2 3; do pgrep -f x.py || true; done",
        "if true; then while pgrep -f x.py; do sleep 5; done; fi",
        # 入れ子の中も見る
        'eval "while pgrep -f x.py; do sleep 5; done"',
        'echo "$(while pgrep -f x.py; do sleep 5; done)"',
        "bash -o pipefail -c 'while pgrep -f x.py; do sleep 5; done'",
        "bash -euo pipefail -c 'while pgrep -f x.py; do sleep 5; done'",
        # sleep の無い for でも pgrep -f は止める(分けて打てば通る)
        "for pid in $(pgrep -f foo); do kill $pid; done",
    ]

    def test_stops(self):
        for command in self.STOP:
            with self.subTest(command=command):
                reason, _ = run(command)
                self.assertIsNotNone(reason, "止まらなかった")
                self.assertIn("waitgate", reason)
                self.assertIn("run_in_background", reason)


class SleepLoops(unittest.TestCase):
    """sleep を回す while・until。前景でも裏でも止める。"""

    STOP = [
        # 出力ファイルを取り違えて 27 分止まった形
        'until grep -qE "^(OK|FAILED|Ran )" out.txt; do sleep 5; done',
        # 前景で打っても時間の上限で裏へ移り、28 時間・16 時間回った形
        'until grep -q "^Ran \\|Traceback" out.txt; do sleep 3; done',
        'until [ "$(grep -c . scen.out)" -gt 3 ]; do sleep 10; done',
        "while [ ! -f done.flag ]; do sleep 2; done; echo ok",
        'while kill -0 "$(cat pid.txt)" 2>/dev/null; do sleep 5; done',
        "(until test -f x; do sleep 1; done) && echo ok",
        "time until test -f x; do sleep 1; done",
        "while pgrep -x research; do sleep 5; done",
        "while pgrep research.py; do sleep 5; done",
        "bash <<'EOF'\nwhile true; do sleep 5; done\nEOF",
        # 終わる条件の無い for は while と同じ
        "for ((;;)); do grep -q X f && break; sleep 3; done",
        "for (( ; ; )); do sleep 1; done",
        "bash -o pipefail -c 'until test -f x; do sleep 1; done'",
    ]
    PASS = [
        "python3 tools/check_route.py",
        "sleep 5; echo done",
        "for i in 1 2 3; do sleep 1; done",
        "while read l; do echo $l; done < f",
        # while read は行を読み終えれば終わる
        "while read u; do curl $u; sleep 1; done < urls",
        "while IFS= read -r u; do sleep 1; done < urls",
        "for ((i = 0; i < 3; i++)); do sleep 1; done",
    ]

    def test_stops_in_the_foreground_and_the_background(self):
        for command in self.STOP:
            for background in (False, True):
                with self.subTest(command=command, background=background):
                    reason, _ = run(command, background=background)
                    self.assertIsNotNone(reason, "止まらなかった")
                    self.assertIn("前景でも裏でも", reason)

    def test_passes(self):
        for command in self.PASS:
            for background in (False, True):
                with self.subTest(command=command, background=background):
                    reason, out = run(command, background=background)
                    self.assertIsNone(reason, out)


class Passes(unittest.TestCase):
    PASS = [
        "pgrep -f x.py",   # ループでない 1 回の探しは止めない
        'pgrep -x python3 && echo "while pgrep -f x.py; do sleep 5; done"',
        "while pgrep -x research; do :; done",   # sleep を回さない
        "for f in a b; do echo $f; done",
        "git commit -m 'while pgrep -f x.py; do sleep 5; done'",
        "cat <<'EOF'\nwhile pgrep -f x.py; do sleep 5; done\nEOF",
        # オプションや語の一部の until・for はループでない
        "python3 tools/usage.py --since X --until Y; pgrep -fl research.py",
        "ps aux | grep wait-for-it",
        "ps -o pid,command -p 1",
        "while read l; do ps aux; done < f",
        # sleep の無い for は回数が決まっていて待ちでない。ps | grep は通す
        "for f in a b; do lsof $f | xargs ps -p | grep -v PID; done",
        "for i in 1 2; do echo $i; done; ps aux | grep x",
        "ls",
        "ps aux | grep py | while read u pid _; do kill $pid; done",
        "pgrep -f x | while read p; do echo $p; done",
    ]

    def test_passes(self):
        for command in self.PASS:
            with self.subTest(command=command):
                reason, out = run(command)
                self.assertIsNone(reason, out)

    def test_other_tools_pass(self):
        self.assertIsNone(run("while pgrep -f x.py; do sleep 5; done", tool="Monitor")[0])
        self.assertIsNone(run("while pgrep -f x.py; do sleep 5; done", tool="Edit")[0])

    def test_bash_without_command_passes(self):
        self.assertIsNone(run(None, raw=json.dumps({"tool_name": "Bash", "tool_input": {}}))[0])


class FailClosed(unittest.TestCase):
    def test_unreadable_input_is_stopped(self):
        reason, _ = run(None, raw="not json")
        self.assertIn("検査自体に失敗した", reason)

    def test_command_that_is_not_a_string_is_stopped(self):
        reason, _ = run(None, raw=json.dumps({"tool_name": "Bash", "tool_input": {"command": ["while"]}}))
        self.assertIn("検査自体に失敗した", reason)

    def test_stop_is_logged(self):
        with tempfile.TemporaryDirectory() as cfg:
            run("while [ ! -f x ]; do sleep 1; done", cfg=cfg)
            log = pathlib.Path(cfg, "waitgate", "denies.log").read_text(encoding="utf-8")
            self.assertIn("deny while [ ! -f x ]", log)


class Registration(unittest.TestCase):
    def test_hook_is_registered_for_bash(self):
        hooks = json.loads((HOOK.parent / "hooks.json").read_text(encoding="utf-8"))["hooks"]["PreToolUse"]
        found = [h for g in hooks if g["matcher"] == "Bash" for h in g["hooks"] if "wait-gate.py" in h["command"]]
        self.assertEqual(len(found), 1)


if __name__ == "__main__":
    unittest.main(verbosity=1)
