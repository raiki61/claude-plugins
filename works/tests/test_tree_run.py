"""コマンドを木ごと止める殻（.shared/core/tree_run.py）の検査。

- 終了コードをそのまま返す（0・3・信号で死んだら 128+信号）
- 殻が SIGTERM を受けたら、コマンドが背景に起こした孫まで止め、孫は後から作業ツリーに書かない
- SIGTERM を無視する孫は猶予の後に SIGKILL で止める。猶予は Archon の cancel の猶予（5 秒）より短く、その内に孫が消える
- コマンドが終わった後に背景に残した孫も止める
- 殻の直下の親（節では uv）が kill -9 で消えたら（親が替わったら）木ごと止める。起きた時に既に孤児（親が 1）なら走らせない
- 終わりを待ち終えた直後に届いた止める信号も落とさない
- pack の中に __pycache__ を作らない
孫の生死はプロセスグループ（コマンドの sh の pid と同じ番号）が空かで見る。
"""
import os
import pathlib
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parents[1]
TREE_RUN = ROOT / ".shared" / "core" / "tree_run.py"
sys.dont_write_bytecode = True   # 下の import が pack の中に __pycache__ を作らないように
sys.path.insert(0, str(TREE_RUN.parent))

import tree_run  # noqa: E402


def group_gone(pgid, within):
    """within 秒の内にプロセスグループが空になれば True"""
    end = time.monotonic() + within
    while True:
        try:
            os.killpg(pgid, 0)
        except ProcessLookupError:
            return True
        except PermissionError:
            pass
        if time.monotonic() >= end:
            return False
        time.sleep(0.05)


def pid_gone(pid, within):
    end = time.monotonic() + within
    while True:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return True
        except PermissionError:
            pass
        if time.monotonic() >= end:
            return False
        time.sleep(0.05)


def read_int(path, within=10):
    """コマンドが書く pid のファイルを待って読む"""
    end = time.monotonic() + within
    while time.monotonic() < end:
        try:
            text = path.read_text().strip()
        except FileNotFoundError:
            text = ""
        if text:
            return int(text)
        time.sleep(0.05)
    raise AssertionError(f"{path} が書かれない")


class TreeRunCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = pathlib.Path(self._tmp.name)
        self.pidf = self.tmp / "pgid"
        self.marker = self.tmp / "late"
        self.env = {k: v for k, v in os.environ.items() if k not in ("INPUTS_CMD", "PYTHONDONTWRITEBYTECODE")}
        self.started = []   # このテストが起こした物（後片付けで止める pgid・pid）

    def tearDown(self):
        for kind, n in self.started:
            try:
                (os.killpg if kind == "pg" else os.kill)(n, signal.SIGKILL)
            except OSError:
                pass
        self._tmp.cleanup()

    def cli(self, *args):
        return [sys.executable, str(TREE_RUN), *args]

    def start(self, cmd, **kw):
        p = subprocess.Popen(self.cli("--", cmd), env=self.env, cwd=str(self.tmp), stdin=subprocess.DEVNULL,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **kw)
        self.started.append(("pid", p.pid))
        return p

    def wait_pgid(self):
        pgid = read_int(self.pidf)
        self.started.append(("pg", pgid))
        return pgid

    def run_cli(self, *args, env=None):
        return subprocess.run(self.cli(*args), env=env or self.env, cwd=str(self.tmp), capture_output=True, text=True,
                              timeout=60)

    # ------------------------------------------------ 終了コード
    def test_exit_codes(self):
        for cmd, want in (("true", 0), ("exit 3", 3), ("kill -KILL $$", 128 + signal.SIGKILL)):
            with self.subTest(cmd):
                self.assertEqual(self.run_cli("--", cmd).returncode, want)

    def test_output_passes_through(self):
        r = self.run_cli("--", "echo 出た; echo 誤り >&2")
        self.assertEqual((r.returncode, r.stdout, r.stderr), (0, "出た\n", "誤り\n"))

    def test_command_from_env(self):
        r = self.run_cli(env={**self.env, "INPUTS_CMD": "echo 環境から; exit 4"})
        self.assertEqual((r.returncode, r.stdout), (4, "環境から\n"))

    def test_empty_command_is_refused(self):
        for args, env in (((), self.env), (("--",), {**self.env, "INPUTS_CMD": "  "})):
            with self.subTest(args=args):
                r = self.run_cli(*args, env=env)
                self.assertEqual(r.returncode, 2)
                self.assertTrue(r.stderr)

    # ------------------------------------------------ 木ごと止める
    def test_sigterm_stops_grandchildren(self):
        # 孫 2 つ: 長い sleep と、3 秒後に作業ツリーへ書く物。殻を止めたら両方消え、書き込みは起きない
        p = self.start(f"echo $$ > {self.pidf}; sleep 300 & (sleep 3; echo late > {self.marker}) & wait")
        pgid = self.wait_pgid()
        p.send_signal(signal.SIGTERM)
        self.assertEqual(p.wait(10), 128 + signal.SIGTERM)
        self.assertTrue(group_gone(pgid, 2), "孫が残った")
        time.sleep(4)
        self.assertFalse(self.marker.exists(), "止めた後に孫が書いた")

    def test_sigint_stops_background_that_ignores_sigint(self):
        # 非対話の sh は背景の子の SIGINT を無視させる。SIGINT を受けても SIGTERM まで送って木を止める
        p = self.start(f"echo $$ > {self.pidf}; sleep 300 & wait")
        pgid = self.wait_pgid()
        t0 = time.monotonic()
        p.send_signal(signal.SIGINT)
        self.assertEqual(p.wait(10), 128 + signal.SIGINT)
        self.assertTrue(group_gone(pgid, 1))
        # 猶予（KILL_GRACE）より十分短く終わる。猶予まで待ったなら SIGTERM を送っていない
        self.assertLess(time.monotonic() - t0, tree_run.KILL_GRACE / 2, "SIGKILL の猶予まで待った（SIGTERM を送っていない）")

    def test_sigterm_ignoring_grandchild_is_killed(self):
        p = self.start(f"echo $$ > {self.pidf}; (trap '' TERM; sleep 300) & wait")
        pgid = self.wait_pgid()
        p.send_signal(signal.SIGTERM)
        self.assertEqual(p.wait(15), 128 + signal.SIGTERM)
        self.assertTrue(group_gone(pgid, 1), "SIGTERM を無視する孫が残った")

    def test_sigterm_ignoring_grandchild_is_killed_before_archon_kills_tree_run(self):
        # Archon の cancel は持ち主のグループへ SIGTERM を送り、5 秒（TERMINATION_GRACE_MS）待って SIGKILL を送る。
        # tree_run の猶予が同じ 5 秒だと、孫へ SIGKILL を送る前に tree_run が殺され、孫が残った（試し P11 の mode=c）。
        # SIGTERM を無視する孫も、Archon の猶予より前に消えていること
        archon_grace = 5.0
        self.assertLess(tree_run.KILL_GRACE, archon_grace)
        p = self.start(f"echo $$ > {self.pidf}; (trap '' TERM; sleep 300) & wait")
        pgid = self.wait_pgid()
        t0 = time.monotonic()
        p.send_signal(signal.SIGTERM)
        self.assertTrue(group_gone(pgid, archon_grace), "Archon の猶予の内に孫が消えなかった")
        self.assertLess(time.monotonic() - t0, archon_grace)
        self.assertEqual(p.wait(10), 128 + signal.SIGTERM)

    def test_leftover_background_is_stopped_after_exit(self):
        # コマンドは緑で終わったが背景に孫を残した。殻が戻る時には孫も居ない
        r = self.run_cli("--", f"sleep 300 & echo $! > {self.pidf}; exit 0")
        self.assertEqual(r.returncode, 0)
        pid = read_int(self.pidf)
        self.started.append(("pid", pid))
        self.assertTrue(pid_gone(pid, 2), "背景の孫が残った")

    def test_parent_death_stops_tree(self):
        # 殻の親（Archon が起こす uv の代わり）が kill -9 で消えたら、殻は親の替わりに気づいて木ごと止める
        cmd = f"echo $$ > {self.pidf}; sleep 300 & (sleep 3; echo late > {self.marker}) & wait"
        wrapper = ("import subprocess, sys, time\n"
                   f"p = subprocess.Popen([sys.executable, {str(TREE_RUN)!r}, '--', {cmd!r}], stdout=subprocess.DEVNULL)\n"
                   "print(p.pid, flush=True)\n"
                   "time.sleep(600)\n")
        w = subprocess.Popen([sys.executable, "-c", wrapper], env=self.env, cwd=str(self.tmp), stdin=subprocess.DEVNULL,
                             stdout=subprocess.PIPE, text=True, start_new_session=True)
        self.started.append(("pg", w.pid))
        tree_pid = int(w.stdout.readline())
        self.started.append(("pid", tree_pid))
        pgid = self.wait_pgid()
        w.kill()
        w.wait(5)
        w.stdout.close()
        self.assertTrue(group_gone(pgid, 8), "親が消えた後に孫が残った")
        self.assertTrue(pid_gone(tree_pid, 8), "殻が残った")
        time.sleep(3)
        self.assertFalse(self.marker.exists(), "親が消えた後に孫が書いた")

    def test_orphan_at_start_does_not_run(self):
        # 起きた時に既に親が 1（直下の親が先に消えた）なら、親の替わりを待てないので何も走らせずに止まる
        outer = (f"(sleep 0.5; exec {sys.executable} {TREE_RUN} -- 'echo ran > {self.marker}') "
                 ">/dev/null 2>&1 </dev/null & exit 0")
        subprocess.run(["/bin/sh", "-c", outer], env=self.env, cwd=str(self.tmp), timeout=10, check=True)
        time.sleep(3)
        self.assertFalse(self.marker.exists(), "孤児で起きたのにコマンドを走らせた")

    def test_signal_right_after_wait_is_not_dropped(self):
        # 子の終わりを待ち終えた直後（後始末の前）に届いた SIGTERM も、止められたとして Stopped にする
        class LateSignal(subprocess.Popen):
            def wait(self, timeout=None):
                rc = super().wait()
                os.kill(os.getpid(), signal.SIGTERM)
                return rc

        with mock.patch.object(tree_run.subprocess, "Popen", LateSignal):
            with self.assertRaises(tree_run.Stopped) as cm:
                tree_run.run(["/bin/sh", "-c", "exit 0"])
        self.assertEqual(cm.exception.signum, signal.SIGTERM)

    # ------------------------------------------------ pack を汚さない
    def test_no_bytecode_in_pack(self):
        self.assertEqual(self.run_cli("--", "true").returncode, 0)
        self.assertEqual(list(ROOT.rglob("__pycache__")), [])


if __name__ == "__main__":
    unittest.main()
