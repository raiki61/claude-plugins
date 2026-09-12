"""回す側が呼ぶコマンド。init / next / done / skip / answer / thicken / add / patch / finalize / status / record。"""
import datetime
import json
import os
import pathlib
import re
import sys

from .advance import advance, emit_instance, load_item
from .board import Board, empty_round
from .record import apply_writes
from .rules import hook, load_rules, registry
from .schema import validate_schema
from .util import PLUGIN_ROOT, Reject, die, dump, get_path, git, has_path, now, porcelain, read_json, safe_name, set_path, sha, write_json
from .validator import find_validator, finalize, run_validator, env_root


# ---------------------------------------------------------------- next
def cmd_next(a):
    b = Board(resolve_dir(a))
    if b.state["status"] in ("converged", "stopped") and all(b.node_state(n) != "pending" for n in b.nodes):
        print(dump({"status": b.state["status"], "round": b.round, "ready": [], "note": "全部の節が終わっている。record.json と report を見よ"}))
        return
    notes = advance(b)
    b.save()
    if b.state.get("pending_human"):
        print(dump({"status": "awaiting_human", "round": b.round, "ready": [], "ask": b.state["pending_human"],
                    "how": "答えが決まったら loop.py answer --text <選択肢>。無人なら init --unattended で保守的な既定になる"}))
        return
    ready = [i for i in b.rd["instances"].values() if i["status"] == "pending"]
    print(dump({
        "status": b.state["status"], "round": b.round, "thickness": b.state["thickness"], "dir": str(b.dir), "notes": notes,
        "ready": [{k: v for k, v in i.items() if k != "tree_before"} for i in ready],
        "how": ("ready の全部を同時に始めてよい（同じ波）。agent は subagent_type に agent_type を渡す。"
                "起動は運び手（小さな汎用 agent）に任せてよい: 運び手は deliver=path なら『<prompt_file> を読み、その指示にそのまま従え』の 1 文で、"
                "deliver=paste なら prompt_file の本文をそのまま貼って役を起動し、返答を一字も変えず out_path に書き、あなたには『wrote』だけ返す。"
                "自分で起動するなら同じ渡し方で、返答を out_path に保存する。"
                "agent_continue は agent_id の agent に SendMessage で続ける（同じ渡し方）。"
                "runner は自分でやる（skills があればその skill を呼ぶ。置き場のパスで渡された物は要る所だけ Read）。返答を out_path に保存して "
                "loop.py done --node <id> [--agent-id <id>]（別の場所に置いたなら --output <file>）。ready が空で status が running なら、done の直後にもう一度 next"),
    }))


# ---------------------------------------------------------------- done
def parse_output(text):
    text = text.strip()
    m = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if m:
        text = m.group(1).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        s, e = text.find("{"), text.rfind("}")
        if s != -1 and e > s:
            try:
                return json.loads(text[s:e + 1])
            except json.JSONDecodeError:
                pass
    raise Reject("返答が JSON として読めない（```json ... ``` か、JSON だけを返せ）")


STDIN_MAX = 20_000_000  # 文字


