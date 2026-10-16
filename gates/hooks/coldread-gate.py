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

エージェントが自分で検査を外す逃げ道は無い(持ち主の判断 2026-10-16。前の COLDREAD_SKIP=1 は、本文ファイルの
書き直しを避けて未検査のまま出す口に 22 回使われた。今は書かれていても効かせず、書いた事実だけを記録する)。
読み役が起動できないときも止める。同じ投稿が STREAK_CAP 回(3)続けて止められたら、それ以上は書き直させず、
持ち主に渡して止まらせ、stuck.log に残す(初見指摘は読み手ごとに揺れ、
完全収束しないため。firstread-loop と同じ知見。2026-09-07 の試走: 画面を広げた後でも、
3,693 字の実物の返信が 3 回とも別の詰まり 1〜2 件で止まり——4:27/7:40=58% を「計算が合わない」
と読む等——10,179 字版は 3 回中 1 回通った。揺れは画面の広さでは消えない。揺れの中身は
疑問(意味は取れたが根拠・出所が欲しい)を詰まりに格上げする癖だったので、依頼文で詰まりの線を
「その箇所で意味が取れず次の文へ読み進められない」に絞り「迷ったら疑問」と明記した——同じ返信が
4 回中 3 回通り、10,179 字版は 2/2、初稿は 1/1。止まるべき側は止まったまま: コンサル語の地の文
(なぞり 4 件)・未解決の参照「引用 (2)」・文脈ゼロの新規 issue の未定義略語 PXK/RQ-7)。

「補完」(読み手が推測で埋めた箇所)も止めずに申し送る。詰まりを数える設計では、
読み手が自信を持って誤読した本文は詰まり 0 件で通ってしまうため、埋めた中身の側を
書かせて書き手に返す。

読み手が持つ文脈は投稿先で変える。PR/issue のスレッドへ付く返信・編集は、題・番号・
file と行・元の指摘・これまでの返信が同じ画面に見えている状態で読まれるので、フックが
gh でその「画面」を取り、読み手に既知として渡す(新規作成は読み手が何も持たないので
文脈ゼロのまま)。画面を渡さずに読ませると、@相手の名前・PR 番号・相手が付けた印・
相手自身の語まで詰まりに出て、書き手がそれを直すと宛先本人に本人の名前と自分の指摘の
意味を説明する返信になる(2026-09-06 に PR 1583 で実測: 1 本の返信が 39 回止まり、
1,021 字 → 2,555 字に膨れて逃げ道で出た。短く戻した版も止まった)。
画面に有るものを本文で説明している箇所は「冗長」として止めずに申し送る。

画面が既知にするのは「何を指しているか」であって「どう書くか」ではない。相手の言い回し・
業界外の横文字・比喩を本文が自分の地の文として使えば、画面に同じ語が有っても詰まり(相手の語を
指して答えるのは既知)。画面をスレッドの語彙の辞書にすると、スレッドの癖のある書き方に読み手が
引っ張られ、本文がその癖を写す向きに働く。写した箇所は「なぞり」として詰まりと同じく止める(直し方は
説明を足すことではなく、自分の言葉に置き換える)。詰まりの条件文に「相手の語で書けば詰まり」と埋めた
形は実物の読み手に 1 件も拾われなかったが、独立の欄として問うと 3 語とも拾い、引用して指す返信は
拾わなかった(2026-09-07 に北極星・ニアバイ・クロージングで実測)。

読み手に渡す画面は、参加者が実際に見ているものまで広げる: 題・番号・状態(open/merged/draft)・
本文の全文・変更ファイルの一覧・これまでの返信(答える相手の直前のものは切らない)・本文と
スレッドが参照する #番号 の題。2026-09-07 に PR 1429 で実測: 文脈ゼロの読み手(0.9.0 導入前に
開始し 0.8.0 のまま走っていたセッション)が「#1231 #1581 #1283 が何か」「9/2 の提案とは」
「相手の『ご依頼』とは」を詰まりに出し、6 回の deny で 5,455 字 → 10,179 字(用語集 19 語が
全体の 25%)に膨れて逃げ道で出た。詰まりは全件、スレッドを見ていれば出ないものだった。旧上限
(本文 800 字・1 コメント 1,500 字)では画面モードでも同じ——1429 の本文 10,150 字の 8%、相手の
返信 4,698 字の 32% しか見せていなかった。

連続 deny は書き手(session)と投稿先の組で数える。log は profile で共有なので、並行セッションの deny が
自分の連続数を増やし、他所の skip が自分の案内を消す(同じ 2026-09-07 に実測: 7 回目の deny で
案内が消えたのは、その 2 分前に別セッションが skip したため)。log の各行に session・版・投稿先を
残すので、どの版のどのセッションがどこへ出したかを後から grep で引ける(今回は版の推定に列の
形を数える必要があった)。cache に自分より新しい版が在れば検査の結果にその旨を 1 行添える——
`${CLAUDE_PLUGIN_ROOT}` はセッション開始時に固定され、長く開いたセッションは更新後も古い版で
検査し続ける(上の 1429 がそれ。16 時間 0.8.0 のままだった)。

読み手は利用者の CLAUDE.md を読まない(--setting-sources を空にして起動する)。読ませると
「初見が読んでもわかるように書く」等の書き手向けの規則を読み手が自分の指示として持ち、
識別子を全部詰まりに出す側へ寄る(2026-09-06 に実測: 素の起動では利用者の CLAUDE.md の
見出しをそのまま引用した。空にすると NONE)。

記録は $CLAUDE_CONFIG_DIR/coldread-gate/ に 4 本:
  denies.log  allow / deny の別(deny はタブ区切りで種別も。maxlen・parse-fail・
              blocked・reader-down・reader-shape・finding・cap)。finding と allow には本文の長さと読み方
              (screen=画面を渡した / cold=文脈ゼロ)も付く——連続 deny の間に本文が
              どれだけ膨れたかを示すため。blocked には止めた理由(why=)が付く。各行の末尾に sid=(session id の先頭 8 字)
              v=(この門番の版) to=(投稿先。種別:repo:番号、新規作成はサブコマンド)、本文を読んだ deny には
              fp=(本文の指紋。本文を写さずに、同じ投稿の書き直しかを比べる)
  skip.log    効かせなかった逃げ道(refused)と、読み役の中で発火した呼び出しのコマンド先頭
  misses.log  本文旗の綴りが在るのに候補も blocked も空だった単純コマンドの、旗の綴りと先頭の語
              =網から落ちた疑い。「投稿でなかった」と区別が付かないと押し出しの量を測れないので分けて残す
  stuck.log   往復の上限に当たった投稿の、会話・版・宛先の種類・止めた回数と理由の並び・本文の長さの並び
              (本文は写さない)。関所か書き方のどちらかがおかしい合図なので、後で直す材料にする

環境変数:
  COLDREAD_READER_CMD        読み役コマンドの差し替え(POSIX sh 文字列として sh -c 実行。stdin に依頼文+本文)。テスト用
  COLDREAD_GH_CMD            画面(投稿先のスレッド)を取る gh の差し替え(POSIX sh 文字列として
                             sh -c 実行。$1 以降に gh の引数列)。テスト用
  COLDREAD_MODEL             既定 sonnet
  COLDREAD_EFFORT            既定 medium
  (手元の文書の読み手の環境変数 COLDREAD_DOC_* は、下の「手元の文書」の節の冒頭)
  COLDREAD_MAX_LEN           これを超えるコマンドは解析せず deny。既定 100000
  COLDREAD_IN_READER=1       読み役の中であることの印(自動で付く)。入れ子の再発火を防ぐ
  COLDREAD_KEYCHAIN_SERVICE  macOS Keychain の OAuth トークンのサービス名(未指定なら
                             CLAUDE_CONFIG_DIR の末尾から推定: ~/.claude-p1 → claude-code-oauth-p1)
