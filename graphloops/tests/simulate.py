#!/usr/bin/env python3
"""engine を、役の返答を台本で差し替えて端から端まで回す（役割 agent も LLM も使わない）。

確かめるのは engine と rules と graph の噛み合わせ——波の順・扇の被覆・件数突合・連続カウント・
ゲートの条件・抜き取り・収束と停止・記録が検証器（convergence-loops の research-record.py）を通ること。
役の判断の質は見ない（それは実走で見る）。

使い方: python3 simulate.py            # 全部の台本と否定検査を回す。失敗があれば exit 1
"""
import collections
import datetime
import hashlib
import importlib.util
import json
import os
import pathlib
import shutil
import subprocess
import sys
import threading
import time
import types

import fakeclaude  # 同じディレクトリ。代役の claude（既定は --output-format json の包みを返す）
import parallel  # 同じディレクトリ。台本を同時に走らせる土台（検査の中身は変えない）

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from engine.advance import ITEM_INLINE, load_item, slim_item  # noqa: E402 — 材料の上限と読み方は engine が正本（台本に写さない）
from engine.render import strip_prefix  # noqa: E402 — 穴の接頭の剥がし方も engine が正本
from engine.util import TERMINAL_STATUS, dump  # noqa: E402 — 終端の status は engine が正本（台本で並べ直さない）

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

# **読了の標本の作り方は rules が正本**（台本に数を写すと、engine だけ変えたとき検査が黙って緩む）。
# 名前にハイフンが入るので import 文では読めない——ファイルから読む
# engine が差し込む道具（engine/rules.py の INJECT が正本）。部品を直に呼ぶ腕のためにここでも差し込む
# ——**写さず import する**: 名前を手で並べると、engine が鍵を足した周に台本だけが古くなる。
# 読み込む前に差し込む（条件の宣言 cond_reads は rules の読み込みの時点で要る）
sys.path.insert(0, str(PLUGIN))
from engine.rules import INJECT as _INJECT  # noqa: E402
_spec = importlib.util.spec_from_file_location("research_rules", PLUGIN / "rules" / "research-loop.py")
RESEARCH_RULES = importlib.util.module_from_spec(_spec)
RESEARCH_RULES.__dict__.update(_INJECT)
_spec.loader.exec_module(RESEARCH_RULES)
PROBE_MIN, PROBE_POINTS = RESEARCH_RULES.PROBE_MIN, RESEARCH_RULES.PROBE_POINTS

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


def skip(desc, reason):
    """環境（OS・道具・権限）で走れない検査。件数には入れ（計画の件数は OS に依らず同じ）、合格と別の印で出す（parallel.skip_line）"""
    global ran
    with parallel.LOCK:
        ran += 1
    parallel.line(parallel.skip_line(desc, reason))


def rm(p):
    """作業場の掃除。Windows は git の object を読み取り専用で置き、素の rmtree が PermissionError で
    落ちる（実測: CI の windows-latest）。掃除の失敗で検査本体を落とさない。"""
    shutil.rmtree(p, ignore_errors=True)



# 台本が実際に返した判定語彙（(節, 欄) → 値の集合）。**「台本が 1 値固定」を件数でなく到達で測る。**
# review 側に同じラチェットを置いた当日、research 側には無かった——**知見が片側にしか適用されない**形。
VOCAB_SEEN = collections.defaultdict(set)
# 到達した語彙の数。**`!=` で見る**——下限だと筋書きを増やしても数が動かず、増やしたつもりの周に誰も気づかない。
VOCAB_REACHED = 23


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

    sys.path.insert(0, str(PLUGIN))
    from engine.schema import walk_schema as engine_walk  # noqa: E402 — schema の走査は engine の 1 本（patternProperties の下にも降りる）

    def walk_schema(nid, sch):
        for p, s in engine_walk(sch):
            if "enum" in s:
                enums[(nid, p.removeprefix("$").removeprefix("."))] = set(s["enum"])

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



class Run:
    def __init__(self, name, thickness=None, decider=None, unattended=False, graph=None, rel_dir=False, before_init=None):
        # graph=<path>: 同梱でなくその写しで回す。**回した後に graph を締める腕**（once の節の凍った出力を
        # 今の schema で測り直す）に要る——同梱を書き換えると、他の台本と本物のリポジトリを壊す
        self._td, self.tmp = parallel.workspace(f"gl-{name}-")
        self.repo = self.tmp / "repo"
        self.repo.mkdir()
        subprocess.run(["git", "init", "-q"], cwd=self.repo, check=True, timeout=120)
        subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "--allow-empty", "-m", "init"], cwd=self.repo, check=True, timeout=120)
        self.doc = self.repo / "mitate.md"
        # 読了の確かめは先頭・中間・末尾から 1 行ずつ取るので、**標本が別々の行になる長さ**にする
        # （1 行しか無い文書だと 3 標本が同じ行になり、部分読みと全文読みが区別できない）
        self.doc.write_text("# 見立て\n\n"
                            "この見立て文書の冒頭の一文は、読了の確かめの標本として先頭から取られる行である。\n\n"
                            "主張 A・B・C・D を含む見立て文書。この一文は中間の標本として取られる行である。\n\n"
                            "この見立て文書の末尾の一文は、読了の確かめの標本として末尾から取られる行である。\n",
                            encoding="utf-8")
        subprocess.run(["git", "add", "."], cwd=self.repo, check=True, timeout=120)
        subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "-m", "doc"], cwd=self.repo, check=True, timeout=120)
        # **読了の確かめは engine が session の転写を読む。** 台本は本物と同じ形の転写を作り、
        # 同じ env（CLAUDE_CONFIG_DIR / CLAUDE_CODE_SESSION_ID）で engine に見つけさせる——
        # 検査用の抜け道（環境変数で柵を外す口）を作らないため、渡し方は本番と同じにする
        self.session = f"gl-{name}-session"
        self.cfg = self.tmp / "config"
        self.transcript = self.cfg / "projects" / "sim" / f"{self.session}.jsonl"
        self.transcript.parent.mkdir(parents=True, exist_ok=True)
        self.transcript.write_text("", encoding="utf-8")
        self.env = {**os.environ, "CLAUDE_CONFIG_DIR": str(self.cfg), "CLAUDE_CODE_SESSION_ID": self.session}
        self.read_into_transcript(self.doc)
        self.dir = self.tmp / "state"
        # rel_dir: **init から相対の --dir で回す**（盤面の外から渡る綴りが解決されているかを測る腕）。
        # cmd の cwd は repo に固定なので、相対の綴りはこの run の中では一貫している
        self.rel_dir = os.path.relpath(self.dir, self.repo) if rel_dir else None
        args = ["init", "--loop", "research-loop", "--request", "この見立ては正しいか", "--document", str(self.doc),
                "--dir", self.rel_dir or str(self.dir), "--validator", str(VALIDATOR)]
        if thickness:
            args += ["--thickness", thickness]
        if decider:
            args += ["--decider", decider]
        if unattended:
            args.append("--unattended")
        if graph:
            args += ["--graph", str(graph)]
        if before_init:
            before_init(self)
        self.init = self.cmd(*args)
        # **engine を回せば、その出力が道具の結果として転写に載る**——本番と同じ形を代役にも作る。
        # 以前は文書の本文だけを転写に置いており、印（run_id）が一度も立たない転写で回していた。
        # 印を成功側で見る分岐が無かった間はそれで通っていたが、その分岐そのものが柵の穴だった。
        if self.init.returncode == 0:
            self.mark_into_transcript()

    def mark_into_transcript(self):
        """engine を回した痕跡（この run の run_id）を転写に足す。

        **実物と同じ形で置く。** 実測（2026-09-20・実走の転写 21.3 MB）では、run_id が道具の結果に
        載った 4 件のうち engine の JSON がそのまま載ったのは 0 件で、残りは回す側が整形し直した形と
        `done` の平文 1 行だった。代役が JSON の綴りだけを作っていると、実物で最も多い形を一度も踏まない。
        ここは実物で最も確実に残る形——`done` の平文 1 行——を置く。
        """
        rid = json.loads((self.dir / "state.json").read_text(encoding="utf-8"))["run_id"]
        body = f"ok p0.question を受け付けた（読んだ先: --output /dev/null）。続きは loop.py next（run {rid}）"
        line = json.dumps({"message": {"content": [{"type": "tool_result", "content": body}]}}, ensure_ascii=False)
        with open(self.transcript, "a", encoding="utf-8") as f:
            f.write(line + "\n")

    def read_into_transcript(self, path):
        """その文書を『会話で読んだ』痕跡を転写に足す（本物の道具の結果と同じ形の 1 行）。"""
        body = pathlib.Path(path).read_bytes().decode("utf-8", "replace")
        line = json.dumps({"message": {"content": [{"type": "tool_result", "content": body}]}}, ensure_ascii=False)
        with open(self.transcript, "a", encoding="utf-8") as f:
            f.write(line + "\n")

    def cmd(self, *args, stdin=None, env=None):
        r = subprocess.run([PY, str(LOOP), *args, *([] if args[0] == "init" else ["--dir", self.rel_dir or str(self.dir)])],
                           cwd=self.repo, capture_output=True, text=True, encoding="utf-8", input=stdin,
                           env=env if env is not None else self.env, timeout=600)
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
        # 読了の確かめは返答の欄でなく session の転写で見る（post_check claims_intake）——返答に印の欄は無い
        "p0.claims": lambda it, r: {"claims": [{"id": "A", "claim": "A は X", "load_bearing": True}, {"id": "B", "claim": "B は Y", "load_bearing": False},
                                               {"id": "C", "claim": "C は Z", "load_bearing": False}, {"id": "D", "claim": "D は W", "load_bearing": False}],
                                    "judgments": [{"text": "好み"}], "judgments_as_facts": [],
                                    # **claims_intake が読むのはこちらの欄**（p0.question の同名の欄ではない）。
                                    # 筋書き 'open' がここを空のままだったので、不成立の理由と結ぶ経路が一度も実行されていなかった
                                    "open_questions": ["選択肢の洗い出し（P1 では解けない）"] if scenario == "open" else [],
                                   },
        "p0.clusters": lambda it, r: {"clusters": [{"key": "c1", "claim_ids": ["A", "B"]}, {"key": "c2", "claim_ids": ["C", "D"]}]},
        "p0.terms": lambda it, r: {"terms": [{"term": "見立て", "definition": "設計の仮説", "status": "社内造語"}],
                                   },
        "p0.prior_decisions": lambda it, r: {"checked": True, "searched": ["GitHub の issue・PR（gh）", "docs/", "git log"], "settled_points": [], "overlaps": [], "reopen_proposals": []},
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
                seen_delivery.add(node)      # 台本ごとの集合（この台本しか触らない）
                with parallel.LOCK:          # 台本をまたぐ集合は排他の中で触る（check と同じ規律）
                    DELIVERY_SEEN.add(node)
                # 遮断系は cli で出るので mode も見る（以前は mode == "agent" と round == 1 を条件にしていて cold_reader の腕が空振りしていた）
                want_mode, want = ("agent", "path") if node == "p1.checker" else ("cli", "paste")
                # 役の節は engine が起こし、材料は標準入力で流れる。deliver は launch が無いときに Agent で起こす受け皿の渡し方
                check(inst["mode"] == want_mode and inst.get("deliver") == want and (inst.get("launch") or {}).get("stdin") == inst["prompt_file"],
                      f"{node} は mode={want_mode}・engine が起こして材料は stdin（受け皿の渡し方は {want}。役の道具から決まる）")
            out = answers[node](load_item(inst), nx["round"])
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
    # 開いた問いが 0 件の run の収束の文言は、分けた文言を足す前と 1 字も変わらない（回帰）
    check(converge_reasons(run)[-1] == "連続 2 周で新規相違ゼロ、標準 段のゲートは全部 pass",
          f"開いた問いの無い収束の文言は元のまま: {converge_reasons(run)[-1:]}")
    v = subprocess.run([PY, str(VALIDATOR), str(run.dir / "record.json")], capture_output=True, text=True, encoding="utf-8", timeout=600)
    check(v.returncode == 0, f"検証器が exit 0（{v.stdout.strip()[:60]}）")
    r1 = st["rounds"][0]
    check("p0.independence_review" in r1["na"], "独立出典だけなので independence_review は na")
    check(any(i.startswith("p1.refuter[A]") for i in r1["instances"]) and any(i.startswith("p1.refuter[B]") for i in r1["instances"]), "refuter は A（荷重確証）と B（相違）に走った")
    check("p1.checker" in st["rounds"][2]["empty"], "3 周目の checker は項目ゼロ（empty）")
    check(len(rec["process"]["skipped"]) == 0, "省略なし")
    rm(run.tmp)


def test_policy_reaches_research_roles():
    """**人の方針の文書**（既定の置き場 <git の共有の置き場>/graphloops/policy.md）は research-loop にも届く——反証役・内部照合役には
    本文が貼られ、回す側の節（問いの確定）には置き場が渡る"""
    print("台本: 人の方針が research の役に貼られ、回す側には置き場が渡る")
    mark = "RESEARCH-POLICY-4c1（検査用の人の方針）"
    pol = lambda r: (r.repo / ".git" / "graphloops").mkdir(parents=True, exist_ok=True) or (r.repo / ".git" / "graphloops" / "policy.md").write_text(mark + "\n", encoding="utf-8")
    run = Run("policy", before_init=pol)
    check(run.init.returncode == 0, f"人の方針: research の init が通る（{run.init.stderr[-160:]}）")
    seen = {}

    def hook(run_, inst, out):
        seen.setdefault(inst["node"], pathlib.Path(inst["prompt_file"]).read_text(encoding="utf-8"))
        return None
    def hook2(run_, inst, out):
        if inst["node"] == "p5.internal":   # 回す側が方針の文書を書き換えた形（周の途中の関所は無いので、仕上げで照らす）
            (run_.repo / ".git" / "graphloops" / "policy.md").write_text(mark + "\nWRITER-EDIT-9d2\n", encoding="utf-8")
        return hook(run_, inst, out)
    drive(run, "std", hook=hook2)
    path = str((run.repo / ".git" / "graphloops" / "policy.md").resolve())
    rec = run.record()
    pol, ch = rec["process"].get("policy") or {}, rec["process"].get("policy_change") or {}
    check(pol.get("path") == path and len(pol.get("sha256") or "") == 64 and mark in pathlib.Path(pol.get("copy") or "/nonexistent").read_text(encoding="utf-8")
          and "amendments" not in pol,
          f"人の方針: research の init も文書の版（sha と写し）を記録に固定する（{pol}）")
    check(ch.get("from") == pol.get("sha256") and ch.get("to") and ch["to"] != ch["from"]
          and "+WRITER-EDIT-9d2" in pathlib.Path(ch.get("diff_file") or "/nonexistent").read_text(encoding="utf-8")
          and "WRITER-EDIT-9d2" not in json.dumps(ch, ensure_ascii=False),
          f"人の方針: run の途中で文書が変わったら、仕上げが前後の sha と差分のファイルを記録に残す（置き場だけで本文は載せない。{ch}）")
    check((run.dir / "report.md").is_file(), "人の方針: 文書が変わった run も報告まで届く（研究の run は周の途中で止めない）")
    check(mark in seen.get("p1.refuter", "") and mark in seen.get("p5.internal", ""),
          f"人の方針: 反証役と内部照合役のプロンプトに本文が貼られる（{sorted(k for k, v in seen.items() if mark in v)}）")
    check(path in seen.get("p0.question", "") and mark not in seen.get("p0.question", ""),
          "人の方針: 回す側の節（問いの確定）には本文でなく置き場が渡る")
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
    # **回す側の節には本文でなくパスが渡る。** 静的にも同じことを見る（graphcheck.py の main の
    # 「回す側（{rb}）の節に書けない」の柵——回す側の節に file: / section: の穴を書けない）
    # パスは engine の契約（init が resolve した綴り）で探す——生の綴りだと Windows の 8.3 短縮名（RUNNER~1）で外れる
    doc = str(run.doc.resolve())
    check(doc in prompts and "主張 A・B・C・D" not in prompts, "回す側の節には文書のパスが渡り、本文は貼られない")
    terms = pathlib.Path(by["p0.terms"]["prompt_file"]).read_text(encoding="utf-8")
    check(doc in terms and "主張 A・B・C・D" not in terms, "同じ波の 2 節目（p0.terms）も本文を貼らない")
    check("open_questions" not in prompts or "[]" in prompts or "この周には無い" in prompts,
          "前の節の出力の穴が埋まっている（空でなく値か『無い』の語）")
    for node in ("p0.claims", "p0.terms", "p5.internal", "p3.rederiver"):
        out = base_answers(run, "std")[node](None, 1)
        if node == "p0.claims":
            # 主張 A だけを太らせる（c1 の束が 1,000 バイト超・c2 は短いまま）。**日本語で約 350 字**なので
            # 字数では上限内・バイトでは超過——落ちる側と残る側が同じ波に並び、測り方も同時に固定される
            out = json.loads(json.dumps(out, ensure_ascii=False))
            out["claims"][0]["claim"] += "。" + "あ" * 350
        run.done(by[node]["id"], out)
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
    # **材料の長い欄は instance に残さない**（engine の slim_item と ITEM_INLINE が正本——import で縛る）。
    # **見るのは実物の next が返した instance**——純関数 slim_item を直に呼ぶ腕だけだと、逃がす配線
    # （emit_instance の呼び）を外しても、閾値を key 以外全部に倒しても、全件緑のままだった。
    # 長さは engine と同じ物差しで測る（util.dump と ITEM_INLINE を import する。台本に写すと engine だけ変えたとき緩む）
    c1full = load_item(ch["c1"])
    # 添字の前に在ることを見る——items/ が痩せる退行では、ここが KeyError で落ちて台本が要約行も出さずに終わる
    check("claims" in c1full, f"材料の正本（items/ のファイル）に材料の欄が在る（欄: {sorted(c1full)}）")
    chars = len(dump(c1full.get("claims")))
    check(chars < ITEM_INLINE < len(dump(c1full.get("claims")).encode("utf-8")),
          f"c1 の材料は字数では上限内・バイトでは超過（{chars} 字）——落ちること自体がバイトで測っている証拠になる")
    check(ch["c1"].get("item_omitted") == ["claims"] and "claims" not in ch["c1"]["item"] and ch["c1"]["item"].get("key") == "c1",
          f"太い材料の長い欄は instance から落ち、短い欄（key）は残る（残った: {sorted(ch['c1']['item'])} / 落とした: {ch['c1'].get('item_omitted')}）")
    check(ch["c2"].get("item_omitted") == [] and ch["c2"]["item"].get("claims"),
          f"短い材料は落ちず、落ちた欄が無いことも欄で言う（空でも書く: {ch['c2'].get('item_omitted')}）")
    # **key だけは長さに関わらず残す**（engine の slim_item が key を落とす候補から外している）。
    # 実物の波には 1,000 バイトの key が出ないので、ここだけ部品を直に呼ぶ
    fat_slim, fat_omitted = slim_item({"key": "あ" * 400, "claims": [{"id": "A"}]})
    # 見るのは **slim_item が key を落とさない** ことだけ——合計の上限が効くので、key が単独で上限を超える材料では
    # 他の欄が全部逃げる（それが正しい: key は下流が添字で読むので落とせない）。この長さの key が実物の next を
    # 通るかは別の層の話（プロンプトのファイル名長）で、上限の置き場が決まるまでここでは主張しない
    check("key" in fat_slim and "key" not in fat_omitted, f"上限を超える長さの key でも slim_item は key を落とさない（落とした: {fat_omitted}）")
    # **合計も同じ上限で縛る**——欄ごとの判定だけだと、上限直下の欄が並ぶ材料は 1 件も落ちずに instance が太る
    many_slim, many_omitted = slim_item({"key": "c1", **{f"f{i}": "あ" * 200 for i in range(4)}})
    check(len(dump(many_slim).encode("utf-8")) <= ITEM_INLINE and many_omitted,
          f"欄ごとに上限未満でも合計が超えれば大きい順に逃がす（残った: {sorted(many_slim)} / 落とした: {many_omitted}）")
    # **engine は instance の item を添字で読まない**（正本は items/ のファイル＝load_item）。写しは欄が
    # 落ちている可能性が在り、key を落とさない例外に支えた直読みは、写しの作り方を変えた周に静かに壊れる。
    # 実行の腕では赤にできない（今は key が必ず残るので、直読みでも同じ答えになる）ので、形で縛る
    # **綴りを 1 本に絞ると素通りする。** 二重引用だけを見ていたとき、i['item']['key'] と
    # i.get("item")["key"] はどちらも全件緑だった（実測 2026-09-19）——後者は load_item 自身が返す綴りで、
    # 次に書く人が踏むのはむしろそちら。書き手（slim_item の結果を instance に入れる 1 行）と、
    # 正本を読む load_item の中だけを名指しで許す
    # **閉じ括弧まで綴りに入れない**——.get("item", {})["key"] は既定値を足しただけの同じ直読みで、
    # 閉じ括弧まで見る柵はこれを素通りした（実測 2026-09-19: この 1 形で全件緑）
    SPELLINGS = ('["item"]', "['item']", '.get("item"', ".get('item'")
    ALLOW = ('inst["item"], omitted = slim_item(item)', 'return inst.get("item")')
    flags = lambda line: any(sp in line for sp in SPELLINGS) and not any(a in line for a in ALLOW)
    # **柵が名乗る綴りを、合成した行で直に測る。** 走査の結果が空であることだけを見ていたとき、
    # 綴りを 1 本に狭めても緑のままだった（実測 2026-09-19: 単引用と .get の形が素通りした）
    caught = [ln for ln in ('    x = i["item"]["key"]', "    x = i['item']['key']",
                            '    x = i.get("item")["key"]', "    x = i.get('item')['key']",
                            '    x = i.get("item", {})["key"]', "    x = i.get('item', {})['key']") if flags(ln)]
    check(len(caught) == 6, f"柵は 6 綴りとも拾う（拾えた: {len(caught)}/6）")
    # **拾わない形も標本で言う。** 「4 綴りを見ている」と注記で断る零処方は、綴りが増えた周に注記だけが
    # 古くなる（同じ手を 3 周続けて写しが増えた）。射程を毎回実行で踏ませ、広がったらこの腕が落ちる
    MISSES = ('    x = i [ "item" ]',            # 空白を挟んだ添字
              '    k = "item"; x = i[k]',         # 鍵を変数に逃がした形
              '    x = getattr(i, "item", None)',  # 属性としての読み
              '    x = {**i}["item"]'.replace('["item"]', '[ITEM_KEY]'),  # 鍵を定数に逃がした形
              )
    slipped = [ln for ln in MISSES if flags(ln)]
    check(not slipped, f"射程の外（空白入り・変数の鍵・属性・定数の鍵）は拾わない——拾い始めたら名乗りを広げろ: {slipped}")
    check(not flags('        inst["item"], omitted = slim_item(item)') and not flags('    return inst.get("item")'),
          "書き手と load_item の中は許す（許しが効いている）")
    direct = [f"{f.name}:{i + 1}" for f in sorted([*(PLUGIN / "engine").glob("*.py"), *(PLUGIN / "rules").glob("*.py")])
              for i, line in enumerate(f.read_text(encoding="utf-8").splitlines()) if flags(line)]
    check(not direct, f"engine と rules が instance の item を直読みしていない（6 綴りとも。load_item を通す。直読み: {direct}）")
    # **落とすのは大きい欄から**——小さい欄から落とすと、上限に収めるのに必要以上の欄が instance から消える
    order_slim, order_omitted = slim_item({"key": "c1", "small": "あ" * 10, "mid": "あ" * 60, "big": "あ" * 400})
    check(order_omitted == ["big"] and {"key", "small", "mid"} <= set(order_slim),
          f"大きい欄 1 つを落とせば収まる材料は、その 1 つだけが落ちる（落とした: {order_omitted}）")
    body = pathlib.Path(ch["c1"]["prompt_file"]).read_text(encoding="utf-8").split("返答はこの JSON Schema")[0]
    check("C は Z" not in body and '"verdict":' not in body and "surveyor" not in body, "checker には他の束の主張も判定も見立ても貼られない")
    # **落としてよいのは回す側の文脈だけで、役に渡る中身は減らしてはいけない。**
    # 期待値は台本側の独立な正本（c1 は A と B）から取る——materials 側（items/）から取ると、
    # 材料が痩せる退行で期待値も一緒に痩せて緑のままになる
    c1claims = load_item(ch["c1"])["claims"]
    want_ids = ["A", "B"]
    got_ids = [c["id"] for c in c1claims]
    missing = [c["id"] for c in c1claims if c["claim"] not in body]
    check(got_ids == want_ids and not missing and c1claims[0]["claim"][-20:] in body,
          f"役には束の全員（{want_ids}）が、本文の末尾まで渡る（材料: {got_ids} / 欠けた主張: {missing}）")
    tail = pathlib.Path(ch["c1"]["prompt_file"]).read_text(encoding="utf-8").split("返答はこの JSON Schema")[1]
    # 予防側（役に引用符をエスケープさせる断り）は、上の body が捨てる側に落ちる。ここで尾を見る
    # ——診断側だけを覆う検査は、直しの半分を文言ごと消しても色が変わらない（実測 2026-09-15）。
    check('\\"' in tail and "エスケープ" in tail, "役へ渡す schema の断りに、引用符をエスケープしろの 1 行が付く")
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


