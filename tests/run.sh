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
# 出力を見ないことが意図の呼び出しが渡す番兵。空文字を「見ない」の合図に使うと、
# 表の行から `|` が落ちて空文字で来たものと区別が付かない。
ANY_OUTPUT='__any_output__'

expect_output() {
    local want_exit=$1 want=$2 desc=$3
    shift 3
    # **期待メッセージが空の呼び出しをここで赤にする。** 空だと下の部分一致が恒真になり、
    # 終了コードだけを見る検査に静かに退化する（冒頭のとおり、その形は個別の検査を消しても
    # 緑のまま通る）。表駆動のループは 9 箇所あって、どの行から `|` が落ちても必ず空文字で
    # ここへ来る——**ガードを入口ごとに書き足すのでなく、全部が通るこの 1 本に持たせる**
    # （入口の片方だけを塞いで残りから通られたのが、この差分が 2 周かけて直した形である）。
    if [ -z "$want" ]; then
        echo "  FAIL $desc — 期待メッセージが空（表の行から | が落ちていないか）"
        fail=1; ran=$((ran + 1)); return
    fi
    local got
    got=$("$@" 2>&1)
    local got_exit=$?
    ran=$((ran + 1))
    if [ "$got_exit" != "$want_exit" ]; then
        echo "  FAIL $desc — exit $want_exit を期待したが $got_exit: $got"
        fail=1
    elif [ "$want" = "$ANY_OUTPUT" ] || [[ "$got" == *"$want"* ]]; then
        echo "  ok   $desc"
    else
        echo "  FAIL $desc — 出力に '$want' が無い: $got"
        fail=1
    fi
}

# 終了コードだけを見る検査。`expect_output` に番兵を渡して委譲する（実行・集計・出力整形を二重に持たない。番兵の理由は上の定義位置）。
expect_exit() {
    local want=$1 desc=$2
    shift 2
    expect_output "$want" "$ANY_OUTPUT" "$desc" "$@"
}

# **空期待ガード自身の腕。** このガードは表駆動ループ 9 箇所すべての恒真化を 1 本で塞いで
# いるのに、それを守るものが何も無かった——検査を守る最後の 1 枚を誰も守っていない形で、
# この差分が 3 周かけて直してきたものと同じである。**副シェルで呼ぶ**——本体の fail / ran を
# 汚さずに、ガードの出力と副作用（実行せずに 1 件だけ赤で数える）だけを見る。
guard_probe=$( fail=0; ran=0; expect_output 2 "" "空期待の番人（この行の出力を検査する）" true
               printf '|ran=%s|fail=%s' "$ran" "$fail" )
ran=$((ran + 1))
case "$guard_probe" in
    *"期待メッセージが空"*"|ran=1|fail=1")
        echo "  ok   期待メッセージが空の呼び出しは、対象を実行せずに赤くなる（恒真に退化しない）" ;;
    *)
        echo "  FAIL 期待メッセージが空の呼び出しが赤にならない: $guard_probe"
        fail=1 ;;
esac

# 記録の一部を壊した JSON を**まとめて 1 プロセスで**書き出す。「壊すと落ちる」ことまで
# 確かめないと、検証が空振りしても合格になる（fail-open）。
#
# **束ねてよいのは素材の生成だけ。** 検査そのものはケースごとに分けたまま——合否が個別に
# 報告されることが要件で、束ねると失敗の切り分けができなくなる。生成を 1 ケース 1 プロセスに
# すると Python の起動コストだけで 26 秒かかる（実測。まとめて 1.2 秒）。
write_broken_records() {
    "$PY_BIN" - "$ROOT" "$WORK" <<'PY'
import json, sys, pathlib

# 手書きの deep copy を 1 本に寄せる（同じ形が 20 箇所に散っていた）。`copy.deepcopy` でなく
# JSON 往復にするのは、**JSON にできない値をここで落とすためではなく、そこで失敗させるため**
# ——固定具は記録として書き出されるので、JSON 化できない値が混ざったら複製の時点で
# TypeError で止まる方がよい（deepcopy は通してしまい、書き出しの段で初めて落ちる）。
def clone(x):
    return json.loads(json.dumps(x))

root, work = pathlib.Path(sys.argv[1]), pathlib.Path(sys.argv[2])
templates = {
    n: json.loads((root / f"templates/{n}.example.json").read_text(encoding="utf-8"))
    for n in ("round-1", "round-2", "round-3")
}


def defer_unit(rec):
    return next(u for u in rec["units"] if u.get("disposition") == "defer")


# 値を書き換えるだけの mutation（round-2 を壊し、round-1 と突合する）。個別の欄の検査を発火させる。
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
    # R1〜R4 の verdict。欄ごと無い・1 つ欠ける・語彙外・役に許されない値。
    "drop-reviews": lambda r: r.pop("reviews"),
    "drop-review-R3": lambda r: r["reviews"].pop("R3"),
    "bad-review-status": lambda r: r["reviews"]["R1"].update(status="looks-fine"),
    "review-only-R2": lambda r: r["reviews"]["R1"].update(status="premise-invalid"),
    "review-only-R34": lambda r: r["reviews"]["R1"].update(status="not_applicable"),
    "pass-without-reason": lambda r: r["reviews"]["R3"].pop("reason"),
    # 持ち越し。from_round が無い・今ラウンド以降を指す・前ラウンドに判定が無い素材から持ち越す。
    "carry-without-from": lambda r: r["materials"]["prior_decisions"].pop("from_round"),
    "carry-from-future": lambda r: r["materials"]["prior_decisions"].update(from_round=2),
    "carry-from-not-applicable": lambda r: r["materials"]["procedure_trace"].update(
        status="carried_over", from_round=1, reason="前と同じ"
    ),
}
# 「型が違う」系。値の書き換えだけでは個別の型検査が一度も発火しない。
TYPE = {
    "bad-round-type": lambda r: r.update(round="2"),
    "bad-round-bool": lambda r: r.update(round=True),
    "round-below-one": lambda r: r.update(round=-100),
    "bad-materials-type": lambda r: r.update(materials=[]),
    "bad-units-type": lambda r: r.update(units={}),
    "bad-unit-type": lambda r: r["units"].__setitem__(0, "not-an-object"),
    "bad-reviews-type": lambda r: r.update(reviews=[]),
    "bad-from-round-type": lambda r: r["materials"]["prior_decisions"].update(from_round="1"),
}
# 個別の検査を通り抜け、末尾の例外境界だけが受け止めるもの。
BOUNDARY = {
    "bad-scalars-type": lambda r: r.update(scalars=["oops"]),
    # `"scalars": null` は JSON として正当なので、falsy 正規化をやめた後は境界の
    # 「想定外の例外」に倒れていた。書き手に何を直せばよいかを伝える診断が要る。
    "null-scalars": lambda r: r.update(scalars=None),
    "unhashable-status": lambda r: r["materials"]["hygiene"].update(status=["found"]),
}


def write(name, rec, num=2, prevs=None):
    """壊した記録を、記録のディレクトリ 1 つとして書き出す（入口はディレクトリだけ）。

    前のラウンドを無傷のテンプレートで埋めるのは、突合（base の一致・持ち越しの連鎖・
    defer 台帳・残存）を発火させる mutation があるため。`prevs` を渡すとその番号だけ差し替える。
    round 欄そのものを壊した mutation も、ファイル名は round-<num> に置く——load_dir が
    「ファイル名の番号と中身の round が違う」で落とす前に validate が走るので、狙った検査は
    変わらず発火する。
    """
    d = work / name
    d.mkdir(exist_ok=True)
    for i in range(1, num):
        r = (prevs or {}).get(i, templates[f"round-{i}"])
        (d / f"round-{i}.json").write_text(json.dumps(r, ensure_ascii=False), encoding="utf-8")
    (d / f"round-{num}.json").write_text(json.dumps(rec, ensure_ascii=False), encoding="utf-8")


for name, mutate in {**VALUE, **TYPE, **BOUNDARY}.items():
    rec = clone((templates["round-2"]))
    mutate(rec)
    write(name, rec)

# 最上位が object でない記録は mutate 関数の形（rec を書き換える）に乗らないので別に書く。
write("not-object", ["not", "an", "object"], num=1)

# 突合（集合演算）は prev だけを走査するので、前ラウンド側の記録を壊す必要がある。
prev = clone((templates["round-1"]))
prev["units"][0]["key"] = ["not", "a", "string"]
write("unhashable-key", templates["round-2"], prevs={1: prev})

# round-1 単独。初回に持ち越しは書けない（from_round が指せるラウンドが無い）。
r1 = clone((templates["round-1"]))
r1["reviews"]["R1"].update(status="carried_over", from_round=1, reason="前と同じ")
write("r1-carry", r1, num=1)

# round-3 を壊し、round-2 と突合する——連鎖・defer 台帳・P-R の飛ばし・停止条件は
# 2 ラウンド目以降の記録でしか発火しない。
def r3(mutate):
    rec = clone((templates["round-3"]))
    mutate(rec)
    return rec

deferred_key = defer_unit(templates["round-2"])["key"]
for name, mutate in {
    # 前ラウンドが round 1 から持ち越しているのに、今ラウンドが round 2 からと書く。
    "carry-chain-broken": lambda r: r["materials"]["prior_decisions"].update(from_round=2),
    # R1 は「台帳に問いが載った周」なので round-3 の実例では pass。持ち越しの連鎖は R2 で見る。
    "review-carry-chain-broken": lambda r: r["reviews"]["R2"].update(from_round=1),
    # 前ラウンドで defer と確定したキーが、新証拠なしに [block] へ上がる。
    "reopen-without-evidence": lambda r: defer_unit(r).update(label="block"),
    # 新証拠つきの再審は記録として正しく、阻害要因（exit 1）として出る。
    "reopen-with-evidence": lambda r: defer_unit(r).update(
        label="block", reopen_evidence="本番ログで上限超過のクエリを 3 件観測"
    ),
    # 阻害要因ゼロなのに R3 が未実施——P-R を飛ばした形。
    "skip-PR": lambda r: r["reviews"]["R3"].update(status="not_applicable", reason="到達せず"),
    "redesign": lambda r: r["reviews"]["R2"].update(status="redesign-needed", reason="機構の規模が実態に対して大きい"),
    # 人に諮る verdict は台帳に問いとして載っていること（載っていない形は q-review-unlisted）。
    "premise-invalid": lambda r: (r["reviews"]["R2"].update(status="premise-invalid", reason="1 デプロイ 1 リポジトリなので記録する問いが無い"),
        r["questions"].append({"key": "解くべき問いが立っているか", "kind": "premise", "origin": "R2",
                               "status": "held", "reason": "judge が仮定を検算中"})),
    "unverifiable": lambda r: (r["reviews"]["R2"].update(status="unverifiable", reason="目的テキストの出典が無い"),
        r["questions"].append({"key": "元の目的をどこから取るか", "kind": "unverifiable", "origin": "R2",
                               "status": "held", "reason": "出典が無い"})),
    "review-not-run": lambda r: r["reviews"]["R4"].update(status="not_run", reason="時間切れ"),
    # 前ラウンドの [block] キーがそのまま残る（stuck）。3 周続くので台帳への記載も要る（無い形は q-stuck-unlisted）。
    "stuck": lambda r: (r["units"].append({"key": templates["round-1"]["units"][0]["key"], "label": "block"}),
        r["questions"].append({"key": "分岐の統合が 2 周直しても残る——処方の誤りか設計か", "kind": "stuck",
                               "origin": templates["round-1"]["units"][0]["key"], "status": "held",
                               "reason": "2 周連続で残った"})),
    # defer のキーが今ラウンドの記録から消えた——台帳には残ることを出力で知らせる。
    "defer-dropped": lambda r: r["units"].remove(defer_unit(r)),
    # 素材の「人の起動待ち」「やるべきだったが飛ばした」。このループが塞いだと主張する穴
    # （無言の省略を「なし」と誤認する）の当の腕で、記録の実例が 1 件も無かった。
    "material-awaiting": lambda r: (r["materials"]["consistency"].update(
        status="awaiting_human", reason="grader が権限エラーで起動できなかった"),
        r["questions"].append({"key": "整合性の grader を誰が起動するか", "kind": "awaiting",
                               "origin": "consistency", "status": "held", "reason": "権限エラー"})),
    "material-not-run": lambda r: r["materials"]["hygiene"].update(
        status="not_run", reason="時間切れで飛ばした"),
    # 同じ key が 1 ラウンドに 2 つ在ると、履歴も台帳も後勝ちで潰れる。
    "dup-key": lambda r: r["units"].append(clone((r["units"][0]))),
    # 「見つけた」と書いた素材が在るのに units が空。
    "found-no-units": lambda r: (
        r["materials"]["local_review"].update(
            status="found", count=3, detail="欠陥レビューが 3 件返した"),
        r["units"].clear(),
        # units を空にすると、今ラウンドに初出の defer（split の origin）は台帳にも無くなる。
        # 見たいのは「found なのに units が空」なので、その問いだけ外す（前ラウンドから
        # 続く fork は defer 台帳に origin が在るので残せる）。
        r["questions"].__setitem__(slice(None), [q for q in r["questions"] if q["kind"] != "split"])),
}.items():
    # stuck は round-2 側にも同じ [block] が在ることが前提なので、そこだけ差し替える。
    r2 = clone((templates["round-2"]))
    r2["units"].append({"key": templates["round-1"]["units"][0]["key"], "label": "block"})
    write(name, r3(mutate), num=3, prevs={2: r2} if name == "stuck" else None)

# 問いの台帳（1 ラウンド内）。何が不正かは下の CASES 表と review-record.py の診断文が持つ。
def add_q(r, **q):
    r["questions"].append(q)
# この節と、下の周またぎの節の両方で使う（同じ値を 2 度定義しない）。
BK = "src/api/limit.py:apply — 上限が効かない"
NIT_KEY = next(u["key"] for u in templates["round-2"]["units"] if u["label"] == "nit")
for name, mutate in {
    "q-split-on-do-now": lambda r: (add_q(r, key="別 PR に積むか", kind="split", origin=defer_unit(r)["key"],
                                          status="held", reason="目的の外"),
                                    defer_unit(r).update(disposition="do-now")),
    # do-now でなく **label が block** の腕。上の q-split-on-do-now は suggest/do-now しか通さない。
    "q-split-on-block": lambda r: (r["units"].append({"key": BK, "label": "block"}),
        add_q(r, key="別 PR に積むか", kind="split", origin=BK, status="held", reason="目的の外")),
    "q-bad-kind": lambda r: add_q(r, key="x", kind="skip", origin=NIT_KEY, status="held", reason="r"),
    "q-bad-status": lambda r: add_q(r, key="x", kind="rule", origin=NIT_KEY, status="pending", reason="r"),
    "q-without-reason": lambda r: add_q(r, key="x", kind="rule", origin=NIT_KEY, status="held"),
    "q-fork-one-option": lambda r: add_q(r, key="x", kind="fork", origin=defer_unit(r)["key"],
                                         status="held", reason="r", options=["(A) だけ"]),
    "q-resolved-without-resolution": lambda r: add_q(r, key="x", kind="rule", origin=NIT_KEY,
                                                     status="resolved", reason="r"),
    "q-origin-missing": lambda r: add_q(r, key="x", kind="fork", origin="src/none.py — 無い",
                                        status="held", reason="r", options=["(A) a", "(B) b"]),
    "q-awaiting-unlisted": lambda r: (r["questions"].clear(),
        r["materials"]["main_path_observation"].update(status="awaiting_human", reason="実機が要る")),
    "q-awaiting-origin-clean": lambda r: add_q(r, key="x", kind="awaiting", origin="hygiene", status="held", reason="r"),
    "q-review-unlisted": lambda r: r["reviews"]["R1"].update(status="unverifiable", reason="出典が無い"),
    "q-premise-origin-mismatch": lambda r: add_q(r, key="x", kind="premise", origin="R2", status="held", reason="r"),
    "q-dup-key": lambda r: (add_q(r, key="x", kind="rule", origin=NIT_KEY, status="held", reason="r"),
                            add_q(r, key="x", kind="rule", origin=NIT_KEY, status="held", reason="r")),
    "q-legacy-ask-human": lambda r: next(u for u in r["units"] if u["label"] == "nit").update(ask_human="rule", reason="r"),
    "q-not-list": lambda r: r.update(questions={}),
    "q-drop": lambda r: r.pop("questions"),
    # 以下は 0.28 で足した検査のうち、腕が無かったもの。腕が無いと、検査を消しても全件緑になる
    # （実測で 6 本がそうだった）。どれも「記録を静かに間違わせる」向きなので、1 本ずつ赤を見る。
    "q-not-object": lambda r: r["questions"].append("問い"),
    "q-no-key": lambda r: add_q(r, kind="rule", origin=NIT_KEY, status="held", reason="r"),
    "q-empty-reason": lambda r: add_q(r, key="x", kind="rule", origin=NIT_KEY, status="held", reason=""),
    "q-depends-type": lambda r: add_q(r, key="x", kind="rule", origin=NIT_KEY, status="held",
                                      reason="r", depends="まとめて 1 本の文字列"),
    "q-fork-options-type": lambda r: add_q(r, key="x", kind="fork", origin=defer_unit(r)["key"],
                                           status="held", reason="r", options="(A) と (B)"),
    "q-origin-field-missing": lambda r: add_q(r, key="x", kind="stuck", status="held", reason="r"),
    "q-awaiting-origin-not-material": lambda r: add_q(r, key="x", kind="awaiting",
                                                      origin="main_path", status="held", reason="r"),
    "q-review-origin-not-r": lambda r: add_q(r, key="x", kind="premise", origin="R9",
                                             status="held", reason="r"),
    # thrash は出どころを持たない種類。origin を許すと、帰属と stuck の縛りをそこから外せる。
    # **depends も同じ入口**——origin だけ塞いでいたとき、ここから開いた [block] 全件に帰属が付いた。
    "q-thrash-with-origin": lambda r: add_q(r, key="x", kind="thrash", origin=NIT_KEY,
                                            status="held", reason="r"),
    "q-thrash-with-depends": lambda r: (r["units"].append({"key": BK, "label": "block"}),
        add_q(r, key="x", kind="thrash", status="held", reason="r", depends=[BK])),
    # 非 unit 域の depends も実在検査に掛かる（綴り違いが黙って無効にならない）。
    # options / depends の「要素の型・空文字」（len < 2 と「配列でない」には腕が在った）。
    "q-fork-options-empty-item": lambda r: add_q(r, key="x", kind="fork", origin=defer_unit(r)["key"],
                                                 status="held", reason="r", options=["(A) a", ""]),
    "q-depends-item-type": lambda r: add_q(r, key="x", kind="rule", origin=NIT_KEY, status="held",
                                           reason="r", depends=[1]),
    # 逆向きの掲載要求の premise 側（unverifiable 側だけ腕が在った。表 1 つに畳んだのは
    # 「逆向きだけ直し忘れたときに落ちない穴」を塞ぐためなのに、順方向の片腕が空いていた）。
    "q-premise-unlisted": lambda r: r["reviews"]["R2"].update(
        status="premise-invalid", reason="解くべき問いが立っていない"),
    "q-awaiting-depends-missing": lambda r: (
        r["materials"]["main_path_observation"].update(status="awaiting_human", reason="実機が要る"),
        add_q(r, key="主経路を誰がどこで動かすか", kind="awaiting", origin="main_path_observation",
              status="held", reason="動かせない", depends=["src/typo.py — 存在しないキー"])),
    # 逆向きの対応表のうち unverifiable 側（premise 側は q-premise-origin-mismatch が見ている）。
    "q-review-origin-status-unverifiable": lambda r: add_q(r, key="x", kind="unverifiable",
                                                           origin="R2", status="held", reason="r"),
    # 問いの key が unhashable。契約（2）を担保するのは末尾の境界だけなので、units 側と同じ
    # 形が questions 側にも要る（非対称のまま放置すると、どちらかだけが守られていると読める）。
    "q-unhashable-key": lambda r: add_q(r, key=["x"], kind="thrash", status="held", reason="r"),
    # 開いたユニットへの帰属禁止は origin だけでなく depends にも当たる。origin を許される先
    # （nit）にしておいて depends から開いた [block] を掴むのが、塞ぎ残しの当の形。
    "q-no-open-via-depends": lambda r: (r["units"].append({"key": BK, "label": "block"}),
        add_q(r, key="どの観点を見直すか", kind="rule", origin=NIT_KEY, status="held",
              reason="同じ指摘が新証拠なく再燃", depends=[BK])),
    # 逆向きの掲載要求も未決で数える。閉じた問いを置いても、素材が人の起動待ちなら満たされない。
    "q-awaiting-listed-resolved": lambda r: (
        r["materials"]["main_path_observation"].update(status="awaiting_human", reason="実機が要る"),
        add_q(r, key="主経路を誰がどこで動かすか", kind="awaiting", origin="main_path_observation",
              status="resolved", reason="起動できなかった", resolution="テスト用設定で起動できる")),
}.items():
    rec = clone((templates["round-2"]))
    mutate(rec)
    write(name, rec)

# ディレクトリ渡し（履歴）。何を見る組かは各 expect_output の説明文が持つ。
def hist(name, recs):
    d = work / name
    d.mkdir()
    for rec in recs:
        (d / f"round-{rec['round']}.json").write_text(json.dumps(rec, ensure_ascii=False), encoding="utf-8")

