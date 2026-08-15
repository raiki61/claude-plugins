#!/usr/bin/env python3
"""research-loop の実行記録を検証し、最終報告の発行を妨げているものを列挙する。

**この道具は不合格しか宣言しない。** 「阻害なし」は品質・飽和の宣言ではなく、機械で
見つけられる欠落が無いという意味にすぎない。統合の妥当性・散文の質を見るのは人と
cold-reader。

守備範囲は「欠落の検出」だけ——散文の報告で落ちやすいのは誤りではなく欠落（必須欄・
数値の出所・語彙の定義）であり、欠落は読んでも見えない。欄を要求すれば欠落が
exit 2 になる。中身の質は保証しない（「該当なし」は書ける——だから該当なしには
理由を要求する）。

収束せずに停止した実行（rederiver の unverifiable・stuck・thrash・暴走ガード）も
発行できる——`convergence.outcome` を "stopped" にして理由を書けば、ゲートの未 pass や
覆りは「未収束の申告」であって阻害ではない。**阻害になるのは「収束した」と名乗り
ながらゲートが通っていない記録だけ**（収束の偽装を塞ぐのが目的で、停止の正直な報告を
塞ぐのは目的でない）。

使い方:
    python3 research-record.py <実行記録.json>

終了コード:
    0  発行を妨げるものなし（品質・飽和の宣言ではない）
    1  発行を妨げるものあり（収束を名乗りながらゲート未 pass・覆り・未反証の相違）
    2  記録が不正（欄の欠落・値の不正・読めない・引数が違う）——1 と取り違えるな

**1 は「記録は読めたが発行を妨げる状態がある」だけに使う。** 読めなかった・引数が
違ったといった計測不成立を 1 に混ぜると、記録を直せば済む状態が「まだ収束していない」と
読まれる。Python の未処理例外は exit 1 なので、**例外を素通しした時点でこの契約は破れる。**
契約を担保するのは末尾の例外境界 1 つだけ。**個々の型検査は診断メッセージを具体的に
するために在るのであって、契約の保証ではない——列挙を増やして塞いだつもりになるな**
（review-record.py が同じ穴で実際に 4 経路漏らした記録を残している）。

検証を JSON Schema で宣言せず手書きにしてある理由も review-record.py と同じ:
検証の一部は欄をまたぐ突合（クラスタ別の件数照合・荷重と反証の整合・厚みとゲートの
対応）で単一スキーマに閉じず、`jsonschema` の導入は「必須は git / python3 / bash だけ」と
衝突する。
"""

import json
import sys

# Windows の既定コンソール（cp932 等）対策。review-record.py と同じ理由。
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8")

