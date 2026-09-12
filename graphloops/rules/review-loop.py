"""review-loop の rules——graphs/review-loop.json に書けない算術だけを持つ。

記録の形と語彙の正本は convergence-loops の scripts/review-record.py（同じリポジトリ。版は plugin.json が正本で、ここに写さない）。
ここはその定数を import して使い（写さない）、周ごとの記録 rounds/round-<N>.json を組み、検証器にディレクトリを渡す。

engine が差し込む道具は engine/rules.py の INJECT が正本（ここに写さない）。
"""
import pathlib
import re

# 差分を割って複数の cold-reader に配る扇（diff_chunks）は落とした。**割る理由が無くなったから**——
# 遮断系は別プロセスの CLI へ標準入力で流すので、貼る上限（Agent ツールのプロンプトの性質。実測 約 50 KB）に
# 当たらない。2026-09-12 にこの環境（macOS・claude 2.1.269）で観測: 748,883 バイトと 774,021 バイトの入力が先頭・末尾とも
# 欠けずに 1 回で届いた（測定の記録は docs/loop-contract.md の T 節。上限の値は目安で、契約ではない）。
# 入り切らなければ API がエラーを返して**うるさく落ちる**ので、割りは安全柵でもなかった（静かに切る
# 経路が事故だったのであって、落ちる経路は守るべき性質を既に満たしている）。
# 落としたのは 23 片に割れていた実績があるから: 750 KB ÷ 40,000 バイト ≒ 23 で、**読み手の人数が
# 差分の大きさで決まっていた**（誰も「衛生の検査には 23 人要る」と決めていない）。同じものを N 人に
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


def on_new_round(b):
    rec, ls = b.record, b.loop_state
    ls["prev_questions"] = rec["questions"]
    ls["prev_units"] = rec["units"]
    ls["prev_scalars"] = rec.get("scalars", {})
    rec["round"] = b.round
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
    # 前の周の P3 が実際に触ったファイル。持ち越しの再発火をこの実体から決める（役の申告 1 欄に頼らない）
    ls["prev_fix_files"] = sorted({f for c in (b.outputs().get("p3.fix", {}) or {}).get("changes", []) for f in c.get("files", [])})



PROCEDURE_PATTERNS = (r"README", r"\.md$", r"\.sh$", r"^scripts/", r"^\.github/workflows/", r"Makefile", r"Dockerfile",
                      r"\.ya?ml$", r"^commands/", r"^hooks/")


def touches_procedures(b):
    files = b.loop_state.get("changed_files", [])
    return any(re.search(p, f) for p in PROCEDURE_PATTERNS for f in files)


def prev_fix_touched(b):
    """前の周の P3 が 1 ファイルでも触ったか（cond の builtin）。

    差分全体を見る素材（衛生・整合・出典・外部標準・手順の追跡など）の再発火を、役の自己申告 1 欄
    （claims_changed 等）でなく **P3 が実際に触ったファイル**から決める。申告に依っていたとき、前の周の P3 が
    直した対象を見た素材が carried_over のまま前の周の主張を運び、閉じた欠陥が次の周に新規の [block] として
    生き返った（実測 2026-09-12: p1.provenance が r1 の主張を運び、判定者が取り下げるまで気づかれなかった）。
    """
    return bool(b.loop_state.get("prev_fix_files"))


CONDS = {"touches_procedures": touches_procedures, "prev_fix_touched": prev_fix_touched}


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
        q["reason"] = f"{src['reason']}——検算で仮定は偽: {src['resolution']}。実測を制約に足し次の周で R2 を回し直す（resolved の確定はその周の judge）"
        b.loop_state.setdefault("facts_to_add", []).extend(src.get("facts_to_add", []))
    b.record["questions"] = [x for x in b.record["questions"] if not (x.get("kind") == "premise" and x.get("origin") == "R2")]
    b.record["questions"].append(q)


WRITE_OPS = {"material_from_findings": material_from_findings, "premise_question": premise_question}


