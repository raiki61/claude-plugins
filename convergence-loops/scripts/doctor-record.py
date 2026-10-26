#!/usr/bin/env python3
"""doctor-loop の実行記録を検証し、最終報告の発行を妨げているものを列挙する。

**このツールは不合格しか宣言しない。** 「阻害なし」は品質・飽和の宣言ではなく、機械で
見つけられる欠落が無いという意味にすぎない。木の妥当性・一撃の筋・散文の質を見るのは
人と cold-reader。

守備範囲は「欠落の検出」——散文の報告で落ちるのは誤りでなく欠落（返答の突合・
抜き取りの結果・変更禁止の確認・再走査の手引き）で、欠落は読んでも見えない。
**飽和の偽装だけを塞ぎ、停止（軽量の打ち切り・上限・stuck・thrash）の正直な申告は
通す**——`convergence.outcome` を "stopped" にして理由を書けば、ゲートの未 pass や
未検証のノードは「未飽和の申告」であって阻害ではない。

使い方:
    python3 doctor-record.py <実行記録.json>

終了コード:
    0  発行を妨げるものなし（品質・飽和の宣言ではない）
    1  発行を妨げるものあり（飽和を名乗りながら条件が揃っていない）
    2  記録が不正（フィールドの欠落・値の不正・読めない・引数が違う）——1 と取り違えるな

契約を担保するのは末尾の例外境界 1 つだけ。**個々の型検査は診断メッセージのために
在るのであって、契約の保証ではない——列挙を増やして塞いだつもりになるな**
（review-record.py が同じ穴で 4 経路漏らした記録を残している）。手書き検証の理由も
兄弟 2 本と同じ: フィールドをまたぐ突合（親参照・重さと増し掛け・厚みとゲートの対応）は
単一スキーマに閉じず、`jsonschema` は「必須は git / python3 / bash だけ」と衝突する。
"""

import sys

# 検証器 4 本が共有する土台（隣の record_common）。**`sys.path[0]` に頼らない**——
# importlib でパスから読み込まれる場でも効くように、自分の在り処から明示で足す。
import pathlib  # noqa: E402
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))  # noqa: E402
from record_common import (  # noqa: E402
    DECIDERS, THICKNESS, check_convergence, check_gate, check_sampling, check_thickness, fail, is_str_list, load,
    not_applicable, require_bool, require_dict, require_int, require_str, require_str_list, run, utf8_output,
)

utf8_output()   # Windows の既定コンソール（cp932 等）対策。理由は record_common.utf8_output

# ここが正本で、手順書は列挙を持たない（二重管理を避ける）。
# 「未検証」は判定の不在（フィールドの初期値）——停止した実行でだけ記録に残ってよい。
NODE_VERDICTS = ("recommended", "conditional", "rejected", "unverifiable", "factually_wrong", "already_settled", "split_verdict", "unverified")
# 判定ごとに追加で要求するフィールド。成立条件のない条件付き・理由のない棄却・
# 確認手段のない検証不能・決着先のない既決着は、いずれも不完全な判定。
VERDICT_FIELDS = {
    "recommended": (),
    "conditional": ("condition",),
    "rejected": ("reason",),
    "unverifiable": ("needs",),
    "factually_wrong": ("reason",),
    "already_settled": ("settled_by",),
    "split_verdict": ("reason",),
    "unverified": (),
}
CONFIDENCES = ("certain", "likely", "hypothesis")
WEIGHTS = ("mechanical_small", "behavior_medium", "library", "architecture")
ESCALATION_WEIGHTS = ("library", "architecture")  # 増し掛け（独立 3 票）の対象
OUTCOMES = ("saturated", "stopped")
FEASIBILITY = ("high", "medium", "low")
# **値は ASCII のキーで持ち、比べる。** 日本語の語は人に見せる表示で、キーから引く（docs/standards/machine-readable-values.md の
# 決まり 3）。以前は値そのものが日本語の語（推奨・軽量など）で、文言を直すと記録と検証器の比較が黙って割れた
LABELS = {
    "recommended": "推奨", "conditional": "条件付き", "rejected": "棄却", "unverifiable": "検証不能",
    "factually_wrong": "事実誤り", "already_settled": "既決着", "split_verdict": "判定不一致", "unverified": "未検証",
    "certain": "確実", "likely": "有力", "hypothesis": "仮説",
    "mechanical_small": "機械検証可能・小", "behavior_medium": "振る舞いに触れる・中", "library": "ライブラリ級",
    "architecture": "構成変更級",
    "light": "軽量", "standard": "標準", "heavy": "重厚", "requester": "依頼者指定", "default": "既定",
    "high": "高", "medium": "中", "low": "低",
}
_missing = [k for k in (*NODE_VERDICTS, *CONFIDENCES, *WEIGHTS, *THICKNESS, *DECIDERS, *FEASIBILITY) if k not in LABELS]
if _missing:
    fail(f"表示の語の表 LABELS にキーが無い: {_missing}")


