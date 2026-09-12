#!/usr/bin/env python3
"""graphs/<loop>.json を機械で確かめる（標準ライブラリだけ）。

写しの形（exec の無いグラフにも効く）:
  1. 節の deps が全部実在し、循環が無い（graphlib）。同時に走らせてよい節の組（波）を出す
  2. 判定（verdict・units・claims の判定・gates）を出す節を、回す側（writer / surveyor /
     prospector / author）が run_by していない——「回す側は採点しない」の機械版。
     写すだけの節は verdict_is_copy、手順書が回す側の仕事と定める分類は
     runner_judgment_by_design（理由の文）で印を付ける
  3. 検証器（scripts/<loop>-record.py）が要求する記録の欄が、どれかの節の outputs に現れる
  4. fresh_context の節のうち forbidden_inputs を持たないものを数えて見せる（誤りではない）
  5. 段名（active_in・max_rounds_by_thickness・thickness.default）が thickness.tiers（正本）の中にある

実行の形（exec: true のグラフだけ）:
  6. run_by が回す側（graph の runners）・役割 agent（graph の plugin の agents/*.md）・driver のどれか。rules（graph の rules）が読める
  7. 回す側と役割 agent の節は prompt_file が実在し、schema か text: true を持つ
  8. プロンプトの穴（{{...}}）が全部 reads に宣言されている（遮断の機械版——宣言に無いものは貼れない）。
     out.<節> は自分より前（deps の推移閉包）の節だけ、prev.<節> は前の周の出力。fresh_context の節は record 全体を読めない
  9. 回す側の節の writes が判定の欄（claims の verdict / refuted、gates、sampling、convergence）に触れない。
     claims に merge する回す側の節は schema が additionalProperties: false で verdict / refuted を持たない
 10. writes.op・fan_out.builtin・builtin・post_check・cond.builtin が engine か rules の知っている名前だけ。
     cover・save_text_as・thickness_from・raw_for_report の指す欄と節が実在する

使い方:
    python3 graphloops/scripts/graphcheck.py graphloops/graphs/research-loop.json [scripts/research-record.py]

第 2 引数を省くと JSON の record.validator_path を、graph の plugin の置き場から探す。

終了コード: 0 = 全部通った / 1 = どれかが通らなかった / 2 = 入力が読めない
"""
import graphlib
import importlib.util
import io
import json
import pathlib
import re
import sys
from contextlib import redirect_stderr

# Windows の既定の標準出力は cp1252（日本語 Windows なら cp932）で、日本語を print すると
# UnicodeEncodeError で落ちる。リポジトリの他の出力スクリプトと同じ型に揃える。
for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8")

HERE = pathlib.Path(__file__).resolve().parent
PLUGIN_ROOT = HERE.parent


sys.path.insert(0, str(PLUGIN_ROOT))
# 穴の形・path の剥がし方・節の最長一致・cond と writes の op は engine が正本——ここに写すと engine だけ変えたとき検査が黙って緩む
from engine.board import COND_OPS, node_of  # noqa: E402
from engine.advance import ENGINE_PRE  # noqa: E402
from engine.record import ENGINE_WRITE_OPS  # noqa: E402
from engine.render import TOKEN, Renderer, strip_prefix  # noqa: E402
from engine.rules import load_rules as engine_load_rules  # noqa: E402
from engine.validator import agent_tools, find_plugin_path  # noqa: E402


def load_rules(gpath, g):
    """engine と同じ読み込み（同じ INJECT）。読めなければ NG の文を返す（engine は die するので、ここで受けて診断に変える）。"""
    if not g.get("rules"):
        return None
    buf = io.StringIO()
    try:
        with redirect_stderr(buf):
            return engine_load_rules(gpath, g)
    except SystemExit:
        return buf.getvalue().strip() or f"rules {g.get('rules')} が読めない"




