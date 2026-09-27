"""線の入口の口（線 A の仕様 4 節。盤面の層の仕様 4.2・4.4）: ラインの節の表を読み、盤面をラインの名前を知らずに開く。

- load_table(line):   PACK/<line>/nodes.json を読み、盤面の層の縛り 1〜5（NodeTable.check）を当てる。破れは全部を 1 つの BoardGap に
- open_board(dir):    盤面の state.works.line から表を引き、表の sha が state.works.table_sha と合わなければ BoardMismatch。
                      ラインの置き場の board_hook.py（在れば）の board_kwargs(table) の返りを DiskBoard.open に渡す
- hook_kwargs(line):  board_hook.py の読み込みだけ（無ければ {}）。盤面を作る側（start）も同じ物を DiskBoard.begin に渡す
- check_inputs(raw, repo): ラインの入力を確かめる（線 A の仕様 4 節）。拒めば InputRefused（人に向けた 1 行）
- local_checks_material(repo, test_cmd, log_path): 任せ先に落ちた CI の節（p0.local_checks・p4.ci）に渡す素材を組む公開の口
  （盤面なしで呼べる。線 B の申し送り 2）
- run_ci(b, nid, *, test_cmd): CI の節を run_engine で走らせ、返りを全部扱う（start と blk-tests の final が使う）
- start(board_dir, repo, raw, *, run_id): 入力の確かめ → 盤面を開く → 修正前のテストの記録 → 方針の文 → 切符

ブロックのスクリプトは open_board で盤面を開く。線 B のライン（darkfactory-rounds）でも同じブロックが同じ口で動く。
"""
import importlib.util
import json
import os
import pathlib
import re
import subprocess
import sys

sys.dont_write_bytecode = True   # board_hook.py の読み込みで pack の中に __pycache__ を作らない

_CORE = pathlib.Path(__file__).resolve().parent
if str(_CORE) not in sys.path:
    sys.path.insert(0, str(_CORE))

from board import GRAPH_SHA, BoardGap, BoardMismatch, DiskBoard, NodeTable, graph_expanded  # noqa: E402
from engine.role_run import _tail  # noqa: E402  （engine が走らせた段の末尾と同じ切り方）
from engine.schema import validate_schema  # noqa: E402
from engine.util import Reject, safe_name  # noqa: E402
import policy  # noqa: E402
import prcheck  # noqa: E402
import ticket  # noqa: E402
import tree_run  # noqa: E402

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
    try:
        kw = fn(table)
    except BoardGap:
        raise
    except Exception as e:   # hook の中の誤りも内部の誤り（スクリプトは終了コード 2。TA19）
        raise BoardGap(f"{path} の board_kwargs が落ちた: {e!r}") from e
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



# ---------------------------------------------------------------- 入力の確かめ（線 A の仕様 4 節）
LINE = "darkfactory"
ORIGIN = "works/darkfactory"   # 依頼の出どころ（record.process.request_entry.origin）
THICKNESS = ("軽量", "標準", "重厚")
THICKNESS_DEFAULT = "標準"
MID_GATES = ("always", "when_needed")
ADAPTER_MODES = ("", "optional")
GATES = ("", "merge")
LIGHT_REFUSED = "軽量は受けない: graph で省けない節を省くことになる（持ち主の決定 2026-09-27）"
HEAVY_REFUSED = "重厚で足す工程がまだ無い"
CI_BUILTIN = "declared_checks"   # 写しの graph の engine_run.builtin のうち、CI の節（p0.local_checks・p4.ci）の語


class InputRefused(Exception):
    """入力を受けない（AI を起こす前に run を止める）。文は人に向けた 1 行"""

    def __init__(self, msg):
        super().__init__(" ".join(str(msg).split()))


class CiRefused(InputRefused):
    """CI の節を engine で走らせられない（2 度とも計画が拒まれた・why だけの返り）。start では入力の拒みと同じく AI の前で止める"""


def _word(raw: dict, key: str) -> str:
    v = raw.get(key)
    return "" if v is None else str(v).strip()


