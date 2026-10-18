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
読み手が直後の本文を読むため、「毎回新規の読み役」も機械が保証する(別プロセスとして新しい。同じ投稿の書き直しの
2 回目からは、前の回の指摘と差分を渡す)。

エージェントが自分で検査を外す逃げ道は無い(持ち主の判断 2026-10-16。前の COLDREAD_SKIP=1 は、本文ファイルの
書き直しを避けて未検査のまま出す口に 22 回使われた。今は書かれていても効かせず、書いた事実だけを記録する)。
読み役が起動できないときも止める。往復の上限は置かない(持ち主 2026-10-17)。同じ投稿の書き直しは、2 回目から
前の回の指摘と直した差分を読み手に渡し、解けていない指摘と直しが持ち込んだ物だけで止め、CARRY_ONLY_ROUND 回目(3)からは
前の回から残った物だけで止める(FOLLOWUP_NOTE)。持ち主に通させる口は置かない(持ち主 2026-10-17)。
同じ投稿が STUCK_MARK 回(3)続けて止まったら stuck.log に残す(初見指摘は読み手ごとに揺れ、
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
gh でその「画面」を取り、読み手に既知として渡す。新しい PR・issue も、GitHub が本文の周りに出すもの
(題・リポジトリ・ブランチ・変更ファイル・本文が指す #番号 の題)を渡す(release・gist・discussion の新規作成は
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
形は実物の読み手に 1 件も拾われなかったが、独立のフィールドとして問うと 3 語とも拾い、引用して指す返信は
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

記録は $CLAUDE_CONFIG_DIR/coldread-gate/ に 4 本と、置き場 2 つ:
  denies.log  allow / deny の別(deny はタブ区切りで種別も。maxlen・parse-fail・
              blocked・reader-down・reader-shape・finding)。finding と allow には本文の長さと読み方
              (screen=スレッドの画面を渡した / new=新しい PR・issue の画面を渡した / cold=文脈ゼロ)も付く——連続 deny の間に本文が
              どれだけ膨れたかを示すため。blocked には止めた理由(why=)が付く。各行の末尾に sid=(session id の先頭 8 字)
              v=(このゲートの版) to=(投稿先。種別:repo:番号、新規作成はサブコマンド)、本文を読んだ deny には
              fp=(本文の指紋。本文を写さずに、同じ投稿の書き直しかを比べる)
  skip.log    効かせなかった逃げ道(refused)と、読み役の中で発火した呼び出しのコマンド先頭
  misses.log  本文旗の綴りが在るのに候補も blocked も空だった単純コマンドの、旗の綴りと先頭の語
              =ゲートから漏れた疑い。「投稿でなかった」と区別が付かないと押し出しの量を測れないので分けて残す
  stuck.log   STUCK_MARK 回続けて止まった投稿の、会話・版・宛先の種類・止めた回数と理由の並び・本文の長さの並び
              (本文は写さない)。ゲートか書き方のどちらかがおかしい合図なので、後で直す材料にする
  rounds/     書き直しの前の回の本文と指摘(書き手と投稿先の組ごとに 1 つ。通ったら消す。FOLLOWUP_NOTE)

環境変数:
  COLDREAD_READER_CMD        読み役コマンドの差し替え(POSIX sh 文字列として sh -c 実行。stdin に依頼文+本文)。テスト用
  COLDREAD_GH_CMD            画面(投稿先のスレッド)を取る gh の差し替え(POSIX sh 文字列として
                             sh -c 実行。$1 以降に gh の引数列)。テスト用
  COLDREAD_MODEL             既定 sonnet
  COLDREAD_EFFORT            既定 medium
  (手元の文書の読み手の環境変数 COLDREAD_DOC_* は、下の「手元の文書」のセクションの冒頭)
  COLDREAD_MAX_LEN           これを超えるコマンドは解析せず deny。既定 100000
  COLDREAD_IN_READER=1       読み役の中であることの印(自動で付く)。入れ子の再発火を防ぐ
  COLDREAD_KEYCHAIN_SERVICE  macOS Keychain の OAuth トークンのサービス名(未指定なら
                             CLAUDE_CONFIG_DIR の末尾から推定: ~/.claude-p1 → claude-code-oauth-p1)
"""
import bisect
import concurrent.futures
import difflib
import hashlib
import importlib.util
import json
import os
import re
import shlex
import shutil
import stat
import subprocess
import sys
import tempfile
import time

# Windows では stdio が locale 既定の code page になり(GitHub Actions windows-latest で
# cp1252 を実測。日本語 Windows なら cp932)、日本語の deny メッセージが UnicodeEncodeError で
# 落ちてフック自体が素通りになるため、UTF-8 に固定する(hook の入出力は UTF-8 の JSON)。
for _stream in (sys.stdin, sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

# 認証の段は隣の共有の本文が持つ(複数のプラグインに写しで在り、同一性は tests/run.sh のチェックが見る)。
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
# 対象外と受容した形は gates/README.md「Reach of the net (honest limits)」。
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
# 一般のままなので、gh が投稿サブコマンドを増やしても --body 等で書かれていればゲートに掛かる。
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
# ゲートから漏れたことの検出だけに使う綴り(判定には使わない)。本文旗が単純コマンドの語にあるのに
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
    注釈を落とす分岐は行末までしか進まないので次の行は残る。

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
    """単純コマンドのコマンド名の位置。前置(環境変数の代入・env/timeout 等とその旗と値)を読み飛ばす。無ければ len(tokens)。

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
    gql_fields = {}   # graphql の -f/-F のフィールド(名前 → (型付きか, 値))。query と変数を後でまとめて見る

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
        取り損ねた投稿が実際にこの形で allow に落ちていた(回帰テストは tests/run.sh)。
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
                            # comments[][body] は review の行コメント(gh api の配列のフィールドの書き方)
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
            # mutation が本文を運ぶのは body(と readme)のフィールドだけ。フィールドの値だけを抜き、ほかのフィールド(ID・トークン・
            # 設定値)は読み役へ送らない。フィールドを持たない mutation(resolveReviewThread など)は投稿でない——
            # 一律で止めていた頃は、これが往復の 57 件を生んでいた。
            texts = graphql_bodies(query, gql_fields, read_file)
            if texts is None:
                blocked.append("graphql mutation の本文を取り出せない")
            elif texts:
                candidates.append("\n\n".join(texts))

    return candidates, blocked


# graphql の mutation で本文を運ぶフィールド。`$body:`(変数の宣言)はフィールドではないので、直前の $ と語の字を除く
GQL_BODY_FIELD_RE = re.compile(r"""(?<![\w$])(?:body|readme)\s*:\s*""")
GQL_STRING_RE = re.compile(r'"""(.*?)"""|"((?:[^"\\]|\\.)*)"|\$([A-Za-z_]\w*)', re.S)


def graphql_bodies(query, fields, read_file):
    """mutation の本文のフィールドの値の列。値が決まらないフィールドが 1 つでも在れば None(止める)。

    値はブロック文字列・文字列・変数($名前 は -f/-F の同じ名前のフィールド)。変数として使われなかった
    body・…[body] のフィールド(input[body]= のように入れ物ごと渡す形)も本文として読む。
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
#   - 同じコマンドの中で本文ファイルを書く単純コマンドが在れば、`cat > f <<EOF` 1 本だけならそのヒアドキュメントを
#     読む(フックの時点のファイルは古い中身)。それ以外の書き手(cp・mv・sed・tee・>…)が在れば止める
#   - 開くのは O_NONBLOCK で、開いた後に fstat で通常のファイルかを見る(FIFO が書き手を待ってフックを止めると、
#     フックの timeout で無検査で通る)。上限(COLDREAD_MAX_LEN 字)を超える・UTF-8 でないものは止める
# 残る穴: フックが読んだ後、gh が読むまでの間に別のプロセスが書き換える余地(チェックと実行の間。gates/README.md)。
WRITE_OPS = {">", ">>", ">|", "&>", "&>>"}
# 本文ファイルの名前を引数に持っていても、ファイルを書き換えないコマンド(書くリダイレクトは別に見る)
READ_ONLY_CMDS = {"cat", "wc", "head", "tail", "ls", "test", "[", "stat", "file", "grep", "diff", "less",
                  "jq", "echo", "printf", "cd"}
_SEQUENTIAL = (";", "&&", "\n")   # 前のコマンドの効果(代入・cd)が後ろへ届く区切り
_RUNS_BEFORE = ("", ";", "\n")     # 直前の区切りがこれなら、そのコマンドは前の成否に関わらず必ず走る
CD_WORDS = {"cd", "pushd", "popd", "chdir"}
CONDITIONAL_WORDS = {"if", "then", "else", "elif", "fi", "case", "esac", "while", "until", "for", "do", "done", "select"}
# 変数を入れ直しうるコマンド(引数に名前を取る)。この名前は同じコマンドの中の代入から解かない
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

    Windows の Claude Code は Bash のツールを Git Bash(MSYS2)で走らせるので、コマンドの中のパスは `/c/Users/…`・
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
        # if・case・繰り返しの中のコマンドは、区切りが ; でも走るとは限らない(予約語は単純コマンドから落ちるので、語の列で見る)
        self.conditional = any(t in CONDITIONAL_WORDS for t in tokens)
        self.cwd = cwd if cwd and os.path.isabs(cwd) else None
        self.k, self.moved = 0, False
        self._assigned = None
        self._sq = None
        # 繰り返し・関数の中では、gh の後に書いたコマンドも次の gh の前に走る
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

        cwd を変えるコマンド(cd・pushd・popd を語のどこかに持つもの。`if cd x`・`builtin cd x` も)が前に在れば、
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
            # `~/` はシェルが HOME で開く。フックは Bash と同じ利用者・同じ HOME で起動される(コマンドの中で HOME を
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
        """同じコマンドの中で target を書く単純コマンド。無ければ None、`cat > f <<EOF` 1 本ならその本文、ほかは "writer"。"""
        base = os.path.basename(target)
        found = []
        for j, c in enumerate(self.cmds):
            if not self.looped and j > self.k and self._between(self.k, j, _SEQUENTIAL + ("||",), below_ok=True):
                continue   # gh が終わった後に走るコマンド(`gh … --body-file f && rm f` の後片付け)は gh の読む中身を変えない
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
    """コマンド 1 本の解析の結果。calls は gh 呼び出しごとの (サブコマンド, 引数列, 本文候補, 止めた理由, cwd)。
    cwd はその gh が走る場所(前の cd を読んだもの。決まらなければ None)。"""

    def __init__(self, parsed, candidates=(), blocked=(), calls=(), misses=()):
        self.parsed, self.candidates, self.blocked = parsed, list(candidates), list(blocked)
        self.calls, self.misses = list(calls), list(misses)

    def call_of(self, body=None):
        """body を運んだ呼び出し(無ければ止めた呼び出し)の (サブコマンド, 引数列, cwd)。無ければ (None, [], None)。"""
        for sub, args, cands, blk, cwd in self.calls:
            if (body is not None and body in cands) or (body is None and (blk or cands)):
                return sub, args, cwd
        return None, [], None

    def target_of(self, body=None):
        """log に残す投稿先と、画面を取る投稿先 (ラベル, dest)。"""
        sub, args, _ = self.call_of(body)
        if sub is None and not args:
            return "-", None
        dest = destination(args, sub) if sub else None
        return target_label(sub, dest), dest


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
            here = files.at(k, c.args[:len(c.args) - len(args) - 1])
            cands, blk = classify(args, heredoc_bodies, live, here, live_var)
            sub = subcommand(args)
            out.calls.append((sub, args, cands, blk, here.cwd_here()))
            out.candidates.extend(cands)
            out.blocked.extend(blk)
        # 素通しの理由が「投稿でない」なのか「ゲートから漏れた」なのかを後から数える。本文旗の綴りが単純コマンドに
        # 在るのに、その単純コマンドが候補も止めた理由も出さなかったら、解析の取りこぼしの疑いがある。
        # 見るのはヒアドキュメントを印に置き換えた後の語(本文の中の綴りは数えない)。gh の語を含む単純コマンドに
        # 限り、当たった旗と先頭の語(sh・python3・echo …)を残す——誤検知(別のツールの旗・文書の中の綴り)を後から分ける
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
# (経緯は冒頭の docstring)。そこで投稿先がスレッドなら gh で画面の中身を取って渡す。
# 新規の PR・issue も読み手は本文だけを見ているのではない。GitHub は本文の周りに題・リポジトリ・
# (PR なら)取り込む先と元のブランチ・変更ファイル・本文が指す #番号 の題を出す(閉じる issue は PR の横に題ごと並ぶ)。
# それを渡さずに読ませると、本文 1 行目の「Closes #660」まで「何の issue か分からない」と止まった
# (2026-10-17 に実測。works-factory の新しい PR 3 本の本文が、合わせて 7 回止まった)。そこで new_item_screen が
# その分だけを組んで渡す。release・gist・discussion の create は今までどおり文脈ゼロ。
# 取れなかったときは文脈ゼロに倒して検査は走らせ、その旨を書き手に伝える。
# 画面の中身は他人の文章なので読み手への指示が混ざりうるが、読み手はツールを持たず(--tools "")、
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
# 新しく作るもので、GitHub が本文の周りに題などを出すもの(new_item_screen)。値は読み手に示す呼び名
NEW_ITEM_SUBS = {("pr", "create"): "PR", ("issue", "create"): "issue"}
# その 2 つの旗のうち値を取るもの(gh 2.x の `gh pr create --help`・`gh issue create --help`)。短縮形 → 長い形。
# 値を値として読み飛ばさないと、本文や題の値が「-t…」で始まるだけで別の旗に読める
CREATE_VALUE_FLAGS = {"-a": "--assignee", "-B": "--base", "-b": "--body", "-F": "--body-file", "-H": "--head",
                      "-l": "--label", "-m": "--milestone", "-p": "--project", "-r": "--reviewer",
                      "-T": "--template", "-t": "--title", "-R": "--repo", "--recover": "--recover"}


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


def flag_value(args, short, long):
    """値を取る旗(-X 値・-X値・--xx 値・--xx=値)の値。無ければ None。"""
    for i, tok in enumerate(args):
        if tok in (short, long) and i + 1 < len(args):
            return args[i + 1]
        for f in (short, long):
            if tok.startswith(f + "="):
                return tok[len(f) + 1:]
        if tok.startswith(short) and tok != short and not tok.startswith("--"):
            return tok[len(short):]
    return None


def repo_flag(args):
    """-R/--repo の値。無ければ None(gh はカレントの git remote を使う)。"""
    return flag_value(args, "-R", "--repo")


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


def referenced_lines(g, repo, nums, label="[本文とスレッドが参照している番号]"):
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
    return [label] + lines if lines else []


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
        # 同じ元の指摘に連なるものだけ。一覧に元の指摘が無ければ(ページの外)、直接取った c を元の指摘として置く
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
        # 元の指摘は body の位置に置いて落とさず、返信だけを予算で落とす対象にする
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


def create_flags(args, sub):
    """gh pr/issue create の旗を {長い形: 値} に読む。値を取らない旗は True。サブコマンド語より後ろだけを見る。"""
    out, longs = {}, set(CREATE_VALUE_FLAGS.values())
    i = args.index(sub[1]) + 1 if sub[1] in args else len(args)
    while i < len(args):
        tok = args[i]
        name, _, val = tok.partition("=") if tok.startswith("--") else (tok, "", "")
        if tok in CREATE_VALUE_FLAGS or tok in longs:
            if i + 1 < len(args):
                out[CREATE_VALUE_FLAGS.get(tok, tok)] = args[i + 1]
            i += 2
            continue
        if tok.startswith("--") and "=" in tok:
            out[name] = val
        elif tok.startswith("-") and not tok.startswith("--") and tok[:2] in CREATE_VALUE_FLAGS:
            val = tok[2:]
            out[CREATE_VALUE_FLAGS[tok[:2]]] = val[1:] if val.startswith("=") else val
        elif tok.startswith("-"):
            out[tok] = True
        i += 1
    return out


def new_item_screen(sub, args, cwd, body):
    """新しく作る PR/issue を開いた読み手に、GitHub が本文の周りに出すものを返す (画面の文, 取れなかった物)。
    題・-R・-B・-H はコマンドから読み、省かれた分(リポジトリ・既定のブランチ・今のブランチ)は gh と git で引く。
    cwd はその gh が走る場所で、決まらない(None)ときは cwd に頼る引き方(リポジトリ・今のブランチ)をしない——
    `cd 別の場所 && gh pr create` で、フックの場所のブランチの中身を画面として渡さないため。
    1 つ取れなくても残りで組む。何も組めなければ画面は None(文脈ゼロで読む)。"""
    g = Screen(cwd)
    missed = []
    flags = create_flags(args, sub)
    title, repo = flags.get("--title"), flags.get("--repo")
    default_branch = None
    try:
        if not (repo or g.cwd):
            raise RuntimeError("gh が走る場所が分からない")
        info = g.json(["repo", "view"] + ([repo] if repo else []) + ["--json", "nameWithOwner,defaultBranchRef"])
        repo = info.get("nameWithOwner") or repo
        default_branch = (info.get("defaultBranchRef") or {}).get("name")
    except Exception:
        if not repo:
            missed.append("リポジトリ")
    draft = sub == ("pr", "create") and ("-d" in flags or "--draft" in flags)
    lines = ["新しい %s%s(%s%s)" % (NEW_ITEM_SUBS[sub], "「%s」" % title if title else "",
                                  repo or "このリポジトリ", "、draft" if draft else "")]
    if sub == ("pr", "create"):
        base = flags.get("--base") or default_branch
        head = flags.get("--head")
        if not head and g.cwd:
            out = _git(["rev-parse", "--abbrev-ref", "HEAD"], g.cwd)
            head = out.decode("utf-8", "replace").strip() if out else None
            head = None if head == "HEAD" else head  # ブランチの無い状態(detached)では gh もブランチを決められない
        if base and head:
            lines.append("[取り込む先 ← 元のブランチ] %s ← %s" % (base, head))
        try:
            if not (repo and base and head):
                raise RuntimeError("比べるブランチが分からない")
            cmp = g.json(["api", "repos/%s/compare/%s...%s" % (repo, base, head)])
            lines += files_lines([f.get("filename") for f in cmp.get("files") or []])
        except Exception:
            missed.append("変更ファイルの一覧")
    nums = referenced_numbers([title, body], None)
    if nums:
        refs = referenced_lines(g, repo, nums, "[本文が参照している番号]") if repo else []
        if not refs:
            missed.append("本文が参照している番号の題")
        lines += refs
    return ("\n".join(lines) if len(lines) > 1 or title or repo else None), missed


# ---- 読み役 ----------------------------------------------------------------
# 観点と報告の形式は 2 つの依頼文で共通。違うのは読み手の立ち位置(文脈ゼロ/画面を見ている)と、
# 画面モードにだけ在る「冗長」フィールド——画面に有るものを本文で説明した箇所を、止めずに書き手へ返す。
# 文脈ゼロの依頼文には冗長を置かない(画面が無いので、冗長かどうかを読み手が決められない)。
_FORMAT_COMMON = """- (1)〜(4) に該当し、その箇所で意味が取れず次の文へ読み進められなかったもの → 1 行 1 件、行頭に「詰まり: 」。
  詰まりは次の 3 つのどれかだけ。「詰まり: 」の直後に (語) (指す先) (筋) のどれかを書く:
  (語) 語・略語・識別子の意味が取れない / (指す先) 何・誰・どこを指すかが取れない / (筋) 文と文のつながり・この文が何を言っているかが取れない
  (1)(2) が言えない・掴めないのは (筋) として書く
  この検査が見るのは通じやすさだけで、出してよいか・中身が正しいか・判断に足りるかは見ない。意味は取れたが、
  根拠・裏付け・出所・数字の出どころが欲しい、判断の材料が足りない、本当にそうか・ほかの場合はどうか・実例はあるかを
  確かめたい、というものは詰まりではなく疑問。迷ったら疑問にする
- (5) のうち、理解はできたが答えが本文に無い疑問 → 1 行 1 件、行頭に「疑問: 」
- (4) のうち、推測で埋めて読み進められた箇所 → 1 行 1 件、行頭に「補完: 」。
  「何をどう埋めたか」を書く(例:「補完: 障害は今起きていると読んだ」)。
  推測で埋めたなら、理解を妨げていなくても書く——書き手はここで初めて自分の誤読を知る
"""
# 依頼文の終わりの、本文の始まりの印。手元の文書の抜き出しは、この印の手前に補足を差し込む(doc_prompt)
BODY_MARK = "--- 本文 ---\n"
_RULES = """規則: 点数・総評・文体の好み・軽微な言い換え提案は書かない。読めば分かることへの確認は書かない。該当の無いフィールドは「詰まり: なし」のように書かず、行ごと省く。日本語で。

""" + BODY_MARK
# 初見の観点。(3) の「何と合わせて解くか」だけが、文脈ゼロと新しい PR/issue(画面あり)で違う
_COLD_VIEWS = """見る観点:
(1) この文章があなたに求めていること(読んで何をすべきか)が言えるか
(2) 冒頭 3 行で「何の話か・自分に関係あるか・急ぐか」が掴めるか
(3) %s意味を解決できない略語・識別子・参照は無いか
(4) 意味を推測で埋めた箇所と、埋めた推測の中身(特に時制・主体・範囲)
(5) 読み終えて残った疑問は何か

報告の形式(この 4 種類だけ。問題の無かった観点は一切書かない):
""" + _FORMAT_COMMON + """- 詰まりも疑問も補完も 1 件も無いときだけ、他に何も書かず CLEAN とだけ出力
  (1 件でもあるなら CLEAN とは書かない)
""" + _RULES
COLD_PROMPT = """あなたはこの文章について何も知らない初見の読者です。会話の経緯もリポジトリも見ていません。
以下の「本文」だけを読み、理解を実際に妨げた事実だけを報告してください。

""" + _COLD_VIEWS % "本文の中だけでは"
# 新しい PR/issue を開いた読み手が、本文の周りに見ているもの(new_item_screen が組む物)
NEW_SCREEN_ITEMS = {"PR": "題・リポジトリ・取り込む先と元のブランチ・変更ファイルの一覧・本文が参照している番号の題と状態",
                    "issue": "題・リポジトリ・本文が参照している番号の題と状態"}
NEW_PROMPT = """あなたはこの {noun} を初めて開いた読者です。会話の経緯もリポジトリの中身も見ていません。
ただし GitHub はこの {noun} の本文の周りに次のものを表示していて、あなたはそれを見ています。

--- 画面に既に見えているもの ---
%s
--- 画面ここまで ---

以下の「本文」を読み、理解を実際に妨げた事実だけを報告してください。
画面に見えているもの({items})は「何を指しているか分かっている」ものとして読み、本文で説明されていなくても詰まりにしない。
画面が分からせるのは何を指しているかであって、語の意味ではない。画面の題に有る語でも、本文がそれを自分の言葉として使い、画面と本文を合わせても意味が取れなければ詰まりにする。
本文が参照している番号の題は、その番号の側の物で、本文の書き手には直せない。その題の中の語が分からなくても詰まりにしない(本文がその語を自分の言葉として使っているときだけ、本文の側の詰まりにする)。

""" + _COLD_VIEWS % "画面と本文を合わせても"
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
- 参照されている番号の題は、その番号の側の物で、本文の書き手には直せない。その題の中の語が分からなくても詰まりにしない(本文がその語を自分の言葉として使っているときだけ、本文の側の詰まりにする)
- 本文が、画面に見えているものを改めて説明している箇所(誰宛か・どの番号の PR か・PR が何をするものか・相手の印や語の意味・相手が何を書いたか)は「冗長: 」として報告する(読み手は既に見ている)

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


def reader_prompt(screen, noun=None):
    """読み手に渡す依頼文(本文の手前まで)。noun(PR/issue)が有れば新しく作る物の画面、
    画面だけ有ればスレッドの画面、どちらも無ければ文脈ゼロ。"""
    if screen and noun:
        return NEW_PROMPT.replace("{noun}", noun).replace("{items}", NEW_SCREEN_ITEMS[noun]) % screen
    return SCREEN_PROMPT % screen if screen else COLD_PROMPT


# 書き直しの 2 回目からの読み手に足す前置き。1 回目の読み手は本文の全体を読んで全部挙げ、2 回目からの読み手は、
# 前の回の指摘が解けたかと、直しが持ち込んだ物だけを止める理由にする。毎回まっさらな読み手に全体を読ませていた頃は、
# 前の回の指摘と直しを知らない読み手が逆の注文を出し(issue へのコメントで、2 回目が「前のコメントの言い直しだから
# 削れ」、3 回目が「前のコメントのどの案か言い換えられていない」)、前の読み手が言わなかった端の所を毎回新しく
# 拾って、同じ投稿が上限の 3 回まで止まり続けた(2026-10-17 の works-factory で 5 本。stuck.log)。持ち主の決め
# (2026-10-17、works-factory の計画の事前審査で同じ型が出た時):「指摘の内容が遷移するはず」「中央の致命的な
# バグから、端っこの細かいのに移るはず」「ある程度出たと判断したら進む形にしよう」「上限はいらないわ」。
# 書き換えていない所で新しく気づいた物は、前の回の読み手が全体を読んで詰まりに挙げなかった所(端に移った物)なので、
# 止めずに疑問か補完として書き手に返す。
FOLLOWUP_NOTE = """これは同じ投稿の書き直しの %d 回目の検査です。1 回目の読み手が本文の全体を読んで指摘を出し、書き手は回ごとに指摘を受けて本文を直しています。前の回に出た指摘と、前の回からの直しは次のとおりです。

--- 前の回の指摘 ---
%s
--- 書き手の直し(前の回の本文との差分。行頭の - は消した行、+ は足した行) ---
%s
--- ここまで ---

%s足した文の意味が取れていて、その中身(根拠・判断の材料・正しさ)を確かめたいだけなら、それも詰まりにせず疑問にする(書き手が答えようとして根拠を足すと、足した文がまた問われ、本文が膨らみ続ける)。
前の回の指摘に応えた直しを戻させる指摘(足した説明を冗長として削れ、など)は出さない。その直しで分かりにくくなったなら、そのことを詰まりとして書く。

"""
# 2 回目は、前の回から残った物と、直しが新しく生んだ物で止める
FOLLOWUP_OPEN = """この回で「詰まり: 」「なぞり: 」として報告するのは、次の 2 つだけ:
- 前の回の詰まり・なぞりのうち、今の本文でまだ解けていないもの(どの指摘かが分かるように、前の指摘の要点を引く)
- 直しで足した・書き換えた所(差分の + の行)が新しく生んだ詰まり・なぞり
書き換えていない所で新しく気づいたことは、詰まりにもなぞりにもせず、疑問か補完として報告する(1 回目の読み手が全体を読み、詰まりに挙げなかった所)。
"""
# CARRY_ONLY_ROUND 回目からは、前の回から残った物だけで止める。直しが新しく生んだ物も止めずに返す
FOLLOWUP_CARRY = """この回で「詰まり: 」「なぞり: 」として報告するのは、前の回に投稿を止めた指摘(詰まり・なぞり)のうち、今の本文でまだ解けていないものだけ。
その行は「詰まり: 」「なぞり: 」の直後に「(前の回)」と書き、どの指摘かが分かるように、前の指摘の要点を引く。解けた指摘は書かない。前の回に止めなかった指摘(疑問など)は、ここに挙げない。
直しで足した・書き換えた所が新しく生んだもの、書き換えていない所で新しく気づいたことは、詰まりにもなぞりにもせず、疑問か補完として報告する。
"""
CARRY_MARK = "(前の回)"
FOLLOWUP_DIFF_MAX = 8000   # 差分の上限(字)。超えた分は切る(本文の全体は下に在る)


def carried_only(found, prev, changed):
    """CARRY_ONLY_ROUND 回目からの仕分け。止めるフィールドの行は、ラベルの直後に前の回から残った印(CARRY_MARK)が有る物だけにし、
    ほかは疑問に移す。印の後ろが「無い」の意味だけの行は落とす。止める行の数は、本文を直していれば前の回の止めた数より
    1 つ少ない数までにし(多い分は疑問に移す)、直していなければ前の回の数までにする。

    読み手が依頼文に従わず新しい物を印付きで書いても、止める数は直すたびに減り、0 になれば通る——ゲートが自分で収まる
    (持ち主 2026-10-17「ある程度出たと判断したら進む形にしよう」「人からパスを売ってもらう運用はやめて」)。
    直さずに打ち直した本文では減らさない(打ち直すだけで通る口にしない)。"""
    prev_found = prev.get("found", {})
    room = sum(len(prev_found.get(label, [])) for label, stops in LABELS.items() if stops)
    if changed:
        room -= 1
    for label, stops in LABELS.items():
        if not stops:
            continue
        keep, moved = [], []
        for line in found[label]:
            rest = LABEL_RE.match(line)
            rest = line[rest.end():].strip() if rest else line
            if not rest.startswith(CARRY_MARK):
                moved.append(line)
            elif NONE_RE.match(rest[len(CARRY_MARK):].strip()):
                continue
            elif room > 0:
                keep.append(line)
                room -= 1
            else:
                moved.append(line)
        found["疑問"] += ["疑問: (止めない) " + line for line in moved]
        found[label] = keep
    return found


def followup_prompt(prompt, prev, body):
    """読み手の依頼文に、前の回の指摘と書き手の直しを足す(本文の始まりの印の手前に差し込む)。"""
    found = prev.get("found", {})
    stopped = "\n".join(line for label, stops in LABELS.items() if stops for line in found.get(label, []))
    kept = "\n".join(line for label, stops in LABELS.items() if not stops for line in found.get(label, []))
    findings = ("投稿を止めた指摘(詰まり・なぞり):\n%s\n止めなかった指摘(前の回の詰まり・なぞりではない):\n%s"
                % (stopped or "(なし)", kept or "(なし)"))
    diff = "\n".join(line for line in difflib.unified_diff(
        prev.get("body", "").splitlines(), body.splitlines(), lineterm="", n=1)
        if not line.startswith(("---", "+++")))
    round_no = prev.get("round", 1) + 1
    note = FOLLOWUP_NOTE % (round_no, findings,
                            clip(diff, FOLLOWUP_DIFF_MAX) if diff else "(前の回と同じ本文。直していない)",
                            FOLLOWUP_CARRY if round_no >= CARRY_ONLY_ROUND else FOLLOWUP_OPEN)
    return prompt[:-len(BODY_MARK)] + note + BODY_MARK


# 読み役のラベルと、投稿を止めるかどうか。依頼文が指示する綴りと 1 対 1 なので隣に置く——
# フィールドを増やすときに、指示と仕分けと止める/止めないが同じ画面で目に入る形にしておく。
# 「なぞり」(相手の言い回しを地の文に写した箇所)は画面モードにだけ在り、詰まりと同じく投稿を止める——
# 画面が既知にするのは指す先であって語彙ではない。詰まりの条件文の中に「相手の語で書けば詰まり」と
# 埋めた形は、実物の読み手(sonnet)に 1 件も拾われなかった(2026-09-07 に実測: 北極星・ニアバイ・
# クロージングを地の文に写した返信が詰まり 0 件)。独立のフィールドとして問う
LABELS = {"詰まり": True, "なぞり": True, "疑問": False, "補完": False, "冗長": False}
LABEL_RE = re.compile("(%s)\\s*[:：]" % "|".join(LABELS))
# ラベルの後ろが「無い」の意味だけの行は、そのフィールドの 0 件であって 1 件ではない。依頼文で「行ごと省け」と
# 言っても読み手は書く(2026-09-06 に実測: 画面モードの読み手が「詰まり: なし」と書き、837 字の
# 返信が詰まり 1 件として止まった)。ここで落とさないと、無いフィールドが投稿を止める
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
    """見出し付きのセクション。中身が無ければ空文字("".join の側でセクションごと落ちる)。"""
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


def deny_streak(session, target, fp=None, inspected=True):
    """同じ書き手(session)の同じ投稿が直近に続けて止められた (回数, その間の本文の長さの列, 止めた種別の列)。列は古い順。

    log は profile で共有なので、他の session の行は無いものとして飛ばす——数えると並行セッションの
    deny が自分の連続数を増やし、他所の skip が自分の案内を消す(2026-09-07 に実測)。同じ書き手でも
    別の投稿先の deny は数えない(長さの列が別の本文の混ざりになる)が、allow は投稿先に関わらず
    連続を切る。同じ投稿先でも、本文の指紋(fp)が似ていない deny に当たったら、そこで別の投稿と見て切る。
    session の無い入力は、同じく session の無い行だけを数える。
    別の版の deny に当たったら切る——前の版の回は読み方も前の回の記録(rounds/)の扱いも違うので、書き直しの回に
    足さない(0.22.3 の 1 回が 0.23.0 の回に足され、新しい版の 2 回目で「3 回続けて」と出た。2026-10-17 の works-factory)。
    inspected は読み手が本文を読んで止めた回(finding)を数えるか、読めずに止めた回(長すぎる・解析できない・本文を
    取り出せない・読み手が動かない・読み手の出力が報告の形でない)を数えるか。もう片方の回は飛ばす(切らない)。
    読めなかった回は書き直しの回ではない——前は、読んで止めた回が 3 回続いた後に本文を同じコマンドの中で書き換えて
    止まった回が、前の 3 回に足されて「4 回続けて止まった」と出た(2026-10-17)。読み手が動かない回も読んで止めた回に足されていた。
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
        if cols.get("v") != GATE_VERSION:
            break
        if cols.get("to", "-") != target:
            continue
        if ((parts[2] if len(parts) > 2 else "-") == "finding") != inspected:
            continue
        # 本文の近さは、読んで止めた回どうしでだけ比べる。読めなかった回は指紋の有る物(読み手が動かない)と無い物
        # (本文を取り出せない)が混ざるので、投稿先だけで数える(比べると並び方しだいで数が変わる)
        if inspected and not cols.get("fp"):
            continue
        if inspected and not same_post(fp, cols.get("fp")):
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
    教えない)。もう 1 つは、差し替えの分岐(COLDREAD_READER_CMD。CI が唯一叩く分岐)だけが stdin で
    渡していたので、テストが実運用の渡し方を覆っていなかった。
    stdin で足りることは実測済み: 2026-09-16 にこの環境(macOS・claude 2.1.273)で、同じ旗と
    claude_auth の認証のまま `-p` を引数なしで起動し、stdin の依頼に返答が返った。大きさの先例は
    graphloops の graph(774,021 バイトを stdin で通した実測。docs/loop-contract.md の T セクション)。
    """
    return [claude_bin, "-p",
            "--model", model or os.environ.get("COLDREAD_MODEL", "sonnet"),
            "--effort", effort or os.environ.get("COLDREAD_EFFORT", "medium"),
            # 読み役は本文を読んで報告するだけでツールは要らない。検査対象の文章そのものを
            # 渡すので、本文に紛れた指示で読み役が動く経路をここで断つ("" で全ツールを無効化)。
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


def run_reader(prompt: str, model=None, effort=None, timeout=READER_TIMEOUT):
    """読み役を起動して出力文字列を返す。prompt は依頼文+本文。model・effort・timeout は既定(投稿の読み役)を替えるときだけ渡す。失敗は例外。"""
    override = os.environ.get("COLDREAD_READER_CMD")
    note = None  # 採った認証の段。差し替えの分岐では認証に触らないので None のまま
    if override:
        # POSIX シェル文字列として sh -c で実行する。shell=True だと Windows では
        # cmd.exe に渡ってしまい、/dev/null 等が解決できない(GitHub Actions windows-latest で実測)。
        # **本文は bytes で渡す**(下の実運用の分岐も同じ)。encoding= を付けて str を渡すと、text mode の
        # 改行変換が働いて本文の \n が Windows で \r\n に化け、「書かれたとおり」読み役へ渡らない
        # (subprocess には newline を指定する口が無い。実測 2026-09-16: windows-latest だけで、
        # 単一引用の中の改行を保つ 1 件が赤かった——読み役には行末に \r が付いた本文が届いていた)。
        proc = subprocess.run(
            ["sh", "-c", override], input=prompt.encode("utf-8"),
            capture_output=True, timeout=timeout,
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
            capture_output=True, timeout=timeout,
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

# 往復の上限は置かず、持ち主に通させもしない(持ち主 2026-10-17「上限はいらないわ」「人からパスを売ってもらう運用はやめて」)。
# ゲートが自分で収まる: 2 回目の読み手は前の回の指摘と直しを見て、解けていない物と直しが持ち込んだ物だけで止め(FOLLOWUP_OPEN)、
# CARRY_ONLY_ROUND 回目からは前の回から残った物だけで止める(FOLLOWUP_CARRY・carried_only)。止める物は回を追って減る。
# 持ち主の決め「ある程度出たと判断したら進む形にしよう」(2026-10-17)。前は持ち主が「coldread-pass <番号>」を打って通す口を
# 置いたが、持ち主が会話で「通していい」と言っても機械が受け取れず、書き手が止まった(works-factory の PR #677、5 回)。
# 同じ投稿がこの回数続けて止まったら、収まらない合図として stuck.log に残す(ゲートの側を直す材料)。3 にしたのは、denies.log
# (2026-09〜10 の 4 profile)の連続の分布から: 1 回止まった後の次で通ったのは 301 本中 178 本、2 回止まった後の次で
# 通ったのは 94 本中 49 本、3 回止まった後の次で通ったのは 33 本中 2 本だった(前の回を知らない読み手のときの数)。
STUCK_MARK = 3
CARRY_ONLY_ROUND = 3   # この回からは、前の回から残った詰まり・なぞりだけで止める(2 回目に直しが持ち込んだ物まで見た後)
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


def same_post(fp_a, fp_b, need=FP_SAME):
    if not fp_a or not fp_b or len(fp_a) != len(fp_b):
        return True   # 指紋の無い行(本文を取り出せなかった deny)は、宛先だけで同じ投稿と見る
    return sum(fp_a[i:i + 4] == fp_b[i:i + 4] for i in range(0, len(fp_a), 4)) >= need


# 書き直しの回の記録。前の回の本文と指摘を、書き手(session)と投稿先の組ごとに 1 つ持つ(2 回目からの読み手に渡すため)。
# 本文を持つので log には書かず、組ごとの小さなファイルにして、通ったら消し、DENY_STREAK_WINDOW を過ぎた物は書くときに消す。
ROUND_DIR = os.path.join(STATE_DIR, "rounds")
# 前の回の記録を引き継ぐ本文の近さ(指紋 16 個中の一致数。推定の Jaccard ≥ 0.5)。続けて止まった数(FP_SAME)より厳しくする——
# 引き継ぐと書き換えていない所の新しい気づきで止めなくなるので、同じ宛先への別の投稿(見出しだけ共通の PR の型など)を
# 書き直しと取り違えると、別の投稿の検査が甘くなる。半分を超えて書き換えた本文は、1 回目として全体を読む
ROUND_SAME = 8


def _pair_key(session, target):
    return hashlib.sha256(("%s\0%s" % (session, target)).encode("utf-8")).hexdigest()


def _round_path(session, target):
    return os.path.join(ROUND_DIR, _pair_key(session, target)[:32] + ".json")


def load_round(session, target, fp):
    """同じ投稿の前の回の記録({round, body, found, fp, t, v})。無い・古い・別の版の・本文が似ていない(別の投稿)なら None。"""
    try:
        with open(_round_path(session, target), encoding="utf-8") as f:
            prev = json.load(f)
    except (OSError, ValueError):
        return None
    if not (isinstance(prev, dict) and isinstance(prev.get("t"), (int, float)) and isinstance(prev.get("body"), str)
            and isinstance(prev.get("found"), dict) and isinstance(prev.get("round"), int)):
        return None   # 壊れた記録は無いものとして、1 回目の読み方に戻る
    if (time.time() - prev["t"] > DENY_STREAK_WINDOW or prev.get("v") != GATE_VERSION
            or not same_post(fp, prev.get("fp"), ROUND_SAME)):
        return None   # 別の版の回は続けて止まった数にも足さない(deny_streak)ので、ここでも 1 回目から読み直す
    return prev


def save_round(session, target, fp, body, found, round_no):
    try:
        os.makedirs(ROUND_DIR, exist_ok=True)
        now = time.time()
        for name in os.listdir(ROUND_DIR):
            path = os.path.join(ROUND_DIR, name)
            try:
                if now - os.path.getmtime(path) > DENY_STREAK_WINDOW:
                    os.remove(path)
            except OSError:
                pass   # 消せない古い記録が 1 つ在っても、この回の記録は書く
        fd = os.open(_round_path(session, target), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)   # 本文を持つので本人だけが読める
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump({"round": round_no, "t": now, "v": GATE_VERSION, "fp": fp, "body": body, "found": found}, f,
                      ensure_ascii=False)
    except OSError:
        pass   # 記録できなくても検査は続く(次の回が 1 回目の読み方に戻るだけ)


def drop_round(session, target):
    try:
        os.remove(_round_path(session, target))
    except OSError:
        pass


def main() -> None:
    try:
        payload = json.load(sys.stdin)
        command = payload.get("tool_input", {}).get("command", "") or ""
    except Exception:
        allow()

    # 手元の文書のゲート: Bash が書いた文書を後で拾うために、走る前の文書の状態を控える(投稿の判定とは独立。
    # 失敗しても投稿のゲートを落とさない)
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

    # 読み役の中で自分がもう一度発火すると、読み役が読み役を起動する入れ子になる
    # (深さぶんの待ち時間になり、外側はフックのタイムアウトで無検査のまま通る)。
    # 読み役のツールを殺す --tools "" とは別の機構にしてある——あちらは「読み役が本文中の
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

    def stop(kind, message, length=None, fp=None, round_no=None):
        """deny して終わる。同じ投稿が STUCK_MARK 回続けて止まったら、記録に残し、この先の止まり方を先頭に添える。
        round_no は読み手が読んだ回(読んで止めたときだけ)。続けて止まった数(本文の近さが緩い)と回(前の回の記録を
        引き継ぐ近さが厳しい)はずれうるので、知らせは回に合わせる。"""
        inspected = kind.startswith("finding\t")
        n, lens, kinds = deny_streak(sid, target, fp, inspected)
        n, kinds = n + 1, kinds + [kind.split("\t", 1)[0]]
        if length is not None:
            lens.append(length)
        record("deny\t" + kind, "\tfp=%s" % fp if fp else "")
        if n >= STUCK_MARK:
            label_kind = target.split(":", 1)[0] if target.count(":") >= 2 else target
            log_line(STUCK_LOG, "sid=%s\tv=%s\tkind=%s\tn=%d\twhy=%s\tlens=%s" % (
                sid, GATE_VERSION, label_kind, n, ",".join(kinds), ",".join(map(str, lens)) or "-"))
            grown = ("。本文は %s 字と書き直された" % " → ".join("{:,}".format(x) for x in lens)
                     if len(lens) >= 2 and lens[-1] != lens[0] else "")
            message = ((
                ("【同じ投稿が %d 回続けて止まった%s】%d 回目の検査からは、前の回から残った詰まり・なぞりだけが投稿を止め、"
                 "止める数は直すたびに減る(新しく気づいた物は止めずに疑問として返る)。挙がった所だけを直して打ち直す。"
                 % (n, grown, CARRY_ONLY_ROUND)
                 if (round_no or 0) + 1 >= CARRY_ONLY_ROUND else
                 "【同じ投稿が %d 回続けて止まった%s】この回は前の回の記録を引き継げず(本文の半分を超えて書き換えた・"
                 "間が 30 分を超えた・版が替わった)、%d 回目の検査として読んだ。挙がった所だけを直して打ち直すと、"
                 "次の回から前の回の指摘を引き継ぎ、止める物が回を追って減る。" % (n, grown, round_no or 1))
                if inspected else
                "【同じ投稿が %d 回続けて、本文を読めずに止まった】読み手はまだ本文を読んでいない。下の理由"
                "(本文の渡し方か、読み手の起動)を先に直す。" % n)
                + "収まらない投稿は記録(coldread-gate/stuck.log)に残した。\n\n"
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

    # 素通しの疑いは判定より前に残す(止める分岐・通す分岐のどちらに進んでも数える)。残すのは当たった旗の綴りと
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
    # 待ち時間が本文の数だけ増える)。取りこぼしの受容は gates/README.md「Reach of the net (honest limits)」。
    body = max(bodies, key=len)
    fp = fingerprint(body)

    # 投稿先がスレッドなら、読み手が画面で既に見ているものを取って渡す。取れなければ
    # 文脈ゼロに倒す——検査は走らせ、画面に有るものへの詰まりは無視してよいと書き手に伝える
    # 投稿先の解釈で例外が出てもゲートを落とさない(落ちるとフックのクラッシュ=無検査で通る)。
    # 解釈できないときは文脈ゼロ側(厳しい側)へ倒れる
    try:
        target, dest = analysis.target_of(body)
    except Exception:
        target, dest = "-", None

    screen, screen_error, screen_note = None, None, ""
    sub, sub_args, sub_cwd = analysis.call_of(body)
    noun = NEW_ITEM_SUBS.get(sub) if dest is None else None
    if dest is not None:
        try:
            screen = screen_for(dest, cwd or "", body)
        except Exception as exc:
            screen_error = str(exc)[:120]
        if screen is None:
            screen_note = (
                "投稿先はスレッドだが、画面の中身(題・元の指摘・これまでの返信)を gh で取れなかった(%s)ので"
                "文脈ゼロで読んだ。画面に有るもの(PR/issue 番号・相手の名前・元の指摘)への詰まりは無視してよい。"
                % screen_error)
    elif noun:
        # 新しい PR/issue。画面を組む途中の失敗でゲートを落とさない(落ちると無検査で通る)
        try:
            screen, missed = new_item_screen(sub, sub_args, sub_cwd, body)
        except Exception as exc:
            missed = ["画面の全部(%s)" % str(exc)[:80]]
        if missed:
            screen_note = (
                "新しい %s の画面に出るもののうち、%s を gh で取れなかったので読み手に渡していない。"
                "それへの詰まりは無視してよい。" % (noun, "・".join(missed)))
    mode = ("new" if noun else "screen") if screen else "cold"

    # 同じ投稿の書き直しなら、前の回の指摘と直しを読み手に渡す(FOLLOWUP_NOTE)
    # 記録の読みで例外が出てもゲートを落とさない(落ちると無検査で通る)。1 回目の読み方に戻す
    prompt = reader_prompt(screen, noun)
    try:
        prev = load_round(sid, target, fp)
        if prev:
            prompt = followup_prompt(prompt, prev, body)
    except Exception:
        prev, prompt = None, reader_prompt(screen, noun)
    round_no = prev["round"] + 1 if prev else 1
    try:
        out = run_reader(prompt + body)
    except Exception as exc:
        # 読み役を起動できないときも止める。逃げ道は無いので、直らなければ持ち主に渡す
        stop("reader-down\t%d" % len(body),
             "外部投稿ゲート: coldreader(文脈ゼロの読み手)の起動に失敗した(%s)。\n" % str(exc)[:150]
             + "検査できていないので止めた。手で検査するなら skill『coldread』の手順で coldreader を立てること。\n"
             + OWNER_NOTE, len(body), fp)

    # **報告の形をしていない出力を「詰まりゼロ」と読まない。** 認証落ちは例外にならない——
    # 実測 2026-09-15: 素で起動した claude は『Failed to authenticate: OAuth session expired and
    # could not be refreshed』の 1 行を**標準出力に・終了コード 0 で**返した。rc も空出力も踏まないので
    # ここまで素通りし、ラベルが 1 つも無いまま allow に落ちていた(＝検査せずに投稿が出る fail-open)。
    # 依頼文が許す出力は CLEAN かラベル行の 2 種類だけなので、どちらでもなければ「検査できない」として止める。
    if not report_shaped(out):
        stop("reader-shape\t%d" % len(body),
             "外部投稿ゲート: coldreader の出力が報告の形(CLEAN かラベル行)をしていない: %r\n" % out[:150]
             + "検査できていないので止める(認証切れはこの形で出る——読み役の標準エラーを見よ)。\n"
             + OWNER_NOTE, len(body), fp)

    found = sort_findings(out)
    if round_no >= CARRY_ONLY_ROUND:
        found = carried_only(found, prev, body != prev.get("body"))
    blocking, questions, fills, redundant, traced = (
        found["詰まり"], found["疑問"], found["補完"], found["冗長"], found["なぞり"])

    # 詰まりとなぞりの有無だけで決める。以前は「最終行が CLEAN なら」も allow の条件だったが、
    # それだと詰まりを列挙した後に CLEAN と書かれた出力が通ってしまう。読み役に本文の
    # 説明以外を書かせるフィールド(補完)を足したぶん、末尾が CLEAN で終わる形は出やすくなっている。
    if not any(found[label] for label, stops in LABELS.items() if stops):
        record("allow\t%d\t%s" % (len(body), mode))
        drop_round(sid, target)
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

    role = {"screen": "この返信を受け取る相手として、スレッドの画面と本文を読んだ別プロセスの読み手",
            "new": "この %s を初めて開く人として、GitHub が本文の周りに出すものと本文を読んだ別プロセスの読み手" % noun,
            }.get(mode, "文脈ゼロの別プロセスの読み手")
    head = (
        "外部投稿ゲート: coldreader(%s)がこの本文で詰まった(%s)。詰まりを直してから同じ形で再実行すること"
        "(再実行時は新しい coldreader が、この回の指摘と直した差分を渡されて読み、回を追って止める物を絞る):"
        % (role, "%d 回目の検査。前の回から残った詰まり・なぞりだけで止めた(止める数は直すたびに減る)" % round_no
                 if round_no >= CARRY_ONLY_ROUND else
                 "%d 回目の検査。前の回の指摘が解けたかと、直しが持ち込んだ物だけを見た" % round_no if prev
                 else "1 回目の検査。本文の全体を読んだ")
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
    if mode == "screen":
        howto = (
            "直し方: 足すより削る。読み手は " + SCREEN_ITEMS + " を画面で見ているので、それらを本文で"
            "説明しない(説明は「冗長」として返る)。詰まりは画面と本文を合わせても解けないものだけなので、"
            "その語の初出 1 か所に中身を添える。相手の語は指してよいが、相手の語で書かない(相手の言い回しを"
            "地の文に写した箇所は、画面に同じ語が有っても「なぞり」として止まる。直し方は自分の言葉に置き換える)。")
    else:
        howto = (("" if prev else "直し方: 指摘の類型を言語化してから、同型を本文全体で掃討する(指摘された 1 箇所だけ直さない)。")
                 + ("読み手は " + NEW_SCREEN_ITEMS.get(noun, "") + " を画面で見ているので、それらを本文で説明し直さなくてよい。"
                    if mode == "new" else ""))
    # 2 回目からは、次の回の読み手が見る所(前の指摘と直した所)に直しを絞らせる。掃討で直していない所まで書き換えると、
    # 書き換えた所がみな次の回に読まれる
    if prev:
        howto = ("直し方: 挙がった所だけを直す(次の回の読み手は、この回の指摘が解けたかと、直した所だけを見る。"
                 "直していない所で新しく気づいた物では止めない)。") + howto
    save_round(sid, target, fp, body, found, round_no)
    stop("finding\t%d\t%s" % (len(body), mode),
         head + "\n\n" + detail[:1500]
         + "\n\n" + howto + "詳細は skill『coldread』。\n" + SCOPE_NOTE
         + ("\n" + screen_note if screen_note else ""),
         len(body), fp, round_no)


# ---- 手元の文書(書いた後に記録し、書いた役の終わりにまとめて読む) -----------------------------
# gh への投稿は出したら取り消せないので、書く前に止める(上の main)。手元の文書は書いた後でも直せるので止めない。
# 書くたびに読み手を起動すると、Edit のたびに待たされ、同じ文書を何度も読む(Vale も書いた後に走らせ、止めずに指摘を返す)。
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
#   ファイルの場所と、新しいサブエージェントに渡して直させるという短い知らせだけを返す。親の Stop はサブエージェントの記録を読まない。
# 直した文書は次の終わりにまた読まれ、同じ中身はハッシュで読み直さないので、直さなければ終わる(Claude Code も連続 8 回で打ち切る)。
# 投稿より読む数が多いので、読み手は速く安いモデル(既定 haiku)を effort high で走らせる。Anthropic の Effort の文書は
# Haiku 5.5 に「Use high for knowledge work, longer agent tasks, and strict instruction following. Use xhigh or max only
# where your evals show a quality gain」と書く(https://platform.claude.com/docs/en/build-with-claude/effort)。初見読みは
# 決まった書式の指示に従って文書を読む知識の仕事なので high。手元の測りでは決めない(持ち主の決まり)。
#
# 前から在る文書は、書き換えた所を含むセクションだけを読ませる(新しく作った文書は全体)。全体を読ませていた頃は、約 200 行の
# 設計の文書に数行足しただけで読み手が時間切れ(210 秒)になり、AGENTS.md の 1 文を直すたびに直していないセクションの前からの
# 疑問が 6〜14 件返って、直させるサブエージェントが「対象の文に指摘なし」で終わった(2026-10-16 に持ち主の会話で実測)。
# 前の版は、書いた役のその回で最初に記録したときの、書く前の中身にする(Write・Edit は PostToolUse の tool_response の
# originalFile。2026-10-16 に claude 2.1.300 で実測: Edit と Write の上書きは文字列、Write の新規は null と type "create")。
# 取れないツール(Bash・MCP)は、書く前の HEAD の版を指す(Bash は走る前の控えの HEAD)。HEAD に無い文書は新しい文書として全体を読む。
# 人が書いていない文書(.gitattributes の linguist-generated。GitHub Linguist の印で、Graphite も AI のレビューから外すのに
# 使う)は読まない。スクリプトがウェブから取った原文の写しを読んで、時間切れと指摘を出していた(2026-10-16 の docs.log)。
# 人が書いた文書でも、ほかの検査が受け持つ所(原文と照合する写しのノートなど)は .gitattributes の -coldread で外せる。
# 生成物の印は意味が違うので付けさせない。my_notes の reference/primary/ は 5 時間で 799 本読まれていた(2026-10-17 の測り)。
#
# 書いた役を呼び起こす(続けさせる・会話を呼び起こす)のは詰まりが在るときだけ。推測で埋めた箇所と疑問だけなら返さず、docs.log に
# 件数だけ残す(投稿のゲートもメインブランチに入れる前のゲートも、止めるのは詰まりだけで、手元の文書のゲートだけが推測で埋めた箇所でも
# 呼び起こしていた)。読み手は推測で埋めた箇所を理解を妨げなくても書くので、ほとんどの文書が CLEAN にならず、直すたびに直した
# セクションがまた読まれた(2026-10-17 の 5 時間で、詰まり 12 件に推測で埋めた箇所 395 件。直す回りが全体の使う量の 17%)。
# 詰まりが在るときは、推測で埋めた箇所と疑問も一緒に返す(書いた役はどのみち呼び起こされるので、誤読を知る機会は残る)。
DOC_EXTS = (".md", ".mdx", ".adoc", ".asciidoc", ".rst", ".txt")
DOC_MIN_LEN = int(os.environ.get("COLDREAD_DOC_MIN_LEN", "300"))   # これ未満の文書は読まない(字)
DOC_MODEL = os.environ.get("COLDREAD_DOC_MODEL", "haiku")
DOC_EFFORT = os.environ.get("COLDREAD_DOC_EFFORT", "high")
DOC_WORKERS = 4      # 1 回の終わりに読む文書を並べる数
# 手元の文書の読み役 1 回の上限。裏で読む口も待って読む口(サブエージェントの終わり・claude -p の終わり・手の read・ブランチのゲート)も同じにする。
# 待って読む口だけ投稿の読み役と同じ 210 秒で切っていた頃は、xhigh の読みが 210 秒を超える文書をサブエージェントが何度書き直しても
# 時間切れで指摘が出なかった(2026-10-17 に my_notes の約 8 千字のメモで、待って読む口は 210 秒で 6 回続けて切れ、裏の口は
# 同じメモを 299 秒・333 秒で読み終えた。docs.log の時間切れ 95 件は全部 210 秒の上限で、読み終えた読みの最長は 412 秒)。
# hooks.json の Stop・SubagentStop の timeout(900s)に、DOC_WORKERS 本ずつ 2 巡で収める
DOC_READ_TIMEOUT = 420
DOC_SEEN_KEEP = 5000  # 読んだ中身のハッシュを覚える数
DOC_FINDINGS_KEEP = 200  # 親に返す指摘を書き出したファイルを残す数(古いものから消す)
DOC_DIR = os.path.join(STATE_DIR, "docs")
DOC_LOG = os.path.join(STATE_DIR, "docs.log")
DOC_SEEN = os.path.join(DOC_DIR, "seen")
DOC_FINDINGS = os.path.join(DOC_DIR, "findings")
# 1 行目にこの印が在る文書は読まない(書き手が意図して置く逃げ道。印がファイルに残るので記録は要らない)。
# coldwrite(このゲートに移る前の、書く前に止めるゲート)の印もそのまま効かせる
DOC_SKIP_MARKS = ("coldread:skip", "coldwrite:skip")
DOC_BASE_DIR = os.path.join(DOC_DIR, "base")   # 書いた役ごとの、文書の前の版(またはその在り処)の控え
DOC_CONTEXT = 5        # 見出しの無い文書で、変えた行の前後に添える行数(さらに段落の切れ目まで広げる)
DOC_LEAD_MAX = 30      # 何の文書かを知るために添える冒頭(題と最初の段落)の行数の上限
DOC_WHOLE_RATIO = 0.8  # 抜き出しが全体の行数のこの割合以上なら、抜き出さずに全体を読ませる
# 書き換えた所を含むセクション(またぐなら、どれか 1 つのセクション)がこの字数を超えるなら、セクションを丸ごとでなく、セクションの見出しと、書き換えた段落・箇条だけを読ませる。
# 長いセクションを丸ごと読ませていた頃は、約 1 万 4 千字のセクション(works-dispatch の SKILL.md の「頼む・納品する」)の 2〜3 か所を
# 直しただけで、ブランチのゲートが回すたびに同じセクションの書き換えていない箇条から新しい詰まりを 1〜2 件出し、6 回目でやっと通った
# (2026-10-17。読み手の haiku は回ごとに拾う所が替わる)。2000 字はこのリポジトリの文書のセクションの 9 割が収まる長さ
# (2026-10-17 の測り: 3956 個のセクションの中央値 380 字・9 割 2019 字)で、短いセクションは今までどおり丸ごと読ませる
DOC_SECTION_MAX = 2000
GENERATED_ATTR = "linguist-generated"
SKIP_ATTR = "coldread"   # .gitattributes で -coldread(unset)にした文書は読まない
# 抜き出しを読ませるときに、依頼文の本文の印の手前に足す補足。観点(COLD_PROMPT)は変えず、読む範囲だけを言う。
# 省いたセクションで説明されている語まで詰まりに出すと、直していない所の前からの疑問が毎回返る形に戻るので、疑問に回させる
DOC_LEAD_LABEL = "【冒頭】"
DOC_HEAD_LABEL = "【セクションの見出し】"
DOC_PART_LABEL = "【書き換えた所】"
DOC_FOCUS_NOTE = ("補足: この本文は、長い文書のうち今回書き換えた所だけを抜き出したもの。「" + DOC_LEAD_LABEL
                  + "」の下は、何の文書かを知るために添えた文書の頭で、「" + DOC_HEAD_LABEL
                  + "」の下は、長いセクションから書き換えた段落・箇条だけを抜いたときに、どのセクションかを知るために添えた見出し。"
                  "どちらへの指摘も書かない。「" + DOC_PART_LABEL
                  + "」の下だけについて報告する。「(略)」は省いた所。省いた所で説明されているかもしれない語や参照が"
                  "分からないときは、詰まりではなく疑問にする。\n\n")


def docs_off():
    """手元の文書のゲートだけを切る(投稿のゲートは残す)。"""
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


# Bash・MCP のツールで書いた文書も拾う(持ち主の方針「防ぐより、ひっかける幅を増やす」)。Write・Edit の記録だけでは、
# cat > x.md <<EOF・tee・sed -i・python で書く文書が 1 本も読まれなかった。
# - Bash: 走る前(PreToolUse。投稿のゲートの main が呼ぶ)に、cwd の git の作業ツリーの変更一覧のうち文書の (mtime, 大きさ) を
#   控え、走った後(PostToolUse・PostToolUseFailure)に取り直して、増えた・変わった文書を記録に載せる。git の外と、git が
#   見ない文書(.gitignore の中)のために、中身をコマンドの字面に持つ書き込み先(ヒアドキュメント・echo・printf の行き先、
#   sed -i)も静的に拾う。ほかのコマンドの出力のリダイレクト先と cp/mv の行き先は写しなので、git の中の差からも外す(下の AUTHOR_CMDS)
# - MCP のツール: 名前が書くツールらしいもの(write・edit・create…)の入力の path のフィールドを拾う
# 同じ checkout を並行の会話が触っていると、その間の他人の書き込みも拾いうる。読むのは中身のハッシュで 1 回だけなので、
# 同じ中身を 2 つの会話が読むことは無いが、先に終わった方に指摘が返る(gates/README.md の射程)。
DOC_SNAP_DIR = os.path.join(DOC_DIR, "snap")
DOC_SNAP_KEEP = 24 * 3600   # 控えを残す秒数。投稿のゲートに止められた Bash は後のフックが走らないので、古い控えを消す
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
        if len(ent) < 4 or not ent[3:].lower().endswith(DOC_EXTS) or ent[:2] in UNMERGED:
            continue
        full = os.path.realpath(os.path.join(root, ent[3:]))   # porcelain のパスは作業ツリーのルートから
        try:
            st = os.stat(full)
        except OSError:
            continue   # 消された文書
        if stat.S_ISREG(st.st_mode):
            docs[full] = [st.st_mtime_ns, st.st_size]
    return docs


def _snap_file(payload):
    return os.path.join(DOC_SNAP_DIR, _safe(str(payload.get("tool_use_id") or "")) + ".json")


# 書いた役が書いた文書と、git が作業ツリーに持ち込んだ文書(リベース・merge・pull・checkout など)を分ける。
# フックの入力はツールの入力と出力だけで、Bash が変えたファイルは載らない(公式の hooks の文書の入力のフィールド)。だから git の記録で分ける:
# HEAD の移動の記録(reflog)の 1 件ごとの見出しは、移したコマンドが書く。git commit は「commit」「commit (initial)」
# 「commit (amend)」で、merge の後の commit は「commit (merge)」、cherry-pick・rebase の途中の commit は「commit (cherry-pick)」
# 「commit (rebase)」、rebase・pull・checkout などは呼んだコマンドの名前(GIT_REFLOG_ACTION。git 2.50.1 の builtin/commit.c)。
# 書いた役の書いた物と見るのは、前の 3 つの見出しの commit が変えた文書だけにする。前(0.18.0 まで)は走る前と後の HEAD の差を
# 丸ごと拾ったので、origin/main の上にリベースするとメインブランチから入った文書 6 本まで書いた文書として読み、書いていない役に直せない
# 指摘が積もった(2026-10-16 に割り振りの部署で実測。15 本のうち 6 本)。git が作業ツリーに書くコマンド(下の GIT_TREE_CMDS)を
# 走らせたか、HEAD を commit 以外で動かしたコマンドでは、変更一覧の差も git の持ち込みと見て拾わない(字面に中身の在る書き込み先は拾う)。
# 衝突して止まった文書(変更一覧の印 UU・AA など)は、いつも拾わない。書いた役が直して git add した後に、変わった文書として拾う
OWN_COMMIT_MSGS = ("commit", "commit (initial)", "commit (amend)")
GIT_TREE_CMDS = ("checkout", "restore", "reset", "rebase", "merge", "pull", "cherry-pick", "revert", "am", "apply", "stash")
GIT_VALUE_OPTS = ("-C", "-c", "--git-dir", "--work-tree", "--namespace", "--config-env")   # 値を次の語に取る git の旗
UNMERGED = ("DD", "AU", "UD", "UA", "DU", "AA", "UU")   # git status --porcelain の衝突の印(git-status の文書の Short Format)
REFLOG_MAX = 500   # 1 回のコマンドの間に足された移動を探す上限(長いリベースでも 1 commit に 1 件と数件)


def _reflog(root, n):
    """HEAD の移動の記録を新しい順に n 件まで [[移した先の commit, 時刻つきの位置, 見出し], …]。無い・取れなければ []。"""
    out = _git(["log", "-g", "-n", str(n), "--date=raw", "--format=%H%x1f%gd%x1f%gs%x1e", "HEAD", "--"], root)
    rows = [r.lstrip("\n").split("\x1f") for r in (out or b"").decode("utf-8", "replace").split("\x1e")]
    return [r for r in rows if len(r) == 3]


def _reflog_time(row):
    """HEAD の移動の記録の 1 件の時刻(秒)。位置は --date=raw で「HEAD@{1792183593 +0900}」。読めなければ 0。"""
    m = re.search(r"@\{(\d+)", row[1]) if row else None
    return int(m.group(1)) if m else 0


def _head_moves(snap):
    """走った間の HEAD の移動を ([(前, 後, 後の時刻, 前の時刻) — 書いた役の commit], commit 以外の移動が在ったか) に分ける。

    走る前の記録の頭(控えの reflog)より新しい分だけを見る。頭が見つからない(記録を消した・上限を超えた)ときは、
    分けられないので commit は拾わず、commit 以外の移動が在ったと見る(メインブランチの文書を読むより、読まない側に倒す)。
    """
    root, top = snap.get("root"), snap.get("reflog")
    rows = _reflog(root, REFLOG_MAX + 1)
    if top is None:
        new, before = rows, None   # 走る前は記録が無かった(最初の commit)
    elif top in rows:
        new, before = rows[:rows.index(top)], top[0]
    else:
        return [], bool(rows) and rows[0][0] != snap.get("head")
    steps, other = [], False
    for k, (sha, _, msg) in enumerate(new):
        old = new[k + 1][0] if k + 1 < len(new) else before
        if msg.split(": ", 1)[0] in OWN_COMMIT_MSGS:
            steps.append((old, sha, _reflog_time(new[k]), _reflog_time(new[k + 1] if k + 1 < len(new) else top)))
        else:
            other = True
    return steps[::-1], other


def _git_subcommand(args):
    """git の単純コマンドの引数(コマンド名の後)から、下位のコマンドの名前。無ければ ""。"""
    i = 0
    while i < len(args):
        a = args[i]
        if a in GIT_VALUE_OPTS:
            i += 2
        elif a.startswith("-"):
            i += 1
        else:
            return a
    return ""


# ---- 並べた役の書き分け ----
# 同じ checkout で役(同じ会話のサブエージェントどうし・親・並行の会話)が並んで動くと、ある役の Bash が走る間に、ほかの役が書いた
# 文書も変更一覧の差に出る。差で拾った物をそのまま走った役の物にしていた頃は、サブエージェント 7 本を並べた調べものの部署で、3 分
# かかる検査(python3 tools/check.py)を走らせたサブエージェントに、その間にほかの 4〜5 本が書いたノートの指摘が届き、受けた役は
# 受け持ちの外として直さずに終えた(2026-10-17 の docs.log とサブエージェントの記録で実測)。差は誰が書いたかを持たないので、二つの
# 帳面で見分ける:
# - 書いた印(DOC_CLAIMS): 記録に載せるたびに、役・文書・時刻を残す。Write・Edit・MCP のツール・字面に書き込み先の在る
#   Bash は書いた役が確かな印、差で拾って下の見分けを通った物も印にする
# - Bash の窓(DOC_WINDOWS と、走っている間の控え DOC_SNAP_DIR): 役・走り始めと終わり・字面に現れた文書の名前・
#   git commit を含むか
# 差で拾った文書は、(1) 走った間にほかの役の印が付いていれば、その役の物として外す。(2) 変わった時刻(mtime。commit で拾った
# 物は reflog の時刻)を含む窓がほかの役にも在れば、字面にその文書の名前が在る窓(commit で拾った物は git commit を含む窓)を
# 先に、次に後から走り始めた窓を選び、選んだ窓の役の物にする。同じ文書をどの役が見ても同じ窓が選ばれるので、届くのは 1 役だけ。
# 印が後から付く隙間(ほかの役の Write の後のフックが走る前に、この役が差を取った)のために、読む前にもう一度印を見て、
# 最後の印がほかの役なら読まない(最後に書いた役が読む)。
DOC_CLAIMS = os.path.join(DOC_DIR, "claims")
DOC_WINDOWS = os.path.join(DOC_DIR, "windows")
LEDGER_MAX = 1 << 20   # 帳面がこの大きさ(バイト)を超えたら、DOC_SNAP_KEEP より古い行を捨てて書き直す
COMMIT_RE = re.compile(r"\bgit\b[^\n;&|]*\bcommit\b")
DOC_NAME_RE = re.compile(r"[^\s'\"`<>|;&()=,]+")


def _role(session, agent):
    """役の名前(待ちの一覧と同じ)。"""
    return os.path.basename(_pending(session, agent))[:-len(".pending")]


def _ledger(path):
    """帳面の行(JSON)を読む。大きくなりすぎたら古い行を捨てる。読めなければ []。"""
    try:
        with open(path, encoding="utf-8") as f:
            rows = [json.loads(line) for line in f if line.strip()]
    except (OSError, ValueError):
        return []
    try:
        if os.path.getsize(path) > LEDGER_MAX:
            cut = time.time() - DOC_SNAP_KEEP
            rows = [r for r in rows if (r.get("t1") or r.get("t") or 0) >= cut]
            tmp = "%s.%d" % (path, os.getpid())
            with open(tmp, "w", encoding="utf-8") as f:
                f.write("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows))
            os.replace(tmp, path)
    except OSError:
        pass
    return rows


def _note(path, rows):
    try:
        os.makedirs(DOC_DIR, exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            f.write("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows))
    except OSError:
        pass   # 書けなければ見分けずに拾う側(前と同じ)に倒れる


def _named(command):
    """コマンドの字面に現れた文書の名前(小文字)。"""
    return sorted({os.path.basename(w).lower() for w in DOC_NAME_RE.findall(command) if w.lower().endswith(DOC_EXTS)})


def _windows(root):
    """root で走った・走っている Bash の窓。走っている窓のうち、同じ役が後から走り始めて終えた窓が在るもの(投稿のゲートに
    止められて後のフックが来なかった控え。役が終われば _drop_snaps が消す)は外す。"""
    done = [w for w in _ledger(DOC_WINDOWS) if w.get("root") == root]
    later = {}
    for w in done:
        later[w.get("r")] = max(later.get(w.get("r"), 0), w.get("t0", 0))
    live = []
    try:
        for e in os.scandir(DOC_SNAP_DIR):
            try:
                with open(e.path, encoding="utf-8") as f:
                    w = json.load(f)
            except (OSError, ValueError):
                continue
            if w.get("root") == root and w.get("r") is not None and later.get(w["r"], 0) <= w.get("t0", 0):
                live.append(dict(w, t1=None))
    except OSError:
        pass
    return done + live


def _drop_snaps(role):
    """終わった役の走る前の控えを消す。後のフックが来なかった控え(投稿のゲートや利用者に止められた Bash)を、走っている窓と
    見続けないため。"""
    try:
        for e in os.scandir(DOC_SNAP_DIR):
            try:
                with open(e.path, encoding="utf-8") as f:
                    mine = json.load(f).get("r") == role
                if mine:
                    os.remove(e.path)
            except (OSError, ValueError):
                continue
    except OSError:
        pass


def _theirs(snap, role, items, now):
    """差で拾った文書 items [(実パス, 変わった時刻, 印を見る下限, commit で拾ったか)] のうち、ほかの役が書いたと見る物の集合。"""
    if not items:
        return set()
    claims = _ledger(DOC_CLAIMS)
    me = {"r": role, "t0": snap.get("t0") or 0, "t1": now, "w": snap.get("w") or [], "c": bool(snap.get("c"))}
    wins = [me] + [w for w in _windows(snap["root"]) if w.get("r") != role]
    out = set()
    for path, when, lo, commit in items:
        if any(c.get("p") == path and c.get("r") != role and c.get("t", 0) >= lo for c in claims):
            out.add(path)
            continue
        span = 1 if commit else 0   # reflog の時刻は秒で切り捨て
        over = [w for w in wins if w.get("t0", 0) <= when + span and (w.get("t1") is None or w["t1"] >= when)]
        name = os.path.basename(path).lower()
        pick = max(over, key=lambda w: (bool(w.get("c")) if commit else name in (w.get("w") or ()), w.get("t0", 0)), default=me)
        if pick["r"] != role:
            out.add(path)
    return out


def docs_snapshot(payload):
    """PreToolUse(Bash): 走る前の、cwd の git の変更一覧の文書の状態を控える。git の外ならルートは None で、静的な読みだけになる。"""
    if docs_off() or payload.get("tool_name") != "Bash" or not payload.get("tool_use_id"):
        return
    t0 = time.time()   # 変更一覧を取る前の時刻。差に出る書き込みは、この後に起きている
    cwd = payload.get("cwd") or ""
    top = _git(["rev-parse", "--show-toplevel"], cwd) if os.path.isdir(cwd) else None
    root = top.decode("utf-8", "replace").strip() if top else None
    docs = _git_docs(root) if root else None
    head = _git(["rev-parse", "--verify", "-q", "HEAD"], root) if docs is not None else None   # 書く前の版の在り処
    last = _reflog(root, 1) if docs is not None else []   # 走る前の HEAD の移動の記録の頭(走った間に足された分を見分ける)
    os.makedirs(DOC_SNAP_DIR, exist_ok=True)
    now = time.time()
    for e in os.scandir(DOC_SNAP_DIR):
        try:
            if now - e.stat().st_mtime > DOC_SNAP_KEEP:
                os.remove(e.path)
        except OSError:
            pass
    command = (payload.get("tool_input") or {}).get("command") or ""
    with open(_snap_file(payload), "w", encoding="utf-8") as f:
        json.dump({"root": root if docs is not None else None, "docs": docs or {},
                   "head": head.decode("ascii", "replace").strip() if head else None,
                   "reflog": last[0] if last else None,
                   "r": _role(*_who(payload)), "t0": t0, "w": _named(command), "c": bool(COMMIT_RE.search(command))}, f)


# Bash の書き込み先のうち、人(書いた役)が書いた文書と見るのは、中身がコマンドの字面に在るものだけにする:
# ヒアドキュメント・ヒア文字列を受けたコマンドの書き込み先、echo・printf の書き込み先、それらをパイプで受けた tee・cat の行き先、
# sed -i の書き換え。ほかのコマンドの出力をリダイレクトした先(`sed -n … ci.log > x.txt`・`git log > x.txt`)と cp・mv・install の
# 行き先は、中身がコマンドの外から来る写しなので読まない。git の作業ツリーの中でも、変更一覧の差から外す。
# 前(0.14.0)は書き込み先を全部拾い、CI のログの抜粋を一時の置き場に書いた .txt を読み手が文書として読んで、詰まりを返した
# (2026-10-16 に窓口の会話で実測)。字面に書き込み先が現れない書き方(python の中で書く)は、git の中の差でだけ拾う
AUTHOR_CMDS = ("echo", "printf")   # 引数が中身
PASS_CMDS = ("cat", "tee")         # 受けた中身をそのまま書く


def _written_by_command(command, cwd):
    """コマンドの書き込み先の文書の実パスを、(書いた文書, 外から来た中身の写し, git が作業ツリーを書くコマンドが在るか) に分ける。

    書いた文書は在るものだけ。
    """
    norm, heredoc_bodies = prepare(command)
    tokens = tokenize(norm)
    if tokens is None:
        return [], [], False
    cmds = split_commands(tokens)
    files = BodyFiles(cmds, cwd, heredoc_bodies, norm, tokens)
    wrote, copied, git_tree = [], [], False
    authored_prev = False   # パイプの前のコマンドが、中身を字面に持つコマンドだったか
    for k, c in enumerate(cmds):
        at = command_start(c.args)
        f = files.at(k, c.args[:at])
        name = os.path.basename(c.args[at]) if at < len(c.args) else ""
        rest = [a for a in c.args[at + 1:] if not a.startswith("-")]
        piped = bool(c.ops) and c.ops[-1][0] == "|"
        git_tree = git_tree or (name == "git" and _git_subcommand(c.args[at + 1:]) in GIT_TREE_CMDS)
        # ヒアドキュメントを受けても、python・sh などはそれを台本として走らせるので、出力は台本の書いた中身ではない
        fed = (any("__HEREDOC" in a for a in c.args) or any(op == "<<<" for op, _ in c.redirects)
               or (piped and authored_prev))
        authored = name in AUTHOR_CMDS or (name in PASS_CMDS and fed)
        mine, theirs = [], []
        dests = [d for op, d in c.redirects if op in WRITE_OPS]
        if name == "tee":
            dests += [a for a in rest if "__HEREDOC" not in a]
        (mine if authored else theirs).extend(dests)
        if name in ("sed", "gsed") and any(a.startswith(("-i", "--in-place")) for a in c.args[at + 1:]):
            mine += [a for a in rest if a.lower().endswith(DOC_EXTS)]
        elif name in ("cp", "mv", "install") and len(rest) >= 2:
            theirs += [rest[-1]] + [os.path.join(rest[-1], os.path.basename(s)) for s in rest[:-1]]
        for d in mine:
            p = f.path(d)
            if p and p.lower().endswith(DOC_EXTS) and os.path.isfile(p):
                wrote.append(p)
        for d in theirs:
            p = f.path(d)
            if p and p.lower().endswith(DOC_EXTS):
                copied.append(os.path.realpath(p))
        authored_prev = authored
    return wrote, copied, git_tree


def _bash_docs(payload):
    """PostToolUse(Bash): (書いた文書, 走る前の控え, {書いた役の commit で拾った文書: その commit の前の版})。

    書いた文書は、控えと取り直しの差で増えた・変わった文書と、走った間の書いた役の commit が変えた文書と、
    コマンドの書き込み先の文書。git が作業ツリーに持ち込んだ分は外す(上の OWN_COMMIT_MSGS の注)。
    """
    found, commits, snap, bases, moved, items = [], [], None, {}, False, []
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
            items += [(p, now[p][0] / 1e9, snap.get("t0") or 0, False) for p in found]
        # 同じコマンドの中で書いて commit した文書は、変更一覧から消えている。HEAD が動いたなら、動いた間の書いた役の
        # commit ごとの差の文書も拾う(リベース・merge・checkout などで動いた分は拾わない)
        head = _git(["rev-parse", "--verify", "-q", "HEAD"], snap["root"])
        if (head or b"").decode("ascii", "replace").strip() != (snap.get("head") or "") or snap.get("reflog") is None:
            steps, moved = _head_moves(snap)
            for old, new, when, lo in steps:
                diff = (_git(["diff", "--name-only", "-z", "--no-renames", old, new, "--"], snap["root"]) if old else
                        _git(["diff-tree", "-r", "--root", "--no-commit-id", "--name-only", "-z", "--no-renames", new],
                             snap["root"]))
                for rel in (diff or b"").decode("utf-8", "replace").split("\0"):
                    full = os.path.realpath(os.path.join(snap["root"], rel)) if rel.lower().endswith(DOC_EXTS) else ""
                    if full and os.path.isfile(full):
                        commits.append(full)
                        bases.setdefault(full, old)
                        # 走った間に書き換わった文書は、変更一覧の差と同じに見る(mtime と走り始め)。前から在った変更を
                        # commit しただけなら、前の HEAD の移動からの印と、commit の時刻を含む窓で見る
                        t0 = snap.get("t0") or 0
                        try:
                            mt = os.stat(full).st_mtime
                        except OSError:
                            mt = 0
                        items.append((full, mt, t0, False) if mt >= t0 else (full, when, lo, True))
    command = (payload.get("tool_input") or {}).get("command") or ""
    try:
        wrote, copied, git_tree = _written_by_command(command, payload.get("cwd") or None)
    except Exception:
        wrote, copied, git_tree = [], [], False   # 静的な読みの失敗で記録の口を落とさない(手元の文書は止めない側)
    if moved or git_tree:
        found = []   # 変更一覧の差は git の持ち込みと見る
    skip = set(copied) - {os.path.realpath(p) for p in wrote}
    if snap and snap.get("root"):
        now_t = time.time()
        live = set(found + commits)
        try:
            skip |= _theirs(snap, snap.get("r") or _role(*_who(payload)), [i for i in items if i[0] in live], now_t)
        except Exception:
            pass   # 見分けの失敗で記録の口を落とさない(見分けずに拾う)
        _note(DOC_WINDOWS, [{"root": snap["root"], "r": snap.get("r") or _role(*_who(payload)), "t0": snap.get("t0") or 0,
                             "t1": now_t, "w": snap.get("w") or [], "c": bool(snap.get("c"))}])
    found = [p for p in found + commits if os.path.realpath(p) not in skip] + wrote
    return found, snap, bases


def _tool_docs(payload):
    """Write・Edit・NotebookEdit と MCP の書くツールの入力の path のフィールド。"""
    tool = str(payload.get("tool_name") or "")
    ti = payload.get("tool_input") or {}
    if tool.startswith("mcp__") and not MCP_WRITE_RE.search(tool.rsplit("__", 1)[-1]):
        return []
    if tool.startswith("mcp__"):
        return [os.path.realpath(v) for v in (ti.get(k) for k in PATH_KEYS) if isinstance(v, str) and v]
    return [os.path.abspath(v) for v in (ti.get(k) for k in ("file_path", "notebook_path")) if isinstance(v, str) and v]


def _base_dir(session, agent):
    """書いた役ごとの、前の版の控えの置き場(待ちの一覧と同じ名前)。"""
    return os.path.join(DOC_BASE_DIR, os.path.basename(_pending(session, agent))[:-len(".pending")])


def _base_file(where, path):
    return os.path.join(where, hashlib.sha256(os.path.realpath(path).encode("utf-8")).hexdigest()[:40] + ".json")


def _rev_entry(path, root=None, head=None):
    """文書の HEAD の版の在り処 {"rev", "root", "rel"}。git の外・HEAD の無い checkout・作業ツリーの外なら {}(全体を読む)。"""
    if not (root and head):
        out = _git(["rev-parse", "--show-toplevel", "--verify", "-q", "HEAD"], os.path.dirname(path) or ".")
        lines = out.decode("utf-8", "replace").split("\n") if out else []
        if len(lines) < 2 or not lines[1].strip():
            return {}
        root, head = lines[0].strip(), lines[1].strip()
    try:
        rel = os.path.relpath(os.path.realpath(path), os.path.realpath(root))
    except ValueError:   # Windows で別のドライブ
        return {}
    if rel == os.pardir or rel.startswith(os.pardir + os.sep) or os.path.isabs(rel):
        return {}
    return {"rev": head, "root": root, "rel": rel.replace(os.sep, "/")}


def _keep_base(where, path, entry):
    """前の版の控えを、その回で最初に記録したときのものだけ残す(後から書いた分で上書きしない。O_EXCL なので並行でも 1 つ)。"""
    try:
        os.makedirs(where, exist_ok=True)
        with open(_base_file(where, path), "x", encoding="utf-8") as f:
            json.dump(entry, f, ensure_ascii=False)
    except OSError:
        pass   # 在る(先に記録した版が勝つ)か、書けない(全体を読む側に倒れる)


def _prune_bases():
    """終わりが来ずに残った控え(会話を閉じた等)を、走る前の控えと同じ秒数で消す。"""
    now = time.time()
    try:
        for e in os.scandir(DOC_BASE_DIR):
            if now - e.stat().st_mtime > DOC_SNAP_KEEP:
                shutil.rmtree(e.path, ignore_errors=True)
    except OSError:
        pass


def docs_record(payload):
    """PostToolUse: 書いた文書のパスを書いた役の待ちの一覧に足し、書く前の版(の在り処)を控える。読まない・止めない。"""
    tool = payload.get("tool_name")
    snap = None
    bases = {}
    if tool == "Bash":
        paths, snap, bases = _bash_docs(payload)
    else:
        paths = _tool_docs(payload)
    paths = [p for p in dict.fromkeys(paths) if p.lower().endswith(DOC_EXTS)]
    if not paths:
        return
    try:
        os.makedirs(DOC_DIR, exist_ok=True)
        with open(_pending(*_who(payload)), "a", encoding="utf-8") as f:
            f.write("".join(p + "\n" for p in paths))
    except OSError:
        return
    now = time.time()
    _note(DOC_CLAIMS, [{"p": os.path.realpath(p), "r": _role(*_who(payload)), "t": now} for p in paths])
    _prune_bases()
    where = _base_dir(*_who(payload))
    resp = payload.get("tool_response") if isinstance(payload.get("tool_response"), dict) else {}
    for p in paths:
        if os.path.exists(_base_file(where, p)):
            continue   # この回の前の版はもう控えてある(git を呼ばずに済ませる)
        if isinstance(resp.get("originalFile"), str):
            entry = {"text": resp["originalFile"]}
        elif resp.get("type") == "create":
            entry = {}   # Write で新しく作った文書
        elif p in bases:
            entry = _rev_entry(p, snap["root"], bases[p]) if bases[p] else {}   # 書いた役の commit の前の版(最初の commit なら全体)
        elif snap and snap.get("root") and snap.get("head"):
            entry = _rev_entry(p, snap["root"], snap["head"])
        else:
            entry = _rev_entry(p)
        _keep_base(where, p, entry)


def _seen():
    return set(_seen_list())


def _remember(digests):
    if not digests:
        return
    try:
        lines = [*_seen_list(), *digests][-DOC_SEEN_KEEP:]
        tmp = "%s.%d.tmp" % (DOC_SEEN, os.getpid())   # 並んだ読みどうしで同じ一時のファイルを取り合わない
        with open(tmp, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
        os.replace(tmp, DOC_SEEN)
    except OSError:
        pass


def _forget(digests):
    """覚えた中身のハッシュから digests を外す(読む前に覚えたが、読めなかった物)。"""
    if not digests:
        return
    drop = set(digests)
    try:
        lines = [d for d in _seen_list() if d not in drop]
        tmp = "%s.%d.tmp" % (DOC_SEEN, os.getpid())   # 並んだ読みどうしで同じ一時のファイルを取り合わない
        with open(tmp, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + ("\n" if lines else ""))
        os.replace(tmp, DOC_SEEN)
    except OSError:
        pass


def _seen_list():
    try:
        with open(DOC_SEEN, encoding="utf-8") as f:
            return f.read().split()
    except OSError:
        return []


def _tmp_roots():
    """一時の置き場のルートの集合(正規化した綴りと実パスの両方)。

    既定は Python の tempfile が一時フォルダを選ぶ候補(環境変数 TMPDIR・TEMP・TMP と OS の決まった場所。最後の候補の
    カレントディレクトリは除く)と、実際に選んだ tempfile.gettempdir()。gettempdir() だけでは足りない: macOS では
    TMPDIR が /var/folders/… を指し、Claude Code の scratchpad(/private/tmp/claude-<uid>/…)は /tmp の下にある
    (2026-10-16 に実測)。macOS の /tmp → /private/tmp・/var → /private/var のように綴りと実体が違うので、両方を持つ。
    COLDREAD_TMP_DIRS(os.pathsep 区切り)が在れば、既定の代わりにそれを使う(試験は一時フォルダの下で走るので)。
    """
    raw = os.environ.get("COLDREAD_TMP_DIRS")
    if raw is not None:
        dirs = raw.split(os.pathsep)
    else:
        dirs = [tempfile.gettempdir()] + [os.environ.get(k) for k in ("TMPDIR", "TEMP", "TMP")]
        if os.name == "nt":
            dirs += [os.path.expanduser(r"~\AppData\Local\Temp"), os.path.expandvars(r"%SYSTEMROOT%\Temp")]
        else:
            dirs += ["/tmp", "/var/tmp", "/usr/tmp"]
    return {os.path.normcase(f(d)) for d in dirs if d for f in (os.path.abspath, os.path.realpath)}


def _job_tmp(p, jobs_roots):
    """正規化したパス p が、Claude Code の会話ごとの一時の置き場 <jobs>/<会話の id>/tmp の下か。

    場所の決まりは公式の文書(agent-view「Where state is stored」の `~/.claude/jobs/<id>/tmp/`「Per-session scratch
    directory」と、env-vars の CLAUDE_JOB_DIR。2026-10-16 に確認)。jobs は設定の置き場(CLAUDE_CONFIG_DIR)の下。
    0.16.0 の一時の置き場のルートはこれを含まず、部署が納品のために書く要約(jobs/<id>/tmp/summary.md など)を読んでいた
    (2026-10-16 の docs.log)。会話の id ごとに置き場が在るので、ルートの集合でなく形で見る。
    """
    for jobs in jobs_roots:
        try:
            rel = os.path.relpath(p, jobs)
        except ValueError:   # Windows で別のドライブ
            continue
        parts = rel.split(os.sep)
        if parts[0] != os.pardir and len(parts) >= 3 and parts[1] == "tmp":
            return True
    return False


def _scratch(path):
    """git の作業ツリーの外で、一時の置き場の下に在るファイルか(書いた役が自分のために置いた写し・頼みの文書。読まない)。"""
    roots = _tmp_roots()
    job_dir = os.environ.get("CLAUDE_JOB_DIR")   # 会話が jobs の外に置かれても、その会話の分はルートとして見る
    if job_dir:
        roots |= {os.path.normcase(f(os.path.join(job_dir, "tmp"))) for f in (os.path.abspath, os.path.realpath)}
    jobs = os.path.join(CONFIG_DIR, "jobs")
    jobs_roots = {os.path.normcase(f(jobs)) for f in (os.path.abspath, os.path.realpath)}
    under = False
    for p in {os.path.normcase(os.path.abspath(path)), os.path.normcase(os.path.realpath(path))}:
        under = under or _job_tmp(p, jobs_roots)
        for r in roots:
            try:
                under = under or os.path.commonpath([p, r]) == r
            except ValueError:   # Windows で別のドライブ
                pass
    if not under:
        return False
    # 一時の置き場の下でも、git の作業ツリーの中なら人に見せる文書として読む。git が無い・時間切れなら外と見る
    d = os.path.dirname(os.path.abspath(path))
    return not (os.path.isdir(d) and _git(["rev-parse", "--show-toplevel"], d))


def doc_to_read(path, seen):
    """読むなら (本文, 中身のハッシュ)、読まないなら (None, 理由)。"""
    if _scratch(path):
        return None, "一時の置き場(git の外)"
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


def doc_prompt(body, focus=False):
    """読み手に渡す依頼文+本文。抜き出し(focus)なら、本文の印の手前に読む範囲の補足を足す。"""
    if not focus:
        return COLD_PROMPT + body
    return COLD_PROMPT[:-len(BODY_MARK)] + DOC_FOCUS_NOTE + BODY_MARK + body


def read_doc(text, focus=False, timeout=DOC_READ_TIMEOUT):
    """文書を 1 本、投稿と同じ観点(COLD_PROMPT)で読ませて、ラベルごとの行を返す。報告の形でなければ例外。"""
    out = run_reader(doc_prompt(text, focus), model=DOC_MODEL, effort=DOC_EFFORT, timeout=timeout)
    if not report_shaped(out):
        raise RuntimeError("報告の形(CLEAN かラベル行)をしていない: %r" % out[:150])
    return sort_findings(out)


# ---- 書き換えた所の抜き出し ----
# セクションは見出しから次の見出しの手前まで(深さは見ない。いちばん内側のセクション)。見出しの書き方は拡張子で決める:
# md・mdx は ATX(# 〜 ######。コードの囲みと冒頭の frontmatter の中は見ない)、adoc は = 〜 ======、rst は下線
# (と上線)付きの行。txt と、見出しの無い文書は、変えた行の前後 DOC_CONTEXT 行を段落の切れ目まで広げる。
# DOC_SECTION_MAX 字を超えるセクションは、セクションの見出しと、変えた行を含む段落・箇条だけにする(_block)
_MD_HEAD = re.compile(r" {0,3}#{1,6}(?:[ \t]|$)")
_MD_FENCE = re.compile(r" {0,3}(`{3,}|~{3,})")
_ADOC_HEAD = re.compile(r"={1,6}[ \t]+\S")
_RST_RULE = re.compile(r"""([=\-~^"'`#*+:.])\1+[ \t]*$""")
_ITEM = re.compile(r"(?:[-*+]|\d{1,9}[.)])[ \t]")   # 字下げの無い箇条の頭(字下げした箇条は、何の箇条かが分かるよう親の箇条に含める)


def _front_end(lines):
    """冒頭の frontmatter(--- で挟んだ行)の次の行。無ければ 0。"""
    if lines and lines[0].strip() == "---":
        for k in range(1, len(lines)):
            if lines[k].strip() in ("---", "..."):
                return k + 1
    return 0


def _sections(lines, ext):
    """(セクションの始まりの行の並び, 見出しを成す行の集まり)。"""
    starts, marks = [], set()
    if ext in (".md", ".mdx"):
        fence = None
        for k in range(_front_end(lines), len(lines)):
            m = _MD_FENCE.match(lines[k])
            if m:
                mark = m.group(1)[0]
                fence = mark if fence is None else (None if fence == mark else fence)
            elif fence is None and _MD_HEAD.match(lines[k]):
                starts.append(k)
                marks.add(k)
    elif ext in (".adoc", ".asciidoc"):
        for k, line in enumerate(lines):
            if _ADOC_HEAD.match(line):
                starts.append(k)
                marks.add(k)
    elif ext == ".rst":
        for k in range(len(lines) - 1):
            title, rule = lines[k], lines[k + 1]
            if (title.strip() and not _RST_RULE.match(title) and _RST_RULE.match(rule)
                    and len(rule.rstrip()) >= len(title.rstrip())):
                over = k > 0 and _RST_RULE.match(lines[k - 1]) and lines[k - 1].strip()[:1] == rule.strip()[:1]
                start = k - 1 if over else k
                if not starts or starts[-1] < start:
                    starts.append(start)
                    marks.update((start, k, k + 1))
    return starts, marks


WORD_SWAP_MAX = 12   # 語の置き換えだけの行と見る、手で選んだ語の 1 か所の字数の上限(「fast-forward」が 12 字)
# 手で選んだ語に使える字(片仮名・英数字・ハイフン・空白)。漢字と仮名を許すと「ブランチ以外」「ではなく」のように意味を足せる
WORD_SWAP_CHARS = re.compile(r"[\u30a1-\u30faー\uff66-\uff9fA-Za-z0-9\- ]+")


def _script(ch):
    """字の種類(漢字は 1、片仮名は 2、ほかは 0)。"""
    return 1 if "\u3400" <= ch <= "\u9fff" else 2 if "\u30a1" <= ch <= "\u30ff" else 0


def _word_span(text, a, b):
    """置き換えが変えた字の範囲 [a, b) を、両端と同じ種類(漢字・片仮名)の字の続く所まで広げた範囲。字の単位の比べは前後の版に
    共通の字を残す(「旧語」→「新語」は「旧」だけが変わる)ので、語の単位にそろえる。"""
    if a < b:
        while a > 0 and _script(text[a]) and _script(text[a - 1]) == _script(text[a]):
            a -= 1
        while b < len(text) and _script(text[b - 1]) and _script(text[b]) == _script(text[b - 1]):
            b += 1
    return a, b


def _same_words(old, fixed, new):
    """今の行 new が、前の行 old のうち置き換え(old を置き換えた fixed)が変えた語の所だけを、別の語にした行か。置き換えの結果と違う
    語を手で選んだ行(グラフの「節」を、置き換えの「セクション」でなく「ノード」にした)も、語の所の外を変えず、選んだ語が片仮名・英数字
    だけ(WORD_SWAP_CHARS)なら同じと見る。語を消しただけの所と、漢字・仮名を足した所は書き換えに数える。"""
    if fixed == new:
        return True
    spans = [_word_span(old, i1, i2) for tag, i1, i2, _j1, _j2
             in difflib.SequenceMatcher(None, old, fixed, autojunk=False).get_opcodes() if tag != "equal"]
    if not spans:
        return False
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, old, new, autojunk=False).get_opcodes():
        word = new[j1:j2]
        if tag != "equal" and (len(word) > WORD_SWAP_MAX or not WORD_SWAP_CHARS.fullmatch(word)
                               or not any(a <= i1 and i2 <= b for a, b in spans)):
            return False
    return True


def _changed(base_lines, lines, fixed=None):
    """今の版で書き換えた行の範囲 [(始め, 終わり)]。消しただけの所は、その前後の行。fixed は base_lines を語の置き換え
    (branch-check の --fixer)に通した行の並び(base_lines と同じ数)で、語の置き換えだけの行(_same_words)は書き換えに数えない。"""
    n, out = len(lines), []

    def mark(j1, j2):
        out.append((j1, j2) if j2 > j1 else (max(0, j1 - 1), min(n, j1 + 1)))

    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, base_lines, lines, autojunk=False).get_opcodes():
        if tag == "equal":
            continue
        if fixed is None or tag != "replace":
            mark(j1, j2)
            continue
        # 書き換えた所の中を、置き換えた前の行ともう一度比べ、行の数がそろう所は 1 行ずつ語の置き換えだけの行かを見る
        sub = difflib.SequenceMatcher(None, fixed[i1:i2], lines[j1:j2], autojunk=False)
        for t, a1, a2, b1, b2 in sub.get_opcodes():
            if t == "replace" and a2 - a1 == b2 - b1:
                for k in range(a2 - a1):
                    if not _same_words(base_lines[i1 + a1 + k], fixed[i1 + a1 + k], lines[j1 + b1 + k]):
                        mark(j1 + b1 + k, j1 + b1 + k + 1)
            elif t != "equal":
                mark(j1 + b1, j1 + b2)
    return [(a, b) for a, b in out if b > a]


