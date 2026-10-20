#!/usr/bin/env python3
"""メインブランチへ入れる処理を、同じ clone（worktree を含む）で申し出た順に 1 本ずつ通す列（会社の形の [land] の queue）。

--land（landing.py）は、メインブランチの先頭へのリベースに入る直前に列へ申し出て、fast-forward して push し終えるまで列の先頭を持つ。
works-dispatch の外のツールは、--queue-run（queuerun.py）でこの列に並んでコマンドを走らせる。札とロックのファイルの形は
my_notes の tools/land_queue.py と同じにしてあり、まだそれを使う処理（my_notes の collect など）とも同じ列に並ぶ。
- 置き場は共通の .git（git rev-parse --git-common-dir）の下の、queue に書いたフォルダ。
- 申し出たときに `<time.time_ns() を 20 桁の 0 埋め>-<pid>.ticket` の札を作り、排他のロック（POSIX は flock、Windows は msvcrt.locking）を
  掛けて、終わるまで持つ。持つ処理が落ちれば OS が外す。
- 札は名の小さい順に並べる。ロックの外れた札は、持ち主の処理が落ちた物として消す。ただし作ってから GRACE 秒の札は、まだロックを
  掛ける前のこともあるので消さずに並べておく。
- 申し出た処理が名乗れば（--land は部署の名前とブランチ）、札の横に `<札の名>.who` を置く。判断役が置き場の `order`（ORDER）に
  部署の名前かブランチを 1 行に 1 つ書けば、名乗りが当たる札をその順で前に出し、残りの札は名の順でその後に並べる（--land-order。
  docs/land.md）。order が無ければ名の順のまま。名乗らない札（my_notes の collect など）は order に当たらない。
  名乗った処理が列を抜けるとき、order から自分の名前とブランチの行を消す（同じ名前で後に申し出た処理を、前の指定で前に出さない）。
- 先頭の生きた札になったら、lock のファイルに排他のロックを（ロックが空くのを待たずに）掛けてみて、取れたら進む。取れなければ
  POLL 秒おいて、札の並びから見直す。2 本が同時に進まないことは lock が保つ。
  終われば、ロックを外して札を消す。
待つ長さに上限は置かない（期限を足さない決まり D5）。止めるのは人の Ctrl-C で、そのときも札を消して抜ける。
"""

import contextlib
import os
import time
from pathlib import Path

try:
    import fcntl
except ImportError:  # Windows
    fcntl = None
    import msvcrt

POLL = 1.0
GRACE = 10
ORDER = "order"   # 判断役が書く、入れる順（部署の名前かブランチを 1 行に 1 つ）
WHO = ".who"      # 札の横の名乗り（1 行目が部署の名前、2 行目がブランチ）


def _try_lock(handle):
    """handle のファイルに、待たずに排他のロックを掛ける。掛かれば True。"""
    try:
        if fcntl:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        else:
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
    except OSError:
        return False
    return True


def _unlock(handle):
    """Windows は閉じたときの外しが遅れうるので、閉じる前に外す。"""
    if not fcntl:
        with contextlib.suppress(OSError):
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)


def _age(name):
    """札の名の頭の時刻から、作ってからの秒。読めなければ大きな値。"""
    try:
        return (time.time_ns() - int(name[:20])) / 1e9
    except ValueError:
        return float("inf")


def who(queue, name):
    """札 name の名乗り（部署の名前, ブランチ）。名乗りが無ければ None。"""
    try:
        lines = (Path(queue) / (name + WHO)).read_text(encoding="utf-8").splitlines()
    except OSError:
        return None
    return (lines + ["", ""])[0], (lines + ["", ""])[1]


def order(queue):
    """判断役が書いた入れる順（部署の名前かブランチの並び）。無ければ空。# で始まる行と空の行は飛ばす。"""
    try:
        text = (Path(queue) / ORDER).read_text(encoding="utf-8")
    except OSError:
        return []
    return [line.strip() for line in text.splitlines() if line.strip() and not line.lstrip().startswith("#")]


