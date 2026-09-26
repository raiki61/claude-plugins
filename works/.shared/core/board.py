"""盤面の層。run の途中の状態をディスクに置く盤面と、写した graphloops の規則をそこに当てる口（仕様 works/docs/specs/2026-09-26-board-layer-design.md）。

今ここに在る物:
- BoardGap・BoardMismatch・RecordInvalid: 内部の誤りの型（仕様 4.6。RecordInvalid は報告の前の検証器の関所）。役の返答の誤りは engine の Reject のまま
- NodeEntry・NodeTable:    節の表（仕様 4.2）。graph の全部の節を、このラインでどう持つかに振る
- DiskBoard:               ディスクの盤面を開く入れ物（仕様 4.1・4.4）。写した engine の Board を継ぐ
- Progress:                settle まで回す口（settle・done・run_builtin・answer・skip）の返り（仕様 4.1）
- tree_runner:             run_engine の既定の runner（works の tree_run で 1 段ずつ。返りの行は engine の run_steps と同じ鍵）
- rules_module・graph_expanded: 盤面なしで写しの RL と graph を読む口（仕様 4.1 の末尾）

節の表のファイル（<ライン>/nodes.json）の形:
  {"line": str, "graph_sha": str, "nodes": {節: {"by": str, "run"?, "fallback"?, "skippable"?, "reason"?, "where"?, "comes_with"?}}}
読むとき（load）は形だけを見る。graph との突き合わせ（縛り 1〜5）は check が誤りの文の一覧で返す。
"""
import contextlib
import dataclasses
import datetime
import json
import os
import pathlib
import shutil
import subprocess
import sys
import time
import types
from typing import Mapping, TypedDict

# pack の中に __pycache__ を作らない（下で import する写しの engine の分。accept.py と同じ）
sys.dont_write_bytecode = True

CORE = pathlib.Path(__file__).resolve().parent
_GL = CORE / "graphloops"
for _p in (_GL, CORE):   # 写しの engine（graphloops/engine）と、works の tree_run（この置き場）
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import engine.util as _util  # noqa: E402
from engine import pointers as _pointers  # noqa: E402
from engine.advance import ENGINE_HELPERS, helper_argv, load_item, open_next_round, run_driver_node  # noqa: E402
from engine.board import Board as _EngineBoard, empty_round, refuse_expression_conds  # noqa: E402
from engine.commands import (STOPPED_BY, _refuse_halted, choice_input_errors, engine_run_refusal,  # noqa: E402
                             max_rounds_for, path_inputs, retire_out, stop_descendants, thicken, undeclared_inputs)
from engine.record import apply_writes  # noqa: E402
from engine.rules import hook, load_rules, registry  # noqa: E402
from engine.schema import expand_refs, graph_text, load_graph, resolve_extends, validate_schema  # noqa: E402
from engine.role_run import _tail  # noqa: E402
from engine.util import (ANSWER_ACTIONS, IN_ROUND_ACTIONS, TERMINAL_STATUS, AnswerReject, Reject, now,  # noqa: E402
                         safe_name, write_json)
from engine.validator import finalize as _finalize_record, report_accepts  # noqa: E402
import tree_run  # noqa: E402

CORE_DIR = CORE
GRAPH_PATH = _GL / "graphs" / "review-loop.json"      # 写しの graph
VALIDATOR_PATH = CORE / "scripts" / "review-record.py"  # 写しの RR（検証器）
GRAPH_SHA = _util.sha(graph_text(GRAPH_PATH))         # 盤面の state.graph_sha と比べる値（engine の init と同じ求め方）
BOARD_VERSION = 1                                     # state.works.board_version。知らない版の盤面は開かない
LANG_DEFAULT = "依頼文の言語（利用者の言語）"          # engine の cmd_init が inputs.lang に置く既定の文


# ---------------------------------------------------------------- 誤りの型
class BoardGap(Exception):
    """内部の誤り（表の欠け・配線の誤り・保存できない盤面への保存・効かない差し替え）。役に返しても直らない"""


class BoardMismatch(BoardGap):
    """盤面を開かない（graph_sha・board_version・表の graph_sha が合わない）。文に両方の値を出す"""


class RecordInvalid(BoardGap):
    """報告の前の関所（pre: finalize の節を出す前の検証器）が通らない。engine は die で exit 1（fail loud）——settle は最後の保存の
    後に投げる（仕上げの記録・trace の validator_failed・settle の進みは盤面に残る）。呼び直せば関所をやり直す（engine の next と同じ）。
    node は出さなかった節、exit・out は検証器の終了コードと出力（exit None は検証器が動かない）"""

    def __init__(self, node, exit, out):
        self.node, self.exit, self.out = node, exit, out
        super().__init__(f"{node}: 記録が検証器を通らない（exit {exit}）——出さない。engine か rules か節の出力の欠陥"
                         f"（record.json と trace.jsonl を見て直す）:\n{out}")


class Progress(TypedDict):
    """settle まで回す口の返り（仕様 4.1）。ready は依存が済んで待っている、表で role・machine・engine_run の節と、
    壁で止めた explicit の機械の節（ラインが次に作る・回す物。人に聞いている間と止めた run は空）。
    asking は state.pending_human、halted は state.halted、notes は止まった理由と機械の節の知らせ"""
    round: int
    ready: list
    asking: dict | None
    halted: dict | None
    notes: list


# ---------------------------------------------------------------- 節の表
BY = ("role", "machine", "engine_run", "builtin", "absent")
RUNS = ("auto", "explicit")                 # builtin の節の回し方（auto は settle がその場で、explicit はラインが run_builtin で）
FALLBACKS = ("machine", "role", "absent")   # engine_run の節が任せ先に落ちたときの持ち方
# 任せ先の仕事が判断（交差した hunk を読んで担当の PR に申し送る）なので、ラインの script（machine）には持たせない節
JUDGED_FALLBACK = {"p0.parallel_pr": ("role", "absent")}


@dataclasses.dataclass(frozen=True)
class NodeEntry:
    """表の 1 節。by 以外の欄は既定なら表のファイルに書かなくてよい"""
    by: str
    run: str = "auto"
    fallback: str = ""
    skippable: bool = False
    reason: str = ""
    where: str = ""
    comes_with: str = ""


_ENTRY_FIELDS = {f.name: f for f in dataclasses.fields(NodeEntry)}
_TOP_KEYS = ("line", "graph_sha", "nodes")


def _no_duplicate_keys(pairs):
    """json の object を組む hook。同じ鍵が 2 度在れば BoardGap（json は黙って後の値を取るため）"""
    seen = {}
    for k, v in pairs:
        if k in seen:
            raise BoardGap(f"同じ鍵が 2 度在る: {k}")
        seen[k] = v
    return seen


def _entry(nid, raw) -> NodeEntry:
    """表のファイルの 1 節を NodeEntry にする（形の誤りは BoardGap）"""
    if not isinstance(raw, dict):
        raise BoardGap(f"節 {nid} が object でない")
    unknown = sorted(set(raw) - set(_ENTRY_FIELDS))
    if unknown:
        raise BoardGap(f"節 {nid} に知らない欄: {', '.join(unknown)}")
    if "by" not in raw:
        raise BoardGap(f"節 {nid} に by が無い")
    for k, v in raw.items():
        want = bool if k == "skippable" else str
        if type(v) is not want:
            raise BoardGap(f"節 {nid} の {k} が {want.__name__} でない: {v!r}")
    return NodeEntry(**raw)


def _graph_kind(g) -> str:
    """graph の節の種類: driver（機械の節）・engine_run（engine が走らせる節）・plain（どちらでもない）"""
    if g.get("run_by") == "driver":
        return "driver"
    return "engine_run" if "engine_run" in g else "plain"


# 表の by と、それを持てる graph の節の種類（absent はどの節にも付く）
_BY_KIND = {"builtin": "driver", "engine_run": "engine_run", "role": "plain", "machine": "plain"}
_KIND_WORD = {"driver": "機械の節（run_by: driver）", "engine_run": "engine が走らせる節（engine_run）",
              "plain": "機械の節でも engine が走らせる節でもない節"}


