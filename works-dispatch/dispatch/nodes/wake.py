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
import re
import time
import uuid

from ports import chat
import filex

WAKE_DIR = "wake"   # 受付箱の下の、待ち受けの印と読んだ所の置き場
QUEUE_DIR = "queue"  # 受付箱の下の、部署ごとの順番待ちの置き場
LOG = "log.jsonl"   # 受付箱の台帳（deliver ノードと同じ名前）
POLL = 1.0          # 台帳を見る間（秒）
BEAT = 5.0          # 印の更新の時刻を進める間（秒）
FRESH = 15.0        # 送る側が待ち受けを居ると見る、印の更新からの秒
GRACE = 2.0         # 新しい待ち受けが、前の待ち受けが終わるのを待つ秒（前の物は POLL ごとに印を見る）
SLACK = 2.0         # 処理の起きた時刻（ps の etime は秒の刻み）と印を書いた時刻の比べの遊び
KINDS = {"ask": "頼み", "deliver": "納品", "queued": "頼み", "note": "頼みの足し"}
HOLD = ("hold", None)  # check の返り: 今は渡さず、BEAT ごとに check を呼び直す（fresh の部署を空にできるまで待つ）
QUEUED = "queued"   # 順番待ちに積んだ知らせの種類（待ち受けは check で渡す頼みを決める）
NOTE = "note"       # 今受けている頼みへの足し（--note）。納品と同じに text をそのまま渡す（ターンの途中なら、ターンの終わりの待ち受けが渡す）
REST = "rest"       # 部署と窓口の属性 company.rest: 会話が自分で「今は空にしてよい区切り」と印した（--rest）。値は印した時の会話の id。
                    # ターンの終わりの待ち受けが窓に /clear を打って消す。人の文でターンが始まると外れる
COMPACT = "compact"   # 部署と窓口の属性 company.compact: 会話が自分で「ここで compact してよい区切り」と印した（--compact）。値は印した時の
                      # 会話の id。ターンの終わりの待ち受けが窓に /compact を打ち、compact の後の会話の始まりの待ち受けが印を外して会話を続けさせる。
                      # 人の文でターンが始まると外れる
COMPACT_FOCUS = "compact-focus"   # 部署と窓口の属性: --compact に渡した焦点（/compact の後ろに付けて、要約に残させる物）
# --compact で待ち受けが /compact を打つ下限の文脈（トークン）。これより小さい会話は compact の費用の元が取れない: Opus 5.5 の値段
# （https://platform.claude.com/docs/en/about-claude/pricing 。キャッシュの読み $0.20・出力 $20・1 時間の書き込み $8 / 100 万トークン）で、
# 10 万トークンの compact は約 $0.14（読み 10 万・要約の出力約 3 千・要約の書き込み約 8 千）、後の要求 1 回の読みは約 $0.018 安くなり、
# 約 8 回で元が取れる。5 万では約 16 回かかる。my_notes の 3.5 日の会話の記録（2026-10-17〜20）の、ターンの境目からの要求の数の中央値は 12〜45
COMPACT_FLOOR = 100000
FINISHED = "finished"   # tmp の部署の属性 company.finished: 会話が自分で「終わった、片付けてよい」と印した（--done）。値は印した時の
                        # 会話の id。ターンの終わりの待ち受けが印を外して --retire を裏で走らせる。人の文でターンが始まると外れる
