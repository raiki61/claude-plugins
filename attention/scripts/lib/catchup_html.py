"""/catchup の報告を 1 枚の HTML に描く部品。catchup.py の --render と --setup が使う。

〈なぜ HTML か〉端末の返答は 4,000〜28,000 字（中央値は約 15,000 字）で、その約 9 割は AI が機械の
枠を写しただけのコードだった（2026-10-15 実測）。AI が自分で書いた部分は約 1,000 字しかない。
写すだけの部分は機械が描けば割れず、AI の手間も減る。そこで、機械が決まった雛形
（attention/templates/catchup.html）に材料を流し込み、AI は小さなフィールドの JSON（headline・where・turn・
next・unseen・explain・figure）だけを書く。端末に出すのはページの path と 1 行の要約だけ。

〈置き場〉~/.cache/attention/catchup/<owner>-<repo>/<番号>.html。同じ件は上書きする。同じ置き場の
index.html が、ページごとに 1 行（件・件名・誰のターン・次の一手・更新・相対リンク）を並べる。index は
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
import html.parser
import json
import os
import pathlib
import re
import shutil
import subprocess
import tempfile

import changemap  # 同じ lib/ にある。呼び手（catchup.py）が lib/ を sys.path に足してから読む

SCHEMA = 1
HERE = pathlib.Path(__file__).resolve().parent
TEMPLATE = HERE.parent.parent / "templates" / "catchup.html"
DATA_SLOT = "/*__DATA__*/null"
INDEX_SLOT = "/*__INDEX__*/null"
TITLE_SLOT = "<title>catchup</title>"
INDEX_HEAD_BYTES = 16384  # ページの頭のこの量だけを読んで index の行を拾う（ページ全体は数百 KB ある）

OPEN_ENV = "ATTENTION_CATCHUP_OPEN"  # 0 なら描いた後に VS Code で開かない（works-dispatch が起動する会話など）
# 外部コマンドを無制限に待たない（catchup.py の GIT_TIMEOUT_SEC と同じ秒）。code --status は生きた窓なら数秒、
# 死んだ socket ならすぐ失敗する
CODE_TIMEOUT_SEC = 20
EXTENSION_ID = "austin-spagnolo.simple-html-viewer"
VIEW_TYPE = "simpleHtmlViewer.preview"
ASSOC_GLOB = "**/.cache/attention/**/*.html"  # /catchup と /reflect のページ
AUTO_REFRESH = ("simpleHtmlViewer.autoRefresh", "onFileChange")
ASSOC_KEY = "workbench.editorAssociations"

TONES = ("good", "bad")
NEXT_CAP = 6        # 次の一手の数の上限
FACT_CAP = 4        # 前回から（where）・止めているもの（turn）の項の数の上限
FACT_TEXT_CAP = 60  # その 1 項の字数（1 文 1 事実）
HEADLINE_CAP = 60   # いまのターンの一言の字数（番号と件名はページの頭に出るので書かない）
NEXT_TEXT_CAP = 60  # 次にやることの 1 項の字数
EXPLAIN_CAP = 6     # 説明の段落の上限（前提・背景・変更 1〜2・使う側。初見向けに詳しく書くので 4〜6 つ）


def cache_root(home=None):
    return pathlib.Path(home or pathlib.Path.home()) / ".cache" / "attention" / "catchup"


# ---- 差分（試作 render.py から写した） -------------------------------------------

HUNK = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@(.*)$")


def parse_diff(text):
    """unified diff を file ごと・hunk ごとに分ける。各行は (印, 前の行番号, 今の行番号, 中身)。"""
    files, f, h = [], None, None
    o = n = 0
    for raw in (text or "").splitlines():
        if raw.startswith("diff --git "):
            # path の読み方（引用形・a/ b/ の外し方・' b/' を含む path）は changemap と 1 つにしてある
            old, new = changemap.head_paths(raw) or ("", raw[len("diff --git "):])
            f = {"path": new, "old": old, "add": 0, "del": 0, "hunks": [], "head": [raw]}
            files.append(f)
            h = None
        elif f is None:
            continue
        elif h is None and not raw.startswith("@@"):
            f["head"].append(raw)
            if raw.startswith("+++ ") and changemap.side_path(raw):
                f["path"] = changemap.side_path(raw)
            elif raw.startswith("--- ") and changemap.side_path(raw) and not f["old"]:
                f["old"] = changemap.side_path(raw)
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
    """変更のセクションの 1 つの見え方（前回から・PR 全体・未コミットなど）。"""
    return {"id": view_id, "name": name, "text": text, "url": url, "note": note,
            "files": summary(parse_diff(text), since_paths)}


# ---- AI のフィールド -----------------------------------------------------------------

FIELD_KEYS = ("headline", "where", "turn", "next", "unseen", "lead", "terms", "explain", "figure", "points", "title")
FIGURE_KINDS = ("graph", "sequence", "compare", "screen", "table", "steps", "html")
FIGURE_CAP = 3      # 1 件に描く図の数の上限（形の違う図を並べるため）
LEAD_CAP = 120      # ひとことの字数の上限（1 文で読める長さ）
TERMS_CAP = 16      # 語の一覧の上限（このリポジトリ・この件の中でしか通じない語。文の中に括弧で定義を足すと 1 文が長くなる）
POINT_CAP = 10      # 変更点の数の上限（1 点は題・前・後の短い文。作者の本文の表を丸ごと写さない）
POINT_TITLE_CAP = 30  # 変更点の題の字数（何がどう変わるかの一言）
POINT_TEXT_CAP = 80   # 変更点の前・後の字数（1 文。長いと横に並べた 2 枚を見比べられない。2026-10-16 は後の中央が 90 字で「頭に入らない」と言われた）
CODE_REF_CAP = 4    # 1 つの変更点・箱に結ぶコードの数の上限
LABEL_CAP = 40      # 図の箱・線・役者の字数の上限（箱の幅 200px で 3 行まで）
SUB_CAP = 60        # 箱の下の補足の字数の上限
EDGE_TEXT_CAP = 18  # 線の字数の上限（流れる物の名前だけ。細かい形は線を押すと出る札とコードへ。長い字は図を横に広げて縮めた）
GRAPH_CAPS = {"nodes": 20, "edges": 30, "groups": 6}  # 1 枚で読み切れる数（全部を 1 画面に入れるため）
SEQ_CAPS = {"actors": 6, "steps": 20}
SCREEN_CAP = 24     # 画面の部品の数の上限
SCREEN_TYPES = ("heading", "text", "field", "textarea", "select", "radio", "checkbox", "toggle", "button",
                "tabs", "list", "alert")
TABLE_CAPS = {"columns": 8, "rows": 16}
STEPS_CAPS = {"lanes": 5, "steps": 16}
HTML_CAP = 20000    # 自由に書く図（html）の字数の上限
PLAY_CAP = 10       # コマ送り（play）のコマの数の上限
PHASES = ("before", "after")  # in: その箱・線が変更前だけ・変更後だけに在る


def validate_fields(obj, need_title=False, data=None, read=None):
    """AI が書いたフィールドを確かめる。直す所を日本語で 1 件 1 行に並べて返す（空なら通った）。
    data（描く材料）を渡すと、変更点（points）と図の箱が指すコードが差分の中に在るかも確かめる。"""
    errs = []
    if not isinstance(obj, dict):
        return ["フィールドの JSON は {…}（オブジェクト）にする"]
    for k in obj:
        if k not in FIELD_KEYS:
            errs.append(f"知らないフィールド {k}（使えるフィールドは {'・'.join(FIELD_KEYS)}）")

    def text(k, required=True):
        v = obj.get(k)
        if v is None:
            if required:
                errs.append(f"{k} が無い（文字列で書く）")
            return
        if not isinstance(v, str) or not v.strip():
            errs.append(f"{k} は空でない文字列にする")

    def facts(k):
        # 前回から・止めているものは、1 項 1 事実の短い文の並び（段落に時刻と件数を詰めると頭に入らないと言われた）。
        # 1 つの文字列も受ける（会話の話題など、事実が 1 つのとき）
        v = obj.get(k)
        if isinstance(v, str) or v is None:
            text(k)
            return
        if not isinstance(v, list) or not 1 <= len(v) <= FACT_CAP or not all(isinstance(x, str) and x.strip() for x in v):
            errs.append(f"{k} は 1〜{FACT_CAP} 個の短い文の並び（[\"…\", …]）にする")
            return
        for i, x in enumerate(v):
            if len(x) > FACT_TEXT_CAP:
                errs.append(f"{k}[{i}] は {FACT_TEXT_CAP} 字までの 1 文にする（今 {len(x)} 字。1 項に 1 つの事実）")

    text("headline")
    if isinstance(obj.get("headline"), str) and len(obj["headline"]) > HEADLINE_CAP:
        errs.append(f"headline は {HEADLINE_CAP} 字までの 1 文にする（今 {len(obj['headline'])} 字。番号と件名はページの頭に出るので書かない）")
    facts("where")
    facts("turn")
    text("title", required=need_title)
    text("lead", required=False)
    if isinstance(obj.get("lead"), str) and len(obj["lead"]) > LEAD_CAP:
        errs.append(f"lead は {LEAD_CAP} 字までの 1 文にする（今 {len(obj['lead'])} 字）")

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
    for i, x in enumerate(obj.get("next") or [] if isinstance(obj.get("next"), list) else []):
        if isinstance(x, str) and len(x) > NEXT_TEXT_CAP:
            errs.append(f"next[{i}] は {NEXT_TEXT_CAP} 字までの 1 手にする（今 {len(x)} 字。理由は止めているものへ）")
    str_list("unseen", 0, 20, False)
    str_list("explain", 0, EXPLAIN_CAP, False)

    errs.extend(_terms_errors(obj.get("terms")))
    files = _diff_files(data, read) if data is not None else None
    pts = obj.get("points")
    n_points = 0
    if pts is not None:
        errs.extend(_points_errors(pts, files))
        if isinstance(pts, dict) and isinstance(pts.get("items"), list):
            n_points = len(pts["items"])
    fig = obj.get("figure")
    if isinstance(fig, list):
        if not 1 <= len(fig) <= FIGURE_CAP:
            errs.append(f"figure を並びにするなら 1〜{FIGURE_CAP} 個にする（今 {len(fig)} 個）")
        for i, f1 in enumerate(fig[:FIGURE_CAP]):
            errs.extend(e.replace("figure", f"figure[{i}]", 1) for e in _figure_errors(f1, files, n_points))
    elif fig is not None:
        errs.extend(_figure_errors(fig, files, n_points))
    return errs


def _terms_errors(terms):
    if terms is None:
        return []
    if not isinstance(terms, list) or not 1 <= len(terms) <= TERMS_CAP or not all(isinstance(t, dict) for t in terms):
        return [f"terms は 1〜{TERMS_CAP} 個の {{\"term\", \"means\"}} の並びにする"]
    errs, seen = [], set()
    for i, t in enumerate(terms):
        at = f"terms[{i}]"
        errs += _keys(t, at, ("term", "means")) + _label(t.get("term"), f"{at}.term", cap=30)
        errs += _label(t.get("means"), f"{at}.means", cap=160)
        if t.get("term") in seen:
            errs.append(f"{at}.term {t.get('term')} が重なっている")
        seen.add(t.get("term"))
    return errs


def _label(v, at, cap=LABEL_CAP, required=True):
    if v is None and not required:
        return []
    if not isinstance(v, str) or not v.strip():
        return [f"{at} は空でない文字列にする"]
    if len(v) > cap:
        return [f"{at} は {cap} 字までにする（今 {len(v)} 字。長い説明は説明の段落か変更点へ）"]
    return []


def _keys(obj, at, allowed):
    return [f"{at} に知らないフィールド {k}（使えるフィールドは {'・'.join(allowed)}）" for k in obj if k not in allowed]


def _tone(obj, at):
    if "tone" in obj and obj["tone"] not in TONES:
        return [f"{at}.tone は good か bad（色を付けないなら書かない）"]
    return []


def _phase(obj, at):
    if "in" in obj and obj["in"] not in PHASES:
        return [f"{at}.in は before（変更前だけに在る）か after（変更後だけに在る）。両方に在るなら書かない"]
    return []


def _ids(items, at, what):
    errs, seen = [], set()
    for i, x in enumerate(items):
        v = x.get("id") if isinstance(x, dict) else None
        if not isinstance(v, str) or not v.strip():
            errs.append(f"{at}[{i}].id は空でない文字列にする（{what}を指す名前）")
        elif v in seen:
            errs.append(f"{at}[{i}].id {v} が重なっている")
        else:
            seen.add(v)
    return errs, seen


def _list(fig, k, at, lo, hi, what):
    v = fig.get(k, [] if lo == 0 else None)
    if not isinstance(v, list) or not lo <= len(v) <= hi or not all(isinstance(x, dict) for x in v):
        return None, [f"{at}.{k} は {lo}〜{hi} 個の{what}（{{…}}）の並びにする"]
    return v, []


def _figure_errors(fig, files=None, n_points=0):
    if not isinstance(fig, dict):
        return ["figure は {\"kind\": …, …}（オブジェクト）か null にする"]
    kind = fig.get("kind")
    if kind not in FIGURE_KINDS:
        return [f"figure.kind は {'・'.join(FIGURE_KINDS)} のどれかにする（形は中身で選ぶ。決まりは skills/catchup/references/figures.md）"]
    errs = _label(fig.get("caption"), "figure.caption", cap=200, required=False)
    if kind == "graph":
        return errs + _graph_errors(fig, files, n_points)
    if kind == "sequence":
        return errs + _sequence_errors(fig)
    if kind == "screen":
        return errs + _screen_errors(fig)
    if kind == "table":
        return errs + _table_errors(fig)
    if kind == "steps":
        return errs + _steps_errors(fig)
    if kind == "html":
        return errs + _keys(fig, "figure", ("kind", "caption", "html")) + html_errors(fig.get("html"))
    return errs + _keys(fig, "figure", ("kind", "caption", "rows")) + _compare_errors(fig.get("rows"))


def _graph_errors(fig, files, n_points):
    errs = _keys(fig, "figure", ("kind", "caption", "dir", "groups", "nodes", "edges", "play"))
    if fig.get("dir", "LR") not in ("LR", "TB"):
        errs.append("figure.dir は LR（左から右）か TB（上から下）")
    groups, e = _list(fig, "groups", "figure", 0, GRAPH_CAPS["groups"], "囲み")
    errs += e
    nodes, e = _list(fig, "nodes", "figure", 1, GRAPH_CAPS["nodes"], "箱")
    errs += e
    edges, e = _list(fig, "edges", "figure", 0, GRAPH_CAPS["edges"], "線")
    errs += e
    gids = set()
    if groups is not None:
        e, gids = _ids(groups, "figure.groups", "囲み")
        errs += e
        for i, g in enumerate(groups):
            at = f"figure.groups[{i}]"
            errs += _keys(g, at, ("id", "text")) + _label(g.get("text"), f"{at}.text")
    nids = set()
    if nodes is not None:
        e, nids = _ids(nodes, "figure.nodes", "箱")
        errs += e
        for i, n in enumerate(nodes):
            at = f"figure.nodes[{i}]"
            errs += _keys(n, at, ("id", "text", "was", "sub", "group", "tone", "in", "points", "code", "fields"))
            fl = n.get("fields", [])
            if not isinstance(fl, list) or len(fl) > 12 or not all(isinstance(x, dict) for x in fl):
                errs.append(f"{at}.fields は 0〜12 個の列（{{\"name\", \"type\"}}）の並びにする")
            else:
                for j, x in enumerate(fl):
                    fat = f"{at}.fields[{j}]"
                    errs += _keys(x, fat, ("name", "type", "tone", "in", "was")) + _label(x.get("name"), f"{fat}.name")
                    errs += _label(x.get("type"), f"{fat}.type", required=False) + _tone(x, fat) + _phase(x, fat)
                    errs += _label(x.get("was"), f"{fat}.was", required=False)
            errs += _label(n.get("text"), f"{at}.text") + _label(n.get("was"), f"{at}.was", required=False)
            errs += _label(n.get("sub"), f"{at}.sub", cap=SUB_CAP, required=False) + _tone(n, at) + _phase(n, at)
            if "was" in n and "in" in n:
                errs.append(f"{at}.was（変更前の字）は前後の両方に在る箱にだけ書く（in と一緒に書かない）")
            if "group" in n and n["group"] not in gids:
                errs.append(f"{at}.group は figure.groups の id のどれか（{'・'.join(sorted(gids)) or 'なし'}）にする")
            errs += _point_refs(n.get("points", []), at, n_points)
            # 増える・消える・変わる箱に番号が無いと、押してもコードが開かず、凡例の項も「図の外」になる（付け忘れが起きた）
            if n_points and ("in" in n or "was" in n) and "points" not in n and "code" not in n:
                errs.append(f"{at} はこの PR で増える・消える・変わる箱なので、その変更点の番号を points に書く"
                            "（差分の外で作る物なら \"points\": [] と書いて、コードが無いことを示す）")
            errs += _code_errors(n.get("code", []), at, files)
    if edges is not None:
        for i, ed in enumerate(edges):
            at = f"figure.edges[{i}]"
            errs += _keys(ed, at, ("from", "to", "text", "tone", "in", "dashed", "points", "code"))
            for k in ("from", "to"):
                if ed.get(k) not in nids:
                    errs.append(f"{at}.{k} は figure.nodes の id のどれかにする（今 {ed.get(k)!r}）")
            errs += _label(ed.get("text"), f"{at}.text", cap=EDGE_TEXT_CAP, required=False) + _tone(ed, at) + _phase(ed, at)
            if "dashed" in ed and not isinstance(ed["dashed"], bool):
                errs.append(f"{at}.dashed は true か false")
            # 線も箱と同じく番号とコードを持てる（何を渡すのか・どう通すのかを押して読めるように。2026-10-16）
            errs += _point_refs(ed.get("points", []), at, n_points)
            if n_points and "in" in ed and "points" not in ed and "code" not in ed:
                errs.append(f"{at} はこの PR で増える・消える線なので、その変更点の番号を points に書く"
                            "（差分の外でつなぐ物なら \"points\": [] と書いて、コードが無いことを示す）")
            errs += _code_errors(ed.get("code", []), at, files)
    errs += _graph_play_errors(fig.get("play"), nids, {f"{e.get('from')}>{e.get('to')}" for e in edges or [] if isinstance(e, dict)})
    return errs


def _point_refs(pts, at, n_points):
    if not isinstance(pts, list) or not all(isinstance(p, int) and not isinstance(p, bool) and 1 <= p <= n_points for p in pts):
        return [f"{at}.points は変更点の番号（1〜{n_points}）の並びにする" if n_points
                else f"{at}.points は points.items を書いたときだけ使う"]
    return []


def _graph_play_errors(play, nids, eids):
    """コマ送り: コマごとに光らせる箱（id）と線（"from>to"）と一言。動きは機械が付ける（線の上を点が流れる）。"""
    if play is None:
        return []
    if not isinstance(play, list) or not 2 <= len(play) <= PLAY_CAP or not all(isinstance(f, dict) for f in play):
        return [f"figure.play は 2〜{PLAY_CAP} 個のコマ（{{\"text\", \"nodes\", \"edges\"}}）の並びにする"]
    errs = []
    for i, f in enumerate(play):
        at = f"figure.play[{i}]"
        errs += _keys(f, at, ("text", "nodes", "edges")) + _label(f.get("text"), f"{at}.text", cap=60)
        ns, es = f.get("nodes", []), f.get("edges", [])
        if not isinstance(ns, list) or any(n not in nids for n in ns):
            errs.append(f"{at}.nodes は figure.nodes の id の並びにする")
        if not isinstance(es, list) or any(e not in eids for e in es):
            errs.append(f"{at}.edges は figure.edges の線を \"from>to\" で書いた並びにする（在る線: {'・'.join(sorted(eids)) or 'なし'}）")
        if not ns and not es:
            errs.append(f"{at} は光らせる箱か線を 1 つ以上書く")
    return errs


def _play_flag(fig):
    if "play" in fig and not isinstance(fig["play"], bool):
        return ["figure.play は true か false（true なら、段を 1 つずつ順に光らせる）"]
    return []


def _sequence_errors(fig):
    errs = _keys(fig, "figure", ("kind", "caption", "actors", "steps", "play")) + _play_flag(fig)
    actors, e = _list(fig, "actors", "figure", 2, SEQ_CAPS["actors"], "役者")
    errs += e
    steps, e = _list(fig, "steps", "figure", 1, SEQ_CAPS["steps"], "やり取り")
    errs += e
    ids = set()
    if actors is not None:
        e, ids = _ids(actors, "figure.actors", "役者")
        errs += e
        for i, a in enumerate(actors):
            errs += _keys(a, f"figure.actors[{i}]", ("id", "text")) + _label(a.get("text"), f"figure.actors[{i}].text")
    if steps is not None:
        for i, s in enumerate(steps):
            at = f"figure.steps[{i}]"
            errs += _keys(s, at, ("from", "to", "text", "tone", "in"))
            for k in ("from", "to"):
                if s.get(k) not in ids:
                    errs.append(f"{at}.{k} は figure.actors の id のどれかにする（今 {s.get(k)!r}）")
            errs += _label(s.get("text"), f"{at}.text") + _tone(s, at) + _phase(s, at)
    return errs


def _screen_errors(fig):
    errs = _keys(fig, "figure", ("kind", "caption", "title", "items"))
    errs += _label(fig.get("title"), "figure.title", required=False)
    items, e = _list(fig, "items", "figure", 1, SCREEN_CAP, "画面の部品")
    errs += e
    for i, it in enumerate(items or []):
        at = f"figure.items[{i}]"
        errs += _keys(it, at, ("type", "label", "value", "hint", "options", "was", "in", "tone", "disabled", "primary", "inline"))
        if it.get("type") not in SCREEN_TYPES:
            errs.append(f"{at}.type は {'・'.join(SCREEN_TYPES)} のどれか")
        errs += _label(it.get("label"), f"{at}.label", cap=60, required=it.get("type") in ("heading", "field", "textarea", "select", "toggle", "button"))
        for k, cap in (("value", 80), ("hint", 160), ("was", 80)):
            errs += _label(it.get(k), f"{at}.{k}", cap=cap, required=False)
        if it.get("type") in ("text", "alert") and not (it.get("label") or it.get("value")):
            errs.append(f"{at} は label か value に文を書く")
        opts = it.get("options", [])
        if not isinstance(opts, list) or len(opts) > 8 or not all(isinstance(o, str) and o.strip() and len(o) <= 30 for o in opts):
            errs.append(f"{at}.options は 0〜8 個の 30 字までの文字列にする（選択肢・タブ・一覧の行）")
        for k in ("disabled", "primary", "inline"):
            if k in it and not isinstance(it[k], bool):
                errs.append(f"{at}.{k} は true か false")
        if "was" in it and "in" in it:
            errs.append(f"{at}.was（変更前の字）は前後の両方に在る部品にだけ書く")
        errs += _tone(it, at) + _phase(it, at)
    return errs


def _table_errors(fig):
    errs = _keys(fig, "figure", ("kind", "caption", "columns", "rows"))
    cols = fig.get("columns")
    if not isinstance(cols, list) or not 1 <= len(cols) <= TABLE_CAPS["columns"] or not all(isinstance(c, str) and c.strip() and len(c) <= LABEL_CAP for c in cols):
        return errs + [f"figure.columns は 1〜{TABLE_CAPS['columns']} 個の列の名前（{LABEL_CAP} 字まで）にする"]
    rows, e = _list(fig, "rows", "figure", 1, TABLE_CAPS["rows"], "行")
    errs += e
    for i, r in enumerate(rows or []):
        at = f"figure.rows[{i}]"
        errs += _keys(r, at, ("label", "cells", "in", "tone")) + _label(r.get("label"), f"{at}.label") + _phase(r, at) + _tone(r, at)
        cells = r.get("cells")
        if not isinstance(cells, list) or len(cells) != len(cols):
            errs.append(f"{at}.cells は列と同じ {len(cols)} 個にする（今 {len(cells) if isinstance(cells, list) else '並びでない'}）")
            continue
        for j, c in enumerate(cells):
            cat = f"{at}.cells[{j}]"
            if isinstance(c, str):
                errs += _label(c, cat, required=False) if c else []
            elif isinstance(c, dict):
                errs += _keys(c, cat, ("text", "was", "tone")) + _label(c.get("text"), f"{cat}.text", required=False)
                errs += _label(c.get("was"), f"{cat}.was", required=False) + _tone(c, cat)
            else:
                errs.append(f"{cat} は文字列か {{\"text\", \"was\", \"tone\"}} にする")
    return errs


def _steps_errors(fig):
    errs = _keys(fig, "figure", ("kind", "caption", "lanes", "steps", "play")) + _play_flag(fig)
    lanes, e = _list(fig, "lanes", "figure", 0, STEPS_CAPS["lanes"], "担い手の列")
    errs += e
    lids = set()
    if lanes:
        e, lids = _ids(lanes, "figure.lanes", "担い手")
        errs += e
        for i, l in enumerate(lanes):
            errs += _keys(l, f"figure.lanes[{i}]", ("id", "text")) + _label(l.get("text"), f"figure.lanes[{i}].text")
    steps, e = _list(fig, "steps", "figure", 1, STEPS_CAPS["steps"], "段")
    errs += e
    for i, st in enumerate(steps or []):
        at = f"figure.steps[{i}]"
        errs += _keys(st, at, ("text", "lane", "when", "tag", "note", "tone", "in"))
        errs += _label(st.get("text"), f"{at}.text", cap=60) + _label(st.get("when"), f"{at}.when", cap=24, required=False)
        errs += _label(st.get("tag"), f"{at}.tag", cap=12, required=False) + _label(st.get("note"), f"{at}.note", cap=120, required=False)
        errs += _tone(st, at) + _phase(st, at)
        if lids and st.get("lane") not in lids:
            errs.append(f"{at}.lane は figure.lanes の id のどれか（{'・'.join(sorted(lids))}）にする")
        elif not lids and "lane" in st:
            errs.append(f"{at}.lane は figure.lanes を書いたときだけ使う")
    return errs


# 自由に書く図（figure.kind = html）の、使ってよいタグと属性。スクリプト・外の読み込み・イベント・フォームの送信は止める。
# 止めたいのは「ページの外へ出る・何かを動かす」ことで、見た目（style・SVG・CSS の動き）は自由にさせる
HTML_TAGS = frozenset("""div span p b strong i em small sub sup code pre kbd mark s u br hr wbr h3 h4 h5 h6 ul ol li dl dt dd
table thead tbody tfoot tr th td caption colgroup col section header footer aside figure figcaption details summary
label button input textarea select option fieldset legend progress meter blockquote q abbr time style
svg g path rect circle ellipse line polyline polygon text tspan textPath defs marker lineargradient radialgradient stop
clippath mask pattern symbol title desc animate animatetransform animatemotion mpath set foreignobject""".split())
HTML_ATTRS = frozenset("""class id style title role lang dir hidden tabindex colspan rowspan scope headers type value placeholder
disabled checked selected readonly multiple rows cols size maxlength min max low high optimum open name for
viewbox preserveaspectratio width height x y x1 x2 y1 y2 cx cy r rx ry dx dy d points pathlength transform
fill fill-opacity fill-rule stroke stroke-width stroke-opacity stroke-dasharray stroke-dashoffset stroke-linecap
stroke-linejoin stroke-miterlimit opacity color font-size font-weight font-family font-style text-anchor
dominant-baseline alignment-baseline letter-spacing text-decoration visibility display overflow vector-effect
marker-start marker-mid marker-end markerwidth markerheight markerunits refx refy orient offset stop-color stop-opacity
gradientunits gradienttransform fx fy spreadmethod clip-path clip-rule mask patternunits patterncontentunits
attributename attributetype from to by values keytimes keysplines calcmode dur begin end repeatcount repeatdur fill
additive accumulate rotate keypoints path startoffset method spacing lengthadjust textlength xmlns""".split())
# url(#id) はページの中（SVG の矢印の印・塗りの参照）なので許す。外を指す url( だけを止める
_URL_IN_CSS = re.compile(r"url\s*\(\s*(?!['\"]?\s*#)|@import|expression\s*\(|javascript:", re.I)


class _HtmlCheck(html.parser.HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.errs, self.in_style = [], False

    def _attr(self, tag, k, v):
        if k.startswith("on"):
            return f"<{tag}> の {k}（イベント）は使えない。動きは CSS か SVG の animate で書く"
        if k.startswith("aria-") or k.startswith("data-"):
            return None
        if k in ("href", "xlink:href"):
            return None if (v or "").startswith("#") else f"<{tag}> の {k} はページの中（#…）だけ指せる"
        if k not in HTML_ATTRS:
            return f"<{tag}> の属性 {k} は使えない"
        if v and _URL_IN_CSS.search(v):
            return f"<{tag}> の {k} に url( / @import / javascript: は書けない（外を読まない）"
        return None

    def handle_starttag(self, tag, attrs):
        if tag not in HTML_TAGS:
            self.errs.append(f"<{tag}> は使えない（スクリプト・外の読み込み・フォームの送信を止めるため）")
        for k, v in attrs:
            e = self._attr(tag, k, v)
            if e:
                self.errs.append(e)
        self.in_style = tag == "style"

    handle_startendtag = handle_starttag

    def handle_endtag(self, tag):
        self.in_style = False

    def handle_data(self, data):
        if self.in_style and _URL_IN_CSS.search(data):
            self.errs.append("<style> に url( / @import / expression( / javascript: は書けない（外を読まない）")


def html_errors(text):
    """自由に書く図の HTML を確かめる。直す所を返す（空なら通った）。直さずに消すことはしない——黙って削ると
    描いた本人が気づかず、図が欠ける。"""
    if not isinstance(text, str) or not text.strip():
        return ["figure.html は空でない文字列にする（HTML か <svg>…</svg>）"]
    if len(text) > HTML_CAP:
        return [f"figure.html は {HTML_CAP} 字までにする（今 {len(text)} 字）"]
    chk = _HtmlCheck()
    try:
        chk.feed(text)
        chk.close()
    except Exception as e:  # noqa: BLE001 — 読めない HTML は直させる
        return [f"figure.html を HTML として読めない（{e}）"]
    seen, out = set(), []
    for e in chk.errs:
        if e not in seen:
            seen.add(e)
            out.append("figure.html: " + e)
    return out[:12]


def _compare_errors(rows):
    if not isinstance(rows, list) or not rows:
        return ["figure.rows（kind が compare）は 1 つ以上の行（{\"name\", \"before\", \"after\"}）の並びにする"]
    errs = []
    for i, r in enumerate(rows):
        at = f"figure.rows[{i}]"
        if not isinstance(r, dict):
            errs.append(f"{at} は {{\"name\", \"before\", \"after\"}}（オブジェクト）にする")
            continue
        errs += _keys(r, at, ("name", "before", "after", "tone")) + _tone(r, at)
        if not isinstance(r.get("name"), str) or not r["name"].strip():
            errs.append(f"{at}.name は空でない文字列にする（比べるものの名前）")
        for k in ("before", "after"):
            if k in r and not isinstance(r[k], str):
                errs.append(f"{at}.{k} は文字列にする（無かった・無くなったなら書かない）")
        if not any(isinstance(r.get(k), str) and r[k].strip() for k in ("before", "after")):
            errs.append(f"{at} は before か after の少なくとも一方を書く")
    return errs


def _points_errors(pts, files):
    if not isinstance(pts, dict):
        return ["points は {\"caption\", \"items\"}（オブジェクト）にする"]
    errs = _keys(pts, "points", ("caption", "items")) + _label(pts.get("caption"), "points.caption", cap=80, required=False)
    items = pts.get("items")
    if not isinstance(items, list) or not 1 <= len(items) <= POINT_CAP:
        return errs + [f"points.items は 1〜{POINT_CAP} 個の変更点（{{\"title\", \"before\", \"after\", \"code\"}}）の並びにする"]
    for i, it in enumerate(items):
        at = f"points.items[{i}]"
        if not isinstance(it, dict):
            errs.append(f"{at} は {{\"title\", \"before\", \"after\", \"code\"}}（オブジェクト）にする")
            continue
        errs += _keys(it, at, ("title", "before", "after", "code", "group"))
        errs += _label(it.get("group"), f"{at}.group", cap=20, required=False)
        for k, need, cap in (("title", True, POINT_TITLE_CAP), ("after", True, POINT_TEXT_CAP), ("before", False, POINT_TEXT_CAP)):
            v = it.get(k)
            if v is None and not need:
                continue
            if not isinstance(v, str) or not v.strip():
                errs.append(f"{at}.{k} は空でない文字列にする")
            elif len(v) > cap:
                errs.append(f"{at}.{k} は {cap} 字までの 1 文にする（今 {len(v)} 字。理由・経緯・前の番号は説明へ、細部はコードへ）")
        errs += _code_errors(it.get("code", []), at, files)
    return errs


def _code_errors(code, at, files):
    if not isinstance(code, list) or len(code) > CODE_REF_CAP:
        return [f"{at}.code は 0〜{CODE_REF_CAP} 個の {{\"path\", \"find\"}} の並びにする"]
    errs = []
    for j, ref in enumerate(code):
        errs += _ref_errors(ref, f"{at}.code[{j}]", files)
    return errs


def _ref_errors(ref, at, files):
    if not isinstance(ref, dict) or not isinstance(ref.get("path"), str) or not ref["path"].strip():
        return [f"{at} は {{\"path\": \"…\"}} の形にする（path は差分の file の path）"]
    # 行番号では指さない。行を知るには差分の枠まで読むことになり、読む量が 1 件 4 万〜6 万字増える（2026-10-16 実測）。
    # 関数・テスト・設定の名前は、もともと読む骨組みに出ているので、それで指す
    errs = _keys(ref, at, ("path", "find"))
    lines = None
    if "find" in ref and (not isinstance(ref["find"], str) or not ref["find"].strip()):
        errs.append(f"{at}.find は差分の中に在る空でない文字列にする")
    if errs or files is None:
        return errs
    f = files.get(ref["path"])
    if f is None and files.read and "find" in ref:
        # 差分の外のファイル（この PR で変えていない受け先の API の形など）は、PR の先頭の版で find を探す
        got = files.read(ref["path"])
        if got is None:
            return [f"{at}.path {ref['path']} は差分に無く、PR の先頭の版でも読めない"]
        if not any(ref["find"] in x for x in got):
            return [f"{at}.find {ref['find']!r} は {ref['path']}（差分の外。PR の先頭の版）に無い"]
        return errs
    if f is None:
        return [f"{at}.path {ref['path']} は差分に無い（差分の file: {'・'.join(sorted(files)) or 'なし'}。"
                "変えていない file を指すなら find も書く。PR の先頭の版から読む）"]
    if not pick_hunks(f, lines, ref.get("find")):
        return [f"{at} に当たる変更の塊が無い（find の {ref.get('find')!r} が {ref['path']} の差分に無い）"]
    return []


# ---- 変更点と図の箱が指すコード（説明からその場で開く差分） --------------------------


class _Files(dict):
    """差分の file を path ごとに。read は差分の外の file の行を PR の先頭の版から返す関数（無ければ None）。"""
    read = None


def _diff_files(data, read=None):
    """描く材料の差分のうち、いちばん広い見え方（PR 全体・この commit など）を path ごとに。"""
    out = _Files()
    out.read = read
    views = [v for v in (data or {}).get("views") or [] if v.get("text")]
    if views:
        v = next((x for x in views if x.get("id") == "all"), views[-1])
        out.update({f["path"]: f for f in parse_diff(v["text"])})
    return out


# 差分の外の file は、find の行の前 2 行から、その行の塊（字下げが find の行より深い間）の終わりまでを見せる。
# 短すぎれば 8 行は見せ、長くても 40 行で切る（決まった行数で切ると、型の後ろの import まで出た）
OUTSIDE_BEFORE, OUTSIDE_MIN, OUTSIDE_MAX = 2, 8, 40


def _indent(s):
    return len(s) - len(s.lstrip())


def _outside_text(path, lines, find):
    """差分の外の file の抜き出しを、変わっていない行だけの unified diff にする（差分と同じ部品で描ける）。"""
    k = next((i for i, x in enumerate(lines) if find in x), None)
    if k is None:
        return None
    base, end = _indent(lines[k]), k + 1
    while end < len(lines) and end - k < OUTSIDE_MAX and (not lines[end].strip() or _indent(lines[end]) > base or end - k < OUTSIDE_MIN):
        end += 1
    while end > k + 1 and not lines[end - 1].strip():
        end -= 1
    lo, hi = max(0, k - OUTSIDE_BEFORE), end
    n = hi - lo
    head = [f"diff --git a/{path} b/{path}", f"--- a/{path}", f"+++ b/{path}", f"@@ -{lo + 1},{n} +{lo + 1},{n} @@"]
    return "\n".join(head + [" " + x for x in lines[lo:hi]]) + "\n"


def pick_hunks(f, lines=None, find=None):
    """file の変更の塊（hunk）のうち、lines（今の版の行の範囲）に重なるか、find の文字列を含むもの。
    どちらも無ければ全部。"""
    out = []
    for h in f["hunks"]:
        news = [r[2] for r in h["rows"] if r[2] is not None]
        lo, hi = (min(news), max(news)) if news else (h["n"], h["n"])
        if lines and (hi < lines[0] or lo > lines[1]):
            continue
        if find and find not in h["ctx"] and not any(find in r[3] for r in h["rows"]):
            continue
        out.append(h)
    return out


def hunks_text(f, hunks):
    """選んだ塊だけの unified diff（diff2html がそのまま描ける形）。"""
    body = []
    for h in hunks:
        oc = sum(1 for r in h["rows"] if r[0] != "+")
        nc = sum(1 for r in h["rows"] if r[0] != "-")
        body.append(f"@@ -{h['o']},{oc} +{h['n']},{nc} @@ {h['ctx']}".rstrip())
        body.extend(r[0] + r[3] for r in h["rows"])
    return "\n".join(f["head"] + body) + "\n"


def _resolve(files, refs):
    out = []
    for ref in refs or []:
        f = files.get(ref.get("path"))
        hs = pick_hunks(f, None, ref.get("find")) if f else []
        if hs:
            out.append({"path": f["path"], "anchor": anchor(f["path"]), "text": hunks_text(f, hs)})
        elif f is None and files.read and ref.get("find"):
            got = files.read(ref["path"])
            text = _outside_text(ref["path"], got, ref["find"]) if got is not None else None
            if text:
                out.append({"path": ref["path"], "text": text, "outside": True})
    return out


def point_code(data, fields, read=None):
    """指したコードの差分。{"points": [変更点ごとの並び], "nodes": {箱の id: 並び}, "edges": {"from>to": 並び}}。引けないものは空。"""
    files = _diff_files(data, read)
    fields = fields or {}
    items = (fields.get("points") or {}).get("items") or []
    figs = fields.get("figure") or []
    figs = figs if isinstance(figs, list) else [figs]
    nodes = [n for f1 in figs if isinstance(f1, dict) and f1.get("kind") == "graph" for n in f1.get("nodes") or []]
    found = {n["id"]: _resolve(files, n.get("code")) for n in nodes if n.get("code")}
    edges = {}
    for f1 in figs:
        if isinstance(f1, dict) and f1.get("kind") == "graph":
            for e in f1.get("edges") or []:
                if e.get("code"):
                    edges.setdefault(f"{e.get('from')}>{e.get('to')}", []).extend(_resolve(files, e.get("code")))
    return {"points": [_resolve(files, it.get("code")) for it in items],
            "nodes": {k: v for k, v in found.items() if v},
            "edges": {k: v for k, v in edges.items() if v}}


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


def build_html(template, data, fields, entry, read=None):
    title = " ".join(x for x in (entry["ref"], entry["title"]) if x) or "catchup"
    for slot in (DATA_SLOT, INDEX_SLOT, TITLE_SLOT):
        if slot not in template:
            raise ValueError(f"雛形に差し込み口 {slot} が無い")
    # 3 つを 1 回の走査で差し込む。順に replace すると、先に入れた件名などに後の差し込み口の文字列が
    # 含まれていたとき、そちらに当たって本物の口が空のまま残る
    filled = {TITLE_SLOT: f"<title>{html.escape(title)}</title>", INDEX_SLOT: _script_json(entry),
              DATA_SLOT: _script_json({"data": data, "fields": fields, "code": point_code(data, fields, read)})}
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


def write_page(data, fields, root=None, template=None, now=None, read=None):
    """ページを書き、index を組み直す。戻り値は (ページの path, 1 行の要約)。"""
    root = pathlib.Path(root) if root else cache_root()
    now = now or dt.datetime.now().astimezone()
    template = template if template is not None else TEMPLATE.read_text(encoding="utf-8")
    rel = page_rel(data, fields)
    entry = index_entry(data, fields, rel, now)
    path = root / rel
    _write_atomic(path, build_html(template, data, fields, entry, read))
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
    """`code --status` が 0 で返る socket だけ。herdr などの中の会話は、起動した時の古い VSCODE_IPC_HOOK_CLI を
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

    server = pathlib.Path(home or pathlib.Path.home()) / ".vscode-server"
    if not server.is_dir():
        # Remote-SSH で繋いだことの無いマシン。手元の VS Code は拡張と設定を別の置き場から読むので、ここに書いても効かない。
        # 置き場を作らずに訳を返す（code が無いときの訳は上で出している）
        if cli:
            missing.append(f"このマシンに VS Code の Remote-SSH の置き場（{server}）が無い。/catchup setup は Remote-SSH"
                           "で繋いだ先のマシンの準備だけをする（手元の VS Code は拡張と設定を別の置き場から読み、ここに書いても"
                           "効かない）。Remote-SSH で繋いだ窓の端末から打ち直す")
        return _setup_report(did, missing)

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
    return _setup_report(did, missing)


