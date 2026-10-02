"""投稿ゲート gates/hooks/coldread-gate.py の解析と記録の検査（tests/run.sh の coldread の節が持たない形）。

- 解析（gh_calls）は同じプロセスで呼ぶ。候補が bash の投稿する値と一致することを 2 つの判定役で見る:
  POSIX 2.7.4（ヒアドキュメント）と 2.6.3（コマンド置換）の意味で書いた期待値と、gh を記録係に差し替えた実物の bash
  （test_scanner_agrees_with_bash）——審査する本文と投稿される本文がずれれば、素通しか止めすぎになる
- 本文ファイルを読む形は tmp_path に置いたファイルで見る。FIFO と書けないファイルは代役で作る（3 OS で同じ件数で回す）
- 記録の行（denies.log・misses.log）・deny の案内・権限の出力・destgate の宛先の検査は、フックを子プロセスで起こして見る
"""
import collections
import importlib.util
import io
import json
import os
import pathlib
import random
import shlex
import shutil
import stat
import subprocess
import sys
import time

import pytest

REPO = pathlib.Path(__file__).resolve().parents[2]
HOOKS = REPO / "gates" / "hooks"


def _load(name, filename):
    spec = importlib.util.spec_from_file_location(name, HOOKS / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


gate = _load("coldread_gate_under_test", "coldread-gate.py")
BODY = "これは検査対象の本文です。" * 20
PAD = "x" * 420
SHELL_STATE = "同じコマンドがシェルの状態を書く"
OTHER_COMMANDS = "同じコマンドの別の命令がファイルを変えうる"
NOT_LITERAL = "字のまま決まらないパス"
UNREADABLE = "本文ファイルを読めない"
NOT_REGULAR = "本文ファイルが通常のファイルでない"
TOO_LARGE = "本文ファイルが上限より大きい"
NOT_UTF8 = "本文ファイルが UTF-8 でない"
PIPE = "パイプからの stdin 渡し"
NOT_HEREDOC = "ヒアドキュメント以外の stdin のリダイレクト"
NO_TERMINATOR = "終端行の無いヒアドキュメント"
INHERITED = "別プロセスからの stdin 渡し"
EXPANDED = "変数・コマンド置換渡し"
BARE = "区切りを引用しないヒアドキュメントの展開"


def parse(command, cwd=None, read_files=False):
    """(本文候補の字, 止めた理由)。"""
    calls = gate.gh_calls(command, cwd, read_files)
    assert calls is not None, command
    bodies, blocked = gate.flatten(calls)
    return [b.text for b in bodies], blocked


def q(path):
    return shlex.quote(pathlib.Path(path).as_posix())


def subst(text):
    return "\"$(cat <<'EOF'\n%s\nEOF\n)\"" % text


# ---- 二重引用の $(cat <<'EOF' … EOF) は bash の値として読む ----------------------------------------------

SUBST = "\"$(cat <<'EOF'\n%s $HOME `x`\n\n\nEOF\n)\"" % BODY
SUBST_VALUE = BODY + " $HOME `x`"   # 区切りを引用したので展開されず、末尾の改行は全部落ちる


@pytest.mark.parametrize("command", [
    "gh pr comment 12 --body " + SUBST,
    "gh issue comment 3 --body " + SUBST,
    "gh pr create --title t --body " + SUBST,
    "gh release create v1 --notes " + SUBST,
    "gh api repos/o/r/issues/1/comments -f body=" + SUBST,
    "gh pr comment 12 --body " + SUBST.replace("cat <<", "cat<<"),
    "gh pr comment 12 --body " + SUBST.replace("<<'EOF'", "<<'EOF' 2>/dev/null"),
], ids=["pr-comment", "issue-comment", "pr-create-with-title", "release-notes", "api-f-body", "no-space",
        "stderr-redirect"])
def test_subst_heredoc_is_read_as_bash_value(command):
    cands, blocked = parse(command)
    assert blocked == []
    assert SUBST_VALUE in cands


def test_subst_heredoc_with_bare_delimiter_and_no_expansion_is_read():
    cands, blocked = parse("gh pr comment 12 --body \"$(cat <<EOF\n%s\nEOF\n)\"" % BODY)
    assert (cands, blocked) == ([BODY], [])


def test_subst_value_is_joined_with_the_letters_around_it():
    # 二重引用の中の置換は語に割れないので、前後の字と連結した値が bash の値
    assert parse("gh pr comment 12 --body \"前 $(cat <<'EOF'\n%s\nEOF\n) 後\"" % BODY) == (["前 %s 後" % BODY], [])


@pytest.mark.parametrize("command,reason", [
    ("gh pr comment 12 --body \"$(cat <<EOF\n%s $HOME\nEOF\n)\"" % BODY, BARE),
    ("gh pr comment 12 --body $(cat <<'EOF'\n%s\nEOF\n)" % BODY, EXPANDED),
    ("gh pr comment 12 --body \"$(cat <<'EOF' | sed s/a/b/\n%s\nEOF\n)\"" % BODY, EXPANDED),
    ("gh pr comment 12 --body \"$(cat <<'EOF'\n%s\nEOF\necho more\n)\"" % BODY, EXPANDED),
    ("gh pr comment 12 --body \"$(cat /tmp/x <<'EOF'\n%s\nEOF\n)\"" % BODY, EXPANDED),
    ("gh pr comment 12 --body \"$(cat <<'EOF')\" # %s" % PAD, EXPANDED),
    ("gh pr comment 12 --body \"$(cat <<'EOF' >&2\n%s\nEOF\n)\"" % BODY, EXPANDED),
    ('gh pr comment 12 --body "$(cat /tmp/x)"', EXPANDED),
    ('gh pr comment 12 --body "$BODY"', EXPANDED),
    ("gh pr comment 12 --body `cat /tmp/x`", EXPANDED),
    ("gh pr comment 12 --body '%s' && gh pr comment 13 --body \"$BODY\"" % BODY, EXPANDED),
], ids=["bare-delim-expands", "unquoted-subst", "pipe-in-subst", "two-commands-in-subst", "cat-with-file",
        "closed-on-start-line", "stdout-redirected", "cat-file", "variable", "backtick", "readable-with-unreadable"])
def test_unreadable_values_stay_blocked(command, reason):
    assert parse(command)[1] == [reason]


def test_mark_written_in_the_body_does_not_become_a_real_heredoc():
    # 本文に字で書いた印が本物の印に化けると、別のヒアドキュメント(cat の中身)が gh の本文にすり替わる
    cands, blocked = parse("gh issue comment 1 --body \"$(cat << __HEREDOC0_0__ )\" && cat <<'X'\n%s\nX" % BODY)
    assert cands == [] and blocked == [EXPANDED]


def test_mark_of_another_nonce_written_in_the_body_is_text():
    # 照らすのはその呼び出しの nonce の印だけ。字で書いた別の nonce の印を展開と読むと、普通の本文を止める
    assert parse("gh issue comment 1 --body '__EXPAND3_99__ と書いた'") == (["__EXPAND3_99__ と書いた"], [])


def test_nonce_avoids_every_number_written_in_the_command():
    assert gate._nonce(" ".join("_%d__" % k for k in range(3001))) == 3001


@pytest.mark.parametrize("prefix", [
    "cat() { printf EVIL; }; ",
    "function cat { printf EVIL; }; ",
    "alias cat='printf EVIL'; ",
    "eval 'cat() { :; }'; ",
    ". ./x.sh; ",
    "source ./x.sh; ",
    "hash -p /tmp/evil cat; ",
    "enable -f ./cat.so cat; ",
    "PATH=/tmp/evil:$PATH; ",
    "export PATH=/tmp/evil; ",
    "read PATH <<< /tmp/evil; ",
    "printf -v PATH %s /tmp/evil; ",
    "mapfile PATH <<< /tmp/evil; ",
    "for PATH in /tmp/evil; do :; done; ",
    "declare -n p=PATH; p=/tmp/evil; ",
    "PATH+=:/tmp/evil; ",
    "BASH_CMDS[cat]=/tmp/evil/cat; ",
    "command read PATH <<< /tmp/evil; ",
    "(( PATH = 0 )); ",
    ": $((PATH=0)); ",
    ": ${PATH:=/tmp/evil}; ",
    "if read PATH <<< /tmp/evil; then :; fi; ",
    "PATH=/tmp/evil :; ",
    "set -e; ",
    "\"$(cat <<'EOF'\nsource\nEOF\n)\" ./x.sh; ",
], ids=["function", "function-keyword", "alias", "eval", "dot", "source", "hash", "enable", "path", "export-path",
        "read", "printf-v", "mapfile", "for", "nameref", "append", "hash-table", "command-wrapped", "arith-command",
        "arith-expansion", "assign-default", "if-condition", "special-builtin-prefix", "set", "name-from-subst"])
def test_subst_cat_is_not_trusted_when_the_command_can_rebind_it(prefix):
    cands, blocked = parse(prefix + "gh pr comment 12 --body " + SUBST)
    assert SUBST_VALUE not in cands and SHELL_STATE in blocked


@pytest.mark.parametrize("prefix", [
    "cd /tmp && git push -u origin HEAD && ",
    "GIT_PAGER=cat git log -1; ",
    "echo start; printf '%s' x > /dev/null; true; ",
    "{ cd /tmp; } && ",
    "env -u GH_DEBUG ",
    "echo $HOME ${HOME} $1 \"$@\"; ",
], ids=["external-chain", "prefixed-external", "pure-builtins", "brace-group", "env-unset", "plain-parameters"])
def test_subst_cat_is_trusted_when_nothing_writes_shell_state(prefix):
    assert parse(prefix + "gh pr comment 12 --body " + SUBST) == ([SUBST_VALUE], [])


# ---- 値の決まる置換は、どの読み手よりも先に値へ解く ---------------------------------------------------

def test_subst_value_decides_command_name_and_flags(body_file):
    # gh が読むのは置換を解いた後の字。解く前の字で判定すると、命令名も本文旗も見えない
    assert parse(subst("gh") + " issue comment 1 --body 'あとの本文'")[0] == ["あとの本文"]
    command = "gh issue comment 1 " + subst("--body-file=%s" % body_file.as_posix())
    assert parse(command, read_files=True) == ([BODY], [])
    assert parse(command) == ([], ["実ファイル指定"])


@pytest.mark.parametrize("template", [
    "gh api repos/o/r/issues/1/comments -F body=" + subst("@{p}"),
    "gh api repos/o/r/issues/1/comments -F " + subst("body=@{p}"),
    "gh api repos/o/r/issues/1/comments --field " + subst("body=@{p}"),
], ids=["value", "key-and-value", "long-flag"])
def test_api_field_at_from_subst_is_a_file(template, body_file):
    # -F の値が @ で始まれば gh はファイルとして読む。置換の値でも同じ(字として審査すると中身が無検査で出る)
    command = template.format(p=body_file.as_posix())
    assert parse(command, read_files=True) == ([BODY], [])
    assert parse(command) == ([], ["実ファイル指定"])


def test_api_field_at_stdin_from_subst_reads_stdin():
    command = "gh api repos/o/r/issues/1/comments -F body=%s <<'X'\n%s\nX" % (subst("@-"), BODY)
    assert parse(command) == ([BODY + "\n"], [])


# ---- 値のどこかに生きた展開が在れば止める(値ごとに見る) ----------------------------------------------------

@pytest.mark.parametrize("value", [
    '"前 $(cat /tmp/long.md)"', '"Hello $NAME"', '"x ${X}"', '"`id` 後"', "x$Y", '"x $1"', '"$@"', '"$[1+1]"',
    '"$((1+1))"', '$"訳文"', '"$\\\n(cat /tmp/long.md)"', '"$\\\nHOME"',
], ids=["text-before-subst", "variable-in-text", "braced-variable", "backtick-before-text", "unquoted-concat",
        "positional", "all-args", "old-arithmetic", "arithmetic", "locale-string", "line-joined-subst",
        "line-joined-variable"])
def test_value_with_expansion_anywhere_is_blocked(value):
    cands, blocked = parse("gh issue comment 1 --body " + value)
    assert cands == [] and blocked == [EXPANDED]


def test_expansion_is_judged_per_value():
    # コマンド全体の真偽値で見ると、置換を含まない 2 本目の本文まで止める
    cands, blocked = parse("gh issue comment 1 --body \"$(true)\"; gh issue comment 2 --body 'costs 5$'")
    assert (cands, blocked) == (["costs 5$"], [EXPANDED])


@pytest.mark.parametrize("value,expected", [
    ('"5$ と US$ 5"', "5$ と US$ 5"),
    ("'$(cat x) と `id`'", "$(cat x) と `id`"),
    ('"\\$5 \\` \\" \\\\ \\q"', '$5 ` " \\ \\q'),
], ids=["dollar-before-space", "single-quoted", "escaped-in-double-quotes"])
def test_dollar_that_bash_keeps_is_read(value, expected):
    assert parse("gh issue comment 1 --body " + value) == ([expected], [])


# ---- 区切りを引用しないヒアドキュメントは、展開を受けるなら止める ----------------------------------------------

@pytest.mark.parametrize("command", [
    "gh issue comment 1 --body-file - <<EOF\n$(cat body.md)\nEOF",
    "gh issue comment 1 --body-file - <<EOF\n%s $V\nEOF" % BODY,
    "gh issue comment 1 -F - <<EOF\n%s `id`\nEOF" % BODY,
    "gh api repos/o/r/issues/1/comments --input - <<EOF\n{\"body\": \"$X %s\"}\nEOF" % BODY,
    "gh api repos/o/r/issues/1/comments -F body=@- <<EOF\n${X} %s\nEOF" % BODY,
    "gh gist create - <<EOF\n$(id) %s\nEOF" % BODY,
], ids=["file-subst", "file-var", "short-F-backtick", "input-json", "api-at-stdin", "gist"])
def test_bare_delimiter_with_expansion_is_blocked(command):
    cands, blocked = parse(command)
    assert cands == [] and blocked == [BARE]


@pytest.mark.parametrize("body,value", [
    ("価格は \\$5、\\`x\\`、\\\\ は 1 つ", "価格は $5、`x`、\\ は 1 つ"),
    ("a\\b と \\\" は字のまま", "a\\b と \\\" は字のまま"),
    ("行を\\\nつなぐ", "行をつなぐ"),
    ("US$ 5 と 5$", "US$ 5 と 5$"),
], ids=["escaped", "other-backslash", "line-join", "dollar-before-space"])
def test_bare_delimiter_without_expansion_is_unescaped_like_bash(body, value):
    cands, blocked = parse("gh issue comment 1 --body-file - <<EOF\n%s\nEOF" % body)
    assert (cands, blocked) == ([value + "\n"], [])


def test_quoted_delimiter_keeps_dollar_and_backtick():
    cands, blocked = parse("gh issue comment 1 --body-file - <<'EOF'\n価格は $5 と `x`\nEOF")
    assert (cands, blocked) == (["価格は $5 と `x`\n"], [])


@pytest.mark.parametrize("command,value", [
    ("gh issue comment 1 --body-file - <<EOF\nshort\\\nEOF\n%s\nEOF" % BODY, "shortEOF\n%s\n" % BODY),
    ("gh issue comment 1 --body-file - <<'EOF'\nshort\\\nEOF\n%s\nEOF" % BODY, "short\\\n"),
    ("gh issue comment 1 --body-file - <<EOF\nshort\\\\\nEOF\n%s\nEOF" % BODY, "short\\\n"),
], ids=["bare-joins-before-matching", "quoted-does-not-join", "escaped-backslash-ends-the-line"])
def test_terminator_is_matched_after_line_joining(command, value):
    # 期待値の shortEOF… は、行末の \ で連結した行が終端行にならず本文に残った形
    assert parse(command) == ([value], [])


# ---- 開始行の続き・部分的な引用・終端行の照合 -------------------------------------------------------------

GRAMMAR_CASES = [
    ("gh issue comment 1 --body-file - <<'EOF' 2>&1 | tail -1\n%s $X\nEOF" % BODY, BODY + " $X\n"),
    ("gh issue comment 1 --body-file - <<'EOF' > /dev/null\n%s\nEOF" % BODY, BODY + "\n"),
    ("gh api repos/o/r/issues/1/comments --input - <<'EOF' && echo ok\n{\"body\": \"%s\"}\nEOF" % BODY, BODY),
    ("gh issue comment 1 --body-file - <<\\EOF\n%s $X\nEOF" % BODY, BODY + " $X\n"),
    ("gh issue comment 1 --body-file - <<E\"OF\"\n%s $X\nEOF" % BODY, BODY + " $X\n"),
    ("gh issue comment 1 --body-file - <<-'EOF'\n\t%s\n\t\tEOF" % BODY, BODY + "\n"),
    ("gh issue comment 1 --body-file - <<-'EOF'\n\t  %s\n\tEOF" % BODY, "  %s\n" % BODY),
    ("gh issue comment 1 --body-file - <<'EOF'\r\n%s\r\nEOF\r\n" % BODY, BODY + "\r\n"),
    ("gh issue comment 1 --body-file - <<'EOF'\n短い\n  EOF\n%s\nEOF" % BODY, "短い\n  EOF\n" + BODY + "\n"),
    ("gh issue comment 1 --body-file - <<1X\n%s\n1X" % BODY, BODY + "\n"),
    ("gh issue comment 1 --body-file - <\\\n<'EOF'\n%s $X\nEOF" % BODY, BODY + " $X\n"),
    ("gh issue comment 1 --body-file - << \\\n'EOF'\n%s $X\nEOF" % BODY, BODY + " $X\n"),
    ("gh issue comment 1 --body-file - <<\\\n-'EOF'\n\t%s $X\n\tEOF" % BODY, BODY + " $X\n"),
    ("gh issue comment 1 --body-file - <<'E'\\\nOF\n%s $X\nEOF" % BODY, BODY + " $X\n"),
]
GRAMMAR_IDS = ["tail", "redirect-out", "and-echo", "backslash-delim", "partly-quoted", "dash-tabs",
               "dash-keeps-spaces", "crlf", "indented-terminator-is-body", "digit-delimiter",
               "line-joined-operator", "line-joined-delimiter", "line-joined-dash", "line-joined-in-delimiter"]


@pytest.mark.parametrize("command,value", GRAMMAR_CASES, ids=GRAMMAR_IDS)
def test_heredoc_grammar_follows_posix(command, value):
    assert parse(command) == ([value], [])


# tests/run.sh の coldread の節が e2e で持つヒアドキュメントの形(解析の段でも同じ形を見る)
RUN_SH_SHAPES = [
    ("gh issue comment 1 --body-file - <<\"EOF\"\n%s\nEOF" % BODY, BODY + "\n"),
    ("gh issue comment 1 --body-file - <<'JSON-EOF'\n%s\nJSON-EOF" % BODY, BODY + "\n"),
    ("gh api repos/o/r/issues/1/comments --input - <<'EOF'\r\n{\"body\": \"%s\"}\r\nEOF\r\n" % BODY, BODY),
    ("gh api repos/o/r/issues -X POST \\\n  -f title='t' \\\n  -F body=@- <<'EOF'\n%s\nEOF" % BODY, BODY + "\n"),
    ("cat > cfg.json <<'SEC'\n{\"api_key\": \"%s\"}\nSEC\ngh pr comment 123 -F - <<'BODY'\n短い本文\nBODY" % BODY,
     "短い本文\n"),
]
RUN_SH_IDS = ["dq-delim", "hyphen-delim", "crlf-input", "line-continuation", "other-command-heredoc"]


@pytest.mark.parametrize("command,value", RUN_SH_SHAPES, ids=RUN_SH_IDS)
def test_run_sh_heredoc_shapes(command, value):
    assert parse(command) == ([value], [])


def test_body_line_starting_with_gh_is_not_a_command():
    cands, blocked = parse("gh issue comment 1 --body-file - <<'EOF'\n%s\ngh issue comment 2 --body 'x\nEOF" % BODY)
    assert (len(cands), blocked) == (1, [])


@pytest.mark.parametrize("command", [
    "gh issue comment 1 --body-file - <<'EOF'\n%s\n  EOF" % BODY,
    # 語の後ろに空白があるので区切りは EOF(\r なし)。終端行の EOF\r とは bash でも一致しない
    "gh issue comment 1 --body-file - <<'EOF' 2>&1 | tail -1\r\n%s\r\nEOF\r\n" % BODY,
], ids=["no-terminator", "crlf-with-start-line-tail"])
def test_heredoc_without_terminator_is_blocked(command):
    # 素通し(候補も理由も無い)を合格にしない——bash は入力の終わりまでを stdin にして投稿する
    assert parse(command) == ([], [NO_TERMINATOR])


def test_unterminated_heredocs_are_read_once(monkeypatch):
    # 終端行の無い << ごとに入力の終わりまで読み直すと、区切りの語を変えて並べた入力で 2 乗に重くなり、
    # フックの timeout で無検査で通る。bash と同じく最初の 1 本が入力の終わりまでを中身にする
    reads = []
    real = gate._read_body
    monkeypatch.setattr(gate, "_read_body", lambda *a: reads.append(1) or real(*a))
    command = "".join("cat <<A%d\n" % k for k in range(2000)) + "gh issue comment 1 --body 'x'"
    assert gate.gh_calls(command) == []
    assert len(reads) == 1


def nested_heredocs(depth):
    """区切りを引用しないヒアドキュメントの中身の $( の中に、また同じ形を depth 段重ねる。一番奥に gh を置く。"""
    command = "gh issue comment 1 --body 'あとの本文'"
    for k in range(depth):
        command = "cat <<E%d\n$(%s\n)\nE%d" % (k, command, k)
    return command


def test_nested_bare_heredocs_are_bounded_in_depth():
    assert parse(nested_heredocs(3))[0] == ["あとの本文"]
    assert gate.gh_calls(nested_heredocs(gate._MAX_HEREDOC_NEST + 1)) is None


def test_nested_substitutions_copy_their_source_once():
    command = "gh issue comment 1 --body hi"
    for _k in range(2000):
        command = "gh issue comment 1 --title \"$(%s)\"" % command
    calls = gate.gh_calls(command)
    assert len(calls) == 2001
    assert max(len(a) for c in calls for a in c.args) <= 200


@pytest.mark.parametrize("command", [
    "gh issue comment 1 --body 'cat <<EOF\n%s\n' && gh issue comment 2 --body 'あとの本文'" % BODY,
    "(( a << 2 )) && gh issue comment 2 --body 'あとの本文'",
    "(\\\n( a << 2 ))\ngh issue comment 2 --body 'あとの本文'\n2",
    "# cat <<EOF\ngh issue comment 2 --body 'あとの本文'",
    "echo ${x:-<<EOF;}\ngh issue comment 2 --body 'あとの本文'\nEOF",
    "echo \\<<EOF\ngh issue comment 2 --body 'あとの本文'\nEOF",
], ids=["in-single-quotes", "arithmetic", "line-joined-arithmetic", "comment", "parameter-expansion",
        "escaped-less-than"])
def test_double_less_than_outside_code_is_not_a_heredoc(command):
    assert "あとの本文" in parse(command)[0]


# gh_calls は、次の引用・注釈・置換の書き方の中の gh を返す(destgate も同じ入口を通る。その側の検査は
# test_destgate_checks_destination_of_new_forms)
@pytest.mark.parametrize("command", [
    "x=$(true)#note; gh issue comment 1 --body 'あとの本文'",
    "echo \"$(printf \"%s # x\")\"; gh issue comment 1 --body 'あとの本文'",
    "echo $[1<<EOF ]; gh issue comment 1 --body 'あとの本文'",
    "echo $(# <<EOF\n); gh issue comment 1 --body 'あとの本文'",
    "echo `# <<EOF`; gh issue comment 1 --body 'あとの本文'",
    "cat <<1X\nfoo\n1X\ngh issue comment 1 --body 'あとの本文'",
    "echo \"$(gh issue comment 1 --body 'あとの本文')\"",
    "echo \"`gh issue comment 1 --body 'あとの本文'`\"",
    "cat <<EOF\n$(gh issue comment 1 --body 'あとの本文')\nEOF",
    "echo ${X:-$(gh issue comment 1 --body 'あとの本文')}",
    "cat <(gh issue comment 1 --body 'あとの本文')",
    "echo $\\\n(gh issue comment 1 --body 'あとの本文')",
    "echo ${ gh issue comment 1 --body 'あとの本文'; }",
    "echo $(case x in (x) gh issue comment 1 --body 'あとの本文';; esac)",
    "echo $(echo use case x in y); gh issue comment 1 --body 'あとの本文'",
    "echo $(echo '; case x in y'); gh issue comment 1 --body 'あとの本文'",
], ids=["hash-after-subst", "nested-double-quotes", "old-arithmetic", "comment-in-subst", "comment-in-backticks",
        "digit-delimiter", "subst-in-double-quotes", "backticks-in-double-quotes", "subst-in-bare-heredoc",
        "subst-in-parameter", "process-substitution", "line-joined-subst", "funsub", "parenthesized-case",
        "case-as-a-word", "quoted-case"])
def test_gh_in_any_lexical_context_is_seen(command):
    assert parse(command)[0] == ["あとの本文"]


@pytest.mark.parametrize("command", [
    "echo $(case x in x) gh issue comment 1 --body hi;; esac)",
    "echo $(if true; then case x in x) gh issue comment 1 --body hi;; esac; fi)",
    "echo $(echo '; esac '; case x in x) gh issue comment 1 --body hi;; esac)",
    "echo \"$(echo \"; esac \"; case x in x) gh issue comment 1 --body-file - ;; esac)\"",
    "echo $(echo $'; esac '; case x in x) gh issue comment 1 --body hi;; esac)",
    "echo $(echo \\; esac; case x in x) gh issue comment 1 --body hi;; esac)",
], ids=["case", "case-after-then", "quoted-esac", "quoted-esac-in-double-quotes", "ansi-quoted-esac",
        "escaped-separator"])
def test_case_pattern_inside_substitution_is_not_guessed(command):
    # 枝の型の ) で置換を閉じると、後ろの gh が前の命令の引数に呑まれて両方のゲートから消える。写していないので止める。
    # 引用や \ の退避の中の esac は数えない——数えると case が esac より多く見えない
    assert gate.gh_calls(command) is None


def test_quoted_operator_is_a_word():
    # 引用した ; を区切りと読むと、後ろの本文旗と -R が gh の引数から外れる
    (call,) = gate.gh_calls("gh issue comment 1 --title ';' --body-file - -R evil/r")
    assert call.args[-4:] == ["--body-file", "-", "-R", "evil/r"] and call.blocked == [INHERITED]


@pytest.mark.parametrize("prefix", [
    "env -iC /tmp ",
    "env -0u NAME ",
    "env -uNAME ",
    "env -vS -i ",
    "env -vS'-u X' ",
    "exec -cla name ",
], ids=["chdir-last", "unset-last", "unset-inline", "split-last", "split-inline", "exec-argv0-last"])
def test_bundled_wrapper_flags_do_not_hide_gh(prefix):
    # 表の突合は旗 1 つずつなので、束ねた形はここで縛る
    assert parse(prefix + "gh issue comment 1 --body 'あとの本文'")[0] == ["あとの本文"]


def test_gh_in_output_process_substitution_is_seen():
    assert parse("tee >(gh issue comment 1 -R evil/r --body-file -)") == ([], [INHERITED])


# ---- トークン化 ---------------------------------------------------------------------------------------------

def _shlex_words(text):
    """判定役: 前の版のトークン化(標準ライブラリ shlex の POSIX の読み)。引用が閉じない等は None。"""
    lex = shlex.shlex(text, posix=True, punctuation_chars="();<>|&\n")
    lex.whitespace, lex.commenters, lex.whitespace_split = " \t\r", "", True
    try:
        return [w for tok in lex for w in (gate._split_ops(tok) if tok and set(tok) <= gate.OP_CHARS else (tok,))]
    except ValueError:
        return None


def _our_words(text):
    tokens = gate.tokenize(text)
    if tokens is None:
        return None
    # 引用した演算子の字だけの語は語のまま(shlex は演算子と読む。ここだけ意図して違える。test_quoted_operator_is_a_word)
    return [w for t in tokens for w in (gate._split_ops(t.text) if not t.op and t.text and set(t.text) <= gate.OP_CHARS
                                        else (t.text,))]


def test_tokenize_agrees_with_shlex():
    rng = random.Random(20261002)
    alphabet = list("ab $;&|<>()\n\t'\"\\#=-") + ["\\\n", "''", '""']
    corpus = [c for c, _v in GRAMMAR_CASES + RUN_SH_SHAPES] + [t for t, _e in DIFF_CORPUS]
    corpus += ["".join(rng.choice(alphabet) for _k in range(rng.randrange(1, 30))) for _n in range(3000)]
    for text in corpus:
        assert _our_words(text) == _shlex_words(text), repr(text)


def test_gate_does_not_use_shlex():
    # shlex は語を字の連結で伸ばすので、長い語(本文・印で膨らんだ語)で重さが 2 乗になる
    assert not hasattr(gate, "shlex")


# ---- 重さは入力に比例する ------------------------------------------------------------------------------------

def _count(monkeypatch, module, name):
    seen = []
    real = getattr(module, name)
    monkeypatch.setattr(module, name, lambda *a, **k: seen.append(1) or real(*a, **k))
    return seen


class _CountingSearch:
    """正規表現の代役。search の回数を数える(走査とトークン化の手数の代理)。"""

    def __init__(self, real, seen):
        self.real, self.seen = real, seen

    def search(self, *a):
        self.seen.append(1)
        return self.real.search(*a)


@pytest.mark.parametrize("build", [
    lambda n: "gh x > /dev/null; " * n + "gh issue comment 1 --body-file /tmp/p.md",
    lambda n: "gh issue comment 1 --body-file /tmp/p.md > /dev/null; " * n,
    lambda n: "cat > /tmp/w.md <<'E'\nx\nE\n" * n + "gh gist create" + " /tmp/p%d.md" * n % tuple(range(n)),
    lambda n: "gh issue comment 1 --body " + "x\\;" * n,
    lambda n: "gh issue comment 1 --body \"%s\"" % ("$a " * n),
    lambda n: "true " + "1\\\n" * n + "< /dev/null; gh issue comment 1 --body hi",
], ids=["gh", "gh-with-file", "writers-and-files", "long-word", "expansions", "joined-digits"])
def test_work_grows_linearly_with_the_command(monkeypatch, build):
    # 字列ごとに決まる値(受け継いだ stdin・ほかの命令・書き手)を gh の呼び出しやファイルごとに作り直すと 2 乗になり、
    # 上限の無い destgate がフックの timeout で外れる。時間は測らず、内側の呼び出しと走査の事象の回数で縛る
    seen = [_count(monkeypatch, gate, name) for name in ("_target_fd", "writes_file", "_cd_or_cat")]
    for name in ("_EVENT_RE", "_WORD_STOP_RE"):
        seen.append([])
        monkeypatch.setattr(gate, name, _CountingSearch(getattr(gate, name), seen[-1]))
    work = []
    for n in (200, 400):
        for s in seen:
            del s[:]
        gate.gh_calls(build(n), "/tmp", read_files=True)
        work.append(sum(map(len, seen)))
    assert 0 < work[1] <= 2.2 * work[0], work


def test_command_is_analysed_once(tmp_path, monkeypatch, capsys):
    scans = _count(monkeypatch, gate, "scan_shell")
    monkeypatch.setattr(gate, "DENY_LOG", str(tmp_path / "denies.log"))
    command = "cd /tmp && gh issue comment 1 --body \"$X\" # %s" % PAD
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps({"tool_input": {"command": command}})))
    with pytest.raises(SystemExit):
        gate.main()
    assert json.loads(capsys.readouterr().out)["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert len(scans) == 1


# ---- stdin は fd 0 への最後のリダイレクトと、直前のパイプで決める ---------------------------------------------

def test_second_heredoc_wins_stdin():
    assert parse("gh issue comment 1 --body-file - <<'A' <<'B'\n%s\nA\nうしろ\nB" % BODY) == (["うしろ\n"], [])


@pytest.mark.parametrize("command,reason", [
    ("gh issue comment 1 --body-file - <<'EOF' < /tmp/x.md\n%s\nEOF" % BODY, NOT_HEREDOC),
    ("gh issue comment 1 --body-file - <<'EOF' <<< \"$X\"\n%s\nEOF" % BODY, NOT_HEREDOC),
    ("gh issue comment 1 --body-file - <<'EOF' <&3\n%s\nEOF" % BODY, NOT_HEREDOC),
    ("gh issue comment 1 --body-file - <<'EOF' <> /tmp/x\n%s\nEOF" % BODY, NOT_HEREDOC),
    ("gh issue comment 1 --body-file - <<'EOF' 0</tmp/x\n%s\nEOF" % BODY, NOT_HEREDOC),
    ("gh issue comment 1 --body-file - <<'A' 2 < /etc/hosts\n%s\nA" % BODY, NOT_HEREDOC),
    ("gh issue comment 1 --body-file - 3<<'EOF'\n%s\nEOF" % BODY, INHERITED),
    ("cat <<'EOF' < /tmp/x.md | gh issue comment 1 --body-file -\n%s\nEOF" % BODY, PIPE),
    ("printf x | cat <<'EOF' | gh issue comment 1 --body-file -\n%s\nEOF" % BODY, PIPE),
    ("( printf evil; cat <<'EOF'\n%s\nEOF\n) | gh issue comment 1 --body-file -" % BODY, PIPE),
    ("cat <<'EOF' |& gh issue comment 1 --body-file -\n%s\nEOF" % BODY, PIPE),
    ("cat <<'EOF' | ( gh issue comment 1 --body-file - )\n%s\nEOF" % BODY, PIPE),
    ("set -e; cat <<'EOF' | gh issue comment 1 --body-file -\n%s\nEOF" % BODY, PIPE),
    ("cat <<'EOF' >&2 | gh issue comment 1 --body-file -\n%s\nEOF" % BODY, PIPE),
], ids=["file-after", "herestring-after", "dup-after", "readwrite-after", "fd0-after", "spaced-number-then-file",
        "other-fd", "pipe-from-cat-with-file", "two-pipes", "subshell-before-pipe", "pipe-with-stderr",
        "pipe-into-subshell", "pipe-with-shell-state", "pipe-from-cat-to-stderr"])
def test_stdin_not_from_a_heredoc_is_blocked(command, reason):
    assert parse(command) == ([], [reason])


@pytest.mark.parametrize("command", [
    "cat <<'EOF' | gh issue comment 1 --body-file -\n%s\nEOF" % BODY,
    "cat <<'EOF' 2>/dev/null | gh issue comment 1 --body-file -\n%s\nEOF" % BODY,
    "cat <<'EOF' |\n%s\nEOF\ngh issue comment 1 --body-file -" % BODY,
    "cat <<'EOF' | gh gist create -d d\n%s\nEOF" % BODY,
    "cat <<'EOF' | gh api repos/o/r/issues/1/comments -F body=@-\n%s\nEOF" % BODY,
], ids=["body-file", "stderr-null", "linebreak-after-pipe", "gist", "api-at-stdin"])
def test_stdin_piped_from_a_lone_cat_heredoc_is_read(command):
    # パイプは左の命令の stdout を右の stdin につなぐ(POSIX 2.9.2)。左が cat <<'EOF' 1 本なら中身は静的に決まる
    assert parse(command) == ([BODY + "\n"], [])


def test_number_separated_by_blank_is_an_argument_not_a_descriptor():
    assert parse("gh issue comment --body-file - 123 <<'EOF'\n%s\nEOF" % BODY) == ([BODY + "\n"], [])


def test_gist_reads_stdin_without_positional_and_each_positional():
    assert parse("gh gist create <<'EOF'\n%s\nEOF" % BODY) == ([BODY + "\n"], [])
    assert parse("gh gist create -d '%s'" % BODY) == ([], [])
    # - と並んだパスも読むか止めるかする(片方だけを候補にしない)
    cands, blocked = parse("gh gist create - notes.md <<'EOF'\n%s\nEOF" % BODY)
    assert (cands, blocked) == ([BODY + "\n"], ["実ファイル指定"])


@pytest.mark.parametrize("command,reason", [
    ("cat notes.md | gh gist create -d d", PIPE),
    ("gh gist create -d d < notes.md", NOT_HEREDOC),
    ("gh gist create -d d <<< \"$X\"", NOT_HEREDOC),
    ("gh gist create -d d <&3", NOT_HEREDOC),
    ("cat notes.md | ( gh gist create -d d )", PIPE),
    ("{ gh gist create -d d; } < notes.md", INHERITED),
    ("exec < notes.md; gh gist create -d d", INHERITED),
    ("cat notes.md | if true; then gh gist create -d d; fi", INHERITED),
    ("echo \"$(gh gist create -d d)\"", INHERITED),
    ("cd /tmp && { gh gist create -d d; } < notes.md", INHERITED),
    ("while true; do gh gist create -d d; done < notes.md", INHERITED),
    ("gh gist create -d d &", INHERITED),
], ids=["pipe", "file", "herestring", "dup", "subshell", "brace-group", "exec", "if-body", "in-subst",
        "group-after-cd", "loop", "background"])
def test_gist_without_positional_blocks_stdin_it_cannot_read(command, reason):
    assert parse(command) == ([], [reason])


@pytest.mark.parametrize("command", [
    "gh gist create -d d",
    "cd /tmp && gh gist create -d d",
    "gh gist create -d d && echo ok",
    "git pull || gh gist create -d d",
], ids=["alone", "after-cd", "before-echo", "after-or"])
def test_gist_without_positional_passes_inherited_stdin(command):
    assert parse(command) == ([], [])


# ---- リテラルのパスの通常のファイルは読む ------------------------------------------------------------

@pytest.fixture
def body_file(tmp_path):
    p = tmp_path / "body.md"
    p.write_text(BODY, encoding="utf-8")
    return p


@pytest.mark.parametrize("template", [
    "gh issue comment 1 --body-file {p}",
    "gh pr create -t T -F {p}",
    "gh release create v1 --notes-file {p}",
    "gh api repos/o/r/issues/1/comments -F body=@{p}",
    "gh gist create {p}",
    "cd /tmp && gh issue comment 1 --body-file {p}",
    "gh issue comment 1 --body-file {p} > /dev/null 2>&1",
    "cd /tmp;\ngh issue comment 1 --body-file {p}",
    "cd /tmp &&\ngh issue comment 1 --body-file {p}",
    "cd /tmp\n\n\ngh issue comment 1 --body-file {p}",
], ids=["body-file", "short-F", "notes-file", "api-at-path", "gist-positional", "cd-then-absolute", "dup-and-null",
        "semicolon-newline", "and-newline", "blank-lines"])
def test_literal_regular_file_is_read(template, body_file):
    assert parse(template.format(p=q(body_file)), read_files=True) == ([BODY], [])


def test_input_file_goes_through_json_body(tmp_path):
    p = tmp_path / "payload.json"
    p.write_text(json.dumps({"body": BODY}), encoding="utf-8")
    calls = gate.gh_calls("gh api repos/o/r/issues/1/comments --input %s" % q(p), read_files=True)
    # .body はファイルから来たので、コマンド長の下限を当てず、通っても権限の確認を飛ばさない
    assert gate.flatten(calls) == ([gate.Body(BODY, True)], [])


def test_relative_path_is_read_against_payload_cwd(body_file):
    cwd = body_file.parent.as_posix()
    assert parse("gh issue comment 1 --body-file body.md", cwd=cwd, read_files=True) == ([BODY], [])
    assert parse("gh issue comment 1 --body-file body.md", read_files=True) == ([], [NOT_LITERAL])
    assert parse("cd sub && gh issue comment 1 --body-file body.md", cwd=cwd, read_files=True)[1] == [NOT_LITERAL]
    assert parse("env -C sub gh issue comment 1 --body-file body.md", cwd=cwd, read_files=True)[1] == [NOT_LITERAL]
    assert parse("env -iC sub gh issue comment 1 --body-file body.md", cwd=cwd, read_files=True)[1] == [NOT_LITERAL]
    assert parse("env -u X gh issue comment 1 --body-file body.md", cwd=cwd, read_files=True) == ([BODY], [])
    assert parse("env -uC gh issue comment 1 --body-file body.md", cwd=cwd, read_files=True) == ([BODY], [])


@pytest.mark.parametrize("template", [
    "cat > {p} <<'EOF'\n新しい本文 $X\nEOF\ngh issue comment 1 --body-file {p}",
    "cat > {p} <<'EOF'\n新しい本文 $X\nEOF\n\ngh issue comment 1 --body-file {p}",
    "cat > {p} <<'EOF';\n新しい本文 $X\nEOF\ngh issue comment 1 --body-file {p}",
    "cat > {p} <<'EOF' &&\n新しい本文 $X\nEOF\ngh issue comment 1 --body-file {p}",
], ids=["newline", "blank-line", "semicolon", "and"])
def test_file_written_by_preceding_cat_heredoc_is_its_value(body_file, template):
    assert parse(template.format(p=q(body_file)), read_files=True) == (["新しい本文 $X\n"], [])


def test_file_written_for_the_first_time_is_its_value(tmp_path):
    # まだ無いファイルでも、書ける置き場なら cat が作って書いた値を gh が読む
    p = tmp_path / "new.md"
    command = "cat > %s <<'EOF'\n新しい本文\nEOF\ngh issue comment 1 --body-file %s" % (q(p), q(p))
    assert parse(command, read_files=True) == (["新しい本文\n"], [])
    assert parse(command.replace(q(p), q(tmp_path / "absent" / "new.md")), read_files=True) == ([], [OTHER_COMMANDS])


@pytest.mark.parametrize("template,reason", [
    ("gh issue comment 1 --body-file {d}/$NAME", NOT_LITERAL),
    ("gh issue comment 1 --body-file ~/body.md", NOT_LITERAL),
    ("gh issue comment 1 --body-file {d}/*.md", NOT_LITERAL),
    ("git push && gh issue comment 1 --body-file {p}", OTHER_COMMANDS),
    ("cat {p} | gh issue comment 1 --body-file {p}", OTHER_COMMANDS),
    ("gh issue comment 1 --body-file {p} &", OTHER_COMMANDS),
    ("gh issue comment 1 --body-file {p} > {p}", OTHER_COMMANDS),
    ("gh issue comment 1 --body-file {p} >& {p}", OTHER_COMMANDS),
    ("gh issue comment 1 --body-file {p} 2> \"$LOG\"", OTHER_COMMANDS),
    ("cat > {p} <<EOF\n$X\nEOF\ngh issue comment 1 --body-file {p}", BARE),
    ("cat >> {p} <<'EOF'\nあと\nEOF\ngh issue comment 1 --body-file {p}", OTHER_COMMANDS),
    ("gh issue comment 1 --body-file {p}; cat > {p} <<'EOF'\nあと\nEOF", OTHER_COMMANDS),
    ("cat > {p} <<'EOF'\nA\nEOF\ncat > {p} <<'EOF'\nB\nEOF\ngh issue comment 1 --body-file {p}", OTHER_COMMANDS),
    ("cat > {p} <<'EOF' || gh issue comment 1 --body-file {p}\nA\nEOF", OTHER_COMMANDS),
    ("cat > {p} <<'EOF' | gh issue comment 1 --body-file {p}\nA\nEOF", OTHER_COMMANDS),
    ("gh issue comment 1 --body-file {d}", NOT_REGULAR),
    ("gh issue comment 1 --body-file {d}/absent.md", UNREADABLE),
    ("gh issue comment 1 --body '%s' && gh pr comment 2 --body-file {p}" % BODY, OTHER_COMMANDS),
    ("cat > {p} <<'EOF'\nA\nEOF\n > {p}\ngh issue comment 1 --body-file {p}", OTHER_COMMANDS),
    (">| {p}; gh issue comment 1 --body-file {p}", OTHER_COMMANDS),
    ("gh issue comment 1 --body-file {p}; > {p}", OTHER_COMMANDS),
    ("cat 1 > {p} <<'EOF'\nA\nEOF\ngh issue comment 1 --body-file {p}", OTHER_COMMANDS),
    ("cd \"$(cp {d}/evil.md {p}; echo /)\" && gh issue comment 1 --body-file {p}", OTHER_COMMANDS),
    ("cd /tmp && gh issue comment 1 --title \"`cp {d}/evil.md {p}`\" --body-file {p}", OTHER_COMMANDS),
    ("cat() {{ cp {d}/evil.md {p}; }}; cat > {d}/x <<'EOF'\nA\nEOF\ngh issue comment 1 --body-file {p}", SHELL_STATE),
    ("set -e; gh issue comment 1 --body-file {p}", SHELL_STATE),
], ids=["variable", "tilde", "glob", "other-command", "pipe", "background", "self-redirect", "self-gtamp",
        "unknown-write-target", "writer-expands", "writer-appends", "writer-after", "two-writers", "or-chain",
        "pipe-writer", "directory", "absent", "other-gh", "redirect-only-after-writer", "redirect-only",
        "redirect-only-last", "spaced-number-writer", "subst-rewrites", "backticks-rewrite", "cat-function",
        "shell-state"])
def test_file_not_decidable_at_hook_time_is_blocked_with_its_cause(template, reason, body_file):
    command = template.format(p=q(body_file), d=q(body_file.parent))
    assert parse(command, read_files=True)[1] == [reason]


def test_writer_through_hard_link_is_seen(body_file):
    link = body_file.parent / "link.md"
    os.link(body_file, link)
    # cat がリンク越しに書いた中身を gh が読む(フックの時点のファイルの中身ではない)
    command = "cat > %s <<'EOF'\nA\nEOF\ngh issue comment 1 --body-file %s" % (q(link), q(body_file))
    assert parse(command, read_files=True) == (["A\n"], [])
    command = "gh issue comment 1 --body-file %s > %s" % (q(body_file), q(link))
    assert parse(command, read_files=True) == ([], [OTHER_COMMANDS])


def test_destgate_and_tests_do_not_open_files(body_file):
    assert parse("gh issue comment 1 --body-file %s" % q(body_file)) == ([], ["実ファイル指定"])


def test_read_body_file_refuses_non_regular_oversized_and_undecodable(tmp_path, body_file, monkeypatch):
    assert gate.read_body_file(str(body_file)) == BODY
    bad = tmp_path / "sjis.md"
    bad.write_bytes("本文".encode("shift_jis"))
    assert gate.read_body_file(str(bad)) == (NOT_UTF8,)
    assert gate.read_body_file(str(tmp_path)) == (NOT_REGULAR,)
    assert gate.read_body_file(str(tmp_path / "absent.md")) == (UNREADABLE,)
    monkeypatch.setattr(gate, "MAX_LEN", 10)
    assert gate.read_body_file(str(body_file)) == (TOO_LARGE,)
    # バイトは上限(MAX_LEN * 4)の内でも、字数が上限を超えれば読まない
    wide = tmp_path / "wide.md"
    wide.write_text("あ" * 11, encoding="utf-8")
    assert gate.read_body_file(str(wide)) == (TOO_LARGE,)


@pytest.mark.parametrize("mode,size_delta,reason", [(stat.S_IFIFO | 0o644, 0, NOT_REGULAR),
                                                    (stat.S_IFREG | 0o644, 1, UNREADABLE)],
                         ids=["fifo", "size-changed"])
def test_read_body_file_checks_the_opened_descriptor(body_file, monkeypatch, mode, size_delta, reason):
    real = os.fstat

    def fake_fstat(fd):
        st = real(fd)
        return os.stat_result((mode, *st[1:6], st.st_size + size_delta, *st[7:]))

    monkeypatch.setattr(gate.os, "fstat", fake_fstat)
    assert gate.read_body_file(str(body_file)) == (reason,)


def test_read_body_file_opens_without_waiting_for_a_writer(body_file, monkeypatch):
    flags = []
    real = os.open
    monkeypatch.setattr(gate.os, "open", lambda path, f, *a: flags.append(f) or real(path, f, *a))
    assert gate.read_body_file(str(body_file)) == BODY
    nonblock = getattr(os, "O_NONBLOCK", 0)
    assert flags and all(f & nonblock == nonblock for f in flags)


def test_same_file_is_opened_once_and_reads_are_bounded_in_total(tmp_path, body_file, monkeypatch):
    opened = _count(monkeypatch, gate.os, "open")
    command = "gh gist create" + (" %s" % q(body_file)) * 50
    assert parse(command, read_files=True) == ([BODY] * 50, [])
    assert len(opened) == 1
    # 別々のファイルでも、1 つのコマンドで読む合計は 1 ファイルの上限まで。超えた分は理由を付けて止める
    monkeypatch.setattr(gate, "MAX_LEN", 100)
    files = []
    for k in range(5):
        p = tmp_path / ("part%d.md" % k)
        p.write_text("y" * 90, encoding="utf-8")
        files.append(q(p))
    cands, blocked = parse("gh gist create " + " ".join(files), read_files=True)
    assert (len(cands), blocked) == (4, ["本文ファイルの合計が上限を超える"])


def test_writer_that_may_fail_is_not_trusted(body_file, monkeypatch):
    command = "cat > %s <<'EOF'\n新しい本文\nEOF\ngh issue comment 1 --body-file %s" % (q(body_file), q(body_file))
    monkeypatch.setattr(gate.os, "access", lambda path, mode: False)
    assert parse(command, read_files=True) == ([], [OTHER_COMMANDS])


def test_writable_needs_a_regular_file_or_a_writable_folder(tmp_path):
    # 在る物は通常のファイルで書けるときだけ。ディレクトリや書けないファイルへの cat > は失敗し、gh は古い中身を読む
    assert gate.writable(str(tmp_path / "new.md"))
    assert not gate.writable(str(tmp_path))
    ro = tmp_path / "ro.md"
    ro.write_text("x", encoding="utf-8")
    ro.chmod(0o444)
    try:
        assert not gate.writable(str(ro))
    finally:
        ro.chmod(0o644)


# ---- 止めた理由の語は原因を指す --------------------------------------------------------------------------------

def test_shell_state_reason_names_the_cause_for_substitutions():
    assert parse("set -e; gh pr comment 12 --body " + SUBST) == ([], [SHELL_STATE])


def test_escape_hatch_inside_substitution_is_honoured():
    # 置換の中の gh に門番が掛かるなら、逃げ道もそこで効く
    assert gate.wants_skip("echo \"$(COLDREAD_SKIP=1 gh issue comment 1 --body hi)\"")


# ---- bash を判定役にした差分検査 -----------------------------------------------------------------------
# gh を「argv・stdin・argv が指す通常のファイルの中身」を書き出す記録係に差し替えた bash で同じコマンドを流し、
# 門番の解析と突き合わせる(McKeeman の差分テスト)。期待を手で書くと作者の POSIX の読みを写すので、実装と
# 同じ向きに間違う。手で書く期待は gh の呼び出しごとの「読むか(read)・止めた理由の語」だけにする。
# コーパスのコマンドが使うのは cat・cd・cp・printf・echo・true・tail・set と gh の代役だけで、作業場の外に書かない。
# macOS の CI の bash 3.2 でも読める構文だけを置く(|& と ${ …; } は単体の検査で縛る)。

RECORDER = r'''
import json, os, sys
argv = sys.argv[1:]
data = sys.stdin.buffer.read()
files = {}
for a in argv:
    for p in (a, a.split("=@", 1)[1] if "=@" in a else "", a.split("=", 1)[1] if "=" in a else "",
              a[1:] if a.startswith("@") else ""):
        if p and os.path.isfile(p):
            with open(p, "rb") as f:
                files[p] = f.read().decode("utf-8", "replace")
with open(os.environ["GH_LOG"], "a", encoding="utf-8") as f:
    f.write(json.dumps({"argv": argv, "stdin": data.decode("utf-8", "replace"), "files": files}) + "\n")
'''


def _bash():
    """記録係を起こす bash。Windows では System32 の WSL の bash を掴まないよう、Git for Windows の bash を先に見る。"""
    if os.name == "nt":
        git = shutil.which("git")
        if git:
            for cand in (pathlib.Path(git).parents[1] / "bin" / "bash.exe", pathlib.Path(git).parents[1] / "usr" / "bin" / "bash.exe"):
                if cand.is_file():
                    return str(cand)
    return shutil.which("bash")


# 状態を書かないと言える語と、split_commands が命令の位置で読み飛ばす予約語。門番の表の写しではなく、ここで意図して
# 持つ固定点——表から導くと、readonly や export を PURE_SHELL_WORDS に足す変異で期待も一緒に変わる
PURE_WORDS = {":", "[", "cd", "echo", "false", "printf", "pwd", "test", "true", "}"}
SKIPPED_WORDS = {"{", "!", "then", "else", "elif", "do"}


def _bash_words():
    """bash 自身が知る組み込みと予約語(compgen -b・compgen -k)。bash が無ければ空。"""
    bash = _bash()
    if not bash:
        return set()
    return set(subprocess.run([bash, "-c", "compgen -b; compgen -k"], capture_output=True, encoding="utf-8",
                              check=True).stdout.split())


BASH_WORDS = _bash_words()


def test_every_bash_word_is_a_shell_word():
    assert BASH_WORDS, "bash が見つからない(語の一覧の判定役)"
    assert BASH_WORDS <= gate.SHELL_WORDS


@pytest.mark.parametrize("word", sorted(BASH_WORDS | gate.SHELL_WORDS | PURE_WORDS | SKIPPED_WORDS))
def test_each_shell_word_decides_trust(word):
    # 単独の命令名に置くのは、構文の語(for … do … done)で別の語が同時に止め、語ごとの退行を互いに隠さないため
    cands, blocked = parse("%s; gh pr comment 12 --body %s" % (word, SUBST))
    if word in PURE_WORDS | SKIPPED_WORDS:
        assert (cands, blocked) == ([SUBST_VALUE], [])
    else:
        assert SHELL_STATE in blocked and SUBST_VALUE not in cands


@pytest.fixture
def bash_posts(tmp_path):
    """コマンドを bash で流し、gh の呼び出しごとの記録の列を返す関数。作業場(@D@)のファイルは下の for が置く。"""
    bash = _bash()
    assert bash, "bash が見つからない(差分検査の判定役)"
    work = tmp_path / "w"
    work.mkdir()
    for name, text in (("body.md", BODY), ("evil.md", "EVIL " + BODY), ("long.md", BODY), ("hosts.txt", "hosts\n")):
        (work / name).write_text(text, encoding="utf-8")
    bindir = tmp_path / "bin"
    bindir.mkdir()
    recorder = tmp_path / "recorder.py"
    recorder.write_text(RECORDER, encoding="utf-8")
    stub = bindir / "gh"
    stub.write_bytes(('#!/bin/sh\nexec "%s" "%s" "$@"\n' % (
        pathlib.Path(sys.executable).as_posix(), recorder.as_posix())).encode("utf-8"))
    stub.chmod(0o755)
    log = tmp_path / "gh.log"
    # MSYS の bash はネイティブのプログラムへ渡す / 始まりの引数を Windows のパスに書き換える。判定役に OS の層の
    # 書き換えを持ち込まないよう止める
    env = {**os.environ, "PATH": str(bindir) + os.pathsep + os.environ.get("PATH", ""), "GH_LOG": str(log),
           "MSYS2_ARG_CONV_EXCL": "*", "MSYS_NO_PATHCONV": "1", "LC_ALL": "C.UTF-8"}

    def run(command):
        # 改行を含む引数は Windows で切り落とされるので、コマンドはファイルに書いて渡す(tests/run.sh の注記と同じ)
        script = tmp_path / "cmd.sh"
        script.write_bytes(command.encode("utf-8"))
        if log.exists():
            log.unlink()
        subprocess.run([bash, str(script)], cwd=work, stdin=subprocess.DEVNULL, env=env, capture_output=True)
        if not log.exists():
            return []
        return [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]

    run.work = work.as_posix()
    return run


def oracle(record):
    """bash が実際に gh へ渡した argv・stdin・ファイルから、同じ旗の表で本文候補を作る。"""
    stdin = gate.Heredoc("-", record["stdin"])
    return gate.classify(record["argv"], stdin, record["files"].get)


def state(call):
    """gh の呼び出し 1 つの結果の語: 読んだ(read)・止めた理由の語(, で連結)・どちらも無い(none)。"""
    if call.blocked:
        return ",".join(sorted(set(call.blocked)))
    return "read" if call.candidates else "none"


DIFF_CORPUS = [(c, ["read"]) for c, _v in GRAMMAR_CASES + RUN_SH_SHAPES] + [
    ("gh pr comment 12 --body " + SUBST, ["read"]),
    ("gh pr comment 12 --body \"$(cat<<'EOF'\n@B@\nEOF\n)\"", ["read"]),
    ("gh pr comment 12 --body \"$(cat <<'EOF' 2>/dev/null\n@B@\nEOF\n)\"", ["read"]),
    ("gh pr comment 12 --body \"前 $(cat <<'EOF'\n@B@\nEOF\n) 後\"", ["read"]),
    ("gh issue comment --body-file - 123 <<'EOF'\n@B@\nEOF", ["read"]),
    ("gh issue comment 1 --body-file - <<EOF\nshort\\\nEOF\n@B@\nEOF", ["read"]),
    ("gh issue comment 1 --body-file - <<-EOF\n\tshort\\\n\tEOF\n\t@B@\n\tEOF", ["read"]),
    ("gh issue comment 1 --body-file - <<EOF\n価格は \\$5 と \\` と \\\\ と US$ 5 と 5$\n@B@\nEOF", ["read"]),
    ('gh issue comment 1 --body "\\$5 \\` \\" \\\\ \\q @B@"', ["read"]),
    ('gh issue comment 1 --body "5$ と US$ 5 @B@"', ["read"]),
    ("gh issue comment 1 --title ';' --body '@B@'", ["read"]),
    ("cd @D@;\ngh issue comment 1 --body-file @D@/body.md", ["read"]),
    ("cd @D@ &&\ngh issue comment 1 --body-file @D@/body.md", ["read"]),
    ("cat > @D@/new.md <<'EOF'\n@B@\nEOF\n\ngh issue comment 1 --body-file @D@/new.md", ["read"]),
    ("gh gist create <<'EOF'\n@B@\nEOF", ["read"]),
    ("cat <<'EOF' | gh issue comment 1 --body-file -\n@B@\nEOF", ["read"]),
    ("cat <<'EOF' |\n@B@\nEOF\ngh issue comment 1 --body-file -", ["read"]),
    ("cat <<'EOF' | gh gist create -d d\n@B@\nEOF", ["read"]),
    ("gh api repos/o/r/issues/1/comments -F body=\"$(cat <<'EOF'\n@@D@/long.md\nEOF\n)\"", ["read"]),
    ("gh api repos/o/r/issues/1/comments -F \"$(cat <<'EOF'\nbody=@@D@/long.md\nEOF\n)\"", ["read"]),
    ("gh issue comment 1 \"$(cat <<'EOF'\n--body-file=@D@/body.md\nEOF\n)\"", ["read"]),
    ("\"$(cat <<'EOF'\ngh\nEOF\n)\" issue comment 1 --body hi", ["read"]),
    ("x=$(true)#note; gh issue comment 1 --body hi", ["read"]),
    ('echo "$(printf "%s # x")"; gh issue comment 1 --body hi', ["read"]),
    ("echo $[1<<EOF ]; gh issue comment 1 --body hi", ["read"]),
    ("echo $(# <<EOF\n); gh issue comment 1 --body hi", ["read"]),
    ("echo `# <<EOF`; gh issue comment 1 --body hi", ["read"]),
    ("cat <<1X\nfoo\n1X\ngh issue comment 1 --body hi", ["read"]),
    ('echo "$(gh issue comment 1 --body hi)"', ["read"]),
    ("cat <<EOF\n$(gh issue comment 1 --body hi)\nEOF", ["read"]),
    ("cat <(gh issue comment 1 --body hi)", ["read"]),
    ("echo ${X:-$(gh issue comment 1 --body hi)}", ["read"]),
    ("echo $\\\n(gh issue comment 1 --body hi)", ["read"]),
    ("echo $(case x in (x) gh issue comment 1 --body hi;; esac)", ["read"]),
    ("gh issue comment 1 --body-file - <\\\n<'EOF'\n@B@\nEOF", ["read"]),
    ('gh issue comment 1 --body "前 $(cat @D@/long.md)"', [EXPANDED]),
    ('gh issue comment 1 --body "$\\\n(cat @D@/long.md)"', [EXPANDED]),
    ('gh issue comment 1 --body "Hello $NAME"', [EXPANDED]),
    ('gh issue comment 1 --body "x $1"', [EXPANDED]),
    ('gh issue comment 1 --body "a `true` b"', [EXPANDED]),
    ("gh issue comment 1 --body x$Y", [EXPANDED]),
    ("gh issue comment 1 --body \"$(true)\"; gh issue comment 2 --body 'costs 5$'", [EXPANDED, "read"]),
    ("gh issue comment 1 --body-file - <<'A' 2 < @D@/hosts.txt\n@B@\nA", [NOT_HEREDOC]),
    ("cat 1 > @D@/p.md <<'EOF'\nNEW\nEOF\ngh issue comment 1 --body-file @D@/p.md", [OTHER_COMMANDS]),
    ("gh issue comment 1 --body-file - <<'EOF'\n@B@\n  EOF", [NO_TERMINATOR]),
    ("gh issue comment 1 --body-file - <<EOF\n$(cat @D@/long.md)\nEOF", [BARE]),
    ("printf x | gh gist create -d d", [PIPE]),
    ("printf x | cat <<'EOF' | gh issue comment 1 --body-file -\n@B@\nEOF", [PIPE]),
    ("( printf evil; cat <<'EOF'\n@B@\nEOF\n) | gh issue comment 1 --body-file -", [PIPE]),
    ("gh gist create -d d < @D@/body.md", [NOT_HEREDOC]),
    ("printf x | ( gh gist create -d d )", [PIPE]),
    ("{ gh gist create -d d; } < @D@/body.md", [INHERITED]),
    ("exec < @D@/body.md; gh gist create -d d", [INHERITED]),
    ('cd "$(cp @D@/evil.md @D@/body.md; echo /)" && gh issue comment 1 --body-file @D@/body.md', [OTHER_COMMANDS]),
    ("cat() { printf EVIL; }; gh issue comment 1 --body \"$(cat <<'EOF'\nGOOD\nEOF\n)\"", [SHELL_STATE]),
    ("set -e; gh issue comment 1 --body \"$(cat <<'EOF'\n@B@\nEOF\n)\"", [SHELL_STATE]),
]


@pytest.mark.parametrize("template,expect", DIFF_CORPUS, ids=["%02d" % k for k in range(len(DIFF_CORPUS))])
def test_scanner_agrees_with_bash(bash_posts, template, expect):
    command = template.replace("@D@", bash_posts.work).replace("@B@", BODY)
    calls = gate.gh_calls(command, bash_posts.work, read_files=True)   # ファイルは bash が書き換える前に読む
    records = bash_posts(command)
    assert calls is not None, command
    # gh を 0 件に呑む読み(注釈・置換・ヒアドキュメントの境の取り違え)は、呼び出しの数で捕まえる
    assert len(calls) == len(records), (command, calls, [r["argv"] for r in records])
    posted = collections.Counter(tuple(b.text for b in oracle(r)[0]) for r in records)
    read = collections.Counter(tuple(b.text for b in c.candidates) for c in calls if c.candidates and not c.blocked)
    assert not read - posted, (command, read, posted)
    assert [state(c) for c in calls] == expect, (command, calls)


# ---- フックを起こして見る: 記録の行・案内・権限の出力・投稿先・destgate ---------------------------------------

def run_hook(script, command, env_extra, cwd=None):
    payload = {"tool_name": "Bash", "session_id": "abcd1234ffff", "tool_input": {"command": command}}
    if cwd:
        payload["cwd"] = cwd
    env = {**os.environ, "COLDREAD_GH_CMD": "exit 1"}
    for name in ("COLDREAD_SKIP", "COLDREAD_IN_READER", "GH_REPO"):
        env.pop(name, None)
    env.update(env_extra)
    proc = subprocess.run([sys.executable, str(HOOKS / script)], input=json.dumps(payload).encode("utf-8"),
                          capture_output=True, env=env)
    assert proc.returncode == 0, proc.stderr.decode("utf-8", "replace")
    out = proc.stdout.decode("utf-8")
    return json.loads(out)["hookSpecificOutput"] if out.strip() else None


def denies(cfg):
    return (cfg / "coldread-gate" / "denies.log").read_text(encoding="utf-8").splitlines()


def test_blocked_deny_records_reasons_and_shows_static_forms(tmp_path):
    out = run_hook("coldread-gate.py", 'gh issue comment 1 --body "$BODY" # ' + PAD,
                   {"CLAUDE_CONFIG_DIR": str(tmp_path), "COLDREAD_READER_CMD": "cat >/dev/null; exit 1"})
    reason = out["permissionDecisionReason"]
    assert "取り出せない" in reason and "<<'EOF' と区切りを引用すれば" in reason
    assert "gh gist create - <<'EOF'" in reason and "\\\\ と退避する" in reason
    assert "cat <<'EOF' 1 本から gh 1 本へ" in reason and "字下げせず" in reason and "set・export" in reason
    assert denies(tmp_path)[-1].split("\t")[1:4] == ["deny", "blocked", EXPANDED]


def test_blocked_reasons_column_splits_into_the_reasons(tmp_path):
    run_hook("coldread-gate.py", 'gh issue comment 1 --body "$BODY" --body-file /no/such/x.md # ' + PAD,
             {"CLAUDE_CONFIG_DIR": str(tmp_path), "COLDREAD_READER_CMD": "cat >/dev/null; exit 1"})
    column = denies(tmp_path)[-1].split("\t")[3]
    assert sorted(column.split(",")) == sorted([EXPANDED, UNREADABLE])


def test_deny_streak_does_not_count_reason_column_as_length(tmp_path, monkeypatch):
    log = tmp_path / "denies.log"
    now = time.strftime("%Y-%m-%d %H:%M:%S")
    log.write_text("".join("%s\t%s\tsid=s1\tv=0\tto=t\n" % (now, cols) for cols in (
        "deny\tfinding\t300\tcold", "deny\tblocked\t実ファイル指定,変数・コマンド置換渡し", "deny\tfinding\t320\tcold")),
        encoding="utf-8")
    monkeypatch.setattr(gate, "DENY_LOG", str(log))
    assert gate.deny_streak("s1", "t") == (3, [300, 320])


# 読み役の代役が依頼文+本文を見て返す文言を変える。grep の綴りは ASCII にする(Windows で日本語を
# sh の引数に載せると化ける。tests/run.sh の CR_STUB_* と同じ理由)
def seeing_stub(marker):
    return "if grep -qF '%s'; then printf '詰まり: SEEN\\n'; else echo CLEAN; fi" % marker


CLEAN_STUB = "cat >/dev/null; echo CLEAN"


def test_subst_heredoc_reaches_reader_with_destination(tmp_path):
    out = run_hook("coldread-gate.py", "gh pr comment 12 --body " + SUBST + " # " + PAD,
                   {"CLAUDE_CONFIG_DIR": str(tmp_path), "COLDREAD_READER_CMD": seeing_stub("$HOME `x`")})
    assert "SEEN" in out["permissionDecisionReason"]
    assert denies(tmp_path)[-1].endswith("\tto=pr:cwd:12")


def test_hook_reads_literal_file_for_the_reader(tmp_path):
    p = tmp_path / "body.md"
    p.write_text(BODY + " MARKER-FILE-7", encoding="utf-8")
    command = "cd /tmp && gh issue comment 1 --body-file %s # %s" % (q(p), PAD)
    out = run_hook("coldread-gate.py", command,
                   {"CLAUDE_CONFIG_DIR": str(tmp_path / "cfg"), "COLDREAD_READER_CMD": seeing_stub("MARKER-FILE-7")})
    assert "SEEN" in out["permissionDecisionReason"]


# ---- 柵の順序: 解析は上限と try の内側だけで走る・短いコマンドでもファイルの本文は審査する --------------------

def test_scanner_failure_is_a_parse_fail_deny_not_a_crash(tmp_path):
    # 末尾の <<EOF\ で走査が落ちると rc=1 になり、PreToolUse は続行する(=無検査で通る)
    command = "gh issue comment 1 --body-file - " + PAD + " <<EOF\\"
    assert gate.gh_calls(command) is None
    out = run_hook("coldread-gate.py", command, {"CLAUDE_CONFIG_DIR": str(tmp_path)})
    assert "解析できない" in out["permissionDecisionReason"]
    assert denies(tmp_path)[-1].split("\t")[1:3] == ["deny", "parse-fail"]


def test_every_parse_runs_inside_the_exception_guard(tmp_path, monkeypatch, capsys):
    # 逃げ道の判定(wants_skip)も走査を使う。そちらだけ try の外に在ると、走査の例外でフックが落ちる
    def raises(_command):
        raise RuntimeError("代役: 走査の例外")

    monkeypatch.setattr(gate, "scan_shell", raises)
    monkeypatch.setattr(gate, "DENY_LOG", str(tmp_path / "denies.log"))
    command = "cd /tmp && gh issue comment 1 --body '%s %s'" % (BODY, PAD)
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps({"tool_input": {"command": command}})))
    with pytest.raises(SystemExit):
        gate.main()
    out = json.loads(capsys.readouterr().out)["hookSpecificOutput"]
    assert out["permissionDecision"] == "deny" and "代役: 走査の例外" in out["permissionDecisionReason"]


