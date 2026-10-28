#!/usr/bin/env python3
"""tree ノード: herdr に開いている会社（リポジトリ）ごとに、会社の情報と部署（git worktree）の様子を組み立てる。外には書かない。

会社の形の設計（docs/specs/2026-10-16-company-shape-design.md）の 4.1・4.2・4.4 に当たる。
- 会社 = git のリポジトリ 1 つ。本社は元の clone、部署は元の clone の git worktree（ブランチ 1 本）。
- 問い合わせられる会社 = herdr に開いている作業場が指すリポジトリ。herdr がリポジトリを持たない作業場は、そのペインの場所から
  git の共通の .git を問うて決める（入口が渡す common_of）。同じリポジトリの別の clone は、別の会社として並べる。
- 部署の属性（役・アカウント・会話の名前と id・頼み元〔納品を返す先。属性 company.boss〕）は、部署ごとの git の設定 company.<名前>（入口が読んで渡す）。
- 部署の会話とその状態は、全アカウントの claude agents --json --all を合わせて見る（一覧はアカウントごとに分かれる。
  会社の形の設計 9.1）。会話は、属性の company.session（会話の id）で結び、無ければ会話の作業フォルダの場所で結ぶ。
  状態は裏の会話の state（作業中・止まっている・終わった など）、手前の会話（kind が interactive）は status から取る。
- 窓は、部署の作業場か部署の場所のペイン（attach の画面など）が herdr に在るか。
- 会社の情報（名前と受ける仕事）は、リポジトリの中の INFO_FILE を先に読み、無ければ設定の置き場の companies/ の中の、その
  リポジトリの分を読む（書き方は同じ。Claude Code の settings.json と settings.local.json の分け方と同じ考え）。リポジトリの中の
  物は、origin の既定のブランチ（origin/HEAD が指す手元の ref）に commit された物を先に読み、無ければ元の clone の作業ツリーの物を読む
  （read_info）。元の clone の作業ツリーはほかの会話が古いブランチで使っていることがあり、部署のブランチは部署が書き換えうるので、どちらにも
  頼らない。会社の形を読む所（--tree・--task・--ask・--deliver・--land・役を足すフック）は全部 read_info を通る。origin は在るのに
  origin/HEAD が無い clone では既定のブランチを決められないので、作業ツリーから読み、直し方（HEAD_FIX）を注記に出す（head_note）。
  書き方は TOML で、フィールドの名前は A2A の Agent Card（name・description・skills〔id・name・description〕）に合わせ、受ける役の
  role と、その受け持ちの部署を起動するときの model・effort・account（役の値より先に効く）と、起動方法の start（start ノード）だけをここで
  足した。知らないフィールドと外したフィールドは、読み飛ばす前に注記（notes）に出す（一覧は known_keys。read_info）。

入口の dispatch.py --tree が、herdr・git・claude から読んだ物を渡して build を呼び、lines で人の読む形にする。
"""

import os
import time
import tomllib
import urllib.parse

import filex
import gitx
import known_keys
from nodes import role, start
from ports import term

INFO_FILE = (".claude", "company.toml")  # リポジトリの中の会社の情報（commit する側）
SETTINGS_DIR = "companies"  # 設定の置き場の下の、リポジトリの外の会社の情報（commit しない側）

# 部署の状態（会話の state、無ければ status から）と、その字
STATES = {"working": "作業中", "blocked": "止まっている", "done": "終わった", "failed": "失敗した", "stopped": "止めた",
          "idle": "待機中", "no_session": "会話なし"}
STATUS = {"busy": "working", "waiting": "blocked", "idle": "idle"}  # 手前の会話の status → 状態


def settings_info_path(settings_dir, root):
    """設定の置き場の中の、そのリポジトリ（元の clone のルート）の会社の情報のファイル。名前はルートの実際のパスを字の符号にしたもの
    （Windows でもファイル名に使えない字が残らない）。"""
    return os.path.join(settings_dir, SETTINGS_DIR, urllib.parse.quote(os.path.realpath(root), safe="") + ".toml")


