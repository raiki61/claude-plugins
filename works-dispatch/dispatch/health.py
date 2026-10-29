#!/usr/bin/env python3
"""受付箱のまわりで、壊れても誰にも知らせが来ない所を見て、--tree と --todo の注記にする（壊れの見つけ方の標準
docs/standards/breakage-detection.md）。

- 裏の処理（background）: 待ち受けと使用上限のフックが会話から切り離して走らせる --move・--retire・--take は、出力を受付箱の
  moves/・retires/・takes/ に <名前>-<秒>.log で、終わりの値を同じ名前の .done に書く（nodes/wake.py の detached。走らせる前に空の
  .done を作る）。0 と 75（今は起動し直さない。wake.NOT_NOW）でない終わりの値と、UNFINISHED_MIN 分たっても .done が空の物を出す。
  .done の無い物（Windows で殻を使わずに走らせた物・空の .done を作るより前の版の跡）は、終わりが分からないので出さない。出すのは RECENT_HOURS 時間
  以内の物だけ。KEEP_DAYS 日より古い出力は、読むときに消す（足し続ける置き場の片付け。標準の決まり 5）。
- 順番待ち（stale_queue）: QUEUE_STALE_MIN 分より前に積まれたまま誰も受けていない頼みの在る順番待ち（宛先ごとに 1 行）。
- 足し続ける物（growth）: 台帳 log.jsonl と due.log の大きさが LEDGER_LIMIT を超えたら出す（台帳は頼みの木の元なので消さない）。
  log.jsonl の読めない行（filex.read_jsonl の bad。読む側は飛ばして標準エラーにだけ出す）も数えて出す。
  空になった順番待ちの置き場（queue/<場所の鍵>）は、EMPTY_DAYS 日より古い物を読むときに消す。
- 一時の置き場の控え（kept_tmp）: --clean・--retire が会話の一時の置き場を消す前に写した控え（nodes/clean.py の keep_tmp。写すときに
  古い物を消す）。消せずに clean.KEPT_DAYS 日より古い物が残れば出す。
- 盤面の写し（boards_archive）: 片付けが場所を消す前に写した graphloops の盤面（nodes/clean.py の keep_boards。写すときに古い物を
  消す）。works-dispatch が写した物の合計が clean.ARCHIVE_LIMIT を超えて残れば出す。
- 周期（due）: 会社の形の受け持ちの周期（[skills.start] の every）の、前に起動した時と次の時。次の時を DUE_LATE_MIN 分過ぎても起動して
  いなければ出す（--due は頼みと納品が流れたときにしか打たれない）。
- 役の本文の字数（oversize）: 役の本文を足すフック（role_hook.py）が部署と窓口に足した文が chat.CONTEXT_LIMIT 字を超えると、会話には
  頭の chat.CONTEXT_PREVIEW 字と保存先のパスしか入らず、後ろの手順が黙って落ちる。フックが超えた場所を受付箱の SIZES_DIR に 1 つずつ
  控え（note_size。収まれば消す）、ここで出す。控えた場所が無くなった（部署が畳まれた）物は、読むときに消す。
"""

import errno
import json
import os
import time

import filex
from nodes import clean, start, wake
from ports import chat

BACKGROUND = ("moves", "retires", "takes")   # 受付箱の下の、裏の処理の出力の置き場（limit_hook.py・wake_hook.py と同じ名前）
FINE = (0, wake.NOT_NOW)
UNFINISHED_MIN = 30
RECENT_HOURS = 48   # .done を書く殻より前の版の跡（.done が無い）を出し続けない
KEEP_DAYS = 14
QUEUE_STALE_MIN = 30
LEDGER_LIMIT = 32 * 1024 * 1024
LEDGERS = (wake.LOG, "due.log")   # due.log は starts.DUE_LOG と同じ名前
EMPTY_DAYS = 1
DUE_LATE_MIN = 60
SIZES_DIR = "role-sizes"   # 受付箱の下の、足した文が上限を超えた場所の控えの置き場（note_size）


