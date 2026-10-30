"""waitgate: 手で書いた待ちのループを、Bash で走る前に止める PreToolUse フック。

止めるのは次の 2 つ。
1. `while`・`until` のループ、または `sleep` を回す `for` のループを持つコマンドの中の、
   `pgrep`・`pidwait` の `-f`(`--full`)、`pkill -0`、`ps … | grep`。コマンド行の全体から探すので、
   同じ文字列で待つ別のシェル(同じ形の待ちのループ)に当たり、互いに相手を見つけて終わらない
   (my_notes の調べものの部署が約 11 時間止まった)。`sleep` の無い `for` は回数が決まっていて待ちでないので、
   `ps | grep` は通す(`pgrep -f` などは止める)。`while read` は行を読み終えれば終わるので見ない。
2. `sleep` を回す `while`・`until` のループ。待つ条件が満たされなければ終わらない。前景で打っても、
   Claude Code は時間の上限に届いた Bash のコマンドを止めずに裏へ移す(公式 https://code.claude.com/docs/en/tools-reference
   の「Foreground commands that move to the background」)ので、終わらずに残る(28 時間・16 時間回った会話がある)。
   そのため前景か裏かを問わず止める。
ループの語はコマンドの頭に在るものだけを見る(`--until` のようなオプションは見ない)。終わる条件の無い `for ((;;))` は
`while` と同じに見る。引用符の中とヒアドキュメントの
中身は見ないが、`bash -c` と `eval` の引数と、ダブルクォートの中の `$( )` と `` ` ` `` は見る。
見えない形: `awk` で `ps` の出力を絞る形、`python3 -c` の中のループ、別のスクリプトの中のループ。

写した元: my_notes の master 2d951aab の tools/no_wait_loop.py(判定)と tools/no_preread.py の executed_text
(引用符とヒアドキュメントを外す)。変えたのは、落ちたら止める・止めた記録を書く・`while read` を外す・`for ((;;))` を待ちと見る・`bash -o pipefail -c`
の中も見る・コメントを外す・パスで呼ぶシェルと長いオプションのシェル(`/bin/bash -c`・`bash --norc -c`)の中も見る・引用符とコメントの中の `<<WORD` をヒアドキュメントと読まない(ダブルクォートの中の `$( )` の中は読む)・
終わりの語を `\\` で引用する形と `-` を持つ形(`<<\\EOF`・`<<'END-1'`)もヒアドキュメントと読む・
`$( )` と `` ` ` `` の中のヒアドキュメントは閉じる記号(`EOF)`・`` EOF` ``)でも終わると読む、の 10 個。
"""

import json
import os
import re
import sys

sys.dont_write_bytecode = True
# `sys.path[0]` に頼らない(coldread-gate.py が claude_auth を読むのと同じ)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import gate_shell  # noqa: E402

# コマンドの頭(行頭・区切りの記号・括弧・do/then/else/time の後)に在るループの語
# 区切りの後は空白とタブだけを飛ばす(改行は区切りの側で読む)。\s* にすると、空の行が続く所で改行ごとに残りの改行の全部を
# 読み直して長さの 2 乗の手間になり、8 万行で 50 秒かかってフックの時間切れで通っていた
_LOOP_HEAD = r"(?:^|[;&|(){}!\n]|\b(?:do|then|else|time)\b)[ \t]*"
FOR = re.compile(_LOOP_HEAD + r"for\s")
# `while read` は行を読み終えれば終わるので待ちでない(`ps aux | grep x | while read p; do kill $p; done`)。
# 終わる条件の無い `for ((;;))` は while と同じに見る(写した元から足した)
WHILE_UNTIL = re.compile(_LOOP_HEAD + r"(?:(?:while|until)\s+(?!(?:IFS=\S*\s+)?read\b)|for\s*\(\([^;]*;\s*;)")
# コマンド行の全体から探す形。pgrep・pidwait の -f(-fl・-af など)と --full、pkill -0(生きているかだけを見る)、
# ps の出力を grep する形。`2>&1` の & では切らない
_ARGS = r"(?:[^|;&\n]|\d?>&\d?)*?"
PGREP_FULL = re.compile(
    r"\b(?:pgrep|pidwait)\b" + _ARGS + r"\s(?:-[A-Za-z]*f[A-Za-z]*|--full)\b"
    r"|\bpkill\b" + _ARGS + r"\s-0\b"
)
PS_GREP = re.compile(r"\bps\b(?:[^;&\n]|\d?>&\d?)*\|&?\s*(?:grep|egrep|fgrep|rg)\b")
SLEEP = re.compile(r"\bsleep\b")
# 前段の絞り: ループの語が無ければ解析しない
LOOP_WORD_RE = re.compile(r"\b(?:while|until|for)\b")