def test_length_limit_comes_before_the_parsed_escape_hatch(tmp_path):
    env = {"CLAUDE_CONFIG_DIR": str(tmp_path), "COLDREAD_MAX_LEN": "600"}
    long_body = "'%s'" % ("x" * 700)
    out = run_hook("coldread-gate.py", "cd /tmp && COLDREAD_SKIP=1 gh issue comment 1 --body " + long_body, env)
    assert "COLDREAD_MAX_LEN" in out["permissionDecisionReason"]
    assert denies(tmp_path)[-1].split("\t")[1:3] == ["deny", "maxlen"]
    assert run_hook("coldread-gate.py", "COLDREAD_SKIP=1 gh issue comment 1 --body " + long_body, env) is None
    assert denies(tmp_path)[-1].split("\t")[1] == "skip"


@pytest.fixture
def long_file(tmp_path):
    p = tmp_path / "long.md"
    p.write_text(BODY + " MARKER-SHORT-9 " + "y" * 500, encoding="utf-8")
    return p


def test_short_command_with_a_long_file_body_is_reviewed(tmp_path, long_file):
    command = "gh issue comment 1 --body-file %s" % q(long_file)
    assert len(command) < 400
    out = run_hook("coldread-gate.py", command,
                   {"CLAUDE_CONFIG_DIR": str(tmp_path / "cfg"), "COLDREAD_READER_CMD": seeing_stub("MARKER-SHORT-9")})
    assert "SEEN" in out["permissionDecisionReason"]
    # 読めた本文と、読めない位置引数・止めた理由が同居しても、短いコマンドでは理由で止めずに本文を審査する
    out = run_hook("coldread-gate.py", "gh gist create %s /no/such.md" % q(long_file),
                   {"CLAUDE_CONFIG_DIR": str(tmp_path / "cfg"), "COLDREAD_READER_CMD": seeing_stub("MARKER-SHORT-9")})
    assert "SEEN" in out["permissionDecisionReason"]


