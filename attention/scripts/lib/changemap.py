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
import pathlib
import re
import shutil
import subprocess
import unicodedata

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


def _ext(path):
    """拡張子（小文字）。無ければ ""。"""
    base = path.rsplit("/", 1)[-1]
    return base.rsplit(".", 1)[-1].lower() if "." in base else ""


def outline(path, lines):
    """骨組みの行。種類ごとに「読む人が構造として見る行」だけ拾う。知らない種類は空。"""
    base = path.rsplit("/", 1)[-1]
    pat = OUTLINE_PATTERNS.get(_ext(path))
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


# ---- 変更の枠（今の姿に、機械が帯を入れる） ---------------------------------------------
#
# 読む人が判断に使うのは diff ではなく「今のコードの中で、どこが変わったか」。unified diff は patch の
# 形式で、@@ の行は人に意味が無く、行頭の +/- は構文の色を消す（端末の highlight は diff か言語かの
# どちらか）。そこで今の姿（言語の色が付く）をそのまま出し、変わった所だけをコメント行の帯で囲む——
# IntelliJ の gutter（構文色は残し、変更は脇の帯で示す）の端末版。
#   実線の枠 ┏ … ┗ ＝ ここが変わった（追加・変更・削除）。中で行頭が `#│`（コメント記号＋│）の薄い行は
#   前、色の行は今。前の行の印は専用にする——コメント記号だけだと、今足したコメント行（コメントアウト・
#   設計コメント）と同じ字面になり、読み方が 2 つになる（実測）
#   点線 ┅ ＝ 行が無い（長い関数で変わっていない区間を畳んだ。前の行が多すぎて省いた）
# 帯はその言語のコメント記法で入れるので、枠は有効なコードのまま。帯の幅は東アジア幅で揃える
# （揃わないと罫線でなく雑音に見える——実測）。近い変更（間 3 行以内）は 1 つの枠にまとめ、挟まった
# 変わっていない行の数を帯に書く（1 行ごとに枠 2 行を払うと枠の山になる——実測）。行番号・変更の断片は
# 入れない（実測: 要らない、ごちゃつく）。
# 単位は関数まるごと（git diff -W）。削るのは関数の数で、行ではない——関数の途中を省くと読む人は
# そこで判断を止める（実測）。長い関数だけ、変わっていない区間を点線で畳む。散文・設定（md・json 等）は
# 関数が無く -W だと文脈が file 全体に広がるので、そこだけ行数の文脈（PROSE_CONTEXT）で取る——枠は出す（file の種類で
# 地図の中身を出し分けない。出し分けると md が主のリポジトリでは木しか出ず、飛び先も消える。実測）。

FRAME_WIDTH = 78   # 帯の全幅（字下げ込み。東アジア幅で数える）
FRAME_GAP = 3      # 変わっていない行がこの数以内で隣り合う変更は 1 つの枠
FRAME_WHOLE = 200  # hunk（-W なら関数まるごと）がこの行数以内なら畳まず全部出す（前後は長めに。仕様の原則 4）
FOLD_KEEP = 30     # 畳むとき、変更の前後に残す行数
PROSE_CONTEXT = 10  # 散文・設定（関数の境目が無い file）の文脈の行数。-W が使えないので行数で広げる
OLD_CAP = 15       # 枠の中に残す前の行の上限。超えたら先頭 3 行と行数
FRAME_FILE_CAP = 300  # 1 file の枠の行数の目安。超えたら関数の切れ目で止めて、残りは --frame で
FRAME_TOTAL_CAP = 800  # 変更の中身の合計の目安。超えた file は名前だけ（大きい変更で報告が材料に埋もれない）
FRAME_NOTE = ("今の姿に機械が帯を入れた。実線の枠 ┏…┗ が変わった所で、中の行頭が `#│`（コメント記号＋│）の"
              "行は前・色の行は今。間 3 行以内の変更は 1 枠で、挟まった変わっていない行の数は帯に書いてある。"
              "点線 ┅ は畳んだ区間。`| ` の後ろをそのまま、見出しの（言語名 X）を付けた枠に貼る")
COMMENT_BY_EXT = {
    ("//", ""): {"ts", "tsx", "js", "jsx", "mjs", "go", "java", "kt", "kts", "c", "h", "cc", "cpp",
                 "hpp", "cs", "rs", "swift", "scala", "php", "hcl", "tf", "tfvars", "groovy", "dart",
                 "proto", "json", "jsonc", "scss", "less", "sass"},
    ("--", ""): {"sql", "lua", "hs", "elm"},
    ("/*", " */"): {"css"},
    ("<!--", " -->"): {"md", "html", "htm", "xml", "svg", "vue"},  # 散文・markup
}
# 関数の境目が無い file。-W は「行頭が字下げ無しの行」を関数の頭とみなすので、ここで -W を使うと
# yaml の 1 行の変更が top-level key から 60 行の枠になり、飛び先も 28 行ずれる（実測）
PROSE_EXT = {"md", "txt", "adoc", "rst", "html", "htm", "xml", "json", "jsonc", "csv", "lock",
             "yml", "yaml", "toml", "ini", "cfg"}


