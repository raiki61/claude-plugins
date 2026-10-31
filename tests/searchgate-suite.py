"""gates の searchgate(gates/hooks/search-gate.py): / やホームの全体から探すのを止め、それより下と作業場の中は通す。

フックを本物と同じく別のプロセスで起動し、PreToolUse の入力(JSON)を stdin に渡して、deny の JSON か空の出力かを見る。
HOME と設定のフォルダ(CLAUDE_CONFIG_DIR。止めた記録の置き場)は一時の物にする。HOME は Python から子に渡す
(Windows の Git Bash から渡すと / で始まる値が Windows の形に書き換わる)。
"""

import json
import os
import pathlib
import random
import subprocess
import sys
import tempfile
import time
import unittest

sys.dont_write_bytecode = True
HOOK = pathlib.Path(__file__).resolve().parents[1] / "gates" / "hooks" / "search-gate.py"
HOME = "/home/tester"
WORK = HOME + "/src/repo"


def run(tool, tool_input, cwd=WORK, raw=None):
    """フックを起動する → (deny の理由か None, 標準出力)。"""
    with tempfile.TemporaryDirectory() as cfg:
        env = dict(os.environ, HOME=HOME, CLAUDE_CONFIG_DIR=cfg)
        data = raw if raw is not None else json.dumps({"tool_name": tool, "tool_input": tool_input, "cwd": cwd})
        p = subprocess.run([sys.executable, str(HOOK)], input=data.encode("utf-8"), capture_output=True, env=env)
        out = p.stdout.decode("utf-8")
        if p.returncode != 0:
            raise AssertionError("フックが落ちた(rc=%d): %s" % (p.returncode, p.stderr.decode("utf-8", "replace")))
        if not out.strip():
            return None, out
        got = json.loads(out)["hookSpecificOutput"]
        assert got["permissionDecision"] == "deny", out
        return got["permissionDecisionReason"], out


