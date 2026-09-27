"""途中の盤面を作る口（testplan の T1: 否定検査を「控えた波・1 手・手で書いた期待」へ移す土台。T2: 層 2 の筋書きの given）。

盤面を端から歩いて 1 か所を見る台本（simulate.py・simulate_review.py）の前半を、同じプロセスで 1 度だけ回して狙いの波ごとに
控え、検査ごとに控えから始めて 1 手だけ打てるようにする。波の表 WAVES と根 ROOTS が、T1 の否定検査と T2 の筋書き
（test_scenarios_review.py・test_scenarios_research.py）が共にする前置きの唯一の置き場——波の手は Run の口と台本の drive を呼ぶ
Python の関数で、筋書きの when も同じ形の関数で書く。

- **作り方**: 台本の Run・answers・base_answers・settle を import して借り（写さない）、glharness.driven(台本, "inproc") の下で
  回す——loop.py は同じプロセスの ``loop.cli()`` に回り、git は本物（型のリポジトリ。Run がセッションで 1 度だけ作る）。
- **控え**: 波ごとに Run の作業場（型のリポジトリ・盤面・設定）をまるごとセッションの置き場へ写す。作業場の置き場は
  Run が作った 1 か所に固定し、検査はそこへ控えを写し戻して始める（置き場が動かないので、盤面の中の絶対パスを書き換えない）。
  1 つの worker の検査は順に走るので、同じ置き場を順に使ってよい。控えは worker ごとの session の fixture で 1 度だけ作る
  （pytest-xdist の worker の間では分けない——作り手が消えたときに待ち手が待ち続ける形と、-n 無しの回にセッションをまたいで
  古い控えを使う形を作らないため）。
- **前半の歩きは check を呼ばない**。台本の check は fixture の中で落ちても数えられないので、前提が崩れたら例外で止める。
  research の台本の drive は hook が None のとき中で check（渡し方の検査）を撃つので、波の手は何もしない hook（NOHOOK）を必ず渡す
  （渡し方の検査は台本の側に残る）。
- **検査の中の 1 手**も台本の Run の口（run.done・run.next・run.cmd）をそのまま使い、fixture ``wave`` が張る
  driven(…, "inproc") の下で同じプロセスで走る。同じプロセスでは見えない物（argv・終了コードの写像・標準入力の文字コード・
  PYTHONIOENCODING）は、移した先のテストの印 ``moved_from(…, kept=理由)`` で台帳に「通しに残す」と書く。

前半の手順のうち、台本の関数の中だけに在る物（test_rejections の主張 A を太らせる・stray.txt と --accept-tree-change・拒ませて
から通す done、T2 の各関数の hook と途中の手）は、台本の本文から下の波の手に書き写してある。台本を消す run まで台本も残るので、
台本の前半を直したらここも直す（ずれを見る柵は無い——README の test_schema_graphcheck.py の写しと同じ扱い）。

大きさ: これを使うテストは medium（glharness.SIZES）。inproc の口が同じプロセスに回すのは loop.py だけで、engine が自分で
起こす子（git・検証器・宣言の走らせる語・launch）は子プロセスのまま走る。small を名乗れるのは、子を消す世界の口（T3）が入った後。
T2 の筋書きには印 layer2 も付く（盤面を何周も回す。手元の反復では ``-m "not layer2"`` で外せる）。
"""
import contextlib
import json
import os
import pathlib
import shutil
import stat
import tempfile

import glharness
import pytest

TESTS = glharness.TESTS
review = glharness.script("review")
research = glharness.script("research")


def pending(run):
    """今の周に出ていて済んでいない instance を節の名前で（next の ready と同じ集合。done の相手を引く口）"""
    rd = run.state()["rounds"][-1]
    return {i["node"]: i for i in rd["instances"].values() if i["status"] == "pending"}


def _ok(r, what):
    if r.returncode != 0:
        raise RuntimeError(f"波の前提が崩れた: {what} が {r.returncode}: {(r.stderr or '')[-400:]}")
    return r


# ---- 波の作り方（名前: (親, 手)）。手は (run, values) を受けて進め、values（JSON の値の控え）に足してよい ------------------

T_NODES = ("p0.prior_decisions", "p1.local_review", "p1.consistency_bypass", "p1.external_standards", "p1.provenance",
           "p1.hygiene", "p2.diagnose", "p3.fix")


def _r_p0(run, v):
    run.next()
    # review の test_rejections は返答の表（answers）を P0 の最初の波で 1 度だけ引き、P1・撃ち直し・判定・修正の拒みの土台に
    # 使い回す——同じ時点で引いた値を控える（後で引き直すと、表が記録を読む節の値が変わる）
    t = review.answers(run, "std", 1)
    v["t"] = {n: t[n](None) for n in T_NODES}


def _settle(run, inst, make):
    """台本の settle（走らせる節は launch——ok でなければ settle が例外。ほかは done）の done の側も、崩れたら止める"""
    got = review.settle(run, inst, make)
    if not isinstance(got, dict):
        _ok(got, inst["node"])


def _r_p0_settled(run, v):
    t = review.answers(run, "std", 1)
    by = pending(run)
    for n in ("p0.base", "p0.local_checks", "p0.premises"):
        _settle(run, by[n], t[n])


def _r_next(run, v):
    run.next()


def _r_p0b_settled(run, v):
    t = review.answers(run, "std", 1)
    by = pending(run)
    for n in ("p0.purpose", "p0.parallel_pr", "p0.prior_decisions"):
        _settle(run, by[n], t[n])


