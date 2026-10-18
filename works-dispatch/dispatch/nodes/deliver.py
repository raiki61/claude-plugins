#!/usr/bin/env python3
"""deliver ノード: 依頼と納品（会社の形の設計 4.5・4.10 の 3・9.2）の中身。宛先と頼み元の窓を決め、要約の項目を確かめ、受付箱に
記録を残し、窓に 1 行を打ち込む。流れ（どの順に呼ぶか）は orders.py が持つ。

- 宛先: 「会社/役」か部署の名前か会社の名前。会社を省けば頼む側の会社。部署の名前（属性 company.name）が先に当たる。会社の名前
  だけなら、その会社の窓口（本社の、--desk で名付けた会話）に届ける。役で宛てたときは、その役の
  常設の部署（company.residency=resident）に届け、無ければ新しく立てる（4.10 の 1・2。都度の部署は頼みごとに立てる）。
- 頼み元の窓: 部署の属性 company.boss-session（頼んだ会話の id）、無ければ company.boss と company.boss-account から会話の一覧で
  引いた会話を、herdr のペインと結ぶ。結び方は、その会話を持つ部署の窓、ペインの会話の印（agent_session）と場所が合うもの、
  頼んだときのペイン（company.boss-pane）の順。ペインの会話の印は裏の会話の attach の窓では別の会話の id を指すことがある
  （2026-10-16 に herdr 0.9.3 で見た）ので、場所が合わない物は使わない。
- 要約の項目: 既定は「結論」「決め手」「残った疑問」「ブランチ」。会社の形（.claude/company.toml か設定の置き場の同じ書き方のファイル）の
  [[roles]] の deliver で役ごとに替えられる（読むのは role ノード）。項目は見出し（`## 結論`）か行の頭の札（`結論: …`）で書く。結論は 3 行以内、
  決め手は原典の URL を含むこと、ほかは空でないこと。ブランチは書かなければ部署のブランチを機械が足す。
- 納品の検査: 役の deliver_check（会社の形）のコマンドを、項目を確かめた後に部署の作業場のルートで走らせる（gate）。何を確かめるかは会社の
  側のスクリプトが持ち、ここは決め打ちしない。0 以外で終われば送らない。
- 受付箱: 頼み元の会社の共通の .git の中の company/inbox（INBOX）。commit されず、部署の worktree を消しても残り（4.10 の 1。
  部署ごとの .git/worktrees/<部署> は git worktree remove で一緒に消える）、勤め先のリポジトリの .gitignore も触らない。
  頼みと納品の本文を 1 件 1 ファイルで置き、log.jsonl に誰が誰に何を頼み何が返ったかを 1 行ずつ足す。
- Stop フック: 部署（company.role の在る場所）の会話で、受けた頼み（company.ask）の納品（company.delivered）が済んでいなければ、
  止まる前に納品のコマンドで返すよう差し戻す。同じ会話・同じ頼みで差し戻すのは STOP_LIMIT 回まで。裏の処理（裏の Bash・サブエージェント）が
  動いている間は差し戻さない（どう見るかは orders.in_flight）。納品した後の差し戻し（メインブランチに入れていない・終わりの印が無い）は
  orders.stop_after が持つ。
"""

import hashlib
import json
import os
import pathlib
import re
import shlex
import time
import uuid

import gitx

