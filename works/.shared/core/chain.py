"""周の鎖の住処（考え chain。地図 docs/concepts.md）。層 L3（結末の住処 report と持ち越しの住処 carry を読む）。

鎖は、利用者が `use.sh start --rounds N [--budget-usd X]` と打った時に起動の殻が起こす、周ごとの普通の 1 周の run の並び
（計画 docs/plans/2026-10-09-chained-rounds.md）。どの周も今と同じ入口の形の 1 本の run で、run の中のどこも鎖を知らない（入力に
鎖の欄を足さない。鎖の印は起動の印 launch_mark の字の中だけ）。k+1 周目の run は k 周目の結果の版から切り、差分の根を k 周目の
基にし（入力 base。P1 の役が k 周目の直しを見る）、依頼は k 周目の報告が書いた次の依頼の下書きから組む。

ここが持つのは周の間の決めだけ: 鎖の控え（chain.json）の形と読み書き・周の行を盤面から組む口・止める条件の順と止めの語・次の
周の依頼・最後に採る周・鎖の報告の行。git と Archon を呼ぶのは殻（dev/use.sh）で、殻は `python3 chain.py <口>` で呼ぶ。
止めの語（STOPS）は鎖の控えと鎖の報告にだけ出る。盤面の state.stop.by の語（考え stop-reasons の stopby）とは別の名の空間で、
盤面には書かない。結末の語は字で持たず、結末の住処の種の表 report.OUTCOME_KIND だけを読む（考え outcome の柵）。

止める条件（決まった順。verdict）:
1. 周の数が名指した N に達した → rounds_reached
2. 結末の種が broken（run が途中で終わった）→ 待つ（wait。人が続けてから chain-resume）
3. 次の依頼の下書きに下書きの印の在る行（人の判断が要る）が在るか、結末の種が waiting → human（鎖は下書きを答えに替えない。
   無人の run が関所で止めた周は結末が止まりでも、下書きが在ればここ。人が居ても居なくても同じ決まり）
4. 結末の種: halted（と読めない結末）→ halted・closed → closed・mended（直して閉じた）は confirm なら確かめの周（依頼の行を空に
   した周。差分は今の周の直し）へ進み、そうでなければ closed
5. 周の差分を書けず結果の版が無い → no_result
6. 周の差分が空 → no_change・残りの行の鍵（carry.row_key）の集まりが前の周と同じ（空でない）→ same_items
7. 費用の上限を名指した時だけ: 読めない周が在る → cost_unknown・累計 ＋ これまでの周の最大 ＞ 上限 → budget
8. どれにも当たらない → go

- STOPS・FILE・REPORT_FILE・FINAL_FILE・request_name(n): 止めの語と文・控えと報告と最後の差分と周の依頼のファイルの名
- new(...)・round_row(n, run_id, base, request_file="")・recorded(row, *, board, diff, result, minutes, cost, diff_ok)・
  minutes(run_row, events): 控えと周の行
- verdict(doc, *, confirm=True) -> {go: go|wait|stop, word, text, next_empty}
- next_request(round_doc, first, *, empty=False) -> (次の依頼, 運ばなかった下書きの行)
- final_round(doc) -> 最後に採る周の番号か None（最後の周から戻り、止まりの記録の無い・結果の版の在る最初の周）
- report_lines(doc, *, final_diff, apply_line) -> 鎖の報告の行
- load(path)・save(path, doc)
"""
from __future__ import annotations

import argparse
import datetime
import json
import pathlib
import sys

sys.dont_write_bytecode = True
_HERE = pathlib.Path(__file__).resolve().parent
if str(_HERE) not in sys.path:   # 殻は python3 -I で起こす（-I は自分の置き場を sys.path に足さない）
    sys.path.insert(0, str(_HERE))

import carry  # noqa: E402   持ち越しの形（依頼の容器・下書きの印・行の鍵）
import report  # noqa: E402  結末の種（OUTCOME_KIND）・報告の結末の読み・費用の和・止まりの記録

