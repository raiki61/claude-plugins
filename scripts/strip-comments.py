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
  - それ以外は字句解析をせず、行全体がコメントの行と、行の先頭から始まるブロックだけを
    落とす（行末コメントは残る＝過小側。1 行目の shebang も残す）。
    **拡張子ごとの記法は LANGS と BASENAMES が正本。ここに列挙を写すと腐る**——
    実際、以前ここに置いた一覧は表からドリフトしていた
  - 表に無い拡張子は触らず、名前を stderr に列挙する（黙って素通しにしない）
  - **剥がした結果が構文として壊れたら、そのファイルは剥がさず名前を出す**（`parses`）

comment-ratio.sh（数える側）が Python と C 系に絞っているのは、拾えない言語で「注釈 0%」を
自信ありげに出さないため。剥がす側は漏れてもコメントが読み手に見えるだけで、名前も出る
ので害が小さく、広く取る。

行は消さず空行にする——読み手の報告（「N 行目で止まった」）を元のファイルの行に
そのまま写せるようにするため。

使い方:
    python3 strip-comments.py <写しのルート> <ルートからの相対パス>...
    python3 strip-comments.py --export <写しのルート> <ルートからの相対パス>...
        （cwd のリポジトリから写しを作ってから剥がす。<写しのルート> は無いか空であること）

