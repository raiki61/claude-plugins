"""進行——機械の節を走らせ、扇を広げ、回す側に渡す節（instance）を発行する。"""
import pathlib

from .render import FILE_CAP, Renderer
from .rules import hook, registry
from .util import die, dump, now, porcelain, read_json, safe_name, sha, write_json
from .validator import agent_def, finalize, run_validator, deliver_mode

ENGINE_PRE = ("finalize",)  # 節の pre で engine が解釈する値。graphcheck が import して綴り違いを落とす
# launch.isolated.argv の穴。engine が埋められるのはこの 5 語だけ——graphcheck が import して知らない穴と、役の定義に無い
# model / effort を静的に落とす（以前は launch_cli の die と format の KeyError でしか出なかった）
LAUNCH_HOLES = ("model", "effort", "role_file", "prompt_file", "out_path")
ITEM_INLINE = 1000  # 扇の項目のうち instance（state.json と next の出力）に残す欄の上限（文字）。超える欄は items/ のファイルにだけ置く


def launch_cli(b, inst, d):
    """道具ゼロの役は Agent ツールで起こさない——別プロセスの CLI で起こす。

    ハーネスは subagent に CLAUDE.md 階層を注入し、**それを止める設定が無い**（公式文書 code.claude.com/docs/en/sub-agents、
    2026-09-12 取得: "Explore and Plan are the only subagents that omit CLAUDE.md and git status. There is no frontmatter
    field or per-agent setting to change which agents skip them."）。実測 2026-09-12: 道具ゼロの
    cold-reader が利用者の CLAUDE.md の 1 項目を逐語で引用した——つまり「道具の不在で遮断する」は
    Agent ツール経由では成立していない。setting source ごと外せるのは CLI だけ（同日の対照実験:
    フラグ無しでは目印が見え、--setting-sources "" を付けると消えた）。

    起動の語（コマンド名・フラグ）は graph が宣言する——engine はハーネスの語彙を持たない。
    """
    spec = b.graph.get("launch", {}).get("isolated")
    if not spec:
        die(f"{inst['id']}: 道具ゼロの役 '{inst['agent_type']}' を起こすのに graph の launch.isolated が無い"
            "（Agent ツールで起こすと CLAUDE.md が注入され、遮断が名ばかりになる）")
    role = b.dir / "roles" / (safe_name(inst["agent_type"]) + ".txt")
    role.parent.mkdir(parents=True, exist_ok=True)
    role.write_text(d["body"], encoding="utf-8")
    sub = dict(zip(LAUNCH_HOLES, (d.get("model") or "", d.get("effort") or "", str(role), inst["prompt_file"], inst["out_path"])))
    for k, v in sub.items():
        if not v and any("{" + k + "}" in a for a in spec["argv"]):
            die(f"{inst['id']}: 起動に要る '{k}' が役の定義（{d['file']}）に無い")
    argv = [a.format(**sub) for a in spec["argv"]]
    # PATH を引いて絶対パスに替える（起こす時の曖昧さを 1 つ減らす）。**見つからなくても落とさない**——
    # next は計画を出す所で、起こすのは回す側の環境である。ここで die にしたら、遮断系を一度も起こさない場
    # （台本の検査・別の機械での再開・記録を読むだけの用）まで動かなくなった（実測 2026-09-12: CI の 3 OS が
    # 全部赤。手元には claude が在るので緑だった）。実際に起こせないことは、回す側が走らせた瞬間に分かる。
    import shutil  # 起動する節でだけ要る（全サブコマンドの起動に掛けない）
    resolved = shutil.which(argv[0])
    launch = {"argv": ([resolved] + argv[1:]) if resolved else argv, "stdin": inst["prompt_file"]}
    if not resolved:
        launch["missing"] = argv[0]  # この環境では起こせない。回す側と記録に見えるようにしておく
    return launch


