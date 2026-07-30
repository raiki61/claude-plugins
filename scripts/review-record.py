#!/usr/bin/env python3
"""レビューループのラウンド記録を検証し、収束を妨げているものを列挙する。

**この道具は不合格しか宣言しない。** 「阻害なし」は収束の宣言ではなく、機械で
見つけられる阻害要因が無いという意味にすぎない。収束を宣言するのは人。

守備範囲は P1 素材の明示返答だけ。欄が空なら検証エラーで落ちる——約束を守ったかを、
守ると書くのでなく確かめられる形にするのが目的。R1〜R4 の verdict は対象外で、
そちらは今も人が見る。

使い方:
    python3 review-record.py <今ラウンドの記録.json> [<前ラウンドの記録.json>]

初回ラウンド（N=1）は前ラウンドの記録が存在しないので第 2 引数を省略しろ。省略すると
「前ラウンドの記録が無い」が阻害要因として 1 件返る（収束は連続 2 ラウンドの比較を
要するので、初回が阻害なしになることはない）。

終了コード:
    0  阻害要因なし（収束の宣言ではない）
    1  阻害要因あり
    2  記録が不正（欄の欠落・値の不正・読めない・引数が違う）——1 と取り違えるな

**1 は「記録は読めたが収束を妨げるものがある」だけに使う。** 読めなかった・引数が
違ったといった計測不成立を 1 に混ぜると、非収束と区別が付かず、記録を直せば済む
状態が「まだ直っていない」と読まれて収束を永久に宣言できない。Python の未処理例外は
exit 1 なので、**例外を素通しした時点でこの契約は破れる。**

**この契約を担保するのは末尾の例外境界 1 つだけ。** 個々の型検査は診断メッセージを
具体的にするために在るのであって、契約の保証ではない——起きうる不正値を列挙する方式は
列挙の完了が原理的に保証されず、実際に列挙を 5 本足した直後に同じファイル内で 2 箇所
（`status` / `key` が unhashable な場合）と `scalars`・深いネストの JSON が漏れた。
検査を足すときは境界に頼れ。**列挙を増やして塞いだつもりになるな。**

検証を JSON Schema で宣言せず手書きにしてあるのは 2 点の理由による。①検証の半分は
ラウンド間の突合（`base` 一致・`round` 連番・scalar の増分）で、**単一ドキュメントに
閉じないので Schema では原理的に表現できない**。②`jsonschema` の導入は pip を要し、
README が配布上の売り文句にしている「必須は git / python3 / bash だけ」「セットアップは
要らない」と正面から衝突する。入れても①は手書きのまま残るため、依存だけが増える。
`research-loop.md` が Schema の語彙を使うのは、あちらの検証をハーネスが持っているため。
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


def load(path):
    """記録を読む。**読めないことは記録の不正（2）で、非収束（1）ではない。**"""
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except OSError as e:
        fail(f"{path}: 開けない（{e.strerror}）")
    except json.JSONDecodeError as e:
        fail(f"{path}: JSON として読めない（{e}）")
    except UnicodeDecodeError as e:
        fail(f"{path}: UTF-8 として読めない（{e}）")


def validate(rec, path):
    # 型を見るのは診断メッセージを具体的にするため（保証は末尾の境界。冒頭 docstring 参照）。
    if not isinstance(rec, dict):
        fail(f"{path}: 記録の最上位が object でない")
    for key in ("base", "round", "materials", "units"):
        if key not in rec:
            fail(f"{path}: 必須の欄 '{key}' が無い")
    if not isinstance(rec["round"], int) or isinstance(rec["round"], bool):
        fail(f"{path}: 'round' が整数でない: {rec['round']!r}")
    # 連番検査（`rec["round"] != prev["round"] + 1`）は間隔しか見ないので、基点を
    # 押さえないと負値から始めて連番のまま永久に素通りできる。手順書は「1 から 1 ずつ」。
    if rec["round"] < 1:
        fail(f"{path}: 'round' が 1 以上でない: {rec['round']!r}")
    if not isinstance(rec["materials"], dict):
        fail(f"{path}: 'materials' が object でない")
    if not isinstance(rec["units"], list):
        fail(f"{path}: 'units' が配列でない")

    for name in MATERIALS:
        m = rec["materials"].get(name)
        if not isinstance(m, dict):
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
        if not isinstance(u, dict):
            fail(f"{path}: units[{i}] が object でない")
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
    if not 2 <= len(sys.argv) <= 3:
        print(__doc__, file=sys.stderr)
        fail(f"引数は 1 個か 2 個（受け取った数: {len(sys.argv) - 1}）")

    rec = load(sys.argv[1])
    # **突合より先に両方を検証する。** 逆順にすると、欄が欠けた記録で比較が KeyError を
    # 投げ、境界が 2 に倒すとはいえ「必須の欄が無い」より読みにくいメッセージになる。
    validate(rec, sys.argv[1])

    prev = None
    if len(sys.argv) > 2:
        prev = load(sys.argv[2])
        validate(prev, sys.argv[2])
        if prev["base"] != rec["base"]:
            fail("2 つの記録の base が違う（基準点を動かすな）")
        if rec["round"] != prev["round"] + 1:
            fail(f"ラウンドが連番でない: {prev['round']} の次が {rec['round']}")

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
    # **終了コードの契約を担保するのはここ 1 箇所。** 上の型検査を全部すり抜けた想定外の
    # 例外も 2（記録が不正）に倒す——素通しすると Python の既定で exit 1 になり
    # 「阻害要因あり」と区別が付かなくなる。型検査を増やして塞ぐのでなく、漏れる前提で
    # この境界に担保させる（冒頭 docstring の「列挙は完了しない」）。
    try:
        main()
    except SystemExit:
        raise
    except Exception as e:
        fail(f"想定外の例外（{type(e).__name__}）: {e}")
