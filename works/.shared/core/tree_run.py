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
- 止める信号（か親の替わり）で木を止めた後は、すぐ抜けずに LINGER 秒待ってから抜ける。Archon は Ctrl-C を受けると
  run を failed と書いてから抜けるが、節がすぐ死ぬとその書き込みが確定する前に CLI が抜け、run が running のまま固まって
  resume できず abandon しか残らなかった（試し P17: すぐ死ぬ節で 3/3、1 秒以上残る節で 5/5 が failed になり resume できた）。
  上限の勘定: 信号に気づくまで POLL、SIGKILL まで KILL_GRACE + PS_TIMEOUT、抜けるまで LINGER で 0.2 + 2 + 1 + 1 = 4.2 秒。
  Archon の cancel の猶予 5 秒より前に抜ける。コマンドが自分で終わった回は待たない。起こす前の証明（prove_launchable）の間に
  届いた信号は POLL の内に証明を捨て、コマンドを起こさずに LINGER 待って抜ける（PROOF_TIMEOUT は勘定に入らない）
- コマンドが自分で終わった後も、背景に残した孫を同じ手順で止める（節が終わった後に作業ツリーを書く物を残さない）
抜け道: 数える前に親が消えて親子の鎖が切れ、かつ setsid でセッションも抜けた子孫（二重 fork の daemon 化。コマンドが
終わった後の `setsid … &` もこの形）は拾えない（本線と同じ限界）。止め切れなかった仲間は標準エラーに名指しする。