def slim_item(item):
    """instance に残す項目——長い欄（貼る本文など）を落とした写しと、落とした欄の名前。"""
    slim, omitted = {}, []
    for k, v in item.items():
        if isinstance(v, str) and len(v) > ITEM_INLINE:
            omitted.append(k)
        else:
            slim[k] = v
    return slim, omitted


def load_item(inst):
    """instance の項目の全部（items/ のファイルが正本。無ければ instance の item）。"""
    if inst.get("item_file"):
        return read_json(inst["item_file"])
    return inst.get("item")


def agent_type_of(b, n):
    if n.get("agent_type"):
        return n["agent_type"]  # 別プラグインの agent（接頭ごと書く）
    return (b.plugin + ":" + n["run_by"]) if b.plugin else n["run_by"]


def emit_instance(b, nid, item=None, suffix=""):
    n = b.nodes[nid]
    iid = nid + (f"[{item['key']}]" if item else "") + suffix
    prompt_path = pathlib.Path(b.state["graph"]).parent / n["prompt_file"]
    try:
        tpl = prompt_path.read_text(encoding="utf-8")
    except OSError as e:
        die(f"{nid}: prompt_file が読めない: {e}")
    ctx = b.ctx(item)
    if n.get("pre") == "finalize":
        # 報告の前に記録を仕上げて検証器を回す。通らなければこの節は出さない（fail loud）
        finalize(b)
        b.save()
        v = run_validator(b)
        accepts = b.graph.get("record", {}).get("report_accepts_exit", [0])
        if v["exit"] not in accepts:  # None（検証器が無い・動かない）も不合格——検査できない run を無検査で報告に進めない
            b.trace("validator_failed", exit=v["exit"], out=v["out"])
            die(f"{nid}: 記録が検証器を通らない（exit {v['exit']}）。engine か rules か節の出力の欠陥——record.json と trace.jsonl を見て直す（手当ては loop.py patch）:\n{v['out']}", 1)
        ctx["validation"] = v
        # 生出力は {{ref:raw}}（Board.ref）だけが渡す——ctx["raw"] は両 graph のどのプロンプトからも読まれておらず、
        # 報告の next で同じ出力を 209 回読み直していた（実測 2026-09-12）
    # 道具ゼロの役は別プロセスの CLI へ標準入力で流すので、貼る先の上限が無い＝切らない（cap=None）。
    # 上限は「Agent ツールのプロンプトに貼る」経路の性質で、engine の都合でもモデルの都合でもない。
    atype = None if b.is_runner(n) else agent_type_of(b, n)
    role_def = agent_def(atype) if atype else None
    role_def_missing = None
    if atype and ":" in atype and role_def is None:
        # 「定義が読めない」を「道具を持つ役」と同じ False に潰さない——遮断系かどうかが分からないまま Agent ツール
        # 経路に倒すと、2f2c081 が閉じた CLAUDE.md 注入がそのまま戻る（launch.isolated.argv の不在は die するのに、
        # 定義の不在だけが黙って落ちていた非対称。実測 2026-09-12: 空の CLAUDE_CONFIG_DIR で p1.hygiene が mode=agent に
        # なり notes は空だった）。graph 自身の plugin の役は定義が要る（遮断系はここにしか居ない）。別 plugin の役
        # （pr-review-toolkit 等）はこの機械に入っていないことが普通にある（実測: CI には無い）——止めずに、定義が
        # 無かった事実を instance と記録に残す（渡し方は paste＝貼れば必ず届く側）。接頭の無い組み込み agent は従来どおり。
        if atype.rpartition(":")[0] == b.plugin:
            die(f"{iid}: 役 '{atype}' の定義（agents/<役>.md）が解決できない——遮断系かどうかが決まらないので起こさない"
                "（plugin の置き場・<PLUGIN>_ROOT・CLAUDE_CONFIG_DIR を確かめよ）")
        role_def_missing = f"{atype} の定義がこの環境に無い（別 plugin）。道具は不明——遮断系としては扱わない。渡し方は paste"
        b.state.setdefault("role_def_missing", []).append({"instance": iid, "round": b.round, "agent_type": atype})
    isolated = role_def is not None and role_def["tools"] == []
    runner = b.is_runner(n)
    # **上限を外す条件は「貼るか（deliver）」で、道具ゼロか（isolated）ではない。** 以前は isolated を見ていたが、
    # それは正本と相関するだけの代理だった——貼る先の上限は「Agent ツールのプロンプトに本文を貼る」経路の性質なので、
    # 役が自分でファイルを読む deliver=path と、自分の節を自分でやる runner には当たらない。代理を見ていたとき、
    # Read を持つ judge の入力だけが切られた（実測 2026-09-13: r1.minimality が 119,284→40,000、p2.diagnose が
    # 78,672→40,000、p2.history が 43,393→40,000。遮断系は 1 件も切られていない）。切られた側は自分が何を失ったか
    # 分からない（全文の置き場が本文に無い）ので、判定の質が落ちても誰も観測できなかった。
    deliver = None if runner else deliver_mode(atype, b.graph.get("deliver", {}).get("path_tools", []),
                                               tools=role_def["tools"] if role_def else None)
    # 貼る経路は「回す側でなく・遮断系でなく・deliver が paste」の 1 通りだけ。isolated を条件から落とすと、
    # 遮断系は deliver_mode が paste を返す（道具ゼロなので path_tools を持たない）ため切られる側に回る
    # ——最初にこの 3 つ目を落として台本が 2 件赤くなった（実測 2026-09-13: 45,118 バイトの本文が切られた）
    r = Renderer(ctx, n.get("reads"), ref=b.ref,
                 cap=None if (runner or isolated or deliver == "path") else FILE_CAP)
    try:
        prompt = r.render(tpl)
    except KeyError as e:
        die(f"{nid}: {e}")
    if n.get("schema"):
        prompt += "\n\n---\n返答はこの JSON Schema に合う JSON だけ（前後に文を付けない）:\n" + dump(n["schema"])
    if r.truncated:
        b.state.setdefault("truncated", []).extend(f"{iid}: {t}" for t in r.truncated)
    pfile = b.dir / "prompts" / f"r{b.round}" / (safe_name(iid) + ".md")
    pfile.parent.mkdir(parents=True, exist_ok=True)
    pfile.write_text(prompt, encoding="utf-8")
    inst = {
        "id": iid, "node": nid, "run_by": n["run_by"],
        "mode": "runner" if runner else "agent",
        "agent_type": None if runner else agent_type_of(b, n),
        "prompt_file": str(pfile), "prompt_sha": sha(prompt), "item": item, "status": "pending", "emitted_at": now(),
        "out_path": str(b.dir / "out" / f"r{b.round}" / (safe_name(iid) + ".json")),  # 返答の置き場（運び手がここへ書けば done は --output 無しで読む）
    }
    if item:
        # 項目の正本は items/ のファイル 1 つ。貼る本文はプロンプトに埋めた後なので、盤面と next の出力には長い欄を残さない
        ifile = b.dir / "items" / f"r{b.round}" / (safe_name(iid) + ".json")
        write_json(ifile, item)
        inst["item"], omitted = slim_item(item)
        inst["item_file"] = str(ifile)
        if omitted:
            inst["item_omitted"] = omitted
    if n.get("skills"):
        inst["skills"] = n["skills"]
    if not runner:
        inst["deliver"] = deliver  # path: 役が自分で読む／paste: 本文を貼る。上限を決める前に 1 度だけ引いた物を使う
        if role_def_missing:
            inst["role_def_missing"] = role_def_missing
        if isolated:  # 道具ゼロ＝遮断系。Agent ツールでは CLAUDE.md を止められない
            inst["mode"] = "cli"
            inst["launch"] = launch_cli(b, inst, role_def)
    # 同じ agent を続ける節: 前の節の instance が返した agent の id を渡す（無ければ新しい context になる旨を残す）
    same = n.get("same_context_as")
    if same and isolated:
        die(f"{iid}: 遮断系（道具ゼロ）の役に same_context_as は使えない——別プロセスは返答と共に終わり、続ける文脈が無い（graph を直せ）")
    if same:
        prior = next((i for i in b.rd["instances"].values() if i["node"] == same and i["status"] == "done"), None)
        if prior and prior.get("agent_id"):
            inst["mode"] = "agent_continue"
            inst["continue_of"] = prior["id"]
            inst["agent_id"] = prior["agent_id"]
        else:
            inst["context_lost"] = f"{same} の agent id が無い（done に --agent-id を渡していない）。新しい context で走る"
            b.state.setdefault("context_lost", []).append({"instance": iid, "round": b.round, "reason": inst["context_lost"]})
    if n["run_by"] in b.graph.get("tree_guard_roles", []):
        # 1 回の next の中では取り直さない（扇の節では項目数ぶん同じ写しを取っていた）。
        # engine は盤面のディレクトリにしか書かないので、同じ走査の中で結果は変わらない。
        snap = b.__dict__.get("_porcelain_once")
        if snap is None:
            snap = b.__dict__["_porcelain_once"] = porcelain()
        if snap is None:
            die(f"{iid}: git status が取れない——{n['run_by']} の作業ツリー保護（前後の突合）ができない場所からは回せない（リポジトリの中で next を呼べ）")
        inst["tree_before"] = snap
    b.rd["instances"][iid] = inst
    b.trace("emit", instance=iid, sha=inst["prompt_sha"])
    return inst


