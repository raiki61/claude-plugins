#!/usr/bin/env bash
# 配布物の検証。CI と手元で同じものを回す（/review-loop の P0-2 が「CI のテスト・lint を
# ローカル実行し緑を確認」を要求するので、その実体がこれ）。
#
# set -e は使わない——各ケースの終了コードを検査するのが目的で、
# 非ゼロで即死すると検査そのものが成立しない。
set -uo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

PY_BIN=$(command -v python3 || command -v python || true)
[ -n "$PY_BIN" ] || { echo "python3 / python が PATH に無い"; exit 2; }

fail=0
ran=0

# 終了コードを検査する。review-record.py は 0（阻害なし）/ 1（阻害あり）/ 2（記録が不正）を
# 区別することが要件なので、真偽でなく値そのものを見る。
expect_exit() {
    local want=$1 desc=$2
    shift 2
    "$@" >/dev/null 2>&1
    local got=$?
    ran=$((ran + 1))
    if [ "$got" = "$want" ]; then
        echo "  ok   $desc"
    else
        echo "  FAIL $desc — exit $want を期待したが $got"
        fail=1
    fi
}

expect_output() {
    local want=$1 desc=$2
    shift 2
    local got
    got=$("$@" 2>&1)
    ran=$((ran + 1))
    if [[ "$got" == *"$want"* ]]; then
        echo "  ok   $desc"
    else
        echo "  FAIL $desc — 出力に '$want' が無い: $got"
        fail=1
    fi
}

# 記録の一部を壊した JSON を作る。「壊すと落ちる」ことまで確かめないと、
# 検証が空振りしても合格になる（fail-open）。
break_record() {
    "$PY_BIN" - "$ROOT" "$WORK" "$1" "$2" <<'PY'
import json, sys, pathlib
root, work, name, mutation = sys.argv[1:5]
rec = json.loads((pathlib.Path(root)/"templates/round-2.example.json").read_text(encoding="utf-8"))
if mutation == "drop-material":
    del rec["materials"]["hygiene"]
elif mutation == "drop-defer-reason":
    del next(u for u in rec["units"] if u.get("disposition") == "defer")["reason"]
elif mutation == "bad-base":
    rec["base"] = "1" * 40
elif mutation == "bad-round":
    rec["round"] = 9
elif mutation == "bad-status":
    rec["materials"]["hygiene"]["status"] = "probably-fine"
elif mutation == "clean-without-checked":
    del rec["materials"]["hygiene"]["checked"]
else:
    raise SystemExit(f"未知の mutation: {mutation}")
(pathlib.Path(work)/name).write_text(json.dumps(rec, ensure_ascii=False), encoding="utf-8")
PY
}

echo "review-record.py"
R1="$ROOT/templates/round-1.example.json"
R2="$ROOT/templates/round-2.example.json"
# 変数に詰めて展開すると、python のパスにスペースがあるだけで壊れる（Windows で起きる）。
RECORD="$ROOT/scripts/review-record.py"

# 阻害あり: block 2 件・do-now 1 件・前ラウンドの記録が無い
expect_exit 1 "非収束の記録は阻害要因を返す" "$PY_BIN" "$RECORD" "$R1"
expect_exit 0 "解消済みの記録は阻害要因なし" "$PY_BIN" "$RECORD" "$R2" "$R1"
expect_output "scalar 'doc_lines': 120 → 135" "増えた scalar を R1 へ渡すため表示する" "$PY_BIN" "$RECORD" "$R2" "$R1"
expect_output "これは収束の宣言ではない" "阻害なしを収束と名乗らない" "$PY_BIN" "$RECORD" "$R2" "$R1"

# 記録が不正（exit 2）。1 と混ざると「非収束」と誤読され、収束を永久に宣言できなくなる
for m in drop-material drop-defer-reason bad-base bad-round bad-status clean-without-checked; do
    break_record "$m.json" "$m" || { echo "  FAIL 壊した記録を作れない: $m"; fail=1; continue; }
    expect_exit 2 "不正な記録は 1 と区別して落ちる: $m" "$PY_BIN" "$RECORD" "$WORK/$m.json" "$R1"
done

