"""research-loop の rules——graphs/research-loop.json に書けない算術だけを持つ。

engine（scripts/loop.py）が graph の名前で呼ぶ。ここにあるのは:
  init_record   記録の初期形（欄の正本は convergence-loops の scripts/research-record.py）
  FAN_OUT       扇の項目の選び方（照合が要るクラスタ・反証が要る主張・抜き取りの無作為選定）
  WRITE_OPS     記録の形に固有の書き込み（クラスタの件数を機械が数える等）
  BUILTINS      機械の節（件数突合・収束判定）
  POST_CHECKS   節ごとの整合（型では書けない規則）。out を検査・補うだけで record は触らない（記録を書くのは WRITE_OPS）
  check_record  判定ごとの必須欄と出典（検証器と同じ規則を done の時点で当てる）
  finalize      報告の前の仕上げ（段ごとの『走らせない』理由・未反証の荷重の申告・未照合の主張の退避）
  on_answer / on_unattended / on_thickness / add   人に聞いた後・無人・昇格・外から足す

engine が差し込む道具は engine/rules.py の INJECT が正本（rules は engine を import しない）。
節名（p1.checker 等）はここには出ない——節の役割は graph が名前で指す。
"""
import json
import os
import pathlib
import random

GATES = ("rederiver", "cold_reader", "cartographer")
# 検証器（research-record.py）の定数は validator_module(b) で読む——engine（engine/rules.py の INJECT）が差し込む。
# 以前ここに在った VERDICTS / VERDICT_FIELDS は検証器と同じ知識の写しで、形が既にずれていた（判定→欄 1 つ vs 判定→欄の組）


# ---------------------------------------------------------------- 記録の初期形
def init_record(thickness, decider):
    return {
        "question": "", "thickness": thickness, "thickness_decider": decider, "constraints": [], "clusters": [], "claims": [],
        "corrections": [], "terms": [], "numbers": [],
        "gates": {k: {"status": "not_applicable", "reason": "未実行"} for k in GATES},
        "sampling": {"status": "not_applicable", "reason": "未実行"},
        "convergence": {"rounds_total": 1, "consecutive_zero": 0, "outcome": "stopped", "stopped_reason": "実行中"},
        "process": {"rerolls": 0, "unrefuted_load_bearing": [], "human_items": []},
        "decisions": {"decide_now": [], "poc": [], "human_only": []},
    }


# ---------------------------------------------------------------- 扇の項目
def clusters_needing_check(b, nid):
    """判定の無い主張と recheck の付いた主張を、クラスタごとに束ねる（2 周目以降の経済）。"""
    by = {}
    for c in b.record["claims"]:
        if c.get("cluster") and (c.get("verdict") is None or c.get("recheck")):
            by.setdefault(c["cluster"], []).append(pick(c, ["id", "claim", "load_bearing"]))
    return [{"key": k, "claims": v} for k, v in sorted(by.items())]


def claims_needing_refute(b, nid):
    """相違（判定自体を疑う）と荷重の確証（崩す証拠を探す）。反証を経ていないものだけ。"""
    items = []
    for c in b.record["claims"]:
        if c.get("refuted"):
            continue
        if c.get("verdict") == "相違":
            mode = "dispute"
        elif c.get("verdict") == "確証" and c.get("load_bearing"):
            mode = "confirm"
        else:
            continue
        it = pick(c, ["id", "claim", "verdict", "evidence", "sources", "correction", "conditions", "load_bearing"])
        it.update({"key": c["id"], "mode": mode})
        items.append(it)
    return items


def sampling_pick(b, nid):
    """無作為に 1〜2 割（run と周で決まる種）。回す側の裁量を挟まない。周の中で選び直さない。"""
    V = validator_module(b)
    ls = b.loop_state
    key = f"sampled_r{b.round}"
    claims = b.record["claims"]
    if key in ls:
        chosen = [c for c in claims if c["id"] in ls[key]]
    else:
        pool = [c for c in claims if c.get("verdict") in V.CHECKED_VERDICTS and not c.get("recheck")]
        if not pool:
            return []
        rng = random.Random(f"{b.state['run_id']}:{b.round}")
        chosen = rng.sample(pool, max(1, round(len(pool) * 0.15)))
        ls[key] = [c["id"] for c in chosen]
    return [{"key": "sample", "claims": [pick(c, ["id", "claim", "load_bearing"]) for c in chosen]}]


FAN_OUT = {"clusters_needing_check": clusters_needing_check, "claims_needing_refute": claims_needing_refute, "sampling_pick": sampling_pick}
# **無作為に項目を引く扇。** 引く物が run ごとに変わるので、そこから返る値は台本の性質ではない
# ——覆いの測定（判定語彙の到達）はこの扇の節を数えない。数えていたとき、同じ台本で到達が
# 24 と 25 のあいだで揺れた（実測 2026-09-13: 種が run_id＝時刻）。**揺れる柵は無い柵より悪い。**
RANDOM_FAN = ("sampling_pick",)
CONDS = {}


# ---------------------------------------------------------------- 記録の形に固有の書き込み
def clusters_from_ids(b, nid, src, w):
    """件数は機械が数える（claims_submitted ＝ claim_ids の数）。回す側の申告を信じない。"""
    rec = b.record
    by_id = {c["id"]: c for c in rec["claims"]}
    rec["clusters"] = []
    seen = set()
    for cl in src:
        ids = cl["claim_ids"]
        unknown = [i for i in ids if i not in by_id]
        if unknown:
            raise Reject(f"{nid}: クラスタ '{cl['key']}' の claim_ids に無い主張: {unknown}")
        dup = [i for i in ids if i in seen]
        if dup:
            raise Reject(f"{nid}: 主張が複数のクラスタに入っている: {dup}")
        seen |= set(ids)
        rec["clusters"].append({"key": cl["key"], "claims_submitted": len(ids)})
        for i in ids:
            by_id[i]["cluster"] = cl["key"]
    left = [c["id"] for c in rec["claims"] if not c.get("cluster")]
    if left:
        raise Reject(f"{nid}: どのクラスタにも入っていない主張: {left}（照合にかける主張は全部クラスタに入れろ）")


def add_claims_op(b, nid, src, w):
    add_claims(b, src, f"節 {nid}（{b.round} 周目）", nid)


def add_claims(b, claims, origin, where):
    rec = b.record
    ids = {c["id"] for c in rec["claims"]}
    keys = {c["key"]: c for c in rec["clusters"]}
    for c in claims:
        if c["id"] in ids:
            raise Reject(f"{where}: 主張 id '{c['id']}' は既にある")
        ids.add(c["id"])
        if c["cluster"] not in keys:
            rec["clusters"].append({"key": c["cluster"], "claims_submitted": 0})
            keys[c["cluster"]] = rec["clusters"][-1]
        keys[c["cluster"]]["claims_submitted"] += 1
        rec["claims"].append({"id": c["id"], "cluster": c["cluster"], "claim": c["claim"], "load_bearing": bool(c["load_bearing"]),
                              "added_by": origin, "added_round": b.round,
                              **({"origin_note": c["origin"]} if c.get("origin") else {}),
                              **({"heuristic": c["heuristic"]} if c.get("heuristic") else {})})