hist("tmpl-1", [templates["round-1"]])
hist("tmpl-12", [templates["round-1"], templates["round-2"]])
full = [templates["round-1"], templates["round-2"], templates["round-3"]]
hist("hist", full)
hist("hist-gap", [templates["round-1"], templates["round-3"]])
back = clone((templates["round-3"]))
back["units"].append({"key": templates["round-1"]["units"][0]["key"], "label": "nit"})
hist("hist-return", [templates["round-1"], templates["round-2"], back])

def r1_at(n, units):
    r = clone((templates["round-1"]))
    r["round"] = n
    r["units"] = units
    # 中立な土台にする。round-1 の実例が持つ「人の起動待ちの素材と、その問い」を外し、
    # **found の素材も落とす**——found が残ると、units を空にした fixture に「素材が found なのに
    # units が空」という 2 つ目の阻害が常に立ち、帰属を狙った検査が狙いの分岐に決して入らない
    # （実測: その形で、当の欠陥を注入しても全件緑のままだった）。
    for name, m in r["materials"].items():
        if m["status"] in ("found", "awaiting_human"):
            r["materials"][name] = {"status": "clean", "checked": "見たが無かった"}
    r["questions"] = []
    return r

LK = "src/db/pool.py — 接続プールの上限を設定に出す"
# 別のレビュー（基準点が違う）の記録が同じディレクトリに残っている。
mixed = clone((templates["round-2"]))
mixed["base"] = "f" * 40
hist("mixed-base", [templates["round-1"], mixed])

hist("block-dropped", [r1_at(1, [{"key": BK, "label": "block"}]), r1_at(2, [])])

# `human-repeat` と、下の問いの節の `q-review-attribution` は同一内容だった（定数 QU / RUQ も
# 全欄一致）。実体が 1 つなので、1 つのディレクトリに腕を 2 本掛ける形に畳んである。
QU = {"key": "元の目的をどこから取るか", "kind": "unverifiable", "origin": "R1",
      "status": "held", "reason": "出典①②③のどれも無い"}
ch = r1_at(1, [])
ch["reviews"]["R1"] = {"status": "unverifiable", "reason": "目的テキストの出典が取れない"}
ch["questions"] = [QU]
ch2 = r1_at(2, [])
ch2["reviews"]["R1"] = {"status": "carried_over", "from_round": 1,
                        "reason": "再発火条件に当たらないので round 1 の判定を流用"}
hist("carry-from-human", [ch, ch2])
# 正直な書き方＝同じ値をもう一度書く。諮る義務が続いていることが毎ラウンド数えられる。
ch3 = r1_at(2, [])
ch3["reviews"]["R1"] = {"status": "unverifiable", "reason": "出典は今ラウンドも取れていない"}
ch3["questions"] = [QU]
hist("human-repeat", [ch, ch3])

# 問いの台帳の周またぎと帰属。
def with_q(rec, *qs):
    rec["questions"] = list(qs)
    return rec
FQ = {"key": "上限をどこで掛けるか", "kind": "fork", "origin": BK, "status": "held",
      "reason": "共有面に及ぶ", "options": ["(A) 入口 → 全経路に効く", "(B) 各経路 → 漏れる"]}
BK2 = "src/api/sort.py:order — 並び順が指定を無視する"
TWO = [{"key": BK, "label": "block"}, {"key": BK2, "label": "block"}]
STUCK3 = [{"key": BK, "label": "block"}]
hist("q-dropped", [with_q(r1_at(1, [{"key": BK, "label": "block"}]), FQ),
                   r1_at(2, [{"key": BK, "label": "block"}])])
hist("q-dropped-escalate", [
    with_q(r1_at(1, [{"key": BK, "label": "block"}]), dict(FQ, status="escalate")),
    r1_at(2, [{"key": BK, "label": "block"}])])
hist("q-depends-missing", [
    with_q(r1_at(1, TWO), dict(FQ, depends=["src/api/typo.py — 存在しないキー"])),
    with_q(r1_at(2, TWO), dict(FQ, depends=["src/api/typo.py — 存在しないキー"]))])
hist("q-stuck-resolved", [
    r1_at(1, STUCK3), r1_at(2, STUCK3),
    with_q(r1_at(3, STUCK3), dict(FQ, status="resolved", resolution="入口に寄せると決めた"))])
hist("q-stuck-other-kind", [
    r1_at(1, STUCK3), r1_at(2, STUCK3),
    with_q(r1_at(3, STUCK3), {"key": "新規が出続ける", "kind": "thrash",
                              "status": "held", "reason": "件数が落ちない"})])
# ここだけ検査がゼロだと、unverifiable だけが残る周が永久に聞かれない形を誰も止められない。
ru1 = r1_at(1, [])
ru1["reviews"]["R1"] = {"status": "unverifiable", "reason": "目的テキストの出典が取れない"}
ru2 = r1_at(2, [])
ru2["reviews"]["R1"] = {"status": "unverifiable", "reason": "出典は今ラウンドも取れていない"}
RUQ = {"key": "元の目的をどこから取るか", "kind": "unverifiable", "origin": "R1",
       "status": "held", "reason": "出典①②③のどれも無い"}
hist("q-review-attribution", [with_q(ru1, RUQ), with_q(ru2, RUQ)])
# awaiting は雛形に実在する最も普通の問いなのに、ここだけ腕が無かった。
am1 = r1_at(1, [])
am1["materials"]["main_path_observation"] = {"status": "awaiting_human", "reason": "実機が要る"}
am2 = r1_at(2, [])
am2["materials"]["main_path_observation"] = {"status": "awaiting_human", "reason": "今も実機が要る"}
AMQ = {"key": "主経路を誰がどこで動かすか", "kind": "awaiting", "origin": "main_path_observation",
       "status": "held", "reason": "この環境では動かせない"}
hist("q-material-attribution", [with_q(am1, AMQ), with_q(am2, AMQ)])
# 2 周目以降だけに掛けると初回が素通りする。
hist("q-origin-missing-round1", [with_q(r1_at(1, [{"key": BK, "label": "block"}]),
                                        dict(FQ, origin="src/none.py — 無い"))])
PMQ = {"key": "解くべき問いが立っているか", "kind": "premise", "origin": "R2",
       "status": "held", "reason": "judge が仮定を検算中"}
def premise_round(n):
    r = r1_at(n, [{"key": BK, "label": "block"}])
    r["reviews"]["R2"] = {"status": "premise-invalid", "reason": "問いが立っていない"}
    return with_q(r, PMQ)
# 短絡すると文言が「前提不成立が確定（escalate）」に変わるので、この期待で status 条件を縛れる。
hist("q-premise-not-escalate", [premise_round(1), premise_round(2)])
def esc_round(n):
    return with_q(r1_at(n, [{"key": BK, "label": "block"}]), dict(FQ, status="escalate"))
hist("q-escalate-not-premise", [esc_round(1), esc_round(2)])
hist("q-stuck-unlisted", [r1_at(n, [{"key": BK, "label": "block"}]) for n in (1, 2, 3)])
# 帰属は前の周から持ち越した保留にだけ付くので、聞く時を見る fixture は 2 周以上にする。
hist("q-stuck-listed", [r1_at(1, [{"key": BK, "label": "block"}]),
                        with_q(r1_at(2, [{"key": BK, "label": "block"}]), FQ),
                        with_q(r1_at(3, [{"key": BK, "label": "block"}]), FQ)])
hist("q-mixed", [with_q(r1_at(n, TWO), FQ) for n in (1, 2)])
hist("q-depends", [with_q(r1_at(n, TWO), dict(FQ, depends=[BK2])) for n in (1, 2)])
# 立った周には聞かない。同じ形を 1 周だけにすると、帰属でなく「今ラウンドに立った問い」の印が付く。
hist("q-fresh", [with_q(r1_at(1, TWO), dict(FQ, depends=[BK2]))])
pe = r1_at(1, [{"key": BK2, "label": "block"}])
pe["reviews"]["R2"] = {"status": "premise-invalid", "reason": "1 デプロイ＝1 リポジトリなら識別子は要らない"}
hist("q-premise-escalate", [with_q(pe, {"key": "解くべき問いが立っているか", "kind": "premise", "origin": "R2",
                                        "status": "escalate", "reason": "judge が仮定を実態で確かめた——真"})])
# ループが決めた問い（resolved）は帰属しない＝その阻害は「仕事」。**肯定の文言で確かめる**——
# 「出ないこと」を見る形にすると、対象が消えても異常終了しても緑になる（実測でそうなった）。
# 2 周とも held の Q1 は帰属するので、resolved の Q2 が帰属したら「帰属しない 0 件」になって
# 文言が変わる。つまりこの 1 本で、resolved を数えたら赤くなる。
RQ = {"key": "並び順をどう直すか", "kind": "fork", "origin": BK2,
      "reason": "候補が 2 つ", "options": ["(A) 入口", "(B) 各経路"]}
hist("q-resolved-is-work", [
    with_q(r1_at(1, TWO), FQ, dict(RQ, status="held")),
    with_q(r1_at(2, TWO), FQ, dict(RQ, status="resolved", resolution="入口に寄せると決めた")),
])

# 出どころの域が違えば、値が文字列として同じでも別物である。unit の key をリテラル "R2" に
# しても、別の域の問い（premise の origin="R2"）はそのユニットを指したことにならない。
# 平坦な文字列で突き合わせていたとき、これが 3 周続いた [block] の振り分け要求を黙らせる
# 逃げ道だった（実測で再現）。名前を禁じる柵でなく、域を持ち回る構造で保証している。
kc = [r1_at(n, [{"key": "R2", "label": "block"}]) for n in (1, 2, 3)]
kc[2]["reviews"]["R2"] = {"status": "premise-invalid", "reason": "解くべき問いが立っていない"}
kc[2]["questions"] = [{"key": "前提が立っているか", "kind": "premise", "origin": "R2",
                       "status": "held", "reason": "judge が検算中"}]
hist("domain-separation", kc)

nq1 = r1_at(1, [{"key": BK, "label": "block"}])
nq2 = r1_at(2, [{"key": BK, "label": "block"}])
nq2["questions"] = [FQ]
nq2["reviews"]["R1"] = {"status": "carried_over", "from_round": 1, "reason": "機構の追加なし"}
hist("q-new-r1-carried", [nq1, nq2])
nq2b = clone((nq2))
nq2b["reviews"]["R1"] = {"status": "pass", "reason": "台帳に問いが載ったので再発火。監査した"}
hist("q-new-r1-ran", [nq1, nq2b])
nq1c = clone((nq1)); nq1c["questions"] = [FQ]
hist("q-carried-r1-carried", [nq1c, nq2])
# 同じ key のまま kind / origin / options を総取り替えする（key の新規性では捕まらない形）。
sw2 = clone((nq2))
sw2["questions"] = [dict(FQ, kind="stuck", origin=BK)]
sw2["questions"][0].pop("options")
hist("q-swap-r1-carried", [nq1c, sw2])
# ループが決めた問いが次の周に未決へ戻る（再燃。key は既出なので「新規」では捕まらない）。
rp1 = clone((nq1))
rp1["questions"] = [dict(FQ, status="resolved", resolution="入口に寄せると決めた")]
hist("q-reopen-r1-carried", [rp1, nq2])

nc = work / "name-case"; nc.mkdir()
(nc / "round-1.json").write_text(json.dumps(r1_at(1, []), ensure_ascii=False), encoding="utf-8")
(nc / "round-2.JSON").write_text(json.dumps(r1_at(2, []), ensure_ascii=False), encoding="utf-8")
# 同じ欠陥の鏡像。受理側を ASCII に狭めただけだと、桁の異体字は「そもそも記録でない」として
# 黙って捨てられる側へ移るだけで、欠陥が入口を移動して残る。
nu = work / "name-unidigit"; nu.mkdir()
(nu / "round-\u0661.json").write_text(json.dumps(r1_at(1, []), ensure_ascii=False), encoding="utf-8")
# 正規表現の軸（桁・英字の大小）では拾えない綴り。区切り・語・拡張子の軸から通る形で、
# **最新ラウンドがこの形だと、記録が 1 つ短いまま「連続 2 ラウンド」の判定に乗る。**
# from_round の下限。**外すと「素材を一度も見ずに連続 2 ラウンド成立」が exit 0 で通る**
# （実測: 全素材と R1/R2 を from_round: 0 にした記録が「round 0 の判定を流用」で収束した）。
# この道具が存在する理由そのものの穴なのに、塞いでいる 1 行に腕が無かった。
fz = work / "from-round-zero"; fz.mkdir()
fz1 = r1_at(1, []); fz2 = r1_at(2, [])
fz2["materials"]["consistency"] = {"status": "carried_over", "from_round": 0, "reason": "流用"}
(fz / "round-1.json").write_text(json.dumps(fz1, ensure_ascii=False), encoding="utf-8")
(fz / "round-2.json").write_text(json.dumps(fz2, ensure_ascii=False), encoding="utf-8")
# 3 周の窓の**幅**。連鎖が r2・r3 だけなので、窓が 3 周なら要求は立たない（exit 1）。
# 窓を 2 周に狭めると要求が立って exit 2 になる＝この 1 本が幅を測る。「対照」と名乗っていた
# stuck-two-rounds は記録が 2 件しか無く、range(2, len(rounds)) に一度も入らなかった。
ww = [r1_at(1, []), r1_at(2, [{"key": BK, "label": "block"}]),
      r1_at(3, [{"key": BK, "label": "block"}])]
hist("stuck-window-width", ww)
# UTF-8 として読めない記録（「開けない」「JSON でない」と別の診断になることを縛る）。
(work / "badenc").mkdir()
(work / "badenc" / "round-1.json").write_bytes(b'{"base": "\xff\xfe"}')
nt = work / "name-tail"; nt.mkdir()
(nt / "round-1.json").write_text(json.dumps(r1_at(1, []), ensure_ascii=False), encoding="utf-8")
(nt / "round_2.json").write_text(json.dumps(r1_at(2, []), ensure_ascii=False), encoding="utf-8")
# 退避先のディレクトリとドットファイルは鳴らさない（下位は読まない規約・OS の成果物）。
nok = work / "name-ok"; nok.mkdir()
(nok / "round-1.json").write_text(json.dumps(r1_at(1, []), ensure_ascii=False), encoding="utf-8")
(nok / "archive-deadbeef").mkdir()
(nok / ".DS_Store").write_text("x", encoding="utf-8")

th2 = r1_at(2, [{"key": BK, "label": "block"}])
th2["questions"] = [{"key": "新規が出続ける", "kind": "thrash", "status": "held", "reason": "件数が落ちない"}]
hist("q-thrash-silent", [r1_at(1, [{"key": BK, "label": "block"}]), th2])

sd = [r1_at(n, TWO) for n in (1, 2, 3)]
sd[2]["questions"] = [dict(FQ, origin=BK2, depends=[BK])]
hist("q-stuck-via-depends", sd)

w4 = [r1_at(n, [{"key": BK, "label": "block"}]) for n in (1, 2, 3, 4)]
w4[2]["questions"] = [dict(FQ, kind="stuck", status="held")]
w4[2]["questions"][0].pop("options")
w4[3]["questions"] = [dict(w4[2]["questions"][0], status="resolved", resolution="入口に寄せると決めた")]
hist("q-stuck-window-slides", w4)
hist("stuck-two-rounds", [r1_at(1, [{"key": BK, "label": "block"}]),
                          r1_at(2, [{"key": BK, "label": "block"}])])

# 縛るのは「まだ聞く気がある問い」だけで、resolved には何も要求しない（緩める向きの 2 本）。
rog = r1_at(1, [{"key": BK, "label": "block"}])
rog["questions"] = [dict(FQ, origin="src/gone.py — 直って消えたキー", status="resolved",
                         resolution="修正で形が変わり岐路が消えた")]
hist("q-resolved-origin-gone", [rog])
rso = r1_at(1, [{"key": BK, "label": "block"}])
rso["questions"] = [{"key": "別 PR に積むか", "kind": "split", "origin": BK, "status": "resolved",
                     "reason": "目的の外に見えた", "resolution": "目的の内側と分かったので本 PR で直す"}]
hist("q-resolved-split-open", [rso])

mid = [r1_at(n, TWO) for n in (1, 2, 3)]
mid[1]["questions"] = [dict(FQ, origin="src/none.py — 無い")]
mid[2]["questions"] = [dict(FQ, origin="src/none.py — 無い")]
hist("q-origin-missing-mid", mid)

hist("round-zero", [r1_at(1, [])])
hist("round-dup", [r1_at(1, []), r1_at(2, [])])
(work / "round-dup" / "round-01.json").write_text(
    json.dumps(r1_at(1, []), ensure_ascii=False), encoding="utf-8")
(work / "round-zero" / "round-0.json").write_text(
    json.dumps(r1_at(1, []), ensure_ascii=False), encoding="utf-8")

cz = clone((templates["round-1"]))
cz["materials"]["local_review"] = {"status": "found", "count": 0, "detail": "0 件だった"}
write("count-zero", cz, num=1)
ce = clone((templates["round-1"]))
ce["materials"]["consistency"] = {"status": "clean", "checked": ""}
write("checked-empty", ce, num=1)
cf = clone((templates["round-1"]))
# **整数は別**——`count: 0` は「見たが 0 件」で正当（その腕は count-zero）。
cf["materials"]["consistency"] = {"status": "clean", "checked": False}
cn = clone((templates["round-1"]))
cn["materials"]["consistency"] = {"status": "clean", "checked": 0}
write("checked-number", cn, num=1)
write("checked-false", cf, num=1)

# defer が 1 ラウンド記録から消えてから [block] で戻る。台帳が隣の 1 ラウンドしか見ないと
# 新証拠なしで素通りし、しかも「（新規）」と事実に反する注記が付いていた。
hist("ledger-gap", [
    r1_at(1, [{"key": LK, "label": "suggest", "disposition": "defer",
               "reason": "共有面を触るので別の変更で扱う"}]),
    r1_at(2, []),
    r1_at(3, [{"key": LK, "label": "block"}]),
])

# JSON として読めない記録と、深いネスト（json モジュールが JSONDecodeError 以外を投げる例）。
for nm, body in (("truncated", '{ "base": '), ("deep", "[" * 100000 + "]" * 100000)):
    (work / nm).mkdir(exist_ok=True)
    (work / nm / "round-1.json").write_text(body, encoding="utf-8")
# 研究記録・診断記録はファイル渡しなので、同じ深いネストを**単体のファイルとしても**置く。
# `$WORK/deep.json` はどこでも作られておらず、それを渡す 2 本の腕は「開けない」で exit 2 に
# なって緑だった——名乗った性質（深いネストでも 1 と区別して落ちる）を一度も測っていない。
(work / "deep.json").write_text("[" * 100000 + "]" * 100000, encoding="utf-8")
# 「開けない」の腕。round-1.json がディレクトリだと open が OSError を投げる。
(work / "unreadable" / "round-1.json").mkdir(parents=True)
PY
}

echo "review-record.py"
R1="$ROOT/templates/round-1.example.json"
R2="$ROOT/templates/round-2.example.json"
R3="$ROOT/templates/round-3.example.json"
# 変数に詰めて展開すると、python のパスにスペースがあるだけで壊れる（Windows で起きる）。
RECORD="$ROOT/scripts/review-record.py"


write_broken_records || { echo "  FAIL 壊した記録を作れない"; fail=1; }

expect_output 1 "前ラウンドの記録が無い" "round-1 だけの記録は、比較の欠落を阻害要因に数える" \
    "$PY_BIN" "$RECORD" "$WORK/tmpl-1"
expect_output 1 "前ラウンドに阻害要因が 4 件あった" "解消した直後のラウンドは連続 2 ラウンドの 1 ラウンド目" \
    "$PY_BIN" "$RECORD" "$WORK/tmpl-12"
# 人に聞く時は機械が帰属で決める。**立った周には帰属しない**ので、round-1 だけの記録では
# 「聞く時」の行がどれも出ず、問いが指している阻害要因に「今ラウンドに立った問い」の印が付く。
expect_output 1 "（今ラウンドに立った問い——再審は次の周）" \
    "問いが立った周には帰属せず、印だけが付く" "$PY_BIN" "$RECORD" "$WORK/tmpl-1"
# **節ごと、行数まで縛る。** 「scalar 'doc_lines': 120 → 135」という綴りは `scalar_changes` と
# `history` の 2 経路から出るので、その 1 行だけを見る形は**どちらを殺しても緑**だった（実測:
# scalar_changes を丸ごと無効化しても、`now > before` を `>=` や `!=` にしても全件緑）。節の
# 見出しは片方しか出さず、直後の 2 行までを期待に含めれば「増えていないものが混ざる」退行も赤になる。
expect_output 1 $'増えた scalar（阻害要因ではない。相殺する削除があるか R1 に見せろ）:\n  - scalar \'doc_lines\': 120 → 135\n  - scalar \'comment_ratio_pct\': 18 → 21\n持ち越し' \
    "増えた scalar だけを、増えた scalar の節に出す" "$PY_BIN" "$RECORD" "$WORK/tmpl-12"
expect_output 0 "連続 2 ラウンド" "2 ラウンド続けて阻害なしなら exit 0" "$PY_BIN" "$RECORD" "$WORK/hist"
expect_output 0 "これは収束の宣言ではない" "阻害なしを収束と名乗らない" "$PY_BIN" "$RECORD" "$WORK/hist"
expect_output 0 "素材 prior_decisions: round 1 の判定を流用（2 ラウンド前）" "持ち越しは実際に見たラウンドと古さを見せる" \
    "$PY_BIN" "$RECORD" "$WORK/hist"