# 後に続く引用符の中身をシェルとして走らせるもの(`bash -c '…'`、`eval "…"`)
# 値を取る -o・-O(`bash -o pipefail -c`・`bash -euo pipefail -c`)の値と、長いオプション(`bash --norc -c`)も飛ばす。
# パスで呼ぶシェル(`/bin/bash -c`)も同じに見る(写した元から足した)
# -o の値は - で始めない。始めてよいと `-o -o -o …` の割り方が語の数の指数で増え、当たらないときに読み終えずフックの時間切れで通る
_SHELL_OPTS = r"(?:(?:-\w*[oO]\s+\w[\w-]*|--[\w-]*|-\w+)\s+)*"
_SHELL = r"(?:[^\s;&|(`'\"]*/)?(?:ba|z|da)?sh"
SHELL_ARGUMENT = re.compile(r"(?:^|[\s;&|(`])(?:" + _SHELL + r"\s+" + _SHELL_OPTS + r"-\w*c\w*|eval)\s*$")
# SHELL_ARGUMENT の当たりの末尾の語と、シェルの語の後に置ける -o・-O の値(shell_argument_before が後ろから戻るのに使う)
SHELL_ARGUMENT_WORD = re.compile(r"(?:-\w*c\w*|eval)$")
VALUE_OPTION = re.compile(r"-\w*[oO]")
OPTION_VALUE = re.compile(r"[\w-]+")
SHELL_ARGUMENT_REACH = 1000   # シェルの語と `-c` の間に置ける語の数の上限(ふつうは数個)
# ヒアドキュメントを読むのがシェルか(`bash <<EOF`)
SHELL_STDIN = re.compile(r"(?:^|[\s;&|(`])" + _SHELL + r"(?:\s+" + _SHELL_OPTS + r")?\s*$")
# `<<<`(here-string)は除く。終わりの語は引用符で囲む形(`<<'END-1'`)と、`\` を前に付けて引用する形(`<<\EOF`)と、
# 引用した片とそのままの片を続けた形(`<<"EO"F`・`<<E\OF`)も読み、シェルと同じく引用を外した字を終わりの語にする。
# 引用の無い頭は英字か _ だけにする(`$((1<<2))` の 2 を終わりの語と読んで後の行を中身と見て落とさない)
_HEREDOC_PIECE = r"'[^'\n]*'|\"[^\"\n]*\"|\\[^\n]"
HEREDOC = re.compile(r"(?<!<)<<(?!<)(?P<dash>-?)[ \t]*(?P<raw>(?:%s|[A-Za-z_])(?:%s|[^\s;&|()<>'\"\\`])*)" % (_HEREDOC_PIECE, _HEREDOC_PIECE))
HEREDOC_PIECE = re.compile(r"'([^'\n]*)'|\"([^\"\n]*)\"|\\([^\n])|(.)")