def fan_items(b, nid):
    fo = b.nodes[nid]["fan_out"]
    fn = registry(b.rules, "FAN_OUT").get(fo["builtin"])
    if not fn:
        die(f"fan_out.builtin '{fo['builtin']}' が rules に無い")
    return fn(b, nid)


def run_driver_node(b, nid, n, notes):
    """機械の節（rules の BUILTINS）。decision を返す節は周の遷移を起こす。
    返り値: True = 進んだ / False = 止まった（notes に理由。人に聞く番の中断もこちら——
    呼び出し側は 2 つを同じに扱うので、三値にしない）"""
    fn = registry(b.rules, "BUILTINS").get(n["builtin"])
    if not fn:
        die(f"builtin '{n['builtin']}' が rules に無い")
    out = fn(b, nid)
    f = b.dir / "out" / f"r{b.round}" / (safe_name(nid) + ".json")
    write_json(f, out)
    b.state["outputs"][nid] = {"file": str(f.relative_to(b.dir)), "round": b.round}
    b.trace("builtin", node=nid, result=out)
    # 返りは 2 つの形のどちらか——{"ok": bool, "problems": [...]} か {"decision": ...}。
    # どちらでもない返りを合格に倒さない（`ok is False` だけを失敗にしていたとき、ok の無い返りが全部 done に載った）。
    if "decision" not in out:
        if not isinstance(out.get("ok"), bool):
            die(f"builtin '{n['builtin']}' の返りが {{'ok': 真偽値}} でも {{'decision': …}} でもない: {sorted(out)}")
        if not out["ok"]:
            notes.append(f"{nid}: " + "; ".join(out.get("problems", ["通らない"])))
            return False
    def mark_done():
        b.rd["done"][nid] = {"at": now(), "builtin": n["builtin"]}
        b.state["done_ever"][nid] = b.round

    if "decision" not in out:
        mark_done()
        return True
    d = out["decision"]
    notes.append(f"{nid}: {d}——{out.get('reason', '')}")
    if d == "ask" and not b.state["unattended"]:
        # 人に聞く番——**done の印は付けない**（決着していない）。付けていたとき、次の next がこの節を再評価せず先へ
        # 進み、入口のガードで同じ報告を複製する必要が生じた。答えが stop なら cmd_answer が印を付け、continue なら周が変わる
        b.state["pending_human"] = {"node": nid, **out["ask"]}
        return False
    mark_done()
    if d == "next_round":
        b.new_round()
        fn2 = hook(b.rules, "on_new_round")
        if fn2:
            fn2(b)
    elif d == "ask":  # 無人実行（有人は上で止めている）
        b.state["pending_human"] = {"node": nid, **out["ask"]}
        fn2 = hook(b.rules, "on_unattended")
        reason = fn2(b, b.state["pending_human"]) if fn2 else "無人実行: 諮る事態に当たったので保守的に停止"
        b.state.pop("pending_human")
        b.state["status"] = "stopped"
        notes.append(f"無人実行: 停止（{reason}）")
    elif d in ("converged", "stopped"):
        b.state["status"] = d
    elif d != "continue":
        die(f"{nid}: decision '{d}' が不明")
    return True


