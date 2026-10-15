"""/catchup の報告を 1 枚の HTML に描く部品。catchup.py の --render と --setup が使う。

〈なぜ HTML か〉端末の返答は 4,000〜28,000 字（中央値は約 15,000 字）で、その約 9 割は AI が機械の
枠を写しただけのコードだった（2026-10-15 実測）。AI が自分で書いた部分は約 1,000 字しかない。
写すだけの部分は機械が描けば割れず、AI の手間も減る。そこで、機械が決まった雛形
（attention/templates/catchup.html）に材料を流し込み、AI は小さな欄の JSON（headline・where・turn・
next・unseen・explain・figure）だけを書く。端末に出すのはページの path と 1 行の要約だけ。

〈置き場〉~/.cache/attention/catchup/<owner>-<repo>/<番号>.html。同じ件は上書きする。同じ置き場の
index.html が、ページごとに 1 行（件・件名・誰の番・次の一手・更新・相対リンク）を並べる。index は
各ページの頭に埋めた小さな JSON から毎回組み直す（並行して描くセッションが互いの行を消さない）。

〈開き方〉持ち主は VS Code の Remote-SSH で、拡張 Simple HTML Viewer を使って見る。描いた後、
ATTENTION_CATCHUP_OPEN=0 でなければ、生きている VS Code の窓のすべてで開く。開けなくても catchup は
失敗にしない（path は必ず出す）。

〈部品の出どころ〉差分の文字列から file ごとの増減と、指摘の行を含む hunk の抜粋を作る所は、
2026-10-15 に承認された試作（render.py）を写した。試作は catchup.py の文字の材料を読み直していたが、
ここは catchup.py が組んだ構造をそのまま受け取る。
"""

import datetime as dt
import glob
import hashlib
import html
import json
import os
import pathlib
import re
import shutil
import subprocess
import tempfile

SCHEMA = 1
HERE = pathlib.Path(__file__).resolve().parent
TEMPLATE = HERE.parent.parent / "templates" / "catchup.html"
DATA_SLOT = "/*__DATA__*/null"
INDEX_SLOT = "/*__INDEX__*/null"
TITLE_SLOT = "<title>catchup</title>"
INDEX_HEAD_BYTES = 16384  # ページの頭のこの量だけを読んで index の行を拾う（ページ全体は数百 KB ある）

OPEN_ENV = "ATTENTION_CATCHUP_OPEN"  # 0 なら描いた後に VS Code で開かない（works-dispatch が起こす会話など）
# 外部コマンドを無制限に待たない（catchup.py の GIT_TIMEOUT_SEC と同じ秒）。code --status は生きた窓なら数秒、
# 死んだ socket ならすぐ失敗する
CODE_TIMEOUT_SEC = 20
EXTENSION_ID = "austin-spagnolo.simple-html-viewer"
VIEW_TYPE = "simpleHtmlViewer.preview"
ASSOC_GLOB = "**/.cache/attention/catchup/**/*.html"
AUTO_REFRESH = ("simpleHtmlViewer.autoRefresh", "onFileChange")
ASSOC_KEY = "workbench.editorAssociations"

TONES = ("good", "bad")
NEXT_CAP = 6        # 次の一手の数の上限
EXPLAIN_CAP = 3     # 説明の段落の上限（材料が有れば 3 つ）


def cache_root(home=None):
    return pathlib.Path(home or pathlib.Path.home()) / ".cache" / "attention" / "catchup"


# ---- 差分（試作 render.py から写した） -------------------------------------------

HUNK = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@(.*)$")
GIT_HEAD = re.compile(r'^diff --git (?:"?a/(.*?)"? "?b/(.*?)"?)$')


def _unquote(p):
    """git の引用形の path（"a/\\346..."）を戻す。core.quotePath=false で取っていれば引用は付かない。"""
    if not p.startswith('"'):
        return p
    try:
        raw = p[1:-1].encode("latin-1").decode("unicode_escape").encode("latin-1")
        return raw.decode("utf-8")
    except (UnicodeError, ValueError):
        return p[1:-1]


