#!/usr/bin/env python3
"""メインブランチへ入れる処理を、同じ clone（worktree を含む）で申し出た順に 1 本ずつ通す列（会社の形の [land] の queue）。

--land（landing.py）は、メインブランチの先頭へのリベースに入る直前に列へ申し出て、fast-forward して push し終えるまで列の先頭を持つ。
works-dispatch の外のツール（my_notes の collect など）は、--queue-run（queuerun.py）でこの列に並んでコマンドを走らせる。
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

会社の形の [land] の batch が 2 以上なら、先頭の --land（束ね役）が待っている札の部署のブランチを束ねて 1 回のゲートで入れる
（束の設計 docs/specs/2026-10-26-land-batch-design.md）。その状態も置き場のフォルダの中だけに持つ（書くのは列の先頭を持つ処理だけ）:
- `<札の名>.rider`（RIDER）: 束ね役が、束に乗せた札の横に書く印（中身は束ね役の部署の名前）。束ね役が終わるときに消す。印が残ったまま
  乗った処理が列を抜けると（ゲートの間の Ctrl-C）、束ね役が入れたかもしれないと 1 行出す。乗った処理が先頭を取れば、束ね役は居ないので消す。
- `suspects`（SUSPECTS）: 赤だった束に乗っていたブランチと、その時の先頭の commit を 1 行に 1 つ（疑いの印）。印の当たる札は束に乗らない。
- `batches/<束ね役の札の名>.json`（BATCHES）: 緑の束の控え（重ねる前のメインブランチ・候補・顔ぶれごとの元と写しの commit）。乗った部署は
  自分の順番で、写しがメインブランチに入っていれば受け取る。
"""

import contextlib
import json
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
RIDER = ".rider"  # 札の横の、束ね役が書く「束に乗せた」印（中身は束ね役の部署の名前）
SUSPECTS = "suspects"   # 疑いの印（1 行に 1 つ、ブランチと赤だった時の先頭の commit）
BATCHES = "batches"     # 束の控えのフォルダ（<束ね役の札の名>.json）


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
            for gone in (ticket, ticket.with_name(ticket.name + WHO), ticket.with_name(ticket.name + RIDER)):
                with contextlib.suppress(OSError):
                    gone.unlink()
        else:
            out.append(ticket.name)
    return _ranked(queue, out)


@contextlib.contextmanager
def turn(queue, say=print, sleep=time.sleep, name=None):
    """列 queue（フォルダ）に入り、自分の番が来たら札の名を渡して戻る。抜けると次の処理に順番を渡す。
    name は名乗り（部署の名前, ブランチ）で、判断役の order が順を決めるのに使う。"""
    queue = Path(queue)
    queue.mkdir(parents=True, exist_ok=True)
    ticket = queue / f"{time.time_ns():020d}-{os.getpid()}.ticket"
    label = ticket.with_name(ticket.name + WHO)
    rider = ticket.with_name(ticket.name + RIDER)
    with open(ticket, "a+b") as mine:
        while not _try_lock(mine):  # ほかの処理の alive() が一瞬ロックを取っている間は掛からない。掛けずに進むと札を消されて割り込む
            sleep(0.01)
        try:
            if name:
                label.write_text("\n".join(x or "" for x in name) + "\n", encoding="utf-8")
            with open(queue / "lock", "a+b") as gate:
                _wait(queue, ticket.name, gate, say, sleep)
                with contextlib.suppress(OSError):
                    rider.unlink()   # 先頭を取れたので、乗せた束ね役はもう居ない（落ちた束ね役の残した印）
                try:
                    yield ticket.name
                finally:
                    _unlock(gate)
        finally:
            _unlock(mine)
            mine.close()
            try:
                leader = rider.read_text(encoding="utf-8").strip()
            except OSError:
                leader = None
            if leader is not None:   # 束に乗ったまま、先頭を取らずに抜けた（ゲートの間の Ctrl-C）
                say(f"束に乗っていたので、束ね役 {leader or '-'} が入れたかもしれない（入っていれば、次の --land か作業場の追いつきが受け取る。"
                    "入れたくなければ、入った commit を git revert で戻す）")
            for gone in (ticket, label, rider):
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


def _write(path, text):
    """置き換えで書く（途中で読まれても半端な中身を見せない）。"""
    tmp = path.with_name(f".{path.name}-{os.getpid()}")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def mark_riders(queue, tickets, leader):
    """束に乗せた札の横に、束ね役の部署の名前を書いた印を置く。札がもう無ければ置かない。"""
    for name in tickets:
        if (Path(queue) / name).exists():
            (Path(queue) / (name + RIDER)).write_text(leader + "\n", encoding="utf-8")


def unmark_riders(queue, tickets):
    for name in tickets:
        with contextlib.suppress(OSError):
            (Path(queue) / (name + RIDER)).unlink()


def suspects(queue):
    """疑いの印 {ブランチ: 赤だった時の先頭の commit}。無ければ空。"""
    try:
        text = (Path(queue) / SUSPECTS).read_text(encoding="utf-8")
    except OSError:
        return {}
    return {parts[0]: parts[1] for parts in (line.split() for line in text.splitlines()) if len(parts) == 2}


def set_suspects(queue, marks):
    """疑いの印を marks（{ブランチ: commit}）にする。空なら置き場から消す。"""
    path = Path(queue) / SUSPECTS
    if not marks:
        with contextlib.suppress(OSError):
            path.unlink()
        return
    _write(path, "".join(f"{b} {s}\n" for b, s in sorted(marks.items())))


def write_batch(queue, ticket, record):
    """束の控えを batches/<札の名>.json に置き換えで書く。"""
    folder = Path(queue) / BATCHES
    folder.mkdir(parents=True, exist_ok=True)
    _write(folder / f"{ticket}.json", json.dumps(record, ensure_ascii=False, indent=1) + "\n")


def batches(queue):
    """束の控えの並び [(札の名, 控え)]（名の順）。読めない控えは飛ばす。"""
    out = []
    for path in sorted((Path(queue) / BATCHES).glob("*.json")):
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue   # 書きかけか壊れた控え。入ったかの正は写しが祖先かなので、飛ばしても誤って受け取らない（束の設計 8.1）
        if isinstance(record, dict) and isinstance(record.get("members"), list):
            out.append((path.name[:-len(".json")], record))
    return out


def drop_batch(queue, ticket):
    with contextlib.suppress(OSError):
        (Path(queue) / BATCHES / f"{ticket}.json").unlink()


class Hold:
    """--land の 1 回が持つ列の順番。take は持っていなければ列に入って順番を待ち（回し直しで重ねて入らない）、drop は順番を手放す。
    持つ間、queue は列の置き場、ticket は自分の札の名、seen は先頭を取った時に生きていた札の並び（入れる順。束の顔ぶれはここから決める）。"""

    def __init__(self):
        self._turn = None
        self.queue = self.ticket = None
        self.seen = []

    def take(self, queue, say=print, name=None):
        if self._turn is None:
            t = turn(queue, say, name=name)
            self.ticket = t.__enter__()
            self._turn = t
            self.queue = queue
            self.seen = alive(queue)

    def drop(self):
        t, self._turn = self._turn, None
        if t is not None:
            t.__exit__(None, None, None)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.drop()
