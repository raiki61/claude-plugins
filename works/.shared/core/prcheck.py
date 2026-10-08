"""並行 PR の検査 p0.parallel_pr（線 A。仕様 3.8・裁定 TA8。持ち主の答え 2026-09-27: 案 (a)）。

1〜5 段（owner/repo の解決・自分の PR の除外・打ち切り・変更ファイルの交差）は、盤面の層の run_engine が写しの
parallel-pr.py を走らせる（run_helper）。交差が在る・gh が無い時だけ任せ先に落ち、読むだけの
段に書いた模型（sonnet・medium）の役 pr-check（ブロック blk-pr）が 6 段の全部をする。remote が forge（PR を持つホスト。GitHub）
でない run（origin が無い・ローカルのパス・ほかのホスト）は、entry の差し替え（on_init・parallel_pr_due・fill_materials。forge.py）
が run の初めに決めて節を条件外にし、素材を not_applicable（no_forge: <種類>）で埋めるので、ここにも役にも来ない。6 段目だけ替える: 担当の PR へ投稿せず、申し送りの下書きを
conflicts[].note に書き handed_over を false で返す（真は blk-pr/scripts/accept.py の check_no_post が拒む）。
投稿しないことは review-graph より下げた所で、<ライン>/downgrades.json に宣言し、報告の冒頭に出す。
review-graph の 6 段の「衝突した箇所を本ループのスコープから外す」は保つ: 役は外す hunk（PR・ファイル・今の作業ツリーでの行の範囲）を
excluded に並べ、受け付けが確かめて今の周の pr-excluded.json に置き、collect が excluded_file で渡す（後の役に触らせないため）。

ここに在る物:
- NODE・ROLE・OUTPUT_FORMAT: 節の名前、役の名前、役の output_format（写しの schema に works だけの欄 excluded を足し、
  印 works-node: pr-check を付けた物。excluded は受け付けが外してから盤面に渡す）
- GH_ENV・GH_WRAPPER・GH_READ: 包みの読む口の環境変数と、役が打つ形、打ってよい gh の語（口を通す）
- run_helper(b, *, runner=None): start（と線 B の境の節）が呼ぶ。engine で済んだか・役が要るか
- snapshot・take・collect・drafts: blk-pr の節 pr-snap・pr-accept・collect の中身（main_* はスクリプトの入口）
- downgrades・head_downgrades: 下げた物の一覧（<ライン>/downgrades.json）と、報告の頭の行の部品

盤面を開く口は線 A の entry.open_board（Task 3）。ここでは opener で差し替えられる（試験は節の表を渡して開く）。
take は entry.take（Task 9）と同じ約束の、このブロックだけの形（rolekit.accept_role の take に渡す）。
"""
import hashlib
import json
import os
import pathlib
import sys

sys.dont_write_bytecode = True

CORE = pathlib.Path(__file__).resolve().parent
PACK = CORE.parents[1]
if str(CORE) not in sys.path:
    sys.path.insert(0, str(CORE))

from accept import TREE_KEYS, role_schema, tree_moved, tree_state  # noqa: E402
from board import GRAPH_PATH, BoardGap  # noqa: E402  （board が写しの engine を sys.path に足す）
from engine.schema import validate_schema  # noqa: E402
from engine.util import AnswerReject, Reject  # noqa: E402
import script_io  # noqa: E402

NODE = "p0.parallel_pr"
ROLE = "pr-check"
MARK = "works-node: pr-check"   # node_marker.mark(role_schema(NODE), "pr-check") と同じ印（Task 2）
# 本ループのスコープから外す hunk（works だけの欄。写しの schema の conflicts[] は additionalProperties: false で足せないので、
# 返答の一番上に置き、受け付けが外してから盤面に渡す）。start・end は今の作業ツリーのファイルの行（1 始まり・両端を含む）
EXCLUDED_SCHEMA = {"type": "array", "items": {
    "type": "object", "required": ["pr", "file", "start", "end", "why"], "additionalProperties": False,
    "properties": {"pr": {"type": "string", "minLength": 1}, "file": {"type": "string", "minLength": 1},
                   "start": {"type": "integer", "minimum": 1}, "end": {"type": "integer", "minimum": 1},
                   "why": {"type": "string", "minLength": 1}}}}


