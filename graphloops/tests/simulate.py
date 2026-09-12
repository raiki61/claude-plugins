#!/usr/bin/env python3
"""engine を、役の返答を台本で差し替えて端から端まで回す（役割 agent も LLM も使わない）。

確かめるのは engine と rules と graph の噛み合わせ——波の順・扇の被覆・件数突合・連続カウント・
ゲートの条件・抜き取り・収束と停止・記録が検証器（convergence-loops の research-record.py）を通ること。
役の判断の質は見ない（それは実走で見る）。

使い方: python3 simulate.py            # 全部の台本と否定検査を回す。失敗があれば exit 1
"""
import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile

# Windows の既定の標準出力は cp1252（日本語 Windows なら cp932）で、日本語を print すると
# UnicodeEncodeError で落ちる。リポジトリの他の出力スクリプトと同じ型に揃える。
for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8")

HERE = pathlib.Path(__file__).resolve().parent
PLUGIN = HERE.parent
LOOP = PLUGIN / "scripts" / "loop.py"
GRAPHCHECK = PLUGIN / "scripts" / "graphcheck.py"
VALIDATOR = PLUGIN.parent / "scripts" / "research-record.py"
PY = sys.executable

fails = []
ran = 0


def check(cond, desc):
    global ran
    ran += 1
    if cond:
        print(f"  ok   {desc}")
    else:
        print(f"  FAIL {desc}")
        fails.append(desc)


def rm(p):
    """作業場の掃除。Windows は git の object を読み取り専用で置き、素の rmtree が PermissionError で
    落ちる（実測: CI の windows-latest）。掃除の失敗で検査本体を落とさない。"""
    shutil.rmtree(p, ignore_errors=True)


class Run:
    def __init__(self, name, thickness=None, decider=None, unattended=False):
        self.tmp = pathlib.Path(tempfile.mkdtemp(prefix=f"gl-{name}-"))
        self.repo = self.tmp / "repo"
        self.repo.mkdir()
        subprocess.run(["git", "init", "-q"], cwd=self.repo, check=True)
        subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "--allow-empty", "-m", "init"], cwd=self.repo, check=True)
        self.doc = self.repo / "mitate.md"
        self.doc.write_text("# 見立て\n\n主張 A・B・C・D を含む見立て文書。\n", encoding="utf-8")
        subprocess.run(["git", "add", "."], cwd=self.repo, check=True)
        subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "-m", "doc"], cwd=self.repo, check=True)
        self.dir = self.tmp / "state"
        args = ["init", "--loop", "research-loop", "--request", "この見立ては正しいか", "--document", str(self.doc),
                "--dir", str(self.dir), "--validator", str(VALIDATOR)]
        if thickness:
            args += ["--thickness", thickness]
        if decider:
            args += ["--decider", decider]
        if unattended:
            args.append("--unattended")
        self.init = self.cmd(*args)

    def cmd(self, *args, stdin=None, env=None):
        r = subprocess.run([PY, str(LOOP), *args, *([] if args[0] == "init" else ["--dir", str(self.dir)])],
                           cwd=self.repo, capture_output=True, text=True, encoding="utf-8", input=stdin, env=env)
        return r

    def next(self):
        r = self.cmd("next")
        if r.returncode != 0:
            raise RuntimeError(f"next が {r.returncode}: {r.stderr}")
        return json.loads(r.stdout)

    def done(self, node, output):
        f = self.tmp / "out.json"
        f.write_text(json.dumps(output, ensure_ascii=False), encoding="utf-8")
        return self.cmd("done", "--node", node, "--output", str(f))

    def record(self):
        return json.loads(self.cmd("record").stdout)

    def status(self):
        return json.loads(self.cmd("status").stdout)

    def state(self):
        return json.loads((self.dir / "state.json").read_text(encoding="utf-8"))


# ---------------------------------------------------------------- 台本
def constraints(origin="独立出典"):
    return [{"text": "対象は 1 リポジトリ", "source": "依頼文", "origin": origin, "breaks_if_false": "範囲が変わる"}]


