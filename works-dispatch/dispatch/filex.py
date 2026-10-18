"""ファイルの読み書きの部品: 原子的な書き込み・ファイルのロック・JSON Lines（台帳 log.jsonl など）の足しと読み。

前は同じ処理を 6 か所（原子的な書き込み）と 2 か所（ロック）に写していて、名前の決まった一時ファイル（<名前>.tmp）を使う物は、
同じ時に 2 つが書くと互いの一時ファイルを上書きしえた。台帳はロック無しで足し、読む 4 か所が読めない行を黙って飛ばしていた。
標準ライブラリに無い物なので、ここに 1 か所の実装を置く（機械が読む値の受け渡しの標準 docs/standards/machine-readable-values.md の
決まり 4・5）。macOS 付属の Python 3.9 でも読める形で書く（limits.py が herdr のタブバーから 3.9 で引く）。

- replace: 一時ファイル（同じフォルダに一意の名前）に書いてから差し替える。読む側は書きかけを見ない。
- lock: 開いたファイルに掛けるロック（POSIX は flock、Windows は msvcrt.locking）。持つ処理が落ちれば OS が外す。
- append_line: ロックを取って 1 行足す。前に書いた処理が改行の前で落ちていれば、改行を補ってから足す（切れた行に次の行を
  つなげない。切れた行は、読む側が読めない行として出す）。
- read_jsonl: 書き終わった行（改行まで）だけを読み、読めない行を数えて返す（黙って飛ばさない）。
"""

import contextlib
import json
import os
import sys
import time
import uuid

LOCK_SUFFIX = ".lock"


def replace(path, text):
    """path を text に替える（一時ファイルに書いてから os.replace）。一時ファイルの名前は処理と乱数で一意にし、同じ時に書く物どうしで
    上書きし合わない。前のファイルが在れば、その権限を引き継ぐ（無ければ umask に従う）。"""
    folder = os.path.dirname(os.path.abspath(path))
    os.makedirs(folder, exist_ok=True)
    tmp = os.path.join(folder, f".{os.path.basename(path)}.{os.getpid()}-{uuid.uuid4().hex[:8]}.tmp")
    try:
        with open(tmp, "x", encoding="utf-8", newline="\n") as f:
            f.write(text)
        try:
            os.chmod(tmp, os.stat(path).st_mode & 0o7777)
        except FileNotFoundError:
            pass   # 新しく作るファイルは umask のまま
        os.replace(tmp, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise


@contextlib.contextmanager
def lock(path, wait=True, pause=time.sleep):
    """path のファイルにロックを掛けて持つ。wait が真なら、ほかが持っている間は待つ（True を渡す）。偽なら待たず、取れなければ
    False を渡す。ロックのファイルは消さない（消すと、開いている物と新しく作った物で別のロックになる）。"""
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "a+b") as f:
        if os.name == "nt":
            import msvcrt
            f.seek(0)
            while True:
                try:
                    msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
                    break
                except OSError as e:
                    if e.errno not in (13, 36):   # EACCES・EDEADLOCK はほかが持っている。ほかの誤りは待たずに投げる
                        raise
                    if not wait:
                        yield False
                        return
                    pause(0.2)
            try:
                yield True
            finally:
                f.seek(0)
                msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            try:
                fcntl.flock(f.fileno(), fcntl.LOCK_EX | (0 if wait else fcntl.LOCK_NB))
            except BlockingIOError:
                yield False
                return
            try:
                yield True
            finally:
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)


def append_line(path, line):
    """path に 1 行足す（line の末尾の改行は 1 つにそろえる）。path + LOCK_SUFFIX のロックを持って書く（長い行を書く間に、ほかの
    処理の行が割り込まない）。"""
    data = (line.rstrip("\n") + "\n").encode("utf-8")
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with lock(path + LOCK_SUFFIX):
        fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT | getattr(os, "O_BINARY", 0), 0o666)
        try:
            size = os.fstat(fd).st_size
            if size:
                with open(path, "rb") as f:
                    f.seek(size - 1)
                    if f.read(1) != b"\n":
                        data = b"\n" + data   # 前に書いた処理が行の途中で落ちた
            while data:
                data = data[os.write(fd, data):]
        finally:
            os.close(fd)


class Read:
    """read_jsonl の結果。rows は読めた行（dict）の並び、pos は読み終えた所（バイト）、bad は読めない行の並び
    [{"at": 行の頭のバイト, "why": 訳, "text": 行の頭の字}]。"""

    def __init__(self, rows, pos, bad):
        self.rows, self.pos, self.bad = rows, pos, bad


def read_jsonl(path, start=0, end=None, stop=False):
    """path の start バイト目から end バイト目（None なら終わり）までの、書き終わった行（改行まで）を JSON として読む。
    終わりの改行の無い行は、書いている途中なので読まず、pos もその頭で止める。JSON の物（dict）でない行は bad に入れる。
    stop が真なら最初の読めない行で止める（rows はその前まで、pos はその行の頭。読んだ所を覚えて続きから読む物が、読めない行の先へ
    進まないため）。偽なら読めない行を飛ばして終わりまで読む（pos は書き終わった行の終わり）。ファイルが無ければ空。"""
    try:
        with open(path, "rb") as f:
            f.seek(start)
            data = f.read() if end is None else f.read(max(end - start, 0))
    except FileNotFoundError:
        return Read([], start, [])
    rows, bad, at = [], [], start
    for chunk in data.splitlines(keepends=True):
        if not chunk.endswith(b"\n"):
            break   # 書いている途中の行
        line = chunk.strip()
        if line:
            try:
                got = json.loads(line.decode("utf-8"))
                why = None if isinstance(got, dict) else f"JSON の物でない（{type(got).__name__}）"
            except (UnicodeDecodeError, ValueError) as e:
                got, why = None, str(e)
            if why:
                bad.append({"at": at, "why": why, "text": line[:120].decode("utf-8", "replace")})
                if stop:
                    return Read(rows, at, bad)
            else:
                rows.append(got)
        at += len(chunk)
    return Read(rows, at, bad)


_warned = set()


def warn(text, err=None):
    """text を標準エラーに出す。同じ処理の中で同じ字は 1 度だけ（待ち受けのように同じ所を何度も読む物が、同じ訳を出し続けない）。"""
    if text in _warned:
        return
    _warned.add(text)
    print(text, file=err or sys.stderr)


def bad_text(path, bad, what="台帳"):
    """読めない行の知らせの字（1 件目と数）。"""
    first = bad[0]
    more = f"ほか {len(bad) - 1} 行。" if len(bad) > 1 else ""
    return (f"{what} {path} の {first['at']} バイト目の行が読めない（{first['why']}。行の頭: {first['text']}）。{more}"
            "その行を直すか消す")
