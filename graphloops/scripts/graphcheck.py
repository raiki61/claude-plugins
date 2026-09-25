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
     out.<節> は自分より前（deps の推移閉包）の節だけ、prev.<節> は前の周の出力。fresh_context の節は record 全体を読めない。
     回す側の節には本文を貼る穴（file: / section:）を書けない——回す側はファイルを読めるので、渡すのはパス
     （見るのは run_by が runners の節だけ。Read を持つ役割 agent の節は対象外）。record.<欄> の穴は、12 の条件の読みと
     同じく記録を書く宣言に在ること（rules が読めない回は照らさない）
  9. 回す側の節の writes が判定の欄（claims の verdict / refuted、gates、sampling、convergence）に触れない。
     claims に merge する回す側の節は schema が additionalProperties: false で verdict / refuted を持たない
 10. writes.op・fan_out.builtin・builtin・post_check・cond / applies_cond（skills[].applies_cond も）が engine か rules の知っている名前だけ。
     cover・save_text_as・thickness_from・raw_for_report の指す欄と節が実在する
 11. schema が engine の読む語（engine/schema.py の KNOWN_KEYWORDS）だけで書かれている——読まない語は書いても効かない
 12. engine が実行に使う欄が宣言どおりの物を指す: writes.from が節の schema.properties に在る、cond / applies_cond の
     関数が宣言した読む欄（cond_reads）と節の reads・outputs の loop.<鍵> が実在する（out./prev./cur. は節の schema、loop. は
     rules の LOOP_KEYS、rd. は周の鍵、record. は記録を書く宣言）、same_context_as の役が一致し遮断系でない、
     report_accepts_exit / round_accepts_exit が整数、pre が engine の知る名前、launch.isolated / launch.tooled / launch.delegate の argv・resume・via の
     穴が engine の埋める語（LAUNCH_HOLES）だけで、resume は {session_id} を持ち、model / effort は遮断系の役の定義に在り、
     via が指す実体が同梱されている、resume_on_reject が 0 以上の整数
 13. graph の enum が検証器の語彙（大文字の定数）の写しからはみ出していない（重なる表のどれかに丸ごと含まれる）
 14. 回す側の任せ先（delegate）: delegate は回す側の節にだけ・skills を持つ節には書けない（入れ子の委任）。
     走らせるだけの節（engine_run）は回す側の節にだけ・名前が rules の ENGINE_RUNS に在り plan と reply を持つ。
     background（任せ先を背景で立てて待たずに受領を返す）は真偽で、背景の節をほかの節が待たない（deps・instance_deps）。
     {{node.<欄>}} は engine が埋める欄（skills）だけ
     背景の節は delegate.result_to に返答の置き場（reads のどれか）を名指しし、delegate を持つ節が在れば launch.delegate.argv が在る。

この一覧は人向けの案内。検査の本体と実行時の見出し（「検査 6〜13」等）は main() の側が正本で、番号を足したらここも直す。

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
from engine.board import COND_HEADS, COND_NODE_HEADS, empty_round, node_of  # noqa: E402
from engine.advance import ENGINE_PRE, LAUNCH_HOLES  # noqa: E402
from engine.record import ENGINE_WRITE_OPS  # noqa: E402
from engine.schema import extends_path, end_anchored, load_graph, unknown_keywords, walk_schema  # noqa: E402
DELEGATE_MODELS = ("haiku", "sonnet", "opus", "fable", "inherit")   # この graph が任せ先に書ける名前: Claude Code の subagent の model の別名
# （https://code.claude.com/docs/en/sub-agents）。完全な model ID も Agent ツールは受けるが、版が変わると古くなるので graph には書かない
from engine.commands import CLI_FLAGS, INPUT_KINDS  # noqa: E402 — 入力の語彙は engine が正本（写さない）
from engine.render import TOKEN, Renderer, node_prompt, strip_prefix  # noqa: E402
from engine.rules import HOOKS, load_rules as engine_load_rules, registry  # noqa: E402
from engine.validator import ENGINE_ACCEPT_KEYS, agent_def, agent_tools, find_plugin_path  # noqa: E402
from engine.util import read_json  # noqa: E402


def schema_patterns(schema):
    """schema の中の正規表現（pattern の値と patternProperties の鍵）を全部——木の走査は engine の walk_schema 1 本"""
    return [x for _, s in walk_schema(schema) for x in ([s["pattern"]] if isinstance(s.get("pattern"), str) else [])
            + list((s.get("patternProperties") or {}))]



# JSON の読み込みは engine の read_json（読めなければ die＝exit 2）。写しを持っていたとき UnicodeDecodeError を
# 落としていて、docstring が定める終了コード契約（2）を外れ exit 1＋Traceback になった（実測 2026-09-12）
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




_VALIDATORS = {}


def load_validator(script_path):
    """検証器を import する（engine と同じ契約）。読めなければ NG（exit 2）——正規表現の後詰めで合格に倒さない。
    SystemExit も捕まえて診断を捨てない（検証器が import 時に sys.exit(2) すると except Exception を素通りし、
    redirect_stderr に捕られた診断文だけが消えて標準エラー 0 バイトで落ちた——実測 2026-09-13）。"""
    if script_path in _VALIDATORS:  # 1 回の実行で 2 度 import しない（validator_vocab と record_fields が同じ物を読む）
        return _VALIDATORS[script_path]
    buf = io.StringIO()
    try:
        spec = importlib.util.spec_from_file_location("_record_mod", script_path)
        mod = importlib.util.module_from_spec(spec)
        with redirect_stderr(buf):
            spec.loader.exec_module(mod)
        _VALIDATORS[script_path] = mod
        return mod
    except KeyboardInterrupt:
        raise
    except BaseException as e:
        print(f"NG 検証器 {script_path} が import できない（engine は import を契約にしているので、読めない検証器は合格にできない）: "
              f"{type(e).__name__}: {e} {buf.getvalue().strip()}", file=sys.stderr)
        sys.exit(2)


def validator_vocab(script_path):
    """検証器の語彙——大文字名の tuple / list / dict（鍵）で要素が全部 str の物。graph の enum がここからはみ出せば写しがずれている。"""
    mod = load_validator(script_path)
    out = {}
    for name in dir(mod):
        if not name.isupper():
            continue
        v = getattr(mod, name)
        vals = list(v.keys()) if isinstance(v, dict) else list(v) if isinstance(v, (tuple, list)) else None
        if vals and all(isinstance(x, str) for x in vals):
            out[name] = set(vals)
    return out


def record_fields(script_path):
    """検証器が要求する必須欄。**まず import して定数を読む**（engine と rules は既に同じ import をしている）。

    正規表現での抽出は、定数として export されていない欄（validate() の中の for key in (...)）のための後詰め。
    import だけに頼ると 0 件になり、0 件は『省略』でなく NG（呼び出し側がそう倒す）。
    """
    names = set()
    mod = load_validator(script_path)
    for const in ("MATERIALS", "REQUIRED"):
        names |= set(getattr(mod, const, ()) or ())
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