def _stamp(name):
    """<名前>-<秒>.log の秒。読めなければ None。"""
    tail = name[:-len(".log")].rsplit("-", 1)[-1]
    return int(tail) if tail.isdigit() else None


def _exit(done):
    """.done の終わりの値。無ければ None（殻の外で走らせた物か、殻が空の .done を作るより前の版の跡）、空なら ""（走っている途中）。"""
    try:
        with open(done, encoding="utf-8") as f:
            text = f.read().strip()
    except OSError:
        return None
    return int(text) if text.lstrip("-").isdigit() else text


def _tail(path, n=160):
    try:
        with open(path, "rb") as f:
            f.seek(max(0, os.path.getsize(path) - n))
            return " ".join(f.read().decode("utf-8", "ignore").split())   # 切った所で割れた字は捨てる（「�」を出さない）
    except OSError:
        return ""


def _remove(path):
    """消せなければその注記の文（消せたか、もう無ければ None）。"""
    try:
        os.unlink(path)
    except FileNotFoundError:
        pass   # もう無い（.done を書かない走らせ方の .log だけの跡か、ほかの --tree が先に消した）
    except OSError as e:
        return f"古い裏の処理の出力 {path} を消せない（{e.strerror or e}）。中を見て要らなければ消す"
    return None


def background(inbox, now):
    """裏の処理の失敗と、終わりの値の無い物の注記の並び。KEEP_DAYS 日より古い出力は消す。"""
    out = []
    for kind in BACKGROUND:
        d = os.path.join(inbox, kind)
        try:
            names = sorted(n for n in os.listdir(d) if n.endswith(".log"))
        except FileNotFoundError:
            continue   # この種類の裏の処理はまだ走っていない（置き場は走らせるときに作る）
        except OSError as e:
            out.append(f"裏の処理の置き場 {d} を読めない（{e.strerror or e}）。この置き場の失敗と止まった物は出ない")
            continue
        for n in names:
            log = os.path.join(d, n)
            done = log[:-len(".log")] + ".done"
            at = _stamp(n)
            if at is None:
                try:
                    at = os.stat(log).st_mtime
                except FileNotFoundError:
                    continue   # 並べた後に消えた（ほかの --tree が古い物として先に消した）
                except OSError as e:
                    out.append(f"裏の処理の出力 {kind}/{n} を読めない（{e.strerror or e}）。終わり方が分からない")
                    continue
            age = now - at
            if age > KEEP_DAYS * 86400:
                # .done を先に消し、消せなければ .log も残す（並べるのは .log なので、先に .log を消すと残った .done を二度と見ない）
                note = _remove(done) or _remove(log)
                if note:
                    out.append(note)
                continue
            if age > RECENT_HOURS * 3600:
                continue
            code = _exit(done)
            if code is None:
                continue
            if code == "":
                if age > UNFINISHED_MIN * 60:
                    out.append(f"裏の処理 {kind}/{n} が {int(age // 60)} 分たっても終わりの値（.done）を書いていない"
                               f"（途中で止められたか、止まったまま）。出力の最後: {_tail(log) or '空'}")
            elif code not in FINE:
                out.append(f"裏の処理 {kind}/{n} が終わりの値 {code} で終わった。出力の最後: {_tail(log) or '空'}")
    return out


