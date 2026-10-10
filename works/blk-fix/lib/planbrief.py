"""承認済みの修正案を項目ごとの brief に切り出して凍結する（blk-fix。依頼 217）。AI を通さず、機械が盤面の物だけから書く。

語:
- brief: 修正案の 1 項目の要求の正本。修正役・TDD の役の指示書の頭で名指し、役はこれに従う。判定の単位は「背景」の節に参照として
  並べる（brief と食い違えば brief が勝つ。役は brief が誤りと見た時だけ申し出る）
- 控え（LEDGER）: 今の周の作業ファイル r<N>/briefs.json。{"briefs": [{item, unit_keys, file, sha256, text}]}。file は周の箱
  （r<N>/）からの名、text は書いた文、sha256 はその文の UTF-8 のバイトの sha256
- 凍結: 控えが在る周では brief を作り直さない。brief のファイルの sha256 が控えと違えば控えの text で書き戻し、盤面の trace に
  RESTORED_OP の行を残す（役が brief を書き換えても、次に読むのは承認された時の文）。書き戻しはリンクの先へ書かない（リンクや
  普通のファイルでない物は消してから書く。ディレクトリなら LedgerBroken）
- 切った印（CUT_OP）: 周の 1 回目の cut が trace に 1 行 {round, ledger_sha256（控えのファイルのバイトの sha256）, files} を書く。
  後の cut は、印の在る周で控えが無い（消して作り直させる）・控えのバイトの sha256 が印と違う（text と sha256 を揃えて書き換えた）・
  印の無い控え（cut の外で置いた）を LedgerBroken で止める。控えは一時のファイルから os.replace で置く
- 切り直し（RECUT_OP。依頼 226）: 今の周の trace で、承認済みの項目の差し替えの印（planmarks.AMEND_OP）の行が最後の CUT_OP の行
  より後に在る時だけ、その行（後に在る物全部）の items の項目を今の承認済みの項目（planmarks.plan_items と凍結した欄）から描き
  直し、文が変わった項目だけファイルを書き、控えを置き直して trace に RECUT_OP {round, items} と CUT_OP の行を書く。行の前後は
  trace の行の並びで決める（時刻で比べない）。amend を通らない save し直しでは切り直さない（凍結のまま）
- 呼ぶ時: cut・cut_at は今の周の承認済みの修正案（差し替えを重ねた物）を凍結する。事前審査（p2.plan_review）と人の関所（p2.human_gate）を
  抜けた後にだけ呼ぶ（前に呼ぶと、承認されていない案がその周の正本になる）

読む物（どれも盤面の物。entry・planmarks・structmark の口だけ）:
- 承認済みの修正案: planmarks.plan_items(b)（今の周の p2.fix_plan の出力の plan に、差し替えた項目の核の欄を重ねた物）。
  項目の並びは控え plan-fields.json と同じ
- 項目の works の欄: planmarks.frozen(b)（今の周の plan-fields.json。凍結の印と食い違えば LedgerBroken に替えて止める）
- 判定の単位 b.record["units"]・凍結した目的の文（record.process.purpose.purpose_text）・構造の目の行（structmark.plan_section）

同じ入力からはバイト単位で同じ文を書く（時刻を書かない。辞書は書いた順）。

- render: 1 項目の brief の文（純粋な関数）
- cut / cut_at: 今の周の brief を書いて凍結する（在れば書き戻すだけ）。返りは {item, unit_keys, file（絶対パス）, sha256} の並び
- by_unit_at: 今の周の控えの brief を単位ごとに {unit_key: [{item, file（絶対パス）}]}（切らない・書き戻さない。食い違いの申し出の
  brief_vs_judgment の確かめが読む。盤面が開けない・控えが無い・壊れているなら {}）
- for_units: 単位の key に当たる項目の行だけ
- head_text: 指示書の頭に置く、brief を名指す節（今直す単位を渡すと、項目のほかの単位に「今は直すな」と添える。単位の書き方は unit_note。
  TDD の輪は今の単位と一緒に直す同じ項目の単位も今直す単位に渡す）
- files: 今の周の brief のファイル（読んだ証拠に足す）
"""
from __future__ import annotations

