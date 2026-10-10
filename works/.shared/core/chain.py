"""周の鎖の住処（考え chain。地図 docs/concepts.md）。層 L1: 標準ライブラリと carry・promptsection（報告の見出しの宣言）だけを import する。3.9 の文法で動く形。
殻（dev/use.sh）は `python3 -I chain.py <口>` でファイルとして呼び、旗を読んで鎖の考えをここに問うだけにする。

鎖は、1 回の `use.sh start --rounds N` が起こす、周ごとの run の並び。各周は今と同じ 1 本の run（1 run＝1 周）で、周の間の決め
（次を起こすか・次の依頼・止めの理由・最後の差分に採る周）と、鎖の控え <家>/chains/<鎖>/chain.json の形と、報告 chain.md の描きは
全部ここが持つ。git に触れる手続き（周の結果の commit・最後の差分）と Archon の起動は殻が持ち、結末の語と費用・時間の読みは
結末の住処 report.py が出した周の事実（report.round_facts）を受けるだけで、ここは結末の語も帳簿の欄の名も書かない。

- STOPS: 鎖の止めの語の表（run の中の止めの理由 stopby.REASONS とは別の考え。鎖の控えと chain.md にだけ出る）
- KIND_*: 結末の種（report.OUTCOME_KINDS の値）。closed＝直し済み・直す物が無い、halted＝止まった、human＝人の判断が要る、
  wait＝途中で落ちた（resume の後に続く）、open＝残りが在る（次の周へ進める）
- decide(doc, facts, budget=None) -> {act, word, text}: 見る順は 周の数 → 結末の種 → 人が要る → 進みが無い → 費用。
  facts が None なら起こした次の周の状態（pending）を見る。act は launch・wait・aborted・stop・follow
- next_request(prev_next_doc, first_doc) -> 次の周の依頼（carry.KEYS の形）・held_rows(next_doc) -> 運ばない下書きの行
- pick(rounds) -> (採る周, 採らずに名指す止まった周の並び)・render(doc) -> chain.md の本文
- new_doc・load・save・add_round: 鎖の控え（排他は <鎖>/chain.json.lock の fcntl.flock。board.py・scopes.py と同じ型）
- 殻の口: init・hold・launched・pid・bound・pending・plan・of-run・prep・step・pick・render
"""
import argparse
import contextlib
import datetime
import fcntl
import json
import os
import pathlib
import re
import shlex
import sys

sys.dont_write_bytecode = True
_HERE = str(pathlib.Path(__file__).resolve().parent)
if _HERE not in sys.path:   # 置き場を sys.path に持たない起こし方（python3 -I）でも同じ層の carry を読む
    sys.path.append(_HERE)

import carry  # noqa: E402
import promptsection  # noqa: E402

KIND_CLOSED, KIND_HALTED, KIND_HUMAN, KIND_WAIT, KIND_OPEN = "closed", "halted", "human", "wait", "open"
KINDS = (KIND_CLOSED, KIND_HALTED, KIND_HUMAN, KIND_WAIT, KIND_OPEN)

# 鎖の止めの語 → 1 行の文。run の中の止めの理由（stopby.REASONS。盤面の state.stop.by に残る）とは別の表
STOPS = {
    "rounds_reached": "指定の周の数に達した",
    "closed": "結末が閉じた（直し済みか、直す物が無い）",
    "halted": "run が止まった（止め札・人が関所で stop・線の止め・記録が検証器を通らない・差分を書けなかった）",
    "human": "人の判断が要る（関所で人に聞いたまま・見直していない下書きの行が残った）",
    "no_change": "進みが無い（周の結果の木が周の頭と同じ）",
    "same_items": "進みが無い（残りの行が前の周と同じ）",
    "budget": "次の周で費用の上限を越えうる",
    "cost_unread": "費用が読めない周が在り、上限を守れると言えない",
    "launch_unbound": "次の周の起動が run に結べないまま終わった",
}

