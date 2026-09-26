"""コマンドを自分のプロセスグループで走らせ、止めるときは木ごと止める殻（標準ライブラリだけ）。

Archon は節を止める（Ctrl-C・SIGTERM・期限）とき直下の子だけを止め、テストが背景に起こした孫は生き残って
作業ツリーに書き続ける（試作で実測: 期限の 2 分後に孫の subshell がファイルを書いた）。graphloops の
engine/role_run.py（_spawn・_kill・kill_all）と同じ形で塞ぐ:
- コマンドを新しいセッション（= 新しいプロセスグループ）で起こす
- SIGINT・SIGTERM・SIGHUP を受けたら、受けた信号と SIGTERM をグループへ送り、KILL_GRACE 秒の内に空にならなければ
  SIGKILL を送る。**止めたと数えるのはグループが空になった時**
- 殻の親が替わったら（親が kill -9 で消えて孤児になった）同じく木ごと止める（POLL 秒ごとに見る）
- コマンドが自分で終わった後も、背景に残した孫を同じ手順で止める（節が終わった後に作業ツリーを書く物を残さない）
抜け道: 孫が自分で setsid して別のグループに出た物は止められない。

使い方: `python3 tree_run.py -- <コマンド>`（-- の後の語は空白で繋いで 1 行にし /bin/sh -c で走らせる。
語が無ければ環境変数 INPUTS_CMD）。終了コードはコマンドの終了コード、信号で死んだら 128+信号、殻が止められたら
128+受けた信号（親が消えた回は SIGHUP）、コマンドが空なら 2。関数として使う側は run(argv, **Popen の引数) を呼ぶ。
"""
import os
import signal
import subprocess
import sys
import time

KILL_GRACE = 5    # SIGTERM から SIGKILL までの猶予（秒）。role_run.KILL_GRACE と同じ
POLL = 0.2        # 信号と親の替わりを見る間隔（秒）
STOP_SIGNALS = (signal.SIGINT, signal.SIGTERM, signal.SIGHUP)


class Stopped(Exception):
    """殻が止められ、木ごと止め終えた。signum は受けた信号（親が消えた回は SIGHUP）"""

    def __init__(self, signum):
        super().__init__(signum)
        self.signum = signum


def _group_alive(pgid):
    """グループにまだ誰か居るか（kill(2) の sig 0）。送る権限が無いだけの回も『居る』と数える"""
    try:
        os.killpg(pgid, 0)
    except ProcessLookupError:
        return False
    except OSError:
        return True
    return True


def stop_group(p, first=signal.SIGTERM):
    """p（グループの頭）のグループを空にする: first と SIGTERM → KILL_GRACE 秒 → SIGKILL → KILL_GRACE 秒。
    直下の子は待って刈り取る（ゾンビもグループに『居る』と数えるため）。刈り取る親の居ない孤児のゾンビが
    残る場では猶予を使い切って戻る（有限）"""
    rounds = ((first, signal.SIGTERM), (signal.SIGKILL,))
    for sigs in rounds:
        for sig in dict.fromkeys(sigs):
            try:
                os.killpg(p.pid, sig)
            except OSError:
                pass   # 既に空（ProcessLookupError は OSError の派生）
        end = time.monotonic() + KILL_GRACE
        while time.monotonic() < end:
            p.poll()
            if not _group_alive(p.pid):
                return
            time.sleep(0.05)


def run(argv, **popen_kw):
    """argv を新しいプロセスグループで起こして終わりを待ち、終了コード（信号で死んだら 128+信号）を返す。
    待つ間に STOP_SIGNALS を受けたか親が替わったら木ごと止めて Stopped を投げる。どの道で抜けても木を残さない"""
    got = []
    old = {s: signal.signal(s, lambda signum, _f: got.append(signum)) for s in STOP_SIGNALS}
    ppid = os.getppid()
    p = None
    try:
        p = subprocess.Popen(argv, start_new_session=True, **popen_kw)
        while True:
            if got or os.getppid() != ppid:
                signum = got[0] if got else signal.SIGHUP
                stop_group(p, signum)
                raise Stopped(signum)
            try:
                rc = p.wait(POLL)
                break
            except subprocess.TimeoutExpired:
                continue
        stop_group(p)   # 背景に残した孫
        return rc if rc >= 0 else 128 - rc
    finally:
        if p is not None and _group_alive(p.pid):
            stop_group(p)
        for s, h in old.items():
            signal.signal(s, h)


def main(argv=None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if args[:1] == ["--"]:
        args = args[1:]
    cmd = " ".join(args) if args else os.environ.get("INPUTS_CMD", "")
    if not cmd.strip():
        print("tree_run: コマンドが空（-- の後か INPUTS_CMD に書く）", file=sys.stderr)
        return 2
    try:
        return run(["/bin/sh", "-c", cmd])
    except Stopped as e:
        return 128 + e.signum


if __name__ == "__main__":
    sys.exit(main())
