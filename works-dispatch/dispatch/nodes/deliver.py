#!/usr/bin/env python3
"""deliver ノード: 依頼と納品（会社の形の設計 4.5・4.10 の 3・9.2）の中身。宛先と頼み元の窓を決め、要約の項目を確かめ、受付箱に
記録を残し、窓に 1 行を打ち込む。流れ（どの順に呼ぶか）は orders.py が持つ。

- 宛先: 「会社/役」か部署の名前。会社を省けば頼む側の会社。部署の名前（属性 company.name）が先に当たる。役で宛てたときは、その役の
  常駐の部署（company.residency=resident）に届け、無ければ新しく立てる（4.10 の 1・2。都度の部署は頼みごとに立てる）。
- 頼み元の窓: 部署の属性 company.boss-session（頼んだ会話の id）、無ければ company.boss と company.boss-account から会話の一覧で
  引いた会話を、herdr のペインと結ぶ。結び方は、その会話を持つ部署の窓、ペインの会話の印（agent_session）と場所が合うもの、
  頼んだときのペイン（company.boss-pane）の順。ペインの会話の印は裏の会話の attach の窓では別の会話の id を指すことがある
  （2026-10-16 に herdr 0.9.3 で見た）ので、場所が合わない物は使わない。
- 要約の項目: 既定は「結論」「決め手」「残った疑問」「枝」。会社の形（.claude/company.toml か設定の置き場の同じ書き方のファイル）の
  [[roles]] の deliver で役ごとに替えられる（読むのは role ノード）。項目は見出し（`## 結論`）か行の頭の札（`結論: …`）で書く。結論は 3 行以内、
  決め手は原典の URL を含むこと、ほかは空でないこと。枝は書かなければ部署の枝を機械が足す。
- 受付箱: 頼み元の会社の共通の .git の中の company/inbox（INBOX）。commit されず、部署の worktree を消しても残り（4.10 の 1。
  部署ごとの .git/worktrees/<部署> は git worktree remove で一緒に消える）、勤め先のリポジトリの .gitignore も触らない。
  頼みと納品の本文を 1 件 1 ファイルで置き、log.jsonl に誰が誰に何を頼み何が返ったかを 1 行ずつ足す。
- Stop フック: 部署（company.role の在る場所）の会話で、受けた頼み（company.ask）の納品（company.delivered）が済んでいなければ、
  止まる前に納品の命令で返すよう差し戻す。同じ会話・同じ頼みで差し戻すのは STOP_LIMIT 回まで。
"""

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


def find_target(companies, here_root, target, task=None):
    """宛先を決める。companies は tree.build の結果、here_root は頼む側の会社の根。
    返すのは {company, department（在れば tree の部署の 1 行）, role（役で宛てたとき）}。
    部署の名前（今の名前、無ければ前の名前）が先に当たる（会社を書けばその会社の中だけ）。役で宛てて task（--task の部署の名前）を
    渡せば、その名前の部署に届け、無ければ department は None（新しく立てる。同じ役の常駐の部署が名前違いで居ても
    使わない）。task が無く、役で宛てて常駐の部署が無ければ department は None（新しく立てる）。"""
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
        # 役で宛てて部署の名前（--task）も渡したときは、その名前の部署に届け、無ければ新しく立てる。同じ役の常駐の部署が名前違いで
        # 1 つ居ても、そこへは届けない（受け持ちごとに担当が居る形で、ほかの受け持ちの担当に届いてしまうため）
        mine = [d for d in company["departments"] if d["attrs"].get("name") == task] or \
            [d for d in company["departments"] if task in gitx.former_names(d["attrs"])]
        if len(mine) > 1:
            raise DeliverError(f"{company['name']} に部署の名前「{task}」が 2 つ以上ある"
                               f"（{'、'.join(d['branch'] or d['path'] for d in mine)}）")
        return {"company": company, "department": mine[0] if mine else None,
                "role": mine[0]["attrs"].get("role") or name if mine else name}
    resident = [d for d in company["departments"]
                if d["attrs"].get("role") == name and d["attrs"].get("residency") == "resident"]
    if len(resident) > 1:
        raise DeliverError(f"{company['name']} に役「{name}」の常駐の部署が 2 つ以上ある"
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
    """宛先の部署の窓に打つ 1 行。短い文は本文ごと、長い物は受付箱のファイルを指す。"""
    head = f"頼みです（受付 {ask_id}、{sender} から）: "
    body = text if text and "\n" not in text and len(text) <= SHORT_TEXT else f"{file} を読んで、その通りに進めてください。"
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


# ---- Stop フック ----

def stop_verdict(payload, attrs, count, run):
    """差し戻すなら、その訳の文。差し戻さないなら None。count はこの会話・この頼みで差し戻した回数。"""
    if not attrs.get("role"):
        return None
    ask = attrs.get("ask")
    if not ask or attrs.get("delivered") == ask:
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