def cmd_done(a):
    b = Board(resolve_dir(a))
    inst = b.rd["instances"].get(a.node)
    if not inst:
        raise Reject(f"この周に節 '{a.node}' は出ていない（loop.py next で確かめよ）")
    if inst["status"] != "pending":
        raise Reject(f"節 '{a.node}' は既に {inst['status']}")
    nid = inst["node"]
    n = b.nodes[nid]
    src = a.output or (inst.get("out_path") if inst.get("out_path") and pathlib.Path(inst["out_path"]).is_file() else None)
    if src:
        try:
            text = pathlib.Path(src).read_text(encoding="utf-8")
        except OSError as e:
            die(f"{src}: 読めない（{e}）")
    elif not sys.stdin.isatty():
        text = sys.stdin.read(STDIN_MAX + 1)
        if len(text) > STDIN_MAX:
            raise Reject(f"標準入力が {STDIN_MAX} 文字を超えている——--output でファイルを渡せ")
    else:
        raise Reject(f"返答が無い——--output か標準入力で渡すか、運び手に {inst.get('out_path')} へ書かせる")
    if n.get("schema"):
        output = parse_output(text)
        errs = validate_schema(output, n["schema"])
        if errs:
            print("NG 返答が型に合わない（直して done し直す。回す側が中身を補ってはいけない——役に返させろ）:", file=sys.stderr)
            for e in errs:
                print(f"  - {e}", file=sys.stderr)
            sys.exit(1)
    else:
        # 本文を返す節にも空の検査を当てる（schema 節は minLength が同じ形を落としている）。空を受けると
        # 0 バイトの report.md が残り、『人が決めること』が黙って消える（実測: --output <空> も </dev/null> も exit 0 だった）。
        if not text.strip():
            raise Reject(f"節 '{nid}' の返答が空——本文を返す節に空は受け付けない（役が何も返していないか、運び手が {inst.get('out_path')} に書けていない）")
        output = {"text": text}
    item = load_item(inst)
    # 作業ツリーの前後突合（書き換えを塞ぐのは定義でも自制でもなくこの突合）
    if "tree_before" in inst:
        after = porcelain()
        if after is None:
            raise Reject("git status が取れない——作業ツリーの突合ができない場所から done している（リポジトリの中で呼べ）")
        if after != inst["tree_before"]:
            diff = sorted(set(after or []) ^ set(inst["tree_before"] or []))
            # 同じ波に保護対象の instance が複数在ると、誰が汚したかはこの突合では決まらない（基準点は全員ほぼ同時刻の
            # グローバルな git status で、done を呼んだ順に検出される）。**帰属を断定せず、同じ波の一覧を記録に残す。**
            peers = sorted(i for i, x in b.rd["instances"].items()
                           if i != a.node and "tree_before" in x and x["status"] == "pending")
            who = f"（同じ波で保護対象の instance が他に {len(peers)} 件走っている: {peers}——変えたのがこの instance とは限らない）" if peers else ""
            if not a.accept_tree_change:
                raise Reject(f"{inst['run_by']} の前後で作業ツリーが変わっている: {diff}{who}。戻してから done し直すか、自分の変更なら --accept-tree-change <理由>")
            b.state.setdefault("git_mismatches", []).append({"instance": a.node, "diff": diff, "accepted": a.accept_tree_change,
                                                            "round": b.round, "concurrent_guarded": peers})
    # 扇の被覆（返した答えが項目を全部覆っているか。欠けは『なし』ではない）
    remaining = None
    cover = n.get("fan_out", {}).get("cover")
    if cover and item:
        items = get_path({"item": item}, cover["items_at"])
        key = cover.get("key", "id")
        want = {x[key] for x in items}
        got = {x.get(key) for x in (get_path(output, cover["answers_at"]) if has_path(output, cover["answers_at"]) else [])}
        extra = got - want
        if extra:
            raise Reject(f"項目に無い {key} を返している: {sorted(extra)}")
        remaining = sorted(want - got)
    # 段の昇格（降格は engine が拒む）
    tf = n.get("thickness_from")
    if tf and has_path(output, tf):
        want = get_path(output, tf)
        if want not in b.tiers:
            raise Reject(f"段 '{want}' はこの loop の段（{b.tiers}）に無い")
        if b.tiers.index(want) < b.tiers.index(b.state["thickness"]):
            raise Reject(f"段を {b.state['thickness']} から {want} に下げようとしている。降格は依頼者の指定で init に渡す（回す側の自己判断による降格＝さぼり降格を禁ずる）")
        if b.tiers.index(want) > b.tiers.index(b.state["thickness"]):
            thicken(b, want, output.get(n.get("thickness_reason_from", ""), ""), by=nid)
    # 節ごとの整合（型では書けない規則。rules が持つ）。**out を検査・補うだけで record は触らない**——
    # 記録を書く経路は writes（WRITE_OPS）1 本。2 本あると『回す側が判定欄に書かない』柵（graphcheck は
    # writes だけを見る）が片方を覆えない。今の graph に違反は無いが、契約として狭めておく
    notes = []
    pc = n.get("post_check")
    if pc:
        fn = registry(b.rules, "POST_CHECKS").get(pc)
        if not fn:
            die(f"post_check '{pc}' が rules に無い")
        note = fn(b, nid, output, item)
        if note:
            notes.append(note)
    apply_writes(b, nid, output, item)
    check = hook(b.rules, "check_record")
    if check:
        errs = check(b)
        if errs:
            print("NG 記録の整合が取れない（役に返させ直す。回す側が補ってはいけない）:", file=sys.stderr)
            for e in errs:
                print(f"  - {e}", file=sys.stderr)
            sys.exit(1)
    f = b.dir / "out" / f"r{b.round}" / (safe_name(a.node) + ".json")
    write_json(f, output)
    if n.get("save_text_as"):
        (b.dir / n["save_text_as"]).write_text(output["text"], encoding="utf-8")
        notes.append(f"本文は {b.dir / n['save_text_as']} に保存した")
    b.state["outputs"][nid] = {"file": str(f.relative_to(b.dir)), "round": b.round, "instance": a.node}
    inst.update({"status": "done", "done_at": now(), "output_file": str(f)})
    if a.agent_id:
        inst["agent_id"] = a.agent_id
    b.trace("done", instance=a.node, sha=sha(text))
    msg = f"ok {a.node} を受け付けた"
    if remaining:
        item = dict(item)
        base = cover["items_at"].split(".", 1)[1]
        item[base] = [x for x in item[base] if x[cover.get("key", "id")] in remaining]
        k = sum(1 for i in b.rd["instances"] if i.startswith(f"{nid}[{item['key']}]"))
        new = emit_instance(b, nid, item, suffix=f"#{k + 1}")
        msg += f"。ただし答えが欠けた項目がある: {remaining}——欠けた分だけ {new['id']} として出し直した（無言の省略を『なし』と読まない）"
    if "fan_out" not in n:
        b.rd["done"][nid] = {"at": now(), "instance": a.node}
        b.state["done_ever"][nid] = b.round
    b.save()
    print("。".join([msg, *notes]) + "。続きは loop.py next")


