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
- 呼ぶ時: cut・cut_at は今の周の p2.fix_plan の出力をそのまま凍結する。事前審査（p2.plan_review）と人の関所（p2.human_gate）を
  抜けた後にだけ呼ぶ（前に呼ぶと、承認されていない案がその周の正本になる）
- 平の run（修正の形 current。fixshape.plain）: 修正案の欄を修正の段に渡さないので、cut は切らずに []（控えを書かない）

読む物（どれも盤面の物。entry・planmarks・structmark の口だけ）:
- 承認済みの修正案: 今の周の p2.fix_plan の出力（b.output_of_round）の plan。項目の並びは控え plan-fields.json と同じ
- 項目の works の欄: planmarks.frozen(b)（今の周の plan-fields.json。凍結の印と食い違えば LedgerBroken に替えて止める）
- 判定の単位 b.record["units"]・凍結した目的の文（record.process.purpose.purpose_text）・構造の目の行（structmark.plan_section）

同じ入力からはバイト単位で同じ文を書く（時刻を書かない。辞書は書いた順）。

- render: 1 項目の brief の文（純粋な関数）
- cut / cut_at: 今の周の brief を書いて凍結する（在れば書き戻すだけ）。返りは {item, unit_keys, file（絶対パス）, sha256} の並び
- by_unit_at: 今の周の控えの brief を単位ごとに {unit_key: [{item, file（絶対パス）}]}（切らない・書き戻さない。食い違いの申し出の
  brief_vs_judgment の確かめが読む。盤面が開けない・控えが無い・壊れているなら {}）
- for_units: 単位の key に当たる項目の行だけ
- head_text: 指示書の頭に置く、brief を名指す節（今直す単位を渡すと、項目のほかの単位に「今は直すな」と添える）
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
import fixshape  # noqa: E402  （.shared/core。盤面の修正の形）
import planmarks  # noqa: E402
import structmark  # noqa: E402

PLAN_NODE = "p2.fix_plan"
LEDGER = "briefs.json"
NAME = "brief-{n}.md"
HEAD = "## 要求の正本（brief）"
RESTORED_OP = "brief_restored"
CUT_OP = "brief_cut"   # 周の 1 回目の cut の印（trace）
BACKGROUND = "背景（参照。brief と食い違えば brief が勝つ。brief が誤りと見たら申し出よ）"
READ_ALL = "まず Read で全部読め。下の決まりの『brief の決まり（要求の正本と背景）』に従え"
NONE = "無し"
NOT_NOW = "今は直すな"   # brief の行で、項目の単位のうち今直す単位でない物の頭（head_text）


class LedgerBroken(ValueError):
    """控え briefs.json が読めない・形が違う・text と sha256 が合わない・切った印と合わない・brief の置き場がディレクトリ・
    1 回目の cut で読む欄の控え plan-fields.json が凍結の印と合わない（planmarks.FieldsBroken。凍結を作り直して隠さず、ここで止める）"""


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
    head = f"### {key}\n\n- label: {u.get('label')}\n- disposition: {u.get('disposition') or NONE}\n- reason: {u.get('reason')}\n"
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
    """今の周の承認済みの修正案の plan。今の周に出していない・plan が並びでないなら None"""
    doc = b.output_of_round(PLAN_NODE, b.round)
    plan = doc.get("plan") if isinstance(doc, dict) else None
    return plan if isinstance(plan, list) else None


def _cut_mark(b) -> dict | None:
    """今の周の切った印（trace の CUT_OP の行の最後の物）。無ければ None"""
    try:
        lines = (pathlib.Path(b.dir) / "trace.jsonl").read_text(encoding="utf-8").splitlines()
    except OSError:
        return None
    mark = None
    for line in lines:
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, dict) and row.get("op") == CUT_OP and row.get("round") == b.round:
            mark = row
    return mark


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


def cut(b) -> list[dict]:
    """今の周の brief を返す。控えが無ければ、修正案の出力と planmarks.frozen(b) が両方在る時だけ項目ごとに render して書き、控えを
    書く（どちらか無ければ [] で何も書かない。欄の控えが凍結の印と食い違えば LedgerBroken）。控えが在れば作り直さず、控えと違う
    ファイルを書き戻す。平の run（修正の形 current。fixshape.plain）は修正案の欄を修正の段に渡さないので、いつも [] で何も書かない
    （形の控えが壊れていれば LedgerBroken）"""
    try:
        plain = fixshape.plain(b.dir)
    except ValueError as e:
        raise LedgerBroken(f"盤面の修正の形が読めない: {e}") from None
    if plain:
        return []
    rows = _ledger(b)
    if rows is not None:
        _restore(b, rows)
        return _out(b, rows)
    try:
        fields = planmarks.frozen(b)
    except planmarks.FieldsBroken as e:
        raise LedgerBroken(str(e)) from None
    plan = _plan(b)
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
        _put(b.work(name), text.encode("utf-8"))
        rows.append({"item": n, "unit_keys": [k for k in item.get("unit_keys") or [] if isinstance(k, str)], "file": name,
                     "sha256": _sha(text), "text": text})
    raw = _write_ledger(b.work(LEDGER), rows)
    out = _out(b, rows)
    b.trace(CUT_OP, round=b.round, ledger_sha256=hashlib.sha256(raw).hexdigest(), files=[r["file"] for r in out])
    return out


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


def head_text(briefs: list, owed=None) -> str:
    """指示書の頭に置く、brief を名指す節。brief が無ければ空。owed（今直す単位の key）を渡すと、行の「単位」は owed と重なる
    物だけにし、項目のほかの単位（義務から外れた・今の段の外）は「今は直すな」と添えて並べる。None なら項目の単位を全部"""
    if not briefs:
        return ""
    want = None if owed is None else set(owed)

    def row(r):
        keys = list(r.get("unit_keys") or [])
        now = keys if want is None else [k for k in keys if k in want]
        rest = [k for k in keys if k not in now]
        tail = f"・{NOT_NOW}: {'、'.join(rest)}" if rest else ""
        return f"- 項目 {r['item']}: {r['file']}（sha256 {r['sha256']}・単位 {'、'.join(now) or NONE}{tail}）"
    return f"{HEAD}\n\n" + "\n".join(row(r) for r in briefs) + f"\n\n{READ_ALL}"


def files(b) -> list[str]:
    """今の周の控えに在る brief のファイル（絶対パス）。控えが無ければ []"""
    return [r["file"] for r in _out(b, _ledger(b) or [])]
