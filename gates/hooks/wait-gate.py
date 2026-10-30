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
の中も見る・コメントを外す・パスで呼ぶシェルと長いオプションのシェル(`/bin/bash -c`・`bash --norc -c`)の中も見る、の 7 つ。
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
_LOOP_HEAD = r"(?:^|[;&|(){}!\n]|\b(?:do|then|else|time)\b)\s*"
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
_SHELL_OPTS = r"(?:(?:-\w*[oO]\s+[\w-]+|--[\w-]+|-\w+)\s+)*"
_SHELL = r"(?:[^\s;&|(`'\"]*/)?(?:ba|z|da)?sh"
SHELL_ARGUMENT = re.compile(r"(?:^|[\s;&|(`])(?:" + _SHELL + r"\s+" + _SHELL_OPTS + r"-\w*c\w*|eval)\s*$")
# ヒアドキュメントを読むのがシェルか(`bash <<EOF`)
SHELL_STDIN = re.compile(r"(?:^|[\s;&|(`])" + _SHELL + r"(?:\s+" + _SHELL_OPTS + r")?\s*$")
# `<<<`(here-string)は除く
HEREDOC = re.compile(r"(?<!<)<<(?!<)(-?)\s*(['\"]?)([A-Za-z_]\w*)\2")

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


def executed_text(command):
    """シェルが走らせる所だけを残したコマンド。

    引用符の中の文字は空白に替え、走る中身(`bash -c` と `eval` の引数、ダブルクォートの中の `$(…)` と `` `…` ``)は
    括弧で囲んで残す。
    """
    command = drop_heredoc_bodies(command)
    out = []
    index = 0
    while index < len(command):
        char = command[index]
        if char == "\\":
            out.append(" ")
            index += 2
        elif char == "#" and (index == 0 or command[index - 1] in " \t\n;&|()"):
            # 語の頭の # から行末まではコメントで走らない。中の引用符を数えると、後の行のループを引用符の中と取り違える
            end = command.find("\n", index)
            index = len(command) if end < 0 else end
        elif char in "'\"":
            end = quote_end(command, index)
            inner = command[index + 1:end]
            out.append(quoted_text(inner, char, "".join(out)))
            index = end + 1
        else:
            out.append(char)
            index += 1
    return "".join(out)


def quoted_text(inner, quote, before):
    if SHELL_ARGUMENT.search(before):
        if quote == '"':
            inner = re.sub(r"\\([\"\\$`])", r"\1", inner)
        return " (%s) " % executed_text(inner)
    if quote == '"':
        return "".join(" (%s) " % found for found in substitutions(inner)) or " "
    return " "


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


def drop_heredoc_bodies(command):
    """シェルでないコマンドに渡すヒアドキュメントの中身を除く。"""
    lines = command.split("\n")
    kept = []
    index = 0
    while index < len(lines):
        line = lines[index]
        kept.append(line)
        index += 1
        for match in HEREDOC.finditer(line):
            body_end = heredoc_end(lines, index, match)
            if SHELL_STDIN.search(line[:match.start()]):
                kept.extend(lines[index:body_end])
            index = body_end + 1
    return "\n".join(kept)


def heredoc_end(lines, start, match):
    word = match.group(3)
    for index in range(start, len(lines)):
        line = lines[index].lstrip("\t") if match.group(1) else lines[index]
        if line == word:
            return index
    return len(lines)


def reason_for(command):
    """止める訳。通すなら None。"""
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