def flag_recheck(b, nid, src, w):
    by_id = {c["id"]: c for c in b.record["claims"]}
    for i in src:
        if i not in by_id:
            raise Reject(f"{nid}: recheck に無い主張 id: {i}")
        by_id[i]["recheck"] = True


def claim_updates(b, nid, src, w):
    by_id = {c["id"]: c for c in b.record["claims"]}
    for u in src:
        if u["id"] not in by_id:
            raise Reject(f"{nid}: claim_updates に無い主張 id: {u['id']}")
        by_id[u["id"]]["claim"] = u["claim"]
        by_id[u["id"]]["recheck"] = True


def cold_reader_round(b, nid, src, w):
    g = b.record["gates"]["cold_reader"]
    if "rounds" not in g:
        b.record["gates"]["cold_reader"] = g = {"rounds": []}
    g["rounds"].append({"verdict": src["verdict"], "findings": len(src.get("findings", [])), "round": b.round})


def sampling_overturn(b, nid, src, w):
    """覆りは機械が数える（元の判定と比べる）。元の判定は役に渡していない。writes の op——記録を書く経路は writes 1 本。"""
    out, item = src, w.get("_item") or {}
    by_id = {c["id"]: c for c in b.record["claims"]}
    overturned = []
    for f in out["findings"]:
        c = by_id.get(f["id"])
        if c is None:
            raise Reject(f"抜き取りに無い主張 id: {f['id']}")
        if c.get("verdict") != f["verdict"]:
            overturned.append(f["id"])
            c["recheck"] = True
            c["sample_verdict"] = f["verdict"]
    b.record["sampling"] = {"status": "done", "sampled_ids": [x["id"] for x in item["claims"]], "overturned": len(overturned),
                            "overturned_ids": overturned, "round": b.round}

def decisions_from_details(b, nid, src, w):
    """3 分類の見出しを記録へ（writes の op。post_check は out を検査するだけで record を触らない）。"""
    dec = b.record["decisions"]
    for k in ("decide_now", "poc", "human_only"):
        dec[k] = [d["text"] for d in src[k]]
    if not any(dec.values()):
        raise Reject("decisions が全部空——3 分類に仕分けろ（P5）")


WRITE_OPS = {"sampling_overturn": sampling_overturn, "decisions_from_details": decisions_from_details, "clusters_from_ids": clusters_from_ids, "add_claims": add_claims_op, "flag_recheck": flag_recheck,
             "claim_updates": claim_updates, "cold_reader_round": cold_reader_round}
# research の記録に素材（materials）は無い——どの op も to を素材の名前として読まない（graphcheck が op ごとの名乗りを求める）
for _op in WRITE_OPS.values():
    _op.writes_material = False


# ---------------------------------------------------------------- 機械の節
def count_check(b, nid):
    """クラスタ欄と判定数の等式・相違の反証・荷重確証の反証。この周の『新規の相違』をここで確定する。"""
    rec = b.record
    problems = []
    for cl in rec["clusters"]:
        got = [c for c in rec["claims"] if c.get("cluster") == cl["key"]]
        judged = [c for c in got if c.get("verdict") is not None and not c.get("recheck")]
        # この周に足された未照合の主張（ループの外から add した等）は次の周の仕事——等式から外す
        deferred = [c for c in got if c.get("verdict") is None and c.get("added_round") == b.round]
        if len(judged) + len(deferred) != cl["claims_submitted"]:
            problems.append(f"クラスタ '{cl['key']}' は {cl['claims_submitted']} 件だが判定は {len(judged)} 件（次の周へ回す未照合 {len(deferred)} 件を除く）")
    for c in rec["claims"]:
        if c.get("verdict") == "相違" and not c.get("refuted"):
            problems.append(f"相違 '{c['id']}' が反証を経ていない")
        if c.get("verdict") == "確証" and c.get("load_bearing") and not c.get("refuted"):
            problems.append(f"荷重の確証 '{c['id']}' が反証を経ていない")
    if problems:
        return {"ok": False, "problems": problems}
    new, stuck = [], b.loop_state.setdefault("stuck_ids", [])
    for c in rec["claims"]:
        if c.get("verdict") == "相違":
            first = c.get("first_discrepant_round")
            if first is None:
                c["first_discrepant_round"] = b.round
                new.append(c["id"])
            elif c.get("checked_round") == b.round and first < b.round and c["id"] not in stuck:
                stuck.append(c["id"])
    b.rd["new_discrepancies"] = len(new)
    b.rd["new_discrepancy_ids"] = new
    return {"ok": True, "new_discrepancies": len(new), "ids": new}


def gate_failures(b):
    V = validator_module(b)
    rec, th = b.record, b.state["thickness"]
    g = rec["gates"]
    fails = []
    if th in V.GATED_THICKNESS:
        v = g["rederiver"]
        if v.get("status") == "not_applicable" or v.get("verdict") != "pass":
            fails.append(f"rederiver: {v.get('verdict', '未実行')}")
        cr = g["cold_reader"]
        # 直近 1 周でなく「最後に再設計を求めた周より後に pass が在るか」を見る。直近だけだと、
        # 再設計要求のあとに 1 回 pass が返れば過去の要求が消える（本文を直していなくても消える）。
        rounds = cr.get("rounds") or []
        last_bad = max((i for i, r in enumerate(rounds) if r["verdict"] != "pass"), default=None)
        passed_after = last_bad is not None and any(r["verdict"] == "pass" for r in rounds[last_bad + 1:])
        if not rounds:
            fails.append("cold_reader: 未実行")
        elif last_bad is not None and not passed_after:
            fails.append(f"cold_reader: {rounds[last_bad]['verdict']}（{rounds[last_bad]['round']} 周目の要求が未解消）")
        elif rounds[-1]["verdict"] != "pass":
            fails.append(f"cold_reader: {rounds[-1]['verdict']}")
    if th == "重厚":
        v = g["cartographer"]
        if v.get("status") == "not_applicable" or v.get("verdict") != "pass" or v.get("new_blind_spots", 1) > 0:
            fails.append(f"cartographer: {v.get('verdict', '未実行')}・新規盲点 {v.get('new_blind_spots', '?')}")
    return fails


def stop(b, reason):
    conv = b.record["convergence"]
    conv["outcome"] = "stopped"
    conv["stopped_reason"] = reason
    return {"decision": "stopped", "reason": reason}