def choices(keys):
    """許す値の一覧を、キーと表示の語の組で（診断の文に出す）"""
    return "/".join(f"{k}（{LABELS[k]}）" if k in LABELS else k for k in keys)


REQUIRED = (
    "area",
    "thickness",
    "thickness_decider",
    "scouts",
    "unseen",
    "nodes",
    "oneshot",
    "triage",
    "ledger_candidates",
    "out_of_scope",
    "sampling",
    "gates",
    "convergence",
    "mod_check",
    "process",
    "rescan",
)


def validate(rec, path):
    # 型を見るのは診断メッセージを具体的にするため（保証は末尾の境界。冒頭 docstring 参照）。
    if not isinstance(rec, dict):
        fail(f"{path}: 記録の最上位が object でない")
    for key in REQUIRED:
        if key not in rec:
            fail(f"{path}: 必須のフィールド '{key}' が無い")

    require_str(rec, "area", path)
    check_thickness(rec, path, choices(THICKNESS))

    # 返答の突合。返答を欠いた scout の面積は「見ていない範囲」に載っていなければ
    # ならない——欠落を「見つからなかった」と読む誤りを等式で塞ぐ。
    if not isinstance(rec["scouts"], list) or not rec["scouts"]:
        fail(f"{path}: 'scouts' が空——走査なしの報告は診断ではない")
    require_str_list(rec["unseen"], f"{path}: 'unseen'")
    for i, s in enumerate(rec["scouts"]):
        require_dict(s, f"{path}: scouts[{i}]")
        require_str(s, "area", f"{path}: scouts[{i}]")
        require_str(s, "lens", f"{path}: scouts[{i}]")
        returned = require_bool(s, "candidates_returned", f"{path}: scouts[{i}]")
        diag = require_bool(s, "diagnosis_returned", f"{path}: scouts[{i}]")
        if not (returned and diag) and s["area"] not in rec["unseen"]:
            fail(
                f"{path}: scout（{s['area']}×{s['lens']}）の返答が欠けているのに"
                "「見ていない範囲」に載っていない——欠落を「見つからなかった」と読むな"
            )

    if not isinstance(rec["nodes"], list):
        fail(f"{path}: 'nodes' が配列でない")
    keys = set()
    escalation_targets = 0
    adoptable = 0
    for i, n in enumerate(rec["nodes"]):
        require_dict(n, f"{path}: nodes[{i}]")
        key = require_str(n, "key", f"{path}: nodes[{i}]")
        if key in keys:
            fail(f"{path}: ノードのキー '{key}' が重複（安定キーは突合に使うため一意）")
        keys.add(key)
        require_int(n, "height", f"{path}: ノード '{key}'", 1)
        if n["height"] > 4:
            fail(f"{path}: ノード '{key}' の height が 4 を超えている（高さは固定 4 段）")
        verdict = n.get("verdict")
        if verdict not in NODE_VERDICTS:
            fail(f"{path}: ノード '{key}' の verdict が不正: {verdict!r}")
        for field in VERDICT_FIELDS[verdict]:
            require_str(n, field, f"{path}: ノード '{key}'（verdict={verdict}）")
        if n.get("confidence") not in CONFIDENCES:
            fail(f"{path}: ノード '{key}' の confidence が不正（{choices(CONFIDENCES)}）")
        require_str(n, "evidence", f"{path}: ノード '{key}'")
        # 重さは scout が付けるフィールド。prospector 生成の親は null でよい（増し掛けの対象外）。
        w = n.get("weight")
        if w is not None and w not in WEIGHTS:
            fail(f"{path}: ノード '{key}' の weight が不正: {w!r}")
        if w in ESCALATION_WEIGHTS:
            escalation_targets += 1
        if verdict in ("recommended", "conditional"):
            adoptable += 1
            # 採用一覧に載るノードは検証計画と固定化案を欠かせない（「検証済み」は名乗れない）。
            require_str(n, "verification_plan", f"{path}: ノード '{key}'")
            require_str(n, "fixation", f"{path}: ノード '{key}'")
    for n in rec["nodes"]:
        parent = n.get("parent")
        if parent is not None and parent not in keys:
            fail(f"{path}: ノード '{n['key']}' の parent '{parent}' が nodes に無い")

    one = rec["oneshot"]
    if not_applicable(one):
        pass
    elif isinstance(one, dict):
        okey = require_str(one, "key", f"{path}: oneshot")
        if okey not in keys:
            fail(f"{path}: oneshot のノード '{okey}' が nodes に無い")
        target = next(n for n in rec["nodes"] if n["key"] == okey)
        if target["verdict"] not in ("recommended", "conditional"):
            fail(f"{path}: 一撃に選べるのは推奨・条件付きのノードだけ（'{okey}' は {target['verdict']}）")
        require_int(one, "descendants", f"{path}: oneshot")
        require_int(one, "descendants_with_unverifiable", f"{path}: oneshot")
        if one.get("feasibility") not in FEASIBILITY:
            fail(f"{path}: oneshot の feasibility が不正（{choices(FEASIBILITY)}）")
        votes = one.get("votes")
        if not is_str_list(votes) or len(votes) != 3:
            fail(f"{path}: oneshot の votes は 3 票の文字列——prospector が自分の統合を自分で確定するな")
    else:
        fail(f"{path}: 'oneshot' は選定の記録か「該当なし+理由」のどちらかの形")

    tri = require_dict(rec["triage"], f"{path}: 'triage'")
    for k in ("discretion", "verification_decides", "human_only"):
        require_str_list(tri.get(k), f"{path}: triage.{k}")
    if adoptable > 0 and not any(
        tri[k] for k in ("discretion", "verification_decides", "human_only")
    ):
        fail(f"{path}: 採用候補が {adoptable} 件あるのに消化の三分類が全部空")

    for name, fields in (
        ("ledger_candidates", ("claim", "reason", "revisit", "evidence")),
        ("out_of_scope", ("finding",)),
    ):
        if not isinstance(rec[name], list):
            fail(f"{path}: '{name}' が配列でない")
        for i, item in enumerate(rec[name]):
            require_dict(item, f"{path}: {name}[{i}]")
            for k in fields:
                require_str(item, k, f"{path}: {name}[{i}]")

    check_sampling(rec["sampling"], path, "sampled_keys", keys, "ノード")

    gates = require_dict(rec["gates"], f"{path}: 'gates'")
    for g in ("cartographer_comparison", "cold_reader", "rederiver_comparison"):
        if g not in gates:
            fail(f"{path}: gates に '{g}' が無い")
        v = gates[g]
        if not_applicable(v):
            # 省略が許される段は「厚みの三段」の表が正本: cartographer の突合と
            # cold-reader は標準以上で必須、rederiver の突合は重厚のみ必須。
            if g in ("cartographer_comparison", "cold_reader") and rec["thickness"] != "light":
                fail(f"{path}: {rec['thickness']} 段でゲート '{g}' を省略している")
            if g == "rederiver_comparison" and rec["thickness"] == "heavy":
                fail(f"{path}: 重厚段で rederiver の突合を省略している")
            continue
        check_gate(g, v, path)

    check_convergence(require_dict(rec["convergence"], f"{path}: 'convergence'"), path, OUTCOMES)

    # 変更禁止の機械確認は必須フィールド——確認せずに「変更していない」と書かせない。
    mc = rec["mod_check"]
    if not isinstance(mc, dict) or mc.get("status") not in ("clean", "restored", "unavailable"):
        fail(f"{path}: 'mod_check' の status は clean / restored / unavailable のいずれか")
    if mc["status"] != "clean":
        require_str(mc, "note", f"{path}: mod_check（status={mc['status']}）")

    proc = require_dict(rec["process"], f"{path}: 'process'")
    require_int(proc, "rerolls", f"{path}: process")
    # 増し掛け（独立 3 票）の対象ゼロは「その旨と重さの根拠」の明示が要る——
    # 選定ゼロで素通りする降格の禁止（P2b）。
    if escalation_targets == 0:
        require_str(proc, "escalation_zero_reason", f"{path}: process（増し掛けの対象がゼロ）")
    elif proc.get("escalation_zero_reason"):
        fail(f"{path}: 増し掛けの対象があるのに escalation_zero_reason がある（申告の腐り）")

    # 再走査の手引き——候補は腐るが被覆の指定は腐らない。報告を捨てても掘り直せる形。
    rs = require_dict(rec["rescan"], f"{path}: 'rescan'")
    require_str(rs, "coverage", f"{path}: rescan（面積×レンズ×層の指定）")
    require_str_list(rs.get("instruments"), f"{path}: rescan.instruments")


