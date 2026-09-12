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
    ls = b.loop_state
    key = f"sampled_r{b.round}"
    claims = b.record["claims"]
    if key in ls:
        chosen = [c for c in claims if c["id"] in ls[key]]
    else:
        pool = [c for c in claims if c.get("verdict") in ("確証", "相違", "留保") and not c.get("recheck")]
        if not pool:
            return []
        rng = random.Random(f"{b.state['run_id']}:{b.round}")
        chosen = rng.sample(pool, max(1, round(len(pool) * 0.15)))
        ls[key] = [c["id"] for c in chosen]
    return [{"key": "sample", "claims": [pick(c, ["id", "claim", "load_bearing"]) for c in chosen]}]


FAN_OUT = {"clusters_needing_check": clusters_needing_check, "claims_needing_refute": claims_needing_refute, "sampling_pick": sampling_pick}
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
    rec, th = b.record, b.state["thickness"]
    g = rec["gates"]
    fails = []
    if th in ("標準", "重厚"):
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
    if zero and not fails and conv["consecutive_zero"] >= 2 and not overturned and not pending:
        conv["outcome"] = "converged"
        conv.pop("stopped_reason", None)
        return {"decision": "converged", "reason": f"連続 {conv['consecutive_zero']} 周で新規相違ゼロ、{th} 段のゲートは全部 pass"}

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
    pd = rec["process"].get("prior_decisions")
    if zero and isinstance(pd, dict) and pd.get("checked") is False:
        asks.append(("prior_decisions_unchecked", "先行議論を洗えていない——決着済みの蒸し返しの可能性が残る。『重複なし』に丸めない"))
    if b.round >= st["max_rounds"]:
        return stop(b, f"暴走ガード: 総ラウンドが上限 {st['max_rounds']} に達した（収束せず）")
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


def open_questions_note(b, nid, out, item):
    if out.get("open_questions"):
        return ("開いた問いがある: " + " / ".join(out["open_questions"]) +
                "——P1（閉じた主張の検証）では解けない。ループの外で deep-research に委ね、持ち帰った事実主張は loop.py add で次の周に入れる")


def clear_stuck_hint(b, nid, out, item):
    b.loop_state["stuck_hint"] = False


POST_CHECKS = {"refuter_consistency": refuter_consistency, "cold_reader_consistency": cold_reader_consistency,
               "cartographer_count": cartographer_count,
               "load_zero_reason": load_zero_reason,
               "open_questions_note": open_questions_note, "clear_stuck_hint": clear_stuck_hint}


def check_record(b, nid=None):
    errs = []
    for c in b.record["claims"]:
        v = c.get("verdict")
        if v is None:
            continue
        # 検証器の表は判定 → 要る欄の組（tuple）。rules に在った写しは判定 → 欄 1 つの dict で、形が既にずれていた
        for need in validator_module(b).VERDICT_FIELDS.get(v, ()):
            if not (isinstance(c.get(need), str) and c[need].strip()):
                errs.append(f"主張 '{c['id']}'（{v}）に '{need}' が無い")
        if v != "検証不能" and not (isinstance(c.get("sources"), list) and c["sources"] and all(isinstance(s, str) and s.strip() for s in c["sources"])):
            errs.append(f"主張 '{c['id']}'（{v}）の sources が空——出典なしの判定は認めない")
    return errs


# ---------------------------------------------------------------- 仕上げと人の答え
def finalize(b):
    rec, th, ls = b.record, b.state["thickness"], b.loop_state
    g = rec["gates"]
    for k in ("rederiver", "cold_reader"):
        if g[k].get("status") == "not_applicable" and th == "軽量":
            g[k]["reason"] = "軽量段では走らせない（厚みの三段の表が正本）"
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
    b.record["process"]["human_items"].append({"round": b.round, "asked": ph["items"], "answer": ans})
    if ans == "stop":
        stop(b, "依頼者の判断で停止: " + ", ".join(ph["kinds"]))
    else:
        if "stuck" in ph["kinds"]:
            b.loop_state["stuck_hint"] = True  # 重厚なら次の周で断面の生成（手詰まり時の手筋）が開く
        b.loop_state["stuck_ids"] = []


def on_unattended(b, ph):
    # 有人（on_answer）と同じ形で積む——無人だけ文字列にすると、報告の穴埋めと読み手が 2 つの型を見る
    b.record["process"]["human_items"].append({"round": b.round, "asked": ph["items"], "answer": "（無人実行で保守的に停止。答えは無い）"})
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
    TYPES = {"id": str, "cluster": str, "claim": str, "load_bearing": bool}
    for i, c in enumerate(items):
        if not isinstance(c, dict):
            raise Reject(f"add[{i}] が object でない")
        for k, ty in TYPES.items():
            if k not in c:
                raise Reject(f"add[{i}] に '{k}' が無い（形: {{id, cluster, claim, load_bearing}}）")
            if not isinstance(c[k], ty) or (ty is bool) != isinstance(c[k], bool):
                raise Reject(f"add[{i}].{k} の型が {ty.__name__} でない: {c[k]!r}")
    add_claims(b, items, f"ループの外（{reason}）", "add")
    return f"主張 {len(items)} 件を足した（次の周の P1 で照合される。出どころ: {reason}）"
