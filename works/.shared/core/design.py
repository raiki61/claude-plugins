"""修正の前に作る独立設計（写しの graph の節 r2.design）の先行。役を起こす支度・受け付け・控え・盤面への渡しを 1 か所に置く。
Archon を知らない関数だけを出す。

写しの graph の r2.design は deps に p4.assemble を持つので、盤面では修正と最後のテストの後にしか待たない。周を重ねない線では、
そこで出た作り直しの要否（R2 の redesign-needed）を拾う周が無い。graph は写しのまま（graph_sha を固めた手本と実物の盤面が
それに乗る）にして、設計の役だけを修正の前に先に起こし、受け付けた返答を盤面の根の design.json に控える。盤面が r2.design を
待った時（p4.assemble の後）に、線がその控えを渡す（目的の文の purpose.json と同じ形）。設計の役の入力は目的の文と実測した
制約・人の方針だけなので、先に起こしても独立は崩れない（修正案・差分を読む口が無い）。

- unusable(b):   目的の出典が R2 に使えない理由（目的不明・狭めている。無ければ None）。式は写しの rules の purpose_unusable
                 （p4.assemble と同じ 1 本）を呼ぶ
- due(b):        設計の役を今起こすか（表に役として在り・控えが無く・諦めていず・盤面で済んでいず・再発火の周で・目的が使える）と理由
- snap:          起こす前の作業ツリーの写し（今の周の design-snapshot.json）。起こさないなら写しを置かずに go: false
- prep:          r2.design の指示書を engine と同じ描き方で描き（節はまだ待っていない。rolekit.render_body の ahead）、役の定義を
                 頭に置く。前の拒否の文は頭に貼る（役は道具を持たないのでファイルを読めない）
- accept:        返答を型（写しの schema）と作業ツリーの比べに通し、通れば design.json。拒否は盤面の根の控えに積み、
                 GIVE_UP_AFTER 回目で done（輪を抜ける。諦めても線は止めない——事前審査は設計なしで進み、最後の R2 が言う）
- read_design:   design.json（無ければ None。壊れていれば Reject）。made は (中身 か None, 壊れている理由) で拒まない
- missing(b):    設計が無い理由の 1 文（諦めた・目的が使えない・控えが無い）。事前審査の指示書と独立の目の出口が使う
- hand(b, …):    盤面が r2.design を待っていて控えが在れば渡す（渡しの手順は line_edge と同じ entry.hand の 1 か所）
"""
import pathlib
import sys

sys.dont_write_bytecode = True   # 下の import が pack の中に __pycache__ を作らないように（必ず import より前）

_CORE = pathlib.Path(__file__).resolve().parent
if str(_CORE) not in sys.path:
    sys.path.insert(0, str(_CORE))

from board import BoardGap, pending_instance  # noqa: E402  （board が写しの engine を sys.path に足す。engine より先に）
from engine.util import Reject, safe_name  # noqa: E402
import accept  # noqa: E402
import entry  # noqa: E402
import rolekit  # noqa: E402

NODE = "r2.design"
DESIGN_FILE = "design.json"             # 受け付けた設計の返答（盤面の根。run に 1 つ）
SNAPSHOT_NAME = "design-snapshot.json"  # 役を起こす前の作業ツリー（今の周の作業ファイル）
PROMPT_NAME = f"prompt-{safe_name(NODE)}.md"
GIVE_UP_AFTER = rolekit.GIVE_UP_AFTER
MISSING = "独立設計が取れなかった"
REJECT_HEADING = rolekit.REJECT_HEADING
UNUSABLE = {"目的不明": "目的の出典が取れない（目的不明）——独立設計を回さない",
            "狭めている": "目的の文を監査が『狭めている』と判定した——狭められた目的で独立設計を回さない"}
HANDED_OP = "r2_design_handed"          # 控えを盤面へ渡した trace の行
MISSING_OP = "r2_design_missing"        # 設計が無いまま先へ進んだ trace の行


def unusable(b):
    """目的の出典が R2 に使えない理由（None／目的不明／狭めている）。写しの p4.assemble が loop.purpose_unusable に置くのと同じ
    1 本（写しの rules の purpose_unusable）を、p4.assemble より前に呼ぶ"""
    return b.rules.purpose_unusable(b)


def read_design(board_dir):
    """盤面の根の design.json（無ければ None）。読めない・型に合わなければ Reject"""
    obj = accept.read_board(board_dir, DESIGN_FILE)
    if obj is not None:
        accept.type_errors(obj, accept.role_schema(NODE), f"盤面の {DESIGN_FILE} ")
    return obj


def made(board_dir) -> tuple:
    """(控えの中身 か None, 控えが壊れている時の理由)"""
    try:
        return read_design(board_dir), ""
    except Reject as e:
        return None, f"{MISSING}: {e}"


def due(b) -> tuple:
    """(起こすか, 理由)"""
    row = b.table.nodes.get(NODE) if b.table is not None else None
    if row is None or row.by != "role":
        return False, f"節の表に {NODE} の役が無い"
    got, broken = made(b.dir)
    if got is not None or broken:
        return False, broken or f"独立設計はもう {DESIGN_FILE} に在る"   # 壊れた控えも作り直さない（設計を 2 度作らない）
    gave = rolekit.given_up_reason(b.dir, NODE, give_up_after=GIVE_UP_AFTER)
    if gave:
        return False, gave
    st = b.node_state(NODE)
    if st != "pending":   # 済んだ・条件外（na）・省いた。まだ依存を待つ節も pending
        return False, f"盤面で {NODE} はこの周に {st}"
    if b.loop_state.get("r2_refire", True) is not True:
        return False, "R2 の再発火条件に当たらない"
    why = unusable(b)
    if why:
        return False, UNUSABLE[why]
    return True, f"{NODE} をこの周の修正の前に作る"


