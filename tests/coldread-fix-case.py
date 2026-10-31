#!/usr/bin/env python3
"""coldread-gate.py の正しさの穴 13 件(頼み cae1e2 のレビューで再現した物)の回帰。tests/coldread-table-case.py から呼ぶ。

1 件ずつ、前の版では赤になり直した版では緑になる形で書く。穴の番号は頼みの番号のまま。読む本体は引数(無ければ
gates/hooks/coldread-gate.py)で、前の版の写しを渡すと全部の穴が赤になることを確かめられる。14・15 は 1〜13 の直し
(commit 8eb61ffd)が持ち込んだ止めすぎで、8eb61ffd の版を渡すと赤になる。16・17 は 14・15 の直し(commit 0bd1e0a2)の
後に見つけた素通しで、0bd1e0a2 の版を渡すと赤になる。21〜33 は 2 度目のレビュー(頼み cae1e2)の F1〜F13 で、
番号から 20 を引くとレビューの番号になる(29 はレビューの F9 で、探しのゲートの側の直しなので tests/searchgate-suite.py に置く)。
34 は 21〜28 を直す間に見つけた素通しで、commit 69816318 の版を渡すと赤になる。35 以降は 3 度目のレビュー(頼み cae1e2)の
直しで、commit 812accd7 の版を渡すと赤になる。
49 以降はその後のレビュー(頼み cae1e2)の直しで、commit ef2d1702 の版を渡すと赤になる。53 以降は 15 回目のレビュー(頼み cae1e2)
の直しで、commit 12d08013 の版を渡すと赤になる。58 は 55 の直し(commit b46a0bfe)が持ち込んだ止めすぎで、b46a0bfe の版を
渡すと赤になる。59 以降は 17 回目のレビュー(頼み cae1e2)の直しで、commit 7e850025 の版を渡すと赤になる。61 は探しのゲートの
11 回目のレビュー(頼み cae1e2)の直しで、commit fce0c115 の版を渡すと赤になる。62 以降は投稿の前のゲートの
レビュー(頼み cae1e2)の直しで、commit a192c351 の版を渡すと赤になる。
全部が通れば FIX_OK を出し、1 件でも落ちれば落ちた番号を出して 1 で終わる。
"""
import contextlib
import importlib.util
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
GATE = sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "gates", "hooks", "coldread-gate.py")
WORK = tempfile.mkdtemp(prefix="coldread-fix-")
os.environ["CLAUDE_CONFIG_DIR"] = os.path.join(WORK, "cfg")
os.environ.pop("COLDREAD_IN_READER", None)
spec = importlib.util.spec_from_file_location("coldread_gate_fix", GATE)
g = importlib.util.module_from_spec(spec)
spec.loader.exec_module(g)

BODY = "これは検査の対象の本文です。読み手に渡る字を確かめます。" * 10
FAILED = []


def check(n, ok, why):
    if not ok:
        FAILED.append("%s: %s" % (n, why))


def guarded(n, fn):
    """1 件の確かめ。例外も赤として数える(前の版で例外になる穴もある)。"""
    try:
        fn()
    except Exception as exc:
        FAILED.append("%s: 例外 %s: %s" % (n, type(exc).__name__, str(exc)[:200]))


class Reached(Exception):
    """main が読み手への依頼文を組む所まで来た印(読み手は起動しない)。"""


@contextlib.contextmanager
def patched(**names):
    old = {k: getattr(g, k) for k in names}
    for k, v in names.items():
        setattr(g, k, v)
    try:
        yield
    finally:
        for k, v in old.items():
            setattr(g, k, v)


def run_main(command, cwd=None):
    """フックの main を 1 回回す。(読み手に渡した画面, 標準出力)。読み手の手前で止める。"""
    seen = {}

    def reader_prompt(screen, noun):
        seen["screen"] = screen
        raise Reached()
    payload = {"tool_name": "Bash", "tool_input": {"command": command}, "session_id": os.urandom(8).hex()}
    if cwd:
        payload["cwd"] = cwd
    out = io.StringIO()
    old_in, old_out = sys.stdin, sys.stdout
    sys.stdin, sys.stdout = io.StringIO(json.dumps(payload)), out
    try:
        with patched(reader_prompt=reader_prompt):
            g.main()
    except (Reached, SystemExit):   # 読み手を呼ぶ所まで来たか、ゲートが答えを出して抜けた
        pass
    finally:
        sys.stdin, sys.stdout = old_in, old_out
    return seen.get("screen"), out.getvalue()


def fake_screen(log, item_body="OLD_BODY_MARK"):
    """gh の代わりに画面の材料を返す Screen。作られた時の cwd を log に残す。item_body が None なら取れない。"""
    class FakeScreen:
        def __init__(self, cwd):
            log.append(cwd)
            self.cwd, self.refs_got, self.deadline = cwd, 0, 0

        def json(self, argv):
            if item_body is None:
                raise RuntimeError("取れない")
            if argv[:2] in (["issue", "view"], ["pr", "view"]):
                return {"number": 5, "title": "TITLE_MARK", "body": item_body, "comments": [],
                        "url": "https://github.com/o/r/issues/5", "state": "OPEN"}
            return {"title": "TITLE_MARK", "body": item_body, "state": "open"}

        def pages(self, path):
            return []

        def cut_lines(self):
            return []
    return FakeScreen


# 1. ヒアドキュメントの盾は引用の外の << だけに掛ける
def f1():
    cands, blk, _ = g.posting_bodies("gh pr comment 1 --body $'Run this:\\ncat <<EOF\\nUNSEEN\\nEOF\\nThen.'", WORK)
    check(1, any("UNSEEN" in c and "__HEREDOC" not in c for c in cands), "$'…' の中の <<EOF を盾にした: %r %r" % (cands, blk))
    cands, blk, _ = g.posting_bodies('gh pr comment 1 --body "Run:\npython3 - <<\'PY\'\nprint(1)\nPY\ndone"', WORK)
    check(1, any("print(1)" in c and "__HEREDOC" not in c for c in cands), "\"…\" の中の <<'PY' を盾にした: %r %r" % (cands, blk))


# 2. graphql の query を読めなければ止める
def f2():
    for cmd in ('gh api graphql -f query="$Q"', 'gh api graphql -f query="$(cat q.graphql)"',
                "gh api graphql -F query=@/no/such.graphql"):
        _, blk, _ = g.posting_bodies(cmd, WORK)
        check(2, bool(blk), "読めない query を通した: %s" % cmd)


M = 'mutation($b: String!) { addComment(input:{subjectId: "x", body: $b}) { x } }'


# 3. mutation の本文の変数も本文の旗と同じ決まりで読む
def f3():
    for cmd in ("gh api graphql -f query='%s' -f b=\"$(cat f)\"" % M, "gh api graphql -f query='%s' -f b=\"$B\"" % M,
                "gh api graphql -f query='%s' -F b=@-" % M):
        cands, blk, _ = g.posting_bodies(cmd, WORK)
        check(3, bool(blk), "読めない本文の変数を字のまま渡した: %s → %r" % (cmd, cands))
    cands, blk, _ = g.posting_bodies("gh api graphql -f query='%s' -F b=@- <<'EOF'\nthe body\nEOF\n" % M, WORK)
    check(3, any("the body" in c for c in cands) and not blk, "-F b=@- のヒアドキュメントを読まない: %r %r" % (cands, blk))


# 4. $'…' は開いて読む。開いた中の置換は止める。ふつうの $'…\n…' は今までどおり通す
def f4():
    _, blk, _ = g.posting_bodies("gh pr comment 1 --body $'\\''\"$(cat x)\"\\'", WORK)
    check(4, bool(blk), "$'…' を閉じた後の \"$(cat x)\" を通した")
    cands, blk, _ = g.posting_bodies("gh pr comment 1 --body $'line1\\nline2'", WORK)
    check(4, cands == ["line1\nline2"] and not blk, "ふつうの $'…' を開かない・止めた: %r %r" % (cands, blk))


# 5. 単引用の中の $ は、その名前の変数だけを読めない物にする
def f5():
    cmd = "D=/; find \"$D\" -name 'x$'"
    norm, bodies = g.prepare(cmd)
    tokens = g.tokenize(norm)
    cmds = g.split_commands(tokens)
    files = g.BodyFiles(cmds, WORK, bodies, norm, tokens)
    files.at(len(cmds) - 1, [])
    check(5, files.var("$D") == "/", "単引用の $ 1 つで $D まで読まなくなった: %r" % files.var("$D"))
    proc = subprocess.run([sys.executable, os.path.join(ROOT, "gates", "hooks", "search-gate.py")],
                          input=json.dumps({"tool_name": "Bash", "tool_input": {"command": cmd}, "cwd": WORK}),
                          capture_output=True, text=True, timeout=60,
                          env=dict(os.environ, CLAUDE_CONFIG_DIR=os.path.join(WORK, "cfg")))
    if GATE == os.path.join(ROOT, "gates", "hooks", "coldread-gate.py"):   # searchgate は隣の本体を読むので、本体を差し替えた回は見ない
        check(5, '"deny"' in proc.stdout, "searchgate が find \"$D\"(D=/)を通した: %r" % proc.stdout[:200])


# 6. 画面は gh が走る場所(前の cd)で引き、場所が読めなければ引かない
def f6():
    a, b = os.path.join(WORK, "a"), os.path.join(WORK, "b")
    os.makedirs(a, exist_ok=True)
    os.makedirs(b, exist_ok=True)
    for cmd, want in (("cd %s && gh issue comment 1 --body '%s'" % (b, BODY), [b]),
                      ("cd \"$X\" && gh issue comment 1 --body '%s'" % BODY, []),
                      ("gh issue comment 1 --body '%s'" % BODY, [a])):
        log = []
        with patched(Screen=fake_screen(log, None)):
            run_main(cmd, a)
        check(6, log == want, "画面を引いた場所 %r(欲しいのは %r): %s" % (log, want, cmd[:40]))


# 7. 本文を置き換える投稿では、古い本文を画面に置かない
def f7():
    for cmd, old_shown in (("gh issue edit 5 -b '%s'" % BODY, False),
                           ("gh pr edit 5 --body '%s'" % BODY, False),
                           ("gh api -X PATCH repos/o/r/issues/5 -f body='%s'" % BODY, False),
                           ("gh issue comment 5 --body '%s'" % BODY, True)):
        log = []
        with patched(Screen=fake_screen(log)):
            screen, out = run_main(cmd, WORK)
        ok = screen is not None and "TITLE_MARK" in screen and ("OLD_BODY_MARK" in screen) == old_shown
        check(7, ok, "画面の古い本文(置くのは %s): %r %r %s" % (old_shown, screen, out[:200], cmd[:40]))


# 8. Claude Code のモデルの別名は読み替えでない
def f8():
    for v in ("haiku", "opus", "Sonnet", "fable", "opusplan", "default", "best", "inherit", "opus[1m]", "SONNET[1M]"):
        check(8, not g.model_redirected({"CLAUDE_CODE_SUBAGENT_MODEL": v}), "別名 %s を読み替えと見た" % v)
    for v in ("gpt-6.1-sol", "glm", "haikus", "opus-x"):
        check(8, g.model_redirected({"ANTHROPIC_MODEL": v}), "%s を読み替えと見なかった" % v)


# 9. 複合コマンドを閉じる語のリダイレクトは写しに分けない(git の差で拾わせる)
def f9():
    for cmd, name in (("{ echo '# x'; echo y; } > notes.md", "notes.md"),
                      ("for i in 1; do echo a; done > x.md", "x.md"),
                      ("if true; then echo a; fi > y.md", "y.md"),
                      ("case a in a) echo a;; esac > z.md", "z.md")):
        _, copied, _ = g._written_by_command(cmd, WORK)
        check(9, not any(p.endswith(name) for p in copied), "閉じる語のリダイレクトを写しに分けた: %s" % cmd)
    _, copied, _ = g._written_by_command("git log > log.md", WORK)
    check(9, any(p.endswith("log.md") for p in copied), "ふつうのコマンドの出力の写しを拾わなくなった")


