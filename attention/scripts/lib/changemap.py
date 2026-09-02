"""変更の地図の部品。/catchup（PR の diff）と /what-am-i-doing（手元の変更）が共用する。

〈立場〉判断はしない。行は 1 文字も変えずに返す——AI が写す元になるので、ここで整えると写した
先が実物と違う。出すのは置き場所（木）・骨組み（step 名・def・上位 key）・配線の当たり（名前の
言及）で、行の要約はしない（思い出す助けにならず、要約は実物と違う言葉になる）。

〈木〉IDE の変更ファイル一覧と同じ形にする。path と ±行数だけで説明語を書かない。周辺の既存も
薄く並べる（同じ階層で名前の近いものを数件と「… ほか N」）——変更ファイルだけの木では
「全体のどこか」が読めない（実測）。新規は行頭 `+`（diff の枠に入れると緑になる）、既存への
変更は `~`、削除は `-`。

〈path〉GitHub のサーバ側 diff は日本語名を "\\346…" の引用形で出す。戻さないと GraphQL の path と
突き合わせられず、その file の中身が黙って落ちる（実測）。git ls-tree も既定は同じ引用形なので
core.quotePath=false を付ける。"""

import os
import re
import shutil
import subprocess
import unicodedata

HUNK_LIMIT = 15      # 既存ファイルの変更がこの行数以内なら hunk を丸ごと出す
HEAD_LINES = 8       # 新規ファイルの先頭コメント / docstring を出す行数
OUTLINE_CAP = 40     # 骨組みの行数の上限（1 ファイルあたり）
SIBLINGS_SHOWN = 4   # 木で 1 階層に薄く並べる周辺の名前の数
TREE_NOTE_COL = 42   # 木の ±行数を置く桁


def width(s):
    return sum(2 if unicodedata.east_asian_width(c) in "WF" else 1 for c in s)


# ---- unified diff ---------------------------------------------------------------


def unquote_git_path(s):
    r"""git の core.quotePath 形式（"…" の中に \ooo の 8 進エスケープ）を UTF-8 に戻す。"""
    if not (len(s) >= 2 and s[0] == '"' and s[-1] == '"'):
        return s
    esc = {"n": "\n", "t": "\t", '"': '"', "\\": "\\"}

    def repl(m):
        e = m.group(1)
        return chr(int(e, 8)) if e[0] in "01234567" else esc.get(e, e)

    decoded = re.sub(r"\\([0-7]{3}|.)", repl, s[1:-1])
    try:
        return decoded.encode("latin-1").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return decoded


def split_diff(text):
    """unified diff を path → hunk の行に分ける。ファイル見出し（---/+++/index…）は落とし、
    @@ 行と '+'/'-'/' ' の行だけ残す。見出しの判定は最初の @@ より前に限る——hunk の中の
    '--- ' は削除された行（元の行が '-- ' で始まる）でありうる。
    path は '+++ b/…' 行（削除なら '--- a/…'）を正とする。'diff --git a/x b/y' は path に
    ' b/' を含むと切れ目が決められない。改名は renames[新] = 旧 に入れて返す。"""
    files, renames, cur, in_hunk = {}, {}, None, False
    lines = text.split("\n")
    if lines and lines[-1] == "":
        lines.pop()  # 末尾の改行で出る空要素。hunk の空行ではない
    for line in lines:
        if line.startswith("diff --git "):
            cur = None
            in_hunk = False
            m = re.match(r'diff --git ("?)a/(.*?)\1 ("?)b/(.*?)\3$', line)
            if m:
                cur = unquote_git_path(m.group(3) + m.group(4) + m.group(3))
                files.setdefault(cur, [])
            continue
        if in_hunk:
            if line == "" or line[0] in "+- ":
                if cur is not None:
                    files[cur].append(line)
            elif line.startswith("@@") and cur is not None:
                files[cur].append(line)
            # "\ No newline at end of file" は落とす
            continue
        if line.startswith("@@"):
            in_hunk = True
            if cur is not None:
                files[cur].append(line)
            continue
        # ここから下は @@ より前の見出し
        if line.startswith("+++ ") and not line.startswith("+++ /dev/null"):
            path = unquote_git_path(line[4:].strip())
            path = path[2:] if path.startswith("b/") else path
            if cur != path:
                files[path] = files.pop(cur, []) if cur is not None else []
                cur = path
        elif line.startswith("--- ") and not line.startswith("--- /dev/null") and cur is None:
            path = unquote_git_path(line[4:].strip())
            cur = path[2:] if path.startswith("a/") else path
            files.setdefault(cur, [])
        elif line.startswith("rename from "):
            renames["__from__"] = unquote_git_path(line[len("rename from "):].strip())
        elif line.startswith("rename to "):
            renames[unquote_git_path(line[len("rename to "):].strip())] = renames.pop("__from__", "")
    renames.pop("__from__", None)
    return files, renames


