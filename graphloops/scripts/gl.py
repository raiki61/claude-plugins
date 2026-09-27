#!/usr/bin/env python3
"""外の土台（Archon の bash・script の節など）から graphloops の規則の関数を呼ぶ薄い層。**盤面にも作業ツリーにも書かない。**

本物の盤面（loop.py init が作る置き場）を読み、読み口を組んで規則の関数を呼び、関数の返り（書き込みの依頼 effects を含む）を JSON 1 行で
返すだけ。effects を当てて盤面を進める口は engine の既存の 1 本（loop.py の done・answer・next）だけで、ここは 2 本目を作らない。
周は盤面の周、前の周の出力・履歴（hist）・入力（inputs。周の頭で固めた版を含む）も盤面から読む。

使い方:
    gl.py cond    --dir <盤面> --name <条件の名前>                       → {ok, value, why}
    gl.py accept  --dir <盤面> --node <節か instance の id> --reply <返答.json> [--item <項目.json>]
                  → {ok, called, form, reason?, note?, reply?, effects, remaining?, pending}——done と同じ検査の鎖（engine の
                    commands.check_reply。型・空の本文・番号の名前戻し・扇の被覆・段・節ごとの整合・effects・記録への写し・記録の整合）を
                    盤面の写しの上で当てる。done の門は拒否に使わない——pending が、engine の門（commands.accept_gate: 止めた run・
                    待っていない instance・deps の待ち）を通るかを言う（作業ツリーの突合は done の時にしか決まらないので含まない）。扇の節は instance の id で指すか --item を渡す（節の id だと最後に出した instance の項目で照らす）。
                    form は節の宣言で決まり（new・legacy・none）、called は節ごとの整合まで届いたか。旧い形の受け付けの関数（盤面を
                    受け取り、中で盤面の隣に書く物が在る）は呼ばない（called: false・form: legacy）
    gl.py request --dir <盤面> --file <依頼.json> --reason <出どころ>    → {ok, reason?, note?, request_findings?}
                    loop.py add と同じ rules の add を盤面の写しの上で当てる（積んだ後の依頼の一覧を返す。盤面には積まない）
    gl.py machine --dir <盤面> --node <機械の節>                         → {ok, called, form, out?, effects?, schema_errors?}
                    新しい形の機械の節だけを呼ぶ（旧い形は作業ツリーや盤面を書くので called: false）
    gl.py exit    --graph <graph.json> --node <節> [--against <schema.json>] [--strip-notes] → {ok, schema} / {ok, diffs}
                    節の出口の型（返答の schema。$ref を展開した形）。--strip-notes で注記の語 note を落とす（外の土台の output_format に
                    貼る形）。--against を渡すと、外の土台の型の写しと突き合わせて食い違う path を返す

終了コード: 拒否（型に合わない・受け付けない・食い違う）も 0 で JSON を返す。引数・盤面・graph・JSON が読めないときだけ 2。
"""
import argparse
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8")

from engine.advance import load_item  # noqa: E402
from engine.board import Board  # noqa: E402
from engine.commands import accept_gate, check_reply  # noqa: E402
from engine.rules import hook, registry, takes_view  # noqa: E402
from engine.schema import load_graph, strip_notes, validate_schema  # noqa: E402
from engine.util import AnswerReject, HandBack, Reject  # noqa: E402


class Unreadable(Exception):
    """読めない（exit 2）"""


def out(obj):
    print(json.dumps(obj, ensure_ascii=False))
    return 0


def board(d):
    if not (pathlib.Path(d) / "state.json").is_file():
        raise Unreadable(f"盤面 {d} に state.json が無い")
    try:
        return Board(d)
    except SystemExit as e:   # engine の die（graph・rules が読めない）
        raise Unreadable(f"盤面 {d} が読めない（exit {e.code}）") from e


def read_json_file(path, what):
    try:
        return json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise Unreadable(f"{what} {path} が読めない（{e}）") from e


def node_of(b, nid):
    if nid not in b.nodes:
        raise Unreadable(f"節 '{nid}' が盤面の graph に無い")
    return b.nodes[nid]