def _skills(raw, where, problems):
    out = []
    if not isinstance(raw, list):
        problems.append(f"{where}: skills が表の並びで無い")
        return out
    for i, s in enumerate(raw):
        if not isinstance(s, dict) or not isinstance(s.get("name"), str):
            problems.append(f"{where}: skills[{i}] に name が無い")
            continue
        got = {k: s[k] if isinstance(s.get(k), str) else None for k in ("id", "name", "description", "role")}
        # その部署を起動するときの --model と --effort。役の値より先に効く（role.launch_flags）。形の違う値はそのフィールドだけ外し、役の値で起動する
        if "model" in s and not (isinstance(s["model"], str) and s["model"] and s["model"] != role.INHERIT):
            problems.append(f"{where}: skills[{i}]（{s['name']}）の model は空でないモデルの名前（inherit は作っていない。頼み元の会話の"
                            f"今のモデルを外から読む口が無い）。外して、役の model で起動する")
        elif "model" in s:
            got["model"] = s["model"]
        if "effort" in s and s["effort"] not in role.EFFORTS + (role.INHERIT,):
            problems.append(f"{where}: skills[{i}]（{s['name']}）の effort は {'・'.join(role.EFFORTS + (role.INHERIT,))} のどれか。"
                            f"外して、役の effort で起動する")
        elif "effort" in s:
            got["effort"] = s["effort"]
        # その部署を新しく立てるときに先に使うアカウント。役の値より先に効く（role.launch_account）。形が違えば外し、役の値で選ぶ
        if "account" in s and not (isinstance(s["account"], str) and s["account"].strip()):
            problems.append(f"{where}: skills[{i}]（{s['name']}）の account は空でないアカウントの名前。外して、役の account で選ぶ")
        elif "account" in s:
            got["account"] = s["account"].strip()
        # その部署を起動するときの --settings に、役の [roles.settings] の上から重ねる Claude Code の設定（role.settings_for）。表でなければ外す
        if "settings" in s and not isinstance(s["settings"], dict):
            problems.append(f"{where}: skills[{i}]（{s['name']}）の settings は表。外して、役の settings だけで起動する")
        elif s.get("settings"):
            got["settings"] = s["settings"]
        # 仕事が終わらないままターンを終えた間に待ち受けが送る keepalive。役の [roles.keepalive] より先に効く（role.keepalive_for）。形が違えば外す
        got["keepalive"] = role.parse_keepalive(s.get("keepalive"), f"{where}: skills[{i}]（{s['name']}）", problems)
        # 起動方法（周期かコマンド・返す先。start ノード）。形が違えば外し、その受け持ちは起動しない
        got["start"] = start.parse(s.get("start"), f"{where}: skills[{i}]（{s['name']}）", problems)
        # on_demand = true（オンデマンド）: 永続の部署を置かず、頼まれたときだけその受け持ちの名前のエフェメラルの部署を立てる（--ask が
        # 立て、--done で畳む）
        flag = s.get("on_demand", False)
        if not isinstance(flag, bool):
            problems.append(f"{where}: skills[{i}]（{s['name']}）の on_demand は true か false。外して永続で扱う")
            flag = False
        got["on_demand"] = flag
        # per_ask = true（頼みごとの部署）: オンデマンドの受け持ちへの頼みを、頼みごとに別の一度きりの部署（「<受け持ち>：<受付番号の
        # 終わり 6 字>」）で受け、並べて進める（orders.ask が名前を決め、role.on_demand_of が名前から受け持ちを引く）。on_demand = true と併せて書く
        per_ask = s.get("per_ask", False)
        if not isinstance(per_ask, bool):
            problems.append(f"{where}: skills[{i}]（{s['name']}）の per_ask は true か false。外して、受け持ちの名前の部署 1 つで受ける")
            per_ask = False
        elif per_ask and not flag:
            problems.append(f"{where}: skills[{i}]（{s['name']}）の per_ask は on_demand = true と併せて書く。外して、受け持ちの名前の部署 1 つで受ける")
            per_ask = False
        got["per_ask"] = per_ask
        out.append({"model": None, "effort": None, "settings": None, "account": None, **got})
    return out


