#!/usr/bin/env python3
"""doctor-loop の実行記録を検証し、最終報告の発行を妨げているものを列挙する。

**この道具は不合格しか宣言しない。** 「阻害なし」は品質・飽和の宣言ではなく、機械で
見つけられる欠落が無いという意味にすぎない。木の妥当性・一撃の筋・散文の質を見るのは
人と cold-reader。

守備範囲は「欠落の検出」——散文の報告で落ちるのは誤りでなく欠落（返答の突合・
抜き取りの結果・変更禁止の確認・再走査の手引き）で、欠落は読んでも見えない。
**飽和の偽装だけを塞ぎ、停止（軽量の打ち切り・上限・stuck・thrash）の正直な申告は
通す**——`convergence.outcome` を "stopped" にして理由を書けば、ゲートの未 pass や
未検証の節は「未飽和の申告」であって阻害ではない。

使い方:
    python3 doctor-record.py <実行記録.json>

終了コード:
    0  発行を妨げるものなし（品質・飽和の宣言ではない）
    1  発行を妨げるものあり（飽和を名乗りながら条件が揃っていない）
    2  記録が不正（欄の欠落・値の不正・読めない・引数が違う）——1 と取り違えるな

契約を担保するのは末尾の例外境界 1 つだけ。**個々の型検査は診断メッセージのために
在るのであって、契約の保証ではない——列挙を増やして塞いだつもりになるな**
（review-record.py が同じ穴で 4 経路漏らした記録を残している）。手書き検証の理由も
兄弟 2 本と同じ: 欄をまたぐ突合（親参照・重さと増し掛け・厚みとゲートの対応）は
単一スキーマに閉じず、`jsonschema` は「必須は git / python3 / bash だけ」と衝突する。
"""

import json
import sys

# Windows の既定コンソール（cp932 等）対策。兄弟と同じ理由。
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8")

# ここが正本で、手順書は列挙を持たない（二重管理を避ける）。
# 「未検証」は判定の不在（欄の初期値）——停止した実行でだけ記録に残ってよい。
NODE_VERDICTS = ("推奨", "条件付き", "棄却", "検証不能", "事実誤り", "既決着", "判定不一致", "未検証")
# 判定ごとに追加で要求する欄。成立条件のない条件付き・理由のない棄却・
# 確認手段のない検証不能・決着先のない既決着は、いずれも不完全な判定。
VERDICT_FIELDS = {
    "推奨": (),
    "条件付き": ("condition",),
    "棄却": ("reason",),
    "検証不能": ("needs",),
    "事実誤り": ("reason",),
    "既決着": ("settled_by",),
    "判定不一致": ("reason",),
    "未検証": (),
}
CONFIDENCES = ("確実", "有力", "仮説")
WEIGHTS = ("機械検証可能・小", "振る舞いに触れる・中", "ライブラリ級", "構成変更級")
ESCALATION_WEIGHTS = ("ライブラリ級", "構成変更級")  # 増し掛け（独立 3 票）の対象
THICKNESS = ("軽量", "標準", "重厚")
DECIDERS = ("依頼者指定", "既定")
GATE_VERDICTS = ("pass", "redesign-needed", "unverifiable")
OUTCOMES = ("saturated", "stopped")
FEASIBILITY = ("高", "中", "低")
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


def fail(msg):
    print(f"記録が不正: {msg}", file=sys.stderr)
    sys.exit(2)


def load(path):
    """記録を読む。**読めないことは記録の不正（2）で、発行阻害（1）ではない。**"""
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except OSError as e:
        fail(f"{path}: 開けない（{e.strerror}）")
    except json.JSONDecodeError as e:
        fail(f"{path}: JSON として読めない（{e}）")
    except UnicodeDecodeError as e:
        fail(f"{path}: UTF-8 として読めない（{e}）")


def require_str(rec, key, where):
    v = rec.get(key)
    if not isinstance(v, str) or not v.strip():
        fail(f"{where}: '{key}' が空か文字列でない")
    return v


def require_int(rec, key, where, minimum=0):
    v = rec.get(key)
    if not isinstance(v, int) or isinstance(v, bool) or v < minimum:
        fail(f"{where}: '{key}' が {minimum} 以上の整数でない")
    return v


def require_bool(rec, key, where):
    v = rec.get(key)
    if not isinstance(v, bool):
        fail(f"{where}: '{key}' が bool でない")
    return v


def not_applicable(v):
    """「該当なし」の共通形。理由なしの該当なしは認めない。"""
    return (
        isinstance(v, dict)
        and v.get("status") == "not_applicable"
        and isinstance(v.get("reason"), str)
        and v["reason"].strip()
    )