@pytest.mark.parametrize("template,grants", [
    ("gh issue comment 1 --body-file {long}", False),
    ("gh issue comment 1 --body-file {long} # %s" % PAD, False),
    ("gh issue comment 1 --body '%s %s'" % (BODY, PAD), True),
], ids=["short-file", "long-file", "long-text"])
def test_passing_review_grants_permission_only_for_text_in_a_long_command(tmp_path, long_file, template, grants):
    # 審査の通過は権限の付与ではない。allow は人の権限の確認を飛ばすので、ファイルの本文と短いコマンドには出さない
    cfg = tmp_path / "cfg"
    out = run_hook("coldread-gate.py", template.format(long=q(long_file)),
                   {"CLAUDE_CONFIG_DIR": str(cfg), "COLDREAD_READER_CMD": CLEAN_STUB})
    assert ("permissionDecision" in out) == grants
    assert "通じやすさのみ" in out["additionalContext"]
    assert denies(cfg)[-1].split("\t")[1] == "allow"


def test_short_command_with_a_long_file_still_honours_the_escape_hatch(tmp_path, long_file):
    cfg = tmp_path / "cfg"
    assert run_hook("coldread-gate.py", "COLDREAD_SKIP=1 gh issue comment 1 --body-file %s" % q(long_file),
                    {"CLAUDE_CONFIG_DIR": str(cfg), "COLDREAD_READER_CMD": "exit 1"}) is None
    assert denies(cfg)[-1].split("\t")[1] == "skip"