def base_answers(run, scenario):
    """節ごとの返答。scenario で分岐する台本。"""
    rec = run.record()

    def claim_verdict(cid):
        return next(c for c in rec["claims"] if c["id"] == cid)

    def checker(item, rnd):
        out = []
        for c in item["claims"]:
            cid = c["id"]
            if cid == "B" and rnd == 1:
                out.append({"id": cid, "verdict": "相違", "evidence": "一次情報は逆", "sources": ["https://x/b"], "correction": "B は逆"})
            elif cid == "B" and scenario == "stuck":
                out.append({"id": cid, "verdict": "相違", "evidence": "まだ逆", "sources": ["https://x/b"], "correction": "B は逆"})
            elif cid == "C":
                out.append({"id": cid, "verdict": "留保", "evidence": "概ね", "sources": ["https://x/c"], "correction": "限定を付ける"})
            elif cid == "E":
                out.append({"id": cid, "verdict": "検証不能", "evidence": "到達できず", "sources": [], "needs": "原典"})
            else:
                # 実物の checker が返す任意欄（source_grade）も台本に持つ——代役が実物より薄いと、その欄の扱いが検査の外に落ちる
                out.append({"id": cid, "verdict": "確証", "evidence": "一致", "sources": [f"https://x/{cid.lower()}"], "conditions": "条件つき", "source_grade": "公式一次"})
        return {"cluster": item["key"], "findings": out}

    def sampler(item):
        out = []
        for c in item["claims"]:
            v = claim_verdict(c["id"])["verdict"]
            f = {"id": c["id"], "verdict": v, "evidence": "再検証", "sources": ["https://x/s"]}
            f[{"確証": "conditions", "相違": "correction", "留保": "correction", "検証不能": "needs"}[v]] = "同じ"
            out.append(f)
        return {"findings": out}

    return {
        "p0.question": lambda it, r: {"question": "この見立ては正しいか", "domain": "設計文書の校正", "constraints": constraints(),
                                       "thickness": scenario_thickness(scenario), "thickness_decider": "既定", "thickness_reason": "後戻りが中程度",
                                       "open_questions": ["選択肢の洗い出し"] if scenario == "open" else []},
        "p0.claims": lambda it, r: {"claims": [{"id": "A", "claim": "A は X", "load_bearing": True}, {"id": "B", "claim": "B は Y", "load_bearing": False},
                                               {"id": "C", "claim": "C は Z", "load_bearing": False}, {"id": "D", "claim": "D は W", "load_bearing": False}],
                                    "judgments": [{"text": "好み"}], "judgments_as_facts": [], "open_questions": []},
        "p0.clusters": lambda it, r: {"clusters": [{"key": "c1", "claim_ids": ["A", "B"]}, {"key": "c2", "claim_ids": ["C", "D"]}]},
        "p0.terms": lambda it, r: {"terms": [{"term": "見立て", "definition": "設計の仮説", "status": "社内造語"}]},
        "p0.prior_decisions": lambda it, r: {"checked": True, "searched": ["gh issue list"], "settled_points": [], "overlaps": [], "reopen_proposals": []},
        "p0.independence_review": lambda it, r: {"verdict": "問題なし", "reason": "狭めていない", "findings": []},
        "p0.generation": lambda it, r: {"claims": [{"id": "G1", "cluster": "c1", "claim": "生成した主張", "load_bearing": False, "heuristic": "逆転"}]},
        "p5.internal": lambda it, r: {"facts": [{"constraint_text": "対象は 1 リポジトリ", "verified": True, "actual": "1 つ", "location": ".git"}],
                                       "corrections": [{"text": "内部の実態の訂正"}]},
        "p1.checker": lambda it, r: checker(it, r),
        "p1.refuter": lambda it, r: ({"id": it["id"], "mode": "dispute", "upheld": True, "verdict": "相違", "refuter_reasoning": "本物", "sources": ["https://x/r"], "correction": "B は逆（確定）"}
                                     if it["mode"] == "dispute" else
                                     {"id": it["id"], "mode": "confirm", "upheld": True, "verdict": "確証", "refuter_reasoning": "崩れない", "sources": ["https://x/r"], "conditions": "条件つき"}),
        "p2.integrate": lambda it, r: {"root_causes": [], "corrections": [{"text": f"{r} 周目の訂正", "claim_ids": ["B"]}] if r == 1 else [],
                                        "applied": [{"claim_id": "B", "stable_key": "B:逆", "where": "mitate.md"}] if r == 1 else [],
                                        "numbers": [{"value": "4 件", "source": "記録"}] if r == 1 else [], "terms": [],
                                        "new_claims": [{"id": "E", "cluster": "c2", "claim": "E は V", "load_bearing": False, "origin": "対抗仮説"}] if (scenario == "newclaim" and r == 1) else [],
                                        "recheck_ids": [], "claim_updates": [{"id": "B", "claim": "B は逆"}] if r == 1 else [], "document_changed": r == 1},
        "p3.rederiver": lambda it, r: {"question_stands": True, "verdict": "pass", "reason": "問いは立っている", "derivation": "固定: 問い／派生: 手段"},
        "p3.rederiver_compare": lambda it, r: ({"verdict": "redesign-needed", "reason": "問いの立て方が違う", "differences": [{"kind": "構造", "text": "固定と派生が逆"}]}
                                               if scenario == "rederiver_fail" else
                                               {"verdict": "pass", "reason": "構造は一致", "differences": [{"kind": "表現", "text": "語が違う"}]}),
        "p3.cartographer": lambda it, r: {"map": [{"aspect": "費用", "components": ["時間"], "depends_on": []}]},
        "p3.cartographer_compare": lambda it, r: {"verdict": "pass", "reason": "盲点なし", "spots": []},
        "p3.cold_reader": lambda it, r: ({"verdict": "redesign-needed", "findings": [{"kind": "未定義語", "where": "冒頭", "text": "見立てが未定義"}]}
                                         if ((r == 2 and scenario != "stuck") or scenario == "coldfail") else {"verdict": "pass", "findings": []}),
        "p3.sampling": lambda it, r: sampler(it),
        "p5.adapt": lambda it, r: {"decide_now": [{"text": "今決める", "basis": "確証×制約", "premortem": ["前提が偽"], "tripwire": "数が変わる"}],
                                    "poc": [], "human_only": [{"text": "事業判断", "options": [{"option": "a", "consequence": "b"}]}]},
        "report": lambda it, r: "# 報告\n\n平易版。\n",
        "reflect": lambda it, r: {"notes": "型は外れなかった", "proposed_changes": [{"target": "none", "text": ""}]},
    }


def scenario_thickness(s):
    return "重厚" if s == "heavy" else "標準"


def drive(run, scenario, max_steps=60, hook=None):
    """next → 台本で done を、止まるか終わるまで。返り値は最後の next の出力。"""
    last = None
    for _ in range(max_steps):
        nx = run.next()
        last = nx
        if nx.get("status") == "awaiting_human" or (not nx["ready"] and nx["status"] in ("converged", "stopped")):
            return nx
        if not nx["ready"]:
            raise RuntimeError("ready が空のまま進まない: " + json.dumps(nx, ensure_ascii=False)[:600])
        answers = base_answers(run, scenario)
        for inst in nx["ready"]:
            node = inst["node"]
            if hook is None and node == "p2.integrate":
                ptxt = pathlib.Path(inst["prompt_file"]).read_text(encoding="utf-8")
                check("record.json" in ptxt and '"claims": [' not in ptxt, "統合の節には記録の本文でなく置き場と要約が渡る")
            if hook is None and inst["mode"] == "agent" and nx["round"] == 1 and node in ("p1.checker", "p3.cold_reader"):
                want = "path" if node == "p1.checker" else "paste"
                check(inst.get("deliver") == want, f"{node} の渡し方は {want}（役の道具から決まる）")
            out = answers[node](inst["item"], nx["round"])
            if hook:
                out = hook(run, inst, out) or out
            if isinstance(out, str):
                f = run.tmp / "out.txt"
                f.write_text(out, encoding="utf-8")
                r = run.cmd("done", "--node", inst["id"], "--output", str(f))
            else:
                r = run.done(inst["id"], out)
            if r.returncode != 0:
                raise RuntimeError(f"done {inst['id']} が {r.returncode}: {r.stderr}")
    raise RuntimeError("max_steps に達した")


