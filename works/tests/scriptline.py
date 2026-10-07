"""線 darkfactory を本物のスクリプトで通す小さな回し手（test_* でないので unittest の発見に拾われない）。

linekit.LineRun はブロックの口の関数を直に呼ぶ。こちらは YAML を読み、Archon と同じ形で script の節を子のプロセスで起こし
（with: → INPUTS_<大文字>・ARTIFACTS_DIR・WORKFLOW_ID、cwd は対象）、標準出力の 1 行を節の output_format に当てる。
Archon の模擬実行（dev/check.sh）は script の節を stub で置き換えるので、スクリプトの本物の出力と宣言の型のずれ
（run 25 の blk-delta review-accept: 型に無い欄 ready・asking・halted・out_file で additionalProperties: false に落ちた）は
そこでは見えない。ここがそれを見る（tests/test_script_contract.py）。

Archon の約束のうち、ここで写す物（darkfactory と include のブロックが使う物だけ）:
- script の節の環境変数 ARCHON_NODE_EXECUTION（JSON）の欄 path は Archon の step の名（測り M1）: 線の最上段は `<節>`、
  include の中は `<include の節の id>__<節>`、輪の中は `<include の節の id>__<輪>.<節>`（線の最上段の輪は `<輪>.<節>`）。
  core の flow_adapter はここから scope（include の名）を引く
- 節の順は YAML の並び（depends_on が前の節を指すことを確かめる）。trigger_rule は all_success（既定）・
  none_failed_min_one_success・all_done。when: は `$<節>.output.<欄> == true|false|'<語>'`
- with: の値: 文字列の中の `$INPUTS.<名>`・`$<節>.output[.<欄>]` を置き換える（文字列はそのまま、ほかは JSON）。
  `{from: "$<節>.output", if_skipped: v}` は出力の JSON（走らなかった節は v の JSON。null なら文字列 null）
- include: with: を親の scope で解いてブロックの inputs（default つき）にし、returns の節の出力を include の節の出力にする
- loop_group: 中の節を並びの順に回し、until_bash（`test $<節>.output.<欄> = <語>`）が真で抜ける。max_iterations に
  当たったら輪の節は失敗（Archon は run を落とす。裁定 R50 で避ける形）。輪の出力は最後の周の最後の節の出力
- 役の節（command・prompt）は replies の返答（呼ぶたびに作り直せる関数も可）。関所（approval）は gates の答え
期限は足さない（子のプロセスに timeout を渡さない。Global Constraints）。
"""
import json
import os
import pathlib
import re
import subprocess
import sys
from typing import Callable

import yaml

TESTS = pathlib.Path(__file__).resolve().parent
ROOT = TESTS.parent
CORE = ROOT / ".shared" / "core"
sys.dont_write_bytecode = True
for p in (str(CORE), str(TESTS)):
    if p not in sys.path:
        sys.path.insert(0, p)

import linekit  # noqa: E402
import accept  # noqa: E402,F401  （写しの engine を sys.path に足す）
from engine.schema import validate_schema  # noqa: E402

LINE = "darkfactory"
RUN_ID = "run-script-line"
NFMOS = "none_failed_min_one_success"
REF = re.compile(r"\$([A-Za-z_][A-Za-z0-9_-]*)\.output(?:\.([A-Za-z_][A-Za-z0-9_]*))?")
INPUT_REF = re.compile(r"\$INPUTS\.([A-Za-z_][A-Za-z0-9_]*)")
WHEN = re.compile(r"^\$([A-Za-z0-9_-]+)\.output\.([A-Za-z0-9_]+) == (true|false|'[^']*')$")
UNTIL = re.compile(r"^test \$([A-Za-z0-9_-]+)\.output\.([A-Za-z0-9_]+) = (\S+)$")
AI_KEYS = ("command", "prompt")
NODE_EXECUTION = "ARCHON_NODE_EXECUTION"   # Archon が script の節に渡す節の居場所（JSON。欄 path が step の名）


def flow(name: str) -> dict:
    return yaml.safe_load((ROOT / name / f"{name}.yaml").read_text(encoding="utf-8"))


def walk(nodes, inner=False):
    """(節, 輪の中か) を並びの順に（loop_group の中も）"""
    for n in nodes or []:
        yield n, inner
        yield from walk((n.get("loop_group") or {}).get("nodes"), True)


def script_nodes(name: str) -> list:
    """YAML の script の節で output_format を持つ物の id（輪の中も）"""
    return [n["id"] for n, _ in walk(flow(name)["nodes"]) if "script" in n and "output_format" in n]