def _paragraph(lines, a, b):
    """[a, b) を前後 DOC_CONTEXT 行広げ、さらに段落の切れ目(空行)まで広げる(広げるのは片側 20 行まで)。"""
    n = len(lines)
    a, b = max(0, a - DOC_CONTEXT), min(n, b + DOC_CONTEXT)
    for _ in range(20):
        if a > 0 and lines[a - 1].strip():
            a -= 1
    for _ in range(20):
        if b < n and lines[b].strip():
            b += 1
    return a, b


def _block(lines, marks, a, b, sa, sb):
    """セクション [sa, sb) の中で、書き換えた行 [a, b) を含む段落・箇条の範囲。見出し・字下げの無い箇条の頭と、空行の後の
    字下げの無い行で切る(空行の後でも字下げした行は、前の箇条の続き)。コードの囲みの中では切らない。"""
    starts, fence, cut = [], None, True
    for k in range(sa, sb):
        line = lines[k]
        m = _MD_FENCE.match(line)
        if fence is not None:
            if m and m.group(1)[0] == fence:
                fence = None
            continue
        if not line.strip():
            cut = True
            continue
        if (cut and not line[:1].isspace()) or k in marks or _ITEM.match(line):
            starts.append(k)
        cut = k in marks
        if m:
            fence = m.group(1)[0]
    i, j = bisect.bisect_right(starts, a) - 1, bisect.bisect_right(starts, b - 1)
    return starts[i] if i >= 0 else sa, starts[j] if j < len(starts) else sb