def stale_queue(inbox, now):
    """QUEUE_STALE_MIN 分より前に積まれたまま誰も受けていない頼みの在る順番待ちの注記の並び（宛先ごとに 1 行）。EMPTY_DAYS 日より古い空の置き場は消す。"""
    out = []
    root = os.path.join(inbox, wake.QUEUE_DIR)
    try:
        keys = sorted(os.listdir(root))
    except OSError:
        return out
    for k in keys:
        d = os.path.join(root, k)
        if not os.path.isdir(d):
            continue   # .DS_Store など。置き場でない物を読むと NotADirectoryError で --tree と --todo ごと落ちる
        items = wake.listed(d)
        if not items:
            try:
                if now - os.stat(d).st_mtime > EMPTY_DAYS * 86400:
                    os.rmdir(d)   # 空でなければ OS が断る（読んだ後に積まれた物は消さない）
            except OSError as e:
                if e.errno not in (errno.ENOENT, errno.ENOTEMPTY, errno.EEXIST):   # ほかが先に消したか、読んだ後に積まれた: 消さなくてよい
                    out.append(f"空の順番待ちの置き場 {d} を消せない（{e.strerror or e}）。中を見て要らなければ消す")
            continue
        oldest = min(items, key=lambda q: _mtime(q["path"]))
        age = now - _mtime(oldest["path"])
        if age > QUEUE_STALE_MIN * 60:
            out.append(f"{oldest.get('to')} の順番待ちに {len(items)} 件。一番古い受付 {oldest.get('id')} は {int(age // 60)} 分積まれたまま、"
                       "まだ誰も受けていない（--tree でその部署の様子を見る。止まっていれば --nudge）")
    return out


def _mtime(path):
    try:
        return os.stat(path).st_mtime
    except OSError:
        return float("inf")   # 読む間にほかが取った


def growth(inbox):
    """足し続ける台帳の大きさが上限を超えていれば、その注記の並び。"""
    out = []
    for name in LEDGERS:
        try:
            size = os.path.getsize(os.path.join(inbox, name))
        except FileNotFoundError:
            continue   # まだ 1 行も書いていない台帳
        except OSError as e:
            out.append(f"受付箱の {name} の大きさを読めない（{e.strerror or e}）。上限を超えたかが分からない")
            continue
        if size > LEDGER_LIMIT:
            out.append(f"受付箱の {name} が {size // (1024 * 1024)} MiB（上限の目安 {LEDGER_LIMIT // (1024 * 1024)} MiB）。"
                       "読むたびに全部を読むので遅くなる。片付け方を決める")
    bad = filex.read_jsonl(os.path.join(inbox, wake.LOG)).bad
    if bad:
        out.append(f"受付箱の {wake.LOG} に読めない行が {len(bad)} 行ある（その行の頼みや納品は --todo に出ない）。"
                   f"最初の行は {bad[0]['at']} バイト目: {bad[0]['why']}")
    return out


def kept_tmp(kept, now):
    """clean.KEPT_DAYS 日より古い控えが残っていれば、その注記の並び（写すときの片付けが動いていない）。"""
    old = [p for t, p in clean.kept_entries(kept) if now - t > clean.KEPT_DAYS * 86400]
    if not old:
        return []
    return [f"一時の置き場の控え {kept} に {clean.KEPT_DAYS} 日より古い物が {len(old)} つ残っている（--clean か --retire が写すときに消す。"
            "消せていない。中を見て要らなければ消す）"]


def boards_archive(archive):
    """works-dispatch が写した盤面の合計が clean.ARCHIVE_LIMIT を超えていれば、その注記の並び（写すときの片付けが動いていない）。"""
    size = clean.archived_size(archive)
    if size <= clean.ARCHIVE_LIMIT:
        return []
    return [f"graphloops の盤面の写し {archive} のうち works-dispatch が写した物が {size // (1024 * 1024)} MiB"
            f"（上限 {clean.ARCHIVE_LIMIT // (1024 * 1024)} MiB）。--land の後の片付け・--clean・--retire が写すときに古い物から消す。消せていない。中を見て要らなければ消す"]