HOW_TO_WAIT = (
    "待つ対象のコマンドそのものを Bash の `run_in_background` で走らせ、ターンを終えて終わりの知らせを待つ"
    "(`nohup … &` で出した処理には終わりの知らせが来ない)。待つ先が出力ファイルなら、それを書くコマンドを "
    "`run_in_background` で走らせる。このゲートに逃げ道は無い。"
)
REASON_FULL = (
    "waitgate: 裏の処理の終わりを `pgrep -f`・`pkill -0`・`ps | grep` のループで待たない。コマンド行の全体から探すので、"
    "同じ文字列を持つ別の裏のシェル(同じ形の待ちのループ)に当たり、互いに相手を見つけて終わらない"
    "(調べものの部署が約 11 時間止まった)。待ちでないループ(回数の決まった `for` など)と一緒に打ったなら、"
    "`pgrep -f` を別の Bash の呼び出しに分けて打てば通る。\n" + HOW_TO_WAIT
)
REASON_SLEEP = (
    "waitgate: `sleep` を回す `while`・`until` の待ちのループは、前景でも裏でも置かない。待つ条件(出力ファイルの文字、"
    "pid の生き死に)が満たされなければ終わらず、止まったことに気づけない。前景で打っても、Bash の時間の上限を超えると "
    "Claude Code が止めずに裏へ移し、終わらずに残る(28 時間回った会話がある)。\n" + HOW_TO_WAIT
)


# 迷う # (comment_at)をコメントと読むか。reason_for が、読む読み(真)で止まらず迷う # を読んだ(COMMENTED)ときは、
# 読まない読み(偽)でも見る。迷わない # は、どちらの読みでもコメントか、どちらでも語の中の字に読む
COMMENTS = True
COMMENTED = []
# 行ごとの、${ }・[[ ]]・(( )) の中の位置(inside_brackets)。reason_for が読むたびに空にする
INSIDE = {}


def comment_at(text, index):
    """text[index] の # をコメントの始まり(語の頭)と読むか。

    - 行の頭(`\\` と改行で前の行とつないだ所は、つないだ先の前の字で見る)と、空白・`;`・`&`・`|`・`(`・`<`・`>` の
      後の # はコメント。ただし同じ行の ${ }・[[ ]]・(( )) の中(`${x%% #*}`・`[[ x =~ (a|#) ]]`・`(( x = 1 #2 ))`)では
      コメントでないことがあるので迷う。
    - `)` の後の # は、case のパターンや `( )` の後ならコメント、置換・配列を閉じる `)`(`$(date)#notes`・`a=(x)#`)の後なら
      語の中の字なので迷う。
    - `\\` で引用した字の後(`my\\ #1`)とほかの字の後の # は語の中の字。
    迷う # は COMMENTS のとおりに読む(reason_for が両方で見る)。迷わない # まで読み替えると、本物のコメントの中の `'`・
    `<<WORD`・ループの語をコードと読み、後の行のループを見落としたり、走らないループの語で止めたりする。"""
    at = index - 1
    while at >= 1 and text[at] == "\n" and escapes(text, at):
        at -= 2   # \ と改行は行をつなぐだけ
    if at >= 0 and escapes(text, at):
        return False
    prev = text[at] if at >= 0 else "\n"
    if prev == ")" or (prev in " \t;&|(<>" and inside_brackets(text, index)):
        COMMENTED.append(index)
        return COMMENTS
    return prev in " \t\n;&|(<>"


def escapes(text, at):
    """text[at] が、\\ で引用された字か(前に続く \\ が奇数個)。"""
    count = 0
    while at - count - 1 >= 0 and text[at - count - 1] == "\\":
        count += 1
    return count % 2 == 1


def inside_brackets(text, index):
    """index が、同じ行の ${ }・[[ ]]・(( )) の中か。行の頭が引用符の中で、行の中の読みが index で引用符の中に居るときも、
    中と見る(迷う側に倒す)。行ごとに一度だけ読んで INSIDE に置く(# の多い長い行で手間を掛け算にしない)。"""
    line_start = text.rfind("\n", 0, index) + 1
    key = (text, line_start)
    if key not in INSIDE:
        line_end = text.find("\n", index)
        line = text[line_start:len(text) if line_end < 0 else line_end]
        flags = bytearray(len(line))
        depth = {"${": 0, "[[": 0, "((": 0}
        closer = {"}": "${", "]]": "[[", "))": "(("}
        at = 0
        while at < len(line):
            flags[at] = 1 if any(depth.values()) else 0
            char = line[at]
            if char == "\\":
                flags[at + 1:at + 2] = flags[at:at + 1]
                at += 2
                continue
            if char in "'\"":
                end = quote_end(line, at)
                for inner in range(at + 1, min(end + 1, len(line))):
                    flags[inner] = 1   # 引用符の中に index が居れば、行の頭が引用符の中だった
                at = end + 1
                continue
            two = line[at:at + 2]
            if two in depth:
                depth[two] += 1
                at += 2
            elif two in closer and depth[closer[two]]:
                depth[closer[two]] -= 1
                at += 2
            elif char == "}" and depth["${"]:
                depth["${"] -= 1
                at += 1
            else:
                at += 1
        INSIDE[key] = flags
    return bool(INSIDE[key][index - line_start])