# 枠に付ける言語名（highlight.js の名前）。AI が ```<言語名> に写す。機械が決めるのは、AI に選ばせると
# 命令書の例に無い .md を plaintext にして色が消えた（実走で実測）から。表に無い種類は拡張子をそのまま出す——
# highlight.js が知らなければ色が付かないだけで害は無く、別の描画器なら付く。plaintext は拡張子が無い file だけ
FENCE_BY_EXT = {
    "python": {"py", "pyi"}, "markdown": {"md", "markdown"}, "bash": {"sh", "bash", "zsh", "bats"},
    "yaml": {"yml", "yaml"}, "json": {"json", "jsonc"}, "typescript": {"ts", "tsx"},
    "javascript": {"js", "jsx", "mjs", "cjs"}, "go": {"go"}, "rust": {"rs"}, "java": {"java"},
    "kotlin": {"kt", "kts"}, "ruby": {"rb"}, "c": {"c", "h"}, "cpp": {"cc", "cpp", "cxx", "hh", "hpp"},
    "csharp": {"cs"}, "swift": {"swift"}, "scala": {"scala"}, "php": {"php"}, "sql": {"sql"},
    "lua": {"lua"}, "dart": {"dart"}, "groovy": {"groovy"}, "gradle": {"gradle"}, "protobuf": {"proto"},
    "html": {"html", "htm", "vue"}, "xml": {"xml", "svg", "plist"}, "css": {"css"}, "scss": {"scss"},
    "less": {"less"}, "toml": {"toml"}, "ini": {"ini", "cfg"}, "diff": {"diff", "patch"},
    "asciidoc": {"adoc"}, "makefile": {"mk"}, "powershell": {"ps1"}, "perl": {"pl", "pm"},
    "r": {"r"}, "haskell": {"hs"}, "elm": {"elm"}, "elixir": {"ex", "exs"}, "graphql": {"graphql", "gql"},
}


def fence_lang(path):
    """その file の枠に付ける言語名（highlight.js の名前）。表に無い種類は拡張子そのまま、拡張子の無い file は plaintext。"""
    base = path.rsplit("/", 1)[-1].lower()
    if base.startswith("dockerfile") or base.endswith(".dockerfile"):
        return "dockerfile"
    if base in ("makefile", "gnumakefile"):
        return "makefile"
    ext = _ext(path)
    for lang, exts in FENCE_BY_EXT.items():
        if ext in exts:
            return lang
    return ext if ext and ext not in ("txt", "text") else "plaintext"


def lang_tag(path):
    """枠の見出しの末尾に置く（言語名 X）。AI はこれを ```X に写す。"""
    return f"（言語名 {fence_lang(path)}）"


def comment_marks(path):
    """その file のコメントの (前, 後)。知らない種類は #。"""
    ext = _ext(path)
    for marks, exts in COMMENT_BY_EXT.items():
        if ext in exts:
            return marks
    return "#", ""


def is_prose(path):
    """散文・設定（md・txt・json など）。関数が無く git diff -W の文脈が file 全体に広がるので、diff は
    文脈 PROSE_CONTEXT 行で取る（frame_diff）。枠と飛び先はコードと同じに出す。"""
    return _ext(path) in PROSE_EXT


def band(marks, indent, glyph, label, fill):
    """帯 1 本。全幅 FRAME_WIDTH に東アジア幅で揃える。字下げの tab は空白 4 つに（帯は機械の行なので
    変えてよい。tab のままだと端末で 7 桁はみ出す）。"""
    pre, suf = marks
    head = indent.expandtabs(4) + pre + " " + glyph + fill * 2 + (f" {label} " if label else "")
    return head + fill * max(FRAME_WIDTH - width(head) - width(suf), 2) + suf


def old_line(marks, text):
    """前の行を `#│ ` の印で薄く見せる。先頭の空白を印の長さまで置き換えて、今の行と桁を揃える
    （字下げが印より浅い行は最大 1 桁ずれる）。"""
    pre, suf = marks
    lead = pre + "│ "
    strip = min(len(lead), len(text) - len(text.lstrip(" ")))
    return lead + text[strip:] + suf


def _indent_of(text):
    return text[:len(text) - len(text.lstrip())]


def common_indent(texts):
    """空でない行に共通の字下げ（先頭の空白の共通接頭辞）。枠に写す前に落とす分——深い入れ子の関数は字下げだけで
    1 行 60 桁の予算を食い、当の行が `…` で切れる（実測: 28 桁の字下げの行 `"thread_id": str(run.thread_id),` が
    61 桁で、AI が 60 桁に切ると確かめたい `id),` が落ちた）。落とした桁数は呼び手が見出しに書く。"""
    indents = [_indent_of(t) for t in texts if t.strip()]
    return os.path.commonprefix(indents) if indents else ""


