#!/usr/bin/env python3
"""research-loop の実行記録を検証し、最終報告の発行を妨げているものを列挙する。

**このツールは不合格しか宣言しない。** 「阻害なし」は品質・飽和の宣言ではなく、機械で
見つけられる欠落が無いという意味にすぎない。統合の妥当性・散文の質を見るのは人と
cold-reader。

守備範囲は「欠落の検出」だけ——散文の報告で落ちやすいのは誤りではなく欠落（必須フィールド・
数値の出所・語彙の定義）であり、欠落は読んでも見えない。フィールドを要求すれば欠落が
exit 2 になる。中身の質は保証しない（「該当なし」は書ける——だから該当なしには
理由を要求する）。

収束せずに停止した実行（rederiver の unverifiable・stuck・thrash・暴走ガード）も
発行できる——`convergence.outcome` を "stopped" にして理由を書けば、ゲートの未 pass や
覆りは「未収束の申告」であって阻害ではない（一度も走らなかった必須のゲートは status=not_run と
reason で書く。not_applicable は「この段では走らせない」に取っておく。フィールドを作る工程より前に止まった run は、
空のフィールドを process.stopped_gaps にフィールドごとの理由つきで申告する）。**阻害になるのは「収束した」と名乗り
ながらゲートが通っていない記録だけ**（収束の偽装を塞ぐのが目的で、停止の正直な報告を
塞ぐのは目的でない）。

使い方:
    python3 research-record.py <実行記録.json>

終了コード:
    0  発行を妨げるものなし（品質・飽和の宣言ではない）
    1  発行を妨げるものあり（収束を名乗りながらゲート未 pass・覆り・未反証の相違）
    2  記録が不正（フィールドの欠落・値の不正・読めない・引数が違う）——1 と取り違えるな

**1 は「記録は読めたが発行を妨げる状態がある」だけに使う。** 読めなかった・引数が
違ったといった計測不成立を 1 に混ぜると、記録を直せば済む状態が「まだ収束していない」と
読まれる。Python の未処理例外は exit 1 なので、**例外を素通しした時点でこの契約は破れる。**
契約を担保するのは末尾の例外境界 1 つだけ。**個々の型検査は診断メッセージを具体的に
するために在るのであって、契約の保証ではない——列挙を増やして塞いだつもりになるな**
（review-record.py が同じ穴で実際に 4 経路漏らした記録を残している）。

検証を JSON Schema で宣言せず手書きにしてある理由も review-record.py と同じ:
検証の一部はフィールドをまたぐ突合（クラスタ別の件数照合・荷重と反証の整合・厚みとゲートの
対応）で単一スキーマに閉じず、`jsonschema` の導入は「必須は git / python3 / bash だけ」と
衝突する。
"""

import collections
import sys

# 検証器 4 本が共有する土台（隣の record_common）。**`sys.path[0]` に頼らない**——
# importlib でパスから読み込まれる場でも効くように、自分の在り処から明示で足す。
import pathlib  # noqa: E402
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))  # noqa: E402
from record_common import (  # noqa: E402
    DECIDERS, GATE_VERDICTS, THICKNESS, _rows, _tables, check_convergence, check_gate, check_sampling, check_thickness, fail,
    is_str_list, load, not_applicable, require_dict, require_int, require_str, require_str_list, run, utf8_output,
)

utf8_output()   # Windows の既定コンソール（cp932 等）対策。理由は record_common.utf8_output

