"""review-loop の rules——graphs/review-loop.json に書けない算術だけを持つ。

記録の形と語彙の正本は convergence-loops の scripts/review-record.py（同じリポジトリ。版は plugin.json が正本で、ここに写さない）。
ここはその定数を import して使い（写さない）、周ごとの記録 rounds/round-<N>.json を組み、検証器にディレクトリを渡す。

engine が差し込む道具は engine/rules.py の INJECT が正本（ここに写さない）。
"""
import importlib.util
import json
import pathlib
import re
import shutil
import tempfile
from typing import NamedTuple

_pspec = importlib.util.spec_from_file_location("graphloops_rules_policy_input", pathlib.Path(__file__).with_name("policy_input.py"))
policy_input = importlib.util.module_from_spec(_pspec)
_pspec.loader.exec_module(policy_input)

# 差分を割って複数の cold-reader に配る扇（diff_chunks）は落とした。**割る理由が無くなったから**——
# 遮断系は別プロセスの CLI へ標準入力で流すので、貼る上限（Agent ツールのプロンプトの性質。実測 約 50 KB）に
# 当たらない。2026-09-12 にこの環境（macOS・claude 2.1.269）で観測: 748,883 バイトと 774,021 バイトの入力が先頭・末尾とも
# 欠けずに 1 回で届いた（測定の記録は docs/loop-contract.md の T 節。上限の値は目安で、契約ではない）。
# 入り切らなければ API がエラーを返して**うるさく落ちる**ので、割りは安全柵でもなかった（静かに切る
# 経路が事故だったのであって、落ちる経路は守るべき性質を既に満たしている）。
# 落としたのは 23 片に割れていた実績があるから: 750 KB の差分が hunk 境界で 23 片（平均 33 KB。上限 40,000 バイトの
# 割り算ではなく実測）に割れ、**読み手の人数が差分の大きさで決まっていた**（誰も「衛生の検査には 23 人要る」と決めていない）。同じものを N 人に
# 読ませて突き合わせたいなら、それは上限の副作用でなく graph の宣言として書くこと。


# ---------------------------------------------------------------- 検証器を正本として読む
# validator_module は engine（engine/rules.py の INJECT）が差し込む——ここに写しを置かない


def review_md_path(b):
    v = b.state.get("validator")
    return str(pathlib.Path(v).resolve().parent.parent / "REVIEW.md") if v else None


# ---------------------------------------------------------------- 初期化と周
def init_record(thickness, decider):
    return {"base": None, "round": 1, "materials": {}, "units": [], "scalars": {}, "reviews": {}, "questions": [],
            "process": {"human_items": [], "human_answers": []}}


def on_init(b, args):
    """REVIEW.md（同梱と対象リポジトリ）と script の置き場を inputs に。"""
    b.state["inputs"]["review_md"] = review_md_path(b)
    repo_md = pathlib.Path(b.state["inputs"]["cwd"]) / "REVIEW.md"
    b.state["inputs"]["repo_review_md"] = str(repo_md) if repo_md.is_file() else None
    b.state["inputs"]["scripts_dir"] = str(pathlib.Path(b.state["validator"]).parent) if b.state.get("validator") else None
    b.state["inputs"]["rounds_dir"] = str(b.dir / "rounds")
    # 条件の関数は inputs を読めない（条件の文脈は record・out・prev・cur・round・rd・loop だけ）ので、選んだ流れを loop に写す。
    # 値は init の後に変わらない（inputs は init で固まる）。値は check_inputs が置き場を作る前に確かめてある
    # flow の写しは、選べる流れの選び方を 1 つに揃える問い（問いの台帳の fork: 仕様の道を extends の版にするか）の決着で、
    # flow の入力ごと消える
    inputs = b.state["inputs"]
    if inputs.get("flow") is not None:
        b.loop_state["flow"] = inputs["flow"]
    if inputs.get("gates") is not None:
        b.loop_state["gates"] = inputs["gates"]
    mutation_decl(b)
    # 人の方針の文書: init の時点の版を固定し（sha と写し）、関所（human_gate）と仕上げが変わっていないかを照らす
    b.record["process"]["policy"] = {**policy_input.resolve(b, git, Reject), "amendments": []}


def check_inputs(inputs):
    """init の入口（置き場を作る前）で、選ぶ入力の鍵と値を確かめる——綴り違いの鍵や知らない値を既定（今の流れ）に倒さない。
    仕様の道（flow=spec）と、変異の検算を合流でまとめる選択（gates=merge）"""
    import difflib
    chosen = {"flow": SPEC_FLOW, "gates": GATES_MERGE}
    for k in inputs:
        # 鍵の綴り違い（gate=merge）は、黙って既定（撃つ）に倒れると選んだつもりの害がそのまま起きる。似て非なる鍵を落とす
        # （graphcheck がフック名の綴り違いを落とすのと同じ形）
        near = difflib.get_close_matches(k, chosen, n=1, cutoff=0.75) if k not in chosen else []
        if near:
            raise Reject(f"--input {k}=… は鍵 {near[0]} の綴り違いに見える（知らない鍵は既定の流れに倒れる）——{near[0]}={chosen[near[0]]} と書け")
    for k, want in chosen.items():
        v = inputs.get(k)
        if v is not None and v != want:
            raise Reject(f"--input {k}={v!r} は知らない値（使えるのは {k}={want}。今の流れなら {k} を渡さない）")


# ---------------------------------------------------------------- 人の修正依頼と、判定から入る入口（R12）
# 依頼は判定役が読む findings の型そのもので受け、出どころを欄（origin）で持つ。役の欄（procedure_findings 等）を
# 借りると、人の依頼か役の観察かが記録の上で区別できない（2026-09-25 の特別周まではそうしていた）。
# **依頼を積むことと、P1 を外すことは別の欄で持つ。** 1 つの欄の在否で両方を運ぶと、途中の周の依頼を受けた瞬間に
# 通常の run の P1 が外れる（2026-09-25 の統合の run の判定）。依頼は周ごとのバッチの一覧（request_findings）、
# 入口の印は request_entry（1 周目の P1 より前の最初の add だけが立て、戻さない）
REQUEST_SCHEMA = {"type": "array", "items": {
    "type": "object", "required": ["round", "origin", "findings"], "additionalProperties": False, "properties": {
        "round": {"type": "integer", "minimum": 1},
        "origin": {"type": "string", "minLength": 1},
        "findings": {"type": "array", "minItems": 1, "items": {
            "type": "object", "required": ["where", "text"], "additionalProperties": False,
            "properties": {k: {"type": "string"} for k in ("where", "text", "mechanism", "measured", "false_positive_if")}}}}}}
ENTRY_SCHEMA = {"type": "object", "required": ["origin"], "additionalProperties": False,
                "properties": {"origin": {"type": "string", "minLength": 1}}}
ENTRY_BUILTIN = "request_entry"


def _requests(b, field):
    """依頼のバッチの一覧（request_findings か request_history）を読む唯一の口 ——(一覧, 型の誤り)。
    型はここで当てる: loop.py patch は rules を通らずに欄を書けるので、add だけで当てると patch の値が型を通らずに流れる"""
    v = b.record.get("process", {}).get(field)
    if v is None:
        return [], None
    errs = validate_schema(v, REQUEST_SCHEMA)
    return ([], f"process.{field}: " + "; ".join(errs)) if errs else (v, None)


def _started(b, inst):
    """instance の役がもう入力を読んだか（読んだかもしれないか）: 起こした（launched_at）・返答の置き場にファイルが在る・待ちでない。
    プロンプトは instance を出した時点で固まるので、読む前なら描き直せば後から積んだ物が届く"""
    return inst["status"] != "pending" or bool(inst.get("launched_at")) or pathlib.Path(inst["out_path"]).is_file()


def _diagnose_started(b):
    """その周の判定役（p2.diagnose）が起きたか——add の締めの唯一の式。節が済んだか、instance のどれかが起きた"""
    return b.node_state("p2.diagnose") != "pending" or any(
        i["node"] == "p2.diagnose" and _started(b, i) for i in b.rd["instances"].values())


def add(b, items, reason):
    """人の修正依頼を、この周の判定役に渡すバッチとして record.process.request_findings に積む（loop.py add）。
    その周の判定役（p2.diagnose）が起きる前なら——instance が出ていても、起こす前（出力が無い間）なら——どの周でも何度でも受ける。
    1 周目の P1 より前の最初の add だけが入口の印（request_entry）を立てる——その run は修正が入るまで P1 の役を起こさない。
    返りの redraw は、積んだ欄を読む（graph の reads）まだ起きていない他へ渡した instance——engine がプロンプトを描き直す"""
    if _diagnose_started(b):
        raise Reject(f"round {b.round} の判定役は既に起きている（起こした・返答が在る・済んだ）——依頼はその周の判定役を起こす前にだけ足せる。"
                     "次の周が来るならその判定の前に足せ。次の周が来ない（収束した・終わった）run なら、新しい run を init し、最初の next の前に add して判定から始めよ")
    batch = {"round": b.round, "origin": reason, "findings": items}
    errs = validate_schema([batch], REQUEST_SCHEMA)
    if errs:
        raise Reject("add の形: [{where, text, mechanism?, measured?, false_positive_if?}] の配列（空でない）: " + "; ".join(errs))
    cur, why = _requests(b, "request_findings")
    if why:
        raise Reject(f"記録の依頼の欄の型が崩れている（{why}）——loop.py patch で直してから足せ")
    proc = b.record["process"]
    opened = entry_opens(b)
    proc["request_findings"] = cur + [batch]
    if opened:
        proc["request_entry"] = {"origin": reason}
    wheres = request_wheres(b)
    wrote = ["record.process.request_findings", *(["record.process.request_entry"] if opened else []),
             *(["loop.request_wheres"] if wheres != b.loop_state.get("request_wheres") else [])]
    b.loop_state["request_wheres"] = wheres   # P0 の範囲の読み口も積んだ時点で引き直す（worktree_before の後の add を落とさない）
    # 積んだ欄を読む節（正本は graph の reads）の、待っている instance。起きていない他へ渡した物は描き直し、起きた物・回す側の節は言う
    near = lambda r, w: r == w or w.startswith(r + ".") or r.startswith(w + ".")
    readers = [i for i in b.rd["instances"].values()
               if i["status"] == "pending" and any(near(r, w) for r in b.nodes[i["node"]].get("reads", []) for w in wrote)]
    own = lambda i: b.is_runner(b.nodes[i["node"]]) and not b.nodes[i["node"]].get("delegate")
    redraw = [i["id"] for i in readers if not own(i) and not _started(b, i)]
    stale = [i["id"] for i in readers if i["id"] not in redraw]
    msg = f"人の依頼 {len(items)} 件を round {b.round} の判定に積んだ（出どころ: {reason}）"
    if stale:
        msg += (f"。{'・'.join(stale)} は起きた後か回す側の節なので描き直していない——この依頼はそのプロンプトに入っていない"
                "（回す側の節なら、描き直した盤面の値で答えよ。範囲に入れるなら最初の next の前に積め）")
    if opened:
        msg += "。判定から入る run として始まる——修正が入るまで P1 の役は起こさない"
    else:
        msg += ("。この run は判定から入る run で、修正が入るまで P1 の役は起こさない" if b.cond(ENTRY_BUILTIN)[0]
                else "。P1 の役はいつもどおり走る（入口の印を立てるのは、1 周目の P1 より前の add だけ）")
    return {"msg": msg, "redraw": redraw}


def _entry_marked(v):
    """入口の印（process.request_entry）が型どおりに在るか。印を読む唯一の式（request_entry と entry_first_fix が呼ぶ）"""
    return not validate_schema(v("record.process.request_entry", None), ENTRY_SCHEMA)  # 欄が無い（None）も型違いとして偽


def entry_opens(b):
    """いま add すれば入口の印が立つか（1 周目の P1 より前で、印がまだ無い）。add と空差分の拒否文の案内が同じこの 1 本を読む"""
    return b.round == 1 and b.node_state("p1.worktree_before") == "pending" and "request_entry" not in b.record["process"]


@cond_reads("record.process.request_entry", "loop.request_fixed_at")
def request_entry(v):
    """判定から入る run の周か（条件の関数。P1 の役の条件・素材の穴埋め・空差分の柵・依頼の移し替えが呼ぶ唯一の式——
    rules の中からは b.cond(ENTRY_BUILTIN) で呼ぶ）。

    入口の印が型どおりに在り、前の周までの P3 がまだ 1 ファイルも触っていない間だけ真。依頼の一覧の在否は見ない
    （途中の周の依頼で P1 を外さない）。入口が省くのは既存のコードへ P1 を回す費用で、修正差分の審査ではない——
    修正が入った次の周からは通常の run と同じく P1 が修正差分を見る"""
    if not _entry_marked(v):
        return False, "入口の印（process.request_entry）が無い——通常の run"
    at = v("loop.request_fixed_at", None)
    if at:
        return False, f"入口の印は在るが、{at} 周目の P3 が修正を入れた——入口の周は終わった"
    return True, "判定から入る run の周（入口の印が在り、修正がまだ 1 ファイルも入っていない）"


@cond_reads("record.process.request_entry", "loop.request_fixed_at", "round")
def entry_first_fix(v):
    """判定から入る run で、最初に修正が入った次の周か（条件の部品）。1 周目の差分が空だった run で、1 周目にしか
    走らない節（p0.parallel_pr）に修正の実ファイルをもう 1 度だけ見せる——1 周目の空の集合との交差の clean を運び続けない"""
    if not _entry_marked(v):
        return False, "入口の印（process.request_entry）が無い——通常の run"
    at, rnd = v("loop.request_fixed_at", None), v("round")
    return at == rnd - 1, f"判定から入る run で、最初に修正が入った周は {at}（今は {rnd} 周目）"


def request_wheres(b):
    """判定から入る run の周に、この周の判定に届く依頼の where の一覧（範囲を差分から取る P0 の節——先行議論・並行 PR——の
    範囲の読み口。判定から入る run の周は差分が空なので、依頼の where を範囲にする）。そうでない周は []——
    差分が在る周の範囲は差分で、依頼の where を足さない。正本は process.request_findings（_requests が型を当てる）"""
    if not b.cond(ENTRY_BUILTIN)[0]:
        return []
    reqs, _ = _requests(b, "request_findings")
    return [f["where"] for x in reqs for f in x["findings"]]


def _entry_skipped(b, n):
    """na の節が入口のせいで外れたか——入口の周で、同じ条件が今は偽で、入口の印を外した文脈（ENTRY_OFF）なら真。
    節の集合は graph の cond が正本（ここに節の名前を並べない）。条件の書き方に依らない——同じ 1 本の関数を 2 回評価する
    （以前は cond の JSON の木から入口の項を抜いていた）。別の条件でも外れていた節は、印を外しても偽なので通常の理由のまま"""
    c = n.get("cond")
    if not c or not b.cond(ENTRY_BUILTIN)[0] or b.cond(c)[0]:
        return False
    return b.cond(c, overlay=ENTRY_OFF)[0]


def _declared_faces(b, rnd):
    """その周に直さずに残すと宣言した穴と、検算していない手直し ——[{key, from, how}]。
    事前審査の穴（p3.fix の plan_faces の declared）・修正差分の穴（p3.delta_fix の declared）・2 回目の差分の穴（p3.delta_fix2 の全部——
    直したと言う行も、それを見る 3 回目は無い）・最後の関門が見つけた、振る舞いの変わる見逃し（p4.final_gates の equivalent 以外）。
    並行の線の分は周でなく版に属すので、ここでなく _lane_faces が渡す（コードの欠陥の疑い＝defect は人の依頼の入口へ。on_new_round）"""
    fix = b.output_of_round("p3.fix", rnd) or {}
    rows = [{"key": r["key"], "from": "p2.plan_review", "how": r["how"]} for r in fix.get("plan_faces") or [] if r["handled"] == "declared"]
    for p in DELTA_PASSES.values():
        for r in (b.output_of_round(p.fix, rnd) or {}).get("handled") or []:
            if r["handled"] == "declared" or p.last:
                rows.append({"key": r["key"], "from": p.fix, "how": r["how"], **({"unverified": True} if r["handled"] == "fixed" else {})})
    rows += [{"key": f"最後の関門 r{rnd}: {r['key']}", "from": "p4.final_gates", "how": f"{r['handled']}: {r['how']}"}
             for r in (b.output_of_round("p4.final_gates", rnd) or {}).get("handled") or [] if r["handled"] != "equivalent"]
    return rows


def on_new_round(b):
    rec, ls = b.record, b.loop_state
    ls["prev_questions"] = rec["questions"]
    ls["prev_units"] = rec["units"]
    ls["prev_scalars"] = rec.get("scalars", {})
    rec["round"] = b.round
    mutation_decl(b)   # 周の修正が宣言を書き換えた周も、次の周の役は今の宣言を読む
    rec["materials"] = {}
    rec["units"] = []
    rec["scalars"] = {}
    rec["reviews"] = {}
    rec["questions"] = []
    for k in ("r1_refire", "r2_refire", "open_units", "ledger_changed", "lines_ratio"):
        ls.pop(k, None)
    # stop.premise_check が resolved で返した実測を制約に足し、この周の R2 を回し直す（目的は動かさない）
    facts = ls.pop("facts_to_add", [])
    if facts:
        rec["process"].setdefault("constraints", []).extend(
            {"text": t, "measured_how": f"stop.premise_check の検算（round {b.round - 1}）", "kind": "実測"} for t in facts)
        ls["r2_refire_forced"] = True
    # 前の周の writer の異議（rejudge_requested）は次の周の p2.history が再審する
    ls["prev_rejudge"] = ls.pop("rejudge_requested", None)
    # 前の周に『残す』と宣言した穴と、もう一度は見ていない手直しを、次の周の判定者へ渡す（p2.history が 1 件ずつ振り分ける）。
    # 渡さないと記録に残るだけで、次の周の全体レビューがたまたま拾い直すのを待つ形になる
    # 並行の線（p3.delta_gates）が書き終えた結果のうち、線の中で閉じなかった見逃しもここで渡す——線は周を越えて走るので、
    # 書き終えた後の最初の周の頭が受け取る。線の行は全部、1 件ずつ振り分けを求める宣言の穴に載せ（p2.history が番号で振り分ける）、
    # テストでは閉じない見逃し（defect＝コードの欠陥の疑い）は下で依頼の入口（request_findings）にも積む（設計の文書 7b:
    # 並行の線の結果を判定へ渡す道は依頼の入口につなぐ——入口に載せても振り分けの柵は外さない）
    lane_rows = _lane_faces(b)
    lane_defects = [r for r in lane_rows if r.get(LANE_DEFECT)]
    ls["prev_declared_faces"] = _declared_faces(b, b.round - 1) + [{k: v for k, v in r.items() if k != LANE_DEFECT} for r in lane_rows]
    # 前の周の「一撃」を次の周に渡す——**効いたかを次の周が検算する**ため。一撃を選ぶ欄は前から在ったが、
    # 効いたかを測る工程が無く、同じクラスが 3 周続けて別の顔で出た（実測 2026-09-13: 判定者の one_shot が
    # 3 周とも同じ根＝「覆いの母数を誰も持たない」を指していたのに、毎周の閉じ方は名指しの 1 site だった）。
    # **「前の周に一撃が無い」と「渡し損ねた」を同じ空にしない。** optional の穴で受けていたとき、この工程の初回が
    # 空振りして誰も気づかなかった（実測 2026-09-13: プロンプトの {{?loop.prev_one_shot}} が空で描画され、盤面にも 0 件）。
    # 値は必ず入れ、無い周は無い理由を文字列で運ぶ——読む側（p2.history）は optional をやめてこれを必須の穴で受ける
    # **前の周に出した判定だけを読む**——最新を読むと、p2.history を省いた周の次に、2 周前の一撃が拾われる
    hist = b.output_of_round("p2.history", b.round - 1) or b.output_of_round("p2.diagnose", b.round - 1) or {}
    if hist.get("one_shot"):
        ls["prev_one_shot"] = {
            "round": b.round - 1, "text": hist["one_shot"],
            "closes": hist.get("one_shot_closes") or [],
            "check": hist.get("one_shot_check") or "",
            # 一撃が閉じると見込んだ単位の、前の周の母数（class_query.total）。今の周に数え直して減ったかを見る
            "totals": {u["key"]: (u.get("class_query") or {}).get("total")
                       for u in hist.get("units", []) if u.get("class_query")},
        }
    else:
        ls["prev_one_shot"] = {"round": b.round - 1, "text": None, "closes": [], "check": "", "totals": {},
                               "absent": f"round {b.round - 1} の判定に one_shot が無い（この周は検算する対象が無い——"
                                         "『届かなかった』ではない。届かない形なら engine が止める）"}
    # 前の周の P3 が実際に触ったファイル——**engine が持つ事実**（前の周の頭に固めた版 head_revs と今の版の木の差）から作る。
    # writer の申告（p3.fix の changes[].files）は照合の片側に降ろす（実測 2026-09-13: 実在しないファイル名の申告で全素材が
    # 再発火し、実際に編集した周が 0 件扱いで持ち越された——申告だけを見ていた）
    claimed = sorted({f for c in (b.output_of_round("p3.fix", b.round - 1) or {}).get("changes", []) for f in c.get("files", [])})
    measured = _files_changed_since(b, b.round - 1)
    ls["prev_fix_files"] = claimed if measured is None else measured
    if ls["prev_fix_files"]:
        ls.setdefault("request_fixed_at", b.round - 1)  # 最初に修正が入った周——入口の周はここで終わる（request_entry が読む。戻さない）
    # 前の周の依頼は判定済み（その扱いは units と台帳を通して p2.history が運ぶ）——この周の判定役に渡すのは、この周に積む依頼だけ。
    # 入口の周が続く間（修正がまだ 0 行）は移さない: P1 の素材が無い判定役から、依頼まで取り上げない
    if not b.cond(ENTRY_BUILTIN)[0]:
        cur, why_cur = _requests(b, "request_findings")
        past, why_past = _requests(b, "request_history")
        if cur and not (why_cur or why_past):
            rec["process"]["request_history"] = past + cur
            rec["process"]["request_findings"] = []
    # 履歴へ移した後に積む（前に積むと同じ呼び出しで履歴へ移り、この周の判定に届かない）。積めた行は、宣言の穴の同じ行に
    # 『同じ 1 件』と書く——判定者が 2 つの入口から別々の単位を立てない（振り分けの柵は to_unit でその単位を指せば満ちる）
    if _route_lane_defects(b, lane_defects):
        same = {r["key"] for r in lane_defects}
        for r in ls["prev_declared_faces"]:
            if r["key"] in same:
                r["how"] += LANE_SAME_ITEM
    if measured is not None and set(claimed) - set(measured):
        # 申告したが差分に現れないファイル——盤面に置くだけでは誰も読まないので、記録の process に周付きで残す（判定者と報告が読める）
        rec["process"].setdefault("fix_claim_mismatch", []).append({"round": b.round - 1, "claimed_not_in_diff": sorted(set(claimed) - set(measured))})
    for k in ("purpose_known", "purpose_unusable"):
        ls.pop(k, None)
    escalate_on_thrash(b)


def escalate_on_thrash(b):
    """**一方向のラチェット**——同じクラスが周をまたいで戻ったら、機械が自分で深い側へ上げる。下げない。

    research 側の「厚みの三段」と同じ規律（昇格は自律で自由・降格は依頼者の明示指定のみ）を review にも置く。
    review には段が無いので、上げるのは『処方の選び方』と『深さで切っている観点を全部走らせる』の 2 つ。
    引き金は判定者が機械可読で返す 2 欄（kind=thrash の問い・reburn_causes）。下げるのは人の手当てだけ
    （loop.py patch state.loop.escalated）——回す側が自分で浅くできると、作業を減らして得する側が深さを決める。
    """
    ls = b.loop_state
    if ls.get("escalated"):
        return  # 一度上げたら run の残り全部で効く（ラチェット）
    # **引き金は機械が持つ 2 つ。どちらかで上がる。**
    #
    # (1) キーの再燃——一度 info（閉じた）と判定されたキーが、後の周にまた [block] で戻っている数。
    #     判定者の任意欄（reburn_causes）を読んでいたとき、上げられる側の自己申告で深さが決まり、
    #     欄を埋めなければ永久に上がらなかった（この差分自身がその形で入り、判定で [block] になった）。
    # (2) **件数が落ちない**——[block] の件数が直近 STALL_ROUNDS 周にわたって 1 度も減っていない。
    #
    # (1) だけでは原理的に 0 件だった。**再燃は毎周ちがうキー文字列で来る**（判定者は同じクラスを別の site で
    # 立て直すので、完全一致の集合演算に一度も当たらない）——実測 2026-09-13: 6 周とも発火せず、
    # 台本を thrash|reburn|escalated|closed_keys で grep しても 0 件。
    # 一方、判定者は履歴を見たうえで「4〜5 周続く再燃を毎周ちがう key 文字列で並べている」と書き、
    # 機械の信号として**件数**を名指しした（「件数が落ちないことを機械が見ておらず…件数が落ちれば resolved にできる」）。
    # (2) は**クラスを同定しない**——閉じる速さが開く速さを上回っていないことだけを測るので、
    # 名前の付け方に依らない。実測の推移: r1=6 r2=9 r3=9 r4=13 r5=12 r6=16。
    reburn = sorted({u["key"] for u in ls.get("prev_units", []) if u.get("label") == "block"} & set(ls.get("closed_keys", [])))
    hist = [x["n"] for x in ls.get("block_counts", [])][-STALL_ROUNDS:]
    stalled = len(hist) >= STALL_ROUNDS and all(hist[i] >= hist[i - 1] for i in range(1, len(hist)))
    if not reburn and not stalled:
        return
    ls["escalated"] = {
        "round": b.round,
        # 前の周の判定文をここに入れない——p2.diagnose は履歴を渡さない節で、why に問いの key を入れると隔離が破れる
        "reburn_count": len(reburn),
        "block_counts": hist,
        "why": (f"一度 info（閉じた）と判定されたキーが、後の周にまた [block] で戻っている（{len(reburn)} 件。機械が数えた）"
                if reburn else
                f"[block] の件数が直近 {STALL_ROUNDS} 周で 1 度も減っていない（{hist}。機械が数えた）"
                "——閉じる速さが開く速さを上回っていない"),
        "effects": ["零処方の優先を外す（クラスを消す設計の処方を第一候補に並べさせる）",
                    "深さで切っている 4 節（p0.prior_decisions・p1.procedure_trace・p1.gate_efficacy・p1.test_double_fidelity）を条件に関わらず走らせる"],
    }
    b.record["process"]["escalated"] = ls["escalated"]


PROCEDURE_PATTERNS = (r"README", r"\.md$", r"\.sh$", r"^scripts/", r"^\.github/workflows/", r"Makefile", r"Dockerfile",
                      r"\.ya?ml$", r"^commands/", r"^hooks/")


@cond_reads("loop.changed_files")
def touches_procedures(v):
    files = v("loop.changed_files", [])
    hit = sorted({f for f in files for p in PROCEDURE_PATTERNS if re.search(p, f)})
    return bool(hit), (f"差分に手順書・スクリプト・CI 定義が {len(hit)} 件" if hit else "差分に手順書・スクリプト・CI 定義が無い")


@cond_reads("loop.prev_fix_files")
def prev_fix_touched(v):
    """前の周の P3 が 1 ファイルでも触ったか（条件の部品）。

    差分全体を見る素材（衛生・整合・出典・外部標準・手順の追跡など）の再発火を、役の自己申告 1 欄
    でなく **P3 が実際に触ったファイル**から決める。申告に依っていたとき、前の周の P3 が
    直した対象を見た素材が carried_over のまま前の周の主張を運び、閉じた欠陥が次の周に新規の [block] として
    生き返った（実測 2026-09-12: p1.provenance が r1 の主張を運び、判定者が取り下げるまで気づかれなかった）。
    """
    n = len(v("loop.prev_fix_files", None) or [])
    return bool(n), f"前の周の P3 が触ったファイルは {n} 件"


def _findings_vetted(rows):
    """目的監査の findings が**裏取りの柵を通った形**か（cite を持つか）。空は偽。
    **式はここ 1 か所。** 同じ式を assemble と条件の両方が持っていると、柵を締めた周に片方だけ
    古くなり、「材料としては使わないが走り直しもしない」という半端な状態で固まる。"""
    return all(isinstance(r, dict) and r.get("cite") for r in rows) if rows else False


def purpose_findings_vetted(b):
    """記録に残る目的監査の findings が、裏取りの柵を通った形か（assemble が読む口）"""
    return _findings_vetted(((b.record.get("process", {}).get("purpose_review", {}) or {}).get("findings")) or [])


@cond_reads("record.process.purpose_review")
def purpose_review_unvetted(v):
    """記録の目的監査が、裏取りの柵より前の形で凍っているか（条件の部品）。

    監査は 1 周目にしか走らないので、**柵が後から入った周でも判定は作り直されない**——旧形の
    findings 5 件が 9 周にわたって材料に載り、うち 4 件は現物に 0 件の字列を根拠にしていた（実測 r9）。
    assemble はそれを「材料として使わない」ところまでやったが、**走り直しの引き金が無い**ので
    記録はいつまでも古いままだった（実測 r10: 素の文字列 5 件が減らない）。

    引き金を『柵を通っていない判定が記録に在る』にしてあるのは、**通った判定は二度と走らない**ため
    ——不利な判定を引くたびに回し直す形にはならない（purpose_sources_changed と同じ規律）。
    """
    pr = v("record.process.purpose_review", None) or {}
    if not pr.get("verdict"):
        return False, "目的監査はまだ一度も走っていない"   # round==1 の側が拾う
    rows = pr.get("findings") or []
    if not rows:
        # **指摘 0 件は「柵を通っていない」ではない。** 『問題なし』は根拠を連れて来る必要が無いので、
        # 裏取り済みかの判定（空なら False）をそのまま引き金にすると**毎周走り直して止まらない**
        # （実測 r10: この形で検査が赤くなった）。空の『狭めている』を拒むのは purpose_findings_cited の仕事
        return False, "目的監査の指摘が 0 件（根拠を連れて来る物が無い）"
    if _findings_vetted(rows):
        return False, "目的監査の指摘は裏取りの柵を通った形"
    return True, "目的監査の指摘が裏取りの柵より前の形で凍っている"


@cond_reads("out.p0.purpose", "loop.prev_fix_files")
def purpose_sources_changed(v):
    """目的テキストの出典文書を、前の周の P3 が触ったか（条件の部品）。

    **目的テキストそのものは動かさない（凍結の規律）。動かすのは「目的監査をもう一度走らせるか」だけ。**
    以前は p0.purpose_review が once で、その判定（狭めている／妥当）は record.process に着地し、
    on_new_round は process をリセットしないので、**実態をどう直しても round 1 の判定が run の残り全周を
    縛った**（実測 2026-09-13: 名乗りの 4 出典は既に直っているのに R2 が 5 周とも走らず、この run が収束
    できない本当の理由がこれだった）。引き金は役の自己申告でなく **P3 が実際に触ったファイル**にする
    ——判定が不利なときに回し直して有利な方を採る形を作らないため（引き金の定義が緩むと規律が壊れる）。
    """
    out = v("out.p0.purpose", None) or {}
    if "source_files" not in out:
        # **欄そのものが無いのは「触っていない」ではなく「決められない」。** p0.purpose は once なので
        # 出力は 1 周目で凍る——後から schema にこの欄を足しても永久に現れない。ここを偽に倒すと
        # 目的監査の走り直しが静かに永久に止まる（実測 2026-09-13: この run は 6 周とも R2 が走らず、
        # 収束できない本当の理由がこれだった）。**偽を返すのは同じでも、返した理由を残す**——
        # engine の frozen_outputs_stale が節ごとの痕跡を持ち、ここは「この引き金が測れなかった」を持つ（周ごとに 1 行）
        why = "p0.purpose の出力に source_files が無い（once で凍った周の schema には無かった欄）"
        v.unevaluable("purpose_sources_changed", why)
        return False, why
    srcs = out.get("source_files") or []
    if not srcs:
        # 欄は在って空＝「出典ファイルを持たない目的」。これは測れた上での偽なので痕跡は要らない
        return False, "目的テキストが出典ファイルを持たない"
    hit = sorted(set(v("loop.prev_fix_files", None) or []) & set(srcs))
    return bool(hit), (f"前の周の P3 が目的の出典 {hit} を触った" if hit else "前の周の P3 は目的の出典を触っていない")


EMPTY = ("なし", "無し", "ない", "無い", "特になし", "n/a", "none", "-", "未確認", "不明",
         "todo", "未実施", "未測定", "後で")  # 「書いていない」と同じ扱いにする語

# R が unverifiable を返した周に機械が立てる台帳の行の見出し。**R ごとに何が取れなかったかを書く**
# ——定数 1 文にすると、原因が違う周にも同じ文が出て、converge がそれをそのまま人に見せる（実測 2026-09-13）
ASK_KEYS = {
    "R1": "累積差分の最小性を独立に測れない（R1 unverifiable）——測る材料を人が示すか、未収束のまま報告するか",
    "R2": "元の目的を独立に取れない（R2 unverifiable）——目的の出典を人が示すか、未収束のまま報告するか",
    "R3": "文書横断の整合を独立に確かめられない（R3 unverifiable）——確かめる材料を人が示すか、未収束のまま報告するか",
    "R4": "横断リスクと消えた能力を独立に確かめられない（R4 unverifiable）——基準点の材料を人が示すか、未収束のまま報告するか",
}


def blank(s, min_len):
    """役が埋める自由文が「空同然」か。**表と長さの両方で見る。**

    以前は判定が 5 か所にインラインで散り、表も EMPTY / EMPTY_HIT の 2 本に割れていた。
    実測 2026-09-13: 両表の最長語は 4 文字なので、`X in EMPTY or len(X) < 10` の**表の照合は
    長さ検査に完全に包含されて一度も効いていなかった**（表が効くのは長さ検査を持たない 1 か所だけ）。
    さらに 1 か所だけ `.lower()` が抜けており、`N/A`・`NONE`・`TODO`・`未実施` が素通りしていた。
    表を 1 本に畳み、正規化をここに寄せる——閾値は欄ごとに違ってよいので引数で受ける。
    """
    t = (s or "").strip()
    return t.lower() in EMPTY or len(t) < min_len

STALL_ROUNDS = 3  # [block] の件数がこの周数だけ減らなければ、ラチェットが上がる（クラスを同定しない引き金）
REJUDGE_MAX = 3  # 往復の上限。依頼者の指定（2026-09-13）: 2〜3 回まで許し、超えたら新しい別の目が会話に参加して判定する


@cond_reads("loop.rejudge_requested", "loop.rejudge_rounds", "round")
def _rejudge(v):
    """今の周に回す側が出した異議と、**その周の**往復の回数。

    **異議と回数は同じ尺度で持つ。** 以前は異議だけを周で絞り、回数は run 全体の通し番号を素通しで返していた
    （`rejudge_rounds` は rejudge_output が増やすだけで、on_new_round のリセットの一覧に入っていなかった）。
    帰結: **どれか 1 周で上限まで往復すると、run の残り全部で p2.rejudge が 1 度も発火せず、新しい異議は
    1 回目からいきなり第三の目へ行く**——rejudge_exhausted の注記は「第三の目は常設しない」と書くのに、
    上限を超えた後は事実上の常設になる（実測 2026-09-13: 生きている盤面で述語を直接呼び、
    rejudge_rounds=3 ＋ 今の周に初めての異議 → rejudge_open=False / rejudge_exhausted=True を確認）。
    graph の `when` も述語の docstring も「その周」と名乗っていたので、**名乗りの側でなく実装を合わせる**。
    """
    rnd = v("round")
    r = v("loop.rejudge_requested", None) or {}
    n = v("loop.rejudge_rounds", None) or {}
    if not isinstance(n, dict):  # 旧い盤面（整数で持っていた run）を読み替える
        n = {"round": rnd, "n": int(n)}
    return (r if r.get("round") == rnd else {}), (int(n.get("n") or 0) if n.get("round") == rnd else 0)


