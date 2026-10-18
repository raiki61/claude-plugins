#!/usr/bin/env python3
"""/reflect の機械の側。ある期間の材料を集め（--out）、AI の書いたフィールドをページに描く（--render）。

〈目的〉手で打てば、その期間の作業から改善の提案と、持ち主の仕事の仕方についての気づきを出す。
判断（何を提案するか・何に気づくか）は AI の仕事で、ここは数えて並べるだけ。仕様の正本は
attention/docs/reflect-spec.md。

〈決め打ちしない〉持ち主の環境の値（ノートの場所・アカウントのフォルダ・gh のアカウント名・探す
リポジトリの範囲）は持たない。読む設定のフォルダは今の Claude Code のもの（足すなら
ATTENTION_REFLECT_CONFIG_DIRS か --config-dir）、リポジトリは会話の作業フォルダから、gh の
アカウントは gh auth status から、日記の置き場は ATTENTION_REFLECT_DIARY_DIR から引く。

〈トークンの数え方〉記録は 1 つの返答を内容のまとまりごとに何行にも分けて書き、行ごとに同じ使用量を
繰り返す。返答（message.id）ごとに 1 回だけ数える（2026-10-16 実測: 行ごとに足すと約 2 倍になった）。
"""

import argparse
import collections
import datetime as dt
import json
import os
import pathlib
import re
import statistics
import subprocess
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "lib"))
import catchup_html  # noqa: E402 — ページの書き方と VS Code で開く口を /catchup と共用
import changemap  # noqa: E402 — remote URL の読み方。/catchup と共用
import claude_auth  # noqa: E402 — 設定のフォルダの決め方（リポジトリの scripts/ の写し）
import transcript  # noqa: E402 — 区切りの操作の表。/what-am-i-doing と共用

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

SCHEMA = 1
HERE = pathlib.Path(__file__).resolve().parent
TEMPLATE = HERE.parent / "templates" / "reflect.html"
DATA_SLOT = "/*__DATA__*/null"
TITLE_SLOT = "<title>reflect</title>"

DIRS_ENV = "ATTENTION_REFLECT_CONFIG_DIRS"
DIARY_ENV = "ATTENTION_REFLECT_DIARY_DIR"
TYPED = {"typed", "queued"}
PASTED = re.compile(r"</?pasted_content[^>]*>")  # 貼り付けの囲み。中身は人の発言として残し、印だけ外す
COMMAND = re.compile(r"<command-name>(.*?)</command-name>(?:.*?<command-args>(.*?)</command-args>)?", re.S)

ASK_CHARS = 300          # 発言 1 件の上限
ASKS_KEEP = 6            # 1 会話の発言は前と後ろからこの数ずつ
FIRST_PROMPT_KEY = 40    # 裏の会話を起動した元を見分ける依頼文の頭
COMMITS_PER_REPO = 60
EVENT_PAGES = 3          # GitHub の events は 1 ページ 100 件・300 件まで
GIT_TIMEOUT_SEC = 20     # 外部コマンドを無制限に待たない（catchup.py と同じ秒）
PROPOSALS_CAP = 7
INSIGHTS_CAP = 7
DIARY_CHARS = 2000
KINDS = ("stop", "automate", "config", "adopt", "fix")
STATUSES = ("open", "adopted", "dismissed", "held")
ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{2,59}$")
DIARY_START = "<!-- reflect:start -->"
DIARY_END = "<!-- reflect:end -->"


# ---- 期間 ----------------------------------------------------------------------


def period(spec, today=None):
    """期間の語を (始まりの日, 終わりの日)（両端を含む）に。読めなければ ValueError。"""
    today = today or dt.date.today()
    spec = (spec or "week").strip()
    named = {"today": (0, 0), "yesterday": (1, 1), "week": (6, 0), "month": (29, 0)}
    if spec in named:
        back, end = named[spec]
        return today - dt.timedelta(days=back), today - dt.timedelta(days=end)
    m = re.fullmatch(r"(\d{4}-\d{2}-\d{2})(?:\.\.(\d{4}-\d{2}-\d{2}))?", spec)
    if not m:
        raise ValueError(f"期間が読めない: {spec}（today・yesterday・week・month・YYYY-MM-DD・YYYY-MM-DD..YYYY-MM-DD）")
    start = dt.date.fromisoformat(m.group(1))
    end = dt.date.fromisoformat(m.group(2)) if m.group(2) else start
    if end < start:
        raise ValueError(f"期間の終わりが始まりより前: {spec}")
    return start, end


def bounds(start, end):
    """日の境は手元の時刻帯の 0 時。戻り値は時刻帯付きの [始まり, 終わり)。"""
    return (dt.datetime.combine(start, dt.time()).astimezone(),
            dt.datetime.combine(end + dt.timedelta(days=1), dt.time()).astimezone())


def when(entry):
    ts = entry.get("timestamp")
    if not isinstance(ts, str):
        return None
    try:
        return dt.datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return None


# ---- 読む設定のフォルダ -----------------------------------------------------------


