"""構造の目（設計書 structure-block-design の 4 節・6 節の「自分で決める」・10 節の S2b）の支度と受け付け。

目は道具を持たない独立の会話の役で、見せるのは structure.json の単位ごとの {id, summary, measure} と問い 1 つと 6 つの形だけ。
受け付けは返答を機械で確かめ、通れば design-row.schema.json の形の行を design.jsonl に書く。拒めば理由を返し、同じ会話で
出し直させる（輪の max_iterations は 3。3 回目の拒否は give_up で輪を抜け、線を落とさない）。

控え eye.json（design.jsonl の隣。段 A が置き直す）: {attempt, started_at, reason, status: pending|ok|gave_up, wall_s}。
wall_s は 1 回目の支度から最後の受け付けまでの壁時計の秒。

- due(doc):                   目を起こす周か（structure.json の status が ok で、実測できた単位が 1 つ以上）
- prep(structure_file):       指示書を描いて控えの attempt を 1 つ進める。返り {prompt, prompt_file, attempt}
- accept(structure_file, design_file, reply): 返答を確かめて行を書く。返り {ok, done, give_up, reason, attempt}
- state(out_dir):             控え（無い・読めないなら {}）
"""
import json
import pathlib
import time

EYE_FILE = "eye.json"
PROMPT_FILE = "eye-prompt-{n}.md"
MAX_ATTEMPTS = 3
SCHEMA = pathlib.Path(__file__).resolve().parents[1] / "design-row.schema.json"
ROUTE = "自分で決める"
ROUTE_REASON = "人に上げる道（設計書 6 節）はこの版に無いので、目の判定をそのまま計画に渡す"
QUESTION = "この案を入れた後、次に同じ領域を直す人が、設計を知らないまま足す形が増えるか"
# 設計書 4 節の 6 つの形（design-row.schema.json の faces の 1〜6 の意味。試験が設計書との一致を見る）
FORMS = (
    "共有の物を run や呼び手ごとに書き換える",
    "責務を 2 か所に割る",
    "既存の仕組みを横から曲げる",
    "ブロックの境をまたいで、他のブロックの中身を前提にする",
    "骨組みの無いまま新しい名前や口を足す",
    "外の道具の事情を名指しで抱え込む",
)
VERDICTS = ("汚れる", "汚れない")
DIRTY = VERDICTS[0]


def measured(doc: dict) -> list:
    return [u for u in doc.get("units") or [] if isinstance(u, dict) and u.get("status") == "measured"]


def due(doc: dict) -> bool:
    return doc.get("status") == "ok" and bool(measured(doc))


def state(out_dir) -> dict:
    try:
        got = json.loads((pathlib.Path(out_dir) / EYE_FILE).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError):
        return {}
    return got if isinstance(got, dict) else {}


