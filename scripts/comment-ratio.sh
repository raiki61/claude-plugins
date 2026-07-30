#!/usr/bin/env bash
# 対象差分の追加行に占める注釈（コメント・docstring）の行数と比率を出す。
# 数えるのは Python と C 系コメント（`//` `/* */`）の言語だけ——それ以外（`#` 系の
# Ruby・Shell 等）と文書は、行数で別に測れ。
#
# review-loop の P4（ratchet 検出の scalar 記録）が使う。ラウンド間で比べるのが目的なので、
# 誰がいつ測っても同じ数字が出ることが要件——手計測に戻すとその前提が崩れる。
#
# **未追跡の新規ファイルは事前に `git add -N` で差分に載せろ。** 載せないと git diff に
# 現れないので、載っていない対象言語のファイルを見つけたら数えずに exit 2 で止まる
# （計測漏れのある数字と、本当に対象ファイルが無い正常系が同じ出力になるのを防ぐ）。
#
# 使い方: bash comment-ratio.sh <BASE の SHA> [<比較先の ref>]
#   比較先を省略すると作業ツリーと比べる。
#
# 終了コード: 0 測れた / 2 測れなかった。**計測不成立を 0 で返すな**——「注釈 0%」と
# 区別が付かず、測れていない数字がラウンド間の比較に混じる。
set -euo pipefail

BASE="${1:?usage: comment-ratio.sh <BASE-sha> [<ref>]}"
REF="${2:-}"

# Windows の Python は `python3` を持たないことがある（逆に Linux / macOS は `python`
# を持たないことがある）ので両方を探す。見つからないまま進むと空の集計が出る。
PY_BIN=$(command -v python3 || command -v python || true)
[ -n "$PY_BIN" ] || { echo "comment-ratio: python3 / python が PATH に無い" >&2; exit 2; }

"$PY_BIN" - "$BASE" "$REF" <<'PY'
import re, subprocess, sys, io, tokenize

# Windows の既定コンソール（cp932 等）では本文の記号を encode できずに落ちるため、
# 出力を UTF-8 に固定する。落ちた場合の終了コードが、測れなかったことを示す 2 と
# 混ざらないようにするのが目的。
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8")

base, ref = sys.argv[1], sys.argv[2]


def die(msg):
    """計測不成立で止まる。**終了コードは 0（測れた）以外に統一して 2**——
    `raise SystemExit("...")` は exit 1 になるので使わない。呼び出し側（P4）が
    「測れなかった」と「注釈が 0%だった」を終了コードで区別できることが要件。"""
    print(f"comment-ratio: {msg}", file=sys.stderr)
    sys.exit(2)


HUNK = re.compile(r"^@@ -\S+ \+(\d+)(?:,(\d+))? @@")
# Python は tokenize、それ以外は C 系コメントとして数える。`#` 系の言語（Ruby・
# Shell 等）を足すな——注釈を 1 行も拾えないまま「注釈 0%」を自信ありげに出す。
EXTS = (".py", ".ts", ".tsx", ".js", ".jsx", ".go", ".rs", ".java", ".kt",
        ".cs", ".cpp", ".cc", ".c", ".h", ".hpp", ".swift", ".scala", ".php")


def git(*args):
    """git の出力。**失敗を握り潰さない**——空を返すと、読めなかったファイルが
    「注釈ゼロ」として集計に混じり、しかも数字は自信ありげに出てしまう。"""
    # text=True は locale のエンコーディングで読むため、Windows（cp932）では日本語を
    # 含む diff を読んだ時点で UnicodeDecodeError になり、reader thread の中で落ちて
    # returncode の検査より前に p.stdout が None になる。リポジトリの中身は UTF-8 と
    # 決めて読む（不正なバイトはパス名を壊さない surrogateescape で通す）。
    try:
        p = subprocess.run(
            ["git", *args],
            capture_output=True,
            encoding="utf-8",
            errors="surrogateescape",
            # 認証待ちで固まる git 操作（credential helper のプロンプト等）で
            # 無制限に待たない。待ち続けると P4 が進まないまま止まる。
            timeout=120,
        )
    except subprocess.TimeoutExpired:
        die(f"git {' '.join(args)} が 120 秒で応答しない")
    if p.returncode != 0:
        die(f"git {' '.join(args)} が失敗: {p.stderr.strip()}")
    return p.stdout