INBOX = ("company", "inbox")      # 共通の .git の下の受付箱
LOG = "log.jsonl"
DEFAULT_ITEMS = ("結論", "決め手", "残った疑問", "ブランチ")
BRANCH_ITEM = "ブランチ"                 # 書かなければ部署のブランチを機械が足す項目
# 項目の前の名前 → 今の名前（IT の定着語に替える前の名前。前の版の役の本文や会社の形の deliver に従って書いた要約も通す）
ITEM_ALIASES = {"枝": BRANCH_ITEM}
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
    """宛先を決める。companies は tree.build の結果、here_root は頼む側の会社のルート。current は (会社, 役の名前) → 今の役の名前
    （会社の形の former_names で、前の役の名前で宛てても、前の名前を属性に持つ部署でも、今の役に当たる）。
    返すのは {company, department（在れば tree の部署の 1 行）, role（役で宛てたとき）}。
    部署の名前（今の名前、無ければ前の名前）が先に当たる（会社を書けばその会社の中だけ）。会社を書かずに会社の名前（会社の形の在る会社だけ）
    だけで宛てれば、その会社の本社の名付いた会話（窓口）に届け、名付いていなければ、会社の形の desk に書いたほかの会社の窓口に
    届け（返しに via を添える）、それも無ければ止める。頼む側の会社の役の名前より先に当たる。役で宛てて task（--task の部署の名前）を
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
        where = "、".join(f"{c['name']}/{d['branch'] or '（ブランチ無し）'} {d['path']}" for c, d in named)
        if len({c["root"] for c, _ in named}) > 1:
            hint = "会社を添えて「会社/名前」で宛てる"
        else:   # 同じ会社の中の重なりは、宛て方では分けられない
            hint = ("同じ会社の中で重なっているので、宛て方では分けられない。--tree で場所を見て、要らない方の部署を片づけるか、"
                    "名前を替える（--reorg）")
        raise DeliverError(f"部署の名前「{name}」が 2 つ以上ある（{where}）。{hint}")
    if named:
        return {"company": named[0][0], "department": named[0][1], "role": named[0][1]["attrs"].get("role")}
    whole = [c for c in companies if company_name is None and c.get("info_source")
             and name in (c["name"], os.path.basename(os.path.normpath(c["root"])))]
    if len(whole) > 1:
        # 同じリポジトリの別の clone（作業用に clone しただけで部署を立てていない物）も、origin の会社の形を読むので同じ名前になる。
        # 部署（役の属性の在る worktree）を持つ clone を会社と見る（2026-10-17、claude-plugins-work1 が数えられて --ask claude-plugins が止まった）
        whole = [c for c in whole if any(d["attrs"].get("role") for d in c["departments"])] or whole
    if len(whole) > 1:
        raise DeliverError(f"会社の名前「{name}」が 2 つ以上ある（{'、'.join(c['root'] for c in whole)}）。部署の名前か「会社/役」で宛てる")
    if whole:
        # 会社の名前だけで宛てたら、その会社の窓口（本社の、--desk で名付けた会話）に届ける（tree.contacts の窓口と同じ物）。部署で
        # ない会話がほかの会社に頼むとき、宛先の役の名前を会社ごとに知らなくてよいように
        head = next((d for d in whole[0]["departments"] if d.get("head_office") and d["attrs"].get("name")), None)
        if head is None and whole[0].get("desk_of"):
            # 本社に窓口が無く、会社の形の desk にほかの会社の窓口が書いてあれば、そこへ届ける（--tree の窓口と同じ物。claude-plugins の
            # 窓口は my_notes の段取り）。書いた先は部署の名前で当たったときだけ使う（役の道に落として、ほかの会社に部署を立てない）
            far, far_name = parse_target(whole[0]["desk_of"])
            hits = [(c, d) for c in companies if c["name"] == far for d in c["departments"]
                    if d["attrs"].get("name") == far_name or far_name in gitx.former_names(d["attrs"])]
            if len({d["path"] for _, d in hits}) != 1:
                raise DeliverError(f"会社「{name}」の窓口は会社の形の desk で {whole[0]['desk_of']} と書いてあるが、その窓口が"
                                   + ("見つからない（その会社が herdr に開いていないか、その名前の窓口が無い）" if not hits else "2 つ以上ある"))
            c, d = hits[0]
            return {"company": c, "department": d, "role": d["attrs"].get("role"), "via": f"{name} の窓口（会社の形の desk）"}
        if head is None:
            raise DeliverError(f"会社「{name}」の窓口が名付けられていない（その会社の本社で持ち主と話す会話が --desk を打つと名付く。"
                               "ほかの会社の窓口が兼ねるなら、会社の形の頭に desk = \"<会社>/<名前>\" と書く）。"
                               "--tree の「受ける仕事」の宛て方で、仕事ごとの部署に宛てる")
        return {"company": whole[0], "department": head, "role": head["attrs"].get("role")}
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
    duty = next((s for s in company.get("skills", []) if s.get("name") == name and s.get("standing") is False), None)
    if duty and duty.get("role"):
        # 頼まれたときだけ立てる受け持ち（standing = false）で、その名前の部署が今は無い: その名前の都度の部署を立てる（orders.ask が
        # 部署の名前とブランチを決める）。同じ受け持ちで立つ部署は名前で 1 つに決まるので、立っている間の次の頼みはその部署の順番待ちに積む
        return {"company": company, "department": None, "role": current(company, duty["role"]), "on_demand": duty["name"]}
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
    """受付箱の台帳の行の並び。読めない行（書きかけの最後の行など）は飛ばす（待ち受けが読む間に書かれることがある）。"""
    out = []
    try:
        with open(os.path.join(inbox, LOG), encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                try:
                    got = json.loads(line)
                except ValueError:
                    continue
                if isinstance(got, dict):
                    out.append(got)
    except FileNotFoundError:
        return []
    return out


def closed_ids(records):
    """台帳の行から、閉じた頼みの受付の集まり（その受付への納品〔--for の返しと failed を除く〕・頼み元の待ち受けへの納品の知らせ・
    回して閉じた〔forwarded〕・取り下げた〔withdrawn〕のどれかが在る物）。"""
    closed = set()
    for r in records:
        kind = r.get("kind")
        if kind == "deliver" and r.get("ask") and r.get("status") != "failed" and not r.get("for"):
            closed.add(r["ask"])
        elif kind == "deliver" and isinstance(r.get("to"), str) and r.get("id"):
            closed.add(r["id"])
        elif kind in ("forwarded", "withdrawn") and r.get("id"):
            closed.add(r["id"])
    return closed


def open_asks(records, held=()):
    """台帳の行（会社をまたいで足し合わせた物）から、まだ閉じていない頼みの並び（積んだ順）。頼みは kind ask の行（status が sent か
    queued。同じ受付が回し直されたら後の行）。閉じたとみるのは、その受付への納品（kind deliver の ask か、頼み元の待ち受けへの
    納品の知らせの id。--for の返しと、知らせられずに failed の物を除く）・回したことで閉じた（forwarded）・取り下げた（withdrawn）とき。
    held は部署が今受けていて納品していない受付の並び（部署の属性 company.ask）で、届いたかを確かめられずに status が failed の
    頼みも、ここに在れば数える。"""
    asks, closed = {}, set()
    for r in records:
        kind = r.get("kind")
        if kind == "ask" and (r.get("status") in ("sent", "queued") or r.get("id") in held) and r.get("id"):
            asks.pop(r["id"], None)
            asks[r["id"]] = r
        elif kind == "deliver" and r.get("ask") and r.get("status") != "failed" and not r.get("for"):
            closed.add(r["ask"])
        elif kind == "deliver" and isinstance(r.get("to"), str) and r.get("id"):
            closed.add(r["id"])   # 頼み元の待ち受けへの納品の知らせ（wake.notice。id が頼みの受付）
        elif kind in ("forwarded", "withdrawn") and r.get("id"):
            closed.add(r["id"])
    return [r for i, r in asks.items() if i not in closed]


# 頼みの本文の頭によく置く決まり文句（題にしない）
BOILERPLATE = ("前提が違う", "段取りからの添え書き", "---")
# 誰からの何かだけを言う頭の文（「社長室からの頼みです（穴の直し）」「知らせです（返事は要りません）」「段取りから社長室へ」など。題にしない）
COVER_RE = re.compile(r"^(?:\S{0,12}?(?:頼み|差し戻し|返し|問い|知らせ)です(?:[（(].*[)）])?|[^\x00-\x7f\s]{1,8}から[^\x00-\x7f\s]{1,8}へ)$")
# 頼みの書き方の項目名を行の頭に置いた形（「困っていること: …」「頼み: …」。項目名は外して題にする）
LABEL_RE = re.compile(r"^(?:困りごと|困っていること|頼み|目的|制約)(?:[（(][^）)]*[)）])?\s*[:：]\s*")
# 題の頭の箇条の印（ITEM_RE と同じ印。ただし - * + は後ろに空白があるときだけ、番号は後ろに数字が続かないときだけ。「--todo の…」の - や
# 「0.66.2 の…」の 0. を印に取らない）
TITLE_ITEM_RE = re.compile(r"^(?:[-*+]\s+|(?:[・•]|\d+[.)．）](?!\d)|[(（]\d+[)）]|[①-⑳])\s*)")
# 持ち主の言葉の「」の閉じのすぐ後ろに来てよい字（無いか、次の言葉の「・括弧の補足・読点・句点。「「困りごと」が題になる」のように
# ほかの字が続けば「」は言葉の一部なので外さない）
QUOTE_END = ("", "「", "（", "(", "、", "。", ",")
# 持ち主の言葉のセクション（「## 持ち主の言葉」）か、見出しにしない書き方の行（「持ち主の言葉（そのまま）:」。同じ行に言葉が続くこともある）
OWNER_WORDS_HEAD = re.compile(r"^(?:#+\s*持ち主の言葉.*|持ち主の言葉(?:[（(][^）)]*[)）])?\s*[:：]\s*(.*))$")


def sentences(line):
    """行を文に分ける（括弧〔（）「」『』〕の外の「。」で切り、「。」は外す。空の文は捨てる）。"""
    out, depth, start = [], 0, 0
    for i, ch in enumerate(line):
        if ch in "（「『(":
            depth += 1
        elif ch in "）」』)" and depth:
            depth -= 1
        elif ch == "。" and not depth:
            out.append(line[start:i])
            start = i + 1
    out.append(line[start:])
    return [x.strip() for x in out if x.strip()]


def _lines(path):
    try:
        return [x.strip() for x in pathlib.Path(path).read_text(encoding="utf-8").splitlines()]
    except (OSError, UnicodeDecodeError, TypeError):
        return None


def ask_title(path, width=60):
    """頼みの本文のファイルの題。回した側の添え書き（「…が回した:」と区切りの ---）の後の、見出し（# の行）・決まり文句の行と、誰からの何か
    だけを言う文を飛ばした、最初の文（文の頭の項目名「困っていること:」などは外す）。見出しは「困りごと」「頼み」のように中身を言わないので
    題にしない（飛ばした後に何も残らなければ、最初の行の頭の # を外す）。読めなければ None。"""
    lines = _lines(path)
    if lines is None:
        return None
    if "---" in lines and any("回した" in x for x in lines[:lines.index("---")]):
        lines = lines[lines.index("---") + 1:]
    lines = [x for x in lines if x and not x.startswith(BOILERPLATE)]
    said = (y for line in lines if not line.startswith("#") for x in sentences(TITLE_ITEM_RE.sub("", line, count=1))
            if not COVER_RE.match(x) for y in [LABEL_RE.sub("", x, count=1)] if y)
    head = next(said, None) or next((x.lstrip("# ") for x in lines), None)
    return head if head is None or len(head) <= width else head[:width] + "…"


