#!/usr/bin/env python3
"""判定表に載っているべき項目が実際に効いているかを確かめる。run.sh から呼ぶ。

**期待値は判定表から読まず、ここに直接書く。** 表を走査して表と突き合わせる形は、
表からメンバーが落ちても反復回数が減るだけで赤くならない(実測で確認した恒真)。
下の一覧は gh 2.96.0 の `gh <group> <sub> --help` を走査して作った実測値で、
gh の側が変わったときはここを直す。

**リテラルで持つだけでは網羅は保証されない。** 手で選んだ標本は実装の表より小さくなり、
表からメンバーを消しても緑のままになる(5 巡目に実測。`-F` は 14 組中 7 組が未検査だった)。
そこで、ここのリテラルから作った鍵集合が実装の表の鍵集合と**一致する**ことを検査する
(片側だけ編集すると赤い)。倒れ先(deny の理由)も同じ形で、実装の文言集合と突合する。
"""
import ast
import importlib.util
import io
import os
import sys

gate_path = os.path.join(os.path.dirname(__file__), "..", "gates", "hooks", "coldread-gate.py")
spec = importlib.util.spec_from_file_location("coldread_gate", gate_path)
gate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gate)

BODY = "これは検査対象の本文です。" * 20
PAD = "x" * 420
HEREDOC = "- <<'EOF'\n%s\n%s\nEOF" % (BODY, PAD)
TEXT = "'%s %s'" % (BODY, PAD)

# 本文を運ぶ旗 1 メンバー = ここ 1 行。鍵は (旗, サブコマンド) で、長い旗は綴りだけで
# 本文と見なすのでサブコマンドを None にする。下でこの鍵集合を実装の表と突き合わせる。
FLAG_CASES = [
    (("--body", None), "gh issue comment 1 --body %s" % TEXT),
    (("--notes", None), "gh release create v1 --notes %s" % TEXT),
    (("--comment", None), "gh issue close 1 --comment %s" % TEXT),
    (("--readme", None), "gh project edit 1 --readme %s" % TEXT),
    (("--body-file", None), "gh issue comment 1 --body-file %s" % HEREDOC),
    (("--notes-file", None), "gh release create v1 --notes-file %s" % HEREDOC),
    (("-b", ("issue", "comment")), "gh issue comment 1 -b %s" % TEXT),
    (("-b", ("issue", "create")), "gh issue create -b %s" % TEXT),
    (("-b", ("issue", "edit")), "gh issue edit 1 -b %s" % TEXT),
    (("-b", ("pr", "comment")), "gh pr comment 1 -b %s" % TEXT),
    (("-b", ("pr", "create")), "gh pr create -b %s" % TEXT),
    (("-b", ("pr", "edit")), "gh pr edit 1 -b %s" % TEXT),
    (("-b", ("pr", "merge")), "gh pr merge 1 -b %s" % TEXT),
    (("-b", ("pr", "revert")), "gh pr revert 1 -b %s" % TEXT),
    (("-b", ("pr", "review")), "gh pr review 1 -b %s" % TEXT),
    (("-b", ("discussion", "comment")), "gh discussion comment 1 -b %s" % TEXT),
    (("-b", ("discussion", "create")), "gh discussion create -b %s" % TEXT),
    (("-b", ("discussion", "edit")), "gh discussion edit 1 -b %s" % TEXT),
    (("-c", ("issue", "close")), "gh issue close 1 -c %s" % TEXT),
    (("-c", ("issue", "reopen")), "gh issue reopen 1 -c %s" % TEXT),
    (("-c", ("pr", "close")), "gh pr close 1 -c %s" % TEXT),
    (("-c", ("pr", "reopen")), "gh pr reopen 1 -c %s" % TEXT),
    (("-n", ("release", "create")), "gh release create v1 -n %s" % TEXT),
    (("-n", ("release", "edit")), "gh release edit v1 -n %s" % TEXT),
    (("-F", ("issue", "comment")), "gh issue comment 1 -F %s" % HEREDOC),
    (("-F", ("issue", "create")), "gh issue create -F %s" % HEREDOC),
    (("-F", ("issue", "edit")), "gh issue edit 1 -F %s" % HEREDOC),
    (("-F", ("pr", "comment")), "gh pr comment 1 -F %s" % HEREDOC),
    (("-F", ("pr", "create")), "gh pr create -F %s" % HEREDOC),
    (("-F", ("pr", "edit")), "gh pr edit 1 -F %s" % HEREDOC),
    (("-F", ("pr", "merge")), "gh pr merge 1 -F %s" % HEREDOC),
    (("-F", ("pr", "revert")), "gh pr revert 1 -F %s" % HEREDOC),
    (("-F", ("pr", "review")), "gh pr review 1 -F %s" % HEREDOC),
    (("-F", ("discussion", "comment")), "gh discussion comment 1 -F %s" % HEREDOC),
    (("-F", ("discussion", "create")), "gh discussion create -F %s" % HEREDOC),
    (("-F", ("discussion", "edit")), "gh discussion edit 1 -F %s" % HEREDOC),
    (("-F", ("release", "create")), "gh release create v1 -F %s" % HEREDOC),
    (("-F", ("release", "edit")), "gh release edit v1 -F %s" % HEREDOC),
]