RETIRE_KEPT = "retire-kept"   # 部署の属性: --retire が片付けずに残した訳（--clean の一覧に出す）
LAUNCHED = "launched"   # 部署と窓口の属性: 起動したときの会社の形の model・effort・起動の設定（role.launch_key の字。--task と --move が書く）
LAUNCHING = "launching"   # 窓口の属性: --move が company.launched を書いて起動した会話が、まだ --desk を打っていない（--desk が外す）
RESTARTING = "restarting"   # 部署と窓口の属性: 待ち受けが --move --if-changed を走らせている間、その会話の id（--move が前の会話を止めたら外す）
RESTART_KEPT = "restart-kept"   # 部署と窓口の属性: 起動し直さずに残した今の値（role.launch_key の字）。同じ値では起動し直しを試し直さない
MOVE_TO = "move-to"   # 部署と窓口の属性: 持ち主か窓口が --move で名指したが、ターンの途中で移せなかったアカウント。区切りで --if-changed が移す（今のアカウントなら、そのまま起動し直す）。待ち受けが keep の部署の作業場を進めて役の定義などが替わったときも、今のアカウントを書く（wake_hook.follow_main）
EARLY = "使用上限に当たる前の区切りで移す"   # 台帳の moved の行の why（--if-changed と待ち受けが、早めに移した・移さなかった）
MOVE_KEPT = "move-kept"   # 部署と窓口の属性: 区切りで早めに移そうとして起動できなかったアカウント（, でつなぐ。accounts.kept）。早めに移す先に選ばない（起動し直すと外れる）
MOVE_SKIPPED = "move-skipped"   # 部署と窓口の属性: 早めに移さなかった訳の種類（<アカウント>/<種類>）。同じ訳では台帳に重ねて書かない
# 部署と窓口の属性: 使用上限か時間帯で止まった会話を、--move --if-limited が移さずに待っている印（待つ処理ごとの字）。後から待ち始めた
# --move が書き替え、会話のターンが誤りなく終わると外れ（wake_hook.ended_well）、起動し直すと外れる。字が自分の物でなくなった処理は待つのをやめる
LIMIT_HOLD = "limit-hold"
# 部署か窓口の会話が、起動し直す前に書く引継ぎ（済んだこと・次の手）のファイル。作業場の git の場所（git rev-parse --git-dir）に置く。
# 起動し直した会話への最初の文（--move の move-brief.md）が、在れば指す（2026-10-19 に調べもの・割り振りが書いたのに最初の文が触れず、
# 移った先の会話が読み落としえた。受付 20261019-004101-f39d00 の困りごと）
HANDOFF = "handoff.md"
# --move --if-changed が「今は起動し直さない」で終わる値（会話がターンの途中・入力フィールドに打ちかけの字）。訳がすぐ替わるので、待ち受けは
# 今の値を RESTART_KEPT に残さず、次の区切りで試し直す。sysexits の EX_TEMPFAIL（https://man.freebsd.org/cgi/man.cgi?query=sysexits ）
NOT_NOW = 75
# 部署と窓口の属性: 待ち受けが窓に /clear を打つ直前に書く、その時の会話の id（own_clear が見分けに使う。空にしたら外す）
CLEAR_TYPED = "clear-typed"


def own_clear(box, attrs, session=None):
    """窓の入力フィールドの字 box（chat.typed）が、待ち受けが打って送られずに残った /clear か: 字が /clear だけ（後ろに Claude Code の
    引数の候補の [..] が付いてもよい。候補は薄字〔SGR 2〕でなく描かれ、typed が除けない）で、属性 CLEAR_TYPED がその会話の id
    （session。省けば属性の会話 company.session）。ほかの字は人の打ちかけと見る（消さない・送らない）。2026-10-20 に my_notes の
    調べもので、待ち受けが打った /clear が、会話がまた動き出したターンの間に送られずに残り、待ち受けも --move も --nudge もその字を
    人の打ちかけと見て、順番待ちの 5 件が 3 時間渡らなかった。"""
    head, _, rest = (box or "").partition(" ")
    sid = session or attrs.get("session")
    return (head == chat.CLEAR and (not rest or re.fullmatch(r"\[[^\[\]]*\]", rest))
            and bool(sid) and attrs.get(CLEAR_TYPED) == sid)


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


def _mark_lock(path):
    """印のファイルの錠。印を書く道（claim）と、token を読み直して消す道（release・_drop_dead）を並べないために持つ（読み直してから
    消すまでの間に新しい待ち受けが印を書くと、新しい方の印が消え、待ち受けが黙って終わる）。錠のファイルは場所ごとに 1 つで、消さない。"""
    return filex.lock(path + ".lock")


