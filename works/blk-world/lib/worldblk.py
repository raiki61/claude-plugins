"""世界の解のブロックの中身（計画 docs/plans/2026-10-09-world-solution.md の 5.2 節・5.4 節・5.5 節。節の口は scripts/*.py）。

依頼の行ごとに、依頼の解き方と対象の名を外した問題の類に言い直させ（言い直す役）、世の中の定石の抜き書きを集めさせ（集める役）、
抜き書きを機械が取り直した本文で照らし（lib/worldcheck）、類ごとの定石と依頼の解き方との比べを判断させ（判断する役）、
行を WORLD_FILE（core の worldmark）に書く。ブロックの外の物は名指さない: 入力は依頼のファイル（findings の配列か
{findings, …} の形）・目的の文のファイル（任意。{purpose_text, means?} の JSON。means は依頼の解き方の文の配列）・run をまたぐ
控えの置き場（任意。空なら包みの家の下）・web の切り替え（on・off）。

置き場は $ARTIFACTS_DIR の下の OUT_DIR（盤面の外。intake が置き直す）。
- intake.json: {findings, purpose_text, means, cached: [{class_id, problem, activity}], web, cache_root, reason}
- classes.json（言い直す役の受け付けが通した行）: [{finding, where, class_id, problem, activity, proposed, queries, wording, cached}]
- plan.json（控えを引いた後）: {skipped, over, taken, cached: {類の id: 控え}, collect, web}
- verified.json（照らした後）: {kept, dropped, offline, over_excerpts, events_read, note}
- judge-input.json・judged.json（判断する役の材料と、受け付けが通した行）
- 輪の控え <役>-state.json: {attempt, reason, status: pending|ok|gave_up}。拒めば同じ会話で出し直させ、MAX_ATTEMPTS 回目の拒否で
  輪を抜ける（線を止めない。出口の status: failed と reason に残す）

上限（5.4 節）: 類は MAX_CLASSES・検索語は類ごとに MAX_QUERIES・抜き書きは類ごとに MAX_EXCERPTS（越えた分は頭から取り、取らなかった
数を残す）。控えは問題の類ごとに 1 本（名は類の id。類の id は問題の類の文を正規化した字の hash で、対象の名を持たないので対象を
またいで使ってよい）。期限は TTL。knowledge の行は控えに足さない。網に出ない run（web が off・集める役が何も返さない・取り直しが
全部網に届かない）も止めず、判断する役は抜き書き無しで知識だけから行を書く（basis: knowledge）。
"""
from __future__ import annotations

import hashlib
import json
import pathlib
import sys

_CORE = pathlib.Path(__file__).resolve().parents[2] / ".shared" / "core"
if str(_CORE) not in sys.path:
    sys.path.insert(0, str(_CORE))
import carry  # noqa: E402  （依頼の容器の形の住処）
import script_io  # noqa: E402  （切り替えの入力の語 on・off の読み口）
import impact  # noqa: E402  （文書のファイルの見分け）
import webget  # noqa: E402  （網の口と run をまたぐ控え）
import worldmark  # noqa: E402  （世界の解の行の住処）
import worldcheck  # noqa: E402  （同じ lib の照らし）

OUT_DIR = "world"
INTAKE, CLASSES, PLAN, VERIFIED, JUDGE_INPUT, JUDGED = (
    "intake.json", "classes.json", "plan.json", "verified.json", "judge-input.json", "judged.json")
STATE = "{role}-state.json"
PROMPT = "{role}-prompt-{n}.md"
CLASSES_ROLE, JUDGE_ROLE = "classes", "judge"
MAX_CLASSES, MAX_QUERIES, MAX_EXCERPTS = 5, 3, 6
MAX_ATTEMPTS = 3
MIN_CHALLENGE = 20   # differs の challenge の字の下限
CACHED_SHOWN = 50    # 言い直す役に見せる控えの類の数の上限（新しい名の順でなく名の順の頭から）
TTL = 90 * 24 * 3600   # 控えの期限（構造の実測の窓と同じ 90 日）
CACHE_SUB = "world"    # 包みの家の下の控えの置き場
SCHEMA = "works-world/1"
MAX_BODY = 2 * 1024 * 1024
HEADERS = {"User-Agent": "works-world/1", "Accept": "text/html, text/plain;q=0.9, */*;q=0.5"}
REJECTED_HEAD = "## 前の回の受け付けが拒んだ理由"