# 10. 長さの上限は前処理より前に見て、前処理は 1 回だけ回す
def f10():
    calls = []
    real = g.prepare

    def counting(command):
        calls.append(len(command))
        if len(command) > g.MAX_LEN:
            raise AssertionError("上限を超えたコマンドを前処理した")
        return real(command)
    with patched(prepare=counting, MAX_LEN=300, Screen=fake_screen([], None)):
        _, out = run_main("gh issue comment 1 --body '%s'" % ("x" * 400))
        check(10, '"deny"' in out and "長すぎて" in out and not calls, "上限より前に前処理した: %r %r" % (calls, out[:150]))
    calls.clear()
    with patched(prepare=counting, Screen=fake_screen([], None)):
        run_main("gh issue comment 1 --body '%s'" % BODY)
    check(10, len(calls) == 1, "前処理を %d 回回した" % len(calls))


def git(root, *args):
    return subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@example.com", "-c", "commit.gpgsign=false", *args],
                          cwd=root, capture_output=True, text=True, check=True).stdout.strip()


# 11. HEAD が在るのに記録の頭を読めなかった控えを、最初の commit と取り違えない
def f11():
    root = os.path.join(WORK, "repo")
    os.makedirs(root, exist_ok=True)
    git(root, "init", "-q")
    for k in range(3):
        with open(os.path.join(root, "d%d.md" % k), "w", encoding="utf-8") as f:
            f.write("x")
        git(root, "add", ".")
        git(root, "commit", "-q", "-m", "c%d" % k)
    head = git(root, "rev-parse", "HEAD")
    steps, other = g._head_moves({"root": os.path.realpath(root), "reflog": None, "head": head})
    check(11, steps == [] and not other, "古い commit を書いた物として拾った: %d 件 %r" % (len(steps), other))
    fresh = os.path.join(WORK, "fresh")
    os.makedirs(fresh, exist_ok=True)
    git(fresh, "init", "-q")
    with open(os.path.join(fresh, "a.md"), "w", encoding="utf-8") as f:
        f.write("x")
    git(fresh, "add", ".")
    git(fresh, "commit", "-q", "-m", "first")
    steps, _ = g._head_moves({"root": os.path.realpath(fresh), "reflog": None, "head": None})
    check(11, len(steps) == 1, "最初の commit を拾わなくなった: %r" % steps)


def branch_run(fail_rel):
    """branch_check を、読み手の代わりの _branch_verdict で回す。(覚えた中身のハッシュ, _branch_verdict に渡った鍵)。"""
    docs = []
    for rel in ("a.md", "b.md"):
        full = os.path.join(WORK, rel)
        with open(full, "w", encoding="utf-8") as f:
            f.write("# %s\n\n%s\n" % (rel, BODY * 2))
        docs.append((rel, full))
    remembered, keys = [], []

    def verdict(key, body, *rest, **kw):
        keys.append(key)
        if body.startswith("# " + fail_rel) or ("# %s\n" % fail_rel) in body:
            raise RuntimeError("読み手が落ちた")
        return {k: [] for k in g.COLD_KINDS}, False, set(), True, []

    def git_stub(args, cwd=None, *rest, **kw):
        return WORK.encode() if args[:2] == ["rev-parse", "--show-toplevel"] else None
    with patched(_git=git_stub, _branch_docs=lambda root, base: ("0" * 40, docs),
                 _branch_where=lambda root, mb, *a, **k: (None, None, "b"), _generated=lambda paths: set(),
                 _moved_lines=lambda root, mb: set(), doc_excerpt=lambda *a, **k: None, _last_path=lambda *a, **k: None,
                 _branch_verdict=verdict, _remember=lambda d: remembered.extend(d),
                 _write_findings=lambda *a, **k: None, reader_source=lambda *a, **k: {}):
        with contextlib.redirect_stdout(io.StringIO()):
            g.branch_check(["--base", "main"])
    return remembered, keys


def digest(rel):
    import hashlib
    return hashlib.sha256(("# %s\n\n%s\n" % (rel, BODY * 2)).encode("utf-8")).hexdigest()


# 12. 読み手が落ちた文書を読んだ物として覚えない
def f12():
    remembered, _ = branch_run("a.md")
    check(12, digest("a.md") not in remembered and digest("b.md") in remembered,
          "落ちた文書を覚えた・読んだ文書を覚えない: a=%s b=%s" % (digest("a.md") in remembered, digest("b.md") in remembered))


# 13. 覚えた判定の鍵にモデルと effort を入れる
def f13():
    _, keys1 = branch_run("none")
    with patched(DOC_MODEL="opus-test"):
        _, keys2 = branch_run("none")
    with patched(DOC_EFFORT="low-test"):
        _, keys3 = branch_run("none")
    check(13, not set(keys1) & set(keys2) and not set(keys1) & set(keys3),
          "モデル・effort を替えても同じ鍵: %r %r %r" % (keys1, keys2, keys3))
    asked = []

    def reader(prompt, schema, **kw):
        asked.append(kw.get("model"))
        return {"verdicts": [{"n": 1, "verdict": "old"}]}
    with patched(run_reader=reader, DOC_BRANCH=os.path.join(WORK, "branch")):
        g._asked_marks("PROMPT", g.BASE_WORDS)
        with patched(DOC_MODEL="opus-test"):
            g._asked_marks("PROMPT", g.BASE_WORDS)
        g._asked_marks("PROMPT", g.BASE_WORDS)
    check(13, len(asked) == 2, "モデルを替えても前の答えを使った(問うた回数 %d)" % len(asked))


# 14. graphql の query が単一引用なら、query の中の $名前 は字のまま。同じ名前のシェルの変数が在っても止めない
def f14():
    q_resolve = "mutation($t: ID!) { resolveReviewThread(input: {threadId: $t}) { thread { id } } }"
    q_pr = 'query($pr: Int!) { repository(owner:"o",name:"r"){ pullRequest(number: $pr){ title } } }'
    q_owner = 'query($owner: String!) { repository(owner: $owner, name: "r") { id } }'
    q_body = 'mutation($body: String!) { addComment(input:{subjectId: "x", body: $body}) { clientMutationId } }'
    for cmd in ("for t in PRRT_a PRRT_b; do gh api graphql -f query='%s' -f t=\"$t\"; done" % q_resolve,
                "for pr in 1 2; do gh api graphql -f query='%s' -F pr=$pr; done" % q_pr,
                "owner=x; gh api graphql -f query='%s' -F owner=\"$owner\"" % q_owner):
        cands, blk, _ = g.posting_bodies(cmd, WORK)
        check(14, not blk and not cands, "単一引用の query を読めないと見た: %s → %r %r" % (cmd[:50], cands, blk))
    cands, blk, _ = g.posting_bodies("body=\"%s\"; gh api graphql -f query='%s' -f body=\"$body\"" % (BODY, q_body), WORK)
    check(14, cands == [BODY] and not blk, "同じ名前の本文の変数を読まない・止めた: %r %r" % (cands, blk))
    # 止める側は残す: 本文の変数が解けない・query の展開される所に置換や変数が在る
    for cmd in ("for t in a b; do gh api graphql -f query='%s' -f body=\"$t\"; done" % q_body,
                "gh api graphql -f query='%s' -f body=\"$body\"" % q_body,
                "body=x; gh api graphql -f query='mutation { addComment(input:{subjectId: \"x\", body: \"'\"$(cat f)\"'\"}) { x } }'",
                "gh api graphql -f query='mutation { addComment(input:{subjectId: \"x\", body: \"'\"$B\"'\"}) { x } }'",
                "t=1; gh api graphql -f query=\"$Q\""):
        _, blk, _ = g.posting_bodies(cmd, WORK)
        check(14, bool(blk), "読めない本文・query を通した: %s" % cmd[:60])


# 15. 単一引用の本文の中の $( や ` は字。ほかの語の展開される置換の頭と突き合わせて止めない
def f15():
    for cmd, want in (("X=$((1+2)); gh pr comment 1 --body 'run $(npm bin)/x %s'" % BODY, "run $(npm bin)/x "),
                      ("X=\"`date`\"; gh issue comment 1 --body 'use `foo` here %s'" % BODY, "use `foo` here "),
                      ("Y=$(date); gh api repos/o/r/issues/1/comments -f body='see $(cat f) %s'" % BODY, "see $(cat f) ")):
        cands, blk, _ = g.posting_bodies(cmd, WORK)
        check(15, len(cands) == 1 and cands[0].startswith(want) and not blk,
              "単一引用の本文を置換渡しと見た: %s → %r %r" % (cmd[:50], [c[:30] for c in cands], blk))
    # 止める側は残す: 二重引用・引用の外の置換は、値の途中でも止める
    for cmd in ("gh api repos/o/r/issues/1/comments -f body=\"See: $(cat f) %s\"" % BODY,
                "gh pr comment 1 --body \"See: `cat f` %s\"" % BODY,
                "gh pr comment 1 --body '%s '\"$(cat f)\"" % BODY,
                "X=$(date); gh pr comment 1 --body \"%s $(cat f)\"" % BODY,
                "gh pr comment 1 --body $(cat f)"):
        _, blk, _ = g.posting_bodies(cmd, WORK)
        check(15, bool(blk), "展開される置換を通した: %s" % cmd[:60])


# 16. 二重引用の本文の `…` は、同じ語に解ける変数や字のままの $ が在っても置換渡し(変数を解いても置換の中身は実行時に替わる)
def f16():
    for cmd in ('gh pr comment 1 --body "Fixed `cat f` in $HOME %s"' % BODY,
                'B=v2; gh pr comment 1 --body "Fixed `cat f` in $B %s"' % BODY,
                'gh api repos/o/r/issues/1/comments -f body="%s `cat f` $HOME"' % BODY,
                'R=o/r; gh pr comment 1 -R "$R" --body "Fixed `cat f` (price: \\$5) %s"' % BODY,
                'B=v2; echo \'$B\'; gh pr comment 1 --body "Fixed `cat f` in $B %s"' % BODY):
        cands, blk, _ = g.posting_bodies(cmd, WORK)
        check(16, bool(blk), "同じ語の置換を通した: %s → %r" % (cmd[:60], [c[:30] for c in cands]))


# 17. 展開される $( )・${ }・`…` の中の引用符は bash が数え直す。語の印が bash と食い違うので、全体で見る側に倒すか止める(18)
def f17():
    for cmd, bash_body in (("gh pr comment 1 -R \"$(printf %s \"'\")\" -b \"' --body '$(cat f)\" #'", None),
                           ("gh pr comment 1 -R \"$(printf %s \"'\")\" -b \"' --body '`cat f`\" #'", None),
                           ("B=secret; echo \"$B\"; gh pr comment 1 -R \"${X:-\"'\"}\" -b \"' --body '$B\" #'", "' --body 'secret")):
        cands, blk, parsed = g.posting_bodies(cmd, WORK)
        # bash が送る本文をそのまま読み手に回すか、止めるか(解析できない物として止めるのも可)
        check(17, bool(blk) or not parsed or (bash_body is not None and cands == [bash_body]),
              "置換の中の引用符で印がずれた本文を通した: %s → %r" % (cmd[:60], cands))