def changed_files():
    # -z を使うのは、空白や非 ASCII を含むパスが git の既定の引用で壊れるため。
    out = git("diff", "--name-only", "-z", base, *([ref] if ref else []))
    return [p for p in out.split("\0") if p.endswith(EXTS)]


def untracked_target_files():
    """差分に載っていない未追跡の対象言語ファイル。

    検知しないと、**計測漏れのある縮退状態と、本当に対象ファイルが無い正常系が
    どちらも「追加行なし」という同じ出力になる**（fail-open）。ラウンド間で比べる
    数字なので、漏れた状態の 0 が「注釈を足した」の証拠に化ける。
    ref を指定した ref 間比較は作業ツリーを見ないので対象外。
    """
    if ref:
        return []
    out = git("ls-files", "--others", "--exclude-standard", "-z")
    return [p for p in out.split("\0") if p.endswith(EXTS)]


def added_line_numbers(path):
    """差分で追加された行の、変更後ファイルにおける行番号。"""
    out = git("diff", "-U0", base, *([ref] if ref else []), "--", path)
    nums = set()
    for line in out.splitlines():
        m = HUNK.match(line)
        if m:
            start, count = int(m.group(1)), int(m.group(2) or 1)
            nums.update(range(start, start + count))
    return nums


def post_image(path):
    """変更後のファイル全文。tokenize は構文的に完全なソースを要求するので、差分の
    断片でなくこちらを読む（断片を読ませると、多行文字列の閉じ引用符を docstring の
    開始と取り違えて以降を数え続ける）。"""
    if ref:
        return git("show", f"{ref}:{path}")
    with open(path, encoding="utf-8") as f:
        return f.read()


def python_annotation_lines(src, path):
    """コメント行と docstring 行の行番号。

    docstring の判定は「文の位置に単独で置かれた文字列」——直前の意味のあるトークンが
    NEWLINE / INDENT / DEDENT のもの。代入の右辺に来る多行文字列は数えない。
    NL（空行・コメント行の改行）で prev を上書きしないのは、それらが文の切れ目では
    ないため。
    """
    lines = set()
    prev = tokenize.NEWLINE
    try:
        for tok in tokenize.generate_tokens(io.StringIO(src).readline):
            if tok.type == tokenize.COMMENT:
                lines.add(tok.start[0])
            elif tok.type == tokenize.STRING and prev in (
                tokenize.NEWLINE,
                tokenize.INDENT,
                tokenize.DEDENT,
            ):
                lines.update(range(tok.start[0], tok.end[0] + 1))
            if tok.type not in (tokenize.NL, tokenize.COMMENT):
                prev = tok.type
    except (tokenize.TokenError, IndentationError, SyntaxError):
        # 構文が壊れたファイルが 1 つでもあれば計測全体を中断する——部分的な数字は
        # ラウンド間の比較に使えず、0 を返すより「測れなかった」と表に出す方がよい。
        die(f"{path} を解析できない（構文エラー）")
    return lines


def c_style_annotation_lines(src):
    """行全体がコメントである行だけを数える。

    完全な字句解析はしない。**文字列やテンプレートリテラルの中に `/*` が
    あると、そこから `*/` までの全行をコメントとして数える**（1 個で末尾まで汚染
    されうる）。行末コメントは数えない（過小側）。
    """
    lines, block = set(), False
    for i, line in enumerate(src.splitlines(), 1):
        s = line.strip()
        if block:
            lines.add(i)
            if "*/" in s:
                block = False
        elif s.startswith("//"):
            lines.add(i)
        elif s.startswith("/*"):
            lines.add(i)
            block = "*/" not in s
    return lines


missed = untracked_target_files()
if missed:
    die(
        "未追跡の対象言語ファイルが差分に載っていない（`git add -N` で載せてから測れ）: "
        + " ".join(missed)
    )

total = annotated = 0
for path in changed_files():
    added = added_line_numbers(path)
    if not added:
        continue
    total += len(added)
    src = post_image(path)
    marked = (
        python_annotation_lines(src, path)
        if path.endswith(".py")
        else c_style_annotation_lines(src)
    )
    annotated += len(added & marked)

if total == 0:
    print(f"対象言語（{' '.join(EXTS)}）のファイルに追加行なし")
else:
    print(f"追加行 {total} / 注釈 {annotated} ({annotated * 100 // total}%)")
PY
