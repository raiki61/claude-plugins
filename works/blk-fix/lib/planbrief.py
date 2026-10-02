"""承認済みの修正案を項目ごとの brief に切り出して凍結する（blk-fix。依頼 217）。AI を通さず、機械が盤面の物だけから書く。

語:
- brief: 修正案の 1 項目の要求の正本。修正役・TDD の役の指示書の頭で名指し、役はこれに従う。判定の単位は「背景」の節に参照として
  並べる（brief と食い違えば役は自分で解かずに申し出る）
- 控え（LEDGER）: 今の周の作業ファイル r<N>/briefs.json。{"briefs": [{item, unit_keys, file, sha256, text}]}。file は周の箱
  （r<N>/）からの名、text は書いた文、sha256 はその文の UTF-8 のバイトの sha256
- 凍結: 控えが在る周では brief を作り直さない。brief のファイルの sha256 が控えと違えば控えの text で書き戻し、盤面の trace に
  RESTORED_OP の行を残す（役が brief を書き換えても、次に読むのは承認された時の文）

読む物（どれも盤面の物。entry・planmarks・structmark の口だけ）:
- 承認済みの修正案: 盤面の outputs の p2.fix_plan の file（今の周の物だけ）の plan。項目の並びは控え plan-fields.json と同じ
- 項目の works の欄: planmarks.read(b)（今の周の plan-fields.json）
- 判定の単位 b.record["units"]・凍結した目的の文（record.process.purpose.purpose_text）・構造の目の行（structmark.plan_section）

同じ入力からはバイト単位で同じ文を書く（時刻を書かない。辞書は書いた順）。

- render: 1 項目の brief の文（純粋な関数）
- cut / cut_at: 今の周の brief を書いて凍結する（在れば書き戻すだけ）。返りは {item, unit_keys, file（絶対パス）, sha256} の並び
- for_units: 単位の key に当たる項目の行だけ
- head_text: 指示書の頭に置く、brief を名指す節
- files: 今の周の brief のファイル（読んだ証拠に足す）
"""
from __future__ import annotations

import hashlib
import json
import pathlib
import sys

sys.dont_write_bytecode = True

_CORE = pathlib.Path(__file__).resolve().parents[2] / ".shared" / "core"
if str(_CORE) not in sys.path:
    sys.path.insert(0, str(_CORE))

from board import BoardGap  # noqa: E402  （board が写しの engine を sys.path に足す）
import entry  # noqa: E402
import planmarks  # noqa: E402
import structmark  # noqa: E402

PLAN_NODE = "p2.fix_plan"
LEDGER = "briefs.json"
NAME = "brief-{n}.md"
HEAD = "## 要求の正本（brief）"
RESTORED_OP = "brief_restored"
BACKGROUND = "背景（参照。brief と食い違えば自分で解かずに申し出よ）"
READ_ALL = "まず Read で全部読め。下の決まりの『要求の正本（brief）と背景』に従え"
NONE = "無し"


class LedgerBroken(ValueError):
    """控え briefs.json が読めない・形が違う・text と sha256 が合わない（凍結を作り直して隠さず、ここで止める）"""


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
        return f"### {key}\n\n判定の記録に無い単位"
    rx = u.get("prescriptions")
    head = f"### {key}\n\n- label: {u.get('label')}\n- disposition: {u.get('disposition', NONE)}\n- reason: {u.get('reason')}\n"
    return head + (f"- prescriptions:\n\n```json\n{_json(rx)}\n```" if rx else f"- prescriptions: {NONE}")


def render(n: int, item: dict, fields: dict, units: dict, purpose: str, structure: str) -> str:
    """修正案の項目 n（1 始まり）の brief の文。item は修正案の項目、fields はその項目の works の欄（planmarks の控えの行）、
    units は判定の単位の key → 単位、purpose は凍結した目的の文、structure は構造の目の節（structmark.plan_section。空なら無し）"""
    keys = [k for k in item.get("unit_keys") or [] if isinstance(k, str)]
    parts = [
        f"# 要求の正本: 修正案の項目 {n}",
        "## 直す単位\n\n" + _bullets(keys, str),
        f"## やり方（approach）\n\n{item.get('approach') or NONE}",
        "## 足す物（adds）\n\n" + _bullets(item.get("adds") or [], _add),
        "## 消す物（removes）\n\n" + _bullets(item.get("removes") or [], str),
        f"## 足さずに閉じる形（shrink_first）\n\n{item.get('shrink_first') or NONE}",
        "## 狭める能力（narrows）\n\n" + _bullets(item.get("narrows") or [], _narrow),
        "## 直し方の道（route）\n\n" + _route(fields),
        "## 受け入れのテスト（tests）\n\n" + _bullets(fields.get("tests") or [], _test),
        "## 書き換えてよい既存のテスト（rewrite_tests）\n\n" + _bullets(fields.get("rewrite_tests") or [], _rewrite),
        "## 整えの申告（refactor）\n\n" + _refactor(fields),
        f"## 目的の文（凍結）\n\n{purpose or NONE}",
        structure or f"## 構造の目の行\n\n{NONE}",
        f"## {BACKGROUND}\n\n" + ("\n\n".join(_unit(k, units) for k in keys) if keys else NONE),
    ]
    return "\n\n".join(parts) + "\n"