# 旗の表に載っていない捕捉形(gh 呼び出しそのものの見つけ方)。表と 1 対 1 でないので
# 鍵集合の突合はせず、形ごとに 1 件ずつ置く。
POSTING = [
    ("gh gist create %s" % HEREDOC, "gist create -"),
    # 前置ラッパー越し
    ("env gh issue comment 1 --body %s" % TEXT, "env 前置"),
    ("command gh issue comment 1 --body %s" % TEXT, "command 前置"),
    ("exec gh issue comment 1 --body %s" % TEXT, "exec 前置"),
    ("nohup gh issue comment 1 --body %s" % TEXT, "nohup 前置"),
    ("/usr/local/bin/gh issue comment 1 --body %s" % TEXT, "絶対パス起動"),
    ("x1=1 gh issue comment 1 --body %s" % TEXT, "環境変数前置"),
    # 値を取る global 旗(空白・= ・密着の 3 形)
    ("gh -R o/r issue comment 1 -b %s" % TEXT, "-R 空白"),
    ("gh --repo o/r issue comment 1 -b %s" % TEXT, "--repo 空白"),
    ("gh --repo=o/r issue comment 1 -b %s" % TEXT, "--repo= 融合"),
    ("gh -Ro/r issue comment 1 -b %s" % TEXT, "-R 密着"),
    ("gh -X POST api repos/o/r/issues/1/comments -f body=%s" % TEXT, "-X 空白"),
    ("gh --method=POST api repos/o/r/issues/1/comments -f body=%s" % TEXT, "--method= 融合"),
    ("gh -H X-F:b api repos/o/r/issues/1/comments -f body=%s" % TEXT, "-H 空白"),
    ("gh --header X-F:b api repos/o/r/issues/1/comments -f body=%s" % TEXT, "--header 空白"),
    ("gh -HX-F:b api repos/o/r/issues/1/comments -f body=%s" % TEXT, "-H 密着"),
    # リダイレクトを挟んでも本文を見失わない
    ("gh issue comment 1 --body %s > /dev/null" % TEXT, "> 後置"),
    ("gh issue comment 1 --body %s >> /tmp/log" % TEXT, ">> 後置"),
    ("gh issue comment 1 --body %s 2>&1" % TEXT, "2>&1 後置"),
    ("gh issue comment 1 --body >&2 %s" % TEXT, ">& 挟み"),
    ("gh issue comment 1 --body <&3 %s" % TEXT, "<& 挟み"),
    ("gh issue comment 1 --body &> /dev/null %s" % TEXT, "&> 挟み"),
    ("gh issue comment 1 --body >| /tmp/f %s" % TEXT, ">| 挟み"),
    ("gh issue comment 1 --body < /tmp/in %s" % TEXT, "< 挟み"),
]