import hashlib
import json
import os
import pathlib
import sys

sys.dont_write_bytecode = True

_CORE = pathlib.Path(__file__).resolve().parents[2] / ".shared" / "core"
if str(_CORE) not in sys.path:
    sys.path.insert(0, str(_CORE))

from board import BoardGap  # noqa: E402  （board が写しの engine を sys.path に足す）
import entry  # noqa: E402
import planmarks  # noqa: E402
import promptsection  # noqa: E402
import structmark  # noqa: E402

LEDGER = "briefs.json"
NAME = "brief-{n}.md"
HEAD = promptsection.Section("## 要求の正本（brief）", source="fn:planbrief.head_text")
RESTORED_OP = "brief_restored"
CUT_OP = "brief_cut"   # 周の 1 回目の cut と切り直しの印（trace）
RECUT_OP = "brief_recut"   # 差し替えの印の後の切り直しの印 {round, items: [番号…]}（trace。直後に CUT_OP の行）
BACKGROUND = "背景（参照。brief と食い違えば brief が勝つ。brief が誤りと見たら申し出よ）"
READ_ALL = "まず Read で全部読め。下の決まりの『brief の決まり（要求の正本と背景）』に従え"
NONE = "無し"
_FN = "fn:planbrief.render"
TITLE = promptsection.Section("# 要求の正本: 修正案の項目 {n}", source=_FN)
UNITS_HEAD = promptsection.Section("## 直す単位", source=_FN)
APPROACH_HEAD = promptsection.Section("## やり方（approach）", source=_FN)
ADDS_HEAD = promptsection.Section("## 足す物（adds）", source=_FN)
REMOVES_HEAD = promptsection.Section("## 消す物（removes）", source=_FN)
SHRINK_HEAD = promptsection.Section("## 足さずに閉じる形（shrink_first）", source=_FN)
NARROWS_HEAD = promptsection.Section("## 狭める能力（narrows）", source=_FN)
ROUTE_HEAD = promptsection.Section("## 直し方の道（route）", source=_FN)
TESTS_HEAD = promptsection.Section("## 受け入れのテスト（tests）", source=_FN)
REWRITE_HEAD = promptsection.Section("## 書き換えてよい既存のテスト（rewrite_tests）", source=_FN)
REFACTOR_HEAD = promptsection.Section("## 整えの申告（refactor）", source=_FN)
ALLOWED_HEAD = promptsection.Section("## 書いてよいパス（allowed_paths）", source=_FN)
OUT_OF_SCOPE_HEAD = promptsection.Section("## 触らない物（out_of_scope）", source=_FN)
PURPOSE_HEAD = promptsection.Section("## 目的の文（凍結）", source=_FN)
STRUCTURE_ROW_HEAD = promptsection.Section("## 構造の目の行", source=_FN)
STRUCTURE_HEAD = promptsection.Section("## 構造の目の行と処方への答え（structure）", source=_FN)
BACKGROUND_HEAD = promptsection.Section(f"## {BACKGROUND}", source=_FN)
UNIT_HEAD = promptsection.Section("### {key}", source="fn:planbrief._unit")

