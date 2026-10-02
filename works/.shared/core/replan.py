"""同じ run の中の案の直し（依頼 226）。裁定 fix_plan_item の単位は次の run へ持ち越さず、同じ run の中で案に戻す。
直しを終えられなかった単位の道は 1 本だけ: 待つ行（conflict の状態 WAITING）を諦めた行（GAVE_UP）にし、ask_human の道
（conflict.asked・human_lines。最後の関所と次の run の依頼に裁定の文を字のまま載せる）に合流させる。

- STOP_BY: この模块が盤面を止める時の by
- CLOSE_WHY・HALTED_WHY: 諦めた理由（conflict.REPLAN_WHY に置く。HALTED_WHY は止まった盤面で締める時で、by・reason は盤面の止めの物）
- UNSETTLED: 締めた後に待つ行が残った時の BoardGap の文
- close(b, why): 待つ行の全部を諦めた行にし、id を返す（待つ行が無ければ何もせず []）
- close_at(board_dir): 盤面を allow_halted で開き、止まっていれば HALTED_WHY、そうでなければ CLOSE_WHY で close。何度呼んでも
  同じ（2 度目は待つ行が無い）。報告の組み立ては必ず走るので、修正の段が落ちて h-rejudge が飛ばされた run でも待つ行が落ちない
- HAND_REFUSED: 1 回目に受け付けた返答の控えを盤面が受けない時の止めの文
- hand_held(board_dir, repo): 盤面が止まっておらず、今の周の p3.fix を受けておらず、1 回目に受け付けた返答の控え
  （conflict.held_reply。待つ単位が在る間に修正の受け付けが盤面に渡さずに置いた物）が在れば、bash_writes を外した控えを
  recount.accept_fix で盤面に渡して真。盤面が受けなければ盤面を止めて（HAND_REFUSED・by STOP_BY）偽。渡す物が無ければ偽
- settle(board_dir, repo): h-rejudge の頭で呼ぶ。1. close_at。2. hand_held。3. 待つ行が残れば BoardGap(UNSETTLED)。
  返り {"closed": [id…], "handed": hand_held の返り}

案の直しの役（blk-plan を replan の入力つきで 2 度目に include した口。blk-plan の lib が入力 replan を見てここへ回す）:
- TRIP_FILE: 今の周の作業ファイル {"round", "items": [行]}。行は TRIP_KEYS（item・units・rows（待つ行の id）・old（承認済みの
  項目）・brief・new（関所の決め手の欄を外した直した項目）・new_marks（外した欄）・review・contract_changed・human_faces・ask・
  answer・result・why）。まだ無い値は null
- PLAN_NODE・REVIEW_NODE・ROLES: 盤面に無い節の名（拒否の控え rejects-<名>.json と指示書 prompt-<名>.md の名。1 回目の
  p2.fix_plan・p2.plan_review の控えと重ならない）
- material(b): 待つ行を裁定の欄 plan_items の番号ごとに束ねて TRIP_FILE を書く（在れば書き直さない＝再開）。{"go", "items"}
- snap・prep・accept_reply・collect: 修正案の役（plan）と事前審査の役（plan-review）の支度・受け付け・出口。修正案の役には誤りと
  裁かれた項目・申し出・裁定の文だけを渡し（REPLAN_ASK）、返答は渡した項目に限る（数・unit_keys の字・works の欄・狭めない案・
  型の誤りを全部並べて 1 回で拒む。REPLAN_REJECT）。受け入れのテストが既に在るかは修正の起点の版（盤面の review_rev）の木で
  引く。事前審査の役には呼び手が組んだ独立設計の節と、前後の項目だけを渡す（REVIEW_ASK_REPLAN）。どちらも読むだけの役で、
  起こす前の作業ツリーの写しと比べて変わっていれば拒む。拒否は rolekit.with_done の控えに積み、GIVE_UP_AFTER 回目で done
  （諦めは盤面を止めない。後の関所が項目ごとに読む）
- new_item(row): TRIP_FILE の行の直した項目に、外した決め手の欄を narrows の行ごとに戻した形

層 L3。entry・conflict・recount・planmarks・gatemarks・accept・rolekit・leftovers を読み、report と blk の lib は import しない
（report がこの模块を呼ぶ向きだけ。blk-plan の lib がこの模块を呼ぶ向きだけ）。期限・回数の上限は持たない（諦めの数は rolekit の物）。
"""
from __future__ import annotations

