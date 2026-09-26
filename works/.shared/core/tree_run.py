"""コマンドを自分のプロセスグループで走らせ、止めるときは木ごと止める殻（標準ライブラリだけ）。

Archon は節を止める（Ctrl-C・SIGTERM・期限）とき直下の子だけを止め、テストが背景に起こした孫は生き残って
作業ツリーに書き続ける（試作で実測: 期限の 2 分後に孫の subshell がファイルを書いた）。graphloops の
engine/role_run.py（_tree_members・_stop_tree。本線 9f91687 = graphloops 0.21.1 の子の制御の層）と同じ式で塞ぐ:
- コマンドを新しいセッション（= 新しいプロセスグループ）で起こす
- 止めるときは **数え上げ→送る→数え直し**。木の仲間は ps の全プロセスの表から拾う: グループの番号かセッションの番号が
  長の番号のもの（setpgid で出た孫もセッションは抜けない）と、それらと前の回に数えた仲間から親子の鎖で辿れる子孫（setsid で
  別のセッションへ出た孫）。送り先は生きた仲間から作り（ゾンビだけのグループへは送らない——macOS は EPERM で拒む）、
  送った後は数えた生きた仲間が消えるまで待つ
- SIGINT・SIGTERM・SIGHUP を受けたら、受けた信号と SIGTERM を仲間へ送り、KILL_GRACE 秒の内に消えなければ SIGKILL を送る。
  **止めたと数えるのは、数え直して生きた仲間が居ない時**。ps が読めない回はグループへだけ送り、グループが空になるまで待つ
- 殻の直下の親（節では uv）が替わったら（kill -9 で消えて孤児になった）同じく木ごと止める（POLL 秒ごとに見る）。
  起きた時に既に親が 1（直下の親が先に消えた）なら、替わりを待てないので何も起こさずに止まる。
  見るのは直下の親だけ: uv が生きたまま Archon だけが kill -9 された回は気づかない（bash の節だった頃と同じ限界）。
  PID 1 の殻（コンテナの sh など）の子として手で起こすと、いつも孤児と見なして走らない
- コマンドが自分で終わった後も、背景に残した孫を同じ手順で止める（節が終わった後に作業ツリーを書く物を残さない）
抜け道: 数える前に親が消えて親子の鎖が切れ、かつ setsid でセッションも抜けた子孫（二重 fork の daemon 化。コマンドが
終わった後の `setsid … &` もこの形）は拾えない（本線と同じ限界）。止め切れなかった仲間は標準エラーに名指しする。

使い方: `python3 tree_run.py -- <コマンド>`（-- の後の語は空白で繋いで 1 行にし /bin/sh -c で走らせる。
語が無ければ環境変数 INPUTS_CMD）。終了コードはコマンドの終了コード、信号で死んだら 128+信号、殻が止められたら
128+受けた信号（直下の親が消えた回は SIGHUP）、コマンドが空なら 2。関数として使う側は run(argv, **Popen の引数) を呼ぶ。
"""
import collections
import os
import signal
import subprocess
import sys
import time

KILL_GRACE = 2    # SIGTERM から SIGKILL までの猶予（秒）。Archon の cancel の猶予（SIGTERM → 5 秒 → SIGKILL）より短くする:
                  # 同じ 5 秒だと、SIGTERM を無視する孫へ SIGKILL を送る前に殻が Archon に殺され、孫が残った（試し P11）
POLL = 0.2        # 信号と親の替わりを見る間隔（秒）
STOP_SIGNALS = (signal.SIGINT, signal.SIGTERM, signal.SIGHUP)
REUSE_SLACK = 2.0   # 開始時刻の読みの誤差（ps の etime は秒の切り捨て）。長を起こした時刻よりこれを超えて後に始まった物は別物
_Proc = collections.namedtuple("_Proc", "pid ppid pgid uid started stat")   # ps の 1 行（started は開始時刻のエポック秒）


class Stopped(Exception):
    """殻が止められ、木ごと止め終えた。signum は受けた信号（直下の親が消えた回は SIGHUP）"""

    def __init__(self, signum):
        super().__init__(signum)
        self.signum = signum


def _answers(send, target):
    """信号 0 の問い: 相手が居る（届く・EPERM）なら真、居なければ偽"""
    try:
        send(target, 0)
    except ProcessLookupError:
        return False
    except OSError:
        return True
    return True