# ---------------------------------------------------------------- 機械の節
def worktree_snapshot(b, nid):
    """P1 の前: 作業ツリーの写しと、対象差分（git diff <BASE>）を機械が取る。回す側に貼らせない。"""
    ls = b.loop_state
    base = b.record.get("base")
    if not base:
        return {"ok": False, "problems": ["BASE が無い（p0.base が先）"]}
    # git の失敗（None）は全部「測れない」で止める。`or ""` で空文字に潰すと『取れない』と『変化なし』が
    # 同じ値になり、保護も件数も黙って通る（util.git の契約は「None は分からない。合格に倒すな」）。
    got = {k: git(*args) for k, args in (("diff", ("diff", base)), ("names", ("diff", "--name-only", base)),
                                         ("stat", ("diff", "--shortstat", base)), ("stash", ("stash", "list")))}
    missing = sorted(k for k, v in got.items() if v is None)
    if missing:
        return {"ok": False, "problems": [f"git が取れない（{', '.join(missing)}）——BASE={base} の対象差分と作業ツリーの保護が測れない場所からは回せない"]}
    diff, names, stat = got["diff"], got["names"], got["stat"]
    # 対象差分が空なら止める。空を通すと、素材が毎周 not_run（理由は事実と逆）で埋まったまま上限まで回る
    # （実測: BASE=HEAD で 5 周・diff 0 バイト・stop_reason=max_rounds、原因は記録のどこにも出ない）。
    if not diff.strip():
        return {"ok": False, "problems": [f"対象差分が空（git diff {base} が 0 バイト）——BASE を確かめよ（p0.base の base_sha）"]}
    snap = porcelain()
    if snap is None:
        return {"ok": False, "problems": ["git status が取れない——作業ツリーの保護（前後の突合）ができない場所からは回せない"]}
    f = b.dir / f"diff-r{b.round}.patch"
    f.write_text(diff, encoding="utf-8")
    ls["diff_file"] = str(f)
    ls["changed_files"] = [x for x in names.splitlines() if x.strip()]
    cf = b.dir / f"changed-r{b.round}.txt"
    cf.write_text("\n".join(ls["changed_files"]) + "\n", encoding="utf-8")
    ls["changed_files_file"] = str(cf)  # 回す側の節には一覧でなくこのパスを渡す（一覧を 4 本のプロンプトに複製しない）
    ls["diff_stat"] = stat.strip()
    ls["diff_lines"] = _lines_of(stat)
    # diff 本文の sha も突合に入れる。porcelain は状態コードとパスだけなので、**既に ' M' のファイルの
    # 中身を差し替えても検知しない**——レビュー対象は定義上ぜんぶ変更済みなので、これが無いと保護は
    # 対象そのものに効かない（agents/investigator.md はこの突合を「担保」と名乗っている）。
    ls["tree_before"] = {"porcelain": snap, "stash": got["stash"].strip(), "stat": stat.strip(), "diff_sha": sha(diff)}
    return {"ok": True, "diff_file": ls["diff_file"], "changed_files": ls["changed_files"], "stat": ls["diff_stat"]}


def _lines_of(stat):
    m = re.search(r"(\d+) insertion", stat or "")
    n = re.search(r"(\d+) deletion", stat or "")
    return (int(m.group(1)) if m else 0) + (int(n.group(1)) if n else 0)


