#!/usr/bin/env python3
"""wake ノード: 頼みと納品の知らせを、宛先の会話の待ち受けで起こして届け、部署の順番待ちを持つ（受付の設計
docs/specs/2026-10-17-reception-design.md の 3・4 章）。人の打つ入力欄に字を打ち込まない。

- 待ち受け（watch）: 部署と窓口の会話の番の終わり・始まりに、Claude Code のフック（asyncRewake）が裏で起こす台本（入口は
  wake_hook.py）。その場所の会社の受付箱の台帳（log.jsonl）を前に読んだ所から先だけ見る。宛先が自分の知らせの行が在れば、
  納品（kind deliver）はその 1 行を、順番待ち（kind queued）は入口の check が渡す頼みを stderr に出して 2 で終わる。宛先違いの行は
  会話に渡さない。
- 知らせ（notice）: 送る側が宛先の会社の台帳に {to: 「会社/名前」, id, kind, file, text, at} を 1 行足す。to が文字列の行だけが
  知らせ（ほかの行の to は、宛先の中身を持つ辞書）。
- 印: 待ち受けは受付箱の wake/<場所の鍵>.json に {names, session, owner, pid, token, place, since} を書き、動いている間は BEAT 秒
  ごとに更新の時刻を進める。送る側は、宛先の名前を持つ印の会話が生きていれば（alive。POSIX は owner の処理が在る、Windows は
  更新が FRESH 秒以内）知らせの行を足す（listening）。番の途中で待ち受けが居なくても、番の終わりに張り直した待ち受けが読む。
  会話が終わると Claude Code は待ち受けに TERM を送るので、入口は印を消して終わる（release）。
- 1 つの場所に待ち受けは 1 つ: 新しい待ち受けが印の token を書き替え、前の待ち受けはそれを見て 0 で終わる。新しい物は GRACE 秒
  待ってから台帳を読み始める（前の物が読み終えた所から続ける）。読んだ所は wake/<場所の鍵>.pos（台帳の何バイト目まで）。初めての
  場所は、待ち受けを張った時の台帳の終わりから読む。読んだ所のファイルが在ること（has_history）が、その場所に待ち受けが居た跡。
- 順番待ち: 受付箱の queue/<場所の鍵>/<受付番号>.json に 1 件 1 ファイル（enqueue）。受付番号は時刻で始まるので、名前の順が
  積んだ順。取るのは待ち受けの入口だけ（take）。
"""

import hashlib
import json
import os
import time
import uuid

WAKE_DIR = "wake"   # 受付箱の下の、待ち受けの印と読んだ所の置き場
QUEUE_DIR = "queue"  # 受付箱の下の、部署ごとの順番待ちの置き場
LOG = "log.jsonl"   # 受付箱の台帳（deliver ノードと同じ名前）
POLL = 1.0          # 台帳を見る間（秒）
BEAT = 5.0          # 印の更新の時刻を進める間（秒）
FRESH = 15.0        # 送る側が待ち受けを居ると見る、印の更新からの秒
GRACE = 2.0         # 新しい待ち受けが、前の待ち受けが終わるのを待つ秒（前の物は POLL ごとに印を見る）
KINDS = {"ask": "頼み", "deliver": "納品", "queued": "頼み"}
QUEUED = "queued"   # 順番待ちに積んだ知らせの種類（待ち受けは check で渡す頼みを決める）
REST = "rest"       # 部署と窓口の属性 company.rest: 会話が自分で「今は空にしてよい区切り」と印した（--rest）。値は印した時の会話の id。
                    # 番の終わりの待ち受けが窓に /clear を打って消す。人の文で番が始まると外れる
FINISHED = "finished"   # 都度の部署の属性 company.finished: 会話が自分で「終わった、片付けてよい」と印した（--done）。値は印した時の
                        # 会話の id。番の終わりの待ち受けが印を外して --retire を裏で走らせる。人の文で番が始まると外れる
RETIRE_KEPT = "retire-kept"   # 部署の属性: --retire が片付けずに残した訳（--clean の一覧に出す）


def address(company, name):
    return f"{company}/{name}"


def addresses(company, attrs, former=()):
    """その場所が受ける宛先の並び（今の名前が先、前の名前が後）。名前が無ければ空（待ち受けを張らない）。"""
    names = [attrs.get("name")] + list(former) if attrs.get("name") else []
    return list(dict.fromkeys(address(company, n) for n in names if n))


def key(place):
    """場所（worktree の .git の場所）の鍵。印と読んだ所のファイル名。"""
    return hashlib.sha1(os.path.normcase(os.path.realpath(place)).encode("utf-8")).hexdigest()[:16]


def _dir(inbox):
    return os.path.join(inbox, WAKE_DIR)


def mark_path(inbox, place):
    return os.path.join(_dir(inbox), key(place) + ".json")


def pos_path(inbox, place):
    return os.path.join(_dir(inbox), key(place) + ".pos")


