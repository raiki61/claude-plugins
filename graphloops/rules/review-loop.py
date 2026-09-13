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
    # 前の周の「一撃」を次の周に渡す——**効いたかを次の周が検算する**ため。一撃を選ぶ欄は前から在ったが、
    # 効いたかを測る工程が無く、同じクラスが 3 周続けて別の顔で出た（実測 2026-09-13: 判定者の one_shot が
    # 3 周とも同じ根＝「覆いの母数を誰も持たない」を指していたのに、毎周の閉じ方は名指しの 1 site だった）。
    # **「前の周に一撃が無い」と「渡し損ねた」を同じ空にしない。** optional の穴で受けていたとき、この工程の初回が
    # 空振りして誰も気づかなかった（実測 2026-09-13: プロンプトの {{?loop.prev_one_shot}} が空で描画され、盤面にも 0 件）。
    # 値は必ず入れ、無い周は無い理由を文字列で運ぶ——読む側（p2.history）は optional をやめてこれを必須の穴で受ける
    hist = b.outputs().get("p2.history") or b.outputs().get("p2.diagnose") or {}
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
    # 前の周の P3 が実際に触ったファイル——**engine が持つ事実**（前の周の P1 で写した diff と、今の diff の差）から作る。
    # writer の申告（p3.fix の changes[].files）は照合の片側に降ろす（実測 2026-09-13: 実在しないファイル名の申告で全素材が
    # 再発火し、実際に編集した周が 0 件扱いで持ち越された——申告だけを見ていた）
    claimed = sorted({f for c in (b.outputs().get("p3.fix", {}) or {}).get("changes", []) for f in c.get("files", [])})
    measured = _files_changed_since(b, b.round - 1)
    ls["prev_fix_files"] = claimed if measured is None else measured
    ls["prev_fix_source"] = "申告（前の周の diff の写しが無く測れない）" if measured is None else "実測（diff の差）"
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
    # **引き金は機械が持つ 2 値の交差だけ**——一度 info（閉じた）と判定されたキーが、後の周にまた [block] で
    # 戻っている数。判定者の任意欄（reburn_causes）を読んでいたとき、上げられる側の自己申告で深さが決まり、
    # 欄を埋めなければ永久に上がらなかった（この差分自身がその形で入り、判定で [block] になった）
    reburn = sorted({u["key"] for u in ls.get("prev_units", []) if u.get("label") == "block"} & set(ls.get("closed_keys", [])))
    if not reburn:
        return
    ls["escalated"] = {
        "round": b.round,
        # 前の周の判定文をここに入れない——p2.diagnose は履歴を渡さない節で、why に問いの key を入れると隔離が破れる
        "reburn_count": len(reburn),
        "why": f"一度 info（閉じた）と判定されたキーが、後の周にまた [block] で戻っている（{len(reburn)} 件。機械が数えた）",
        "effects": ["零処方の優先を外す（クラスを消す設計の処方を第一候補に並べさせる）",
                    "深さで切っている 4 節（p0.prior_decisions・p1.procedure_trace・p1.gate_efficacy・p1.test_double_fidelity）を条件に関わらず走らせる"],
    }
    b.record["process"]["escalated"] = ls["escalated"]


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
        q["reason"] = f"{src['reason']}——検算で仮定は偽: {src.get("resolution", "（resolution が無い返答）")}。実測を制約に足し次の周で R2 を回し直す（resolved の確定はその周の judge）"
        b.loop_state.setdefault("facts_to_add", []).extend(src.get("facts_to_add", []))
    b.record["questions"] = [x for x in b.record["questions"] if not (x.get("kind") == "premise" and x.get("origin") == "R2")]
    b.record["questions"].append(q)


WRITE_OPS = {"material_from_findings": material_from_findings, "premise_question": premise_question}


# ---------------------------------------------------------------- 機械の節
def _patch_sections(text):
    """diff の本文をファイルごとの節に割る（diff --git の見出しで）。"""
    out, cur, key = {}, [], None
    for line in text.splitlines():
        if line.startswith("diff --git "):
            if key is not None:
                out[key] = "\n".join(cur)
            key, cur = line.split(" b/", 1)[1] if " b/" in line else line, []
        cur.append(line)
    if key is not None:
        out[key] = "\n".join(cur)
    return out


