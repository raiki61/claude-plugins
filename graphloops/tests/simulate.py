#!/usr/bin/env python3
"""engine を、役の返答を台本で差し替えて端から端まで回す（役割 agent も LLM も使わない）。

確かめるのは engine と rules と graph の噛み合わせ——波の順・扇の被覆・件数突合・連続カウント・
ゲートの条件・抜き取り・収束と停止・記録が検証器（convergence-loops の research-record.py）を通ること。
役の判断の質は見ない（それは実走で見る）。

使い方: python3 simulate.py            # 全部の台本と否定検査を回す。失敗があれば exit 1
"""
import collections
import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import types

import parallel  # 同じディレクトリ。台本を同時に走らせる土台（検査の中身は変えない）

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from engine.util import TERMINAL_STATUS  # noqa: E402 — 終端の status は engine が正本（台本で並べ直さない）

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
DELIVERY_SEEN = set()  # 渡し方の検査が実際に当たった節。腕が空振りしても件数が偶然同じなら件数の柵は見ない（実測）ので、名指しで見る


def check(cond, desc):
    # 件数と失敗一覧は台本をまたいで共有される。**`ran += 1` は不可分ではない**ので錠を掛ける
    # ——素で並列にすると数え落とし、件数の柵（run.sh の EXPECTED_CHECKS）が走るたび違う値になる。
    global ran
    with parallel.LOCK:
        ran += 1
        if not cond:
            fails.append(desc)
    parallel.line(f"  ok   {desc}" if cond else f"  FAIL {desc}")


def rm(p):
    """作業場の掃除。Windows は git の object を読み取り専用で置き、素の rmtree が PermissionError で
    落ちる（実測: CI の windows-latest）。掃除の失敗で検査本体を落とさない。"""
    shutil.rmtree(p, ignore_errors=True)


MADE = set()  # この プロセスが作った作業場だけを後始末する（接頭辞の列挙は他プロセスの盤面を巻き込む）

# 台本が実際に返した判定語彙（(節, 欄) → 値の集合）。**「台本が 1 値固定」を件数でなく到達で測る。**
# review 側に同じラチェットを置いた当日、research 側には無かった——**知見が片側にしか適用されない**形。
VOCAB_SEEN = collections.defaultdict(set)
# 到達した語彙の数。**`!=` で見る**——下限だと筋書きを増やしても数が動かず、増やしたつもりの周に誰も気づかない。
VOCAB_REACHED = 22


def record_vocab(node, output):
    """台本が返した値を集める。**既存の検査に相乗りするので、この測定のために 1 回も余計に回さない。**"""
    if not isinstance(output, dict):
        return
    nid = node.split("[")[0]

    def walk(v, p=""):
        if isinstance(v, dict):
            for k, x in v.items():
                walk(x, f"{p}.{k}" if p else k)
        elif isinstance(v, list):
            for x in v:
                walk(x, p + "[]")
        elif isinstance(v, (str, bool)):
            with parallel.LOCK:
                VOCAB_SEEN[(nid, p)].add(v)

    walk(output)


def vocab_coverage():
    """graph が宣言する判定語彙のうち、台本が返したものの数と、返していないものの一覧。"""
    g = json.loads((PLUGIN / "graphs" / "research-loop.json").read_text(encoding="utf-8"))
    enums = {}

    def walk_schema(nid, sch, path=""):
        if not isinstance(sch, dict):
            return
        if "enum" in sch:
            enums[(nid, path)] = set(sch["enum"])
        for k, v in (sch.get("properties") or {}).items():
            walk_schema(nid, v, f"{path}.{k}" if path else k)
        if "items" in sch:
            walk_schema(nid, sch["items"], path + "[]")

    # **無作為に項目を引く扇の節は数えない**——引く物が run ごとに変わるので、そこから返る値は
    # 台本の性質ではない（実測: 数えていたとき到達が 24 と 25 で揺れた）。除外は rules が宣言する
    # `RANDOM_FAN` から導く——測る側で節の名前を手で並べると、扇を足した周にまた揺れる
    sys.path.insert(0, str(PLUGIN))
    from engine.rules import load_rules
    rules = load_rules(PLUGIN / "graphs" / "research-loop.json", g)
    random_fan = set(getattr(rules, "RANDOM_FAN", ()) or ())
    for nid, n in g["nodes"].items():
        if (n.get("fan_out") or {}).get("builtin") in random_fan:
            continue
        if n.get("schema"):
            walk_schema(nid, n["schema"])
    total = sum(len(v) for v in enums.values())
    reached = sum(len(v & VOCAB_SEEN.get(k, set())) for k, v in enums.items())
    unreached = sorted(f"{k[0]}.{k[1]}={v}" for k, vs in enums.items() for v in sorted(vs - VOCAB_SEEN.get(k, set())))
    return reached, total, unreached

# **落ちた回も後始末する。** 後始末は main の finally に在るが、main に届かない落ち方（import 時の例外・
# 台本が engine を壊して全体が落ちる・退行注入の試走）では作業場が残る。溜まった実測: 502 個・148 MB
# （正常終了する回は 1 個も漏らさない——漏れるのは落ちた回だけ）。atexit なら finally の外も覆う。
# **消すのは自分が作った物だけ**（MADE）——接頭辞で列挙すると、同時に走る他プロセスの盤面を巻き込む。
import atexit as _atexit  # noqa: E402


@_atexit.register
def _sweep_made():
    for _d in list(MADE):
        shutil.rmtree(_d, ignore_errors=True)