def dedent(texts, prefix):
    """共通の字下げ prefix を落とす。prefix で始まらない行（空行）はそのまま。"""
    return [t[len(prefix):] if prefix and t.startswith(prefix) else t for t in texts]


# 複数行の文字列リテラル（SQL・テンプレート）の中身は枠の行数を食うが、読む人が判断に使わない（実測: 候補 repository
# の save() 70 行のうち 45 行が INSERT の列名の 2 度書き）。代入や引数の後ろで始まるもの（`query = """`・`(f"""`）
# だけ畳み、行頭（字下げの直後）から始まるもの（docstring・裸の文字列）は作者の言葉なので畳まない
LITERAL_FOLD_MIN = 8    # 中の行数（両端を除く）がこれを超えたら畳む
LITERAL_KEEP_HEAD = 3   # 畳むとき、中の先頭に残す行数
LITERAL_KEEP_TAIL = 1   # 畳むとき、中の末尾に残す行数
LITERAL_DELIMS_BY_EXT = {
    ('"""', "'''"): {"py", "pyi"},
    ('"""',): {"kt", "kts", "scala", "java", "groovy"},
    ("`",): {"ts", "tsx", "js", "jsx", "mjs", "go"},
}


def literal_delims(path):
    ext = _ext(path)
    return next((d for d, exts in LITERAL_DELIMS_BY_EXT.items() if ext in exts), ())


def literal_ranges(texts, path):
    """畳める文字列リテラルの位置 [(開く行の index, 閉じる行の index)]。中（両端を除く）が LITERAL_FOLD_MIN 行を
    超えるものだけ。開く行で区切り記号が奇数回出れば開き（同じ行で閉じるものは対象外）。行頭から始まるものは
    docstring とみて記録しないが、閉じる行を次の開きと読まないよう、中に居ることは追う。"""
    delims = literal_delims(path)
    if not delims:
        return []
    out, open_i, open_d, record = [], None, None, False
    for i, t in enumerate(texts):
        if open_i is None:
            for d in delims:
                if t.count(d) % 2 == 1:
                    open_i, open_d, record = i, d, not t.lstrip().startswith(d)
                    break
            continue
        if open_d in t:
            if record and i - open_i - 1 > LITERAL_FOLD_MIN:
                out.append((open_i, i))
            open_i, open_d, record = None, None, False
    return out


def _fold_ranges(texts, path, ranges):
    """ranges の中を畳んで [(元の index か None, 行)]。None は点線（畳んだ印。帯と同じ形で、文字列の中と行数を書く）。"""
    marks = comment_marks(path)
    rows, pos = [], 0
    for o, c in ranges:
        keep_to = o + 1 + LITERAL_KEEP_HEAD
        rows.extend((k, texts[k]) for k in range(pos, keep_to))
        rows.append((None, band(marks, _indent_of(texts[o + 1]), "┅",
                                f"文字列の中 {c - keep_to - LITERAL_KEEP_TAIL} 行省略", "┅")))
        pos = c - LITERAL_KEEP_TAIL
    rows.extend((k, texts[k]) for k in range(pos, len(texts)))
    return rows


def fold_literals(texts, path):
    """行の列の、畳める文字列リテラルの中を畳む。戻りは [(元の index か None, 行)]——呼び手が行番号を付け直せる。"""
    return _fold_ranges(texts, path, literal_ranges(texts, path))


def fold_literal_items(items, path):
    """frame_hunk の items [(印, 行)] で、変わっていない行だけの文字列リテラルの中を畳む。変更を含むリテラルは
    畳まない（変わった行を隠す）。点線は印 " "（変わっていない行）として後段に流す。"""
    texts = [t for _, t in items]
    ranges = [(o, c) for o, c in literal_ranges(texts, path) if all(m == " " for m, _ in items[o + 1:c])]
    if not ranges:
        return items
    return [(items[k][0], t) if k is not None else (" ", t) for k, t in _fold_ranges(texts, path, ranges)]


def _fold(run, marks, fold):
    """変わっていない行の列。畳むなら前後 FOLD_KEEP 行を残して点線。"""
    if not fold or len(run) <= FOLD_KEEP * 2 + 1:
        return list(run)
    dropped = len(run) - FOLD_KEEP * 2
    return [*run[:FOLD_KEEP], band(marks, _indent_of(run[FOLD_KEEP]), "┅", f"{dropped} 行省略", "┅"),
            *run[-FOLD_KEEP:]]