@pytest.mark.parametrize("template", [
    "gh issue comment 1 --body-file {short}",
    "gh issue comment 1 --body \"$X\"",
    "cat {long} | gh issue comment 1 --body-file -",
    "gh api -X PUT repos/o/r/actions/secrets/K --input {payload}",
    "gh issue comment 1 --body-file /no/such.md",
    "gh issue comment 1 --body '%s'" % ("短い返信" * 60),
], ids=["short-file", "variable", "pipe", "secret-input", "absent-file", "text-body"])
def test_short_command_without_a_long_file_body_passes_unrecorded(tmp_path, long_file, template):
    short = tmp_path / "short.md"
    short.write_text("短い本文" * 10, encoding="utf-8")
    payload = tmp_path / "payload.json"
    payload.write_text(json.dumps({"encrypted_value": "z" * 300, "key_id": "1"}), encoding="utf-8")
    command = template.format(short=q(short), long=q(long_file), payload=q(payload))
    assert len(command) < 400
    cfg = tmp_path / "cfg"
    assert run_hook("coldread-gate.py", command, {"CLAUDE_CONFIG_DIR": str(cfg), "COLDREAD_READER_CMD": "exit 1"}) is None
    assert not (cfg / "coldread-gate" / "denies.log").exists()


def test_short_command_that_cannot_be_parsed_is_counted(tmp_path, monkeypatch, capsys):
    # 通す判断は下限の前提どおり。ただし本文ファイルの審査が外れた回を数えられるよう、種類だけを残す
    cfg = tmp_path / "cfg"
    assert run_hook("coldread-gate.py", "gh issue comment 1 --body-file 'x.md", {"CLAUDE_CONFIG_DIR": str(cfg)}) is None
    misses = cfg / "coldread-gate" / "misses.log"
    assert misses.read_text(encoding="utf-8").splitlines()[-1].split("\t")[1:] == ["parse-error", "unparseable"]

    def raises(_command):
        raise MemoryError("代役")

    monkeypatch.setattr(gate, "scan_shell", raises)
    monkeypatch.setattr(gate, "STATE_DIR", str(misses.parent))
    monkeypatch.setattr(gate, "MISS_LOG", str(misses))
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps({"tool_input": {"command": "gh issue comment 1"}})))
    with pytest.raises(SystemExit):
        gate.main()
    assert capsys.readouterr().out == ""
    assert misses.read_text(encoding="utf-8").splitlines()[-1].split("\t")[1:] == ["parse-error", "MemoryError"]