終了コード: 0 走った / 2 走れなかった（引数違い・写し先が不正・写しの中身が作業ツリーと違う）。
**触れなかったファイルは 0 のまま名前を stderr に出す**（対象外の拡張子・非 UTF-8・元から構文が
壊れている・剥がすと構文が壊れる の 4 つ。理由は違っても読み手への帰結は同じで、コメントが
付いたまま見える）。ここを経路ごとに 0 と 2 で分けていたときは、同じ「剥がせない」が片方は
即死・無報告、片方は継続・報告になっていた。
"""

import io
import subprocess
import tarfile
import sys
import tokenize
from pathlib import Path

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8")

# 言語ごとの記法: (行コメントの接頭辞の組, ブロックの (開始, 終了) の組)。
C_STYLE = (("//",), (("/*", "*/"),))
HASH = (("#",), ())
LANGS = {
    **{e: C_STYLE for e in (".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".go", ".rs",
                            ".java", ".kt", ".kts", ".cs", ".cpp", ".cc", ".c", ".h",
                            ".hpp", ".swift", ".scala", ".php", ".dart", ".m", ".mm",
                            ".groovy", ".gradle")},
    **{e: HASH for e in (".sh", ".bash", ".zsh", ".fish", ".rake",
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


def line_ending(line):
    """行末の改行（無ければ空文字）。空にする側と残す側の両方が要る。"""
    return line[len(line.rstrip("\r\n")):]


def has_code(text):
    """空白以外が残っているか——「コメントを消しても同じ行の実コードは消さない」の判定。

    この不変条件は行ベースの剥がし（ブロックが閉じたあと）と tokenize ベースの剥がし
    （docstring の前後）の両方に要る。**3 箇所に別々に書いていたら、3 回とも別のラウンドで
    「片腕だけ塞いだ」として戻ってきた**ので、判定そのものに名前を付けて 1 箇所にする。
    """
    return bool(text.strip())


def strip_python(src, path):
    """コメントは開始桁から行末まで、docstring はその範囲だけを空にする。元から構文が壊れていれば None。

    docstring を「行ごと」空にすると、docstring と同じ行に `;` で続くコードが
    写しから消える（strip_lines の 2 本の腕で塞いだのと同じ欠陥の 3 本目）。
    範囲だけを空にすれば、行数は変わらないまま前後のコードが残る。
    """
    lines = src.splitlines(keepends=True)
    prev = tokenize.NEWLINE
    try:
        for tok in tokenize.generate_tokens(io.StringIO(src).readline):
            if tok.type == tokenize.COMMENT:
                row, col = tok.start
                line = lines[row - 1]
                lines[row - 1] = line[:col].rstrip() + line_ending(line)
            elif tok.type == tokenize.STRING and prev in (
                tokenize.NEWLINE, tokenize.INDENT, tokenize.DEDENT,
            ):
                (srow, scol), (erow, ecol) = tok.start, tok.end
                for row in range(srow, erow + 1):
                    line = lines[row - 1]
                    head = line[:scol] if row == srow else ""
                    tail = line[ecol:].rstrip("\r\n") if row == erow else ""
                    # docstring が文の区切りで終わっていると、消したあとに区切りだけが
                    # 先頭に残って構文が壊れる。区切りごと落として後続のコードを生かす。
                    tail = tail if has_code(head) else tail.lstrip().lstrip(";").lstrip()
                    lines[row - 1] = ((head + tail).rstrip() or "") + line_ending(line)
            if tok.type not in (tokenize.NL, tokenize.COMMENT):
                prev = tok.type
    except (tokenize.TokenError, IndentationError, SyntaxError):
        # ここで exit すると、それ以前に書き換えた分の写しが残ったまま、触れなかった
        # ファイルの一覧（skipped / undecodable / broke）も出ずに落ちる。**同じ「剥がせない」が
        # 経路によって「即死・無報告」と「継続・報告」に分かれていた。**元から壊れている
        # ファイルは剥がしようが無いだけなので、他の 3 つと同じく名前を出して継続する。
        return None
    return "".join(lines)


def parses(text, rel):
    """剥がした結果が、その言語の構文として通るか。通らないなら剥がしてはいけない。

    行ベースの剥がしは字句解析をしないので、文字列やヒアドキュメントの中の
    シャープで始まる行をコメントと誤認する。実測: tests/run.sh で、行継続した
    二重引用符の中身の行が空にされ、引用符が閉じず写しが bash の構文エラーに
    なった。読み手はその壊れた写しを精読することになる。

    **零処方（shell を LANGS から外す）を採らなかった理由**: 同じ壊れ方は shell に限らない。
    Python でも docstring の後ろに続くコードの扱いで構文を壊しうる（実測で一度壊した）。
    言語を 1 つ外しても、外していない言語の同じ穴は残る。ここは言語をまたいで
    1 つの判断で塞ぐ側に倒し、そのぶん判定手段は増やさない——Python は標準の compile、
    shell は bash があれば `bash -n`、それ以外の言語は判定しない。

    返すのは 3 値だけ: True 通る / False 通らない / None 判定しない。**「確かめられなかった」を
    False に潰すな**——呼び出し側は `parses(src) is not False and parses(new) is False` で判定して
    いて、左が False になった時点で短絡し、退避ごと飛ばして書き出す。実測: bash を引けない環境
    （`PATH=/usr/bin`）で、構文の壊れた写しが「剥がした: 1 ファイル」・exit 0・stderr 空で
    書き出された。道具を引けないときは例外を末尾の境界へ抜けさせ、この道具の契約どおり
    exit 2（計測不成立を 0 で返さない）に倒す——同ファイルの `git()` が採っている形と同じ。
    """
    if rel.endswith(".py"):
        try:
            compile(text, rel, "exec")
            return True
        except SyntaxError:
            return False
    if rel.rsplit("/", 1)[-1].split(".")[-1] in ("sh", "bash", "zsh"):
        p = subprocess.run(["bash", "-n"], input=text.encode("utf-8"),
                           capture_output=True, timeout=GIT_TIMEOUT_SEC)
        return p.returncode == 0
    return None


def strip_lines(src, prefixes, blocks):
    """行全体のコメントと、行頭から始まるブロックを空行にする。1 行目の shebang は残す。"""
    out, closing = [], None
    for i, line in enumerate(src.splitlines(keepends=True)):
        s = line.strip()
        eol = line_ending(line)
        if closing is not None:
            at = s.find(closing)
            # 閉じたあとにコードが残る行を空にすると、1 行で閉じた場合と同じく
            # 写しからコードが消える。過小側に倒す判断は両方の腕に掛ける。
            if at >= 0 and has_code(s[at + len(closing):]):
                out.append(line)
            else:
                out.append(eol)
            if at >= 0:
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
            elif has_code(rest[at + len(e):]):
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
    try:
        p = subprocess.run(["git", *args], capture_output=True, timeout=GIT_TIMEOUT_SEC, **kw)
    except subprocess.TimeoutExpired:
        fail(f"git {' '.join(args)} が {GIT_TIMEOUT_SEC} 秒で応答しない")
    if p.returncode != 0:
        fail(f"git {' '.join(args)} が失敗: {p.stderr.decode('utf-8', 'replace').strip()}")
    return p.stdout


def require_outside_repo(root):
    """写し先がどの git 作業ツリーにも属さないことを確かめる。

    **両方の入口に掛ける。**片方だけだと同じ欠陥が残る腕から入れる:
    - `--export` 側だけに掛けると、`--export` を付けずに本物のリポジトリを写し先として
      渡された剥がしが、その場で本物のコメントを消す（元に戻す機能は無い）。
    - cwd のリポジトリとだけ比べると、**別の**リポジトリの中に写しを作られたときに
      素通りし、`git apply` がそのリポジトリを見つけて patch を無視する。

    後者は「当てなかった」を返り値でも stderr でも伝えない——実測（git 2.50.1）で
    returncode 0・stderr 0 バイト。だから git のメッセージを読む形の検査は成立しない。
    """
    probe = root if root.exists() else root.parent
    p = subprocess.run(["git", "-C", str(probe), "rev-parse", "--show-toplevel"],
                       capture_output=True, timeout=GIT_TIMEOUT_SEC)
    if p.returncode == 0:
        top = p.stdout.decode("utf-8", "replace").strip()
        fail(f"{root}: git の作業ツリー（{top}）の中。"
             "写しはどのリポジトリにも属さない場所に作れ——"
             "中に作ると未コミット分が黙って当たらず、本物を渡すと本物が書き換わる")


def export(root):
    """cwd のリポジトリの今の姿（HEAD＋未コミット）を root に展開する。"""

    if root.exists() and any(root.iterdir()):
        fail(f"{root}: 空でない（写しは空のディレクトリか無いパスに作れ。本物に当てるな）")
    require_outside_repo(root)
    root.mkdir(parents=True, exist_ok=True)
    with tarfile.open(fileobj=io.BytesIO(git("archive", "--format=tar", "HEAD"))) as tar:
        # filter は 3.12 で導入され 3.14 で既定が data になった。明示しないと版で
        # 挙動が変わり、絶対 symlink を含むリポジトリが版によって展開できない。
        if hasattr(tarfile, "data_filter"):
            tar.extractall(root, filter="data")
        else:
            # 例外の型で判定すると、展開中の別原因の TypeError でもここへ落ち、
            # 原因を取り違えたままフィルタ無しで展開し直すことになる。公式は
            # data_filter の有無で機能検出しろと書いており、落ちるときは黙るなとも書いている。
            print("strip-comments: この python は tar の展開フィルタを持たない"
                  "（3.12 未満）。写しの展開は無防備になる", file=sys.stderr)
            tar.extractall(root)
    patch = git("diff", "HEAD", "--binary")
    if patch.strip():
        p = subprocess.run(["git", "apply", "--whitespace=nowarn", "-"], input=patch,
                           cwd=root, capture_output=True, timeout=GIT_TIMEOUT_SEC)
        err = p.stderr.decode("utf-8", "replace").strip()
        if p.returncode != 0:
            fail(f"未コミット分を写しに当てられない: {err}")


def verify_mirror(root, rels):
    """写しの中身が今の作業ツリーと一致するか、**結果を見て**確かめる。

    git の出力の文言を読む形（`"Skipped patch" in stderr`）は成立しない——当てなかった
    ときに何も出力しない版が在り（実測: git 2.50.1 で stderr 0 バイト）、出力しても
    gettext の翻訳対象なので非英語ロケールで一致しない。事後条件なら版にもロケールにも
    依存せず、写し先がどこであっても同じ 1 つの検査で塞がる。
    """
    for rel in rels:
        src, dst = Path(rel), root / rel
        if not src.is_file() or not dst.is_file():
            continue
        if src.read_bytes() != dst.read_bytes():
            fail(f"{rel}: 写しの中身が作業ツリーと違う"
                 "（未コミット分が当たっていない。写しの場所を確かめろ）")


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
    else:
        # 剥がしはその場で上書きし、元に戻す機能が無い。写し先が本物のリポジトリだと
        # 本物のコメントが消えるので、--export を付けない入口にも同じ判定を掛ける。
        require_outside_repo(root)
    if not root.is_dir():
        fail(f"{root}: ディレクトリでない")
    if do_export:
        verify_mirror(root, args[1:])
    skipped, undecodable, unparsable, broke, unverified, done = [], [], [], [], [], 0
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
        is_py = rel.endswith(".py")
        if not is_py and not syn:
            skipped.append(rel)
            continue
        try:
            src = p.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            # errors="replace" で読んで書き戻すと、非 UTF-8 の中身が U+FFFD に
            # 化けたまま保存される。読み手はそれをコード側の欠陥として報告する。
            undecodable.append(rel)
            continue
        new = strip_python(src, rel) if is_py else strip_lines(src, *syn)
        if new is None:
            unparsable.append(rel)
            continue
        # **剥がした側から先に判定する。** 逆順だと、剥がしても壊れない大多数のファイルで
        # 元の側の検算まで走る（shell は 1 回が bash のプロセス起動で、実測 50 件で
        # 100 回 0.700 秒 → 50 回 0.389 秒）。and は可換なので結果は同じ。
        verdict = parses(new, rel)
        if verdict is False and parses(src, rel) is not False:
            # 元は通るのに剥がすと通らない＝剥がしが構文を壊した。写しを渡す先は
            # 「読んで説明する」役なので、壊れた写しは偽の指摘に化ける。
            broke.append(rel)
            continue
        if verdict is None:
            # 剥がしたが検算していない。行ベースの剥がしは引用符を見ないので、複数行の
            # 文字列（テンプレートリテラル・ヒアドキュメント・ブロックスカラー）の中の
            # 行をコメントと誤認して中身を消しうる。**検算できた剥がしと同じ顔で渡すな**——
            # 読み手が「ここで意味が取れない」と言ったとき、コードの欠陥なのか写しの破損なのかを
            # 分ける材料になる（この道具が掲げる「黙って素通しにしない」を、唯一破っていた経路）。
            unverified.append(rel)
        p.write_text(new, encoding="utf-8")
        done += 1
    print(f"剥がした: {done} ファイル")
    # 触れなかった理由は 4 つあるが、読み手への帰結は 1 つ——コメントが付いたまま見える。
    # **その名前を R1 の読み手に渡す一覧から外し、その分は未実測と書くこと**（渡すと、
    # そこに書いてある目的で隔離が破れる。実測でそうなった）。
    for why, files in (("対象外の拡張子", skipped),
                       ("UTF-8 として読めない", undecodable),
                       ("元から構文が壊れている", unparsable),
                       ("剥がすと構文が壊れた", broke)):
        if files:
            print(f"触っていない（{why}。読み手にはコメント付きのまま見えるので、"
                  f"R1 の一覧から外して未実測と書け）: " + " ".join(files), file=sys.stderr)
    if unverified:
        print("剥がしたが検算していない（この言語の構文を確かめる手段が無い。読み手が"
              "「意味が取れない」と言ったら、コードでなくこの写しを疑え）: "
              + " ".join(unverified), file=sys.stderr)


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception as e:
        fail(f"想定外の例外（{type(e).__name__}）: {e}")
