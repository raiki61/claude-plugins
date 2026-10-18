#!/usr/bin/env python3
"""wake ノード: 頼みと納品の知らせを、宛先の会話の待ち受けで起動して届け、部署の順番待ちを持つ（受付の設計
docs/specs/2026-10-17-reception-design.md の 3・4 章）。人の打つ入力フィールドに字を打ち込まない。

- 待ち受け（watch）: 部署と窓口の会話のターンの終わり・始まりに、Claude Code のフック（asyncRewake）が裏で起動する台本（入口は
  wake_hook.py）。その場所の会社の受付箱の台帳（log.jsonl）を前に読んだ所から先だけ見る。宛先が自分の知らせの行が在れば、
  納品（kind deliver）はその 1 行を、順番待ち（kind queued）は入口の check が渡す頼みを stderr に出して 2 で終わる。宛先違いの行は
  会話に渡さない。
- 知らせ（notice）: 送る側が宛先の会社の台帳に {to: 「会社/名前」, id, kind, file, text, at} を 1 行足す。to が文字列の行だけが
  知らせ（ほかの行の to は、宛先の中身を持つ辞書）。
- 印: 待ち受けは受付箱の wake/<場所の鍵>.json に {names, session, owner, pid, token, place, since} を書き、動いている間は BEAT 秒
  ごとに更新の時刻を進める。送る側は、宛先の名前を持つ印の会話が生きていれば（alive。POSIX は owner の処理が在る、Windows は
  更新が FRESH 秒以内）知らせの行を足す（listening）。ターンの途中で待ち受けが居なくても、ターンの終わりに張り直した待ち受けが読む。
  会話が終わると Claude Code は待ち受けに TERM を送るので、入口は印を消して終わる（release）。
- 1 つの場所に待ち受けは 1 つ: 新しい待ち受けが印の token を書き替え、前の待ち受けはそれを見て 0 で終わる。新しい物は GRACE 秒
  待ってから台帳を読み始める（前の物が読み終えた所から続ける）。読んだ所は wake/<場所の鍵>.pos（台帳の何バイト目まで）。初めての
  場所は、待ち受けを張った時の台帳の終わりから読む。読んだ所のファイルが在ること（has_history）が、その場所に待ち受けが居た跡。
  台帳に読めない行が在れば、読んだ所はその行の頭で止め、会話に 1 度だけ知らせる（知らせた行の頭は wake/<場所の鍵>.bad）。
- 順番待ち: 受付箱の queue/<場所の鍵>/<受付番号>.json に 1 件 1 ファイル（enqueue）。受付番号は時刻で始まるので、名前の順が
  積んだ順。先頭に回した件（front。--first）は、回した時刻の新しい順にその前に並ぶ。取るのは待ち受けの入口だけ（take）。
- 頼みの錠: 部署の受けている頼み（属性 company.ask と頼み元）を書き換える道（待ち受けの take・--ask の窓への打ち込み・--take）は、
  受付箱の wake/<場所の鍵>.lock の錠（ask_lock）を取ってから属性を読み直し、未納品の頼みが無いときだけ書く。
"""

import contextlib
import hashlib
import json
import os
import time
import uuid

import filex

WAKE_DIR = "wake"   # 受付箱の下の、待ち受けの印と読んだ所の置き場
QUEUE_DIR = "queue"  # 受付箱の下の、部署ごとの順番待ちの置き場
LOG = "log.jsonl"   # 受付箱の台帳（deliver ノードと同じ名前）
POLL = 1.0          # 台帳を見る間（秒）
BEAT = 5.0          # 印の更新の時刻を進める間（秒）
FRESH = 15.0        # 送る側が待ち受けを居ると見る、印の更新からの秒
GRACE = 2.0         # 新しい待ち受けが、前の待ち受けが終わるのを待つ秒（前の物は POLL ごとに印を見る）
KINDS = {"ask": "頼み", "deliver": "納品", "queued": "頼み", "note": "頼みの足し"}
HOLD = ("hold", None)  # check の返り: 今は渡さず、BEAT ごとに check を呼び直す（fresh の部署を空にできるまで待つ）
QUEUED = "queued"   # 順番待ちに積んだ知らせの種類（待ち受けは check で渡す頼みを決める）
NOTE = "note"       # 今受けている頼みへの足し（--note）。納品と同じに text をそのまま渡す（ターンの途中なら、ターンの終わりの待ち受けが渡す）
REST = "rest"       # 部署と窓口の属性 company.rest: 会話が自分で「今は空にしてよい区切り」と印した（--rest）。値は印した時の会話の id。
                    # ターンの終わりの待ち受けが窓に /clear を打って消す。人の文でターンが始まると外れる