# ---- destgate ------------------------------------------------------------------------------------------

def destgate(tmp_path, command, allowlist, cwd=None, env=None):
    (tmp_path / "destgate").mkdir(exist_ok=True)
    (tmp_path / "destgate" / "allowlist").write_text(allowlist, encoding="utf-8")
    return run_hook("dest-gate.py", command, {"CLAUDE_CONFIG_DIR": str(tmp_path), **(env or {})},
                    cwd=str(cwd or tmp_path))


@pytest.mark.parametrize("command,allowed", [
    ("gh pr comment 1 -R evil/place --body " + SUBST, False),
    ("gh issue comment 1 -R evil/place --body-file - <<'EOF' 2>&1 | tail -1\n%s\nEOF" % BODY, False),
    ("gh issue comment 1 -R evil/place --body-file /no/such/body.md", False),
    ("echo \"$(gh issue comment 1 -R evil/place --body hi)\"", False),
    ("x=$(true)#note; gh issue comment 1 -R evil/place --body hi", False),
    ("tee >(gh issue comment 1 -R evil/place --body-file -)", False),
    ("cat notes.md | gh gist create -d d", False),
    ("gh issue comment 1 --title ';' --body hi -R evil/place", False),
    ("gh issue comment 1 " + subst("--repo=evil/place") + " --body hi", False),
    ("gh pr comment 1 -R allowed/repo --body " + SUBST, True),
], ids=["subst", "start-line-tail", "file", "gh-in-subst", "hash-after-subst", "output-process-subst", "gist-pipe",
        "after-quoted-operator", "repo-flag-from-subst", "allowed"])
