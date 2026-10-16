#!/usr/bin/env python3
"""tree ノード: herdr に開いている会社（リポジトリ）ごとに、会社の情報と部署（git worktree）の様子を組み立てる。外には書かない。

会社の形の設計（docs/specs/2026-10-16-company-shape-design.md）の 4.1・4.2・4.4 に当たる。
- 会社 = git のリポジトリ 1 つ。本社は元の clone、部署は元の clone の git worktree（枝 1 本）。
- 問い合わせられる会社 = herdr に開いている作業場が指すリポジトリ。herdr がリポジトリを持たない作業場は、そのペインの場所から
  git の共通の .git を問うて決める（入口が渡す common_of）。同じリポジトリの別の clone は、別の会社として並べる。
- 部署の属性（役・アカウント・会話の名前と id・上役）は、部署ごとの git の設定 company.<名前>（入口が読んで渡す）。
- 部署の会話とその状態は、全アカウントの claude agents --json --all を合わせて見る（一覧はアカウントごとに分かれる。
  会社の形の設計 9.1）。会話は、属性の company.session（会話の id）で結び、無ければ会話の作業フォルダの場所で結ぶ。
  状態は裏の会話の state（作業中・止まっている・終わった など）、手前の会話（kind が interactive）は status から取る。
- 窓は、部署の作業場か部署の場所のペイン（attach の画面など）が herdr に在るか。
- 会社の情報（名前と受ける仕事）は、リポジトリの中の INFO_FILE を先に読み、無ければ設定の置き場の companies/ の中の、その
  リポジトリの分を読む（書き方は同じ。Claude Code の settings.json と settings.local.json の分け方と同じ考え）。リポジトリの中の
  物は、origin の既定の枝（origin/HEAD が指す手元の ref）に commit された物を先に読み、無ければ元の clone の作業ツリーの物を読む
  （read_info）。元の clone の作業ツリーはほかの会話が古い枝で使っていることがあり、部署の枝は部署が書き換えうるので、どちらにも
  頼らない。会社の形を読む所（--tree・--task・--ask・--deliver・--land・役を足すフック）は全部 read_info を通る。origin は在るのに
  origin/HEAD が無い clone では既定の枝を決められないので、作業ツリーから読み、直し方（HEAD_FIX）を注記に出す（head_note）。
  書き方は TOML で、欄の名前は A2A の Agent Card（name・description・skills〔id・name・description〕）に合わせ、受ける役の
  role だけをここで足した。知らない欄は読み飛ばす。

入口の dispatch.py --tree が、herdr・git・claude から読んだ物を渡して build を呼び、lines で人の読む形にする。
"""

import os
import pathlib
import tomllib
import urllib.parse

import gitx

INFO_FILE = (".claude", "company.toml")  # リポジトリの中の会社の情報（commit する側）
SETTINGS_DIR = "companies"  # 設定の置き場の下の、リポジトリの外の会社の情報（commit しない側）

# 部署の状態（会話の state、無ければ status から）と、その字
STATES = {"working": "作業中", "blocked": "止まっている", "done": "終わった", "failed": "失敗した", "stopped": "止めた",
          "idle": "待機中", "no_session": "会話なし"}
STATUS = {"busy": "working", "waiting": "blocked", "idle": "idle"}  # 手前の会話の status → 状態


def inside(cwd, path):
    """cwd が path かその下か（リンクを辿った実際のパスで比べる）。"""
    c, p = pathlib.PurePath(os.path.realpath(cwd)), pathlib.PurePath(os.path.realpath(path))
    return c == p or p in c.parents


def _session_of(pane):
    """ペインの会話の印（herdr の agent_session の value）。無ければ None。"""
    got = pane.get("agent_session")
    return got.get("value") if isinstance(got, dict) else None