def committed_info(root, g=gitx):
    """origin の既定のブランチに commit された INFO_FILE。(場所の札 例 origin/main:.claude/company.toml, 中身) か None。
    手元の ref を読むだけで fetch しない（毎回の会話の始まりに走るフックも通るので、外へ問い合わせない）。"""
    ref = g.origin_head(root)
    rel = "/".join(INFO_FILE)
    text = g.file_at(root, ref, rel) if ref else None
    return (f"{ref}:{rel}", text) if text is not None else None


HEAD_FIX = "remote set-head origin --auto"  # origin/HEAD を origin の今の既定のブランチに向ける git のコマンド（git -C <ルート> の後ろ）


def head_note(root, g=gitx):
    """origin は在るのに origin/HEAD が無い clone なら、会社の形の読み方が落ちる訳と直し方の注記。それ以外（git でない・origin が
    無い・origin/HEAD が在る）は None。手元の ref を読むだけ。"""
    if not g.origin_url(root) or g.origin_head(root):
        return None
    return (f"{root} に origin/HEAD（origin の既定のブランチを指す手元の印）が無いので、origin の既定のブランチに commit された会社の形を読めず、"
            f"元の clone の作業ツリー（古いブランチなら古い形）か設定の置き場の物で読む。直すには: git -C {root} {HEAD_FIX}")


def _blank(source=None, path=None, notes=()):
    return {"source": source, "path": path, "text": None, "name": None, "description": None, "desk": None, "skills": [],
            "problems": [], "notes": list(notes), "keys": []}


def company_name(root, info):
    """会社の名前: 会社の形の name、無ければ元の clone のフォルダの名前（宛先の「会社/名前」の会社。--ask と待ち受けが同じ物を使う）。"""
    return info.get("name") or os.path.basename(os.path.normpath(root))


def read_info(root, settings_dir, g=gitx, committed=None):
    """その会社の情報。{source: origin|repo|settings|None, path, text, name, description, skills, problems, notes}。会社の形を読む場所を
    決めるのはこの 1 か所で、読む順は origin の既定のブランチに commit された物（committed。path は ref:パス の札）、元の clone の作業
    ツリーの物、設定の置き場の物。text は読んだ中身（role.load・land.read_rules に渡す。同じ物を読み直さない）。
    読めない・形の違うファイルは problems に書き、そこで止める（次の置き場へ落とさない。書いた物が効いていないことを隠さない）。
    notes は、止めずに知らせる事（origin/HEAD が無い clone の直し方〔head_note〕と、会社の形の知らない鍵・外した鍵〔keys にも入れる。
    --tree の会社の注記に出す〕）。知らない鍵で止めるのは、ゲートを持つ所（役の項目〔role.load の odd〕と [land]〔land.read_rules〕）だけ。
    g は git の口（ports.git）。committed を渡せば、origin の既定のブランチの物をそれで読む（既定は committed_info を g で）。"""
    got = committed(root) if committed else committed_info(root, g)
    notes = []
    if got:
        source, path, text = "origin", got[0], got[1]
    else:
        notes = [n for n in [head_note(root, g)] if n]
        places = [("repo", os.path.join(root, *INFO_FILE))]
        if settings_dir:
            places.append(("settings", settings_info_path(settings_dir, root)))
        for source, path in places:
            if os.path.isfile(path):
                break
        else:
            return _blank(notes=notes)
        try:
            with open(path, encoding="utf-8") as f:
                text = f.read()
        except (OSError, UnicodeDecodeError) as e:
            out = _blank(source, path, notes)
            out["problems"].append(f"{path}: 読めない（{e}）")
            return out
    out = {**_blank(source, path, notes), "text": text}
    try:
        raw = tomllib.loads(text)
    except tomllib.TOMLDecodeError as e:
        out["problems"].append(f"{path}: TOML として読めない（{e}）")
        return out
    for k in ("name", "description"):
        if isinstance(raw.get(k), str):
            out[k] = raw[k]
        elif k in raw:
            out["problems"].append(f"{path}: {k} が文字列で無い")
    desk = raw.get("desk").strip() if isinstance(raw.get("desk"), str) else raw.get("desk")
    if isinstance(desk, str) and desk.count("/") == 1 and all(desk.split("/")):
        out["desk"] = desk   # ほかの会社の窓口が兼ねる（「会社/名前」）。本社に窓口が立っていないときの窓口
    elif "desk" in raw:
        out["problems"].append(f"{path}: desk は「会社/名前」の文字列で書く（ほかの会社の窓口が兼ねるとき）")
    out["skills"] = _skills(raw.get("skills", []), path, out["problems"])
    out["keys"] = known_keys.company(raw, path)
    out["notes"] += out["keys"]
    return out


