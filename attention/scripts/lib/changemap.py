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
# そこで判断を止める（実測）。長い関数だけ、変わっていない区間を点線で畳む。

FRAME_WIDTH = 78   # 帯の全幅（字下げ込み。東アジア幅で数える）
FRAME_GAP = 3      # 変わっていない行がこの数以内で隣り合う変更は 1 つの枠
FRAME_WHOLE = 100  # hunk（-W なら関数まるごと）がこの行数以内なら畳まず全部出す
FOLD_KEEP = 10     # 畳むとき、変更の前後に残す行数
OLD_CAP = 15       # 枠の中に残す前の行の上限。超えたら先頭 3 行と行数
FRAME_FILE_CAP = 300  # 1 file の枠の行数の目安。超えたら関数の切れ目で止めて、残りは --frame で
FRAME_TOTAL_CAP = 800  # 変更の中身の合計の目安。超えた file は名前だけ（大きい変更で報告が材料に埋もれない）
FRAME_NOTE = ("今の姿に機械が帯を入れた。実線の枠 ┏…┗ が変わった所で、中の行頭が `#│`（コメント記号＋│）の"
              "行は前・色の行は今。間 3 行以内の変更は 1 枠で、挟まった変わっていない行の数は帯に書いてある。"
              "点線 ┅ は畳んだ区間。`| ` の後ろをそのまま言語の枠に貼る")
COMMENT_BY_EXT = {
    ("//", ""): {"ts", "tsx", "js", "jsx", "mjs", "go", "java", "kt", "kts", "c", "h", "cc", "cpp",
                 "hpp", "cs", "rs", "swift", "scala", "php", "hcl", "tf", "tfvars", "groovy", "dart",
                 "proto", "json", "jsonc", "scss", "less", "sass"},
    ("--", ""): {"sql", "lua", "hs", "elm"},
    ("/*", " */"): {"css"},
    ("<!--", " -->"): {"md", "html", "htm", "xml", "svg", "vue"},  # 散文・markup。AI は散文なら枠でなく文で言う
}
PROSE_EXT = {"md", "txt", "adoc", "rst", "html", "htm", "xml", "json", "jsonc", "csv", "lock"}


def comment_marks(path):
    """その file のコメントの (前, 後)。知らない種類は #。"""
    ext = _ext(path)
    for marks, exts in COMMENT_BY_EXT.items():
        if ext in exts:
            return marks
    return "#", ""


def is_prose(path):
    """散文・設定（md・txt・json など）。関数が無く git diff -W の文脈が file 全体に広がるので、既定の
    出力では枠を出さず 1 行で済ませる（AI も散文は文で言う）。--frame なら出す。"""
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
    """git diff（-W 推奨）の全文を、path → {"new": 新規か, "blocks": [hunk ごとの枠の行], "gaps": [hunk の
    間の行数]} にする。全行が + の file（新規）は帯を入れない——全部が追加で、印が何も伝えない。"""
    files, _ = split_diff(text)
    out = {}
    for path, lines in files.items():
        body = [ln or " " for ln in lines if (ln[:1] or " ") in "+- "]
        if not body:
            continue
        if all(ln.startswith("+") for ln in body):
            out[path] = {"new": True, "blocks": [[ln[1:] for ln in body]], "gaps": []}
            continue
        blocks, gaps, cur, prev_end = [], [], [], None
        for ln in lines:
            m = HUNK_RE.match(ln)
            if m:
                if cur:
                    blocks.append(cur)
                cur = []
                start, count = int(m.group(1)), int(m.group(2) or 1)
                if prev_end is not None:
                    gaps.append(max(start - prev_end, 0))
                prev_end = start + count
            elif (ln[:1] or " ") in "+- ":
                cur.append(ln or " ")
        if cur:
            blocks.append(cur)
        out[path] = {"new": False, "blocks": [frame_hunk(path, b) for b in blocks], "gaps": gaps}
    return out


FRAME_CAP_NOTE = f"。1 file {FRAME_FILE_CAP} 行を超えたら関数の切れ目で止めて、続きは --frame path で"


def frame_lines(path, info, cap=FRAME_FILE_CAP, indent="    "):
    """join_frames の列を、出力に貼る形（字下げ＋prefix＋行）にした文字列の列。"""
    return [indent + prefix + ln for prefix, ln in join_frames(path, info, cap)]


def prose_skip(path, where):
    """散文・設定の file に枠を出さないときの断り。where は「何を言うようになったか」を読む場所
    （PR なら本文と先頭コメント、手元なら file）。"""
    return f"（散文・設定。枠は出さない——何を言うようになったかは{where}。--frame {path} で枠は出る）"


def head_and_outline(path, lines, more=""):
    """新規 file の材料——先頭コメント / docstring（作者の自己紹介）と骨組み。全行が新しいので枠は何も
    伝えない。返すのは join_frames と同じ (prefix, text) の列（"| " は貼る行、"" は機械の説明）。more は
    先頭が切れたときに添える、続きを読む場所。"""
    out = []
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


def join_frames(path, info, cap=FRAME_FILE_CAP):
    """1 file の枠を、hunk の間に点線を挟んで 1 列にする。cap を超えるなら関数の切れ目で止め、残りを
    申告する（関数の途中では切らない）。返すのは (prefix, text) の列。"| " は貼る行、"" は機械の説明。"""
    marks = comment_marks(path)
    out, total = [], 0
    for i, block in enumerate(info["blocks"]):
        if cap and out and total + len(block) > cap:
            rest = info["blocks"][i:]
            out.append(("", f"（残り {len(rest)} 関数 {sum(len(b) for b in rest)} 行は --frame {path} で全部出る）"))
            break
        if i:
            gap = info["gaps"][i - 1] if i - 1 < len(info["gaps"]) else 0
            out.append(("| ", band(marks, "", "┅", f"{gap} 行省略" if gap else "別の関数", "┅")))
        out.extend(("| ", ln) for ln in block)
        total += len(block)
    return out


def function_diff(cwd=None, rev="HEAD", paths=()):
    """関数まるごとを文脈にした diff（git diff -W）。rev は比べる元（手元なら HEAD、PR なら
    base...head）。無い・失敗なら None。"""
    return git("-c", "core.quotePath=false", "diff", "-W", rev, "--", *paths, cwd=cwd)


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