def _segment(items, marks):
    """変わった区間 1 つを枠にする。中は、前の行（コメント）→ 今の行。間の変わっていない行はそのまま。"""
    kinds = {m for m, _ in items if m != " "}
    label = "追加" if kinds == {"+"} else "削除" if kinds == {"-"} else "変更"
    same = sum(1 for m, _ in items if m == " ")
    if same:
        label += f"（変わっていない {same} 行を挟む）"  # 近い変更を 1 枠にまとめた印。枠の中の行数と照らせる
    # 帯の字下げは区間の中で一番浅い行に合わせる（深い行に合わせると、浅い行を囲む帯が中に食い込む）
    indent = min((_indent_of(t) for _, t in items if t.strip()), key=len, default="")
    out = [band(marks, indent, "┏", label, "━")]
    olds = []

    def flush():
        if len(olds) > OLD_CAP:
            out.extend(old_line(marks, t) for t in olds[:3])
            out.append(band(marks, indent, "┅", f"前の行 {len(olds) - 3} 行省略", "┅"))
        else:
            out.extend(old_line(marks, t) for t in olds)
        olds.clear()

    for m, t in items:
        if m == "-":
            olds.append(t)
        else:
            flush()
            out.append(t)
    flush()
    out.append(band(marks, indent, "┗", "", "━"))
    return out


def frame_hunk(path, lines):
    """1 つの hunk（-W で取れば関数まるごと）を「今の姿＋帯」にする。lines は '+'/'-'/' ' で始まる行
    （@@ の行は無視）。返すのは貼れる行の列。今の行は 1 文字も変えない。"""
    marks = comment_marks(path)
    # 空行は文脈（diff は空の文脈行を " " で出すが、"" で来ても変更に数えない）
    items = [((ln[:1] or " "), ln[1:]) for ln in lines if (ln[:1] or " ") in "+- "]
    items = fold_literal_items(items, path)
    changed = [i for i, (m, _) in enumerate(items) if m != " "]
    if not changed:
        return [t for _, t in items]
    segs, start, prev = [], changed[0], changed[0]
    for i in changed[1:]:
        if i - prev - 1 > FRAME_GAP:
            segs.append((start, prev))
            start = i
        prev = i
    segs.append((start, prev))
    fold = len(items) > FRAME_WHOLE
    out, pos = [], 0
    for s, e in segs:
        out.extend(_fold([t for _, t in items[pos:s]], marks, fold))
        out.extend(_segment(items[s:e + 1], marks))
        pos = e + 1
    out.extend(_fold([t for _, t in items[pos:]], marks, fold))
    return out


HUNK_RE = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@")


def framed_diff(text):
    """git diff（frame_diff 推奨）の全文を、path → {"new": 新規か, "blocks": [hunk ごとの枠の行],
    "gaps": [hunk の間の行数], "starts": [hunk の新側の開始行。None は飛び先を置かない]} にする。全行が
    + の file（新規）は帯を入れず 1 枠で、starts は [1]——印は何も伝えないが、開く場所は要る。飛び先が
    無いのは file ごと削除（新側が 0 行）だけ——head にその file がもう無いので開けない。blocks と
    starts は同じ hunk から同時に足すので長さが揃う。

    starts は AI が箇所の見出し（path:行）と枠の上の注釈に写す飛び先。-W なら関数の先頭、文脈 3 行の
    diff（gh pr diff）なら変更の 3 行前で、def の行とは限らない——それでも端末で開けば変更はすぐ下にある。"""
    files, _ = split_diff(text)
    out = {}
    for path, lines in files.items():
        body = [ln or " " for ln in lines if (ln[:1] or " ") in "+- "]
        if not body:
            continue
        if all(ln.startswith("+") for ln in body):
            out[path] = {"new": True, "blocks": [[ln[1:] for ln in body]], "gaps": [], "starts": [1]}
            continue
        blocks, gaps, starts, cur, start, prev_end = [], [], [], [], None, None
        for ln in lines:
            m = HUNK_RE.match(ln)
            if m:
                if cur:
                    blocks.append(cur)
                    starts.append(start)
                cur = []
                head, count = int(m.group(1)), int(m.group(2) or 1)
                # 新側が 0 行（file ごと削除）なら head に開く行が無い——飛び先は置かない
                start = head if count else None
                if prev_end is not None:
                    gaps.append(max(head - prev_end, 0))
                prev_end = head + count
            elif (ln[:1] or " ") in "+- ":
                cur.append(ln or " ")
        if cur:
            blocks.append(cur)
            starts.append(start)
        out[path] = {"new": False, "blocks": [frame_hunk(path, b) for b in blocks], "gaps": gaps,
                     "starts": starts}
    return out


def cap_note(frame_cmd="--frame"):
    """1 file の上限の断り。frame_cmd は続きを出す呼び手のコマンド（呼び手ごとに違う）。"""
    return f"。1 file {FRAME_FILE_CAP} 行を超えたら関数の切れ目で止めて、続きは {frame_cmd} path で"


FRAME_CAP_NOTE = cap_note()
# 飛び先の断り。/catchup の地図と /what-am-i-doing の変更の中身が、見出しの括弧に同じ文で入れる
JUMP_NOTE = ("各枠の前の『飛び先 path:行』は head（手元）の行番号。AI は箇所の見出しと枠の上の注釈に写す。"
             "path の前後は半角スペースで離す（端末のクリックが隣の文字を巻き込む）")