def _setup_report(did, missing):
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
    "status": [{"key": "threads", "label": "未解決の会話", "value": "1 件 · 私が返すターン 1 件", "tone": "mine"},
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
    "headline": "私の指摘に作者が直して返してきた。私が確かめて返すターン。",
    "where": ["09:41 に、包まれた例外も見てほしいと指摘した", "作者が 15:32 に push し、15:44 に返信した"],
    "turn": ["止めているのは私の返事だけ"],
    "next": ["差分を読み、包まれた切断が 4 になるかを確かめる", "返信して解決にする"],
    "unseen": ["これは見本で、実在の件ではない"],
    "lead": "包まれた切断も、終了コード 4（切断）で終わるようにする。",
    "explain": ["このページは /catchup setup が描いた見本です。色が付いて差分が出ていれば、拡張と設定が効いています。"],
    "points": {"items": [{"title": "原因の連鎖をたどる", "before": "いちばん外の例外だけを見ていた",
                          "after": "原因の連鎖をたどり、どこかに切断があれば 4 にする",
                          "code": [{"path": "app/retry.py"}]}]},
    "figure": {"kind": "graph", "caption": "見本の図", "nodes": [
        {"id": "err", "text": "例外"},
        {"id": "walk", "text": "原因の連鎖をたどる", "was": "いちばん外だけを見る", "points": [1], "code": [{"path": "app/retry.py"}]},
        {"id": "four", "text": "4 で終わる（切断）"},
        {"id": "one", "text": "1 で終わる"}],
        "edges": [{"from": "err", "to": "walk"}, {"from": "walk", "to": "four", "text": "外が切断"},
                  {"from": "walk", "to": "four", "text": "中に切断", "in": "after", "points": [1]},
                  {"from": "walk", "to": "one", "text": "中に切断", "in": "before", "tone": "bad", "points": [1]},
                  {"from": "walk", "to": "one", "text": "切断が無い"}]},
}


def save_data(data, stem="catchup-data"):
    """catchup.py が組んだ材料を一時ファイル（0600）に書き、path を返す。--out の報告と同じ置き場。"""
    fd, path = tempfile.mkstemp(prefix=f"{stem}-{dt.datetime.now():%Y%m%d-%H%M%S}-", suffix=".json")
    with open(fd, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)
    return path
