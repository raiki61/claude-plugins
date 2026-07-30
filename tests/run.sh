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

# 出力と終了コードの**両方**を検査する。終了コードを見ないと、対象が異常終了しても
# そのエラーメッセージが期待文字列を偶然含んでいれば ok になる（fail-open）。
# REVIEW.md のコード衛生観点が「検査自体が実行不能に終わったとき赤くなるか」を
# 要求しているので、それを配るスイート自身が満たしていなければならない。
#
# **期待メッセージを指定できることが要件。** スクリプトは末尾の例外境界で想定外の例外も
# exit 2 に倒すので、終了コードだけを見る検査は個別の型検査を消しても緑のまま通る
# （＝恒真）。どの検査が発火したかはメッセージでしか区別できない。
expect_output() {
    local want_exit=$1 want=$2 desc=$3
    shift 3
    local got
    got=$("$@" 2>&1)
    local got_exit=$?
    ran=$((ran + 1))
    if [ "$got_exit" != "$want_exit" ]; then
        echo "  FAIL $desc — exit $want_exit を期待したが $got_exit: $got"
        fail=1
    elif [[ "$got" == *"$want"* ]]; then
        echo "  ok   $desc"
    else
        echo "  FAIL $desc — 出力に '$want' が無い: $got"
        fail=1
    fi
}

# 終了コードだけを見る検査。`expect_output` に空の期待文字列を渡すのと同義なので委譲する
# （空文字列は必ず部分一致する）。実行・集計・出力整形を二重に持たない。
expect_exit() {
    local want=$1 desc=$2
    shift 2
    expect_output "$want" "" "$desc" "$@"
}