@cond_reads(*_rejudge.reads)
def rejudge_open(v):
    """回す側が今の周に異議を出し、往復が上限未満か（条件の関数）。

    **異議を次の周へ送らない口。** 以前は rejudge_requested を次の周の p2.history が読む形しか無く、
    同じ周に閉じる辺が graph に 0 本だった——実運用では engine の外の会話で往復が起き、記録にも trace にも
    残らなかった（実測 2026-09-13: この run で往復が 5 回起き、残ったのは loop.py patch を通した 1 件だけ。
    そのうち 2 回は engine のコードが判定の最中に変わる重さだったのに、盤面は何も止めなかった）。
    依頼者の指定の 4 条件のうち、ここが担うのは「往復が記録に残る」——done が trace.jsonl と state に残す。
    """
    r, n = _rejudge(v)
    if not r:
        return False, "回す側は今の周に異議を出していない"
    return n < REJUDGE_MAX, f"今の周の異議に往復 {n} 回（上限 {REJUDGE_MAX}）"


@cond_reads("record.units")
def units_open(v):
    """今の周に直す単位（[block]・do-now）が在るか（条件の関数）。修正案とその事前審査は直す物が在る周にだけ立つ"""
    n = sum(1 for u in v("record.units", None) or [] if v.validator.is_open(u))
    return bool(n), f"今の周に直す単位（[block]・do-now）が {n} 件"


class DeltaPass(NamedTuple):
    """修正差分の往復 1 回ぶんの構造。**節の名前の対応はこの表だけが持ち**、ほかは全部ここから引く"""
    state_key: str   # loop_state の鍵（その回の差分 {round, file, files, rev}）
    cut: str         # 差分を切り出す節（driver）
    review: str      # 差分を見る節
    owed: str        # 手直しが答える義務を組む節（driver）
    owed_key: str    # 義務の loop 値の鍵——手直しの節はこの値をそのまま貼り、答え合わせも同じ値で行う
    fix: str         # 手直しの節
    last: bool       # 最終の回か（ここで直した物は、次の周の判定者が検算する）


# 回 → DeltaPass。1 回目は修正（p3.fix）の差分、2 回目は手直しの差分。3 回目は無い
DELTA_PASSES = {1: DeltaPass("fix_delta", "p3.fix_delta", "p3.delta_review", "p3.delta_owed", "delta_owed", "p3.delta_fix", False),
                2: DeltaPass("fix_delta2", "p3.fix_delta2", "p3.delta_review2", "p3.delta_owed2", "delta_owed2", "p3.delta_fix2", True)}
DELTA_PASS_OF = {nid: n for n, p in DELTA_PASSES.items() for nid in (p.cut, p.review, p.owed, p.fix)}


def _in_round(d, rnd):
    """周に属する loop 値（{round, …}）を今の周の物だけ読む。前の周の値は None"""
    d = d or {}
    return d if d.get("round") == rnd else None


def _delta_of(b, n):
    """n 回目の修正差分（{round, file, files, rev}）——今の周に書いた物だけ。前の周の値は None。
    **状態は周に属し、読む側で周を照らす**（Gerrit の票が patch set に属し、新しい patch set で読み直すのと同じ形）。
    周の頭で消す形は、消し忘れた鍵や同じ周の撃ち直しに効かない"""
    return _in_round(b.loop_state.get(DELTA_PASSES[n].state_key), b.round)


def _owed_rows(b, n):
    """n 回目の手直しが答える義務——[{key, from, text}]。差分レビューの穴と塞がっていない検算（closed=false）だけ。
    **変異の検算（p3.delta_gates）の見逃しは入れない**——検算は周の締めを止めない並行の線で、見逃しへの答えも線が持つ
    （実測 2026-09-24: 4 周目は検算 172 分と見逃しへの手直し 167 分で、周の約 8 時間のうち約 5.7 時間を締めの待ちが占めた。
    見逃し 109 本の手直しがコードに触れたのは docstring の 1 行だけ）。**計算はここ 1 本**で、盤面に置くのは delta_owed（driver）だけ"""
    p = DELTA_PASSES[n]
    rv = b.output_of_round(p.review, b.round) or {}
    rows = [{"key": f["key"], "from": p.review, "text": f"{f['kind']} {f['where']}:「{f['cite']}」——{f['why']}"} for f in rv.get("faces") or []]
    rows += [{"key": c["key"], "from": f"{p.review}.checks", "text": f"塞いだと言われたが、差分で塞がっていない——{c['why']}"}
             for c in rv.get("checks") or [] if c["closed"] is False]
    return rows


def delta_owed(b, nid):
    """手直しの前: 答える義務を 1 本の loop 値（DeltaPass.owed_key）に組んで盤面に置く（driver の builtin）。
    **手直しの役に見せる値と、手直しを起こす条件・答え合わせが引く値を同じ物にする**——義務を rules が、見せる物を graph の reads と
    プロンプトが別々に持っていたとき、4 周目に義務へ足した成分（塞がっていない検算）が役に 1 度も見えず、答えるべき key を知る道が無かった"""
    n = DELTA_PASS_OF[nid]
    rows = _owed_rows(b, n)
    b.loop_state[DELTA_PASSES[n].owed_key] = {"round": b.round, "rows": rows}
    return {"ok": True, "owed": len(rows)}


def _delta_owed(b, n):
    """n 回目の手直しが答える義務の key——delta_owed が今の周に置いた値だけ（前の周の値は読まない）。
    手直しを起こす条件（delta_faces_open）・手直しの答え合わせ（delta_fix_output）がここから引き、答えは _declared_faces で次の周へ渡る"""
    return _owed_key_set(_in_round(b.loop_state.get(DELTA_PASSES[n].owed_key), b.round))


def _owed_key_set(d):
    """義務の loop 値（delta_owed の置いた {round, rows}）から key の集合を引く式の正本（条件の側も同じ物を呼ぶ）"""
    return {r["key"] for r in (d or {}).get("rows") or []}


@cond_reads("loop." + DELTA_PASSES[1].state_key, "round")
def fix_delta_nonempty(v):
    """この周の修正が差分を作ったか（条件の部品。1 回目の差分レビューを起こす条件の片方）"""
    n = _round_files(v, "loop." + DELTA_PASSES[1].state_key)
    return bool(n), f"この周の修正の差分は {n} ファイル"


def _claimed_closed_from(v, n):
    """_claimed_closed の条件の側（宣言した欄だけで読む）。式は _closed_keys の 1 本"""
    src = "cur.p3.fix" if n == 1 else f"cur.{DELTA_PASSES[n - 1].fix}"
    return _closed_keys(v(src, None), n)


@cond_reads(*fix_delta_nonempty.reads, "cur.p3.fix")
def delta_review_due(v):
    """1 回目の差分レビューを起こすか（条件の関数）: 今の周の差分が空でない、または検算すべき『塞いだ』申告が在る。
    差分の無い申告を誰も検算しない形を作らない"""
    ok, why = fix_delta_nonempty(v)
    if ok:
        return ok, why
    k = len(_claimed_closed_from(v, 1))
    return bool(k), f"{why}、修正が塞いだと言う事前審査の穴は {k} 件"


@cond_reads("loop." + DELTA_PASSES[2].state_key, "round", "cur." + DELTA_PASSES[1].fix)
def delta_review2_due(v):
    """2 回目の差分レビューを起こすか（条件の関数）: 手直しの差分が空でない、または手直しが直したと言う穴が在る"""
    n = _round_files(v, "loop." + DELTA_PASSES[2].state_key)
    k = len(_claimed_closed_from(v, 2)) if not n else 0
    return bool(n or k), f"手直しの差分は {n} ファイル" + ("" if n else f"、手直しが直したと言う穴は {k} 件")


def _owed_keys(v, n):
    """_delta_owed の条件の側（宣言した欄だけで読む）"""
    return _owed_key_set(_in_round(v("loop." + DELTA_PASSES[n].owed_key, None), v("round")))


@cond_reads("loop." + DELTA_PASSES[1].owed_key, "round")
def delta_faces_open(v):
    """1 回目の手直しを起こすか（条件の関数）: 答える義務が在るか"""
    k = len(_owed_keys(v, 1))
    return bool(k), f"修正差分のレビューと検算が挙げた、手直しが答える義務は {k} 件"


@cond_reads("loop." + DELTA_PASSES[2].owed_key, "round")
def delta2_faces_open(v):
    """2 回目の手直しを起こすか（条件の関数）: 答える義務が在るか"""
    k = len(_owed_keys(v, 2))
    return bool(k), f"手直しの差分のレビューが挙げた、2 回目の手直しが答える義務は {k} 件"


@cond_reads("cur." + DELTA_PASSES[1].fix)
def delta_fixed(v):
    """修正差分の穴を今の周に直したか（条件の関数）——直した手直しにだけ、もう 1 回差分レビューを当てる"""
    k = sum(1 for r in (v("cur." + DELTA_PASSES[1].fix, None) or {}).get("handled") or [] if r["handled"] == "fixed")
    return bool(k), f"手直しが今の周に直した（fixed）穴は {k} 件"


@cond_reads(*_rejudge.reads)
def rejudge_exhausted(v):
    """往復が上限に達しても決着しない周か（条件の関数）。**第三の目は常設しない**——ここでだけ立つ。"""
    r, n = _rejudge(v)
    if not r:
        return False, "回す側は今の周に異議を出していない"
    return n >= REJUDGE_MAX, f"今の周の異議に往復 {n} 回（上限 {REJUDGE_MAX}）"


# ---------------------------------------------------------------- 変異の検算の並行の線と最後の関門
# **検算は周の締めを止めない。** 変異 1 本ごとにテスト一式を回す検算と、その見逃しへのテストの書き足しが、周の締め
# （P4・R1〜R4）と次の周の前に必ず待たれていた（実測 2026-09-24: 4 周目は検算 172 分・手直し 167 分で、周の約 8 時間の
# うち約 5.7 時間。見逃し 109 本の手直しがコードに触れたのは docstring の 1 行だけで、残りはテストの追加か等価の宣言）。
# 線は Google の差分への変異の検算（Petrović & Ivanković, ICSE-SEIP 2018 §2.3.1・§3）と同じ形——審査と非同期に撃ち、
# 生き残りを次の審査の所見として出す。**engine は線を追わない**（Temporal の Parent Close Policy ABANDON と同じ——親の周が
# 閉じても子の線は影響を受けない）。線の結果は撃った版で鍵付けした置き場（盤面の lanes/）に落ち、次の周の機械の節が
# 版ごとに読む。途中の版で撃った結果は、その版の結果でしかない——収束の前に最終のコードで撃ち直す（p4.final_gates）
LANE_HANDLED = ("tests_added", "equivalent", "needs_test", "defect")   # 見逃しへの答え。schema（$defs.lane_reply）の enum と同じ語
LANE_OPEN = ("needs_test", "defect")   # 線の中で閉じなかった答え——次の周の判定へ渡す（needs_test は線がテストを書けなかった物）
# 線の台帳の状態。abandoned は回す側が止めた線（Temporal の Cancelled と同じく running と別の閉じた状態）——engine は線を追わないので、
# 止めた回す側が loop.py patch で state と理由 why を書く。止めた後に届いた結果は重ねない
LANE_STATES = ("running", "merged", "conflict", "unusable", "abandoned")
LANE_ROW = ("round", "result", "patch", "state")
# **変異の検算を合流でまとめる run**（init --input gates=merge）。並べた run がそれぞれ撃つと、合流した版での撃ち直しと
# 負荷を食い合う（実測 2026-09-25: 4 本が各自撃って負荷 99）。選んだ run は P1 のゲートの検算（p1.gate_efficacy）も線
# （p3.delta_gates）も最後の関門（p4.final_gates）も条件外で閉じ、収束の手前で止まる（converge の gates_deferred）——検算は消さず、
# 合流した版を gates=merge 無しの run で回して撃つ（GitHub の merge queue と同じ形: 重い検査はまとめた版に対して走らせる）。
# P1 の検算も外すのは人の決定（2026-09-25『変異テストは並べた run の中では撃たず、合流した版でまとめて撃つ』）
GATES_MERGE = "merge"   # inputs.gates の値。これ以外の値は init で拒む（check_inputs）
GATES_MERGE_WHY = "変異の検算は合流した版でまとめて 1 回撃つ（init --input gates=merge）"


def _unproven(arms):
    """覆いの証拠にならない腕——赤・対照の緑・当たりの証拠のどれかが欠けた腕の名前。返答の欄（red_confirmed・control_green・
    hit_evidence）の読み方はここ 1 本で、gate_arms_all_red も同じ物を読む。欄を組むのは実行器（このリポジトリなら
    tests/mutate.py --gate-efficacy。欄の正本は実行器の proven）で、rules は組み直さない"""
    return [a["arm"] for a in arms if not (a.get("red_confirmed") and a.get("control_green") and not blank(a.get("hit_evidence"), 10))]


def gates_cut(b, nid):
    """周の締めの前（修正と手直しが済んだ所）: この周のコードの最後の姿を固め、並行の線が撃つ範囲（周の頭の版 → この版）と、
    線の結果の置き場を置く（loop.gates_cut）。範囲が空でなければ線を台帳（loop.lanes。版 → 置き場）に載せる。
    固め方は採点する版と同じ _snapshot 1 本。**撃つ範囲は周の頭から**——修正（p3.fix）だけでなく 1 回目・2 回目の手直しが
    足した分岐も入る（以前は 2 回目の手直しをどの周の撃ち手も撃たず、次の周の頭の自動の腕で拾っていた）"""
    ls = b.loop_state
    frm = (ls.get("head_revs") or {}).get(str(b.round))
    if not frm:
        return {"ok": False, "problems": [f"{nid}: この周の頭の版が無い（p1.worktree_before が固める）——線が撃つ範囲の起点が決まらない"]}
    try:
        snap = _snapshot(f"graphloops gates r{b.round}")
    except Reject as e:
        return {"ok": False, "problems": [str(e)]}
    names = git("diff", "--name-only", "-z", frm, snap)
    if names is None:
        return {"ok": False, "problems": [f"git diff {frm[:12]} {snap[:12]} が取れない——線が撃つ範囲を測れない"]}
    files = [x for x in names.split("\0") if x]
    d = b.dir / "lanes"
    d.mkdir(exist_ok=True)
    tag = f"r{b.round}-{snap[:12]}"
    # 置き場は版で鍵付けする（周の番号も添えるのは読む人のため）。結果の型は graph が正本で、線の役にはここから貼る
    # 足したテストの patch の置き場はここで決めない——任せ先は sandbox の中で盤面に書けないので、自分の写しの側に置いて
    # 結果の patch の欄で名指しする（lane_merge はその欄を読む）。結果そのものは engine が置き場へ置く（launch の result_to）
    cut = {"round": b.round, "from": frm, "rev": snap, "files": files, "result": str(d / f"{tag}.json")}
    ls["gates_cut"] = {**cut, "reply_schema": _lane_schema(b)}
    if files and ls.get("gates") != GATES_MERGE:   # 合流でまとめる run は線を立てない（台帳に running の線を載せない）
        ls.setdefault("lanes", {})[snap] = {**{k: v for k, v in cut.items() if k != "files"}, "state": "running"}
    return {"ok": True, "rev": snap, "files": files}


MUTATION_UNDECLARED = ("対象リポジトリの宣言（{decl}）に mutation の段が無い——在りかと呼び方は対象リポジトリの側（README・CONTRIBUTING・"
                       "CI 定義・対象リポジトリの REVIEW.md など）が名指しする物を探せ（このプロンプトは道具の名前と引数の綴りを持たない）")


def mutation_decl(b):
    """変異の実行器と腕の一覧の名指しを、役に貼る 1 段落にして loop.mutation_decl に置く（init と周の頭）。宣言の mutation の段が在れば
    その値、無い・読めなければ対象リポジトリの側を探させる散文（宣言の無いリポジトリの道）。3 本の指示書はこの穴で受ける"""
    root = _repo_root()
    d = declared_checks(root) if root else None
    m = (d or {}).get("mutation")
    if m:
        text = (f"対象リポジトリの宣言 {DECL_NAME} の mutation の段——実行器の呼び方の頭 {json.dumps(m['argv'], ensure_ascii=False)}・"
                f"腕の一覧 {m['arms']}（口の綴りは実行器の --help が正本）")
    else:
        text = MUTATION_UNDECLARED.format(decl=DECL_NAME)
        err = (d or {}).get("mutation_error") or (d or {}).get("error")
        if err:
            text += f"（宣言は在るが mutation の段を読めない: {err}）"
    b.loop_state["mutation_decl"] = {"declared": bool(m), "text": text}


def _lane_schema(b):
    """線の結果の型——graph の p3.delta_gates の result_schema（$defs.lane_reply を展開した物）。受領の型（schema）と別に持つ:
    受領は線を立てた事実で、結果は線が後で置き場に書く物"""
    return b.nodes["p3.delta_gates"]["result_schema"]


def _gates_cut(b):
    """この周に固めた線の範囲（前の周の値は None）——_delta_of と同じく、読む側で周を照らす"""
    c = b.loop_state.get("gates_cut") or {}
    return c if c.get("round") == b.round else None


@cond_reads("loop.gates_cut", "round")
def gates_cut_nonempty(v):
    """線を立てるか（条件の関数）: この周のコードが周の頭から変わったか"""
    n = _round_files(v, "loop.gates_cut")
    return bool(n), f"この周のコードは周の頭から {n} ファイル変わった"


@cond_reads("loop.gates")
def gates_merge(v):
    """変異の検算を合流でまとめる run か（条件の部品。lane_due・final_gate_due・gate_efficacy_due が読む）"""
    got = v("loop.gates", None)
    return got == GATES_MERGE, (GATES_MERGE_WHY if got == GATES_MERGE else "変異の検算をこの run で撃つ（init --input gates=merge が無い）")


@cond_reads(*gates_merge.reads, *gates_cut_nonempty.reads)
def lane_due(v):
    """線を立てるか（p3.delta_gates の条件）: 合流でまとめる run でなく、この周のコードが周の頭から変わったとき"""
    merged, why = gates_merge(v)
    return (False, why) if merged else gates_cut_nonempty(v)


def _lane_errors(b, out, rev, final):
    """線（final=False）・最後の関門（final=True）の返答の整合——型の後に当てる。見逃した腕に全部 1 度だけ答え、
    撃った版が名乗りどおり。最後の関門は作業ツリーに書かない（tests_added と patch を持たない）"""
    errs = []
    if out.get("rev") != rev:
        errs.append(f"撃った版 {str(out.get('rev'))[:12]} が名指しの版 {rev[:12]} と違う")
    missed = {f"arm:{a}" for a in _unproven(out.get("arms") or [])}
    rows = out.get("handled") or []
    errs += _keys_once(rows, "handled")
    got = {r["key"] for r in rows}
    errs += [f"見逃した腕 '{k[:50]}' に答えが無い" for k in sorted(missed - got)]
    errs += [f"handled の '{k[:50]}' は見逃した腕に無い" for k in sorted(got - missed)]
    added = [r["key"] for r in rows if r["handled"] == "tests_added"]
    if final and (added or out.get("patch")):
        errs.append(f"最後の関門は作業ツリーに書かない——テストが要る見逃しは needs_test で返せ（tests_added: {added[:3]}）")
    if not final and added and not (out.get("patch") and pathlib.Path(out["patch"]).is_file()):
        errs.append(f"tests_added の行 {added[:3]} が在るのに、足したテストの patch（{out.get('patch')!r}）が無い")
    # テスト一式の緑は役の申告（suite）で受けない——最後の関門の版の一式は同じ周の p4.ci を engine が走らせた結果
    # （_converge_ready）、線が足したテストは合流した周の p4.ci が走らせる
    return errs


def _lane_result(b, lane):
    """線の結果（置き場のファイル）を読む ——（結果, 誤り）。まだ無ければ（None, []）＝走っている。
    **読むのは書き終えた物だけ**——線は <置き場>.tmp に書いてから置き場へ移す（途中の書きかけを読まない）"""
    p = pathlib.Path(lane["result"])
    if not p.is_file():
        return None, []
    # engine の read_json は読めないと die する——線の結果は engine の外で書かれるので、壊れた 1 本で周を止めない
    try:
        out = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        return None, [f"結果が読めない（{e}）"]
    if not isinstance(out, dict):
        return None, [f"結果が JSON のオブジェクトでない（{type(out).__name__}）"]
    errs = validate_schema(out, _lane_schema(b))
    return out, errs or _lane_errors(b, out, lane["rev"], final=False)


LANE_DEFECT = "_defect"   # _lane_faces の行の印（on_new_round が依頼の入口へも積む行を選び、宣言の穴に載せる前に外す）
LANE_ORIGIN = "並行の線（変異の検算とテストの書き足し。人の依頼ではなく機械の線の結果）"
LANE_PROVENANCE = "【並行の線の結果——人でなく、変異の検算の線が見つけた見逃し。役の観察と同じく反証の対象】"
LANE_SAME_ITEM = "（同じ 1 件を依頼の入口にも where＝この key で積んだ——直す単位は 1 つにまとめ、to_unit はその単位を指せ）"


def _route_lane_defects(b, rows):
    """並行の線が見つけた、テストでは閉じない見逃し（defect）を、この周の判定に人の依頼の入口（request_findings）で届ける
    ——出どころは線（LANE_ORIGIN）で、本文の頭に人の依頼でないことを書く。同じ行は宣言の穴にも載る（on_new_round）ので、
    依頼の欄が崩れていて積めない回も振り分けからは落ちない。積んだかを返す"""
    if not rows:
        return False
    cur, why = _requests(b, "request_findings")
    if why:   # 依頼の欄が崩れていて積めない——行は宣言の穴に載っているので、振り分けからは落ちない
        return False
    b.record["process"]["request_findings"] = cur + [{"round": b.round, "origin": LANE_ORIGIN, "findings": [
        {"where": r["key"], "text": LANE_PROVENANCE + r["how"],
         "mechanism": "並行の線（p3.delta_gates）が撃った腕が見逃され、線の中でテストを足しても閉じないと答えた（defect）。宣言の穴の同じ key の行と同じ 1 件"}
        for r in rows]}]
    return True


def _lanes(b):
    """線の台帳を読む口 ——（[(版, 行)] 周の順, [(版, 誤り)]）。台帳を読む所は全部ここを通る。止めた線は回す側が loop.py patch で
    書く（rules を通らない）ので、_requests と同じく読む側で行の形を当て、崩れた行は読まずに誤りとして返す"""
    good, bad = [], []
    for rev, lane in (b.loop_state.get("lanes") or {}).items():
        row = lane if isinstance(lane, dict) else {}
        miss = [k for k in LANE_ROW if k not in row]
        if miss:
            bad.append((rev, f"欄 {miss} が無い"))
        elif not isinstance(row["round"], int) or row["state"] not in LANE_STATES:
            bad.append((rev, f"round が整数でないか、state {row['state']!r} が {LANE_STATES} に無い"))
        elif row["state"] == "abandoned" and blank(row.get("why"), 4):
            bad.append((rev, "止めた線（abandoned）に理由 why が無い"))
        else:
            good.append((rev, row))
    return sorted(good, key=lambda kv: kv[1]["round"]), bad


def _lane_faces(b):
    """線の結果のうち、まだ判定へ渡していない物を宣言の穴の行にする（{key, from, how}）。渡した線に印を付ける（1 度だけ）。
    線の中で閉じなかった見逃し（needs_test・defect）・読めない／型に合わない結果・合流で当たらなかった patch が行になる。
    走っている線は渡さない（次の周の頭でもう一度見る）"""
    rows = []
    good, bad = _lanes(b)
    told = b.loop_state.setdefault("lanes_bad_delivered", [])
    for rev, why in bad:
        if rev not in told:
            told.append(rev)
            rows.append({"key": f"線 @{str(rev)[:12]}: 台帳の行が読めない", "from": "p3.delta_gates",
                         "how": f"{why}——線の台帳（loop.lanes）の手当て（loop.py patch）を確かめよ。この行は合流も要約もしない"})
    declared_mut = (b.loop_state.get("mutation_decl") or {}).get("declared")
    for rev, lane in good:
        if lane.get("delivered") or lane["state"] == "abandoned":
            continue
        tag = f"線 r{lane['round']}@{rev[:12]}"
        if lane["state"] == "conflict":
            rows.append({"key": f"{tag}: テストの patch が当たらない", "from": "p3.delta_gates",
                         "how": f"合流（p3.lane_merge）で {lane['patch']} が今の作業ツリーに当たらなかった（{lane.get('why', '')[:200]}）——p3.fix が手で重ねたかを確かめよ"})
            lane["delivered"] = True
            continue
        out, errs = _lane_result(b, lane)
        if out is None and not errs:
            continue
        lane["delivered"] = True
        if errs:
            rows.append({"key": f"{tag}: 結果が使えない", "from": "p3.delta_gates", "how": "; ".join(errs)[:600]})
            continue
        if not out.get("arms") and declared_mut:
            # 撃てた腕 0 本を見逃し 0 本と同じ形で運ばない。宣言の無いリポジトリの 0 本は記録（process.lanes の arms）にだけ残す
            rows.append({"key": f"{tag}: 撃てた腕が 0 本", "from": "p3.delta_gates",
                         "how": "対象リポジトリの宣言に変異の実行器が在るのに、線は腕を 1 本も撃っていない——見逃し 0 本とは違う。"
                                "最後の関門が最終の版で撃ち直す"})
        rows += [{"key": f"{tag}: {r['key']}", "from": "p3.delta_gates", "how": f"{r['handled']}: {r['how']}",
                  **({LANE_DEFECT: True} if r["handled"] == "defect" else {})}
                 for r in out["handled"] if r["handled"] in LANE_OPEN]
    return rows


def lane_merge(b, nid):
    """修正の前: 書き終えた線のうち未合流の物の、足したテストの patch を作業ツリーに重ねる（git apply。index は触らない）。
    重ねたテストは周の頭の版より後・修正より前に入るので、この周の修正差分（p3.fix_delta）に載り、差分レビューの目に入る。
    当たらない patch は重ねず、p3.fix に見せ（loop.lane_merge.conflicts）、次の周の判定へも渡す。結果の使えない線は重ねない"""
    ls = b.loop_state
    merged, conflicts = [], []
    for rev, lane in _lanes(b)[0]:
        if lane["state"] != "running":   # 止めた線（abandoned）に後から届いた結果も重ねない
            continue
        out, errs = _lane_result(b, lane)
        if out is None and not errs:
            continue
        if errs:
            lane["state"] = "unusable"
            continue
        patch = out.get("patch") or ""
        if not patch or not pathlib.Path(patch).is_file() or not (read_capped(patch, READ_CAP)[0] or b"").strip():
            lane["state"] = "merged"
            continue
        if git("apply", "--check", patch) is None:
            lane.update(state="conflict", why="git apply の試し当てが通らない", patch=patch)
            conflicts.append({"rev": rev, "round": lane["round"], "patch": patch})
            continue
        if git("apply", patch) is None:
            return {"ok": False, "problems": [f"{nid}: {patch} は試し当てを通ったのに git apply が落ちた——作業ツリーを確かめよ"]}
        lane["state"] = "merged"
        merged.append({"rev": rev, "round": lane["round"], "patch": patch})
    ls["lane_merge"] = {"round": b.round, "merged": merged, "conflicts": conflicts}
    return {"ok": True, "merged": len(merged), "conflicts": len(conflicts)}


def lane_summary(b):
    """線の台帳の要約（記録の process.lanes へ）——止めた run の報告からも、走り終えていない線と閉じなかった見逃しが見えるように"""
    rows = []
    good, bad = _lanes(b)
    for rev, lane in good:
        out, errs = (None, []) if lane["state"] == "abandoned" else _lane_result(b, lane)
        # arms＝撃てた腕の本数（結果がまだ無い・使えない・止めた線は None）——0 本と見逃し 0 本を分ける
        rows.append({"round": lane["round"], "rev": rev, "state": lane["state"],
                     "arms": len(out.get("arms") or []) if out and not errs else None,
                     "open": [r["key"] for r in (out or {}).get("handled") or [] if r["handled"] in LANE_OPEN] if not errs else [],
                     **({"why": lane["why"]} if lane["state"] == "abandoned" else {}),
                     **({"errors": errs[:3]} if errs else {})})
    rows += [{"rev": rev, "state": "unreadable", "errors": [why]} for rev, why in bad]
    return rows


def _ci_by_engine(checks, rnd):
    """この周の CI（p4.ci）の結果を engine が走らせて得たか。任せ先の周（宣言の無いリポジトリ）の clean は自己申告で、
    走り切る前に読んだ clean と見分けられない（実測 2026-09-25: 572 件の途中の 537 件で clean）"""
    c = (checks or {}).get("p4.ci") or {}
    return c.get("round") == rnd and c.get("by") == "engine"


def _converge_ready(record_out, local_checks, by_engine):
    """検証器が阻害なし（p4.record の branch が converged）で、この周の CI が緑で、その緑を engine が走らせて得た。最後の関門の
    条件と converge が同じ 1 本を読む（record_out はこの周の p4.record の出力、local_checks は local_checks の素材の status を
    返す引き手、by_engine は _ci_by_engine を返す引き手——短絡で後に読む）"""
    return (record_out or {}).get("branch") == "converged" and local_checks() == "clean" and by_engine()


def _would_converge(b):
    return _converge_ready(b.output_of_round("p4.record", b.round),
                           lambda: b.record["materials"].get("local_checks", {}).get("status"),
                           lambda: _ci_by_engine(b.record["process"].get("checks"), b.round))


@cond_reads("cur.p4.record", "record.materials", "record.process.checks", "round")
def would_converge(v):
    """関門の他が全部そろった周か（条件の部品）——撃つのは最終のコードに対してだけ"""
    ok = _converge_ready(v("cur.p4.record", None), lambda: v("record.materials").get("local_checks", {}).get("status"),
                         lambda: _ci_by_engine(v("record.process.checks", None), v("round")))
    return ok, "検証器が阻害なしで、この周の CI を engine が走らせて緑" if ok else "検証器の阻害なしか、この周の CI の緑（engine が走らせた物）が欠ける"


@cond_reads(*gates_merge.reads, *would_converge.reads)
def final_gate_due(v):
    """最後の関門を撃つか（p4.final_gates の条件）: 合流でまとめる run でなく、関門の他が全部そろった周"""
    merged, why = gates_merge(v)
    return (False, why) if merged else would_converge(v)


def _final_gate_problems(b):
    """最後の関門が通らない理由（空なら通る）。関門は、この周に固めた最終の版を撃った結果が在り、見逃しが全部
    振る舞いの変わらない変異（equivalent）で、撃った後に作業ツリーが変わっていないこと（テスト一式の緑は、関門を撃つ条件の
    _converge_ready が同じ版の p4.ci——engine が走らせた物——で見る）。
    **途中の版の線の結果は数えない**——撃った版が今のコードでなければ古い"""
    cut = _gates_cut(b)
    out = b.output_of_round("p4.final_gates", b.round)
    if not cut or out is None:
        return ["最後の関門（p4.final_gates）がこの周の最終の版を撃っていない"]
    probs = [f"{r['key']} が {r['handled']}（{r['how'][:80]}）" for r in out["handled"] if r["handled"] != "equivalent"]
    tree = git("rev-parse", f"{cut['rev']}^{{tree}}")
    if not out.get("arms") and (tree or "").strip() != b.loop_state.get("final_gate_empty_ok"):
        # 撃てた腕が 0 本の回を『見逃し 0 本』として通さない（変異の実行器が 0 本を合格と言わない——empty で exit 1——のと同じ向き）。
        # 0 本が正しい差分（文書だけ等）かは対象リポジトリの実行器ごとに違うので、rules は決めずに人に諮る（converge。PIT の
        # failWhenNoMutations も、0 本を通すかは人が設定で決める）。同じ木に人が continue したら通す
        probs.append(FINAL_GATE_EMPTY)
    try:
        now_tree = _worktree_tree()
    except Reject as e:
        now_tree, probs = None, probs + [str(e)]
    if tree is None or now_tree is None or tree.strip() != now_tree:
        probs.append(f"関門が撃った版 {cut['rev'][:12]} の後に作業ツリーが変わった（または木の id が取れない）——撃った結果は古い")
    return probs


FINAL_GATE_EMPTY = "最後の関門が撃った腕が 0 本——0 本のまま収束してよいかを人に諮る"


# このループが節に書く鍵（graphcheck の検査 15 が engine の ENGINE_NODE_KEYS・DOC_NODE_KEYS と合わせて閉じた集合にする）。
# NODE_KEYS は rules か graphcheck が読む鍵、NODE_NOTE_KEYS は人が読む説明の鍵
NODE_KEYS = frozenset({"materials", "na_self_ok", "na_reason", "carry_reason", "result_schema"})
NODE_NOTE_KEYS = frozenset({"inputs", "enforced_by", "escalate_note", "must_run_in_round_1", "na_reason_note", "refire_when"})


ACCEPT_KEYS = ("round_accepts_exit",)  # このループが読む受理集合の鍵（graphcheck が engine の分と合わせて形を見る）

# ---------------------------------------------------------------- 節の条件（graph の cond が名前で指す）
# graph には関数の名前だけを書き、どう判断するかはここに置く。関数は読む欄を cond_reads で宣言し（graphcheck が
# 前の節の出力・LOOP_KEYS・記録を書く宣言と突き合わせる）、engine が宣言した欄だけの入れ物 v を渡す。返りは（真偽, 理由の文）
# ——理由は走らなかった節の盤面の na と、持ち越した素材の理由に載る。**or / and の評価の順と短絡は、以前の JSON の条件と同じ**
# （default の無い欄は、評価の順で届いたときにだけ解決できないと落ちる）。
# 入口（request_entry）で外れたかは、同じ関数を入口の印を外した文脈でもう一度評価して決める（_entry_skipped）
# ——条件の書き方に依らない（以前は JSON の木から入口の項を抜いていた）
def _first(v):
    return v("round") == 1


def _eq_true(x):
    """以前の JSON の条件の eq と同じ比較——1 も真として数え、真理値として真になるだけの値（空でない文字列など）は数えない"""
    return x == True  # noqa: E712


def _round_files(v, key):
    """loop の鍵 key の値がこの周の物なら、その files の件数（前の周の値・無い値は 0）"""
    return len((_in_round(v(key, None), v("round")) or {}).get("files") or [])


def _fix_says(v, field):
    return _eq_true(v(f"prev.p3.fix.{field}", False))


def _escalated(v):
    return bool(v("loop.escalated", None))


def _because(ok, when, facts):
    """理由の文: 条件の名乗り（when）と、評価に使った事実"""
    return ok, f"{when}——{'成り立つ' if ok else '成り立たない'}（{facts}）"


def _touched(field, fix_field, what):
    """差分が〜に触れるか: 差分の形の申告（p0.base の field）か、前の周の修正の申告（p3.fix の fix_field）"""
    @cond_reads(f"out.p0.base.{field}", f"prev.p3.fix.{fix_field}")
    def fn(v):
        ok = _eq_true(v(f"out.p0.base.{field}")) or _fix_says(v, fix_field)
        return ok, f"差分が{what}に触れる" if ok else f"差分も前の周の修正も{what}に触れない（p0.base.{field}・p3.fix.{fix_field}）"
    fn.__name__ = f"{field.removeprefix('touches_')}_touched"
    return fn