def worktree_compare(b, nid):
    """P1 の後: 作業ツリーが変わっていないこと（どの道具が汚したかを当てるのでなく機械で突き合わせる）。
    走らせなかった素材の欄も、ここで機械が埋める（条件外＝not_applicable／持ち越し＝carried_over／
    走らせるべきだったのに無い＝not_run）。judge に渡る素材は必ず 15 欄そろう。"""
    ls = b.loop_state
    before = ls.get("tree_before") or {}
    snap = porcelain()
    # shortstat は diff 本文の sha に包含される（本文が同じなら行数も同じ）ので取り直さない——subprocess 1 本分
    got = {k: git(*args) for k, args in (("stash", ("stash", "list")), ("diff", ("diff", b.record["base"])))}
    if snap is None or any(v is None for v in got.values()) or before.get("porcelain") is None:
        return {"ok": False, "problems": ["git status / git diff が取れない——作業ツリーの前後を突き合わせられない（一致とは言えない）"]}
    now = {"porcelain": snap, "stash": got["stash"].strip(), "stat": before.get("stat"), "diff_sha": sha(got["diff"])}
    problems = []
    for k in ("porcelain", "stash", "diff_sha"):
        if before.get(k) != now[k]:
            problems.append(f"{k}: {before.get(k)!r} → {now[k]!r}")
    if problems:
        # writer 自身の変更（engine をその場で直した等）は、done と同じく理由を添えて通せる——痕跡は
        # process.git_mismatches に accepted として残る。通す道が無いと、engine を直しながら回す run は
        # ここで永久に止まる（実測 2026-09-12: P1 の途中で done の読み取りを直したら next が 10 回同じ note を返した。
        # stash で退避しても stash の一覧が突合に入っているので通らない）。受け付けたら基準を今の姿に置き直す。
        accepted = getattr(b, "accept_tree_change", None)
        entry = {"where": "P1", "round": b.round, "diff": problems, "accepted": accepted}
        gm = b.state.setdefault("git_mismatches", [])
        if not gm or gm[-1] != entry:  # 同じ止まり方で next を叩き直すたびに増やさない
            gm.append(entry)
        if not accepted:
            return {"ok": False, "problems": ["P1 の前後で作業ツリーが変わっている（戻してから next。自分の変更なら next --accept-tree-change <理由>）: " + "; ".join(problems)]}
        ls["tree_before"] = now
    fill_materials(b)
    return {"ok": True, "materials": sorted(b.record["materials"])}




def fill_materials(b):
    """走らせなかった素材の欄を機械が埋める。条件外＝not_applicable／前の判定を流用＝carried_over／
    前が awaiting_human・not_run（流用できない値）＝同じ値をもう一度（今も待っている記録）／それ以外＝not_run。"""
    V = validator_module(b)
    ls = b.loop_state
    last = ls.setdefault("last_seen", {})
    last_mat = ls.setdefault("last_material", {})
    mats = b.record["materials"]
    for name, st in mats.items():
        if st.get("status") in ("found", "clean"):
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
            if state == "skipped":
                mats[mat] = {"status": "not_run", "reason": f"回す側が省いた: {b.rd['skipped'].get(nid, '')}"}
                continue
            applies = n.get("applies_cond")
            if applies is not None and not b.eval_cond(applies):
                mats[mat] = {"status": "not_applicable", "reason": n.get("na_reason", "条件に当たらない")}
            elif mat in last:
                # 持ち越しの理由は「確かめた対象」を書く。理由を事実と独立に既定文で書いていたとき、
                # 前の周の P3 が直した対象を見た素材が carried_over のまま前の周の主張を運び、
                # 閉じた欠陥が次の周に新規の [block] として生き返った（実測 2026-09-12）。
                # 再発火そのものは graph の cond（builtin: prev_fix_touched）が決める——埋める側でなく走らせる側で。
                n_files = len(b.loop_state.get("prev_fix_files") or [])
                mats[mat] = {"status": "carried_over", "from_round": last[mat],
                             "reason": n.get("carry_reason", "再発火の条件に当たらない周（前の判定を流用。実際に見たのは from_round）")
                                       + f"（確認: 前の周の P3 が触ったファイルは {n_files} 件で、この節の再発火条件に当たらない）"}
            elif mat in last_mat and last_mat[mat].get("status") in ("awaiting_human", "not_run"):
                prev = last_mat[mat]
                mats[mat] = {"status": prev["status"], "reason": prev.get("reason", "") + "（前の周と同じ。流用できない値なので今も同じ状態として書く）"}
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