def converge(b, nid):
    """round.converge の機械版。判断は 4 つ: converged / next_round / stopped / ask。"""
    st, rec, rd, ls = b.state, b.record, b.rd, b.loop_state
    th = st["thickness"]
    conv = rec["convergence"]
    new = rd.get("new_discrepancies")
    if new is None:
        raise Reject(f"{nid}: 件数突合が走っていない")
    zero = new == 0
    conv["consecutive_zero"] = (conv["consecutive_zero"] + 1) if zero else 0
    conv["rounds_total"] = b.round
    smp = rec["sampling"]
    overturned = smp.get("overturned", 0) if smp.get("status") == "done" and smp.get("round") == b.round else 0
    if overturned:
        conv["consecutive_zero"] = 0
    fails = gate_failures(b) if zero else ["この周に新規の相違がある（ゲートは回していない）"]
    pending = [c["id"] for c in rec["claims"] if c.get("verdict") is None or c.get("recheck")]

    if th == "軽量":
        return stop(b, "軽量段: 1 ラウンドで打ち切り（収束の宣言はしない。判定の集計と結論・残件だけを出す）")
    # 主張が 0 件の周は収束を名乗らせない——空集合に対する全称条件は全部真になるので、
    # 「何も検証していない周」が『新規相違ゼロ・ゲート pass・pending 空』で収束に見える。
    if not rec["claims"]:
        fails = fails + ["照合の対象になる主張が 1 件も無い（母数ゼロを収束と区別する）"]
    # **柵が空振りした周は収束の条件そのものに入れる。** 前の周はこの判断を下の asks に置いた——
    # asks は収束しない周にしか組み立てられないので、**収束する周には一度も評価されなかった**
    # （名乗りは『収束判定に入れた』なのに、入っていたのは収束しない周だけ）。検算の測り方も
    # 『converge に read_through_unchecked が現れるか』だったので、置いた場所が到達しないことを測れなかった。
    unchecked = b.state.get("read_through_unchecked") or []
    if zero and not fails and not unchecked and conv["consecutive_zero"] >= 2 and not overturned and not pending:
        conv["outcome"] = "converged"
        conv.pop("stopped_reason", None)
        why = f"連続 {conv['consecutive_zero']} 周で新規相違ゼロ、{th} 段のゲートは全部 pass"
        # 開いた問いは収束を止めない（待たない設計）が、『収束』の一語で依頼者に調べ尽くしたと読ませない。
        # 記録が知っているのは P0 で挙がったことだけなので、ループの外で扱ったかまでは言わない
        oq = rec["process"].get("open_questions") or []
        if oq:
            why = (f"閉じた主張の検証は収束した（{why}）。開いた問い {len(oq)} 件はこの run の記録の上では未解決"
                   "——閉じた主張の検証の対象外で、この収束はその答えを意味しない（ループの外で扱ったかは記録に無い。"
                   "報告に並べる）: " + " / ".join(oq))
        return {"decision": "converged", "reason": why}

    asks = []
    if ls.get("stuck_ids"):
        asks.append(("stuck", f"同じ相違が反映後も残っている: {ls['stuck_ids']}——主張側でなく前提側が誤っている可能性。P0 に戻すか"))
    hist = [r.get("new_discrepancies") for r in st["rounds"]]
    if b.round >= 3 and all(x for x in hist[-3:]):
        asks.append(("thrash", f"3 周続けて新規相違が出ている（{hist[-3:]}）——主張の棚卸し（P0-2）が浅い。切り直すか"))
    rv = rec["gates"]["rederiver"]
    if rv.get("verdict") == "redesign-needed":
        ls["rederiver_redesign_rounds"] = ls.get("rederiver_redesign_rounds", 0) + 1
        if ls["rederiver_redesign_rounds"] >= 2:
            asks.append(("zero_base_divergence", "rederiver の redesign-needed が再ラウンド 1 回で解消しない——機械では決められない設計の岐路"))
    if rv.get("verdict") == "unverifiable":
        asks.append(("unverifiable", "問いの独立出典が取れず rederiver が unverifiable——pass でも redesign でもないので収束を宣言できない"))
    # 上の収束の条件が痕跡を見て止めた回に、何が起きたかを人へ出す口（条件は上、説明はここ）
    if unchecked:
        why = unchecked[-1]["why"]
        asks.append(("read_through_unchecked",
                     f"読了の確かめが成立しなかった回が {len(unchecked)} 件ある（最後の理由: {why[:120]}）"
                     "——本文が会話に入ったかを engine が確かめられていないので、収束を機械で宣言できない"))
    pd = rec["process"].get("prior_decisions")
    if zero and isinstance(pd, dict) and pd.get("checked") is False:
        asks.append(("prior_decisions_unchecked", "先行議論を洗えていない——決着済みの蒸し返しの可能性が残る。『重複なし』に丸めない"))
    if b.round >= st["max_rounds"]:
        # **上限でも諮る。** 以前はここで `stop` に倒しており、直前に組み立てた `asks` を捨てていた
        # ——依頼者が「続けろ」と答える受け口が無く、`loop.py patch --path state.*` しか道が残らない。
        # 何を聞かれて続行したかも記録に残らなかった（実測 2026-09-14: review 側は同じ欠陥を直したのに
        # research 側だけ残っていた＝**知見が片側にしか当たっていない**）。延長は 1 周だけ（on_answer が上げる）。
        asks.append(("max_rounds", f"総ラウンドが上限 {st['max_rounds']} に達した（収束せず）"
                                   "——上限を 1 周だけ延ばして続けるか、未収束のまま報告へ進むか"))
        return {"decision": "ask", "reason": "; ".join(k for k, _ in asks), "ask": {
            "kinds": [k for k, _ in asks],
            "question": f"上限 {st['max_rounds']} 周に達した。次のどれにするか"
                        "（continue: 上限を 1 周だけ延ばして次の周へ／stop: 未収束のまま報告へ）",
            "items": [f"{k}: {t}" for k, t in asks],
            "options": ["continue", "stop"]}}
    can_escalate = bool(b.tiers) and st.get("thickness") != b.tiers[-1]
    if asks:
        return {"decision": "ask", "reason": "; ".join(k for k, _ in asks), "ask": {
            "kinds": [k for k, _ in asks],
            "question": "収束していない。次のどれにするか（continue: 次の周へ／stop: 未収束のまま報告へ"
                        + ("／escalate: 重厚に上げて次の周へ" if can_escalate else "") + "）",
            "items": [f"{k}: {t}" for k, t in asks],
            # 最上段では escalate を出さない——出しても answer が『降格は許さない』で拒み、取れない選択肢になる
            "options": ["continue", "stop"] + (["escalate"] if can_escalate else []),
        }}
    if new:
        why = f"新規相違 {new} 件"
    elif fails:
        why = "ゲート未 pass: " + "; ".join(fails)
    elif pending:
        why = f"照合前・再照合待ちの主張がある: {pending}"
    else:
        why = f"連続ゼロ {conv['consecutive_zero']} 周（2 周で収束）"
    return {"decision": "next_round", "reason": why}


