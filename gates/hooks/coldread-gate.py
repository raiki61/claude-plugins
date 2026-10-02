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

記録は $CLAUDE_CONFIG_DIR/coldread-gate/ に 3 本:
  denies.log  allow / deny / skip の別(deny はタブ区切りで種別も。maxlen・parse-fail・
              blocked・reader-down・finding)。blocked には止めた理由の語(, 区切り。値は
              書かない)も付く——どの形の止めが多いかを数えるため。finding と allow には本文の長さと読み方
              (screen=画面を渡した / cold=文脈ゼロ)も付く——連続 deny の間に本文が
              どれだけ膨れたかを書き手に示すため。各行の末尾に sid=(session id の先頭 8 字)
              v=(この門番の版) to=(投稿先。種別:repo:番号、新規作成はサブコマンド)
  skip.log    逃げ道を使った投稿のコマンド先頭 200 字
  misses.log  本文旗の綴りが在るのに候補も blocked も空だった素通し=網から落ちた疑い。
              「投稿でなかった」と区別が付かないと押し出しの量を測れないので分けて残す。
              下限より短いコマンドの解析が落ちて本文ファイルを審査せずに通した回も
              parse-error<タブ><種類>(例外の型名か unparseable。値は書かない)として残す

環境変数:
  COLDREAD_SKIP=1            この 1 回だけゲートを通す(記録が残る)
  COLDREAD_READER_CMD        読み役コマンドの差し替え(POSIX sh 文字列として sh -c 実行。stdin に依頼文+本文)。テスト用
  COLDREAD_GH_CMD            画面(投稿先のスレッド)を取る gh の差し替え(POSIX sh 文字列として
                             sh -c 実行。$1 以降に gh の引数列)。テスト用
  COLDREAD_MODEL             既定 sonnet
  COLDREAD_EFFORT            既定 medium
  COLDREAD_MIN_LEN           これ未満のコマンドは素通し(本文旗のファイルから読めた 200 字以上の本文だけは審査する)。既定 400
  COLDREAD_MAX_LEN           これを超えるコマンドは解析せず deny(先頭に置いた COLDREAD_SKIP=1 だけはこの前に効く)。既定 100000
  COLDREAD_IN_READER=1       読み役の中であることの印(自動で付く)。入れ子の再発火を防ぐ
  COLDREAD_KEYCHAIN_SERVICE  macOS Keychain の OAuth トークンのサービス名(未指定なら
                             CLAUDE_CONFIG_DIR の末尾から推定: ~/.claude-p1 → claude-code-oauth-p1)