def executed_text(command):
    """シェルが走らせる所だけを残したコマンド。

    引用符の中の文字は空白に替え、走る中身(`bash -c` と `eval` の引数、ダブルクォートの中の `$(…)` と `` `…` ``、
    引用符の外の `` `…` ``)は括弧で囲んで残す。
    """
    command = drop_heredoc_bodies(command)
    out = []
    solid = 0   # out の、空白だけでない最後の片の次の位置(shell_argument_before が末尾の空白を読み直さないため)
    index = 0
    while index < len(command):
        if len(out) > solid and not out[-1].isspace():
            solid = len(out)
        char = command[index]
        if char == "\\":
            out.append(" ")
            index += 2
        elif char == "#" and comment_at(command, index):
            # 語の頭の # から行末まではコメントで走らない。中の引用符を数えると、後の行のループを引用符の中と取り違える
            end = command.find("\n", index)
            index = len(command) if end < 0 else end
        elif char in "'\"":
            end = quote_end(command, index)
            inner = command[index + 1:end]
            out.append(quoted_text(inner, char, out, solid))
            index = end + 1
        elif char == "`":
            # シェルは先に閉じる `` ` `` で閉じる。中の引用符をその先まで数えると、後の行のループを引用符の中と取り違える
            end = next_backtick(command, index + 1)
            out.append(" (%s) " % executed_text(command[index + 1:end]))
            index = end + 1
        else:
            out.append(char)
            index += 1
    return "".join(out)


def quoted_text(inner, quote, out, solid):
    if shell_argument_before(out, solid):
        if quote == '"':
            inner = re.sub(r"\\([\"\\$`])", r"\1", inner)
        return " (%s) " % executed_text(inner)
    if quote == '"':
        return "".join(" (%s) " % found for found in substitutions(inner)) or " "
    return " "


def shell_argument_before(out, solid):
    """out(executed_text が組んでいる途中の出力。solid は空白だけでない最後の片の次の位置)の末尾が、次の引用符をシェル
    として走らせる形(SHELL_ARGUMENT)か。

    出力の全体を引用符ごとに探すと、引用符の数 × 長さの手間になり、50KB ほどのコマンドで hooks.json の時間の上限
    (30 秒)を超える(時間切れのフックは止めずに通す)。SHELL_ARGUMENT の当たりの中で、シェルの語の後の語は `-` で始まるか、
    `-o`・`-O` の値(`[\\w-]+`)だけなので、末尾から語をそこまで戻り、戻った先の語から後だけを探す(答えは全体を探すのと同じ)。
    戻る語が SHELL_ARGUMENT_REACH を超えたら、読めないとして落とす(フックの失敗は止める側に倒れる)。"""
    size = 16
    while True:
        start = max(solid - size, 0)
        words = "".join(out[start:solid]).split()
        # words[0] は片の途中から始まりうるので、決めるのに words[0] を使わずに済んだときか、頭まで読んだときに止める
        last = len(words) - 1
        if last >= 1 or start == 0:
            if not words or not SHELL_ARGUMENT_WORD.search(words[last]):
                return False
        at = last
        while at > 0 and (words[at].startswith("-") or (OPTION_VALUE.fullmatch(words[at])
                                                         and VALUE_OPTION.fullmatch(words[at - 1]))):
            at -= 1
            if last - at > SHELL_ARGUMENT_REACH:
                raise ValueError("`bash -c`・`eval` の形を探す語が多すぎて読めない")
        if at >= 2 or start == 0:
            return bool(SHELL_ARGUMENT.search(" ".join(words[at:])))
        size *= 4


