#!/usr/bin/env python3
"""tree ノード: herdr に開いている会社（リポジトリ）ごとに、会社の情報と部署（git worktree）の様子を組み立てる。外には書かない。

会社の形の設計（docs/specs/2026-10-16-company-shape-design.md）の 4.1・4.2・4.4 に当たる。
- 会社 = git のリポジトリ 1 つ。本社は元の clone、部署は元の clone の git worktree（枝 1 本）。
- 問い合わせられる会社 = herdr に開いている作業場が指すリポジトリ。herdr がリポジトリを持たない作業場は、そのペインの場所から
  git の共通の .git を問うて決める（入口が渡す common_of）。同じリポジトリの別の clone は、別の会社として並べる。
- 部署の属性（役・アカウント・会話の名前・上役）は、部署ごとの git の設定 company.<名前>（入口が読んで渡す）。
- 会社の情報（名前と受ける仕事）は、リポジトリの中の INFO_FILE を先に読み、無ければ設定の置き場の companies/ の中の、その
  リポジトリの分を読む（書き方は同じ。Claude Code の settings.json と settings.local.json の分け方と同じ考え）。
  書き方は TOML で、欄の名前は A2A の Agent Card（name・description・skills〔id・name・description〕）に合わせ、受ける役の
  role だけをここで足した。知らない欄は読み飛ばす。

入口の dispatch.py --tree が、herdr・git・claude から読んだ物を渡して build を呼び、lines で人の読む形にする。
"""

import os
import pathlib
import tomllib
import urllib.parse

INFO_FILE = (".claude", "company.toml")  # リポジトリの中の会社の情報（commit する側）
SETTINGS_DIR = "companies"  # 設定の置き場の下の、リポジトリの外の会社の情報（commit しない側）

# herdr の会話の状態 → 部署の状態。会話の居ないペインだけなら no_conversation、ペインが無ければ closed
STATES = {"working": "作業中", "blocked": "確認待ち", "waiting": "待機中", "no_conversation": "会話なし", "closed": "開いていない"}


def inside(cwd, path):
    """cwd が path かその下か（リンクを辿った実際のパスで比べる）。"""
    c, p = pathlib.PurePath(os.path.realpath(cwd)), pathlib.PurePath(os.path.realpath(path))
    return c == p or p in c.parents


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


def read_info(root, settings_dir):
    """その会社の情報。{source: repo|settings|None, path, name, description, skills, problems}。読む順はリポジトリの中、設定の置き場。
    読めない・形の違うファイルは problems に書き、そこで止める（次の置き場へ落とさない。書いた物が効いていないことを隠さない）。"""
    places = [("repo", os.path.join(root, *INFO_FILE))]
    if settings_dir:
        places.append(("settings", settings_info_path(settings_dir, root)))
    for source, path in places:
        if not os.path.isfile(path):
            continue
        out = {"source": source, "path": path, "name": None, "description": None, "skills": [], "problems": []}
        try:
            with open(path, "rb") as f:
                raw = tomllib.load(f)
        except (OSError, tomllib.TOMLDecodeError) as e:
            out["problems"].append(f"{path}: TOML として読めない（{e}）")
            return out
        for k in ("name", "description"):
            if isinstance(raw.get(k), str):
                out[k] = raw[k]
            elif k in raw:
                out["problems"].append(f"{path}: {k} が文字列で無い")
        out["skills"] = _skills(raw.get("skills", []), path, out["problems"])
        return out
    return {"source": None, "path": None, "name": None, "description": None, "skills": [], "problems": []}


def roots(workspaces, panes, common_of):
    """herdr の作業場から、会社（元の clone の根）を herdr の並びの順に、重なり無しで。herdr が repo_root を持たない作業場は、
    その作業場の最初のペインの場所を common_of（git の共通の .git の場所 → 元の clone の根。git でなければ None）に渡す。"""
    seen, out = set(), []
    for w in workspaces:
        root = w.get("repo_root")
        if not root:
            cwd = next((p.get("cwd") for p in panes if p.get("workspace_id") == w["workspace_id"] and p.get("cwd")), None)
            root = common_of(cwd) if cwd else None
        if root and os.path.realpath(root) not in seen:
            seen.add(os.path.realpath(root))
            out.append(root)
    return out