def _lead(lines, marks):
    """何の文書かを知るために添える冒頭(frontmatter の後の、題と最初の段落)。"""
    start = j = _front_end(lines)
    n = len(lines)
    while j < n and (not lines[j].strip() or j in marks):
        j += 1
    while j < n and lines[j].strip() and j not in marks:
        j += 1
    return start, min(j, start + DOC_LEAD_MAX)


def doc_excerpt(path, text, base, fixer=None):
    """前の版 base から書き換えた所を含むセクション(長いセクションはセクションの見出しと書き換えた段落・箇条)と冒頭を抜き出した本文。全体を読ませるなら None、書き換えが無ければ ""。
    fixer は語の置き換え(本文を受けて置き換えた本文を返す。branch-check の --fixer)で、前の行を置き換えた結果と同じ行は書き換えに数えない。"""
    if not base:
        return None
    base = base.replace("\r\n", "\n")
    lines, base_lines = text.split("\n"), base.split("\n")
    fixed = fixer(base).split("\n") if fixer else None
    if fixed is not None and len(fixed) != len(base_lines):
        log_line(DOC_LOG, "fixer-lines\t%d → %d 行で、置き換えを当てない\t%s" % (len(base_lines), len(fixed), path))
        fixed = None
    touched = _changed(base_lines, lines, fixed)
    if not touched:
        return ""
    n = len(lines)
    starts, marks = _sections(lines, os.path.splitext(path)[1].lower())
    spans = []   # (始め, 終わり, 種類)。種類は 0 が冒頭、1 がセクションの見出し、2 が書き換えた所
    for a, b in touched:
        if starts:   # 範囲の頭の行が入るセクションの始めから、尻の行が入るセクションの終わりまで
            i, j = bisect.bisect_right(starts, a) - 1, bisect.bisect_right(starts, b - 1) - 1
            sa, sb = starts[i] if i >= 0 else 0, starts[j + 1] if j + 1 < len(starts) else n
            bounds = [sa] + [s for s in starts if sa < s < sb] + [sb]
            if max(len("\n".join(lines[x:y])) for x, y in zip(bounds, bounds[1:])) <= DOC_SECTION_MAX:
                spans.append((sa, sb, 2))
                continue
            # 長いセクションは、書き換えた段落・箇条と、どのセクションかを知るための見出しだけ(上の DOC_SECTION_MAX)
            spans.append(_block(lines, marks, a, b, sa, sb) + (2,))
            hb = sa
            while hb < sb and hb in marks:
                hb += 1
            if hb > sa:
                spans.append((sa, hb, 1))
        else:
            spans.append(_paragraph(lines, a, b) + (2,))
    la, lb = _lead(lines, marks)
    if lb > la:
        spans.append((la, lb, 0))
    parts = []   # 重なるか接する範囲を合わせる。合わせた範囲の種類は、書き換えた所・セクションの見出し・冒頭の順に強い物
    for a, b, kind in sorted(spans):
        if parts and a <= parts[-1][1]:
            parts[-1] = [parts[-1][0], max(parts[-1][1], b), max(parts[-1][2], kind)]
        else:
            parts.append([a, b, kind])
    if sum(b - a for a, b, _ in parts) >= DOC_WHOLE_RATIO * n:
        return None
    out, pos = [], 0
    for a, b, kind in parts:
        if a > pos and any(line.strip() for line in lines[pos:a]):
            out.append("(略: %d 行)" % (a - pos))
        out.append((DOC_LEAD_LABEL, DOC_HEAD_LABEL, DOC_PART_LABEL)[kind] + "\n" + "\n".join(lines[a:b]).strip("\n"))
        pos = max(pos, b)
    if pos < n and any(line.strip() for line in lines[pos:]):
        out.append("(略: %d 行)" % (n - pos))
    return "\n\n".join(out) + "\n"


