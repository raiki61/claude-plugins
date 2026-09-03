#!/usr/bin/env python3
"""外部投稿ゲート (PreToolUse/Bash)。

gh で GitHub へ本文を投稿するコマンド(issue/PR のコメント・本文、release notes、gist 等)を
検出すると、フック自身が読み役を走らせる:
コマンドから本文を取り出し、文脈ゼロの別プロセス(既定は claude -p の headless 実行)に
初見で読ませ、理解を妨げた「詰まり」が出たら deny の理由にその指摘を載せて止める。
「疑問」(理解はできたが答えが本文に無いもの)は止めずに申し送る——疑問ゼロの文章は
ほぼ書けず、疑問で止めるとゲートが厳しすぎて逃げ道が常態化するため。

検査の実行を書き手(モデル)の申告に頼らないので、「検査した印だけ押して通す」穴が
構造的に無い(自動の振る舞いはフックが実行する、の原則)。再実行のたびに新しい
読み手が直後の本文を読むため、「毎回新規の読み役」も機械が保証する。

逃げ道は COLDREAD_SKIP=1 の 1 本(記録が残る)。読み役が起動できないときも
deny + 逃げ道の案内にする(投稿不能にはならない)。連続 3 回 deny されたら、
残る指摘の採否を判断して skip してよい旨を案内する(初見指摘は読み手ごとに揺れ、
完全収束しないため。firstread-loop と同じ知見)。

「補完」(読み手が推測で埋めた箇所)も止めずに申し送る。詰まりを数える設計では、
読み手が自信を持って誤読した本文は詰まり 0 件で通ってしまうため、埋めた中身の側を
書かせて書き手に返す。

記録は $CLAUDE_CONFIG_DIR/coldread-gate/ に 3 本:
  denies.log  allow / deny / skip の別(deny はタブ区切りで種別も。maxlen・parse-fail・
              blocked・reader-down・finding)
  skip.log    逃げ道を使った投稿のコマンド先頭 200 字
  misses.log  本文旗の綴りが在るのに候補も blocked も空だった素通し=網から落ちた疑い。
              「投稿でなかった」と区別が付かないと押し出しの量を測れないので分けて残す

環境変数:
  COLDREAD_SKIP=1            この 1 回だけゲートを通す(記録が残る)
  COLDREAD_READER_CMD        読み役コマンドの差し替え(POSIX sh 文字列として sh -c 実行。stdin に依頼文+本文)。テスト用
  COLDREAD_MODEL             既定 sonnet
  COLDREAD_EFFORT            既定 medium
  COLDREAD_MIN_LEN           これ未満のコマンドは素通し。既定 400
  COLDREAD_MAX_LEN           これを超えるコマンドは解析せず deny。既定 100000
  COLDREAD_IN_READER=1       読み役の中であることの印(自動で付く)。入れ子の再発火を防ぐ
  COLDREAD_KEYCHAIN_SERVICE  macOS Keychain の OAuth トークンのサービス名(未指定なら
                             CLAUDE_CONFIG_DIR の末尾から推定: ~/.claude-p1 → claude-code-oauth-p1)
"""
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import time