def unused_reads(nid, node, holes):
    """`reads` に在るのに、その節のプロンプトのどの穴も使っていない欄を落とす。

    **`reads` は貼ってよい物の許可表であって、配り口ではない。** 穴が無ければ値は役に届かない。
    以前は「穴 ⊆ reads」の片方向しか見ていなかったので、宣言だけ在って誰にも届いていない欄が
    静的にも実行時にも赤くならなかった（実測 2026-09-16: prev.r1.minimality・prev.r3.coherence・
    prev.r4.hidden_scope の 6 件。前の周の独立の目の判定は、次の周の判定者にも直す手にも
    1 度も渡っていなかった。そこへ「前の周の R1 の where を逐語で写せ」と課す柵を足したので、
    削除候補が 1 件でも出た run は 2 周目の P2 が永久に通らなくなるところだった）。
    """
    errs = []
    for r in node.get("reads") or []:
        if not any(h == r or h.startswith(r + ".") or h.split(":")[-1].startswith(r) for h in holes):
            errs.append(f"節 {nid}: reads の '{r}' を使う穴が prompt_file に無い——"
                        "reads は許可表であって配り口ではないので、この欄は役に届かない（穴を書くか reads から落とせ）")
    return errs


SKILL_KEYS = {"skill", "args", "note", "required", "applies_cond"}


def skills_shape(nid, skills):
    """`skills` の 1 要素は SKILL_KEYS の欄を持つ dict。**名前を独立の欄にするための型。**

    以前は「/simplify（指摘だけ）」のような名前＋条件の散文 1 本で、宣言と返答を突き合わせるには
    誰も決めていない正規化規則が要り、その規則自体が新しい未定義物になっていた（実測 2026-09-15:
    宣言 `/simplify（指摘だけ）` に対し返答の綴りは 4 本に分裂した）。欄を割れば照合の両側が
    同じ文字列になる——engine は `{{node.skills}}` で正典をそのまま役へ渡し、post_check は
    同じ配列の `skill` を数える。当てる条件は `applies_cond`（rules の条件の関数の名前）、効力段のような引数は `args` へ分ける。
    """
    if skills is None:
        return []
    if not isinstance(skills, list) or not skills:
        return [f"節 {nid}: skills は空でない配列"]
    errs, seen = [], set()
    for i, e in enumerate(skills):
        if not isinstance(e, dict):
            errs.append(f"節 {nid}: skills[{i}] は {{skill, args, note, required, applies_cond}} の object（散文 1 本は不可——名前を独立の欄にする型）: {e!r}")
            continue
        extra = sorted(set(e) - SKILL_KEYS)
        if extra:
            errs.append(f"節 {nid}: skills[{i}] に知らない欄: {extra}（使えるのは {sorted(SKILL_KEYS)}）")
        name = e.get("skill")
        if not isinstance(name, str) or not name.strip():
            errs.append(f"節 {nid}: skills[{i}] に skill（名前）が無い")
            continue
        if name != name.strip():
            errs.append(f"節 {nid}: skills[{i}].skill の前後に空白: {name!r}（照合の両側が同じ文字列でなくなる）")
        if name in seen:
            errs.append(f"節 {nid}: skills に同じ skill が 2 回: {name}（1 本につき findings の行 1 本を数えるので重複は数えられない）")
        seen.add(name)
        for f in ("args", "note"):
            if f in e and not isinstance(e[f], str):
                errs.append(f"節 {nid}: skills[{i}].{f} は文字列")
        # **required は省けない。** 「在るときの型」だけ見ていたので、欄を省いた要素が静的にも実行時にも
        # 通り、既定値は graph・graphcheck・prompt・docs のどこにも宣言されていなかった——真偽値の
        # 2 値のうちどちらでもない 3 つ目の状態が表現できていた（実測 2026-09-16）。
        if "required" not in e:
            errs.append(f"節 {nid}: skills[{i}]（{name}）に required が無い——既定値はどこにも宣言されていないので省けない")
        elif not isinstance(e["required"], bool):
            errs.append(f"節 {nid}: skills[{i}].required は真偽値")
        # 両向きにする理由: 片向きだと、条件を持たない false の要素がまた散文の読みで当てるかを決める形に戻る。名前と読む欄は節の cond と同じ所で見る
        elif e["required"] != ("applies_cond" not in e):
            errs.append(f"節 {nid}: skills[{i}]（{name}）は required: false と applies_cond を対で持つ"
                        "（当てない周を決めるのは条件の関数だけ。required: true に条件は書けない）")
        if "applies_cond" in e and not isinstance(e["applies_cond"], str):
            errs.append(f"節 {nid}: skills[{i}].applies_cond は文字列（rules の CONDS の名前）")
    return errs


def ancestors(nodes, nid, seen=None):
    seen = seen if seen is not None else set()
    for d in nodes[nid].get("deps", []) + nodes[nid].get("instance_deps", []):
        if d in nodes and d not in seen:
            seen.add(d)
            ancestors(nodes, d, seen)
    return seen




def _record_ok(rest, g, rules):
    """記録の欄 rest（record. を剥いだ path）を、記録を書く宣言で照らす。**前方一致で丸ごと通さない**:
    - init_record の欄（入れ子も）・rules の RECORD_KEYS（writes の外で書く欄）は完全一致か、その親（入れ物）を読むときだけ
    - 節の writes.to の下を読むなら、下の最初の欄がその write の pick に在るか、from が指す schema の properties に在ること
    以前の JSON の条件の検査は record. の葉を見ておらず、record.reviews.R2.stauts のような綴り違いは回すまで分からなかった"""
    exact = set()

    def walk(obj, pre):
        for k, v in obj.items():
            exact.add(pre + k)
            if isinstance(v, dict):
                walk(v, pre + k + ".")
    init = getattr(rules, "init_record", None)
    if callable(init):
        try:
            walk(init(None, None) or {}, "")
        except Exception:  # noqa: BLE001 — 段の既定値を要る init_record は候補を出さない（writes.to と RECORD_KEYS が残る）
            pass
    exact |= set(getattr(rules, "RECORD_KEYS", ()) or ())
    for n in g["nodes"].values():
        for w in n.get("writes") or []:
            if not (isinstance(w, dict) and isinstance(w.get("to"), str)):
                continue
            to = w["to"]
            exact.add(to)
            if not rest.startswith(to + "."):
                continue
            first = rest[len(to) + 1:].split(".")[0]
            if w.get("pick"):
                if first in w["pick"]:
                    return True
                continue
            sch = n.get("schema") or {}
            frm = w.get("from")
            if frm and frm != "$":
                sch = (sch.get("properties") or {}).get(frm.split(".")[0]) or {}
            if first in (sch.get("properties") or {}):
                return True
    return any(rest == c or c.startswith(rest + ".") for c in exact)


