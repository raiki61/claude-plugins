#!/usr/bin/env python3
"""読み手の実測用に、指定ファイルからコメントと docstring を落とす（行番号は保つ）。

review-loop の R1 前段が使う。目的を知らない読み手（`reader`）に、コメントを剥がした
作業ツリーの写しを精読させ、それでも正しく説明できた箇所のコメントは情報を運んで
いない（削る候補）、説明がずれた箇所は構造か名前で直す——という判定の材料を作る。

**本物の作業ツリーに当てるな。** 写しの中のファイルを書き換える道具で、元に戻す機能は無い。

写しは `--export` で作れる: cwd のリポジトリの HEAD を `git archive` で展開し、未コミット分
（`git diff HEAD --binary`。`git add -N` した新規ファイルも含む）を当て、指定パスを剥がす。
git worktree は使わない——登録と remove の片付けが要り、途中で落ちると残る。写しはただの
ディレクトリなので、片付けは `rm -rf`（scratchpad に作れば放置してもよい）。

落とし方:
  - Python: tokenize でコメント（行末も）と、文の位置に置かれた文字列（docstring）
  - それ以外は字句解析をせず、**行全体がコメントの行と、行頭から始まるブロック**だけを
    落とす（行末コメントは残る＝過小側。文字列中にブロック開始があると末尾まで汚染しうる）。
    言語ごとの記法は LANGS が正本: C 系 `//` `/* */`、`#` 系（Shell・Ruby・Perl・YAML・
    TOML・R・Elixir・Dockerfile・Makefile）、`--` 系（SQL・Lua・Haskell）、`<!-- -->`
    （HTML・XML・Vue・Svelte）、CSS 系。1 行目の shebang は残す
  - 表に無い拡張子は触らず、名前を stderr に列挙する（黙って素通しにしない）

comment-ratio.sh（数える側）が Python と C 系に絞っているのは、拾えない言語で「注釈 0%」を
自信ありげに出さないため。剥がす側は漏れてもコメントが読み手に見えるだけで、名前も出る
ので害が小さく、広く取る。

行は消さず空行にする——読み手の報告（「N 行目で止まった」）を元のファイルの行に
そのまま写せるようにするため。

使い方:
    python3 strip-comments.py <写しのルート> <ルートからの相対パス>...
    python3 strip-comments.py --export <写しのルート> <ルートからの相対パス>...
        （cwd のリポジトリから写しを作ってから剥がす。<写しのルート> は無いか空であること）

終了コード: 0 剥がせた / 2 剥がせなかった（構文エラー・読めない・引数違い）。
`review-record.py` と同じく、計測不成立を 0 で返さない。
"""

import io
import sys
import tokenize
from pathlib import Path

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8")

# 言語ごとの記法: (行コメントの接頭辞の組, ブロックの (開始, 終了) の組)。
C_STYLE = (("//",), (("/*", "*/"),))
HASH = (("#",), ())
DASH = (("--",), ())
LANGS = {
    **{e: C_STYLE for e in (".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".go", ".rs",
                            ".java", ".kt", ".kts", ".cs", ".cpp", ".cc", ".c", ".h",
                            ".hpp", ".swift", ".scala", ".php", ".dart", ".m", ".mm",
                            ".groovy", ".gradle")},
    **{e: HASH for e in (".sh", ".bash", ".zsh", ".fish", ".rb", ".rake", ".pl", ".pm",
                         ".yml", ".yaml", ".toml", ".r", ".R", ".ex", ".exs", ".tf",
                         ".ini", ".cfg", ".conf", ".ps1")},
    ".rb": (("#",), (("=begin", "=end"),)),
    ".pl": (("#",), (("=pod", "=cut"), ("=head1", "=cut"))),
    ".pm": (("#",), (("=pod", "=cut"), ("=head1", "=cut"))),
    ".sql": (("--",), (("/*", "*/"),)),
    ".lua": (("--",), (("--[[", "]]"),)),
    ".hs": (("--",), (("{-", "-}"),)),
    ".elm": (("--",), (("{-", "-}"),)),
    **{e: ((), (("<!--", "-->"),)) for e in (".html", ".htm", ".xml", ".vue", ".svelte", ".xhtml")},
    ".css": ((), (("/*", "*/"),)),
    ".scss": C_STYLE,
    ".less": C_STYLE,
}
# 拡張子の無い定番ファイル。
BASENAMES = {"Dockerfile": HASH, "Makefile": HASH, "Rakefile": HASH, "Gemfile": HASH}