def _r_p1_done(run, v):
    by = pending(run)
    for n in ("p1.local_review", "p1.consistency_bypass", "p1.external_standards", "p1.provenance", "p1.hygiene"):
        _ok(run.done(by[n]["id"], v["t"][n]), n)


def _r_p2_pre(run, v):
    """P1 の後の作業ツリーの突合で止め、writer の変更として受け付け、撃ち直しの節を済ませる（stray.txt は残したまま）"""
    (run.repo / "stray.txt").write_text("x", encoding="utf-8")
    nx = run.next()
    if nx["ready"]:
        raise RuntimeError(f"波の前提が崩れた: 作業ツリーを汚した next が止まらない: {nx['ready'][:1]}")
    r = _ok(run.cmd("next", "--accept-tree-change", "writer の変更（検査用）"), "next --accept-tree-change")
    for i in json.loads(r.stdout).get("ready", []):
        _ok(run.done(i["id"], v["t"][i["node"]]), f"撃ち直した {i['node']}")


def _r_p2(run, v):
    run.next()
    (run.repo / "stray.txt").unlink()


def _r_p3(run, v):
    """判定役の返答を台本と同じ形（置き場に古い返答・標準入力で件数を書き違えた新しい返答）で通し、修正案と事前審査を済ませる"""
    jd = pending(run)["p2.diagnose"]
    good = v["t"]["p2.diagnose"]
    pathlib.Path(jd["out_path"]).parent.mkdir(parents=True, exist_ok=True)
    pathlib.Path(jd["out_path"]).write_text(json.dumps({**good, "framing": "STALE"}, ensure_ascii=False), encoding="utf-8")
    _ok(run.cmd("done", "--node", jd["id"], "--stdin", "--agent-id", "judge-1",
                input=json.dumps(fresh_judge_reply(good), ensure_ascii=False)), "p2.diagnose")
    nx = run.next()
    for node in ("p2.fix_plan", "p2.plan_review"):
        it = next(i for i in nx["ready"] if i["node"] == node)
        _ok(run.done(it["id"], review.answers(run, "std", nx["round"])[node](None)), node)
        nx = run.next()
    v["fix"] = review.answers(run, "std", nx["round"])["p3.fix"](None)
    v["round"] = nx["round"]


# 判定者の件数の置き換えを見る腕の class_query（台本の test_rejections と同じ値）
ZERO_QUERY = {"how": {"patterns": ["no-such-word"], "paths": ["src/a.py"], "count": "lines"}, "counts": "population", "total": 1}


def fresh_judge_reply(good):
    """台本が標準入力で渡す judge の返答: unit 0 の件数を 3 と書き違え（engine が 1 に置き換える）、unit 1 は 0 件を数える問い"""
    return {**good, "framing": "FRESH", "units": [{**good["units"][0], "class_query": {**good["units"][0]["class_query"], "total": 3}},
                                                  {**good["units"][1], "class_query": ZERO_QUERY}] + good["units"][2:]}


def _s_q_done(run, v):
    q = pending(run)["p0.question"]
    _ok(run.done(q["id"], research.base_answers(run, "std")["p0.question"](None, 1)), "p0.question")


def _s_w3(run, v):
    """調べ役の前後で作業ツリーを汚して拒ませ、理由つきで通し、P0 の残りを済ませる（主張 A だけを太らせる）"""
    by = pending(run)
    (run.repo / "stray.txt").write_text("x", encoding="utf-8")
    if run.done(by["p0.prior_decisions"]["id"], research.base_answers(run, "std")["p0.prior_decisions"](None, 1)).returncode != 1:
        raise RuntimeError("波の前提が崩れた: 作業ツリーを汚した調べ役の done が拒まれない")
    _ok(run.cmd("done", "--node", by["p0.prior_decisions"]["id"], "--output", str(run.tmp / "out.json"),
                "--accept-tree-change", "自分で作った"), "p0.prior_decisions --accept-tree-change")
    (run.repo / "stray.txt").unlink()
    for node in ("p0.claims", "p0.terms", "p5.internal", "p3.rederiver"):
        out = research.base_answers(run, "std")[node](None, 1)
        if node == "p0.claims":
            out = json.loads(json.dumps(out, ensure_ascii=False))
            out["claims"][0]["claim"] += "。" + "あ" * 350
        _ok(run.done(by[node]["id"], out), node)
    run.next()


def _s_w4(run, v):
    cl = pending(run)["p0.clusters"]
    _ok(run.done(cl["id"], research.base_answers(run, "std")["p0.clusters"](None, 1)), "p0.clusters")


def _s_w5b(run, v):
    _ok(run.done("p1.checker[c1]", CHECKER_A_ONLY), "p1.checker[c1]")


# 主張 A だけに判定を返す checker の返答（B が欠けて p1.checker[c1]#2 が出る）
CHECKER_A_ONLY = {"cluster": "c1", "findings": [{"id": "A", "verdict": "確証", "evidence": "e", "sources": ["https://x"], "conditions": "c"}]}
CHECKER_B_CORRECTED = {"cluster": "c1", "findings": [{"id": "B", "verdict": "相違", "evidence": "e", "sources": ["https://x"], "correction": "c"}]}


def _s_w7(run, v):
    _ok(run.done("p1.checker[c1]#2", CHECKER_B_CORRECTED), "p1.checker[c1]#2")


# ---- T2 の筋書きの波の手（台本の関数の前半と hook の写し） ------------------------------------------------------------