def _files_changed_since(b, prev_round):
    """前の周の P1 が写した diff（diff-r<N>.patch）と今の git diff <BASE> の差＝その間に作業ツリーで変わったファイル。
    None = 測れない（前の周の写しが無い・git が取れない）——申告に落とす側は呼ぶ側で決める。"""
    f = b.dir / f"diff-r{prev_round}.patch"
    if not f.is_file() or not b.record.get("base"):
        return None
    raw = git_bytes("diff", b.record["base"])  # 突合と同じ生バイト（replace 復号だと等長の非 UTF-8 置換が同じ節に見える）
    if raw is None:
        return None
    now = raw.decode("latin-1")
    before, after = _patch_sections(f.read_bytes().decode("latin-1")), _patch_sections(now)
    return sorted({k for k in set(before) | set(after) if before.get(k) != after.get(k)})


def worktree_snapshot(b, nid):
    """P1 の前: 作業ツリーの写しと、対象差分（git diff <BASE>）を機械が取る。回す側に貼らせない。"""
    ls = b.loop_state
    base = b.record.get("base")
    if not base:
        return {"ok": False, "problems": ["BASE が無い（p0.base が先）"]}
    # git の失敗（None）は全部「測れない」で止める。`or ""` で空文字に潰すと『取れない』と『変化なし』が
    # 同じ値になり、保護も件数も黙って通る（util.git の契約は「None は分からない。合格に倒すな」）。
    # numstat 1 本で変更ファイルと行数の両方を取る（name-only と shortstat の 2 プロセスは冗長）
    # 対象差分は**生バイトで 1 度だけ**引く（写し・突合の sha・空の検査の 3 つが同じ値を使う）。以前は
    # 復号した text 版も別に引いていたが、その値は空の検査にしか使われず、927 KB を読む subprocess 1 本が
    # 捨てられていた（実測 2026-09-13）。
    got = {k: git(*args) for k, args in (("numstat", ("diff", "--numstat", base)), ("stash", ("stash", "list")))}
    got["diff"] = git_bytes("diff", base)
    missing = sorted(k for k, v in got.items() if v is None)
    if missing:
        return {"ok": False, "problems": [f"git が取れない（{', '.join(missing)}）——BASE={base} の対象差分と作業ツリーの保護が測れない場所からは回せない"]}
    raw_diff = got["diff"]
    rows = [ln.split("\t") for ln in got["numstat"].splitlines() if ln.strip()]
    names = "\n".join(r[2] for r in rows if len(r) == 3)
    ins = sum(int(r[0]) for r in rows if len(r) == 3 and r[0].isdigit())
    dels = sum(int(r[1]) for r in rows if len(r) == 3 and r[1].isdigit())
    stat = f"{len(rows)} files changed, {ins} insertions(+), {dels} deletions(-)"
    # 対象差分が空なら止める。空を通すと、素材が毎周 not_run（理由は事実と逆）で埋まったまま上限まで回る
    # （実測: BASE=HEAD で 5 周・diff 0 バイト・stop_reason=max_rounds、原因は記録のどこにも出ない）。
    if not raw_diff.strip():
        return {"ok": False, "problems": [f"対象差分が空（git diff {base} が 0 バイト）——BASE を確かめよ（p0.base の base_sha）"]}
    snap = porcelain()
    if snap is None:
        return {"ok": False, "problems": ["git status が取れない——作業ツリーの保護（前後の突合）ができない場所からは回せない"]}
    f = b.dir / f"diff-r{b.round}.patch"
    # **写しは生バイトで書く。** 復号した str を UTF-8 で書き戻すと、復号できないバイトが U+FFFD（UTF-8 で 3 バイト）
    # に化けるので、生バイトで読み直す側（_files_changed_since）と永久に一致しない——誰も触っていない周でも
    # 「変わった」と出て prev_fix_touched が恒真になり、再発火の条件分けが効かず prev_fix_source だけが
    # 「実測」と名乗り続けた（実測 2026-09-13）。突合の sha（下の tree_before）は既に生バイトに揃えてあり、
    # 揃っていないのは書く側のこの 1 か所だけだった。**貼る用の本文は復号済みの diff をそのまま使う**——
    # 切り分けは「貼るか突き合わせるか」で、同じファイルが両方に使われるなら正本は突合の側（生バイト）。
    f.write_bytes(raw_diff)
    ls["diff_file"] = str(f)
    ls["changed_files"] = [x for x in names.splitlines() if x.strip()]
    cf = b.dir / f"changed-r{b.round}.txt"
    cf.write_text("\n".join(ls["changed_files"]) + "\n", encoding="utf-8")
    ls["changed_files_file"] = str(cf)  # 回す側の節には一覧でなくこのパスを渡す（一覧を 4 本のプロンプトに複製しない）
    ls["diff_stat"] = stat.strip()
    ls["diff_lines"] = ins + dels  # 2 行上で numstat から数えた整数をそのまま使う（stat 文字列に組んでから正規表現で読み直していた）
    # diff 本文の sha も突合に入れる。porcelain は状態コードとパスだけなので、**既に ' M' のファイルの
    # 中身を差し替えても検知しない**——レビュー対象は定義上ぜんぶ変更済みなので、これが無いと保護は
    # 対象そのものに効かない（agents/investigator.md はこの突合を「担保」と名乗っている）。
    # 突合の sha は**生バイト**から取る（貼る用の diff は replace 復号でよい）——replace は復号できないバイトを
    # 種類に依らず U+FFFD 1 文字に写すので、等長の非 UTF-8 書き換えが同じ sha になり、この腕が porcelain と
    # 同じ盲点に戻っていた（実測 2026-09-13）。生バイトが取れない場（git 不在）は None で「測れない」側に倒れる
    ls["tree_before"] = {"porcelain": snap, "stash": got["stash"].strip(),
                         "diff_sha": sha(raw_diff.decode("latin-1"))}  # 写しと同じ生バイトから取る（上で 1 度だけ引いた）
    return {"ok": True, "diff_file": ls["diff_file"], "changed_files": ls["changed_files"], "stat": ls["diff_stat"]}


