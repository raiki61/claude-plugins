"""始めの記録（盤面の r1/start.json。考え start-record）の住処。層 L1（標準ライブラリだけ）。

始めの記録は、線の入口（入口のブロックの節 open。中身は core の entry.start）が run の入力を確かめて置く控えで、入口の入力の形
（欄 input）と run の入力の控え（test_cmd・adapter・機能の切り替え…）と start の結果（ci_role_go・pr_go・head_line）を持つ。
書き手は entry.start と固定材料の取り込み（fixture.adopt）。約束（JSON Schema）は入口のブロックの schemas/start.schema.json で、
欄 input は同じ置き場の input.schema.json と同じ形。置き場の名と読む口はここ 1 つで、ほかのモジュール・殻はここを引く
（前は置き場の名を 3 か所が、読む口を 6 か所が別々に持ち、続きの run で機能の切り替えが黙って変わった 8dfebca6 の元になった）。

- NAME・REL: 周の置き場の中の名（盤面の work(NAME) が今の周 r<N>/ に置く）と、盤面の根からの置き場（1 周目）
- path(board_dir): 盤面の根からの始めの記録のパス
- read(board_dir): 始めの記録の dict（無い・読めない・dict でなければ {}。読み手が欠けを欄ごとに扱う）
- shape(doc): 入口の入力の形（欄 input の dict）。無い前の版の控え（入口の入力の形を持つ前の固定材料）は None
- diff_empty(doc): 入口の差分が空か（真偽）。入力の形が無ければ None
- requests(doc): 依頼の行の数。入力の形が無ければ None
- words(shape): 頭の行と報告の冒頭 2 の入口の文（例: 差分なし（HEAD）・依頼 2 件——P1 の役は起こさない）。出どころは
  base.label（入口の変換が書いた文）で、入口の種類で分岐しない
"""
from __future__ import annotations

import json
import pathlib

NAME = "start.json"
REL = f"r1/{NAME}"
P1_OFF_WORDS = "P1 の役は起こさない"   # 差分が空の run の入口の文の尻（入口の印が立ち、1 周目の P1 の役を起こさない）
SPEC_WORDS = "仕様の段あり"


def path(board_dir) -> pathlib.Path:
    """盤面の根 board_dir からの始めの記録のパス"""
    return pathlib.Path(board_dir) / REL


def read(board_dir) -> dict:
    """始めの記録（無い・読めない・dict でなければ空の dict）"""
    try:
        doc = json.loads(path(board_dir).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return doc if isinstance(doc, dict) else {}


def shape(doc: dict):
    """入口の入力の形（欄 input）。dict でない・無ければ None"""
    got = doc.get("input") if isinstance(doc, dict) else None
    return got if isinstance(got, dict) else None


def diff_empty(doc: dict):
    """入口の差分が空か（input.diff.empty の真偽）。入力の形・欄が無ければ None"""
    s = shape(doc)
    got = (s.get("diff") or {}).get("empty") if s is not None and isinstance(s.get("diff"), dict) else None
    return got if isinstance(got, bool) else None


def requests(doc: dict):
    """依頼の行の数（input.requests）。入力の形・欄が無ければ None"""
    s = shape(doc)
    got = s.get("requests") if s is not None else None
    return got if isinstance(got, int) and not isinstance(got, bool) else None


def words(s: dict) -> str:
    """入口の文（「入口: 」の後ろ）: 差分 <根の版の頭 12 字>..HEAD（N ファイル・<出どころ>）・依頼 N 件 ／
    差分なし（<出どころ>）・依頼 N 件——P1 の役は起こさない。仕様の段を挟む run は「・仕様の段あり」を足す"""
    base, diff = s["base"], s["diff"]
    if diff["empty"]:
        out = f"差分なし（{base['label']}）・依頼 {s['requests']} 件——{P1_OFF_WORDS}"
    else:
        out = f"差分 {base['rev'][:12]}..HEAD（{diff['files']} ファイル・{base['label']}）・依頼 {s['requests']} 件"
    return out + (f"・{SPEC_WORDS}" if s.get("spec") else "")