FINISHED = "finished"   # 都度の部署の属性 company.finished: 会話が自分で「終わった、片付けてよい」と印した（--done）。値は印した時の
                        # 会話の id。ターンの終わりの待ち受けが印を外して --retire を裏で走らせる。人の文でターンが始まると外れる
RETIRE_KEPT = "retire-kept"   # 部署の属性: --retire が片付けずに残した訳（--clean の一覧に出す）
LAUNCHED = "launched"   # 部署と窓口の属性: 起動したときの会社の形の model・effort・起動の設定（role.launch_key の字。--task と --move が書く）
LAUNCHING = "launching"   # 窓口の属性: --move が company.launched を書いて起動した会話が、まだ --desk を打っていない（--desk が外す）
RESTARTING = "restarting"   # 部署と窓口の属性: 待ち受けが --move --if-changed を走らせている間、その会話の id（--move が前の会話を止めたら外す）
RESTART_KEPT = "restart-kept"   # 部署と窓口の属性: 起動し直さずに残した今の値（role.launch_key の字）。同じ値では起動し直しを試し直さない
# --move --if-changed が「今は起動し直さない」で終わる値（会話がターンの途中・入力フィールドに打ちかけの字）。訳がすぐ替わるので、待ち受けは
# 今の値を RESTART_KEPT に残さず、次の区切りで試し直す。sysexits の EX_TEMPFAIL（https://man.freebsd.org/cgi/man.cgi?query=sysexits ）
NOT_NOW = 75


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


def bad_path(inbox, place):
    """待ち受けが会話に知らせた、台帳の読めない行の頭（バイト）を覚えるファイル（同じ行を 2 度知らせない）。"""
    return os.path.join(_dir(inbox), key(place) + ".bad")


def _replace(path, text):
    """書きかけを読ませない（一時のファイルに書いてから差し替える）。"""
    filex.replace(path, text)


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


@contextlib.contextmanager
def ask_lock(inbox, place, pause=time.sleep):
    """その場所の頼みの錠を取って持つ（ほかが持っていれば放すまで待つ）。部署の受けている頼みは属性の 1 組なので、読んでから書くまでの
    間にほかの道が別の頼みを書くと、前の頼みの頼み元が消え、納品が後の頼みの頼み元へ届く（2026-10-17 に my_notes の調べもので、
    待ち受けが受付 73d574 を渡した 11 秒後に、その前に部署を読んでいた --ask が受付 df9c5b を窓に打って属性を書き換えた）。
    錠は開いたファイルに掛けるので、持つ処理が落ちれば OS が外す。inbox か place が無ければ何もしない。"""
    if not (inbox and place):
        yield
        return
    with filex.lock(os.path.join(_dir(inbox), key(place) + ".lock"), pause=pause):
        yield


def pending(attrs):
    """部署が受けた頼みをまだ納品していなければ、その受付番号。ほかは None。"""
    held = attrs.get("ask")
    return held if held and attrs.get("delivered") != held else None


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


def watching(inbox, place, now=None, posix=os.name != "nt"):
    """その場所の待ち受けの台本そのものが動いているか（alive は印の会話を見る。待ち受けが会話を再開させて終わった後も、会話が生きて
    いれば alive は真のまま）。POSIX は印を書いた待ち受けの処理（pid）が在るか、Windows は印の更新が FRESH 秒以内か。"""
    try:
        mtime = os.stat(mark_path(inbox, place)).st_mtime
    except OSError:
        return False
    got = read_mark(inbox, place)
    if not got:
        return False
    if not posix:
        return alive({**got, "_mtime": mtime}, now, posix)
    return alive({"owner": got.get("pid")}, now, posix)


def stalled(inbox, place, attrs, now=None, posix=os.name != "nt"):
    """順番待ちが渡されずに止まっているか: 順番待ちが在り、部署は今の頼みを納品済み（か頼みが無い）なのに、渡す待ち受けが動いて
    いない。待ち受けはターンの終わりに張られるので、会話がターンを終えて止まったまま待ち受けが居なければ、次のターンが来るまで誰も渡さない
    （2026-10-17 に my_notes のノートの手入れで約 70 分止まった）。"""
    held = attrs.get("ask")
    if held and attrs.get("delivered") != held:
        return False   # 今の頼みのターンの終わりに待ち受けが張られる
    return bool(queued(inbox, place)) and not watching(inbox, place, now, posix)


