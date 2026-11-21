"""台本が返した判定語彙の到達を数える部品（simulate.py と simulate_review.py が使う）。

集めた値（(ノード, フィールド) → 値の集合）は各台本が自分の dict に持ち、ここには持たない——台本ごとの到達の数が混ざらない。
到達を測る理由と数の定数（VOCAB_REACHED）は各台本の側に在る。
"""
import sys

import parallel  # 同じディレクトリ。集めた値の共有の更新を守る錠（parallel.LOCK）


def record(seen, node, output):
    """台本が返した値を seen に集める。**既存の検査に相乗りするので、この測定のために 1 回も余計に回さない。**"""
    if not isinstance(output, dict):
        return
    nid = node.split("[")[0]

    def walk(v, p=""):
        if isinstance(v, dict):
            for k, x in v.items():
                walk(x, f"{p}.{k}" if p else k)
        elif isinstance(v, list):
            for x in v:
                walk(x, p + "[]")
        elif isinstance(v, (str, bool)):
            with parallel.LOCK:
                seen[(nid, p)].add(v)

    walk(output)


def coverage(plugin, graph_path, seen):
    """graph が宣言する判定語彙のうち、台本が返したものの数と、返していないものの一覧 ——(到達, 全体, 未到達の一覧, 到達した値の一覧)。"""
    sys.path.insert(0, str(plugin))
    from engine.rules import load_rules
    # engine と同じく $ref（ブロックのファイルも）を展開した形で数える（出口のノードの schema はブロックのファイルに在り、生の graph では
    # $ref の先の語彙が数えられない）。schema の走査は engine の 1 本（patternProperties の下にも降りる）
    from engine.schema import load_graph, walk_schema
    g = load_graph(graph_path)[0]
    enums = {}
    # **無作為に項目を引く扇のノードは数えない**——引く物が run ごとに変わるので、そこから返る値は
    # 台本の性質ではない（実測: research で数えていたとき到達が 24 と 25 で揺れた）。除外は rules が宣言する
    # `RANDOM_FAN` から導く——測る側でノードの名前を手で並べると、扇を足した周にまた揺れる。review の graph に今 fan_out は
    # 無いが、両方の台本が同じ口で数えるので、扇を足した周に**片側だけラチェットが乱数で揺れる**ことは起きない
    # （実測 2026-09-14: RANDOM_FAN を読むのが research 側だけだったとき、review 側は 0 件だった）
    rules = load_rules(graph_path, g)
    random_fan = set(getattr(rules, "RANDOM_FAN", ()) or ())
    for nid, n in g["nodes"].items():
        if (n.get("fan_out") or {}).get("builtin") in random_fan:
            continue
        for p, s in walk_schema(n.get("schema") or {}):
            if "enum" in s:
                enums[(nid, p.removeprefix("$").removeprefix("."))] = set(s["enum"])
    total = sum(len(v) for v in enums.values())
    reached = sum(len(v & seen.get(k, set())) for k, v in enums.items())
    unreached = sorted(f"{k[0]}.{k[1]}={v}" for k, vs in enums.items() for v in sorted(vs - seen.get(k, set())))
    # 到達した値そのもの（組に分けた回は、まとめの口がこの和集合の大きさを記録と照合する）
    keys = sorted(f"{k[0]}.{k[1]}={v}" for k, vs in enums.items() for v in sorted(vs & seen.get(k, set())))
    return reached, total, unreached, keys
