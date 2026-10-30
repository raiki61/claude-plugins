"""gates の waitgate(gates/hooks/wait-gate.py): 手で書いた待ちのループを止め、待ちでないループと 1 回の探しは通す。

フックを本物と同じく別のプロセスで起動し、PreToolUse の入力(JSON)を stdin に渡して、deny の JSON か空の出力かを見る。
設定のフォルダ(CLAUDE_CONFIG_DIR。止めた記録の置き場)は一時の物にする。止める形と通す形は、写した元の
my_notes の tools/tests/test_no_wait_loop.py(master 2d951aab)の表と同じ。
"""

import json
import os
import pathlib
import subprocess
import sys
import tempfile
import unittest

sys.dont_write_bytecode = True
HOOK = pathlib.Path(__file__).resolve().parents[1] / "gates" / "hooks" / "wait-gate.py"


def run(command, tool="Bash", background=False, raw=None, cfg=None, timeout=None):
    """フックを起動する → (deny の理由か None, 標準出力)。timeout(秒)を過ぎたら subprocess.TimeoutExpired。"""
    with tempfile.TemporaryDirectory() as tmp:
        env = dict(os.environ, CLAUDE_CONFIG_DIR=cfg or tmp)
        tool_input = {"command": command}
        if background:
            tool_input["run_in_background"] = True
        data = raw if raw is not None else json.dumps({"tool_name": tool, "tool_input": tool_input, "cwd": tmp})
        p = subprocess.run([sys.executable, str(HOOK)], input=data.encode("utf-8"), capture_output=True, env=env,
                           timeout=timeout)
        out = p.stdout.decode("utf-8")
        if p.returncode != 0:
            raise AssertionError("フックが落ちた(rc=%d): %s" % (p.returncode, p.stderr.decode("utf-8", "replace")))
        if not out.strip():
            return None, out
        got = json.loads(out)["hookSpecificOutput"]
        assert got["permissionDecision"] == "deny", out
        return got["permissionDecisionReason"], out


class FullCommandLine(unittest.TestCase):
    """コマンド行の全体から探す待ち(pgrep -f・pkill -0・ps | grep)。"""

    STOP = [
        # 2026-10-24 に 11 時間止まった形
        'sleep 20; while pgrep -f "research.py theme" >/dev/null; do sleep 5; done; echo done',
        'while pgrep -f "research.py (theme|respond)" >/dev/null; do sleep 5; done',
        'until ! pgrep -fl "research.py" >/dev/null; do sleep 5; done',
        'while pgrep -af "x.py" >/dev/null; do sleep 5; done',
        'while pgrep --full "x.py" >/dev/null; do sleep 5; done',
        "while pgrep -f x.py\ndo\n  sleep 5\ndone",
        'while true; do pgrep -f "x.py" || break; sleep 5; done',
        "for i in 1 2 3; do pgrep -f x.py || break; sleep 5; done",
        "(while pgrep -f x.py >/dev/null; do sleep 5; done; echo done) &",
        "while ps aux | grep -v grep | grep -q x.py; do sleep 5; done",
        "bash -c 'while pgrep -f \"x.py\"; do sleep 5; done'",
        "while ps aux 2>&1 | grep -q x.py; do sleep 5; done",
        "while ps aux |& grep -q x.py; do sleep 5; done",
        "while ps aux | egrep -q x.py; do sleep 5; done",
        "while ps aux | rg -q x.py; do sleep 5; done",
        "while pkill -0 -f x.py; do sleep 5; done",
        "while pidwait -f x.py; do sleep 5; done",
        "while pgrep -f x.py 2>&1 >/dev/null; do sleep 5; done",
        # 待ち(while・until、sleep を回す for)と同じコマンドに在れば止める
        "pgrep -fl research.py; while true; do sleep 5; done",
        # sleep の無い for でも pgrep -f は止める
        "pgrep -fl research.py; for f in /tmp/*.log; do tail -1 $f; done",
        "for i in 1 2 3; do pgrep -f x.py || true; done",
        "if true; then while pgrep -f x.py; do sleep 5; done; fi",
        # 入れ子の中も見る
        'eval "while pgrep -f x.py; do sleep 5; done"',
        'echo "$(while pgrep -f x.py; do sleep 5; done)"',
        "bash -o pipefail -c 'while pgrep -f x.py; do sleep 5; done'",
        "bash -euo pipefail -c 'while pgrep -f x.py; do sleep 5; done'",
        # sleep の無い for でも pgrep -f は止める(分けて打てば通る)
        "for pid in $(pgrep -f foo); do kill $pid; done",
    ]

    def test_stops(self):
        for command in self.STOP:
            with self.subTest(command=command):
                reason, _ = run(command)
                self.assertIsNotNone(reason, "止まらなかった")
                self.assertIn("waitgate", reason)
                self.assertIn("run_in_background", reason)