def roots(workspaces, panes, common_of, cwds=()):
    """会社（元の clone のルート）を、herdr の作業場の並びの順、その後に会話の作業フォルダ（cwds）の順で、重なり無しで。
    herdr が repo_root を持たない作業場は、その作業場の最初のペインの場所を common_of（場所 → 元の clone のルート。git でなければ None）
    に渡す。会話の作業フォルダも common_of に渡す（herdr に開いていない会社の裏の会話も拾う）。"""
    seen, out = set(), []

    def add(root):
        if root and os.path.realpath(root) not in seen:
            seen.add(os.path.realpath(root))
            out.append(root)

    for w in workspaces:
        root = w.get("repo_root")
        if not root:
            cwd = next((p.get("cwd") for p in panes if p.get("workspace_id") == w["workspace_id"] and p.get("cwd")), None)
            root = common_of(cwd) if cwd else None
        add(root)
    for cwd in cwds:
        add(common_of(cwd))
    return out


def _deepest(places, cwd):
    hits = [p for p in places if cwd and filex.inside(cwd, p["path"])]
    return max(hits, key=lambda p: len(os.path.realpath(p["path"])), default=None)


def _owner(places, pane):
    """ペインがどの部署の物か。部署の作業場の中のペインならその部署、そうでなければ場所の一番深く当たる部署。無ければ None。"""
    by_ws = next((p for p in places if p.get("workspace") and p["workspace"] == pane.get("workspace_id")), None)
    return by_ws or _deepest(places, pane.get("cwd"))


def session_state(s):
    """会話の 1 件から、部署の状態（STATES の鍵）。"""
    if s is None:
        return "no_session"
    if s.get("state") in STATES:
        return s["state"]
    return STATUS.get(s.get("status"), "idle")


def copied_from(office, attrs):
    """部署の場所の属性 attrs が、本社の属性 office を git の worktree add が写した物か。git は extensions.worktreeConfig が入って
    いると、作った worktree に元の worktree の config.worktree を写すので、代表の clone から作った worktree（ツールの一時の場所・
    --land の版を上げる一時の場所・herdr が作る部署の場所）は、作ってから属性を消すか書き直すまで、本社と同じ名前の部署に見える。
    git は中身を出す前に写すので、その間には出し終えるまでの時間が入る（my_notes の写しで出すのに 1.2 秒かかった。2026-10-18 に
    --ask 段取り がツールの一時の場所と本社の「2 つ以上ある」で止まった。受付 596ed5）。名前と役が本社と同じで、部署の立て方が書く
    メインブランチを知った位置（company.base）が無い物を写しとみる。会話の id（company.session）では見ない。本社の窓口が会話を替えると本社の
    id だけが書き換わり、写しの方は古い id のまま残るため。base を持つ部署は、本社と同じ名前でも隠さない（前と同じく「2 つ以上ある」で止まる）。"""
    if not attrs.get("name") or attrs.get("base"):
        return False
    return (attrs["name"], attrs.get("role")) == (office.get("name"), office.get("role"))