@dataclasses.dataclass(frozen=True)
class NodeTable:
    """節の表。nodes は読むだけの Mapping（表の順を保つ）"""
    line: str
    graph_sha: str
    nodes: Mapping[str, NodeEntry]

    def __post_init__(self):
        nodes = dict(self.nodes)
        for nid, e in nodes.items():
            if not isinstance(e, NodeEntry):
                raise BoardGap(f"節 {nid} の値が NodeEntry でない: {e!r}")
        object.__setattr__(self, "nodes", types.MappingProxyType(nodes))

    @classmethod
    def load(cls, path: pathlib.Path) -> "NodeTable":
        """表のファイルを読む。読めない・同じ鍵が 2 度・形の誤りは BoardGap（graph との突き合わせは check）"""
        path = pathlib.Path(path)
        try:
            doc = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_no_duplicate_keys)
        except BoardGap as e:
            raise BoardGap(f"節の表 {path}: {e}") from None
        except (OSError, ValueError) as e:
            raise BoardGap(f"節の表 {path} を読めない: {e}") from None
        try:
            if not isinstance(doc, dict):
                raise BoardGap("表が object でない")
            unknown = sorted(set(doc) - set(_TOP_KEYS))
            if unknown:
                raise BoardGap(f"知らない欄: {', '.join(unknown)}")
            for k in _TOP_KEYS:
                if k not in doc:
                    raise BoardGap(f"{k} が無い")
            for k in ("line", "graph_sha"):
                if not isinstance(doc[k], str):
                    raise BoardGap(f"{k} が文字列でない: {doc[k]!r}")
            if not isinstance(doc["nodes"], dict):
                raise BoardGap("nodes が object でない")
            nodes = {nid: _entry(nid, raw) for nid, raw in doc["nodes"].items()}
        except BoardGap as e:
            raise BoardGap(f"節の表 {path}: {e}") from None
        return cls(doc["line"], doc["graph_sha"], nodes)

    @classmethod
    def everything(cls, graph: dict, graph_sha: str) -> "NodeTable":
        """graph の全部の節をラインが持つ表（手本の再生用）。機械の節は builtin/auto、
        engine が走らせる節は engine_run（任せ先は p0.parallel_pr が role、他は machine）、残りは role"""
        nodes = {}
        for nid, g in graph["nodes"].items():
            kind = _graph_kind(g)
            if kind == "driver":
                nodes[nid] = NodeEntry(by="builtin")
            elif kind == "engine_run":
                nodes[nid] = NodeEntry(by="engine_run", fallback="role" if nid in JUDGED_FALLBACK else "machine")
            else:
                nodes[nid] = NodeEntry(by="role")
        return cls("everything", graph_sha, nodes)

    def check(self, graph: dict, graph_sha: str) -> list[str]:
        """仕様 4.2 の縛り 1〜5 を当て、破った物の文の一覧を返す（空なら通る）。graph は写しの graph の dict、
        graph_sha はその engine の sha(graph_text(...))。見る graph の欄は run_by・engine_run・optional だけ"""
        errs = []
        gnodes = graph["nodes"]
        # 縛り 2: 表の graph_sha が写しの graph と同じ
        if self.graph_sha != graph_sha:
            errs.append(f"表の graph_sha {self.graph_sha} が写しの graph の {graph_sha} と違う")
        # 縛り 1: graph の全部の節が表にちょうど 1 度ずつ（同じ鍵 2 度は load が拒む）
        missing = [n for n in gnodes if n not in self.nodes]
        if missing:
            errs.append(f"graph の節が表に無い: {', '.join(missing)}")
        extra = [n for n in self.nodes if n not in gnodes]
        if extra:
            errs.append(f"graph に無い節が表に在る: {', '.join(extra)}")
        for nid, e in self.nodes.items():
            g = gnodes.get(nid)
            if g is None:
                continue
            kind = _graph_kind(g)
            if e.by not in BY:
                errs.append(f"{nid}: 知らない by {e.by!r}（{' / '.join(BY)} のどれか）")
                continue
            # 縛り 3: builtin は driver の節だけ、engine_run は engine_run を持つ節だけ、role・machine はどちらでもない節だけ
            if e.by != "absent" and _BY_KIND[e.by] != kind:
                errs.append(f"{nid}: by {e.by} は{_KIND_WORD[_BY_KIND[e.by]]}だけに付く（この節は{_KIND_WORD[kind]}）")
            # 縛り 4: absent の reason は空でない。engine_run の fallback は必須で決まった値（p0.parallel_pr は判断なので role か absent）
            if e.by == "absent" and not e.reason.strip():
                errs.append(f"{nid}: absent の reason が空")
            if e.by == "engine_run":
                allowed = JUDGED_FALLBACK.get(nid, FALLBACKS)
                if e.fallback not in allowed:
                    got = repr(e.fallback) if e.fallback else "無い"
                    errs.append(f"{nid}: engine_run の fallback が {got}（{' / '.join(allowed)} のどれか）")
            elif e.fallback:
                errs.append(f"{nid}: fallback は engine_run の節だけの欄（by {e.by}）")
            if e.by == "builtin":
                if e.run not in RUNS:
                    errs.append(f"{nid}: builtin の run が {e.run!r}（{' / '.join(RUNS)} のどれか）")
            elif e.run != "auto":
                errs.append(f"{nid}: run は builtin の節だけの欄（by {e.by}）")
            # 縛り 5: skippable は graph で optional の節だけ（engine の skip は optional でない節を拒む）
            if e.skippable and not g.get("optional"):
                errs.append(f"{nid}: skippable は graph で optional の節だけに付く")
        return errs

    def absent(self) -> list[dict]:
        """このラインに無い節の全部 [{node, reason, comes_with}]（表の順）。盤面の state.works.not_in_line に書く物"""
        return [{"node": nid, "reason": e.reason, "comes_with": e.comes_with}
                for nid, e in self.nodes.items() if e.by == "absent"]

    def sha(self) -> str:
        """表の中身の sha（engine の util.sha と同じ 12 桁）。既定の欄は数えないので、書き方によらず同じ表なら同じ値"""
        nodes = {nid: {k: v for k, v in dataclasses.asdict(e).items()
                       if k == "by" or v != _ENTRY_FIELDS[k].default}
                 for nid, e in self.nodes.items()}
        doc = {"line": self.line, "graph_sha": self.graph_sha, "nodes": nodes}
        return _util.sha(json.dumps(doc, ensure_ascii=False, sort_keys=True, separators=(",", ":")))


# ---------------------------------------------------------------- 盤面なしで写しを読む口
def graph_expanded(graph: pathlib.Path | None = None) -> dict:
    """$ref を開いた graph（engine の load_graph）に、$ref を開いた $defs を戻した物。graph を渡さなければ写しの graph。
    engine の load_graph は $defs を落とすが、線 C は型（$defs.lane_reply・gate_arm）をここから読む。読めなければ BoardGap"""
    path = str(graph or GRAPH_PATH)
    g, why = load_graph(path)
    if why:
        raise BoardGap(why)
    try:
        raw = resolve_extends(path, _util.read_json).get("$defs") or {}
        opened = expand_refs({"$defs": raw, "nodes": {k: {"schema": v} for k, v in raw.items()}})["nodes"]
    except ValueError as e:
        raise BoardGap(f"{path}: {e}") from None
    g["$defs"] = {k: v["schema"] for k, v in opened.items()}
    return g


def rules_module(graph: pathlib.Path | None = None):
    """写しの RL を読み込んだ module（engine の load_rules。呼ぶたびに新しく読むので、差し替えは他に漏れない）"""
    path = str(graph or GRAPH_PATH)
    return load_rules(path, graph_expanded(path))


# ---------------------------------------------------------------- engine が走らせる節の既定の runner
def tree_runner(steps: list, cwd, log_dir) -> list:
    """run_engine の既定の runner（仕様 4.3）: 段を 1 つずつ works の tree_run で走らせる——shell を通さない・別のプロセス
    グループ・期限なし・標準入力は空・uv run の環境を外す（tree_run.outside_env。blk-tests の run_tests と同じ 1 本）・止められたら SIGTERM → KILL_GRACE（2 秒）→ SIGKILL で
    木ごと止めて tree_run.Stopped を投げる（ここでは捕まえない）。標準出力・標準エラーは log_dir/<段の番号>.out・.err に丸ごと。
    返りの行は engine の run_steps と同じ鍵 {name, argv, out, err, exit, wall_s, tail}（起こせなければ exit None と error）。
    engine と違う所: 信号で死んだ段の exit は tree_run の 128+信号（engine は負の番号）。どちらも赤に読まれる。
    子の環境は uv run の外の形で、PYTHONDONTWRITEBYTECODE=1 を立てる（works の決まり。engine の run_steps は環境をそのまま継ぐ）"""
    log_dir = pathlib.Path(log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)
    env = tree_run.outside_env(os.environ)
    runs = []
    for i, s in enumerate(steps):
        started = time.time()
        base = log_dir / f"{i + 1}"
        row = {"name": s["name"], "argv": list(s["argv"]), "out": str(base) + ".out", "err": str(base) + ".err"}
        with open(row["out"], "wb") as out, open(row["err"], "wb") as err:
            try:
                rc = tree_run.run(list(s["argv"]), stdin=subprocess.DEVNULL, stdout=out, stderr=err, cwd=str(cwd), env=env)
            except OSError as e:
                rc = None
                row["error"] = str(e)
                err.write(str(e).encode("utf-8"))
        data = pathlib.Path(row["out"]).read_bytes() + b"\n" + pathlib.Path(row["err"]).read_bytes()
        row.update(exit=rc, wall_s=round(time.time() - started, 1), tail=_tail(data))
        runs.append(row)
    return runs


# ---------------------------------------------------------------- 盤面
def _read_json(path: pathlib.Path) -> dict:
    """盤面のファイルを読む。読めなければ BoardGap（engine の read_json は die で終わるので使わない）"""
    try:
        return json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise BoardGap(f"{path} を読めない: {e}") from None


def _core() -> dict:
    """state.works.core: 写しの元の commit（COPIED_FROM の 1 行目）と、今の写しの置き場"""
    first = (CORE_DIR / "COPIED_FROM").read_text(encoding="utf-8").splitlines()[0]
    return {"commit": first.split()[0], "path": str(CORE_DIR)}


def _refuse_unowned(nid, n) -> None:
    """盤面の層が持たない節の形（扇の節 fan_out・段の昇格 thickness_from）を黙って回さない。a1202d0 の graph には無い
    （再生の比べない欄 NOT_REPRODUCED の「扇の被覆」「段の昇格」）。写し直しで入ったら、ここで止まる"""
    for key, what in (("fan_out", "扇の節（項目ごとの instance・被覆）"), ("thickness_from", "段の昇格")):
        if key in n:
            raise BoardGap(f"節 '{nid}' は {key} を持つ——{what}は盤面の層が持たない（a1202d0 の graph に無い形）")