def _replace(path, text):
    """書きかけを読ませない（一時のファイルに書いてから差し替える）。"""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = f"{path}.{os.getpid()}.tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    os.replace(tmp, path)


def read_mark(inbox, place):
    try:
        with open(mark_path(inbox, place), encoding="utf-8") as f:
            got = json.load(f)
    except (OSError, ValueError):
        return None
    return got if isinstance(got, dict) else None


def new_token():
    return f"{os.getpid()}-{uuid.uuid4().hex[:8]}"


def claim(inbox, place, names, session, owner, token, now):
    """その場所の待ち受けの印を書く（前の待ち受けの印を上書きして、前の物を終わらせる）。読んだ所が無ければ台帳の終わりを書く
    （待ち受けが居た跡。順番待ちに積んでよい印になる）。"""
    _replace(mark_path(inbox, place), json.dumps(
        {"names": names, "session": session, "owner": owner, "pid": os.getpid(), "token": token, "place": place,
         "since": now}, ensure_ascii=False))
    if _read_pos(inbox, place) is None:
        _replace(pos_path(inbox, place), str(_size(os.path.join(inbox, LOG))))


def has_history(inbox, place):
    """その場所に待ち受けが居た跡（読んだ所のファイル）が在るか。無ければフックの無い古い版の会話で、順番待ちを渡す者が居ない。"""
    return os.path.isfile(pos_path(inbox, place))


def alive(mark, now=None, posix=os.name != "nt"):
    """印の会話が生きているか。POSIX は印を書いた待ち受けの親（会話の処理）が在るか、Windows は印の更新が FRESH 秒以内か
    （Windows の os.kill は 0 を渡しても処理を止めるので使わない）。"""
    if posix:
        owner = mark.get("owner")
        if not isinstance(owner, int) or owner <= 1:
            return False
        try:
            os.kill(owner, 0)
        except PermissionError:
            return True
        except OSError:
            return False
        return True
    now = time.time() if now is None else now
    return now - float(mark.get("_mtime") or 0) <= FRESH


def release(inbox, place, token):
    """印がまだ自分の物なら消す（送る側がすぐに予備の打ち込みへ回れるように）。"""
    got = read_mark(inbox, place)
    if got and got.get("token") == token:
        try:
            os.unlink(mark_path(inbox, place))
        except OSError:
            pass


def _living(inbox, now, posix):
    """受付箱の、生きた会話の印の並び（ファイルの名前の順）。"""
    now = time.time() if now is None else now
    try:
        names = sorted(os.listdir(_dir(inbox)))
    except OSError:
        return
    for n in names:
        if not n.endswith(".json"):
            continue
        path = os.path.join(_dir(inbox), n)
        try:
            mtime = os.stat(path).st_mtime
            with open(path, encoding="utf-8") as f:
                got = json.load(f)
        except (OSError, ValueError):
            continue
        if isinstance(got, dict) and alive({**got, "_mtime": mtime}, now, posix):
            yield got


def listening(inbox, to, now=None, posix=os.name != "nt"):
    """宛先 to を受ける、生きた会話の印が在れば、その印。無ければ None。now は印の更新の時刻と比べる今（既定は時計）。"""
    return next((got for got in _living(inbox, now, posix) if to in (got.get("names") or [])), None)


def listening_session(inbox, session, now=None, posix=os.name != "nt"):
    """会話の id が session の、宛先を持つ生きた会話の印が在れば、その印。無ければ None（名前で引けない頼み元を会話の id で引く）。"""
    return next((got for got in _living(inbox, now, posix) if session and got.get("session") == session and got.get("names")),
                None)


# ---- 順番待ち ----

def queue_dir(inbox, place):
    return os.path.join(inbox, QUEUE_DIR, key(place))


def queued(inbox, place):
    """その場所の順番待ちの並び（積んだ順。各件に path を添える）。"""
    d = queue_dir(inbox, place)
    try:
        names = sorted(n for n in os.listdir(d) if n.endswith(".json"))
    except OSError:
        return []
    out = []
    for n in names:
        try:
            with open(os.path.join(d, n), encoding="utf-8") as f:
                got = json.load(f)
        except (OSError, ValueError):
            continue
        if isinstance(got, dict):
            out.append({**got, "path": os.path.join(d, n)})
    return out


def find(inbox, ask_id):
    """受付箱のどれかの順番待ちに積まれた受付 ask_id の件（path を添える）。無ければ None。"""
    root = os.path.join(inbox, QUEUE_DIR)
    try:
        keys = sorted(os.listdir(root))
    except OSError:
        return None
    for k in keys:
        path = os.path.join(root, k, f"{ask_id}.json")
        try:
            with open(path, encoding="utf-8") as f:
                got = json.load(f)
        except (OSError, ValueError):
            continue
        if isinstance(got, dict):
            return {**got, "path": path}
    return None


def pull(item):
    """順番待ちから、find で見つけた件を取る（ファイルを消す）。ほかが先に取っていれば False。"""
    try:
        os.unlink(item["path"])
    except OSError:
        return False
    return True