def parse_diff(text):
    """unified diff を file ごと・hunk ごとに分ける。各行は (印, 前の行番号, 今の行番号, 中身)。"""
    files, f, h = [], None, None
    o = n = 0
    for raw in (text or "").splitlines():
        if raw.startswith("diff --git "):
            m = GIT_HEAD.match(raw)
            old, new = (m.group(1), m.group(2)) if m else ("", raw[len("diff --git "):])
            f = {"path": new, "old": old, "add": 0, "del": 0, "hunks": [], "head": [raw]}
            files.append(f)
            h = None
        elif f is None:
            continue
        elif h is None and not raw.startswith("@@"):
            f["head"].append(raw)
            if raw.startswith("+++ ") and raw != "+++ /dev/null":
                p = _unquote(raw[4:].strip())
                f["path"] = p[2:] if p.startswith("b/") else p
            elif raw.startswith("--- ") and raw != "--- /dev/null" and not f["old"]:
                p = _unquote(raw[4:].strip())
                f["old"] = p[2:] if p.startswith("a/") else p
        elif raw.startswith("@@"):
            m = HUNK.match(raw)
            if not m:
                continue
            h = {"o": int(m.group(1)), "n": int(m.group(3)), "ctx": m.group(5).strip(), "rows": []}
            f["hunks"].append(h)
            o, n = h["o"], h["n"]
        elif raw.startswith("\\"):
            continue
        elif raw.startswith("diff ") or raw.startswith("index "):
            continue
        else:
            mark, body = raw[:1] or " ", raw[1:]
            if mark == "+":
                h["rows"].append(("+", None, n, body))
                n += 1
                f["add"] += 1
            elif mark == "-":
                h["rows"].append(("-", o, None, body))
                o += 1
                f["del"] += 1
            else:
                h["rows"].append((" ", o, n, body))
                o += 1
                n += 1
    return files


def anchor(path):
    """GitHub の Files changed の file の飛び先は `#diff-<path の sha256>`。"""
    return "diff-" + hashlib.sha256(path.encode("utf-8")).hexdigest()


def summary(files, since_paths=()):
    return [{"path": f["path"], "add": f["add"], "del": f["del"], "anchor": anchor(f["path"]),
             "since": f["path"] in since_paths} for f in files]


def excerpt(f, line, before=5, after=4):
    """指摘の行を含む hunk から、その行の前後を抜いた小さな unified diff を作る（無ければ None）。
    GitHub のレビューのスレッドが出す断片と同じ形。"""
    for h in f["hunks"]:
        idx = next((i for i, r in enumerate(h["rows"]) if r[2] == line), None)
        if idx is None:
            continue
        rows = h["rows"][max(0, idx - before):idx + after + 1]
        o0 = next((r[1] for r in rows if r[1] is not None), h["o"])
        n0 = next((r[2] for r in rows if r[2] is not None), h["n"])
        oc = sum(1 for r in rows if r[0] != "+")
        nc = sum(1 for r in rows if r[0] != "-")
        body = "\n".join(r[0] + r[3] for r in rows)
        return "\n".join(f["head"] + [f"@@ -{o0},{oc} +{n0},{nc} @@ {h['ctx']}", body]) + "\n"
    return None


def context_excerpt(path, lines, line, before=5, after=4):
    """差分に無い行への指摘は、head の行を変わっていない行だけの断片にして見せる（行番号は head のもの）。"""
    if not lines or not line or line > len(lines):
        return None
    lo, hi = max(1, line - before), min(len(lines), line + after)
    body = "\n".join(" " + lines[k - 1] for k in range(lo, hi + 1))
    n = hi - lo + 1
    return (f"diff --git a/{path} b/{path}\n--- a/{path}\n+++ b/{path}\n"
            f"@@ -{lo},{n} +{lo},{n} @@\n{body}\n")


def filter_diff(text, paths):
    """diff の文字列から、paths の file の塊だけを残す。"""
    want = set(paths)
    keep = []
    for block in re.split(r"(?m)^(?=diff --git )", text or ""):
        if not block.startswith("diff --git "):
            continue
        got = parse_diff(block)
        if got and (got[0]["path"] in want or got[0]["old"] in want):
            keep.append(block)
    return "".join(keep)


def view(view_id, name, text, url="", note="", since_paths=()):
    """変更の節の 1 つの見え方（前回から・PR 全体・未コミットなど）。"""
    return {"id": view_id, "name": name, "text": text, "url": url, "note": note,
            "files": summary(parse_diff(text), since_paths)}


# ---- AI の欄 -----------------------------------------------------------------

FIELD_KEYS = ("headline", "where", "turn", "next", "unseen", "explain", "figure", "title")


def validate_fields(obj, need_title=False):
    """AI が書いた欄を確かめる。直す所を日本語で 1 件 1 行に並べて返す（空なら通った）。"""
    errs = []
    if not isinstance(obj, dict):
        return ["欄の JSON は {…}（オブジェクト）にする"]
    for k in obj:
        if k not in FIELD_KEYS:
            errs.append(f"知らない欄 {k}（使える欄は {'・'.join(FIELD_KEYS)}）")

    def text(k, required=True):
        v = obj.get(k)
        if v is None:
            if required:
                errs.append(f"{k} が無い（文字列で書く）")
            return
        if not isinstance(v, str) or not v.strip():
            errs.append(f"{k} は空でない文字列にする")

    text("headline")
    text("where")
    text("turn")
    text("title", required=need_title)

    def str_list(k, lo, hi, required):
        v = obj.get(k)
        if v is None:
            if required:
                errs.append(f"{k} が無い（[\"…\", …] の形で書く）")
            return
        if not isinstance(v, list) or not all(isinstance(s, str) and s.strip() for s in v):
            errs.append(f"{k} は空でない文字列の並び（[\"…\", …]）にする")
            return
        if not lo <= len(v) <= hi:
            errs.append(f"{k} は {lo}〜{hi} 個にする（今 {len(v)} 個）")

    str_list("next", 1, NEXT_CAP, True)
    str_list("unseen", 0, 20, False)
    str_list("explain", 0, EXPLAIN_CAP, False)

    fig = obj.get("figure")
    if fig is not None:
        errs.extend(_figure_errors(fig))
    return errs