# ---------------------------------------------------------------- 検査
def test_converges():
    print("台本: 標準・3 周で収束")
    run = Run("std")
    check(run.init.returncode == 0, "init が通る")
    last = drive(run, "std")
    rec, st = run.record(), run.state()
    check(last["status"] == "converged", "status が converged")
    check(rec["convergence"] == {"rounds_total": 3, "consecutive_zero": 2, "outcome": "converged"}, f"convergence が 3 周・連続 2: {rec['convergence']}")
    check([r["verdict"] for r in rec["gates"]["cold_reader"]["rounds"]] == ["redesign-needed", "pass"], "cold_reader が 2 周（redesign→pass）")
    check(rec["gates"]["rederiver"]["verdict"] == "pass", "rederiver は比較係の pass")
    check(rec["gates"]["cartographer"].get("status") == "not_applicable", "標準では cartographer は not_applicable")
    check(rec["sampling"]["status"] == "done" and rec["sampling"]["overturned"] == 0, f"抜き取りが走り覆り 0: {rec['sampling']}")
    check(next(c for c in rec["claims"] if c["id"] == "B")["verdict"] == "確証", "B は再照合で確証に戻った")
    check(next(c for c in rec["claims"] if c["id"] == "A")["refuted"] is True, "荷重の確証 A は反証を経た")
    check([c["no"] for c in rec["corrections"]] == [1, 2], f"訂正の番号は機械が連番で振る: {[c['no'] for c in rec['corrections']]}")
    check((run.dir / "report.md").is_file(), "report.md が保存された")
    v = subprocess.run([PY, str(VALIDATOR), str(run.dir / "record.json")], capture_output=True, text=True, encoding="utf-8")
    check(v.returncode == 0, f"検証器が exit 0（{v.stdout.strip()[:60]}）")
    r1 = st["rounds"][0]
    check("p0.independence_review" in r1["na"], "独立出典だけなので independence_review は na")
    check(any(i.startswith("p1.refuter[A]") for i in r1["instances"]) and any(i.startswith("p1.refuter[B]") for i in r1["instances"]), "refuter は A（荷重確証）と B（相違）に走った")
    check("p1.checker" in st["rounds"][2]["empty"], "3 周目の checker は項目ゼロ（empty）")
    check(len(rec["process"]["skipped"]) == 0, "省略なし")
    rm(run.tmp)


def test_unattended_stuck():
    print("台本: 無人・stuck で保守的に停止")
    run = Run("stuck", unattended=True)
    last = drive(run, "stuck")
    rec = run.record()
    check(last["status"] == "stopped", "status が stopped")
    check(rec["convergence"]["outcome"] == "stopped" and "無人実行" in rec["convergence"]["stopped_reason"], f"stopped_reason: {rec['convergence'].get('stopped_reason', '')[:40]}")
    check(any("stuck" in str(x) for x in rec["process"]["human_items"]), "要人間判断に stuck が載る")
    check((run.dir / "report.md").is_file(), "停止でも報告は出る（検証器は stopped を通す）")
    rm(run.tmp)


def test_attended_stuck_answer():
    print("台本: 有人・stuck で諮り、escalate で重厚に上げて続行")
    run = Run("ask")
    last = drive(run, "stuck")
    check(last["status"] == "awaiting_human" and "stuck" in last["ask"]["kinds"], "人に聞く番になる")
    r = run.cmd("answer", "--text", "escalate")
    check(r.returncode == 0, "answer escalate が通る")
    st = run.status()
    check(st["thickness"] == "重厚" and st["round"] == 3, f"重厚で 3 周目に入る: {st['thickness']} r{st['round']}")
    nx = run.next()
    check(any(i["node"] == "p0.generation" for i in nx["ready"]), "stuck 後の重厚では断面の生成が開く")
    check(any(i["node"] == "p3.cartographer" for i in nx["ready"]), "重厚に上がると cartographer が序盤に出る")
    rm(run.tmp)


def test_light():
    print("台本: 軽量は 1 周で打ち切り")
    r = Run("light-bad", thickness="軽量")
    check(r.init.returncode == 2, "軽量は --decider 依頼者指定 が無いと init を拒む")
    rm(r.tmp)
    run = Run("light", thickness="軽量", decider="依頼者指定")
    answers_patch = lambda run_, inst, out: ({**out, "thickness": "軽量", "thickness_decider": "依頼者指定"} if inst["node"] == "p0.question" else out)
    last = drive(run, "light", hook=answers_patch)
    rec = run.record()
    check(last["status"] == "stopped" and "軽量" in rec["convergence"]["stopped_reason"], "軽量は stopped（収束を名乗らない）")
    check(rec["gates"]["rederiver"].get("status") == "not_applicable" and "軽量" in rec["gates"]["rederiver"]["reason"], "ゲートは not_applicable で理由に軽量")
    st = run.state()
    check("p5.internal" in st["rounds"][0]["na"] and "p0.prior_decisions" in st["rounds"][0]["na"], "軽量では P0-6 と内部突合が na")
    check((run.dir / "report.md").is_file(), "軽量でも報告は出る")
    rm(run.tmp)