def NOHOOK(run, inst, out):
    """research の drive に渡す何もしない hook（None を渡すと drive の中で台本の check が走る）"""
    return None


def _cp(r):
    return {"rc": r.returncode, "out": r.stdout or "", "err": r.stderr or ""}


def _walk(kind, scenario, key="last", hook=None, stop_at=None, catch=None):
    """台本の drive で歩き、最後の next の出力を values[key] に控える。hook は values を受けて hook を返す工場。catch は drive の
    RuntimeError を受けて控える値を返す（台本が例外を握って下の検査へ進む関数の写し。無ければ止める）"""
    def step(run, v):
        mod = review if kind == "review" else research
        h = hook(v) if hook else (NOHOOK if kind == "research" else None)
        try:
            v[key] = mod.drive(run, scenario, hook=h, stop_at=stop_at)
        except RuntimeError as e:
            if catch is None:
                raise
            v[key] = catch(e)
    return step


def _cmd(key, *args):
    """loop.py の語を打って結果を values[key] に控える（拒まれても止めない——拒まれたかを筋書きが見る）"""
    def step(run, v):
        v[key] = _cp(run.cmd(*args))
    return step


def _cmd_ok(*args):
    def step(run, v):
        _ok(run.cmd(*args), " ".join(args[:1]))
    return step


def _seq(*steps):
    def step(run, v):
        for s in steps:
            s(run, v)
    return step


def _state_into(key, get):
    def step(run, v):
        v[key] = get(run)
    return step


def at_node(node):
    return lambda nx: any(i["node"] == node for i in nx["ready"])


def _dropped(e):
    """research の test_stopped_before_gates_reports の drive_to_end: 検証器に落とされた next を赤の 1 件として控える"""
    return {"status": f"落ちた: {str(e)[-200:]}"}


def _patch_one_round(run, v):
    one = run.tmp / "one.json"
    one.write_text("1", encoding="utf-8")
    v["patch"] = _cp(run.cmd("patch", "--path", "state.max_rounds", "--file", str(one), "--reason", "1 周目で止める筋を作る"))


def _await_hook(v):
    """review の test_awaiting: 主経路の観測で見たと嘘をつく返答を 2 通り打ち、拒まれたかを控える"""
    lied = v.setdefault("lied", {})

    def hook(run, inst, out):
        if inst["node"] == "p1.main_path_observation" and "rc" not in lied:
            lie = review.CLEAN("画面は未観測だが異常なし（検査用の嘘）")
            r = run.done(inst["id"], {"material": lie, "observed": []})
            lied["rc"], lied["err"] = r.returncode, r.stderr
            r = run.done(inst["id"], {"material": lie, "observed": [{"path": " ", "value": " "}]})
            lied["blank_rc"], lied["blank_err"] = r.returncode, r.stderr
        return None
    return hook


# review の test_awaiting_origin_guards の問い（筋書きの期待も同じ値を読む）
FIELD_Q = {"key": "Windows の実機で動かしたか", "kind": "field", "status": "held", "reason": "手元にも CI にも Windows の実機が無い（検査用）"}
WAIT_CI = {"key": "CI をどこで走らせるか", "kind": "awaiting", "origin": "local_checks", "status": "held", "reason": "手元で CI を走らせられない（検査用）"}


def _origin_hook(v):
    seen = v.setdefault("seen", {})

    def hook(run, inst, out):
        if inst["node"] == "p0.local_checks":
            return {"material": review.M("awaiting_human", reason="CI 専用のジョブで手元では走らない（検査用）")}
        if inst["node"] == "p2.diagnose" and run.state()["round"] == 1:
            r = run.done(inst["id"], {**out, "questions": [FIELD_Q]}, agent_id="judge-1")
            seen["unlisted"] = [r.returncode, r.stderr]
            if r.returncode == 0:
                raise RuntimeError("人待ちの素材を台帳に載せない判定を受け付けた")
            bad = {**out, "questions": [WAIT_CI, {"key": "Windows の実機で動かしたか", "kind": "awaiting", "origin": "main_path_observation",
                                                  "status": "held", "reason": "（検査用）"}]}
            r = run.done(inst["id"], bad, agent_id="judge-1")
            seen["judge"] = [r.returncode, r.stderr]
            if r.returncode == 0:
                raise RuntimeError("判定の時点の柵が効かなかった")
            return {**out, "questions": [WAIT_CI, FIELD_Q]}
        if inst["node"] == "p4.ci" and run.state()["round"] == 1:
            seen["ci_prompt"] = pathlib.Path(inst["prompt_file"]).read_text(encoding="utf-8")
            r = run.done(inst["id"], {"material": review.CLEAN("pytest 緑（検査用）")})
            seen["ci"] = [r.returncode, r.stderr]
            if r.returncode == 0:
                raise RuntimeError("書いた時点の柵が効かなかった")
            return {"material": review.M("awaiting_human", reason="手元の pytest は緑。CI 専用のジョブは人待ち（検査用）")}
        return None
    return hook


def _noawait_hook(v):
    seen = v.setdefault("seen", {})

    def hook(run, inst, out):
        if inst["node"] == "p4.ci" and "rc" not in seen:
            r = run.done(inst["id"], {"material": review.M("awaiting_human", reason="runner で確かめる話があるので（検査用の取り違え）")})
            seen["rc"], seen["err"] = r.returncode, r.stderr
            if r.returncode == 0:
                raise RuntimeError("柵が効かなかった")
        return None
    return hook