def assemble(b, nid):
    """P3 の後: 開いたユニットの数・R1/R2 の再発火・行数の伸び・台帳の変化を機械が数える。"""
    V = validator_module(b)
    rec, ls = b.record, b.loop_state
    fix = b.outputs().get("p3.fix", {})
    ls["open_units"] = sum(1 for u in rec["units"] if V.is_open(u))
    lines = ls.get("diff_lines", 0)
    at_r1 = ls.get("lines_at_r1")
    ratio = (lines / at_r1) if at_r1 else None
    ls["lines_ratio"] = ratio
    prev_q = _prev_round_record(b)
    ls["ledger_changed"] = (V.ledger_shape(rec) != V.ledger_shape(prev_q)) if prev_q else False
    mech = bool(fix.get("mechanism_changed"))
    drift = bool(fix.get("premise_drift"))
    grew = ratio is not None and ratio > 1.5
    forced = bool(ls.pop("r2_refire_forced", False))  # 先に消費する——式の最右に置くと短絡で pop に届かず、変化の無い次の周まで旗が効いた
    ls["r2_refire"] = b.round == 1 or mech or drift or grew or forced
    ls["r1_refire"] = ls["r2_refire"] or ls["ledger_changed"]
    # 目的が取れない（目的不明）のと、writer の要約を inspector が「狭めている」と判定したのは、R2 にとって同じ——
    # 独立の出典として使えない（以前は判定を誰も読まず、狭められた目的で R2 が回った。実測 2026-09-12）
    narrowed = b.record.get("process", {}).get("purpose_review", {}).get("verdict") == "狭めている"
    ls["purpose_known"] = (b.outputs().get("p0.purpose", {}).get("source") != "目的不明") and not narrowed
    if fix.get("premise_drift"):
        ls.setdefault("drift_notes", []).append({"round": b.round, "text": fix.get("premise_drift_note", "")})
    return {"ok": True, "open_units": ls["open_units"], "r1_refire": ls["r1_refire"], "r2_refire": ls["r2_refire"],
            "lines_ratio": ratio, "ledger_changed": ls["ledger_changed"], "purpose_known": ls["purpose_known"]}


def _prev_round_record(b):
    p = b.dir / "rounds" / f"round-{b.round - 1}.json"
    return read_json(p) if p.is_file() else None


def record_round(b, nid):
    """周の記録 rounds/round-<N>.json を組み、検証器にディレクトリを渡す。R の欄も機械が埋める。"""
    V = validator_module(b)
    rec, ls = b.record, b.loop_state
    last = ls.setdefault("last_seen", {})
    last_review = ls.setdefault("last_review", {})
    reviews = rec["reviews"]
    if ls.get("purpose_known") is False and "R2" not in reviews:
        reviews["R2"] = {"status": "unverifiable", "reason": "元の目的の出典が取れない（P0-4 で目的不明）"}
        # 検証器は同じ周に kind=unverifiable / origin=R2 の台帳の行を要求する。judge は既に done なので機械が書く（判定でなく機械的な帰結）
        if not any(x.get("kind") == "unverifiable" and x.get("origin") == "R2" for x in rec["questions"]):
            rec["questions"].append({"key": "元の目的を独立に取れない（R2 unverifiable）——目的の出典を人が示すか、未収束のまま報告するか",
                                     "kind": "unverifiable", "origin": "R2", "status": "held",
                                     "reason": "p0.purpose の source が目的不明。R2 は独立の出典なしに検証できない"})
    for name in V.REVIEWS:
        if name in reviews:
            if reviews[name]["status"] not in ("carried_over", "not_applicable"):
                last_review[name] = {"round": b.round, **reviews[name]}
            continue
        prev = last_review.get(name)
        if name in ("R3", "R4"):
            reviews[name] = {"status": "not_applicable", "reason": f"[block]＋do-now が {ls.get('open_units', '?')} 件残り P-R に到達していない"}
        elif prev and V.REVIEW_STATUS[prev["status"]].carryable:
            reviews[name] = {"status": "carried_over", "from_round": prev["round"], "reason": "再発火の条件（機構の追加・置換／前提のドリフト／行数 1.5 倍／台帳の変化）に当たらない"}
        elif prev:
            reviews[name] = {"status": prev["status"], "reason": prev["reason"] + f"（round {prev['round']} と同じ。持ち越せない値なので今も諮っている記録として書く）"}
        else:
            reviews[name] = {"status": "not_run", "reason": "走らせるべき周に返答が無い"}
    if ls.get("r1_refire") and "R1" in reviews and reviews["R1"]["status"] not in ("carried_over",):
        ls["lines_at_r1"] = ls.get("diff_lines", 0)
    for name, st in rec["materials"].items():
        if st.get("status") in ("found", "clean"):
            last[name] = b.round
        if st.get("status") != "carried_over":
            ls.setdefault("last_material", {})[name] = st
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
    # 分岐の文言は検証器の定数を import して使う（写すと、文言を直した周に分岐が黙って work_remains へ倒れる）
    branch = "converged" if v["exit"] == 0 else "premise_escalate" if V.STOP_PREMISE in out else \
        "work_exhausted" if V.STOP_WORK_EXHAUSTED in out else "work_remains"
    for u in rec["units"]:
        if u["label"] == "suggest" and u.get("disposition") == "defer":
            ls.setdefault("defer_ledger", {})[u["key"]] = {"reason": u.get("reason"), "round": b.round}
        if u["label"] == "block":
            ls.setdefault("prev_blocks", [])
            if u["key"] not in ls["prev_blocks"]:
                ls["prev_blocks"].append(u["key"])
    ls.setdefault("validator_outputs", {})[str(b.round)] = out
    return {"ok": True, "exit": v["exit"], "branch": branch, "out": out}