def test_rejections():
    print("否定検査: engine が受け付けないもの")
    run = Run("neg")
    nx = run.next()
    q = nx["ready"][0]
    check(q["node"] == "p0.question" and q["mode"] == "runner", "最初の節は p0.question（回す側）")
    r = run.done(q["id"], {"question": "x"})
    check(r.returncode == 1 and "必須の欄" in r.stderr, "型に合わない返答は exit 1")
    r = run.done(q["id"], {**base_answers(run, "std")["p0.question"](None, 1), "thickness": "軽量"})
    check(r.returncode == 1 and "下げようとしている" in r.stderr, "回す側の降格は exit 1")
    r = run.done(q["id"], base_answers(run, "std")["p0.question"](None, 1))
    check(r.returncode == 0, "正しい返答は通る")
    r = run.done(q["id"], base_answers(run, "std")["p0.question"](None, 1))
    check(r.returncode == 1 and "既に" in r.stderr, "同じ節に 2 回 done は exit 1（回し直しの禁止）")
    r = run.cmd("skip", "--node", "p0.claims", "--reason", "面倒")
    check(r.returncode == 1 and "optional でない" in r.stderr, "optional でない節は省けない")
    nx = run.next()
    by = {i["node"]: i for i in nx["ready"]}
    check({"p0.claims", "p0.terms", "p0.prior_decisions", "p5.internal", "p3.rederiver"} <= set(by), f"2 波目に P0 の残りと先行起動が並ぶ: {sorted(by)}")
    check(by["p0.prior_decisions"]["agent_type"] == "convergence-loops:investigator", "調べ役の agent_type は convergence-loops: 接頭")
    # investigator の前後で作業ツリーが変わると拒む
    (run.repo / "stray.txt").write_text("x", encoding="utf-8")
    r = run.done(by["p0.prior_decisions"]["id"], base_answers(run, "std")["p0.prior_decisions"](None, 1))
    check(r.returncode == 1 and "作業ツリーが変わっている" in r.stderr, "investigator の前後で作業ツリーが変わると exit 1")
    r = run.cmd("done", "--node", by["p0.prior_decisions"]["id"], "--output", str(run.tmp / "out.json"), "--accept-tree-change", "自分で作った")
    check(r.returncode == 0, "理由付きなら通る（痕跡が残る）")
    (run.repo / "stray.txt").unlink()
    st = run.state()
    check(st["git_mismatches"][0]["accepted"] == "自分で作った", "git_mismatches に理由が残る")
    # 穴の宣言: プロンプトに reads に無い穴があると engine が止まる（graph を壊して確かめる）
    prompts = pathlib.Path(by["p0.claims"]["prompt_file"]).read_text(encoding="utf-8")
    check("主張 A・B・C・D" in prompts and "見立て文書" in prompts, "プロンプトに文書本文が貼られている（file: の穴）")
    check("open_questions" not in prompts or "[]" in prompts, "前の節の出力の穴が埋まっている")
    for node in ("p0.claims", "p0.terms", "p5.internal", "p3.rederiver"):
        run.done(by[node]["id"], base_answers(run, "std")[node](None, 1))
    nx = run.next()
    cl = next(i for i in nx["ready"] if i["node"] == "p0.clusters")
    r = run.done(cl["id"], {"clusters": [{"key": "c1", "claim_ids": ["A", "B"]}]})
    check(r.returncode == 1 and "どのクラスタにも入っていない" in r.stderr, "クラスタに入れ漏れた主張があると exit 1")
    run.done(cl["id"], base_answers(run, "std")["p0.clusters"](None, 1))
    rec = run.record()
    check([c["claims_submitted"] for c in rec["clusters"]] == [2, 2], "claims_submitted は機械が数える")
    nx = run.next()
    ch = {i["item"]["key"]: i for i in nx["ready"] if i["node"] == "p1.checker"}
    check(set(ch) == {"c1", "c2"}, "checker はクラスタごとに並ぶ")
    body = pathlib.Path(ch["c1"]["prompt_file"]).read_text(encoding="utf-8").split("返答はこの JSON Schema")[0]
    check("A は X" in body and "C は Z" not in body and '"verdict":' not in body and "surveyor" not in body, "checker には自分の束の主張だけ、判定も見立ても貼られない")
    r = run.done(ch["c1"]["id"], {"cluster": "c1", "findings": [{"id": "Z", "verdict": "確証", "evidence": "e", "sources": ["https://x"], "conditions": "c"}]})
    check(r.returncode == 1 and "項目に無い" in r.stderr, "扇の被覆: 渡した項目に無い id を返すと exit 1（cover の腕）")
    r = run.done(ch["c1"]["id"], {"cluster": "c1", "findings": [{"id": "A", "verdict": "確証", "evidence": "e", "sources": ["https://x"], "conditions": "c"}]})
    check(r.returncode == 0 and "欠けた" in r.stdout and "p1.checker[c1]#2" in r.stdout, "判定が欠けた主張は欠けた分だけ出し直す")
    r = run.done(ch["c1"]["id"], {"cluster": "c1", "findings": []})
    check(r.returncode == 1, "済んだ instance にはもう done できない")
    nx = run.next()
    ids = [i["id"] for i in nx["ready"]]
    check("p1.checker[c1]#2" in ids and "p1.refuter[A]" in ids, f"欠けた分の checker と、返った分の refuter が同じ波に出る（pipeline）: {ids}")
    r = run.done("p1.refuter[A]", {"id": "A", "mode": "confirm", "upheld": True, "verdict": "相違", "refuter_reasoning": "x", "sources": ["https://x"], "correction": "y"})
    check(r.returncode == 1 and "整合" in r.stderr, "refuter の upheld と verdict の食い違いは exit 1")
    r = run.done("p1.checker[c1]#2", {"cluster": "c1", "findings": [{"id": "B", "verdict": "相違", "evidence": "e", "sources": ["https://x"]}]})
    check(r.returncode == 1 and "correction" in r.stderr, "相違に correction が無いと exit 1（検証器の規則を先取り）")
    r = run.done("p1.checker[c1]#2", {"cluster": "c1", "findings": [{"id": "B", "verdict": "相違", "evidence": "e", "sources": ["https://x"], "correction": "c"}]})
    check(r.returncode == 0, "欄が揃えば通る")
    # 記録の手当ては痕跡が残る
    (run.tmp / "p.json").write_text('"x"', encoding="utf-8")
    r = run.cmd("patch", "--path", "process.note", "--file", str(run.tmp / "p.json"), "--reason", "試験")
    check(r.returncode == 0 and run.state()["patches"][0]["reason"] == "試験", "patch は痕跡付き")
    rm(run.tmp)