def _empty_gate(v):
    """review の test_final_gate_empty_asks_human: 最後の関門が撃てた腕 0 本を返す"""
    return lambda run, inst, out: {**out, "arms": [], "handled": []} if inst["node"] == "p4.final_gates" else None


def _patch_max_to_asked_round(run, v):
    """上限を、別の run（gate-empty）が 0 本の関門で人に諮った周にする（台本の asked_round を run をまたいで借りる）"""
    asked = v["needs"]["review/gate-empty/asked"]["asked_round"]
    mx = run.tmp / "max.json"
    mx.write_text(json.dumps(asked), encoding="utf-8")
    run.cmd("patch", "--path", "state.max_rounds", "--file", str(mx), "--reason", "台本: 上限の周で 0 本にする")
    v["asked_round"] = asked


def _stale_round_file(run):
    (run.dir / "rounds").mkdir(exist_ok=True)
    (run.dir / "rounds" / "round-1.json").write_text('{"stale": true}', encoding="utf-8")


def _nodecl_run():
    """宣言（graph の stop）の無い graph の写しで回す Run（init の版が古い run）。写しはセッションの置き場の下に置く"""
    gtmp = pathlib.Path(tempfile.mkdtemp(prefix="gl-review-nostop-"))
    for sub in ("prompts", "rules", "graphs", "blocks"):
        shutil.copytree(glharness.PLUGIN / sub, gtmp / sub)
    gp = gtmp / "graphs" / "review-loop.json"
    g = json.loads(gp.read_text(encoding="utf-8"))
    g.pop("stop")
    gp.write_text(json.dumps(g, ensure_ascii=False), encoding="utf-8")
    return review.Run("stop-nodecl", graph=gp)


def _review_stop_end(run, v):
    """review の test_stop_midround の主経路の後半: 止めた節への返答・二度目の stop（どちらも拒まれる）・next の後、最後まで回す"""
    f = run.tmp / "late.json"
    f.write_text("{}", encoding="utf-8")
    run.cmd("done", "--node", "p2.fix_plan", "--output", str(f))
    run.cmd("stop", "--reason", "二度目")
    run.next()
    v["last"] = review.drive(run, "std")


def _resume(run, v):
    """review の test_stop_after_round: 止めた run を next・status・finalize の後で resume する（1 周目の試行を控えて比べる）"""
    run.next()
    run.cmd("status")
    run.cmd("finalize")
    v["r1"] = run.state()["rounds"][0]["instances"]
    v["resume"] = _cp(run.cmd("resume", "--reason", "検査: 続ける", "--stop-after-round", "2"))


# review の test_human_gate の印の字（筋書きの期待も同じ値を読む）
WRITER_POLICY = "修正役が書いた方針（検査用 WRITER-POLICY）"
EXCLUDE_WHY = "この周は触らない（検査用 EXCLUDE-WHY）"


def _gate_hook(v):
    seen = v.setdefault("seen", {})

    def hook(run_, inst, out):
        rnd = run_.state()["round"]
        if inst["node"] == "p2.diagnose" and "diagnose" not in seen:
            seen["diagnose"] = pathlib.Path(inst["prompt_file"]).read_text(encoding="utf-8")
        if inst["node"] == "p2.fix_plan" and rnd == 1:
            return {"plan": [{**out["plan"][0], "narrows": [{"what": "呼び元が上限なしで呼べる経路（検査用 NARROW-1）",
                                                              "why": "上限を入口 1 か所に寄せると呼び元の分岐が消える（検査用）"}]}]}
        if inst["node"] == "p3.fix" and rnd == 1:
            seen["fix"] = pathlib.Path(inst["prompt_file"]).read_text(encoding="utf-8")
            review.put_policy(run_, WRITER_POLICY)   # 役が方針の文書を書き換える形
        if inst["node"] == "p3.delta_review" and "delta" not in seen:
            bad = {**out, "faces": [{"key": "後退: 呼び元の経路", "kind": "regression", "where": "src/a.py", "cite": "limit",
                                     "why": "呼び元の上限なしの経路が消えた（検査用）"}]}
            r = run_.done(inst["id"], bad)
            seen["delta"] = [r.returncode, r.stderr]
        if inst["node"] == "r4.hidden_scope":
            return {**out, "capability_inventory": {"fired": True, "lost": ["呼び元の上限なしの経路（検査用 LOST-1）"]},
                    "policy_conflicts": ["期限を足した（検査用 CONFLICT-1）"]}
        return None
    return hook


def _gate_rest(run, v):
    """人が通すたびに次の関所まで回し、R4 の lost と方針とのぶつかりを聞かれた回数を数える（6 回まで）"""
    asked, kinds, last = {"LOST-1": 0, "CONFLICT-1": 0}, set(), None
    for _ in range(6):
        last = review.drive(run, "std", hook=_gate_hook(v))
        if last["status"] != "awaiting_human":
            break
        for k in asked:
            asked[k] += k in "".join(last["ask"]["items"])
        kinds |= set(last["ask"]["kinds"])
        run.cmd("answer", "--text", "continue", "--note", "消えてよい（検査用）")
    v.update(asked=asked, kinds=sorted(kinds), last=last)


def _face_hook(v):
    def hook(run_, inst, out):
        if inst["node"] == "p2.plan_review":
            return {**out, "faces": [{"key": "後退: 上限なしで呼べる経路が消える", "unit_keys": out["faces"][0]["unit_keys"] if out.get("faces") else [1],
                                      "kind": "regression", "where": "src/a.py", "why": "案が呼び元の分岐を消すと、上限なしの呼び出しができなくなる（検査用）",
                                      "severity": "block"}]}
        return None
    return hook