# 18. 二重引用の中の置換の閉じる所を言い切れなければ、語の切れ目が bash と違いうるので解析できない物として止める
#     (印を付けない見方に倒しても、ずれた語を本文と読んで通していた)。閉じると言い切れる正直な形は今までどおり読む
def f18():
    for cmd in ("gh issue create -R o/r -t \"$(printf %s \"'\")\" -b \"' -t '$(cat f)' --body 'hello\" #'",
                "gh pr comment 1 -R \"$(case a in a) printf %s \"'\";; esac)\" -b \"' --body '$(cat f)\" #'",
                "gh pr comment 1 -R \"${x//)/}\" -b \"' --body '$(cat f)\" #'",
                "gh pr comment 1 -R \"`echo \"'\"`\" -b \"' --body '$(cat f)\" #'"):
        cands, blk, parsed = g.posting_bodies(cmd, WORK)
        check(18, not parsed or (blk and not cands), "置換の中の引用符で語のずれる形の本文を通した: %s → %r %r" % (cmd[:60], [c[:30] for c in cands], blk))
    for cmd, want in (("gh pr create --title \"$(git log -1 --format='%%s')\" --body 'plain %s'" % BODY, "plain "),
                      ("gh pr comment 1 -R \"${R:-o/r}\" --body 'plain %s'" % BODY, "plain "),
                      ("gh pr comment 1 -R \"$((1+2))\" --body 'plain %s'" % BODY, "plain ")):
        cands, blk, parsed = g.posting_bodies(cmd, WORK)
        check(18, parsed and len(cands) == 1 and cands[0].startswith(want) and not blk,
              "閉じると言い切れる置換を読めない物と見た: %s → %r %r %r" % (cmd[:60], [c[:30] for c in cands], blk, parsed))


# 19. 二重引用の中の $( ) と `…` の中の gh の投稿も読む(shlex には 1 語で、前は中の本文を読み手に回さずに通していた)。
#     置換の中に " を書いた正直な形は、語の切れ目を bash に合わせて読む。語の頭の #・引用の外の ${ } の中の # は、bash どおりに読むか止める
def f19():
    for cmd, want in (("u=\"$(gh pr create --title t --body 'inner %s')\"" % BODY, "inner "),
                      ("u=`gh pr create --title t --body 'inner %s'`" % BODY, "inner "),
                      ("echo \"url: $(gh issue comment 1 --body \"inner %s\")\"" % BODY, "inner "),
                      ("gh pr comment 1 -R \"${REPO:-\"o/r\"}\" --body 'plain %s'" % BODY, "plain "),
                      ("gh pr comment 1 -R \"$(printf '%%s' \"o/r\")\" --body 'plain %s'" % BODY, "plain ")):
        cands, blk, parsed = g.posting_bodies(cmd, WORK)
        check(19, parsed and len(cands) == 1 and cands[0].startswith(want) and not blk,
              "置換の中の投稿か正直な形を読めなかった: %s → %r %r %r" % (cmd[:60], [c[:30] for c in cands], blk, parsed))
    for cmd in ("for f in a b; do echo \"$(basename \"$f\")\"; done; gh pr list",
                "gh api \"repos/$(gh repo view --json nameWithOwner -q \".nameWithOwner\")/pulls\""):
        cands, blk, parsed = g.posting_bodies(cmd, WORK)
        check(19, parsed and not cands and not blk, "読むだけの gh を止めた: %s → %r %r %r" % (cmd[:60], cands, blk, parsed))
    for cmd in ("cd sub && echo \"url: $(gh pr create --title t --body-file note.md)\"",
                "x=\"$(gh pr comment 1 --body \"$(cat f)\")\""):
        cands, blk, parsed = g.posting_bodies(cmd, WORK)
        check(19, bool(blk) or not parsed, "置換の中の読めない本文を通した: %s → %r" % (cmd[:60], [c[:30] for c in cands]))
    for cmd in ("gh issue comment 1 --body \"%s\" -t \"$( (true)#)\" '\n)\" --body 'EVIL' #'" % BODY,
                "gh issue comment 1 ${x:- #'}'} --body 'EVIL %s'" % BODY):
        cands, blk, parsed = g.posting_bodies(cmd, WORK)
        check(19, not parsed or any(c.startswith("EVIL") for c in cands),
              "閉じる所を言い切れない置換の後ろの本文を見落とした: %s → %r %r" % (cmd[:60], [c[:30] for c in cands], blk))



# 20. 置換の中を読むときに、外と読み方がずれて本文を見落とさない。読めなかったヒアドキュメント(`<<\EOF`)は止める。
#     二重引用の中の $( ) の中の " の後ろの # を注釈と見て本文の旗を消さない。`…` の中は \ を外してから読む。置換の中は
#     外の書き込み・cd・代入が見えないのでファイルを読まず、置換の中の書き込みは外の書き手に数える。埋め草を変数の名前と
#     見ない。深い入れ子は時間をかけずに止める。語の途中の #(`/#frag`)は注釈と見ない
def f20():
    os.makedirs(os.path.join(WORK, "sub"), exist_ok=True)
    for name, text in (("note.md", "BENIGN NOTE"), (os.path.join("sub", "note.md"), "SUB EVIL NOTE")):
        with open(os.path.join(WORK, name), "w") as f:
            f.write(text)
    for cmd in ("u=\"$(cat <<\\EOF\n)\" ; gh issue comment 1 --body decoy; echo \"\nEOF\ngh issue comment 1 --body REALHIDDEN\n)\"",
                "u=\"$(cat <<-\\EOF\n)\" ; gh issue comment 1 --body decoy; echo \"\nEOF\ngh issue comment 1 --body REALHIDDEN\n)\""):
        cands, blk, parsed = g.posting_bodies(cmd, WORK)
        check(20, not parsed, "読めないヒアドキュメントの ) で置換を閉じた: %s → %r %r" % (cmd[:40], cands, blk))
    for cmd, want in (("gh issue comment 1 -t \"$(echo \" #\" )\" --body 'REAL BODY' -t \"$(echo \"\n\")\"", "REAL BODY"),
                      ("u=\"`gh issue comment 1 --body \\\"hello world EVIL\\\"`\"", "hello world EVIL"),
                      ("x=`echo \\`gh issue comment 1 --body hidden\\``", "hidden")):
        cands, blk, parsed = g.posting_bodies(cmd, WORK)
        check(20, bool(blk) or not parsed or want in cands, "bash の送る本文を見落とした: %s → %r %r" % (cmd[:50], cands, blk))
    # $$ の後の ( { は、二重引用の中で bash 3.2 が括弧と数えて引用の閉じる所が変わる。`$[`・`$(( ))` の中の # は字。どれも読めない物とする
    for cmd in ("echo $${ # it's\ngh issue comment 1 --body 'EVILBODY' # ' }",
                "echo \"$${\" # it's\ngh issue comment 1 --body 'EVILBODY' # ' }\"",
                "echo \"S $$(\" #\"\n)\"; gh pr comment 1 --body EVILBODY #\"",
                "echo \"S $${\" #\"\n}\"; gh pr comment 1 --body EVILBODY #\"",
                "false && echo \"S $[ \" #\"\n]\"; gh pr comment 1 --body EVILBODY #\"",
                "false && echo $(( 1 #\"\n\" )); gh pr comment 1 --body EVILBODY #\"",
                "(( x = 1 # )); gh pr comment 1 --body EVILBODY",
                "for (( i=0; i<1 # ; i++ )); do :; done; gh pr comment 1 --body EVILBODY"):
        cands, blk, parsed = g.posting_bodies(cmd, WORK)
        check(20, bool(blk) or not parsed or "EVILBODY" in cands, "読めない形の後の本文を見落とした: %r → %r %r" % (cmd[:30], cands, blk))
    # \ で引用した字と、置換を閉じる ) の後の # は語の途中で、同じ行の後ろの gh は走る
    for cmd in ("echo a\\ #x; gh pr comment 1 --body EVILBODY", "echo a\\;#x; gh pr comment 1 --body EVILBODY",
                "echo $(echo a)#x; gh pr comment 1 --body EVILBODY", "echo $((1+2))#x; gh pr comment 1 --body EVILBODY",
                "cat <(echo a)#x; gh pr comment 1 --body EVILBODY", "a=(x)#x; gh pr comment 1 --body EVILBODY",
                # サブシェル・関数・(( ))・case のパターンを閉じる ) の後の # は注釈で、中の ' の後の行の gh は走る
                "(cd sub)# '\ngh pr comment 1 --body EVILBODY\n# '", "f()# '\n{ :; }\ngh pr comment 1 --body EVILBODY\n# '",
                "(( x=1 ))# '\ngh pr comment 1 --body EVILBODY\n# '", "case a in a)# '\ngh pr comment 1 --body EVILBODY\n# '\n;; esac"):
        cands, blk, parsed = g.posting_bodies(cmd, WORK)
        check(20, bool(blk) or not parsed or "EVILBODY" in cands, "語の途中の # を注釈と見て本文を見落とした: %r → %r %r" % (cmd[:30], cands, blk))
    for cmd in ("printf EVIL > note.md; u=\"$(gh issue comment 1 --body-file \"note.md\")\"",
                "\\cd sub; u=\"$(gh issue comment 1 --body-file \"note.md\")\"",
                "CLAUDE_JOB_DIR=$PWD/sub; u=\"$(gh issue comment 1 --body-file \"$CLAUDE_JOB_DIR/note.md\")\"",
                "x=\"$(cp sub/note.md note.md)\"; gh issue comment 1 --body-file note.md",
                "x=\"$(f=note.md; cp sub/note.md $f)\"; gh issue comment 1 --body-file note.md",
                "f=a; x=\"$(f=note.md; cat sub/note.md > $f)\"; gh issue comment 1 --body-file note.md",
                "x=\"$(python3 - <<'EOF'\nopen('note.md','w').write('EVIL BODY')\nEOF\n)\"; gh issue comment 1 --body-file note.md",
                "F=a.md; x=\"$(export F=note.md; cp other.md $F)\"; gh issue comment 1 --body-file note.md",
                "x=\"$(declare F=note.md; cp other.md \"$F\")\"; gh issue comment 1 --body-file note.md",
                "x=\"$(: ${F:=note.md}; cp other.md $F)\"; gh issue comment 1 --body-file note.md",
                "______________=\"benign\"; gh issue comment 1 --body \"${x:-\"REAL BODY\"}\""):
        cands, blk, parsed = g.posting_bodies(cmd, WORK)
        check(20, (bool(blk) and not cands) or not parsed, "外の効果の見えない本文を読んで通した: %s → %r" % (cmd[:50], cands))
    # 置換の中の読むだけのコマンドの、外で決まる変数は書き手に数えない
    for cmd in ("BR=feat; N=\"$(gh pr view \"$BR\" --json number -q .number)\"; gh pr comment \"$N\" --body-file note.md",
                "F=\"$(basename \"$PWD\")\"; gh pr comment 1 --body-file note.md",
                "LOG=\"$(git log --oneline \"$BASE\"..HEAD)\"; gh pr comment 1 --body-file note.md"):
        cands, blk, parsed = g.posting_bodies(cmd, WORK)
        check(20, parsed and cands == ["BENIGN NOTE"] and not blk, "置換の中の $ を持つ語を書き手と見て止めた: %r → %r %r" % (cmd[:40], cands, blk))
    cands, blk, parsed = g.posting_bodies("(cd sub)# it's fine\ngh pr comment 1 --body ok", WORK)
    check(20, parsed and cands == ["ok"] and not blk, "サブシェルの後の注釈を語と読んで止めた: %r %r %r" % (cands, blk, parsed))
    deep = "x=" + "\"$(echo a " * 400 + "z" + ")\"" * 400 + "; gh issue comment 1 --body-file note.md"
    started = time.monotonic()
    cands, blk, parsed = g.posting_bodies(deep, WORK)
    check(20, not parsed and time.monotonic() - started < 10, "深い入れ子を止めなかったか遅い: %r %.1fs" % (parsed, time.monotonic() - started))
    cmd = "gh issue comment 1 --body 'ok %s' -t \"$(curl -s https://example.com/a/#frag)\"" % BODY
    cands, blk, parsed = g.posting_bodies(cmd, WORK)
    check(20, parsed and len(cands) == 1 and not blk, "語の途中の # を注釈と見て止めた: %r %r %r" % ([c[:20] for c in cands], blk, parsed))

