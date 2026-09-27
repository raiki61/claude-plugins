"""食い違いの申し出の裁定の輪（blk-fix の rule-loop。読むだけの役 rule の前後の機械。持ち主 2026-09-28「おしで」）。

コントローラが下請けの「できない・すべきでない」を証拠つきで受け、記録した決まりで裁き、能力を下げる・決められない物だけを
人に上げるのと同じ形を、修正役の出口に置く。輪の AI の節は rule の 1 つ（TA13）で、done の印で抜ける（R50）。

- check(b): 節 conflict-check。今の周に裁かれていない申し出が在れば go（裁定の輪と 2 回目の修正役を回す）
- prep(board_dir, repo, values): 節 rule-prep。作業ツリーの姿を控え（entry.snapshot。読むだけの役の見張り）、指示書を
  fixrules.ruler_prompt で組んで盤面の今の周の prompt-rule.md に書く。出し直しなら前の拒否の理由のファイルを 1 行目で名指す（R44）
- accept_rule(reply, board, base_rev, repo): 節 rule-accept（script_io.main が回す）。作業ツリーが変わっていない・裁く申し出の id に
  ちょうど 1 件ずつ・語・fix_test_scope の範囲が現物に在る、を確かめて conflict.apply_rulings で積む。GIVE_UP_AFTER 回目の拒否では
  裁かれていない申し出を全部 ask_human に裁いて抜ける（決められない物は人へ。max_iterations で落とさない）
"""
import json
import os
import pathlib
import sys

sys.dont_write_bytecode = True

_CORE = pathlib.Path(__file__).resolve().parents[2] / ".shared" / "core"
if str(_CORE) not in sys.path:
    sys.path.insert(0, str(_CORE))

from accept import TREE_KEYS, tree_moved  # noqa: E402   共通の作業ツリーの比べ（R47）
from board import BoardGap  # noqa: E402
import conflict  # noqa: E402
from engine.schema import validate_schema  # noqa: E402
import entry  # noqa: E402
import fixrules  # noqa: E402
import node_marker  # noqa: E402
import script_io  # noqa: E402

ROLE = "rule"
TREE = "rule-tree.json"          # 役を起こす前の作業ツリーの姿（b.work）
PROMPT = "prompt-rule.md"        # 指示書（b.work）
LEDGER = "rule-prep.json"        # この輪の回の数え {iterations}
GIVE_UP_AFTER = 3                # 輪 rule-loop の max_iterations と同じ（試験が YAML と突き合わせる）
BY_ROLE = "role:rule"
BY_GIVE_UP = "works:rule-give-up"
GIVE_UP_TEXT = f"裁定役の返答が {GIVE_UP_AFTER} 回とも受け付けを通らなかった——材料から決められない物として人に回した"
READONLY = "裁定役は読むだけで、作業ツリー・HEAD・枝・git が無視するファイルを変えてはいけない: "
REJECT_GLOB = f"{script_io.REJECT_PREFIX}accept_rule-*.txt"
RULE_OUTPUT_FORMAT = node_marker.mark({
    "type": "object", "additionalProperties": False, "required": ["rulings"],
    "properties": {"rulings": {"type": "array", "minItems": 1, "items": conflict.RULING_SCHEMA}}}, ROLE)


