"""差分の審査の返答の works 側の 2 判定の欄（依頼 218）。

1 回目の差分の審査の役（p3.delta_review）に、承認済みの修正案の項目への準拠（compliance）と、差分の品質（quality）の 2 つの
判定を書かせる。写しの graph の型は欄を持てない（写しはバイト一致で縛られる）ので、修正案の works の欄（planmarks）と同じく、
役の型にだけ欄を足し、受け付けが盤面へ渡す前に外して今の周の作業ファイル delta-verdicts.json に置く。2 回目の審査
（p3.delta_review2）には重ねない。
- with_verdicts(node, schema): 役の型（accept.role_schema が重ねる）
- gaps(reply, items): 欠けと誤りの行（審査の受け付けが拒む。拒否の理由は書いた役に戻り、その役が直せる）。items は
  承認済みの修正案の項目（planmarks.approved_items。無い run は None か空で、準拠は not_applicable）
- split(reply)・save(b, verdicts)・read(b)・fail_rows(verdicts): 欄を外す口・盤面の外の控え・準拠の落ちた行
語:
- 準拠の行: compliance.items の 1 行 {item（修正案の項目の番号）, kind, face_key, why}
- 落ちた行: kind が missing（足すと言った物が無い）・extra（範囲の外の物を足した）・misunderstood（項目の読み違え）の行。
  差分の中の所を faces に挙げ、その key を face_key に写して結ぶ（穴は写しの規則が手直しの義務に積む形のまま）
- 結ばれない穴: faces の key のうち、どの準拠の行の face_key にも無い物。在れば品質は fail、無ければ pass

写しの engine の型の検査（engine.schema。L0 の写し）だけを使い、accept・refix・entry を import しない（accept がこの模块を
読むので、輪を作らない）。
"""
from __future__ import annotations

import copy
import json
import os
import pathlib
import sys

_GL = pathlib.Path(__file__).resolve().parent / "graphloops"
if str(_GL) not in sys.path:
    sys.path.insert(0, str(_GL))

from engine.schema import validate_schema  # noqa: E402

NODE = "p3.delta_review"
NODES = (NODE,)                       # 2 回目の審査（p3.delta_review2）は含めない
VERDICTS_FILE = "delta-verdicts.json"   # 今の周の作業ファイル {"round": 周, "compliance": …, "quality": …}
SAVED_OP = "delta_verdicts_saved"       # save が盤面の trace に書く行 {compliance: 判定, quality: 判定}
COMPLIANCE = ("pass", "fail", "unverifiable", "not_applicable")
QUALITY = ("pass", "fail")
KINDS = ("missing", "extra", "misunderstood", "unverifiable")
FAIL_KINDS = ("missing", "extra", "misunderstood")   # 落ちた行の kind（faces の穴に結ぶ）
MIN_WHY = 20
KEYS = ("compliance", "quality")
_WHY = {"type": "string", "minLength": MIN_WHY}
FIELD_SCHEMA = {
    "compliance": {"type": "object", "additionalProperties": False, "required": ["verdict", "items", "read"], "properties": {
        "verdict": {"type": "string", "enum": list(COMPLIANCE)},
        "items": {"type": "array", "items": {
            "type": "object", "additionalProperties": False, "required": ["item", "kind", "face_key", "why"],
            "properties": {"item": {"type": "integer", "minimum": 1}, "kind": {"type": "string", "enum": list(KINDS)},
                           "face_key": {"type": "string"}, "why": _WHY}}},
        "read": _WHY}},   # 何を読んで判じたか
    "quality": {"type": "object", "additionalProperties": False, "required": ["verdict", "why"], "properties": {
        "verdict": {"type": "string", "enum": list(QUALITY)}, "why": _WHY}},
}

REJECT = ("差分の審査の返答の 2 判定の欄（準拠 compliance・品質 quality）に欠けか誤りが在る（直して done し直す）。"
          "下の行を直した返答を丸ごと出し直せ:")


# ---------------------------------------------------------------- 役の型
def with_verdicts(node: str, schema: dict) -> dict:
    """役の型に 2 判定の欄を足した写し（NODES の節でなければ渡した物をそのまま返す）"""
    if node not in NODES:
        return schema
    out = copy.deepcopy(schema)
    out["properties"].update(copy.deepcopy(FIELD_SCHEMA))
    out["required"] = [*out.get("required", []), *(k for k in KEYS if k not in out.get("required", []))]
    return out


# ---------------------------------------------------------------- 受け付け
def _face_keys(reply: dict) -> set:
    faces = reply.get("faces")
    return {f["key"] for f in faces if isinstance(f, dict) and isinstance(f.get("key"), str)} if isinstance(faces, list) else set()