# 受け手の宣言（役の印の名 ← 節 ← 入る条件を判じる関数）。brief の節は、直す役の全部（枝・輪・裁定の後の役）の頭に貼る
_BRIEFED = ("fix", "fix-ruled", "fix-lane-1", "fix-lane-2", "fix-lane-3", "tdd", "tdd-lane-1", "tdd-lane-2", "tdd-lane-3", "tdd-rest")
RECEIVES = [
    *(promptsection.Receive(role, head, "planbrief.render") for role in _BRIEFED for head in (
        TITLE, UNITS_HEAD, APPROACH_HEAD, ADDS_HEAD, REMOVES_HEAD, SHRINK_HEAD, NARROWS_HEAD, ROUTE_HEAD, TESTS_HEAD, REWRITE_HEAD,
        REFACTOR_HEAD, ALLOWED_HEAD, OUT_OF_SCOPE_HEAD, PURPOSE_HEAD, STRUCTURE_ROW_HEAD, STRUCTURE_HEAD, BACKGROUND_HEAD)),
    *(promptsection.Receive(role, UNIT_HEAD, "planbrief._unit") for role in _BRIEFED),
    *(promptsection.Receive(role, HEAD, "planbrief.head_text") for role in _BRIEFED),
    *(promptsection.Receive(role, structmark.PLAN_HEAD, "structmark.plan_section") for role in _BRIEFED),
]
UNSCOPED = "無し（この案は範囲を決めていない。範囲では縛らない）"   # 範囲の欄の無い項目（依頼 218 より前の案）の範囲の節
NOT_NOW = "今は直すな"   # brief の行で、項目の単位のうち今直す単位でない物の頭（head_text）


class LedgerBroken(ValueError):
    """控え briefs.json が読めない・形が違う・text と sha256 が合わない・切った印と合わない・brief の置き場がディレクトリ・
    cut・切り直しで読む欄の控え plan-fields.json が凍結の印と合わない（planmarks.FieldsBroken。凍結を作り直して隠さず、ここで止める）"""


# ---------------------------------------------------------------- 文
def _json(v) -> str:
    return json.dumps(v, ensure_ascii=False, indent=1)


def _bullets(rows: list, line) -> str:
    return "\n".join(f"- {line(r)}" for r in rows) if rows else NONE


def _add(r) -> str:
    if isinstance(r, dict):
        return f"{r.get('kind')}: {r.get('name')}（正本: {r.get('canonical')}）"
    return str(r)


def _narrow(r) -> str:
    if isinstance(r, dict):
        return f"{r.get('what')}——{r.get('why')}"
    return str(r)


def _test(r) -> str:
    if not isinstance(r, dict):
        return str(r)
    return (f"`{r.get('id')}`\n  - behavior: {r.get('behavior')}\n  - path: {r.get('path')}\n"
            f"  - red_kind: {r.get('red_kind')}\n  - red_why: {r.get('red_why')}")


def _rewrite(r) -> str:
    if not isinstance(r, dict):
        return str(r)
    return (f"`{r.get('id')}`（書き換えてよい範囲 limit: {r.get('limit') or '引けない（書き換えは許されない）'}）\n"
            f"  - behavior: {r.get('behavior')}\n  - old: {r.get('old')}\n  - new: {r.get('new')}")


def _scope(r) -> str:
    if isinstance(r, dict):
        return f"{r.get('glob')}——{r.get('why')}"
    return str(r)


def _scoped(fields: dict, key: str, line) -> str:
    """範囲の欄 key の節の中身。欄の無い行（依頼 218 より前の案）は UNSCOPED（範囲で縛らない）、在って空なら無し"""
    if key not in fields:
        return UNSCOPED
    return _bullets(fields.get(key) or [], line)


def _route(fields: dict) -> str:
    route = fields.get("route")
    if route is None:
        return NONE
    why = fields.get("route_why")
    return f"{route}（理由: {why}）" if isinstance(why, str) and why.strip() else str(route)


def _refactor(fields: dict) -> str:
    rf = fields.get("refactor")
    if not isinstance(rf, dict):
        return NONE
    return f"declared: {'true' if rf.get('declared') is True else 'false'}" + (f"（理由: {rf['why']}）" if rf.get("why") else "")


def _unit(key: str, units: dict) -> str:
    u = units.get(key)
    if not isinstance(u, dict):
        return f"{UNIT_HEAD.format(key=key)}\n\n判定の記録に無い単位"
    rx = u.get("prescriptions")
    head = f"{UNIT_HEAD.format(key=key)}\n\n- label: {u.get('label')}\n- disposition: {u.get('disposition') or NONE}\n- reason: {u.get('reason')}\n"
    return head + (f"- prescriptions:\n\n```json\n{_json(rx)}\n```" if rx else f"- prescriptions: {NONE}")