def frame_lines(path, info, cap=FRAME_FILE_CAP, indent="    ", frame_cmd="--frame"):
    """join_frames の列を、出力に貼る形（字下げ＋prefix＋行）にした文字列の列。"""
    return [indent + prefix + ln for prefix, ln in join_frames(path, info, cap, frame_cmd)]


def head_and_outline(path, lines, more=""):
    """新規 file の材料——先頭コメント / docstring（作者の自己紹介）と骨組み。全行が新しいので枠は何も
    伝えない。返すのは join_frames と同じ (prefix, text) の列（"| " は貼る行、"" は機械の説明）。more は
    先頭が切れたときに添える、続きを読む場所。飛び先は先頭行（新規は 1 行目から読む）。"""
    out = [("", f"飛び先 {path}:1")]
    head, cut = file_head(path, lines)
    out.extend(("| ", ln) for ln in head)
    if not head:
        out.append(("", "（先頭にコメントも docstring も無い）"))
    elif cut:
        out.append(("", f"（先頭は {HEAD_LINES} 行で切った{more}）"))
    ol = outline(path, lines)
    if ol:
        out.append(("", "骨組み:"))
        out.extend(("| ", ln) for ln in ol[:OUTLINE_CAP])
        if len(ol) > OUTLINE_CAP:
            out.append(("", f"（骨組みは他に {len(ol) - OUTLINE_CAP} 行）"))
    return out


def join_frames(path, info, cap=FRAME_FILE_CAP, frame_cmd="--frame"):
    """1 file の枠を、hunk の間に点線を挟んで 1 列にする。cap を超えるなら関数の切れ目で止め、残りを
    申告する（関数の途中では切らない）。返すのは (prefix, text) の列。"| " は貼る行、"" は機械の説明。

    各枠の前に「飛び先 path:行」を機械の説明として 1 行置く（枠の行には触らない）。行は framed_diff の
    starts＝hunk の新側の開始行で、AI が箇所の見出しと枠の上の注釈に写す。head に行が無い枠（file ごと
    削除）にだけ置かない。"""
    marks = comment_marks(path)
    out, total = [], 0
    for i, block in enumerate(info["blocks"]):
        # 先頭の枠も上限に掛ける——掛けないと、file 全体が 1 つの hunk になる書き換え（散文でよく起きる）が
        # 上限ゼロで全部出る（実測: 1000 行の枠が 300 行の上限を素通りした）
        if cap and total + len(block) > cap:
            rest = info["blocks"][i:]
            out.append(("", f"（残り {len(rest)} 枠 {sum(len(b) for b in rest)} 行は"
                            f" {frame_cmd} {path} で全部出る）"))
            break
        if i:
            gap = info["gaps"][i - 1] if i - 1 < len(info["gaps"]) else 0
            out.append(("| ", band(marks, "", "┅", f"{gap} 行省略" if gap else "別の関数", "┅")))
        if info["starts"][i] is not None:
            out.append(("", f"飛び先 {path}:{info['starts'][i]}"))
        out.extend(("| ", ln) for ln in block)
        total += len(block)
    return out


# 読み手の git 設定で diff の形が変わるのを止める。color.ui=always は tty でなくても ANSI を出し、
# diff.external と .gitattributes の diff driver は unified diff を出さず、textconv は行を書き換える。
# 前の 2 つは split_diff の "diff --git " 一致を外して全 file が「中身が diff に無い」という嘘の断りになり、
# textconv は嘘の行を枠に貼る（どれも実測）。他人の checkout（fork）は相手の .gitattributes を持つ
DIFF_SANE = ("--no-color", "--no-ext-diff", "--no-textconv")
# pathspec は既定で glob と magic を解釈する。`*` や `[` を含む file 名が別の file に当たり、先頭が `:` の
# path は magic として読まれる。:(top,literal) で literal 固定・リポジトリの根からの相対にする
# （cwd が下の階層でも、git が返す path はいつも根からなので）


def pathspecs(names):
    return [f":(top,literal){n}" for n in names]


def changed_pairs(cwd=None, rev="HEAD"):
    """rev と比べて変わった file を [(振り分けに使う path, git に渡す path の組)]。改名は新旧を 1 組で
    返す——新側だけを pathspec に渡すと git が対を作れず、中身の変更が消えて全行 + の「新規」diff に
    なる（実測）。-z なので path は引用形にならない。失敗なら None。"""
    text = git("-c", "core.quotePath=false", "diff", *DIFF_SANE, "--name-status", "-z", rev, "--", cwd=cwd)
    if text is None:
        return None
    parts = [p for p in text.split("\0") if p]
    out, i = [], 0
    while i + 1 < len(parts):
        if parts[i][:1] in ("R", "C"):     # R100\0旧\0新
            out.append((parts[i + 2], (parts[i + 1], parts[i + 2])))
            i += 3
        else:
            out.append((parts[i + 1], (parts[i + 1],)))
            i += 2
    return out