def task_title(path, width=60):
    """頼みの木（--todo）と --html に出す題。本文に持ち主の言葉（「## 持ち主の言葉」のセクションか「持ち主の言葉（そのまま）:」の行）が在れば、
    その最初の言葉（箇条の印を外す。頭が「で、閉じの後ろに文が続かなければ、その「」の中）。無ければ ask_title。窓口が回す頼みの頭の行は「持ち主の頼みです（社長室から）。」のような定型で、
    題にならないため。読めなければ None。"""
    lines = _lines(path)
    if lines is None:
        return None
    at = next(((i, m) for i, x in enumerate(lines) if (m := OWNER_WORDS_HEAD.match(x))), None)
    head = None
    if at is not None:
        i, m = at
        head = (m.group(1) or "").strip() or next((x for x in lines[i + 1:] if x and not x.startswith("#")), None)
    if not head:
        return ask_title(path, width)
    head = TITLE_ITEM_RE.sub("", head, count=1).strip()
    if head.startswith("「"):
        depth = 0
        for i, ch in enumerate(head):
            depth += {"「": 1, "」": -1}.get(ch, 0)
            if not depth:
                if head[i + 1:i + 2] in QUOTE_END:
                    head = head[1:i]
                break
        else:
            head = head[1:]   # 閉じの無い「
    return head if len(head) <= width else head[:width] + "…"