# 30. 置換の中の case を読めない物とするのは、コマンドの語の位置の case だけ(前は `use-case.md` の case でも止めていた)
def f30():
    for cmd in ('x="$(cat docs/use-case.md)"; gh pr comment 1 --body ok', "x=\"$(grep 'test case' f)\"; gh pr comment 1 --body ok",
                'x="$(echo esac)"; gh pr comment 1 --body ok'):
        cands, blk, parsed = g.posting_bodies(cmd, WORK)
        check(30, parsed and cands == ["ok"] and not blk, "語の位置でない case で止めた: %r → %r %r %r" % (cmd[:40], cands, blk, parsed))
    for cmd in ('x="$(case a in a) echo;; esac)"; gh pr comment 1 --body ok', 'x="$(echo; case a in a) :;; esac)"; gh pr comment 1 --body ok',
                'x="$(if case a in a) :;; esac; then :; fi)"; gh pr comment 1 --body ok'):
        _, blk, parsed = g.posting_bodies(cmd, WORK)
        check(30, bool(blk) or not parsed, "置換の中の本物の case を読んだ: %r" % cmd[:40])


# 21〜28 の引き金。GH は本文にファイルの中身を渡す投稿で、読めれば置換渡しで止まる。TAIL はヒアドキュメントで、盾が開始を
# 読み落とすと、本文の中の ' が引用を開き、後ろの GH を引用の中に隠す
GH = 'gh pr comment 1 --body "$(cat secret)"'
TAIL = "<<EOF\nit's\nEOF\n" + GH + " #'"


def stops(n, cmd):
    _, blk, parsed = g.posting_bodies(cmd, WORK)
    check(n, bool(blk) or not parsed, "bash が走らせる gh を見落とした: %r" % cmd[:60])


# 21. 盾(ヒアドキュメントを抜く前処理)と注釈を落とす前処理が、同じ # を注釈かどうかで割れない
# (置換を閉じる ) の後・\ で引用した空白の後・`…` の中・${ } の中の #)。盾が置換の中に置いたヒアドキュメントの本文が、
# 置換を閉じた後の行に在る形(bash はその行をコマンドとして走らせる)も見落とさない
def f21():
    for cmd in ("cat $(echo a)#x " + TAIL, "echo `echo #x` " + TAIL, "cat a\\ #x " + TAIL, "echo ${x:-a #b} " + TAIL,
                "x=`cat <<EOF`\n" + GH + "\nEOF", "echo ${x:-<<EOF}\n" + GH + "\nEOF",
                "x=$(cat <<EOF)\n" + GH + "\nEOF", 'x="$(cat <<EOF)"\n' + GH + "\nEOF", "echo $((1<<x))\n" + GH + "\nx"):
        stops(21, cmd)


# 22. `…` の中は bash が先に \\ を \ にしてから読むので、`echo \\'` の ' は引用符でない
def f22():
    for cmd in ("echo `echo \\\\'` ; cat " + TAIL, "echo \"`echo \\\\'`\" ; cat " + TAIL):
        stops(22, cmd)


# 23. 二重引用の中の ${ } の中の引用を追う
def f23():
    stops(23, "echo \"${x:-'\"'}\" " + TAIL)


# 24. 盾が読めない区切りの << を読み飛ばさない。本文の無いヒアドキュメントは読む(読めないと止めすぎになる)
def f24():
    for delim in ("\\EOF", 'E"OF"', "1", "@E", "E\\$", "EOF'x"):
        stops(24, "cat <<%s\nit's\nEOF\n%s #'" % (delim, GH))
    cands, blk, parsed = g.posting_bodies("cat > f <<'EOF'\nEOF\ngh pr comment 1 --body ok", WORK)
    check(24, parsed and cands == ["ok"] and not blk, "本文の無いヒアドキュメントで止めた: %r %r %r" % (cands, blk, parsed))


# 25. 算術の (( )) の中の # は、行をまたいでも注釈と読まない
def f25():
    for cmd in ("((x=1+\n2 #x)); " + GH, "((x=1+\\\n2 #x)); " + GH, "(( 1 + ((2)) #c )); " + GH):
        stops(25, cmd)


# 26. 置換の中の case のパターンの ) を、置換を閉じる ) と読まない(bash 4 以降)
def f26():
    stops(26, "( echo $(case a in a) :;; esac)#x; " + GH + " )")


# 27. \ で引用した字の後に行継続が続いても、次の行の頭の # は語の途中
def f27():
    stops(27, "echo a\\ \\\n#x; " + GH)


# 28. [[ … =~ 正規表現 ]] の正規表現の中の # を注釈と読まない
def f28():
    for cmd in ("[[ x =~ ^(a|b)#[0-9]+$ ]] && echo ok; " + GH, "[[ x =~ (#b) ]]; " + GH, "[[ x =~ a|#b ]]; " + GH):
        stops(28, cmd)


# 33. 注釈を落とす前処理が読めない形と見たコマンドでも、字面に書いた書き込み先の文書を記録する(前は何も拾わず、
# git の外に書いた文書が検査から漏れた)。読めるコマンドの拾い方は変えない
def f33():
    doc = os.path.join(WORK, "f33.md")
    with open(doc, "w") as f:
        f.write("a\n")
    for cmd in ("case $x in a)# c\necho a > f33.md;; esac", "echo $[1+1] > f33.md", "echo a > f33.md"):
        wrote = g._written_by_command(cmd, WORK)[0]
        check(33, [os.path.realpath(p) for p in wrote] == [os.path.realpath(doc)],
              "書いた文書を記録しなかった: %r → %r" % (cmd, wrote))


# 34. コマンド名の前に書いたヒアドキュメント(`<<'EOF' gh …`)の後ろの gh を見落とさず、本文も後ろに書いたのと同じに読む
def f34():
    stops(34, "<<'EOF' " + GH + "\nx\nEOF")
    stops(34, "<<'EOF' timeout 5 " + GH + "\nx\nEOF")
    cands, blk, parsed = g.posting_bodies("<<'EOF' gh issue comment 1 -F -\n" + BODY + "\nEOF", WORK)
    check(34, parsed and cands == [BODY] and not blk, "前に書いたヒアドキュメントの本文を読まなかった: %r %r" % (blk, parsed))


# 31. 外の cd の後で走る置換の中の gh を、フックの場所で走る物と読まない(前は画面をフックの場所のリポジトリの
# 同じ番号のスレッドから引いていた)。cd の無い置換の中の gh は、今までどおりフックの場所で走る物と読む
def f31():
    a = g.analyze('cd /other/repo && x="$(' + 'g' + 'h pr comment 5 --body hi)"; echo "$x"', WORK)
    check(31, a.parsed and a.run_place("hi", WORK) is None,
          "cd の後の置換の中の gh の走る場所をフックの場所と読んだ: %r" % a.run_place("hi", WORK))
    a = g.analyze('x="$(' + 'g' + 'h pr comment 5 --body hi)"; echo "$x"', WORK)
    check(31, a.parsed and a.run_place("hi", WORK) == WORK,
          "cd の無い置換の中の gh の走る場所を読めない物にした: %r" % a.run_place("hi", WORK))


# 32. 置換の中の引用符を探す読みが、閉じない $( ・入れ子の ${ の並ぶ長いコマンドで長さの 2 乗の時間をかけない
# (前は 70KB で 15 秒を超え、100KB の上限の近くで 40 秒。フックの時間切れを過ぎると止めずに通る)
def f32():
    for cmd in ("echo " + "$(:\\()" * 12000 + "; gh pr comment 1 --body x",
                "gh pr comment 1 --body ${a:-" + "${a:-" * 12000 + "x" + "}" * 12001):
        started = time.monotonic()
        g.posting_bodies(cmd, WORK)
        took = time.monotonic() - started
        check(32, took < 8, "%d 字のコマンドを読むのに %.1f 秒かかった: %r" % (len(cmd), took, cmd[:30]))


# 35. case から esac までの ) を降ろさない決めを、esac の後と引用の中の case に及ぼさない。case の後に開いた算術の括弧は
# 降ろす(前は後ろのコマンドの全部を算術の中と読み、後ろのヒアドキュメントで止め、`<<1x` を桁送りと読んで後ろの gh を見落とした)
def f35():
    for cmd in ('for f in *; do\n  case "$f" in *.md) n=$((n+1));; esac\ndone\ngh pr comment 1 --body-file - <<\'EOF\'\n' + BODY + "\nEOF",
                'gh pr comment 1 --body "Fix the edge\ncase where it fails' + BODY + '" && echo $((1+1)) # c'):
        cands, blk, parsed = g.posting_bodies(cmd, WORK)
        check(35, parsed and len(cands) == 1 and BODY in cands[0] and not blk,
              "case の後の算術の括弧を閉じずに止めた: %r → %r %r" % (cmd[:40], blk, parsed))
    for cmd in ("case $1 in a) n=$((n+1));; esac\ncat <<1x\nit's\n1x\n" + GH + "\necho it\\'s",
                "case $x in (a) n=$((n+1));; esac\n# c '\n" + GH, "case a in a) ((x=1+\n2 #x));; esac; " + GH,
                "case a in a) echo $((1+\n2 #x));; esac; " + GH):
        stops(35, cmd)


# 36. =~ の正規表現の範囲は、引用の外の [[ の後の =~ だけで、後ろに ]] が無ければ行末まで(前は引用・注釈の中の =~ も数え、
# 範囲を文字列の終わりまで延ばして、後ろの注釈で止めた)
def f36():
    for cmd in ("gh pr comment 1 --body 'Use =~ for regex " + BODY + "' # c",
                "echo 'a =~ b'\n# step\ngh pr comment 1 --body '" + BODY + "'",
                "gh pr view 1 # title =~ foo?\n# next\ngh pr comment 1 --body '" + BODY + "'"):
        cands, blk, parsed = g.posting_bodies(cmd, WORK)
        check(36, parsed and len(cands) == 1 and BODY in cands[0] and not blk,
              "引用・注釈の中の =~ の後の注釈で止めた: %r → %r %r" % (cmd[:40], blk, parsed))
    for cmd in ("[[ $x =~ (a)#b\nc ]]; " + GH, "[[ x =~ ^(a|b)#[0-9]+$ ]] && echo ok; " + GH):
        stops(36, cmd)


# 37. ヒアドキュメントの開始行が、行継続(\\ で終わる)か閉じない引用で次の行へつながる形は読めない物とする(bash は本文を、
# つないだ行の後から読む。前は次の行を本文と読み、つないだ行の gh を見落とした)。注釈の中の \\ と引用符ではつながない
def f37():
    for cmd in ("cat <<'EOF' \\\n| " + GH + "\nbody\nEOF", "cat <<'EOF' > b.md \\\n  && " + GH + "\nbody\nEOF",
                "cat <<A; echo 'x\ny'; " + GH + "\nA\necho it\\'s", 'cat <<A; echo "$(echo\n)"; ' + GH + "\nA\necho it\\'s"):
        stops(37, cmd)
    cands, blk, parsed = g.posting_bodies("cat <<EOF # it's \\\nbody\nEOF\ngh pr comment 1 --body '" + BODY + "'", WORK)
    check(37, parsed and cands == [BODY] and not blk, "注釈の中の \\ と ' でつながると読んだ: %r %r" % (blk, parsed))


# 38. 引用・注釈の中の「__HEREDOC」の字を、盾(ヒアドキュメントを抜く前処理)の置いた印と見ない(前は読めない物として止めた)。
# 盾の置いた印が引用の中に在る形は、今までどおり止める
def f38():
    for cmd in ("grep -n '__HEREDOC' f; gh pr comment 1 --body '" + BODY + "'",
                "echo a # __HEREDOC0__\ngh pr comment 1 --body '" + BODY + "'"):
        cands, blk, parsed = g.posting_bodies(cmd, WORK)
        check(38, parsed and cands == [BODY] and not blk, "引用・注釈の中の印の字で止めた: %r → %r %r" % (cmd[:40], blk, parsed))
    check(38, g.normalize_shell("echo ' __HEREDOC0__ '", 1) is None, "盾の置いた印が引用の中に在るのを読んだ")