def worktree_compare(b, nid):
    """P1 の後: 作業ツリーが変わっていないこと（どの道具が汚したかを当てるのでなく機械で突き合わせる）。

    **射程は git が映す範囲だけ**——porcelain・stash・diff の sha はいずれも .git/ 配下・.gitignore 対象・
    リポジトリの外（$HOME 等）を映さない。役が .git/hooks/ や ~/.claude/settings.json を書いても緑で通る。
    これは**事故の検知**であって権限の強制ではない（この run 自身の生成物 .git/graphloops/… も射程の外）。
    走らせなかった素材の欄も、ここで機械が埋める（条件外＝not_applicable／持ち越し＝carried_over／
    走らせるべきだったのに無い＝not_run）。judge に渡る素材は必ず 15 欄そろう。"""
    ls = b.loop_state
    before = ls.get("tree_before") or {}
    snap = porcelain()
    # shortstat は diff 本文の sha に包含される（本文が同じなら行数も同じ）ので取り直さない——subprocess 1 本分
    got = {k: git(*args) for k, args in (("stash", ("stash", "list")), ("diff", ("diff", b.record["base"])))}
    if snap is None or any(v is None for v in got.values()) or before.get("porcelain") is None:
        return {"ok": False, "problems": ["git status / git diff が取れない——作業ツリーの前後を突き合わせられない（一致とは言えない）"]}
    raw = git_bytes("diff", b.record["base"])
    if raw is None:
        return {"ok": False, "problems": ["git diff（生バイト）が取れない——作業ツリーの前後を突き合わせられない（一致とは言えない）"]}
    now = {"porcelain": snap, "stash": got["stash"].strip(), "diff_sha": sha(raw.decode("latin-1"))}
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
                # 再発火そのものは graph の cond（builtin: prev_fix_touched）が決める——埋める側でなく走らせる側で。
                why = (f"（確認: 前の周の P3 が触ったファイルは {len(b.loop_state.get('prev_fix_files') or [])} 件で、この節の再発火条件に当たらない）"
                       if n.get("cond") else "（確認: この節は再発火条件を持たない once の節）")
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
    src = b.outputs().get("p0.purpose", {}).get("source")
    narrowed = b.record.get("process", {}).get("purpose_review", {}).get("verdict") == "狭めている"
    # 原因を運ぶ 1 値（None／目的不明／狭めている）——bool に畳むと record_round が定数文で説明するしかなく、理由が事実と逆になる
    # （実測 2026-09-13: 狭めている周の R2 の reason が『P0-4 で目的不明』）
    ls["purpose_unusable"] = "目的不明" if src == "目的不明" else ("狭めている" if narrowed else None)
    ls["purpose_known"] = ls["purpose_unusable"] is None
    if fix.get("premise_drift"):
        ls.setdefault("drift_notes", []).append({"round": b.round, "text": fix.get("premise_drift_note", "")})
    return {"ok": True, "open_units": ls["open_units"], "r1_refire": ls["r1_refire"], "r2_refire": ls["r2_refire"],
            "lines_ratio": ratio, "ledger_changed": ls["ledger_changed"], "purpose_known": ls["purpose_known"]}


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