def added_lines(hunk_lines):
    return [ln[1:] for ln in hunk_lines if ln.startswith("+")]


# ---- ファイルの自己紹介と骨組み ------------------------------------------------------


def file_head(path, lines, cap=HEAD_LINES):
    """先頭のコメントか docstring。作者の自己紹介にあたる部分だけ取る。
    返すのは (行, 切れたか)。切れたことは出力に書く——黙って切ると、途中で終わった文が
    作者の言葉として写される（実測）。"""
    i = 1 if lines and lines[0].startswith("#!") else 0
    while i < len(lines) and not lines[i].strip():
        i += 1
    out = []
    if path.endswith(".py"):
        # coding 行や著作権のコメントが docstring の前にあることがある。# 塊を先に取り、
        # その直後に docstring があれば続けて取る
        j = i
        while j < len(lines) and lines[j].startswith("#"):
            out.append(lines[j])
            j += 1
        while j < len(lines) and not lines[j].strip():
            j += 1
        m = re.match(r"\s*[rRuUbB]{0,2}(\"\"\"|''')", lines[j]) if j < len(lines) else None
        if m:
            q = m.group(1)
            out.append(lines[j])
            closed = lines[j].count(q) >= 2
            k = j + 1
            while not closed and k < len(lines) and len(out) < cap:
                out.append(lines[k])
                closed = q in lines[k]
                k += 1
            if not closed:
                return out[:cap], True
        return out[:cap], len(out) > cap
    # コメント塊は name:（workflow）や shebang の後ろに置かれることが多い。先頭 6 行以内に
    # 現れる最初の塊を取り、コードで止める
    while i < len(lines) and i < 6 and not lines[i].startswith(("#", "//")):
        i += 1
    for ln in lines[i:]:
        if not ln.startswith(("#", "//")):
            break
        out.append(ln)
    return out[:cap], len(out) > cap


OUTLINE_PATTERNS = {
    "yml": r"^(?:[A-Za-z_][\w.-]*:|  [A-Za-z_][\w.-]*:\s*$|\s+- (?:name|id|uses): |\s+uses: )",
    "py": r"^(?:(?:async )?def |class |    (?:async )?def )",
    "sh": r"^(?:function [\w-]+|[\w-]+\s*\(\)\s*\{?\s*$)",
    "bats": r"^@test ",
    "hcl": r'^(?:target|group|variable|function) "',
    "tf": r'^(?:resource|module|variable|output|data) "',
    "ts": r"^(?:export |function |class |const \w+ = )",
    "go": r"^(?:func |type )",
    "adoc": r"^=+ ",
    "md": r"^#+ ",
}
OUTLINE_PATTERNS["yaml"] = OUTLINE_PATTERNS["yml"]
OUTLINE_PATTERNS["bash"] = OUTLINE_PATTERNS["sh"]
OUTLINE_PATTERNS["js"] = OUTLINE_PATTERNS["ts"]


def outline(path, lines):
    """骨組みの行。種類ごとに「読む人が構造として見る行」だけ拾う。知らない種類は空。"""
    base = path.rsplit("/", 1)[-1]
    ext = base.rsplit(".", 1)[-1].lower() if "." in base else ""
    pat = OUTLINE_PATTERNS.get(ext)
    if pat is None and base.lower().startswith("dockerfile"):
        pat = r"^(?:FROM|ENTRYPOINT|CMD|EXPOSE)\b"
    if pat is None:
        return []
    return [ln for ln in lines if re.match(pat, ln)]