FILE = "chain.json"
REPORT_FILE = "chain.md"
FINAL_FILE = "final.diff"
STOPS = {
    "rounds_reached": "名指した周の数に達した",
    "closed": "直す物が無くなった（直す物が無い周か、直した周の後の確かめの周が何も出さなかった）",
    "halted": "周が止まった（止め札・人が関所で stop・ラインの止め・記録が検証器を通らない）",
    "human": "人の判断が要る（答えの下書き・目的の外とした所見の下書きが在るか、結末が人の判断か確かめを待つ）",
    "no_result": "周の差分を書けず、次の周の基にする結果の版を作れなかった",
    "no_change": "周の差分が空（直しが進まない）",
    "same_items": "残りの行が前の周と同じ（直しが進まない）",
    "budget": "次の周で費用の上限を越えうる（累計とこれまでの周の最大の和が上限を越える）",
    "cost_unknown": "費用の読めない周が在り、上限を守れると言えない",
}
GO_TEXT = "次の周を起こす"
CONFIRM_TEXT = "直した周の後に、依頼の行を空にして直しを確かめる周を起こす"
WAIT_TEXT = "run が途中で終わった（人が続けてから chain-resume で鎖を進める）"
UNREAD_TEXT = "（報告の結末を読めない）"


def request_name(n: int) -> str:
    """周 n の依頼のファイルの名（鎖の置き場の中）"""
    return f"round-{n}-request.json"


def new(chain_id: str, target: str, original_base: str, rounds_max: int, budget_usd, launch: dict, first_request: str) -> dict:
    """鎖の控え（周の行はまだ無い。止めるまで stop は None）"""
    return {"id": chain_id, "target": target, "original_base": original_base, "rounds_max": rounds_max,
            "budget_usd": budget_usd, "launch": launch, "first_request": first_request, "rounds": [], "stop": None}


def round_row(n: int, run_id: str, base: str, request_file: str = "") -> dict:
    """起こした周の行（記録の欄は recorded が足す）"""
    return {"n": n, "run_id": run_id, "base": base, "request_file": request_file}


def _read_json(path):
    try:
        return json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _held_line(r: dict) -> str:
    head = " ".join(str(r.get("where") or r.get("question") or "").split())
    body = " ".join(str(r.get("text") or r.get("note") or "").split())
    return f"{head}: {body[:200]}" if body else head


def _diff_files(diff) -> int:
    try:
        text = pathlib.Path(diff).read_text(encoding="utf-8", errors="replace") if diff else ""
    except OSError:
        return 0
    return sum(1 for line in text.splitlines() if line.startswith("diff --git "))


def recorded(row: dict, *, board, diff, result: str, minutes, cost: tuple, diff_ok: bool) -> dict:
    """周の行に記録を足した写し: 盤面の報告の結末・次の依頼の下書きの残りの鍵（下書きでない findings の carry.row_key）と下書きの
    行・止まりの記録（report.stopped_run が止まりと言えば真。言えない時は偽）・差分のファイルの数。cost は report.spent の返り"""
    board = pathlib.Path(board) if board else None
    nxt = _read_json(board / carry.NEXT_REQUEST_FILE) if board else None
    nxt = nxt if isinstance(nxt, dict) else {}
    rows = [r for k in (carry.FINDINGS, carry.ANSWERS) for r in nxt.get(k) or [] if isinstance(r, dict)]
    findings = [r for r in nxt.get(carry.FINDINGS) or [] if isinstance(r, dict) and not carry.is_draft(r)]
    held = [_held_line(r) for r in rows if carry.is_draft(r)]
    usd, _missing = cost
    stopped = report.stopped_run(board) if board and board.is_dir() else None
    return {**row, "result": result or "", "diff_ok": bool(diff_ok),
            "outcome": report.read_outcome(board) if board else "",
            "minutes": minutes, "cost_usd": usd, "cost_known": usd is not None,
            "open_keys": sorted({carry.row_key(r) for r in findings}), "held": len(held), "held_rows": held,
            "files": _diff_files(diff), "stopped": bool(stopped),
            "next_file": str(board / carry.NEXT_REQUEST_FILE) if board else "",
            "report_file": str(board / report.REPORT_FILE) if board else "", "diff_file": str(diff or "")}


