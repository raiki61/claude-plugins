"""線の入口の口（線 A の仕様 4 節。盤面の層の仕様 4.2・4.4）: ラインの節の表を読み、盤面をラインの名前を知らずに開く。

- load_table(line):   PACK/<line>/nodes.json を読み、盤面の層の縛り 1〜5（NodeTable.check）を当てる。破れは全部を 1 つの BoardGap に
- open_board(dir):    盤面の state.works.line から表を引き、表の sha が state.works.table_sha と合わなければ BoardMismatch。
                      ラインの置き場の board_hook.py（在れば）の board_kwargs(table) の返りを DiskBoard.open に渡す
- hook_kwargs(line):  board_hook.py の読み込みだけ（無ければ {}）。盤面を作る側（start）も同じ物を DiskBoard.create に渡す

ブロックのスクリプトは open_board で盤面を開く。線 B のライン（darkfactory-rounds）でも同じブロックが同じ口で動く。
"""
import importlib.util
import json
import pathlib
import re
import sys

sys.dont_write_bytecode = True   # board_hook.py の読み込みで pack の中に __pycache__ を作らない

_CORE = pathlib.Path(__file__).resolve().parent
if str(_CORE) not in sys.path:
    sys.path.insert(0, str(_CORE))

from board import GRAPH_SHA, BoardGap, BoardMismatch, DiskBoard, NodeTable, graph_expanded  # noqa: E402

PACK = pathlib.Path(__file__).resolve().parents[2]   # works/（Archon は run ごとに pack を写すので、今の写しの置き場）
TABLE_NAME = "nodes.json"
HOOK_NAME = "board_hook.py"
HOOK_KEYS = ("overrides", "validator_runner")      # board_kwargs が返してよい鍵（DiskBoard.open・create の引数）
_LINE_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]*")


def _line_dir(line) -> pathlib.Path:
    """ラインの置き場。名前は盤面から来るので、pack の外を指す名前（/・..・空）を拒む"""
    if not isinstance(line, str) or not _LINE_NAME.fullmatch(line):
        raise BoardGap(f"ラインの名前 {line!r} が読めない（英数字・_・- だけ）")
    return PACK / line


def load_table(line: str = "darkfactory") -> NodeTable:
    """PACK/<line>/nodes.json を読む。形の誤りは NodeTable.load の BoardGap、縛り 1〜5 の破れと line の違いは全部を並べた BoardGap"""
    path = _line_dir(line) / TABLE_NAME
    table = NodeTable.load(path)
    errs = table.check(graph_expanded(), GRAPH_SHA)
    if table.line != line:
        errs.append(f"表の line {table.line} がラインの置き場の名前 {line} と違う")
    if errs:
        raise BoardGap(f"節の表 {path} が縛りに当たる（{len(errs)} 件）: " + "; ".join(errs))
    return table


def hook_kwargs(line: str, table: NodeTable | None = None) -> dict:
    """PACK/<line>/board_hook.py の board_kwargs(table) の返り（無ければ {}）。毎回新しく読み、sys.modules に残さない。
    返りは dict で、鍵は overrides・validator_runner だけ（ほかの鍵・読めない hook は BoardGap）。table を渡さなければ load_table(line)"""
    path = _line_dir(line) / HOOK_NAME
    if not path.is_file():
        return {}
    if table is None:
        table = load_table(line)
    try:
        spec = importlib.util.spec_from_file_location(f"_works_board_hook_{line.replace('-', '_')}", path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    except Exception as e:
        raise BoardGap(f"{path} を読み込めない: {e!r}") from e
    fn = getattr(mod, "board_kwargs", None)
    if not callable(fn):
        raise BoardGap(f"{path} に board_kwargs(table) が無い")
    kw = fn(table)
    if not isinstance(kw, dict):
        raise BoardGap(f"{path} の board_kwargs の返りが dict でない: {type(kw).__name__}")
    unknown = sorted(set(kw) - set(HOOK_KEYS))
    if unknown:
        raise BoardGap(f"{path} の board_kwargs が知らない鍵を返した: {', '.join(map(str, unknown))}（{' / '.join(HOOK_KEYS)} だけ）")
    return kw


def open_board(board_dir: pathlib.Path, *, allow_halted: bool = False) -> DiskBoard:
    """盤面を開く。表は state.works.line のラインの nodes.json。表の sha が盤面を作った時の state.works.table_sha と違えば
    BoardMismatch（run の途中で表が替わった盤面を、替わった表で回さない）。board_hook.py の返りを DiskBoard.open に渡す"""
    d = pathlib.Path(board_dir)
    try:
        state = json.loads((d / "state.json").read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise BoardGap(f"{d / 'state.json'} を読めない: {e}") from None
    works = state.get("works") if isinstance(state, dict) else None
    line = works.get("line") if isinstance(works, dict) else None
    if line is None:
        raise BoardGap(f"盤面 {d} に state.works.line が無い（works の盤面でない）")
    table = load_table(line)
    want, got = works.get("table_sha"), table.sha()
    if want != got:
        raise BoardMismatch(f"盤面 {d} の表の sha {want} が今のライン {line} の表の {got} と違う"
                            f"（盤面を作った後に {line}/{TABLE_NAME} が替わった。替わった表で回さない）")
    return DiskBoard.open(d, table=table, allow_halted=allow_halted, **hook_kwargs(line, table))