def record_round(b, nid):
    """周の記録 rounds/round-<N>.json を組み、検証器にディレクトリを渡す。R の欄も機械が埋める。"""
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
        # 検証器は同じ周に kind=unverifiable / origin=R2 の台帳の行を要求する。judge は既に done なので機械が書く（判定でなく機械的な帰結）
        if not any(x.get("kind") == "unverifiable" and x.get("origin") == "R2" for x in rec["questions"]):
            # 理由は reviews.R2 と同じ 1 値（purpose_unusable）から引く——定数文で書いていたとき、原因が
            # 『狭めている』の周にも『目的不明』と表示され、converge がそれをそのまま人に見せた（実測 2026-09-13）
            rec["questions"].append({"key": "元の目的を独立に取れない（R2 unverifiable）——目的の出典を人が示すか、未収束のまま報告するか",
                                     "kind": "unverifiable", "origin": "R2", "status": "held",
                                     "reason": reviews["R2"]["reason"]})
    for name in V.REVIEWS:
        if name in reviews:
            if reviews[name]["status"] not in ("carried_over", "not_applicable"):
                last_review[name] = {"round": b.round, **reviews[name]}
            continue
        prev = last_review.get(name)
        if name in ("R3", "R4"):
            reviews[name] = {"status": "not_applicable",
                             "reason": f"[block]＋do-now が {ls.get('open_units', '?')} 件残り、前の周の P3 も触っていない（どちらの再発火条件にも当たらない）"}
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
    V = validator_module(b)
    rec_out = b.outputs().get("p4.record", {})
    branch = rec_out.get("branch")
    ls = b.loop_state
    ci = b.record["materials"].get("local_checks", {})
    asking = [q for q in b.record["questions"] if q["status"] in V.ASKING]
    # 暴走ガードは全部の分岐に掛かる——converged/found の早期 return の後ろに置いていたとき、CI が赤のまま上限を越えて
    # 回り続けた（実測 2026-09-13: round 9 / max 5 で running）。収束する周（阻害なし・CI 緑）だけは上限より優先して収束させる
    will_converge = branch == "converged" and ci.get("status") == "clean"
    if b.round >= b.state["max_rounds"] and not will_converge:
        ls["outcome"] = "stopped"
        ls["stop_reason"] = "max_rounds"
        return {"decision": "stopped", "reason": f"暴走ガード: 総ラウンドが上限 {b.state['max_rounds']} に達した（収束せず。台帳の held / escalate をまとめて聞く）"}
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
    return {"decision": "next_round", "reason": "阻害要因が残る（検証器の出力を P2 の履歴に渡す）"}