def substitutions(text):
    """ダブルクォートの中の `$(…)` と `` `…` `` の中身を、走る形にして返す。"""
    found = []
    index = 0
    while index < len(text):
        if text[index] == "\\":
            index += 2
        elif text.startswith("$(", index):
            end = paren_end(text, index + 1)
            found.append(executed_text(text[index + 2:end]))
            index = end + 1
        elif text[index] == "`":
            end = backtick_end(text, index)
            found.append(executed_text(text[index + 1:end]))
            index = end + 1
        else:
            index += 1
    return found


def quote_end(text, start):
    """start の引用符を閉じる位置。閉じていなければ末尾。"""
    if text[start] == "'":
        end = text.find("'", start + 1)
        return end if end >= 0 else len(text)
    index = start + 1
    while index < len(text):
        if text[index] == "\\":
            index += 2
        elif text[index] == '"':
            return index
        elif text.startswith("$(", index):
            index = paren_end(text, index + 1) + 1
        elif text[index] == "`":
            index = backtick_end(text, index) + 1
        else:
            index += 1
    return len(text)


def paren_end(text, start):
    """start の `(` を閉じる `)` の位置。引用符の中の括弧は数えない。"""
    depth = 0
    index = start
    while index < len(text):
        char = text[index]
        if char == "\\":
            index += 1
        elif char in "'\"":
            index = quote_end(text, index)
        elif char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth == 0:
                return index
        index += 1
    return len(text)


def backtick_end(text, start):
    end = text.find("`", start + 1)
    return end if end >= 0 else len(text)


def end_mark(word):
    """ヒアドキュメントの中身を除いた後の、終わりの語の行に替える印の行。シェルに渡るコマンドは C の文字列なので NUL を
    持たず、本物の行と取り違えない。語を 16 進で添えるのは、置換の中のヒアドキュメントの印で、それを囲むヒアドキュメントを
    閉じないため(16 進の字は引用符もループの語も作らない)。"""
    return "\x00" + word.encode().hex()


def drop_heredoc_bodies(command):
    """シェルでないコマンドに渡すヒアドキュメントの中身を除く。終わりの語の行は印の行(end_mark)に替える。

    置換や `bash -c "…"` の中は executed_text が読み直すときにもう一度除く。終わりの語の行まで除いていると、2 度目は
    `<<EOF` の後のコードを中身と見て落とし、後の行のループを見落とす(何度除いても同じ結果になるようにする)。
    終わりの語の行をそのまま残すと、語が `while`・`until` ならループの語に、`it's` なら引用符の始まりに見えるので、
    どの語のヒアドキュメントも閉じる印の行に替える。"""
    found = []
    scan_code(command, 0, None, found)
    out = []
    copied = 0
    for start, body_start, keep, word in sorted(found, key=lambda item: item[1]):
        line_start = command.rfind("\n", 0, start) + 1
        if body_start < copied:
            continue
        if SHELL_STDIN.search(command[line_start:start]):
            # シェルが読む中身はコードなので残す。中身の中のヒアドキュメントは外の読みが飛ばしたので、ここで除く
            # (`bash <<'X'` の中の `cat <<'E'` の中身の `'` で、後の行のループを引用符の中と取り違えない)
            out.append(command[copied:body_start])
            out.append(drop_heredoc_bodies(command[body_start:abs(keep)]))
            copied = abs(keep)
            continue
        out.append(command[copied:body_start])
        if keep < 0:
            out.append(end_mark(word) + "\n")
        copied = abs(keep)
    out.append(command[copied:])
    return "".join(out)