# 39. 区切りの語の一部だけを引用したヒアドキュメント(`<<\\EOF`・`<<E"OF"`・`<<"E"OF`)を、引用した区切りと読む(本文を展開しない)。
# `$(` の中の `EOF)` も終わりの行と読む。bash 3.2 と 5 で読みの割れる形(置換の中の一部だけ引用した区切り・`EOF)` で終わる
# 本文の括弧)は、今までどおり読まない
def f39():
    for delim in ("\\EOF", 'E"OF"', '"E"OF', "E\\OF"):
        cands, blk, parsed = g.posting_bodies("gh pr comment 1 --body-file - <<%s\n$HOME %s\nEOF" % (delim, BODY), WORK)
        check(39, parsed and cands == ["$HOME " + BODY] and not blk, "%s の本文を読まなかった: %r %r" % (delim, blk, parsed))
    cands, blk, parsed = g.posting_bodies("x=$(cat <<EOF\nbody\nEOF)\ngh pr comment 1 --body '" + BODY + "'", WORK)
    check(39, parsed and cands == [BODY] and not blk, "$( の中の EOF) で終わるヒアドキュメントで止めた: %r %r" % (blk, parsed))
    for cmd in ("x=$(cat <<EOF\nb)\nEOF)\n" + GH, 'u="$(cat <<\\EOF\n)" ; ' + GH + '; echo "\nEOF\n)"'):
        stops(39, cmd)


# 40. 注釈を落とす前処理が読めない形と見たコマンドで、注釈の中に引用符(`a)# don't`)が在っても、書き込み先の文書を記録する
# (前は字句解析が引用の閉じを探して止まり、何も拾わなかった)
def f40():
    doc = os.path.join(WORK, "f40.md")
    with open(doc, "w") as f:
        f.write("a\n")
    for cmd in ("case $x in a)# don't\n;; esac\necho a > f40.md", "echo $[1+1] # it's\necho a > f40.md"):
        wrote = g._written_by_command(cmd, WORK)[0]
        check(40, [os.path.realpath(p) for p in wrote] == [os.path.realpath(doc)],
              "注釈の中の引用符で書いた文書を記録しなかった: %r → %r" % (cmd, wrote))
    wrote = g._written_by_command("echo $[1+1] '# x' > f40.md", WORK)[0]
    check(40, [os.path.realpath(p) for p in wrote] == [os.path.realpath(doc)], "引用の中の # を注釈と読んだ: %r" % wrote)

# 41. 最後の引数を書き込み先に取るコマンド(cp・mv など)の書き込み先が、同じコマンドの中で解けない $ を持つ(`cp a "$F"`)と、
# 本文ファイルを書きうる物と見る(前は字のままの名前を照合して書き手に数えず、gh の前に書き換わる古いファイルを読んだ)。
# 解ける書き込み先(F=other.md)と、書き込み先を取らないコマンドの解けない $(`git log "$BASE"..HEAD`)は今までどおり読む
def f41():
    with open(os.path.join(WORK, "note.md"), "w") as f:
        f.write("BENIGN NOTE")
    for cmd in ('cp /etc/hosts "$F41_UNSET"; gh pr comment 1 --body-file note.md',
                'x="$(mv other.md "$F41_UNSET")"; gh pr comment 1 --body-file note.md',
                'ln -sf /etc/hosts "$F41_UNSET" && gh pr comment 1 --body-file note.md'):
        cands, blk, parsed = g.posting_bodies(cmd, WORK)
        check(41, (bool(blk) and not cands) or not parsed, "解けない書き込み先の cp を書き手と見ず、古いファイルを読んだ: %s → %r" % (cmd, cands))
    for cmd in ('F=other.md; cp /etc/hosts "$F"; gh pr comment 1 --body-file note.md',
                'git log --oneline "$F41_UNSET"..HEAD; gh pr comment 1 --body-file note.md'):
        cands, blk, parsed = g.posting_bodies(cmd, WORK)
        check(41, parsed and cands == ["BENIGN NOTE"] and not blk, "解ける書き込み先・書き込み先を取らないコマンドで止めた: %s → %r %r" % (cmd, cands, blk))

# 42. =~ の正規表現の範囲は、開いた [[ の中の 1 つの語の =~ から、[[ を閉じる 1 つの語の ]] まで。`[[:space:]]` の中の ]] と引用の
# 中の ]] では閉じない(前は後の最初の ]] で範囲を閉じ、`(#|$)` の # を注釈と読んで後ろの gh を落とした)。`d=~/w`(代入とチルダ)の
# =~ と、閉じた [[ の後の =~ は字(前は前に [[ が在るだけで範囲と見て、後ろの注釈で止めた)
def f42():
    for cmd in ("line='# x'; [[ $line =~ ^[[:space:]]*(#|$) ]] && " + GH,
                "while read -r line; do [[ $line =~ ^[[:space:]]*(#|$) ]] && continue; done < /dev/null; " + GH,
                '[[ $x =~ " ]] "(#) ]] || ' + GH, "[[ $x =~ a\\ ]] (#) ]] || " + GH):
        stops(42, cmd)
    for cmd in ("[[ $a == b ]] && d=~/w # w\ngh pr comment 1 --body '" + BODY + "'",
                "[[ -d a ]] && X=~/f.md # note\ngh pr comment 1 --body '" + BODY + "'",
                "[[ $x =~ ^a$ ]] && echo =~ # c\ngh pr comment 1 --body '" + BODY + "'"):
        cands, blk, parsed = g.posting_bodies(cmd, WORK)
        check(42, parsed and cands == [BODY] and not blk, "[[ の外の =~ の後の注釈で止めた: %r → %r %r" % (cmd[:40], blk, parsed))

# 43. 引用の外の $( ) の中の引用符では語の印(mark_words)を落とさない(bash も shlex も、その中の引用を外と同じに数える。前は落として
# 全体で見る側に倒れ、graphql の query の単一引用の中の $id を、ほかの語で展開される同じ名前と見て止めた)。二重引用の中の $( ) の
# 中の引用符は、ほかの語に引用の外の $( ) が在っても今までどおり印を落とす(17 の形)
def f43():
    for cmd in ("id=$(gh api repos/o/r/pulls/1/comments --jq '.[0].node_id'); gh api graphql -f query='mutation($id: ID!)"
                "{resolveReviewThread(input:{threadId:$id}){thread{id}}}' -f id=\"$id\"",
                "id=$(gh api repos/o/r/pulls/1/comments --jq \".[0].node_id\"); gh api graphql -f query='mutation($id: ID!)"
                "{minimizeComment(input:{subjectId:$id,classifier:OUTDATED}){clientMutationId}}' -f id=\"$id\""):
        cands, blk, parsed = g.posting_bodies(cmd, WORK)
        check(43, parsed and not blk, "引用の外の $( ) の中の引用符で印を落として止めた: %r → %r %r" % (cmd[:40], blk, parsed))
    for cmd in ("id=$(gh api x --jq '.a'); gh pr comment 1 -R \"$(printf %s \"'\")\" -b \"' --body '$id\" #'",
                "B=$(cat f); X=$(echo '{}'); gh pr comment 1 -R \"${X:-\"'\"}\" -b \"' --body '$B\" #'"):
        _, blk, _ = g.posting_bodies(cmd, WORK)
        check(43, bool(blk), "二重引用の中の置換の中の引用符で印がずれた本文を通した: %s" % cmd[:60])

# 44. nice・sudo・stdbuf・caffeinate・ionice・doas・arch・chronic・unbuffer・exec -a・builtin command・coproc・パスで書いた前置
# (/usr/bin/env)と、find -exec の後ろの gh を呼び出しと見て本文を読む。xargs・parallel の後ろの gh と、find -exec の {} を持つ gh
# の投稿は、足す語が本文の旗にもなりうるので止める(前はどれも gh が見えず素通しだった)。読むだけのサブコマンドと gh でない
# コマンドは今までどおり通す
def f44():
    post = "gh pr comment 1 --body '" + BODY + "'"
    for pre in ("nice -n 19 ", "sudo -u $USER ", "stdbuf -oL ", "caffeinate -i ", "ionice -c 3 ", "doas -u root ",
                "arch -arm64 ", "arch -arch arm64 ", "chronic ", "unbuffer ", "exec -a foo ", "builtin command ",
                "/usr/bin/env ", "/usr/bin/nice -n 5 ", "/usr/bin/time -o t.log ", "coproc "):
        cands, blk, parsed = g.posting_bodies(pre + post, WORK)
        check(44, parsed and cands == [BODY] and not blk, "前置の後ろの gh の本文を読まなかった: %r → %r %r" % (pre, blk, parsed))
    for cmd in ("coproc X { " + post + "; }", "find . -maxdepth 0 -exec " + post + " \\;"):
        cands, blk, parsed = g.posting_bodies(cmd, WORK)
        check(44, parsed and cands == [BODY] and not blk, "gh の本文を読まなかった: %r → %r %r" % (cmd[:30], blk, parsed))
    for cmd in ("printf '%s\\n' 12 13 | xargs -I{} gh pr comment 1 --body '" + BODY + "' {}",
                "echo /etc/hosts | xargs gh pr comment 1 --body-file", 'echo "pr comment 1 --body-file /etc/hosts" | xargs gh',
                "parallel gh pr comment {} --body-file /etc/hosts ::: 1 2", "find . -name '*.md' -exec gh pr comment 1 --body-file {} \\;",
                "find . -name '*.md' -exec nice gh pr comment 1 --body-file {} +"):
        _, blk, parsed = g.posting_bodies(cmd, WORK)
        check(44, bool(blk) or not parsed, "xargs・find -exec の後ろの gh の投稿を通した: %r" % cmd[:60])
    for cmd in ("gh pr list --json number --jq '.[].number' | xargs -I{} gh pr view {} --json title",
                "gh pr list --json number --jq '.[].number' | xargs -n1 gh pr view", "nice -n 19 python3 x.py",
                "xargs -n1 echo", "sudo -u root ls", "time -p ls", "find . -name '*.py' -exec grep -l gh {} \\;"):
        cands, blk, parsed = g.posting_bodies(cmd, WORK)
        check(44, parsed and not cands and not blk, "読むだけの形・gh でないコマンドで止めた: %r → %r %r" % (cmd[:40], blk, parsed))

# 45. [[ の後が空白でない区切り(行継続の \・括弧)でも [[ を開きと見て、=~ の右の # を注釈と読まない。=~ の左の $( ) の中の
# [[ … ]] は、外の [[ を閉じない(前はどちらも =~ の範囲を見失い、# から後ろの gh を注釈として落とした)。閉じた [[ の後の
# `d=~/w # w` は今までどおり通す(42)
def f45():
    for cmd in ("[[\\\n $x =~ ^(a)#x ]]; " + GH, "[[($x =~ ^(a)#x) ]]; " + GH,
                "x=a; [[ $([[ -n a ]] && echo a) =~ ^(a)#x ]]; " + GH, "[[ $( [[ -n a ]] ) =~ (a)#x ]]; " + GH,
                "[[\t$x =~ ^(a)#x ]]; " + GH):
        stops(45, cmd)
    for cmd in ("[[ $([[ -n a ]] && echo a) == a ]] && d=~/w # w\ngh pr comment 1 --body '" + BODY + "'",
                "[[(-d a) ]] && X=~/f.md # note\ngh pr comment 1 --body '" + BODY + "'"):
        cands, blk, parsed = g.posting_bodies(cmd, WORK)
        check(45, parsed and cands == [BODY] and not blk, "閉じた [[ の後の =~ の後の注釈で止めた: %r → %r %r" % (cmd[:40], blk, parsed))