def fail(msg):
    print(f"strip-comments: {msg}", file=sys.stderr)
    sys.exit(2)


def strip_python(src, path):
    """コメントは開始桁から行末まで、docstring は行ごと空にする。"""
    lines = src.splitlines(keepends=True)
    prev = tokenize.NEWLINE
    try:
        for tok in tokenize.generate_tokens(io.StringIO(src).readline):
            if tok.type == tokenize.COMMENT:
                row, col = tok.start
                line = lines[row - 1]
                eol = line[len(line.rstrip("\r\n")):]
                lines[row - 1] = line[:col].rstrip() + eol
            elif tok.type == tokenize.STRING and prev in (
                tokenize.NEWLINE, tokenize.INDENT, tokenize.DEDENT,
            ):
                for row in range(tok.start[0], tok.end[0] + 1):
                    line = lines[row - 1]
                    lines[row - 1] = line[len(line.rstrip("\r\n")):]
            if tok.type not in (tokenize.NL, tokenize.COMMENT):
                prev = tok.type
    except (tokenize.TokenError, IndentationError, SyntaxError):
        fail(f"{path} を解析できない（構文エラー）")
    return "".join(lines)


def strip_lines(src, prefixes, blocks):
    """行全体のコメントと、行頭から始まるブロックを空行にする。1 行目の shebang は残す。"""
    out, closing = [], None
    for i, line in enumerate(src.splitlines(keepends=True)):
        s = line.strip()
        eol = line[len(line.rstrip("\r\n")):]
        if closing is not None:
            out.append(eol)
            if closing in s:
                closing = None
            continue
        if i == 0 and s.startswith("#!"):
            out.append(line)
            continue
        start = next(((b, e) for b, e in blocks if s.startswith(b)), None)
        if start:
            b, e = start
            rest = s[len(b):]
            at = rest.find(e)
            if at < 0:
                out.append(eol)
                closing = e
            elif rest[at + len(e):].strip():
                # 同じ行でブロックが閉じ、そのあとにコードが残る。行ごと空にすると
                # 読み手に渡す写しからコードが消えるので触らない（docstring が宣言
                # している「過小側に倒す」に揃える。剥がし漏れは読み手に見えるが、
                # 消えたコードは見えない）。
                out.append(line)
            else:
                out.append(eol)
        elif any(s.startswith(p) for p in prefixes):
            out.append(eol)
        else:
            out.append(line)
    return "".join(out)


def syntax_for(rel):
    name = rel.rsplit("/", 1)[-1]
    if name in BASENAMES:
        return BASENAMES[name]
    for ext, syn in LANGS.items():
        if rel.endswith(ext):
            return syn
    return None


GIT_TIMEOUT_SEC = 120


def git(*args, **kw):
    import subprocess

    try:
        p = subprocess.run(["git", *args], capture_output=True, timeout=GIT_TIMEOUT_SEC, **kw)
    except subprocess.TimeoutExpired:
        fail(f"git {' '.join(args)} が {GIT_TIMEOUT_SEC} 秒で応答しない")
    if p.returncode != 0:
        fail(f"git {' '.join(args)} が失敗: {p.stderr.decode('utf-8', 'replace').strip()}")
    return p.stdout


