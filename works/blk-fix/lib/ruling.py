"""食い違いの申し出の裁定の輪（blk-fix の rule-loop。読むだけの役 rule の前後の機械。持ち主 2026-09-28「おしで」）。

コントローラが下請けの「できない・すべきでない」を証拠つきで受け、記録した決まりで裁き、能力を下げる・決められない物だけを
人に上げるのと同じ形を、修正役の出口に置く。輪の AI の節は rule の 1 つ（TA13）で、done の印で抜ける（R50）。

- check(b): 節 conflict-check。今の周に裁かれていない申し出が在れば go（裁定の輪と 2 回目の修正役を回す）
- prep(board_dir, repo, values): 節 rule-prep。作業ツリーの姿を控え（entry.snapshot。読むだけの役の見張り）、指示書を
  fixrules.ruler_prompt で組んで盤面の今の周の prompt-rule.md に書く。出し直しなら前の拒否の理由のファイルを 1 行目で名指す（R44）
- accept_rule(reply, board, base_rev, repo): 節 rule-accept（script_io.main が回す）。作業ツリーが変わっていない・裁く申し出の id に
  ちょうど 1 件ずつ・語・fix_test_scope の範囲が現物に在る・replace_query の問いが例（hits・misses・申し出の correct_lines）で
  外れない・裁きの出どころ（grounds）が現物に在り、依頼のファイルが在る run の ask_human は依頼の行か request_searched を持つ・
  fix_plan_item は範囲を持たず、grounds にその単位の brief の行を名指す（planbrief.by_unit_at・conflict.brief_cite_problem）・
  同じ返答で fix_plan_item に裁いた項目の単位に直す裁定を出さない（plan_item_fix_problems）、
  を確かめて conflict.apply_rulings で積む
  （fix_plan_item には欄 plan_items にその単位の brief の項目の番号を、欄 plan_units にその項目に載る単位の全部を足す）。GIVE_UP_AFTER 回目の拒否では
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
import planbrief  # noqa: E402   今の周の brief の行（fix_plan_item を brief の在る単位に限る）
import querytest  # noqa: E402
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
REJECT_FN = "accept_rule"   # 受け付けの関数の名（拒否の理由のファイルの名。script_io.reject_name）
RULING_KEYS = ("decision", "text", "limits", "grounds", "request_searched", "query")   # 盤面の控えに積む裁定の欄
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
    """裁定の受け付けが今の scope の根に書いた一番新しい拒否の理由のファイル（ほかの scope の物は見ない。script_io.last_reject）"""
    return script_io.last_reject(board_dir, REJECT_FN)


def prep(board_dir, repo, values: dict, pass_tag: str = "") -> dict:
    """節 rule-prep: {prompt_file, iteration}。裁く申し出が無ければ BoardGap（配線の誤り）。pass_tag は修正の段の回の印
    （fixrules.tagged。指示書・回の数えの控え・拒否の理由の名を分け、2 回目の修正の段の裁定の輪は 1 から数える）"""
    board_dir = pathlib.Path(board_dir)
    b = entry.open_board(board_dir)
    todo = conflict.unruled(b)
    if not todo:
        raise BoardGap("裁く申し出が無い（conflict-check の go が偽なのに裁定の輪を回した）")
    ledger = b.work(fixrules.tagged(LEDGER, pass_tag))
    n = ((_read_json(ledger) or {}).get("iterations") or 0) + 1
    entry.snapshot(board_dir, TREE, pathlib.Path(repo))
    vals = {**values, "conflicts_file": str(b.work(conflict.FILE)), "ids": ", ".join(i["id"] for i in todo),
            "request_file": conflict.request_file(board_dir)}
    text = fixrules.ruler_prompt(vals, reject_file=_last_reject(board_dir) if n > 1 else "", iteration=n,
                                 lang=fixrules.lang_at(board_dir))
    path = b.work(fixrules.tagged(PROMPT, pass_tag))
    path.write_text(text, encoding="utf-8")
    ledger.write_text(json.dumps({"iterations": n}) + "\n", encoding="utf-8")
    return {"prompt_file": str(path), "iteration": n}


def limit_problem(lim: str, repo) -> str:
    """範囲の 1 つ（<パス>・<パス>:<行>・<パス>:<行>-<行>。リポジトリの根から）が現物に在るか"""
    if not isinstance(lim, str) or not lim.strip():
        return f"範囲 {lim!r} が空"
    if conflict.parse_limit(lim) is None:   # 絶対パス・根の外: 凍結の検査（tddloop.frozen_problems）が読めない範囲を受けない
        return f"範囲 {lim!r} がリポジトリの根からの相対パスでない"
    if conflict.CITE.match(lim.strip()):
        return conflict.cite_problem(lim, repo)
    repo = pathlib.Path(repo).resolve()
    p = (repo / lim.strip()).resolve()
    if pathlib.Path(lim.strip()).is_absolute() or not str(p).startswith(str(repo) + os.sep) or not p.is_file():
        return f"範囲 {lim!r} がリポジトリの中のファイルでない"
    return ""


def grounds_problems(r: dict, repo, request: str, roots) -> list:
    """裁きの出どころ: grounds の名指しが全部現物に在る（conflict.cite_problem）。依頼のファイルが在る run の ask_human は、
    grounds に依頼の行を挙げる（依頼に先に書かれた人の答え。debconf の preseed と同じく、在れば聞かずに使う）か、
    request_searched に依頼で何を探して答えが無かったかを書く"""
    grounds = r.get("grounds") or []
    errs = [e for e in (conflict.cite_problem(g, repo, roots) for g in grounds) if e]
    def at(p):
        return (pathlib.Path(repo) / p).resolve()   # 絶対のパスは / がそのまま勝つ
    if r["decision"] == conflict.ASK and request and at(request).is_file() and not r.get("request_searched"):
        cited = [m for m in (conflict.CITE.match(g.strip()) for g in grounds if isinstance(g, str)) if m]
        if not any(at(m["path"]) == at(request) for m in cited):
            errs.append(f"依頼のファイル {request} が在る run の ask_human は、依頼に先に書かれた人の答えを当たった証拠が要る——"
                        "答えが在れば grounds に依頼の行（<絶対パス>:<行>）を挙げてそれで裁き、無ければ request_searched に"
                        "依頼で何を探して答えが無かったかを書け")
    return errs


def plan_item_units(unit_key, briefs) -> tuple:
    """fix_plan_item が誤りと裁く案の項目: (その単位の brief の項目の番号, その項目に載る単位の全部)。briefs は
    planbrief.by_unit_at の {unit_key: [{item, file}]}（brief の無い単位は ([], [])）"""
    nums = [x["item"] for x in (briefs or {}).get(unit_key) or []]
    return nums, [k for k, rows in (briefs or {}).items() if any(x["item"] in nums for x in rows)]


def problems(reply, todo: dict, repo, request: str = "", roots=(), briefs=None) -> list:
    """裁定の返答の確かめ（空なら通る）。request は run の依頼のファイル（空なら依頼の無い run）、roots は grounds の絶対パスを
    許す置き場（依頼のファイル・盤面）、briefs は今の周の brief の行 {unit_key: [{item, file}]}（planbrief.by_unit_at。None と {}
    は brief の無い run で、fix_plan_item を通さない）"""
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
            errs.append(f"申し出 {r['id']}: fix_test_scope なのに範囲（limits。直してよいテストの <パス>・<パス>:<行>・<パス>:<行>-<行>）が無い")
        if r["decision"] in conflict.FIX_DECISIONS:
            errs += [f"申し出 {r['id']}: {e}" for e in (limit_problem(x, repo) for x in r["limits"]) if e]
        if r["decision"] == conflict.REPLAN:
            if r["limits"]:
                errs.append(f"申し出 {r['id']}: {conflict.REPLAN} は範囲を持たない（テストの変更の許しを作らない。limits は空）")
            bad = conflict.brief_cite_problem((todo.get(r["id"]) or {}).get("unit_key"), r.get("grounds"), repo, briefs,
                                              conflict.REPLAN, "grounds")
            if bad:
                errs.append(f"申し出 {r['id']}: {bad}")
        if r["decision"] == conflict.REPLACE or "query" in r:
            errs += [f"申し出 {r['id']}: {e}" for e in query_problems(r, todo.get(r["id"]) or {})]
        errs += [f"申し出 {r['id']}: {e}" for e in grounds_problems(r, repo, request, roots)]
    errs += plan_item_fix_problems(rows, todo, briefs)
    return errs


def plan_item_fix_problems(rows: list, todo: dict, briefs) -> list:
    """同じ返答で fix_plan_item に裁いた案の項目に載る単位へ、直す裁定（FIX_DECISIONS）を出した物（項目の単位は fix_plan_item が
    直す義務から外すので、「直せ」と「直すな」が裁定の文に並ぶ）。単位・裁定・項目を名指す"""
    held = {}
    for r in rows:
        if r["decision"] == conflict.REPLAN and r["id"] in todo:
            nums, units = plan_item_units(todo[r["id"]].get("unit_key"), briefs)
            for k in units:
                held.setdefault(k, (r["id"], nums))
    errs = []
    for r in rows:
        k = (todo.get(r["id"]) or {}).get("unit_key")
        if r["decision"] in conflict.FIX_DECISIONS and k in held:
            rid, nums = held[k]
            errs.append(f"申し出 {r['id']}: 単位 {k} は同じ返答で {conflict.REPLAN} に裁いた申し出 {rid} の案の項目 "
                        f"{', '.join(map(str, nums))} に載る（その項目の単位は直さない）のに {r['decision']} に裁いた——"
                        f"項目が誤りなら {conflict.REPLAN} か {conflict.ASK} に揃えよ")
    return errs


def query_problems(r: dict, item: dict) -> list:
    """replace_query の裁定の問いを例で試す（Semgrep の規則の試験の ruleid・ok と同じ形）: hits に全部当たり、misses にも
    申し出の correct_lines（判定者の問いが当たってしまった直した後の正しい行）にも当たらない"""
    if r["decision"] != conflict.REPLACE:
        return [f"query は {conflict.REPLACE} の裁定だけに書く"]
    q = r.get("query")
    if not isinstance(q, dict):
        return [f"{conflict.REPLACE} なのに置き換える問い（query {{how, counts, hits, misses}}）が無い"]
    if item.get("which_is_right") != conflict.QUERY:
        return [f"{conflict.REPLACE} は which_is_right が {conflict.QUERY} の申し出だけに裁ける"]
    hits, misses, correct = list(q["hits"]), list(q["misses"]), list(item.get(conflict.CORRECT) or [])
    got, why = querytest.run_examples(q["how"], hits + misses + correct)
    if why:
        return [f"置き換える問いを例に当てられない（{why}）"]
    errs = []
    missed = [h for i, h in enumerate(hits) if i not in got]
    if missed:
        errs.append("置き換える問いが hits に当たらない: " + " / ".join(repr(h) for h in missed))
    struck = [m for i, m in enumerate(misses) if len(hits) + i in got]
    if struck:
        errs.append("置き換える問いが misses に当たる: " + " / ".join(repr(m) for m in struck))
    wrong = [c for i, c in enumerate(correct) if len(hits) + len(misses) + i in got]
    if wrong:
        errs.append(f"置き換える問いが申し出の {conflict.CORRECT}（直した後の正しい行）にも当たる: "
                    + " / ".join(repr(c) for c in wrong))
    return errs


def accept_rule(reply, board, base_rev, repo) -> dict:
    """節 rule-accept の中身。{ok, done, reason, rulings_file, counts}。裁定の文の名は修正の段の回の印（環境変数 INPUTS_PASS_TAG）で分ける"""
    tag = os.environ.get("INPUTS_PASS_TAG", "")
    b = entry.open_board(pathlib.Path(board))
    todo = {i["id"]: i for i in conflict.unruled(b)}
    it = int(os.environ["INPUTS_ITERATION"])
    snap = _read_json(b.work(TREE))
    if not (isinstance(snap, dict) and set(TREE_KEYS) <= set(snap)):
        raise BoardGap(f"{b.work(TREE)} が無い・形が違う——rule-prep が先に走る")
    moved = tree_moved({k: snap[k] for k in TREE_KEYS}, pathlib.Path(repo))
    request = conflict.request_file(board)
    briefs = planbrief.by_unit_at(board)
    errs = [READONLY + "・".join(moved)] if moved else problems(reply, todo, repo, request, (request, str(board)), briefs)
    if not errs:
        def stored(r):   # 盤面に積む欄（役の欄と、fix_plan_item には機械が足すその単位の brief の項目の番号と、その項目の単位の全部）
            got = {k: r[k] for k in RULING_KEYS if k in r}
            if r["decision"] == conflict.REPLAN:
                got[conflict.PLAN_ITEMS], got[conflict.PLAN_UNITS] = plan_item_units(todo[r["id"]]["unit_key"], briefs)
            return got
        path = conflict.apply_rulings(b, {r["id"]: stored(r) for r in reply["rulings"]}, by=BY_ROLE, pass_tag=tag)
        return {"ok": True, "done": True, "reason": "", "rulings_file": str(path), "counts": conflict.counts(b)}
    out = {"ok": False, "done": False, "reason": " / ".join(errs), "rulings_file": "", "counts": conflict.counts(b)}
    if it >= GIVE_UP_AFTER:
        path = conflict.apply_rulings(b, {i: {"decision": conflict.ASK, "text": GIVE_UP_TEXT, "limits": []} for i in todo},
                                      by=BY_GIVE_UP, pass_tag=tag)
        out.update(done=True, rulings_file=str(path), counts=conflict.counts(b))
    return out
