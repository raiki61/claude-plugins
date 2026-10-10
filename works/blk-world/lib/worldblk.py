"""世界の解のブロックの中身（計画 docs/plans/2026-10-09-world-solution.md の 5.2 節・5.4 節・5.5 節。節の口は scripts/*.py）。

依頼の行ごとに、依頼の解き方と対象の名を外した問題の類に言い直させ（言い直す役。道具ゼロ）、言い直した問題の類・作業・検索語・
依頼の解き方だけを見せた web の役に、世の中の定石の抜き書きを集めさせて類ごとの定石と依頼の解き方との比べを判断させ（web の役。
web の検索と取得だけ）、抜き書きを機械が取り直した本文で照らし（lib/worldcheck）、行を WORLD_FILE（core の worldmark）に書く。
ブロックの外の物は名指さない: 入力は依頼のファイル（findings の配列か {findings, …} の形）・目的の文のファイル（任意。
{purpose_text, means?} の JSON。means は依頼の解き方の文の配列）・web の切り替え（on・off）。

置き場は $ARTIFACTS_DIR の下の OUT_DIR（盤面の外。place が盤面の置き場から組む。intake が置き直す）。
- intake.json: {findings, purpose_text, means, web, reason}
- classes.json（言い直す役の受け付けが通した行）: [{finding, where, class_id, problem, activity, proposed, queries}]
- plan.json（類を決めた後）: {over, taken}
- judge-input.json・judged.json（web の役の材料と、受け付けが通した行）
- verified.json（web の役の受け付けが抜き書きを照らした結果）: {kept, dropped, offline, over_excerpts}
- rejects-<役>.json: 出し直しの輪の拒否の文（core の rolekit が積む）。拒めば同じ会話で出し直させ、rolekit.GIVE_UP_AFTER 回目の拒否で
  輪を抜ける（線を止めない。出口の status: failed と reason に残す）

上限（5.4 節）: 類は MAX_CLASSES・検索語は類ごとに MAX_QUERIES（全部の行に 1 本以上）・抜き書きは返答の全部で MAX_EXCERPTS ×
取った類の数（抜き書きは類に結ばないので類ごとには数えない。越えた分は頭から取り、取らなかった数を残す）。類の id は問題の類の
文を正規化した字の hash で、対象の名を持たない。言い直す役の問題の類・作業・検索語・依頼の解き方は、web の役に渡るので、全部が
依頼の行の識別子を持たない。web の役の返答の根拠（sources）と
印（basis）は機械だけが決める（役は basis を返さない）: 取り直した本文に字のまま在る抜き書きを指す根拠だけ残し、残れば
basis: web、残りが無い行は basis: knowledge にする。
網に出ない run（web が off・取り直しが全部網に届かない）も止めず、行は知識だけで書く（basis: knowledge）。
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
import board  # noqa: E402  （置き場の控えの欠けを投げる例外の住処）
import promptsection  # noqa: E402
import rolekit  # noqa: E402  （出し直しの輪の拒否の控えと指示書の頭）
import webget  # noqa: E402  （網の口）
import worldmark  # noqa: E402  （世界の解の行の住処）
import worldcheck  # noqa: E402  （同じ lib の照らし）

OUT_DIR = "world"
INTAKE, CLASSES, PLAN, VERIFIED, JUDGE_INPUT, JUDGED = (
    "intake.json", "classes.json", "plan.json", "verified.json", "judge-input.json", "judged.json")
PROMPT = "{role}-prompt-{n}.md"
CLASSES_ROLE, JUDGE_ROLE = "classes", "judge"
MAX_CLASSES, MAX_QUERIES, MAX_EXCERPTS = 5, 3, 6
MIN_CHALLENGE = 20   # differs の challenge の字の下限
MAX_BODY = 2 * 1024 * 1024
HEADERS = {"User-Agent": "works-world/1", "Accept": "text/html, text/plain;q=0.9, */*;q=0.5"}


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
        raise board.BoardGap(f"{pathlib.Path(out) / name} が無いか読めない")
    return got


def place(board_dir) -> pathlib.Path:
    """このブロックの置き場（盤面の置き場 $ARTIFACTS_DIR/board の隣の $ARTIFACTS_DIR/world）"""
    return pathlib.Path(board_dir).parent / OUT_DIR


def class_id(problem: str) -> str:
    """問題の類の id（正規化した文の sha256 の頭 12 字）。同じ字の類は同じ id になる"""
    return "w-" + hashlib.sha256(worldcheck.normalize(problem).encode("utf-8")).hexdigest()[:12]


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


def fetch(url):
    """機械が同じ URL を取り直す口（抜き書きの照らしの get）"""
    return webget.http_get(url, HEADERS, MAX_BODY)


def intake(out, *, request: str, purpose_file: str, web, cwd) -> dict:
    """置き場を置き直して intake.json を書く。返り {due, findings, reason}（due は言い直す役を起こすか）。依頼や目的の文が読めない
    時も止めない（reason に残し、due は偽。出口が status: failed にする）"""
    out = pathlib.Path(out)
    out.mkdir(parents=True, exist_ok=True)
    for p in out.iterdir():
        if p.is_file():
            p.unlink()
    doc = {"findings": [], "purpose_text": "", "means": [], "web": True, "reason": ""}
    try:
        doc["web"] = _switch(web)
        doc["findings"] = _findings(request, cwd)
        doc["purpose_text"], doc["means"] = _purpose(purpose_file, cwd)
    except ValueError as e:
        doc["reason"] = " ".join(str(e).split())
    _write(out / INTAKE, doc)
    return {"due": bool(doc["findings"]) and not doc["reason"], "findings": len(doc["findings"]), "reason": doc["reason"]}


def _switch(web) -> bool:
    return script_io.switch_on(web, "web")


# ---------------------------------------------------------------- 輪の控え（拒否は rolekit の控えに積む）
def _prep(out, role, body: str) -> dict:
    rejected = rolekit.rejected(out, role)
    prompt = rolekit.with_reject(body, rejected[-1]) if rejected else body
    path = pathlib.Path(out) / PROMPT.format(role=role, n=len(rejected) + 1)
    path.write_text(prompt, encoding="utf-8")
    return {"prompt": prompt, "prompt_file": str(path)}


def _close_round(out, role, bad: list) -> dict:
    return rolekit.with_done(pathlib.Path(out), role, {"ok": not bad, "reason": " / ".join(bad)})


def _why_failed(out, role) -> str:
    """輪が通らなかった役の理由（諦めた文か、落ちた周の最後の拒否の文。拒否も無ければ走らなかった）"""
    rejected = rolekit.rejected(out, role)
    return rolekit.given_up_reason(out, role) or (rejected[-1] if rejected else "輪が走らなかったか落ちた")


# ---------------------------------------------------------------- 言い直す役
def _finding_lines(findings) -> list:
    out = []
    for i, f in enumerate(findings, 1):
        out.append(f"{i}. where: {f.get('where')}")
        out += [f"   {k}: {f[k]}" for k in ("text", "mechanism", "measured", "false_positive_if") if isinstance(f.get(k), str)]
    return out


FINDINGS_HEAD = promptsection.Section("## 依頼の行（機械が依頼のファイルから抜いた物。これが渡された物の全部）", source="fn:worldblk.classes_prep")
PURPOSE_HEAD = promptsection.Section("## 目的の文", source="fn:worldblk.classes_prep")
REPLY_HEAD = promptsection.Section("## 返し方", source="fn:worldblk.classes_prep")


def classes_prep(out) -> dict:
    doc = _need(out, INTAKE)
    lines = [FINDINGS_HEAD, "", *_finding_lines(doc["findings"]), "",
             PURPOSE_HEAD, "", doc["purpose_text"] or "（渡されていない）", ""]
    if doc["means"]:
        lines += ["依頼が示した解き方（目的の文から分けた物）:", *[f"- {m}" for m in doc["means"]], ""]
    lines += [REPLY_HEAD, "",
              f"- classes に、依頼の行の全部へ 1 つずつ（finding は上の行の番号 1〜{len(doc['findings'])}）",
              "- problem: 依頼の行を、依頼が示した解き方と対象の名（パス・ファイル・関数・欄・環境変数・部品の名・run の id）を外し、"
              "実務家がする作業の言葉で言い直した問題の類の 1 文",
              "- activity: 作業の種類の名（短い名）",
              "- proposed: 依頼が示した解き方を、対象の名を外して写す（上の『依頼が示した解き方』と依頼の文から。示していなければ空）。"
              "これは web の役にも渡る",
              f"- queries: 世の中の実務家がこの類をどう解いているか（実践・慣習・標準）を問う検索語（全部の行に 1〜{MAX_QUERIES} 本。"
              "対象の名を入れない）",
              "- 機械は problem・activity・proposed・queries に依頼の行から取った識別子が在れば、その識別子を名指して拒む"]
    return _prep(out, CLASSES_ROLE, "\n".join(lines) + "\n")


def class_problems(doc: dict, reply) -> list:
    rows = reply.get("classes") if isinstance(reply, dict) else None
    if not isinstance(rows, list):
        return ["返答に classes（行の配列）が無い"]
    findings = doc["findings"]
    banned = worldcheck.banned_tokens(findings)
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
        if not isinstance(qs, list) or not all(isinstance(q, str) and q.strip() for q in qs) or len(qs) > MAX_QUERIES:
            out.append(f"{head}: queries は空でない字の配列（{MAX_QUERIES} 本まで）")
            qs = []
        elif not qs:
            out.append(f"{head}: queries が無い（全部の行に 1 本以上）")
        texts = [("problem", r.get("problem")), ("activity", r.get("activity")), ("proposed", r.get("proposed"))]
        for key, text in texts + [("queries", q) for q in qs]:   # web の役に渡る文は全部、対象の名を持たない
            hit = worldcheck.text_problems(text, banned)
            if hit:
                out.append(f"{head}: {key} に依頼の行の識別子 {hit} が在る（対象の名を外し、作業の言葉で言い直せ）")
    missing = [n for n in range(1, len(findings) + 1) if n not in seen]
    if missing:
        out.append(f"行の無い依頼の行: {missing}（全部の行に 1 つずつ）")
    return out


def classes_accept(out, reply) -> dict:
    doc = _need(out, INTAKE)
    bad = class_problems(doc, reply)
    if not bad:
        rows = []
        for r in sorted(reply["classes"], key=lambda x: x["finding"]):
            rows.append({"finding": r["finding"], "where": doc["findings"][r["finding"] - 1]["where"],
                         "class_id": class_id(r["problem"]), "problem": r["problem"].strip(), "activity": r["activity"].strip(),
                         "proposed": r["proposed"].strip(), "queries": [q.strip() for q in r["queries"]]})
        _write(pathlib.Path(out) / CLASSES, rows)
    return _close_round(out, CLASSES_ROLE, bad)


# ---------------------------------------------------------------- 類を決める
def plan(out) -> dict:
    """言い直しの行から、取る類（MAX_CLASSES まで）を決めて plan.json に書く。返り {judge_due}（web の役を起こすか）"""
    out = pathlib.Path(out)
    _need(out, INTAKE)   # 入口の控えの無い置き場は配線の誤り
    rows = _read(out / CLASSES)
    if not isinstance(rows, list):
        _write(out / PLAN, {"over": [], "taken": []})
        return {"judge_due": False}
    taken, over = [], []
    for r in rows:
        if r["class_id"] not in taken and len(taken) >= MAX_CLASSES:
            over.append(r["finding"])
        elif r["class_id"] not in taken:
            taken.append(r["class_id"])
    _write(out / PLAN, {"over": over, "taken": taken})
    return {"judge_due": bool(taken)}


# ---------------------------------------------------------------- web の役
def _judge_rows(out) -> list:
    """web の役に渡す行（取った類の、依頼の行ごと）。言い直しの行の問題の類・作業・検索語・依頼の解き方だけで、依頼の行の本文は持たない
    （where は機械が行に写すために持ち、役の指示書には貼らない）"""
    out = pathlib.Path(out)
    rows, pl = _need(out, CLASSES), _need(out, PLAN)
    return [{k: r[k] for k in ("finding", "where", "class_id", "problem", "activity", "proposed", "queries")}
            for r in rows if r["class_id"] in pl["taken"]]


PROBLEMS_HEAD = promptsection.Section("## 問題の類と依頼の解き方（機械が言い直しの返答から抜いた物。これが渡された物の全部）", source="fn:worldblk.judge_prep")
CLASS_HEAD = promptsection.Section("### 類 {class_id}", source="fn:worldblk.judge_prep")

RECEIVES = [
    *(promptsection.Receive(role, rolekit.REJECT_HEADING) for role in ("world-classes", "world-judge")),
    *(promptsection.Receive("world-classes", head) for head in (FINDINGS_HEAD, PURPOSE_HEAD, REPLY_HEAD)),
    *(promptsection.Receive("world-judge", head) for head in (PROBLEMS_HEAD, CLASS_HEAD)),
    promptsection.Receive("world-judge", REPLY_HEAD, "worldblk.judge_prep"),
]


def judge_prep(out) -> dict:
    out = pathlib.Path(out)
    if not (out / JUDGE_INPUT).is_file():
        _write(out / JUDGE_INPUT, _judge_rows(out))
    rows = _need(out, JUDGE_INPUT)
    web = _need(out, INTAKE)["web"]
    by_class = {}
    for r in rows:
        by_class.setdefault(r["class_id"], []).append(r)
    lines = [PROBLEMS_HEAD, ""]
    for cid, group in by_class.items():
        first = group[0]
        lines += [CLASS_HEAD.format(class_id=cid), "", f"- 問題の類: {first['problem']}", f"- 作業: {first['activity']}",
                  *[f"- 検索語: {q}" for q in first["queries"]],
                  *[f"- 依頼の行 {r['finding']} の依頼の解き方: {r['proposed'] or '（示していない）'}" for r in group], ""]
    lines += [REPLY_HEAD, ""]
    if web:
        lines += ["- 検索語で世の中の定石を探し（検索語を足してよいが、対象の名を入れない）、取得の道具で取得したページから抜き書きを運ぶ",
                  "- excerpts に {id, url, excerpt} を並べる。id は x1・x2 … の名前で、返答の中で重ねない",
                  f"- 抜き書きは全部で {MAX_EXCERPTS * len(by_class)} まで。{worldcheck.MIN_EXCERPT} 字以上で、取得した本文の文を字のまま写す。"
                  "機械が同じ URL を取り直し、本文に字のまま無い抜き書きは落とし、それを指す sources も外す",
                  "- url は取得の道具で本当に取得したページだけ（検索の結果の一覧に出ただけの URL は書かない）"]
    else:
        lines += ["- web は off: 検索も取得もしない。excerpts は空の配列、sources は空にして、知識だけで定石を書く",
                  "  （web を使っても機械が抜き書きを捨て、根拠を外す）"]
    lines += ["- rows に、上の依頼の行の全部へ 1 つずつ（finding は上の番号）",
              "- practice: 世の中の実務家がこの類を決まってどう解いているか（1〜3 文。対象の名を書かない）",
              "- sources: practice の根拠にした抜き書きの id（excerpts の id）。抜き書きを使わないなら空。web で確かめたかの印は、機械が"
              "照らして残った根拠から付ける",
              "- applies: この依頼にどう当たるか。not_applies: どこには当たらないか（当たらない依頼なら applies は空）",
              f"- verdict: 依頼の解き方が定石と同じなら {worldmark.SAME}、違えば {worldmark.DIFFERS}、依頼が解き方を示していなければ "
              f"{worldmark.NONE}",
              f"- challenge: {worldmark.DIFFERS} の時だけ「依頼は X、定石は Y。…でない限り Y を選ぶ」の形の文（{MIN_CHALLENGE} 字以上）。"
              "ほかは空",
              "- 機械は practice に依頼の行から取った識別子が在れば拒む"]
    return _prep(out, JUDGE_ROLE, "\n".join(lines) + "\n")


def _excerpts(reply) -> tuple:
    """返答の excerpts（無ければ抜き書き無し）。(抜き書きの配列, 形の問題の文の配列)"""
    got = reply.get("excerpts", []) if isinstance(reply, dict) else []
    if not isinstance(got, list):
        return [], ["excerpts は {id, url, excerpt} の配列"]
    took, bad, ids = [], [], set()
    for i, e in enumerate(got):
        if not isinstance(e, dict) or not all(isinstance(e.get(k), str) for k in ("id", "url", "excerpt")) or not e["id"].strip():
            bad.append(f"excerpts[{i}] が {{id, url, excerpt}} の字の組でない（id は空でない字）")
        elif e["id"] in ids:
            bad.append(f"excerpts[{i}]: id {e['id']} が返答の中で重なる")
        else:
            ids.add(e["id"])
            took.append({k: e[k] for k in ("id", "url", "excerpt")})
    return took, bad


def judge_problems(rows: list, findings: list, reply, web: bool = True) -> list:
    """web の役の返答の拒否の文。web が off の run は抜き書きと根拠を見ない（機械が捨てる）。印 basis は見ない（機械が付ける）"""
    got = reply.get("rows") if isinstance(reply, dict) else None
    if not isinstance(got, list):
        return ["返答に rows（行の配列）が無い"]
    want = {r["finding"]: r for r in rows}
    banned = worldcheck.banned_tokens(findings)
    excerpts, out = _excerpts(reply) if web else ([], [])
    ids = {e["id"] for e in excerpts}
    seen = []
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
        src = r.get("sources")
        if not isinstance(src, list) or not all(isinstance(s, str) for s in src):
            out.append(f"{head}: sources は抜き書きの id の配列")
            src = []
        stray = [s for s in src if s not in ids] if web else []
        if stray:
            out.append(f"{head}: sources {stray} は返答の excerpts の id でない（在るのは {sorted(ids) or '無し'}）")
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


def _check_excerpts(out, reply, web: bool, get, classes: int) -> dict:
    """返答の抜き書きを、機械が取り直した本文で照らして verified.json に書く。返り {抜き書きの id: {id, url, excerpt}}（残った物）。
    web が off の run は取り直さず、残る抜き書きは無い。越えた分（返答の全部で MAX_EXCERPTS × 取った類の数）は頭から取り、
    取らなかった数を残す"""
    excerpts = _excerpts(reply)[0] if web else []
    took = excerpts[:MAX_EXCERPTS * classes]
    got = worldcheck.verify(took, get)
    _write(pathlib.Path(out) / VERIFIED, {"kept": got["kept"], "dropped": got["dropped"], "offline": got["offline"],
                                          "over_excerpts": len(excerpts) - len(took)})
    return {k["id"]: k for k in got["kept"]}


def judge_accept(out, reply, get=fetch) -> dict:
    """web の役の返答を受け付ける。通れば、抜き書きを get で取り直した本文に照らし、字のまま無い抜き書きを指す根拠を外し、
    根拠の残らない行の印を knowledge にして、判断の行を書く"""
    out = pathlib.Path(out)
    rows = _need(out, JUDGE_INPUT)
    web = _need(out, INTAKE)["web"]
    bad = judge_problems(rows, _need(out, INTAKE)["findings"], reply, web)
    if not bad:
        kept = _check_excerpts(out, reply, web, get, len({r["class_id"] for r in rows}))
        judged = []
        for j in sorted(reply["rows"], key=lambda r: r["finding"]):
            sources = [kept[s] for s in dict.fromkeys(j["sources"]) if s in kept]
            judged.append({**j, "sources": sources, "basis": worldmark.WEB if sources else worldmark.KNOWLEDGE})
        _write(out / JUDGED, judged)
    return _close_round(out, JUDGE_ROLE, bad)


# ---------------------------------------------------------------- 出口
def _rows(out) -> list:
    base = {r["finding"]: r for r in _read(pathlib.Path(out) / JUDGE_INPUT) or []}
    rows = []
    for j in _read(pathlib.Path(out) / JUDGED) or []:
        b = base[j["finding"]]
        rows.append({"finding": b["finding"], "where": b["where"], "class_id": b["class_id"], "problem": b["problem"],
                     "activity": b["activity"], "practice": j["practice"].strip(), "sources": j["sources"],
                     "applies": j["applies"].strip(), "not_applies": j["not_applies"].strip(),
                     "versus": {"proposed": b["proposed"], "verdict": j["verdict"],
                                "challenge": j["challenge"].strip() if j["verdict"] == worldmark.DIFFERS else ""},
                     "basis": j["basis"]})
    return rows


def finish(out) -> dict:
    """行を WORLD_FILE に書き、出口 {ok, world_file, status, reason, classes, dropped} を返す。
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
        if not (out / CLASSES).is_file():
            status = "failed"
            reasons.append(f"言い直す役の返答が受け付けを通らなかった: {_why_failed(out, CLASSES_ROLE)}")
        elif not pl:
            status = "failed"
            reasons.append("類を決める節が落ちた（類を決めた控えが無い）")
        elif pl.get("taken") and not (out / JUDGED).is_file():
            status = "failed"
            reasons.append(f"集めて判断する役の返答が受け付けを通らなかった: {_why_failed(out, JUDGE_ROLE)}")
    rows = _rows(out) if status == "ok" else []
    world.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
    if not intake_doc.get("web", True) and pl.get("taken"):
        reasons.append(f"web が off（{worldmark.NOT_WEB}）")
    elif ver.get("offline"):
        reasons.append(f"網に届かなかった（{worldmark.NOT_WEB}）")
    if pl.get("over"):
        reasons.append(f"類の上限 {MAX_CLASSES} を越えた依頼の行 {pl['over']} は行を書いていない")
    return {"ok": True, "world_file": str(world), "status": status, "reason": "／".join(reasons),
            "classes": len(pl.get("taken") or []), "dropped": len(ver.get("dropped") or []) + int(ver.get("over_excerpts") or 0)}