def warm_path(inbox, place):
    """keepalive の控え（{session, tasks, sent, stopped, spent}。同じ会話が同じ物〔裏の処理と頼み〕を待つ間に続けて送った本数と、
    止めたかと、送った分の費用の累計〔ドル。借りるか買うかの部品の rent の和〕）。"""
    return os.path.join(_dir(inbox), key(place) + ".warm.json")


def warm_state(inbox, place, session, tasks):
    """同じ会話（session）が同じ物（tasks。裏の処理の id か数と、ask:・child:・parked: の頼み。wake_hook.warm_for）を待つ間の keepalive の
    控え {sent, stopped, spent}。控えが無い・読めない・会話か待つ物が替わっていれば {sent: 0, stopped: False, spent: 0}（新しい待ちの始まり）。"""
    fresh = {"sent": 0, "stopped": False, "spent": 0}
    try:
        with open(warm_path(inbox, place), encoding="utf-8") as f:
            got = json.load(f)
    except (OSError, ValueError):
        return fresh   # 控えが無いか壊れていれば、新しい待ちとして数え直す（多く数えても、送る本数の上限に早く着くだけ）
    if not isinstance(got, dict) or got.get("session") != session or got.get("tasks") != tasks:
        return fresh
    spent = got.get("spent")   # 控えはこの待ち受けだけが書く。壊れた spent は、壊れた控えと同じく新しい待ちとして 0 から数える
    return {"sent": got.get("sent") if isinstance(got.get("sent"), int) else 0, "stopped": got.get("stopped") is True,
            "spent": spent if isinstance(spent, (int, float)) and not isinstance(spent, bool) and spent >= 0 else 0}


def warm_note(inbox, place, session, tasks, sent, stopped=False, spent=0):
    """keepalive を送った本数と、止めたかと、送った分の費用の累計を控えに書く。"""
    os.makedirs(_dir(inbox), exist_ok=True)
    _replace(warm_path(inbox, place), json.dumps({"session": session, "tasks": tasks, "sent": sent, "stopped": stopped,
                                                  "spent": spent}, ensure_ascii=False))


def compact_path(inbox, place):
    """keepalive の時刻の compact の判断の控え（{session, asked, deferred, turned, judged}。wake_hook.Warm が会話に compact の焦点を
    問うたか・会話が keepalive の時刻の問いに skip と答えて延ばした回数・ターンの終わりの問いに延ばした回数・判断で compact の印を
    付けたか）。"""
    return os.path.join(_dir(inbox), key(place) + ".compact.json")


def compact_state(inbox, place, session):
    """同じ会話（session）の compact の判断の控え {asked, deferred, turned, judged}。控えが無い・読めない・会話が替わっていれば
    {asked: False, deferred: 0, turned: 0, judged: False}。"""
    fresh = {"asked": False, "deferred": 0, "turned": 0, "judged": False}
    try:
        with open(compact_path(inbox, place), encoding="utf-8") as f:
            got = json.load(f)
    except (OSError, ValueError):
        return fresh   # 控えが無いか壊れていれば、問うていない・延ばしていないと見る（延ばす回数が上限から数え直しになるだけ）
    if not isinstance(got, dict) or got.get("session") != session:
        return fresh
    count = lambda v: v if isinstance(v, int) and not isinstance(v, bool) and v >= 0 else 0
    return {"asked": got.get("asked") is True, "judged": got.get("judged") is True,
            "deferred": count(got.get("deferred")), "turned": count(got.get("turned"))}


def compact_note(inbox, place, session, asked=False, deferred=0, judged=False, turned=0):
    """compact の判断の控えを書く。"""
    os.makedirs(_dir(inbox), exist_ok=True)
    _replace(compact_path(inbox, place), json.dumps({"session": session, "asked": asked, "deferred": deferred, "turned": turned,
                                                     "judged": judged}, ensure_ascii=False))