def render(n: int, item: dict, fields: dict, units: dict, purpose: str, structure: str) -> str:
    """修正案の項目 n（1 始まり）の brief の文。item は修正案の項目、fields はその項目の works の欄（planmarks の控えの行）、
    units は判定の単位の key → 単位、purpose は凍結した目的の文、structure は構造の目の節（structmark.plan_section。空なら無し）"""
    keys = [k for k in item.get("unit_keys") or [] if isinstance(k, str)]
    parts = [
        TITLE.format(n=n),
        f"{UNITS_HEAD}\n\n" + _bullets(keys, str),
        f"{APPROACH_HEAD}\n\n{item.get('approach') or NONE}",
        f"{ADDS_HEAD}\n\n" + _bullets(item.get("adds") or [], _add),
        f"{REMOVES_HEAD}\n\n" + _bullets(item.get("removes") or [], str),
        f"{SHRINK_HEAD}\n\n{item.get('shrink_first') or NONE}",
        f"{NARROWS_HEAD}\n\n" + _bullets(item.get("narrows") or [], _narrow),
        f"{ROUTE_HEAD}\n\n" + _route(fields),
        f"{TESTS_HEAD}\n\n" + _bullets(fields.get("tests") or [], _test),
        f"{REWRITE_HEAD}\n\n" + _bullets(fields.get("rewrite_tests") or [], _rewrite),
        f"{REFACTOR_HEAD}\n\n" + _refactor(fields),
        f"{ALLOWED_HEAD}\n\n" + _scoped(fields, "allowed_paths", str),
        f"{OUT_OF_SCOPE_HEAD}\n\n" + _scoped(fields, "out_of_scope", _scope),
        f"{PURPOSE_HEAD}\n\n{purpose or NONE}",
        structure or f"{STRUCTURE_ROW_HEAD}\n\n{NONE}",
        f"{STRUCTURE_HEAD}\n\n" + _bullets(fields.get("structure") or [], planmarks.answer_line),
        f"{BACKGROUND_HEAD}\n\n" + ("\n\n".join(_unit(k, units) for k in keys) if keys else NONE),
    ]
    return "\n\n".join(parts) + "\n"


# ---------------------------------------------------------------- 凍結
def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _box(b) -> pathlib.Path:
    """控えと brief の置き場（b.work が控えに返す今の周の箱。ディレクトリは b.work が作る）"""
    return pathlib.Path(b.work(LEDGER)).parent


def _drawn(b) -> list[tuple[list, str]] | None:
    """今の周の承認済みの修正案の項目ごとの (unit_keys, brief の文)。案（planmarks.plan_items）か凍結した欄（planmarks.frozen）が
    無ければ None。控えが凍結の印と食い違う・項目と欄の数が違えば LedgerBroken"""
    try:
        fields = planmarks.frozen(b)
        plan = planmarks.plan_items(b)
    except planmarks.FieldsBroken as e:
        raise LedgerBroken(str(e)) from None
    if plan is None or fields is None:
        return None
    if len(fields) != len(plan):
        raise LedgerBroken(f"修正案の項目の数 {len(plan)} と盤面の控え {planmarks.FIELDS_FILE} の欄の数 {len(fields)} が違う"
                           "（同じ周の受け付けが同じ並びで書く物）")
    given = planmarks.prescriptions(b)   # 写しの盤面の記録は単位の処方を写さない（判定の返答から足す。利用者の声 D2）
    units = {u["key"]: {**u, "prescriptions": given.get(u["key"]) or u.get("prescriptions")}
             for u in b.record.get("units") or [] if isinstance(u, dict) and isinstance(u.get("key"), str)}
    purpose = ((b.record.get("process") or {}).get("purpose") or {}).get("purpose_text") or ""
    structure = structmark.plan_section(b.dir)
    out = []
    for n, (item, f) in enumerate(zip(plan, fields), 1):
        item = item if isinstance(item, dict) else {}
        out.append(([k for k in item.get("unit_keys") or [] if isinstance(k, str)],
                    render(n, item, f if isinstance(f, dict) else {}, units, purpose, structure)))
    return out