class Run:
    def __init__(self, name, thickness=None, decider=None, unattended=False, graph=None):
        # graph=<path>: 同梱でなくその写しで回す。**回した後に graph を締める腕**（once の節の凍った出力を
        # 今の schema で測り直す）に要る——同梱を書き換えると、他の台本と本物のリポジトリを壊す
        self.tmp = pathlib.Path(tempfile.mkdtemp(prefix=f"gl-{name}-"))
        MADE.add(self.tmp)
        self.repo = self.tmp / "repo"
        self.repo.mkdir()
        subprocess.run(["git", "init", "-q"], cwd=self.repo, check=True, timeout=120)
        subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "--allow-empty", "-m", "init"], cwd=self.repo, check=True, timeout=120)
        self.doc = self.repo / "mitate.md"
        self.doc.write_text("# 見立て\n\n主張 A・B・C・D を含む見立て文書。\n", encoding="utf-8")
        subprocess.run(["git", "add", "."], cwd=self.repo, check=True, timeout=120)
        subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "-m", "doc"], cwd=self.repo, check=True, timeout=120)
        self.dir = self.tmp / "state"
        args = ["init", "--loop", "research-loop", "--request", "この見立ては正しいか", "--document", str(self.doc),
                "--dir", str(self.dir), "--validator", str(VALIDATOR)]
        if thickness:
            args += ["--thickness", thickness]
        if decider:
            args += ["--decider", decider]
        if unattended:
            args.append("--unattended")
        if graph:
            args += ["--graph", str(graph)]
        self.init = self.cmd(*args)

    def cmd(self, *args, stdin=None, env=None):
        r = subprocess.run([PY, str(LOOP), *args, *([] if args[0] == "init" else ["--dir", str(self.dir)])],
                           cwd=self.repo, capture_output=True, text=True, encoding="utf-8", input=stdin, env=env, timeout=600)
        return r

    def next(self):
        r = self.cmd("next")
        if r.returncode != 0:
            raise RuntimeError(f"next が {r.returncode}: {r.stderr}")
        return json.loads(r.stdout)

    def done(self, node, output):
        record_vocab(node, output)
        f = self.tmp / "out.json"
        f.write_text(json.dumps(output, ensure_ascii=False), encoding="utf-8")
        return self.cmd("done", "--node", node, "--output", str(f))

    def record(self):
        # **記録は盤面のファイルを直読みする。** loop.py record は record.json の丸写しなのに、CLI 経由だと
        # 1 回ごとに python の起動と engine の import を払う（実測 2026-09-13: 2 本の台本で計 567 回・30.4 秒、
        # 直読みに替えると検査一式が 161 秒 → 132 秒で件数と失敗数は不変）。record サブコマンド自体の煙テストは
        # record_cli() に 1 か所だけ残す——全部を直読みにすると、そのコマンドが壊れても誰も気づかない
        return json.loads((self.dir / "record.json").read_text(encoding="utf-8"))

    def record_cli(self):
        """loop.py record が record.json の丸写しを返すことの煙テスト（呼ぶのは 1 か所だけ）。"""
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
    seen_delivery = set()  # 渡し方の検査は節ごとに初回だけ（P3 の遮断系は 1 周目に出ない——round == 1 の条件では一度も当たらなかった）
    for _ in range(max_steps):
        nx = run.next()
        last = nx
        if nx.get("status") == "awaiting_human" or (not nx["ready"] and nx["status"] in TERMINAL_STATUS):
            return nx
        if not nx["ready"]:
            raise RuntimeError("ready が空のまま進まない: " + json.dumps(nx, ensure_ascii=False)[:600])
        answers = base_answers(run, scenario)
        for inst in nx["ready"]:
            node = inst["node"]
            if hook is None and node == "p2.integrate":
                ptxt = pathlib.Path(inst["prompt_file"]).read_text(encoding="utf-8")
                check("record.json" in ptxt and '"claims": [' not in ptxt, "統合の節には記録の本文でなく置き場と要約が渡る")
            if hook is None and node in ("p1.checker", "p3.cold_reader") and node not in seen_delivery:
                seen_delivery.add(node)
                DELIVERY_SEEN.add(node)
                # 遮断系は cli で出るので mode も見る（以前は mode == "agent" と round == 1 を条件にしていて cold_reader の腕が空振りしていた）
                want_mode, want = ("agent", "path") if node == "p1.checker" else ("cli", "paste")
                check(inst["mode"] == want_mode and inst.get("deliver") == want, f"{node} は mode={want_mode}・渡し方 {want}（役の道具から決まる）")
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
    v = subprocess.run([PY, str(VALIDATOR), str(run.dir / "record.json")], capture_output=True, text=True, encoding="utf-8", timeout=600)
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
    # graph が必須にしている入力（{{file:inputs.document}}）は入口で落とす——以前は init が exit 0 で、2 回目の next で
    # p0.claims の穴が埋まらず初めて落ちた（実測 2026-09-13）。渡されたパスの実在も同じ場所で見る
    nodoc = [PY, str(LOOP), "init", "--loop", "research-loop", "--request", "x", "--dir", str(run.tmp / "nodoc"), "--validator", str(VALIDATOR)]
    r = subprocess.run(nodoc, cwd=run.repo, capture_output=True, text=True, encoding="utf-8", timeout=600)
    check(r.returncode != 0 and "--document" in r.stderr and "p0.claims" in r.stderr, f"research を --document 無しで init すると入口で落ち、要る節と穴を名指しする（rc={r.returncode}: {r.stderr[-100:]}）")
    r = subprocess.run(nodoc + ["--document", str(run.tmp / "no-such.md")], cwd=run.repo, capture_output=True, text=True, encoding="utf-8", timeout=600)
    check(r.returncode != 0 and "が無い" in r.stderr, "実在しない --document も入口で落ちる")
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
    check("open_questions" not in prompts or "[]" in prompts or "この周には無い" in prompts,
          "前の節の出力の穴が埋まっている（空でなく値か『無い』の語）")
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
    r = run.done(ch["c1"]["id"], {"cluster": "c1", "findings": [{"id": "A", "verdict": "たぶん", "evidence": "e", "sources": ["https://x"], "conditions": "c"}]})
    check(r.returncode == 1 and "型に合わない" in r.stderr, "語彙に無い判定語は節の schema（検証器の語彙の写し——graphcheck が包含を見る）で exit 1")
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
    # 記録の側の柵（check_record）は節の schema を通らない経路（patch）でも知らない判定語を拒む——以前は「要求欄なし＝合格」に倒れた
    rec = run.record()
    rec["claims"][0]["verdict"] = "たぶん"
    (run.tmp / "c.json").write_text(json.dumps(rec["claims"], ensure_ascii=False), encoding="utf-8")
    run.cmd("patch", "--path", "claims", "--file", str(run.tmp / "c.json"), "--reason", "試験（語彙外の判定語）")
    sys.path.insert(0, str(PLUGIN))
    from engine.rules import load_rules
    g = json.loads((PLUGIN / "graphs" / "research-loop.json").read_text(encoding="utf-8"))
    rules = load_rules(PLUGIN / "graphs" / "research-loop.json", g)
    board = types.SimpleNamespace(state={"validator": str(VALIDATOR)}, record=run.record())
    errs = rules.check_record(board)
    check(any("語彙に無い" in e for e in errs), f"check_record は語彙に無い verdict を拒む（{errs[:1]}）")
    rm(run.tmp)


def test_graphcheck():
    print("graphcheck: 正しい graph は通り、壊した graph は腕ごとに NG の診断文を出して落ちる（例外で死なない）")
    g = json.loads((PLUGIN / "graphs" / "research-loop.json").read_text(encoding="utf-8"))
    r = subprocess.run([PY, str(GRAPHCHECK), str(PLUGIN / "graphs" / "research-loop.json"), str(VALIDATOR)], capture_output=True, text=True, encoding="utf-8", timeout=600)
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
        r = subprocess.run([PY, str(GRAPHCHECK), str(p), *([validator] if validator else [])], capture_output=True, text=True, encoding="utf-8", timeout=600)
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
    broken(lambda b: b["nodes"]["p1.checker"]["schema"].__setitem__("oneOf", []), "engine が読まない語", "schema に engine が読まない語（oneOf）を書いた graph は落ちる（書いても効かない語を黙って通さない）")
    # engine が実行に使う欄の綴り違い（文書欄 outputs の照合は通っても、実行では黙って素通りしていた）
    broken(lambda b: b["nodes"]["p1.checker"]["writes"][0].__setitem__("from", "findingz"), "writes.from", "writes.from が schema に無い欄を指す graph は落ちる（記録に着地しない）")
    broken(lambda b: b["nodes"]["p1.refuter"].__setitem__("cond", {"path": "out.p1.checker.findingz", "op": "nonempty", "default": False}), "schema に無い", "cond の path が節の schema に無い欄を指す graph は落ちる")
    broken(lambda b: b["record"].__setitem__("report_accepts_exit", ["0"]), "report_accepts_exit", "report_accepts_exit に整数でない値を書いた graph は落ちる")
    # 同じ context を継ぐ節: 役が一致し、遮断系でないこと（review graph で見る）
    rg = json.loads((PLUGIN / "graphs" / "review-loop.json").read_text(encoding="utf-8"))
    rv = str(PLUGIN.parent / "scripts" / "review-record.py")
    for i, (mut, want, desc) in enumerate((
            (lambda b: b["nodes"]["p2.history"].__setitem__("run_by", "inspector"), "役が違う", "same_context_as の役と自分の役が違う graph は落ちる"),
            (lambda b: (b["nodes"]["p2.history"].__setitem__("run_by", "blind-judge"), b["nodes"]["p2.diagnose"].__setitem__("run_by", "blind-judge")), "遮断系", "遮断系の役に same_context_as を書いた graph は落ちる（実行時の die を静的にも見る）"),
            # cond の path は out. だけでなく prev.<節>.<欄> も節の schema と突き合わせる（review-loop の default 付きの葉は prev. が多数派）
            (lambda b: b["nodes"]["p1.external_standards"].__setitem__("cond", {"path": "prev.p3.fix.changez", "op": "nonempty", "default": False}), "schema に無い", "cond の path が prev.<節>.<欄> で欄を綴り違えた graph は落ちる（再発火条件が恒偽のまま通らない）"),
            # graph の enum は検証器の語彙の写し——はみ出せば片方だけ変わっている
            (lambda b: b["nodes"]["p0.local_checks"]["schema"]["properties"]["material"]["properties"]["status"]["enum"].append("maybe"), "丸ごと含まれない", "素材の status の enum が検証器の語彙からはみ出す graph は落ちる（写しのずれ）"),
            # 遮断系の起動の穴は engine が埋める語だけ——知らない穴は実行時の format で KeyError にしかならなかった
            (lambda b: b["launch"]["isolated"]["argv"].append("{nope}"), "埋められない", "launch.isolated.argv に engine が埋められない穴を書いた graph は落ちる（遮断系の不変条件を die にだけ置かない）"))):
        badr = json.loads(json.dumps(rg))
        mut(badr)
        pr = tmp / "graphs" / f"badreview{i}.json"
        pr.write_text(json.dumps(badr, ensure_ascii=False), encoding="utf-8")
        r = subprocess.run([PY, str(GRAPHCHECK), str(pr), rv], capture_output=True, text=True, encoding="utf-8", timeout=600)
        check(r.returncode == 1 and want in r.stdout and "Traceback" not in r.stderr, f"{desc}（NG『{want}』で exit 1）")
    broken(lambda b: b["nodes"]["p1.checker"].__setitem__("run_by", "nobody"), "run_by", "回す側でも役でもない run_by は落ちる")
    # cond の op ごとに要る鍵（engine の COND_OP_KEYS が正本）——欠けると実行時に KeyError か恒偽になる
    broken(lambda b: b["nodes"]["p1.refuter"].__setitem__("cond", {"path": "loop.x", "op": "any_field_eq", "value": 1, "default": []}),
           "要る鍵が無い", "any_field_eq で field を書き忘れた graph は落ちる（実行時の KeyError を静的に見る）")
    broken(lambda b: b["nodes"]["p1.refuter"].__setitem__("cond", {"path": "loop.x", "op": "in", "default": None}),
           "要る鍵が無い", "in で value を書き忘れた graph は落ちる（恒偽に倒れない）")
    broken(lambda b: b["nodes"]["p1.checker"]["writes"][0].__setitem__("stamp_round", True), "stamp_round", "stamp_round に真偽値を書く graph は落ちる（欄の名前だけ）")
    # 段名の正本は thickness.tiers——キーの集合から導かない
    broken(lambda b: b["thickness"].__setitem__("default", "超重厚"), "超重厚", "thickness.default が段に無い graph は落ちる")
    broken(lambda b: b["nodes"]["p0.generation"].__setitem__("active_in", ["deciders"]), "deciders", "thickness のキー名（deciders）を段として使う graph は落ちる")
    # 検証器の欄との突合は省略で通さない
    broken(lambda b: b["record"].__setitem__("validator_path", "scripts/no-such-record.py"), "見つからない", "検証器のパスが解決できない graph は落ちる（第 2 引数なし）", validator=None)
    broken(lambda b: None, "必須欄が 1 つも拾えない", "必須欄を持たないファイルを検証器として渡すと落ちる（0 個の突合を合格にしない）", validator=str(PLUGIN / "engine" / "util.py"))
    # rules のフック名の綴り違い（engine は名前一致でしか探さないので、1 字違いは静かに『持たない』に倒れる）
    # rules は graph のディレクトリからの相対で解決されるので、写しの graph（tmp/graphs/）を通す
    bad_rules = (tmp / "rules" / "research-loop.py")
    src = bad_rules.read_text(encoding="utf-8")
    bad_rules.write_text(src.replace("def on_answer(", "def on_anwser("), encoding="utf-8")
    ok_graph = tmp / "graphs" / "hookcheck.json"
    ok_graph.write_text(json.dumps(g, ensure_ascii=False), encoding="utf-8")
    r = subprocess.run([PY, str(GRAPHCHECK), str(ok_graph), str(VALIDATOR)], capture_output=True, text=True, encoding="utf-8", timeout=600)
    bad_rules.write_text(src, encoding="utf-8")
    check(r.returncode == 1 and "綴り違い" in r.stdout,
          f"rules のフック名の綴り違いは graphcheck が落とす（rc={r.returncode}: {r.stdout.strip()[-90:]}）")

    # 遮断系（道具ゼロの役）は別プロセスで起こすので context を継げない。**実行時の die だけに置かない**
    iso = json.loads(json.dumps(g))
    tgt = next(k for k, v in iso["nodes"].items() if v.get("run_by") in ("cold-reader", "blind-judge"))
    dep = (iso["nodes"][tgt].get("deps") or ["p0.question"])[0]
    iso["nodes"][tgt]["same_context_as"] = dep
    bad_iso = tmp / "graphs" / "iso.json"
    bad_iso.write_text(json.dumps(iso, ensure_ascii=False), encoding="utf-8")
    r = subprocess.run([PY, str(GRAPHCHECK), str(bad_iso), str(VALIDATOR)], capture_output=True, text=True, encoding="utf-8", timeout=600)
    check(r.returncode == 1 and "context は継げない" in r.stdout,
          f"遮断系の役に same_context_as を書いた graph は落ちる（rc={r.returncode}: {r.stdout.strip()[-90:]}）")
    # **対象は graphs/ の実体から導く**（名前を手で並べると、足した graph も落とした graph も検査の側が追えない）
    for gf in sorted((PLUGIN / "graphs").glob("*.json")):
        if gf.name == "research-loop.json":
            continue  # 上でフックの腕に使っている
        r = subprocess.run([PY, str(GRAPHCHECK), str(gf)], capture_output=True, text=True, encoding="utf-8", timeout=600)
        check(r.returncode == 0, f"{gf.name} は第 2 引数なし（検証器を渡さない）でも形の検査だけで通る")
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
                          cwd=run.repo, capture_output=True, text=True, encoding="utf-8", timeout=600)
    seen = ""
    for _ in range(40):
        nx = subprocess.run([PY, str(LOOP), "next", "--dir", str(d2)], cwd=run.repo, capture_output=True, text=True, encoding="utf-8", timeout=600)
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
                           cwd=run.repo, capture_output=True, text=True, encoding="utf-8", timeout=600)
    check(init.returncode == 0 and "でも" in seen and "shapeless" in seen, f"形の違う返りは die（合格に倒さない）: {seen[-140:]}")
    rm(tmp); rm(run.tmp)