def _ranked(queue, names):
    want = order(queue)
    if not want:
        return names

    def rank(name):
        hits = [want.index(x) for x in (who(queue, name) or ()) if x in want]
        return min(hits) if hits else len(want)
    return sorted(names, key=lambda n: (rank(n), n))


def alive(queue):
    """生きた札の名を入れる順（判断役の order、無ければ名の順）に返し、ロックの外れた札は消す。"""
    out = []
    for ticket in sorted(Path(queue).glob("*.ticket")):
        try:
            with open(ticket, "a+b") as handle:
                stale = _try_lock(handle)
                if stale:
                    _unlock(handle)
        except OSError:  # Windows でロックされた札は開けないことがある
            stale = False
        if stale and _age(ticket.name) > GRACE:
            for gone in (ticket, ticket.with_name(ticket.name + WHO)):
                with contextlib.suppress(OSError):
                    gone.unlink()
        else:
            out.append(ticket.name)
    return _ranked(queue, out)


@contextlib.contextmanager
def turn(queue, say=print, sleep=time.sleep, name=None):
    """列 queue（フォルダ）に入り、自分の番が来たら戻る。抜けると次の処理に順番を渡す。
    name は名乗り（部署の名前, ブランチ）で、判断役の order が順を決めるのに使う。"""
    queue = Path(queue)
    queue.mkdir(parents=True, exist_ok=True)
    ticket = queue / f"{time.time_ns():020d}-{os.getpid()}.ticket"
    label = ticket.with_name(ticket.name + WHO)
    with open(ticket, "a+b") as mine:
        while not _try_lock(mine):  # ほかの処理の alive() が一瞬ロックを取っている間は掛からない。掛けずに進むと札を消されて割り込む
            sleep(0.01)
        try:
            if name:
                label.write_text("\n".join(x or "" for x in name) + "\n", encoding="utf-8")
            with open(queue / "lock", "a+b") as gate:
                _wait(queue, ticket.name, gate, say, sleep)
                try:
                    yield
                finally:
                    _unlock(gate)
        finally:
            _unlock(mine)
            mine.close()
            for gone in (ticket, label):
                with contextlib.suppress(OSError):
                    gone.unlink()
            if name:
                with contextlib.suppress(OSError):
                    _forget(queue, name)


def _forget(queue, name):
    """列を抜けた処理の名乗り（部署の名前・ブランチ）に当たる行を order から消す（同じ名前で後に申し出た処理を、前の指定で前に出さない）。"""
    path = queue / ORDER
    lines = path.read_text(encoding="utf-8").splitlines()
    kept = [line for line in lines if line.strip() not in {x for x in name if x}]
    if kept == lines:
        return
    tmp = queue / f".order-{os.getpid()}"
    tmp.write_text("".join(line + "\n" for line in kept), encoding="utf-8")
    os.replace(tmp, path)


def _wait(queue, name, gate, say, sleep):
    told = None
    while True:
        names = alive(queue)
        ahead = names.index(name) if name in names else 0
        if not ahead and _try_lock(gate):
            return
        if ahead != told:
            say(f"メインブランチへ入れる列（{queue}）で待つ: 前に {ahead} 本" + (f"（先頭の札 {names[0]}）" if ahead else "（先頭。前の処理が lock を外すのを待つ）"))
            told = ahead
        sleep(POLL)


class Hold:
    """--land の 1 回が持つ列の順番。take は持っていなければ列に入って順番を待ち（回し直しで重ねて入らない）、drop は順番を手放す。"""

    def __init__(self):
        self._turn = None

    def take(self, queue, say=print, name=None):
        if self._turn is None:
            t = turn(queue, say, name=name)
            t.__enter__()
            self._turn = t

    def drop(self):
        t, self._turn = self._turn, None
        if t is not None:
            t.__exit__(None, None, None)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.drop()