def _cat_blobs(root, specs):
    """git cat-file --batch で <rev>:<path> の中身を読む。読めない(HEAD に無い・UTF-8 でない)ものは None。"""
    try:
        r = subprocess.run(["git", "-C", root, "cat-file", "--batch"], input="".join(s + "\n" for s in specs).encode("utf-8"),
                           capture_output=True, timeout=GIT_TIMEOUT, env=dict(os.environ, GIT_OPTIONAL_LOCKS="0"))
    except (OSError, subprocess.SubprocessError):
        return [None] * len(specs)
    out, pos, data = [], 0, r.stdout if r.returncode == 0 else b""
    for _ in specs:
        nl = data.find(b"\n", pos)
        if nl < 0:
            out.append(None)
            continue
        head = data[pos:nl].split()
        pos = nl + 1
        if len(head) == 3 and head[1] == b"blob" and head[2].isdigit():
            size = int(head[2])
            try:
                out.append(data[pos:pos + size].decode("utf-8"))
            except UnicodeDecodeError:
                out.append(None)
            pos += size + 1
        else:
            out.append(None)   # missing(追跡外・新しい文書)
    return out


def _bases(where, paths):
    """{パス: 前の版の本文}。控えの無い・前の版の無い(新しい)文書は None(全体を読む)。"""
    out, revs = {}, {}
    for p in paths:
        try:
            with open(_base_file(where, p), encoding="utf-8") as f:
                e = json.load(f)
        except (OSError, ValueError):
            e = {}
        if isinstance(e.get("text"), str):
            out[p] = e["text"]
        elif e.get("rev") and e.get("root") and e.get("rel") and "\n" not in e["rel"]:
            revs.setdefault(e["root"], []).append((p, "%s:%s" % (e["rev"], e["rel"])))
        else:
            out[p] = None
    for root, items in revs.items():
        for (p, _), blob in zip(items, _cat_blobs(root, [spec for _, spec in items])):
            out[p] = blob
    return out