def _figure_errors(fig):
    errs = []
    if not isinstance(fig, dict):
        return ["figure は {\"caption\": …, \"rows\": […]}（オブジェクト）か null にする"]
    for k in fig:
        if k not in ("caption", "rows"):
            errs.append(f"figure に知らない欄 {k}（使える欄は caption・rows）")
    if "caption" in fig and not isinstance(fig["caption"], str):
        errs.append("figure.caption は文字列にする")
    rows = fig.get("rows")
    if not isinstance(rows, list) or not rows:
        return errs + ["figure.rows は 1 つ以上の行（{\"label\", \"steps\", \"notes\"}）の並びにする"]
    for i, r in enumerate(rows):
        at = f"figure.rows[{i}]"
        if not isinstance(r, dict):
            errs.append(f"{at} は {{\"label\", \"steps\", \"notes\"}}（オブジェクト）にする")
            continue
        for k in r:
            if k not in ("label", "steps", "notes"):
                errs.append(f"{at} に知らない欄 {k}（使える欄は label・steps・notes）")
        if not isinstance(r.get("label"), str) or not r["label"].strip():
            errs.append(f"{at}.label は空でない文字列にする（例: 変更前・変更後）")
        steps = r.get("steps")
        if not isinstance(steps, list) or not steps:
            errs.append(f"{at}.steps は 1 つ以上の箱（{{\"text\", \"tone\"}}）の並びにする")
            steps = []
        for j, s in enumerate(steps):
            sat = f"{at}.steps[{j}]"
            if not isinstance(s, dict) or not isinstance(s.get("text"), str) or not s["text"].strip():
                errs.append(f"{sat} は {{\"text\": \"…\"}} の形にする（text は空でない文字列）")
                continue
            errs.extend(_extra_and_tone(s, sat, ("text", "tone")))
        notes = r.get("notes", [])
        if not isinstance(notes, list):
            errs.append(f"{at}.notes は注記（{{\"at\", \"text\", \"tone\"}}）の並びにする")
            continue
        for j, nt in enumerate(notes):
            nat = f"{at}.notes[{j}]"
            if not isinstance(nt, dict) or not isinstance(nt.get("text"), str) or not nt["text"].strip():
                errs.append(f"{nat} は {{\"at\": 箱の番号, \"text\": \"…\"}} の形にする")
                continue
            errs.extend(_extra_and_tone(nt, nat, ("at", "text", "tone")))
            a = nt.get("at")
            if not isinstance(a, int) or isinstance(a, bool) or not 0 <= a < max(1, len(steps)):
                errs.append(f"{nat}.at は注記を付ける箱の番号（0〜{max(0, len(steps) - 1)}）にする")
    return errs


def _extra_and_tone(obj, at, allowed):
    errs = [f"{at} に知らない欄 {k}（使える欄は {'・'.join(allowed)}）" for k in obj if k not in allowed]
    if "tone" in obj and obj["tone"] not in TONES:
        errs.append(f"{at}.tone は good か bad（色を付けないなら書かない）")
    return errs


# ---- ページを書く ----------------------------------------------------------------


def _safe(s):
    return re.sub(r"[^A-Za-z0-9._-]+", "_", s).strip("_") or "_"


def page_rel(data, fields):
    """置き場からの相対 path（index のリンクにそのまま使う）。材料が無い（会話の話題）なら件名から。"""
    if data and data.get("page"):
        return data["page"] + ".html"
    title = (fields or {}).get("title") or ""
    return "topics/" + hashlib.sha1(title.encode("utf-8")).hexdigest()[:10] + ".html"


def index_entry(data, fields, rel, now):
    head = (data or {}).get("head") or {}
    repo = (data or {}).get("repo") or ""
    ref = head.get("ref") or ""
    turn = head.get("turn") or {}
    # 待ちは誰を待っているかまで（「待ち」だけでは一覧で次の手が決まらない）
    label = turn.get("detail") if turn.get("kind") == "wait" and turn.get("detail") else turn.get("label")
    return {"page": rel, "repo": repo, "ref": ref,
            "title": head.get("title") or (fields or {}).get("title") or "",
            "turn": label or "", "turn_kind": turn.get("kind") or "",
            "next": ((fields or {}).get("next") or [""])[0], "updated": now.isoformat(timespec="seconds")}