def _expected(rows: list) -> str:
    """準拠の行から決まる判定（落ちた行が 1 行でも在れば fail、無くて unverifiable が在れば unverifiable、行が無ければ pass）"""
    kinds = {r["kind"] for r in rows}
    if kinds & set(FAIL_KINDS):
        return "fail"
    return "unverifiable" if "unverifiable" in kinds else "pass"


def gaps(reply: dict, items: list | None) -> list[str]:
    """2 判定の欄の欠けと誤りの行（"compliance…: 理由"・"quality…: 理由"）。空なら通る。型の誤りが在れば型の行だけを返す
    （中身の照らしは型の通った返答にだけ当てる）。例外で拒まない"""
    if not isinstance(reply, dict):
        return ["compliance: 返答が object でない（2 判定の欄を読めない）"]
    out = []
    for k in KEYS:
        if k not in reply:
            out.append(f"{k}: 無い（works の欄。型の {k} を見よ）")
        else:
            out += validate_schema(reply[k], FIELD_SCHEMA[k], k)
    if out:
        return out
    comp, qual = reply["compliance"], reply["quality"]
    rows, verdict, n = comp["items"], comp["verdict"], len(items or [])
    faces = _face_keys(reply)
    if not n:
        if verdict != "not_applicable":
            out.append(f"compliance.verdict（{verdict}）: 承認済みの修正案の項目が無い run は not_applicable にせよ")
        if rows:
            out.append("compliance.items: 承認済みの修正案の項目が無い run は空の並びにせよ")
    elif verdict == "not_applicable":
        out.append(f"compliance.verdict（not_applicable）: 承認済みの修正案の項目が {n} 個在る。"
                   "pass・fail・unverifiable のどれかにせよ")
    for j, r in enumerate(rows):
        if n and not 1 <= r["item"] <= n:
            out.append(f"compliance.items[{j}].item（{r['item']}）: 承認済みの修正案の項目の番号は 1〜{n}")
        if r["kind"] in FAIL_KINDS and r["face_key"] not in faces:
            out.append(f"compliance.items[{j}].face_key（{r['face_key']}）: faces の key に無い。"
                       "差分の中の所を faces に挙げて face_key で結べ")
    if n and verdict != "not_applicable" and verdict != _expected(rows):
        out.append(f"compliance.verdict（{verdict}）: 行から決まる値は {_expected(rows)}（missing・extra・misunderstood が"
                   "1 行でも在れば fail、無くて unverifiable が在れば unverifiable、行が無ければ pass）")
    untied = sorted(faces - {r["face_key"] for r in rows})
    want = "fail" if untied else "pass"
    if qual["verdict"] != want:
        why = (f"準拠の行に結ばれない穴が在る（{'・'.join(untied)}）" if untied else "準拠の行に結ばれない穴が無い")
        out.append(f"quality.verdict（{qual['verdict']}）: {why}ので {want} にせよ")
    return out


def split(reply: dict) -> tuple[dict, dict]:
    """（2 判定の欄を外した返答の写し, {compliance, quality}）。gaps を通った返答に使う（渡した返答は変えない）"""
    out = copy.deepcopy(reply)
    return out, {k: out.pop(k) for k in KEYS if k in out}


# ---------------------------------------------------------------- 盤面の外の控え
def save(b, verdicts: dict) -> None:
    """今の周の作業ファイル b.work(VERDICTS_FILE) を {"round": b.round, **verdicts} で置き換え（一時のファイルから os.replace）、
    盤面の trace に SAVED_OP の行を 1 行足す（b は work・round・trace を読む）"""
    p = b.work(VERDICTS_FILE)
    tmp = p.with_name(p.name + ".tmp")
    tmp.write_text(json.dumps({"round": b.round, **verdicts}, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    os.replace(tmp, p)
    b.trace(SAVED_OP, compliance=verdicts["compliance"]["verdict"], quality=verdicts["quality"]["verdict"])


def read(b) -> dict | None:
    """今の周の控え。無い・周が違う・読めないなら None"""
    try:
        doc = json.loads(b.work(VERDICTS_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return doc if isinstance(doc, dict) and doc.get("round") == b.round else None


def fail_rows(verdicts: dict | None) -> list[dict]:
    """控えの準拠の落ちた行（kind が missing・extra・misunderstood）。控えが無い・形が違えば空"""
    comp = verdicts.get("compliance") if isinstance(verdicts, dict) else None
    rows = comp.get("items") if isinstance(comp, dict) else None
    return [r for r in rows if isinstance(r, dict) and r.get("kind") in FAIL_KINDS] if isinstance(rows, list) else []