BUILTINS = {"worktree_snapshot": worktree_snapshot, "worktree_compare": worktree_compare, "assemble": assemble,
            "record_round": record_round, "converge": converge}


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
        # 今の周に直す単位は、同じ形を**全部**引ける機械の問いを持て。名指しの 1 site だけを塞ぐ閉じ方が 3 周続き、
        # 同じ不変条件の別の入口が毎周ちがう顔で出た（実測 2026-09-13: 判定者自身が『覆いの母数を誰も持たない』と書いた）。
        # 問い（how）と件数（total）が在れば、次の周の判定者が同じコマンドを走らせて母数を検算できる。
        if u["label"] == "block" or (u["label"] == "suggest" and u.get("disposition") == "do-now"):
            cq = u.get("class_query") or {}
            if not (cq.get("how") or "").strip() or not isinstance(cq.get("total"), int) or isinstance(cq.get("total"), bool):
                errs.append(f"units[{i}]（今の周に直す単位）に class_query（how＝同じ形を全部引ける機械の問い・total＝その件数）が無い"
                            "——1 site しか無いなら total: 1 でそう示せ")
    # 一撃は反証可能に——「何が消えるはずか」を名指しし、次の周が測る問いを添える。名指しが無いと、
    # 効かなかったことを誰も言えないまま次の周が同じ根を選び直す（実測 2026-09-13: 3 周とも同じ根）
    open_units = [u for u in out["units"] if u["label"] == "block" or (u["label"] == "suggest" and u.get("disposition") == "do-now")]
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
        domain, extra = V.QUESTION_KINDS[kind]
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
    # 覆いの母数——「1 か所直して終わり」を数字で見えるようにする。closed < total は禁じない（残すのは判断）が、
    # 残したこと自体を書かせる。ここで検算できるのは数の整合だけで、問い（how）が正しいかは次の周の判定者が同じ
    # コマンドを走らせて見る（kind=実測 に measured_output を要求するのと同じ形）
    EMPTY = ("なし", "無し", "ない", "無い", "特になし", "n/a", "none", "-", "未確認", "不明")
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
        for f, ks in shared.items():
            extra = sorted(set(seen[f]["changes"]) - set(ks))
            if extra:
                raise Reject(f"interactions[{f}] の changes に、その面を触っていない修正が在る: {extra}")
            ck = (seen[f].get("checked") or "").strip()
            if ck.lower() in EMPTY or len(ck) < 10:
                raise Reject(f"interactions[{f}] の checked が空同然——一方が他方を不要にしないか・順序で結果が変わらないか・"
                             "組み合わせて初めて生まれる状態が無いかを突き合わせた結果を書け")
    # 「破れない」「壊れない」の自己申告は、**探した形跡が無い一語**では受け取らない。機械が検算できるのは
    # 「探したと言っているか」までだが、次の周の判定者はこの欄を材料に当て直せる（kind=実測 の measured_output と同じ形）
    # 判定者が数えた母数（class_query.total）。**writer が how を狭めて total を書き直せば「1 か所直して終わり」が
    # 緑で通った**ので、判定者の値と突き合わせる（判定者の数え方を疑うなら remaining に書け）
    judged = {u["key"]: (u.get("class_query") or {}).get("total")
              for u in ((b.record.get("process") or {}).get("diagnosis") or {}).get("units", [])}
    for c in out["changes"]:
        bt = (c.get("bypass_tried") or "").strip()
        if bt.lower() in EMPTY or len(bt) < 10:
            raise Reject(f"{c['unit_key'][:60]}: bypass_tried が空同然——**修正を残したまま**破りに行った入力と結果を書け"
                         "（『修正を外したら赤くなった』は不在の検知であって完全性の証拠にならない）")
        br = c.get("breaks") or {}
        if (br.get("result") or "").strip().lower() in EMPTY:
            raise Reject(f"{c['unit_key'][:60]}: breaks.result が空同然——壊しうる面を how で引いて、壊れていないことを確かめた結果を書け")
        ros = c.get("root_or_symptom") or {}
        if ros.get("kind") == "symptom" and len((ros.get("why") or "").strip()) < 10:
            raise Reject(f"{c['unit_key'][:60]}: 症状を塞ぐ修正なのに、なぜ今それで止めるかが無い（根に当てるのが設計作業なら、そう書いて questions に fork を立てろ）")
        cov = c.get("coverage") or {}
        total = cov.get("total")
        if not (cov.get("how") or "").strip():
            raise Reject(f"{c['unit_key'][:60]}: coverage.how（同じ形を全部引ける機械の問い）が無い——名指しの 1 site だけを塞いでいないことは母数でしか示せない")
        if not isinstance(total, int) or isinstance(total, bool):
            raise Reject(f"{c['unit_key'][:60]}: coverage.total は数で書け")
        closed = len(c.get("closure", {}).get("sites", []) or [])  # 塞いだ数は closure.sites から機械が数える（二度書かせない）
        if closed > total:
            raise Reject(f"{c['unit_key'][:60]}: closure.sites が {closed} 件なのに coverage.total が {total}——母数を超えて塞げない（問いが対象を取りこぼしている）")
        if closed < total and not (cov.get("remaining") or "").strip():
            raise Reject(f"{c['unit_key'][:60]}: 母数 {total} のうち閉鎖を実証した site が {closed} 件で、残りが在るのに remaining（残した理由）が無い"
                         "——残すこと自体は禁じないが、黙って残すのは禁じる")
        jt = judged.get(c["unit_key"])
        if isinstance(jt, int) and not isinstance(jt, bool) and total < jt and not (cov.get("remaining") or "").strip():
            raise Reject(f"{c['unit_key'][:60]}: 判定者が数えた母数は {jt} なのに coverage.total を {total} に狭めている"
                         "——狭める理由（問いが対象を取りこぼしていた等）を remaining に書け")
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
    # applies_cond が真で走った節の not_applicable は check_record の表（status × 機械の事実）が拒む——ここには写さない
    unred = [a["arm"] for a in arms if not a.get("red_confirmed")]
    nocontrol = [a["arm"] for a in arms if not a.get("control_green")]
    # **赤が出たことは、その赤が守りたい行から出た証拠にならない。** 腕が守る行を一度も通らないまま緑で
    # 素通りする形が実測で出た（2026-09-13: 持ち越しの可否の柵に退行を注入しても検査は緑のままで、その分岐が
    # 書く理由文字列を一意の印に差し替えても記録に印が現れなかった＝筋書きがその行を通っていない）。
    # 赤は「柵が無ければ落ちる」ことしか言わず、「この腕がその柵を通った」ことは別に測る必要がある。
    # 測り方は今周の gate_efficacy が実際に使った形をそのまま欄にする——分岐が書く値を一意の印に替え、
    # その印が出力か記録に現れることを見る（`hit_evidence` に何をどう確かめたか）。
    EMPTY_HIT = {"", "-", "なし", "未実施", "未確認", "N/A", "n/a", "TODO"}
    nohit = [a["arm"] for a in arms
             if (a.get("hit_evidence") or "").strip() in EMPTY_HIT or len((a.get("hit_evidence") or "").strip()) < 10]
    # 未赤の腕が在るのに found 以外（clean / carried_over / not_applicable …）を名乗る返答は拒む——clean だけ見ていたとき
    # carried_over で腕ゼロのまま通った（実測 2026-09-13）
    if st != "found" and (unred or nocontrol or nohit):
        raise Reject(f"{nid}: 赤を見ていない腕 {unred} / 壊していない写しで緑を確かめていない腕 {nocontrol} / "
                     f"守る行を通ったことを測っていない腕 {nohit} が在るのに status=clean"
                     "——未達は found（count と detail に腕を書く）")
    # **status に依らず当てる腕**: 赤も control 緑も見た腕が、守る行を通ったことを測っていないなら、
    # その腕は「覆いの証拠」として数えられない。found でも同じなので、ここは status の外で拒む。
    if nohit and not (unred or nocontrol):
        raise Reject(f"{nid}: 腕 {nohit} は赤も control の緑も見ているが、**その腕が守る行を通ったこと**を測っていない"
                     "（hit_evidence）——赤は柵の不在の検知であって、この腕がその柵に当たった証拠にならない。"
                     "分岐が書く値を一意の印に替え、その印が出力か記録に現れることを確かめて hit_evidence に書け")