class SleepLoops(unittest.TestCase):
    """sleep を回す while・until。前景でも裏でも止める。"""

    STOP = [
        # 出力ファイルを取り違えて 27 分止まった形
        'until grep -qE "^(OK|FAILED|Ran )" out.txt; do sleep 5; done',
        # 前景で打っても時間の上限で裏へ移り、28 時間・16 時間回った形
        'until grep -q "^Ran \\|Traceback" out.txt; do sleep 3; done',
        'until [ "$(grep -c . scen.out)" -gt 3 ]; do sleep 10; done',
        "while [ ! -f done.flag ]; do sleep 2; done; echo ok",
        'while kill -0 "$(cat pid.txt)" 2>/dev/null; do sleep 5; done',
        "(until test -f x; do sleep 1; done) && echo ok",
        "time until test -f x; do sleep 1; done",
        "while pgrep -x research; do sleep 5; done",
        "while pgrep research.py; do sleep 5; done",
        "bash <<'EOF'\nwhile true; do sleep 5; done\nEOF",
        # 終わる条件の無い for は while と同じ
        "for ((;;)); do grep -q X f && break; sleep 3; done",
        "for (( ; ; )); do sleep 1; done",
        "bash -o pipefail -c 'until test -f x; do sleep 1; done'",
        # パスで呼ぶシェル・長いオプションのシェルの中も見る
        "/bin/bash -c 'while [ ! -f x ]; do sleep 5; done'",
        "bash --norc -c 'while [ ! -f x ]; do sleep 5; done'",
        "/bin/bash <<'EOF'\nwhile true; do sleep 5; done\nEOF",
        # コメントの中の引用符で、後の行のループを引用符の中と取り違えない
        "# don't spin\nwhile [ ! -f done ]; do sleep 5; done",
        # コメント・引用符の中の <<WORD はヒアドキュメントを始めないので、後の行を中身と見て落とさない
        "echo x\n# cat <<EOF\nuntil false; do sleep 2; done",
        'git log --grep "a <<EOF"\nwhile ! test -f out; do sleep 2; done',
        # ダブルクォートの中の $( ) のヒアドキュメントも読む。前は中身の ' を引用符の頭と読み、後のループを見落として通していた
        "git commit -m \"$(cat <<'EOF'\nfix: don't drop the cache\nEOF\n)\" && git push && until gh run view --exit-status; do sleep 30; done",
        # 複数の行にまたがる引用符の後の行の <<WORD も、ヒアドキュメントを始めない
        'git commit -m "subj\n\nuse cat <<EOF in scripts"\nwhile ! test -f out; do sleep 2; done',
        # 終わりの語を \ で引用する形・引用符の中に - を持つ形も、ヒアドキュメントと読む(中身の ' で後のループを隠さない)
        "cat <<\\EOF\ndon't\nEOF\nuntil test -f x; do sleep 1; done",
        "cat <<'END-1'\ndon't\nEND-1\nuntil test -f x; do sleep 1; done",
        # $( ) の中のヒアドキュメントは、終わりの語で始まり ) を持つ行(`EOF)"`・`EOF )"`)で閉じ、後の行は走る。
        # 前は終わりの語の行と読まず、後の行を全部中身と見て落とし、後のループを見落として通していた
        "gh pr comment 5 --body \"$(cat <<'EOF'\nDone.\nEOF)\"\nuntil gh pr checks 5 | grep -q pass; do sleep 30; done",
        "gh pr comment 5 --body \"$(cat <<'EOF'\nDone.\nEOF )\"\nuntil gh pr checks 5 | grep -q pass; do sleep 30; done",
        # `` ` ` `` の中のヒアドキュメントは、中身の `` ` `` で閉じる
        'x="`cat <<EOF\nDone.\nEOF`"\nuntil gh pr checks 5 | grep -q pass; do sleep 30; done',
        "x=`cat <<EOF\nit's done\nEOF `\nuntil gh pr checks 5 | grep -q pass; do sleep 30; done",
        # zsh は $( ) の中のヒアドキュメントを終わりの語だけの行で閉じる。終わりの語で始まり ) を持つ中身の行で閉じたと読むと、
        # 後の中身の ' で後のループを引用符の中と取り違える。閉じない読みでも見る
        "gh pr comment 5 --body \"$(cat <<'EOF'\nEOF handling (#12) is fixed; it's covered now\nEOF\n)\"\nuntil gh pr checks 5; do sleep 30; done",
        # `` ` ` `` の中の ' は、シェルが先に閉じる `` ` `` を越えない
        "x=`echo it's`\nwhile true; do sleep 5; done",
        "x=`cat <<'EOF'\nrun `ls` it's\nEOF\n`\nwhile true; do sleep 5; done",
        # 置換と `bash -c "…"` の中のヒアドキュメントの後のループ。中身を除いた後の中をもう一度読むときに除き直すと、
        # 終わりの語の行が無いので後のループを中身と見て落としていた
        "x=`cat <<EOF\nhello\nEOF\nuntil test -f M; do sleep 1; done\n`",
        "x=\"$(cat <<EOF\nhi\nEOF\nuntil test -f M; do sleep 1; done\n)\"",
        'bash -c "x=$(cat <<EOF\nhi\nEOF\n)\nuntil test -f M; do sleep 1; done"',
        'eval "x=$(cat <<EOF\nhi\nEOF\n)\nuntil test -f M; do sleep 1; done"',
        # 終わりの語が引用符を持つヒアドキュメント。終わりの語の行を残すと、その ' で後の行を引用符の中と見ていた
        "cat <<\"it's\"\nbody\nit's\nwhile sleep 1; do :; done",
        # 置換を閉じる ) と \ で引用した空白は語の中の字で、その後の # はコメントでない
        "echo $(date +%F)#notes; while sleep 1; do :; done",
        "echo $((1+2))#x; while sleep 1; do :; done",
        "diff <(ls)#x; while sleep 1; do :; done",
        "touch my\\ #1; while sleep 1; do :; done",
        # \ と改行は行をつなぐだけで、`\` の位置が語の頭なら次の行の頭の # はコメント(中の ' で後の行を引用符の中と見ない)
        "echo a \\\n# it's a note\nwhile true; do sleep 1; done",
        "echo a\\\n#x; while true; do sleep 1; done",
        # 置換の中のヒアドキュメントの印の行で、それを囲むヒアドキュメントを閉じない
        'bash -c "cat <<A\n$(cat <<B\nb\nB\n)\nit\'s\nA\nwhile true; do sleep 1; done"',
        # case のパターンの ) が置換の括弧を先に閉じても、置換を閉じる ) の後の # をコメントと見ない
        "echo $(case a in a) echo x;; esac)#x; while true; do sleep 1; done",
        # ${ }・[[ =~ ]]・(( ))・配列の ( ) の中や後の # はコメントでない。コメントと読んでも、読まない読みでも見る
        "echo ${line%% #*}; while true; do sleep 1; done",
        "[[ x =~ (a|#) ]]; while true; do sleep 1; done",
        "(( x = 1 #2 )); while true; do sleep 1; done",
        "a=(x)#; while true; do sleep 1; done",
        # case のパターンの ) の後の # はコメント(中の ' で後の行を引用符の中と見ない)
        "case a in a)# it's\nwhile true; do sleep 1; done;;\nesac",
        # 引用した片とそのままの片を続けた終わりの語は、引用を外した字で閉じる
        "cat <<\"EO\"F\nhi\nEOF\nwhile true; do sleep 1; done",
        "cat <<E\\OF\nhi\nEOF\nwhile true; do sleep 1; done",
        # シェルが読むヒアドキュメントの中の、ヒアドキュメントの中身を除く
        "bash <<'X'\ncat <<'E'\nit's\nE\nwhile true; do sleep 1; done\nX",
        "bash -- <<'EOF'\nwhile true; do sleep 1; done\nEOF",
        # 本物のコメントは、迷う # を読まない読みでもコメントのまま。前はコメントの中の <<WORD・' をコードと読み、
        # 置換の後・\ で引用した空白の後・${ }・[[ =~ ]] の中の # の後ろのループを見落としていた
        "# see <<X\necho $(true)# ; until test -f x; do sleep 1; done",
        "# it's\necho $(true)#'\n'\nuntil test -f x; do sleep 1; done",
        "# feed it with cat <<EOF\necho a\\ #; until test -f x; do sleep 1; done",
        ": # it's\necho a\\ #'\n'\nuntil test -f x; do sleep 1; done",
        "# it's\nx=a; : ${x%% #*}; until test -f x; do sleep 1; done",
        "# don't\n[[ a =~ (a|#) ]]; until test -f x; do sleep 1; done",
        # コメントの中の \ は行をつながない(前は次の行のコメントを語の中の字と読み、中の ' や <<EOF で後ろのループを見落とした)
        "# see C:\\tmp\\\n# don't wait forever\nuntil test -f x; do sleep 1; done",
        "ls  # trailing\\\n# note: it's flaky\nuntil test -f x; do sleep 1; done",
        "# usage: foo\\\n# cat <<EOF\nuntil test -f x; do sleep 1; done",
        # ( の後の # はパターンの字のことがある(zsh の (#i)・bash の @(#|x)・case の (#*))
        "setopt extendedglob; ls -d /(#i)TMP; until test -f x; do sleep 1; done",
        "for l in '#x'; do case $l in (#*) echo c;; esac; done; until test -f x; do sleep 1; done",
        "echo /(#|tmp); until test -f x; do sleep 1; done",
        "shopt -s extglob\necho /@(#|tmp); until test -f x; do sleep 1; done",
        # 複数の行にまたがる ${ }・[[ ]]・$(( ))・入れ子の括弧の中の #
        "x=${y:-\n#}; until test -f x; do sleep 1; done",
        "echo ${x%%\n #*}; until test -f x; do sleep 1; done",
        "[[ a =~ (a|\n#) ]]; until test -f x; do sleep 1; done",
        "echo $((1+\n#2)); until test -f x; do sleep 1; done",
        "(( x = (1+(2)) #3 )); until test -f x; do sleep 1; done",
        # ${ } の中の $( )・` `・{ } の } で ${ } を閉じない
        "echo ${x:-`echo }` #}; until test -f x; do sleep 1; done",
        "echo ${x:-$(echo }) #}; until test -f x; do sleep 1; done",
        "echo ${x:-{a} #}; until test -f x; do sleep 1; done",
        # if・time -p の直後のループ
        "if until test -f x; do sleep 1; done; then :; fi",
        "time -p until test -f x; do sleep 1; done",
        # `EOF)` で閉じた後ろは外の ${ } の中。外のシェルが \\ を \ にする中身の `\ #` は語の中の字
        "echo ${y:-$(cat <<EOF\nhi\nEOF) # $(until test -f x; do sleep 1; done)}",
        "bash <<X\necho a\\\\ #b; until test -f x; do sleep 1; done\nX",
        # 引数の中の `a=(`・`--color=(` は zsh でパターン(中の # はコメントでない)
        "ls a=(x #) ; until test -f x; do sleep 1; done",
        "ls --color=(auto|#x); until test -f x; do sleep 1; done",
        # 外のシェルが \${ を ${ にするので、中の # はコメントでない
        "bash <<EOF\nname=\\${line%% #*}; until test -f x; do sleep 1; done\nEOF",
        # <<- の中身は外のシェルが行の頭のタブを除いてから渡すので、中の <<X は \tX の行で閉じる
        "bash <<-'E'\n\tcat <<X\n\thello\n\tX\n\tuntil test -f x; do sleep 1; done\nE",
        "bash <<-'EOF'\n\techo a\\\n\t#b; until test -f x; do sleep 1; done\nEOF",
        # バッククォートの中の \$ はシェルが $ にするので、中の # はコメントでない
        "echo `echo \\${HOME%% #*}; until test -f x; do sleep 1; done`",
        "echo \"`echo \\${HOME%% #*}; until test -f x; do sleep 1; done`\"",
        # `-s`・`-` の後に引数を書いても、`\` で行を続けても、シェルは中身を走らせる
        "bash -s -- arg <<'EOF'\nuntil test -f x; do sleep 1; done\nEOF",
        "bash - <<'EOF'\nuntil test -f x; do sleep 1; done\nEOF",
        "bash \\\n  <<'EOF'\nuntil test -f x; do sleep 1; done\nEOF",
        # 終わりの語を引用しない中身の \` は、外のシェルが ` にして渡す
        "ssh h bash <<EOF\nst=\\`until test -f x; do sleep 1; done; echo ok\\`\nEOF",
        # ダブルクォートの中のバッククォートの \" は、シェルが " にして読む
        'x="`echo \\"it\'s\\"; until test -f x; do sleep 1; done`"',
        # 引用しない <<- の \ + 改行の次の行は、外のシェルが頭のタブを残してつなぐ(`do\` と `\t\tsleep` は別の語)
        "bash <<-EOF\n\tuntil test -f x; do\\\n\t\tsleep 1; done\n\tEOF",
        # 終わりの語の前の行の末尾の \ を外しても、終わりの語の行を消さない
        "bash <<EOF\ncd /tmp && \\\nEOF\n# wait until the build's done\nuntil test -f x; do\n  [ ${#errs} -gt 0 ] && break; sleep 1\ndone",
    ]
    PASS = [
        "python3 tools/check_route.py",
        "sleep 5; echo done",
        "for i in 1 2 3; do sleep 1; done",
        "while read l; do echo $l; done < f",
        # while read は行を読み終えれば終わる
        "while read u; do curl $u; sleep 1; done < urls",
        "while IFS= read -r u; do sleep 1; done < urls",
        "for ((i = 0; i < 3; i++)); do sleep 1; done",
        # コメントの中のループは走らない。$# と ${#x} はコメントでない
        "# while true; do sleep 5; done\necho ok",
        'echo $# ${#x}; for i in 1 2; do sleep 1; done',
        # 本物のヒアドキュメントの中身(シェルでないコマンドが読む)は、今までどおり見ない
        "cat <<'EOF' > note.md\nwhile true; do sleep 5; done\nEOF",
        "git commit -m \"$(cat <<'EOF'\nwhile true; do sleep 5; done\nEOF\n)\"",
        "gh pr comment 5 --body \"$(cat <<'EOF'\nEOF handling (#12) is fixed; it's covered now\nEOF\n)\"",
        "x=`echo 'a b'`; echo \"$x\"",
        "bash <<'X'\ngit commit -m \"$(cat <<'EOF'\nwhile true; do sleep 5; done\nEOF\n)\"\nX",
        # `bash script.sh` は中身を走らせず、データとして読ませる
        "bash script.sh arg <<'EOF'\nwhile true; do sleep 5; done\nEOF",
        "bash - script.sh <<'EOF'\nwhile true; do sleep 5; done\nEOF",
        # 終わりの語がループの語のヒアドキュメント。終わりの語の行を残すと、ループの語に見えて止めていた
        "cat <<until\nx\nuntil\nsleep 1\n",
        "(true)# it's fine\necho ok",
        'bash -c "cat <<A\n$(cat <<B\nb\nB\n)\n  sleep 1 done;\nA\nuntil [ -f x ]; do :; done"',
        "echo x # it's fine\nls",
        "cat <<E\"OF\"\nuntil x; do sleep 1; done\nEOF\necho ok",
        # 本物のコメントの中のループの語・' をコードと読まない
        "# Create a helper that's used by CI\ncat > /tmp/retry_x.sh <<'EOF'\n# Retry until it succeeds (don't give up)\n"
        "until \"$@\"; do sleep 2; done\nEOF\nchmod +x /tmp/retry_x.sh",
        "sleep 0 # then while it builds, check logs",
        "# Poll the service (until healthy) and sleep between tries\ncurl -s localhost:8080/health",
        # ただの { } のまとまり・サブシェル・関数の中身・シェルが読むヒアドキュメントの中身のコメントも、コメントのまま
        "start_server() {\n  # Record start time while the server boots\n  ./server &\n  sleep 3\n}\nstart_server",
        "(\n  cd /tmp\n  # Hold the lock (while the job runs) and give it a moment\n  sleep 1\n)",
        "{\n  echo start\n  # step 2 (until v2 ships): sleep before the probe\n  sleep 1\n} > log",
        "{\n  # check if while the server boots the port answers\n  sleep 5; curl localhost\n}",
        "bash <<'X'\n# note: (while it runs) we sleep\nsleep 1\nX",
        # 複数の行の配列の中のコメントも、コメントのまま
        'args=(\n  --retry 5   # (until the server is up)\n  --silent\n)\ncurl "${args[@]}" localhost; sleep 1',
        "declare -A m=(\n  [a]=1  # (until v2)\n)\nsleep 0",
        # 外のシェルが外す \$ は、中のコメントの読みを変えない
        "bash <<EOF\ncd \\$HOME\n# make && while ! curl -s localhost; do sleep 1; done\nEOF",
    ]

    def test_stops_in_the_foreground_and_the_background(self):
        for command in self.STOP:
            for background in (False, True):
                with self.subTest(command=command, background=background):
                    reason, _ = run(command, background=background)
                    self.assertIsNotNone(reason, "止まらなかった")
                    self.assertIn("前景でも裏でも", reason)

    def test_passes(self):
        for command in self.PASS:
            for background in (False, True):
                with self.subTest(command=command, background=background):
                    reason, out = run(command, background=background)
                    self.assertIsNone(reason, out)