# Windows では stdio が locale 既定の code page になり(GitHub Actions windows-latest で
# cp1252 を実測。日本語 Windows なら cp932)、日本語の deny メッセージが UnicodeEncodeError で
# 落ちてフック自体が素通りになるため、UTF-8 に固定する(hook の入出力は UTF-8 の JSON)。
for _stream in (sys.stdin, sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

CONFIG_DIR = os.environ.get("CLAUDE_CONFIG_DIR") or os.path.expanduser("~/.claude")
STATE_DIR = os.path.join(CONFIG_DIR, "coldread-gate")
SKIP_LOG = os.path.join(STATE_DIR, "skip.log")
DENY_LOG = os.path.join(STATE_DIR, "denies.log")
MISS_LOG = os.path.join(STATE_DIR, "misses.log")
MIN_LEN = int(os.environ.get("COLDREAD_MIN_LEN", "400"))
# 上限。これを超える文字列は正規表現の後方追跡(HEREDOC_RE)が重くなりうるので解析せず deny
MAX_LEN = int(os.environ.get("COLDREAD_MAX_LEN", "100000"))
READER_TIMEOUT = 210
DENY_STREAK_WINDOW = 30 * 60

# ---- 投稿の判定 ------------------------------------------------------------
# 「gh らしさ」と「旗らしさ」を文字列全体へ独立に照合する方式は、複合コマンドで別コマンドの
# 旗を gh の物と誤認し(git checkout -b)、引用・短縮形で取りこぼした(0.2.x で実測)。
# 代わりに、ヒアドキュメントを盾置換 → shlex でトークン化 → 単純コマンドに区切り、gh の
# 引数列の中だけで「本文を運ぶ旗」を見る。単純コマンド分割と旗表は自作なので網羅性はテストで
# 守る。なぜこの方式か・いつ乗り換えるかは docs/coldread-gate-next.md(正本)。
# 対象外と受容した形は gates/README.md「網の射程」。
# デリミタは引用の有無(' か " か無し)と . - を許し、<<- の字下げ終端も拾う。
# 行末は \r?\n。コマンド文字列が CRLF で届くと \n 固定では開始行も終端行もマッチせず、
# 正しく書いたヒアドキュメントが「stdin 渡し」という嘘の理由で止まる(実測)。
HEREDOC_RE = re.compile(
    r"""<<-?\s*(['"]?)([A-Za-z_][A-Za-z0-9_.-]*)\1\r?\n(.*?)\r?\n[ \t]*\2(?:\r?\n|\r?$)""", re.S
)

# 本文を運ぶ旗の表(非 api 経路はこれを引く。api・gist 経路は下でハードコード)。
# text=次の値が本文 / file=ファイル指定(- は stdin)。
#
# 長い旗は綴りだけで判定してよい——gh 2.96.0 の全サブコマンドを走査した結果、この 5 つが
# 本文以外を指すのは secret/variable set の --body(値は秘密そのもの)だけだった。
LONG_TEXT_FLAGS = {
    "--body": "text", "--notes": "text", "--comment": "text", "--readme": "text",
    "--body-file": "file", "--notes-file": "file",
}
NON_POSTING = {("secret", "set"), ("variable", "set")}
# 長い旗でも本文でない 1 例: gh pr review の --comment はレビュー種別を選ぶ真偽旗で値を取らない
LONG_FLAG_NOT_BODY = {("--comment", ("pr", "review"))}
# 短縮形は同じ綴りが別の意味に割り当てられていて、綴りだけでは判定できない(同じ走査で確認):
# pr checkout -b=--branch / repo sync・view -b=--branch / issue develop -b=--base -c=--checkout
# -n=--name / pr・issue・discussion view -c=--comments / pr status -c=--conflict-status /
# discussion create・edit -c=--category / run download -n=--name / workflow run -F=--field /
# pr review -c=--comment(レビュー種別を選ぶ真偽旗で値を取らない)。
# そこで短縮形は「その綴りが本文を意味するサブコマンド」の中でだけ本文と見る。長い旗の側は
# 一般のままなので、gh が投稿サブコマンドを増やしても --body 等で書かれていれば網に入る。
SHORT_TEXT_FLAGS = {
    "-b": ("text", {("issue", "comment"), ("issue", "create"), ("issue", "edit"),
                    ("pr", "comment"), ("pr", "create"), ("pr", "edit"),
                    ("pr", "merge"), ("pr", "revert"), ("pr", "review"),
                    ("discussion", "comment"), ("discussion", "create"), ("discussion", "edit")}),
    "-c": ("text", {("issue", "close"), ("issue", "reopen"),
                    ("pr", "close"), ("pr", "reopen")}),
    "-n": ("text", {("release", "create"), ("release", "edit")}),
    "-F": ("file", {("issue", "comment"), ("issue", "create"), ("issue", "edit"),
                    ("pr", "comment"), ("pr", "create"), ("pr", "edit"),
                    ("pr", "merge"), ("pr", "revert"), ("pr", "review"),
                    ("discussion", "comment"), ("discussion", "create"), ("discussion", "edit"),
                    ("release", "create"), ("release", "edit")}),
}
# 値を取る global 旗(サブコマンド語の特定でだけ読み飛ばす)。-H/-X は api の前置で挟まりうる。
GLOBAL_VALUE_FLAGS = {"-R", "--repo", "-H", "--header", "-X", "--method"}
WRAPPERS = {"env", "command", "exec", "nohup", "time"}
# シェルの予約語。単純コマンドの先頭語になりうるが、コマンド名ではないので読み飛ばす。
# 飛ばさないと `{ gh …; }`・`if …; then gh …`・`while …; do gh …`・`! gh …` の gh が
# 見えず、投稿が無検査・無記録で通る(両ゲートとも。実測)。同じ意味の `( gh … )` は
# `(` が OP_CHARS にあるので元から通っていた——書き方だけで片方が抜ける状態だった。
# 載せるのは「直後にコマンドが来る」語だけ。done・fi・in は後ろにコマンドを取らないので
# 入れない(入れても発火させられず、表の全メンバーを検査する回帰が張れない)。
RESERVED = {"{", "!", "then", "else", "elif", "do"}
OP_CHARS = set("();<>|&\n")
# リダイレクト演算子(演算子と行き先を読み飛ばす)。&> >& <& は & を含むが区切りではない。
REDIRECT_OPS = {"<", ">", ">>", "<<", "<<<", "<&", ">&", "&>", "&>>", ">|"}
VAR_RE = re.compile(r"\$\{?[A-Za-z_][A-Za-z0-9_]*\}?\Z")
# 環境変数の前置(NAME=値)。単純コマンドの先頭で読み飛ばす範囲を決める
ENV_PREFIX_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*=")
# 前段の粗選別。部分文字列だと highlight・through 等の語で解析に入ってしまう
GH_WORD_RE = re.compile(r"\bgh\b")
# 網から落ちたことの検出だけに使う綴り(判定には使わない)。本文旗が生の文字列にあるのに
# 候補も blocked も空なら、投稿でないのではなく解析が取りこぼした疑いがある。
# 権威表から導出する——手で 2 本目の綴り表を持つと、旗を足したとき計器だけが黙り、
# 最も新しい=最も取りこぼしやすい旗のところで数えられなくなる(表と検査の突合は
# tests/coldread-table-case.py)。--body-file は --body\b が既に当てるので重複は無害。
API_BODY_FLAGS = {"--input"}  # classify() の api 経路が本文と見る旗
BODY_FLAG_RE = re.compile(
    "|".join(sorted(re.escape(f) + r"\b" for f in set(LONG_TEXT_FLAGS) | API_BODY_FLAGS))
    + r"|-[fF]\s*body="
)
# 短縮形(-b/-c/-n/-F)は入れない。git checkout -b 等と綴りが衝突して誤検知が増え、計器が濁るため。
# 生の文字列を見るので、行継続で割れた `--bo\<改行>dy` も数えられない。どちらもこの計器が
# 下限しか出さないことの内訳で、押し出しの量は「これ以上」としてしか読めない。


HEREDOC_MARK = "__HEREDOC%d__"


def shield_heredocs(command):
    """ヒアドキュメント本文を取り出し、解析用の文字列では番号付きの印に置き換える。

    番号を振るのは、どの単純コマンドに付いたヒアドキュメントかを後で見分けるため。
    番号が無いと、同じ行の別コマンド(cat > f <<EOF)の中身まで gh の本文候補に混ざる。
    """
    bodies = []

    def repl(m):
        bodies.append(m.group(3))
        return " " + (HEREDOC_MARK % (len(bodies) - 1)) + " \n"

    return HEREDOC_RE.sub(repl, command), bodies


def own_heredocs(args, heredoc_bodies):
    """この単純コマンドに付いたヒアドキュメント本文だけを返す。"""
    return [heredoc_bodies[i] for i in range(len(heredoc_bodies))
            if (HEREDOC_MARK % i) in args]


def has_live_substitution(text):
    """引用の外(または二重引用の中)に $( や ` があるか。単一引用の中は展開されない。

    引用の種別は shlex が落としてしまうので、生の文字列の側で見る。これを見ないと、
    本文に ``` や `--body` を含むだけの普通の文章まで「置換渡し」と誤判定する。
    """
    i, quote = 0, None
    while i < len(text):
        c = text[i]
        if quote == "'":
            if c == "'":
                quote = None
        elif c == "\\" and quote != "'":
            i += 1
        elif quote == '"':
            if c == '"':
                quote = None
            elif c == "`" or text.startswith("$(", i):
                return True
        elif c in "'\"":
            quote = c
        elif c == "`" or text.startswith("$(", i):
            return True
        i += 1
    return False


# 正規化で出力が実際に変わるのは注釈と行継続の 2 事象だけ。事象の起きうる文字へ正規表現で
# 跳び、その間はスライスで一括複製する。1 文字ずつ積むと 100KB の本文で 5ms/回掛かる
_EVENT_RE = re.compile(r"""[#\\'"]""")


def normalize_shell(text):
    r"""字句解析の前に、bash が入力段で落とす 2 つ(行継続・注釈)を 1 度の走査で落とす。

    bash は行継続の除去と注釈の認識を同じ 1 パスでやる。こちらも 1 パスにしないと、
    どちらを先に置いても bash が実行する gh を見失う形が残る(両方とも bash で実測):
      注釈が先   `echo x\<改行>#y; gh …` の gh が消える。bash は行を連結するので #y は
                 語中の # であって注釈ではない
      行継続が先 `echo a # メモ \<改行>gh …` の gh が消える。bash は注釈を行末で切るので
                 その \ は注釈の一部であって行継続ではない
    どちらも「gh は実行されるのにゲートには見えない」= 無検査・無記録の素通しになる。
    1 パスなら両方が自然に出る——注釈の判定に使う直前の 1 文字を、入力側ではなく
    出力側(prev)で見るため。行継続を落としても prev を据え置くので前後の語が連結し、
    注釈を落とす枝は行末までしか進まないので次の行は残る。

    落とすもの:
      行継続 …… 引用の外と二重引用の中の `\`+改行。空白に置換せず削除する
                 (POSIX の行継続は前後の語を連結する。`--bo\<改行>dy` は `--body`)。
                 単一引用の中は行継続にならないので残す
      注釈 …… 引用の外の、語頭の # から行末まで。改行は区切りとして残す

    落とさないと何が起きるか:
      行継続 …… tokenize は改行を区切りの演算子として残すので、1 つの gh 呼び出しが複数の
        単純コマンドに割れる。旗だけが載った断片は gh 呼び出しと認識されず(gh_args が None)、
        本文を運ぶ旗が引数列から消えて、候補も blocked も無い状態=投稿でないとして素通しになる。
        2026-09-03 の issue 3 本(skip.log 53-55 行)は逃げ道 COLDREAD_SKIP=1 で通ったので記録は
        残るが、同じ 3 本から逃げ道を外して掛け直すと、この経路で記録の無い素通しになることを
        実測した——同じコマンドに独立した穴が 2 つ在り、こちらは黙って外れる方である。
        同じ解析層を import している destgate の宛先検査も同時に外れていた。
      注釈 …… shlex の既定の注釈処理は readline() で改行ごと捨てるので、改行を区切りにしている
        tokenize では 2 つの単純コマンドが 1 本に融合し、先頭語が cd や echo になって gh が
        見えなくなる。かといって注釈をただ切ると、注釈の語が引数として残り、gist create のように
        位置引数を本文と見る経路で嘘の deny が出る。bash と同じ「語頭の # から行末まで」だけを
        落とすのが、どちらにも倒れない唯一の形。
    """
    out, i, n, quote, copied, gap = [], 0, len(text), None, 0, ""
    while True:
        m = _EVENT_RE.search(text, i)
        if m is None:
            break
        i = m.start()
        c = text[i]
        if quote == "'":
            if c == "'":
                quote = None
            i += 1
        elif c == "\\":
            if text.startswith(("\\\r\n", "\\\n"), i):
                # 連結するので gap(直前に出力した 1 文字)は据え置く。ここを改行や空白に
                # すると `echo x\<改行>#y` の # が語頭に見え、注釈として次の gh まで消える
                gap = text[i - 1] if i > copied else gap
                out.append(text[copied:i])
                i += 3 if text[i + 1] == "\r" else 2
                copied = i
            else:
                i += 2  # 退避された 1 文字は事象として見ない(`\#` は注釈の開始ではない)
        elif c == '"':
            quote = None if quote == '"' else '"'
            i += 1
        elif c == "'" and quote is None:
            quote = "'"
            i += 1
        elif c == "#" and quote is None and _head(text, i, copied, gap):
            gap = text[i - 1] if i > copied else gap
            out.append(text[copied:i])
            nl = text.find("\n", i)
            i = n if nl < 0 else nl  # 改行は残す(単純コマンドの区切り)
            copied = i
        else:  # 二重引用の中の '、引用の中の #、語中の # はどれも構文ではない
            i += 1
    if not out:
        return text  # 落とす物が 1 件も無ければ複製しない
    out.append(text[copied:])
    return "".join(out)


def _head(text, i, copied, gap):
    r"""text[i] が語頭か——注釈の始まりかどうかの判定。

    見るのは「直前に出力した 1 文字」で、入力側の text[i-1] ではない。複製待ちの区間が
    残っていればその末尾が直前の出力、区間が空なら直前の削除の手前の 1 文字(gap)。
    この違いが出るのが `echo x\<改行>#y` で、行継続を落とした後の直前の出力は x なので
    # は語中=注釈ではない。入力側で見ると改行が直前になり、注釈として後ろの gh まで消える。
    """
    prev = text[i - 1] if i > copied else gap
    return not prev or prev in " \t\n;|&()"


def prepare(command):
    r"""生のコマンド → (解析用に正規化した文字列, ヒアドキュメント本文)。解析する側は必ずここを通る。

    盾置換が先で正規化が後。順序は入れ替えられない——ヒアドキュメント本文の中の # や
    `\`+改行 は構文ではなく投稿する散文の中身なので、先に正規化すると本文が壊れる。
    字句解析(tokenize)と生の文字列を見る検査(has_live_substitution)が同じ 1 本の文字列を
    見ることを、この入口で構成として保証する——別々に正規化させると、片方だけ更新されて
    食い違う(destgate が現にそうなっていた)。
    """
    shielded, bodies = shield_heredocs(command)
    return normalize_shell(shielded), bodies


def tokenize(text):
    """POSIX の引用規則でトークン化する。引用が閉じない等で解析できなければ None。

    渡すのは prepare() を通した文字列。ここで正規化しないのは、生の文字列を見る検査
    (has_live_substitution)と同じ 1 本を共有させるため——ここに隠すと呼び出し側ごとに
    正規化を掛け直すことになり、100KB の本文で 1 回 6ms を余分に払う。
    """
    lex = shlex.shlex(text, posix=True, punctuation_chars="();<>|&\n")
    lex.whitespace = " \t\r"  # 改行は区切りの演算子として残す
    # shlex 自身の注釈処理は使わない(上で bash の規則どおりに落とした)。既定のままだと
    # 語の途中の # でも行末まで読み捨てるので、`--title fix#123 \` の次行の本文旗が消える。
    lex.commenters = ""
    lex.whitespace_split = True
    try:
        return list(lex)
    except ValueError:
        return None


def simple_commands(tokens):
    """演算子で区切った単純コマンドのトークン列を返す。リダイレクトは演算子と行き先ごと除く。"""
    cmds, cur, i = [], [], 0
    while i < len(tokens):
        tok = tokens[i]
        if tok and all(c in OP_CHARS for c in tok):
            if tok in REDIRECT_OPS:
                # 2>&1 の 2 のような先行 fd 番号はリダイレクトの一部で、引数ではない
                if cur and cur[-1].isdigit():
                    cur.pop()
                i += 2  # 演算子とその行き先(fd かファイル名)を読み飛ばす
                continue
            # ; | & && || 改行 () は単純コマンドの区切り
            if cur:
                cmds.append(cur)
                cur = []
            i += 1
            continue
        # 予約語はコマンド位置(蓄積中の単純コマンドが空)でだけ読み飛ばす。ここで捌くのは、
        # 同じ意味の `( gh … )` が `(` の区切りとして既に通っていたのに `{ gh …; }` は
        # 抜ける、という非対称を構成として消すため。gh_args と wants_skip の両方が
        # simple_commands を通るので、表の読者が増えても片方だけ外れることが起きない。
        # 全トークンから除いてはいけない——`--body do` の本文が空になる(実測)。
        if not cur and tok in RESERVED:
            i += 1
            continue
        cur.append(tok)
        i += 1
    if cur:
        cmds.append(cur)
    return cmds


def gh_args(tokens):
    """単純コマンド 1 件が gh 呼び出しなら gh より後のトークン列を、違えば None を返す。"""
    i, after_wrapper = 0, False
    while i < len(tokens):
        tok = tokens[i]
        if tok == "gh" or tok.endswith("/gh"):
            return tokens[i + 1:]
        if ENV_PREFIX_RE.match(tok):
            i += 1
            continue
        if tok in WRAPPERS:
            after_wrapper = True
            i += 1
            continue
        if after_wrapper and tok.startswith("-"):
            i += 1
            continue
        return None
    return None


def subcommand(args):
    """引数列の先頭の位置引数(最大 2 語)。旗の意味が api 系かどうかで変わるため先に確定する。

    先頭に知らない旗があってサブコマンドを特定できないときは None を返す。空タプルと
    区別するのは、「投稿でないと分かった」と「投稿かどうか判らなかった」を混ぜないため——
    混ぜると後者が黙って allow に落ちる。
    """
    words, i = [], 0
    while i < len(args) and len(words) < 2:
        tok = args[i]
        # -R o/r・--repo=o/r・-Ro/r のどれでも来る(gh は pflag の融合形を受ける)
        if tok in GLOBAL_VALUE_FLAGS:
            i += 2
            continue
        if any(tok.startswith(f + "=") or (not f.startswith("--") and tok.startswith(f))
               for f in GLOBAL_VALUE_FLAGS):
            i += 1
            continue
        if tok.startswith("-") and tok != "-":
            return None
        words.append(tok)
        i += 1
    return tuple(words)


def classify(args, heredoc_bodies, live_substitution=False):
    """gh の引数列から (本文候補, 検査できない本文の説明) を返す。"""
    heredoc_bodies = own_heredocs(args, heredoc_bodies)
    # 倒れ先はすべて blocked.append に集める。テスト側が理由の一覧を実装から機械で読み、
    # 一つずつ実際に発火させて突合するため、ここだけは別経路(return の直書き)を作らない。
    # 縛れるのは倒れ先だけで、候補(candidates)側の網羅は機械では言えない——抽出した文字列が
    # 本文かどうかは判定できないので、候補を足す経路は人が読んで守る。
    candidates, blocked = [], []
    sub = subcommand(args)
    if sub is None:
        # サブコマンドが読めない以上、本文を運ぶ旗があるかも判らない。素通しにすると
        # 「読めなかった」が「投稿でない」に化けるので、検査できない側に倒す。
        blocked.append("サブコマンドを特定できない")
        return candidates, blocked
    if sub in NON_POSTING:
        return candidates, blocked  # 投稿でないので本文検出も検査もしない
    is_api = sub[:1] == ("api",)
    is_graphql = sub == ("api", "graphql")
    saw_mutation = False

    def add(kind, value):
        """本文旗 1 つ分を判定し、candidates(読ませる)か blocked(止める)へ必ず積む。

        積まないのは「本文でないと確かめた」ときだけで、それは not_body で明示する。
        main() は候補も blocked も無い状態を「投稿でない」と読んで allow するので、
        積み忘れは取り損ねを黙って素通しにする——`--input -` でヒアドキュメントを
        取り損ねた投稿が実際にこの形で allow に落ちていた(回帰網は tests/run.sh)。
        """
        mark = len(candidates) + len(blocked)
        not_body = False
        if kind == "json":
            # gh api --input の中身は本文とは限らない(secrets の暗号値・設定の JSON 等)。
            # .body を持つときだけ本文として読ませ、持たない JSON は読み役へ送らない。
            if value in ("-", ""):
                if not heredoc_bodies:
                    # パイプ・別プロセスからの stdin と、ヒアドキュメントを取り損ねた形は
                    # ここでは区別できない。兄弟の file 分岐と同じ向きに倒す。
                    blocked.append("別プロセスからの stdin 渡し")
                for raw in heredoc_bodies:
                    try:
                        obj = json.loads(raw)
                    except ValueError:
                        blocked.append("JSON として読めない --input")
                        continue
                    body = obj.get("body") if isinstance(obj, dict) else None
                    if isinstance(body, str):
                        candidates.append(body)
                    elif json_has_long_text(obj):
                        # .body 以外の場所に長い文字列がある。投稿本文なのか設定値なのか
                        # 判らないので、読み役へ送らず「検査できない」として止める。
                        blocked.append("JSON の本文の位置を特定できない")
                    else:
                        not_body = True  # 本文らしい長さの文字列を持たない JSON
            else:
                blocked.append("実ファイル指定")
        elif kind == "text":
            # 変数・コマンド置換は実行時まで中身が無く、検査できない。
            # 引用されていない $(...) や `...` は shlex が演算子で割るので、値が "$" や
            # "`cat" のような断片になって届く。断片かどうかは形だけでは決まらない
            # (単一引用の中の ``` や $ は普通の文字)ので、生の文字列側の判定と併せて見る。
            looks_sub = (value in ("$", "") or value.endswith("$")
                         or value.startswith("`") or value.startswith("$("))
            if VAR_RE.match(value) or (live_substitution and looks_sub):
                blocked.append("変数・コマンド置換渡し")
            else:
                candidates.append(value)
        elif kind == "file":
            if value in ("-", "@-"):
                if heredoc_bodies:
                    candidates.extend(heredoc_bodies)
                else:
                    blocked.append("別プロセスからの stdin 渡し")
            else:
                blocked.append("実ファイル指定")
        if not not_body and len(candidates) + len(blocked) == mark:
            # 引き金は 2 つ: 表に知らない種別が足された・分岐が倒れ先を書き忘れた。
            blocked.append("本文旗の値を判定できない")

    i, n, seen_ddash = 0, len(args), False
    while i < n:
        tok = args[i]
        if tok == "--":
            seen_ddash = True
        elif not seen_ddash and tok.startswith("-") and tok != "-":
            name, val = tok, None
            if tok.startswith("--") and "=" in tok:
                name, val = tok.split("=", 1)
            elif not tok.startswith("--") and len(tok) > 2:
                name, val = tok[:2], tok[2:]  # -b本文 の密着形
            if is_api:
                if name in ("-f", "-F", "--field", "--raw-field"):
                    if val is None and i + 1 < n:
                        i += 1
                        val = args[i]
                    if val and "=" in val:
                        key, fval = val.split("=", 1)
                        if key == "query" and is_graphql:
                            # mutation は投稿。ブロック文字列("""...""")を本文として抜くと、
                            # body 以外のフィールド(ID・トークン・設定値)の値まで外部の読み役
                            # へ送ってしまう(実測)。フィールド名で絞るには GraphQL の構文解析が
                            # 要り、それは docs/coldread-gate-next.md が扱う岐路に入るので、
                            # mutation は本文を取り出さず一律で検査できない側へ倒す。
                            if re.search(r"\bmutation\b", fval):
                                saw_mutation = True
                        elif key == "body":
                            if name in ("-F", "--field") and fval.startswith("@"):
                                add("file", "@-" if fval == "@-" else fval[1:])
                            else:
                                add("text", fval)
                elif name == "--input":
                    if val is None and i + 1 < n:
                        i += 1
                        val = args[i]
                    add("json", val or "")
            else:
                kind = LONG_TEXT_FLAGS.get(name)
                if (name, sub) in LONG_FLAG_NOT_BODY:
                    kind = None
                if kind is None and name in SHORT_TEXT_FLAGS:
                    short_kind, posting = SHORT_TEXT_FLAGS[name]
                    kind = short_kind if sub in posting else None
                if kind:
                    if val is None and i + 1 < n:
                        i += 1
                        val = args[i]
                    add(kind, val or "")
        i += 1

    # gist は本文旗を持たず、位置引数(- は stdin)が本文そのもの。
    # -d/--desc・-f/--filename は値を取るので、その値を位置引数と数えない。
    if sub == ("gist", "create"):
        pos, j = [], 2
        while j < len(args):
            t = args[j]
            if t in ("-d", "--desc", "-f", "--filename"):
                j += 2
                continue
            if t.startswith("-") and t != "-":
                j += 1
                continue
            pos.append(t)
            j += 1
        if "-" in pos or any(t.startswith("__HEREDOC") for t in pos):
            add("file", "-")
        elif pos:
            blocked.append("実ファイル指定")

    if saw_mutation:
        blocked.append("graphql mutation の本文を取り出せない")

    return candidates, blocked


def json_has_long_text(obj, limit=200):
    """JSON のどこかに本文らしい長さの文字列があるか(位置は問わない)。"""
    if isinstance(obj, str):
        return len(obj.strip()) >= limit
    if isinstance(obj, dict):
        return any(json_has_long_text(v, limit) for v in obj.values())
    if isinstance(obj, list):
        return any(json_has_long_text(v, limit) for v in obj)
    return False


def posting_bodies(command):
    """コマンド文字列から (本文候補, 検査できない本文の説明, 解析成否) を返す。"""
    norm, heredoc_bodies = prepare(command)
    tokens = tokenize(norm)
    if tokens is None:
        return [], [], False
    # 字句解析と同じ 1 本を見る。生の側を見ていると `--body "$\<改行>(cat x)"` が
    # 置換渡しと判定されず、実行時まで中身の無い文字列が本文候補として読み役へ回る
    live = has_live_substitution(norm)
    candidates, blocked = [], []
    for simple in simple_commands(tokens):
        args = gh_args(simple)
        if args is None:
            continue
        c, b = classify(args, heredoc_bodies, live)
        candidates.extend(c)
        blocked.extend(b)
    return candidates, blocked, True


READER_PROMPT = """あなたはこの文章について何も知らない初見の読者です。会話の経緯もリポジトリも見ていません。
以下の「本文」だけを読み、理解を実際に妨げた事実だけを報告してください。

見る観点:
(1) この文章があなたに求めていること(読んで何をすべきか)が言えるか
(2) 冒頭 3 行で「何の話か・自分に関係あるか・急ぐか」が掴めるか
(3) 本文の中だけでは意味を解決できない略語・識別子・参照は無いか
(4) 意味を推測で埋めた箇所と、埋めた推測の中身(特に時制・主体・範囲)
(5) 読み終えて残った疑問は何か

報告の形式(この 4 種類だけ。問題の無かった観点は一切書かない):
- (1)〜(4) に該当し、理解を実際に妨げたもの → 1 行 1 件、行頭に「詰まり: 」
- (5) のうち、理解はできたが答えが本文に無い疑問 → 1 行 1 件、行頭に「疑問: 」
- (4) のうち、推測で埋めて読み進められた箇所 → 1 行 1 件、行頭に「補完: 」。
  「何をどう埋めたか」を書く(例:「補完: 障害は今起きていると読んだ」)。
  推測で埋めたなら、理解を妨げていなくても書く——書き手はここで初めて自分の誤読を知る
- 詰まりも疑問も補完も 1 件も無いときだけ、他に何も書かず CLEAN とだけ出力
  (1 件でもあるなら CLEAN とは書かない)
規則: 点数・総評・文体の好み・軽微な言い換え提案は書かない。読めば分かることへの確認は書かない。日本語で。

--- 本文 ---
"""
# 読み役の 3 つのラベル。READER_PROMPT が指示する綴りと 1 対 1 なので隣に置く——
# 欄を増やすときに、指示と仕分けが同じ画面で目に入る形にしておく
LABEL_RE = re.compile(r"(詰まり|疑問|補完)\s*[:：]")


def section(head: str, items: list) -> str:
    """見出し付きの節。中身が無ければ空文字("".join の側で節ごと落ちる)。"""
    return head + "\n" + "\n".join(items) if items else ""


def allow() -> None:
    sys.exit(0)


def deny(reason: str) -> None:
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    }, ensure_ascii=False))
    sys.exit(0)


