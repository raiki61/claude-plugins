"""修正の受け付けを盤面の数え直しに替える（線 A。仕様 3.2・計画 Task 12）。

1 本目の受け付け（accept.check_fix: changes[].unit_key を修正案に読み替えて fix_plan_covers_units）を、盤面の
done("p3.fix") に替える。graph の p3.fix の受け付けの検査は写しの fix_covers_open_units で、盤面の上で次を当てる:
直す義務の単位（[block] と do-now）を全部覆うか・修正が在るのに閉鎖の実証を黙らせていないか・判定役の class_query を
修正前の版（state.inputs.review_rev）と修正後の作業ツリーで数え直し、closure.sites の数と母数が合うか・欠陥の形の数が
減ったか・修正が書いた指し（wrote_refs）を現物で引けるか（読んだ記録は包みの置き場 adapter.reads_dir(run の worktree)/reads.jsonl から。
写しの RL の hook_evidence の置き場を entry.CORE_OVERRIDES が差し替える）。
数え直した件数は盤面の loop.coverage_after、指しの読了は loop.wrote_refs_reads に残る。

ここに在る物:
- FIX_NODE・ROLE・FIX_OUTPUT_FORMAT: 節の名前、役の名前（印の名）、役の output_format（graph の p3.fix の schema に
  印 works-node: fix を付けた物。Task 17 で blk-fix.yaml の fix に貼る）
- READS: 読んだ証拠の節 fix-reads が reads.main_for に渡す (役, include, 輪, 節)
- accept_fix: 節 fix-accept の中身。entry.take に渡し、1 本目の出口のための changes を足す
- collect: 節 collect の中身。1 本目の出口の欄に fix_file・not_done・coverage・reads_file を足す
- main_accept: 受け付けのスクリプトの入口（script_io.main の約束。回す側の誤りは 2）
"""
import json
import os
import pathlib
import sys

sys.dont_write_bytecode = True

CORE = pathlib.Path(__file__).resolve().parent
if str(CORE) not in sys.path:
    sys.path.insert(0, str(CORE))

from accept import role_schema  # noqa: E402
from board import BoardGap  # noqa: E402  （board が写しの engine を sys.path に足す）
from engine.util import Reject  # noqa: E402
import entry  # noqa: E402
import node_marker  # noqa: E402

FIX_NODE = "p3.fix"
ROLE = "fix"
FIX_OUTPUT_FORMAT = node_marker.mark(role_schema(FIX_NODE), ROLE)
READS = (ROLE, "fixing", "fix-loop", ROLE)   # reads.main_for の (役, include, 輪, 節)。include の名は darkfactory の fixing
V1_CHANGE_KEYS = ("unit_key", "files", "what")   # 1 本目の出口の changes の欄（assert-changed・changes.json が読む）
CHANGES_FILE = "changes.json"


class Unreadable(Exception):
    """集める節の入力が読めない・盤面が修正を受けていない（回す側の誤り。スクリプトは 2）"""


def _fix_output(b) -> tuple:
    """(盤面が受けた p3.fix の返答, そのファイルの絶対パス)。今の周に受けていなければ Unreadable"""
    out = (b.state.get("outputs") or {}).get(FIX_NODE)
    if not out or out.get("round") != b.round:
        raise Unreadable(f"盤面が今の周（{b.round}）の {FIX_NODE} を受けていない")
    f = b.dir / out["file"]
    try:
        return json.loads(f.read_text(encoding="utf-8")), f
    except (OSError, ValueError) as e:
        raise Unreadable(f"盤面の {FIX_NODE} の返答 {f} が読めない: {e}") from None