gates_touched = _touched("touches_gates", "gates_changed", "検証ゲート")
seams_touched = _touched("touches_external_seams", "seams_changed", "外部との継ぎ目")
user_path_touched = _touched("touches_user_path", "path_changed", "利用者から見える経路")
_security_declared = _touched("touches_security_surface", "security_surface_changed", "認証・データの取り扱い・外部との入出力")


@cond_reads(*dict.fromkeys((*_security_declared.reads, *seams_touched.reads, "record.process.fixes")))
def security_surface_touched(v):
    """認証・データの取り扱い・外部との入出力に触れるか。外部 I/O は既存の継ぎ目の申告（seams_touched）でも真にする——
    2 つの申告が食い違ったら当てる側に倒す。**前のどの周の修正の申告でも真**（record.process.fixes）: 局所レビューは
    BASE からの累積の差分を見るので、一度入った面は run の終わりまで差分に残る。申告の欄が無い盤面（欄を足す前に
    once の p0.base を終えた）は当てる側に倒し、倒したことを痕跡に残す"""
    if v("out.p0.base.touches_security_surface", None) is None:
        v.unevaluable("security_surface_touched", "p0.base に touches_security_surface の欄が無い盤面——当てる側に倒した")
        return True, "p0.base に touches_security_surface の欄が無い盤面なので、当てる側に倒した（申告されていない）"
    for part in (_security_declared, seams_touched):
        ok, why = part(v)
        if ok:
            return True, why
    past = [f.get("round") for f in v("record.process.fixes", []) or []
            if isinstance(f, dict) and (f.get("security_surface_changed") is True or f.get("seams_changed") is True)]
    if past:
        return True, f"前の周（{past}）の修正が認証・データの取り扱い・外部との入出力か継ぎ目に触れた（累積の差分に残る）"
    return False, ("差分も前のどの周の修正も認証・データの取り扱い・外部との入出力・継ぎ目に触れない"
                   "（p0.base.touches_security_surface・touches_external_seams・process.fixes）")
_TOUCH = ("round", *prev_fix_touched.reads)   # 深さの節が共通して読む欄


@cond_reads(*request_entry.reads)
def not_request_entry(v):
    """判定から入る run の周でない（1 周目の P1 より前に add で依頼を置いて始めた run は、修正が入るまで P1 の役を起こさない）"""
    entry, why = request_entry(v)
    return (not entry), (f"{why}のため、P1 の役を起こさない" if entry else why)


@cond_reads(*request_entry.reads, *_TOUCH, "prev.p3.fix.mechanism_changed")
def external_standards_due(v):
    """判定から入る run の周でなく、初回か、機構を足した／変えた周か、前の周の P3 が何かを直した周（依存の宣言ファイルを変えた周も後者に入る）"""
    entry, why = request_entry(v)
    if entry:
        return False, f"{why}のため、外部標準の照合を起こさない"
    ok = _first(v) or _fix_says(v, "mechanism_changed") or prev_fix_touched(v)[0]
    return _because(ok, "初回か、機構を足した／変えた周か、前の周の P3 が何かを直した周",
                    f"round={v('round')}・{prev_fix_touched(v)[1]}")


@cond_reads(*request_entry.reads, *_TOUCH)
def provenance_due(v):
    """判定から入る run の周でなく、初回か、前の周の P3 が何かを直した周（事実の主張を増減した周も後者に入る）"""
    entry, why = request_entry(v)
    if entry:
        return False, f"{why}のため、出典の確かめを起こさない"
    ok = _first(v) or prev_fix_touched(v)[0]
    return _because(ok, "初回か、前の周の P3 が何かを直した周", f"round={v('round')}・{prev_fix_touched(v)[1]}")


def _deep(v, touched, when, extra=None):
    """P1 の深さの節の、入口を見た後の残り: (touched and (初回[ or extra が人待ち])) or 前の周の P3 が触った。
    前の周の P3 が申告する『変えた』の旗は項に持たない——旗が真の周は P3 がファイルを触った周で、後ろの or が必ず真になる"""
    t, twhy = touched(v)
    ok = (t and (_first(v) or (extra is not None and v(extra, None) == "awaiting_human"))) or prev_fix_touched(v)[0]
    return _because(ok, when, f"round={v('round')}・{twhy}・{prev_fix_touched(v)[1]}")


def _deep_due(name, touched, when, noun, merge_off=False):
    """P1 の深さの節（手順の追跡・ゲートの検算・代役の忠実さ）の条件の工場: 判定から入る run の周でなければ _deep で決め、
    偽でも昇格した周（loop.escalated）なら起こす。入口の周は外すが、昇格した周は入口より勝つ。3 節の分岐の正本はここ 1 つ。
    merge_off の節（変異の実行器を撃つ節）は、合流でまとめる run（gates_merge）なら入口・昇格より先に外す——人の決定が昇格にも勝つ"""
    extra = gates_merge.reads if merge_off else ()
    @cond_reads(*dict.fromkeys((*extra, *request_entry.reads, *_TOUCH, *touched.reads, "loop.escalated")))
    def fn(v):
        if merge_off:
            merged, mwhy = gates_merge(v)
            if merged:
                return False, mwhy
        entry, why = request_entry(v)
        if not entry:
            ok, rwhy = _deep(v, touched, when)
            return (True, f"{rwhy}・昇格した周") if not ok and _escalated(v) else (ok, rwhy)
        if _escalated(v):
            return True, f"判定から入る run の周だが、昇格した周なので{noun}を起こす"
        return False, f"{why}のため、{noun}を起こさない"
    fn.__name__ = fn.__qualname__ = name
    fn.__doc__ = f"{when}。判定から入る run の周は外すが、昇格した周は入口より勝つ"
    return fn


procedure_trace_due = _deep_due("procedure_trace_due", touches_procedures,
                                "差分に手順書・スクリプト・CI 定義があって初回の周、または前の周の P3 が何かを直した周", "手順の追跡")
gate_efficacy_due = _deep_due("gate_efficacy_due", gates_touched,
                              "差分がゲートを新設・変更していて初回の周、または前の周の P3 が何かを直した周", "ゲートの検算",
                              merge_off=True)
test_double_fidelity_due = _deep_due("test_double_fidelity_due", seams_touched,
                                     "差分が外部との継ぎ目に触れていて初回の周、または前の周の P3 が何かを直した周", "代役の忠実さの確かめ")


@cond_reads(*request_entry.reads, *_TOUCH, *user_path_touched.reads, "loop.last_material.main_path_observation.status")
def main_path_observation_due(v):
    """判定から入る run の周でなく、差分が利用者から見える経路を変え、初回か前の周に人待ちだった周
    （動かす手段が見つかったか再挑戦）、または前の周の P3 が何かを直した周"""
    entry, why = request_entry(v)
    if entry:
        return False, f"{why}のため、主経路の観察を起こさない"
    return _deep(v, user_path_touched, "差分が利用者から見える経路を変え、初回か前の周に人待ちだった周、"
                 "または前の周の P3 が何かを直した周", extra="loop.last_material.main_path_observation.status")


@cond_reads("round", "prev.p3.fix.decision_records_changed", "loop.escalated", *prev_fix_touched.reads)
def prior_decisions_due(v):
    """初回か、前の周の P3 がリポジトリの外に issue などの決定記録を書き足した周、または前の周の P3 が何かを直した周（昇格した周も）。
    decision_records_changed は p3.fix の任意の欄で、ファイルを 1 つも触らずに外へ書いた周だけ、この旗が条件を変える
    （リポジトリの中の台帳を書き足した周は prev_fix_touched が拾う）"""
    ok = _first(v) or _fix_says(v, "decision_records_changed") or prev_fix_touched(v)[0] or _escalated(v)
    return _because(ok, "初回か、前の周の P3 がリポジトリの外に決定記録を書き足した周、または前の周の P3 が何かを直した周（昇格した周も）",
                    f"round={v('round')}・{prev_fix_touched(v)[1]}")


@cond_reads("out.p0.purpose.source", "round", *purpose_sources_changed.reads, *purpose_review_unvetted.reads)
def purpose_review_due(v):
    """目的テキストを writer が要約した（出典③）周。1 周目、または前の周の P3 が目的の出典ファイルを触った周・監査が柵より前の形の周に走り直す"""
    src = v("out.p0.purpose.source")
    if src != "③writer の要約":
        return False, f"目的テキストの出典が {src}——監査するのは writer が要約した目的（③）だけ"
    if _first(v):
        return True, "writer が要約した目的の 1 周目"
    for f in (purpose_sources_changed, purpose_review_unvetted):
        ok, why = f(v)
        if ok:
            return True, why
    return False, "writer が要約した目的だが、1 周目でなく、出典も監査の形も変わっていない"


@cond_reads("round", *entry_first_fix.reads)
def parallel_pr_due(v):
    """1 周目か、判定から入る run で最初に修正が入った次の周（1 周目の差分が空だった run で、修正の実ファイルと並行 PR の交差をもう 1 度だけ見る）"""
    if _first(v):
        return True, "1 周目"
    return entry_first_fix(v)


@cond_reads("round")
def after_first_round(v):
    r = v("round")
    return (isinstance(r, (int, float)) and r > 1), f"round={r}"


@cond_reads("loop.r1_refire")
def r1_refire(v):
    """R1 が再発火する周（初回は必ず）"""
    ok = _eq_true(v("loop.r1_refire", True))
    return ok, "R1 の再発火条件に当たる" if ok else "R1 の再発火条件に当たらない（前の周から台帳も差分も変わっていない）"


@cond_reads("loop.r2_refire", "loop.purpose_known")
def r2_design_due(v):
    """R2 の再発火条件に当たり、目的の出典が取れている周（初回は必ず）"""
    if not _eq_true(v("loop.r2_refire", True)):
        return False, "R2 の再発火条件に当たらない"
    ok = _eq_true(v("loop.purpose_known", True))
    return ok, "R2 が再発火し、目的の出典が取れている" if ok else "目的の出典が取れていない（目的不明か、監査が狭めていると判定した）"


@cond_reads("loop.r2_refire", "out.r2.design.question_stands", "loop.purpose_known")
def r2_compare_due(v):
    if not _eq_true(v("loop.r2_refire", True)):
        return False, "R2 の再発火条件に当たらない"
    if not _eq_true(v("out.r2.design.question_stands", False)):
        return False, "R2 のゼロベース再導出が、問いは立っていないと言った"
    ok = _eq_true(v("loop.purpose_known", True))
    return ok, "R2 が再発火し、問いが立ち、目的の出典が取れている" if ok else "目的の出典が取れていない"


@cond_reads("loop.open_units", *prev_fix_touched.reads)
def overview_due(v):
    """阻害要因（[block]＋do-now）が 0 の周、または前の周の P3 が実際にファイルを触った周（R3・R4）"""
    n = v("loop.open_units", 0)
    if n == 0:
        return True, "阻害要因（[block]＋do-now）が 0 件"
    ok, why = prev_fix_touched(v)
    return ok, f"阻害要因が {n} 件・{why}"


@cond_reads("record.reviews.R2.status")
def r2_premise_invalid(v):
    st = v("record.reviews.R2.status", None)
    return st == "premise-invalid", f"R2 の判定は {st}"


# rules が盤面の loop（b.loop_state）に持つ鍵の宣言——loop の鍵の正本。条件の関数が loop.<鍵> を読むとき、graphcheck が
# ここと突き合わせる（綴り違いを回す前に落とす）。graph の節の outputs に書く loop.<鍵> もここに在ること（graphcheck）。
# 台本（simulate_review）が両向きを確かめる: 回した盤面の鍵が全部ここに在り、ここの鍵が全部 rules のどこかで書かれている
# ——宣言だけ残った古い鍵を default 付きで読む形を残さない。修正差分の往復の鍵は DELTA_PASSES から引く
LOOP_KEYS = frozenset({
    "block_counts", "changed_files", "changed_files_file", "closed_keys", "cold_check", "coverage_after", "defer_ledger",
    "diff_file", "diff_lines", "diff_lines_by_round", "diff_stat", "drift_notes", "engine_zero", "escalated", "facts_to_add",
    "final_gate_empty_ok", "flow", "gates", "gates_cut", "head_revs", "in_round_answers", "lane_merge", "lanes", "lanes_bad_delivered", "last_material", "last_review", "last_seen",
    "ledger_changed", "lines_at_r1", "lines_ratio", "mutation_decl", "open_units", "outcome", "prev_blocks", "prev_declared_faces",
    "prev_fix_files", "prev_one_shot", "prev_questions", "prev_rejudge", "prev_scalars", "prev_units", "purpose_known",
    "purpose_review_stale", "purpose_unusable", "r1_refire", "r2_refire", "r2_refire_forced", "rejudge_requested",
    "rejudge_rounds", "request_fixed_at", "request_wheres", "retaken_for_reviews", "reviewed_revision", "spec_changed",
    "spec_pending", "stop_reason", "tree_before", "validator_outputs", "wrote_refs_reads",
}) | {k for p in DELTA_PASSES.values() for k in (p.state_key, p.owed_key)}
# 記録の欄のうち rules が writes の外で書く物（add が書く入口の印・依頼の一覧・止める口 on_stop が書く止めた所と理由）——条件が record.<欄> を読むとき、完全一致で照らす
RECORD_KEYS = ("process.request_entry", "process.request_findings", "process.request_history", "process.checks",
               "process.scalars_unmeasured", "process.halted")
ENTRY_OFF = {"record.process.request_entry": None}   # 入口の印を外す重ね書き（_entry_skipped）——印が無い文脈は _entry_marked が偽


CONDS = {
    ENTRY_BUILTIN: request_entry, "not_request_entry": not_request_entry,
    "purpose_review_due": purpose_review_due, "prior_decisions_due": prior_decisions_due,
    "external_standards_due": external_standards_due, "procedure_trace_due": procedure_trace_due,
    "gate_efficacy_due": gate_efficacy_due, "test_double_fidelity_due": test_double_fidelity_due,
    "main_path_observation_due": main_path_observation_due, "provenance_due": provenance_due,
    "parallel_pr_due": parallel_pr_due, "after_first_round": after_first_round, "units_open": units_open,
    "delta_review_due": delta_review_due, "fix_delta_nonempty": fix_delta_nonempty, "delta_faces_open": delta_faces_open,
    "delta_fixed": delta_fixed, "delta_review2_due": delta_review2_due, "delta2_faces_open": delta2_faces_open,
    "r1_refire": r1_refire, "r2_design_due": r2_design_due, "r2_compare_due": r2_compare_due,
    "overview_due": overview_due, "r2_premise_invalid": r2_premise_invalid,
    "rejudge_open": rejudge_open, "rejudge_exhausted": rejudge_exhausted,
    "gates_cut_nonempty": gates_cut_nonempty, "would_converge": would_converge,
    "gates_merge": gates_merge, "lane_due": lane_due, "final_gate_due": final_gate_due,
    # 素材の applies_cond（走った節が『条件に当たらない』を名乗れるか）が指す部品
    "touches_procedures": touches_procedures, "gates_touched": gates_touched, "seams_touched": seams_touched,
    "user_path_touched": user_path_touched,
    # 局所レビューの条件付きレンズ（skills[].applies_cond）が指す部品
    "security_surface_touched": security_surface_touched,
}


# ---------------------------------------------------------------- 記録の形に固有の書き込み
def material_from_findings(b, nid, src, w):
    """役の返答（findings と seen）を素材 1 つに写す。

    以前は割った塊ごとの返答を畳む形だった（merge_material_chunks）。扇を落としたので畳む相手が 1 つに
    なり、「何片に割ったか」を素材に書く欄（split）も意味を失った。
    """
    findings = src.get("findings", [])
    m = {"status": "found" if findings else "clean", "checked": src.get("seen", "")}
    if findings:
        m["count"] = len(findings)
        m["detail"] = " / ".join(f"{f.get('where', '')}: {f.get('text', '')}" for f in findings)
    b.record["materials"][w["to"]] = m


def premise_question(b, nid, src, w):
    """R2 の premise-invalid を、立った周に judge が検算した結果を台帳に載せる。"""
    q = {"key": src["key"], "kind": "premise", "origin": "R2", "status": src["verdict"], "reason": src["reason"]}
    if src["verdict"] == "resolved":
        # 検証器は「R2 が premise-invalid の周」に未決（held / escalate）の premise の行を要求する——resolved で
        # 書くと立った周の記録が通らない（実測: 台本 premise_resolved が p4.record で exit 2）。判定を捨てるのではなく、
        # 行は held のまま実測を理由に書き、facts_to_add を制約に足して次の周で R2 を回し直す。resolved に確定するのは
        # 次の周の judge（p2.history の再審）——回し直した R2 の結果を見てから。
        q["status"] = "held"
        # resolution は schema の任意欄——添字で読むと、judge が省いた周に素の KeyError が exit 2（盤面が読めない側）に化ける
        res = src.get("resolution") or "（resolution が無い返答）"
        q["reason"] = f"{src['reason']}——検算で仮定は偽: {res}。実測を制約に足し次の周で R2 を回し直す（resolved の確定はその周の judge）"
        b.loop_state.setdefault("facts_to_add", []).extend(src.get("facts_to_add", []))
    # 消すのは同じ key の行と、この周に書いた R2 の前提の行だけ。前の周から台帳に残っている行（判定者が再審して引き継いだ物）を消すと、
    # この節は前の周の台帳を読まない別の目なので key が揃う保証が無く、検証器の『前の周の問いが今の周の台帳に無い』
    # （dropped_questions）に周の記録の段で初めて当たる——判定の受け付けで同じ規則を当てても、後の書き手が消せば届かない
    prev = b.loop_state.get("prev_questions") or []
    kept = {x.get("key") for x in prev if x.get("status") in validator_module(b).TRACKED} if prev else set()
    b.record["questions"] = [x for x in b.record["questions"]
                             if not (x.get("kind") == "premise" and x.get("origin") == "R2"
                                     and (x.get("key") not in kept or x.get("key") == q["key"]))]
    b.record["questions"].append(q)


WRITE_OPS = {"material_from_findings": material_from_findings, "premise_question": premise_question}# op ごとに、to を素材の名前として読むか（writes_material）を名乗る。graphcheck は WRITE_OPS の全 op にこの名乗りを求め、
# 真の op の書き先を節の materials の宣言と照合する——名前の表を別に持つと、op を足した周に表への追記を忘れても黙って通る
material_from_findings.writes_material = True
premise_question.writes_material = False


# ---------------------------------------------------------------- 機械の節
def _files_changed_since(b, prev_round):
    """前の周の頭に固めた版と、今の作業ツリーの木の差＝その間に変わったファイル（未追跡の新規ファイルも含む）。
    None = 測れない（前の周の頭の版が無い・git が取れない）——申告に落とす側は呼ぶ側で決める。
    写しの節を突き合わせる形だった頃は、写し（版の世界）と今の diff（作業ツリーの世界）が割れると未追跡のファイルが毎周『変わった』と出た"""
    prev = (b.loop_state.get("head_revs") or {}).get(str(prev_round))
    if not prev:
        return None
    try:
        now = _worktree_tree()
    except Reject:
        return None
    names = git("diff", "--name-only", "-z", prev, now)
    return None if names is None else sorted(x for x in names.split("\0") if x)


def numstat_totals(text):
    """`git diff --numstat` の出力から（ファイル名の並び・追加行・削除行）を取る。

    **バイナリの行は `-\t-\tfile` で来る**ので、数として足す前に数字かを見る（`int('-')` で落ちる）。
    欄が 3 つ揃わない行（壊れた出力・空行）も数えない。

    切り出した理由: 同じ式を検査が写して持っていて、**実装を変えても検査が落ちなかった**
    （実測 2026-09-13: `and` を `or` に変える退行を注入しても全件緑——検査が自分のコピーを測っていた）。
    """
    if "\0" in text:
        # **`-z` で引いた出力。** 既定の出力は非 ASCII のパスを C クオート（"\346\227\245…"）で、改名を
        # `old => new` で出す——どちらもファイルとして開けない綴りで、この一覧は今や /code-review に渡す
        # 対象そのものなので、レンズは開けないパスを渡されて「見たが所見なし」と同じ形の返答をする
        # （実測 2026-09-16: git 2.50.1 既定で `"\346\227\245…"` と `a.txt => b.txt` の両方を再現）。
        # `-z` はクオートせず、改名を NUL で 2 本の名前に割る。**改名は新しい側を採る**（レビュー対象は今の姿）。
        rows, i = [], 0
        parts = text.split("\0")
        while i < len(parts):
            head = parts[i]
            if not head.strip():
                i += 1
                continue
            cols = head.split("\t")
            if len(cols) == 3 and cols[2] == "":      # 改名: ins \t dels \t "" \0 old \0 new
                if i + 2 >= len(parts):
                    break
                rows.append([cols[0], cols[1], parts[i + 2]])
                i += 3
            elif len(cols) == 3:
                rows.append(cols)
                i += 1
            else:
                rows.append(cols)
                i += 1
    else:
        rows = [ln.split("\t") for ln in text.splitlines() if ln.strip()]
    full = [r for r in rows if len(r) == 3]
    names = "\n".join(r[2] for r in full)
    ins = sum(int(r[0]) for r in full if r[0].isdigit())
    dels = sum(int(r[1]) for r in full if r[1].isdigit())
    return names, ins, dels, len(rows)


def _take_diff(b, suffix=""):
    """BASE との差分を取り、写しに落とし、loop_state の 5 鍵を更新する。**取り方はこの 1 本だけ。**

    P1 の頭（worktree_snapshot）と P3 の後（_retake_for_reviews）で同じ物を取る。以前は後者が
    前者の後半を書き直した写しで、**原本が実測付きで持つ空差分の柵と、どの git が取れなかったかを
    名指しする problems が写しの側に無かった**（実測 2026-09-16: 同じ BASE で原本が ok:false を返す
    条件下で写しは True を返し、0 バイトの .patch を書いた。r2.compare は本文ごと貼る遮断系なので、
    役は『差分が無い』と『渡し損ねた』を区別できない）。同じ 3 行を 2 か所に置くと片方だけ直る、と
    書いた注記の隣で、まさにそれが起きていた。

    `suffix` は写しの名前だけを変える——**周の頭の版（head_revs[N]）を記録するのは接尾辞の無い回だけ**で、
    _files_changed_since が次の周の持ち越しの無効化に使う（前の周の頭の版と今の木の差）。-after-fix の回がそれを
    書き換えると、修正した所を見た素材が carried_over のまま前の周の主張を運ぶ。
    """
    ls = b.loop_state
    base = b.record.get("base")
    if not base:
        return {"ok": False, "problems": ["BASE が無い（p0.base が先）"]}
    # git の失敗（None）は全部「測れない」で止める。`or ""` で空文字に潰すと『取れない』と『変化なし』が
    # 同じ値になり、保護も件数も黙って通る（util.git の契約は「None は分からない。合格に倒すな」）。
    # numstat 1 本で変更ファイルと行数の両方を取る（name-only と shortstat の 2 プロセスは冗長）。
    # 対象差分は**生バイトで 1 度だけ**引く（写しと空の検査が同じ値を使う。前後の突合は版の木の id で見る）。
    # **版を先に固め、差分は BASE → 版で取る。** 作業ツリーとの diff は未追跡の新規ファイルを落とすので、採点する版
    # （本物の index の写しに add -A）と写しの世界が割れ、新設のプロンプト 6 本が P1 の役に 1 本も渡らなかった（実測 2026-09-24 の 4 周目）。
    # 写し・作業ツリーの前後の突合・周をまたぐ変更の検出は、全部この 1 つの版から引く
    try:
        snap = _freeze_revision(b)
    except Reject as e:
        return {"ok": False, "problems": [str(e)]}
    raw_diff = git_bytes("diff", base, snap)
    numstat = git("diff", "--numstat", "-z", base, snap)  # -z: クオートせず、改名を 2 本の名前に割る（開けない綴りを一覧に入れない）
    missing = sorted(k for k, v in (("diff", raw_diff), ("numstat", numstat)) if v is None)
    if missing:
        return {"ok": False, "problems": [f"git が取れない（{', '.join(missing)}）——BASE={base} の対象差分が測れない場所からは回せない"]}
    # 対象差分が空なら止める。空を通すと、素材が毎周 not_run（理由は事実と逆）で埋まったまま上限まで回る
    # （実測: BASE=HEAD で 5 周・diff 0 バイト・stop_reason=max_rounds、原因は記録のどこにも出ない）。
    # 例外は判定から入る run の周だけ——人の依頼は既存のコードに向くので空が普通で、素材は入口の理由で埋まる
    # （実測 2026-09-25: 入口の無い特別周が BASE=HEAD でここに止まった）。依頼を全部却下した run もここを通って報告まで届く
    if not raw_diff.strip() and not b.cond(ENTRY_BUILTIN)[0]:
        if suffix:
            why = "P3 の修正が差分を全部戻した可能性がある（零処方『欠陥を持ち込んだ変更ごと取り下げる』）——BASE ではなく修正の内容を見よ"
        else:
            why = "BASE を確かめよ（p0.base の base_sha）"
            if entry_opens(b):
                why += ("。人の修正依頼から始める run なら、BASE はこのままで loop.py add --file <依頼.json> --reason <出どころ> --dir <DIR> で"
                        "依頼を置けば判定から入る（手順書の「判定から入る（人の修正依頼）」）")
        return {"ok": False, "problems": [f"対象差分が空（git diff {base} が 0 バイト）——{why}"]}
    names, ins, dels, nfiles = numstat_totals(numstat)
    f = b.dir / f"diff-r{b.round}{suffix}.patch"
    # **写しは生バイトで書く。** 役が読む写しを git の出力と 1 バイトも違えない（復号した str を UTF-8 で書き戻すと、
    # 復号できないバイトが U+FFFD に化ける）。周をまたぐ変更の検出はもう写しを読み直さず、固めた版どうしの木の差で見る
    f.write_bytes(raw_diff)
    changed = [x for x in names.splitlines() if x.strip()]
    cf = b.dir / f"changed-r{b.round}{suffix}.txt"
    cf.write_text("\n".join(changed) + "\n", encoding="utf-8")
    ls["diff_file"] = str(f)
    ls["changed_files"] = changed
    ls["changed_files_file"] = str(cf)  # 回す側の節には一覧でなくこのパスを渡す（一覧を 4 本のプロンプトに複製しない）
    ls["request_wheres"] = request_wheres(b)
    ls["diff_stat"] = f"{nfiles} files changed, {ins} insertions(+), {dels} deletions(-)"
    ls["diff_lines"] = ins + dels  # numstat から数えた整数をそのまま使う（stat 文字列に組んでから正規表現で読み直していた）
    # **版も一緒に取り直す**（上で固めた）。以前は接尾辞が空のとき（周の頭）だけ固定していたので、P3 の後に
    # 差分だけ撮り直すと、R1〜R4 が『修正後の差分』と『修正前の版』を同時に渡された（実測 r8）。
    # 周の頭の版は周ごとに残す——reviewed_revision は -after-fix で上書きされ、次の周の変更の検出に使えない
    if not suffix:
        ls.setdefault("head_revs", {})[str(b.round)] = snap
    return {"ok": True, "raw": raw_diff, "diff_file": str(f), "changed_files": changed, "stat": ls["diff_stat"], "rev": snap}


def _freeze_revision(b):
    """**その周に採点する版を、リビジョン 1 つに固定する。**（固め方は _snapshot 1 本。修正後の版を固める fix_delta も同じ 1 本）

    採点役が生きた作業ツリーを読んでいたとき、同じ周のうちに writer が直すと判定の行番号と母数が
    途中で腐り、次の周は『赤だったのか記録が古かったのか』を見分けられなかった（実測 r6）。
    世の中のコードレビューが commit を見て作業ツリーを見ないのと同じ理由である。

    **渡すのは写しでなくリビジョン。** 一度は git archive で展開した写しを渡したが、写しは .git を
    持たないので**役は渡された場所で git を打てず**、engine の数え直しだけが生きた木を見るという
    割れ方をした（実測 r8: 採点役 7 枚が git の実行を前提に書かれていた）。リビジョンなら役も engine も
    `git -C <repo> … <rev>` で同じ版を読める——**見る物と測る物を割らない**というのがこの節の不変条件で、
    写しの寿命（掃除）も無くなる。

    固定できない場合は止める。倒れ方が fail-closed なのは正しいが、そのときに出る文が
    『プロンプトの穴が埋まらない』では回す側は原因にたどり着けないので、ここで理由を名乗る。
    """
    # **git の「分からない」を「綺麗」と同じ値に潰さない。** どの段でも None は失敗であって
    # 「変更が無い」ではない——潰すと、その周の作業を 1 行も含まない版に黙って倒れる。
    # 採点役 7 枚も根拠の数え直しもその版を読むので、**レビュー対象を 1 行も見ないまま通る**。
    # util.git の契約（失敗なら None。分からないとして扱い、合格に倒さない）を、ここでも守る。
    # **一時 index の上で組み立てる。** 以前は git stash create を使っていたが、この経路は
    # **このループの主経路で必ず落ちる**——p0.base が未追跡の新規ファイルに `git add -N` を指示しており、
    # intent-to-add の index では stash create も write-tree も非 0 で返る（実測 r10: 新規 2 ファイルを
    # 載せた周で P1 の頭が止まった）。本物の index を一時 index に写してから `add -A` すれば、
    # intent-to-add は普通の追加として materialize され、**未追跡の新規ファイルも版に載る**
    # ——stash create は未追跡を既定で落とすので、参照だけが差分に載って本体が載らない形になっていた（同 r10）。
    # 分岐を残さず 1 本にしてあるのは、「どちらの道を通ったか」で版の中身が変わる形を作らないため。
    snap = _snapshot(f"graphloops review r{b.round}")
    b.loop_state["reviewed_revision"] = snap
    b.state["inputs"]["review_rev"] = snap
    return snap


def _worktree_tree():
    """作業ツリーの今の姿の木の id（未追跡の新規ファイルも含め、追跡していない .gitignore の対象は除く）。固められなければ Reject。
    中身が同じなら id も同じなので、前後の突合はこの id を比べるだけで済む。

    **本物の index を一時 index に写してから** `add -A` する。空の一時 index から始めていたとき、追跡中だが .gitignore に
    当たるファイルは `add -A` に拾われず、版から落ちて『削除』に見えた（実測 2026-09-25: 別のリポジトリの run で、判定役が
    これを根拠に誤った [block] を出した）。写しは stat の情報も持つので、`add -A` は変わったファイルだけをハッシュする。
    写しの上で `--really-refresh` を打つのは assume-unchanged の印を外すため——印を持ったままだと、git はそのファイルを
    見ずに古い中身で版を作る。本物の index は読むだけで書かない"""
    tmp = tempfile.mkdtemp(prefix="graphloops-index-")
    idx = pathlib.Path(tmp) / "index"
    env = {"GIT_INDEX_FILE": str(idx)}
    why = []   # git が言った失敗の理由（util.git の why）。止める文に添える
    try:
        real = git("rev-parse", "--path-format=absolute", "--git-path", "index", why=why)
        if real is None or not real.strip():
            raise _unfrozen("本物の index の場所を git rev-parse --git-path で引けない", why,
                            "git 2.31 以上か、リポジトリの中で呼んでいるかを確かめよ")
        try:
            shutil.copy2(real.strip(), idx)   # 時刻ごと写す——index の時刻が新しくなると、同じ秒に書き換えたファイル（racy git）を綺麗と見誤る
        except FileNotFoundError:
            pass   # index がまだ無い（init の直後で 1 度も add していない）＝追跡中のファイルが無いので、空から始めて落ちる物が無い
        except OSError as e:
            raise Reject(f"この周に採点する版を固定できない（本物の index を写せない: {e}）")
        if git("update-index", "-q", "--really-refresh", env=env, why=why) is None or git("add", "-A", env=env, why=why) is None:
            raise _unfrozen("一時 index への git update-index / add -A が失敗した", why)
        tree = git("write-tree", env=env, why=why)
        if tree is None or not tree.strip():
            raise _unfrozen("git write-tree が木を返さない", why)
        return tree.strip()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _unfrozen(what, why, hint=None):
    """版を固定できない回の Reject。**git が言った理由を必ず添える**——添えなかったとき、止まった利用者は原因
    （壊れた object・書けない置き場・git の版）を文から読めず、git を手で打ち直すしかなかった"""
    said = " / ".join(w for w in why if w) or "git は理由を返さなかった"
    return Reject(f"この周に採点する版を固定できない（{what}。git の言い分: {said}）" + (f"——{hint}" if hint else ""))


# 周に固める版（push しない engine の内部の commit）の作者の**代わりの名前**。まず利用者の git が決める作者で固め
# （設定・環境変数・推し量りの順は git 自身が持つ——写すと EMAIL のような欄が落ちる）、それが止まったときだけこれで
# 固め直す。名前とメールの無い環境（CI・新しい機械・コンテナ）で周の頭が止まらないため。与えられていない時だけ
# 代わりを使う形は git の ident.c の prepare_fallback_ident と同じ。環境変数は git の設定より優先される（git(1)）
SNAPSHOT_FALLBACK_IDENT = {"GIT_AUTHOR_NAME": "graphloops", "GIT_AUTHOR_EMAIL": "graphloops@localhost",
                           "GIT_COMMITTER_NAME": "graphloops", "GIT_COMMITTER_EMAIL": "graphloops@localhost"}


def _snapshot(msg):
    """作業ツリーの今の姿（未追跡の新規ファイルも含め、追跡していない .gitignore の対象は除く）を commit 1 つに固めて返す。固められなければ Reject"""
    tree = _worktree_tree()
    # HEAD が無い（commit が 1 つも無い）リポジトリでは親を付けない。**None と空を混ぜない**
    # ——失敗を「親が無い」に潰すと、履歴の在るリポジトリで根なしの版を採点することになる
    head = git("rev-parse", "HEAD")
    parent = ["-p", head.strip()] if head and head.strip() else []
    why = []
    for ident in (None, SNAPSHOT_FALLBACK_IDENT):
        snap = git("commit-tree", tree, *parent, "-m", msg, env=ident, why=why)
        if snap is not None:
            break
    if snap is None or not snap.strip():
        raise _unfrozen("git commit-tree が版を返さない", why)
    return snap.strip()


def fix_delta(b, nid):
    """P3 の直後: **この周の修正だけ**の差分を取る（周の頭に固めた版 → 修正後の姿）。

    修正の良し悪しを見る段は、今まで全部が累積差分（BASE からの差）か次の周の全体レビューだった。累積差分では
    この周の修正がどれかを役が切り分けられず、修正が作った写し・入口・ずれは次の周に新しい指摘として挙がり、
    その修正がまた次の穴を作った（実測 2026-09-24: 3 周目の指摘のうち 8 件が 2 周目の修正の産物）。
    修正後の姿は採点する版と同じ手続き（_snapshot）で固める——未追跡の新規ファイルも載り、比べる 2 つの版の世界が揃う。
    """
    # 1 回目は周の頭に固めた版から、2 回目（手直しの差分）は 1 回目に固めた修正後の姿から
    n = DELTA_PASS_OF[nid]
    key = DELTA_PASSES[n].state_key
    rev = b.loop_state.get("reviewed_revision") if n == 1 else (_delta_of(b, n - 1) or {}).get("rev")
    if not rev:
        return {"ok": False, "problems": [f"{nid}: 差分の起点の版が無い（1 回目は P1 の頭で、2 回目は p3.fix_delta で固める）"]}
    try:
        snap = _snapshot(f"graphloops fix r{b.round}")
    except Reject as e:
        return {"ok": False, "problems": [str(e)]}
    raw = git_bytes("diff", rev, snap)
    names = git("diff", "--name-only", "-z", rev, snap)
    if raw is None or names is None:
        return {"ok": False, "problems": [f"git diff {rev[:12]} {snap[:12]} が取れない——修正の差分を測れない"]}
    f = b.dir / f"{key.replace('_', '-')}-r{b.round}.patch"
    f.write_bytes(raw)
    files = [x for x in names.split("\0") if x]
    b.loop_state[key] = {"round": b.round, "file": str(f), "files": files, "rev": snap}
    return {"ok": True, "fix_delta_file": str(f), "changed_files": files}