def test_graphcheck():
    print("graphcheck: 正しい graph は通り、壊した graph は腕ごとに NG の診断文を出して落ちる（例外で死なない）")
    g = json.loads((PLUGIN / "graphs" / "research-loop.json").read_text(encoding="utf-8"))
    r = subprocess.run([PY, str(GRAPHCHECK), str(PLUGIN / "graphs" / "research-loop.json"), str(VALIDATOR)], capture_output=True, text=True, encoding="utf-8")
    check(r.returncode == 0, "research-loop.json は通る")
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="gl-gc-"))
    (tmp / "graphs").mkdir()
    shutil.copytree(PLUGIN / "prompts", tmp / "prompts")
    shutil.copytree(PLUGIN / "rules", tmp / "rules")
    n = [0]

    def broken(mutate, want, desc, validator=str(VALIDATOR)):
        """graph を 1 か所壊して graphcheck に通す。腕ごとに 1 行で足せる（壊し方・期待する診断文・説明）。"""
        bad = json.loads(json.dumps(g))
        mutate(bad)
        n[0] += 1
        p = tmp / "graphs" / f"bad{n[0]}.json"
        p.write_text(json.dumps(bad, ensure_ascii=False), encoding="utf-8")
        r = subprocess.run([PY, str(GRAPHCHECK), str(p), *([validator] if validator else [])], capture_output=True, text=True, encoding="utf-8")
        check(r.returncode == 1 and want in r.stdout and "Traceback" not in r.stderr, f"{desc}（NG『{want}』で exit 1）")

    broken(lambda b: b["nodes"]["p2.integrate"]["writes"].append({"op": "set", "to": "gates.rederiver", "from": "root_causes"}), "判定の欄", "回す側が gates に書く graph は落ちる")
    broken(lambda b: b["nodes"]["p1.checker"]["reads"].append("record"), "record 全体", "fresh_context の節が record 全体を読む graph は落ちる")
    broken(lambda b: b["nodes"]["p0.claims"]["reads"].append("out.p2.integrate"), "前の節でない", "後の節の出力を読む graph は落ちる")
    broken(lambda b: b["nodes"]["p1.refuter"].__setitem__("post_check", "nope"), "POST_CHECKS に無い", "rules に無い名前を指す graph は落ちる")
    # errs に溜める側の腕（以前は errs の束縛が後ろにあり UnboundLocalError で診断文が出なかった 8 経路）
    broken(lambda b: b.pop("runners"), "runners", "runners の無い graph は落ちる")
    broken(lambda b: b.__setitem__("agent_prefix", "x"), "agent_prefix", "廃止した agent_prefix を持つ graph は落ちる")
    broken(lambda b: b.__setitem__("plugin", "no-such-plugin"), "役割 agent の定義", "役の定義が見つからない plugin を指す graph は落ちる")
    broken(lambda b: b.pop("launch"), "launch.isolated.argv", "道具ゼロの役を使うのに起こし方を宣言しない graph は落ちる")
    broken(lambda b: b["nodes"]["p1.checker"].__setitem__("run_by", "nobody"), "run_by", "回す側でも役でもない run_by は落ちる")
    broken(lambda b: b["nodes"]["p1.checker"]["writes"][0].__setitem__("stamp_round", True), "stamp_round", "stamp_round に真偽値を書く graph は落ちる（欄の名前だけ）")
    # 段名の正本は thickness.tiers——キーの集合から導かない
    broken(lambda b: b["thickness"].__setitem__("default", "超重厚"), "超重厚", "thickness.default が段に無い graph は落ちる")
    broken(lambda b: b["nodes"]["p0.generation"].__setitem__("active_in", ["deciders"]), "deciders", "thickness のキー名（deciders）を段として使う graph は落ちる")
    # 検証器の欄との突合は省略で通さない
    broken(lambda b: b["record"].__setitem__("validator_path", "scripts/no-such-record.py"), "見つからない", "検証器のパスが解決できない graph は落ちる（第 2 引数なし）", validator=None)
    broken(lambda b: None, "必須欄が 1 つも拾えない", "必須欄を持たないファイルを検証器として渡すと落ちる（0 個の突合を合格にしない）", validator=str(PLUGIN / "engine" / "util.py"))
    for other in ("review", "doctor", "firstread"):
        r = subprocess.run([PY, str(GRAPHCHECK), str(PLUGIN / "graphs" / f"{other}-loop.json")], capture_output=True, text=True, encoding="utf-8")
        check(r.returncode == 0, f"{other}-loop.json（写しだけ）は写しの形の検査だけで通る")
    rm(tmp)