def _script_json(obj):
    """<script type="application/json"> に埋める JSON。`<` を全部 \\u003c にする——`</script>` や `<!--` で
    script の中身が閉じない（JSON の構文に `<` は無いので、文字列の中だけが変わる）。"""
    return json.dumps(obj, ensure_ascii=False).replace("<", "\\u003c")


def build_html(template, data, fields, entry):
    title = " ".join(x for x in (entry["ref"], entry["title"]) if x) or "catchup"
    for slot in (DATA_SLOT, INDEX_SLOT, TITLE_SLOT):
        if slot not in template:
            raise ValueError(f"雛形に差し込み口 {slot} が無い")
    # 3 つを 1 回の走査で差し込む。順に replace すると、先に入れた件名などに後の差し込み口の文字列が
    # 含まれていたとき、そちらに当たって本物の口が空のまま残る
    filled = {TITLE_SLOT: f"<title>{html.escape(title)}</title>", INDEX_SLOT: _script_json(entry),
              DATA_SLOT: _script_json({"data": data, "fields": fields})}
    pattern = re.compile("|".join(re.escape(slot) for slot in filled))
    return pattern.sub(lambda m: filled.pop(m.group(0), m.group(0)), template)


def _write_atomic(path, text):
    """同じ階層の一時ファイルに書いてから置き換える。拡張の autoRefresh（onFileChange）が書きかけを読まない。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix="." + path.name + ".", dir=str(path.parent))
    try:
        with open(fd, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def summary_line(entry, fields):
    head = " ".join(x for x in (entry["ref"], entry["title"]) if x)
    if len(head) > 48:
        head = head[:47] + "…"
    turn = f" — {entry['turn']}" if entry["turn"] else ""
    nxt = (fields.get("next") or [""])[0]
    return f"{head}{turn}。次: {nxt}"


def write_page(data, fields, root=None, template=None, now=None):
    """ページを書き、index を組み直す。戻り値は (ページの path, 1 行の要約)。"""
    root = pathlib.Path(root) if root else cache_root()
    now = now or dt.datetime.now().astimezone()
    template = template if template is not None else TEMPLATE.read_text(encoding="utf-8")
    rel = page_rel(data, fields)
    entry = index_entry(data, fields, rel, now)
    path = root / rel
    _write_atomic(path, build_html(template, data, fields, entry))
    rebuild_index(root)
    return path, summary_line(entry, fields)


# ---- index ---------------------------------------------------------------------

ENTRY_RE = re.compile(r'<script type="application/json" id="catchup-index">(.*?)</script>', re.S)


def read_entry(path):
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            head = f.read(INDEX_HEAD_BYTES)
    except OSError:
        return None
    m = ENTRY_RE.search(head)
    if not m:
        return None
    try:
        e = json.loads(m.group(1))
    except ValueError:
        return None
    return e if isinstance(e, dict) and e.get("page") else None


def collect_entries(root):
    """置き場の下のページ（1 階層下の *.html）から index の行を拾う。頭に行の無いページ（試しの見本など）は並べない。"""
    root = pathlib.Path(root)
    out = []
    for p in sorted(root.glob("*/*.html")):
        e = read_entry(p)
        if e:
            e["page"] = p.relative_to(root).as_posix()  # 動かされたページでも今の置き場を指す
            out.append(e)
    out.sort(key=lambda e: e.get("updated") or "", reverse=True)
    return out


def rebuild_index(root):
    root = pathlib.Path(root)
    path = root / "index.html"
    _write_atomic(path, index_html(collect_entries(root)))
    return path


INDEX_CSS = """
:root { --bg: #ffffff; --muted-bg: #f6f8fa; --fg: #1f2328; --muted: #59636e; --accent: #0969da;
  --border: #d1d9e0; --severe: #bc4c00; --severe-bg: #fff1e5; --done: #8250df;
  --font: -apple-system, BlinkMacSystemFont, "Segoe UI", "Noto Sans", Helvetica, Arial, "Hiragino Sans", "Noto Sans JP", "Meiryo", sans-serif;
  --mono: ui-monospace, SFMono-Regular, "SF Mono", Menlo, Consolas, "Liberation Mono", monospace; }