def test_destgate_checks_destination_of_new_forms(tmp_path, command, allowed):
    out = destgate(tmp_path, command, "allowed/repo\n")
    assert (out is None) == allowed
    if not allowed:
        assert "許可一覧に無い" in out["permissionDecisionReason"] or "特定できない" in out["permissionDecisionReason"]


@pytest.mark.parametrize("command,allowed", [
    ("gh issue comment 1 -R \"evil/repo$(: /owner/x)\" --body hi", False),
    ("gh issue comment 1 -R evil/repo$(: /owner/x) --body hi", False),
    ("gh issue comment 1 -R $(printf 'evil/r #')/owner/x --body hi", False),
    ("gh issue comment 1 --repo=\"evil/repo`: /owner/x`\" --body hi", False),
    ("gh api \"repos/owner/x$(: )/issues/1/comments\" -f body=hi", False),
    ("gh api repos/owner/x/issues/1/comments -f body=hi", True),
    ("gh issue comment 1 -R owner/x --body hi", True),
    ("gh issue comment 1 -R https://github.com/owner/x.git --body hi", True),
    ("gh issue comment 1 -R " + subst("owner/x") + " --body hi", True),
    ("gh issue comment 1 -R " + subst("evil/x") + " --body hi", False),
    ("gh issue comment 1 -R owner/x+y --body hi", False),
    ("gh issue comment 1 -R owner/x --repo=evil/r --body hi", False),
], ids=["quoted-subst", "unquoted-subst", "printf-subst", "backticks", "api-path-subst", "api-path", "literal", "url",
        "static-subst", "static-subst-elsewhere", "not-a-name", "last-repo-wins"])
