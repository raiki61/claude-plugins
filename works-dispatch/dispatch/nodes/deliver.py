#!/usr/bin/env python3
"""deliver ノード: 依頼と納品（会社の形の設計 4.5・4.10 の 3・9.2）の中身。宛先と頼み元の窓を決め、要約の項目を確かめ、受付箱に
記録を残し、窓に 1 行を打ち込む。流れ（どの順に呼ぶか）は orders.py が持つ。

- 宛先: 「会社/役」か部署の名前。会社を省けば頼む側の会社。部署の名前（属性 company.name）が先に当たる。役で宛てたときは、その役の
  常設の部署（company.residency=resident）に届け、無ければ新しく立てる（4.10 の 1・2。都度の部署は頼みごとに立てる）。
- 頼み元の窓: 部署の属性 company.boss-session（頼んだ会話の id）、無ければ company.boss と company.boss-account から会話の一覧で
  引いた会話を、herdr のペインと結ぶ。結び方は、その会話を持つ部署の窓、ペインの会話の印（agent_session）と場所が合うもの、
  頼んだときのペイン（company.boss-pane）の順。ペインの会話の印は裏の会話の attach の窓では別の会話の id を指すことがある
  （2026-10-16 に herdr 0.9.3 で見た）ので、場所が合わない物は使わない。
- 要約の項目: 既定は「結論」「決め手」「残った疑問」「枝」。会社の形（.claude/company.toml か設定の置き場の同じ書き方のファイル）の
  [[roles]] の deliver で役ごとに替えられる（読むのは role ノード）。項目は見出し（`## 結論`）か行の頭の札（`結論: …`）で書く。結論は 3 行以内、
  決め手は原典の URL を含むこと、ほかは空でないこと。枝は書かなければ部署の枝を機械が足す。
- 納品の検査: 役の deliver_check（会社の形）の命令を、項目を確かめた後に部署の作業場の根で走らせる（gate）。何を確かめるかは会社の
  側のスクリプトが持ち、ここは決め打ちしない。0 以外で終われば送らない。
- 受付箱: 頼み元の会社の共通の .git の中の company/inbox（INBOX）。commit されず、部署の worktree を消しても残り（4.10 の 1。
  部署ごとの .git/worktrees/<部署> は git worktree remove で一緒に消える）、勤め先のリポジトリの .gitignore も触らない。
  頼みと納品の本文を 1 件 1 ファイルで置き、log.jsonl に誰が誰に何を頼み何が返ったかを 1 行ずつ足す。
- Stop フック: 部署（company.role の在る場所）の会話で、受けた頼み（company.ask）の納品（company.delivered）が済んでいなければ、
  止まる前に納品の命令で返すよう差し戻す。同じ会話・同じ頼みで差し戻すのは STOP_LIMIT 回まで。
"""

import hashlib
import json
import os
import pathlib
import re
import time
import uuid

import gitx

INBOX = ("company", "inbox")      # 共通の .git の下の受付箱
LOG = "log.jsonl"
DEFAULT_ITEMS = ("結論", "決め手", "残った疑問", "枝")
BRANCH_ITEM = "枝"                 # 書かなければ部署の枝を機械が足す項目
CONCLUSION_ITEM, CONCLUSION_LINES = "結論", 3
URL_ITEMS = ("決め手",)            # 原典の URL を含むこと
URL = re.compile(r"https?://\S+")
SHORT_TEXT = 400                  # これより長いか改行を含む頼みの文は、本文を窓に打たず受付箱のファイルを指す
STOP_LIMIT = 3                    # 同じ会話・同じ頼みで Stop フックが差し戻す上限


class DeliverError(Exception):
    """宛先・頼み元・受付箱が決まらない。訳を 1 つの文で持つ。"""


def inside(cwd, path):
    c, p = pathlib.PurePath(os.path.realpath(cwd)), pathlib.PurePath(os.path.realpath(path))
    return c == p or p in c.parents


# ---- 宛先 ----

def parse_target(target):
    """宛先の字から (会社の名前か None, 役か部署の名前)。「会社/役」の会社は最後の / の前。"""
    company, sep, rest = target.strip().rpartition("/")
    if not rest:
        raise DeliverError(f"宛先「{target}」に役か部署の名前が無い（「会社/役」か部署の名前で渡す）")
    return (company or None) if sep else None, rest