def worktree_snapshot(b, nid):
    """P1 の前: この周に採点する版を固め、対象差分（BASE → 版）と、前後の突合の基準（porcelain・stash・版の木の id）を機械が取る。回す側に貼らせない。"""
    ls = b.loop_state
    stash = git("stash", "list")
    if stash is None:
        return {"ok": False, "problems": ["git stash list が取れない——作業ツリーの保護（前後の突合）が測れない場所からは回せない"]}
    # **写しを書く前に柵を全部通す。** 統合前はこの順だった——後ろに回すと、git status が取れずに
    # ok:False を返す回でも .patch と changed-*.txt が既に在り、loop_state の 5 鍵も更新済みになる
    # （今は worktree_compare が porcelain の None で fail-closed に倒れるので黙る穴には届いていないが、
    # 統合で失われた順序である。実測 2026-09-16・静的）
    snap = b.porcelain()
    if snap is None:
        return {"ok": False, "problems": ["git status が取れない——作業ツリーの保護（前後の突合）ができない場所からは回せない"]}
    d = _take_diff(b)
    if not d["ok"]:
        return d
    # 固めた版の木の id も突合に入れる。porcelain は状態コードとパスだけなので、**既に ' M' のファイルの
    # 中身を差し替えても検知しない**——レビュー対象は定義上ぜんぶ変更済みなので、これが無いと保護は
    # 対象そのものに効かない（agents/investigator.md はこの突合を「担保」と名乗っている）。木の id は中身のハッシュなので、バイト単位の書き換えも拾う
    tree = git("rev-parse", f"{d['rev']}^{{tree}}")
    if tree is None:
        return {"ok": False, "problems": ["固めた版の木の id が取れない——作業ツリーの保護（前後の突合）ができない場所からは回せない"]}
    ls["tree_before"] = {"porcelain": snap, "stash": stash.strip(), "tree": tree.strip()}
    # 前の周の修正と手直しが足した分岐（前の周の頭 → 周の終わり）を自動の腕で撃つのは、前の周の並行の線（p3.delta_gates）だけ。
    # 以前はここで『--auto <前の周の頭>』を組み、次の周の p1.gate_efficacy が同じ範囲をもう一度撃っていた（撃ち手が 2 つ）
    return {"ok": True, "diff_file": d["diff_file"], "changed_files": d["changed_files"], "stat": d["stat"]}


def worktree_compare(b, nid):
    """P1 の後: 作業ツリーが変わっていないこと（どの道具が汚したかを当てるのでなく機械で突き合わせる）。

    **射程は git が映す範囲だけ**——porcelain・stash・版の木の id はいずれも .git/ 配下・追跡していない .gitignore 対象・
    リポジトリの外（$HOME 等）を映さない。役が .git/hooks/ や ~/.claude/settings.json を書いても緑で通る。
    これは**事故の検知**であって権限の強制ではない（この run 自身の生成物 .git/graphloops/… も射程の外）。
    走らせなかった素材の欄も、ここで機械が埋める（条件外＝not_applicable／持ち越し＝carried_over／
    走らせるべきだったのに無い＝not_run）。judge に渡る素材は必ず 15 欄そろう。"""
    ls = b.loop_state
    before = ls.get("tree_before") or {}
    snap = b.porcelain()
    # 中身は採点する版と同じ手続きで固めた木の id で比べる（作業ツリーとの diff は未追跡を落とし、版の世界と割れる）
    try:
        tree = _worktree_tree()
    except Reject:
        tree = None
    got = {"stash": git("stash", "list"), "tree": tree}
    if snap is None or any(v is None for v in got.values()) or before.get("porcelain") is None:
        return {"ok": False, "problems": ["git status / 作業ツリーの木が取れない——作業ツリーの前後を突き合わせられない（一致とは言えない）"]}
    now = {"porcelain": snap, "stash": got["stash"].strip(), "tree": got["tree"]}
    problems = []
    for k in ("porcelain", "stash", "tree"):
        if before.get(k) != now[k]:
            problems.append(f"{k}: {before.get(k)!r} → {now[k]!r}")
    if problems:
        # writer 自身の変更（engine をその場で直した等）は、done と同じく理由を添えて通せる——痕跡は
        # process.git_mismatches に accepted として残る。通す道が無いと、engine を直しながら回す run は
        # ここで永久に止まる（実測 2026-09-12: P1 の途中で done の読み取りを直したら next が 10 回同じ note を返した。
        # stash で退避しても stash の一覧が突合に入っているので通らない）。受け付けたら基準を今の姿に置き直す。
        accepted = getattr(b, "accept_tree_change", None)
        entry = {"where": "P1", "round": b.round, "diff": problems, "accepted": accepted}
        # **痕跡は取り直しより先に積む。** 取り直しが失敗した回だけ「作業ツリーが変わって受理した」事実が
        # 記録から消えていた（下の return が append より前に在った）。entry は参照で持つので、後から追記できる
        gm = b.state.setdefault("git_mismatches", [])
        if not gm or gm[-1] != entry:  # 同じ止まり方で next を叩き直すたびに増やさない
            gm.append(entry)
        if accepted:
            # **受理したら審査対象を取り直す。** tree_before だけ今の姿に置き直して diff-r<N>.patch と
            # changed-r<N>.txt を P1 前のままにすると、P2 に渡る写しと現物が割れる——**同じ周の素材 2 つが
            # 同じ行について逆の結論を出せる**（写しを読む役は受理前の姿を、現物を読む役は受理後の姿を見る）。
            # 腕は graphloops/tests/simulate_review.py:test_worktree_guard_fires が持つ。
            # 取り直しは snapshot をもう一度呼ぶ形で行う——同じ 3 行を 2 か所に置くと、片方だけ直る
            again = worktree_snapshot(b, nid)
            if not again["ok"]:
                entry["retake_failed"] = again.get("problems") or True
                return again
            entry["retaken"] = {"stat": ls.get("diff_stat"), "files": len(ls.get("changed_files") or [])}
            # **取り直した審査対象に、材料を揃える。** 写しだけ取り直すと、変更前の姿を見て書き終えた材料が古いまま
            # 判定役に渡る（GitHub の保護ブランチの『差分に効くコミットが積まれたら既存の承認を取り消す』と同じ形）
            stale, old = _rewind_materials(b, nid)
            entry["refired"] = stale
            entry["stale_materials"] = old
            if stale:
                return {"ok": False, "rewound": stale,
                        "problems": [f"作業ツリーの変更を受理して審査対象を取り直した——変更前の姿を見て書いた材料の節 {stale} を撃ち直す"]}
        if not accepted:
            return {"ok": False, "problems": ["P1 の前後で作業ツリーが変わっている（戻してから next。自分の変更なら next --accept-tree-change <理由>）: " + "; ".join(problems)]}
    fill_materials(b)
    return {"ok": True, "materials": sorted(b.record["materials"])}




def _rewind_materials(b, nid):
    """nid の依存のうち、この周に走り終えた役の節と条件外にした節を engine に待ちへ戻させる ——（戻した節, 外した素材の中身）。
    どの節を戻すかだけが rules の判断で、戻し方（状態・返答の置き場・出力の指し・記録の欄）は engine の Board.rewind が持つ。
    外した素材の中身は呼び元が痕跡（process.git_mismatches）に残す"""
    back = [d for d in b.nodes[nid].get("deps", []) if b.nodes[d].get("run_by") != "driver" and (d in b.rd["done"] or d in b.rd["na"])]
    old, ran = {}, {d for d in back if d in b.rd["done"]}
    for d, got in b.rewind(back, by=nid).items():
        for to, val in got.items():
            if to.startswith("materials."):
                old[to.split(".", 1)[1]] = val
        # 素材を書く独自の op（material_from_findings は to を素材名として読む）の素材は、op の意味を知る rules が外す。
        # 外すのはこの周に走った節の分だけ（条件外の節の素材は、この周にはまだ書かれていない）
        for mat in b.nodes[d].get("materials", []) if d in ran else []:
            if mat in b.record["materials"]:
                old[mat] = b.record["materials"].pop(mat)
    return back, old


def fill_materials(b):
    """走らせなかった素材の欄を機械が埋める。条件外＝not_applicable／前の判定を流用＝carried_over／
    前が awaiting_human・not_run（流用できない値）＝同じ値をもう一度（今も待っている記録）／それ以外＝not_run。"""
    V = validator_module(b)
    ls = b.loop_state
    last = ls.setdefault("last_seen", {})
    last_mat = ls.setdefault("last_material", {})
    mats = b.record["materials"]
    for name, st in mats.items():
        # 「最後に見たのはいつか」を数えるのは、自分で見たと主張している値だけ（検証器の表が正本）
        if st.get("status") in V.OBSERVED_STATUS:
            last[name] = b.round
        if st.get("status") != "carried_over":
            last_mat[name] = st
    declared = set()
    for nid, n in b.nodes.items():
        for mat in n.get("materials", []):
            declared.add(mat)
            if mat in mats:
                continue
            state = b.node_state(nid)
            if state == "pending":
                continue  # まだ走っていない節（P3 の fix_closure 等）
            if state == "na" and _entry_skipped(b, n):
                reqs, _ = _requests(b, "request_findings")
                mats[mat] = {"status": "not_applicable",
                             "reason": f"判定から入る run（出どころ: {b.record['process']['request_entry']['origin']}。この周の判定に届く人の依頼 "
                                       f"{sum(len(x['findings']) for x in reqs)} 件）のため、P1 の役を起こしていない"
                                       "——依頼の外を見る目はこの周に無い（判定役と修正前後の審査だけが見る）"}
                continue
            if state == "skipped":
                mats[mat] = {"status": "not_run", "reason": f"回す側が省いた: {b.rd['skipped'].get(nid, '')}"}
                continue
            if state == "stopped":   # 人が止めた（loop.py stop）——省いた（回す側の判断）とは別の事実として書く
                mats[mat] = {"status": "not_run", "reason": f"{b.rd['stopped'][nid]}——この周に節 {nid} は走っていない"}
                continue
            applies = n.get("applies_cond")
            ap_ok, ap_why = b.cond(applies) if applies is not None else (True, "")
            if not ap_ok:
                mats[mat] = {"status": "not_applicable", "reason": f"{n.get('na_reason', '条件に当たらない')}（{ap_why}）"}
            elif state == "na" and n.get("cond") == "gate_efficacy_due" and b.loop_state.get("gates") == GATES_MERGE:
                # 撃たなかった事実・理由・残る義務を見せる。not_run（阻害）にすると検証器が止め、gates_deferred に届かず上限まで回る。
                # 同じ run の線と最後の関門（条件外で閉じる）と同じ扱いで、義務は converge の gates_deferred と報告が運ぶ
                mats[mat] = {"status": "not_applicable",
                             "reason": f"{GATES_MERGE_WHY}——差分はゲートに触れているが、この run では撃たない。"
                                       "合流した版を gates=merge 無しの run で回し、そこの P1 のゲートの検算が撃つ"}
            elif mat in last_mat and not V.STATUS[last_mat[mat]["status"]].carryable:
                # **持ち越せるかは「前の周の値」が決める（検証器の表 STATUS.carryable が正本）**。以前は last_seen
                # ＝「最後に found/clean だった周」という代理を先に見ていたので、r1=clean・r2=awaiting_human・
                # r3=非実行 の並びで carried_over を書き、検証器が exit 2 で落とし、record_round が ok:False を
                # 返し続けて converge に到達せず——暴走ガードにも届かない run になった（実測 2026-09-13）
                prev = last_mat[mat]
                mats[mat] = {"status": prev["status"], "reason": prev.get("reason", "") + "（前の周と同じ。流用できない値なので今も同じ状態として書く）"}
            elif mat in last:
                # 持ち越しの理由は「確かめた対象」を書く。理由を事実と独立に既定文で書いていたとき、
                # 前の周の P3 が直した対象を見た素材が carried_over のまま前の周の主張を運び、
                # 閉じた欠陥が次の周に新規の [block] として生き返った（実測 2026-09-12）。
                # 再発火そのものは graph の cond（rules の条件の関数）が決める——埋める側でなく走らせる側で。
                why = (f"（確認: 再発火の条件 {b.rd['na'].get(nid, '')}）" if n.get("cond") and nid in b.rd["na"]
                       else "（確認: この節は再発火条件を持たない once の節）")
                mats[mat] = {"status": "carried_over", "from_round": last[mat],
                             "reason": n.get("carry_reason", "再発火の条件に当たらない周（前の判定を流用。実際に見たのは from_round）") + why}
            elif state == "done":
                # 走ったのに素材が無い＝返答は受理されたが記録に着地していない（writes の from / to の欠陥）。
                # 「走らせる条件に当たらず」と書くと理由が事実と逆になる（実測: writes を空にしても 5 周回って stopped）
                mats[mat] = {"status": "not_run", "reason": f"節 {nid} は走ったが素材 '{mat}' が記録に着地していない（graph の writes の欠陥——from / to を確かめよ）"}
            else:
                mats[mat] = {"status": "not_run", "reason": f"走らせる条件に当たらず、流用できる前の判定も無い（節 {nid}）"}
    if "fix_closure" not in mats:
        mats["fix_closure"] = {"status": "not_applicable", "reason": "P1 時点。修正は P3 でこれから行う"}
    for name in V.MATERIALS:
        if name not in mats and name not in declared:
            mats[name] = {"status": "not_run", "reason": "どの節も返していない（graph の欠陥）"}


def _retake_for_reviews(b):
    """P3 の後の姿を、R1〜R4 に渡すためだけに写し直す。**取り方は _take_diff＝P1 の頭と同じ 1 本。**

    **周の頭の版（head_revs[N]）は書き換えない**（_take_diff は接尾辞の在る回に head_revs を触らない）。あれは周をまたぐ
    比較の基準で（_files_changed_since が前の周の頭の版と今の木を比べて、前の周の P3 が触ったファイルを出す）、
    書き換えると次の周の持ち越しの無効化が効かなくなる——修正した所を見た素材が carried_over のまま前の周の主張を運ぶ。
    腕は台本が持つ（『前の周の P3 が触ったので走り直す』）。

    なので別の名前（-after-fix）に写し、R の節にはそちらを渡す。P1 の頭で凍結した姿しか渡さないと、
    R は**修正前の姿しか見られない**（実測 2026-09-16: 2 周とも R1 の judge が『渡された写しは
    古い』と自分で気づいて作業ツリーを直接読み、そのおかげで 1 周目の回帰を捕まえた。仕組みが
    そうさせたのではなく、気づかなかった 2 件は次の周の P1 が捕まえた＝同じ周で収まらなかった）。

    返りは _take_diff のまま（ok と problems）——**失敗の理由を握り潰さない**。以前はこの関数が
    独自に真偽値を返し、空差分の柵も problems も持っていなかったので、0 バイトの写しを ok として
    R へ渡せた（実測 2026-09-16）。
    """
    d = _take_diff(b, "-after-fix")
    if d["ok"]:
        b.loop_state["retaken_for_reviews"] = {"file": d["diff_file"]}  # stat は ls["diff_stat"] に在る（値を 2 組持たない）
    return d


def assemble(b, nid):
    """P3 の後: 開いたユニットの数・R1/R2 の再発火・行数の伸び・台帳の変化を機械が数える。

    **最初に審査対象を取り直す。** P3 は必ず作業ツリーを変える段なので、P1 の頭で凍結した
    diff-r<N>.patch のままだと、この後に走る R1〜R4 は**修正前の姿しか見られない**
    （実測 2026-09-16: 2 周とも R1 の judge が『渡された写しは古い』と自分で気づいて作業ツリーを
    直接読み、そのおかげで 1 周目の回帰を捕まえた。仕組みがそうさせたのではない。気づかなかった
    2 件は次の周の P1 が捕まえた＝同じ周で収まらなかった）。worktree_compare が変更を受理したときに
    取り直すのと**同じ 1 本（_take_diff）を呼ぶ**——同じ 3 行を 2 か所に置くと片方だけ直る
    （実測 2026-09-16: この注記が『同じ関数を呼ぶ』と書いていた時点で、写しの側は原本の空差分の柵を
    持たない別実装だった。注記が事実と逆を教えていた）。
    """
    taken = _retake_for_reviews(b)
    if not taken["ok"]:
        # **理由をそのまま前に出す。** 1 行に潰すと、BASE が無いのか git が死んだのか差分が空なのかが
        # 記録から読めない（R へ渡すのは本文ごと貼る遮断系なので、役は『差分が無い』と『渡し損ね』を区別できない）
        return {"ok": False, "problems": ["P3 の後の写しが取れない——R1〜R4 に渡す対象が古いままになる"] + taken["problems"]}
    V = validator_module(b)
    rec, ls = b.record, b.loop_state
    fix = b.output_of_round("p3.fix", b.round) or {}
    ls["open_units"] = sum(1 for u in rec["units"] if V.is_open(u))
    lines = ls.get("diff_lines", 0)
    at_r1 = ls.get("lines_at_r1")
    ratio = (lines / at_r1) if at_r1 else None
    ls["lines_ratio"] = ratio
    prev_q = _prev_round_record(b)
    ls["ledger_changed"] = (V.ledger_shape(rec) != V.ledger_shape(prev_q)) if prev_q else False
    ls["r2_refire"] = _r2_refire(b.round, fix, ratio, lines, ls)
    ls["r1_refire"] = ls["r2_refire"] or ls["ledger_changed"]
    # 目的が取れない（目的不明）のと、writer の要約を inspector が「狭めている」と判定したのは、R2 にとって同じ——
    # 独立の出典として使えない（以前は判定を誰も読まず、狭められた目的で R2 が回った。実測 2026-09-12）
    src = (b.latest_output("p0.purpose") or {}).get("source")
    # **裏取りを通っていない判定は使わない。** 監査は 1 周目にしか走らない（cond）ので、裏取りの柵が入る前に
    # 書かれた判定は**一度も数え直されないまま毎周の判定材料に載り続ける**（実測 r9: findings が素の文字列 5 件で、
    # うち 4 件は現物に 0 件の字列を根拠にしていた——r2 から 6 周同じ指摘が再燃した原因がここ）。
    # 根拠が今の形（text / cite / hits）で書かれた判定だけを使い、旧形は『判定なし』として扱う。
    pr = b.record.get("process", {}).get("purpose_review", {}) or {}
    vetted = purpose_findings_vetted(b)   # 式の正本は 1 か所（条件の purpose_review_unvetted と同じ _findings_vetted を呼ぶ）
    narrowed = pr.get("verdict") == "狭めている" and vetted
    if pr.get("verdict") == "狭めている" and not vetted:
        ls.setdefault("purpose_review_stale", []).append(
            {"round": b.round, "why": "裏取りを通っていない形の findings（旧形の素の文字列、または cite 無し）"
                                      "に乗った『狭めている』なので、R2 を止める根拠には使わない"})
    # 原因を運ぶ 1 値（None／目的不明／狭めている）——bool に畳むと record_round が定数文で説明するしかなく、理由が事実と逆になる
    # （実測 2026-09-13: 狭めている周の R2 の reason が『P0-4 で目的不明』）
    ls["purpose_unusable"] = "目的不明" if src == "目的不明" else ("狭めている" if narrowed else None)
    ls["purpose_known"] = ls["purpose_unusable"] is None
    if fix.get("premise_drift"):
        ls.setdefault("drift_notes", []).append({"round": b.round, "text": fix.get("premise_drift_note", "")})
    return {"ok": True, "open_units": ls["open_units"], "r1_refire": ls["r1_refire"], "r2_refire": ls["r2_refire"],
            "lines_ratio": ratio, "ledger_changed": ls["ledger_changed"], "purpose_known": ls["purpose_known"]}


def _stuck_unrouted(b, V, out):
    """履歴を読む判定の節（reads に loop.prev_blocks）で、同じ [block] が 3 周続けて在るのに振り分けた跡の無いユニットを拒む。
    式は検証器の stuck_unlisted を import して前の 2 周の記録とこの返答に当てる（写さない）。以前は周の記録の段（p4.record）で
    初めて落ち、その周の判定の節は done 済みで返させ直せなかった（実測 2026-09-24 の 4 周目。判定のプロンプトにも規則が無かった）"""
    prev = [read_json(p) for p in (b.dir / "rounds" / f"round-{n}.json" for n in (b.round - 2, b.round - 1)) if p.is_file()]
    if len(prev) < 2:
        return []
    cand = {"round": b.round, "units": out.get("units") or [], "questions": out.get("questions") or []}
    return [f"同じ [block] '{k[:60]}' が 3 周続けて在る（2 周連続の残存＝stuck）——処方の誤りか設計の問題かを振り分け、"
            "このユニットを origin に持つ未決の問い（stuck か fork）を questions に載せよ" for _, k in V.stuck_unlisted(prev + [cand])]


def _defer_ledger(b):
    """盤面の defer 台帳（key → {reason, round}）を、検証器の述語が読む形（key → (理由, 周)）にする"""
    return {k: (v.get("reason"), v.get("round")) for k, v in (b.loop_state.get("defer_ledger") or {}).items()}


def _history_rules(b, V, nd, out):
    """周をまたぐ検証器の規則（defer の再浮上の根拠・未決の問いの連続）を、判定の受け付けで当てる。式は検証器の述語
    （JUDGE_TIME_RULES）で、写さない。**当てるのは、規則を満たすのに要る入力を読む節だけ**——履歴を見せない判定（p2.diagnose）に
    前の周の台帳を求めると、役が見ていない物を書き写せず、返させ直しても通らない（_stuck_unrouted を loop.prev_blocks で絞るのと同じ）"""
    reads = nd.get("reads") or []
    errs = []
    if "loop.prev_units" in reads:
        errs += V.reopened_without_evidence(out.get("units") or [], _defer_ledger(b))
    if "loop.prev_questions" in reads:
        # kind=unverifiable の行は除く: R が今の周も unverifiable なら周の記録の段で機械が同じ key で立て直す（record_round）ので、
        # 判定の時点では落としてよいかが決まらない（R はこの後に走る）。落としたまま R が通った周は、記録の段の検証器が止める
        prev = [q for q in b.loop_state.get("prev_questions") or [] if q.get("kind") != "unverifiable"]
        errs += V.dropped_questions(prev, out.get("questions") or [])
    return errs


def _prev_round_record(b):
    p = b.dir / "rounds" / f"round-{b.round - 1}.json"
    return read_json(p) if p.is_file() else None


def stop_branch(V, exit_code, out):
    """検証器の出力から周の分岐を決める。文言は検証器の定数を import して使う（写すと、文言を直した周に分岐が黙って
    work_remains へ倒れる）。見るのは**行頭が空白でない行**（判定と見出し）だけ——台帳・履歴・阻害要因の echo は
    「  - 」で字下げして印字され、**検証器の bullet() が 2 行目以降も字下げする**（splitlines が行と見なす文字をすべて潰す）ので、役が書いた自由文に停止文言や改行が含まれても行頭は作れない。以前は書く側（judge の key / reason）だけを 1 行に正規化していたが、覆いは 19 節中 2 節で、素材の reason・レビューの reason・台帳の resolution が外に残っていた。
    **これが成り立つのは judge_output が 1 行の欄から改行を落としているからで、行頭規則だけでは成り立たない**
    （実測 2026-09-13: 改行 1 文字で新しい行頭を作れた）。検証器の書式（字下げ）に依る点は残る——機械用の返り口を
    検証器に持たせる案は台帳の fork で decided（採らない。零処方で閉じるため）。"""
    if exit_code == 0:
        return "converged"
    lines = [ln for ln in out.splitlines() if ln and not ln[0].isspace()]
    if any(V.STOP_PREMISE in ln for ln in lines):
        return "premise_escalate"
    if any(V.STOP_WORK_EXHAUSTED in ln for ln in lines):
        return "work_exhausted"
    return "work_remains"


def record_round(b, nid, stopped_reason=None):
    """周の記録 rounds/round-<N>.json を組み、検証器にディレクトリを渡す。R の欄も機械が埋める。
    stopped_reason は人が止めた周（on_stop）——走らなかった R を条件外・持ち越しでなく、止めた事実の not_run で書く"""
    V = validator_module(b)
    rec, ls = b.record, b.loop_state
    last = ls.setdefault("last_seen", {})
    last_review = ls.setdefault("last_review", {})
    reviews = rec["reviews"]
    if ls.get("purpose_known") is False and "R2" not in reviews:
        why = ls.get("purpose_unusable") or "目的不明"
        reviews["R2"] = {"status": "unverifiable", "reason": {
            "目的不明": "元の目的の出典が取れない（P0-4 で目的不明）",
            "狭めている": "writer 自書の目的テキストを inspector が『狭めている』と判定（p0.purpose_review）——独立の出典として使えず、狭められた目的で独立設計を回さない"}[why]}
    for name in V.REVIEWS:
        if name in reviews:
            # **最後の「本物の判定」だけを覚える。** 機械が埋めた値（走らなかった節の持ち越し・条件外）で
            # 上書きすると、前の周の諮る義務が静かに消える。2 語を手で並べていた——値を足した周に漏れる
            if not V.REVIEW_STATUS[reviews[name]["status"]].machine_written:
                last_review[name] = {"round": b.round, **reviews[name]}
            continue
        prev = last_review.get(name)
        if prev and not V.REVIEW_STATUS[prev["status"]].carryable:
            # **持ち越せない値を先に見る。** 以前は R3 / R4 だけがこの腕より前で prev を一切見ずに
            # not_applicable を書いていた（R1 / R2 には下の腕が在った）。not_applicable は blocks=False なので、
            # 前の周の redesign-needed / unverifiable が**痕跡なく消える**——検証器 :167-171 が明文で禁じている
            # 「1 度持ち越した時点で人に諮る義務が阻害要因から消える」形そのもの（実測 2026-09-13: round 1 の
            # R3=redesign-needed を round 2 で上書きすると、収束を妨げるものが 3 件 → 2 件に減り、警告も trace も出ない）。
            # 再発火の条件に当たらない周でも、**据え置きは上書きより優先する**。
            reviews[name] = {"status": prev["status"], "reason": prev["reason"] + f"（round {prev['round']} と同じ。持ち越せない値なので今も諮っている記録として書く）"}
        elif stopped_reason:
            reviews[name] = {"status": "not_run", "reason": f"{stopped_reason}——この周の {name} は走っていない"}
        elif name in V.REVIEW_STATUS["not_applicable"].only_for:  # 条件外を名乗れる R だけ（表が正本）
            reviews[name] = {"status": "not_applicable",
                             "reason": f"[block]＋do-now が {ls.get('open_units', '?')} 件残り、前の周の P3 も触っていない（どちらの再発火条件にも当たらない）"}
        elif prev:
            # ここに来る prev は carryable だけ——持ち越せない値は上の 1 本目が全部取る。
            # **到達しない腕を残さない。** 1 本目を前に置いた周に `elif prev:`（同じ本文の写し）が
            # 到達不能のまま残り、読む人が生きている腕と死んだ腕を区別できなくなっていた
            reviews[name] = {"status": "carried_over", "from_round": prev["round"], "reason": "再発火の条件（機構の追加・置換／前提のドリフト／行数が R1 の時点の 1.5 倍・前の周の 2/3 以下／台帳の変化）に当たらない"}
        else:
            reviews[name] = {"status": "not_run", "reason": "走らせるべき周に返答が無い"}
    # **unverifiable を返した R 全部に、台帳の行を機械が立てる。** 検証器（validate_questions の KIND_FOR_REVIEW_STATUS の突合）は「その R を origin に持つ
    # kind=unverifiable の行が同じ周の questions に要る」と fail で要求するが、以前は R2 の腕でしか行を立てておらず、
    # R1 / R3 / R4 が同じ値を返すと**誰も書けない行を要求されて run が止まった**——R の節は judge より後の波なので
    # 台帳を書ける役は既に done、p4.record は driver なので done できず、optional でない節は skip も拒む。
    # 出口が 1 つも無く、残るのは loop.py patch だけだった（実測 2026-09-13: 写しで r3.coherence に
    # unverifiable を返させると ready が空のまま進まず、検証器単体でも R1 / R3 / R4 それぞれ exit 2）。
    # unverifiable は 3 節とも schema の enum に在る正規の返答なので、**返せる値には受け口を用意する**。
    # 行の中身は判定でなく機械的な帰結——理由は当の reviews[name] から引き、judge の再審に掛ける。
    for name in V.REVIEWS:
        if reviews.get(name, {}).get("status") != "unverifiable":
            continue
        if any(x.get("kind") == "unverifiable" and x.get("origin") == name for x in rec["questions"]):
            continue
        rec["questions"].append({
            "key": (ASK_KEYS.get(name) or f"{name} が独立に確かめられない（unverifiable）——人が材料を示すか、未収束のまま報告するか"),
            "kind": "unverifiable", "origin": name, "status": "held",
            "reason": reviews[name]["reason"]})
    if ls.get("r1_refire") and "R1" in reviews and reviews["R1"]["status"] not in ("carried_over",):
        ls["lines_at_r1"] = ls.get("diff_lines", 0)
    # [block] の件数の推移。**ラチェットの引き金 (2) の入力**——キーの完全一致では再燃を見つけられないので、
    # クラスを同定せずに「閉じる速さが開く速さを上回っているか」だけを測る
    counts = ls.setdefault("block_counts", [])
    if not any(x["round"] == b.round for x in counts):
        counts.append({"round": b.round, "n": sum(1 for u in rec["units"] if u.get("label") == "block")})
    for name, st in rec["materials"].items():
        if st.get("status") in V.OBSERVED_STATUS:
            last[name] = b.round
        if st.get("status") != "carried_over":
            ls.setdefault("last_material", {})[name] = st
    # **前の周の修正が作った面を数える。** 判定役は毎周これを散文の note へ逃がしていて、機械が数えられなかった
    # ——実走では、この数が [block] の件数（ほぼ横ばい）より収束をよく表した（申し送り元の 10 周 run の実測）。
    hist = b.output_of_round("p2.history", b.round)
    if isinstance(hist, dict):
        rec["scalars"] = {**(rec.get("scalars") or {}),
                          "faces_created_by_prev_fix": len({x.get("key") for x in hist.get("reburn_causes") or []
                                                            if isinstance(x, dict) and x.get("cause") == "前の周の修正"})}
    round_rec = {"base": rec["base"], "round": b.round, "materials": rec["materials"], "units": rec["units"],
                 "reviews": reviews, "questions": rec["questions"]}
    if rec.get("scalars"):
        round_rec["scalars"] = rec["scalars"]
    d = b.dir / "rounds"
    d.mkdir(exist_ok=True)
    write_json(d / f"round-{b.round}.json", round_rec)
    v = b.run_validator(d)
    out = v.get("out", "")
    # 受理集合の正本は graph（advance の report の節・cmd_finalize と同じ）。集合の外（None＝時間切れ／未知の
    # 終了コード）は「検査が成立しなかった」であって合格ではない——周を進めない。
    if v["exit"] not in b.graph.get("record", {}).get("round_accepts_exit", [0, 1]):
        return {"ok": False, "exit": v["exit"], "problems": [f"記録が検証器を通らない（exit {v['exit']}。役の返答か rules の欠陥、または検証器が動かない。直して next）: " + out[-1500:]]}
    branch = stop_branch(V, v["exit"], out)
    for u in rec["units"]:
        if u["label"] == "suggest" and u.get("disposition") == "defer":
            ls.setdefault("defer_ledger", {})[u["key"]] = {"reason": u.get("reason"), "round": b.round}
        if u["label"] == "block":
            ls.setdefault("prev_blocks", [])
            if u["key"] not in ls["prev_blocks"]:
                ls["prev_blocks"].append(u["key"])
        if u["label"] == "info" and u["key"] not in ls.setdefault("closed_keys", []):
            ls["closed_keys"].append(u["key"])  # 一度閉じたキー。後の周に [block] で戻れば「再燃」（ラチェットの引き金）
    ls.setdefault("validator_outputs", {})[str(b.round)] = out
    return {"ok": True, "exit": v["exit"], "branch": branch, "out": out}


def converge(b, nid):
    """周の締め。人に諮る（decision=ask）分岐は全部、返る口のこの 1 か所で outcome=stopped と stop_reason（問いの種類）を立てる
    ——stop の答えでも無人の停止でも、記録から止めた理由が読める。continue の答えは on_answer が外す"""
    out = _converge(b, nid)
    if out.get("decision") == "ask":
        b.loop_state["outcome"] = "stopped"
        b.loop_state["stop_reason"] = ((out.get("ask") or {}).get("kinds") or [out.get("reason")])[0]
    return out