# ---- 残った疑問の担当者（役の holders。my_notes の tools/deliver_check.py の holder_problems から移した）----

OPEN = "残った疑問"
# 担当者の札（前の名前「持ち手」も読む。my_notes の tools/deliver_check.py や前の版の役の本文が書く）
HOLDER_WORDS = ("担当者", "持ち手")
HOLDER_RE = re.compile(rf"(?:{'|'.join(HOLDER_WORDS)})[:：]\s*([^。、\n]+)")
# 箇条の頭（- * ・ • + と、1. 1) 1． 1） (1) ① の番号）。字下げした子の項目は親に続ける
ITEM_RE = re.compile(r"^\s{0,1}(?:[-*・•+]|\d+[.)．）]|[(（]\d+[)）]|[①-⑳])\s*")
NONE_RE = re.compile(r"(?:特に)?(?:無し|なし|無い|ない|ありません)(?:です|でした)?(?:$|[。．.、，,（()）「」『』【】：:；;！!→—/\s])")
# 問いの印を探す前に消す URL（\S+ だと URL のすぐ後ろの全角の「？」まで消える）
ASCII_URL = re.compile(r"https?://[\x21-\x7e]+")
OWNER_WORDS = ("持ち主", "所有者")
OWNER_OK = ("持ち主（価値で選ぶ）", "持ち主（確認してからやる）")