FILE, LOCK, REPORT, FINAL = "chain.json", "chain.json.lock", "chain.md", "final.diff"
REPORT_HEAD = promptsection.Section("# 鎖 {cid} の報告", human="人が読む鎖の報告 chain.md の見出し。役の指示書には貼らない")
ENV_KEY = re.compile(r"WORKS_USE_[A-Z0-9_]+|WORKS_DESIGN_ONLY")   # 鎖の控えに持つ起動の環境の名（殻が渡す KEY=VALUE。値は読まない）
_HELD = False   # 殻が錠を持ったまま呼ぶ時は真（この口は錠を取り直さない）


# ---------------------------------------------------------------- 控え
def path(chain_dir) -> pathlib.Path:
    return pathlib.Path(chain_dir) / FILE


@contextlib.contextmanager
def locked(chain_dir):
    """<鎖>/chain.json.lock の排他（プロセスが終われば外れる。board.py・scopes.py と同じ fcntl.flock の型）"""
    if _HELD:
        yield
        return
    with open(pathlib.Path(chain_dir) / LOCK, "a", encoding="utf-8") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


def new_doc(chain_id: str, *, target: str, rounds: int, budget, request: str, test_cmd: str, tdd_suite: str,
            env: list, use_sh: str, pid: int, pr: int = 0, mark_from: str = "") -> dict:
    """鎖の控えの中身。1 周目の起動が pending（起こす前。pid は start の殻）。env は殻が渡した KEY=VALUE の並び。pr は 1 周目に名指した
    PR の番号（0 なら無し）: 次の周の起動の入力には使わず、次の依頼の pr 欄に載せて運ぶ"""
    bad = [e for e in env if "=" not in e or not ENV_KEY.fullmatch(e.split("=", 1)[0])]
    if bad:
        raise ValueError(f"起動の環境は WORKS_USE_* か WORKS_DESIGN_ONLY の KEY=VALUE（受けた値: {bad[0]!r}）")
    return {"id": chain_id, "target": target, "rounds_max": rounds, "budget_usd": budget, "first_request": request,
            "test_cmd": test_cmd, "tdd_suite": tdd_suite, "env": list(env), "use_sh": use_sh, "first_run": "", "pr": pr,
            "original_base": "", "rounds": [], "stop": None,
            "pending": {"round": 1, "mark": f"{chain_id}-1", "pid": pid, "launched": False, "run": "", "from": mark_from,
                        "request": request, "log": ""}}


def load(chain_dir) -> dict:
    doc = json.loads(path(chain_dir).read_text(encoding="utf-8"))
    if not isinstance(doc, dict) or not isinstance(doc.get("rounds"), list):
        raise ValueError(f"{path(chain_dir)} が鎖の控えの形でない")
    return doc


def save(chain_dir, doc: dict) -> None:
    carry.write(path(chain_dir), doc)


def update(chain_dir, fn) -> dict:
    """錠の下で控えを読み、fn(doc) で直して書く（fn は doc を直接変える）。返りは直した後の doc"""
    with locked(chain_dir):
        doc = load(chain_dir)
        fn(doc)
        save(chain_dir, doc)
        return doc


def add_round(chain_dir, row: dict) -> dict:
    """終わった周の行を足し、pending を外す。同じ run の行が在れば足さない（wait の打ち直し）"""
    def put(doc):
        if all(r.get("run") != row.get("run") for r in doc["rounds"]):
            doc["rounds"].append(row)
            doc["pending"] = None
    return update(chain_dir, put)


# ---------------------------------------------------------------- 決め
def _alive(pid) -> bool:
    """pid の process が居るか（信号 0。tree_run._answers と同じ問い）"""
    if not isinstance(pid, int) or isinstance(pid, bool) or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _stop(word: str, extra: str = "") -> dict:
    return {"act": "stop", "word": word, "text": STOPS[word] + (f"（{extra}）" if extra else "")}


def drafts_in(next_doc) -> list:
    """次の依頼の下書きの中の、下書きの印の在る行（findings と answers。人が見直して印を消すまで依頼の入口が拒む行）"""
    if not isinstance(next_doc, dict):
        return []
    return [r for key in (carry.FINDINGS, carry.ANSWERS) for r in (next_doc.get(key) or []) if carry.is_draft(r)]