def _converge(b, nid):
    V = validator_module(b)
    rec_out = b.output_of_round("p4.record", b.round) or {}
    branch = rec_out.get("branch")
    ls = b.loop_state
    ci = b.record["materials"].get("local_checks", {})
    asking = [q for q in b.record["questions"] if q["status"] in V.ASKING]
    # 線の台帳の要約を記録に残す——止めた run の報告からも、走り終えていない線と閉じなかった見逃しが見える
    if ls.get("lanes"):
        b.record["process"]["lanes"] = lane_summary(b)
    # 暴走ガードは全部の分岐に掛かる——converged/found の早期 return の後ろに置いていたとき、CI が赤のまま上限を越えて
    # 回り続けた（実測 2026-09-13: round 9 / max 5 で running）。収束する周（阻害なし・CI 緑・最後の関門が通る）だけは上限より優先して収束させる。
    # **converged を返す道はこの 1 本の条件だけが開く**——関門の条件を読む場所を 1 か所にする（上限の柵と収束の分岐が別々に
    # branch と CI を見直していると、片方に足した条件をもう片方が飛ばす）
    if _would_converge(b) and ls.get("gates") == GATES_MERGE:
        # 関門の他が全部そろったが、関門は合流した版で撃つ run——収束を名乗らずに止める（上限の柵より先に。関門を撃たない
        # まま next_round にすると、関門が撃っていないことを理由に上限まで回る）
        ls["outcome"] = "stopped"
        ls["stop_reason"] = "gates_deferred"
        return {"decision": "stopped", "reason": f"検証器は阻害なし・CI 緑だが、{GATES_MERGE_WHY}——収束を言うのは、"
                                                "合流した版を gates=merge 無しの run で回し、最後の関門が通った時だけ"}
    gate = _final_gate_problems(b) if _would_converge(b) else None
    will_converge = gate == []
    if gate == [FINAL_GATE_EMPTY]:
        # 関門の他は全部そろい、撃てた腕だけが 0 本——収束してよいかは人が決める（無人では on_unattended が止める）。
        # run の頭に 1 度決めるフラグ（PIT の failWhenNoMutations の形）にしないのは、0 本が正しいかが周ごとの差分で変わるから
        # （同じ run でも文書だけの周と Python の周がある）
        return {"decision": "ask", "reason": "final_gate_empty", "ask": {
            "kinds": ["final_gate_empty"],
            "question": ("最後の関門: 最終のコードで変異の検算を撃ったが、撃てた腕が 0 本だった（見逃しも 0 本だが、何も確かめていない）。"
                         "差分が撃つ物の無い形（文書だけ等）だと確かめたなら continue --note <確かめたこと>（同じ木なら次の周の関門が通る）。"
                         "撃てるはずの差分なら stop（未収束のまま報告へ）"),
            "items": [f"撃った版 {(_gates_cut(b) or {}).get('rev', '')[:12]}・腕 0 本"],
            "options": ["continue", "stop"]}}
    if b.round >= b.state["max_rounds"] and not will_converge:
        # **聞くと書いたら聞く口を返す。** 以前はここだけ decision=stopped を返しており、理由の文は
        # 「台帳の held / escalate をまとめて聞く」と名乗るのに、answer の口（pending_human）が立たなかった
        # ——依頼者が「続けろ」と答えても engine に受け口が無く、state を手当てするしか進む道が無い
        # （実測 2026-09-13: 5 周で止めた run に 6 周目を頼まれ、loop.py patch --path state.* 以外の道が無かった）。
        # 他の 2 つの停止分岐（premise_escalate / work_exhausted）は最初から ask を返していたので、
        # **同じ「人に諮る」でありながら、上限だけが口を持たなかった**。
        # continue の答えは on_answer が上限を 1 周ぶんだけ上げる——上限ごと外すのではなく、
        # **余分な 1 周ごとに人が同意し直す**形にして、暴走ガードの目的（際限なく回らない）を保つ。
        return {"decision": "ask", "reason": "max_rounds", "ask": {
            "kinds": ["max_rounds"],
            "question": (f"暴走ガード: 総ラウンドが上限 {b.state['max_rounds']} に達した（収束せず）。"
                         "台帳の held / escalate に答えて 1 周だけ延ばすか（continue --note <答え>。"
                         "上限は 1 周ぶんだけ上がり、次の周末にまた聞く）、未収束のまま報告に進むか（stop）"),
            "items": [f"[{q['status']}] {q['kind']}: {q['key']} — {q.get('reason', '')}"
                      + (f" 選択肢: {q['options']}" if q.get("options") else "") for q in asking],
            "options": ["continue", "stop"],
        }}
    if will_converge:
        ls["outcome"] = "converged"
        return {"decision": "converged", "reason": f"検証器が連続 2 ラウンド阻害なし・CI 緑（local_checks clean: {(ci.get('checked') or '')[:80]}）・"
                                                  "最後の関門（最終のコードで撃ち直した変異の見逃しが全部等価）が通った。"
                                                  "残った指摘は意図的に受容した設計判断として理由を明示して終える"}
    if gate:
        return {"decision": "next_round", "reason": "最後の関門が通らない——" + "; ".join(gate)[:600]
                + "（振る舞いの変わる見逃しは次の周の判定へ渡す）"}
    if branch == "converged":
        st = ci.get("status")
        if st == "found":
            return {"decision": "next_round", "reason": "検証器は阻害なしだが CI が赤（local_checks が found）——P3 で直してから"}
        if st == "clean" and not _ci_by_engine(b.record["process"].get("checks"), b.round):
            why = ((b.record["process"].get("checks") or {}).get("p4.ci") or {}).get("why") or "この周の p4.ci を engine が走らせていない"
            return {"decision": "ask", "reason": "ci_unverified（local_checks の clean は任せ先の自己申告）", "ask": {
                "kinds": ["ci_unverified"],
                "question": (f"検証器は阻害なしで CI は clean と書かれたが、engine が走らせた結果ではない（{why}）。"
                             f"走らせる語を宣言 {DECL_NAME} に書けば次の周から engine が走らせる。"
                             "確かめてから続けるか（continue --note <何を走らせて何色だったか>）、未収束のまま報告に進むか（stop）"),
                "items": [f"local_checks: clean（任せ先の申告）— {ci.get('checked') or ''}"],
                "options": ["continue", "stop"],
            }}
        if st != "clean":
            # 確かめていない CI を緑と数えない——素材は 6 値で、赤でないことは緑ではない（not_applicable / not_run /
            # awaiting_human / carried_over / 欄なし）。プロンプトは「緑を仮定して進むな」と書くが機械が縛っていなかった
            # （実測 2026-09-12: 台本の local_checks と p4.ci を not_applicable にすると 3 周で converged・検証器 exit 0）。
            return {"decision": "ask", "reason": f"ci_unverified（local_checks が {st or '無し'}）", "ask": {
                "kinds": ["ci_unverified"],
                "question": (f"検証器は阻害なしだが CI を確かめていない（local_checks が {st or '無し'}: "
                             f"{ci.get('reason') or ci.get('checked') or ci.get('detail') or ''}）。"
                             "確かめてから続けるか（continue --note <何を走らせて何色だったか>）、未収束のまま報告に進むか（stop）"),
                "items": [f"local_checks: {st or '無し'} — {ci.get('reason') or ci.get('checked') or ci.get('detail') or ''}"],
                "options": ["continue", "stop"],
            }}
    if branch in ("premise_escalate", "work_exhausted"):
        return {"decision": "ask", "reason": branch, "ask": {
            "kinds": [branch],
            "question": ("前提不成立が確定した——残る仕事は全てその答えに従属する。" if branch == "premise_escalate" else
                         "残る阻害要因は保留の問いに帰属するものだけ——答え無しに進める仕事は無い。") +
                        " 台帳の held / escalate に答えるか（continue --note <答え>）、未収束のまま報告に進むか（stop）",
            "items": [f"[{q['status']}] {q['kind']}: {q['key']} — {q.get('reason', '')}" + (f" 選択肢: {q['options']}" if q.get("options") else "") for q in asking],
            "options": ["continue", "stop"],
        }}
    return {"decision": "next_round", "reason": "阻害要因が残る（検証器の出力を P2 の履歴に渡す）"}


# ---------------------------------------------------------------- 規模の数値（p4.scalars）
SCALARS_FIXED = ("added_lines", "comment_lines", "comment_ratio_pct")   # comment-ratio.sh が印字する名前（doc_lines は numstat）


def _comment_ratio(b, base, rev):
    """comment-ratio.sh <BASE> <版> の最後の scalars: 行 ——（名前 → 数, 測れなかった理由）。印字を読むだけで数え直さない"""
    import subprocess
    script = pathlib.Path(b.state["inputs"].get("scripts_dir") or "") / "comment-ratio.sh"
    try:
        r = subprocess.run(["bash", str(script), base, rev], cwd=_repo_root() or None, capture_output=True, text=True,
                           encoding="utf-8", errors="replace", stdin=subprocess.DEVNULL)
    except OSError as e:
        return {}, f"comment-ratio.sh を起こせない（{e}）"
    if r.returncode != 0:
        return {}, f"comment-ratio.sh が exit {r.returncode}: {(r.stderr or r.stdout).strip()[-300:]}"
    line = next((ln for ln in reversed(r.stdout.splitlines()) if ln.startswith("scalars:")), None)
    if line is None:
        return {}, "comment-ratio.sh の出力に scalars: 行が無い"
    got = {}
    for kv in line[len("scalars:"):].split():
        k, _, v = kv.partition("=")
        if k in SCALARS_FIXED and v.isdigit():
            got[k] = int(v)
    return got, None


def scalars(b, nid):
    """規模の数値を engine が数える（任せ先が写していた頃、added_lines 0（実測 457）・1957（実測 9）・全部 0 と写し違えた）。
    数える版は p3.gates_cut が固めたこの周の最後の版 1 つ（線・最後の関門と同じ版）。コードの 3 つは comment-ratio.sh の印字、
    doc_lines は `git diff --numstat BASE <版> -- '*.md'` の追加行の合計（added_lines と同じ物差し。判定から入る run で周の頭の
    変更一覧が空でも差分から数える）。その場で足す x_ の数値は p3.fix の返答の x_scalars から。
    **測れなかった値は書かない**（0 にしない）が、**周も止めない**——scalar はゲートでない（増分は R1 への入力）。
    測れなかった理由は process.scalars_unmeasured に周ごとに残す"""
    cut = _gates_cut(b)
    base = b.record.get("base")
    got, why = {}, []
    if not cut or not base:
        why.append("この周の最後の版（p3.gates_cut）か BASE が無い")
    else:
        got, err = _comment_ratio(b, base, cut["rev"])
        if err:
            why.append(err)
        ns = git("diff", "--numstat", "-z", base, cut["rev"], "--", "*.md")
        if ns is None:
            why.append(f"git diff --numstat {base[:12]} {cut['rev'][:12]} が取れない（doc_lines）")
        else:
            got["doc_lines"] = numstat_totals(ns)[1]
    x = (b.output_of_round("p3.fix", b.round) or {}).get("x_scalars") or {}
    b.record["scalars"] = {**got, **x}
    if why:
        b.record["process"].setdefault("scalars_unmeasured", {})[str(b.round)] = "; ".join(why)
    return {"ok": True, "scalars": b.record["scalars"], **({"unmeasured": why} if why else {})}


BUILTINS = {"worktree_snapshot": worktree_snapshot, "worktree_compare": worktree_compare, "assemble": assemble, "fix_delta": fix_delta,
            "delta_owed": delta_owed, "gates_cut": gates_cut, "lane_merge": lane_merge,
            "record_round": record_round, "converge": converge, "scalars": scalars}


# ---------------------------------------------------------------- 走らせるだけの節（graph の engine_run）
# 走らせて写すだけの節を任せ先（haiku）に渡していた頃、走り切る前に読む・写し違える・一部を飛ばすが 1 周目で止めた run の
# 全部で出た（実測 2026-09-25: テスト 572 件の途中の 537 件で clean、CI の 2 系統のうち 1 系統だけ）。engine が走らせ、
# 終了コードから返答を組む。何を走らせるかは対象リポジトリの宣言（engine/declared.py。人の承認は要らない——外した理由と
# 守られなくなった物はそこの注記）。
# 宣言の無いリポジトリだけ任せ先に落とし、その周の CI を engine が確かめていないことを process.checks に残す
# ——converge はそれを『CI を確かめていない』として人に諮る（_ci_by_engine）。


def _checks_note(b, nid, **kw):
    b.record["process"].setdefault("checks", {})[nid] = {"round": b.round, **kw}


def checks_plan(b, nid):
    root = _repo_root()
    if not root:
        return {"fallback": "リポジトリのルートが引けない"}
    d = declared_checks(root)
    if d is None:
        return {"fallback": f"対象リポジトリに走らせる語の宣言 {DECL_NAME} が無い——任せ先が CI の定義から走らせる（engine は終了コードを見ていない）"}
    if "error" in d:
        return {"blocked": d["error"]}
    return {"steps": d["steps"], "sha": d["sha"]}


def checks_fallback(b, nid, reason):
    _checks_note(b, nid, by="role", why=reason)


def checks_reply(b, nid, launch, runs):
    """走らせた結果から local_checks の素材を組む。走らせられないときは、判定の前（p0）なら awaiting_human、判定の後（p4.ci）
    なら not_run（人待ちを新しく立てない規則）。p4.ci は台帳に local_checks を出どころにする未決の人待ちが在れば、走らせた
    結果を reason に入れて awaiting_human のまま組む——その判定は check_record と同じ _awaiting_origins を通す（写さない）"""
    after_judge = nid == "p4.ci"
    cant = "not_run" if after_judge else "awaiting_human"
    if launch.get("blocked"):
        m = {"status": cant, "reason": launch["blocked"]}
        _checks_note(b, nid, by="engine", blocked=launch["blocked"])
    else:
        summary = "; ".join(f"{r['name']}: exit {r['exit']}（{r['wall_s']} 秒）" for r in runs)
        broken = [r for r in runs if r["exit"] is None]
        red = [r for r in runs if r["exit"] not in (0, None)]
        if broken:
            m = {"status": cant, "reason": "宣言の語を起こせない: " + "; ".join(f"{r['name']}: {r.get('error')}" for r in broken)}
        elif red:
            m = {"status": "found", "count": len(red),
                 "detail": f"engine が宣言 {DECL_NAME} を走らせた: {summary} ／ " + " ／ ".join(f"{r['name']} の末尾: {r['tail'][-600:]}" for r in red)}
        else:
            m = {"status": "clean", "checked": f"engine が宣言 {DECL_NAME}（sha {launch['sha'][:12]}）の {len(runs)} 段を走らせた: {summary}"}
        _checks_note(b, nid, by="engine", sha=launch.get("sha"),
                     runs=[{k: r.get(k) for k in ("name", "argv", "exit", "wall_s", "out", "err")} for r in runs])
    if after_judge and m["status"] != "awaiting_human":
        V = validator_module(b)
        if _awaiting_origins(V, b.record["questions"], {**b.record["materials"], "local_checks": m}, "questions"):
            m = {"status": "awaiting_human", "reason": ("台帳に local_checks を出どころにする人待ちの問いが在る（閉じるのは次の周の判定者）——"
                                                       f"engine が走らせた結果: {m.get('checked') or m.get('detail') or m.get('reason')}")[:1500]}
    return {"reply": {"material": m}}


GITHUB_REMOTE = re.compile(r"^(?:https?://github\.com/|ssh://git@github\.com[^/]*/|git@github\.com[^:]*:)([^/\s]+)/([^/\s]+?)(?:\.git)?/?$")


def _github_repo():
    """並行 PR を引く owner/repo ——（値, 引けない理由）。upstream の remote を先に、無ければ origin（p0.parallel_pr.md の 1 段）"""
    up = git("rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}")
    remote = up.strip().split("/", 1)[0] if up and up.strip() else "origin"
    url = git("remote", "get-url", remote)
    if url is None:
        return None, f"remote '{remote}' の URL が引けない"
    m = GITHUB_REMOTE.match(url.strip())
    if not m:
        return None, f"remote '{remote}' が GitHub でない（{url.strip()[:80]}）——同等のコマンドへの読み替えは役"
    return f"{m.group(1)}/{m.group(2)}", None


def _pr_files(b):
    """交差を取る変更ファイルの集合。差分が空（判定から入る run）なら、依頼の where の文字列に含まれる、追跡中のパス"""
    f = b.loop_state.get("changed_files_file")
    files = [ln.strip() for ln in pathlib.Path(f).read_text(encoding="utf-8").splitlines() if ln.strip()] if f and pathlib.Path(f).is_file() else []
    if files:
        return files
    wheres = request_wheres(b)
    tracked = (git("ls-files", "-z") or "").split("\0")
    return sorted({t for t in tracked if t and any(t in w for w in wheres)})


def parallel_pr_plan(b, nid):
    repo, why = _github_repo()
    if not repo:
        return {"fallback": why}
    if not shutil.which("gh"):
        return {"fallback": "gh がこの環境に無い"}
    files = _pr_files(b)
    if not files:
        return {"blocked": "交差を取る変更ファイルの集合が空（差分も、依頼の where が名指す追跡中のパスも無い）——空の集合との交差は何も確かめない"}
    head = (git("rev-parse", "HEAD") or "").strip()
    f = b.dir / "runs" / f"r{b.round}" / "parallel_pr-files.txt"
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text("\n".join(files) + "\n", encoding="utf-8")
    return {"helper": "parallel-pr.py", "args": ["--repo", repo, "--head", head, "--changed", str(f)]}


