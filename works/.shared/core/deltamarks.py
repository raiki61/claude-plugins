"""差分の審査の返答の works 側の 2 判定の欄（依頼 218）。

1 回目の差分の審査の役（p3.delta_review）に、承認済みの修正案の項目への準拠（compliance）と、差分の品質（quality）の 2 つの
判定を書かせる。写しの graph の型は欄を持てない（写しはバイト一致で縛られる）ので、足す・外す・置く・読むの手順は住処
marks（種 delta。役の型にだけ欄を足し、受け付けが盤面へ渡す前に外して今の周の作業ファイルに置く）に任せる。2 回目の審査
（p3.delta_review2）には重ねない。
- with_verdicts(node, schema): 役の型（accept.role_schema が重ねる）
- gaps(reply, items): 欠けと誤りの行（審査の受け付けが拒む。拒否の理由は書いた役に戻り、その役が直せる）。items は
  承認済みの修正案の項目（planmarks.approved_items。無い run は None か空で、準拠は not_applicable）。裁定で外れた項目は
  held（外した裁定の理由）を持ち、その項目の落ちた行は拒む（外れた項目を手直しの義務にしない）
- malformed(reply): faces が穴の並びの形でない返答か（真なら受け付けは 2 判定の欄を照らさず、写しの型に拒ませる）
- split(reply)・save(b, verdicts)・read(b)・fail_rows(verdicts): 欄を外す口・盤面の外の控え・準拠の落ちた行
語:
- 準拠の行: compliance.items の 1 行 {item（修正案の項目の番号）, kind, face_key, why}
- 落ちた行: kind が missing（足すと言った物が無い）・extra（範囲の外の物を足した）・misunderstood（項目の読み違え）の行。
  差分の中の所を faces に挙げ、その key を face_key に写して結ぶ（穴は写しの規則が手直しの義務に積む形のまま）。穴に結ぶのは
  落ちた行だけで、unverifiable の行は face_key を空にする（穴を結べない）
- 結ばれない穴: faces の key のうち、どの落ちた行の face_key にも無い物。在れば品質は fail、無ければ pass

写しの engine の型の検査（engine.schema。L0 の写し）と住処 marks（L1）だけを使い、accept・refix・entry を import しない
（accept がこの模块を読むので、輪を作らない）。
"""
from __future__ import annotations

import pathlib
import sys

_GL = pathlib.Path(__file__).resolve().parent / "graphloops"
if str(_GL) not in sys.path:
    sys.path.insert(0, str(_GL))

from engine.schema import validate_schema  # noqa: E402
import marks  # noqa: E402

NODES = marks.nodes("delta")          # 2 回目の審査（p3.delta_review2）は含めない
NODE = NODES[0]
VERDICTS_FILE = marks.KINDS["delta"].file   # 今の周の作業ファイル {"round": 周, "compliance": …, "quality": …}
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
    return marks.add("delta", node, schema, FIELD_SCHEMA, required=KEYS)


# ---------------------------------------------------------------- 受け付け
def malformed(reply) -> bool:
    """返答が object でないか、faces が key（文字列）を持つ object の並びでないか。真なら 2 判定の欄を照らさない（穴の key の集合が
    決まらない。写しの型が拒み、その文で役に返す）"""
    faces = reply.get("faces") if isinstance(reply, dict) else None
    return not (isinstance(faces, list) and all(isinstance(f, dict) and isinstance(f.get("key"), str) for f in faces))


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
    held = {it.get("item"): it.get("held") for it in items or [] if isinstance(it, dict) and it.get("held")}
    for j, r in enumerate(rows):
        if n and not 1 <= r["item"] <= n:
            out.append(f"compliance.items[{j}].item（{r['item']}）: 承認済みの修正案の項目の番号は 1〜{n}")
        if r["kind"] in FAIL_KINDS and r["item"] in held:
            out.append(f"compliance.items[{j}].item（{r['item']}）: 項目 {r['item']} は裁定で直す義務から外れた（held: "
                       f"{held[r['item']]}）。外れた項目に {r['kind']} の行を書くな（手直しに直させない。最後の人の関所で人が決める）")
        if r["kind"] in FAIL_KINDS and r["face_key"] not in faces:
            out.append(f"compliance.items[{j}].face_key（{r['face_key']}）: faces の key に無い。"
                       "差分の中の所を faces に挙げて face_key で結べ")
        if r["kind"] not in FAIL_KINDS and r["face_key"]:
            out.append(f"compliance.items[{j}].face_key（{r['face_key']}）: unverifiable の行は穴に結ばない。face_key を空にせよ"
                       "（穴に結ぶのは missing・extra・misunderstood の行だけ）")
    if n and verdict != "not_applicable" and verdict != _expected(rows):
        out.append(f"compliance.verdict（{verdict}）: 行から決まる値は {_expected(rows)}（missing・extra・misunderstood が"
                   "1 行でも在れば fail、無くて unverifiable が在れば unverifiable、行が無ければ pass）")
    untied = sorted(faces - {r["face_key"] for r in rows if r["kind"] in FAIL_KINDS})
    want = "fail" if untied else "pass"
    if qual["verdict"] != want:
        why = (f"準拠の行に結ばれない穴が在る（{'・'.join(untied)}）" if untied else "準拠の行に結ばれない穴が無い")
        out.append(f"quality.verdict（{qual['verdict']}）: {why}ので {want} にせよ")
    return out


def split(reply: dict) -> tuple[dict, dict]:
    """（2 判定の欄を外した返答の写し, {compliance, quality}）。渡した返答は変えない。object でない返答はそのままの写しと空"""
    return marks.split("delta", NODE, reply, KEYS)


# ---------------------------------------------------------------- 盤面の外の控え
def save(b, verdicts: dict) -> None:
    """今の周の作業ファイル b.work(VERDICTS_FILE) を {"round": b.round, **verdicts} で置き換え（一時のファイルから os.replace）、
    盤面の trace に SAVED_OP の行を 1 行足す（b は work・round・trace を読む）"""
    marks.write(marks.path_of("delta", b), {"round": b.round, **verdicts})
    b.trace(SAVED_OP, compliance=verdicts["compliance"]["verdict"], quality=verdicts["quality"]["verdict"])


def read(b) -> dict | None:
    """今の周の控え。無い・周が違う・読めないなら None"""
    doc = marks.load(marks.path_of("delta", b))
    return doc if isinstance(doc, dict) and doc.get("round") == b.round else None


def fail_rows(verdicts: dict | None) -> list[dict]:
    """控えの準拠の落ちた行（kind が missing・extra・misunderstood）。控えが無い・形が違えば空"""
    comp = verdicts.get("compliance") if isinstance(verdicts, dict) else None
    rows = comp.get("items") if isinstance(comp, dict) else None
    return [r for r in rows if isinstance(r, dict) and r.get("kind") in FAIL_KINDS] if isinstance(rows, list) else []