def validate(rec, path):
    # 型を見るのは診断メッセージを具体的にするため（保証は末尾の境界。冒頭 docstring 参照）。
    if not isinstance(rec, dict):
        fail(f"{path}: 記録の最上位が object でない")
    for key in REQUIRED:
        if key not in rec:
            fail(f"{path}: 必須の欄 '{key}' が無い")

    require_str(rec, "area", path)
    if rec["thickness"] not in THICKNESS:
        fail(f"{path}: 'thickness' が不正: {rec['thickness']!r}（{'/'.join(THICKNESS)}）")
    if rec["thickness_decider"] not in DECIDERS:
        fail(f"{path}: 'thickness_decider' が不正: {rec['thickness_decider']!r}")

    # 返答の突合。返答を欠いた scout の面積は「見ていない範囲」に載っていなければ
    # ならない——欠落を「見つからなかった」と読む誤りを等式で塞ぐ。
    if not isinstance(rec["scouts"], list) or not rec["scouts"]:
        fail(f"{path}: 'scouts' が空——走査なしの報告は診断ではない")
    if not isinstance(rec["unseen"], list) or not all(
        isinstance(s, str) and s.strip() for s in rec["unseen"]
    ):
        fail(f"{path}: 'unseen' が文字列の配列でない")
    for i, s in enumerate(rec["scouts"]):
        if not isinstance(s, dict):
            fail(f"{path}: scouts[{i}] が object でない")
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
        if not isinstance(n, dict):
            fail(f"{path}: nodes[{i}] が object でない")
        key = require_str(n, "key", f"{path}: nodes[{i}]")
        if key in keys:
            fail(f"{path}: 節のキー '{key}' が重複（安定キーは突合に使うため一意）")
        keys.add(key)
        require_int(n, "height", f"{path}: 節 '{key}'", 1)
        if n["height"] > 4:
            fail(f"{path}: 節 '{key}' の height が 4 を超えている（高さは固定 4 段）")
        verdict = n.get("verdict")
        if verdict not in NODE_VERDICTS:
            fail(f"{path}: 節 '{key}' の verdict が不正: {verdict!r}")
        for field in VERDICT_FIELDS[verdict]:
            require_str(n, field, f"{path}: 節 '{key}'（verdict={verdict}）")
        if n.get("confidence") not in CONFIDENCES:
            fail(f"{path}: 節 '{key}' の confidence が不正（{'/'.join(CONFIDENCES)}）")
        require_str(n, "evidence", f"{path}: 節 '{key}'")
        # 重さは scout が付ける欄。prospector 生成の親は null でよい（増し掛けの対象外）。
        w = n.get("weight")
        if w is not None and w not in WEIGHTS:
            fail(f"{path}: 節 '{key}' の weight が不正: {w!r}")
        if w in ESCALATION_WEIGHTS:
            escalation_targets += 1
        if verdict in ("推奨", "条件付き"):
            adoptable += 1
            # 採用一覧に載る節は検証計画と固定化案を欠かせない（「検証済み」は名乗れない）。
            require_str(n, "verification_plan", f"{path}: 節 '{key}'")
            require_str(n, "fixation", f"{path}: 節 '{key}'")
    for n in rec["nodes"]:
        parent = n.get("parent")
        if parent is not None and parent not in keys:
            fail(f"{path}: 節 '{n['key']}' の parent '{parent}' が nodes に無い")

    one = rec["oneshot"]
    if not_applicable(one):
        pass
    elif isinstance(one, dict):
        okey = require_str(one, "key", f"{path}: oneshot")
        if okey not in keys:
            fail(f"{path}: oneshot の節 '{okey}' が nodes に無い")
        target = next(n for n in rec["nodes"] if n["key"] == okey)
        if target["verdict"] not in ("推奨", "条件付き"):
            fail(f"{path}: 一撃に選べるのは推奨・条件付きの節だけ（'{okey}' は {target['verdict']}）")
        require_int(one, "descendants", f"{path}: oneshot")
        require_int(one, "descendants_with_unverifiable", f"{path}: oneshot")
        if one.get("feasibility") not in FEASIBILITY:
            fail(f"{path}: oneshot の feasibility が不正（{'/'.join(FEASIBILITY)}）")
        votes = one.get("votes")
        if not isinstance(votes, list) or len(votes) != 3 or not all(
            isinstance(v, str) and v.strip() for v in votes
        ):
            fail(f"{path}: oneshot の votes は 3 票の文字列——prospector が自分の統合を自分で確定するな")
    else:
        fail(f"{path}: 'oneshot' は選定の記録か「該当なし+理由」のどちらかの形")

    tri = rec["triage"]
    if not isinstance(tri, dict):
        fail(f"{path}: 'triage' が object でない")
    for k in ("discretion", "verification_decides", "human_only"):
        v = tri.get(k)
        if not isinstance(v, list) or not all(isinstance(s, str) and s.strip() for s in v):
            fail(f"{path}: triage.{k} が文字列の配列でない")
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
            if not isinstance(item, dict):
                fail(f"{path}: {name}[{i}] が object でない")
            for k in fields:
                require_str(item, k, f"{path}: {name}[{i}]")

    smp = rec["sampling"]
    if not_applicable(smp):
        pass
    elif isinstance(smp, dict) and smp.get("status") == "done":
        sampled = smp.get("sampled_keys")
        if not isinstance(sampled, list) or not sampled:
            fail(f"{path}: sampling.sampled_keys が空")
        unknown = [s for s in sampled if s not in keys]
        if unknown:
            fail(f"{path}: sampling.sampled_keys に無い節: {unknown}")
        require_int(smp, "overturned", f"{path}: sampling")
    else:
        fail(f"{path}: 'sampling' は status=done か「該当なし+理由」のどちらかの形")

    gates = rec["gates"]
    if not isinstance(gates, dict):
        fail(f"{path}: 'gates' が object でない")
    for g in ("cartographer_comparison", "cold_reader", "rederiver_comparison"):
        if g not in gates:
            fail(f"{path}: gates に '{g}' が無い")
        v = gates[g]
        if not_applicable(v):
            # 省略が許される段は「厚みの三段」の表が正本: cartographer の突合と
            # cold-reader は標準以上で必須、rederiver の突合は重厚のみ必須。
            if g in ("cartographer_comparison", "cold_reader") and rec["thickness"] != "軽量":
                fail(f"{path}: {rec['thickness']} 段でゲート '{g}' を省略している")
            if g == "rederiver_comparison" and rec["thickness"] == "重厚":
                fail(f"{path}: 重厚段で rederiver の突合を省略している")
            continue
        if not isinstance(v, dict):
            fail(f"{path}: gates.{g} が object でない")
        if g == "cold_reader":
            rounds = v.get("rounds")
            if not isinstance(rounds, list) or not rounds:
                fail(f"{path}: cold_reader の rounds が空")
            for i, r in enumerate(rounds):
                if not isinstance(r, dict) or r.get("verdict") not in GATE_VERDICTS:
                    fail(f"{path}: cold_reader rounds[{i}] の verdict が不正")
                require_int(r, "findings", f"{path}: cold_reader rounds[{i}]")
        else:
            if v.get("verdict") not in GATE_VERDICTS:
                fail(f"{path}: {g} の verdict が不正: {v.get('verdict')!r}")
            require_str(v, "reason", f"{path}: gates.{g}")

    conv = rec["convergence"]
    if not isinstance(conv, dict):
        fail(f"{path}: 'convergence' が object でない")
    require_int(conv, "rounds_total", f"{path}: convergence", 1)
    require_int(conv, "consecutive_zero", f"{path}: convergence")
    if conv.get("outcome") not in OUTCOMES:
        fail(f"{path}: convergence.outcome が不正（{'/'.join(OUTCOMES)}）")
    if conv["outcome"] == "stopped":
        require_str(conv, "stopped_reason", f"{path}: convergence（outcome=stopped）")

    # 変更禁止の機械確認は必須欄——確認せずに「変更していない」と書かせない。
    mc = rec["mod_check"]
    if not isinstance(mc, dict) or mc.get("status") not in ("clean", "restored", "unavailable"):
        fail(f"{path}: 'mod_check' の status は clean / restored / unavailable のいずれか")
    if mc["status"] != "clean":
        require_str(mc, "note", f"{path}: mod_check（status={mc['status']}）")

    proc = rec["process"]
    if not isinstance(proc, dict):
        fail(f"{path}: 'process' が object でない")
    require_int(proc, "rerolls", f"{path}: process")
    # 増し掛け（独立 3 票）の対象ゼロは「その旨と重さの根拠」の明示が要る——
    # 選定ゼロで素通りする降格の禁止（P2b）。
    if escalation_targets == 0:
        require_str(proc, "escalation_zero_reason", f"{path}: process（増し掛けの対象がゼロ）")
    elif proc.get("escalation_zero_reason"):
        fail(f"{path}: 増し掛けの対象があるのに escalation_zero_reason がある（申告の腐り）")

    # 再走査の手引き——候補は腐るが被覆の指定は腐らない。報告を捨てても掘り直せる形。
    rs = rec["rescan"]
    if not isinstance(rs, dict):
        fail(f"{path}: 'rescan' が object でない")
    require_str(rs, "coverage", f"{path}: rescan（面積×レンズ×層の指定）")
    if not isinstance(rs.get("instruments"), list) or not all(
        isinstance(s, str) and s.strip() for s in rs["instruments"]
    ):
        fail(f"{path}: rescan.instruments が文字列の配列でない")


def blockers(rec):
    """**飽和を名乗る記録だけを疑う。** outcome=stopped は未飽和の正直な申告
    （軽量の打ち切り・上限・stuck・thrash）であり、阻害でない。"""
    if rec["convergence"]["outcome"] == "stopped":
        return []

    out = []
    for n in rec["nodes"]:
        if n["verdict"] == "未検証":
            out.append(f"節 '{n['key']}' が未検証のまま——飽和は全節に判定が付いてから")

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
    if rec["thickness"] == "重厚" and not not_applicable(red) and red["verdict"] != "pass":
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
    # 終了コードの契約を担保するのはここ 1 箇所（理由は冒頭 docstring）。
    try:
        main()
    except SystemExit:
        raise
    except Exception as e:
        fail(f"想定外の例外（{type(e).__name__}）: {e}")