def open_items(text):
    """残った疑問を 1 件ずつに割る。箇条書きが無ければ全体で 1 件。箇条でない段落（箇条の前の前置きと、箇条の間・後ろの、空行の後の
    字下げの無い行。空行まで 1 段落）は、最後の行が「：」か「:」で終わり、ほかの行が文の終わり（。？?）で終わらない物（「次の 2 件：」
    など。折り返した行も 1 段落）で、すぐ次が箇条の物だけを箇条を導く札として件に数えず、ほかは 1 件に数える（前置きや後書きに問いを書いて担当者を省くと
    通っていた。my_notes の受付 3c9a61）。"""
    blocks, gap = [], True   # 箇条の 1 件は字、段落は行の並び
    for line in (text or "").splitlines():
        if not line.strip():
            gap = True
            continue
        if ITEM_RE.match(line):
            blocks.append(line.strip())
        elif blocks and not (gap and (isinstance(blocks[-1], list) or not line[:1].isspace())):
            if isinstance(blocks[-1], list):
                blocks[-1].append(line.strip())
            else:
                blocks[-1] += " " + line.strip()
        else:
            blocks.append([line.strip()])
        gap = False
    if not any(isinstance(b, str) for b in blocks):
        return [" ".join(" ".join(b) for b in blocks)] if blocks else []
    return [b if isinstance(b, str) else " ".join(b) for i, b in enumerate(blocks)
            if isinstance(b, str) or not (_intro(b) and i + 1 < len(blocks) and isinstance(blocks[i + 1], str))]


def _intro(lines):
    """箇条でない段落（行の並び）が、箇条を導くだけの札か（最後の行が「：」で終わり、ほかの行が文の終わりで終わらない）。"""
    return lines[-1].endswith((":", "：")) and not any(x.endswith(("。", "？", "?")) for x in lines[:-1])


def _none(text):
    """疑問が無いと書いた物か（「なし」「- なし」「なし（全部閉じた）」「無い。<理由>」「ありません」など）。無しの語の後が句読点・括弧・
    空白・終わりのときだけで、「無い場合はどうするか」のように語が文の頭に来ただけの物と、問いの印（？。URL の中の ? は除く）の在る物は
    数えない（3c9a61）。"""
    body = ITEM_RE.sub("", text.strip(), count=1).strip()
    return bool(NONE_RE.match(body)) and not any(w in body for w in HOLDER_WORDS) and not any(q in ASCII_URL.sub("", body) for q in "？?")


def holder_problems(text, relays=()):
    """残った疑問（text）の 1 件ごとの担当者の違反の並び。担当者が無い・持ち主（か relays の名前。持ち主への中継の会話）を担当者にして、
    価値で選ぶ問いか確認してからやる事と示していない、の 2 つ。「無し」だけなら違反なし。"""
    text = (text or "").strip()
    items = open_items(text)
    if not text or len(items) == 1 and _none(items[0]):
        return []
    out = []
    for item in items:
        head = item[:40]
        found = HOLDER_RE.search(item)
        if not found:
            out.append(f"担当者が無い: {head}")
            continue
        holder = re.sub(r"\s+", "", found.group(1)).replace("(", "（").replace(")", "）")
        if holder.startswith(OWNER_WORDS + tuple(relays)) and not holder.startswith(OWNER_OK):
            out.append(f"担当者が持ち主（か持ち主への中継）で、「持ち主（価値で選ぶ）」か「持ち主（確認してからやる）」と示していない: {head}")
    return out


ASK_ID_RE = re.compile(r"\b\d{8}-\d{6}-[0-9a-f]{6}\b")


def open_holders(text):
    """残った疑問（text）の 1 件ごとの担当者の並び [{"holder": 担当者の字, "ask": 担当者の字の中の受付番号か None}]（納品の台帳の行の
    holders のフィールド。担当者の受付を、台帳の射影が頼みの続きに結ぶ。docs/ledger.md）。担当者の無い件と「無し」は数えない。"""
    text = (text or "").strip()
    out = []
    for item in open_items(text) if text else []:
        found = HOLDER_RE.search(item)
        if found and not _none(item):
            holder = found.group(1).strip()
            got = ASK_ID_RE.search(holder)
            out.append({"holder": holder, "ask": got.group(0) if got else None})
    return out


