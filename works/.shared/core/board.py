"""盤面の層。run の途中の状態をディスクに置く盤面と、写した graphloops の規則をそこに当てる口（仕様 works/docs/specs/2026-09-26-board-layer-design.md）。

今ここに在る物:
- BoardGap・BoardMismatch: 内部の誤りの型（仕様 4.6）。役の返答の誤りは engine の Reject のまま
- NodeEntry・NodeTable:    節の表（仕様 4.2）。graph の全部の節を、このラインでどう持つかに振る

節の表のファイル（<ライン>/nodes.json）の形:
  {"line": str, "graph_sha": str, "nodes": {節: {"by": str, "run"?, "fallback"?, "skippable"?, "reason"?, "where"?, "comes_with"?}}}
読むとき（load）は形だけを見る。graph との突き合わせ（縛り 1〜5）は check が誤りの文の一覧で返す。
"""
import dataclasses
import json
import pathlib
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
        object.__setattr__(self, "nodes", types.MappingProxyType(dict(self.nodes)))

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