def _output_format():
    s = role_schema(NODE)
    s["properties"]["excluded"] = EXCLUDED_SCHEMA
    s["required"] = [*s["required"], "excluded"]
    return {"description": MARK, **s}


OUTPUT_FORMAT = _output_format()
SNAPSHOT = "pr-snapshot.json"   # 役を起こす前の作業ツリーの写し（accept.tree_state の形）
EXCLUDED = "pr-excluded.json"   # 受け付けた外す hunk {node, excluded}（collect の excluded_file）
# 読む gh は包みの読む口を通す: 印のある起動の全部に、包み（.shared/core/adapter.py の 5）が素の gh を拒み（permissions.deny Bash(gh:*) と
#   本物の gh のパス）、許す物だけを通す口のパスを環境変数 WORKS_GH に置く。口が通すのは pr list・pr view・pr diff の -R つきと
#   repo view <OWNER/REPO> だけ。役は `"$WORKS_GH" pr view <n> -R <owner/repo>` の形で打つ（指示書と試験がこの形を見る）。
# GH_READ: 口を通して打ってよい gh の語（全部 -R <owner/repo> を付ける）。許す物の正本は包みの口の側で、これは指示書の側の組。
#   禁じる物の一覧は読むだけの役にとって完全にならない（gh pr update-branch・git push など）ので、柵は許す物で組む。
GH_ENV = "WORKS_GH"
GH_WRAPPER = f'"${GH_ENV}"'
GH_READ = ("pr list", "pr view", "pr diff")
BRIEF = "pr-brief.json"         # 役への渡し物（落ちた理由・交差を取る集合・版）
STOP_BY = "works:pr"           # 任せ先の役が 3 回とも拒まれて輪を抜けた盤面の state.stop.by
READS = (ROLE, "pr-loop", ROLE)   # reads.main_for の (役, 輪, 節)（include の名は reads が今の scope から引く）
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
def _anchored(excluded: list, repo) -> list:
    """外す hunk ごとに、受け付けた時の行の中身 text（start〜end。改行つき）と、その行のバイトの sha256 を足した写し。
    行の番号は後の周の修正でずれるので、後の役・受け付けは中身で引き直す（review-graph は同じ writer が中身で覚えている）"""
    out = []
    for h in excluded:
        raw = b"".join((pathlib.Path(repo) / h["file"]).read_bytes().splitlines(keepends=True)[h["start"] - 1:h["end"]])
        out.append({**h, "text": raw.decode("utf-8", "replace"), "sha256": hashlib.sha256(raw).hexdigest()})
    return out


def check_excluded(reply: dict, repo) -> list:
    """外す hunk（excluded）の誤りの一覧（空なら通す。返答の残りは写しの schema を通った後に呼ぶ）: 型・start <= end・PR が conflicts に在りファイルがその行の files に在る・
    ファイルが今の作業ツリーに在り end が行の数を超えない・外す hunk を持つ PR の行に申し送りの下書き（note）が在る"""
    ex = reply.get("excluded")
    if ex is None:
        return ["excluded が無い（外す hunk が無ければ空の配列）"]
    errs = validate_schema(ex, EXCLUDED_SCHEMA)
    if errs:
        return [f"excluded の型: {e}" for e in errs]
    rows = {c.get("pr"): c for c in reply.get("conflicts") or [] if isinstance(c, dict)}
    out = []
    for i, h in enumerate(ex):
        at = f"excluded[{i}]（PR {h['pr']}・{h['file']}）"
        c = rows.get(h["pr"])
        if h["start"] > h["end"]:
            out.append(f"{at}: start {h['start']} が end {h['end']} より大きい")
        if c is None:
            out.append(f"{at}: PR {h['pr']} は conflicts に無い")
            continue
        if h["file"] not in (c.get("files") or []):
            out.append(f"{at}: ファイルは PR {h['pr']} の交差したファイル {c.get('files')} に無い")
        f = pathlib.Path(repo) / h["file"]
        if not f.is_file():
            out.append(f"{at}: ファイルが今の作業ツリーに無い（行の範囲は今の作業ツリーのファイルで書く）")
        else:
            n = len(f.read_bytes().splitlines())
            if h["end"] > n:
                out.append(f"{at}: end {h['end']} がファイルの行の数 {n} を超える")
        if not (c.get("note") or "").strip():
            out.append(f"{at}: 外す hunk を持つ PR {h['pr']} の行に申し送りの下書き（note）が無い")
    return out


