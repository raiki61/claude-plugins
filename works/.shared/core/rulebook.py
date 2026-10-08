"""書く役の指示書の組み立ての口（裁定 R65）。AI を通さず、機械が決まりのファイルを節に切り、run の値の穴を埋めて繋ぐ。

- CANON: 書く役（コードを直す役はどれも）の決まりの正本 writerules/common.md。ブロックの境を越えて読めるよう core に 1 つだけ置く
  （ほかの置き場に写さない。tests/test_fix_rules.py）。節は core-fix（直し方）・evidence・evidence-<種類>（テストで赤→緑を示せない
  直しの証拠）・core-conflict（食い違いの申し出）・core-keep（守ること）
- sections(path): `<!-- 節 <id> -->` の行で切った {id: 本文}（印の行は指示書に入れない）
- fill: 型の穴 <<名>> を `値`（空は EMPTY）で埋める。穴に値が無い時は Unfilled
- render: 節の並び [(id, 本文, 理由)] から指示書の 1 つの形。1 行目（HEADER）に、どの節を載せたか・なぜかを機械の事実として書く。
  呼び手が盤面から取った言語の 1 行（rolekit.lang_line）を渡せば末尾に置く

同じ入力からはバイト単位で同じ指示書になる（時刻を書かない）。層は L3。どの役の道・どのブロックの決まりかは呼び手が持つ。
"""
import hashlib
import json
import pathlib
import re
import sys

sys.dont_write_bytecode = True

_CORE = pathlib.Path(__file__).resolve().parent
if str(_CORE) not in sys.path:
    sys.path.insert(0, str(_CORE))

import rolekit  # noqa: E402

CANON = _CORE / "writerules" / "common.md"
EMPTY = "（空）"
HOLE = re.compile(r"<<([a-z_]+)>>")
MARK = re.compile(r"^<!-- 節 ([a-z0-9-]+) -->$")
HEADER = "<!-- works-prompt {} -->"


class Unfilled(ValueError):
    """型の穴に値が無い・値の名が要る物と違う（回す側の誤り）"""


# ---------------------------------------------------------------- 節
def sections(path) -> dict:
    """決まりのファイルの節 {id: 本文}（ファイルの順。本文の前後の空行は落とす。印の行は入れない）"""
    path = pathlib.Path(path)
    out, cur = {}, None
    for line in path.read_text(encoding="utf-8").split("\n"):
        m = MARK.match(line)
        if m:
            cur = m.group(1)
            if cur in out:
                raise Unfilled(f"{path.name}: 節 {cur} が 2 つ在る")
            out[cur] = []
        elif cur is not None:
            out[cur].append(line)
        elif line.strip():
            raise Unfilled(f"{path.name}: 節の印より前に文が在る: {line[:60]!r}")
    return {k: "\n".join(v).strip("\n") for k, v in out.items()}


def join(texts) -> str:
    """節を繋ぐ: 箇条の行の後に箇条で始まる節が来れば改行 1 つ（同じ箇条を続ける）、ほかは空行 1 つ"""
    out = ""
    for t in texts:
        if not t:
            continue
        if out:
            last = out.rsplit("\n", 1)[-1]
            out += "\n" if t.startswith("- ") and (last.startswith("- ") or last.startswith("  ")) else "\n\n"
        out += t
    return out


def shared() -> str:
    """決まりの正本の全文（全部の節。印の行を除いた字）"""
    return join(sections(CANON).values())


def sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------- 値の穴
def _value(v) -> str:
    v = "" if v is None else str(v)
    return f"`{v}`" if v else EMPTY


def fill(template: str, values: dict) -> str:
    """型の穴 <<名>> を `値`（空は EMPTY）で埋める。1 回の置き換え（埋めた字を読み直さない）"""
    lack = sorted(set(HOLE.findall(template)) - set(values))
    if lack:
        raise Unfilled(f"型の穴に値が無い: {lack}")
    return HOLE.sub(lambda m: _value(values[m.group(1)]), template)


def pick(values: dict, names: tuple) -> dict:
    """run の値から names だけ（欠けは Unfilled）"""
    lack = [k for k in names if k not in values]
    if lack:
        raise Unfilled(f"run の値が無い: {lack}")
    return {k: values[k] for k in names}


# ---------------------------------------------------------------- 組み立て（純粋）
def render(role: str, iteration: int, parts: list, *, before=(), after=(), reject_file: str = "", lang: str = "") -> dict:
    """指示書 {text, head}。決まりの節は全部載せる。head は 1 行目（HEADER）に書く機械の事実 {role, iteration, rules_sha（決まりの
    本文の sha256）, sections: [{id, why}]}。lang は言語の 1 行（rolekit.lang_line。空なら置かない）で末尾に置く。
    並び: HEADER → [拒否の理由のファイルの 1 行] → before → 決まり → after → [言語の 1 行]"""
    rules_text = join(text for _, text, _ in parts)
    head = {"role": role, "iteration": iteration, "rules_sha": sha(rules_text),
            "sections": [{"id": pid, "why": w} for pid, _, w in parts]}
    text = rolekit.compose([*before, rules_text, *after, lang], reject_file=reject_file)
    text = HEADER.format(json.dumps(head, ensure_ascii=False)) + "\n" + text.rstrip("\n") + "\n"
    return {"text": text, "head": head}