# 長い旗でも本文でない例外 1 メンバー = ここ 1 行(鍵集合を実装と突合する)
NOT_BODY_CASES = [
    (("--comment", ("pr", "review")), "gh pr review 1 --comment %s" % TEXT),
]
# 投稿でないサブコマンド 1 メンバー = ここ 1 行(同上)
NON_POSTING_CASES = [
    (("secret", "set"), "gh secret set K --body %s" % TEXT),
    (("variable", "set"), "gh variable set V --body %s" % TEXT),
]
# 前置ラッパー 1 メンバー = ここ 1 行(同上。本文の検出は POSTING 側で見る)
WRAPPER_CASES = [
    ("env", "env gh issue comment 1 --body %s" % TEXT),
    ("command", "command gh issue comment 1 --body %s" % TEXT),
    ("exec", "exec gh issue comment 1 --body %s" % TEXT),
    ("nohup", "nohup gh issue comment 1 --body %s" % TEXT),
]
# 値を取る global 旗 1 メンバー = ここ 1 行(同上)
GLOBAL_FLAG_CASES = [
    ("-R", "gh -R o/r issue comment 1 -b %s" % TEXT),
    ("--repo", "gh --repo o/r issue comment 1 -b %s" % TEXT),
    ("-H", "gh -H X-F:b api repos/o/r/issues/1/comments -f body=%s" % TEXT),
    ("--header", "gh --header X-F:b api repos/o/r/issues/1/comments -f body=%s" % TEXT),
    ("-X", "gh -X POST api repos/o/r/issues/1/comments -f body=%s" % TEXT),
    ("--method", "gh --method POST api repos/o/r/issues/1/comments -f body=%s" % TEXT),
]

# 投稿でない形(値を読み役へ送らない・止めない)
QUIET = [
    ("gh pr checkout 1 -b feature/%s" % ("x" * 300), "pr checkout -b はブランチ名"),
    ("gh repo sync -b main # %s" % PAD, "repo sync -b はブランチ名"),
    ("gh issue develop 5 -n branch/%s" % ("x" * 300), "issue develop -n はブランチ名"),
    ("gh issue view 12 -c # %s %s" % (PAD, BODY), "issue view -c は --comments"),
    ("gh pr status -c # %s %s" % (PAD, BODY), "pr status -c は --conflict-status"),
    ("gh run download 5 -n name/%s" % ("x" * 300), "run download -n は --name"),
    ("gh workflow run w.yml -F key=%s" % TEXT, "workflow run -F は field"),
    ("gh pr view 12 --json state # %s" % PAD, "読み取り"),
    ("gh api graphql -f query='query { repository { name } }' # %s" % PAD, "graphql の読み取り"),
]

# 倒れ先 1 つ = ここ 1 行。実装の blocked.append の文言集合と一致することを下で検査する。
# 「本文旗の値を判定できない」は表に知らない種別が入ったときの唯一の倒れ先なので、
# 検査用の旗を一時的に表へ挿して発火させる(下の PATCH_FLAG)。
PATCH_FLAG = "--zz-test-unknown-kind"
BLOCKED_CASES = [
    ("サブコマンドを特定できない", "gh --unknown-flag=x issue comment 1 -b %s" % TEXT),
    ("別プロセスからの stdin 渡し", "cat /tmp/b.md | gh issue comment 1 --body-file - # %s" % PAD),
    # --input - は別分岐。理由まで見ないと、末尾のガード(本文旗の値を判定できない)が
    # 肩代わりして deny になるので、分岐を消しても気付けない(5 巡目に変異で実測)
    ("別プロセスからの stdin 渡し",
     "cat /tmp/p.json | gh api repos/o/r/issues/1/comments --input - # %s" % PAD),
    ("実ファイル指定", "gh issue comment 1 --body-file /tmp/real.md # %s" % PAD),
    ("変数・コマンド置換渡し", 'gh issue comment 1 --body "$BODY" # %s' % PAD),
    ("JSON として読めない --input",
     "gh api repos/o/r/issues/1/comments --input - <<'EOF'\n{\"body\": ここは JSON でない %s\nEOF" % PAD),
    ("JSON の本文の位置を特定できない",
     "gh api -X PUT /repos/o/r/actions/secrets/K --input - <<'EOF'\n{\"encrypted_value\": \"%s\"}\nEOF" % PAD),
    ("graphql mutation の本文を取り出せない",
     "gh api graphql -f query='mutation { addComment(input:{body: \"%s\"}) }'" % PAD),
    ("本文旗の値を判定できない", "gh issue comment 1 %s %s" % (PATCH_FLAG, TEXT)),
]

failures = []


def bodies_of(command):
    candidates, blocked, parsed = gate.posting_bodies(command)
    return [c for c in candidates if len(c.strip()) >= 200], blocked, parsed