def scan_code(text, index, stop, found):
    """text の index から、シェルが語として読む所を読み、閉じる位置(stop の `)` か `` ` ``。無ければ末尾)を返す。

    ヒアドキュメントの演算子を見つけたら、(演算子の位置, 中身の頭, 写し直す位置, 終わりの語)を found に積む(heredoc_end)。引用符とコメントの
    中の `<<WORD` はヒアドキュメントを始めない(後の行を中身と見て落とすとループが見えない)。ダブルクォートの中の `$(…)` と
    `` `…` `` はシェルが走らせるので、中のヒアドキュメントも読む(`git commit -m "$(cat <<'EOF'` の中身の `'` で、後の行の
    ループを引用符の中と取り違えない)。行ごとでなくコマンドの全体で読むので、複数の行にまたがる引用符も閉じる所まで読む。"""
    pending = []
    depth = 0
    # `` ` `` の中は、シェルが先に閉じる `` ` ``(`\` で引用していない物)で閉じる。中の引用符はそこを越えない
    close = next_backtick(text, index) if stop == "`" else len(text)
    while index < len(text):
        index = min(index, close)
        char = text[index]
        if char == "\\":
            index += 2
        elif char == "\n":
            index += 1
            for match in pending:
                index, closed = heredoc_end(text, index, match, found, stop)
                if closed:
                    break   # 置き換えが閉じた。残りのヒアドキュメントの中身は落とさない(見える側に倒す)
            pending = []
        elif char == "#" and comment_at(text, index):
            end = text.find("\n", index)
            index = len(text) if end < 0 else end
        elif char == "'":
            end = text.find("'", index + 1)
            index = len(text) if end < 0 else end + 1
        elif char == '"':
            index = scan_double_quote(text, index, found) + 1
        elif text.startswith("$(", index):
            index = scan_code(text, index + 2, ")", found) + 1
        elif char == "`":
            if stop == "`":
                return index
            index = scan_code(text, index + 1, "`", found) + 1
        elif char == "(":
            depth += 1
            index += 1
        elif char == ")":
            if stop == ")" and depth == 0:
                return index
            depth = max(depth - 1, 0)
            index += 1
        else:
            match = HEREDOC.match(text, index) if char == "<" else None
            if match:
                pending.append(match)
                index = match.end()
            else:
                index += 1
    return len(text)


def scan_double_quote(text, start, found):
    """start のダブルクォートを閉じる位置(閉じていなければ末尾)。中の `$(…)` と `` `…` `` は scan_code で読む。"""
    index = start + 1
    while index < len(text):
        if text[index] == "\\":
            index += 2
        elif text[index] == '"':
            return index
        elif text.startswith("$(", index):
            index = scan_code(text, index + 2, ")", found) + 1
        elif text[index] == "`":
            index = scan_code(text, index + 1, "`", found) + 1
        else:
            index += 1
    return len(text)


# `$( )` の中のヒアドキュメントを、終わりの語で始まり `)` を持つ行で閉じるか(bash の読み)。zsh は終わりの語だけの行でしか
# 閉じない。reason_for が両方の読みで見る。EARLY_CLOSED には、閉じる読みで実際に閉じた数を積む
EARLY_CLOSE = True
EARLY_CLOSED = []


def heredoc_end(text, index, match, found, stop=None):
    """index の行から始まるヒアドキュメントの中身を found に積み、(読み終えた位置, 置き換えが閉じたか)を返す。

    ふつうは終わりの語の行の後の位置を返す。終わりが無ければ末尾。`$( )` と `` ` ` `` の中(stop)では、終わりの語の行より
    前に置き換えが閉じることがあり、閉じた後の行はシェルが走らせる。中身と見て末尾まで落とすと、後の行のループが見えない
    (`gh pr comment 5 --body "$(cat <<'EOF'` の終わりを `EOF)"` と書いた後の `until …; do sleep 30; done` を見落として通していた)。
    - `` ` ` `` の中: シェルは先に閉じる `` ` `` を探すので、中身の `` ` `` の所で閉じる(bash・zsh)。
    - `$( )` の中: 終わりの語で始まり、後に `)` を持つ行(`EOF)"`・`EOF )`)で閉じ、語の後はコードとして読む(bash 5 の読み方。
      bash 3.2 は先に `)` を探して閉じるので、どちらでも後の行は走る)。
      zsh は終わりの語だけの行まで中身と読むので、EARLY_CLOSE が偽のときはこの閉じ方をしない(reason_for が両方で見る。
      `EOF handling (#12) is fixed; it's …` のような中身の行を閉じと読むと、後の中身の `'` で後の行のループが引用符に隠れる)。
    閉じたときは、閉じる記号の手前(`$( )` は終わりの語の後)の位置を返し、呼び元はその記号から読み続ける。"""
    word = "".join("".join(piece) for piece in HEREDOC_PIECE.findall(match.group("raw")))
    body_start = index
    closed = False
    keep = len(text)
    while index < len(text):
        end = text.find("\n", index)
        line_end = len(text) if end < 0 else end
        line = text[index:line_end]
        tick = unescaped_backtick(line) if stop == "`" else -1
        if tick >= 0:
            index, closed = index + tick, True
            keep = index
            break
        stripped = line.lstrip("\t") if match.group("dash") else line
        if stripped == word or line == end_mark(word):
            index = len(text) if end < 0 else end + 1
            keep = -index   # 負の数は「終わりの語の行を印の行に替えて、その後から写す」(drop_heredoc_bodies)
            break
        if stop == ")" and EARLY_CLOSE and stripped.startswith(word) and ")" in stripped[len(word):]:
            keep = index
            index, closed = line_end - len(stripped) + len(word), True
            EARLY_CLOSED.append(index)
            break
        index = len(text) if end < 0 else end + 1
    found.append((match.start(), body_start, keep, word))
    return index, closed


