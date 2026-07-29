#!/usr/bin/env python3
"""レビューループのラウンド記録を検証し、収束を妨げているものを列挙する。

**この道具は不合格しか宣言しない。** 「阻害なし」は収束の宣言ではなく、機械で
見つけられる阻害要因が無いという意味にすぎない。収束を宣言するのは人。

守備範囲は P1 素材の明示返答だけ。欄が空なら検証エラーで落ちる——約束を守ったかを、
守ると書くのでなく確かめられる形にするのが目的。R1〜R4 の verdict は対象外で、
そちらは今も人が見る。

使い方:
    python3 review-record.py <今ラウンドの記録.json> [<前ラウンドの記録.json>]

終了コード:
    0  阻害要因なし（収束の宣言ではない）
    1  阻害要因あり
    2  記録が不正（欄の欠落・値の不正）——1 と取り違えるな
"""

import json
import sys

# Windows の既定コンソールは cp932 等で、本文の記号（—）を encode できずに落ちる。
# 落ちると終了コードが 1 になり「阻害要因あり」と区別が付かないため、収束を永久に
# 宣言できなくなる。出力を UTF-8 に固定して塞ぐ。
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8")

# P1 が生産する素材。ここが正本で、手順書は列挙を持たない。
MATERIALS = (
    "local_review",  # 局所レビュー（公式 skill）
    "consistency",
    "bypass",  # 標準機構の迂回
    "hygiene",  # コード衛生（文脈遮断）
    "external_standards",  # 外部標準照合＋手元の依存
    "procedure_trace",  # 手順トレース
    "gate_efficacy",  # 新設ゲートの赤の確認
    "test_double_fidelity",  # 代役の忠実性
    "main_path_observation",  # 主経路の実行観測
    "provenance",  # 根拠の出所検査
)

# 素材の状態と、その状態で追加に要求する欄。
STATUS = {
    "found": ("count", "detail"),  # 見つかった
    "clean": ("checked",),  # 見たが無かった（何を見たかを要求する）
    "not_applicable": ("reason",),  # 条件に当たらない
    "awaiting_human": ("reason",),  # 人の起動待ちで止まっている
    "not_run": ("reason",),  # やるべきだったが飛ばした
}

# 収束を妨げる状態。**「やらなかった」を 3 値に割ってあるのが要点**——散文だと
# awaiting_human（手順どおりの停止）と not_run（逸脱）が同じ「未実施」に潰れ、
# さらに not_applicable にまで化ける。潰すと報告上で見分けられなくなる。
BLOCKING = ("awaiting_human", "not_run")

# nit / question / info は**意図的に**阻害要因にしない。ここを塞ぐと、受容して
# 再修正を止めるという連鎖の断ち方が使えなくなる。
LABELS = ("block", "suggest", "nit", "question", "info")


def fail(msg):
    print(f"記録が不正: {msg}", file=sys.stderr)
    sys.exit(2)


def validate(rec, path):
    for key in ("base", "round", "materials", "units"):
        if key not in rec:
            fail(f"{path}: 必須の欄 '{key}' が無い")

    for name in MATERIALS:
        m = rec["materials"].get(name)
        if m is None:
            fail(f"{path}: 素材 '{name}' の返答が無い（明示返答は全素材に要る）")
        status = m.get("status")
        if status not in STATUS:
            fail(
                f"{path}: 素材 '{name}' の status が不正: {status!r}（{'/'.join(STATUS)}）"
            )
        for field in STATUS[status]:
            if not m.get(field):
                fail(
                    f"{path}: 素材 '{name}' は status={status} なので '{field}' が要る"
                )

    for i, u in enumerate(rec["units"]):
        if not u.get("key"):
            fail(f"{path}: units[{i}] に key が無い（ラウンド間の突合に使う）")
        if u.get("label") not in LABELS:
            fail(f"{path}: units[{i}] の label が不正: {u.get('label')!r}")
        if u["label"] == "suggest":
            if u.get("disposition") not in ("do-now", "defer"):
                fail(f"{path}: units[{i}] は suggest なので disposition が要る")
            if u["disposition"] == "defer" and not u.get("reason"):
                fail(f"{path}: units[{i}] の defer に構造的理由が無い")


def blockers(rec, prev):
    out = []

    for name in MATERIALS:
        m = rec["materials"][name]
        if m["status"] in BLOCKING:
            label = "人の起動待ち" if m["status"] == "awaiting_human" else "未実施"
            out.append(f"素材 '{name}' が{label}: {m['reason']}")

    for u in rec["units"]:
        if u["label"] == "block":
            out.append(f"[block] 未解消: {u['key']}")
        elif u["label"] == "suggest" and u.get("disposition") == "do-now":
            out.append(f"[suggest] do-now 未対応: {u['key']}")

    if prev is None:
        out.append("前ラウンドの記録が無い（収束は連続 2 ラウンドの比較を要する）")
        return out

    prev_keys = {u["key"] for u in prev["units"] if u["label"] == "block"}
    for u in rec["units"]:
        if u["label"] == "block" and u["key"] not in prev_keys:
            out.append(f"新規 [block]: {u['key']}")

    return out


def scalar_changes(rec, prev):
    """前ラウンド比で増えた scalar。**相殺の有無は判定せず、R1 へ渡すだけ。**

    これを阻害要因に混ぜないこと——測れるものをゲートにすると、規則が測れるものへ
    寄る。増分の正当化を求める相手は人（R1）であって、この道具ではない。
    """
    if prev is None:
        return []
    out = []
    for name, now in (rec.get("scalars") or {}).items():
        before = (prev.get("scalars") or {}).get(name)
        if (
            isinstance(before, (int, float))
            and isinstance(now, (int, float))
            and now > before
        ):
            out.append(f"scalar '{name}': {before} → {now}")
    return out


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    with open(sys.argv[1], encoding="utf-8") as f:
        rec = json.load(f)
    prev = None
    if len(sys.argv) > 2:
        with open(sys.argv[2], encoding="utf-8") as f:
            prev = json.load(f)
        validate(prev, sys.argv[2])
        if prev["base"] != rec["base"]:
            fail("2 つの記録の base が違う（基準点を動かすな）")
        if rec["round"] != prev["round"] + 1:
            fail(f"ラウンドが連番でない: {prev['round']} の次が {rec['round']}")

    validate(rec, sys.argv[1])

    grew = scalar_changes(rec, prev)
    if grew:
        print("増えた scalar（阻害要因ではない。相殺する削除があるか R1 に見せろ）:")
        for line in grew:
            print(f"  - {line}")

    found = blockers(rec, prev)
    if found:
        print(f"収束を妨げるもの {len(found)} 件:")
        for b in found:
            print(f"  - {b}")
        sys.exit(1)
    print(
        "機械で見つけられる阻害要因は無い。**これは収束の宣言ではない**——"
        "R1〜R4 の verdict と、記録に載らない懸念の有無は人が見ろ。"
    )


if __name__ == "__main__":
    main()