BUILTINS = {"count_check": count_check, "converge": converge}


# ---------------------------------------------------------------- 節ごとの整合
def refuter_consistency(b, nid, out, item):
    m, up, v = out["mode"], out["upheld"], out["verdict"]
    if m == "dispute" and up != (v == "相違"):
        raise Reject(f"refuter の整合: mode=dispute では upheld={up} と verdict={v} が食い違う（相違が本物なら upheld=true・verdict=相違）")
    if m == "confirm" and up != (v == "確証"):
        raise Reject(f"refuter の整合: mode=confirm では upheld={up} と verdict={v} が食い違う（確証が崩れなければ upheld=true・verdict=確証）")
    if item and out["id"] != item["id"]:
        raise Reject(f"refuter が別の主張 id を返した: {out['id']}（項目は {item['id']}）")


def cold_reader_consistency(b, nid, out, item):
    if (out["verdict"] == "pass") != (len(out["findings"]) == 0):
        raise Reject("cold-reader の整合: 所見があるなら redesign-needed、無いときだけ pass")


def cartographer_count(b, nid, out, item):
    out["new_blind_spots"] = len(out["spots"])
    if any(s.get("affects_conclusion") for s in out["spots"]) and out["verdict"] == "pass":
        raise Reject("cartographer 比較係の整合: 結論に影響する盲点があるのに pass")



def load_zero_reason(b, nid, out, item):
    if out.get("load_zero_reason"):
        b.loop_state["load_zero_reason"] = out["load_zero_reason"]


# 読了の確かめ。**engine が回す側のセッションの転写を読み、文書の本文が会話に入った痕跡を探す。**
# 回す側に何かを書かせて確かめる形（末尾の一文の逐語引用）は、末尾に到達したことしか示せなかった。
# 転写には道具の結果がそのまま残るので、Read でも cat でも sed でも、本文が会話に入れば痕跡が残る
# ——読み方の綴りを engine が知る必要が無い。実測 2026-09-18: 全文を 1 度読んだ文書は 3 標本とも hit、
# 部分しか見ていない文書は中間だけ hit、engine が別プロセスで読んだだけの文書は 3 標本とも miss。
# **射程の正本はここ 1 か所**（プロンプトも手順書も拒否文も、これより強いことを言ってはいけない）。
# engine が確かめているのは 1 つだけ——**CLAUDE_CODE_SESSION_ID が指す転写 1 本の中に、この run の
# run_id と 3 標本が同居するか**。それ以上は読まない:
#   - その転写が「親のもの」か「subagent のもの」かを、engine は判定していない
#     （判定の材料になる欄を 1 つも読まない。isSidechain も子の session id も参照は 0 件）。
#   - 照合は部分一致なので、同じ行が別の道具の出力に在れば読まずに立つ（読了の証明ではない）。
# 「回す側そのものが subagent なら成立しない」は engine の保証ではなく、**ハーネスが subagent の
# 道具の結果を親の転写へ書かない**という置き場の性質に乗った観測である（その性質は engine の外に在り、
# transcript_path の docstring が『ハーネスの持ち物なので写さない』と書いているもの）。
# ハーネスが置き場の作り方を変えれば、この観測は engine を 1 行も変えずに成り立たなくなる。
PROBE_POINTS = ("先頭", "中間", "末尾")
PROBE_MIN = 12  # 標本に使える行の最短（使い方は read_probes が正本）
# 3 標本が挟む区間が本文（非空行の文字数）に占める割合の下限（**百分率の整数**）。射程を直に測る。
# 0 にはできない——見立て文書はほぼ必ず短い見出しで始まり、先頭の標本の前に数字ぶん残る。
# **整数で持つのは、境界に到達できるようにするため。** 0.95 の小数で持っていたとき 1 - 0.95 が
# 0.050000000000000044 になり、「許容ぴったり」という入力がそもそも作れなかった——つまり境界の
# 腕が書けず、`>` と `>=` の取り違えが検査を素通りした（実測 2026-09-21: 取り違えても全件緑）。
COVER_MIN_PCT = 95


def transcript_path():
    """回す側のセッションの転写と、**見つからなかったときの理由**（見つかれば理由は None）。

    スラグ（置き場の名前）の作り方はハーネスの持ち物なので写さない。session id のファイルを glob で探す。
    **CLAUDE_CONFIG_DIR の既定は ~/.claude**——このリポジトリで同じ env を読む他の 7 か所と同じ形。
    既定を持たなかったとき、旗を渡さない配置では柵が毎回空振りし、それが誰にも見えなかった。
    """
    sid = os.environ.get("CLAUDE_CODE_SESSION_ID")
    cfg = os.environ.get("CLAUDE_CONFIG_DIR") or os.path.expanduser("~/.claude")
    if not sid:
        return None, "CLAUDE_CODE_SESSION_ID が無い（engine を起こした session が分からない）"
    try:
        hit = sorted(pathlib.Path(cfg).glob(f"projects/*/{sid}.jsonl"))
    except OSError as e:
        # **外部の置き場を触る所は全部 3 値の中に閉じる**（素の例外は通過／不成立／不合格のどれでもない）
        return None, f"{cfg} を探せない（{e}）"
    if not hit:
        return None, f"{cfg}/projects/*/{sid}.jsonl に転写が無い"
    if len(hit) > 1:
        # **どれかを機械で選ばない**——別のプロジェクト配下の同名を掴むと、読んでいないのに通る
        return None, "転写が {} 件見つかり、どれがこの session か決められない（{}）".format(
            len(hit), "、".join(str(x) for x in hit))
    return hit[0], None


def tool_result_texts(line):
    """転写の 1 行から **道具の結果の本文だけ** を出す。

    **会話の地の文（役や人が書いた文）は見ない**——engine がループの操作者の会話を読む形にしない。
    探したいのは「文書の本文が道具を通って会話に入ったか」だけなので、これで足りる。
    本文が配列で入る道具も在る（実測 2026-09-18）ので両方を出す。
    """
    try:
        d = json.loads(line)
    except ValueError:
        return []
    if not isinstance(d, dict):
        return []            # 前置フィルタは素の部分一致なので、その語を含む非 dict 行も来る
    # **message の型も見る。** `(d.get("message") or {})` は message が真値の非 dict（文字列・配列）だと
    # そのまま .get を呼んで AttributeError になり、名乗る 3 値の外へ抜けた（トップレベルの型だけ見ていた）
    msg = d.get("message")
    content = msg.get("content") if isinstance(msg, dict) else None
    if not isinstance(content, list):
        return []
    out = []
    for blk in content:
        if not isinstance(blk, dict) or blk.get("type") != "tool_result":
            continue
        x = blk.get("content")
        if isinstance(x, str):
            out.append(x)
        elif isinstance(x, list):
            out += [y.get("text", "") for y in x if isinstance(y, dict)]
    return out