def test_units():
    """engine の部品を直に呼ぶ検査（盤面を回さずに柵の腕へ入力を与える）。"""
    print("否定検査: 型検査と遮断の腕（部品を直に呼ぶ）")
    sys.path.insert(0, str(PLUGIN))
    from engine.render import Renderer, ReadsViolation, cap_bytes, FILE_CAP, ABSENT
    from engine.schema import validate_schema
    # 遮断: reads に無い穴は optional（{{?…}}）でも空で通さない
    r = Renderer({"a": {"b": 1}, "secret": "x"}, reads=["a"])
    check(r.render("{{a.b}}") == "1", "reads に在る穴は埋まる")
    try:
        r.render("{{?secret}}")
        check(False, "reads に無い穴が {{?…}} で空埋めされた（遮断が ? 一文字で外れる）")
    except ReadsViolation:
        check(True, "reads に無い穴は optional でも ReadsViolation（KeyError と別の型）")
    # **『無い』は空でなく語で埋める。** 空に潰すと、文の途中に在る穴が判定不能の文になり、
    # しかも「この周には無い」と「engine が渡し損ねた」が同じ値になる（実測 2026-09-13: p2.diagnose.md の
    # {{?loop.escalated}} が空に潰れ、「深い側に上がっているなら順序を反転しろ: が在る周は」という文になった）
    check(r.render("{{?a.nope}}") == ABSENT, "reads の中の『無い』穴は optional なら語で埋まる（空にしない）")
    check(r.render("前は {{?a.nope}} だった") == f"前は {ABSENT} だった", "文の途中でも語が残る（読む側が真偽を決められる）")
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
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True, timeout=120)
    subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "--allow-empty", "-m", "init"], cwd=repo, check=True, timeout=120)
    doc = repo / "m.md"
    doc.write_text("# 見立て\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=repo, check=True, timeout=120)
    subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "-m", "doc"], cwd=repo, check=True, timeout=120)
    call = lambda *a: subprocess.run([PY, str(LOOP), *a], cwd=repo, capture_output=True, text=True, encoding="utf-8", timeout=600)
    r = call("init", "--loop", "research-loop", "--request", "q", "--document", str(doc), "--validator", str(VALIDATOR))
    # 区切り文字で見ない——Windows は \\ で返り、'/.git/…/' の部分一致は落ちた（実測: CI の windows-latest）
    d0 = pathlib.Path(json.loads(r.stdout)["dir"]) if r.returncode == 0 else pathlib.Path()
    check(r.returncode == 0 and d0.parts[-4:-1] == (".git", "graphloops", "research-loop"), f"--dir を省いた init は .git の下に盤面を作る（{d0}）")
    r = call("status")
    check(r.returncode == 0 and json.loads(r.stdout)["loop"] == "research-loop", "run が 1 本なら --dir 無しで解決する")
    r = call("init", "--loop", "review-loop", "--request", "r", "--validator", str(PLUGIN.parent / "scripts" / "review-record.py"))
    check(r.returncode == 0, "別のループも同じリポジトリに init できる")
    r = call("status")
    check(r.returncode == 2 and "--dir で指せ" in r.stderr and "research-loop" in r.stderr and "review-loop" in r.stderr, "run が 2 本並ぶと --dir 無しは exit 2（新しい方を黙って選ばない）")
    r = call("init", "--loop", "research-loop", "--request", "q", "--document", str(doc), "--validator", "/nonexistent/x-record.py")
    check(r.returncode == 2 and "明示された" in r.stderr, f"明示した検証器が無ければ init は die（黙って同梱の検証器に倒れない）（rc={r.returncode}: {r.stderr.strip()[-160:]}）")
    check(len(list((repo / ".git" / "graphloops" / "research-loop").glob("2*"))) == 1, "die した init は空の盤面を残さない（検証器は置き場を作る前に解決する）")
    # 同じ秒に 2 回 init しても run-id が衝突しない（以前は FileExistsError で exit 2）
    r2a = call("init", "--loop", "research-loop", "--request", "q", "--document", str(doc), "--validator", str(VALIDATOR))
    r2b = call("init", "--loop", "research-loop", "--request", "q", "--document", str(doc), "--validator", str(VALIDATOR))
    d2a, d2b = (json.loads(x.stdout)["dir"] if x.returncode == 0 else None for x in (r2a, r2b))
    check(r2a.returncode == 0 and r2b.returncode == 0 and d2a != d2b, f"同じ秒の 2 回の init は別の置き場になる（{d2a and d2a[-20:]} / {d2b and d2b[-20:]}）")
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



