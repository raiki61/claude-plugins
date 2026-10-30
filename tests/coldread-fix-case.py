#!/usr/bin/env python3
"""coldread-gate.py の正しさの穴 13 件(頼み cae1e2 のレビューで再現した物)の回帰。tests/coldread-table-case.py から呼ぶ。

1 件ずつ、前の版では赤になり直した版では緑になる形で書く。穴の番号は頼みの番号のまま。読む本体は引数(無ければ
gates/hooks/coldread-gate.py)で、前の版の写しを渡すと全部の穴が赤になることを確かめられる。
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


for n, fn in enumerate((f1, f2, f3, f4, f5, f6, f7, f8, f9, f10, f11, f12, f13), 1):
    guarded(n, fn)

shutil.rmtree(WORK, ignore_errors=True)
if FAILED:
    print("FIX_FAILED")
    for line in FAILED:
        print(line)
    sys.exit(1)
print("FIX_OK")