EXTERNAL_MARK = "tool-results/"  # 大きい道具の結果の外出し先（ハーネスが親の転写に残す参照）


def probes_found(path, probes, mark):
    """転写を舐めて（見つかった標本の名前, 見た道具の結果の数, 外出しの参照が在ったか, **この run の印が在ったか**, 読めなかった理由）。

    **欄の型を経路で変えない**——理由を件数の位置に同居させていたとき、読む側は 1 番目が None かを
    先に見ないと型を誤る形だった（呼び出し元は 1 か所なので実害は出ていないが、姉妹の 2 つの関数は
    どちらも『値か理由か』の素直な形である）。

    **印（この run の run_id）を一緒に探すのは、転写が回す側のものかを確かめるため。**
    engine を起こすと必ず run_id が出力に出る（init／next／status の JSON と done の 1 行）ので、回す側が自分で
    engine を回していれば、その道具の結果として印が転写に載る。載っていない転写は**回す側のもので
    はない**（回す側そのものが subagent の配置・出力をファイルへ落とした配置）ので、標本が無くても
    「読んでいない」とは言えない——claims_intake がその回を不合格でなく不成立へ倒す。

    **通る回は全部そろった時点で読むのをやめる。拒む回は最後まで読む**（実測 2026-09-19: 36.9 MB・
    標本がどこにも無い回で 3.86 秒。前置フィルタを入れて約 2.2 倍速くなる）——拒む回は回す側が
    読み直して出し直す経路なので、同じ全走査が毎回繰り返される。上限は置いていない。
    見た数を返すのは、道具の結果が 1 つも無い転写——形が変わった疑い——を「読んでいない」と区別するため。
    外出しの参照を返すのは、**本文が親の転写に残らない形**（大きい結果は別ファイルへ出され、
    参照と先頭の抜粋しか残らない）を「読んでいない」と区別するため。
    """
    found, seen, external, marked = set(), 0, False, False
    try:
        f = open(path, encoding="utf-8", errors="replace")
    except OSError as e:
        # 探した直後に読めない（権限・消えた）——「読んでいない」ではないので不成立へ流す。
        # 素の例外のまま抜けると、claims_intake が名乗る 3 値のどれにも落ちず traceback になる
        return None, 0, False, False, str(e)
    # **反復中の OSError も 3 値の中に閉じる。** 捕まえていたのは open() だけで、読みの途中で
    # 消えた・切れた転写は素の例外のまま抜けた（探した直後に読めない、と同じ扱いにする）
    try:
        with f:
            for line in f:
                if '"tool_result"' not in line:
                    continue  # 道具の結果を含まない行は JSON に起こさない（拒む回は最後まで読むので効く）
                for text in tool_result_texts(line):
                    seen += 1
                    external = external or EXTERNAL_MARK in text
                    marked = marked or mark in text
                    found |= {name for name, probe in probes if name not in found and probe in text}
                    if len(found) == len(probes) and marked:
                        return found, seen, external, marked, None
    except OSError as e:
        return None, seen, False, False, str(e)
    return found, seen, external, marked, None


def sink_hints(path, external):
    """本文が親の転写の外に落ちうる経路（在れば、**拒否文に添える手がかり**）。

    **言えるのは「この session にその経路の跡が在る」ことだけ**——外出しの参照は転写のどこかに
    在れば立ち、subagents/ は置き場の有無しか見ない。この done の読みがその経路を通ったかは分からない
    ので、手がかりは一般的な注意として書き、判定には使わない。

    ハーネスは本文を親の転写だけに置くとは限らない——subagent に読ませれば別の転写へ行き、
    大きい結果は別ファイルへ外出しされて参照しか残らない。**これは判定の材料にしない**——
    置き場が在るかは『その本文がそこに在る』ことを 1 つも示さないので、在るだけで通していたとき、
    文書と無関係な subagent を 1 つ起こした session では柵が二度と不合格を出さなくなった
    （実測: この置き場でループを回した session は 4/4 が subagents/ を持つ）。
    engine が読むのは session id が指す転写 1 本だけで、その転写の由来は判定していない——射程の正本は
    PROBE_POINTS の上の注記で、名乗り（プロンプト・手順書・拒否文）はそこから導く。**どこまで読みに行くかは未決**
    （台帳の fork: 親の転写だけ／兄弟ファイルまで読む）。
    """
    out = []
    sub = path.parent / path.stem / "subagents"
    if sub.is_dir():
        out.append("この session には subagent の転写が在る——subagent に読ませた本文は親の転写に残らないので、"
                   "自分で読み直せ")
    if external:
        out.append(f"この session には大きい道具の結果を別ファイル（{EXTERNAL_MARK}）へ外出しした跡が在る"
                   "——外出しされると親の転写には抜粋しか残らないので、分けて読むか小さく読み直せ")
    return out


def read_probes(text):
    """文書の先頭・中間・末尾から 1 行ずつと、**標本にできなかった理由**（取れれば理由は None）。

    **射程（3 標本が挟む区間が本文をどれだけ覆うか）を実装の副作用でなく直に測る。** 標本を「長さの
    下限を満たす行」の中から位置で選んでいたとき、下限未満の行だけが並ぶ区間——箇条書き・表・参考文献で
    終わる末尾、40 字の行を持たない中ほど——が何行あっても射程の外に残り、7.7%／39%／41% しか読んで
    いない回が通った（実測 2026-09-19）。長さは標本の選び方ではなく、成立／不成立の境目にだけ使う。

    位置も量も**行数でなく文字数**で測る（短い行が並ぶ区間は行数では重く、文字数では軽い）。
    不成立へ倒す 4 つ——①標本にできる行が 1 つも無い ②標本が挟めない区間が本文の COVER_MIN_PCT% を割る
    ③本文の中ほどの帯に標本にできる行が無い ④3 本が相異ならない。どれも不合格ではない（文書の側の
    性質で、読んだかどうかの証拠にならないだけ）。
    """
    live = [ln for ln in (line.strip() for line in text.splitlines()) if ln]
    total = sum(len(ln) for ln in live)
    if not total:
        return [], "本文に非空行が 1 つも無い"
    usable = [k for k, ln in enumerate(live) if len(ln) >= PROBE_MIN]
    if not usable:
        return [], f"{PROBE_MIN} 字以上の行が 1 つも無い"
    start, acc = [], 0
    for ln in live:                          # 各行が本文の何字目から始まるか（位置の物差し）
        start.append(acc)
        acc += len(ln)
    center = lambda k: start[k] + len(live[k]) / 2
    head, tail = usable[0], usable[-1]
    before, after = start[head], total - start[tail] - len(live[tail])
    # 射程外を数える 1 つの式。**両辺を整数にして比べる**（小数を掛けると境界が到達できない値になる）
    if (before + after) * 100 > total * (100 - COVER_MIN_PCT):
        return [], (f"標本の外に {before + after} 字（本文の {(before + after) * 100 // total}%）が残る"
                    f"——先頭の標本の前に {before} 字、末尾の標本の後ろに {after} 字。"
                    f"{PROBE_MIN} 字未満の行だけが並ぶ区間は標本にできない")
    band = [k for k in usable if total / 3 <= center(k) <= total * 2 / 3]
    if not band:
        return [], f"本文の中ほど（{total // 3}〜{total * 2 // 3} 字目）に {PROBE_MIN} 字以上の行が 1 つも無い"
    mid = min(band, key=lambda k: abs(center(k) - total / 2))
    picked = [live[head], live[mid], live[tail]]
    if len(set(picked)) < len(PROBE_POINTS):
        return [], (f"{len(PROBE_POINTS)} 点の標本が {len(set(picked))} 種しか相異ならず、"
                    "先頭・中間・末尾が同じ行になる")
    return list(zip(PROBE_POINTS, picked)), None