# 記録が不正（exit 2）。1 と混ざると「非収束」と誤読され、収束を永久に宣言できなくなる。
# **期待メッセージまで検査する**（理由は冒頭の expect_output の段）。
while IFS='|' read -r m msg; do
    [ -n "$m" ] || continue
    expect_output 2 "$msg" "不正な記録は 1 と区別して落ちる: $m" "$PY_BIN" "$RECORD" "$WORK/$m"
done <<'CASES'
drop-material|素材 'hygiene' の返答が無い
drop-defer-reason|defer に構造的理由が無い
drop-base|必須の欄 'base' が無い
drop-round|必須の欄 'round' が無い
bad-base|base が違う
bad-round|ファイル名の番号と違う
bad-status|status が不正
clean-without-checked|'checked' が要る
bad-label|label が不正
drop-key|key が無い
drop-reviews|必須の欄 'reviews' が無い
drop-review-R3|R3 の verdict が無い
bad-review-status|R1 の status が不正
review-only-R2|R1 は premise-invalid にできない
review-only-R34|R1 は not_applicable にできない
pass-without-reason|R3 は status=pass なので 'reason' が要る
carry-without-from|'from_round' が要る
carry-from-future|今ラウンド（2）より前でない
carry-from-not-applicable|前ラウンドが not_applicable なので持ち越せない
not-object|記録の最上位が object でない
bad-round-type|'round' が整数でない
bad-round-bool|'round' が整数でない
round-below-one|'round' が 1 以上でない
bad-materials-type|'materials' が object でない
bad-units-type|'units' が配列でない
bad-unit-type|units[0] が object でない
bad-reviews-type|'reviews' が object でない
bad-from-round-type|'from_round' は数で書け
bad-scalars-type|'scalars' が object でない
null-scalars|'scalars' が object でない
unhashable-status|想定外の例外（TypeError）
CASES

expect_output 2 "想定外の例外（TypeError）" "前ラウンドの key が unhashable でも 1 と区別して落ちる" \
    "$PY_BIN" "$RECORD" "$WORK/unhashable-key"
expect_output 2 "今ラウンド（1）より前でない" "初回ラウンドに持ち越しは書けない" \
    "$PY_BIN" "$RECORD" "$WORK/r1-carry"

# 2 ラウンド目以降でしか発火しない突合（round-3 を壊し round-2 と比べる）。
while IFS='|' read -r code m msg; do
    [ -n "$m" ] || continue
    expect_output "$code" "$msg" "前ラウンドとの突合: $m" "$PY_BIN" "$RECORD" "$WORK/$m"
done <<'CASES'
2|carry-chain-broken|持ち越しが連鎖していない
2|review-carry-chain-broken|R2 の from_round（1）が前ラウンド（2）でない
2|reopen-without-evidence|reopen_evidence が無い
1|reopen-with-evidence|既受容 defer の再審。新証拠: 本番ログで上限超過のクエリを 3 件観測
1|skip-PR|R3 が not_applicable だが、P-R への到達を妨げる阻害要因が記録に無い
1|redesign|R2 が redesign-needed
1|premise-invalid|収束を宣言せずユーザーに諮れ
1|unverifiable|収束を宣言せずユーザーに諮れ
1|review-not-run|R4 が not_run
0|defer-dropped|台帳には残る
0|defer-dropped|[人へ] fork
1|material-awaiting|素材 'consistency' が人の起動待ち
1|material-not-run|素材 'hygiene' が未実施
2|dup-key|突合の識別子なので 1 ラウンドに 1 つ
1|found-no-units|素材が found なのに units が空
CASES
expect_output 1 "残存——過去のラウンドにも在った" "同じ [block] キーが 2 ラウンド残れば残存の印を出す" \
    "$PY_BIN" "$RECORD" "$WORK/stuck"

# 問いの台帳（1 ラウンド内）。
while IFS='|' read -r m msg; do
    [ -n "$m" ] || continue
    expect_output 2 "$msg" "問いの台帳: $m" "$PY_BIN" "$RECORD" "$WORK/$m"
done <<'CASES'
q-split-on-do-now|split の origin / depends が [block] / do-now
q-split-on-block|split の origin / depends が [block] / do-now
q-bad-kind|kind が不正
q-bad-status|status が不正
q-without-reason|'reason' が要る
q-fork-one-option|options は選択肢 2 つ以上の配列
q-resolved-without-resolution|'resolution' が要る
q-origin-missing|origin が今ラウンドの units にも defer 台帳にも無い
q-awaiting-unlisted|素材 'main_path_observation' が awaiting_human なのに問いの台帳に無い
q-awaiting-origin-clean|awaiting の origin 'hygiene' が awaiting_human でない
q-review-unlisted|R1 が unverifiable なのに問いの台帳に無い
q-premise-origin-mismatch|premise の origin R2 が premise-invalid でない
q-dup-key|の key が重複: x
q-legacy-ask-human|人に聞く候補は questions（問いの台帳）に
q-not-list|'questions' が配列でない
q-drop|必須の欄 'questions' が無い
q-not-object|questions[2] が object でない
q-no-key|に key が無い（周をまたぐ突合に使う
q-empty-reason|'reason' が空（きっかけ・根拠を書け）
q-depends-type|depends は、この答え待ちで手を止めるユニットの key の配列
q-fork-options-type|options は選択肢 2 つ以上の配列
q-origin-field-missing|なので origin（units の key）が要る
q-awaiting-origin-not-material|なので origin は素材名
q-review-origin-not-r|なので origin は R1〜R4
q-thrash-with-origin|なので origin / depends を持てない
q-thrash-with-depends|なので origin / depends を持てない
q-awaiting-depends-missing|depends が今ラウンドの units にも defer 台帳にも無い
q-fork-options-empty-item|options は選択肢 2 つ以上の配列
q-depends-item-type|depends は、この答え待ちで手を止めるユニットの key の配列
q-premise-unlisted|R2 が premise-invalid なのに問いの台帳に無い
q-review-origin-status-unverifiable|の origin R2 が unverifiable でない
q-no-open-via-depends|rule の origin / depends が [block] / do-now
q-awaiting-listed-resolved|が awaiting_human なのに問いの台帳に無い
q-unhashable-key|想定外の例外（TypeError）
CASES
# 問いの台帳（周またぎ）と、人に聞く時の判定。
expect_output 2 "前ラウンドの問い（held）が今ラウンドの台帳に無い" "保留した問いは黙って落とせない" \
    "$PY_BIN" "$RECORD" "$WORK/q-dropped"
expect_output 2 "前ラウンドの問い（escalate）が今ラウンドの台帳に無い" "人へ回した問いも黙って落とせない" \
    "$PY_BIN" "$RECORD" "$WORK/q-dropped-escalate"
expect_output 2 "depends が今ラウンドの units にも defer 台帳にも無い" \
    "出どころの実在検査は depends にも当たる（綴り違いが黙って無効にならない）" \
    "$PY_BIN" "$RECORD" "$WORK/q-depends-missing"
# 期待は長い文言で。「問いの台帳に無い」は「素材が awaiting_human なのに」「R が … なのに」の
# 2 つの診断にも出るので、短いままだと別の理由で落ちても通る（実測: 中立化を止めた記録では、
# stuck の検査を完全に殺しても exit 2 かつこの語を含んで検査が通った）。
expect_output 2 "2 ラウンド連続の残存＝stuck）のに問いの台帳に無い" \
    "閉じた問い（resolved）では stuck の振り分け要求が満たされない" \
    "$PY_BIN" "$RECORD" "$WORK/q-stuck-resolved"
# この腕が落ちる理由は「kind が違う」ではなく「出どころを持たない種類は origin を書けない」。
# **種類による絞りは機械にもう無い**——出どころの key 空間を分けたので恒真になり、削ってある。
expect_output 2 "2 ラウンド連続の残存＝stuck）のに問いの台帳に無い" \
    "出どころを持たない種類を置いても stuck の振り分け要求は満たされない" \
    "$PY_BIN" "$RECORD" "$WORK/q-stuck-other-kind"
expect_output 1 "残る阻害要因は保留の問いに帰属するものだけ（1 件）" \
    "R1〜R4 の人に諮る verdict も保留の問いに帰属する" \
    "$PY_BIN" "$RECORD" "$WORK/q-review-attribution"
expect_output 1 "（保留の問いに帰属——答えを待っている）" \
    "人の起動待ちの素材も保留の問いに帰属する" \
    "$PY_BIN" "$RECORD" "$WORK/q-material-attribution"
expect_output 2 "origin が今ラウンドの units にも defer 台帳にも無い" \
    "出どころの実在検査は round 1 にも掛かる" \
    "$PY_BIN" "$RECORD" "$WORK/q-origin-missing-round1"
# 前提不成立の短絡は「premise」かつ「escalate」の両方が要る。**載せた周には聞かない**が
# ここでも効く——held のうちは出さない。これはこの設計の要で、どちらの条件も腕が無かった。
expect_output 1 "保留の問いに帰属する阻害要因 1 件は聞くのを待て——帰属しない 1 件を先に直せ" \
    "前提不成立でも、問いが held のうちは短絡しない（載せた周には聞かない）" \
    "$PY_BIN" "$RECORD" "$WORK/q-premise-not-escalate"
expect_output 1 "残る阻害要因は保留の問いに帰属するものだけ（1 件）" \
    "premise 以外の escalate では前提不成立を出さない" \
    "$PY_BIN" "$RECORD" "$WORK/q-escalate-not-premise"
expect_output 2 "2 ラウンド連続の残存＝stuck）のに問いの台帳に無い" "同じ [block] が 3 周続けば台帳への記載を要求する" \
    "$PY_BIN" "$RECORD" "$WORK/q-stuck-unlisted"
expect_output 1 "残る阻害要因は保留の問いに帰属するものだけ（1 件）" "残る阻害が保留の問いだけなら「聞く時」を出す" \
    "$PY_BIN" "$RECORD" "$WORK/q-stuck-listed"
expect_output 1 "（今ラウンドに立った問い——再審は次の周）" \
    "同じ形でも、問いが立った周には帰属せず印だけが付く（立った周には聞かない）" \
    "$PY_BIN" "$RECORD" "$WORK/q-fresh"
expect_output 1 "帰属しない 1 件を先に直せ" \
    "ループが決めた問い（resolved）の阻害要因は仕事であって、聞く時ではない" \
    "$PY_BIN" "$RECORD" "$WORK/q-resolved-is-work"
expect_output 1 "（保留の問いに帰属——答えを待っている）" "帰属する阻害要因の行に印が付く" \
    "$PY_BIN" "$RECORD" "$WORK/q-stuck-listed"
expect_output 1 "帰属しない 1 件を先に直せ" "帰属しない阻害が残るうちは聞かない" \
    "$PY_BIN" "$RECORD" "$WORK/q-mixed"
# do-now の見出しを縛る腕が 1 本も無く、[block] の見出しに潰しても全件緑だった。
expect_output 1 "[suggest] do-now 未対応" "do-now の行は [block] と別の見出しで出る" \
    "$PY_BIN" "$RECORD" "$WORK/tmpl-1"
expect_output 1 "残る阻害要因は保留の問いに帰属するものだけ（2 件）" "depends に挙げたユニットの阻害も問いに帰属する" \
    "$PY_BIN" "$RECORD" "$WORK/q-depends"
expect_output 1 "前提不成立が確定（escalate）" "premise の escalate は他の阻害の帰属を問わず「聞く時」" \
    "$PY_BIN" "$RECORD" "$WORK/q-premise-escalate"
expect_output 2 "2 ラウンド連続の残存＝stuck）のに問いの台帳に無い: R2" \
    "unit の key が R の名前と同じでも、別の域の問いはそのユニットを指したことにならない" \
    "$PY_BIN" "$RECORD" "$WORK/domain-separation"
# 台帳を監査する経路は R1 しか無いので、問いが新しく載った周に R1 を持ち越すと監査が走らない。
expect_output 2 "台帳の未決の問いが前ラウンドから変わったのに R1 が carried_over" \
    "問いが載った周に R1 を持ち越した記録は不正" "$PY_BIN" "$RECORD" "$WORK/q-new-r1-carried"
# **key の新規性だけを見ていたとき素通りした 2 形。** どちらも台帳の中身は動いている。
expect_output 2 "台帳の未決の問いが前ラウンドから変わったのに R1 が carried_over" \
    "同じ key のまま中身を総取り替えした周も、R1 を持ち越せない" \
    "$PY_BIN" "$RECORD" "$WORK/q-swap-r1-carried"
expect_output 2 "台帳の未決の問いが前ラウンドから変わったのに R1 が carried_over" \
    "ループが決めた問いが未決に戻った周も、R1 を持ち越せない" \
    "$PY_BIN" "$RECORD" "$WORK/q-reopen-r1-carried"
expect_output 1 "[block] 未解消" "同じ形でも R1 を走らせていれば通る（対照）" \
    "$PY_BIN" "$RECORD" "$WORK/q-new-r1-ran"
expect_output 1 "[block] 未解消" "持ち越した問いだけの周は R1 も持ち越してよい（縛るのは新しく載った問い）" \
    "$PY_BIN" "$RECORD" "$WORK/q-carried-r1-carried"
expect_output 2 "は記録の名前でない" "大小が違うだけのファイルを黙って捨てない" \
    "$PY_BIN" "$RECORD" "$WORK/name-case"
# 受理は厳しく（ASCII の桁だけ）、見逃しの検知は広く（Unicode の桁も拾う）。入口の片方を
# 狭めただけだと、欠陥はもう片方の入口へ移動して残る。
expect_output 2 "は記録の名前でない" "桁の異体字のファイル名も黙って受理せず、黙って捨てもしない" \
    "$PY_BIN" "$RECORD" "$WORK/name-unidigit"
# **最新ラウンドが消える形。** 欠番検査は 1..max しか見ないので、末尾の欠落は赤くならない。
expect_output 2 "は記録の名前でない" "正規表現の軸に載らない綴りでも、最新ラウンドを黙って捨てない" \
    "$PY_BIN" "$RECORD" "$WORK/name-tail"
expect_output 1 "前ラウンドの記録が無い" "退避先のディレクトリと OS の成果物では鳴らさない（対照）" \
    "$PY_BIN" "$RECORD" "$WORK/name-ok"
# 「聞く時」の 3 分岐はどれも通らない周。台帳の数え直しが exit 1 側にも要る。
expect_output 1 "台帳に未決の問いが 1 件（うち人へ 0 件）" \
    "出どころで手を止めない問いだけが残る周も、台帳が黙って終わらない" \
    "$PY_BIN" "$RECORD" "$WORK/q-thrash-silent"
expect_output 2 "2 ラウンド連続の残存＝stuck）のに問いの台帳に無い" \
    "連鎖のキーを depends に並べても stuck の振り分け要求は満たされない（見るのは origin）" \
    "$PY_BIN" "$RECORD" "$WORK/q-stuck-via-depends"
expect_output 2 "round 4: 同じ [block] が 3 ラウンドの記録に続けて在る" \
    "3 周の窓は滑る（中間の周で振り分けても、最後の周で切れれば落ちる）" \
    "$PY_BIN" "$RECORD" "$WORK/q-stuck-window-slides"
expect_output 1 "（残存——過去のラウンドにも在った）" \
    "2 周の残存では、まだ台帳への記載を要求しない（対照）" "$PY_BIN" "$RECORD" "$WORK/stuck-two-rounds"
# 未決だけを縛る絞りを、緩める向きで 2 本。resolved はループが決めた跡なので、機械は縛らない。
expect_output 1 "[block] 未解消" "ループが決めた問いの出どころは、記録から消えていてよい" \
    "$PY_BIN" "$RECORD" "$WORK/q-resolved-origin-gone"
expect_output 1 "[block] 未解消" "ループが決めた split は、開いた [block] を指していてよい" \
    "$PY_BIN" "$RECORD" "$WORK/q-resolved-split-open"
expect_output 2 "round 2: questions[0] の origin" "出どころの実在検査は中間のラウンドにも掛かる" \
    "$PY_BIN" "$RECORD" "$WORK/q-origin-missing-mid"

# 前のレビューの記録が同じディレクトリに残っている形。手順書は消すなと言っているので、
# 止まるだけでなく退避先を案内できていることまで縛る。
expect_output 2 "混ざっていないか" "別レビューの記録が混ざったら、退避の案内を出して止まる" \
    "$PY_BIN" "$RECORD" "$WORK/mixed-base"
# 消えた [block] の報告。defer 側にだけ在って block 側に無いと、未解消の [block] を
# 記録から落とすだけで阻害要因が 0 になり、収束の分岐に乗る。
expect_output 1 "過去のラウンドの [block] で今ラウンドの記録に無いキー" \
    "前ラウンドの [block] が記録から消えたら報告する（defer 側との非対称を消す）" \
    "$PY_BIN" "$RECORD" "$WORK/block-dropped"
expect_output 2 "前ラウンドが unverifiable なので持ち越せない" \
    "人に諮る verdict を持ち越すと記録の不正になる（阻害要因から消えるため）" \
    "$PY_BIN" "$RECORD" "$WORK/carry-from-human"
# 正直な書き方＝同じ値をもう一度書く。これなら毎ラウンド阻害要因として数えられる。
expect_output 1 "R1 が unverifiable（収束を宣言せずユーザーに諮れ）" \
    "人に諮る verdict は、同じ値を書き直せば毎ラウンド数えられる" \
    "$PY_BIN" "$RECORD" "$WORK/human-repeat"
expect_output 2 "1 から始まる番号でない" "round-0.json を黙って捨てない" \
    "$PY_BIN" "$RECORD" "$WORK/round-zero"
expect_output 2 "同じ番号" "ゼロ詰めの別名が同じ番号に潰れるのを落とす" \
    "$PY_BIN" "$RECORD" "$WORK/round-dup"
expect_output 1 "収束を妨げるもの" "count: 0 を「値が無い」と言わない" \
    "$PY_BIN" "$RECORD" "$WORK/count-zero"
expect_output 2 "が空（何を見たかを書け）" "空文字は欠落と分けて診断する" \
    "$PY_BIN" "$RECORD" "$WORK/checked-empty"
expect_output 2 "from_round が 1 以上でない" \
    "存在しないラウンド 0 からの流用を落とす（外すと素材を一度も見ずに収束できる）" \
    "$PY_BIN" "$RECORD" "$WORK/from-round-zero"
expect_output 1 "（残存——過去のラウンドにも在った）" \
    "連鎖が 2 周ぶんなら、3 周の窓では台帳への記載を要求しない（窓の幅を測る）" \
    "$PY_BIN" "$RECORD" "$WORK/stuck-window-width"
expect_output 2 "UTF-8 として読めない" "UTF-8 でない記録は「開けない」「JSON でない」と別の診断で落ちる" \
    "$PY_BIN" "$RECORD" "$WORK/badenc"
expect_output 2 "が空（何を見たかを書け）" "縮退値（false / [] / {}）で明示返答の欄を埋められない" \
    "$PY_BIN" "$RECORD" "$WORK/checked-false"
# 免除を**型**（整数なら通す）で持っていたとき、文を要求する欄に 0 を書いて全部素通りした。
# 免除の単位は欄の名前（NUMERIC_FIELDS）で、count / from_round だけが数で埋まる。
expect_output 2 "が空（何を見たかを書け）" "文を要求する欄に数を書いても「埋まっている」にならない" \
    "$PY_BIN" "$RECORD" "$WORK/checked-number"
expect_output 2 "reopen_evidence が無い" "1 ラウンド記録から落としても、台帳は全ラウンドの和なので再審を止める" \
    "$PY_BIN" "$RECORD" "$WORK/ledger-gap"
expect_output 0 "履歴（round 1〜3" "ディレクトリを渡すと全ラウンドの履歴を出す" "$PY_BIN" "$RECORD" "$WORK/hist"
expect_output 0 "問いの台帳（人に聞く候補。載せた周には聞かない" "台帳の問いは阻害要因にせず、人に聞く候補として出す" "$PY_BIN" "$RECORD" "$WORK/hist"
expect_output 0 "r1:held(awaiting) → r2:resolved(awaiting) → r3:—" "問いの推移を履歴に出す（決めた問いは次の周から消えてよい）" "$PY_BIN" "$RECORD" "$WORK/hist"
expect_output 0 "問いの台帳の件数（保留・人へ・ループが決めた）: 1・0・0 → 1・0・1 → 1・1・0" "台帳の件数の推移を出す" "$PY_BIN" "$RECORD" "$WORK/hist"
expect_output 0 "台帳に未決の問いが 2 件（うち人へ 1 件）" \
    "阻害要因が 0 でも、台帳に未決が残っていれば判定行がそう言う" "$PY_BIN" "$RECORD" "$WORK/hist"
expect_output 0 "要対応（[block]＋do-now）の件数: 3 → 0 → 0" "要対応の件数の推移を出す" "$PY_BIN" "$RECORD" "$WORK/hist"
expect_output 2 "round-2.json が無い" "連番に穴があれば履歴を出さずに落ちる" "$PY_BIN" "$RECORD" "$WORK/hist-gap"
expect_output 0 "r1:block → r2:— → r3:nit（消えて 1 回戻った）" "直したはずのキーが戻れば履歴に印を付ける" \
    "$PY_BIN" "$RECORD" "$WORK/hist-return"