def _fake_claude(bindir, body):
    """代役の claude を、**実物と同じ実行形式**で置く。返り値は argv[0] に渡すパス。

    実物（/usr/local/bin/claude 等）は OS が直接起こせる実行体で、shebang 付きのテキストは POSIX でしか
    起こせない。代役だけを shebang のスクリプトにしていたとき、Windows の CreateProcess は shebang を
    解釈しないので **代役だけが起動できず**、この腕が OSError（WinError 193）で模擬実行ごと止めた
    （実測 2026-09-13: HEAD c73fd6e の CI で windows-latest が 320 件中 139 件で停止）。腕の目的は
    「engine が組んだ argv をそのまま実行する」ことなので、argv を書き換えず実行形式の側を実物に寄せる。
    """
    impl = bindir / "fake_claude_impl.py"
    impl.write_text(body, encoding="utf-8")
    if os.name == "nt":
        # CreateProcess は .bat / .cmd を cmd.exe 経由で起こせる（shebang は解さない）
        fake = bindir / "claude.bat"
        fake.write_text(f'@echo off\r\n"{sys.executable}" "{impl}" %*\r\n', encoding="utf-8")
        return fake
    fake = bindir / "claude"
    fake.write_text(f"#!{sys.executable}\n" + body, encoding="utf-8")
    fake.chmod(0o755)
    return fake


def test_isolated_real_launch():
    """遮断系を **argv どおりに実際に起こす**。代役が argv の形しか見ていないと、実物の失敗形（非 0 終了・空返答・
    短い非 JSON）を一度も観測できない——REVIEW.md『動かして赤・失敗を一度も見ていない保護機構を機能していると扱わない』。

    偽の claude は**この腕の env にだけ** PATH の先頭で渡す。run 全体の PATH に置くと、test_isolated_launch の
    nopath の腕（shutil.which("claude") の親だけを外す作り）が本物を残したまま緑になる。
    """
    print("実起動: 遮断系を launch.argv どおりに起こし、返答と失敗形を観測する")
    run = Run("reallaunch")
    run.next()
    run.done("p0.question", base_answers(run, "std")["p0.question"](None, 1))
    nx = run.next()
    cli = [i for i in nx["ready"] if i.get("mode") == "cli"]
    check(bool(cli), f"遮断系が cli で出る（{[i['node'] for i in cli]}）")
    inst = cli[0]
    bindir = run.tmp / "fakebin"
    bindir.mkdir()
    # **標準入力はバイトで読む。** 実物の claude と同じで、text で読むと Windows は OS 既定（cp1252）で復号し、
    # 日本語のプロンプトが UnicodeDecodeError になる（実測 2026-09-13: .bat で起動できるようにした直後の CI）。
    # engine 側の cmd_done が同じ理由で既にバイト読みに直してある——代役だけが実物と違う形に残っていた
    fake = _fake_claude(bindir,
                        "import sys, json\n"
                        "raw = sys.stdin.buffer.read()\n"
                        "sys.stdout.write(json.dumps({'seen_bytes': len(raw), 'argv': sys.argv[1:]}) + '\\n')\n")
    env = {**os.environ, "PATH": str(bindir) + os.pathsep + os.environ.get("PATH", "")}
    argv = list(inst["launch"]["argv"])
    argv[0] = str(fake)  # engine は next の時点で PATH から解決済みなので、この腕では偽物を名指しする
    with open(inst["launch"]["stdin"], "rb") as fh:
        r = subprocess.run(argv, stdin=fh, capture_output=True, text=True, encoding="utf-8", env=env, timeout=600)
    check(r.returncode == 0, f"argv どおりに起こせて exit 0（{r.returncode}: {r.stderr[:120]}）")
    got = json.loads(r.stdout)
    want = len(pathlib.Path(inst["launch"]["stdin"]).read_bytes())
    check(got["seen_bytes"] == want, f"標準入力が欠けずに届く（届いた {got['seen_bytes']} / 渡した {want} バイト）")
    check("--setting-sources" in got["argv"] and got["argv"][got["argv"].index("--setting-sources") + 1] == "",
          "起こされた側の argv にも遮断のフラグが入っている（形だけでなく実際に渡っている）")

    # 実物の失敗形: 非 0 終了と短い非 JSON（1 周目の認証落ちがこの形だった）
    fake = _fake_claude(bindir, "import sys\nsys.stdin.buffer.read()\nsys.stdout.write('Invalid API key\\n')\nsys.exit(1)\n")
    with open(inst["launch"]["stdin"], "rb") as fh:
        r = subprocess.run(argv, stdin=fh, capture_output=True, text=True, encoding="utf-8", env=env, timeout=600)
    check(r.returncode != 0 and "Invalid API key" in r.stdout, f"失敗形（非 0・短い非 JSON）を観測できる（rc={r.returncode}）")
    out = run.tmp / "bad.json"
    out.write_text(r.stdout, encoding="utf-8")
    d = run.cmd("done", "--node", inst["id"], "--output", str(out))
    check(d.returncode == 1 and "JSON" in d.stderr, f"その返答を done に渡すと exit 1 で拒まれる（{d.returncode}: {d.stderr[-90:]}）")
    rm(run.tmp)


def test_relative_dir():
    """**`--dir` を相対で渡した run が、全周の生出力を読む節まで通る。**

    盤面は出力ファイルの綴りを 1 つに決める（盤面からの相対）。以前は同じ 1 行が 2 つの綴りで書いており
    （`state["outputs"]["file"]` は盤面からの相対、instance の `output_file` は `--dir` をそのまま前に付けた綴り）、
    後者は**記録されていない過去の作業ディレクトリ**に錨を持っていた。帰結: 相対の `--dir` で回すと
    `ref:raw` / `ref:out.<節>` が `<dir>/<dir>/…` を読みに行って exit 2（実測 2026-09-13: 5 周・33 節のうち
    `ref:raw` を使う節が最終報告の 1 本だけだったので、run の最後の節まで現れなかった）。
    この腕は**その 1 本が通る所まで**回す——綴りが割れると必ず赤くなる。
    """
    print("相対 --dir: 盤面の綴りが 1 つで、全周の生出力を読む節まで通る")
    run = Run("reldir")
    # 同じ盤面を相対の --dir で開き直す（init は絶対で作られている）
    rel = os.path.relpath(run.dir, run.repo)
    check(not os.path.isabs(rel), f"相対の --dir を作れた（{rel}）")
    drive(run, "std")
    rec = run.record()
    check(rec.get("convergence") or rec.get("process", {}).get("outcome"), "相対の準備でも run は最後まで進む")
    # 盤面が持つ綴りが 1 つであること——ここが割れると ref: の解決が cwd に依る
    st = run.state()
    stored = [i["output_file"] for rd in st["rounds"] for i in rd["instances"].values() if i.get("output_file")]
    check(stored and not any(os.path.isabs(x) or x.startswith(str(run.dir)) for x in stored),
          f"instance の output_file は盤面からの相対 1 つの綴り（{stored[:1]}）")
    # 相対の --dir で ref: を解決させる——engine を別 cwd から呼び、全周の生出力を読む経路を通す
    r = subprocess.run([PY, str(LOOP), "status", "--dir", rel], cwd=run.repo,
                       capture_output=True, text=True, encoding="utf-8", timeout=600)
    check(r.returncode == 0, f"相対の --dir で盤面を開ける（{r.returncode}: {r.stderr[-160:]}）")
    sys.path.insert(0, str(PLUGIN))
    from engine.board import Board
    b = Board(run.dir)
    got = b.ref("raw")
    check(bool(got), "ref:raw が全周の生出力を返す（1 件以上）")
    for _, f, _ in got:
        check(pathlib.Path(f).is_file(), f"ref:raw が指す置き場が実在する（{f}）")
        break
    rm(run.tmp)