def unsure_problems(items):
    """残った疑問の外の項目に「要確認」が在れば、その違反の並び（残った疑問に移して担当者を付ける。my_notes の決まりを移した）。"""
    return [f"「{name}」に「要確認」がある。残った疑問に移して担当者を付ける" for name, body in items.items()
            if name != OPEN and "要確認" in (body or "")]


# ---- 要約の項目 ----

def required_items(role):
    """その役の必須の項目。role は会社の形の役の項目（role ノードが [[roles]] から読んだ物。無ければ None）で、deliver が有れば
    それを、無ければ既定の項目を使う。"""
    return [ITEM_ALIASES.get(x, x) for x in (role or {}).get("deliver") or DEFAULT_ITEMS]


def _label(names):
    alt = "|".join(re.escape(n) for n in sorted(names, key=len, reverse=True))
    return (re.compile(rf"^\s*#{{1,6}}\s*(?:\*\*)?({alt})(?:\*\*)?\s*[:：]?\s*$"),
            re.compile(rf"^\s*(?:[-*]\s+)?(?:\*\*)?({alt})(?:\*\*)?\s*[:：]\s*(.*)$"))


def parse(text, names):
    """要約の本文から {項目: 本文}。項目は見出し（`## 結論`）か行の頭の札（`結論: …`）で始まり、次の項目か見出しまで続く。
    項目の前の名前（ITEM_ALIASES）で書いた物は今の名前で返す。"""
    names = set(names) | {old for old, new in ITEM_ALIASES.items() if new in names}
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
    merged = {}
    for k, v in out.items():
        merged.setdefault(ITEM_ALIASES.get(k, k), []).extend(v)
    return {k: "\n".join(v).strip() for k, v in merged.items()}


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
    """納品の検査。command（シェルの字）を place（部署の作業場のルート）で走らせ、payload（role・ask・branch・place・items・summary・version）を
    JSON で標準入力に渡す。(終了の値, 標準出力と標準エラーの終わりの GATE_TAIL 行)。0 なら通った、0 以外なら送らない。
    runner は subprocess.run（このノードは subprocess を持たないので、流れの orders.py が渡す）。"""
    p = runner(command, shell=True, cwd=place, input=json.dumps(payload, ensure_ascii=False), capture_output=True,
               text=True, encoding="utf-8", errors="replace")
    both = (p.stdout or "") + (p.stderr or "")
    return p.returncode, "\n".join(both.rstrip().splitlines()[-GATE_TAIL:])


def absent_files(command, place):
    """納品の検査のコマンドの字のうち、place からの相対のファイルの名に見えて（/ を含むか拡張子を持つ）place に無い物の並び。会社の形は
    origin のメインブランチから読むが、検査は部署の作業場で走るので、台本の入る前のメインブランチから切ったブランチでは台本が無い（2026-10-17 に my_notes の
    調べものの納品が tools/deliver_check.py が無くて止まった）。"""
    try:
        words = shlex.split(command)
    except ValueError:
        return []
    return [w for w in words if not w.startswith("-") and not os.path.isabs(w) and ("/" in w or os.path.splitext(w)[1])
            and not os.path.exists(os.path.join(place, w))]


def summary_text(items, required):
    """受付箱に置く要約の本文（項目の順は必須の並び、その後に書かれた順）。"""
    order = list(required) + [k for k in items if k not in required]
    return "\n\n".join(f"## {k}\n{items[k]}" for k in order if items.get(k))


def flat(text):
    return " / ".join(x.strip() for x in text.splitlines() if x.strip())


# ---- 窓に打ち込む 1 行 ----

def deliver_command(run):
    """run は dispatch.py を起動する字（引用符付きの Python と dispatch.py のパス。orders.RUN）。"""
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
    return f"納品です（受付 {ask_id or '-'}、{sender}・ブランチ {branch or '-'} から）: {body} （全文: {path}）"


# 送った 1 行が入力フィールドに残っていないかを見る回数（1 回ごとに pause）
SUBMIT_LOOKS = 3