# ---------------------------------------------------------------- skip / answer / thicken / add / patch
def cmd_skip(a):
    b = Board(resolve_dir(a))
    n = b.nodes.get(a.node)
    if not n:
        die(f"節 '{a.node}' が無い")
    if not n.get("optional"):
        raise Reject(f"節 '{a.node}' は optional でない——省けない（省略できる機構は graph の optional と段の宣言が正本）")
    if b.node_state(a.node) != "pending":
        raise Reject(f"節 '{a.node}' は {b.node_state(a.node)}")
    b.rd["skipped"][a.node] = a.reason
    for i in b.rd["instances"].values():
        if i["node"] == a.node and i["status"] == "pending":
            i["status"] = "skipped"
    b.state["done_ever"][a.node] = b.round
    b.trace("skip", node=a.node, reason=a.reason)
    b.save()
    print(f"ok {a.node} を省いた（報告の『省略した機構』に載る）")


def cmd_answer(a):
    b = Board(resolve_dir(a))
    ph = b.state.get("pending_human")
    if not ph:
        raise Reject("人に聞いている節は無い")
    ans = a.text.strip()
    if ans not in ph["options"]:
        raise Reject(f"答えは {ph['options']} のどれか")
    ph["note"] = a.note or ""
    fn = hook(b.rules, "on_answer")
    if fn:
        fn(b, ph, ans)
    b.state.pop("pending_human")
    b.trace("answer", answer=ans, kinds=ph.get("kinds"))
    if ans == "stop":
        b.state["status"] = "stopped"
    else:
        if ans == "escalate":
            # 段名は graph の thickness.tiers が正本——escalate は最上段へ
            if not b.tiers:
                raise Reject("この loop に段（thickness.tiers）が無いので escalate できない")
            thicken(b, b.tiers[-1], "依頼者の判断（諮った結果）", by="answer")
        b.new_round()
        fn2 = hook(b.rules, "on_new_round")
        if fn2:
            fn2(b)
    b.save()
    print(f"ok 答え '{ans}' を記録した。続きは loop.py next")