def call_refs(paths, hunks, hits_cap=6):
    """追加行が他の変更ファイルの名前を含む関係と、その行（先頭 hits_cap 行）。名前は basename、
    composite action は dir 名。文字列一致なので当たりでしかない——コメントでの言及も混ざる。
    呼び出しかどうかは AI が行を見て決める（uses:・run:・-f・import なら呼び出し）。"""
    keys = {}
    for p in paths:
        base = p.rsplit("/", 1)[-1]
        if base in ("action.yml", "action.yaml") and p.count("/") >= 1:
            base = p.rsplit("/", 2)[-2]
        if len(base) >= 4:
            keys[p] = base
    rel = {}
    for a, lines in hunks.items():
        if a not in paths:
            continue
        added = added_lines(lines)
        for b, key in keys.items():
            if a == b:
                continue
            hits = [ln for ln in added if key in ln]
            if hits:
                rel.setdefault(a, []).append((b, hits[:hits_cap]))
    for a in rel:
        rel[a].sort()
    return rel


def modified_hunks(path, lines, adds, dels):
    """小さい変更は hunk をそのまま。大きい変更は @@ の見出し（関数名つき）と、追加行のうち
    骨組みにあたる行（新しい step・def・見出し）だけ。骨組みの取れない種類（拡張子なし等）は
    コメントでない変更行を数行。全文は gh pr diff で見る。
    返すのは (prefix, text) の列。prefix が "| " なら実物の行、"" なら機械の説明。"""
    if adds + dels <= HUNK_LIMIT:
        return [("| ", ln) for ln in lines]
    heads = [ln for ln in lines if ln.startswith("@@")]
    out = [("| ", ln) for ln in heads[:5]]
    if len(heads) > 5:
        out.append(("", f"（@@ は他に {len(heads) - 5} 個）"))
    ol = outline(path, added_lines(lines))
    if ol:
        out.append(("", "追加行の骨組み:"))
        out.extend(("| ", "+" + ln) for ln in ol[:12])
        if len(ol) > 12:
            out.append(("", f"（他に {len(ol) - 12} 行）"))
        return out
    body = [ln for ln in lines if ln[:1] in "+-" and ln[1:].lstrip()
            and not ln[1:].lstrip().startswith(("#", "//"))]
    if body:
        out.append(("", "コメントでない変更行:"))
        out.extend(("| ", ln) for ln in body[:8])
        if len(body) > 8:
            out.append(("", f"（他に {len(body) - 8} 行）"))
    return out


# ---- 手元の git ------------------------------------------------------------------