# ここが正本で、手順書は列挙を持たない（二重管理を避ける）。
VERDICTS = ("確証", "相違", "留保", "検証不能")
# 判定ごとに追加で要求する欄。適用条件のない確証・訂正のない相違/留保・
# 「何が確認できれば判定できるか」のない検証不能は、いずれも不完全な判定。
VERDICT_FIELDS = {
    "確証": ("conditions",),
    "相違": ("correction",),
    "留保": ("correction",),
    "検証不能": ("needs",),
}
THICKNESS = ("軽量", "標準", "重厚")
DECIDERS = ("依頼者指定", "既定")
# 制約の出典の独立性（P0-1/P0-5）。surveyor 自書は rederiver の扱いが変わるため、
# 自由文字列でなく二値で申告させる。
ORIGINS = ("独立出典", "surveyor自書")
GATE_VERDICTS = ("pass", "redesign-needed", "unverifiable")
OUTCOMES = ("converged", "stopped")
# 記録の必須欄。terms（語彙定義）・numbers（数値と出所の組）が空配列でも欄自体は要る——
# 「定義すべき語・出所を書くべき数値は無かった」の明示と、欄ごと忘れた欠落を区別するため。
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

    require_str(rec, "question", path)
    if rec["thickness"] not in THICKNESS:
        fail(f"{path}: 'thickness' が不正: {rec['thickness']!r}（{'/'.join(THICKNESS)}）")
    if rec["thickness_decider"] not in DECIDERS:
        fail(f"{path}: 'thickness_decider' が不正: {rec['thickness_decider']!r}")

    if not isinstance(rec["constraints"], list) or not rec["constraints"]:
        fail(f"{path}: 'constraints' が空——制約なしの調査は P0-1 に反する")
    for i, c in enumerate(rec["constraints"]):
        if not isinstance(c, dict):
            fail(f"{path}: constraints[{i}] が object でない")
        for k in ("text", "source", "breaks_if_false"):
            require_str(c, k, f"{path}: constraints[{i}]")
        if c.get("origin") not in ORIGINS:
            fail(f"{path}: constraints[{i}] の origin が不正（{'/'.join(ORIGINS)}）")

    if not isinstance(rec["clusters"], list) or not rec["clusters"]:
        fail(f"{path}: 'clusters' が空")
    cluster_expect = {}
    for i, c in enumerate(rec["clusters"]):
        if not isinstance(c, dict):
            fail(f"{path}: clusters[{i}] が object でない")
        key = require_str(c, "key", f"{path}: clusters[{i}]")
        if key in cluster_expect:
            fail(f"{path}: クラスタ '{key}' が重複")
        cluster_expect[key] = require_int(c, "claims_submitted", f"{path}: クラスタ '{key}'", 1)

    if not isinstance(rec["claims"], list) or not rec["claims"]:
        fail(f"{path}: 'claims' が空")
    ids = set()
    load_bearing_count = 0
    cluster_seen = {k: 0 for k in cluster_expect}
    for i, cl in enumerate(rec["claims"]):
        if not isinstance(cl, dict):
            fail(f"{path}: claims[{i}] が object でない")
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
        for field in VERDICT_FIELDS[verdict]:
            require_str(cl, field, f"{path}: 主張 '{cid}'（verdict={verdict}）")
        for flag in ("load_bearing", "refuted"):
            if not isinstance(cl.get(flag), bool):
                fail(f"{path}: 主張 '{cid}' の '{flag}' が bool でない")
        if cl["load_bearing"]:
            load_bearing_count += 1
        sources = cl.get("sources")
        if verdict != "検証不能":
            if not isinstance(sources, list) or not sources or not all(
                isinstance(s, str) and s.strip() for s in sources
            ):
                fail(f"{path}: 主張 '{cid}' の sources が空——出典なしの判定は認めない")

    # 件数の照合。散文の「突合しろ」を機械の等式に置き換えた欄——ここが赤なら
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
        if not isinstance(c, dict):
            fail(f"{path}: corrections[{i}] が object でない")
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
            if not isinstance(item, dict):
                fail(f"{path}: {name}[{i}] が object でない")
            for k in fields:
                require_str(item, k, f"{path}: {name}[{i}]")

    gates = rec["gates"]
    if not isinstance(gates, dict):
        fail(f"{path}: 'gates' が object でない")
    for g in ("rederiver", "cold_reader", "cartographer"):
        if g not in gates:
            fail(f"{path}: gates に '{g}' が無い")
        v = gates[g]
        if not_applicable(v):
            # ゲートの省略が許される段は「厚みの三段」の表が正本:
            # rederiver / cold-reader は標準以上で必須、cartographer は重厚のみ必須。
            if g in ("rederiver", "cold_reader") and rec["thickness"] != "軽量":
                fail(f"{path}: {rec['thickness']} 段でゲート '{g}' を省略している")
            if g == "cartographer" and rec["thickness"] == "重厚":
                fail(f"{path}: 重厚段で cartographer を省略している——これ無しで盲点ゼロを名乗るな")
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
            if g == "cartographer":
                require_int(v, "new_blind_spots", f"{path}: gates.cartographer")

    smp = rec["sampling"]
    if not_applicable(smp):
        pass
    elif isinstance(smp, dict) and smp.get("status") == "done":
        sampled = smp.get("sampled_ids")
        if not isinstance(sampled, list) or not sampled:
            fail(f"{path}: sampling.sampled_ids が空")
        unknown = [s for s in sampled if s not in ids]
        if unknown:
            fail(f"{path}: sampling.sampled_ids に無い主張 id: {unknown}")
        require_int(smp, "overturned", f"{path}: sampling")
    else:
        fail(f"{path}: 'sampling' は status=done か「該当なし+理由」のどちらかの形")

    conv = rec["convergence"]
    if not isinstance(conv, dict):
        fail(f"{path}: 'convergence' が object でない")
    require_int(conv, "rounds_total", f"{path}: convergence", 1)
    require_int(conv, "consecutive_zero", f"{path}: convergence")
    if conv.get("outcome") not in OUTCOMES:
        fail(f"{path}: convergence.outcome が不正（{'/'.join(OUTCOMES)}）")
    if conv["outcome"] == "stopped":
        require_str(conv, "stopped_reason", f"{path}: convergence（outcome=stopped）")

    proc = rec["process"]
    if not isinstance(proc, dict):
        fail(f"{path}: 'process' が object でない")
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
    # 正さず、無申告だけを塞ぐ（存在の可視化がこの道具の役割）。
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
        require_str(proc, "load_zero_reason", f"{path}: process（荷重の選定がゼロ）")
    elif proc.get("load_zero_reason"):
        fail(f"{path}: 荷重があるのに load_zero_reason がある（申告の腐り）")

    dec = rec["decisions"]
    if not isinstance(dec, dict):
        fail(f"{path}: 'decisions' が object でない")
    for k in ("decide_now", "poc", "human_only"):
        v = dec.get(k)
        if not isinstance(v, list) or not all(isinstance(s, str) and s.strip() for s in v):
            fail(f"{path}: decisions.{k} が文字列の配列でない")
    if not any(dec[k] for k in ("decide_now", "poc", "human_only")):
        fail(f"{path}: decisions が全部空——3 分類に仕分けろ（P5）")


def blockers(rec):
    """**収束を名乗る記録だけを疑う。** outcome=stopped は未収束の正直な申告であり、
    ゲートの未 pass・覆りは阻害でない（停止の理由が記録にある）。"""
    if rec["convergence"]["outcome"] == "stopped":
        return []

    out = []
    for cl in rec["claims"]:
        # 相違は敵対検証を経て初めて確定（P1 の規律）。未反証の相違を載せた収束は発行できない。
        if cl["verdict"] == "相違" and not cl["refuted"]:
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
    # 終了コードの契約を担保するのはここ 1 箇所（理由は冒頭 docstring）。
    try:
        main()
    except SystemExit:
        raise
    except Exception as e:
        fail(f"想定外の例外（{type(e).__name__}）: {e}")