def snap(board_dir, repo) -> dict:
    """{ok, go, snapshot_file}。起こすなら作業ツリーの写しを置く"""
    b = entry.open_board(pathlib.Path(board_dir))
    go, _ = due(b)
    if not go:
        return {"ok": True, "go": False, "snapshot_file": ""}
    return {"ok": True, "go": True, "snapshot_file": str(entry.snapshot(pathlib.Path(board_dir), SNAPSHOT_NAME, pathlib.Path(repo)))}


def _rejects(board_dir) -> list:
    rows = accept.read_board(board_dir, rolekit.rejects_path(board_dir, NODE).name) or []
    return [r for r in rows if isinstance(r, dict)]


def prep(board_dir, repo) -> dict:
    """返り {prompt, prompt_file, node, attempt, already, role_def, role_def_missing}。起こさない盤面は BoardGap（snap が go の時だけ）"""
    b = entry.open_board(pathlib.Path(board_dir))
    go, why = due(b)
    if not go:
        raise BoardGap(f"{NODE} を今は起こさない（{why}）——snap が go の時だけ支度する")
    body, _ = rolekit.render_body(b, NODE, ahead=True)
    prompt, def_file, missing = rolekit.with_role_definition(b, NODE, body)
    rows = _rejects(board_dir)
    if rows:   # 役は道具を持たないので、理由のファイルでなく文を貼る
        prompt = rolekit.with_reject(prompt, rows[-1].get("reason", ""))
    p = b.work(PROMPT_NAME)
    p.write_text(prompt, encoding="utf-8")
    return {"prompt": prompt, "prompt_file": str(p), "node": NODE, "attempt": len(rows) + 1, "already": False,
            "role_def": def_file, "role_def_missing": missing}


def check_design(reply, board_dir, repo) -> dict:
    """型（写しの r2.design の schema）→ 作業ツリー（役を起こす前の写しと同じ）。通れば design.json。{ok, reason, design_file}"""
    def run():
        b = entry.open_board(pathlib.Path(board_dir))
        moved = entry.tree_moved_since(b, SNAPSHOT_NAME, pathlib.Path(repo))
        if moved:
            raise Reject(entry.READONLY_MOVED + moved)
        accept.type_errors(reply, accept.role_schema(NODE), "独立設計の返答")
        return {"ok": True, "reason": "", "design_file": str(accept.write_board(board_dir, DESIGN_FILE, reply))}
    return accept.guard(run, design_file="")


def accept_reply(board_dir, raw, repo) -> dict:
    """返り {ok, done, give_up, skipped, reason, node}。拒否は盤面の根の控えに積み、GIVE_UP_AFTER 回目で done・give_up"""
    reply, why = rolekit.parse_reply(raw)
    got = {"ok": False, "reason": why} if reply is None else check_design(reply, board_dir, repo)
    out = rolekit.with_done(pathlib.Path(board_dir), NODE, {"ok": got["ok"], "reason": got.get("reason", "")},
                            give_up_after=GIVE_UP_AFTER)
    return {"ok": out["ok"], "done": out["done"], "give_up": bool(out["done"] and not out["ok"]), "skipped": False,
            "reason": out["reason"], "node": NODE}


def missing(b) -> str:
    """設計が無い理由の 1 文（控えが在れば空）"""
    got, broken = made(b.dir)
    if got is not None or broken:
        return broken
    gave = rolekit.given_up_reason(b.dir, NODE, give_up_after=GIVE_UP_AFTER)
    if gave:
        return f"{MISSING}: {gave}"
    why = unusable(b)
    if why:
        return UNUSABLE[why]
    return f"{MISSING}: 修正の前に設計の役を起こしていない（{DESIGN_FILE} が無い）"


def hand(b, board_dir, repo) -> dict:
    """盤面が r2.design を待っていて控えが在れば渡す。返り {handed, reason}。渡さない時は handed: False と理由（止めない——
    設計が無いことは独立の目の出口が言う）"""
    if b.state.get("halted") or b.state.get("stop"):
        return {"handed": False, "reason": "盤面は止まっている（周を締めた・止めた）"}
    if pending_instance(b, NODE) is None:
        return {"handed": False, "reason": f"{NODE} は盤面で待っていない（{b.node_state(NODE)}）"}
    reply, _ = made(board_dir)
    if reply is None:   # 控えが無い・壊れている（受け付けの後に書き換わった）: 渡さず、目の層に理由を残す
        why = missing(b)
        b.trace(MISSING_OP, reason=why)
        return {"handed": False, "reason": why}
    got = entry.hand(b, pathlib.Path(board_dir), NODE, reply, pathlib.Path(repo))
    if not got["ok"]:
        why = f"{MISSING}: 盤面が {DESIGN_FILE} を受けない（{got['reason']}）"
        entry.open_board(pathlib.Path(board_dir)).trace(MISSING_OP, reason=why)
        return {"handed": False, "reason": why}
    entry.open_board(pathlib.Path(board_dir)).trace(HANDED_OP, file=DESIGN_FILE)
    return {"handed": True, "reason": ""}