import copy
import json
import os
import pathlib
import posixpath
import sys

sys.dont_write_bytecode = True

_CORE = pathlib.Path(__file__).resolve().parent
if str(_CORE) not in sys.path:
    sys.path.insert(0, str(_CORE))

from board import BoardGap  # noqa: E402  （board が写しの engine を sys.path に足す。engine より先に）
from engine.schema import validate_schema  # noqa: E402
from engine.util import Reject, safe_name  # noqa: E402
import accept  # noqa: E402
import conflict  # noqa: E402
import entry  # noqa: E402
import gatemarks  # noqa: E402
import leftovers  # noqa: E402
import planmarks  # noqa: E402
import recount  # noqa: E402
import rolekit  # noqa: E402
import writes  # noqa: E402

STOP_BY = "works:replan"
CLOSE_WHY = "同じ run の中で案の直しを終えられなかった（案の段に戻るのは 1 run に 1 回）"
HALTED_WHY = "run が止まった（{by}: {reason}）ので、案の直しを終えなかった"
UNSETTLED = "案の直しを待つ単位を残したまま修正の段を抜けようとした: {ids}"
HAND_REFUSED = "1 回目に受け付けた修正の返答を盤面が受けない: {reason}"
_ENDED_BY = "stop_after_round"   # 1 周の run が周を締めた盤面の halted.by（普通の終わりで、止めたと読まない）

TRIP_FILE = "replan.json"          # 今の周の作業ファイル {"round": n, "items": [行]}
TRIP_KEYS = ("item", "units", "rows", "old", "brief", "new", "new_marks", "review", "contract_changed", "human_faces", "ask",
             "answer", "result", "why")
PLAN_NODE = "replan.fix_plan"      # 盤面に無い節の名（拒否の控えと指示書の名。1 回目の p2.fix_plan と重ならない）
REVIEW_NODE = "replan.plan_review"
ROLES = {"plan": PLAN_NODE, "plan-review": REVIEW_NODE}
REVIEW_GRAPH_NODE = "p2.plan_review"   # 事前審査の返答の型を引く写しの graph の節（修正案は planmarks.NODE）
BRIEF_NAME = "brief-{n}.md"        # 項目の brief の名（blk の lib の planbrief.NAME と同じ。tests/test_replan.py が突き合わせる）
READS_INDEX = "reads-replan-block.json"   # 案の直しの役の読んだ証拠の索引（1 回目の reads-plan-block.json を上書きしない）
READS_PREFIX = "replan-"           # 読んだ証拠の役の名の頭（reads-replan-<役>.json）
REPLAN_ASK = ("承認済みの修正案の項目のうち、下に貼った項目だけを直せ。修正の段で修正役がこの項目の誤りを申し出て、裁定役が"
              "fix_plan_item（案の項目そのものの誤り）と裁いた。申し出の文と裁定の文を読み、裁定の文が名指した所を直した項目を"
              "返せ。plan は下に貼った項目と同じ数・同じ順で、各項目の unit_keys は貼った文字列を一字も変えずに写せ（番号で書かない）。"
              "ほかの項目は返すな。直した項目は事前審査に掛かり、約束の欄（unit_keys・narrows・removes・allowed_paths・out_of_scope・"
              "rewrite_tests・tests の behavior）を変えた時は人の関所に出る。")
REVIEW_ASK_REPLAN = ("下は承認済みの修正案の項目の前の形と、修正の段の申し出と裁定を受けて修正案の役が直した形。直した形が裁定の文の"
                     "指摘を直したか、新しい後退（regression）や方針とのぶつかり（policy）を作らないかを見よ。前の形に在った穴を"
                     "挙げ直さない。穴は faces に挙げよ。")
