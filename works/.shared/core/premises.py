"""前提の実測（graphloops の節 p0.premises）の受け付け。blk-premises の節の script が呼ぶ。Archon を知らない関数だけを出す。

- check_premises: 実測役の返答を受け付ける。作業ツリー → 型（graph の p0.premises の schema）→ graph の節が名指す
                  post_check（写した rules の measured_needs_output）。通れば盤面の premises.json に書く
- PREMISES_SNAPSHOT_FILE: 実測役を起こす前（依頼の型を確かめた時）の作業ツリーの姿（accept.tree_state。バイトコードは除く）。
                  blk-premises の intake が置く
- PREMISES_REQUEST_FILE: intake が型を確かめた依頼の行の控え（受け付けの check_claims と collect が読む）
- claims(items): 依頼の行のうち measured（依頼者が測ったと書いた値）を持つ物の {where, measured}
- collect(board): ブロックの出口（盤面の premises.json から。v1 の欄 constraints_file・constraints_summary に数を足した物）

規則は写しから呼ぶだけで、ここに書き直さない（accept.py が POST_CHECKS を呼ぶのと同じ形）。規則に渡す入れ物は盤面の層の
DiskBoard.scratch（仕様 7 節の v1 の受け付けの入れ物。保存しない）。

TODO（線 A の配線）: ラインが盤面の層（DiskBoard）で run を持つようになったら、受け付けは b.done("p0.premises", 返答) に
替える。型・post_check・writes（record.process.constraints）・out/r1/p0.premises.json が engine と同じに付く。
ラインの節の表（<ライン>/nodes.json）の行は {"by": "role", "where": "blk-premises"}。それまでは v1 の受け付けと同じく、
盤面の直下に premises.json（受け付けた返答そのもの）を置く。
"""
import copy
import json
import pathlib
import sys

sys.dont_write_bytecode = True   # 下で import する写しの engine の分（accept.py と同じ。この物自身の分は呼び手が止める）

CORE = pathlib.Path(__file__).resolve().parent
if str(CORE) not in sys.path:
    sys.path.insert(0, str(CORE))

from accept import (TREE_KEYS, TREE_SCHEMA, guard, in_repo, read_board, resolve_rev,  # noqa: E402
                    tree_moved, tree_state, type_errors, write_board)
from board import DiskBoard  # noqa: E402
import script_io  # noqa: E402
from engine.rules import registry  # noqa: E402
from engine.schema import validate_schema  # noqa: E402
from engine.util import Reject  # noqa: E402

PREMISES_NODE = "p0.premises"
PREMISES_FILE = "premises.json"                     # 受け付けた実測役の返答 {"constraints": [...]}
PREMISES_SNAPSHOT_FILE = "premises-snapshot.json"   # 実測役を起こす前の作業ツリーの姿。形は accept.TREE_SCHEMA（tree_state）
RULE = "実測役は作業ツリーを変えてはいけない"


def _tree_unchanged(repo, board, rev):
    """実測役が作業ツリーと履歴を変えていないか（Ruling R3・R14）。見張りは共通の口（accept.tree_state・tree_moved。R47）で、
    バイトコードは数えない（bytecode=False。測るために試験を走らせて出来る物。修正の差分の側と同じ定義）。
    盤面に premises-snapshot.json（intake の時の tree_state）が在れば今と比べる（HEAD・枝・git が無視するパスの増減も見る。
    役が作った物を commit しても head で見える）。古い形（head の無い写し）は型で拒み、intake から取り直させる。
    無ければ作業ツリーが綺麗（git status --porcelain と git が無視するパスが空）で、HEAD が数える版 rev のままであることを
    求める（判定役の見張りと同じ。dogfood run 21）。違えば Reject"""
    snap = read_board(script_io.scope_dir(board), PREMISES_SNAPSHOT_FILE)   # intake が今の include の置き場に置いた写し
    if snap is None:
        now = tree_state(repo, bytecode=False)
        dirty = now["porcelain"].splitlines() + [f"!! {n}" for n in now["ignored"]]
        if dirty:
            raise Reject(f"作業ツリーに変更が在る——{RULE}。測るときに作った物を消してから出し直せ"
                         f"（git status --porcelain --ignored: {dirty[:5]}{' ほか' if len(dirty) > 5 else ''}）")
        if now["head"] != rev:
            raise Reject(f"HEAD が数える版から動いた（版 {rev[:12]} / 今 {now['head'][:12]}）——{RULE}。commit・reset・checkout で"
                         "履歴を動かしてはいけない")
        return
    type_errors(snap, TREE_SCHEMA, f"盤面の {PREMISES_SNAPSHOT_FILE}（古い形なら intake から写しを取り直せ）")
    moved = tree_moved({k: snap[k] for k in TREE_KEYS}, repo, bytecode=False)
    if moved:
        raise Reject(f"依頼を受け付けた後から作業ツリーが変わった——{RULE}（HEAD・枝・git が無視するファイルも）。測るときに作った物"
                     "（出力のファイル・キャッシュ）は rm で消し、書き換えた追跡中のファイルは git restore -- <path> で戻してから"
                     f"出し直せ（出力は $TMPDIR に置く）（{'・'.join(moved)}）")