def build(company_roots, places_of, panes, attrs_of, info_of, sessions=None):
    """会社の並び。places_of は 元の clone のルート → herdr.worktrees の並び（元の clone 自身は linked=False）。panes は herdr の
    ペインの並び。attrs_of は 部署の場所 → その部署の git の属性。info_of は ルート → read_info の結果。sessions は
    アカウントの名 → そのアカウントの claude agents --json --all の並び（無ければ会話を見ない）。"""
    every = [(root, p) for root in company_roots for p in places_of.get(root, []) if not p.get("prunable")]
    flat = [p for _, p in every]
    owned = {}
    for pane in panes:
        got = _owner(flat, pane)
        if got is not None:
            owned.setdefault(id(got), []).append(pane)
    attrs = {id(p): attrs_of(p["path"]) for p in flat}
    for root in company_roots:
        # 本社の属性の写しを載せた worktree は部署に数えない（copied_from）
        office = next((attrs[id(p)] for r, p in every if r == root and not p.get("linked")), {})
        for p in (p for r, p in every if r == root and p.get("linked") and copied_from(office, attrs[id(p)])):
            attrs[id(p)] = {}
    by_id = {a.get("session"): p for p in flat for a in [attrs[id(p)]] if a.get("session")}
    found = {}
    for account, items in (sessions or {}).items():
        for s in items:
            got = by_id.get(s.get("sessionId")) or _deepest(flat, s.get("cwd"))
            if got is not None:
                found.setdefault(id(got), []).append({**s, "account": account})
    companies = []
    for root in company_roots:
        info = info_of(root)
        rows = []
        # 本社（元の clone）を頭に、部署は herdr の作業場の並びと同じ仕事の流れの順（role.flow_rank）、同じ順の中はブランチの名前
        duties = [x.get("name") for x in info.get("skills", [])]
        for p in sorted((p for r, p in every if r == root),
                        key=lambda p: (p.get("linked", False), *role.flow_rank(attrs[id(p)], duties), p.get("branch") or "")):
            a = attrs[id(p)]
            mine = owned.get(id(p), [])
            talks = sorted(found.get(id(p), []), key=lambda s: -(s.get("startedAt") or 0))
            main = next((s for s in talks if a.get("session") and s.get("sessionId") == a["session"]), None) or \
                next(iter(talks), None)
            rows.append({
                "path": p["path"], "branch": p.get("branch"), "head_office": not p.get("linked"),
                "workspace": p.get("workspace") or next((x.get("workspace_id") for x in mine), None),
                "state": session_state(main),
                "session": None if main is None else {k: main.get(k) for k in ("id", "sessionId", "name", "account", "kind",
                                                                               "state", "status", "cwd")},
                "sessions": len(talks),
                "panes": [{"pane_id": x["pane_id"], "label": x.get("label"), "agent": x.get("agent"),
                           "agent_status": x.get("agent_status"),
                           "agent_session": x.get("agent_session")} for x in mine],
                "attrs": a,
                "role": a.get("role"), "lifecycle": a.get("lifecycle"), "fresh": bool(a.get("fresh")),
                "account": a.get("account") or (main or {}).get("account"),
                "name": a.get("name") or (main or {}).get("name"), "boss": a.get("boss"),
            })
        companies.append({"root": root, "name": company_name(root, info),
                          "info_source": info.get("source"), "info_path": info.get("path"),
                          "description": info.get("description"), "skills": info.get("skills", []), "desk_of": info.get("desk"),
                          "problems": info.get("problems", []) + info.get("keys", []), "departments": rows})
    return companies