def thicken(b, to, reason, by):
    cur = b.state["thickness"]
    if not b.tiers or to not in b.tiers:
        raise Reject(f"段 '{to}' はこの loop の段（{b.tiers}）に無い")
    if b.tiers.index(to) <= b.tiers.index(cur):
        raise Reject(f"{cur} から {to} へは下げられない（降格は init の --thickness だけ）")
    b.state.setdefault("thickness_changes", []).append({"round": b.round, "from": cur, "to": to, "by": by, "reason": reason})
    b.state["thickness"] = to
    b.state["max_rounds"] = max_rounds_for(b.graph, to)
    fn = hook(b.rules, "on_thickness")
    if fn:
        fn(b, to)
    b.trace("thicken", to=to, by=by, reason=reason)


def max_rounds_for(graph, thickness):
    return graph["round"].get("max_rounds_by_thickness", {}).get(thickness, graph["round"]["max_rounds"])


def cmd_thicken(a):
    b = Board(resolve_dir(a))
    thicken(b, a.to, a.reason, by="thicken")
    b.save()
    print(f"ok 段を {a.to} に上げた。この周から {a.to} の節が有効になる（次の next で出る）")


def cmd_add(a):
    b = Board(resolve_dir(a))
    fn = hook(b.rules, "add")
    if not fn:
        raise Reject("このループの rules は add を受け付けない")
    msg = fn(b, read_json(a.file), a.reason)
    b.trace("add", reason=a.reason)
    b.save()
    print(f"ok {msg}")


def cmd_patch(a):
    """記録（既定）か盤面（state. 接頭）の手当て。痕跡は state.patches と trace に残る。

    盤面も許すのは、run の途中で graph と雛形が変わると rules の私有の鍵が足りずに next が止まり、
    記録側の手当てでは届かないから（実測 2026-09-12: 雛形が新しい loop_state の鍵を読み、回す側が
    state.json を手で書き換えて続けた——手当ての口が盤面の壊れ方を覆っていなかった）。
    """
    b = Board(resolve_dir(a))
    if a.path.startswith("state."):
        set_path(b.state, a.path[len("state."):], read_json(a.file))
    else:
        set_path(b.record, a.path, read_json(a.file))
    b.state.setdefault("patches", []).append({"round": b.round, "path": a.path, "reason": a.reason, "at": now()})
    b.trace("patch", path=a.path, reason=a.reason)
    b.save()
    print(f"ok {a.path if a.path.startswith('state.') else 'record.' + a.path} を手当てした（痕跡は state.patches と trace に残る）")


# ---------------------------------------------------------------- finalize / status / record
def cmd_finalize(a):
    b = Board(resolve_dir(a))
    finalize(b)
    b.save()
    v = run_validator(b)
    print(dump({"validator": v, "record": str(b.dir / "record.json")}))
    accepts = b.graph.get("record", {}).get("report_accepts_exit", [0])  # 受理集合の正本は graph（advance の report の節と同じ）
    if v["exit"] not in accepts:  # None（検証器が無い・動かない）も不合格
        sys.exit(1)


def cmd_status(a):
    b = Board(resolve_dir(a))
    st = b.state
    print(dump({
        "dir": str(b.dir), "loop": st["loop_name"], "status": st["status"], "round": b.round, "thickness": st["thickness"],
        "max_rounds": st["max_rounds"], "unattended": st["unattended"],
        "this_round": {"done": sorted(b.rd["done"]), "na": b.rd["na"], "skipped": b.rd["skipped"], "empty": b.rd["empty"],
                       "pending_instances": [i["id"] for i in b.rd["instances"].values() if i["status"] == "pending"]},
        "pending_human": st.get("pending_human"), "validator": st.get("validator"),
    }))


def cmd_record(a):
    print(dump(Board(resolve_dir(a)).record))


