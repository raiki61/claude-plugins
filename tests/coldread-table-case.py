#!/usr/bin/env python3
"""判定表に載っているべき項目が実際に効いているかを確かめる。run.sh から呼ぶ。

**期待値は判定表から読まず、ここに直接書く。** 表を走査して表と突き合わせる形は、
表からメンバーが落ちても反復回数が減るだけで赤くならない(実測で確認した恒真)。
下の一覧は gh 2.96.0 の `gh <group> <sub> --help` を走査して作った実測値で、
gh の側が変わったときはここを直す。
"""
import importlib.util
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

# 本文を運ぶ形(gh 2.96.0 の --help 実測)。ここが検査の期待値で、実装の表とは独立に持つ。
POSTING = [
    ("gh issue comment 1 --body %s" % TEXT, "issue comment --body"),
    ("gh issue comment 1 -b %s" % TEXT, "issue comment -b"),
    ("gh issue create --body %s" % TEXT, "issue create --body"),
    ("gh issue create -b %s" % TEXT, "issue create -b"),
    ("gh issue edit 1 -b %s" % TEXT, "issue edit -b"),
    ("gh issue close 1 --comment %s" % TEXT, "issue close --comment"),
    ("gh issue close 1 -c %s" % TEXT, "issue close -c"),
    ("gh issue reopen 1 -c %s" % TEXT, "issue reopen -c"),
    ("gh pr comment 1 -b %s" % TEXT, "pr comment -b"),
    ("gh pr create -b %s" % TEXT, "pr create -b"),
    ("gh pr edit 1 -b %s" % TEXT, "pr edit -b"),
    ("gh pr merge 1 -b %s" % TEXT, "pr merge -b"),
    ("gh pr revert 1 -b %s" % TEXT, "pr revert -b"),
    ("gh pr review 1 -b %s" % TEXT, "pr review -b"),
    ("gh pr close 1 -c %s" % TEXT, "pr close -c"),
    ("gh pr reopen 1 -c %s" % TEXT, "pr reopen -c"),
    ("gh discussion comment 1 -b %s" % TEXT, "discussion comment -b"),
    ("gh discussion create -b %s" % TEXT, "discussion create -b"),
    ("gh discussion edit 1 -b %s" % TEXT, "discussion edit -b"),
    ("gh release create v1 --notes %s" % TEXT, "release create --notes"),
    ("gh release create v1 -n %s" % TEXT, "release create -n"),
    ("gh release edit v1 -n %s" % TEXT, "release edit -n"),
    ("gh project edit 1 --readme %s" % TEXT, "project edit --readme"),
    ("gh issue comment 1 --body-file %s" % HEREDOC, "issue comment --body-file"),
    ("gh issue comment 1 -F %s" % HEREDOC, "issue comment -F"),
    ("gh pr comment 1 -F %s" % HEREDOC, "pr comment -F"),
    ("gh pr review 1 -F %s" % HEREDOC, "pr review -F"),
    ("gh discussion comment 1 -F %s" % HEREDOC, "discussion comment -F"),
    ("gh release create v1 --notes-file %s" % HEREDOC, "release create --notes-file"),
    ("gh release create v1 -F %s" % HEREDOC, "release create -F"),
    ("gh release edit v1 -F %s" % HEREDOC, "release edit -F"),
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

# 投稿でない形(値を読み役へ送らない・止めない)
QUIET = [
    ("gh pr checkout 1 -b feature/%s" % ("x" * 300), "pr checkout -b はブランチ名"),
    ("gh repo sync -b main # %s" % PAD, "repo sync -b はブランチ名"),
    ("gh issue develop 5 -n branch/%s" % ("x" * 300), "issue develop -n はブランチ名"),
    ("gh issue view 12 -c # %s %s" % (PAD, BODY), "issue view -c は --comments"),
    ("gh pr status -c # %s %s" % (PAD, BODY), "pr status -c は --conflict-status"),
    ("gh run download 5 -n name/%s" % ("x" * 300), "run download -n は --name"),
    ("gh secret set K --body %s" % TEXT, "secret set の値は秘密"),
    ("gh variable set V --body %s" % TEXT, "variable set の値は設定"),
    ("gh workflow run w.yml -F key=%s" % TEXT, "workflow run -F は field"),
    ("gh pr view 12 --json state # %s" % PAD, "読み取り"),
    ("gh api graphql -f query='query { repository { name } }' # %s" % PAD, "graphql の読み取り"),
]

failures = []
for command, why in POSTING:
    candidates, blocked, parsed = gate.posting_bodies(command)
    if not [c for c in candidates if len(c.strip()) >= 200]:
        failures.append("%s: 本文を拾えていない (blocked=%s parsed=%s)" % (why, blocked, parsed))
for command, why in QUIET:
    candidates, blocked, parsed = gate.posting_bodies(command)
    bodies = [c for c in candidates if len(c.strip()) >= 200]
    if bodies or blocked:
        failures.append("%s: 素通しのはずが反応した (bodies=%s blocked=%s)"
                        % (why, [len(b) for b in bodies], blocked))

if failures:
    for f in failures:
        print("表の検査で漏れ: " + f)
    sys.exit(1)
print("TABLE_OK")
