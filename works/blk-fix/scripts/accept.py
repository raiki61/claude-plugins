# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""修正役の返答の受け付け（blk-fix の節 fix-accept）。順は
0. 盤面が p3.fix を待っている（instance が待ち・起こした印が在る・依存が済んだ）ときだけ、返答の changes[].unit_key を盤面の
   控え（graph の pointers。mark_launched が固めた一覧）で名前に戻した列を作り、次の 2 つの works だけの検査に当てる。
   待っていない・番号を名前に戻せないときは検査せず 2 に進む（entry.take が回す側の誤り（2）か型・番号の文で拒む）
1. works だけの 2 つの検査（TA25 で .shared/core/accept.py には足さない。写しの fix_covers_open_units はどちらも見ない。
   1 本目は check_fix が fix_plan_covers_units に読み替えてどちらも拒んでいた。works は graphloops の上にこの拒否を残す）
   - check_unique_units: 同じ unit_key を 2 行に分けた返答を拒む
   - check_opened_units: 今の周に開いた単位（検証器の is_open）に無い unit_key を拒む（判定が defer にした単位・判定に
     無い key。1 本目の unknown = got - opened。fork の出どころは開いた単位なので通す）
1a. check_pack_copy: .archon/ の下（自分食いの run では動いている線の pack の写し）を申告した・変えた返答を拒む（run 26）
1b. TDD の輪で緑になった単位のテストのファイルを、輪の後の修正役が変えていないか（INPUTS_TDD_STATE。tddloop.frozen_problems。
   空・欠けは輪の無い run で見ない）
2. recount.accept_fix: 盤面の done("p3.fix")。写しの fix_covers_open_units が判定役の class_query を修正前の版と修正後の
   作業ツリーで数え直す（仕様 3.2）。通れば 1 本目の出口のための changes（unit_key・files・what）を足す