def contacts(company, shape):
    """--tree に宛て方を足す: 受ける仕事ごとに頼むコマンドの宛先を ask に、会社に窓口（本社の会話）を desk に。shape は role.load の結果。
    外の会社の部署も中の部署も、仕事が決まれば受ける仕事の宛先へ、決まらない件と部署をまたぐ件は窓口へ頼む。窓口は会社の部署すべてを
    見渡す本社の会話で、部署をまたぐ件の上げ先を関わる部署すべてを見渡す段とする組織論の原典（Galbraith 1974）と、外の入口を 1 つに
    する形（ITIL のサービスデスク）に当たる。受ける仕事ごとの宛先は働きごとに宛先を分ける形（RFC 2142）に当たる。
    宛先の決まりは deliver.find_target と同じ: 永続の役の受け持ちとオンデマンドの受け持ちは部署の名前（＝受け持ちの名前。役を足す
    フックが同じ名前で結ぶ）で宛て、永続の役の部署がまだ立っていなければ役で宛てて --task に受け持ちの名前を添える（その名前で立つ）。エフェメラルの役は役で宛てて --task に
    部署の名前を添える。立てるときはブランチ（--branch）も要る（orders.ask）。頼み元（属性 company.boss）は納品の返し先で、ここでは使わない。"""
    plain = company["name"]
    named = {d["attrs"].get("name") for d in company["departments"]}
    for s in company["skills"]:
        r = shape["roles"].get(role.current(shape, s["role"])) if s.get("role") else None
        # 先に使うアカウント（受け持ちの値、無ければ役の値。role.launch_account）。--tree の受ける仕事の行に出す
        s["account_wish"] = role.launch_account(r, s)[0]
        s["ask"] = (None if r is None or r["machine"] else
                    f"--ask {plain}/{s['name']}" if s.get("on_demand") or r["persistent"] and s["name"] in named else
                    f"--ask {plain}/{r['name']} --task {s['name']} --branch <ブランチ>" if r["persistent"] else
                    f"--ask {plain}/{r['name']} --task <部署の名前> --branch <ブランチ>")
    head = next((d for d in company["departments"] if d["head_office"] and d["attrs"].get("name")), None)
    if head is None:
        # 本社の窓口を --handover で継いだ部署が窓口（deliver.find_target の会社の名前だけの宛先と同じ物）
        heirs = [d for d in company["departments"] if not d["head_office"] and gitx.inherited_desk(d["attrs"])]
        head = heirs[0] if len(heirs) == 1 and heirs[0]["attrs"].get("name") else None
    if head is not None:
        # 窓口の会話が起きるときに効く model と effort（役のフィールドの旗が [roles.settings] より先。role.desk_spec）
        model, effort = role.desk_spec(shape["roles"].get(role.current(shape, head["attrs"].get("role"))))
        company["desk"] = {"name": head["attrs"]["name"], "role": head["attrs"].get("role"),
                           "ask": f"--ask {plain}/{head['attrs']['name']}", "model": model, "effort": effort}
    else:
        company["desk"] = None
    if company["desk"] is None and company.get("desk_of"):
        # 会社の形の頭の desk（「会社/名前」）: ほかの会社の窓口がこの会社の窓口を兼ねる（claude-plugins の窓口は my_notes の段取り）
        company["desk"] = {"name": company["desk_of"], "role": None, "ask": f"--ask {company['desk_of']}"}
    return company


def _at(t):
    return time.strftime("%m-%d %H:%M", time.localtime(t)) if t else "-"