def converge(b, nid):
    rec_out = b.outputs().get("p4.record", {})
    branch = rec_out.get("branch")
    ls = b.loop_state
    ci = b.record["materials"].get("local_checks", {})
    asking = [q for q in b.record["questions"] if q["status"] in ("held", "escalate")]
    if branch == "converged":
        st = ci.get("status")
        if st == "found":
            return {"decision": "next_round", "reason": "検証器は阻害なしだが CI が赤（local_checks が found）——P3 で直してから"}
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
        ls["outcome"] = "converged"
        return {"decision": "converged", "reason": f"検証器が連続 2 ラウンド阻害なし・CI 緑（local_checks clean: {(ci.get('checked') or '')[:80]}）。"
                                                  "残った指摘は意図的に受容した設計判断として理由を明示して終える"}
    if branch in ("premise_escalate", "work_exhausted"):
        ls["outcome"] = "stopped"
        ls["stop_reason"] = branch
        return {"decision": "ask", "reason": branch, "ask": {
            "kinds": [branch],
            "question": ("前提不成立が確定した——残る仕事は全てその答えに従属する。" if branch == "premise_escalate" else
                         "残る阻害要因は保留の問いに帰属するものだけ——答え無しに進める仕事は無い。") +
                        " 台帳の held / escalate に答えるか（continue --note <答え>）、未収束のまま報告に進むか（stop）",
            "items": [f"[{q['status']}] {q['kind']}: {q['key']} — {q.get('reason', '')}" + (f" 選択肢: {q['options']}" if q.get("options") else "") for q in asking],
            "options": ["continue", "stop"],
        }}
    if b.round >= b.state["max_rounds"]:
        ls["outcome"] = "stopped"
        ls["stop_reason"] = "max_rounds"
        return {"decision": "stopped", "reason": f"暴走ガード: 総ラウンドが上限 {b.state['max_rounds']} に達した（収束せず。台帳の held / escalate をまとめて聞く）"}
    return {"decision": "next_round", "reason": "阻害要因が残る（検証器の出力を P2 の履歴に渡す）"}


BUILTINS = {"worktree_snapshot": worktree_snapshot, "worktree_compare": worktree_compare, "assemble": assemble,
            "record_round": record_round, "converge": converge}


# ---------------------------------------------------------------- 節ごとの整合（out を検査するだけ。record を書くのは WRITE_OPS）
def base_valid(b, nid, out, item):
    sha = out["base_sha"]
    if not re.fullmatch(r"[0-9a-f]{7,40}", sha) or git("cat-file", "-e", f"{sha}^{{commit}}") is None:
        raise Reject(f"BASE '{sha}' がこのリポジトリのコミットでない")
    b.record["base"] = git("rev-parse", sha).strip()