def compare_keys(what, expected, actual):
    missing = sorted(map(str, expected - actual))
    extra = sorted(map(str, actual - expected))
    if missing:
        failures.append("%s: この検査に在って実装に無い — %s" % (what, missing))
    if extra:
        failures.append("%s: 実装に在ってこの検査に無い(未検査のメンバー) — %s" % (what, extra))


# 鍵集合の突合。片側だけ編集すると赤くなるので、表を増やしたら検査も増える。
impl_flag_keys = {(flag, None) for flag in gate.LONG_TEXT_FLAGS}
for flag, (_kind, subs) in gate.SHORT_TEXT_FLAGS.items():
    impl_flag_keys |= {(flag, sub) for sub in subs}
compare_keys("本文を運ぶ旗", {key for key, _ in FLAG_CASES}, impl_flag_keys)
compare_keys("長い旗の本文でない例外", {key for key, _ in NOT_BODY_CASES}, set(gate.LONG_FLAG_NOT_BODY))
compare_keys("投稿でないサブコマンド", {key for key, _ in NON_POSTING_CASES}, set(gate.NON_POSTING))
compare_keys("前置ラッパー", {key for key, _ in WRAPPER_CASES}, set(gate.WRAPPERS))
compare_keys("値を取る global 旗", {key for key, _ in GLOBAL_FLAG_CASES}, set(gate.GLOBAL_VALUE_FLAGS))

# 倒れ先の文言も同じ形で突合する。実装から機械で読むので、理由を足したら検査も足すまで赤い。
tree = ast.parse(io.open(gate_path, encoding="utf-8").read())
impl_reasons = {
    node.args[0].value
    for node in ast.walk(tree)
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    and node.func.attr == "append" and isinstance(node.func.value, ast.Name)
    and node.func.value.id == "blocked" and node.args
    and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str)
}
compare_keys("止めた理由", {reason for reason, _ in BLOCKED_CASES}, impl_reasons)

# 本文を拾えるべき形
for _key, command in FLAG_CASES:
    bodies, blocked, parsed = bodies_of(command)
    if not bodies:
        failures.append("%s: 本文を拾えていない (blocked=%s parsed=%s)" % (_key, blocked, parsed))
for command, why in POSTING:
    bodies, blocked, parsed = bodies_of(command)
    if not bodies:
        failures.append("%s: 本文を拾えていない (blocked=%s parsed=%s)" % (why, blocked, parsed))

# 素通しであるべき形
for command, why in QUIET + [(c, str(k)) for k, c in NOT_BODY_CASES + NON_POSTING_CASES]:
    bodies, blocked, parsed = bodies_of(command)
    if bodies or blocked:
        failures.append("%s: 素通しのはずが反応した (bodies=%s blocked=%s)"
                        % (why, [len(b) for b in bodies], blocked))

# graphql の mutation からは本文候補を取り出さない。取り出すと body 以外のフィールドに
# 書かれた値(ID・トークン・設定値)まで読み役へ渡る。deny になるかどうかでは検出できない
# ——mutation は一律で止まるので、抽出を戻しても deny のままになる(5 巡目に変異で実測)
SECRET = "DB_PASSWORD=hunter2"
MUTATION = ("gh api graphql -f query='mutation { u(input:{subjectId: \"\"\"%s%s\"\"\", "
            "body: \"\"\"%s\"\"\"}) }'" % (SECRET, PAD, BODY))
mutation_candidates = gate.posting_bodies(MUTATION)[0]
if mutation_candidates:
    failures.append("graphql mutation から本文候補を取り出している(非 body の値が読み役へ渡る) — %s"
                    % [c[:40] for c in mutation_candidates])

# 倒れ先: 理由ごとに、その理由で実際に止まることを確かめる
gate.LONG_TEXT_FLAGS[PATCH_FLAG] = "zz-unknown-kind"
try:
    for reason, command in BLOCKED_CASES:
        _bodies, blocked, parsed = bodies_of(command)
        if reason not in blocked:
            failures.append("倒れ先 %r で止まらない (blocked=%s parsed=%s)" % (reason, blocked, parsed))
finally:
    del gate.LONG_TEXT_FLAGS[PATCH_FLAG]

if failures:
    for f in failures:
        print("表の検査で漏れ: " + f)
    sys.exit(1)
print("TABLE_OK")
