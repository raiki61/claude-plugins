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
- pack の中に __pycache__ を作らない（試験が持つ写しの pack で見る）
孫の生死はプロセスグループ（コマンドの sh の pid と同じ番号）が空かで見る。グループの外へ出た孫は、孫が書いた pid で見る。
"""
import json
import os
import pathlib
import shlex
import shutil
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
sys.path.insert(0, str(ROOT / "tests"))

import gitkit  # noqa: E402
import script_io  # noqa: E402
import tree_run  # noqa: E402
import webget  # noqa: E402

RERUN = "GRAPHLOOPS_RERUN_CHECKS"   # 本流の引かずに走らせる旗と同じ名


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
        body = ("import os, subprocess, time\n"
                "g = os.getpgid(0)\n"
                "os.setpgid(0, 0)\n"
                "z = os.fork()\n"
                "if z == 0:\n"
                "    os.setpgid(0, g)\n"
                "    os._exit(0)\n"
                # Z が終わるまで待つ。回収はしない（ゾンビのまま）。os.waitid（WNOWAIT）は macOS の Python 3.12 以前に無いので ps の状態で見る
                "while not subprocess.run(['ps', '-o', 'stat=', '-p', str(z)], capture_output=True,\n"
                "                         text=True).stdout.strip().startswith('Z'):\n"
                "    time.sleep(0.02)\n"
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
                # 木が消えたと見えた時刻 t_gone は見張りの間隔と負荷の分だけ遅れる（CI の macOS で 0.88 秒の実測）。
                # 守りたいのは「すぐ抜けない」ことなので、LINGER の半分を下限にする
                self.assertGreaterEqual(t_exit - t_gone, tree_run.LINGER / 2, "木を止めた後すぐに抜けた")
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
        # 共有の作業ツリーを見ると別の実行が残した __pycache__ を拾うので、この試験だけが持つ写しで起こす。
        # core ごと写す（tree_run.py は隣の slotwrap.sh を __file__ から引く）
        core = self.tmp / "core"
        shutil.copytree(TREE_RUN.parent, core, ignore=shutil.ignore_patterns("__pycache__"))
        r = subprocess.run([sys.executable, str(core / "tree_run.py"), "--", "true"], env=self.env, cwd=str(self.tmp),
                           capture_output=True, text=True, encoding="utf-8", timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(list(core.rglob("__pycache__")), [])



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


class CommandArgvCase(unittest.TestCase):
    def test_simple_words_are_direct(self):
        for cmd, argv in (("pytest", ["pytest"]), ("pytest -q tests", ["pytest", "-q", "tests"]),
                          ("  python3 -m pytest --x=1 ", ["python3", "-m", "pytest", "--x=1"]),
                          ("uv run pytest -k a-b", ["uv", "run", "pytest", "-k", "a-b"])):
            with self.subTest(cmd=cmd):
                self.assertEqual(tree_run.command_argv(cmd), (argv, "direct"))

    def test_shell_forms_go_through_bash(self):
        for cmd in ("a && b", "a || b", "a | b", "a; b", "a &", "a > log", "2>&1 a", "a < in", "(a)", "a $HOME", "a `b`",
                    "a *.py", "a ?", "a [x]", "a {1,2}", "~/bin/a", "a 'q r'", 'a "q"', "a\\ b", "a#b", "a # note",
                    "a\nb", "a\rb", "! a", "a ^ b", "FOO=1 a", "cd x", ". env", "source env", "command -v a", "exec a",
                    "export A=1", "if true", "for x", "while true", "time a", "echo x", "test -f x", "[ -f x ]",
                    "'unterminated", ""):
            with self.subTest(cmd=cmd):
                self.assertEqual(tree_run.command_argv(cmd), (["bash", "-c", cmd], "shell"))

    def test_direct_argv_means_what_bash_means(self):
        for cmd in ("printf-x a b", "x -q  --y=z", "a:b c,d e@f g+h %i"):
            argv, how = tree_run.command_argv(cmd)
            self.assertEqual(how, "direct")
            words = subprocess.run(["bash", "-c", f'set -- {cmd}; printf "%s\\n" "$@"'],
                                   capture_output=True, text=True, encoding="utf-8").stdout.splitlines()
            self.assertEqual(argv, words)

    def test_launch_kind_reads_126_127_as_red(self):
        self.assertEqual([tree_run.launch_kind(c) for c in (None, 0, 1, 126, 127)],
                         ["broken", "clean", "red", "red", "red"])


class SlotReuseCase(unittest.TestCase):
    """slotted_run の結果の使い回し: 同じ run の中で、同じ git の木・同じ argv・同じ環境の 2 度目は子を起こさない。
    置き場は run の盤面（ARTIFACTS_DIR）の下で、別の run は引かない。本物の git と本物の子のプロセスで試す"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = pathlib.Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        self.repo = self.tmp / "repo"
        self.repo.mkdir()
        (self.repo / "a.txt").write_text("1\n", encoding="utf-8")
        (self.repo / ".gitignore").write_text("ignored/\n", encoding="utf-8")
        gitkit.git(self.repo, "init", "-q")
        gitkit.git(self.repo, "add", "-A")
        gitkit.git(self.repo, "commit", "-q", "-m", "seed")
        self.count = self.tmp / "count"
        self.home = self.tmp / "home"
        self.art = self.tmp / "artifacts" / "run-a"
        self.env = {"PATH": os.environ["PATH"], "WORKS_TESTSLOT": "", webget.SHARED_ENV: str(self.home),
                    "ARTIFACTS_DIR": str(self.art)}
        self.n = 0
        outer = mock.patch.dict(os.environ, {}, clear=False)
        outer.start()
        self.addCleanup(outer.stop)
        os.environ.pop(RERUN, None)

    def launch(self, argv=None, *, env=None, outputs=(), cwd=None):
        """slotted_run を 1 回呼ぶ ——（終了コード, 出力, note）。argv の既定は count に 1 行足して out/err を書く sh"""
        argv = argv or ["sh", "-c", f'echo 1 >> {self.count}; echo out; echo err >&2']
        note = {}
        self.n += 1
        log = self.tmp / f"log-{self.n}"
        with open(log, "wb") as f:
            rc, _ = tree_run.slotted_run(argv, env or self.env, outputs=outputs, note=note, stdin=subprocess.DEVNULL,
                                         stdout=f, stderr=subprocess.STDOUT, cwd=str(cwd or self.repo))
        return rc, log.read_bytes(), note

    def fresh(self, name):
        """別の検査のために、数えのファイルと run の置き場を新しくする（同じ試験の中で検査を重ねる）"""
        self.count = self.tmp / f"count-{name}"
        self.env = {**self.env, "ARTIFACTS_DIR": str(self.tmp / "artifacts" / name)}

    def launched(self):
        return len(self.count.read_text(encoding="utf-8").split()) if self.count.exists() else 0

    def test_second_identical_run_does_not_launch(self):
        rc1, out1, note1 = self.launch()
        rc2, out2, note2 = self.launch()
        self.assertEqual((rc1, rc2, self.launched()), (0, 0, 1))
        self.assertEqual(out1, out2)
        self.assertIn(b"out", out2)
        self.assertNotIn("reused", note1)
        self.assertEqual(set(note2["reused"]), {"at", "took_s", "key", "entry", "from"})
        self.assertEqual(note2["reused"]["from"], "run-a")
        self.assertTrue(pathlib.Path(note2["reused"]["entry"]).is_file())
        # 木のファイルを 1 字変える・環境の値を 1 つ変えると走らせる
        (self.repo / "a.txt").write_text("2\n", encoding="utf-8")
        self.launch()
        self.assertEqual(self.launched(), 2)
        self.launch(env={**self.env, "SOME_FLAG": "x"})
        self.assertEqual(self.launched(), 3)
        # .gitignore に当たるファイルの変更は木に入らない
        (self.repo / "ignored").mkdir()
        (self.repo / "ignored" / "x").write_text("x", encoding="utf-8")
        self.launch()
        self.assertEqual(self.launched(), 3)
        for name in ("without_home_or_run_it_always_launches", "other_run_does_not_reuse", "merged_consumer_gets_both_streams",
                     "outputs_are_written_back"):
            with self.subTest(name):
                self.fresh(name)
                getattr(self, f"check_{name}")()

    def test_stale_output_is_not_kept(self):
        """緑で終わったのに outputs を書かなかった回は、前から残る古い報告を控えに入れない（控えに入れると、2 度目の書き戻しで
        古い報告が新しい時刻を得て、報告の鮮度の確かめを通ってしまう）。2 度目も古い報告は古いまま"""
        report = self.repo / "ignored" / "report.xml"
        report.parent.mkdir()
        report.write_text("<old/>\n", encoding="utf-8")
        old = time.time() - 3600
        os.utime(report, (old, old))
        argv = ["sh", "-c", f'echo 1 >> {self.count}']
        self.launch(argv, outputs=(report,))
        _, _, note = self.launch(argv, outputs=(report,))
        self.assertEqual(self.launched(), 1)
        self.assertIn("reused", note)
        self.assertLess(report.stat().st_mtime, time.time() - 1800, "古い報告を書き戻して新しく見せた")

    def test_entry_lives_under_run_board(self):
        """控えは run の盤面の下（ARTIFACTS_DIR/board/test-reuse）に置く: 包みの家の下には何も作らない"""
        self.launch()
        _, _, note = self.launch()
        self.assertEqual(self.launched(), 1)
        entry = pathlib.Path(note["reused"]["entry"])
        self.assertTrue(entry.is_file())
        self.assertEqual(entry.parent, self.art / script_io.BOARD_DIR / tree_run.REUSE_SUB)
        self.assertFalse((self.home / tree_run.REUSE_SUB).exists())

    def check_without_home_or_run_it_always_launches(self):
        """置き場は run の盤面の下なので、ARTIFACTS_DIR が無い呼びは 2 度とも走らせ、家が無い・相対の呼びは 2 度目を使い回す"""
        env = {k: v for k, v in self.env.items() if k != "ARTIFACTS_DIR"}
        self.launch(env=env)
        _, _, note = self.launch(env=env)
        self.assertEqual(self.launched(), 2)
        self.assertNotIn("reused", note)
        for name, home in (("no_home", None), ("relative_home", "relative/home")):
            with self.subTest(name):
                self.fresh(name)
                env = {k: v for k, v in self.env.items() if k != webget.SHARED_ENV}
                if home:
                    env[webget.SHARED_ENV] = home
                self.launch(env=env)
                _, _, note = self.launch(env=env)
                self.assertEqual(self.launched(), 1)
                self.assertIn("reused", note)

    def check_other_run_does_not_reuse(self):
        """使い回すのは同じ run の中だけ: 同じ家・同じ木・同じコマンドでも、別の run（ARTIFACTS_DIR の名が違う）は走らせる"""
        self.launch()
        _, _, note = self.launch(env={**self.env, "ARTIFACTS_DIR": str(self.tmp / "artifacts" / "run-b")})
        self.assertEqual(self.launched(), 2)
        self.assertNotIn("reused", note)
        self.launch()
        self.assertEqual(self.launched(), 2)

    def test_red_or_tree_changing_run_is_not_kept(self):
        red = ["sh", "-c", f'echo 1 >> {self.count}; exit 1']
        self.assertEqual(self.launch(red)[0], 1)
        rc, _, note = self.launch(red)
        self.assertEqual((rc, self.launched()), (1, 2))
        self.assertIn("reuse_off", note)
        self.assertNotIn("reused", note)
        # .gitignore の外にファイルを作る回は、緑でも置かない
        make = ["sh", "-c", f'echo 1 >> {self.count}; echo x > made.txt']
        _, _, note = self.launch(make)
        self.assertIn("reuse_off", note)
        (self.repo / "made.txt").unlink()
        self.launch(make)
        self.assertEqual(self.launched(), 4)   # 置かれていれば 2 度目は控えから使われ、子が起きない
        (self.repo / "made.txt").unlink()
        with self.subTest("not_a_git_tree_launches_and_says_why"):
            self.fresh("not_a_git_tree")
            self.check_not_a_git_tree_launches_and_says_why()

    def test_rerun_flag_runs_and_keeps_writing(self):
        show = ["sh", "-c", f'echo 1 >> {self.count}; env']
        with mock.patch.dict(os.environ, {RERUN: "1"}):
            _, out1, _ = self.launch(show)
            _, out2, note2 = self.launch(show)
        self.assertEqual(self.launched(), 2)
        self.assertNotIn("reused", note2)
        self.assertNotIn(RERUN.encode(), out1 + out2)
        # 旗を外した次の呼びは、旗の下で書いた結果に当たる
        _, _, note3 = self.launch(show)
        self.assertEqual(self.launched(), 2)
        self.assertIn("reused", note3)

    def test_per_node_vars_do_not_split_key_and_are_not_passed(self):
        show = ["sh", "-c", f'echo 1 >> {self.count}; env']
        first = {**self.env, "ARCHON_NODE_EXECUTION": "a", "INPUTS_X": "1", "ARCHON_HOME": "/h"}
        second = {**self.env, "ARCHON_NODE_EXECUTION": "b", "INPUTS_X": "2"}
        _, out, _ = self.launch(show, env=first)
        _, _, note = self.launch(show, env=second)
        self.assertEqual(self.launched(), 1)
        self.assertIn("reused", note)
        seen = {line.split(b"=", 1)[0] for line in out.splitlines() if b"=" in line}
        self.assertFalse({n for n in seen if n.startswith((b"ARCHON_", b"INPUTS_"))}, seen)
        self.assertNotIn(webget.SHARED_ENV.encode(), seen)
        self.assertIn(b"ARTIFACTS_DIR", seen)

    def test_tool_change_splits_key(self):
        script = self.tmp / "tool.sh"
        script.write_text(f"#!/bin/sh\necho 1 >> {self.count}\n", encoding="utf-8")
        script.chmod(0o755)
        self.launch([str(script)])
        self.launch([str(script)])
        self.assertEqual(self.launched(), 1)
        script.write_text(f"#!/bin/sh\necho 1 >> {self.count}\necho changed\n", encoding="utf-8")
        self.launch([str(script)])
        self.assertEqual(self.launched(), 2)

    def check_merged_consumer_gets_both_streams(self):
        """標準出力と標準エラーを別のファイルに受けた回の控えは、標準エラーを標準出力に併せる呼び手（TDD の輪の頭など）にも両方届く。
        逆に併せた回の控えを別々に受ける呼び手には、併せた出力が標準出力に、標準エラーは空で届く"""
        argv = ["sh", "-c", f'echo 1 >> {self.count}; echo to-out; echo to-err >&2']
        out, err = self.tmp / "split.out", self.tmp / "split.err"
        with open(out, "wb") as o, open(err, "wb") as e:
            tree_run.slotted_run(argv, self.env, stdin=subprocess.DEVNULL, stdout=o, stderr=e, cwd=str(self.repo))
        rc, merged, note = self.launch(argv)
        self.assertEqual((rc, self.launched()), (0, 1))
        self.assertIn("reused", note)
        self.assertEqual(sorted(merged.split()), [b"to-err", b"to-out"])
        (self.repo / "a.txt").write_text("3\n", encoding="utf-8")
        self.launch(argv)
        out2, err2 = self.tmp / "again.out", self.tmp / "again.err"
        with open(out2, "wb") as o, open(err2, "wb") as e:
            tree_run.slotted_run(argv, self.env, stdin=subprocess.DEVNULL, stdout=o, stderr=e, cwd=str(self.repo))
        self.assertEqual(self.launched(), 2)
        self.assertEqual(sorted(out2.read_bytes().split()), [b"to-err", b"to-out"])
        self.assertEqual(err2.read_bytes(), b"")

    def check_outputs_are_written_back(self):
        report = self.tmp / "report.xml"
        argv = ["sh", "-c", f'echo 1 >> {self.count}; echo "<r/>" > {report}']
        self.launch(argv, outputs=(report,))
        report.unlink()
        _, _, note = self.launch(argv, outputs=(report,))
        self.assertEqual(self.launched(), 1)
        self.assertIn("reused", note)
        self.assertEqual(report.read_text(encoding="utf-8"), "<r/>\n")

    def check_not_a_git_tree_launches_and_says_why(self):
        plain = self.tmp / "plain"
        plain.mkdir()
        self.launch(cwd=plain)
        _, _, note = self.launch(cwd=plain)
        self.assertEqual(self.launched(), 2)
        self.assertIn("reuse_off", note)

    def launch_new(self, argv=None, *, env=None, outputs=(), **extra):
        """launch と同じに slotted_run を 1 回呼ぶ。足した引数（skip など）を渡す。呼びが例外を上げたら試験の失敗として読める形で返す
        ——（終了コード, 出力, note）"""
        argv = argv or ["sh", "-c", f'echo 1 >> {self.count}; echo out; echo err >&2']
        note = {}
        self.n += 1
        log = self.tmp / f"log-{self.n}"
        try:
            with open(log, "wb") as f:
                rc, _ = tree_run.slotted_run(argv, env or self.env, outputs=outputs, note=note, stdin=subprocess.DEVNULL,
                                             stdout=f, stderr=subprocess.STDOUT, cwd=str(self.repo), **extra)
        except Exception as e:   # noqa: BLE001  試験の本文の失敗として読ませる（変異の実行器が見分ける）
            self.fail(f"slotted_run が例外を上げた: {type(e).__name__}: {e}")
        return rc, log.read_bytes(), note

    def entry_of(self, note):
        return pathlib.Path(note["reused"]["entry"])

    def rewrite_entry(self, path, edit):
        doc = json.loads(path.read_text(encoding="utf-8"))
        edit(doc)
        path.write_text(json.dumps(doc), encoding="utf-8")

    def test_skip_runs_child_and_keeps_writing(self):
        _, _, note1 = self.launch_new()
        self.assertEqual(self.launched(), 1)
        rc, _, note2 = self.launch_new(skip="呼び手の都合で引かない")
        self.assertEqual((rc, self.launched()), (0, 2))
        self.assertNotIn("reused", note2)
        self.assertIn("呼び手の都合で引かない", note2.get("reuse_off", ""))
        _, _, note3 = self.launch_new()
        self.assertEqual(self.launched(), 2)
        self.assertIn("reused", note3)

    def test_broken_entry_runs_child_and_says_why(self):
        report = self.tmp / "report.xml"

        def broken_base64(doc):
            doc["out"] = "!!broken!!"

        def longer_files(doc):
            doc["files"] = doc["files"] + [None]

        def missing_out(doc):
            del doc["out"]

        for name, edit, word in (("broken_base64", broken_base64, "base64"), ("files_length", longer_files, "files"),
                                 ("missing_field", missing_out, "KeyError")):
            with self.subTest(name):
                self.fresh(name)
                argv = ["sh", "-c", f'echo 1 >> {self.count}; echo out; echo "<r/>" > {report}']
                self.launch_new(argv, outputs=(report,))
                _, _, note2 = self.launch_new(argv, outputs=(report,))
                self.assertEqual(self.launched(), 1)
                self.rewrite_entry(self.entry_of(note2), edit)
                rc, log, note3 = self.launch_new(argv, outputs=(report,))
                self.assertEqual((rc, self.launched()), (0, 2))
                self.assertNotIn("reused", note3)
                self.assertEqual(log, b"out\n")
                self.assertIn(word, note3.get("reuse_off", ""))

    def test_red_entry_is_not_reused(self):
        """控えの JSON の終了コードを手で 1 に書き換えると、同じ呼びは控えを引かずに子を起こし、緑でないと名指す"""
        self.launch_new()
        _, _, note2 = self.launch_new()
        self.assertEqual(self.launched(), 1)
        self.rewrite_entry(self.entry_of(note2), lambda doc: doc.update(exit=1))
        rc, _, note3 = self.launch_new()
        self.assertEqual((rc, self.launched()), (0, 2))
        self.assertNotIn("reused", note3)
        self.assertIn("緑でない", note3.get("reuse_off", ""))

    def test_entry_with_other_material_is_not_reused(self):
        """材料（指紋の元）の違う控えを同じ名に置いても、同じ呼びは控えを引かずに子を起こし、材料が違うと名指す"""
        self.launch_new()
        _, _, note2 = self.launch_new()
        self.assertEqual(self.launched(), 1)
        self.rewrite_entry(self.entry_of(note2), lambda doc: doc["material"].update(os="other-os"))
        rc, _, note3 = self.launch_new()
        self.assertEqual((rc, self.launched()), (0, 2))
        self.assertNotIn("reused", note3)
        self.assertIn("材料", note3.get("reuse_off", ""))

    def test_entry_without_time_runs_child_without_partial_replay(self):
        report = self.tmp / "report.xml"
        argv = ["sh", "-c", f'echo 1 >> {self.count}; echo out; echo "<r/>" > {report}']
        self.launch_new(argv, outputs=(report,))
        _, _, note2 = self.launch_new(argv, outputs=(report,))
        self.rewrite_entry(self.entry_of(note2), lambda doc: doc.pop("at"))
        rc, log, note3 = self.launch_new(argv, outputs=(report,))
        self.assertEqual((rc, self.launched()), (0, 2))
        self.assertEqual(log.count(b"out"), 1, log)
        self.assertNotIn("reused", note3)
        self.assertTrue(note3.get("reuse_off"), note3)

    def test_writeback_failure_restores_log(self):
        report = self.tmp / "report.xml"
        argv = ["sh", "-c", f'echo 1 >> {self.count}; echo out; [ -d {report} ] || echo "<r/>" > {report}']
        self.launch_new(argv, outputs=(report,))
        report.unlink()
        report.mkdir()   # 書き戻し先がディレクトリ: IsADirectoryError
        rc, log, note = self.launch_new(argv, outputs=(report,))
        self.assertEqual((rc, self.launched()), (0, 2))
        self.assertNotIn("reused", note)
        self.assertEqual(log, b"out\n")
        self.assertNotIn(b"\x00", log)
        self.assertTrue(note.get("reuse_off"), note)

    def test_writeback_reason_names_what_could_not_be_undone(self):
        """書き戻しの失敗の片付けが効かなかった時、理由は『戻した』と言い切らず、戻せなかったパスを名指す"""
        first, blocked = self.tmp / "first.xml", self.tmp / "blocked"
        blocked.mkdir()   # 2 つ目の書き先がディレクトリ: 1 つ目を書いた後で IsADirectoryError
        entry = {"files": [b"<r/>", b"<r/>"], "std": [b"", b""]}
        with mock.patch.object(tree_run.os, "unlink", side_effect=PermissionError("no")):
            why = tree_run._write_back([((first, blocked), entry)], [{}])
        self.assertIn("戻せなかった", why)
        self.assertIn(str(first), why)
        self.assertNotIn("書いた分は戻した", why)
        first.unlink()
        self.assertIn("書いた分は戻した", tree_run._write_back([((first, blocked), entry)], [{}]))
        self.assertFalse(first.exists())

    def test_plain_miss_names_key(self):
        _, _, first = self.launch_new()
        _, _, second = self.launch_new()
        head = second["reused"]["key"][:12]
        self.assertRegex(first.get("reuse_off", ""), "同じ指紋の控えが無い")
        self.assertIn(head, first.get("reuse_off", ""))
        self.fresh("without_run")
        _, _, plain = self.launch_new(env={k: v for k, v in self.env.items() if k != "ARTIFACTS_DIR"})
        self.assertNotIn("reuse_off", plain)

    def test_entry_from_other_run_copy_is_not_reused(self):
        self.launch_new()
        _, _, note2 = self.launch_new()
        self.assertEqual(self.launched(), 1)
        src = self.entry_of(note2).parent
        dst = pathlib.Path(str(src).replace("run-a", "run-b"))
        self.assertNotEqual(src, dst)
        shutil.copytree(src, dst)   # 固定材料の写しと同じに、置き場を丸ごと別の run の場所へ
        rc, _, note = self.launch_new(env={**self.env, "ARTIFACTS_DIR": str(self.tmp / "artifacts" / "run-b")})
        self.assertEqual((rc, self.launched()), (0, 2))
        self.assertNotIn("reused", note)
        self.assertIn("run-a", note.get("reuse_off", ""))


if __name__ == "__main__":
    unittest.main()