def judge_output(b, nid, out, item):
    """judge の返答を、検証器の語彙（写さず import）で先に見る。落ちるなら judge に返させ直す。"""
    V = validator_module(b)
    errs = []
    keys = set()
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
        domain, extra = V.QUESTION_KINDS[kind]
        for f in ("reason",) + extra + V.QUESTION_STATUS[status]:
            if not q.get(f):
                errs.append(f"questions[{i}]（{kind}/{status}）に '{f}' が要る")
        if kind == "fork" and not (isinstance(q.get("options"), list) and len(q["options"]) >= 2):
            errs.append(f"questions[{i}] の options は選択肢 2 つ以上（各項に帰結まで）")
        if domain == "unit" and q.get("origin") not in keys | defer:
            errs.append(f"questions[{i}] の origin '{q.get('origin')}' が units にも defer 台帳にも無い")
        if domain == "material" and q.get("origin") not in V.MATERIALS:
            errs.append(f"questions[{i}] の origin は素材名: {q.get('origin')}")
        if domain == "review" and q.get("origin") not in V.REVIEWS:
            errs.append(f"questions[{i}] の origin は R1〜R4: {q.get('origin')}")
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
    awaiting = {name for name, m in b.record["materials"].items() if m.get("status") == "awaiting_human"}
    listed = {q.get("origin") for q in out["questions"] if q.get("kind") == "awaiting" and q.get("status") in V.ASKING}
    for name in sorted(awaiting - listed):
        errs.append(f"素材 '{name}' が awaiting_human なのに台帳に kind=awaiting で無い")
    if out.get("materials_missing"):
        errs.append("judge が素材の欠落を報告した（P2 を止めて当該 grader を再起動しろ）: " + ", ".join(out["materials_missing"]))
    if errs:
        raise Reject("judge の返答が記録の語彙に合わない（judge に返させ直す）: " + "; ".join(errs))


def fix_covers_open_units(b, nid, out, item):
    """[block] と do-now は必ず直す。fork の出どころ・depends だけは待ってよい。"""
    V = validator_module(b)
    fork_targets = set()
    for q in b.record["questions"]:
        if q.get("kind") == "fork" and q.get("status") in V.ASKING:
            fork_targets.add(q.get("origin"))
            fork_targets.update(q.get("depends", []) or [])
    changed = {c["unit_key"] for c in out["changes"]}
    waiting = {c["unit_key"]: c["why"] for c in out.get("not_done", [])}
    missing = []
    for u in b.record["units"]:
        if not V.is_open(u):
            continue
        if u["key"] in changed:
            continue
        if u["key"] in fork_targets:
            continue
        if u["key"] in waiting:
            missing.append(f"{u['key']}（理由: {waiting[u['key']]}）——fork の出どころでないなら直す義務がある")
        else:
            missing.append(u["key"])
    if missing:
        raise Reject("直していない [block] / do-now がある（writer の裁量で defer に覆せない。異議は新しい judge に再判定させる）: " + "; ".join(missing))
    # 閉鎖の実証は自己申告——機械が検算できるのは「赤を一度も見ていないのに clean を名乗る」形だけなので、そこは拒む
    # （gate_arms_all_red と同じ形。以前は red_seen が全部 false・verified_how が「見ていない」でも clean が通った）。
    # 見るのは周の全体——文書だけの修正は赤を見られないので、修正ごとに要求すると文書を触った周が全部 found になる。
    # 修正ごとの赤の有無は sites にそのまま残り、judge が読む。
    st = out.get("fix_closure", {}).get("status")
    if out["changes"] and st in ("not_applicable", "carried_over"):
        # 修正が在る周の閉鎖の実証は今の周の修正に対して行う——「条件に当たらない」「前の周の流用」は
        # 機械が持つ事実（changes が非空）と食い違う（実測: 全 site が red_seen=false でも not_applicable なら
        # 受理され、3 周で converged した）
        raise Reject(f"修正が {len(out['changes'])} 件在るのに fix_closure が {st}——閉鎖の実証は今の周の修正に対して行う（clean か found）")
    if out["changes"] and st == "clean":
        if not any(s.get("red_seen") for c in out["changes"] for s in c["closure"].get("sites", [])):
            raise Reject("閉鎖の実証で赤を一度も見ていないのに fix_closure=clean——found にして赤を見ていない site を書くか、"
                         "退行を注入して赤を見てから出せ")
    if out.get("rejudge_requested"):
        b.loop_state["rejudge_requested"] = {"round": b.round, "text": out["rejudge_requested"]}


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
    # 節が走ったのは applies_cond が真だったから——機械が持つその事実と、役の書いた not_applicable は両立しない
    # （実測: 真で走った周に not_applicable と書けば腕ゼロで通った）
    ap = b.nodes[nid].get("applies_cond")
    if st == "not_applicable" and ap is not None and b.eval_cond(ap):
        raise Reject(f"{nid}: applies_cond が真（この差分は検証ゲートを新設・変更している）のに status=not_applicable——腕を書け")
    unred = [a["arm"] for a in arms if not a.get("red_confirmed")]
    nocontrol = [a["arm"] for a in arms if not a.get("control_green")]
    if st == "clean" and (unred or nocontrol):
        raise Reject(f"{nid}: 赤を見ていない腕 {unred} / 壊していない写しで緑を確かめていない腕 {nocontrol} が在るのに status=clean"
                     "——未達は found（count と detail に腕を書く）")