def _trace_rows(b) -> list[dict]:
    """今の周の trace の行（行の並びのまま。読めない行は飛ばす）"""
    try:
        lines = (pathlib.Path(b.dir) / "trace.jsonl").read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    out = []
    for line in lines:
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, dict) and row.get("round") == b.round:
            out.append(row)
    return out


def _mine(b, row: dict) -> bool:
    """CUT_OP の行がこの控えの置き場（_box）の物か。行の ledger（控えの絶対パス）が在れば同じパス、無い行（前の版の盤面）は
    どれも自分の物（同じ周の同じブロックの 2 度目の段は自分の置き場に自分の控えを切る。1 度目の控えの印を自分の物と読まない）"""
    ledger = row.get("ledger")
    return ledger is None or pathlib.Path(ledger) == (_box(b) / LEDGER).resolve()


def _cut_mark(b) -> dict | None:
    """今の周のこの控えの切った印（trace の CUT_OP の行のうち _mine の最後の物）。無ければ None"""
    return next((r for r in reversed(_trace_rows(b)) if r.get("op") == CUT_OP and _mine(b, r)), None)


def _amended_since_cut(b) -> list[int]:
    """今の周のこの控えの最後の CUT_OP の行より後に在る差し替えの印（planmarks.AMEND_OP）の行の items の番号（重ねずに昇順）。
    無ければ []"""
    got: set = set()
    for r in reversed(_trace_rows(b)):
        if r.get("op") == CUT_OP and _mine(b, r):
            break
        if r.get("op") == planmarks.AMEND_OP:
            got.update(n for n in r.get("items") or [] if isinstance(n, int) and not isinstance(n, bool))
    return sorted(got)


def _row_ok(r) -> bool:
    return (isinstance(r, dict) and isinstance(r.get("item"), int) and not isinstance(r.get("item"), bool)
            and isinstance(r.get("unit_keys"), list) and all(isinstance(k, str) for k in r["unit_keys"])
            and isinstance(r.get("text"), str) and isinstance(r.get("file"), str) and isinstance(r.get("sha256"), str)
            and r["file"] not in ("", ".", "..") and pathlib.PurePosixPath(r["file"]).name == r["file"] and "\\" not in r["file"])


def _ledger(b) -> list | None:
    """今の周の控えの行。控えも切った印も無ければ None。次は LedgerBroken: 印が在るのに控えが無い・控えが読めない・行の形が違う・
    行の text と sha256 が合わない・印の無い控え・控えのバイトの sha256 が印と違う"""
    p = _box(b) / LEDGER
    mark = _cut_mark(b)
    if not p.exists():
        if mark is not None:
            raise LedgerBroken(f"周 {b.round} は {CUT_OP} の印が在るのに brief の控え {p} が無い（消して作り直させない）")
        return None
    try:
        raw = p.read_bytes()
        rows = json.loads(raw.decode("utf-8")).get("briefs")
    except (OSError, ValueError, AttributeError) as e:
        raise LedgerBroken(f"brief の控え {p} を読めない: {e}") from None
    if not isinstance(rows, list):
        raise LedgerBroken(f"brief の控え {p} に briefs の並びが無い")
    for r in rows:
        if not _row_ok(r):
            raise LedgerBroken(f"brief の控え {p} の行が形を成さない: {str(r)[:200]}")
        if r["sha256"] != _sha(r["text"]):
            raise LedgerBroken(f"brief の控え {p} の項目 {r['item']} の text と sha256 が合わない")
    if mark is None:
        raise LedgerBroken(f"brief の控え {p} に周 {b.round} の {CUT_OP} の印が無い（cut の外で置いた控えを正本にしない）")
    if mark.get("ledger_sha256") != hashlib.sha256(raw).hexdigest():
        raise LedgerBroken(f"brief の控え {p} のバイトの sha256 が周 {b.round} の {CUT_OP} の印と違う（凍結の後に書き換えた）")
    return rows


