#!/usr/bin/env python3
"""メインブランチへ入れる処理を、同じ clone（worktree を含む）で申し出た順に 1 本ずつ通す列（会社の形の [land] の queue）。

--land（landing.py）は、メインブランチの先頭へのリベースに入る直前に列へ申し出て、fast-forward して push し終えるまで列の先頭を持つ。
札とロックのファイルの形は my_notes の tools/land_queue.py と同じにして、
works-dispatch を import しない処理（my_notes の collect など）とも同じ列に並ぶ。
- 置き場は共通の .git（git rev-parse --git-common-dir）の下の、queue に書いたフォルダ。
- 申し出たときに `<time.time_ns() を 20 桁の 0 埋め>-<pid>.ticket` の札を作り、排他のロック（POSIX は flock、Windows は msvcrt.locking）を
  掛けて、終わるまで持つ。持つ処理が落ちれば OS が外す。
- 札は名の小さい順に並べる。ロックの外れた札は、持ち主の処理が落ちた物として消す。ただし作ってから GRACE 秒の札は、まだロックを
  掛ける前のこともあるので消さずに並べておく。
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


def alive(queue):
    """生きた札の名を順に返し、ロックの外れた札は消す。"""
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
            with contextlib.suppress(OSError):
                ticket.unlink()
        else:
            out.append(ticket.name)
    return out


@contextlib.contextmanager
def turn(queue, say=print, sleep=time.sleep):
    """列 queue（フォルダ）に入り、自分の番が来たら戻る。抜けると次の処理に順番を渡す。"""
    queue = Path(queue)
    queue.mkdir(parents=True, exist_ok=True)
    ticket = queue / f"{time.time_ns():020d}-{os.getpid()}.ticket"
    with open(ticket, "a+b") as mine:
        _try_lock(mine)
        try:
            with open(queue / "lock", "a+b") as gate:
                _wait(queue, ticket.name, gate, say, sleep)
                try:
                    yield
                finally:
                    _unlock(gate)
        finally:
            _unlock(mine)
            mine.close()
            with contextlib.suppress(OSError):
                ticket.unlink()


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

    def take(self, queue, say=print):
        if self._turn is None:
            t = turn(queue, say)
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