def find_target(companies, here_root, target, task=None, current=lambda company, name: name):
    """宛先を決める。companies は tree.build の結果、here_root は頼む側の会社の根。current は (会社, 役の名前) → 今の役の名前
    （会社の形の former_names で、前の役の名前で宛てても、前の名前を属性に持つ部署でも、今の役に当たる）。
    返すのは {company, department（在れば tree の部署の 1 行）, role（役で宛てたとき）}。
    部署の名前（今の名前、無ければ前の名前）が先に当たる（会社を書けばその会社の中だけ）。役で宛てて task（--task の部署の名前）を
    渡せば、その名前の部署に届け、無ければ department は None（新しく立てる。同じ役の常設の部署が名前違いで居ても
    使わない）。task が無く、役で宛てて常設の部署が無ければ department は None（新しく立てる）。"""
    company_name, name = parse_target(target)
    if company_name is None:
        pool = companies
    else:
        pool = [c for c in companies if c["name"] == company_name
                or os.path.basename(os.path.normpath(c["root"])) == company_name]
        if not pool:
            known = "、".join(c["name"] for c in companies) or "なし"
            raise DeliverError(f"会社「{company_name}」が herdr に開いていない（開いている会社: {known}）")
    named = [(c, d) for c in pool for d in c["departments"] if d["attrs"].get("name") == name]
    if not named:
        # 名前を替えた部署（--reorg・--desk）は、前の名前でも引く（今の名前が先）
        named = [(c, d) for c in pool for d in c["departments"] if name in gitx.former_names(d["attrs"])]
    if len(named) > 1:
        where = "、".join(f"{c['name']}/{d['branch']}" for c, d in named)
        raise DeliverError(f"部署の名前「{name}」が 2 つ以上ある（{where}）。「会社/役」で宛てるか、会社を添える")
    if named:
        return {"company": named[0][0], "department": named[0][1], "role": named[0][1]["attrs"].get("role")}
    if company_name is None:
        home = [c for c in companies if os.path.realpath(c["root"]) == os.path.realpath(here_root)] if here_root else []
        if not home:
            raise DeliverError(f"「{name}」という部署が無く、頼む側の会社も herdr に開いていないので役で宛てられない"
                               "（「会社/役」で渡す）")
        company = home[0]
    else:
        company = pool[0]
    if task:
        # 役で宛てて部署の名前（--task）も渡したときは、その名前の部署に届け、無ければ新しく立てる。同じ役の常設の部署が名前違いで
        # 1 つ居ても、そこへは届けない（受け持ちごとに担当が居る形で、ほかの受け持ちの担当に届いてしまうため）
        mine = [d for d in company["departments"] if d["attrs"].get("name") == task] or \
            [d for d in company["departments"] if task in gitx.former_names(d["attrs"])]
        if len(mine) > 1:
            raise DeliverError(f"{company['name']} に部署の名前「{task}」が 2 つ以上ある"
                               f"（{'、'.join(d['branch'] or d['path'] for d in mine)}）")
        return {"company": company, "department": mine[0] if mine else None,
                "role": current(company, mine[0]["attrs"].get("role") or name if mine else name)}
    name = current(company, name)
    resident = [d for d in company["departments"]
                if d["attrs"].get("role") and current(company, d["attrs"]["role"]) == name
                and d["attrs"].get("residency") == "resident"]
    if len(resident) > 1:
        raise DeliverError(f"{company['name']} に役「{name}」の常設の部署が 2 つ以上ある"
                           f"（{'、'.join(d['attrs'].get('name') or d['branch'] for d in resident)}）。部署の名前で宛てる")
    return {"company": company, "department": resident[0] if resident else None, "role": name}


def window(dept):
    """部署の窓（会話の居るペイン）。無ければ None。"""
    return next((p["pane_id"] for p in dept["panes"] if p.get("agent")), None)


# ---- 頼み元 ----