# ここが正本で、手順書は列挙を持たない（二重管理を避ける）。
VERDICTS = ("confirmed", "contradicted", "qualified", "unverifiable")
# **一次情報に到達できた判定**（検証不能は届かなかった側）。抜き取りの母数はここから取る
# ——「検証不能を除く」を読む側が手で並べていたので、判定語を足した周にその 1 語だけ母数から落ちた。
CHECKED_VERDICTS = tuple(v for v in VERDICTS if v != "unverifiable")
# 判定ごとに追加で要求するフィールド。適用条件のない確証・訂正のない相違/留保・
# 「何が確認できれば判定できるか」のない検証不能は、いずれも不完全な判定。
# **note は飾りではなく、役に貼る本文の正本**（PROMPT_TABLES が組み立てる）。判定語の意味が散文の
# コメントにしか無かったとき、貼る側（p1.checker.md ほか 5 本）が手で写していた——実測 2026-09-13:
# 6 本の prompt が検証器の名前表を 13 か所で並べ直していた。review 側で同じ形を閉じた直後に、
# research 側は手つかずで残っていた（**知見が片側にしか適用されない**）。
# **`fail` は `_rows` より前に置く。** `_rows` は import 時に `VERDICT_FIELDS = _rows(...)` で呼ばれるので、
# 属性の書き忘れで except に入った瞬間に `fail` が未束縛だと NameError → **未処理例外の exit 1** になる
# ——`_rows` の docstring が名乗る当の壊れ方そのもの（実測 2026-09-14: review 側は fail が先なので同じ注入で
# exit 2、research 側だけ exit 1 だった）。**写しは中身でなく順序で割れていた**ので、
# docstring の「この重複は構造上のもの（写しが狭くなる種類ではない）」という申し立ても外れていた。


Verdict = collections.namedtuple("Verdict", "fields note")
VERDICT_FIELDS = _rows("判定語", Verdict, {
    "confirmed": (("conditions",), "一次情報が主張どおり。conditions に適用条件・限界を必ず書く"
                          "（適用条件のない確証は不完全で、後段の適応で使えない）"),
    "contradicted": (("correction",), "一次情報と食い違う。correction に文書へ書くべき正しい記述"),
    "qualified": (("correction",), "概ね正しいが重要な限定・精密化が要る。correction に限定を書く"),
    "unverifiable": (("needs",), "一次情報に到達できない。needs に「何が確認できれば判定できるか」"),
})
# **収束ゲート（rederiver / cold-reader）を走らせる段。** 「軽量でない」を読む側が 2 語で並べていたので、
# 段を足した周にその 1 段だけゲートを課されないまま緑になる。厚みの三段の表がここの正本。
GATED_THICKNESS = tuple(t for t in THICKNESS if t != "light")
# 制約の出典の独立性（P0-1/P0-5）。surveyor 自書は rederiver の扱いが変わるため、
# 自由文字列でなく二値で申告させる。
ORIGINS = ("independent", "surveyor_written")
# **値は ASCII のキーで持ち、比べる。** 日本語の語は人と役に見せる表示で、キーから引く（docs/standards/machine-readable-values.md の
# 決まり 3）。以前は値そのものが日本語の語（確証・軽量など）で、文言を直すと記録とスキーマと rules の比較が黙って割れた
LABELS = {
    "confirmed": "確証", "contradicted": "相違", "qualified": "留保", "unverifiable": "検証不能",
    "light": "軽量", "standard": "標準", "heavy": "重厚",
    "requester": "依頼者指定", "default": "既定",
    "independent": "独立出典", "surveyor_written": "surveyor 自書",
}


def label(key):
    """キー（確証なら confirmed）を人に見せる語で。表に無いキーはキーのまま（読めない値を黙って別の語に化かさない）"""
    return f"{LABELS[key]}（{key}）" if key in LABELS else key


OUTCOMES = ("converged", "stopped")

# **プロンプトに貼る語彙は、ここが組み立てて engine が渡す。** 役に渡す散文へ表を手で写すと、正本を
# 直した周に写しだけが古くなり、しかも役は写しの方を読む（実測 2026-09-13: research の prompt 6 本が
# 検証器の名前表を 13 か所で並べ直していた——review 側で同じ形を閉じた直後に、こちらは手つかずだった）。
# **engine はこの dict の中身を知らない**——名前で引いて貼るだけなので、ループの語彙は engine に入らない。
_missing = [k for k in (*VERDICTS, *THICKNESS, *DECIDERS, *ORIGINS) if k not in LABELS]
if _missing:
    fail(f"表示の語の表 LABELS にキーが無い: {_missing}")
