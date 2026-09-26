"""コマンドを自分のプロセスグループで走らせ、止めるときは木ごと止める殻（標準ライブラリだけ）。

Archon は節を止める（Ctrl-C・SIGTERM・期限）とき直下の子だけを止め、テストが背景に起こした孫は生き残って
作業ツリーに書き続ける（試作で実測: 期限の 2 分後に孫の subshell がファイルを書いた）。graphloops の
engine/role_run.py（_spawn・_kill・kill_all）と同じ形で塞ぐ:
- コマンドを新しいセッション（= 新しいプロセスグループ）で起こす
- SIGINT・SIGTERM・SIGHUP を受けたら、受けた信号と SIGTERM をグループへ送り、KILL_GRACE 秒の内に空にならなければ
  SIGKILL を送る。**止めたと数えるのはグループが空になった時**
- 殻の直下の親（節では uv）が替わったら（kill -9 で消えて孤児になった）同じく木ごと止める（POLL 秒ごとに見る）。
  起きた時に既に親が 1（直下の親が先に消えた）なら、替わりを待てないので何も起こさずに止まる。
  見るのは直下の親だけ: uv が生きたまま Archon だけが kill -9 された回は気づかない（bash の節だった頃と同じ限界）。
  PID 1 の殻（コンテナの sh など）の子として手で起こすと、いつも孤児と見なして走らない
- コマンドが自分で終わった後も、背景に残した孫を同じ手順で止める（節が終わった後に作業ツリーを書く物を残さない）
抜け道: 孫が自分で setsid して別のグループに出た物は止められない。

使い方: `python3 tree_run.py -- <コマンド>`（-- の後の語は空白で繋いで 1 行にし /bin/sh -c で走らせる。
語が無ければ環境変数 INPUTS_CMD）。終了コードはコマンドの終了コード、信号で死んだら 128+信号、殻が止められたら
128+受けた信号（直下の親が消えた回は SIGHUP）、コマンドが空なら 2。関数として使う側は run(argv, **Popen の引数) を呼ぶ。
子に渡す環境は outside_env(os.environ) で uv run の外の形にする（blk-tests の run_tests と盤面の tree_runner。台帳 R23。
決まりを 1 か所に置くのは、線の CI と engine_run の CI で同じ宣言が片方だけ偽の赤になるのを防ぐため）。
"""
import os
import signal
import subprocess
import sys
import time

KILL_GRACE = 2    # SIGTERM から SIGKILL までの猶予（秒）。Archon の cancel の猶予（SIGTERM → 5 秒 → SIGKILL）より短くする:
                  # 同じ 5 秒だと、SIGTERM を無視する孫へ SIGKILL を送る前に殻が Archon に殺され、孫が残った（試し P11）
POLL = 0.2        # 信号と親の替わりを見る間隔（秒）
STOP_SIGNALS = (signal.SIGINT, signal.SIGTERM, signal.SIGHUP)


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
    待つ間（後始末の間も）に STOP_SIGNALS を受けたか直下の親が替わったら、木ごと止めて Stopped を投げる。
    起きた時に既に孤児（親が 1）なら起こさずに Stopped(SIGHUP)。どの道で抜けても木を残さない"""
    got = []
    old = {s: signal.signal(s, lambda signum, _f: got.append(signum)) for s in STOP_SIGNALS}
    ppid = os.getppid()
    p = None
    try:
        if ppid == 1:
            raise Stopped(signal.SIGHUP)
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
        if got:         # 待ち終えた後・後始末の間に届いた止める信号を落とさない
            raise Stopped(got[0])
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