def test_hook_evidence():
    """**読んだ事実を、読んだ瞬間に盤面の隣へ残す（フックの一次情報）。**

    これまで柵は、会話の記録（転写 JSONL）を engine が後から開いて痕跡を探していた。
    公式文書が内部形式と明記するものを自前で解析する形で、壊れるたびに守りを足してきた。

    **ハーネス側は実物で測った**（2026-09-22、macOS。この検査では測れない——フックは session の
    開始時に読み込まれるので、子の claude を `--settings` 付きで起こして確かめた）: Read のたびに
    発火し（tool_use_id が `toolu_01HsNpjr…`）、offset 付きは partial で残り、**subagent の中でも
    発火して agent_id が載る**。ここで測れるのは engine と記録の契約までで、
    **ハーネスがフックを呼ぶことは検査では覆えない**。

    **書く先は盤面の隣で、回っている run が在るときだけ**——ここが一番の不変条件。
    最初は利用者ごとの置き場へ session 単位で永久に書く形で、graphloops を使っていない session の
    読み取り履歴まで寿命なしで溜めていた。盤面の隣なら run の寿命で消える。
    """
    print("読了の柵（フック）: 回っている run の盤面の隣にだけ書き、5 通りに分ける（read / none / absent / partial / stale）")
    _td, tmp = parallel.workspace("gl-hookev-")
    repo = tmp / "repo"; (repo / ".git" / "graphloops" / "research-loop").mkdir(parents=True)
    board = tmp / "board"; board.mkdir()
    doc = tmp / "doc.md"
    doc.write_text("aaa" + chr(10) + "bbb" + chr(10) + "ccc" + chr(10), encoding="utf-8")
    hook = PLUGIN / "hooks" / "record-read.py"

    # **利用者ごとの置き場を一時の場所へ向け、そこに何も出来ないことを見る。**
    # 盤面に何も出来ないことだけ見ていたとき、別の場所へ溜める形に戻す注入が赤にならなかった
    # （実測 r10: 腕 h6 が緑）——「どこにも書かない」は、書きうる場所を渡して初めて測れる
    cfg = tmp / "cfg"; cfg.mkdir()
    fire_env = {**os.environ, "CLAUDE_CONFIG_DIR": str(cfg), "HOME": str(tmp / "home")}

    def fire(path, cwd=None, **ti):
        payload = {"hook_event_name": "PostToolUse", "session_id": "sess-t", "tool_name": "Read",
                   "tool_use_id": "toolu_t", "agent_id": "agent-t", "cwd": str(cwd or repo),
                   # **実物と同じ形で渡す。** 実物のハーネスの tool_response は文字列でなく構造を持つ
                   "tool_input": {"file_path": str(path), **ti},
                   "tool_response": {"type": "text", "file": {"filePath": str(path)}}}
        r = subprocess.run([PY, str(hook)], input=json.dumps(payload), capture_output=True,
                           text=True, encoding="utf-8", timeout=60, env=fire_env)
        return r.returncode

    def ask():
        return RESEARCH_RULES.hook_evidence(board, str(doc))

    # **回っている run が無ければ 1 バイトも書かない。** ここが寿命の設計そのもの
    check(fire(doc) == 0, "run が無くてもフックは道具を止めない（終了コード 0）")
    check(not (board / "reads.jsonl").exists(), "**run が無い回は盤面に書かない**")
    strays = sorted(x for x in (list(cfg.rglob("*")) + list((tmp / "home").rglob("*"))) if x.is_file())
    check(not strays, f"**run が無い回はどこにも書かない**（利用者ごとの置き場にも: {strays[:2]}）")
    check(ask()[0] == "none", "記録が無ければ none（フックが入っていない環境で柵を切らない）")

    (repo / ".git" / "graphloops" / "research-loop" / "current").write_text(str(board), encoding="utf-8")
    other = tmp / "other.md"; other.write_text("zzz" + chr(10), encoding="utf-8")
    check(fire(other) == 0 and (board / "reads.jsonl").is_file(), "run が在れば盤面の隣に書く")
    check(ask()[0] == "absent", "記録は在るがこの文書の読みが無ければ absent")
    check(fire(doc, offset=2) == 0 and ask()[0] == "partial" and "offset / limit 付き" in ask()[1],
          "**部分読みは全文の証拠にしない**（offset / limit が付いた読み。説明もその理由を言う）")
    check(fire(doc) == 0, "全文読みを記録する")
    got, why = ask()
    check(got == "read", f"全文読みが在れば read（{why[:60]}）")
    check("agent" in why, "誰が読んだか（agent_id）を説明に載せる——subagent の中でも発火する")
    doc.write_text("aaa" + chr(10) + "bbb" + chr(10) + "CHANGED" + chr(10), encoding="utf-8")
    check(ask()[0] == "stale", "**読んだ後に文書が変われば stale**（中身は記録に残さず sha で突き合わせる）")
    import engine.util as _u  # noqa: E402
    _cap = _u.READ_CAP
    try:
        _u.READ_CAP = 1
        got, why = ask()
        check(got == "none" and "大きすぎて" in why, f"上限を超える文書は sha を取らず none（{why[:60]}）")
    finally:
        _u.READ_CAP = _cap
    check(fire(doc) == 0 and ask()[0] == "read", "読み直せば read に戻る")
    # **読めない文書は none に倒す**（例外を上げない）。記録は在るのに文書が消えた回に、
    # except OSError を外すと呼び元の done ごと落ちる
    got, why = RESEARCH_RULES.hook_evidence(board, str(tmp / "vanished.md"))
    check(got == "none" and "読めない" in why, f"読めない文書は例外でなく none（{why[:60]}）")
    # **フック側の上限は engine 側の写しで、2 つの値が揃っている。** フックは engine を import しないので
    # 値を写しで持つ——ずれると、読む側が捨てる sha を書く側が取り続ける（または逆）
    import importlib.util as _iu  # noqa: E402
    _spec = _iu.spec_from_file_location("gl_hook_cap", hook)
    _hk = _iu.module_from_spec(_spec); _spec.loader.exec_module(_hk)
    check(_hk.READ_CAP == _u.READ_CAP,
          f"フックの READ_CAP（{_hk.READ_CAP}）は engine の値（{_u.READ_CAP}）の写しで、揃っている")
    big = tmp / "big.bin"
    with open(big, "wb") as f:
        f.truncate(_u.READ_CAP + 2)   # 疎なファイルで大きさだけを作る（+2: 読めた長さ CAP+1 と stat の大きさを見分ける）
    check(fire(big) == 0, "上限を超える文書を読んでもフックは道具を止めない")
    rows = [json.loads(l) for l in (board / "reads.jsonl").read_text(encoding="utf-8").splitlines()]
    last = next(r for r in reversed(rows) if r.get("path") == str(big.resolve()))
    check(last.get("file_sha") is None and last.get("bytes") == _u.READ_CAP + 2,
          f"上限を超える文書は sha を取らず、大きさだけ残す（file_sha={last.get('file_sha')} bytes={last.get('bytes')}）")
    # **ちょうど上限の文書は測る**（境界を < に変えると、上限ちょうどの文書が事実と違う stale / none になる）
    edge = tmp / "edge.bin"
    with open(edge, "wb") as f:
        f.truncate(_u.READ_CAP)
    check(fire(edge) == 0, "上限ちょうどの文書を読んでもフックは道具を止めない")
    rows = [json.loads(l) for l in (board / "reads.jsonl").read_text(encoding="utf-8").splitlines()]
    last = next(r for r in reversed(rows) if r.get("path") == str(edge.resolve()))
    check(last.get("file_sha") is not None and last.get("partial") is True,
          f"上限ちょうどの文書は、フックが sha を取る。ハーネスが切りうる大きさなので partial で残す（{str(last.get('file_sha'))[:12]} / {last.get('partial')}）")
    # 読む側の境界は、全文読みの行を足して見る（フックはこの大きさを partial に倒すので、実物の行では read に届かない）
    with open(board / "reads.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps({**last, "partial": False, "tool_use_id": "edge-full"}) + chr(10))
    got, why = RESEARCH_RULES.hook_evidence(board, str(edge))
    check(got == "read", f"上限ちょうどの文書は、読む側も測って read を返す（{got}: {why[:50]}）")
    for name, body in (("lines.md", ("x" + chr(10)) * 2001), ("bytes.md", "y" * 25_001), ("l2000.md", ("x" + chr(10)) * 2000)):
        pth = tmp / name; pth.write_text(body, encoding="utf-8")
        check(fire(pth) == 0, f"{name} を読む")
    small = tmp / "small.md"; small.write_text("s" + chr(10), encoding="utf-8"); fire(small)
    rows = {json.loads(l)["path"]: json.loads(l) for l in (board / "reads.jsonl").read_text(encoding="utf-8").splitlines()}
    R = lambda n: rows[str((tmp / n).resolve())]
    check(R("lines.md")["partial_why"] == "size" and R("bytes.md")["partial_why"] == "size"
          and not rows[str(small.resolve())]["partial"] and not R("l2000.md")["partial"],
          "offset / limit 無しでも、2000 行を超えるか 25,000 バイト超の文書は partial（理由 size。ちょうど 2000 行と小さい文書は全文）")
    got, why = RESEARCH_RULES.hook_evidence(board, str(tmp / "bytes.md"))
    check(got == "partial" and "切りうる大きさ" in why and "読み直しても変わらない" in why and "offset" not in why,
          f"大きさで倒した partial は、offset を付けたとは言わない（読み直しても変わらない。{why[:60]}）")
    # **大きさを申告しない物（FIFO）は開かない。** stat の大きさで上限を見てから読み切っていた頃は、
    # 書き手が流し続ける FIFO を丸ごと読んだ。書き手の居ない FIFO は開くだけで止まる
    if hasattr(os, "mkfifo"):
        import threading  # noqa: E402
        fifo = tmp / "pipe"
        os.mkfifo(fifo)

        def feed():
            # 書き手を 1 つ立てる（読み手が開けば数バイト流して閉じる）。開かなければ待ったまま——daemon なので
            # 台本の終わりを止めない。書き手が居るので、柵を外した写しでは開いて読み、記録に行が増える
            def w():
                with open(fifo, "wb") as f:
                    f.write(b"fifo-bytes")
            threading.Thread(target=w, daemon=True).start()
        n = len((board / "reads.jsonl").read_text(encoding="utf-8").splitlines())
        feed()
        check(fire(fifo) == 0 and len((board / "reads.jsonl").read_text(encoding="utf-8").splitlines()) == n,
              "FIFO を読んだ回はフックが記録しない（開かずに道具へ返す）")
        feed()
        got, why = RESEARCH_RULES.hook_evidence(board, str(fifo))
        check(got == "none" and "通常のファイルでない" in why, f"FIFO は開かずに none（{why[:50]}）")
    else:
        skip("FIFO を読んだ回はフックが記録しない", "この OS には FIFO（os.mkfifo）が無い")
        skip("FIFO は開かずに none", "この OS には FIFO（os.mkfifo）が無い")
    # **sha を持たない行（書いた側の上限超え）は大きさの部分読みとして扱い、一致の証拠にも不一致の証拠にもしない**——
    # 不一致と数えていた頃は、2 つの上限の写しがずれた日に、小さい文書が『読んだ後に変わった』と名乗られた
    nosha = tmp / "nosha.md"; nosha.write_text("n" + chr(10), encoding="utf-8")
    with open(board / "reads.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps({"ts": "t", "session_id": "s", "agent_id": None, "path": str(nosha.resolve()),
                            "file_sha": None, "bytes": 2, "partial": False, "tool_use_id": "x"}) + chr(10))
    got, why = RESEARCH_RULES.hook_evidence(board, str(nosha))
    check(got == "partial" and "切りうる大きさ" in why, f"sha を持たない行だけなら stale と名乗らず、大きさの partial（{got}: {why[:50]}）")
    # **sha の無い行と、今の sha と違う行が両方在るなら stale を名乗る**（読み直せば済む。none に倒すと理由が消える）
    with open(board / "reads.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps({"ts": "t", "session_id": "s", "agent_id": None, "path": str(nosha.resolve()),
                            "file_sha": "0" * 64, "bytes": 2, "partial": False, "tool_use_id": "y"}) + chr(10))
    got, why = RESEARCH_RULES.hook_evidence(board, str(nosha))
    check(got == "stale" and "一致しない" in why, f"sha の無い行と古い sha の行が両方なら stale（{got}: {why[:50]}）")
    # **呼び元が渡したバイト列にも上限を当てる**（読み終えたバイト列を渡す経路で、上限の外の物の sha を取らない）
    got, why = RESEARCH_RULES.hook_evidence(board, str(nosha), data=b"n" * (RESEARCH_RULES.READ_CAP + 1))
    check(got == "none" and "大きすぎて測らない" in why, f"渡されたバイト列が上限を超えれば none（{got}: {why[:50]}）")
    got, why = RESEARCH_RULES.hook_evidence(tmp / "no-board", str(nosha))
    check(got == "none" and "reads.jsonl が無い" in why, f"記録の無い置き場は none（{got}: {why[:50]}）")
    # **記録は 1 回の検査で 1 度だけ読む**（cache を渡した呼び元）。申告の数だけ記録を読み直していた頃は、
    # 行数に上限の無い記録を 1 行ごとに全部読んで解析した。渡した cache の中身が次の問いで使われることを見る
    fresh = tmp / "fresh.md"; fresh.write_text("fresh" + chr(10), encoding="utf-8")
    memo = {}
    first = RESEARCH_RULES.hook_evidence(board, str(fresh), cache=memo)[0]
    check(fire(fresh) == 0, "cache の後に記録へ 1 行足す")
    again = RESEARCH_RULES.hook_evidence(board, str(fresh), cache=memo)[0]
    now = RESEARCH_RULES.hook_evidence(board, str(fresh))[0]
    check(first == "absent" and again == "absent" and now == "read",
          f"cache を渡した呼び元は記録を読み直さない（1 度目 {first} / 同じ cache {again} / cache なし {now}）")
    # **記録に本文を写さない。** 文書の中身をこちらのディスクへ置く形にしない
    log = (board / "reads.jsonl").read_text(encoding="utf-8")
    # sha の 16 進は a〜f を含む（本文の "aaa" と偶然一致しうる）ので、sha の欄を落としてから探す
    bare = "\n".join(json.dumps({k: v for k, v in json.loads(l).items() if k != "file_sha"}, ensure_ascii=False) for l in log.splitlines())
    check("CHANGED" not in bare and "aaa" not in bare, "記録に文書の本文は入らない（sha と大きさだけ）")
    strays = sorted(x for x in (list(cfg.rglob("*")) + list((tmp / "home").rglob("*"))) if x.is_file())
    check(not strays, f"**run が在る回も、利用者ごとの置き場には 1 バイトも書かない**（{strays[:2]}）")
    rm(tmp)


def test_schema_pattern_properties():
    """型検査の patternProperties: 型で決めた名前の外は、名前の形に合うものだけを受ける（OpenAPI の x- 拡張と同じ口）"""
    print("型検査: patternProperties")
    from engine.schema import validate_schema, unknown_keywords  # noqa: E402
    s = {"type": "object", "additionalProperties": False, "properties": {"a": {"type": "integer"}},
         "patternProperties": {"^x_[a-z0-9_]+$": {"type": "number"}}}
    check(validate_schema({"a": 1, "x_n": 2.5}, s) == [], "patternProperties: 形に合う名前は受ける")
    check(any("知らない欄 'y'" in e for e in validate_schema({"y": 1}, s)), "patternProperties: 形に合わない名前は additionalProperties で拒む")
    check(any("x_n" in e for e in validate_schema({"x_n": "1"}, s)), "patternProperties: 形に合う名前も値の型は見る")
    check(unknown_keywords({"patternProperties": {"^x_": {"typo": 1}}}) != [], "patternProperties: 中の語も engine の読む語かを見る")


def test_schema_end_anchored():
    """型検査の pattern の `$` は ECMA-262 の意味（入力の末尾だけ）。エスケープした `\\$` と文字クラスの中の `$` は字のまま"""
    print("型検査: pattern の $ は末尾だけ")
    from engine.schema import end_anchored  # noqa: E402
    m = lambda pat, s: bool(end_anchored(pat).search(s))
    check(m("^a$", "a") and not m("^a$", "a\n"), "pattern: $ は末尾の改行の手前で一致しない（Python の $ と違う）")
    check(m("^a\\$$", "a$") and not m("^a\\$$", "a"), "pattern: \\$ はエスケープした字のまま（\\Z に読み替えない）")
    check(m("^[$]$", "$") and not m("^[$]$", "a"), "pattern: 文字クラスの中の $ は字のまま")
    check(m("^[ab$]$", "$"), "pattern: 文字クラスは ] まで続く（2 字目以降の後の $ もクラスの中）")
    check(m("^[]$]+$", "]$") and not m("^[]$]+$", "]$\n"), "pattern: [ の直後の ] は文字クラスの中の字で、その後の $ もクラスの中")
    check(m("^[a]$", "a") and not m("^[a]$", "a\n"), "pattern: 文字クラスを閉じた後の $ は末尾")
    # **クラスの閉じは位置で決める**（Python の re の文書: ] が字になるのは [ か [^ の直後だけ）。直前の 1 字で見ていたとき、
    # エスケープした \[ の直後の ] を字と読み、クラスを閉じ損ねて後ろの $ を素通しした
    check(m("^[\\[]a$", "[a") and not m("^[\\[]a$", "[a\n"), "pattern: エスケープした [ の直後の ] はクラスを閉じ、後ろの $ は末尾")
    check(m("^[^]$]$", "a") and not m("^[^]$]$", "$") and not m("^[^]$]$", "a\n"),
          "pattern: [^ の直後の ] はクラスの中の字（コンパイルでき、$ もクラスの中）")
    check(m("^[^]a]$", "b") and not m("^[^]a]$", "b\n"), "pattern: [^] の後のクラスを閉じた $ は末尾")


def test_schema_refs_fail_closed():
    """**展開されていない $ref は型検査が拒み、引ける綴りは docstring の名乗り（#/$defs/<名前> と engine#/<名前>）だけ。**
    知らない語として無視していたとき、未展開の {"$ref": …} は何でも合格にした。engine#/$defs/<名前> は演算子の優先順位で
    受け付けていた（読み手の読みが割れた）"""
    print("型検査: 未展開の $ref は拒み、引ける綴りは 2 つだけ")
    from engine.schema import validate_schema, expand_refs  # noqa: E402
    from engine.util import ENGINE_DEFS  # noqa: E402
    check(any("展開されていない" in e for e in validate_schema({"x": 1}, {"$ref": "#/$defs/a"})), "未展開の $ref は何でも通すのでなく拒む")
    name = sorted(ENGINE_DEFS)[0]
    ok = lambda ref: expand_refs({"$defs": {"a": {"type": "string"}}, "nodes": {"n": {"schema": {"$ref": ref}}}})
    check(ok(f"engine#/{name}")["nodes"]["n"]["schema"] == ENGINE_DEFS[name], "engine#/<名前> は引ける")
    check(ok("#/$defs/a")["nodes"]["n"]["schema"] == {"type": "string"}, "#/$defs/<名前> は引ける")
    # 3 つの綴りは、条件の項を 1 つ外すと別の表の鍵に当たる形を選ぶ（engine の表の $defs/・局所の表の名前・局所の $defs/ を外した頭 6 字）
    for bad in (f"engine#/$defs/{name}", "engine#/$defs/a", "#/a", "#/xxxxxxa", f"#/{name}", "other#/a"):
        try:
            ok(bad)
            got = "通った"
        except ValueError as e:
            got = str(e)
        check("引けない" in got, f"{bad} は名乗りの外なので拒む（{got[:40]}）")