def boss_session(attrs, sessions):
    """頼み元の会話の (id, 一覧の 1 件か None)。sessions は アカウントの名 → 会話の並び。名前で引くのは、その名前の終わっていない
    会話が 1 つに決まるときだけ。一時停止したまま --resume で開き直した会話は、同じ id で古い処理と今の処理が並ぶので、今の処理
    （startedAt の新しい方）を 1 件とする。"""
    sid = attrs.get("boss-session")
    pool = sessions.get(attrs.get("boss-account"), []) if attrs.get("boss-account") else \
        [s for items in sessions.values() for s in items]
    if sid:
        return sid, _latest(s for s in pool if s.get("sessionId") == sid)
    if not attrs.get("boss"):
        return None, None
    alive = {}
    for s in pool:
        if s.get("name") == attrs["boss"] and s.get("state") not in ("done", "failed", "stopped"):
            alive.setdefault(s.get("sessionId"), []).append(s)
    return (next(iter(alive)), _latest(next(iter(alive.values())))) if len(alive) == 1 else (None, None)


def _latest(items):
    return max(items, key=lambda s: s.get("startedAt") or 0, default=None)


def _same_place(pane, cwd):
    return bool(cwd and pane.get("cwd")) and os.path.realpath(pane["cwd"]) == os.path.realpath(cwd)


def boss_window(attrs, sid, entry, panes, companies):
    """頼み元の窓のペイン。(ペイン, 結び方) か (None, 訳)。"""
    cwd = entry.get("cwd") if entry else None
    if sid:
        for c in companies:
            for d in c["departments"]:
                if d["attrs"].get("session") == sid and window(d):
                    return window(d), "部署の窓"
        hits = [p for p in panes if (p.get("agent_session") or {}).get("value") == sid and p.get("agent")]
        good = [p for p in hits if _same_place(p, cwd)] if cwd else hits
        if len(good) == 1:
            return good[0]["pane_id"], "会話の印"
    hint = attrs.get("boss-pane")
    if hint:
        p = next((p for p in panes if p["pane_id"] == hint), None)
        if p and p.get("agent") and (not cwd or _same_place(p, cwd)):
            return hint, "頼んだときのペイン"
    if not sid and not hint:
        return None, "頼み元（company.boss-session か、company.boss とそのアカウントで 1 つに決まる会話）が分からない"
    return None, "頼み元の会話の居るペインが herdr に見つからない（窓を閉じたか、会話が終わった）"


# ---- 受付箱と記録 ----

def inbox_of(common_dir):
    return os.path.join(common_dir, *INBOX)


def digest(text):
    """頼みの本文の指紋（前後の空白を除いた字の sha256）。同じ中身の頼みを 2 度積まない見分けに使う。"""
    return hashlib.sha256((text or "").strip().encode("utf-8")).hexdigest()


def common_of_inbox(inbox):
    """受付箱の場所から、その会社の共通の .git の場所（inbox_of の逆）。"""
    path = os.path.normpath(inbox)
    for _ in INBOX:
        path = os.path.dirname(path)
    return path


def new_id(now, rand=None):
    """受付番号。時刻（UTC）と短い乱数。"""
    stamp = time.strftime("%Y%m%d-%H%M%S", time.gmtime(now))
    return f"{stamp}-{rand or uuid.uuid4().hex[:6]}"


def put(inbox, name, text):
    """受付箱に本文を 1 件置き、そのパスを返す。"""
    os.makedirs(inbox, exist_ok=True)
    path = os.path.join(inbox, name)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text if text.endswith("\n") else text + "\n")
    return path


def log(inbox, record):
    """受付箱の台帳（log.jsonl）に 1 行足す。"""
    os.makedirs(inbox, exist_ok=True)
    with open(os.path.join(inbox, LOG), "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")


def records(inbox):
    try:
        with open(os.path.join(inbox, LOG), encoding="utf-8") as f:
            return [json.loads(line) for line in f if line.strip()]
    except FileNotFoundError:
        return []


# ---- 要約の項目 ----

def required_items(role):
    """その役の必須の項目。role は会社の形の役の項目（role ノードが [[roles]] から読んだ物。無ければ None）で、deliver が有れば
    それを、無ければ既定の項目を使う。"""
    return list((role or {}).get("deliver") or DEFAULT_ITEMS)


def _label(names):
    alt = "|".join(re.escape(n) for n in sorted(names, key=len, reverse=True))
    return (re.compile(rf"^\s*#{{1,6}}\s*(?:\*\*)?({alt})(?:\*\*)?\s*[:：]?\s*$"),
            re.compile(rf"^\s*(?:[-*]\s+)?(?:\*\*)?({alt})(?:\*\*)?\s*[:：]\s*(.*)$"))


