"""記録への書き込み。汎用の op（set / append / merge_by_id）は engine が、記録の形に固有の op は rules が持つ。"""
from .rules import registry
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
            ops[op](b, nid, src, {**w, "_item": item})  # 扇の項目も渡す（記録を書く op が item を要ることがある）