class Passes(unittest.TestCase):
    PASS = [
        "pgrep -f x.py",   # ループでない 1 回の探しは止めない
        'pgrep -x python3 && echo "while pgrep -f x.py; do sleep 5; done"',
        "while pgrep -x research; do :; done",   # sleep を回さない
        "for f in a b; do echo $f; done",
        "git commit -m 'while pgrep -f x.py; do sleep 5; done'",
        "cat <<'EOF'\nwhile pgrep -f x.py; do sleep 5; done\nEOF",
        # オプションや語の一部の until・for はループでない
        "python3 tools/usage.py --since X --until Y; pgrep -fl research.py",
        "ps aux | grep wait-for-it",
        "ps -o pid,command -p 1",
        "while read l; do ps aux; done < f",
        # sleep の無い for は回数が決まっていて待ちでない。ps | grep は通す
        "for f in a b; do lsof $f | xargs ps -p | grep -v PID; done",
        "for i in 1 2; do echo $i; done; ps aux | grep x",
        "ls",
        "ps aux | grep py | while read u pid _; do kill $pid; done",
        "pgrep -f x | while read p; do echo $p; done",
    ]

    def test_passes(self):
        for command in self.PASS:
            with self.subTest(command=command):
                reason, out = run(command)
                self.assertIsNone(reason, out)

    def test_other_tools_pass(self):
        self.assertIsNone(run("while pgrep -f x.py; do sleep 5; done", tool="Monitor")[0])
        self.assertIsNone(run("while pgrep -f x.py; do sleep 5; done", tool="Edit")[0])

    def test_bash_without_command_passes(self):
        self.assertIsNone(run(None, raw=json.dumps({"tool_name": "Bash", "tool_input": {}}))[0])