# 46. 前置の束ねた短い旗(`sudo -Eu me`・`xargs -0n 1`)を 1 字ずつ読み、値を取る旗の字が最後なら次の語を値として飛ばす(前は語ごとに
# しか見ず、値の語をコマンド名と読んで後ろの gh を見落とした)。値が融合した束(`-un1`)・値を省ける旗の束(`-tiI`)・束ねない
# 前置(`arch -arm64e`)は、次の語を飛ばさない
def f46():
    post = "gh pr comment 1 --body '" + BODY + "'"
    for pre in ("sudo -Eu me ", "sudo -un1 ", "arch -arm64e ", "stdbuf -oL -eL ", "nice -n5 "):
        cands, blk, parsed = g.posting_bodies(pre + post, WORK)
        check(46, parsed and cands == [BODY] and not blk, "前置の後ろの gh の本文を読まなかった: %r → %r %r" % (pre, blk, parsed))
    for cmd in ("echo 1 | xargs -0n 1 gh pr comment 1 --body-file /etc/hosts", "sudo -EHu me gh pr comment 1 --body-file /etc/hosts"):
        cands, blk, parsed = g.posting_bodies(cmd, WORK)
        check(46, bool(blk) or bool(cands) or not parsed, "束ねた旗の後ろの gh の投稿を見落とした: %r" % cmd)
    cands, blk, parsed = g.posting_bodies("xargs -tiI gh pr view 1", WORK)
    check(46, parsed and not cands and not blk, "値を省ける旗の束の後ろの gh を値と読んだ: %r %r" % (blk, parsed))
    check(46, g.command_start(["sudo", "-Eu", "me", "gh"]) == 3 and g.command_start(["sudo", "-Eun1", "gh"]) == 2,
          "束ねた旗の値の数え方が違う")

# 47. find の 2 つ目からの -exec の gh と、\( \) の式・\; の閉じで割れた後ろの -exec の gh も呼び出しと見る(前は最初の gh で返し、
# 割れた後ろを見ず、本文を読まずに通した)。-execdir・-okdir・sudo -D・--chdir の後ろの gh は別の所で走るので、本文ファイルの
# 相対のパスをフックの場所で読まない(前は gh が走らない所の n.md を本文と読んだ)。-exec を連ねた長い find も 1 度の走査で読む
def f47():
    with open(os.path.join(WORK, "n.md"), "w") as f:
        f.write("BENIGN NOTE")
    for cmd in ("find . -maxdepth 0 -exec true \\; -exec gh pr comment 1 --body-file /etc/hosts \\;",
                "find . \\( -name a \\) -exec gh pr comment 1 --body-file /etc/hosts \\;",
                "find . -maxdepth 0 -exec gh pr view 1 {} + -exec gh pr comment 1 --body-file /etc/hosts \\;",
                "find . -maxdepth 0 -exec gh pr view 1 \\; -exec gh pr comment 1 --body-file /etc/hosts \\;"):
        cands, blk, parsed = g.posting_bodies(cmd, WORK)
        check(47, parsed and len(cands) == 1 and "localhost" in cands[0] and not blk,
              "find の後ろの -exec の gh の本文を読まなかった: %r → %r %r" % (cmd[:50], blk, parsed))
    for cmd in ("find d -name n.md -execdir gh pr comment 1 --body-file n.md \\;", "find d -okdir gh pr comment 1 --body-file n.md \\;",
                "sudo -D /other gh pr comment 1 --body-file n.md", "sudo -ED /other gh pr comment 1 --body-file n.md",
                "sudo --chdir=/other gh pr comment 1 --body-file n.md", "env -C /other gh pr comment 1 --body-file n.md"):
        cands, blk, parsed = g.posting_bodies(cmd, WORK)
        check(47, bool(blk) and "BENIGN NOTE" not in cands, "別の所で走る gh の本文をフックの場所で読んだ: %r → %r" % (cmd, cands))
    cands, blk, parsed = g.posting_bodies("find . -maxdepth 0 -exec gh pr comment 1 --body-file n.md \\;", WORK)
    check(47, cands == ["BENIGN NOTE"] and not blk, "-exec の gh の本文ファイルを読まなかった: %r %r" % (cands, blk))
    for cmd in ("find . " + "-exec nice " * 9000 + "gh pr comment 1 --body-file /etc/hosts \\;",
                "find . " + "-exec true \\; " * 7000 + "-exec gh pr comment 1 --body-file /etc/hosts \\;"):
        started = time.monotonic()
        cands, blk, parsed = g.posting_bodies(cmd, WORK)
        took = time.monotonic() - started
        check(47, took < 8 and parsed and len(cands) == 1, "%d 字の find を %.1f 秒で読み、%r %r" % (len(cmd), took, blk, parsed))

# 48. xargs -I・-i・--replace・parallel -I・find -exec の {} は、差し込む印の在る所だけに印を付ける(FED_WORD)。語の途中
# (`repos/o/r/pulls/{}/comments`)・-- の後ろ・後ろに本文の旗が見えている pr/issue comment の位置引数(gh は本文の旗を 2 つ
# 受けない)は旗にならないので通し、見えている本文は読む。旗の語の中・旗の値・サブコマンドの語(`xargs -I view gh pr view …`
# は gh pr comment にもなる)・本文の旗より後ろの位置引数(--body を重ねると後ろが勝つ)は止める(前は差し込む語の在る gh の
# 投稿を全部止め、サブコマンドの語の印を読むだけの形と見て通していた)。xargs の -n・-L と、parallel の -m などの {} を何語にも
# する旗が在れば、今までどおり止める
def f48():
    for cmd in ("gh pr list --json number -q '.[].number' | xargs -I{} gh api repos/o/r/pulls/{}/comments",
                "git diff --name-only | xargs -I{} gh api repos/o/r/contents/{}", "find . -exec gh api repos/x/{} \\;",
                "ls | xargs -0I{} gh api repos/o/r/contents/{}", "parallel -I@ gh api repos/o/r/pulls/@ ::: 1 2"):
        cands, blk, parsed = g.posting_bodies(cmd, WORK)
        check(48, parsed and not cands and not blk, "語の途中の差し込みで読むだけの gh api を止めた: %r → %r %r" % (cmd[:50], blk, parsed))
    for cmd in ("ls | xargs -I{} gh pr comment {} --body '" + BODY + "'", "ls | xargs -i gh issue comment {} -b '" + BODY + "'",
                "ls | xargs --replace=@ gh pr comment @ --body '" + BODY + "'",
                "ls | xargs -I{} gh api repos/o/r/issues/{}/comments -f body='" + BODY + "'",
                "find . -exec gh pr comment {} --body '" + BODY + "' \\;", "ls | xargs -I{} gh pr comment -R o/r --body '" + BODY + "' -- {}"):
        cands, blk, parsed = g.posting_bodies(cmd, WORK)
        check(48, parsed and cands == [BODY] and not blk, "差し込む語の在る gh の見えている本文を読まなかった: %r → %r %r" % (cmd[:50], blk, parsed))
    with open(os.path.join(WORK, "view.md"), "w") as f:
        f.write("BENIGN VIEW")
    for cmd in ("printf comment | xargs -I view gh pr view 1 --body-file view.md", "ls | xargs -I{} gh pr comment 1 --body-file {}",
                "ls | xargs -I{} gh pr comment 1 --body={}", "ls | xargs -I{} gh pr comment {} -R {} --body x",
                "ls | xargs -I{} gh pr comment 1 {}", "ls | xargs -I{} gh pr comment 1 --body x {}",
                "ls | xargs -I{} gh api repos/o/r/issues/1/comments -f body={}", "ls | xargs -I{} gh api {}",
                "ls | xargs -I a -I {} gh pr comment 1 --body-file {}", "ls | xargs -J % gh pr comment 1 --body x %",
                "parallel gh pr comment {} --body x ::: 1", "find . -exec gh pr comment 1 --body-file {} +",
                "find . -exec gh pr comment 1 {} \\;", "printf issue | xargs -I@ gh @ comment 1 --body x",
                "ls | xargs -n1 -I{} gh pr comment {} --body x", "parallel -m -I@ gh pr comment @ --body x ::: a b"):
        cands, blk, parsed = g.posting_bodies(cmd, WORK)
        check(48, (bool(blk) or not parsed) and "BENIGN VIEW" not in cands, "差し込む語で中身か宛先の変わる gh を通した: %r → %r" % (cmd, cands))

# 49. gh api の宛先が `graphql` の 1 語でなくても、`/graphql`・`https://api.github.com/graphql`・`x/../graphql`・`%67raphql`
# のように GraphQL へ届く綴りなら、query の mutation の本文を読む(前は REST の投稿と読み、query を本文と見ずに通した)。
# 読めない query のファイル(`-F query=@q.graphql`)は止める。mutation でない query と REST の宛先は今までどおり
def f49():
    q = "mutation{addComment(input:{subjectId:\"X\",body:\"" + BODY + "\"}){clientMutationId}}"
    for ep in ("/graphql", "https://api.github.com/graphql", "HTTPS://API.github.com/GraphQL/", "repos/o/../../graphql",
               "/%67raphql?x=1", "https://ghe.example.com/api/graphql"):
        cands, blk, parsed = g.posting_bodies("gh api %s -f query='%s'" % (ep, q), WORK)
        check(49, parsed and cands == [BODY] and not blk, "GraphQL へ届く宛先の mutation の本文を読まなかった: %r → %r %r" % (ep, blk, parsed))
    cands, blk, parsed = g.posting_bodies("gh api /graphql -F query=@missing.graphql", WORK)
    check(49, bool(blk), "読めない query のファイルの GraphQL を通した: %r %r" % (cands, parsed))
    for cmd in ("gh api /graphql -f query='{viewer{login}}'", "gh api repos/o/r/graphql-x -f title=t"):
        cands, blk, parsed = g.posting_bodies(cmd, WORK)
        check(49, parsed and not cands and not blk, "本文を持たない呼び出しを止めた: %r → %r %r" % (cmd, blk, parsed))
    cands, blk, parsed = g.posting_bodies("gh api repos/o/r/issues/1/comments -f body='" + BODY + "'", WORK)
    check(49, cands == [BODY] and not blk, "REST の本文を読まなかった: %r %r" % (cands, blk))

# 50. find の式の括弧と -exec の閉じの \; が並ぶ形(`\( … -exec true \; \) -exec gh …`・`-exec true \; \( -exec gh … \; \)`・
# `\;\(`)と、`{}` の後でない + の後ろ(`-exec echo + \; -exec gh …`。find は `{} +` の + でだけ閉じる)の -exec の gh も読む
# (前は繋ぎが切れ、本文を読まずに通した)。式の括弧か -exec が開いたまま、ほかの区切りで止まった find の後ろに gh の語が在れば
# 止める。閉じた find の後ろの本物の区切り(`&&`・改行・`;`・サブシェルの閉じ)の gh は、今までどおり別のコマンドとして読む
def f50():
    post = "gh pr comment 1 --body '" + BODY + "'"
    for cmd in ("find fd \\( -name a -exec true \\; \\) -exec %s \\;", "find fd \\( -name a -exec true \\; \\) -a -exec %s \\;",
                "find fd -name a \\( -exec true \\; \\) -exec %s \\;", "find fd -exec true \\; \\( -exec %s \\; \\)",
                "find fd -exec true \\;\\( -exec %s \\; \\)", "find fd -exec echo + \\; -exec %s \\;",
                "find fd -exec true \\; \\( -exec %s \\;"):
        cands, blk, parsed = g.posting_bodies(cmd % post, WORK)
        check(50, parsed and cands == [BODY] and not blk, "find の括弧の後ろの -exec の gh の本文を読まなかった: %r → %r %r" % (cmd, blk, parsed))
    for cmd in ("find fd \\( -name a && " + post, "find fd -exec true | " + post):
        cands, blk, parsed = g.posting_bodies(cmd, WORK)
        check(50, not parsed or bool(blk), "読み切れない find の後ろの gh を通した: %r → %r" % (cmd, cands))
    for cmd in ("find . -name x -exec rm {} \\; && " + post, "find . -name x -exec rm {} \\;\n" + post,
                "(find . -exec true \\;) && " + post, "find . \\( -name a \\) ; (" + post + ")",
                "find . -exec true {} + ; " + post, "x=$(find . -exec basename {} \\;) && " + post):
        cands, blk, parsed = g.posting_bodies(cmd, WORK)
        check(50, parsed and cands == [BODY] and not blk, "閉じた find の後ろの gh を読まなかった: %r → %r %r" % (cmd, blk, parsed))