def _when(v):
    try:
        t = datetime.datetime.fromisoformat(str(v).replace(" ", "T").replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return t if t.tzinfo else t.replace(tzinfo=datetime.timezone.utc)


def minutes(run_row: dict, events) -> float | None:
    """周の分: Archon の run の行の started_at から completed_at まで。どちらかが無ければ出来事の最初から最後まで。どれも無ければ None"""
    a, b = _when((run_row or {}).get("started_at")), _when((run_row or {}).get("completed_at"))
    if not (a and b):
        ats = [t for t in (_when(e.get("created_at")) for e in events or [] if isinstance(e, dict)) if t]
        a, b = (min(ats), max(ats)) if ats else (None, None)
    return round((b - a).total_seconds() / 60, 1) if a and b else None


def _stop(word: str, extra: str = "") -> dict:
    return {"go": "stop", "word": word, "text": STOPS[word] + extra, "next_empty": False}


def verdict(doc: dict, *, confirm: bool = True) -> dict:
    """鎖の控えの最後の周から、次を起こすか（go）・待つか（wait）・止めるか（stop）と、止めの語と文。confirm は直した周の後に
    確かめの周を足すか（next_empty が真の go）"""
    rows = doc.get("rounds") or []
    last = rows[-1]
    if len(rows) >= int(doc.get("rounds_max") or 0):
        return _stop("rounds_reached")
    kind = report.OUTCOME_KIND.get(last.get("outcome") or "")
    if kind == "broken":
        return {"go": "wait", "word": "", "text": WAIT_TEXT, "next_empty": False}
    if last.get("held") or kind == "waiting":   # 無人の run が関所で止めた周（結末は止まり）も、下書きが在れば人の判断を待つ
        return _stop("human")
    if kind is None:
        return _stop("halted", UNREAD_TEXT)
    if kind == "halted":
        return _stop("halted")
    if kind == "closed" or (kind == "mended" and not confirm):
        return _stop("closed")
    if not last.get("diff_ok", True) or not last.get("result"):
        return _stop("no_result")
    if not last.get("files"):
        return _stop("no_change")
    keys = set(last.get("open_keys") or [])
    if keys and len(rows) >= 2 and keys == set(rows[-2].get("open_keys") or []):
        return _stop("same_items")
    cap = doc.get("budget_usd")
    if cap is not None:
        if not all(r.get("cost_known") for r in rows):
            return _stop("cost_unknown")
        costs = [float(r.get("cost_usd") or 0) for r in rows]
        if sum(costs) + max(costs) > float(cap):
            return _stop("budget", f"（累計 ${sum(costs):.2f}・最大の周 ${max(costs):.2f}・上限 ${float(cap):.2f}）")
    mended = kind == "mended"
    return {"go": "go", "word": "go", "text": CONFIRM_TEXT if mended else GO_TEXT, "next_empty": mended}


def next_request(round_doc, first, *, empty: bool = False) -> tuple:
    """(次の周の依頼, 運ばなかった下書きの行)。依頼は今の依頼の容器の形だけで組む: findings は前の周の下書きでない残りの行
    （empty なら空＝確かめの周）、prior_failures は前の周の物、answers は 1 周目の依頼の答えと前の周が運んだ人の答え（同じ question
    は新しい方）、pr・issue は 1 周目の依頼の物。下書きの印の在る行は運ばない（人が見る物として返す）。組んだ依頼は依頼の入口と同じ
    carry.parts で確かめる（ValueError）"""
    doc = round_doc if isinstance(round_doc, dict) else {}
    findings = [r for r in doc.get(carry.FINDINGS) or [] if isinstance(r, dict)]
    answers = [a for a in doc.get(carry.ANSWERS) or [] if isinstance(a, dict)]
    held = [r for r in findings + answers if carry.is_draft(r)]
    head = carry.parts(first) if first is not None else {carry.PR: [], carry.ISSUE: [], carry.ANSWERS: []}
    out = {carry.FINDINGS: [] if empty else [r for r in findings if not carry.is_draft(r)]}
    for key in (carry.PR, carry.ISSUE):
        if head[key]:
            out[key] = head[key]
    human = carry.human_answers([], [*head[carry.ANSWERS], *(a for a in answers if not carry.is_draft(a))], "")
    if human:
        out[carry.ANSWERS] = human
    out[carry.PRIOR] = [r for r in doc.get(carry.PRIOR) or [] if isinstance(r, dict)]
    carry.parts(out)
    return out, held


def final_round(doc: dict):
    """最後に採る周の番号: 最後の周から戻り、結果の版が在り、止まりの記録（report.stopped_run）が無い最初の周。無ければ None"""
    for r in reversed(doc.get("rounds") or []):
        if r.get("result") and r.get("diff_ok", True) and not r.get("stopped"):
            return r["n"]
    return None


def _num(v, fmt: str) -> str:
    return format(v, fmt) if isinstance(v, (int, float)) and not isinstance(v, bool) else "取れない"


def report_lines(doc: dict, *, final_diff: str, apply_line: str) -> list:
    """鎖の報告（chain.md と殻が終わりに出す行）: 頭の 3 行（何が起きたか・止めた訳・人が見る物）・周ごとの表・合計・最後の差分と
    当てる行・採らなかった周の差分・運ばなかった下書きの行・周ごとの報告。読めない分と費用は 0 と書かず「取れない」"""
    rows = [r for r in doc.get("rounds") or [] if "outcome" in r]
    mins = [r.get("minutes") for r in rows]
    costs = [r.get("cost_usd") if r.get("cost_known") else None for r in rows]
    t_min = sum(m for m in mins if isinstance(m, (int, float)))
    t_cost = sum(c for c in costs if isinstance(c, (int, float)))
    unknown = sum(1 for c in costs if c is None)
    cost_text = f"${t_cost:.2f}" + (f"（取れない周 {unknown} 本は入っていない）" if unknown else "")
    cap = doc.get("budget_usd")
    stop = doc.get("stop") or {}
    held = [h for r in rows for h in r.get("held_rows") or []]
    pick = final_round(doc)
    look = [f"最後の差分 {final_diff}（当てる前に読む）"] if final_diff and pick else []
    if held:
        look.append(f"次の周に運ばなかった下書きの行 {len(held)} 件")
    out = [f"周の鎖 {doc.get('id')}: {len(rows)} 周を回した（名指した周の数 {doc.get('rounds_max')}"
           + (f"・費用の上限 ${float(cap):.2f}" if cap is not None else "") + f"）。合計 {t_min:.0f} 分・{cost_text}",
           f"止めた訳: {stop.get('text') or '止めていない'}" + (f"（{stop['word']}）" if stop.get("word") else ""),
           "人が見る物: " + ("・".join(look) if look else "無い"),
           "",
           "| 周 | run | 結末 | 分 | $ | 残り | ファイル |",
           "| --- | --- | --- | --- | --- | --- | --- |"]
    for r, m, c in zip(rows, mins, costs):
        out.append(f"| {r['n']} | {r.get('run_id')} | {r.get('outcome') or '読めない'} | {_num(m, '.0f')} | {_num(c, '.2f')} | "
                   f"{len(r.get('open_keys') or [])} | {r.get('files', 0)} |")
    out += ["", f"合計: {t_min:.0f} 分・{cost_text}"]
    if pick:
        out.append(f"最後の差分（元の基 {str(doc.get('original_base'))[:12]} → 周 {pick} の結果）: {final_diff or '書けていない'}")
        if apply_line:
            out.append(f"当てる: {apply_line}")
    else:
        out.append("最後の差分: 無い（結果の版が在り、止まりの記録の無い周が無い）")
    for r in rows:
        if r["n"] != pick and (r.get("stopped") or not r.get("result")) and r.get("diff_file"):
            out.append(f"採らなかった周 {r['n']}（{r.get('outcome') or '読めない'}）の差分: {r['diff_file']}")
    if held:
        out += ["", "次の周に運ばなかった下書きの行（人が見直してから依頼に使う）:", *[f"- {h}" for h in held]]
    out += ["", "周ごとの報告:", *[f"- 周 {r['n']}（run {r.get('run_id')}）: {r.get('report_file') or '無い'}" for r in rows]]
    return out


def load(path) -> dict:
    return json.loads(pathlib.Path(path).read_text(encoding="utf-8"))


def save(path, doc: dict) -> None:
    """一時のファイルに書いて os.replace で置く（carry.write と同じ書き方）"""
    carry.write(path, doc)


# ---------------------------------------------------------------- 殻の口（dev/use.sh が呼ぶ）
def _dir(a) -> pathlib.Path:
    return pathlib.Path(a.dir)


def _cli_new(a) -> int:
    env = dict(e.split("=", 1) for e in a.env or [] if "=" in e)
    doc = new(a.id, a.target, a.rev, a.rounds, a.budget, {"test_cmd": a.test_cmd, "tdd_suite": a.tdd_suite, "env": env},
              a.request)
    doc["rounds"].append(round_row(1, a.run_id, a.rev, a.request))
    _dir(a).mkdir(parents=True, exist_ok=True)
    save(_dir(a) / FILE, doc)
    print(_dir(a) / FILE)
    return 0


def _cli_of(a) -> int:
    """run id を周に持つ鎖の置き場（無ければ何も出さない）"""
    for p in sorted(pathlib.Path(a.home).glob(f"*/{FILE}")):
        got = _read_json(p)
        if isinstance(got, dict) and any(r.get("run_id") == a.run_id for r in got.get("rounds") or []):
            print(p.parent)
            return 0
    return 0


def _cli_record(a) -> int:
    doc = load(_dir(a) / FILE)
    row = next((r for r in doc["rounds"] if r.get("run_id") == a.run_id), None)
    if row is None:
        print(f"chain record: 鎖 {doc.get('id')} に run {a.run_id} の周が無い", file=sys.stderr)
        return 2
    if "outcome" not in row:   # 記録は 1 度だけ（wait・start・chain-resume のどれから来ても同じ行）
        run_row = _read_json(a.row) or {}
        got = _read_json(a.events) if a.events else None
        events = got.get("events") if isinstance(got, dict) else None
        row.update(recorded(row, board=a.board or None, diff=a.diff or None, result=a.result, minutes=minutes(run_row, events),
                            cost=report.spent(events), diff_ok=a.diff_ok == "1"))
        save(_dir(a) / FILE, doc)
    return 0


def _cli_verdict(a) -> int:
    doc = load(_dir(a) / FILE)
    if doc.get("stop"):
        got = {"go": "stop", "word": doc["stop"]["word"], "text": doc["stop"]["text"], "next_empty": False}
    else:
        got = verdict(doc, confirm=not a.no_confirm)
        if got["go"] == "stop":
            doc["stop"] = {"word": got["word"], "text": got["text"]}
            save(_dir(a) / FILE, doc)
    print("\t".join([got["go"], got["word"], got["text"], "1" if got["next_empty"] else "0"]))
    return 0


def _cli_next(a) -> int:
    doc = load(_dir(a) / FILE)
    last = doc["rounds"][-1]
    first = _read_json(doc["first_request"]) if doc.get("first_request") else None
    try:
        req, held = next_request(_read_json(last.get("next_file") or "") or {}, first, empty=a.empty == "1")
    except ValueError as e:
        print(f"chain next: 次の周の依頼を組めない: {' '.join(str(e).split())}", file=sys.stderr)
        return 2
    path = _dir(a) / request_name(last["n"] + 1)
    carry.write(path, req)
    print(path)
    return 0


def _cli_add(a) -> int:
    doc = load(_dir(a) / FILE)
    doc["rounds"].append(round_row(len(doc["rounds"]) + 1, a.run_id, a.rev, a.request))
    save(_dir(a) / FILE, doc)
    return 0


def _cli_last(a) -> int:
    """最後の周の「番号<TAB>run id<TAB>記録済みか（1・0）<TAB>結果の版<TAB>基の版<TAB>止めの語」"""
    doc = load(_dir(a) / FILE)
    r = doc["rounds"][-1]
    print("\t".join([str(r["n"]), r.get("run_id") or "", "1" if "outcome" in r else "0", r.get("result") or "",
                     r.get("base") or "", (doc.get("stop") or {}).get("word") or ""]))
    return 0


def _cli_final(a) -> int:
    """最後に採る周の「結果の版<TAB>元の基<TAB>最後の差分のパス」（採れる周が無ければ何も出さない）"""
    doc = load(_dir(a) / FILE)
    n = final_round(doc)
    if n is not None:
        r = next(x for x in doc["rounds"] if x["n"] == n)
        print("\t".join([r["result"], doc["original_base"], str(_dir(a) / FINAL_FILE)]))
    return 0


def _cli_report(a) -> int:
    doc = load(_dir(a) / FILE)
    final = _dir(a) / FINAL_FILE
    lines = report_lines(doc, final_diff=str(final) if final.is_file() else "", apply_line=a.apply_line)
    if doc.get("stop"):
        (_dir(a) / REPORT_FILE).write_text("\n".join([f"# 周の鎖の報告（{doc.get('id')}）", "", *lines]) + "\n",
                                           encoding="utf-8")
    print("\n".join(lines))
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="chain.py")
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("new")
    for k in ("--dir", "--id", "--target", "--rev", "--run-id"):
        c.add_argument(k, required=True)
    c.add_argument("--rounds", type=int, required=True)
    c.add_argument("--budget", type=float, default=None)
    c.add_argument("--request", default="")
    c.add_argument("--test-cmd", default="")
    c.add_argument("--tdd-suite", default="")
    c.add_argument("--env", action="append")
    c = sub.add_parser("of")
    c.add_argument("--home", required=True)
    c.add_argument("--run-id", required=True)
    c = sub.add_parser("record")
    for k in ("--dir", "--run-id", "--row"):
        c.add_argument(k, required=True)
    for k in ("--events", "--diff", "--result", "--board"):
        c.add_argument(k, default="")
    c.add_argument("--diff-ok", default="1")
    c = sub.add_parser("verdict")
    c.add_argument("--dir", required=True)
    c.add_argument("--no-confirm", action="store_true")
    c = sub.add_parser("next")
    c.add_argument("--dir", required=True)
    c.add_argument("--empty", default="0")
    c = sub.add_parser("add")
    for k in ("--dir", "--run-id", "--rev"):
        c.add_argument(k, required=True)
    c.add_argument("--request", default="")
    for name in ("last", "final"):
        sub.add_parser(name).add_argument("--dir", required=True)
    c = sub.add_parser("report")
    c.add_argument("--dir", required=True)
    c.add_argument("--apply-line", default="")
    a = ap.parse_args(argv)
    return {"new": _cli_new, "of": _cli_of, "record": _cli_record, "verdict": _cli_verdict, "next": _cli_next,
            "add": _cli_add, "last": _cli_last, "final": _cli_final, "report": _cli_report}[a.cmd](a)


if __name__ == "__main__":
    for _s in (sys.stdout, sys.stderr):   # Windows の既定 cp1252 で日本語の出力が落ちないように
        if hasattr(_s, "reconfigure"):
            _s.reconfigure(encoding="utf-8")
    sys.exit(main())
