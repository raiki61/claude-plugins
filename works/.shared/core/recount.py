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
  印 works-node: fix と食い違いの申し出の欄 conflicts・Bash で書いたファイルの申告の欄 bash_writes・closure.sites[] の欄 path・
  changes[].precedent の条件付き必須 allOf（_precedent_conditions）を足した物。blk-fix.yaml の fix に貼る）。RULED_OUTPUT_FORMAT は裁定の後の
  2 回目の修正役（印 works-node: fix-ruled continue=fix）の物
- READS: 読んだ証拠の節 fix-reads が reads.main_for に渡す (役, 輪, 節)（include の名は reads が今の scope から引く）。reads_role(tag) は回の印で分けた役の名（2 回目の修正の段の reads-fix.<印>.json）
- accept_fix: 節 fix-accept の中身。entry.take に渡し、1 本目の出口のための changes を足す（v1_changes）
- fix_reply: 修正の返答を読む 1 つの口（今の周の盤面の p3.fix か、無ければ 1 回目に受け付けた返答の控え conflict.held_reply）。
  集める節と報告が読む
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
import conflict  # noqa: E402
import entry  # noqa: E402
import node_marker  # noqa: E402
import writes  # noqa: E402

FIX_NODE = "p3.fix"
ROLE = "fix"
RULED_ROLE = "fix-ruled"   # 裁定の後の 2 回目の修正役（修正役の会話の続き。印 continue=fix）
SITE_PATH = "path"   # closure.sites[] の works だけの欄: site が在るファイルの対象の根からの相対パス（unitrows が問いの当たりに結ぶ）
SITE_PATH_SCHEMA = {"type": "string"}


PRECEDENT_MIN_LEN = 4 # 写しの _precedent_gap・blank(problem, 4) の下限（テストが写しと突き合わせる）


def _precedent_conditions() -> list:
    """changes[].precedent の条件付き必須（draft-07 の if/then）。写しの受け付け（_precedent_gap）と同じ決まり:
    from_judge_row が真でない限り problem を求め、verdict が not_found なら searched、それ以外なら source を求める。
    写しの engine の型検査は if/then を読まないので、役に渡る型（claude の --json-schema）にだけ効く"""
    not_judge_row = {"not": {"required": ["from_judge_row"], "properties": {"from_judge_row": {"const": True}}}}
    is_not_found = {"required": ["verdict"], "properties": {"verdict": {"const": "not_found"}}}
    isnt_not_found = {"required": ["verdict"], "properties": {"verdict": {"not": {"const": "not_found"}}}}

    def needs(field: str) -> dict:
        return {"required": [field], "properties": {field: {"type": "string", "minLength": PRECEDENT_MIN_LEN}}}
    return [{"if": not_judge_row, "then": needs("problem")},
            {"if": {"allOf": [not_judge_row, is_not_found]}, "then": needs("searched")},
            {"if": {"allOf": [not_judge_row, isnt_not_found]}, "then": needs("source")}]


def fix_output_format(name: str = ROLE, cont: str | None = None) -> dict:
    """修正役の output_format: 写しの p3.fix の schema に印と、食い違いの申し出の欄 conflicts・Bash で書いたファイルの申告の欄
    bash_writes・closure.sites[] の欄 path（どれも任意。受け付けが盤面へ渡す前に外す）・changes[].precedent の条件付き必須 allOf"""
    out = node_marker.mark(role_schema(FIX_NODE), name, cont=cont)
    out["properties"]["changes"]["items"]["properties"]["precedent"]["allOf"] = _precedent_conditions()
    out["properties"]["conflicts"] = conflict.CONFLICTS_SCHEMA
    out["properties"][writes.FIELD] = writes.BASH_WRITES_SCHEMA
    site = out["properties"]["changes"]["items"]["properties"]["closure"]["properties"]["sites"]["items"]
    site["properties"][SITE_PATH] = SITE_PATH_SCHEMA
    return out


FIX_OUTPUT_FORMAT = fix_output_format()
RULED_OUTPUT_FORMAT = fix_output_format(RULED_ROLE, ROLE)
READS = (ROLE, "fix-loop", ROLE)   # reads.main_for の (役, 輪, 節)。include の名は reads が今の scope（flow_adapter）から引く
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


def fix_reply(b) -> tuple:
    """(修正の返答, そのファイルの絶対パス)。今の周の盤面の p3.fix（_fix_output）か、無ければ 1 回目に受け付けた返答の控え
    （conflict.held_reply。欄 bash_writes を外した写し。待つ単位が在る間に受け付けが盤面に渡さずに置いた物）。どちらも無ければ
    Unreadable。控えが壊れていれば held_reply の BoardGap"""
    try:
        return _fix_output(b)
    except Unreadable as e:
        held, path = conflict.held_reply(b)
        if held is None:
            raise Unreadable(f"{e}。1 回目に受け付けた返答の控え {path} も無い") from None
    return {k: v for k, v in held.items() if k != writes.FIELD}, path


def v1_changes(rows) -> list:
    """1 本目の出口のための changes（[{unit_key, files, what}]）"""
    return [{k: c[k] for k in V1_CHANGE_KEYS} for c in rows]


