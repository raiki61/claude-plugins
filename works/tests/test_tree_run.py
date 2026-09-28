"""コマンドを木ごと止める殻（.shared/core/tree_run.py）の検査。

- 終了コードをそのまま返す（0・3・信号で死んだら 128+信号）
- 殻が SIGTERM を受けたら、コマンドが背景に起こした孫まで止め、孫は後から作業ツリーに書かない
- SIGTERM を無視する孫は猶予の後に SIGKILL で止める。猶予は Archon の cancel の猶予（5 秒）より短く、その内に孫が消える
- コマンドが終わった後に背景に残した孫も止める
- 自分で setsid して別のセッション（= 別のグループ）へ出た孫も、殻が SIGTERM を受けたら止める（SIGTERM を無視しても
  Archon の猶予の内に SIGKILL で）
- 生きた仲間の居ないグループ（ゾンビだけ）に惑わされず、別のグループへ出た生きた仲間を止めて、猶予を使い切らずに戻る
- 殻の直下の親（節では uv）が kill -9 で消えたら（親が替わったら）木ごと止める。起きた時に既に孤児（親が 1）なら走らせない
- 終わりを待ち終えた直後に届いた止める信号も落とさない
- pack の中に __pycache__ を作らない
孫の生死はプロセスグループ（コマンドの sh の pid と同じ番号）が空かで見る。グループの外へ出た孫は、孫が書いた pid で見る。
"""
import os
import pathlib
import shlex
import signal
import subprocess
import sys
import tempfile
import threading
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
    @classmethod
    def setUpClass(cls):
        # 木ごと止める殻はプロセスのグループ（os.killpg・os.setsid。Python の公式文書で Availability: Unix）で孫を見る
        if not (hasattr(os, "killpg") and hasattr(os, "setsid")):
            raise unittest.SkipTest("SKIP process-group: この OS の os に killpg・setsid が無い")

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = pathlib.Path(self._tmp.name)
        self.pidf = self.tmp / "pgid"
        self.marker = self.tmp / "late"
        self.env = {k: v for k, v in os.environ.items() if k not in ("INPUTS_CMD", "PYTHONDONTWRITEBYTECODE")}
        # このテストが起こした物（後片付けで止める Popen・pgid・pid）。pgid・pid は消えたと確かめた時点で外す——
        # 確かめた後に同じ番号が別のプロセスに再利用されても、後片付けで送らない。Popen は回収済みなら送らない
        self.started = []

    def tearDown(self):
        for kind, n in self.started:
            try:
                if kind == "popen":
                    if n.poll() is None:
                        n.kill()
                        n.wait(5)
                else:
                    (os.killpg if kind == "pg" else os.kill)(n, signal.SIGKILL)
            except (OSError, subprocess.SubprocessError):
                pass
        self._tmp.cleanup()

    def group_gone(self, pgid, within):
        """group_gone と同じ。空と確かめたら後片付けの対象から外す"""
        gone = group_gone(pgid, within)
        if gone and ("pg", pgid) in self.started:
            self.started.remove(("pg", pgid))
        return gone

    def pid_gone(self, pid, within):
        """pid_gone と同じ。消えたと確かめたら後片付けの対象から外す"""
        gone = pid_gone(pid, within)
        if gone and ("pid", pid) in self.started:
            self.started.remove(("pid", pid))
        return gone

    def cli(self, *args):
        return [sys.executable, str(TREE_RUN), *args]

    def start(self, cmd, **kw):
        p = subprocess.Popen(self.cli("--", cmd), env=self.env, cwd=str(self.tmp), stdin=subprocess.DEVNULL,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **kw)
        self.started.append(("popen", p))
        return p

    def wait_pgid(self):
        pgid = read_int(self.pidf)
        self.started.append(("pg", pgid))
        return pgid

    def run_cli(self, *args, env=None):
        return subprocess.run(self.cli(*args), env=env or self.env, cwd=str(self.tmp), capture_output=True, text=True, encoding="utf-8",
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
        self.assertTrue(self.group_gone(pgid, 2), "孫が残った")
        time.sleep(4)
        self.assertFalse(self.marker.exists(), "止めた後に孫が書いた")

    def test_sigint_stops_background_that_ignores_sigint(self):
        # 非対話の sh は背景の子の SIGINT を無視させる。SIGINT を受けても SIGTERM まで送って木を止める
        p = self.start(f"echo $$ > {self.pidf}; sleep 300 & wait")
        pgid = self.wait_pgid()
        t0 = time.monotonic()
        p.send_signal(signal.SIGINT)
        # 木は猶予（KILL_GRACE）より短く消える。猶予まで待ったなら SIGTERM を送っていない。上限は猶予の 3/4: 止める手順は
        # ps を 2 回起こす（数え上げと数え直し）ので、負荷の高い機械（load average 100 前後）では半分の 1 秒を越えることがある。
        # 殻が抜けるのは木が消えてから LINGER 後なので、殻の終わりでなく木の消えた時で計る
        self.assertTrue(self.group_gone(pgid, tree_run.KILL_GRACE * 0.75), "SIGKILL の猶予まで待った（SIGTERM を送っていない）")
        self.assertLess(time.monotonic() - t0, tree_run.KILL_GRACE * 0.75)
        self.assertEqual(p.wait(10), 128 + signal.SIGINT)

    def test_sigterm_ignoring_grandchild_is_killed(self):
        p = self.start(f"echo $$ > {self.pidf}; (trap '' TERM; sleep 300) & wait")
        pgid = self.wait_pgid()
        p.send_signal(signal.SIGTERM)
        self.assertEqual(p.wait(15), 128 + signal.SIGTERM)
        self.assertTrue(self.group_gone(pgid, 1), "SIGTERM を無視する孫が残った")

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
        self.assertTrue(self.group_gone(pgid, archon_grace), "Archon の猶予の内に孫が消えなかった")
        self.assertLess(time.monotonic() - t0, archon_grace)
        self.assertEqual(p.wait(10), 128 + signal.SIGTERM)

    def test_leftover_background_is_stopped_after_exit(self):
        # コマンドは緑で終わったが背景に孫を残した。殻が戻る時には孫も居ない
        r = self.run_cli("--", f"sleep 300 & echo $! > {self.pidf}; exit 0")
        self.assertEqual(r.returncode, 0)
        pid = read_int(self.pidf)
        self.started.append(("pid", pid))
        self.assertTrue(self.pid_gone(pid, 2), "背景の孫が残った")

    def test_parent_death_stops_tree(self):
        # 殻の親（Archon が起こす uv の代わり）が kill -9 で消えたら、殻は親の替わりに気づいて木ごと止める
        cmd = f"echo $$ > {self.pidf}; sleep 300 & (sleep 3; echo late > {self.marker}) & wait"
        wrapper = ("import subprocess, sys, time\n"
                   f"p = subprocess.Popen([sys.executable, {str(TREE_RUN)!r}, '--', {cmd!r}], stdout=subprocess.DEVNULL)\n"
                   "print(p.pid, flush=True)\n"
                   "time.sleep(600)\n")
        w = subprocess.Popen([sys.executable, "-c", wrapper], env=self.env, cwd=str(self.tmp), stdin=subprocess.DEVNULL,
                             stdout=subprocess.PIPE, text=True, encoding="utf-8", start_new_session=True)
        self.started.append(("pg", w.pid))
        tree_pid = int(w.stdout.readline())
        self.started.append(("pid", tree_pid))
        pgid = self.wait_pgid()
        w.kill()
        w.wait(5)
        w.stdout.close()
        self.assertTrue(self.group_gone(pgid, 8), "親が消えた後に孫が残った")
        self.assertTrue(self.pid_gone(tree_pid, 8), "殻が残った")
        self.assertTrue(self.group_gone(w.pid, 2), "殻の親のグループが残った")
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

    def test_signal_during_launch_proof_stops_without_launching(self):
        # 起こす前の証明（bash の command -v。BASH_ENV を読む）が遅くても、その間に届いた SIGTERM で証明を捨て、コマンドを
        # 起こさずに Stopped にする（証明の待ちが Archon の cancel の猶予の勘定に足されない）
        slow = self.tmp / "slow-env.sh"
        slow.write_text("sleep 4\n")
        env = {**self.env, "BASH_ENV": str(slow)}
        argv = ["bash", "-c", f"touch {self.marker}"]
        launched = []

        class Seen(subprocess.Popen):
            def __init__(self, args, *a, **kw):
                launched.append(list(args))
                super().__init__(args, *a, **kw)

        timer = threading.Timer(0.3, os.kill, (os.getpid(), signal.SIGTERM))
        timer.start()
        self.addCleanup(timer.cancel)
        t0 = time.monotonic()
        with mock.patch.object(tree_run.subprocess, "Popen", Seen), self.assertRaises(tree_run.Stopped) as cm:
            tree_run.run(argv, env=env, cwd=str(self.tmp))
        self.assertEqual(cm.exception.signum, signal.SIGTERM)
        self.assertLess(time.monotonic() - t0, tree_run.POLL + tree_run.LINGER + 1.5, "証明を待ち切ってから止めた")
        self.assertNotIn(argv, launched, "止められたのにコマンドを起こした")

    # ------------------------------------------------ グループの外へ出た孫
    def setsid_sleeper(self, pidf, ignore_term=False):
        """setsid で新しいセッションへ出て、自分の pid を pidf に書いて眠る孫（python。macOS に setsid の道具は無い）"""
        body = ("import os, signal, time\n"
                + ("signal.signal(signal.SIGTERM, signal.SIG_IGN)\n" if ignore_term else "")
                + "os.setsid()\n"
                f"open({str(pidf)!r}, 'w').write(str(os.getpid()))\n"
                "time.sleep(300)\n")
        return f"{sys.executable} -c {shlex.quote(body)}"

    def wait_pid(self, path):
        pid = read_int(path)
        self.started.append(("pid", pid))
        return pid

    def test_sigterm_stops_setsid_grandchild(self):
        # 孫が setsid で別のセッション（別のグループ）へ出ても、親子の鎖で拾って止める
        gpidf = self.tmp / "gpid"
        p = self.start(f"echo $$ > {self.pidf}; {self.setsid_sleeper(gpidf)} & wait")
        pgid = self.wait_pgid()
        gpid = self.wait_pid(gpidf)
        self.assertEqual(os.getsid(gpid), gpid, "孫が setsid していない（試験の前提）")
        p.send_signal(signal.SIGTERM)
        self.assertTrue(self.pid_gone(gpid, tree_run.KILL_GRACE + 1), "setsid で出た孫が残った")
        self.assertEqual(p.wait(10), 128 + signal.SIGTERM)
        self.assertTrue(self.group_gone(pgid, 1))

    def test_sigterm_ignoring_setsid_grandchild_is_killed_before_archon_kills_tree_run(self):
        # setsid で出て SIGTERM も無視する孫も、Archon の cancel の猶予（5 秒）より前に SIGKILL で消える
        archon_grace = 5.0
        gpidf = self.tmp / "gpid"
        p = self.start(f"echo $$ > {self.pidf}; {self.setsid_sleeper(gpidf, ignore_term=True)} & wait")
        pgid = self.wait_pgid()
        gpid = self.wait_pid(gpidf)
        t0 = time.monotonic()
        p.send_signal(signal.SIGTERM)
        self.assertTrue(self.pid_gone(gpid, archon_grace), "Archon の猶予の内に setsid で出た孫が消えなかった")
        self.assertLess(time.monotonic() - t0, archon_grace)
        self.assertEqual(p.wait(10), 128 + signal.SIGTERM)
        self.assertTrue(self.group_gone(pgid, 1))

    def test_zombie_only_group_does_not_hide_live_members(self):
        # コマンドの sh（グループ G の長）が緑で終わった時、G に残るのはゾンビ Z だけ。Z の親 A は setpgid で別のグループへ
        # 出て（セッションは G のまま）Z を回収せずに眠る。macOS はゾンビだけのグループへの killpg を EPERM で拒むので、
        # グループだけを見ると A に届かず、猶予を使い切っても A が残る。仲間を数え上げて A を止め、猶予を待たずに戻る
        apidf = self.tmp / "apid"
        body = ("import os, time\n"
                "g = os.getpgid(0)\n"
                "os.setpgid(0, 0)\n"
                "z = os.fork()\n"
                "if z == 0:\n"
                "    os.setpgid(0, g)\n"
                "    os._exit(0)\n"
                "os.waitid(os.P_PID, z, os.WEXITED | os.WNOWAIT)\n"   # Z が終わるまで待つ。回収はしない（ゾンビのまま）
                f"open({str(apidf)!r}, 'w').write(str(os.getpid()))\n"
                "time.sleep(300)\n")
        p = self.start(f"echo $$ > {self.pidf}; {sys.executable} -c {shlex.quote(body)} & "
                       f"while [ ! -s {apidf} ]; do sleep 0.05; done; exit 0")
        pgid = self.wait_pgid()
        apid = self.wait_pid(apidf)
        t0 = time.monotonic()
        self.assertEqual(p.wait(15), 0)
        self.assertLess(time.monotonic() - t0, tree_run.KILL_GRACE * 1.5, "ゾンビだけのグループで猶予を使い切った")
        self.assertTrue(self.pid_gone(apid, 1), "ゾンビだけのグループの向こうの生きた仲間が残った")
        self.assertTrue(self.group_gone(pgid, 2))

    # ------------------------------------------------ 止めた後に抜ける前の待ち（試し P17 の Ctrl-C の穴）
    def test_stop_budget_is_under_archon_grace(self):
        # 信号に気づくまで POLL、SIGKILL まで KILL_GRACE + PS_TIMEOUT、抜けるまで LINGER。和が Archon の cancel の猶予
        # （5 秒）より短いこと（0.2 + 2 + 1 + 1 = 4.2 秒）
        archon_grace = 5.0
        self.assertGreaterEqual(tree_run.LINGER, 1.0)
        self.assertLess(tree_run.POLL + tree_run.KILL_GRACE + tree_run.PS_TIMEOUT + tree_run.LINGER, archon_grace)

    def test_stopped_run_lingers_before_exit_within_archon_grace(self):
        # 止める信号で木を止めた後、殻は LINGER 秒待ってから抜ける（節がすぐ死ぬと Archon の run が running のまま固まる。
        # 1 秒残ると failed になり resume できた——試し P17）。SIGTERM を無視する孫（猶予を使い切る道）でも、殻が抜けるのは
        # Archon の猶予（5 秒）より前
        archon_grace = 5.0
        for name, cmd in (("quick", "sleep 300 & wait"), ("ignores-term", "(trap '' TERM; sleep 300) & wait")):
            with self.subTest(name):
                pidf = self.tmp / f"pgid-{name}"
                p = subprocess.Popen(self.cli("--", f"echo $$ > {pidf}; {cmd}"), env=self.env, cwd=str(self.tmp),
                                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                self.started.append(("popen", p))
                pgid = read_int(pidf)
                self.started.append(("pg", pgid))
                t0 = time.monotonic()
                p.send_signal(signal.SIGTERM)
                self.assertTrue(self.group_gone(pgid, archon_grace), "木が消えなかった")
                t_gone = time.monotonic()
                self.assertEqual(p.wait(archon_grace), 128 + signal.SIGTERM)
                t_exit = time.monotonic()
                self.assertGreaterEqual(t_exit - t_gone, tree_run.LINGER - 0.1, "木を止めた後すぐに抜けた")
                self.assertLess(t_exit - t0, archon_grace, "Archon の猶予の内に抜けなかった")

    def test_normal_exit_does_not_linger(self):
        # コマンドが自分で終わった回は待たない（LINGER を大きくしても、すぐ戻る）
        with mock.patch.object(tree_run, "LINGER", 30, create=True):
            t0 = time.monotonic()
            self.assertEqual(tree_run.run(["/bin/sh", "-c", "exit 0"]), 0)
            self.assertLess(time.monotonic() - t0, 10)

    # ------------------------------------------------ ps が遅い・壊れている
    def test_slow_or_failing_ps_still_stops_before_archon_kills_tree_run(self):
        # ps が固まる・失敗する場でも、止める手順は Archon の cancel の猶予（5 秒）の内に SIGTERM を無視する孫へ SIGKILL を
        # 届ける。ps を待つのは PS_TIMEOUT 秒までで、読めなければグループへ直ちに送り、以後の回は ps を起こさない
        archon_grace = 5.0
        for name, body in (("slow", "exec sleep 8"), ("failing", "echo 壊れた >&2; exit 1")):
            with self.subTest(name):
                fake = self.tmp / f"bin-{name}"
                fake.mkdir()
                (fake / "ps").write_text(f"#!/bin/sh\n{body}\n")
                (fake / "ps").chmod(0o755)
                pidf = self.tmp / f"pgid-{name}"
                env = {**self.env, "PATH": f"{fake}{os.pathsep}{self.env.get('PATH', '')}"}
                p = subprocess.Popen(self.cli("--", f"echo $$ > {pidf}; (trap '' TERM; sleep 300) & wait"), env=env,
                                     cwd=str(self.tmp), stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                     stderr=subprocess.DEVNULL)
                self.started.append(("popen", p))
                pgid = read_int(pidf)
                self.started.append(("pg", pgid))
                t0 = time.monotonic()
                p.send_signal(signal.SIGTERM)
                self.assertTrue(self.group_gone(pgid, archon_grace), "ps が使えない場で、Archon の猶予の内に孫が消えなかった")
                self.assertLess(time.monotonic() - t0, archon_grace)
                self.assertEqual(p.wait(15), 128 + signal.SIGTERM)

    # ------------------------------------------------ pack を汚さない
    def test_no_bytecode_in_pack(self):
        self.assertEqual(self.run_cli("--", "true").returncode, 0)
        self.assertEqual(list(ROOT.rglob("__pycache__")), [])



class OutsideEnvCase(unittest.TestCase):
    """uv run の外の環境（tree_run.outside_env。blk-tests の run_tests と盤面の tree_runner が使う。台帳 R23）"""

    def test_strips_path_front_inside_uv(self):
        """uv run の中（UV_RUN_RECURSION_DEPTH が在る）: PATH の頭のこの python の bin を 1 度だけ外し、後ろの同じフォルダは残す。
        sys.prefix を指す VIRTUAL_ENV・UV_RUN_RECURSION_DEPTH・UV_NO_CONFIG を外し、PYTHONDONTWRITEBYTECODE=1 を立てる"""
        ours = os.path.dirname(sys.executable)
        env = tree_run.outside_env({"PATH": os.pathsep.join([ours, "/usr/bin", ours]), "UV_RUN_RECURSION_DEPTH": "1",
                                    "VIRTUAL_ENV": sys.prefix, "UV_NO_CONFIG": "1", "HOME": "/h"})
        self.assertEqual(env, {"PATH": os.pathsep.join(["/usr/bin", ours]), "PYTHONDONTWRITEBYTECODE": "1", "HOME": "/h"})

    def test_keeps_foreign_venv_and_outside_uv(self):
        """sys.prefix でない VIRTUAL_ENV（利用者の物）は残す。uv run の外なら PATH も VIRTUAL_ENV も触らない（UV_NO_CONFIG は外す）"""
        ours = os.path.dirname(sys.executable)
        env = tree_run.outside_env({"PATH": ours, "UV_RUN_RECURSION_DEPTH": "1", "VIRTUAL_ENV": "/elsewhere"})
        self.assertEqual(env, {"PATH": "", "VIRTUAL_ENV": "/elsewhere", "PYTHONDONTWRITEBYTECODE": "1"})
        env = tree_run.outside_env({"PATH": ours, "VIRTUAL_ENV": sys.prefix, "UV_NO_CONFIG": "1"})
        self.assertEqual(env, {"PATH": ours, "VIRTUAL_ENV": sys.prefix, "PYTHONDONTWRITEBYTECODE": "1"})

    def test_does_not_touch_given_mapping(self):
        src = {"UV_RUN_RECURSION_DEPTH": "1", "PATH": ""}
        tree_run.outside_env(src)
        self.assertEqual(src, {"UV_RUN_RECURSION_DEPTH": "1", "PATH": ""})


class LaunchProofShapeCase(unittest.TestCase):
    """起こす前の証明（tree_run.prove_launchable）が、bash では走るコマンドを見つからないと読まないこと"""

    def test_runnable_shapes_pass_the_proof(self):
        for cmd in ("true; echo done", "true|cat", "true&&true", "# note\ntrue", "FOO=1 true", "2>/dev/null true",
                    "2>&1 true", "10<&0 true", ">/dev/null true", "time true"):
            with self.subTest(cmd=cmd):
                self.assertEqual(subprocess.run(["bash", "-c", cmd], stdout=subprocess.DEVNULL).returncode, 0)
                tree_run.prove_launchable(["bash", "-c", cmd])


if __name__ == "__main__":
    unittest.main()