echo "comment-ratio.sh"
REPO="$WORK/repo"
mkdir -p "$REPO"
(
    cd "$REPO" || exit 1
    git init -q . && git config user.email t@t && git config user.name t
    echo "x = 1" > a.py
    git add -A && git commit -qm base
    # Python は tokenize、Go は C 系コメントとして数える。既存行 x = 1 は差分に載らない。
    printf '"""docstring は注釈。"""\n# 行コメントも注釈。\nx = 1\n' > a.py
    printf '// Go の行コメント\nfunc f() {}\n' > b.go
    git add -A
) >/dev/null 2>&1
BASE=$(git -C "$REPO" rev-parse HEAD)
expect_output "追加行 4 / 注釈 3 (75%)" "Python と C 系の注釈を数える" \
    bash -c "cd '$REPO' && bash '$ROOT/scripts/comment-ratio.sh' '$BASE'"
expect_output "追加行なし" "対象言語の追加行が無ければそう言う" \
    bash -c "cd '$ROOT' && bash '$ROOT/scripts/comment-ratio.sh' HEAD"

echo "マニフェストと参照の整合"
expect_exit 0 "marketplace.json / plugin.json が必須の欄を持つ" "$PY_BIN" - "$ROOT" <<'PY'
import json, sys, pathlib
root = pathlib.Path(sys.argv[1])
mk = json.loads((root/".claude-plugin/marketplace.json").read_text(encoding="utf-8"))
# owner はこれが無いと `claude plugin marketplace add` が schema 違反で落ちる（実測）。
for key in ("name", "owner", "plugins"):
    assert key in mk, f"marketplace.json に {key} が無い"
assert isinstance(mk["owner"], dict) and mk["owner"].get("name"), "owner は name を持つ object"
assert mk["plugins"], "plugins が空"
pl = json.loads((root/".claude-plugin/plugin.json").read_text(encoding="utf-8"))
for key in ("name", "version", "description"):
    assert key in pl, f"plugin.json に {key} が無い"
PY

expect_exit 0 "手順書が名指しする REVIEW.md のセクションが実在する" "$PY_BIN" - "$ROOT" <<'PY'
import re, sys, pathlib
root = pathlib.Path(sys.argv[1])
review = (root/"REVIEW.md").read_text(encoding="utf-8")
known = set(re.findall(r"^##+ (.+)$", review, re.M)) | set(re.findall(r"\*\*(.+?)\*\*", review))
missing = set()
for f in (root/"commands").glob("*.md"):
    body = f.read_text(encoding="utf-8")
    for name in re.findall(r"`REVIEW\.md`\s*(?:の)?\s*[「『]([^」』]+)[」』]", body):
        if not any(name in k for k in known):
            missing.add(f"{f.name}: 「{name}」")
assert not missing, "REVIEW.md に無いセクションを参照している: " + " / ".join(sorted(missing))
PY

expect_exit 0 "配布物に固有の技術名が混ざっていない" "$PY_BIN" - "$ROOT" <<'PY'
import re, sys, pathlib
root = pathlib.Path(sys.argv[1])
# 特定プロジェクト由来の名前が観点側に残ると、そのリポジトリでしか意味を持たない写しになる。
banned = re.compile(r"FastAPI|next-intl|config_kit|DeepAgents|asyncio_mode|guided-resolver")
hits = []
for f in [root/"REVIEW.md", root/"README.md", *(root/"commands").glob("*.md"), *(root/"docs").glob("*.md")]:
    for i, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
        if banned.search(line):
            hits.append(f"{f.name}:{i}")
assert not hits, "固有の技術名が残っている: " + " / ".join(hits)
PY

# 検査が 1 件も走らなかった場合を「合格」と区別する（対象が空でも緑になる穴を塞ぐ）。
EXPECTED_MIN=15
if [ "$ran" -lt "$EXPECTED_MIN" ]; then
    echo "検査が $ran 件しか走っていない（$EXPECTED_MIN 件以上を期待）——検証自体が空振りしている"
    exit 2
fi

echo
if [ "$fail" = 0 ]; then
    echo "$ran 件すべて緑"
else
    echo "$ran 件のうち失敗あり"
fi
exit "$fail"