def _narrow_hook(v):
    seen = v.setdefault("seen", {})

    def hook(run_, inst, out):
        if inst["node"] == "p2.fix_plan":
            return {"plan": [{**out["plan"][0], "narrows": [{"what": "検査用の狭め", "why": "関所を立てるため（検査用）"}]}]}
        if inst["node"] == "p3.fix" and "fix" not in seen:
            seen["fix"] = pathlib.Path(inst["prompt_file"]).read_text(encoding="utf-8")
        return None
    return hook


def _gate_exclude(run, v):
    """関所で --detail の形の誤り（義務に無い単位）を拒ませ、次に義務の単位 1 を外す"""
    bad, good = run.tmp / "bad.json", run.tmp / "good.json"
    bad.write_text(json.dumps({"exclude": [{"unit": "義務に無い単位（検査用）", "why": "外す（検査用）"}]}), encoding="utf-8")
    good.write_text(json.dumps({"exclude": [{"unit": 1, "why": EXCLUDE_WHY}]}), encoding="utf-8")
    v["bad"] = _cp(run.cmd("answer", "--text", "continue", "--note", "通す（検査用）", "--detail", str(bad)))
    v["hi_after_bad"] = list(run.record()["process"]["human_items"])
    v["good"] = _cp(run.cmd("answer", "--text", "continue", "--note", "通す（検査用）", "--detail", str(good)))
    v["unit1"] = run.record()["units"][0]["key"]


def _gate_exclude_to_fix(run, v):
    review.drive(run, "std", hook=_narrow_hook(v), stop_at=lambda n: "fix" in v["seen"])


def _unattended_narrow(v):
    return lambda run_, inst, out: ({"plan": [{**out["plan"][0], "narrows": [{"what": "検査用の狭め", "why": "無人で止まるか（検査用）"}]}]}
                                    if inst["node"] == "p2.fix_plan" else None)


CI_RED = [{"name": "suite", "argv": [review.PY, "-c", "import sys; print('1 failed'); sys.exit(1)"]}]   # engine が走らせて毎周赤
ROUND = lambda k: (lambda nx: nx["round"] >= k)