def lines(companies):
    """人の読む形。会社ごとに、頭の行・受ける仕事（と宛て方）・窓口・本社・部署の行。"""
    if not companies:
        return [f"{term.NAME} に開いている会社（git のリポジトリ）も、裏の会話も無い"]
    out = []
    for c in companies:
        where = {"origin": "既定のブランチ", "repo": "リポジトリの中", "settings": "設定の置き場"}.get(c["info_source"])
        out.append(f"{c['name']}  {c['root']}" + (f"  （会社の情報: {where}）" if where else "  （会社の情報なし）"))
        if c["description"]:
            out.append(f"  {c['description']}")
        for s in c["skills"]:
            out.append(f"  受ける仕事: {s['name']}" + (f"（{s['description']}）" if s["description"] else "")
                       + (f" → {s['role']}" if s["role"] else "")
                       + "".join(f"  {k} {s[k]}" for k in ("model", "effort") if s.get(k))
                       + (f"  先に使うアカウント {s['account_wish']}" if s.get("account_wish") else "")
                       + (f"  起動方法: {(s['start']['every'] + ' ごとか') if s['start']['every'] else ''}--start"
                          f"、{s['start']['report_to']} に返す" if s.get("start") else "")
                       + (f"（前 {_at(s.get('last_started'))}・次 {_at(s.get('next_start'))}）"
                          if "next_start" in s else "")
                       + ("  オンデマンド" if s.get("on_demand") else "") + ("（頼みごとの部署）" if s.get("per_ask") else "")
                       + (f"  宛て方 {s['ask']}" if s.get("ask") else ""))
        if c.get("desk"):
            desk = c["desk"]   # model・effort はこの会社の本社の窓口だけ（ほかの会社が兼ねる窓口は、その会社の行に出る）
            out.append(f"  窓口: {desk['name']}（受ける仕事に当たらない件・部署をまたぐ件）"
                       + ("".join(f"  {k} {desk[k] or '既定'}" for k in ("model", "effort")) if "model" in desk else "")
                       + f"  宛て方 {desk['ask']}")
        elif "desk" in c and c["skills"]:
            out.append("  窓口: 名付けていない（本社で持ち主と話す会話から --desk を打つと名付く）")
        for t in c.get("tools", []):
            out.append(f"  ツール: {t['role']}/{t['name']}" + (f"（{t['title']}）" if t["title"] else "")
                       + f"  片づかなければ {t['fallback_role']} に回す"
                       + (f"（先に使うアカウント {t['account']}）" if t.get("account") else "") + f"  外れ {t['misses']} 回")
        out += [f"  ! {p}" for p in c["problems"] + c.get("health", [])]
        depts = c["departments"]
        for i, d in enumerate(depts):
            head = "本社" if d["head_office"] else ("└" if i == len(depts) - 1 else "├")
            fields = [STATES[d["state"]] + (f"（会話 {d['sessions']}）" if d["sessions"] > 1 else "")]
            if d["name"]:
                fields.append(f"会話 {d['name']}")
            fields += [f"役 {d['role'] or '-'}" + (f"（{role.seat_label(d['lifecycle'], d['fresh'])}）" if d["role"] else ""), f"アカウント {d['account'] or '-'}", f"頼み元 {d['boss'] or '-'}",
                       f"窓 {'あり' if d['panes'] else 'なし'}"]
            if d.get("queue"):
                stuck = "渡す待ち受けが居ない" if d.get("stalled") else (f"渡さずに待っている（{d['held']}）" if d.get("held") else None)
                fields.append(f"順番待ち {d['queue']} 件（{d['queue_dir']}）"
                              + (f"  ! {stuck}（--nudge {d['name'] or d['branch']} で動かす）" if stuck else ""))
            if d.get("long_wait"):
                w = d["long_wait"]
                fields.append(f"! 裏の処理{'（' + str(w['tasks']) + ' 本）' if w.get('tasks') else ''}を待ってターンを終えたまま、"
                              f"{_at(w['since'])} から同じ頼みで会話が動いていない（待つ処理が終わらない形かを窓で確かめる）")
            if d.get("no_talk_id"):
                fields.append("! 会話の id（company.session）が無い（窓の会話が落ちたとき、--ask か --nudge が会話の一覧の部署の場所の会話で戻して書き戻す）")
            if d.get("tool_place"):
                out.append(f"  {head} （ツールの一時の場所）  {d['path']}  ツールが走り終えれば消える。残っていれば --clean が並べる")
                continue
            out.append(f"  {head} {d['branch'] or '（ブランチ無し）'}  " + "  ".join(fields))
        if c.get("asks"):
            out.append(f"  動いている頼み（台帳でまだ閉じていない物。{len(c['asks'])} 件）:")
            for a in c["asks"]:
                stamp = time.strftime("%m-%d %H:%M", time.localtime(a["at"])) if a.get("at") else "-"
                out.append(f"    {a['id']}  {stamp}  {a['from'] or '-'} → {a['to'] or '-'}  {a['state']}"
                           + (f"  {a['title']}" if a.get("title") else ""))
    return out