def test_research_vocab_not_copied():
    """**research 側の語彙も検証器 1 か所から渡す。** review 側で閉じた形が、こちらには手つかずで残っていた。

    実測 2026-09-13: research の prompt 6 本が検証器の名前表を 13 か所で並べ直していた——review の
    `p2.diagnose.md` で同じ形を閉じた当日に、こちらは 1 か所も直っていない。**知見が片側にしか
    適用されない**のが、この周の一撃（宣言している面が消費している面より狭い）の別の顔。
    """
    print("否定検査: research の判定語彙も検証器が組み立てて渡す")
    sys.path.insert(0, str(PLUGIN))
    import importlib.util
    from engine.render import Renderer
    spec = importlib.util.spec_from_file_location("rvrec", str(VALIDATOR))
    V = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(V)
    check(hasattr(V, "PROMPT_TABLES"), "検証器が貼る用の表を宣言している")
    for name in ("p1.checker", "p1.refuter", "p3.sampling"):
        tpl = (PLUGIN / "prompts" / "research-loop" / f"{name}.md").read_text(encoding="utf-8")
        check("{{validator." in tpl, f"{name}: 語彙を穴で受ける")
        # 節の他の穴（item.* 等）は reads の外なので、語彙の穴だけを取り出して埋める
        holes = "\n".join(ln for ln in tpl.splitlines() if "{{validator." in ln)
        got = Renderer({"validator": V.PROMPT_TABLES}, ["validator"]).render(holes)
        missing = [v for v in V.VERDICTS if v not in got]
        check(not missing, f"{name}: 検証器が知る判定語が 1 つ残らず届く（届かない: {missing}）")
    # **生成されている証拠**: 検証器に判定語を足すと、プロンプトを触らずに届く
    grown = dict(V.PROMPT_TABLES)
    grown["verdicts"] = V.PROMPT_TABLES["verdicts"] + "／架空の判定（台本が足した）"
    tpl = (PLUGIN / "prompts" / "research-loop" / "p1.checker.md").read_text(encoding="utf-8")
    holes = "\n".join(ln for ln in tpl.splitlines() if "{{validator." in ln)
    check("架空の判定" in Renderer({"validator": grown}, ["validator"]).render(holes),
          "検証器に足した語が、プロンプトを触らずに役へ届く（写しなら届かない）")


def test_porcelain_memo():
    """**作業ツリーの写しは 1 プロセスに 1 回。** 前後の突合は別プロセスなので混ざらない。

    以前は engine が `emit_instance` の中だけで memo を持ち、rules は素の `porcelain()` を呼んでいたので、
    周が変わる next で同じ `git status` が 2 回走っていた（1 回 15 ミリ秒）。**memo は盤面が持つ。**

    `next` と `done` は別プロセスなので、P1 の前後（`worktree_before` / `worktree_after`）が同じ写しを
    見ることはない——混ざる心配をしたが、実測で別プロセスだと確かめた。前後の柵そのものの腕は
    simulate_review の `test_worktree_guard_fires` が持つ。
    """
    print("否定検査: 作業ツリーの写しは 1 プロセス 1 回（前後は別プロセスなので混ざらない）")
    sys.path.insert(0, str(PLUGIN))
    import engine.util as U
    from engine.board import Board
    run = Run("porcmemo")
    b = Board(run.dir)
    calls = []
    real = U.porcelain
    U.porcelain = lambda: (calls.append(1), real())[1]
    try:
        a1, a2, a3 = b.porcelain(), b.porcelain(), b.porcelain()
    finally:
        U.porcelain = real
    check(len(calls) == 1, f"同じ盤面では 1 回しか引かない（{len(calls)} 回）")
    check(a1 == a2 == a3, "同じ値を返す")
    b2 = Board(run.dir)
    calls.clear()
    U.porcelain = lambda: (calls.append(1), real())[1]
    try:
        b2.porcelain()
    finally:
        U.porcelain = real
    check(len(calls) == 1, "盤面を開き直せば取り直す（別プロセス＝別の時点）")
    rm(run.tmp)


def test_optional_writes_declared():
    """**任意の欄を写す write は、任意だと宣言してあること。** engine は欄が無い返答を黙って読み飛ばす。

    `has_path` が偽なら `continue` なので、役が省いた周は**その write だけ音も無く消える**——
    「意図した省略」と「綴り違い・欄の消失」が同じ無音になる。宣言で分け、実際に飛んだ周は記録に残す。
    """
    print("否定検査: 任意の欄を写す write は宣言が要る／飛んだら痕跡が残る")
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="gl-optw-"))
    MADE.add(tmp)
    shutil.copytree(PLUGIN / "prompts", tmp / "prompts")
    shutil.copytree(PLUGIN / "rules", tmp / "rules")
    (tmp / "graphs").mkdir()
    g = json.loads((PLUGIN / "graphs" / "research-loop.json").read_text(encoding="utf-8"))
    nid = next(k for k, v in g["nodes"].items()
               if v.get("schema", {}).get("required") and v.get("writes"))
    n = g["nodes"][nid]
    opt = "smoke_optional"
    n["schema"].setdefault("properties", {})[opt] = {"type": "string"}
    n["writes"].append({"op": "set", "to": "process.smoke", "from": opt})
    gp = tmp / "graphs" / "research-loop.json"
    gp.write_text(json.dumps(g, ensure_ascii=False), encoding="utf-8")

    def gcheck():
        r = subprocess.run([PY, str(GRAPHCHECK), str(gp), str(VALIDATOR)], capture_output=True, text=True,
                           encoding="utf-8", timeout=600)
        return r.returncode, [ln for ln in (r.stdout + r.stderr).splitlines() if ln.startswith("NG") and opt in ln]

    code, ng = gcheck()
    check(code != 0 and ng, f"required に無い欄を写すのに宣言が無ければ落とす（{ng[:1]}）")
    n["writes"][-1]["optional"] = True
    gp.write_text(json.dumps(g, ensure_ascii=False), encoding="utf-8")
    code, ng = gcheck()
    check(code == 0 and not ng, f"optional を宣言すれば通る（{code}: {ng[:1]}）")
    # **実際に飛んだ周は痕跡に残る。** 宣言の要求は静的な側で、役が毎周省いていることは記録にしか出ない
    # （この腕を足す前、痕跡を残す行を消しても全件緑だった）
    run = Run("optw", graph=gp)
    drive(run, "std")
    sk = run.state().get("writes_skipped") or []
    check(any(s["node"] == nid and s["from"] == opt for s in sk),
          f"役が省いた欄の write が飛んだことが盤面に残る（{sk[:2]}）")
    check((run.dir / "record.json").is_file() and opt not in json.loads((run.dir / "record.json").read_text(encoding="utf-8")).get("process", {}),
          "飛んだ write の着地先は書かれない（無音で消えるのを痕跡で見えるようにしただけ）")
    rm(run.tmp)
    rm(tmp)


def test_answer_vocabulary():
    """**人の答えの語は engine が表で持つ。** 知らない語が「続ける」側に落ちない。

    以前は `ans == "stop"` だけを見て、それ以外は全部 else（新しい周を開く）だった。rules が諮りの
    選択肢に綴り違いや engine の知らない語を入れると、**その語が「続ける」として通る**——諮った意味が消える。
    諮りの口は「止める／続ける」の分岐なので、**既定を「続ける」にしてはいけない。**
    """
    print("否定検査: 人の答えの語は engine の表に在るものだけ")
    sys.path.insert(0, str(PLUGIN))
    from engine.util import ANSWER_ACTIONS
    check(set(ANSWER_ACTIONS) == {"continue", "stop", "escalate"}, f"engine が動ける語（{ANSWER_ACTIONS}）")
    run = Run("answers")
    drive(run, "stuck")
    # 諮っている盤面を作り、選択肢に engine の知らない語を混ぜて next を通す（立てる側で落ちる）
    st = run.state()
    st["status"] = "running"
    st["pending_human"] = {"node": "converge", "kinds": ["stuck"], "items": ["x"], "options": ["continue", "halt"]}
    (run.dir / "state.json").write_text(json.dumps(st, ensure_ascii=False), encoding="utf-8")
    r = run.cmd("answer", "--text", "halt")
    check(r.returncode != 0 and "動けない語" in (r.stdout + r.stderr),
          f"engine が動けない語は答えられない（{r.returncode}: {(r.stdout + r.stderr)[-140:]}）")
    r = run.cmd("answer", "--text", "nope")
    check(r.returncode != 0, "選択肢に無い語も拒む（元からの腕）")
    # **立てる側も通す。** 上は盤面を手で書いて答える側だけを踏んでいるので、`advance` から諮りの腕を
    # 外しても緑のままだった（実測: この腕を足す前、2 か所のうち片方しか覆えていなかった）。
    # rules の converge に engine の知らない語を返させ、実物の next で落ちることを見る
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="gl-ansopt-"))
    MADE.add(tmp)
    shutil.copytree(PLUGIN / "prompts", tmp / "prompts")
    shutil.copytree(PLUGIN / "rules", tmp / "rules")
    (tmp / "graphs").mkdir()
    rp = tmp / "rules" / "research-loop.py"
    rp.write_text(rp.read_text(encoding="utf-8").replace(
        '"options": ["continue", "stop"]', '"options": ["continue", "halt"]'), encoding="utf-8")
    gp = tmp / "graphs" / "research-loop.json"
    gp.write_text((PLUGIN / "graphs" / "research-loop.json").read_text(encoding="utf-8"), encoding="utf-8")
    r2 = Run("ansopt", graph=gp)
    seen = ""
    for _ in range(60):
        nx = r2.cmd("next")
        seen += nx.stderr
        if nx.returncode != 0 or not nx.stdout.strip():
            break
        out = json.loads(nx.stdout)
        if not out["ready"]:
            break
        tbl = base_answers(r2, "stuck")
        for inst in out["ready"]:
            r2.done(inst["id"], tbl[inst["node"]](inst["item"], out["round"]))
    check("動けない語" in seen or "halt" in seen,
          f"諮りの選択肢に engine の知らない語が在れば、立てる側で落ちる（{seen[-160:]}）")
    rm(tmp)
    rm(r2.tmp)
    rm(run.tmp)


