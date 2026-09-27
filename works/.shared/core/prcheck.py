"""並行 PR の検査 p0.parallel_pr（線 A。仕様 3.8・裁定 TA8。持ち主の答え 2026-09-27: 案 (a)）。

1〜5 段（owner/repo の解決・自分の PR の除外・打ち切り・変更ファイルの交差）は、盤面の層の run_engine が写しの
parallel-pr.py を走らせる（run_helper）。交差が在る・remote が GitHub でない・gh が無い時だけ任せ先に落ち、読むだけの
opus の役 pr-check（ブロック blk-pr）が 6 段の全部をする。6 段目だけ替える: 担当の PR へ投稿せず、申し送りの下書きを
conflicts[].note に書き handed_over を false で返す（真は blk-pr/scripts/accept.py の check_no_post が拒む）。
投稿しないことは review-graph より下げた所で、<ライン>/downgrades.json に宣言し、報告の冒頭に出す。

ここに在る物:
- NODE・ROLE・OUTPUT_FORMAT: 節の名前、役の名前、役の output_format（写しの schema に印 works-node: pr-check no-post）
- run_helper(b, *, runner=None): start（と線 B の境の節）が呼ぶ。engine で済んだか・役が要るか
- snapshot・take・collect・drafts: blk-pr の節 pr-snap・pr-accept・collect の中身（main_* はスクリプトの入口）
- downgrades・head_downgrades: 下げた物の一覧（<ライン>/downgrades.json）と、報告の頭の行の部品

盤面を開く口は線 A の entry.open_board（Task 3）。ここでは opener で差し替えられる（試験は節の表を渡して開く）。
take は entry.take（Task 9）と同じ約束の、このブロックだけの形（Task 9 が入ったら entry.take に寄せる。報告の配線の残り）。
"""
import json
import os
import pathlib
import sys

sys.dont_write_bytecode = True

CORE = pathlib.Path(__file__).resolve().parent
PACK = CORE.parents[1]
if str(CORE) not in sys.path:
    sys.path.insert(0, str(CORE))

from accept import role_schema, snapshot_tree  # noqa: E402
from board import GRAPH_PATH, BoardGap  # noqa: E402  （board が写しの engine を sys.path に足す）
from engine.util import AnswerReject, Reject  # noqa: E402
import script_io  # noqa: E402

NODE = "p0.parallel_pr"
ROLE = "pr-check"
LINE = "darkfactory"
MARK = "works-node: pr-check no-post"   # node_marker.mark(role_schema(NODE), "pr-check", flags=("no-post",)) と同じ印（Task 2）
OUTPUT_FORMAT = {"description": MARK, **role_schema(NODE)}
SNAPSHOT = "pr-snapshot.json"   # 役を起こす前の作業ツリーの写し（accept.snapshot_tree の形）
BRIEF = "pr-brief.json"         # 役への渡し物（落ちた理由・交差を取る集合・版）
READS = (ROLE, "pr-checking", "pr-loop", ROLE)   # reads.main_for の (役, include, 輪, 節)
DOWNGRADES = "downgrades.json"
DOWNGRADE_KEYS = ("node", "what", "versus")
ARTIFACTS_ENV = script_io.ARTIFACTS_ENV


class Refused(Exception):
    """engine の 1〜5 段を走らせられない（呼び直しても計画が拒まれる・対象の根が引けない）。start は AI を起こす前に止める
    （entry の CiRefused と同じ扱い）"""


def open_board(board_dir, **kw):
    """盤面を開く既定の口（線 A の entry.open_board。節の表と board_hook.py を引く）"""
    try:
        import entry
    except ModuleNotFoundError as e:
        if e.name != "entry":
            raise
        raise BoardGap("盤面を開く口 entry.open_board（線 A Task 3）がまだ無い") from None
    return entry.open_board(board_dir, **kw)


def _waiting(b):
    """この周の待っている p0.parallel_pr の instance（人に聞いている間・止めた run は無い扱い）"""
    if b.state.get("pending_human") or b.state.get("halted"):
        return None
    inst = b.rd["instances"].get(NODE)
    return inst if inst and inst.get("status") == "pending" else None


# ---------------------------------------------------------------- engine の 1〜5 段
def run_helper(b, *, runner=None) -> dict:
    """ready に p0.parallel_pr が在れば run_engine で 1〜5 段を走らせる。返り {by, role_needed, why}:
    - engine で済んだ → by "engine"（why は走らせずに返答を組んだ時の理由。無ければ空）
    - 任せ先に落ちた（今落ちた・前に落ちていた）→ by "role"・role_needed 真・why は落ちた理由。表の fallback が absent なら
      節は skipped で by ""・role_needed 偽
    - ready に無い → by ""・role_needed 偽
    relaunch（計画の宣言が変わった）は 1 度だけ呼び直す。2 度目も同じか、why だけの返り（対象の根が引けない）なら Refused"""
    inst = _waiting(b)
    if inst is None:
        return {"by": "", "role_needed": False, "why": ""}
    if inst.get("engine_fallback"):
        return {"by": "role", "role_needed": True, "why": inst["engine_fallback"]}
    for attempt in (1, 2):
        got = b.run_engine(NODE, runner=runner)
        if got.get("ok"):
            return {"by": "engine", "role_needed": False, "why": got.get("blocked") or ""}
        if "fallback" in got:
            waiting = _waiting(b) is not None
            return {"by": "role" if waiting else "", "role_needed": waiting, "why": got["fallback"]}
        if not got.get("relaunch"):
            raise Refused(f"{NODE} を engine で走らせられない: {got.get('why')}")
    raise Refused(f"{NODE} の計画が 2 度とも拒まれた（呼び直しても同じ）: {got.get('why')}")