REPLAN_REJECT = "直した項目の返答に誤りが在る（下の行を全部直して出し直せ）:"
REVIEW_REJECT = "事前審査の返答の型が合わない（下の行を全部直して出し直せ）:"
ITEM_HEAD = "## 直す項目 {n}（承認済みの修正案の項目の番号）"
OLD_HEAD = "### 前の項目（承認済み。機械が貼った）"
NEW_HEAD = "### 直した項目（修正案の役が返した形。機械が貼った）"
ROW_HEAD = "### 修正の段の申し出と裁定（{id}）"
MAX_TYPE_ERRORS = 10   # 型の外れを並べる行の数（accept の型の拒否と同じ数。残りは件数）


def close(b, why: str) -> list[str]:
    """待つ行（conflict.waiting）の全部を諦めた行（GAVE_UP・理由 why）にし、その id を返す。待つ行が無ければ何もせず []"""
    ids = [r["id"] for r in conflict.waiting(b)]
    if ids:
        conflict.set_replan(b, ids, conflict.GAVE_UP, why=why)
    return ids


def _stop_of(b) -> dict | None:
    """盤面の止め（state.stop か、周の締めでない state.halted）。止まっていなければ None"""
    st = b.state
    if st.get("stop"):
        return st["stop"]
    halted = st.get("halted") or {}
    return halted if halted and halted.get("by") != _ENDED_BY else None


def close_at(board_dir) -> list[str]:
    """盤面を allow_halted で開き、止まっていれば HALTED_WHY（盤面の止めの by・reason）、そうでなければ CLOSE_WHY で close"""
    b = entry.open_board(pathlib.Path(board_dir), allow_halted=True)
    stop = _stop_of(b)
    why = HALTED_WHY.format(by=stop.get("by") or "", reason=stop.get("reason") or "") if stop else CLOSE_WHY
    return close(b, why)


def hand_held(board_dir, repo) -> bool:
    """1 回目に受け付けた返答の控えを盤面に渡す。盤面が止まっている・今の周の p3.fix を受けた（held_reply が None）・控えが
    無いなら何もせず偽。渡して盤面が受ければ真、受けなければ盤面を止めて（by STOP_BY）偽。何度呼んでも渡すのは 1 度"""
    board_dir = pathlib.Path(board_dir)
    b = entry.open_board(board_dir, allow_halted=True)
    if b.state.get("stop") or b.state.get("halted"):   # 周の締めの halted も（盤面はもう返答を受けない）
        return False
    held, _ = conflict.held_reply(b)
    if held is None:
        return False
    reply = {k: v for k, v in held.items() if k != writes.FIELD}
    out = recount.accept_fix(reply, board_dir, "", pathlib.Path(repo))
    if out.get("ok") is True:
        return True
    reason = " ".join(str(out.get("reason") or "").split())
    entry.open_board(board_dir, allow_halted=True).stop(HAND_REFUSED.format(reason=reason), by=STOP_BY)
    return False


def settle(board_dir, repo) -> dict:
    """h-rejudge の頭（修正の段を抜ける所）の締め。待つ行を諦めた行にし、1 回目に受け付けた返答の控えを盤面に渡し
    （hand_held）、それでも待つ行が残れば BoardGap（UNSETTLED）"""
    closed = close_at(board_dir)
    handed = hand_held(board_dir, repo)
    left = conflict.waiting(entry.open_board(pathlib.Path(board_dir), allow_halted=True))
    if left:
        raise BoardGap(UNSETTLED.format(ids="、".join(r["id"] for r in left)))
    return {"closed": closed, "handed": handed}


# ---------------------------------------------------------------- 案の直しの役（blk-plan の replan の口）
def node_of(role: str) -> str:
    """役（plan・plan-review）の盤面に無い節の名。知らない役は BoardGap"""
    if role not in ROLES:
        raise BoardGap(f"役 {role!r} は案の直しの役（{' / '.join(ROLES)}）でない")
    return ROLES[role]