"""
import concurrent.futures
import hashlib
import json
import os
import re
import shlex
import shutil
import stat
import subprocess
import sys
import time

# Windows では stdio が locale 既定の code page になり(GitHub Actions windows-latest で
# cp1252 を実測。日本語 Windows なら cp932)、日本語の deny メッセージが UnicodeEncodeError で
# 落ちてフック自体が素通りになるため、UTF-8 に固定する(hook の入出力は UTF-8 の JSON)。
for _stream in (sys.stdin, sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

# 認証の段は隣の共有の本文が持つ(複数のプラグインに写しで在り、同一性は tests/run.sh の柵が見る)。
# **`sys.path[0]` に頼らない**——検査は importlib でパスから読み込むので、自分の在り処から明示で足す。
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import claude_auth  # noqa: E402

CONFIG_DIR = claude_auth.config_dir(os.environ)   # 決め方の正本は共通の claude_auth（リポジトリの scripts/ から写す）
STATE_DIR = os.path.join(CONFIG_DIR, "coldread-gate")
SKIP_LOG = os.path.join(STATE_DIR, "skip.log")
DENY_LOG = os.path.join(STATE_DIR, "denies.log")
MISS_LOG = os.path.join(STATE_DIR, "misses.log")
STUCK_LOG = os.path.join(STATE_DIR, "stuck.log")
# 上限。これを超える文字列は正規表現の後方追跡(HEREDOC_RE)が重くなりうるので解析せず deny
MAX_LEN = int(os.environ.get("COLDREAD_MAX_LEN", "100000"))
READER_TIMEOUT = 210
GH_TIMEOUT = 12   # 画面取得の gh 呼び出し 1 回分
GH_BUDGET = 40    # 画面取得の合計。読み役の 210 と手元の文書の控え(git 2 回・各 5 秒まで)と合わせてフックの timeout(275s)に収める——
                  # 超えるとフック自体が時間切れになり、投稿が無検査で通る(fail-open)
GH_PAGES = 5      # 会話の取得で辿る最大ページ数(1 ページ 100 件)
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
# 開始行の区切りの後ろには、同じ行で旗やパイプが続きうる(`<<'J' -q .html_url`・`<<'EOF' | tail`)。
# 区切りの直後に改行を求めていた頃は、この形を見落として「別プロセスからの stdin」で止めていた(33 件)。
# 続きは群 3 に取って解析用の文字列に残す(旗もパイプも gh の引数列と区切りとして読む)。区切りの直後に
# 区切りの字が続かないこと((?!…))を求めるのは、`<<EOFX` を区切り EOF と続き X に割らないため。
# 終わりの行の字下げを許すのは `<<-` のときだけで、許すのもタブだけ(bash と同じ)。`<<EOF` で字下げした `  EOF` の行を
# 終わりと読むと、本文の続きがシェルとして解析され、gh が出す本文の後半が読み役に届かない。
# 群は 1=`-` 2=引用 3=区切り 4=開始行の続き 5=本文。
HEREDOC_RE = re.compile(
    r"""<<(-)?\s*(['"]?)([A-Za-z_][A-Za-z0-9_.-]*)\2(?![A-Za-z0-9_.-])([^\r\n]*)\r?\n(.*?)\r?\n(?(1)\t*)\3(?:\r?\n|\r?$)""",
    re.S,
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
HELP_FLAGS = {"--help", "-h", "--version"}
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
# `gh api` は自分の旗を endpoint の前にも置ける(gh 2.102.0 の `gh api --help` の FLAGS)。知らない旗として None に倒すと、
# 読むだけの `gh api --allow-escape-sequences <endpoint>` まで「検査できない」で止まった(2026-10-15 に実測)。
# 値を取る旗は値ごと読み飛ばす。ここに無い旗は今までどおり None(検査できない側)に倒す
API_VALUE_FLAGS = {"--cache", "-F", "--field", "-H", "--header", "--hostname", "--input", "-q", "--jq",
                   "-X", "--method", "-p", "--preview", "-f", "--raw-field", "-t", "--template"}
API_BOOL_FLAGS = {"--allow-escape-sequences", "-i", "--include", "--paginate", "--silent", "--slurp", "--verbose"}
WRAPPERS = {"env", "command", "exec", "nohup", "time", "timeout", "gtimeout"}
# 前置の旗のうち値を取るもの(値ごと読み飛ばす)と、前置が取る位置引数の数(timeout の時間)。
# timeout を前置に入れていなかった頃は `timeout 180 gh pr create …` の gh が見えず素通しだった
WRAPPER_VALUE_OPTS = {
    "timeout": {"-s", "--signal", "-k", "--kill-after"},
    "gtimeout": {"-s", "--signal", "-k", "--kill-after"},
    "env": {"-u", "--unset", "-C", "--chdir"},
}
WRAPPER_POSITIONALS = {"timeout": 1, "gtimeout": 1}
# シェルの予約語。単純コマンドの先頭語になりうるが、コマンド名ではないので読み飛ばす。
# 飛ばさないと `{ gh …; }`・`if …; then gh …`・`while …; do gh …`・`! gh …` の gh が
# 見えず、投稿が無検査・無記録で通る(両ゲートとも。実測)。同じ意味の `( gh … )` は
# `(` が OP_CHARS にあるので元から通っていた——書き方だけで片方が抜ける状態だった。
# if・while・until も直後に条件のコマンドを取る(`if gh … --body-file f; then` の gh が見えず素通しだった)。
# 載せるのは「直後にコマンドが来る」語だけ。done・fi・in は後ろにコマンドを取らないので
# 入れない(入れても発火させられず、表の全メンバーを検査する回帰が張れない)。
RESERVED = {"{", "!", "then", "else", "elif", "do", "if", "while", "until"}
OP_CHARS = set("();<>|&\n")
# リダイレクト演算子(演算子と行き先を読み飛ばす)。&> >& <& は & を含むが区切りではない。
REDIRECT_OPS = {"<", ">", ">>", "<<", "<<<", "<&", ">&", "&>", "&>>", ">|"}
VAR_RE = re.compile(r"\$\{?[A-Za-z_][A-Za-z0-9_]*\}?\Z")
# 環境変数の前置(NAME=値)。単純コマンドの先頭で読み飛ばす範囲を決める
ENV_PREFIX_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*=")
# 前段の粗選別。部分文字列だと highlight・through 等の語で解析に入ってしまう
GH_WORD_RE = re.compile(r"\bgh\b")
# 網から落ちたことの検出だけに使う綴り(判定には使わない)。本文旗が単純コマンドの語にあるのに
# 候補も blocked も空なら、投稿でないのではなく解析が取りこぼした疑いがある(当て方は analyze())。
# 権威表から導出する——手で 2 本目の綴り表を持つと、旗を足したとき計器だけが黙り、
# 最も新しい=最も取りこぼしやすい旗のところで数えられなくなる(表と検査の突合は
# tests/coldread-table-case.py)。--body-file は --body\b が既に当てるので重複は無害。
API_BODY_FLAGS = {"--input"}  # classify() の api 経路が本文と見る旗
BODY_FLAG_RE = re.compile(
    "|".join(sorted(re.escape(f) + r"\b" for f in set(LONG_TEXT_FLAGS) | API_BODY_FLAGS))
    + r"|-[fF]\s*body="
)
# 短縮形(-b/-c/-n/-F)は入れない。git checkout -b 等と綴りが衝突して誤検知が増え、計器が濁るため。
# 当てるのはヒアドキュメントを印に置き換え、行継続を畳んだ後の語なので、本文の中の綴りは数えない。
# 短縮形を数えないことが、この計器が下限しか出さないことの内訳で、押し出しの量は「これ以上」としてしか読めない。


HEREDOC_MARK = "__HEREDOC%d__"


class Expands(str):
    """区切りを引用しないヒアドキュメント(`<<EOF`)で、本文に $ か ` が在るもの。シェルが展開するので、字のままの
    本文は実際に出る本文と違う。読ませずに止める印(中身は普通の str として扱える)。"""


def shield_heredocs(command):
    """ヒアドキュメント本文を取り出し、解析用の文字列では番号付きの印に置き換える。

    番号を振るのは、どの単純コマンドに付いたヒアドキュメントかを後で見分けるため。
    番号が無いと、同じ行の別コマンド(cat > f <<EOF)の中身まで gh の本文候補に混ざる。

    続きの行に 2 本目の開始(`cat <<A > f; gh … <<B`)が在ると、1 回目の置換では 2 本目の開始が置換後の
    文字列に入って走査されないので、置換が起きなくなるまで繰り返す(bash も本文を開始の順に読む)。
    """
    bodies = []

    def repl(m):
        body = m.group(5)
        bodies.append(Expands(body) if not m.group(2) and re.search(r"[$`]", body) else body)
        return " " + (HEREDOC_MARK % (len(bodies) - 1)) + " " + m.group(4) + "\n"

    while True:
        command, n = HEREDOC_RE.subn(repl, command)
        if not n:
            return command, bodies


def own_heredocs(args, heredoc_bodies):
    """この単純コマンドに付いたヒアドキュメント本文だけを返す。"""
    return [heredoc_bodies[i] for i in range(len(heredoc_bodies))
            if (HEREDOC_MARK % i) in args]


def has_live_variable(text):
    """引用の外(または二重引用の中)に $名前・${ があるか(変数の展開)。単一引用の中は展開されない。"""
    return _live(text, lambda t, i: t[i] == "$" and i + 1 < len(t) and (t[i + 1].isalpha() or t[i + 1] in "_{"))


def has_live_substitution(text):
    """引用の外(または二重引用の中)に $( や ` があるか。単一引用の中は展開されない。

    引用の種別は shlex が落としてしまうので、生の文字列の側で見る。これを見ないと、
    本文に ``` や `--body` を含むだけの普通の文章まで「置換渡し」と誤判定する。
    """
    return _live(text, lambda t, i: t[i] == "`" or t.startswith("$(", i))


def _live(text, hit):
    """単一引用の外で hit(text, 位置) が真になる位置が在るか。"""
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
            elif hit(text, i):
                return True
        elif c in "'\"":
            quote = c
        elif hit(text, i):
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


class Simple:
    """単純コマンド 1 件: 引数列・リダイレクト((演算子, 行き先) の列)・直前の区切り。

    ops は直前の区切りの演算子と、それが現れた括弧の深さの列((演算子, 深さ))。depth はこのコマンドの深さ
    (サブシェル `( … )`・`$( … )` の中なら 1 以上)。sep は ops のうち括弧でないものの代表(効果が届かない演算子が
    在ればそれ、無ければ最後のもの。先頭のコマンドは "")。
    """

    __slots__ = ("args", "redirects", "sep", "ops", "depth")

    def __init__(self, args, redirects, ops, depth):
        self.args, self.redirects, self.ops, self.depth = args, redirects, ops, depth
        plain = [op for op, _ in ops if op not in "()"] or [op for op, _ in ops][-1:]
        weak = [op for op in plain if op not in _SEQUENTIAL]
        self.sep = weak[0] if weak else (plain[-1] if plain else "")


_OP_RE = re.compile(r"&&|\|\||;;|[;&|()\n]")


def split_commands(tokens):
    """演算子で区切った単純コマンド(Simple)の列。リダイレクトは引数列から除き、redirects に残す。

    区切りを残すのは、本文ファイルのパスを静的に解くとき(変数の代入・cd)に、前のコマンドの効果が
    gh まで届くか(; && 改行なら届く。| & ( ) は別のプロセスなので届かない)を見るため。
    """
    cmds, cur, redirects, ops, depth, cmd_depth, i = [], [], [], [], 0, 0, 0
    while i < len(tokens):
        tok = tokens[i]
        if tok and all(c in OP_CHARS for c in tok):
            if tok in REDIRECT_OPS:
                # 2>&1 の 2 のような先行 fd 番号はリダイレクトの一部で、引数ではない
                if cur and cur[-1].isdigit():
                    cur.pop()
                redirects.append((tok, tokens[i + 1] if i + 1 < len(tokens) else ""))
                i += 2  # 演算子とその行き先(fd かファイル名)を読み飛ばす
                continue
            # ; | & && || 改行 () は単純コマンドの区切り。shlex は続いた区切りを 1 語にする(`);`)ので演算子に割る
            if cur:
                cmds.append(Simple(cur, redirects, ops, cmd_depth))
                cur, redirects, ops = [], [], []
            for op in _OP_RE.findall(tok):
                if op == ")":
                    depth -= 1
                ops.append((op, depth))
                if op == "(":
                    depth += 1
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
        if not cur:
            cmd_depth = depth
        cur.append(tok)
        i += 1
    if cur:
        cmds.append(Simple(cur, redirects, ops, cmd_depth))
    return cmds


def simple_commands(tokens):
    """演算子で区切った単純コマンドのトークン列を返す。リダイレクトは演算子と行き先ごと除く。"""
    return [c.args for c in split_commands(tokens)]


def command_start(tokens):
    """単純コマンドの命令名の位置。前置(環境変数の代入・env/timeout 等とその旗と値)を読み飛ばす。無ければ len(tokens)。

    gh_args と wants_skip の両方がここを通る——読み飛ばす範囲を 2 か所に書くと、片方だけ外れる。
    """
    i, wrapper, need = 0, None, 0
    while i < len(tokens):
        tok = tokens[i]
        if wrapper and tok.startswith("-") and tok != "-":
            # 値を取る旗は値ごと飛ばす(--signal=KILL・-sKILL の融合形は 1 語)
            i += 2 if tok in WRAPPER_VALUE_OPTS.get(wrapper, ()) else 1
            continue
        if need:
            need -= 1   # 前置が取る位置引数(timeout の時間)
            i += 1
            continue
        if ENV_PREFIX_RE.match(tok):
            i += 1
            continue
        if tok in WRAPPERS:
            wrapper, need = tok, WRAPPER_POSITIONALS.get(tok, 0)
            i += 1
            continue
        return i
    return i


def gh_args(tokens):
    """単純コマンド 1 件が gh 呼び出しなら gh より後のトークン列を、違えば None を返す。"""
    i = command_start(tokens)
    if i < len(tokens) and (tokens[i] == "gh" or tokens[i].endswith("/gh")):
        return tokens[i + 1:]
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
        if words == ["api"] and tok.startswith("-") and tok != "-":
            name = tok.split("=", 1)[0]
            if name in API_BOOL_FLAGS:
                i += 1
                continue
            if name in API_VALUE_FLAGS:
                i += 1 if "=" in tok else 2
                continue
            if not tok.startswith("--") and tok[:2] in API_VALUE_FLAGS:   # -XPOST・-fbody=… の融合形
                i += 1
                continue
        if tok.startswith("-") and tok != "-":
            return None
        words.append(tok)
        i += 1
    return tuple(words)


def classify(args, heredoc_bodies, live_substitution=False, ctx=None, live_variable=True):
    """gh の引数列から (本文候補, 検査できない本文の説明) を返す。

    ctx(BodyFiles)が有れば、本文ファイル・変数で書いた値を同じコマンドの中で静的に解いて読む。無ければ
    (destgate のように投稿かどうかだけを見る呼び手)、ファイルと変数は今までどおり検査できない側に倒す。
    live_variable はコマンドの中に展開される $名前 が在るか(無ければ本文の中の $ は字のまま)。
    """
    heredoc_bodies = own_heredocs(args, heredoc_bodies)
    # 倒れ先はすべて blocked.append に集める。テスト側が理由の一覧を実装から機械で読み、
    # 一つずつ実際に発火させて突合するため、ここだけは別経路(return の直書き)を作らない。
    # 縛れるのは倒れ先だけで、候補(candidates)側の網羅は機械では言えない——抽出した文字列が
    # 本文かどうかは判定できないので、候補を足す経路は人が読んで守る。
    candidates, blocked = [], []
    if any(t in HELP_FLAGS for t in (args[:args.index("--")] if "--" in args else args)):
        # --help・-h・--version は旗がどこに在っても gh が案内を出して終わる(投稿しない)。短いコマンドを解析の前に
        # 通していた頃は `gh --version` も通っていたので、ここで止めると逆戻りになる
        return candidates, blocked
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
    gql_fields = {}   # graphql の -f/-F の欄(名前 → (型付きか, 値))。query と変数を後でまとめて見る

    def file_failed(why):
        """本文ファイルを読まなかった理由を blocked へ積む(理由ごとに直し方が違うので語を分ける)。"""
        if why == "path":
            blocked.append("本文ファイルのパスが決まらない")
        elif why == "writer":
            blocked.append("本文ファイルを同じコマンドの中で書き換えうる")
        elif why == "notreg":
            blocked.append("本文ファイルが通常のファイルでない")
        elif why == "large":
            blocked.append("本文ファイルが上限より大きい")
        elif why == "utf8":
            blocked.append("本文ファイルが UTF-8 でない")
        elif why == "unreadable":
            blocked.append("本文ファイルを読めない")
        elif why == "expand":
            blocked.append("区切りを引用しないヒアドキュメントの展開")
        else:   # ctx の無い呼び手(destgate)
            blocked.append("実ファイル指定")

    def read_file(value):
        """本文ファイルの中身。読めなければ理由を blocked へ積んで None。"""
        text, why = ctx.read(value) if ctx else (None, "noctx")
        if text is None:
            file_failed(why)
        return text

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
            # 本文の位置(.body と review の comments[].body)の中身だけを読ませる。
            if value in ("-", ""):
                raws = heredoc_bodies
                if any(isinstance(b, Expands) for b in raws):
                    file_failed("expand")
                    raws = []
                elif not raws:
                    # パイプ・別プロセスからの stdin と、ヒアドキュメントを取り損ねた形は
                    # ここでは区別できない。兄弟の file 分岐と同じ向きに倒す。
                    blocked.append("別プロセスからの stdin 渡し")
            else:
                raws = [t for t in (read_file(value),) if t is not None]
            for raw in raws:
                body, why = json_bodies(raw)
                if why == "json":
                    blocked.append("JSON として読めない --input")
                elif why == "pos":
                    # 本文の位置の外に長い文字列がある。投稿本文なのか設定値なのか
                    # 判らないので、読み役へ送らず「検査できない」として止める。
                    blocked.append("JSON の本文の位置を特定できない")
                elif body is not None:
                    candidates.append(body)
                else:
                    not_body = True  # 本文らしい長さの文字列を持たない JSON
        elif kind == "text":
            # 変数・コマンド置換は実行時まで中身が無い。変数だけは、同じコマンドの中の代入から
            # 静的に解けるなら読む(ctx.var)。解けなければ検査できない。
            # 引用されていない $(...) や `...` は shlex が演算子で割るので、値が "$" や
            # "`cat" のような断片になって届く。断片かどうかは形だけでは決まらない
            # (単一引用の中の ``` や $ は普通の文字)ので、生の文字列側の判定と併せて見る。
            # 本文の一部だけが変数の形("See: $B")も同じ——字のまま読ませると、実際に出る本文と違う。
            looks_sub = (value in ("$", "") or value.endswith("$")
                         or value.startswith("`") or value.startswith("$("))
            if "$" in value and (live_variable or VAR_RE.match(value)):
                got = ctx.var(value) if ctx else None
                if got is None:
                    blocked.append("変数・コマンド置換渡し")
                else:
                    candidates.append(got)
            elif live_substitution and looks_sub:
                blocked.append("変数・コマンド置換渡し")
            else:
                candidates.append(value)
        elif kind == "file":
            if value in ("-", "@-"):
                if any(isinstance(b, Expands) for b in heredoc_bodies):
                    file_failed("expand")
                elif heredoc_bodies:
                    candidates.extend(heredoc_bodies)
                else:
                    blocked.append("別プロセスからの stdin 渡し")
            else:
                text = read_file(value)
                if text is not None:
                    candidates.append(text)
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
                        typed = name in ("-F", "--field")
                        if is_graphql:
                            gql_fields[key] = (typed, fval)
                        elif key == "body" or key.endswith("[body]"):
                            # comments[][body] は review の行コメント(gh api の配列の欄の書き方)
                            if typed and fval.startswith("@"):
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

    if is_graphql:
        query = None
        if "query" in gql_fields:
            typed, qv = gql_fields.pop("query")
            query = read_file(qv[1:]) if typed and qv.startswith("@") and qv != "@-" else qv
        if query and re.search(r"\bmutation\b", query):
            # mutation が本文を運ぶのは body(と readme)の欄だけ。欄の値だけを抜き、ほかの欄(ID・トークン・
            # 設定値)は読み役へ送らない。欄を持たない mutation(resolveReviewThread など)は投稿でない——
            # 一律で止めていた頃は、これが往復の 57 件を生んでいた。
            texts = graphql_bodies(query, gql_fields, read_file)
            if texts is None:
                blocked.append("graphql mutation の本文を取り出せない")
            elif texts:
                candidates.append("\n\n".join(texts))

    return candidates, blocked


# graphql の mutation で本文を運ぶ欄。`$body:`(変数の宣言)は欄ではないので、直前の $ と語の字を除く
GQL_BODY_FIELD_RE = re.compile(r"""(?<![\w$])(?:body|readme)\s*:\s*""")
GQL_STRING_RE = re.compile(r'"""(.*?)"""|"((?:[^"\\]|\\.)*)"|\$([A-Za-z_]\w*)', re.S)


def graphql_bodies(query, fields, read_file):
    """mutation の本文の欄の値の列。値が決まらない欄が 1 つでも在れば None(止める)。

    値はブロック文字列・文字列・変数($名前 は -f/-F の同じ名前の欄)。変数として使われなかった
    body・…[body] の欄(input[body]= のように入れ物ごと渡す形)も本文として読む。
    """
    texts, used = [], set()
    for m in GQL_BODY_FIELD_RE.finditer(query):
        v = GQL_STRING_RE.match(query, m.end())
        if v is None:
            return None   # 入れ物の変数・列挙など、文字列でない値
        if v.group(1) is not None:
            texts.append(v.group(1))
        elif v.group(2) is not None:
            try:
                texts.append(json.loads('"%s"' % v.group(2)))
            except ValueError:
                texts.append(v.group(2))
        else:
            name = v.group(3)
            if name not in fields:
                return None
            used.add(name)
            texts.append(_gql_field_value(fields[name], read_file))
    for key, field in fields.items():
        if key not in used and (key == "body" or key.endswith("[body]")):
            texts.append(_gql_field_value(field, read_file))
    if any(t is None for t in texts):
        return None
    return texts


def _gql_field_value(field, read_file):
    typed, value = field
    if typed and value.startswith("@") and value != "@-":
        return read_file(value[1:])
    return value


def json_bodies(raw):
    """--input の JSON → (本文, 理由)。本文を持たないと確かめたら (None, None)。理由は json・pos。

    本文の位置は .body と、review の行コメント comments[].body。.body だけを見ていた頃は、行コメントが
    読まれずに出ていた(27 件。.body が空の review も在った)。読ませるのは 1 本にまとめた全部——
    最長の 1 本だけを読ませる決まり(main)で行コメントが落ちないように。位置の外に長い文字列が残れば、
    本文なのか設定値なのか判らないので止める。
    """
    try:
        obj = json.loads(raw)
    except ValueError:
        return None, "json"
    texts, rest = [], obj
    if isinstance(obj, dict):
        rest = dict(obj)
        body = rest.pop("body", None)
        if isinstance(body, str):
            texts.append(body)
        elif body is not None:
            rest["body"] = body
        comments = rest.pop("comments", None)
        if isinstance(comments, list):
            left = []
            for c in comments:
                if isinstance(c, dict) and isinstance(c.get("body"), str):
                    c = dict(c)
                    texts.append("[行コメント: %s]\n%s" % (c.get("path") or "?", c.pop("body")))
                left.append(c)
            rest["comments"] = left
        elif comments is not None:
            rest["comments"] = comments
    if json_has_long_text(rest):
        return None, "pos"
    if not texts:
        return None, None
    return "\n\n".join(t for t in texts if t.strip()), None


def json_has_long_text(obj, limit=200):
    """JSON のどこかに本文らしい長さの文字列があるか(位置は問わない)。"""
    if isinstance(obj, str):
        return len(obj.strip()) >= limit
    if isinstance(obj, dict):
        return any(json_has_long_text(v, limit) for v in obj.values())
    if isinstance(obj, list):
        return any(json_has_long_text(v, limit) for v in obj)
    return False


# ---- 本文ファイル(フックが自分で読む) ----------------------------------------
# 本文がファイルに在る形(--body-file f・-F f・-F body=@f・--input f)を「取り出せない」で止めて書き直させて
# いた頃は、往復が 124 回あり、うち 22 回は逃げ道で未検査のまま出た。フックが自分で読めば往復は要らない。
# 読むのは gh がそのファイルを読むときに同じ中身だと静的に言えるときだけで、言えなければ止める:
#   - パスは字のまま・同じコマンドの中で代入した変数・cwd(フックの入力)からの相対・`cd <絶対パス> &&` の先の
#     相対まで解く。それ以外(解けない変数・~・グロブ・`;` で続く cd の後の相対)は止める
#   - 同じコマンドの中で本文ファイルを書く命令が在れば、`cat > f <<EOF` 1 本だけならそのヒアドキュメントを
#     読む(フックの時点のファイルは古い中身)。それ以外の書き手(cp・mv・sed・tee・>…)が在れば止める
#   - 開くのは O_NONBLOCK で、開いた後に fstat で通常のファイルかを見る(FIFO が書き手を待ってフックを止めると、
#     フックの timeout で無検査で通る)。上限(COLDREAD_MAX_LEN 字)を超える・UTF-8 でないものは止める
# 残る穴: フックが読んだ後、gh が読むまでの間に別のプロセスが書き換える余地(チェックと実行の間。gates/README.md)。
WRITE_OPS = {">", ">>", ">|", "&>", "&>>"}
# 本文ファイルの名前を引数に持っていても、ファイルを書き換えない命令(書くリダイレクトは別に見る)
READ_ONLY_CMDS = {"cat", "wc", "head", "tail", "ls", "test", "[", "stat", "file", "grep", "diff", "less",
                  "jq", "echo", "printf", "cd"}
_SEQUENTIAL = (";", "&&", "\n")   # 前のコマンドの効果(代入・cd)が後ろへ届く区切り
_RUNS_BEFORE = ("", ";", "\n")     # 直前の区切りがこれなら、そのコマンドは前の成否に関わらず必ず走る
CD_WORDS = {"cd", "pushd", "popd", "chdir"}
CONDITIONAL_WORDS = {"if", "then", "else", "elif", "fi", "case", "esac", "while", "until", "for", "do", "done", "select"}
# 変数を入れ直しうる命令(引数に名前を取る)。この名前は同じコマンドの中の代入から解かない
REASSIGN_CMDS = {"read", "printf", "declare", "typeset", "local", "readonly", "mapfile", "readarray", "for",
                 "select", "unset", "let", "getopts"}
_APPEND_RE = re.compile(r"([A-Za-z_][A-Za-z0-9_]*)\+=")
_VAR_REF_RE = re.compile(r"\$(?:\{([A-Za-z_][A-Za-z0-9_]*)\}|([A-Za-z_][A-Za-z0-9_]*))")


def single_quoted_dollar(text):
    """単一引用の中に $ が在るか。shlex は引用を落とすので、'$S' と "$S" を語の側では見分けられない。"""
    i, quote = 0, None
    while i < len(text):
        c = text[i]
        if quote == "'":
            if c == "'":
                quote = None
            elif c == "$":
                return True
        elif c == "\\" and quote != "'":
            i += 1
        elif quote == '"':
            if c == '"':
                quote = None
        elif c in "'\"":
            quote = c
        i += 1
    return False


_MSYS_DRIVE_RE = re.compile(r"/([A-Za-z])(?=/|$)")
_native_cache = {}


def native_path(p):
    """コマンドに書かれたパスを、フックの Python が開ける形にする。直せなければ None(止める側)。

    Windows の Claude Code は Bash の道具を Git Bash(MSYS2)で走らせるので、コマンドの中のパスは `/c/Users/…`・
    `/tmp/…` の POSIX 形で書かれうる。フックの Python はネイティブの Windows で動き、その形を開けない(`/tmp/x` は
    `C:\\tmp\\x` と読まれる)。MSYS2 が同梱する cygpath(`-w` で Windows の形を出す)で直し、cygpath が無ければ
    ドライブの形(`/c/…` → `C:\\…`)だけを直す。`/tmp` などの割り当ては Git の入れ場所で変わるので推し量らない。
    Windows 以外と、`/` で始まらないパス(`C:/…`・相対パス)はそのまま返す。
    """
    if os.name != "nt" or not p.startswith("/") or p.startswith("//"):
        return p
    if p not in _native_cache:
        out = None
        try:
            r = subprocess.run(["cygpath", "-w", p], capture_output=True, timeout=5,   # 掛かれば止める側に倒す
                               env=dict(os.environ, LC_ALL="C.UTF-8"))
            if r.returncode == 0:
                out = r.stdout.decode("utf-8").strip() or None
        except (OSError, subprocess.SubprocessError, UnicodeDecodeError):
            pass
        if out is None:
            m = _MSYS_DRIVE_RE.match(p)
            out = m.group(1).upper() + ":\\" + p[3:].replace("/", "\\") if m else None
        _native_cache[p] = out
    return _native_cache[p]


class BodyFiles:
    """1 つのコマンド文字列の中で、k 番目の単純コマンド(gh)が読む本文ファイルと変数を静的に解く。

    解くのは、前のコマンドが必ず走って効果が gh まで届くと字面で言えるときだけ。言えなければ None(止める側)。
    """

    def __init__(self, cmds, cwd, heredoc_bodies, norm, tokens=()):
        self.cmds, self.heredocs, self.norm = cmds, heredoc_bodies, norm
        # if・case・繰り返しの中の命令は、区切りが ; でも走るとは限らない(予約語は単純コマンドから落ちるので、語の列で見る)
        self.conditional = any(t in CONDITIONAL_WORDS for t in tokens)
        self.cwd = cwd if cwd and os.path.isabs(cwd) else None
        self.k, self.moved = 0, False
        self._assigned = None
        self._sq = None
        # 繰り返し・関数の中では、gh の後に書いた命令も次の gh の前に走る
        self.looped = any(c.args[:1] in (["done"], ["}"]) for c in cmds)

    def at(self, k, prefix):
        """k 番目の gh 呼び出しを見る。prefix は gh より前の語(env -C・-C<dir>・--chdir は cwd を変える)。"""
        self.k = k
        self.moved = any(t.startswith(("-C", "--chdir")) for t in prefix)
        return self

    def _flows(self, j, k=None):
        """j 番目のコマンド(変数の代入)が必ず走り、その値が k 番目(既定は gh)まで届くか。

        届かないのは: 条件・繰り返しの中・`|| B=x`(走らないことがある)・`B=x |`・`B=x &`(別のプロセスで代入される)・
        `( B=x ); gh`(サブシェルが先に閉じる)。`a && B=x` は、そこから gh まで && だけで続くときだけ(B=x が走らなければ
        gh も走らない)。間に在るほかのコマンドのパイプや `$( … )` は、親のシェルの変数を変えないので見ない。
        """
        k = self.k if k is None else k
        if not (j < k) or self.conditional or not self._between(j, k, None, below_ok=False):
            return False
        d = self.cmds[j].depth
        if any(op in ("|", "&") and dep == d for op, dep in self.cmds[j + 1].ops):
            return False
        if self._runs(j, ()):
            return True
        return self._runs(j, ("&&",)) and self._between(j, k, ("&&",), below_ok=False)

    def _runs(self, j, also):
        """j 番目のコマンドが前の成否に関わらず走るか(直前の区切りのうち括弧でないものが ; 改行 か also だけ)。"""
        return all(op in _RUNS_BEFORE + also for op, _ in self.cmds[j].ops if op not in "()")

    def _between(self, j, k, allowed, below_ok):
        """j の後から k までの区切りのうち、j の深さ以下に現れた演算子がどれも allowed か(None なら演算子は問わない)。

        j より深いところ(後の `$( … )` の中)の演算子は、j の効果(代入・cd・書き込み)の届き方に関わらないので見ない。
        below_ok が偽なら、j を囲むサブシェルが k より前に閉じる(深さが j より浅くなる)ことも許さない
        (`( S=x ); gh` の S は gh に届かない)。ファイルへの書き込みは届くので、書き手の順を見るときは真にする。
        """
        d = self.cmds[j].depth
        for m in range(j + 1, k + 1):
            for op, dep in self.cmds[m].ops:
                if op in "()":
                    if not below_ok and op == ")" and dep < d:
                        return False
                    continue
                if allowed is not None and dep <= d and op not in allowed:
                    return False
        return below_ok or self.cmds[k].depth >= d

    def assigned(self):
        """変数名 → (値, 位置)。値が 1 つに決まらない名前は None。

        決まらないのは: 2 度代入された・`+=` で書き足された・read・printf -v・declare・local・mapfile・for・unset などで
        入れ直されうる(`B=x; read -r B < f` の B は f の中身)。
        """
        if self._assigned is None:
            table, spoiled = {}, set()
            for j, c in enumerate(self.cmds):
                spoiled.update(m.group(1) for m in (_APPEND_RE.match(a) for a in c.args) if m)
                if c.args and c.args[0] in ("eval", "source", "."):
                    spoiled.update(n for a in (cc.args for cc in self.cmds) for t in a for n in [t.split("=", 1)[0]])
                    spoiled.add("*")   # どの名前でも入れ直しうる
                if c.args and c.args[0] in REASSIGN_CMDS:
                    spoiled.update(a.split("=", 1)[0] for a in c.args[1:])
                args = c.args[1:] if c.args[:1] == ["export"] else c.args
                if args and not c.redirects and all(ENV_PREFIX_RE.match(a) for a in args):
                    for a in args:
                        name, value = a.split("=", 1)
                        if name in table:
                            spoiled.add(name)
                        table[name] = (value, j)
            self._assigned = {n: (None if n in spoiled or "*" in spoiled else v) for n, v in table.items()}
        return self._assigned

    def var(self, value):
        """$名前・${名前} を同じコマンドの中の代入で置き換えた値。解けなければ None。"""
        if "$" not in value:
            return value
        if self._sq is None:
            self._sq = single_quoted_dollar(self.norm)
        if self._sq:
            return None   # '$S' は字のまま。語の側では引用が落ちていて見分けられない
        table = self.assigned()
        failed = []

        def sub(m):
            entry = table.get(m.group(1) or m.group(2))
            if not entry or not self._flows(entry[1]) or "$" in entry[0] or "`" in entry[0]:
                failed.append(m.group(0))
                return ""
            return entry[0]

        out = _VAR_REF_RE.sub(sub, value)
        return None if failed or "$" in out else out

    def cwd_here(self, k=None):
        """k 番目(既定は gh)のコマンドが走る cwd。決まらなければ None。

        cwd を変える命令(cd・pushd・popd を語のどこかに持つもの。`if cd x`・`builtin cd x` も)が前に在れば、
        `cd <絶対パス>` が必ず走り、そこから k まで && だけで続く形でだけ、その先を cwd と見る。
        """
        k = self.k if k is None else k
        if self.moved:
            return None
        cwd = self.cwd
        for j in range(k):
            c = self.cmds[j]
            if not any(t in CD_WORDS for t in c.args):
                continue
            args = c.args[command_start(c.args):]
            dest = self.var(args[1]) if args[:1] == ["cd"] and len(args) == 2 else None
            dest = native_path(dest) if dest else None
            ok = (dest and os.path.isabs(dest) and not self.conditional and self._runs(j, ("&&",))
                  and self._between(j, k, ("&&",), below_ok=False))
            cwd = dest if ok else None
        return cwd

    def path(self, value, k=None):
        """本文ファイルの実パス(k 番目のコマンドの cwd で解く)。字のまま決まらなければ None。"""
        v = self.var(value)
        if v and v.startswith("~/") and "HOME" not in self.assigned() and os.environ.get("HOME"):
            # `~/` はシェルが HOME で開く。フックは Bash と同じ利用者・同じ HOME で起こされる(コマンドの中で HOME を
            # 入れ直していなければ)。`~user/` の形は開かない
            v = os.path.join(os.environ["HOME"], v[2:])
        if not v or v.startswith("~") or "__HEREDOC" in v or any(ch in v for ch in "*?["):
            return None
        v = native_path(v)
        if not v:
            return None
        if not os.path.isabs(v):
            cwd = self.cwd_here(k)
            if not cwd:
                return None
            v = os.path.join(cwd, v)
        return os.path.realpath(v)

    def _writes_first(self, j):
        """j 番目のコマンドが、gh が走るなら必ずその前に走り終えるか(ファイルへの書き込みの順だけを見る)。

        区切りは ; && 改行と、サブシェルの括弧(`URL=$(gh …)` の gh も cat の後に走る)まで許す。パイプ・& は同時に走り、
        `||`・条件・繰り返しの中は走らないことがある。`a && cat > f && gh` は && で gh まで続くときだけ。
        """
        if not (j < self.k) or self.conditional:
            return False
        if self._runs(j, ()):
            return self._between(j, self.k, _SEQUENTIAL, below_ok=True)
        return self._runs(j, ("&&",)) and self._between(j, self.k, ("&&",), below_ok=True)

    def writer(self, target):
        """同じコマンドの中で target を書く命令。無ければ None、`cat > f <<EOF` 1 本ならその本文、ほかは "writer"。"""
        base = os.path.basename(target)
        found = []
        for j, c in enumerate(self.cmds):
            if not self.looped and j > self.k and self._between(self.k, j, _SEQUENTIAL + ("||",), below_ok=True):
                continue   # gh が終わった後に走る命令(`gh … --body-file f && rm f` の後片付け)は gh の読む中身を変えない
            # gh 自身のリダイレクト(`gh … --body-file f > f`)も書き手に数える: シェルが gh より先に f を空にする
            for op, dest in c.redirects:
                if op not in WRITE_OPS:
                    continue
                d = self.var(dest)
                if d is None or os.path.basename(d) == base:
                    marks = [t for t in c.args[1:] if t.startswith("__HEREDOC")]
                    # ヒアドキュメントを本文と見るのは、その cat が必ず gh より先に走り(`[ -e f ] || cat > f` は走らないことがある)、
                    # 書く先が cat の cwd で解いて同じファイルのときだけ
                    heredoc = (c.args[:1] == ["cat"] and len(c.args) == 2 and len(marks) == 1 and op in (">", ">|")
                               and d is not None and self.path(dest, j) == target and self._writes_first(j))
                    found.append(int(marks[0][9:-2]) if heredoc else "writer")
            at = command_start(c.args)
            if j != self.k and at < len(c.args) and os.path.basename(c.args[at]) not in READ_ONLY_CMDS:
                for t in c.args[1:]:
                    tv = self.var(t) or t
                    if os.path.basename(tv.rstrip("/")) == base:
                        found.append("writer")
        if not found:
            return None
        if len(found) > 1 or found[0] == "writer":
            return "writer"
        return self.heredocs[found[0]]

    def read(self, value):
        """本文ファイルの中身 → (本文, None) か (None, 理由)。"""
        target = self.path(value)
        if target is None:
            return None, "path"
        w = self.writer(target)
        if w == "writer":
            return None, "writer"
        if isinstance(w, Expands):
            return None, "expand"
        if w is not None:
            return w, None
        return read_body_file(target)


def read_body_file(path):
    """通常のファイルを UTF-8 で読む → (本文, None) か (None, 理由)。理由は unreadable・notreg・large・utf8。

    開いてから fstat で確かめる(stat と open の間に差し替えられても FIFO を掴まない)。O_NONBLOCK で
    開くのは、FIFO が書き手を待ってフックを止めないため。大きさの食い違い(読む間の書き換え)も止める。
    """
    limit = MAX_LEN * 4   # UTF-8 の 1 字は 4 バイトまで
    flags = os.O_RDONLY
    for name in ("O_NONBLOCK", "O_NOCTTY", "O_BINARY"):
        flags |= getattr(os, name, 0)
    try:
        fd = os.open(path, flags)
    except OSError:
        return None, ("notreg" if os.path.isdir(path) else "unreadable")   # Windows はディレクトリを開けない
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode):
            return None, "notreg"
        if st.st_size > limit:
            return None, "large"
        chunks, got = [], 0
        while got <= limit:
            chunk = os.read(fd, limit + 1 - got)
            if not chunk:
                break
            chunks.append(chunk)
            got += len(chunk)
    except OSError:
        return None, "unreadable"
    finally:
        os.close(fd)
    data = b"".join(chunks)
    if len(data) != st.st_size:
        return None, "unreadable"
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return None, "utf8"
    return (text, None) if len(text) <= MAX_LEN else (None, "large")


class Analysis:
    """コマンド 1 本の解析の結果。calls は gh 呼び出しごとの (サブコマンド, 引数列, 本文候補, 止めた理由)。"""

    def __init__(self, parsed, candidates=(), blocked=(), calls=(), misses=()):
        self.parsed, self.candidates, self.blocked = parsed, list(candidates), list(blocked)
        self.calls, self.misses = list(calls), list(misses)

    def target_of(self, body=None):
        """log に残す投稿先と、画面を取る投稿先 (ラベル, dest)。body を運んだ呼び出し(無ければ止めた呼び出し)を見る。"""
        for sub, args, cands, blk in self.calls:
            if (body is not None and body in cands) or (body is None and (blk or cands)):
                dest = destination(args, sub) if sub else None
                return target_label(sub, dest), dest
        return "-", None


def _head_word(args):
    """misses.log に添える、単純コマンドの先頭の語(環境変数の前置は値を残さないので飛ばす)。"""
    for t in args:
        if not ENV_PREFIX_RE.match(t):
            return re.sub(r"\s", "_", os.path.basename(t))[:40] or "-"
    return "-"


def analyze(command, cwd=None):
    """コマンド文字列を解析する(Analysis)。解析できなければ parsed=False。"""
    norm, heredoc_bodies = prepare(command)
    tokens = tokenize(norm)
    if tokens is None:
        return Analysis(False)
    # 字句解析と同じ 1 本を見る。生の側を見ていると `--body "$\<改行>(cat x)"` が
    # 置換渡しと判定されず、実行時まで中身の無い文字列が本文候補として読み役へ回る
    live = has_live_substitution(norm)
    live_var = has_live_variable(norm)
    cmds = split_commands(tokens)
    files = BodyFiles(cmds, cwd, heredoc_bodies, norm, tokens)
    out = Analysis(True)
    for k, c in enumerate(cmds):
        args = gh_args(c.args)
        cands, blk, sub = [], [], None
        if args is not None:
            cands, blk = classify(args, heredoc_bodies, live, files.at(k, c.args[:len(c.args) - len(args) - 1]), live_var)
            sub = subcommand(args)
            out.calls.append((sub, args, cands, blk))
            out.candidates.extend(cands)
            out.blocked.extend(blk)
        # 素通しの理由が「投稿でない」なのか「網から落ちた」なのかを後から数える。本文旗の綴りが単純コマンドに
        # 在るのに、その単純コマンドが候補も止めた理由も出さなかったら、解析の取りこぼしの疑いがある。
        # 見るのはヒアドキュメントを印に置き換えた後の語(本文の中の綴りは数えない)。gh の語を含む単純コマンドに
        # 限り、当たった旗と先頭の語(sh・python3・echo …)を残す——誤検知(別の道具の旗・文書の中の綴り)を後から分ける
        if not cands and not blk and sub not in NON_POSTING:
            joined = " ".join(c.args)
            hit = BODY_FLAG_RE.search(joined)
            if hit and GH_WORD_RE.search(joined):
                out.misses.append((hit.group(0), _head_word(c.args)))
    return out


def posting_bodies(command, cwd=None):
    """コマンド文字列から (本文候補, 検査できない本文の説明, 解析成否) を返す。"""
    a = analyze(command, cwd)
    return a.candidates, a.blocked, a.parsed


# ---- 投稿先の画面 ------------------------------------------------------------
# 返信の読み手は文脈ゼロではない。スレッドへ付く返信は、題・番号・file と行・元の指摘・
# これまでの返信が同じ画面に見えている状態で読まれる。読み手にそれを渡さず本文だけで
# 読ませると、画面に有るもの(相手の名前・PR 番号・相手の印・相手の語)が全部詰まりに出る
# (経緯は冒頭の docstring)。そこで投稿先がスレッドなら gh で画面の中身を取って渡し、
# 新規作成(issue/PR/release/gist/discussion の create)は読み手が何も持たないので渡さない。
# 取れなかったときは文脈ゼロに倒して検査は走らせ、その旨を書き手に伝える。
# 画面の中身は他人の文章なので読み手への指示が混ざりうるが、読み手は道具を持たず(--tools "")、
# 出力は詰まりの有無にしか効かない。
# 読み手(sonnet)は入力が 3〜4 万字でも所要はほぼ変わらない。旧上限(全体 9,000・本文 800・
# 1 コメント 1,500)は #1429 の本文 10,150 字の 8%、相手の返信 4,698 字の 32% しか見せず、
# 画面モードでも文脈ゼロと同じ詰まりが出る形だった(2026-09-07 に実測)
SCREEN_MAX = 40000         # 画面全体の上限(字)。超えたら古いコメントから落とす(末尾=答える相手を残す)
SCREEN_BODY_MAX = 6000     # 1 コメントの上限。最後の 1 件(答える相手)は切らない
SCREEN_ITEM_BODY_MAX = 12000  # PR/issue 本文
SCREEN_HUNK_LINES = 25     # 指摘が付いた行は hunk の末尾なので末尾側を残す
SCREEN_COMMENTS = 30       # PR/issue の会話で見せる直近コメント数の上限
SCREEN_REFS = 8            # 本文とスレッドが参照する #番号 のうち、題を引く数(本文の分を先に)
SCREEN_FILES = 100         # 変更ファイル一覧の上限
SCREEN_BODY_KEEP = 1000    # 予算のために本文を切るとき、最低これだけは残す
SCREEN_CLIP_NOTE = 60      # clip が付ける「以下略」の行ぶんの余白
# gh api の path から投稿先の種別を読む。群 o/r が owner/repo、群 n が番号か ID。
# review コメントへの返信は REST の正式形が pulls/N/comments/ID/replies(PR 番号入り)で、
# 今日の投稿 16 件がこの形だった。PR 番号無しの形も記録に 5 件あるので両方受ける
_REPO = r"^repos/(?P<o>[^/]+)/(?P<r>[^/]+)/"
API_DEST_RES = (
    (re.compile(_REPO + r"pulls/\d+/comments/(?P<n>\d+)/replies$"), "review-reply"),
    (re.compile(_REPO + r"pulls/comments/(?P<n>\d+)/replies$"), "review-reply"),
    (re.compile(_REPO + r"pulls/comments/(?P<n>\d+)$"), "review-edit"),
    (re.compile(_REPO + r"pulls/(?P<n>\d+)/comments$"), "item"),
    (re.compile(_REPO + r"pulls/(?P<n>\d+)/reviews$"), "item"),
    (re.compile(_REPO + r"issues/(?P<n>\d+)/comments$"), "item"),
    (re.compile(_REPO + r"issues/comments/(?P<n>\d+)$"), "issue-comment-edit"),
    (re.compile(_REPO + r"(?:issues|pulls)/(?P<n>\d+)$"), "item"),
)
# 非 api 経路で、既に在る PR/issue へ本文を付けるサブコマンド(create は入れない)
PR_THREAD_SUBS = {("pr", "comment"), ("pr", "review"), ("pr", "close"), ("pr", "reopen"),
                  ("pr", "merge"), ("pr", "revert"), ("pr", "edit")}
ISSUE_THREAD_SUBS = {("issue", "comment"), ("issue", "close"), ("issue", "reopen"), ("issue", "edit")}


class BudgetExhausted(RuntimeError):
    """画面取得の時間予算を使い切った。参照番号の題引きはこれで止め、有る分の画面で読ませる。"""


class Screen:
    """1 回の画面取得。gh の呼び出しを合計の時間予算で縛る(超えたら例外→文脈ゼロへ倒す)。"""

    def __init__(self, cwd):
        self.cwd = cwd if cwd and os.path.isdir(cwd) else None
        self.deadline = time.time() + GH_BUDGET

    def gh(self, gh_argv):
        """gh を読み取りで呼び、stdout を返す。失敗は例外。"""
        left = self.deadline - time.time()
        if left <= 0:
            raise BudgetExhausted("画面取得の時間予算 %ds を使い切った" % GH_BUDGET)
        timeout = min(GH_TIMEOUT, left)
        override = os.environ.get("COLDREAD_GH_CMD")
        if override:
            proc = subprocess.run(["sh", "-c", override, "gh", *gh_argv],
                                  capture_output=True, encoding="utf-8", timeout=timeout)
        else:
            gh_bin = shutil.which("gh")
            if not gh_bin:
                raise RuntimeError("gh が PATH に無い")
            proc = subprocess.run([gh_bin, *gh_argv], capture_output=True, encoding="utf-8",
                                  timeout=timeout, cwd=self.cwd)
        if proc.returncode != 0:
            raise RuntimeError((proc.stderr or "gh failed").strip()[:150])
        return proc.stdout

    def json(self, gh_argv):
        return json.loads(self.gh(gh_argv))

    def pages(self, path):
        """一覧の endpoint を 100 件ずつ最大 GH_PAGES ページ辿る。100 件未満のページで止まる。"""
        out = []
        for page in range(1, GH_PAGES + 1):
            chunk = self.json(["api", "%s?per_page=100&page=%d" % (path, page)])
            out.extend(chunk)
            if len(chunk) < 100:
                break
        return out


def repo_flag(args):
    """-R/--repo の値。無ければ None(gh はカレントの git remote を使う)。"""
    for i, tok in enumerate(args):
        if tok in ("-R", "--repo") and i + 1 < len(args):
            return args[i + 1]
        for f in ("-R", "--repo"):
            if tok.startswith(f + "="):
                return tok[len(f) + 1:]
        if tok.startswith("-R") and tok != "-R":
            return tok[2:]
    return None


def positional_after(args, sub):
    """サブコマンド語より後ろの最初の位置引数(番号・URL・ブランチ)。無ければ None。

    旗の値は位置引数と見ない。「旗の直後の語は値」と読むので、値を取らない旗(--web 等)の直後に
    番号が来る形は取りこぼして None になる(gh が今のブランチの PR に解決するのと同じ倒れ方)。
    """
    i, seen, after_flag = 0, 0, False
    while i < len(args):
        tok = args[i]
        if tok in GLOBAL_VALUE_FLAGS:
            i += 2
            continue
        if any(tok.startswith(f + "=") or (not f.startswith("--") and tok.startswith(f))
               for f in GLOBAL_VALUE_FLAGS):
            i += 1
            continue
        if seen < len(sub):
            seen += 1
            i += 1
            continue
        if tok.startswith("-") and tok != "-":
            after_flag = "=" not in tok  # --旗=値 は値込みなので次の語は位置引数
        elif after_flag:
            after_flag = False  # 直前の旗の値
        elif not tok.startswith("__HEREDOC"):
            return tok
        i += 1
    return None


def destination(args, sub):
    """投稿先が既に在るスレッドなら (種別, owner/repo か None, 番号か ID か None)。新規作成等は None。"""
    if not sub:
        return None
    if sub[0] == "api":
        if len(sub) < 2:
            return None
        path = re.sub(r"^[a-z+]+://[^/]+", "", sub[1]).lstrip("/").split("?", 1)[0]
        for rx, kind in API_DEST_RES:
            m = rx.match(path)
            if m:
                return (kind, m.group(1) + "/" + m.group(2), m.group(3))
        return None
    if sub in PR_THREAD_SUBS:
        return ("pr", repo_flag(args), positional_after(args, sub))
    if sub in ISSUE_THREAD_SUBS:
        return ("issue", repo_flag(args), positional_after(args, sub))
    return None


def target_label(sub, dest):
    """log に残す投稿先の綴り。スレッドなら 種別:repo:番号、新規作成ならサブコマンド、不明なら -。"""
    if dest:
        kind, repo, ref = dest
        return "%s:%s:%s" % (kind, repo or "cwd", ref or "current")
    return ":".join(sub) if sub else "-"


def clip(text, limit):
    text = text or ""
    if len(text) <= limit:
        return text
    return text[:limit] + "\n…(以下略。全 %d 字)" % len(text)


def _login(obj):
    return ((obj.get("user") or obj.get("author") or {}).get("login")) or "?"


def _date(obj):
    return (obj.get("created_at") or obj.get("createdAt") or "")[:10]


REF_RE = re.compile(r"(?<![\w/])#(\d{1,7})\b")


def referenced_numbers(texts, own):
    """本文とスレッドが参照する #番号(自分の番号を除く。出た順で上限 SCREEN_REFS。本文の分を先に置く)。"""
    out = []
    for text in texts:
        for m in REF_RE.finditer(text or ""):
            n = m.group(1)
            if n != str(own) and n not in out:
                out.append(n)
                if len(out) == SCREEN_REFS:
                    return out
    return out


def item_state(obj):
    """画面に出す状態の綴り。REST(issues/pulls: state・draft・merged・pull_request.merged_at)と
    gh view(state=OPEN/MERGED/CLOSED・isDraft)の両方の形を読み、小文字に揃える。"""
    if obj.get("merged") or (obj.get("pull_request") or {}).get("merged_at"):
        return "merged"
    if obj.get("draft") or obj.get("isDraft"):
        return "draft"
    return str(obj.get("state") or "?").lower()


def files_lines(files):
    files = [f for f in files if f][:SCREEN_FILES]
    return ["[変更ファイル %d 件]" % len(files)] + files if files else []


def comment_label(label, t):
    return "[%s] %s(%s):" % (label, _login(t), _date(t))


def comment_blocks(label, ts):
    """コメントのブロック列(古い順)。最後の 1 件(答える相手)は切らない——書き手はそれに逐条で答えている。"""
    return [[comment_label(label, t), clip(t.get("body"), SCREEN_MAX if i == len(ts) - 1 else SCREEN_BODY_MAX)]
            for i, t in enumerate(ts)]


def referenced_lines(g, repo, nums):
    """参照されている番号の題と状態。1 件ずつ取り、取れない番号は飛ばす。予算切れなら有る分で止める。"""
    lines = []
    for n in nums:
        try:
            it = g.json(["api", "repos/%s/issues/%s" % (repo, n)])
        except (BudgetExhausted, subprocess.TimeoutExpired):
            break
        except Exception:
            continue
        lines.append("#%s「%s」(%s)" % (n, it.get("title", ""), item_state(it)))
    return ["[本文とスレッドが参照している番号]"] + lines if lines else []


def assemble(head, body, comments, tail):
    """画面を組む。head と body は必ず残す(body は PR/issue 本文か、review スレッドの元の指摘)。
    comments は古い順のブロックで、予算を超えたら古い方から落とす(末尾=最新=答える相手を残す)。
    それでも超えれば body を切り、最後に全体を切る。旧版は組んだ後に末尾を切っていて、本文を長く
    見せるほど最新の返信が落ちる形だった。"""
    dropped = 0

    def text():
        omitted = ["…(古いコメント %d 件は省略)" % dropped] if dropped else []
        return "\n".join(head + [body] + omitted + [line for c in comments for line in c] + tail)

    while len(text()) > SCREEN_MAX and len(comments) > 1:
        comments, dropped = comments[1:], dropped + 1
    over = len(text()) - SCREEN_MAX
    if over > 0 and len(body) - over >= SCREEN_BODY_KEEP:
        body = clip(body, len(body) - over - SCREEN_CLIP_NOTE)
    return clip(text(), SCREEN_MAX)


def screen_for(dest, cwd, body=""):
    """投稿先の画面に既に見えているものを、読み手に渡す文章にして返す。取れなければ例外。
    body は投稿する本文——その中の #番号 の題を引くために見る。"""
    kind, repo, ref = dest
    g = Screen(cwd)
    if kind in ("review-reply", "review-edit"):
        c = g.json(["api", "repos/%s/pulls/comments/%s" % (repo, ref)])
        root_id = c.get("in_reply_to_id") or c["id"]
        num = str(c["pull_request_url"]).rstrip("/").rsplit("/", 1)[-1]
        pr = g.json(["api", "repos/%s/pulls/%s" % (repo, num)])
        # 同じ根に連なるものだけ。一覧に根が無ければ(ページの外)、直接取った c を根として置く
        thread = [t for t in g.pages("repos/%s/pulls/%s/comments" % (repo, num))
                  if t.get("id") == root_id or t.get("in_reply_to_id") == root_id]
        if not any(t.get("id") == root_id for t in thread) and c["id"] == root_id:
            thread.insert(0, c)
        if kind == "review-edit":
            thread = [t for t in thread if t.get("id") != c["id"]]  # 直す当のコメントは新本文が置き換える
        thread.sort(key=lambda t: t.get("created_at", ""))
        head = ["PR #%s「%s」(%s、%s)の file %s の %s 行目に付いた指摘のスレッド"
                % (num, pr.get("title", ""), repo, item_state(pr), c.get("path"), c.get("line") or c.get("original_line"))]
        hunk = (c.get("diff_hunk") or "").splitlines()
        if hunk:
            head += ["[指摘が付いた差分の末尾]"] + hunk[-SCREEN_HUNK_LINES:]
        # 根(元の指摘)は body の位置に置いて落とさず、返信だけを予算で落とす対象にする
        root, replies = thread[:1], thread[1:]
        root_text = ""
        if root:
            head.append(comment_label("元の指摘", root[0]))
            root_text = clip(root[0].get("body"), SCREEN_BODY_MAX if replies else SCREEN_MAX)
        nums = referenced_numbers([body] + [t.get("body") for t in thread], num)
        return assemble(head, root_text, comment_blocks("これまでの返信", replies), referenced_lines(g, repo, nums))
    if kind in ("item", "issue-comment-edit"):
        skip = None
        if kind == "issue-comment-edit":
            c = g.json(["api", "repos/%s/issues/comments/%s" % (repo, ref)])
            ref, skip = str(c["issue_url"]).rstrip("/").rsplit("/", 1)[-1], c["id"]
        # PR も issues 経由で取れる(state・draft・pull_request.merged_at も載るので pulls/N は要らない)
        item = g.json(["api", "repos/%s/issues/%s" % (repo, ref)])
        comments = [t for t in g.pages("repos/%s/issues/%s/comments" % (repo, ref)) if t.get("id") != skip]
        is_pr, where = bool(item.get("pull_request")), repo
        files = ([f.get("filename") for f in
                  g.json(["api", "repos/%s/pulls/%s/files?per_page=%d" % (repo, ref, SCREEN_FILES)])]
                 if is_pr else [])
    else:  # 非 api の pr / issue。番号・URL・ブランチの解決は gh 自身に任せる
        argv = [kind, "view"] + ([ref] if ref else []) + (["-R", repo] if repo else [])
        fields = "number,title,body,comments,url,state" + (",isDraft,files" if kind == "pr" else "")
        item = g.json(argv + ["--json", fields])
        is_pr = kind == "pr"
        # repo が取れなければ None——題は「このリポジトリ」で出し、参照番号の題は引かない
        where = re.sub(r"^https?://[^/]+/", "", str(item.get("url") or "")).split("/pull/")[0].split("/issues/")[0] or None
        files = [f.get("path") for f in (item.get("files") or [])]
        comments = item.get("comments") or []
        ref = item.get("number")
    head = ["%s #%s「%s」(%s、%s)" % ("PR" if is_pr else "issue", ref, item.get("title", ""),
                                  where or "このリポジトリ", item_state(item))]
    head += files_lines(files) + ["[本文]"]
    nums = referenced_numbers([body, item.get("body")] + [t.get("body") for t in comments], ref)
    return assemble(head, clip(item.get("body"), SCREEN_ITEM_BODY_MAX),
                    comment_blocks("これまでのコメント", comments[-SCREEN_COMMENTS:]),
                    referenced_lines(g, where, nums) if where else [])


# ---- 読み役 ----------------------------------------------------------------
# 観点と報告の形式は 2 つの依頼文で共通。違うのは読み手の立ち位置(文脈ゼロ/画面を見ている)と、
# 画面モードにだけ在る「冗長」欄——画面に有るものを本文で説明した箇所を、止めずに書き手へ返す。
# 文脈ゼロの依頼文には冗長を置かない(画面が無いので、冗長かどうかを読み手が決められない)。
_FORMAT_COMMON = """- (1)〜(4) に該当し、その箇所で意味が取れず次の文へ読み進められなかったもの → 1 行 1 件、行頭に「詰まり: 」。
  意味は取れたが根拠・出所・数字の出どころ・答えが欲しい、というものは詰まりではなく疑問。迷ったら疑問にする
- (5) のうち、理解はできたが答えが本文に無い疑問 → 1 行 1 件、行頭に「疑問: 」
- (4) のうち、推測で埋めて読み進められた箇所 → 1 行 1 件、行頭に「補完: 」。
  「何をどう埋めたか」を書く(例:「補完: 障害は今起きていると読んだ」)。
  推測で埋めたなら、理解を妨げていなくても書く——書き手はここで初めて自分の誤読を知る
"""
_RULES = """規則: 点数・総評・文体の好み・軽微な言い換え提案は書かない。読めば分かることへの確認は書かない。該当の無い欄は「詰まり: なし」のように書かず、行ごと省く。日本語で。

--- 本文 ---
"""
COLD_PROMPT = """あなたはこの文章について何も知らない初見の読者です。会話の経緯もリポジトリも見ていません。
以下の「本文」だけを読み、理解を実際に妨げた事実だけを報告してください。

見る観点:
(1) この文章があなたに求めていること(読んで何をすべきか)が言えるか
(2) 冒頭 3 行で「何の話か・自分に関係あるか・急ぐか」が掴めるか
(3) 本文の中だけでは意味を解決できない略語・識別子・参照は無いか
(4) 意味を推測で埋めた箇所と、埋めた推測の中身(特に時制・主体・範囲)
(5) 読み終えて残った疑問は何か

報告の形式(この 4 種類だけ。問題の無かった観点は一切書かない):
""" + _FORMAT_COMMON + """- 詰まりも疑問も補完も 1 件も無いときだけ、他に何も書かず CLEAN とだけ出力
  (1 件でもあるなら CLEAN とは書かない)
""" + _RULES
# 読み手が画面で見ているものの列挙。依頼文(既知の範囲)と deny の直し方(説明しないもの)の両方がこれを使う
SCREEN_ITEMS = ("PR/issue の題と番号と状態・リポジトリ・相手の名前・元の指摘の文言と印・file と行・"
                "変更ファイルの一覧・これまでの返信の中身・参照されている番号の題")
SCREEN_PROMPT = """あなたはこの返信を受け取る側の人(スレッドの参加者)です。手元の画面には次のものが既に表示されていて、新しい返信はその下に付きます。

--- 画面に既に見えているもの ---
%s
--- 画面ここまで ---

以下の「本文」(新しい返信)を読み、理解を実際に妨げた事実だけを報告してください。

前提:
- 画面に見えているもの(""" + SCREEN_ITEMS + """)は「何を指しているか分かっている」ものとして読む。それらが本文で説明されていなくても詰まりにしない
- 画面は語彙の辞書ではない。相手の言い回し・業界の外では通じない横文字・比喩(例: 北極星・ニアバイ・クロージング)を、本文が自分の地の文として使っている箇所は「なぞり: 」として報告する——画面に同じ語が有っても、画面を持たずにこのスレッドを後から読む人には解けない。定着した技術用語・製品名・file 名・相手が付けた印は含めない。相手の語を引用して指す(「reviewer_x さんの言う『ニアバイ』は」「[block] の 2 件目は」)のはなぞりではない
- 本文が、画面に見えているものを改めて説明している箇所(誰宛か・何番の PR か・PR が何をするものか・相手の印や語の意味・相手が何を書いたか)は「冗長: 」として報告する(読み手は既に見ている)

見る観点:
(1) この返信があなたに求めていること(何を確認し・何を返せばよいか)が言えるか
(2) 冒頭 3 行で「何をどう直したか・自分は何をすればよいか」が掴めるか
(3) 画面と本文を合わせても意味を解決できない略語・識別子・参照は無いか
(4) 意味を推測で埋めた箇所と、埋めた推測の中身(特に時制・主体・範囲)
(5) 読み終えて残った疑問は何か

報告の形式(この 6 種類だけ。問題の無かった観点は一切書かない):
""" + _FORMAT_COMMON + """- 画面に有るものを本文で説明している箇所 → 1 行 1 件、行頭に「冗長: 」
- 相手の言い回しを本文が地の文に写している箇所 → 1 行 1 件、行頭に「なぞり: 」(その語と、どの発言の語か)
- 詰まりも疑問も補完も冗長もなぞりも 1 件も無いときだけ、他に何も書かず CLEAN とだけ出力
  (1 件でもあるなら CLEAN とは書かない)
""" + _RULES


def reader_prompt(screen):
    """読み手に渡す依頼文(本文の手前まで)。画面が有れば画面モード、無ければ文脈ゼロ。"""
    return SCREEN_PROMPT % screen if screen else COLD_PROMPT


# 読み役のラベルと、投稿を止めるかどうか。依頼文が指示する綴りと 1 対 1 なので隣に置く——
# 欄を増やすときに、指示と仕分けと止める/止めないが同じ画面で目に入る形にしておく。
# 「なぞり」(相手の言い回しを地の文に写した箇所)は画面モードにだけ在り、詰まりと同じく投稿を止める——
# 画面が既知にするのは指す先であって語彙ではない。詰まりの条件文の中に「相手の語で書けば詰まり」と
# 埋めた形は、実物の読み手(sonnet)に 1 件も拾われなかった(2026-09-07 に実測: 北極星・ニアバイ・
# クロージングを地の文に写した返信が詰まり 0 件)。独立の欄として問う
LABELS = {"詰まり": True, "なぞり": True, "疑問": False, "補完": False, "冗長": False}
LABEL_RE = re.compile("(%s)\\s*[:：]" % "|".join(LABELS))
# ラベルの後ろが「無い」の意味だけの行は、その欄の 0 件であって 1 件ではない。依頼文で「行ごと省け」と
# 言っても読み手は書く(2026-09-06 に実測: 画面モードの読み手が「詰まり: なし」と書き、837 字の
# 返信が詰まり 1 件として止まった)。ここで落とさないと、無い欄が投稿を止める
NONE_RE = re.compile(r"^(?:なし|無し|ない|無い|特になし|特に無し|該当なし|該当無し|ありません|0\s*件|ゼロ|none)"
                     r"\s*(?:[（(][^）)]*[）)])?\s*[。．.]?\s*$", re.I)


def report_shaped(out):
    """読み役の出力が報告の形(CLEAN かラベル行)をしているか。していなければ検査できていない(認証切れはこの形で出る)。"""
    return "CLEAN" in out or any(LABEL_RE.match(line.strip()) for line in out.splitlines())


def sort_findings(out):
    """読み役の出力をラベルごとの行に仕分ける。

    ラベルはコロンまで見る。行頭の語だけで拾うと「詰まりは無い」のような地の文が
    詰まりに数えられ、指摘ゼロの本文が deny になる(補完の追加で自由文の行が増えたため)。
    """
    found = {label: [] for label in LABELS}
    for line in out.splitlines():
        line = line.strip()
        m = LABEL_RE.match(line)
        if m and not NONE_RE.match(line[m.end():].strip()):
            found[m.group(1)].append(line)
    return found


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
            "permissionDecisionReason": "\n".join(filter(None, (reason, VERSION_NOTE))),
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


def deny_streak(session, target, fp=None):
    """同じ書き手(session)の同じ投稿が直近に続けて止められた (回数, その間の本文の長さの列, 止めた種別の列)。列は古い順。

    log は profile で共有なので、他の session の行は無いものとして飛ばす——数えると並行セッションの
    deny が自分の連続数を増やし、他所の skip が自分の案内を消す(2026-09-07 に実測)。同じ書き手でも
    別の投稿先の deny は数えない(長さの列が別の本文の混ざりになる)が、allow は投稿先に関わらず
    連続を切る。同じ投稿先でも、本文の指紋(fp)が似ていない deny に当たったら、そこで別の投稿と見て切る。
    session の無い入力は、同じく session の無い行だけを数える。
    """
    try:
        with open(DENY_LOG, encoding="utf-8") as f:
            lines = f.readlines()[-400:]
    except OSError:
        return 0, [], []
    n, lens, kinds = 0, [], []
    now = time.time()
    for line in reversed(lines):
        parts = line.rstrip("\n").split("\t")
        if len(parts) < 2:
            break
        try:
            ts = time.mktime(time.strptime(parts[0], "%Y-%m-%d %H:%M:%S"))
        except ValueError:
            break
        if now - ts > DENY_STREAK_WINDOW:
            break
        cols = dict(p.split("=", 1) for p in parts[2:] if "=" in p)
        if cols.get("sid", "") != session:
            continue
        if parts[1] != "deny":
            break
        if cols.get("to", "-") != target:
            continue
        if fp and not cols.get("fp"):
            continue   # 本文を取り出せなかった deny は、本文の在る投稿の連続に数えない(別の投稿かもしれない)
        if not same_post(fp, cols.get("fp")):
            break
        n += 1
        kinds.append(parts[2] if len(parts) > 2 else "-")
        if len(parts) >= 4 and parts[3].isdigit():
            lens.append(int(parts[3]))  # 逆順に辿っているので後で戻す
    lens.reverse()
    kinds.reverse()
    return n, lens, kinds


PLUGIN_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def plugin_version():
    try:
        with open(os.path.join(PLUGIN_DIR, ".claude-plugin", "plugin.json"), encoding="utf-8") as f:
            return str(json.load(f).get("version") or "?")
    except (OSError, ValueError):
        return "?"


GATE_VERSION = plugin_version()


def version_tuple(name):
    return tuple(int(x) for x in name.split(".")) if re.fullmatch(r"\d+(?:\.\d+)*", name) else None


def newer_installed():
    """cache の兄弟(…/gates/<版>/)に自分より新しい版が在ればその版名。無ければ None。

    ${CLAUDE_PLUGIN_ROOT} はセッション開始時に固定されるので、更新の後も開いたままのセッションは
    古い版で検査し続ける(2026-09-07 に実測: 16 時間 0.8.0 のまま)。開発 checkout(兄弟が版名でない)では
    None。半端に入った版を拾わないよう、フック本体が在るものだけを見る。
    """
    my = version_tuple(GATE_VERSION)
    if my is None:
        return None
    parent = os.path.dirname(PLUGIN_DIR)
    try:
        names = os.listdir(parent)
    except OSError:
        return None
    hook = os.path.join("hooks", os.path.basename(__file__))
    found = [(v, n) for n in names for v in [version_tuple(n)]
             if v and v > my and os.path.isfile(os.path.join(parent, n, hook))]
    return max(found)[1] if found else None


_NEWER = newer_installed()
VERSION_NOTE = ("この検査は gates %s で走った(手元の cache には %s が在る。フックの版はセッション開始時に"
                "固定されるので、新しいセッションから反映される)" % (GATE_VERSION, _NEWER)) if _NEWER else ""


def reader_argv(claude_bin, model=None, effort=None):
    """読み役(headless claude)の起動引数。テストから読めるように関数にしてある。

    **本文は argv に載せない**(依頼文+本文は stdin で渡す)。載せていた頃は 2 つ問題が在った:
    Windows のコマンドラインは 32,767 字が上限で、画面つきの依頼文(本文だけで最大 SCREEN_MAX 字)
    が超えると起動そのものが落ち、ゲートは「読み役の起動に失敗」で投稿を全部止める(理由は面を
    教えない)。もう 1 つは、差し替えの枝(COLDREAD_READER_CMD。CI が唯一叩く枝)だけが stdin で
    渡していたので、テストが実運用の渡し方を覆っていなかった。
    stdin で足りることは実測済み: 2026-09-16 にこの環境(macOS・claude 2.1.273)で、同じ旗と
    claude_auth の認証のまま `-p` を引数なしで起こし、stdin の依頼に返答が返った。大きさの先例は
    graphloops の graph(774,021 バイトを stdin で通した実測。docs/loop-contract.md の T 節)。
    """
    return [claude_bin, "-p",
            "--model", model or os.environ.get("COLDREAD_MODEL", "sonnet"),
            "--effort", effort or os.environ.get("COLDREAD_EFFORT", "medium"),
            # 読み役は本文を読んで報告するだけで道具は要らない。検査対象の文章そのものを
            # 渡すので、本文に紛れた指示で読み役が動く経路をここで断つ("" で全道具を無効化)。
            "--tools", "",
            # 利用者の CLAUDE.md(と settings)を読ませない。cwd を state 側にしてもユーザー階層の
            # CLAUDE.md は載る——2026-09-06 に実測: この引数無しだと利用者の CLAUDE.md の見出しを
            # そのまま引用し、有りだと NONE。書き手向けの「初見でも分かるように書く」等の規則を
            # 読み手が自分の指示として持つと、識別子を全部詰まりに出す側へ寄る
            "--setting-sources", ""]


def _child_text(raw, strict=True):
    r"""子の出力を UTF-8 で読み、改行を \n に揃える。

    復号を strict に保つのは、errors="replace" だと壊れた読み役出力で「詰まり」の行頭一致が
    崩れ、deny が無音 allow に化けるから——読めない出力は例外→deny(検査できないものは通さない)。
    診断のためだけに読む標準エラーは strict=False で読む(そちらで落とすと、読める本文の
    判定まで一緒に失う)。
    """
    return (raw or b"").decode("utf-8", "strict" if strict else "replace").replace("\r\n", "\n")


def run_reader(prompt: str, model=None, effort=None):
    """読み役を起動して出力文字列を返す。prompt は依頼文+本文。model と effort は既定(投稿の読み役)を替えるときだけ渡す。失敗は例外。"""
    override = os.environ.get("COLDREAD_READER_CMD")
    note = None  # 採った認証の段。差し替えの枝では認証に触らないので None のまま
    if override:
        # POSIX シェル文字列として sh -c で実行する。shell=True だと Windows では
        # cmd.exe に渡ってしまい、/dev/null 等が解決できない(GitHub Actions windows-latest で実測)。
        # **本文は bytes で渡す**(下の実運用の枝も同じ)。encoding= を付けて str を渡すと、text mode の
        # 改行変換が働いて本文の \n が Windows で \r\n に化け、「書かれたとおり」読み役へ渡らない
        # (subprocess には newline を指定する口が無い。実測 2026-09-16: windows-latest だけで、
        # 単一引用の中の改行を保つ 1 件が赤かった——読み役には行末に \r が付いた本文が届いていた)。
        proc = subprocess.run(
            ["sh", "-c", override], input=prompt.encode("utf-8"),
            capture_output=True, timeout=READER_TIMEOUT,
        )
    else:
        # 認証(段の中身と理由は claude_auth の冒頭)。トークンはディスクにもログにも書かない。
        # 取れなくても claude 自身の保存済み認証で動く場合があるため、足せなくても進む。
        env, note = claude_auth.auth_env(
            os.environ, service=os.environ.get("COLDREAD_KEYCHAIN_SERVICE"))
        env["COLDREAD_IN_READER"] = "1"
        claude_bin = shutil.which("claude") or os.path.expanduser("~/.local/bin/claude")
        os.makedirs(STATE_DIR, exist_ok=True)
        proc = subprocess.run(
            reader_argv(claude_bin, model, effort), input=prompt.encode("utf-8"),
            capture_output=True, timeout=READER_TIMEOUT,
            cwd=STATE_DIR, env=env,  # cwd を state 側にしてプロジェクト設定を子に読ませない
        )
    out = _child_text(proc.stdout).strip()
    if proc.returncode != 0 or not out:
        why = (_child_text(proc.stderr, strict=False) or "empty output")[:200]
        raise RuntimeError(why if note is None else "%s(認証: %s)" % (why, note))
    return out


SKIP_TOKEN = "COLDREAD_SKIP=1"
# 生の文字列の先頭に置かれた逃げ道。解析できないコマンドでも読めるので先に見る。
SKIP_PREFIX_RE = re.compile(r"\s*(?:[A-Za-z_][A-Za-z0-9_]*=\S*\s+)*" + SKIP_TOKEN + r"(?=\s|$)")


def wants_skip(command):
    """逃げ道(COLDREAD_SKIP=1)が書き手の前置として置かれているか。本文に文字列が入っているだけでは数えない。

    **逃げ道はもう効かない**(持ち主の判断 2026-10-16: エージェントに使わせない)。これは、書いた事実を
    記録に残し、止めた理由に「効かない」と添えるためだけに読む。前は逃げ道が 22 回、本文ファイルの書き直しを
    避けて未検査のまま出す口になっていた。持ち主が自分で出すときは、Claude Code の ! か自分の端末で打つ。
    """
    if SKIP_PREFIX_RE.match(command):
        return True
    tokens = tokenize(prepare(command)[0])
    if tokens is None:
        return False
    # 読み飛ばす範囲は gh_args と同じ command_start(予約語は simple_commands が先に落とす)。
    # 前置が途切れたら、そこから先は引数か本文
    return any(SKIP_TOKEN in cmd[:command_start(cmd)] for cmd in simple_commands(tokens))


# 止めたときに書き手が取れる手。逃げ道を案内しない——自分で検査を外せる口は、往復を避けて未検査のまま出す口になった
OWNER_NOTE = (
    "直せない・検査できないと判断したら、書き直しを重ねず、本文の場所と止めた理由を持ち主に渡して止まる"
    "(出すかどうかは持ち主が決め、出すなら持ち主が Claude Code の ! か自分の端末で打つ)。"
)
SKIP_REFUSED_NOTE = "COLDREAD_SKIP=1 はもう効かない(付けても検査は外れない)。"
# 通過・差し戻しのどちらでも保証範囲を言う。無言で通すと、摩擦を越えた事実が
# 「審査に合格した」と読まれ、権限・名義の検査の代わりにされる(実例あり)。
SCOPE_NOTE = (
    "この検査が見るのは通じやすさのみ——出してよい投稿か・名義・宛先は検査していない"
    "(宛先の許可制は同梱の destgate)。"
)

# 往復の上限。同じ書き手・同じ宛先・似た本文の投稿がこの回数だけ続けて止められたら、それ以上書き直させず、
# 持ち主に渡して止まらせる。3 にしたのは、denies.log(2026-09〜10 の 4 profile)の連続の分布から:
# 1 回止まった後の次で通ったのは 301 本中 178 本、2 回止まった後の次で通ったのは 94 本中 49 本、
# 3 回止まった後の次で通ったのは 33 本中 2 本だった(3 回目からは前の案内が逃げ道を勧めていたので、通る率は
# 低めに出ている)。上限で止まるのは、関所か書き方のどちらかがおかしい合図なので、stuck.log に残して後で直す。
STREAK_CAP = 3
FP_SIZE = 16       # 本文の指紋(MinHash)の数。log に本文を写さずに「同じ投稿の書き直しか」を比べるため
FP_SAME = 3        # 指紋が 16 個中これ以上一致すれば同じ投稿の書き直しと見る(推定の Jaccard ≥ 0.19)
_FP_SALTS = [int(hashlib.sha256(b"coldread-fp-%d" % i).hexdigest()[:16], 16) for i in range(FP_SIZE)]
_MASK64 = (1 << 64) - 1


def fingerprint(text):
    """本文の指紋(5 字の断片の MinHash を 16 個、16 進 64 字)。本文を復元できない形で、書き直しの近さだけを比べる。"""
    t = re.sub(r"\s+", " ", text.strip())
    shingles = {t[i:i + 5] for i in range(max(1, len(t) - 4))}
    hs = [int.from_bytes(hashlib.blake2b(s.encode("utf-8"), digest_size=8).digest(), "big") for s in shingles]
    mins = (min((((h ^ salt) * 0x9E3779B97F4A7C15) & _MASK64) for h in hs) >> 48 for salt in _FP_SALTS)
    return "".join("%04x" % m for m in mins)


def same_post(fp_a, fp_b):
    if not fp_a or not fp_b or len(fp_a) != len(fp_b):
        return True   # 指紋の無い行(本文を取り出せなかった deny)は、宛先だけで同じ投稿と見る
    return sum(fp_a[i:i + 4] == fp_b[i:i + 4] for i in range(0, len(fp_a), 4)) >= FP_SAME


def main() -> None:
    try:
        payload = json.load(sys.stdin)
        command = payload.get("tool_input", {}).get("command", "") or ""
    except Exception:
        allow()

    # 手元の文書の門番: Bash が書いた文書を後で拾うために、走る前の文書の状態を控える(投稿の判定とは独立。
    # 失敗しても投稿の門番を落とさない)
    try:
        docs_snapshot(payload)
    except Exception:
        pass

    # log の各行に書き手(session)・版・投稿先を残す。連続 deny は session ごとに数える
    sid = str(payload.get("session_id") or "")[:8]
    cwd = payload.get("cwd") or None
    target = "-"  # 投稿先が分かった時点で付け替える(record は呼んだ時の束縛を読む)

    def record(text, extra=""):
        log_line(DENY_LOG, "%s\tsid=%s\tv=%s\tto=%s%s" % (text, sid, GATE_VERSION, target, extra))

    # 読み役の中で自分がもう一度発火すると、読み役が読み役を起こす入れ子になる
    # (深さぶんの待ち時間になり、外側はフックのタイムアウトで無検査のまま通る)。
    # 読み役の道具を殺す --tools "" とは別の機構にしてある——あちらは「読み役が本文中の
    # 指示で動かない」ための処置で、起動の仕方(差し替えの読み役)に依存する。こちらは
    # 起動の仕方に関わらず入れ子を止める。allow に落ちる以上、記録を残す。
    if os.environ.get("COLDREAD_IN_READER") == "1":
        log_line(SKIP_LOG, "in-reader: " + command[:150].replace("\n", " "))
        allow()

    # 長さで解析を飛ばさない。前は 400 字未満のコマンドを解析の前に記録も残さず通していて、本文ファイル・
    # 変数を運ぶ短い投稿(直近 14 日で 54 件)が読まれずに出た。短い定型の返信を読み役に回さないのは、
    # 取り出した本文の長さ(200 字未満は通す)で決める。
    if not GH_WORD_RE.search(command):
        allow()

    skip_note = ""
    if wants_skip(command):
        log_line(SKIP_LOG, "refused\t" + command[:200].replace("\n", " "))
        skip_note = SKIP_REFUSED_NOTE

    def stop(kind, message, length=None, fp=None):
        """deny して終わる。同じ投稿が上限の回数だけ続けて止められたら、書き直させずに持ち主に渡させる。"""
        n, lens, kinds = deny_streak(sid, target, fp)
        n, kinds = n + 1, kinds + [kind.split("\t", 1)[0]]
        if length is not None:
            lens.append(length)
        record("deny\t" + kind, "\tfp=%s" % fp if fp else "")
        if n >= STREAK_CAP:
            label_kind = target.split(":", 1)[0] if target.count(":") >= 2 else target
            log_line(STUCK_LOG, "sid=%s\tv=%s\tkind=%s\tn=%d\twhy=%s\tlens=%s" % (
                sid, GATE_VERSION, label_kind, n, ",".join(kinds), ",".join(map(str, lens)) or "-"))
            grown = ("。本文は %s 字と書き直された" % " → ".join("{:,}".format(x) for x in lens)
                     if len(lens) >= 2 and lens[-1] != lens[0] else "")
            message = (
                "【上限に当たった: 同じ投稿が %d 回続けて止められた%s】これ以上書き直さず、持ち主に渡して止まれ"
                "(この投稿の宛先・本文の場所と下の理由を渡す)。出すかどうかは持ち主が決め、出すなら持ち主が "
                "Claude Code の ! か自分の端末で打つ。上限で止まるのは、関所か書き方のどちらかがおかしい合図で、"
                "記録(coldread-gate/stuck.log)に残した。\n\n" % (n, grown)
            ) + message
        deny("\n".join(filter(None, (message, skip_note))))

    # 解析の失敗は例外の形でも起こりうる(壊れた JSON の再帰・想定外の入力)。
    # 「引用が閉じない」を deny にしているのに例外だけ素通りでは、検査を避ける口になる。
    # 捕まえるのは Exception 全体で、ValueError に狭めるな——狭めた瞬間に、それ以外の例外は
    # フックのクラッシュ(=PreToolUse は続行)になって無検査で通る。
    if len(command) > MAX_LEN:
        stop("maxlen",
             "外部投稿ゲート: このコマンドは長すぎて解析しない(%d 文字 > 上限 %d)。\n" % (len(command), MAX_LEN)
             + "本文を短くして再実行すること"
             "(上限を変えるにはフックを起動する側の環境変数 COLDREAD_MAX_LEN を設定する——"
             "コマンド先頭に書いてもフック自身には届かない)。\n" + OWNER_NOTE)

    try:
        analysis = analyze(command, cwd)
    except Exception as exc:
        analysis = Analysis(False)
        parse_error = str(exc)[:150]
    else:
        parse_error = "引用が閉じていない等"
    if not analysis.parsed:
        stop("parse-fail",
             "外部投稿ゲート: このコマンドは解析できない(%s)。" % parse_error
             + "gh を含むため、投稿かどうか確かめられないものは通せない。\n"
             "引用を直して再実行すること。\n" + OWNER_NOTE)

    # 素通しの疑いは判定より前に残す(止める枝・通す枝のどちらに進んでも数える)。残すのは当たった旗の綴りと
    # 先頭の語だけで、コマンドの抜粋は残さない——`gh secret set --body <値>` のような値は秘密そのもので、
    # 抜粋にすると平文で溜まる。狙いは押し出しの量を測ることなので綴りで足りる。
    for flag, head in analysis.misses:
        log_line(MISS_LOG, "%s\t%s" % (flag, head))

    # 「検査できない本文がある」は、別の本文が読めたかどうかと独立に止める。
    # ここを bodies の有無に従属させると、読める本文と同居した投稿が無検査で通る。
    if analysis.blocked:
        target = analysis.target_of()[0]
        stop("blocked\twhy=%s" % "・".join(sorted(set(analysis.blocked))),
             "外部投稿ゲート: この投稿は本文を取り出せない形をしている(%s)。検査できないものは通せない。\n"
             "本文はヒアドキュメント(<<'EOF' ... EOF)・本文旗(--body / --notes 等)・本文ファイル(--body-file "
             "<絶対パス> 等。同じコマンドの中で書き換えない)のどれかで渡して再実行すること。\n"
             % "・".join(sorted(set(analysis.blocked))) + OWNER_NOTE)

    bodies = [b for b in analysis.candidates if len(b.strip()) >= 200]
    if not bodies:
        allow()
    # 複数の本文が同居するときは最長を代表として読ませる(全部読ませると読み役の回数と
    # 待ち時間が本文の数だけ増える)。取りこぼしの受容は gates/README.md「網の射程」。
    body = max(bodies, key=len)
    fp = fingerprint(body)

    # 投稿先がスレッドなら、読み手が画面で既に見ているものを取って渡す。取れなければ
    # 文脈ゼロに倒す——検査は走らせ、画面に有るものへの詰まりは無視してよいと書き手に伝える
    # 投稿先の解釈で例外が出ても門番を落とさない(落ちるとフックのクラッシュ=無検査で通る)。
    # 解釈できないときは文脈ゼロ側(厳しい側)へ倒れる
    try:
        target, dest = analysis.target_of(body)
    except Exception:
        target, dest = "-", None

    # 上限に当たった後の書き直しは、読み役を起こさずに止める(書き直しを重ねさせない)
    if deny_streak(sid, target, fp)[0] >= STREAK_CAP:
        stop("cap\t%d" % len(body), "外部投稿ゲート: この投稿は既に往復の上限に当たっている。", len(body), fp)

    screen, screen_error = None, None
    if dest is not None:
        try:
            screen = screen_for(dest, cwd or "", body)
        except Exception as exc:
            screen_error = str(exc)[:120]
    mode = "screen" if screen else "cold"
    screen_note = (
        "投稿先はスレッドだが、画面の中身(題・元の指摘・これまでの返信)を gh で取れなかった(%s)ので"
        "文脈ゼロで読んだ。画面に有るもの(PR/issue 番号・相手の名前・元の指摘)への詰まりは無視してよい。"
        % screen_error if dest is not None and screen is None else ""
    )

    try:
        out = run_reader(reader_prompt(screen) + body)
    except Exception as exc:
        # 読み役を起こせないときも止める。逃げ道は無いので、直らなければ持ち主に渡す(上限でも止まる)
        stop("reader-down\t%d" % len(body),
             "外部投稿ゲート: coldreader(文脈ゼロの読み手)の起動に失敗した(%s)。\n" % str(exc)[:150]
             + "検査できていないので止めた。手で検査するなら skill『coldread』の手順で coldreader を立てること。\n"
             + OWNER_NOTE, len(body), fp)

    # **報告の形をしていない出力を「詰まりゼロ」と読まない。** 認証落ちは例外にならない——
    # 実測 2026-09-15: 素で起こした claude は『Failed to authenticate: OAuth session expired and
    # could not be refreshed』の 1 行を**標準出力に・終了コード 0 で**返した。rc も空出力も踏まないので
    # ここまで素通りし、ラベルが 1 つも無いまま allow に落ちていた(＝検査せずに投稿が出る fail-open)。
    # 依頼文が許す出力は CLEAN かラベル行の 2 種類だけなので、どちらでもなければ「検査できない」として止める。
    if not report_shaped(out):
        stop("reader-shape\t%d" % len(body),
             "外部投稿ゲート: coldreader の出力が報告の形(CLEAN かラベル行)をしていない: %r\n" % out[:150]
             + "検査できていないので止める(認証切れはこの形で出る——読み役の標準エラーを見よ)。\n"
             + OWNER_NOTE, len(body), fp)

    found = sort_findings(out)
    blocking, questions, fills, redundant, traced = (
        found["詰まり"], found["疑問"], found["補完"], found["冗長"], found["なぞり"])

    # 詰まりとなぞりの有無だけで決める。以前は「最終行が CLEAN なら」も allow の条件だったが、
    # それだと詰まりを列挙した後に CLEAN と書かれた出力が通ってしまう。読み役に本文の
    # 説明以外を書かせる欄(補完)を足したぶん、末尾が CLEAN で終わる形は出やすくなっている。
    if not any(found[label] for label, stops in LABELS.items() if stops):
        record("allow\t%d\t%s" % (len(body), mode))
        extra = "\n".join(filter(None, (
            SCOPE_NOTE,
            skip_note,
            screen_note,
            VERSION_NOTE,
            section("coldreader が推測で埋めた箇所——意図と違うなら投稿を編集して直すこと:", fills),
            section("画面に有るものを本文で説明している箇所(削ってよい。投稿を編集して短くできる):", redundant),
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

    role = ("この返信を受け取る相手として、スレッドの画面と本文を読んだ別プロセスの読み手"
            if mode == "screen" else "文脈ゼロの別プロセスの読み手")
    head = (
        "外部投稿ゲート: coldreader(%s)がこの本文で詰まった。詰まりを直してから"
        "同じ形で再実行すること(再実行時は直した本文を新しい coldreader が検査する。同じ投稿が %d 回続けて"
        "止まったら、それ以上は書き直させずに持ち主に渡させる):" % (role, STREAK_CAP)
    )
    # 見出しで分ける。混ぜて並べると、直さなくてよい補完・疑問が過半を占めたまま
    # 「以下を直せ」と読め、直す量を過大に見せて逃げ道を引く方向に働く(実測で 8.9 行中 4.7 行)。
    detail = "\n\n".join(filter(None, (
        section("投稿を止めている詰まり(直せば通る):", blocking),
        section("投稿を止めている、相手の言い回しを地の文に写した箇所(自分の言葉に直せば通る。説明を足すのではない):", traced),
        section("止めてはいないが coldreader が推測で埋めた箇所(意図と違うなら直す):", fills),
        section("画面に有るものを本文で説明している箇所(削ってよい):", redundant),
        section("残った疑問(反映するかは判断してよい):", questions),
    )))
    # 直し方は読み方で変える。画面モードで「同型を掃討」と言うと、画面に有るものの説明を
    # 本文全体に足す向きに働く(PR 1583 で実測: 宛先本人に本人の名前の説明が付いた)
    howto = (
        "直し方: 足すより削る。読み手は " + SCREEN_ITEMS + " を画面で見ているので、それらを本文で"
        "説明しない(説明は「冗長」として返る)。詰まりは画面と本文を合わせても解けないものだけなので、"
        "その語の初出 1 か所に中身を添える。相手の語は指してよいが、相手の語で書かない(相手の言い回しを"
        "地の文に写した箇所は、画面に同じ語が有っても「なぞり」として止まる。直し方は自分の言葉に置き換える)。"
        if mode == "screen" else
        "直し方: 指摘の類型を言語化してから、同型を本文全体で掃討する(指摘された 1 箇所だけ直さない)。"
    )
    stop("finding\t%d\t%s" % (len(body), mode),
         head + "\n\n" + detail[:1500]
         + "\n\n" + howto + "詳細は skill『coldread』。\n" + SCOPE_NOTE
         + ("\n" + screen_note if screen_note else ""),
         len(body), fp)


# ---- 手元の文書(書いた後に記録し、書いた役の終わりにまとめて読む) -----------------------------
# gh への投稿は出したら取り消せないので、書く前に止める(上の main)。手元の文書は書いた後でも直せるので止めない。
# 書くたびに読み手を起こすと、Edit のたびに待たされ、同じ文書を何度も読む(Vale も書いた後に走らせ、止めずに指摘を返す)。
# だから書いた後(PostToolUse)は書いた文書の名前を記録するだけにし、書いた役が終わるときに、その役が書いた
# 文書を 1 本 1 回だけ読ませる。読み手と観点は投稿と同じ COLD_PROMPT で、正本はこの 1 か所。
#
# 記録は書いた役ごとに分ける。サブエージェントの中のフックの入力には、その役を指す agent_id が付く(公式の hooks の
# 文書「the input carries the `agent_id` and `agent_type` common input fields that identify the subagent」。2026-10-15 に
# claude 2.1.300 で実測: サブエージェントの Write の PostToolUse と、その役の SubagentStop に同じ agent_id が付き、親の
# Write と Stop には付かない。Stop はサブエージェントの終わりでは撃たれず、親の終わりに 1 回だけ撃たれた)。
# - サブエージェントが書いた文書は、その役の SubagentStop で読み、指摘の全文をその役に返して直させる(SubagentStop の
#   additionalContext はその役を続けさせる)。前は親の Stop で読んでいたので、指摘が親に届き、親は書いた役へ送り直すしか
#   なく、親の文脈を食った。書き手が書き終える前の書きかけを読む空振りもした。
# - 親(agent_id が無い)が書いた文書は親の Stop で読むが、指摘の全文は親の文脈に積まない。ファイルに書き出し、本数・件数・
#   ファイルの場所と、新しい作業役に渡して直させるという短い知らせだけを返す。親の Stop はサブエージェントの記録を読まない。
# 直した文書は次の終わりにまた読まれ、同じ中身はハッシュで読み直さないので、直さなければ終わる(Claude Code も連続 8 回で打ち切る)。
# 投稿より読む数が多いので、読み手は速く安いモデル(既定 haiku)を effort xhigh で走らせる(Artificial Analysis の総合
# ランキング 2026-10-13 で、Haiku 5.5 の xhigh は Sonnet 5.5 の medium と同じ総合点を約 4 分の 1 の費用で出した。
# convergence-loops 0.42.0 の CHANGELOG)。
DOC_EXTS = (".md", ".mdx", ".adoc", ".asciidoc", ".rst", ".txt")
DOC_MIN_LEN = int(os.environ.get("COLDREAD_DOC_MIN_LEN", "300"))   # これ未満の文書は読まない(字)
DOC_MODEL = os.environ.get("COLDREAD_DOC_MODEL", "haiku")
DOC_EFFORT = os.environ.get("COLDREAD_DOC_EFFORT", "xhigh")
DOC_WORKERS = 4      # 1 回の終わりに読む文書を並べる数。Stop のフックの timeout(300s)に、読み役 1 回(210s)で収める
DOC_SEEN_KEEP = 5000  # 読んだ中身のハッシュを覚える数
DOC_FINDINGS_KEEP = 200  # 親に返す指摘を書き出したファイルを残す数(古いものから消す)
DOC_DIR = os.path.join(STATE_DIR, "docs")
DOC_LOG = os.path.join(STATE_DIR, "docs.log")
DOC_SEEN = os.path.join(DOC_DIR, "seen")
DOC_FINDINGS = os.path.join(DOC_DIR, "findings")
# 1 行目にこの印が在る文書は読まない(書き手が意図して置く逃げ道。印がファイルに残るので記録は要らない)。
# coldwrite(このゲートに移る前の、書く前に止める門番)の印もそのまま効かせる
DOC_SKIP_MARKS = ("coldread:skip", "coldwrite:skip")


def docs_off():
    """手元の文書の門番だけを切る(投稿の門番は残す)。"""
    return os.environ.get("COLDREAD_DOCS_OFF") == "1"


def _safe(name):
    return re.sub(r"[^A-Za-z0-9_-]", "_", name)


def _pending(session, agent=""):
    """書いた役ごとの待ちの一覧。親は <session>.pending、サブエージェントは <session>.<agent_id>.pending。

    区切りの「.」は _safe が両方の名前から消すので、親の名前とサブエージェントの名前は重ならない。
    """
    name = _safe(session or "nosession") + ("." + _safe(agent) if agent else "")
    return os.path.join(DOC_DIR, "%s.pending" % name)


def _who(payload):
    """(session_id, agent_id)。agent_id はサブエージェントの中のフックにだけ付く(親では空)。"""
    return str(payload.get("session_id") or ""), str(payload.get("agent_id") or "")


# Bash・MCP の道具で書いた文書も拾う(持ち主の方針「防ぐより、ひっかける幅を増やす」)。Write・Edit の記録だけでは、
# cat > x.md <<EOF・tee・sed -i・python で書く・mv/cp で置く文書が 1 本も読まれなかった。
# - Bash: 走る前(PreToolUse。投稿の門番の main が呼ぶ)に、cwd の git の作業ツリーの変更一覧のうち文書の (mtime, 大きさ) を
#   控え、走った後(PostToolUse・PostToolUseFailure)に取り直して、増えた・変わった文書を記録に載せる。git の外と、git が
#   見ない文書(.gitignore の中)のために、コマンドの中の書き込み先(リダイレクト・tee・sed -i・cp/mv の行き先)も静的に拾う
# - MCP の道具: 名前が書く道具らしいもの(write・edit・create…)の入力の path の欄を拾う
# 同じ checkout を並行の会話が触っていると、その間の他人の書き込みも拾いうる。読むのは中身のハッシュで 1 回だけなので、
# 同じ中身を 2 つの会話が読むことは無いが、先に終わった方に指摘が返る(gates/README.md の射程)。
DOC_SNAP_DIR = os.path.join(DOC_DIR, "snap")
DOC_SNAP_KEEP = 24 * 3600   # 控えを残す秒数。投稿の門番に止められた Bash は後のフックが走らないので、古い控えを消す
GIT_TIMEOUT = 5             # git 1 回の上限(秒)。PostToolUse のフックの timeout(10s)に収める。超えたら静的な読みだけにする
MCP_WRITE_RE = re.compile(r"write|edit|create|update|save|put|append|move|copy|rename|replace|insert", re.I)
PATH_KEYS = ("file_path", "path", "filePath", "notebook_path", "filename", "destination", "target")


def _git(args, cwd):
    """git を読み取りで走らせ、標準出力(bytes)を返す。失敗・時間切れは None。index の lock を取らない(並行の会話と競らない)。"""
    try:
        r = subprocess.run(["git", "-C", cwd, *args], capture_output=True, timeout=GIT_TIMEOUT,
                           env=dict(os.environ, GIT_OPTIONAL_LOCKS="0"))
    except (OSError, subprocess.SubprocessError):
        return None
    return r.stdout if r.returncode == 0 else None


def _git_docs(root):
    """git の作業ツリー root の変更一覧(追跡外も含む)のうち文書 → {実パス: [mtime_ns, 大きさ]}。取れなければ None。"""
    out = _git(["status", "--porcelain=v1", "-z", "--untracked-files=all", "--no-renames"], root)
    if out is None:
        return None
    docs = {}
    for ent in out.decode("utf-8", "replace").split("\0"):
        if len(ent) < 4 or not ent[3:].lower().endswith(DOC_EXTS):
            continue
        full = os.path.realpath(os.path.join(root, ent[3:]))   # porcelain のパスは作業ツリーの根から
        try:
            st = os.stat(full)
        except OSError:
            continue   # 消された文書
        if stat.S_ISREG(st.st_mode):
            docs[full] = [st.st_mtime_ns, st.st_size]
    return docs


def _snap_file(payload):
    return os.path.join(DOC_SNAP_DIR, _safe(str(payload.get("tool_use_id") or "")) + ".json")


def docs_snapshot(payload):
    """PreToolUse(Bash): 走る前の、cwd の git の変更一覧の文書の状態を控える。git の外なら根は None で、静的な読みだけになる。"""
    if docs_off() or payload.get("tool_name") != "Bash" or not payload.get("tool_use_id"):
        return
    cwd = payload.get("cwd") or ""
    top = _git(["rev-parse", "--show-toplevel"], cwd) if os.path.isdir(cwd) else None
    root = top.decode("utf-8", "replace").strip() if top else None
    docs = _git_docs(root) if root else None
    os.makedirs(DOC_SNAP_DIR, exist_ok=True)
    now = time.time()
    for e in os.scandir(DOC_SNAP_DIR):
        try:
            if now - e.stat().st_mtime > DOC_SNAP_KEEP:
                os.remove(e.path)
        except OSError:
            pass
    with open(_snap_file(payload), "w", encoding="utf-8") as f:
        json.dump({"root": root if docs is not None else None, "docs": docs or {}}, f)


def _written_by_command(command, cwd):
    """コマンドの中の書き込み先のうち、在る文書の実パス(リダイレクト・tee・sed -i・cp/mv/install の行き先)。"""
    norm, heredoc_bodies = prepare(command)
    tokens = tokenize(norm)
    if tokens is None:
        return []
    cmds = split_commands(tokens)
    files = BodyFiles(cmds, cwd, heredoc_bodies, norm, tokens)
    out = []
    for k, c in enumerate(cmds):
        at = command_start(c.args)
        f = files.at(k, c.args[:at])
        dests = [d for op, d in c.redirects if op in WRITE_OPS]
        name = os.path.basename(c.args[at]) if at < len(c.args) else ""
        rest = [a for a in c.args[at + 1:] if not a.startswith("-")]
        if name == "tee":
            dests += rest
        elif name in ("sed", "gsed") and any(a.startswith(("-i", "--in-place")) for a in c.args[at + 1:]):
            dests += [a for a in rest if a.lower().endswith(DOC_EXTS)]
        elif name in ("cp", "mv", "install") and len(rest) >= 2:
            dests += [rest[-1]] + [os.path.join(rest[-1], os.path.basename(s)) for s in rest[:-1]]
        for d in dests:
            p = f.path(d)
            if p and p.lower().endswith(DOC_EXTS) and os.path.isfile(p):
                out.append(p)
    return out


def _bash_docs(payload):
    """PostToolUse(Bash): 控えと取り直しの差で増えた・変わった文書と、コマンドの書き込み先の文書。"""
    found, snap = [], None
    try:
        with open(_snap_file(payload), encoding="utf-8") as f:
            snap = json.load(f)
        os.remove(_snap_file(payload))
    except (OSError, ValueError):
        pass
    if snap and snap.get("root"):
        now = _git_docs(snap["root"])
        if now is not None:
            before = snap.get("docs") or {}
            found += [p for p, st in now.items() if before.get(p) != st]
    command = (payload.get("tool_input") or {}).get("command") or ""
    try:
        found += _written_by_command(command, payload.get("cwd") or None)
    except Exception:
        pass   # 静的な読みの失敗で記録の口を落とさない(手元の文書は止めない側)
    return found


def _tool_docs(payload):
    """Write・Edit・NotebookEdit と MCP の書く道具の入力の path の欄。"""
    tool = str(payload.get("tool_name") or "")
    ti = payload.get("tool_input") or {}
    if tool.startswith("mcp__") and not MCP_WRITE_RE.search(tool.rsplit("__", 1)[-1]):
        return []
    if tool.startswith("mcp__"):
        return [os.path.realpath(v) for v in (ti.get(k) for k in PATH_KEYS) if isinstance(v, str) and v]
    return [os.path.abspath(v) for v in (ti.get(k) for k in ("file_path", "notebook_path")) if isinstance(v, str) and v]


def docs_record(payload):
    """PostToolUse: 書いた文書のパスを、書いた役の待ちの一覧に足す。読まない・止めない。"""
    paths = _bash_docs(payload) if payload.get("tool_name") == "Bash" else _tool_docs(payload)
    paths = [p for p in dict.fromkeys(paths) if p.lower().endswith(DOC_EXTS)]
    if not paths:
        return
    try:
        os.makedirs(DOC_DIR, exist_ok=True)
        with open(_pending(*_who(payload)), "a", encoding="utf-8") as f:
            f.write("".join(p + "\n" for p in paths))
    except OSError:
        pass


def _seen():
    return set(_seen_list())


def _remember(digests):
    if not digests:
        return
    try:
        lines = [*_seen_list(), *digests][-DOC_SEEN_KEEP:]
        tmp = DOC_SEEN + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
        os.replace(tmp, DOC_SEEN)
    except OSError:
        pass


def _seen_list():
    try:
        with open(DOC_SEEN, encoding="utf-8") as f:
            return f.read().split()
    except OSError:
        return []


def doc_to_read(path, seen):
    """読むなら (本文, 中身のハッシュ)、読まないなら (None, 理由)。"""
    try:
        with open(path, encoding="utf-8") as f:
            text = f.read()
    except (OSError, UnicodeDecodeError) as e:
        return None, "読めない(%s)" % type(e).__name__
    first = text.split("\n", 1)[0]
    if any(mark in first for mark in DOC_SKIP_MARKS):
        return None, "1 行目に逃げ道の印"
    if len(text) < DOC_MIN_LEN:
        return None, "%d 字(%d 字未満は読まない)" % (len(text), DOC_MIN_LEN)
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    if digest in seen:
        return None, "同じ中身を前に読んだ"
    return text, digest


def read_doc(text):
    """文書を 1 本、投稿と同じ観点(COLD_PROMPT)で読ませて、ラベルごとの行を返す。報告の形でなければ例外。"""
    out = run_reader(COLD_PROMPT + text, model=DOC_MODEL, effort=DOC_EFFORT)
    if not report_shaped(out):
        raise RuntimeError("報告の形(CLEAN かラベル行)をしていない: %r" % out[:150])
    return sort_findings(out)


def doc_feedback(path, found):
    """1 本の文書の指摘を、直してほしい順の節にする(詰まりも補完も無ければ空)。"""
    if not (found["詰まり"] or found["補完"]):
        return ""
    return "\n".join(filter(None, (
        "■ %s" % path,
        section("詰まり(直す):", found["詰まり"]),
        section("coldreader が推測で埋めた箇所(意図と違うなら直す):", found["補完"]),
        section("残った疑問(反映するかは判断してよい):", found["疑問"]),
    )))


def _read_pending(session, agent):
    """書いた役の待ちの一覧を読んで消し、読ませる文書を読ませる。(指摘の節, 件数, 読めなかった文書) を返す。"""
    pending = _pending(session, agent)
    try:
        with open(pending, encoding="utf-8") as f:
            # 同じ文書が別の綴り(Write の abspath と Bash の実パス)で載っていても 1 回だけ読む
            paths = list({os.path.realpath(p): p for p in (line.strip() for line in f) if p}.values())
        os.remove(pending)
    except OSError:
        return [], {"詰まり": 0, "補完": 0}, []
    who = "sid=%s" % session[:8] + ("\taid=%s" % agent[:17] if agent else "")
    seen = _seen()
    todo = []
    for path in paths:
        text, why = doc_to_read(path, seen)
        if text is None:
            log_line(DOC_LOG, "skip\t%s\t%s\t%s" % (why, who, path))
        else:
            todo.append((path, text, why))
    notes, counts, read, down = [], {"詰まり": 0, "補完": 0}, [], []
    if not todo:
        return notes, counts, down
    with concurrent.futures.ThreadPoolExecutor(max_workers=DOC_WORKERS) as pool:
        futures = {pool.submit(read_doc, text): (path, text, digest) for path, text, digest in todo}
    for fut, (path, text, digest) in futures.items():
        try:
            found = fut.result()
        except Exception as exc:
            log_line(DOC_LOG, "reader-down\t%s\t%s\t%s" % (str(exc)[:150].replace("\n", " "), who, path))
            down.append(path)
            continue
        read.append(digest)
        note = doc_feedback(path, found)
        log_line(DOC_LOG, "%s\t%d\t%s\t%s" % ("finding" if note else "clean", len(text), who, path))
        if note:
            notes.append(note)
            for label in counts:
                counts[label] += len(found[label])
    _remember(read)
    return notes, counts, down


def _write_findings(session, body):
    """親に返す指摘の全文をファイルに書き、その場所を返す。古いものは DOC_FINDINGS_KEEP 本を残して消す。"""
    os.makedirs(DOC_FINDINGS, exist_ok=True)
    path = os.path.join(DOC_FINDINGS, "%s-%s-%d.txt" % (time.strftime("%Y%m%d-%H%M%S"), _safe(session)[:8], os.getpid()))
    with open(path, "w", encoding="utf-8") as f:
        f.write(body + "\n")
    try:
        old = sorted(os.scandir(DOC_FINDINGS), key=lambda e: e.stat().st_mtime)[:-DOC_FINDINGS_KEEP]
        for e in old:
            os.remove(e.path)
    except OSError:
        pass
    return path


def docs_check(payload):
    """Stop・SubagentStop: 終わろうとしている役が書いた文書を 1 本 1 回だけ読ませ、指摘が在れば止めずに返して直させる。

    サブエージェント(agent_id が有る)には指摘の全文を返す。親には全文をファイルに書き、短い知らせだけを返す。
    """
    session, agent = _who(payload)
    notes, counts, down = _read_pending(session, agent)
    if not notes and not down:
        return
    event = payload.get("hook_event_name") or ("SubagentStop" if agent else "Stop")
    reader = "coldread(文脈を持たない初見の読み手 coldreader、モデル %s・effort %s)" % (DOC_MODEL, DOC_EFFORT)
    tail = ("読み手を起こせず読めなかった文書(%s)。手で読ませるなら python3 %s read <パス>。"
            % ("・".join(down), os.path.abspath(__file__))) if down else ""
    if agent:
        head = (reader + "が、この役が書いた文書を読んだ。"
                + ("詰まった箇所を直すこと(直した文書はこの役の終わりにまた読まれる。直さずに残すと判断したものは、"
                   "そのまま終えてよい——同じ中身は読み直さない):" if notes else ""))
        context = "\n\n".join(filter(None, (head, *notes, tail, VERSION_NOTE)))
    else:
        context = tail
        if notes:
            try:
                where = _write_findings(session, "\n\n".join((reader + "が、親の会話で書いた文書を読んだ指摘。", *notes)))
            except OSError as exc:
                where = None
                log_line(DOC_LOG, "findings-unwritten\t%s\tsid=%s" % (type(exc).__name__, session[:8]))
            if where:
                context = "\n\n".join(filter(None, ((
                    "%sが、このターンで書いた文書 %d 本に指摘を出した(詰まり %d 件・推測で埋めた箇所 %d 件)。全文は %s 。"
                    "新しい作業役(サブエージェント)にこのファイルを渡して直させ、全文をこの会話に読み込まない。"
                    "推測で埋めた箇所のうち書き手の意図と違うものだけは、この会話で見て、正しい意図を作業役に伝える。"
                    "直さずに残すと判断したものは、そのまま終えてよい——同じ中身は読み直さない。"
                    % (reader, len(notes), counts["詰まり"], counts["補完"], where)), tail)))
            else:
                # 書き出せないときは全文を返す(指摘を落とすより文脈を食うほうがまし)
                context = "\n\n".join(filter(None, (reader + "が、このターンで書いた文書を読んだ。詰まった箇所を直すこと:", *notes, tail)))
        context = "\n\n".join(filter(None, (context, VERSION_NOTE)))
    print(json.dumps({"hookSpecificOutput": {"hookEventName": event, "additionalContext": context}}, ensure_ascii=False))


def read_now(path):
    """手で 1 本を読ませる(記録もハッシュも見ない)。指摘を出し、詰まりが在れば 1 で終わる。"""
    with open(path, encoding="utf-8") as f:
        text = f.read()
    found = read_doc(text)
    body = doc_feedback(path, found)
    print(body or "CLEAN(詰まりも補完も無い)" + ("\n" + section("残った疑問:", found["疑問"]) if found["疑問"] else ""))
    return 1 if found["詰まり"] else 0


def hook_main(mode):
    """手元の文書の口。フックの入力は JSON の stdin。失敗しても書き手の作業を止めない(手元の文書は書いた後でも直せる)。"""
    if docs_off() or os.environ.get("COLDREAD_IN_READER") == "1":
        return
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return
    (docs_record if mode == "docs-record" else docs_check)(payload)


if __name__ == "__main__":
    MODE = sys.argv[1] if len(sys.argv) > 1 else ""
    if MODE in ("docs-record", "docs-check"):
        hook_main(MODE)
    elif MODE == "read" and len(sys.argv) == 3:
        sys.exit(read_now(sys.argv[2]))
    elif MODE == "prompt":
        # 初見で読む観点の正本はこの 1 か所(COLD_PROMPT)。手で読み手を立てるときも、これを依頼文にする。
        # バイトで出す(Windows の文字の出力は改行を \r\n に替え、正本と同じバイトにならない)
        sys.stdout.flush()
        sys.stdout.buffer.write(COLD_PROMPT.encode("utf-8"))
    elif MODE:
        sys.exit("使い方: coldread-gate.py [docs-record | docs-check | read <パス> | prompt](引数なしは投稿の門番)")
    else:
        main()