def parse(text, names):
    """要約の本文から {項目: 本文}。項目は見出し（`## 結論`）か行の頭の札（`結論: …`）で始まり、次の項目か見出しまで続く。"""
    heading, label = _label(names)
    out, cur = {}, None
    for line in text.splitlines():
        m = heading.match(line)
        if m:
            cur = m.group(1)
            out.setdefault(cur, [])
            continue
        m = label.match(line)
        if m:
            cur = m.group(1)
            out.setdefault(cur, []).append(m.group(2))
            continue
        if re.match(r"^\s*#{1,6}\s", line):
            cur = None
            continue
        if cur:
            out[cur].append(line)
    return {k: "\n".join(v).strip() for k, v in out.items()}


def check(items, required):
    """欠けている項目の訳の並び（空ならそろっている）。"""
    out = []
    for name in required:
        body = items.get(name, "")
        if not body:
            out.append(f"{name}（無いか空）")
        elif name == CONCLUSION_ITEM and len([x for x in body.splitlines() if x.strip()]) > CONCLUSION_LINES:
            out.append(f"{name}（{CONCLUSION_LINES} 行を超える）")
        elif name in URL_ITEMS and not URL.search(body):
            out.append(f"{name}（原典の URL が無い）")
    return out


GATE_TAIL = 20   # 納品の検査が通らなかったとき、部署に返す検査の出力の終わりの行数


def gate(command, place, payload, runner):
    """納品の検査。command（シェルの字）を place（部署の作業場の根）で走らせ、payload（role・ask・branch・place・items・summary）を
    JSON で標準入力に渡す。(終了の値, 標準出力と標準エラーの終わりの GATE_TAIL 行)。0 なら通った、0 以外なら送らない。
    runner は subprocess.run（ノードは subprocess を持たないので、流れの orders.py が渡す）。"""
    p = runner(command, shell=True, cwd=place, input=json.dumps(payload, ensure_ascii=False), capture_output=True,
               text=True, encoding="utf-8", errors="replace")
    both = (p.stdout or "") + (p.stderr or "")
    return p.returncode, "\n".join(both.rstrip().splitlines()[-GATE_TAIL:])


def summary_text(items, required):
    """受付箱に置く要約の本文（項目の順は必須の並び、その後に書かれた順）。"""
    order = list(required) + [k for k in items if k not in required]
    return "\n\n".join(f"## {k}\n{items[k]}" for k in order if items.get(k))


def flat(text):
    return " / ".join(x.strip() for x in text.splitlines() if x.strip())


# ---- 窓に打ち込む 1 行 ----

def deliver_command(run):
    """run は dispatch.py を起こす字（引用符付きの Python と dispatch.py のパス。orders.RUN）。"""
    return f"{run} --deliver <要約のファイル>"


def rules_of(required):
    """要る項目に付く決まりの短い文の並び（返し方の文に添えて、部署が送り返されてから知ることを減らす）。"""
    out = []
    if CONCLUSION_ITEM in required:
        out.append(f"{CONCLUSION_ITEM}は {CONCLUSION_LINES} 行以内")
    out += [f"{name}には原典の http(s) の URL が要る（無い URL や、決め手でない URL を足さない）" for name in required if name in URL_ITEMS]
    if BRANCH_ITEM in required:
        out.append(f"{BRANCH_ITEM}は書かなければ機械が足す")
    return out


def tail(required, run):
    """頼みの後ろに付ける、返し方の 1 文。要る項目と、その項目に付く決まり（URL が要るか など）を書く。"""
    rules = rules_of(required)
    return (f" 終わったら、要約を {'・'.join(required)} の見出しで書いたファイルにして、{deliver_command(run)} で"
            "頼み元へ返す（項目が足りなければ送られずに返ってくる" + (f"。{'・'.join(rules)}" if rules else "") + "）。")


def ask_line(ask_id, sender, text, file, required, run):
    """宛先の部署の窓に打つ 1 行。短い文は本文ごと、長い物は受付箱のファイルを指す。
    「その通りに」とは書かない（頼みに異論を返してよいかは会社の形の役の本文が決める。頼みの文がそれを打ち消さないように）。"""
    head = f"頼みです（受付 {ask_id}、{sender} から）: "
    body = text if text and "\n" not in text and len(text) <= SHORT_TEXT else f"{file} を読んで進めてください。"
    return head + body + tail(required, run)