def wired_blocks() -> list:
    """線が include するブロック（線の並び）"""
    return [n["include"] for n in flow(LINE)["nodes"] if "include" in n]


def _text(v) -> str:
    return v if isinstance(v, str) else json.dumps(v, ensure_ascii=False)


class Failed(Exception):
    """節が落ちた（終了コードが 0 でない・出力が JSON でない・輪が max_iterations に当たった）。Archon は run を落とす"""


class Scope:
    """1 つの工程（線かブロック）の節の出力と状態。include は線がこの工程を差し込んだ include の節の id（線そのものは空）"""

    def __init__(self, block, inputs, include=""):
        self.block, self.inputs, self.include = block, inputs, include
        self.out, self.status = {}, {}

    def step(self, nid: str, loop: str = "") -> str:
        """Archon の step の名（ARCHON_NODE_EXECUTION の path）: [<include>__][<輪>.]<節>"""
        return (f"{self.include}__" if self.include else "") + (f"{loop}." if loop else "") + nid

    def sub(self, s: str) -> str:
        s = INPUT_REF.sub(lambda m: _text(self.inputs.get(m.group(1), "")), s)

        def one(m):
            nid, field = m.group(1), m.group(2)
            if nid not in self.out:
                return ""
            v = self.out[nid]
            return _text(v.get(field, "") if field else v)
        return REF.sub(one, s)

    def value(self, v) -> str:
        if isinstance(v, dict) and "from" in v:
            m = REF.fullmatch(v["from"])
            if not m:
                raise ValueError(f"from: の形が違う: {v['from']}")
            nid, field = m.group(1), m.group(2)
            if self.status.get(nid) != "ok":
                return json.dumps(v.get("if_skipped"))
            got = self.out[nid]
            return json.dumps(got.get(field) if field else got, ensure_ascii=False)
        return self.sub(str(v))