def compact_forget(inbox, place):
    """compact の判断の控えを消す（compact が済んだ・会話が --compact を打った。次の回は延ばした回数を 0 から数える）。"""
    with contextlib.suppress(FileNotFoundError):
        os.remove(compact_path(inbox, place))


LONG_WAIT = 3600   # --tree が「裏の処理を待ったまま動きが無い」と出す、裏の処理を残したターンの終わりからの秒
TURN_ROWS = ("user", "assistant")   # 会話の記録の行のうち、ターンが動いた印の type（人の文・知らせ・ツールの結果と、答え）


def turn_row(line):
    """会話の記録（transcript_path の JSONL）の 1 行がターンの行（type が TURN_ROWS）か。読めない行はターンの行と見ない。
    ターンの行でない行（ターンの終わりのフックの要約・手が空いた会話の要約 away_summary など）は、会話が止まっていても足される。
    サブエージェントの行（isSidechain）は本体の会話のターンでないので数えない。終えたターンの答えの行は Stop のフックより前に
    書かれる（2026-10-24 に my_notes の調べものの記録の 17 回のターンの終わりで、答えの行が stop_hook_summary より前に在るのを見た）。"""
    try:
        row = json.loads(line)
    except ValueError:
        return False
    return isinstance(row, dict) and row.get("type") in TURN_ROWS and not row.get("isSidechain")


def turned(path, pos):
    """会話の記録の pos バイト目より後に、ターンの行が足されたか。(足されたか, 次に読む位置)。書きかけの行（改行の無い終わり）は
    次に回す。記録が読めなければ足されていないと見る。記録が縮んだ（作り直された）なら足されたと見る。"""
    try:
        size = os.path.getsize(path)
        if size < pos:
            return True, size
        with open(path, "rb") as f:
            f.seek(pos)
            for line in iter(f.readline, b""):   # 行ごとに読み、ターンの行が見つかった所で打ち切る
                if not line.endswith(b"\n"):
                    break
                pos += len(line)
                if turn_row(line):
                    return True, pos
    except (OSError, TypeError, ValueError):
        return False, pos
    return False, pos


def waiting_path(inbox, place):
    """裏の処理を残して終えたターンの控え（{session, ask, tasks, at, transcript, pos}。--tree の long_wait が読む）。"""
    return os.path.join(_dir(inbox), key(place) + ".waiting.json")


def waiting_note(inbox, place, session, ask, tasks, at, transcript=None):
    """ターンの終わり（Stop）に、裏の処理（tasks。id の並びか数）を残したなら控えに書き、残さなかったなら控えを消す。控えには、その時の
    会話の記録（transcript）の大きさを pos に書く（long_wait が、その後にターンの行が足されたかで会話が動いたかを見る）。
    keepalive のターン（waiting_kept の印の有る控えの後のターン）の終わりで、会話・頼み・待つ処理が前の控えと同じなら、at は前の値を
    残す（keepalive は会話を動かしていない。残さないと、送るたびに long_wait の時計が戻り、止まった部署が --tree に出ない）。"""
    path = waiting_path(inbox, place)
    if not tasks:
        with contextlib.suppress(FileNotFoundError):
            os.remove(path)
        return
    try:
        pos = os.path.getsize(transcript) if transcript else None
    except OSError:
        pos = None
    before = _read_json(path)
    if (before.get("kept") is True and isinstance(before.get("at"), (int, float))
            and (before.get("session"), before.get("ask"), before.get("tasks")) == (session, ask, tasks)):
        at = before["at"]
    os.makedirs(_dir(inbox), exist_ok=True)
    _replace(path, json.dumps({"session": session, "ask": ask, "tasks": tasks, "at": at, "transcript": transcript, "pos": pos},
                              ensure_ascii=False))


def waiting_kept(inbox, place):
    """keepalive を送った印を控えに付ける（次のターンの終わりの waiting_note が、そのターンを会話の動きと数えない）。"""
    path = waiting_path(inbox, place)
    got = _read_json(path)
    if got:
        _replace(path, json.dumps({**got, "kept": True}, ensure_ascii=False))