def _snapshot_name(role: str) -> str:
    return f"replan-{role}-snapshot.json"


def read_trip(b) -> dict | None:
    """今の周の TRIP_FILE（無ければ None）。読めない・形が違えば BoardGap"""
    p = b.work(TRIP_FILE)
    try:
        doc = json.loads(p.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, ValueError) as e:
        raise BoardGap(f"案の直しの控え {p} が読めない: {e}") from None
    rows = doc.get("items") if isinstance(doc, dict) else None
    if not isinstance(rows, list) or not all(isinstance(r, dict) and isinstance(r.get("item"), int) and isinstance(r.get("old"), dict)
                                             for r in rows):
        raise BoardGap(f"案の直しの控え {p} の形が違う（{{round, items: [{{item, old, …}}]}}）")
    return doc


def _write_trip(b, doc: dict) -> None:
    p = b.work(TRIP_FILE)
    tmp = p.with_name(p.name + ".tmp")
    tmp.write_text(json.dumps(doc, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    os.replace(tmp, p)


def _closed(b) -> bool:
    """盤面が止まっている（周の締めも）か、今の周の p3.fix を受けた（案の直しの役を起こさない）"""
    if b.state.get("stop") or b.state.get("halted"):
        return True
    took = ((b.state.get("outputs") or {}).get(conflict.FIX_NODE) or {})
    return took.get("round") == b.round


def material(b) -> dict:
    """待つ行（conflict.waiting）を裁定の欄 plan_items の番号ごとに束ねて TRIP_FILE を書く（項目 1 つに行 1 つ。単位は束ねた行の
    ruled_units の和。old は承認済みの項目から鍵 item を外した物）。TRIP_FILE が今の周に在れば書き直さない（再開）。
    盤面が止まっている・今の周の p3.fix を受けた・束ねる行が無いなら go False。返り {"go", "items": [番号…]}"""
    if _closed(b):
        return {"go": False, "items": []}
    doc = read_trip(b)
    if doc is None:
        by_item: dict[int, list] = {}
        for r in conflict.waiting(b):
            for n in (r.get("ruling") or {}).get(conflict.PLAN_ITEMS) or []:
                by_item.setdefault(n, []).append(r)
        if not by_item:
            return {"go": False, "items": []}
        current = planmarks.approved_items(b)
        if current is None:
            raise BoardGap(f"案の直しを待つ行が在るのに、周 {b.round} の承認済みの修正案か凍結した欄の控えが無い")
        items = []
        for n in sorted(by_item):
            if not isinstance(n, int) or isinstance(n, bool) or not 1 <= n <= len(current):
                raise BoardGap(f"裁定の欄 {conflict.PLAN_ITEMS} の項目 {n!r} が承認済みの修正案（{len(current)} 項目）の外")
            rows = by_item[n]
            brief = b.work(BRIEF_NAME.format(n=n))
            items.append({**dict.fromkeys(TRIP_KEYS), "item": n,
                          "units": list(dict.fromkeys(k for r in rows for k in conflict.ruled_units(r))),
                          "rows": [r["id"] for r in rows],
                          "old": {k: v for k, v in current[n - 1].items() if k != "item"},
                          "brief": str(brief) if brief.is_file() else ""})
        doc = {"round": b.round, "items": items}
        _write_trip(b, doc)
    return {"go": bool(doc["items"]), "items": [it["item"] for it in doc["items"]]}


def _handed(doc: dict | None, role: str) -> list:
    """役に渡す項目の行（doc の行そのもの）: plan は new の無い行、plan-review は new が在り review の無い行"""
    rows = (doc or {}).get("items") or []
    if role == "plan":
        return [r for r in rows if r.get("new") is None]
    return [r for r in rows if r.get("new") is not None and r.get("review") is None]


def snap(board_dir, role: str, repo) -> dict:
    """{ok, go, snapshot_file}。plan は material を通し new の無い項目が在れば go、plan-review は new が在り review の無い項目が
    在れば go。go なら起こす前の作業ツリーの写しを置く（支度が起こす直前に置き直す）"""
    node_of(role)
    board_dir = pathlib.Path(board_dir)
    b = entry.open_board(board_dir, allow_halted=True)
    if role == "plan":
        go = material(b)["go"] and bool(_handed(read_trip(b), role))
    else:
        go = not _closed(b) and bool(_handed(read_trip(b), role))
    if not go:
        return {"ok": True, "go": False, "snapshot_file": ""}
    return {"ok": True, "go": True, "snapshot_file": str(entry.snapshot(board_dir, _snapshot_name(role), pathlib.Path(repo)))}


def _rejects(board_dir, node: str) -> list:
    rows = accept.read_board(board_dir, rolekit.rejects_path(pathlib.Path(board_dir), node).name) or []
    return [r for r in rows if isinstance(r, dict)] if isinstance(rows, list) else []


def new_item(row: dict) -> dict:
    """TRIP_FILE の行の直した項目（new）に、外した決め手の欄（new_marks）を narrows の行ごとに戻した形"""
    out = copy.deepcopy(row.get("new") or {})
    for narrow, marks in zip(out.get("narrows") or [], row.get("new_marks") or []):
        if isinstance(narrow, dict) and isinstance(marks, dict):
            narrow.update(copy.deepcopy(marks))
    return out


def _json_block(doc) -> list:
    return ["```json", json.dumps(doc, ensure_ascii=False, indent=1), "```"]


def _section(row: dict, conflicts: dict, role: str) -> str:
    """項目ごとの節: 番号・unit_keys（字のまま）・前の項目・brief のパス・申し出の行・裁定の文（字のまま）・事前審査なら直した項目"""
    old = row["old"]
    lines = [ITEM_HEAD.format(n=row["item"]), "",
             f"- unit_keys（この字のまま写せ）: {json.dumps(old.get('unit_keys'), ensure_ascii=False)}",
             f"- この項目の brief: {row.get('brief') or '（無い）'}", "", OLD_HEAD, "", *_json_block(old)]
    for rid in row.get("rows") or []:
        c = conflicts.get(rid)
        if c is None:
            raise BoardGap(f"案の直しの控え {TRIP_FILE} の行 {rid} が食い違いの控えに無い")
        ru = c.get("ruling") or {}
        lines += ["", ROW_HEAD.format(id=rid), "",
                  f"- 申し出の単位: {c.get('unit_key')}",
                  f"- 申し出の名指し（between）: {', '.join(c.get('between') or [])}",
                  f"- 申し出の理由（why_both_cannot_hold）: {c.get('why_both_cannot_hold')}",
                  f"- 申し出の種類（kind）: {c.get(conflict.KIND_FIELD) or '（無し）'}",
                  f"- 正しいと見た側（which_is_right）: {c.get('which_is_right')}",
                  f"- 裁定（{ru.get('decision')}）の文: {ru.get('text')}"]
    if role == "plan-review":
        lines += ["", NEW_HEAD, "", *_json_block(new_item(row))]
    return "\n".join(lines)


def prep(board_dir, role: str, repo, *, head: str, design_part: str = "") -> dict:
    """指示書を書き、起こす前の作業ツリーの写しを置き直す。返り {prompt_file, attempt, out_path, node, already}（planblk.prep と同じ鍵。
    out_path は受け付けが置く TRIP_FILE）。指示書は head（呼び手の planblk.head）・役の頼み（plan は REPLAN_ASK、plan-review は
    design_part と REVIEW_ASK_REPLAN と planmarks.REVIEW_ASK）・項目ごとの節だけ。拒否の後は 1 行目で前の理由のファイルを名指す。
    渡す項目が無ければ BoardGap（snap が go の時だけ支度する）"""
    node = node_of(role)
    board_dir = pathlib.Path(board_dir)
    b = entry.open_board(board_dir)
    rows = _handed(read_trip(b), role)
    if not rows:
        raise BoardGap(f"{node} に渡す項目が無い（{TRIP_FILE} を snap が go と言った時だけ支度する）")
    conflicts = {c.get("id"): c for c in conflict.items(b)}
    ask = [REPLAN_ASK] if role == "plan" else [design_part, REVIEW_ASK_REPLAN, planmarks.REVIEW_ASK]
    parts = [head.rstrip("\n"), *ask, *(_section(r, conflicts, role) for r in rows)]
    rejects = _rejects(board_dir, node)
    reject_file = ""
    if rejects:   # 拒否の控えは文で積む（盤面の節でない受け付け）。役が Read で読むファイルに置いて名指す（文は貼らない。R44）
        rf = b.work(f"reject-{safe_name(node)}-{len(rejects)}.txt")
        rf.write_text(str(rejects[-1].get("reason") or ""), encoding="utf-8")
        reject_file = str(rf)
    entry.snapshot(board_dir, _snapshot_name(role), pathlib.Path(repo))
    p = b.work(rolekit.prompt_name(node))
    p.write_text(rolekit.compose(parts, reject_file=reject_file), encoding="utf-8")
    return {"prompt_file": str(p), "attempt": len(rejects) + 1, "out_path": str(b.work(TRIP_FILE)), "node": node,
            "already": False}


def _start_tree(b, repo):
    """受け入れのテストの定義を修正の起点の版（盤面の state.inputs.review_rev。無ければ HEAD）の木で引く口（planmarks.gaps の
    exists）。版が引けなければ Reject（『分からない』を在ると・無いとに倒さない）"""
    rev = (b.state.get("inputs") or {}).get("review_rev") or "HEAD"
    try:
        leftovers.git(repo, "rev-parse", "--verify", "--quiet", f"{rev}^{{commit}}")
    except leftovers.Unreadable as e:
        raise Reject(f"修正の起点の版 {rev} が引けない: {e}") from None
    cache: dict = {}

    def exists(test_id):
        path = posixpath.normpath(str(test_id).split("::", 1)[0])
        if path not in cache:
            try:
                cache[path] = leftovers.git(repo, "show", f"{rev}:{path}")
            except leftovers.Unreadable:   # その版に無いファイル
                cache[path] = None
        return planmarks.line_in(cache[path], test_id) if cache[path] is not None else None
    return exists


def _malformed(reply) -> bool:
    """修正案の返答の形が崩れているか（plan が list でない・行が dict でない・narrows が list でない）。崩れていれば欄の検査を
    飛ばし、型の外れだけを言う"""
    plan = reply.get("plan") if isinstance(reply, dict) else None
    if not isinstance(plan, list):
        return True
    return any(not isinstance(p, dict) or not isinstance(p.get("narrows") or [], list) for p in plan)


def _type_lines(reply, node: str) -> list:
    errs = validate_schema(reply, accept.role_schema(node))
    more = [f"型の外れ: ほか {len(errs) - MAX_TYPE_ERRORS} 件"] if len(errs) > MAX_TYPE_ERRORS else []
    return [f"型の外れ: {e}" for e in errs[:MAX_TYPE_ERRORS]] + more


def _plan_errors(b, rows: list, reply, repo) -> list:
    """修正案の役の返答の誤りの行の全部（数・unit_keys の字・works の欄・狭めない案・型）"""
    plan = reply.get("plan") if isinstance(reply, dict) else None
    out = []
    if not isinstance(plan, list) or len(plan) != len(rows):
        out.append(f"plan[] は {len(rows)} 項目（貼った項目の数）")
    for i, (row, got) in enumerate(zip(rows, plan if isinstance(plan, list) else [])):
        want = row["old"].get("unit_keys")
        if not isinstance(got, dict) or got.get("unit_keys") != want:
            out.append(f"plan[{i}].unit_keys が貼った {json.dumps(want, ensure_ascii=False)} と違う（一字も変えずに写す）")
    if not _malformed(reply):
        out += planmarks.gaps(reply, pathlib.Path(repo), exists=_start_tree(b, pathlib.Path(repo)))
        out += gatemarks.narrow_gaps(planmarks.NODE, reply)
    return out + _type_lines(reply, planmarks.NODE)


def _review_of(row: dict, reply: dict, rows: list) -> dict:
    """事前審査の返答のうち項目 row の分: faces・shrink は unit_keys が項目の単位と重なる行（どの渡した項目とも重ならない行は
    全部の項目に置く。落とさない）。ほかの欄はそのまま"""
    mine = set(row["old"].get("unit_keys") or [])
    every = set().union(*(set(r["old"].get("unit_keys") or []) for r in rows))

    def keep(x):
        keys = set(x.get("unit_keys") or []) if isinstance(x, dict) else set()
        return bool(keys & mine) or not (keys & every)
    out = copy.deepcopy(reply)
    for key in ("faces", "shrink"):
        out[key] = [x for x in reply.get(key) or [] if keep(x)]
    return out


def _take(board_dir: pathlib.Path, role: str, reply, repo) -> dict:
    """受け付けの中身。誤りは {ok: False, reason}、通れば TRIP_FILE に置いて {ok: True, reason: ""}"""
    b = entry.open_board(board_dir)
    doc = read_trip(b)
    rows = _handed(doc, role)
    moved = entry.tree_moved_since(b, _snapshot_name(role), pathlib.Path(repo))
    if moved:
        return {"ok": False, "reason": entry.READONLY_MOVED + moved}
    if role == "plan":
        errs = _plan_errors(b, rows, reply, repo)
        if errs:
            return {"ok": False, "reason": REPLAN_REJECT + "\n" + "\n".join(f"  - {e}" for e in errs)}
        for row, got in zip(rows, reply["plan"]):
            bare, marks = gatemarks.split(planmarks.NODE, {"plan": [got]})
            row["new"], row["new_marks"] = bare["plan"][0], marks[0]
    else:
        errs = _type_lines(reply, REVIEW_GRAPH_NODE)
        if errs:
            return {"ok": False, "reason": REVIEW_REJECT + "\n" + "\n".join(f"  - {e}" for e in errs)}
        for row in rows:
            row["review"] = _review_of(row, reply, rows)
    _write_trip(b, doc)
    return {"ok": True, "reason": ""}


def accept_reply(board_dir, role: str, raw, repo) -> dict:
    """役の返答（JSON の文字列）を受け付ける。返り {ok, done, give_up, reason, node}（design.accept_reply と同じ形）。拒否は
    rolekit.with_done の控え（盤面の根の rejects-<節>.json）に積み、GIVE_UP_AFTER 回目で done・give_up（盤面は止めない）"""
    node = node_of(role)
    board_dir = pathlib.Path(board_dir)
    if not _handed(read_trip(entry.open_board(board_dir)), role):   # 配線の誤り（拒否に数えない）
        raise BoardGap(f"{node} に渡した項目が {TRIP_FILE} に無い（支度の後に受け付ける）")
    reply, why = rolekit.parse_reply(raw)
    got = {"ok": False, "reason": why} if reply is None else accept.guard(lambda: _take(board_dir, role, reply, repo))
    out = rolekit.with_done(board_dir, node, {"ok": got["ok"], "reason": got.get("reason", "")},
                            give_up_after=rolekit.GIVE_UP_AFTER)
    return {"ok": out["ok"], "done": out["done"], "give_up": bool(out["done"] and not out["ok"]), "reason": out["reason"],
            "node": node}


def collect(board_dir) -> dict:
    """出口（blk-plan の出口と同じ鍵）。役の諦めは盤面を止めない（後の関所が項目ごとに読む）。reads_file は読んだ証拠の索引
    READS_INDEX（無ければ空）"""
    b = entry.open_board(pathlib.Path(board_dir), allow_halted=True)
    idx = b.work(READS_INDEX)
    return {"ok": True, "plan_file": "", "review_file": "", "asks_human": False, "gate_kinds": [],
            "reads_file": str(idx) if idx.exists() else "", "gave_up": False, "reason_file": ""}