def log_line(path: str, text: str) -> None:
    try:
        os.makedirs(STATE_DIR, exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            f.write("%s\t%s\n" % (time.strftime("%Y-%m-%d %H:%M:%S"), text))
    except OSError:
        pass


def deny_streak() -> int:
    try:
        with open(DENY_LOG, encoding="utf-8") as f:
            lines = f.readlines()[-10:]
    except OSError:
        return 0
    n = 0
    now = time.time()
    for line in reversed(lines):
        parts = line.rstrip("\n").split("\t")
        if len(parts) < 2:
            break
        try:
            ts = time.mktime(time.strptime(parts[0], "%Y-%m-%d %H:%M:%S"))
        except ValueError:
            break
        if now - ts > DENY_STREAK_WINDOW or parts[1] != "deny":
            break
        n += 1
    return n


def keychain_service() -> str:
    svc = os.environ.get("COLDREAD_KEYCHAIN_SERVICE")
    if svc:
        return svc
    # 利用者のシェルラッパーの命名慣行から推定: ~/.claude → -default, ~/.claude-p1 → -p1
    base = os.path.basename(CONFIG_DIR.rstrip("/"))
    suffix = "default" if base == ".claude" else base.replace(".claude-", "")
    return "claude-code-oauth-" + suffix


def run_reader(body: str):
    """読み役を起動して出力文字列を返す。失敗は例外。"""
    override = os.environ.get("COLDREAD_READER_CMD")
    if override:
        # POSIX シェル文字列として sh -c で実行する。shell=True だと Windows では
        # cmd.exe に渡ってしまい、/dev/null 等が解決できない(GitHub Actions windows-latest で実測)。
        # 復号は strict に保つ——errors="replace" だと壊れた読み役出力で「詰まり」の行頭一致が
        # 崩れ、deny が無音 allow に化ける。読めない出力は例外→deny(検査できないものは通さない)。
        proc = subprocess.run(
            ["sh", "-c", override], input=READER_PROMPT + body,
            capture_output=True, encoding="utf-8", timeout=READER_TIMEOUT,
        )
    else:
        # 認証: トークンを Keychain から読み、形式を検査して環境変数で渡す(ディスクにもログにも書かない)。
        # 取れなくても claude 自身の保存済み認証で動く場合があるため、失敗は握って進む。
        env = dict(os.environ)
        env.setdefault("CLAUDE_CONFIG_DIR", CONFIG_DIR)
        env["COLDREAD_IN_READER"] = "1"
        if "CLAUDE_CODE_OAUTH_TOKEN" not in env and sys.platform == "darwin":
            try:
                tok = subprocess.run(
                    ["security", "find-generic-password", "-s", keychain_service(), "-w"],
                    capture_output=True, encoding="utf-8", timeout=10,
                ).stdout.strip()
                if tok.startswith("sk-ant-oat01-"):
                    env["CLAUDE_CODE_OAUTH_TOKEN"] = tok
            except Exception:
                pass
        claude_bin = shutil.which("claude") or os.path.expanduser("~/.local/bin/claude")
        os.makedirs(STATE_DIR, exist_ok=True)
        proc = subprocess.run(
            [claude_bin, "-p", READER_PROMPT + body,
             "--model", os.environ.get("COLDREAD_MODEL", "sonnet"),
             "--effort", os.environ.get("COLDREAD_EFFORT", "medium"),
             # 読み役は本文を読んで報告するだけで道具は要らない。検査対象の文章そのものを
             # 渡すので、本文に紛れた指示で読み役が動く経路をここで断つ("" で全道具を無効化)。
             "--tools", ""],
            capture_output=True, encoding="utf-8", timeout=READER_TIMEOUT,
            cwd=STATE_DIR, env=env,  # cwd を state 側にしてプロジェクト設定を子に読ませない
        )
    out = (proc.stdout or "").strip()
    if proc.returncode != 0 or not out:
        raise RuntimeError((proc.stderr or "empty output")[:200])
    return out


SKIP_TOKEN = "COLDREAD_SKIP=1"
# 生の文字列の先頭に置かれた逃げ道。解析できないコマンドでも読めるので先に見る。
SKIP_PREFIX_RE = re.compile(r"\s*(?:[A-Za-z_][A-Za-z0-9_]*=\S*\s+)*" + SKIP_TOKEN + r"(?=\s|$)")


def wants_skip(command):
    """逃げ道が書き手の前置として置かれているか。本文に文字列が入っているだけでは効かせない。

    部分文字列一致にすると、門番自身の話題を投稿する本文で門番が黙って外れる(実測)。
    2 段構えなのは、逃げ道の主用途が「解析できないコマンドを通す」ことだから——
    解析前の先頭一致は必ず効かせ、解析できたときに限って cd や && の先の前置も拾う。
    """
    if SKIP_PREFIX_RE.match(command):
        return True
    tokens = tokenize(prepare(command)[0])
    if tokens is None:
        return False
    for cmd in simple_commands(tokens):
        for tok in cmd:
            if tok == SKIP_TOKEN:
                return True
            # 読み飛ばす範囲は gh_args と同じにする。ここだけ env を透かさないと、
            # ゲートが投稿と認めた形なのに逃げ道だけ効かず、案内どおり書いた人が嵌まる
            # (予約語は simple_commands が先に落とすので、ここに書かなくても揃う)
            if tok not in WRAPPERS and not ENV_PREFIX_RE.match(tok):
                break  # 前置が途切れたら、そこから先は引数か本文
    return False


ESCAPE_NOTE = (
    "軽微と判断した指摘を残して通すとき・検査器が使えないときは、"
    "コマンド先頭に COLDREAD_SKIP=1 を付けて再実行する(記録が残る)。"
)
# 通過・差し戻しのどちらでも保証範囲を言う。無言で通すと、摩擦を越えた事実が
# 「審査に合格した」と読まれ、権限・名義の検査の代わりにされる(実例あり)。
SCOPE_NOTE = (
    "この検査が見るのは通じやすさのみ——出してよい投稿か・名義・宛先は検査していない"
    "(宛先の許可制は同梱の destgate)。"
)


def main() -> None:
    try:
        payload = json.load(sys.stdin)
        command = payload.get("tool_input", {}).get("command", "") or ""
    except Exception:
        allow()

    # 読み役の中で自分がもう一度発火すると、読み役が読み役を起こす入れ子になる
    # (深さぶんの待ち時間になり、外側はフックのタイムアウトで無検査のまま通る)。
    # 読み役の道具を殺す --tools "" とは別の機構にしてある——あちらは「読み役が本文中の
    # 指示で動かない」ための処置で、起動の仕方(差し替えの読み役)に依存する。こちらは
    # 起動の仕方に関わらず入れ子を止める。allow に落ちる以上、逃げ道と同じく記録を残す。
    if os.environ.get("COLDREAD_IN_READER") == "1":
        log_line(SKIP_LOG, "in-reader: " + command[:150].replace("\n", " "))
        allow()

    if len(command) < MIN_LEN or not GH_WORD_RE.search(command):
        allow()

    if wants_skip(command):
        log_line(SKIP_LOG, command[:200].replace("\n", " "))
        log_line(DENY_LOG, "skip")
        allow()

    # 解析の失敗は例外の形でも起こりうる(壊れた JSON の再帰・想定外の入力)。
    # 「引用が閉じない」を deny にしているのに例外だけ素通りでは、検査を避ける口になる。
    # 捕まえるのは Exception 全体で、ValueError に狭めるな——狭めた瞬間に、それ以外の例外は
    # フックのクラッシュ(=PreToolUse は続行)になって無検査で通る。
    if len(command) > MAX_LEN:
        log_line(DENY_LOG, "deny\tmaxlen")
        deny(
            "外部投稿ゲート: このコマンドは長すぎて解析しない(%d 文字 > 上限 %d)。\n"
            % (len(command), MAX_LEN)
            + "本文を短くして再実行すること"
            "(上限を変えるにはフックを起動する側の環境変数 COLDREAD_MAX_LEN を設定する——"
            "コマンド先頭に書いてもフック自身には届かない)。\n" + ESCAPE_NOTE
        )

    try:
        candidates, blocked, parsed = posting_bodies(command)
    except Exception as exc:
        parsed, candidates, blocked = False, [], []
        parse_error = str(exc)[:150]
    else:
        parse_error = "引用が閉じていない等"
    if not parsed:
        log_line(DENY_LOG, "deny\tparse-fail")
        deny(
            "外部投稿ゲート: このコマンドは解析できない(%s)。" % parse_error
            + "gh を含むため、投稿かどうか確かめられないものは通せない。\n"
            "引用を直して再実行すること。\n" + ESCAPE_NOTE
        )

    # 「検査できない本文がある」は、別の本文が読めたかどうかと独立に止める。
    # ここを bodies の有無に従属させると、読める本文と同居した投稿が無検査で通る。
    if blocked:
        log_line(DENY_LOG, "deny\tblocked")
        deny(
            "外部投稿ゲート: この投稿は本文をコマンドから取り出せない形をしている(%s)。"
            "検査できないものは通せない。\n"
            "本文はヒアドキュメント(<<'EOF' ... EOF)か、そのサブコマンドの本文旗"
            "(--body / --notes 等)に直接書いて再実行すること。\n"
            % "・".join(sorted(set(blocked))) + ESCAPE_NOTE
        )

    # 素通しの理由が「投稿でない」なのか「網から落ちた」なのかを後から数えられるようにする。
    # 本文旗の綴りが生の文字列にあるのに候補も blocked も空なら、解析の取りこぼしの疑いが濃い。
    # deny にはしない——誤検知の率を測る前に門番の判定を変えると、また実測なしの設計になる。
    miss = BODY_FLAG_RE.search(command)
    if not candidates and not blocked and miss:
        # 残すのは当たった旗の綴りだけ。コマンドの抜粋は残さない——`gh secret set --body <値>` は
        # 投稿でない(NON_POSTING)ので必ずこの枝に落ち、抜粋にすると旗表が「値は秘密そのもの」と
        # 書いている当の値が平文で溜まる。狙いは押し出しの量を測ることなので綴りで足りる。
        log_line(MISS_LOG, miss.group(0))

    bodies = [b for b in candidates if len(b.strip()) >= 200]
    if not bodies:
        allow()
    # 複数の本文が同居するときは最長を代表として読ませる(全部読ませると読み役の回数と
    # 待ち時間が本文の数だけ増える)。取りこぼしの受容は gates/README.md「網の射程」。
    body = max(bodies, key=len)

    try:
        out = run_reader(body)
    except Exception as exc:
        log_line(DENY_LOG, "deny\treader-down")
        deny(
            "外部投稿ゲート: coldreader(文脈ゼロの読み手)の起動に失敗した(%s)。\n" % str(exc)[:150]
            + "手動で検査するなら skill『coldread』の手順で coldreader を立てること。\n"
            + ESCAPE_NOTE
        )

    # ラベルはコロンまで見る。行頭の語だけで拾うと「詰まりは無い」のような地の文が
    # 詰まりに数えられ、指摘ゼロの本文が deny になる(補完の追加で自由文の行が増えたため)。
    found = {"詰まり": [], "疑問": [], "補完": []}
    for line in out.splitlines():
        line = line.strip()
        m = LABEL_RE.match(line)
        if m:
            found[m.group(1)].append(line)
    blocking, questions, fills = found["詰まり"], found["疑問"], found["補完"]

    # 詰まりの有無だけで決める。以前は「最終行が CLEAN なら」も allow の条件だったが、
    # それだと詰まりを列挙した後に CLEAN と書かれた出力が通ってしまう。読み役に本文の
    # 説明以外を書かせる欄(補完)を足したぶん、末尾が CLEAN で終わる形は出やすくなっている。
    if not blocking:
        log_line(DENY_LOG, "allow")
        extra = "\n".join(filter(None, (
            SCOPE_NOTE,
            section("coldreader が推測で埋めた箇所——意図と違うなら投稿を編集して直すこと:", fills),
            section("投稿は通したが、coldreader(初見の読み手)に残った疑問"
                    "(必要なら本文に反映して編集してよい):", questions),
        )))
        print(json.dumps({
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "allow",
                "permissionDecisionReason": "coldreader の検査を通過(詰まりゼロ)",
                "additionalContext": extra,
            }
        }, ensure_ascii=False))
        sys.exit(0)

    streak = deny_streak() + 1
    log_line(DENY_LOG, "deny\tfinding")
    tail = (
        "\n\n【%d 回連続で止まっている】初見指摘は coldreader ごとに揺れる。残る指摘の採否を自分で判断し、"
        "採らない指摘を理由にもう直さないなら COLDREAD_SKIP=1 で通してよい(記録が残る)。" % streak
        if streak >= 3 else "\n\n" + ESCAPE_NOTE
    )
    # 見出しで分ける。混ぜて並べると、直さなくてよい補完・疑問が過半を占めたまま
    # 「以下を直せ」と読め、直す量を過大に見せて逃げ道を引く方向に働く(実測で 8.9 行中 4.7 行)。
    detail = "\n\n".join(filter(None, (
        section("投稿を止めている詰まり(直せば通る):", blocking),
        section("止めてはいないが coldreader が推測で埋めた箇所(意図と違うなら直す):", fills),
        section("残った疑問(反映するかは判断してよい):", questions),
    )))
    deny(
        "外部投稿ゲート: coldreader(文脈ゼロの別プロセスの読み手)がこの本文で詰まった。詰まりを直してから"
        "同じ形で再実行すること(再実行時は直した本文を新しい coldreader が検査する):\n\n"
        + detail[:1500]
        + "\n\n直し方: 指摘の類型を言語化してから、同型を本文全体で掃討する(指摘された 1 箇所だけ直さない)。"
        "詳細は skill『coldread』。\n" + SCOPE_NOTE
        + tail
    )


if __name__ == "__main__":
    main()
