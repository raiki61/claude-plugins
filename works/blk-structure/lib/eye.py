"""構造の目（設計書 structure-block-design の 4 節・6 節・10 節の S2b、計画 2026-10-09-clean-whole の Task 2.3）の支度と受け付け。

目は道具を持たない独立の会話の役で、見せるのは structure.json の単位ごとの {id, summary, measure, concepts}（concepts は段 A が
置いた、単位に当たる考えの地図の行と知る場所の数）と、対象の決まり rules（方針の文書と根の地図の文書）と、問い 1 つ
（core の concepthome.EYE_ASK。判断の 1 軸と「知る場所が増えるか」）と 6 つの形だけ。
行き先（route）は「自分で決める」か「人に上げる」。人に上げるのは決め手（人の前の決定・方針・対象の同じ場面・世界の解）を
当たっても 1 つに決まらない汚れる行だけで、決まらない訳（undecided_because）と捨てた案と代償（rejected）が要る。受け付けは
訳の無い「人に上げる」を拒む。上げた行は線の側が修正前の関所の項目にする（このブロックは関所を持たない）。
受け付けは返答を機械で確かめ、通れば design-row.schema.json の形の行を design.jsonl に書く。拒めば理由を返し、同じ会話で
出し直させる（輪の max_iterations は 3。3 回目の拒否は give_up で輪を抜け、線を落とさない）。

控え eye.json（design.jsonl の隣。段 A が置き直す）: {attempt, started_at, reason, status: pending|ok|gave_up, wall_s}。
目の秒は 1 回目の支度から最後の受け付けまでの壁時計の秒。
ブロックの時間の欄の名 WALL（秒）はこのモジュールが持つ: 段 A・段 B の timing は stamp で書き、出口（collect）は wall で読んで足す。

- due(doc):                   目を起こす周か（structure.json の status が ok で、実測できた単位が 1 つ以上）
- prep(structure_file):       指示書を描いて控えの attempt を 1 つ進める。返り {prompt, prompt_file, attempt}
- accept(structure_file, design_file, reply): 返答を確かめて行を書く。返り {ok, done, give_up, reason, attempt}
- state(out_dir):             控え（無い・読めないなら {}）
- stamp(doc, t0, **more):     doc の timing に t0（time.monotonic）からの秒を WALL の欄で書く（more は timing に並べる欄）
- wall(doc):                  doc の timing（無ければ doc そのもの）の WALL の秒（無い・空なら 0）
"""
import json
import pathlib
import sys
import time

_CORE = pathlib.Path(__file__).resolve().parents[2] / ".shared" / "core"
if str(_CORE) not in sys.path:
    sys.path.insert(0, str(_CORE))
import concepthome  # noqa: E402  （判断の 1 軸と目の問いの文の住処）
import promptsection  # noqa: E402

EYE_FILE = "eye.json"
PROMPT_FILE = "eye-prompt-{n}.md"
MAX_ATTEMPTS = 3
DUP_SHOWN = 5   # 目に見せる duplicates の件数（残りは duplicates_total の数だけ。_cut）
SCHEMA = pathlib.Path(__file__).resolve().parents[1] / "design-row.schema.json"
WALL = "wall_s"   # ブロックの時間の欄の名（壁時計の秒。段 A・段 B の timing・目の控え・出口が同じ名で持つ）
ROUTES = ("自分で決める", "人に上げる")
ROUTE, ROUTE_UP = ROUTES
ROUTE_REASON = "目が決め手から 1 つに決めた（決めきれない訳を書かなかった）"
MIN_UNDECIDED = 20   # 決まらない訳の字の下限（関所の項目の訳になる）
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


def stamp(doc: dict, t0: float, **more) -> None:
    doc["timing"] = {**more, WALL: round(time.monotonic() - t0, 3)}


def wall(doc) -> float:
    if not isinstance(doc, dict):
        return 0
    t = doc.get("timing") if isinstance(doc.get("timing"), dict) else doc
    return t.get(WALL) or 0

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


def _cut(v):
    """duplicates の配列を先頭 DUP_SHOWN 件に切り、全件の数を隣の duplicates_total に置く（入れ子のどこでも）。
    大きい追跡ファイルを名指す単位で塊の一致が数百件になり、支度の出力が Archon の標準出力の上限を越えて線が落ちた（run 131）"""
    if isinstance(v, list):
        return [_cut(x) for x in v]
    if not isinstance(v, dict):
        return v
    out = {k: _cut(x) for k, x in v.items()}
    dups = v.get("duplicates")
    if isinstance(dups, list) and len(dups) > DUP_SHOWN:
        out["duplicates"] = [_cut(x) for x in dups[:DUP_SHOWN]]
        out["duplicates_total"] = len(dups)
    return out


def view(doc: dict) -> dict:
    """目に見せる JSON。根拠の JSON Pointer はこれの中を指すので、受け付けも同じ物で引く。concepts（単位に当たる考えの地図の行と
    知る場所の数）と rules（方針と根の地図の文書）は段 A が置いた時だけ載る"""
    units = []
    for u in measured(doc):
        row = {"id": u["id"], "summary": u.get("summary", ""), "measure": _cut(u.get("measure"))}
        if u.get("concepts"):
            row["concepts"] = u["concepts"]
        units.append(row)
    out = {"units": units, "timing": doc.get("timing")}
    if doc.get("rules"):
        out["rules"] = doc["rules"]
    return out


