#!/usr/bin/env python3
"""coldread-gate.py の正しさの穴 13 件(頼み cae1e2 のレビューで再現した物)の回帰。tests/coldread-table-case.py から呼ぶ。

1 件ずつ、前の版では赤になり直した版では緑になる形で書く。穴の番号は頼みの番号のまま。読む本体は引数(無ければ
gates/hooks/coldread-gate.py)で、前の版の写しを渡すと全部の穴が赤になることを確かめられる。14・15 は 1〜13 の直し
(commit 8eb61ffd)が持ち込んだ止めすぎで、8eb61ffd の版を渡すと赤になる。16・17 は 14・15 の直し(commit 0bd1e0a2)の
後に見つけた素通しで、0bd1e0a2 の版を渡すと赤になる。21〜33 は 2 度目のレビュー(頼み cae1e2)の F1〜F13 で、
番号から 20 を引くとレビューの番号になる(29 はレビューの F9 で、探しのゲートの側の直しなので tests/searchgate-suite.py に置く)。
34 は 21〜28 を直す間に見つけた素通しで、commit 69816318 の版を渡すと赤になる。35 以降は 3 度目のレビュー(頼み cae1e2)の
直しで、commit 812accd7 の版を渡すと赤になる。
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


TESTS = {n: fn for n, fn in enumerate((f1, f2, f3, f4, f5, f6, f7, f8, f9, f10, f11, f12, f13, f14, f15, f16, f17, f18, f19, f20), 1)}
TESTS.update({21: f21, 22: f22, 23: f23, 24: f24, 25: f25, 26: f26, 27: f27, 28: f28, 30: f30, 31: f31, 32: f32, 33: f33, 34: f34, 35: f35, 36: f36, 37: f37, 38: f38, 39: f39})
for n, fn in sorted(TESTS.items()):
    guarded(n, fn)

shutil.rmtree(WORK, ignore_errors=True)
if FAILED:
    print("FIX_FAILED")
    for line in FAILED:
        print(line)
    sys.exit(1)
print("FIX_OK")