def parallel_pr_reply(b, nid, launch, runs):
    """同梱の parallel-pr.py の印字から返答を組む。交差が在れば 6 段（hunk を読んで担当の PR に申し送る）が要るので任せ先に回す"""
    empty = {"repo": "", "listed": 0, "truncated": False, "conflicts": []}
    if launch.get("blocked"):
        return {"reply": {"material": {"status": "not_run", "reason": launch["blocked"]}, **empty}}
    r = runs[0]
    if r["exit"] != 0:
        return {"reply": {"material": {"status": "awaiting_human", "reason": f"parallel-pr.py が exit {r['exit']}（確かめられなかった）: {(r.get('error') or r['tail'])[-600:]}"}, **empty}}
    try:
        got = json.loads(pathlib.Path(r["out"]).read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        return {"reply": {"material": {"status": "awaiting_human", "reason": f"parallel-pr.py の印字が読めない（{e}）"}, **empty}}
    rest = {k: got.get(k) for k in ("repo", "listed", "truncated")}
    if got.get("conflicts"):
        return {"fallback": f"並行 PR と {len(got['conflicts'])} 件交差した（{[c['pr'] for c in got['conflicts']][:10]}）——交差した hunk を読んで担当の PR に申し送る 6 段は役"}
    if got.get("truncated"):
        return {"reply": {"material": {"status": "awaiting_human", "reason": f"gh pr list が上限 {got.get('listed')} 件で打ち切られた——打ち切られた一覧で衝突なしと書かない"}, **rest, "conflicts": []}}
    return {"reply": {"material": {"status": "clean", "checked": (f"engine が gh -R {got['repo']} で open な PR {got['listed']} 件を引き、自分の PR（headRefOid が HEAD）を除いて、"
                                                            f"変更ファイルの集合と交差 0 件（打ち切りなし）")}, **rest, "conflicts": []}}


ENGINE_RUNS = {"declared_checks": {"plan": checks_plan, "reply": checks_reply, "fallback": checks_fallback},
               "parallel_pr": {"plan": parallel_pr_plan, "reply": parallel_pr_reply}}


# ---------------------------------------------------------------- 節ごとの整合（post_check）
# 多くは out を検査して Reject を投げるだけだが、例外が 2 つ在る: base_valid は record.base を、r2_design は
# reviews.R2（premise-invalid）を書く。record の書き込みは本来 WRITE_OPS の仕事で、この 2 つは「検査の結果で
# 初めて決まる値」なので post_check に置いている（見出しが「out を検査するだけ」と名乗っていたのは事実と違った）。
def base_valid(b, nid, out, item):
    sha = out["base_sha"]
    if not re.fullmatch(r"[0-9a-f]{7,40}", sha) or git("cat-file", "-e", f"{sha}^{{commit}}") is None:
        raise Reject(f"BASE '{sha}' がこのリポジトリのコミットでない")
    b.record["base"] = git("rev-parse", sha).strip()


ONE_LINE_FIELDS = ("key", "reason")


def _carried_r1_accounted(b, out):
    """前の周の R1 最小性が挙げた削除候補を、judge が 1 件につき 1 行で処理したか。

    **直したのは「渡してはいるが誰も数えていない」面。** 配線は前から在る——p2.diagnose も p3.fix も
    reads に prev.r1.minimality を持ち、前の周の削除候補は judge にも writer にも届いていた。
    届いた上で落とせたのは、直す義務が record["units"] にしか掛からないからで（fix_covers_open_units）、
    判定者が unit に昇格させなければ誰も赤くならなかった。実測（別リポジトリの run、2026-09-16）:
    1 周目の最小性が挙げた 14 件が 2 周目の修正対象に 1 件も入らず、2 周目の最小性でそのまま再掲された。

    数え方は宣言レンズと同じ形にしてある——**照合の両側が同じ文字列**（judge は貼られた行の no で指し、engine が where に戻す）。
    綴りを寄せる正規化の段は置かない。置けば、その規則自体が誰も決めていない未定義物になる。
    """
    # **「前の周の R1」は「最後に走った R1」ではない。** outputs は節ごとに最新の 1 件しか持たず、
    # R1 は再発火条件付き（cond: loop.r1_refire）なので、走らなかった周を挟むと数周前の出力が返る
    # ——処理済みの削除候補が次の周にも同じ顔で要求される（実測 2026-09-16・静的。嘘の緑ではなく
    # 要求が過剰に出る向きだが、役には直す術が無い形なので同じく止まる）。直前の周のものだけを見る。
    info = (b.state.get("outputs") or {}).get("r1.minimality") or {}
    if info.get("round") != b.round - 1:
        return []
    prev = b.outputs(before_round=b.round).get("r1.minimality") or {}
    want = [d["where"] for d in prev.get("deletions", []) if isinstance(d, dict) and d.get("where")]
    rows = out.get("carried_r1") or []
    errs, seen = [], {}
    for i, r in enumerate(rows):
        w = r.get("where", "")
        if w in seen:
            errs.append(f"carried_r1 に同じ where の行が 2 本: {w}")
        seen[w] = r
        if w not in want:
            errs.append(f"carried_r1[{i}] の where '{w}' は前の周の R1 の削除候補に無い（正本は prev.r1.minimality.deletions。写さずに、貼られた行の no で指せ）")
        elif r["disposition"] == "promote" and not (r.get("unit_key") or "").strip():
            errs.append(f"carried_r1[{i}]（{w}）が disposition=promote なのに unit_key が無い")
        elif r["disposition"] == "decline" and not (r.get("why") or "").strip():
            errs.append(f"carried_r1[{i}]（{w}）が disposition=decline なのに why が無い——落とす判断にも理由が要る")
    keys = {u["key"] for u in out.get("units", [])}
    for r in rows:
        if r.get("disposition") == "promote" and r.get("unit_key") and r["unit_key"] not in keys:
            errs.append(f"carried_r1 の unit_key '{r['unit_key']}' が units に無い")
    for w in want:
        if w not in seen:
            errs.append(f"前の周の R1 が挙げた '{w}' の行が carried_r1 に無い——unit に上げるか、落とす理由を書け。"
                        "**行を省くな**（省けるなら、読んだ上で黙って落とせていた元の穴に戻る）")
    return errs


def _fork_moves_forward(b, out):
    """fork が出どころの [block] を免除するのは 1 周だけ。2 周目からは escalate（人に実際に届く形）に上げろ。

    **義務は動ける役の手前に置く。** 最初この柵を P3（fix_covers_open_units）に置いたが、writer には
    questions を書く権限が無く、同じ周の p2 は既に done で再実行できず、p3.fix は optional でないので
    skip もできない——正本のプロンプトが「fork の出どころは実装するな」と言う所で機械が「実装しろ」と
    言い、writer の手が無くなった（実測 2026-09-16: judge が [block] として名指しした）。
    questions を書けるのは p2 の節なので、ここで返させ直す。

    突き合わせるのは問いの key でなく**免除される対象**（origin と depends）。key は自然文で毎周
    judge が書き直すので、少し言い換えるだけで「新しい fork」になり免除が更新される——しかも記録に
    痕跡が残らない。対象は unit の key なので綴りが安定している。
    """
    V = validator_module(b)
    prev_exempt = set()
    for q in (b.loop_state.get("prev_questions") or []):
        if q.get("kind") == "fork" and q.get("status") in V.ASKING:
            prev_exempt |= {q.get("origin")} | set(q.get("depends", []) or [])
    prev_exempt.discard(None)
    if not prev_exempt:
        return []
    errs = []
    for i, q in enumerate(out.get("questions", [])):
        if q.get("kind") != "fork" or q.get("status") != "held":
            continue
        again = ({q.get("origin")} | set(q.get("depends", []) or [])) & prev_exempt
        if again:
            errs.append(f"questions[{i}]（fork）の出どころ {sorted(again)} は前の周も fork で免除されていた——"
                        "held のまま 2 周目に入ると、人には何も届かないまま [block] が未着手で通り続ける。"
                        "escalate に上げて人に聞くか、decided / resolved に倒せ")
    return errs


def _precedent_gap(r):
    """先行例の 1 行に足りない物（無ければ空文字）。判定者の行と修正役の行が同じ規則を使う——見つからないなら何を探したか、
    それ以外は一次情報の出典"""
    if r.get("verdict") == "not_found":
        return "searched（何をどう探したか）が無い" if blank(r.get("searched"), 4) else ""
    return "source（一次情報の出典）が無い" if blank(r.get("source"), 4) else ""


def _precedent_errors(V, out):
    """判定者の先行例の行（precedents）: 今の周に直す単位と人へ回す問いの key ごとに 1 行、出典つき。人へ回す問いの行には
    『世界の解を当たっても決まらない理由』。**機構を新設した修正を、ループの誰も『再発明』と言わなかった**（実測 2026-09-24:
    自前のミニ言語が 3 周続けて隙間を出し、人に回した岐路も OWASP を引けば決まる問いだった）"""
    rows = out.get("precedents") or []
    errs, by = _keys_once(rows, "precedents"), {r["key"]: r for r in rows}
    for i, r in enumerate(rows):
        gap = _precedent_gap(r)
        if gap:
            errs.append(f"precedents[{i}]（{r['verdict']}）に {gap}")
    need = [(u["key"], False) for u in out["units"] if V.is_open(u)]
    need += [(q["key"], True) for q in out["questions"]
             if (q.get("kind") == "fork" and q.get("status") in V.ASKING) or q.get("status") == "escalate"]
    for k, asks in need:
        r = by.get(k)
        if r is None:
            errs.append(f"precedents に '{k[:60]}' の行が無い——今の周に直す単位と人へ回す問いには、世界の解（先行例）を当たった行が要る")
        elif asks and blank(r.get("undecided_because"), 10):
            errs.append(f"precedents['{k[:60]}'] に undecided_because が無い——世界の解を当たっても決まらない理由（困っている点・残る不安）を"
                        "書け。書けないなら自明なので人に回さず、処方として採れ")
    return errs


def _awaiting_origins(V, questions, materials, where):
    """人待ちの問い（kind=awaiting で未決）の出どころが、今 awaiting_human の素材か。検証器は周の最後の 1 回だけ見るので、
    **欄を書いた時点で同じ規則を当てる**（OWASP Input Validation Cheat Sheet: 入力の検証は "as early as possible in the data flow"）。
    入口は 2 つ（判定者が人待ちでない欄を出どころにする・後の工程が人待ちの欄を上書きする）で、どちらも節の done なので、
    全部の done が通る check_record 1 か所から呼ぶ"""
    errs = []
    for i, q in enumerate(questions):
        if V.origin_not_awaiting(q, materials):
            m = materials[q["origin"]]
            errs.append(f"{where}[{i}]（awaiting・{q['status']}）の出どころの素材 '{q['origin']}' が {m.get('status')}——awaiting の出どころは"
                        "今 awaiting_human の素材だけ。素材を書く節は、人に諮っている最中の欄を awaiting_human のまま書け（見た結果は reason に）。"
                        "人が実地で確かめるまで決まらない問いは kind=field で立てろ（素材の欄を借りない）")
    return errs


def _declared_route_errors(b, out):
    """前の周に残すと宣言した穴を、判定者が 1 件ずつ振り分けたか（to_unit＝今の周の直す単位に上げた／accept＝残すことを認めた）"""
    asked = {r["key"] for r in b.loop_state.get("prev_declared_faces") or []}
    rows = out.get("declared_routed") or []
    errs = _keys_once(rows, "declared_routed")
    errs += [f"declared_routed の key '{r['key'][:40]}' は前の周に宣言された穴に無い" for r in rows if r["key"] not in asked]
    errs += [f"前の周に残すと宣言された穴 '{k[:40]}' を振り分けていない——to_unit（直す単位に上げる）か accept（残すことを認める）で答えろ"
             for k in sorted(asked - {r["key"] for r in rows})]
    units = {u["key"] for u in out.get("units") or []}
    errs += [f"declared_routed '{r['key'][:40]}' は to_unit なのに unit_key が今の周の units に無い" for r in rows
             if r["route"] == "to_unit" and r.get("unit_key") not in units]
    return errs


def judge_output(b, nid, out, item):
    """judge の返答を、検証器の語彙（写さず import）で先に見る。落ちるなら judge に返させ直す。
    あわせて 1 行の欄を 1 行に正規化する（out を補うだけ。記録を書くのは writes）。"""
    V = validator_module(b)
    errs = []
    # **役の自由文から改行を落とす。** 検証器は台帳と阻害要因を「  - 」で字下げして echo するので、key / reason の
    # 中の改行が新しい行頭を作り、その行が停止文言を含めば stop_branch の行頭規則が判定行と読み違える——返答 1 文字
    # （\n）で premise_escalate / work_exhausted に倒せた（実測 2026-09-13）。代理（印字の書式）と正本（検証器の判定）を
    # 一対一にするのは、読む側を狭めることでなく入力の側を 1 行に固定すること
    for row in list(out.get("units", [])) + list(out.get("questions", [])):
        for f in ONE_LINE_FIELDS:
            if isinstance(row.get(f), str):
                row[f] = " ".join(row[f].split())
    if nid == "p2.history":
        errs += _declared_route_errors(b, out)
    keys = set()
    root, replaced, zeroed, zero_keys = None, [], [], []
    for i, u in enumerate(out["units"]):
        if u["key"] in keys:
            errs.append(f"units[{i}] の key が重複: {u['key']}")
        keys.add(u["key"])
        if u["label"] not in V.LABELS:
            errs.append(f"units[{i}] の label が不正: {u['label']}")
        if u["label"] == "suggest":
            if u.get("disposition") not in ("do-now", "defer"):
                errs.append(f"units[{i}]（suggest）に disposition（do-now / defer）が無い")
            elif u["disposition"] == "defer" and not u.get("reason"):
                errs.append(f"units[{i}] の defer に構造的理由が無い")
        # 今の周に直す単位は、同じ形を**全部**引ける機械の問いを持て。名指しの 1 site だけを塞ぐ閉じ方が 3 周続き、
        # 同じ不変条件の別の入口が毎周ちがう顔で出た（実測 2026-09-13: 判定者自身が『覆いの母数を誰も持たない』と書いた）。
        # 問い（how）と件数（total）が在れば、次の周の判定者が同じコマンドを走らせて母数を検算できる。
        # **「この周に直す単位か」の正本は検証器の is_open。** rules 側に同じ式の写しを持っていたので、
        # 要求する母数（class_query を課す側）と数える母数（検証器）が片方だけ動けば静かにずれる形だった。
        if V.is_open(u):
            if root is None:
                root = _repo_root() or ""
            cq = u.get("class_query") or {}
            if not cq.get("how") or not isinstance(cq.get("total"), int) or isinstance(cq.get("total"), bool):
                errs.append(f"units[{i}]（今の周に直す単位）に class_query（how＝同じ形を全部引ける機械の問い・total＝その件数）が無い"
                            "——1 site しか無いなら total: 1 でそう示せ")
            else:
                # 判定役が読んだのと同じ版（この周に固定した版）で数える。修正役の after は作業ツリーで数える
                got, why = _run_query(b, f"units[{i}].class_query", cq["how"], root, rev=(b.state.get("inputs") or {}).get("review_rev"))
                if why:
                    errs.append(why)
                elif got == 0 and cq["total"] != 0:
                    # **0 件は黙って置き換えない**——在るべき物が無い型の欠陥（数える問いは正しく 0）と、問いが対象を
                    # 取りこぼした形を engine は区別できない。置き換えると 0 が修正役の『判定者の母数』になり、
                    # 母数を狭めていないかの検査がその単位で効かなくなる。役の数を残し、0 だったことを note に書く
                    zeroed.append(f"units[{i}].class_query（役 {cq['total']} / engine 0）")
                    zero_keys.append(u["key"])
                    cq["note"] = (f"{cq.get('note') or ''}（engine が how を走らせると 0 件——在るべき物が無い型か、問いが対象を"
                                  f"取りこぼしている。役の書いた {cq['total']} を残した）").strip()
                elif got != cq["total"]:
                    replaced.append(f"units[{i}].class_query.total {cq['total']} → {got}")
                    cq["note"] = (f"{cq.get('note') or ''}（役の書いた total は {cq['total']}。engine が how を走らせた {got} に置き換えた）").strip()
                    cq["total"] = got
    # 一撃は反証可能に——「何が消えるはずか」を名指しし、次の周が測る問いを添える。名指しが無いと、
    # 効かなかったことを誰も言えないまま次の周が同じ根を選び直す（実測 2026-09-13: 3 周とも同じ根）
    open_units = [u for u in out["units"] if V.is_open(u)]
    closes = out.get("one_shot_closes") or []
    if open_units:
        if not closes:
            errs.append("one_shot_closes が空——その一撃が閉じると見込む unit の key を名指ししろ（次の周が実際の再発と突き合わせる）")
    unknown = [k for k in closes if k not in keys]
    if unknown:
        errs.append(f"one_shot_closes に今の周の units に無い key: {unknown}")
    defer = set(b.loop_state.get("defer_ledger", {}))
    for i, q in enumerate(out["questions"]):
        unknown = sorted(set(q) - set(V.QUESTION_FIELDS))
        if unknown:
            errs.append(f"questions[{i}] に知らない欄: {unknown}（書けるのは {'/'.join(V.QUESTION_FIELDS)}）")
        kind, status = q.get("kind"), q.get("status")
        if kind not in V.QUESTION_KINDS:
            errs.append(f"questions[{i}] の kind が不正: {kind}")
            continue
        if status not in V.QUESTION_STATUS:
            errs.append(f"questions[{i}] の status が不正: {status}")
            continue
        domain, extra = V.QUESTION_KINDS[kind].domain, V.QUESTION_KINDS[kind].fields
        for f in ("reason",) + extra + V.QUESTION_STATUS[status]:
            if not q.get(f):
                errs.append(f"questions[{i}]（{kind}/{status}）に '{f}' が要る")
        if kind == "fork" and not (isinstance(q.get("options"), list) and len(q["options"]) >= 2):
            errs.append(f"questions[{i}] の options は選択肢 2 つ以上（各項に帰結まで）")
        # 出どころ（origin と depends）の走査は検証器の targets 1 本——3 走査を別々に書くと depends を足した修正が 2 か所にしか
        # 当たらない（検証器自身の docstring に同じ事故が書いてある）
        for fld, dom, val in V.targets(q):
            if dom == "unit" and val not in keys | defer:
                errs.append(f"questions[{i}] の {fld} '{val}' が units にも defer 台帳にも無い")
            elif dom == "material" and val not in V.MATERIALS:
                errs.append(f"questions[{i}] の {fld} は素材名: {val}")
            elif dom == "review" and val not in V.REVIEWS:
                errs.append(f"questions[{i}] の {fld} は R1〜R4: {val}")
        if domain == "none" and (q.get("origin") or q.get("depends")):
            errs.append(f"questions[{i}]（{kind}）は origin / depends を持てない")
        for d in q.get("depends", []) or []:
            if d not in keys | defer:
                errs.append(f"questions[{i}] の depends '{d}' が units にも defer 台帳にも無い")
        if status in V.ASKING and kind in V.NO_OPEN_ORIGIN:
            for k in [q.get("origin")] + list(q.get("depends", []) or []):
                u = next((x for x in out["units"] if x["key"] == k), None)
                if u and V.is_open(u):
                    errs.append(f"questions[{i}]（{kind}）の出どころ '{k}' が [block] / do-now（人に聞く前に直す義務が消える。defer にして構造的理由を書け）")
        errs += [f"questions[{i}]: {m}" for m in V.settled_state_errors(q, out["units"])]
    awaiting = {name for name, m in b.record["materials"].items() if m.get("status") == "awaiting_human"}
    listed = {q.get("origin") for q in out["questions"] if q.get("kind") == "awaiting" and q.get("status") in V.ASKING}
    for name in sorted(awaiting - listed):
        errs.append(f"素材 '{name}' が awaiting_human なのに台帳に kind=awaiting で無い")
    if out.get("materials_missing"):
        errs.append("judge が素材の欠落を報告した（P2 を止めて当該 grader を再起動しろ）: " + ", ".join(out["materials_missing"]))
    # **義務を負うのは、その欄を持つ節だけ。** judge_output は p2.diagnose と p2.history の 2 節が共有するが、
    # carried_r1 を schema に持つのは前者だけ。節を見ずに当てていたとき、前の周の R1 が削除候補を 1 件でも
    # 挙げた周は p2.history が必ず落ち、しかも schema が additionalProperties: false なので役には直す術が
    # 無かった（P2 が二度と通らない＝周が進まない。実測 2026-09-16、push した後に気づいた）。
    # **義務は入力に従う（fail-closed）。** 前の周の R1 を読む節は carried_r1 を持たなければならない。
    # 「schema に在れば数える」だけだと、欄を落とすだけで柵が黙って消える——engine は graphcheck を
    # 一度も呼ばないので（init --graph <任意のパス> は静的検査を通さない graph も受ける）、
    # 同じ差分の local_review_covers_lenses が fail-closed を選んだ理由がこちらにもそのまま当たる。
    errs += _fork_moves_forward(b, out)
    nd = b.graph["nodes"][nid]
    # 先行例の行は schema が必須にしている節だけに当てる（judge_output は p2.diagnose と p2.history が共有する）。
    # 欄を落とした graph で柵が黙って消えないよう、節が judge の返答を書くなら欄の宣言も要求する（fail-closed）
    if "precedents" in (nd.get("schema", {}).get("properties") or {}):
        errs += _precedent_errors(V, out)
    else:
        errs.append(f"{nid} の schema に precedents が無い——先行例の行を数える口が消える（graph を直せ）")
    declares = "carried_r1" in (nd.get("schema", {}).get("properties") or {})
    if "prev.r1.minimality" in (nd.get("reads") or []):
        if not declares:
            errs.append(f"{nid} は prev.r1.minimality を読むのに schema に carried_r1 が無い——"
                        "前の周の削除候補を数える口が消える（graph を直せ）")
        else:
            errs += _carried_r1_accounted(b, out)
    if "loop.prev_blocks" in (nd.get("reads") or []):
        errs += _stuck_unrouted(b, V, out)
    errs += _history_rules(b, V, nd, out)
    if errs:
        raise Reject("judge の返答が記録の語彙に合わない（judge に返させ直す）: " + "; ".join(errs))
    # engine が 0 件と数えた単位（在るべき物が無い型か、問いの取りこぼし）を、修正の側が読める値で残す——note の文だけだと、
    # 修正役が判定者の how をそのまま使うと『問いを狭めている』で拒まれ、塞いだのに『残した』と書く形しか無かった
    b.loop_state["engine_zero"] = {"round": b.round, "keys": zero_keys}
    notes = ([f"class_query の件数を engine が走らせた値に置き換えた: {'; '.join(replaced)}"] if replaced else []) + \
            ([f"engine の数が 0 件なので置き換えなかった: {'; '.join(zeroed)}"] if zeroed else [])
    if notes:
        return " / ".join(notes)


def _owed_units(b):
    """今の周に直す義務の単位の key——開いた単位（検証器の is_open）から、人に諮っている fork の出どころ・depends を除いた物。
    修正案（fix_plan_covers_units）と修正（fix_covers_open_units）が同じこの 1 本から引く（2 か所で計算していた頃は、
    修正案の側だけ免除が抜けていた）"""
    V = validator_module(b)
    exempt = set()
    for q in b.record["questions"]:
        if q.get("kind") == "fork" and q.get("status") in V.ASKING:
            exempt.add(q.get("origin"))
            exempt.update(q.get("depends", []) or [])
    return {u["key"] for u in b.record["units"] if V.is_open(u)} - exempt


def fix_covers_open_units(b, nid, out, item):
    """[block] と do-now は必ず直す。fork の出どころ・depends だけは待ってよい（義務の集合は _owed_units）。"""
    V = validator_module(b)
    # **fork の出どころは待ってよい。** 待ちが前に進んでいるかを見るのは judge の側（_fork_moves_forward）
    # ——ここで止めると、正本のプロンプト（p3.fix.md「fork の出どころは実装するな」）と機械が逆を言い、writer には
    # questions を書く権限が無く、同じ周の p2 は既に done で再実行できない＝周が詰む（実測 2026-09-16）。義務は、動ける役の手前に置く。
    changed = {c["unit_key"] for c in out["changes"]}
    waiting = {c["unit_key"]: c["why"] for c in out.get("not_done", [])}
    missing = [f"{k}（理由: {waiting[k]}）——fork の出どころでないなら直す義務がある" if k in waiting else k
               for k in sorted(_owed_units(b) - changed)]
    if missing:
        raise Reject("直していない [block] / do-now がある（writer の裁量で defer に覆せない。異議は新しい judge に再判定させる）: " + "; ".join(missing))
    # 閉鎖の実証は自己申告——機械が検算できるのは「赤を一度も見ていないのに clean を名乗る」形だけなので、そこは拒む
    # （gate_arms_all_red と同じ形。以前は red_seen が全部 false・verified_how が「見ていない」でも clean が通った）。
    # 見るのは周の全体——文書だけの修正は赤を見られないので、修正ごとに要求すると文書を触った周が全部 found になる。
    # 修正ごとの赤の有無は sites にそのまま残り、judge が読む。
    st = out.get("fix_closure", {}).get("status")
    # **「黙って通る値」の集合は検証器の表から引く**（SILENT_STATUS＝自分で見たと主張せず、阻害要因にも出ない値）。
    # 2 語を手で写していたとき、値を足した周にその 1 値だけ柵の外に落ちる形だった——同じ欠陥を
    # check_record も持っていた（実測 2026-09-13: 6 値のうち柵が当たるのは 2 値だけ）。
    if out["changes"] and st in V.SILENT_STATUS:
        # 修正が在る周の閉鎖の実証は今の周の修正に対して行う——「条件に当たらない」「前の周の流用」は
        # 機械が持つ事実（changes が非空）と食い違う（実測: 全 site が red_seen=false でも not_applicable なら
        # 受理され、3 周で converged した）
        raise Reject(f"修正が {len(out['changes'])} 件在るのに fix_closure が {st}——閉鎖の実証は今の周の修正に対して行う（clean か found）")
    # 覆いの母数——「1 か所直して終わり」を数字で見えるようにする。closed < total は禁じない（残すのは判断）が、
    # 残したこと自体を書かせる。ここで検算できるのは数の整合だけで、問い（how）が正しいかは次の周の判定者が同じ
    # コマンドを走らせて見る（kind=実測 に measured_output を要求するのと同じ形）
    # 修正どうしの干渉。**面は「同じファイルを触った修正どうし」**（changes[].files の交差）で、面の一覧は機械が出す。
    # 別ファイルにまたがる干渉（非 UTF-8 の修正が同じ git ラッパーを共有する突合に穴を開けた形）はこの粒度では
    # 捕れない——そちらは breaks.how（同じ経路・同じ不変条件を引くコマンド）の担当。名乗りをその線に留める
    shared = {}
    for c in out["changes"]:
        for f in c.get("files", []):
            shared.setdefault(f, []).append(c["unit_key"])
    shared = {f: ks for f, ks in shared.items() if len(set(ks)) >= 2}
    if shared:
        seen = {i.get("surface"): i for i in out.get("interactions", [])}
        missing = sorted(set(shared) - set(seen))
        if missing:
            raise Reject(f"2 つ以上の修正が触った面が interactions に無い: {missing}"
                         "——面の一覧は機械が changes[].files から出す。一方が他方を不要にしないか・順序で結果が変わらないか・"
                         "組み合わせて初めて生まれる状態が無いかを突き合わせて書け")
        # 面ごとにどの修正が触ったかは shared[f] として機械が持つ——役に写させない（以前の interactions[].changes）
        for f, ks in shared.items():
            if blank(seen[f].get("checked"), 10):
                raise Reject(f"interactions[{f}] の checked が空同然——一方が他方を不要にしないか・順序で結果が変わらないか・"
                             "組み合わせて初めて生まれる状態が無いかを突き合わせた結果を書け")
    # 「破れない」「壊れない」の自己申告は、**探した形跡が無い一語**では受け取らない。機械が検算できるのは
    # 「探したと言っているか」までだが、次の周の判定者はこの欄を材料に当て直せる（kind=実測 の measured_output と同じ形）
    # 判定者が数えた母数（class_query.total）。**writer が how を狭めて total を書き直せば「1 か所直して終わり」が
    # 緑で通った**ので、判定者の値と突き合わせる（判定者の数え方を疑うなら remaining に書け）
    judged = {u["key"]: (u.get("class_query") or {})
              for u in ((b.record.get("process") or {}).get("diagnosis") or {}).get("units", [])}
    root, afters = None, []
    for c in out["changes"]:
        if blank(c.get("bypass_tried"), 10):
            raise Reject(f"{c['unit_key'][:60]}: bypass_tried が空同然——**修正を残したまま**破りに行った入力と結果を書け"
                         "（『修正を外したら赤くなった』は不在の検知であって完全性の証拠にならない）")
        br = c.get("breaks") or {}
        if blank(br.get("result"), 1):
            raise Reject(f"{c['unit_key'][:60]}: breaks.result が空同然——壊しうる面を how で引いて、壊れていないことを確かめた結果を書け")
        pr = c.get("precedent") or {}
        if pr.get("from_judge_row"):   # 判定者の行を採った印は欄で持つ（共有の verdict の語彙に修正役だけの値を混ぜない）
            if c["unit_key"] not in {r.get("key") for r in ((b.record.get("process") or {}).get("precedents") or [])}:
                raise Reject(f"{c['unit_key'][:60]}: precedent が from_judge_row なのに、判定者の先行例の行（process.precedents）にこの単位の行が無い"
                             "——自分で先行例を当たって problem と source を書け")
        elif blank(pr.get("problem"), 4) or _precedent_gap(pr):
            raise Reject(f"{c['unit_key'][:60]}: precedent に problem と source（not_found なら searched）が要る——機構を足す・形を変える修正は、"
                         "同じ問題を世の中がどう解いているかを一次情報で確かめてから書け（REVIEW.md『処方の最小性』の世界の解を採る）")
        ros = c.get("root_or_symptom") or {}
        if ros.get("kind") == "symptom" and len((ros.get("why") or "").strip()) < 10:
            raise Reject(f"{c['unit_key'][:60]}: 症状を塞ぐ修正なのに、なぜ今それで止めるかが無い（根に当てるのが設計作業なら、そう書いて questions に fork を立てろ）")
        # **判定者の how は役に写させない**——役が how を書かなければ判定者の class_query の how を補い、out に書き戻す
        # （process.fixes と R1 には今までと同じ how が残る）。役が書いた how は作り直しとして採る（狭めれば下の柵が remaining を求める）
        jq = judged.get(c["unit_key"]) or {}
        cov = c.get("coverage") or {}
        if not cov.get("how") and jq.get("how"):
            cov = c["coverage"] = {**cov, "how": jq["how"]}
        if not cov.get("how"):
            raise Reject(f"{c['unit_key'][:60]}: 判定者の class_query が無い単位なのに coverage.how（同じ形を全部引ける機械の問い）が無い"
                         "——名指しの 1 site だけを塞いでいないことは母数でしか示せない")
        # **修正の前後の件数は engine が数える。向きは判定者が決める**——修正役が書く total と counts を入力にしていた頃は、
        # 検査される側の申告で柵が外れた（counts を population に書き換えると修正後の件数の拒否が消え、修正後だけ未追跡を
        # 外して数えるので、判定時 2・修正後 1 の数え違いで defects の柵をすり抜けた。2026-09-24 の review-graph 1 周目）。
        # 修正前は判定者が読んだのと同じ固定の版、修正後はそれと同じ世界（未追跡も含め、.gitignore に当たる物は外す）
        counts = jq.get("counts") or cov.get("counts")
        if counts not in ("defects", "population"):
            raise Reject(f"{c['unit_key'][:60]}: 数えるものの向きが決まらない——判定者の class_query が無い単位は coverage.counts（defects / population）を書け")
        # 空語（『なし』『-』…）は理由でない——残した理由の有無を blank で見る（truthiness で見ていた頃は『なし』で柵が外れた）
        remaining = "" if blank(cov.get("remaining"), 10) else cov["remaining"].strip()
        if root is None:
            root = _repo_root() or ""
        total, why = _run_query(b, f"{c['unit_key'][:60]}: coverage（修正前）", cov["how"], root, rev=(b.state.get("inputs") or {}).get("review_rev"))
        if why:
            raise Reject(why)
        closed = len(c.get("closure", {}).get("sites", []) or [])  # 塞いだ数は closure.sites から機械が数える（二度書かせない）
        after, why = _run_query(b, f"{c['unit_key'][:60]}: coverage（修正後）", {**cov["how"], "untracked": True}, root, probe=False)
        if why:
            raise Reject(why)
        # 修正前が 0 件の問い（在るべき物が無い型）は、修正で生まれた数（修正後の件数）まで site を書ける
        cap = total if total else after
        if closed > cap:
            raise Reject(f"{c['unit_key'][:60]}: closure.sites が {closed} 件なのに、engine が how を修正前の版で数えた母数は {total}"
                         f"（修正前が 0 件なら修正後の {after}）——母数を超えて塞げない"
                         "（問いが対象を取りこぼしている）。判定者の how が根の 1 行だけを数えているなら、直す site になる行を全部数える how に作り直せ")
        if closed < cap and not remaining:
            raise Reject(f"{c['unit_key'][:60]}: 母数 {cap} のうち閉鎖を実証した site が {closed} 件で、残りが在るのに remaining（残した理由）が無い"
                         "——残すこと自体は禁じないが、黙って残すのは禁じる")
        zero = b.loop_state.get("engine_zero") or {}
        jt = 0 if zero.get("round") == b.round and c["unit_key"] in (zero.get("keys") or []) else jq.get("total")
        if isinstance(jt, int) and not isinstance(jt, bool) and total < jt and not remaining:
            raise Reject(f"{c['unit_key'][:60]}: 判定者が数えた母数は {jt} なのに、この how は修正前の版で {total} しか数えない（問いを狭めている）"
                         "——狭める理由（問いが対象を取りこぼしていた等）を remaining に書け")
        # **欠陥の形を数える問いなら、全部塞いだ後の件数は 0**
        if counts == "defects" and after and closed >= total and not remaining:
            raise Reject(f"{c['unit_key'][:60]}: 欠陥の形を数える問い（判定者の counts: defects）が、母数 {total} を全部塞いだと言う修正の後も {after} 件を数える"
                         "——塞ぎ損ねた site が在る（向きは判定者が決めるので、修正役が population と書いても外れない）")
        afters.append({"unit_key": c["unit_key"], "how": cov["how"], "counts": counts, "total": total, "closed": closed, "after": after})
    if out["changes"] and st == "clean":
        if not any(s.get("red_seen") for c in out["changes"] for s in c["closure"].get("sites", [])):
            raise Reject("閉鎖の実証で赤を一度も見ていないのに fix_closure=clean——found にして赤を見ていない site を書くか、"
                         "退行を注入して赤を見てから出せ")
    # **修正が新しく書いた指しを、指摘と同じ裏取りに通す**（何を・どの版で・どこまで数えるかは _cite_errors の
    # docstring、採った道と落とした道は docs/feedback/review-loop-remaining-findings.md の『設計の記録: 修正側の裏取り』が正本）。
    # **申告が空でも通す**——`if refs:` で囲っていた頃、いちばん多い周（新しい指しを書かなかった周）は
    # 関数に入らず、読了の記録が前の周の値のまま残った。不変条件は、それが守る経路の上に置く
    errs, reads = _cite_errors(b, nid, out.get("wrote_refs") or [], None, "wrote_refs")
    # 次の周の判定役が読む（graph の reads に loop.wrote_refs_reads）。**拒否には使わない**。**周を刻み、
    # 空の周も必ず書く**——前の周の値が『この周の材料』として読まれないため（p2.diagnose は同じ周の p3.fix より
    # 前に走る）
    b.loop_state["wrote_refs_reads"] = {"round": b.round, "items": reads}
    b.loop_state["coverage_after"] = {"round": b.round, "items": afters}
    if errs:
        # **機械が支える範囲だけを言う。** 以前は「申告を消して通すな」と添えていたが、消した周を見る
        # 機械は無い（引くのは申告された行だけ）——支えない主張は、正直に申告した側にだけ効く
        raise Reject(f"{nid}: 修正が書いた指しが現物で引けない（直してから出し直せ）: " + "; ".join(errs))
    pf = _plan_face_errors(b, out)
    if pf:
        raise Reject(f"{nid}: 修正案の事前審査への応答が揃わない: " + "; ".join(pf))
    links = _md_link_errors(b.record["base"], _repo_root() or "") if b.record.get("base") else []
    if links:
        raise Reject(f"{nid}: 差分が足した Markdown のリンクが指し先に届かない（申告に依らず engine が差分から拾った。直してから出し直せ）: "
                     + "; ".join(links[:10]) + (f" ほか {len(links) - 10} 件" if len(links) > 10 else ""))
    if out.get("rejudge_requested"):
        b.loop_state["rejudge_requested"] = {"round": b.round, "text": out["rejudge_requested"]}


# 差分が足した Markdown のリンク。**申告に頼らず差分から機械が拾う**——修正側の裏取り（wrote_refs）は申告された指しだけを
# 引くので、申告を空にすれば 1 件も引かれない。文書の中の参照はリンクの形で書かせてリンク検査にかけるのが定番
# （lychee の --include-fragments は Markdown の見出しのアンカーまで確かめる。https://github.com/lycheeverse/lychee）。
# ここは外部の道具を足さず、相対リンクの指し先のファイルと見出しだけを標準ライブラリで引く。**拾う形は CommonMark の部分集合**:
# インラインの指し先（山括弧つき <a b.md> を含む）だけ。拾わない形——参照形式（[文字][名] と [名]: 指し先。リポジトリに 0 件で、拾う入口を
# 足すほど誤検知の面が増えた）・指し先の中の括弧（f(1).md）——は黙って通る。
# 見出し（#…）を確かめるのは指し先が .md のときだけ（ほかの形式のアンカーは形式ごとに規則が違う）
MD_LINK = re.compile(r"(?<!!)\[[^\]\n]*\]\((?:<([^>\n]+)>|([^()\s<]+))(?:\s+\"[^\"]*\")?\)")
MD_FENCE = re.compile(r"^\s{0,3}(```|~~~)")



def _md_lines(text):
    """(行番号, 行) を、コードブロック（``` / ~~~ の囲い）の外の行だけ返す"""
    fence = False
    for i, line in enumerate(text.splitlines(), 1):
        if MD_FENCE.match(line):
            fence = not fence
        elif not fence:
            yield i, line


def _md_slugs(text):
    """見出しのアンカー（GitHub の書き方: 小文字にし、語の文字・- ・空白以外を落とし、空白を - に。重複は -1, -2 …）"""
    seen, out = {}, set()
    for _, line in _md_lines(text):
        m = re.match(r"^\s{0,3}#{1,6}\s+(.*?)\s*#*\s*$", line)
        if not m:
            continue
        h = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", m.group(1).strip())   # 見出しの中のリンクは文字だけが残る
        s = re.sub(r"[^\w\- ]", "", h.lower()).replace(" ", "-")
        n = seen.get(s, 0)
        seen[s] = n + 1
        out.add(s if n == 0 else f"{s}-{n}")
    return out


def _added_md_links(base, root):
    """BASE から今の作業ツリーまでに足された .md の行（コードブロックとコードスパンの外）にある相対リンク ——
    [(ファイル, 行, 指し先)]。None は差分を引けなかった。git add -N していない未追跡の .md（.gitignore に当たらない物）は
    git diff に出ないので、中身の全行を足された行として数える"""
    # core.quotePath を切る——既定のままだと日本語のファイル名が引用符つきの 8 進表記になり、+++ b/ の行で拾えず黙って飛ばす。
    # :(top) で、サブディレクトリから回した run でもリポジトリ全体の .md を見る
    # 接頭辞は明示する（利用者の diff.noprefix・diff.mnemonicPrefix で +++ b/ が変わると、1 件も拾わずに通った）。
    # ls-files は --full-name でルート相対に（git の cwd はサブディレクトリでありうる）
    d = git("-c", "core.quotePath=false", "diff", "-U0", "--no-color", "--no-ext-diff", "--src-prefix=a/", "--dst-prefix=b/",
            base, "--", ":(top)*.md")
    new = git("-c", "core.quotePath=false", "ls-files", "--full-name", "--others", "--exclude-standard", "--", ":(top)*.md")
    if d is None or new is None:
        return None
    added, cur = {}, None
    for rel in new.splitlines():
        if rel.strip():
            added[rel] = None   # 全行
    for line in d.splitlines():
        if line.startswith("+++ "):
            # 空白を含む名前には git が行末にタブを付ける
            cur = line[6:].rstrip("\t") if line.startswith("+++ b/") else None
        elif line.startswith("@@") and cur:
            m = re.search(r"\+(\d+)(?:,(\d+))?", line)
            start, n = int(m.group(1)), int(m.group(2) or 1)
            if added.get(cur, set()) is not None:
                added.setdefault(cur, set()).update(range(start, start + n))
    links = []   # (ファイル, 行, 指し先, 問題)——問題が在る行は指し先を引かずにその文で落とす
    for rel, lines in sorted(added.items()):
        data, why = read_capped(str(pathlib.Path(root) / rel), READ_CAP)
        if data is None:
            links.append((rel, 0, None, f"を読めないのでリンクを確かめられない（{why}）"))   # 読めない文書を黙って飛ばさない
            continue
        body = list(_md_lines(data.decode("utf-8", "replace")))
        for i, line in body:
            if lines is not None and i not in lines:
                continue
            bare = re.sub(r"`+[^`]*`+", "", line)
            tgts = [a or b for a, b in MD_LINK.findall(bare)]
            for tgt in tgts:
                if not re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*:", tgt):   # URL の scheme（http: mailto: …）は引かない
                    links.append((rel, i, tgt, None))
    return links


def _walk_as_written(start, rel):
    """start から rel を 1 部品ずつたどる。**symlink の部品だけ実体へ解き、ほかの部品は書かれた綴りのまま残す**。

    丸ごと resolve していたとき、Windows では実在するファイルの綴りがディスク上の大小に直り（Python 公式文書の
    os.path.realpath: "The returned path uses the case reported by the operating system"）、綴りの大小違いのリンクが
    版の一覧に当たって通った（macOS・Linux は直さないので赤）。字面だけで畳むと、symlink のディレクトリを経由する
    リンクを通さなくなる（今ある能力の後退。人の決定 2026-09-25: 狭めずに直す）。`..` は symlink を解いた後の
    実体の親をたどるので、resolve と同じ意味になる"""
    cur = start
    for part in pathlib.PurePosixPath(rel).parts:
        if part == "..":
            cur = cur.parent
        elif part not in ("", ".", "/"):
            cur = cur / part
            if cur.is_symlink():
                cur = cur.resolve()
    return cur


def _md_link_errors(base, root):
    """足されたリンクが、指し先のファイル（リポジトリの中）と見出しに届くか。届かない件の文の一覧"""
    from urllib.parse import unquote
    links = _added_md_links(base, root)
    if links is None:
        return ["差分を引けないので、足された Markdown のリンクを確かめられない"]
    rootp, errs, slugs = pathlib.Path(root).resolve(), [], {}

    def dest_of(rel, tgt):
        path = tgt.partition("#")[0]
        # / で始まるリンクはリポジトリのルート基準（GitHub の文書の相対リンクの規則）
        base_dir = rootp if path.startswith("/") else (rootp / rel).parent
        return _walk_as_written(base_dir, unquote(path.lstrip("/"))) if path else _walk_as_written(rootp, rel)
    inside = {dest_of(r, g).relative_to(rootp).as_posix() for r, _, g, u in links
              if not u and rootp in dest_of(r, g).parents}
    # ディレクトリは、版に入るファイルを 1 本以上含むこと（FS の is_dir だけだと、空のディレクトリや無視対象だけの
    # ディレクトリへのリンクが通った）
    dirs = {x for x in inside if (rootp / x).is_dir()}
    with_files = {x for x in dirs if (git("ls-files", "--full-name", "--cached", "--others", "--exclude-standard", "--",
                                          f":(top,literal){x}") or "").strip()}
    # **在るかは版の世界で見る**（_in_version——ls-files で綴りまで一致・.gitignore に当たる物は入らない）。FS の exists は、
    # 大文字小文字を区別しないファイルシステムの綴り違いと、他の人の手元に無い .gitignore の対象を通した
    versioned = _in_version(sorted(inside)) if inside else {}
    if versioned is None:
        return ["git が動かないので、足された Markdown のリンクの指し先を確かめられない"]
    for rel, line, tgt, problem in links:
        if problem:
            errs.append(f"{rel}{':' + str(line) if line else ''} {problem}")
            continue
        frag = tgt.partition("#")[2]
        dest = dest_of(rel, tgt)
        where = f"{rel}:{line} の ({tgt[:60]})"
        if dest != rootp and rootp not in dest.parents:
            errs.append(f"{where} がリポジトリの外を指す")
        # ファイルは版に在り、かつ作業ツリーにも在ること（index に残るだけの消したファイルを通さない——_in_version の前提）
        elif not ((dest.relative_to(rootp).as_posix() in with_files) if dest.is_dir() and dest != rootp else
                  (dest != rootp and dest.is_file() and dest.relative_to(rootp).as_posix() in versioned)):
            errs.append(f"{where} の指し先 {dest.relative_to(rootp) if rootp in dest.parents else dest} が版に無い（無いか、綴りが違うか、.gitignore に当たる）")
        elif frag and dest.suffix == ".md":
            if dest not in slugs:
                data, _ = read_capped(str(dest), READ_CAP)
                slugs[dest] = _md_slugs(data.decode("utf-8", "replace")) if data is not None else set()
            if unquote(frag).lower() not in slugs[dest]:
                errs.append(f"{where} の見出し #{frag[:40]} が {dest.relative_to(rootp)} に無い")
    return errs


def main_path_observed(b, nid, out, item):
    """主経路の観測: 見たと言う状態（found / clean）は、観測した値（observed）を 1 つ以上持つ。本文に『未観測』と書いたまま
    状態を『異常なし』にした返答が、周の最後の検証まで見つからなかった（実走の申し送り 2026-09-24）——文の言い回しでなく、
    観測の欄の有無で見る。動かせなかったなら awaiting_human か not_run"""
    st = (out.get("material") or {}).get("status")
    # 空白だけの行は型（observed[].path / value の minLength。前後の空白を除いて測る）が落とすので、ここは行の有無だけ見る
    if st in validator_module(b).OBSERVED_STATUS and not out.get("observed"):
        raise Reject(f"{nid}: status={st} なのに観測した値（observed）が 1 つも無い——動かして観測した経路と値を observed に書け。"
                     "動かせなかったなら awaiting_human（何を待つか）か not_run（なぜ飛ばしたか）")


def external_rankings(b, nid, out, item):
    """外部標準照合の順位の行: 差分が乗る選択肢（diff_at）は ranked のどれかで、最上位でないなら上位を採れない理由が要る。
    特徴の一致だけで『定番と同型』と判定した形（実測 2026-09-24: 3 周続けて clean、実際は下位の順位）を型で塞ぐ"""
    errs = []
    if not out.get("rankings") and blank(out.get("rankings_none"), 10):
        errs.append("rankings が空なのに rankings_none（順位を付けられる一般化した問題が無い理由）が無い——空の順位で clean を名乗らせない")
    for i, r in enumerate(out.get("rankings") or []):
        if r["diff_at"] not in r["ranked"]:
            errs.append(f"rankings[{i}] の diff_at '{r['diff_at'][:40]}' が ranked に無い——一次情報が推す選択肢のどれに乗るかを、ranked の綴りのまま書け")
        elif r["diff_at"] != r["ranked"][0] and blank(r.get("why_not_higher"), 10):
            errs.append(f"rankings[{i}]: 差分は最上位（{r['ranked'][0][:40]}）でなく '{r['diff_at'][:40]}' に乗るのに、上位を採れない理由（why_not_higher）が無い")
    if errs:
        raise Reject(f"{nid}: " + "; ".join(errs))


def r2_design(b, nid, out, item):
    if not out["question_stands"]:
        b.record["reviews"]["R2"] = {"status": "premise-invalid", "reason": out.get("premise_invalid_reason") or out["reason"]}


def r4_inventory(b, nid, out, item):
    inv = out.get("capability_inventory", {})
    if inv.get("fired") and "lost" not in inv:
        raise Reject("R4: BASE 能力インベントリが発火する差分なのに『消えた能力』の明示返答（lost）が無い")


def cold_check_note(b, nid, out, item):
    """初見検査の結果を report の節に渡す**注記**——門ではない。cold-reader は report.human_items の本文を読み、その後の
    report の節が詰まりを直す設計（graph の deps: human_items → cold_check → report）なので、非 pass をここで Reject
    すると正直な判定を拒んで直す道が無くなる。直したかは機械では見ない（writer の申告）。verdict と stops は
    process.cold_check に残し、報告と人が見られるようにする（以前は notes にしか無かった）。"""
    b.loop_state["cold_check"] = {"round": b.round, "verdict": out["verdict"], "stops": len(out.get("stops", [])),
                                  "guessed": len(out.get("guessed", []) or []), "decidable": out.get("decidable")}
    if out["verdict"] != "pass":
        return f"初見検査で詰まりがある（{len(out.get('stops', []))} 箇所）。report の節で直してから出す（直したかは機械では見ない）"


def measured_needs_output(b, nid, out, item):
    """kind=実測 の制約は、実行したコマンドと出力（measured_output）を持て。

    『実測』の札だけが検算なしで信頼値に昇格し、誤った事実がゼロベースで疑う役に所与として渡る
    （実測 2026-09-12: 『CI の定義はリポジトリに無い』が実測として凍結され、R2 の独立設計がそれを前提に書いた。
    .github/workflows/test.yml は実在する）。再現の形を持たないものは仮説へ落とさせる。
    """
    bad = [c["text"][:60] for c in out.get("constraints", []) if c.get("kind") == "実測" and not (c.get("measured_output") or "").strip()]
    if bad:
        raise Reject(f"{nid}: kind=実測 なのに measured_output（実行したコマンドと出力）が無い制約がある: {bad}"
                     "——コマンドと出力を示せないものは kind=仮説 に落とせ")


def gate_arms_all_red(b, nid, out, item):
    """赤を見ていない腕が 1 つでも在れば clean を名乗らせない（赤は覆いの証拠にならない、の裏側）。

    柵の実効性を確かめる節そのものが自己申告で緑を名乗れる形だった（実測: 26 腕中 24 腕しか赤を見て
    いないのに status=clean で、残り 2 腕は note にしか残らなかった）。
    """
    arms = out.get("arms", [])
    st = out.get("material", {}).get("status")
    # 腕 0 行は『撃てた腕が無い』回だけ——見たと言う状態（found / clean）を 0 行で名乗らせない。型の minItems で縛っていた頃は、
    # 実行器が正直に返す not_run（撃てた腕 0 本）まで型で落ちた
    if not arms and st in validator_module(b).OBSERVED_STATUS:
        raise Reject(f"{nid}: status={st} なのに腕が 0 行——撃った腕を行にするか、撃てた腕が無いなら not_run（理由つき）で書け")
    # applies_cond が真で走った節の not_applicable は check_record の表（status × 機械の事実）が拒む——ここには写さない
    unred = [a["arm"] for a in arms if not a.get("red_confirmed")]
    nocontrol = [a["arm"] for a in arms if not a.get("control_green")]
    # **赤が出たことは、その赤が守りたい行から出た証拠にならない。** 腕が守る行を一度も通らないまま緑で
    # 素通りする形が実測で出た（2026-09-13: 持ち越しの可否の柵に退行を注入しても検査は緑のままで、その分岐が
    # 書く理由文字列を一意の印に差し替えても記録に印が現れなかった＝筋書きがその行を通っていない）。
    # 赤は「柵が無ければ落ちる」ことしか言わず、「この腕がその柵を通った」ことは別に測る必要がある。
    # 測り方は今周の gate_efficacy が実際に使った形をそのまま欄にする——分岐が書く値を一意の印に替え、
    # その印が出力か記録に現れることを見る（`hit_evidence` に何をどう確かめたか）。
    nohit = [a["arm"] for a in arms if blank(a.get("hit_evidence"), 10)]
    # 未赤の腕が在るのに『見て無かった』側（clean / carried_over / not_applicable …）を名乗る返答は拒む——clean だけ
    # 見ていたとき carried_over で腕ゼロのまま通った（実測 2026-09-13）。**収束を止める状態（表の blocks）は通す**——
    # 人の起動待ちの腕（問いの台帳に kind=awaiting で origin が gate_efficacy の行が在る）では、検証器が素材を
    # awaiting_human にしろと求めるので、ここで found を強いると done と検証器が逆を言い、patch が毎周要った
    # （実走の申し送り: 7 周連続）
    # 通すのは人の起動待ちだけ（名乗った理由どおり）。not_run も収束を止める状態だが、赤を見ていない腕を抱えた返答に
    # 是正の文（found にして腕を書け）を届ける
    if st != "found" and _unproven(arms) and st != "awaiting_human":
        raise Reject(f"{nid}: 赤を見ていない腕 {unred} / 壊していない写しで緑を確かめていない腕 {nocontrol} / "
                     f"守る行を通ったことを測っていない腕 {nohit} が在るのに status=clean"
                     "——未達は found（count と detail に腕を書く）、人の起動待ちなら awaiting_human（reason に何を待つか）")
    # **status に依らず、腕ごとに当てる**: 赤も control 緑も見た腕が、守る行を通ったことを測っていないなら、
    # その腕は「覆いの証拠」として数えられない。他の腕が未赤でも外さない——外していた頃は、撃てない腕が 1 本
    # 在るだけで 13 腕の印の欠けが素通りした（台本の『撃てない腕が在っても…腕ごとに拒む』の腕）
    proven = [a["arm"] for a in arms if a.get("red_confirmed") and a.get("control_green") and blank(a.get("hit_evidence"), 10)]
    if proven:
        nohit = proven
        raise Reject(f"{nid}: 腕 {nohit} は赤も control の緑も見ているが、**その腕が守る行を通ったこと**を測っていない"
                     "（hit_evidence）——赤は柵の不在の検知であって、この腕がその柵に当たった証拠にならない。"
                     "分岐が書く値を一意の印に替え、その印が出力か記録に現れることを確かめて hit_evidence に書け")


def _keys_once(rows, label):
    """行の key が重複しないか（重複の文の一覧）"""
    seen, errs = set(), []
    for i, r in enumerate(rows):
        if r["key"] in seen:
            errs.append(f"{label}[{i}] の key が重複: {r['key'][:60]}")
        seen.add(r["key"])
    return errs


def fix_plan_covers_units(b, nid, out, item):
    """修正案は今の周に直す単位を全部、どれか 1 つの案に入れる。**書き落とした単位は事前審査に届かない**"""
    V = validator_module(b)
    want, opened = _owed_units(b), {u["key"] for u in b.record["units"] if V.is_open(u)}
    got = [k for p in out["plan"] for k in p["unit_keys"]]
    errs = []
    unknown = sorted(set(got) - opened)   # 免除の単位（fork の出どころ）は入れても入れなくてもよい
    if unknown:
        errs.append(f"今の周に直す単位に無い key {[k[:40] for k in unknown[:3]]}（写さずに、貼られた単位の no で指せ）")
    missing = sorted(want - set(got))
    if missing:
        errs.append(f"どの案にも入っていない単位 {[k[:40] for k in missing[:3]]}——直す義務の単位は全部どれかの案に入れる")
    dup = sorted({k for k in got if got.count(k) > 1})
    if dup:
        errs.append(f"2 つの案に入った単位 {[k[:40] for k in dup[:3]]}——1 単位は 1 案")
    if errs:
        raise Reject(f"{nid}: " + "; ".join(errs))


def plan_review_output(b, nid, out, item):
    """事前審査の穴は案の単位を指し、key は一意。穴も別案も無いなら、何を確かめて無いと言えるか（faces_none）を書く"""
    planned = {k for p in (b.output_of_round("p2.fix_plan", b.round) or {}).get("plan") or [] for k in p["unit_keys"]}
    rows = (out.get("faces") or []) + (out.get("shrink") or [])
    errs = _keys_once(rows, "faces・shrink")
    for i, r in enumerate(rows):
        stray = [k for k in r["unit_keys"] if k not in planned]
        if stray:
            errs.append(f"{r['key'][:40]}: unit_keys {[k[:40] for k in stray]} は修正案に無い")
    if not rows and blank(out.get("faces_none"), 20):
        errs.append("穴も別案も挙げないなら faces_none に何を確かめて無いと言えるかを書け")
    # 入口の穴は『足さずに閉じる形』を併記する——入口を足せと言う審査は、足した入口が次の周の指摘の種になる
    # （実測 2026-09-24: 3 周目の事前審査に従って参照形式の入口を足したら、4 周目に『入口を足し続けている』と挙がった）
    errs += [f"faces の '{f['key'][:40]}'（entrance）に no_add（柵や入口を足さずに閉じる形。無理なら無理な理由）が無い"
             for f in out.get("faces") or [] if f["kind"] == "entrance" and blank(f.get("no_add"), 20)]
    if errs:
        raise Reject(f"{nid}: " + "; ".join(errs))


def _plan_face_errors(b, out):
    """修正は事前審査の穴と別案に key ごとに 1 度だけ答える（absorbed＝取り込んだ／declared＝残す理由）"""
    rv = b.output_of_round("p2.plan_review", b.round)
    if not rv:
        return []
    asked = {r["key"] for r in (rv.get("faces") or []) + (rv.get("shrink") or [])}
    rows = out.get("plan_faces") or []
    errs = _keys_once(rows, "plan_faces")
    errs += [f"plan_faces の key '{r['key'][:40]}' は事前審査に無い" for r in rows if r["key"] not in asked]
    answered = {r["key"] for r in rows}
    errs += [f"事前審査の '{k[:40]}' に応答が無い——absorbed（どう取り込んだか）か declared（残す理由）で答えろ"
             for k in sorted(asked - answered)]
    return errs


def _closed_keys(out, n):
    """『塞いだ』と言われた穴の key を、その回の返答（1 回目は p3.fix、2 回目は 1 回目の手直し）から引く式の正本"""
    rows, (field, word) = (out or {}), (("plan_faces", "absorbed") if n == 1 else ("handled", "fixed"))
    return {r["key"] for r in rows.get(field) or [] if r["handled"] == word}


def _claimed_closed(b, n):
    """n 回目の差分レビューが検算する『塞いだ』と言われた穴の key——1 回目は修正が absorbed と答えた事前審査の穴、2 回目は手直しが fixed と答えた穴"""
    return _closed_keys(b.output_of_round("p3.fix" if n == 1 else DELTA_PASSES[n - 1].fix, b.round), n)


def delta_review_output(b, nid, out, item):
    """修正差分のレビューの穴は、この周の修正が触ったファイルの中に在る字列を指す。無いなら faces_none。
    『塞いだ』と言われた穴は 1 件ずつ検算し（checks）、塞がっていないもの（closed=false）は手直しの節が同じ key で答える（_delta_owed）"""
    n = DELTA_PASS_OF[nid]
    d = _delta_of(b, n) or {}
    files, root = set(d.get("files") or []), pathlib.Path(_repo_root() or ".")
    faces = out.get("faces") or []
    errs = _keys_once(faces, "faces")
    for i, f in enumerate(faces):
        if f["kind"] in HUMAN_FACE_KINDS:
            # 手直しの義務に入ると、人より先に修正役が残すか戻すかを決める
            errs.append(f"faces[{i}] の kind '{f['kind']}' は事前審査だけの語——修正の後の後退・方針とのぶつかりは R4 と関所（r4.human_gate）が人に聞く")
            continue
        if f["kind"] in PLAN_ONLY_FACE_KINDS:
            errs.append(f"faces[{i}] の kind '{f['kind']}' は事前審査だけの語——判定者の先行例はこの節に渡っていない")
            continue
        if f["where"] not in files:
            errs.append(f"faces[{i}] の where '{f['where'][:60]}' はこの周の修正が触ったファイルでない（{sorted(files)[:5]}）")
            continue
        data, _ = read_capped(str(root / f["where"]), READ_CAP)
        if data is None or f["cite"].encode("utf-8") not in data:
            errs.append(f"faces[{i}] の cite '{f['cite'][:40]}' が {f['where']} の今の姿に無い——在る字列を写せ")
    if not faces and blank(out.get("faces_none"), 20):
        errs.append("穴を挙げないなら faces_none に何を読んで無いと言えるかを書け")
    claimed, checks = _claimed_closed(b, n), out.get("checks") or []
    errs += _keys_once(checks, "checks")
    errs += [f"checks の key '{r['key'][:40]}' は塞いだと言われた穴に無い" for r in checks if r["key"] not in claimed]
    errs += [f"塞いだと言われた穴 '{k[:40]}' に検算が無い——差分で塞がったか（closed）を 1 件ずつ書け"
             for k in sorted(claimed - {r["key"] for r in checks})]
    if errs:
        raise Reject(f"{nid}: " + "; ".join(errs))


def delta_fix_output(b, nid, out, item):
    """修正差分のレビューが挙げた穴に key ごとに 1 度だけ答える。fixed は触ったファイルを書く"""
    asked = _delta_owed(b, DELTA_PASS_OF[nid])   # 差分レビューの穴と塞がっていない検算（変異の見逃しは並行の線が答える）
    rows = out["handled"]
    errs = _keys_once(rows, "handled")
    errs += [f"handled の key '{r['key'][:40]}' は修正差分のレビューに無い" for r in rows if r["key"] not in asked]
    errs += [f"穴 '{k[:40]}' に応答が無い" for k in sorted(asked - {r["key"] for r in rows})]
    errs += [f"handled '{r['key'][:40]}' は fixed なのに files が空" for r in rows if r["handled"] == "fixed" and not r.get("files")]
    if errs:
        raise Reject(f"{nid}: " + "; ".join(errs))


def rejudge_output(b, nid, out, item):
    """擦り合わせの返答: **新しい事実を自分で確かめたこと**を要求し、往復の回数を数える。

    依頼者の指定の条件 1（反論は新しい事実を伴うときだけ通す）と 3（判定を確定する権限は移らない）を機械で持つ。
    確かめた結果を書かずに採る／退けるのは、回す側の異議をそのまま飲む／握り潰すのと同じで、どちらも
    「判定を都合よく使うな」に反する。回数は loop_state が持ち、cond（rejudge_open / rejudge_exhausted）が読む。
    """
    fact = (out.get("new_facts") or "").strip()
    if blank(fact, 20):
        raise Reject(f"{nid}: new_facts が空同然——回す側が出した事実を**自分で確かめた結果**を書け"
                     "（確かめずに採る／退けるのは、どちらも判定を都合よく使うことになる）")
    # 再審は units だけを書く（questions は書かない）ので、当てられるのは units だけで決まる defer の再浮上だけ。拒否文が defer の
    # 理由を名指すので、台帳を読まない再審の役にも直す手が在る
    ledger = _defer_ledger(b)
    errs = validator_module(b).reopened_without_evidence(out.get("units") or [], ledger) if ledger else []
    if errs:
        raise Reject(f"{nid}: " + "; ".join(errs))
    ls = b.loop_state
    prev = ls.get("rejudge_rounds") or {}
    if not isinstance(prev, dict):
        prev = {"round": b.round, "n": int(prev)}
    # 周が変わったら数え直す——回数は「その周の往復」なので、周をまたいで積むと上限が run 全体に掛かる
    ls["rejudge_rounds"] = {"round": b.round, "n": (int(prev.get("n") or 0) if prev.get("round") == b.round else 0) + 1}
    # 決着したら異議を降ろす。決着しなければ次の往復（上限を超えれば第三の目）へ
    if out.get("verdict") in ("採る", "退ける"):
        ls.pop("rejudge_requested", None)


def local_review_covers_lenses(b, nid, out, item):
    """宣言したレンズ 1 本につき findings の行を 1 本、**例外なく**要求する（台帳の (a)+(c)、2026-09-16 の裁定）。

    直したのは「未起動が所見ゼロと同じ形で受理される」面。実測 2026-09-15: 架空のレンズ名も findings 空も
    どちらも通り、3 周にわたって型設計のレンズが起動されないまま記録のどこにも赤が出なかった。
    行を必須にすると、起こさなかったことは沈黙では通らず `failed` に書くしかなくなる。

    **この検査は嘘を捕まえない**——起こしていないのに items を書けば通る。変わるのは、未起動を
    「黙って」通せた形が「明示の虚偽」を経由しないと通せない形になるところまで。

    条件付きのレンズ（required: false で applies_cond を持つ要素）も行は必須にする。条件外のとき行ごと省ける
    設計にすると、まさに直した穴がそのまま戻る——起こさなかった周は `failed` に理由を書いて表す。**条件が真の周に
    起こさなかった行（invoked が true でない）は拒む**——値は engine が節を出す時点に評価して instance の skills に
    置いた applies を読む（無ければ当てる側に倒す）。呼び出しが落ちて人に上げる行（material が awaiting_human）は通す。

    照合の両側は同じ文字列: engine が `{{node.skills}}` で正典をそのまま役へ渡し、ここは同じ配列の
    `skill` を読む。綴りの正規化という段は存在しない（在れば、その規則自体が誰も決めていない未定義物になる）。
    """
    inst = next((i for i in reversed(list(b.rd["instances"].values())) if i.get("node") == nid and i.get("status") != "done"), None)
    skills = (inst or {}).get("skills") or b.graph["nodes"][nid].get("skills") or []
    if not skills:
        # **空なら落とす（fail-closed）。** 空リストだと 1 周も回らず全件合格になり、非空であることの
        # 保証は別ファイルの graphcheck が別の欄（run_by == skill）を根拠に持っていた。engine は
        # かつて graphcheck を一度も呼ばず、`init --graph <任意のパス>` は静的検査を素通りした。
        # 今は init が同じ検査を呼ぶ（engine/commands.py の check_graph）——入口で 1 度見たものを
        # 実行時にもう 1 度見るのは重複ではない: graph は init の後で書き換えられる（実測: 台本 drive_graph）
        raise Reject(f"{nid} の skills が空——数える対象が無い柵は全件合格になる。graph に宣言を書け")
    declared = [e["skill"] for e in skills]
    rows = out.get("findings") or []
    seen, errs = {}, []
    for i, row in enumerate(rows):
        name = row.get("skill", "")
        if name in seen:
            errs.append(f"findings に同じ skill の行が 2 本: {name}（1 本のレンズは 1 行にまとめろ）")
        seen[name] = row
        if name not in declared:
            errs.append(f"findings[{i}] の skill '{name}' は宣言に無い——正本は graph の skills（{declared}）。"
                        "名指しを増やしたいなら graph を直せ（役が勝手に増やした名前は数えられない）")
    for name in declared:
        row = seen.get(name)
        if row is None:
            errs.append(f"宣言した '{name}' の行が findings に無い——起こしたなら items を、起こしていない・"
                        "非該当なら items を空にして failed に理由を書け。**行を省くな**（省けるなら、"
                        "未起動が所見ゼロと同じ形で通っていた元の穴に戻る）")
        elif not row.get("items") and not (row.get("failed") or "").strip():
            errs.append(f"'{name}' の行が items も failed も持たない——『起こして 0 件』なら failed に"
                        "『起こしたが所見なし』と何を見たかを書け。空の行は『起こしていない』と区別できない")
    awaiting = (out.get("material") or {}).get("status") == "awaiting_human"
    for e in skills:
        row = seen.get(e["skill"])
        if row is None or "applies_cond" not in e or not e.get("applies", True) or awaiting:
            continue
        if row.get("invoked") is not True:
            errs.append(f"'{e['skill']}' は条件 {e['applies_cond']} が真の周（{e.get('applies_why', '評価の値が無いので当てる側に倒した')}）"
                        "なのに invoked が true でない——起こして invoked: true を書け。呼び出しが落ちたなら failed に理由を書き、"
                        "material を awaiting_human にせよ")
    if errs:
        raise Reject("宣言したレンズと findings の行が合わない:\n" + "\n".join("  - " + e for e in errs))


def purpose_findings_cited(b, nid, out, item):
    """**指摘は、作業ツリーで引ける根拠を連れて来る**（境界で検査する。信じて後で棄却しない）。

    目的の監査の指摘が素の文字列だったとき、**リポジトリに 1 件も無い字列を根拠にした指摘が 5 周
    再燃した**——毎周ちがう判定者が自分で grep して 0 件を確かめ、棄却し、次の周にまた同じ指摘が出た
    （実測 r3〜r7: document_tail と TAIL_MIN はどちらも 0 件）。棄却は判定者の手間としてだけ残り、
    出す側には何も返らないので止まらない。ここで数え直して、合わない指摘を受け取らない。

    数えるのは engine ではなく git（作業ツリーの現物が正本）。git が使えない環境では**申告を信じず、
    確かめられなかったことを理由に拒む**——「検査できないから通す」は、この差分が繰り返し塞いだ形である。
    """
    rows = out.get("findings") or []
    # **根拠 0 件の『狭めている』を通さない。** findings が空だと 0 回ループして合格していた——
    # 裏取りの柵を入れた意味が、いちばん効くべき場合（根拠を書かずに判定だけ出す回）で消える。
    if out.get("verdict") == "狭めている" and not rows:
        raise Reject(f"{nid}: 『狭めている』のに findings が空——**判定には作業ツリーで引ける根拠を 1 件以上付けろ**"
                     "（欠落を指摘したいなら、欠けている場所の周辺に実在する字列を cite にして、"
                     "そこに在るべき物が無いことを text に書く）")
    errs, _ = _cite_errors(b, nid, rows, b.loop_state.get("reviewed_revision"), "findings")
    if errs:
        raise Reject(f"{nid}: 指摘の根拠が作業ツリーで裏取りできない: " + "; ".join(errs))


def _repo_root():
    return repo_root(git)   # 本体は engine の 1 本。rules に差し込まれた git を渡す


# 1 周に数える問いを走らせてよい回数と時間の上限。1 回ごとの上限（60 秒・出力 4MB）だけでは、差し戻しのたびに全単位を
# 走らせ直す周の総量に天井が無い（GitHub Actions の jobs.<id>.timeout-minutes が段ごとでなくジョブ全体に天井を置くのと同じ形）。
# 値は実走の最大（1 周の単位 20 前後 × 差し戻し 6 回 ＋ 修正 20 前後）の倍に置く
COUNT_BUDGET = {"calls": 300, "seconds": 900}


def _run_query(b, where, how, root, rev=None, probe=True):
    """役が書いた問い（how）を engine が走らせる ——（件数, 拒否文）。走らせられなければ件数は None。

    argv を組む形と受け取らない形は engine/util.py の count_argv が正本。走らせる場所はリポジトリのルート（役はルート相対の
    パスで書く）。
    **件数は engine が書き、役の数とは突き合わせない。** 以前は役の total と違えば拒み、拒否文が走らせた件数を教えて
    いたので、突合は検算でなく写しの往復だった——how を書く判定役は shell を持たず、件数を推測で書くしかない
    （2026-09-23。台本 test_rejections の FRESH の腕）。拒むのは走らせられない問いだけ
    """
    if not root:
        return None, f"{where}: how を走らせる場所（リポジトリのルート）を引けない——確かめられない件数は受け取らない"
    import json as _json
    import time
    # **固定した版で数えた結果は盤面に取っておく**——版は動かないので同じ問いの答えも動かない。差し戻しのたびの数え直しと、
    # 同じ周の p2.diagnose と p2.history が同じ問いを数える分が、上限を食わなくなる
    cf, ck = b.dir / "count-cache.json", _json.dumps([how, rev], ensure_ascii=False, sort_keys=True)
    cache = (read_json(cf) if cf.is_file() else {}) if rev else {}
    if ck in cache:
        got, why = cache[ck]
        return (got, "") if got is not None else (None, f"{where}: how を機械が走らせられない（{why}）")
    # **量は盤面の隣のファイルに刻む**——差し戻し（Reject）の done は盤面を保存しないので、loop_state に置くと
    # いちばん数えたい出し直しが 1 回も数えられない
    bf = b.dir / "count-budget.json"
    bud = read_json(bf) if bf.is_file() else {}
    if bud.get("round") != b.round:
        bud = {"round": b.round, "calls": 0, "seconds": 0.0}
    if bud["calls"] >= COUNT_BUDGET["calls"] or bud["seconds"] >= COUNT_BUDGET["seconds"]:
        return None, (f"{where}: この周に数える問いを走らせた量が上限（{COUNT_BUDGET['calls']} 回か {COUNT_BUDGET['seconds']} 秒）に達した"
                      f"（{bud['calls']} 回・{bud['seconds']:.0f} 秒）——同じ返答を出し直し続けていないか。続けるなら盤面の count-budget.json を消す")
    t0 = time.monotonic()
    got, why = run_count(how, root, rev=rev, probe=probe)
    bud["calls"] += 1
    bud["seconds"] += time.monotonic() - t0
    write_json(bf, bud)
    if rev and got is not None:   # 取っておくのは数えられた答えだけ——時間切れ・標準エラーは一時的でありうる
        cache[ck] = [got, why]
        write_json(cf, cache)
    if got is None:
        return None, f"{where}: how を機械が走らせられない（{why}）"
    return got, ""


def _r2_refire(rnd, fix, ratio, lines, ls):
    """R2（独立設計との突き合わせ）をこの周に回し直すか。"""
    by_round = ls.setdefault("diff_lines_by_round", {})
    by_round[str(rnd)] = lines
    grew, shrank = _lines_moved(ratio, lines, by_round.get(str(rnd - 1)))
    forced = bool(ls.pop("r2_refire_forced", False))  # 先に消費する——式の最右に置くと短絡で pop に届かず、変化の無い次の周まで旗が効いた
    mech, drift = bool(fix.get("mechanism_changed")), bool(fix.get("premise_drift"))
    return rnd == 1 or mech or drift or grew or shrank or forced


def _lines_moved(ratio, lines, prev_lines):
    """差分の行数が大きく動いたか ——（増えた, 減った）。R2（独立設計との突き合わせ）を回し直す条件の 2 項。

    **増えた**は R1 を最後に回した周の行数の 1.5 倍を超えたとき。**減った**は前の周の 2/3 以下になったとき——
    処方の向きが『足す』から『消す・畳む』へ変わった周は、設計が組み替わっているのに行数は減るので、増える向きの
    項だけでは R2 を回し直さず前の判定を流用していた（実走の申し送り: 10 周 run の 10 周目）。減る向きを直前の周と
    比べるのは、1 周目と比べると、足してから畳んだ周が 1 周目より多いまま残り、転換が見えないため。
    """
    grew = ratio is not None and ratio > 1.5
    shrank = bool(prev_lines) and lines <= prev_lines * 2 / 3
    return grew, shrank


def _grep_count(cite, rev):
    """固めた版に対する `git grep -F -cI`（字面として数える）。並びは `grep [旗] -e <語> <版> -- :(top)`。指摘側だけが呼ぶ。

    **-F（字面）が要る**——既定の grep は基本正規表現として解釈するので、ドット・角括弧を含む現物のコード片は
    別の物を数える（現物に在る引用が当たらず、現物に無い字列が偶然当たる、という両方向の壊れ方をした。実測 r8）。
    **-e で語だと明示する**——`-- <語>` の位置に置くと git は版を検索語・語を path として読み、0 件が返る
    （実測 2026-09-21: 台本が全件赤になった）。

    **ルート基準にするのは、ルート（_repo_root）で走らせること**（修正側と同じ世界を数える）。argv の `:(top)` は、
    ルートで走らせる今は効かない——cwd がルートでなくなったときの二重の備えとして残す（tests/mutations.json の dropped と
    同じ決定）。版は周の頭に必ず固まる（_freeze_revision）ので、版の無い枝は持たない。

    **走らせ方は engine の grep（数え直しの問いと同じ 1 本）**——時間切れ・出力の上限・標準エラーへの書き込み・
    1 でない非 0 を『読めなかった』として理由付きで返し、一致なしの exit 1 だけを 0 件にする。git() の None は
    その 3 つを区別しないので、以前は 0 件と壊れた世界を後から問い合わせて見分けていた。
    返すのは（`…:数` の文字列, ""）か（None, 理由）。
    """
    root = _repo_root()
    if root is None:
        return None, "git が動かない"
    return grep(["git", "grep", "-F", "-cI", "-e", cite, rev, "--", ":(top)"], root, 60)


def _in_version(rels):
    """指し先の候補を、**次の周に指摘側が数える版にほぼ同じ世界**で引く（違いは下の注記）——{rel: "text" | "binary"}（無い rel は入らない）。
    git が動かなければ None。

    **在るかどうかの判定者はこの 1 本だけ。** 以前は在るかを FS の is_file で、数えを git grep で決め、
    食い違うたびに特例（バイナリの 2 回目の grep・大小文字の ls-files）を足していた——`.gitignore` に当たる
    ファイルは FS では在るのに、周の頭に add -A で固める版にもコミットにも入らない。数える世界を広げて
    受理すると、柵が塞ごうとした『指し先の無い案内板』を柵自身が合格にした（再現: simulate_review.py の主経路の腕
    『.gitignore に当たる指し先は『版に入らない』で拒む』——数える世界を広げると rc=0 になる）。

    `--cached --others --exclude-standard` は本物の index＋.gitignore に当たらない未追跡で、周の頭に固める版（本物の index の
    写しへの add -A）とは 1 点で違う: index に残る消したファイル（呼び元が作業ツリーの通常ファイルも要求して落とす）。
    force-add した .gitignore の対象は、どちらの世界にも入る（_worktree_tree が本物の index を写すので）。`--full-name` は git の cwd がサブディレクトリでも
    ルート相対で返させるため、`--eol` の `w/-text` がバイナリの印。申告の数に依らず子プロセスは 1 本。
    """
    got = git("ls-files", "-z", "--full-name", "--cached", "--others", "--exclude-standard", "--eol",
              "--", *[f":(top,literal){r}" for r in rels])
    if got is None:
        return None
    want, found = set(rels), {}
    for ent in got.split("\0"):
        meta, sep, path = ent.partition("\t")
        if sep and path in want:
            found[path] = "binary" if "w/-text" in meta.split() else "text"
    return found


def _resolve_target(tgt, root):
    """役が書いたパス 1 つ（指し先か書いた場所）を、**リポジトリ相対の正規形 1 つ**に解く ——（rel, 理由）。

    **同じ入力の解決を 1 か所にする。** 以前は同じ `target` を 3 つの機構が別々の基準で解いていた——
    存在検査と読了の記録は `Path(root) / tgt` を resolve した絶対パス、走査は生の `:(top){tgt}`。
    そこから 3 つの割れ方が出た: ①pathspec の既定は wildmatch なので `a[1].md` と書くと `a1.md` を
    数え（`:(top)` は基準点を決める magic で、綴りを字面に固定するのは `literal`——gitglossary）、
    ②`./docs/a.md` は is_file を通るのに pathspec では index の綴りに当たらず 0 件、③`/etc/hosts` は
    `Path(root) / tgt` が結合を捨てて絶対パスを返すので、存在検査を通った先を hook_evidence が開いた。
    ここで作った 1 つの文字列を、版の問い・数え・読了の記録の**三方すべて**に渡す。

    **綴りが正規形と違えば、直さずに拒む**（`./` 付き・`..` で戻る・symlink 経由）。黙って直すと、
    役は自分が何を書いたかを知らないまま通り、次の周に同じ綴りでまた書く。リポジトリの外へ出る指しも拒む。
    """
    rootp = pathlib.Path(root).resolve()
    try:
        real = (rootp / tgt).resolve()
        rel = real.relative_to(rootp).as_posix()
    except (ValueError, OSError, RuntimeError):   # RuntimeError: 3.12 以前の resolve は symlink の輪をこれで投げる
        return None, "リポジトリの外を指している（リポジトリ相対のパスで書け。絶対パスや '..' で外へ出る指しは受け取らない）"
    if rel != tgt:
        return None, f"正規形で書け: '{rel}'（'./' 付き・'..' で戻る綴り・symlink 経由は、指し先が 1 つに決まらない）"
    return rel, ""


def _not_in_version(full):
    """版に無いパスの、事実どおりの理由（拒否文の後半）。**判定には使わない**——判定は _in_version だけが下す。"""
    if full.is_dir():
        return "通常のファイルでない（ディレクトリなど）——ファイルを 1 つ指せ"
    if full.exists() and not full.is_file():
        return "通常のファイルでない（FIFO・ソケットなど）——ファイルを 1 つ指せ"
    if full.exists() or full.is_symlink():
        return ("在るが版の一覧に出ない（.gitignore に当たる・綴りの大文字小文字が違う・サブモジュールの中、など）——次の周に"
                "指摘側が数える版にもコミットにも入らない指し先は、他の人の手元に存在しない。リポジトリの一覧に在る綴りの、版に入るファイルを指せ")
    return "いまの作業ツリーに無い——ファイルを 1 つ指せ（綴りを確かめるか、先に作れ）"


# 数え直しの呼び元ごとの性質。**呼ぶ先を増やすときはここに 1 行足す。** 共有するのは行の事前検査と拒否の形で、
# 数え方は呼び元で分かれる（下の target）。
#   what      拒否文が名乗る「何を」
#   target    申告に「指し先のファイル」が付くか。付かない側（findings）は版全体を数えて件数の申告（hits）と
#             突き合わせ、付く側は申告の種類（kind）ごとに、指し先が版に在るか・その中に字列が在るかを見る
#             （射程は _cite_errors の docstring）。
#             **行の形（"hits" in row）で決めない**——行で決めていたとき、findings の schema から hits を
#             外すだけで件数の突合が全行で黙って消え、台本は全件緑のままだった
CITE_LABELS = {"findings": {"what": "指摘の根拠", "target": False},
               "wrote_refs": {"what": "修正が書いた指し", "target": True}}


def _cite_errors(b, nid, rows, rev, label):
    """**申告された字列を、現物で数え直す** ——（errs, reads）。reads は指し先ごとの読了の記録（target の呼び元だけ）。

    **指摘する側と修正する側が同じ関数を呼ぶ。** 以前この数え直しは指摘側（findings）の中に埋まっていて、
    **修正側が新しく書いた節名・見出し・引用は誰も引き直さなかった**——記憶から組み立てた節名がそのまま
    通り、指し先の無い案内板が残った（伝聞: 別リポジトリの 11 周目の申し送り。こちらでは再現していない。
    受領の記録は docs/feedback/review-loop-remaining-findings.md）。同じ柵を 2 か所に書き写すと片方だけ
    直るので、呼ぶ先を増やす形にしてある。

    `rev` は数える版。None なら作業ツリーを、周の頭に固める版と同じ世界で数える。**指し先を持つ呼び元
    （target）は作業ツリーだけ**を数える——修正役がファイルを書くのは p3.fix の中なので、周の頭で固めた版には
    まだ入っていない（版を渡していたときは、この周に作ったファイルを指す正直な申告が必ず落ちた）。

    **修正側は「指し先のファイル」の中だけを数える。** リポジトリ全体を数えていたとき、柵は主張より
    弱かった——同じ名前が別の文書に在るだけで通った（実測: この柵を入れた差分自身が、発端の実例の字列を
    別の文書に持っていた）。**リポジトリの中で再現できる**: 数える先を指し先から外すと、simulate_review.py の
    『別の文書に同じ字列が在っても通らない』腕が rc=0 になる。指し先と書いた場所（where）の在る・無いは
    _in_version 1 本で決め、数えは解決済みの 1 ファイルを上限付きで直接読む（索引の意味論は要らない）。

    **射程**: 引くのは申告された行だけで、空配列は 1 件も引かない（この 1 点は役のプロンプトに書かない——
    抜け方を当の役に教えることになる）。挙げ漏れを機械で拾う案は機構の新設なので採っていない（台帳の fork）。
    **target に『その指しを書いた当のファイル』を書くと、書いた行そのものに当たって通る**——where を
    target と同じ規律で解き、同じファイルなら印（self）を付けて次の周の判定役に見せる。拒まないのは、
    同じファイルの中の指し（目次から本文の節へ、など）が正当な形だから。判断の記録は
    docs/feedback/review-loop-remaining-findings.md の『設計の記録: 修正側の裏取り』。
    """
    # 知らない label は KeyError で落とす——黙って一般名に倒すと、呼ぶ先を増やした周に文言だけが古いまま残る
    kind = CITE_LABELS[label]
    what = kind["what"]
    if kind["target"] and rev:
        raise ValueError(f"{label}: 指し先を持つ呼び元は作業ツリーを数える（版 {rev[:12]} を渡された）")
    if not kind["target"] and not rev:
        raise Reject(f"{nid}: {what}を数え直せない（採点する版が固まっていない）——確かめられないものを合格にはしない")
    # **不変な問いは 1 度だけ引き、要る枝に入るまで引かない。** 頭で打たないのは、引く行が 1 つも無い周が
    # あるため（申告が空の周・指し先を持たない findings では、root の問いは 100% 捨てられる）。
    # 費用は子プロセス 1 本あたり 158ms（writer がこの機械で 2026-09-22 に測った値。
    # `git -C . rev-parse` を 20 回起こした平均）。行ごとに打ち直していた頃は、外した行 1 件につき 2 本の上乗せ。
    probed = {}
    errs, reads, pend = [], [], []
    for i, row in enumerate(rows):
        # **素の文字列の拒否は残す。** 主経路では schema が object を強制するので届かないが、検証器の台本は
        # この関数を直に呼ぶし、graph を持ち込む側は items の型を緩められる。柵の側を薄くして入口の宣言に
        # 頼ると、宣言を書き換えた周に黙って通る
        if not isinstance(row, dict):
            errs.append((i, f"{label}[{i}]: 素の文字列は受け取らない（cite を持つ形で出せ）——"
                            "裏取りの柵が入る前の形が、数え直されないまま毎周の判定材料に載り続けていた"))
            continue
        # **申告の種類で満たし方を分ける**（修正側だけ）。ファイル名の指しは指し先の本文に自分のパスを持たないので、
        # 字列の在る・無いで判定していた頃は、正しいファイルを正直に申告した行ほど必ず落ちた（主経路で観測）
        rk = row.get("kind") if kind["target"] else "text"
        if rk not in ("file", "text"):
            errs.append((i, f"{label}[{i}]: kind が {rk!r}——file（ファイルそのものを指した）か text（ファイルの中の"
                            "節名・見出し・引用を指した）で書け"))
            continue
        cite = (row.get("cite") or "").strip()
        if rk == "text" and not cite:
            errs.append((i, f"{label}[{i}]: cite（作業ツリーで引ける字列）が空"))
            continue
        if "\n" in cite or "\r" in cite:
            errs.append((i, f"{label}[{i}]: cite に改行が入っている——" + (
                "1 行 1 件で書け（書いた指しの 1 か所を、指し先の 1 行から写す）" if kind["target"] else
                "数えは行単位の git grep なので『どれか 1 行が在れば合格』に化ける（空行を混ぜれば必ず通る。-F でも同じ）。"
                "1 行 1 件に割って出せ")))
            continue
        # **NUL を含む字列は受け取らない。** argv に NUL は入らないので subprocess が ValueError を投げ、
        # **拒否でなく例外**になる（実測: 自己反証で cite に NUL を混ぜたら done が例外で落ちた）
        if "\0" in cite or "\0" in (row.get("target") or "") or "\0" in (row.get("where") or ""):
            errs.append((i, f"{label}[{i}]: cite / target / where に NUL が入っている"
                            "——検索語にもパスにも使えない（現物から写し直せ）"))
            continue
        if not kind["target"]:
            _count_in_version(nid, what, label, i, row, cite, rev, probed, errs)
            continue
        tgt = (row.get("target") or "").strip()
        if not tgt:
            errs.append((i, f"{label}[{i}]: target（この指しが指しているファイル）が空"
                            "——どこを見れば在ると言えるのかを書け（柵はそのファイルの中だけを数える）"))
            continue
        # **ルートが引けない回は、何も開く前に止める。** 以前は封じ込めが『ルートが引けた回だけ』に
        # 掛かり、引けない回は検査ごと飛んで、その先の読了の突合がリポジトリ外の絶対パスを開いた
        # （再現: simulate_review.py の test_wrote_refs_reads_and_dir_target の、ルートを引けない回の腕）——**開くのが先で
        # 拒むのが後**だった。ルートが無いことは『確かめられない』であって『検査対象外』ではない
        if "root" not in probed:
            probed["root"] = _repo_root()
        if not probed["root"]:
            raise Reject(f"{nid}: {what}の指し先を確かめられない（リポジトリのルートを引けない——git が動かないか、"
                         "リポジトリの外で打った）——確かめられないものを合格にはしない")
        rel, why = _resolve_target(tgt, probed["root"])
        if rel is None:
            errs.append((i, f"{label}[{i}]: 指し先 '{tgt}' は{why}"))
            continue
        # **where も target と同じ規律で解き、空なら拒む。** 入口の宣言（schema の required）だけに頼ると、
        # 直に呼ぶ経路で空の where が通り、印（self）が真・偽・null の 3 値になった
        where = (row.get("where") or "").strip()
        if not where:
            errs.append((i, f"{label}[{i}]: where（この指しを書き込んだファイル）が空"
                            "——書いた場所が分からないと、指し先と同じファイルかを誰も見られない"))
            continue
        wrel, why = _resolve_target(where, probed["root"])
        if wrel is None:
            errs.append((i, f"{label}[{i}]: 書いた場所 '{where}' は{why}"))
            continue
        pend.append((i, rk, cite, rel, wrel))
    if pend:
        seen = _in_version(sorted({p for _, _, _, rel, wrel in pend for p in (rel, wrel)}))
        if seen is None:
            raise Reject(f"{nid}: {what}を数え直せない（git が動かない）——確かめられないものを合格にはしない")
        cache = {}
        for i, rk, cite, rel, wrel in pend:
            full = pathlib.Path(probed["root"]) / rel
            # **版の一覧に在り、かつ作業ツリーに通常のファイルとして在る**——一覧は実物の index（--cached）を引くので、
            # git rm を使わずに消したファイルが残る。周の頭に固める版（一時 index への add -A）には入らないのに、
            # 中を開かない kind=file の指しだけが通っていた（2026-09-23。台本 test_wrote_refs_direct_arms の gone.md の腕）
            if rel not in seen or not full.is_file():
                errs.append((i, f"{label}[{i}]: 指し先 '{rel}' は{_not_in_version(full)}"))
                continue
            wfull = pathlib.Path(probed["root"]) / wrel
            if wrel not in seen or not wfull.is_file():
                errs.append((i, f"{label}[{i}]: 書いた場所 '{wrel}' は{_not_in_version(wfull)}"))
                continue
            data = None
            if rk == "text":
                if seen[rel] == "binary":
                    errs.append((i, f"{label}[{i}]: 指し先 '{rel}' はバイナリなので中を数えられない"
                                    "——字列で確かめられる指し先（テキスト）を指すか、ファイルそのものの指しなら kind を file にせよ"))
                    continue
                data, why = read_capped(full, READ_CAP)
                if data is None:
                    errs.append((i, f"{label}[{i}]: 指し先 '{rel}' は版には在るが、作業ツリーで数えられない（{why}）"
                                    "——消した・置き換えた指し先なら、書いた指しの方を直せ"))
                    continue
            state, hwhy = hook_evidence(b.dir, str(full), cache=cache, data=data)
            reads.append({"kind": rk, "cite": cite[:60] or None, "target": rel, "where": wrel,
                          "self": wrel == rel, "state": state, "why": hwhy})
            if rk == "text" and cite.encode("utf-8") not in data:
                hint = "（このファイルをこの run で読んだ記録が無い——記憶で書いていないか）" if state == "absent" else ""
                errs.append((i, f"{label}[{i}]: '{cite[:40]}' は指し先 '{rel}' の中に無い{hint}"
                                "——文書に書いた指しを指し先に在る綴りへ直し、その字列で申告し直せ（申告だけ差し替えても文書の誤りは残る）"))
    return [m for _, m in sorted(errs, key=lambda e: e[0])], reads


def _count_in_version(nid, what, label, i, row, cite, rev, probed, errs):
    got, why = _grep_count(cite, rev)
    if why:
        # 読めなかった理由のうち、よく在る 2 つ（git そのもの・版が消えた）は直し方が違うので名指しする。
        # **取り違えると拒否文が事実と逆になる**（『現物に 1 件も無い』は、数えられなかった回には偽）
        if "alive" not in probed:
            probed["alive"] = git("rev-parse", "--is-inside-work-tree") is not None
            probed["rev"] = git("rev-parse", "--verify", f"{rev}^{{commit}}") is not None
        if not probed["alive"]:
            raise Reject(f"{nid}: {what}を数え直せない（git が動かない）——確かめられないものを合格にはしない")
        if not probed["rev"]:
            raise Reject(f"{nid}: {what}を数え直せない（採点する版 {rev[:12]} を解決できない）"
                         "——版が消えた run では、数えた結果も『現物に無い』も言えない")
        raise Reject(f"{nid}: {what}を数え直せない（{why}）——確かめられないものを合格にはしない")
    hits = sum_counts(got)
    if hits is None:
        raise Reject(f"{nid}: {what}を数え直せない（git grep -c の出力が `…:数` の形でない: {got.splitlines()[:1]}）")
    if hits == 0:
        errs.append((i, f"{label}[{i}]: '{cite[:40]}' が現物に 1 件も無い"
                        "——現物に無い字列は受け取らない（現物を開いて、在る字列で出し直せ）"))
    elif row.get("hits") != hits:
        errs.append((i, f"{label}[{i}]: '{cite[:40]}' の件数の申告 {row.get('hits')} が数え直し {hits} と違う"))


def lane_receipt(b, nid, out, item):
    """線を立てた受領: 名乗る置き場がこの周に固めた線の置き場と同じか。**線の結果はここでは待たない**——受領は線を立てた事実だけで、
    結果は線が書き終えた後の周の頭（_lane_faces）と修正の前（lane_merge）が置き場から読む"""
    cut = _gates_cut(b) or {}
    if out["lane"] != cut.get("result"):
        raise Reject(f"{nid}: 受領の置き場 {out['lane']!r} がこの周の線の置き場 {cut.get('result')!r} と違う——プロンプトが名指す置き場で線を立てよ")


def final_gates_output(b, nid, out, item):
    """最後の関門の返答の整合: この周に固めた最終の版を撃ち、見逃しに全部 1 度だけ答え、作業ツリーに書かない"""
    errs = _lane_errors(b, out, (_gates_cut(b) or {}).get("rev") or "", final=True)
    if errs:
        raise Reject(f"{nid}: " + "; ".join(errs))


POST_CHECKS = {"main_path_observed": main_path_observed, "external_rankings": external_rankings, "purpose_findings_cited": purpose_findings_cited, "gate_arms_all_red": gate_arms_all_red, "rejudge_output": rejudge_output, "measured_needs_output": measured_needs_output, "base_valid": base_valid, "judge_output": judge_output, "fix_covers_open_units": fix_covers_open_units,
               "r2_design": r2_design, "r4_inventory": r4_inventory, "cold_check_note": cold_check_note,
               "local_review_covers_lenses": local_review_covers_lenses, "fix_plan_covers_units": fix_plan_covers_units,
               "plan_review_output": plan_review_output, "delta_review_output": delta_review_output, "delta_fix_output": delta_fix_output,
               "lane_receipt": lane_receipt, "final_gates_output": final_gates_output}


def check_record(b, nid=None):
    """素材と俯瞰の欄を、検証器の表（STATUS / REVIEW_STATUS）で done の時点に見る（写さず import）。
    あわせて役が書いた status を機械が既に持つ事実と突き合わせる——走った節の素材が not_applicable（applies_cond が
    真だったから走った）は矛盾。nid は今 done している節（まだ done の印が付いていないので名指しで渡る）。"""
    V = validator_module(b)
    errs = []
    # 「今の周に走った」＝今の周に instance が出て done（once の節は前の周の done を引き継ぐので node_state では見ない）
    ran = {nid} | {i["node"] for i in b.rd["instances"].values() if i["status"] == "done"}
    for k, n in b.nodes.items():
        if k not in ran:
            continue
        ap = n.get("applies_cond")
        for mat in n.get("materials", []):
            m = b.record["materials"].get(mat)
            if not m:
                continue
            st = m.get("status")
            # 素材の status（6 値）× 機械が持つ事実（この周に走った・applies_cond が真だった）の表。走った節の素材に
            # 『流用』『条件外』は書けない——1 値（not_applicable）だけ塞いでいたとき carried_over で同じ穴が通った（実測 2026-09-13）
            # 『流用』は走らなかった節に機械が書くもの。走った節に書けるのは今の周の判定。
            # **carried_over 1 語を名指ししない**——検証器の表から「黙って通る値」を引く（not_applicable は
            # 下の腕が na_self_ok の宣言と突き合わせるので、ここでは除く）
            if st in V.SILENT_STATUS and st != "not_applicable":
                errs.append(f"素材 '{mat}'（節 {k}）は今の周に走ったのに {st}——自分で見たと主張しない値は走らなかった節に機械が書く。今の周の判定を書け")
            # 走った節の『条件に当たらない』は、機械が持つ事実（applies_cond が真）と食い違うなら拒む。
            # applies_cond を持たない節は機械に照らす事実が無いので、**正当に名乗れる節を graph が宣言する**
            # （na_self_ok）——`ap is not None` で絞っていたとき、宣言の無い 11 節（うち回す側が 6）まで自己申告で
            # 素通りした。逆に全部拒むと、CI が存在しない対象や修正 0 件の周という正当な経路が落ちる（実測 2026-09-13）
            if st == "not_applicable":
                if ap is not None and b.cond(ap)[0]:
                    errs.append(f"素材 '{mat}'（節 {k}）は applies_cond が真で走ったのに not_applicable——機械が持つ事実と食い違う")
                elif ap is None and not n.get("na_self_ok"):
                    errs.append(f"素材 '{mat}'（節 {k}）は走ったのに not_applicable——この節は正当に名乗れる節として graph が"
                                "宣言していない（na_self_ok）。今の周の判定を書くか、名乗れる理由を graph に宣言しろ")
    errs += _awaiting_origins(V, b.record["questions"], b.record["materials"], "台帳の questions")
    # **逆向きも書いた時点で見る**: 判定者が台帳を書いた後の周の工程が、人待ちの問いの無い素材を awaiting_human と書いたら拒む。
    # 検証器は周の最後に『awaiting_human なのに台帳に kind=awaiting で無い』と落とすだけで、書いた節に返らなかった
    # （2026-09-24: 任せ先の p4.ci が、CI の欄と関係ない field の問いを理由に、緑の CI を awaiting_human と書いた）。
    # 判定より前の工程（P1 の素材）は、人待ちを書くのが先で判定者が問いを立てるのが後なので当てない
    judged = any(x["node"] in ("p2.diagnose", "p2.history") and x["status"] == "done" for x in b.rd["instances"].values())
    listed = {q.get("origin") for q in b.record["questions"] if q.get("kind") == "awaiting" and q.get("status") in V.ASKING}
    for mat in b.nodes.get(nid, {}).get("materials", []) if (judged and nid) else []:
        m = b.record["materials"].get(mat) or {}
        if m.get("status") == "awaiting_human" and mat not in listed:
            errs.append(f"素材 '{mat}'（節 {nid}）を awaiting_human と書いたが、台帳にこの素材を出どころにする人待ちの問い（kind=awaiting）が無い"
                        "——判定の後の工程は人待ちを新しく立てない。見た結果を found / clean で、走らせられなかったなら not_run（理由つき。収束は止まる）で書け"
                        "（人が実地で確かめる話は判定者の field の問いで、素材の欄ではない）")
    for name, m in b.record["materials"].items():
        st = m.get("status")
        if st not in V.STATUS:
            errs.append(f"素材 '{name}' の status が不正: {st!r}")
            continue
        for f in V.STATUS[st].fields:
            v = m.get(f)
            if f in V.NUMERIC_FIELDS:
                if not V.is_int(v):  # 数の判定は検証器の述語を使う（写しは 10 値で一致していても、変えたとき片方だけ動く）
                    errs.append(f"素材 '{name}'（{st}）の '{f}' は数で書け")
            elif not isinstance(v, (str, list)) or not v:
                errs.append(f"素材 '{name}'（{st}）に '{f}' が要る（何を見たかを書け）")
    for name, r in b.record["reviews"].items():
        st = r.get("status")
        if st not in V.REVIEW_STATUS:
            errs.append(f"{name} の status が不正: {st!r}")
            continue
        if name not in V.REVIEW_STATUS[st].only_for:
            errs.append(f"{name} は {st} にできない")
        for f in V.REVIEW_STATUS[st].fields:
            if not r.get(f):
                errs.append(f"{name}（{st}）に '{f}' が要る")
    return errs


# ---------------------------------------------------------------- 仕上げと人の答え
def finalize(b):
    V = validator_module(b)
    rec, ls = b.record, b.loop_state
    proc = rec["process"]
    # 結末は決まったときだけ書く（GitHub Checks の conclusion と同じ）。loop に結末が無いまま仕上げに来た run は、盤面が止まって
    # いれば stopped、走っているなら running（loop.py finalize を途中で打った）——未決を stopped と名乗らせない
    proc["outcome"] = ls.get("outcome") or ("stopped" if b.state.get("status") == "stopped" else "running")
    # init --stop-after-round で止めた run は converge が next_round を返した後なので loop に理由が無い——止めた口（halted）の理由を写す
    proc["stop_reason"] = ls.get("stop_reason") or (b.state.get("halted") or {}).get("by")
    # 止めた所と理由の本文（halted は後の節を出さない止め方、stop は loop.py stop の記録）。by だけでは人の理由が落ちる
    proc["halted"] = b.state.get("halted") or b.state.get("stop")
    proc["defer_ledger"] = ls.get("defer_ledger", {})
    proc["validator_outputs"] = ls.get("validator_outputs", {})
    proc["drift_notes"] = ls.get("drift_notes", [])
    # **書く欄には読み手を付ける。** 付けずに置いていたとき、この欄は 2 周ぶん書かれたまま
    # リポジトリのどこからも読まれず、R2 は「なぜ目的が使えないのか」を知らずに回った（実測 r10）。
    # 運び方は隣の drift_notes と同じ 3 点（記録へ写す・プロンプトの穴・graph の reads）で揃える
    proc["purpose_review_stale"] = ls.get("purpose_review_stale", [])
    proc["context_lost"] = b.state.get("context_lost", [])
    # 引き金そのものが測れなかった周。**「条件に当たらなかった」と「条件を測れなかった」を同じ偽にしない**
    proc["unevaluable"] = b.state.get("unevaluable", [])
    proc["cold_check"] = ls.get("cold_check")  # 初見検査の verdict と件数（非 pass でも報告は出る。直したかは writer の申告）
    proc["open_questions"] = [q for q in rec["questions"] if q.get("status") in V.ASKING]
    proc["resolved_questions"] = [q for q in rec["questions"] if q.get("status") in V.DECIDED_STATUS]
    # 最後の関所の後に方針の文書が変わって止まった run も、変化を記録と報告に残す（関所は周の途中にしか無い）
    ch = "policy" in proc and _policy_change(b)
    if ch:
        proc["policy_change"] = ch
    else:
        proc.pop("policy_change", None)


def on_answer(b, ph, ans):
    # **kinds を落とさない。** 以前は round / asked / answer / note だけを積んでいたので、
    # 記録からは「何を聞かれて continue したか」が読めず、上限を延ばした周とそうでない周を区別できなかった
    # （実測 2026-09-13: process.human_answers が {"round":5,"note":…,"asked":[]} で、延長が読み取れない。
    # kinds が残るのは trace.jsonl だけだった——下の注記が「痕跡は process.human_answers に残る」と
    # 名乗っていたのに、その前半が現物と食い違っていた）。
    kinds = ph.get("kinds") or []
    b.record["process"]["human_items"].append({"round": b.round, "kinds": kinds, "asked": ph["items"],
                                               "answer": ans, "note": ph.get("note", "")})
    if ans == "continue":
        entry = {"round": b.round, "kinds": kinds, "note": ph.get("note", ""), "asked": ph["items"]}
        b.loop_state.pop("outcome", None)
        b.loop_state.pop("stop_reason", None)
        if "final_gate_empty" in kinds:
            # 人が 0 本で収束してよいと答えた木——同じ木を撃った関門だけが 0 本で通る（木が変われば聞き直す）
            cut = _gates_cut(b) or {}
            tree = git("rev-parse", f"{cut.get('rev', '')}^{{tree}}") if cut.get("rev") else None
            b.loop_state["final_gate_empty_ok"] = (tree or "").strip() or None
            if b.state["max_rounds"] <= b.round:   # 上限の周の答え——同じ木の関門を撃つ次の周を 1 つ開ける
                _extend_one_round(b, entry)
        if "max_rounds" in kinds:
            _extend_one_round(b, entry)
        b.record["process"]["human_answers"].append(entry)


def _extend_one_round(b, entry):
    """上限を 1 周ぶんだけ上げ、上げた値を答えの記録（entry）に書く。上限ごと外すと暴走ガードが二度と掛からない——延長の同意は
    1 周に 1 回もらい直す（state だけに置くと、上げた出どころが自由文の note にしか残らない）"""
    entry["max_rounds"] = {"from": b.state["max_rounds"], "to": b.round + 1}
    b.state["max_rounds"] = b.round + 1


def on_unattended(b, ph):
    b.record["process"]["human_items"].append({"round": b.round, "kinds": ph.get("kinds") or [], "asked": ph["items"],
                                               "answer": None, "note": "無人実行で停止（答えは無い）"})
    return "無人実行: " + ", ".join(ph["kinds"]) + "——保守的に停止。要人間判断は process.human_items"


def on_stop(b, info):
    """人が loop.py stop で止めた（engine の cmd_stop が呼ぶ）。止めた事実を今すぐ記録に書き（報告の節が読む）、報告の前の
    検証器が読む周の記録を揃える。返すのは報告を出せない理由（None なら出せる）——engine はそのとき後の節を出さずに止める。

    engine は盤面の保存が衝突すると読み直した盤面にこれを当て直す。周の記録のファイルは盤面の外なので、周の締めが済んだかは
    ファイルの有無でなく盤面（周の記録を組む節が済んだか）で決め、済んでいなければ当て直すたびに今の盤面から組み直して上書きする
    ——負けた試行が残したファイルを『済んだ』と読むと、記録と周の記録が割れる"""
    rec, ls = b.record, b.loop_state
    ls["outcome"], ls["stop_reason"] = "stopped", "stop"
    rec["process"]["halted"] = info
    if info.get("unanswered"):
        ua = info["unanswered"]
        rec["process"]["human_items"].append({"round": b.round, "kinds": ua.get("kinds") or [], "asked": ua.get("items") or [],
                                              "answer": None, "note": f"答えないまま人が止めた（loop.py stop）: {info['reason']}"})
    if any(n.get("builtin") == "record_round" and nid in b.rd["done"] for nid, n in b.nodes.items()):
        return None   # 周の記録は済んでいる（周の締めの後で止めた）
    if b.round > 1 and b.output_of_round("p2.diagnose", b.round) is None:
        # 判定より前に止めた 2 周目以降: 周の頭で空にした台帳と単位を前の周の姿に戻す（報告は record を読む）。周の記録は前の周まで
        rec["units"], rec["questions"] = ls.get("prev_units") or [], ls.get("prev_questions") or []
        return None
    return _stopped_round_record(b, f"人が止めた（loop.py stop）: {info['reason']}")


def _stopped_round_record(b, reason):
    """止めた周の記録を組む（record_round と fill_materials をそのまま使う）。**写しの上で組み、検証器を通ったときだけ盤面に残す**
    ——通らなければ記録・loop の欄・周の記録のファイルを組む前に戻し、報告を出せない理由を返す"""
    import copy
    rec0, ls0 = copy.deepcopy(b.record), copy.deepcopy(b.loop_state)
    # 止めた節の素材に機械が先に置いた仮の値（P1 の時点の fix_closure など）は、止めた事実で書き直す——同じ素材を書く節が
    # この周に済んでいれば（p0.local_checks と p4.ci の local_checks）その値を残す
    ran = {m for nid, n in b.nodes.items() if nid in b.rd["done"] for m in n.get("materials", [])}
    for nid in b.rd.get("stopped", {}):
        for mat in b.nodes[nid].get("materials", []):
            if mat not in ran:
                b.record["materials"].pop(mat, None)
    fill_materials(b)
    out = record_round(b, None, stopped_reason=reason)
    if out.get("ok"):
        return None
    b.record = rec0
    b.state["loop"] = ls0
    (b.dir / "rounds" / f"round-{b.round}.json").unlink(missing_ok=True)
    return "止めた周の記録が検証器を通らない: " + "; ".join(out.get("problems") or [])[-800:]


# ---------------------------------------------------------------- 仕様の道（選んだときだけ）
# 新しい仕組みを作る依頼で、受け入れ条件を先に固めてから判定に入る道。init の `--input flow=spec` だけが選び、
# 既定（flow を渡さない）は今の流れのまま——spec.* の節は cond（spec_flow）が偽で na になり、ここの builtin と post_check は
# 呼ばれない（呼ばれるのは init の check_inputs・on_init と、条件の評価の spec_flow・spec_revise_due だけ）。
# 今の流れの関数からここは呼ばない（将来のブロック分割で『仕様ブロック』へ移す単位）。受け入れ条件の本文
# （Given/When/Then）の正本は対象リポジトリのテストのファイルで、記録はその置き場・sha・承認の時点の終了コードだけを持つ
# （写さない）。同じテストが TDD の『先に書く赤いテスト』になる——record.process.spec.acceptance[].run がその呼び方。
SPEC_FLOW = "spec"
SPEC_ORIGIN = "仕様（人が承認した受け入れ条件。テストの本文は writer が書いた）"
# 判定のプロンプト（p2.diagnose.md）は依頼の入口の欄を『多くは人の依頼』と案内し、人でない出どころ（仕様・並行の線）は 1 件ごとの
# 本文の頭で見分けさせる。仕様のバッチは writer が書いたテストと機械の実測なので、出どころを 1 件ごとの本文に書く
SPEC_PROVENANCE = "【仕様の受け入れ条件——テストの本文は writer が書き、人は承認しただけ。役の観察と同じく反証の対象】"
SPEC_RUN_TIMEOUT = 600      # 受け入れ条件 1 件の run の上限（秒）
GWT = ("Given", "When", "Then")


@cond_reads("loop.flow")
def spec_flow(v):
    """仕様の道を選んだ run か（条件の関数。spec.* の節だけが読む）"""
    got = v("loop.flow", None)
    return got == SPEC_FLOW, (f"仕様の道を選んだ run（flow={got}）" if got == SPEC_FLOW else
                              "仕様の道を選んでいない run（init --input flow=spec が無い）——今の流れのまま")


def _spec_now(b):
    """いまの仕様——修正役が直した版（spec.revise）が在ればそれ、無ければ最初の版（spec.write）"""
    rv = b.latest_output("spec.revise")
    return rv["spec"] if rv else b.latest_output("spec.write")


@cond_reads("out.spec.review")
def spec_faces_open(v):
    n = len((v("out.spec.review", None) or {}).get("faces") or [])
    return bool(n), f"仕様の審査が挙げた穴は {n} 件"


@cond_reads(*spec_flow.reads, *spec_faces_open.reads)
def spec_revise_due(v):
    """仕様の道を選んだ run で、仕様の審査が穴を挙げたとき（spec.revise の条件）"""
    ok, why = spec_flow(v)
    return spec_faces_open(v) if ok else (ok, why)


def _file_sha(root, rel):
    p = root / rel
    return sha_file(p) if p.is_file() else None


def sha_file(p):
    """役が指したファイルの sha256（読めない・通常のファイルでない・上限を超えるなら None）——役が指したパスを開く所は read_capped を通す"""
    import hashlib
    data, _why = read_capped(str(p), READ_CAP)
    return None if data is None else hashlib.sha256(data).hexdigest()


def _spec_errors(spec):
    """仕様の形（post_check の共通部分）: 鍵が一意・受け入れ条件が要件を指す・要件は 1 件以上の受け入れ条件を持つ・
    テストのファイルが在ってその名前と Given/When/Then を含む"""
    root = pathlib.Path(_repo_root() or ".")
    reqs, acs = spec["requirements"], spec["acceptance"]
    errs = _keys_once(reqs, "requirements") + _keys_once(acs, "acceptance")
    rkeys = {r["key"] for r in reqs}
    errs += [f"acceptance '{a['key']}' の requirement '{a['requirement']}' が requirements に無い" for a in acs if a["requirement"] not in rkeys]
    errs += [f"要件 '{k}' に受け入れ条件が無い——実行できるテストを 1 つ以上書け" for k in sorted(rkeys - {a["requirement"] for a in acs})]
    for a in acs:
        data, why = read_capped(str(root / a["file"]), READ_CAP)
        if data is None:
            errs.append(f"acceptance '{a['key']}' のテストのファイル {a['file']} が読めない（{why}）——対象リポジトリに先に書け")
            continue
        text = data.decode("utf-8", errors="replace")
        if a["name"] not in text:
            errs.append(f"acceptance '{a['key']}' の name '{a['name']}' が {a['file']} に無い")
        miss = [w for w in GWT if w not in text]
        if miss:
            errs.append(f"acceptance '{a['key']}' の {a['file']} に {'/'.join(miss)} が無い——受け入れ条件は Given/When/Then をテストの中に書く")
    return errs


def spec_write_output(b, nid, out, item):
    errs = _spec_errors(out)
    if errs:
        raise Reject(f"{nid}: " + "; ".join(errs))


def spec_review_output(b, nid, out, item):
    faces = out.get("faces") or []
    errs = _keys_once(faces, "faces")
    if not faces and blank(out.get("faces_none"), 20):
        errs.append("穴を挙げないなら faces_none に何を確かめて無いと言えるかを書け")
    if errs:
        raise Reject(f"{nid}: " + "; ".join(errs))


def spec_revise_output(b, nid, out, item):
    """審査の穴に key ごとに 1 度だけ答える（語彙は事前審査への答え plan_faces と同じ absorbed / declared）"""
    asked = {f["key"] for f in (b.latest_output("spec.review") or {}).get("faces") or []}
    rows = out["handled"]
    errs = _keys_once(rows, "handled")
    errs += [f"handled の key '{r['key'][:40]}' は仕様の審査に無い" for r in rows if r["key"] not in asked]
    errs += [f"仕様の審査の '{k[:40]}' に応答が無い——absorbed（どう取り込んだか）か declared（残す理由）で答えろ"
             for k in sorted(asked - {r["key"] for r in rows})]
    errs += _spec_errors(out["spec"])
    if errs:
        raise Reject(f"{nid}: " + "; ".join(errs))


def _spec_run(root, cmd):
    """受け入れ条件 1 件の run を今の作業ツリーで走らせた終了コード（走らなければ None と理由）。走らせるのは人が承認の問いで
    このコマンドの字面を見て continue した後だけ（spec_freeze）。時間切れは木ごと止める（engine の run_tree）"""
    import subprocess
    try:
        r = run_tree(cmd, cwd=root, timeout=SPEC_RUN_TIMEOUT, shell=True)
    except (OSError, subprocess.TimeoutExpired) as e:
        left = getattr(e, "tree_left", None)   # 時間切れで止め切れなかった木
        return None, f"{type(e).__name__}: {e}" + (f"——止め切れない木が残った: {left}" if left else "")
    return r.returncode, ""


def spec_approve(b, nid):
    """仕様を人に諮る（周の途中の問い）。**受け入れ条件の run は走らせずに字面を見せる**——run は writer が書いたコマンドで、
    engine の中で走らせると分類器にも人にも掛からない。走らせるのは人が字面を見て continue した後（spec_freeze。
    承認の時点の終了コードはそこで取り、緑なら『赤を見ていない』と判定役に渡す）"""
    spec, root = _spec_now(b), pathlib.Path(_repo_root() or ".")
    rows = [{**a, "sha256": _file_sha(root, a["file"])} for a in spec["acceptance"]]
    b.loop_state["spec_pending"] = {"requirements": spec["requirements"], "acceptance": rows,
                                    "out_of_scope": spec.get("out_of_scope") or []}
    rv = b.latest_output("spec.review") or {}
    handled = {r["key"]: r for r in (b.latest_output("spec.revise") or {}).get("handled") or []}
    items = [f"要件 {r['key']}: {r['text']}" for r in spec["requirements"]]
    items += [f"受け入れ条件 {r['key']}（要件 {r['requirement']}）: {r['file']} の {r['name']}——承認すると engine が `{r['run']}` を"
              "作業ツリーで走らせる（承認の前には走らせていない）" for r in rows]
    items += [f"審査の穴 [{f['kind']}] {f['key']}: {f['why'][:200]}——" + (f"{handled[f['key']]['handled']}: {handled[f['key']]['how'][:200]}" if f["key"] in handled else "答え無し")
              for f in rv.get("faces") or []]
    return {"decision": "ask", "reason": "spec_approval", "ask": {
        "kinds": ["spec_approval"], "in_round": True,
        "question": ("仕様（要件と受け入れ条件）を承認するか。承認すると各受け入れ条件の run のコマンドを走らせて承認の時点の終了コードを取り、"
                     "受け入れ条件を記録に固定し、判定と修正案の基準にする"
                     "（continue --note <承認の言葉や条件>）。承認しないなら run をここで止める（stop）——仕様を直してから新しい run で始めよ"),
        "items": items, "options": ["continue", "stop"]}}


def on_answer_in_round(b, ph, ans):
    """周の途中の問いへの答え（engine の cmd_answer が in_round の問いにだけ呼ぶ）。今の流れの on_answer とは別の口で、
    CI への指示として読まれる process.human_answers には積まない"""
    b.loop_state.setdefault("in_round_answers", []).append(
        {"round": b.round, "node": ph["node"], "kinds": ph.get("kinds") or [], "answer": ans, "note": ph.get("note", "")})
    if ph["node"] in HUMAN_GATES:
        human_gate_answered(b, ph, ans)
    if ans == "continue" and "spec_changed" in (ph.get("kinds") or []):
        spec = b.record["process"]["spec"]
        for ch in b.loop_state.pop("spec_changed", []):
            for a in spec["acceptance"]:
                if a["file"] == ch["file"]:
                    a["sha256"] = ch["to"]
            spec.setdefault("amendments", []).append({**ch, "round": b.round, "note": ph.get("note", "")})


def spec_freeze(b, nid):
    """承認済みの仕様を record.process.spec に 1 度だけ固定し、受け入れ条件をその周の判定に届くよう人の依頼のバッチとして積む
    （1 件の受け入れ条件が 1 件の findings）。承認の時点の終了コード（exit_at_approval）はここで各 run を走らせて取る（人が
    字面を見て continue した後）。積むのはこの 1 回だけで、2 周目以降に受け入れ条件の緑を機械で確かめる節は無い——判定役が
    受け入れ条件を依頼として読み、テストの改変の検知は spec.check が持つ（緑を収束の条件にするのは、選べる流れの選び方の
    fork の決着——TDD の版の実行器に載せるか——で決める）。**拒む回は盤面を変えない**（検査を先に済ませ、成功の後に pop）"""
    cur, why = _requests(b, "request_findings")
    if why:
        return {"ok": False, "problems": [f"記録の依頼の欄の型が崩れている（{why}）——loop.py patch で直してから next"]}
    root = pathlib.Path(_repo_root() or ".")
    pend = dict(b.loop_state["spec_pending"])
    rows = []
    for a in pend["acceptance"]:
        code, err = _spec_run(root, a["run"])
        rows.append({**a, "exit_at_approval": code, **({"run_error": err} if err else {})})
    pend["acceptance"] = rows
    ans = [x for x in b.loop_state.get("in_round_answers", []) if x["node"] == "spec.approve"]
    b.record["process"]["spec"] = {**pend, "approval": ans[-1] if ans else None}
    b.loop_state.pop("spec_pending")
    findings = [{"where": f"{a['file']}: {a['name']}",
                 "text": f"{SPEC_PROVENANCE}受け入れ条件 {a['key']}（要件 {a['requirement']}）がまだ満たされていない——承認の時点で `{a['run']}` が "
                         + ("走らない" if a["exit_at_approval"] is None else
                            "既に exit 0（緑——赤を見ていないので、テストが要件を確かめているかを疑え）" if a["exit_at_approval"] == 0 else
                            f"exit {a['exit_at_approval']}"),
                 "mechanism": f"Given/When/Then の本文は {a['file']} の {a['name']} が正本（記録に写さない）。要件: "
                              + next(r["text"] for r in pend["requirements"] if r["key"] == a["requirement"]),
                 "measured": f"承認の時点（round {b.round}）の実測: `{a['run']}` → "
                             + (a.get("run_error") or "") + ("" if a["exit_at_approval"] is None else f"exit {a['exit_at_approval']}"),
                 "false_positive_if": f"`{a['run']}` が今の版で exit 0 で、{a['file']} が承認の後に変わっていない（sha256 {str(a['sha256'])[:12]}）なら誤り"}
                for a in pend["acceptance"]]
    b.record["process"]["request_findings"] = cur + [{"round": b.round, "origin": SPEC_ORIGIN, "findings": findings}]
    return {"ok": True}


def spec_check(b, nid):
    """承認済みの受け入れ条件のテストが、承認の後に変わっていないか（毎周、修正の後）。変わっていれば人に諮る——
    テストを書いた writer は修正役でもあるので、弱めて緑にしても誰も突き合わせない形を残さない"""
    spec = b.record["process"].get("spec")
    if not spec:
        return {"ok": False, "problems": ["record.process.spec が無い——仕様が固定されていない"]}
    root = pathlib.Path(_repo_root() or ".")
    seen, changed = set(), []
    for a in spec["acceptance"]:
        if a["file"] in seen:
            continue
        seen.add(a["file"])
        now_sha = _file_sha(root, a["file"])
        if now_sha != a["sha256"]:
            changed.append({"file": a["file"], "from": a["sha256"], "to": now_sha})
    if not changed:
        return {"ok": True}
    b.loop_state["spec_changed"] = changed
    return {"decision": "ask", "reason": "spec_changed", "ask": {
        "kinds": ["spec_changed"], "in_round": True,
        "question": ("承認済みの受け入れ条件のテストのファイルが、承認の後に変わった。変更を承認し直すか（continue --note <確かめたこと>。"
                     "新しい sha を記録に固定し、変更の履歴を process.spec.amendments に残す）、run をここで止めるか（stop）"),
        "items": [f"{c['file']}: sha256 {str(c['from'])[:12]} → {str(c['to'])[:12] if c['to'] else '消えた'}" for c in changed],
        "options": ["continue", "stop"]}}


CONDS.update({"spec_flow": spec_flow, "spec_revise_due": spec_revise_due})
BUILTINS.update({"spec_approve": spec_approve, "spec_freeze": spec_freeze, "spec_check": spec_check})
POST_CHECKS.update({"spec_write_output": spec_write_output, "spec_review_output": spec_review_output,
                    "spec_revise_output": spec_revise_output})


# ---------------------------------------------------------------- 人の決定権の関所（能力の後退・人の方針）
# 今ある能力を減らす取捨と、人の方針にぶつかる案は、役（判定役・審査役・修正役）が代償として決めない——並んだら必ず人に聞く。
# 機械は「目的や依頼が名指しした削除か」を判定しない（それも取捨の判断なので人に回す）。
# 修正差分の審査は削除を cite できず、手直しの義務に入ると人より先に修正役が決めるので、修正の後の後退と方針とのぶつかりは、
# 累積差分を BASE と比べる R4 が受ける。
# 事前審査の穴のうち人に聞く語の一覧の正本（graph の $defs.face_kind の enum の部分集合。部分集合であることは pytest の
# test_policy_gate が見る）。事前審査と修正差分のレビューの enum に割らないのは、engine の schema が anyOf を読まないので、
# 割ると共通の語を 2 つの enum に写すことになるから
HUMAN_FACE_KINDS = ("regression", "policy")
# 事前審査だけが書く語（修正差分のレビューは受け付けで拒む）。precedent は、案が採る判定者の先行例の出典を事前審査が開いて
# 確かめた食い違い——判定者の先行例は修正差分のレビューに渡らないので、その節には確かめる材料が無い
PLAN_ONLY_FACE_KINDS = HUMAN_FACE_KINDS + ("precedent",)


def _policy_change(b):
    return policy_input.change(b, git, b.record["process"].get("policy") or {})


def _plan_gate_items(b):
    items = []
    for i, p in enumerate((b.output_of_round("p2.fix_plan", b.round) or {}).get("plan") or []):
        items += [("regression", f"修正案 {i + 1} が狭める能力: {n['what']}——{n['why']}") for n in p.get("narrows") or []]
    items += [(f["kind"], f"事前審査の穴 [{f['kind']}] {f['key']}: {f['why']}")
              for f in (b.output_of_round("p2.plan_review", b.round) or {}).get("faces") or [] if f["kind"] in HUMAN_FACE_KINDS]
    return items


R4_ROWS = (("regression", "lost", "R4 が BASE から消えたと見た能力: "), ("policy", "policy_conflicts", "R4 が見た人の方針とのぶつかり: "))


def _r4_gate_items(b):
    passed = {a for h in b.record["process"]["human_items"] if h.get("answer") == "continue" for a in h.get("asked") or []}
    out = b.output_of_round("r4.hidden_scope", b.round) or {}
    got = {"lost": (out.get("capability_inventory") or {}).get("lost") or [], "policy_conflicts": out.get("policy_conflicts") or []}
    return [(kind, row) for kind, field, head in R4_ROWS for row in (head + x for x in got[field]) if row not in passed]


HUMAN_GATES = {"p2.human_gate": _plan_gate_items, "r4.human_gate": _r4_gate_items}


def human_gate(b, nid):
    """能力の後退・方針とのぶつかり・方針の文書の変化が 1 件でも在れば、人に聞く（周の途中の問い）。無ければ素通り"""
    rows = HUMAN_GATES[nid](b)
    ch = _policy_change(b)
    if ch:
        b.loop_state["policy_change"] = ch
        rows.append(("policy_changed", policy_input.change_row(ch)))
    if not rows:
        return {"ok": True}
    kinds = sorted({k for k, _ in rows})
    return {"decision": "ask", "reason": "human_gate", "ask": {
        "kinds": kinds, "in_round": True,
        "question": ("今ある能力を減らす・狭める変更、人の方針とぶつかる変更、または方針の文書そのものの変更が挙がった。役は代償として決めない"
                     "——人が決める。通すなら continue --note <通す範囲と条件>（答えは記録の process.human_items に残り、修正役に届く。"
                     "方針の文書の変更を通すと、その版を固定し直す）。通さないなら stop（run をここで止める。直す向きを決めてから新しい run で）"),
        "items": [r for _, r in rows], "options": ["continue", "stop"]}}


def human_gate_answered(b, ph, ans):
    b.record["process"]["human_items"].append({"round": b.round, "kinds": ph.get("kinds") or [], "asked": ph["items"],
                                               "answer": ans, "note": ph.get("note", ""), "node": ph["node"]})
    ch = b.loop_state.pop("policy_change", None)
    if ans == "continue" and ch and "policy_changed" in (ph.get("kinds") or []):
        pol = b.record["process"]["policy"]
        pol.setdefault("amendments", []).append({**ch, "round": b.round, "note": ph.get("note", "")})
        pol["path"], pol["sha256"], pol["copy"] = ch["path"], ch["to"], ch["to_copy"]
        b.state["inputs"]["policy_md"] = ch["path"] if ch["to"] else None


BUILTINS.update({"human_gate": human_gate})