def test_destgate_judges_the_destination_bash_will_post_to(tmp_path, command, allowed):
    # 展開前の字を許可一覧に照らすと、bash が展開した後の別の宛先に投稿する。GitHub の名前に $ ( ` は入らない
    out = destgate(tmp_path, command, "owner/*\n")
    assert (out is None) == allowed, out
    if not allowed:
        assert "特定できない" in out["permissionDecisionReason"] or "許可一覧に無い" in out["permissionDecisionReason"]


def _git_repo(path, **remotes):
    path.mkdir()
    subprocess.run(["git", "init", "-q", str(path)], check=True)
    for name, url in remotes.items():
        subprocess.run(["git", "-C", str(path), "remote", "add", name, url], check=True)
    return path


PLACEHOLDER_POST = "gh api repos/{owner}/{repo}/issues/1/comments -f body=hi"


def test_destgate_placeholders_without_a_repository_are_matched_as_written(tmp_path):
    # 今のリポジトリが分からなければ、gh の置き換えの前の字のまま照らす(* の一覧なら通る)
    assert destgate(tmp_path, PLACEHOLDER_POST, "*\n") is None
    assert destgate(tmp_path, PLACEHOLDER_POST, "owner/*\n") is not None


def test_destgate_placeholders_take_every_remote_and_gh_repo(tmp_path):
    repo = _git_repo(tmp_path / "w", origin="https://github.com/owner/x.git")
    assert destgate(tmp_path, PLACEHOLDER_POST, "owner/*\n", cwd=repo) is None
    # gh は remote の優先順(upstream が先)と set-default で選ぶので、どの remote も許可一覧に当たる必要がある
    subprocess.run(["git", "-C", str(repo), "remote", "add", "upstream", "https://github.com/other/y.git"], check=True)
    assert destgate(tmp_path, PLACEHOLDER_POST, "owner/*\n", cwd=repo) is not None
    # GH_REPO は remote より先に効く
    assert destgate(tmp_path, PLACEHOLDER_POST, "other/*\n", cwd=repo, env={"GH_REPO": "other/y"}) is None
    assert destgate(tmp_path, PLACEHOLDER_POST, "owner/*\n", cwd=repo, env={"GH_REPO": "evil/z"}) is not None


@pytest.mark.parametrize("command,allowed", [
    ("GH_REPO=owner/y gh issue comment 1 --body hi", True),
    ("GH_REPO=evil/r gh issue comment 1 --body hi", False),
    ("env GH_REPO=owner/y gh issue comment 1 --body hi", True),
    ("env GH_REPO=evil/r gh issue comment 1 --body hi", False),
    ("export GH_REPO=owner/y; gh issue comment 1 --body hi", True),
    ("export GH_REPO=evil/r; gh issue comment 1 --body hi", False),
    ("GH_REPO=evil/r; export GH_REPO; gh issue comment 1 --body hi", False),
    ("GH_REPO=evil/r gh api repos/{owner}/{repo}/issues/1/comments -f body=hi", False),
    ("env " + subst("GH_REPO=owner/y") + " gh issue comment 1 --body hi", True),
    ("env " + subst("GH_REPO=evil/r") + " gh issue comment 1 --body hi", False),
    ("env " + subst("GH_REPO=evil/r") + " " + PLACEHOLDER_POST, False),
    ("GH_REPO=owner/y$(x) gh issue comment 1 --body hi", False),
    ("export GH_REPO=\"$X\"; gh issue comment 1 --body hi", False),
    ("read GH_REPO; gh issue comment 1 --body hi", False),
    ("while read GH_REPO; do gh issue comment 1 --body hi; done", False),
    ("printf -v GH_REPO evil/r; gh issue comment 1 --body hi", False),
    ("for GH_REPO in evil/r; do gh issue comment 1 --body hi; done", False),
    ("declare -n GH_REPO=OTHER; gh issue comment 1 --body hi", False),
    ("echo ${GH_REPO:=evil/r}; gh issue comment 1 --body hi", False),
    ("eval GH_REPO=evil/r; gh issue comment 1 --body hi", False),
    ("builtin export GH_REPO=evil/r; gh issue comment 1 --body hi", False),
    ("builtin eval 'GH_REPO=evil/r'; gh issue comment 1 --body hi", False),
    ("env -S 'GH_REPO=evil/r' gh issue comment 1 --body hi", False),
    ("gh issue comment 1 --body 'GH_REPO=evil/r'", True),
    ("echo 'GH_REPO を直した' && gh pr comment 1 --body hi", True),
    ("[ -n \"$X\" ] && echo GH_REPO; gh issue comment 1 --body hi", True),
    ("printf 'GH_REPO\\n'; gh issue comment 1 --body hi", True),
    ("git commit -m 'fix GH_REPO handling' && gh pr comment 1 --body hi", True),
    ("GH_REPO=evil/r git push && gh pr comment 1 --body hi", True),
    ("source .venv/bin/activate && gh pr create --body hi", True),
], ids=["prefix", "prefix-other", "env", "env-other", "export", "export-other", "assign-then-export", "placeholder",
        "static-subst", "static-subst-other", "static-subst-placeholder", "expanded-value", "export-variable", "read",
        "while-read", "printf-v", "for", "nameref", "assigning-expansion", "eval", "builtin-export",
        "builtin-eval", "env-split", "body-text", "echo", "test-and-echo", "printf-text", "commit-message", "child-prefix", "source"])
