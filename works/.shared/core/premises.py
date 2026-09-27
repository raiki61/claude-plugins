"""前提の実測（graphloops の節 p0.premises）の受け付け。blk-premises の節の script が呼ぶ。Archon を知らない関数だけを出す。

- check_premises: 実測役の返答を受け付ける。作業ツリー → 型（graph の p0.premises の schema）→ graph の節が名指す
                  post_check（写した rules の measured_needs_output）。通れば盤面の premises.json に書く
- PREMISES_SNAPSHOT_FILE: 実測役を起こす前（依頼の型を確かめた時）の作業ツリーの写し。blk-premises の intake が置く

規則は写しから呼ぶだけで、ここに書き直さない（accept.py が POST_CHECKS を呼ぶのと同じ形）。規則に渡す入れ物は盤面の層の
DiskBoard.scratch（仕様 7 節の v1 の受け付けの入れ物。保存しない）。

TODO（線 A の配線）: ラインが盤面の層（DiskBoard）で run を持つようになったら、受け付けは b.done("p0.premises", 返答) に
替える。型・post_check・writes（record.process.constraints）・out/r1/p0.premises.json が engine と同じに付く。
ラインの節の表（<ライン>/nodes.json）の行は {"by": "role", "where": "blk-premises"}。それまでは v1 の受け付けと同じく、
盤面の直下に premises.json（受け付けた返答そのもの）を置く。
"""
import copy
import pathlib
import sys

sys.dont_write_bytecode = True   # 下で import する写しの engine の分（accept.py と同じ。この物自身の分は呼び手が止める）

CORE = pathlib.Path(__file__).resolve().parent
if str(CORE) not in sys.path:
    sys.path.insert(0, str(CORE))

from accept import SNAPSHOT_SCHEMA, _guard, _in_repo, _read_board, _rev, _write_board, snapshot_tree, tree_change  # noqa: E402
from board import DiskBoard  # noqa: E402
from engine.rules import registry  # noqa: E402
from engine.schema import validate_schema  # noqa: E402
from engine.util import Reject  # noqa: E402

PREMISES_NODE = "p0.premises"
PREMISES_FILE = "premises.json"                     # 受け付けた実測役の返答 {"constraints": [...]}
PREMISES_SNAPSHOT_FILE = "premises-snapshot.json"   # 実測役を起こす前の作業ツリー。形は accept.SNAPSHOT_FILE と同じ


def _tree_unchanged(repo, board, rev):
    """実測役が作業ツリーを変えていないか。実測役は測るために Bash を持つが、作業ツリーは変えない約束
    （後ろの判定のブロックはこの後の作業ツリーを写し、修正の差分は版からの差分で数える——ここで残った物は修正役の差分に混じる）。
    盤面に premises-snapshot.json が在ればそれと丸ごと（HEAD を含めて。commit で HEAD を動かしても見える）比べ、
    無ければ作業ツリーが綺麗で HEAD が数える版 rev のままであることを求める。バイトコードは数えない（snapshot_tree）。違えば Reject"""
    snap = _read_board(board, PREMISES_SNAPSHOT_FILE)
    if snap is None:
        now = snapshot_tree(repo)
        dirty = now["porcelain"].splitlines()
        if dirty:
            raise Reject("作業ツリーに変更が在る——実測役は作業ツリーを変えてはいけない。測るときに作った物を消してから出し直せ"
                         f"（git status --porcelain: {dirty[:5]}{' ほか' if len(dirty) > 5 else ''}）")
        if now["head"] != rev:
            raise Reject(f"HEAD が数える版から動いた（版 {rev[:12]} / 今 {now['head'][:12]}）——実測役は commit・reset・checkout で"
                         "履歴を動かしてはいけない")
        return
    errs = validate_schema(snap, SNAPSHOT_SCHEMA)
    if errs:
        raise Reject(f"盤面の {PREMISES_SNAPSHOT_FILE} の型が合わない（古い形なら intake から写しを取り直せ）: " + "; ".join(errs[:10]))
    changed = tree_change(snap, repo)
    if changed:
        raise Reject("依頼を受け付けた後から作業ツリーが変わった——実測役は作業ツリーを変えてはいけない。測るときに作った物"
                     "（出力のファイル・キャッシュ）は rm で消し、書き換えた追跡中のファイルは git restore -- <path> で戻してから"
                     f"出し直せ（出力は $TMPDIR に置く）（{changed}）")


def check_premises(reply: dict, board: pathlib.Path, base_rev: str, repo: pathlib.Path) -> dict:
    """実測役の返答を受け付ける。作業ツリーが変わっていれば拒む（_tree_unchanged）→ 型（graph の p0.premises の schema）→
    graph の節の post_check（measured_needs_output: kind=実測 は measured_output が要る）を写した rules から呼ぶ。
    base_rev は数える版として引けるかだけを見る（空はその場の HEAD。Ruling R2）。
    通れば盤面の premises.json に返答を書く。{"ok", "reason", "constraints_file"}"""
    def run():
        repo_p = pathlib.Path(repo)
        pathlib.Path(board).mkdir(parents=True, exist_ok=True)
        with _in_repo(repo_p):
            rev = _rev(repo_p, base_rev)
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
            path = _write_board(board, PREMISES_FILE, reply)
        return {"ok": True, "reason": note or "", "constraints_file": str(path)}
    return _guard(run, constraints_file="")