class LongCommands(unittest.TestCase):
    """長いコマンドも、hooks.json の時間の上限(30 秒)の内に読み終える。時間切れのフックは止めずに通す。"""

    def test_many_quotes_are_read_in_time(self):
        # 前は引用符ごとに前の出力の全体を探し、52KB で約 50 秒かかった(時間切れで通る)
        command = "for f in *; do :; done\n" + "\n".join("echo 'a' 'b'" for _ in range(4000))
        command += "\nwhile [ ! -f done ]; do sleep 5; done"
        reason, _ = run(command, timeout=20)
        self.assertIsNotNone(reason, "止まらなかった")
        self.assertIn("前景でも裏でも", reason)

    def test_too_many_words_before_dash_c_are_stopped(self):
        # `bash -c` の形を探して戻る語が多すぎるときは、読めないとして止める(通す側に倒さない)
        command = "for f in *; do :; done\nx " + " ".join("-c 'a'" for _ in range(1100))
        reason, _ = run(command, timeout=20)
        self.assertIn("検査自体に失敗した", reason)


    def test_many_option_words_are_read_in_time(self):
        # 前は -o の値に - で始まる語を許し、`-o -o …` の割り方が語の数の指数で増えて 40 語で約 60 秒かかった(時間切れで通る)
        reason, _ = run(": bash " + "-o " * 40 + "a-c 'x'; while true; do sleep 1; done", timeout=20)
        self.assertIsNotNone(reason, "止まらなかった")

    def test_many_blank_lines_are_read_in_time(self):
        # 前はループの語の前の空白に改行も数え、空の行の続きを改行ごとに読み直して 8 万行で約 50 秒かかった(時間切れで通る)
        reason, _ = run("true" + "\n" * 80000 + ":\nuntil test -f x; do sleep 1; done", timeout=20)
        self.assertIsNotNone(reason, "止まらなかった")

    def test_many_comments_in_backticks_are_read_in_time(self):
        # 前はバッククォートの中のコメントごとに閉じる ` を探し直し、60KB で約 40 秒かかった(時間切れで通る)
        reason, _ = run("echo `" + "\n#" * 45000 + "\n`; until test -f x; do sleep 1; done", timeout=20)
        self.assertIsNotNone(reason, "止まらなかった")

    def test_nested_unclosed_heredocs_are_read_in_time(self):
        # 前は閉じないヒアドキュメントの入れ子ごとに後ろの全部を 1 行ずつ読み直し、10 万字で 30 秒を超えた(時間切れで通る)
        loop = "until test -f x; do sleep 1; done"
        for command in ("x=$(:)# ; " + loop + "\n" + "cat <<A\n" * 985 + "\n" * 92000,
                        loop + "\n# x\n" + "bash <<A\n" * 900 + "\n" * 92000):
            reason, _ = run(command, timeout=20)
            self.assertIsNotNone(reason, "止まらなかった")

    def test_nested_closed_heredocs_read_by_shells_are_read_in_time(self):
        # 前はシェルが読む中身ごとに、終わりの語の行を 1 行ずつ探し直し、入れ子 900 段で 40 秒を超えた
        command = ("".join("bash <<A%d\n#\n" % i for i in range(900)) + "x\n" * 40000
                   + "".join("A%d\n" % i for i in reversed(range(900))) + "echo $(date)# ; while true; do sleep 1; done")
        reason, _ = run(command, timeout=20)
        self.assertIsNotNone(reason, "止まらなかった")

    def test_deeply_nested_substitutions_with_many_comments_are_read_in_time(self):
        # 前はヒアドキュメントの無い置換の中身も入れ子ごとに読み直し、270 段で 30 秒を超えた
        command = 'echo ' + '"$(echo ' * 270 + "#\n" * 46000 + ')"' * 270 + "\necho $(date)# ; while true; do sleep 1; done"
        reason, _ = run(command, timeout=20)
        self.assertIsNotNone(reason, "止まらなかった")

    def test_many_heredocs_on_continued_lines_are_read_in_time(self):
        # `\` で続けた 1 行に演算子が何千も在っても、演算子ごとに前の行を全部たどり直さない
        command = "cat <<A \\\n" * 10000 + "A\n" * 10001 + "echo $(date)# ; until test -f x; do sleep 1; done"
        reason, _ = run(command, timeout=20)
        self.assertIsNotNone(reason, "止まらなかった")

    def test_many_lines_that_almost_end_a_heredoc_are_read_in_time(self):
        # 前は終わりの語に似た行(<<- の引用したタブの語の行)ごとに後ろの全部を探し直し、96KB で 30 秒を超えた
        command = "echo $(date)#; until test -f x; do sleep 1; done\nx=$(cat <<-'\tE'\n" + "\tE\n" * 32000 + ")"
        reason, _ = run(command, timeout=20)
        self.assertIsNotNone(reason, "止まらなかった")

    def test_many_hashes_in_nested_substitutions_are_read_in_time(self):
        # 前は # ごとに行の終わりを探し直し、改行の無い長い行を入れ子の置換ごとに読んで約 40 秒かかった(時間切れで通る)
        command = 'echo "$(' * 40 + "echo ${x" + " #" * 45000 + "}; until test -f x; do sleep 1; done" + ')"' * 40
        reason, _ = run(command, timeout=20)
        self.assertIsNotNone(reason, "止まらなかった")


class FailClosed(unittest.TestCase):
    def test_unreadable_input_is_stopped(self):
        reason, _ = run(None, raw="not json")
        self.assertIn("検査自体に失敗した", reason)

    def test_command_that_is_not_a_string_is_stopped(self):
        reason, _ = run(None, raw=json.dumps({"tool_name": "Bash", "tool_input": {"command": ["while"]}}))
        self.assertIn("検査自体に失敗した", reason)

    def test_stop_is_logged(self):
        with tempfile.TemporaryDirectory() as cfg:
            run("while [ ! -f x ]; do sleep 1; done", cfg=cfg)
            log = pathlib.Path(cfg, "waitgate", "denies.log").read_text(encoding="utf-8")
            self.assertIn("deny while [ ! -f x ]", log)


class Registration(unittest.TestCase):
    def test_hook_is_registered_for_bash(self):
        hooks = json.loads((HOOK.parent / "hooks.json").read_text(encoding="utf-8"))["hooks"]["PreToolUse"]
        found = [h for g in hooks if g["matcher"] == "Bash" for h in g["hooks"] if "wait-gate.py" in h["command"]]
        self.assertEqual(len(found), 1)


if __name__ == "__main__":
    unittest.main(verbosity=1)