def _write(path: pathlib.Path, obj) -> pathlib.Path:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    os.replace(tmp, path)
    return path


def snapshot(board_dir, repo, *, opener=None) -> dict:
    """pr-snap: 任せ先の役を起こす前に、作業ツリーの写し（SNAPSHOT）と役への渡し物（BRIEF）を今の周の作業ファイルに書く。
    渡し物は {node, cwd, base, changed_files, request_wheres, fallback}——changed_files は engine の helper と同じ集合
    （写しの RL の _pr_files。差分が空なら依頼の where が名指す追跡中のパス）。任せ先に落ちていない節には BoardGap
    （pr_go が偽の run では blk-pr を開かない）。最後に起こした印（mark_launched）を今の試行に置く。
    返り {ok, snapshot_file, brief_file, attempt, out_path}"""
    b = (opener or open_board)(board_dir)
    inst = _waiting(b)
    if inst is None or not inst.get("engine_fallback"):
        raise BoardGap(f"{NODE} は任せ先に落ちて待っていない——blk-pr は start の pr_go が真の時だけ開く")
    repo = pathlib.Path(repo).resolve()
    base = b.record.get("base") or (b.record.get("process", {}).get("base") or {}).get("base_sha")
    brief = {"node": NODE, "cwd": str(repo), "base": base, "changed_files": b.rules._pr_files(b),
             "request_wheres": b.rules.request_wheres(b), "fallback": inst["engine_fallback"]}
    snap = _write(b.work(SNAPSHOT), tree_state(repo))
    out = _write(b.work(BRIEF), brief)
    # pr-snap は役を起こす前の最後の節: 起こした印を今の試行に置く（盤面のラインの約束 2。印の無い試行の返答は done が受けない）。
    # 同じ試行への 2 度目は前の印を返す（Archon の再開で pr-snap が走り直しても）
    m = b.mark_launched(NODE, inst.get("attempts", 1))
    return {"ok": True, "snapshot_file": str(snap), "brief_file": str(out), "attempt": m["attempt"], "out_path": m["out_path"]}


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
        before = {k: snap[k] for k in TREE_KEYS}
    except (OSError, ValueError, KeyError, TypeError) as e:
        raise BoardGap(f"{snap_p} が読めない: {e}") from None
    repo = pathlib.Path(repo)
    moved = tree_moved(before, repo)   # 共通の比べ（R47。HEAD が引けなくなったのもここで 1 行になる）
    if moved:
        return {"ok": False, "reason": "読むだけの役が作業ツリーを変えた: 並行 PR の任せ先は読むだけの役で、作業ツリー・HEAD・枝・"
                "git が無視するファイルを変えてはいけない（checkout・switch・stash・reset・gh pr checkout を打つな）（"
                + "・".join(moved) + "）"}
    # 写しの schema を先に当てる（型の崩れた conflicts を外す hunk の検査が読んで落ちないように。拒みの文は盤面の done と同じ形）
    errs = validate_schema({k: v for k, v in reply.items() if k != "excluded"}, role_schema(NODE))
    if errs:
        return {"ok": False, "reason": "返答が型に合わない（直して返し直す）:\n" + "\n".join(f"  - {e}" for e in errs)}
    errs = check_excluded(reply, repo)
    if errs:
        return {"ok": False, "reason": "外す hunk（excluded）が合わない: " + "; ".join(errs)}
    excluded = _anchored(reply["excluded"], repo)
    try:
        p = b.done(NODE, {k: v for k, v in reply.items() if k != "excluded"})
    except AnswerReject as e:
        return {"ok": False, "reason": str(e)}
    _write(b.work(EXCLUDED), {"node": NODE, "head": before["head"], "excluded": excluded})   # 上で比べて同じ（HEAD も起こす前のまま）
    return {"ok": True, "reason": "", "ready": p["ready"], "asking": bool(p["asking"]), "halted": bool(p["halted"]),
            "out_file": b.state["outputs"][NODE]["file"]}


def _accepted(b) -> tuple:
    """(受け付けた返答, 返答のファイル)。受けていなければ (None, None)"""
    out = (b.state.get("outputs") or {}).get(NODE)
    if not out:
        return None, None
    f = b.dir / out["file"]
    try:
        return json.loads(f.read_text(encoding="utf-8")), f
    except (OSError, ValueError):
        return None, None