def check_read_path(path, where, g, rules, errs, before=None):
    """条件（と節の reads）が読む欄 path を、実行の前に照らす。out.<節>.<欄>・prev.<節>.<欄>・cur.<節>.<欄> は節と欄
    （schema.properties）が実在し、before（条件を持つ節の deps の推移閉包）が在れば out.・cur. はその中の節だけ。loop.<鍵> は
    rules の LOOP_KEYS、rd.<鍵> は engine の周の鍵か rules の ROUND_KEYS、record.<欄> は記録を書く宣言（_record_ok）"""
    nodes = g["nodes"]
    head, _, rest = path.partition(".")
    if head not in COND_HEADS:
        errs.append(f"{where}: 読む欄 '{path}' の頭が条件の文脈に無い（使えるのは {'/'.join(COND_HEADS)}）")
    elif head in COND_NODE_HEADS:
        ref = node_of(rest, nodes)
        if ref is None:
            errs.append(f"{where}: 読む欄 '{path}' の節が無い")
            return
        field = rest[len(ref) + 1:].split(".")[0] if len(rest) > len(ref) else ""
        props = (nodes[ref].get("schema") or {}).get("properties")
        if field and props and field not in props:
            errs.append(f"{where}: 読む欄 '{path}' の欄 '{field}' が節 {ref} の schema に無い（綴り違いか、書いても効かない）")
        if head != "prev" and before is not None and ref not in before:
            errs.append(f"{where}: {head}.{ref} を読むが、{ref} はこの節の前（deps の推移閉包）に無い——評価の時点で今の周の出力が在る保証が無い")
    elif head == "loop":
        keys = getattr(rules, "LOOP_KEYS", None)
        if keys is None:
            errs.append(f"{where}: loop.{rest} を読むが、rules が LOOP_KEYS（盤面の loop の鍵の宣言）を持たない")
        elif rest.split(".")[0] not in keys:
            errs.append(f"{where}: 読む欄 '{path}' の鍵が rules の LOOP_KEYS に無い（綴り違いか、誰も書かない鍵）")
    elif head == "rd":
        if rest.split(".")[0] not in set(empty_round(0)) | set(getattr(rules, "ROUND_KEYS", ()) or ()):
            errs.append(f"{where}: 読む欄 '{path}' の鍵が周の鍵（engine の empty_round と rules の ROUND_KEYS）に無い")
    elif head == "record":
        if not rest or not _record_ok(rest, g, rules):
            errs.append(f"{where}: 読む欄 '{path}' を書く宣言が無い（init_record・節の writes.to と pick / schema・rules の RECORD_KEYS）")
    elif rest:
        errs.append(f"{where}: 読む欄 '{path}'——{head} は値そのもの（下に欄を持たない）")


def check_declared_reads(fn, name, where, g, rules, errs, nid=None):
    """条件の関数が宣言した読む欄（cond_reads）を 1 本ずつ check_read_path で照らす"""
    reads = getattr(fn, "reads", None)
    if not isinstance(reads, tuple) or not all(isinstance(r, str) and r for r in reads):
        errs.append(f"{where}: cond '{name}' が読む欄を宣言していない（rules で cond_reads(...) を付けよ）")
        return
    before = ancestors(g["nodes"], nid) if nid else None
    for path in reads:
        check_read_path(path, f"{where}（cond '{name}'）", g, rules, errs, before)


def dropped(base, merged, path=""):
    """base に在って merged に無い物（object の鍵・配列の要素）を入れ子まで辿って列挙する。値（文字列・数・真偽）の差し替えは数えない"""
    if isinstance(base, dict):
        if not isinstance(merged, dict):
            return [f"{path or '節'} を object でない値に差し替えた"]
        return [w for k, v in base.items()
                for w in ([f"{path + '.' if path else ''}{k} を消した"] if k not in merged else dropped(v, merged[k], f"{path + '.' if path else ''}{k}"))]
    if isinstance(base, list):
        got = merged if isinstance(merged, list) else []
        lost = [x for x in base if x not in got]
        return [f"{path} を落とした: {lost}"] if lost else []
    return []