def test_bad_builtin():
    print("否定検査: 機械の節の返りが {ok: 真偽値} でも {decision: …} でもなければ die")
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="gl-bb-"))
    shutil.copytree(PLUGIN / "prompts", tmp / "prompts")
    shutil.copytree(PLUGIN / "rules", tmp / "rules")
    (tmp / "graphs").mkdir()
    r = (tmp / "rules" / "research-loop.py")
    r.write_text(r.read_text(encoding="utf-8") +
                 '\n\ndef shapeless(b, nid):\n    return {"nope": 1}\n\n\nBUILTINS["shapeless"] = shapeless\n', encoding="utf-8")
    g = json.loads((PLUGIN / "graphs" / "research-loop.json").read_text(encoding="utf-8"))
    g["nodes"]["p1.record_check"]["builtin"] = "shapeless"
    (tmp / "graphs" / "bad.json").write_text(json.dumps(g, ensure_ascii=False), encoding="utf-8")
    run = Run("badbuiltin")
    d2 = run.tmp / "s2"
    init = subprocess.run([PY, str(LOOP), "init", "--loop", "research-loop", "--graph", str(tmp / "graphs" / "bad.json"),
                           "--request", "q", "--document", str(run.doc), "--dir", str(d2), "--validator", str(VALIDATOR)],
                          cwd=run.repo, capture_output=True, text=True, encoding="utf-8")
    seen = ""
    for _ in range(40):
        nx = subprocess.run([PY, str(LOOP), "next", "--dir", str(d2)], cwd=run.repo, capture_output=True, text=True, encoding="utf-8")
        seen += nx.stderr
        if nx.returncode != 0 or not nx.stdout.strip():
            break
        out = json.loads(nx.stdout)
        if not out["ready"]:
            break
        answers = base_answers(run, "std")
        for inst in out["ready"]:
            o = answers[inst["node"]](inst["item"], out["round"])
            f = run.tmp / "o.json"
            f.write_text(json.dumps(o, ensure_ascii=False) if not isinstance(o, str) else o, encoding="utf-8")
            subprocess.run([PY, str(LOOP), "done", "--node", inst["id"], "--output", str(f), "--dir", str(d2)],
                           cwd=run.repo, capture_output=True, text=True, encoding="utf-8")
    check(init.returncode == 0 and "でも" in seen and "shapeless" in seen, f"形の違う返りは die（合格に倒さない）: {seen[-140:]}")
    rm(tmp); rm(run.tmp)