def _generated(paths):
    """読まない印の付いた文書。git の属性 linguist-generated(GitHub Linguist の、人が書いていない生成物の印)か -coldread。

    linguist-generated の値の読み方は Linguist に合わせる(lib/linguist/lazy_blob.rb の boolean_attribute: 付いていて
    "false" でなければ生成物)。git check-attr は付いていない・-linguist-generated を unspecified・unset と返す。
    coldread は unset(-coldread)だけを外す印にする。git の外の文書は印が無い側。
    """
    by_dir, out = {}, set()
    for p in paths:
        by_dir.setdefault(os.path.dirname(p) or ".", []).append(p)
    for d, ps in by_dir.items():
        try:
            r = subprocess.run(["git", "-C", d, "check-attr", "-z", "--stdin", GENERATED_ATTR, SKIP_ATTR],
                               input=b"".join(os.path.basename(p).encode("utf-8") + b"\0" for p in ps),
                               capture_output=True, timeout=GIT_TIMEOUT, env=dict(os.environ, GIT_OPTIONAL_LOCKS="0"))
        except (OSError, subprocess.SubprocessError):
            continue
        if r.returncode != 0:
            continue
        f = r.stdout.decode("utf-8", "replace").split("\0")
        for k in range(0, len(f) - 2, 3):
            if (f[k + 2] not in ("unspecified", "unset", "false") if f[k + 1] == GENERATED_ATTR else f[k + 2] == "unset"):
                out.update(p for p in ps if os.path.basename(p) == f[k])
    return out