def _owner(places, pane):
    """ペインがどの部署の物か。部署の作業場の中のペインならその部署、そうでなければ場所の一番深く当たる部署。無ければ None。"""
    by_ws = next((p for p in places if p.get("workspace") and p["workspace"] == pane.get("workspace_id")), None)
    if by_ws:
        return by_ws
    hits = [p for p in places if pane.get("cwd") and inside(pane["cwd"], p["path"])]
    return max(hits, key=lambda p: len(os.path.realpath(p["path"])), default=None)


def _session_owner(places, session, pane_of_session):
    pane = pane_of_session.get(session.get("sessionId"))
    if pane is not None:
        return _owner(places, pane)
    hits = [p for p in places if session.get("cwd") and inside(session["cwd"], p["path"])]
    return max(hits, key=lambda p: len(os.path.realpath(p["path"])), default=None)


def state(panes):
    """部署のペインの並びから、部署の状態（STATES の鍵）。"""
    talking = [p for p in panes if p.get("agent")]
    if any(p.get("agent_status") == "working" for p in talking):
        return "working"
    if any(p.get("agent_status") == "blocked" for p in talking):
        return "blocked"
    if talking:
        return "waiting"
    return "no_conversation" if panes else "closed"


def build(company_roots, places_of, panes, attrs_of, info_of, sessions=None):
    """会社の並び。places_of は 元の clone の根 → herdr.worktrees の並び（元の clone 自身は linked=False）。panes は herdr の
    ペインの並び。attrs_of は 部署の場所 → その部署の git の属性。info_of は 根 → read_info の結果。sessions は
    アカウントの名 → そのアカウントの claude agents --json の並び（無ければ会話のアカウントを見ない）。"""
    every = [(root, p) for root in company_roots for p in places_of.get(root, []) if not p.get("prunable")]
    flat = [p for _, p in every]
    owned = {}
    for pane in panes:
        got = _owner(flat, pane)
        if got is not None:
            owned.setdefault(id(got), []).append(pane)
    pane_of_session = {(p.get("agent_session") or {}).get("value"): p for p in panes if (p.get("agent_session") or {}).get("value")}
    live = {}
    for account, items in (sessions or {}).items():
        for s in items:
            got = _session_owner(flat, s, pane_of_session)
            if got is not None:
                live.setdefault(id(got), set()).add(account)
    companies = []
    for root in company_roots:
        info = info_of(root)
        rows = []
        for p in sorted((p for r, p in every if r == root), key=lambda p: (p.get("linked", False), p.get("branch") or "")):
            mine = owned.get(id(p), [])
            attrs = attrs_of(p["path"])
            rows.append({
                "path": p["path"], "branch": p.get("branch"), "head_office": not p.get("linked"),
                "workspace": p.get("workspace") or next((x.get("workspace_id") for x in mine), None),
                "state": state(mine),
                "panes": [{"pane_id": x["pane_id"], "label": x.get("label"), "agent": x.get("agent"),
                           "agent_status": x.get("agent_status")} for x in mine],
                "attrs": attrs,
                "role": attrs.get("role"), "account": attrs.get("account"), "name": attrs.get("name"),
                "boss": attrs.get("boss"),
                "live_accounts": sorted(live.get(id(p), ())),
            })
        companies.append({"root": root, "name": info.get("name") or os.path.basename(os.path.normpath(root)),
                          "info_source": info.get("source"), "info_path": info.get("path"),
                          "description": info.get("description"), "skills": info.get("skills", []),
                          "problems": info.get("problems", []), "departments": rows})
    return companies


def _account(d):
    if d["account"]:
        return d["account"]
    return f"{'・'.join(d['live_accounts'])}（会話から）" if d["live_accounts"] else "-"


def lines(companies):
    """人の読む形。会社ごとに、頭の行・受ける仕事・本社・部署の行。"""
    if not companies:
        return ["herdr に開いている会社（git のリポジトリ）は無い"]
    out = []
    for c in companies:
        where = {"repo": "リポジトリの中", "settings": "設定の置き場"}.get(c["info_source"])
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
            fields = [STATES[d["state"]], f"役 {d['role'] or '-'}", f"アカウント {_account(d)}", f"上役 {d['boss'] or '-'}"]
            if d["name"]:
                fields.insert(1, f"会話 {d['name']}")
            out.append(f"  {head} {d['branch'] or '（枝無し）'}  " + "  ".join(fields))
    return out