def test_run_count():
    """数える問い（how）は欄で受け、argv は engine が決まった形で組む。腕は柵ごとに置き、拒否理由を**その柵に固有の語**で見る
    ——共通の一語で見ていた頃は、柵を 1 つ消しても別の拒否文に当たって緑のままだった（2026-09-23 の gate_efficacy）。"""
    print("数える問い: 欄から argv を組み、読めなかった問いを 0 件にしない")
    import engine.util as _u  # noqa: E402
    _td, tmp = parallel.workspace("gl-count-")
    (tmp / "a.txt").write_text("x1\nx2\ny\n", encoding="utf-8"); (tmp / "b.txt").write_text("x3\n", encoding="utf-8")
    (tmp / "d").mkdir(); (tmp / "d" / "c.txt").write_text("x4\n", encoding="utf-8")
    (tmp / ".gitignore").write_text("ignored.*\n", encoding="utf-8")
    for c in (["init", "-q"], ["add", "-A"], ["-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "x"]):
        subprocess.run(["git", *c], cwd=tmp, capture_output=True)
    (tmp / "untracked.txt").write_text("x9\n", encoding="utf-8"); (tmp / "ignored.txt").write_text("x8\n", encoding="utf-8")
    # 数える版は役の欄でなく engine の引数（rev）。表では書きやすさのため欄に書き、ここで引数へ移す
    rc = lambda h, **k: (_u.run_count({x: v for x, v in h.items() if x != "rev"}, str(tmp), rev=h.get("rev"), **k)
                         if isinstance(h, dict) else _u.run_count(h, str(tmp), **k))
    H = lambda **k: {"patterns": ["x"], "paths": ["a.txt"], "count": "lines", **k}
    for label, how, want in (("数える: 一致した行の数", H(), 2), ("数える: パスと語を複数", H(patterns=["x1", "x3"], paths=["a.txt", "b.txt"]), 2),
                             ("数える: 一致したファイルの本数", H(paths=["."], count="files"), 3), ("数える: リポジトリ全体", H(paths=["."]), 4),
                             ("数える: 版を指定", H(rev="HEAD"), 2), ("数える: 版を指定してファイルの本数", H(rev="HEAD", paths=["."], count="files"), 3),
                             ("数える: 未追跡も数える", H(untracked=True, paths=["untracked.txt"]), 1),
                             ("数える: 固定文字列の正規表現記号", H(patterns=["(x;"], fixed=True), 0), ("数える: 固定文字列の #", H(patterns=["issue#12"], fixed=True), 0),
                             ("数える: 一致なしは 0", H(patterns=["nothing"]), 0), ("数える: 大文字小文字を無視", H(patterns=["X"], ignore_case=True), 2),
                             ("数える: 語の単位", H(word=True), 0), ("数える: - で始まる検索語は語のまま", H(patterns=["--output=c.txt"]), 0),
                             ("数える: 版を渡せば未追跡の旗は落とす", H(rev="HEAD", untracked=True), 2)):
        got = rc(how)
        check(got == (want, ""), f"{label} → {want}（{got}）")
    for label, bad, why in (("走らせない: 1 行のコマンド", "git grep -c x -- a.txt", "欄（patterns"), ("走らせない: 知らない欄", H(argv=["rm"]), "知らない欄"),
                            ("走らせない: 空の検索語の配列", H(patterns=[]), "how.patterns: 要素が 1 個未満"), ("走らせない: 改行を含む検索語", H(patterns=["x\ny"]), "how.patterns[0]: 形が合わない"),
                            ("走らせない: CR を含む検索語", H(patterns=["x\ry"]), "how.patterns[0]: 形が合わない"),
                            ("走らせない: NUL を含むパス", H(paths=["a\x00b"]), "how.paths[0]: 形が合わない"),
                            ("走らせない: パスの欠落", {"patterns": ["x"], "count": "lines"}, "必須の欄 'paths' が無い"),
                            ("走らせない: 数え方", H(count="wc"), "how.count: 値 'wc' が語彙"), ("走らせない: 真偽値でない旗", H(fixed="yes"), "how.fixed: 型が boolean でない"),
                            ("走らせない: - で始まる版", H(rev="--output=c.txt"), "数える版は版の名前"), ("走らせない: 空白を含む版", H(rev="HEAD x"), "数える版は版の名前"),
                            ("走らせない: 解決できない版", H(rev="no-such-rev"), "版として解決できない"),
                            ("走らせない: 当たらないパス", H(paths=["nope/"]), "'nope/' が数える世界（追跡中のファイル）"),
                            ("走らせない: 未追跡を旗なしで", H(paths=["untracked.txt"]), "'untracked.txt' が数える世界"),
                            ("走らせない: .gitignore に当たる未追跡", H(untracked=True, paths=["ignored.txt"]), "'ignored.txt' が数える世界"),
                            ("走らせない: リポジトリの外", H(paths=["/etc/passwd"]), "'/etc/passwd' を確かめられない"),
                            ("走らせない: 親ディレクトリ", H(paths=["../a.txt"]), "'../a.txt' を確かめられない"),
                            ("走らせない: .git の中", H(paths=[".git/config"]), "'.git/config' が数える世界"),
                            ("走らせない: 版に無いパス", H(rev="HEAD", paths=["untracked.txt"]), "版 HEAD"),
                            ("走らせない: - で始まるパスは pathspec のまま", H(paths=["--output=c.txt"]), "が数える世界"),
                            ("走らせない: 壊れた正規表現", H(patterns=["(x"]), "標準エラーに書いた")):
        got = rc(bad)
        check(got[0] is None and why in got[1], f"{label}（{got[1][:70]}）")
    got = _u.run_count(H(rev="HEAD"), str(tmp))
    check(got[0] is None and "知らない欄" in got[1], f"走らせない: 問いに版を書く（数える版は engine が決める。{got[1][:60]}）")
    argv, _ = _u.count_argv(H(patterns=["a", "b"], paths=["p", "q"], fixed=True, ignore_case=True, word=True, count="files"), "HEAD")
    check(argv == ["git", "grep", "-I", "--no-color", "-l", "-F", "-i", "-w", "-e", "a", "-e", "b", "HEAD", "--", "p", "q"],
          f"argv は決まった形（旗・語ごとの -e・版・-- の後ろにパス。{argv}）")
    # **読めなかった問いを 0 件にしない**——git grep が黙って非 0 を返す・時間切れ・上限超えは実物で作れないので、走らせる口を差し替えて撃つ
    _rcp = _u._run_capped
    try:
        _u._run_capped = lambda argv, *a: (2, b"", "", False, False) if "-c" in argv else _rcp(argv, *a)
        got = rc(H())
        _u._run_capped = lambda argv, *a: (1, b"", "", False, False) if "-c" in argv else _rcp(argv, *a)
        got1 = rc(H())
        _u._run_capped = lambda argv, *a: (0, b"", "", False, True) if "-c" in argv else _rcp(argv, *a)
        late = rc(H())
        _u._run_capped = lambda argv, *a: (0, b"", "", True, False) if "-c" in argv else _rcp(argv, *a)
        over = rc(H())
        _u._run_capped = lambda argv, *a: (0, b"a.txt:3", "warning: 一部を読めなかった", False, False) if "-c" in argv else _rcp(argv, *a)
        warned = rc(H())
    finally:
        _u._run_capped = _rcp
    check(got[0] is None and "exit 2" in got[1], f"走らせない: 黙った非 0（{got}）")
    check(got1 == (0, ""), f"数える: exit 1（標準エラー無し）は 0 件（{got1}）")
    check(late[0] is None and "秒で終わらない" in late[1], f"走らせない: 時間切れ（{late}）")
    check(over[0] is None and "上限" in over[1], f"走らせない: 出力の上限超え（{over}）")
    check(warned[0] is None and "標準エラーに書いた" in warned[1], f"走らせない: 終了コード 0 でも標準エラーに書いた（{warned}）")
    r = _u._run_capped([sys.executable, "-c", "import time; time.sleep(30)"], str(tmp), 1, 100)
    check(r[4] is True, f"時間切れの子は殺して late を返す（{r[:1]} / late={r[4]}）")
    r = _u._run_capped(["cat", "--", "a.txt"], str(tmp), 10, 3)
    check(r[3] is True, f"上限を超える出力は読み切らずに over を返す（{r[3]}）")
    # **engine の標準入力を子に継がせない**——閉じない管を標準入力にした子のプロセスで、ファイルを持たない cat を起こし、
    # 時間切れより前に返ることを見る
    code = (f"import sys; sys.path.insert(0, {str(PLUGIN)!r}); import engine.util as u; "
            f"print(u._run_capped(['cat'], {str(tmp)!r}, 3, 100)[4])")
    p = subprocess.Popen([sys.executable, "-c", code], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, encoding="utf-8")
    try:
        out = p.stdout.read(); p.wait(timeout=20)
    finally:
        p.stdin.close()
    check(out.strip() == "False", f"標準入力は DEVNULL（閉じない管を渡しても、読みに行かずに返る。late={out.strip()!r}）")
    check(_u.sum_counts("a:1" + chr(10) + "b:2") == 3 and _u.sum_counts("a:1" + chr(10) + "本文 b") is None,
          "`…:数` の合計は、数でない行が 1 行でも在れば None（黙って飛ばさない）")
    check((tmp / "a.txt").is_file() and not (tmp / "c.txt").exists() and not (tmp / "--output=c.txt").exists(),
          "拒んだ問いも数えた問いも、何も消さず何も書かない")
    rm(tmp)


def test_hook_evidence_passes_gate_without_transcript():
    """**フックの記録が在る回は、転写を 1 本も開かずに柵が通る。**

    hook_evidence を単体で測るだけでは、柵に繋がっているかは分からない——繋ぎを落としても
    単体の検査は緑のままになる。ここは主経路（loop.py done）を実際に打ち、
    **転写が存在しない環境**で通ることで「転写を見ていない」を示す。

    実走 2026-09-22: 転写 0 本・フックの記録 1 行で done が exit 0・0.05 秒。
    """
    print("読了の柵（フック）: 記録が在れば転写を開かずに通る（転写 0 本の環境で主経路を打つ）")
    _td, tmp = parallel.workspace("gl-hookgate-")
    doc = tmp / "doc.md"
    doc.write_text("".join(f"{i:02d} 行目: この文書のためだけの一意の一文である。" + chr(10)
                           for i in range(30)), encoding="utf-8")
    repo = tmp / "repo"; repo.mkdir()

    def g(*a):
        subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t", *a],
                       cwd=repo, check=True, capture_output=True, timeout=120)
    g("init", "-q"); (repo / "f.txt").write_text("a" + chr(10), encoding="utf-8")
    g("add", "-A"); g("commit", "-q", "-m", "base")
    cfg = tmp / "cfg"                          # **転写は 1 本も置かない**
    env = {**os.environ, "CLAUDE_CONFIG_DIR": str(cfg), "CLAUDE_CODE_SESSION_ID": "gate-t"}

    def loop(*a):
        return subprocess.run([PY, str(PLUGIN / "scripts" / "loop.py"), *a], cwd=repo,
                              capture_output=True, text=True, encoding="utf-8", env=env, timeout=600)

    loop("init", "--loop", "research-loop", "--request", "x", "--document", str(doc), "--unattended")
    d = pathlib.Path(json.loads(loop("status").stdout)["dir"])
    loop("next")
    (d / "out" / "r1").mkdir(parents=True, exist_ok=True)
    (d / "out" / "r1" / "p0.question.json").write_text(json.dumps(
        {"question": "q", "domain": "d", "thickness": "標準", "thickness_decider": "既定",
         "thickness_reason": "既定のまま",
         "constraints": [{"text": "t", "source": "s", "origin": "surveyor自書", "breaks_if_false": "b"}]},
        ensure_ascii=False), encoding="utf-8")
    loop("done", "--node", "p0.question"); loop("next")
    (d / "out" / "r1" / "p0.claims.json").write_text(json.dumps(
        {"claims": [{"id": "A1", "claim": "c", "load_bearing": True}],
         "judgments": [], "judgments_as_facts": [], "open_questions": []}, ensure_ascii=False), encoding="utf-8")

    r = loop("done", "--node", "p0.claims")
    check(r.returncode == 0 and "確かめられなかった" in r.stdout,
          "フックの記録が無ければ、転写も無いので**不成立**（柵を切らず痕跡を残す）")

    # **run が在るので、フックは盤面の隣へ書く**（cwd がリポジトリなら current から辿れる）
    subprocess.run([PY, str(PLUGIN / "hooks" / "record-read.py")], timeout=60,
                   input=json.dumps({"hook_event_name": "PostToolUse", "session_id": "gate-t",
                                     "tool_name": "Read", "tool_use_id": "toolu_g", "cwd": str(repo),
                                     "tool_input": {"file_path": str(doc)},
                                     "tool_response": {"type": "text", "file": {"filePath": str(doc)}}}),
                   capture_output=True, text=True, encoding="utf-8")
    check((d / "reads.jsonl").is_file(), "記録は盤面の隣に落ちる（利用者ごとの置き場に溜めない）")
    loop("next")
    (d / "out" / "r1" / "p0.terms.json").write_text(json.dumps(
        {"terms": [{"term": "t", "definition": "d", "status": "社内造語"}]}, ensure_ascii=False), encoding="utf-8")
    r2 = loop("done", "--node", "p0.terms")
    check(r2.returncode == 0 and "確かめられなかった" not in r2.stdout,
          f"**フックの記録が在れば、転写 0 本でも通る**（{r2.stdout.strip()[-60:]}）")
    rm(tmp)


def test_graphcheck():
    print("graphcheck: 正しい graph は通り、壊した graph は腕ごとに NG の診断文を出して落ちる（例外で死なない）")
    g = json.loads((PLUGIN / "graphs" / "research-loop.json").read_text(encoding="utf-8"))
    r = subprocess.run([PY, str(GRAPHCHECK), str(PLUGIN / "graphs" / "research-loop.json"), str(VALIDATOR)], capture_output=True, text=True, encoding="utf-8", timeout=600)
    check(r.returncode == 0, "research-loop.json は通る")
    _td_tmp, tmp = parallel.workspace("gl-gc-")
    (tmp / "graphs").mkdir()
    shutil.copytree(PLUGIN / "prompts", tmp / "prompts")
    shutil.copytree(PLUGIN / "rules", tmp / "rules")
    # 読む欄の宣言を壊した条件の関数を、写しの rules にだけ足す（graph の cond がその名前を指したときに graphcheck が落とすか）
    bad_conds = {"bad_field": ("out.p1.checker.findingz",), "bad_prev": ("prev.p1.checker.findingz",), "bad_loop": ("loop.stuck_hintz",),
                 "bad_record": ("record.constraintz",), "bad_head": ("rounds",), "bad_rd": ("rd.new_discrepanciez",),
                 "bad_order": ("out.p3.cartographer",), "bad_under": ("round.x",)}
    with open(tmp / "rules" / "research-loop.py", "a", encoding="utf-8") as f:
        f.write("\n\n")
        for name, reads in bad_conds.items():
            f.write(f"CONDS[{name!r}] = cond_reads(*{reads!r})(lambda v: (True, 'x'))\n")
        f.write("CONDS['no_reads'] = lambda v: (True, 'x')\n")
    with open(tmp / "rules" / "review-loop.py", "a", encoding="utf-8") as f:
        f.write("\n\nCONDS['bad_prev_fix'] = cond_reads('prev.p3.fix.changez')(lambda v: (True, 'x'))\n"
                "CONDS['bad_loop_key'] = cond_reads('loop.prev_fix_filez')(lambda v: (True, 'x'))\n"
                "CONDS['bad_record_sub'] = cond_reads('record.reviews.R2.stauts')(lambda v: (True, 'x'))\n")
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
    # **溜めた NG の出口は 1 つ。** exec を落とすと『実行の形の検査は省略』へ抜けるが、
    # そこまでに溜めた NG（inputs 宣言の欠けなど）は吐かれなければならない。吐かずに戻っていたとき、
    # 写しだけのグラフは宣言が欠けたまま ok で通った（実測 r10）——この腕は exec の有無を跨ぐので、
    # inputs の欠けだけを壊す腕（下）では踏めない
    # **旗で渡る入力（CLI_FLAGS）は宣言が要らない**ので、そこを壊しても赤くならない
    # ——最初 document を落として腕を書き、緑のまま通った（実測 r10）。旗でない cwd を落とす
    def _drop_input_decl(b):
        b["inputs"].pop("cwd", None)
    broken(_drop_input_decl, "graph の inputs に cwd の宣言が無い",
           "穴が読む入力の宣言が欠けた graph は落ちる")

    def _drop_input_decl_and_exec(b):
        _drop_input_decl(b)
        b.pop("exec", None)
    broken(_drop_input_decl_and_exec, "graph の inputs に cwd の宣言が無い",
           "exec が無くても、そこまでに溜めた NG は吐かれる（早い return で握り潰さない）")
    # **回す側の節に本文を貼る穴（file: / section:）**。graph の dict だけでは壊せない（穴はプロンプト側に在る）ので、
    # この関数の冒頭で tmp に写した prompts の隣へ腕ごとに 1 枚だけ別名で置き、その節の prompt_file を向け替える。
    # 条件は or の 2 腕なので file: だけ見ると片側しか赤を見ていない
    def paste_into_runner(b, hole, name):
        src = tmp / "prompts" / "research-loop" / "p0.claims.md"
        dst = tmp / "prompts" / "research-loop" / f"p0.claims.{name}.md"
        dst.write_text(src.read_text(encoding="utf-8") + "\n" + hole + "\n", encoding="utf-8")
        b["nodes"]["p0.claims"]["prompt_file"] = f"../prompts/research-loop/{dst.name}"
        # reads は接頭を剥がした形で照合される（render.allowed が strip_prefix を通す）——穴の綴りをそのまま足すと
        # 新しい柵に加えて『reads に無い』も同時に出て、腕が何を見ているのか読めなくなる
        b["nodes"]["p0.claims"]["reads"].append(strip_prefix(hole.strip("{} ")).split("#")[0])

    broken(lambda b: paste_into_runner(b, "{{file:inputs.document}}", "file"), "の節に書けない",
           "回す側の節に本文を貼る穴（file:）を持つ graph は落ちる")
    broken(lambda b: paste_into_runner(b, "{{section:inputs.document#見立て}}", "section"), "の節に書けない",
           "同じ柵の section: の腕も落ちる（or の両側）")
    # errs に溜める側の腕（以前は errs の束縛が後ろにあり UnboundLocalError で診断文が出なかった 8 経路）
    broken(lambda b: b.pop("runners"), "runners", "runners の無い graph は落ちる")
    broken(lambda b: b.__setitem__("agent_prefix", "x"), "agent_prefix", "廃止した agent_prefix を持つ graph は落ちる")
    broken(lambda b: b.__setitem__("plugin", "no-such-plugin"), "役割 agent の定義", "役の定義が見つからない plugin を指す graph は落ちる")
    broken(lambda b: b.pop("launch"), "launch.isolated.argv", "道具ゼロの役を使うのに起こし方を宣言しない graph は落ちる")
    # 前置（via）は起こした瞬間にしか落ちない——python が「そんなファイルは無い」で止まり、返答が空のまま done が拒む
    broken(lambda b: b["launch"]["isolated"].__setitem__("via", ["{python}", "{plugin_root}/scripts/no-such.py"]),
           "同梱されていない", "via が同梱していない実体を指す graph は落ちる（実行時にしか出ない落ち方を静的に見る）")
    broken(lambda b: b["launch"]["isolated"].__setitem__("via", "scripts/with-auth.py"), "文字列の配列", "via が配列でない graph は落ちる")
    # skills の要素は object。名前を独立の欄にしておかないと、宣言と返答の
    # 突合に誰も決めていない正規化規則が要る（実測 2026-09-15: 宣言『/simplify（指摘だけ）』に対し返答の綴りが 4 本に分裂した）
    def skills(v):
        return lambda b: b["nodes"]["p1.refuter"].__setitem__("skills", v)
    broken(skills(["pr-review-toolkit:code-reviewer"]), "object", "skills の要素が散文 1 本の graph は落ちる")
    broken(skills([]), "空でない配列", "skills が空配列の graph は落ちる")
    broken(skills([{"skill": "a"}, {"skill": "a"}]), "2 回", "同じ skill を 2 回宣言する graph は落ちる（1 本につき 1 行を数えられない）")
    broken(skills([{"skill": "a", "effort": "high"}]), "知らない欄", "skills に知らない欄がある graph は落ちる")
    broken(skills([{"skill": "  a"}]), "前後に空白", "skill 名の前後に空白がある graph は落ちる（照合の両側が同じ文字列でなくなる）")
    broken(skills([{"skill": "a", "required": "yes"}]), "真偽値", "required が真偽値でない graph は落ちる")
    broken(skills([{"args": "high"}]), "skill（名前）が無い", "名前の欄が無い skills の graph は落ちる")
    # reads は「貼ってよい物の許可表」であって配り口ではない。穴が無ければ役に届かないので、
    # 宣言だけ在る欄は静的に落とす（実測 2026-09-16: 届いていない reads が 6 件在り、そのうち
    # prev.r1.minimality に「逐語で写せ」と課す柵を足したせいで 2 周目の P2 が永久に通らなくなるところだった）
    broken(lambda b: b["nodes"]["p1.refuter"]["reads"].append("round"), "使う穴が prompt_file に無い",
           "宣言だけ在って穴がどのプロンプトにも無い reads を持つ graph は落ちる")
    broken(lambda b: b["nodes"]["p1.checker"]["schema"].__setitem__("oneOf", []), "engine が読まない語", "schema に engine が読まない語（oneOf）を書いた graph は落ちる（書いても効かない語を黙って通さない）")
    # engine が実行に使う欄の綴り違い（文書欄 outputs の照合は通っても、実行では黙って素通りしていた）
    broken(lambda b: b["nodes"]["p1.checker"]["writes"][0].__setitem__("from", "findingz"), "writes.from", "writes.from が schema に無い欄を指す graph は落ちる（記録に着地しない）")
    # 条件は rules の関数の名前だけ。関数が宣言した読む欄を、graphcheck が実行の前に照らす（以前の JSON の条件の検査は
    # out.・prev. の葉しか見ず、loop.・record. の葉の綴り違いは回すまで分からなかった）
    for name, want, desc in (
            ("bad_field", "schema に無い", "条件が節の schema に無い欄を読むと宣言した graph は落ちる"),
            ("bad_prev", "schema に無い", "条件が prev.<節>.<欄> で欄を綴り違えた graph は落ちる"),
            ("bad_loop", "LOOP_KEYS に無い", "条件が rules の LOOP_KEYS に無い loop の鍵を読む graph は落ちる"),
            ("bad_record", "を書く宣言が無い", "条件が記録に無い欄を読む graph は落ちる"),
            ("bad_head", "頭が条件の文脈に無い", "条件の読む欄の頭が文脈に無い graph は落ちる"),
            ("bad_rd", "周の鍵", "条件が周の鍵に無い rd.<鍵> を読む graph は落ちる"),
            ("bad_order", "前（deps の推移閉包）に無い", "条件が自分より後の節の今の出力を読む graph は落ちる"),
            ("bad_under", "値そのもの", "round の下の欄を読む graph は落ちる"),
            ("no_reads", "宣言していない", "読む欄を宣言していない条件を指す graph は落ちる")):
        broken(lambda b, name=name: b["nodes"]["p1.refuter"].__setitem__("cond", name), want, desc)
    broken(lambda b: b["nodes"]["p1.refuter"].__setitem__("cond", {"path": "round", "op": "eq", "value": 1}), "CONDS の名前でない",
           "条件を JSON の式で書いた graph は落ちる（graph には関数の名前だけ）")
    broken(lambda b: b["nodes"]["p1.refuter"].__setitem__("cond", "no_such"), "CONDS の名前でない", "rules に無い条件の名前を指す graph は落ちる")
    broken(lambda b: b["record"].__setitem__("report_accepts_exit", ["0"]), "report_accepts_exit", "report_accepts_exit に整数でない値を書いた graph は落ちる")
    # 同じ context を継ぐ節: 役が一致し、遮断系でないこと（review graph で見る）
    rg = json.loads((PLUGIN / "graphs" / "review-loop.json").read_text(encoding="utf-8"))
    rv = str(PLUGIN.parent / "scripts" / "review-record.py")
    for i, (mut, want, desc) in enumerate((
            (lambda b: b["nodes"]["p2.history"].__setitem__("run_by", "inspector"), "役が違う", "same_context_as の役と自分の役が違う graph は落ちる"),
            (lambda b: (b["nodes"]["p2.history"].__setitem__("run_by", "blind-judge"), b["nodes"]["p2.diagnose"].__setitem__("run_by", "blind-judge")), "遮断系", "遮断系の役に same_context_as を書いた graph は落ちる（実行時の die を静的にも見る）"),
            # 条件の読む欄は out. だけでなく prev.<節>.<欄> も節の schema と、loop.<鍵> も rules の LOOP_KEYS と突き合わせる
            (lambda b: b["nodes"]["p1.external_standards"].__setitem__("cond", "bad_prev_fix"), "schema に無い", "条件が prev.<節>.<欄> で欄を綴り違えた graph は落ちる（再発火条件が恒偽のまま通らない）"),
            (lambda b: b["nodes"]["p1.external_standards"].__setitem__("cond", "bad_loop_key"), "LOOP_KEYS に無い", "条件が loop の鍵を綴り違えた graph は落ちる（以前は検査の外で、default の値に化けた）"),
            (lambda b: b["nodes"]["p1.gate_efficacy"].__setitem__("applies_cond", "bad_loop_key"), "LOOP_KEYS に無い", "applies_cond の関数の読む欄も同じく照らす"),
            (lambda b: b["nodes"]["p2.diagnose"]["reads"].append("loop.escalatedd"), "LOOP_KEYS に無い", "節の reads の loop.<鍵> の綴り違いも同じ宣言で落ちる（穴は ABSENT で黙って埋まる）"),
            (lambda b: b["nodes"]["stop.premise_check"].__setitem__("cond", "bad_record_sub"), "を書く宣言が無い", "記録の writes.to の下の欄の綴り違い（pick に無い）は落ちる"),
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
    check(r.returncode == 1 and "遮断が崩れる" in r.stdout,
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
    _td_tmp, tmp = parallel.workspace("gl-bb-")
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
        nx = subprocess.run([PY, str(LOOP), "next", "--dir", str(d2)], cwd=run.repo, capture_output=True, text=True, encoding="utf-8", env=run.env, timeout=600)
        seen += nx.stderr
        if nx.returncode != 0 or not nx.stdout.strip():
            break
        out = json.loads(nx.stdout)
        if not out["ready"]:
            break
        answers = base_answers(run, "std")
        for inst in out["ready"]:
            o = answers[inst["node"]](load_item(inst), out["round"])
            f = run.tmp / "o.json"
            f.write_text(json.dumps(o, ensure_ascii=False) if not isinstance(o, str) else o, encoding="utf-8")
            subprocess.run([PY, str(LOOP), "done", "--node", inst["id"], "--output", str(f), "--dir", str(d2)], env=run.env,
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
    check(validate_schema("xxx", {"type": "string", "maxLength": 2}), "maxLength: 上限を超えた字列は落とす")
    check(not validate_schema("xx", {"type": "string", "maxLength": 2}), "maxLength: ちょうどは通る")
    check(validate_schema(" x ", {"type": "string", "maxLength": 2}), "maxLength: 前後の空白も数える（削って測らない）")


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
    _td_tmp, tmp = parallel.workspace("gl-dir-")
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
    # **上限でも諮る（review 側と同じ形）。** 以前は `stop` に倒して直前に組み立てた asks を捨てていたので、
    # 依頼者が「続けろ」と答える受け口が無かった。無人実行はその ask を保守的に停止へ畳むので、
    # 停止理由は「暴走ガード」でなく「諮るべき事態（…max_rounds…）」になる——**何を聞かれたかが残る側**
    sr = rec["convergence"]["stopped_reason"]
    check(last["status"] == "stopped" and "max_rounds" in sr, f"cold_reader が pass しないまま上限で stopped（{sr[:40]}）")
    hi = rec["process"]["human_items"]
    check(hi and "max_rounds" in (hi[-1].get("kinds") or []), f"何を聞かれて止まったかが記録に残る（{hi[-1].get('kinds') if hi else None}）")
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
    check(bool(ag), f"道具を持つ役は cli でなく agent の mode で出る（起こし方は test_research_tooled_launch）（{sorted({i['node'] for i in ag})}）")
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



def test_research_tooled_launch():
    """道具つきの役（investigator・inspector・judge）も engine が起こすこと（graph の launch.tooled）。

    宣言が無いと launch_spec は黙って None を返し、節は Agent ツールの経路に落ちる——research-loop だけが
    その形で取り残されていた（2026-09-25）。旗は argv から直に読む: 柵の launch_refusal は claude が PATH に
    無い場（CI）で必ず『claude が無い』を返すので、ここで当てると CI でだけ赤になる（柵の腕は test_tooled_launch_fence）。
    """
    from engine.role_run import tooled_permission
    from engine.validator import agent_def
    print("道具つきの役も engine が起こす: 標準の筋書きで出る役の節は全部 launch を持ち、道具つきの役は tooled の形")
    seen = []

    def watch(run, inst, out):
        seen.append(inst)
        return out

    run = Run("tooled")
    drive(run, "std", hook=watch)
    ag = [i for i in seen if i["mode"] == "agent"]
    check(not [i["node"] for i in ag if not i.get("launch")],
          f"役の節は全部 engine が起こす——Agent ツールの経路に落ちる節が無い（{sorted({i['node'] for i in ag if not i.get('launch')})}）")
    roles = sorted({i["agent_type"] for i in ag})
    check(roles == ["convergence-loops:inspector", "convergence-loops:investigator", "convergence-loops:judge"],
          f"道具つきの 3 役が標準の筋書きに出る（{roles}）")
    for role in roles:
        inst = next(i for i in ag if i["agent_type"] == role)
        L = inst.get("launch") or {}
        argv = L.get("argv") or []

        def after(flag):
            return argv[argv.index(flag) + 1] if flag in argv and argv.index(flag) + 1 < len(argv) else None

        tools = agent_def(role)["tools"]
        perm = tooled_permission(tools)
        # 形（sandbox / read_only）は起こす環境で決まるので、ここでは Bash を持つかどうかで分かれることだけを見る
        forms = ("sandbox", "read_only") if "Bash" in tools else ("plain",)
        check(L.get("kind") == "tooled" and after("--tools") == ",".join(tools) and after("--allowedTools") == ",".join(perm["allowed_tools"])
              and after("--permission-mode") == perm["permission_mode"] and after("--permission-prompts") == "none"
              and after("--setting-sources") == "" and L.get("form") in forms and (after("--settings") == "{}") == (L.get("form") != "sandbox")
              and "--agents" not in argv and L.get("stdin") == inst["prompt_file"],
              f"{inst['node']}（{role}）は tooled の形: 定義の道具・engine が決めた権限と設定・聞く先無し・設定を読まない・材料は stdin（{L.get('form')} {argv[2:]}）")
    rm(run.tmp)
    # 起こす語は review-loop の graph と同じ（理由の正本は review-loop の why。語がずれたら片方だけが古い）
    here = json.loads((PLUGIN / "graphs" / "research-loop.json").read_text(encoding="utf-8"))["launch"]
    there = json.loads((PLUGIN / "graphs" / "review-loop.json").read_text(encoding="utf-8"))["launch"]
    for kind in ("isolated", "tooled"):
        for k in ("argv", "resume", "via"):
            check(here.get(kind, {}).get(k) == there.get(kind, {}).get(k), f"launch.{kind}.{k} は review-loop の graph と同じ語")


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
    fake = fakeclaude.install(bindir)
    env = {**os.environ, "PATH": str(bindir) + os.pathsep + os.environ.get("PATH", ""), "FAKE_MODE": "seen"}
    argv = list(inst["launch"]["argv"])
    # **差し替えるのは claude の 1 語だけ。** argv[0] を偽物にしていたとき、前置（launch.isolated.via の
    # with-auth）を丸ごと飛び越えて起こしていて、層が在ろうと無かろうとこの腕は緑だった（2026-09-15 に
    # 前置を足した周で発覚）。engine は next の時点で PATH から解決済みなので、解決後の綴りで名指しする。
    target = shutil.which("claude") or "claude"
    check(target in argv, f"engine が組んだ argv に起こす対象が 1 語で在る（{target}）")
    argv[argv.index(target)] = str(fake)
    with open(inst["launch"]["stdin"], "rb") as fh:
        r = subprocess.run(argv, stdin=fh, capture_output=True, text=True, encoding="utf-8", env=env, timeout=600)
    check(r.returncode == 0, f"argv どおりに起こせて exit 0（{r.returncode}: {r.stderr[:120]}）")
    check("with-auth: auth=" in r.stderr, f"前置の層を通って起きている（標準エラーに 1 行。{r.stderr[:80]!r}）")
    check(r.stdout.strip().startswith("{"), "層の語が標準出力に混ざらない（out_path に落とすのは子の返答だけ）")
    got = json.loads(json.loads(r.stdout)["result"])  # --output-format json の包みの本文
    want = len(pathlib.Path(inst["launch"]["stdin"]).read_bytes())
    check(got["seen_bytes"] == want, f"標準入力が欠けずに届く（届いた {got['seen_bytes']} / 渡した {want} バイト）")
    check("--setting-sources" in got["argv"] and got["argv"][got["argv"].index("--setting-sources") + 1] == "",
          "起こされた側の argv にも遮断のフラグが入っている（形だけでなく実際に渡っている）")

    # 実物の失敗形: 非 0 終了と短い非 JSON（1 周目の認証落ちがこの形だった）
    fake = _fake_claude(bindir, "import sys\nsys.stdin.buffer.read()\nsys.stdout.write('Invalid API key\\n')\nsys.exit(1)\n")
    with open(inst["launch"]["stdin"], "rb") as fh:
        r = subprocess.run(argv, stdin=fh, capture_output=True, text=True, encoding="utf-8", env=env, timeout=600)
    check(r.returncode != 0 and "Invalid API key" in r.stdout, f"失敗形（非 0・短い非 JSON）を観測できる（rc={r.returncode}）")
    check("rc=1" in r.stderr, f"前置の層が非 0 を見て、どの段で起こしたかを添える（{r.stderr[-90:]!r}）")
    out = run.tmp / "bad.json"
    out.write_text(r.stdout, encoding="utf-8")
    d = run.cmd("done", "--node", inst["id"], "--output", str(out))
    check(d.returncode == 1 and "JSON" in d.stderr, f"その返答を done に渡すと exit 1 で拒まれる（{d.returncode}: {d.stderr[-90:]}）")
    rm(run.tmp)


def _load_claude_auth():
    """scripts/claude_auth.py（認証の段。プラグインに写して配る共有の本文）をパスから読み込む。"""
    import importlib.util
    spec = importlib.util.spec_from_file_location("claude_auth_under_test", PLUGIN / "scripts" / "claude_auth.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_with_auth():
    """遮断系を起こす前に**認証だけ**を足す層（launch.isolated.via）。

    子は対話の claude の認証を継がない（実測 2026-09-12: 『Failed to authenticate』の 1 行 73 バイトが返り、
    done が非 JSON として拒んだ）。段は 3 つで、**Keychain は mac だけの追加段**——この腕の半分は
    「Keychain の無い環境で何も壊さない」側を見る（gates の同じ分岐には腕が 1 本も無く、3 OS の CI でも
    一度も踏まれていなかった。写すときに腕ごと足す）。
    """
    print("認証の層: 段の選び方と、Keychain の無い環境での素通し")
    wa = _load_claude_auth()
    calls = []

    def runner(out="", boom=None):
        def run(argv, **kw):
            calls.append(argv)
            if boom:
                raise boom
            return types.SimpleNamespace(stdout=out, returncode=0)
        return run

    mac = dict(platform="darwin")
    # 1. 親の環境に認証が在れば触らない——**足す側に倒すと、利用者が選んだ経路を黙って別の口に差し替える**
    for k in ("CLAUDE_CODE_OAUTH_TOKEN", "ANTHROPIC_API_KEY", "CLAUDE_CODE_USE_BEDROCK"):
        calls.clear()
        env, note = wa.auth_env({k: "x", "CLAUDE_CONFIG_DIR": "/tmp/.claude-p1"}, runner=runner("sk-ant-oat01-kc"), **mac)
        check(note == f"inherited({k})" and not calls, f"親の {k} が在れば Keychain を引かない（{note}、引いた回数 {len(calls)}）")
    # 2. mac 以外は Keychain を引かない（security が無い環境でここを通ると毎回 1 プロセス無駄に起こす）
    calls.clear()
    env, note = wa.auth_env({"CLAUDE_CONFIG_DIR": "/tmp/.claude-p1"}, platform="linux", runner=runner("sk-ant-oat01-kc"))
    check(note == "none" and not calls, f"mac 以外は Keychain を引かない（{note}、引いた回数 {len(calls)}）")
    check(env["CLAUDE_CONFIG_DIR"] == "/tmp/.claude-p1" and "CLAUDE_CODE_OAUTH_TOKEN" not in env,
          "それでも CLAUDE_CONFIG_DIR は子に渡る（mac 以外はこの段だけが効く）")
    # 3. mac で取れたら渡す。サービス名は CLAUDE_CONFIG_DIR から導く（プロファイルごとに別項目）
    for cfg, svc in (("/x/.claude", "claude-code-oauth-default"), ("/x/.claude-p1", "claude-code-oauth-p1"), ("/x/.claude-p2", "claude-code-oauth-p2")):
        calls.clear()
        env, note = wa.auth_env({"CLAUDE_CONFIG_DIR": cfg}, runner=runner("sk-ant-oat01-kc"), **mac)
        check(env.get("CLAUDE_CODE_OAUTH_TOKEN") == "sk-ant-oat01-kc" and calls and svc in calls[0],
              f"{cfg} → {svc} から読んで子に渡す（{note}）")
    env, note = wa.auth_env({"CLAUDE_CONFIG_DIR": "/x/.claude-p1", "CLAUDE_KEYCHAIN_SERVICE": "共通の名前"},
                            runner=runner("sk-ant-oat01-kc"), **mac)
    check("共通の名前" in note, f"サービス名は共通の環境変数で上書きできる（{note}）")
    # 呼ぶ側は自分の環境変数（gates の COLDREAD_KEYCHAIN_SERVICE / graphloops の GL_KEYCHAIN_SERVICE）で
    # 上書きしたい——**共有の本文は呼ぶ側の綴りを知らない**ので、引数で受けて共通の名前より先に見る
    env, note = wa.auth_env({"CLAUDE_CONFIG_DIR": "/x/.claude-p1", "CLAUDE_KEYCHAIN_SERVICE": "共通の名前"},
                            runner=runner("sk-ant-oat01-kc"), service="呼ぶ側の名前", **mac)
    check("呼ぶ側の名前" in note, f"呼ぶ側の明示は共通の環境変数より先（{note}）")
    # 旗は値まで見る——`=0` は「使わない」の意味で、在るだけで認証が在ることにはならない
    calls.clear()
    env, note = wa.auth_env({"CLAUDE_CODE_USE_BEDROCK": "0", "CLAUDE_CONFIG_DIR": "/x/.claude"},
                            runner=runner("sk-ant-oat01-kc"), **mac)
    check(note.startswith("keychain(") and env.get("CLAUDE_CODE_OAUTH_TOKEN") == "sk-ant-oat01-kc",
          f"Bedrock / Vertex の旗が 0 なら「認証が在る」と読まない（{note}）")
    check("sk-ant-oat01-kc" not in note, "採った段の名前にトークンそのものは出ない（この 1 行は標準エラーに出す）")
    env, note = wa.auth_env({}, runner=runner("sk-ant-oat01-kc"), **mac)
    check(env["CLAUDE_CONFIG_DIR"].endswith(".claude") and "default" in note,
          f"CLAUDE_CONFIG_DIR 未設定なら既定を明示して子に渡す（{env['CLAUDE_CONFIG_DIR']}、{note}）")
    # 4. 取れない・壊れている・security が落ちる——**どれも例外にせず、足さずに進む**。
    #    ここで落とすと、子の保存済み認証で普通に動く場（mac 以外・別経路で認証済み）まで起こせなくなる
    for kind, run, want in (("空振り", runner(""), "keychain-miss"),
                            ("壊れた値", runner("junk"), "keychain-malformed"),
                            ("security が落ちる", runner(boom=OSError("no security")), "keychain-error")):
        env, note = wa.auth_env({"CLAUDE_CONFIG_DIR": "/x/.claude"}, runner=run, **mac)
        check(note.startswith(want) and "CLAUDE_CODE_OAUTH_TOKEN" not in env,
              f"Keychain が{kind}でも足さずに進む（{note}）")

    # 5. 実起動——層を通しても標準入力は欠けず、標準出力は子の返答だけ、終了コードはそのまま返る
    td, tmp = parallel.workspace("gl-withauth-")
    # **代役は `claude` の名前で置く。** 層は名前で起こす相手を縛っている（許可ルールを広げないため）ので、
    # 別名のスクリプトで検査すると、実物と違う枝（名前で撥ねる側）を通ってしまう
    bindir = tmp / "bin"
    bindir.mkdir()
    fake = _fake_claude(bindir,
                        "import os, sys\n"
                        "raw = sys.stdin.buffer.read()\n"
                        "sys.stdout.write('%d %s\\n' % (len(raw), os.environ.get('CLAUDE_CONFIG_DIR', '')))\n"
                        "sys.exit(int(sys.argv[1]))\n")
    cfg = str(tmp / ".claude-p9")
    # 親の認証は落として起こす。**在る機械と無い機械で結果が変わらない腕にする**——CI（mac 以外）でも
    # 手元（mac・Keychain 在り）でも、無い名前の項目を指せば「足さずに進む」側を通る
    env = {k: v for k, v in os.environ.items() if k not in wa.INHERITED}
    env.update({"CLAUDE_CONFIG_DIR": cfg, "GL_KEYCHAIN_SERVICE": "graphloops-test-no-such-service"})
    wrap = [PY, str(PLUGIN / "scripts" / "with-auth.py")]
    body = b"\xe6\x97\xa5\xe6\x9c\xac\xe8\xaa\x9e" * 1000  # 日本語のバイト列（Windows で text 読みだと壊れる形）
    r = subprocess.run(wrap + [str(fake), "0"], input=body, capture_output=True, env=env, timeout=600)
    out, err = r.stdout.decode("utf-8"), r.stderr.decode("utf-8")
    check(r.returncode == 0 and out.split()[0] == str(len(body)), f"標準入力が欠けずに子へ届く（{out.strip()[:40]}）")
    check(out.split()[1] == cfg, f"CLAUDE_CONFIG_DIR が子の環境に入る（{out.split()[1]}）")
    check(err.startswith("with-auth: auth=") and "sk-ant" not in err, f"採った段を標準エラーの 1 行目に出す（トークンは出さない。{err.strip()[:70]}）")
    # **認証落ちは rc では捕まらない**（実測 2026-09-15: 層無しの claude は『Failed to authenticate…』を
    # 標準出力に・exit 0 で返した）。足せなかった回だけ、起こす前に言う
    check("終了コード 0 のまま" in err, f"認証を足せなかった回は、静かな落ち方の注意が付く（{err.strip()[-60:]}）")
    r2 = subprocess.run(wrap + [str(fake), "0"], input=body, capture_output=True, timeout=600,
                        env={**env, "CLAUDE_CODE_OAUTH_TOKEN": "sk-ant-oat01-parent"})
    err2 = r2.stderr.decode("utf-8")
    check("inherited(" in err2 and "終了コード 0 のまま" not in err2 and "sk-ant" not in err2,
          f"認証が在る回は注意を付けない（毎回出すと読まれなくなる。{err2.strip()[:60]}）")
    r = subprocess.run(wrap + [str(fake), "3"], input=body, capture_output=True, env=env, timeout=600)
    check(r.returncode == 3 and "rc=3" in r.stderr.decode("utf-8"), f"子の終了コードをそのまま返し、落ちた理由の当たりを添える（{r.returncode}）")
    r = subprocess.run(wrap, capture_output=True, env=env, timeout=600)
    check(r.returncode == 2, f"コマンドを渡さなければ exit 2（{r.returncode}）")
    r = subprocess.run(wrap + [str(tmp / "nobin" / "claude")], capture_output=True, env=env, timeout=600)
    check(r.returncode == 127, f"起こせない（在りもしない）claude は exit 127 で、その旨を言う（{r.returncode}）")
    # **許可ルールを広げないための縛り。** 回す側の環境はこの層を名指しして許可することになるので、
    # 何でも exec できる層だと、その 1 本が「何でも起こしてよい」の意味になる
    r = subprocess.run(wrap + [PY, "-c", "print(1)"], capture_output=True, env=env, timeout=600)
    check(r.returncode == 2 and "専用" in r.stderr.decode("utf-8"),
          f"claude 以外は名前で撥ねる（{r.returncode}: {r.stderr.decode('utf-8').strip()[:60]}）")
    del td


def test_engine_launch():
    """遮断系は **engine が起こす**（`loop.py launch`）。回す側の Bash に子の claude を出さない。

    回す側が Bash から起こす形は、出力を out_path に落とす綴りだと auto mode の分類器が止める
    （実測 2026-09-15）。Agent ツールへ逃げると CLAUDE.md が注入されて遮断が名ばかりになる（実測 2026-09-12）。
    起こす場所を engine へ移すぶん、**何を起こすかは engine が機械で縛る**——この腕の後半はその柵。
    """
    from engine.commands import launch_prefix, launch_refusal  # 起こしてよい形は engine が正本
    print("engine 起動: 遮断系を loop.py launch で起こし、受け付けまで済ませ、起こしてよい形を柵で縛る")
    run = Run("englaunch")
    run.next()
    run.done("p0.question", base_answers(run, "std")["p0.question"](None, 1))
    bindir = run.tmp / "fakebin"
    bindir.mkdir()
    fake = fakeclaude.install(bindir)
    # engine と代役の標準出力を Windows のパイプの既定（ANSI コードページ）に強いる（test_role_run と同じ理由）
    env = {**os.environ, "PATH": str(bindir) + os.pathsep + os.environ.get("PATH", ""), "PYTHONIOENCODING": "cp1252"}
    nx = json.loads(run.cmd("next", env=env).stdout)
    cli = [i for i in nx["ready"] if i.get("mode") == "cli"]
    check(bool(cli), f"遮断系が cli で出る（{[i['node'] for i in cli]}）")
    inst = cli[0] if cli else {}
    ans = run.tmp / "answer.json"
    ans.write_text(json.dumps(base_answers(run, "std")[inst["node"]](load_item(inst), 1), ensure_ascii=False), encoding="utf-8")
    log = run.tmp / "fake.log"
    # 役が誤りで終わった回: 受け付けに回さず、層の 1 行（with-auth: auth=…）を運び、起こし直しの記録を残す
    # ——層の行を運ばないと、認証落ちが「役の返答の不良」に見える
    data = run.tmp / "plugin-data"
    r = run.cmd("launch", "--node", inst["id"], env={**env, "FAKE_MODE": "error", "CLAUDE_PLUGIN_DATA": str(data)})
    bad = (json.loads(r.stdout)["launched"] if r.returncode == 0 else [{}])[0]
    rows = [json.loads(x) for x in (data / "intake.jsonl").read_text(encoding="utf-8").splitlines()] if (data / "intake.jsonl").is_file() else []
    check(r.returncode == 0 and [(x["where"], x["exc"], x["func"], x.get("run", {}).get("run_id")) for x in rows]
          in ([(f"loop.py launch --node {inst['node']}", exc, "role_run.run_role", json.loads((run.dir / "state.json").read_text(encoding="utf-8"))["run_id"])]
              for exc in ("launch_child_failed", "launch_auth"))
          and "stderr" not in rows[0],
          f"launch は exit 0 のまま、落ちた役の行を利用者の置き場に 1 行残す（標準エラーは既定で残さない。{rows}）")
    st = json.loads((run.dir / "state.json").read_text(encoding="utf-8"))
    me = st["rounds"][-1]["instances"].get(inst["id"], {})
    check(not bad.get("ok") and "誤りで終わった" in (bad.get("why") or "") and "with-auth: auth=" in (bad.get("stderr") or ""),
          f"誤りの包みは受け付けず、層の標準エラーを結果に運ぶ（{bad.get('why')} / {(bad.get('stderr') or '')[:50]}）")
    check(me.get("status") == "pending" and [x.get("kind") for x in me.get("attempt_log", [])] == ["failed"],
          f"落ちた起動は盤面の attempt_log に理由つきで残り、節は待ったまま（{me.get('status')} {me.get('attempt_log')}）")
    r = run.cmd("launch", "--node", inst["id"], env=env)
    check("起こし済み" in r.stdout, f"起こした試行は 2 度起こさない——出口は relaunch（{r.stdout[-120:]}）")
    old_out = me.get("out_path")
    r = run.cmd("relaunch", "--node", inst["id"], "--reason", "検査: 役が誤りで終わった", env=env)
    check(r.returncode == 0, f"relaunch で新しい試行を作れる（{r.stderr[-80:]}）")
    # 遅れて終わった古い試行が、新しい試行の節を受け付けさせない（本文は今の試行の置き場からしか読まない）
    from engine.commands import _accept_for_launch
    from engine.util import Reject
    pathlib.Path(old_out).write_text(ans.read_text(encoding="utf-8"), encoding="utf-8")
    try:
        _accept_for_launch(str(run.dir), inst["id"], old_out)("")
        stale = "受け付けた"
    except Reject as e:
        stale = str(e)
    check("起こし直されている" in stale, f"古い試行の返答は、新しい試行の節に受け付けない（{stale[:60]}）")
    r = run.cmd("launch", "--node", inst["id"], env={**env, "FAKE_OUT": str(ans), "FAKE_LOG": str(log), "FAKE_SESSION": "sess-cli"})
    got = json.loads(r.stdout)["launched"] if r.returncode == 0 else []
    one = got[0] if got else {}
    check(r.returncode == 0 and one.get("ok"), f"engine が起こして ok（rc={r.returncode}: {one.get('why') or r.stderr[-160:]}）")
    st = json.loads((run.dir / "state.json").read_text(encoding="utf-8"))
    me = st["rounds"][-1]["instances"].get(inst["id"], {})
    check(me.get("status") == "done" and me.get("session_id") == "sess-cli" and me.get("launch_state") == "ended",
          f"launch が受け付けまで済ませ、会話の番号を盤面に残す（{me.get('status')} {me.get('session_id')} {me.get('launch_state')}）")
    check("result" not in r.stdout and ans.read_text(encoding="utf-8")[:40] not in r.stdout,
          "launch の出力に役の返答の本文は載らない（回す側の会話に流さない）")
    runs = [json.loads(x) for x in (run.dir / "trace.jsonl").read_text(encoding="utf-8").splitlines()
            if '"role_run"' in x]
    runs = [x for x in runs if x.get("session_id") == "sess-cli"]
    check(len(runs) == 1 and runs[0].get("session_id") == "sess-cli" and runs[0].get("num_turns") == 2
          and runs[0].get("total_cost_usd") == 0.001 and runs[0].get("instance") == inst["id"],
          f"実行の要約（会話の番号・往復数・費用）が盤面の trace.jsonl に 1 起動 1 行で残る（{runs[-1:] }）")
    seen = [json.loads(x) for x in log.read_text(encoding="utf-8").splitlines()] if log.is_file() else []
    check(seen and seen[0]["stdin"] == pathlib.Path(inst["prompt_file"]).read_text(encoding="utf-8")[:4000],
          "材料（指示書）は標準入力で子へ届く")
    cwd = seen[0].get("cwd") if seen else None
    in_git = cwd is not None and subprocess.run(["git", "-C", cwd, "rev-parse", "--is-inside-work-tree"], capture_output=True, text=True, encoding="utf-8").stdout.strip() == "true"
    check(cwd is not None and not in_git and not pathlib.Path(cwd).resolve().is_relative_to(run.repo.resolve()),
          f"道具ゼロの役は Git リポジトリの外の一時ディレクトリで起こす（git status の写しを注入させない。cwd {cwd}）")
    r2 = run.cmd("launch", "--node", inst["id"], env=env)
    check(r2.returncode == 1 and "起こせる節が無い" in r2.stderr, f"済んだ節は起こし直さない（{r2.returncode}: {r2.stderr[-80:]}）")

    # **柵は graph の宣言を読まない。** graph を書き換えられる立場の人が柵ごと書き換えられるので、
    # engine は「自分の前置」と「遮断の旗」だけを見る
    from engine.validator import agent_def
    cold = agent_def("convergence-loops:cold-reader")
    role_file = run.tmp / "cold-reader.txt"
    role_file.write_text(cold["body"], encoding="utf-8")
    good = {"agent_type": "convergence-loops:cold-reader",
            "launch": {"argv": launch_prefix() + ["claude", "-p", "--model", cold["model"], "--effort", cold["effort"], "--tools", "",
                                                  "--setting-sources", "", "--append-system-prompt-file", str(role_file),
                                                  "--output-format", "json"], "stdin": str(fake)}}
    check(launch_refusal(good) is None, f"前置と旗が揃っていれば起こす（{launch_refusal(good)}）")
    for mut, want in ((lambda a: a[:1] + a[2:], "前置"),                    # 同梱の層を外す
                      (lambda a: [x for x in a if x != "--tools"], "旗")):  # 遮断の旗を落とす
        why = launch_refusal({**good, "launch": {"argv": mut(good["launch"]["argv"]), "stdin": str(fake)}}) or ""
        check(want in why, f"{want} が違えば engine は起こさない（{why[:70]}）")
    why = launch_refusal({**good, "launch": {**good["launch"], "missing": "claude"}}) or ""
    check("この環境に" in why, f"claude の無い環境では起こさず、その旨を返す（{why[:50]}）")
    # **綴りが違っても同じ層なら起こし、外へ出た綴りは撥ねる**（柵が緩んでいないことを対で見る）。
    # なぜ綴りが混ざるか・なぜ normpath で足りるかは engine.commands._norm が持つ
    for spelling, same in ((os.path.join(str(PLUGIN), "scripts", ".", "with-auth.py"), True),
                           (os.path.join(str(PLUGIN), "scripts", "..", "..", "evil.py"), False)):
        argv = [good["launch"]["argv"][0], spelling, *good["launch"]["argv"][2:]]
        why = launch_refusal({**good, "launch": {"argv": argv, "stdin": str(fake)}})
        check((why is None) == same,
              f"{'同じ層を指す綴りなら起こす' if same else '外へ出た綴りは撥ねる'}（{why or 'ok'}）")
    rm(run.tmp)


def test_role_run():
    """役を起こす関数（engine/role_run.run_role）を代役の claude で端から端まで通す。盤面を持たずに呼べること・
    包みを解いて本文だけを書くこと・拒まれたら同じ会話に続きを頼むこと・起こし直しで子を木ごと止めること。"""
    from engine import role_run
    print("役を起こす関数: 包み・受け付け・同じ会話での出し直し・起こし直しで木ごと止める・役のせいでない失敗は続けない")
    _td, tmp = parallel.workspace("gl-rolerun-")
    bindir = tmp / "bin"
    bindir.mkdir()
    fake = str(fakeclaude.install(bindir))
    prompt = tmp / "prompt.md"
    prompt.write_text("指示書の本文\n", encoding="utf-8")
    ans = tmp / "ans.json"
    ans.write_text('{"ok": 1}', encoding="utf-8")
    log, flog = tmp / "trace.jsonl", tmp / "fake.log"
    # 子の標準出力を Windows のパイプの既定（ANSI コードページ）に強いる——代役が日本語を書けないと、どの OS でも赤になる
    env = {**os.environ, "FAKE_OUT": str(ans), "FAKE_LOG": str(flog), "FAKE_MODE": "bad_then_answer", "FAKE_SESSION": "sess-9",
           "PYTHONIOENCODING": "cp1252"}
    seen = []

    def accept(text):
        seen.append(text)
        return None if text.strip().startswith("{") else "返答が JSON として読めない"

    argv = [fake, "-p", "--tools", ""]
    resume = [fake, "-p", "--resume", "{session_id}", "--tools", ""]
    out = tmp / "out.json"
    r = role_run.run_role(argv, prompt, out, accept=accept, resume_argv=resume, max_resumes=2,
                          log_path=log, meta={"instance": "x"}, env=env)
    calls = [json.loads(x) for x in flog.read_text(encoding="utf-8").splitlines()]
    check(r["ok"] and r["session_id"] == "sess-9" and len(r["runs"]) == 2 and r["rejections"] == ["返答が JSON として読めない"],
          f"拒まれたら同じ会話に続きを頼み、受け付けまで済ませる（{ {k: r[k] for k in ('ok', 'session_id', 'rejections')} }）")
    check(len(calls) == 2 and calls[1]["argv"][calls[1]["argv"].index("--resume") + 1] == "sess-9"
          and "返答が JSON として読めない" in calls[1]["stdin"] and calls[0]["stdin"] == "指示書の本文\n",
          "続きは記録した会話の番号で --resume し、拒否の理由を標準入力で渡す（初回は指示書）")
    check(out.read_text(encoding="utf-8") == '{"ok": 1}' and "sess-9" not in json.dumps({k: v for k, v in r.items() if k != "runs" and k != "session_id"}),
          "out_path には包みの本文（result）だけを書き、返り値は本文を持たない")
    rows = [json.loads(x) for x in log.read_text(encoding="utf-8").splitlines()]
    check([x.get("kind") for x in rows] == ["first", "resume"] and all(x.get("op") == "role_run" and x.get("instance") == "x" for x in rows)
          and rows[1].get("permission_denials") == ["WebFetch"] and all(x.get("envelope") is True for x in rows),
          f"1 起動 1 行の要約（op=role_run・添えた値・権限で拒まれた道具）を JSON Lines で足す（{[(x.get('kind'), x.get('permission_denials')) for x in rows]}）")
    # 上限まで拒まれ続けたら止める（続けない）
    r = role_run.run_role(argv, prompt, out, accept=lambda _t: "いつも拒む", resume_argv=resume, max_resumes=1, env=env)
    check(not r["ok"] and len(r["runs"]) == 2 and r["accepted"] is False and "いつも拒む" in r["why"],
          f"拒否が上限（resume_on_reject）まで続いたら止めて理由を返す（{len(r['runs'])} 起動）")
    # 役のせいでない失敗（受け付けの検査が例外）は続きを頼まない
    def boom(_t):
        raise RuntimeError("盤面が読めない")
    r = role_run.run_role(argv, prompt, out, accept=boom, resume_argv=resume, max_resumes=2, env={**env, "FAKE_MODE": "answer"})
    check(not r["ok"] and len(r["runs"]) == 1 and "盤面が読めない" in (r["why"] or ""),
          f"受け付けの検査が例外で落ちたら、続きを頼まずに理由を返す（{len(r['runs'])} 起動: {r['why']}）")
    r = role_run.run_role(argv, prompt, out, accept=accept, resume_argv=resume, max_resumes=2, env={**env, "FAKE_MODE": "error"})
    check(not r["ok"] and len(r["runs"]) == 1 and "誤りで終わった" in (r["why"] or ""), f"誤りの包みは受け付けに回さない（{r['why']}）")
    # result の無い誤りの包み（公式の SDKResultMessage: 誤りの subtype は result でなく errors を持つ）
    r = role_run.run_role(argv, prompt, out, accept=accept, env={**env, "FAKE_MODE": "error_noresult"})
    one = r["runs"][0] if r["runs"] else {}
    check(not r["ok"] and "誤りで終わった（error_max_turns: Reached maximum number of turns" in (r["why"] or "")
          and one.get("session_id") == "sess-9" and one.get("total_cost_usd") == 0.002 and one.get("num_turns") == 9
          and '"error_max_turns"' in (one.get("stdout_head") or ""),
          f"result の無い誤りの包みは subtype と errors を理由に出し、要約と標準出力の頭を残す（{r['why']} / {one.get('session_id')}）")
    # 包まずに本文だけが出た回（--output-format text の語で起こした古い graph の run）: 全文を本文として受け付けに回す。
    # 受け付けは engine の本物（commands.parse_output）。3 形（素の JSON・``` 囲い・後ろに文）の読み分けは
    # graphloops/tests/py/test_role_run_unwrap.py が見るので、ここは子プロセスを通す 1 形だけ
    from engine.commands import parse_output
    from engine.util import AnswerReject

    def parse(text):
        try:
            parse_output(text)
        except AnswerReject as e:
            return str(e)
        return None
    out2 = tmp / "out-text.json"
    body = '{"findings": []}\n\n以上が判定です。'
    ans.write_text(body, encoding="utf-8")
    r = role_run.run_role(argv, prompt, out2, accept=parse, resume_argv=resume, max_resumes=2,
                          log_path=log, env={**env, "FAKE_MODE": "text"})
    one = r["runs"][0] if r["runs"] else {}
    check(r["ok"] and len(r["runs"]) == 1 and out2.read_text(encoding="utf-8") == body and one.get("envelope") is False
          and r["session_id"] is None and not any(k in one for k in role_run.SUMMARY_KEYS),
          f"包みでない出力は全文を本文として受け付けまで通し、要約は envelope=false だけ（{r['why']}）")
    # 包みでない出力が拒まれたら、会話の番号が無いので続きを頼まずに 1 起動で止まる
    ans.write_text("判定は次のとおりです（散文）", encoding="utf-8")
    r = role_run.run_role(argv, prompt, out2, accept=parse, resume_argv=resume, max_resumes=2, env={**env, "FAKE_MODE": "text"})
    check(not r["ok"] and len(r["runs"]) == 1 and r["accepted"] is False and "JSON として読めない" in (r["why"] or ""),
          f"包みでない出力が拒まれたら、同じ会話に続きを頼めないので 1 起動で止まる（{len(r['runs'])} 起動）")
    # 包みでない出力が exit 0 以外と重なった回: 受け付けにも out_path にも回らないので、何が返ったかは標準出力の頭にだけ残る
    before = out2.read_text(encoding="utf-8")
    r = role_run.run_role(argv, prompt, out2, accept=parse, env={**env, "FAKE_MODE": "text", "FAKE_EXIT": "3"})
    one = r["runs"][0] if r["runs"] else {}
    check(not r["ok"] and "exit 3" in (r["why"] or "") and one.get("stdout_head") == "判定は次のとおりです（散文）"
          and out2.read_text(encoding="utf-8") == before,
          f"包みでない出力が exit 0 以外で終わった回は、受け付けに回さず標準出力の頭を要約に残す（{r['why']} / {one.get('stdout_head')!r}）")
    ans.write_text("", encoding="utf-8")
    r = role_run.run_role(argv, prompt, out2, accept=parse, env={**env, "FAKE_MODE": "text"})
    check(not r["ok"] and "標準出力が空" in (r["why"] or "") and r["accepted"] is None,
          f"空の標準出力は受け付けに回さない（{r['why']}）")
    ans.write_text('{"ok": 1}', encoding="utf-8")
    # 番号の再利用の見分けは開始時刻で（POSIX は ps の etime、Windows は CreationDate の FILETIME）
    check(role_run.parse_etime("05:07") == 307 and role_run.parse_etime("2-01:00:00") == 2 * 86400 + 3600
          and role_run.parse_etime("x") is None and role_run.parse_etime("") is None,
          "ps の etime（[[dd-]hh:]mm:ss）を秒に読む（読めなければ None——確かめられない）")
    check(role_run.parse_cim("gone\r\n") == role_run.GONE and role_run.parse_cim("alive:116444736000000000") == 0.0
          and role_run.parse_cim("alive:") is None and role_run.parse_cim("") is None,
          "Windows: 居ない・開始時刻・読めない（確かめられない＝止めずに拒む）を分ける")
    if os.name == "posix":
        def gone(pid, within=10):
            """pid が居なくなるまで期限つきで問い直す——止めた孫は親が居なくなってから init が回収するので、1 回だけ見ると
            回収前のゾンビを『生きている』と数えて時々赤くなる"""
            t0 = time.monotonic()
            while True:
                try:
                    os.kill(pid, 0)
                except OSError:
                    return True
                if time.monotonic() - t0 > within:
                    return False
                time.sleep(0.05)

        def sleeper(extra):
            """眠る子（孫も立てる）を run_role で起こし、印（<out>.pgid）と孫の pid が出るまで待つ。返すのは (スレッド, 結果, 孫の pid)"""
            pidf = tmp / f"grandchild-{len(extra)}.pid"
            got = {}
            th = threading.Thread(target=lambda: got.update(role_run.run_role(
                argv, prompt, out, env={**env, "FAKE_MODE": "sleep", "FAKE_PID": str(pidf)}, **extra)))
            th.start()
            t0 = time.monotonic()
            while not (pidf.is_file() and pidf.read_text(encoding="utf-8")) and th.is_alive() and time.monotonic() - t0 < 30:
                time.sleep(0.05)
            return th, got, int(pidf.read_text(encoding="utf-8")) if pidf.is_file() and pidf.read_text(encoding="utf-8") else None

        mark = pathlib.Path(str(out) + ".pgid")
        th, got, pid = sleeper({})
        check(mark.is_file() and json.loads(mark.read_text(encoding="utf-8")).get("pgid"),
              "起こした子のグループの番号を置き場の隣（<out>.pgid）に書く——別のプロセス（relaunch）が止める口")
        t0 = time.monotonic()
        why = role_run.stop_group(str(mark))
        th.join(30)
        check(why is None and not th.is_alive() and not got.get("ok") and time.monotonic() - t0 < 30,
              f"stop_group は別の口から試行の子を止め、run_role は失敗として返る（{why} {got.get('why')}）")
        check(pid is not None and gone(pid), f"stop_group では孫（前置の層の先の claude に当たる）まで止まる（pid {pid}）")
        check(not mark.exists(), "子が終わったら印を消す（残った番号が別のグループに当たらない）")
        check(role_run.stop_group(str(mark)) is None, "印が無ければ止める物は無い（relaunch は素通り）")
        # launch のプロセスが止められたとき（kill_all）も、生きている子を孫まで止める
        th, got, pid = sleeper({"log_path": None})
        role_run.kill_all()
        th.join(30)
        check(not th.is_alive() and pid is not None and gone(pid) and not mark.exists(),
              f"kill_all は生きている子を孫まで止める（launch が止められても子を残さない。pid {pid}）")
        # 起こした直後に起こし直されていたと分かったら、その子を自分で止めて『起こし直された』で返る（still_mine）
        seen_mark = {}

        def superseded():
            # 聞かれるのは印を書いた後（relaunch と交わっても一方が止める順序）。印の番号を控えて、その子が止まったかを見る
            seen_mark.update(json.loads(mark.read_text(encoding="utf-8")) if mark.is_file() else {})
            return False
        th, got, _ = sleeper({"still_mine": superseded})
        th.join(30)
        check(not th.is_alive() and got.get("superseded") and not got.get("ok") and got.get("why") == role_run.SUPERSEDED,
              f"起こし直された試行は子を止めて返る（{got.get('why')}）")
        leader = seen_mark.get("pgid")
        check(not mark.exists() and leader is not None and gone(leader),
              f"そのとき子の木も印も残さない——still_mine を聞く前に印は書いてある（pgid {leader}）")
        # 番号が印より後に始まったプロセスに再利用されていたら止めない——同じ python・同じ層（with-auth.py）の兄弟の試行でも
        other = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"], start_new_session=True)
        mark.write_text(json.dumps({"pgid": other.pid}), encoding="utf-8")
        past = time.time() - 60
        os.utime(mark, (past, past))   # 印は 60 秒前に書かれた（その後に始まった other は別物）
        why = role_run.stop_group(str(mark))
        alive = other.poll() is None
        other.kill()
        other.wait()
        check(why is None and alive and not mark.exists(), f"番号が印より後に始まったプロセスに再利用されていれば止めずに印だけ消す（{why} alive={alive}）")
        # 開始時刻を確かめられない回は止めない（止める向きの誤りは無関係な木を止める）
        orig = role_run._started_at
        role_run._started_at = lambda pid: None
        try:
            mark.write_text(json.dumps({"pgid": os.getpid()}), encoding="utf-8")
            why = role_run.stop_group(str(mark))
        finally:
            role_run._started_at = orig
        check(why and "確かめられない" in why and mark.exists(), f"開始時刻を確かめられなければ止めずに理由を返す（{why}）")
        mark.unlink()
        # テストの実行器を走らせる口（run_tree）: 時間切れは孫まで止め、標準入力は閉じ、文字列で返す
        gpid = tmp / "tree-grandchild.pid"
        try:
            role_run.run_tree(["sh", "-c", f"sleep 37 & echo $! > {gpid}; wait"], cwd=tmp, timeout=1)
            got = "時間切れにならなかった"
        except subprocess.TimeoutExpired:
            got = "TimeoutExpired"
        gp = int(gpid.read_text(encoding="utf-8")) if gpid.is_file() else None
        check(got == "TimeoutExpired" and gp is not None and gone(gp), f"run_tree: 時間切れで孫まで止めてから TimeoutExpired を上げる（{got} pid {gp}）")
        # SIGTERM を無視する孫も止まる——長（sh）が先に終わっても、グループが消えるまで待って SIGKILL を送る
        gpid2 = tmp / "tree-deaf.pid"
        try:
            role_run.run_tree(["sh", "-c", f"(trap '' TERM; echo $$ > /dev/null; exec sh -c 'trap \"\" TERM; echo $$ > {gpid2}; while :; do sleep 1; done') & wait"],
                              cwd=tmp, timeout=1)
        except subprocess.TimeoutExpired:
            pass
        gp2 = int(gpid2.read_text(encoding="utf-8")) if gpid2.is_file() and gpid2.read_text(encoding="utf-8").strip() else None
        check(gp2 is not None and gone(gp2), f"run_tree: SIGTERM を無視する孫も、グループが消えるまで待って SIGKILL で止める（pid {gp2}）")
        r = role_run.run_tree(["sh", "-c", "read x; echo \"got:$x\"; echo err >&2"], cwd=tmp, timeout=30)
        check(r.returncode == 0 and r.stdout == "got:\n" and r.stderr == "err\n",
              f"run_tree: 標準入力は閉じ（対話を待たない）、出力は文字列で返す（{r.returncode} {r.stdout!r} {r.stderr!r}）")
    rm(tmp)


def test_relaunch_live_launch():
    """**生きている launch に relaunch する**（回す側の案内どおりの使い方）。relaunch は新しい試行を盤面に書いてから古い試行の子を
    止めるので、止められた古い launch の締めは版の競りで relaunch を落とさず、『起こし直された古い試行』に言い換わる
    （実測 2026-09-25: 止めてから書いていた版は 4 回とも exit 2）"""
    if os.name != "posix":
        return
    print("生きている launch への relaunch: 1 回目で通り、古い launch は起こし直された試行として締める")
    run = Run("relaunch-live")
    run.next()
    run.done("p0.question", base_answers(run, "std")["p0.question"](None, 1))
    bindir = run.tmp / "fakebin"
    bindir.mkdir()
    fakeclaude.install(bindir)
    env = {**os.environ, "PATH": str(bindir) + os.pathsep + os.environ.get("PATH", "")}
    nx = json.loads(run.cmd("next", env=env).stdout)
    inst = next(i for i in nx["ready"] if i.get("mode") == "cli")
    pidf = run.tmp / "grandchild.pid"
    lp = subprocess.Popen([PY, str(LOOP), "launch", "--node", inst["id"], "--dir", str(run.dir)], cwd=run.repo,
                          env={**env, "FAKE_MODE": "sleep", "FAKE_PID": str(pidf)}, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                          text=True, encoding="utf-8")
    mark = pathlib.Path(inst["out_path"] + ".pgid")
    t0 = time.monotonic()
    while not (mark.is_file() and pidf.is_file() and pidf.read_text(encoding="utf-8")) and time.monotonic() - t0 < 60:
        time.sleep(0.05)
    r = run.cmd("relaunch", "--node", inst["id"], "--reason", "検査: 生きている launch を起こし直す", env=env)
    try:
        out, err = lp.communicate(timeout=60)
    except subprocess.TimeoutExpired:
        lp.kill()
        out, err = lp.communicate()
    me = run.state()["rounds"][-1]["instances"][inst["id"]]
    check(r.returncode == 0 and me.get("attempts") == 2,
          f"relaunch: 生きている launch への 1 回目の起こし直しが通る（rc={r.returncode} attempts={me.get('attempts')} {r.stderr.strip()[-120:]}）")
    rows = json.loads(out)["launched"] if lp.returncode == 0 and out.strip() else []
    from engine.role_run import SUPERSEDED
    check(rows and rows[0].get("superseded") and rows[0].get("why") == SUPERSEDED,
          f"古い launch の行は『起こし直された古い試行』に言い換わる（rc={lp.returncode} {rows[:1]} {err.strip()[-120:]}）")
    check(me.get("status") == "pending" and not me.get("launched_at") and me["out_path"] != inst["out_path"],
          "新しい試行は待ったまま（古い launch の締めが新しい試行に書かない）")
    rm(run.tmp)


CONFLICT_PROBE = r"""
import io, json, pathlib, sys, types
from contextlib import redirect_stderr, redirect_stdout
sys.path.insert(0, sys.argv[1])
from engine import commands as C
from engine.board import Board
from engine.util import BoardConflict
d = sys.argv[2]
run_dir = pathlib.Path(d)
got = {}

def bump_rev():
    st = json.loads((run_dir / "state.json").read_text(encoding="utf-8"))
    st["rev"] = st.get("rev", 0) + 1
    (run_dir / "state.json").write_text(json.dumps(st, ensure_ascii=False), encoding="utf-8")

calls = []
def fn(b):
    calls.append(1)
    b.trace("conflict_probe", n=len(calls))
    if len(calls) == 1:
        bump_rev()
    return len(calls)
buf = io.StringIO()
with redirect_stderr(buf):
    got["retry"] = C._board_update(d, fn)
got["retry_stderr"] = buf.getvalue()
got["probe_rows"] = [json.loads(x)["n"] for x in (run_dir / "trace.jsonl").read_text(encoding="utf-8").splitlines() if '"conflict_probe"' in x]

def always(b):
    bump_rev()
try:
    C._board_update(d, always)
    got["lose"] = None
except BoardConflict as e:
    got["lose"] = [e.code, e.msg, str(e)]

st = json.loads((run_dir / "state.json").read_text(encoding="utf-8"))
iid = next(k for k, i in st["rounds"][-1]["instances"].items() if i["status"] == "pending")
st["rounds"][-1]["instances"][iid].update(launch={"argv": ["x"], "stdin": "x"}, launched_at="2026-09-25T00:00:00+09:00", launch_state="ended")
(run_dir / "state.json").write_text(json.dumps(st, ensure_ascii=False), encoding="utf-8")
orig_save, hit = Board.save, []
def flaky_save(self):
    if not hit:
        hit.append(1)
        self.seen_rev = -1
    return orig_save(self)
Board.save = flaky_save
out = io.StringIO()
with redirect_stdout(out):
    C.cmd_launch(types.SimpleNamespace(dir=d, node=None))
Board.save = orig_save
got["mark_hit"] = bool(hit)
got["launched"] = [x["id"] for x in json.loads(out.getvalue())["launched"]]
got["iid"] = iid

def losing(*_a, **_k):
    raise BoardConflict("検査用の衝突")
C.accept_output = losing
inst = json.loads((run_dir / "state.json").read_text(encoding="utf-8"))["rounds"][-1]["instances"][iid]
pathlib.Path(inst["out_path"]).parent.mkdir(parents=True, exist_ok=True)
pathlib.Path(inst["out_path"]).write_text("{}", encoding="utf-8")
acc = C._accept_for_launch(d, iid, inst["out_path"])
try:
    acc("")
    got["accept"] = "受け付けた"
except BoardConflict:
    got["accept"] = "BoardConflict"
got["accept_flag"] = acc.conflict

# 1 回負けてから通る受け付け: 当て直しの 2 回目で本物の受け付けに届く
calls = []
def once(*a, **k):
    calls.append(1)
    if len(calls) == 1:
        raise BoardConflict("検査用の 1 回目の衝突")
    return "受け付けた（検査用）"
C.accept_output = once
acc = C._accept_for_launch(d, iid, inst["out_path"])
got["accept_retry"] = [acc(""), acc.msg, acc.conflict, len(calls)]

# launch_one は受け付けの負け（conflict の印）に done の案内を足す
C.accept_output = losing
C.launch_refusal = lambda _inst: None
def fake_run_role(argv, prompt, out, accept=None, **kw):
    try:
        accept("")
        why = None
    except (Exception, SystemExit) as e:
        why = f"受け付けの検査が落ちた（{type(e).__name__}: {e}）"
    return {"ok": False, "why": why, "session_id": None, "superseded": False, "accepted": None, "runs": [], "rejections": []}
C.run_role = fake_run_role
row = C.launch_one(d, {**inst, "launch": {"argv": ["x"], "stdin": inst["out_path"]}}, 0)
got["launch_hint"] = row.get("why")
print(json.dumps(got, ensure_ascii=False))
"""


CLI_CONFLICT_PROBE = r"""
import os, runpy, sys
sys.path.insert(0, sys.argv[1])
from engine.board import Board
from engine.util import BoardConflict
def always(self):
    raise BoardConflict("検査用の衝突の文（loop.py の入口が出す）")
Board.save = always
sys.argv = ["loop.py", "next", "--dir", sys.argv[2]]
runpy.run_path(os.environ["GL_LOOP"], run_name="__main__")
"""


RELAUNCH_RACE_PROBE = r"""
import json, pathlib, sys, types
sys.path.insert(0, sys.argv[1])
from engine import commands as C
from engine.util import Reject
d, iid = sys.argv[2], sys.argv[3]
state = pathlib.Path(d) / "state.json"

def racing_probe(_mark):
    # 印を確かめている間に、別の relaunch が同じ instance を起こし直した（置き場が変わった）
    st = json.loads(state.read_text(encoding="utf-8"))
    st["rounds"][-1]["instances"][iid]["out_path"] += ".a9.json"
    state.write_text(json.dumps(st, ensure_ascii=False), encoding="utf-8")
    C.probe_group = lambda _m: (None, None)
    return None, None
C.probe_group = racing_probe
try:
    C.cmd_relaunch(types.SimpleNamespace(dir=d, node=iid, reason="検査用"))
    print("通った")
except Reject as e:
    print(str(e))
"""


def test_relaunch_race():
    """読んでいる間に別の relaunch が同じ instance を起こし直したら、新しい試行を重ねずに拒む（別のプロセスで差し替えて起こす）"""
    print("起こし直しの競り: 読んでいる間に置き場が変わったら拒む")
    run = Run("relaunch-race")
    run.next()
    run.done("p0.question", base_answers(run, "std")["p0.question"](None, 1))
    nx = run.next()
    inst = next(i for i in nx["ready"] if i.get("launch") or i.get("mode") == "cli")
    r = subprocess.run([PY, "-c", RELAUNCH_RACE_PROBE, str(PLUGIN), str(run.dir), inst["id"]], capture_output=True, text=True, encoding="utf-8", timeout=300)
    me = run.state()["rounds"][-1]["instances"][inst["id"]]
    check("別の relaunch" in r.stdout and me.get("attempts", 1) == 1,
          f"relaunch: 読んでいる間に別の relaunch が起こし直していたら、新しい試行を作らない（{r.stdout.strip()[-120:]} {r.stderr[-120:]} attempts={me.get('attempts')}）")
    rm(run.tmp)


SIGNAL_PROBE = r"""
import json, os, subprocess, sys, time
sys.path.insert(0, sys.argv[1])
from engine import role_run as R
got = {}
# 錠を持つ最中の同じスレッドに信号の口が割り込んでも止まらない（再入できる錠）
with R._LIVE_LOCK:
    R.kill_all()
    got["reentrant"] = True
# 止める信号の後に起こした子は、すぐ止めて StopSignal を上げる（止め始めた後に子を増やさない）
R._STOPPING.set()
try:
    R.run_tree(["sh", "-c", "sleep 30"], cwd=".", timeout=60)
    got["stopping"] = "起こした"
except R.StopSignal:
    got["stopping"] = "StopSignal"
got["live_after"] = len(R.LIVE)
R._STOPPING.clear()
# 止め切れなかった木の理由は、時間切れの例外に添えて呼び元へ運ぶ
orig = R._stop_tree
R._stop_tree = lambda pgid, leader=None: "検査用の止め切れない理由"
try:
    R.run_tree(["sh", "-c", "sleep 3"], cwd=".", timeout=0.3)
    got["tree_left"] = None
except subprocess.TimeoutExpired as e:
    got["tree_left"] = getattr(e, "tree_left", None)
R._stop_tree = orig
print(json.dumps(got, ensure_ascii=False))
"""


def test_stop_signal_guards():
    """止める信号の口の守り: 再入できる錠・止め始めた後の起動の拒否・止め切れなかった理由の運び（engine の大域を差し替えるので
    別のプロセスで走らせる）"""
    if os.name != "posix":
        return
    print("止める信号の口: 錠の再入・止め始めた後の起動を拒む・止め切れない理由を運ぶ")
    r = subprocess.run([PY, "-c", SIGNAL_PROBE, str(PLUGIN)], capture_output=True, text=True, encoding="utf-8", timeout=120)
    try:
        got = json.loads(r.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        got = {}
    check(got.get("reentrant") is True, f"信号の口（kill_all）は錠を持つ最中の同じスレッドでも止まらない（{r.stderr[-160:]}）")
    check(got.get("stopping") == "StopSignal" and got.get("live_after") == 0,
          f"止める信号の後に起こした子はすぐ止めて StopSignal を上げる（{got.get('stopping')} live={got.get('live_after')}）")
    check(got.get("tree_left") == "検査用の止め切れない理由", f"止め切れなかった木の理由は時間切れの例外に添えて運ぶ（{got.get('tree_left')}）")


def test_board_conflict():
    """**版の衝突の消費側**: _board_update は読み直して当て直し、成功した回は失敗の文も重なった trace も残さない。launch の
    印付け（mark）は当て直しで行を重ねない。受け付けが当て直しの回数まで負けたら、launch は done の案内を足せる印を立てる。
    engine の関数を差し替えて起こすので、別のプロセスで走らせる（台本は同じプロセスで並列に走る——差し替えが他の台本に漏れる）"""
    print("版の衝突: 読み直して当て直す・成功した回は文も trace も重ねない・mark は行を重ねない・受け付けの負けは印で運ぶ")
    run = Run("conflict")
    run.next()
    r = subprocess.run([PY, "-c", CONFLICT_PROBE, str(PLUGIN), str(run.dir)], capture_output=True, text=True, encoding="utf-8", timeout=300)
    try:
        got = json.loads(r.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        got = {}
    check(got.get("retry") == 2 and got.get("retry_stderr") == "" and got.get("probe_rows") == [2],
          f"_board_update: 衝突したら読み直して当て直し、成功した回は失敗の文も控えた trace も出さない（{got.get('retry')} {got.get('retry_stderr')!r} {got.get('probe_rows')} {r.stderr[-200:]}）")
    lose = got.get("lose") or [None, "", ""]
    check(lose[0] == 2 and "盤面が読んだ後に進んでいる" in lose[1] and lose[2] == lose[1],
          f"_board_update: 当て直しの回数まで負けたら BoardConflict（exit 2・文は呼び手が出す）を上げる（{lose}）")
    check(got.get("mark_hit") and got.get("launched") == [got.get("iid")],
          f"cmd_launch の mark: 当て直しても『起こし済み』の行を重ねない（{got.get('launched')}）")
    check(got.get("accept") == "BoardConflict" and got.get("accept_flag") is True,
          f"受け付けの衝突は当て直しの後に印（conflict）を立てて上げる（{got.get('accept')} {got.get('accept_flag')}）")
    check(got.get("accept_retry") == [None, "受け付けた（検査用）", False, 2],
          f"受け付けは 1 回負けても当て直しで通る（{got.get('accept_retry')}）")
    check("done --node" in (got.get("launch_hint") or "") and "返答は" in (got.get("launch_hint") or ""),
          f"launch は受け付けの負けに done の案内を足す（{(got.get('launch_hint') or '')[-120:]}）")
    r = subprocess.run([PY, "-c", CLI_CONFLICT_PROBE, str(PLUGIN), str(run.dir)], capture_output=True, text=True, encoding="utf-8",
                       env={**os.environ, "GL_LOOP": str(LOOP)}, timeout=300)
    check(r.returncode == 2 and "NG 検査用の衝突の文" in r.stderr,
          f"loop.py の入口は版の衝突の文を最後に 1 度出して exit 2（rc={r.returncode} {r.stderr.strip()[-120:]}）")
    rm(run.tmp)


def test_tooled_launch_fence():
    """道具つきの役を engine が起こしてよい形（launch_refusal の 2 形目）。**入口ごとに 1 本ずつ倒して撥ねることを見る**。
    柵は許可表なので、倒し方は「値を変える」「要る旗を落とす」「知らない語を足す」の 3 系統を全部撃つ。"""
    from engine import role_run
    from engine.commands import launch_prefix, launch_refusal
    from engine.role_run import protected_paths, tooled_permission
    from engine.validator import agent_def
    print("道具つきの柵: 許可表の旗だけ・設定を読まない・聞く先が無い・権限の形と道具と sandbox の設定は engine が決めた値だけ")
    _td, tmp = parallel.workspace("gl-tooledfence-")
    stdin = tmp / "p.md"
    stdin.write_text("x", encoding="utf-8")
    # 子が起きる作業ツリー（linked worktree を 1 本持つ）と盤面の置き場
    repo, other, board = tmp / "repo", tmp / "wt2", tmp / "board"
    board.mkdir()
    for args in (["init", "-q", str(repo)], ["-C", str(repo), "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q",
                                                  "--allow-empty", "-m", "x"], ["-C", str(repo), "worktree", "add", "-q", str(other)]):
        subprocess.run(["git", *args], capture_output=True, check=True)
    real = os.path.realpath
    tools = ["Read", "Glob", "Grep", "WebSearch", "WebFetch"]  # agents/judge.md の道具
    perm = tooled_permission(tools)
    check(perm == {"form": "plain", "permission_mode": "dontAsk", "allowed_tools": tools, "settings": "{}"},
          f"コマンドを走らせない役は dontAsk で、道具を全部先に許し、設定は空（{perm}）")
    # 許すコマンドは字面で持つ——期待を tooled_permission から導くと、定数に gh api を足しても起こす側・柵・検査が揃って変わり緑のまま
    read_rules = ["Bash(gh issue list:*)", "Bash(gh issue view:*)", "Bash(gh pr list:*)", "Bash(gh pr view:*)", "Bash(gh pr diff:*)",
                  "Bash(gh search:*)", "Bash(gh repo view:*)", "Bash(git remote get-url:*)"]
    saved = role_run.sandbox_available
    try:
        role_run.sandbox_available = lambda: False
        p2 = tooled_permission(["Read", "Bash", "WebFetch"], repo, board)
        check(p2 == {"form": "read_only", "permission_mode": "dontAsk", "allowed_tools": ["Read", "WebFetch"] + read_rules, "settings": "{}"},
              f"sandbox を使えない環境では Bash を持つ役も dontAsk にし、Bash を丸ごと許さず読むだけのコマンドの前置だけを許す（gh api は許さない）（{p2}）")
        role_run.sandbox_available = lambda: True
        p3 = tooled_permission(["Read", "Bash", "WebFetch"], repo, board)
        box = json.loads(p3["settings"]).get("sandbox") or {}
        want_deny = sorted({real(repo), real(repo / ".git"), real(other), real(board)})
        check(p3["form"] == "sandbox" and p3["permission_mode"] == "dontAsk" and p3["allowed_tools"] == ["Read", "WebFetch"] + read_rules,
              f"sandbox を使える環境では Bash を持つ役を sandbox の形で起こし、gh は読むだけの前置で縛ったまま（{p3['form']} {p3['allowed_tools']}）")
        check(box.get("enabled") is True and box.get("allowUnsandboxedCommands") is False and box.get("failIfUnavailable") is True
              and box.get("autoAllowBashIfSandboxed") is True and box.get("excludedCommands") == ["gh:*"]
              and box.get("network") == {"allowedDomains": [], "strictAllowlist": True},
              f"sandbox の形: 外へ出る口を閉じ、起きなければ起動で落ち、gh だけ外で権限に掛け、中からの通信は無し（{box}）")
        check((box.get("filesystem") or {}).get("denyWrite") == want_deny,
              f"書き込みを止める場所は、自分を含む作業ツリーの根の全部・共有の .git・盤面の置き場（{(box.get('filesystem') or {}).get('denyWrite')}）")
        plain_dir = tmp / "plain"
        plain_dir.mkdir()
        check(protected_paths(plain_dir, board) == sorted({real(plain_dir), real(board)}),
              f"git の作業ツリーでない場所では cwd と盤面だけを守る（{protected_paths(plain_dir, board)}）")

        def body_of(role):
            d = agent_def(role)
            rf = tmp / (role.replace(":", "__") + ".txt")
            rf.write_text(d["body"], encoding="utf-8")
            return d, rf

        def argv_for(role, p, resume=None):
            d, rf = body_of(role)
            words = ["claude", "-p"] + (["--resume", resume] if resume else []) + [
                "--model", d["model"], "--effort", d["effort"], "--tools", ",".join(d["tools"]),
                "--allowedTools", ",".join(p["allowed_tools"]), "--permission-mode", p["permission_mode"],
                "--settings", p["settings"], "--permission-prompts", "none", "--setting-sources", "",
                "--append-system-prompt-file", str(rf), "--output-format", "json"]
            return launch_prefix() + words

        def refuse(inst):
            return launch_refusal(inst, repo, board)

        good = {"agent_type": "convergence-loops:judge", "launch": {"argv": argv_for("convergence-loops:judge", perm), "stdin": str(stdin)}}
        check(refuse(good) is None, f"揃った形は起こす（{refuse(good)}）")

        def swap(flag, val):
            return lambda a: [val if i > 0 and a[i - 1] == flag else x for i, x in enumerate(a)]

        def drop(flag):
            return lambda a: [x for i, x in enumerate(a) if x != flag and not (i > 0 and a[i - 1] == flag)]

        def with_argv(inst, argv):
            return {**inst, "launch": {**inst["launch"], "argv": argv}}

        other_file = tmp / "other.txt"
        other_file.write_text("別の本文", encoding="utf-8")
        # 入口ごとの腕（tests/mutations.json の TF*）が名指しで落とせるよう、検査の名前は字面で書く
        for mut, want, desc in ((swap("--setting-sources", "user"), "--setting-sources", "柵: 利用者の設定を読む子は起こさない"),
                                (swap("--permission-prompts", "ask"), "--permission-prompts", "柵: 聞く先を持つ子は起こさない"),
                                (drop("--setting-sources"), "argv に無い", "柵: 要る旗を落とした子は起こさない"),
                                (lambda a: a + ["--dangerously-skip-permissions"], "許可表に無い", "柵: 権限を外す旗を持つ子は起こさない"),
                                (lambda a: a + ["--allowed-tools", "Bash"], "許可表に無い", "柵: 別名の旗で道具を足した子は起こさない"),
                                (lambda a: a + ["--allowedTools=Bash"], "許可表に無い", "柵: = 綴りの旗で道具を足した子は起こさない"),
                                (lambda a: a + ["--add-dir", "/"], "許可表に無い", "柵: 作業ディレクトリを足した子は起こさない"),
                                (lambda a: a + ["--mcp-config", str(stdin)], "許可表に無い", "柵: MCP の設定を足した子は起こさない"),
                                (lambda a: a + ["--agents", "{}"], "許可表に無い", "柵: 役の定義を差し込んだ子は起こさない"),
                                (lambda a: a + ["余分"], "許可表に無い", "柵: 余分な位置引数を持つ子は起こさない"),
                                (swap("--permission-mode", "bypassPermissions"), "--permission-mode", "柵: 権限の形を広げた子は起こさない"),
                                (swap("--tools", ",".join(tools + ["Write"])), "--tools", "柵: 役の定義に無い道具を持つ子は起こさない"),
                                (swap("--allowedTools", ",".join(tools + ["Bash"])), "--allowedTools", "柵: 先に許す道具を広げた子は起こさない"),
                                (swap("--model", "haiku-other"), "--model", "柵: 役の定義と違うモデルの子は起こさない"),
                                (swap("--output-format", "stream-json"), "--output-format", "柵: 返答の包みを変えた子は起こさない"),
                                (swap("--append-system-prompt-file", str(other_file)), "--append-system-prompt-file",
                                 "柵: 役の定義でない本文を system prompt に足した子は起こさない"),
                                (swap("--settings", '{"permissions": {"allow": ["Bash"]}}'), "--settings", "柵: 設定で権限を配る子は起こさない"),
                                (lambda a: a + ["--tools", "Bash"], "--tools", "柵: 旗を重ねて後勝ちを狙う子は起こさない"),
                                (lambda a: a + ["--tools", ",".join(tools)], "2 度", "柵: 同じ旗を 2 度渡す子は起こさない（同じ値でも）")):
            why = refuse(with_argv(good, mut(good["launch"]["argv"]))) or ""
            check(want in why, f"{desc}（{why[:70]}）")
        # 続きの語（--resume）は engine が決めた会話だけ: 続きを頼む語は穴の字面、起こす語は instance の会話の番号
        check(refuse({**good, "launch": {**good["launch"], "resume_argv": argv_for("convergence-loops:judge", perm, "{session_id}")}}) is None,
              "続きを頼む語の --resume は穴の字面なら起こす")
        why = refuse(with_argv(good, argv_for("convergence-loops:judge", perm, "someone-else"))) or ""
        check("--resume" in why, f"柵: engine が決めていない会話を続ける子は起こさない（{why[:70]}）")
        check(refuse({**with_argv(good, argv_for("convergence-loops:judge", perm, "sess-1")), "session_id": "sess-1"}) is None,
              "前の節の会話（instance の session_id）を続ける語は起こす")
        bad_resume = {**good, "launch": {**good["launch"], "resume_argv": drop("--permission-prompts")(good["launch"]["argv"])}}
        check("argv に無い" in (refuse(bad_resume) or ""), "続きを頼む語にも同じ柵が当たる")

        # コマンドを走らせる役（investigator）の sandbox の形: 揃った形は起こし、設定の 1 か所でも緩めた形は撥ねる
        itools = agent_def("convergence-loops:investigator")["tools"]
        iperm = tooled_permission(itools, repo, board)
        igood = {"agent_type": "convergence-loops:investigator",
                 "launch": {"argv": argv_for("convergence-loops:investigator", iperm), "stdin": str(stdin)}}
        check(iperm["form"] == "sandbox" and refuse(igood) is None, f"Bash を持つ役の sandbox の形は起こす（{iperm['form']} {refuse(igood)}）")
        for extra, desc in (("Bash(gh api:*)", "柵: 書ける gh api を先に許した子は起こさない"), ("Bash", "柵: Bash を丸ごと先に許した子は起こさない")):
            why = refuse(with_argv(igood, swap("--allowedTools", ",".join(iperm["allowed_tools"] + [extra]))(igood["launch"]["argv"]))) or ""
            check("--allowedTools" in why, f"{desc}（{why[:70]}）")

        def loosen(fn):
            s = json.loads(iperm["settings"])
            fn(s["sandbox"])
            return json.dumps(s, ensure_ascii=False)

        wt_deny = [x for x in want_deny if x != real(other)]
        for fn, want, desc in ((lambda s: s.update(enabled=False), "sandbox が", "柵: sandbox を切った子は起こさない"),
                               (lambda s: s.update(allowUnsandboxedCommands=True), "sandbox が", "柵: sandbox の外へ出る口を開けた子は起こさない"),
                               (lambda s: s.update(failIfUnavailable=False), "sandbox が", "柵: sandbox が起きなくても走る子は起こさない"),
                               (lambda s: s["network"].update(allowedDomains=["api.github.com"]), "sandbox が", "柵: 通信の宛先を足した子は起こさない"),
                               (lambda s: s.update(excludedCommands=["gh:*", "python3:*"]), "sandbox が", "柵: sandbox の外で走るコマンドを足した子は起こさない"),
                               (lambda s: s["filesystem"].update(allowWrite=["/"]), "sandbox が", "柵: 書ける場所を足した子は起こさない"),
                               (lambda s: s["filesystem"].update(denyWrite=wt_deny), "denyWrite", "柵: 守る作業ツリーを欠いた子は起こさない")):
            why = refuse(with_argv(igood, swap("--settings", loosen(fn))(igood["launch"]["argv"]))) or ""
            check(want in why, f"{desc}（{why[:70]}）")
        s = json.loads(iperm["settings"])
        s["hooks"] = {}
        why = refuse(with_argv(igood, swap("--settings", json.dumps(s))(igood["launch"]["argv"]))) or ""
        check("--settings のキー" in why, f"柵: sandbox の外のキー（hooks）を混ぜた子は起こさない（{why[:70]}）")
        why = refuse(with_argv(igood, drop("--settings")(igood["launch"]["argv"]))) or ""
        check("argv に無い" in why, f"柵: sandbox の設定を落とした子は起こさない（{why[:70]}）")
        more = loosen(lambda s: s["filesystem"].update(denyWrite=s["filesystem"]["denyWrite"] + [str(tmp / "gone")]))
        check(refuse(with_argv(igood, swap("--settings", more)(igood["launch"]["argv"]))) is None,
              "起こした後に消えた作業ツリーを守る場所に残した子は起こす（守る場所の包含で見る）")
        subprocess.run(["git", "-C", str(repo), "worktree", "add", "-q", str(tmp / "wt3")], capture_output=True, check=True)
        why = refuse(igood) or ""
        check("relaunch" in why, f"柵: 起こした後に増えた作業ツリーを守らない子は起こさず、引き直しを促す（{why[:70]}）")
        # sandbox を使えない環境: 読むだけの形の語は起こし、sandbox の設定を持つ語は撥ねる（形は起こす時に engine が決め直す）
        role_run.sandbox_available = lambda: False
        rperm = tooled_permission(itools, repo, board)
        rgood = {**igood, "launch": {**igood["launch"], "argv": argv_for("convergence-loops:investigator", rperm)}}
        check(rperm["form"] == "read_only" and refuse(rgood) is None, f"sandbox を使えない環境では読むだけの形で起こす（{refuse(rgood)}）")
        check("--settings のキー" in (refuse(igood) or ""), "sandbox を使えない環境では sandbox の設定を持つ語を起こさない")
    finally:
        role_run.sandbox_available = saved
    from engine.advance import tooled_launchable
    for d, desc in (({"tools": ["Read", "Write"], "model": "opus", "effort": "high"}, "ファイルを書く道具を持つ役は engine が起こさない"),
                    ({"tools": ["*"], "model": "opus", "effort": "high"}, "道具の一覧を持たない役は engine が起こさない"),
                    ({"tools": ["Read"], "model": "inherit", "effort": "high"}, "モデルを名指ししない役は engine が起こさない")):
        check(not tooled_launchable(d), desc)
    check(tooled_launchable({"tools": ["Read"], "model": "sonnet", "effort": "medium"}), "道具を名指しした読むだけの役は engine が起こす")
    # 役の定義が読めない役は、形が決まらないので起こさない
    check("定義が読めない" in (launch_refusal({**good, "agent_type": "no-such-plugin:nobody"}) or ""), "定義の読めない役は起こさない")
    rm(tmp)


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
    check(stored and all(not os.path.isabs(x) and (run.dir / x).is_file() for x in stored),
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
    # **旧い綴り（--dir をそのまま前に付けた形）を、絶対の --dir で開いても二重にしない。**
    # 文字列の前方一致で見分けていたとき、絶対の --dir では旧い相対の綴りが前方一致にも絶対にも
    # 当たらず `<dir>/<dir>/…` に戻った（実測 2026-09-14: 旧盤面 20260912-214912 がその形）
    # 旧い綴りは cwd に対する相対なので、cwd を持つ子プロセスで見る（台本は並列に走るので chdir は使えない）
    old = os.path.relpath(next(f for _, f, _ in got), run.repo)
    probe = ("import pathlib,sys;sys.path.insert(0,sys.argv[1]);from engine.board import Board;"
             "b=Board(pathlib.Path(sys.argv[2]));"
             "print(pathlib.Path(b._out_path(sys.argv[3])).is_file(),"
             "b._out_path('out/r1/nope.json')==str(pathlib.Path(sys.argv[2])/'out/r1/nope.json'))")
    r = subprocess.run([PY, "-c", probe, str(PLUGIN), str(run.dir), old], cwd=run.repo,
                       capture_output=True, text=True, encoding="utf-8", timeout=600)
    check(r.stdout.split() == ["True", "True"],
          f"旧い綴りを絶対の --dir で開いても二重に繋がず、実在しない綴りは盤面の下として返す（{r.stdout.strip()} {r.stderr[-120:]}）")
    rm(run.tmp)

    # **init から相対の --dir で回した run も、別の cwd から開ける。** 盤面の外から渡る綴りを 1 度だけ
    # 解決する規律が外れると、instance の item_file に cwd 依存の綴りが残り、別の cwd の呼び出しが落ちる
    # （上の腕は init を絶対で作るのでこの形にならない）
    rel_run = Run("reldir-init", rel_dir=True)
    check(rel_run.init.returncode == 0, f"相対の --dir で init できる（{rel_run.init.stderr[-160:]}）")
    drive(rel_run, "std")
    stored = [i["item_file"] for rd in rel_run.state()["rounds"] for i in rd["instances"].values() if i.get("item_file")]
    check(stored and all(os.path.isabs(x) for x in stored),
          f"扇の材料の綴りは cwd に依らない絶対（相対の --dir で回しても。{stored[:1]}）")
    r = subprocess.run([PY, str(LOOP), "status", "--dir", str(rel_run.dir)], cwd=rel_run.tmp,
                       capture_output=True, text=True, encoding="utf-8", env=rel_run.env, timeout=600)
    check(r.returncode == 0, f"相対で init した盤面を別の cwd から絶対で開ける（{r.returncode}: {r.stderr[-160:]}）")
    rm(rel_run.tmp)


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
    _td_tmp, tmp = parallel.workspace("gl-optw-")
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
    _td_tmp, tmp = parallel.workspace("gl-ansopt-")
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
            r2.done(inst["id"], tbl[inst["node"]](load_item(inst), out["round"]))
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

    def stopped_record(th, outcome="stopped"):
        # 止まった事実は record.convergence.outcome だけに置く（rules の stop() が書く場所）。loop_state は空——
        # 以前は loop_state に鍵を差し込んでいて、research-loop の rules が一度も書かない鍵を finalize が読む形を見なかった
        rec = {"gates": {k: {"status": "not_applicable"} for k in gates},
               "sampling": {"status": "not_applicable"}, "claims": [], "clusters": [], "process": {},
               "convergence": {"outcome": outcome}}
        b = types.SimpleNamespace(record=rec, state={"thickness": th}, loop_state={}, round=3)
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
    # 対の腕: 収束した記録では finalize が『飛ばした』を書かない（止まった事実の読み違いで収束を汚さない）
    g = stopped_record("標準", outcome="converged")
    check(all(g[k].get("status") != "not_run" for k in gates),
          f"収束した記録のゲートを『飛ばした』と書かない——{[g[k].get('status') for k in gates]}")


def test_stopped_before_gates_reports():
    """**ゲートが一度も走らずに止まった標準・重厚の run が、報告まで届く。**

    部品（finalize）を直に呼ぶ否定検査は、止まった事実を誰が書くかを見ない。書き手（rules の stop()）→ finalize →
    検証器 → report の一本道を、engine の CLI だけで通す。上限を 1 周にし、1 周目（新規相違があるのでゲートは
    走らない）で止める——標準は人が stop と答え、重厚は無人の保守的な停止。
    """
    print("台本: ゲートが走る前に止まった標準・重厚の run も report まで届く")
    for th, unattended in (("標準", False), ("重厚", True)):
        run = Run(f"stop-early-{th}", thickness=th, unattended=unattended)
        one = run.tmp / "one.json"
        one.write_text("1", encoding="utf-8")
        r = run.cmd("patch", "--path", "state.max_rounds", "--file", str(one), "--reason", "1 周目で止める筋を作る")
        check(r.returncode == 0, f"{th}: 上限を 1 周にできる（{r.stderr.strip()[-120:]}）")
        scenario = "heavy" if th == "重厚" else "std"

        def drive_to_end():
            # report の前で検証器に落とされると next が exit 1 になる——例外で台本ごと抜けず、赤の 1 件として数える
            try:
                return drive(run, scenario)
            except RuntimeError as e:
                return {"status": f"落ちた: {str(e)[-200:]}"}
        last = drive_to_end()
        if not unattended:
            check(last["status"] == "awaiting_human" and "max_rounds" in last["ask"]["kinds"], f"{th}: 上限で人に聞く（{last.get('ask', {}).get('kinds')}）")
            r = run.cmd("answer", "--text", "stop")
            check(r.returncode == 0, f"{th}: stop と答えられる")
            last = drive_to_end()
        rec = run.record()
        check(last["status"] == "stopped" and rec["convergence"]["outcome"] == "stopped", f"{th}: 止まった run として終わる（{last['status']}）")
        check((run.dir / "report.md").is_file(), f"{th}: ゲートが走る前に止まっても report.md が出る")
        v = subprocess.run([PY, str(VALIDATOR), str(run.dir / "record.json")], capture_output=True, text=True, encoding="utf-8", timeout=600)
        check(v.returncode == 0 and "停止（未収束）の申告つき" in v.stdout, f"{th}: 検証器が止まった記録として通す（exit {v.returncode}: {(v.stdout + v.stderr).strip()[-120:]}）")
        g = rec["gates"]
        skipped = ("cold_reader", "cartographer") if th == "重厚" else ("cold_reader",)
        for k in skipped:
            check(g[k].get("status") == "not_run" and bool(g[k].get("reason")), f"{th}: {k} は『飛ばした』と理由つきで残る——{g[k]}")
        if th == "標準":
            check(g["cartographer"].get("status") == "not_applicable" and bool(g["cartographer"].get("reason")),
                  f"標準: cartographer はこの段では走らせない（飛ばしたと名乗らない）——{g['cartographer']}")
        # rederiver の導出は毎周の序盤に走り暫定の判定を置くので、止まった周にも判定が残る（比較の半分は走っていない）。
        # その暫定の pass の扱いはこの台本の範囲外——ここでは『飛ばした』に化けないことだけを見る（語の妥当は上の検証器が見る）
        check(g["rederiver"].get("status") is None and bool(g["rederiver"].get("verdict")),
              f"{th}: rederiver は導出の暫定の判定が残る——{g['rederiver']}")
        rm(run.tmp)

def test_graphcheck_sets_derived():
    """**柵が見る鍵の一覧を、engine と rules から組む（手で並べない）。**

    受理集合（検証器の終了コードのうち先へ進んでよいもの）の鍵を graphcheck が 2 語で手書きしていた。
    engine か rules が鍵を増やしても柵は増えないので、**増えた鍵だけ形を誰も検査しないまま通る**。
    この腕は「rules が宣言した鍵が実際に見られること」と「宣言しなければ見られないこと」を対で見る
    ——宣言が母数だという性質そのものを踏む。
    """
    print("否定検査: 受理集合の鍵は engine と rules の宣言から組む")
    _td_tmp, tmp = parallel.workspace("gl-acck-")
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

    # **実物の next を通す。** 上は部品を直に呼ぶ腕と材料（prompt_bytes）の有無しか見ておらず、
    # **痕跡を積む配線（`if grew:`）を殺しても全件緑だった**（実測 2026-09-14。下の r2 の腕を足す前の話で、
    # 足した後は同じ注入が赤くなる——`grew = None` にして この台本を走らせれば再現する）。
    # 写しの graph で 100 KB の穴を育てるより、線を下げて実物の run を 1 本通す方が安い。
    r2 = Run("grow2")
    # 線と倍率の両方を下げる——台本の穴は周をまたいでも 1.05 倍までしか育たない（実測: p2.integrate が
    # 6,737 → 7,055 バイト）ので、線だけ下げても配線を通らない。2 つとも下げて初めて実物の next が踏む
    env = dict(os.environ, GL_PROMPT_NOTICE="1", GL_PROMPT_GROWTH_RATIO="1.0")
    for _ in range(60):
        nx = r2.next()
        if not nx["ready"]:
            break
        answers = base_answers(r2, "std")
        for inst in nx["ready"]:
            r2.done(inst["id"], answers[inst["node"]](load_item(inst), nx["round"]))
        # 2 周目以降の next は線を下げて通す（同じ節の穴が育っていれば growing_prompts に行が立つ）
        if r2.state()["round"] >= 2:
            r2.cmd("next", env=env)
    grew = r2.state().get("growing_prompts") or []
    check(grew, f"実物の next で育ちが盤面に残る（{[g.get('node') for g in grew][:3]}）")
    check(all({"node", "round", "bytes", "was"} <= set(g) for g in grew), f"行に節・周・前後の大きさが揃う（{grew[:1]}）")
    rec = r2.record()
    check("growing_prompts" in (rec.get("process") or {}), "記録（process.growing_prompts）にも着地する")
    rm(r2.tmp)


def test_relaunch():
    """**起こし直しは新しい試行を盤面に刻んでから前の試行の子を止め、前の置き場を締め出す。時間の上限は無い。**

    起こし直しが盤面に残らず、emitted_at は最初の起動のままだった（実測 2026-09-25: 週の上限で P1 の 8 節が落ち、別の
    セッションが起こし直した）。起こし直した試行は置き場を分ける（Temporal の task token が試行ごとに一意なのと同じ）。
    期限（deadline_minutes・wait）は 2026-09-25 に外した——目安の値が役の子を止める上限を兼ねていた。
    """
    print("起こし直し: next・status は経過と試行の回数を出し、relaunch は前の試行の子を止め、試行を刻んで前の置き場を締め出す")
    run = Run("relaunch")
    nx = run.next()
    own = next(i for i in nx["ready"] if i["node"] == "p0.question")
    check("deadline_at" not in own and "overdue" not in own and own.get("elapsed_min") == 0 and own.get("attempts") == 1,
          f"next: 期限を出さず、経過と試行の回数を出す（{ {k: own.get(k) for k in ('deadline_at', 'elapsed_min', 'attempts')} }）")
    r = run.cmd("relaunch", "--node", own["id"], "--reason", "検査用")
    check(r.returncode == 1 and "他へ渡して待っている" in r.stderr, f"relaunch: 回す側が自分でやる節は起こし直さない（{r.stderr.strip()[-80:]}）")
    r = run.cmd("wait", "--node", own["id"])
    check(r.returncode != 0 and "invalid choice" in r.stderr, f"wait の口は無い（期限の無い待ちを作らない）（{r.stderr.strip()[-60:]}）")
    def finish(i):
        r = run.done(i["id"], base_answers(run, "std")[i["node"]](load_item(i), 1))   # 台本の答えは記録から組むので毎回作り直す
        if r.returncode != 0:
            raise RuntimeError(f"done {i['id']} が {r.returncode}: {r.stderr}")
    inst = None
    for _ in range(10):   # 役（investigator）の節が出るまで回す側の節を済ませる
        inst = next((i for i in nx["ready"] if i["node"] == "p0.prior_decisions"), None)
        if inst:
            break
        for i in nx["ready"]:
            finish(i)
        nx = run.next()
    iid = inst["id"]
    check("deadline_at" not in inst and inst.get("attempts") == 1 and inst.get("elapsed_min") == 0,
          f"next: 役に渡す節にも期限は無く、経過・試行の回数を出す（{ {k: inst.get(k) for k in ('deadline_at', 'attempts')} }）")
    pend = run.status()["this_round"]["pending_instances"]
    check(any(p["id"] == iid and p.get("elapsed_min") == 0 and "overdue" not in p for p in pend), f"status: 待っている instance ごとに経過を出す（{pend[:1]}）")
    st = run.state()
    real_base = st["rounds"][-1]["instances"][iid].get("tree_before")
    st["rounds"][-1]["instances"][iid]["tree_before"] = ["?? 前の試行の基準点（検査用）"]
    (run.dir / "state.json").write_text(json.dumps(st, ensure_ascii=False), encoding="utf-8")
    old = pathlib.Path(st["rounds"][-1]["instances"][iid]["out_path"])
    old.write_text("前の試行の途中の返答（検査用）", encoding="utf-8")
    # 前の試行の子が生きている形: 自分のグループで眠る子を立て、role_run と同じ印を置き場の隣に置く
    child = None
    if os.name == "posix":
        script = run.tmp / "prev-attempt.py"
        script.write_text("import time\ntime.sleep(120)\n", encoding="utf-8")
        child = subprocess.Popen([sys.executable, str(script)], start_new_session=True)
        # 本物では子を起こした launch のプロセスが終了を待って回収する。ここでは台本がその役——回収しないと子は
        # ゾンビとしてグループに残り、relaunch には止まらない子に見える
        reaper = threading.Thread(target=child.wait)
        reaper.start()
        pathlib.Path(str(old) + ".pgid").write_text(json.dumps({"pgid": child.pid}), encoding="utf-8")   # 子を起こした後に書く（role_run と同じ順）
    r = run.cmd("relaunch", "--node", iid, "--reason", "子が落ちた（検査用）")
    check(r.returncode == 0, f"relaunch: 待っている instance は起こし直せる（{r.stderr.strip()[-80:]}）")
    if child is not None:
        reaper.join(15)
        stopped = not reaper.is_alive()   # 台本が止める前に終わっていた＝relaunch が止めた
        if not stopped:
            child.kill()
            reaper.join()
        check(stopped and child.returncode is not None and child.returncode < 0,
              f"relaunch: 前の試行の子を木ごと止めてから起こし直す（relaunch が止めた: {stopped}・信号で終わった: {child.returncode}）")
        check(not pathlib.Path(str(old) + ".pgid").exists(), "relaunch: 止めた試行の印を消す")
    new = run.state()["rounds"][-1]["instances"][iid]
    check(new.get("attempts") == 2 and len(new.get("attempt_log") or []) == 1 and "検査用" in new["attempt_log"][0]["reason"],
          f"relaunch: 試行の回数と理由を盤面に刻む（{new.get('attempts')} {new.get('attempt_log')}）")
    check(new["out_path"] in r.stdout, "relaunch: 新しい置き場を回す側に返す（運び手に渡す先）")
    check("deadline_at" not in new, f"relaunch: 新しい試行にも期限を付けない（{new.get('deadline_at')}）")
    check(new["out_path"] != str(old) and ".a2." in new["out_path"], f"relaunch: 新しい試行は別の置き場に書く（{new['out_path']}）")
    check(not old.exists() and old.with_name(old.name + ".stale-a1").is_file(), "relaunch: 前の試行の置き場に在った物は .stale-a1 へ退ける")
    check(new.get("tree_before") == ["?? 前の試行の基準点（検査用）"], "relaunch: 作業ツリーの基準点は前の試行の物を引き継ぐ（取り直さない）")
    trace = (run.dir / "trace.jsonl").read_text(encoding="utf-8")
    check('"relaunched"' in trace, "relaunch: trace に relaunched を残す")
    # 前の試行が遅れて書いても、done は今の試行の置き場しか読まない
    old.write_text("遅れて届いた前の試行の返答（検査用）", encoding="utf-8")
    r = run.cmd("done", "--node", iid)
    check(r.returncode != 0 and "返答が無い" in r.stderr, f"done: 前の試行の置き場は読まない（{r.stderr.strip()[-80:]}）")
    bad = pathlib.Path(new["out_path"] + ".pgid")
    bad.write_text("読めない印（検査用）", encoding="utf-8")
    r = run.cmd("relaunch", "--node", iid, "--reason", "止められない（検査用）")
    check(r.returncode == 1 and "確かめられない" in r.stderr and run.state()["rounds"][-1]["instances"][iid].get("attempts") == 2,
          f"relaunch: 前の試行の子を確かめられなければ新しい試行を作らない（{r.returncode} {r.stderr.strip()[-80:]}）")
    bad.unlink()
    # 前の relaunch が止め切れずに残した子（1 回目の試行の置き場の印）も、次の relaunch が止め直す（attempt_log の前の置き場）
    stale_child = None
    if os.name == "posix":
        stale_child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"], start_new_session=True)
        stale_reaper = threading.Thread(target=stale_child.wait)
        stale_reaper.start()
        pathlib.Path(str(old) + ".pgid").write_text(json.dumps({"pgid": stale_child.pid}), encoding="utf-8")
    # 置き場に何も無いまま 2 回目の起こし直し: 退ける物が無くても起こし直せ、試行の記録は積み増す
    r = run.cmd("relaunch", "--node", iid, "--reason", "2 回目（検査用）")
    if stale_child is not None:
        stale_reaper.join(15)
        stopped = not stale_reaper.is_alive()
        if not stopped:
            stale_child.kill()
            stale_reaper.join()
        check(stopped, "relaunch: 前の relaunch が止め切れなかった前の試行の子も、attempt_log の置き場の印から止め直す")
    new3 = run.state()["rounds"][-1]["instances"][iid]
    check(r.returncode == 0 and new3.get("attempts") == 3 and len(new3.get("attempt_log") or []) == 2,
          f"relaunch: 前の置き場が空でも起こし直せ、attempt_log は積み増す（{r.returncode} {new3.get('attempt_log')}）")
    st = run.state()
    st["rounds"][-1]["instances"][iid]["tree_before"] = real_base   # 検査用の基準点を本物に戻す（done の突合に通す）
    (run.dir / "state.json").write_text(json.dumps(st, ensure_ascii=False), encoding="utf-8")
    r = run.done(iid, base_answers(run, "std")["p0.prior_decisions"](load_item(new3), 1))
    check(r.returncode == 0, f"前提: 役の返答を --output で受け付ける（{r.stderr.strip()[-200:]}）")
    r = run.cmd("relaunch", "--node", iid, "--reason", "x")
    check(r.returncode == 1 and "待っている instance でない" in r.stderr, "relaunch: 済んだ instance は起こし直さない")
    r = run.cmd("relaunch", "--node", "無い節（検査用）", "--reason", "x")
    check(r.returncode == 1 and "待っている instance でない" in r.stderr, "relaunch: 今の周に無い instance は拒む")
    # 扇の項目の instance も、同じ id・同じ項目で起こし直せる
    fan = None
    for _ in range(20):
        nx = run.next()
        fan = next((i for i in nx["ready"] if i["node"] == "p1.checker"), None)
        if fan or not nx["ready"]:
            break
        for i in nx["ready"]:
            finish(i)
    r = run.cmd("relaunch", "--node", fan["id"], "--reason", "扇の項目（検査用）")
    got = run.state()["rounds"][-1]["instances"].get(fan["id"]) or {}
    check(r.returncode == 0 and got.get("attempts") == 2 and load_item(got) == load_item(fan),
          f"relaunch: 扇の項目の instance は同じ id・同じ項目で起こし直す（{r.returncode} {fan['id']}）")
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
    _td_tmp, tmp = parallel.workspace("gl-frozen-graph-")
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
            run.done(inst["id"], answers[inst["node"]](load_item(inst), nx["round"]))
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
    head, tail = "［先頭の目印 HEAD-NOCAP］", "［末尾の目印 TAIL-NOCAP］この行は読了の印の下限を満たす長さにしてある"
    big = f"# 見立て\n\n{head}\n" + ("主張 A・B・C・D を含む長い見立て。" * 8000) + f"\n{tail}\n"
    run.doc.write_text(big, encoding="utf-8")
    run.read_into_transcript(run.doc)   # 差し替えた本文を『会話で読んだ』ことにする（読了の確かめは転写を見る）
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
    _td_cfg, cfg = parallel.workspace("gl-cfg-")
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
        _td_tmp, tmp = parallel.workspace(f"gl-{name}-")
        shutil.copytree(PLUGIN / "prompts", tmp / "prompts")
        shutil.copytree(PLUGIN / "rules", tmp / "rules")
        (tmp / "graphs").mkdir()
        src = json.loads((PLUGIN / "graphs" / "research-loop.json").read_text(encoding="utf-8"))
        gp = tmp / "graphs" / "g.json"
        gp.write_text(json.dumps(src, ensure_ascii=False), encoding="utf-8")
        run = Run(name)
        d2 = run.tmp / "s2"
        call = lambda *a: subprocess.run([PY, str(LOOP), *a, "--dir", str(d2)], cwd=run.repo, capture_output=True, text=True, encoding="utf-8", env=run.env, timeout=600)
        init = call("init", "--loop", "research-loop", "--graph", str(gp), "--request", "q", "--document", str(run.doc), "--validator", str(VALIDATOR))
        # **壊すのは init の後。** init は静的検査を通すので、壊した graph はそもそも入口で落ちる
        # （それは別の腕で測る）。ここで見たいのは**実行時**の振る舞いなので、盤面ができてから差し替える
        g = json.loads(gp.read_text(encoding="utf-8"))
        mutate(g)
        gp.write_text(json.dumps(g, ensure_ascii=False), encoding="utf-8")
        run.dir = d2  # 台本（base_answers）が読む盤面をこの run に向ける（Run() が作った盤面のままだと抜き取りの項目が食い違う）
        run.mark_into_transcript()   # この盤面の run_id も転写に載せる（別の run の印では成立しない）
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
                o = answers[inst["node"]](load_item(inst), out["round"])
                f = run.tmp / "o.json"
                f.write_text(json.dumps(o, ensure_ascii=False) if not isinstance(o, str) else o, encoding="utf-8")
                call("done", "--node", inst["id"], "--output", str(f))
        if (d2 / "state.json").is_file():
            st = json.loads((d2 / "state.json").read_text(encoding="utf-8"))
        rm(tmp); rm(run.tmp)
        return seen, insts, st

    def init_only(name, mutate):
        """壊した graph で init だけを打つ（入口の静的検査を測る腕）。"""
        _td_tmp, tmp = parallel.workspace(f"gl-{name}-")
        shutil.copytree(PLUGIN / "prompts", tmp / "prompts")
        shutil.copytree(PLUGIN / "rules", tmp / "rules")
        (tmp / "graphs").mkdir()
        g = json.loads((PLUGIN / "graphs" / "research-loop.json").read_text(encoding="utf-8"))
        mutate(g)
        gp = tmp / "graphs" / "g.json"
        gp.write_text(json.dumps(g, ensure_ascii=False), encoding="utf-8")
        run = Run(name)
        r = subprocess.run([PY, str(LOOP), "init", "--loop", "research-loop", "--graph", str(gp), "--request", "q",
                            "--document", str(run.doc), "--dir", str(run.tmp / "s3"), "--validator", str(VALIDATOR)],
                           cwd=run.repo, capture_output=True, text=True, encoding="utf-8", env=run.env, timeout=600)
        board = (run.tmp / "s3" / "state.json").is_file()
        rm(tmp); rm(run.tmp)
        return r, board

    # **持ち込みの graph も入口で検査する。** 以前は静的検査が CLI にしかなく、init --graph <任意> は
    # 何も確かめずに通った（同梱の graph だけが守られていた）——実装は写さず、CLI と同じ関数を engine が呼ぶ
    r, board = init_only("initcheck", lambda g: g["nodes"]["p3.cold_reader"].__setitem__("run_by", "no-such-role"))
    check(r.returncode != 0 and "静的検査が通らない" in r.stderr and "no-such-role" in r.stderr,
          f"壊れた graph は init で落ちる（静的検査の理由も出る。rc={r.returncode}: {r.stderr[-120:]}）")
    check(not board, "静的検査で落ちた init は盤面を残さない")

    # graph 自身の plugin の役（遮断系はここにしか居ない）: 定義が無ければ die
    seen, insts, _ = drive_graph("norole", lambda g: g["nodes"]["p3.cold_reader"].__setitem__("run_by", "no-such-role"), "p3.cold_reader")
    check("解決できない" in seen and not insts, f"定義の無い役の節で next が die し、その節は一度も出ない（modes={[i['mode'] for i in insts]}: {seen[-160:]}）")
    # 別 plugin の役（pr-review-toolkit 等）はこの機械に無いことが普通にある（実測: CI）——止めず、痕跡を残して paste で出す
    seen, insts, st = drive_graph("foreign", lambda g: g["nodes"]["p1.checker"].__setitem__("agent_type", "other-plugin:someone"), "p1.checker")
    check("解決できない" not in seen and insts and all(i["mode"] == "agent" and i.get("deliver") == "paste" and i.get("role_def_missing") for i in insts),
          f"別 plugin の役は定義が無くても止めず、mode=agent・paste・role_def_missing 付きで出る（{len(insts)} 件: {seen[-120:]}）")
    check(bool(st) and any(x["agent_type"] == "other-plugin:someone" for x in st.get("role_def_missing", [])), "定義が無かった事実は state（→ process.role_def_missing）に残る")


def session_fixture(tmp, env, text=None, said=None, said_inline=False, as_list=False, dup=False,
                    numbered=False, externalized=False, subagent=False, parent_body=False, marked=True,
                    unreadable=False, mark_dir_only=False, scalar_line=False):
    """転写だけを差し替えた env（本番と同じ読み方で engine に見つけさせる）。

    text は道具の結果の本文、said は会話の地の文（役や人が書いた文）、as_list は本文が配列で入る形
    （実測 2026-09-18: Agent・SendMessage・ToolSearch の結果はこの形、Bash・Read は文字列）。
    **実物の転写が本文を落とす場所は 1 つではない**ので、失敗の形も作れるようにする:
      numbered      実物の Read と同じく各行に行番号＋タブの接頭が付く（照合は部分一致なので通るはず）
      externalized  大きい結果は別ファイル（tool-results/）へ外出しされ、親の転写には参照と抜粋しか残らない
      subagent      本文は subagent の別の転写（<sid>/subagents/agent-*.jsonl）に入り、親には無関係な結果だけ
      parent_body   置き場は作るが、親の転写にも本文を入れる（置き場の有無が判定に効かないことを見る腕）
      marked        この run を回した出力（engine が必ず言う盤面のパス）が転写に在る形。既定は在る——
                    **実物では、回す側が自分で engine を回していれば必ず載る**。False は載っていない形
                    （回す側そのものが subagent／出力をファイルへ落とした配置）で、engine が読んでいる
                    転写が回す側のものでないことを意味する
      scalar_line   dict でない JSON の行（前置フィルタの語だけを含む配列）を 1 行混ぜる。実物の転写は
                    ハーネスが行の形を足しうるので、**dict を前提にした読みが素の例外へ抜けない**ことを見る
      said_inline   地の文を**道具の結果と同じ 1 行**に並べる（実物の転写に在る形。別の行に置くと
                    前置フィルタが行ごと飛ばすので、ブロックの型を見ているかを測れない）。実物の地の文
                    （type=text）は本文を "text" に持ち "content" を持たないので、型の判定を外しても
                    数えられない——**型の柵そのものを測る**ために、content を持つ別の型のブロック
                    （engine が知らない型。ハーネスが後から足しうる形）を同じ 1 行に並べる
    unreadable は転写のパスは在るが開けない形（<sid>.jsonl をディレクトリにする。chmod は環境差が
    大きいので使わない）——探した直後に読めない回が、3 値の外（素の例外）へ抜けないことを見る。
    dup は同じ session id の転写が 2 つ見つかる形。**置き場の名前は内容の sha1 から作る**——
    abs(hash(...)) は PYTHONHASHSEED でプロセスごとに変わり、衝突した実行だけが別の標本の転写を
    共有して落ちる（再現しない赤になる）。
    """
    tag = hashlib.sha1(f"{text}|{said}|{said_inline}|{as_list}|{dup}|{numbered}|{externalized}|{subagent}|{parent_body}|{marked}|{unreadable}|{mark_dir_only}|{scalar_line}".encode("utf-8")).hexdigest()[:8]
    cfg, sid = tmp / f"cfg{tag}", "s" + tag
    parent_text = text
    if text is not None and numbered:
        parent_text = "\n".join(f"{i + 1}\t{ln}" for i, ln in enumerate(text.splitlines()))
    side = []          # 親の転写の外に落ちる本文（engine は読まない）
    if text is not None and externalized:
        head = "\n".join(text.splitlines()[:2])
        parent_text = f"{head}\n… （長いので tool-results/{tag}.txt に外出し）"
        side.append((cfg / "projects" / "sim" / sid / "tool-results" / f"{tag}.txt", text))
    if text is not None and subagent:
        parent_text = text if parent_body else "（本文は subagent が読んだ。親には残らない）"
        side.append((cfg / "projects" / "sim" / sid / "subagents" / "agent-1.jsonl",
                     json.dumps({"message": {"content": [{"type": "tool_result", "content": text}]}}, ensure_ascii=False) + "\n"))
    blocks = []
    if marked:
        # engine を回すとどのコマンドも run_id を言う——その道具の結果が転写に載る（Run の盤面は tmp/state）。
        # **engine と同じ直列化（util.dump＝json.dumps）を通す**: 平文で置いていたとき、実物が通る
        # 直列化の段を一度も通らず、Windows の区切りが二重化されて印が一致しない欠陥を捕まえられなかった。
        # 印を run_id にしたのも同じ理由で、パスと違い直列化で綴りが変わらない
        board = tmp / "state"
        rid = (json.loads((board / "state.json").read_text(encoding="utf-8"))["run_id"]
               if (board / "state.json").is_file() else "no-run")
        out = {"status": "running", "dir": str(board.resolve()), "run_id": rid}
        if mark_dir_only:
            out.pop("run_id")      # 盤面のパスだけが載った転写（印をパスに戻した実装でだけ印が立つ形）
        blocks.append({"message": {"content": [{"type": "tool_result", "content": dump(out)}]}})
    if parent_text is not None:
        body = [{"type": "text", "text": parent_text}] if as_list else parent_text
        blocks.append({"message": {"content": [{"type": "tool_result", "content": body}]}})
    if said is not None:
        if said_inline and blocks:
            blocks[-1]["message"]["content"] += [{"type": "text", "text": said},
                                                 {"type": "engine が知らない型", "content": said}]
        else:
            blocks.append({"message": {"content": [{"type": "text", "text": said}]}})
    line = "".join(json.dumps(b, ensure_ascii=False) + "\n" for b in blocks)
    if scalar_line:
        # 前置フィルタ（素の部分一致）は通るが dict ではない行。**先頭に置く**——読み手は
        # そろった時点で打ち切るので、後ろに置くと通る回では一度も読まれない
        line = json.dumps(["tool_result", "dict ではない行"], ensure_ascii=False) + "\n" + line
    for proj in (("a", "b") if dup else ("sim",)):
        (cfg / "projects" / proj).mkdir(parents=True, exist_ok=True)
        if unreadable:
            (cfg / "projects" / proj / f"{sid}.jsonl").mkdir(exist_ok=True)
        else:
            (cfg / "projects" / proj / f"{sid}.jsonl").write_text(line, encoding="utf-8")
    for path, content in side:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    return {**env, "CLAUDE_CONFIG_DIR": str(cfg), "CLAUDE_CODE_SESSION_ID": sid}


def read_through_run(name):
    """読了の腕 1 本ぶんの盤面（p0.claims が pending の所まで進めた run と、返答のファイル）。

    **通る腕は節を消費する**（done が受理されると同じ節にはもう出せない）ので、通る腕ごとに run を分ける。
    """
    run = Run(name)
    run.done(run.next()["ready"][0]["id"], base_answers(run, "std")["p0.question"](None, 1))
    ids = {i["node"]: i["id"] for i in run.next()["ready"]}
    out = run.tmp / "claims.json"
    out.write_text(json.dumps(base_answers(run, "std")["p0.claims"](None, 1), ensure_ascii=False), encoding="utf-8")
    terms = run.tmp / "terms.json"
    terms.write_text(json.dumps(base_answers(run, "std")["p0.terms"](None, 1), ensure_ascii=False), encoding="utf-8")
    return run, ids, out, terms


def test_read_through():
    """柵の本体を測る: 標本 3 本が親の転写の道具の結果に在るか（理由は rules の claims_intake が正本）。
    **部分読みが部分読みとして出ること**と、道具の結果以外（会話の地の文）を数えないことを見る。"""
    print("読了: 転写に文書の本文が入っているかを先頭・中間・末尾で見る")
    run, ids, out, terms = read_through_run("readthru")
    body = run.doc.read_text(encoding="utf-8")
    probes = dict(RESEARCH_RULES.read_probes(body)[0])   # **標本の取り方は rules が正本**（台本で写さない）
    # **印（この転写は回す側のものか）は engine のどの出力にも載る値でなければならない。**
    rid = run.state()["run_id"]
    check(rid in run.init.stdout and json.loads(run.cmd("status").stdout).get("run_id") == rid,
          f"init と status が run_id を言う（印が立つ口。{rid}）")
    # **next も言う。** 印が立つ口は 4 つ（init／next／status／done）で、**回す側が最も多く打つのは next**——
    # ここが落ちると、他の 3 つを打たない周では印が 1 つも立たない（柵は黙って不成立へ倒れる）
    check(json.loads(run.cmd("next").stdout).get("run_id") == rid,
          f"next も run_id を言う（回す側が最も多く打つ口。{rid}）")
    # **印に使えるのは直列化で綴りが変わらない値だけ。** 盤面のパスを印にしていたとき、engine の出力は
    # json.dumps を通るので Windows の区切りが二重化され、印が恒久的に一致せず柵が黙って通る側へ倒れた
    # （区切りが / の環境では実行の腕に出ないので、形で縛る）
    win = "C:\\repo\\.git\\graphloops\\research-loop\\20260919-101112"
    ser = dump({"dir": win, "run_id": "20260919-101112"})
    check(win not in ser and "20260919-101112" in ser,
          f"engine の直列化はパスの綴りを変えるが run_id は変えない（印に使えるのは後者。{ser[:40]}）")
    sess = lambda **kw: session_fixture(run.tmp, run.env, **kw)

    r = run.cmd("done", "--node", ids["p0.claims"], "--output", str(out), env=sess(text="何も読んでいない"))
    check(r.returncode == 1 and "親の転写の道具の結果に入っていない" in r.stderr and "先頭" in r.stderr,
          f"文書が親の転写に入っていない session は exit 1（欠けた位置を言う）: {r.stderr[-80:]}")
    check("見た転写" in r.stderr, f"拒否文が、見に行った転写のパスを言う（切り分けに要る）: {r.stderr[-60:]}")
    # **拒否文が復帰の手を言う。** 転写への書き込みは後追いなので、読みと done を同じ道具呼びに並べた回は
    # 実際に読んでいても拒まれる（実測: 代役は同期で書くのでこの形は台本に出ない）——言わないと同じ手を繰り返す
    check("次の手" in r.stderr, f"拒否文が『読んだ次の手で出し直せ』を言う（同じ手に並べた回の復帰）: {r.stderr[-60:]}")
    r = run.cmd("done", "--node", ids["p0.claims"], "--output", str(out), env=sess(text=probes["中間"]))
    check(r.returncode == 1 and "親の転写の道具の結果に入っていない" in r.stderr and "先頭" in r.stderr and "末尾" in r.stderr,
          f"中間しか読んでいない session も exit 1（欠けた 2 点を言う）: {r.stderr[-80:]}")
    # **探すのは道具の結果だけ**——会話の地の文まで探すと、本文を自分で書いた（写した）だけで通る。
    # engine がループの操作者の会話を読まない規律でもある。道具の結果は在る（別の出力）ので、
    # 「道具の結果が 1 つも無い」（別の腕）とは違う筋
    r = run.cmd("done", "--node", ids["p0.claims"], "--output", str(out),
                env=sess(text="別の道具の出力（文書とは無関係）", said=body))
    check(r.returncode == 1 and "親の転写の道具の結果に入っていない" in r.stderr,
          f"地の文に本文が在るだけでは通らない（探すのは道具の結果だけ）: {r.stderr[-80:]}")
    # **同じ 1 行に、道具の結果と・地の文と・engine が知らない型のブロックが並ぶ形。** 数えるブロックを
    # 型で絞っていないと、道具を通っていない本文（自分で書いた・別の型で運ばれた）まで数えて通る。
    # 別の行に置いた腕では前置フィルタが行ごと飛ばすので、型の柵はそこでは測れない
    r = run.cmd("done", "--node", ids["p0.claims"], "--output", str(out),
                env=sess(text="別の道具の出力（文書とは無関係）", said=body, said_inline=True))
    check(r.returncode == 1 and "親の転写の道具の結果に入っていない" in r.stderr,
          f"同じ 1 行でも、道具の結果でないブロックの本文は数えない（型を見る）: {r.stderr[-80:]}")
    r = run.cmd("done", "--node", ids["p0.claims"], "--output", str(out), env=sess(text=body))
    check(r.returncode == 0, f"全文が会話に入っていれば通る（control）: {r.stderr[-80:]}")
    check(f"run {rid}" in r.stdout, f"done の 1 行も run_id を言う（done だけを打った session でも印が立つ）: {r.stdout[-60:]}")
    check(not run.state().get("read_through_unchecked"), "確かめられた周には『確かめられなかった』の痕跡が付かない")
    # **同じ柵が p0.terms にも当たる**（同じ波の 2 節目。片方だけ post_check を外しても気づかない形にしない）
    r = run.cmd("done", "--node", ids["p0.terms"], "--output", str(terms), env=sess(text="何も読んでいない"))
    check(r.returncode == 1 and "親の転写の道具の結果に入っていない" in r.stderr,
          f"同じ柵が p0.terms にも当たる（読んでいない session は exit 1）: {r.stderr[-80:]}")
    rm(run.tmp)

    # **本文が配列で入る形も読む**（実物の道具の内訳は session_fixture の説明が正本）
    run2, ids2, out2, terms2 = read_through_run("readthru-list")
    r = run2.cmd("done", "--node", ids2["p0.claims"], "--output", str(out2),
                 env=session_fixture(run2.tmp, run2.env, text=run2.doc.read_text(encoding="utf-8"), as_list=True))
    # **通ったことだけを見ない**——配列の腕を殺すと道具の結果が 0 件に見え、「確かめられない」側で
    # やはり通る。見つけたのか見つけられなかったのかは痕跡で分かれる
    check(r.returncode == 0 and not run2.state().get("read_through_unchecked"),
          f"道具の結果が配列の形でも本文は見つかる（痕跡なしで通る。{r.stderr[-80:]}）")
    # **実物の Read は各行に行番号＋タブを付ける**（照合は部分一致なので通るはず。行の一致に変えた周に赤くなる）
    r = run2.cmd("done", "--node", ids2["p0.terms"], "--output", str(terms2),
                 env=session_fixture(run2.tmp, run2.env, text=run2.doc.read_text(encoding="utf-8"), numbered=True))
    check(r.returncode == 0 and not run2.state().get("read_through_unchecked"),
          f"行番号＋タブの接頭が付く形（実物の Read）でも本文は見つかる（{r.stderr[-80:]}）")
    rm(run2.tmp)

    # **文書そのものが読めない回は拒む**（init のあとで消された・移された）。不成立へ倒すと、
    # 文書を消せば柵が黙る形になる——痕跡が付かないことまで見る
    run3, ids3, out3, _ = read_through_run("readthru-gone")
    run3.doc.unlink()
    r = run3.cmd("done", "--node", ids3["p0.claims"], "--output", str(out3),
                 env=session_fixture(run3.tmp, run3.env, text="何も読んでいない"))
    check(r.returncode == 1 and "読めない" in r.stderr and not (run3.state().get("read_through_unchecked") or []),
          f"見立て文書が消えた回は拒む（不成立で通さない。rc={r.returncode}: {r.stderr[-90:]}）")
    rm(run3.tmp)


def test_read_through_hidden_sinks():
    """**判定は本文の在処だけで下す。** 本文が親の転写の外に落ちる形（大きい結果の外出し・subagent の
    別の転写）は、engine からは『読んでいない』と区別が付かないので拒む——置き場が在るかで通していた
    とき、文書と無関係な subagent を 1 つ起こした session では柵が二度と不合格を出さなくなった。
    拒否文は**読み直し方**を場合ごとに言う（自分で読む／大きい結果は分けて読む）。
    """
    print("読了: 置き場が在るかでは通さない（判定は本文の在処だけ。拒否文が読み直し方を言う）")
    run, ids, out, terms = read_through_run("readthru-sink")
    body = run.doc.read_text(encoding="utf-8")
    r = run.cmd("done", "--node", ids["p0.claims"], "--output", str(out),
                env=session_fixture(run.tmp, run.env, text=body, externalized=True))
    check(r.returncode == 1 and "分けて読む" in r.stderr,
          f"外出しで親の転写に抜粋しか残らない回は拒み、読み直し方を言う（rc={r.returncode}: {r.stderr[-90:]}）")
    r = run.cmd("done", "--node", ids["p0.claims"], "--output", str(out),
                env=session_fixture(run.tmp, run.env, text=body, subagent=True))
    check(r.returncode == 1 and "自分で読み直せ" in r.stderr,
          f"subagent に読ませた回も拒み、自分で読み直せと言う（rc={r.returncode}: {r.stderr[-90:]}）")
    # **置き場が在るだけでは通さない。** 本文はどこにも無い（無関係な subagent を 1 つ起こしただけ）の形
    r = run.cmd("done", "--node", ids["p0.claims"], "--output", str(out),
                env=session_fixture(run.tmp, run.env, text="無関係な出力", subagent=True))
    check(r.returncode == 1 and "親の転写の道具の結果に入っていない" in r.stderr,
          f"置き場は在るが本文がどこにも無い session は拒む（rc={r.returncode}: {r.stderr[-90:]}）")
    # 置き場が在っても、親の転写に本文が在れば通る（手がかりは判定に効かない）
    r = run.cmd("done", "--node", ids["p0.claims"], "--output", str(out),
                env=session_fixture(run.tmp, run.env, text=body, subagent=True, parent_body=True))
    check(r.returncode == 0 and not run.state().get("read_through_unchecked"),
          f"置き場が在っても、親の転写に本文が在れば通る（rc={r.returncode}: {r.stderr[-90:]}）")
    rm(run.tmp)


def test_read_through_positions():
    """**射程（3 標本が挟む区間が本文を覆う割合）を直に測る。** 標本を「長さの下限を満たす行」の中から
    位置で選んでいたとき、下限に満たない行だけが並ぶ区間——箇条書き・表で終わる末尾、長い行を持たない
    中ほど——は何行あっても射程の外に残り、前半だけ読んだ回が通った（実測 2026-09-19）。
    射程外が残る文書は**不成立**（確かめられない）として痕跡を残し、射程に入る文書では中間・末尾の
    標本が本当に中ほど・末尾を指す（＝そこまで読まないと拒まれる）ことを見る。"""
    print("読了: 射程外が残る文書は不成立として残り、射程に入る文書は中間・末尾が欠ければ拒む")
    run, ids, out, terms = read_through_run("readthru-pos")
    # 前半は長い散文、後半 30 行は標本にできない短い箇条書き（PROBE_MIN 未満）で終わる文書
    head = "この見立て文書の冒頭の一文は、読了の確かめの標本として文書の先頭から取られる行である。\n"
    mid = "この見立て文書の中ほどの一文は、読了の確かめの標本として文書の中間から取られる行である。\n"
    tail = "この見立て文書の末尾に近い一文は、読了の確かめの標本として文書の末尾から取られる行である。\n"
    short = "".join(f"- 短 {i}\n" for i in range(30))
    check(all(len(ln.strip()) < PROBE_MIN for ln in short.splitlines()), "後ろ 30 行は標本にできない長さ（下限は rules が正本）")
    run.doc.write_text(f"# 見立て\n\n{head}\n{mid}\n{tail}{short}", encoding="utf-8")
    body = run.doc.read_text(encoding="utf-8")
    # **全文を読んでいても通さない**——標本が挟めない区間が残る文書では、読了を確かめたと言えない
    r = run.cmd("done", "--node", ids["p0.claims"], "--output", str(out),
                env=session_fixture(run.tmp, run.env, text=body))
    left = run.state().get("read_through_unchecked") or []
    check(r.returncode == 0 and left and "残る" in left[-1]["why"] and "%" in left[-1]["why"],
          f"射程外が残る文書は、全文を読んだ回でも不成立として量を残す（rc={r.returncode} / {left[-1]['why'][:40] if left else None}）")
    rm(run.tmp)

    # **射程に入る文書では、中間も末尾も文書の中の位置どおりを指す。** 標本を長い行だけから選んでいた
    # とき、後ろに続く短めの行の区間（表・箇条書き・参考文献）は射程の外で、そこを読まずに通った
    run2, ids2, out2, terms2 = read_through_run("readthru-tailtable")
    long_tail = ("# 見立て\n\n"
                 "冒頭の一文は、読了の確かめの標本として文書の先頭から取られる行であり長さも足りている。\n\n"
                 "中ほどの一文は、読了の確かめの標本として文書の中間から取られる行であり長さも足りている。\n\n"
                 "末尾の長い一文は、読了の確かめのために置かれた行であり長さも足りている。\n")
    table = "".join(f"| 行 {i} | 値 {i} | 備考 {i} |\n" for i in range(30))
    run2.doc.write_text(long_tail + table, encoding="utf-8")
    picked = dict(RESEARCH_RULES.read_probes(long_tail + table)[0])
    check(picked["中間"] in table and picked["末尾"] in table,
          f"中間・末尾の標本はどちらも後ろの表の中から取られる（中間: {picked['中間'][:12]} / 末尾: {picked['末尾'][:12]}）")
    r = run2.cmd("done", "--node", ids2["p0.claims"], "--output", str(out2),
                 env=session_fixture(run2.tmp, run2.env, text=long_tail))
    check(r.returncode == 1 and "中間" in r.stderr and "末尾" in r.stderr,
          f"長い行まで読んで止めた回は、後ろの表が欠けて拒まれる（rc={r.returncode}: {r.stderr[-90:]}）")
    # 表の前半（中間の標本の所）まで読んでも、末尾の標本に届かなければ拒む
    r = run2.cmd("done", "--node", ids2["p0.claims"], "--output", str(out2),
                 env=session_fixture(run2.tmp, run2.env, text=long_tail + table[:table.index(picked["末尾"])]))
    check(r.returncode == 1 and "末尾" in r.stderr and "中間" not in r.stderr,
          f"表の途中まででは末尾だけが欠けて拒まれる（rc={r.returncode}: {r.stderr[-90:]}）")
    r = run2.cmd("done", "--node", ids2["p0.claims"], "--output", str(out2),
                 env=session_fixture(run2.tmp, run2.env, text=long_tail + table))
    check(r.returncode == 0 and not run2.state().get("read_through_unchecked"),
          f"表まで読んでいれば痕跡なしで通る（control。{r.stderr[-80:]}）")
    rm(run2.tmp)

    # **中ほどに標本にできる行が無い文書も不成立。** 射程の外（先頭の前・末尾の後ろ）は無いのに、
    # 中間の標本が中ほどを指せない形——中ほどを読まずに先頭と末尾だけ見た回と区別が付かない
    run3, ids3, out3, _ = read_through_run("readthru-midgap")
    gap = "".join(f"- 短 {i}\n" for i in range(40))
    run3.doc.write_text(f"{head}\n{gap}\n{tail}", encoding="utf-8")
    r = run3.cmd("done", "--node", ids3["p0.claims"], "--output", str(out3),
                 env=session_fixture(run3.tmp, run3.env, text=run3.doc.read_text(encoding="utf-8")))
    left = run3.state().get("read_through_unchecked") or []
    check(r.returncode == 0 and left and "中ほど" in left[-1]["why"],
          f"中ほどに標本にできる行が無い文書は不成立として残る（rc={r.returncode} / {left[-1]['why'][:40] if left else None}）")
    rm(run3.tmp)


def test_read_through_scanned_once():
    """**同じ周に同じ物を 2 度走査しない。** 確かめは同じ波の 2 節に付いており、転写は単調に育つので
    拒否が続く周ほど全走査が重くなる（実測: 36.9 MB で 3.86 秒 × 2 節）。柵は両方の節に当て続けたまま、
    2 度目は盤面に残した結果を読む。**鍵は「何を確かめたか」**——文書や session が差し替わったら読み直す。"""
    print("読了: 同じ周・同じ文書・同じ転写なら走査は 1 回（差し替わったら読み直す）")
    run, ids, out, terms = read_through_run("scan-once")
    body = run.doc.read_text(encoding="utf-8")
    env = session_fixture(run.tmp, run.env, text=body)
    r = run.cmd("done", "--node", ids["p0.claims"], "--output", str(out), env=env)
    check(r.returncode == 0, f"1 節目は実際に走査して通る（{r.stderr[-70:]}）")
    memo = json.loads((run.dir / "read-through.json").read_text(encoding="utf-8"))
    check(memo.get("scope") and memo["scope"][0] == 1,
          f"確かめた範囲（周・文書・大きさ・転写）が盤面の外の写しに残る（{memo.get('scope')}）")
    # **2 節目は走査しない**——転写の綴りはそのまま、中身だけ本文を含まない物に置き換える。
    # 走査していれば「親の転写の道具の結果に入っていない」で拒まれる（＝通れば読んでいない証拠）
    tr = next(pathlib.Path(env["CLAUDE_CONFIG_DIR"]).glob("projects/*/*.jsonl"))
    tr.write_text(json.dumps({"message": {"content": [{"type": "tool_result", "content": "本文は入っていない"}]}},
                             ensure_ascii=False) + "\n", encoding="utf-8")
    r = run.cmd("done", "--node", ids["p0.terms"], "--output", str(terms), env=env)
    check(r.returncode == 0 and not (run.state().get("read_through_unchecked") or []),
          f"同じ周・同じ文書・同じ転写なら 2 節目は盤面の結果を読む（中身が変わっても走査しない。rc={r.returncode}）")
    rm(run.tmp)

    # **写しに当たっても、その節の出力から出る一言は出る。** 早期 return にしていたとき、
    # 確かめの結果と一緒に節ごとの導線（開いた問いを deep-research へ渡す一文）まで消えた
    # ——**p0.terms を先に done した周**は、開いた問いを持つ p0.claims が写しに当たり、導線が 1 度も出なかった
    run4, ids4, out4, terms4 = read_through_run("scan-open")
    body4 = run4.doc.read_text(encoding="utf-8")
    env4 = session_fixture(run4.tmp, run4.env, text=body4)
    ans4 = base_answers(run4, "open")["p0.claims"](None, 1)
    check(ans4.get("open_questions"), "筋書き 'open' は開いた問いを持つ（この腕の前提）")
    out4.write_text(json.dumps(ans4, ensure_ascii=False), encoding="utf-8")
    terms4.write_text(json.dumps(base_answers(run4, "open")["p0.terms"](None, 1), ensure_ascii=False), encoding="utf-8")
    r = run4.cmd("done", "--node", ids4["p0.terms"], "--output", str(terms4), env=env4)   # **先に terms**
    check(r.returncode == 0, f"先に p0.terms を出しても通る（{r.stderr[-60:]}）")
    r = run4.cmd("done", "--node", ids4["p0.claims"], "--output", str(out4), env=env4)    # 写しに当たる側
    check(r.returncode == 0 and "開いた問いがある" in r.stdout and "deep-research" in r.stdout,
          f"写しに当たった節でも、開いた問いの導線は出る（rc={r.returncode}: {r.stdout.strip()[:80]}）")
    rm(run4.tmp)

    # **拒否は写さない。** 一度は「拒む回こそ重いから写す」と入れたが、実走で主経路が壊れた
    # （実測 2026-09-21: 文書を読んでから出し直しても、同じ周では写しが先に拒み続けた）。
    # 拒否の直後に回す側がすることはまさに『読んでもう一度出す』で、その回は読み直さなければならない
    run3, ids3, out3, terms3 = read_through_run("scan-reject")
    body3 = run3.doc.read_text(encoding="utf-8")
    env3 = session_fixture(run3.tmp, run3.env, text="何も読んでいない")
    r = run3.cmd("done", "--node", ids3["p0.claims"], "--output", str(out3), env=env3)
    check(r.returncode == 1, f"1 節目は走査して拒む（{r.stderr[-60:]}）")
    check(not (run3.dir / "read-through.json").is_file(),
          "拒んだ回は写しを残さない（残すと、読んでからの出し直しが同じ周ずっと塞がる）")
    tr3 = next(pathlib.Path(env3["CLAUDE_CONFIG_DIR"]).glob("projects/*/*.jsonl"))
    tr3.write_text(json.dumps({"message": {"content": [{"type": "tool_result", "content": body3}]}},
                              ensure_ascii=False) + "\n", encoding="utf-8")   # 読んだ形に差し替える
    r = run3.cmd("done", "--node", ids3["p0.claims"], "--output", str(out3), env=env3)
    check(r.returncode == 0,
          f"読んだあとの出し直しは同じ周でも通る（写しに塞がれない。rc={r.returncode}: {r.stderr[-70:]}）")
    rm(run3.tmp)

    # **文書が差し替わったら読み直す**（周だけを鍵にすると、確かめていない物を確かめた扱いにする）
    run2, ids2, out2, terms2 = read_through_run("scan-again")
    body2 = run2.doc.read_text(encoding="utf-8")
    r = run2.cmd("done", "--node", ids2["p0.claims"], "--output", str(out2),
                 env=session_fixture(run2.tmp, run2.env, text=body2))
    check(r.returncode == 0, f"1 節目は通る（{r.stderr[-70:]}）")
    run2.doc.write_text(body2 + "\nこの行はこの周の途中で足された、まだ会話に入っていない一文である。\n",
                        encoding="utf-8")
    r = run2.cmd("done", "--node", ids2["p0.terms"], "--output", str(terms2),
                 env=session_fixture(run2.tmp, run2.env, text=body2))
    check(r.returncode == 1 and "親の転写の道具の結果に入っていない" in r.stderr,
          f"文書が差し替わったら読み直して拒む（使い回さない。rc={r.returncode}: {r.stderr[-70:]}）")
    rm(run2.tmp)


def test_read_through_naming():
    """**名乗りと実装が同じことを言う。** プロンプト 2 枚は、engine が拒む形（subagent に読ませた・
    大きすぎて外出しされた）を『記録に残すだけ』と書いてはいけない——回す側がそう読んで subagent に
    読ませ、done が exit 1 で落ちてから仕様を読み直すことになる（実測 2026-09-19 に 1 枚がそうなっていた）。"""
    print("読了: プロンプト 2 枚の名乗りが、拒む形を『記録に残すだけ』と書いていない／手順書が柵の前提を書く")
    # **回す側に見える面にも前提を書く。** 柵は「engine を回した出力が転写に載る」を前提にするが、
    # この差分自身の目的（回す側に渡る量を減らす）に沿って出力をファイルへ落とすと、その前提が崩れて
    # 確かめが恒常的に成立しなくなる——回す側がそれを知らずに節約すると、柵は黙って効かなくなる
    cmd = (PLUGIN / "commands" / "research-graph.md").read_text(encoding="utf-8")
    check("engine の出力を会話から外さない" in cmd and "確かめられなかった" in cmd,
          "手順書が『engine の出力を会話から外すと読了の確かめが成立しない』を書く")
    check("engine を回した出力が会話に残らない場から回すと確かめは成立しない" in cmd,
          "手順書が、成立しない条件を『出力が会話に残るか』で書く（誰が回したか、ではない）")
    # **名乗りが engine の射程を越えない。** engine は転写の由来（親か下請けか）を判定する材料を
    # 1 つも読まないのに、名乗りは『subagent なら成立しない』と機構の保証として言い切っていた——
    # その 1 文を根拠に、2 周続けて『subagent でも通るか』の検証に周が費やされた（実測 r6・r7）
    for name, txt in (("commands/research-graph.md", cmd),
                      ("prompts/research-loop/p0.claims.md",
                       (PLUGIN / "prompts" / "research-loop" / "p0.claims.md").read_text(encoding="utf-8")),
                      ("prompts/research-loop/p0.terms.md",
                       (PLUGIN / "prompts" / "research-loop" / "p0.terms.md").read_text(encoding="utf-8"))):
        check("親の session から回せ" not in txt,
              f"{name} が『親の session から回せ』（engine が由来を判定するかのような名乗り）を言わない")
    # 射程の正本は rules の 1 か所（名乗りはそこから導く）。正本が消えたら、導いている側の根拠も消える
    rules_src = (PLUGIN / "rules" / "research-loop.py").read_text(encoding="utf-8")
    check("射程の正本はここ 1 か所" in rules_src and "engine は判定していない" in rules_src,
          "engine が確かめている射程の正本が rules に 1 か所在り、由来を判定していないと明記する")
    # **配置の説明（回す側そのものが subagent なら確かめは成立しない）の正本は手順書 1 枚**——同じ波で
    # 2 枚が同時に回す側の文脈へ入るので、機構の説明は p0.claims.md 側だけに置く（渡る量を増やさない）
    claims = (PLUGIN / "prompts" / "research-loop" / "p0.claims.md").read_text(encoding="utf-8")
    terms = (PLUGIN / "prompts" / "research-loop" / "p0.terms.md").read_text(encoding="utf-8")
    check("この run を回した出力（run_id）" in claims and "run_id" not in terms and "後追い" in claims,
          "確かめの射程の説明は p0.claims.md 側だけに在る（p0.terms.md は操作の指示だけ）")
    for name in ("p0.claims.md", "p0.terms.md"):
        txt = (PLUGIN / "prompts" / "research-loop" / name).read_text(encoding="utf-8")
        seg = [ln for ln in txt.splitlines() if "subagent" in ln]
        check(seg and all("拒" in ln or "自分で読" in ln for ln in seg),
              f"{name} は subagent の回を『拒む／自分で読め』と書く（記録に残すだけ、と書かない）: {seg[:1]}")
        check("確かめられなかったこととして記録に残す" not in txt,
              f"{name} に、拒む形を不成立と読める一文が無い")
        # **読んだ次の手で返せ、を両方が言う。** 言わないと、読みと返答を同じ道具呼びに並べた役が
        # 拒まれて読み方を疑い、同じ手を繰り返す（実物の転写は後追いで書かれる）
        check("次の手" in txt, f"{name} が、読んだ次の手で返せと書く")


def test_read_through_unevaluable():
    """**確かめられないときは、赤でも緑でもなく「不成立」。** 転写の形が変わった・標本が取れない・
    転写が 1 つに決まらない——どれも「読んでいない」とは別物で、黙って通すと柵が空振りしていることが
    誰にも見えない。通しつつ理由を盤面に積み、記録と報告に出す。"""
    print("読了: 確かめられない経路は、通すが理由を盤面に残す（件数は台本に写さない）")
    # 転写に道具の結果が 1 つも無い（形が変わった疑い）
    run, ids, out, terms = read_through_run("readthru-noresult")
    body = run.doc.read_text(encoding="utf-8")
    r = run.cmd("done", "--node", ids["p0.claims"], "--output", str(out),
                env=session_fixture(run.tmp, run.env, said=body, marked=False))   # 道具の結果を 1 つも作らない形
    left = run.state().get("read_through_unchecked") or []
    check(r.returncode == 0 and left and "道具の結果が 1 つも無い" in left[-1]["why"],
          f"道具の結果が 1 つも無い転写は不成立として通り、理由が残る（rc={r.returncode} / {[x['why'][:24] for x in left[-1:]]}）")
    # **理由は done の 1 行にも出る。** 盤面にしか積まなかったとき、柵が空振りした回と確かめられた回が
    # 周の途中では同じに見えた（記録を開くまで誰も気づけない）——盤面の痕跡とは別の口として測る
    check("読了は確かめられなかった" in r.stdout and "道具の結果が 1 つも無い" in r.stdout,
          f"不成立の理由が done の 1 行にも出る（{r.stdout.strip()[:60]}）")
    # 標本が取れない文書（PROBE_MIN 字以上の行が無い）——同じ run の 2 節目で測る
    run.doc.write_text("# 見立て\n\n短い行だけ。\n", encoding="utf-8")
    r = run.cmd("done", "--node", ids["p0.terms"], "--output", str(terms),
                env=session_fixture(run.tmp, run.env, text=body))
    left = run.state().get("read_through_unchecked") or []
    check(r.returncode == 0 and "行が 1 つも無い" in left[-1]["why"],
          f"標本に使える行が無い文書は不成立として通り、理由が残る（rc={r.returncode} / {left[-1]['why'][-24:]}）")
    rm(run.tmp)

    # 転写が複数見つかる（別プロジェクト配下の同名を機械で選ばない）
    run2, ids2, out2, terms2 = read_through_run("readthru-dup")
    r = run2.cmd("done", "--node", ids2["p0.claims"], "--output", str(out2),
                 env=session_fixture(run2.tmp, run2.env, text=run2.doc.read_text(encoding="utf-8"), dup=True))
    left = run2.state().get("read_through_unchecked") or []
    check(r.returncode == 0 and left and "決められない" in left[-1]["why"],
          f"転写が 2 つ見つかる session は不成立として通り、理由が残る（rc={r.returncode} / {left[-1]['why'][:30] if left else None}）")
    # 標本が同じ行に潰れる文書（長い行が 1 種しか無い）——3 点の標本にならないので不成立
    run2.doc.write_text("# 見立て\n\n" + "この見立て文書には、標本に使える長さの行がこの 1 種類しか無いので、3 点の標本が同じ行に潰れる。\n" * 3,
                        encoding="utf-8")
    r = run2.cmd("done", "--node", ids2["p0.terms"], "--output", str(terms2),
                 env=session_fixture(run2.tmp, run2.env, text="何も読んでいない"))
    left = run2.state().get("read_through_unchecked") or []
    check(r.returncode == 0 and "同じ行になる" in left[-1]["why"],
          f"標本が同じ行に潰れる文書は不成立として通り、理由が残る（rc={r.returncode} / {left[-1]['why'][-26:]}）")
    rm(run2.tmp)

    # **転写が回す側のものでない形**（回す側そのものが subagent／engine の出力をファイルへ落とした配置）。
    # engine を回せば盤面のパスが道具の結果として必ず載るので、印が 1 つも無い転写に標本が無くても
    # 「読んでいない」とは言えない——**不合格にすると、その配置には柵を切る以外の出口が無くなる**
    run3, ids3, out3, terms3 = read_through_run("readthru-nomark")
    r = run3.cmd("done", "--node", ids3["p0.claims"], "--output", str(out3),
                 env=session_fixture(run3.tmp, run3.env, text="別の道具の出力（この run の物ではない）", marked=False))
    left = run3.state().get("read_through_unchecked") or []
    check(r.returncode == 0 and left and "この run を回した出力" in left[-1]["why"]
          and "engine を回した出力が会話に残る場から回し直せ" in left[-1]["why"],
          f"この run の印が無い転写は不成立として通り、出力が会話に残る場から回せと言う（rc={r.returncode} / {left[-1]['why'][:36] if left else None}）")
    # **印が在れば今までどおり拒む**（印は出口を開けるだけで、読んでいない回を通す口ではない）
    r = run3.cmd("done", "--node", ids3["p0.terms"], "--output", str(terms3),
                 env=session_fixture(run3.tmp, run3.env, text="何も読んでいない"))
    check(r.returncode == 1 and "親の転写の道具の結果に入っていない" in r.stderr,
          f"印が在る転写では、読んでいない回は今までどおり拒まれる（rc={r.returncode}: {r.stderr[-70:]}）")
    rm(run3.tmp)

    # **印はパスではない。** engine の出力は json.dumps を通るので、パスを印にすると Windows の区切りが
    # 二重化されて印が恒久的に一致せず、柵が黙って通る側へ倒れる（区切りが / の環境では実行の腕に出ない）。
    # 盤面のパスだけが載った転写で印が立たないことを見て、印がパスでないことを実行の側から縛る
    run5, ids5, out5, _ = read_through_run("readthru-dirmark")
    r = run5.cmd("done", "--node", ids5["p0.claims"], "--output", str(out5),
                 env=session_fixture(run5.tmp, run5.env, text="別の道具の出力", mark_dir_only=True))
    left = run5.state().get("read_through_unchecked") or []
    check(r.returncode == 0 and left and "この run を回した出力" in left[-1]["why"],
          f"盤面のパスだけが載った転写では印は立たない（印は run_id。rc={r.returncode} / {left[-1]['why'][:30] if left else None}）")
    rm(run5.tmp)

    # **標本は全部そろい、印だけが無い形。** 以前はここが if/elif の連鎖のどの条件にも当たらず、
    # **印を一度も見ずに合格**していた——3 標本が親の転写の別の道具の結果にたまたま在れば通る経路で、
    # 名乗り（印は転写が回す側のものかを確かめるため）と食い違っていた
    run6, ids6, out6, _ = read_through_run("readthru-nomarkfull")
    r = run6.cmd("done", "--node", ids6["p0.claims"], "--output", str(out6),
                 env=session_fixture(run6.tmp, run6.env, text=run6.doc.read_text(encoding="utf-8"), marked=False))
    left = run6.state().get("read_through_unchecked") or []
    check(r.returncode == 0 and left and "標本はそろったが" in left[-1]["why"],
          f"標本がそろっても印が無い回は不成立として通り、理由が残る（rc={r.returncode} / {left[-1]['why'][:34] if left else None}）")
    rm(run6.tmp)

    # **転写は見つかるが開けない形**——探した直後に読めない回が 3 値の外（素の例外）へ抜けない
    run4, ids4, out4, _ = read_through_run("readthru-unreadable")
    r = run4.cmd("done", "--node", ids4["p0.claims"], "--output", str(out4),
                 env=session_fixture(run4.tmp, run4.env, text=run4.doc.read_text(encoding="utf-8"), unreadable=True))
    left = run4.state().get("read_through_unchecked") or []
    check(r.returncode == 0 and left and "開けない" in left[-1]["why"] and "Traceback" not in r.stderr,
          f"転写が開けない回は不成立として通り、理由が残る（rc={r.returncode} / {left[-1]['why'][:40] if left else None}）")
    rm(run4.tmp)


def test_open_questions_note():
    """**新しく足した結合を、台本が一度も踏んでいない形にしない。** 読了の不成立の理由と
    『開いた問いがある』を ' / ' で結ぶ経路は、open_questions を非空にする筋書きが台本に無く、
    一度も実行されていなかった（結合の結果が誰の目にも出ない＝壊しても赤くならない）。"""
    print("台本: 開いた問いがある周は、その旨が done の 1 行に出る（読了の不成立と併記される）")
    run, ids, out, terms = read_through_run("openq")
    body = run.doc.read_text(encoding="utf-8")
    ans = base_answers(run, "open")["p0.claims"](None, 1)
    check(ans.get("open_questions"), "筋書き 'open' は開いた問いを持つ（この腕の前提）")
    out.write_text(json.dumps(ans, ensure_ascii=False), encoding="utf-8")
    # ① 読了が通った回: 開いた問いの一言だけが出る
    r = run.cmd("done", "--node", ids["p0.claims"], "--output", str(out),
                env=session_fixture(run.tmp, run.env, text=body))
    check(r.returncode == 0 and "開いた問いがある" in r.stdout and "deep-research" in r.stdout,
          f"開いた問いは done の 1 行に出る（rc={r.returncode}: {r.stdout.strip()[:90]}）")
    check("読了は確かめられなかった" not in r.stdout, "読了が通った回に不成立の文は出ない")
    # ② 読了が不成立の回: 2 つが ' / ' で結ばれる（この結合が一度も踏まれていなかった）
    terms.write_text(json.dumps(base_answers(run, "open")["p0.terms"](None, 1), ensure_ascii=False), encoding="utf-8")
    noenv = {k: v for k, v in run.env.items() if k != "CLAUDE_CODE_SESSION_ID"}
    r = run.cmd("done", "--node", ids["p0.terms"], "--output", str(terms), env=noenv)
    check(r.returncode == 0 and "読了は確かめられなかった" in r.stdout,
          f"読了の不成立も同じ 1 行に出る（rc={r.returncode}: {r.stdout.strip()[:90]}）")
    rm(run.tmp)


def converge_reasons(run):
    """節 converge の返りの reason を周の順に（engine が trace の builtin の行に残す物を読む。収集の経路を新設しない）。"""
    rows = [json.loads(x) for x in (run.dir / "trace.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()]
    return [r["result"].get("reason", "") for r in rows if r.get("op") == "builtin" and r.get("node") == "converge"]


def test_open_questions_unresolved():
    """**開いた問いを残した収束を『調べ尽くした』と読ませない。** 開いた問いは収束を止めない（待たない設計）が、
    以前は収束の文言が『連続 N 周で新規相違ゼロ』とだけ言い、報告の指示書にも開いた問いを並べる義務が無かった
    ——記録の process.open_questions は書かれるだけで、依頼者に届く口のどこにも出なかった。"""
    print("台本: 開いた問いを残して収束した run は、収束の文言が分かれ、報告の指示書に問いが並ぶ")
    run = Run("openq-conv")
    last = drive(run, "open")
    rec = run.record()
    q = base_answers(run, "open")["p0.claims"](None, 1)["open_questions"]
    check(last["status"] == "converged" and rec["process"].get("open_questions") == q,
          f"開いた問いが残っても収束は止まらない（{last['status']}・{rec['process'].get('open_questions')}）")
    why = (converge_reasons(run) or [""])[-1]
    check("閉じた主張の検証は収束した" in why and f"開いた問い {len(q)} 件" in why and "未解決" in why and q[0] in why,
          f"収束の文言が『閉じた主張の検証は収束』と『開いた問いは未解決』を分けて言う: {why[:120]}")
    prompts = sorted(run.dir.glob("prompts/r*/report.md"))
    body = prompts[-1].read_text(encoding="utf-8") if prompts else ""
    check("未解決の開いた問い" in body and q[0] in body,
          f"報告の指示書が未解決の開いた問いを本文ごと並べさせる（{len(body)} バイト）")
    rm(run.tmp)


def test_threshold_boundaries():
    """**閾値の比較は、境界ちょうどで測る。** 3 つの比較（標本に使える行の下限・射程の外に残る量・
    扇の項目を items/ へ出す大きさ）はどれも閾値から遠い材料しか踏んでおらず、`>` と `>=` を
    取り違えても検査の色が変わらなかった。境界の 1 つ内側・ちょうど・1 つ外側の 3 点で縛る。"""
    print("否定検査: 3 つの閾値を、境界の 1 つ内側・ちょうど・1 つ外側で測る")
    from engine.advance import ITEM_INLINE, slim_item  # noqa: E402 — 部品を直に呼ぶ腕
    # ① 標本に使える行の下限（len(ln) >= PROBE_MIN）——ちょうどの長さは「使える」側
    def usable(n):
        # 相異なる行にする（同じ行が 3 本だと「標本が同じ行に潰れる」別の理由で落ち、下限を測れない）
        body = "\n\n".join(f"{i}" + "あ" * (n - 1) for i in range(3))
        return RESEARCH_RULES.read_probes(body)[0]
    check(not usable(PROBE_MIN - 1), f"下限より 1 字短い行は標本に使えない（{PROBE_MIN - 1} 字）")
    check(usable(PROBE_MIN), f"下限ちょうどの行は標本に使える（{PROBE_MIN} 字。>= と > の取り違えがここで出る）")
    # ② 射程の外に残る量（(before + after) * 100 > total * (100 - COVER_MIN_PCT)）——ちょうどは「通る」側。
    #    標本に使えない短い行で本文を挟み、外に残る字数を 1 字単位で狙う（本文 120 字・許容 5% ＝ 6 字）
    def outside(head, tail, mid_len=38, n=3):
        lines = ["あ" * head] + [f"{i}" + "い" * (mid_len - 1) for i in range(n)] + ["う" * tail]
        return RESEARCH_RULES.read_probes("\n\n".join(lines))
    probes, why = outside(3, 3)
    check(probes and why is None, f"射程の外がちょうど許容ぴったり（本文 120 字の 5%＝6 字）なら通る（{why}）")
    probes, why = outside(3, 4)
    check(not probes and why and "7 字" in why,
          f"許容を 1 字超えたら不成立になり、外に残った量を字数で言う（> と >= の取り違えがここで出る: {why}）")
    # ③ 扇の項目を items/ へ出す大きさ（len(dump(slim)) > ITEM_INLINE）——ちょうどは「残す」側
    def slim_len(pad):
        item = {"key": "K", "v": "x" * pad}
        slim, omitted = slim_item(item)
        return len(dump(slim).encode("utf-8")), omitted
    pad = 1
    while slim_len(pad)[0] < ITEM_INLINE:
        pad += 1
    n, omitted = slim_len(pad)
    check(n == ITEM_INLINE and not omitted,
          f"上限ちょうどの項目は落とさない（{n} バイト・落とした欄 {omitted}。> と >= の取り違えがここで出る）")
    n2, omitted2 = slim_len(pad + 1)
    check(omitted2 == ["v"], f"上限を 1 バイト超えた項目は落とす（{n2} バイト・落とした欄 {omitted2}）")


def test_item_file_relative_migration():
    """**保存済みの相対の綴りを持つ盤面も開ける。** 置き場の綴りを入口で絶対化した周に、既に走っていた
    run は item_file に相対を持ったまま残った——別の cwd から next を打つと read_json が die して、
    その run はどの周にも進めなくなる（新規だけ直して移行を置かない形）。"""
    print("台本: item_file が相対の盤面も、盤面の綴りを基準に開いて絶対へ直す")
    _td, tmp = parallel.workspace("gl-item-")
    (tmp / "items" / "r1").mkdir(parents=True)
    (tmp / "items" / "r1" / "x.json").write_text(json.dumps({"key": "K", "v": 1}, ensure_ascii=False), encoding="utf-8")
    from engine.advance import load_item  # noqa: E402 — 部品を直に呼ぶ腕
    # **engine が実際に書く綴りを食わせる**（`str(b.dir / "items" / f"r{round}" / …)`）。
    # 台本が engine の書かない綴り（盤面の根からの相対）を食わせていたとき、救済は台本でだけ効いて
    # 実物では必ず外れていた（実測 r9）——**腕の入力は engine の出力から取る**
    inst = {"item_file": str(pathlib.Path("state") / "items" / "r1" / "x.json")}
    got = load_item(inst, tmp)
    check(got == {"key": "K", "v": 1}, f"engine の書く綴り（盤面の綴りを含む相対）でも盤面から開ける（{got}）")
    check(pathlib.Path(inst["item_file"]).is_absolute(),
          f"開けたら綴りを絶対に直して書き戻す（救い続ける経路を残さない: {inst['item_file']}）")
    got2 = load_item(inst)            # 基準無しでも開ける（直った後）
    check(got2 == {"key": "K", "v": 1}, "直したあとは基準無しでも開ける")
    rm(tmp)


def test_transcript_non_dict_line():
    """転写の 1 行が **dict でない JSON**（配列・スカラ）でも、3 値の外（素の例外）へ抜けない。

    前置フィルタは素の部分一致なので、`"tool_result"` の語を含むだけの非 dict 行もそのまま読み手に届く
    （ハーネスは行の形を足しうる）。dict を前提に `.get` していると、その 1 行で done が traceback に化ける。"""
    print("読了: dict でない転写の行が来ても素の例外にならない")
    run, ids, out, _ = read_through_run("readthru-scalar")
    r = run.cmd("done", "--node", ids["p0.claims"], "--output", str(out),
                env=session_fixture(run.tmp, run.env, text=run.doc.read_text(encoding="utf-8"), scalar_line=True))
    check(r.returncode == 0 and "Traceback" not in r.stderr and not (run.state().get("read_through_unchecked") or []),
          f"dict でない行が混じっても通過の判定は変わらない（rc={r.returncode}: {r.stderr[-70:]}）")
    rm(run.tmp)


def test_unchecked_blocks_convergence():
    """**収束する周に、柵が成立していなければ収束を宣言しない。**

    これは収束の条件そのものに入っていなければ意味がない——前の周は同じ判断を asks の側に置いたが、
    asks は収束しない周にしか組み立てられないので、**収束する周には一度も評価されなかった**。
    既存の腕（転写が無い run）は 1 周目の諮りで止まるため、条件が効く位置まで到達していなかった
    （実測 2026-09-21: 条件から外しても全件緑）。**収束する直前の周だけ柵を空振りさせて測る。**
    """
    print("台本: 収束の条件が、柵の空振りを見て収束を止める（収束する周まで進めて測る）")
    # 柵が回るのは 1 周目（p0.claims / p0.terms）だけ。そこで転写を見失わせると、痕跡は盤面に残ったまま
    # 収束の周（3 周目）まで持ち越される——他の収束条件は全部そろうので、条件の位置がそのまま結果に出る
    run = Run("unchk-conv")
    noenv = {k: v for k, v in run.env.items() if k != "CLAUDE_CODE_SESSION_ID"}
    statuses, last = [], None
    for _ in range(80):
        nx = run.next()
        last = nx
        statuses.append(nx.get("status"))
        if nx.get("status") == "awaiting_human":
            kinds = (nx.get("ask") or {}).get("kinds", [])
            if "read_through_unchecked" not in kinds:
                break                      # 別の理由で止まったら、この腕の対象ではない
            run.cmd("answer", "--text", "continue", "--note", "柵の空振りを承知で続ける（検査）")
            continue
        if not nx["ready"] and nx["status"] in TERMINAL_STATUS:
            break
        answers = base_answers(run, "std")
        for inst in nx["ready"]:
            out = answers[inst["node"]](load_item(inst), nx["round"])
            f = run.tmp / "o.json"
            f.write_text(json.dumps(out, ensure_ascii=False) if not isinstance(out, str) else out, encoding="utf-8")
            r = run.cmd("done", "--node", inst["id"], "--output", str(f),
                        env=noenv if nx["round"] == 1 else run.env)
            if r.returncode != 0:
                raise RuntimeError(f"done {inst['id']} が {r.returncode}: {r.stderr[-200:]}")
    left = run.state().get("read_through_unchecked") or []
    check(left and all(x["round"] == 1 for x in left), f"1 周目に柵が空振りし、痕跡が残る（{[x['round'] for x in left]}）")
    check("converged" not in statuses,
          f"他の条件が全部そろう周まで進んでも、柵が空振りした run は収束しない（見た status: {statuses[-4:]}）")
    check(run.state()["round"] >= 3, f"収束の条件が効く周（連続 2 周ゼロ）まで実際に進んだ（{run.state()['round']} 周）")
    rm(run.tmp)


def test_read_through_unchecked():
    """**検査できない環境では黙って通さない。** 転写の見つからないハーネスから回されたとき、
    読了を確かめられなかった事実を盤面に残す。
    あわせて、**置き場の旗が無くても既定（~/.claude）で成立する**ことを見る——既定が無いと、
    旗を渡さない配置では柵が毎回空振りし、それが誰にも見えない。"""
    print("読了: 転写が見つからない環境では通すが痕跡を残す／旗が無くても既定の置き場で成立する")
    run, ids, out, terms = read_through_run("nochk")
    noenv = {k: v for k, v in run.env.items() if k != "CLAUDE_CODE_SESSION_ID"}
    r = run.cmd("done", "--node", ids["p0.claims"], "--output", str(out), env=noenv)
    check(r.returncode == 0, f"転写が無い環境でも止めない（検査できないことを理由に止めない）: {r.stderr[-80:]}")
    left = run.state().get("read_through_unchecked") or []
    check(left and left[0]["node"] == "p0.claims" and left[0]["round"] == 1,
          f"確かめられなかった事実が盤面に残る（{left[:1]}）")
    # 既定の置き場（~/.claude）: HOME だけを写しに向け、そこに転写を置いて p0.terms で測る
    home = run.tmp / "home"
    (home / ".claude" / "projects" / "sim").mkdir(parents=True, exist_ok=True)
    rid = run.state()["run_id"]
    (home / ".claude" / "projects" / "sim" / "deflt.jsonl").write_text("".join(
        json.dumps({"message": {"content": [{"type": "tool_result", "content": c}]}}, ensure_ascii=False) + "\n"
        for c in (run.doc.read_text(encoding="utf-8"),
                  # 印も置く——本文だけの転写は「読んだが、この run を回していない」形で、成立しない
                  f"ok を受け付けた。続きは loop.py next（run {rid}）")), encoding="utf-8")
    denv = {k: v for k, v in run.env.items() if k != "CLAUDE_CONFIG_DIR"}
    denv.update({"HOME": str(home), "USERPROFILE": str(home), "CLAUDE_CODE_SESSION_ID": "deflt"})
    before = len(run.state().get("read_through_unchecked") or [])
    r = run.cmd("done", "--node", ids["p0.terms"], "--output", str(terms), env=denv)
    check(r.returncode == 0 and len(run.state().get("read_through_unchecked") or []) == before,
          f"CLAUDE_CONFIG_DIR が無くても既定の置き場の転写で確かめが成立する（rc={r.returncode}: {r.stderr[-90:]}）")
    rm(run.tmp)

    # **痕跡は盤面で止めず、記録と報告まで出す。** 写すのは rules の finalize、数えて見せるのは engine の
    # traces()——どちらかが欠けると「柵が 1 度も成立しなかった周」が静かに終わる
    run2 = Run("nochk-record")
    run2.env = {k: v for k, v in run2.env.items() if k != "CLAUDE_CODE_SESSION_ID"}
    nx = drive(run2, "std")
    # **柵が 1 度も成立しなかった周は、機械が勝手に収束と言わない**（収束判定が人に諮る）。
    # 痕跡が finalize の件数にしか出なかったとき、柵が壊れている run と通った run が周の途中で同じに見えた
    check(nx.get("status") == "awaiting_human" and "read_through_unchecked" in (nx.get("ask") or {}).get("kinds", []),
          f"読了を確かめられなかった周は収束を宣言せず人に諮る（{nx.get('status')} / {(nx.get('ask') or {}).get('kinds')}）")
    check("読了の確かめが成立しなかった" in json.dumps((nx.get("ask") or {}).get("items", []), ensure_ascii=False),
          "諮る文が、何が確かめられなかったかを言う")
    r = run2.cmd("finalize")   # 諮ったあとも痕跡は記録と報告まで出る（機構は上の注記が正本）
    proc = run2.record().get("process") or {}
    check(proc.get("read_through_unchecked"),
          f"確かめられなかった事実が記録（process）に出る（{len(proc.get('read_through_unchecked') or [])} 件）")
    tr = (json.loads(r.stdout) if r.stdout.strip().startswith("{") else {}).get("traces") or {}
    check(tr.get("read_through_unchecked") == len(proc["read_through_unchecked"]),
          f"件数が finalize の出力（人に見せる口）に出る（{tr}）")
    rm(run2.tmp)


def test_path_inputs_table():
    """**どの入力がパスかは graph が宣言する**（graph の inputs が正本。engine は kind → 見方の対応だけ）。宣言に無い鍵は、貼る穴（file:）に
    渡っていても実在検査に当たらない——名乗りと実装が同じことを言う状態を、部品を直に呼んで固定する。
    あわせて、**見立て文書の入力が無い盤面**でも読了の柵が不成立を残すことを見る（今は入口が止めるので
    実物の経路では到達しないが、post_check を別の graph へ付け替えた周に静かに素通りするのを防ぐ）。"""
    print("入力の表: 実在検査は表の鍵だけに当たる／文書が無い盤面も不成立を残す")
    from engine.commands import required_inputs_missing  # noqa: E402 — 部品を直に呼ぶ腕
    _td, tmp = parallel.workspace("gl-tbl-")
    (tmp / "prompts").mkdir()
    (tmp / "prompts" / "n.md").write_text("{{file:inputs.other}} と {{inputs.document}}", encoding="utf-8")
    g = {"inputs": {"document": {"kind": "file"}}, "nodes": {"n1": {"prompt_file": "prompts/n.md"}}}
    gp = tmp / "g.json"
    gp.write_text(json.dumps(g, ensure_ascii=False), encoding="utf-8")
    doc = tmp / "doc.md"
    doc.write_text("見立て", encoding="utf-8")
    miss = required_inputs_missing(g, str(gp), {"document": str(doc), "other": str(tmp / "no-such.txt")})
    check(miss == [], f"表に無い鍵は、貼る穴に渡っていても実在検査に当たらない（表が正本。出た欠け: {miss}）")
    miss = required_inputs_missing(g, str(gp), {"document": str(tmp / "no-such.md"), "other": str(doc)})
    check(len(miss) == 1 and "--document" in miss[0], f"表に在る鍵は当たる（{miss}）")
    # **接頭の剥がし方は render が正本。** ここで接頭を手で知っていたとき、section: の穴しか持たない節は
    # 鍵が取れず、存在しない --document が入口を素通りした（実在検査にも欠け検査にも当たらない）
    (tmp / "prompts" / "sec.md").write_text("{{section:inputs.document#見出し}}", encoding="utf-8")
    gs = {"inputs": {"document": {"kind": "file"}}, "nodes": {"n1": {"prompt_file": "prompts/sec.md"}}}
    gsp = tmp / "gs.json"
    gsp.write_text(json.dumps(gs, ensure_ascii=False), encoding="utf-8")
    miss = required_inputs_missing(gs, str(gsp), {"document": str(tmp / "no-such.md")})
    check(len(miss) == 1 and "--document" in miss[0], f"section: の穴だけの節でも鍵が取れて実在検査に当たる（{miss}）")
    # **宣言が正本であることを実行で縛る。** graph の inputs から document を落とすと実在検査に当たらない
    # ——engine 側に名前の表が残っていたら、宣言を消しても当たり続けてこの腕が赤くなる
    gn = {"inputs": {}, "nodes": {"n1": {"prompt_file": "prompts/sec.md"}}}
    gnp = tmp / "gn.json"
    gnp.write_text(json.dumps(gn, ensure_ascii=False), encoding="utf-8")
    miss = required_inputs_missing(gn, str(gnp), {"document": str(tmp / "no-such.md")})
    check(miss == [], f"graph が宣言しない鍵は実在検査に当たらない（engine に名前の写しが残っていない: {miss}）")
    # 知らない kind は「パスでない」として扱う（graphcheck が静的に弾くので、実行時は黙って落とすだけ）
    gk = {"inputs": {"document": {"kind": "知らない種類"}}, "nodes": {"n1": {"prompt_file": "prompts/sec.md"}}}
    gkp = tmp / "gk.json"
    gkp.write_text(json.dumps(gk, ensure_ascii=False), encoding="utf-8")
    miss = required_inputs_missing(gk, str(gkp), {"document": str(tmp / "no-such.md")})
    check(miss == [], f"engine の知らない kind は実在検査の対象にしない（静的検査の担当: {miss}）")
    check(required_inputs_missing(gs, str(gsp), {"document": str(doc)}) == [], "在る文書なら section: の穴でも通る")
    # 文書が無い盤面: 部品（post_check）を直に呼ぶ——実物の経路は入口が止めるので通れない
    board = types.SimpleNamespace(state={"inputs": {}}, round=3, dir=tmp)
    RESEARCH_RULES.claims_intake(board, "p0.claims", {}, None)
    left = board.state.get("read_through_unchecked") or []
    check(len(left) == 1 and left[0]["node"] == "p0.claims" and left[0]["round"] == 3,
          f"見立て文書の入力が無い盤面でも、確かめられなかった事実が残る（{left}）")
    rm(tmp)


def test_input_existence():
    """**入力の実在検査は、貼る穴の接頭に依らず当たる。** 本物の graph には file:inputs.document の穴が
    3 つ残っているので、素の research-loop で測ると旧経路（is_file の分岐）が先に赤を出し、名前で見る側の
    腕が在っても無くても同じ色になる（実測 2026-09-18: 新 2 腕を BASE の 1 行に戻して全件緑）。柵が守ると
    名乗る形——回す側がパス渡しに寄り切って貼る穴が 1 つも無い graph——を作ってから測る。"""
    print("入口の検査: 貼る穴を持たない graph でも、存在しない --document と --cwd で init が落ちる")
    _td_tmp, tmp = parallel.workspace("gl-inp-")
    shutil.copytree(PLUGIN / "prompts", tmp / "prompts")
    shutil.copytree(PLUGIN / "rules", tmp / "rules")
    (tmp / "graphs").mkdir()
    g = json.loads((PLUGIN / "graphs" / "research-loop.json").read_text(encoding="utf-8"))
    for nid, n in g["nodes"].items():           # 貼る穴（file:）を 1 つ残らずパス渡しへ寄せた graph
        n["reads"] = [("inputs.document" if r == "file:inputs.document" else r) for r in (n.get("reads") or [])]
    for f in tmp.glob("prompts/research-loop/*.md"):
        f.write_text(f.read_text(encoding="utf-8").replace("{{file:inputs.document}}", "{{inputs.document}}"), encoding="utf-8")
    gp = tmp / "graphs" / "g.json"
    gp.write_text(json.dumps(g, ensure_ascii=False), encoding="utf-8")
    run = Run("inputs")
    init = lambda *extra: subprocess.run(
        [PY, str(LOOP), "init", "--loop", "research-loop", "--graph", str(gp), "--request", "q",
         "--dir", str(run.tmp / f"s{len(extra)}{hashlib.sha1(repr(extra).encode()).hexdigest()[:8]}"),
         "--validator", str(VALIDATOR), *extra],
        cwd=run.repo, capture_output=True, text=True, encoding="utf-8", timeout=600)
    r = init("--document", str(run.doc))
    check(r.returncode == 0, f"貼る穴を持たない graph でも、実在する --document なら init は通る（rc={r.returncode}: {r.stderr[-120:]}）")
    r = init("--document", str(run.tmp / "no-such.md"))
    check(r.returncode != 0 and "が無い" in r.stderr and "p0.claims" in r.stderr,
          f"貼る穴が 1 つも無くても、存在しない --document は入口で落ち、要る節を名指しする（rc={r.returncode}: {r.stderr[-120:]}）")
    # 以下 4 つの腕が守る規約の正本は engine/commands.py（診断の綴り・正規化の対象・空文字の扱い）
    r = init("--document", str(run.doc), "--input", f"cwd={run.tmp / 'no-such-dir'}")
    check(r.returncode != 0 and "が無い" in r.stderr,
          f"存在しないディレクトリを --input cwd= で渡すと入口で落ちる（rc={r.returncode}: {r.stderr[-120:]}）")
    check("--input cwd=" in r.stderr and "--cwd " not in r.stderr,
          f"旗を持たない鍵の診断は --input <鍵>=… と書く（打てない旗を名乗らない）: {r.stderr[-120:]}")
    d2 = run.tmp / "s_rel"
    r = subprocess.run([PY, str(LOOP), "init", "--loop", "research-loop", "--graph", str(gp), "--request", "q",
                        "--dir", str(d2), "--validator", str(VALIDATOR), "--document", str(run.doc),
                        "--input", f"document={run.doc.name}"],
                       cwd=run.repo, capture_output=True, text=True, encoding="utf-8", env=run.env, timeout=600)
    got = json.loads((d2 / "state.json").read_text(encoding="utf-8"))["inputs"]["document"] if (d2 / "state.json").is_file() else ""
    check(r.returncode == 0 and pathlib.Path(got).is_absolute(),
          f"--input document=<相対パス> も絶対パスに正規化されて盤面に入る（{got}）")
    d3 = run.tmp / "s_cwd"
    r = subprocess.run([PY, str(LOOP), "init", "--loop", "research-loop", "--graph", str(gp), "--request", "q",
                        "--dir", str(d3), "--validator", str(VALIDATOR), "--document", str(run.doc),
                        "--input", "cwd=."],
                       cwd=run.repo, capture_output=True, text=True, encoding="utf-8", env=run.env, timeout=600)
    gotc = json.loads((d3 / "state.json").read_text(encoding="utf-8"))["inputs"]["cwd"] if (d3 / "state.json").is_file() else ""
    check(r.returncode == 0 and pathlib.Path(gotc).is_absolute(),
          f"--input cwd=<相対パス> も絶対パスに正規化されて盤面に入る（{gotc}）")
    r = init("--document", str(run.doc), "--input", "cwd=")
    check(r.returncode != 0 and "が空" in r.stderr,
          f"--input cwd=（空）は入口で落ちる（rc={r.returncode}: {r.stderr[-100:]}）")
    rm(tmp); rm(run.tmp)


def test_non_utf8_document():
    """file: の穴が指す文書（--document）が UTF-8 でない——render の read_text が厳格復号で UnicodeDecodeError を投げ、
    next が『想定外の例外』で exit 2 になっていた（git の出力側は util.git の errors=replace が別に守る。この腕は render 側）。"""
    print("台本: UTF-8 でない --document でも file: の穴は置換して埋まる（render 側の復号）")
    run = Run("latin")
    doc = run.repo / "latin.md"
    # **読了の柵が成立する形にしておく**（非 UTF-8 の復号を測る台本なので、柵の不成立で収束が止まると
    # 測りたい所まで回らない）——標本が 3 区間から取れるだけの行数を持たせる
    doc.write_bytes(("# caf\u00e9 \ufffd の見立て文書（標本に使う長さの見出し）\n\n"
                     "\u00e9 claims この冒頭の行は標本に使う長さにしてある\n"
                     "\u00e9 claims この中ほどの行は標本に使う長さにしてある\n"
                     "\u00e9 claims この末尾の行は標本に使う長さにしてある\n"
                     ).encode("utf-8").replace(b"\xef\xbf\xbd", b"\xff"))
    run.read_into_transcript(doc)       # この台本は別の文書で init するので、その本文を転写に入れる
    d2 = run.tmp / "s2"
    r = subprocess.run([PY, str(LOOP), "init", "--loop", "research-loop", "--request", "q", "--document", str(doc), "--dir", str(d2), "--validator", str(VALIDATOR)],
                       cwd=run.repo, capture_output=True, text=True, encoding="utf-8", env=run.env, timeout=600)
    check(r.returncode == 0, f"UTF-8 でない文書でも init は通る（{r.stderr[-80:]}）")
    call = lambda *a: subprocess.run([PY, str(LOOP), *a, "--dir", str(d2)], cwd=run.repo, capture_output=True, text=True, encoding="utf-8", env=run.env, timeout=600)
    q = json.loads(call("next").stdout)["ready"][0]
    f = run.tmp / "o.json"
    f.write_text(json.dumps(base_answers(run, "std")["p0.question"](None, 1), ensure_ascii=False), encoding="utf-8")
    call("done", "--node", q["id"], "--output", str(f))
    run.dir = d2  # 台本（base_answers）が読む盤面をこの run に向ける
    run.mark_into_transcript()   # この盤面の run_id も転写に載せる（別の run の印では成立しない）
    # **本文を貼るのは、自分で読めない役だけ**（回す側にはパスが渡る）ので、復号の腕は遮断系の節で見る。
    # そこまで台本で回す——p3.cold_reader は新規相違ゼロの周にだけ立つ。**回すのは drive に任せる**:
    # 自前の周回しは next の rc と stderr を捨てるので、守っている退行（非 UTF-8 で next が exit 2）が
    # 再発したとき、赤の文面に原因（UnicodeDecodeError・rc=2）が 1 文字も出なかった
    grabbed = {}

    def grab(_run, inst, _out):
        if inst["node"] == "p3.cold_reader":
            grabbed["body"] = pathlib.Path(inst["prompt_file"]).read_text(encoding="utf-8")
        return None

    last = drive(run, "std", hook=grab)
    check("body" in grabbed, f"文書を貼る節（遮断系）まで回った（最後の status: {last.get('status')}）")
    check("�" in grabbed.get("body", "") and "caf" in grabbed.get("body", "") and "claims" in grabbed.get("body", ""),
          "文書の本文は置換文字で、先頭から末尾まで欠けずに貼られる——以前は next が UnicodeDecodeError で exit 2")
    rm(run.tmp)


def test_set_path():
    """**手当ての口は、読める綴りだけを受けて、当たらないなら落ちる。** set_path は get_path が読む
    `a.2.b` を解さず、辞書の setdefault だけで辿っていた。`questions[1]` を渡すと配列の要素ではなく
    その名前の鍵が新設され、patch は ok を返す——**当たっていない手当てが成功と報告される**
    （実測 2026-09-16: 台帳への手当て 2 回がどちらも入らず、検証器が別の理由で落ちて初めて分かった）。
    倒れる向きが危ない側なので、書けない綴りは黙って別の場所を作らず落とす。"""
    print("手当ての口（set_path）: 配列の要素に当たる／当たらない綴りは落ちる")
    sys.path.insert(0, str(PLUGIN))
    from engine.util import set_path, get_path
    d = {"questions": [{"k": 0}, {"k": 1}], "a": {"b": {"c": 1}}}
    set_path(d, "questions.1", {"k": "書けた"})
    check(d["questions"][1] == {"k": "書けた"}, "配列の要素を点の添字で書き換えられる")
    set_path(d, "questions.0.k", "深い所")
    check(d["questions"][0]["k"] == "深い所", "配列の中の鍵まで辿って書ける")
    check(get_path(d, "questions.0.k") == "深い所", "書いた所を get_path が同じ綴りで読める（読み書きの綴りが揃う）")
    for bad in ("questions[1]", "questions.9", "questions.1.k.deep"):
        try:
            set_path(d, bad, "x")
            check(False, f"書けない綴り {bad} は落ちる")
        except KeyError:
            check(True, f"書けない綴り {bad} は落ちる（黙って別の場所を作らない）")
    check("questions[1]" not in d, "角括弧の綴りが、その名前の鍵として新設されていない")
    # **葉の新設（作成枝）。** ここに腕が無かったので、作成枝を丸ごと KeyError に差し替える 1 行の退行が
    # 検査一式を緑のまま通った（実測 2026-09-16: 判定役が名指しした 5 つの 1 行退行のうち、この 1 本だけが緑）。
    set_path(d, "materials.local_review", {"status": "clean"})
    check(get_path(d, "materials.local_review") == {"status": "clean"}, "既存の辞書の下に葉を 1 つ新設できる")
    # **点を含む鍵が最後に来る綴り。** 走査が最後の区切りを候補から外していたので、既存の
    # `outputs["p1.local_review"]` を指す綴りが `outputs["p1"]["local_review"]` を黙って新設し、
    # get_path は元の場所を読み続けた——patch は ok を印字しながら手当てが当たらない（実測 2026-09-16）
    d["outputs"] = {"p1.local_review": {"round": 1}}
    set_path(d, "outputs.p1.local_review", {"round": 2})
    check(d["outputs"] == {"p1.local_review": {"round": 2}}, "点を含む鍵を最長一致で食い、隣に入れ子を作らない")
    check(get_path(d, "outputs.p1.local_review") == {"round": 2}, "書いた所を get_path が同じ綴りで読める（点入りの鍵）")
    # 2 段以上の新設は「点を含む 1 つの鍵」と区別が付かないので受けない（黙ってどちらかを選ばない）
    try:
        set_path(d, "outputs.p2.nope.deep", "x")
        check(False, "2 段以上の新設は落ちる")
    except KeyError as e:
        check("葉 1 つ" in str(e), "2 段以上の新設は落ちる（どちらの読みも成り立つ綴りを機械が選ばない）")
    check("p2" not in d["outputs"], "落ちた綴りが途中まで書き込まれていない")


def test_carried_r1_only_previous_round():
    """`前の周の R1` は `最後に走った R1` ではない。走らなかった周を挟んだら要求しない。

    outputs は節ごとに最新の 1 件しか持たず、R1 は再発火条件付き（cond: loop.r1_refire）なので、
    走らなかった周を挟むと数周前の出力が返る——処理済みの削除候補が次の周にも同じ顔で要求され、
    judge には直す術が無い（実測 2026-09-16: judge がこの形を名指しした）。
    """
    print("carried_r1: 直前の周に走った R1 の削除候補だけを要求する")
    sys.path.insert(0, str(PLUGIN))
    import json as _json
    from engine.rules import load_rules
    gp = str(PLUGIN / "graphs" / "review-loop.json")
    graph = _json.loads(pathlib.Path(gp).read_text(encoding="utf-8"))
    m = load_rules(gp, graph)

    class B:
        pass

    def board(ran_in_round):
        b = B()
        b.graph, b.round = graph, 3
        b.state = {"outputs": {"r1.minimality": {"round": ran_in_round}}}
        b.outputs = lambda before_round=None: {"r1.minimality": {"deletions": [{"where": "src/a.py:1 の注記", "why": "写し"}]}}
        return b

    out = {"units": [], "carried_r1": []}
    errs = m._carried_r1_accounted(board(2), out)
    check(errs and "carried_r1 に無い" in errs[0], "直前の周（round-1）に走った R1 の候補は要求する")
    errs = m._carried_r1_accounted(board(1), out)
    check(errs == [], "2 周前の R1 の候補は要求しない（走らなかった周を挟んだら黙って持ち越さない）")


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
    # **拒否の文は原因を 1 つに断定しない。** 候補は素の str で元テキストのどこから切ったかを
    # 運ばないので、pos を候補間で比べても「どこまで読めたか」にならない（実測 2026-09-15:
    # 断定する形で書いたら、散文に波括弧が混じった返答＝JSON を 1 文字も返していない返答に
    # 『直すのは中身』と出た。素の JSON の後ろに文が付いた形では旧文言の方が正しかった）。
    broken = '{"findings": [{"where": "配列（"/code-review high" 等）", "text": "x"}]}'
    try:
        parse_output("```json\n" + broken + "\n```")
        check(False, "囲いの中の壊れた JSON は Reject")
    except Reject as e:
        msg = str(e)
        check("候補 2 本すべてで失敗" in msg, "拒否の文が、試した相異なる候補の本数を言う")
        check("``` 囲いの中" in msg and "全文そのまま" in msg, "候補ごとに、どの切り方で何が起きたかを並べる")
        check("/code-review high" in msg and "[ここ]" in msg, "折れた所として、実際に壊れている値が前後ごと出る")
        # **『断定しない』は綴りの不在で測れない。** 以前ここは「直すのは囲いの付け方ではなく中身」
        # という 1 綴りの不在だけを見ていたが、その文字列は当の検査にしか無く条件は常に真だった
        # ——同じ趣旨を別の言い回しで書き戻しても赤にならない（実測 2026-09-16: 別綴りの断定文を
        # 注入した写しが全件緑）。名乗った範囲を測れる形＝診断行が候補の数だけ並ぶ構造で見る。
        diag = [l for l in msg.splitlines() if l.startswith("  - ")]
        check(len(diag) == 2, f"診断行が、試した候補と同じ本数だけ並ぶ（原因を 1 本に畳まない。実際 {len(diag)}）")
        check(len(set(diag)) == len(diag), "同じ中身の候補を 2 回試さない（同一の診断行が並ばない）")
        check("よくある原因:" in msg and "囲い（```）が閉じていない" in msg,
              "助言行が付く（役に直し方を教える側——診断だけ出して直し方を出さない形にしない）")
    # 省略記号は「まだ前後がある」の印。端で無条件に付けると、無いものが在るように読める。
    broken2 = '{"a": "x（"y"）"}'          # 折れる位置が先頭近くで、後ろも短い
    try:
        parse_output(broken2)
        check(False, "短い壊れた JSON は Reject")
    except Reject as e:
        line = [l for l in str(e).splitlines() if l.startswith("  - ")][0]
        check("...[ここ]" not in line, "折れた所が先頭寄りなら、前側に省略記号を付けない")
        check(not line.rstrip().endswith("..."), "折れた所の後ろが尽きているなら、後側に省略記号を付けない")
    # 3 本目の候補（{ から } まで）は、囲いの外に波括弧が在る形でだけ相異なる中身になる。
    # ラベルを書き換えても赤くならないままだと、どの切り方で落ちたかの名前が信用できない。
    try:
        parse_output("前置き { \"a\": } 後書き")
        check(False, "囲い無しで波括弧を含む壊れた返答は Reject")
    except Reject as e:
        check("{ から } まで" in str(e), "3 本目の候補のラベルが、実際にその切り方で落ちたときに出る")
    try:
        parse_output("これは JSON を返しません。{ここは例です}")
        check(False, "散文に波括弧が混じる返答は Reject")
    except Reject as e:
        check("全文そのまま: Expecting value" in str(e),
              "JSON を 1 文字も返していない返答では、全文候補が頭から落ちたことが見える")
    # 空は候補を出す前に落とす。候補は無条件に全文を 1 本出すので、後ろで「候補が 0 本」を
    # 見る枝は到達しない（実測 2026-09-15: そう書いた枝が死んでいた）。
    for empty in ("", "   ", "\n\n"):
        try:
            parse_output(empty)
            check(False, "空の返答は Reject")
        except Reject as e:
            msg = str(e)
            # **読み元を名指しさせない。** cmd_done は --output / --stdin / out_path の 3 入口で
            # text を作り、parse_output には text しか渡らない。1 つに決め打つと、既定の導線
            # （手順書が案内する --output）で誤った場所を直しに行かせる。
            check("空か空白だけ" in msg and "候補" not in msg,
                  f"空の返答は候補の話をせず、中身が無いことだけを言う（{empty!r}）")
            check("out_path" not in msg and "--stdin" not in msg,
                  f"空の返答の拒否文が、3 入口のどれか 1 つを読み元と決め打たない（{empty!r}）")
    # 閉じ ``` が無い返答は、入力長に対して線形で落ちる。以前ここは正規表現の貪欲な空白 +
    # lazy な本文で、後戻り地点 × 舐め直しの二次になっていた（実測 2026-09-16: 空白 80,000 文字
    # で 21.8 秒）。**時間を測る検査は環境差で揺れるので、閾値は桁で置く。**
    import time as _t
    _s = _t.time()
    try:
        parse_output("```json" + " " * 80000 + "x")
        check(False, "閉じない囲いは Reject")
    except Reject:
        pass
    check(_t.time() - _s < 1.0, "閉じ ``` が無い返答が、入力長に対して線形で落ちる（1 秒未満）")


def test_workspace_cleanup():
    """**作業場は、落ちた回でも消える。** 台本の作業場（git リポジトリを含む）は 1 本あたり数百 KB で、
    残ると溜まる（実測 2026-09-13: 502 個・148 MB。正常終了する回は 1 個も漏らさず、漏れるのは落ちた回だけ）。

    以前は `mkdtemp` ＋ モジュール変数の集合 ＋ `atexit` で自作していた——`tempfile.TemporaryDirectory`
    （`weakref.finalize`）の再実装で、しかも後から並列化を足したとき**自作の集合だけ排他の外に残った**。
    要件（落ちた回でも消える）を検査した腕は 1 本も無く、標準に寄せた後も無ければ同じことになる。
    """
    print("作業場の後始末: 持ち手を捨てたとき・プロセスが落ちたときの両方で消える")
    _td, tmp = parallel.workspace("gl-ws-")
    (tmp / "x.txt").write_text("x", encoding="utf-8")
    check(tmp.exists(), "作業場ができる")
    del _td
    check(not tmp.exists(), f"持ち手を捨てたらその場で消える（{tmp}）")
    # **落ち方は子プロセスでしか作れない**——この台本自身を落とすと残りの検査が走らない
    src = "import sys, pathlib; sys.path.insert(0, %r); import parallel\ntd, p = parallel.workspace('gl-ws-die-')\nprint(p)\nraise SystemExit(3)\n" % str(HERE)
    r = subprocess.run([PY, "-c", src], capture_output=True, text=True, encoding="utf-8", timeout=120)
    check(r.returncode == 3 and not pathlib.Path(r.stdout.strip()).exists(),
          f"落ちた回（SystemExit）でも消える（exit {r.returncode}: {r.stdout.strip()}）")



def test_cond_truth_tables():
    """**research-loop の条件ごとの真偽表**（graph の cond が名前で指す rules の関数）。engine と同じ口（run_cond）で
    文脈を手で組んで直に呼ぶ。期待の "die" は、宣言した欄が default 無しで解決できないと落ちること（偽に倒さない）。
    CONDS の名前が全部表に在ることも見る"""
    print("条件の真偽表（research）: CONDS の関数を 1 つずつ、真・偽・落ちるの行で当てる")
    import io  # noqa: E402
    from contextlib import redirect_stderr  # noqa: E402
    from engine.board import COND_HEADS, run_cond  # noqa: E402

    def ev(name, ctx):
        fn = RESEARCH_RULES.CONDS[name]
        buf = io.StringIO()
        try:
            with redirect_stderr(buf):
                return run_cond(name, fn, {**{h: {} for h in COND_HEADS}, "round": 1, **ctx})[0]
        except SystemExit:
            return "die"
    T = {
        "constraints_self_written": [({}, False), ({"record": {"constraints": []}}, False),
                                     ({"record": {"constraints": [{"origin": "人"}, {"origin": "surveyor自書"}]}}, True),
                                     ({"record": {"constraints": [{"origin": "人"}]}}, False), ({"record": {"constraints": {"origin": "surveyor自書"}}}, False)],
        "generation_due": [({}, True), ({"round": 2}, False), ({"round": 2, "loop": {"stuck_hint": True}}, True),
                           ({"round": 2, "loop": {"stuck_hint": False}}, False)],
        "no_new_discrepancies": [({"rd": {"new_discrepancies": 0}}, True), ({"rd": {"new_discrepancies": 2}}, False), ({}, "die")],
        "rederiver_compare_due": [({"rd": {"new_discrepancies": 0}, "out": {"p3.rederiver": {"verdict": "pass"}}}, True),
                                  ({"rd": {"new_discrepancies": 0}, "out": {"p3.rederiver": {"verdict": "fail"}}}, False),
                                  ({"rd": {"new_discrepancies": 1}}, False), ({"rd": {"new_discrepancies": 0}}, "die")],
        "sampling_due": [({}, False), ({"round": 2, "rd": {"item_counts": {"p1.checker": 0}}}, True),
                         ({"round": 2, "rd": {"item_counts": {"p1.checker": 3}}}, False), ({"round": 2}, "die")],
    }
    for name, rows in T.items():
        for i, (ctx, want) in enumerate(rows):
            got = ev(name, ctx)
            check(got == want, f"{name} の行 {i}: 期待 {want}・実際 {got}")
    check(set(RESEARCH_RULES.CONDS) <= set(T), f"CONDS の名前が全部真偽表に在る（表に無い: {sorted(set(RESEARCH_RULES.CONDS) - set(T))}）")


def main():
    os.environ.pop("CONVERGENCE_LOOPS_ROOT", None)
    # 一時ディレクトリ（git リポジトリを含む）の後始末は `parallel.workspace`（TemporaryDirectory）が持つ。
    # **消すのは自分が作った作業場だけ**——接頭辞で列挙して差分を消していたとき、実行中に他プロセスが作った
    # 作業場が差分に入り、そのプロセスの盤面が走行中に消えた（実測 2026-09-13: 退行注入と baseline が
    # 互いを殺し、落ちた台本が毎回違った）。持ち手を Run が握るので、台本を抜けた時点で消える
    # （main に届かない落ち方——import 時の例外・engine を壊して全体が落ちる・退行注入の試走——も
    # weakref.finalize がプロセス終了時に覆う。自作の集合 ＋ atexit はこれの再実装だった）。
    # **台本は名前で集めて同時に走らせる。** 手で並べると足した台本の呼び忘れに誰も気づかない
    # （呼ばれない台本は件数を増やさないので件数の柵をすり抜ける）。同時に走らせてよいのは、
    # 台本どうしが自分の作業場しか触らないから——時間はほぼ全部が子プロセスの終了待ちだった。
    # 直列に戻すのは GL_TEST_WORKERS=1——並列でだけ落ちる台本を切り分けるときに使う。
    tests = parallel.collect(globals())
    parallel.run_all(tests)
    only = bool(os.environ.get("GL_TEST_ONLY"))
    check(only or DELIVERY_SEEN >= {"p1.checker", "p3.cold_reader"}, f"渡し方の検査は checker（agent/path）と cold_reader（cli/paste）の両方に実際に当たった（{sorted(DELIVERY_SEEN)}）")
    reached, total, unreached = vocab_coverage()
    if not only:   # 台本を絞った回は、全台本の到達を見る検査を当てない
        check(reached == VOCAB_REACHED,
              f"判定語彙の到達 {reached}/{total}（記録は {VOCAB_REACHED}）——筋書きを増やしたら数を上げろ。"
              f"未到達の頭: {unreached[:3]}")
    # **本数は「実際に集めて走らせた関数」を数える**（run.sh の grep ではなく）。text を grep すると、
    # 字面だけ変えた（インデントした・改名した）台本が消えても数が合ったままになる
    print(f"台本 {len(tests)} 本")
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