def test_units():
    """engine の部品を直に呼ぶ検査（盤面を回さずに柵の腕へ入力を与える）。"""
    print("否定検査: 型検査と遮断の腕（部品を直に呼ぶ）")
    sys.path.insert(0, str(PLUGIN))
    from engine.render import Renderer, ReadsViolation, cap_bytes, FILE_CAP
    from engine.schema import validate_schema
    # 遮断: reads に無い穴は optional（{{?…}}）でも空で通さない
    r = Renderer({"a": {"b": 1}, "secret": "x"}, reads=["a"])
    check(r.render("{{a.b}}") == "1", "reads に在る穴は埋まる")
    try:
        r.render("{{?secret}}")
        check(False, "reads に無い穴が {{?…}} で空埋めされた（遮断が ? 一文字で外れる）")
    except ReadsViolation:
        check(True, "reads に無い穴は optional でも ReadsViolation（KeyError と別の型）")
    check(r.render("{{?a.nope}}") == "", "reads の中の『無い』穴は optional なら空でよい")
    # 貼る上限はバイト（日本語は 1 字 3 バイト——字数で測ると 2〜3 倍のバイトが通る）
    tr = []
    ja = "あ" * (FILE_CAP // 2)
    out = cap_bytes(ja, "x", tr)
    check(len(out.encode()) <= FILE_CAP + 200 and tr, f"上限はバイトで効く（{len(ja)} 字＝{len(ja.encode())} バイトを切った）")
    check(cap_bytes("abc", "x", []) == "abc", "上限内はそのまま")
    # 型検査: 真偽値と数値を同一視しない
    check(validate_schema(True, {"enum": [0, 1]}), "enum: True は語彙 [0, 1] に無い（bool は int の部分型）")
    check(not validate_schema(1, {"enum": [0, 1]}), "enum: 1 は通る")
    check(validate_schema(True, {"const": 1}), "const: True は 1 でない")
    check(validate_schema("   ", {"type": "string", "minLength": 1}), "minLength: 空白だけは空と数える")


def test_arms():
    print("否定検査: 型検査の腕・git が効かない場・検証器の無い run")
    run = Run("arms")
    nx = run.next()
    q = nx["ready"][0]
    good = base_answers(run, "std")["p0.question"](None, 1)
    r = run.done(q["id"], {**good, "thickness_decider": "誰か"})
    check(r.returncode == 1 and "型に合わない" in r.stderr and "誰か" in r.stderr, "enum: 語彙に無い決め手は exit 1（段の柵と別の腕）")
    r = run.done(q["id"], {**good, "thickness": "超重厚"})
    check(r.returncode == 1 and "超重厚" in r.stderr, "語彙に無い段は exit 1")
    r = run.done(q["id"], {**good, "extra": 1})
    check(r.returncode == 1 and "型に合わない" in r.stderr, "additionalProperties: 知らない欄は exit 1")
    r = run.done(q["id"], {**good, "constraints": "文字列"})
    check(r.returncode == 1 and "型に合わない" in r.stderr, "type: 配列の欄に文字列は exit 1")
    r = run.done(q["id"], {**good, "constraints": []})
    check(r.returncode == 1 and "型に合わない" in r.stderr, "minItems: 制約が空は exit 1")
    r = run.done(q["id"], {**good, "question": ""})
    check(r.returncode == 1 and "型に合わない" in r.stderr, "minLength: 問いが空文字は exit 1")
    r = run.done(q["id"], good)
    check(r.returncode == 0, "正しい返答は通る")
    # git が効かない場では、作業ツリー保護を持つ役（investigator）の節を出さない（保護を『一致』に倒さない）
    nogit = {**os.environ, "PATH": str(run.tmp / "empty-bin")}
    (run.tmp / "empty-bin").mkdir()
    r = run.cmd("next", env=nogit)
    check(r.returncode != 0 and "git status が取れない" in r.stderr, "git が無い場からの next は investigator の節で止まる（tree_before=None を通さない）")
    nx = run.next()
    by = {i["node"]: i for i in nx["ready"]}
    check("p0.prior_decisions" in by, "git が効く場では investigator の節が出る")
    f = run.tmp / "pd.json"
    f.write_text(json.dumps(base_answers(run, "std")["p0.prior_decisions"](None, 1), ensure_ascii=False), encoding="utf-8")
    r = run.cmd("done", "--node", by["p0.prior_decisions"]["id"], "--output", str(f), env=nogit)
    check(r.returncode == 1 and "git status が取れない" in r.stderr, "git が無い場からの done は突合できないので exit 1")
    rm(run.tmp)
    # 検証器が無い run は report の前で止まる（無検査で報告に進めない）
    run = Run("noval")
    st = run.state()
    st["validator"] = None
    (run.dir / "state.json").write_text(json.dumps(st, ensure_ascii=False), encoding="utf-8")
    try:
        drive(run, "std", hook=lambda *_: None)
        check(False, "検証器の無い run が report まで進んでしまった")
    except RuntimeError as e:
        check("検証器" in str(e) or "validator" in str(e).lower(), f"検証器の無い run は report の前で exit 1（{str(e)[:80]}）")
    check(not (run.dir / "report.md").is_file(), "report.md は作られない")
    rm(run.tmp)


def test_resolve_dir():
    print("否定検査: --dir を省いた呼び出しは、同じリポジトリに別のループの run が並ぶと取り違えずに拒む")
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="gl-dir-"))
    repo = tmp / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "--allow-empty", "-m", "init"], cwd=repo, check=True)
    doc = repo / "m.md"
    doc.write_text("# 見立て\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "-m", "doc"], cwd=repo, check=True)
    call = lambda *a: subprocess.run([PY, str(LOOP), *a], cwd=repo, capture_output=True, text=True, encoding="utf-8")
    r = call("init", "--loop", "research-loop", "--request", "q", "--document", str(doc), "--validator", str(VALIDATOR))
    check(r.returncode == 0 and "/.git/graphloops/research-loop/" in json.loads(r.stdout)["dir"], "--dir を省いた init は .git の下に盤面を作る")
    r = call("status")
    check(r.returncode == 0 and json.loads(r.stdout)["loop"] == "research-loop", "run が 1 本なら --dir 無しで解決する")
    r = call("init", "--loop", "review-loop", "--request", "r", "--validator", str(PLUGIN.parent / "scripts" / "review-record.py"))
    check(r.returncode == 0, "別のループも同じリポジトリに init できる")
    r = call("status")
    check(r.returncode == 2 and "--dir で指せ" in r.stderr and "research-loop" in r.stderr and "review-loop" in r.stderr, "run が 2 本並ぶと --dir 無しは exit 2（新しい方を黙って選ばない）")
    d = json.loads(call("status", "--dir", str(next((repo / ".git" / "graphloops" / "research-loop").glob("2*")))).stdout)
    check(d["loop"] == "research-loop", "--dir で名指しすれば解決する")
    rm(tmp)


def test_gate_arms():
    print("台本: ゲートが pass しない周が続く——上限で止まる／独立導出の岐路で人に聞く")
    run = Run("coldfail", unattended=True)
    last = drive(run, "coldfail")
    rec = run.record()
    check(last["status"] == "stopped" and "暴走ガード" in rec["convergence"]["stopped_reason"], f"cold_reader が pass しないまま上限で stopped（{rec['convergence'].get('stopped_reason', '')[:30]}）")
    check(rec["convergence"]["outcome"] == "stopped" and all(r["verdict"] == "redesign-needed" for r in rec["gates"]["cold_reader"]["rounds"]), "収束を名乗らず、ゲートの周ごとの verdict が残る")
    check(run.state()["round"] == run.state()["max_rounds"], f"止まった周は max_rounds（{run.state()['round']}）")
    rm(run.tmp)
    run = Run("rederiver")
    last = drive(run, "rederiver_fail")
    check(last["status"] == "awaiting_human" and "zero_base_divergence" in last["ask"]["kinds"], f"rederiver の redesign-needed が 2 周解消しないと人に聞く（{last.get('ask', {}).get('kinds')}）")
    rm(run.tmp)


def test_isolated_launch():
    """道具ゼロの役は Agent ツールで起こさず、別プロセスの CLI で起こすこと。

    ハーネスは subagent に CLAUDE.md 階層を注入し、止める設定が公式に無い（実測 2026-09-12: 道具ゼロの
    cold-reader が利用者の CLAUDE.md を逐語で引用した）。setting source ごと外せるのは CLI だけなので、
    「道具の不在で遮断する」は起こし方まで含めて初めて成立する。
    """
    print("否定検査: 道具ゼロの役は cli で起こす（Agent ツールでは CLAUDE.md を止められない）")
    seen = {}

    def watch(run, inst, out):
        seen.setdefault(inst["mode"], []).append(inst)
        return out

    run = Run("isolated")
    drive(run, "std", hook=watch)
    cli, ag = seen.get("cli", []), seen.get("agent", [])
    check(bool(cli), f"道具ゼロの役が cli で出る（{sorted({i['node'] for i in cli})}）")
    check(bool(ag), f"道具を持つ役は agent のまま（{sorted({i['node'] for i in ag})}）")
    L = cli[0].get("launch") if cli else {}
    argv = L.get("argv") or []

    def after(flag):
        return argv[argv.index(flag) + 1] if flag in argv and argv.index(flag) + 1 < len(argv) else None

    check(L.get("stdin") == cli[0]["prompt_file"] if cli else False, "材料は stdin で渡す（貼る上限に当たらない）")
    check(after("--setting-sources") == "", '起動に --setting-sources "" が入る（CLAUDE.md ごと外す）')
    check(after("--tools") == "", '起動に --tools "" が入る（道具ゼロを CLI 側でも守る）')
    role = after("--append-system-prompt-file")
    check(bool(role) and pathlib.Path(role).is_file() and pathlib.Path(role).read_text(encoding="utf-8").strip(),
          "役の定義の本文が盤面に書き出され、system prompt として渡る")
    rm(run.tmp)

    # **起こすコマンドが無い場でも next は止まらない。** 計画を出す所で落とすと、遮断系を一度も起こさない場
    # （この台本・別の機械での再開・記録を読むだけの用）まで全部死ぬ（実測 2026-09-12: ここを die にしたら
    # CI の 3 OS が全部赤になった。手元には claude が在るので緑で、CI でしか出なかった）。
    run = Run("nopath")
    run.next()  # 最初の波は回す側の節だけ——遮断系が出る波まで 1 手進めてから見る
    run.done("p0.question", base_answers(run, "std")["p0.question"](None, 1))
    cdir = os.path.dirname(shutil.which("claude") or "")
    env = {**os.environ, "PATH": os.pathsep.join(p for p in os.environ.get("PATH", "").split(os.pathsep) if p and p != cdir)}
    r = run.cmd("next", env=env)
    check(r.returncode == 0, f"起こすコマンドが PATH に無くても next は通る（rc={r.returncode}: {r.stderr[:120]}）")
    ready = json.loads(r.stdout)["ready"] if r.returncode == 0 else []
    cli2 = [i for i in ready if i.get("mode") == "cli"]
    check(bool(cli2) and all(i["launch"].get("missing") for i in cli2),
          "起こせない旨が launch.missing に立つ（回す側と記録に見える）")
    rm(run.tmp)


def test_isolated_not_truncated():
    """遮断系へ渡す本文は切らない——貼る先の上限は Agent ツールのプロンプトの性質で、標準入力には無い。

    実測 2026-09-12: 748,883 バイトが先頭・末尾とも欠けずに CLI を通った。渡し方を変えたのに切り続けると、
    見せられる物を捨てることになる（この run で R2 が『全体の 5.7% しか見ていない』と判定を拒否した）。
    """
    print("否定検査: 遮断系に渡す本文は切られない")
    run = Run("nocap")
    head, tail = "［先頭の目印 HEAD-NOCAP］", "［末尾の目印 TAIL-NOCAP］"
    big = f"# 見立て\n\n{head}\n" + ("主張 A・B・C・D を含む長い見立て。" * 8000) + f"\n{tail}\n"
    run.doc.write_text(big, encoding="utf-8")
    check(len(big.encode("utf-8")) > 200_000, f"材料が旧上限 40,000 バイトを大きく超える（{len(big.encode('utf-8'))} バイト）")
    seen = []

    def watch(run, inst, out):
        if inst["mode"] == "cli":
            seen.append((inst["node"], pathlib.Path(inst["prompt_file"]).read_text(encoding="utf-8")))
        return out

    drive(run, "std", hook=watch)
    # 材料を渡された節だけを見る——先頭の目印で絞る。「見立て」のような本文中の語で絞ると、
    # 文書を受け取らない節（問いの文に同じ語が在る p3.rederiver）まで拾って検査が嘘をつく。
    withdoc = [(n, p) for n, p in seen if head in p]
    check(bool(withdoc), f"材料を渡される遮断系の節が在る（{sorted({n for n, _ in withdoc})}）")
    check(all(tail in p for _, p in withdoc),
          f"遮断系のプロンプトに材料の末尾が残る＝切られていない（欠けた節: {[n for n, p in withdoc if tail not in p]}）")
    rm(run.tmp)


def test_concurrent_save():
    """1 つの盤面に 2 人が付いたとき、後から書く側が先の完了を消さないこと。

    ここだけ subprocess でなく engine を直に呼ぶ。競合は「A が読む → B が書く → A が書く」の順でしか
    起きず、別プロセス越しにこの順を決定的に作れない（時刻に頼ると CI で揺れる）。B の側は本物の
    engine コマンドにする——手で rev を書き足すと「engine が rev を上げていない」を見逃す。
    """
    print("否定検査: 1 つの盤面に 2 人が付くと、後から書く側が落ちる")
    sys.path.insert(0, str(PLUGIN))
    from engine.board import Board

    run = Run("concurrent")
    a = Board(run.dir)  # A が読む（まだ書かない）
    r = run.cmd("thicken", "--to", "重厚", "--reason", "別プロセスが盤面を進める")
    check(r.returncode == 0, f"B（別プロセス）の書き込みは通る（rc={r.returncode}）")
    before = (run.dir / "state.json").read_text(encoding="utf-8")
    a.state["書かれてはいけない欄"] = True
    code = None
    try:
        a.save()
    except SystemExit as e:
        code = e.code
    check(code == 2, f"A の save は die（exit 2 を期待、実際 {code}）")
    check((run.dir / "state.json").read_text(encoding="utf-8") == before,
          "落ちた save は盤面を 1 バイトも変えていない（後勝ちで上書きしない）")
    b = Board(run.dir)
    check("書かれてはいけない欄" not in b.state, "A が握っていた古い state は書き戻されていない")


def main():
    os.environ.pop("CONVERGENCE_LOOPS_ROOT", None)
    test_graphcheck()
    test_rejections()
    test_units()
    test_bad_builtin()
    test_arms()
    test_converges()
    test_unattended_stuck()
    test_attended_stuck_answer()
    test_light()
    test_resolve_dir()
    test_gate_arms()
    test_isolated_launch()
    test_isolated_not_truncated()
    test_concurrent_save()
    print(f"\n{ran} 件中 {len(fails)} 件失敗")
    if ran == 0:  # 台本が 1 本も走らないと「0 件中 0 件失敗」が緑に見える——母数 0 は赤
        print("  - 検査が 1 件も走っていない")
        sys.exit(1)
    if fails:
        for f in fails:
            print("  - " + f)
        sys.exit(1)


if __name__ == "__main__":
    main()