def _read_json(path):
    try:
        with open(path, encoding="utf-8") as f:
            got = json.load(f)
    except (OSError, ValueError):
        return {}
    return got if isinstance(got, dict) else {}


def long_wait(inbox, place, attrs, now=None):
    """部署が、納品していない同じ頼みを受けたまま、裏の処理を残したターンの終わりから LONG_WAIT 秒を超えて会話が動いていなければ
    {since: そのターンの終わりの時刻, tasks: 待つ裏の処理の数}。ほかは None（控えが無い・会話か頼みが替わった・納品した・その後に
    会話の記録にターンの行が足された・記録の場所が控えに無い）。裏の処理の終わりを待つ形の誤り（待ちのループが互いに当たって
    終わらないなど）で、人が気づくまで止まった部署を --tree に出す（2026-10-23 に my_notes の調べものが約 11 時間止まった。
    my_notes の受付 f55a1b）。"""
    try:
        with open(waiting_path(inbox, place), encoding="utf-8") as f:
            got = json.load(f)
    except (OSError, ValueError):
        return None
    ask = attrs.get("ask")
    if (not isinstance(got, dict) or not isinstance(got.get("at"), (int, float)) or not ask or attrs.get("delivered") == ask
            or got.get("ask") != ask or got.get("session") != attrs.get("session")
            or not isinstance(got.get("transcript"), str) or not isinstance(got.get("pos"), int) or got["pos"] < 0):
        return None
    if (time.time() if now is None else now) - got["at"] < LONG_WAIT or turned(got["transcript"], got["pos"])[0]:   # 読むのは控えの後だけ
        return None
    tasks = got.get("tasks") if isinstance(got.get("tasks"), list) else []
    count = len(tasks) or None
    if len(tasks) == 1 and str(tasks[0]).startswith("count:"):   # id の分からない裏の処理は数だけ（warm_for の count:N）
        count = int(tasks[0][6:]) if tasks[0][6:].isdigit() else None
    return {"since": got["at"], "tasks": count}


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
    with _mark_lock(mark_path(inbox, place)):
        _replace(mark_path(inbox, place), json.dumps(
            {"names": names, "session": session, "owner": owner, "pid": os.getpid(), "token": token, "place": place,
             "since": now}, ensure_ascii=False))
    if read_pos(inbox, place) is None:
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


def alive(mark, now=None, posix=os.name != "nt", starts=None):
    """印の会話が生きているか。POSIX は印を書いた待ち受けの親（会話の処理）が在るか、Windows は印の更新が FRESH 秒以内か
    （Windows の os.kill は 0 を渡しても処理を止めるので使わない）。starts（処理の番号 → 起きた時刻。claudex.start_times）を
    渡せば、その番号の処理が印を書いた時（since）より SLACK 秒より後に起きていれば、番号を使い回した別の処理と見て死んだとする
    （会話が終わった後に同じ番号の処理が起きると、os.kill だけでは生きて見えた）。since の無い・0 の印（前の版の印と試験）は見ない。"""
    if posix:
        owner = mark.get("owner")
        if not isinstance(owner, int) or owner <= 1:
            return False
        try:
            os.kill(owner, 0)
        except PermissionError:
            pass   # 処理は在り、別の利用者の物（生きている）
        except OSError:
            return False
        since = mark.get("since")
        born = (starts or {}).get(owner)
        return not (born is not None and isinstance(since, (int, float)) and since > 0 and born > since + SLACK)
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
    return alive({"owner": got.get("pid"), "since": got.get("since")}, now, posix, chat.start_times())


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
    with _mark_lock(mark_path(inbox, place)):
        got = read_mark(inbox, place)
        if got and got.get("token") == token:
            try:
                os.unlink(mark_path(inbox, place))
            except OSError:
                pass   # 残った印は、会話が終われば送る側が待ち受けを探すとき（listening）の _drop_dead が消し、会話が生きていれば次の待ち受けが書き直す（claim）