class ScriptLine:
    """線を本物のスクリプトで回す。replies[<ブロック>/<節>] か replies[<節>] は役の返答（dict か f(attempt) -> dict）。
    bad_first に在る役（同じ鍵）は 1 回目に bad の返答を返す（受け付けの拒否の出口を通す）。edits[<鍵>] は役が作業ツリーに
    当てる変更（repo を受ける関数。返答の前に毎回当てる）。gates[<関所>] は関所の答え。stop_at の境の節の前に止め札を置く。
    declared が偽なら種にテストの宣言（.review-checks.json）を置かない（CI の任せ先の役 blk-ci が回る）。
    sessions なら start の後に包みの家へ判定役の会話の id と起動の行を置く（再審の役が判定役の会話を継げる run）。
    inputs に無いラインの入力は yaml の inputs の default に落ちる（adapter だけ optional——この器は包みを通さずに回す）。
    runs は起こした script の節の記録 {block, node, rc, out, errors, stderr}（errors は output_format に当てた食い違い）。
    watch(<節>, "start"|"done") は線の最上段の include の節ごとに、走らせる直前と出口が ok の直後に呼ぶ（飛ばした節では呼ばない）。
    github なら種の origin を GitHub の形にし、交差を返す偽の gh を子の PATH の頭に置く（並行 PR の任せ先の役 blk-pr が回る run。
    linekit.github_crossing）。無ければ種は remote を持たない forge の無い run で、並行 PR は機械が条件外にする"""

    def __init__(self, tmp, *, replies=None, gates=None, inputs=None, edits=None, bad_first=(), bad=None, stop_at=None,
                 declared=True, sessions=False, watch: Callable[[str, str], None] | None = None, github=False):
        self.tmp = pathlib.Path(tmp)
        self.watch = watch
        self.replies, self.gates, self.edits = replies or {}, gates or {}, edits or {}
        self.bad_first, self.bad = set(bad_first), bad if bad is not None else {}
        self.stop_at = stop_at
        self.sessions = sessions
        self.repo = linekit.seed_repo(self.tmp / "repo", declared=declared)
        req = self.tmp / "req" / "request.json"
        req.parent.mkdir(parents=True, exist_ok=True)
        req.write_text((linekit.SEED / "request_ok.json").read_text(encoding="utf-8"), encoding="utf-8")
        self.inputs = {"request": str(req), "adapter": "optional", **(inputs or {})}
        self.art = self.tmp / "art"
        self.art.mkdir(parents=True, exist_ok=True)
        self.board = self.art / "board"
        self.runs, self.trail, self.attempts = [], [], {}
        self.env = {k: v for k, v in os.environ.items() if not k.startswith("INPUTS_")}
        self.env.update({"ARTIFACTS_DIR": str(self.art), "WORKFLOW_ID": RUN_ID, "PYTHONDONTWRITEBYTECODE": "1",
                         "WORKS_ADAPTER_HOME": str(self.tmp / "adapter-home"),
                         "XDG_STATE_HOME": str(self.tmp / "state"), **linekit.lens_plugin(self.tmp)})
        if github:
            self.env["PATH"] = linekit.github_crossing(self.repo, self.tmp)

    # -- 役・関所
    def _reply(self, block, nid):
        key = next((k for k in (f"{block}/{nid}", nid) if k in self.replies), None)
        n = self.attempts[(block, nid)] = self.attempts.get((block, nid), 0) + 1
        for k in (f"{block}/{nid}", nid):
            if k in self.edits:
                self.edits[k](self.repo)
                break
        if n == 1 and ({f"{block}/{nid}", nid} & self.bad_first):
            return self.bad.get(f"{block}/{nid}", self.bad.get(nid, {}))
        if key:
            got = self.replies[key]
        elif (block, nid) == ("blk-structure", "structure-eye"):   # 単位の id は run ごとに決まるので、実測から組む
            got = linekit.structure_eye_reply(self.art / "structure" / "structure.json")
        elif (block, nid) == ("blk-judge", "judge-verify"):   # 判定の裏取りの束ね役: 下請けの代わりに答えのファイルを書く（線の木の段 3）
            got = linekit.verify_answers(self.board)
        else:
            got = default_reply(block, nid)
        return got(n) if callable(got) else got

    # -- 節
    def _script(self, scope, n, loop=""):
        env = dict(self.env)
        env[NODE_EXECUTION] = json.dumps({"runId": RUN_ID, "path": scope.step(n["id"], loop)})
        env.update({f"INPUTS_{k.upper()}": scope.value(v) for k, v in (n.get("with") or {}).items()})
        path = ROOT / scope.block / "scripts" / f"{n['script']}.py"
        p = subprocess.run([sys.executable, str(path)], cwd=str(self.repo), env=env, capture_output=True, text=True, encoding="utf-8",
                           stdin=subprocess.DEVNULL)
        rec = {"block": scope.block, "node": n["id"], "rc": p.returncode, "out": None, "errors": [],
               "stderr": p.stderr.strip()[-2000:]}
        self.runs.append(rec)
        if p.returncode != 0:
            raise Failed(f"{scope.block}/{n['id']} が終了コード {p.returncode}: {rec['stderr']}")
        try:
            out = json.loads(p.stdout)
        except json.JSONDecodeError as e:
            raise Failed(f"{scope.block}/{n['id']} の標準出力が JSON でない（{e}）: {p.stdout[:300]!r}") from None
        rec["out"] = out
        if "output_format" in n:
            rec["errors"] = validate_schema(out, n["output_format"])
        return out

    def _put_session(self):
        """包みの家（子のプロセスと同じ WORKS_ADAPTER_HOME）に判定役の会話の id と起動の行（盤面を作った後）を置く"""
        from unittest import mock
        import rejudgekit
        with mock.patch.dict(os.environ, {"WORKS_ADAPTER_HOME": self.env["WORKS_ADAPTER_HOME"]}):
            rejudgekit.put_session(self.repo)

    def _edge_stop(self, n):
        if self.stop_at == n["id"]:
            import halt
            halt.place(self.board, "止め札の試し", "test")

    def _include(self, scope, n):
        name = n["include"]
        doc = flow(name)
        given = {k: scope.value(v) for k, v in (n.get("with") or {}).items()}
        inputs = {k: given.get(k, (spec or {}).get("default", "")) for k, spec in (doc.get("inputs") or {}).items()}
        inner = Scope(name, inputs, include=n["id"])
        self._nodes(inner, doc["nodes"])
        ret = doc["returns"]
        if inner.status.get(ret) != "ok":
            raise Failed(f"{name} の出口 {ret} が走らなかった（{inner.status.get(ret)}）")
        return inner.out[ret]

    def _loop(self, scope, n):
        lg = n["loop_group"]
        m = UNTIL.match(lg["until_bash"].split("#")[0].strip())
        if not m:
            raise ValueError(f"until_bash の形が違う: {lg['until_bash']}")
        for _ in range(lg["max_iterations"]):
            for k in [c["id"] for c in lg["nodes"]]:
                scope.status.pop(k, None)
                scope.out.pop(k, None)
            self._nodes(scope, lg["nodes"], loop=n["id"])
            nid, field, want = m.groups()
            if scope.status.get(nid) == "ok" and _text(scope.out[nid].get(field)) == want:
                return scope.out[lg["nodes"][-1]["id"]]
        raise Failed(f"{scope.block}/{n['id']} が max_iterations {lg['max_iterations']} に当たった（until_bash が偽のまま）")

    def _runs(self, scope, n, loop) -> bool:
        deps = n.get("depends_on") or []
        for d in deps:
            if d not in scope.status:
                raise ValueError(f"{scope.block}/{n['id']} の depends_on {d} が前に無い")
        st = [scope.status[d] for d in deps]
        rule = n.get("trigger_rule") or "all_success"
        if rule == "all_done":
            go = True
        elif rule == NFMOS:
            go = "failed" not in st and (not st or "ok" in st)
        else:
            go = all(s == "ok" for s in st)
        if go and n.get("when"):
            m = WHEN.match(n["when"].strip())
            if not m:
                raise ValueError(f"when: の形が違う: {n['when']}")
            nid, field, want = m.groups()
            have = scope.out.get(nid, {}).get(field) if scope.status.get(nid) == "ok" else None
            go = (have is True) if want == "true" else (have is False) if want == "false" else have == want.strip("'")
        return go

    def _nodes(self, scope, nodes, loop=""):
        for n in nodes:
            nid = n["id"]
            if not self._runs(scope, n, loop):
                scope.status[nid] = "skipped"
                continue
            if "script" in n:
                if n["script"] == "edge":
                    self._edge_stop(n)
                out = self._script(scope, n, loop)
                if self.sessions and scope.block == LINE and nid == "start":
                    self._put_session()
            elif "include" in n:
                top = self.watch is not None and scope.block == LINE
                if top:
                    self.watch(nid, "start")
                out = self._include(scope, n)
                if top:
                    self.watch(nid, "done")
            elif "loop_group" in n:
                out = self._loop(scope, n)
            elif any(k in n for k in AI_KEYS):
                out = self._reply(scope.block, nid)
            elif "approval" in n:
                out = self.gates.get(nid) or {"decision": "continue", "text": ""}
            else:
                raise ValueError(f"{scope.block}/{nid} の種類が分からない")
            scope.out[nid], scope.status[nid] = out, "ok"
            self.trail.append(f"{scope.block}/{nid}")

    def run(self) -> dict:
        """線を回す。返り {completed, failure, runs, trail, out}（failure は落ちた節の文。落ちなければ空）"""
        doc = flow(LINE)
        top = Scope(LINE, {k: self.inputs.get(k, (spec or {}).get("default", ""))
                           for k, spec in (doc.get("inputs") or {}).items()})
        failure = ""
        try:
            self._nodes(top, doc["nodes"])
        except Failed as e:
            failure = str(e)
        return {"completed": not failure, "failure": failure, "runs": self.runs, "trail": self.trail, "out": top.out}


