# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""修正役の返答の受け付け（blk-fix の節 fix-accept）。順は
-3. TDD の輪で凍ったテストのファイル（下の 1b）
-2. 書き込みの出どころ（check_writes。writes.check）: 版からの変更に、Edit・Write の書き込みの記録か返答の欄 bash_writes の申告が
   在るか。無ければ拒む。記録の無い run（包みが無い）は通し、受けた時に盤面の trace に 1 行。盤面に渡す返答からは bash_writes を外す
-1. 食い違いの申し出（欄 conflicts。INPUTS_PASS が first か ruled）: take_conflicts。名指しが現物に無ければ普通の拒否、在れば
   拒否に数えずその単位を止める。1 回目（first）で裁かれていない申し出が在れば盤面に渡さずに {ok: true, parked: true}
   （輪を抜け、裁定の輪 → 2 回目の修正役 fix-ruled が渡す）。盤面に渡す返答からは conflicts を外す（写しの schema に無い欄）
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
   空・欠けは輪の無い run で見ない）。裁定の後（ruled）は、裁定 fix_test_scope の範囲（conflict.ruled_test_limits）の中の変更を通す
1c. check_tests: 版からの変更に当たる試験を、TDD の輪と同じ実行器で機械が走らせ、元で赤でなかった試験の赤を拒む
   （tddloop.selected_problems。実行器の無い run は走らせない。一式の緑は線の最後のテストの段が確かめる）
2. recount.accept_fix: 盤面の done("p3.fix")。写しの fix_covers_open_units が判定役の class_query を修正前の版と修正後の
   作業ツリーで数え直す（仕様 3.2）。通れば 1 本目の出口のための changes（unit_key・files・what）を足す