def test_destgate_reads_gh_repo_written_in_the_command(tmp_path, command, allowed):
    # gh は GH_REPO を remote より先に使う。字のままの owner/repo はその値で照らし、字から読めない値は特定できないとして
    # 止める。変数を書かない語と子のプロセスの引数の字は数えない
    repo = _git_repo(tmp_path / "w", origin="https://github.com/owner/x.git")
    out = destgate(tmp_path, command, "owner/*\n", cwd=repo)
    assert (out is None) == allowed, out


@pytest.mark.parametrize("command,outside,allowed", [
    ("gh issue comment 1 --body hi", "owner/y", True),
    ("gh issue comment 1 --body hi", "evil/r", False),
    ("unset GH_REPO; gh issue comment 1 --body hi", "owner/y", False),
    ("env -u GH_REPO gh issue comment 1 --body hi", "evil/r", False),
], ids=["outside", "outside-other", "unset-adds-remotes", "env-u-adds-remotes"])
def test_destgate_reads_gh_repo_of_the_hook_environment(tmp_path, command, outside, allowed):
    # 消す形が在れば remote も照らす(remote の upstream は許可一覧の外)
    repo = _git_repo(tmp_path / "w", origin="https://github.com/owner/x.git", upstream="https://github.com/evil/y.git")
    out = destgate(tmp_path, command, "owner/*\n", cwd=repo, env={"GH_REPO": outside})
    assert (out is None) == allowed, out


def test_destgate_takes_every_remote_or_the_set_default(tmp_path):
    # gh は set-default が無ければ remote の優先順(upstream が origin より先)の先頭へ投稿する
    repo = _git_repo(tmp_path / "w", origin="https://github.com/owner/x.git", upstream="https://github.com/evil/y.git")
    post = "gh issue comment 1 --body hi"
    assert destgate(tmp_path, post, "owner/*\n", cwd=repo) is not None
    subprocess.run(["git", "-C", str(repo), "config", "remote.origin.gh-resolved", "base"], check=True)
    assert destgate(tmp_path, post, "owner/*\n", cwd=repo) is None
    # gh-resolved が owner/repo の字なら、gh はその repo へ投稿する
    subprocess.run(["git", "-C", str(repo), "config", "remote.origin.gh-resolved", "evil/z"], check=True)
    assert destgate(tmp_path, post, "owner/*\n", cwd=repo) is not None


@pytest.mark.parametrize("template,allowed", [
    ("cd {other} && gh pr comment 1 --body hi", False),
    ("cd {mine} && gh pr comment 1 --body hi", True),
    ("env -C {other} gh pr comment 1 --body hi", False),
    ("cd {other} && echo \"$(gh pr comment 1 --body hi)\"", False),
    ("gh pr comment 1 --body hi; cd {other}", False),
    ("cd \"$D\" && gh pr comment 1 --body hi", False),
    ("cd - && gh pr comment 1 --body hi", False),
    ("cd {other} && gh pr comment 1 -R owner/x --body hi", True),
    ("builtin cd {other} && gh pr comment 1 --body hi", False),
], ids=["cd-other", "cd-mine", "env-C", "gh-in-subst-after-cd", "cd-after", "cd-variable", "cd-back", "explicit-repo",
        "builtin-cd"])
def test_destgate_judges_the_directory_gh_moves_to(tmp_path, template, allowed):
    # 移った先の remote へ投稿する。行き先と書いた位置は推さず、移る前と全部の行き先の和で照らす
    repo = _git_repo(tmp_path / "w", origin="https://github.com/owner/x.git")
    other = _git_repo(tmp_path / "o", origin="https://github.com/evil/q.git")
    mine = _git_repo(tmp_path / "m", origin="https://github.com/owner/z.git")
    command = template.format(other=q(other), mine=q(mine))
    out = destgate(tmp_path, command, "owner/*\n", cwd=repo)
    assert (out is None) == allowed, out


@pytest.mark.parametrize("command,allowed", [
    ("gh pr review 12 --comment -R evil/x -b hi", False),
    ("gh pr review 12 -b hi -aR evil/x", False),
    ("gh pr review 12 -b hi -cRevil/x", False),
    ("gh api repos/evil/x/issues/1/comments -H -Rx:owner/y -f body=hi", False),
    ("gh --foo issue comment 1 --body hi", False),
    ("gh issue comment 1 --body -R --repo=owner/y", True),
    ("gh issue comment 1 -bR --repo owner/y", True),
    ("gh pr create -H -Revil/x --body hi", True),
], ids=["boolean-comment", "bundled-boolean", "bundled-boolean-inline", "header-value",
        "unknown-flag-before-subcommand", "repo-spelled-in-body", "body-bundle", "head-value"])
def test_destgate_reads_repo_flags_like_gh(tmp_path, command, allowed):
    # 値の読み飛ばしは classify と同じ表で決める。--comment は pr review では値を取らない
    repo = _git_repo(tmp_path / "w", origin="https://github.com/owner/x.git")
    out = destgate(tmp_path, command, "owner/*\n", cwd=repo)
    assert (out is None) == allowed, out


def test_repo_flag_is_the_last_value_gh_uses():
    sub = ("issue", "comment")
    assert gate.repo_flags(["issue", "comment", "1", "-R", "a/b", "-Rc/d", "--repo=e/f", "-R=g/h"], sub) == \
        ["a/b", "c/d", "e/f", "g/h"]
    assert gate.repo_flag(["issue", "comment", "1", "-R", "a/b", "--repo=e/f"], sub) == "e/f"
    assert gate.repo_flags(["issue", "comment", "1", "--body", "-R", "--", "-R", "x/y"], sub) == []


@pytest.mark.parametrize("command", [
    "gh -R evil/x issue comment 1 -b \"$(case a in a) echo hi;; esac)\"",
    "COLDREAD_SKIP=1 gh -R evil/x issue comment 1 -b \"$(case a in a) echo hi;; esac)\" # " + PAD,
    "gh issue comment 1 -R evil/x --body 'unclosed",
], ids=["short", "escape-hatch", "unclosed-quote"])
def test_destgate_stops_commands_it_cannot_analyse(tmp_path, command):
    # coldread は短いコマンドと逃げ道付きのコマンドを通すので、destgate が通すと許可一覧の外へ無検査で出る
    assert gate.analyze(command) is None
    assert run_hook("coldread-gate.py", command, {"CLAUDE_CONFIG_DIR": str(tmp_path / "cr")}) is None
    out = destgate(tmp_path, command, "owner/*\n")
    assert out is not None and "解析できない" in out["permissionDecisionReason"]
    assert (tmp_path / "destgate" / "denies.log").read_text(encoding="utf-8").split("\t")[1].startswith("deny 解析不能")
    (tmp_path / "destgate" / "allowlist").unlink()
    assert run_hook("dest-gate.py", command, {"CLAUDE_CONFIG_DIR": str(tmp_path)}) is None


def test_destgate_names_in_api_paths_are_checked(tmp_path):
    dg = _load("dest_gate_under_test", "dest-gate.py")
    for path, dest in (("orgs/owner/teams", ["owner/*"]), ("orgs/ow$(x)/teams", None),
                       ("repos/owner/x/issues", ["owner/x"]), ("repos/owner/x`y`/issues", None)):
        assert dg.dest_of(["api", path], str(tmp_path)) == dest, path


def test_destgate_analyses_the_command_once(tmp_path, monkeypatch, capsys):
    dg = _load("dest_gate_under_test", "dest-gate.py")
    (tmp_path / "destgate").mkdir()
    (tmp_path / "destgate" / "allowlist").write_text("owner/*\n", encoding="utf-8")
    monkeypatch.setattr(dg, "ALLOWLIST", str(tmp_path / "destgate" / "allowlist"))
    monkeypatch.setattr(dg, "DENY_LOG", str(tmp_path / "destgate" / "denies.log"))
    monkeypatch.setattr(dg.cr, "STATE_DIR", str(tmp_path / "destgate"))
    scans = _count(monkeypatch, dg.cr, "scan_shell")
    command = "gh issue comment 1 -R evil/r --body hi"
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps({"tool_name": "Bash", "tool_input": {"command": command}})))
    with pytest.raises(SystemExit):
        dg.main()
    assert "evil/r" in json.loads(capsys.readouterr().out)["hookSpecificOutput"]["permissionDecisionReason"]
    assert len(scans) == 1


def test_destgate_reads_remotes_once_per_directory(tmp_path, monkeypatch):
    dg = _load("dest_gate_under_test", "dest-gate.py")
    repo = _git_repo(tmp_path / "w", origin="https://github.com/owner/x.git")
    monkeypatch.delenv("GH_REPO", raising=False)
    runs = _count(monkeypatch, dg.subprocess, "run")
    for k in range(50):
        assert dg.dest_of(["issue", "comment", str(k)], str(repo)) == ["owner/x"]
    assert len(runs) == 2   # git remote -v と、set-default の git config


@pytest.mark.parametrize("build", [
    lambda n: "".join("export GH_REPO=owner/x%d; gh issue comment %d --body hi; " % (k, k) for k in range(n)),
    lambda n: "".join("cd /nowhere/d%d; gh pr comment %d --body hi; " % (k, k) for k in range(n)),
    lambda n: "".join("export GH_REPO=owner/x%d; gh api repos/{owner}/{repo}/issues/%d/comments -f body=hi; " % (k, k)
                      for k in range(n)),
    lambda n: "if " * n + "true; gh issue comment 1 --body hi",
], ids=["gh-repo-values", "moves", "placeholders", "leads"])
def test_destgate_work_grows_linearly_with_the_command(tmp_path, monkeypatch, build):
    # 宛先の材料(書いた GH_REPO・移った先)を gh の呼び出しごとに作り直すか照らし直すと 2 乗になり、上限の無い destgate が
    # フックの timeout で外れる。時間は測らず、宛先の読みと許可一覧の照合の回数で縛る
    dg = _load("dest_gate_under_test", "dest-gate.py")
    allowlist = tmp_path / "allowlist"
    allowlist.write_text("owner/*\n", encoding="utf-8")
    monkeypatch.setattr(dg, "ALLOWLIST", str(allowlist))
    monkeypatch.setattr(dg, "remote_repos", lambda cwd: ({"origin": "owner/x"}, {}))
    seen = [_count(monkeypatch, dg, name) for name in ("command_repo", "repos_at", "_name_pair")]
    seen += [_count(monkeypatch, dg.cr, "read_prefix"), _count(monkeypatch, dg.fnmatch, "fnmatchcase")]
    work = []
    for n in (200, 400):
        for s in seen:
            del s[:]
        payload = {"tool_name": "Bash", "cwd": str(tmp_path), "tool_input": {"command": build(n)}}
        monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(payload)))
        assert dg.main() is None   # どれも許可一覧に当たる
        work.append(sum(map(len, seen)))
    assert 0 < work[1] <= 2.2 * work[0], work