def _living(inbox, now, posix, starts=None):
    """受付箱の、生きた会話の印の並び（ファイルの名前の順）。POSIX では、会話の死んだ印を見つけたら消す（読んだ所の .pos は残す。
    待ち受けが居た跡として順番待ちが使う）。消す直前に読み直し、token が替わっていれば（新しい待ち受けが書いた）消さない。
    Windows は更新の時刻で見るので、ターンの間の会話の印も古く見える。消さない。"""
    now = time.time() if now is None else now
    try:
        names = sorted(os.listdir(_dir(inbox)))
    except OSError:
        return
    if posix and starts is None:
        starts = chat.start_times()
    for n in names:
        if not n.endswith(".json"):
            continue
        path = os.path.join(_dir(inbox), n)
        try:
            mtime = os.stat(path).st_mtime
            with open(path, encoding="utf-8") as f:
                got = json.load(f)
        except FileNotFoundError:
            continue   # 並べた後に消えた（印は差し替えで書く _replace なので、書きかけは無い）
        except (OSError, ValueError) as e:
            filex.warn(f"注記: 待ち受けの印 {path} が読めない（{e}）。居ない待ち受けとした。直すか、要らなければ消す")
            continue
        if not isinstance(got, dict):
            continue
        if alive({**got, "_mtime": mtime}, now, posix, starts):
            yield got
        elif posix:
            _drop_dead(path, got.get("token"))


def _drop_dead(path, token):
    """死んだ会話の印を消す。読み直した token が同じときだけ（読んでから消すまでに新しい待ち受けが書いた印は残す）。"""
    try:
        with _mark_lock(path):
            with open(path, encoding="utf-8") as f:
                again = json.load(f)
            if isinstance(again, dict) and again.get("token") == token:
                os.unlink(path)   # 閉じてから消す（Windows は開いたファイルを消せない）
    except (OSError, ValueError):
        pass   # 先に消えたか消せない。死んだ会話の印は alive が死んだとし続けるので、次の掃除でまた消す


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
    try:
        _replace(path, json.dumps(item, ensure_ascii=False))
    except FileNotFoundError:   # 作った置き場を、片付け（health.stale_queue の古い空の置き場）が書く前に消した。作り直して 1 度だけ書き直す
        _replace(path, json.dumps(item, ensure_ascii=False))
    return path


def move(item, inbox, place, body):
    """find か queued で見つけた件を、中身を body に書き直してから、ほかの場所の順番待ちへ rename で移す（同じ受付箱の中なので、
    件はどの時点でもどちらか 1 か所にだけ在る。途中で落ちても、2 か所に残らず、消えもしない）。移した先のパスを返す。"""
    _replace(item["path"], json.dumps(body, ensure_ascii=False))
    path = os.path.join(queue_dir(inbox, place), f"{body['id']}.json")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    os.replace(item["path"], path)
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


def read_new(log, pos, end=None):
    """台帳の pos バイト目から先（end を渡せば end バイト目まで）の、書き終わった行（改行まで）の並びと、読み終えた所と、読めない行の
    並び（filex.read_jsonl の bad）。読めない行が在れば、その前の行までを返し、読み終えた所はその行の頭で止める（先へ進めると、その行の
    知らせが誰にも気づかれずに消える）。行を直すか消せば、次に読むときにその行から続く。"""
    try:
        got = filex.read_jsonl(log, pos, end, stop=True)
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
        pass   # 覚えが無いか読めない: まだ知らせていないとして知らせる（黙る側に倒さない）
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


def read_pos(inbox, place):
    """その場所の待ち受けが台帳を読んだ所（バイト）。無いか読めなければ None。"""
    try:
        with open(pos_path(inbox, place), encoding="utf-8") as f:
            return int(f.read().strip())
    except (OSError, ValueError):
        return None