def send(pane, line, h, pause=None):
    """窓の会話に 1 行を送る（herdr agent prompt。終わりは待たない）。書く口。(sent か failed, 訳)。
    pause を渡すと、送った後に入力フィールド（行の頭が ❯ の行）にその文が残っていないかを見て、残っていれば Enter を 1 回足す。
    Windows で、attach で戻した直後の会話に送った文が、入力フィールドに入ったまま送信されなかった（まっさらな環境での 7 回目の試しの 1）。
    入力フィールドが空のときの Enter は何もしないので、見誤っても害は無い。"""
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
                return "sent", "入力フィールドに残っていたので Enter を足した"
    return "sent", None


# 送った 1 行で会話が動き出したかを見る回数（1 回ごとに pause）と、届いていなければ打ち直す回数
CONFIRM_LOOKS = 8
SEND_TRIES = 3


def _rule(x):
    """会話の画面の横の罫線の行か（入力フィールドの上と下に引かれる「────」。上の罫線には部署の名前が入ることがある）。"""
    return x.count("─") >= 10


def input_box(screen):
    """会話の画面の入力フィールドの字（下から 2 本の罫線の間の行をつないだ物）。罫線が 2 本無ければ None（字を受けられる形でない）。"""
    lines = (screen or "").splitlines()
    rules = [i for i, x in enumerate(lines) if _rule(x)]
    if len(rules) < 2:
        return None
    return " ".join(" ".join(lines[rules[-2] + 1:rules[-1]]).split())


_ESC = re.compile(r"\x1b\[([0-9;:?<=>]*)[ -/]*([@-~])|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)|\x1b[()][0-9A-Za-z]|[\x0e\x0f]")


def _solid(screen):
    """ANSI の画面の字を、行ごとに (制御の字を除いた字, そのうち薄字〔SGR 2〕でない字) の組にする。薄字は Claude Code が入力フィールドに
    出す次の文の候補と、空の入力フィールドの例の字（打てば消える。https://code.claude.com/docs/en/interactive-mode#prompt-suggestions ）。
    人が打った字と貼った字（[Pasted text …]）は薄字でない（2026-10-18 に claude を端末で起動して見た）。"""
    out, faint = [], False
    for line in (screen or "").splitlines():
        plain, solid, at = [], [], 0
        for m in _ESC.finditer(line):
            piece = line[at:m.start()]
            plain.append(piece)
            if not faint:
                solid.append(piece)
            at = m.end()
            if m.group(2) == "m":
                codes = (m.group(1) or "0").split(";")
                while codes:
                    code = codes.pop(0)
                    if code in ("38", "48", "58"):   # 色の指定の続き（5;n か 2;r;g;b）は薄字の 2 と読まない
                        del codes[:2 if codes[:1] == ["5"] else 4]
                    elif code in ("", "0", "22"):
                        faint = False
                    elif code == "2":
                        faint = True
        plain.append(line[at:])
        if not faint:
            solid.append(line[at:])
        out.append(("".join(plain), "".join(solid)))
    return out


def typed(screen):
    """会話の画面（herdr.read の ansi の字）の入力フィールドに、人が打った字（薄字の候補と頭の ❯ を除く）。入力フィールドが空なら ""、
    罫線が 2 本無ければ None（字を受けられる形でない）。打ちかけの字を消さないための見分け（/clear・/exit・1 行を打つ前に見る）。
    2026-10-18 に my_notes の段取りで、入力フィールドの候補「消していいよ」を打ちかけと見て、区切りの /clear と起動し直しを 1 時間打たなかった。"""
    rows = _solid(screen)
    rules = [i for i, (x, _) in enumerate(rows) if _rule(x)]
    if len(rules) < 2:
        return None
    return " ".join(" ".join(x for _, x in rows[rules[-2] + 1:rules[-1]]).split()).lstrip("❯").strip()


def ready(screen):
    """会話の画面が字を受けられる形か（入力フィールドが出ている）。"""
    return input_box(screen) is not None


def above_box(screen):
    """入力フィールドより上の画面の字（会話に届いた字が載る所）。"""
    lines = (screen or "").splitlines()
    rules = [i for i, x in enumerate(lines) if _rule(x)]
    return " ".join(" ".join(lines[:rules[-2]] if len(rules) >= 2 else lines).split())