def _put(out_dir, doc: dict) -> None:
    (pathlib.Path(out_dir) / EYE_FILE).write_text(json.dumps(doc, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


def _load(structure_file) -> dict:
    return json.loads(pathlib.Path(structure_file).read_text(encoding="utf-8"))


def view(doc: dict) -> dict:
    """目に見せる JSON。根拠の JSON Pointer はこれの中を指すので、受け付けも同じ物で引く"""
    units = [{"id": u["id"], "summary": u.get("summary", ""), "measure": u.get("measure")} for u in measured(doc)]
    return {"units": units, "timing": doc.get("timing")}


def render(doc: dict, rejected: str = "") -> str:
    lines = []
    if rejected:
        lines += ["## 前の回の受け付けが拒んだ理由", "", rejected, "", "ここを直した返答を丸ごと出し直せ（直した所だけを返すな）。", ""]
    lines += ["## 問い", "", f"単位ごとに答えよ: {QUESTION}。", "",
              "## 見る形（番号で答える）", "", *[f"{i}. {f}" for i, f in enumerate(FORMS, 1)], "",
              "## 返し方", "",
              "- 下の単位の全部に 1 行ずつ（汚れないと見た単位も黙って通さない）。unit_id は単位の id をそのまま写す",
              f"- verdict は {'・'.join(VERDICTS)} のどちらか。faces は当たった形の番号（汚れるなら 1 つ以上）",
              "- evidence は根拠にした実測の欄を、下の JSON（units の配列と timing）の中を指す JSON Pointer（RFC 6901。例 /units/0/measure）で"
              " 1 つ以上。無い欄を指すな",
              "- reason は理由。汚れると見た単位は chosen（推しの避け方）と chosen_reason（推しの理由）も書く", "",
              "## 単位と実測（structure.json から機械が抜いた物。これが渡された物の全部）", "",
              "```json", json.dumps(view(doc), ensure_ascii=False, indent=1), "```"]
    return "\n".join(lines) + "\n"


def prep(structure_file) -> dict:
    out_dir = pathlib.Path(structure_file).parent
    doc = _load(structure_file)
    st = state(out_dir)
    n = int(st.get("attempt") or 0) + 1
    prompt = render(doc, st.get("reason") or "")
    path = out_dir / PROMPT_FILE.format(n=n)
    path.write_text(prompt, encoding="utf-8")
    _put(out_dir, {"attempt": n, "started_at": st.get("started_at") or time.time(), "reason": st.get("reason") or "",
                   "status": "pending", "wall_s": st.get("wall_s", 0)})
    return {"prompt": prompt, "prompt_file": str(path), "attempt": n}


def _pointer(doc, ptr: str) -> bool:
    """ptr（RFC 6901）が doc の中の在る欄（値が null でない。null の欄は根拠にならない）を指すか"""
    if not isinstance(ptr, str) or not ptr.startswith("/"):
        return False
    cur = doc
    for raw in ptr[1:].split("/"):
        key = raw.replace("~1", "/").replace("~0", "~")
        if isinstance(cur, dict) and key in cur:
            cur = cur[key]
        elif isinstance(cur, list) and key.isdigit() and int(key) < len(cur) and (key == "0" or not key.startswith("0")):
            cur = cur[int(key)]
        else:
            return False
    return cur is not None


def problems(doc: dict, reply) -> list:
    """返答の外れ（空なら通る）。単位と 1 対 1・形・根拠の実在・汚れる行の避け方・人に上げる道の無さを見る"""
    rows = reply.get("rows") if isinstance(reply, dict) else None
    if not isinstance(rows, list):
        return ["返答に rows（行の配列）が無い"]
    keys = set(json.loads(SCHEMA.read_text(encoding="utf-8"))["properties"])
    want = [u["id"] for u in measured(doc)]
    seen, out = [], []
    shown = view(doc)
    for i, r in enumerate(rows):
        if not isinstance(r, dict):
            out.append(f"行 {i} が JSON のオブジェクトでない")
            continue
        uid = r.get("unit_id")
        head = f"行 {i}（{uid}）"
        extra = sorted(set(r) - keys)
        if extra:
            out.append(f"{head}: 行の形に無い欄 {extra}")
        if uid not in want:
            out.append(f"{head}: 実測した単位に無い id（在るのは {want}）")
        elif uid in seen:
            out.append(f"{head}: 同じ単位の 2 行目")
        seen.append(uid)
        if r.get("verdict") not in VERDICTS:
            out.append(f"{head}: verdict は {'・'.join(VERDICTS)} のどちらか")
        faces = r.get("faces")
        if not isinstance(faces, list) or any(not isinstance(f, int) or isinstance(f, bool) or not 1 <= f <= len(FORMS)
                                              for f in faces):
            out.append(f"{head}: faces は形の番号 1〜{len(FORMS)} の配列")
        elif r.get("verdict") == DIRTY and not faces:
            out.append(f"{head}: 汚れると見たのに当たった形の番号が無い")
        ev = r.get("evidence")
        if not isinstance(ev, list) or not ev:
            out.append(f"{head}: evidence（根拠にした実測の欄）が空")
        else:
            out += [f"{head}: evidence {p!r} が実測の中の在る欄を指さない" for p in ev if not _pointer(shown, p)]
        if not isinstance(r.get("reason"), str) or not r["reason"].strip():
            out.append(f"{head}: reason が空")
        if r.get("verdict") == DIRTY and not all(isinstance(r.get(k), str) and r[k].strip() for k in ("chosen", "chosen_reason")):
            out.append(f"{head}: 汚れると見た行に chosen（推しの避け方）と chosen_reason が無い")
        if r.get("route", ROUTE) != ROUTE:
            out.append(f"{head}: route は {ROUTE} だけ（人に上げる道はこの版に無い）")
    missing = [u for u in want if u not in seen]
    if missing:
        out.append(f"行の無い単位: {missing}（汚れないと見た単位も 1 行ずつ）")
    return out


def accept(structure_file, design_file, reply) -> dict:
    out_dir = pathlib.Path(structure_file).parent
    st = state(out_dir)
    n = int(st.get("attempt") or 1)
    started = st.get("started_at") or time.time()
    bad = problems(_load(structure_file), reply)
    wall = round(time.time() - started, 3)
    if bad:
        reason = " / ".join(bad)
        give_up = n >= MAX_ATTEMPTS
        _put(out_dir, {**st, "attempt": n, "started_at": started, "reason": reason,
                       "status": "gave_up" if give_up else "pending", "wall_s": wall})
        return {"ok": False, "done": give_up, "give_up": give_up, "reason": reason, "attempt": n}
    rows = [{**r, "route": ROUTE, "route_reason": ROUTE_REASON} for r in reply["rows"]]
    pathlib.Path(design_file).write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
    _put(out_dir, {**st, "attempt": n, "started_at": started, "reason": "", "status": "ok", "wall_s": wall})
    return {"ok": True, "done": True, "give_up": False, "reason": "", "attempt": n}