def _put(p: pathlib.Path, data: bytes) -> None:
    """data を p に置く。リンクや普通のファイルでない物はリンクの先へ書かずに消してから書く。ディレクトリなら LedgerBroken"""
    if p.is_dir() and not p.is_symlink():
        raise LedgerBroken(f"brief の置き場 {p} がディレクトリ（書き戻せない）")
    if p.is_symlink() or (p.exists() and not p.is_file()):
        p.unlink()
    p.write_bytes(data)


def _write_ledger(p: pathlib.Path, rows: list) -> bytes:
    """控えを一時のファイルから os.replace で置き、置いたバイトを返す（一時のファイルの置き場に先に在る物は消してから書く。
    リンクの先へ書かない）"""
    raw = (json.dumps({"briefs": rows}, ensure_ascii=False, indent=1) + "\n").encode("utf-8")
    tmp = p.with_name(p.name + ".tmp")
    tmp.unlink(missing_ok=True)
    tmp.write_bytes(raw)
    os.replace(tmp, p)
    return raw


def _out(b, rows: list) -> list[dict]:
    box = _box(b).resolve()
    return [{"item": r["item"], "unit_keys": list(r.get("unit_keys") or []), "file": str(box / r["file"]), "sha256": r["sha256"]}
            for r in rows]


def _restore(b, rows: list) -> None:
    """sha256 が控えと違う（消えた・書き換えられた）brief を控えの text で書き戻し、書き戻したファイルを trace に残す"""
    fixed = []
    for r in rows:
        p = _box(b) / r["file"]
        try:
            same = (not p.is_symlink() and p.is_file()
                    and hashlib.sha256(p.read_bytes()).hexdigest() == r["sha256"])
        except OSError:
            same = False
        if not same:
            _put(p, r["text"].encode("utf-8"))
            fixed.append(str(_box(b).resolve() / r["file"]))
    if fixed:
        b.trace(RESTORED_OP, files=fixed)


def _freeze(b, rows: list, recut: list[int] | None = None) -> list[dict]:
    """控えを置き、trace に切った印 CUT_OP を書いて返りの並びを返す。recut（切り直した項目の番号）を渡すと、控えを置いた後・
    CUT_OP の前に RECUT_OP の行を書く"""
    ledger = b.work(LEDGER)
    raw = _write_ledger(ledger, rows)
    if recut is not None:
        b.trace(RECUT_OP, round=b.round, items=recut)
    out = _out(b, rows)
    b.trace(CUT_OP, round=b.round, ledger_sha256=hashlib.sha256(raw).hexdigest(), files=[r["file"] for r in out],
            ledger=str(ledger.resolve()))
    return out


def _recut(b, rows: list, items: list[int]) -> list:
    """差し替えた項目 items を今の承認済みの項目から描き直し、文が変わった項目だけファイルを書いて控えの行を替え、trace に
    RECUT_OP と CUT_OP を書く。描き直す元が無い・項目の数が控えと違う・番号が控えに無ければ LedgerBroken"""
    drawn = _drawn(b)
    if drawn is None or len(drawn) != len(rows):
        raise LedgerBroken(f"周 {b.round} の差し替えの印 {planmarks.AMEND_OP} の後に、brief の控えと同じ数の承認済みの項目が無い"
                           f"（控え {len(rows)} 個・今の項目 {'無し' if drawn is None else len(drawn)}）")
    rows = [dict(r) for r in rows]
    by_item = {r["item"]: r for r in rows}
    for n in items:
        r = by_item.get(n)
        if r is None or not 1 <= n <= len(drawn):
            raise LedgerBroken(f"差し替えの印 {planmarks.AMEND_OP} の項目 {n} が brief の控えに無い")
        keys, text = drawn[n - 1]
        if text != r["text"]:
            _put(_box(b) / r["file"], text.encode("utf-8"))
            r.update(unit_keys=keys, sha256=_sha(text), text=text)
    _freeze(b, rows, recut=items)
    return rows