POST_CHECKS = {"gate_arms_all_red": gate_arms_all_red, "measured_needs_output": measured_needs_output, "base_valid": base_valid, "judge_output": judge_output, "fix_covers_open_units": fix_covers_open_units,
               "r2_design": r2_design, "r4_inventory": r4_inventory, "cold_check_note": cold_check_note}


def check_record(b, nid=None):
    """素材と俯瞰の欄を、検証器の表（STATUS / REVIEW_STATUS）で done の時点に見る（写さず import）。
    あわせて役が書いた status を機械が既に持つ事実と突き合わせる——走った節の素材が not_applicable（applies_cond が
    真だったから走った）は矛盾。nid は今 done している節（まだ done の印が付いていないので名指しで渡る）。"""
    V = validator_module(b)
    errs = []
    ran = {k for k in b.nodes if k == nid or b.node_state(k) == "done"}
    for k, n in b.nodes.items():
        ap = n.get("applies_cond")
        if k not in ran or ap is None:
            continue
        for mat in n.get("materials", []):
            m = b.record["materials"].get(mat)
            if m and m.get("status") == "not_applicable" and b.eval_cond(ap):
                errs.append(f"素材 '{mat}'（節 {k}）は applies_cond が真で走ったのに not_applicable——機械が持つ事実と食い違う")
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
    proc["outcome"] = ls.get("outcome", "stopped")
    proc["stop_reason"] = ls.get("stop_reason")
    proc["defer_ledger"] = ls.get("defer_ledger", {})
    proc["validator_outputs"] = ls.get("validator_outputs", {})
    proc["drift_notes"] = ls.get("drift_notes", [])
    proc["context_lost"] = b.state.get("context_lost", [])
    proc["cold_check"] = ls.get("cold_check")  # 初見検査の verdict と件数（非 pass でも報告は出る。直したかは writer の申告）
    proc["open_questions"] = [q for q in rec["questions"] if q.get("status") in V.ASKING]
    proc["resolved_questions"] = [q for q in rec["questions"] if q.get("status") in ("resolved", "decided")]


def on_answer(b, ph, ans):
    b.record["process"]["human_items"].append({"round": b.round, "asked": ph["items"], "answer": ans, "note": ph.get("note", "")})
    if ans == "continue":
        b.record["process"]["human_answers"].append({"round": b.round, "note": ph.get("note", ""), "asked": ph["items"]})
        b.loop_state.pop("outcome", None)
        b.loop_state.pop("stop_reason", None)


def on_unattended(b, ph):
    b.record["process"]["human_items"].append({"round": b.round, "asked": ph["items"], "answer": None, "note": "無人実行で停止（答えは無い）"})
    return "無人実行: " + ", ".join(ph["kinds"]) + "——保守的に停止。要人間判断は process.human_items"