def deliver_line(ask_id, sender, branch, items, required, path):
    """頼み元の窓に打つ 1 行（要約を本文ごと。全文は受付箱）。"""
    order = list(required) + [k for k in items if k not in required]
    body = " ".join(f"【{k}】{flat(items[k])}" for k in order if items.get(k))
    return f"納品です（受付 {ask_id or '-'}、{sender}・枝 {branch or '-'} から）: {body} （全文: {path}）"


# 送った 1 行が入力欄に残っていないかを見る回数（1 回ごとに pause）
SUBMIT_LOOKS = 3


def send(pane, line, h, pause=None):
    """窓の会話に 1 行を送る（herdr agent prompt。終わりは待たない）。書く口。(sent か failed, 訳)。
    pause を渡すと、送った後に入力欄（行の頭が ❯ の行）にその文が残っていないかを見て、残っていれば Enter を 1 回足す。
    Windows で、attach で戻した直後の会話に送った文が、入力欄に入ったまま送信されなかった（まっさらな環境での 7 回目の試しの 1）。
    入力欄が空のときの Enter は何もしないので、見誤っても害は無い。"""
    try:
        h.prompt(pane, line, False)
    except h.HerdrError as e:
        return "failed", str(e)
    if pause is not None:
        head = " ".join(line.split())[:20]
        for _ in range(SUBMIT_LOOKS):
            pause()
            try:
                tail = [x.strip() for x in h.read(pane, 12).splitlines() if x.strip()]
            except h.HerdrError:
                break
            if any(x.startswith("❯") and head in " ".join(x.split()) for x in tail[-8:]):
                try:
                    h.send_keys(pane, "enter")
                except h.HerdrError:
                    pass
                return "sent", "入力欄に残っていたので Enter を足した"
    return "sent", None


# 送った 1 行で会話が動き出したかを見る回数（1 回ごとに pause）と、届いていなければ打ち直す回数
CONFIRM_LOOKS = 8
SEND_TRIES = 3


def _rule(x):
    """会話の画面の横の罫線の行か（入力欄の上と下に引かれる「────」。上の罫線には部署の名前が入ることがある）。"""
    return x.count("─") >= 10


def input_box(screen):
    """会話の画面の入力欄の字（下から 2 本の罫線の間の行をつないだ物）。罫線が 2 本無ければ None（字を受けられる形でない）。"""
    lines = (screen or "").splitlines()
    rules = [i for i, x in enumerate(lines) if _rule(x)]
    if len(rules) < 2:
        return None
    return " ".join(" ".join(lines[rules[-2] + 1:rules[-1]]).split())


def ready(screen):
    """会話の画面が字を受けられる形か（入力欄が出ている）。"""
    return input_box(screen) is not None


def above_box(screen):
    """入力欄より上の画面の字（会話に届いた字が載る所）。"""
    lines = (screen or "").splitlines()
    rules = [i for i, x in enumerate(lines) if _rule(x)]
    return " ".join(" ".join(lines[:rules[-2]] if len(rules) >= 2 else lines).split())