PROMPT_TABLES = _tables("プロンプトの表", lambda: {
        # **必須フィールドは全部並べる。** 先頭 1 つだけを貼っていたので、判定語に 2 つ目の必須フィールドを足しても
    # 役に渡る本文には現れなかった（review 側は同じ表を全要素で並べており、写しどうしが割れていた）
    "verdicts": "／".join(f"{k}（{LABELS[k]}。" + "・".join(f"{f} が要る" for f in v.fields) + f"）: {v.note}"
                         for k, v in VERDICT_FIELDS.items()),
        "checked_verdicts": "／".join(map(label, CHECKED_VERDICTS)),
        "gate_verdicts": "／".join(GATE_VERDICTS),
        "origins": "／".join(map(label, ORIGINS)),
        "thickness": "／".join(map(label, THICKNESS)),
})
# 記録の必須フィールド。terms（語彙定義）・numbers（数値と出所の組）が空配列でもフィールド自体は要る——
# 「定義すべき語・出所を書くべき数値は無かった」の明示と、フィールドごと忘れた欠落を区別するため。
REQUIRED = (
    "question",
    "thickness",
    "thickness_decider",
    "constraints",
    "clusters",
    "claims",
    "corrections",
    "terms",
    "numbers",
    "gates",
    "sampling",
    "convergence",
    "process",
    "decisions",
)


# 止まった記録でだけ、空のまま受けるフィールド（process.stopped_gaps にフィールドごとの理由を書く）。作る工程より前に止まった run の
# 報告を出すため——収束を名乗る記録では今までどおり空を落とす（not_run のゲートを止まった記録でだけ受けるのと同じ形）
GAP_FIELDS = ("question", "constraints", "clusters", "claims", "decisions")


def stopped_gaps(rec, path):
    """止まった記録が理由つきで空と申告したフィールドの集合。申告の形が崩れている・止まっていない記録の申告・空でないフィールドの申告は落とす"""
    gaps = (rec.get("process") or {}).get("stopped_gaps") if isinstance(rec.get("process"), dict) else None
    if gaps is None:
        return set()
    if not isinstance(gaps, dict) or not all(k in GAP_FIELDS and isinstance(v, str) and v.strip() for k, v in gaps.items()):
        fail(f"{path}: process.stopped_gaps は {{{'/'.join(GAP_FIELDS)}: 理由}} の形")
    if not isinstance(rec.get("convergence"), dict) or rec["convergence"].get("outcome") != "stopped":
        fail(f"{path}: 収束を名乗りながら空のフィールドを申告している（stopped_gaps は outcome=stopped の記録でだけ受ける）")
    dec = rec.get("decisions")
    filled = {"question": bool(rec.get("question")), "decisions": isinstance(dec, dict) and any(dec.get(k) for k in ("decide_now", "poc", "human_only")),
              **{k: bool(rec.get(k)) for k in ("constraints", "clusters", "claims")}}
    rotten = [k for k in gaps if filled[k]]
    if rotten:
        fail(f"{path}: 空でないフィールドを空と申告している（申告の腐り）: {rotten}")
    return set(gaps)