def doc_feedback(path, found, focus=False, carried=()):
    """1 本の文書の指摘を、直してほしい順のセクションにする(詰まりも補完も前からの詰まりも無ければ空)。focus は書き換えた所だけを
    読ませたとき。carried はブランチのゲートで、メインブランチの版にも在ったので止めなかった詰まり。"""
    if not (found["詰まり"] or found["補完"] or carried):
        return ""
    return "\n".join(filter(None, (
        "■ %s%s" % (path, "(書き換えたセクションだけを読んだ)" if focus else ""),
        section("詰まり(直す):", found["詰まり"]),
        section("メインブランチの版にも在った詰まり(このブランチでは止めない。直すかは判断してよい):", list(carried)),
        section("coldreader が推測で埋めた箇所(意図と違うなら直す):", found["補完"]),
        section("残った疑問(反映するかは判断してよい):", found["疑問"]),
    )))


def _down_reason(exc):
    """読めなかった訳を、書き手に返す短い言葉にする。"""
    if isinstance(exc, subprocess.TimeoutExpired):
        return "読み手が %d 秒で時間切れ" % exc.timeout
    return "読み手を起動できなかった(%s)" % str(exc)[:80].replace("\n", " ")


def _timed_read(text, focus, timeout):
    """read_doc に、かかった秒を添える。((結果, 例外), 秒)。秒は docs.log に残し、次に重さを測れるようにする。"""
    start = time.monotonic()
    try:
        got = (read_doc(text, focus, timeout), None)
    except Exception as exc:
        got = (None, exc)
    return got, time.monotonic() - start