def put_back(item):
    """pull で取った件を、同じ順番待ちの同じ場所（同じファイルの名前なので、積んだ順も同じ）に戻す。"""
    _replace(item["path"], json.dumps({k: v for k, v in item.items() if k != "path"}, ensure_ascii=False))


def enqueue(inbox, place, item):
    """順番待ちに 1 件積み、そのファイルのパスを返す。item には id が要る。"""
    path = os.path.join(queue_dir(inbox, place), f"{item['id']}.json")
    _replace(path, json.dumps(item, ensure_ascii=False))
    return path


def take(inbox, place):
    """順番待ちの先頭を取り（ファイルを消し）、その件を返す。無ければ None。"""
    for item in queued(inbox, place):
        try:
            os.unlink(item["path"])
        except OSError:
            continue   # ほかが先に取った
        return {k: v for k, v in item.items() if k != "path"}
    return None


def notice(to, ask_id, kind, file, text, now):
    """宛先の会社の台帳に足す知らせの 1 行。"""
    return {"to": to, "id": ask_id, "kind": kind, "file": file, "text": text, "at": now}


def mine(record, names):
    return isinstance(record.get("to"), str) and record["to"] in names


def read_new(log, pos):
    """台帳の pos バイト目から先の、書き終わった行（改行まで）の並びと、読み終えた所。"""
    try:
        with open(log, "rb") as f:
            f.seek(pos)
            data = f.read()
    except OSError:
        return [], pos
    end = data.rfind(b"\n")
    if end < 0:
        return [], pos
    out = []
    for line in data[:end + 1].splitlines():
        try:
            got = json.loads(line.decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            continue
        if isinstance(got, dict):
            out.append(got)
    return out, pos + end + 1


def wake_text(records):
    """会話に渡す字（知らせ 1 件に 1 行）。送る側の 1 行が無ければ、受付・種類・本文のパスから作る。"""
    lines = []
    for r in records:
        text = " ".join(str(r.get("text") or "").split())
        lines.append(text or f"{KINDS.get(r.get('kind'), r.get('kind') or '知らせ')}です（受付 {r.get('id') or '-'}）: "
                             f"{r.get('file') or '-'} を読む")
    return "\n".join(lines)


def _finish(verdict, err):
    kind, text = verdict
    if kind == "wake" and text:
        err.write(text + "\n")
        err.flush()
        return 2
    return 0


def _size(path):
    try:
        return os.path.getsize(path)
    except OSError:
        return 0


def _read_pos(inbox, place):
    try:
        with open(pos_path(inbox, place), encoding="utf-8") as f:
            return int(f.read().strip())
    except (OSError, ValueError):
        return None


def watch(inbox, place, names, session, owner, token, err, now=time.time, pause=time.sleep, parent=os.getppid, check=None):
    """待ち受けの本体。終了の値（2 は会話に渡す字を err に出した。0 は替わった・会話が居なくなった・check が終わらせた）。
    owner は待ち受けを起こした会話の処理（Claude Code）の番号で、parent() がそれと違えば（会話の処理が落ちて親が替わった）終わる。
    check は、読み始める時と、自分宛ての順番待ちの知らせ（queued）を見るたびに呼ぶ関数で、("wake", 字)（その字で会話を起こす）・
    ("end", None)（0 で終わる。会話を空にしたなど）・None（待ち続ける）を返す。"""
    claim(inbox, place, names, session, owner, token, now())
    pause(GRACE)
    log = os.path.join(inbox, LOG)
    pos = _read_pos(inbox, place)
    if pos is None:
        pos = _size(log)
        _replace(pos_path(inbox, place), str(pos))
    got = read_mark(inbox, place)
    if check and got and got.get("token") == token:
        verdict = check()
        if verdict:
            return _finish(verdict, err)
    beat = now()
    while True:
        got = read_mark(inbox, place)
        if not got or got.get("token") != token:
            return 0   # 新しい待ち受けに替わった
        if parent() != owner:
            release(inbox, place, token)
            return 0
        size = _size(log)
        if size < pos:
            pos = size   # 台帳を作り直した
        if size > pos:
            records, pos = read_new(log, pos)
            hits = [r for r in records if mine(r, names)]
            _replace(pos_path(inbox, place), str(pos))   # 出す前に進める（同じ行で 2 度起こさない）
            said = [r for r in hits if r.get("kind") != QUEUED]
            verdict = check() if check and len(said) < len(hits) else None
            if verdict and verdict[0] == "end" and not said:
                return 0
            text = "\n".join(x for x in [wake_text(said) if said else "", verdict[1] if verdict and verdict[0] == "wake" else ""]
                             if x)
            if text:
                return _finish(("wake", text), err)
        if now() - beat >= BEAT:
            try:
                os.utime(mark_path(inbox, place))
            except OSError:
                pass
            beat = now()
        pause(POLL)