def validate(rec, path):
    # 型を見るのは診断メッセージを具体的にするため（保証は末尾の境界。冒頭 docstring 参照）。
    if not isinstance(rec, dict):
        fail(f"{path}: 記録の最上位が object でない")
    for key in REQUIRED:
        if key not in rec:
            fail(f"{path}: 必須のフィールド '{key}' が無い")
    # 結末を先に見る——未決の記録（走っている run を途中で仕上げた）は他のフィールドも作りかけなので、後ろの検査で落ちると
    # 『記録が壊れている』に見える。止まった記録でだけ受ける規則（stopped_gaps・not_run）もこの値を読む
    conv = require_dict(rec["convergence"], f"{path}: 'convergence'")
    if conv.get("outcome") is None:
        fail(f"{path}: convergence.outcome が未決（run が終わっていない——止めるか収束してから仕上げよ）")
    if conv.get("outcome") not in OUTCOMES:
        fail(f"{path}: convergence.outcome が不正（{'/'.join(OUTCOMES)}）")
    gaps = stopped_gaps(rec, path)

    if not ("question" in gaps and rec["question"] == ""):
        require_str(rec, "question", path)
    check_thickness(rec, path, "/".join(THICKNESS))

    if not isinstance(rec["constraints"], list) or not (rec["constraints"] or "constraints" in gaps):
        fail(f"{path}: 'constraints' が空——制約なしの調査は P0-1 に反する")
    for i, c in enumerate(rec["constraints"]):
        require_dict(c, f"{path}: constraints[{i}]")
        for k in ("text", "source", "breaks_if_false"):
            require_str(c, k, f"{path}: constraints[{i}]")
        if c.get("origin") not in ORIGINS:
            fail(f"{path}: constraints[{i}] の origin が不正（{'/'.join(ORIGINS)}）")

    if not isinstance(rec["clusters"], list) or not (rec["clusters"] or "clusters" in gaps):
        fail(f"{path}: 'clusters' が空")
    cluster_expect = {}
    for i, c in enumerate(rec["clusters"]):
        require_dict(c, f"{path}: clusters[{i}]")
        key = require_str(c, "key", f"{path}: clusters[{i}]")
        if key in cluster_expect:
            fail(f"{path}: クラスタ '{key}' が重複")
        cluster_expect[key] = require_int(c, "claims_submitted", f"{path}: クラスタ '{key}'", 1)

    if not isinstance(rec["claims"], list) or not (rec["claims"] or "claims" in gaps):
        fail(f"{path}: 'claims' が空")
    ids = set()
    load_bearing_count = 0
    cluster_seen = {k: 0 for k in cluster_expect}
    for i, cl in enumerate(rec["claims"]):
        require_dict(cl, f"{path}: claims[{i}]")
        cid = require_str(cl, "id", f"{path}: claims[{i}]")
        if cid in ids:
            fail(f"{path}: 主張 id '{cid}' が重複（ラウンド間の突合に使うため一意）")
        ids.add(cid)
        require_str(cl, "claim", f"{path}: 主張 '{cid}'")
        ckey = require_str(cl, "cluster", f"{path}: 主張 '{cid}'")
        if ckey not in cluster_expect:
            fail(f"{path}: 主張 '{cid}' のクラスタ '{ckey}' が clusters に無い")
        cluster_seen[ckey] += 1
        verdict = cl.get("verdict")
        if verdict not in VERDICTS:
            fail(f"{path}: 主張 '{cid}' の verdict が不正: {verdict!r}（{'/'.join(VERDICTS)}）")
        for field in VERDICT_FIELDS[verdict].fields:
            require_str(cl, field, f"{path}: 主張 '{cid}'（verdict={verdict}）")
        for flag in ("load_bearing", "refuted"):
            if not isinstance(cl.get(flag), bool):
                fail(f"{path}: 主張 '{cid}' の '{flag}' が bool でない")
        if cl["load_bearing"]:
            load_bearing_count += 1
        sources = cl.get("sources")
        if verdict != "unverifiable":
            if not is_str_list(sources) or not sources:
                fail(f"{path}: 主張 '{cid}' の sources が空——出典なしの判定は認めない")

    # 件数の照合。散文の「突合しろ」を機械の等式に置き換えたフィールド——ここが赤なら
    # 判定の欠落（無言の省略）が起きている。
    for key, expect in cluster_expect.items():
        if cluster_seen[key] != expect:
            fail(
                f"{path}: クラスタ '{key}' は claims_submitted={expect} だが"
                f"判定は {cluster_seen[key]} 件——判定の欠落を「なし」と読むな"
            )

    # 訂正の記録は append-only の台帳（P2-3）で、2 ループ目以降は 1 から始まらない。
    # 先頭の番号は任意（1 以上）、以降は連番——増分は先頭と末尾の no で表現できる。
    if not isinstance(rec["corrections"], list):
        fail(f"{path}: 'corrections' が配列でない")
    start = None
    for i, c in enumerate(rec["corrections"]):
        require_dict(c, f"{path}: corrections[{i}]")
        no = require_int(c, "no", f"{path}: corrections[{i}]", 1)
        if start is None:
            start = no
        elif no != start + i:
            fail(f"{path}: 訂正の番号が連番でない（{i}番目が no={no}、先頭は no={start}）")
        require_str(c, "text", f"{path}: corrections[{i}]")

    for name, fields in (("terms", ("term", "definition")), ("numbers", ("value", "source"))):
        if not isinstance(rec[name], list):
            fail(f"{path}: '{name}' が配列でない")
        for i, item in enumerate(rec[name]):
            require_dict(item, f"{path}: {name}[{i}]")
            for k in fields:
                require_str(item, k, f"{path}: {name}[{i}]")

    check_convergence(conv, path, OUTCOMES)   # 結末は上で先に見てある（ここでの結末の検査は必ず通る）

    gates = require_dict(rec["gates"], f"{path}: 'gates'")
    for g in ("rederiver", "cold_reader", "cartographer"):
        if g not in gates:
            fail(f"{path}: gates に '{g}' が無い")
        v = gates[g]
        # ゲートの省略が許される段は「厚みの三段」の表が正本:
        # rederiver / cold-reader は標準以上で必須、cartographer は重厚のみ必須。
        required = rec["thickness"] == "heavy" if g == "cartographer" else rec["thickness"] in GATED_THICKNESS
        if not_applicable(v):
            if required:
                what = ("重厚段で cartographer を省略している——これ無しで盲点ゼロを名乗るな" if g == "cartographer"
                        else f"{rec['thickness']} 段でゲート '{g}' を省略している")
                fail(f"{path}: {what}（止まった run で走らなかったなら status=not_run と reason）")
            continue
        # **飛ばした（not_run）は「この段では走らせない」（not_applicable）と別の値。** 止まった run の必須の
        # ゲートにだけ許す——収束を名乗る記録で受けると、走らなかったゲートが緑と区別できなくなる
        if isinstance(v, dict) and v.get("status") == "not_run":
            require_str(v, "reason", f"{path}: gates.{g}（not_run）")
            if conv["outcome"] != "stopped":
                fail(f"{path}: 収束を名乗りながらゲート '{g}' を飛ばしている（not_run は outcome=stopped の記録でだけ受ける）")
            if not required:
                fail(f"{path}: {rec['thickness']} 段で走らせないゲート '{g}' を飛ばしたと名乗っている（not_applicable と reason で書け）")
            continue
        check_gate(g, v, path)
        if g == "cartographer":
            require_int(v, "new_blind_spots", f"{path}: gates.cartographer")

    check_sampling(rec["sampling"], path, "sampled_ids", ids, "主張 id")

    proc = require_dict(rec["process"], f"{path}: 'process'")
    require_int(proc, "rerolls", f"{path}: process")
    declared = proc.get("unrefuted_load_bearing")
    if not isinstance(declared, list):
        fail(f"{path}: process.unrefuted_load_bearing が配列でない")
    unknown = [s for s in declared if s not in ids]
    if unknown:
        fail(f"{path}: process.unrefuted_load_bearing に無い主張 id: {unknown}")
    if declared and not (isinstance(proc.get("reason"), str) and proc["reason"].strip()):
        fail(f"{path}: 反証を経ていない荷重があるのに process.reason が無い")
    # 荷重と反証の整合。「荷重なのに反証していない」は起こりうる——起きたこと自体は
    # 正さず、無申告だけを塞ぐ（存在の可視化がこのツールの役割）。
    for cl in rec["claims"]:
        if cl["load_bearing"] and not cl["refuted"] and cl["id"] not in declared:
            fail(
                f"{path}: 荷重の主張 '{cl['id']}' が反証を経ておらず、"
                "process.unrefuted_load_bearing に申告も無い"
            )
    for cid in declared:
        cl = next(c for c in rec["claims"] if c["id"] == cid)
        if not cl["load_bearing"] or cl["refuted"]:
            fail(f"{path}: '{cid}' は未反証の荷重でないのに申告されている（申告の腐り）")
    # 荷重の選定ゼロは「その旨と理由」の明示が要る（P1——選定ゼロで素通りする降格の禁止）。
    if load_bearing_count == 0:
        if rec["claims"] or "claims" not in gaps:   # 主張ごと無い止まった記録は選定もしていない
            require_str(proc, "load_zero_reason", f"{path}: process（荷重の選定がゼロ）")
    elif proc.get("load_zero_reason"):
        fail(f"{path}: 荷重があるのに load_zero_reason がある（申告の腐り）")

    dec = require_dict(rec["decisions"], f"{path}: 'decisions'")
    for k in ("decide_now", "poc", "human_only"):
        require_str_list(dec.get(k), f"{path}: decisions.{k}")
    if not any(dec[k] for k in ("decide_now", "poc", "human_only")) and "decisions" not in gaps:
        fail(f"{path}: decisions が全部空——3 分類に仕分けろ（P5）")