# ---------------------------------------------------------------- init
def resolve_dir(a):
    if getattr(a, "dir", None):
        return a.dir
    gd = git("rev-parse", "--git-dir")
    if gd:
        base = pathlib.Path(gd.strip()).resolve() / "graphloops"
        found = {}
        for p in sorted(base.glob("*/current")):
            t = p.read_text(encoding="utf-8").strip()
            if pathlib.Path(t).is_dir():
                found[p.parent.name] = t
        if len(found) > 1:
            # 別のループの run に記録が入る取り違えを黙って起こさない——曖昧なら指させる
            die("--dir が無く、current を持つループが複数ある: " + ", ".join(f"{k} → {v}" for k, v in found.items()) + "——--dir で指せ（init の出力の dir）")
        if found:
            return next(iter(found.values()))
    die("--dir が無く、current も見つからない（init したか？）")


def cmd_init(a):
    graph = a.graph or str(PLUGIN_ROOT / "graphs" / f"{a.loop}.json")
    g = read_json(graph)
    if not g.get("exec"):
        die(f"{graph}: 実行用の欄（exec: true）が無い——このグラフはまだ写しだけで、engine では回せない")
    rules = load_rules(graph, g)
    loop = g["loop"]
    run_id = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    if a.dir:
        d = pathlib.Path(a.dir)
    else:
        gd = git("rev-parse", "--git-dir")
        if not gd:
            die("git リポジトリでない。--dir で置き場を渡せ")
        d = pathlib.Path(gd.strip()).resolve() / "graphloops" / loop / run_id
    d.mkdir(parents=True, exist_ok=False)
    req = a.request
    if req.startswith("@"):
        req = pathlib.Path(req[1:]).read_text(encoding="utf-8")
    tcfg = g.get("thickness", {})
    tiers, default = tcfg.get("tiers") or [], tcfg.get("default")
    th = a.thickness or default
    if th and th not in tiers:
        die(f"段 '{th}' はこの loop の段（{tiers}）に無い")
    deciders = tcfg.get("deciders", {})
    decider = a.decider or deciders.get("default")
    if a.decider and a.decider not in deciders.values():
        die(f"--decider '{a.decider}' はこの loop の値（{sorted(deciders.values())}）に無い")
    if th and default in tiers and tiers.index(th) < tiers.index(default) and decider != deciders.get("downgrade"):
        die(f"{th} は依頼者が明示に指定した場合だけ——依頼者がそう言ったときに限り --decider {deciders.get('downgrade')} を添えて init する")
    validator = find_validator(loop, g.get("plugin"), a.validator)
    fn = hook(rules, "init_record")
    record = fn(th, decider) if fn else {}
    inputs = {"request": req, "document": str(pathlib.Path(a.document).resolve()) if a.document else None,
              "lang": a.lang or "依頼文の言語（利用者の言語）", "cwd": os.getcwd()}
    for kv in a.input or []:
        k, _, v = kv.partition("=")
        inputs[k] = v
    state = {
        "loop_name": loop, "run_id": run_id, "graph": str(pathlib.Path(graph).resolve()),
        "graph_sha": sha(pathlib.Path(graph).read_text(encoding="utf-8")),
        "created": now(), "status": "running", "round": 1, "rounds": [empty_round(1)],
        "thickness": th, "max_rounds": max_rounds_for(g, th), "unattended": bool(a.unattended),
        "inputs": inputs, "validator": validator, "outputs": {}, "done_ever": {}, "loop": {},
    }
    write_json(d / "state.json", state)
    write_json(d / "record.json", record)
    (d.parent / "current").write_text(str(d) + "\n", encoding="utf-8")
    with open(d / "trace.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps({"t": now(), "op": "init", "thickness": th, "decider": decider}, ensure_ascii=False) + "\n")
    fn = hook(rules, "on_init")
    if fn:
        b = Board(d)
        fn(b, a)
        b.save()
    print(dump({"dir": str(d), "loop": loop, "thickness": th, "thickness_decider": decider, "max_rounds": state["max_rounds"],
                "validator": validator or ("見つからない（report の前に init --validator で渡すか " + (env_root(g["plugin"]) if g.get("plugin") else "graph の plugin") + "）"),
                "overview": g.get("overview", ""), "next": f"python3 {PLUGIN_ROOT / 'scripts' / 'loop.py'} next --dir {d}"}))