WAVES = {
    # review の test_rejections（Run("neg")）
    "review/neg/init": (None, None),
    "review/neg/p0": ("review/neg/init", _r_p0),               # 最初の波が出た（P0 の 1 波目）
    "review/neg/p0-settled": ("review/neg/p0", _r_p0_settled),  # 1 波目を済ませ、next の前
    "review/neg/p0b": ("review/neg/p0-settled", _r_next),       # P0 の 2 波目が出た
    "review/neg/p0b-settled": ("review/neg/p0b", _r_p0b_settled),  # 2 波目を済ませ、next の前
    "review/neg/p1": ("review/neg/p0b-settled", _r_next),       # P1 の役の波が出た
    "review/neg/p1-done": ("review/neg/p1", _r_p1_done),        # P1 の役を全部済ませ、next の前
    "review/neg/p2-pre": ("review/neg/p1-done", _r_p2_pre),     # 突合を writer の変更として通し、撃ち直しも済ませた
    "review/neg/p2": ("review/neg/p2-pre", _r_p2),              # 判定役（p2.diagnose）が出た
    "review/neg/p3": ("review/neg/p2", _r_p3),                  # 修正（p3.fix）が出た
    # review の宣言の無いリポジトリ（Run("neg-nodecl", checks=None)）
    "review/nodecl/init": (None, None),
    # research の test_rejections（Run("neg")）
    "research/neg/init": (None, None),
    "research/neg/q": ("research/neg/init", _r_next),           # p0.question が出た
    "research/neg/q-done": ("research/neg/q", _s_q_done),       # p0.question を済ませ、next の前
    "research/neg/w2": ("research/neg/q-done", _r_next),        # P0 の 2 波目が出た
    "research/neg/w3": ("research/neg/w2", _s_w3),              # p0.clusters が出た
    "research/neg/w4": ("research/neg/w3", _s_w4),              # クラスタを済ませ、next の前
    "research/neg/w5": ("research/neg/w4", _r_next),            # checker がクラスタごとに出た
    "research/neg/w5b": ("research/neg/w5", _s_w5b),            # checker[c1] が A だけ返した
    "research/neg/w6": ("research/neg/w5b", _r_next),           # 欠けた分の checker と refuter が出た
    "research/neg/w7": ("research/neg/w6", _s_w7),              # 欠けた分の checker も済んだ

    # ---- T2（層 2 の筋書き）。名前の 2 段目が台本の関数の中の Run 1 つ。(親, 手, 借りる波) の 3 つ目は別の run の波の値を借りる
    # review の test_runaway・test_ci_red_runaway（無人で上限まで）
    "review/runaway/init": (None, None),
    "review/runaway/end": ("review/runaway/init", _walk("review", "runaway")),
    "review/cired/init": (None, None),
    "review/cired/end": ("review/cired/init", _walk("review", "cired")),
    # review の test_no_new_awaiting_after_judge・test_awaiting・test_awaiting_origin_guards（人待ち）
    "review/noawait/init": (None, None),
    "review/noawait/end": ("review/noawait/init", _walk("review", "std", hook=_noawait_hook, stop_at=ROUND(2), catch=lambda e: None)),
    "review/await/init": (None, None),
    "review/await/asked": ("review/await/init", _walk("review", "awaiting", hook=_await_hook, catch=lambda e: None)),
    "review/await/end": ("review/await/asked", _seq(_cmd_ok("answer", "--text", "continue", "--note",
                                                            "テスト用設定 config/dev.local.example で起動できる"),
                                                    _walk("review", "awaiting"))),
    "review/awaitorigin/init": (None, None),
    "review/awaitorigin/end": ("review/awaitorigin/init", _walk("review", "std", key="stopped", hook=_origin_hook, stop_at=ROUND(2),
                                                                catch=lambda e: str(e))),
    # review の test_final_gate_empty_asks_human（最後の関門の 0 本で諮る。2 本目の run は 1 本目が諮った周を上限にする）
    "review/gate-empty/init": (None, None),
    "review/gate-empty/asked": ("review/gate-empty/init", _seq(_walk("review", "std", hook=_empty_gate),
                                                               _state_into("asked_round", lambda run: run.state()["round"]))),
    "review/gate-empty/end": ("review/gate-empty/asked", _seq(_cmd_ok("answer", "--text", "continue", "--note", "文書だけの差分と確かめた（検査用）"),
                                                              _walk("review", "std", hook=_empty_gate))),
    "review/gate-empty-max/init": (None, None),
    "review/gate-empty-max/asked": ("review/gate-empty-max/init", _seq(_patch_max_to_asked_round, _walk("review", "std", hook=_empty_gate)),
                                    ("review/gate-empty/asked",)),
    "review/gate-empty-max/extended": ("review/gate-empty-max/asked", _cmd("answer", "answer", "--text", "continue", "--note", "確かめた（検査用）")),
    "review/gate-empty-max/end": ("review/gate-empty-max/extended", _walk("review", "std", hook=_empty_gate)),
    # review の test_stop_midround（人が途中で止める。通しに残す 10 本の 1 つ）
    "review/stopmid/init": (None, None),
    "review/stopmid/at-fixplan": ("review/stopmid/init", _walk("review", "std", key="at", stop_at=at_node("p2.fix_plan"))),
    "review/stopmid/stopped": ("review/stopmid/at-fixplan", _cmd("stop", "stop", "--reason", "検査: 修正案の前で止める")),
    "review/stopmid/end": ("review/stopmid/stopped", _review_stop_end),
    "review/stopstale/init": (None, None),
    "review/stopstale/at-fixplan": ("review/stopstale/init", _walk("review", "std", key="at", stop_at=at_node("p2.fix_plan"))),
    "review/stopr2/init": (None, None),
    "review/stopr2/at-r2": ("review/stopr2/init", _walk("review", "std", key="at", stop_at=lambda nx: nx["round"] == 2)),
    "review/stopask/init": (None, None),
    "review/stopask/asked": ("review/stopask/init", _walk("review", "premise")),
    "review/stopnodecl/init": (None, None),
    "review/stopnodecl/at-fixplan": ("review/stopnodecl/init", _walk("review", "std", key="at", stop_at=at_node("p2.fix_plan"))),
    "review/stopnodecl/stopped": ("review/stopnodecl/at-fixplan", _seq(_cmd("stop", "stop", "--reason", "検査: 宣言の無い graph"),
                                                                       _state_into("nx", lambda run: run.next()))),
    # review の test_stop_after_round（N 周目で止める）
    "review/stop1/init": (None, None),
    "review/stop1/end1": ("review/stop1/init", _walk("review", "std")),
    "review/stop1/resumed": ("review/stop1/end1", _resume),
    "review/stop1/end2": ("review/stop1/resumed", _walk("review", "std")),
    "review/stop2/init": (None, None),
    "review/stop2/end": ("review/stop2/init", _walk("review", "std")),
    "review/stop1a/init": (None, None),
    "review/stop1a/asked": ("review/stop1a/init", _walk("review", "premise")),
    # review の test_human_gate（人の決定権の関所。主経路は通しに残す 10 本の 1 つ）
    "review/gate/init": (None, None),
    "review/gate/asked1": ("review/gate/init", _walk("review", "std", hook=_gate_hook)),
    "review/gate/answered1": ("review/gate/asked1", _cmd_ok("answer", "--text", "continue", "--note", "呼び元の経路は残せ（検査用 KEEP-NOTE）")),
    "review/gate/asked2": ("review/gate/answered1", _walk("review", "std", hook=_gate_hook)),
    "review/gate/answered2": ("review/gate/asked2", _cmd("answer", "answer", "--text", "continue", "--note", "確かめた（検査用）")),
    "review/gate/end": ("review/gate/answered2", _gate_rest),
    "review/gatestop/init": (None, None),
    "review/gatestop/asked": ("review/gatestop/init", _walk("review", "std", hook=_face_hook)),
    "review/gateex/init": (None, None),
    "review/gateex/asked": ("review/gateex/init", _walk("review", "std", hook=_narrow_hook)),
    "review/gateex/excluded": ("review/gateex/asked", _gate_exclude),
    "review/gateex/fix": ("review/gateex/excluded", _gate_exclude_to_fix),
    "review/gateun/init": (None, None),
    "review/gateun/end": ("review/gateun/init", _walk("review", "std", hook=_unattended_narrow)),
    # research の test_unattended_stuck・test_attended_stuck_answer
    "research/stuck/init": (None, None),
    "research/stuck/end": ("research/stuck/init", _walk("research", "stuck")),
    "research/ask/init": (None, None),
    "research/ask/asked": ("research/ask/init", _walk("research", "stuck")),
    "research/ask/answered": ("research/ask/asked", _cmd_ok("answer", "--text", "escalate")),
    # research の test_gate_arms（上限で止まる・独立導出の岐路で人に聞く）
    "research/coldfail/init": (None, None),
    "research/coldfail/end": ("research/coldfail/init", _walk("research", "coldfail")),
    "research/rederiver/init": (None, None),
    "research/rederiver/end": ("research/rederiver/init", _walk("research", "rederiver_fail")),
    # research の test_stopped_before_gates_reports（上限を 1 周にして、ゲートが走る前に止める。標準は人が stop、重厚は無人）
    "research/early-std/init": (None, None),
    "research/early-std/patched": ("research/early-std/init", _patch_one_round),
    "research/early-std/asked": ("research/early-std/patched", _walk("research", "std", catch=_dropped)),
    "research/early-std/end": ("research/early-std/asked", _seq(_cmd("answer", "answer", "--text", "stop"),
                                                                 _walk("research", "std", catch=_dropped))),
    "research/early-heavy/init": (None, None),
    "research/early-heavy/patched": ("research/early-heavy/init", _patch_one_round),
    "research/early-heavy/end": ("research/early-heavy/patched", _walk("research", "heavy", catch=_dropped)),
    # research の test_stop_midway（人が途中で止める・最初の節の前で止める・途中の finalize）
    "research/stopmid/init": (None, None),
    "research/stopmid/at-checker": ("research/stopmid/init", _walk("research", "std", key="at", stop_at=at_node("p1.checker"))),
    "research/stopmid/stopped": ("research/stopmid/at-checker", _cmd("stop", "stop", "--reason", "検査: 照合の前で止める")),
    "research/stopmid/end": ("research/stopmid/stopped", _seq(lambda run, v: run.next(), _walk("research", "std"))),
    "research/stopfirst/init": (None, None),
    "research/stopfirst/end": ("research/stopfirst/init", _seq(_cmd("stop", "stop", "--reason", "検査: すぐ止める"), _walk("research", "std"))),
    "research/finearly/init": (None, None),
    "research/finearly/at-checker": ("research/finearly/init", _walk("research", "std", key="at", stop_at=at_node("p1.checker"))),
    "research/finearly/finalized": ("research/finearly/at-checker", _cmd("finalize", "finalize")),
}