def read_through_unchecked(b, nid, why):
    """**検査が成立しなかった**ことを盤面に積む（黙って通さない）。

    早期離脱の経路ごとに手で分岐していたとき、痕跡が残るのは 3 本のうち 1 本だけで、
    その 1 本も record にも報告にも出なかった（engine/advance.py の slim_item が同じ規律を書いている）。
    finalize が record.process へ写し、engine の traces() が報告に出す（unevaluable と同じ形）。
    """
    b.state.setdefault("read_through_unchecked", []).append({"node": nid, "round": b.round, "why": why})
    # **回す側にもその場で見せる。** 痕跡が finalize の件数にしか出なかったとき、柵が空振りした回と
    # 確かめられた回が done の出力では同じに見えた（周の途中では誰も気づけない）
    return f"読了は確かめられなかった（記録に残す）: {why}"



def claims_intake(b, nid, out, item):
    """棚卸しの受け取り: 文書の本文が会話に入った印を転写で探し、開いた問いがあれば回す側に渡す。

    **確かめるのは「読んだ」でなく「本文が会話に入った」**。読んで理解したかは測れないが、
    engine が貼るのをやめた以上、本文が回す側の文脈を通ったことは転写でしか確かめられない。

    判定は 3 値——通過／**不成立**（確かめられない。理由を盤面に積んで通し、done の出力にも出す）／
    不合格（Reject）。不成立に落ちる分岐は read_through_unchecked を呼ぶ全経路で、どれも 1 か所へ
    流すのは黙って通る経路を作らないため（件数をここに写さない——増えた周に名乗りだけ古くなる）。
    """
    # **同じ周に 2 度走査しない。** 確かめは同じ波の 2 節（p0.claims / p0.terms）に付いており、
    # 転写は単調に育つので拒否が続く周ほど全走査が重くなる（実測: 36.9 MB で 3.86 秒 × 2 節）。
    # 柵はどちらの節にも当て続けたまま、**2 度目は盤面に残した結果を読む**——節から外すと、
    # 片方の post_check が落ちても誰も気づかない形になる。
    # 周が変われば読み直す（周をまたいで使い回すと、その周に読んだかを見ていないことになる）。
    # **鍵は「何を確かめたか」**（周・文書の綴りと大きさ・転写の綴り）。周だけを鍵にすると、
    # 文書や session が節のあいだで差し替わった回に、確かめていない物を確かめた扱いにしてしまう。
    doc = (b.state.get("inputs") or {}).get("document")
    tp, no_transcript = transcript_path()
    try:
        size = pathlib.Path(doc).stat().st_size if doc else None
    except OSError:
        size = None
    # **写しは盤面の外のファイルに置く。** 盤面に書いていたとき、**拒まれた done は盤面を保存しない**ので
    # 拒む回（＝転写を最後まで読む、いちばん重い回）が 1 つも覆えなかった——処方が正当化に使った経路を
    # 1 つも覆っていない形だった（実測 r8: R1 最小性が反証し、writer が現物で確かめた）。
    # **フックの状態も鍵に入れる。** 入れていなかったとき、不成立を写した後に同じ周で
    # フックの記録が出来ても（＝文書を読んでも）、2 節目は写しの「確かめられなかった」を読み続けた
    # ——拒否を写すと再提出が塞がるのと同じ形で、**読んだ次の手が通らない**（実測 r10）。
    hook, hook_why = hook_evidence(b.dir, doc) if doc else ("none", "見立て文書の入力が無い")
    memo = b.dir / "read-through.json"
    scope = [b.round, doc, size, str(tp), hook]
    try:
        cached = read_json(memo) if memo.is_file() else None
    except Exception:                       # noqa: BLE001 — 写しが読めないなら走査し直すだけ
        cached = None
    # **写しに当たっても、この節の出力から出る一言は出す。** 早期 return にしていたとき、
    # 確かめの結果と一緒に**節ごとの導線（開いた問いを deep-research へ渡す一文）まで消えた**
    # ——写しに当たるのは同じ波の後から done した側で、開いた問いを持つのは p0.claims だけなので、
    # p0.terms を先に done した周はその導線が 1 度も出なかった（実測 r9）。
    # 確かめの結果だけを写しから取り、後段の合流は必ず通す。
    note, skip_scan = None, False
    if cached and cached.get("scope") == scope:
        note, skip_scan = cached.get("note"), True
    if skip_scan:
        pass                                  # 走査は済んでいる（写しの結果を上で受け取った）
    elif not doc:
        # 4 つ目の経路。今は入口（required_inputs_missing）が止めるので到達しないが、
        # post_check を別の graph へ付け替えた周に静かに素通りするのを防ぐ
        note = read_through_unchecked(b, nid, "見立て文書の入力（inputs.document）が無い")
    else:
        try:
            body = pathlib.Path(doc).read_bytes().decode("utf-8", "replace")
        except OSError as e:
            raise Reject(f"{nid}: 見立て文書 {doc} を読めない（{e}）")
        probes, no_probe = read_probes(body)
        if hook == "read":
            # **一次情報が在る回は転写を開かない。** フックは読んだその瞬間に書くので、
            # 転写の「書き込みは後追い」という制約も、外出し（tool-results/）の見分けも要らない
            note = None
        elif no_probe:
            note = read_through_unchecked(b, nid, f"{doc} から標本を取れない: {no_probe}")
        elif tp is None:
            note = read_through_unchecked(b, nid, f"session の転写が読めない: {no_transcript}")
        else:
            # **印は run_id**（engine のどの出力にも載り、直列化で綴りが変わらない）。盤面のパスを
            # 印にしていたとき、出力は json.dumps を通るので Windows の区切りが二重化され、印が
            # 恒久的に一致せず柵が黙って通る側へ倒れた（実測 2026-09-19: 判定者が現物で特定）
            found, seen, external, marked, unreadable = probes_found(tp, probes, str(b.state.get("run_id") or b.dir))
            missing = [] if found is None else [name for name, _ in probes if name not in found]
            if found is None:
                note = read_through_unchecked(b, nid, f"転写 {tp} を開けない（{unreadable}）")
            elif not seen:
                note = read_through_unchecked(b, nid, f"転写 {tp} に道具の結果が 1 つも無い（転写の形が変わった疑い）")
            elif missing and not marked:
                # **この転写は回す側のものではない。** engine を回せば盤面のパスが道具の結果として
                # 必ず載るので、印が 1 つも無い転写に標本が無くても「読んでいない」とは言えない
                # （回す側そのものが subagent の配置・engine の出力をファイルへ落とした配置）。
                # 不合格にすると、その配置には**柵を切る以外の出口が無くなる**——不成立にして痕跡を残す
                note = read_through_unchecked(b, nid, f"転写 {tp} に、この run を回した出力（run {b.state.get('run_id')}）が 1 つも無い"
                                               "——engine が読んでいるのは回す側の転写ではない"
                                               "（回す側そのものが subagent／出力をファイルへ落としている）。"
                                               "engine を回した出力が会話に残る場から回し直せ")
            elif not marked:
                # **どの条件にも当たらない入力を黙って通さない。** 以前はここが無く、標本が全部そろえば
                # 印を一度も見ずに合格していた——3 標本が親の転写の**別の道具の結果**にたまたま在れば
                # （probes_found の docstring がその可能性を認めている）、印を問わず通る経路だった。
                # 名乗り（印は転写が回す側のものかを確かめるため）は成功側でも印を見ると言っている。
                note = read_through_unchecked(b, nid, f"転写 {tp} に標本はそろったが、この run を回した出力"
                                              f"（run {b.state.get('run_id')}）が 1 つも無い"
                                              "——同じ字列が別の道具の結果に在っただけの可能性を engine は切り分けられない")
            elif missing:
                # **判定は本文の在処だけで下す。** 置き場が在るかは証拠にならないので、抜け道の
                # 手がかり（sink_hints）は拒否文に添えるだけにする——添えるのは、読み直し方が
                # 場合によって違うから（subagent でなく自分で読む／大きい結果は分けて読む）
                hints = sink_hints(tp, external)
                # **拒否は写さない。** 一度は「拒む回こそ重いから写す」と書いたが、実走で壊れた
                # （実測 2026-09-21: 文書を読んでから出し直しても、同じ周では写しが先に拒み続けた）——
                # 拒否の直後に回す側がすることはまさに『文書を読んでもう一度出す』で、**その回は
                # 読み直さなければならない**。読んだことは鍵（周・文書・転写の綴り）に現れないので、
                # 写すと再提出の道が同じ周の間ずっと塞がる。
                # したがって走査が 1 回で済むのは通る回だけで、**拒む回は節ごとに全走査する**。
                # これは取りこぼしではなく、再提出を成立させるために必要な費用である。
                raise Reject(f"{nid}: 見立て文書の {' と '.join(missing)} が、この session の親の転写の道具の結果に入っていない"
                             f"——engine は本文を貼らないので、{doc} を自分で読んでから出し直せ"
                             f"（大きい文書は Read が途中で切れる。続きを読め）。"
                             # 実行でだけ出る形: 代役は同期で書くので検査では一生出ない（test_double_fidelity）
                             f"**転写への書き込みは後追い**なので、読みと done を同じ道具呼びに並べた回は"
                             f"まだ載っていない——読んだ**次の手**で出し直せ。見た転写: {tp}"
                             # **なぜ転写を読んでいるのかを見せる。** フックの記録が在れば転写は開かないので、
                             # ここに来たのは「記録が無い／この文書の全文読みが無い」のどちらかである
                             f"（フックの一次情報は使えなかった: {hook_why}）"
                             + ("。" + " / ".join(hints) if hints else ""))
    # 確かめの結果だけを残す（開いた問いの一言は節ごとに違うので、下で足す）
    if not skip_scan:
        write_json(memo, {"scope": scope, "note": note})
    if out.get("open_questions"):
        note = " / ".join(x for x in (note, "開いた問いがある: " + " / ".join(out["open_questions"]) +
                                      "——P1（閉じた主張の検証）では解けない。ループの外で deep-research に委ね、"
                                      "持ち帰った事実主張は loop.py add で次の周に入れる") if x)
    return note