def drafts(board, *, opener=None) -> list:
    """受け付けた返答の申し送りの下書き [{pr, files, note}]（note を持つ交差だけ。報告の冒頭 1 が人に渡す）"""
    rep, _ = _accepted((opener or open_board)(board, allow_halted=True))
    return [{"pr": c["pr"], "files": c["files"], "note": c["note"]}
            for c in (rep or {}).get("conflicts", []) if c.get("note")]


def collect(board, *, opener=None, gave_up=None) -> dict:
    """集める節: {ok, pr_file, conflicts, drafts, material_status, excluded, excluded_file, reads_file}。
    drafts は note を持つ交差の件数、excluded は本ループのスコープから外した hunk の数、excluded_file はその一覧
    （pr-excluded.json。後の役——判定・修正案・修正——に触らせない範囲として渡す）。reads_file は読んだ証拠の節（pr-reads）が
    今の周に書いた reads-pr-check.json（無ければ空）。盤面が p0.parallel_pr を受けていない・handed_over が真の行が残る・
    外す hunk の一覧が無い時は ok 偽。gave_up(board) -> str は受けていない時の諦めの腕（blk-pr の collect が rolekit.gave_up を
    渡す: 3 回の拒否で輪を抜けたなら最後の拒否の文で盤面を止めて理由を返す。後ろの役を起こさない）"""
    b = (opener or open_board)(board, allow_halted=True)
    rep, f = _accepted(b)
    empty = {"pr_file": "", "conflicts": 0, "drafts": 0, "material_status": "", "excluded": 0, "excluded_file": "",
             "reads_file": ""}
    if rep is None:
        why = gave_up(board) if gave_up is not None else ""
        return {"ok": False, "reason": why or f"盤面が {NODE} の返答を受けていない", **empty}
    reads, ex_p = b.work(f"reads-{ROLE}.json"), b.work(EXCLUDED)
    try:
        excluded = json.loads(ex_p.read_text(encoding="utf-8"))["excluded"]
    except (OSError, ValueError, KeyError, TypeError):
        excluded = None
    posted = [c["pr"] for c in rep["conflicts"] if c.get("handed_over")]
    why = ([f"handed_over が真の行が在る: {posted}"] if posted else []) + \
          ([f"外す hunk の一覧 {ex_p} が読めない"] if excluded is None else [])
    return {"ok": not why, "reason": "; ".join(why), "pr_file": str(f),
            "conflicts": len(rep["conflicts"]), "drafts": sum(1 for c in rep["conflicts"] if c.get("note")),
            "material_status": rep["material"]["status"], "excluded": len(excluded or []),
            "excluded_file": str(ex_p) if excluded is not None else "", "reads_file": str(reads) if reads.is_file() else ""}


# ---------------------------------------------------------------- スクリプトの入口
# 受け付け（pr-accept）は blk-pr/scripts/accept.py が rolekit.main_accept に take を渡して回す（拒否の控え・3 回目で done。R50）。
# pr-snap・collect の 1 行は $LOOP_PREV で次の周へ渡らないので script_io._emit で出す（形は同じ 1 行・ensure_ascii=False）
def _artifacts():
    d = os.environ.get(ARTIFACTS_ENV)
    if not d:
        print(f"環境変数が無い: {ARTIFACTS_ENV}", file=sys.stderr)
        return None
    return pathlib.Path(d) / script_io.BOARD_DIR


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


def main_collect(gave_up=None) -> int:
    """collect のスクリプトの入口（gave_up は collect の諦めの腕）。環境変数が欠けたら 2"""
    board = _artifacts()
    if board is None:
        return 2
    try:
        got = collect(board, gave_up=gave_up)
    except (BoardGap, Reject) as e:
        print(f"{NODE} の出口を組めない: {e}", file=sys.stderr)
        return 2
    script_io._emit(got)
    return 0


# ---------------------------------------------------------------- 下げた物の宣言
def downgrades(line: str, *, pack: pathlib.Path = PACK) -> list:
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


def head_downgrades(line: str, *, pack: pathlib.Path = PACK) -> str:
    """報告の頭の行（と start の head_line）の部品「下げている所: K 個」"""
    return f"下げている所: {len(downgrades(line, pack=pack))} 個"