def check(gpath, script=None, emit=print):
    """graph を静的に検査して ok を返す（graphcheck の本体。engine の init もここを呼ぶ）。

    **入口を 2 つにしても実装は 1 つ。** 以前は検査が CLI にしか無く、engine は init で graph を
    受け取っても何も確かめなかった——同梱のグラフだけが守られ、--graph で渡した任意のグラフは
    素通りした。呼ぶ側が増えても正本を増やさないよう、CLI も engine もこの関数を呼ぶ。
    """
    gpath = pathlib.Path(gpath)
    g, why = load_graph(gpath)
    if why:
        emit(f"NG {why}")
        return False
    nodes = g["nodes"]
    ok = True
    errs = []  # 実行の形の NG（末尾でまとめて印字）。関数の途中で作り直さない——先に溜めた分が捨てられる
    # **差し替えの版（extends）は、元の節から何も落とさない**——足すか、値（文字列・数・真偽）を差し替えるだけ。重ね方
    # （RFC 7396）は配列を置き換え、null で鍵を消し、入れ子の object を上書きできるので、元の graph に後から足した依存・読む欄・
    # 書き先・schema の必須の欄が、差し替えの版の古い一覧で黙って消える。節と、節の中の入れ子の全部を辿って見る
    # 見るのは節の下だけでなく graph の全体（最上位の配列・$defs の schema の required・inputs の宣言も、同じ重ね方で消えうる）
    base_path = extends_path(gpath, read_json(gpath))
    if base_path is not None:
        base_g, _ = load_graph(base_path)
        errs += [f"差し替えの版が元の {base_path.name} の {w}"[:300] for w in dropped(base_g or {}, g)]

    # 1. 依存の実在と波
    unknown = [(k, d) for k, v in nodes.items() for d in v.get("deps", []) + v.get("instance_deps", []) if d not in nodes]
    if unknown:
        ok = False
        for k, d in unknown:
            emit(f"NG 節 {k} の deps に無い節: {d}")
    ts = graphlib.TopologicalSorter({k: set(v.get("deps", [])) for k, v in nodes.items()})
    try:
        ts.prepare()
    except graphlib.CycleError as e:
        ok = False
        emit(f"NG 循環: {e}")
    else:
        waves = []
        while ts.is_active():
            ready = sorted(ts.get_ready())
            waves.append(ready)
            ts.done(*ready)
        emit(f"ok  {g['loop']}: 節 {len(nodes)}・波 {len(waves)}（同じ波は同時に走らせてよい）")
        for i, w in enumerate(waves, 1):
            emit(f"    波{i}: {', '.join(w)}")

    # 2. 回す側が判定を出していないか（回す側の run_by は graph の runners が正本）
    runners = g.get("runners")
    if runners is None:
        errs.append("runners（回す側の run_by の一覧）が無い——engine は役の名前を持たないので graph が宣言する")
        runners = []
    if g.get("agent_prefix"):
        errs.append("agent_prefix は廃止——plugin（役割 agent と検証器を持つ plugin の名前）を書く")
    # **入力の宣言は graph が正本、kind の語彙は engine が正本。** 写しを置かず import で縛る
    # （engine に名前の表を持たせていたとき、loop を足す人が engine を書き換える形になっていた）。
    # 知らない kind は黙って「パスでない」に倒れる＝実在検査から静かに外れるので、ここで止める。
    declared = g.get("inputs")
    if declared is None:
        errs.append("inputs（どの入力がパスかの宣言）が無い——engine は loop の入力名を持たないので graph が宣言する")
        declared = {}
    elif not isinstance(declared, dict):
        errs.append("inputs は 名前 → {kind: …} の辞書")
        declared = {}
    for key, decl in declared.items():
        kind = (decl or {}).get("kind") if isinstance(decl, dict) else None
        if kind not in INPUT_KINDS:
            errs.append(f"inputs.{key} の kind '{kind}' を engine が知らない（使えるのは {'/'.join(INPUT_KINDS)}）"
                        "——知らない kind は実在検査から黙って外れる")
        vals = decl.get("values") if isinstance(decl, dict) else None
        if kind == "choice" and not (isinstance(vals, list) and vals and all(isinstance(v, str) and v for v in vals)):
            errs.append(f"inputs.{key} は choice なのに values（選べる値の空でない文字列の配列）が無い——init が値を確かめられない")
    # **貼る穴に渡る入力は、必ず kind を宣言する。** 実在検査の発火条件を『file: の接頭』から
    # 『inputs の宣言』へ移したので、宣言を書き忘れた入力は file: の穴に渡っていても実在検査から
    # 黙って外れる——init が素通りし、2 手先の next で初めて落ちる（この差分自身が塞いだはずの形）。
    pasted = set()
    for nid, n in nodes.items():
        if not n.get("prompt_file"):
            continue
        try:
            tpl = node_prompt(gpath, n, errors="replace")
        except OSError:
            continue
        # **穴の抽出と接頭の剥がしは engine の正本（render の TOKEN / strip_prefix）を使う。**
        # 手書きの正規表現を持っていたとき、`[^}]+` が pick 付きの穴（`| pick …`）を丸ごと拾って
        # 偽の NG を出し、しかも check_graph は init から呼ばれるので init が止まった。
        # **射程も広げる**: 見るのは file: / section: の穴だけでなく、裸の `{{inputs.X}}` も含む
        # ——同じ差分の別の柵が回す側に接頭を禁じたので、回す側だけが読むパス入力は裸でしか書けず、
        # 接頭だけを見る柵は走査の外に出ていた（実測 r9: init --input spec=/no/such が exit 0）。
        for m in TOKEN.finditer(tpl):
            core = strip_prefix(m.group(2).strip()).split("#", 1)[0].strip()
            if core.startswith("inputs."):
                key = core[len("inputs."):].strip()
                if key and "." not in key:
                    pasted.add((key, nid))
    for key, nid in sorted(pasted):
        # 旗で渡る入力（--request / --lang / --document）はパスとは限らないので kind を持たない。
        # 除外の一覧は engine の CLI_FLAGS が正本（写さず import する）
        if key not in declared and key not in CLI_FLAGS:
            errs.append(f"節 {nid}: 穴が inputs.{key} を読むのに、graph の inputs に {key} の宣言が無い"
                        "——宣言が無い入力は実在検査に当たらないので、存在しないパスが init を素通りする")
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
            emit(f"ok  節 {k}: 回す側が判定するのは設計どおり——{v['runner_judgment_by_design']}")
            continue
        ok, bad2 = False, True
        emit(f"NG 節 {k}: 回す側（{v['run_by']}）が判定を出している: {judges}")
    if not bad2:
        emit("ok  判定を出す節に回す側が無い（verdict_is_copy は写すだけ、runner_judgment_by_design は手順書が定めた例外）")

    # 3. 記録の欄 ⊆ outputs
    # 検証器の綴りは呼ぶ側から（CLI は第 2 引数、engine は --validator）
    vp = g.get("record", {}).get("validator_path")
    if not script and vp:
        script = find_plugin_path(vp, g.get("plugin"))  # engine と同じ探し方（明示 → <PLUGIN>_ROOT → 同じリポジトリ → キャッシュ）
        if not script:
            ok = False
            emit(f"NG record.validator_path '{vp}' が見つからない（plugin {g.get('plugin')!r} の置き場に無い。第 2 引数で渡すか置き場を直す）——欄の突合を省略で通さない")
    if script:
        # 13. graph の enum は検証器の語彙の写し——はみ出せば片方だけ変わっている（包含検査がどこにも無く exit 0 だった）
        vocab = validator_vocab(script)

        def walk_enum(s, where):
            if not isinstance(s, dict):
                return
            e = s.get("enum")
            if isinstance(e, list) and e and all(isinstance(x, str) for x in e):
                es = set(e)
                # 検証器の語彙のどれかと重なる enum は、そのどれかに丸ごと含まれること（素材の status と俯瞰の status のように
                # 語を共有する表が複数在るので、重なる表の全部に含まれる必要は無い）
                touching = {name: vs for name, vs in vocab.items() if es & vs}
                if touching and not any(es <= vs for vs in touching.values()):
                    errs.append(f"{where}: enum {sorted(es)} が検証器のどの語彙にも丸ごと含まれない（重なる表: {sorted(touching)}——写しがずれている）")
            for k2, v2 in (s.get("properties") or {}).items():
                walk_enum(v2, f"{where}.{k2}")
            if isinstance(s.get("items"), dict):
                walk_enum(s["items"], where + "[]")
        for k, v in nodes.items():
            if isinstance(v.get("schema"), dict):
                walk_enum(v["schema"], f"節 {k}: schema")
        need = record_fields(script)
        if not need:
            ok = False
            emit(f"NG 検証器 {script} から必須欄が 1 つも拾えない（書式が変わったか、検証器でない）——0 個の突合を合格にしない")
        else:
            have = " ".join(o for v in nodes.values() for o in v.get("outputs", []))
            missing = sorted(n for n in need if not re.search(rf"\b{re.escape(n)}\b", have))
            if missing:
                ok = False
                emit(f"NG 検証器の欄で outputs に無いもの: {', '.join(missing)}")
            else:
                emit(f"ok  検証器の必須欄 {len(need)} 個すべてがどれかの節の outputs に現れる")
    elif not vp:
        emit("--  検証器の欄との突合は省略（graph に record.validator_path が無く、第 2 引数も無い）")

    # 4. fresh_context と forbidden_inputs
    fresh = [k for k, v in nodes.items() if v.get("fresh_context")]
    bare = [k for k in fresh if not nodes[k].get("forbidden_inputs")]
    emit(f"ok  fresh_context {len(fresh)} 節、うち固有の遮断（forbidden_inputs）を持たないのは "
          f"{len(bare)}（ラウンド規律だけが効く）: {', '.join(bare) or 'なし'}")

    # 5. 段名の正本は thickness.tiers（低い順の配列）。キーの集合から導かない——tiers / deciders / rule が段名として通る
    th = g.get("thickness", {})
    tiers = th.get("tiers") or []
    uses_tiers = any(v.get("active_in") or v.get("thickness_from") for v in nodes.values()) or g.get("round", {}).get("max_rounds_by_thickness")
    bad5 = False
    if not isinstance(tiers, list) or not all(isinstance(t, str) for t in tiers):
        ok, bad5 = False, True
        emit("NG thickness.tiers は段名の配列（低い順）")
        tiers = []
    if uses_tiers and not tiers:
        ok, bad5 = False, True
        emit("NG 段（active_in / thickness_from / max_rounds_by_thickness）を使うのに thickness.tiers（低い順）が無い")
    if tiers:
        for k, v in nodes.items():
            bad = [t for t in v.get("active_in", []) if t not in tiers]
            if bad:
                ok, bad5 = False, True
                emit(f"NG 節 {k} の active_in に無い段: {bad}（段は {tiers}）")
        for t in g.get("round", {}).get("max_rounds_by_thickness", {}):
            if t not in tiers:
                ok, bad5 = False, True
                emit(f"NG max_rounds_by_thickness の段 '{t}' が thickness.tiers に無い")
        if th.get("default") not in tiers:
            ok, bad5 = False, True
            emit(f"NG thickness.default '{th.get('default')}' が tiers に無い")
        if not bad5:
            emit(f"ok  段名は thickness.tiers {tiers} の中（active_in・max_rounds_by_thickness・default）")

    def flush(head):
        """**溜めた NG の出口はここ 1 つ。** 早い return の手前で吐かずに戻っていたとき、
        exec を持たないグラフでは inputs 宣言の欠けごと ok で通った（実測 r10）——
        溜める所と吐く所が離れていると、間に出口が増えるたびに同じ穴が開く。"""
        if errs:
            for e in errs:
                emit("NG " + e)
            return False
        emit(head)
        return True

    if not g.get("exec"):
        # 実行の形の検査は省くが、**ここまでに溜めた NG（inputs 宣言・schema の語など）は吐く**
        ok = flush("ok  宣言の形（inputs・schema の語）。exec が無いので実行の形の検査 6〜13 は省略") and ok
        return ok

    # 11. schema は engine が読む語だけで書く——読まない語（oneOf / not / format / 綴り違い）は validate_schema が黙って
    # 無視するので、書いても効かない schema が graph に入る（以前は docstring の注記だけで守っていた）
    for k, v in nodes.items():
        if isinstance(v.get("schema"), dict):
            for u in unknown_keywords(v["schema"]):
                errs.append(f"節 {k}: schema に engine が読まない語 {u}（綴り違いか本家 JSON Schema の語——書いても効かない）")
            for pat in schema_patterns(v["schema"]):
                try:
                    end_anchored(pat)   # 検査と同じ読み替えを通した物をコンパイルする（読み替えた後が壊れる形も拾う）
                except re.error as e:
                    errs.append(f"節 {k}: schema の正規表現 {pat!r} が壊れている（{e}）——型検査の時点で例外になる")
    # 6〜13. 実行の形
    agents = agent_names(g)
    if agents is None:
        errs.append(f"役割 agent の定義（agents/）が見つからない: plugin {g.get('plugin')!r}——graph に plugin を書き、その plugin が同じリポジトリかキャッシュか <PLUGIN>_ROOT に在ること")
        agents = set()
    dl = g.get("deliver", {}).get("path_tools")
    if dl is not None and not (isinstance(dl, list) and all(isinstance(t, str) for t in dl)):
        errs.append("deliver.path_tools は道具の名前の一覧")
    # 回す側の節の任せ先（delegate）: 回す側の節にだけ・モデルの名前は表のどれか・理由を書く
    for k, v in nodes.items():
        dg = v.get("delegate")
        if dg is None:
            continue
        if v.get("run_by") not in set(g.get("runners", [])):
            errs.append(f"節 {k}: delegate は回す側の節（runners）にだけ書ける——役の節の model は役の定義が正本")
        elif not (isinstance(dg, dict) and dg.get("model") in DELEGATE_MODELS and isinstance(dg.get("why"), str) and dg["why"].strip()):
            errs.append(f"節 {k}: delegate は {{model: {'/'.join(DELEGATE_MODELS)}, why: 任せてよい理由}}")
        if isinstance(dg, dict) and "background" in dg:
            if not isinstance(dg["background"], bool):
                errs.append(f"節 {k}: delegate.background は真偽（任せ先を背景で立てて待たずに受領を返すか）")
            elif dg["background"]:
                # 背景の節の done は受領（線を立てた事実）でしかない——待つ節は、線の結果を待ったと読み違える
                waiters = sorted(w for w, x in nodes.items() if k in (x.get("deps") or []) + (x.get("instance_deps") or []))
                if waiters:
                    errs.append(f"節 {k}: 背景の節（delegate.background）を {waiters} が待っている——背景の節の done は受領で、結果は置き場から読む")
                # 背景の任せ先の返答は engine が置き場へ置く（子は sandbox の中で盤面に書けない）——置き場は節が読む材料の 1 つ
                if dg.get("result_to") not in (v.get("reads") or []):
                    errs.append(f"節 {k}: 背景の任せ先は delegate.result_to に返答の置き場（この節の reads のどれか）を名指しする"
                                "——engine が子の返答をそこへ置く")
        if v.get("skills"):
            # skill（/simplify・/code-review）は中でさらに役を背景で起こす。任せ先の役越しに呼ぶと、孫の完了の知らせが
            # 任せ先に届かないまま待ち続けた（実測 2026-09-25: 局所レビューの任せ先が 7 時間以上戻らなかった）
            errs.append(f"節 {k}: skills を持つ節に delegate は書けない——skill は回す側（最上位のセッション）が自分で呼ぶ（入れ子の委任は完了の知らせが届かない）")
    if any(isinstance(v.get("delegate"), dict) for v in nodes.values()) and not (g.get("launch", {}).get("delegate") or {}).get("argv"):
        errs.append("任せ先（delegate）を持つ節が在るのに launch.delegate.argv が無い——任せ先を sandbox で縛って起こせない"
                    "（Agent ツールで起こすと本物の作業ツリーと .git に書ける）")
    pr = g.get("deliver", {}).get("paste_roles")
    if pr is not None and not (isinstance(pr, list) and all(isinstance(t, str) and ":" in t for t in pr)):
        errs.append("deliver.paste_roles は役の名前（<plugin>:<役>）の一覧")
    for t in pr if isinstance(pr, list) else []:
        # 同じ plugin の役は定義が在ることまで見る（綴りを違えると deliver_mode が path を返し、防ぎたかった往復が黙って戻る）
        plug, _, role = t.rpartition(":")
        if plug == g.get("plugin") and agents and role not in agents:
            errs.append(f"deliver.paste_roles の役 {t!r} が {plug} の agents/ に無い（綴り違いは黙って path に倒れる）")
    # 道具ゼロの役（遮断系）を使うなら、起こし方の宣言が要る。Agent ツールで起こすとハーネスが
    # CLAUDE.md 階層を注入し、止める設定が公式に無い——遮断が名ばかりになる（実測 2026-09-12）。
    isolated = sorted(r for r in agents if agent_tools(f"{g.get('plugin')}:{r}") == [])
    used = {v.get("run_by") for v in nodes.values()} | {v.get("agent_type", "").rpartition(":")[2] for v in nodes.values()}
    if isolated and (used & set(isolated)) and not (g.get("launch", {}).get("isolated", {}).get("argv")):
        errs.append(f"道具ゼロの役 {sorted(used & set(isolated))} を使うのに launch.isolated.argv が無い"
                    "——Agent ツールで起こすと CLAUDE.md が注入され、遮断が成立しない")
    launch = g.get("launch") or {}
    for kind in ("isolated", "tooled", "delegate"):
        spec = launch.get(kind) or {}
        if not spec:
            continue
        via = spec.get("via")
        if via is not None and not (isinstance(via, list) and all(isinstance(a, str) for a in via)):
            errs.append(f"launch.{kind}.via は解決した argv の前に置く語の一覧（文字列の配列）")
            via = None
        for a in via or []:
            # via が指す実体が同梱されているか。**実行時にしか出ない落ち方**——launch が起こした瞬間に
            # python が「そんなファイルは無い」で落ち、役の返答が空のまま拒まれるだけになる。
            # plugin_root しか穴が無い語は検査の時点で埋まる（他の穴を含む語は実行時にしか決まらないので触らない）
            if "{plugin_root}" in a and "{" not in a.replace("{plugin_root}", ""):
                p = pathlib.Path(a.format(plugin_root=PLUGIN_ROOT))
                if not p.is_file():
                    errs.append(f"launch.{kind}.via が指す {p} が無い（プラグインに同梱されていない）")
        for part in ("argv", "resume"):
            words = spec.get(part)
            if words is None and part == "resume":
                continue
            if not (isinstance(words, list) and words and all(isinstance(a, str) for a in words)):
                errs.append(f"launch.{kind}.{part} は起こす語の一覧（空でない文字列の配列）")
                continue
            # 起動の穴は engine の launch_spec が埋める語だけ（LAUNCH_HOLES）。知らない穴は format の KeyError
            holes = {m.group(1) for a in words + list(via or []) for m in re.finditer(r"\{(\w+)\}", a)}
            unknown = holes - set(LAUNCH_HOLES)
            if unknown:
                errs.append(f"launch.{kind}.{part} / via の穴 {sorted(unknown)} を engine は埋められない（埋めるのは {list(LAUNCH_HOLES)}）")
            if part == "resume" and "session_id" not in holes:
                errs.append(f"launch.{kind}.resume に {{session_id}} が無い——続ける会話を名指ししない語は同じ会話を続けない")
            if kind == "isolated" and isolated and (used & set(isolated)):
                # model / effort は役の定義から埋めるので定義に無ければ die——実行時にしか出ない不変条件を静的に見る
                for r in sorted(used & set(isolated)):
                    d = agent_def(f"{g.get('plugin')}:{r}") or {}
                    for k in ("model", "effort"):
                        if k in holes and not d.get(k):
                            errs.append(f"遮断系の役 {r} の定義に '{k}' が無いが launch.isolated.{part} が {{{k}}} を使う（実行時の die を静的にも見る）")
    ror = launch.get("resume_on_reject", 0)
    if not (isinstance(ror, int) and not isinstance(ror, bool) and ror >= 0):
        errs.append(f"launch.resume_on_reject は 0 以上の整数（{ror!r}）")
    rules = load_rules(gpath, g)
    rules_unreadable = isinstance(rules, str)
    if rules_unreadable:
        errs.append(rules)
        rules = None
    if rules is not None:
        # フック名の綴り違いを落とす。engine は getattr の名前一致で探すので、1 字違いは「このループは持たない」に
        # 静かに倒れる（意図的な不在と区別が付かない）。似て非なる公開名を NG にする
        import difflib
        # **母数は「この rules が定義した公開の関数」全部。** 以前は `on_` で始まる名前と、
        # 非 `on_` のフック名を**手で並べた 4 語**だけを見ていた——engine の HOOKS はその 4 語を
        # 持つので今は一致するが、綴り違いはその表に載らないので、`finalize` を `finalise` と書いても
        # 母数に入らず 1 件も出なかった（実測 2026-09-13: 柵は「フック名の綴り違いを落とす」と
        # 名乗るのに、落とせるのは `on_` で始まるものだけだった）。**engine に非 `on_` のフックが
        # 増えた周も、ここは黙って狭いまま。** 定義元で絞るので、import した名前は母数に入らない。
        public = {n for n in dir(rules)
                  if not n.startswith("_") and callable(getattr(rules, n, None))
                  and getattr(getattr(rules, n, None), "__module__", None) == getattr(rules, "__name__", None)}
        for n in sorted(public - set(HOOKS)):
            near = difflib.get_close_matches(n, HOOKS, n=1, cutoff=0.8)
            if near:
                errs.append(f"rules の公開名 '{n}' は engine のフック '{near[0]}' の綴り違いに見える（engine は名前一致でしか探さないので静かに無視される）")
    reg = lambda name: set(registry(rules, name))  # 名前表の引き方は engine の registry（写しを持たない）
    # 受理集合の形。**鍵の一覧は engine と rules から組む**——手で 2 語並べていたとき、どちらかが鍵を
    # 増やしてもこの柵は増えず、増えた鍵だけ形（整数の空でない一覧）を誰も検査しないまま通った。
    # **鍵が在れば null でも落とす**——`is not None` で外していたので、NG 文が名指しする null そのものが
    # 素通りし、実行時は `exit not in None` の TypeError になった。
    for key in sorted(set(ENGINE_ACCEPT_KEYS) | reg("ACCEPT_KEYS")):
        if key not in g.get("record", {}):
            continue
        ae = g["record"][key]
        if not (isinstance(ae, list) and ae and all(isinstance(x, int) and not isinstance(x, bool) for x in ae)):
            errs.append(f"record.{key} は終了コード（整数）の空でない一覧: {ae!r}（null や文字列は engine / rules が『受理集合に無い』と読めず TypeError で落ちる）")
    write_ops = set(ENGINE_WRITE_OPS) | reg("WRITE_OPS")
    # 素材の書き先と宣言を揃える。節の materials は『この節がどの素材を出すか』の正本で、判定の後の人待ちの柵
    # （check_record の awaiting の出どころ）や巻き戻しはこの宣言しか見ない——書き先だけに在る素材は柵をすり抜け、
    # 宣言だけに在る素材は誰も書かないのに在る前提で読まれる。to を素材名として読むかは rules の op ごとに writes_material で名乗る
    # （op の意味を知るのは rules だけ——ここに op の名前を写さない。名乗りの無い op は落とす）。素材を丸ごと書く to（materials）は宣言と照合できないので落とす
    rops = registry(rules, "WRITE_OPS")
    errs += [f"rules の WRITE_OPS の op '{k}' が writes_material（to を素材の名前として読むか）を真偽で名乗らない"
             for k, fn in rops.items() if not isinstance(getattr(fn, "writes_material", None), bool)]
    mat_ops = {k for k, fn in rops.items() if getattr(fn, "writes_material", False) is True}
    for k, v in nodes.items():
        ws = [w for w in v.get("writes") or [] if isinstance(w, dict) and isinstance(w.get("to"), str)]
        if any(w["to"] == "materials" for w in ws):
            errs.append(f"節 {k}: writes の to が materials そのもの——素材は 1 つずつ（materials.<名前>）書け（宣言と照合できない）")
        wrote = {w["to"].removeprefix("materials.") for w in ws if w["to"].startswith("materials.") or w.get("op") in mat_ops}
        declared = set(v.get("materials") or [])
        if wrote != declared:
            errs.append(f"節 {k}: materials の宣言 {sorted(declared)} と writes の素材の書き先 {sorted(wrote)} が揃わない")
    fan_builtins, node_builtins, post_checks = reg("FAN_OUT"), reg("BUILTINS"), reg("POST_CHECKS")
    conds = dict(registry(rules, "CONDS"))
    for nid in g.get("raw_for_report", []):
        if nid not in nodes:
            errs.append(f"raw_for_report に無い節: {nid}")
    def check_conds(k, v):
        """節の条件（cond・applies_cond・skills[].applies_cond）の名前と読む欄、節の reads・outputs が名指す loop.<鍵> を照らす
        （driver の節も同じ）"""
        named = [(key, v[key]) for key in ("cond", "applies_cond") if key in v]
        named += [(f"skills[{i}].applies_cond", e["applies_cond"]) for i, e in enumerate(v.get("skills") or [])
                  if isinstance(e, dict) and "applies_cond" in e]
        for key, c in named:
            if not isinstance(c, str) or c not in conds:
                errs.append(f"節 {k}: {key} '{c}' が rules の CONDS の名前でない（graph には条件の関数の名前だけを書く。CONDS: {sorted(conds)}）")
                continue
            check_declared_reads(conds[c], c, f"節 {k}.{key}", g, rules, errs, nid=k)
        # 節の reads と outputs が名指す loop.<鍵> も、条件と同じ宣言（LOOP_KEYS）で照らす——穴（{{?loop.X}}）の綴り違いは
        # ABSENT で黙って埋まり、outputs の loop.<鍵> は宣言の 2 本目として別にずれうる
        if rules is not None and getattr(rules, "LOOP_KEYS", None) is not None:
            for key in ("reads", "outputs"):
                for r in v.get(key) or []:
                    if isinstance(r, str) and r.startswith("loop."):
                        check_read_path(r.split()[0].rstrip("（(:"), f"節 {k}.{key}", g, rules, errs)

    for k, v in nodes.items():
        rb = v.get("run_by")
        if rb not in runners and rb not in agents and rb not in ("driver", "skill") and not v.get("agent_type"):
            errs.append(f"節 {k}: run_by '{rb}' が回す側でも役割 agent（{sorted(agents)}）でも driver / skill でもなく、agent_type の上書きも無い")
        if rb == "skill" and not v.get("skills"):
            errs.append(f"節 {k}: run_by が skill なのに skills（呼ぶ skill の一覧）が無い")
        errs += skills_shape(k, v.get("skills"))
        if rb in isolated and v.get("agent_type"):
            # 遮断系の役は cli で起こす（emit_instance が mode=cli にする）。run_by に置いたうえで agent_type を
            # 上書きすると起こし方が 2 つ宣言された状態になる——実行時の die を静的にも見る
            errs.append(f"節 {k}: 遮断系（道具ゼロ）の役 '{rb}' を run_by に置きながら agent_type で上書きしている（起こし方が 2 つ）")
        same = v.get("same_context_as")
        if same and (same not in nodes or same not in ancestors(nodes, k)):
            errs.append(f"節 {k}: same_context_as '{same}' が前の節でない")
        # 遮断系（道具ゼロの役）は渡された物しか知らない読み手なので、前の節の文脈を継がせない。**実行時の die だけに置かない**
        # ——回した周にしか出ないので、静的に無いことが痛みとして現れにくい（engine/advance.py の die と同じ不変条件）
        if same and rb in isolated:
            errs.append(f"節 {k}: 遮断系（道具ゼロ）の役 '{rb}' に same_context_as——前の節の文脈を持ち込むと遮断が崩れる")
        er = v.get("engine_run")
        if er is not None:
            # 走らせるだけの節: 回す側の節にだけ（任せ先に落ちたときに回す側の節として出る）・名前が rules の ENGINE_RUNS に在り、
            # 計画（plan）と返答を組む関数（reply）の両方を持つ・理由を書く
            entry = registry(rules, "ENGINE_RUNS").get(er.get("builtin")) if isinstance(er, dict) else None
            if rb not in runners:
                errs.append(f"節 {k}: engine_run は回す側の節（runners）にだけ書ける——宣言が無いときは回す側の節として出る")
            elif not (isinstance(er, dict) and set(er) == {"builtin", "why"} and isinstance(er.get("why"), str) and er["why"].strip()):
                errs.append(f"節 {k}: engine_run は {{builtin: rules の ENGINE_RUNS の名前, why: engine が走らせてよい理由}}")
            elif not (isinstance(entry, dict) and callable(entry.get("plan")) and callable(entry.get("reply"))):
                errs.append(f"節 {k}: engine_run.builtin '{er.get('builtin')}' が rules の ENGINE_RUNS に無いか、plan と reply を持たない")
        if rb == "driver":
            if v.get("builtin") not in node_builtins:
                errs.append(f"節 {k}: builtin '{v.get('builtin')}' が rules の BUILTINS に無い")
            # **driver 節にもデータの契約を要求する。** ここで抜けさせていたとき、driver 節は reads を 1 つも持てず
            # deps が「順序」と「要る値」の 2 つの意味を 1 本で担い、どちらの意味で載っているかを機械にも読み手にも
            # 区別させなかった（実測 2026-09-13: p4.assemble は p4.ci / p4.scalars を読まないのに deps に持ち、
            # 読まないから外せるように見えた——実際はその 2 本が記録に着地する順序を保証する唯一の辺だった）。
            # engine は driver の reads を穴埋めに使わないので挙動は変わらない。宣言として要る
            if v.get("reads") is None:
                errs.append(f"節 {k}: reads が無い（driver も宣言しろ——deps のどれが値でどれが順序かが読めない）")
            check_conds(k, v)
            continue
        pf = v.get("prompt_file")
        if not pf or not (gpath.parent / pf).is_file():
            errs.append(f"節 {k}: prompt_file が無い（{pf}）")
            continue
        gone = [p for p in v.get("prompt_append") or [] if not (gpath.parent / p).is_file()]
        if gone:
            errs.append(f"節 {k}: prompt_append のファイルが無い（{gone}）")
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
        tpl = node_prompt(gpath, v)
        # **逆向きも見る。** 穴 ⊆ reads だけでは、宣言だけ在って誰にも届いていない欄が赤くならない
        errs += unused_reads(k, v, {m.group(2).strip() for m in TOKEN.finditer(tpl)})
        for m in TOKEN.finditer(tpl):
            path = m.group(2).strip()
            core = strip_prefix(path)
            if path.startswith("ref:") and not (core == "record" or core.startswith("record.") or core == "raw"
                                                or core.startswith("out.") or core.startswith("prev.")):
                errs.append(f"節 {k}: {{{{{path}}}}} は ref: にできない（record・out.<節>・prev.<節>・raw だけ）")
            # **回す側の節に本文を貼らない（パスで渡す）。** runner のプロンプトは回す側が Read するので、
            # 貼った本文はそのまま回す側の文脈に入る——しかも runner には上限が無い（advance.py の
            # cap=None。切ると「文書はこれだ」と言って途中で切った物を渡すことになるので、切れない形である）。
            # 同じ波の 2 節が同じ文書を貼れば 2 部入る（実測 2026-09-18: 29,886 バイトの見立て文書で
            # p0.claims 33,478 B ＋ p0.terms 31,771 B ＝ 1 波で 65 KB が回す側の文脈へ）。
            # 回す側はファイルを読めるのだから、渡すのはパスで足りる——どこまで読むかの判断を engine が奪わない。
            # 貼る形に意味が在るのは、自分で読めない相手（標準入力で流す遮断系・本文を貼って渡す agent）だけ。
            # 貼る接頭の綴りは写さない——core（strip_prefix の結果）が path と違えば何らかの接頭が付いており、
            # そのうち ref: だけが本文でなく置き場の要約を渡す。engine が貼る接頭を増やした周に、
            # ここだけ古い一覧のまま緩む（素通りする）のを防ぐ
            if rb in runners and core != path and not path.startswith("ref:"):
                errs.append(f"節 {k}: {{{{{path}}}}} は回す側（{rb}）の節に書けない——"
                            "本文でなくパスを渡し、どこまで読むかは回す側に決めさせろ"
                            "（**この柵が見るのは回す側の節だけ**。Read を持つ役割 agent の節には当たらない）")
            # 許可の判定は engine の Renderer を呼ぶ（式を写すと engine だけ変えたとき検査が黙って緩む）
            if not Renderer({}, reads).allowed(path):
                errs.append(f"節 {k}: プロンプトの穴 {{{{{path}}}}} が reads に無い")
            # record.<欄> の穴も条件の読みと同じ照らし（記録を書く宣言）に通す——省略可の穴（{{?record.…}}）の綴り違いは
            # 実行時に『（この周には無い）』で黙って埋まる。rules が在るのに読めなかった回は照らさない（init_record を
            # 引けず、全部の穴が偽の NG になって本当の原因——rules が読めない——が埋もれる）
            if core.startswith("record.") and not rules_unreadable:
                check_read_path(core, f"節 {k}: プロンプトの穴 {{{{{path}}}}}", g, rules, errs)
            if core.startswith("out."):
                src = node_of(core[4:], nodes)
                if src is None or src not in anc:
                    errs.append(f"節 {k}: {core} を読むが、その節は前の節（deps の推移閉包）でない（前の周の出力なら prev.<節>）")
            if core.startswith("prev.") and node_of(core[5:], nodes) is None:
                errs.append(f"節 {k}: {core} の節が無い")
            if core.startswith("node.") and core != "node.skills":
                errs.append(f"節 {k}: {{{{{core}}}}} は engine が埋めない（埋める node の欄は skills だけ）。埋められずに next で止まる")
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
        if "instance_deps" in v and ("cond" in v or any(isinstance(e, dict) and "applies_cond" in e for e in v.get("skills") or [])):
            errs.append(f"節 {k}: instance_deps と cond（skills[].applies_cond も）は同時に持てない（項目を先に出すとき cond を評価できない）")
        if v.get("post_check") and v["post_check"] not in post_checks:
            errs.append(f"節 {k}: post_check '{v['post_check']}' が rules の POST_CHECKS に無い")
        check_conds(k, v)
        # 12. engine が実行に使う欄（writes.from・条件の読む欄・same_context_as の役）は、宣言どおりの物を指すこと。
        # 文書欄（outputs）の照合は通っても、実行の欄の綴り違いは黙って素通りしていた（実測 2026-09-12: writes.from を
        # 綴り違いにしても exit 0 で、台本は 5 周回って stopped）
        props = set((v.get("schema") or {}).get("properties", {}))
        req = set((v.get("schema") or {}).get("required", []))
        if props:
            for w in v.get("writes", []) or []:
                frm = w.get("from")
                if not frm or frm == "$":
                    continue
                head = frm.split(".")[0]
                if head not in props:
                    errs.append(f"節 {k}: writes.from '{frm}' が schema.properties に無い（返答に無い欄を写そうとしている——記録に着地しない）")
                elif head not in req and not w.get("optional"):
                    # **任意の欄を写すなら、任意だと宣言しろ。** engine は欄が無い返答を黙って読み飛ばす
                    # （`has_path` が偽なら continue）ので、役が省いた周は**その write だけ音も無く消える**。
                    # 「意図した省略」と「綴り違い・欄の消失」がここで同じ無音になる——宣言で分ける。
                    errs.append(f"節 {k}: writes.from '{frm}' は schema.required に無い（任意の欄）のに optional の宣言が無い"
                                "——役が省いた周はこの write が無音で消える。意図した省略なら writes に optional: true を書け")
        same = v.get("same_context_as")
        if same and same in nodes:
            me = v.get("agent_type") or v.get("run_by")
            them = nodes[same].get("agent_type") or nodes[same].get("run_by")
            if me != them:
                errs.append(f"節 {k}: same_context_as '{same}' と役が違う（{them} → {me}）——同じ context を継げない")
            if (me or "").rpartition(":")[2] in isolated:
                errs.append(f"節 {k}: 遮断系（道具ゼロ）の役に same_context_as は使えない——前の節の文脈を持ち込むと遮断が崩れる（実行時の die を静的にも見る）")
        # pre は『報告の前に記録を仕上げて検証器を回す』唯一の門。綴り違いは検証器を通さずに報告を出す形になる
        if "pre" in v and v["pre"] not in ENGINE_PRE:
            errs.append(f"節 {k}: pre '{v['pre']}' を engine が知らない（使えるのは {'/'.join(ENGINE_PRE)}）")
    ok = flush("ok  実行の形: run_by・prompt_file・schema・reads（穴の宣言と前の節だけ）・回す側は判定欄に書かない・名前は engine か rules にある") and ok
    return ok


def main():
    if len(sys.argv) not in (2, 3):
        print(__doc__, file=sys.stderr)
        sys.exit(2)
    sys.exit(0 if check(sys.argv[1], sys.argv[2] if len(sys.argv) == 3 else None) else 1)


if __name__ == "__main__":
    main()