def clear_stuck_hint(b, nid, out, item):
    b.loop_state["stuck_hint"] = False


POST_CHECKS = {"refuter_consistency": refuter_consistency, "cold_reader_consistency": cold_reader_consistency,
               "cartographer_count": cartographer_count,
               "load_zero_reason": load_zero_reason,
               "claims_intake": claims_intake, "clear_stuck_hint": clear_stuck_hint}


def check_record(b, nid=None):
    errs = []
    V = validator_module(b)
    for c in b.record["claims"]:
        v = c.get("verdict")
        if v is None:
            continue
        if v not in V.VERDICTS:  # 知らない判定語は「要求欄なし＝合格」に倒れていた（review 側と同じ形に）
            errs.append(f"主張 '{c['id']}' の verdict が語彙に無い: {v!r}（{'/'.join(V.VERDICTS)}）")
            continue
        # 検証器の表は判定 → 要る欄の組（tuple）。rules に在った写しは判定 → 欄 1 つの dict で、形が既にずれていた
        for need in (V.VERDICT_FIELDS[v].fields if v in V.VERDICT_FIELDS else ()):
            if not (isinstance(c.get(need), str) and c[need].strip()):
                errs.append(f"主張 '{c['id']}'（{v}）に '{need}' が無い")
        if v != "検証不能" and not (isinstance(c.get("sources"), list) and c["sources"] and all(isinstance(s, str) and s.strip() for s in c["sources"])):
            errs.append(f"主張 '{c['id']}'（{v}）の sources が空——出典なしの判定は認めない")
    return errs