def config_dirs(env, extra=()):
    """今の設定のフォルダと、足すと言われたフォルダ（在るものだけ、重なりを除いて）。"""
    raw = [claude_auth.config_dir(env)]
    raw += [p for p in (env.get(DIRS_ENV) or "").split(os.pathsep) if p.strip()]
    raw += list(extra)
    out, seen = [], set()
    for p in raw:
        path = pathlib.Path(os.path.expanduser(p.strip()))
        try:
            key = path.resolve()
        except OSError:
            continue
        if key in seen or not path.is_dir():
            continue
        seen.add(key)
        out.append(path)
    return out


# ---- 会話 ------------------------------------------------------------------------


def text_of(entry):
    """user の行の文字。ツールの結果なら None。"""
    content = (entry.get("message") or {}).get("content")
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return None
    if any(isinstance(b, dict) and b.get("type") == "tool_result" for b in content):
        return None
    return "\n".join(b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text")


def human_ask(entry, text):
    """人の発言なら、その文（コマンドは「/名前 引数」に直す）。そうでなければ None。

    打った発言には promptSource が付くが、コマンド（/attention:catchup など）の行には付かない
    （2026-10-16 実測）。コマンドの形の行も人の発言として拾う。"""
    if entry.get("isMeta") or text is None:
        return None
    m = COMMAND.search(text)
    if m:
        return f"{m.group(1).strip()} {(m.group(2) or '').strip()}".strip()
    if entry.get("promptSource") in TYPED:
        return PASTED.sub("", text).strip()
    return None


def scan(path, start, end):
    """1 つの会話の記録から期間の中の分を数える。期間に 1 行も無ければ None。"""
    s = {"id": path.stem, "cwd": None, "first": None, "last": None, "asks": [], "first_prompt": None,
         "tools": collections.Counter(), "marks": collections.Counter(), "out": {}, "models": {}, "errors": 0}
    try:
        f = open(path, encoding="utf-8", errors="replace")
    except OSError:
        return None
    with f:
        for line in f:
            try:
                o = json.loads(line)
            except ValueError:
                continue
            if not isinstance(o, dict):
                continue
            t = when(o)
            if t is None or not (start <= t < end):
                continue
            s["cwd"] = s["cwd"] or o.get("cwd")
            s["first"] = s["first"] or t
            s["last"] = t
            kind = o.get("type")
            if kind == "user":
                text = text_of(o)
                ask = human_ask(o, text)
                if ask is not None:
                    s["asks"].append(ask)
                if s["first_prompt"] is None and text and not o.get("isMeta"):
                    s["first_prompt"] = ask or text
            elif kind == "assistant":
                msg = o.get("message") or {}
                mid = msg.get("id") or f"line{len(s['out'])}"
                usage = msg.get("usage") or {}
                s["out"][mid] = max(s["out"].get(mid, 0), int(usage.get("output_tokens") or 0))
                if msg.get("model"):
                    s["models"][mid] = msg["model"]
                if o.get("isApiErrorMessage"):
                    s["errors"] += 1
                for b in msg.get("content") or []:
                    if not (isinstance(b, dict) and b.get("type") == "tool_use"):
                        continue
                    s["tools"][b.get("name") or "?"] += 1
                    if b.get("name") == "Bash":
                        for key in transcript.landmarks((b.get("input") or {}).get("command")):
                            s["marks"][key] += 1
    return s if s["first"] else None


def clip(text, n=ASK_CHARS):
    text = re.sub(r"\s+", " ", text or "").strip()
    return text if len(text) <= n else text[:n] + "…"


def sessions(dirs, start, end):
    """(人の会話の並び, 裏の会話の並び)。両方とも scan の結果に、どのフォルダかを足したもの。"""
    human, background = [], []
    floor = start.timestamp()
    for d in dirs:
        for path in sorted((d / "projects").glob("*/*.jsonl")):
            try:
                if path.stat().st_mtime < floor:
                    continue
            except OSError:
                continue
            s = scan(path, start, end)
            if not s:
                continue
            s["config_dir"] = d.name
            (human if s["asks"] else background).append(s)
    return human, background


def home_short(p):
    home = str(pathlib.Path.home())
    return ("~" + p[len(home):]) if p and p.startswith(home) else p


def tokens_by_model(group):
    """出力のトークンをモデルごとに足す（モデルの分からない返答は "?"）。単価がモデルで数十倍違うので、モデルをまたいで足さない。"""
    out = collections.Counter()
    for s in group:
        for mid, n in s["out"].items():
            out[s["models"].get(mid, "?")] += n
    return {m: n for m, n in out.most_common() if n}  # 失敗の返答（<synthetic>）のような 0 の行は出さない


def human_rows(human, days=1):
    """会話ごとの行。期間が長いほど 1 会話の発言を減らす（AI が読む量を 1 日分と同じくらいに保つ）。"""
    keep = ASKS_KEEP if days <= 1 else max(2, ASKS_KEEP // 2)
    chars = ASK_CHARS if days <= 1 else ASK_CHARS * 2 // 3
    rows = []
    for s in sorted(human, key=lambda s: s["first"]):
        asks = s["asks"]
        kept = asks if len(asks) <= 2 * keep else asks[:keep] + asks[-keep:]
        rows.append({
            "id": s["id"], "config_dir": s["config_dir"], "cwd": home_short(s["cwd"]),
            "start": s["first"].astimezone().isoformat(timespec="minutes"),
            "end": s["last"].astimezone().isoformat(timespec="minutes"),
            "asks_total": len(asks), "asks": [clip(a, chars) for a in kept],
            "asks_cut": len(asks) - len(kept),
            "tools": dict(s["tools"].most_common(8)), "marks": dict(s["marks"]),
            "output_tokens": sum(s["out"].values()), "output_by_model": tokens_by_model([s]),
            "errors": s["errors"],
        })
    return rows


def origin_key(s):
    head = re.sub(r"\s+", " ", s["first_prompt"] or "").strip()[:FIRST_PROMPT_KEY]
    return home_short(s["cwd"] or "?"), head


def background_rows(background):
    groups = collections.defaultdict(list)
    for s in background:
        groups[origin_key(s)].append(s)
    rows = []
    for (cwd, head), group in groups.items():
        per = [sum(s["out"].values()) for s in group]
        rows.append({
            "cwd": cwd, "prompt_head": head, "runs": len(group),
            "config_dirs": sorted({s["config_dir"] for s in group}),
            "output_tokens": sum(per), "median_output_tokens": int(statistics.median(per)) if per else 0,
            "max_output_tokens": max(per) if per else 0,
            "models": tokens_by_model(group), "errors": sum(s["errors"] for s in group),
        })
    rows.sort(key=lambda r: (-r["output_tokens"], -r["runs"]))
    return rows


def normalize(ask):
    return re.sub(r"\d+", "#", re.sub(r"\s+", " ", ask).strip().lower())


def repeats(human):
    """2 回以上出た発言（正規化した形）と、コマンドの回数。"""
    seen = collections.defaultdict(set)
    count = collections.Counter()
    commands = collections.Counter()
    for s in human:
        for ask in s["asks"]:
            if ask.startswith("/"):
                commands[ask.split()[0]] += 1  # コマンドは名前で数える。発言の繰り返しには並べない
                continue
            key = normalize(ask)
            if len(key) < 2:
                continue
            count[key] += 1
            seen[key].add(s["id"])
    asks = [{"text": clip(k, 160), "count": n, "sessions": len(seen[k])}
            for k, n in count.most_common() if n >= 2][:30]
    return asks, dict(commands.most_common(20))


# ---- git と GitHub ----------------------------------------------------------------


def run(args, cwd=None, env=None):
    """外部コマンドの標準出力。失敗・時間切れ・無いコマンドは None（材料が減るだけで止まらない）。"""
    try:
        p = subprocess.run(args, cwd=cwd, env=env, capture_output=True, encoding="utf-8",  # noqa: S603 — 引数はこのファイルの組み立て
                           errors="replace", timeout=GIT_TIMEOUT_SEC)
    except (OSError, subprocess.SubprocessError):
        return None
    return p.stdout if p.returncode == 0 else None


def repo_label(top):
    """リポジトリの呼び名。origin の "owner/name"（読み方は lib/changemap.py の repo_of）か、無ければフォルダの名前。"""
    url = run(["git", "-C", top, "remote", "get-url", "origin"]) or ""
    return changemap.repo_of(url) or os.path.basename(top)


def repo_tops(cwds):
    """作業フォルダから引いたリポジトリ（worktree は同じリポジトリにまとめる）。{共通の .git: 最初に見たルート}。"""
    repos = {}
    for cwd in cwds:
        if not cwd or not os.path.isdir(cwd):
            continue
        common = (run(["git", "-C", cwd, "rev-parse", "--path-format=absolute", "--git-common-dir"]) or "").strip()
        top = (run(["git", "-C", cwd, "rev-parse", "--show-toplevel"]) or "").strip()
        if common and top and common not in repos:
            repos[common] = top
    return repos


def commits(cwds, start, end):
    """会話の作業フォルダから引いたリポジトリごとに、その user.email の期間の commit。

    二重に数えないための 3 つ（どれも 2026-10-16 の実測で数が膨らんだ）:
    - --all でなくローカルブランチとリモート追跡ブランチだけ。git subrepo などが持つ別の ref（refs/subrepo/…）は、取り込んだ先の
      他のリポジトリの commit を同じ author で抱えている
    - --first-parent。取り込み（subrepo pull・main の取り込み）で第 2 親から入った他所の commit を外す
    - 同じ origin の別の clone は 1 つのリポジトリにまとめ、同じ commit は 1 回だけ数える"""
    by_label, seen = {}, set()
    for top in repo_tops(cwds).values():
        email = (run(["git", "-C", top, "config", "user.email"]) or "").strip()
        if not email:
            continue
        log = run(["git", "-C", top, "log", "--branches", "--remotes", "--first-parent", "--no-merges",
                   f"--author={email}", f"--since={start.isoformat()}", f"--until={end.isoformat()}",
                   "--format=%H%x1f%aI%x1f%s", f"-n{COMMITS_PER_REPO}"]) or ""
        label = repo_label(top)
        for line in log.splitlines():
            if line.count("\x1f") != 2:
                continue
            sha, at, subject = line.split("\x1f")
            if sha in seen:
                continue
            seen.add(sha)
            by_label.setdefault(label, []).append({"sha": sha[:9], "at": at, "subject": subject})
    return [{"repo": k, "count": len(v), "commits": v[:COMMITS_PER_REPO]} for k, v in by_label.items()]


def gh_logins(unseen=None):
    """gh で使えるアカウントの login。読めなければ空で、unseen に訳を足す（渡されたときだけ）。"""
    unseen = [] if unseen is None else unseen
    raw = run(["gh", "auth", "status", "--json", "hosts"])
    logins = []
    if raw is None:
        unseen.append("GitHub の動き: gh auth status が失敗した（gh が無いか、ログインしていない）。どのアカウントも読んでいない")
        return logins
    try:
        hosts = json.loads(raw).get("hosts") or {}
    except (ValueError, AttributeError) as e:
        unseen.append(f"GitHub の動き: gh auth status の出力を読めなかった（{type(e).__name__}）。どのアカウントも読んでいない")
        return logins
    for entry in hosts.get("github.com") or []:
        if entry.get("state") == "success" and entry.get("login") and entry["login"] not in logins:
            logins.append(entry["login"])
    return logins


def event_row(e):
    p = e.get("payload") or {}
    item = p.get("pull_request") or p.get("issue") or {}
    review = p.get("review") or {}
    return {"type": (e.get("type") or "").replace("Event", ""), "repo": (e.get("repo") or {}).get("name"),
            "action": p.get("action") or review.get("state"), "number": item.get("number"),
            "title": clip(item.get("title") or "", 120), "at": local(e.get("created_at")),
            "private": not e.get("public", False)}


def local(ts):
    t = when({"timestamp": ts})
    return t.astimezone().isoformat(timespec="minutes") if t else ts


def github(start, end, unseen=None):
    """gh で使えるアカウントごとの、期間の動き。ページが読めなかったら、そのアカウントの残りのページは
    読まずに次のアカウントへ進み、unseen に訳を足す（空の結果と見分けが付くように）。"""
    unseen = [] if unseen is None else unseen
    out = []
    for login in gh_logins(unseen):
        token = (run(["gh", "auth", "token", "--hostname", "github.com", "--user", login]) or "").strip()
        env = {**os.environ, "GH_TOKEN": token} if token else None
        rows, oldest, full = [], None, True
        for page in range(1, EVENT_PAGES + 1):
            raw = run(["gh", "api", f"/users/{login}/events?per_page=100&page={page}"], env=env)
            try:
                events = json.loads(raw) if raw is not None else None
            except ValueError:
                events = None
            if not isinstance(events, list):
                unseen.append(f"GitHub の動き: {login} の {page} ページ目を読めなかった（gh api が失敗したか、形が違う）。"
                              "そこから先の動きは数えていない")
                full = False
                break
            for e in events:
                t = when({"timestamp": e.get("created_at")})
                if t is None:
                    continue
                oldest = t if oldest is None or t < oldest else oldest
                if start <= t < end:
                    rows.append(event_row(e))
            if len(events) < 100 or (oldest and oldest < start):
                full = False
                break
        kinds = collections.Counter(r["type"] for r in rows)
        out.append({"login": login, "count": len(rows), "kinds": dict(kinds), "events": rows[:200],
                    "truncated": full and bool(oldest) and oldest >= start})
    return out


# ---- /insights の控えと持ち物 --------------------------------------------------------


def insights(dirs, session_ids):
    facets, reports = [], []
    for d in dirs:
        base = d / "usage-data"
        for sid in session_ids:
            p = base / "facets" / f"{sid}.json"
            if not p.is_file():
                continue
            try:
                f = json.loads(p.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if isinstance(f, dict):
                facets.append({k: f.get(k) for k in ("session_id", "brief_summary", "outcome", "friction_counts",
                                                      "friction_detail", "underlying_goal")})
        found = sorted(base.glob("report*.html"), key=lambda p: p.stat().st_mtime) if base.is_dir() else []
        if found:
            newest = found[-1]
            reports.append({"config_dir": d.name, "path": str(newest),
                            "at": dt.datetime.fromtimestamp(newest.stat().st_mtime).astimezone().isoformat(timespec="minutes")})
    return {"facets": facets, "reports": reports}


def first_line(path):
    """コマンド・スキルの説明（先頭の `---` の間の `description:`）。ファイルが読めなければ読めなかったと、
    説明が書かれていなければ無いと書いた文を返す（空にすると 2 つが「説明が空」と同じに見える）。"""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as e:
        return f"（読めなかった: {type(e).__name__}）"
    about = frontmatter_description(text)
    return clip(about, 160) if about is not None else "（説明が無い: 先頭の --- の間に description が無い）"


def frontmatter_description(text):
    """先頭の `---` の間の `description:` の値。無ければ None。

    YAML を読む物が標準ライブラリに無く、プラグインは pip の物を持てない（docs/standards/machine-readable-values.md
    の決まり 5）。ここで要るのは説明の 1 項目だけなので、この 1 か所で読む。本文の中の `description:` は拾わない。
    折り返し（`>`・`|`）と、次の行へ続く字下げの値は、続きの行を空白でつないで 1 行にする。"""
    lines = text.lstrip("\ufeff").splitlines()  # 先頭の BOM は frontmatter の --- の前に来る
    if not lines or lines[0].strip() != "---":
        return None
    head = []
    for line in lines[1:]:
        if line.strip() == "---":
            break
        head.append(line)
    else:
        return None  # 閉じの --- が無い。frontmatter でない
    for i, line in enumerate(head):
        if not line.startswith("description:"):
            continue
        value = line[len("description:"):].strip()
        rest = []
        for more in head[i + 1:]:
            if more[:1] not in (" ", "\t"):
                break
            rest.append(more.strip())
        if value in (">", "|", ">-", "|-", ">+", "|+") or not value:
            value = " ".join(rest)
        elif rest:
            value = " ".join([value, *rest])
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        return value
    return None


def assets(dirs, cwds):
    plugins, seen = [], set()
    for d in dirs:
        try:
            installed = json.loads((d / "plugins" / "installed_plugins.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            installed = {}
        for name, entries in (installed.get("plugins") or {}).items():
            for e in entries if isinstance(entries, list) else []:
                root = pathlib.Path(e.get("installPath") or "")
                # 同じプラグインが入れた範囲（user・project）の数だけ並ぶので、名前で 1 つにする
                if name in seen:
                    continue
                seen.add(name)
                cmds = [{"name": p.stem, "about": first_line(p)} for p in sorted(root.glob("commands/*.md"))]
                skills = [{"name": p.parent.name, "about": first_line(p)} for p in sorted(root.glob("skills/*/SKILL.md"))]
                plugins.append({"plugin": name, "version": e.get("version"), "commands": cmds, "skills": skills})
    files = [str(d / "CLAUDE.md") for d in dirs if (d / "CLAUDE.md").is_file()]
    for top in repo_tops(cwds).values():
        files += [str(pathlib.Path(top) / n) for n in ("CLAUDE.md", "AGENTS.md") if (pathlib.Path(top) / n).is_file()]
    return {"plugins": plugins, "instructions": [home_short(f) for f in files]}


# ---- 台帳 ------------------------------------------------------------------------


def ledger_path(env=None):
    env = os.environ if env is None else env
    base = env.get("XDG_STATE_HOME") or os.path.join(os.path.expanduser("~"), ".local", "state")
    return pathlib.Path(base) / "attention" / "reflect-ledger.json"


def read_ledger(path):
    """台帳。無ければ空。在るのに読めない・形が違うなら ValueError——空として上書きすると、却下の記録が消えて
    同じ提案が戻る（台帳をキャッシュでなく状態の置き場に置いた狙いと逆になる）。"""
    path = pathlib.Path(path)
    if not path.exists():
        return {"schema": SCHEMA, "proposals": []}
    try:
        obj = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise ValueError(f"台帳 {path} が読めない（{e}）。直すか、別の名前に退けてから走らせ直す") from None
    if not isinstance(obj, dict) or not isinstance(obj.get("proposals"), list):
        raise ValueError(f"台帳 {path} の形が違う（proposals の並びが無い）。直すか、別の名前に退けてから走らせ直す")
    return obj


def write_ledger(path, ledger):
    catchup_html._write_atomic(pathlib.Path(path), json.dumps(ledger, ensure_ascii=False, indent=2) + "\n")


def decide(path, pid, status, note="", today=None):
    if status not in STATUSES:
        raise ValueError(f"状態は {'・'.join(STATUSES)} のどれか: {status}")
    ledger = read_ledger(path)
    for p in ledger["proposals"]:
        if p.get("id") == pid:
            p["status"] = status
            p["decided"] = (today or dt.date.today()).isoformat()
            if note:
                p["note"] = note
            write_ledger(path, ledger)
            return p
    raise ValueError(f"台帳に無い id: {pid}")


# ---- 材料 ------------------------------------------------------------------------


def repo_private(label):
    """そのリポジトリが非公開か。gh で使えるどのアカウントでも決められなければ、非公開として扱う（書かない側に倒す）。"""
    if "/" not in label:
        return True
    for login in gh_logins():
        token = (run(["gh", "auth", "token", "--hostname", "github.com", "--user", login]) or "").strip()
        raw = (run(["gh", "api", f"repos/{label}", "--jq", ".private"], env={**os.environ, "GH_TOKEN": token} if token else None) or "").strip()
        if raw in ("true", "false"):
            return raw == "true"
    return True


def privacy(commit_rows, gh_rows, ask=repo_private):
    """非公開のリポジトリの名前と、そこで出てきた PR・issue の番号。AI の文に書かせない（render が見る）。

    公開・非公開は、GitHub の動きの記録の public の印を先に使い、無いリポジトリだけ問い合わせる。"""
    known = {}
    for g in gh_rows:
        for r in g["events"]:
            if r.get("repo"):
                known.setdefault(r["repo"], bool(r.get("private")))
    for c in commit_rows:
        if c["repo"] not in known:
            known[c["repo"]] = ask(c["repo"])
        c["private"] = known[c["repo"]]
    repos = sorted(k for k, v in known.items() if v)
    numbers = {r["number"] for g in gh_rows for r in g["events"] if r.get("private") and r.get("number")}
    numbers |= {int(n) for c in commit_rows if c["private"] for x in c["commits"] for n in REF.findall(x["subject"])}
    return {"repos": repos, "numbers": sorted(numbers)}


# 非公開の番号を集める・フィールドの文から探す用。lib/ghtext.py の refs（コードと引用の中を数えない）より広く、
# 「PR 12」の形も、コードの中の #12 も当てる——ここは漏れを防ぐ側なので、外すより当て過ぎに倒す
REF = re.compile(r"(?:#|\b(?:PR|pr|issue|Issue)\s*#?)(\d+)")


def leaks(fields, data):
    """フィールドの文に、非公開のリポジトリの名前・番号が入っていれば、その誤りを並べる。"""
    priv = data.get("private") or {}
    texts = []

    def walk(v):
        if isinstance(v, str):
            texts.append(v)
        elif isinstance(v, list):
            for x in v:
                walk(x)
        elif isinstance(v, dict):
            for x in v.values():
                walk(x)
    walk(fields)
    text = "\n".join(texts)
    errs = []
    for repo in priv.get("repos") or []:
        names = {repo} | ({repo.split("/", 1)[1]} if "/" in repo and len(repo.split("/", 1)[1]) >= 4 else set())
        # 語の切れ目で当てる（名前が一般の語のとき、id の「unknown-one」のような語の一部に当てない）
        hit = sorted(n for n in names if re.search(r"(?<![\w-])" + re.escape(n) + r"(?![\w-])", text))
        if hit:
            errs.append(f"非公開のリポジトリの名前を書いている: {'、'.join(hit)}")
    nums = set(priv.get("numbers") or [])
    hit = sorted({int(n) for n in REF.findall(text)} & nums)
    if hit:
        errs.append("非公開のリポジトリの PR・issue の番号を書いている: " + "、".join(f"#{n}" for n in hit))
    if errs:
        errs.append("非公開のリポジトリの件は、番号・名前・件名でなく、何の作業か・どのくらいの量か・言いたいことで書く")
    return errs


def collect(spec, env=None, extra_dirs=(), with_github=True, today=None):
    env = dict(os.environ if env is None else env)
    first, last = period(spec, today)
    start, end = bounds(first, last)
    dirs = config_dirs(env, extra_dirs)
    human, background = sessions(dirs, start, end)
    cwds = sorted({s["cwd"] for s in human if s["cwd"]})
    asks, cmds = repeats(human)
    gh_unseen = []
    gh = github(start, end, gh_unseen) if with_github else []
    commit_rows = commits(cwds, start, end)
    private = privacy(commit_rows, gh, repo_private if with_github else (lambda _label: True))
    try:
        ledger, ledger_error = read_ledger(ledger_path(env)), None
    except ValueError as e:
        ledger, ledger_error = {"proposals": []}, str(e)
    return {
        "schema": SCHEMA,
        "period": {"spec": spec or "week", "start": first.isoformat(), "end": last.isoformat(), "days": (last - first).days + 1},
        "config_dirs": [str(d) for d in dirs],
        "counts": {
            "human_sessions": len(human), "asks": sum(len(s["asks"]) for s in human),
            "background_sessions": len(background),
            "human_output_tokens": sum(sum(s["out"].values()) for s in human),
            "background_output_tokens": sum(sum(s["out"].values()) for s in background),
            "human_output_by_model": tokens_by_model(human),
            "background_output_by_model": tokens_by_model(background),
        },
        "sessions": human_rows(human, (last - first).days + 1),
        "background": background_rows(background),
        "repeats": {"asks": asks, "commands": cmds},
        "commits": commit_rows,
        "github": gh,
        "private": private,
        "insights": insights(dirs, {s["id"] for s in human}),
        "assets": assets(dirs, cwds),
        "ledger": ledger["proposals"],
        "diary_dir": env.get(DIARY_ENV) or None,
        "unseen": [
            "サブエージェントの記録は、親の会話のトークンに足していない",
            *([ledger_error] if ledger_error else []),
            *([] if with_github else ["GitHub の動きは読んでいない（--no-github）"]),
            *gh_unseen,
        ],
    }


# ---- フィールドと描く ----------------------------------------------------------------------


def _str(v, at, errs, cap=None, empty=False):
    if not isinstance(v, str) or (not empty and not v.strip()):
        errs.append(f"{at} は空でない文字列")
        return
    if cap and len(v) > cap:
        errs.append(f"{at} は {cap} 字まで（{len(v)} 字）")


def _num(v, at, errs):
    if v is not None and (isinstance(v, bool) or not isinstance(v, (int, float)) or v < 0):
        errs.append(f"{at} は 0 以上の数か null")


def validate_fields(obj):
    """フィールドの JSON の誤りを並べる（空なら通る）。"""
    if not isinstance(obj, dict):
        return ["フィールドは {…} の JSON"]
    errs = []
    extra = set(obj) - {"headline", "proposals", "insights", "unseen", "diary"}
    if extra:
        errs.append("知らない key: " + ", ".join(sorted(extra)))
    _str(obj.get("headline"), "headline", errs, 200)
    props = obj.get("proposals")
    if not isinstance(props, list) or len(props) > PROPOSALS_CAP:
        errs.append(f"proposals は {PROPOSALS_CAP} 件までの並び")
        props = []
    ids = set()
    for i, p in enumerate(props):
        at = f"proposals[{i}]"
        if not isinstance(p, dict):
            errs.append(f"{at} は {{…}}")
            continue
        if not isinstance(p.get("id"), str) or not ID_RE.match(p["id"]):
            errs.append(f"{at}.id は [a-z0-9-] の 3〜60 字")
        elif p["id"] in ids:
            errs.append(f"{at}.id が重なっている: {p['id']}")
        else:
            ids.add(p["id"])
        if p.get("kind") not in KINDS:
            errs.append(f"{at}.kind は {'・'.join(KINDS)} のどれか")
        for k in ("title", "evidence", "where", "action"):
            _str(p.get(k), f"{at}.{k}", errs)
        if "existing" in p:
            _str(p.get("existing"), f"{at}.existing", errs, empty=True)
        _num(p.get("count"), f"{at}.count", errs)
        _num(p.get("minutes"), f"{at}.minutes", errs)
        extra = set(p) - {"id", "title", "kind", "evidence", "count", "minutes", "where", "existing", "action"}
        if extra:
            errs.append(f"{at} の知らない key: " + ", ".join(sorted(extra)))
    ins = obj.get("insights")
    if not isinstance(ins, list) or len(ins) > INSIGHTS_CAP:
        errs.append(f"insights は {INSIGHTS_CAP} 件までの並び")
        ins = []
    for i, x in enumerate(ins):
        at = f"insights[{i}]"
        if not isinstance(x, dict):
            errs.append(f"{at} は {{…}}")
            continue
        for k in ("title", "body", "evidence"):
            _str(x.get(k), f"{at}.{k}", errs)
    unseen = obj.get("unseen", [])
    if not isinstance(unseen, list) or not all(isinstance(u, str) for u in unseen):
        errs.append("unseen は文字列の並び")
    if "diary" in obj:
        _str(obj.get("diary"), "diary", errs, DIARY_CHARS)
    return errs


def score(p):
    c, m = p.get("count"), p.get("minutes")
    return (c * m) if isinstance(c, (int, float)) and isinstance(m, (int, float)) else None


def rank(proposals):
    """回数 × 手間の大きい順。両方有るものが先で、無いものは AI の並びのまま後ろ。"""
    scored = [p for p in proposals if score(p) is not None]
    rest = [p for p in proposals if score(p) is None]
    return sorted(scored, key=score, reverse=True) + rest


def merge_ledger(ledger, proposals, today):
    """新しい id を open で足し、前からの id は last_seen だけ進める。却下の id は落とし、落とした id を返す。"""
    known = {p.get("id"): p for p in ledger["proposals"]}
    kept, dropped = [], []
    for p in proposals:
        old = known.get(p["id"])
        if old and old.get("status") == "dismissed":
            dropped.append(p["id"])
            continue
        if old:
            old["last_seen"] = today
            old["title"] = p["title"]
        else:
            ledger["proposals"].append({"id": p["id"], "title": p["title"], "status": "open",
                                        "first_seen": today, "last_seen": today, "decided": None, "note": ""})
        kept.append({**p, "status": (old or {}).get("status", "open")})
    return kept, dropped


def page_path(data, root=None):
    root = pathlib.Path(root) if root else catchup_html.cache_root().parent / "reflect"
    p = data["period"]
    return root / f"{p['start']}_{p['end']}.html"


def build_html(template, data, fields):
    if DATA_SLOT not in template or TITLE_SLOT not in template:
        raise ValueError("雛形に差し込み口が無い")
    title = f"reflect {data['period']['start']}〜{data['period']['end']}"
    payload = catchup_html._script_json({"data": data, "fields": fields})
    # 差し込みは 1 回だけ。中身に差し込み口の字が有っても 2 度目の置き換えに巻き込まない
    head, tail = template.split(DATA_SLOT, 1)
    return head.replace(TITLE_SLOT, f"<title>{catchup_html._safe(title)}</title>", 1) + payload + tail


def write_diary(diary_dir, data, text):
    """1 日の期間なら、その日の日記の末尾のセクションを置き換える。戻り値は人に見せる 1 行。"""
    p = data["period"]
    if p["start"] != p["end"]:
        return "日記には書いていない（1 日の期間のときだけ書く）"
    folder = pathlib.Path(os.path.expanduser(diary_dir))
    if not folder.is_dir():
        return f"日記には書いていない（{DIARY_ENV} のフォルダが無い: {folder}）"
    path = folder / f"{p['start']}.md"
    try:
        body = path.read_text(encoding="utf-8") if path.exists() else f"# {p['start']}\n"
    except OSError as e:
        return f"日記には書いていない（読めない: {e}）"
    block = f"{DIARY_START}\n## 振り返り（自動）\n\n{text.strip()}\n{DIARY_END}\n"
    pat = re.compile(re.escape(DIARY_START) + r".*?" + re.escape(DIARY_END) + r"\n?", re.S)
    if pat.search(body):
        body = pat.sub(lambda _m: block, body, count=1)
    else:
        body = body.rstrip("\n") + "\n\n" + block
    catchup_html._write_atomic(path, body)
    return f"日記のセクションを書いた: {path}"


def render(data_path, fields_path, env=None, root=None, template=None, today=None):
    """ページを描き、台帳と日記を更新する。戻り値は (終了コード, 人に見せる行)。"""
    env = dict(os.environ if env is None else env)
    try:
        data = json.loads(pathlib.Path(data_path).read_text(encoding="utf-8"))
        fields = json.loads(pathlib.Path(fields_path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        return 2, [f"材料かフィールドの JSON が読めない（{e}）"]
    if not isinstance(data, dict) or data.get("schema") != SCHEMA:
        return 2, [f"材料の形が違う（schema {SCHEMA} の reflect.py --out で集め直す）"]
    errs = validate_fields(fields) or leaks(fields, data)
    if errs:
        return 2, ["フィールドの JSON を直す:"] + [f"- {e}" for e in errs]
    today_s = (today or dt.date.today()).isoformat()
    lpath = ledger_path(env)
    try:
        ledger = read_ledger(lpath)
    except ValueError as e:
        return 2, [str(e)]
    kept, dropped = merge_ledger(ledger, fields["proposals"], today_s)
    fields = {**fields, "proposals": rank(kept), "dropped": dropped}
    template = template if template is not None else TEMPLATE.read_text(encoding="utf-8")
    path = page_path(data, root)
    catchup_html._write_atomic(path, build_html(template, data, fields))
    write_ledger(lpath, ledger)
    lines = [str(path), fields["headline"]]
    if dropped:
        lines.append("却下済みなので落とした提案: " + ", ".join(dropped))
    diary_dir = env.get(DIARY_ENV)
    if fields.get("diary") and diary_dir:
        lines.append(write_diary(diary_dir, data, fields["diary"]))
    lines.append(catchup_html.open_in_vscode(path, env))
    return 0, lines


# ---- 入口 ------------------------------------------------------------------------


def main(argv=None):
    ap = argparse.ArgumentParser(description="/reflect の材料を集め、ページを描く。仕様は attention/docs/reflect-spec.md")
    ap.add_argument("period", nargs="?", default="week", help="today・yesterday・week（既定）・month・YYYY-MM-DD・YYYY-MM-DD..YYYY-MM-DD")
    ap.add_argument("--out", action="store_true", help="材料を JSON の file に書き、その path を出す")
    ap.add_argument("--render", nargs=2, metavar=("材料", "フィールド"), help="材料とフィールドの JSON からページを描く")
    ap.add_argument("--decide", nargs=2, metavar=("id", "状態"), help="台帳の提案の状態を変える（open・adopted・dismissed・held）")
    ap.add_argument("--note", default="", help="--decide に添える一言")
    ap.add_argument("--config-dir", action="append", default=[], help="読む設定のフォルダを足す（重ねてよい）")
    ap.add_argument("--no-github", action="store_true", help="GitHub を読まない")
    a = ap.parse_args(argv)
    if a.decide:
        try:
            p = decide(ledger_path(), a.decide[0], a.decide[1], a.note)
        except ValueError as e:
            print(e, file=sys.stderr)
            return 2
        print(f"{p['id']}: {p['status']}（{p['title']}）")
        return 0
    if a.render:
        code, lines = render(*a.render)
        print("\n".join(lines))
        return code
    try:
        data = collect(a.period, extra_dirs=a.config_dir, with_github=not a.no_github)
    except ValueError as e:
        print(e, file=sys.stderr)
        return 2
    text = json.dumps(data, ensure_ascii=False, indent=1)
    if not a.out:
        print(text)
        return 0
    out = catchup_html.cache_root().parent / "reflect" / "materials" / f"{data['period']['start']}_{data['period']['end']}.json"
    catchup_html._write_atomic(out, text + "\n")
    c = data["counts"]
    print(f"{out}\n人の会話 {c['human_sessions']} 本・発言 {c['asks']} 件・裏の会話 {c['background_sessions']} 本・"
          f"commit {sum(r['count'] for r in data['commits'])} 件・GitHub の動き {sum(g['count'] for g in data['github'])} 件")
    return 0


if __name__ == "__main__":
    sys.exit(main())