loop_group の外の節は中の節の出力を引けず、輪の出力は最後の周の末端（この節）の出力なので、受け付けた changes を
ここで出口へ運ぶ（collect が今の周の changes.json に書く）。拒んだときの changes は空。
中身の拒否は終了コード 0 の {"ok": false, "reason", "reason_file", "changes": [], "done"} を 1 行。回す側の誤りは 2。
done は輪を抜ける旗（通った時か輪の 3 回目の拒否。R50: max_iterations に当てて run を落とさない）。諦めた輪の後は
assert-changed が盤面を止め、collect が ok: false の出口を出す
"""
import copy
import sys
from pathlib import Path

sys.dont_write_bytecode = True   # 下の import が pack の中に __pycache__ を作らないように。必ず import より前
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))   # ブロックの模块（lib/ は Archon が探さない）
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / ".shared" / "core"))   # 頭に入れる（Ruling R7）
import os  # noqa: E402
import posixpath  # noqa: E402

import leftovers  # noqa: E402   .archon/ の決まりと修正役の前の控え（.shared/core）
import recount  # noqa: E402
import tddloop  # noqa: E402
import entry  # noqa: E402
from engine import pointers  # noqa: E402  （recount が import した board が写しの engine を sys.path に足す）
from engine.rules import validator_module  # noqa: E402

INPUTS = ("INPUTS_REPLY", "INPUTS_BASE_REV", "INPUTS_TDD_STATE", "INPUTS_ITERATION")
GIVE_UP_AFTER = 3   # 輪 fix-loop の max_iterations と同じ（tests/test_blk_fix.py が YAML と突き合わせる）
DUPLICATE = "同じ unit_key を 2 行以上に分けた（直した単位ごとにちょうど 1 行。1 つの単位が複数のファイルに及ぶなら files に並べよ）: "
NOT_OPENED = ("今の周に直す単位に無い unit_key を changes に書いた（判定が defer にした単位・判定に無い単位は直さない。"
              "単位を切り直さず、貼られた単位の no か key で指せ。判定への異議は rejudge_requested に書く）: ")


PACK_COPY = ("修正役は .archon/ の下を変えてはいけない（Archon の置き場で、自分食いの run では .archon/workflows/works/** が"
             "この run を動かしている線の pack の写し。直すのは元の works/** だけで、写しは次の run が作り直す）: ")


def check_pack_copy(reply: dict, board: Path, repo: Path) -> str:
    """.archon/ の下（leftovers.ARCHON_PREFIX）を changes[].files に申告した・修正役の前の控え（節 ignored-before）から
    .archon/ の下の中身が変わった返答を拒む文（通れば空）。控えが無いのは回す側の誤り（Unreadable → 2）"""
    declared = set()
    for c in reply.get("changes") or []:
        for f in (c.get("files") if isinstance(c, dict) else None) or []:
            if not isinstance(f, str) or not f.strip():
                continue
            f = f.strip()
            if os.path.isabs(f):
                f = os.path.relpath(f, repo)
            f = posixpath.normpath(f)
            if f == leftovers.ARCHON_PREFIX.rstrip("/") or f.startswith(leftovers.ARCHON_PREFIX):
                declared.add(f)
    changed = leftovers.archon_changes(board, repo)
    parts = []
    if declared:
        parts.append(f"changes[].files に申告した {sorted(declared)}（申告から外す）")
    if changed:
        parts.append(f"修正役の前の控え（節 ignored-before）から変わった {changed[:20]}（.archon/ の下は元の姿に戻してから"
                     "出し直す: 追跡している物は git checkout -- <パス>、足した物は消す）")
    return PACK_COPY + " / ".join(parts) if parts else ""


def fix_unit_keys(reply: dict, board: Path):
    """盤面が p3.fix を待っていれば (changes[].unit_key を名前に戻した列, 今の周に開いた単位の key の集合)。待っていない・
    changes の形が崩れている・番号を名前に戻せないときは None（検査せず entry.take に任せる）"""
    b = entry.open_board(board)
    inst = b.rd["instances"].get(recount.FIX_NODE)
    if not inst or inst["status"] != "pending" or not inst.get("launched_at") or not b.deps_met(recount.FIX_NODE):
        return None
    rows = reply.get("changes") if isinstance(reply, dict) else None
    if not isinstance(rows, list) or not all(isinstance(c, dict) for c in rows):
        return None
    out = {"changes": copy.deepcopy(rows)}
    if pointers.resolve(out, b.nodes[recount.FIX_NODE].get("pointers"), inst.get("pointers")):
        return None
    keys = [c.get("unit_key") for c in out["changes"]]
    if not all(isinstance(k, str) for k in keys):
        return None
    V = validator_module(b)
    return keys, {u["key"] for u in b.record["units"] if V.is_open(u)}


def check_unique_units(keys: list) -> list:
    """2 度以上現れる unit_key（現れた順）"""
    seen, dup = set(), []
    for k in keys:
        if k in seen and k not in dup:
            dup.append(k)
        seen.add(k)
    return dup


def check_opened_units(keys: list, opened: set) -> list:
    """今の周に開いた単位に無い unit_key（現れた順・重なりは 1 つ）"""
    return list(dict.fromkeys(k for k in keys if k not in opened))


def accept_fix(reply, board, base_rev, repo):
    frozen = tddloop.frozen_problems(os.environ.get("INPUTS_TDD_STATE", ""), repo)
    if frozen:
        return {"ok": False, "reason": " / ".join(frozen), "changes": []}
    got = fix_unit_keys(reply, board)
    if got is not None:
        pack = check_pack_copy(reply, board, repo)
        if pack:
            return {"ok": False, "reason": pack, "changes": []}
        keys, opened = got
        for words, bad in ((DUPLICATE, check_unique_units(keys)), (NOT_OPENED, check_opened_units(keys, opened))):
            if bad:
                return {"ok": False, "reason": words + " / ".join(bad), "changes": []}
    return recount.accept_fix(reply, board, base_rev, repo)


def with_done(out: dict) -> dict:
    """輪を抜ける旗 done（R50）: 通った時か、この周の輪の 3 回目（fix-prep の iteration。INPUTS_ITERATION）の拒否。
    iteration が数でなければ ValueError（回す側の誤り。main_accept が 2 にする）"""
    it = int(os.environ["INPUTS_ITERATION"])
    return {**out, "done": out.get("ok") is True or it >= GIVE_UP_AFTER}


if __name__ == "__main__":
    sys.exit(recount.main_accept(accept_fix, finish=with_done))