class Bash(unittest.TestCase):
    STOP = [
        "find / -name dag-executor.ts -not -path '*/node_modules/*' 2>/dev/null | head -1",
        "f=$(find / -name dag-executor.ts -path '*archon*' 2>/dev/null | head -1)",
        "find ~ -name research.json",
        "find ~/ -name x",
        "find $HOME -name x",
        'find "${HOME}" -name x',
        "find /home/tester -name x",
        "find /home/tester/src/.. -name x",
        "find /Users -name x",
        "find /System/Volumes/Data -name x",
        "find /Volumes /tmp -name x",
        "find -L / -name x",
        "/usr/bin/find / -name x",
        "bfs -S dfs / -name x",
        "gfind / -name x",
        "cd a && find ~ -name x",
        "timeout 60 find / -name x",
        "nice -n 19 find / -name x",
        "sudo find / -name x",
        'echo "$(find / -name x)"',
        "a=`find / -name x`",
        'bash -c "find / -name x"',
        "sh -lc 'cd /tmp && find / -name x'",
        'eval "find / -name x"',
        "D=/; find $D -name x",
        "D=$HOME && find $D -name x",
        "if true; then find / -name x; fi",
        "fd research.json /",
        "fd -e ts dag ~",
        "fd --search-path / x",
        "rg -n pattern /",
        "rg -e pattern ~",
        "grep -rn needle /",
        "grep -R --include='*.json' needle ~",
        "xargs -0 find / -name x",
        "xargs -I {} find / -name {}",
        "find ~/* -name x",
        "grep -rn needle /Users/*",
        "rg needle /*",
        "bash -o pipefail -c 'find / -name x'",
        "bash -euo pipefail -c 'find ~ -name x'",
        # Linux の / の直下の大きいフォルダ
        "find /home -name x",
        "find /usr -name x",
        "rg needle /var",
        "fd x /mnt",
        "grep -rn needle /root",
        # Windows のドライブのルート(どの書き方でも)とその下の大きいフォルダ。大文字と小文字は区別しない
        "find C:/ -name x",
        "find 'C:\\' -name x",
        "find /c/ -name x",
        "find /cygdrive/c -name x",
        "find /mnt/c -name x",
        "find /c/Users -name x",
        "find 'C:\\Users' -name x",
        "find C:/Users/.. -name x",
        "find 'C:\\Windows\\..' -name x",
        "find /c/Windows -name x",
        "rg needle 'C:/Program Files'",
        "find /users -name x",
        "find /HOME -name x",
        # 旗の終わりの -- の後ろも起点(BSD・GNU・bfs の find)
        "find -- / -name x",
        "find -H -- /Users -name x",
    ]
    PASS = [
        "find . -name x",
        "find ~/.cache/works-factory -name dag-executor.ts",
        "find $HOME/.cache -name x",
        "find /home/tester/src/repo -name x",
        "find /tmp -name x",
        "find /opt/homebrew -name x",
        "find src -name x",
        'grep -rn "find /" README.md',
        "echo 'find / -name x'",
        "git log --grep find",
        "grep needle /etc/hosts",
        "ls / | grep -r needle",
        "cat a | rg needle",
        "rg needle",
        "fd x",
        "fd -x rm / x",
        "find $UNKNOWN -name x",
        "git status",
        "cat <<'EOF'\nfind / -name x\nEOF",
        "find ~/src/* -name x",
        "git log | grep -i needle",
        "find /usr/local/lib -name x",
        "find /c/Users/tester/src -name x",
        "find 'C:\\Users\\tester\\src' -name x",
        "find /mnt/data -name x",
    ]
    # 作業場がホームのときも通す形(起点を取らない呼び出し)
    PASS_IN_HOME = [
        "rg --version",
        "fd --help",
        "find --version",
        "command -v rg",
        "nice -n 19 pytest -k find",
        "fd -V",
    ]

    def test_stops_wide_starts(self):
        for command in self.STOP:
            with self.subTest(command=command):
                reason, _ = run("Bash", {"command": command})
                self.assertIsNotNone(reason, "止まらなかった")
                self.assertIn("searchgate", reason)
                self.assertIn("逃げ道は無い", reason)

    def test_passes_narrow_starts(self):
        for command in self.PASS:
            with self.subTest(command=command):
                reason, out = run("Bash", {"command": command})
                self.assertIsNone(reason, out)

    def test_passes_calls_without_a_start(self):
        for command in self.PASS_IN_HOME:
            with self.subTest(command=command):
                reason, out = run("Bash", {"command": command}, cwd=HOME)
                self.assertIsNone(reason, out)

    def test_names_the_start_it_stopped(self):
        reason, _ = run("Bash", {"command": "find ~ -name x"})
        self.assertIn("find の起点 /home/tester は", reason)

    @unittest.skipIf(os.name == "nt", "cd の行き先は Windows では cygpath で Windows の形に直る(coldread と同じ読み方)")
    def test_relative_start_after_cd(self):
        self.assertIsNotNone(run("Bash", {"command": "cd / && find . -name x"})[0])
        # 探すコマンドより後ろの繰り返しの語は、前の cd が走るかを変えない
        self.assertIsNotNone(run("Bash", {"command": "cd / && find . -name x | while read f; do echo $f; done"})[0])
        self.assertIsNotNone(run("Bash", {"command": "cd / && find . -name x; for f in a; do :; done"})[0])
        # 前の繰り返しの中の cd は走りうるので、行き先と前の場所の両方を見る(前は解かずに通していた)
        self.assertIsNotNone(run("Bash", {"command": "for d in a; do cd /; done; find . -name x"})[0])
        self.assertIsNone(run("Bash", {"command": "for d in a; do cd /tmp; done; find . -name x"})[0])
        # 前の繰り返しの中の代入で、後ろの cd まで解くのをやめない
        self.assertIsNotNone(run("Bash", {"command": "for f in *; do n=$f; done; cd / && find . -name x"})[0])
        # 相対の cd は、そこまでに決まった場所に繋ぐ
        self.assertIsNotNone(run("Bash", {"command": "cd .. && find . -name x"}, cwd=HOME + "/src")[0])
        self.assertIsNotNone(run("Bash", {"command": "cd ../.. && rg needle"})[0])
        self.assertIsNone(run("Bash", {"command": "cd .. && find . -name x"})[0])
        self.assertIsNotNone(run("Bash", {"command": "cd ~ || exit 1; find ."})[0])
        # && の後の cd は、; の後ろのコマンドが走るときに走ったとは限らない。行き先の読めない cd も、走るとは限らなければ前の場所を見る
        self.assertIsNotNone(run("Bash", {"command": "test -d sub && cd sub; find . -name x"}, cwd=HOME)[0])
        self.assertIsNone(run("Bash", {"command": "test -d sub && cd sub && find . -name x"}, cwd=HOME)[0])
        self.assertIsNotNone(run("Bash", {"command": 'cd /; if [ -n "$X" ]; then cd "$X"; fi; find . -name x'})[0])
        # 走るとは限らない cd が続いても、場所は倍々に増えない(前は 20 個で時間切れになり、時間切れは通す)
        many = "".join("if [ -d d%d ]; then cd d%d; fi\n" % (i, i) for i in range(40)) + "find . -name x"
        started = time.monotonic()
        self.assertIsNotNone(run("Bash", {"command": many}, cwd=HOME)[0])
        self.assertLess(time.monotonic() - started, 10)
        # 前の繰り返しが cd・代入を持たなければ、後ろの cd はそのまま走る(前は語が在るだけで解くのをやめていた)
        self.assertIsNotNone(run("Bash", {"command": "for f in *.md; do echo $f; done; cd / && find . -name x"})[0])
        self.assertIsNotNone(run("Bash", {"command": "cd /; while read f; do :; done < list; find . -name x"})[0])

    @unittest.skipIf(os.name == "nt", "cd の行き先は Windows では cygpath で Windows の形に直る(coldread と同じ読み方)")
    def test_later_cd_in_a_loop_moves_the_next_pass(self):
        # 繰り返しの中で探すコマンドの後ろに書いた cd は、2 回目からの探す場所を変える
        for command, cwd in (("for d in a b; do find . -name x; cd ..; done", HOME + "/src"),
                             ("for i in 1 2; do find . -name x; cd /; done", WORK),
                             ("while true; do find . -name x; cd ~; done", WORK),
                             ("for d in a b; do rg foo; cd ../..; done", WORK),
                             ("while cd ..; do find . -name x; done", HOME + "/src"),
                             ("for i in 1; do for j in 1 2; do find . -name x; cd ..; done; done", HOME + "/src")):
            with self.subTest(command=command):
                self.assertIsNotNone(run("Bash", {"command": command}, cwd=cwd)[0])
        # サブシェルの中の cd と、戻ってくる cd は、次の回の場所を広げない
        for command in ("for d in a b; do (cd $d && find . -name x); done", "for d in a b; do find . -name x; (cd /); done",
                        "for d in a b; do cd a; find . -name x; cd ..; done", "for i in 1 2; do find . -name x; cd /tmp; done"):
            with self.subTest(command=command):
                self.assertIsNone(run("Bash", {"command": command})[0])
        # 走るとは限らない cd を繰り返しの中に並べても、時間切れ(時間切れは通す)にならない
        many = "".join("if [ -d d%d ]; then cd d%d; fi\n" % (i, i) for i in range(40))
        started = time.monotonic()
        self.assertIsNotNone(run("Bash", {"command": "while true; do\n" + many + "find . -name x\n" + many + "done"},
                                 cwd=HOME)[0])
        self.assertLess(time.monotonic() - started, 10)

    @unittest.skipIf(os.name == "nt", "cd の行き先は Windows では cygpath で Windows の形に直る(coldread と同じ読み方)")
    def test_cd_in_a_loop_before_the_search_repeats(self):
        # 探すコマンドより前に閉じる繰り返しの中の cd は、回ごとに重なる(前は 1 回だけたどり、2 回目の cd .. を見落として通していた)
        cwd = HOME + "/src/repo"
        for command in ("for i in 1 2; do cd ..; done; find . -name x", "for i in 1 2 3; do cd ..; done; find . -name x",
                        "while [ ! -d .git ]; do cd ..; done; rg foo .", "for i in 1 2; do cd ..; done && find . -name x",
                        "for i in 1; do for j in 1 2; do cd ..; done; done; find . -name x"):
            with self.subTest(command=command):
                self.assertIsNotNone(run("Bash", {"command": command}, cwd=cwd)[0])
        # 戻ってくる cd・絶対の行き先・サブシェルの中の cd・抜けた後の cd は、探す場所を広げない
        for command in ('for d in */; do cd "$d" || continue; make; cd ..; done; rg y .',
                        "for i in 1 2; do cd /tmp; done; find . -name x", "for i in 1 2; do (cd ..); done; find . -name x",
                        "while [ ! -d .git ]; do cd ..; done; cd /tmp; rg foo .",
                        "for d in a b; do cd a; make; cd ..; done; rg y ."):
            with self.subTest(command=command):
                self.assertIsNone(run("Bash", {"command": command}, cwd=cwd)[0])
        # 入れ子の繰り返しの cd で場所が増え続けても、時間切れ(時間切れは通す)の前に、読み切れないとして止める
        nest = "for a in 1; do " * 6 + "cd d; " + "done; " * 6 + "find . -name x"
        started = time.monotonic()
        self.assertIsNotNone(run("Bash", {"command": nest}, cwd=cwd)[0])
        self.assertLess(time.monotonic() - started, 10)

    @unittest.skipIf(os.name == "nt", "cd の行き先は Windows では cygpath で Windows の形に直る(coldread と同じ読み方)")
    def test_cd_or_continue_skips_the_rest_of_the_pass(self):
        # `cd "$d" || continue`・`|| break` の cd が落ちると、この回の残り(後ろの cd .. も)を飛ばすので、動かなかった場所から
        # cd .. で / やホームに届くことはない(前は届くと読み、/tmp や ~/work の下を回る繰り返しを止めていた)
        for cwd in ("/tmp", HOME + "/work", "/usr/src"):
            for command in ('for d in */; do cd "$d" || continue; rg -l TODO .; cd ..; done',
                            'for d in */; do cd "$d" || break; rg -l TODO .; cd ..; done',
                            'for d in */; do cd "$d" || continue; find . -name x; cd ..; done'):
                with self.subTest(command=command, cwd=cwd):
                    self.assertIsNone(run("Bash", {"command": command}, cwd=cwd)[0])
        # 外の繰り返しへ抜ける continue 2・繰り返しの後ろ・サブシェルの中の exit は、落ちた cd の後ろを飛ばさない
        for command in ('for d in */; do cd "$d" || continue 2; rg x .; cd ..; done',
                        'for d in */; do cd "$d" || break; cd ..; done; rg x .',
                        "for d in a; do cd /tmp || continue; done; rg x .", "cd /tmp || ( exit 1 ); rg x ."):
            with self.subTest(command=command):
                self.assertIsNotNone(run("Bash", {"command": command}, cwd=HOME)[0])

    @unittest.skipIf(os.name == "nt", "cd の行き先は Windows では cygpath で Windows の形に直る(coldread と同じ読み方)")
    def test_continue_where_a_condition_cd_failed_skips_the_rest_of_the_pass(self):
        # `if ! cd "$d"; then continue; fi` の then も、cd が落ちたときにこの回の残りを飛ばす(前は exit・return だけを見て、
        # 動かなかった場所からの cd .. でホームに届いたと読み、止めていた)
        for cwd in ("/tmp", HOME + "/work", HOME + "/src/repo"):
            for command in ('for d in */; do if ! cd "$d"; then continue; fi; rg x .; cd ..; done',
                            'for d in */; do if ! cd "$d"; then echo "skip $d"; continue; fi; rg x .; cd ..; done',
                            'for d in */; do if ! cd "$d"; then break; fi; rg x .; cd ..; done',
                            'for d in */; do if cd "$d"; then :; else continue; fi; rg x .; cd ..; done'):
                with self.subTest(command=command, cwd=cwd):
                    self.assertIsNone(run("Bash", {"command": command}, cwd=cwd)[0])
        # 外の繰り返しへ抜ける continue 2・繰り返しの後ろ・繰り返しの外・サブシェルや && の後ろの continue は飛ばさない
        for command in ('for d in */; do if ! cd "$d"; then continue 2; fi; rg x .; cd ..; done',
                        "for d in a; do if ! cd /tmp; then continue; fi; done; rg x .",
                        "if ! cd /tmp; then continue; fi; rg x .",
                        'for d in */; do if ! cd "$d"; then (continue); fi; rg x .; done',
                        'for d in */; do if ! cd "$d"; then false && continue; fi; rg x .; done'):
            with self.subTest(command=command):
                self.assertIsNotNone(run("Bash", {"command": command}, cwd=HOME)[0])

    @unittest.skipIf(os.name == "nt", "cd の行き先は Windows では cygpath で Windows の形に直る(coldread と同じ読み方)")
    def test_then_after_a_condition_cd_runs_only_where_the_cd_moved(self):
        # 条件の最後の cd が移れたときにだけ走る then・do の cd は、cd が落ちた場所には当てない(前は落ちた場所にも then の cd .. を
        # 当て、~/src で打つとホームに届いたと読んで止めていた)
        for command in ("if cd sub; then make; cd ..; fi; rg bar .", "if [ -d sub ] && cd sub; then make; cd ..; fi; rg bar .",
                        "if cd sub; then make; cd ..; else echo no; fi; rg bar .",
                        "if x; then :; elif cd sub; then cd ..; fi; rg bar .",
                        "while cd sub; do cd ..; break; done; rg bar .",
                        "for d in a b; do if cd $d; then make; cd ..; fi; done; rg bar ."):
            with self.subTest(command=command):
                self.assertIsNone(run("Bash", {"command": command}, cwd=HOME + "/src")[0])
        # 条件が cd を走らせずに通る(||)・裏返す(!)・cd の後ろに条件が続く・then の後ろの cd・cd が落ちた場所そのものは、今までどおり
        for command, cwd in (("if foo || cd sub; then cd ..; fi; rg bar .", HOME + "/src"),
                             ("if ! cd sub; then cd ..; fi; rg bar .", HOME + "/src"),
                             ("if cd sub; [ -f y ]; then cd ..; fi; rg bar .", HOME + "/src"),
                             ("if cd sub; then make; fi; cd ..; rg bar .", HOME + "/src"),
                             ("if cd /tmp; then :; fi; rg foo .", HOME),
                             ("if cd sub; then make; cd ..; fi; rg bar .", HOME)):
            with self.subTest(command=command):
                self.assertIsNotNone(run("Bash", {"command": command}, cwd=cwd)[0])
        # 条件の中の cd を持つ if を並べても、時間切れ(時間切れは通す)にならない
        many = "".join("if cd d%d; then make; cd ..; fi\n" % i for i in range(60))
        started = time.monotonic()
        self.assertIsNone(run("Bash", {"command": many + "rg y ."}, cwd=HOME + "/src/repo")[0])
        self.assertLess(time.monotonic() - started, 10)

    @unittest.skipIf(os.name == "nt", "cd の行き先は Windows では cygpath で Windows の形に直る(coldread と同じ読み方)")
    def test_cds_of_one_then_section_or_and_chain_run_together(self):
        # then・else の区画と && の繋がりの中の cd は、組に入らなければどれも走らない。入らなかった場所に組の後ろの cd .. を
        # 当てない(前は当てて、繰り返しの回ごとに 1 つずつ上がり、/ やホームに届いたと読んで止めていた)
        for command, cwd in (('for d in */; do [ -d "$d/.git" ] && cd "$d" && git pull && cd ..; done; rg x .', WORK + "/a/b"),
                             ("for d in a b; do if [ -d build ]; then cd build; make; cd ..; fi; done; rg x .", WORK + "/a/b"),
                             ('for d in */; do if [ -f "$d/Makefile" ]; then cd "$d" && make && cd ..; fi; done; rg TODO .',
                              WORK + "/a/b"),
                             ("for d in a b; do rg -l x .; if [ -d build ]; then cd build; make; cd ..; fi; done", WORK),
                             ("if [ -d build ]; then cd build; make; cd ..; fi; if [ -d docs ]; then cd docs; make; cd ..; fi; "
                              "rg x .", WORK),
                             ("if [ -d b ]; then cd /; cd /tmp; fi; rg x .", HOME + "/src"),
                             ("for a in x y; do cd a1; for b in p q; do cd b1; for c in 1 2; do if cd c1; then make; cd ..; fi; "
                              "done; cd ..; done; cd ..; done; rg x src", WORK),
                             ("for i in 1 2; do if true; then cd ..; if [ -f .zshrc ]; then exit; fi; cd src; fi; done; rg foo .",
                              HOME + "/src")):
            with self.subTest(command=command):
                self.assertIsNone(run("Bash", {"command": command}, cwd=cwd)[0])
        # 組に入ったときに上がる cd・組の中で cd が落ちても走る後ろの cd(; の後ろ・|| の後ろ)・&& の途中で止まった場所は、今までどおり
        for command in ("if [ -d x ]; then cd ..; fi; rg x .", "for d in a b; do if [ -d build ]; then cd ..; fi; done; rg x .",
                        'for d in */; do [ -d "$d" ] && cd "$d" && make; cd ..; done; rg x .',
                        "if [ -d build ]; then cd build || true; cd ..; fi; rg x .",
                        "if [ -d b ]; then make && cd build; cd ..; fi; rg x .",
                        "[ -d x ] && cd / && false && cd /tmp; rg x .", "if [ -d b ]; then cd /; make; fi; rg x .",
                        "for d in a b; do if [ -d build ]; then cd build; make; cd ../..; fi; done; rg x .",
                        # 区画の中で cd の前の break・continue・return(入れ子の中も)で抜けた場所は、区画の後ろの cd を通らずに来る
                        "for i in 1 2; do if true; then cd ..; if [ -f .zshrc ]; then break; fi; cd src; fi; done; rg foo .",
                        "for i in 1 2; do if cd ..; then if [ -f .zshrc ]; then break; fi; cd src; fi; done; rg foo .",
                        "for i in 1 2; do if true; then cd ..; case $i in 1) break;; esac; cd src; fi; done; rg foo .",
                        "f() { if true; then cd ..; if [ -f .zshrc ]; then return; fi; cd src; fi; }; f; rg foo .",
                        "for i in 1 2; do if true; then cd ..; break; cd src; fi; done; rg foo .",
                        "for i in 1 2; do if true; then cd ..; [ -f .zshrc ] && continue; cd src; fi; done; rg foo ."):
            with self.subTest(command=command):
                self.assertIsNotNone(run("Bash", {"command": command}, cwd=HOME + "/src")[0])

    @unittest.skipIf(os.name == "nt", "cd の行き先は Windows では cygpath で Windows の形に直る(coldread と同じ読み方)")
    def test_cd_in_a_group_after_and_or_runs_only_with_the_group(self):
        # `{ }` のまとまりの中の cd は、頭の前の && || でまとまりごと走らないことがある(前は頭でない cd を必ず走ると読み、
        # ホームで打つと ~/proj で探すと読んで通していた)
        for command in ("[ -d proj ] && { echo found; cd proj; }; rg foo .",
                        "[ -d proj ] || { git clone url proj; cd proj; }; rg foo .",
                        "[ -d proj ] && { echo; cd proj || exit 1; }; rg foo .", "x && { y; cd ..; }; rg foo ."):
            with self.subTest(command=command):
                self.assertIsNotNone(run("Bash", {"command": command}, cwd=HOME)[0])
        # まとまりに入った場所だけが来る所(まとまりの中・後ろの && の繋がり)と、まとまりの前が && || でない形は通す
        for command in ("[ -d proj ] && { echo found; cd proj; rg foo .; }", "[ -d proj ] && { cd proj; rg foo .; }",
                        "[ -d proj ] && { echo; cd proj; } && rg foo .", "{ echo; cd proj; }; rg foo ."):
            with self.subTest(command=command):
                self.assertIsNone(run("Bash", {"command": command}, cwd=HOME)[0])
        # まとまりは全部が走るか走らないかで、入らなかった場所にまとまりの後ろの cd .. を当てない(前は当てて、~/src で打つと
        # ホームに届いたと読んで止めていた)
        for command, cwd in (("[ -d build ] && { cd build; make; cd ..; }; rg x .", WORK + "/a/b"),
                             ("[ -d build ] && { cd build; make; cd ..; }; rg x .", HOME + "/src"),
                             ("for d in a b; do [ -d build ] && { cd build; make; cd ..; }; done; rg x .", HOME + "/src"),
                             ('for d in */; do [ -d "$d" ] && { cd "$d"; git pull; cd ..; }; done; rg x .', HOME + "/src"),
                             ("[ -d x ] && { cd ..; cd src; }; rg foo .", HOME + "/src")):
            with self.subTest(command=command, cwd=cwd):
                self.assertIsNone(run("Bash", {"command": command}, cwd=cwd)[0])
        # まとまりに入ったときに上がる cd・まとまりの中で cd の前の break で抜けた場所・まとまりの後ろの || は、今までどおり
        for command, cwd in (("[ -d x ] && { cd ..; cd ..; }; rg foo .", HOME + "/src/a"),
                             ("for d in a b; do [ -d build ] && { cd build; make; cd ../..; }; done; rg x .", HOME + "/src"),
                             ("for i in 1 2; do [ -d x ] && { cd ..; if [ -f .zshrc ]; then break; fi; cd src; }; done; rg foo .",
                              HOME + "/src"),
                             ("[ -d x ] && { cd ..; cd src; } || true; rg foo .", HOME + "/src")):
            with self.subTest(command=command, cwd=cwd):
                self.assertIsNotNone(run("Bash", {"command": command}, cwd=cwd)[0])
        # まとまりの中の if・case・サブシェルの中の cd は、まとまりが走っても走るとは限らない(前はまとまりの組に入れて必ず走ると
        # 読み、~/src で打つと通していた)
        for command, cwd in (("[ -d .git ] && { cd ..; if [ -d repo ]; then cd repo; fi; }; rg foo .", HOME + "/src"),
                             ("true && { cd ..; if [ -d build ]; then cd build; fi; }; rg foo .", HOME + "/src"),
                             ("true && { if [ -d sub ]; then cd sub; fi; cd ..; }; rg foo .", HOME + "/src"),
                             ("true && { cd ..; case $1 in a) cd sub;; esac; }; rg foo .", HOME + "/src"),
                             ("true && { cd ..; ( cd sub ); }; rg foo .", HOME + "/src"),
                             ("for i in 1 2; do true && { cd ..; if [ -d x ]; then cd x; fi; }; done; rg foo .", WORK)):
            with self.subTest(command=command, cwd=cwd):
                self.assertIsNotNone(run("Bash", {"command": command}, cwd=cwd)[0])
        # まとまりの頭が if・case でも、まとまりのじかの cd は今までどおりまとまりの組に入れる
        for command in ("[ -d b ] && { if x; then :; fi; cd build; make; cd ..; }; rg x .",
                        "[ -d b ] && { case $x in a) :;; esac; cd build; make; cd ..; }; rg x ."):
            with self.subTest(command=command):
                self.assertIsNone(run("Bash", {"command": command}, cwd=HOME + "/src")[0])

    @unittest.skipIf(os.name == "nt", "cd の行き先は Windows では cygpath で Windows の形に直る(coldread と同じ読み方)")
    def test_cd_or_a_group_that_exits_and_and_chained_cd_in_a_condition(self):
        # `|| { …; exit 1; }` のまとまりも、最後が exit なら cd が落ちたときに後ろを走らせない。条件の中で && で繋いだ cd は、
        # 条件が通ったときに走る then で移れた(前はどちらも止めていた)
        for command in ("cd proj || { echo no; exit 1; }; rg foo .", "cd proj || { echo no >&2; exit 1; }\nrg foo .",
                        "if [ -d proj ] && cd proj; then rg foo .; fi",
                        'for d in */; do cd "$d" || { echo skip; continue; }; rg x .; cd ..; done',
                        "while [ -d proj ] && cd proj; do rg foo .; break; done"):
            with self.subTest(command=command):
                self.assertIsNone(run("Bash", {"command": command}, cwd=HOME)[0])
        # 抜けないまとまり・サブシェル・&& の後ろや入れ子の exit・まとまりの中の探すコマンド・& で後ろに回した cd と、条件の値が
        # cd で決まらない・条件が落ちたときに走る所・ブロックの後ろは、cd が移れたと限らない
        for command in ("cd proj || { echo no; }; rg foo .", "cd proj || ( echo no; exit 1 ); rg foo .",
                        "cd proj || { exit 1 & }; rg foo .", "cd proj || { echo no && exit 1; }; rg foo .",
                        "cd proj || { rg foo .; exit 1; }", "cd proj || { if x; then exit 1; fi; }; rg foo .",
                        "cd proj || exit 1 & rg foo .", "if [ -d proj ] && cd proj; true; then rg foo .; fi",
                        "if [ -d proj ] && cd proj; then :; fi; rg foo .", "if [ -d proj ] && cd proj || true; then rg foo .; fi",
                        "if [ -d proj ] && ! cd proj; then :; else rg foo .; fi",
                        "if [ -d proj ] && cd proj; then :; else rg foo .; fi"):
            with self.subTest(command=command):
                self.assertIsNotNone(run("Bash", {"command": command}, cwd=HOME)[0])

    @unittest.skipIf(os.name == "nt", "cd の行き先は Windows では cygpath で Windows の形に直る(coldread と同じ読み方)")
    def test_cd_inside_an_escape_does_not_move_the_later_commands(self):
        # 逃げ口(`|| { …; exit 1; }`)の中の cd は、cd が落ちたときに走って抜けるので、後ろのコマンドの場所を変えない(前は中の
        # cd .. を移れた側にも当て、ホームに届いたと読んで止めていた)
        for command in ("cd sub || { cd ..; exit 1; }; cd ../..; rg foo .", "cd sub || { cd /; exit 1; }; rg foo ."):
            with self.subTest(command=command):
                self.assertIsNone(run("Bash", {"command": command}, cwd=HOME + "/src/a")[0])
        # 抜けないまとまり・サブシェルの exit・|| の後ろのただの cd・逃げ口の中で探すコマンド・繰り返しの後ろは、今までどおり
        for command in ("cd sub || { cd ..; }; cd ../..; rg foo .", "cd sub || { cd ..; ( exit 1 ); }; cd ../..; rg foo .",
                        "cd sub || cd ..; cd ../..; rg foo .", "cd sub || { cd /; rg foo .; exit 1; }",
                        'for d in */; do cd "$d" || { cd ..; continue; }; done; rg x .',
                        # return で終わる逃げ口の中の cd は後ろに届く(関数の中では呼んだ所に戻り、関数の外では return が落ちる)
                        "f() { cd sub || { cd /; return 1; }; }; f; rg foo .", "cd sub || { cd /; return 1; }; rg foo .",
                        "cd sub || { cd ..; return 1; }; cd ../..; rg foo ."):
            with self.subTest(command=command):
                self.assertIsNotNone(run("Bash", {"command": command}, cwd=HOME + "/src/a")[0])

    @unittest.skipIf(os.name == "nt", "cd の行き先は Windows では cygpath で Windows の形に直る(coldread と同じ読み方)")
    def test_cd_in_a_condition_is_sure_only_where_the_condition_held(self):
        # 条件の中の cd は、else・繰り返しの後ろ・until の do では落ちて移っていないことがある
        for command in ("if cd sub; then echo ok; else find . -name x; fi", "while cd sub; do break; done; find . -name x",
                        "until cd sub; do find . -name x; done", "if cd sub; then :; fi; find . -name x"):
            with self.subTest(command=command):
                self.assertIsNotNone(run("Bash", {"command": command}, cwd=HOME)[0])
        # 条件が通ったときに走る then・elif の then・while の do の中では、今までどおり移った後の場所で見る
        for command in ("if cd sub; then find . -name x; fi", "while cd sub; do find . -name x; break; done",
                        "if false; then :; elif cd sub; then find . -name x; fi",
                        "cd sub && if cd x; then :; else find . -name y; fi"):
            with self.subTest(command=command):
                self.assertIsNone(run("Bash", {"command": command}, cwd=HOME)[0])

    @unittest.skipIf(os.name == "nt", "cd の行き先は Windows では cygpath で Windows の形に直る(coldread と同じ読み方)")
    def test_cd_is_sure_where_only_a_moved_cd_reaches(self):
        # `!` で裏返した条件の cd は else で移れた。cd が落ちた区画が exit で終わる if と、cd が移れるまで回る until・while ! の
        # 後ろでも移れた(前は then・do の中でだけ移れたと見て止めていた)
        for command in ("if ! cd proj; then exit 1; fi; rg foo .", "if cd proj; then :; else exit 1; fi; rg foo .",
                        "until cd proj; do sleep 1; done; rg foo .", "while ! cd proj; do sleep 1; done; rg foo .",
                        "if ! cd proj; then echo no; else rg foo .; fi",
                        "if ! cd proj\nthen\n  echo no >&2\n  exit 1\nfi\nrg foo ."):
            with self.subTest(command=command):
                self.assertIsNone(run("Bash", {"command": command}, cwd=HOME)[0])
        # 裏返した cd の then は cd が落ちた所(前は移れた所と見て通していた)。落ちた区画が抜けない・抜けるのがサブシェルや
        # && の後ろ・ブロックが走るとは限らない・条件の値が cd で決まらない・break で抜けうる繰り返しは、後ろで移れたと限らない
        for command in ("if ! cd proj; then find . -name x; fi", "if ! cd proj; then echo no; fi; rg foo .",
                        "if cd proj; then exit 1; fi; rg foo .", "until cd proj; do break; done; rg foo .",
                        "while cd proj; do sleep 1; done; rg foo .", "until ! cd proj; do sleep 1; done; rg foo .",
                        "if ! cd proj; then (exit 1); fi; rg foo .", "if ! cd proj; then false && exit 1; fi; rg foo .",
                        "x && if ! cd proj; then exit 1; fi; rg foo .", "if ! cd proj; then exit 1; fi | cat; rg foo .",
                        "if ! cd proj; true; then exit 1; fi; rg foo .", "if cd proj; true; then rg foo .; fi",
                        "if ! { cd proj; true; }; then exit 1; fi; rg foo .",
                        "if a; then :; elif ! cd proj; then exit 1; fi; rg foo .",
                        "if cd proj; then :; elif x; then :; else exit 1; fi; rg foo ."):
            with self.subTest(command=command):
                self.assertIsNotNone(run("Bash", {"command": command}, cwd=HOME)[0])

    @unittest.skipIf(os.name == "nt", "cd の行き先は Windows では cygpath で Windows の形に直る(coldread と同じ読み方)")
    def test_cd_in_a_piped_or_backgrounded_group_does_not_reach_later_commands(self):
        # パイプの中か & で後ろに回した `{ }` のまとまりは別のシェルで走るので、中の cd は閉じの } の後ろに届かない(前は届くと見て、
        # ホームの `{ cd proj; } | cat; rg x .` を ~/proj で探すと読んで通し、~/src/repo の `{ cd ..; cd ..; } | tee log; rg x .` を止めていた)
        for command in ("{ cd proj; } | cat; rg x .", "{ cd proj; } & rg x .", "echo | { cd proj; }; rg x .",
                        "{ { cd proj; }; } | cat; rg x .", "{ cd /; rg x .; } | cat", "{ cd /; } && rg x ."):
            with self.subTest(command=command):
                self.assertIsNotNone(run("Bash", {"command": command}, cwd=HOME)[0])
        for command, cwd in (("{ cd ..; cd ..; } | tee log; rg x .", WORK), ("{ cd proj; rg x .; } | cat", HOME),
                             ("{ cd proj; }; rg x .", HOME)):
            with self.subTest(command=command):
                self.assertIsNone(run("Bash", {"command": command}, cwd=cwd)[0])

    @unittest.skipIf(os.name == "nt", "cd の行き先は Windows では cygpath で Windows の形に直る(coldread と同じ読み方)")
    def test_reserved_words_after_time_and_function_name_start_a_command(self):
        # `time`(予約語。旗は -p と --)の後ろの `{`・`!`・if などと、`function 名前` の後ろの `{` はコマンドの頭(前はどれも
        # `time`・`function` の引数と読み、中の探すコマンドと cd を見落として通していた)。`function f { … }` は `f() { … }` と同じに読む
        for command, cwd in (("function f { rg foo /; }; f", WORK), ("function f { cd /; }; f; rg foo .", WORK),
                             ("time { rg foo /; }", WORK), ("time { cd /; }; rg foo .", WORK), ("time ! rg foo /", WORK),
                             ("time -p { cd /; }; rg foo .", WORK), ("time -- { rg foo /; }", WORK), ("time -p -- ! rg foo /", WORK),
                             ("! time { rg foo /; }", WORK), ("time function f { rg foo /; }", WORK),
                             ("time for d in a; do cd /; done; rg foo .", WORK),
                             ("[ -d src ] && time { cd src; }; rg foo .", HOME), ("f() { cd /; }; f; rg foo .", WORK)):
            with self.subTest(command=command, cwd=cwd):
                self.assertIsNotNone(run("Bash", {"command": command}, cwd=cwd)[0])
        for command, cwd in (("time { cd src; }; rg foo .", HOME), ("function f { cd src; }; f; rg foo .", HOME),
                             ("echo time { rg foo /; }", WORK), ("echo function f { rg foo /; }", WORK),
                             ("function f ( cd / ); f; rg foo .", WORK)):
            with self.subTest(command=command, cwd=cwd):
                self.assertIsNone(run("Bash", {"command": command}, cwd=cwd)[0])

    @unittest.skipIf(os.name == "nt", "cd の行き先は Windows では cygpath で Windows の形に直る(coldread と同じ読み方)")
    def test_substitution_runs_in_the_cwd_of_its_command(self):
        # $( ) の中は、それを持つコマンドの場所(前の cd)と変数で走る
        self.assertIsNotNone(run("Bash", {"command": 'cd / && echo "$(find . -name x)"'})[0])
        self.assertIsNotNone(run("Bash", {"command": 'D=/; echo "$(find $D -name x)"'})[0])
        self.assertIsNotNone(run("Bash", {"command": "cd ~ && for f in $(find . -name '*.json'); do echo; done"})[0])
        self.assertIsNone(run("Bash", {"command": 'cd /tmp && echo "$(find . -name foo)"'}, cwd=HOME)[0])

    def test_wrappers_after_hops_are_skipped(self):
        # nice・sudo の後ろの timeout・env も前置きとして飛ばす
        self.assertIsNotNone(run("Bash", {"command": "nice -n 19 timeout 300 find / -name x"})[0])
        self.assertIsNotNone(run("Bash", {"command": "sudo env X=1 find / -name x"})[0])

    def test_bare_substitution_after_a_wrapper_is_skipped(self):
        # env・sudo の後ろの引用の外の置換だけの語(`env $(cat .env | xargs)`)は代入と同じに越え、後ろのコマンドを見る
        # (前は置換を語に留めた後、その語をコマンド名と読み、後ろの find・rg を見ずに通していた。頼み cae1e2)
        for command in ("env $(cat .env | xargs) find / -name x", "sudo env $(cat .env) rg foo /",
                        'env $(cat .env) sh -c "cd / && find ."'):
            self.assertIsNotNone(run("Bash", {"command": command})[0], command)
        self.assertIsNone(run("Bash", {"command": "env $(cat .env | xargs) find . -name x"})[0])
        # 前置の無い頭の展開だけの語(`$(true)`・`$SUDO`・`` `true` ``)も越える。展開は空にも前置にもなりうるので、後ろの語を
        # コマンドと見て読む(前はその語をコマンド名と読んで通していた)
        for command in ("$(true) find / -name x", "$(: ) rg foo /", "$SUDO find / -name x", "${X} rg foo ~",
                        "`true` rg foo /", "$(true) env X=1 rg foo /"):
            self.assertIsNotNone(run("Bash", {"command": command})[0], command)
        for command in ("$(true) find . -name x", "$(cd /) rg foo .", "$SUDO rg foo src"):
            self.assertIsNone(run("Bash", {"command": command})[0], command)
        # 頭の展開だけの語の後ろの cd も行き先を見る(前は cd を見ず、`$(true) cd /; rg foo .` を作業場の中の . と読んで通していた)
        for command in ("$(true) cd /; rg foo .", "$X cd ~ && rg foo .", "`true` cd /; find . -name x"):
            self.assertIsNotNone(run("Bash", {"command": command})[0], command)
        for command in ("$(true) cd src; rg foo .", "echo cd /; rg foo ."):
            self.assertIsNone(run("Bash", {"command": command})[0], command)

    def test_assignments_only_command_reads_earlier_assignments(self):
        # 代入だけのコマンド(`D=/ x=$(rg foo $D)`)は左から順に代入するので、後ろの語の $( ) は前の語の代入を見て起点を解く
        # (前は前の語の値を知らず、起点の $D を解けずに通していた。頼み cae1e2)
        for command in ("D=/ x=$(rg foo $D)", "d=~ out=$(grep -rl foo $d)", 'D=/ x="$(find $D -name y)"',
                        "D=/ x=$(echo $(rg foo $D))", "D=/ x=$(rg foo $D) >/dev/null",
                        "D=/ bash -c 'find $D -name x' > log"):
            self.assertIsNotNone(run("Bash", {"command": command})[0], command)
        for command in ("D=src x=$(rg foo $D)", "x=$(rg foo $D) D=/", "D=/; D=src x=$(rg foo $D)", "D=/ rg foo $D",
                        "D=src bash -c 'find $D -name x' > log"):
            self.assertIsNone(run("Bash", {"command": command})[0], command)
        # コマンドの前に並べた代入の語も同じ(前は代入だけのコマンドでしか前の語を見ず、`D=/ x=$(rg foo $D) true` を通していた)。
        # env の後ろの語は代入より先に展開するので、前の D=/ を見ない(前は `D=/ env x=$(rg foo $D)` を代入だけと読んで止めていた)
        for command in ("D=/ x=$(rg foo $D) true", "D=/ x=$(rg foo $D) y=1 make", 'D=/ x="$(rg foo $D)" true'):
            self.assertIsNotNone(run("Bash", {"command": command})[0], command)
        for command in ("D=src x=$(rg foo $D) true", "D=/ env x=$(rg foo $D)", "x=$(rg foo $D) D=/ true"):
            self.assertIsNone(run("Bash", {"command": command})[0], command)

    def test_backticks_inside_a_bare_substitution_are_read(self):
        # 引用の外の $( … ) の中の ` … ` も読む(中に ` が在るとトークン化が単純コマンドに割り、割った語は ` の中身を持たない。
        # 前は外の読み直しが $( … ) ごと飛ばし、`x=$(echo `rg foo /`)` を通していた。頼み cae1e2)
        for command in ("x=$(echo `rg foo /`)", "x=$(cd / && n=`find . -name x`)", "x=$(echo $(echo `rg foo /`))",
                        "cat <(echo `find / -name x`)"):
            self.assertIsNotNone(run("Bash", {"command": command})[0], command)
        for command in ("x=$(echo `rg foo src`)", "x=$(cd ~/p && n=`find . -name x`)"):
            self.assertIsNone(run("Bash", {"command": command}, cwd=HOME)[0], command)

    def test_quoted_close_parens_do_not_end_a_substitution(self):
        # 置換の中の引用の中の ) では置換を閉じない(前は引用を見ずに数え、' の中の ) で閉じたと読んで、後ろの ` … ` と rg を
        # 単一引用の中と見て通していた)
        for command in ("x=$(echo ')' `rg foo /`)", "x=$(printf '%s)' `rg foo /`)", "echo \"$(printf '%s)\\n' x; rg foo /)\"",
                        'x=$(echo ")" `rg foo /`)', 'x=$(echo "(" `rg foo /`)'):
            self.assertIsNotNone(run("Bash", {"command": command})[0], command)
        for command in ("x=$(echo ')' `rg foo src`)", "echo \"$(printf '%s)\\n' x; rg foo src)\""):
            self.assertIsNone(run("Bash", {"command": command})[0], command)

    def test_quoted_open_parens_do_not_keep_a_substitution_open(self):
        # 置換の中の引用の中や \ の後の ( では置換を開いたままにしない(前は引用を見ない数え方の閉じない遠い所まで中身と読み、
        # 後ろの ` … ` を外のコマンドとして見ずに通していた。頼み cae1e2)
        for command, cwd in (("x=$(sed 's/(.*//' f); n=`rg foo /`", WORK), ("x=$(grep -c '(' f); n=`find / -name x`", WORK),
                             ("echo \"$(echo '(')\"; echo `rg foo /`", WORK), ("x=$(echo \\(); n=`rg foo /`", WORK),
                             ("x=$(echo '(' ); cd /; y=`rg foo .`", WORK),
                             ("cd ~ && x=$(git log --format='%s (%h' -1); n=`rg -l TODO .`", HOME)):
            self.assertIsNotNone(run("Bash", {"command": command}, cwd=cwd)[0], command)
        for command in ("x=$(sed 's/(.*//' f); n=`rg foo src`", "x=$(echo \\(); n=`rg foo src`"):
            self.assertIsNone(run("Bash", {"command": command})[0], command)
        # 引用を見る閉じが case の型・${ } の中の ) で手前に来ても、数え方の中身も読む(頼み cae1e2)
        for command in ('x="$(echo "(" ; case a in a) :;; esac; rg foo /)"', "echo \"$(echo '(' ; case $x in a) :;; esac; find / -name x)\"",
                        'echo "$(echo "(" ${x:-)} ; rg foo /)"'):
            self.assertIsNotNone(run("Bash", {"command": command}, cwd=WORK)[0], command)
        # 数え方が閉じないときは、終わりまでを中身として読まない。後ろの引用の中の字をコマンドと読まず、引用した ( を持つ置換を
        # 600 並べた語も時間切れの前に読み終える(頼み cae1e2)
        for command in ("echo \"$(echo '(')\"; git commit -m \"note; find / -name x\"", "n=$(printf '(('); git commit -m \"fix; rg foo /\"",
                        'x="$(echo "(" ; true)" rg foo src', "x=\"$(grep -c '(' f)\"; echo \"hint; rg foo /\"",
                        "x=\"$(echo \"(\")\"; echo '\"; rg foo /'"):
            self.assertIsNone(run("Bash", {"command": command}, cwd=WORK)[0], command)
        started = time.monotonic()
        self.assertIsNotNone(run("Bash", {"command": 'echo "' + "$(echo '(')" * 600 + '"; rg foo /'}, cwd=WORK)[0])
        self.assertLess(time.monotonic() - started, 10)
        # 数え方が閉じなくても、引用を見る閉じの後ろの、外の読みが引用の中と見て飛ばす字は読む(commit 87964f05 で読むのを
        # やめたとき、引用した ( を 2 つ持ち case の型か ${y%)} で手前に閉じる置換の、後ろの rg を落としていた。頼み cae1e2)
        for command in ('x="$(echo "((" ; case a in a) :;; esac; rg foo /)"', "x=\"$(grep -c '((' f; case $a in y) :;; esac; rg foo /)\"",
                        'x="$(echo "(("; echo ${y%)}; rg foo /)"', "x=\"$(sed 's/(//;s/(//' f; echo ${y%)}; find / -name x)\"",
                        # 手前の閉じの後ろに " や ` … ` が在っても読む(次の " の手前まで読む形では落としていた)
                        'x="$(echo "(("; case a in a) :;; esac; echo "hi"; rg foo /)"', 'x="$(echo "(("; case a in a) :;; esac; echo `date`; rg foo /)"',
                        'x="$(echo "(("; echo ${y%)}; echo "z"; find / -name x)"',
                        # 外の閉じの " の後ろに字が続いても読む(終わりの 1 字を落とすだけでは、中の rg を引用の中と読んでいた)
                        'x="$(echo "((" ; case a in a) :;; esac; echo "hi"; rg foo /)"; echo ok',
                        'echo "$(echo "((" ; case a in a) :;; esac; echo "hi"; rg foo /)" && echo ok',
                        # 中に " を持つ二重引用の中の置換の後ろのコマンドも、語の切れ目を bash に合わせて見る(前は ( をコマンドの名前と読み、
                        # 後ろの find・rg を引数と見て通していた)
                        'x="$(echo "(" ; true)" find / -name x', 'x="$(echo ")" ; true)" rg foo /', 'x="$(echo "(" ; true)" xargs rg foo /'):
            self.assertIsNotNone(run("Bash", {"command": command}, cwd=WORK)[0], command)
        # 閉じない $( を 9000 並べた 99KB の語も、$( ごとに終わりまで数え直さず、時間切れの前に読み終える(頼み cae1e2)
        started = time.monotonic()
        self.assertIsNotNone(run("Bash", {"command": 'echo "' + "$(echo '(')" * 9000 + '"; rg foo /'}, cwd=WORK)[0])
        self.assertIsNone(run("Bash", {"command": 'echo "' + "$(echo '(')" * 9000 + '"; rg foo src'}, cwd=WORK)[0])
        self.assertLess(time.monotonic() - started, 10)

    def test_parallel_runs_the_command_after_it(self):
        # GNU parallel の後ろのコマンドも見る。値を取る旗(-j 4・-S host)の値は飛ばし、::: の後ろの値はコマンドに足して走る
        # (前は parallel を前置と見ず、`parallel rg {} / ::: foo bar` を通していた)
        for command in ("parallel rg {} / ::: foo bar", "parallel -j 4 rg foo ::: / ~", "parallel find / -name {} ::: a b",
                        "parallel find {} -name x ::: / ~", "parallel --jobs 4 grep -rn x / ::: a", "ls | parallel -j4 rg x /",
                        "parallel -S host1 find / -name x"):
            with self.subTest(command=command):
                self.assertIsNotNone(run("Bash", {"command": command})[0])
        # 探さないコマンド・作業場の中の値・標準入力やファイルから値を読む形は通す
        for command in ("parallel gzip ::: *.log", "parallel -j 8 gzip ::: *.log", "parallel rg -l {} ::: TODO FIXME",
                        "parallel -j4 find {} -name '*.py' ::: src tests", "ls *.txt | parallel grep -r foo",
                        "parallel rg foo :::: list.txt"):
            with self.subTest(command=command):
                self.assertIsNone(run("Bash", {"command": command}, cwd=HOME)[0])

    def test_long_and_bundled_flags_of_xargs_and_parallel_take_their_values(self):
        # xargs の長い形の旗(--arg-file・--delimiter など)と parallel の値を取る旗(--block-size など)と、束ねた 1 字の旗
        # (-0n 2・-kS host)の値を飛ばす(前は値をコマンドと読み、後ろの rg を見落とした)
        for command in ("xargs --arg-file list rg foo /", "xargs --delimiter , rg foo /", "xargs --max-args 2 rg foo /",
                        "xargs --max-procs 4 find / -name x", "xargs --process-slot-var S rg foo /",
                        "xargs -0n 2 rg foo /", "parallel --block-size 1M rg foo ::: /", "parallel --pipe --block 1M rg foo /",
                        "parallel -kS host rg foo ::: /", "parallel --max-lines rg foo ::: /",
                        "parallel --max-lines 3 rg foo ::: /"):
            with self.subTest(command=command):
                self.assertIsNotNone(run("Bash", {"command": command})[0])
        # 作業場の中を探す形と、値を = で付けた形・数だけを取る旗(-l 3)は通す
        for command in ("xargs --max-args=2 rg foo", "xargs --arg-file list rg foo src", "xargs -0n 2 rg foo src",
                        "parallel --block-size 1M rg foo ::: src", "parallel -l 3 rg foo ::: src", "sudo -Eu root rg foo src",
                        "nice -n19 rg foo src", "xargs -r0 rg foo"):
            with self.subTest(command=command):
                self.assertIsNone(run("Bash", {"command": command}, cwd=HOME + "/src/repo")[0])

    def test_parallel_runs_a_one_word_command_through_the_shell(self):
        # 1 語の文字列で渡したコマンド・シェルに渡すコマンド・コマンドの無い parallel は、::: の値を {} に入れるか後ろに足した
        # 文字列をシェルが走らせる(前は 1 語のコマンドを名前と読み、どれも通していた)
        for command in ('parallel "rg foo {}" ::: /', "parallel 'find {} -name x' ::: /",
                        "parallel bash -c 'find {} -name x' ::: /", 'parallel ::: "find / -name x"',
                        "parallel -j4 'rg foo {}' ::: src /", 'parallel "rg foo" ::: /', "parallel ::: find ::: /"):
            with self.subTest(command=command):
                self.assertIsNotNone(run("Bash", {"command": command})[0])
        # 探さないコマンド・作業場の中の値・標準入力やファイルから読む値(決まらない)は通す
        for command in ("parallel gzip ::: *.log", 'parallel -j4 "gzip {}" ::: *.log', "ls | parallel rg foo {}",
                        'parallel "rg foo {}" ::: src lib', 'ls | parallel "rg foo {}"', 'parallel "rg foo {}" :::: list.txt',
                        "parallel bash -c 'echo {}' ::: a b", 'parallel ::: "echo a" "echo b"'):
            with self.subTest(command=command):
                self.assertIsNone(run("Bash", {"command": command}, cwd=HOME + "/src/repo")[0])

    def test_wrappers_written_as_full_paths_are_skipped(self):
        for command in ("/usr/bin/time find / -name x", "/usr/bin/env find / -name x", "/usr/bin/timeout 60 find / -name x"):
            with self.subTest(command=command):
                self.assertIsNotNone(run("Bash", {"command": command})[0])

    def test_find_paths_after_the_expression_are_read(self):
        # Claude Code の find は bfs で走り、式の後ろに書いたパスも起点にする
        for command in ("find -name x /", "find . -name x /", "find -maxdepth 3 ~", "find . -type f -name '*.json' /Users"):
            with self.subTest(command=command):
                self.assertIsNotNone(run("Bash", {"command": command})[0])
        # 値を取る式の値(-path の値・-newer のファイル)と -exec の中は起点でない
        for command in ('find . -path "/Users/me/*" -name x', "find src -name '*.py' -newer Makefile",
                        "find . -name x -exec grep -l y {} \\;"):
            with self.subTest(command=command):
                self.assertIsNone(run("Bash", {"command": command})[0])

    def test_find_exec_after_a_closing_semicolon_and_a_parenthesis_is_read(self):
        # -exec の閉じの \; と式の括弧が並んでも、後ろの -exec を繋いで読む。-exec は `{} +` の + か ; でだけ閉じる(前は
        # 区切りの組で見て割れた後ろを読まず、+ の語でも閉じたと見て、どれも通していた)
        for command in ("find . \\( -name a -exec true \\; \\) -exec rg x / \\;",
                        "find . -exec true \\; \\( -exec rg x / \\; \\)", "find . -exec echo + \\; -exec rg x / \\;"):
            with self.subTest(command=command):
                self.assertIsNotNone(run("Bash", {"command": command})[0])
        # 括弧か -exec が開いたまま区切りが来て繋ぎ切れず、後ろに探すツールの語が在れば止める(読み切れない)
        self.assertIsNotNone(run("Bash", {"command": "find . -exec true && rg x src"})[0])
        # 閉じた -exec・式の括弧の後ろの区切りと、作業場の中の探すコマンドは通す
        for command in ("find . -exec rg x {} + ; rg y src", "find . -exec true \\; \\( -name a \\) -exec rg x {} \\;",
                        "find . -exec echo + \\; -print", "find . -exec echo {} \\; && rg x src",
                        "find . -exec true && echo done"):
            with self.subTest(command=command):
                self.assertIsNone(run("Bash", {"command": command})[0])

    def test_find_exec_closes_only_at_a_plus_after_braces(self):
        # -exec の後ろのコマンドの引数の + は閉じでない(前は + で閉じたと見て、後ろの / を find の式の語と読んで通していた)
        for command in ("find . -exec rg + -newer / \\;", "find . -exec echo + \\; -name x /", "find . -exec rg x {} + /"):
            with self.subTest(command=command):
                self.assertIsNotNone(run("Bash", {"command": command})[0])
        # {} の直後の + と ; で閉じた -exec と、引数に + を持つ作業場の中のコマンドは通す
        for command in ("find . -name '*.py' -exec rg -l x {} +", "find . -exec rg -l x {} + -name y",
                        "find src -exec grep -l + {} +", "find . -exec echo + \\; -print"):
            with self.subTest(command=command):
                self.assertIsNone(run("Bash", {"command": command}, cwd=HOME + "/src/repo")[0])

    def test_quoted_closing_parenthesis_is_not_a_subshell_close(self):
        # 囲むサブシェルの無い所の閉じ括弧(`')'`・`\)`。トークン化で引用符が落ちる)は字と見る(前はサブシェルの閉じと見て、
        # find の後ろを繋がず、cd が後ろに届かないと読んで通していた)
        for command in ("find fd -name ')' -exec rg x / \\;", "find fd -exec echo \\) \\; -exec rg x / \\;",
                        "cd /; echo ')'; rg x .", "cd / && echo ')' && rg x .",
                        "echo ')'; find fd -name ')' -exec rg x / \\;", "(find . -name x) && rg y /"):
            with self.subTest(command=command):
                self.assertIsNotNone(run("Bash", {"command": command}, cwd=HOME + "/src/repo")[0])
        # 本物のサブシェルの閉じと、括弧の字を探す作業場の中のコマンドは通す
        for command in ("find . -name ')' -print", "find fd -exec echo \\) \\; -print", "(find . -name x); rg y src",
                        "(cd /; echo ')'); rg x .", "(cd /tmp); rg x .", "echo ')'; rg x src"):
            with self.subTest(command=command):
                self.assertIsNone(run("Bash", {"command": command}, cwd=HOME + "/src/repo")[0])

    @unittest.skipIf(os.name == "nt", "cd の行き先は Windows では cygpath で Windows の形に直る(coldread と同じ読み方)")
    def test_process_substitution_after_a_redirect_is_a_subshell(self):
        # リダイレクトの行き先のプロセス置換(`< <(…)`・`> >(…)`)は別のプロセスで、中の cd は後ろに届かない(前は `<(` ごと
        # 読み飛ばして中の語を外のコマンドに繋ぎ、`(` を数えず、中の cd が後ろに届くと読んでホームの `rg foo .` を通していた)
        for command, cwd in (("mapfile -t a < <(cd src && ls); rg foo .", HOME), ("cat < <(cd src; ls); rg foo .", HOME),
                             ("echo hi > >(cd src; cat); rg foo .", HOME), ("cd /; exec > >(tee log) 2>&1; rg x .", WORK),
                             ("cat < <(rg foo /)", WORK)):
            with self.subTest(command=command):
                self.assertIsNotNone(run("Bash", {"command": command}, cwd=cwd)[0])
        for command in ("cat < <(cd /; ls); rg foo src", 'while read f; do rg foo "$f"; done < <(ls)', "cat < <(rg foo .)"):
            with self.subTest(command=command):
                self.assertIsNone(run("Bash", {"command": command}, cwd=WORK)[0])

    def test_words_after_an_unquoted_substitution_belong_to_the_same_command(self):
        # 引用の外の `$( )`・`<( )` の閉じの後ろの語も同じコマンドの語(前は ( を区切りと読み、閉じの ) の後ろを別のコマンドに割って、
        # 作業場の中の `rg $(cat pat.txt) /` の起点 / を見なかった)。置換の中の探すコマンドと cd は今までどおり読む
        for command in ("rg $(cat pat.txt) /", 'grep -r "$(cat p)" /', "rg foo < <(echo) /", "grep -r $((1+1)) /",
                        "echo $(cd /; rg foo .)", "x=$(echo $(rg foo /))"):
            with self.subTest(command=command):
                self.assertIsNotNone(run("Bash", {"command": command}, cwd=WORK)[0])
        for command in ("cd $(git rev-parse --show-toplevel) && rg x .", "rg $(cat pat.txt) src", "rg foo < <(echo) src"):
            with self.subTest(command=command):
                self.assertIsNone(run("Bash", {"command": command}, cwd=WORK)[0])

    def test_nested_substitutions_after_maybe_cds_stop_before_the_timeout(self):
        # $( ) の中身は外のコマンドの走りうる cwd ごとに読み直すので、走るとは限らない cd の後の入れ子の $( ) は掛け算で増える
        # (前は 7 段で 2 分かかり、時間切れは通す)。cd の無いコマンドを並べた長い 1 本も、cd をたどる数が増える(前は 2 万本で
        # 40 秒)。どちらも時間切れの前に、読み切れないとして止める
        nest = "rg foo src"
        for _ in range(7):
            nest = "[ -d a ] && cd a; [ -d b ] && cd b; [ -d c ] && cd c; echo $(%s)" % nest
        for command in (nest, ":; " * 20000 + "rg foo src"):
            with self.subTest(command=command[:40]):
                started = time.monotonic()
                self.assertIn("読み切れない", run("Bash", {"command": command})[0] or "")
                self.assertLess(time.monotonic() - started, 15)
        # 浅い入れ子と、cd の無いコマンドを数千本並べた 1 本は今までどおり読み切る
        shallow = "rg foo src"
        for _ in range(3):
            shallow = "[ -d a ] && cd a; [ -d b ] && cd b; [ -d c ] && cd c; echo $(%s)" % shallow
        for command in (shallow, ":; " * 3000 + "rg foo src"):
            with self.subTest(command=command[:40]):
                self.assertIsNone(run("Bash", {"command": command})[0])
        self.assertIsNotNone(run("Bash", {"command": shallow.replace("src", "/")})[0])

    def test_many_unclosed_substitutions_are_read_before_the_timeout(self):
        # 閉じない $( が多く並んでも、閉じる所を $( ごとに初めから読み直さない(前は字の数の 2 乗の時間がかかり、10 万字の
        # ヒアドキュメントで 60 秒・二重引用で 40 秒を超え、フックの時間切れで後ろの rg foo / を通していた。頼み cae1e2)
        for command in ("cat <<EOF >/dev/null\n" + "$($\\)" * 20000 + "\nEOF\nrg foo /",
                        'echo "' + "$(\\)" * 25000 + '"; rg foo /'):
            with self.subTest(command=command[:40]):
                started = time.monotonic()
                self.assertIsNotNone(run("Bash", {"command": command})[0])
                self.assertLess(time.monotonic() - started, 10)

    def test_long_scripts_with_cds_and_assignments_are_read_to_the_end(self):
        # cd と置換の多い数百行の手書きの台本は読み切って通す。前は、代入だけのコマンドの語の置換を 2 度読み直し、cd ごとの
        # 場所の動きも cd の後ろのコマンドごとに引き直していたので、600 行の台本と、`a=$(pwd) b=$(rg -c x .)` の並ぶ 100 行を
        # 読み切れないとして止めていた
        rand = random.Random(1)
        subs = ["src", "tests", "docs", "pkg/a", "pkg/b", "tools", "web/app"]
        lines = ['#!/bin/bash', 'set -euo pipefail', 'ROOT="$(git rev-parse --show-toplevel)"', 'cd "$ROOT"']
        while len(lines) < 600:
            r, s = rand.random(), rand.choice(subs)
            if r < 0.15:
                lines += ['cd "$ROOT/%s"' % s, 'rg -n "TODO" . | head -5 || true', 'cd "$ROOT"']
            elif r < 0.25:
                lines += ['if [ -d %s ]; then' % s, '  cd %s' % s, '  find . -name "*.py" -newer Makefile | wc -l',
                          '  cd - >/dev/null', 'fi']
            elif r < 0.35:
                lines += ['for f in $(find %s -name "*.sh"); do' % s, '  echo "checking $f"',
                          '  shellcheck "$f" || echo "fail $f"', 'done']
            elif r < 0.45:
                lines += ['count=$(grep -rc "import" %s | wc -l)' % s, 'echo "count=$count"']
            elif r < 0.55:
                lines += ['pushd %s >/dev/null' % s, 'fd -e md . | xargs wc -l', 'popd >/dev/null']
            elif r < 0.65:
                lines += ['while read -r line; do', '  echo "$line" | cut -d: -f1', 'done < <(rg -l "fixme" %s)' % s]
            elif r < 0.72:
                lines += ['(cd %s && make -s test) || echo "make failed"' % s]
            elif r < 0.8:
                lines += ['ver=$(python3 -c "import sys; print(sys.version)")', 'echo "$ver $(date +%s) $(basename "$PWD")"']
            elif r < 0.88:
                lines += ['case "$1" in', '  build) make;;', '  test) "$ROOT/scripts/test.sh" %s;;' % s, '  *) echo usage;;',
                          'esac']
            else:
                lines += ['f%d() {' % len(lines), '  local d="$1"', '  grep -rn "def " "$d" | head', '}', 'f%d %s' % (len(lines), s)]
        script = "\n".join(lines + ['rg -n "main" src'])
        multi = "\n".join(["cd ~/src/repo"] + ["cd pkg/a%d && a=$(pwd) b=$(rg -c x .) c=$(git log -1) && cd ../.." % i
                                               for i in range(100)])
        for command in (script, multi):
            with self.subTest(command=command[-60:]):
                started = time.monotonic()
                self.assertIsNone(run("Bash", {"command": command})[0])
                self.assertLess(time.monotonic() - started, 10)
        # 読み切った上で、末尾の / からの探しと、代入の語の置換の中の / からの探しは今までどおり止める
        self.assertIsNotNone(run("Bash", {"command": script + "\nrg foo /"})[0])
        self.assertIsNotNone(run("Bash", {"command": multi + "\na=$(pwd) b=$(rg -c x /)"})[0])

    def test_contents_past_the_deepest_level_are_not_passed_unread(self):
        # 読む段の終わり(8 段)より深い二重引用の中の $( )・bash -c に探すツールの語が在れば、読み切れないとして止める(前は黙って
        # 通していた)。探すツールの語の無い深い入れ子は今までどおり通す
        def wrap(inner, levels):
            for _ in range(levels):
                inner = "echo $(%s)" % inner
            return inner
        for command in (wrap('echo "$(rg foo /)"', 8), wrap("bash -c 'rg foo /'", 8), wrap('echo "$(find / -name x)"', 11)):
            with self.subTest(command=command):
                self.assertIsNotNone(run("Bash", {"command": command})[0])
        self.assertIsNone(run("Bash", {"command": wrap('echo "$(echo hi)"', 10) + "; rg foo src"})[0])

    def test_heredocs_inside_a_substitution_are_read(self):
        # $( )・<( ) の中のヒアドキュメントの本文も読む(中のシェルが走らせる本文と、区切りを引用しない本文の $( ))。前は中身を
        # 読み直すときに本文を持たず、`x=$(bash <<'EOF'` の本文の rg foo / を通していた。区切りを引用した本文の字は今までどおり通す
        for command in ("x=$(bash <<'EOF'\nrg foo /\nEOF\n)", "x=$(sh -s <<EOF\nfind / -name x\nEOF\n)",
                        "for f in $(cat <<EOF\n$(find / -name '*.log')\nEOF\n); do echo $f; done",
                        "diff <(cat <<EOF\n$(rg foo /)\nEOF\n) b", "x=$(bash <<'EOF'\ncd /\nrg foo .\nEOF\n)",
                        "x=\"$(bash <<'EOF'\nrg foo /\nEOF\n)\"", "echo \"$(cat <<EOF\n$(rg foo /)\nEOF\n)\"",
                        "x=`bash <<'EOF'\nrg foo /\nEOF\n`"):
            with self.subTest(command=command):
                self.assertIsNotNone(run("Bash", {"command": command})[0])
        for command in ("x=$(cat <<'EOF'\nrg foo /\nEOF\n)", "x=$(bash <<'EOF'\nrg foo src\nEOF\n)"):
            with self.subTest(command=command):
                self.assertIsNone(run("Bash", {"command": command})[0])

    def test_fd_exec_command_is_read(self):
        # fd の -x・-X・--exec・--exec-batch の後ろのコマンドも探すコマンドとして読む(前は読まず、`fd foo -x rg y / {}` を通していた)
        for command in ("fd foo -x rg y / {}", "fd -e py -X rg -l foo /", "fd -Hx rg y /", "fd --exec=rg y /",
                        "fd --exec-batch rg -l foo ~", "fd -e x foo -x find / -name {}", 'fd -e x foo -x sh -c "rg y /"',
                        "fd foo / -x echo"):
            with self.subTest(command=command):
                self.assertIsNotNone(run("Bash", {"command": command})[0])
        # fd が見つけた物({})や作業場の中を探すコマンド、旗の値の x、; の後ろの fd の起点は通す
        for command in ("fd foo -x rg y {}", "fd -e py -X rg -l foo", "fd -e x foo", "fd -tf -x wc -l",
                        "fd foo -x echo {} \\; src"):
            with self.subTest(command=command):
                self.assertIsNone(run("Bash", {"command": command})[0])
        # 置き換えの印の無いコマンドには fd が {} を足すので、ホームで打っても見つけた物だけを探す(前は止めていた)。fd そのものが
        # / やホームを探す形と、印の外で / やホームを渡す形・中の殻が cwd を探す形は今までどおり止める
        for command in ("fd -e py . ~/src/repo -x rg -l TODO", "fd . src -X rg TODO", "fd . src -x grep -rl foo",
                        "fd . src -x rg TODO {//}"):
            with self.subTest(command=command):
                self.assertIsNone(run("Bash", {"command": command}, cwd=HOME)[0])
        for command in ("fd . / -x rg TODO", "fd . -x rg TODO", "fd . src -x rg TODO ~ {}", "fd . src -x sh -c 'rg TODO'"):
            with self.subTest(command=command):
                self.assertIsNotNone(run("Bash", {"command": command}, cwd=HOME)[0])

    def test_grep_with_a_number_flag_is_recursive(self):
        # Claude Code の grep は ugrep で走り、-NUM と --depth は下をたどる深さ
        self.assertIsNotNone(run("Bash", {"command": "git log | grep -5 needle"}, cwd=HOME)[0])
        for command in ("grep -9 needle ~", "grep --depth=5 needle /", "grep -5r needle /", "rgrep needle /"):
            with self.subTest(command=command):
                self.assertIsNotNone(run("Bash", {"command": command})[0])
        self.assertIsNone(run("Bash", {"command": "grep -5 needle file.txt"})[0])
        self.assertIsNone(run("Bash", {"command": "grep -A5 needle file.txt"})[0])

    def test_scripts_given_to_a_shell_are_read(self):
        # stdin に渡すスクリプト・bash -c と eval の中の外の変数・名前付きのホーム
        for command in ("bash <<'EOF'\nfind / -name x\nEOF", "sh -s <<EOF\nfind / -name x\nEOF",
                        'D=/; bash -c "find $D -name x"', 'D=/; eval "find $D -name x"', "D=/; eval 'find $D -name x'",
                        "export D=/; bash -c 'find $D -name x'", "D=/ bash -c 'find $D -name x'",
                        "D=/ bash <<'EOF'\nfind $D -name x\nEOF",
                        "D=/ timeout 60 bash -c 'find $D -name x'", "env D=/ sh -c 'find \"$D\" -name x'",
                        "echo \"it's\"; D=/; bash -c 'find $D -name x'", "printf 'cd /\\nfind . -name x\\n' | sh",
                        "find ~tester -name x"):
            with self.subTest(command=command):
                self.assertIsNotNone(run("Bash", {"command": command})[0])
        # bash script.sh は stdin をデータとして読ませる
        self.assertIsNone(run("Bash", {"command": "bash script.sh <<EOF\nfind / -name x\nEOF"})[0])
        self.assertIsNone(run("Bash", {"command": 'D=src; eval "find $D -name x"'})[0])

    def test_substitutions_in_unquoted_heredoc_bodies_are_read(self):
        # 区切りを引用しないヒアドキュメントの本文の $( ) と ` ` は、シェルに渡さないコマンドの本文でも走る(' は本文の中では字)
        for command in ("cat <<EOF > out.txt\n$(find / -name x)\nEOF", "cat <<EOF > out.txt\n`find ~ -name x`\nEOF",
                        'python3 - <<EOF\nprint("""$(rg -l foo /)""")\nEOF', "cat <<EOF\nIt's $(find / -name x)\nEOF",
                        "D=/; cat <<EOF\n$(find $D -name x)\nEOF"):
            with self.subTest(command=command):
                self.assertIsNotNone(run("Bash", {"command": command})[0])
        # 区切りを引用した本文と、\ で引用した $ は展開しない
        for command in ("cat <<'EOF'\n$(find / -name x)\nEOF", "cat <<\\EOF\n$(find / -name x)\nEOF",
                        "cat <<EOF\n\\$(find / -name x)\nEOF", "cat <<EOF\n$(find . -name x)\nEOF"):
            with self.subTest(command=command):
                self.assertIsNone(run("Bash", {"command": command})[0])

    @unittest.skipIf(os.name == "nt", "cd の行き先は Windows では cygpath で Windows の形に直る(coldread と同じ読み方)")
    def test_backticks_run_in_the_cwd_of_their_command(self):
        for command in ("cd / && for f in `find . -name '*.json'`; do :; done", "cd / && a=`find . -name x`"):
            with self.subTest(command=command):
                self.assertIsNotNone(run("Bash", {"command": command})[0])
        # 語に割れないバッククォートは、` を持つコマンドの場所で見て、後ろの cd の行き先では見ない
        self.assertIsNone(run("Bash", {"command": "cd /tmp && n=`find . -name '*.py' | wc -l` && cd ~ && echo $n"})[0])

    def test_recursive_grep_after_a_pipe_searches_cwd(self):
        # grep -r は起点が無ければ、前がパイプでも cwd を探す(stdin を読まない)。rg は stdin を読む
        self.assertIsNotNone(run("Bash", {"command": "ls | grep -r needle"}, cwd=HOME)[0])
        self.assertIsNone(run("Bash", {"command": "ls | rg needle"}, cwd=HOME)[0])
        self.assertIsNone(run("Bash", {"command": "cd /tmp && find . -name x"})[0])
        self.assertIsNotNone(run("Bash", {"command": "cd ~; find . -name x"})[0])
        self.assertIsNotNone(run("Bash", {"command": "cd /\nrg needle"})[0])
        self.assertIsNotNone(run("Bash", {"command": "cd && find . -name x"})[0])
        # xargs の後ろの grep -r は、xargs が渡すパスを探す(cwd ではない)
        self.assertIsNone(run("Bash", {"command": "ls *.txt | xargs grep -r foo"}, cwd=HOME)[0])

    def test_drive_start_is_not_joined_to_cwd(self):
        # ドライブの形の起点(D:\)は絶対で、cwd に繋がない(繋ぐと /home/tester/src/repo/D: になって通っていた)
        self.assertIsNotNone(run("Bash", {"command": "find 'D:\\' -name x"})[0])

    @unittest.skipUnless(os.name == "nt", "C:\\… の cwd は Windows の Claude Code だけが渡す(ほかの OS では絶対のパスでないので cd の読み方が捨てる)")
    def test_relative_start_in_windows_cwd(self):
        self.assertIsNone(run("Bash", {"command": "find src -name x"}, cwd="C:\\Users\\tester\\repo")[0])
        self.assertIsNotNone(run("Bash", {"command": "find .. -name x"}, cwd="C:\\Users\\tester")[0])

    def test_relative_start_in_wide_cwd(self):
        self.assertIsNotNone(run("Bash", {"command": "find . -name x"}, cwd=HOME)[0])
        self.assertIsNotNone(run("Bash", {"command": "rg needle"}, cwd="/")[0])


