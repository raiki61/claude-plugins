"""役に写させない——engine が一覧に振った番号で役に指させ、受け付けで名前に戻す（graph の節の `pointers`）。

役に長い文字列（判定の単位の key・事前審査の穴の key）を一字一句写させ、1 字違えば受け付けで拒んで返させ直していた
（実測: run 20260924-081523 の 5 周目に 3 回の差し戻し）。Anthropic の Citations が文書の添字で指させ、本文を API の側で
引くのと同じ形にする。

宣言: `"pointers": [{"at": "plan[].unit_keys[]", "from": ["record.units"], "field": "key"}]`
  - at    —— 返答の中の位置（`.` で区切り、`[]` は配列の要素ごと）。その位置は番号（1 始まりの整数）か名前（文字列）
  - from  —— 役に貼る一覧の ctx パス（reads に在ること）。複数なら連結して通し番号
  - field —— 名前にする欄（既定 key）。要素が文字列の一覧ならその文字列

流れ:
  1. 読み込み（widen。schema.expand_refs が graph を読む唯一の入口で呼ぶ）: at の位置の型を [integer, string] に広げる。
     型を graph に手で書かせない——schema と pointers の宣言が食い違う状態を作れなくする
  2. emit（snapshot）: from の一覧を解いて名前の列を instance に固め、Renderer が from の穴を貼るときに各行へ no を足す
  3. done（resolve）: schema の検査の直後、at の位置の整数を固めた名前に置き換える。範囲外と、名前の列を固めていない
     instance（出した後に graph が変わった）への整数は拒む。置き換えた後の返答だけが rules・記録・報告に届くので、
     rules の突き合わせと周をまたぐ台帳（defer 台帳）は名前の字面のまま動く

文字列は今までどおり名前として通す（記録済みの run の返答と偽の役の台本をそのまま流し込める。名前の正しさは rules の
字面の突き合わせが見る）。
"""
from .util import get_path

NO = "no"   # 貼る一覧の各行に足す番号の欄


def _segs(at):
    return [(s[:-2], True) if s.endswith("[]") else (s, False) for s in at.split(".")]


def _schema_at(schema, at):
    """at の位置の schema（辿れなければ None）。走査は schema.walk_schema が正本（位置の綴りは $.<at>）"""
    from .schema import walk_schema   # schema と pointers は互いを引く（schema.expand_refs が widen を呼ぶ）ので、使う所で import する
    return dict(walk_schema(schema)).get("$." + at)


def widen(nodes):
    """pointers の宣言を確かめ、at の位置の型を番号か名前に広げる（schema を書き換える。graph を読む入口で 1 度だけ）。
    宣言の誤りは ValueError——黙って飛ばすと、番号が名前に戻らないまま rules に届く"""
    from .render import Renderer
    for nid, n in nodes.items():
        ptrs = n.get("pointers")
        if ptrs is None:
            continue
        if not isinstance(ptrs, list) or not n.get("schema"):
            raise ValueError(f"節 {nid}: pointers は schema を持つ節の配列")
        seen = {}
        for i, r in enumerate(ptrs):
            if not isinstance(r, dict) or set(r) - {"at", "from", "field", "note"} or not r.get("at") \
                    or not isinstance(r.get("from"), list) or not r["from"]:
                raise ValueError(f"節 {nid}: pointers[{i}] は {{at, from: [パス…], field?}}")
            leaf = _schema_at(n["schema"], r["at"])
            if leaf is None or leaf.get("type") not in ("string", ["string"], ["integer", "string"]):
                raise ValueError(f"節 {nid}: pointers[{i}] の at '{r['at']}' が schema の文字列の欄に無い")
            leaf["type"] = ["integer", "string"]
            leaf["minimum"] = 1
            for f in r["from"]:
                if not Renderer({}, n.get("reads")).allowed(f):
                    raise ValueError(f"節 {nid}: pointers[{i}] の from '{f}' が reads に無い（貼れない一覧の番号は役に見えない）")
                # 同じ一覧を別の連結で指すと、同じ行に 2 つの番号が要る——連結は節の中で 1 通り
                if seen.setdefault(f, r["from"]) != r["from"]:
                    raise ValueError(f"節 {nid}: from '{f}' が pointers ごとに別の連結で使われている（番号が 1 つに決まらない）")


def snapshot(ctx, ptrs):
    """emit の時点の名前の列と、貼る一覧ごとの番号の起点 ——([{at, names}], {パス: 起点})"""
    snap, offsets = [], {}
    for r in ptrs or []:
        names = []
        for f in r["from"]:
            try:
                rows = get_path(ctx, f)
            except KeyError:
                rows = []
            offsets[f] = len(names)
            names += [(x.get(r.get("field", "key")) if isinstance(x, dict) else x) for x in (rows if isinstance(rows, list) else [])]
        snap.append({"at": r["at"], "names": names})
    return snap, offsets


def number(rows, offset):
    """貼る一覧の各行の先頭に no を足した写し（ctx の値は書き換えない——record と loop_state に no を残さない）。
    行が元から no の欄を持っていても engine の番号で上書きする（役が指すのは engine の番号だけ）"""
    return [{NO: offset + i + 1, **{k: v for k, v in x.items() if k != NO}} if isinstance(x, dict) else {NO: offset + i + 1, "value": x}
            for i, x in enumerate(rows)]


def _slots(obj, segs):
    """at の位置の（入れ物, 鍵）を全部"""
    (name, arr), rest = segs[0], segs[1:]
    if not isinstance(obj, dict) or name not in obj:
        return
    v = obj[name]
    if not arr:
        yield from (_slots(v, rest) if rest else [(obj, name)])
        return
    for i, x in enumerate(v if isinstance(v, list) else []):
        yield from (_slots(x, rest) if rest else [(v, i)])


def resolve(output, ptrs, snap):
    """返答の中の番号を名前に置き換える（output を書き換える）。拒む理由の一覧を返す（空なら全部置き換えた）"""
    errs = []
    for i, r in enumerate(ptrs or []):
        names = snap[i]["names"] if snap and i < len(snap) and snap[i]["at"] == r["at"] else None
        for box, k in _slots(output, _segs(r["at"])):
            v = box[k]
            if not isinstance(v, int) or isinstance(v, bool):
                continue
            if names is None:
                errs.append(f"{r['at']} の番号 {v}: この instance は番号の一覧を固めていない（出した後に graph が変わった）——名前で書け")
            elif not 1 <= v <= len(names) or not isinstance(names[v - 1], str):
                errs.append(f"{r['at']} の番号 {v} は貼った一覧（{'・'.join(r['from'])}）の no に無い（1〜{len(names)}）")
            else:
                box[k] = names[v - 1]
    return errs