# ---------------------------------------------------------------- blk-pr の節
def _write(path: pathlib.Path, obj) -> pathlib.Path:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    os.replace(tmp, path)
    return path


def snapshot(board_dir, repo, *, opener=None) -> dict:
    """pr-snap: 任せ先の役を起こす前に、作業ツリーの写し（SNAPSHOT）と役への渡し物（BRIEF）を今の周の作業ファイルに書く。
    渡し物は {node, cwd, base, changed_files, request_wheres, fallback}——changed_files は engine の helper と同じ集合
    （写しの RL の _pr_files。差分が空なら依頼の where が名指す追跡中のパス）。任せ先に落ちていない節には BoardGap
    （pr_go が偽の run では blk-pr を開かない）。返り {ok, snapshot_file, brief_file}"""
    b = (opener or open_board)(board_dir)
    inst = _waiting(b)
    if inst is None or not inst.get("engine_fallback"):
        raise BoardGap(f"{NODE} は任せ先に落ちて待っていない——blk-pr は start の pr_go が真の時だけ開く")
    repo = pathlib.Path(repo).resolve()
    base = b.record.get("base") or (b.record.get("process", {}).get("base") or {}).get("base_sha")
    brief = {"node": NODE, "cwd": str(repo), "base": base, "changed_files": b.rules._pr_files(b),
             "request_wheres": b.rules.request_wheres(b), "fallback": inst["engine_fallback"]}
    snap = _write(b.work(SNAPSHOT), snapshot_tree(repo))
    out = _write(b.work(BRIEF), brief)
    return {"ok": True, "snapshot_file": str(snap), "brief_file": str(out)}


def take(board_dir, reply: dict, repo, *, opener=None) -> dict:
    """pr-accept の中身（works だけの検査 check_no_post の後）: 読むだけの役が作業ツリーを変えていないか（pr-snap の写しと
    比べる）→ 盤面の done（写しの schema と規則が盤面の上で当たる）。返り {ok, reason, ready, asking, halted, out_file}。
    返答の中身の誤り（AnswerReject）と作業ツリーの変化だけを ok 偽で返す（盤面は書かない。入れ物は捨てる）。
    写しが無い（pr-snap が走っていない）・止めた run への書き込み（Reject）・BoardGap は投げる（回す側の誤り）"""
    b = (opener or open_board)(board_dir)
    snap_p = b.work(SNAPSHOT)
    if not snap_p.is_file():
        raise BoardGap(f"{snap_p} が無い——pr-snap が走っていない（役を起こす前の写しと比べられない）")
    try:
        snap = json.loads(snap_p.read_text(encoding="utf-8"))
        before = {k: snap[k] for k in ("porcelain", "diff_sha256")}
    except (OSError, ValueError, KeyError, TypeError) as e:
        raise BoardGap(f"{snap_p} が読めない: {e}") from None
    now = snapshot_tree(pathlib.Path(repo))
    if now != before:
        return {"ok": False, "reason": "読むだけの役が作業ツリーを変えた: 並行 PR の任せ先は読むだけの役で、作業ツリーを変えてはいけない"
                f"（git status --porcelain: 役を起こす前 {before['porcelain'].splitlines()[:5]} / 今 {now['porcelain'].splitlines()[:5]}）"}
    try:
        p = b.done(NODE, reply)
    except AnswerReject as e:
        return {"ok": False, "reason": str(e)}
    return {"ok": True, "reason": "", "ready": p["ready"], "asking": bool(p["asking"]), "halted": bool(p["halted"]),
            "out_file": b.state["outputs"][NODE]["file"]}