def git(*args, cwd=None):
    """git を呼ぶ。無い・失敗なら None（地図の材料は無くても本体の報告は成り立つ）。"""
    exe = shutil.which("git")
    if not exe:
        return None
    try:
        r = subprocess.run(  # noqa: S603 — git は which で解決。引数はこのファイル内のリテラルと path だけ
            [exe, *args], cwd=cwd, capture_output=True, encoding="utf-8", errors="replace",
            timeout=15,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return r.stdout if r.returncode == 0 else None


def repo_top(cwd=None):
    out = git("rev-parse", "--show-toplevel", cwd=cwd)
    return out.strip() if out else None


def origin_matches(top, owner, name):
    """origin が owner/name か。末尾 2 セグメントの等値で見る——部分一致だと org/platform-docs の
    checkout を org/platform と誤認し、別リポジトリの名前が「同じ階層の既存」に混ざる（実測）。"""
    url = git("remote", "get-url", "origin", cwd=top)
    if not url:
        return False
    m = re.search(r"[:/]([^/:]+)/([^/]+?)(?:\.git)?/?$", url.strip())
    return bool(m) and (m.group(1).lower(), m.group(2).lower()) == (owner.lower(), name.lower())


def tracked_names(top, d):
    """階層 d（"." は根）の、HEAD が追跡している名前。無ければ None。
    os.listdir だと .venv や __pycache__ が「既存」に混ざるので ls-tree で数える。"""
    args = ["-c", "core.quotePath=false", "ls-tree", "HEAD"]
    args += [] if d == "." else ["--", d + "/"]
    out = git(*args, cwd=top)
    if not out:
        return None
    names = []
    for line in out.splitlines():
        # <mode> SP <type> SP <hash> TAB <path>
        meta, _, path = line.partition("\t")
        if not path:
            continue
        base = os.path.basename(path)
        names.append(base + "/" if meta.split()[1:2] == ["tree"] else base)
    return sorted(names)


def siblings_for(top, paths):
    """変更ファイルの各階層について、同じ階層の追跡ファイル名を引く。"""
    dirs = sorted({p.rsplit("/", 1)[0] if "/" in p else "." for p in paths})
    return {d: tracked_names(top, d) for d in dirs}


# ---- 木 -------------------------------------------------------------------------


def _tokens(name):
    name = name.rstrip("/")
    stem = name.rsplit(".", 1)[0] if "." in name else name
    toks = set()
    for t in re.split(r"[-_.]+", stem.lower()):
        if len(t) >= 3:
            toks.add(t[:-1] if len(t) > 3 and t.endswith("s") else t)  # check / checks を同じ語に
    return toks


def rank_siblings(names, changed, shown=SIBLINGS_SHOWN):
    """周辺から薄く見せる名前を選ぶ。変更ファイルと語（-_. 区切り）と拡張子を共有するものを
    先に。判断ではなく近さの目安で、読む人が「同じ階層の何の隣か」を掴むためのもの。"""
    if not names:
        return []
    ctoks = set()
    cexts = set()
    for c in changed:
        ctoks |= _tokens(c)
        if "." in c:
            cexts.add(c.rsplit(".", 1)[-1].lower())
    def score(n):
        ext = n.rsplit(".", 1)[-1].lower() if "." in n else ""
        # 語の共有 → 拡張子の一致 → dotfile でない → 名前順。dotfile は設定で、隣として掴む相手ではない
        return (-len(_tokens(n) & ctoks), -(ext in cexts and ext != ""), n.startswith("."), n)
    pool = [n for n in names if n.rstrip("/") not in changed]
    return sorted(pool, key=score)[:shown]


def render_tree(entries, siblings=None, root_label="."):
    """変更ファイルの木。entries は {path, mark, note} の列（mark は "+" 新規 / "~" 変更 / "-" 削除、
    note は "+526" や "+5/-1"）。siblings は 階層 → 追跡ファイル名（None なら周辺は出さない）。
    行頭 1 桁が mark。diff の枠に入れると + が緑、- が赤になる。"""
    siblings = siblings or {}
    by_dir = {}
    for e in entries:
        d, base = (e["path"].rsplit("/", 1) if "/" in e["path"] else (".", e["path"]))
        by_dir.setdefault(d, []).append((base, e))
    # 木に出る階層: 変更のある階層と、その親
    dirs = set()
    for d in by_dir:
        parts = [] if d == "." else d.split("/")
        for i in range(len(parts) + 1):
            dirs.add("/".join(parts[:i]) or ".")
    out = []

    def label(d, depth, marker=" "):
        names = siblings.get(d)
        shown_children = {b for b, _ in by_dir.get(d, [])}
        shown_children |= {c.split("/")[-1] for c in dirs if c != "." and (
            (c.rsplit("/", 1)[0] if "/" in c else ".") == d)}
        picked = rank_siblings(names, shown_children) if names else []
        bare = {n.rstrip("/") for n in names} if names else set()
        rest = len(names) - len(shown_children & bare) - len(picked) if names else 0
        text = (root_label + "/") if d == "." else (d.rsplit("/", 1)[-1] + "/")
        line = marker + "  " * depth + text
        if rest > 0:
            line += f"  … ほか {rest}"
        out.append(line)
        return picked

    def walk(d, depth):
        picked = label(d, depth)
        if picked:
            row = " " + "  " * (depth + 1)
            joined = row + "  ".join(picked)
            if width(joined) <= 60:
                out.append(joined)
            else:
                for n in picked:
                    out.append(row + n)
        for base, e in sorted(by_dir.get(d, []), key=lambda x: x[0]):
            line = e.get("mark", "~") + "  " * (depth + 1) + base
            note = e.get("note") or ""
            if note:
                pad = max(2, TREE_NOTE_COL - width(line))
                if width(line) + pad + width(note) <= 60:
                    line += " " * pad + note
                else:
                    # 長い名前は注記を次の行に落とす。折り返すと行頭の印が消える
                    out.append(line)
                    line = " " + "  " * (depth + 1) + "  " + note
            out.append(line)
        children = sorted(c for c in dirs if c != "." and c != d and (
            (c.rsplit("/", 1)[0] if "/" in c else ".") == d))
        for c in children:
            walk(c, depth + 1)

    walk(".", 0)
    return out


def entries_from_porcelain(porcelain, numstat=None):
    """git status --porcelain の行を木の entries にする。numstat は path → (追加, 削除)。"""
    numstat = numstat or {}
    entries = []
    for line in porcelain.splitlines():
        # 位置で切らない。出力全体を strip されると 1 行目の先頭空白が消えて桁がずれる
        # （" M docs/a.md" → "M docs/a.md"。3 桁目から切ると "ocs/a.md" になる。実測）
        parts = line.split(maxsplit=1)
        if len(parts) < 2:
            continue
        xy, rest = parts
        path = rest.split(" -> ", 1)[-1]
        if path.startswith('"') and path.endswith('"'):
            path = unquote_git_path(path)
        whole_dir = path.endswith("/")  # "?? newdir/"（-uall なし）。階層ごと新規
        path = path.rstrip("/")
        if not path:
            continue
        if xy == "??" or "A" in xy:
            mark = "+"
        elif "D" in xy:
            mark = "-"
        else:
            mark = "~"
        a, d = numstat.get(path, (None, None))
        if mark == "+" and a is None:
            note = "新規（階層ごと。中は git status -uall で）" if whole_dir else "新規"
        elif a is None:
            note = ""
        elif mark == "-":
            note = f"-{d}"
        else:
            note = f"+{a}" if not d else f"+{a}/-{d}"
        if " -> " in rest:
            note = (note + "  " if note else "") + "旧: " + rest.split(" -> ", 1)[0]
        entries.append({"path": path, "mark": mark, "note": note})
    return entries


def working_tree(cwd=None):
    """手元の未コミットの変更を (パスの一覧, 木の行) で返す。変更が無ければ ([], [])。
    /catchup（今のブランチで呼んだとき）と /what-am-i-doing が共用。"""
    # -uall: 未追跡の階層を中のファイルに展開する（既定は "newdir/" の 1 行で、木に名前の無い行が出る）
    porcelain = git("status", "--porcelain", "--untracked-files=all", cwd=cwd) or ""
    entries = entries_from_porcelain(
        porcelain, parse_numstat(git("-c", "core.quotePath=false", "diff", "HEAD",
                                     "--numstat", cwd=cwd)))
    if not entries:
        return [], []
    top = repo_top(cwd)
    sib = siblings_for(top, [e["path"] for e in entries]) if top else None
    label = os.path.basename(top) if top else "."
    return [e["path"] for e in entries], render_tree(entries, sib, root_label=label)


def parse_numstat(text):
    out = {}
    for line in (text or "").splitlines():
        parts = line.split("\t")
        if len(parts) != 3:
            continue
        a, d, path = parts
        if path.startswith('"') and path.endswith('"'):
            path = unquote_git_path(path)
        # 改名は "dir/{old => new}/x" か "old => new"。中括弧は新しい側に畳む
        path = re.sub(r"\{([^{}]*) => ([^{}]*)\}", r"\2", path).replace("//", "/")
        path = path.split(" => ")[-1]
        try:
            out[path] = (int(a), int(d))
        except ValueError:
            out[path] = (None, None)  # バイナリは "-"
    return out