def instance_of(b, name):
    """--node の宛先 ——（節の id, instance か None）。instance の id（done と同じ宛先）ならその instance。節の id なら今の周の
    待ちの物、無ければ最後に出した物（どの周でも）——扇の節は同じ節に instance が並ぶので、項目を照らすなら instance の id で指す"""
    rows = [i for rd in b.state["rounds"] for i in rd["instances"].values()]
    if name not in b.nodes:
        mine = [i for i in rows if i.get("id") == name]
        if not mine:
            raise Unreadable(f"'{name}' が盤面の graph の節にも instance にも無い")
        return mine[-1]["node"], mine[-1]
    rows = [i for i in rows if i.get("node") == name]
    pending = [i for i in rows if i.get("status") == "pending"]
    return name, (pending or rows or [None])[-1]


def would_take(b, inst):
    """done がこの instance の返答を今受けうるか——engine の門（accept_gate: 止めた run・待っていない instance・deps の待ち）をそのまま
    当てる。作業ツリーの突合は done の時にしか決まらないので含まない"""
    if not inst:
        return False
    try:
        accept_gate(b, inst["id"])
    except Reject:
        return False
    return True


def form_of(fn):
    return "none" if fn is None else "new" if takes_view(fn) else "legacy"


def cmd_cond(a):
    b = board(a.dir)
    if a.name not in registry(b.rules, "CONDS"):
        raise Unreadable(f"条件 '{a.name}' が rules の CONDS に無い")
    value, why = b.cond(a.name)
    return out({"ok": True, "value": value, "why": why})


def cmd_accept(a):
    b = board(a.dir)
    b.held_trace = []   # 段の昇格（thicken）が trace.jsonl に書く行を控えたまま捨てる——盤面の置き場に書かない
    nid, inst = instance_of(b, a.node)
    n = b.nodes[nid]
    try:
        text = pathlib.Path(a.reply).read_text(encoding="utf-8")
    except OSError as e:
        raise Unreadable(f"返答 {a.reply} が読めない（{e}）") from e
    fn = registry(b.rules, "POST_CHECKS").get(n.get("post_check")) if n.get("post_check") else None
    form = form_of(fn)
    pending = would_take(b, inst)
    if form == "legacy":
        return out({"ok": False, "called": False, "form": form, "effects": [], "pending": pending,
                    "reason": f"節 {nid} の受け付け '{n['post_check']}' は旧い形（盤面を受け取る）で、gl からは呼ばない——"
                              "新しい形（読み口を受けて JSON と effects を返す）へ移した後に呼べる"})
    item = read_json_file(a.item, "項目") if a.item else (load_item(inst, b.dir) if inst else None)
    seen = {}
    try:
        output, notes, remaining, effs = check_reply(b, nid, text, item, (inst or {}).get("pointers"), seen=seen)
    except (AnswerReject, Reject, HandBack) as e:
        return out({"ok": False, "called": bool(fn and seen), "form": form, "reason": str(e), "effects": [], "pending": pending})
    return out({"ok": True, "called": fn is not None, "form": form, "reply": output, "effects": effs, "pending": pending,
                **({"remaining": remaining} if remaining else {}), **({"note": " / ".join(notes)} if notes else {})})


def cmd_request(a):
    b = board(a.dir)
    fn = hook(b.rules, "add")
    if not fn:
        raise Unreadable("この盤面のループの rules は add（依頼の受け付け）を持たない")
    items = read_json_file(a.file, "依頼")
    try:
        got = fn(b, items, a.reason)   # 盤面の写し（このプロセスの中だけ）に積む——保存しない
    except Reject as e:
        return out({"ok": False, "reason": str(e)})
    msg = got if isinstance(got, str) else got["msg"]
    return out({"ok": True, "note": msg, "request_findings": (b.record.get("process") or {}).get("request_findings")})