ROOTS = {
    "review/neg/init": lambda: review.Run("neg"),
    "review/nodecl/init": lambda: review.Run("neg-nodecl", checks=None),
    "research/neg/init": lambda: research.Run("neg"),
    "review/runaway/init": lambda: review.Run("runaway", unattended=True),
    "review/cired/init": lambda: review.Run("cired", unattended=True, checks=CI_RED),
    "review/noawait/init": lambda: review.Run("noawait", checks=None),
    "review/await/init": lambda: review.Run("await"),
    "review/awaitorigin/init": lambda: review.Run("awaitorigin", checks=None),
    "review/gate-empty/init": lambda: review.Run("gate-empty"),
    "review/gate-empty-max/init": lambda: review.Run("gate-empty-max"),
    "review/stopmid/init": lambda: review.Run("stop-mid"),
    "review/stopstale/init": lambda: review.Run("stop-stale"),
    "review/stopr2/init": lambda: review.Run("stop-r2"),
    "review/stopask/init": lambda: review.Run("stop-ask"),
    "review/stopnodecl/init": _nodecl_run,
    "review/stop1/init": lambda: review.Run("stop1", init_args=["--stop-after-round", "1"]),
    "review/stop2/init": lambda: review.Run("stop2", init_args=["--stop-after-round", "2"]),
    "review/stop1a/init": lambda: review.Run("stop1-answer", init_args=["--stop-after-round", "1"]),
    "review/gate/init": lambda: review.Run("gate"),
    "review/gatestop/init": lambda: review.Run("gate-stop"),
    "review/gateex/init": lambda: review.Run("gate-exclude"),
    "review/gateun/init": lambda: review.Run("gate-unattended", unattended=True),
    "research/stuck/init": lambda: research.Run("stuck", unattended=True),
    "research/ask/init": lambda: research.Run("ask"),
    "research/coldfail/init": lambda: research.Run("coldfail", unattended=True),
    "research/rederiver/init": lambda: research.Run("rederiver"),
    "research/early-std/init": lambda: research.Run("stop-early-標準", thickness="標準", unattended=False),
    "research/early-heavy/init": lambda: research.Run("stop-early-重厚", thickness="重厚", unattended=True),
    "research/stopmid/init": lambda: research.Run("stop-mid"),
    "research/stopfirst/init": lambda: research.Run("stop-first"),
    "research/finearly/init": lambda: research.Run("finalize-early"),
}


def lineage(name):
    """波とその祖先（借りた波の祖先も）——被覆の道具（cover_moved.py）が、テストが使った波の作りの行を集めるのに使う"""
    out, todo = [], [name]
    while todo:
        n = todo.pop()
        if n is None or n in out:
            continue
        out.append(n)
        todo += [WAVES[n][0], *(WAVES[n][2] if len(WAVES[n]) > 2 else ())]
    return out


def _kind(name):
    return name.split("/", 1)[0]


def _module(name):
    return review if _kind(name) == "review" else research


def _chain(name):
    return "/".join(name.split("/")[:2])