class Tools(unittest.TestCase):
    def test_glob(self):
        stop = [{"pattern": "**/research.json", "path": "/"},
                {"pattern": "/Users/**/x.ts"},
                {"pattern": "**/x.ts", "path": "~"},
                {"pattern": "/home/tester/**/x"},
                {"pattern": "C:/**/x"},
                {"pattern": "**/x", "path": "C:\\Users"},
                {"pattern": "**/x", "path": "D:\\"}]
        for args in stop:
            with self.subTest(args=args):
                self.assertIsNotNone(run("Glob", args)[0])
        self.assertIsNotNone(run("Glob", {"pattern": "**/x"}, cwd=HOME)[0])
        passes = [{"pattern": "**/*.py"},
                  {"pattern": "**/x", "path": "/home/tester/.cache/works-factory"},
                  {"pattern": "/home/tester/.cache/**/x"},
                  {"pattern": "src/a.py"},
                  {"pattern": "~/.zshrc"},
                  {"pattern": "/opt/homebrew"},
                  {"pattern": "C:/Users/tester/src/**/x"},
                  {"pattern": "**/x", "path": "C:\\Users\\tester\\src"}]
        for args in passes:
            with self.subTest(args=args):
                self.assertIsNone(run("Glob", args)[0])

    def test_grep(self):
        self.assertIsNotNone(run("Grep", {"pattern": "x", "path": "/"})[0])
        self.assertIsNotNone(run("Grep", {"pattern": "x", "path": "$HOME"})[0])
        self.assertIsNone(run("Grep", {"pattern": "x", "path": "/home/tester/src"})[0])
        self.assertIsNone(run("Grep", {"pattern": "/"})[0])

    def test_other_tools_pass(self):
        self.assertIsNone(run("Read", {"file_path": "/"})[0])