class WorldGap(Exception):
    """置き場の控えが無い・読めない（配線の誤り。節は標準エラーに 1 行出して 1）"""


# ---------------------------------------------------------------- 置き場
def _read(path, default=None):
    try:
        return json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError):
        return default


def _write(path, doc) -> None:
    pathlib.Path(path).write_text(json.dumps(doc, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


def _need(out, name):
    got = _read(pathlib.Path(out) / name)
    if got is None:
        raise WorldGap(f"{pathlib.Path(out) / name} が無いか読めない")
    return got


def store(root) -> webget.Store:
    return webget.Store(pathlib.Path(root) if root else None, SCHEMA, TTL)


def class_id(problem: str) -> str:
    """問題の類の id（正規化した文の sha256 の頭 12 字）。同じ字の類は同じ id になる"""
    return "w-" + hashlib.sha256(worldcheck.normalize(problem).encode("utf-8")).hexdigest()[:12]


def _name(cid: str) -> str:
    return f"{cid}.json"


# ---------------------------------------------------------------- 入口
def _findings(request, cwd) -> list:
    if not request:
        return []
    p = pathlib.Path(request)
    p = p if p.is_absolute() else pathlib.Path(cwd) / p
    try:
        doc = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError) as e:
        raise ValueError(f"依頼のファイル {request} が読めない（{type(e).__name__}: {e}）") from None
    rows = carry.parts(doc)[carry.FINDINGS]
    bad = [i for i, f in enumerate(rows, 1) if not isinstance(f, dict) or not isinstance(f.get("where"), str)
           or not isinstance(f.get("text"), str)]
    if bad:
        raise ValueError(f"依頼の行 {bad} が {{where, text}} の形でない")
    return rows


def _purpose(path, cwd) -> tuple:
    if not path:
        return "", []
    p = pathlib.Path(path)
    doc = _read(p if p.is_absolute() else pathlib.Path(cwd) / p)
    if not isinstance(doc, dict):
        raise ValueError(f"目的の文のファイル {path} が JSON のオブジェクトとして読めない")
    means = doc.get("means") if isinstance(doc.get("means"), list) else []
    return str(doc.get("purpose_text") or ""), [m for m in means if isinstance(m, str) and m.strip()]


def cached_classes(root, now: float) -> list:
    st = store(root)
    out = []
    for name in st.names(now, ("ok",))[:CACHED_SHOWN]:
        doc = st.get(name, now, ("ok",)) or {}
        if doc.get("class_id") and doc.get("problem"):
            out.append({"class_id": doc["class_id"], "problem": doc["problem"], "activity": doc.get("activity", "")})
    return out


def intake(out, *, request: str, purpose_file: str, cache_root: str, web, cwd, env, now: float) -> dict:
    """置き場を置き直して intake.json を書く。返り {due, findings, reason}（due は言い直す役を起こすか）。依頼や目的の文が読めない
    時も止めない（reason に残し、due は偽。出口が status: failed にする）"""
    out = pathlib.Path(out)
    out.mkdir(parents=True, exist_ok=True)
    for p in out.iterdir():
        if p.is_file():
            p.unlink()
    root = cache_root or (str(webget.shared_root(env, CACHE_SUB) or ""))
    doc = {"findings": [], "purpose_text": "", "means": [], "cached": [], "web": True, "cache_root": root, "reason": ""}
    try:
        doc["web"] = _switch(web)
        doc["findings"] = _findings(request, cwd)
        doc["purpose_text"], doc["means"] = _purpose(purpose_file, cwd)
    except ValueError as e:
        doc["reason"] = " ".join(str(e).split())
    doc["cached"] = cached_classes(root, now) if root else []
    _write(out / INTAKE, doc)
    return {"due": bool(doc["findings"]) and not doc["reason"], "findings": len(doc["findings"]), "reason": doc["reason"]}


def _switch(web) -> bool:
    return script_io.switch_on(web, "web")


# ---------------------------------------------------------------- 輪の控え
def loop_state(out, role) -> dict:
    got = _read(pathlib.Path(out) / STATE.format(role=role), {})
    return got if isinstance(got, dict) else {}


def _put_state(out, role, doc) -> None:
    _write(pathlib.Path(out) / STATE.format(role=role), doc)


def _prep(out, role, body: str) -> dict:
    st = loop_state(out, role)
    n = int(st.get("attempt") or 0) + 1
    lines = []
    if st.get("reason"):
        lines += [REJECTED_HEAD, "", st["reason"], "", "ここを直した返答を丸ごと出し直せ（直した所だけを返すな）。", ""]
    prompt = "\n".join(lines) + body
    path = pathlib.Path(out) / PROMPT.format(role=role, n=n)
    path.write_text(prompt, encoding="utf-8")
    _put_state(out, role, {"attempt": n, "reason": st.get("reason") or "", "status": "pending"})
    return {"prompt": prompt, "prompt_file": str(path), "attempt": n}


def _verdict(out, role, bad: list) -> dict:
    st = loop_state(out, role)
    n = int(st.get("attempt") or 1)
    if bad:
        reason = " / ".join(bad)
        give_up = n >= MAX_ATTEMPTS
        _put_state(out, role, {"attempt": n, "reason": reason, "status": "gave_up" if give_up else "pending"})
        return {"ok": False, "done": give_up, "give_up": give_up, "reason": reason, "attempt": n}
    _put_state(out, role, {"attempt": n, "reason": "", "status": "ok"})
    return {"ok": True, "done": True, "give_up": False, "reason": "", "attempt": n}


# ---------------------------------------------------------------- 言い直す役
def _finding_lines(findings) -> list:
    out = []
    for i, f in enumerate(findings, 1):
        out.append(f"{i}. where: {f.get('where')}")
        out += [f"   {k}: {f[k]}" for k in ("text", "mechanism", "measured", "false_positive_if") if isinstance(f.get(k), str)]
    return out


def classes_prep(out) -> dict:
    doc = _need(out, INTAKE)
    lines = ["## 依頼の行（機械が依頼のファイルから抜いた物。これが渡された物の全部）", "", *_finding_lines(doc["findings"]), "",
             "## 目的の文", "", doc["purpose_text"] or "（渡されていない）", ""]
    if doc["means"]:
        lines += ["依頼が示した解き方（目的の文から分けた物）:", *[f"- {m}" for m in doc["means"]], ""]
    lines += ["## 控えの類（前の run が定石を確かめた問題の類。同じ類なら class_id にその id を書く）", ""]
    lines += [f"- {c['class_id']}: {c['problem']}（作業: {c['activity']}）" for c in doc["cached"]] or ["（無い）"]
    lines += ["", "## 返し方", "",
              f"- classes に、依頼の行の全部へ 1 つずつ（finding は上の行の番号 1〜{len(doc['findings'])}）",
              "- problem: 依頼の行を、依頼が示した解き方と対象の名（パス・ファイル・関数・欄・環境変数・部品の名・run の id）を外し、"
              "実務家がする作業の言葉で言い直した問題の類の 1 文",
              "- activity: 作業の種類の名（短い名）",
              "- proposed: 依頼が示した解き方（上の『依頼が示した解き方』と依頼の文から写す。示していなければ空）",
              f"- queries: 世の中の実務家がこの類をどう解いているか（実践・慣習・標準）を問う検索語（1〜{MAX_QUERIES} 本。対象の名を入れない。"
              "語の直しだけの行は空でよい）",
              "- wording: 文書の語・誤字・言い回しだけを直す行なら真（where が全部文書のファイルの行だけ。それ以外は偽）",
              "- class_id: 上の控えの類と同じ類ならその id。新しい類なら空",
              "- 機械は problem・activity・queries に依頼の行から取った識別子が在れば、その識別子を名指して拒む"]
    return _prep(out, CLASSES_ROLE, "\n".join(lines) + "\n")


def class_problems(doc: dict, reply) -> list:
    rows = reply.get("classes") if isinstance(reply, dict) else None
    if not isinstance(rows, list):
        return ["返答に classes（行の配列）が無い"]
    findings = doc["findings"]
    banned = worldcheck.banned_tokens(findings)
    known = {c["class_id"] for c in doc["cached"]}
    seen, out = [], []
    for i, r in enumerate(rows):
        if not isinstance(r, dict):
            out.append(f"classes[{i}] が JSON のオブジェクトでない")
            continue
        n = r.get("finding")
        head = f"classes[{i}]（依頼の行 {n}）"
        if not isinstance(n, int) or isinstance(n, bool) or not 1 <= n <= len(findings):
            out.append(f"{head}: finding は依頼の行の番号 1〜{len(findings)}")
            continue
        if n in seen:
            out.append(f"{head}: 同じ依頼の行の 2 つ目")
        seen.append(n)
        for key in ("problem", "activity"):
            if not isinstance(r.get(key), str) or not r[key].strip():
                out.append(f"{head}: {key} が空")
        if not isinstance(r.get("proposed"), str):
            out.append(f"{head}: proposed が字でない（示していなければ空の字）")
        qs = r.get("queries")
        wording = r.get("wording") is True
        if not isinstance(qs, list) or not all(isinstance(q, str) and q.strip() for q in qs) or len(qs) > MAX_QUERIES:
            out.append(f"{head}: queries は空でない字の配列（{MAX_QUERIES} 本まで）")
            qs = []
        elif not qs and not wording:
            out.append(f"{head}: queries が無い（語の直しだけの行のほかは 1 本以上）")
        cid = r.get("class_id", "")
        if not isinstance(cid, str) or (cid and cid not in known):
            out.append(f"{head}: class_id は控えの類の id か空（在るのは {sorted(known) or '無し'}）")
        for key, text in [("problem", r.get("problem")), ("activity", r.get("activity"))] + [("queries", q) for q in qs]:
            hit = worldcheck.text_problems(text, banned)
            if hit:
                out.append(f"{head}: {key} に依頼の行の識別子 {hit} が在る（対象の名を外し、作業の言葉で言い直せ）")
        if wording:
            where = findings[n - 1]["where"]
            paths = worldmark.where_paths(where)
            if not paths or not all(impact.is_doc(p) for p in paths):
                out.append(f"{head}: wording は where が全部文書のファイルの行だけ（where: {where}）")
    missing = [n for n in range(1, len(findings) + 1) if n not in seen]
    if missing:
        out.append(f"行の無い依頼の行: {missing}（全部の行に 1 つずつ）")
    return out


def classes_accept(out, reply) -> dict:
    doc = _need(out, INTAKE)
    bad = class_problems(doc, reply)
    if not bad:
        cached = {c["class_id"]: c for c in doc["cached"]}
        by_text = {worldcheck.normalize(c["problem"]): c["class_id"] for c in doc["cached"]}
        rows = []
        for r in sorted(reply["classes"], key=lambda x: x["finding"]):
            cid = r.get("class_id") or by_text.get(worldcheck.normalize(r["problem"])) or class_id(r["problem"])
            rows.append({"finding": r["finding"], "where": doc["findings"][r["finding"] - 1]["where"], "class_id": cid,
                         "problem": r["problem"].strip(), "activity": r["activity"].strip(), "proposed": r["proposed"].strip(),
                         "queries": [q.strip() for q in r["queries"]], "wording": r.get("wording") is True,
                         "cached": cid in cached})
        _write(pathlib.Path(out) / CLASSES, rows)
    return _verdict(out, CLASSES_ROLE, bad)


# ---------------------------------------------------------------- 控えを引く
def plan(out, now: float) -> dict:
    """言い直しの行から、飛ばす行・取る類（MAX_CLASSES まで）・控えに当たった類・集める類を決めて plan.json に書く。
    返り {collect_due, judge_due, prompt}（prompt は集める役の指示書。集めない時は空）"""
    out = pathlib.Path(out)
    doc = _need(out, INTAKE)
    rows = _read(out / CLASSES)
    if not isinstance(rows, list) or loop_state(out, CLASSES_ROLE).get("status") != "ok":
        _write(out / PLAN, {"skipped": [], "over": [], "taken": [], "cached": {}, "collect": [], "web": doc["web"]})
        return {"collect_due": False, "judge_due": False, "prompt": ""}
    st = store(doc["cache_root"])
    skipped = [r["finding"] for r in rows if r["wording"]]
    taken, over = [], []
    for r in rows:
        if r["wording"]:
            continue
        if r["class_id"] not in taken and len(taken) >= MAX_CLASSES:
            over.append(r["finding"])
        elif r["class_id"] not in taken:
            taken.append(r["class_id"])
    hits = {cid: got for cid in taken if (got := st.get(_name(cid), now, ("ok",))) is not None}
    collect = [cid for cid in taken if cid not in hits] if doc["web"] else []
    _write(out / PLAN, {"skipped": skipped, "over": over, "taken": taken, "cached": hits, "collect": collect, "web": doc["web"]})
    return {"collect_due": bool(collect), "judge_due": bool(taken), "prompt": collect_prompt(rows, collect) if collect else ""}


def collect_prompt(rows, collect) -> str:
    first = {}
    for r in rows:
        first.setdefault(r["class_id"], r)
    lines = ["## 問題の類（機械が言い直しの返答から抜いた物。これが渡された物の全部）", ""]
    for cid in collect:
        r = first[cid]
        lines += [f"- class: {cid}", f"  - 問題の類: {r['problem']}", f"  - 作業: {r['activity']}",
                  *[f"  - 検索語: {q}" for q in r["queries"]]]
    lines += ["", "## 返し方", "",
              "- excerpts に {class, url, excerpt} を並べる。class は上の class の字のまま",
              f"- 抜き書きは類ごとに {MAX_EXCERPTS} まで。{worldcheck.MIN_EXCERPT} 字以上で、取得した本文の文を字のまま写す",
              "- url は取得の道具で本当に取得したページだけ（検索の結果の一覧に出ただけの URL は書かない）"]
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------- 照らす
def _cap(excerpts, allowed) -> tuple:
    """類ごとに頭から MAX_EXCERPTS まで（上の類の外の行は落とす）。(取った行, 取らなかった数)"""
    took, count, over = [], {}, 0
    for e in excerpts if isinstance(excerpts, list) else []:
        if not isinstance(e, dict) or e.get("class") not in allowed:
            continue
        if count.get(e["class"], 0) >= MAX_EXCERPTS:
            over += 1
            continue
        count[e["class"]] = count.get(e["class"], 0) + 1
        took.append(e)
    return took, over


def collect_classes(out) -> list:
    """集める類の id（控えを引いた後。集めない周は空）"""
    return list(_need(out, PLAN)["collect"])


def verify(out, reply, fetched, get) -> dict:
    """集める役の返答 reply（無い・形の違う物は抜き書き無し）を照らして verified.json に書く。fetched は役が取得した URL の集合
    （出来事が読めなければ None）。返り {kept, dropped, offline}"""
    out = pathlib.Path(out)
    pl = _need(out, PLAN)
    excerpts = reply.get("excerpts") if isinstance(reply, dict) else None
    note = "" if isinstance(excerpts, list) or not pl["collect"] else "集める役の返答が無い（落ちたか走らなかった）"
    took, over = _cap(excerpts, set(pl["collect"]))
    got = worldcheck.verify(took, fetched or set(), get)
    if fetched is None and took:
        note = (note + "／" if note else "") + "役の取得の記録（流れの道具の出来事）が読めない（抜き書きは全部落ちる）"
    doc = {**got, "over_excerpts": over, "events_read": fetched is not None, "note": note}
    _write(out / VERIFIED, doc)
    return {"kept": len(got["kept"]), "dropped": len(got["dropped"]), "offline": got["offline"]}


# ---------------------------------------------------------------- 判断する役
def _judge_rows(out) -> list:
    """判断する役に渡す行（取った類の、飛ばさない依頼の行ごと）。抜き書きは控えに当たった類は控えの物、ほかは照らして残った物"""
    out = pathlib.Path(out)
    rows, pl = _need(out, CLASSES), _need(out, PLAN)
    kept = (_read(out / VERIFIED) or {}).get("kept") or []
    sources, n = {}, 0
    for cid in pl["taken"]:
        if cid in pl["cached"]:
            got = []
            for s in pl["cached"][cid].get("sources") or []:
                n += 1
                got.append({"id": f"c{n}", "url": s.get("url"), "excerpt": s.get("excerpt")})
            sources[cid] = got
        else:
            sources[cid] = [{"id": k["id"], "url": k["url"], "excerpt": k["excerpt"]} for k in kept if k.get("class") == cid]
    return [{**{k: r[k] for k in ("finding", "where", "class_id", "problem", "activity", "proposed")},
             "cached": r["class_id"] in pl["cached"], "sources": sources[r["class_id"]],
             "cached_practice": pl["cached"].get(r["class_id"], {}).get("practice", "")}
            for r in rows if not r["wording"] and r["class_id"] in pl["taken"]]


def judge_prep(out) -> dict:
    out = pathlib.Path(out)
    if not (out / JUDGE_INPUT).is_file():
        _write(out / JUDGE_INPUT, _judge_rows(out))
    rows = _need(out, JUDGE_INPUT)
    lines = ["## 依頼の行ごとの問題の類と抜き書き（機械が照らして残した物。これが渡された物の全部）", ""]
    for r in rows:
        lines += [f"### 依頼の行 {r['finding']}（類 {r['class_id']}）", "", f"- 問題の類: {r['problem']}", f"- 作業: {r['activity']}",
                  f"- 依頼の解き方: {r['proposed'] or '（示していない）'}"]
        if r["cached_practice"]:
            lines.append(f"- 前の run が確かめた定石: {r['cached_practice']}")
        lines += [f"- 抜き書き {s['id']}: {s['url']}「{s['excerpt']}」" for s in r["sources"]] or ["- 抜き書き: 無い（網で確かめられなかった）"]
        lines.append("")
    lines += ["## 返し方", "",
              "- rows に、上の依頼の行の全部へ 1 つずつ（finding は上の番号）",
              "- practice: 世の中の実務家がこの類を決まってどう解いているか（1〜3 文。対象の名を書かない）",
              "- sources: practice の根拠にした抜き書きの id（その依頼の行の抜き書きだけ）。抜き書きを使わないなら空",
              f"- basis: sources が 1 つ以上なら {worldmark.WEB}、空なら {worldmark.KNOWLEDGE}（抜き書きの無い行は知識だけで書く）",
              "- applies: この依頼にどう当たるか。not_applies: どこには当たらないか（当たらない依頼なら applies は空）",
              f"- verdict: 依頼の解き方が定石と同じなら {worldmark.SAME}、違えば {worldmark.DIFFERS}、依頼が解き方を示していなければ "
              f"{worldmark.NONE}",
              f"- challenge: {worldmark.DIFFERS} の時だけ「依頼は X、定石は Y。…でない限り Y を選ぶ」の形の文（{MIN_CHALLENGE} 字以上）。"
              "ほかは空",
              "- 機械は practice に依頼の行から取った識別子が在れば拒む"]
    return _prep(out, JUDGE_ROLE, "\n".join(lines) + "\n")


def judge_problems(rows: list, findings: list, reply) -> list:
    got = reply.get("rows") if isinstance(reply, dict) else None
    if not isinstance(got, list):
        return ["返答に rows（行の配列）が無い"]
    want = {r["finding"]: r for r in rows}
    banned = worldcheck.banned_tokens(findings)
    seen, out = [], []
    for i, r in enumerate(got):
        if not isinstance(r, dict):
            out.append(f"rows[{i}] が JSON のオブジェクトでない")
            continue
        n = r.get("finding")
        head = f"rows[{i}]（依頼の行 {n}）"
        if n not in want:
            out.append(f"{head}: finding は渡した依頼の行の番号（{sorted(want)}）")
            continue
        if n in seen:
            out.append(f"{head}: 同じ依頼の行の 2 つ目")
        seen.append(n)
        base = want[n]
        if not isinstance(r.get("practice"), str) or not r["practice"].strip():
            out.append(f"{head}: practice が空")
        else:
            hit = worldcheck.text_problems(r["practice"], banned)
            if hit:
                out.append(f"{head}: practice に依頼の行の識別子 {hit} が在る（対象の名を書かない）")
        ids = {s["id"] for s in base["sources"]}
        src = r.get("sources")
        if not isinstance(src, list) or not all(isinstance(s, str) for s in src):
            out.append(f"{head}: sources は抜き書きの id の配列")
            src = []
        stray = [s for s in src if s not in ids]
        if stray:
            out.append(f"{head}: sources {stray} はこの依頼の行の照らして残った抜き書きでない（在るのは {sorted(ids) or '無し'}）")
        basis = r.get("basis")
        if basis not in worldmark.BASES:
            out.append(f"{head}: basis は {'・'.join(worldmark.BASES)} のどちらか")
        elif (basis == worldmark.WEB) != bool(src):
            out.append(f"{head}: basis {worldmark.WEB} は sources が 1 つ以上・{worldmark.KNOWLEDGE} は sources が空の時")
        for key in ("applies", "not_applies", "challenge"):
            if not isinstance(r.get(key), str):
                out.append(f"{head}: {key} が字でない（無ければ空の字）")
        verdict = r.get("verdict")
        if verdict not in worldmark.VERDICTS:
            out.append(f"{head}: verdict は {'・'.join(worldmark.VERDICTS)} のどれか")
        elif (verdict == worldmark.NONE) != (not base["proposed"]):
            out.append(f"{head}: verdict {worldmark.NONE} は依頼が解き方を示していない行だけ（この行の依頼の解き方: "
                       f"{base['proposed'] or '無し'}）")
        elif verdict == worldmark.DIFFERS and len(str(r.get("challenge") or "").strip()) < MIN_CHALLENGE:
            out.append(f"{head}: verdict {worldmark.DIFFERS} は challenge（「依頼は X、定石は Y。…でない限り Y を選ぶ」。"
                       f"{MIN_CHALLENGE} 字以上）が要る")
    missing = sorted(set(want) - set(seen))
    if missing:
        out.append(f"行の無い依頼の行: {missing}（全部の行に 1 つずつ）")
    return out


def judge_accept(out, reply) -> dict:
    out = pathlib.Path(out)
    rows = _need(out, JUDGE_INPUT)
    bad = judge_problems(rows, _need(out, INTAKE)["findings"], reply)
    if not bad:
        _write(out / JUDGED, sorted(reply["rows"], key=lambda r: r["finding"]))
    return _verdict(out, JUDGE_ROLE, bad)


# ---------------------------------------------------------------- 出口
def _rows(out) -> list:
    base = {r["finding"]: r for r in _read(pathlib.Path(out) / JUDGE_INPUT) or []}
    rows = []
    for j in _read(pathlib.Path(out) / JUDGED) or []:
        b = base[j["finding"]]
        by_id = {s["id"]: s for s in b["sources"]}
        rows.append({"finding": b["finding"], "where": b["where"], "class_id": b["class_id"], "problem": b["problem"],
                     "activity": b["activity"], "practice": j["practice"].strip(), "sources": [by_id[s] for s in j["sources"]],
                     "applies": j["applies"].strip(), "not_applies": j["not_applies"].strip(),
                     "versus": {"proposed": b["proposed"], "verdict": j["verdict"],
                                "challenge": j["challenge"].strip() if j["verdict"] == worldmark.DIFFERS else ""},
                     "basis": j["basis"], "cached": b["cached"]})
    return rows


def share(root, rows, now: float) -> list:
    """web の行の定石の部分を控えに足す（控えから使った類と knowledge の行は足さない。類ごとに最初の行）。書けなかった理由の並び"""
    st, done, whys = store(root), set(), []
    for r in rows:
        if r["basis"] != worldmark.WEB or r["cached"] or r["class_id"] in done:
            continue
        done.add(r["class_id"])
        why = st.put(_name(r["class_id"]), {"schema": SCHEMA, "status": "ok", "at": now, "class_id": r["class_id"],
                                            "problem": r["problem"], "activity": r["activity"], "practice": r["practice"],
                                            "sources": [{"url": s["url"], "excerpt": s["excerpt"]} for s in r["sources"]],
                                            "basis": worldmark.WEB})
        if why:
            whys.append(why)
    return whys


def finish(out, now: float) -> dict:
    """行を WORLD_FILE に書き、控えに足し、出口 {ok, world_file, status, reason, classes, cached, skipped, dropped} を返す。
    落ちた段が在っても線は止めない（status: failed と reason）"""
    out = pathlib.Path(out)
    intake_doc = _read(out / INTAKE) or {}
    pl = _read(out / PLAN) or {}
    ver = _read(out / VERIFIED) or {}
    world = out / worldmark.WORLD_FILE
    reasons, status = [], "ok"
    if not intake_doc:
        status, reasons = "failed", ["入口の控えが無い（入口の節が落ちた）"]
    elif intake_doc.get("reason"):
        status, reasons = "failed", [intake_doc["reason"]]
    elif intake_doc.get("findings"):
        cs = loop_state(out, CLASSES_ROLE)
        js = loop_state(out, JUDGE_ROLE)
        if cs.get("status") != "ok":
            status = "failed"
            reasons.append(f"言い直す役の返答が受け付けを通らなかった: {cs.get('reason') or '輪が走らなかったか落ちた'}")
        elif not pl:
            status = "failed"
            reasons.append("控えを引く節が落ちた（類を決めた控えが無い）")
        elif pl.get("taken") and js.get("status") != "ok":
            status = "failed"
            reasons.append(f"判断する役の返答が受け付けを通らなかった: {js.get('reason') or '輪が走らなかったか落ちた'}")
    rows = _rows(out) if status == "ok" else []
    world.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
    if not pl.get("web", True) and pl.get("taken"):
        reasons.append(f"web が off（{worldmark.NOT_WEB}）")
    elif ver.get("offline"):
        reasons.append(f"網に届かなかった（{worldmark.NOT_WEB}）")
    if ver.get("note"):
        reasons.append(ver["note"])
    if pl.get("over"):
        reasons.append(f"類の上限 {MAX_CLASSES} を越えた依頼の行 {pl['over']} は行を書いていない")
    reasons += [f"控えに書けない: {w}" for w in share(intake_doc.get("cache_root") or "", rows, now)] if rows else []
    return {"ok": True, "world_file": str(world), "status": status, "reason": "／".join(reasons),
            "classes": len(pl.get("taken") or []), "cached": len(pl.get("cached") or {}), "skipped": len(pl.get("skipped") or []),
            "dropped": len(ver.get("dropped") or []) + int(ver.get("over_excerpts") or 0)}