def check_inputs(raw: dict, repo: pathlib.Path) -> dict:
    """ラインの入力を確かめて {request_file, items, request_text, test_cmd, thickness, gates, mid_gate, adapter, policy_md} を返す。
    盤面は作らない。拒む物（InputRefused）: 依頼が読めない・JSON の配列でない・依頼の型（写しの RL の REQUEST_SCHEMA）に
    合わない、thickness が軽量・重厚・知らない値、mid_gate・adapter・gates が語の外（gates の文は写しの RL の check_inputs）、
    名指した方針の文書が無い。test_cmd が空で宣言（.review-checks.json）も無い run は拒まない（裁定 R52: graphloops と同じく
    p0.local_checks・p4.ci が任せ先の役に落ち、役がリポジトリを読んでテストの走らせ方を探す）。
    相対のパス（依頼・方針の文書）は対象の根 repo から"""
    repo = pathlib.Path(repo)
    thickness = _word(raw, "thickness") or THICKNESS_DEFAULT
    if thickness == "軽量":
        raise InputRefused(LIGHT_REFUSED)
    if thickness == "重厚":
        raise InputRefused(HEAVY_REFUSED)
    if thickness not in THICKNESS:
        raise InputRefused(f"thickness={thickness!r} は知らない値（{' / '.join(THICKNESS)}。受けるのは {THICKNESS_DEFAULT} だけ）")
    mid_gate = _word(raw, "mid_gate") or MID_GATES[0]
    if mid_gate not in MID_GATES:
        raise InputRefused(f"mid_gate={mid_gate!r} は知らない値（{' / '.join(MID_GATES)}）")
    adapter = _word(raw, "adapter")
    if adapter not in ADAPTER_MODES:
        raise InputRefused(f"adapter={adapter!r} は知らない値（空か optional）")
    gates = _word(raw, "gates")
    rules = board_rules()
    try:
        rules.check_inputs({"gates": gates} if gates else {})
    except Reject as e:
        raise InputRefused(f"gates: {e}") from None
    rel = _word(raw, "request")
    if not rel:
        raise InputRefused("依頼のファイルが名指されていない（request が空）")
    path = pathlib.Path(rel) if pathlib.Path(rel).is_absolute() else repo / rel
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as e:
        raise InputRefused(f"依頼のファイル {rel} が読めない（{type(e).__name__}: {e}）") from None
    try:
        items = json.loads(text)
    except json.JSONDecodeError as e:
        raise InputRefused(f"依頼のファイル {rel} が JSON として読めない（{e}）") from None
    if not isinstance(items, list):
        raise InputRefused(f"依頼のファイル {rel} が JSON の配列でない（{type(items).__name__}）")
    errs = validate_schema([{"round": 1, "origin": ORIGIN, "findings": items}], rules.REQUEST_SCHEMA)
    if errs:
        raise InputRefused(f"依頼のファイル {rel} の形: [{{where, text, mechanism?, measured?, false_positive_if?}}] の配列（空でない）: "
                           + "; ".join(errs))
    pol = _word(raw, "policy_md")
    if pol:
        pp = pathlib.Path(pol) if pathlib.Path(pol).is_absolute() else repo / pol
        if not pp.is_file():
            raise InputRefused(f"名指した方針の文書 {pol} が無い（policy_md。人の方針の文書を名指すなら先に置く）")
        pol = str(pp)
    return {"request_file": str(path.resolve()), "items": items, "request_text": text, "test_cmd": _word(raw, "test_cmd"),
            "thickness": thickness, "gates": gates, "mid_gate": mid_gate, "adapter": adapter, "policy_md": pol}


def board_rules():
    """写しの RL（盤面なし。入口の検査に使う）"""
    from board import rules_module
    return rules_module()


# ---------------------------------------------------------------- CI の節（p0.local_checks・p4.ci）
def local_checks_material(repo: pathlib.Path, test_cmd: str, log_path: pathlib.Path) -> dict:
    """任せ先に落ちた CI の節に渡す素材 {"material": …} を組む（盤面なしで呼べる公開の口。線 B の申し送り 2）。
    test_cmd を ["bash", "-c", test_cmd] で tree_run に走らせ（対象の根で・標準入力は空・環境は tree_run.outside_env。
    標準出力と標準エラーを log_path に）、終了コード 0 なら clean（写しの RR の規則で checked が要る）、他は found・count 1。
    detail はログの末尾（engine の段の末尾と同じ切り方）。起こせなければ not_run。test_cmd が空なら走らせずに not_run。
    止められたら（tree_run.Stopped）捕まえない"""
    cmd = (test_cmd or "").strip()
    if not cmd:
        return {"material": {"status": "not_run", "reason": "テストのコマンド（test_cmd）が空で、走らせる物が無い"}}
    log_path = pathlib.Path(log_path)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with open(log_path, "wb") as f:
        try:
            code = tree_run.run(["bash", "-c", cmd], stdin=subprocess.DEVNULL, stdout=f, stderr=subprocess.STDOUT,
                                cwd=str(repo), env=tree_run.outside_env(os.environ))
        except OSError as e:
            return {"material": {"status": "not_run", "reason": f"bash -c でテストのコマンドを起こせない: {e}"}}
    tail = _tail(log_path.read_bytes())
    ran = f"bash -c {cmd!r} を対象の根で走らせた: exit {code}（ログ {log_path}）"
    if code == 0:
        return {"material": {"status": "clean", "count": 0, "checked": ran, "detail": tail}}
    return {"material": {"status": "found", "count": 1, "detail": f"{ran} ／ 末尾: {tail}"}}