def held(inbox, cwd, place, attrs=None):
    """順番待ちが在り、部署は今の頼みを納品済み（か頼みが無い）で、その場所の待ち受けが動いているのに渡さずに待っている（台帳の
    その場所の、今の待ち受けの会話の行のうち最後の渡した handed か渡さずに待つ held の行が held）なら、その訳。ほかは None。
    待ち受けは渡せない訳が替わるまで台帳に書き直さないので、行が古くても待ち続けている。--take で取った頼みは handed を残さないので、
    納品済みかと今の待ち受けの会話の行かで、古い held を数えない。cwd は部署の場所（台帳の行の place は待ち受けの会話の場所で、
    部署の場所の下のフォルダでもよい）。"""
    attrs = attrs or {}
    if attrs.get("ask") and attrs.get("delivered") != attrs["ask"]:
        return None
    mark = read_mark(inbox, place)
    if not queued(inbox, place) or not mark or not watching(inbox, place):
        return None
    here, last = os.path.realpath(cwd), None
    path = os.path.join(inbox, LOG)
    try:
        read = filex.read_jsonl(path)
    except OSError:
        return None
    if read.bad:
        filex.warn("注記: " + filex.bad_text(path, read.bad) + "（その行を飛ばして読んだ）")
    for got in read.rows:
        at = os.path.realpath(got.get("place") or "")
        if (got.get("kind") in ("held", "handed") and got.get("place") and (at == here or at.startswith(here + os.sep))
                and got.get("session") == mark.get("session")):
            last = got
    return (last.get("detail") or "渡さずに待っている") if last and last.get("kind") == "held" else None


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
    """その場所の順番待ちの並び（渡す順。各件に path を添える）。先頭に回した件（front に回した時刻）が、新しく回した物から先に
    並び、ほかは積んだ順。"""
    return listed(queue_dir(inbox, place))


def _item(path):
    """順番待ちの 1 件のファイルを読む。無ければ None。読めない・JSON の物でなければ、標準エラーに知らせて None（積むのは
    _replace なので書きかけは無く、読めないのは壊れた物。黙って飛ばすと、その頼みが順番待ちからも --todo からも消えて見える）。"""
    try:
        with open(path, encoding="utf-8") as f:
            got = json.load(f)
    except FileNotFoundError:
        return None   # 読む間にほかが取った
    except (OSError, ValueError) as e:
        filex.warn(f"注記: 順番待ちの {path} が読めない（{e}）。この頼みを飛ばした。直すか、要らなければ消す")
        return None
    if not isinstance(got, dict):
        filex.warn(f"注記: 順番待ちの {path} が JSON の物でない（{type(got).__name__}）。この頼みを飛ばした。直すか、要らなければ消す")
        return None
    return {**got, "path": path}


def listed(d):
    """順番待ちの置き場 d（queue/<場所の鍵>）の並び（queued と同じ順）。"""
    try:
        names = sorted(n for n in os.listdir(d) if n.endswith(".json"))
    except FileNotFoundError:
        return []
    out = [x for x in (_item(os.path.join(d, n)) for n in names) if x]
    out.sort(key=lambda q: (0, -float(q["front"])) if isinstance(q.get("front"), (int, float)) else (1, 0))
    return out


def find(inbox, ask_id):
    """受付箱のどれかの順番待ちに積まれた受付 ask_id の件（path を添える）。無ければ None。"""
    root = os.path.join(inbox, QUEUE_DIR)
    try:
        keys = sorted(os.listdir(root))
    except OSError:
        return None
    for k in keys:
        got = _item(os.path.join(root, k, f"{ask_id}.json"))
        if got:
            return got
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
    """宛先が自分の知らせか。知らせは to が字で、種類が知らせの種類（KINDS。頼み・納品・順番待ち・足し）の行だけ（記録の行に字の
    to を書いても、空の知らせで会話を再開させない）。"""
    return isinstance(record.get("to"), str) and record["to"] in names and record.get("kind") in KINDS


def read_new(log, pos):
    """台帳の pos バイト目から先の、書き終わった行（改行まで）の並びと、読み終えた所と、読めない行の並び（filex.read_jsonl の bad）。
    読めない行が在れば、その前の行までを返し、読み終えた所はその行の頭で止める（先へ進めると、その行の知らせが誰にも気づかれずに
    消える）。行を直すか消せば、次に読むときにその行から続く。"""
    try:
        got = filex.read_jsonl(log, pos, stop=True)
    except OSError:
        return [], pos, []
    return got.rows, got.pos, got.bad


def wake_text(records):
    """会話に渡す字（知らせ 1 件に 1 行）。送る側の 1 行が無ければ、受付・種類・本文のパスから作る。"""
    lines = []
    for r in records:
        text = " ".join(str(r.get("text") or "").split())
        lines.append(text or f"{KINDS.get(r.get('kind'), r.get('kind') or '知らせ')}です（受付 {r.get('id') or '-'}）: "
                             f"{r.get('file') or '-'} を読む")
    return "\n".join(lines)