def accept_fix(reply: dict, board: pathlib.Path, base_rev: str, repo: pathlib.Path, *, commit: bool = True) -> dict:
    """修正役の返答を盤面に渡す（entry.take(board, "p3.fix", reply, repo)）。結果に 1 本目の出口のための changes
    （[{unit_key, files, what}]。盤面が受けた返答の changes[] から写す）を足す。拒否のときの changes は空（1 本目と同じ）。
    base_rev は受け取るだけ（修正前の版は盤面の state.inputs.review_rev が決める。start が固めた版）。
    BoardGap・止めた run の Reject は投げる（回す側の誤り。TA19）。
    commit が偽なら entry.take(…, commit=False)（乾いた照らし。盤面を書かない）の返りに changes: [] を足して返す（盤面を読み直さない）"""
    if not commit:
        return {**entry.take(board, FIX_NODE, reply, repo, commit=False), "changes": []}
    got = entry.take(board, FIX_NODE, reply, repo)
    if not got["ok"]:
        return {**got, "changes": []}
    b = entry.open_board(board, allow_halted=True)
    out, _ = _fix_output(b)
    return {**got, "changes": v1_changes(out["changes"])}


def _coverage(b) -> dict:
    """単位ごとの {before, after}（盤面の loop.coverage_after の今の周の行。before は修正前の版で数えた母数 total）"""
    cov = b.loop_state.get("coverage_after") or {}
    if cov.get("round") != b.round:
        return {}
    return {i["unit_key"]: {"before": i["total"], "after": i["after"]} for i in cov.get("items") or []}


def reads_role(tag: str = "") -> str:
    """読んだ証拠の役の名（reads.collect が reads-<役>.json に書く）。回の印が在れば fix.<印>（書く先は
    script_io.tagged("reads-fix.json", 印)。2 回目の修正の段が 1 回目の証拠を上書きしない）"""
    return f"{ROLE}.{tag}" if tag else ROLE


def collect(board: pathlib.Path, accepted: dict, changed: dict, tag: str = "") -> dict:
    """集める節の中身。1 本目の {ok, files, changes_file} を全部残し、fix_file（fix_reply が読んだ方のファイル: 盤面の
    state.outputs["p3.fix"]["file"] か 1 回目に受け付けた返答の控えの絶対パス）・not_done（件数）・coverage（単位ごとの {before, after}）・reads_file（fix-reads が今の周に書いた
    reads-fix.json。回の印 tag が在れば reads-fix.<tag>.json。無ければ空）を足す。受け付けた changes を今の周の changes.json（{"changes": [...]}。1 本目の形）に書く。
    受け付けが通っていない・assert-changed の出力が読めない・盤面が今の周の p3.fix を受けておらず控えも無い・changes が空（直す義務の
    単位が残らず、答え待ちの問いの出どころか直す裁定でない裁定（ask_human・fix_plan_item）で外れた単位が在る盤面 conflict.nothing_owed_but_excused を除く）ときは
    Unreadable（何も書かない）"""
    if not isinstance(accepted, dict) or accepted.get("ok") is not True:
        raise Unreadable(f"受け付けが通っていない（{(accepted or {}).get('reason') if isinstance(accepted, dict) else accepted!r}）")
    changes = accepted.get("changes")
    if not isinstance(changes, list):
        raise Unreadable("受け付けの出力に changes が無い")
    files = changed.get("files") if isinstance(changed, dict) else None
    if not isinstance(changed, dict) or changed.get("ok") is not True or not isinstance(files, list) \
            or not all(isinstance(f, str) for f in files):
        raise Unreadable(f"assert-changed の出力に files が無い（{changed!r}）")
    b = entry.open_board(board, allow_halted=True)
    if not changes and not conflict.nothing_owed_but_excused(b):
        raise Unreadable("受け付けの出力に changes が無い")
    out, fix_file = fix_reply(b)
    path = b.work(CHANGES_FILE)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps({"changes": changes}, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    os.replace(tmp, path)
    reads = b.work(f"reads-{reads_role(tag)}.json")
    return {"ok": True, "files": files, "changes_file": str(path), "fix_file": str(fix_file),
            "not_done": len(out.get("not_done") or []), "coverage": _coverage(b),
            "reads_file": str(reads) if reads.is_file() else ""}


def main_accept(fn=accept_fix, *, finish=None) -> int:
    """節 fix-accept のスクリプトの入口。script_io.main（INPUTS_REPLY・INPUTS_BASE_REV・ARTIFACTS_DIR）で fn を呼ぶ:
    中身の拒否（読めない返答を含む）は終了コード 0 の 1 行で、reason_file に理由の本文のパス（裁定 R44）。
    環境変数の欠けは script_io.main の 2。fn が投げた BoardGap・Reject（判定の前・止めた run など。TA19）と思わぬ誤りは、
    標準出力に何も出さずに標準エラーに 1 行で 2（rolekit.main_accept と同じ分け方）。finish は
    script_io.main に渡す"""
    import script_io
    try:
        return script_io.main(fn, finish=finish)
    except (BoardGap, Reject) as e:
        print(f"{FIX_NODE} の受け付けを回せない（{type(e).__name__}）: {' '.join(str(e).split())}", file=sys.stderr)
    except Exception as e:   # 思わぬ誤りも 1 行と 2（traceback を出さない）
        print(f"{FIX_NODE} の受け付けの内部の誤り: {type(e).__name__}: {' '.join(str(e).split())}", file=sys.stderr)
    return 2