def load_json(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        print(f"読めない: {path}: {e}", file=sys.stderr)
        sys.exit(2)


def record_fields(script_path):
    """検証器が要求する必須欄。**まず import して定数を読む**（engine と rules は既に同じ import をしている）。

    正規表現での抽出は、定数として export されていない欄（validate() の中の for key in (...)）のための後詰め。
    import だけに頼ると 0 件になり、0 件は『省略』でなく NG（呼び出し側がそう倒す）。
    """
    names = set()
    try:
        spec = importlib.util.spec_from_file_location("_record_mod", script_path)
        mod = importlib.util.module_from_spec(spec)
        with redirect_stderr(io.StringIO()):
            spec.loader.exec_module(mod)
        for const in ("MATERIALS", "REQUIRED"):
            names |= set(getattr(mod, const, ()) or ())
    except Exception:
        pass  # 実行できない検証器は正規表現で読む（下の後詰め）
    try:
        src = open(script_path, encoding="utf-8").read()
    except OSError as e:
        print(f"読めない: {script_path}: {e}", file=sys.stderr)
        sys.exit(2)
    for const in ("MATERIALS", "REQUIRED"):
        m = re.search(rf"^{const}\s*=\s*\((.*?)^\)", src, re.S | re.M)
        if m:
            names |= set(re.findall(r'"([a-z_]+)"', m.group(1)))
    for m in re.finditer(r"for key in \(([^)]*)\):\s*\n\s*if key not in rec", src):
        names |= set(re.findall(r'"([a-z_]+)"', m.group(1)))
    return names


def agent_names(g):
    """graph の plugin の agents/*.md から役の名前を取る。見つからなければ None（役の検査はできない）。"""
    d = find_plugin_path("agents", g.get("plugin"), kind="dir") if g.get("plugin") else None
    return {p.stem for p in pathlib.Path(d).glob("*.md")} if d else None


def ancestors(nodes, nid, seen=None):
    seen = seen if seen is not None else set()
    for d in nodes[nid].get("deps", []) + nodes[nid].get("instance_deps", []):
        if d in nodes and d not in seen:
            seen.add(d)
            ancestors(nodes, d, seen)
    return seen


COND_KEYS = {"all", "any", "not", "builtin", "path", "op", "value", "default", "field"}  # engine の eval_cond が読む鍵


def check_cond(c, where, errs, conds=frozenset()):
    if not isinstance(c, dict):
        errs.append(f"{where}: cond が object でない")
        return
    # 葉の未知キーは NG——書いても効かない宣言（綴り違い含む）が黙って無視されると、書き手は条件を宣言した
    # つもりで節が毎周走る／走らない側に固定される（実測: cond の default を engine が読まなかった）
    unknown = set(c) - COND_KEYS
    if unknown:
        errs.append(f"{where}: cond の葉に engine が読まない鍵: {sorted(unknown)}（綴り違いか、書いても効かない宣言）")
    if "all" in c or "any" in c:
        for x in c.get("all", []) + c.get("any", []):
            check_cond(x, where, errs, conds)
    elif "not" in c:
        check_cond(c["not"], where, errs, conds)
    elif "builtin" in c:
        if c["builtin"] not in conds:
            errs.append(f"{where}: cond.builtin '{c['builtin']}' が rules の CONDS に無い（{sorted(conds)}）")
    elif "path" in c:
        if c.get("op", "eq") not in COND_OPS:
            errs.append(f"{where}: cond.op '{c.get('op')}' を駆動器が知らない")
    else:
        errs.append(f"{where}: cond の形が不明: {c}")


def main():
    if len(sys.argv) not in (2, 3):
        print(__doc__, file=sys.stderr)
        sys.exit(2)
    gpath = pathlib.Path(sys.argv[1])
    g = load_json(gpath)
    nodes = g["nodes"]
    ok = True
    errs = []  # 実行の形の NG（末尾でまとめて印字）。関数の途中で作り直さない——先に溜めた分が捨てられる

    # 1. 依存の実在と波
    unknown = [(k, d) for k, v in nodes.items() for d in v.get("deps", []) + v.get("instance_deps", []) if d not in nodes]
    if unknown:
        ok = False
        for k, d in unknown:
            print(f"NG 節 {k} の deps に無い節: {d}")
    ts = graphlib.TopologicalSorter({k: set(v.get("deps", [])) for k, v in nodes.items()})
    try:
        ts.prepare()
    except graphlib.CycleError as e:
        ok = False
        print(f"NG 循環: {e}")
    else:
        waves = []
        while ts.is_active():
            ready = sorted(ts.get_ready())
            waves.append(ready)
            ts.done(*ready)
        print(f"ok  {g['loop']}: 節 {len(nodes)}・波 {len(waves)}（同じ波は同時に走らせてよい）")
        for i, w in enumerate(waves, 1):
            print(f"    波{i}: {', '.join(w)}")

    # 2. 回す側が判定を出していないか（回す側の run_by は graph の runners が正本）
    runners = g.get("runners")
    if runners is None:
        errs.append("runners（回す側の run_by の一覧）が無い——engine は役の名前を持たないので graph が宣言する")
        runners = []
    if g.get("agent_prefix"):
        errs.append("agent_prefix は廃止——plugin（役割 agent と検証器を持つ plugin の名前）を書く")
    # 判定の語彙は **graph が宣言する**（loop ごとに違う——firstread の questions は読み役の疑問で判定ではない）。
    # engine にも graphcheck にも写しを置かない: 写すと engine だけ変えたとき柵が緩み、engine に持たせると
    # 「engine は loop の語を持たない」に反する。
    VERDICT_PATHS = tuple(g.get("verdict_paths") or ())
    VERDICT_FIELDS = frozenset(g.get("verdict_fields") or ())
    if not VERDICT_PATHS and not VERDICT_FIELDS:
        errs.append("verdict_paths / verdict_fields（回す側が書いてはいけない記録の場所と欄名）が graph に無い")
    bad2 = False
    for k, v in nodes.items():
        # 判定の欄かどうかは**名前の部分一致でなく engine の語彙**（VERDICT_PATHS / VERDICT_FIELDS）から導く。
        # 正規表現の写しを持たせていたとき、その語に当たらない命名の判定欄は素通りした（柵の対象集合が名乗りより狭い）。
        outs = v.get("outputs", [])
        judges = [o for o in outs
                  if any(o == p or o.startswith(p + ".") for p in VERDICT_PATHS)
                  or o.rsplit(".", 1)[-1] in VERDICT_FIELDS]
        if v.get("run_by") not in runners or not judges or v.get("verdict_is_copy"):
            continue
        if v.get("runner_judgment_by_design"):
            print(f"ok  節 {k}: 回す側が判定するのは設計どおり——{v['runner_judgment_by_design']}")
            continue
        ok, bad2 = False, True
        print(f"NG 節 {k}: 回す側（{v['run_by']}）が判定を出している: {judges}")
    if not bad2:
        print("ok  判定を出す節に回す側が無い（verdict_is_copy は写すだけ、runner_judgment_by_design は手順書が定めた例外）")

    # 3. 記録の欄 ⊆ outputs
    script = sys.argv[2] if len(sys.argv) == 3 else None
    vp = g.get("record", {}).get("validator_path")
    if not script and vp:
        script = find_plugin_path(vp, g.get("plugin"))  # engine と同じ探し方（明示 → <PLUGIN>_ROOT → 同じリポジトリ → キャッシュ）
        if not script:
            ok = False
            print(f"NG record.validator_path '{vp}' が見つからない（plugin {g.get('plugin')!r} の置き場に無い。第 2 引数で渡すか置き場を直す）——欄の突合を省略で通さない")
    if script:
        need = record_fields(script)
        if not need:
            ok = False
            print(f"NG 検証器 {script} から必須欄が 1 つも拾えない（書式が変わったか、検証器でない）——0 個の突合を合格にしない")
        else:
            have = " ".join(o for v in nodes.values() for o in v.get("outputs", []))
            missing = sorted(n for n in need if not re.search(rf"\b{re.escape(n)}\b", have))
            if missing:
                ok = False
                print(f"NG 検証器の欄で outputs に無いもの: {', '.join(missing)}")
            else:
                print(f"ok  検証器の必須欄 {len(need)} 個すべてがどれかの節の outputs に現れる")
    elif not vp:
        print("--  検証器の欄との突合は省略（graph に record.validator_path が無く、第 2 引数も無い）")

    # 4. fresh_context と forbidden_inputs
    fresh = [k for k, v in nodes.items() if v.get("fresh_context")]
    bare = [k for k in fresh if not nodes[k].get("forbidden_inputs")]
    print(f"ok  fresh_context {len(fresh)} 節、うち固有の遮断（forbidden_inputs）を持たないのは "
          f"{len(bare)}（ラウンド規律だけが効く）: {', '.join(bare) or 'なし'}")

    # 5. 段名の正本は thickness.tiers（低い順の配列）。キーの集合から導かない——tiers / deciders / rule が段名として通る
    th = g.get("thickness", {})
    tiers = th.get("tiers") or []
    uses_tiers = any(v.get("active_in") or v.get("thickness_from") for v in nodes.values()) or g.get("round", {}).get("max_rounds_by_thickness")
    bad5 = False
    if not isinstance(tiers, list) or not all(isinstance(t, str) for t in tiers):
        ok, bad5 = False, True
        print("NG thickness.tiers は段名の配列（低い順）")
        tiers = []
    if uses_tiers and not tiers:
        ok, bad5 = False, True
        print("NG 段（active_in / thickness_from / max_rounds_by_thickness）を使うのに thickness.tiers（低い順）が無い")
    if tiers:
        for k, v in nodes.items():
            bad = [t for t in v.get("active_in", []) if t not in tiers]
            if bad:
                ok, bad5 = False, True
                print(f"NG 節 {k} の active_in に無い段: {bad}（段は {tiers}）")
        for t in g.get("round", {}).get("max_rounds_by_thickness", {}):
            if t not in tiers:
                ok, bad5 = False, True
                print(f"NG max_rounds_by_thickness の段 '{t}' が thickness.tiers に無い")
        if th.get("default") not in tiers:
            ok, bad5 = False, True
            print(f"NG thickness.default '{th.get('default')}' が tiers に無い")
        if not bad5:
            print(f"ok  段名は thickness.tiers {tiers} の中（active_in・max_rounds_by_thickness・default）")

    if not g.get("exec"):
        print("--  exec の無いグラフ（写しだけ）。実行の形の検査 6〜10 は省略")
        sys.exit(0 if ok else 1)

    # 6〜10. 実行の形
    agents = agent_names(g)
    if agents is None:
        errs.append(f"役割 agent の定義（agents/）が見つからない: plugin {g.get('plugin')!r}——graph に plugin を書き、その plugin が同じリポジトリかキャッシュか <PLUGIN>_ROOT に在ること")
        agents = set()
    dl = g.get("deliver", {}).get("path_tools")
    if dl is not None and not (isinstance(dl, list) and all(isinstance(t, str) for t in dl)):
        errs.append("deliver.path_tools は道具の名前の一覧")
    # 道具ゼロの役（遮断系）を使うなら、起こし方の宣言が要る。Agent ツールで起こすとハーネスが
    # CLAUDE.md 階層を注入し、止める設定が公式に無い——遮断が名ばかりになる（実測 2026-09-12）。
    isolated = sorted(r for r in agents if agent_tools(f"{g.get('plugin')}:{r}") == [])
    used = {v.get("run_by") for v in nodes.values()} | {v.get("agent_type", "").rpartition(":")[2] for v in nodes.values()}
    if isolated and (used & set(isolated)) and not (g.get("launch", {}).get("isolated", {}).get("argv")):
        errs.append(f"道具ゼロの役 {sorted(used & set(isolated))} を使うのに launch.isolated.argv が無い"
                    "——Agent ツールで起こすと CLAUDE.md が注入され、遮断が成立しない")
    rules = load_rules(gpath, g)
    if isinstance(rules, str):
        errs.append(rules)
        rules = None
    reg = lambda name: set(getattr(rules, name, {}) or {}) if rules else set()
    write_ops = set(ENGINE_WRITE_OPS) | reg("WRITE_OPS")
    fan_builtins, node_builtins, post_checks, conds = reg("FAN_OUT"), reg("BUILTINS"), reg("POST_CHECKS"), reg("CONDS")
    for nid in g.get("raw_for_report", []):
        if nid not in nodes:
            errs.append(f"raw_for_report に無い節: {nid}")
    for k, v in nodes.items():
        rb = v.get("run_by")
        if rb not in runners and rb not in agents and rb not in ("driver", "skill") and not v.get("agent_type"):
            errs.append(f"節 {k}: run_by '{rb}' が回す側でも役割 agent（{sorted(agents)}）でも driver / skill でもなく、agent_type の上書きも無い")
        if rb == "skill" and not v.get("skills"):
            errs.append(f"節 {k}: run_by が skill なのに skills（呼ぶ skill の一覧）が無い")
        same = v.get("same_context_as")
        if same and (same not in nodes or same not in ancestors(nodes, k)):
            errs.append(f"節 {k}: same_context_as '{same}' が前の節でない")
        if rb == "driver":
            if v.get("builtin") not in node_builtins:
                errs.append(f"節 {k}: builtin '{v.get('builtin')}' が rules の BUILTINS に無い")
            continue
        pf = v.get("prompt_file")
        if not pf or not (gpath.parent / pf).is_file():
            errs.append(f"節 {k}: prompt_file が無い（{pf}）")
            continue
        if not v.get("schema") and not v.get("text"):
            errs.append(f"節 {k}: schema も text: true も無い（返答の形が決まらない）")
        if v.get("save_text_as") and not v.get("text"):
            errs.append(f"節 {k}: save_text_as は text: true の節だけ")
        tf = v.get("thickness_from")
        if tf and tf not in v.get("schema", {}).get("properties", {}):
            errs.append(f"節 {k}: thickness_from '{tf}' が schema に無い")
        reads = v.get("reads")
        if reads is None:
            errs.append(f"節 {k}: reads が無い（貼ってよいものを宣言しろ。宣言に無い穴は engine が埋めない）")
            reads = []
        if v.get("fresh_context") and "record" in reads:
            errs.append(f"節 {k}: fresh_context なのに record 全体を読む（判定と見立てが丸ごと渡る）")
        anc = ancestors(nodes, k)
        tpl = (gpath.parent / pf).read_text(encoding="utf-8")
        for m in TOKEN.finditer(tpl):
            path = m.group(2).strip()
            core = strip_prefix(path)
            if path.startswith("ref:") and not (core == "record" or core.startswith("record.") or core == "raw"
                                                or core.startswith("out.") or core.startswith("prev.")):
                errs.append(f"節 {k}: {{{{{path}}}}} は ref: にできない（record・out.<節>・prev.<節>・raw だけ）")
            # 許可の判定は engine の Renderer を呼ぶ（式を写すと engine だけ変えたとき検査が黙って緩む）
            if not Renderer({}, reads).allowed(path):
                errs.append(f"節 {k}: プロンプトの穴 {{{{{path}}}}} が reads に無い")
            if core.startswith("out."):
                src = node_of(core[4:], nodes)
                if src is None or src not in anc:
                    errs.append(f"節 {k}: {core} を読むが、その節は前の節（deps の推移閉包）でない（前の周の出力なら prev.<節>）")
            if core.startswith("prev.") and node_of(core[5:], nodes) is None:
                errs.append(f"節 {k}: {core} の節が無い")
        for r in reads:
            if r.startswith("out."):
                src = node_of(r[4:], nodes)
                if src is None or src not in anc:
                    errs.append(f"節 {k}: reads の {r} は前の節でない（前の周の出力なら prev.<節>）")
            if r.startswith("prev.") and node_of(r[5:], nodes) is None:
                errs.append(f"節 {k}: reads の {r} の節が無い")
        for w in v.get("writes", []):
            op = w.get("op")
            if op not in write_ops:
                errs.append(f"節 {k}: writes.op '{op}' を engine も rules も知らない")
            if "stamp_round" in w and not (isinstance(w["stamp_round"], str) and w["stamp_round"]):
                errs.append(f"節 {k}: writes.stamp_round は周を書き込む欄の名前（文字列）——append でも merge_by_id でも同じ意味")
            to = w.get("to", "")
            if rb in runners:
                if any(to == p or to.startswith(p + ".") for p in VERDICT_PATHS) or op == "cold_reader_round":
                    errs.append(f"節 {k}: 回す側が判定の欄 '{to or op}' に書いている")
                if to == "claims" and op == "merge_by_id":
                    fields = w.get("fields")
                    if fields and VERDICT_FIELDS & set(fields):
                        errs.append(f"節 {k}: 回す側が claims の判定欄に書いている: {sorted(VERDICT_FIELDS & set(fields))}")
                    if not fields:
                        item = v.get("schema", {}).get("properties", {}).get(w.get("from", ""), {}).get("items", {})
                        if item.get("additionalProperties") is not False or VERDICT_FIELDS & set(item.get("properties", {})):
                            errs.append(f"節 {k}: 回す側が claims に merge する schema が判定欄を通しうる（additionalProperties: false で verdict / refuted を持たない形にしろ）")
                if w.get("const") and VERDICT_FIELDS & set(w["const"]):
                    errs.append(f"節 {k}: 回す側が const で判定欄を書いている")
        fo = v.get("fan_out")
        if fo:
            if fo.get("builtin") not in fan_builtins:
                errs.append(f"節 {k}: fan_out.builtin '{fo.get('builtin')}' が rules の FAN_OUT に無い")
            cov = fo.get("cover")
            if cov and not (cov.get("items_at", "").startswith("item.") and cov.get("answers_at")):
                errs.append(f"節 {k}: fan_out.cover は items_at（item. で始まる）と answers_at が要る")
        if "instance_deps" in v and "cond" in v:
            errs.append(f"節 {k}: instance_deps と cond は同時に持てない（項目を先に出すとき cond を評価できない）")
        if v.get("post_check") and v["post_check"] not in post_checks:
            errs.append(f"節 {k}: post_check '{v['post_check']}' が rules の POST_CHECKS に無い")
        if "cond" in v:
            check_cond(v["cond"], f"節 {k}", errs, conds)
        if "applies_cond" in v:
            check_cond(v["applies_cond"], f"節 {k}.applies_cond", errs, conds)
        # pre は『報告の前に記録を仕上げて検証器を回す』唯一の門。綴り違いは検証器を通さずに報告を出す形になる
        if "pre" in v and v["pre"] not in ENGINE_PRE:
            errs.append(f"節 {k}: pre '{v['pre']}' を engine が知らない（使えるのは {'/'.join(ENGINE_PRE)}）")
    if errs:
        ok = False
        for e in errs:
            print("NG " + e)
    else:
        print("ok  実行の形: run_by・prompt_file・schema・reads（穴の宣言と前の節だけ）・回す側は判定欄に書かない・名前は engine か rules にある")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