REJECT_HEAD = promptsection.Section("## 前の回の受け付けが拒んだ理由", source="fn:eye.render")
ASK_HEAD = promptsection.Section("## 問い", source="fn:eye.render")
SHAPES_HEAD = promptsection.Section("## 見る形（番号で答える）", source="fn:eye.render")
REPLY_HEAD = promptsection.Section("## 返し方", source="fn:eye.render")
UNITS_HEAD = promptsection.Section("## 単位と実測（structure.json から機械が抜いた物。これが渡された物の全部）", source="fn:eye.render")
# 受け手の宣言（役の印の名 ← 節 ← 入る条件を判じる関数）
RECEIVES = [promptsection.Receive("structure-eye", head, "eye.render") for head in (REJECT_HEAD, ASK_HEAD, SHAPES_HEAD, REPLY_HEAD, UNITS_HEAD)]


def render(doc: dict, rejected: str = "") -> str:
    lines = []
    if rejected:
        lines += [REJECT_HEAD, "", rejected, "", "ここを直した返答を丸ごと出し直せ（直した所だけを返すな）。", ""]
    lines += [ASK_HEAD, "", concepthome.EYE_ASK, "",
              SHAPES_HEAD, "", *[f"{i}. {f}" for i, f in enumerate(FORMS, 1)], "",
              REPLY_HEAD, "",
              "- 下の単位の全部に 1 行ずつ（汚れないと見た単位も黙って通さない）。unit_id は単位の id をそのまま写す",
              f"- verdict は {'・'.join(VERDICTS)} のどちらか。faces は当たった形の番号（汚れるなら 1 つ以上）",
              "- evidence は根拠にした実測の欄を、下の JSON（units の配列と timing）の中を指す JSON Pointer（RFC 6901。例 /units/0/measure）で"
              " 1 つ以上。無い欄を指すな",
              "- reason は理由。汚れると見た単位は chosen（推しの避け方）と chosen_reason（推しの理由）も書く",
              "- 単位の summary（判定の単位の reason）が世の中の定石（世界の解）を名指していれば、汚れると見た単位の chosen はその作りに沿わせ、"
              "沿わないならその訳を chosen_reason に書く",
              f"- route は {ROUTE}（既定。書かなくてよい）か {ROUTE_UP}。{ROUTE_UP}は、汚れると見た単位で、決め手（下の rules の"
              "方針・人の前の決定・対象の同じ場面・世界の解）を当たっても避け方が 1 つに決まらない時だけ。その時は chosen に推し、"
              f"rejected に捨てた案と代償を 1 つ以上、undecided_because に決まらない訳（{MIN_UNDECIDED} 字以上。何と何で割れたか）を書く。"
              "人は修正の前にその問いに答える",
              "- 単位の concepts.rows は単位のファイルに当たる考えの地図の行、concepts.places は単位のファイルに在る考えの語の行の数"
              "（home は住処か知ってよい所か・known_places はその考えを知る場所の数）。rules は対象の方針と根の地図の文書",
              f"- duplicates は先頭 {DUP_SHOWN} 件だけを載せた。duplicates_total が在れば、それが全件の数", "",
              UNITS_HEAD, "",
              "```json", json.dumps(view(doc), ensure_ascii=False, separators=(",", ":")), "```"]
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
                   "status": "pending", WALL: st.get(WALL, 0)})
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
        route = r.get("route", ROUTE)
        if route not in ROUTES:
            out.append(f"{head}: route は {'・'.join(ROUTES)} のどちらか")
        elif route == ROUTE_UP:
            if r.get("verdict") != DIRTY:
                out.append(f"{head}: {ROUTE_UP}のは汚れると見た行だけ")
            why = r.get("undecided_because")
            if not isinstance(why, str) or len(why.strip()) < MIN_UNDECIDED:
                out.append(f"{head}: {ROUTE_UP}行は undecided_because（決め手を当たっても決まらない訳。{MIN_UNDECIDED} 字以上）が要る")
            rej = r.get("rejected")
            if not isinstance(rej, list) or not rej:
                out.append(f"{head}: {ROUTE_UP}行は rejected（捨てた案と代償）が 1 つ以上要る")
        elif r.get("undecided_because"):
            out.append(f"{head}: undecided_because は {ROUTE_UP}行だけに書く")
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
                       "status": "gave_up" if give_up else "pending", WALL: wall})
        return {"ok": False, "done": give_up, "give_up": give_up, "reason": reason, "attempt": n}
    rows = [{**r, "route": r.get("route", ROUTE),
             "route_reason": r["undecided_because"].strip() if r.get("route") == ROUTE_UP else ROUTE_REASON}
            for r in reply["rows"]]
    pathlib.Path(design_file).write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
    _put(out_dir, {**st, "attempt": n, "started_at": started, "reason": "", "status": "ok", WALL: wall})
    return {"ok": True, "done": True, "give_up": False, "reason": "", "attempt": n}