def decide(doc: dict, facts, budget=None, *, alive=_alive) -> dict:
    """鎖の次の一手 {act, word, text}。facts が周の事実 {kind, same_tree, keys, next, cost, cost_read}（終わった周の行 doc["rounds"][-1]
    と同じ周）なら、見る順は 周の数 → 結末の種 → 人が要る → 進みが無い → 費用。どれにも当たらなければ launch。
    facts が None なら、起こした次の周の状態 doc["pending"] を見る: run が結ばれていれば follow、結ばれる前でも子の pid が生きていれば
    wait（launched かに依らない）、pid が死んで起動の印を Archon の前で置いていれば（launched が偽）launch（起こし直す）、
    Archon を起こした後に死んで run が無ければ launch_unbound で stop。budget は費用の上限 USD（無ければ控えの budget_usd）"""
    if facts is None:
        pend = doc.get("pending")
        if doc.get("stop"):
            return {"act": "stop", "word": doc["stop"]["word"], "text": doc["stop"]["text"]}
        if not pend:
            return {"act": "wait", "word": "", "text": "起こした周が無い"}
        if pend.get("run"):
            return {"act": "follow", "word": "", "text": pend["run"]}
        if alive(pend.get("pid")):
            return {"act": "wait", "word": "", "text": "次の周の起動が済むのを待つ"}
        if pend.get("launched"):
            return _stop("launch_unbound")
        return {"act": "launch", "word": "", "text": f"{pend.get('round')} 周目を起こし直す"}
    rows = doc.get("rounds") or []
    if len(rows) >= int(doc.get("rounds_max") or 0):
        return _stop("rounds_reached")
    kind = facts.get("kind")
    if kind == KIND_CLOSED:
        return _stop("closed")
    if kind == KIND_WAIT:
        return {"act": "aborted", "word": "", "text": "run が途中で落ちた（resume で続けた後の wait が続ける）"}
    if kind == KIND_HUMAN:
        return _stop("human")
    if kind != KIND_OPEN:
        return _stop("halted", "" if kind == KIND_HALTED else f"結末の種が読めない: {kind!r}")
    held = drafts_in(facts.get("next"))
    if held:
        return _stop("human", f"下書きの行 {len(held)} 件")
    if facts.get("same_tree"):
        return _stop("no_change")
    keys = set(facts.get("keys") or [])
    if keys and len(rows) >= 2 and keys == set(rows[-2].get("keys") or []):
        return _stop("same_items")
    limit = doc.get("budget_usd") if budget is None else budget
    if limit is not None:
        if any(not r.get("cost_read") or r.get("cost") is None for r in rows):
            return _stop("cost_unread")
        costs = [float(r["cost"]) for r in rows]
        if sum(costs) + max(costs) > float(limit):
            return _stop("budget", f"累計 ${sum(costs):.2f}・最大の周 ${max(costs):.2f}・上限 ${float(limit):.2f}")
    return {"act": "launch", "word": "", "text": f"{len(rows) + 1} 周目を起こす"}


def next_request(prev_next_doc, first_doc) -> dict:
    """次の周の依頼（carry.KEYS の形）。前の周の下書きでない findings と prior_failures、1 周目の依頼の answers・pr・issue を並べる。
    下書きの行は運ばない（held_rows が名指して chain.md の人が見る物へ回す）。first_doc が無ければ 1 周目の答えは無い"""
    prev = prev_next_doc if isinstance(prev_next_doc, dict) else {}
    first = carry.parts(first_doc) if first_doc is not None else {}
    out = {carry.FINDINGS: [r for r in prev.get(carry.FINDINGS) or [] if not carry.is_draft(r)],
           carry.PRIOR: list(prev.get(carry.PRIOR) or [])}
    for key in (carry.PR, carry.ISSUE, carry.ANSWERS):
        if first.get(key):
            out[key] = first[key]
    return out


def held_rows(next_doc) -> list:
    """運ばなかった下書きの行（findings の目的の外の所見と answers の答えの下書き）"""
    return drafts_in(next_doc)