def accept_fix(reply: dict, board: pathlib.Path, base_rev: str, repo: pathlib.Path) -> dict:
    """修正役の返答を盤面に渡す（entry.take(board, "p3.fix", reply, repo)）。結果に 1 本目の出口のための changes
    （[{unit_key, files, what}]。盤面が受けた返答の changes[] から写す）を足す。拒否のときの changes は空（1 本目と同じ）。
    base_rev は受け取るだけ（修正前の版は盤面の state.inputs.review_rev が決める。start が固めた版）。
    BoardGap・止めた run の Reject は投げる（回す側の誤り。TA19）"""
    got = entry.take(board, FIX_NODE, reply, repo)
    if not got["ok"]:
        return {**got, "changes": []}
    b = entry.open_board(board, allow_halted=True)
    out, _ = _fix_output(b)
    return {**got, "changes": [{k: c[k] for k in V1_CHANGE_KEYS} for c in out["changes"]]}


def _coverage(b) -> dict:
    """単位ごとの {before, after}（盤面の loop.coverage_after の今の周の行。before は修正前の版で数えた母数 total）"""
    cov = b.loop_state.get("coverage_after") or {}
    if cov.get("round") != b.round:
        return {}
    return {i["unit_key"]: {"before": i["total"], "after": i["after"]} for i in cov.get("items") or []}


def collect(board: pathlib.Path, accepted: dict, changed: dict) -> dict:
    """集める節の中身。1 本目の {ok, files, changes_file} を全部残し、fix_file（盤面の state.outputs["p3.fix"]["file"] の
    絶対パス）・not_done（件数）・coverage（単位ごとの {before, after}）・reads_file（fix-reads が今の周に書いた
    reads-fix.json。無ければ空）を足す。受け付けた changes を今の周の changes.json（{"changes": [...]}。1 本目の形）に書く。
    受け付けが通っていない・assert-changed の出力が読めない・盤面が今の周の p3.fix を受けていないときは Unreadable（何も書かない）"""
    if not isinstance(accepted, dict) or accepted.get("ok") is not True:
        raise Unreadable(f"受け付けが通っていない（{(accepted or {}).get('reason') if isinstance(accepted, dict) else accepted!r}）")
    changes = accepted.get("changes")
    if not isinstance(changes, list) or not changes:
        raise Unreadable("受け付けの出力に changes が無い")
    files = changed.get("files") if isinstance(changed, dict) else None
    if not isinstance(changed, dict) or changed.get("ok") is not True or not isinstance(files, list) \
            or not all(isinstance(f, str) for f in files):
        raise Unreadable(f"assert-changed の出力に files が無い（{changed!r}）")
    b = entry.open_board(board, allow_halted=True)
    out, fix_file = _fix_output(b)
    path = b.work(CHANGES_FILE)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps({"changes": changes}, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    os.replace(tmp, path)
    reads = b.work(f"reads-{ROLE}.json")
    return {"ok": True, "files": files, "changes_file": str(path), "fix_file": str(fix_file),
            "not_done": len(out.get("not_done") or []), "coverage": _coverage(b),
            "reads_file": str(reads) if reads.is_file() else ""}


def main_accept(fn=accept_fix) -> int:
    """節 fix-accept のスクリプトの入口。script_io.main（INPUTS_REPLY・INPUTS_BASE_REV・ARTIFACTS_DIR）で fn を呼ぶ:
    中身の拒否（読めない返答を含む）は終了コード 0 の 1 行で、reason_file に理由の本文のパス（裁定 R44）。
    環境変数の欠けは script_io.main の 2。fn が投げた BoardGap・Reject（判定の前・止めた run など。TA19）と思わぬ誤りは、
    標準出力に何も出さずに標準エラーに 1 行で 2（entry.main_take と同じ分け方）"""
    import script_io
    try:
        return script_io.main(fn)
    except (BoardGap, Reject) as e:
        print(f"{FIX_NODE} の受け付けを回せない（{type(e).__name__}）: {' '.join(str(e).split())}", file=sys.stderr)
    except Exception as e:   # 思わぬ誤りも 1 行と 2（traceback を出さない）
        print(f"{FIX_NODE} の受け付けの内部の誤り: {type(e).__name__}: {' '.join(str(e).split())}", file=sys.stderr)
    return 2
