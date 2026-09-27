"""記録への書き込み。汎用の op（set / append / merge_by_id）は engine が、記録の形に固有の op は rules が持つ。

rules の op のうち読み口を受ける新しい形（cond_reads の印を持つ物）は、書く値を返すだけで記録を直に書かない。書き先は op が writes_to
（graph の writes の to を {to} に埋める記録の path の型）で名乗り、ここがそこに置く——記録への書き込みの口を増やさず、書き先の正本は
graph の writes の宣言（graphcheck が照らし、巻き戻しが見る）のまま。旧い形の op（盤面を受け取る物）は今までどおり盤面で呼ぶ。"""
from .rules import registry, takes_view
from .util import Reject, die, get_path, has_path, pick, set_path

ENGINE_WRITE_OPS = ("set", "append", "merge_by_id")  # engine が持つ op。graphcheck はこれを import して照合する（写さない）


def stamp_field(w, nid):
    """stamp_round は『周を書き込む欄の名前』（append でも merge_by_id でも同じ意味）。真偽値は受け付けない。"""
    f = w.get("stamp_round")
    if f is None:
        return None
    if not isinstance(f, str) or not f:
        die(f"{nid}: writes.stamp_round は欄の名前（文字列）で書く: {f!r}")
    return f


def apply_writes(b, nid, output, item):
    ops = registry(b.rules, "WRITE_OPS")
    for w in b.nodes[nid].get("writes", []):
        op = w["op"]
        frm = w.get("from", "$")
        if not has_path(output, frm):
            # 欄が無い＝その write は起きない。**起きなかったことを残す**——graphcheck が optional の宣言を
            # 要求するのは静的な側で、実際に飛んだ周は記録にしか出ない（役が毎周省いていても誰も気づかない形だった）
            b.state.setdefault("writes_skipped", []).append({"node": nid, "round": b.round, "from": frm, "to": w.get("to")})
            continue
        src = output if frm == "$" else get_path(output, frm)
        if "pick" in w:
            src = pick(src, w["pick"])
        if op not in ENGINE_WRITE_OPS and op not in ops:
            die(f"writes.op '{op}' を engine も rules も知らない")
        if op == "set":
            set_path(b.record, w["to"], src)
        elif op == "append":
            if not has_path(b.record, w["to"]):
                set_path(b.record, w["to"], [])
            lst = get_path(b.record, w["to"])
            for it in src if isinstance(src, list) else [src]:
                it = dict(it) if isinstance(it, dict) else {"text": it}
                if w.get("number"):
                    it[w["number"]] = (lst[-1][w["number"]] + 1) if lst else 1
                sf = stamp_field(w, nid)
                if sf:
                    it[sf] = b.round
                lst.append(it)
        elif op == "merge_by_id":
            lst = get_path(b.record, w["to"])
            key = w.get("key", "id")
            index = {x.get(key): x for x in lst}
            for it in src if isinstance(src, list) else [src]:
                if not isinstance(it, dict) or key not in it:
                    raise Reject(f"{nid}: '{frm}' の要素に '{key}' が無い")
                fields = w.get("fields")
                data = {k: v for k, v in it.items() if k != key and (fields is None or k in fields)}
                data.update(w.get("const", {}))
                sf = stamp_field(w, nid)
                if sf:
                    data[sf] = b.round
                if it[key] in index:
                    index[it[key]].update(data)
                elif w.get("allow_new"):
                    new = {key: it[key], **data}
                    lst.append(new)
                    index[it[key]] = new
                else:
                    raise Reject(f"{nid}: 記録に無い {key}='{it[key]}' を書こうとしている（新規は許可されていない）")
        else:
            fn = ops[op]
            new, got = b.rule(op, fn, nid, src, {**w, "_item": item})  # 扇の項目も渡す（記録を書く op が item を要ることがある）
            if new:
                set_path(b.record, writes_to(fn, op, w), got)


def writes_to(fn, op, w):
    """新しい形の rules の op が値を置く記録の path（op の writes_to に graph の writes の to を埋めた物）"""
    tmpl = getattr(fn, "writes_to", None)
    if not isinstance(tmpl, str) or not tmpl:
        die(f"writes.op '{op}' は新しい形（読み口を受ける）なのに writes_to（値を置く記録の path の型）を名乗らない（rules の欠陥）")
    return tmpl.format(to=w.get("to", ""))
