"""プロセスをまたぐ排他の錠（盤面の置き場のファイル 1 つにつき 1 本）。

持ち主のプロセスが死ねば OS が外すので、残骸かどうかを pid や時間で見分けなくてよい（flock(2): 錠は開いたファイルの記述に付き、
記述が全部閉じると外れる）。POSIX は fcntl.flock、Windows は msvcrt.locking の 1 バイト目。ファイルは Python の既定どおり
子に継がせない（継ぐと、持ち主が死んだ後も孤児の子が錠を持ち続ける）。

2 つの形:
- board_lock(<盤面>): 盤面を書く手順（読み直し→比べる→書く）を不可分にする錠。**同じプロセスの中では入れ子で取れる**
  （入口が取った後に Board.save がもう一度取る）。別のスレッドは待つ。取れるまで待ち、時間で諦めない
- try_hold(path) / release(h): 待たない錠。取れなければ None。回し手が run の間ずっと持つ（engine/runner.py）
"""
import os
import pathlib
import threading
import time

WINDOWS_RETRY_S = 0.05   # Windows の待たない錠を取り直す間隔（msvcrt の LK_LOCK は 10 回で諦めて OSError を上げるので使わない）


def _lock(f, wait):
    """開いたファイル f に排他の錠を掛ける。wait が偽なら取れないとき False"""
    if os.name == "posix":
        import fcntl
        try:
            fcntl.flock(f.fileno(), fcntl.LOCK_EX | (0 if wait else fcntl.LOCK_NB))
            return True
        except BlockingIOError:
            return False
    import msvcrt
    while True:
        f.seek(0)   # 錠の位置はファイルの今の位置から数える——いつも 1 バイト目に掛ける
        try:
            msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
            return True
        except OSError:
            if not wait:
                return False
            time.sleep(WINDOWS_RETRY_S)


def _unlock(f):
    if os.name == "posix":
        import fcntl
        fcntl.flock(f.fileno(), fcntl.LOCK_UN)
    else:
        import msvcrt
        f.seek(0)
        msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)


def _open(path):
    path = pathlib.Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    return open(path, "a+b")   # 追記で開く——在る中身を消さず、無ければ作る


def try_hold(path):
    """待たずに排他の錠を取る。取れたら開いたファイル（release に渡す）、取れなければ None"""
    f = _open(path)
    if _lock(f, wait=False):
        return f
    f.close()
    return None


def release(h):
    if h is None or h.closed:
        return
    try:
        _unlock(h)
    finally:
        h.close()


class BoardLock:
    """盤面 1 つの錠。with で使う。同じプロセスの同じスレッドは入れ子で取れ（深さを数え、最初に取った時だけファイルに錠を掛け、
    最後に外した時だけ外す）、別のスレッドは RLock で待つ——同じプロセスの中で 2 本目の記述に flock を掛けると、自分自身を待って止まる"""

    def __init__(self, path):
        self.path = pathlib.Path(path)
        self._thread = threading.RLock()
        self._depth = 0
        self._f = None

    def __enter__(self):
        self._thread.acquire()
        if self._depth == 0:
            try:
                f = _open(self.path)
                _lock(f, wait=True)
            except BaseException:
                self._thread.release()
                raise
            self._f = f
        self._depth += 1
        return self

    def __exit__(self, *exc):
        self._depth -= 1
        if self._depth == 0:
            f, self._f = self._f, None
            release(f)
        self._thread.release()
        return False


BOARD_LOCK_NAME = "board.lock"
_LOCKS = {}
_LOCKS_GUARD = threading.Lock()


def board_lock(board_dir):
    """盤面の置き場 board_dir の錠（同じ置き場には同じ物を返す——入れ子で取れるのは同じ物を使うとき）"""
    key = os.path.realpath(pathlib.Path(board_dir) / BOARD_LOCK_NAME)
    with _LOCKS_GUARD:
        if key not in _LOCKS:
            _LOCKS[key] = BoardLock(key)
        return _LOCKS[key]