def parse_etime(s):
    """ps の etime（[[dd-]hh:]mm:ss）を秒に。読めなければ None"""
    try:
        days, _, rest = s.strip().rpartition("-")
        parts = [int(x) for x in rest.split(":")]
        if not 2 <= len(parts) <= 3:
            return None
        h, m, sec = ([0] + parts)[-3:]
        return (int(days) if days else 0) * 86400 + h * 3600 + m * 60 + sec
    except ValueError:
        return None


def _ps_all():
    """全プロセスの表 ——({pid: _Proc}, None)。読めなければ (None, 理由)。開始時刻は ps を起こす**前**の時刻から etime を
    引く（後から引くと ps の遅れが開始時刻に乗り、番号の再利用の見分けを誤る）。本線 role_run._ps_all の写し"""
    now = time.time()
    try:
        r = subprocess.run(["ps", "-A", "-o", "pid=,ppid=,pgid=,uid=,etime=,stat="], stdin=subprocess.DEVNULL,
                           capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30)
    except (OSError, subprocess.SubprocessError) as e:
        return None, f"ps を起こせない（{e}）"
    rows = {}
    for line in r.stdout.splitlines():
        f = line.split()
        secs = parse_etime(f[4]) if len(f) >= 6 else None
        if secs is None or not all(x.lstrip("-").isdigit() for x in f[:4]):
            continue
        rows[int(f[0])] = _Proc(int(f[0]), int(f[1]), int(f[2]), int(f[3]), now - secs, f[5])
    if r.returncode != 0 or not rows:
        return None, f"ps が全プロセスの表を返さない（exit {r.returncode}: {r.stderr.strip()[-200:]}）"
    return rows, None


def _tree_members(pgid, known=None, born=None):
    """木の仲間を数え上げる ——({pid: _Proc}, 理由)。表が読めなければ (None, 理由)。本線 role_run._tree_members の写し。
    拾う印は 3 つ: pgid が長の番号・セッションの番号が長の番号（長は setsid で起こしてある）・その 2 つと known（前の回に
    数えた {pid: 開始時刻}。今の表に同じ開始時刻で居るものだけ）から親子の鎖で辿れる子孫（setsid で出た孫）。
    born（長を起こした時刻）より REUSE_SLACK を超えて後に始まったプロセスが長の番号に居れば、番号は再利用されている
    （グループもセッションも在る限り番号は再利用されない）ので、グループとセッションでは拾わない。
    呼んだ自分と自分の祖先は数えない。セッションの番号を読めない同じ利用者のプロセスが在れば、仲間かを決められないと
    理由を返す"""
    rows, why = _ps_all()
    if rows is None:
        return None, why
    uid, sessions, unreadable = os.getuid(), {}, []
    for pid, row in rows.items():
        try:
            sessions[pid] = os.getsid(pid)
        except ProcessLookupError:
            pass
        except PermissionError:
            if row.uid == uid:
                unreadable.append(pid)
    mine, cur = set(), os.getpid()
    while cur in rows and cur not in mine:
        mine.add(cur)
        cur = rows[cur].ppid
    reused = born is not None and pgid in rows and rows[pgid].started > born + REUSE_SLACK
    found = set() if reused else {pid for pid, row in rows.items() if row.pgid == pgid or sessions.get(pid) == pgid}
    found |= {pid for pid, t in (known or {}).items() if pid in rows and abs(rows[pid].started - t) <= REUSE_SLACK}
    children = {}
    for pid, row in rows.items():
        children.setdefault(row.ppid, []).append(pid)
    todo = list(found)
    while todo:
        for c in children.get(todo.pop(), ()):
            if c not in found:
                found.add(c)
                todo.append(c)
    found -= mine
    lost = [pid for pid in unreadable if pid not in found and pid not in mine]
    why = f"セッションの番号を読めないプロセスが在り、木の仲間かを決められない（pid {lost[:5]}）" if lost else None
    return {pid: rows[pid] for pid in found}, why


def _live(members):
    return {pid: m for pid, m in members.items() if not m.stat.startswith("Z")}


def _name(members):
    return ", ".join(f"pid {m.pid}（pgid {m.pgid}・{m.stat}）" for m in list(members.values())[:5])