def _clear_readonly(func, path, _):
    """windows は git の object を読み取り専用で置く——印を外して消し直す（Python の shutil.rmtree の文書の例）"""
    os.chmod(path, stat.S_IWRITE)
    func(path)


def _wipe(path, root):
    """写し戻す直前に作業場を消す。控えの置き場（root）より深いパスだけを消し、外を指したら例外にする。

    parallel.rm は使えない: 基点の gettempdir を、wave の fixture が張る gl_tmp がテストごとの tmp_path に動かし、作業場は
    その外（セッションの置き場）に在る。parallel.rm と違い消し損ねを握り潰さない——残った物があると続く copytree が
    FileExistsError で落ちるか、前の検査の残りが控えに混じる"""
    real, base = os.path.realpath(path), os.path.realpath(root)
    if real == base or os.path.commonpath([real, base]) != base:
        raise ValueError(f"_wipe: 控えの置き場（{base}）より深いパスでないので消さない: {path}")
    shutil.rmtree(path, onexc=_clear_readonly)


class Wave:
    """控えから始めた 1 つの波: 台本の Run（run）と、作るときに控えた JSON の値（values）"""

    def __init__(self, run, values):
        self.run, self.values = run, values

    def pending(self):
        return pending(self.run)


class Waves:
    """worker ごとの控えの置き場。波は要ったときに 1 度だけ作る（親の波の控えから始めて手を 1 つ進める）"""

    def __init__(self, root):
        self.root = pathlib.Path(root)
        self.runs = {}      # 筋書き（review/neg など）→ 作業場を持つ Run（作業場の置き場は筋書きごとに 1 か所）
        self.values = {}    # 波 → JSON の値の控え

    def _snap(self, name):
        return self.root / "snap" / name.replace("/", "__")

    def _restore(self, name):
        run = self.runs[_chain(name)]
        _wipe(run.tmp, self.root)
        shutil.copytree(self._snap(name), run.tmp, symlinks=True)
        return run

    def build(self, name):
        if name in self.values:
            return
        parent, step, *rest = WAVES[name]
        needs = rest[0] if rest else ()
        for n in needs:
            self.build(n)
        mod = _module(name)
        with glharness.driven(mod, "inproc"):
            if parent is None:
                live = self.root / "live"
                live.mkdir(exist_ok=True)
                saved = tempfile.tempdir
                tempfile.tempdir = str(live)   # 台本の作業場（parallel.workspace）をセッションの置き場の下に作る
                try:
                    run = ROOTS[name]()
                finally:
                    tempfile.tempdir = saved
                _ok(run.init, f"{name} の init")
                self.runs[_chain(name)] = run
                values = {}
            else:
                self.build(parent)
                run = self._restore(parent)
                values = json.loads(json.dumps(self.values[parent]))
                if needs:
                    values["needs"] = {n: json.loads(json.dumps(self.values[n])) for n in needs}
                step(run, values)
        shutil.copytree(run.tmp, self._snap(name), symlinks=True)
        self.values[name] = values

    def get(self, name):
        self.build(name)
        return Wave(self._restore(name), json.loads(json.dumps(self.values[name])))


# ---- 層 2 の筋書きの行（given・when・then） ---------------------------------------------------------------------------

def row(script, head, given, then, when=None, *, id, kept=None):
    """筋書きの 1 行: given は波の名前（None なら波から始めない）、when は Wave を受けて 1 手を打つ関数（返りを then が受ける）、
    then は (Wave, when の返り) を受ける手書きの述語。印 moved_from で台本の check 1 件を名乗る"""
    return pytest.param(given, when, then, id=id, marks=pytest.mark.moved_from(script, head, **({"kept": kept} if kept else {})))


def play(wave, given, when, then):
    w = wave(given) if given else None
    got = when(w) if when else None
    last = (w.values.get("last") or {}) if w else {}
    assert then(w, got), f"status={last.get('status')} ask={(last.get('ask') or {}).get('kinds')} round={last.get('round')} got={str(got)[:300]}"


def pytest_configure(config):
    config.addinivalue_line("markers", "layer2: 層 2 の筋書き（控えた波から盤面を何周も回す medium。手元の反復は -m 'not layer2' で外せる）")


def pytest_addoption(parser):
    parser.addoption("--gl-prebuild-waves", action="store_true", default=False,
                     help="波を全部、最初に wave を使うテストの準備（setup）の段で作る（既定は要ったときに作る）。被覆を測る道具"
                          "（cover_moved.py）が、波を作る行を検査の本体（run）と分けて数えるために使う")


@pytest.fixture(scope="session")
def gl_waves(tmp_path_factory, request):
    w = Waves(tmp_path_factory.mktemp("waves"))
    if request.config.getoption("--gl-prebuild-waves"):
        for name in WAVES:
            w.build(name)
    return w


@pytest.fixture
def wave(gl_waves, gl_tmp, request):
    """控えた波から始める: wave("review/neg/p2") が Wave を返す。検査の間は台本 2 本とも inproc の口で loop.py を呼ぶ。
    使った波はテストの user_properties に ("gl_wave", 名前) で積む（junitxml に載り、cover_moved.py が台本ごとの波の作りを選ぶ）"""
    def get(name):
        request.node.user_properties.append(("gl_wave", name))
        return gl_waves.get(name)
    with contextlib.ExitStack() as stack:
        stack.enter_context(glharness.driven(review, "inproc"))
        stack.enter_context(glharness.driven(research, "inproc"))
        yield get