# 記録の一部を壊した JSON を作る。「壊すと落ちる」ことまで確かめないと、
# 検証が空振りしても合格になる（fail-open）。
break_record() {
    "$PY_BIN" - "$ROOT" "$WORK" "$1" "$2" "${3:-round-2}" <<'PY'
import json, sys, pathlib
root, work, name, mutation, src = sys.argv[1:6]
rec = json.loads((pathlib.Path(root)/f"templates/{src}.example.json").read_text(encoding="utf-8"))
if mutation == "drop-material":
    del rec["materials"]["hygiene"]
elif mutation == "drop-defer-reason":
    del next(u for u in rec["units"] if u.get("disposition") == "defer")["reason"]
elif mutation == "drop-base":
    del rec["base"]
elif mutation == "drop-round":
    del rec["round"]
elif mutation == "bad-base":
    rec["base"] = "1" * 40
elif mutation == "bad-round":
    rec["round"] = 9
elif mutation == "bad-status":
    rec["materials"]["hygiene"]["status"] = "probably-fine"
elif mutation == "clean-without-checked":
    del rec["materials"]["hygiene"]["checked"]
# 以下は「型が違う」系。値の書き換えだけでは個別の型検査が一度も発火しない。
elif mutation == "not-object":
    rec = ["not", "an", "object"]
elif mutation == "bad-round-type":
    rec["round"] = "2"
elif mutation == "bad-round-bool":
    rec["round"] = True
elif mutation == "round-below-one":
    rec["round"] = -100
elif mutation == "bad-materials-type":
    rec["materials"] = []
elif mutation == "bad-units-type":
    rec["units"] = {}
elif mutation == "bad-unit-type":
    rec["units"][0] = "not-an-object"
elif mutation == "bad-material-type":
    rec["materials"]["hygiene"] = "looks-fine"
# 以下は個別検査を通り抜け、末尾の例外境界だけが受け止めるもの。
elif mutation == "bad-scalars-type":
    rec["scalars"] = ["oops"]
elif mutation == "unhashable-status":
    rec["materials"]["hygiene"]["status"] = ["found"]
elif mutation == "unhashable-key":
    rec["units"][0]["key"] = ["not", "a", "string"]
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

# 初回ラウンドの正しい呼び方（第 2 引数なし）。手順書がこの形を指示している。
# 阻害あり: block 2 件・do-now 1 件・前ラウンドの記録が無い
expect_output 1 "前ラウンドの記録が無い" "初回は第 2 引数なしで走り、比較の欠落を阻害要因に数える" \
    "$PY_BIN" "$RECORD" "$R1"
expect_exit 0 "解消済みの記録は阻害要因なし" "$PY_BIN" "$RECORD" "$R2" "$R1"
expect_output 0 "scalar 'doc_lines': 120 → 135" "増えた scalar を R1 へ渡すため表示する" "$PY_BIN" "$RECORD" "$R2" "$R1"
expect_output 0 "これは収束の宣言ではない" "阻害なしを収束と名乗らない" "$PY_BIN" "$RECORD" "$R2" "$R1"

# 記録が不正（exit 2）。1 と混ざると「非収束」と誤読され、収束を永久に宣言できなくなる。
# **期待メッセージまで検査する。** 終了コードだけを見ると、末尾の例外境界が想定外の例外も
# 2 に倒すため、個別の検査を 1 つ消しても緑のまま通る（検査が恒真になる）。
while IFS='|' read -r m msg; do
    [ -n "$m" ] || continue
    break_record "$m.json" "$m" || { echo "  FAIL 壊した記録を作れない: $m"; fail=1; continue; }
    expect_output 2 "$msg" "不正な記録は 1 と区別して落ちる: $m" "$PY_BIN" "$RECORD" "$WORK/$m.json" "$R1"
done <<'CASES'
drop-material|素材 'hygiene' の返答が無い
drop-defer-reason|defer に構造的理由が無い
drop-base|必須の欄 'base' が無い
drop-round|必須の欄 'round' が無い
bad-base|base が違う
bad-round|ラウンドが連番でない
bad-status|status が不正
clean-without-checked|'checked' が要る
not-object|記録の最上位が object でない
bad-round-type|'round' が整数でない
bad-round-bool|'round' が整数でない
round-below-one|'round' が 1 以上でない
bad-materials-type|'materials' が object でない
bad-units-type|'units' が配列でない
bad-unit-type|units[0] が object でない
bad-material-type|素材 'hygiene' の返答が無い
bad-scalars-type|想定外の例外（AttributeError）
unhashable-status|想定外の例外（TypeError）
CASES

# 前ラウンド側の記録が壊れている経路。突合（集合演算）は prev だけを走査するので、
# 今ラウンドの記録を壊しても発火しない。
break_record "unhashable-key.json" "unhashable-key" round-1 \
    || { echo "  FAIL 壊した記録を作れない: unhashable-key"; fail=1; }
expect_output 2 "想定外の例外（TypeError）" "前ラウンドの key が unhashable でも 1 と区別して落ちる" \
    "$PY_BIN" "$RECORD" "$R2" "$WORK/unhashable-key.json"

# 記録に到達できない場合も 2。**Python の未処理例外は exit 1** なので、素通しすると
# 「読めなかった」が「非収束」に化ける——手順どおり round-0.json を渡した瞬間に起きた穴。
printf '{ "base": ' > "$WORK/truncated.json"
expect_output 2 "JSON として読めない" "壊れた JSON は 1 と区別して落ちる" \
    "$PY_BIN" "$RECORD" "$WORK/truncated.json"
expect_output 2 "開けない" "存在しない記録は 1 と区別して落ちる（初回に round-0.json を渡した場合）" \
    "$PY_BIN" "$RECORD" "$WORK/does-not-exist.json"
expect_exit 2 "引数なしは 1 と区別して落ちる" "$PY_BIN" "$RECORD"
expect_exit 2 "引数が多すぎる場合も 1 と区別して落ちる" "$PY_BIN" "$RECORD" "$R2" "$R1" "$R1"
# json モジュールが投げる例外は JSONDecodeError だけではない（深いネストは RecursionError）。
# **ここは終了コードだけを見る。** どの経路で 2 になるかは環境で変わる——再帰上限に達すれば
# 境界が受け、達しなければ最上位の型検査が受ける（macOS は 10 万段でも読み切る）。
# 例外名を検査すると環境依存のテストになり、緑が環境の性質を映すだけになる。
# 境界そのものは上の bad-scalars-type / unhashable-status が例外名まで検査している。
"$PY_BIN" -c "import sys,pathlib; pathlib.Path(sys.argv[1]).write_text('['*100000 + ']'*100000, encoding='utf-8')" "$WORK/deep.json"
expect_exit 2 "深いネストの JSON も 1 と区別して落ちる（経路は環境で変わる）" \
    "$PY_BIN" "$RECORD" "$WORK/deep.json"

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
expect_output 0 "追加行 4 / 注釈 3 (75%)" "Python と C 系の注釈を数える" \
    bash -c "cd '$REPO' && bash '$ROOT/scripts/comment-ratio.sh' '$BASE'"

# 対象言語の追加行が無い正常系。**$ROOT でなく使い捨てリポジトリで測る**——$ROOT だと
# 開発中の未コミット変更の有無で結果が変わり、検査が環境依存になる。
git -C "$REPO" commit -qm change >/dev/null 2>&1
expect_output 0 "追加行なし" "対象言語の追加行が無ければそう言う" \
    bash -c "cd '$REPO' && bash '$ROOT/scripts/comment-ratio.sh' HEAD"

# 未追跡の対象言語ファイルは計測漏れ。**止めるのは「計測漏れの 0」と「本当に 0」が
# 原理的に区別できない場合だけ**——数えられているなら列挙して見せる（無関係な下書きで
# P4 が毎回止まると、手順そのものが成立しない）。
printf 'y = 2\n' > "$REPO/untracked.py"
expect_output 2 "計測漏れと区別できない" "追加行が無く未追跡の対象ファイルがあれば落ちる" \
    bash -c "cd '$REPO' && bash '$ROOT/scripts/comment-ratio.sh' HEAD"
expect_output 0 "未計測（未追跡・差分に載っていない）: untracked.py" \
    "数えられるなら止めずに未計測分を列挙する" \
    bash -c "cd '$REPO' && bash '$ROOT/scripts/comment-ratio.sh' '$BASE'"
# ref 間比較は作業ツリーを見ないので、未追跡ファイルが在っても対象外（短絡が効いているか）。
expect_output 0 "追加行なし" "ref を指定した比較では未追跡ファイルを見ない" \
    bash -c "cd '$REPO' && bash '$ROOT/scripts/comment-ratio.sh' HEAD HEAD"
rm -f "$REPO/untracked.py"

# 計測不成立は必ず 2。**旧版はここが exit 1 だった**（`raise SystemExit(str)` の既定）ので、
# 「測れなかった」と「注釈 0%」が終了コードで区別できなかった。
expect_output 2 "が失敗" "不正な ref は 1 と区別して落ちる" \
    bash -c "cd '$REPO' && bash '$ROOT/scripts/comment-ratio.sh' deadbeefdeadbeefdeadbeefdeadbeefdeadbeef"
printf 'def f(\n' > "$REPO/broken.py"
git -C "$REPO" add -A >/dev/null 2>&1
expect_output 2 "解析できない（構文エラー）" "解析できない Python は 1 と区別して落ちる" \
    bash -c "cd '$REPO' && bash '$ROOT/scripts/comment-ratio.sh' HEAD"
git -C "$REPO" rm -q -f --cached broken.py >/dev/null 2>&1
rm -f "$REPO/broken.py"

echo "マニフェストと参照の整合"
expect_exit 0 "marketplace.json / plugin.json が必須の欄を持つ" "$PY_BIN" - "$ROOT" <<'PY'
import json, re, sys, pathlib
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

# 局所レビューの依存は公式の宣言機構で入れる。宣言が消えると pr-review-toolkit が
# 入らないまま「欠陥の観点が 1 つ静かに欠けたレビュー」が通るので、宣言の実在を検査する。
deps = [d for d in (pl.get("dependencies") or []) if isinstance(d, dict)]
assert any(d.get("name") == "pr-review-toolkit" for d in deps), \
    "plugin.json が pr-review-toolkit を dependencies で宣言していない"
# 別 marketplace への依存は、ルート marketplace の許可リストが無いと install が
# cross-marketplace エラーで落ちる。
needed = {d["marketplace"] for d in deps if d.get("marketplace")}
allowed = set(mk.get("allowCrossMarketplaceDependenciesOn") or [])
assert needed <= allowed, \
    f"marketplace.json の allowCrossMarketplaceDependenciesOn に {sorted(needed - allowed)} が無い"
# 宣言に移した以上、手順書側に導入コマンドを戻すな（宣言と自作導入は排他——宣言が
# 解決できない環境ではプラグイン自体がロードされず、導入コマンドに到達しない）。
# **語の間の空白は緩めて見る**——`claude plugin \`＋改行＋`  install` のように整形を
# 変えるだけで完全一致は外れ、検査が素通りする。
body = (root/"commands/review-loop.md").read_text(encoding="utf-8")
install_cmd = re.compile(r"claude\s+plugin\s+(?:\S+\s+)*install")
assert not install_cmd.search(body), \
    "review-loop.md に自作の導入コマンドが戻っている（依存は plugin.json の dependencies が正本）"

# `gh` は `-R owner/repo` が無いと cwd の remote と `gh` のログイン状態に暗黙依存し、
# 別リポジトリの PR 一覧を**エラーにならず**返す。取り違えは正常終了するので、手順書の
# 文言が `-R` 無しに戻ったことを検知できるのはこの検査だけ（実行時の付け忘れは別）。
bare_gh = [
    line.strip()
    for line in body.splitlines()
    if re.search(r"`gh (pr list|pr view|pr diff)", line) and "-R " not in line
]
assert not bare_gh, "gh の呼び出しに -R が無い行がある: " + " / ".join(bare_gh)
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

# 検査が空振りした場合を「合格」と区別する（対象が空でも緑になる穴を塞ぐ）。
# **これは下限で、総数の台帳ではない**——「意味のある検査を消して些末なものを足す」形の
# 劣化は検知しない（それを見るのは人のレビュー）。件数を他所に書き写すな（腐る）。
EXPECTED_MIN=20
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