def frame_diff(cwd=None, rev="HEAD", paths=()):
    """枠のための diff。コードは関数まるごと（git diff -W）、散文・設定は文脈 PROSE_CONTEXT 行（-W は関数の境目を
    探すので、境目の無い file では文脈が file 全体に広がる）。rev は比べる元（手元なら HEAD、PR なら
    base...head）。paths を省くと rev の変更 file を git に聞いて振り分ける（改名は新旧を同じ側に入れる
    ——割ると対が作れない）。どれか 1 本でも失敗したら None（半分の diff を返すと、落ちた側の file が
    「変更なし」に見える）。"""
    pairs = [(p, (p,)) for p in paths] if paths else changed_pairs(cwd=cwd, rev=rev)
    if pairs is None:
        return None
    parts = []
    for flag, group in ((("-W",), [g for key, g in pairs if not is_prose(key)]),
                        ((f"-U{PROSE_CONTEXT}",), [g for key, g in pairs if is_prose(key)])):
        names = [n for g in group for n in g]
        if not names:
            continue
        text = git("-c", "core.quotePath=false", "diff", *DIFF_SANE, *flag, rev, "--",
                   *pathspecs(names), cwd=cwd)
        if text is None:
            return None
        parts.append(text)
    return "".join(parts)


# ---- 手元の git ------------------------------------------------------------------


def run(*args, cwd=None, timeout=15, env=None):
    """git を呼んで (終了コード, stdout, stderr) を返す。失敗の言い分（stderr）が要るとき用（/catchup の
    git switch）。git が無い・timeout・起動できないなら (None, "", 理由)。timeout は読むだけの呼び出し用
    ——書く操作（switch）は timeout=None で呼ぶ。途中で殺すと書きかけの木と index.lock が残る（実測）。
    stdin は閉じる（hook や filter が入力待ちで固まらない）。env は環境に足す変数（/catchup の fetch が
    GIT_TERMINAL_PROMPT=0 を足す。git は認証を stdin でなく端末に聞くので、stdin を閉じるだけでは固まる）。"""
    exe = shutil.which("git")
    if not exe:
        return None, "", "git が見つからない"
    try:
        r = subprocess.run(  # noqa: S603 — git は which で解決。引数は呼び手のリテラルと path・ブランチ名だけ
            [exe, *args], cwd=cwd, capture_output=True, encoding="utf-8", errors="replace",
            timeout=timeout, stdin=subprocess.DEVNULL, env={**os.environ, **env} if env else None,
        )
    except subprocess.TimeoutExpired:
        return None, "", f"{timeout} 秒で応答が無い"
    except (OSError, subprocess.SubprocessError) as e:
        return None, "", str(e)
    return r.returncode, r.stdout, r.stderr


def git(*args, cwd=None):
    """git を呼ぶ。無い・失敗なら None（地図の材料は無くても本体の報告は成り立つ）。"""
    rc, out, _ = run(*args, cwd=cwd)
    return out if rc == 0 else None


def repo_top(cwd=None):
    out = git("rev-parse", "--show-toplevel", cwd=cwd)
    return out.strip() if out else None


def has_commit(oid, cwd=None):
    """commit oid を手元に持っているか（^{commit} で tag / blob を除く）。oid が無ければ False。"""
    return bool(oid) and git("cat-file", "-e", f"{oid}^{{commit}}", cwd=cwd) is not None


def current_branch(cwd=None):
    """今のブランチ名。detached なら ""、読めなければ None（区別が要らない呼び手は or "" で受ける）。"""
    out = git("branch", "--show-current", cwd=cwd)
    return out.strip() if out is not None else None


def origin_url(top):
    """origin の URL。無ければ ""。"""
    return (git("remote", "get-url", "origin", cwd=top) or "").strip()


# remote URL の末尾「<区切り><owner>/<name>[.git]」。読む（origin_is）のと差し替える（swap_repo）のとで
# 同じ形を 2 度書かないための 1 本——ssh の : ・.git・末尾 / の扱いが、片方だけ直る余地を無くす
REPO_TAIL = re.compile(r"([:/])([^/:]+)/([^/]+?)(\.git)?/?$")


def origin_is(url, owner, name):
    """url が owner/name か。末尾 2 セグメントの等値で見る——部分一致だと org/platform-docs の
    checkout を org/platform と誤認し、別リポジトリの名前が「同じ階層の既存」に混ざる（実測）。"""
    m = REPO_TAIL.search(url.strip())
    return bool(m) and (m.group(2).lower(), m.group(3).lower()) == (owner.lower(), name.lower())


def swap_repo(url, repo):
    """remote URL の owner/name を repo（"owner/name"）に差し替える。scheme・host・.git はそのまま
    （/catchup が origin の URL から fork の URL を作る。API の url を使わないのは、origin と同じ
    scheme・認証を引き継ぐため）。"""
    return REPO_TAIL.sub(lambda m: m.group(1) + repo + (m.group(4) or ""), url.strip())