def _read_pending(session, agent, timeout=DOC_READ_TIMEOUT):
    """書いた役の待ちの一覧を読んで消し、読ませる文書を読ませる。(指摘のセクション, 件数, 読めなかった文書) を返す。"""
    pending = _pending(session, agent)
    try:
        with open(pending, encoding="utf-8") as f:
            # 同じ文書が別の綴り(Write の abspath と Bash の実パス)で載っていても 1 回だけ読む
            paths = list({os.path.realpath(p): p for p in (line.strip() for line in f) if p}.values())
        os.remove(pending)
    except OSError:
        return [], {"詰まり": 0, "補完": 0}, []
    who = "sid=%s" % session[:8] + ("\taid=%s" % agent[:17] if agent else "")
    last = {}
    for c in _ledger(DOC_CLAIMS):
        if c.get("t", 0) >= last.get(c.get("p"), {}).get("t", 0):
            last[c.get("p")] = c
    role = _role(session, agent)
    for path in [p for p in paths if last.get(os.path.realpath(p), {}).get("r", role) != role]:
        log_line(DOC_LOG, "skip\t後からほかの役が書いた(%s)\t%s\t%s" % (last[os.path.realpath(path)]["r"][:26], who, path))
        paths.remove(path)
    where = _base_dir(session, agent)
    bases = _bases(where, paths)
    shutil.rmtree(where, ignore_errors=True)
    seen = _seen()
    todo = []
    for path in paths:
        text, why = doc_to_read(path, seen)
        if text is None:
            log_line(DOC_LOG, "skip\t%s\t%s\t%s" % (why, who, path))
        else:
            todo.append((path, text, why))
    generated = _generated([path for path, _, _ in todo]) if todo else set()
    picked = []
    for path, text, digest in todo:
        if path in generated:
            log_line(DOC_LOG, "skip\t読まない印(%s か -%s)\t%s\t%s" % (GENERATED_ATTR, SKIP_ATTR, who, path))
            continue
        part = doc_excerpt(path, text, bases.get(path))
        if part == "":
            log_line(DOC_LOG, "skip\t書く前と同じ中身\t%s\t%s" % (who, path))
            continue
        picked.append((path, text, digest, part))
    notes, counts, down = [], {"詰まり": 0, "補完": 0}, []
    if not picked:
        return notes, counts, down
    # 読む前に、読む中身を読んだ物として覚えておき、読めなかった物だけ後で外す。読み終えてから覚えていた頃は、裏の読み
    # (1 回 2〜4 分)の間に同じ文書が commit で記録し直され、次のターンの終わりの読みが同じ中身をもう一度読んだ
    # (2026-10-17 に説明書の部署で実測: 同じ 11 本を 05:29:04 と 05:30:23 に同じ字数で 2 回読んだ)
    _remember([digest for _, _, digest, _ in picked])
    with concurrent.futures.ThreadPoolExecutor(max_workers=DOC_WORKERS) as pool:
        futures = {pool.submit(_timed_read, text if part is None else part, part is not None, timeout): (path, text, digest, part)
                   for path, text, digest, part in picked}
    unread = []
    for fut, (path, text, digest, part) in futures.items():
        (found, exc), secs = fut.result()
        if exc is not None:
            log_line(DOC_LOG, "reader-down\t%s\t%ds\te=%s\t%s\t%s" % (str(exc)[:150].replace("\n", " "), secs, DOC_EFFORT, who, path))
            down.append("%s: %s" % (path, _down_reason(exc)))
            unread.append(digest)
            continue
        # 書いた役を呼び起こすのは詰まりが在るときだけ(上の「書いた役を呼び起こす」)。推測で埋めた箇所だけなら guess で件数を残す
        note = doc_feedback(path, found, part is not None) if found["詰まり"] else ""
        # 長さのフィールドは読み手に渡した字数。抜き出しなら「渡した字数/全体の字数」
        size = "%d" % len(text) if part is None else "%d/%d" % (len(part), len(text))
        kind = "finding" if note else "guess=%d" % len(found["補完"]) if found["補完"] else "clean"
        # e= は読み手の effort。アカウントごとに effort を替えて、詰まりの在る文書の割合を同じ時期の記録で比べるために残す
        log_line(DOC_LOG, "%s\t%s\t%ds\te=%s\t%s\t%s" % (kind, size, secs, DOC_EFFORT, who, path))
        if note:
            notes.append(note)
            for label in counts:
                counts[label] += len(found[label])
    _forget(unread)   # 読めなかった中身は、次の終わりにまた読む
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


# ---- ターンの終わりを塞がない ----
# 親の Stop で読み終えるまで待たせていた頃は、ターンの終わりごとに持ち主と部署が読み役 1 回ぶん(xhigh で数十秒〜210 秒)
# 待った(持ち主 2026-10-16「coldreadがながいな」)。対話の会話では、Stop のフックを asyncRewake(公式の hooks の文書
# 「runs in the background and wakes Claude on exit code 2. The hook's stderr … is shown to Claude as a system reminder」)
# で裏で走らせ、ターンは待たずに終える。指摘が在れば終了コード 2 と標準エラーで会話を呼び起こして返す。2026-10-16 に
# claude 2.1.301 で実測: Stop の asyncRewake のフックが 8 秒後に 2 で終わると、終えたターンの後に会話が起きて標準エラーの
# 文に答えた。
# 画面の無い会話(claude -p)では、裏のフックは終わりに切られる(同じ文書「kills any async hook still running at
# teardown」)ので、今までどおり待って読む。見分けは Claude Code がフックに渡す環境の CLAUDE_CODE_ENTRYPOINT(実測:
# 対話と agent view の会話は cli、-p は sdk-cli)。無いか sdk で始まるときは待って読む側に倒す(読み落とすより待つ)。
# hooks.json の Stop には同じ読みを 2 つの口(待つ docs-check と裏の docs-check-async)で置き、この見分けでどちらか
# 片方だけが読む。サブエージェントの終わり(SubagentStop)は、指摘をその役に返して直させるので待って読む
# 裏の読みの間に /clear が打たれると、読み終えた知らせは /clear の後の空の会話を呼び起こす(公式の hooks の文書の asyncRewake は
# 窓の会話を呼び起こす)。受けた会話は書いたときの意図を持たないのに、自分が書いた物かが分からず、意図と照合できない推測の扱いに迷う
# (2026-10-17 10:35 ごろに my_notes の本社で、前の会話が書いた 2 本の指摘を受けた会話が、意図を確かめずにサブエージェントへ任せた)。
# /clear で終わる会話は SessionEnd のフック(reason が clear)で覚え、その会話の分の知らせには、前の会話の id と、意図を
# 確かめられない推測の扱いを書く
DOC_CLEARED = os.path.join(DOC_DIR, "cleared")   # /clear で終わった会話の帳面


def docs_session_end(payload):
    """SessionEnd: /clear で終わった会話の id を覚える。"""
    if payload.get("reason") == "clear" and payload.get("session_id"):
        _note(DOC_CLEARED, [{"s": payload["session_id"], "t": time.time()}])


def _cleared(session):
    """この会話が /clear で終わっているか。"""
    return any(r.get("s") == session for r in _ledger(DOC_CLEARED))


def rewakes():
    """この会話の親の Stop を裏で読むか(対話の会話)。"""
    entry = os.environ.get("CLAUDE_CODE_ENTRYPOINT", "")
    return bool(entry) and not entry.startswith("sdk")