# 2 ラウンド目に初出しただけのキーは「戻った」ではない。**行末の改行まで期待に含める**ことで
# 「注記が付いていない」を肯定で言う——「出ないこと」を grep で見る形は、対象が消えても
# 異常終了しても緑になる（この節でもう 1 本が実際にそうなっていた）。
# **引用は ANSI-C（$'…'）でなければならない。** `"$(printf '…\n')"` はコマンド置換が末尾の
# 改行を落とすので期待からも改行が消え、注記が付いた出力にも一致する——実測: この形にして
# いたとき、初出を「戻った」と数える変異を当てても全件緑のままだった（肯定形に直したつもりが、
# 同じ恒真をもう 1 本作っていた）。
expect_output 0 $'r1:— → r2:suggest/defer → r3:suggest/defer\n' \
    "初出のキーを「戻った」と数えない（注記が付かない）" "$PY_BIN" "$RECORD" "$WORK/hist"

# 記録に到達できない場合も 2（契約は冒頭 `review-record.py` の docstring が正本）。
expect_output 2 "JSON として読めない" "壊れた JSON は 1 と区別して落ちる" \
    "$PY_BIN" "$RECORD" "$WORK/truncated"
expect_output 2 "ディレクトリでない" "記録のディレクトリでないものを渡したら 1 と区別して落ちる" \
    "$PY_BIN" "$RECORD" "$WORK/does-not-exist"
expect_output 2 "開けない" "読めない記録は 1 と区別して落ちる" \
    "$PY_BIN" "$RECORD" "$WORK/unreadable"
expect_exit 2 "引数なしは 1 と区別して落ちる" "$PY_BIN" "$RECORD"
expect_exit 2 "引数が多すぎる場合も 1 と区別して落ちる" "$PY_BIN" "$RECORD" "$WORK/tmpl-12" "$R1"
# **ここは終了コードだけを見る。** どの経路で 2 になるかは環境で変わる——再帰上限に達すれば
# 境界が受け、達しなければ最上位の型検査が受ける（macOS は 10 万段でも読み切る）。例外名を
# 検査すると、緑が環境の性質を映すだけになる。境界そのものは上の unhashable-status と
# q-unhashable-key が例外名（TypeError）まで検査している。
expect_exit 2 "深いネストの JSON も 1 と区別して落ちる（経路は環境で変わる）" \
    "$PY_BIN" "$RECORD" "$WORK/deep"

echo "research-record.py"
RR="$ROOT/scripts/research-record.py"
RR_EX="$ROOT/templates/research-record.example.json"

expect_output 0 "これは品質・飽和の宣言ではない" "阻害なしを品質・飽和と名乗らない" \
    "$PY_BIN" "$RR" "$RR_EX"

# 記録の一部を壊した JSON をまとめて 1 プロセスで書き出す（生成のみ束ねる。理由は上の
# write_broken_records と同じ——検査はケースごとに分けたままにする）。
"$PY_BIN" - "$ROOT" "$WORK" <<'PY' || { echo "  FAIL 壊した研究記録を作れない"; fail=1; }
import json, sys, pathlib

# 手書きの deep copy を 1 本に寄せる（理由は上の `write_broken_records` の clone と同じ）。
def clone(x):
    return json.loads(json.dumps(x))
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
    rec = clone((base))
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

# 手書きの deep copy を 1 本に寄せる（理由は上の `write_broken_records` の clone と同じ）。
def clone(x):
    return json.loads(json.dumps(x))
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
    rec = clone((base))
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

# 手書きの deep copy を 1 本に寄せる（理由は上の `write_broken_records` の clone と同じ）。
def clone(x):
    return json.loads(json.dumps(x))
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
    rec = clone((r1))
    mutate(rec)
    (work / f"{name}.json").write_text(json.dumps(rec, ensure_ascii=False), encoding="utf-8")

# 周をまたぐ検査は 2 周目の側を壊す。
same = clone((r1)); same["round"] = 2
(work / "fr-same-stuck.json").write_text(json.dumps(same, ensure_ascii=False), encoding="utf-8")

new = clone((r2))
new["materials"]["stopped"]["items"].append(
    {"key": "rollback/前提が逆順", "verbatim": "戻す手順が、出す手順を読んだ前提で書かれていた",
     "in_scope": True}
)
(work / "fr-new-stuck.json").write_text(json.dumps(new, ensure_ascii=False), encoding="utf-8")

# 削除も移動も無いまま行数だけ増えた周。**阻害要因ではないが報せる。**
grew = clone((r2))
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

expect_output 0 "ok" "閉鎖の実証とゲートの赤の確認が、腕ごと・箇所ごとを要求している" "$PY_BIN" -c "
import sys, pathlib
t = pathlib.Path(sys.argv[1]).read_text(encoding='utf-8')
assert '不変条件を共有する箇所を先に全部挙げ' in t, '閉鎖の実証が「1 つ」で止まってよい文面に戻っている'
assert '条件の腕ごとに 1 つずつ' in t, 'ゲートの赤の確認が腕ごとを要求していない'
assert '退行を 1 つ注入して' not in t, '古い「退行を 1 つ」の文面が残っている'
print('ok')" "$ROOT/commands/review-loop.md"
# 実走で出た 3 つの穴（別セッションと私が独立に踏んだ）。道具を渡して隔離を指示に落とす・品質の
# 道具が木を動かす・仕掛けが壊れて全腕が同じ色に出る、のどれも「空振りが合格に見える」形。
expect_output 0 "ok" "実走で出た 3 つの穴（貼れない差分・品質の道具・対照の緑）が手順書に書いてある" "$PY_BIN" -c "
import sys, pathlib
t = pathlib.Path(sys.argv[1]).read_text(encoding='utf-8')
assert 'この役に道具を渡して解決するな——貼る側を割れ' in t, '貼り切れない差分の扱いが無い（道具を渡す形に倒れる）'
assert 'P1 では指摘だけ返す形で呼べ' in t, '品質の道具が P1 で木を動かす形のまま'
assert '壊していない写しでも 1 本走らせて緑を確認しろ' in t, '対照の緑が無い（仕掛けの空振りを合格と読める）'
print('ok')" "$ROOT/commands/review-loop.md"
# 「見つけた周に直したものをどう書くか」が無いと、実行者は「直したのに阻害が残る」を不具合と読んで
# ラベルを軽い側へ倒す＝writer が採点する形になる（実測: 別の実行者が、どこにも書かれていない慣習として
# その倒し方を踏襲していた）。設計どおりだと明記した一文が落ちないよう縛る。
expect_output 0 "ok" "見つけた周に直しても記録は判定どおり書く、と手順書が言っている" "$PY_BIN" -c "
import sys, pathlib
t = pathlib.Path(sys.argv[1]).read_text(encoding='utf-8')
assert '見つけた周の記録は、その周に直していても判定どおり書け' in t, '直した周の記録の書き方が無い'
assert '直した周が阻害要因ありで終わるのは設計どおり' in t, '阻害が残るのが設計どおりだと書かれていない'
print('ok')" "$ROOT/commands/review-loop.md"
# 入口の説明（README）と手順書がずれると、読者はもう無い検証を信じたまま使う。実測: 手順書を
# 差し替えたのに README だけ旧方式の現在形（「剥がした写しを精読させ、削る」）で残っていた——
# 柵が手順書にしか掛かっておらず、README は素通りだった。
expect_output 0 "ok" "README の入口の説明が、今の前段（名指しさせる形）と揃っている" "$PY_BIN" -c "
import sys, pathlib
t = pathlib.Path(sys.argv[1]).read_text(encoding='utf-8')
assert '剥がした写しを精読' not in t, 'README が落とした仕掛けを現在形で説明している'
assert '同じ内容がどこにあるかを名指しさせ' in t, 'README が今の前段を説明していない'
print('ok')" "$ROOT/README.md"
# 前段が取れないと R1 の verdict ごと not_run に倒す形は、not_run が阻害要因なので「安全側に
# 倒したつもりが収束不能」になる（実測）。前段の仕掛けを差し替えたときにこの規定も一緒に落ちた——
# 仕掛けが変わっても壊れ方は同じなので、一般の形で縛り直す。
expect_output 0 "ok" "前段が取れなくても R1 の verdict までは倒さない規定が在る" "$PY_BIN" -c "
import sys, pathlib
t = pathlib.Path(sys.argv[1]).read_text(encoding='utf-8')
assert 'verdict まで \`not_run\` に倒すな' in t, '前段の失敗で verdict ごと倒す形に戻っている'
assert '収束できなかった' in t, '倒すと収束不能になる実測が落ちている'
print('ok')" "$ROOT/commands/review-loop.md"
# 「差分だけを見るな」は依頼者の逐語（「差分にしか触れないのはダメ」）に対する規定で、0.22.0 まで
# R1 前段に在った。自作の仕掛けを消したときに一文ごと落ちた——**視野を狭めるなと書いた同じ差分で、
# 視野を狭める削除をしていた**。落ちても何も赤くならなかったので、ここで縛る。
expect_output 0 "ok" "対象差分が視野の線でないこと（差分だけを貼るな）が手順書に在る" "$PY_BIN" -c "
import sys, pathlib
t = pathlib.Path(sys.argv[1]).read_text(encoding='utf-8')
assert '「どこまで見るか」の線ではない' in t, '対象差分を視野の線と読める状態に戻っている'
assert '差分だけを貼って済ませるな' in t, 'リポジトリを読める役に差分だけを渡す禁止が無い'
assert '理解に要る限り依存先・近傍・呼び元まで読ませろ' in t, '差分の外まで読ませる指示が無い'
print('ok')" "$ROOT/commands/review-loop.md"
# 集める側で範囲を切ると、切った外は判定役の目に一度も入らない。実測: 「import している依存に
# 限れ」と書いていたため、自分で依存に宣言していた役が集合の外に落ち、3 ラウンド続けて
# 「再発明は該当なし」が返った。柵を動かすのでなく、柵をやめて範囲の申告に替えたことを縛る。
expect_output 0 "ok" "探す役に見るなの線を引かず、見た範囲と見ていない範囲を返させる規律が在る" "$PY_BIN" -c "
import sys, pathlib
t = pathlib.Path(sys.argv[1]).read_text(encoding='utf-8')
assert '探す役に「ここは見るな」の線を writer が引くな' in t, '集める側で範囲を切らない規律が無い'
assert '見た範囲と、見ていない範囲を返させろ' in t, '範囲の申告を求めていない'
assert '限れ**——差分から機械的に導ける集合で' not in t, '古い「import している依存に限れ」が残っている'
print('ok')" "$ROOT/commands/review-loop.md"
# 人はラウンドの間ずっと別の作業をしていて、報告を読む時点で文脈を持っていない。内部の語彙で
# 書かれた問いは決められないし、急ぎと後回しを混ぜて並べるとどれも決まらない。この規定が
# 落ちると、聞く側は書けたつもりで出し、聞かれた側は初見で読めないまま放置になる。
expect_output 0 "ok" "人に聞くところを、初見で決められる形にする規定が手順書に在る" "$PY_BIN" -c "
import sys, pathlib
t = pathlib.Path(sys.argv[1]).read_text(encoding='utf-8')
assert 'ループを見ていない人が初見で読んで決められる形' in t, '初見で決められる形にする要求が無い'
assert '急ぐものと後でよいものを分け、件数を先に言え' in t, '急ぎと後回しを分ける要求が無い'
assert '内部の語彙を使わずに言えないなら、まだ問いになっていない' in t, '内部語彙の禁止が無い'
assert 'cold-reader' in t and '人に聞くところの本文だけ' in t, '出す前に文脈ゼロの読み手に当てる検査が無い'
print('ok')" "$ROOT/commands/review-loop.md"
# この規定が落ちると、writer が「もう聞くしかない」と決めてループを止める形に戻る
# （なぜ立った周に聞かないかの実測は、手順書の「停止条件」が正本）。
expect_output 0 "ok" "人に聞く候補を立った周に聞かず、台帳に載せて次の周の judge に再審させる規定が手順書に在る" "$PY_BIN" -c "
import sys, pathlib
t = pathlib.Path(sys.argv[1]).read_text(encoding='utf-8')
assert '問いの台帳の再審' in t, '保留した問いを次の周の judge が再審する段が無い'
assert '答え無しに進める仕事' in t, '人に聞く時を機械の帰属で決める規定が無い'
assert '決定を待て' not in t, '岐路で止めて決定を待つ古い文面が残っている'
assert 'ユーザーに判断を仰げ' not in t, '停止条件が「立った周に聞く」形のまま'
assert 'ループが自分で決めたこと' in t, 'ループが決めた問いを人が覆せる形で見せる規定が無い'
assert '台帳全体を並べて枝同士を見ろ' in t, '問い同士のシナジー（横断の突合）を見る段が無い'
assert 'ask_human' not in t, '0.27 までの unit.ask_human が手順書に残っている'
print('ok')" "$ROOT/commands/review-loop.md"
# **観点の正本（REVIEW.md）も対象に入れる。** 0.28.0 ではここだけ柵の外で、手順書が split の正本として
# 名指ししている段が 0.27 の機構（人に諮る印・ループは止めず最終報告で聞く）のまま残っていた——
# 正本どおりに書くと記録が不正になる形が、唯一見られていないファイルに残っていた。
expect_output 0 "ok" "README・customize・観点の正本が、問いの台帳（立った周に聞かない）を説明している" "$PY_BIN" -c "
import sys, pathlib
# 対象が 0 件なら本体が一度も回らず ok を出す形（隣の柵は sys.argv[1] を直接引くので
# 引数欠落で落ちる）。同じ差分の中で防御の向きを揃える。
assert sys.argv[1:], '検査の対象が渡されていない'
for f in sys.argv[1:]:
    t = pathlib.Path(f).read_text(encoding='utf-8')
    assert '問いの台帳' in t, f + ' が問いの台帳を説明していない'
    assert 'ask_human' not in t, f + ' に 0.27 までの ask_human が残っている'
print('ok')" "$ROOT/README.md" "$ROOT/docs/customize.md" "$ROOT/REVIEW.md"
# R1 の前段は、既に依存に入っている comment-analyzer に寄せた。呼び出し時に足す 3 つが
# 落ちると、削除の提案が意見のままになり（在り処を名指ししない）、迷ったときに残す側へ倒れる
# （残す判断に義務が無い）。自作の剥がす仕掛けに戻っていないことも同時に縛る。
expect_output 0 "ok" "R1 の前段が comment-analyzer に寄せてあり、足すべき 3 つが落ちていない" "$PY_BIN" -c "
import sys, pathlib
t = pathlib.Path(sys.argv[1]).read_text(encoding='utf-8')
assert 'comment-analyzer' in t, 'R1 の前段が既存の役に寄せられていない'
assert '同じ内容がどこにあるかを名指しさせる' in t, '削除候補に在り処を名指しさせる要求が無い'
assert '運んでいる事実を一文で言わせる' in t, '残す判断の側に義務が無い（残す側に倒れる）'
assert 'strip-comments' not in t, '自作の剥がす仕掛けに戻っている'
print('ok')" "$ROOT/commands/review-loop.md"
# 「過去の [block] が記録から消えた」は機械が数えられない（和なら永久に残り、隣接なら 1
# ラウンドで会計から落ちる。どちらも実測）。数えない代わりに judge に振り分けさせる義務が
# 手順書から落ちると、未閉鎖の [block] が無言で記録から抜ける（実測 3 件）。
expect_output 0 "ok" "過去ラウンドの [block] の一覧を、台帳と同じルーターに掛ける義務が手順書に在る" "$PY_BIN" -c "
import sys, pathlib
t = pathlib.Path(sys.argv[1]).read_text(encoding='utf-8')
assert '同じルーターを、過去ラウンドの \`[block]\` キーにも課せ' in t, '過去の [block] の振り分けが judge の義務になっていない'
assert '機械はこの一覧を数えない' in t, '数えない理由が書かれていない（次に「積め」と直される）'
print('ok')" "$ROOT/commands/review-loop.md"
# ゲートの赤の確認を共有の木でやると、同時に読んでいる役が壊れた瞬間を踏む。順序の約束は
# 守ったかを確かめられないので、写しの上で壊す形に固定した。戻ると赤くする。
expect_output 0 "ok" "ゲートの赤の確認が、本物でなく写しの上で壊すことを要求している" "$PY_BIN" -c "
import sys, pathlib
t = pathlib.Path(sys.argv[1]).read_text(encoding='utf-8')
assert '腕ごとにリポジトリの写しを' in t and 'の下に作り、写しの上で壊して' in t, '写しの上で壊す指示が無い'
assert 'mktemp -d' in t, '写しの置き場所が指定されていない（リポジトリ内に作ると突合が汚れる）'
assert '並行起動した grader が全部返ったあとに行え' not in t, '順序の約束だけで塞ぐ古い文面が残っている'
print('ok')" "$ROOT/commands/review-loop.md"

# Python の docstring 判定を、綴りでなく**判定結果**で突く。以前は剥がす側（自作の
# strip-comments.py）と条件が同じかを正規表現で見ていたが、剥がす側ごと落としたので、
# 数える側の挙動そのものを固定する。
DSREPO="$WORK/docstring-cross"
mkdir -p "$DSREPO"
(
    cd "$DSREPO" || exit 1
    git init -q . && git config user.email t@t && git config user.name t
    : > .keep && git add -A && git commit -qm base
    printf '"""mod doc"""\ndef f():\n    """doc\n    two"""\n    s = """not doc"""\n    return s\n# tail comment\n' > d.py
    git add -A
) >/dev/null 2>&1
DSBASE=$(git -C "$DSREPO" rev-parse HEAD)
# 数える側: 追加 7 行のうち注釈は 4 行（module docstring 1・関数 docstring 2・# 行 1）。
# 代入の右辺の文字列は注釈ではない。
expect_output 0 "追加行 7 / 注釈 4 (57%)" "数える側の docstring 判定（代入の文字列は注釈にしない）" \
    bash -c "cd '$DSREPO' && bash '$ROOT/scripts/comment-ratio.sh' '$DSBASE'"

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

# テンプレートは写される前提で読まれる。手順書 P0-5 が「恒真になる」と禁じた `gh repo view` の
# 突き合わせが実例に載っていると、手順書側の禁止が無効になる（実際に載っていた）。
for t in sorted((root/"templates").glob("round-*.example.json")):
    assert "gh repo view" not in t.read_text(encoding="utf-8"), \
        f"{t.name} が手順書の禁じ手（gh repo view で owner/repo を確認）を実例として見せている"
PY

# **番人を置く。** 隣の定数実在検査は出力（末尾の合図の語）まで見るのに、ここだけ終了コード
# しか見ていなかった。**引用を拾う正規表現を絶対に一致しない形に変えても全件緑**になる（実測）
# ——照合が 0 件なら missing は空で assert が通るため。拾った件数まで出させて縛る。
expect_output 0 "DOC_HEADINGS_OK" "手順書が名指しする REVIEW.md のセクションが実在する" \
    "$PY_BIN" - "$ROOT" <<'PYHEAD'
import re, sys, pathlib
root = pathlib.Path(sys.argv[1])
review = (root/"REVIEW.md").read_text(encoding="utf-8")
known = set(re.findall(r"^##+ (.+)$", review, re.M)) | set(re.findall(r"\*\*(.+?)\*\*", review))
# **「実在する」の定義が崩れていないことも見る。** 見出しと太字の集合を本文 1 個に潰すと、
# 照合が本文への部分一致に戻って節を丸ごと削っても緑になる（今周それを 1 度やった）。
# 入口を数えて 1 つずつ壊したとき、この入口だけ腕が無かった。下限は走らせた実測値。
assert len(known) >= 72, f"見出し・太字を {len(known)} 個しか拾えていない（72 個以上を期待）"
missing, found = set(), 0
# **対象集合が狭いと、柵は緑のまま文書だけが消えた名前を指す。** 機械のコメントから
# `REVIEW.md` の見出しを引く箇所が増えたのに対象が commands / agents だけで、実在しない
# 見出しを引いた行が 1 周素通りした。backtick も任意にする。
for f in [*(root/"commands").glob("*.md"), *(root/"agents").glob("*.md"),
          *(root/"scripts").glob("*.py"), root/"README.md", root/"docs"/"customize.md"]:
    body = f.read_text(encoding="utf-8")
    # 内側の『』で途中で切れないよう、同じ種類の鉤で閉じるまでを 1 つの名前として取る。
    # **助詞を「の」に限るな**——`REVIEW.md`**が**「…」という引用が 1 件在って、**1 度も
    # 走査されていなかった**（しかもその引用は正本と逐語一致しない＝走査されていれば赤く
    # なる側だった）。覆いを軸ごとに足していくと、足していない軸から必ず漏れる。
    for name in re.findall(r"`?REVIEW\.md`?\s*[のがにはをも]?\s*「((?:[^「」]|『[^『』]*』)+)」", body):
        found += 1
        # 入れ子のときは内側の鉤が『』に置き換わるので、比較の前に揃える。
        name = name.replace("『", "「").replace("』", "」")
        # **本文への部分一致を合格に足すな。** 一度足したとき、`REVIEW.md` の節を見出しごと
        # 8 行まるごと削っても全件緑になった（実測）——同じ語が散文に 1 度でも残っていれば
        # 通るため。本文の一文を引いていた 2 箇所（README と review-record.py）は、節名・
        # 太字の見出しで指す形に書き換えた。**柵の名乗りに覆いを揃える。**
        if not any(name in k for k in known):
            missing.add(f"{f.name}: 「{name}」")