def settings_info_path(settings_dir, root):
    """設定の置き場の中の、そのリポジトリ（元の clone の根）の会社の情報のファイル。名前は根の実際のパスを字の符号にしたもの
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
        out.append({k: s[k] if isinstance(s.get(k), str) else None for k in ("id", "name", "description", "role")})
    return out


def committed_info(root):
    """origin の既定の枝に commit された INFO_FILE。(場所の札 例 origin/main:.claude/company.toml, 中身) か None。
    手元の ref を読むだけで fetch しない（毎回の会話の始まりに走るフックも通るので、外へ問い合わせない）。"""
    ref = gitx.origin_head(root)
    rel = "/".join(INFO_FILE)
    text = gitx.file_at(root, ref, rel) if ref else None
    return (f"{ref}:{rel}", text) if text is not None else None


HEAD_FIX = "remote set-head origin --auto"  # origin/HEAD を origin の今の既定の枝に向ける git の命令（git -C <根> の後ろ）


def head_note(root, g=gitx):
    """origin は在るのに origin/HEAD が無い clone なら、会社の形の読み方が落ちる訳と直し方の注記。それ以外（git でない・origin が
    無い・origin/HEAD が在る）は None。手元の ref を読むだけ。"""
    if not g.origin_url(root) or g.origin_head(root):
        return None
    return (f"{root} に origin/HEAD（origin の既定の枝を指す手元の印）が無いので、origin の既定の枝に commit された会社の形を読めず、"
            f"元の clone の作業ツリー（古い枝なら古い形）か設定の置き場の物で読む。直すには: git -C {root} {HEAD_FIX}")


def _blank(source=None, path=None, notes=()):
    return {"source": source, "path": path, "text": None, "name": None, "description": None, "skills": [], "problems": [],
            "notes": list(notes)}


def read_info(root, settings_dir, committed=committed_info):
    """その会社の情報。{source: origin|repo|settings|None, path, text, name, description, skills, problems, notes}。会社の形を読む場所を
    決めるのはこの 1 か所で、読む順は origin の既定の枝に commit された物（committed。path は ref:パス の札）、元の clone の作業
    ツリーの物、設定の置き場の物。text は読んだ中身（role.load・land.read_rules に渡す。同じ物を読み直さない）。
    読めない・形の違うファイルは problems に書き、そこで止める（次の置き場へ落とさない。書いた物が効いていないことを隠さない）。
    notes は、止めずに知らせる事（origin/HEAD が無い clone の直し方。head_note）。"""
    got = committed(root)
    notes = []
    if got:
        source, path, text = "origin", got[0], got[1]
    else:
        notes = [n for n in [head_note(root)] if n]
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
    out["skills"] = _skills(raw.get("skills", []), path, out["problems"])
    return out


def roots(workspaces, panes, common_of, cwds=()):
    """会社（元の clone の根）を、herdr の作業場の並びの順、その後に会話の作業フォルダ（cwds）の順で、重なり無しで。
    herdr が repo_root を持たない作業場は、その作業場の最初のペインの場所を common_of（場所 → 元の clone の根。git でなければ None）
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
    hits = [p for p in places if cwd and inside(cwd, p["path"])]
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


def build(company_roots, places_of, panes, attrs_of, info_of, sessions=None):
    """会社の並び。places_of は 元の clone の根 → herdr.worktrees の並び（元の clone 自身は linked=False）。panes は herdr の
    ペインの並び。attrs_of は 部署の場所 → その部署の git の属性。info_of は 根 → read_info の結果。sessions は
    アカウントの名 → そのアカウントの claude agents --json --all の並び（無ければ会話を見ない）。"""
    every = [(root, p) for root in company_roots for p in places_of.get(root, []) if not p.get("prunable")]
    flat = [p for _, p in every]
    owned = {}
    for pane in panes:
        got = _owner(flat, pane)
        if got is not None:
            owned.setdefault(id(got), []).append(pane)
    attrs = {id(p): attrs_of(p["path"]) for p in flat}
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
        for p in sorted((p for r, p in every if r == root), key=lambda p: (p.get("linked", False), p.get("branch") or "")):
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
                           "agent_session": _session_of(x)} for x in mine],
                "attrs": a,
                "role": a.get("role"), "residency": a.get("residency"),
                "account": a.get("account") or (main or {}).get("account"),
                "name": a.get("name") or (main or {}).get("name"), "boss": a.get("boss"),
            })
        companies.append({"root": root, "name": info.get("name") or os.path.basename(os.path.normpath(root)),
                          "info_source": info.get("source"), "info_path": info.get("path"),
                          "description": info.get("description"), "skills": info.get("skills", []),
                          "problems": info.get("problems", []), "departments": rows})
    return companies


def lines(companies):
    """人の読む形。会社ごとに、頭の行・受ける仕事・本社・部署の行。"""
    if not companies:
        return ["herdr に開いている会社（git のリポジトリ）も、裏の会話も無い"]
    out = []
    for c in companies:
        where = {"origin": "既定の枝", "repo": "リポジトリの中", "settings": "設定の置き場"}.get(c["info_source"])
        out.append(f"{c['name']}  {c['root']}" + (f"  （会社の情報: {where}）" if where else "  （会社の情報なし）"))
        if c["description"]:
            out.append(f"  {c['description']}")
        for s in c["skills"]:
            out.append(f"  受ける仕事: {s['name']}" + (f"（{s['description']}）" if s["description"] else "")
                       + (f" → {s['role']}" if s["role"] else ""))
        out += [f"  ! {p}" for p in c["problems"]]
        depts = c["departments"]
        for i, d in enumerate(depts):
            head = "本社" if d["head_office"] else ("└" if i == len(depts) - 1 else "├")
            fields = [STATES[d["state"]] + (f"（会話 {d['sessions']}）" if d["sessions"] > 1 else "")]
            if d["name"]:
                fields.append(f"会話 {d['name']}")
            fields += [f"役 {d['role'] or '-'}" + ("（常駐）" if d["residency"] == "resident" else ""), f"アカウント {d['account'] or '-'}", f"上役 {d['boss'] or '-'}",
                       f"窓 {'あり' if d['panes'] else 'なし'}"]
            out.append(f"  {head} {d['branch'] or '（枝無し）'}  " + "  ".join(fields))
    return out