def next_backtick(text, start):
    """text の start から後の、`\\` で引用していない最初の `` ` `` の位置。無ければ末尾。"""
    found = unescaped_backtick(text, start)
    return len(text) if found < 0 else found


def unescaped_backtick(line, index=0):
    """line の index から後の、`\\` で引用していない最初の `` ` `` の位置。無ければ -1。"""
    while index < len(line):
        if line[index] == "\\":
            index += 2
        elif line[index] == "`":
            return index
        else:
            index += 1
    return -1


def reason_for(command):
    """止める訳。通すなら None。`$( )` の中のヒアドキュメントの閉じ方はシェルで違う(EARLY_CLOSE)ので、閉じる読みで止まらず、
    その読みで実際に閉じた所が在れば、閉じない読みでも見る。コメントと読んだ # がシェルではコメントでないことがある
    (comment_at)ので、コメントを読む読みで止まらず、コメントを読んだ所が在れば、読まない読みでも同じように見る。"""
    global EARLY_CLOSE, COMMENTS
    reason = None
    try:
        for COMMENTS in (True, False):
            del EARLY_CLOSED[:]
            del COMMENTED[:]
            INSIDE.clear()
            EARLY_CLOSE = True
            reason = reason_in(command)
            if reason is None and EARLY_CLOSED:
                EARLY_CLOSE = False
                reason = reason_in(command)
            if reason is not None or not COMMENTED:
                break
    finally:
        EARLY_CLOSE, COMMENTS = True, True
        INSIDE.clear()
    return reason


def reason_in(command):
    text = executed_text(command)
    while_until = WHILE_UNTIL.search(text)
    sleeps = SLEEP.search(text)
    if while_until or (FOR.search(text) and sleeps):
        waits_on_command_line = PGREP_FULL.search(text) or PS_GREP.search(text)
    else:
        # 回数の決まった for は待ちでない。ps | grep は通すが、pgrep -f は互いに当たって終わらない形になりうるので止める
        waits_on_command_line = FOR.search(text) and PGREP_FULL.search(text)
    if waits_on_command_line:
        return REASON_FULL
    if while_until and sleeps:
        return REASON_SLEEP
    return None


def main():
    raw = json.load(sys.stdin)
    if raw.get("tool_name") != "Bash":
        return
    args = raw.get("tool_input") or {}
    if not isinstance(args, dict):
        raise ValueError("tool_input が object でない")
    command = args.get("command", "")
    if not isinstance(command, str):
        raise ValueError("tool_input.command が文字列でない")
    if not LOOP_WORD_RE.search(command):
        return   # ループの語が無い(bash -c・eval・$( ) の中も字としては同じ文字列に在る)
    reason = reason_for(command)
    if reason is None:
        return
    gate_shell.refuse(gate_shell.load_coldread(), "waitgate", "deny %s" % " ".join(command.split())[:200], reason)


if __name__ == "__main__":
    gate_shell.run(main, lambda why: "waitgate: 待ちのループの検査自体に失敗した(%s)。" % why)