assert not missing, "REVIEW.md に無いセクションを参照している: " + " / ".join(sorted(missing))
# **拾った件数の下限。** 正規表現が壊れて 0 件になっても missing は空で通る（自分の空振りで
# 合格になる形）。下限は走らせた実測値だけを書く。
assert found >= 26, f"引用を {found} 件しか拾えていない（26 件以上を期待。走らせた実測値だけを書け）"
print(f"DOC_HEADINGS_OK {found}")
PYHEAD

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
# **検査を足したらこの数も上げろ。**下限が実数から離れると、この柵自体が空振りする——
# 実測（commit 935b205。下限が 225 のまま実件数が 448 件まで増えていた時点）: review-record と
# 実行件数の一致検査（下の `-ne`）が見るのはこの数。**走らせた実測値だけを書け**——数える前に
# 書いた数はどのコミットでも再現しなかった（前は「457 件」と書いてあった）。残る注記の仕事は 1 つ
# だけで、**検査面を捨てて数を下げるときは、下げた理由をここに残す**こと。数を下げる操作自体は
# 機械が止められない（削った本人が数も一緒に下げれば一致するので通る）。増やす側と、下げ忘れ・
# 上げ忘れは `-ne` が止めるので、ここには書かない。下げた実例は commit 4bb8d62（自作の剥がす
# 仕掛けを落として検査面が対象ごと消えた周）。
EXPECTED_CHECKS=528
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
# 門番を module として読む前置きと、deny 理由を取り出す前置き(-c の頭に付ける)
CR_LOAD='import importlib.util,sys
spec=importlib.util.spec_from_file_location("g", sys.argv[1]); g=importlib.util.module_from_spec(spec); spec.loader.exec_module(g)'
CR_REASON='import json,sys,subprocess
out = subprocess.run(sys.argv[1:], capture_output=True, encoding="utf-8").stdout
reason = json.loads(out)["hookSpecificOutput"]["permissionDecisionReason"]'

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
# 逃げ道は書き手の前置であって、本文に文字列が入っていることではない。塞ぐ側と守る側を
# 両方張る——守る側だけなら部分文字列一致のままでも緑、塞ぐ側だけなら逃げ道を殺しても緑になる。
# 塞ぐ側で「詰まり」を期待するのは、deny になった事実でなく読み役が実際に本文を読んだことまで
# 見るため($CR_STUB_FAIL だと「coldreader の起動に失敗」でも緑になり、検査が走った証明にならない)
CR_BODY_MENTIONS="gh issue comment 1 --body-file - <<'EOF'
$CR_BODY
検査を飛ばすときは COLDREAD_SKIP=1 を付けて再実行します。
$CR_PAD
EOF"
expect_output 0 "詰まり" "本文が COLDREAD_SKIP=1 に言及するだけでは外れない" \
    "$CR_CASE" "$CR_CFG" "$CR_STUB_BLOCK" "$CR_BODY_MENTIONS"
expect_output 0 "詰まり" "旗の値としての COLDREAD_SKIP=1 でも外れない" \
    "$CR_CASE" "$CR_CFG" "$CR_STUB_BLOCK" "gh issue comment 1 --body 'COLDREAD_SKIP=1 $CR_BODY $CR_PAD'"
expect_output 0 "ALLOW_EMPTY" "cd の次の行に前置しても通る" \
    "$CR_CASE" "$CR_CFG" "$CR_STUB_FAIL" "cd /tmp
COLDREAD_SKIP=1 $CR_POST"
expect_output 0 "ALLOW_EMPTY" "&& の先に前置しても通る" \
    "$CR_CASE" "$CR_CFG" "$CR_STUB_FAIL" "cd /tmp && COLDREAD_SKIP=1 $CR_POST"
expect_output 0 "ALLOW_EMPTY" "解析できないコマンドでも前置なら通る(逃げ道の主用途)" \
    "$CR_CASE" "$CR_CFG" "$CR_STUB_FAIL" "COLDREAD_SKIP=1 gh issue comment 1 --body '引用が閉じない $CR_BODY $CR_PAD"
expect_output 0 "取り出せない" "本文を取り出せない形は deny" \
    "$CR_CASE" "$CR_CFG" "$CR_STUB_FAIL" "gh issue comment 1 --body-file /tmp/real.md # $CR_PAD"
expect_output 0 "通じやすさのみ" "読み役が CLEAN なら通り、保証範囲の注が載る" \
    "$CR_CASE" "$CR_CFG" "$CR_STUB_CLEAN" "$CR_POST"
expect_output 0 "詰まり" "読み役の詰まりで deny になり指摘が載る" \
    "$CR_CASE" "$CR_CFG" "$CR_STUB_BLOCK" "$CR_POST"
expect_output 0 "残った疑問" "疑問のみなら通り、申し送りが載る" \
    "$CR_CASE" "$CR_CFG" "$CR_STUB_QUEST" "$CR_POST"
expect_output 0 "coldreader(文脈ゼロの読み手)の起動に失敗" "読み役の故障は deny+案内(投稿不能にはしない)" \
    "$CR_CASE" "$CR_CFG" "$CR_STUB_FAIL" "$CR_POST"
# 行継続(`\` + 改行)。tokenize は改行を区切りの演算子として残すので、正規化しないと 1 つの
# gh 呼び出しが複数の単純コマンドに割れる。旗だけが載った断片は gh 呼び出しと認識されず、
# 本文旗が引数列から消えて「投稿でない」として無検査・無記録で素通しになっていた。
# 2026-09-03 の issue 3 本は逃げ道で通った(記録は残る)が、同じ 3 本から逃げ道を外すと
# この経路で記録の無い素通しになることを実測した——同じコマンドに独立した穴が 2 つ在った。
# 4 形を張るのは折り返す位置で壊れ方が変わるため。期待を「詰まり」にするのは、
# deny になった事実でなく読み役が実際に本文を読んだことまで見るため。
expect_output 0 "詰まり" "行継続: 旗の前で折り返しても網に入る" \
    "$CR_CASE" "$CR_CFG" "$CR_STUB_BLOCK" "gh issue comment 1 \\
  --body '$CR_BODY $CR_PAD'"
expect_output 0 "詰まり" "行継続: サブコマンドの後で折り返しても網に入る" \
    "$CR_CASE" "$CR_CFG" "$CR_STUB_BLOCK" "gh issue \\
  comment 1 --body '$CR_BODY $CR_PAD'"
expect_output 0 "詰まり" "行継続: gh api + ヒアドキュメント(事故の形)も網に入る" \
    "$CR_CASE" "$CR_CFG" "$CR_STUB_BLOCK" "gh api repos/o/r/issues -X POST \\
  -f title='t' \\
  -F body=@- <<'EOF'
$CR_BODY
$CR_PAD
EOF"
CR_CONT_CRLF=$(printf "gh issue comment 1 \\\\\r\n  --body '%s %s'" "$CR_BODY" "$CR_PAD")
expect_output 0 "詰まり" "行継続: CRLF で届いても網に入る" \
    "$CR_CASE" "$CR_CFG" "$CR_STUB_BLOCK" "$CR_CONT_CRLF"
# 単一引用の中の `\`+改行 は行継続ではない(シェルが畳まない)。畳んでしまうと本文が
# 書かれたとおりに読み役へ渡らないので、こちらは保つ側を張る。
# 期待を「詰まり」にすると畳んでも緑になる(どちらでも読み役は走る)ので、読み役の側で
# 本文を実際に見て、畳まれたかどうかで返す文言を変える
CR_STUB_FOLD='if grep -q "まえ\\\\$"; then printf "詰まり: 行継続が畳まれずに届いた\n"; else printf "詰まり: 行継続が畳まれてしまった\n"; fi'
expect_output 0 "畳まれずに届いた" "単一引用の中の改行は畳まず、本文が書かれたとおり読み役へ渡る" \
    "$CR_CASE" "$CR_CFG" "$CR_STUB_FOLD" "gh issue comment 1 --body 'まえ\\
うしろ $CR_BODY $CR_PAD'"

# 注釈(#)。shlex の既定は行末まで読み捨てるので、区切りにしている改行まで消えて
# 単純コマンドが融合し、先頭語が cd や echo になって gh が見えなくなる。
# 行継続を畳むようにしたぶん融合の射程が「物理行」から「論理行」へ広がるので、
# 塞ぐ側を張る(1 件目は今回の変更が入れた退行、2 件目は元から在った穴)
expect_output 0 "詰まり" "語中の # があっても行継続の先の本文旗を見失わない" \
    "$CR_CASE" "$CR_CFG" "$CR_STUB_BLOCK" "gh issue create -R o/r --title fix#123 \\
  --body '$CR_BODY $CR_PAD'"
expect_output 0 "詰まり" "注釈行の次の行の gh を見失わない" \
    "$CR_CASE" "$CR_CFG" "$CR_STUB_BLOCK" "cd /tmp  # 作業場所
gh issue comment 1 --body '$CR_BODY $CR_PAD'"

# 注釈と行継続は 1 パスで落とす。2 パスだと順序をどちらに置いても、bash が実行する gh を
# 片方で見失う(どちらも gh スタブを PATH に置いた bash で「実行される」ことを実測):
#   注釈が先   → 1 件目を落とす(行が連結されるので #y は語中の # であって注釈ではない)
#   行継続が先 → 2 件目を落とす(注釈は行末で切れるので、その \ は注釈の一部)
# 2 件同時に緑になるのは 1 パスのときだけなので、この 2 本で順序への逆戻りを縛る
expect_output 0 "詰まり" "行継続で連結した後の # は語中(注釈にせず、後ろの gh を残す)" \
    "$CR_CASE" "$CR_CFG" "$CR_STUB_BLOCK" "echo x\\
#y; gh issue comment 1 --body '$CR_BODY $CR_PAD'"
expect_output 0 "詰まり" "注釈の中の \\ は行継続にしない(次の行の gh を残す)" \
    "$CR_CASE" "$CR_CFG" "$CR_STUB_BLOCK" "echo a # メモ \\
gh issue comment 1 --body '$CR_BODY $CR_PAD'"

# シェルの予約語。( gh … ) は元から網に入るのに { gh …; } は抜ける、という
# 「書き方だけで片方が抜ける」状態だった
expect_output 0 "詰まり" "{ } で括った gh も網に入る" \
    "$CR_CASE" "$CR_CFG" "$CR_STUB_BLOCK" "{ gh issue comment 1 --body '$CR_BODY $CR_PAD'; }"
expect_output 0 "詰まり" "if の then に置いた gh も網に入る" \
    "$CR_CASE" "$CR_CFG" "$CR_STUB_BLOCK" "if true; then gh issue comment 1 --body '$CR_BODY $CR_PAD'; fi"
expect_output 0 "詰まり" "while の do に置いた gh も網に入る" \
    "$CR_CASE" "$CR_CFG" "$CR_STUB_BLOCK" "while true; do gh issue comment 1 --body '$CR_BODY $CR_PAD'; break; done"

# 網から落ちた投稿を数えられるようにする。sh -c は受容済みの限界(gates/README.md)だが、
# 落ちた事実が 0 行なのは「投稿でなかった」と区別が付かず、押し出しの量を測れない
expect_output 0 "ALLOW_EMPTY" "sh -c の中の gh は今も素通し(受容済みの限界)" \
    "$CR_CASE" "$CR_CFG" "$CR_STUB_FAIL" "sh -c 'gh issue comment 1 --body \"$CR_BODY $CR_PAD\"'"
expect_output 0 "--body" "網から落ちた投稿は旗の綴りだけ misses.log に残る" \
    cat "$CR_CFG/coldread-gate/misses.log"

# 補完(読み手が推測で埋めた箇所)。詰まり 0 件で通る自信のある誤読を書き手に返すための欄で、
# 投稿は止めない。事故で最悪だった誤読(「いま CI が壊れている」)がこの型
CR_STUB_FILL='cat >/dev/null; printf "補完: 障害は今起きていると読んだ\nCLEAN\n"'
CR_STUB_BLOCK_FILL='cat >/dev/null; printf "詰まり: F3 が何か本文で解決できない\n補完: 障害は今起きていると読んだ\n"'
CR_STUB_PROSE='cat >/dev/null; printf "詰まりは無い。本文は将来の話をしている。\nCLEAN\n"'
expect_output 0 "推測で埋めた箇所" "補完のみなら通り、埋めた中身が載る" \
    "$CR_CASE" "$CR_CFG" "$CR_STUB_FILL" "$CR_POST"
expect_output 0 "補完: 障害は今起きている" "補完は deny の指摘にも載る(直す機会があるのは deny の側)" \
    "$CR_CASE" "$CR_CFG" "$CR_STUB_BLOCK_FILL" "$CR_POST"
# 期待は allow にしか出ない語にする。「通じやすさのみ」(SCOPE_NOTE)は deny にも載るので
# 恒真になる——実際に恒真だったのを変異で検出して直した
expect_output 0 "検査を通過" "ラベルはコロンまで見る(「詰まりは無い」の地の文で deny にしない)" \
    "$CR_CASE" "$CR_CFG" "$CR_STUB_PROSE" "$CR_POST"
expect_output 0 "止めてはいないが" "deny の指摘は見出しで分ける(直す詰まりと、直さなくてよい補完)" \
    "$CR_CASE" "$CR_CFG" "$CR_STUB_BLOCK_FILL" "$CR_POST"
# 末尾の CLEAN で詰まりが上書きされないこと。読み役に自由文の欄(補完)を足したぶん、
# 「指摘を並べた後に CLEAN と書く」形が出やすくなっている
CR_STUB_BLOCK_CLEAN='cat >/dev/null; printf "詰まり: F3 が何か本文で解決できない\nCLEAN\n"'
expect_output 0 "投稿を止めている詰まり" "詰まりを並べた後に CLEAN と書かれても通さない" \
    "$CR_CASE" "$CR_CFG" "$CR_STUB_BLOCK_CLEAN" "$CR_POST"
# misses.log は当たった旗の綴りだけを残す。gh secret set は投稿でない(NON_POSTING)ので
# 必ず miss の枝に落ちるため、コマンドの抜粋を残すと秘密そのものが平文で溜まる
expect_output 0 "ALLOW_EMPTY" "gh secret set は投稿でないので素通し" \
    "$CR_CASE" "$CR_CFG" "$CR_STUB_FAIL" "gh secret set MY_TOKEN --body 'sk-secret-value-$CR_PAD'"
expect_output 1 "0" "misses.log に秘密の値を残さない" \
    grep -c "sk-secret-value" "$CR_CFG/coldread-gate/misses.log"

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
expect_output 0 "取り出せない" "graphql の mutation は本文を取り出せないので deny" \
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
# 表そのものを走査して、各項目が実際に効いていることを確かめる(表が増えれば検査も増える)
expect_output 0 "TABLE_OK" "判定表の全項目が効いている" "$PY_BIN" "$ROOT/tests/coldread-table-case.py"
expect_output 0 "COLDWRITE_CFG_OK" "coldwrite の宣言設定が 4 箇所で一致している" "$PY_BIN" "$ROOT/tests/coldwrite-config-check.py"
# 壊すと落ちることまで確かめる(fail-open 対策)。検査対象の 4 箇所だけを作業場に写し、
# continueOnBlock を全ハンドラから消した hooks.json で赤くなるか
CW_WORK="$WORK/coldwrite-broken"
mkdir -p "$CW_WORK/coldwrite/hooks" "$CW_WORK/coldwrite/.claude-plugin" "$CW_WORK/.claude-plugin" "$CW_WORK/tests"
cp "$ROOT/coldwrite/README.md" "$CW_WORK/coldwrite/README.md"
cp "$ROOT/coldwrite/.claude-plugin/plugin.json" "$CW_WORK/coldwrite/.claude-plugin/plugin.json"
cp "$ROOT/.claude-plugin/marketplace.json" "$CW_WORK/.claude-plugin/marketplace.json"
cp "$ROOT/README.md" "$CW_WORK/README.md"
cp "$ROOT/tests/coldwrite-config-check.py" "$CW_WORK/tests/coldwrite-config-check.py"
"$PY_BIN" - "$ROOT/coldwrite/hooks/hooks.json" "$CW_WORK/coldwrite/hooks/hooks.json" <<'PY'
import json, sys
d = json.load(open(sys.argv[1], encoding="utf-8"))
for h in d["hooks"]["PreToolUse"][0]["hooks"]:
    h.pop("continueOnBlock", None)
json.dump(d, open(sys.argv[2], "w", encoding="utf-8"), ensure_ascii=False, indent=2)
PY
expect_output 1 "continueOnBlock" "coldwrite: continueOnBlock を消すと赤くなる" "$PY_BIN" "$CW_WORK/tests/coldwrite-config-check.py"
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
expect_output 0 "取り出せない" "-H 前置があっても graphql の mutation を見逃さない" \
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
expect_output 0 "検査を通過" "--input - の JSON は殻でなく .body が読み役に届く" \
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
# 引用の中の ` や $( は展開されないので、本文の一部として読ませる(止めると普通の文章が通らない)
expect_output 0 "詰まり" "コードフェンスで始まる本文も読み役に届く" \
    "$CR_CASE" "$CR_CFG" "$CR_STUB_BLOCK" "gh issue comment 1 --body '\`\`\`