def cut(b) -> list[dict]:
    """今の周の brief を返す。控えが無ければ、修正案（planmarks.plan_items）と planmarks.frozen(b) が両方在る時だけ項目ごとに
    render して書き、控えを書く（どちらか無ければ [] で何も書かない。欄の控えが凍結の印と食い違えば LedgerBroken）。控えが在れば
    作り直さず、最後の切った印の後に差し替えの印が在る時だけ差し替えた項目を切り直し（_recut）、控えと違うファイルを書き戻す"""
    rows = _ledger(b)
    if rows is not None:
        items = _amended_since_cut(b)
        if items:
            rows = _recut(b, rows, items)
        _restore(b, rows)
        return _out(b, rows)
    drawn = _drawn(b)
    if drawn is None:
        return []
    rows = []
    for n, (keys, text) in enumerate(drawn, 1):
        name = NAME.format(n=n)
        _put(b.work(name), text.encode("utf-8"))
        rows.append({"item": n, "unit_keys": keys, "file": name, "sha256": _sha(text), "text": text})
    return _freeze(b, rows)


def cut_at(board_dir) -> list[dict]:
    """盤面を（止まっていても）開いて cut。盤面が開けなければ []"""
    try:
        b = entry.open_board(pathlib.Path(board_dir), allow_halted=True)
    except BoardGap:
        return []
    return cut(b)


# ---------------------------------------------------------------- 読む口
def by_unit_at(board_dir) -> dict[str, list[dict]]:
    """盤面を（止まっていても）開き、今の周の控えの行を単位ごとに {unit_key: [{item, file（絶対パス）}]}（項目の順）。切らない・
    書き戻さない・trace を書かない。盤面が開けない・控えが無い・控えが壊れている（LedgerBroken）なら {}（brief の無い側＝
    brief_vs_judgment を通さない側に倒す。壊れた控えは次の支度の cut が止める）"""
    try:
        b = entry.open_board(pathlib.Path(board_dir), allow_halted=True)
        rows = _ledger(b) or []
    except (BoardGap, LedgerBroken):
        return {}
    out: dict[str, list[dict]] = {}
    for r in _out(b, rows):
        for k in dict.fromkeys(r["unit_keys"]):
            out.setdefault(k, []).append({"item": r["item"], "file": r["file"]})
    return out


def for_units(briefs: list, keys) -> list[dict]:
    """unit_keys が keys と重なる項目の行（項目の順。1 つの単位が 2 項目に在れば両方）"""
    want = set(keys)
    return [r for r in briefs if want & set(r.get("unit_keys") or [])]


def unit_note(keys: list, owed=None) -> str:
    """項目の単位の並び keys の書き方: owed（今直す単位の key）と重なる物を「、」で並べ（無ければ NONE）、ほかの単位は
    「・今は直すな: …」と添える。owed が None なら keys を全部（head_text の行と fixrules の下請けの実装役の型の題が使う）"""
    keys = list(keys or [])
    want = None if owed is None else set(owed)
    now = keys if want is None else [k for k in keys if k in want]
    rest = [k for k in keys if k not in now]
    return ("、".join(now) or NONE) + (f"・{NOT_NOW}: {'、'.join(rest)}" if rest else "")


def head_text(briefs: list, owed=None) -> str:
    """指示書の頭に置く、brief を名指す節。brief が無ければ空。owed（今直す単位の key）を渡すと、行の「単位」は owed と重なる
    物だけにし、項目のほかの単位（義務から外れた・今の段の外）は「今は直すな」と添えて並べる。None なら項目の単位を全部"""
    if not briefs:
        return ""

    def row(r):
        return f"- 項目 {r['item']}: {r['file']}（sha256 {r['sha256']}・単位 {unit_note(r.get('unit_keys'), owed)}）"
    return f"{HEAD}\n\n" + "\n".join(row(r) for r in briefs) + f"\n\n{READ_ALL}"


def files(b) -> list[str]:
    """今の周の控えに在る brief のファイル（絶対パス）。控えが無ければ []"""
    return [r["file"] for r in _out(b, _ledger(b) or [])]