# ---------------------------------------------------------------- 凍結
def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _box(b) -> pathlib.Path:
    """今の周の箱 r<N>/（作らない。b.work と同じ置き場）"""
    return pathlib.Path(b.dir) / f"r{b.round}"


def _plan(b) -> list | None:
    """今の周の承認済みの修正案の plan。出力が無い・前の周の物・読めないなら None"""
    out = (b.state.get("outputs") or {}).get(PLAN_NODE)
    if not isinstance(out, dict) or out.get("round") != b.round or not isinstance(out.get("file"), str):
        return None
    try:
        doc = json.loads((pathlib.Path(b.dir) / out["file"]).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    plan = doc.get("plan") if isinstance(doc, dict) else None
    return plan if isinstance(plan, list) else None


def _ledger(b) -> list | None:
    """今の周の控えの行。控えが無ければ None。在るのに読めない・形が違う・text と sha256 が合わなければ LedgerBroken"""
    p = _box(b) / LEDGER
    if not p.is_file():
        return None
    try:
        rows = json.loads(p.read_text(encoding="utf-8")).get("briefs")
    except (OSError, ValueError, AttributeError) as e:
        raise LedgerBroken(f"brief の控え {p} を読めない: {e}") from None
    if not isinstance(rows, list):
        raise LedgerBroken(f"brief の控え {p} に briefs の並びが無い")
    for r in rows:
        if not (isinstance(r, dict) and isinstance(r.get("text"), str) and isinstance(r.get("file"), str)
                and pathlib.PurePosixPath(r["file"]).name == r["file"] and r.get("sha256") == _sha(r["text"])):
            raise LedgerBroken(f"brief の控え {p} の行が形を成さないか、text と sha256 が合わない: {str(r)[:200]}")
    return rows


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
            same = hashlib.sha256(p.read_bytes()).hexdigest() == r["sha256"]
        except OSError:
            same = False
        if not same:
            p.write_bytes(r["text"].encode("utf-8"))
            fixed.append(str(p.resolve()))
    if fixed:
        b.trace(RESTORED_OP, files=fixed)


def cut(b) -> list[dict]:
    """今の周の brief を返す。控えが無ければ、修正案の出力と planmarks.read(b) が両方在る時だけ項目ごとに render して書き、控えを
    書く（どちらか無ければ [] で何も書かない）。控えが在れば作り直さず、控えと違うファイルを書き戻す"""
    rows = _ledger(b)
    if rows is not None:
        _restore(b, rows)
        return _out(b, rows)
    plan, fields = _plan(b), planmarks.read(b)
    if plan is None or fields is None:
        return []
    if len(fields) != len(plan):
        raise LedgerBroken(f"修正案の項目の数 {len(plan)} と盤面の控え {planmarks.FIELDS_FILE} の欄の数 {len(fields)} が違う"
                           "（同じ周の受け付けが同じ並びで書く物）")
    units = {u["key"]: u for u in b.record.get("units") or [] if isinstance(u, dict) and isinstance(u.get("key"), str)}
    purpose = ((b.record.get("process") or {}).get("purpose") or {}).get("purpose_text") or ""
    structure = structmark.plan_section(b.dir)
    rows = []
    for n, (item, f) in enumerate(zip(plan, fields), 1):
        item = item if isinstance(item, dict) else {}
        text = render(n, item, f if isinstance(f, dict) else {}, units, purpose, structure)
        name = NAME.format(n=n)
        b.work(name).write_bytes(text.encode("utf-8"))
        rows.append({"item": n, "unit_keys": [k for k in item.get("unit_keys") or [] if isinstance(k, str)], "file": name,
                     "sha256": _sha(text), "text": text})
    b.work(LEDGER).write_text(json.dumps({"briefs": rows}, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return _out(b, rows)


def cut_at(board_dir) -> list[dict]:
    """盤面を（止まっていても）開いて cut。盤面が開けなければ []"""
    try:
        b = entry.open_board(pathlib.Path(board_dir), allow_halted=True)
    except BoardGap:
        return []
    return cut(b)


# ---------------------------------------------------------------- 読む口
def for_units(briefs: list, keys) -> list[dict]:
    """unit_keys が keys と重なる項目の行（項目の順。1 つの単位が 2 項目に在れば両方）"""
    want = set(keys)
    return [r for r in briefs if want & set(r.get("unit_keys") or [])]


def head_text(briefs: list) -> str:
    """指示書の頭に置く、brief を名指す節。brief が無ければ空"""
    if not briefs:
        return ""
    rows = [f"- 項目 {r['item']}: {r['file']}（sha256 {r['sha256']}・単位 {'、'.join(r.get('unit_keys') or []) or NONE}）"
            for r in briefs]
    return f"{HEAD}\n\n" + "\n".join(rows) + f"\n\n{READ_ALL}"


def files(b) -> list[str]:
    """今の周の控えに在る brief のファイル（絶対パス）。控えが無ければ []"""
    return [r["file"] for r in _out(b, _ledger(b) or [])]