def origin_matches(top, owner, name):
    """手元の checkout の origin が owner/name か。"""
    return origin_is(origin_url(top), owner, name)


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
    for c in changed:
        ctoks |= _tokens(c)
    cexts = {e for e in map(_ext, changed) if e}
    def score(n):
        ext = _ext(n)
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
        note = change_note(mark, *numstat.get(path, (None, None)),
                           whole_dir=whole_dir,
                           old=rest.split(" -> ", 1)[0] if " -> " in rest else None)
        entries.append({"path": path, "mark": mark, "note": note})
    return entries


def change_note(mark, a, d, whole_dir=False, old=None):
    """木の行の右に出す ±行数（と改名の旧名）。手元の未コミットと commit の両方が使う。"""
    if mark == "+" and a is None:
        note = "新規（階層ごと。中は git status -uall で）" if whole_dir else "新規"
    elif a is None:
        note = ""
    elif mark == "-":
        note = f"-{d}"
    else:
        note = f"+{a}" if not d else f"+{a}/-{d}"
    return (note + "  " if note else "") + "旧: " + old if old else note


def working_tree(cwd=None):
    """手元の未コミットの変更を (パスの一覧, 木の行) で返す。変更が無ければ ([], [])。
    /catchup（今のブランチで呼んだとき）と /what-am-i-doing が共用。"""
    # -uall: 未追跡の階層を中のファイルに展開する（既定は "newdir/" の 1 行で、木に名前の無い行が出る）
    porcelain = git("status", "--porcelain", "--untracked-files=all", cwd=cwd) or ""
    entries = entries_from_porcelain(
        porcelain, parse_numstat(git("-c", "core.quotePath=false", "diff", *DIFF_SANE, "HEAD",
                                     "--numstat", cwd=cwd)))
    if not entries:
        return [], []
    top = repo_top(cwd)
    sib = siblings_for(top, [e["path"] for e in entries]) if top else None
    label = os.path.basename(top) if top else "."
    return [e["path"] for e in entries], render_tree(entries, sib, root_label=label)


EMPTY_TREE = "4b825dc642cb6eb9a060e54bf8d69288fbee4904"  # git の空の木。最初の commit には親が無い


def branch_exists(token, cwd=None):
    """token が手元の枝か、origin にだけ有る枝か。枝なら「移る」対象（仕様の原則 1）で、commit より先に見る。
    照合は show-ref の完全一致——rev-parse だと HEAD~1 が refs/remotes/origin/HEAD の親に解けて枝扱いになる（実走で実測。
    仕様 3 節: HEAD~n は commit で、枝が勝つのは同じ語が枝の名前のときだけ）。HEAD は枝ではない（origin/HEAD は
    symbolic ref で show-ref に通る）。"""
    if token == "HEAD":
        return False
    for ref in (f"refs/heads/{token}", f"refs/remotes/origin/{token}"):
        if git("show-ref", "--verify", "--quiet", ref, cwd=cwd) is not None:
            return True
    return False


def default_branch_ref(cwd=None):
    """既定ブランチの追跡 ref（origin/main など）。origin/HEAD が無ければ origin/main・origin/master を試す。"""
    out = git("symbolic-ref", "--quiet", "refs/remotes/origin/HEAD", cwd=cwd)
    if out and out.strip().startswith("refs/remotes/"):
        return out.strip()[len("refs/remotes/"):]
    for cand in ("origin/main", "origin/master"):
        if git("rev-parse", "--verify", "--quiet", cand, cwd=cwd) is not None:
            return cand
    return None


def commit_oid(token, cwd=None):
    """token が指す commit の oid（sha・HEAD~2・タグ・ブランチ名も通る）。commit でなければ None。"""
    out = git("rev-parse", "--verify", "--quiet", f"{token}^{{commit}}", cwd=cwd)
    return (out or "").strip() or None


def commit_range(oid, cwd=None):
    """その commit 1 つ分の diff の範囲。親が無い（最初の commit）なら空の木と比べる。
    merge commit は第 1 親との差（git show の既定と同じ）。"""
    parent = git("rev-parse", "--verify", "--quiet", f"{oid}^", cwd=cwd)
    return f"{(parent or '').strip() or EMPTY_TREE}..{oid}"


def commit_tree(rev, cwd=None):
    """commit（範囲）の変更を (パスの一覧, 木の行) で。working_tree の commit 版で、
    出す形は同じ——読む人が「手元の木」と「commit の木」で読み方を変えなくていい。"""
    text = git("-c", "core.quotePath=false", "diff", *DIFF_SANE, "--name-status", "-z",
               rev, "--", cwd=cwd)
    if text is None:
        return [], []
    nums = parse_numstat(git("-c", "core.quotePath=false", "diff", *DIFF_SANE, "--numstat",
                             rev, "--", cwd=cwd))
    parts = [p for p in text.split("\0") if p]
    entries, i = [], 0
    while i + 1 < len(parts):
        status = parts[i]
        old = parts[i + 1] if status[:1] in ("R", "C") else None
        path = parts[i + 2] if old else parts[i + 1]
        i += 3 if old else 2
        mark = {"A": "+", "D": "-"}.get(status[:1], "~")
        entries.append({"path": path, "mark": mark,
                        "note": change_note(mark, *nums.get(path, (None, None)), old=old)})
    if not entries:
        return [], []
    top = repo_top(cwd)
    sib = siblings_for(top, [e["path"] for e in entries]) if top else None
    return ([e["path"] for e in entries],
            render_tree(entries, sib, root_label=os.path.basename(top) if top else "."))


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