def send_confirmed(pane, line, h, pause, busy):
    """窓の会話に 1 行を送り、会話が動き出した（busy() が真）のを見てから返す。書く口。(sent か failed, 訳)。
    Windows で、attach で戻した直後の会話に送った 1 行が、届かないか入力欄に残った（まっさらな環境での 9 回目の試しの 1）。
    送る前に入力欄が出るのを待ち、送った後は、入力欄に残っていれば Enter を足し、入力欄にも画面にも見えず動き出してもいなければ
    打ち直す（SEND_TRIES 回まで）。画面に送った字が見えていれば（入力欄でない所に）、届いたと見て打ち直さない（二重に送らない）。
    送る前から動いている会話は、打った字を番の後の待ちの列に回すので、動き出しでは確かめられない。入力欄に残れば Enter を足し、
    入力欄の上（待ちの列か、番の途中で取り込まれた会話の中）に載るか、入力欄から出たのを見て届いたとする。見えなくても打ち直さない
    （打った字は待ちの列に入るか番の途中で取り込まれる。打ち直すと同じ頼みが何度も届いた）。"""
    head = " ".join(line.split())[:20]
    was_busy = busy()
    seen = 0   # 送る前に入力欄より上に見えていた数（前に送った同じ字が画面に残っていても、届いたと見誤らない）
    for _ in range(CONFIRM_LOOKS):
        try:
            screen = h.read(pane, 40)
        except h.HerdrError:
            break
        if ready(screen):
            seen = above_box(screen).count(head)
            break
        pause()
    detail = None
    for attempt in range(1 if was_busy else SEND_TRIES):
        try:
            h.prompt(pane, line, False)
        except h.HerdrError as e:
            return "failed", str(e)
        entered = False
        for _ in range(CONFIRM_LOOKS):
            pause()
            if not was_busy and busy():
                return "sent", detail
            try:
                screen = h.read(pane, 40)
            except h.HerdrError:
                continue
            if head in (input_box(screen) or ""):
                if not entered:
                    try:
                        h.send_keys(pane, "enter")
                    except h.HerdrError:
                        pass
                    entered, detail = True, "入力欄に残っていたので Enter を足した"
            elif above_box(screen).count(head) > seen:
                return "sent", detail   # 入力欄から出て、入力欄より上に新しく載った（会話に届いた）
            elif was_busy and entered and ready(screen):
                return "sent", detail   # 入力欄に入った字が、Enter で入力欄から出た（待ちの列に回った）
        if was_busy:
            return "sent", "動いている会話に 1 回打った（待ちの列に載ったのを画面で見られなかったが、二重に送らないよう打ち直さない）"
        detail = f"届いたかを確かめられず打ち直した（{attempt + 1} 回目）"
    return "failed", f"{SEND_TRIES} 回打ったが、会話が動き出さない（部署の窓を見て、入力欄に残っていれば Enter を押す）"


CLEAR = "/clear"


def clear_talk(pane, h, pause, cleared):
    """窓の会話に /clear を打ち、会話が空になった（cleared() が真。会話の一覧の id が変わった）のを見てから返す。書く口。
    (cleared・unconfirmed・failed, 訳)。入力欄に /clear が残っていれば Enter を 1 回足す（残ったまま頼みを打つと、頼みの頭に
    /clear が付いて届く）。見えなくても打ち直さない（2 度打っても害は無いが、空になったかは一覧でしか分からない）。"""
    try:
        h.prompt(pane, CLEAR, False)
    except h.HerdrError as e:
        return "failed", str(e)
    entered = False
    for _ in range(CONFIRM_LOOKS):
        pause()
        if cleared():
            return "cleared", None
        try:
            box = input_box(h.read(pane, 40)) or ""
        except h.HerdrError:
            continue
        if CLEAR in box and not entered:
            try:
                h.send_keys(pane, "enter")
            except h.HerdrError:
                pass
            entered = True
    return "unconfirmed", "/clear を打ったが、会話の id が変わったのを見られなかった（前の会話のまま頼みが届いたかもしれない）"


# ---- Stop フック ----

def stop_verdict(payload, attrs, count, run):
    """差し戻すなら、その訳の文。差し戻さないなら None。count はこの会話・この頼みで差し戻した回数。
    部署が --wait で人の答え待ちにした頼み（company.waiting が今の頼み）は促さない（人がその会話に打つと印が外れ、また促す）。"""
    if not attrs.get("role"):
        return None
    ask = attrs.get("ask")
    if not ask or attrs.get("delivered") == ask or attrs.get("waiting") == ask:
        return None
    sid = payload.get("session_id")
    if attrs.get("session") and sid and attrs["session"] != sid:
        return None   # 同じ作業場の別の会話（部署の会話ではない）
    if count >= STOP_LIMIT:
        return None
    boss = attrs.get("boss") or "頼み元"
    return (f"頼み（受付 {ask}）をまだ納品していない。止まる前に、要約をファイルに書いて {deliver_command(run)} で"
            f"{boss} へ返す（足りない項目は命令が教える）。返せない訳があれば、それを要約の「残った疑問」に書いて返す"
            f"（この差し戻しは {STOP_LIMIT} 回まで。{count + 1} 回目）。")


def stop_count_path(tmp_dir, session_id, ask):
    safe = re.sub(r"[^0-9A-Za-z_.-]", "_", f"{session_id}-{ask}")
    return os.path.join(tmp_dir, "works-dispatch-stop", safe)