def test_stopped_gates_all_thicknesses():
    """**収束せず停止した run は、どの段でも報告できなければならない。**

    停止の到達経路は max_rounds・thrash・stuck・独立検証不能の 4 つで、どれも設計上「停止して報告する」筋。
    ところがゲートが `not_applicable` のまま残ると検証器が落ち、`report_accepts_exit` の既定 [0] の外なので
    engine が die して **report の節が永久に出ない**。

    前の周にこれを直したが、**直したのは 3 本のうち 2 本だけだった**——`cartographer` が漏れ、重厚段で
    停止した run は同じ理由で報告が出ないまま残っていた（実測 2026-09-13: 部品を直に呼び、重厚でだけ
    理由の付かない not_applicable が残ることを確認）。**1 本直して赤が消えたところで止めた形。**
    この腕は段を 3 つとも踏む——1 段だけ見ていると同じ漏れがまた通る。
    """
    print("否定検査: 停止した run のゲートは、どの段でも『飛ばした』と名乗る")
    sys.path.insert(0, str(PLUGIN))
    from engine.rules import load_rules
    gp = PLUGIN / "graphs" / "research-loop.json"
    rules = load_rules(gp, json.loads(gp.read_text(encoding="utf-8")))
    gates = ("rederiver", "cold_reader", "cartographer")

    def stopped_record(th):
        rec = {"gates": {k: {"status": "not_applicable"} for k in gates},
               "sampling": {"status": "not_applicable"}, "claims": [], "clusters": [], "process": {}}
        b = types.SimpleNamespace(record=rec, state={"thickness": th}, loop_state={"outcome": "stopped"}, round=3)
        rules.finalize(b)
        return rec["gates"]

    for th, want in (("軽量", ()), ("標準", ("rederiver", "cold_reader")), ("重厚", gates)):
        g = stopped_record(th)
        for k in want:
            check(g[k].get("status") == "not_run",
                  f"{th}: {k} は『飛ばした』として残る（緑と数えない）——{g[k].get('status')}")
        for k in gates:
            check(bool(g[k].get("reason")), f"{th}: {k} に理由が付く（無言の not_applicable を残さない）")
            if k not in want:
                # **その段で必須でないゲートを『飛ばした』と名乗らせない。** not_run は「走らせる筋だったのに
                # 走らなかった」で、「この段では走らせない」とは別の事実——混ぜると、段を下げただけの run が
                # 検査を飛ばしたように読める（実測: 重厚の絞りを外す退行を注入したとき、この腕が無くて緑だった）
                check(g[k].get("status") == "not_applicable",
                      f"{th}: {k} はこの段では走らせない（飛ばしたと名乗らない）——{g[k].get('status')}")


def test_graphcheck_sets_derived():
    """**柵が見る鍵の一覧を、engine と rules から組む（手で並べない）。**

    受理集合（検証器の終了コードのうち先へ進んでよいもの）の鍵を graphcheck が 2 語で手書きしていた。
    engine か rules が鍵を増やしても柵は増えないので、**増えた鍵だけ形を誰も検査しないまま通る**。
    この腕は「rules が宣言した鍵が実際に見られること」と「宣言しなければ見られないこと」を対で見る
    ——宣言が母数だという性質そのものを踏む。
    """
    print("否定検査: 受理集合の鍵は engine と rules の宣言から組む")
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="gl-acck-"))
    MADE.add(tmp)
    shutil.copytree(PLUGIN / "prompts", tmp / "prompts")
    shutil.copytree(PLUGIN / "rules", tmp / "rules")
    (tmp / "graphs").mkdir()
    gp = tmp / "graphs" / "research-loop.json"
    g = json.loads((PLUGIN / "graphs" / "research-loop.json").read_text(encoding="utf-8"))
    g.setdefault("record", {})["smoke_accepts_exit"] = None  # 形が壊れた受理集合（null）
    gp.write_text(json.dumps(g, ensure_ascii=False), encoding="utf-8")
    rp = tmp / "rules" / "research-loop.py"
    base = rp.read_text(encoding="utf-8")

    def gcheck():
        r = subprocess.run([PY, str(GRAPHCHECK), str(gp), str(VALIDATOR)], capture_output=True, text=True,
                           encoding="utf-8", timeout=600)
        return r.returncode, [ln for ln in (r.stdout + r.stderr).splitlines() if ln.startswith("NG") and "smoke_accepts_exit" in ln]

    code, ng = gcheck()
    check(not ng, f"control: rules が宣言しない鍵は見ない（宣言が母数）: {ng[:1]}")
    rp.write_text(base + '\n\nACCEPT_KEYS = ("smoke_accepts_exit",)\n', encoding="utf-8")
    code, ng = gcheck()
    check(code != 0 and ng, f"rules が宣言した鍵は形を検査される（{ng[:1]}）")
    # engine 側の鍵は宣言に依らず常に見る（graph が持てば必ず形を測る）
    rp.write_text(base, encoding="utf-8")
    g2 = json.loads(gp.read_text(encoding="utf-8"))
    g2["record"].pop("smoke_accepts_exit", None)
    g2["record"]["report_accepts_exit"] = "0"
    gp.write_text(json.dumps(g2, ensure_ascii=False), encoding="utf-8")
    code, _ = gcheck()
    r = subprocess.run([PY, str(GRAPHCHECK), str(gp), str(VALIDATOR)], capture_output=True, text=True, encoding="utf-8", timeout=600)
    check(r.returncode != 0 and any("report_accepts_exit" in ln for ln in r.stdout.splitlines() if ln.startswith("NG")),
          "engine の鍵は rules の宣言に依らず常に形を検査される")

    # **フック名の綴り違いも、母数を手で並べない。** 以前は `on_` で始まる名前と手書きの 4 語だけを
    # 見ていたので、`finalize` を `finalise` と書いても母数に入らず 1 件も出なかった（実測 2026-09-13:
    # 直す前の柵に同じ綴り違いを注入したら exit 0 だった）。engine に非 `on_` のフックが増えた周も同じ。
    g3 = json.loads(gp.read_text(encoding="utf-8"))
    g3["record"].pop("report_accepts_exit", None)
    gp.write_text(json.dumps(g3, ensure_ascii=False), encoding="utf-8")
    for bad, near in (("finalise", "finalize"), ("on_new_rounds", "on_new_round")):
        rp.write_text(base + f"\n\ndef {bad}(b):\n    return None\n", encoding="utf-8")
        r = subprocess.run([PY, str(GRAPHCHECK), str(gp), str(VALIDATOR)], capture_output=True, text=True,
                           encoding="utf-8", timeout=600)
        hit = [ln for ln in (r.stdout + r.stderr).splitlines() if ln.startswith("NG") and bad in ln and near in ln]
        check(r.returncode != 0 and hit, f"フック '{near}' の綴り違い '{bad}' を落とす（{hit[:1]}）")
    rp.write_text(base, encoding="utf-8")
    r = subprocess.run([PY, str(GRAPHCHECK), str(gp), str(VALIDATOR)], capture_output=True, text=True, encoding="utf-8", timeout=600)
    check(r.returncode == 0, f"control: 綴りが正しければ通る（{r.returncode}）")
    rm(tmp)


def test_prompt_growth():
    """**周をまたいで育つ穴を測る。** 上限が無い経路でも、育っていることは言う。

    実測 2026-09-13: `report.human_items` が `record.process` と `loop` を丸ごと読み、6 周目で 1,120 KB。
    回す側の節なので上限が無く（`cap=None`）、切られないから `truncated_inputs` にも出ず、記録にも
    報告にも痕跡が 1 つも無かった。**上限の不在は「いくらでも貼ってよい」ではない。**

    見るのは大きさでなく育ち方——差分を丸ごと貼る節（912 KB）は大きくて正しい。大きさで線を引くと
    正しく大きい節が毎周鳴り、育っている節がその中に紛れる。
    """
    print("否定検査: 周をまたいで育つ穴（上限が無い経路でも測る）")
    sys.path.insert(0, str(PLUGIN))
    from engine.advance import PROMPT_NOTICE, prompt_growth

    def fake(rounds, rnd=2):
        return types.SimpleNamespace(round=rnd, state={"rounds": rounds})

    r1 = [{"round": 1, "instances": {"a": {"node": "n", "prompt_bytes": 100_000}}}]
    check(prompt_growth(fake([]), "n", 10 ** 7) is None, "前の周が無ければ言わない（比べる相手が無い）")
    # **線の腕は、倍率の腕が同時に成り立たない値で踏む。** 同じ値で両方が真になる入力だと、線を
    # 外しても倍率が拾って緑のまま（実測: PROMPT_NOTICE を 0 に替えても赤くならなかった）
    small = [{"round": 1, "instances": {"a": {"node": "n", "prompt_bytes": 1_000}}}]
    check(prompt_growth(fake(small), "n", 50_000) is None, "線より下は倍率が 50 倍でも言わない（小さい節の揺れ）")
    check(prompt_growth(fake(r1), "n", 140_000) is None, "1.5 倍以下は育ちと呼ばない")
    g = prompt_growth(fake(r1), "n", 160_000)
    check(g and g["was"] == 100_000 and g["bytes"] == 160_000, f"線を超えて 1.5 倍を超えたら言う（{g}）")
    check(prompt_growth(fake(r1), "other", 10 ** 7) is None, "別の節の大きさとは比べない")
    # **比べる材料が残っていること。** prompt_bytes が instance に無いと、育ちは原理的に測れない
    run = Run("grow")
    drive(run, "std")
    st = run.state()
    sizes = [i.get("prompt_bytes") for rd in st["rounds"] for i in rd["instances"].values()]
    check(sizes and all(isinstance(x, int) and x > 0 for x in sizes),
          f"実物の next が節ごとの大きさを残す（{len(sizes)} 節・欠けは {sum(1 for x in sizes if not x)} 件）")
    rm(run.tmp)