def blockers(rec):
    """**収束を名乗る記録だけを疑う。** outcome=stopped は未収束の正直な申告であり、
    ゲートの未 pass・覆りは阻害でない（停止の理由が記録にある）。"""
    if rec["convergence"]["outcome"] == "stopped":
        return []

    out = []
    for cl in rec["claims"]:
        # 相違は敵対検証を経て初めて確定（P1 の規律）。未反証の相違を載せた収束は発行できない。
        if cl["verdict"] == "contradicted" and not cl["refuted"]:
            out.append(f"相違 '{cl['id']}' が反証を経ていない（相違は敵対検証を経て確定）")

    smp = rec["sampling"]
    if isinstance(smp, dict) and smp.get("status") == "done" and smp["overturned"] > 0:
        out.append(
            f"抜き取りで判定が {smp['overturned']} 件覆っている——飽和ではない。通常ラウンドへ戻れ"
        )

    for g in ("rederiver", "cartographer"):
        v = rec["gates"][g]
        if not not_applicable(v) and v["verdict"] != "pass":
            out.append(f"{g} が pass していないのに収束を名乗っている（{v['verdict']}）")

    cart = rec["gates"]["cartographer"]
    if not not_applicable(cart) and cart["new_blind_spots"] > 0:
        out.append(
            f"cartographer の新規盲点が {cart['new_blind_spots']} 件残っている——盲点ゼロが収束条件"
        )

    cr = rec["gates"]["cold_reader"]
    if not not_applicable(cr) and cr["rounds"][-1]["verdict"] != "pass":
        out.append("cold-reader が pass していないのに収束を名乗っている")
    return out


def main():
    if len(sys.argv) != 2:
        print(__doc__, file=sys.stderr)
        fail(f"引数は 1 個（受け取った数: {len(sys.argv) - 1}）")

    rec = load(sys.argv[1])
    validate(rec, sys.argv[1])

    found = blockers(rec)
    if found:
        print(f"発行を妨げるもの {len(found)} 件:")
        for b in found:
            print(f"  - {b}")
        sys.exit(1)
    if rec["convergence"]["outcome"] == "stopped":
        print(
            f"停止（未収束）の申告つきで発行できる: {rec['convergence']['stopped_reason']}——"
            "諮りたかった内容は散文の冒頭に「要人間判断」として列挙しろ。"
        )
        return
    print(
        "機械で見つけられる発行の阻害は無い。**これは品質・飽和の宣言ではない**——"
        "統合の妥当性・散文の質・記録に載らない懸念は人と cold-reader が見ろ。"
    )


if __name__ == "__main__":
    run(main)   # 終了コードの契約を担保する例外境界（理由は冒頭 docstring）