POST_CHECKS = {"gate_arms_all_red": gate_arms_all_red, "measured_needs_output": measured_needs_output, "base_valid": base_valid, "judge_output": judge_output, "fix_covers_open_units": fix_covers_open_units,
               "r2_design": r2_design, "r4_inventory": r4_inventory, "cold_check_note": cold_check_note}


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
            if st == "carried_over":
                errs.append(f"素材 '{mat}'（節 {k}）は今の周に走ったのに carried_over——流用は走らなかった節に機械が書く。今の周の判定を書け")
            # 走った節の『条件に当たらない』は、機械が持つ事実（applies_cond が真）と食い違うなら拒む。
            # applies_cond を持たない節は機械に照らす事実が無いので、**正当に名乗れる節を graph が宣言する**
            # （na_self_ok）——`ap is not None` で絞っていたとき、宣言の無い 11 節（うち回す側が 6）まで自己申告で
            # 素通りした。逆に全部拒むと、CI が存在しない対象や修正 0 件の周という正当な経路が落ちる（実測 2026-09-13）
            if st == "not_applicable":
                if ap is not None and b.eval_cond(ap):
                    errs.append(f"素材 '{mat}'（節 {k}）は applies_cond が真で走ったのに not_applicable——機械が持つ事実と食い違う")
                elif ap is None and not n.get("na_self_ok"):
                    errs.append(f"素材 '{mat}'（節 {k}）は走ったのに not_applicable——この節は正当に名乗れる節として graph が"
                                "宣言していない（na_self_ok）。今の周の判定を書くか、名乗れる理由を graph に宣言しろ")
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