"""
import collections
import itertools
import json
import os
import re
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

CONFIG_DIR = os.environ.get("CLAUDE_CONFIG_DIR") or os.path.expanduser("~/.claude")
STATE_DIR = os.path.join(CONFIG_DIR, "coldread-gate")
SKIP_LOG = os.path.join(STATE_DIR, "skip.log")
DENY_LOG = os.path.join(STATE_DIR, "denies.log")
MISS_LOG = os.path.join(STATE_DIR, "misses.log")
MIN_LEN = int(os.environ.get("COLDREAD_MIN_LEN", "400"))
# 上限。これを超える文字列は解析せず deny——解析は長さに比例して重くなり、
# フックの timeout を超えると無検査で通る
MAX_LEN = int(os.environ.get("COLDREAD_MAX_LEN", "100000"))
READER_TIMEOUT = 210
GH_TIMEOUT = 12   # 画面取得の gh 呼び出し 1 回分
GH_BUDGET = 40    # 画面取得の合計。読み役の 210 と合わせてフックの timeout(260s)に収める——
                  # 超えるとフック自体が時間切れになり、投稿が無検査で通る(fail-open)
GH_PAGES = 5      # 会話の取得で辿る最大ページ数(1 ページ 100 件)
DENY_STREAK_WINDOW = 30 * 60

# ---- 投稿の判定 ------------------------------------------------------------
# 「gh らしさ」と「旗らしさ」を文字列全体へ独立に照合する方式は、複合コマンドで別コマンドの
# 旗を gh の物と誤認し(git checkout -b)、引用・短縮形で取りこぼした(0.2.x で実測)。
# 代わりに、字句の走査 → トークン化 → 単純コマンドに区切り、gh の
# 引数列の中だけで「本文を運ぶ旗」を見る。単純コマンド分割と旗表は自作なので網羅性はテストで
# 守る。なぜこの方式か・いつ乗り換えるかは docs/coldread-gate-next.md(正本)。
# 対象外と受容した形は gates/README.md「網の射程」。
# bash の字句の文脈(引用・置換・注釈・行継続・ヒアドキュメント・IO_NUMBER・展開)を読むのは字句の走査
# scan_shell の 1 本だけで、ほかの段はその結果(印に置き換えた文字列と、印ごとの中身)を読むだけにする。
# 段ごとに文脈を読み直すと読みが互いにずれ、審査した本文と投稿される本文が離れるか、bash が走らせる gh が
# 両方のゲートから消える(2026-10-02 に 6 形を実測)。読みが bash と合うかは tests/py/test_coldread_gate.py が
# bash を判定役にして突き合わせる。写していない構文(case の枝の `)` を置換の中に置く形など)は、読みを推さずに
# 解析できないものとして止める。
Heredoc = collections.namedtuple("Heredoc", "mark value")
# 生きた展開 1 つ。kind は sub($(…))・bt(`…`)・procsub(<(…) >(…))・funsub(${ …; })・param(${…} と $名前)・
# arith($((…)))・arithb($[…])。span は元の字の (文字列, 始め, 終わり)——入れ子の置換ごとに切り出すと長さの 2 乗に
# なるので、写すのは unmark の時だけにする。inner は命令を走らせる種類の中身を同じ走査で書き換えた文字列(ほかは None)
Expansion = collections.namedtuple("Expansion", "mark kind span inner in_dq")
Scanned = collections.namedtuple("Scanned", "text docs exps marks")
COMMAND_KINDS = {"sub", "bt", "procsub", "funsub"}
# 印の綴り。呼び出しごとの nonce を付けるのは、本文に字で書いた印が本物に化けないようにするため
MARK_TAGS = "HEREDOC|EXPAND|FD"
MARK = "__%s%s_%d__"
# 読めなかった本文 1 つと、止めた理由の語。本文ファイル(_Files)・stdin(stdin_source)・置換の値の読めなさは、
# すべてこの形で返す
Unread = collections.namedtuple("Unread", "reason")
# 本文候補 1 つ。from_file は本文旗のファイルから読んだもの——コマンド長の下限(MIN_LEN)を当てず、
# 審査を通っても権限の確認を飛ばさない(main)
Body = collections.namedtuple("Body", "text from_file")
# gh の呼び出し 1 つ。args は静的な置換を値に解いた後の語で、解けない展開は書かれたとおりの字に戻す。prefix は gh より
# 前の語(NAME=値・包みとその旗)を同じ規則で戻したもの——destgate が gh 自身に効く GH_REPO・env -u・env -C を読む
Call = collections.namedtuple("Call", "args candidates blocked prefix", defaults=((),))

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
# 値を取る global 旗(サブコマンド語の特定と -R の読みで読み飛ばす)。-H/-X は api の前置で挟まりうる。
GLOBAL_VALUE_FLAGS = {"-R", "--repo", "-H", "--header", "-X", "--method"}
# gh api で値を取る旗のうち、classify が読む物(key=値 のフィールド)。--input は API_BODY_FLAGS
API_FIELD_FLAGS = {"-f", "-F", "--field", "--raw-field"}
WRAPPERS = {"env", "command", "exec", "nohup", "time"}
# 包みの旗のうち値を取るもの(env -u NAME・-C DIR・-P PATH・-S STRING、exec -a NAME)。値を命令名と読まない
WRAPPER_VALUE_FLAGS = {"-u", "--unset", "-C", "--chdir", "-P", "-S", "--split-string", "-a"}
WRAPPER_CHDIR = ("-C", "--chdir")   # env -C DIR は命令の cwd を変える
# シェルの予約語。単純コマンドの先頭語になりうるが、コマンド名ではないので読み飛ばす。
# 飛ばさないと `{ gh …; }`・`if …; then gh …`・`while …; do gh …`・`! gh …` の gh が
# 見えず、投稿が無検査・無記録で通る(両ゲートとも。実測)。同じ意味の `( gh … )` は
# `(` が OP_CHARS にあるので元から通っていた——書き方だけで片方が抜ける状態だった。
# 載せるのは「直後にコマンドが来る」語だけ。done・fi・in は後ろにコマンドを取らないので
# 入れない(入れても発火させられず、表の全メンバーを検査する回帰が張れない)。
RESERVED = {"{", "!", "then", "else", "elif", "do"}
OP_CHARS = set("();<>|&\n")
# リダイレクト演算子。&> >& <& は & を含むが区切りではない。
# <> は fd 0 を読み書きで開く——区切りと読むと、後ろの行き先が stdin を差し替えたことを見失う
REDIRECT_OPS = {"<", ">", ">>", "<<", "<<<", "<&", ">&", "&>", "&>>", ">|", "<>"}
# 引用していない演算子の字の並び(;改行・改行改行・&&改行・)>)を bash の演算子に割る表で、長いものから当てる。
# <( >( は区切りとして読む——1 字ずつ割ると < が ( を行き先として食い、後ろの gh が前の命令の
# 引数に呑まれる(走査はプロセス置換を印に替えるので、ふつうはここに届かない)
_OPS = sorted(REDIRECT_OPS | {"&&", "||", ";;", ";&", ";;&", "|&", "<(", ">("}, key=len, reverse=True)
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


# 走査が止まる字。それ以外の字は文脈を変えないので一括で写す
_EVENT_RE = re.compile(r"""[\\'"`$()}\[\]<>#\n]""")
_DELIM_STOP = set(" \t\n;&|<>()")
# この字の直後は語頭(注釈の #・算術の命令の ((・IO_NUMBER の数字を見分ける)。見るのは出力側の直前の字で、
# 行継続で連結した `echo x\<改行>#y` の # は語中になる
_WORD_BREAK = " \t\n;&|()<>"
_CODE = {"code", "sub", "bt", "procsub", "funsub"}   # 命令として読む文脈(<<・注釈・IO_NUMBER が構文になる)
_PARAM_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*|[0-9@*#?$!-]")
# 置換の中の case と esac(命令の位置の語)。閉じる ) の時点で case が esac より多ければ、その ) は枝の型の閉じ
_CASE_RE = re.compile(r"(?:^|[;&|(){}\n]|\b(?:then|do|else)\s)\s*case\s+\S+\s+in\s")
_ESAC_RE = re.compile(r"(?:^|[;&|(){}\n])\s*esac(?=$|[\s;&|)])")
# 数える前に 1 字の語の字へ潰す、引用と \ の退避。`echo '; esac '`・`echo \; esac` の esac は命令の位置の語でない
_QUOTED_RE = re.compile(r"""\\.|\$'(?:\\.|[^'\\])*'|'[^']*'|"(?:\\.|[^"\\])*\"""", re.S)
# 開始行で見つけ、中身をまだ読んでいない << 。開いた文脈の _Frame が持つ
_Pending = collections.namedtuple("_Pending", "mark delim quoted strip")
_MAX_HEREDOC_NEST = 8   # 区切りを引用しないヒアドキュメントの中身の、置換の中のヒアドキュメント…の深さ


class _Buf:
    """1 つの命令の文脈の出力。引用の文脈は外側の _Buf に書く(トークン化が引用を読めるように)。"""

    __slots__ = ("parts", "last")

    def __init__(self):
        self.parts, self.last = [], ""

    def emit(self, s):
        if s:
            self.parts.append(s)
            self.last = s[-1]

    def at_word_start(self):
        return not self.last or self.last in _WORD_BREAK

    def take_io_number(self):
        """末尾の数字の並びが語頭から始まっていれば外して返す(POSIX 2.10.1 の IO_NUMBER)。違えば None。

        数字は部品を後ろから集めて最後に 1 回だけ連結する——前へ足して伸ばすと、行継続で 1 字ずつの部品に割った
        数字の並びで長さの 2 乗になる。
        """
        runs, k, before = [], len(self.parts), ""
        while k:
            s = self.parts[k - 1]
            j = len(s)
            while j and s[j - 1] in "0123456789":
                j -= 1
            runs.append(s[j:])
            if j:
                before = s[j - 1]
                break
            k -= 1
        run = "".join(reversed(runs))
        if not run or (before and before not in _WORD_BREAK):
            return None
        cut = len(run)
        while cut:
            s = self.parts.pop()
            if len(s) > cut:
                self.parts.append(s[:-cut])
                break
            cut -= len(s)
        self.last = self.parts[-1][-1] if self.parts else ""
        return run


class _Frame:
    __slots__ = ("kind", "buf", "depth", "start", "in_dq", "pending")

    def __init__(self, kind, buf, start=0, in_dq=False):
        self.kind, self.buf, self.start, self.in_dq = kind, buf, start, in_dq
        self.depth, self.pending = 0, []


class _Scanner:
    """bash の字句の文脈を読み、生きた展開・ヒアドキュメント・IO_NUMBER を印に置き換える。

    区切りを引用しないヒアドキュメントの中身は、入れ子ごとに読み直す(深さは _MAX_HEREDOC_NEST まで)。
    """

    def __init__(self, nonce):
        self.nonce, self.docs, self.exps, self.ndocs = nonce, {}, [], 0
        self.nest, self.unparsable = 0, False

    def mark(self, tag, k):
        return MARK % (tag, k, self.nonce)

    def scan(self, text, base):
        """text を base の文脈(code か、区切りを引用しないヒアドキュメントの中身 hd)で読む → 置き換えた文字列。

        文脈が閉じないまま終われば None(bash も構文の誤りで走らせない)。
        """
        stack = [_Frame(base, _Buf())]
        i, n = 0, len(text)
        while i < n:
            f = stack[-1]
            kind, buf = f.kind, f.buf
            if kind == "sq":
                j = text.find("'", i)
                if j < 0:
                    return None
                buf.emit(text[i:j + 1])
                stack.pop()
                i = j + 1
                continue
            m = _EVENT_RE.search(text, i)
            if m is None:
                buf.emit(text[i:])
                break
            buf.emit(text[i:m.start()])
            i, c = m.start(), m.group()
            if c == "\\":
                i = self.backslash(text, i, f)
            elif kind == "ansi":
                buf.emit(c)
                i += 1
                if c == "'":
                    stack.pop()
            elif kind in ("dq", "hd") and c not in "$`":
                buf.emit(c)
                i += 1
                if c == '"' and kind == "dq":
                    stack.pop()
            elif c == "$":
                i = self.dollar(text, i, stack)
            elif c == "`":
                if kind == "bt":
                    i += 1
                    self.close(stack, text, i)
                else:
                    self.open(stack, "bt", i)
                    i += 1
            elif c in "'\"":
                buf.emit(c)
                stack.append(_Frame("sq" if c == "'" else "dq", buf))
                i += 1
            elif c in "()[]}":
                i = self.bracket(text, i, stack)
            elif kind not in _CODE:
                buf.emit(c)   # 算術・パラメータの中の < > # 改行は字
                i += 1
            elif c == "#":
                if buf.at_word_start():
                    i = self.comment_end(text, i, kind)
                else:
                    buf.emit(c)
                    i += 1
            elif c in "<>":
                i = self.redirect(text, i, stack)
            else:   # 改行
                buf.emit(c)
                i += 1
                if f.pending:
                    i = self.bodies(text, i, f)
        if len(stack) != 1:
            return None
        return "".join(stack[0].buf.parts)

    def backslash(self, text, i, f):
        kind, buf, nxt = f.kind, f.buf, text[i + 1:i + 2]
        if kind not in ("ansi", "hd") and (nxt == "\n" or text.startswith("\r\n", i + 1)):
            return i + (3 if nxt == "\r" else 2)   # 行継続は前後を連結するので buf.last は据え置く
        if kind == "dq" and nxt in "$`" and nxt:
            buf.emit(nxt)   # トークン化は二重引用の中の \$ を字のまま残すので、bash の値の字にして渡す
        elif kind == "hd" and nxt in "$`\\" and nxt:
            buf.emit(nxt)
        else:
            buf.emit(text[i:i + 2])
        return i + 2

    @staticmethod
    def joined(text, j, kind):
        """先読みの位置 j から行継続を飛ばした位置。先読みは必ずここを通す——生の字を見ると `$\\<改行>(` を
        展開と読まず、bash が投稿する置換の値を字面のまま審査する。

        区切りを引用しないヒアドキュメントの中身は読む前に連結済み(_logical_line)で、$'…' の中は行継続でない。
        """
        return j if kind in ("hd", "ansi") else _skip_joins(text, j)

    def dollar(self, text, i, stack):
        f = stack[-1]
        j = self.joined(text, i + 1, f.kind)
        nxt = text[j:j + 1]
        if nxt == "(":
            k = self.joined(text, j + 1, f.kind)
            if text.startswith("(", k):
                self.open(stack, "arith", i)
                return k + 1
            self.open(stack, "sub", i)
            return j + 1
        if nxt == "[":
            self.open(stack, "arithb", i)
            return j + 1
        if nxt == "{":
            k = self.joined(text, j + 1, f.kind)
            if text[k:k + 1] in (" ", "\t", "\n", "|"):
                self.open(stack, "funsub", i)   # bash 5.3 の ${ 命令; } と ${| 命令; }
                return k + 1 if text[k] == "|" else k
            self.open(stack, "param", i)
            return j + 1
        if nxt == "'" and f.kind not in ("dq", "hd"):
            f.buf.emit("$'")
            stack.append(_Frame("ansi", f.buf))
            return j + 1
        if nxt == '"' and f.kind not in ("dq", "hd"):
            end = i + 1   # $"…" は訳文に置き換わる。$ だけを展開にして、引用は続けて読む
        else:
            m = _PARAM_RE.match(text, j)
            if m is None:
                f.buf.emit("$")   # 後ろが名前でも括弧でもない $ は字(5$・US$ 5)
                return i + 1
            end = m.end()
        mark = self.mark("EXPAND", len(self.exps))
        self.exps.append(Expansion(mark, "param", (text, i, end), None, f.kind == "dq"))
        f.buf.emit(mark)
        return end

    def bracket(self, text, i, stack):
        f = stack[-1]
        kind, buf, c = f.kind, f.buf, text[i]
        if c == "(":
            k = self.joined(text, i + 1, kind)
            if kind in _CODE and buf.at_word_start() and text.startswith("(", k):
                buf.emit("((")   # 命令の位置の (( は算術の命令。中の << はシフト
                stack.append(_Frame("arithcmd", buf))
                return k + 1
            if kind in _CODE or kind in ("arith", "arithcmd"):
                f.depth += 1
        elif c == ")":
            if f.depth and kind != "param":
                f.depth -= 1
            elif kind in ("sub", "procsub"):
                inner = _QUOTED_RE.sub("_", "".join(buf.parts))
                if len(_CASE_RE.findall(inner)) > len(_ESAC_RE.findall(inner)):
                    # bash は置換の中の case の枝の型 `x)` で置換を閉じない。その読みは写していないので、推さずに止める
                    self.unparsable = True
                self.close(stack, text, i + 1)
                return i + 1
            elif kind in ("arith", "arithcmd"):
                k = self.joined(text, i + 1, kind)
                end = k + 1 if text.startswith(")", k) else i + 1
                if kind == "arith":
                    self.close(stack, text, end)
                else:
                    buf.emit("))" if end > i + 1 else ")")
                    stack.pop()
                return end
        elif c == "[":
            if kind == "arithb":
                f.depth += 1
        elif c == "]":
            if kind == "arithb":
                if not f.depth:
                    self.close(stack, text, i + 1)
                    return i + 1
                f.depth -= 1
        elif kind == "param" or (kind == "funsub" and not f.depth and buf.at_word_start()):
            self.close(stack, text, i + 1)   # }
            return i + 1
        buf.emit(c)
        return i + 1

    def comment_end(self, text, i, kind):
        """語頭の # から注釈の終わり(改行の手前。改行は残す)。`…` の中の注釈は閉じる ` で終わる。"""
        nl = text.find("\n", i)
        end = len(text) if nl < 0 else nl
        if kind == "bt":
            tick = text.find("`", i, end)
            if tick >= 0:
                end = tick
        return end

    def redirect(self, text, i, stack):
        f = stack[-1]
        buf = f.buf
        j = self.joined(text, i + 1, f.kind)
        if text.startswith("(", j):
            self.open(stack, "procsub", i)
            return j + 1
        fd = buf.take_io_number()
        if fd is not None:
            buf.emit(self.mark("FD", fd))
        if text[i] == "<" and text.startswith("<", j):
            k = self.joined(text, j + 1, f.kind)
            if text.startswith("<", k):
                buf.emit("<<<")
                return k + 1
            word = _delim_word(text, k)
            if word is None:
                buf.emit("<<")
                return k
            delim, quoted, strip, end = word
            mark = self.mark("HEREDOC", self.ndocs)
            self.ndocs += 1
            f.pending.append(_Pending(mark, delim, quoted, strip))
            # 印を << の行き先として残すのは、stdin を fd 0 への最後のリダイレクトで決めるため(_fd0_source)
            buf.emit("<< %s " % mark)
            return end
        buf.emit(text[i])
        return i + 1

    def bodies(self, text, pos, f):
        """開始行の改行の次から、その文脈で開いたヒアドキュメントの中身を順に読む → 読み終えた位置。"""
        todo, f.pending = f.pending, []
        for p in todo:
            body, pos = _read_body(text, pos, p)
            if body is None:
                return len(text)   # 終端行が無い: bash は入力の終わりまでを中身にする(印は Heredoc を持たない)
            if p.quoted:
                value = body
            elif self.nest >= _MAX_HEREDOC_NEST:
                # 中身の $( の中のヒアドキュメントの中身…は入れ子の深さぶん読み直す。深さを縛らないと、入れ子を
                # 重ねた入力の重さが長さの 2 乗になり、フックの timeout で無検査で通る。読めないものとして止める
                self.unparsable = True
                return len(text)
            else:
                # 区切りを引用しなければ中身は展開を受ける。展開が 1 つでも在れば値は実行するまで決まらない
                before = len(self.exps)
                self.nest += 1
                value = self.scan(body, "hd")
                self.nest -= 1
                if len(self.exps) > before:
                    value = None
            self.docs[p.mark] = Heredoc(p.mark, value)
        return pos

    def open(self, stack, kind, start):
        stack.append(_Frame(kind, _Buf(), start, stack[-1].kind == "dq"))

    def close(self, stack, text, end):
        """展開の文脈を閉じ、外側に印を書く。中で開いて中身がまだ始まっていない << は捨てる。"""
        f = stack.pop()
        mark = self.mark("EXPAND", len(self.exps))
        inner = "".join(f.buf.parts) if f.kind in COMMAND_KINDS else None
        self.exps.append(Expansion(mark, f.kind, (text, f.start, end), inner, f.in_dq))
        stack[-1].buf.emit(mark)


def _nonce(command):
    """コマンドに _数字__ として現れない最小の数。印がコマンドの字と取り違わないようにする。"""
    used = {int(d) for d in re.findall(r"_(\d+)__", command)}
    return next(k for k in itertools.count() if k not in used)


def _skip_joins(text, j):
    """j から行継続(\\ と改行)を飛ばした位置(POSIX 2.2.1)。"""
    while text.startswith("\\", j):
        if text.startswith("\n", j + 1):
            j += 2
        elif text.startswith("\r\n", j + 1):
            j += 3
        else:
            break
    return j


def _delim_word(command, j):
    """<< の後の区切りの語 → (引用を外した語, どこかが引用されていたか, <<- か, 語の終わり)。読めなければ None。"""
    n = len(command)
    strip = command.startswith("-", j)
    if strip:
        j += 1
    while j < n and command[j] in " \t":
        j += 1
    out, quoted = [], False
    while j < n and command[j] not in _DELIM_STOP:
        c = command[j]
        if c == "\\" and _skip_joins(command, j) > j:
            j = _skip_joins(command, j)
        elif c == "'":
            k = command.find("'", j + 1)
            if k < 0:
                return None
            out.append(command[j + 1:k])
            quoted, j = True, k + 1
        elif c == '"':
            k = j + 1
            while k < n and command[k] != '"':
                if command[k] == "\\" and command[k + 1:k + 2] in ("$", "`", '"', "\\", "\n"):
                    k += 1
                out.append(command[k])
                k += 1
            if k >= n:
                return None
            quoted, j = True, k + 1
        elif c == "\\":
            if j + 1 >= n:
                return None
            out.append(command[j + 1])
            quoted, j = True, j + 2
        elif c == "`" or (c == "$" and command[j + 1:j + 2] in ("(", "{", "[")):
            return None   # 置換を含む区切りは読みを推さず、ヒアドキュメントにしない(後ろは命令として見える)
        else:
            out.append(c)
            j += 1
    if not out and not quoted:
        return None
    return "".join(out), quoted, strip, j


def _logical_line(text, pos, join):
    """pos から 1 行 → (行, 次の位置)。join なら、行末の退避されていない \\ で次の行と連結する(POSIX 2.2.1)。

    区切りを引用しないヒアドキュメントでは、bash は連結した後の行を終端と照合する。中身の値も連結した行で持つ。
    """
    parts = []
    while True:
        nl = text.find("\n", pos)
        end = len(text) if nl < 0 else nl + 1
        line, pos = text[pos:end], end
        if join and nl >= 0:
            head = line[:-1]
            if (len(head) - len(head.rstrip("\\"))) % 2:
                parts.append(head[:-1])
                if pos < len(text):
                    continue
                return "".join(parts), pos
        parts.append(line)
        return "".join(parts), pos


def _read_body(text, pos, p):
    """1 本のヒアドキュメントの中身 → (中身, 終端行の後)。終端行が無ければ (None, 入力の終わり)。

    終端行は字のまま照合する(<<- は先頭のタブを落として)。字下げした終端行を寛容に終端と読むと、
    bash が投稿する長い本文でなく、投稿されない短い本文を審査することになる。
    """
    lines = []
    while pos < len(text):
        line, pos = _logical_line(text, pos, not p.quoted)
        if p.strip:
            line = line.lstrip("\t")
        if line.rstrip("\n") == p.delim:
            return "".join(lines), pos
        lines.append(line)
    return None, len(text)


def scan_shell(command):
    """生のコマンド → Scanned。字句の文脈が閉じないか、写していない構文に当たれば None。

    text は生きた展開・ヒアドキュメント・IO_NUMBER を印に置き換え、注釈と行継続を落とした文字列で、
    tokenize にそのまま渡す。exps の inner(命令を走らせる展開の中身)も同じ規則の文字列。
    """
    nonce = _nonce(command)
    scanner = _Scanner(nonce)
    text = scanner.scan(command, "code")
    if text is None or scanner.unparsable:
        return None
    marks = re.compile(r"__(%s)(\d+)_%d__" % (MARK_TAGS, nonce))
    return Scanned(text, scanner.docs, scanner.exps, marks)


def _target_fd(fd, op):
    """リダイレクトが差し替える fd(POSIX 2.7: 番号が無ければ < の類は 0、ほかは 1。&> は 1 と 2)。"""
    return fd or ("0" if op.startswith("<") else "1")


def _fd0_source(redirects, docs):
    """fd 0 に最後に効いたリダイレクト → Heredoc か Unread。fd 0 へのリダイレクトが無ければ None。

    bash はリダイレクトを左から順に効かせるので、stdin は最後のものが決める——ヒアドキュメントの後ろの
    `< file`・`<<< "$X"`・`<&3`・2 本目のヒアドキュメントが、審査した中身と別の物を投稿させる。
    """
    src = None
    for fd, op, target in redirects:
        if _target_fd(fd, op) == "0":
            if op != "<<":
                src = Unread("ヒアドキュメント以外の stdin のリダイレクト")
            else:
                src = docs.get(target) or Unread("終端行の無いヒアドキュメント")
    return src


def _cat_heredoc(simple, docs):
    """単純コマンドが `cat <<'EOF' … EOF` 1 本(fd 0 の最後がヒアドキュメントで、fd 0 と 1 をほかに差し替えない)なら
    その Heredoc。違えば None。2>/dev/null は出力を変えない。置換の中とパイプの左の両方がこれを引く。
    """
    doc = _fd0_source(simple.redirects, docs)
    if simple.args != ["cat"] or not isinstance(doc, Heredoc):
        return None
    for fd, op, target in simple.redirects:
        if op == "<<" and target == doc.mark:
            continue
        if op in ("&>", "&>>") or _target_fd(fd, op) in ("0", "1"):
            return None
    return doc


Token = collections.namedtuple("Token", "text op")
# 語の中で読み方が変わる字。ほかの字は語の字として一括で写す
_WORD_STOP_RE = re.compile(r"""[ \t\r();<>|&\n'"\\]""")
_DQ_STOP_RE = re.compile(r'["\\]')


def tokenize(text):
    """走査が書き換えた文字列 → Token の列。引用が閉じない等で解析できなければ None。

    引用は POSIX の規則で外す(単一引用は字のまま、二重引用の中の \\ は " と \\ の前でだけ退避)。改行は区切りの
    演算子として残し、空白は空白・タブ・CR。引用しない演算子の字の並びだけを演算子にする——`--title ';'` の ; は語で、
    区切りと読むと後ろの本文旗と -R が gh の引数から外れる。語は部分の列に積んで最後に連結する(字を足して伸ばすと
    語の長さの 2 乗になり、上限の無い destgate がフックの timeout で外れる)。
    """
    tokens, word, in_word, i, n = [], [], False, 0, len(text)
    while i < n:
        m = _WORD_STOP_RE.search(text, i)
        j = n if m is None else m.start()
        if j > i:
            word.append(text[i:j])
            in_word = True
        if m is None:
            break
        c = text[j]
        if c in " \t\r" or c in OP_CHARS:
            if in_word:
                tokens.append(Token("".join(word), False))
                word, in_word = [], False
            i = j + 1
            if c in OP_CHARS:
                while i < n and text[i] in OP_CHARS:
                    i += 1
                tokens.extend(Token(op, True) for op in _split_ops(text[j:i]))
        elif c == "'":
            end = text.find("'", j + 1)
            if end < 0:
                return None
            word.append(text[j + 1:end])
            in_word, i = True, end + 1
        elif c == '"':
            i = j + 1
            while True:
                e = _DQ_STOP_RE.search(text, i)
                if e is None:
                    return None
                k = e.start()
                word.append(text[i:k])
                if text[k] == '"':
                    i = k + 1
                    break
                nxt = text[k + 1:k + 2]
                if not nxt:
                    return None
                word.append(nxt if nxt in '"\\' else "\\" + nxt)
                i = k + 2
            in_word = True
        else:   # 引用の外の \ は次の 1 字を字にする
            if j + 1 >= n:
                return None
            word.append(text[j + 1])
            in_word, i = True, j + 2
    if in_word:
        tokens.append(Token("".join(word), False))
    return tokens


def _split_ops(run):
    out, i = [], 0
    while i < len(run):
        op = next((o for o in _OPS if run.startswith(o, i)), run[i])
        out.append(op)
        i += len(op)
    return out


# 単純コマンド 1 件。before は前の単純コマンドとの間の区切りの並び(パイプの左を確かめる stdin_source が読む)
Simple = collections.namedtuple("Simple", "args redirects before")
# |・&&・|| の後の改行は区切りでなく、前の区切りの続き(POSIX の linebreak)
_LINEBREAK_AFTER = {"|", "|&", "&&", "||"}


def split_commands(tokens, marks=None):
    """演算子で区切った単純コマンドの列と、区切りの演算子の列を返す。

    リダイレクトは引数から除き、(fd か None, 演算子, 行き先) の順の列として単純コマンドに付ける
    (stdin がどこから来るかは _fd0_source が fd 0 への最後のリダイレクトで決める)。fd は走査が IO_NUMBER の
    印にした語だけ——空白で離れた数字(`… 123 <<'EOF'`・`cat 1 > p`)は引数のまま残る(POSIX 2.10.1)。
    引数の無いリダイレクトだけの単純コマンド(`> P`)も積む——落とすと、その書き込みが本文ファイルの
    「cd と cat だけ」の検査からも書き手の走査からも見えない。
    """
    cmds, seps, cur, redirects, before, i = [], [], [], [], [], 0
    while i < len(tokens):
        tok = tokens[i]
        if tok.op:
            if tok.text in REDIRECT_OPS:
                fd = None
                m = marks.fullmatch(cur[-1]) if marks and cur else None
                if m and m.group(1) == "FD":
                    fd = m.group(2)
                    cur.pop()
                redirects.append((fd, tok.text, tokens[i + 1].text if i + 1 < len(tokens) else ""))
                i += 2   # 行き先は redirects に積んだ
                continue
            # ; | & && || 改行 () は単純コマンドの区切り
            seps.append(tok.text)
            if cur or redirects:
                cmds.append(Simple(cur, redirects, tuple(before)))
                before = []
            cur, redirects = [], []
            if not (tok.text == "\n" and before[-1:] and before[-1] in _LINEBREAK_AFTER):
                before.append(tok.text)
            i += 1
            continue
        # 予約語はコマンド位置(蓄積中の単純コマンドが空)でだけ読み飛ばす。ここで捌くのは、
        # 同じ意味の `( gh … )` が `(` の区切りとして既に通っていたのに `{ gh …; }` は
        # 抜ける、という非対称を構成として消すため。gh_args と wants_skip の両方が
        # split_commands を通るので、表の読者が増えても片方だけ外れることが起きない。
        # 全トークンから除いてはいけない——`--body do` の本文が空になる(実測)。
        if not cur and tok.text in RESERVED:
            i += 1
            continue
        cur.append(tok.text)
        i += 1
    if cur or redirects:
        cmds.append(Simple(cur, redirects, tuple(before)))
    return cmds, seps


# 字列 1 つ(地の字列か、命令を走らせる展開の中身)の読み
Segment = collections.namedtuple("Segment", "exp tokens cmds seps")
# 値の決まる置換を解いた読み(_resolve)。parsed は解いた後の字列
Words = collections.namedtuple("Words", "parsed statics unsure distrust")
# 1 つのコマンドの解析。走査とトークン化と置換の解きは analyze の 1 回だけにし、gh_calls・wants_skip・destgate が
# 同じ結果を読む(parsed は解く前、words は解いた後)
Analysis = collections.namedtuple("Analysis", "scanned parsed words")


def _segments(scanned):
    """(展開か None, 字列) の列。地の字列と、命令を走らせる展開の中身。どの字列の中の gh も同じ手順で読む。"""
    return [(None, scanned.text)] + [(e, e.inner) for e in scanned.exps if e.inner is not None]


def _parse(scanned):
    """字列ごとの Segment の列。どれかが解析できなければ None。"""
    out = []
    for exp, text in _segments(scanned):
        tokens = tokenize(text)
        if tokens is None:
            return None
        out.append(Segment(exp, tokens, *split_commands(tokens, scanned.marks)))
    return out


def analyze(command):
    """コマンド → Analysis。解析できなければ None。"""
    scanned = scan_shell(command)
    parsed = _parse(scanned) if scanned is not None else None
    return None if parsed is None else Analysis(scanned, parsed, _resolve(parsed, scanned))


def unmark(args, scanned, limit=200):
    """解けなかった印を元の字へ戻す。記録と案内は書かれたとおりの字で見せ、destgate は展開を含む宛先を字で見て止める。

    展開の元の字は頭の limit 字まで——入れ子の置換の中の gh ごとに外側の長い字を写すと、長さの 2 乗になる。
    """
    def back(m):
        if m.group(1) == "EXPAND":
            text, start, end = scanned.exps[int(m.group(2))].span
            return text[start:min(end, start + limit)]
        return m.group(2) if m.group(1) == "FD" else m.group(0)
    return [scanned.marks.sub(back, a) for a in args]


# 単純コマンドの前置の読み。at は命令名の位置(無ければ語の数)、assigns は NAME=値 の語、flags は包みの旗の
# (旗, 値か None) の列
Prefix = collections.namedtuple("Prefix", "at assigns flags")


def read_prefix(tokens, start=0):
    """単純コマンドの前置(NAME=値・WRAPPERS とその旗)を tokens[start] から読む → Prefix。前置の読みはここ 1 本。"""
    i, after_wrapper, assigns, flags = start, False, [], []
    while i < len(tokens):
        tok = tokens[i]
        if ENV_PREFIX_RE.match(tok):
            assigns.append(tok)
            i += 1
        elif tok in WRAPPERS:
            i, after_wrapper = i + 1, True
        elif after_wrapper and tok.startswith("-"):
            i += 1
            if tok.startswith("--") or tok == "-":
                flag, eq, value = tok.partition("=")
                value = value if eq else None
                if value is None and flag in WRAPPER_VALUE_FLAGS:
                    value, i = (tokens[i] if i < len(tokens) else ""), i + 1
                flags.append((flag, value))
                continue
            # 短い旗は束ねて書ける(env -iC DIR・-0uNAME)。値を取る最初の字が旗で、後ろに字が残ればそれが値
            for j, c in enumerate(tok[1:], 1):
                if "-" + c not in WRAPPER_VALUE_FLAGS:
                    flags.append(("-" + c, None))
                    continue
                value = tok[j + 1:]
                if not value:
                    value, i = (tokens[i] if i < len(tokens) else ""), i + 1
                flags.append(("-" + c, value))
                break
        else:
            break
    return Prefix(i, assigns, flags)


def command_at(tokens):
    """単純コマンドの前置を読み飛ばした命令名の位置と、前置が cwd を変えるか(env -C)。命令名が無ければ位置は len(tokens)。"""
    prefix = read_prefix(tokens)
    return prefix.at, any(flag in WRAPPER_CHDIR for flag, _value in prefix.flags)


def gh_args(tokens):
    """単純コマンド 1 件が gh 呼び出しなら gh より後のトークン列を、違えば None を返す。"""
    i, _moved = command_at(tokens)
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
        if tok.startswith("-") and tok != "-":
            return None
        words.append(tok)
        i += 1
    return tuple(words)


def _flag_name(tok):
    """旗の語 → (名前, 密着した値か None)。--旗=値 と -b本文 の密着形を割る。"""
    if tok.startswith("--"):
        name, eq, value = tok.partition("=")
        return name, (value if eq else None)
    return (tok[:2], tok[2:]) if len(tok) > 2 else (tok, None)


def body_flag_kind(name, sub):
    """api でない gh の旗の名前 → 本文の種別(text・file)。本文旗でなければ None。"""
    if (name, sub) in LONG_FLAG_NOT_BODY:
        return None
    kind = LONG_TEXT_FLAGS.get(name)
    if kind is None and name in SHORT_TEXT_FLAGS:
        short_kind, posting = SHORT_TEXT_FLAGS[name]
        kind = short_kind if sub in posting else None
    return kind


def takes_value(name, sub):
    """旗の名前が、密着した値が無ければ次の語を値に取るか。classify が値を読む旗と GLOBAL_VALUE_FLAGS の 1 本の読み。"""
    if name in GLOBAL_VALUE_FLAGS:
        return True
    if sub[:1] == ("api",):
        return name in API_FIELD_FLAGS or name in API_BODY_FLAGS
    return body_flag_kind(name, sub) is not None


def classify(args, stdin=None, read_file=None, inherited=False, marks=None, unsure=None):
    """gh の引数列から (本文候補 Body の列, 検査できない本文の説明) を返す。

    args は値の決まる置換を値に解いた後の語で、解けない展開は marks(その呼び出しの nonce の印)のまま残る。
    unsure は、値の決まる形なのに信じられない置換の印 → Unread。stdin は Heredoc・Unread か、fd 0 を差し替えない
    None。read_file はパス → 本文の字か Unread(渡さなければファイルは読まない)。inherited は、stdin が
    フックを起こした側から受け継いだまま(差し替えも本文も無い)と確かめられたときだけ真。
    """
    # 倒れ先はすべて blocked.append に集める(読めなかった本文は Unread の語をそのまま積む)。テスト側が理由の一覧を
    # 実装の blocked.append("…") と Unread("…") から機械で読み、一つずつ実際に発火させて突合するため、
    # ここだけは別経路(return の直書き)を作らない。
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

    def heredoc_text(doc):
        """ヒアドキュメントの bash の値。展開を受けて決まらなければ止めた理由を積んで None。"""
        if doc.value is None:
            blocked.append("区切りを引用しないヒアドキュメントの展開")
            return None
        return Body(doc.value, False)

    def stdin_text():
        if stdin is None:
            # fd 0 を差し替えていないので、中身はフックを起こした側か、囲む構文の外のパイプから来る
            blocked.append("別プロセスからの stdin 渡し")
            return None
        if isinstance(stdin, Unread):
            blocked.append(stdin.reason)
            return None
        return heredoc_text(stdin)

    def file_text(path):
        got = read_file(path) if read_file else None
        if got is None:
            blocked.append("実ファイル指定")
            return None
        if isinstance(got, Unread):
            blocked.append(got.reason)
            return None
        return Body(got, True)

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
            raw = stdin_text() if value in ("-", "") else file_text(value)
            if raw is not None:
                try:
                    obj = json.loads(raw.text)
                except ValueError:
                    blocked.append("JSON として読めない --input")
                else:
                    body = obj.get("body") if isinstance(obj, dict) else None
                    if isinstance(body, str):
                        candidates.append(Body(body, raw.from_file))
                    elif json_has_long_text(obj):
                        # .body 以外の場所に長い文字列がある。投稿本文なのか設定値なのか
                        # 判らないので、読み役へ送らず「検査できない」として止める。
                        blocked.append("JSON の本文の位置を特定できない")
                    else:
                        not_body = True  # 本文らしい長さの文字列を持たない JSON
        elif kind == "text":
            live = [m.group(0) for m in marks.finditer(value)] if marks else []
            why = next((unsure[m] for m in live if m in (unsure or {})), None)
            if why is not None:
                blocked.append(why.reason)
            elif live:
                # 値のどこかに解けない展開が在る。bash は展開してから渡すので、字面は投稿される本文でない
                # (前後に字を伴う置換・$NAME・$1 も。単一引用の中の $ や ` は走査が展開にしない)
                blocked.append("変数・コマンド置換渡し")
            else:
                candidates.append(Body(value, False))
        elif kind == "file":
            text = stdin_text() if value in ("-", "@-") else file_text(value)
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
            name, val = _flag_name(tok)
            if is_api:
                if name in API_FIELD_FLAGS:
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
                elif name in API_BODY_FLAGS:
                    if val is None and i + 1 < n:
                        i += 1
                        val = args[i]
                    add("json", val or "")
            else:
                kind = body_flag_kind(name, sub)
                if kind:
                    if val is None and i + 1 < n:
                        i += 1
                        val = args[i]
                    add(kind, val or "")
        i += 1

    # gist は本文旗を持たず、位置引数(- は stdin、それ以外はファイル)が本文そのもの。位置引数が
    # 無ければ stdin を読む。-d/--desc・-f/--filename は値を取るので、その値を位置引数と数えない。
    # stdin を読まないのは、受け継いだままと確かめられたとき(inherited。定義は gh_calls)だけ
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
        for t in pos:
            add("file", t)
        if not pos and not inherited:
            add("file", "-")

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


def flatten(calls):
    """gh_calls の結果 → (本文候補 Body の列, 止めた理由の列)。"""
    return [b for c in calls for b in c.candidates], [r for c in calls for r in c.blocked]


SHELL_STATE = Unread("同じコマンドがシェルの状態を書く")
OTHER_COMMANDS = Unread("同じコマンドの別の命令がファイルを変えうる")
_PIPES = {"|", "|&"}


def gh_calls(command, cwd=None, read_files=False, analysis=None):
    """コマンドの gh 呼び出しごとの Call の列。解析できなければ None。

    唯一の入口で、coldread の main と destgate が同じ 1 本を通る(analysis を渡せば解析し直さない)。地の字列と、
    命令を走らせる展開の中身のどちらの gh も返す。read_files は main だけが渡す——リテラルのパスのファイルを開いて読む。
    """
    analysis = analysis or analyze(command)
    if analysis is None:
        return None
    scanned = analysis.scanned
    parsed, statics, unsure, distrust = analysis.words
    # 命令を走らせる展開は、フックが読んだ後でファイルを書き換えうる(cd "$(cp evil body; echo /)" の形)
    runs = any(e.kind in COMMAND_KINDS and e.mark not in statics for e in scanned.exps)
    why = SHELL_STATE if distrust else OTHER_COMMANDS if runs else None
    cache = _FileCache() if read_files else None
    calls = []
    for seg in parsed:
        # 受け継いだ stdin と言えるのは、地の字列にパイプも背景の & も無く、どの単純コマンドも fd 0 を
        # 差し替えないときだけ(囲む { } < f・( ) < f・exec < f・done < f の差し替えもここで落ちる)。字列ごとに 1 回決める
        inherited = (seg.exp is None and set(seg.seps) <= _INHERITS_STDIN
                     and not any(_target_fd(fd, op) == "0" for c in seg.cmds for fd, op, _t in c.redirects))
        files = _Files(seg, scanned, cwd, cache, why) if read_files else None
        for k, simple in enumerate(seg.cmds):
            args = gh_args(simple.args)
            if args is None:
                continue
            reader = (lambda path, k=k, files=files: files.read(path, k)) if files else None
            stdin = stdin_source(seg.cmds, k, scanned.docs, distrust)
            c, b = classify(args, stdin, reader, inherited, scanned.marks, unsure)
            prefix = simple.args[:len(simple.args) - len(args) - 1]
            calls.append(Call(unmark(args, scanned), c, b, tuple(unmark(prefix, scanned))))
    return calls


def static_subst_doc(seg, docs):
    """二重引用の中の $(cat <<'EOF' … EOF) のように値が静的に決まる形の置換なら、その cat が読む Heredoc。違えば None。

    中身は単純コマンド 1 本の `cat <<'EOF'`(_cat_heredoc)。引用の外の置換は語に割れるので読まない。
    """
    exp = seg.exp
    if exp.kind != "sub" or not exp.in_dq or len(seg.cmds) != 1 or not set(seg.seps) <= {"\n"}:
        return None
    return _cat_heredoc(seg.cmds[0], docs)


def _resolve(parsed, scanned):
    """字列の列 → Words。値の決まる置換は、どの読み手(命令名・旗・本文・パス・書き手の行き先・destgate の宛先と
    GH_REPO)よりも先に値へ解く。意味を決めてから解くと、gh が読む字(-F body=@path のファイル・置換の値が本文旗・
    env の前置の GH_REPO=…)と別の字を審査する。
    """
    distrust = _rebinds_commands(parsed, scanned)
    statics, unsure = _static_values(parsed, scanned, distrust)
    if statics:
        resolved = [seg._replace(cmds=[_resolved(c, statics, scanned.marks) for c in seg.cmds]) for seg in parsed]
        if not distrust and _rebinds_commands(resolved, scanned):
            # 解いた値が命令名になってシェルの状態を書く(source など)。置換の中の cat も信じない
            unsure.update(dict.fromkeys(statics, SHELL_STATE))
            return Words(parsed, {}, unsure, True)
        parsed = resolved
    return Words(parsed, statics, unsure, distrust)


def _static_values(parsed, scanned, distrust):
    """(値の決まる置換の印 → 値, 値の決まる形なのに信じられない置換の印 → Unread)。

    値は末尾の改行を全部落とした字(POSIX 2.6.3)。distrust なら cat が別物になりうるので信じない。
    """
    statics, unsure = {}, {}
    for seg in parsed:
        doc = static_subst_doc(seg, scanned.docs) if seg.exp is not None else None
        if doc is None:
            continue
        if distrust:
            unsure[seg.exp.mark] = SHELL_STATE
        elif doc.value is None:
            unsure[seg.exp.mark] = Unread("区切りを引用しないヒアドキュメントの展開")
        else:
            statics[seg.exp.mark] = doc.value.rstrip("\n")
    return statics, unsure


def _resolved(simple, statics, marks):
    """単純コマンドの語と書き手の行き先の、値の決まる置換の印を値に置き換えたもの。

    二重引用の中の置換だけを解くので、値の中の空白で語は割れない(前後の字と連結しても bash の値と同じ)。
    """
    def word(w):
        return marks.sub(lambda m: statics.get(m.group(0), m.group(0)), w)
    return simple._replace(args=[word(a) for a in simple.args],
                           redirects=[(fd, op, word(t)) for fd, op, t in simple.redirects])


def stdin_source(cmds, k, docs, distrust):
    """k 番目の単純コマンドの stdin → Heredoc か Unread。fd 0 を差し替えなければ None(受け継いだ stdin)。

    fd 0 へのリダイレクトが在れば最後のものが決める。無くて直前がパイプなら、パイプの左が `cat <<'EOF'` 1 本だけで、
    その cat 自身はパイプの右になく、cat を別物にしうる形がコマンドに無いときだけ、その中身を読む(パイプは
    末尾の改行を落とさない。POSIX 2.9.2)。( … ) | や 2 段のパイプは、左の単純コマンドの出力だけでないので読まない。
    """
    src = _fd0_source(cmds[k].redirects, docs)
    if src is not None:
        return src
    before = cmds[k].before
    if not _PIPES.intersection(before):
        return None
    if before == ("|",) and k and not distrust and not _PIPES.intersection(cmds[k - 1].before):
        doc = _cat_heredoc(cmds[k - 1], docs)
        if doc is not None:
            return doc
    return Unread("パイプからの stdin 渡し")


# 今のシェルの中で走る語(bash の組み込みと予約語。bash の man の SHELL BUILTIN COMMANDS と RESERVED WORDS)。
# シェルの状態(変数・関数・探し先の表・fd)を書けるのはこれらと代入と展開だけで、ほかの命令は子のプロセスで走る
SHELL_WORDS = {
    ".", ":", "[", "alias", "bg", "bind", "break", "builtin", "caller", "cd", "command", "compgen", "complete",
    "compopt", "continue", "declare", "dirs", "disown", "echo", "enable", "eval", "exec", "exit", "export",
    "false", "fc", "fg", "getopts", "hash", "help", "history", "jobs", "kill", "let", "local", "logout",
    "mapfile", "popd", "printf", "pushd", "pwd", "read", "readarray", "readonly", "return", "set", "shift",
    "shopt", "source", "suspend", "test", "times", "trap", "true", "type", "typeset", "ulimit", "umask",
    "unalias", "unset", "wait",
    "!", "[[", "]]", "case", "coproc", "do", "done", "elif", "else", "esac", "fi", "for", "function", "if", "in",
    "select", "then", "time", "until", "while", "{", "}",
}
# そのうち、シェルの状態を書かないと言える語(printf は -v を取らないときだけ。} は { } の閉じ)
PURE_SHELL_WORDS = {":", "[", "cd", "echo", "false", "printf", "pwd", "test", "true", "}"}
# 代入も評価もしない展開($NAME・${NAME}・$1・$@ 等と、訳文の $"…" の $)。${x:=…}・${a[i]}・${x:n}・$((…)) は
# 変数を書くか算術を評価する
_PLAIN_PARAM_RE = re.compile(r"\$(?:{0}|\{{(?:{0})\}})?".format(_PARAM_RE.pattern))


def _rebinds_commands(parsed, scanned):
    """コマンドのどこかで cat や cd が別物になりうるか(シェルの状態を書かないと言えない形が在るか)。

    書かないと言えるのは、子のプロセスで走る命令(前置の代入はその命令にだけ効く)・PURE_SHELL_WORDS・
    代入も評価もしない展開だけ。ほか(関数の定義・代入だけの単純コマンド・ほかの組み込みと予約語・(( ))・
    代入や算術の展開)が 1 つでも在れば真——PATH を書く経路(read・printf -v・for・declare -n・
    BASH_CMDS[cat]=…・$((PATH=0)) …)を数え上げずに閉じる。
    真なら、置換の中の cat もファイルの書き手も信じない——フックが読んだ本文と bash が投稿する本文がずれる。
    """
    if any(e.kind not in COMMAND_KINDS and not _PLAIN_PARAM_RE.fullmatch(e.span[0][e.span[1]:e.span[2]])
           for e in scanned.exps):
        return True
    for seg in parsed:
        if any(a.op and a.text == "(" and b.op and b.text in ("(", ")") for a, b in zip(seg.tokens, seg.tokens[1:])):
            return True   # name() の関数の定義と (( )) の算術
        if any(not _pure(c.args) for c in seg.cmds):
            return True
    return False


def _pure(args):
    """単純コマンド 1 件がシェルの状態を書かないと言えるか(_rebinds_commands)。"""
    i, _moved = command_at(args)
    if i == len(args):
        return not args   # リダイレクトだけなら書かない。代入だけ・exec だけは書く
    name = args[i]
    if "=" in name:
        return False   # PATH+=…・a[i]=… の代入(ENV_PREFIX_RE に掛からない形)
    if name not in SHELL_WORDS:
        return True
    return name in PURE_SHELL_WORDS and not i and not (name == "printf" and args[1:2] and args[1].startswith("-v"))


# 本文ファイルのパスで、bash の展開を受けるので字面と gh が開くパスが一致しない字
# ($ ` は展開、* ? [ { はグロブとブレース。先頭の ~ はホームの展開で別に見る)
_EXPANDED_PATH_RE = re.compile(r"[$`*?\[{]")
# 前が終わってから次が始まる区切り。| と & は並行に走り、|| は前の失敗で走る
_SEQUENTIAL = {";", "\n", "&&"}
# 各コマンドが地のシェルの stdin を受け継ぐ区切り。| は前の出力を、& は /dev/null を stdin にする
_INHERITS_STDIN = _SEQUENTIAL | {"||", "(", ")"}


def literal_path(path, marks=None):
    return (bool(path) and not path.startswith("~") and not _EXPANDED_PATH_RE.search(path)
            and not (marks and marks.search(path)))


def writes_file(op, target):
    """このリダイレクトがファイルを書く(開くときに作る・消す)か。/dev/null と fd の複製(>&2・>&-)は書かない。"""
    if ">" not in op:
        return False
    return target != "/dev/null" and not (op == ">&" and (target.isdigit() or target == "-"))


class _Files:
    """1 つの字列の中で gh が本文として読むファイル。gh の位置に依らない判定(ほかの命令・書き手の行き先)は
    字列ごとに 1 回だけ作る——gh の呼び出しごとに作り直すと、gh を並べた入力で重さが 2 乗になる。
    """

    def __init__(self, seg, scanned, cwd, cache, why):
        self.seg, self.marks, self.docs, self.cwd, self.cache = seg, scanned.marks, scanned.docs, cwd, cache
        # why は gh_calls が決める字列の外の理由(シェルの状態を書く・命令を走らせる展開)。区切りは順に走るものだけ
        self.why = why or (None if set(seg.seps) <= _SEQUENTIAL else OTHER_COMMANDS)
        self.others = None
        self.writers = {}

    def read(self, path, k):
        """k 番目の単純コマンド(gh)が本文として読むファイル path の中身の字か、フックの時点で決まらない理由(Unread)。

        同じ命令の他の単純コマンドは cd と cat だけを許す——それ以外のコマンドはどのファイルを書くか
        分からない(cp・sed -i・git checkout・gh release download …)。
        path を書くリダイレクトが無ければ、今のファイルを読む。前の `cat > path <<'EOF'` 1 本だけが
        書くなら、gh が読むのはそのヒアドキュメントの値(フックの時点のファイルは古い中身)。
        フックが読んだ後で gh が読むまでに別のプロセスが書き換える余地(CWE-367)は残る(gates/README.md)。
        """
        if self.why:
            return self.why
        cmds = self.seg.cmds
        if self.others is None:
            self.others = [j for j, c in enumerate(cmds) if not _cd_or_cat(c.args)][:2]
            self.cd = any(c.args[:1] == ["cd"] for c in cmds)
        if any(j != k for j in self.others):
            return OTHER_COMMANDS
        moved = self.cd or command_at(cmds[k].args)[1]   # cd・env -C
        target = self.resolve(path, moved)
        if target is None:
            return Unread("字のまま決まらないパス")
        writers = self.writers_of(moved)
        if isinstance(writers, Unread):
            return writers
        hits = writers.get(target, set()) | writers.get(_inode(target), set())   # ハードリンクは realpath で揃わない
        if not hits:
            return self.cache.read(target)
        if len(hits) > 1:
            return OTHER_COMMANDS
        (j, n), = hits
        c = cmds[j]
        fd, op, _dest = c.redirects[n]
        doc = _fd0_source(c.redirects, self.docs)
        if (j > k or c.args != ["cat"] or op not in (">", ">|") or _target_fd(fd, op) != "1"
                or not isinstance(doc, Heredoc)
                or sum(writes_file(o, d) for _fd, o, d in c.redirects) != 1 or not writable(target)):
            return OTHER_COMMANDS
        if doc.value is None:
            return Unread("区切りを引用しないヒアドキュメントの展開")
        return doc.value

    def resolve(self, p, moved):
        """パス → 実パス。字のまま決まらない(展開・グロブ・~・cd の後の相対パス・cwd の無い相対パス)なら None。"""
        if not literal_path(p, self.marks):
            return None
        if os.path.isabs(p):
            return os.path.realpath(p)
        if moved or not (self.cwd and os.path.isabs(self.cwd)):
            return None   # cd の後の相対パスは、どこを指すかが cd の成否で変わる
        return os.path.realpath(os.path.join(self.cwd, p))

    def writers_of(self, moved):
        """ファイルを書くリダイレクトの、実パスと (st_dev, st_ino) → {(単純コマンドの位置, リダイレクトの位置)}。
        行き先の決まらない書き込みが 1 つでも在れば Unread(その書き込みは path かもしれない)。"""
        if moved not in self.writers:
            index = {}
            for j, c in enumerate(self.seg.cmds):
                for n, (_fd, op, dest) in enumerate(c.redirects):
                    if not writes_file(op, dest):
                        continue
                    where = self.resolve(dest, moved)
                    if where is None:
                        self.writers[moved] = OTHER_COMMANDS
                        return OTHER_COMMANDS
                    for key in (where, _inode(where)):
                        if key is not None:
                            index.setdefault(key, set()).add((j, n))
            self.writers[moved] = index
        return self.writers[moved]


def _cd_or_cat(args):
    """本文ファイルと同じコマンドに並べてよい単純コマンド(cd と、書き手になりうる素の cat)か。"""
    return args[:1] == ["cd"] or args == ["cat"]


def _inode(path):
    try:
        st = os.stat(path)
    except OSError:
        return None   # まだ無い
    return st.st_dev, st.st_ino


def writable(path):
    """`cat > path` が書けるか。書けずに失敗すると、; と改行の後の gh は前からある中身を読む。"""
    if os.path.lexists(path):
        return os.path.isfile(path) and os.access(path, os.W_OK)
    parent = os.path.dirname(path)
    return os.path.isdir(parent) and os.access(parent, os.W_OK)


class _FileCache:
    """gh_calls 1 回の中で読んだ本文ファイル。同じ実パスは 1 度だけ開き、読むバイトの合計を 1 ファイルの上限
    までに縛る——同じ大きなファイルや別々のファイルを位置引数に数万並べると、読む量でフックの timeout に届き、
    無検査で通る。
    """

    def __init__(self):
        self.got, self.left = {}, MAX_LEN * 4

    def read(self, path):
        if path not in self.got:
            got = read_body_file(path, self.left)
            if isinstance(got, str):
                self.left -= len(got.encode("utf-8"))
            self.got[path] = got
        return self.got[path]


# 本文ファイルを読まなかった原因。直し方が違うので語を分ける(無い・権限・読む間の書き換え／ディレクトリ・FIFO／
# 大きさ／文字コード)
UNREADABLE = Unread("本文ファイルを読めない")
NOT_REGULAR = Unread("本文ファイルが通常のファイルでない")
TOO_LARGE = Unread("本文ファイルが上限より大きい")
NOT_UTF8 = Unread("本文ファイルが UTF-8 でない")


def read_body_file(path, budget=None):
    """通常のファイルを UTF-8 で読む → 字か Unread。開けない・読み切れない・通常のファイルでない・大きすぎる・
    UTF-8 でない、または budget(この呼び出しで読んでよい残りのバイト数)を超えるなら読まない。

    開いてから fstat で確かめる(stat と open の間に差し替えられても FIFO を掴まない)。O_NONBLOCK で
    開くのは、FIFO が書き手を待ってフックを止めないため——止まるとフックの timeout で無検査で通る。
    期限は足さない。大きさの食い違いは、読む間の書き換えと、大きさ 0 で中身の在る類(/proc)を除く。
    """
    limit = MAX_LEN * 4   # UTF-8 の 1 字は 4 バイトまで
    flags = os.O_RDONLY
    for name in ("O_NONBLOCK", "O_NOCTTY", "O_BINARY"):
        flags |= getattr(os, name, 0)
    try:
        fd = os.open(path, flags)
    except OSError:
        return NOT_REGULAR if os.path.isdir(path) else UNREADABLE   # Windows はディレクトリを開けない
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode):
            return NOT_REGULAR
        if st.st_size > limit:
            return TOO_LARGE
        if budget is not None and st.st_size > budget:
            return Unread("本文ファイルの合計が上限を超える")
        chunks, got = [], 0
        while got <= limit:
            chunk = os.read(fd, limit + 1 - got)
            if not chunk:
                break
            chunks.append(chunk)
            got += len(chunk)
    except OSError:
        return UNREADABLE
    finally:
        os.close(fd)
    data = b"".join(chunks)
    if len(data) != st.st_size:
        return UNREADABLE
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return NOT_UTF8
    return text if len(text) <= MAX_LEN else TOO_LARGE


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


def repo_flags(args, sub):
    """-R/--repo の値を書かれた順に(gh は最後の値を使う)。destgate と repo_flag が引く -R の読みの 1 本。

    ほかの旗の値の位置と -- より後ろは読まない。値の読み飛ばしは classify と同じ表(takes_value)で決める——値を取る
    旗を取らないと読み違えるのは止める側(値の位置の語を -R と数える)、逆は素通し(後ろの -R を値として飛ばす)なので、
    表に無い旗は値を取らないと見る。
    """
    sub = sub or ()
    out, i = [], 0
    while i < len(args):
        tok = args[i]
        i += 1
        if tok == "--":
            break
        if not tok.startswith("-") or tok == "-":
            continue
        if tok.startswith("--"):
            name, value = _flag_name(tok)
            if name != "--repo" and not takes_value(name, sub):
                continue
        else:
            name, value = _short_bundle(tok, sub)
            if name is None:
                continue
        if value is None:
            value = args[i] if i < len(args) else ""
            i += 1
        if name in ("-R", "--repo"):
            out.append(value)
    return out


def _short_bundle(tok, sub):
    """短い旗の束(-aR evil/x・-Rx・-bR)→ (値を取る旗, 密着した値か None)。値を取る旗が無ければ (None, None)。

    pflag と同じく、値を取らない字を飛ばし、値を取る最初の字の後ろの字(先頭の = は落とす)をその値にする。
    """
    for j, c in enumerate(tok[1:], 1):
        if c == "R" or takes_value("-" + c, sub):
            rest = tok[j + 1:]
            return "-" + c, (rest[1:] if rest.startswith("=") else rest) or None
    return None, None


def repo_flag(args, sub):
    """gh が使う -R/--repo の値(最後のもの)。無ければ None(gh はカレントの git remote を使う)。"""
    values = repo_flags(args, sub)
    return values[-1] if values else None


def api_path(sub):
    """gh api のパス(スキームとホスト・先頭の /・? 以降を落とす)。api のパスでなければ None。"""
    if sub[:1] != ("api",) or len(sub) < 2:
        return None
    return re.sub(r"^[a-z+]+://[^/]+", "", sub[1]).lstrip("/").split("?", 1)[0]


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
        else:
            return tok
        i += 1
    return None


def destination(args, sub):
    """投稿先が既に在るスレッドなら (種別, owner/repo か None, 番号か ID か None)。新規作成等は None。"""
    if not sub:
        return None
    if sub[0] == "api":
        path = api_path(sub)
        if path is None:
            return None
        for rx, kind in API_DEST_RES:
            m = rx.match(path)
            if m:
                return (kind, m.group(1) + "/" + m.group(2), m.group(3))
        return None
    if sub in PR_THREAD_SUBS:
        return ("pr", repo_flag(args, sub), positional_after(args, sub))
    if sub in ISSUE_THREAD_SUBS:
        return ("issue", repo_flag(args, sub), positional_after(args, sub))
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


def deny_streak(session, target):
    """同じ書き手(session)が同じ投稿先(target)で直近に連続して止められた (回数, その間の本文の長さの列・古い順)。

    log は profile で共有なので、他の session の行は無いものとして飛ばす——数えると並行セッションの
    deny が自分の連続数を増やし、他所の skip が自分の案内を消す(2026-09-07 に実測)。同じ書き手でも
    別の投稿先の deny は数えない(長さの列が別の本文の混ざりになる)が、allow・skip は投稿先に関わらず
    連続を切る。session の無い入力は、同じく session の無い行だけを数える。
    """
    try:
        with open(DENY_LOG, encoding="utf-8") as f:
            lines = f.readlines()[-400:]
    except OSError:
        return 0, []
    n, lens = 0, []
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
        n += 1
        if len(parts) >= 4 and parts[3].isdigit():
            lens.append(int(parts[3]))  # 逆順に辿っているので後で戻す
    lens.reverse()
    return n, lens


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


def reader_argv(claude_bin):
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
            "--model", os.environ.get("COLDREAD_MODEL", "sonnet"),
            "--effort", os.environ.get("COLDREAD_EFFORT", "medium"),
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


def run_reader(prompt: str):
    """読み役を起動して出力文字列を返す。prompt は依頼文+本文。失敗は例外。"""
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
            reader_argv(claude_bin), input=prompt.encode("utf-8"),
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


def wants_skip(command, analysis=None):
    """逃げ道が書き手の前置として置かれているか。本文に文字列が入っているだけでは効かせない。

    部分文字列一致にすると、門番自身の話題を投稿する本文で門番が黙って外れる(実測)。
    2 段構えなのは、逃げ道の主用途が「解析できないコマンドを通す」ことだから——
    解析前の先頭一致は必ず効かせ、解析できたときに限って cd や && の先の前置も拾う。
    解析は gh_calls と同じ走査と字列の列を通る(置換の中の gh に門番が掛かるなら、逃げ道もそこで効く)。
    """
    if SKIP_PREFIX_RE.match(command):
        return True
    analysis = analysis or analyze(command)
    if analysis is None:
        return False
    # 前置が途切れたら、そこから先は引数か本文
    return any(SKIP_TOKEN in cmd.args[:command_at(cmd.args)[0]] for seg in analysis.parsed for cmd in seg.cmds)


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

    # log の各行に書き手(session)・版・投稿先を残す。連続 deny は session ごとに数える
    sid = str(payload.get("session_id") or "")[:8]
    target = "-"  # 投稿先が分かった時点で付け替える(record は呼んだ時の束縛を読む)

    def record(text):
        log_line(DENY_LOG, "%s\tsid=%s\tv=%s\tto=%s" % (text, sid, GATE_VERSION, target))

    # 読み役の中で自分がもう一度発火すると、読み役が読み役を起こす入れ子になる
    # (深さぶんの待ち時間になり、外側はフックのタイムアウトで無検査のまま通る)。
    # 読み役の道具を殺す --tools "" とは別の機構にしてある——あちらは「読み役が本文中の
    # 指示で動かない」ための処置で、起動の仕方(差し替えの読み役)に依存する。こちらは
    # 起動の仕方に関わらず入れ子を止める。allow に落ちる以上、逃げ道と同じく記録を残す。
    if os.environ.get("COLDREAD_IN_READER") == "1":
        log_line(SKIP_LOG, "in-reader: " + command[:150].replace("\n", " "))
        allow()

    if not GH_WORD_RE.search(command):
        allow()

    def skip():
        log_line(SKIP_LOG, command[:200].replace("\n", " "))
        record("skip")
        allow()

    # 下限は「コマンドが短ければ本文も短い」を前提にした定型返信の素通し。本文旗のファイルから読んだ本文は
    # この前提に乗らないので、短いコマンドでもそれだけは審査に回す(下で from_file の本文だけを残す)
    short = len(command) < MIN_LEN
    # 解析を使わない先頭一致の逃げ道だけを上限より前に見る。解析は上限と try の内側でしか走らせない——
    # 走査の例外がフックの外へ抜けるとフックのクラッシュ(=PreToolUse は続行)、重い入力は timeout で、
    # どちらも無検査で通る
    if SKIP_PREFIX_RE.match(command) and not short:
        skip()
    if len(command) > MAX_LEN:
        record("deny\tmaxlen")
        deny(
            "外部投稿ゲート: このコマンドは長すぎて解析しない(%d 文字 > 上限 %d)。\n"
            % (len(command), MAX_LEN)
            + "本文を短くして再実行すること"
            "(上限を変えるにはフックを起動する側の環境変数 COLDREAD_MAX_LEN を設定する——"
            "コマンド先頭に書いてもフック自身には届かない)。\n" + ESCAPE_NOTE
        )

    # 解析の失敗は例外の形でも起こりうる(壊れた JSON の再帰・想定外の入力)。
    # 「引用が閉じない」を deny にしているのに例外だけ素通りでは、検査を避ける口になる。
    # 捕まえるのは Exception 全体で、ValueError に狭めるな——狭めた瞬間に、それ以外の例外は
    # フックのクラッシュ(=PreToolUse は続行)になって無検査で通る。
    try:
        analysis = analyze(command)
        wants = wants_skip(command, analysis) if analysis else bool(SKIP_PREFIX_RE.match(command))
        calls = (None if analysis is None or (wants and not short)
                 else gh_calls(command, payload.get("cwd") or None, read_files=True, analysis=analysis))
    except Exception as exc:
        wants, calls, parse_error, parse_kind = False, None, str(exc)[:150], type(exc).__name__
    else:
        parse_error, parse_kind = "引用が閉じていない・写していない構文等", "unparseable"
    if short:
        # 短いコマンドで止めるのはファイルの本文の詰まりだけ。読めなかった物・止めた理由では止めない
        if calls is None:
            # 本文ファイルの審査が外れた回を数えられるよう残す(値は書かない)
            log_line(MISS_LOG, "parse-error\t" + parse_kind)
            allow()
        candidates = [b for b in flatten(calls)[0] if b.from_file and len(b.text.strip()) >= 200]
        if not candidates:
            allow()
        blocked = []
    if wants:
        skip()
    if calls is None:
        record("deny\tparse-fail")
        deny(
            "外部投稿ゲート: このコマンドは解析できない(%s)。" % parse_error
            + "gh を含むため、投稿かどうか確かめられないものは通せない。\n"
            "引用を直して再実行すること(置換の中の case は、枝の型を (型) と括弧で囲めば読める)。"
            "宛先の許可制(destgate)が有効なら、解析できないコマンドは destgate も止め、そちらは COLDREAD_SKIP=1 では"
            "外れない。\n" + ESCAPE_NOTE
        )

    if not short:
        candidates, blocked = flatten(calls)
    # 「検査できない本文がある」は、別の本文が読めたかどうかと独立に止める。
    # ここを bodies の有無に従属させると、読める本文と同居した投稿が無検査で通る。
    if blocked:
        # 記録の列は語彙に出ない , で連結する(理由の語が「・」を含むので、表示と同じ連結では数えられない)
        record("deny\tblocked\t" + ",".join(sorted(set(blocked))))   # 理由は classify の固定の語彙で、値は含まない
        deny(
            "外部投稿ゲート: この投稿は本文をコマンドから取り出せない形をしている(%s)。"
            "検査できないものは通せない。\n"
            "本文は静的に読める形で渡して再実行すること: 本文旗(--body / --notes 等)に直接書く・"
            "--body-file - <<'EOF' … EOF・gh gist create - <<'EOF' … EOF・"
            "本文旗の値を \"$(cat <<'EOF' … EOF)\" にする。"
            "<<'EOF' と区切りを引用すれば、同じ本文を字のまま出せる"
            "(<<EOF と引用しないと bash が $ と ` を展開するので止まる。引用しない <<EOF で行末の \\ は"
            "次の行とつながるので、字のまま出すなら \\\\ と退避する)。"
            "ファイルで渡すなら、$ や ~ を含まないパスの、UTF-8 で上限(%d 字)以内の通常のファイルにする"
            "(同じ命令に並べてよいのは cd と、そのファイルを書く cat > パス <<'EOF' だけ。"
            "変数のパスは読まない)。"
            "パイプで渡すなら、cat <<'EOF' 1 本から gh 1 本へ直接つなぐ。"
            "ヒアドキュメントの終端行は字下げせず、区切りの語だけの行にする。"
            "同じコマンドに set・export・source・関数の定義・代入・for や if などが在ると、置換もファイルも読まない"
            "(それらは別のコマンドに分ける)。\n"
            % ("・".join(sorted(set(blocked))), MAX_LEN) + ESCAPE_NOTE
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

    bodies = [b for b in candidates if len(b.text.strip()) >= 200]
    if not bodies:
        allow()
    # 複数の本文が同居するときは最長を代表として読ませる(全部読ませると読み役の回数と
    # 待ち時間が本文の数だけ増える)。取りこぼしの受容は gates/README.md「網の射程」。
    chosen = max(bodies, key=lambda b: len(b.text))
    body = chosen.text

    # 投稿先がスレッドなら、読み手が画面で既に見ているものを取って渡す。取れなければ
    # 文脈ゼロに倒す——検査は走らせ、画面に有るものへの詰まりは無視してよいと書き手に伝える
    # 投稿先の解釈で例外が出ても門番を落とさない(落ちるとフックのクラッシュ=無検査で通る)。
    # 解釈できないときは文脈ゼロ側(厳しい側)へ倒れる
    try:
        args = next(c.args for c in calls if chosen in c.candidates)
        sub = subcommand(args)
        dest = destination(args, sub)
    except Exception:
        sub, dest = None, None
    target = target_label(sub, dest)
    screen, screen_error = None, None
    if dest is not None:
        try:
            screen = screen_for(dest, payload.get("cwd") or "", body)
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
        record("deny\treader-down")
        deny(
            "外部投稿ゲート: coldreader(文脈ゼロの読み手)の起動に失敗した(%s)。\n" % str(exc)[:150]
            + "手動で検査するなら skill『coldread』の手順で coldreader を立てること。\n"
            + ESCAPE_NOTE
        )

    # **報告の形をしていない出力を「詰まりゼロ」と読まない。** 認証落ちは例外にならない——
    # 実測 2026-09-15: 素で起こした claude は『Failed to authenticate: OAuth session expired and
    # could not be refreshed』の 1 行を**標準出力に・終了コード 0 で**返した。rc も空出力も踏まないので
    # ここまで素通りし、ラベルが 1 つも無いまま allow に落ちていた(＝検査せずに投稿が出る fail-open)。
    # 依頼文が許す出力は CLEAN かラベル行の 2 種類だけなので、どちらでもなければ「検査できない」として止める。
    if "CLEAN" not in out and not any(LABEL_RE.match(line.strip()) for line in out.splitlines()):
        record("deny\treader-shape")
        deny(
            "外部投稿ゲート: coldreader の出力が報告の形(CLEAN かラベル行)をしていない: %r\n" % out[:150]
            + "検査できていないので止める(認証切れはこの形で出る——読み役の標準エラーを見よ)。\n"
            + ESCAPE_NOTE
        )

    # ラベルはコロンまで見る。行頭の語だけで拾うと「詰まりは無い」のような地の文が
    # 詰まりに数えられ、指摘ゼロの本文が deny になる(補完の追加で自由文の行が増えたため)。
    found = {label: [] for label in LABELS}
    for line in out.splitlines():
        line = line.strip()
        m = LABEL_RE.match(line)
        if m and not NONE_RE.match(line[m.end():].strip()):
            found[m.group(1)].append(line)
    blocking, questions, fills, redundant, traced = (
        found["詰まり"], found["疑問"], found["補完"], found["冗長"], found["なぞり"])

    # 詰まりとなぞりの有無だけで決める。以前は「最終行が CLEAN なら」も allow の条件だったが、
    # それだと詰まりを列挙した後に CLEAN と書かれた出力が通ってしまう。読み役に本文の
    # 説明以外を書かせる欄(補完)を足したぶん、末尾が CLEAN で終わる形は出やすくなっている。
    if not any(found[label] for label, stops in LABELS.items() if stops):
        record("allow\t%d\t%s" % (len(body), mode))
        extra = "\n".join(filter(None, (
            SCOPE_NOTE,
            screen_note,
            VERSION_NOTE,
            section("coldreader が推測で埋めた箇所——意図と違うなら投稿を編集して直すこと:", fills),
            section("画面に有るものを本文で説明している箇所(削ってよい。投稿を編集して短くできる):", redundant),
            section("投稿は通したが、coldreader(初見の読み手)に残った疑問"
                    "(必要なら本文に反映して編集してよい):", questions),
        )))
        out = {"hookEventName": "PreToolUse", "additionalContext": extra}
        # 審査の通過は権限の付与ではない。本文がコマンドの字に無い(ファイルから読んだ)投稿と、下限より短い
        # コマンドは、人の権限の確認を残す(allow は確認を飛ばす)。本文がコマンドの字に在る長いコマンドの allow は
        # 0.11 系からの振る舞い
        if not short and not any(b.from_file for b in candidates):
            out.update(permissionDecision="allow", permissionDecisionReason="coldreader の検査を通過(詰まりゼロ)")
        print(json.dumps({"hookSpecificOutput": out}, ensure_ascii=False))
        sys.exit(0)

    streak, lens = deny_streak(sid, target)
    streak += 1
    lens.append(len(body))
    record("deny\tfinding\t%d\t%s" % (len(body), mode))
    role = ("この返信を受け取る相手として、スレッドの画面と本文を読んだ別プロセスの読み手"
            if mode == "screen" else "文脈ゼロの別プロセスの読み手")
    head = (
        "外部投稿ゲート: coldreader(%s)がこの本文で詰まった。詰まりを直してから"
        "同じ形で再実行すること(再実行時は直した本文を新しい coldreader が検査する):" % role
    )
    if streak >= 3:
        # 先頭に置く。末尾に置いた案内は 36 回無視された(PR 1583。詰まりの欄が「直せば通る」と
        # 読める限り、書き手は次の 1 回を試す)。本文がどれだけ膨れたかは 1 回ごとの数列で見せる——
        # 足すたびに増えた本文が新しい詰まりを生む、という輪を書き手が自分の数字で見られるように。
        # 出させるのは「今の本文」でなく「最初の本文」——旧文言は膨れた版を出せと読めた(1429 で実測)
        grown = ("。この連続の間に本文は %s 字に増えた" % " → ".join("{:,}".format(n) for n in lens)
                 if len(lens) >= 2 and lens[-1] > lens[0] else "")
        head = (
            "【%d 回連続で止まっている——ここから先は本文を足して直さない】coldreader の指摘は読み手ごとに"
            "揺れ、足した文がまた新しい指摘を生む%s。この連続の最初の本文に戻し、画面と本文を合わせても"
            "解けない語の初出 1 か所に中身を添えるだけにする。残る指摘の採否は自分で決め、採らないなら "
            "COLDREAD_SKIP=1 でその本文を出す(記録が残る)。\n\n" % (streak, grown)
        ) + head
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
    deny(
        head + "\n\n" + detail[:1500]
        + "\n\n" + howto + "詳細は skill『coldread』。\n" + SCOPE_NOTE
        + ("\n" + screen_note if screen_note else "")
        + ("" if streak >= 3 else "\n\n" + ESCAPE_NOTE)
    )


if __name__ == "__main__":
    main()