def _engine_log(b, nid: str, runs: list) -> pathlib.Path:
    """engine が走らせた全部の段の標準出力と標準エラーを 1 つのログ r<N>/<節>.log に並べる（2 段目の赤・標準エラーだけの出力も
    見えるように。段ごとの元のファイルは runs[].out・err のまま残る）。走らせなかった回（宣言が読めない）は素材の理由を書く"""
    log = b.work(safe_name(nid) + ".log")
    parts = []
    for i, r in enumerate(runs, 1):
        parts.append(f"== 段 {i} {r.get('name')}: {json.dumps(r.get('argv'), ensure_ascii=False)} → exit {r.get('exit')}\n")
        if r.get("error"):
            parts.append(f"起こせない: {r['error']}\n")
        for key in ("out", "err"):
            src = r.get(key)
            body = pathlib.Path(src).read_text(encoding="utf-8", errors="replace") if src and pathlib.Path(src).is_file() else ""
            parts.append(f"--- {'標準出力' if key == 'out' else '標準エラー'}（{src}）\n{body}")
            if body and not body.endswith("\n"):
                parts.append("\n")
    if not runs:
        m = (b.record.get("materials") or {}).get("local_checks") or {}
        parts.append(f"engine は宣言の段を走らせなかった: {m.get('reason') or m.get('detail') or m.get('checked') or ''}\n")
    log.write_text("".join(parts), encoding="utf-8")
    return log


def run_ci(b, nid: str, *, test_cmd: str, runner=None) -> dict:
    """CI の節 nid（p0.local_checks・p4.ci）を b.run_engine で走らせ、返りを全部扱う（start と blk-tests の final が使う）。
    - relaunch（宣言が計画の後に変わった）は 1 度だけ呼び直す。2 度目も同じなら CiRefused（文に why）
    - ok: engine が受け付けまで済ませた → {by: "engine", log: 全部の段のログ}
    - fallback（宣言が無い）で任せ先に落ちた: test_cmd が在れば、起こした印（mark_launched）を置いてから local_checks_material を
      b.done で渡す → {by: "role", log}。test_cmd が空なら素材を作らずに {by: "role_needed", log: "", why}——節は任せ先に
      落ちたまま ready に残り、任せ先の役（graphloops の p0.local_checks・p4.ci の役と同じく、リポジトリを読んで走らせ方を探す）
      が渡す（裁定 R52。役のブロックは後の Task）
    - ok: False で relaunch も fallback も無い（why だけ。対象の根が引けない）→ CiRefused"""
    got = b.run_engine(nid, runner=runner)
    if got.get("relaunch"):
        got = b.run_engine(nid, runner=runner)
        if got.get("relaunch"):
            raise CiRefused(f"{nid}: 宣言が計画の後に 2 度変わった（呼び直しても同じ）: {got.get('why')}")
    if got.get("ok"):
        return {"by": "engine", "log": str(_engine_log(b, nid, got.get("runs") or []))}
    if "fallback" not in got:
        raise CiRefused(f"{nid} を engine で走らせられない: {got.get('why')}")
    inst = next((i for i in b.rd["instances"].values() if i["node"] == nid and i["status"] == "pending"), None)
    if inst is None:
        raise BoardGap(f"{nid} は任せ先に落ちたが待っていない（表の fallback が absent）——CI の節は任せ先を持つ表で回す")
    if not (test_cmd or "").strip():
        return {"by": "role_needed", "log": "", "why": got["fallback"]}
    b.mark_launched(nid, inst.get("attempts", 1))   # 任せ先の返答の前に起こした印（board.py の頭のラインの約束 2）
    log = b.work(safe_name(nid) + ".log")
    b.done(nid, local_checks_material(pathlib.Path(b.state["inputs"]["cwd"]), test_cmd, log))
    return {"by": "role", "log": str(log)}


def _is_ci(b, nid: str) -> bool:
    return ((b.nodes.get(nid) or {}).get("engine_run") or {}).get("builtin") == CI_BUILTIN


def _fell_back(b, nid: str) -> bool:
    inst = b.rd["instances"].get(nid)
    return bool(inst and inst.get("status") == "pending" and inst.get("engine_fallback"))