def _bad_news(inbox, place, log, bad):
    """台帳の読めない行（read_new の bad）を会話に渡す字。読んだ所はその行の頭で止まり、直すか消すまで先の知らせも渡らないので、
    黙らずに会話へ 1 度だけ知らせる（知らせた行の頭を bad_path に覚え、同じ行では空を返す）。"""
    if not bad:
        return ""
    at = str(bad[0]["at"])
    try:
        with open(bad_path(inbox, place), encoding="utf-8") as f:
            if f.read().strip() == at:
                return ""
    except OSError:
        pass
    _replace(bad_path(inbox, place), at)
    return ("works-dispatch の待ち受け: " + filex.bad_text(log, bad)
            + "。直すまで、この行より後の知らせはこの会話に渡らない")


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


def watch(inbox, place, names, session, owner, token, err, now=time.time, pause=time.sleep, parent=os.getppid, check=None,
          ready=None):
    """待ち受けの本体。終了の値（2 は会話に渡す字を err に出した。0 は替わった・会話が居なくなった・check が終わらせた）。
    owner は待ち受けを起動した会話の処理（Claude Code）の番号で、parent() がそれと違えば（会話の処理が落ちて親が替わった）終わる。
    check は、読み始める時と、自分宛ての順番待ちの知らせ（queued）を見るたびに（同じ回にほかの知らせが在れば、そちらを先に会話へ
    渡して呼ばない）呼ぶ関数で、("wake", 字)（その字で会話を再開させる）・
    ("end", None)（0 で終わる。会話を空にしたなど）・HOLD（渡せる時を待つ。BEAT ごとに呼び直す）・None（待ち続ける）を返す。
    ready は会話が字を受けられるかを返す関数（None なら常に受けられる）。受けられない間は、印を張ったまま台帳を読まず check も
    呼ばない（読んだ所を進めないので、受けられるようになってから同じ行で起動する）。"""
    claim(inbox, place, names, session, owner, token, now())
    pause(GRACE)
    log = os.path.join(inbox, LOG)
    pos = _read_pos(inbox, place)
    if pos is None:
        pos = _size(log)
        _replace(pos_path(inbox, place), str(pos))
    holding, first = False, check is not None   # first: 読み始めの check をまだ呼んでいない
    beat = now()
    while True:
        got = read_mark(inbox, place)
        if not got or got.get("token") != token:
            return 0   # 新しい待ち受けに替わった
        if parent() != owner:
            release(inbox, place, token)
            return 0
        if ready is not None and not ready():
            if now() - beat >= BEAT:
                try:
                    os.utime(mark_path(inbox, place))
                except OSError:
                    pass
                beat = now()
            pause(POLL)
            continue
        if first:
            first = False
            verdict = check()
            holding = verdict == HOLD
            if verdict and not holding:
                return _finish(verdict, err)
        size = _size(log)
        if size < pos:
            pos = size   # 台帳を作り直した
        if size > pos:
            records, pos, bad = read_new(log, pos)
            hits = [r for r in records if mine(r, names)]
            _replace(pos_path(inbox, place), str(pos))   # 出す前に進める（同じ行で 2 度起動しない）
            said = [r for r in hits if r.get("kind") != QUEUED]
            broken = _bad_news(inbox, place, log, bad)
            # 知らせ（said）が在れば先に会話へ渡し、順番待ちはそのターンの終わりに見る（同じ回に見ると、知らせを受ける前に空にしうる）
            verdict = check() if check and hits and not said else None
            holding = holding or verdict == HOLD
            if verdict and verdict[0] == "end" and not said and not broken:
                return 0
            text = "\n".join(x for x in [wake_text(said) if said else "", broken,
                                          verdict[1] if verdict and verdict[0] == "wake" else ""] if x)
            if text:
                return _finish(("wake", text), err)
        if now() - beat >= BEAT:
            if holding:
                verdict = check()
                holding = verdict == HOLD
                if verdict and not holding:
                    return _finish(verdict, err)
            try:
                os.utime(mark_path(inbox, place))
            except OSError:
                pass
            beat = now()
        pause(POLL)


# 会話から切り離してコマンドを走らせる殻（POSIX）。外の sh はすぐ終わり、中の ( … ) & は親を失って init の子になる。会話の処理を止めると
# Claude Code はフックの子孫も止めるので、フックの子のまま走らせた --move は、自分が止めた前の会話と一緒に止まり、何も書かずに消えた
# （2026-10-17 の my_notes の段取り。16:03 と 16:54 に moves/ の出力が 0 バイトのまま、窓口が消えた。部署の --move の跡も同じ）
DETACH = 'log=$1; done=$2; shift 2; ( "$@" >"$log" 2>&1 </dev/null; echo $? >"$done" ) &'


def detached(argv, log, done):
    """argv を会話から切り離して走らせる sh の並び。出力は log に、終わりの値は done に書く。"""
    return ["/bin/sh", "-c", DETACH, "sh", log, done, *argv]