def tracked_set(cwd, paths):
    """paths のうち index が追跡しているもの。1 回の ls-files で（file ごとに聞くと N 回 spawn する）。
    -z は path を引用形にしないため（日本語名が集合と一致する）。paths が空だと ls-files は全 file を
    列挙するので、空集合を返す。"""
    if not paths:
        return set()
    out = git("ls-files", "-z", "--", *paths, cwd=cwd) or ""
    return set(filter(None, out.split("\0")))


def new_file_rows(cwd, path, kind, frame_cmd="--frame"):
    """新規 file（未追跡・add 済み）の見出しと、先頭コメント・骨組み。file が読めなければ []。"""
    full = pathlib.Path(cwd) / path
    if not full.is_file():
        return []
    try:
        lines = full.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []
    rows = head_and_outline(path, lines, more=f"。続きは {frame_cmd} {path} か file を開く")
    return [f"    === {path} （{kind}。{len(lines)} 行。先頭と骨組みだけ——全文は {frame_cmd} {path} か file を開く）"
            + lang_tag(path)] \
        + ["    " + prefix + ln for prefix, ln in rows]


def frames_section(cwd, paths, rev="HEAD", frame_cmd="--frame", new_from_file=True, jump_note=JUMP_NOTE):
    """変更の中身を枠で（コードは関数まるごと、散文・設定は前後 PROSE_CONTEXT 行）。/what-am-i-doing の
    「変更の中身」、/catchup の手元だけの報告、/catchup の commit が共用する。rev は比べる元
    （手元なら HEAD、commit なら 親..その commit）、frame_cmd は続きを出す呼び手のコマンド。
    new_from_file が真なら新規 file は手元の file から先頭と骨組みだけ（未コミットの新規は diff に
    無いか全行 + で、枠が何も伝えない）。偽なら diff の中身をそのまま枠にする（commit の新規）。
    追跡 file で diff に hunk が無ければ（バイナリ・mode・改名だけ）その旨。"""
    out = []
    w = out.append
    text = frame_diff(cwd=cwd, rev=rev)
    if text is None:
        # 失敗を "" で飲むと、全 file を「中身が diff に無い」と嘘の断りで断定する（実測）
        return ["  変更の中身: 出せない（git diff が失敗した。木と件数だけが上の材料）"]
    frames = framed_diff(text)
    hunks, _ = split_diff(text)
    dirty = paths
    tracked = tracked_set(cwd, dirty) if new_from_file else set(dirty)
    w("  変更の中身（" + FRAME_NOTE + cap_note(frame_cmd)
      + f"。合計は {FRAME_TOTAL_CAP} 行まで。" + jump_note + "）:")
    total = 0
    for path in sorted(dirty):
        info = frames.get(path)
        if info is None and path in tracked:
            w(f"    === {path} （中身が diff に無い。バイナリ・mode・改名だけ）")
            continue
        if info is None or (info["new"] and new_from_file):
            out.extend(new_file_rows(cwd, path, "add 済みの新規" if info else "未追跡の新規", frame_cmd))
            continue
        if info["new"] and not new_from_file and sum(map(len, info["blocks"])) > FRAME_FILE_CAP:
            # commit・範囲の新規 file が 1 file の上限を超えると、枠は「残り 1 枠 N 行」の案内だけになって何も
            # 伝えない（実測: 346 行の仕様書）。PR の地図と同じく先頭と骨組みを出し、全文は frame_cmd で
            added = added_lines(hunks.get(path, []))
            w(f"    === {path} （新規。{len(added)} 行。先頭と骨組みだけ——全文は {frame_cmd} {path}）" + lang_tag(path))
            out.extend("    " + prefix + ln for prefix, ln in
                       head_and_outline(path, added, more=f"。続きは {frame_cmd} {path}"))
            continue
        rows = frame_lines(path, info, frame_cmd=frame_cmd)
        # 足してから判定する（足す前に見ると、最後の 1 file の分だけ上限を必ず超える）。先頭の file は
        # それ 1 本で超えても出す——1 file も出さずに「上限」とだけ言う出力は材料にならない
        if total and total + len(rows) > FRAME_TOTAL_CAP:
            w(f"    === {path} （合計の上限。{frame_cmd} {path} で出る）")
            continue
        w(f"    === {path} {lang_tag(path)}")
        out.extend(rows)
        total += len(rows)
    return out