# 51. gh api の gist の作成・書き換え(`gists`・`gists/<id>`)の files[<名前>][content] は本文として読む(前は body のフィールド
# だけを見て、公開の gist に出す中身を読まずに通した)。`-F files[…][content]=@ファイル` は、ほかの @ファイルのフィールドと同じに
# 読み、読めなければ止める。gist でない宛先の同じ名前のフィールドは、今までどおり本文と見ない
def f51():
    with open(os.path.join(WORK, "g51.md"), "w") as f:
        f.write(BODY)
    for cmd in ("gh api gists -f 'files[notes.md][content]=" + BODY + "' -F public=true",
                "gh api /gists/abc -X PATCH -f 'files[n.md][content]=" + BODY + "'", "gh api gists -F 'files[n.md][content]=@g51.md'"):
        cands, blk, parsed = g.posting_bodies(cmd, WORK)
        check(51, parsed and cands == [BODY] and not blk, "gist のファイルの中身を読まなかった: %r → %r %r" % (cmd[:50], blk, parsed))
    cands, blk, parsed = g.posting_bodies("gh api gists -F 'files[n.md][content]=@missing.md' -F public=true", WORK)
    check(51, bool(blk), "読めない gist のファイルの中身を通した: %r %r" % (cands, parsed))
    cands, blk, parsed = g.posting_bodies("gh api repos/o/r/dispatches -f 'files[a][content]=x'", WORK)
    check(51, parsed and not cands and not blk, "gist でない宛先のフィールドを本文と読んだ: %r %r" % (cands, blk))

# 52. xargs の -I に -n・-L を重ねた形(何語になるか決まらない側)でも、語の途中の印を替える(macOS の xargs は語の途中にも差し込み、
# `echo rev | xargs -n1 -I v gh pr view 1 -c -b x` は gh pr review を走らせる。前は語の全体が印のときだけ替え、読むだけの
# pr view と見て通した)。印の無い読むだけの形は今までどおり通す
def f52():
    for cmd in ("echo rev | xargs -n1 -I v gh pr view 1 -c -b x", "echo r | xargs -L1 -I e gh pr view 1 -b x"):
        cands, blk, parsed = g.posting_bodies(cmd, WORK)
        check(52, bool(blk) or not parsed, "語の途中の印で投稿に変わる gh を通した: %r → %r" % (cmd, cands))
    for cmd in ("ls | xargs -n1 -I{} gh pr view {}", "ls | xargs -I a -I b gh pr view 1"):
        cands, blk, parsed = g.posting_bodies(cmd, WORK)
        check(52, parsed and not cands and not blk, "読むだけの gh を止めた: %r → %r %r" % (cmd, blk, parsed))

# 53. re.split・re.sub・re.subn の maxsplit・count・flags を位置で渡さない(Python 3.13 から DeprecationWarning が出て、フックの
# 標準エラーに毎回残る。前は gh api の宛先のパスを割る所で位置で渡していた)。動かして警告が出ないことと、書き方そのものを見る
def f53():
    import ast
    import warnings
    with warnings.catch_warnings():
        warnings.simplefilter("error", DeprecationWarning)
        segs = g.api_endpoint_path("https://api.github.com/repos/o/r/issues?per_page=1")[0]
    check(53, segs == ["repos", "o", "r", "issues"], "宛先のパスを読み違えた: %r" % segs)
    hooks = os.path.join(ROOT, "gates", "hooks")
    for path in (GATE, os.path.join(hooks, "dest-gate.py"), os.path.join(hooks, "search-gate.py")):
        with open(path, encoding="utf-8") as f:
            tree = ast.parse(f.read())
        for node in ast.walk(tree):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name)
                    and node.func.value.id == "re" and node.func.attr in ("split", "sub", "subn")
                    and len(node.args) > (2 if node.func.attr == "split" else 3)):
                check(53, False, "%s の %d 行で re.%s の数を位置で渡した" % (os.path.basename(path), node.lineno, node.func.attr))

# 54. GitHub Enterprise Server の REST の頭(`https://<host>/api/v3/`)を付けた gist の宛先も gist と見て、files[<名前>][content] を
# 本文として読む(前は頭の api・v3 を gist の語と比べ、中身を読まずに通した)。gist でない GHE の宛先は今までどおり本文と見ない
def f54():
    for cmd in ("gh api https://ghe.example.com/api/v3/gists -f 'files[a.md][content]=" + BODY + "'",
                "gh api /api/v3/gists/abc -X PATCH -f 'files[a.md][content]=" + BODY + "'"):
        cands, blk, parsed = g.posting_bodies(cmd, WORK)
        check(54, parsed and cands == [BODY] and not blk, "GHE の gist のファイルの中身を読まなかった: %r → %r %r" % (cmd[:60], blk, parsed))
    cands, blk, parsed = g.posting_bodies("gh api https://ghe.example.com/api/v3/repos/o/r/dispatches -f 'files[a][content]=x'", WORK)
    check(54, parsed and not cands and not blk, "gist でない GHE の宛先のフィールドを本文と読んだ: %r %r" % (cands, blk))

# 55. xargs -I・find -exec が gh api の宛先のパスに差し込む語は、`graphql`・`gists`・`../../graphql` になって宛先の種類を変えうるので、
# 埋めた後に種類が変わると本文になるフィールド(graphql の query・gist の files[…][content])を運ぶときと、埋める前のパスで graphql か
# gist と決めたときは止める(前は埋める前のパスで REST と見て、mutation・gist の中身を読まずに通した)。語の途中の印の読むだけの宛先と、
# REST の body のフィールドは今までどおり
def f55():
    mutation = "-f query='mutation{addComment(input:{subjectId:\"X\",body:\"" + BODY + "\"}){clientMutationId}}'"
    for cmd in ("echo graphql | xargs -I{} gh api /{} " + mutation,
                "echo graphql | xargs -I{} gh api https://api.github.com/{} " + mutation,
                "echo x | xargs -I{} gh api repos/o/r/issues/{}/comments " + mutation,
                "echo gists | xargs -I{} gh api /{} -f 'files[a][content]=" + BODY + "'",
                "echo x | xargs -I{} gh api https://ghe.example.com/api/v3/{} -F 'files[a][content]=@x.md'",
                "echo x | xargs -I{} gh api graphql/{}/.. -f body=hi",
                "find . -name graphql -exec gh api {} " + mutation + " \\;"):
        cands, blk, parsed = g.posting_bodies(cmd, WORK)
        check(55, not parsed or bool(blk), "宛先のパスに差し込む語の gh api を通した: %r → %r %r" % (cmd[:70], cands, blk))
    cands, blk, parsed = g.posting_bodies("ls | xargs -I{} gh api repos/o/r/pulls/{}/comments", WORK)
    check(55, parsed and not cands and not blk, "読むだけの gh api を止めた: %r %r" % (cands, blk))
    cands, blk, parsed = g.posting_bodies("ls | xargs -I{} gh api repos/o/r/issues/{}/comments -f body='" + BODY + "'", WORK)
    check(55, parsed and cands == [BODY] and not blk, "REST の body のフィールドの読み方が変わった: %r %r" % (cands, blk))
    cands, blk, parsed = g.posting_bodies("ls | xargs -I{} gh api 'search/issues?q={}' -f query=x", WORK)
    check(55, parsed and not blk, "? の後ろの差し込む語を宛先のパスと見た: %r" % (blk,))

# 56. 字句解析は引用した区切りの字(`')'`・`'\;'`)を本物の区切りと同じ語にするので、find の -name などの値の所と -exec の中の括弧と、
# サブシェルの中でない find の後ろの ) は語として繋ぎ、後ろの -exec の gh の本文を読む(前は ) をサブシェルの閉じと読んで繋ぎを止め、
# gh を見落として通した)。値の所の ( で式が開いたと読んで止めすぎない。サブシェルの本当の閉じの後ろの gh は今までどおり別に読む
def f56():
    post = "gh pr comment 1 --body '" + BODY + "'"
    for cmd in (r"find fd -name ')' -exec %s \;", r"find fd -name ';' -exec %s \;", r"find fd -name x -exec echo \) \; -exec %s \;",
                r"find fd -name x -exec grep -q ')' {} \; -exec %s \;", r"find fd -exec echo '(' \; -exec %s \;",
                r"find fd ')' -exec %s \;", r"(find . -name ')' -exec %s \;)",
                r"case $x in a) find . -name ')' -exec %s \; ;; esac"):
        cands, blk, parsed = g.posting_bodies(cmd % post, WORK)
        check(56, parsed and cands == [BODY] and not blk, "引用した区切りの字の後ろの -exec の gh の本文を読まなかった: %r → %r %r" % (cmd, blk, parsed))
    for cmd in ("find . -name '(' -print; " + post, r"(find . -name x -exec true \;) && " + post,
                r"find . \( -name a -o -name b \) -print && " + post):
        cands, blk, parsed = g.posting_bodies(cmd, WORK)
        check(56, parsed and cands == [BODY] and not blk, "find の後ろの gh を読まなかったか止めた: %r → %r %r" % (cmd, blk, parsed))

# 57. find の -exec か式の括弧が開いたまま区切りが来て、後ろの gh を読み切れないときは、止める文に「find の -exec か括弧が
# 閉じていない」と書く(前は引用が正しいのに「引用が閉じていない等」と書き、どこを直せばよいか分からなかった)。置換の中の find も
# 同じ訳を返す。引用の閉じ忘れは今までどおりの文
def f57():
    for cmd in ("find . -exec cat {} && gh pr comment 1 --body hi", "x=$(find . -exec cat {} && gh pr comment 1 --body hi)",
                r"find . \( -name a && gh pr comment 1 --body hi"):
        a = g.analyze(cmd, WORK)
        check(57, not a.parsed and a.why == g.FIND_OPEN_WHY, "find の閉じ忘れの訳を返さなかった: %r → %r" % (cmd, a.why))
        _, out = run_main(cmd, WORK)
        check(57, g.FIND_OPEN_WHY in out, "止める文に find の訳が無い: %r → %r" % (cmd, out[:200]))
    _, out = run_main("gh pr comment 1 --body 'hi", WORK)
    check(57, "deny" in out and g.FIND_OPEN_WHY not in out, "引用の閉じ忘れの止める文が変わった: %r" % out[:200])