使い方: `python3 tree_run.py -- <コマンド>`（-- の後の語は空白で繋いで 1 行にし /bin/sh -c で走らせる。
語が無ければ環境変数 INPUTS_CMD）。終了コードはコマンドの終了コード、信号で死んだら 128+信号、殻が止められたら
128+受けた信号（直下の親が消えた回は SIGHUP）、コマンドが空なら 2。関数として使う側は run(argv, **Popen の引数) を呼ぶ。
子に渡す環境は outside_env(os.environ) で uv run の外の形にする（blk-tests の run_tests と盤面の tree_runner。台帳 R23。
決まりを 1 か所に置くのは、線の CI と engine_run の CI で同じ宣言が片方だけ偽の赤になるのを防ぐため）。
"""
import collections
import errno
import os
import re
import shlex
import signal
import subprocess
import sys
import time

KILL_GRACE = 2    # SIGTERM から SIGKILL までの猶予（秒）。Archon の cancel の猶予（SIGTERM → 5 秒 → SIGKILL）より短くする:
                  # 同じ 5 秒だと、SIGTERM を無視する孫へ SIGKILL を送る前に殻が Archon に殺され、孫が残った（試し P11）
POLL = 0.2        # 信号と親の替わりを見る間隔（秒）
STOP_SIGNALS = (signal.SIGINT, signal.SIGTERM, signal.SIGHUP)
LINGER = 1.0      # 止める信号で木を止めた後、抜ける前に待つ秒数（試し P17 の Ctrl-C の穴。モジュールの説明に上限の勘定）
PS_TIMEOUT = 1.0  # 全プロセスの表（ps）を待つ上限（秒）。超えたら表を読めない回として扱う（stop_group の上限の勘定）
REUSE_SLACK = 2.0   # 開始時刻の読みの誤差（ps の etime は秒の切り捨て）。長を起こした時刻よりこれを超えて後に始まった物は別物
_Proc = collections.namedtuple("_Proc", "pid ppid pgid uid started stat")   # ps の 1 行（started は開始時刻のエポック秒）


class Stopped(Exception):
    """殻が止められ、木ごと止め終えた。signum は受けた信号（直下の親が消えた回は SIGHUP）"""

    def __init__(self, signum):
        super().__init__(signum)
        self.signum = signum


def outside_env(environ):
    """uv run が足した物を外した環境（写し。environ は書き換えない）。PYTHONDONTWRITEBYTECODE=1 は立てる——子（テスト）が
    作業ツリーに __pycache__ を作って修正の差分に紛れ込むのを止める（works の決まり。engine の run_steps は環境をそのまま継ぐ）。
    外すのは:
    - PATH の頭の、この python の bin（dirname(sys.executable) か sys.prefix/bin。実体のパスで比べる）。uv は頭に足すので
      頭だけを見て、同じフォルダは 1 度だけ外す（元の PATH に同じフォルダが在っても後ろの物は残る）
    - UV_RUN_RECURSION_DEPTH と、sys.prefix を指す VIRTUAL_ENV（uv が起こした環境。対象の .venv もここ）
    uv run の外で起こされた（UV_RUN_RECURSION_DEPTH が無い）ときは、下の UV_NO_CONFIG のほかは外さない。
    - UV_NO_CONFIG はいつも外す。利用者が Archon の環境に立てていても、テストのコマンド（`uv run pytest` など）には対象の
      [tool.uv]（私的な index など）を読ませる。渡すと公開の PyPI から解決して、偽の赤と依存の取り違えの口になる
    Archon は script の節を `uv run <ファイル>` で起こし、uv は PATH の頭に自分の python の bin を足し、VIRTUAL_ENV・
    UV_RUN_RECURSION_DEPTH を立てる。そのまま渡すと `python3 -m pytest` が uv の python を掴んで偽の赤になる。
    限界: 節に deps: を足すと uv は --with の層の bin も足し、それは外れない（今の節は deps を持たない）"""
    env = dict(environ)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env.pop("UV_NO_CONFIG", None)
    if env.pop("UV_RUN_RECURSION_DEPTH", None) is None:
        return env
    ours = {os.path.realpath(d) for d in (os.path.dirname(sys.executable), os.path.join(sys.prefix, "bin"))}
    parts = env.get("PATH", "").split(os.pathsep)
    while parts and parts[0] and os.path.realpath(parts[0]) in ours:
        ours.discard(os.path.realpath(parts.pop(0)))
    env["PATH"] = os.pathsep.join(parts)
    venv = env.get("VIRTUAL_ENV")
    if venv and os.path.realpath(venv) == os.path.realpath(sys.prefix):
        del env["VIRTUAL_ENV"]
    return env


SHELL_LAUNCH_CODES = (126, 127)   # シェルの予約値（POSIX.1-2024 2.8.2: 127 は見つからない・126 は見つかったが実行できない）
PROOF_TIMEOUT = 5.0   # 起こす前の証明（command -v）を待つ上限（秒）。超えたら証明できない回として起こす
_ASSIGN = re.compile(r"[A-Za-z_][A-Za-z0-9_]*=")
_UNPROVABLE = set("$`*?[{~")   # 展開される語は字面から引けない


def _first_word(cmd: str):
    """シェルのコマンド cmd の先頭の語と、その前の代入の前置き {名: 値}。字面から引けない（割れない・展開を含む・語でなく記号か
    向け直しで始まる）なら None"""
    lex = shlex.shlex(cmd, posix=True, punctuation_chars=True)
    lex.whitespace_split = True
    try:
        words = list(lex)
    except ValueError:
        return None
    assigns = {}
    while words and _ASSIGN.match(words[0]):
        name, _, value = words.pop(0).partition("=")
        if _UNPROVABLE & set(value):
            return None
        assigns[name] = value
    if not words or not words[0] or words[0][0] in lex.punctuation_chars or _UNPROVABLE & set(words[0]):
        return None
    if words[0].isdigit() and words[1:2] and words[1][0] in "<>":   # 2>log のような番号つきの向け直しで始まる
        return None
    return words[0], assigns


def prove_launchable(argv, cwd=None, env=None, halted=lambda: False):
    """bash -c の argv を起こす前に、中のコマンドの先頭の語を bash の command -v（POSIX: 見つからなければ >0 で何も起こさない）で
    引き、引けなければ起こさずに FileNotFoundError（パスの語でファイルは在る時は PermissionError）を上げる。呼ぶ側の OSError の道
    （exit None → broken → not_run）にそのまま乗る。bash -c でない argv は Popen 自身が起こせなさを OSError で上げるので見ない。
    引く間は POLL 秒ごとに halted() を見て、真なら引くのをやめて戻る（止める判断は呼ぶ側。run は証明の待ちを cancel の勘定に足さない）。
    限界: 見るのは先頭の語だけ（パイプの後ろ・&& の後ろ・sh に渡したスクリプトの有無は見ない）。展開を含む語は引かずに起こす"""
    if list(argv[:2]) != ["bash", "-c"] or len(argv) < 3:
        return
    got = _first_word(argv[2])
    if got is None:
        return
    word, assigns = got
    q = subprocess.Popen(["bash", "-c", 'command -v -- "$1" >/dev/null', "_", word], stdin=subprocess.DEVNULL,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, cwd=cwd, start_new_session=True,
                         env={**(os.environ if env is None else env), **assigns})
    deadline = time.monotonic() + PROOF_TIMEOUT
    while True:
        try:
            rc = q.wait(POLL)
            break
        except subprocess.TimeoutExpired:
            if halted() or time.monotonic() >= deadline:
                try:
                    os.killpg(q.pid, signal.SIGKILL)   # BASH_ENV が起こした子も残さない
                except OSError:
                    pass
                q.wait()
                return
    if rc == 0:
        return
    if "/" in word and os.path.exists(os.path.join(cwd or os.getcwd(), word)):
        raise PermissionError(errno.EACCES, "起こす前の証明（command -v）: 実行できない", word)
    raise FileNotFoundError(errno.ENOENT, "起こす前の証明（command -v）: 見つからない", word)


def launch_kind(code, argv) -> str:
    """argv で起こした段の終了コードの分類: "clean"（0）・"red"（走って落ちた）・"broken"（起こせない。exit None。bash -c の先頭の語が
    prove_launchable の証明を通らなかった回もここ）・"suspect"（argv が bash -c のシェル越しで SHELL_LAUNCH_CODES。先頭の語は証明を
    通ったのに、後ろの語・スクリプトの中など証明の見ない所の起こせなさはシェルの戻り値でしか見えないので、起こせなかった疑いとして
    赤と分ける。直に起こした段の 126・127 はその段自身の戻り値なので赤）。
    broken は engine の checks_reply の broken（exit is None）と同じ規則"""
    if code is None:
        return "broken"
    if code == 0:
        return "clean"
    if list(argv[:2]) == ["bash", "-c"] and code in SHELL_LAUNCH_CODES:
        return "suspect"
    return "red"


def _answers(send, target):
    """信号 0 の問い: 相手が居る（届く・EPERM）なら真、居なければ偽。ほかの誤りは上げる（本線 role_run._answers と同じ）"""
    try:
        send(target, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
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
                           capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=PS_TIMEOUT)
    except subprocess.TimeoutExpired:
        return None, f"ps が {PS_TIMEOUT} 秒の内に答えない"
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


def stop_group(p, first=signal.SIGTERM, born=None, known=None):
    """p（長）の木を止める。返すのは止め切れなかった理由（None なら止まった・居なかった）。本線 role_run._stop_tree の式
    （数え上げ→送る→数え直し）で、猶予は KILL_GRACE、送る列は (first と SIGTERM) → SIGKILL:
    回ごとに仲間を数え上げ、生きた仲間が居なければ戻る。居れば、生きた仲間が属するグループのうち長が仲間のグループと
    p のグループへは killpg（数えた後に増えた子にも届く）、残りの仲間へは 1 本ずつ送り、数えた生きた仲間が消えるまで
    待つ（長は待つ間に回収する）。SIGKILL の後に数え直して生きた仲間が残れば名指しの理由を返す。
    **上限**: 最初の回の待ちは止め始めから KILL_GRACE 秒で切る（ps を待った分も含める）。ps は PS_TIMEOUT 秒で切り、
    1 度でも表を読めなければ、以後の回は ps を起こさずに直ちに送る——送り先は p のグループと、前の回に数えて待ち終えても
    消えたのを見ていない仲間（番号は同じ相手のまま）。これで SIGKILL は止め始めから KILL_GRACE + PS_TIMEOUT 秒の内に出る
    （＋殻が信号に気づくまでの POLL。Archon の cancel の 5 秒より前）。表を読めなかった回は、外へ出た子孫を確かめていないと返す。
    born は長の番号の再利用の目印で、長を回収した後にだけ効かせる（回収していない子の番号は再利用されない）。
    known は呼ぶ側が前に数えた仲間 {pid: 開始時刻}（_tree_members の known。Claude の包みが走る間の見回りで溜めた物。
    同じ辞書に数えた仲間を足していく）。省けば空から数える"""
    t0 = time.monotonic()

    def wait(done, end):
        while time.monotonic() < end:
            p.poll()
            if done():
                return
            time.sleep(0.05)

    def watch(pids, group=False):
        """待つ間に消えたのを見た番号を pids から外していく done（group なら p のグループが空になるのも待つ）"""
        def done():
            pids.difference_update([pid for pid in list(pids) if not _answers(os.kill, pid)])
            return not pids and not (group and _answers(os.killpg, p.pid))
        return done

    known = {} if known is None else known
    blind, pending = None, set()   # blind: 表を読めなかった理由（以後は ps を起こさない）
    for i, sigs in enumerate(((first, signal.SIGTERM), (signal.SIGKILL,), ())):   # 空の回は送らずに数え直して判定だけ
        sigs = tuple(dict.fromkeys(sigs))
        end = t0 + KILL_GRACE if i == 0 else None
        if blind is None:
            p.poll()
            members, why = _tree_members(p.pid, known, born if p.returncode is not None else None)
            if members is None:
                blind = why
        if blind is not None:
            if not sigs:
                return f"止める相手を数え上げられない（{blind}）——グループ {p.pid} の外へ出た子孫を確かめていない"
            targets = [(os.killpg, p.pid)] + [(os.kill, pid) for pid in sorted(pending)]
            done = watch(pending, group=True)
        else:
            known.update({pid: m.started for pid, m in members.items()})
            live = _live(members)
            if not live:
                return why
            if not sigs:
                return f"グループ {p.pid} の木が SIGKILL の後も残っている（{_name(live)}）"
            groups = {m.pgid for m in live.values() if m.pgid in members or m.pgid == p.pid}
            targets = [(os.killpg, g) for g in sorted(groups)] + [(os.kill, pid) for pid, m in live.items() if m.pgid not in groups]
            pending = set(live)
            done = watch(pending)
        for sig in sigs:
            for send, target in targets:
                try:
                    send(target, sig)
                except OSError:
                    pass   # 間に消えた・送れない（送れない相手は数え直しで残りとして名指しする）
        wait(done, end if end is not None else time.monotonic() + KILL_GRACE)
    return None   # 届かない（最後の回は必ず返す）


def run(argv, **popen_kw):
    """argv を新しいプロセスグループで起こして終わりを待ち、終了コード（信号で死んだら 128+信号）を返す。bash -c の argv は起こす前に
    prove_launchable で中の先頭の語を引き、引けなければ起こさずに OSError。
    待つ間（後始末の間も）に STOP_SIGNALS を受けたか直下の親が替わったら、木ごと止め、LINGER 秒待ってから Stopped を投げる。
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

    def stopped_by(signum):
        """木を止め終えた後、LINGER 秒待ってから Stopped を投げる（待つ間に届いた信号は got に溜まるだけ）"""
        time.sleep(LINGER)
        return Stopped(signum)

    try:
        if ppid == 1:
            raise Stopped(signal.SIGHUP)
        prove_launchable(argv, popen_kw.get("cwd"), popen_kw.get("env"), lambda: bool(got) or os.getppid() != ppid)
        if got or os.getppid() != ppid:   # 証明の間に止められたら起こさない
            raise stopped_by(got[0] if got else signal.SIGHUP)
        born = time.time()   # 長の番号の再利用の目印（_tree_members の born）
        p = subprocess.Popen(argv, start_new_session=True, **popen_kw)
        while True:
            if got or os.getppid() != ppid:
                signum = got[0] if got else signal.SIGHUP
                stop(signum)
                raise stopped_by(signum)
            try:
                rc = p.wait(POLL)
                break
            except subprocess.TimeoutExpired:
                continue
        stop()      # 背景に残した孫
        if got:     # 待ち終えた後・後始末の間に届いた止める信号を落とさない
            raise stopped_by(got[0])
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
    for _s in (sys.stdout, sys.stderr):   # Windows の既定 cp1252 で日本語の出力が落ちないように
        if hasattr(_s, "reconfigure"):
            _s.reconfigure(encoding="utf-8")
    sys.exit(main())