def _accepted(board) -> tuple:
    """(state, 受け付けた返答, 返答のファイル)。受けていなければ返答とファイルは None"""
    board = pathlib.Path(board)
    try:
        state = json.loads((board / "state.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None, None, None
    out = (state.get("outputs") or {}).get(NODE)
    if not out:
        return state, None, None
    f = board / out["file"]
    try:
        return state, json.loads(f.read_text(encoding="utf-8")), f
    except (OSError, ValueError):
        return state, None, None


def drafts(board) -> list:
    """受け付けた返答の申し送りの下書き [{pr, files, note}]（note を持つ交差だけ。報告の冒頭 1 が人に渡す）"""
    _, rep, _ = _accepted(board)
    return [{"pr": c["pr"], "files": c["files"], "note": c["note"]}
            for c in (rep or {}).get("conflicts", []) if c.get("note")]


def collect(board) -> dict:
    """集める節: {ok, pr_file, conflicts, drafts, material_status, reads_file}（drafts は note を持つ交差の件数）。
    reads_file は読んだ証拠の節（pr-reads）が今の周に書いた reads-pr-check.json（無ければ空）。
    盤面が p0.parallel_pr を受けていない・handed_over が真の行が残る時は ok 偽"""
    state, rep, f = _accepted(board)
    if rep is None:
        return {"ok": False, "reason": f"盤面が {NODE} の返答を受けていない", "pr_file": "", "conflicts": 0, "drafts": 0,
                "material_status": "", "reads_file": ""}
    reads = pathlib.Path(board) / f"r{state['round']}" / f"reads-{ROLE}.json"   # b.work と同じ置き場（今の周）
    posted = [c["pr"] for c in rep["conflicts"] if c.get("handed_over")]
    return {"ok": not posted, "reason": f"handed_over が真の行が在る: {posted}" if posted else "", "pr_file": str(f),
            "conflicts": len(rep["conflicts"]), "drafts": sum(1 for c in rep["conflicts"] if c.get("note")),
            "material_status": rep["material"]["status"], "reads_file": str(reads) if reads.is_file() else ""}


# ---------------------------------------------------------------- スクリプトの入口
def _artifacts():
    d = os.environ.get(ARTIFACTS_ENV)
    if not d:
        print(f"環境変数が無い: {ARTIFACTS_ENV}", file=sys.stderr)
        return None
    return pathlib.Path(d) / script_io.BOARD_DIR


def main_take(reply_env: str = "INPUTS_REPLY") -> int:
    """pr-accept のスクリプトの入口（script_io.main と同じ約束）。中身の拒否は 0 で {"ok": false, "reason"} を 1 行、
    回す側の誤り（環境変数の欠け・BoardGap・止めた run への書き込み）は標準エラーに 1 行で 2（TA19）"""
    if reply_env not in os.environ:
        print(f"環境変数が無い: {reply_env}", file=sys.stderr)
        return 2
    board = _artifacts()
    if board is None:
        return 2
    raw = os.environ[reply_env]
    try:
        reply = json.loads(raw)
    except ValueError as e:
        script_io._emit({"ok": False, "reason": f"返答が JSON として読めない: {e}（頭: {raw[:200]!r}）"})
        return 0
    if not isinstance(reply, dict):
        script_io._emit({"ok": False, "reason": f"返答が JSON のオブジェクトでない（{type(reply).__name__}）"})
        return 0
    try:
        got = take(board, reply, pathlib.Path.cwd())
    except (BoardGap, Reject) as e:
        print(f"{NODE} の受け付けを回せない: {e}", file=sys.stderr)
        return 2
    script_io._emit(got)
    return 0


def main_snapshot() -> int:
    """pr-snap のスクリプトの入口。回す側の誤り（環境変数の欠け・BoardGap・git が効かない）は 2"""
    board = _artifacts()
    if board is None:
        return 2
    try:
        got = snapshot(board, pathlib.Path.cwd())
    except (BoardGap, Reject) as e:
        print(f"{NODE} の写しを置けない: {e}", file=sys.stderr)
        return 2
    script_io._emit(got)
    return 0


def main_collect() -> int:
    """collect のスクリプトの入口。環境変数が欠けたら 2"""
    board = _artifacts()
    if board is None:
        return 2
    script_io._emit(collect(board))
    return 0


# ---------------------------------------------------------------- 下げた物の宣言
def downgrades(line: str = LINE, *, pack: pathlib.Path = PACK) -> list:
    """<pack>/<line>/downgrades.json（[{node, what, versus}]。無ければ []）。形が崩れていれば BoardGap
    （黙って 0 個と数えない）。node は写しの graph の節"""
    p = pathlib.Path(pack) / line / DOWNGRADES
    if not p.is_file():
        return []
    try:
        rows = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise BoardGap(f"{p} が読めない: {e}") from None
    nodes = json.loads(GRAPH_PATH.read_text(encoding="utf-8"))["nodes"]
    bad = [] if isinstance(rows, list) else [f"一番上が配列でない（{type(rows).__name__}）"]
    for i, r in enumerate(rows if isinstance(rows, list) else []):
        if not (isinstance(r, dict) and sorted(r) == sorted(DOWNGRADE_KEYS)
                and all(isinstance(r[k], str) and r[k].strip() for k in DOWNGRADE_KEYS)):
            bad.append(f"{i} 行目が {{node, what, versus}}（空でない文字列）でない: {r!r}")
        elif r["node"] not in nodes:
            bad.append(f"{i} 行目の node {r['node']!r} は graph の節に無い")
    if bad:
        raise BoardGap(f"{p}: " + "; ".join(bad))
    return rows


def head_downgrades(line: str = LINE, *, pack: pathlib.Path = PACK) -> str:
    """報告の頭の行（と start の head_line）の部品「下げている所: K 個」"""
    return f"下げている所: {len(downgrades(line, pack=pack))} 個"