# 58. 埋める前のパスが gist の gh api は、宛先のパスに差し込む語が在っても一律に止めない(55 の直しの止めすぎ)。読むだけの形
# (`… | xargs -I{} gh api gists/{}`・--jq・-X DELETE)は通し、body のフィールドは読む。gist のファイルの中身と query は今までどおり止め、
# 埋める前のパスが graphql の物も止める
def f58():
    for cmd in ("gh gist list | awk '{print $1}' | xargs -I{} gh api gists/{}",
                "gh gist list | awk '{print $1}' | xargs -I{} gh api gists/{} --jq '.files[].raw_url'",
                "gh gist list | awk '{print $1}' | xargs -I{} gh api -X DELETE gists/{}"):
        cands, blk, parsed = g.posting_bodies(cmd, WORK)
        check(58, parsed and not cands and not blk, "読むだけの gist の gh api を止めた: %r → %r" % (cmd[:70], blk))
    for cmd in ("gh gist list | awk '{print $1}' | xargs -I{} gh api gists/{}/comments -f body='" + BODY + "'",
                "echo x | xargs -I{} gh api gists/{} -f body='" + BODY + "'"):
        cands, blk, parsed = g.posting_bodies(cmd, WORK)
        check(58, parsed and cands == [BODY] and not blk, "gist の宛先の body のフィールドを読まなかった: %r → %r %r" % (cmd[:70], cands, blk))
    for cmd in ("echo x | xargs -I{} gh api gists/{} -f 'files[a][content]=" + BODY + "'",
                "echo x | xargs -I{} gh api gists/{} -f query='mutation{x}'",
                "echo x | xargs -I{} gh api graphql/{}/.. --input q.json", "echo x | xargs -I{} gh api graphql/{}/.."):
        cands, blk, parsed = g.posting_bodies(cmd, WORK)
        check(58, not parsed or bool(blk), "宛先のパスに差し込む語の gh api を通した: %r → %r %r" % (cmd[:70], cands, blk))

# 59. gh gist edit の id の後ろの位置引数(- は標準入力)と -a は、gist のファイルの中身を置き換える・足すので、gist create の位置引数と
# 同じに読む(- はヒアドキュメントを読み、手元のファイルは止める。前はどちらも読まず、中身を読まずに通した)。位置引数も -a も無い形
# (エディタで直す)と、-d(説明)・-r(ファイルを消す)・-f(直すファイルを選ぶ)だけの形は、今までどおり本文と見ない
def f59():
    for cmd in ("gh gist edit abc --filename a.md x.md", "gh gist edit abc -f a.md x.md", "gh gist edit abc x.md",
                "gh gist edit abc -a new.md", "gh gist edit --add=new.md", "gh gist edit abc --filename=a.md -- x.md"):
        cands, blk, parsed = g.posting_bodies(cmd, WORK)
        check(59, parsed and bool(blk), "gh gist edit の手元のファイルを通した: %r → %r %r" % (cmd, cands, parsed))
    for cmd in ("gh gist edit abc -f a.md - <<'E'\n%s\nE", "gh gist edit abc -fa.md - <<'E'\n%s\nE",
                "gh gist edit abc -a new.md - <<'E'\n%s\nE"):
        cands, blk, parsed = g.posting_bodies(cmd % BODY, WORK)
        check(59, parsed and cands == [BODY] and not blk, "gh gist edit の標準入力の中身を読まなかった: %r → %r %r" % (cmd, cands, blk))
    for cmd in ("gh gist edit abc", "gh gist edit", "gh gist edit abc -d '" + BODY + "'", "gh gist edit abc -r a.md",
                "gh gist edit abc -f a.md"):
        cands, blk, parsed = g.posting_bodies(cmd, WORK)
        check(59, parsed and not cands and not blk, "本文を運ばない gh gist edit を止めたか読んだ: %r → %r %r" % (cmd[:60], cands, blk))

# 60. xargs・find -exec が足す語・差し込む語は、本文・コメント・メッセージの旗を持たない gh のサブコマンド(gist view・list、run rerun・
# cancel・watch・download、workflow view・list、cache list・delete、pr checkout)では投稿にならないので止めない(前は FED_READ_SUBS に
# 無く、`gh gist list | cut -f1 | xargs -I{} gh gist view {} --raw` まで止めていた)。本文を運びうる pr edit・issue close などは今までどおり止める
def f60():
    for cmd in ("gh gist list | cut -f1 | xargs -I{} gh gist view {} --raw", "gh gist list | cut -f1 | xargs -n1 gh gist view",
                "echo 1 | xargs -I{} gh run rerun {} --failed", "echo 1 | xargs -n1 gh run cancel", "echo 1 | xargs -n1 gh run watch",
                "echo 1 | xargs -I{} gh run download {}", "echo ci.yml | xargs -I{} gh workflow view {}",
                "echo x | xargs gh workflow list", "echo x | xargs gh gist list", "echo x | xargs gh cache list",
                "echo 1 | xargs -I{} gh cache delete {}", "echo 1 | xargs -I{} gh pr checkout {}",
                r"find . -name '*.id' -exec gh gist view {} \;"):
        cands, blk, parsed = g.posting_bodies(cmd, WORK)
        check(60, parsed and not cands and not blk, "本文の旗を持たない gh の xargs を止めた: %r → %r %r" % (cmd, blk, parsed))
    for cmd in ("echo 1 | xargs gh pr edit --body x", "echo 1 | xargs -I{} gh pr edit {} --add-label x", "echo 1 | xargs -n1 gh issue close",
                "echo 1 | xargs -n1 gh pr merge", "echo 1 | xargs -I{} gh issue edit {} --add-label x",
                "echo 1 | xargs -I{} gh gist edit {} -", "echo 1 | xargs -I{} gh gist create {}"):
        cands, blk, parsed = g.posting_bodies(cmd, WORK)
        check(60, not parsed or bool(blk), "本文を運びうる gh の xargs を通した: %r → %r %r" % (cmd, cands, parsed))

# 61. リダイレクトの行き先のプロセス置換(`< <(…)`・`> >(…)`)の中は別のコマンドとして読む(前は `<(` ごと読み飛ばして中の語を
# 外のコマンドの引数にし、`cat < <(gh pr comment 1 --body-file x.md)` の gh を見落として通した)。--body-file <(…) と、
# 標準入力をプロセス置換から渡す形は今までどおり止める
def f61():
    with open(os.path.join(WORK, "x.md"), "w", encoding="utf-8") as f:
        f.write(BODY)
    for cmd in ("cat < <(gh pr comment 1 --body-file x.md)", "cat < <(gh pr comment 1 --body '%s')" % BODY):
        cands, blk, parsed = g.posting_bodies(cmd, WORK)
        check(61, parsed and cands == [BODY] and not blk, "プロセス置換の中の gh を読まなかった: %r → %r %r" % (cmd[:60], cands, blk))
    for cmd in ("gh pr comment 1 --body-file <(cat x.md)", "gh pr comment 1 --body-file - < <(cat x.md)",
                "echo x > >(gh pr comment 1 --body-file -)"):
        cands, blk, parsed = g.posting_bodies(cmd, WORK)
        check(61, not parsed or bool(blk), "プロセス置換の本文を通した: %r → %r %r" % (cmd, cands, parsed))
    cmds = g.split_commands(g.tokenize("mapfile -t a < <(cd src && ls); gh pr view 1"))
    check(61, [c.args for c in cmds] == [["mapfile", "-t", "a"], ["cd", "src"], ["ls"], ["gh", "pr", "view", "1"]]
          and cmds[0].redirects == [("<", "<(")] and cmds[1].depth == 1 and cmds[3].depth == 0,
          "プロセス置換の中を外のコマンドに繋いだ: %r" % [(c.args, c.redirects, c.depth) for c in cmds])

# 62. gh に組み込みのサブコマンドの別名(`pr new`・`issue new`・`release new`・`gist new`・`ls`・`pr co`)は本当の名前と同じに読む
# (前は短い本文の旗 -b・-n・-F を本文と見ず、`gh gist new a.md` も投稿と見ずに通した)。新しい PR の題も別名の後ろから読む
def f62():
    with open(os.path.join(WORK, "a.md"), "w", encoding="utf-8") as f:
        f.write(BODY)
    pairs = (("gh pr new -t T -b '%s'", "gh pr create -t T -b '%s'"), ("gh issue new -t T -b '%s'", "gh issue create -t T -b '%s'"),
             ("gh release new v1 -n '%s'", "gh release create v1 -n '%s'"), ("gh pr new -F a.md", "gh pr create -F a.md"),
             ("gh issue new -F a.md", "gh issue create -F a.md"), ("gh release new v1 -F a.md", "gh release create v1 -F a.md"),
             ("gh gist new a.md", "gh gist create a.md"), ("gh gist new - <<'E'\n%s\nE", "gh gist create - <<'E'\n%s\nE"),
             ("gh -R o/r issue new -b '%s'", "gh -R o/r issue create -b '%s'"))
    for alias, real in pairs:
        got = [g.posting_bodies(c % BODY if "%s" in c else c, WORK) for c in (alias, real)]
        check(62, got[0] == got[1] and (got[0][0] or got[0][1]), "別名を本当の名前と違えて読んだ: %r → %r / %r" % (alias, got[0], got[1]))
    for words, real in ((["pr", "new"], ("pr", "create")), (["pr", "ls"], ("pr", "list")), (["pr", "co", "3"], ("pr", "checkout")),
                        (["gist", "ls"], ("gist", "list")), (["repo", "new", "x"], ("repo", "create")), (["-R", "o/r", "run", "ls"], ("run", "list")),
                        (["api", "new"], ("api", "new"))):
        check(62, g.subcommand(words) == real, "別名を本当の名前に直さなかった: %r → %r" % (words, g.subcommand(words)))
    check(62, g.create_flags(["pr", "new", "-t", "TITLE_MARK"], ("pr", "create")).get("--title") == "TITLE_MARK",
          "別名の新しい PR の題を読まなかった")
    cands, blk, parsed = g.posting_bodies("echo 1 | xargs -I{} gh pr co {}", WORK)
    check(62, parsed and not cands and not blk, "別名の pr co を xargs で止めた: %r" % blk)

# 63. gh gist create はファイルの名前が無ければ標準入力を読む(- と同じ)ので、名前の無い形は - と同じに読む(パイプ・< ・<<< の標準入力は
# 止め、ヒアドキュメントは読む)。名前が在れば - の無い限り標準入力を読まないので、ヒアドキュメントを名前の代わりに読まない
def f63():
    for cmd in ("cat a.md | gh gist create", "cat <<'E' | gh gist create -f notes.md -d desc\n%s\nE" % BODY, "gh gist create < a.md",
                "gh gist create <<< '%s'" % BODY, "gh gist create -d '%s'" % BODY, "gh gist new -p < a.md",
                "gh gist create zz-no-such.md <<'E'\nshort\nE"):
        cands, blk, parsed = g.posting_bodies(cmd, WORK)
        check(63, not parsed or bool(blk), "gh gist create の標準入力か名前のファイルを読まずに通した: %r → %r %r" % (cmd[:60], cands, parsed))
    for cmd in ("gh gist create <<'E'\n%s\nE", "gh gist create -f notes.md -d desc <<'E'\n%s\nE", "gh gist create - <<'E'\n%s\nE"):
        cands, blk, parsed = g.posting_bodies(cmd % BODY, WORK)
        check(63, parsed and cands == [BODY] and not blk, "gh gist create のヒアドキュメントを読まなかった: %r → %r %r" % (cmd, cands, blk))

TESTS = {n: fn for n, fn in enumerate((f1, f2, f3, f4, f5, f6, f7, f8, f9, f10, f11, f12, f13, f14, f15, f16, f17, f18, f19, f20), 1)}
TESTS.update({21: f21, 22: f22, 23: f23, 24: f24, 25: f25, 26: f26, 27: f27, 28: f28, 30: f30, 31: f31, 32: f32, 33: f33, 34: f34, 35: f35, 36: f36, 37: f37, 38: f38, 39: f39, 40: f40, 41: f41, 42: f42, 43: f43, 44: f44, 45: f45, 46: f46, 47: f47, 48: f48, 49: f49, 50: f50, 51: f51, 52: f52, 53: f53, 54: f54, 55: f55, 56: f56, 57: f57, 58: f58, 59: f59, 60: f60, 61: f61, 62: f62, 63: f63})
for n, fn in sorted(TESTS.items()):
    guarded(n, fn)

shutil.rmtree(WORK, ignore_errors=True)
if FAILED:
    print("FIX_FAILED")
    for line in FAILED:
        print(line)
    sys.exit(1)
print("FIX_OK")