# ---------------------------------------------------------------- 仕上げと人の答え
def finalize(b):
    rec, th, ls = b.record, b.state["thickness"], b.loop_state
    g = rec["gates"]
    # 止まった事実の正本は record.convergence.outcome（stop() が書き、検証器が読む）。loop_state.outcome は
    # review-loop の rules だけが書く鍵で、ここで読むと止まった run を一度も見分けられなかった
    stopped = rec["convergence"].get("outcome") == "stopped"
    # **段ごとに必須のゲート全部を見る。** 以前は rederiver と cold_reader の 2 本だけを回しており、
    # **同じ不変条件の 3 本目（cartographer）が漏れていた**——重厚段で停止した run は cartographer が
    # not_applicable のまま理由も付かず、検証器 :241 が「重厚段で cartographer を省略している」で落ちる。
    # 帰結は前と同じで、**report の節が永久に出ない**（実測 2026-09-13: 部品を直に呼んで、重厚だけ
    # 理由の付かない not_applicable が残ることを確認）。**1 本直して赤が消えたところで止めていた形。**
    for k in ("rederiver", "cold_reader", "cartographer"):
        if g[k].get("status") != "not_applicable":
            continue
        if k == "cartographer" and th != "重厚":
            continue  # 重厚だけ必須。下の腕が「この段では走らせない」の理由を付ける
        if th == "軽量":
            g[k]["reason"] = "軽量段では走らせない（厚みの三段の表が正本）"
        elif stopped:
            # **収束せず停止した run は報告できなければならない。** 以前はここが軽量段しか触らず status も動かさなかったので、
            # 非収束で止まった標準／重厚段は検証器が exit 2 を返し続け（軽量でない段で not_applicable のゲートは fail）、
            # report_accepts_exit の既定 [0] の外なので engine が die し、**report の節が永久に出なかった**
            # （到達経路は max_rounds・thrash・stuck・unverifiable の 4 つで、どれも設計上『停止して報告する』筋）。
            # 受理集合を広げる処方は採らない——exit 2 は「記録が不正」であって、広げると本当の不正も通る
            g[k]["status"] = "not_run"
            g[k]["reason"] = ("収束しないまま報告の仕上げに来たので走らせる周が来なかった（このゲートは新規相違ゼロの周にだけ走る）"
                              "——飛ばした事実として記録に残す。緑と数えない")
    if g["cartographer"].get("status") == "not_applicable" and th != "重厚":
        g["cartographer"]["reason"] = f"{th} 段では走らせない（重厚だけ。厚みの三段の表が正本）"
    if rec["sampling"].get("status") == "not_applicable":
        rec["sampling"]["reason"] = "再ラウンドの検証対象が空集合になった周が無かった（抜き取りの条件に当たらない）"
    proc = rec["process"]
    # 打ち切りで照合に乗らなかった主張は、判定を捏造せず claims から外して申告する（件数の等式を保つ）
    unchecked = [c for c in rec["claims"] if c.get("verdict") is None]
    if unchecked:
        proc["unchecked_claims"] = [pick(c, ["id", "cluster", "claim", "load_bearing"]) for c in unchecked]
        rec["claims"] = [c for c in rec["claims"] if c.get("verdict") is not None]
        for cl in rec["clusters"]:
            cl["claims_submitted"] = sum(1 for c in rec["claims"] if c.get("cluster") == cl["key"])
        rec["clusters"] = [cl for cl in rec["clusters"] if cl["claims_submitted"] > 0]
    # 読了の柵が成立しなかった周は、成立しなかったことを人に見せる（engine の traces() が拾う欄名）
    proc["read_through_unchecked"] = b.state.get("read_through_unchecked", [])
    proc["stale_verdicts"] = [c["id"] for c in rec["claims"] if c.get("recheck")]
    unref = [c["id"] for c in rec["claims"] if c.get("load_bearing") and not c.get("refuted")]
    proc["unrefuted_load_bearing"] = unref
    if unref:
        proc["reason"] = "反証は『相違』と『荷重の確証』にだけ掛かる（留保・検証不能の荷重は対象外）。該当: " + ", ".join(
            f"{c['id']}={c.get('verdict')}" for c in rec["claims"] if c["id"] in unref)
    else:
        proc.pop("reason", None)
    if not any(c.get("load_bearing") for c in rec["claims"]):
        # 役が返さなかった欄を機械が埋めない——柵が要求するのは理由であって『理由が無い旨』ではない。
        # 埋めていたとき、検証器の非空検査は既定文で通り、欄が空だったことが記録から消えていた。
        if ls.get("load_zero_reason"):
            proc["load_zero_reason"] = ls["load_zero_reason"]
    else:
        proc.pop("load_zero_reason", None)


def on_answer(b, ph, ans):
    # **kinds を落とさない。** 以前は round / asked / answer だけを積んでおり、記録からは
    # 「何を聞かれて続行したか」が読めなかった（kinds が残るのは trace.jsonl だけ）。review 側は
    # 同じ欠陥を直したのに research 側だけ残っていた（実測 2026-09-14）。
    kinds = ph.get("kinds") or []
    b.record["process"]["human_items"].append(
        {"round": b.round, "kinds": kinds, "asked": ph["items"], "answer": ans})
    if ans == "stop":
        stop(b, "依頼者の判断で停止: " + ", ".join(kinds))
    else:
        if "stuck" in kinds:
            b.loop_state["stuck_hint"] = True  # 重厚なら次の周で断面の生成（手詰まり時の手筋）が開く
        b.loop_state["stuck_ids"] = []
        if "max_rounds" in kinds:
            # **上限は 1 周だけ延ばす。** 延ばした事実は記録に残る（human_items の kinds と下の欄）
            was = b.state["max_rounds"]
            b.state["max_rounds"] = was + 1
            b.record["process"].setdefault("max_rounds_extended", []).append(
                {"round": b.round, "from": was, "to": was + 1, "note": ph.get("note", "")})


def on_unattended(b, ph):
    # 有人（on_answer）と同じ形で積む——無人だけ文字列にすると、報告の穴埋めと読み手が 2 つの型を見る
    b.record["process"]["human_items"].append({"round": b.round, "kinds": ph.get("kinds") or [], "asked": ph["items"], "answer": "（無人実行で保守的に停止。答えは無い）"})
    reason = "無人実行: 諮るべき事態（" + ", ".join(ph["kinds"]) + "）に当たったので保守的に停止。要人間判断は process.human_items"
    stop(b, reason)
    return reason


def on_thickness(b, to):
    b.record["thickness"] = to


def add(b, items, reason):
    """ループの外（deep-research 等）で得た事実主張を次の周の P1 へ。"""
    # **型も見る**——欄の有無だけを見ていたとき、load_bearing に文字列 "false" を渡すと bool() で True に
    # 化けて受理された（節経由は schema が縛るので、緩いのは人が JSON を手書きするこの口だけ）。
    if not (isinstance(items, list) and items):
        raise Reject("add の形: [{id, cluster, claim, load_bearing}] の配列（空でない）")
    # 型検査は engine の validate_schema（INJECT）——同じ型語彙をここに写さない。真偽値と整数の区別も engine と同じ
    errs = validate_schema(items, {"type": "array", "minItems": 1, "items": {"type": "object", "required": ["id", "cluster", "claim", "load_bearing"],
                                   "properties": {"id": {"type": "string"}, "cluster": {"type": "string"}, "claim": {"type": "string"}, "load_bearing": {"type": "boolean"}}}})
    if errs:
        raise Reject("add の形が合わない（形: [{id, cluster, claim, load_bearing}]）: " + "; ".join(errs))
    add_claims(b, items, f"ループの外（{reason}）", "add")
    return f"主張 {len(items)} 件を足した（次の周の P1 で照合される。出どころ: {reason}）"