def send_confirmed(pane, line, h, pause, busy):
    """窓の会話に 1 行を送り、会話が動き出した（busy() が真）のを見てから返す。書く口。(sent か failed, 訳)。
    Windows で、attach で戻した直後の会話に送った 1 行が、届かないか入力フィールドに残った（まっさらな環境での 9 回目の試しの 1）。
    送る前に入力フィールドが出るのを待ち、送った後は、入力フィールドに残っていれば Enter を足し、入力フィールドにも画面にも見えず動き出してもいなければ
    打ち直す（SEND_TRIES 回まで）。画面に送った字が見えていれば（入力フィールドでない所に）、届いたと見て打ち直さない（二重に送らない）。
    送る前から動いている会話は、打った字をターンの後の待ちの列に回すので、動き出しでは確かめられない。入力フィールドに残れば Enter を足し、
    入力フィールドの上（待ちの列か、ターンの途中で取り込まれた会話の中）に載るか、入力フィールドから出たのを見て届いたとする。見えなくても打ち直さない
    （打った字は待ちの列に入るかターンの途中で取り込まれる。打ち直すと同じ頼みが何度も届いた）。"""
    head = " ".join(line.split())[:20]
    was_busy = busy()
    seen = 0   # 送る前に入力フィールドより上に見えていた数（前に送った同じ字が画面に残っていても、届いたと見誤らない）
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
                    entered, detail = True, "入力フィールドに残っていたので Enter を足した"
            elif above_box(screen).count(head) > seen:
                return "sent", detail   # 入力フィールドから出て、入力フィールドより上に新しく載った（会話に届いた）
            elif was_busy and entered and ready(screen):
                return "sent", detail   # 入力フィールドに入った字が、Enter で入力フィールドから出た（待ちの列に回った）
        if was_busy:
            return "sent", "動いている会話に 1 回打った（待ちの列に載ったのを画面で見られなかったが、二重に送らないよう打ち直さない）"
        detail = f"届いたかを確かめられず打ち直した（{attempt + 1} 回目）"
    return "failed", f"{SEND_TRIES} 回打ったが、会話が動き出さない（部署の窓を見て、入力フィールドに残っていれば Enter を押す）"


CLEAR = "/clear"


def clear_talk(pane, h, pause, cleared):
    """窓の会話に /clear を打ち、会話が空になった（cleared() が真。会話の一覧の id が変わった）のを見てから返す。書く口。
    (cleared・unconfirmed・failed, 訳)。入力フィールドに /clear が残っていれば Enter を 1 回足す（残ったまま頼みを打つと、頼みの頭に
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


# 前の会話を終えるコマンドと、シェルに戻るのを見る回数（1 回ごとに pause）
EXIT = "/exit"
EXIT_LOOKS = 20


def exit_talk(pane, h, pause, looks=EXIT_LOOKS):
    """窓の前の会話（持ち主の前で動く窓口など）に /exit を打ち、シェルが前に戻ったら True。書く口。"""
    try:
        h.prompt(pane, EXIT, False)
    except h.HerdrError:
        return False
    for _ in range(looks):
        pause()
        try:
            if h.shell_in_front(pane):
                return True
        except h.HerdrError:
            return False
    return False


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
    # 本文の場所も添える。頼みを渡した字が会話に届かなくても、この差し戻しで本文へたどれる（my_notes の受付 4bae53 は、起動し直した
    # 会話が受付番号だけを見て、本文を読まずに「受けている頼みは無い」と納品した）
    file = os.path.join(attrs.get("boss-inbox") or "", f"{ask}-ask.md")
    body = f"本文は {file}（まだ読んでいなければ、先に読んで進める）。" if attrs.get("boss-inbox") and os.path.isfile(file) else ""
    return (f"頼み（受付 {ask}）をまだ納品していない。{body}止まる前に、要約をファイルに書いて {deliver_command(run)} で"
            f"{boss} へ返す（足りない項目はコマンドが教える）。返せない訳があれば、それを要約の「残った疑問」に書いて返す"
            f"（この差し戻しは {STOP_LIMIT} 回まで。{count + 1} 回目）。裏の処理（run_in_background の Bash や Agent）の終わりを待つだけなら、"
            "ターンを終えてよい（動いている間はこの差し戻しは出ず、終われば知らせで会話が起きる）。")


def stop_count_path(tmp_dir, session_id, ask):
    safe = re.sub(r"[^0-9A-Za-z_.-]", "_", f"{session_id}-{ask}")
    return os.path.join(tmp_dir, "works-dispatch-stop", safe)