def due(skills, records, now):
    """周期の有る受け持ちの、(前に起動した時, 次の時) を skill に書き足し、次の時を DUE_LATE_MIN 分過ぎた物と、一度も起動していない物の注記の並び。"""
    out = []
    for s in skills:
        st = s.get("start")
        if not (st and st.get("every")):
            continue
        last = start.last_started(records, s["name"])
        s["last_started"] = last
        every = start.seconds(st["every"])   # 形の違う周期は会社の形の検査が出す
        s["next_start"] = None if last is None or every is None else last + every
        if last is None and every is not None:   # start.due は「もう起動すべき」と見る。--due が一度も走らなければ黙ったまま
            out.append(f"受け持ち {s['name']} の周期（{st['every']} ごと）が一度も起動した記録が無い"
                       "（--due は頼みと納品が流れたときに裏で打たれる。流れが無ければ手で --due を打つか、OS の予定に置く）")
        elif s["next_start"] is not None and now - s["next_start"] > DUE_LATE_MIN * 60:
            out.append(f"受け持ち {s['name']} の周期（{st['every']} ごと）が {int((now - s['next_start']) // 60)} 分過ぎても起動していない"
                       "（--due は頼みと納品が流れたときに裏で打たれる。流れが無ければ手で --due を打つか、OS の予定に置く）")
    return out


def note_size(inbox, place, name, chars):
    """場所 place（worktree の .git の場所。部署の名前 name）に足した文の字数 chars を控える。上限を超えていれば控えを書き、収まっていれば消す。"""
    path = os.path.join(inbox, SIZES_DIR, f"{wake.key(place)}.json")
    if chars <= chat.CONTEXT_LIMIT:
        try:
            os.unlink(path)
        except FileNotFoundError:
            pass   # 前から収まっている（控えは超えたときだけ書く）
        return
    filex.replace(path, json.dumps({"place": place, "name": name, "chars": chars, "at": time.time()}, ensure_ascii=False))


def oversize(inbox):
    """足した文が上限を超えた場所の注記の並び。場所の無くなった控えは消す。"""
    out = []
    d = os.path.join(inbox, SIZES_DIR)
    try:
        names = sorted(n for n in os.listdir(d) if n.endswith(".json"))
    except FileNotFoundError:
        return out   # まだ超えた場所が無い（置き場は超えたときに作る）
    except OSError as e:
        return [f"役の本文の字数の控えの置き場 {d} を読めない（{e.strerror or e}）。上限を超えた部署が出ない"]
    for n in names:
        path = os.path.join(d, n)
        try:
            with open(path, encoding="utf-8") as f:
                got = json.load(f)
        except FileNotFoundError:
            continue   # 読む間にフックが消した（収まった）
        except (OSError, ValueError) as e:
            out.append(f"役の本文の字数の控え {path} を読めない（{e}）。中を見て要らなければ消す")
            continue
        if not isinstance(got, dict) or not isinstance(got.get("chars"), int):
            out.append(f"役の本文の字数の控え {path} の形が違う（place・name・chars の JSON でない）。中を見て要らなければ消す")
            continue
        if not os.path.isdir(got.get("place") or ""):
            try:
                os.unlink(path)   # 部署が畳まれた
            except FileNotFoundError:
                pass   # ほかの --tree か --todo が先に消した
            except OSError as e:
                out.append(f"畳まれた部署の役の本文の字数の控え {path} を消せない（{e.strerror or e}）。中を見て要らなければ消す")
            continue
        out.append(f"部署 {got.get('name') or got.get('place')} の会話の始まりに足す文が {got['chars']:,} 字で、フックの上限"
                   f" {chat.CONTEXT_LIMIT:,} 字を超えた（会話には頭の {chat.CONTEXT_PREVIEW:,} 字しか入らず、後ろの手順が落ちる）。"
                   "その部署の受け持ちの説明（[[skills]] の description）か役の本文を縮める")
    return out


def inbox_notes(inbox, now):
    """受付箱 1 つの注記（裏の処理・順番待ち・台帳の大きさ・役の本文の字数）。"""
    if not inbox or not os.path.isdir(inbox):
        return []
    return background(inbox, now) + stale_queue(inbox, now) + growth(inbox) + oversize(inbox)
