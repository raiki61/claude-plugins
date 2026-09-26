"""run の状態（盤面の loop）へ書く唯一の口。規則の関数は書き込みを effect（{to: "loop.<鍵>", reducer, value}）で頼み、engine が
graph の state_schema の鍵ごとの合わせ方（x-reducer）で当てる——LangGraph の State の reducer と同じ形（節は更新だけを返し、鍵ごとの
reducer が合わせる）。旧い形の規則の関数（盤面を受け取る物）も同じ口（rules に差し込む write_loop）を通して書く。

人の手当て（loop.py patch）は reducer を飛ばす上書きで、飛ばした鍵と合わせ方を痕跡（state.patches の bypass）に残す（LangGraph の
Overwrite と同じ扱い）。
"""
import copy

from .util import die

# 合わせ方の語（graph の state_schema の最上位の鍵の x-reducer。graphcheck がこの表を import して語と位置を照らす）
#   overwrite    値で置き換える（値が null なら鍵を外す）
#   append       配列の後ろに足す（値は配列）
#   merge_by_key 辞書の鍵ごとに合わせる（値は辞書。同じ鍵の値がどちらも辞書なら欄を上書きで足し、ほかは置き換える）
#   set_once     まだ無いときだけ置く（在れば何もしない——一方向の旗。下げるのは人の手当てだけ）
REDUCERS = ("overwrite", "append", "merge_by_key", "set_once")
REDUCER_KEY = "x-reducer"
LOOP_HEAD = "loop."


def reducer_of(schema, key):
    """state_schema が鍵 key に宣言した合わせ方（宣言が無ければ None）"""
    prop = ((schema or {}).get("properties") or {}).get(key)
    return prop.get(REDUCER_KEY) if isinstance(prop, dict) else None


def declares_reducers(schema):
    """state_schema が合わせ方を宣言している（＝run の状態を effect の口だけで書く）graph か"""
    return any(isinstance(p, dict) and REDUCER_KEY in p for p in ((schema or {}).get("properties") or {}).values())


def apply_effects(loop, effects, schema, by):
    """effect の並びを盤面の loop（dict。その場で書き換える）に当てる。形の外れは規則の欠陥なので止める（盤面は保存しない）。
    state_schema に無い鍵は外すこと（overwrite で null）だけを受ける——旧い版の rules が積んだ鍵の片付け"""
    if not isinstance(effects, list):
        die(f"{by}: effects は配列で返す（{type(effects).__name__}）")
    for i, e in enumerate(effects):
        if not (isinstance(e, dict) and set(e) == {"to", "reducer", "value"} and isinstance(e["to"], str) and e["to"].startswith(LOOP_HEAD)):
            die(f"{by}: effects[{i}] は {{to: 'loop.<鍵>', reducer, value}} の形で書く（{e!r:.200}）")
        key, r, value = e["to"][len(LOOP_HEAD):], e["reducer"], e["value"]
        if not key or "." in key:
            die(f"{by}: effects[{i}] の書き先 '{e['to']}' は loop の最上位の鍵 1 つ（下の欄は合わせ方の値で書く）")
        want = reducer_of(schema, key)
        if want is None:
            if r == "overwrite" and value is None and key not in ((schema or {}).get("properties") or {}):
                loop.pop(key, None)
                continue
            die(f"{by}: effects[{i}] の鍵 '{key}' に graph の state_schema が合わせ方（{REDUCER_KEY}）を宣言していない")
        if r != want:
            die(f"{by}: effects[{i}] の鍵 '{key}' の合わせ方は {want}（state_schema）——{r} で頼んだ")
        value = copy.deepcopy(value)
        if r == "overwrite":
            if value is None:
                loop.pop(key, None)
            else:
                loop[key] = value
        elif r == "append":
            if not isinstance(value, list):
                die(f"{by}: effects[{i}] の append の値は配列（{type(value).__name__}）")
            loop.setdefault(key, []).extend(value)
        elif r == "merge_by_key":
            if not isinstance(value, dict):
                die(f"{by}: effects[{i}] の merge_by_key の値は辞書（{type(value).__name__}）")
            cur = loop.setdefault(key, {})
            for k, v in value.items():
                if isinstance(cur.get(k), dict) and isinstance(v, dict):
                    cur[k].update(v)
                else:
                    cur[k] = v
        elif r == "set_once":
            loop.setdefault(key, value)
        else:
            die(f"{by}: effects[{i}] の合わせ方 '{r}' を engine が知らない（{'/'.join(REDUCERS)}）")


def write_loop(b, key, reducer, value, by=None):
    """旧い形の規則の関数（盤面を受け取る物）が run の状態を書く口（rules に差し込む）。effect 1 つを同じ apply_effects で当てる"""
    apply_effects(b.loop_state, [{"to": LOOP_HEAD + key, "reducer": reducer, "value": value}],
                  (getattr(b, "graph", None) or {}).get("state_schema"), by or f"write_loop {key}")


def bypassed(before, after, schema):
    """手当て（loop.py patch）の前後で変わった loop の鍵と、その鍵の合わせ方（飛ばした reducer。宣言の無い鍵は None）"""
    keys = sorted(k for k in set(before) | set(after) if before.get(k, None) != after.get(k, None) or (k in before) != (k in after))
    return {k: reducer_of(schema, k) for k in keys}