def stop_group(p, first=signal.SIGTERM, born=None):
    """p（長）の木を止める。返すのは止め切れなかった理由（None なら止まった・居なかった）。本線 role_run._stop_tree の式
    （数え上げ→送る→数え直し）で、猶予は KILL_GRACE、送る列は (first と SIGTERM) → SIGKILL:
    回ごとに仲間を数え上げ、生きた仲間が居なければ戻る。居れば、生きた仲間が属するグループのうち長が仲間のグループと
    p のグループへは killpg（数えた後に増えた子にも届く）、残りの仲間へは 1 本ずつ送り、数えた生きた仲間が消えるまで
    KILL_GRACE 秒待つ（長は待つ間に回収する）。SIGKILL の後に数え直して生きた仲間が残れば名指しの理由を返す。
    ps が読めない回は p のグループへだけ送り、グループが空になるまで待つ（外へ出た子孫は確かめていないと返す）。
    born は長の番号の再利用の目印で、長を回収した後にだけ効かせる（回収していない子の番号は再利用されない）"""
    def wait(done):
        end = time.monotonic() + KILL_GRACE
        while time.monotonic() < end:
            p.poll()
            if done():
                return
            time.sleep(0.05)

    def count():
        p.poll()
        return _tree_members(p.pid, known, born if p.returncode is not None else None)

    known = {}
    for sigs in ((first, signal.SIGTERM), (signal.SIGKILL,), ()):   # 空の回は送らずに数え直して判定だけ
        sigs = tuple(dict.fromkeys(sigs))
        members, why = count()
        if members is None:
            if not sigs:
                return f"止める相手を数え上げられない（{why}）——グループ {p.pid} の外へ出た子孫を確かめていない"
            for sig in sigs:
                try:
                    os.killpg(p.pid, sig)
                except OSError:
                    pass   # 既に空（ProcessLookupError は OSError の派生）
            wait(lambda: not _answers(os.killpg, p.pid))
            continue
        known.update({pid: m.started for pid, m in members.items()})
        live = _live(members)
        if not live:
            return why
        if not sigs:
            return f"グループ {p.pid} の木が SIGKILL の後も残っている（{_name(live)}）"
        groups = {m.pgid for m in live.values() if m.pgid in members or m.pgid == p.pid}
        targets = [(os.killpg, g) for g in sorted(groups)] + [(os.kill, pid) for pid, m in live.items() if m.pgid not in groups]
        for sig in sigs:
            for send, target in targets:
                try:
                    send(target, sig)
                except OSError:
                    pass   # 間に消えた・送れない（送れない相手は数え直しで残りとして名指しする）
        wait(lambda: not any(_answers(os.kill, pid) for pid in live))
    return None   # 届かない（最後の回は必ず返す）


def run(argv, **popen_kw):
    """argv を新しいプロセスグループで起こして終わりを待ち、終了コード（信号で死んだら 128+信号）を返す。
    待つ間（後始末の間も）に STOP_SIGNALS を受けたか直下の親が替わったら、木ごと止めて Stopped を投げる。
    起きた時に既に孤児（親が 1）なら起こさずに Stopped(SIGHUP)。どの道で抜けても木を止めに行き、止め切れなければ
    標準エラーに名指しする（抜け道はモジュールの説明）"""
    got = []
    old = {s: signal.signal(s, lambda signum, _f: got.append(signum)) for s in STOP_SIGNALS}
    ppid = os.getppid()
    p = None
    stopped = False

    def stop(first=signal.SIGTERM):
        nonlocal stopped
        why = stop_group(p, first, born)
        stopped = True
        if why:
            print(f"tree_run: 木を止め切れない: {why}", file=sys.stderr)

    try:
        if ppid == 1:
            raise Stopped(signal.SIGHUP)
        born = time.time()   # 長の番号の再利用の目印（_tree_members の born）
        p = subprocess.Popen(argv, start_new_session=True, **popen_kw)
        while True:
            if got or os.getppid() != ppid:
                signum = got[0] if got else signal.SIGHUP
                stop(signum)
                raise Stopped(signum)
            try:
                rc = p.wait(POLL)
                break
            except subprocess.TimeoutExpired:
                continue
        stop()      # 背景に残した孫
        if got:     # 待ち終えた後・後始末の間に届いた止める信号を落とさない
            raise Stopped(got[0])
        return rc if rc >= 0 else 128 - rc
    finally:
        if p is not None and not stopped:
            stop()
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