def docs_check(payload, background=False):
    """Stop・SubagentStop: 終わろうとしている役が書いた文書を 1 本 1 回だけ読ませ、指摘が在れば止めずに返して直させる。

    サブエージェント(agent_id が有る)には指摘の全文を返す。親には全文をファイルに書き、短い知らせだけを返す。
    background は Stop の裏の口(asyncRewake)。知らせは標準エラーに書いて 2 で終わり、終えたターンの後に会話を呼び起こす。
    """
    session, agent = _who(payload)
    _drop_snaps(_role(session, agent))
    if not agent and background != rewakes():
        return   # 親の Stop はもう片方の口が読む
    if agent and background:
        return
    notes, counts, down = _read_pending(session, agent)
    if not notes and not down:
        return
    event = payload.get("hook_event_name") or ("SubagentStop" if agent else "Stop")
    turn = "直前のターン" if background else "このターン"
    reader = "coldread(文脈を持たない初見の読み手 coldreader、モデル %s・effort %s)" % (DOC_MODEL, DOC_EFFORT)
    tail = ("読み手が読めなかった文書(%s)。手で読ませるなら python3 %s read <パス>。"
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
            if where and background and _cleared(session):
                context = "\n\n".join(filter(None, ((
                    "%sが、/clear で終わった前の会話(id %s)が書いた文書 %d 本に指摘を出した(詰まり %d 件・推測で埋めた箇所 %d 件)。"
                    "この会話が書いた物ではなく、書いたときの意図はこの会話に無い。全文は %s 。"
                    "新しいサブエージェントにこのファイルを渡して詰まりを直させ、全文をこの会話に読み込まない(詰まりは意図が無くても直せる)。"
                    "推測で埋めた箇所は、文書のほかの所・commit の記録・頼みのファイルで意図が確かめられるものだけを直させ、"
                    "確かめられないものは直さずに残す(推測を別の推測で書き換えない)。"
                    "直さずに残すと判断したものは、そのまま終えてよい——同じ中身は読み直さない。"
                    % (reader, session[:8], len(notes), counts["詰まり"], counts["補完"], where)), tail)))
            elif where:
                context = "\n\n".join(filter(None, ((
                    "%sが、%sで書いた文書 %d 本に指摘を出した(詰まり %d 件・推測で埋めた箇所 %d 件)。全文は %s 。"
                    "新しいサブエージェントにこのファイルを渡して直させ、全文をこの会話に読み込まない。"
                    "推測で埋めた箇所のうち書き手の意図と違うものだけは、この会話で見て、正しい意図をサブエージェントに伝える。"
                    "直さずに残すと判断したものは、そのまま終えてよい——同じ中身は読み直さない。"
                    % (reader, turn, len(notes), counts["詰まり"], counts["補完"], where)), tail)))
            else:
                # 書き出せないときは全文を返す(指摘を落とすより文脈を食うほうがまし)
                context = "\n\n".join(filter(None, (reader + "が、%sで書いた文書を読んだ。詰まった箇所を直すこと:" % turn, *notes, tail)))
        context = "\n\n".join(filter(None, (context, VERSION_NOTE)))
    if background:
        sys.stderr.write(context + "\n")
        sys.stderr.flush()
        sys.exit(2)
    print(json.dumps({"hookSpecificOutput": {"hookEventName": event, "additionalContext": context}}, ensure_ascii=False))


# ---- メインブランチに入れる前のゲート: ブランチが書いた文書を読む ----
# 部署はターンの中でメインブランチに入れるコマンド(works-dispatch の --land)まで済ませ、上の手元の文書の読みはターンの終わりに裏で
# 走るので、指摘はいつもメインブランチに入った後に届いた(2026-10-17 に 8 件。担当の決まり「初見読みの指摘は入れる前に直す」が
# 守れなかった)。この口は --land のゲート(会社の形の [land] の check)から、入れる候補の commit を置いた一時の作業ツリーで
# 呼ばれ、メインブランチ(既定は origin/HEAD の指すブランチ)とブランチの分かれ目からブランチが足した・変えた文書を、手元の文書と同じ読み手と観点で読む。
# 前から在る文書は分かれ目の版と比べて書き換えたセクションだけを読ませる。詰まりが 1 件でもあれば 1 で終わって止め(分かれ目の版にも
# 同じ理由で在った詰まりは止めない。下の BASE_CHECK_HEAD)、推測で埋めた
# 箇所と疑問だけなら通す(手元の文書のゲートと同じ重さ: 直すのは詰まり、推測は意図と違うときだけ)。読めなかった文書が在っても
# 1 で終わる(読まずに通すと、ゲートが黙って空になる)。指摘の全文は findings/ に書き、--land が部署の窓に返す末尾の行に
# 詰まりと全文の場所を出す。メインブランチが先に進むたびにリベースして打ち直すので、同じ依頼文の判定は branch/ に覚えて読み直さない
DOC_BRANCH = os.path.join(DOC_DIR, "branch")   # 依頼文のハッシュごとの判定(読み直さない)
DOC_BRANCH_KEEP = 2000   # 覚える判定の数(古いものから消す)


def _branch_docs(root, base):
    """(分かれ目の commit, [(作業ツリーのルートからのパス, 実パス)])。ブランチが足した・変えた文書だけ。分かれ目が取れなければ None。"""
    mb = _git(["merge-base", "HEAD", base], root)
    if not mb:
        return None
    mb = mb.decode("ascii", "replace").strip()
    out = _git(["diff", "--name-only", "-z", "--no-renames", "--diff-filter=AM", mb, "HEAD", "--"], root) or b""
    rels = [r for r in out.decode("utf-8", "replace").split("\0") if r.lower().endswith(DOC_EXTS)]
    return mb, [(r, os.path.join(root, r)) for r in rels if os.path.isfile(os.path.join(root, r))]


# ブランチが足した文書のうち、ブランチが消した・変えた文書の分かれ目の版に在った行は、移しただけの行として読み直さない(git の copy の
# 検出を行の単位でする形)。スキルの書き方の標準(docs/standards/skill-authoring.md)で SKILL.md のセクションを字を変えずに
# references/ へ移すと、前からメインブランチに在った文が新しい文書として丸ごと読まれ、元の本文の前のセクションで説明していた語が 1 本だけでは
# 取れないという詰まりが、読むたびに別の文書へ移りながら出続けた(2026-10-18、works-dispatch の dispatch の分けで
# references/ の 12 本に約 70 件。convergence-loops・graphloops の 6 本は .gitattributes の -coldread で逃がしていた)。
# 行は前後の空白と見出しの # を除いて比べる(移すとセクションの深さが変わる)。新しく書いた行(題・書き換えた指し先)を含むセクションは読む
def _line_key(line):
    return line.strip().lstrip("#").strip()


def _moved_lines(root, mb):
    """ブランチが消した・変えた文書の、分かれ目の版の行(_line_key で比べる形)の集まり。"""
    out = _git(["diff", "--name-only", "-z", "--no-renames", "--diff-filter=DM", mb, "HEAD", "--"], root) or b""
    rels = [r for r in out.decode("utf-8", "replace").split("\0") if r.lower().endswith(DOC_EXTS)]
    keys = set()
    for blob in _cat_blobs(root, ["%s:%s" % (mb, r) for r in rels]) if rels else ():
        keys.update(_line_key(line) for line in (blob or "").replace("\r\n", "\n").split("\n"))
    keys.discard("")
    return keys


def _moved_base(text, moved):
    """足した文書の前の版の代わり: 空行と、移した元に在った行だけを残した本文。移した行が 1 つも無ければ None(全体を読む)。"""
    lines = text.split("\n")
    kept = [line for line in lines if not _line_key(line) or _line_key(line) in moved]
    return "\n".join(kept) if any(_line_key(line) for line in kept) else None


def _branch_cached(key, compute):
    """覚えた結果か、compute() で出して覚えた結果。(結果, 覚えた結果か)。compute の例外はそのまま出す。"""
    where = os.path.join(DOC_BRANCH, key + ".json")
    try:
        with open(where, encoding="utf-8") as f:
            return json.load(f), True
    except (OSError, ValueError):
        pass
    found = compute()
    try:
        os.makedirs(DOC_BRANCH, exist_ok=True)
        with open(where, "w", encoding="utf-8") as f:
            json.dump(found, f, ensure_ascii=False)
        for e in sorted(os.scandir(DOC_BRANCH), key=lambda e: e.stat().st_mtime)[:-DOC_BRANCH_KEEP]:
            os.remove(e.path)
    except OSError:
        pass
    return found, False


# ブランチの文書の詰まりのうち、メインブランチの版にも同じ理由で在った物は止めない(一覧には残す)。語の置き換え(持ち主 2026-10-18
# 「節とかITになじみのない言葉を使ってる箇所を置き換えておいて」)は文書の全体に散るので、書き換えたセクションだけを読ませても
# 長く専門語の多い文書はほぼ全体が読まれ、前からの読みにくさが詰まりとして出て、直すたびに別の所で詰まった(2026-10-19、説明書の
# 頼みで 36 → 17 → 23 件と減らず、main に入れられなかった。指摘の詰まりの引用の多くは分かれ目の版にそのまま在った)。
# 分かれ目の版も読ませて指摘を突き合わせる形は採らない: 読み手は回ごとに拾う所が替わる(上の DOC_SECTION_MAX)ので、前からの
# 詰まりでも 2 回の読みの指摘は合わない。出た詰まりを 1 件ずつ、分かれ目の版でも同じ理由で詰まるかを問う。前の版で語を説明して
# いた文をブランチが消したなら、前の版では詰まらないので止める。迷えば新しい詰まり、問えなければ全部を新しい詰まりにする
# (どちらも今までどおり止める)。ブランチが足した文書は全部がブランチの文なので問わない
BASE_CHECK_HEAD = """あなたは文書の 2 つの版を比べる係です。初見の読み手が文書の新しい版を読み、下の「詰まり」を報告しました。
詰まりごとに、前の版を初見で読んでも、同じ箇所で同じ理由で詰まるかを判定してください。
- OLD: 前の版にも同じ箇所(言い回しが少し違っても中身が同じ文)が在り、前の版のほかの所にも説明が無く、同じ理由で意味が取れない
- NEW: 前の版にその箇所が無い・前の版では意味が取れる(説明が在る・言い方が違って分かる)・新しい版で書き換えた語や文が詰まりの原因
- 迷ったら NEW
出力は 1 行 1 件、詰まりの番号と OLD か NEW だけ(例: 1 OLD)。ほかは何も書かない。
"""
BASE_CHECK_RE = re.compile(r"^\s*(\d+)\s*[.:：)]?\s*(OLD|NEW)\b", re.I)


def _base_marks(out):
    """比べる係の出力を {番号の文字列: "OLD" か "NEW"} にする。1 行も読めなければ例外。"""
    marks = {m.group(1): m.group(2).upper() for m in map(BASE_CHECK_RE.match, out.splitlines()) if m}
    if not marks:
        raise RuntimeError("番号と OLD・NEW の行が無い: %r" % out[:150])
    return marks


def _carried_from_base(stuck, body, base):
    """詰まり(stuck)のうち、メインブランチの版(base)にも同じ理由で在った物の番号(0 から)。問えなければ空(全部を新しい詰まりにする)。"""
    prompt = (BASE_CHECK_HEAD + "\n--- 詰まり ---\n" + "".join("%d. %s\n" % (k, line) for k, line in enumerate(stuck, 1))
              + "\n--- 新しい版(読み手が読んだ本文) ---\n" + body + "\n--- 前の版 ---\n" + base)
    key = hashlib.sha256(prompt.encode("utf-8")).hexdigest()[:40]
    try:
        marks, _ = _branch_cached(key, lambda: _base_marks(
            run_reader(prompt, model=DOC_MODEL, effort=DOC_EFFORT, timeout=DOC_READ_TIMEOUT)))
    except Exception as exc:
        log_line(DOC_LOG, "base-check-down\t%s" % str(exc)[:150].replace("\n", " "))
        return set()
    return {k for k in range(len(stuck)) if marks.get(str(k + 1)) == "OLD"}


def _branch_verdict(key, body, focus, base):
    """(判定, 覚えた判定か, メインブランチの版にも在った詰まりの番号)。判定は覚えた物か、読んで覚えた物({"詰まり", "補完", "疑問"})。
    読めなければ例外。base はメインブランチの版(ブランチが足した文書は None で、問わない)。"""
    found, cached = _branch_cached(key, lambda: read_doc(body, focus))
    old = _carried_from_base(found["詰まり"], body, base) if found["詰まり"] and base is not None else set()
    return found, cached, old


# 語の置き換えだけの行は読み直さない(--fixer <Python のファイル>)。リポジトリの文を IT の定着語にそろえる置き換え(持ち主 2026-10-18)は
# 文書のほぼ全部のセクションに散るので、書き換えたセクションの抜き出しが 8 割(DOC_WHOLE_RATIO)を超えて文書を丸ごと読ませ、元からある
# 書き方の詰まりで --land が止まった(2026-10-19、graphloops・convergence-loops の 108 本のうち 80 本に詰まり 394 件。置き換えた語に
# 当たる詰まりは無かった)。そのファイルの fix_text(本文) を前の版に当て、置き換えが変えた語の所だけが違う今の行は書き換えに数えない
# (片仮名・英数字の別の語を手で選んだ所も含む。_same_words)。語の所の外も変えた行は今までどおり読む。語の選び方の取り違えは、初見の読み手でなく
# 置き換えた側が照合する(置き換えた語の意味が合うかは、語の前後だけを読む初見の読み手より、元の語と並べて見る側が分かる)
def _load_fixer(path):
    """path の Python のファイルの fix_text を、例外を出さない置き換え(出せば本文をそのまま返す)にして返す。読めなければ例外。"""
    spec = importlib.util.spec_from_file_location("coldread_fixer", os.path.abspath(path))
    if spec is None or spec.loader is None:
        raise ImportError("Python のファイルとして読めない")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    fix_text = getattr(mod, "fix_text", None)
    if not callable(fix_text):
        raise ImportError("fix_text(本文) が無い")

    def fixer(text):
        try:
            out = fix_text(text)
        except Exception as exc:
            log_line(DOC_LOG, "fixer-down\t%s" % str(exc)[:150].replace("\n", " "))
            return text
        if not isinstance(out, str):
            log_line(DOC_LOG, "fixer-down\tfix_text が文字列でない %s を返した" % type(out).__name__)
            return text
        return out
    return fixer


def branch_check(argv):
    """--land のゲート: ブランチが書いた文書を読み、詰まりが在れば 1、読めない文書が在れば 1、無ければ 0。"""
    base = argv[argv.index("--base") + 1] if "--base" in argv[:-1] else None
    fixer = None
    if "--fixer" in argv:
        where = argv[argv.index("--fixer") + 1] if "--fixer" in argv[:-1] else ""
        try:
            fixer = _load_fixer(where)
        except Exception as exc:
            print("coldread branch-check: --fixer の %s から fix_text を読めない(%s)" % (where or "(パスが無い)", str(exc)[:150]))
            return 2
    top = _git(["rev-parse", "--show-toplevel"], os.getcwd())
    if not top:
        print("coldread branch-check: git の作業ツリーの中で走らせる")
        return 2
    root = top.decode("utf-8", "replace").strip()
    if not base:
        head = _git(["rev-parse", "--abbrev-ref", "origin/HEAD"], root)
        base = head.decode("utf-8", "replace").strip() if head else "origin/main"
    got = _branch_docs(root, base)
    if got is None:
        print("coldread branch-check: %s との分かれ目が取れない(--base <メインブランチの ref> で渡す)" % base)
        return 2
    mb, docs = got
    generated = _generated([full for _, full in docs]) if docs else set()
    moved = _moved_lines(root, mb) if docs else set()
    picked = []
    for rel, full in docs:
        try:
            with open(full, encoding="utf-8") as f:
                text = f.read()
        except (OSError, UnicodeDecodeError):
            continue
        if full in generated or len(text) < DOC_MIN_LEN or any(m in text.split("\n", 1)[0] for m in DOC_SKIP_MARKS):
            continue
        old = _git(["show", "%s:%s" % (mb, rel)], root)
        old = old.decode("utf-8", "replace") if old is not None else None
        part = doc_excerpt(full, text, old if old is not None else _moved_base(text, moved), fixer)
        if part == "":
            continue
        body = text if part is None else part
        key = hashlib.sha256(doc_prompt(body, part is not None).encode("utf-8")).hexdigest()[:40]
        picked.append((rel, text, body, part is not None, key, old))
    notes, stuck, counts, down, fresh = [], [], {"詰まり": 0, "補完": 0, "前から": 0}, [], 0
    with concurrent.futures.ThreadPoolExecutor(max_workers=DOC_WORKERS) as pool:
        futures = [(pool.submit(_branch_verdict, key, body, focus, old), rel, text, focus)
                   for rel, text, body, focus, key, old in picked]
    for fut, rel, text, focus in futures:
        try:
            found, cached, old = fut.result()
        except Exception as exc:
            log_line(DOC_LOG, "reader-down\t%s\tbranch\t%s" % (str(exc)[:150].replace("\n", " "), rel))
            down.append("%s: %s" % (rel, _down_reason(exc)))
            continue
        fresh += not cached
        log_line(DOC_LOG, "%s\tbranch%s\t%s" % ("finding" if found["詰まり"] or found["補完"] else "clean",
                                                  "(覚えた判定)" if cached else "", rel))
        carried = [line for k, line in enumerate(found["詰まり"]) if k in old]
        found = dict(found, 詰まり=[line for k, line in enumerate(found["詰まり"]) if k not in old])
        note = doc_feedback(rel, found, focus, carried)
        if note:
            notes.append(note)
        stuck += ["%s — %s" % (rel, line) for line in found["詰まり"]]
        counts["詰まり"] += len(found["詰まり"])
        counts["補完"] += len(found["補完"])
        counts["前から"] += len(carried)
    _remember([hashlib.sha256(text.encode("utf-8")).hexdigest() for _, text, _, _, _, _ in picked])   # ターンの終わりの読みと重ねない
    where = _write_findings("branch", "\n\n".join(("coldread が、メインブランチに入れる前にブランチの文書を読んだ指摘(分かれ目 %s)。" % mb[:8], *notes))) \
        if notes else None
    for line in stuck:
        print(line)
    if down:
        print("読めなかった文書(読み手を起動できない。手で読ませるなら python3 %s read <パス>): %s"
              % (os.path.abspath(__file__), "・".join(down)))
    print("coldread branch-check: ブランチの文書 %d 本を読んだ(新しく読んだ %d 本)。詰まり %d 件%s・推測で埋めた箇所 %d 件%s。%s"
          % (len(picked), fresh, counts["詰まり"],
             "(ほかにメインブランチの版にも在った詰まり %d 件は止めない)" % counts["前から"] if counts["前から"] else "",
             counts["補完"], "・読めなかった %d 本" % len(down) if down else "",
             ("全文: " + where) if where else "指摘なし"))
    return 1 if stuck or down else 0


def read_now(path):
    """手で 1 本を読ませる(記録もハッシュも見ない)。指摘を出し、詰まりが在れば 1 で終わる。"""
    with open(path, encoding="utf-8") as f:
        text = f.read()
    try:
        found = read_doc(text)
    except Exception as exc:
        print("読めなかった: %s" % _down_reason(exc))
        return 1
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
    if mode == "docs-record":
        docs_record(payload)
    elif mode == "docs-session-end":
        docs_session_end(payload)
    else:
        docs_check(payload, background=mode == "docs-check-async")


if __name__ == "__main__":
    MODE = sys.argv[1] if len(sys.argv) > 1 else ""
    if MODE in ("docs-record", "docs-check", "docs-check-async", "docs-session-end"):
        hook_main(MODE)
    elif MODE == "branch-check":
        sys.exit(branch_check(sys.argv[2:]))
    elif MODE == "read" and len(sys.argv) == 3:
        sys.exit(read_now(sys.argv[2]))
    elif MODE == "prompt":
        # 初見で読む観点の正本はこの 1 か所(COLD_PROMPT)。手で読み手を立てるときも、これを依頼文にする。
        # バイトで出す(Windows の文字の出力は改行を \r\n に替え、正本と同じバイトにならない)
        sys.stdout.flush()
        sys.stdout.buffer.write(COLD_PROMPT.encode("utf-8"))
    elif MODE:
        sys.exit("使い方: coldread-gate.py [docs-record | docs-check | docs-check-async | branch-check [--base <ref>] [--fixer <Python のファイル>] | read <パス> | prompt](引数なしは投稿のゲート)")
    else:
        main()