$CR_BODY $CR_PAD
\`\`\`'"
expect_output 0 "詰まり" "単一引用の中の \$( は展開されないので本文として読ませる" \
    "$CR_CASE" "$CR_CFG" "$CR_STUB_BLOCK" "gh issue comment 1 --body '\$(cat x) と書く。$CR_BODY $CR_PAD'"
# ヒアドキュメントは付いた単純コマンドに帰属させる(同じ行の別コマンドの中身を巻き込まない)
expect_output 0 "ALLOW_EMPTY" "別コマンドのヒアドキュメントを gh の本文に混ぜない" \
    "$CR_CASE" "$CR_CFG" "$CR_STUB_FAIL" "cat > /tmp/cfg.json <<'SEC'
{\"api_key\": \"$CR_BODY $CR_PAD\"}
SEC
gh pr comment 123 -F - <<'BODY'
短い本文
BODY"
# 解析器が読めなかったものは「投稿でない」ではなく「検査できない」に倒す(素通りにしない)
expect_output 0 "詰まり" "融合形の global 旗(--repo=)でもサブコマンドを見失わない" \
    "$CR_CASE" "$CR_CFG" "$CR_STUB_BLOCK" "gh --repo=o/r issue comment 1 -b '$CR_BODY $CR_PAD'"
expect_output 0 "取り出せない" "未クォートのコマンド置換は検査できないので deny" \
    "$CR_CASE" "$CR_CFG" "$CR_STUB_FAIL" "gh issue comment 1 --body \$(cat /tmp/x) # $CR_PAD"
expect_output 0 "取り出せない" "バッククォートのコマンド置換も検査できないので deny" \
    "$CR_CASE" "$CR_CFG" "$CR_STUB_FAIL" "gh issue comment 1 --body \`cat /tmp/x\` # $CR_PAD"
expect_output 0 "取り出せない" "知らない旗でサブコマンドを特定できないときは deny" \
    "$CR_CASE" "$CR_CFG" "$CR_STUB_FAIL" "gh --unknown-flag=x issue comment 1 -b '$CR_BODY $CR_PAD'"
expect_output 0 "詰まり" "project edit の --readme も網に入る" \
    "$CR_CASE" "$CR_CFG" "$CR_STUB_BLOCK" "gh project edit 1 --readme '$CR_BODY $CR_PAD'"
# mutation は body 以外のフィールドにもブロック文字列を書ける。中身を本文として抜くと ID・
# トークン・設定値まで読み役(外部プロセス)へ渡るので、本文を取り出さず一律で止める。読み役が
# 起動していればここは「coldreader の起動に失敗」になる(CR_STUB_FAIL は exit 1)——起動しないことの検査
expect_output 0 "取り出せない" "graphql の mutation はブロック文字列でも読み役へ送らずに止める" \
    "$CR_CASE" "$CR_CFG" "$CR_STUB_FAIL" "gh api graphql -f query='mutation { addComment(input:{subjectId: \"\"\"DB_PASSWORD=$CR_PAD\"\"\", body: \"\"\"$CR_BODY\"\"\"}) }'"
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
expect_output 0 "取り出せない" "api --input の .body でない長い JSON は読み役に送らず deny" \
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
# --input - でヒアドキュメントを取り損ねると候補ゼロ・止めた理由ゼロになり、「投稿でない」と
# 読まれて無検査で通る。兄弟の --body-file - と同じ向きに倒すことの検査
expect_output 0 "取り出せない" "--input - にヒアドキュメントが無ければ検査できないので deny" \
    "$CR_CASE" "$CR_CFG" "$CR_STUB_FAIL" "cat /tmp/payload.json | gh api repos/o/r/issues/1/comments --input - # $CR_PAD"
# 行末が CRLF のヒアドキュメント。\n 固定で照合すると開始行・終端行ともマッチせず、正しく書いた
# 投稿が「stdin 渡し」という嘘の理由で止まる(--body-file)か、無検査で通る(--input)
CR_CRLF_FILE=$(printf 'gh issue comment 1 --body-file - <<'\''EOF'\''\r\n%s\r\n%s\r\nEOF\r\n' "$CR_BODY" "$CR_PAD")
expect_output 0 "詰まり" "行末が CRLF のヒアドキュメントでも本文を取り出す" \
    "$CR_CASE" "$CR_CFG" "$CR_STUB_BLOCK" "$CR_CRLF_FILE"
CR_CRLF_INPUT=$(printf 'gh api repos/o/r/issues/1/comments --input - <<'\''EOF'\''\r\n{"body": "%s%s"}\r\nEOF\r\n' "$CR_BODY" "$CR_PAD")
expect_output 0 "詰まり" "CRLF のヒアドキュメントを --input - で渡しても本文を検査する" \
    "$CR_CASE" "$CR_CFG" "$CR_STUB_BLOCK" "$CR_CRLF_INPUT"
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
expect_output 0 "coldreader(文脈ゼロの読み手)の起動に失敗" "読み役出力が UTF-8 でないときは deny に倒す" \
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
# 連続 deny は書き手(session)ごと。log は profile 共有なので、並行セッションの deny を数えると
# 1 回目の書き手に「3 回連続」の案内が出て、他所の skip が自分の案内を消す(2026-09-07 に PR 1429 で実測:
# 7 回目の deny で案内が消えたのは、2 分前に別セッションが skip したため)
CR_SID_CFG="$WORK/coldread-cfg-sid"; mkdir -p "$CR_SID_CFG"
COLDREAD_TEST_SESSION=aaaa1111 "$CR_CASE" "$CR_SID_CFG" "$CR_STUB_BLOCK" "$CR_POST" >/dev/null 2>&1
COLDREAD_TEST_SESSION=aaaa1111 "$CR_CASE" "$CR_SID_CFG" "$CR_STUB_BLOCK" "$CR_POST" >/dev/null 2>&1
expect_output 0 "SID_ISOLATED" "他セッションの deny 2 回の後でも、自分の 1 回目に連続の案内は出ない" \
    env COLDREAD_TEST_SESSION=bbbb2222 "$PY_BIN" -c "$CR_REASON"$'\n''print("SID_ISOLATED" if "回連続" not in reason else "BAD: " + reason[:120])' \
    "$CR_CASE" "$CR_SID_CFG" "$CR_STUB_BLOCK" "$CR_POST"
COLDREAD_TEST_SESSION=bbbb2222 "$CR_CASE" "$CR_SID_CFG" "$CR_STUB_FAIL" "COLDREAD_SKIP=1 $CR_POST" >/dev/null 2>&1
expect_output 0 "3 回連続で止まっている" "他セッションの skip を挟んでも、自分の 3 回目で案内が出る" \
    env COLDREAD_TEST_SESSION=aaaa1111 "$CR_CASE" "$CR_SID_CFG" "$CR_STUB_BLOCK" "$CR_POST"
expect_output 0 "to=issue:cwd:1" "log の各行に session・版・投稿先が残る(どの版のどのセッションがどこへ出したかを grep で引く)" \
    grep -E $'deny\tfinding\t[0-9]+\tcold\tsid=aaaa1111\tv=[0-9.]+\tto=issue:cwd:1' "$CR_SID_CFG/coldread-gate/denies.log"

# ---- coldread: 返信の読み手には画面(投稿先のスレッド)を渡す ----------------------------
# 文脈ゼロで読ませると、画面に有るもの(相手の名前・PR 番号・相手の印・相手の語)が全部詰まりに出て、
# 書き手が宛先本人に本人の名前を説明する返信を書く(2026-09-06 に PR 1583 で実測、39 回 deny)。
# gh は代役に差し替える(CI に gh も認証も無い)。引数列で応答を選び、知らない呼び方は失敗させる
CR_GHSTUB="$WORK/ghstub.sh"
cat > "$CR_GHSTUB" <<'SH'
#!/bin/sh
case "$*" in
  "api repos/o/r/pulls/comments/77") printf '%s' '{"id":77,"in_reply_to_id":null,"path":"docs/a.adoc","line":32,"diff_hunk":"@@ -0,0 +1,3 @@\n+= 題\n+本文の行","body":"[block] F3 の行が抜けています。F3 は fixture 3 の略です。","user":{"login":"reviewer_x"},"created_at":"2026-09-04T11:21:40Z","pull_request_url":"https://api.github.com/repos/o/r/pulls/9"}' ;;
  "api repos/o/r/pulls/comments/78") printf '%s' '{"id":78,"in_reply_to_id":77,"path":"docs/a.adoc","line":32,"diff_hunk":"@@ -0,0 +1,3 @@\n+= 題\n+本文の行","body":"先の返信です","user":{"login":"author_y"},"created_at":"2026-09-05T00:00:00Z","pull_request_url":"https://api.github.com/repos/o/r/pulls/9"}' ;;
  "api repos/o/r/pulls/9") printf '%s' '{"number":9,"title":"docs: F3 の説明を足す","body":"PR の説明"}' ;;
  "api repos/o/r/pulls/9/comments?per_page=100&page=1") printf '%s' '[{"id":77,"in_reply_to_id":null,"body":"[block] F3 の行が抜けています。F3 は fixture 3 の略です。","user":{"login":"reviewer_x"},"created_at":"2026-09-04T11:21:40Z"},{"id":78,"in_reply_to_id":77,"body":"先の返信です","user":{"login":"author_y"},"created_at":"2026-09-05T00:00:00Z"},{"id":90,"in_reply_to_id":null,"body":"別スレッドの指摘","user":{"login":"reviewer_x"},"created_at":"2026-09-04T11:22:00Z"}]' ;;
  "pr view 9 --json number,title,body,comments,url,state,isDraft,files") printf '%s' '{"number":9,"title":"docs: F3 の説明を足す","body":"PR の説明","url":"https://github.com/o/r/pull/9","state":"OPEN","isDraft":false,"files":[{"path":"docs/a.adoc"},{"path":"src/f3.py"}],"comments":[{"author":{"login":"reviewer_x"},"body":"レビューしました。F3 は fixture 3 の略です。","createdAt":"2026-09-04T11:19:54Z"}]}' ;;
  "api repos/o/r/issues/5") printf '%s' '{"number":5,"title":"issue 5 の題","body":"issue の本文"}' ;;
  "api repos/o/r/issues/5/comments?per_page=100&page=1") printf '%s' '[{"id":501,"body":"issue への先のコメント。F3 は fixture 3 の略です。","user":{"login":"reviewer_x"},"created_at":"2026-09-04T00:00:00Z"}]' ;;
  *) echo "ghstub: 知らない呼び方: $*" >&2; exit 1 ;;
esac
SH
# sh で明示的に起動する(実行ビットと shebang の解釈に依らない——Windows の Git Bash でも同じ形で動く)
CR_GH="sh $CR_GHSTUB \"\$@\""
# REST の正式形(PR 番号入り)。2026-09-06 の実物の投稿 16 件がこの形で、PR 番号無しの形を
# 前提にした版はこれを取りこぼして文脈ゼロに落ちていた(自分の変更の実測で発見)
CR_REPLY="gh api repos/o/r/pulls/9/comments/77/replies -X POST --jq .html_url --input - <<'EOF'
{\"body\": \"$CR_BODY $CR_PAD\"}
EOF"
# 読み役の代役が stdin(依頼文+本文)を見て、画面が渡ったかどうかで返す文言を変える
CR_STUB_SEES_SCREEN='if grep -q "fixture 3 の略"; then echo CLEAN; else printf "詰まり: 画面(元の指摘)が読み手に渡っていない\n"; fi'
CR_STUB_SEES_PRIOR='if grep -q "先の返信です"; then echo CLEAN; else printf "詰まり: これまでの返信が渡っていない\n"; fi'
CR_STUB_OTHER_THREAD='if grep -q "別スレッドの指摘"; then printf "詰まり: 別スレッドの指摘まで渡された\n"; else echo CLEAN; fi'
CR_STUB_NO_SCREEN='if grep -q "画面に既に見えているもの"; then printf "詰まり: 新規作成なのに画面が渡された\n"; else echo CLEAN; fi'
CR_STUB_REDUNDANT='cat >/dev/null; printf "冗長: 冒頭で PR 番号とリポジトリ名を説明している\n"'
expect_output 0 "検査を通過" "review スレッドへの返信では元の指摘と PR の題が読み手に渡る" \
    "$CR_CASE" "$CR_CFG" "$CR_STUB_SEES_SCREEN" "$CR_REPLY" "$CR_GH"
expect_output 0 "検査を通過" "同じスレッドのこれまでの返信も渡る" \
    "$CR_CASE" "$CR_CFG" "$CR_STUB_SEES_PRIOR" "$CR_REPLY" "$CR_GH"
expect_output 0 "検査を通過" "PR 番号無しの replies の形も同じスレッドと読む" \
    "$CR_CASE" "$CR_CFG" "$CR_STUB_SEES_SCREEN" "gh api repos/o/r/pulls/comments/77/replies -f body='$CR_BODY $CR_PAD'" "$CR_GH"
# 読み役の代役は stdin を一度読んでから 2 条件を見る(grep を 2 回掛けると 2 回目の stdin は空)
CR_STUB_EDIT='b=$(cat); case "$b" in *"fixture 3 の略"*) case "$b" in *"先の返信です"*) printf "詰まり: 直す当のコメントが画面に残った\n";; *) echo CLEAN;; esac;; *) printf "詰まり: 元の指摘が画面に無い\n";; esac'
expect_output 0 "検査を通過" "編集(PATCH)では根の指摘は見え、直す当の返信は画面から除く" \
    "$CR_CASE" "$CR_CFG" "$CR_STUB_EDIT" "gh api repos/o/r/pulls/comments/78 -X PATCH -f body='$CR_BODY $CR_PAD'" "$CR_GH"
expect_output 0 "検査を通過" "旗が先でも後ろの番号を位置引数として読む" \
    "$CR_CASE" "$CR_CFG" "$CR_STUB_SEES_SCREEN" "gh pr comment --body '$CR_BODY $CR_PAD' 9" "$CR_GH"
expect_output 0 "検査を通過" "別スレッドの指摘は渡さない(画面に無いもの)" \
    "$CR_CASE" "$CR_CFG" "$CR_STUB_OTHER_THREAD" "$CR_REPLY" "$CR_GH"
expect_output 0 "検査を通過" "gh pr comment は PR の題と会話が読み手に渡る" \
    "$CR_CASE" "$CR_CFG" "$CR_STUB_SEES_SCREEN" "gh pr comment 9 --body '$CR_BODY $CR_PAD'" "$CR_GH"
expect_output 0 "検査を通過" "gh api issues/N/comments は issue の題と会話が読み手に渡る" \
    "$CR_CASE" "$CR_CFG" "$CR_STUB_SEES_SCREEN" "gh api repos/o/r/issues/5/comments -f body='$CR_BODY $CR_PAD'" "$CR_GH"
expect_output 0 "検査を通過" "issue の新規作成は文脈ゼロのまま(画面を渡さない)" \
    "$CR_CASE" "$CR_CFG" "$CR_STUB_NO_SCREEN" "gh issue create --title t --body '$CR_BODY $CR_PAD'" "$CR_GH"
expect_output 0 "検査を通過" "gist の新規作成も文脈ゼロのまま" \
    "$CR_CASE" "$CR_CFG" "$CR_STUB_NO_SCREEN" "$CR_GIST" "$CR_GH"
# 画面を取れないときは止めずに文脈ゼロで読み、書き手には「画面に有るものへの詰まりは無視してよい」と伝える
expect_output 0 "取れなかった" "画面を取れないときは文脈ゼロで読み、その旨を書き手に伝える(通過側)" \
    "$CR_CASE" "$CR_CFG" "$CR_STUB_CLEAN" "$CR_REPLY" "exit 1"
expect_output 0 "取れなかった" "画面を取れないときの deny にもその旨が載る" \
    "$CR_CASE" "$CR_CFG" "$CR_STUB_BLOCK" "$CR_REPLY" "exit 1"
# 画面は参加者が実際に見ているものまで: 状態・変更ファイル・本文が参照する #番号 の題(2026-09-07 の
# PR 1429 で、用語集 19 語を生んだ最初の詰まりは「#1231 #1581 #1283 が何か」だった)
CR_STUB_SEES_STATE='if grep -q "、open)"; then echo CLEAN; else printf "詰まり: PR の状態が画面に無い\n"; fi'
CR_STUB_SEES_FILES='if grep -q "src/f3.py"; then echo CLEAN; else printf "詰まり: 変更ファイルの一覧が画面に無い\n"; fi'
CR_STUB_SEES_REF='if grep -q "issue 5 の題"; then echo CLEAN; else printf "詰まり: 本文が参照する #5 の題が画面に無い\n"; fi'
expect_output 0 "検査を通過" "PR の状態(open/merged/draft)が画面に載る" \
    "$CR_CASE" "$CR_CFG" "$CR_STUB_SEES_STATE" "gh pr comment 9 --body '$CR_BODY $CR_PAD'" "$CR_GH"
expect_output 0 "検査を通過" "PR の変更ファイルの一覧が画面に載る" \
    "$CR_CASE" "$CR_CFG" "$CR_STUB_SEES_FILES" "gh pr comment 9 --body '$CR_BODY $CR_PAD'" "$CR_GH"
expect_output 0 "検査を通過" "本文が参照する #番号 の題を引いて画面に載せる" \
    "$CR_CASE" "$CR_CFG" "$CR_STUB_SEES_REF" "gh pr comment 9 --body '$CR_BODY #5 を閉じる $CR_PAD'" "$CR_GH"
# 画面が既知にするのは「何を指しているか」で、「どう書くか」ではない。画面を語彙の辞書にすると、
# スレッドの癖のある書き方に読み手が引っ張られ、本文がその癖を写す向きに働く
CR_STUB_VOCAB='if grep -q "なぞり: 」"; then echo CLEAN; else printf "詰まり: 画面を語彙の辞書にしない規則(なぞりの欄)が依頼文に無い\n"; fi'
expect_output 0 "検査を通過" "画面モードの依頼文は、画面を語彙の辞書にしない(相手の語を地の文で使えば「なぞり」)" \
    "$CR_CASE" "$CR_CFG" "$CR_STUB_VOCAB" "gh pr comment 9 --body '$CR_BODY $CR_PAD'" "$CR_GH"
# なぞりは詰まりと同じく止める。詰まりの条件文に埋めた形は実物の読み手に 1 件も拾われなかった(2026-09-07 に実測)
CR_STUB_TRACED='cat >/dev/null; printf "なぞり: 「ニアバイして」は reviewer_x の語をそのまま地の文に使っている\n"'
expect_output 0 "自分の言葉に直せば通る" "相手の言い回しを地の文に写した箇所(なぞり)は投稿を止め、直し方は説明を足すことではないと言う" \
    "$CR_CASE" "$CR_CFG" "$CR_STUB_TRACED" "gh pr comment 9 --body '$CR_BODY $CR_PAD'" "$CR_GH"
CR_STUB_TRACED_NONE='cat >/dev/null; printf "なぞり: なし\n"'
expect_output 0 "検査を通過" "「なぞり: なし」は 0 件として通る" \
    "$CR_CASE" "$CR_CFG" "$CR_STUB_TRACED_NONE" "gh pr comment 9 --body '$CR_BODY $CR_PAD'" "$CR_GH"
expect_output 0 "相手の語で書かない" "返信の deny の直し方に「相手の語は指してよいが、相手の語で書かない」が在る" \
    "$CR_CASE" "$CR_CFG" "$CR_STUB_BLOCK" "gh pr comment 9 --body '$CR_BODY $CR_PAD'" "$CR_GH"
# 予算を超えたら古いコメントから落とす。旧版は組んだ後に末尾を切り、本文を長く見せるほど最新の返信が落ちた
expect_output 0 "ASSEMBLE_OK" "画面が予算を超えたら古いコメントから落とし、最後の 1 件(答える相手)と本文は残る" \
    "$PY_BIN" -c "$CR_LOAD"$'\n''blocks=[["[c%d]"%i, "x"*g.SCREEN_BODY_MAX] for i in range(20)]
out=g.assemble(["title","[本文]"], "b"*3000, blocks, ["tail"])
ok = len(out)<=g.SCREEN_MAX and "[c19]" in out and "[c0]" not in out and "省略" in out and "tail" in out and "b"*3000 in out
print("ASSEMBLE_OK" if ok else "BAD len=%d" % len(out))' "$ROOT/gates/hooks/coldread-gate.py"
# 古い版で走り続けるセッションに、新しい版が cache に在ることを伝える(フックの版はセッション開始時に固定。
# 2026-09-07 に実測: 0.9.0 導入前に開始したセッションが 16 時間 0.8.0 のまま検査していた)
CR_VCACHE="$WORK/vcache/gates"
mkdir -p "$CR_VCACHE/0.1.0/hooks" "$CR_VCACHE/0.1.0/.claude-plugin" "$CR_VCACHE/0.2.0/hooks" "$CR_VCACHE/0.10.0/hooks"
cp "$ROOT/gates/hooks/coldread-gate.py" "$CR_VCACHE/0.1.0/hooks/"
echo '{"name":"gates","version":"0.1.0"}' > "$CR_VCACHE/0.1.0/.claude-plugin/plugin.json"
: > "$CR_VCACHE/0.2.0/hooks/coldread-gate.py"
expect_output 0 "0.2.0 が在る" "cache に新しい版が在れば検査結果にその旨が載る(本体の無い 0.10.0 は入りかけなので拾わない)" \
    env COLDREAD_GATE="$CR_VCACHE/0.1.0/hooks/coldread-gate.py" "$CR_CASE" "$CR_CFG" "$CR_STUB_BLOCK" "$CR_POST"
expect_output 0 "NO_NOTE" "開発 checkout(兄弟が版名でない)では版の注記を出さない" \
    "$PY_BIN" -c "$CR_LOAD"$'\n''print("NO_NOTE" if g.VERSION_NOTE == "" else "BAD: " + g.VERSION_NOTE)' "$ROOT/gates/hooks/coldread-gate.py"
# 冗長(画面に有るものの説明)は止めない申し送り。詰まりと同じ欄に混ぜると「直せ」と読まれる
expect_output 0 "削ってよい" "冗長は止めずに申し送る" \
    "$CR_CASE" "$CR_CFG" "$CR_STUB_REDUNDANT" "$CR_REPLY" "$CR_GH"
# 直し方は読み方で変える。画面モードで「同型を掃討」と言うと、画面に有るものの説明を足す向きに働く
expect_output 0 "足すより削る" "スレッドへの返信の deny は「足すより削る」と案内する" \
    "$CR_CASE" "$CR_CFG" "$CR_STUB_BLOCK" "$CR_REPLY" "$CR_GH"
expect_output 0 "掃討" "新規作成の deny は従来の「同型を掃討」の案内のまま" \
    "$CR_CASE" "$CR_CFG" "$CR_STUB_BLOCK" "gh issue create --title t --body '$CR_BODY $CR_PAD'" "$CR_GH"
# 「詰まり: なし」は 0 件であって 1 件ではない。依頼文で省けと言っても読み手は書く(2026-09-06 に実測:
# 画面モードの読み手が書き、837 字の返信が止まった)。落とさないと無い欄が投稿を止める
CR_STUB_NONE='cat >/dev/null; printf "詰まり: なし\n補完: 無し。\n疑問: 期限はいつか\n"'
expect_output 0 "検査を通過" "「詰まり: なし」は詰まりに数えない(疑問だけ残って通る)" \
    "$CR_CASE" "$CR_CFG" "$CR_STUB_NONE" "$CR_POST"
CR_STUB_NONE_ONLY='cat >/dev/null; printf "詰まり: なし\n"'
expect_output 0 "検査を通過" "「詰まり: なし」だけの出力は CLEAN と同じに通る" \
    "$CR_CASE" "$CR_CFG" "$CR_STUB_NONE_ONLY" "$CR_POST"
# 読み役は利用者の CLAUDE.md を読まない(--setting-sources を空で起動)。2026-09-06 に実測: 無しだと
# 利用者の CLAUDE.md の見出しをそのまま引用し、有りだと NONE。CI に claude は無いので起動引数で縛る
expect_output 0 "READER_ARGV_OK" "読み役の起動引数に --setting-sources '' と --tools '' が在る" \
    "$PY_BIN" -c "$CR_LOAD"$'\n''a=g.reader_argv("claude","x")
ok = "--setting-sources" in a and a[a.index("--setting-sources")+1]=="" and "--tools" in a and a[a.index("--tools")+1]==""
print("READER_ARGV_OK" if ok else "BAD %r" % a)' "$ROOT/gates/hooks/coldread-gate.py"
# 連続 deny の案内は先頭に置き、本文の膨れ方を数字で示す(末尾の案内は 36 回無視された)
CR_GROW_CFG="$WORK/coldread-cfg-grow"; mkdir -p "$CR_GROW_CFG"
"$CR_CASE" "$CR_GROW_CFG" "$CR_STUB_BLOCK" "$CR_POST" >/dev/null 2>&1
"$CR_CASE" "$CR_GROW_CFG" "$CR_STUB_BLOCK" "$CR_POST" >/dev/null 2>&1
CR_POST_LONGER="gh issue comment 1 --body-file - <<'EOF'
$CR_BODY
$CR_BODY
$CR_PAD
EOF"
expect_output 0 " → " "3 回連続 deny で本文が増えていれば、1 回ごとの字数の数列を案内に載せる" \
    "$CR_CASE" "$CR_GROW_CFG" "$CR_STUB_BLOCK" "$CR_POST_LONGER"
# 出させるのは「今の本文」でなく「最初の本文」。旧文言は膨れた版を出せと読めた(1429: 5,455 字 → 10,179 字で skip)
expect_output 0 "最初の本文に戻し" "3 回連続 deny の案内は、最初の本文に戻してから出せと言う" \
    "$CR_CASE" "$CR_GROW_CFG" "$CR_STUB_BLOCK" "$CR_POST_LONGER"
expect_output 0 "HEAD_OK" "3 回連続 deny の案内は deny 理由の先頭に在る" \
    "$PY_BIN" -c "$CR_REASON"$'\n''print("HEAD_OK" if reason.startswith("【") and "足して直さない" in reason[:80] else "BAD: " + reason[:120])' \
    "$CR_CASE" "$CR_GROW_CFG" "$CR_STUB_BLOCK" "$CR_POST_LONGER"

# ---- destgate: 投稿先の許可一覧(coldread と独立の軸。一覧が無ければ眠る) ----
DG_CASE="$ROOT/tests/destgate-case.sh"
DG_CFG="$WORK/destgate-cfg"; mkdir -p "$DG_CFG/destgate"
printf 'good/*\nallowed/repo\n' > "$DG_CFG/destgate/allowlist"
DG_NOCFG="$WORK/destgate-nocfg"; mkdir -p "$DG_NOCFG"
DG_POST_EVIL="gh issue comment 1 -R evil/place --body 'こんにちは、これは宛先検査のテスト本文です'"

expect_output 0 "ALLOW_EMPTY" "destgate: 一覧が無ければ眠る(投稿でも素通し)" \
    "$DG_CASE" "$DG_NOCFG" "$WORK" "$DG_POST_EVIL"
expect_output 0 "ALLOW_EMPTY" "destgate: 一覧内の宛先(完全一致)は通る" \
    "$DG_CASE" "$DG_CFG" "$WORK" "gh issue comment 1 -R allowed/repo --body 'テストの本文です'"
expect_output 0 "ALLOW_EMPTY" "destgate: owner/* パターンで通る" \
    "$DG_CASE" "$DG_CFG" "$WORK" "gh pr comment 2 -R good/anything --body 'テストの本文です'"
expect_output 0 "許可一覧に無い" "destgate: 一覧外の宛先は deny" \
    "$DG_CASE" "$DG_CFG" "$WORK" "$DG_POST_EVIL"
expect_output 0 "許可一覧に無い" "destgate: COLDREAD_SKIP=1 でも宛先検査は外れない" \
    "$DG_CASE" "$DG_CFG" "$WORK" "COLDREAD_SKIP=1 $DG_POST_EVIL"
expect_output 0 "許可一覧に無い" "destgate: 行継続で折り返しても宛先検査は外れない" \
    "$DG_CASE" "$DG_CFG" "$WORK" "gh issue comment 1 -R evil/place \\
  --body 'こんにちは、これは宛先検査のテスト本文です'"
expect_output 0 "ALLOW_EMPTY" "destgate: 読み取り系は宛先が一覧外でも素通し" \
    "$DG_CASE" "$DG_CFG" "$WORK" "gh pr list -R evil/place --limit 5"
expect_output 0 "許可一覧に無い" "destgate: gh api の repos/ パスから宛先を取る" \
    "$DG_CASE" "$DG_CFG" "$WORK" "gh api repos/evil/place/issues/1/comments -f body='宛先検査のテスト本文です'"
expect_output 0 "特定できない" "destgate: 宛先を特定できない投稿は deny(-R の明示を促す)" \
    "$DG_CASE" "$DG_CFG" "$WORK" "gh api graphql -f query='mutation { m }' -f body='宛先検査のテスト本文です'"

# 明示の -R が無い投稿は、gh と同じくカレントの git remote を宛先とみなす
DG_REPO_OK="$WORK/dg-repo-ok"; git init -q "$DG_REPO_OK"; git -C "$DG_REPO_OK" remote add origin git@github.com:good/things.git
DG_REPO_NG="$WORK/dg-repo-ng"; git init -q "$DG_REPO_NG"; git -C "$DG_REPO_NG" remote add origin https://github.com/evil/place.git
expect_output 0 "ALLOW_EMPTY" "destgate: -R 無しは git remote を宛先にする(一覧内)" \
    "$DG_CASE" "$DG_CFG" "$DG_REPO_OK" "gh issue comment 1 --body 'テストの本文です'"
expect_output 0 "許可一覧に無い" "destgate: -R 無しの git remote が一覧外なら deny" \
    "$DG_CASE" "$DG_CFG" "$DG_REPO_NG" "gh issue comment 1 --body 'テストの本文です'"

# ---- attention/catchup: 1 件の PR / issue の「前回から何が起きたか」 ----
# 取得(gh / GraphQL)は網の外。ここで検査するのは材料 → 出力の規則だけで、取得をモックすると
# 検査対象が自分で書いたモックになる
CU_CASE="$ROOT/tests/catchup-case.py"

expect_output 0 "レビュー結果です。block が 1 件あります" \
    "catchup: 自分の最後の発言が「私が最後にしたこと」になる" "$PY_BIN" "$CU_CASE" mine
expect_output 0 "私宛の依頼が来ていて、その後に私は発言していない" \
    "catchup: 依頼ボタンも未解決スレッドも無い名指しの依頼を手番として拾う" \
    "$PY_BIN" "$CU_CASE" mine
expect_output 0 "人にしか判断できない 3 点" \
    "catchup: 依頼が「渡された時点」より前でも拾う" "$PY_BIN" "$CU_CASE" ask-before-handover
expect_output 0 "で私に渡された" \
    "catchup: 未発言の件はそう言う（作成時に落とさず、渡された時点を出す）" \
    "$PY_BIN" "$CU_CASE" ask-before-handover
expect_output 0 "レビュアー · ● 私の番" \
    "catchup: レビュー依頼が来ていれば立場はレビュアー" "$PY_BIN" "$CU_CASE" ask-before-handover
expect_output 0 "レビュー依頼 を出している" \
    "catchup: 本文の依頼を優先しつつ、後から押された依頼ボタンも申し送る" \
    "$PY_BIN" "$CU_CASE" ask-prefers-text
expect_output 0 "未参加 · ○ 待ち — レビュー待ち: someone" \
    "catchup: 依頼も担当も発言も無ければ私の番ではなく、立場は未参加" "$PY_BIN" "$CU_CASE" waiting
expect_output 0 "実装者（作者） · ● 私の番" \
    "catchup: 作者なら立場は実装者" "$PY_BIN" "$CU_CASE" ci-unknown-conclusion
expect_output 0 "    - CI 赤は作者（私）しか外せない" \
    "catchup: 知らない conclusion は赤に倒す。理由が複数なら箇条書き" \
    "$PY_BIN" "$CU_CASE" ci-unknown-conclusion
expect_output 0 "赤 1 件（deploy）" \
    "catchup: 赤いチェックの名前を出す" "$PY_BIN" "$CU_CASE" ci-unknown-conclusion
expect_output 0 "lint  https://example.invalid/runs/1" \
    "catchup: 赤いチェックに行き先の URL を添える" "$PY_BIN" "$CU_CASE" ci-red-url
expect_output 0 "CI が落ちた理由（上の URL か gh pr checks で見る）" \
    "catchup: 焦点で CI の材料を外したときは、落ちた理由は見ていないと断り、CI を付ける口を書く" \
    "$PY_BIN" "$CU_CASE" ci-red-url
expect_output 0 "実行中 1 件" \
    "catchup: 走っている最中は赤にも緑にも数えない" "$PY_BIN" "$CU_CASE" ci-running
expect_output 0 "書きかけのレビューが未送信" \
    "catchup: 未送信レビューを自分の宿題として出す" "$PY_BIN" "$CU_CASE" pending-review
expect_output 0 "その後に起きたこと — 0 件" \
    "catchup: 未送信レビューを時系列に混ぜない（相手には届いていない）" \
    "$PY_BIN" "$CU_CASE" pending-review
expect_output 0 "未解決スレッド 1 件で相手が返している（私が返す番）" \
    "catchup: 自分が入っている未解決スレッドの返答を手番として拾う" \
    "$PY_BIN" "$CU_CASE" thread-turn
expect_output 0 "CI: 報告なし" \
    "catchup: チェックが 1 本も無い状態を「全 pass」と言わない" "$PY_BIN" "$CU_CASE" no-checks
expect_output 0 "この件で私はまだ何もしていない" \
    "catchup: 触っていない件はそう言う" "$PY_BIN" "$CU_CASE" no-checks
expect_output 0 "まだ承認されていない（REVIEW_REQUIRED）" \
    "catchup: API の値をそのまま出さず、中身を先に書いて原語を括弧で添える" \
    "$PY_BIN" "$CU_CASE" waiting
expect_output 0 "コメントの古い方 139 件（140 件中、新しい 1 件だけ取った）" \
    "catchup: 取得上限に当たったら黙って切らず、何を見落としうるかまで申告する" \
    "$PY_BIN" "$CU_CASE" cap
expect_output 0 "（本文なし）" \
    "catchup: 引用だけの本文を発言の中身として扱わない" "$PY_BIN" "$CU_CASE" quote-only
expect_output 0 "その後に起きたこと — 0 件" \
    "catchup: login に結び付いていない commit を、手元の git config の user.email と照合して自分の push にする" \
    "$PY_BIN" "$CU_CASE" push-alias
expect_output 0 "me-git が push" \
    "catchup: メールが一致しなければ、結び付いていない commit は名前のまま他人として出す（名前では照合しない）" \
    "$PY_BIN" "$CU_CASE" push-stranger
expect_output 0 "結び付いていない commit（名前: me-git）が誰のものか" \
    "catchup: 照合に外れた結び付き無しの commit を末尾で申告する" \
    "$PY_BIN" "$CU_CASE" push-stranger
expect_output 0 "私の最後の発言（" \
    "catchup: 自分の件で本文なしの承認と解決済みスレッドは「求められていること」に拾わない" \
    "$PY_BIN" "$CU_CASE" ask-on-my-item-empty
expect_output 0 "レビュー依頼が誰にも出ていない（依頼先を決めるのは私）" \
    "catchup: 自分の PR でレビュー依頼が誰にも出ていなければ、渡すのは私" \
    "$PY_BIN" "$CU_CASE" own-pr-unrequested
expect_output 0 "未参加 · ● 私の番 — 私宛の依頼が来ていて" \
    "catchup: 名指しで呼ばれただけの件は「未参加 · 私の番」（どちらでもないと断定しない）" \
    "$PY_BIN" "$CU_CASE" mentioned-outsider
expect_output 0 "再確認をお願いします" \
    "catchup: push は返事ではない——最後の痕跡が push でも、依頼は最後の発言より後から探す" \
    "$PY_BIN" "$CU_CASE" push-not-cutoff
expect_output 0 "名指しは無い。私の件への発言" \
    "catchup: 自分の件では名指しの無い発言も最後の 1 件を拾い、名指しが無いと断る" \
    "$PY_BIN" "$CU_CASE" ask-on-my-item
expect_output 0 "問いかは本文で確かめる" \
    "catchup: 名指しの無い発言は、問いかどうかを機械で決めずに手番の理由に書く" \
    "$PY_BIN" "$CU_CASE" ask-on-my-item
expect_output 0 "その後に起きたこと — 0 件" \
    "catchup: 参照（他の PR がこの番号を書いた）を出来事に数えない" \
    "$PY_BIN" "$CU_CASE" refs-not-events
expect_output 0 "#99 別の PR" \
    "catchup: 参照はつながっている先に置く" "$PY_BIN" "$CU_CASE" refs-not-events
expect_output 0 "○ 待ち — レビュー待ち: someone" \
    "catchup: 自分の PR の assignee は、それだけでは私の番の理由にならない" \
    "$PY_BIN" "$CU_CASE" assignee-own-pr
expect_output 0 "担当 · ● 私の番 — 私が担当（assignee）" \
    "catchup: issue では担当が手番の根拠で、立場も担当" "$PY_BIN" "$CU_CASE" issue-assignee
expect_output 0 "ISSUE_UNSEEN_OK" \
    "catchup: issue の「見ていないもの」に diff を書かず、本文は上限で切れた分だけ申告する" \
    "$PY_BIN" "$CU_CASE" issue-not-seen
expect_output 1 "使い方" \
    "catchup: 知らないケース名は落ちる（検査自体の空振りを防ぐ）" "$PY_BIN" "$CU_CASE"
expect_output 1 "番号か PR / issue の URL、手元の commit を渡す" \
    "catchup: 番号でも URL でもない引数は、gh を叩く前に落とす" \
    "$PY_BIN" "$ROOT/attention/scripts/catchup.py" abc
expect_output 1 "対象は 1 つだけ渡す" \
    "catchup: 対象を 2 つ渡したら gh を叩く前に落とす" \
    "$PY_BIN" "$ROOT/attention/scripts/catchup.py" 1 2
expect_output 0 "SPLIT_OK" \
    "catchup: 引数の語を対象と焦点（指摘・地図・CI）に分ける。焦点だけ・引数なしは今のブランチ" \
    "$PY_BIN" "$CU_CASE" split-words
expect_output 0 "TAILS_OK" \
    "catchup: 末尾の材料は有れば全部出す（自分の PR にも地図）。焦点はその 1 つに絞り、issue には無い" \
    "$PY_BIN" "$CU_CASE" tails-by-existence
expect_output 0 "WORDING_OK" \
    "catchup: 焦点なしの既定では、赤なら CI の材料が付くので「見ていない」と断らず、PR なら地図が付くと言う" \
    "$PY_BIN" "$CU_CASE" tails-default-wording
expect_output 0 "THREADS_OK" \
    "catchup: 指摘の材料は相手の発言がある未解決スレッドだけ。相手の最後の発言と head の前後の行、file の外の行はそう言う" \
    "$PY_BIN" "$CU_CASE" threads-material
expect_output 0 "SINCE_OK" \
    "catchup: 私が返す番で相手が私の発言の後に返した件は、私の発言以降の変更を今の姿に帯で出す。共通の字下げは落とし、代入の文字列リテラルの中は畳む。字下げのある def も関数の境目" \
    "$PY_BIN" "$CU_CASE" threads-since
expect_output 0 "BRANCH_OK" \
    "catchup: ブランチ名の番号は区切りに挟まれた数字だけ（版の数字を番号にせず、1 桁は通す）" \
    "$PY_BIN" "$CU_CASE" branch-number
expect_output 0 "CI_OK" \
    "catchup: CI の材料は Actions の run だけログを取り、行頭の印を落として最後の ##[error] までにする" \
    "$PY_BIN" "$CU_CASE" ci-material
expect_output 0 "BODY_OK" \
    "catchup: 本文の材料は作者の本文を 60 行まで（--full で全部）、閉じる issue は冒頭 12 行。行は 1 文字も変えない" \
    "$PY_BIN" "$CU_CASE" body-material
expect_output 0 "REFS_OK" \
    "catchup: 本文が # で指す番号の冒頭を 3 件まで出す（自分・閉じる issue・URL の fragment は除く。PR は PR と言う）" \
    "$PY_BIN" "$CU_CASE" body-refs
expect_output 0 "STACKED_OK" \
    "catchup: 取り込み先が既定ブランチでなければその枝と枝の PR（fork の同名は除く）を出し、上に積む open PR は 3 件＋「他にもある」" \
    "$PY_BIN" "$CU_CASE" stacked
expect_output 0 "STACKED_OK" \
    "catchup: 取り込み先が既定ブランチなら取り込み先の行は出ない" \
    "$PY_BIN" "$CU_CASE" stacked-default
expect_output 0 "SUGGESTED_OK" \
    "catchup: 依頼先の候補（GitHub の提案）は自分の PR で依頼が誰にも出ていないときだけ根拠つきで出し、空なら「なし」、依頼があれば出ない" \
    "$PY_BIN" "$CU_CASE" suggested
expect_output 0 "SINCE_OK" \
    "catchup: 私の痕跡以降に変わった file——基準がレビューなら厳密、作者側の commit だけ file を取り取り込みは数だけ、status は git の 1 文字で最後の commit のもの" \
    "$PY_BIN" "$CU_CASE" since-review
expect_output 0 "SINCE_OK" \
    "catchup: 基準が本文コメントなら commit の日付で置いた近似と断り、最初の commit より前なら節を出さない" \
    "$PY_BIN" "$CU_CASE" since-approx
expect_output 0 "SINCE_OK" \
    "catchup: 基準の commit が履歴に無ければ（rebase / amend）その 1 行だけで、file は取りに行かない" \
    "$PY_BIN" "$CU_CASE" since-rewritten
expect_output 0 "SINCE_OK" \
    "catchup: allCommits が 100 本で切れていて基準が窓に無ければ「書き換え」と断定せず、取っていないと言う" \
    "$PY_BIN" "$CU_CASE" since-outside
expect_output 0 "MAP_JUMPS_OK" \
    "catchup: 地図の変更に、各枠の前の飛び先 path:行 と見出しの断り。散文（md）も枠、新規は path:1、削除 file だけ飛び先が無い" \
    "$PY_BIN" "$CU_CASE" map-jumps

expect_output 0 "OK" \
    "catchup: ブランチ名で呼ぶと移る（手元の枝／origin にだけ有る枝は作って／既に居る／未コミットで移らない）。移った枝では既定ブランチより先の commit の変更が木と枠で出て、main では出ない" \
    "$PY_BIN" "$ROOT/tests/catchup-switch-case.py" branch-name

expect_output 0 "WIRING_OK" \
    "catchup: main() の受け口の配線——焦点の断りは人の語（内部 key を出さない）、commit の 地図 は断らない、none の --frame は PR か commit に案内して止まる、commit の --switch は移る先が無いと言う" \
    "$PY_BIN" "$CU_CASE" main-wiring

expect_output 0 "COMMIT_OK" \
    "catchup: commit（sha・HEAD~2・タグ）を渡すと GitHub に聞かず、題と本文・木・変更の中身（枠と飛び先）を出す。--frame は 1 file を全部" \
    "$PY_BIN" "$CU_CASE" commit

expect_output 0 "RANGE_OK" \
    "catchup: commit の範囲 A..B（A...B は merge-base から）を渡すと、commit の一覧（古い順）・木・変更の中身（枠と飛び先は B の版）を 1 commit と同じ形で出す。--frame は 1 file を全部" \
    "$PY_BIN" "$CU_CASE" range

expect_output 0 "NO_TARGET_OK" \
    "catchup: PR も番号も無いブランチ（main 等）でも止まらず、GitHub に聞かずに手元のブランチと未コミットの中身（枠と飛び先）を出す" \
    "$PY_BIN" "$CU_CASE" no-target
# stdio の UTF-8 固定を OS 非依存で検査する(reconfigure が消えると cp1252 強制下で
# UnicodeEncodeError になり、日本語の報告そのものが出せない＝道具が丸ごと使えなくなる。
# GitHub Actions の windows-latest で実測して赤くなった)
expect_output 0 "○ 待ち" \
    "catchup: stdio を cp1252 に強制しても日本語の報告が出る" \
    env PYTHONIOENCODING=cp1252 "$PY_BIN" "$CU_CASE" waiting
expect_output 1 "番号か PR / issue の URL、手元の commit を渡す" \
    "catchup: cp1252 強制下でも引数エラーの日本語が出る" \
    env PYTHONIOENCODING=cp1252 "$PY_BIN" "$ROOT/attention/scripts/catchup.py" abc

# ---- attention/catchup --switch: 該当ブランチへ移る（一時の git リポジトリで実際に動かす） ----
# GitHub には触らない。guard は「git 自身が止めない状態」で組む（枝で中身が違う file で汚すと guard を
# 消しても git が拒んで緑のまま）。合否は行の文言と git の状態（branch --show-current 等）の両方で見る
CS_CASE="$ROOT/tests/catchup-switch-case.py"
expect_output 0 "--switch" "catchup: --switch の口がある（命令書が番号か URL の呼び方に付ける）" \
    "$PY_BIN" "$ROOT/attention/scripts/catchup.py" --help
expect_output 0 "ISSUE_OK" \
    "catchup --switch: issue の移る先は名前に番号を持つ手元の枝が 1 本のときだけ（純関数。0 本・2 本以上は候補名）" \
    "$PY_BIN" "$CU_CASE" issue-branch
expect_output 0 "SWITCH_OK" "catchup --switch: きれいな木なら移り、元のブランチ名を行に残す" \
    "$PY_BIN" "$CS_CASE" moved
expect_output 0 "SWITCH_OK" "catchup --switch: 追跡ファイルの未コミット（git は持ち越せる）があれば移らず、変更もそのまま" \
    "$PY_BIN" "$CS_CASE" dirty
expect_output 0 "SWITCH_OK" "catchup --switch: 未追跡だけなら移り、持ち越した数を行に書く" \
    "$PY_BIN" "$CS_CASE" untracked
expect_output 0 "SWITCH_OK" "catchup --switch: ignored の file を対象の枝が追跡していれば上書きせず止まる（--no-overwrite-ignore）" \
    "$PY_BIN" "$CS_CASE" ignored
expect_output 0 "SWITCH_OK" "catchup --switch: 既に居れば移らず、居る扱い（手元の節が付く）" \
    "$PY_BIN" "$CS_CASE" already
expect_output 0 "SWITCH_OK" "catchup --switch: 別の worktree に checkout 済みの枝には移らず、機械の言葉でその旨" \
    "$PY_BIN" "$CS_CASE" worktree
expect_output 0 "SWITCH_OK" "catchup --switch: origin にだけある枝は、その 1 本を fetch して作って移る（手元の古い追跡 ref からは作らない。追跡先は origin/<枝>）" \
    "$PY_BIN" "$CS_CASE" remote-only
expect_output 0 "SWITCH_OK" "catchup --switch: 手元に無い枝でも guard が先——未コミットがあれば fetch もせず止まり、一手は git switch でなく「もう一度 /catchup」、行に今どこに居るかが添う" \
    "$PY_BIN" "$CS_CASE" remote-dirty
expect_output 0 "SWITCH_OK" "catchup --switch: origin から作るときも ignored の file を上書きせず、拒まれたら枝を作らない" \
    "$PY_BIN" "$CS_CASE" remote-ignored
expect_output 0 "SWITCH_OK" "catchup --switch: 手元にも origin にも無ければ作らずそう言う（merge 済みなら削除済みと取り方、届かなければ git の言い分、応答が無ければ timeout）" \
    "$PY_BIN" "$CS_CASE" none
expect_output 0 "SWITCH_OK" "catchup --switch: fork の PR の枝が手元に無ければ origin の refs/pull/N/head から作って移り、追跡先は gh pr checkout と同じ" \
    "$PY_BIN" "$CS_CASE" fork-remote
expect_output 0 "SWITCH_OK" "catchup --switch: origin が別のリポジトリ・origin 無しなら移らない（その行にも今どこに居るかが付く）" \
    "$PY_BIN" "$CS_CASE" origin-mismatch
expect_output 0 "SWITCH_OK" "catchup --switch: git の checkout でない場所では移らない（落ちない）" \
    "$PY_BIN" "$CS_CASE" no-git
expect_output 0 "SWITCH_OK" "catchup --switch: guard の git status が読めなければ（None）止める。空と同じにしない（純関数）" \
    "$PY_BIN" "$CS_CASE" status-none
expect_output 0 "SWITCH_OK" "catchup --switch: fork の PR は名前だけでは移らず、手元の枝が head の commit を含むときだけ移る（手元が古い・無関係なら移らない）" \
    "$PY_BIN" "$CS_CASE" fork
expect_output 0 "SWITCH_OK" "catchup --switch: head が main の fork PR で手元の main に移らず、<owner>/main を無ければ refs/pull/N/head から作り、あればそれに移る。消えた fork は名前だけでは移らない" \
    "$PY_BIN" "$CS_CASE" fork-main
expect_output 0 "SWITCH_OK" "catchup --switch: origin が自分の fork（三角 workflow）なら、その fork からの PR は名前一致で移る" \
    "$PY_BIN" "$CS_CASE" triangular
expect_output 0 "SWITCH_OK" "catchup --switch: 解決済みの merge（MERGE_HEAD あり）は「途中」と言って移らない（stash は MERGE_HEAD を消す）" \
    "$PY_BIN" "$CS_CASE" merge
expect_output 0 "LINE_OK" "catchup --switch: 結果の行は見出しの URL の直下（命令書が位置に依存する）。無ければ足さない" \
    "$PY_BIN" "$CU_CASE" branch-line
expect_output 0 "SWITCH_OK" "catchup --switch: post-checkout hook が非 0 でも HEAD は移っているので移った扱い（終了コードで判定しない）" \
    "$PY_BIN" "$CS_CASE" hook
expect_output 0 "SWITCH_OK" "catchup --switch: index.lock（他のセッションが git を動かしている最中）なら移れず、その名前が行に出る" \
    "$PY_BIN" "$CS_CASE" lock
expect_output 0 "SWITCH_OK" "catchup --switch: 同名のタグがあっても枝を見失わない" \
    "$PY_BIN" "$CS_CASE" tag-shadow
expect_output 0 "SWITCH_OK" "catchup --switch: - で始まる枝名をオプションと取り違えない" \
    "$PY_BIN" "$CS_CASE" dash-name
expect_output 0 "SWITCH_OK" "catchup --switch: detached から移れ、置き去りの commit の警告を行に添える" \
    "$PY_BIN" "$CS_CASE" detached
expect_output 0 "SWITCH_OK" "catchup --switch: 衝突した rebase の途中なら「途中」と言って移らない（commit か stash とは言わない）" \
    "$PY_BIN" "$CS_CASE" rebase
expect_output 0 "SWITCH_OK" "catchup --switch: issue は名前に番号を持つ手元の枝が 1 本のときだけ移る（0 本・2 本以上は候補名）" \
    "$PY_BIN" "$CS_CASE" issue
expect_output 0 "SWITCH_OK" "catchup --switch: 手元の節で、PR の head より後ろなら数え、head を持っていなければそう言う" \
    "$PY_BIN" "$CS_CASE" behind
expect_exit 1 "catchup --switch: 知らないケース名は落ちる（検査自体の空振りを防ぐ）" "$PY_BIN" "$CS_CASE"

# ---- attention/scripts/lib/changemap: 変更の地図の部品（/catchup と /what-am-i-doing が共用） ----
# git にも GitHub にも触らない。diff の分解・骨組み・木の描画を固定の材料で叩く
expect_output 0 "OK" "changemap: 変更の地図の部品の回帰（unittest。引用形の日本語 path・改名・木の周辺）" \
    "$PY_BIN" "$ROOT/tests/changemap-suite.py"

# ---- attention/what-am-i-doing: いま居るセッションで何が起きたか ----
# 本物のセッション記録には触らない。作業用の設定ディレクトリを毎回作って差し替える
WAI_CASE="$ROOT/tests/what-am-i-doing-case.py"

expect_output 0 "→ 直して push しました" \
    "what-am-i-doing: 依頼と返答を対で並べる（片方だけでは追いつけない）" \
    "$PY_BIN" "$WAI_CASE" pairs
expect_output 0 "やり取り 1 往復" \
    "what-am-i-doing: 道具の出力を依頼に数えない（tool_result も user レコードで落ちる）" \
    "$PY_BIN" "$WAI_CASE" ignores-tool-results
expect_output 0 "テスト実行・コミット・push" \
    "what-am-i-doing: 区切りになる操作を Bash の中身から拾う" "$PY_BIN" "$WAI_CASE" landmarks
expect_output 0 "道具 Bash×2, WebSearch×1" \
    "what-am-i-doing: 何の道具を何回使ったかを添える" "$PY_BIN" "$WAI_CASE" tool-counts
expect_output 0 "ONLY_FIRST_OK" \
    "what-am-i-doing: 返答は最初のひとまとまりだけ（全文だと記録の写しになる）" \
    "$PY_BIN" "$WAI_CASE" first-reply-only
expect_output 0 "（題が付いていない）" \
    "what-am-i-doing: 題が無いセッションはそう言う" "$PY_BIN" "$WAI_CASE" no-title
expect_output 0 "開始 01-05" \
    "what-am-i-doing: 開始は記録の 1 件目から取る（ctime は追記のたび動く）" \
    "$PY_BIN" "$WAI_CASE" start-time
expect_output 0 "間の 21 往復は省いた" \
    "what-am-i-doing: 上限を超えたら黙って切らずに省いた数を書く" "$PY_BIN" "$WAI_CASE" elide
expect_output 0 "29 番目のお願いです" \
    "what-am-i-doing: --full なら省かない" "$PY_BIN" "$WAI_CASE" full
expect_output 1 "セッション記録が見つからない" \
    "what-am-i-doing: 記録が無ければ落ちる（黙って空を出さない）" "$PY_BIN" "$WAI_CASE" missing
expect_output 0 "→ 直して push しました" \
    "what-am-i-doing: stdio を cp1252 に強制しても日本語の報告が出る" \
    env PYTHONIOENCODING=cp1252 "$PY_BIN" "$WAI_CASE" pairs
expect_output 0 "PICK_OK" \
    "what-am-i-doing: 立場の対象は会話で一番呼ばれている番号から当てる（ブランチ頼みは別件を拾う）" \
    "$PY_BIN" "$WAI_CASE" pick-reference
expect_output 0 "DIRTY_OK" \
    "what-am-i-doing: 未コミットのパスを位置で切らない（strip で桁がずれる）" \
    "$PY_BIN" "$WAI_CASE" dirty-paths
expect_output 0 "TREE_OK" \
    "what-am-i-doing: 未コミットの変更を木で出す（周辺つき、新規は行頭 +、変更は ~）" \
    "$PY_BIN" "$WAI_CASE" dirty-tree
expect_output 0 "FRAMES_OK" \
    "what-am-i-doing: 未コミットの中身は今の姿に機械が帯を入れた枠（コードは関数まるごと・散文は文脈 3 行。前の行はコメント）。各枠の前に飛び先 path:行。改名は新規に化けない。未追跡は先頭と骨組み。--frame は 1 file を全部。git diff が失敗したら断る" \
    "$PY_BIN" "$WAI_CASE" frames
expect_output 0 "TOPIC_OK" \
    "what-am-i-doing: --topic はその語が出た往復だけを出す（/catchup が会話の話題を追う背骨）" \
    "$PY_BIN" "$WAI_CASE" topic
expect_output 0 "UNSEEN_OK" \
    "what-am-i-doing: 見ていないものを実際の状態に合わせる（省いた・外した往復は件数と見落としうるものを書く）" \
    "$PY_BIN" "$WAI_CASE" unseen-wording
expect_output 0 "STANCE_OK" \
    "what-am-i-doing: 立場の判定は /catchup と共用の純関数。送ったレビューも数え、「どちらでもない」とは言わない" \
    "$PY_BIN" "$WAI_CASE" stance
expect_output 1 "使い方" \
    "what-am-i-doing: 知らないケース名は落ちる（検査自体の空振りを防ぐ）" "$PY_BIN" "$WAI_CASE"

# ---- attention/whose-turn: open 全件から誰の番か ----
# GitHub には触らない。判定は純粋関数で、固定の材料が規則を 1 行ずつ固定する
WT="$ROOT/attention/scripts/whose-turn.py"
expect_output 0 "OK" "whose-turn: 判定規則の回帰（unittest 111 件。時刻はローカル、検査は UTC 固定）" \
    "$PY_BIN" "$ROOT/tests/whose-turn-suite.py"
expect_output 0 "見ていないもの" "whose-turn: --help に判定の定義と見ていないものが出る" \
    "$PY_BIN" "$WT" --help

# ---- attention/scripts/figure-check: 絵（系の前後の図）の幅・行数・縦線・箱の検査 ----
# gh にも git にも触らない。通る図は命令書の例（14 行）そのもの。合否は落ちる／通るだけでなく行と桁が出ることで見る
FC_CASE="$ROOT/tests/figure-check-case.py"
expect_output 0 "FIGURE_OK" "figure-check: 命令書の例（14 行）が通り、行数と最大桁が出る（file でも stdin でも同じ 1 行、exit 0）" \
    "$PY_BIN" "$FC_CASE" pass
expect_output 0 "FIGURE_OK" "figure-check: 60 桁を超える行は行番号と実際の幅で落ちる（東アジア幅は 2。縦線が揃っていれば幅の 1 件だけ）" \
    "$PY_BIN" "$FC_CASE" width
expect_output 0 "FIGURE_OK" "figure-check: 15 行目（空行でも）があれば行数で落ちる" \
    "$PY_BIN" "$FC_CASE" lines
expect_output 0 "FIGURE_OK" "figure-check: 縦線の列（2 行以上に立つ桁）以外の │ は行と桁で落ち、縦線の列が添う" \
    "$PY_BIN" "$FC_CASE" bar
expect_output 0 "FIGURE_OK" "figure-check: 縦線の列が 1 つも無ければ、その │ がずれとして出て列は「無い」" \
    "$PY_BIN" "$FC_CASE" bar-lone
expect_output 0 "FIGURE_OK" "figure-check: ┌┐ と └┘ の幅が違えば箱がずれ（行と桁と両辺の幅）。対の罫線が無い行もそう言う" \
    "$PY_BIN" "$FC_CASE" box
expect_output 0 "FIGURE_OK" "figure-check: 空の入力は「通った」と言わない" \
    "$PY_BIN" "$FC_CASE" empty
expect_exit 1 "figure-check: 知らないケース名は落ちる（検査自体の空振りを防ぐ）" "$PY_BIN" "$FC_CASE"

# ---- attention の命令書と README: 機械の出力語を同じ綴りで持つ（絵の例が規則を通るかは figure-check の pass が命令書から読む） ----
expect_output 0 "DOC_WORDS_OK" "命令書 2 本と README と仕様書が、機械の出力行の語（飛び先・取り込み先・上に積む・依頼先の候補・私の痕跡以降に変わった file）を同じ綴りで持つ（写す規則なので綴り違いは AI が探せない）" \
    "$PY_BIN" - "$ROOT" <<'PY'
import sys, pathlib
root = pathlib.Path(sys.argv[1])
docs = {n: (root / n).read_text(encoding="utf-8") for n in
        ["attention/commands/catchup.md", "attention/commands/what-am-i-doing.md", "attention/README.md",
         "attention/docs/catchup-spec.md"]}
others = docs.keys() - {"attention/commands/what-am-i-doing.md"}  # /what-am-i-doing は PR の材料を持たない
for word, files in [("飛び先", docs), ("figure-check.py", docs), ("（言語名 X）", docs), ("取り込み先", others), ("上に積む", others),
                    ("依頼先の候補", others), ("私の痕跡以降に変わった file", others)]:
    for f in files:
        assert word in docs[f], f"{f}: 「{word}」が無い"
print("DOC_WORDS_OK")
PY

expect_output 0 "DOC_NUMBERS_OK" "仕様書 7 節の上限の表が、機械の定数と同じ数値を持つ（数値の正本は仕様書。ずれたら片方が古い）" \
    "$PY_BIN" - "$ROOT" <<'PYNUM'
import sys, pathlib, importlib.util
root = pathlib.Path(sys.argv[1])
spec = (root / "attention/docs/catchup-spec.md").read_text(encoding="utf-8")
table = spec[spec.index("## 7."):spec.index("## 8.")]
sys.path.insert(0, str(root / "attention/scripts"))
def load(name, rel):
    s = importlib.util.spec_from_file_location(name, root / rel); m = importlib.util.module_from_spec(s); s.loader.exec_module(m); return m
cm = load("changemap", "attention/scripts/lib/changemap.py")
cu = load("catchup", "attention/scripts/catchup.py")
for label, value in [("本文", f"{cu.BODY_CAP} 行"), ("冒頭", f"{cu.ISSUE_HEAD_LINES} 行"), ("件数", f"{cu.ISSUE_CAP} 件"),
                     ("スレッド", f"{cu.THREAD_BODY_CAP} 行"), ("1 file", f"{cm.FRAME_FILE_CAP} 行"), ("合計", f"{cm.FRAME_TOTAL_CAP} 行"),
                     ("指摘の件数", f"{cu.THREAD_CAP} 件"), ("帯", f"{cm.FRAME_WIDTH} 桁"), ("畳む", f"{cm.FRAME_WHOLE} 行"),
                     ("残す", f"{cm.FOLD_KEEP} 行"), ("散文", f"前後 {cm.PROSE_CONTEXT} 行"), ("指摘の前後", f"前後 {cu.THREAD_CONTEXT} 行"),
                     ("まとめる間", f"{cm.FRAME_GAP} 行")]:
    assert value in table, f"仕様書 7 節に {label} の {value} が無い"
print("DOC_NUMBERS_OK")
PYNUM

# 文書が名指しする機械の定数の実在検査。手順書・README は「正本は `QUESTION_KINDS`」の形で
# 写しを持たない作りにしてあるが、**名指しした先が在るかを誰も見ていなかった**——改名すれば、
# 文書だけが消えた名前を指したまま残り、読む人はそこへ探しに行って何も見つけられない。
cat > "$WORK/doc-symbols.py" <<'PYSYM'
import pathlib, re, sys
root = pathlib.Path(sys.argv[1])
# **除外は明示の表で持つ**——表に無い名前を名指しした瞬間に赤くなるので、足し忘れは
# fail-closed 側に倒れる。接頭辞はホストの環境変数、名前は git の用語。
EXTERNAL_PREFIX = ("CLAUDE_CODE_",)
EXTERNAL_NAMES = {"HEAD", "SHA"}
# **名指しする側は文書だけではない。** 削除した定数を「正本」と呼ぶコメントが `tests/run.sh` に、
# 削除した柵を「今も効いている」と述べたコメントが `scripts/*.py` に残ったことがある。
# **定義を持つ側も `scripts/*.py` だけではない**——検査スイートの定数も shell の定数も名指しされる。
CODE = sorted((root / "scripts").glob("*.py")) + sorted((root / "scripts").glob("*.sh")) + [
    root / "tests/run.sh"]
# **この列挙は柵の覆いの上限である。** 名指しの置き場が増えた周に、ここを直し忘れると柵は
# 黙って外れる（実測: 対象外の 2 ファイルに実在しない名前を書いても全件緑だった）。広げ方は
# 設計の岐路として台帳に載せてあるので、ここに軸を足していく形にするな。
NAMED_IN = (root / "commands/review-loop.md", root / "docs/customize.md",
            root / "README.md", root / "REVIEW.md", root / "tests/run.sh",
            *sorted((root / "scripts").glob("*.py")))
# **アンダースコアを要求するな。** 要求していたとき、`MATERIALS` / `REVIEWS` / `LABELS` /
# `STATUS` を同じ体裁で名指ししている箇所が 1 つも検査されなかった。
TOKEN = r"`([A-Z][A-Z0-9_]{2,})`"
# **ファイル名つきの名指しは、そのファイルに在ることを要求する。** 定義を全ファイル横断の
# 平坦な集合で持っていたとき、`review-record.py` の `MATERIALS` を改名しても
# `firstread-record.py` の同名定数で満たされて全件緑だった（実測。同名の定義は 10 個ある）。
# `targets()` が今周採った「域を持ち回って組で照合する」と同じ形にする。
# **行単位でなく隣接で取る**——同じ行に別のファイル名が在るだけで組にすると誤検出になる
# （実測: `comment-ratio.sh` に触れた行の `EXPECTED_CHECKS` が「そのファイルに無い」と出た）。
PAIR = r"`([A-Za-z0-9_.-]+\.(?:py|sh))`\s*(?:の)?\s*`([A-Z][A-Z0-9_]{2,})`"

by_file = {}
for p in CODE:
    by_file[p.name] = set(re.findall(r"^([A-Z][A-Z0-9_]*)\s*=", p.read_text(encoding="utf-8"), re.M))
names = set().union(*by_file.values())

def wrong_pairs(pairs, label):
    """名指しされたファイルにその定数が無い組を返す。**自己検査のために関数にしてある**
    ——リポジトリには現に 1 件も無いので、外からは論理が効いているか測れない。"""
    return [f"{label}: {tok}（{fn} に無い）" for fn, tok in pairs
            if fn in by_file and tok not in by_file[fn]]

# 自己検査: 実在する「他所にだけ在る」組（`REQUIRED` は doctor / research にだけ在る）を
# 同じ関数に通し、必ず 1 件返ることを見る。平坦な集合なら通ってしまう組である。
# **測れない残りを明記する**——上の呼び出しを消す退行は、リポジトリに実際に落ちる組が
# 無い限りどんな腕でも捕まらない。捕まえられるのは抽出（下の件数の下限）と論理（ここ）。
PROBE = ("review-record.py", "REQUIRED")
assert PROBE[1] in names, "自己検査の前提が崩れた（この名前がどこにも定義されていない）"
assert wrong_pairs([PROBE], "self"), "自己検査: 組の照合が効いていない"

missing, used, paired = [], set(), 0
for f in NAMED_IN:
    body = f.read_text(encoding="utf-8")
    pairs = re.findall(PAIR, body)
    paired += len(pairs)
    missing += wrong_pairs(pairs, f.name)
    for tok in sorted(set(re.findall(TOKEN, body))):
        used.add(tok)
        if tok.startswith(EXTERNAL_PREFIX) or tok in EXTERNAL_NAMES or tok in names:
            continue
        missing.append(f"{f.name}: {tok}")
assert not missing, "名指しされた定数が在るべき場所に無い: " + ", ".join(missing)
# 組の下限。正規表現が壊れて 0 件になると、上の組の検査が黙って空振りする。
assert paired >= 4, f"ファイル名つきの名指しを {paired} 件しか拾えていない（4 件以上を期待）"

# **除外表の未使用項目を赤にする。** これは未使用項の剪定であって、**誤った抑制は検知しない**
# ——表に「今も名指しされていて、かつ定義が無い名前」を 1 つ足せば、真の破れをそのまま
# 恒久的に隠せる（実測）。隠す使い方を止める仕掛けではない、と読める形で書いておく。
stale = sorted(n for n in EXTERNAL_NAMES if n not in used or n in names)
# 接頭辞は面で黙らせるので、**定義が在る名前を覆っていないか**も見る。`"MATERIAL"` を足せば
# `MATERIALS` の破れをそのまま隠せた（実測。名前の表と同じ穴が接頭辞側に残っていた）。
stale += [p for p in EXTERNAL_PREFIX if not any(t.startswith(p) for t in used)]
stale += [f"{p}（定義の在る名前を覆っている）" for p in EXTERNAL_PREFIX
          if any(t.startswith(p) and t in names for t in used)]
assert not stale, "除外表に使われていない項目が在る: " + ", ".join(stale)
print("DOC_SYMBOLS_OK")
PYSYM
expect_output 0 "DOC_SYMBOLS_OK" "文書が名指しする機械の定数が実在する（改名で片方だけ動かない）" \
    "$PY_BIN" "$WORK/doc-symbols.py" "$ROOT"

# **`-ne` であること。** 以前は `-lt` で、下限を上げ忘れても下げ忘れても黙って通った（実測:
# 実数 501 に対して下限が 491 のまま走り、検査を 10 件消しても「491 件すべて緑」で exit 0）。
# 注記で「上げるときは実測値を書け」と書いてあっても、注記は赤くならない——③仕組みに置き換える。
if [ "$ran" -ne "$EXPECTED_CHECKS" ]; then
    echo "検査が $ran 件走った（$EXPECTED_CHECKS 件を期待）——検証の空振りか、件数の更新漏れ"
    exit 2
fi

echo
if [ "$fail" = 0 ]; then
    echo "$ran 件すべて緑"
else
    echo "$ran 件のうち失敗あり"
fi
exit "$fail"