# ---------------------------------------------------------------- start（線 A の仕様 4 節）
def start(board_dir: pathlib.Path, repo: pathlib.Path, raw: dict, *, run_id: str, runner=None) -> dict:
    """ラインの入口。順:
    1. check_inputs（拒めば盤面を作らずに InputRefused）
    2. DiskBoard.begin（判定から入る 1 周の run。origin works/darkfactory・base_rev は空＝HEAD・stop_after_round=1・
       board_hook.py の overrides・validator_runner）。入口の Reject は InputRefused
    3. 盤面の約束 1: Progress.run_engine の節を全部走らせて settle する、を空になるまで。CI の節は run_ci（修正前のテストを
       盤面に記録）、p0.parallel_pr は prcheck.run_helper（落ちても印は置かない。blk-pr の pr-snap が置く）。CiRefused・
       prcheck.Refused は AI を起こす前に止める（InputRefused）
    4. 切符（ticket.write）を書き、r1/start.json に入力の控えを置く
    返り {ok, base_rev, test_cmd, policy_paste, policy_path, mid_gate, adapter, thickness, gates, ci_role_go, pr_go, head_line}。
    ci_role_go は CI の節（p0.local_checks）が任せ先に落ちたまま待っている（test_cmd も宣言も無い。裁定 R52）、pr_go は
    p0.parallel_pr が任せ先に落ちた（blk-pr を回す）。同じ置き場で呼び直せば begin は盤面を開いて続きから（Archon の再開）"""
    repo = pathlib.Path(repo).resolve()
    board_dir = pathlib.Path(board_dir)
    inp = check_inputs(raw, repo)
    table = load_table(LINE)
    try:
        b, p = DiskBoard.begin(board_dir, repo=repo, table=table, items=inp["items"], origin=ORIGIN, base_rev="",
                               request_text=inp["request_text"],
                               inputs={"gates": inp["gates"] or None, "policy_md": inp["policy_md"] or None},
                               stop_after_round=1, **hook_kwargs(LINE, table))
    except Reject as e:
        raise InputRefused(f"盤面が入力を受けない: {e}") from None
    ran = set()
    pr = None
    try:
        while p["run_engine"]:
            for nid in p["run_engine"]:
                if nid in ran:
                    raise BoardGap(f"{nid} を走らせた後も run_engine に残る（盤面の欠陥）")
                ran.add(nid)
                if nid == prcheck.NODE:
                    pr = prcheck.run_helper(b, runner=runner)
                elif _is_ci(b, nid):
                    run_ci(b, nid, test_cmd=inp["test_cmd"], runner=runner)
                else:
                    raise BoardGap(f"start は engine_run の節 {nid} の回し方を知らない（CI の節と {prcheck.NODE} だけ）")
            p = b.settle()
        if pr is None:   # 呼び直し（前の start で落ちていた）: 走らせずに盤面から読む
            pr = prcheck.run_helper(b, runner=runner)
    except prcheck.Refused as e:
        raise InputRefused(str(e)) from None
    ci_role_go = any(_fell_back(b, nid) for nid in p["ready"] if _is_ci(b, nid))
    try:
        ticket.write(board_dir, repo, run_id)
    except ticket.TicketError as e:
        raise InputRefused(f"包みの切符を書けない: {e}") from None
    pol = policy.brief(b)
    absent = len(b.state["works"].get("not_in_line") or [])
    n_items = len(inp["items"])
    thick = inp["thickness"] + ("（既定）" if not _word(raw, "thickness") else "")
    head = (f"入口: 判定から（依頼 {n_items} 件）・段: {thick}・gates: {inp['gates'] or '空'}・"
            f"このラインに無い節: {absent} 個・{prcheck.head_downgrades(LINE)}")
    if ci_role_go:
        head += "・修正前のテスト: 宣言も test_cmd も無い——任せ先の役がリポジトリから走らせ方を探す"
    base_rev = (b.record.get("base") or "")
    out = {"ok": True, "base_rev": base_rev, "test_cmd": inp["test_cmd"], "policy_paste": pol["paste"],
           "policy_path": pol["path"], "mid_gate": inp["mid_gate"], "adapter": inp["adapter"], "thickness": inp["thickness"],
           "gates": inp["gates"], "ci_role_go": ci_role_go, "pr_go": bool(pr["role_needed"]), "head_line": head}
    keep = {k: inp[k] for k in ("request_file", "test_cmd", "thickness", "gates", "mid_gate", "adapter", "policy_md")}
    doc = {**keep, "run_id": run_id, "requests": n_items, "base_rev": base_rev, "ci_role_go": ci_role_go,
           "pr_go": out["pr_go"], "head_line": head}
    work = b.work("start.json")
    tmp = work.with_name(work.name + ".tmp")
    tmp.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, work)
    return out