def blockers(rec):
    """**飽和を名乗る記録だけを疑う。** outcome=stopped は未飽和の正直な申告
    （軽量の打ち切り・上限・stuck・thrash）であり、阻害でない。"""
    if rec["convergence"]["outcome"] == "stopped":
        return []

    out = []
    for n in rec["nodes"]:
        if n["verdict"] == "unverified":
            out.append(f"ノード '{n['key']}' が未検証のまま——飽和は全ノードに判定が付いてから")

    smp = rec["sampling"]
    if not_applicable(smp):
        out.append("飽和を名乗るなら抜き取り検査が要る（該当なしでは飽和を宣言できない）")
    elif smp["overturned"] > 0:
        out.append(f"抜き取りで判定が {smp['overturned']} 件覆っている——飽和ではない")

    cart = rec["gates"]["cartographer_comparison"]
    if not_applicable(cart):
        out.append("cartographer の突合なしで飽和を名乗っている——これ無しで「掘り尽くした」を名乗るな")
    elif cart["verdict"] != "pass":
        out.append(f"cartographer の突合が pass していないのに飽和を名乗っている（{cart['verdict']}）")

    red = rec["gates"]["rederiver_comparison"]
    if rec["thickness"] == "heavy" and not not_applicable(red) and red["verdict"] != "pass":
        out.append(f"rederiver の突合が pass していないのに飽和を名乗っている（{red['verdict']}）")

    cr = rec["gates"]["cold_reader"]
    if not not_applicable(cr) and cr["rounds"][-1]["verdict"] != "pass":
        out.append("cold-reader が pass していないのに飽和を名乗っている")
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
            f"停止（未飽和）の申告つきで発行できる: {rec['convergence']['stopped_reason']}——"
            "諮りたかった内容は散文の冒頭に「要人間判断」として列挙しろ。"
        )
        return
    print(
        "機械で見つけられる発行の阻害は無い。**これは品質・飽和の宣言ではない**——"
        "木の妥当性・一撃の筋・記録に載らない懸念は人と cold-reader が見ろ。"
    )


if __name__ == "__main__":
    run(main)   # 終了コードの契約を担保する例外境界（理由は冒頭 docstring）
