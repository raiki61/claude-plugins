"""盤面の層。run の途中の状態をディスクに置く盤面と、写した graphloops の規則をそこに当てる口（仕様 works/docs/specs/2026-09-26-board-layer-design.md）。

今ここに在る物:
- BoardGap・BoardMismatch: 内部の誤りの型（仕様 4.6）。役の返答の誤りは engine の Reject のまま
- NodeEntry・NodeTable:    節の表（仕様 4.2）。graph の全部の節を、このラインでどう持つかに振る
- DiskBoard:               ディスクの盤面を開く入れ物（仕様 4.1・4.4）。写した engine の Board を継ぐ
- rules_module・graph_expanded: 盤面なしで写しの RL と graph を読む口（仕様 4.1 の末尾）

節の表のファイル（<ライン>/nodes.json）の形:
  {"line": str, "graph_sha": str, "nodes": {節: {"by": str, "run"?, "fallback"?, "skippable"?, "reason"?, "where"?, "comes_with"?}}}
読むとき（load）は形だけを見る。graph との突き合わせ（縛り 1〜5）は check が誤りの文の一覧で返す。
"""
import contextlib
import dataclasses
import datetime
import json
import pathlib
import shutil
import sys
import types
from typing import Mapping

# pack の中に __pycache__ を作らない（下で import する写しの engine の分。accept.py と同じ）
sys.dont_write_bytecode = True

CORE = pathlib.Path(__file__).resolve().parent
_GL = CORE / "graphloops"
if str(_GL) not in sys.path:
    sys.path.insert(0, str(_GL))

import engine.util as _util  # noqa: E402
from engine.board import Board as _EngineBoard, empty_round, refuse_expression_conds  # noqa: E402
from engine.commands import choice_input_errors, max_rounds_for, path_inputs, undeclared_inputs  # noqa: E402
from engine.rules import hook, load_rules, registry  # noqa: E402
from engine.schema import expand_refs, graph_text, load_graph, resolve_extends  # noqa: E402
from engine.util import Reject, now  # noqa: E402

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
    def create(cls, d, *, repo, table, inputs, request_text, max_rounds=None, stop_after_round=None,
               overrides=None, validator_runner=None) -> "DiskBoard":
        """盤面を作る（engine の cmd_init と同じ順と入口の検査。仕様 4.1 の 1〜5）。入口で拒めば置き場を作らず、
        作った後のどこかで例外なら置き場を消して投げ直す（空の盤面を残さない）。既に在る置き場には作らない（BoardGap）"""
        d = pathlib.Path(d).resolve()
        _check_table(table)
        if stop_after_round is not None and (type(stop_after_round) is not int or stop_after_round < 1):
            raise BoardGap(f"stop_after_round は 1 以上の整数（{stop_after_round!r}）——止める周の番号で、その周の締めの後で止まる")
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
        notes = [f"inputs の {k} は graph の inputs に宣言が無く、どの節も rules も読まない（効かない）"
                 for k in undeclared_inputs(graph, list(inputs or {}))]
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
                "unattended": False,
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
        """scratch の入れ物は保存しない（BoardGap）。他は engine の save（版の突き合わせ・止めた run の拒否）"""
        if self._scratch:
            raise BoardGap("scratch の入れ物（v1 の受け付け）は保存しない")
        super().save()

    def run_validator(self, target=None):
        """validator_runner を渡した盤面だけ、それを (盤面, target) で呼ぶ。渡さなければ engine と同じ"""
        if self.validator_runner is not None:
            return self.validator_runner(self, target)
        return super().run_validator(target)

    # -- works の作業ファイル
    def work(self, name: str) -> pathlib.Path:
        """今の周の作業ファイルの置き場 r<N>/<name>（ディレクトリを作る）"""
        p = self.dir / f"r{self.round}" / name
        p.parent.mkdir(parents=True, exist_ok=True)
        return p