class FailClosed(unittest.TestCase):
    def test_unreadable_input_is_stopped(self):
        reason, _ = run(None, None, raw="not json")
        self.assertIn("検査自体に失敗した", reason)

    def test_unnormalizable_command_is_stopped(self):
        # coldread の正規化が読めない形(`$[ ]`)と見たコマンドは、どこで何を探すかを決められないので止める。字面の find だけを
        # 拾うと rg・cd の後の find を通す(前は None に正規表現を掛けて落ちていた)
        for command in ("echo $[1+1]; find / -name a", ": $[0]; rg foo /", "echo $[1+1]; cd / && find . -name x"):
            with self.subTest(command=command):
                self.assertIn("読めない形", run("Bash", {"command": command})[0] or "")

    def test_search_words_only_in_quoted_heredoc_bodies_pass(self):
        # 読めない形でも、探すツールの語が区切りを引用したヒアドキュメントの本文(展開も実行もしない字)の中にしか無ければ通す
        # (前は `git commit -m "$(cat <<'EOF'` の本文の字で止めていた)
        for command in ("git commit -m \"$(cat <<'EOF'\nfix: grep -r handling. Don't\nEOF)\"",
                        "git commit -m \"$(cat <<'EOF'\nfix: find handles (x)\nEOF)\"",
                        "git commit -m \"$(cat <<\\EOF\nfind x\nEOF\n)\""):
            with self.subTest(command=command):
                self.assertIsNone(run("Bash", {"command": command})[0])
        # 本文の外の語・区切りを引用しない本文(中の $( ) が走る)・注釈の中の << と、bash 3.2 が本文の中で置換を閉じる形は止める。
        # `cat <<'EOF' | \` の次の行の rg は、bash が行をつないだ後のコマンドで本文の外なので、止めたままにする
        for command in ("git commit -m \"$(cat <<'EOF'\nDon't\nEOF)\" && rg foo /",
                        ": $[0]; cat <<EOF\n$(find / -name x)\nEOF", ": $[0] # <<'X'\nrg foo /\nX",
                        "x=$(cat <<'EOF'\na) rg foo /\nEOF)", "cat <<'EOF' | \\\n  rg foo /\nfind\nEOF",
                        "echo $[1]; find / -name x"):
            with self.subTest(command=command):
                self.assertIsNotNone(run("Bash", {"command": command}, cwd=HOME)[0])

    def test_quoted_bodies_given_to_a_shell_are_not_skipped(self):
        # 読めない形のコマンドでも、シェルが走らせる本文(bash・ssh … bash・bash -s・bash -c "$(cat <<'EOF'"・行を \ でつないだ
        # シェル・パイプの先のシェル)は除かずに見る(前は区切りを引用した本文をどれも除いて、本文の find / を通していた)
        for command in ("x=$[1+1]; bash <<'EOF'\nfind / -name x\nEOF", "x=$[1+1]; ssh host bash <<'EOF'\nfind / -name x\nEOF",
                        "x=$[1+1]; bash -s <<'EOF'\nfind / -name x\nEOF", "x=$[1+1]; /bin/sh \\\n  <<'EOF'\nfind / -name x\nEOF",
                        "x=$[1+1]; bash -c \"$(cat <<'EOF'\nfind / -name x\nEOF\n)\"",
                        "x=$[1+1]; cat <<'EOF' | bash\nfind / -name x\nEOF"):
            with self.subTest(command=command):
                self.assertIn("読めない形", run("Bash", {"command": command})[0] or "")
        # シェルに渡さない本文は今までどおり除く
        for command in ("x=$[1+1]; cat <<'EOF' > notes.md\nfind / -name x\nEOF", "x=$[1+1]; cat \\\n  <<'EOF'\nfind / -name x\nEOF"):
            with self.subTest(command=command):
                self.assertIsNone(run("Bash", {"command": command})[0])

    def test_stop_is_logged(self):
        with tempfile.TemporaryDirectory() as cfg:
            env = dict(os.environ, HOME=HOME, CLAUDE_CONFIG_DIR=cfg)
            data = json.dumps({"tool_name": "Bash", "tool_input": {"command": "find / -name x"}, "cwd": WORK})
            subprocess.run([sys.executable, str(HOOK)], input=data.encode("utf-8"), capture_output=True, env=env)
            log = pathlib.Path(cfg, "searchgate", "denies.log").read_text(encoding="utf-8")
            self.assertIn("deny find /", log)


if __name__ == "__main__":
    unittest.main(verbosity=1)