@media (prefers-color-scheme: dark) { :root:not([data-theme="light"]):not(:has(body.vscode-light)) {
  --bg: #0d1117; --muted-bg: #151b23; --fg: #f0f6fc; --muted: #9198a1; --accent: #4493f8; --border: #3d444d;
  --severe: #db6d28; --severe-bg: #db6d281a; --done: #ab7df8; color-scheme: dark; } }
:root[data-theme="dark"], :root:has(body.vscode-dark) { --bg: #0d1117; --muted-bg: #151b23; --fg: #f0f6fc;
  --muted: #9198a1; --accent: #4493f8; --border: #3d444d; --severe: #db6d28; --severe-bg: #db6d281a; --done: #ab7df8;
  color-scheme: dark; }
* { box-sizing: border-box; }
body { margin: 0; background: var(--bg); color: var(--fg); font: 14px/1.5 var(--font); }
main { max-width: 1012px; margin: 0 auto; padding: 24px 16px 64px; }
h1 { font-size: 20px; font-weight: 600; margin: 0 0 4px; }
.sub { color: var(--muted); font-size: 13px; margin: 0 0 16px; }
a { color: var(--accent); text-decoration: none; } a:hover { text-decoration: underline; }
ul { list-style: none; margin: 0; padding: 0; border: 1px solid var(--border); border-radius: 6px; }
li { display: grid; grid-template-columns: minmax(0, 1fr) auto; gap: 2px 12px; padding: 10px 16px; }
li + li { border-top: 1px solid var(--border); }
.ref { font: 12px/1.6 var(--mono); color: var(--muted); }
.title { font-weight: 600; overflow-wrap: anywhere; }
.next { grid-column: 1 / -1; color: var(--muted); font-size: 13px; overflow-wrap: anywhere; }
.when { color: var(--muted); font-size: 12px; white-space: nowrap; text-align: right; }
.turn { display: inline-block; font-size: 12px; line-height: 20px; padding: 0 8px; border-radius: 2em;
  border: 1px solid var(--border); color: var(--muted); margin-right: 6px; white-space: nowrap; }
.turn.mine { background: var(--severe); border-color: transparent; color: #fff; font-weight: 600; }
.turn.done { color: var(--done); border-color: var(--done); }
.empty { color: var(--muted); }
"""


def index_html(entries):
    def row(e):
        cls = {"mine": " mine", "done": " done"}.get(e.get("turn_kind"), "")
        ref = " ".join(x for x in (e.get("repo"), e.get("ref")) if x)
        turn = f'<span class="turn{cls}">{html.escape(e["turn"])}</span>' if e.get("turn") else ""
        when = (e.get("updated") or "")[:16].replace("T", " ")
        return (f'<li><div><div class="ref">{html.escape(ref)}</div>'
                f'<a class="title" href="{html.escape(e["page"], quote=True)}">{html.escape(e.get("title") or e["page"])}</a></div>'
                f'<div class="when">{turn}{html.escape(when)}</div>'
                f'<div class="next">次: {html.escape(e.get("next") or "")}</div></li>')
    body = ("<ul>" + "".join(row(e) for e in entries) + "</ul>") if entries else \
        '<p class="empty">まだページが無い。/catchup を打つと、ここに 1 件ずつ並ぶ。</p>'
    return ("<!doctype html>\n<html lang=\"ja\">\n<head>\n<meta charset=\"utf-8\">\n"
            "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">\n"
            f"<title>catchup の一覧</title>\n<style>{INDEX_CSS}</style>\n</head>\n<body>\n<main>\n"
            f"<h1>catchup の一覧</h1>\n<p class=\"sub\">{len(entries)} 件。新しく描いた順。"
            "同じ件は描き直すたびに上書きされる。</p>\n"
            f"{body}\n</main>\n</body>\n</html>\n")


# ---- VS Code で開く -------------------------------------------------------------


def run_code(args, env):
    """code を呼んで終了コードを返す。起動できない・時間内に返らないなら None。"""
    try:
        r = subprocess.run(args, env=env, capture_output=True, encoding="utf-8", errors="replace",  # noqa: S603 — code は which か固定の置き場で解決
                           timeout=CODE_TIMEOUT_SEC, stdin=subprocess.DEVNULL)
    except (OSError, subprocess.SubprocessError):
        return None
    return r.returncode


def code_cli(home=None, which=shutil.which):
    """VS Code の CLI。PATH の code、無ければ Remote の server が置いた remote-cli の code のうち新しいもの。"""
    exe = which("code")
    if exe:
        return exe
    home = pathlib.Path(home or pathlib.Path.home())
    found = glob.glob(str(home / ".vscode-server" / "cli" / "servers" / "*" / "server" / "bin" / "remote-cli" / "code"))
    found += glob.glob(str(home / ".vscode-server" / "bin" / "*" / "bin" / "remote-cli" / "code"))
    return max(found, key=_mtime) if found else None


def _mtime(p):
    try:
        return os.path.getmtime(p)
    except OSError:
        return 0.0


def ipc_sockets(env):
    """VS Code の窓が CLI に開く socket（vscode-ipc-*.sock）を新しい順に。TMPDIR（無ければ /tmp）と
    XDG_RUNTIME_DIR を探し、環境の VSCODE_IPC_HOOK_CLI も候補に入れる（古いことがあるので生死は別に見る）。"""
    dirs = [env.get("TMPDIR") or "/tmp", env.get("XDG_RUNTIME_DIR") or ""]
    found = set()
    for d in dirs:
        if d:
            found.update(glob.glob(os.path.join(d, "vscode-ipc-*.sock")))
    hook = env.get("VSCODE_IPC_HOOK_CLI")
    if hook and os.path.exists(hook):
        found.add(hook)
    return sorted(found, key=_mtime, reverse=True)


def live_sockets(cli, socks, env, run=run_code):
    """`code --status` が 0 で返る socket だけ。herdr などの中の会話は、起こした時の古い VSCODE_IPC_HOOK_CLI を
    継いでいる。持ち主が見ていた窓は 2 つの生きた socket の古い方で答えた（2026-10-15 実測）ので、全部を試す。"""
    return [s for s in socks if run([cli, "--status"], {**env, "VSCODE_IPC_HOOK_CLI": s}) == 0]


def open_in_vscode(path, env=None, home=None, run=run_code, which=shutil.which):
    """生きている窓のすべてで path を開く。戻り値は人に見せる 1 行（開けなくても例外にしない）。"""
    env = dict(os.environ if env is None else env)
    if env.get(OPEN_ENV) == "0":
        return f"開いていない（{OPEN_ENV}=0）"
    try:
        cli = code_cli(home, which)
        if not cli:
            return "開いていない（VS Code の CLI の code が見つからない）"
        live = live_sockets(cli, ipc_sockets(env), env, run)
        if not live:
            return "開いていない（VS Code が繋がっていない。path を開く）"
        ok = sum(1 for s in live if run([cli, "--reuse-window", str(path)], {**env, "VSCODE_IPC_HOOK_CLI": s}) == 0)
        return f"VS Code の窓 {ok} 個で開いた" if ok else "開けなかった（code --reuse-window が失敗した）"
    except Exception as e:  # noqa: BLE001 — 開けないことで catchup を落とさない
        return f"開けなかった（{type(e).__name__}: {e}）"


# ---- 準備（/catchup setup） ------------------------------------------------------


def settings_path(home=None):
    return pathlib.Path(home or pathlib.Path.home()) / ".vscode-server" / "data" / "Machine" / "settings.json"


def _strip_jsonc(text):
    """// と /* */ の注記と、閉じ括弧の前の余分な , を落とす（文字列の中は触らない）。戻り値は (JSON, 注記が有ったか)。"""
    out, i, n, comments = [], 0, len(text), False
    while i < n:
        c = text[i]
        if c == '"':
            j = i + 1
            while j < n and text[j] != '"':
                j += 2 if text[j] == "\\" else 1
            out.append(text[i:j + 1])
            i = j + 1
        elif text.startswith("//", i):
            comments = True
            while i < n and text[i] != "\n":
                i += 1
        elif text.startswith("/*", i):
            comments = True
            j = text.find("*/", i + 2)
            i = n if j < 0 else j + 2
        else:
            out.append(c)
            i += 1
    return _drop_trailing_commas("".join(out)), comments


def _drop_trailing_commas(text):
    """閉じ括弧の前の余分な , を、文字列の外でだけ落とす（文字列の中の ",]" を壊さない）。注記を落とした後に呼ぶ。"""
    out, i, n = [], 0, len(text)
    while i < n:
        c = text[i]
        if c == '"':
            j = i + 1
            while j < n and text[j] != '"':
                j += 2 if text[j] == "\\" else 1
            out.append(text[i:j + 1])
            i = j + 1
            continue
        if c == ",":
            j = i + 1
            while j < n and text[j] in " \t\r\n":
                j += 1
            if j < n and text[j] in "}]":
                i += 1
                continue
        out.append(c)
        i += 1
    return "".join(out)


def settings_gaps(obj):
    """足りない設定を人の言葉で並べる（空なら揃っている）。"""
    gaps = []
    assoc = obj.get(ASSOC_KEY)
    if not isinstance(assoc, dict) or assoc.get(ASSOC_GLOB) != VIEW_TYPE:
        gaps.append(f'{ASSOC_KEY} の "{ASSOC_GLOB}": "{VIEW_TYPE}"')
    if obj.get(AUTO_REFRESH[0]) != AUTO_REFRESH[1]:
        gaps.append(f'"{AUTO_REFRESH[0]}": "{AUTO_REFRESH[1]}"')
    return gaps


def read_settings(path):
    """(設定の dict か None, 注記が有ったか, 読めない理由)。file が無ければ空の dict。"""
    path = pathlib.Path(path)
    if not path.exists():
        return {}, False, ""
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as e:
        return None, False, f"読めない（{e}）"
    text, comments = _strip_jsonc(raw)
    try:
        obj = json.loads(text) if text.strip() else {}
    except ValueError as e:
        return None, comments, f"JSON として読めない（{e}）"
    if not isinstance(obj, dict):
        return None, comments, "中身が {…} でない"
    return obj, comments, ""


def merge_settings(path, now=None):
    """2 つの設定を足す。他の key は消さない。書く前に同じ階層へ控えを置く。戻り値は人に見せる行の並び。
    注記（// や /* */）の有る file は書き直すと注記が消えるので、書かずに足す行だけを示す。"""
    path = pathlib.Path(path)
    obj, comments, why = read_settings(path)
    if obj is None:
        return [f"設定 {path} は{why}ので触らない。手で足す: " + "、".join(settings_gaps({}))], False
    gaps = settings_gaps(obj)
    if not gaps:
        return [f"設定は揃っている（{path}）"], True
    if comments:
        return [f"設定 {path} に注記が有るので書き直さない（書くと注記が消える）。手で足す: " + "、".join(gaps)], False
    if isinstance(obj.get(ASSOC_KEY), list):
        return [f"設定 {path} の {ASSOC_KEY} が古い形（並び）なので触らない。手で足す: " + "、".join(gaps)], False
    lines = []
    if path.exists():
        stamp = (now or dt.datetime.now()).strftime("%Y%m%d-%H%M%S")
        backup = path.with_name(f"{path.name}.bak-{stamp}")
        shutil.copy2(path, backup)
        lines.append(f"設定の控えを {backup} に置いた")
    assoc = obj.get(ASSOC_KEY) if isinstance(obj.get(ASSOC_KEY), dict) else {}
    assoc[ASSOC_GLOB] = VIEW_TYPE
    obj[ASSOC_KEY] = assoc
    obj[AUTO_REFRESH[0]] = AUTO_REFRESH[1]
    _write_atomic(path, json.dumps(obj, ensure_ascii=False, indent=4) + "\n")
    lines.append(f"設定 {path} に足した: " + "、".join(gaps))
    return lines, True


def extension_dirs(home=None):
    home = pathlib.Path(home or pathlib.Path.home())
    return sorted(glob.glob(str(home / ".vscode-server" / "extensions" / f"{EXTENSION_ID}-*")))


def setup(check=False, home=None, env=None, root=None, run=run_code, which=shutil.which, now=None):
    """準備を確かめ、check でなければ足りない物を入れる。戻り値は (終了コード, 人に見せる行)。
    終了コードは、全部揃えば 0、足りない物が残れば 1。"""
    env = dict(os.environ if env is None else env)
    did, missing = [], []
    cli = code_cli(home, which)
    live = live_sockets(cli, ipc_sockets(env), env, run) if cli else []
    if not cli:
        missing.append("VS Code の CLI（code）が見つからない。VS Code の Remote-SSH で一度このマシンに繋ぐ")
    elif not live:
        missing.append("生きている VS Code の窓が無い（VS Code が繋がっていない）。繋いでから /catchup setup をもう一度")
    else:
        did.append(f"VS Code の窓 {len(live)} 個が繋がっている（{live[0]} ほか）")

    ext = extension_dirs(home)
    if ext:
        did.append(f"拡張 Simple HTML Viewer は入っている（{os.path.basename(ext[-1])}）")
    elif check or not live:
        missing.append(f"拡張 Simple HTML Viewer が入っていない（code --install-extension {EXTENSION_ID}）")
    else:
        rc = run([cli, "--install-extension", EXTENSION_ID], {**env, "VSCODE_IPC_HOOK_CLI": live[0]})
        if rc == 0:
            did.append(f"拡張 Simple HTML Viewer を入れた（{EXTENSION_ID}）")
        else:
            missing.append(f"拡張 Simple HTML Viewer を入れられなかった（code --install-extension {EXTENSION_ID} が失敗）")

    spath = settings_path(home)
    if check:
        obj, _, why = read_settings(spath)
        gaps = settings_gaps(obj) if obj is not None else [f"設定 {spath} が{why}"]
        if gaps:
            missing.append(f"設定 {spath} に足りない: " + "、".join(gaps))
        else:
            did.append(f"設定は揃っている（{spath}）")
    else:
        lines, ok = merge_settings(spath, now)
        (did if ok else missing).extend(lines)

    if not check:
        root = pathlib.Path(root) if root else cache_root(home)
        sample = root / "setup-sample.html"
        template = TEMPLATE.read_text(encoding="utf-8")
        entry = index_entry(SAMPLE_DATA, SAMPLE_FIELDS, sample.name, now or dt.datetime.now().astimezone())
        _write_atomic(sample, build_html(template, SAMPLE_DATA, SAMPLE_FIELDS, dict(entry, page="")))
        rebuild_index(root)
        did.append(f"見本のページを {sample} に描いた")
        if live:
            opened = sum(1 for s in live
                         if run([cli, "--reuse-window", str(sample)], {**env, "VSCODE_IPC_HOOK_CLI": s}) == 0)
            did.append(f"見本を VS Code の窓 {opened} 個で開いた（色付きのページが出れば準備は済み。"
                       "ソースのまま出たら、拡張が入っていないか設定が効いていない）")
    lines = ["した・確かめたこと:"] + [f"  - {x}" for x in did]
    lines += (["まだ足りないもの:"] + [f"  - {x}" for x in missing]) if missing else ["まだ足りないもの: なし"]
    return (1 if missing else 0), lines


# 見本のページ（/catchup setup が描く）。実在の件ではない
SAMPLE_DIFF = """diff --git a/app/retry.py b/app/retry.py
--- a/app/retry.py
+++ b/app/retry.py
@@ -10,7 +10,9 @@ def exit_code(err):
     \"\"\"終わるときの数字を決める。\"\"\"
-    if isinstance(err, TimeoutError):
+    while err is not None:
+        if isinstance(err, TimeoutError):
+            return 4
+        err = err.__cause__
-        return 4
     return 1
"""
SAMPLE_DATA = {
    "schema": SCHEMA, "kind": "pr", "page": "", "repo": "example/app", "generated": "",
    "head": {"kind": "pr", "ref": "#1", "title": "見本: 包まれた切断も終了コード 4 にする", "url": "",
             "state": "open", "draft": False, "author": "hanako", "role": "レビュアー",
             "turn": {"kind": "mine", "label": "私の番", "reasons": ["レビュー依頼が私に来ている"], "detail": ""},
             "files": 1, "additions": 3, "deletions": 1, "notes": ["これは /catchup setup が描いた見本"]},
    "anchor": "mine", "anchor_label": "前回から",
    "mine": {"when": "10-15 09:41", "min": 0, "who": "私", "kind": "スレッド app/retry.py:12（未解決）", "cat": "spoken",
             "sha": "", "text": "包まれた例外も見てほしい"},
    "events": [{"when": "10-15 15:32", "min": 351, "who": "hanako", "kind": "push", "cat": "push", "sha": "4cf1df3",
                "text": "4cf1df3 原因の連鎖をたどる"},
               {"when": "10-15 15:44", "min": 363, "who": "hanako", "kind": "スレッド app/retry.py:12（未解決）",
                "cat": "spoken", "sha": "", "text": "直しました"}],
    "status": [{"key": "threads", "label": "未解決の会話", "value": "1 件 · 私が返す番 1 件", "tone": "mine"},
               {"key": "ci", "label": "CI", "value": "全 pass（緑 3）", "tone": "ok"},
               {"key": "approval", "label": "承認", "value": "まだ承認されていない（REVIEW_REQUIRED）", "tone": "warn"}],
    "links": {"closes": [], "stacked": [], "refs": []},
    "unseen": ["GitHub の外（チャット・口頭・メール）でのやり取り"],
    "threads": [{"path": "app/retry.py", "line": 12, "my_turn": True, "who": "hanako", "when": "10-15 15:44",
                 "quote": "直しました。原因の連鎖をたどります。", "mine": {"when": "10-15 09:41", "quote": "包まれた例外も見てほしい"},
                 "href": "", "outdated": False, "excerpt": SAMPLE_DIFF, "changed": True}],
    "ci": [], "local": "", "scale": "1 ファイル +3/-1",
    "views": [{"id": "all", "name": "PR 全体（1 files）", "text": SAMPLE_DIFF, "url": "", "note": "",
               "files": summary(parse_diff(SAMPLE_DIFF))}],
}
SAMPLE_FIELDS = {
    "headline": "見本の #1 は私が返す番。私の指摘に、作者が直して返してきた。",
    "where": "09:41 に包まれた例外も見てほしいと指摘した。作者が 15:32 に push し、15:44 に返信した。",
    "turn": "止めているのは私の返事だけ。CI は緑、承認はまだ。",
    "next": ["差分を読み、包まれた切断が 4 になるかを確かめる", "返信して解決にする"],
    "unseen": ["これは見本で、実在の件ではない"],
    "explain": ["このページは /catchup setup が描いた見本です。色が付いて差分が出ていれば、拡張と設定が効いています。"],
    "figure": {"caption": "見本の図", "rows": [
        {"label": "変更前", "steps": [{"text": "例外"}, {"text": "1 段だけ見る", "tone": "bad"}, {"text": "1 で終わる"}]},
        {"label": "変更後", "steps": [{"text": "例外"}, {"text": "原因の連鎖をたどる", "tone": "good"}, {"text": "4 で終わる"}]}]},
}


def save_data(data, stem="catchup-data"):
    """catchup.py が組んだ材料を一時ファイル（0600）に書き、path を返す。--out の報告と同じ置き場。"""
    fd, path = tempfile.mkstemp(prefix=f"{stem}-{dt.datetime.now():%Y%m%d-%H%M%S}-", suffix=".json")
    with open(fd, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)
    return path
