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

# 記録の一部を壊した JSON を**まとめて 1 プロセスで**書き出す。「壊すと落ちる」ことまで
# 確かめないと、検証が空振りしても合格になる（fail-open）。
#
# **束ねてよいのは素材の生成だけ。** 検査そのものはケースごとに分けたまま——合否が個別に
# 報告されることが要件で、束ねると失敗の切り分けができなくなる。生成を 1 ケース 1 プロセスに
# すると Python の起動コストだけで 26 秒かかる（実測。まとめて 1.2 秒）。
write_broken_records() {
    "$PY_BIN" - "$ROOT" "$WORK" <<'PY'
import json, sys, pathlib
root, work = pathlib.Path(sys.argv[1]), pathlib.Path(sys.argv[2])
templates = {
    n: json.loads((root / f"templates/{n}.example.json").read_text(encoding="utf-8"))
    for n in ("round-1", "round-2")
}


def defer_unit(rec):
    return next(u for u in rec["units"] if u.get("disposition") == "defer")


# 値を書き換えるだけの mutation。個別の欄の検査を発火させる。
VALUE = {
    "drop-material": lambda r: r["materials"].pop("hygiene"),
    "drop-defer-reason": lambda r: defer_unit(r).pop("reason"),
    "drop-base": lambda r: r.pop("base"),
    "drop-round": lambda r: r.pop("round"),
    "bad-base": lambda r: r.update(base="1" * 40),
    "bad-round": lambda r: r.update(round=9),
    "bad-status": lambda r: r["materials"]["hygiene"].update(status="probably-fine"),
    "clean-without-checked": lambda r: r["materials"]["hygiene"].pop("checked"),
    # ラベルと key の検査は、消えても記録が「阻害要因なし（exit 0）」で通ってしまう
    # ——[block] が黙って数えられなくなる、この道具の存在理由そのものの穴。
    "bad-label": lambda r: r["units"][0].update(label="blocker"),
    "drop-key": lambda r: r["units"][0].pop("key"),
}
# 「型が違う」系。値の書き換えだけでは個別の型検査が一度も発火しない。
TYPE = {
    "bad-round-type": lambda r: r.update(round="2"),
    "bad-round-bool": lambda r: r.update(round=True),
    "round-below-one": lambda r: r.update(round=-100),
    "bad-materials-type": lambda r: r.update(materials=[]),
    "bad-units-type": lambda r: r.update(units={}),
    "bad-unit-type": lambda r: r["units"].__setitem__(0, "not-an-object"),
}
# 個別の検査を通り抜け、末尾の例外境界だけが受け止めるもの。
BOUNDARY = {
    "bad-scalars-type": lambda r: r.update(scalars=["oops"]),
    "unhashable-status": lambda r: r["materials"]["hygiene"].update(status=["found"]),
}


def write(name, rec):
    (work / f"{name}.json").write_text(json.dumps(rec, ensure_ascii=False), encoding="utf-8")


for name, mutate in {**VALUE, **TYPE, **BOUNDARY}.items():
    rec = json.loads(json.dumps(templates["round-2"]))
    mutate(rec)
    write(name, rec)

# 最上位が object でない記録は mutate 関数の形（rec を書き換える）に乗らないので別に書く。
write("not-object", ["not", "an", "object"])

# 突合（集合演算）は prev だけを走査するので、前ラウンド側の記録を壊す必要がある。
prev = json.loads(json.dumps(templates["round-1"]))
prev["units"][0]["key"] = ["not", "a", "string"]
write("unhashable-key", prev)

# JSON として読めない記録と、深いネスト（json モジュールが JSONDecodeError 以外を投げる例）。
(work / "truncated.json").write_text('{ "base": ', encoding="utf-8")
(work / "deep.json").write_text("[" * 100000 + "]" * 100000, encoding="utf-8")
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

write_broken_records || { echo "  FAIL 壊した記録を作れない"; fail=1; }

# 記録が不正（exit 2）。1 と混ざると「非収束」と誤読され、収束を永久に宣言できなくなる。
# **期待メッセージまで検査する。** 終了コードだけを見ると、末尾の例外境界が想定外の例外も
# 2 に倒すため、個別の検査を 1 つ消しても緑のまま通る（検査が恒真になる）。
while IFS='|' read -r m msg; do
    [ -n "$m" ] || continue
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
bad-label|label が不正
drop-key|key が無い
not-object|記録の最上位が object でない
bad-round-type|'round' が整数でない
bad-round-bool|'round' が整数でない
round-below-one|'round' が 1 以上でない
bad-materials-type|'materials' が object でない
bad-units-type|'units' が配列でない
bad-unit-type|units[0] が object でない
bad-scalars-type|想定外の例外（AttributeError）
unhashable-status|想定外の例外（TypeError）
CASES

expect_output 2 "想定外の例外（TypeError）" "前ラウンドの key が unhashable でも 1 と区別して落ちる" \
    "$PY_BIN" "$RECORD" "$R2" "$WORK/unhashable-key.json"

# 記録に到達できない場合も 2（契約は冒頭 `review-record.py` の docstring が正本）。
expect_output 2 "JSON として読めない" "壊れた JSON は 1 と区別して落ちる" \
    "$PY_BIN" "$RECORD" "$WORK/truncated.json"
expect_output 2 "開けない" "存在しない記録は 1 と区別して落ちる（初回に round-0.json を渡した場合）" \
    "$PY_BIN" "$RECORD" "$WORK/does-not-exist.json"
expect_exit 2 "引数なしは 1 と区別して落ちる" "$PY_BIN" "$RECORD"
expect_exit 2 "引数が多すぎる場合も 1 と区別して落ちる" "$PY_BIN" "$RECORD" "$R2" "$R1" "$R1"
# **ここは終了コードだけを見る。** どの経路で 2 になるかは環境で変わる——再帰上限に達すれば
# 境界が受け、達しなければ最上位の型検査が受ける（macOS は 10 万段でも読み切る）。例外名を
# 検査すると、緑が環境の性質を映すだけになる。境界そのものは上の bad-scalars-type /
# unhashable-status が例外名まで検査している。
expect_exit 2 "深いネストの JSON も 1 と区別して落ちる（経路は環境で変わる）" \
    "$PY_BIN" "$RECORD" "$WORK/deep.json"

echo "research-record.py"
RR="$ROOT/scripts/research-record.py"
RR_EX="$ROOT/templates/research-record.example.json"

expect_output 0 "これは品質・飽和の宣言ではない" "阻害なしを品質・飽和と名乗らない" \
    "$PY_BIN" "$RR" "$RR_EX"

# 記録の一部を壊した JSON をまとめて 1 プロセスで書き出す（生成のみ束ねる。理由は上の
# write_broken_records と同じ——検査はケースごとに分けたままにする）。
"$PY_BIN" - "$ROOT" "$WORK" <<'PY' || { echo "  FAIL 壊した研究記録を作れない"; fail=1; }
import json, sys, pathlib
root, work = pathlib.Path(sys.argv[1]), pathlib.Path(sys.argv[2])
base = json.loads((root / "templates/research-record.example.json").read_text(encoding="utf-8"))

def all_unloaded(r):
    for c in r["claims"]:
        c["load_bearing"] = False
    r["process"]["unrefuted_load_bearing"] = []
    r["process"].pop("reason", None)


MUT = {
    # 記録の不正（exit 2）
    "rr-drop-claims": lambda r: r.pop("claims"),
    "rr-bad-verdict": lambda r: r["claims"][0].update(verdict="たぶん確証"),
    "rr-conf-without-conditions": lambda r: r["claims"][0].pop("conditions"),
    "rr-count-mismatch": lambda r: r["clusters"][0].update(claims_submitted=3),
    "rr-corrections-gap": lambda r: r.update(
        corrections=[{"no": 7, "text": "a"}, {"no": 9, "text": "b"}]
    ),
    "rr-corrections-bool": lambda r: r["corrections"][0].update(no=True),
    "rr-undeclared-unrefuted": lambda r: r["process"].update(unrefuted_load_bearing=[]),
    "rr-na-without-reason": lambda r: r.update(sampling={"status": "not_applicable"}),
    "rr-number-without-source": lambda r: r["numbers"][0].pop("source"),
    "rr-origin-missing": lambda r: r["constraints"][0].pop("origin"),
    "rr-heavy-without-cartographer": lambda r: r.update(thickness="重厚"),
    "rr-stopped-without-reason": lambda r: r["convergence"].update(outcome="stopped"),
    "rr-load-zero-undeclared": all_unloaded,
    "rr-decisions-empty": lambda r: r.update(
        decisions={"decide_now": [], "poc": [], "human_only": []}
    ),
    # 個別の検査を通り抜け、末尾の例外境界だけが受け止めるもの
    "rr-unhashable-declared": lambda r: r["process"].update(unrefuted_load_bearing=[["L2"]]),
    # 発行の阻害（exit 1）——記録としては正しいが、収束を名乗ったまま出してはいけない状態
    "rr-overturned": lambda r: r["sampling"].update(overturned=1),
    "rr-rederiver-fail": lambda r: r["gates"]["rederiver"].update(verdict="redesign-needed"),
    "rr-unrefuted-disagreement": lambda r: r["claims"][1].update(verdict="相違"),
    "rr-coldreader-fail": lambda r: r["gates"]["cold_reader"].update(
        rounds=[
            {"verdict": "redesign-needed", "findings": 8},
            {"verdict": "redesign-needed", "findings": 7},
        ]
    ),
    # 停止（未収束）の正直な申告は発行できる（exit 0）——収束の偽装だけを塞ぐ
    "rr-stopped-ok": lambda r: (
        r["gates"]["rederiver"].update(verdict="unverifiable"),
        r["convergence"].update(
            outcome="stopped", stopped_reason="独立出典が取れず rederiver が unverifiable"
        ),
    ),
}
for name, mutate in MUT.items():
    rec = json.loads(json.dumps(base))
    mutate(rec)
    (work / f"{name}.json").write_text(json.dumps(rec, ensure_ascii=False), encoding="utf-8")
PY

# 記録の不正（exit 2）。期待メッセージまで検査する理由は review-record.py の節と同じ。
while IFS='|' read -r m msg; do
    [ -n "$m" ] || continue
    expect_output 2 "$msg" "不正な研究記録は 1 と区別して落ちる: $m" "$PY_BIN" "$RR" "$WORK/$m.json"
done <<'CASES'
rr-drop-claims|必須の欄 'claims' が無い
rr-bad-verdict|verdict が不正
rr-conf-without-conditions|'conditions' が空か文字列でない
rr-count-mismatch|判定の欠落を「なし」と読むな
rr-corrections-gap|連番でない
rr-corrections-bool|'no' が 1 以上の整数でない
rr-undeclared-unrefuted|申告も無い
rr-na-without-reason|「該当なし+理由」
rr-number-without-source|'source' が空か文字列でない
rr-origin-missing|origin が不正
rr-heavy-without-cartographer|盲点ゼロを名乗るな
rr-stopped-without-reason|'stopped_reason' が空か文字列でない
rr-load-zero-undeclared|'load_zero_reason' が空か文字列でない
rr-decisions-empty|3 分類に仕分けろ
rr-unhashable-declared|想定外の例外（TypeError）
CASES

# 発行の阻害（exit 1）。記録の不正（2）と混ぜない——直すべき対象が違う。
while IFS='|' read -r m msg; do
    [ -n "$m" ] || continue
    expect_output 1 "$msg" "発行を妨げる状態は 2 と区別して報せる: $m" "$PY_BIN" "$RR" "$WORK/$m.json"
done <<'CASES'
rr-overturned|飽和ではない
rr-rederiver-fail|収束を名乗っている
rr-unrefuted-disagreement|反証を経ていない
rr-coldreader-fail|cold-reader が pass していない
CASES

expect_output 0 "停止（未収束）の申告つきで発行できる" "非収束の停止は記録を偽らずに出せる" \
    "$PY_BIN" "$RR" "$WORK/rr-stopped-ok.json"

expect_exit 2 "引数なしは 1 と区別して落ちる" "$PY_BIN" "$RR"
expect_exit 2 "引数が多すぎる場合も 1 と区別して落ちる（研究記録）" "$PY_BIN" "$RR" "$RR_EX" "$RR_EX"
expect_output 2 "開けない" "存在しない研究記録は 1 と区別して落ちる" \
    "$PY_BIN" "$RR" "$WORK/rr-does-not-exist.json"
expect_exit 2 "深いネストの研究記録も 1 と区別して落ちる（経路は環境で変わる）" \
    "$PY_BIN" "$RR" "$WORK/deep.json"

echo "doctor-record.py"
DR="$ROOT/scripts/doctor-record.py"
DR_EX="$ROOT/templates/doctor-record.example.json"

expect_output 0 "これは品質・飽和の宣言ではない" "阻害なしを品質・飽和と名乗らない（診断記録）" \
    "$PY_BIN" "$DR" "$DR_EX"

"$PY_BIN" - "$ROOT" "$WORK" <<'PY' || { echo "  FAIL 壊した診断記録を作れない"; fail=1; }
import json, sys, pathlib
root, work = pathlib.Path(sys.argv[1]), pathlib.Path(sys.argv[2])
base = json.loads((root / "templates/doctor-record.example.json").read_text(encoding="utf-8"))

UNVERIFIED = {
    "key": "断面から生えた新候補（次ラウンド対象）",
    "height": 1,
    "verdict": "未検証",
    "confidence": "仮説",
    "weight": None,
    "parent": None,
    "evidence": "走査の断面で観測",
}

MUT = {
    # 記録の不正（exit 2）
    "dr-drop-nodes": lambda r: r.pop("nodes"),
    "dr-bad-verdict": lambda r: r["nodes"][0].update(verdict="たぶん推奨"),
    "dr-conditional-without-condition": lambda r: r["nodes"][1].pop("condition"),
    "dr-parent-missing": lambda r: r["nodes"][1].update(parent="存在しない親"),
    "dr-scout-unreturned-not-unseen": lambda r: r["scouts"][0].update(candidates_returned=False),
    "dr-height-five": lambda r: r["nodes"][0].update(height=5),
    "dr-oneshot-on-rejected": lambda r: r["oneshot"].update(
        key="log_service/logger 置換案: 例外の握り潰しを logger 化する"
    ),
    "dr-votes-two": lambda r: r["oneshot"].update(votes=["票1", "票2"]),
    "dr-escalation-stale": lambda r: r["nodes"][0].update(weight="ライブラリ級"),
    "dr-modcheck-restored-without-note": lambda r: r.update(mod_check={"status": "restored"}),
    "dr-rescan-empty": lambda r: r["rescan"].update(coverage=" "),
    # 発行の阻害（exit 1）——飽和を名乗ったまま出してはいけない状態
    "dr-unverified-node": lambda r: r["nodes"].append(dict(UNVERIFIED)),
    "dr-sampling-na": lambda r: r.update(
        sampling={"status": "not_applicable", "reason": "新規ゼロが自明なので省いた"}
    ),
    "dr-cart-fail": lambda r: r["gates"]["cartographer_comparison"].update(verdict="redesign-needed"),
    "dr-overturned": lambda r: r["sampling"].update(overturned=2),
    # 停止（未飽和）の正直な申告は発行できる（exit 0）
    "dr-stopped-ok": lambda r: (
        r["gates"]["cold_reader"]["rounds"].append({"verdict": "redesign-needed", "findings": 4}),
        r["convergence"].update(outcome="stopped", stopped_reason="軽量段の 1 ラウンド打ち切り（設計どおり）"),
    ),
}
for name, mutate in MUT.items():
    rec = json.loads(json.dumps(base))
    mutate(rec)
    (work / f"{name}.json").write_text(json.dumps(rec, ensure_ascii=False), encoding="utf-8")
PY

while IFS='|' read -r m msg; do
    [ -n "$m" ] || continue
    expect_output 2 "$msg" "不正な診断記録は 1 と区別して落ちる: $m" "$PY_BIN" "$DR" "$WORK/$m.json"
done <<'CASES'
dr-drop-nodes|必須の欄 'nodes' が無い
dr-bad-verdict|verdict が不正
dr-conditional-without-condition|'condition' が空か文字列でない
dr-parent-missing|が nodes に無い
dr-scout-unreturned-not-unseen|「見つからなかった」と読むな
dr-height-five|高さは固定 4 段
dr-oneshot-on-rejected|一撃に選べるのは推奨・条件付きの節だけ
dr-votes-two|3 票
dr-escalation-stale|申告の腐り
dr-modcheck-restored-without-note|'note' が空か文字列でない
dr-rescan-empty|'coverage' が空か文字列でない
CASES

while IFS='|' read -r m msg; do
    [ -n "$m" ] || continue
    expect_output 1 "$msg" "飽和の偽装は 2 と区別して報せる: $m" "$PY_BIN" "$DR" "$WORK/$m.json"
done <<'CASES'
dr-unverified-node|飽和は全節に判定が付いてから
dr-sampling-na|抜き取り検査が要る
dr-cart-fail|pass していないのに飽和を名乗っている
dr-overturned|飽和ではない
CASES

expect_output 0 "停止（未飽和）の申告つきで発行できる" "非飽和の停止は記録を偽らずに出せる" \
    "$PY_BIN" "$DR" "$WORK/dr-stopped-ok.json"
expect_exit 2 "引数なしは 1 と区別して落ちる（診断記録）" "$PY_BIN" "$DR"
expect_exit 2 "深いネストの診断記録も 1 と区別して落ちる（経路は環境で変わる）" \
    "$PY_BIN" "$DR" "$WORK/deep.json"

echo "firstread-record.py"
FR="$ROOT/scripts/firstread-record.py"

# `pre_answers` は実在パスを要求する（**頭の中に置くのを許さない**のがこの欄の趣旨）。
# テンプレートは雛形であって実行可能な記録ではないので、ここで実在パスへ差し替える。
"$PY_BIN" - "$ROOT" "$WORK" <<'PY' || { echo "  FAIL 壊した初読記録を作れない"; fail=1; }
import json, sys, pathlib
root, work = pathlib.Path(sys.argv[1]), pathlib.Path(sys.argv[2])

pre = work / "pre-answers.md"
pre.write_text("先に書いた答え（読み役の答えを見る前に書いたもの）\n", encoding="utf-8")

def read(n):
    r = json.loads((root / f"templates/firstread-round-{n}.example.json").read_text(encoding="utf-8"))
    r["pre_answers"] = str(pre)
    return r

r1, r2 = read(1), read(2)
(work / "fr-1.json").write_text(json.dumps(r1, ensure_ascii=False), encoding="utf-8")
(work / "fr-2.json").write_text(json.dumps(r2, ensure_ascii=False), encoding="utf-8")

MUT = {
    # 記録の不正（exit 2）
    "fr-drop-materials": lambda r: r.pop("materials"),
    "fr-drop-skipped": lambda r: r["materials"].pop("skipped"),
    "fr-none-without-asked": lambda r: r["materials"].__setitem__("ideas", {"status": "none"}),
    "fr-item-no-key": lambda r: r["materials"]["stopped"]["items"][0].pop("key"),
    "fr-item-no-verbatim": lambda r: r["materials"]["stopped"]["items"][0].pop("verbatim"),
    "fr-pre-answers-gone": lambda r: r.update(pre_answers=str(work / "書いていない.md")),
    "fr-no-profile": lambda r: r.update(reader_profile=""),
    "fr-no-scope": lambda r: r.update(scope=[]),
    "fr-no-in-scope": lambda r: r["materials"]["stopped"]["items"][0].pop("in_scope"),
    "fr-outside-no-disposition": lambda r: r["materials"]["stopped"]["items"][1].pop("disposition"),
    "fr-bad-verdict": lambda r: r["unresolved"][0].update(verdict="たぶん書き落とし"),
    "fr-round-zero": lambda r: r.update(round=0),
    "fr-no-size": lambda r: r.pop("size"),
    "fr-empty-errands": lambda r: r.update(errands=[]),
    "fr-writeup-no-written": lambda r: r["unresolved"][0].update(verdict="missing_writeup"),
    # 収束の阻害（exit 1）
    "fr-not-asked": lambda r: r["materials"].__setitem__(
        "skipped", {"status": "not_asked", "reason": "聞き忘れた"}
    ),
    "fr-errand-lost": lambda r: r["errands"][0].update(found=False, reached=""),
    "fr-writeup-unwritten": lambda r: r["unresolved"][0].update(
        verdict="missing_writeup", written=False
    ),
    "fr-git-unchecked": lambda r: r.update(git_status_match=False),
}
for name, mutate in MUT.items():
    rec = json.loads(json.dumps(r1))
    mutate(rec)
    (work / f"{name}.json").write_text(json.dumps(rec, ensure_ascii=False), encoding="utf-8")

# 周をまたぐ検査は 2 周目の側を壊す。
same = json.loads(json.dumps(r1)); same["round"] = 2
(work / "fr-same-stuck.json").write_text(json.dumps(same, ensure_ascii=False), encoding="utf-8")

new = json.loads(json.dumps(r2))
new["materials"]["stopped"]["items"].append(
    {"key": "rollback/前提が逆順", "verbatim": "戻す手順が、出す手順を読んだ前提で書かれていた",
     "in_scope": True}
)
(work / "fr-new-stuck.json").write_text(json.dumps(new, ensure_ascii=False), encoding="utf-8")

# 削除も移動も無いまま行数だけ増えた周。**阻害要因ではないが報せる。**
grew = json.loads(json.dumps(r2))
grew["size"] = {"lines_before": 138, "lines_after": 150}
grew["removed"] = []
grew["moved"] = []
(work / "fr-grew-only.json").write_text(json.dumps(grew, ensure_ascii=False), encoding="utf-8")
PY

expect_output 0 "これは収束の宣言ではない" "阻害なしを収束と名乗らない（初読記録）" \
    "$PY_BIN" "$FR" "$WORK/fr-2.json" "$WORK/fr-1.json"

while IFS='|' read -r m msg; do
    [ -n "$m" ] || continue
    expect_output 2 "$msg" "不正な初読記録は 1 と区別して落ちる: $m" "$PY_BIN" "$FR" "$WORK/$m.json"
done <<'CASES'
fr-drop-materials|必須の欄 'materials' が無い
fr-drop-skipped|素材 'skipped' の返答が無い
fr-none-without-asked|status=none なので 'asked' が要る
fr-item-no-key|key が無い
fr-item-no-verbatim|読み役の原文
fr-pre-answers-gone|'pre_answers' の指す先が無い
fr-no-profile|前提の線を引かない
fr-no-scope|'scope' が空
fr-no-in-scope|'in_scope' が真偽値でない
fr-outside-no-disposition|'disposition'（行き先
fr-bad-verdict|verdict が不正
fr-round-zero|'round' が 1 以上でない
fr-no-size|'size' が object でない
fr-empty-errands|'errands' が空
fr-writeup-no-written|書き足したかの 'written' が要る
CASES

while IFS='|' read -r m msg; do
    [ -n "$m" ] || continue
    expect_output 1 "$msg" "収束の偽装は 2 と区別して報せる: $m" "$PY_BIN" "$FR" "$WORK/$m.json"
done <<'CASES'
fr-not-asked|素材 'skipped' を聞いていない
fr-errand-lost|用事が片づいていない
fr-writeup-unwritten|書き落としのまま
fr-git-unchecked|書き換えていないことを確かめていない
CASES

expect_output 0 "範囲の外へ出したもの" "範囲外の詰まりは 2 周続いても収束を妨げない（行き先だけ報せる）" \
    "$PY_BIN" "$FR" "$WORK/fr-2.json" "$WORK/fr-1.json"
expect_output 1 "同じ場所でまた詰まった" "直し方が効いていないことを報せる" \
    "$PY_BIN" "$FR" "$WORK/fr-same-stuck.json" "$WORK/fr-1.json"
expect_output 1 "新しい詰まり" "新規の詰まりは収束を妨げる" \
    "$PY_BIN" "$FR" "$WORK/fr-new-stuck.json" "$WORK/fr-1.json"
expect_output 0 "足す側に偏っている" "削除も移動も無い増加を報せる（阻害要因にはしない）" \
    "$PY_BIN" "$FR" "$WORK/fr-grew-only.json" "$WORK/fr-1.json"
expect_exit 2 "引数なしは 1 と区別して落ちる（初読記録）" "$PY_BIN" "$FR"

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
# 引数の誤りも計測不成立なので 2。bash の `${1:?...}` は exit 1 になるため使えない。
expect_output 2 "usage" "引数なしは 1 と区別して落ちる" \
    bash -c "cd '$REPO' && bash '$ROOT/scripts/comment-ratio.sh'"
expect_output 2 "usage" "引数が多すぎる場合も 1 と区別して落ちる" \
    bash -c "cd '$REPO' && bash '$ROOT/scripts/comment-ratio.sh' HEAD HEAD extra"
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

# 手順書の文言が `-R` 無しに戻ったことを検知できるのはこの検査だけ（実行時の付け忘れは
# 縛れない）。`-R` を要求する理由は `docs/customize.md`「fork 運用・複数アカウント」が正本。
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
for f in [*(root/"commands").glob("*.md"), *(root/"agents").glob("*.md")]:
    body = f.read_text(encoding="utf-8")
    for name in re.findall(r"`REVIEW\.md`\s*(?:の)?\s*[「『]([^」』]+)[」』]", body):
        if not any(name in k for k in known):
            missing.add(f"{f.name}: 「{name}」")
assert not missing, "REVIEW.md に無いセクションを参照している: " + " / ".join(sorted(missing))
PY

expect_exit 0 "役割 agent の定義と手順書の参照が整合する" "$PY_BIN" - "$ROOT" <<'PY'
import re, sys, pathlib
root = pathlib.Path(sys.argv[1])
# 遮断系は道具ゼロで起動する。`tools: []` が「道具なし」、行ごと省くと全道具を継承、
# 列挙した全部が解決できないときだけ起動拒否——という区別は実測で確かめた
# （2026-08-21・Claude Code 2.1.238・`claude -p` で `tools: []` の agent は Read に失敗、
# `tools: Read` の agent は読めた）。
BLIND = {"cold-reader", "blind-judge"}
WRITE_TOOLS = {"Edit", "Write", "NotebookEdit"}
agents = {}
for f in sorted((root / "agents").glob("*.md")):
    m = re.match(r"---\n(.*?)\n---\n", f.read_text(encoding="utf-8"), re.S)
    assert m, f"{f.name}: frontmatter が無い"
    fm = dict(re.findall(r"^([a-zA-Z-]+):[ \t]*(.*)$", m.group(1), re.M))
    for key in ("name", "description", "model", "effort", "tools"):
        assert fm.get(key) is not None, f"{f.name}: frontmatter に {key} が無い"
    assert fm["name"] == f.stem, f"{f.name}: name '{fm['name']}' が filename と違う"
    assert fm["model"] in ("sonnet", "opus", "haiku"), f"{f.name}: model が不正: {fm['model']}"
    assert fm["effort"] in ("low", "medium", "high", "xhigh", "max"), f"{f.name}: effort が不正: {fm['effort']}"
    raw = fm["tools"].strip()
    assert raw, f"{f.name}: tools が空文字——省略と同じで全道具を継承する。道具なしは `tools: []` と 1 行で書け（複数行の配列も不可）"
    # CSV（`Read, Glob`）と YAML 配列（`["Read", "Glob"]`）はどちらも Claude Code が受ける。片方だけ
    # 解くと、もう片方で書いた書く道具が素通りする。スコープ付き（`Write(docs/*)`）は括弧の前で切る。
    tools = [t for t in (re.sub(r"\(.*", "", x.strip().strip("\"'")).strip() for x in raw.strip("[]").split(",")) if t]
    # 「書き換えるな」を言い渡しでなく定義で担保する——どの役にも書く道具を渡さない
    assert not (WRITE_TOOLS & set(tools)), f"{f.name}: 書く道具を持っている: {sorted(WRITE_TOOLS & set(tools))}"
    agents[fm["name"]] = tools
assert agents, "agents/ が空"
for n in sorted(BLIND):
    assert n in agents, f"遮断系の役 {n} が無い"
    assert agents[n] == [], f"{n} は道具を持ってはいけない: {agents[n]}"

# 存在検査は手順書と文書のどこに識別子が出ても効かせる。使用検査（孤児の検出）は手順書だけ——
# README は全役の一覧表を持つので、含めると孤児が原理的に出なくなる。手順書側の語彙宣言行
# （「以降 `X` と書いたものは…」）も全役を列挙するので、同じ理由で使用に数えない。
commands = list((root / "commands").glob("*.md"))
for f in [*commands, root / "docs" / "customize.md", root / "README.md"]:
    for name in re.findall(r"convergence-loops:([a-z][a-z-]*)", f.read_text(encoding="utf-8")):
        assert name in agents, f"{f.name}: 存在しない役割 convergence-loops:{name} を参照している"
referenced = set()
for f in commands:
    body = f.read_text(encoding="utf-8")
    for line in body.splitlines():
        if "と書いたものは" in line:
            continue
        referenced |= {n for n in re.findall(r"`([a-z][a-z-]*)`", line) if n in agents}
    # 役割に寄せた以上、汎用 agent とモデル名の写し（`model:` の形でも散文でも）を手順書に戻すな（正本は agents/）
    assert "general-purpose" not in body, f"{f.name}: subagent_type: general-purpose が戻っている"
    hit = re.search(r"(?i)\b(sonnet|opus|haiku|fable)\b", body)
    assert not hit, f"{f.name}: モデル名の写しが戻っている: {hit.group(0)}"
    # 役名の無い起動は既定 subagent に落ち、モデルも道具も継承する（遮断が崩れる）。孤児検査は
    # 「役が一度も使われない」しか見ないので、「X を起動」の X が役名であることを別に見る。
    # 見るのはこの語形だけ——doctor / research は「checker＝`inspector`」の形で役を束ねる。
    for tok in re.findall(r"([^\s、。」（(]+)\s*を起動", body):
        assert tok.strip("*") in {f"`{n}`" for n in agents}, f"{f.name}: 役名の付いていない起動がある: 「{tok} を起動」"
orphans = set(agents) - referenced
assert not orphans, "どの手順書からも使われない役割がある: " + ", ".join(sorted(orphans))
PY

expect_exit 0 "配布物に固有の技術名が混ざっていない" "$PY_BIN" - "$ROOT" <<'PY'
import re, sys, pathlib
root = pathlib.Path(sys.argv[1])
# 特定プロジェクト由来の名前が観点側に残ると、そのリポジトリでしか意味を持たない写しになる。
banned = re.compile(r"FastAPI|next-intl|config_kit|DeepAgents|asyncio_mode|guided-resolver")
hits = []
for f in [root/"REVIEW.md", root/"README.md", *(root/"commands").glob("*.md"), *(root/"agents").glob("*.md"), *(root/"docs").glob("*.md")]:
    for i, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
        if banned.search(line):
            hits.append(f"{f.name}:{i}")
assert not hits, "固有の技術名が残っている: " + " / ".join(hits)
PY

# 検査が空振りした場合を「合格」と区別する（対象が空でも緑になる穴を塞ぐ）。
# **これは下限で、総数の台帳ではない**——「意味のある検査を消して些末なものを足す」形の
# 劣化は検知しない（それを見るのは人のレビュー）。件数を他所に書き写すな（腐る）。
EXPECTED_MIN=160
# ---- coldread ゲート ------------------------------------------------------
# 読み役は COLDREAD_READER_CMD のスタブに差し替えて検査する(CI に claude も Keychain も無い)。
# allow 系は「出力が空」を ALLOW_EMPTY の目印に変換して検査する(空文字の contains は恒真のため)。
# 実際の LLM 読み役を通した実測は配布前に手元で行う。
CR_CASE="$ROOT/tests/coldread-case.sh"
CR_CFG="$WORK/coldread-cfg"; mkdir -p "$CR_CFG"
CR_PAD=$("$PY_BIN" -c "print('x'*420)")
# 生成側の stdout を UTF-8 に固定する。Windows の既定 code page(cp1252/cp932)では
# 日本語が UnicodeEncodeError で落ち、CR_BODY が空のまま以降のテストが走っていた
# (日本語本文の検査が実質 x の羅列になる)。
CR_BODY=$(PYTHONIOENCODING=utf-8 "$PY_BIN" -c "print('これは検査対象の本文です。'*20)")
if [ "${#CR_BODY}" -lt 200 ]; then
    echo "  FAIL テスト土台: CR_BODY が生成できていない(長さ ${#CR_BODY})"
    fail=1
fi
CR_POST="gh issue comment 1 --body-file - <<'EOF'
$CR_BODY
$CR_PAD
EOF"
CR_STUB_CLEAN='cat >/dev/null; echo CLEAN'
CR_STUB_BLOCK='cat >/dev/null; printf "詰まり: F3 が何か本文で解決できない\n疑問: 期限はいつか\n"'
CR_STUB_QUEST='cat >/dev/null; printf "疑問: 期限はいつか\n"'
CR_STUB_FAIL='cat >/dev/null; exit 1'

echo "coldread ゲート:"
expect_output 0 "ALLOW_EMPTY" "投稿以外の長いコマンドは素通し" \
    "$CR_CASE" "$CR_CFG" "$CR_STUB_FAIL" "git status && echo $CR_PAD"
expect_output 0 "ALLOW_EMPTY" "gh の読み取りは素通し" \
    "$CR_CASE" "$CR_CFG" "$CR_STUB_FAIL" "gh pr view 12 --json state # $CR_PAD"
expect_output 0 "ALLOW_EMPTY" "400 文字未満の返信は素通し" \
    "$CR_CASE" "$CR_CFG" "$CR_STUB_FAIL" "gh issue comment 1 --body 'ありがとうございます'"
expect_output 0 "ALLOW_EMPTY" "COLDREAD_SKIP=1 は通る" \
    "$CR_CASE" "$CR_CFG" "$CR_STUB_FAIL" "COLDREAD_SKIP=1 $CR_POST"
expect_output 0 "COLDREAD_SKIP" "skip は記録に残る" \
    cat "$CR_CFG/coldread-gate/skip.log"
expect_output 0 "取り出せない" "本文を取り出せない形は deny" \
    "$CR_CASE" "$CR_CFG" "$CR_STUB_FAIL" "gh issue comment 1 --body-file /tmp/real.md # $CR_PAD"
expect_output 0 "ALLOW_EMPTY" "読み役が CLEAN なら通る" \
    "$CR_CASE" "$CR_CFG" "$CR_STUB_CLEAN" "$CR_POST"
expect_output 0 "詰まり" "読み役の詰まりで deny になり指摘が載る" \
    "$CR_CASE" "$CR_CFG" "$CR_STUB_BLOCK" "$CR_POST"
expect_output 0 "残った疑問" "疑問のみなら通り、申し送りが載る" \
    "$CR_CASE" "$CR_CFG" "$CR_STUB_QUEST" "$CR_POST"
expect_output 0 "読み役の起動に失敗" "読み役の故障は deny+案内(投稿不能にはしない)" \
    "$CR_CASE" "$CR_CFG" "$CR_STUB_FAIL" "$CR_POST"
# 網: 「本文を運ぶ旗」を、ヒアドキュメント盾置換+shlex トークン化+単純コマンド単位の帰属で見る
CR_NOTES="gh release create v9.9.9 --notes-file - <<'EOF'
$CR_BODY
$CR_PAD
EOF"
expect_output 0 "詰まり" "release create --notes-file も網に入る" \
    "$CR_CASE" "$CR_CFG" "$CR_STUB_BLOCK" "$CR_NOTES"
expect_output 0 "詰まり" "issue close --comment も網に入る" \
    "$CR_CASE" "$CR_CFG" "$CR_STUB_BLOCK" "gh issue close 9 --comment '$CR_BODY $CR_PAD'"
expect_output 0 "ALLOW_EMPTY" "gh api graphql の長い読み取りは巻き込まない" \
    "$CR_CASE" "$CR_CFG" "$CR_STUB_FAIL" "gh api graphql -f query='query { repository { pullRequest { comments(first: 50) { nodes { body } } } } } # $CR_PAD'"
expect_output 0 "詰まり" "--body の長文が読み役に届く" \
    "$CR_CASE" "$CR_CFG" "$CR_STUB_BLOCK" "gh issue comment 1 --body '$CR_BODY $CR_PAD'"
expect_output 0 "詰まり" "-b 短縮形も網に入る" \
    "$CR_CASE" "$CR_CFG" "$CR_STUB_BLOCK" "gh pr comment 1 -b '$CR_BODY $CR_PAD'"
CR_FDASH="gh issue comment 1 -F - <<'EOF'
$CR_BODY
$CR_PAD
EOF"
expect_output 0 "詰まり" "-F - (--body-file 短縮形)のヒアドキュメントも網に入る" \
    "$CR_CASE" "$CR_CFG" "$CR_STUB_BLOCK" "$CR_FDASH"
expect_output 0 "詰まり" "release create -n 短縮形も網に入る" \
    "$CR_CASE" "$CR_CFG" "$CR_STUB_BLOCK" "gh release create v1 -n '$CR_BODY $CR_PAD'"
expect_output 0 "詰まり" "gh api -f body= も網に入る" \
    "$CR_CASE" "$CR_CFG" "$CR_STUB_BLOCK" "gh api repos/o/r/issues/1/comments -f body='$CR_BODY $CR_PAD'"
CR_JSON_POST="gh api repos/o/r/issues/1/comments --input - <<'EOF'
{\"body\": \"$CR_BODY $CR_PAD\"}
EOF"
expect_output 0 "詰まり" "--input - の JSON 本文も網に入る" \
    "$CR_CASE" "$CR_CFG" "$CR_STUB_BLOCK" "$CR_JSON_POST"
expect_output 0 "詰まり" "graphql の mutation は網に入る(長い文字列リテラル)" \
    "$CR_CASE" "$CR_CFG" "$CR_STUB_BLOCK" "gh api graphql -f query='mutation { addComment(input:{subjectId:\"x\", body:\"$CR_BODY $CR_PAD\"}) }'"
expect_output 0 "詰まり" "列挙に無いサブコマンドでも本文の旗があれば網に入る" \
    "$CR_CASE" "$CR_CFG" "$CR_STUB_BLOCK" "gh discussion comment 1 --body '$CR_BODY $CR_PAD'"
expect_output 0 "詰まり" "複合コマンド中の gh も判定する" \
    "$CR_CASE" "$CR_CFG" "$CR_STUB_BLOCK" "cd /tmp && gh issue comment 1 --body '$CR_BODY $CR_PAD'"
expect_output 0 "詰まり" "小文字・数字入りの環境変数前置でも gh を見失わない" \
    "$CR_CASE" "$CR_CFG" "$CR_STUB_BLOCK" "x1=1 gh issue comment 1 --body '$CR_BODY $CR_PAD'"
CR_GIST="gh gist create - <<'EOF'
$CR_BODY
$CR_PAD
EOF"
expect_output 0 "詰まり" "gist create - のヒアドキュメントも網に入る" \
    "$CR_CASE" "$CR_CFG" "$CR_STUB_BLOCK" "$CR_GIST"
# 帰属の負例: 旗が gh 以外のコマンドに付いていても巻き込まない
expect_output 0 "ALLOW_EMPTY" "別コマンドの -b を gh の旗と誤認しない" \
    "$CR_CASE" "$CR_CFG" "$CR_STUB_FAIL" "gh pr list --limit 100 && git checkout -b feature/x && echo '$CR_PAD'"
expect_output 0 "ALLOW_EMPTY" "引用の中の gh はコマンドと見なさない" \
    "$CR_CASE" "$CR_CFG" "$CR_STUB_FAIL" "grep -r 'gh issue comment --body' . # $CR_PAD"
# --comment が真偽旗と分かっていないと、次の -b を値として食い、本文が位置引数に落ちて取りこぼす
expect_output 0 "詰まり" "pr review の --comment は真偽旗なので後続の -b を本文として拾う" \
    "$CR_CASE" "$CR_CFG" "$CR_STUB_BLOCK" "gh pr review 12 --comment -b '$CR_BODY $CR_PAD'"
expect_output 0 "ALLOW_EMPTY" "pr review の --comment 自体は本文扱いしない" \
    "$CR_CASE" "$CR_CFG" "$CR_STUB_FAIL" "gh pr review 12 --comment # $CR_PAD"
# 検査できない本文は fail-closed で止める
# 旗表・帰属の各分岐を個別に殺す網(消すとどれか 1 件だけが赤くなる形にする)
expect_output 0 "詰まり" "--旗=値 の密着形も網に入る" \
    "$CR_CASE" "$CR_CFG" "$CR_STUB_BLOCK" "gh issue comment 1 --body='$CR_BODY $CR_PAD'"
expect_output 0 "詰まり" "-b 値 の密着形も網に入る" \
    "$CR_CASE" "$CR_CFG" "$CR_STUB_BLOCK" "gh issue comment 1 -b'$CR_BODY $CR_PAD'"
expect_output 0 "詰まり" "release create --notes 長形も網に入る" \
    "$CR_CASE" "$CR_CFG" "$CR_STUB_BLOCK" "gh release create v1 --notes '$CR_BODY $CR_PAD'"
expect_output 0 "詰まり" "issue close -c 短縮形も網に入る" \
    "$CR_CASE" "$CR_CFG" "$CR_STUB_BLOCK" "gh issue close 9 -c '$CR_BODY $CR_PAD'"
expect_output 0 "詰まり" "command 前置越しの gh も網に入る" \
    "$CR_CASE" "$CR_CFG" "$CR_STUB_BLOCK" "command gh issue comment 1 --body '$CR_BODY $CR_PAD'"
expect_output 0 "詰まり" "絶対パス起動の gh も網に入る" \
    "$CR_CASE" "$CR_CFG" "$CR_STUB_BLOCK" "/usr/local/bin/gh issue comment 1 --body '$CR_BODY $CR_PAD'"
expect_output 0 "詰まり" "-R 前置があってもサブコマンドを見失わない" \
    "$CR_CASE" "$CR_CFG" "$CR_STUB_BLOCK" "gh -R o/r pr review 12 --comment -b '$CR_BODY $CR_PAD'"
expect_output 0 "詰まり" "-H 前置があっても graphql の mutation を見失わない" \
    "$CR_CASE" "$CR_CFG" "$CR_STUB_BLOCK" "gh api -H 'X-Foo: bar' graphql -f query='mutation { addComment(input:{body:\"$CR_BODY $CR_PAD\"}) }'"
# リダイレクトは区切りではない(演算子と行き先だけを除く)。挟まれた本文を見失えば無検査で通る
expect_output 0 "詰まり" "本文旗の直後のリダイレクトで本文を見失わない" \
    "$CR_CASE" "$CR_CFG" "$CR_STUB_BLOCK" "gh issue comment 5 --body >&2 '$CR_BODY $CR_PAD'"
expect_output 0 "詰まり" "2>&1 を挟んでも本文を見失わない" \
    "$CR_CASE" "$CR_CFG" "$CR_STUB_BLOCK" "gh pr comment 123 --body 2>&1 '$CR_BODY $CR_PAD'"
expect_output 0 "詰まり" "出力リダイレクト付きでも本文を見失わない" \
    "$CR_CASE" "$CR_CFG" "$CR_STUB_BLOCK" "gh issue comment 5 --body '$CR_BODY $CR_PAD' >/dev/null"
# ヒアドキュメントのデリミタ記法(gh --help や人が実際に書く形)
expect_output 0 "詰まり" '二重引用符デリミタのヒアドキュメントも網に入る' \
    "$CR_CASE" "$CR_CFG" "$CR_STUB_BLOCK" "gh issue comment 1 --body-file - <<\"EOF\"
$CR_BODY
$CR_PAD
EOF"
expect_output 0 "詰まり" "ハイフン入りデリミタのヒアドキュメントも網に入る" \
    "$CR_CASE" "$CR_CFG" "$CR_STUB_BLOCK" "gh issue comment 1 --body-file - <<'JSON-EOF'
$CR_BODY
$CR_PAD
JSON-EOF"
# 本文でない値を読み役へ送らない・投稿でない gh を止めない
# 読み役に渡るのが JSON の殻だと、初見の読み手は本文でなくエスケープ済みの構造を読まされる
CR_STUB_SHELL='if grep -q body; then printf "詰まり: JSON の殻が読み役に渡った\\n"; else echo CLEAN; fi'
expect_output 0 "ALLOW_EMPTY" "--input - の JSON は殻でなく .body が読み役に届く" \
    "$CR_CASE" "$CR_CFG" "$CR_STUB_SHELL" "$CR_JSON_POST"
# 解析を打ち切る上限。超える入力を素通しにすると、長さで検査を外せる。
# あわせて「解析中の想定外の例外は deny に倒す」も検査する(上限超過は ValueError 以外で投がる)
expect_output 0 "COLDREAD_MAX_LEN" "上限を超える長さのコマンドは deny し、上げ方を案内する" \
    env COLDREAD_MAX_LEN=300 "$CR_CASE" "$CR_CFG" "$CR_STUB_FAIL" "gh issue comment 1 --body '$CR_BODY $CR_PAD'"
# 引用が閉じない形は解析器が None を返す経路(例外ではない)
expect_output 0 "解析できない" "引用が閉じないコマンドは deny(fail-closed)" \
    "$CR_CASE" "$CR_CFG" "$CR_STUB_FAIL" "gh issue comment 1 --body '$CR_BODY $CR_PAD"
# 解析器が例外を投げる経路。実物の入力で非 ValueError を起こす手段は Python の版に依存する
# ため、解析器を代役に差し替えて倒れ先だけを固定する
expect_output 0 "解析できない" "解析が例外で落ちても deny(fail-closed)" \
    "$PY_BIN" "$ROOT/tests/coldread-raise-case.py"
# 読み役の中で発火すると、読み役が読み役を起こす入れ子になる(外側はタイムアウトで無検査通過)
expect_output 0 "ALLOW_EMPTY" "読み役の中では発火しない(入れ子を作らない)" \
    env COLDREAD_IN_READER=1 "$CR_CASE" "$CR_CFG" "$CR_STUB_FAIL" "gh issue comment 1 --body '$CR_BODY $CR_PAD'"
# 短縮形は綴りが同じでも意味が違う。投稿でないサブコマンドの -b/-c/-n を本文と誤認すると、
# ローカル操作の引数が読み役(外部プロセス)へ渡り、的外れな deny で作業も止まる
expect_output 0 "ALLOW_EMPTY" "pr checkout の -b(ブランチ名)は本文扱いしない" \
    "$CR_CASE" "$CR_CFG" "$CR_STUB_FAIL" "gh pr checkout 123 -b $CR_BODY$CR_PAD"
expect_output 0 "ALLOW_EMPTY" "issue develop の -n(ブランチ名)は本文扱いしない" \
    "$CR_CASE" "$CR_CFG" "$CR_STUB_FAIL" "gh issue develop 5 -n $CR_BODY$CR_PAD"
expect_output 0 "ALLOW_EMPTY" "issue view の -c(--comments)は本文扱いしない" \
    "$CR_CASE" "$CR_CFG" "$CR_STUB_FAIL" "gh issue view 12 -c # $CR_PAD $CR_BODY"
expect_output 0 "詰まり" "close の -c(--comment)は本文として拾う" \
    "$CR_CASE" "$CR_CFG" "$CR_STUB_BLOCK" "gh issue close 9 -c '$CR_BODY $CR_PAD'"
# gh api --input の中身は本文とは限らない(secrets の暗号値等)。.body を持つときだけ読ませる
expect_output 0 "ALLOW_EMPTY" "api --input の本文でない JSON は読み役に送らない" \
    "$CR_CASE" "$CR_CFG" "$CR_STUB_FAIL" "gh api -X PUT /repos/o/r/actions/secrets/K --input - <<'EOF'
{\"encrypted_value\": \"$CR_PAD$CR_PAD\", \"key_id\": \"1\"}
EOF"
# secret/variable set は長い旗まで --body なので、綴りだけでは投稿と見分けられない
expect_output 0 "ALLOW_EMPTY" "secret set の値(--body)は読み役に送らない" \
    "$CR_CASE" "$CR_CFG" "$CR_STUB_FAIL" "gh secret set DEPLOY_KEY --body '$CR_BODY $CR_PAD'"
expect_output 0 "ALLOW_EMPTY" "variable set の値(--body)は読み役に送らない" \
    "$CR_CASE" "$CR_CFG" "$CR_STUB_FAIL" "gh variable set CONF --body '$CR_BODY $CR_PAD'"
expect_output 0 "ALLOW_EMPTY" "workflow run の -F は本文ではないので止めない" \
    "$CR_CASE" "$CR_CFG" "$CR_STUB_FAIL" "gh workflow run deploy.yml -F name=scully -F greeting=hello # $CR_PAD"
expect_output 0 "ALLOW_EMPTY" "gist create の説明文(-d)だけでは本文と見なさない" \
    "$CR_CASE" "$CR_CFG" "$CR_STUB_FAIL" "gh gist create -d '$CR_BODY $CR_PAD' # $CR_PAD"
# 部分文字列で拾うと、gh コマンドの無い長文が「解析できない」で止まる(引用未終端で判別できる)
expect_output 0 "ALLOW_EMPTY" "gh を含む語(highlight 等)だけでは解析に入らない" \
    "$CR_CASE" "$CR_CFG" "$CR_STUB_FAIL" "echo it's a highlight of the day # $CR_PAD"
# 検査できない本文は、読める本文が同居していても握り潰さない
expect_output 0 "取り出せない" "読める本文と同居しても実ファイル指定は止める" \
    "$CR_CASE" "$CR_CFG" "$CR_STUB_BLOCK" "gh issue comment 1 --body '$CR_BODY $CR_PAD' && gh pr comment 2 --body-file /tmp/x.md"
expect_output 0 "取り出せない" "--input 実ファイルは検査できないので deny" \
    "$CR_CASE" "$CR_CFG" "$CR_STUB_FAIL" "gh api repos/o/r/issues/1/comments --input /tmp/payload.json # $CR_PAD"
expect_output 0 "取り出せない" "-F 実ファイル(--body-file 短縮形)は検査できないので deny" \
    "$CR_CASE" "$CR_CFG" "$CR_STUB_FAIL" "gh pr create -t T -F /tmp/body.md # $CR_PAD"
expect_output 0 "取り出せない" "パイプの stdin は検査できないので deny" \
    "$CR_CASE" "$CR_CFG" "$CR_STUB_FAIL" "cat /tmp/b.md | gh issue comment 1 --body-file - # $CR_PAD"
expect_output 0 "取り出せない" "変数渡しの本文は検査できないので deny" \
    "$CR_CASE" "$CR_CFG" "$CR_STUB_FAIL" "gh issue comment 1 --body \"\$BODY\" # $CR_PAD"
expect_output 0 "解析できない" "引用が閉じない gh コマンドは deny(fail-closed)" \
    "$CR_CASE" "$CR_CFG" "$CR_STUB_FAIL" "gh issue comment 1 --body 'これは閉じない引用 $CR_PAD"

# 倒れ先の検査: 読み役出力が UTF-8 で読めないときは deny に倒す(復号を errors="replace" に
# 緩めると詰まりマーカーが化けて無音 allow になる——それを赤くする回帰網)
CR_STUB_SJIS='cat >/dev/null; printf "\213\154\202\334\202\350\072\040\223\307\202\337\202\310\202\242\012"'
expect_output 0 "読み役の起動に失敗" "読み役出力が UTF-8 でないときは deny に倒す" \
    "$CR_CASE" "$CR_CFG" "$CR_STUB_SJIS" "$CR_POST"
# stdio の UTF-8 固定を OS 非依存で検査する(reconfigure が消えると cp1252 強制下で
# UnicodeEncodeError → exit 1 = フック素通りになり、この 1 件が赤くなる)
expect_output 0 "詰まり" "stdio を cp1252 に強制しても deny 文言が出る" \
    env PYTHONIOENCODING=cp1252 "$CR_CASE" "$CR_CFG" "$CR_STUB_BLOCK" "$CR_POST"

# 連続 deny: 専用 config で履歴を隔離し「ちょうど 3 回目」で発火する境界を検査する
# (共有 config だと先行テストの deny が積まれ、見る回数が先行テストの増減で揺れる)
CR_STREAK_CFG="$WORK/coldread-cfg-streak"; mkdir -p "$CR_STREAK_CFG"
"$CR_CASE" "$CR_STREAK_CFG" "$CR_STUB_BLOCK" "$CR_POST" >/dev/null 2>&1
"$CR_CASE" "$CR_STREAK_CFG" "$CR_STUB_BLOCK" "$CR_POST" >/dev/null 2>&1
expect_output 0 "3 回連続で止まっている" "3 回連続 deny で skip の案内が出る(ちょうど 3 で発火)" \
    "$CR_CASE" "$CR_STREAK_CFG" "$CR_STUB_BLOCK" "$CR_POST"

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