def pick(rounds: list):
    """最後の周から戻り、止まりと言われていない（stopped が空で、結果の commit が在る）最初の周を採る。(採る周か None,
    採らずに飛ばした止まった周の並び)。止まった周は捨てずに名指す（chain.md が差分のパスを添える）"""
    skipped = []
    for r in reversed(rounds):
        if r.get("stopped"):
            skipped.append(r)
        elif r.get("result"):
            return r, skipped
    return None, skipped


# ---------------------------------------------------------------- 報告
def _cell(v, fmt="{}", none="読めない"):
    return none if v is None else fmt.format(v)


def render(doc: dict, *, final: bool = False) -> str:
    """chain.md の本文: 頭の 3 行（何が起きたか・止めた訳・人が見る物）、周ごとの表（周・run・結末・分・$・残り・ファイル）、合計、
    最後の差分と取り込み、人が要る時の手順。読めない費用は 0 と書かず「読めない」と名指す。final は final.diff が書けたか"""
    rows = doc.get("rounds") or []
    kept, skipped = pick(rows)
    stop = doc.get("stop") or {}
    target, use_sh, cid = doc.get("target", ""), doc.get("use_sh", ""), doc.get("id", "")
    held = [h for r in rows for h in (r.get("held_rows") or [])]
    notes = []
    if skipped:
        notes.append("止まった周 " + "・".join(f"周 {r['n']}（run {r['run']}。差分 {r.get('diff') or '無し'}）" for r in skipped)
                     + " は最後の差分に採らず、差分を残した")
    if held:
        notes.append(f"運ばなかった下書きの行 {len(held)} 件（見直して新しい依頼に入れる）")
    if kept and kept.get("kind") == KIND_OPEN and kept.get("r2"):
        notes.append("閉じていない（独立の目 R2 の作り直しが残る）")
    done = f"{len(rows)} 周のうち{('周 ' + str(kept['n']) + ' の結果までを最後の差分にした') if kept else '採れる周が無かった'}"
    lines = [REPORT_HEAD.format(cid=cid), "",
             f"- 何が起きたか: 指定 {doc.get('rounds_max')} 周のうち {done}（元の基 {(doc.get('original_base') or '—')[:12]}）",
             f"- 止めた訳: {stop.get('word', '（まだ止めていない）')}——{stop.get('text', '次の周を待っている')}" if stop
             else "- 止めた訳: まだ止めていない（次の周を待っている）",
             f"- 人が見る物: {'。'.join(notes) if notes else '無し'}", "",
             "| 周 | run | 結末 | 分 | $ | 残り | ファイル |", "| --- | --- | --- | --- | --- | --- | --- |"]
    for r in rows:
        lines.append("| {} | {} | {} | {} | {} | {} | {} |".format(
            r["n"], str(r.get("run", ""))[:8], r.get("outcome") or "（結末を読めない）", _cell(r.get("minutes"), "{:.0f}"),
            _cell(r.get("cost") if r.get("cost_read") else None, "{:.2f}"), len(r.get("keys") or []), r.get("files", 0)))
    minutes = [r["minutes"] for r in rows if r.get("minutes") is not None]
    costs = [r["cost"] for r in rows if r.get("cost_read") and r.get("cost") is not None]
    unread = sum(1 for r in rows if not r.get("cost_read") or r.get("cost") is None)
    lines += ["", "合計: {} 周・{} 分・{}".format(
        len(rows), f"{sum(minutes):.0f}" if minutes else "読めない",
        (f"${sum(costs):.2f}" if costs else "読めない") + (f"（費用が読めない周 {unread} 本を除く）" if costs and unread else ""))]
    if kept:
        lines += ["", f"最後の差分: {pathlib.Path(doc.get('dir', '')) / FINAL if doc.get('dir') else FINAL}"
                  + ("" if final else "（まだ書いていない）"),
                  f"取り込む: sh {use_sh} apply {target} {cid}"]
    if stop.get("word") == "human" or held:
        nxt = next((r.get("next_file") for r in reversed(rows) if r.get("next_file")), "")
        lines += ["", "続けずに、下書きを見直して新しい鎖を起こす（保留して続ける口は作らない）:",
                  f"1. 下書き {nxt or '（next-request.json）'} の draft・source の行を、採る物は印を消し、採らない物は消す",
                  f"2. 取り込むなら sh {use_sh} apply {target} {cid}",
                  f"3. 見直した依頼で sh {use_sh} start --rounds <周の数> {target} <依頼の JSON> を打つ"]
    for r in skipped:
        lines.append(f"止まった周 {r['n']} の差分: {r.get('diff') or '無し'}（{' '.join(str(x) for x in r['stopped'])}）")
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------- 殻の口
def _read(p, default=None):
    try:
        return json.loads(pathlib.Path(p).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def _count_files(diff: str) -> int:
    try:
        with open(diff, encoding="utf-8", errors="replace") as f:
            return sum(1 for ln in f if ln.startswith("diff --git "))
    except OSError:
        return 0


def build_row(pend: dict, facts: dict, *, diff: str, result: str, same_tree: bool, next_doc, base: str) -> dict:
    nxt = next_doc if isinstance(next_doc, dict) else {}
    return {"n": pend["round"], "run": pend["run"], "from": pend.get("from", ""), "base_rev": facts.get("base_rev") or base,
            "result": result, "same_tree": same_tree, "outcome": facts.get("outcome") or "", "kind": facts.get("kind"),
            "minutes": facts.get("minutes"), "cost": facts.get("cost"), "cost_read": bool(facts.get("cost_read")),
            "keys": [carry.row_key(r) for r in nxt.get(carry.FINDINGS) or [] if isinstance(r, dict) and not carry.is_draft(r)],
            "held_rows": held_rows(nxt), "files": _count_files(diff), "r2": facts.get("r2") or 0,
            "stopped": facts.get("stopped"), "diff": diff if os.path.isfile(diff) else "", "report": facts.get("report_file") or "",
            "next_file": facts.get("next_file") or ""}


def _step(a) -> str:
    """終わった周を控えに足して次の一手を決め、殻が読む 1 行を返す。launch\\t<周>\\t<印> / wait\\t<文> / stop\\t<語>\\t<文> /
    follow\\t<run>。同じ run を 2 度渡されても周を足さず、控えの今の姿で決め直す（二重に起こさない）"""
    d = a.dir
    with locked(d):
        doc = load(d)
        if all(r.get("run") != a.run for r in doc["rounds"]):
            pend = doc.get("pending")
            if not pend or pend.get("run") != a.run:
                return f"none\trun {a.run} は鎖 {doc['id']} の起こした周でない"
            facts = _read(a.facts, {}) or {}
            if facts.get("kind") == KIND_WAIT:   # 途中で落ちた周は足さず、pending も変えない（resume の後の wait が続ける）
                return "aborted\t" + decide(doc, {"kind": KIND_WAIT})["text"]
            from_rev = pend.get("from", "")
            why = a.unwritten or facts.get("error") or ""   # 差分か周の事実を書けなかった周は結果を作らず、halted で止める
            present = bool(a.diff) and os.path.isfile(a.diff)
            diff_made = bool(a.result) and present and not why
            result = a.result if diff_made else from_rev
            same = bool(why) or not present or (a.result_tree == a.from_tree and bool(a.from_tree))
            nxt = _read(facts.get("next_file") or "", None)
            row = build_row(pend, facts, diff=a.diff, result=result if diff_made else "", same_tree=same, next_doc=nxt,
                            base=doc.get("original_base", ""))
            if pend["round"] == 1:
                doc["original_base"] = row["base_rev"]
            doc["rounds"].append(row)
            doc["pending"] = None
            if why:
                got = _stop("halted", why)
                row["kind"] = KIND_HALTED
            else:
                got = decide(doc, {**row, "next": nxt})
            if got["act"] == "launch":
                first = _read(doc["first_request"], None) if doc.get("first_request") else None
                if doc.get("pr"):   # 1 周目に名指した PR は依頼の pr 欄として運ぶ（次の周の入力には使わない）
                    first = dict(first) if isinstance(first, dict) else {carry.FINDINGS: list(first or [])}
                    first[carry.PR] = sorted(set(first.get(carry.PR) or []) | {doc["pr"]})
                req = next_request(nxt, first)
                req_file = ""
                if any(req.get(k) for k in req):
                    req_file = str(pathlib.Path(d) / f"round-{pend['round'] + 1}-request.json")
                    carry.write(req_file, req)
                doc["pending"] = {"round": pend["round"] + 1, "mark": f"{doc['id']}-{pend['round'] + 1}", "pid": None,
                                  "launched": False, "run": "", "from": result, "request": req_file, "log": ""}
        else:
            got = decide(doc, None)
        if got["act"] == "stop" and not doc.get("stop"):
            doc["stop"] = {"word": got["word"], "text": got["text"]}
            doc["pending"] = None
        save(d, doc)
    if got["act"] == "launch":
        return f"launch\t{doc['pending']['round']}\t{doc['pending']['mark']}"
    if got["act"] == "stop":
        return f"stop\t{got['word']}\t{got['text']}"
    if got["act"] == "follow":
        return f"follow\t{got['text']}"
    return f"wait\t{got['text']}"


def _find(home: str, run: str):
    for p in sorted(pathlib.Path(home, "chains").glob("*/" + FILE)):
        doc = _read(p, {})
        if isinstance(doc, dict) and (run == (doc.get("pending") or {}).get("run")
                                      or any(r.get("run") == run for r in doc.get("rounds") or [])):
            return doc.get("id")
    return None


def main(argv=None) -> int:
    global _HELD
    ap = argparse.ArgumentParser(prog="chain.py")
    ap.add_argument("--held", action="store_true", help="殻が錠を持ったまま呼ぶ（錠を取り直さない）")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("init")
    for k in ("--dir", "--id", "--target", "--request", "--test-cmd", "--tdd-suite", "--use-sh"):
        s.add_argument(k, required=True)
    s.add_argument("--rounds", type=int, required=True)
    s.add_argument("--budget", default="")
    s.add_argument("--pid", type=int, required=True)
    s.add_argument("--first-pr", type=int, default=0)
    s.add_argument("--env", action="append", default=[])
    s = sub.add_parser("hold")
    s.add_argument("fd", type=int)
    s = sub.add_parser("launched")
    s.add_argument("--dir", required=True)
    s.add_argument("--from", dest="from_rev", required=True)
    s = sub.add_parser("pid")
    s.add_argument("--dir", required=True)
    s.add_argument("--pid", type=int, required=True)
    s.add_argument("--log", default="")
    s = sub.add_parser("bound")
    s.add_argument("--dir", required=True)
    s.add_argument("--run", required=True)
    for name in ("pending", "plan", "pick", "render"):
        s = sub.add_parser(name)
        s.add_argument("--dir", required=True)
    s = sub.add_parser("of-run")
    s.add_argument("--home", required=True)
    s.add_argument("--run", required=True)
    s = sub.add_parser("prep")
    s.add_argument("--dir", required=True)
    s.add_argument("--run", required=True)
    s.add_argument("--facts", required=True)
    s = sub.add_parser("step")
    for k in ("--dir", "--run", "--facts"):
        s.add_argument(k, required=True)
    s.add_argument("--diff", default="")
    s.add_argument("--result", default="")
    s.add_argument("--result-tree", default="")
    s.add_argument("--from-tree", default="")
    s.add_argument("--unwritten", default="")
    a = ap.parse_args(argv)
    _HELD = a.held
    try:
        return _run(a)
    except (OSError, ValueError, KeyError) as e:
        print(f"chain {a.cmd}: {' '.join(str(e).split())}", file=sys.stderr)
        return 2


def _run(a) -> int:
    if a.cmd == "hold":
        fcntl.flock(a.fd, fcntl.LOCK_EX)
        return 0
    if a.cmd == "init":
        d = pathlib.Path(a.dir)
        budget = float(a.budget) if a.budget else None
        d.mkdir(parents=True, exist_ok=True)
        save(d, new_doc(a.id, target=a.target, rounds=a.rounds, budget=budget, request=a.request, test_cmd=a.test_cmd,
                        tdd_suite=a.tdd_suite, env=a.env, use_sh=a.use_sh, pid=a.pid, pr=a.first_pr))
        return 0
    if a.cmd == "of-run":
        got = _find(a.home, a.run)
        if got:
            print(got)
        return 0 if got else 1
    if a.cmd == "launched":
        def mark(doc):
            doc["pending"]["launched"] = True
            doc["pending"]["from"] = doc["pending"].get("from") or a.from_rev
        update(a.dir, mark)
        return 0
    if a.cmd == "pid":
        def put(doc):
            doc["pending"]["pid"] = a.pid
            doc["pending"]["log"] = a.log
        update(a.dir, put)
        return 0
    if a.cmd == "bound":
        def bind(doc):
            doc["pending"]["run"] = a.run
            if doc["pending"]["round"] == 1:
                doc["first_run"] = a.run
        update(a.dir, bind)
        return 0
    doc = load(a.dir)
    doc["dir"] = str(a.dir)
    if a.cmd == "pending":
        p = doc.get("pending") or {}
        last = (doc.get("rounds") or [{}])[-1].get("run", "")
        print("\t".join([str(p.get("run", "")), str(p.get("pid") or ""), "1" if p.get("launched") else "", str(p.get("round", "")),
                         "1" if doc.get("stop") else "", str(p.get("log", "")), str(last)]))
        return 0
    if a.cmd == "plan":
        # 次の周の start --chain-next が読む: 起動の環境と、対象・依頼・test_cmd・tdd_suite・起動の基・差分の根・起動の印・1 周目の run
        p = doc.get("pending")
        if not p or p.get("round", 1) < 2:
            print("次の周の pending が無い", file=sys.stderr)
            return 2
        for e in doc.get("env") or []:
            k, v = e.split("=", 1)
            if not ENV_KEY.fullmatch(k):   # 殻が eval する行なので、控えが書き換わっていても名の形を外さない
                raise ValueError(f"起動の環境の名が WORKS_USE_* か WORKS_DESIGN_ONLY でない（{k!r}）")
            print(f"export {k}={shlex.quote(v)}")
        for k, v in (("CN_REQUEST", p.get("request", "")), ("CN_TEST_CMD", doc["test_cmd"]),
                     ("CN_TDD_SUITE", doc["tdd_suite"]), ("CN_FROM", p["from"]), ("CN_BASE", doc["original_base"]),
                     ("CN_MARK", p["mark"]), ("CN_ROUND", str(p["round"])), ("CN_FIRST_RUN", doc.get("first_run", ""))):
            print(f"{k}={shlex.quote(str(v))}")
        return 0
    if a.cmd == "prep":
        if any(r.get("run") == a.run for r in doc["rounds"]):   # wait の打ち直し: 周は足してある（結果も作らない）
            print("done\t\t")
            return 0
        p = doc.get("pending") or {}
        if p.get("run") != a.run:
            print(f"run {a.run} は鎖 {doc['id']} の起こした周でない", file=sys.stderr)
            return 2
        facts = _read(a.facts, {}) or {}
        print(f"{p.get('round')}\t{p.get('from', '')}\t{facts.get('base_rev') or doc.get('original_base', '')}")
        return 0
    if a.cmd == "step":
        print(_step(a))
        return 0
    if a.cmd == "pick":
        kept, _ = pick(doc["rounds"])
        if kept:
            print(f"{kept['n']}\t{kept['run']}\t{kept['result']}\t{doc.get('original_base', '')}")
        return 0
    if a.cmd == "render":
        final = (pathlib.Path(a.dir) / FINAL).is_file()
        text = render(doc, final=final)
        out = pathlib.Path(a.dir) / REPORT
        out.write_text(text, encoding="utf-8")
        sys.stdout.write(text)
        return 0
    return 2


if __name__ == "__main__":
    for _s in (sys.stdout, sys.stderr):   # Windows の既定 cp1252 で日本語の出力が落ちないように
        if hasattr(_s, "reconfigure"):
            _s.reconfigure(encoding="utf-8")
    sys.exit(main())