def _check_table(table: "NodeTable") -> None:
    """節の表の縛り 1〜5（仕様 4.2）。表の graph_sha の違いは BoardMismatch、他の破れは BoardGap"""
    if not isinstance(table, NodeTable):
        raise BoardGap(f"節の表が NodeTable でない: {type(table).__name__}")
    if table.graph_sha != GRAPH_SHA:
        raise BoardMismatch(f"節の表の graph_sha {table.graph_sha} が写しの graph の {GRAPH_SHA} と違う")
    errs = table.check(graph_expanded(), GRAPH_SHA)
    if errs:
        raise BoardGap("節の表が graph と合わない: " + "; ".join(errs))


def _captured(rules) -> dict:
    """RL の BUILTINS・CONDS・POST_CHECKS・ENGINE_RUNS が値として掴んでいる関数 {id: 表の名前}。
    これらは読み込みの時に関数を掴むので、大域の名前を差し替えても効かない"""
    out = {}
    for reg in ("BUILTINS", "CONDS", "POST_CHECKS", "ENGINE_RUNS"):
        for v in registry(rules, reg).values():
            for fn in (v.values() if isinstance(v, dict) else (v,)):
                out.setdefault(id(fn), reg)
    return out


class DiskBoard(_EngineBoard):
    """ディスクの盤面（仕様 4.1）。写した engine の Board を継ぎ、engine の属性と関数はそのまま使う。
    上書きするのは __init__・save・run_validator だけ。開く・作るは open・create、v1 の受け付けの入れ物は scratch"""

    def __init__(self, d, *, state, record, table, overrides=None, validator_runner=None, allow_halted=False, scratch=False):
        """渡された state・record の dict から組む（engine の Board.__init__ と同じ順）。state の中の pack のパスは
        写しのパスに記憶の中だけで読み替え（仕様 4.4 の 4）、overrides を当てる（4.4 の 5）。scratch の入れ物は GIT_CWD を触らない"""
        self.dir = pathlib.Path(d)
        self.state = state
        self._rewrite_paths()
        if not scratch:
            _util.GIT_CWD = (self.state.get("inputs") or {}).get("cwd")
        self.seen_rev = self.state.get("rev", 0)
        self.halted_at_read = bool(self.state.get("halted"))
        self.record = record
        self.graph, why = load_graph(self.state["graph"])
        if why:
            raise BoardGap(why)
        self.nodes = self.graph["nodes"]
        refuse_expression_conds(self.state["graph"], self.nodes)
        self.rules = load_rules(self.state["graph"], self.graph)
        # works の欄（engine の Board に無い物）
        self.table = table
        self.validator_runner = validator_runner
        self._scratch = scratch
        self._notes = []      # settle の輪が集める知らせ（機械の節の notes と止まった理由）
        self._walls = []      # settle の輪の最後の段で当たった explicit の機械の節（ready に出す）
        self._record_invalid = None   # settle の輪で報告の前の関所が通らなかった時の RecordInvalid（最後の保存の後に投げる）
        if allow_halted:
            self.allow_halted = True
        self._apply_overrides(overrides or {})

    def _rewrite_paths(self):
        """state の pack のパス（graph・validator・inputs.scripts_dir・inputs.review_md）を今の写しのパスにする。
        Archon は run ごとに pack を写すので、盤面が持つパスは古い写しを指しうる。ディスクは書かない（保存すれば今のパスで残る）"""
        self.state["graph"] = str(GRAPH_PATH)
        self.state["validator"] = str(VALIDATOR_PATH)
        inputs = self.state.get("inputs")
        if isinstance(inputs, dict):
            if "scripts_dir" in inputs:
                inputs["scripts_dir"] = str(VALIDATOR_PATH.parent)
            if "review_md" in inputs:
                inputs["review_md"] = str(CORE_DIR / "REVIEW.md")

    def _apply_overrides(self, overrides):
        """RL の module の大域の名前を差し替え、state.works.overrides に名前と理由を足す（前に開いた時の分は消さない）。
        RL は開くたびに新しく読むので、差し替えは他の盤面に漏れない"""
        if not overrides:
            return
        captured = _captured(self.rules)
        rows = []
        for name, spec in overrides.items():
            if not (isinstance(spec, tuple) and len(spec) == 2):
                raise BoardGap(f"overrides の {name} が (関数, 理由) でない: {spec!r}")
            fn, reason = spec
            if not callable(fn):
                raise BoardGap(f"overrides の {name} の関数が呼べない: {fn!r}")
            if not (isinstance(reason, str) and reason.strip()):
                raise BoardGap(f"overrides の {name} に理由が無い")
            if not isinstance(name, str) or not hasattr(self.rules, name):
                raise BoardGap(f"overrides の {name} は RL の大域の名前に無い（綴り違いの差し替えは効かない）")
            reg = captured.get(id(getattr(self.rules, name)))
            if reg:
                raise BoardGap(f"overrides の {name} は RL の {reg} が値として掴んでいる関数で、大域の名前を差し替えても効かない")
            rows.append({"name": name, "reason": reason})
        for name, (fn, _) in overrides.items():
            setattr(self.rules, name, fn)
        kept = self.state.setdefault("works", {}).setdefault("overrides", [])
        kept.extend(r for r in rows if r not in kept)

    # -- 開く・作る
    @classmethod
    def open(cls, d, *, table, repo=None, overrides=None, validator_runner=None, allow_halted=False) -> "DiskBoard":
        """盤面を開く（仕様 4.4 の順: graph_sha → board_version → 表の縛り → パスの読み替え → overrides）。
        util.GIT_CWD は inputs.cwd（repo を渡せばそれ）。state.works.core を今の写しで書き直す（保存すれば残る）"""
        d = pathlib.Path(d)
        state = _read_json(d / "state.json")
        got = state.get("graph_sha")
        if got != GRAPH_SHA:
            raise BoardMismatch(f"盤面 {d} の graph_sha {got} が写しの graph の {GRAPH_SHA} と違う（別の版の graph で作った盤面は開かない）")
        works = state.get("works")
        version = works.get("board_version") if isinstance(works, dict) else None
        if version != BOARD_VERSION:
            raise BoardMismatch(f"盤面 {d} の board_version {version if version is not None else '（無い）'} を知らない"
                                f"（この盤面の層は {BOARD_VERSION}）")
        _check_table(table)
        record = _read_json(d / "record.json")
        b = cls(d, state=state, record=record, table=table, overrides=overrides, validator_runner=validator_runner,
                allow_halted=allow_halted)
        if repo is not None:
            _util.GIT_CWD = str(pathlib.Path(repo).resolve())
        b.state["works"]["core"] = _core()
        return b

    @classmethod
    def create(cls, d, *, repo, table, inputs, request_text, max_rounds=None, stop_after_round=None, unattended=False,
               overrides=None, validator_runner=None) -> "DiskBoard":
        """盤面を作る（engine の cmd_init と同じ順と入口の検査。仕様 4.1 の 1〜5）。入口で拒めば置き場を作らず、
        作った後のどこかで例外なら置き場を消して投げ直す（空の盤面を残さない）。既に在る置き場には作らない（BoardGap）。
        unattended は engine の init --unattended（人の答えを待たずに RL の保守的な既定で進む run）。入口の文（止める周が
        1 未満・graph に宣言の無い入力の notes）は engine の cmd_init と同じ文"""
        d = pathlib.Path(d).resolve()
        _check_table(table)
        if stop_after_round is not None and type(stop_after_round) is not int:
            raise BoardGap(f"stop_after_round は整数（{stop_after_round!r}）——止める周の番号で、その周の締めの後で止まる")
        if stop_after_round is not None and stop_after_round < 1:
            raise BoardGap(f"--stop-after-round は 1 以上（{stop_after_round}）——止める周の番号で、その周の締めの後で止まる")
        if type(unattended) is not bool:
            raise BoardGap(f"unattended は真偽（{unattended!r}）")
        graph = graph_expanded()
        rules = load_rules(str(GRAPH_PATH), graph)
        # 1〜2: inputs に engine と同じ既定を足し、パスの入力を絶対にし、RL と graph の選ぶ入力の値を確かめる
        ins = {"request": request_text, "document": None, "lang": LANG_DEFAULT, "cwd": str(pathlib.Path(repo).resolve()),
               **(inputs or {})}
        for k in path_inputs(graph):
            if ins.get(k):
                ins[k] = str(pathlib.Path(ins[k]).resolve())
        fn = hook(rules, "check_inputs")
        if fn:
            fn(ins)
        bad = choice_input_errors(graph, ins)
        if bad:
            raise Reject("; ".join(bad))
        notes = [f"--input {k}=… は graph の inputs に宣言が無く、どの節も rules も読まない（効かない）——綴りを確かめよ"
                 f"（宣言済みの入力: {', '.join(sorted(graph.get('inputs') or {}))}）" for k in undeclared_inputs(graph, list(inputs or {}))]
        # 3: 最終の置き場
        try:
            d.mkdir(parents=True, exist_ok=False)
        except FileExistsError:
            raise BoardGap(f"盤面の置き場 {d} が既に在る（盤面は作り直さない）") from None
        try:
            record = hook(rules, "init_record")(None, None)
            state = {
                "loop_name": graph["loop"], "run_id": datetime.datetime.now().astimezone().strftime("%Y%m%d-%H%M%S"),
                "graph": str(GRAPH_PATH), "graph_sha": GRAPH_SHA,
                "created": now(), "status": "running", "round": 1, "rounds": [empty_round(1)],
                "thickness": None, "max_rounds": max_rounds if max_rounds is not None else max_rounds_for(graph, None),
                "unattended": unattended,
                **({"stop_after_round": stop_after_round} if stop_after_round is not None else {}),
                "inputs": ins, "validator": str(VALIDATOR_PATH), "outputs": {}, "done_ever": {}, "loop": {},
                **({"notes": notes} if notes else {}),
                # 5: works の欄
                "works": {"board_version": BOARD_VERSION, "line": table.line, "table_sha": table.sha(), "core": _core(),
                          "not_in_line": table.absent(), "overrides": []},
            }
            _util.write_json(d / "state.json", state)
            _util.write_json(d / "record.json", record)
            with open(d / "trace.jsonl", "a", encoding="utf-8") as f:
                f.write(json.dumps({"t": now(), "op": "init", "thickness": None, "decider": None,
                                    "line": table.line, "table_sha": table.sha()}, ensure_ascii=False) + "\n")
            # 4: 盤面を開いて RL の on_init（REVIEW.md・scripts の置き場・rounds_dir・方針の文書の固定）→ 保存
            b = cls.open(d, table=table, repo=repo, overrides=overrides, validator_runner=validator_runner)
            fn = hook(b.rules, "on_init")
            if fn:
                fn(b, None)   # engine は init の引数を渡すが、RL の on_init は読まない
            b.save()
        except BaseException:
            shutil.rmtree(d, ignore_errors=True)
            raise
        return b

    @classmethod
    def scratch(cls, board, *, review_rev, record=None, loop_state=None) -> "DiskBoard":
        """v1 の受け付け（accept.py）の入れ物（仕様 7 節）。周 1・空の周の箱の engine の形を記憶の中だけに組む。
        dir は渡された盤面の置き場（RL の count-cache・hook_evidence が読み書きする）、state.validator は写しの RR。
        保存できない（save は BoardGap）。GIT_CWD は触らない（v1 は _in_repo で向ける）。instance は持たない（BL24）"""
        graph = graph_expanded()
        state = {"loop_name": graph["loop"], "run_id": "scratch", "graph": str(GRAPH_PATH), "graph_sha": GRAPH_SHA,
                 "status": "running", "round": 1, "rounds": [empty_round(1)], "thickness": None,
                 "max_rounds": max_rounds_for(graph, None), "inputs": {"review_rev": review_rev},
                 "validator": str(VALIDATOR_PATH), "outputs": {}, "done_ever": {},
                 "loop": loop_state if loop_state is not None else {}}
        b = cls(board, state=state, record={}, table=None, scratch=True)
        b.record = record if record is not None else b.rules.init_record(None, None)
        return b

    @classmethod
    @contextlib.contextmanager
    def edit(cls, d, **open_kw):
        """開いて渡し、抜けるときに save。中で例外なら書かない（その入れ物は捨てる）"""
        b = cls.open(d, **open_kw)
        yield b
        b.save()

    # -- 上書きする関数
    def save(self):
        """scratch の入れ物は保存しない（BoardGap）。他は engine の save（版の突き合わせ・止めた run の拒否）。
        保存した盤面が止めた run（halted）なら、この入れ物の以後の保存も allow_halted 無しでは拒む——engine は手ごとに盤面を
        読み直すので、止めた手の後の手は必ず halted を読んで拒まれる。同じ入れ物で続ける works もそれに揃える"""
        if self._scratch:
            raise BoardGap("scratch の入れ物（v1 の受け付け）は保存しない")
        super().save()
        self.halted_at_read = bool(self.state.get("halted"))

    def run_validator(self, target=None):
        """validator_runner を渡した盤面だけ、それを (盤面, target) で呼ぶ。渡さなければ engine と同じ"""
        if self.validator_runner is not None:
            return self.validator_runner(self, target)
        return super().run_validator(target)

    # -- 役の節の控え（instance）と受け付け
    def _emit(self, nid: str, attempt: int = 1) -> dict:
        """役の節の最小の instance を今の周の箱に置いて返す（仕様 4.1 の「instance の控え」。engine の emit_instance の、
        描画・起動を除いた部分）。id は節の名前（扇の節は a1202d0 の graph に無い）。out_path は engine と同じ置き場
        （本文を返す節は .md。出し直した試行 attempt > 1 は engine と同じく .a<試行> を挟む）で、受けるまで在らない。attempts は試行の数。
        skills は graph の節の skills を写し、applies_cond を持つ要素だけその場で b.cond() を評価して applies・applies_why を置く
        （engine と同じく、出す時点の値を受け付けの柵が読む）"""
        n = self.nodes[nid]
        skills = [{**e, **dict(zip(("applies", "applies_why"), self.cond(e["applies_cond"])))}
                  if isinstance(e, dict) and "applies_cond" in e else e for e in n.get("skills", [])]
        out = self.dir / "out" / f"r{self.round}" / (safe_name(nid) + (f".a{attempt}" if attempt > 1 else "")
                                                     + (".md" if n.get("text") else ".json"))
        inst = {"id": nid, "node": nid, "run_by": n["run_by"], "status": "pending", "emitted_at": now(), "out_path": str(out),
                "attempts": attempt}
        if skills:
            inst["skills"] = skills
        out.parent.mkdir(parents=True, exist_ok=True)
        self.rd["instances"][nid] = inst
        self.trace("emit", instance=nid)
        return inst

    def accept(self, nid: str, output: dict) -> str:
        """ラインの受け付けの口（仕様 4.1）。engine が走らせる節（graph の engine_run）は、任せ先に落ちた（instance が
        engine_fallback を持つ）後だけ受ける——落ちる前の結果は run_engine が engine と同じく組む（engine の cmd_done の拒否と
        同じ。落ちる前の外からの返答は BoardGap〔再審2 m10〕）。中身は _accept"""
        return self._accept(nid, output, engine_reply=False)

    def _accept_engine_reply(self, nid: str, reply: dict) -> str:
        """run_engine の中の受け付け（engine の launch_engine_run の accept_output）。落ちる前の engine_run の節を受ける口"""
        return self._accept(nid, reply, engine_reply=True)

    def _accept(self, nid: str, output: dict, *, engine_reply: bool) -> str:
        """役（か機械の返答・engine が走らせた節）の返答を受けて盤面と記録に写し、保存する（engine の accept_output と同じ範囲。
        settle しない）。順は engine と同じ: 止めた run の拒否 → instance → 依存 → 型 → 番号の読み替え → post_check →
        writes → check_record → out/r<N>/<節>.json → state.outputs → instance を done → 周の箱の done・done_ever → trace → 保存。
        返答の中身の誤りは engine の AnswerReject と同じ文で拒み、盤面（ディスク）は書かない（記憶の入れ物は汚れうるので捨てる）。
        ラインの配線の誤り（表で受けられない節・待っている instance が無い・依存が済んでいない）は BoardGap。
        engine の受け付けのうち、描画・起動に関わる所（read_from・agent_id・tree_before の突合・save_text_as）は持たない
        （再生の比べない欄 tests/boardreplay.py の NOT_REPRODUCED）。扇の節・段の昇格を持つ節は受けずに BoardGap。
        本文を返す節の返答は {text} だけ（engine と同じく他の鍵は届かない形。余分な鍵は BoardGap）"""
        _refuse_halted(self)
        n = self.nodes.get(nid)
        if n is None:
            raise BoardGap(f"節 '{nid}' は graph に無い")
        entry = (self.table.nodes.get(nid) if self.table is not None else None)
        if entry is None or entry.by not in ("role", "machine", "engine_run"):
            by = entry.by if entry is not None else "（表が無い）"
            raise BoardGap(f"節 '{nid}' は表で {by}——accept で受けるのは role・machine・engine_run の節だけ"
                           "（機械の節は step_builtin・run_builtin、このラインに無い節は受けない）")
        _refuse_unowned(nid, n)
        inst = self.rd["instances"].get(nid)
        if not inst:
            raise BoardGap(f"この周に節 '{nid}' の instance が出ていない（settle が出した節だけを受ける）")
        if inst["status"] != "pending":
            raise BoardGap(f"節 '{nid}' の instance は既に {inst['status']}（受け直すなら先に rewind で待ちに戻す）")
        if engine_reply and "engine_run" not in n:
            raise BoardGap(f"節 '{nid}' は engine が走らせる節（graph の engine_run）でない——_accept_engine_reply は run_engine の中の口")
        if not engine_reply and "engine_run" in n and not inst.get("engine_fallback"):
            raise BoardGap(f"節 '{nid}' は engine が走らせる節（engine_run）で、まだ任せ先に落ちていない——結果は run_engine が組む"
                           "（ラインの accept・done は受けない。任せ先に落ちた後なら表の fallback の持ち主が渡す）")
        if not self.deps_met(nid):
            wait = [d for d in n.get("deps", []) if self.node_state(d) == "pending"]
            raise BoardGap(f"節 '{nid}' の deps {wait} がまだ済んでいない——先にそちらを受ける")
        output = json.loads(json.dumps(output))   # 呼び出し側の dict を書き換えない（読み替え・post_check は中を書く）
        if n.get("schema"):
            errs = validate_schema(output, n["schema"])
            if errs:
                raise AnswerReject("返答が型に合わない（直して done し直す。回す側が中身を補ってはいけない——役に返させろ）:\n"
                                   + "\n".join(f"  - {e}" for e in errs))
        elif isinstance(output, dict) and set(output) - {"text"}:
            # engine は本文から {text} を組むので、他の鍵は届かない。余分な鍵はラインが返答を組む所の誤り
            raise BoardGap(f"節 '{nid}' は本文を返す節——返答は {{text}} だけ（余分な鍵: {sorted(set(output) - {'text'})}）")
        elif not (isinstance(output, dict) and isinstance(output.get("text"), str) and output["text"].strip()):
            raise AnswerReject(f"節 '{nid}' の返答が空——本文を返す節に空は受け付けない（役が何も返していないか、{inst.get('out_path')} に書けていない）")
        # 番号で指した欄を名前に戻す。一覧を固めた控え（instance.pointers）を持たないので、番号は engine の文で拒まれる（BL17）
        errs = _pointers.resolve(output, n.get("pointers"), None)
        if errs:
            raise AnswerReject(f"{nid}: " + "; ".join(errs))
        item = load_item(inst, self.dir)
        notes = []
        pc = n.get("post_check")
        if pc:
            fn = registry(self.rules, "POST_CHECKS").get(pc)
            if not fn:
                raise BoardGap(f"post_check '{pc}' が rules に無い")
            try:
                note = fn(self, nid, output, item)
            except AnswerReject:
                raise
            except Reject as e:   # 節ごとの整合（rules）は返答の中身を見る——役に返せば直る側（engine と同じ）
                raise AnswerReject(str(e)) from e
            if note:
                notes.append(note)
        apply_writes(self, nid, output, item)
        check = hook(self.rules, "check_record")
        if check:
            errs = check(self, nid)
            if errs:
                raise AnswerReject("記録の整合が取れない（役に返させ直す。回す側が補ってはいけない）:\n"
                                   + "\n".join(f"  - {e}" for e in errs))
        f = self.dir / "out" / f"r{self.round}" / (safe_name(nid) + ".json")
        write_json(f, output)
        rel = str(f.relative_to(self.dir))
        self.state["outputs"][nid] = {"file": rel, "round": self.round, "instance": nid}
        inst.update({"status": "done", "done_at": now(), "output_file": rel})
        if "fan_out" not in n:
            self.rd["done"][nid] = {"at": now(), "instance": nid}
            self.state["done_ever"][nid] = self.round
        text = output["text"] if not n.get("schema") else json.dumps(output, ensure_ascii=False, sort_keys=True)
        self.trace("done", instance=nid, sha=_util.sha(text))
        self.save()
        return "。".join([f"ok {nid} を受け付けた", *notes])

    # -- 機械の節と settle（engine の advance の輪）
    def _entry(self, nid: str) -> NodeEntry:
        if self.table is None:
            raise BoardGap("節の表が無い入れ物（scratch）は settle・機械の節を回さない")
        e = self.table.nodes.get(nid)
        if e is None:
            raise BoardGap(f"節 '{nid}' が表に無い")
        return e

    def _check_builtin(self, nid: str) -> NodeEntry:
        """機械の節を 1 つ回してよいか（表で builtin・待ち・依存が済んだ・人に聞いていない）。配線の誤りは BoardGap"""
        n = self.nodes.get(nid)
        if n is None:
            raise BoardGap(f"節 '{nid}' は graph に無い")
        e = self._entry(nid)
        if e.by != "builtin" or n.get("run_by") != "driver":
            raise BoardGap(f"節 '{nid}' は表で {e.by}——機械の節（builtin）だけを回す")
        if self.state.get("pending_human"):
            raise BoardGap(f"人に聞いている間（{self.state['pending_human'].get('node')}）は機械の節を回さない——先に answer")
        if self.node_state(nid) != "pending":
            raise BoardGap(f"節 '{nid}' は既に {self.node_state(nid)}")
        if not self.deps_ok(nid):
            wait = [d for d in n.get("deps", []) if self.node_state(d) == "pending"]
            raise BoardGap(f"節 '{nid}' の deps {wait} がまだ済んでいない")
        return e

    def step_builtin(self, nid: str) -> dict:
        """機械の節を 1 つだけ回して保存する（engine の run_driver_node。settle しない）。返りは {progressed, notes}
        （progressed が偽なら止まった——通らない・人に聞く・stop_after_round の周の締め。理由は notes）。
        条件（cond）は見ない（見るのは settle と run_builtin）。止めた run には書かない（engine の Reject）"""
        _refuse_halted(self)
        self._check_builtin(nid)
        notes = []
        progressed = run_driver_node(self, nid, self.nodes[nid], notes)
        self._mark_recorded(nid)
        self.save()
        return {"progressed": progressed, "notes": notes}

    def run_builtin(self, nid: str, accept_tree_change: str | None = None) -> Progress:
        """表で explicit の機械の節を回す（ラインが段の境で呼ぶ）: 読んだ物の控えを消して accept_tree_change を置き直し、
        条件に当たらなければ na、当たれば step_builtin → settle（同じ accept_tree_change）。
        auto の節（settle が回す）・機械の節でない節・待っていない・依存が済んでいない節は BoardGap"""
        _refuse_halted(self)
        if self._check_builtin(nid).run != "explicit":
            raise BoardGap(f"節 '{nid}' は表で auto——settle が回す（run_builtin は explicit の節だけ）")
        self._fresh_reads(accept_tree_change)   # 前の settle の控え・理由のまま回さない（engine は next ごとに新しいプロセス）
        why = self.applicable(nid)
        if why:
            self.rd["na"][nid] = why
            self.save()
            notes = [f"{nid}: 条件に当たらない（{why}）"]
        else:
            notes = self.step_builtin(nid)["notes"]
        p = self.settle(accept_tree_change)
        p["notes"] = notes + p["notes"]
        return p

    def done(self, nid: str, output: dict) -> Progress:
        """役（か機械の返答）の返答を受けて、settle まで回す（loop.py done → next）"""
        msg = self.accept(nid, output)
        p = self.settle()
        p["notes"] = [msg] + p["notes"]
        return p

    # -- engine が走らせる節（仕様 4.3）
    def run_engine(self, nid: str, *, runner=None, plan=None) -> dict:
        """engine が走らせる節（graph の engine_run）を、engine の「出す時の計画」と launch（launch_engine_run）を 1 つに
        つないだ順で走らせ、受け付けまで済ませる（settle しない）。返り {ok, node, fallback?, blocked?, runs?, why?, relaunch?}。
        1. 計画: plan を渡されなければ RL の ENGINE_RUNS[builtin].plan（渡すのは撮った計画を差し込む試験）。形は 4 つ——
           steps（対象の宣言の語）・helper（engine に同梱の語。写しの graphloops/scripts/<名前> を今の Python で）・
           blocked（走らせずに返答を組む）・fallback（任せ先へ。7）
        2. steps・helper は走らせる直前に engine の engine_run_refusal（対象のルートの宣言と sha の照合）を当てる。拒めば
           {ok: False, why, relaunch: True} を返し、盤面は書かず、節は待ちのまま（呼び直す＝今の宣言で計画し直す）
        3. runner(steps, cwd=リポジトリのルート, log_dir=runs/r<N>/<id>.a<k>/。k は空いた最初の番号)（既定は tree_runner）。tree_run.Stopped は
           盤面を書かずに投げ直す（Archon の取り消し・Ctrl-C。節は待ちのまま）
        4. RL の ENGINE_RUNS[builtin].reply → 返りが fallback なら 7。そうでなければ instance に engine と同じ mode・launch を
           置いて _accept_engine_reply。受け付けが拒めば（AnswerReject）7
        7. 任せ先へ落とす（_fall_back）: 記憶を捨ててディスクから読み直し、self に入れ直し、RL の fallback（checks_fallback は
           process.checks[nid] = {by: "role"}）→ 節の instance を engine_fallback つきで出し直す → 表の fallback が absent なら
           skipped に表の理由 → 保存。machine・role なら節は待ちのまま ready に残り、ラインが done で渡す。
        配線の誤り（graph の engine_run でない・表で engine_run でない・待っている instance が無い・既に任せ先に落ちた・依存が
        済んでいない・ENGINE_RUNS に無い・同梱に無い helper）は BoardGap。止めた run は engine の Reject"""
        _refuse_halted(self)
        n = self.nodes.get(nid)
        if n is None or "engine_run" not in n:
            raise BoardGap(f"節 '{nid}' は engine が走らせる節（graph の engine_run）でない")
        e = self._entry(nid)
        if e.by != "engine_run":
            raise BoardGap(f"節 '{nid}' は表で {e.by}——run_engine は表で engine_run の節だけを走らせる")
        inst = self.rd["instances"].get(nid)
        if not inst or inst["status"] != "pending":
            raise BoardGap(f"この周に節 '{nid}' の待っている instance が無い（settle が出した節だけを走らせる）")
        if inst.get("engine_fallback"):
            raise BoardGap(f"節 '{nid}' は任せ先に落ちた（{inst['engine_fallback']}）——表の fallback（{e.fallback}）の持ち主が done で渡す")
        if not self.deps_met(nid):
            wait = [d for d in n.get("deps", []) if self.node_state(d) == "pending"]
            raise BoardGap(f"節 '{nid}' の deps {wait} がまだ済んでいない")
        builtin = n["engine_run"]["builtin"]
        er = registry(self.rules, "ENGINE_RUNS").get(builtin)
        if not er:
            raise BoardGap(f"engine_run.builtin '{builtin}' が rules の ENGINE_RUNS に無い")
        self._drop_read_caches()   # 前の受け付け・settle の控えのまま計画と返答を組まない（engine は launch ごとに読み直す）
        if plan is None:
            plan = er["plan"](self, nid)
        if "fallback" in plan:
            return self._fall_back(nid, er, plan["fallback"], {})
        if "helper" in plan:
            if plan["helper"] not in ENGINE_HELPERS:
                raise BoardGap(f"{nid}: 同梱の語 '{plan['helper']}' は engine の ENGINE_HELPERS に無い")
            steps = [{"name": plan["helper"], "argv": helper_argv(plan["helper"], plan.get("args") or [])}]
        else:
            steps = plan.get("steps") or []
        launch = {"kind": "engine_run", "builtin": builtin, "steps": steps, "sha": plan.get("sha"), "blocked": plan.get("blocked")}
        runs = []
        if not launch["blocked"]:
            root = _util.repo_root()
            if not root:
                return {"ok": False, "node": nid, "why": "対象リポジトリのルートが引けない（git rev-parse --show-toplevel）"}
            why = engine_run_refusal({"launch": {"steps": steps, "sha": launch["sha"]}}, root)
            if why:
                return {"ok": False, "node": nid, "why": why, "relaunch": True}
            log_dir = self._log_dir(nid)
            runs = (runner or tree_runner)(steps, pathlib.Path(root), log_dir)
            self.trace("engine_run", instance=nid, node=nid,
                       runs=[{k: r.get(k) for k in ("name", "exit", "wall_s", "error")} for r in runs])
        reply = er["reply"](self, nid, launch, runs)
        if "fallback" in reply:
            return self._fall_back(nid, er, reply["fallback"], {"runs": runs})
        inst["mode"], inst["launch"] = "engine_run", launch
        try:
            self._accept_engine_reply(nid, reply["reply"])
        except AnswerReject as ex:
            return self._fall_back(nid, er, f"engine が組んだ返答を受け付けが拒んだ（{str(ex)[:400]}）", {"runs": runs})
        return {"ok": True, "node": nid, "runs": runs, **({"blocked": launch["blocked"]} if launch["blocked"] else {})}

    def _log_dir(self, nid: str) -> pathlib.Path:
        """走らせた語のログの置き場 runs/r<N>/<id>.a<k>/（engine と同じ名前）。k は空いている最初の番号——engine は instance の
        試行の数（attempts）で分けるが、DiskBoard は試行を数えないので、止められた後の呼び直しで前の走りのログを上書きしない"""
        top = self.dir / "runs" / f"r{self.round}"
        k = 1
        while (top / safe_name(f"{nid}.a{k}")).exists():
            k += 1
        return top / safe_name(f"{nid}.a{k}")

    def _fall_back(self, nid: str, er: dict, reason: str, extra: dict) -> dict:
        """engine の組んだ結果を使えない節を任せ先へ落とす（仕様 4.3 の 7。engine の _engine_fallback と、出す時の計画の
        fallback）。記憶の入れ物は捨て、ディスクから読み直した盤面を self に入れ直してから当てる〔再審 N3・再審2 P2〕"""
        self._reload_from_disk()
        inst = self.rd["instances"].get(nid)
        if not inst or inst["status"] != "pending":
            raise BoardGap(f"読み直した盤面で節 '{nid}' が待っていない——別の手が先に進めた")
        if er.get("fallback"):
            er["fallback"](self, nid, reason)
        inst = self._emit(nid)
        inst["engine_fallback"] = reason
        self.trace("engine_fallback", instance=nid, reason=reason)
        e = self._entry(nid)
        if e.fallback == "absent":
            # このラインに任せ先が無い: engine の skip と同じ印（周の箱の skipped・instance・done_ever・trace）。理由は表の理由
            why = e.reason.strip() or f"任せ先はこのラインに無い（表の fallback: absent）——{reason}"
            self.rd["skipped"][nid] = why
            inst["status"] = "skipped"
            self.state["done_ever"][nid] = self.round
            self.trace("skip", node=nid, reason=why)
        self.save()
        return {"ok": False, "node": nid, "fallback": reason, **extra,
                "why": f"任せ先に回した（表の fallback: {e.fallback}）: {reason}"}

    def _reload_from_disk(self):
        """記憶の state・record を捨て、ディスクの盤面を読み直して self に入れる（seen_rev・halted_at_read も。読んだ物の控えは消す）。
        開いた時に置いた works の欄（core・overrides の控え）と、読み込んだ RL の module（overrides の差し替え）はそのまま"""
        works = self.state.get("works")
        self.state = _read_json(self.dir / "state.json")
        self._rewrite_paths()
        if works is not None:
            self.state["works"] = works
        self.record = _read_json(self.dir / "record.json")
        self.seen_rev = self.state.get("rev", 0)
        self.halted_at_read = bool(self.state.get("halted"))
        self._drop_read_caches()

    def settle(self, accept_tree_change: str | None = None) -> Progress:
        """engine の loop.py next の advance を、役の節は控え（instance）を出すだけにして回す（仕様 4.1 の settle の 1〜5）。
        1. 入口の止め方は engine の cmd_next と同じ: 止めた run・終わって待ちの無い run・人に聞いている間は、何もせず返す（保存もしない）
        2. 読んだ物の控え（_out_cache・_porcelain・_vtables）を消し、accept_tree_change を盤面に置く（RL の worktree_compare が読む）
        3. 進む物が無くなるまで _settle_pass を回す（機械の節が止まったらそこで終わる）。pre: finalize の節（report）は、出す前に
           記録を仕上げて保存し、検証器（self.run_validator）が受理集合の外なら出さずに止まる（_pre_finalize。engine の emit_instance）
        5. 最後に 1 度だけ保存する（3 の仕上げの保存は engine と同じく別に数える）。
        4. 保存が通った後に、周の記録（record_round。p4.record）が済んだ周の添え書き rounds/works/round-<N>.json を書く（この settle の
           終わりの周の箱で）。書く周の印は盤面の state.works.note_rounds に保存してあるので、step_builtin・run_builtin で済んだ周や、
           印を保存した後に捨てた入れ物の周も、次の settle が書く。保存が落ちれば（BoardConflict）書かない。
        3 で関所が通らなかったら、保存と添え書きの後に RecordInvalid を投げる（engine の exit 1 と同じく fail closed）。
        engine の advance の頭の graph_changed・engine_changed・frozen_outputs_stale は持たない（開くときに graph_sha を突き合わせ、
        写しの版は state.works.core。再生の比べない欄 NOT_REPRODUCED の state.engine・graph_changes・stale_frozen）"""
        if self.table is None:
            raise BoardGap("節の表が無い入れ物（scratch）は settle しない")
        st = self.state
        if st.get("halted"):
            h = st["halted"]
            return self._progress([f"止めた run（halted: {h.get('by')}・{h.get('node')}）。後の節は出さない"])
        if st.get("status") in TERMINAL_STATUS and all(self.node_state(x) != "pending" for x in self.nodes):
            return self._progress([f"全部の節が終わっている（status: {st['status']}）"])
        if st.get("pending_human"):
            return self._progress([f"人に聞いている間（{st['pending_human'].get('node')}）は進めない——answer で答える"])
        self._fresh_reads(accept_tree_change)
        self._notes = []
        self._record_invalid = None
        while self._settle_pass():
            pass
        self.save()
        self._write_pending_notes()
        if self._record_invalid is not None:
            raise self._record_invalid
        return self._progress(list(self._notes))

    def _fresh_reads(self, accept_tree_change):
        """読んだ物の控え（_out_cache・_porcelain・_vtables）を消し、accept_tree_change を盤面に置く（RL の worktree_compare が読む）"""
        self._drop_read_caches()
        self.accept_tree_change = accept_tree_change

    def _drop_read_caches(self):
        for k in ("_out_cache", "_porcelain", "_vtables"):
            self.__dict__.pop(k, None)

    def _progress(self, notes) -> Progress:
        ph, halted = self.state.get("pending_human"), self.state.get("halted")
        ready = []
        if not ph and not halted:
            for i in self.rd["instances"].values():
                if (i["status"] == "pending" and i["node"] not in ready
                        and self.table.nodes[i["node"]].by in ("role", "machine", "engine_run")):
                    ready.append(i["node"])
            ready += [w for w in self._walls if w not in ready and self.node_state(w) == "pending"]
        return Progress(round=self.round, ready=ready, asking=ph, halted=halted, notes=notes)

    def _settle_pass(self) -> bool:
        """engine の advance の輪の 1 段: graph の節の順に、待ちで依存が済んだ節を 1 つずつ評価する（_evaluate）。
        返りは「もう 1 段回すか」——進んだ物が在り、機械の節で止まっていない（engine は止まったらその場で advance を抜ける）。
        explicit の機械の節に当たったら、この段では graph の順でその後ろを評価しない（壁。仕様 4.1 の 3〔審 I8〕）"""
        self._walls = []
        progressed = False
        for nid, n in self.nodes.items():
            if self.node_state(nid) != "pending":
                continue
            _refuse_unowned(nid, n)
            if not self.deps_ok(nid):
                continue
            got = self._evaluate(nid)
            if got == "stop":
                return False
            if got == "wall":
                self._walls.append(nid)
                return progressed
            progressed = progressed or got in ("na", "skipped", "ran", "emitted")
        return progressed

    def _settle_node(self, nid: str) -> str | None:
        """節を 1 つだけ評価する（待ちで依存が済んだ節。1 手ずつの試験が na の手に当てる）。na にしたら理由を返す"""
        if self.node_state(nid) != "pending" or not self.deps_ok(nid):
            raise BoardGap(f"節 '{nid}' は評価する形でない（{self.node_state(nid)}・依存が済んだか {self.deps_ok(nid)}）")
        _refuse_unowned(nid, self.nodes[nid])
        got = self._evaluate(nid)
        return self.rd["na"][nid] if got == "na" else None

    def _evaluate(self, nid: str) -> str:
        """待ちで依存が済んだ節を 1 つ評価する（engine の advance の輪の中身）。返りは何が起きたか:
        na（条件に当たらない）・skipped（表で absent）・ran（機械の節が進んだ）・stop（機械の節が止まった）・
        wall（表で explicit の機械の節。待ちのまま）・emitted（役の節の instance を出した）・waiting（既に出して待っている）"""
        why = self.applicable(nid)
        if why:
            self.rd["na"][nid] = why
            return "na"
        e = self._entry(nid)
        if e.by == "absent":
            # engine の skip と同じ印（周の箱の skipped・done_ever・trace）。理由は表の理由
            self.rd["skipped"][nid] = e.reason
            self.state["done_ever"][nid] = self.round
            self.trace("skip", node=nid, reason=e.reason)
            return "skipped"
        if e.by == "builtin":
            if e.run == "explicit":
                return "wall"
            ran = run_driver_node(self, nid, self.nodes[nid], self._notes)
            self._mark_recorded(nid)
            return "ran" if ran else "stop"
        if any(i["node"] == nid and i["status"] == "pending" for i in self.rd["instances"].values()):
            return "waiting"
        if "pre" in self.nodes[nid] and not self._pre_finalize(nid):
            return "stop"
        self._emit(nid)
        return "emitted"

    def _pre_finalize(self, nid: str) -> bool:
        """pre: finalize の節（report）を出す前の関所（engine の emit_instance と同じ順）: 記録を仕上げて保存（finalize）→
        検証器（self.run_validator——validator_runner を渡した盤面はその包み。engine の直の run_validator は呼ばない）→
        終了コードが graph の受理集合（report_accepts_exit）に入れば真。入らなければ（None＝検証器が動かないも）engine と同じく
        trace に validator_failed を書き、出さずに止める（偽。settle が最後の保存の後に RecordInvalid を投げる——engine は die で
        exit 1）。finalize でない pre は BoardGap"""
        pre = self.nodes[nid]["pre"]
        if pre != "finalize":
            raise BoardGap(f"節 '{nid}' の pre '{pre}' を盤面の層は持たない（持つのは finalize だけ。a1202d0 の graph に無い形）")
        self.finalize()
        v = self.run_validator()
        if v.get("exit") not in report_accepts(self):
            self.trace("validator_failed", exit=v.get("exit"), out=v.get("out"))
            self._record_invalid = RecordInvalid(nid, v.get("exit"), v.get("out"))
            self._notes.append(str(self._record_invalid))
            return False
        return True

    # -- 依頼・人の答え・省く・止める・仕上げ（engine の cmd_add・cmd_answer・cmd_skip・cmd_stop・cmd_finalize の盤面の部分）
    def add_request(self, items: list, origin: str) -> dict:
        """人の依頼を RL の add に渡して記録に積み、保存する（engine の cmd_add と同じ記録。settle しない）。返り {msg, redraw}。
        redraw は RL が名指した「積んだ欄を読む、まだ起きていない instance」——engine と同じく新しい試行として出し直す
        （out_path は .a<試行>、前の置き場に在った物は .stale-a<試行> へ退ける）。ラインは、その節の役を起こしていたら止めて起こし直す。
        RL が拒めば engine の Reject（盤面は書かない。記憶の入れ物は汚れうるので捨てる）。止めた run は保存で拒む（engine と同じ）"""
        fn = hook(self.rules, "add")
        if not fn:
            raise Reject("このループの rules は add を受け付けない")
        got = fn(self, json.loads(json.dumps(items)), origin)   # 呼び出し側の依頼の dict を記録と共有しない
        msg, redraw = (got, []) if isinstance(got, str) else (got["msg"], got.get("redraw") or [])
        bad = [x for x in redraw if (self.rd["instances"].get(x) or {}).get("status") != "pending"]
        if bad:
            raise BoardGap(f"rules の add が描き直せと言う {bad} は、今の周の待っている instance でない（rules の欠陥）")
        for iid in redraw:
            prev = self.rd["instances"][iid]
            new = self._reissue(prev, f"add で積んだ物を届けるため描き直した（{origin}）")
            retire_out(prev["out_path"], prev.get("attempts", 1))
            self.trace("redrawn", instance=iid, attempt=new["attempts"], reason=origin)
        self.trace("add", reason=origin)
        self.save()
        return {"msg": msg, "redraw": list(redraw)}

    def _reissue(self, prev: dict, reason: str) -> dict:
        """待っている instance を同じ節の新しい試行として出し直す（engine の reissue の、描画を除いた部分）。
        作業ツリーの基準点（tree_before）は前の試行の物を継ぎ、attempt_log に前の試行を足す。
        任せ先に落ちた engine_run の節は、落ちた印（engine_fallback）も継ぐ——engine は出し直す時に計画し直して同じ印を置くが、
        DiskBoard の計画は run_engine の中なので、落ちた事実を継がないとラインの done が拒まれ、計画も 2 度になる"""
        nid, n = prev["node"], prev.get("attempts", 1)
        new = self._emit(nid, attempt=n + 1)
        for k in ("tree_before", "engine_fallback"):
            if k in prev:
                new[k] = prev[k]
        new["attempt_log"] = (prev.get("attempt_log") or []) + [{"at": new["emitted_at"], "reason": reason,
                                                                 "prev_emitted_at": prev["emitted_at"],
                                                                 "prev_out_path": str(prev["out_path"])}]
        return new

    def _answer_record(self, ans: str, note: str = "") -> None:
        """人の答えを記録して保存する（engine の cmd_answer と同じ範囲。settle しない）。周の途中の問い（in_round）は RL の
        on_answer_in_round、周の終わりの問いは on_answer。continue・escalate の周の終わりの答えは次の周を開く（engine の
        open_next_round。stop_after_round の周なら開かずに halted）。stop は run を止める（周の途中なら halted.by == "answer"）。
        答えの誤り（聞いていない・選択肢に無い・周の途中に使えない語）は engine と同じ文の Reject。止めた run は保存で拒む"""
        ph = self.state.get("pending_human")
        if not ph:
            raise Reject("人に聞いている節は無い")
        if not isinstance(ans, str):
            raise BoardGap(f"答えが文字列でない: {ans!r}")
        ans = ans.strip()
        if ans not in ph["options"]:
            raise Reject(f"答えは {ph['options']} のどれか")
        if ans not in ANSWER_ACTIONS:
            raise Reject(f"答え '{ans}' は engine が動けない語（動けるのは {list(ANSWER_ACTIONS)}）——諮りの選択肢の側が壊れている")
        in_round = bool(ph.get("in_round"))
        if in_round and ans not in IN_ROUND_ACTIONS:
            raise Reject(f"周の途中の問い（in_round）に '{ans}' は使えない（使えるのは {list(IN_ROUND_ACTIONS)}）")
        ph["note"] = note or ""
        fn = hook(self.rules, "on_answer_in_round" if in_round else "on_answer")
        if fn:
            fn(self, ph, ans)
        self.state.pop("pending_human")
        self.trace("answer", answer=ans, kinds=ph.get("kinds"))
        if in_round:
            # 問うた節をここで済ませる（ask では done の印を付けない）。continue は同じ周のまま先へ、stop は run をその場で止める
            self.rd["done"][ph["node"]] = {"at": now(), "builtin": f"answer:{ans}"}
            self.state["done_ever"][ph["node"]] = self.round
            if ans == "stop":
                self.state["status"] = "stopped"
                self.state["halted"] = {"node": ph["node"], "round": self.round, "by": "answer", "reason": ph["note"]}
        elif ans == "stop":
            self.rd["done"][ph["node"]] = {"at": now(), "builtin": "answer:stop"}
            self.state["done_ever"][ph["node"]] = self.round
            self.state["status"] = "stopped"
        else:
            if ans == "escalate":
                if not self.tiers:
                    raise Reject("この loop に段（thickness.tiers）が無いので escalate できない")
                thicken(self, self.tiers[-1], "依頼者の判断（諮った結果）", by="answer")
            if not open_next_round(self, ph["node"]):
                # stop_after_round の周: 次の周を開かずに止めた（halted）。聞いた節はここで済ませる
                self.rd["done"][ph["node"]] = {"at": now(), "builtin": f"answer:{ans}"}
                self.state["done_ever"][ph["node"]] = self.round
        self.save()

    def answer(self, ans: str, note: str = "") -> Progress:
        """人の答え（loop.py answer → next）: _answer_record → settle"""
        self._answer_record(ans, note)
        return self.settle()

    def _skip_record(self, nid: str, reason: str) -> None:
        """節を省いて保存する（engine の cmd_skip と同じ記録。settle しない）。省けるのは表で skippable の節だけ
        （縛り 5 で graph の optional の節にだけ付く。engine の skip と同じ強さ〔審 I6〕）。
        表で skippable でない・理由が空・graph に無い節は BoardGap（ラインの配線の誤り）。optional でない・待っていない節は
        engine と同じ文の Reject。止めた run は保存で拒む"""
        n = self.nodes.get(nid)
        if n is None:
            raise BoardGap(f"節 '{nid}' は graph に無い")
        if not (isinstance(reason, str) and reason.strip()):
            raise BoardGap(f"節 '{nid}' を省く理由が空——省いた理由は記録と報告の『省略した機構』に残る")
        if not self._entry(nid).skippable:
            raise BoardGap(f"節 '{nid}' は表で skippable でない——省けるのは表で skippable の節（graph で optional の節だけに付く）")
        if not n.get("optional"):
            raise Reject(f"節 '{nid}' は optional でない——省けない（省略できる機構は graph の optional と段の宣言が正本）")
        if self.node_state(nid) != "pending":
            raise Reject(f"節 '{nid}' は {self.node_state(nid)}")
        self.rd["skipped"][nid] = reason
        for i in self.rd["instances"].values():
            if i["node"] == nid and i["status"] == "pending":
                i["status"] = "skipped"
        self.state["done_ever"][nid] = self.round
        self.trace("skip", node=nid, reason=reason)
        self.save()

    def skip(self, nid: str, reason: str) -> Progress:
        """節を省く（loop.py skip → next）: _skip_record → settle"""
        self._skip_record(nid, reason)
        return self.settle()

    def stop(self, reason: str, by: str) -> dict:
        """走っている run をその時点で止める（engine の cmd_stop の盤面の部分。子を止めるのは含まない——役は Archon と
        works のブロックが起こす）。graph の stop.node の下流（報告の節）だけを残し、他の待ちの節は rd.stopped、待っている
        instance は stopped。RL の on_stop が止めた事実と止めた周の記録を書き、報告を出せなければ halted。by は止めた口の名前
        （engine の loop.py stop は "stop"）で、state.stop・halted・記録の process.halted に残る。
        止めた周の記録（rounds/round-<N>.json）が在れば周の添え書きも書く（仕様 4.5）。
        返り {stopped: state.stop, handed_not_stopped: [起こし中かもしれない役の instance]}（engine と同じ。ラインが止める）。
        理由が空・既に止まった・終わった run は engine と同じ文の Reject"""
        reason = reason.strip() if isinstance(reason, str) else ""
        if not reason:
            raise Reject("止める理由が空——--reason に、なぜ止めるかを書け（記録と報告に残る）")
        if not (isinstance(by, str) and by.strip()):
            raise BoardGap(f"stop の by（止めた口の名前）が空: {by!r}")
        if self.state.get("halted"):
            raise Reject(f"もう止まっている（halted: {self.state['halted'].get('by')}）——止める物が無い")
        if self.state["status"] in TERMINAL_STATUS:
            raise Reject(f"run は既に {self.state['status']}——止める物が無い（報告の節が残っているなら next で続けよ）")
        root = (self.graph.get("stop") or {}).get("node")
        keep = stop_descendants(self.nodes, root) if root else set()
        info = {"by": by, "reason": reason, "round": self.round, "at": now(), "node": root, "report": bool(root)}
        ph = self.state.pop("pending_human", None)
        if ph:
            info["unanswered"] = {k: ph[k] for k in ("node", "kinds", "question", "items", "in_round") if k in ph}
        rd = self.rd
        rd.setdefault("stopped", {})
        for nid in self.nodes:
            if nid != root and nid not in keep and self.node_state(nid) == "pending":
                rd["stopped"][nid] = f"{STOPPED_BY}: {reason}"
        handed = []
        for i in rd["instances"].values():
            if i["status"] != "pending" or i["node"] in keep:
                continue
            i["status"] = "stopped"
            i["stopped_by"] = reason
            n = self.nodes[i["node"]]
            if not i.get("launch") and (not self.is_runner(n) or n.get("delegate")):
                handed.append(i["id"])
        fn = hook(self.rules, "on_stop")
        no_report = fn(self, info) if fn else None
        if root and not no_report:
            rd["done"][root] = {"at": now(), "builtin": "stop"}
            self.state["done_ever"][root] = self.round
        else:
            info["report"] = False
            info["no_report"] = no_report or "graph に stop の宣言（止めた後に走らせる節）が無い——init の版の graph が古い"
            self.state["halted"] = {"node": root, "round": self.round, "by": by, "reason": reason}
        self.state["status"] = "stopped"
        self.state["stop"] = info
        self.trace("stop", reason=reason, round=self.round, report=info["report"], stopped=sorted(rd["stopped"]))
        self.save()
        if (self.dir / "rounds" / f"round-{self.round}.json").exists():
            self._write_round_note(self.round)
        return {"stopped": info, "handed_not_stopped": handed}

    def finalize(self) -> None:
        """記録の仕上げ（engine の validator.finalize: RL の finalize → 周の箱の skipped・stopped と痕跡の欄を process に写す）→ 保存
        （loop.py finalize の記録の部分）。検証器は回さない——回すのは呼び出し側で、必ず self.run_validator（validator_runner の
        包みが効く口）を通す（settle の pre: finalize の関所がそう呼ぶ）。止めた run に書くなら allow_halted で開いた盤面で"""
        _finalize_record(self)
        self.save()

    # -- works の周の添え書き（仕様 4.5）
    def _mark_recorded(self, nid: str) -> None:
        """周の記録を組む機械の節（builtin record_round。a1202d0 では p4.record）が済んだら、添え書きを書く周の番号を盤面の
        state.works.note_rounds に控える（記憶だけにすると、印を持った入れ物を settle の前に捨てた周の添え書きが落ちる）"""
        if self.nodes[nid].get("builtin") == "record_round" and nid in self.rd["done"]:
            marks = self.state.setdefault("works", {}).setdefault("note_rounds", [])
            if self.round not in marks:
                marks.append(self.round)

    def _write_pending_notes(self) -> None:
        """印の周の添え書きを書き、記憶の印を消す（settle の保存の後に呼ぶ。消した印は次の保存で盤面に残る——
        それまでに入れ物を捨てれば、次の settle が同じ周の添え書きを書き直す）"""
        marks = (self.state.get("works") or {}).get("note_rounds") or []
        for n in sorted(marks):
            self._write_round_note(n)
        if marks:
            self.state["works"]["note_rounds"] = []

    def _write_round_note(self, n: int) -> pathlib.Path:
        """rounds/works/round-<n>.json を書いて返す（仕様 4.5 の形）:
        {round, line, table_sha, not_in_line: [{node, reason, comes_with, in_round, materials}], skipped_optional: [{node, reason}],
         checks: {節: {by, why?}}}
        - not_in_line は表の absent の全部（表の順）。in_round はその周の周の箱での終わり方（skipped・na・stopped・done、どれでも
          なければ pending）。materials はその節が書く素材（graph の materials）の、周の記録（rounds/round-<n>.json。無ければ今の
          記録）の status
        - skipped_optional は、その周に省いた節のうち表で absent でない物（skip で省いた optional の節と、任せ先が absent で省いた
          engine_run の節）
        - checks は process.checks のうち、その周の分（CI を engine が確かめたか・役の自己申告か）
        写しの RR は rounds/ の下のディレクトリを読み飛ばすので、周の記録の判定を変えない"""
        if self.table is None:
            raise BoardGap("節の表が無い入れ物（scratch）は周の添え書きを書かない")
        rd = self.state["rounds"][n - 1]
        rnd_file = self.dir / "rounds" / f"round-{n}.json"
        mats = (_read_json(rnd_file) if rnd_file.exists() else self.record).get("materials") or {}
        rows = []
        for a in self.table.absent():
            nid = a["node"]
            where = next((box for box in ("skipped", "na", "stopped", "done") if nid in (rd.get(box) or {})), "pending")
            rows.append({**a, "in_round": where,
                         "materials": {m: (mats.get(m) or {}).get("status") for m in self.nodes[nid].get("materials", [])}})
        absent = {r["node"] for r in rows}
        checks = (self.record.get("process") or {}).get("checks") or {}
        doc = {"round": n, "line": self.table.line, "table_sha": self.table.sha(), "not_in_line": rows,
               "skipped_optional": [{"node": k, "reason": v} for k, v in rd["skipped"].items() if k not in absent],
               "checks": {k: {"by": c.get("by"), **({"why": c["why"]} if c.get("why") else {})}
                          for k, c in checks.items() if isinstance(c, dict) and c.get("round") == n}}
        p = self.dir / "rounds" / "works" / f"round-{n}.json"
        p.parent.mkdir(parents=True, exist_ok=True)
        write_json(p, doc)
        return p

    # -- works の作業ファイル
    def work(self, name: str) -> pathlib.Path:
        """今の周の作業ファイルの置き場 r<N>/<name>（ディレクトリを作る）"""
        p = self.dir / f"r{self.round}" / name
        p.parent.mkdir(parents=True, exist_ok=True)
        return p