PREMISES_REQUEST_FILE = "premises-request.json"     # intake が型を確かめた依頼の行（JSON の配列）
NONE_SUMMARY = "（測る数値・事実の主張は依頼に無かった。制約 0 件）"


class Broken(Exception):
    """盤面の premises.json が無い・読めない・形が崩れている（collect は終了コード 1）"""


def claims(items: list) -> list:
    """依頼の行のうち measured（依頼者が測ったと書いた値）を持つ物の {where, measured}。実測役はこの where を text にそのまま入れて
    測り直す（blk-premises の check_claims が確かめる）"""
    return [{"where": it["where"], "measured": it["measured"]} for it in items or []
            if isinstance(it, dict) and isinstance(it.get("where"), str) and it.get("measured") not in (None, "")]


def request_items(board: pathlib.Path) -> list | None:
    """intake が控えた依頼の行（無い・読めないなら None）"""
    try:
        doc = json.loads((script_io.scope_dir(board) / PREMISES_REQUEST_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return doc if isinstance(doc, list) else None


def _covering(where: str, constraints: list) -> list:
    return [c for c in constraints if isinstance(c, dict) and isinstance(c.get("text"), str) and where in c["text"]]


def _one_line(text: str) -> str:
    return " ".join(str(text).split())


def collect(board: pathlib.Path) -> dict:
    """前提の実測のブロックの出口。盤面の premises.json（受け付けを通った返答）から
    {ok, premises_file, constraints_file, constraints_summary, constraints, measured, hypotheses, claims, claims_hypothesis, reads_file}。
    constraints・measured・hypotheses は制約の行・kind 実測・kind 仮説の数。claims は依頼の measured の行の数、claims_hypothesis は
    そのうち where を含む制約が仮説だけの数（測り直せなかった依頼の実測）。constraints_file は v1 の欄（premises_file と同じ）、
    constraints_summary は判定役に貼る 1 行 1 制約の要約（measured_output は載せない）。reads_file はまだ無い（空）。
    premises.json が無い・読めない・形が崩れていれば Broken"""
    path = pathlib.Path(board) / PREMISES_FILE
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise Broken(f"盤面の {PREMISES_FILE} が読めない（{path}: {type(e).__name__}: {e}）——受け付けを通った前提の実測が無い") from None
    cs = doc.get("constraints") if isinstance(doc, dict) else None
    if not isinstance(cs, list) or not all(isinstance(c, dict) and all(isinstance(c.get(k), str) for k in ("text", "measured_how", "kind"))
                                           for c in cs):
        raise Broken(f"盤面の {PREMISES_FILE} の形が崩れている（constraints[].text・measured_how・kind が要る）: {path}")
    asked = claims(request_items(board) or [])
    hyp = [c for c in asked if not any(x["kind"] == "実測" for x in _covering(c["where"], cs))]
    summary = "\n".join(f"- [{c['kind']}] {_one_line(c['text'])}（測り方: {_one_line(c['measured_how'])}）" for c in cs)
    return {"ok": True, "premises_file": str(path), "constraints_file": str(path), "constraints_summary": summary or NONE_SUMMARY,
            "constraints": len(cs), "measured": sum(c["kind"] == "実測" for c in cs),
            "hypotheses": sum(c["kind"] == "仮説" for c in cs), "claims": len(asked), "claims_hypothesis": len(hyp),
            "reads_file": ""}


def check_premises(reply: dict, board: pathlib.Path, base_rev: str, repo: pathlib.Path) -> dict:
    """実測役の返答を受け付ける。作業ツリーか HEAD が変わっていれば拒む（_tree_unchanged。共通の accept.tree_moved）→ 型（graph の p0.premises の schema）→
    graph の節の post_check（measured_needs_output: kind=実測 は measured_output が要る）を写した rules から呼ぶ。
    base_rev は数える版として引けるかだけを見る（空はその場の HEAD。Ruling R2）。
    通れば盤面の premises.json に返答を書く。{"ok", "reason", "constraints_file"}"""
    def run():
        repo_p = pathlib.Path(repo)
        pathlib.Path(board).mkdir(parents=True, exist_ok=True)
        with in_repo(repo_p):
            rev = resolve_rev(repo_p, base_rev)
            # 実測役は測るために Bash を持つが、作業ツリーは変えない約束（後ろの判定のブロックはこの後の作業ツリーを写し、
            # 修正の差分は版からの差分で数える——ここで残った物は修正役の差分に混じる）
            _tree_unchanged(repo_p, board, rev)
            b = DiskBoard.scratch(board, review_rev=rev)
            node = b.nodes[PREMISES_NODE]
            errs = validate_schema(reply, node["schema"])
            if errs:
                raise Reject("前提の実測の返答の型が合わない: " + "; ".join(errs[:10])
                             + (f"（ほか {len(errs) - 10} 件）" if len(errs) > 10 else ""))
            fn = registry(b.rules, "POST_CHECKS").get(node["post_check"])
            if fn is None:
                raise Reject(f"post_check '{node['post_check']}' が写しの rules に無い")
            note = fn(b, PREMISES_NODE, copy.deepcopy(reply), None)
            path = write_board(board, PREMISES_FILE, reply)
        return {"ok": True, "reason": note or "", "constraints_file": str(path)}
    return guard(run, constraints_file="")