def graph_changed(b, notes):
    """init の後に graph が編集されていたら、痕跡を残して知らせる（止めはしない——止めると直せない）。"""
    cur = sha(pathlib.Path(b.state["graph"]).read_text(encoding="utf-8"))
    if cur != b.state.get("graph_sha"):
        b.state.setdefault("graph_changes", []).append({"round": b.round, "from": b.state.get("graph_sha"), "to": cur, "at": now()})
        b.state["graph_sha"] = cur
        b.trace("graph_changed", to=cur)
        notes.append(f"graph が init の後に変わっている（sha {cur}）。痕跡は process.graph_changes")


def advance(b):
    """機械の節を走らせ、周の終わりなら次の周を開く。回す側に渡す節が出るまで（または止まるまで）進める。"""
    notes = []
    graph_changed(b, notes)
    while True:
        progressed = False
        for nid, n in b.nodes.items():
            if b.node_state(nid) != "pending":
                continue
            node_deps = b.deps_ok(nid)
            # 扇の節は instance_deps が揃えば項目を先に出してよい（pipeline——全部の checker を待たない）。
            # cond / once は節の deps が揃ってから見る。active_in だけは先に見る
            early = (not node_deps and "fan_out" in n and "instance_deps" in n and b.deps_ok(nid, "instance_deps")
                     and not (n.get("active_in") and b.state["thickness"] not in n["active_in"]))
            if not node_deps and not early:
                continue
            if node_deps:
                why = b.applicable(nid)
                if why:
                    b.rd["na"][nid] = why
                    progressed = True
                    continue
            if n["run_by"] == "driver":
                r = run_driver_node(b, nid, n, notes)
                if not r:  # 止まった（機械の節が通らない／人に聞く番）。二値——None の第 3 の値は持たない
                    return notes
                progressed = True
                continue
            if "fan_out" in n:
                items = fan_items(b, nid)
                if items or node_deps:
                    b.rd["item_counts"][nid] = len(items)  # いま分かっている項目の数（先出しの節は増えていく）
                mine = [i for i in b.rd["instances"].values() if i["node"] == nid]
                pending = [i for i in mine if i["status"] == "pending"]
                existing = {i["item"]["key"] for i in mine if i["status"] in ("pending", "done")}
                new_items = [it for it in items if it["key"] not in existing]
                for it in new_items:
                    emit_instance(b, nid, it)
                    progressed = True
                if node_deps and not new_items and not pending:
                    if mine:
                        b.rd["done"][nid] = {"at": now(), "instances": len(mine)}
                    else:
                        b.rd["empty"].append(nid)
                    b.state["done_ever"][nid] = b.round
                    progressed = True
                continue
            if not any(i["node"] == nid and i["status"] == "pending" for i in b.rd["instances"].values()):
                emit_instance(b, nid)
                progressed = True
        if not progressed:
            return notes