def _read_json(path: pathlib.Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def check(board_dir) -> dict:
    """節 conflict-check: {go, count, file}"""
    b = entry.open_board(pathlib.Path(board_dir))
    todo = conflict.unruled(b)
    return {"go": bool(todo), "count": len(todo), "file": str(b.work(conflict.FILE)) if todo else ""}


def _last_reject(board_dir) -> str:
    def n(p):
        tail = p.stem.rsplit("-", 1)[-1]
        return int(tail) if tail.isdigit() else -1
    got = sorted(pathlib.Path(board_dir).glob(REJECT_GLOB), key=n)
    return str(got[-1]) if got else ""


def prep(board_dir, repo, values: dict) -> dict:
    """節 rule-prep: {prompt_file, iteration}。裁く申し出が無ければ BoardGap（配線の誤り）"""
    board_dir = pathlib.Path(board_dir)
    b = entry.open_board(board_dir)
    todo = conflict.unruled(b)
    if not todo:
        raise BoardGap("裁く申し出が無い（conflict-check の go が偽なのに裁定の輪を回した）")
    ledger = b.work(LEDGER)
    n = ((_read_json(ledger) or {}).get("iterations") or 0) + 1
    entry.snapshot(board_dir, TREE, pathlib.Path(repo))
    vals = {**values, "conflicts_file": str(b.work(conflict.FILE)), "ids": ", ".join(i["id"] for i in todo),
            "request_file": conflict.request_file(board_dir)}
    text = fixrules.ruler_prompt(vals, reject_file=_last_reject(board_dir) if n > 1 else "", iteration=n)
    path = b.work(PROMPT)
    path.write_text(text, encoding="utf-8")
    ledger.write_text(json.dumps({"iterations": n}) + "\n", encoding="utf-8")
    return {"prompt_file": str(path), "iteration": n}


def limit_problem(lim: str, repo) -> str:
    """範囲の 1 つ（<パス> か <パス>:<行>。リポジトリの根から）が現物に在るか"""
    if not isinstance(lim, str) or not lim.strip():
        return f"範囲 {lim!r} が空"
    if conflict.CITE.match(lim.strip()):
        return conflict.cite_problem(lim, repo)
    repo = pathlib.Path(repo).resolve()
    p = (repo / lim.strip()).resolve()
    if pathlib.Path(lim.strip()).is_absolute() or not str(p).startswith(str(repo) + os.sep) or not p.is_file():
        return f"範囲 {lim!r} がリポジトリの中のファイルでない"
    return ""


def problems(reply, todo: dict, repo) -> list:
    """裁定の返答の確かめ（空なら通る）"""
    errs = validate_schema(reply, RULE_OUTPUT_FORMAT)
    if errs:
        return [f"返答の形: {e}" for e in errs]
    rows = reply["rulings"]
    ids = [r["id"] for r in rows]
    errs = [f"知らない申し出の id {i!r}（裁くのは {sorted(todo)}）" for i in dict.fromkeys(i for i in ids if i not in todo)]
    errs += [f"申し出 {i} を 2 度裁いた" for i in dict.fromkeys(i for i in ids if ids.count(i) > 1)]
    errs += [f"申し出 {i} を裁いていない" for i in todo if i not in ids]
    for r in rows:
        if r["decision"] == "fix_test_scope" and not r["limits"]:
            errs.append(f"申し出 {r['id']}: fix_test_scope なのに範囲（limits。直してよいテストの <パス> か <パス>:<行>）が無い")
        if r["decision"] in conflict.FIX_DECISIONS:
            errs += [f"申し出 {r['id']}: {e}" for e in (limit_problem(x, repo) for x in r["limits"]) if e]
    return errs


def accept_rule(reply, board, base_rev, repo) -> dict:
    """節 rule-accept の中身。{ok, done, reason, rulings_file, counts}"""
    b = entry.open_board(pathlib.Path(board))
    todo = {i["id"]: i for i in conflict.unruled(b)}
    it = int(os.environ["INPUTS_ITERATION"])
    snap = _read_json(b.work(TREE))
    if not (isinstance(snap, dict) and set(TREE_KEYS) <= set(snap)):
        raise BoardGap(f"{b.work(TREE)} が無い・形が違う——rule-prep が先に走る")
    moved = tree_moved({k: snap[k] for k in TREE_KEYS}, pathlib.Path(repo))
    errs = [READONLY + "・".join(moved)] if moved else problems(reply, todo, repo)
    if not errs:
        path = conflict.apply_rulings(b, {r["id"]: {k: r[k] for k in ("decision", "text", "limits")}
                                          for r in reply["rulings"]}, by=BY_ROLE)
        return {"ok": True, "done": True, "reason": "", "rulings_file": str(path), "counts": conflict.counts(b)}
    out = {"ok": False, "done": False, "reason": " / ".join(errs), "rulings_file": "", "counts": conflict.counts(b)}
    if it >= GIVE_UP_AFTER:
        path = conflict.apply_rulings(b, {i: {"decision": conflict.ASK, "text": GIVE_UP_TEXT, "limits": []} for i in todo},
                                      by=BY_GIVE_UP)
        out.update(done=True, rulings_file=str(path), counts=conflict.counts(b))
    return out