def cmd_machine(a):
    b = board(a.dir)
    n = node_of(b, a.node)
    fn = registry(b.rules, "BUILTINS").get(n.get("builtin")) if n.get("builtin") else None
    if fn is None:
        raise Unreadable(f"節 '{a.node}' は機械の節（builtin）でない")
    if form_of(fn) == "legacy":
        return out({"ok": False, "called": False, "form": "legacy",
                    "reason": f"機械の節 '{n['builtin']}' は旧い形（盤面を受け取り、作業ツリーや盤面を書く物が在る）で、gl からは呼ばない"})
    try:
        _, got = b.rule(n["builtin"], fn, a.node)
    except Reject as e:
        return out({"ok": False, "called": True, "form": "new", "reason": str(e)})
    effs = got.pop("effects", []) if isinstance(got, dict) else []
    errs = validate_schema(got, n["schema"]) if isinstance(n.get("schema"), dict) else []
    return out({"ok": not errs, "called": True, "form": "new", "out": got, "effects": effs, **({"schema_errors": errs} if errs else {})})


def diffs(a, b, path="$"):
    """2 つの schema の食い違う path（鍵の有無と値）"""
    if isinstance(a, dict) and isinstance(b, dict):
        rows = []
        for k in sorted(set(a) | set(b)):
            if k not in a or k not in b:
                rows.append(f"{path}.{k}: {'外の型にだけ在る' if k not in a else 'graph にだけ在る'}")
            else:
                rows += diffs(a[k], b[k], f"{path}.{k}")
        return rows
    if isinstance(a, list) and isinstance(b, list) and len(a) == len(b):
        return [r for i, (x, y) in enumerate(zip(a, b)) for r in diffs(x, y, f"{path}[{i}]")]
    return [] if a == b else [f"{path}: graph は {json.dumps(a, ensure_ascii=False)[:80]}・外の型は {json.dumps(b, ensure_ascii=False)[:80]}"]


def cmd_exit(a):
    g, why = load_graph(a.graph)
    if why:
        raise Unreadable(why)
    n = g["nodes"].get(a.node)
    if n is None:
        raise Unreadable(f"節 '{a.node}' が graph に無い")
    sch = n.get("schema")
    if not isinstance(sch, dict):
        return out({"ok": False, "reason": f"節 {a.node} は出口の型（schema）を持たない"})
    if a.strip_notes:
        sch = strip_notes(sch)
    if not a.against:
        return out({"ok": True, "schema": sch})
    rows = diffs(sch, read_json_file(a.against, "外の型"))
    return out({"ok": not rows, "diffs": rows})


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("cond")
    s.add_argument("--dir", required=True)
    s.add_argument("--name", required=True)
    s = sub.add_parser("accept")
    s.add_argument("--dir", required=True)
    s.add_argument("--node", required=True)
    s.add_argument("--reply", required=True)
    s.add_argument("--item")
    s = sub.add_parser("request")
    s.add_argument("--dir", required=True)
    s.add_argument("--file", required=True)
    s.add_argument("--reason", required=True)
    s = sub.add_parser("machine")
    s.add_argument("--dir", required=True)
    s.add_argument("--node", required=True)
    s = sub.add_parser("exit")
    s.add_argument("--graph", required=True)
    s.add_argument("--node", required=True)
    s.add_argument("--against")
    s.add_argument("--strip-notes", action="store_true")
    a = p.parse_args(argv)
    try:
        return {"cond": cmd_cond, "accept": cmd_accept, "request": cmd_request, "machine": cmd_machine, "exit": cmd_exit}[a.cmd](a)
    except Unreadable as e:
        print(json.dumps({"ok": False, "unreadable": str(e)}, ensure_ascii=False))
        return 2
    except SystemExit as e:   # engine の die（規則の欠陥・盤面の壊れ）——判定を下せない
        print(json.dumps({"ok": False, "unreadable": f"engine が止めた（exit {e.code}）"}, ensure_ascii=False))
        return 2
    except Exception as e:  # noqa: BLE001 — 盤面の形が崩れている等で関数が落ちた——判定を下せない（拒否と混ぜない）
        print(json.dumps({"ok": False, "unreadable": f"{type(e).__name__}: {e}"}, ensure_ascii=False))
        return 2


if __name__ == "__main__":
    sys.exit(main())