# ---------------------------------------------------------------- 役の既定の返答（linekit.LineRun と同じ見本）
def default_reply(block, nid):
    if block == "blk-eyes":
        import test_blk_eyes as TB
        return TB.REPLY[nid]
    if block == "blk-material":
        if str(ROOT / "blk-material" / "lib") not in sys.path:
            sys.path.insert(0, str(ROOT / "blk-material" / "lib"))
        import material
        import test_blk_material as TM
        board_nid = material.ROLES[nid]
        return linekit.reply("purpose_review_ok") if board_nid == "p0.purpose_review" else TM.good_reply(board_nid)
    if block == "blk-report":
        stubs = yaml.safe_load((ROOT / "blk-report" / "fixtures" / "pass.stubs.yaml").read_text(encoding="utf-8"))
        return stubs[nid]
    if block == "blk-lens":
        return linekit.LENS_REPLY
    fixed ={("blk-pr", "pr-check"): "pr_no_conflicts", ("blk-premises", "premises"): "premises_ok",
             ("blk-purpose", "purpose"): "purpose_ok", ("blk-judge", "judge"): "judge_ok", ("blk-plan", "r2-design"): "design_ok"}
    if (block, nid) in fixed:
        return linekit.reply(fixed[(block, nid)])
    raise KeyError(f"{block}/{nid} の返答が replies に無い")