def test_frozen_schema_drift():
    """**`once` で凍った出力を、今の schema で測り直す。**

    `once` の出力は最初に走った周で凍る。あとから schema に必須の欄を足しても、その節はもう走らないので
    **欄は永久に現れない**。欄を読む cond・述語は「無い＝偽」に倒れ、run の残り全周で偽のままになる
    ——しかも痕跡が無いので、「条件に当たらなかった」と区別できない。

    実測 2026-09-13: review-loop の `p0.purpose` に `source_files` を 5 周目に足したが、この節は 1 周目で
    凍っていた。欄を読む `purpose_sources_changed` は 6 周とも偽で、目的監査の走り直しが一度も起きず、
    **R2（独立設計との突合）が 6 周とも走らなかった**。run が収束できない本当の理由がこれだった。

    この腕は control（締める前は鳴らない）と本番（締めたら鳴る）を対で見る——常に鳴る仕掛けは、
    鳴ったことが証拠にならない。
    """
    print("否定検査: once の節の凍った出力を、今の schema で測り直す")
    # graph の綴りは同梱からの相対（`../prompts/…`）で、rules も graph の隣から引く。写しは同じ形に置く
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="gl-frozen-graph-"))
    MADE.add(tmp)
    shutil.copytree(PLUGIN / "prompts", tmp / "prompts")
    shutil.copytree(PLUGIN / "rules", tmp / "rules")
    (tmp / "graphs").mkdir()
    gp = tmp / "graphs" / "research-loop.json"
    g = json.loads((PLUGIN / "graphs" / "research-loop.json").read_text(encoding="utf-8"))
    gp.write_text(json.dumps(g, ensure_ascii=False), encoding="utf-8")
    run = Run("frozen", graph=gp)
    node = "p0.question"  # once の節。1 周目で凍る
    # **走り切らせない。** 締めたあとに実物の `next` を通すので、盤面が動く途中で止める
    for _ in range(12):
        nx = run.next()
        if not nx["ready"]:
            break
        answers = base_answers(run, "std")
        for inst in nx["ready"]:
            run.done(inst["id"], answers[inst["node"]](inst["item"], nx["round"]))
        if node in run.state()["done_ever"]:
            break
    sys.path.insert(0, str(PLUGIN))
    from engine.advance import frozen_outputs_stale
    from engine.board import Board

    b = Board(run.dir)
    check(b.nodes[node].get("once") and node in b.state["done_ever"], f"{node} は once で、もう出さない集合に載っている")
    notes = []
    frozen_outputs_stale(b, notes)
    check(not notes and not b.state.get("stale_frozen"), f"control: graph を締める前は鳴らない（{notes[:1]}）")

    # 凍った出力が持ちえない欄を、その節の schema に足す（5 周目に source_files を足したのと同じ形）
    sch = g["nodes"][node]["schema"]
    sch["required"] = list(sch.get("required", [])) + ["source_files"]
    sch.setdefault("properties", {})["source_files"] = {"type": "array", "items": {"type": "string"}}
    gp.write_text(json.dumps(g, ensure_ascii=False), encoding="utf-8")

    b2 = Board(run.dir)
    notes2 = []
    frozen_outputs_stale(b2, notes2)
    stale = b2.state.get("stale_frozen") or []
    check(len(stale) == 1 and stale[0]["node"] == node, f"締めたら鳴る（{[s.get('node') for s in stale]}）")
    check(any("source_files" in e for e in (stale[0].get("errors") or [])), f"足した欄が理由に出る（{stale[0].get('errors')}）")
    check(stale[0].get("frozen_in") == 1, f"どの周で凍ったかが残る（{stale[0].get('frozen_in')}）")
    check(notes2 and node in notes2[0], f"回す側にも知らせる（{notes2[:1]}）")
    # 節ごとに 1 度だけ——周ごとに繰り返すと notes が同じ行で埋まる
    notes3 = []
    frozen_outputs_stale(b2, notes3)
    check(not notes3 and len(b2.state.get("stale_frozen") or []) == 1, "同じ節は 2 度言わない")
    # **実物の `next` でも鳴ること。** 上の 3 つは部品を直に呼んでいるので、`advance` から呼び出しを
    # 外しても全部緑のままだった（実測: この腕を足す前、3 か所のうち配線だけが覆われていなかった）
    nx = run.next()
    st = run.state()
    check(any(s["node"] == node for s in st.get("stale_frozen", [])), f"実物の next でも盤面に残る（{st.get('stale_frozen')}）")
    check(any(node in t for t in nx.get("notes", [])), f"実物の next が回す側に知らせる（notes: {nx.get('notes')}）")
    rm(tmp)
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


def test_plugin_path_ambiguity():
    """同名 plugin がキャッシュの 2 出所に在っても、明示（--validator）や同梱（同じリポジトリ）が先に見つかれば落ちない。
    以前は候補を積んだ後に出所の判定が来て、明示が在っても init が exit 2 で落ち、案内した回避策がその場で効かなかった
    （実測 2026-09-12）。"""
    print("否定検査: キャッシュの曖昧さは、明示・同梱で解決できない時だけ落とす")
    cfg = pathlib.Path(tempfile.mkdtemp(prefix="gl-cfg-"))
    for market, ver in (("marketA", "1.0.0"), ("marketB", "2.0.0")):
        d = cfg / "plugins" / "cache" / market / "convergence-loops" / ver
        (d / "scripts").mkdir(parents=True)
        shutil.copy(VALIDATOR, d / "scripts" / "research-record.py")
        (d / "agents").mkdir()
        shutil.copy(PLUGIN.parent / "agents" / "cold-reader.md", d / "agents" / "cold-reader.md")
    env = {**os.environ, "CLAUDE_CONFIG_DIR": str(cfg)}
    run = Run("ambig")
    d2 = run.tmp / "s2"
    call = lambda *a: subprocess.run([PY, str(LOOP), *a, "--dir", str(d2)], cwd=run.repo, capture_output=True, text=True, encoding="utf-8", env=env, timeout=600)
    r = call("init", "--loop", "research-loop", "--request", "q", "--document", str(run.doc), "--validator", str(VALIDATOR))
    check(r.returncode == 0, f"2 出所でも --validator の明示があれば init は通る（rc={r.returncode}: {r.stderr[-160:]}）")
    nx = call("next")
    ok = nx.returncode == 0 and nx.stdout.strip().startswith("{")
    if ok:  # 最初の波（回す側の節）を返して、役割 agent が出る波まで進める——役の定義の解決もキャッシュの曖昧さを踏まない
        o = run.tmp / "o.json"
        o.write_text(json.dumps(base_answers(run, "std")["p0.question"](None, 1), ensure_ascii=False), encoding="utf-8")
        call("done", "--node", "p0.question", "--output", str(o))
        nx = call("next")
        ok = nx.returncode == 0 and any(i["mode"] != "runner" for i in json.loads(nx.stdout)["ready"])
    check(ok, f"役の定義は同梱（同じリポジトリ）が先に当たるので、役が出る波の next も通る（rc={nx.returncode}: {nx.stderr[-160:]}）")
    rm(cfg); rm(run.tmp)


