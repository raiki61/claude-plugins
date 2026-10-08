"""手直しの役（refix・refix2）の指示書の組み立て。AI を通さず、機械が書く役の決まりの正本（rulebook.CANON）のうちこの役に
当たる節（NOT_HERE の外）を字のまま載せ、手直しの決まり（rules/refix.md）と run の値を繋ぐ。同じ入力からはバイト単位で同じ。

並び: 役の頭（refix-head-<n>）→ 正本の節（NOT_HERE を除いた全部。ファイルの順）→ 読み替え（refix-remap。正本より勝つ）→ 手直しだけの決まり
（refix-keep）→ 借りたスキルの座（seat。修正の形 g3 の receiving-code-review。呼び手の支度 scripts/prep.py が
seat.section で組んで渡す。空なら載せない）→ 返答（refix-reply。どの回も同じ）→ 返答の後に当たる物（refix-tail-<n>）。支度は輪の外で 1 度だけ組むので、形は full だけ（拒否の理由のファイルは役の節の
prompt が $LOOP_PREV で名指す）。
"""
import pathlib
import sys

sys.dont_write_bytecode = True

_CORE = pathlib.Path(__file__).resolve().parents[2] / ".shared" / "core"
if str(_CORE) not in sys.path:
    sys.path.insert(0, str(_CORE))

import rulebook  # noqa: E402

RULES = pathlib.Path(__file__).resolve().parents[1] / "rules" / "refix.md"
VALUES = ("brief_file", "diff_file", "policy_path")
ROLES = {1: "refix", 2: "refix2"}
ALWAYS = "いつも"
# 正本のうち載せない節: 食い違いの申し出（conflicts）の出口はこの役に無い。曲げない決まりと、申し出の代わりの declared は読み替え
# （refix-remap）が言う
NOT_HERE = ("core-conflict",)


def parts(n: int, values: dict, seat: str = "") -> list:
    """n 回目の手直しの役の決まりの節 [(id, 本文, 理由)]（順は指示書の順）。seat は借りたスキルの座（空なら載せない）"""
    if n not in ROLES:
        raise rulebook.Unfilled(f"手直しの往復 {n!r} は {sorted(ROLES)} のどれでもない")
    r = rulebook.sections(RULES)
    canon = [(sid, text, ALWAYS + "（書く役の決まりの正本）") for sid, text in rulebook.sections(rulebook.CANON).items()
             if sid not in NOT_HERE]
    return [("refix-head", rulebook.fill(r[f"refix-head-{n}"], rulebook.pick(values, VALUES)), ALWAYS + "（役・材料・run の値）"),
            *canon,
            ("refix-remap", r["refix-remap"], ALWAYS + "（この役での読み替え）"),
            ("refix-keep", r["refix-keep"], ALWAYS + "（手直しだけの決まり）"),
            *([("seat", seat, ALWAYS + "（修正の形 g3 の座）")] if seat else []),
            ("refix-reply", r["refix-reply"], ALWAYS + "（返答の欄）"),
            ("refix-tail", r[f"refix-tail-{n}"], ALWAYS + "（返答の後に当たる物）")]


def build(n: int, values: dict, seat: str = "") -> str:
    """n 回目の手直しの役の指示書（純粋）。values の lang（言語の 1 行。refix.prep_fix が盤面から置く）は末尾に。seat は parts の座"""
    got = parts(n, values, seat)
    return rulebook.render(ROLES[n], 1, got, lang=values.get("lang") or "")["text"]