loop_group の外の節は中の節の出力を引けず、輪の出力は最後の周の末端（この節）の出力なので、受け付けた changes を
ここで出口へ運ぶ（collect が今の周の changes.json に書く）。拒んだときの changes は空。
中身の拒否は終了コード 0 の {"ok": false, "reason", "reason_file", "changes": [], "done"} を 1 行。回す側の誤りは 2。
done は輪を抜ける旗（通った時か輪の 3 回目の拒否。R50: max_iterations に当てて run を落とさない）。諦めた輪の後は
assert-changed が盤面を止め、collect が ok: false の出口を出す
"""
import copy
import json
import sys
from pathlib import Path

sys.dont_write_bytecode = True   # 下の import が pack の中に __pycache__ を作らないように。必ず import より前
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))   # ブロックの模块（lib/ は Archon が探さない）
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / ".shared" / "core"))   # 頭に入れる（Ruling R7）
import os  # noqa: E402
import posixpath  # noqa: E402

import conflict  # noqa: E402   食い違いの申し出（.shared/core）
import leftovers  # noqa: E402   .archon/ の決まりと修正役の前の控え（.shared/core）
import recount  # noqa: E402
import tddloop  # noqa: E402
import entry  # noqa: E402
import writes  # noqa: E402   書き込みの出どころの突き合わせ（.shared/core）
from engine import pointers  # noqa: E402  （recount が import した board が写しの engine を sys.path に足す）
from engine.rules import validator_module  # noqa: E402

INPUTS = ("INPUTS_REPLY", "INPUTS_BASE_REV", "INPUTS_TDD_STATE", "INPUTS_ITERATION", "INPUTS_PASS")
GIVE_UP_AFTER = 3   # 輪 fix-loop の max_iterations と同じ（tests/test_blk_fix.py が YAML と突き合わせる）
TESTS_OP = "fix_tests_selected"   # 受け付けが選んだ試験を走らせた盤面の trace の行
DUPLICATE = "同じ unit_key を 2 行以上に分けた（直した単位ごとにちょうど 1 行。1 つの単位が複数のファイルに及ぶなら files に並べよ）: "
NOT_OPENED = ("今の周に直す単位に無い unit_key を changes に書いた（判定が defer にした単位・判定に無い単位は直さない。"
              "単位を切り直さず、貼られた単位の no か key で指せ。判定への異議は rejudge_requested に書く）: ")


CONFLICT_BAD = "食い違いの申し出を受けない（名指した所が現物に無いか、形が違う。直して丸ごと出し直せ）: "
SECOND_CONFLICT = ("裁定の後の出し直しで新しく申し出た食い違い——裁定の輪は 1 周に 1 回だけなので、機械が人に回した"
                   "（最後の人の関所で人が決める）")


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


def _reject(reason: str) -> dict:
    return {"ok": False, "reason": reason, "changes": []}


def take_conflicts(reply: dict, board: Path, repo: Path, pass_: str):
    """食い違いの申し出（欄 conflicts）を外した返答と、拒否の文か止めた印。返り (返答, 結果 | None)。結果が None なら受け付けを続ける。
    - 申し出が在れば機械が確かめる（conflict.problems: 形・今の直す義務の単位か・名指した所が現物に在るか）。外れれば普通の拒否
    - first: 通った申し出を盤面の控えに積み（拒否に数えない）、裁かれていない申し出が在れば（TDD の輪の分も）盤面に渡さずに
      {ok: true, parked: true, changes: []}（裁定の輪の後、2 回目の修正役が渡す）。返答は盤面の置き場に控える（PARKED_REPLY）
    - ruled: 裁定の後の新しい申し出は、裁定の輪がもう無いので機械が ask_human に裁いて積む。ask_human の単位を直した返答は拒む"""
    reply = dict(reply)
    items = reply.pop("conflicts", None) or []
    b = entry.open_board(board)
    V = validator_module(b)
    owed = {u["key"] for u in b.record["units"] if V.is_open(u)} - conflict.asked_keys(b)
    if items:
        bad = conflict.problems(items, repo=repo, board_dir=board, owed=owed)
        both = sorted({i.get("unit_key") for i in items if isinstance(i, dict)}
                      & {c.get("unit_key") for c in reply.get("changes") or [] if isinstance(c, dict)})
        if both:
            bad.append(f"申し出た単位を changes にも書いた: {both}（申し出た単位は直さない）")
        if bad:
            return reply, _reject(CONFLICT_BAD + " / ".join(bad))
        if pass_ == "first":
            conflict.park(b, items, source="fix")
        else:
            conflict.park(b, items, source="fix", ruling={"decision": conflict.ASK, "text": SECOND_CONFLICT, "limits": [],
                                                          "by": "works:fix-accept"})
            conflict.write_rulings(b)
    if pass_ == "first" and conflict.unruled(b):
        path = b.work(conflict.PARKED_REPLY)
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(json.dumps({**reply, "conflicts": items}, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        os.replace(tmp, path)
        return reply, {"ok": True, "parked": True, "reason": "", "changes": []}
    asked = sorted(conflict.asked_keys(b) & {c.get("unit_key") for c in reply.get("changes") or [] if isinstance(c, dict)})
    if asked:
        return reply, _reject(f"ask_human に裁いた単位を直した: {asked}（最後の人の関所で人が決める。changes から外し、作業ツリーの"
                              "その単位の直しを戻す）")
    return reply, None


def check_writes(reply: dict, board: Path, base_rev: str, repo: Path, state: str) -> dict:
    """書き込みの出どころ（writes.check。欄 bash_writes を外した返答は reply に）。盤面は書かない"""
    made = set(tddloop.suite_made(state))
    rev = writes.base_rev(entry.open_board(board), base_rev)
    return writes.check(reply, repo, [p for p in writes.changed(repo, rev) if p not in made], writes.sink(repo))


def check_tests(board: Path, base_rev: str, repo: Path, state: str) -> tuple:
    """版からの変更に当たる試験を機械が走らせた赤（tddloop.selected_problems）。返り (赤の文, 知らせ)。盤面は書かない"""
    return tddloop.selected_problems(state, repo, writes.base_rev(entry.open_board(board), base_rev))


def accept_fix(reply, board, base_rev, repo):
    state = os.environ.get("INPUTS_TDD_STATE", "")
    pass_ = os.environ.get("INPUTS_PASS") or "first"
    allowed = conflict.ruled_test_limits(entry.open_board(board)) if state and pass_ == "ruled" else []
    frozen = tddloop.frozen_problems(state, repo, allowed)
    if frozen:
        return _reject(" / ".join(frozen))
    wrote = check_writes(reply, board, base_rev, repo, state)
    if wrote["problems"]:
        return _reject(" / ".join(wrote["problems"]))
    reply = wrote["reply"]
    reply, done = take_conflicts(reply, board, repo, pass_)
    if done is not None:
        return done
    got = fix_unit_keys(reply, board)
    if got is not None:
        pack = check_pack_copy(reply, board, repo)
        if pack:
            return {"ok": False, "reason": pack, "changes": []}
        keys, opened = got
        for words, bad in ((DUPLICATE, check_unique_units(keys)), (NOT_OPENED, check_opened_units(keys, opened))):
            if bad:
                return {"ok": False, "reason": words + " / ".join(bad), "changes": []}
    red, note = check_tests(board, base_rev, repo, state)
    if red:
        return _reject(" / ".join(red))
    out = recount.accept_fix(reply, board, base_rev, repo)
    if out.get("ok") is True:   # 受けた時だけ盤面の trace に積む（拒否・回す側の誤りでは盤面を前のままにする）
        b = entry.open_board(board, allow_halted=True)
        writes.trace(b, recount.ROLE, wrote)
        b.trace(TESTS_OP, node=recount.ROLE, note=note)
    return out


def with_done(out: dict) -> dict:
    """輪を抜ける旗 done（R50）: 通った時か、この周の輪の 3 回目（fix-prep の iteration。INPUTS_ITERATION）の拒否。
    iteration が数でなければ ValueError（回す側の誤り。main_accept が 2 にする）"""
    it = int(os.environ["INPUTS_ITERATION"])
    return {**out, "done": out.get("ok") is True or it >= GIVE_UP_AFTER}


if __name__ == "__main__":
    sys.exit(recount.main_accept(accept_fix, finish=with_done))