def test_unresolved_role():
    """役の定義（agents/<役>.md）が解決できない節は起こさない。以前は「定義なし」を「道具を持つ役」と同じ False に潰し、
    遮断系が黙って Agent ツール経路（mode=agent）に倒れて CLAUDE.md 注入の経路が戻っていた（実測 2026-09-12）。"""
    print("否定検査: 役の定義が解決できなければ next は die（Agent 経路に黙って倒れない）——別 plugin の役は止めずに痕跡を残す")

    def drive_graph(name, mutate, watch_node):
        """graph を 1 か所変えて init し、台本で回す。watch_node の instance と stderr を返す。"""
        tmp = pathlib.Path(tempfile.mkdtemp(prefix=f"gl-{name}-"))
        shutil.copytree(PLUGIN / "prompts", tmp / "prompts")
        shutil.copytree(PLUGIN / "rules", tmp / "rules")
        (tmp / "graphs").mkdir()
        g = json.loads((PLUGIN / "graphs" / "research-loop.json").read_text(encoding="utf-8"))
        mutate(g)
        (tmp / "graphs" / "g.json").write_text(json.dumps(g, ensure_ascii=False), encoding="utf-8")
        run = Run(name)
        d2 = run.tmp / "s2"
        call = lambda *a: subprocess.run([PY, str(LOOP), *a, "--dir", str(d2)], cwd=run.repo, capture_output=True, text=True, encoding="utf-8", timeout=600)
        call("init", "--loop", "research-loop", "--graph", str(tmp / "graphs" / "g.json"), "--request", "q", "--document", str(run.doc), "--validator", str(VALIDATOR))
        run.dir = d2  # 台本（base_answers）が読む盤面をこの run に向ける（Run() が作った盤面のままだと抜き取りの項目が食い違う）
        seen, insts, st = "", [], None
        for _ in range(80):
            nx = call("next")
            seen += nx.stderr
            if nx.returncode != 0 or not nx.stdout.strip():
                break
            out = json.loads(nx.stdout)
            if not out["ready"]:
                if out["status"] != "running":
                    break
                continue
            answers = base_answers(run, "std")
            for inst in out["ready"]:
                if inst["node"] == watch_node:
                    insts.append(inst)
                o = answers[inst["node"]](inst["item"], out["round"])
                f = run.tmp / "o.json"
                f.write_text(json.dumps(o, ensure_ascii=False) if not isinstance(o, str) else o, encoding="utf-8")
                call("done", "--node", inst["id"], "--output", str(f))
        if (d2 / "state.json").is_file():
            st = json.loads((d2 / "state.json").read_text(encoding="utf-8"))
        rm(tmp); rm(run.tmp)
        return seen, insts, st

    # graph 自身の plugin の役（遮断系はここにしか居ない）: 定義が無ければ die
    seen, insts, _ = drive_graph("norole", lambda g: g["nodes"]["p3.cold_reader"].__setitem__("run_by", "no-such-role"), "p3.cold_reader")
    check("解決できない" in seen and not insts, f"定義の無い役の節で next が die し、その節は一度も出ない（modes={[i['mode'] for i in insts]}: {seen[-160:]}）")
    # 別 plugin の役（pr-review-toolkit 等）はこの機械に無いことが普通にある（実測: CI）——止めず、痕跡を残して paste で出す
    seen, insts, st = drive_graph("foreign", lambda g: g["nodes"]["p1.checker"].__setitem__("agent_type", "other-plugin:someone"), "p1.checker")
    check("解決できない" not in seen and insts and all(i["mode"] == "agent" and i.get("deliver") == "paste" and i.get("role_def_missing") for i in insts),
          f"別 plugin の役は定義が無くても止めず、mode=agent・paste・role_def_missing 付きで出る（{len(insts)} 件: {seen[-120:]}）")
    check(bool(st) and any(x["agent_type"] == "other-plugin:someone" for x in st.get("role_def_missing", [])), "定義が無かった事実は state（→ process.role_def_missing）に残る")


def test_non_utf8_document():
    """file: の穴が指す文書（--document）が UTF-8 でない——render の read_text が厳格復号で UnicodeDecodeError を投げ、
    next が『想定外の例外』で exit 2 になっていた（git の出力側は util.git の errors=replace が別に守る。この腕は render 側）。"""
    print("台本: UTF-8 でない --document でも file: の穴は置換して埋まる（render 側の復号）")
    run = Run("latin")
    doc = run.repo / "latin.md"
    doc.write_bytes(b"# caf\xe9 \xff\n\n\xe9 claims\n")
    d2 = run.tmp / "s2"
    r = subprocess.run([PY, str(LOOP), "init", "--loop", "research-loop", "--request", "q", "--document", str(doc), "--dir", str(d2), "--validator", str(VALIDATOR)],
                       cwd=run.repo, capture_output=True, text=True, encoding="utf-8", timeout=600)
    check(r.returncode == 0, f"UTF-8 でない文書でも init は通る（{r.stderr[-80:]}）")
    call = lambda *a: subprocess.run([PY, str(LOOP), *a, "--dir", str(d2)], cwd=run.repo, capture_output=True, text=True, encoding="utf-8", timeout=600)
    q = json.loads(call("next").stdout)["ready"][0]
    f = run.tmp / "o.json"
    f.write_text(json.dumps(base_answers(run, "std")["p0.question"](None, 1), ensure_ascii=False), encoding="utf-8")
    call("done", "--node", q["id"], "--output", str(f))
    r = call("next")
    check(r.returncode == 0, f"文書を貼る節（p0.claims）を出す next が落ちない（rc={r.returncode}: {r.stderr[-100:]}）——以前は UnicodeDecodeError で exit 2")
    ready = json.loads(r.stdout)["ready"] if r.returncode == 0 else []
    claims = next((i for i in ready if i["node"] == "p0.claims"), None)
    body = pathlib.Path(claims["prompt_file"]).read_text(encoding="utf-8") if claims else ""
    check("�" in body and "claims" in body, "文書の本文は置換文字で欠けずに貼られる")
    rm(run.tmp)


def test_parse_output():
    """done が読む返答の剥がし方。**素の JSON を先に読む**——先に囲いを探すと、本文の中の ``` を囲いと誤認して
    中身を切り出し、正しい返答が『JSON として読めない』で拒まれる（実測 2026-09-12: 指摘文に ```json を書いた
    runner の返答が落ちた。役の指摘がコードの囲いに触れるのはレビューでは普通に起きる）。"""
    print("done の返答の読み方: 素の JSON → 本文中の囲い → { } の切り出し")
    sys.path.insert(0, str(PLUGIN))
    from engine.commands import parse_output
    from engine.util import Reject
    inner = {"findings": [{"where": "x", "text": "実物は ```json … ``` で囲んで返す。正規表現 ```(?:json)?\\s*(.*?)``` は常に不一致"}]}
    bare = json.dumps(inner, ensure_ascii=False)
    check(parse_output(bare) == inner, "本文に ``` を含む素の JSON は、そのまま読める（囲いと誤認しない）")
    check(parse_output("```json\n" + bare + "\n```") == inner, "全体を ```json で囲った返答は剥がして読める")
    check(parse_output("以下が返答です。\n```\n" + bare + "\n```\n以上。") == inner, "前後に文が付いた囲いも読める")
    try:
        parse_output("これは JSON ではない")
        check(False, "JSON の無い返答は Reject")
    except Reject:
        check(True, "JSON の無い返答は Reject")


def main():
    os.environ.pop("CONVERGENCE_LOOPS_ROOT", None)
    # 一時ディレクトリ（git リポジトリを含む）は各検査の末尾で消すが、例外で抜けた周回はそこへ届かない。
    # 走らせる側で後始末を保証する——確保は Run.__init__ の中で暗黙に起き、解放は呼び出し側の平文に在る非対称
    import tempfile as _t
    # **消すのは自分が作った作業場だけ。** 接頭辞で列挙して差分を消していたとき、実行中に他プロセスが作った
    # 作業場が差分に入り、そのプロセスの盤面が走行中に消えた（実測 2026-09-13: 退行注入と baseline が
    # 互いを殺し、落ちた台本が毎回違った）。Run が自分の tmp を持っているので、それを集めて消す
    # **台本は名前で集めて同時に走らせる。** 手で並べると足した台本の呼び忘れに誰も気づかない
    # （呼ばれない台本は件数を増やさないので件数の柵をすり抜ける）。同時に走らせてよいのは、
    # 台本どうしが自分の作業場しか触らないから——時間はほぼ全部が子プロセスの終了待ちだった。
    # 直列に戻すのは GL_TEST_WORKERS=1——並列でだけ落ちる台本を切り分けるときに使う。
    try:
        parallel.run_all(parallel.collect(globals()))
    finally:
        for _d in sorted(MADE):
            rm(_d)
    check(DELIVERY_SEEN >= {"p1.checker", "p3.cold_reader"}, f"渡し方の検査は checker（agent/path）と cold_reader（cli/paste）の両方に実際に当たった（{sorted(DELIVERY_SEEN)}）")
    reached, total, unreached = vocab_coverage()
    check(reached == VOCAB_REACHED,
          f"判定語彙の到達 {reached}/{total}（記録は {VOCAB_REACHED}）——筋書きを増やしたら数を上げろ。"
          f"未到達の頭: {unreached[:3]}")
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