def start_pos(inbox, place, pos):
    """その場所に読んだ所が無ければ pos を書く（初めての待ち受けが台帳の終わりから読み始めて、その前に置いた行を取りこぼさない）。"""
    if read_pos(inbox, place) is None:
        _replace(pos_path(inbox, place), str(pos))


def _names_at(names, since, pos):
    """台帳の pos バイト目で自分宛てと見る宛先と、その見方が替わる次の位置（無ければ None）。since（{宛先: 位置}）の宛先は、その位置
    より後の行だけを自分宛てと見る（--handover で継いだ宛先。その位置より前は、前の部署が読んだか、後継の宛先へ写し直した物）。"""
    later = [at for to, at in since.items() if to in names and at > pos]
    return [n for n in names if not (n in since and since[n] > pos)], (min(later) if later else None)


def watch(inbox, place, names, session, owner, token, err, now=time.time, pause=time.sleep, parent=os.getppid, check=None,
          ready=None, since=None, idle=None):
    """待ち受けの本体。終了の値（2 は会話に渡す字を err に出した。0 は替わった・会話が居なくなった・check が終わらせた）。
    owner は待ち受けを起動した会話の処理（Claude Code）の番号で、parent() がそれと違えば（会話の処理が落ちて親が替わった）終わる。
    check は、読み始める時と、自分宛ての順番待ちの知らせ（queued）を見るたびに（同じ回にほかの知らせが在れば、そちらを先に会話へ
    渡して呼ばない）呼ぶ関数で、("wake", 字)（その字で会話を再開させる）・
    ("end", None)（0 で終わる。会話を空にしたなど）・HOLD（渡せる時を待つ。BEAT ごとに呼び直す）・None（待ち続ける）を返す。
    ready は会話が字を受けられるかを返す関数（None なら常に受けられる）。受けられない間は、印を張ったまま台帳を読まず check も
    呼ばない（読んだ所を進めないので、受けられるようになってから同じ行で起動する）。since は {宛先: 位置} で、その宛先は台帳のその
    位置より後の行だけを自分宛てと見る（_names_at）。idle は、渡す知らせが無い周ごとに呼ぶ関数で、字を返せばその字で会話を
    再開させる（keepalive。wake_hook.Warm）。None を返せば待ち続ける。"""
    claim(inbox, place, names, session, owner, token, now())
    pause(GRACE)
    log = os.path.join(inbox, LOG)
    pos = read_pos(inbox, place)
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
                    pass   # 印が消えたか触れない（消えていれば次の周の read_mark が見て抜ける）
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
            now_names, cut = _names_at(names, since or {}, pos)
            records, pos, bad = read_new(log, pos, cut)
            hits = [r for r in records if mine(r, now_names)]
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
                pass   # 印が消えたか触れない（消えていれば次の周の read_mark が見て抜ける）
            beat = now()
        said = idle() if idle else None
        if said:
            return _finish(("wake", said), err)
        pause(POLL)


# 会話から切り離してコマンドを走らせる殻（POSIX）。外の sh はすぐ終わり、中の ( … ) & は親を失って init の子になる。会話の処理を止めると
# Claude Code はフックの子孫も止めるので、フックの子のまま走らせた --move は、自分が止めた前の会話と一緒に止まり、何も書かずに消えた
# （2026-10-17 の my_notes の段取り。16:03 と 16:54 に moves/ の出力が 0 バイトのまま、窓口が消えた。部署の --move の跡も同じ）
# done は走らせる前に空で作る（空なら走っている途中、無ければこの殻の外で走らせた物。--tree が終わりの値の無い物を見分ける。health.py）
DETACH = 'log=$1; done=$2; shift 2; : >"$done"; ( "$@" >"$log" 2>&1 </dev/null; echo $? >"$done" ) &'


def detached(argv, log, done):
    """argv を会話から切り離して走らせる sh の並び。出力は log に、終わりの値は done に書く。"""
    return ["/bin/sh", "-c", DETACH, "sh", log, done, *argv]