def export(root):
    """cwd のリポジトリの今の姿（HEAD＋未コミット）を root に展開する。"""
    import subprocess
    import tarfile

    if root.exists() and any(root.iterdir()):
        fail(f"{root}: 空でない（写しは空のディレクトリか無いパスに作れ。本物に当てるな）")
    # 写しがリポジトリの作業ツリーの中だと、下の git apply が patch の経路を頂点から
    # 解決して「カレントの外」として Skipped patch を返し、**終了コード 0 のまま**
    # HEAD の姿だけの写しができる。読み手はこのラウンドで直した内容が入っていない
    # コードを精読することになるので、入口で塞ぐ。
    top = Path(git("rev-parse", "--show-toplevel").decode("utf-8", "replace").strip()).resolve()
    dest = root.resolve()
    if dest == top or top in dest.parents:
        fail(f"{root}: リポジトリの中（写しは作業ツリーの外に作れ。中に作ると未コミット分が当たらない）")
    root.mkdir(parents=True, exist_ok=True)
    import io

    with tarfile.open(fileobj=io.BytesIO(git("archive", "--format=tar", "HEAD"))) as tar:
        # filter は 3.12 で導入され 3.14 で既定が data になった。明示しないと版で
        # 挙動が変わり、絶対 symlink を含むリポジトリが版によって展開できない。
        try:
            tar.extractall(root, filter="data")
        except TypeError:
            tar.extractall(root)
    patch = git("diff", "HEAD", "--binary")
    if patch.strip():
        p = subprocess.run(["git", "apply", "--whitespace=nowarn", "-"], input=patch,
                           cwd=root, capture_output=True, timeout=GIT_TIMEOUT_SEC)
        err = p.stderr.decode("utf-8", "replace").strip()
        if p.returncode != 0:
            fail(f"未コミット分を写しに当てられない: {err}")
        if "Skipped patch" in err:
            # 上の封じ込めを抜けた場合の fail-closed。0 が返っても当たっていない。
            fail(f"未コミット分が写しに当たらなかった: {err}")


def main():
    args = sys.argv[1:]
    do_export = bool(args) and args[0] == "--export"
    if do_export:
        args = args[1:]
    if len(args) < 2:
        print(__doc__, file=sys.stderr)
        fail(f"引数は [--export] <写しのルート> <相対パス>... （受け取った数: {len(sys.argv) - 1}）")
    root = Path(args[0])
    if do_export:
        export(root)
    if not root.is_dir():
        fail(f"{root}: ディレクトリでない")
    skipped, undecodable, done = [], [], 0
    rr = root.resolve()
    for rel in args[1:]:
        p = root / rel
        # 相対パスの位置に絶対パスや .. を渡されると pathlib が root を捨て、
        # 本物のファイルをその場で書き換えてしまう（元に戻す機能は無い）。
        pr = p.resolve()
        if pr != rr and rr not in pr.parents:
            fail(f"{rel}: 写しの外を指している（相対パスで渡せ。本物に当てるな）")
        if not p.is_file():
            fail(f"{p}: 無い（写しに載っていない。新規なら git add -N してから写せ。"
                 f"削除されたファイルは渡すな——git diff --name-only <BASE> --diff-filter=d で外せ）")
        syn = syntax_for(rel)
        if rel.endswith(".py"):
            strip = lambda s: strip_python(s, rel)
        elif syn:
            strip = lambda s, syn=syn: strip_lines(s, *syn)
        else:
            skipped.append(rel)
            continue
        try:
            src = p.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            # errors="replace" で読んで書き戻すと、非 UTF-8 の中身が U+FFFD に
            # 化けたまま保存される。読み手はそれをコード側の欠陥として報告する。
            undecodable.append(rel)
            continue
        p.write_text(strip(src), encoding="utf-8")
        done += 1
    print(f"剥がした: {done} ファイル")
    if skipped:
        print("触っていない（対象外の拡張子。読み手にはコメント付きのまま見える）: " + " ".join(skipped), file=sys.stderr)
    if undecodable:
        print("触っていない（UTF-8 として読めない。読み手にはコメント付きのまま見える）: " + " ".join(undecodable), file=sys.stderr)


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception as e:
        fail(f"想定外の例外（{type(e).__name__}）: {e}")
