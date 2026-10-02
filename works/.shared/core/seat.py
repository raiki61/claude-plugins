"""借りたスキルの座（計画 220 Task 2）: 216 の節（seams.json の 1 項目）を、修正の工程の役の指示書に載せる 1 節の文を組む。

語:
- 節（seam）: .shared/borrow/seams.json の 1 項目。use_as が skill（スキル 1 本を Skill の道具で読ませる）か prompt（部品の型の
  穴を埋めて指示書に置く）。
- 座: 節を役に載せる口。SEATS（役の印の名 → 節の名）が表で持ち、修正の形が SHAPE（g3）の時だけ文が出る。
- 読み替え: rolekit.skill_overlay()（.shared/borrow/unattended.md の頭の 1 行と全文）。座の末尾にいつも載る。

口:
- SEATS・SHAPE・carries(node, shape): どの節に、どの形で座が載るか
- skill_of(seam): skill の節の files[0]（skills/<名>/…）の <名>
- pinned(): 写しが固定と合うかを照らし、(item, 写しの置き場) を返す（合わなければ ValueError）
- section(node, shape, values): 座の文。載らなければ空。HEAD → 節の種類ごとの本文 → 読み替え

座を組む前に、写し（spseam.vendored_dir）が固定（borrow.json の superpowers.pin）と合うかを spseam.pin_problems で照らす。
食い違い・型の穴の埋め残り（spseam.fill）は ValueError で名指す（af の文へ黙って逃げない。支度の script は 2 で落ちる）。
写しと節の契約は spseam.BORROW_DIR から呼ぶたびに読む。層は L3（rolekit・spseam と同じ）。
"""
from __future__ import annotations

import json
import pathlib
import sys

sys.dont_write_bytecode = True   # 下の import が pack の中に __pycache__ を作らないように（必ず import より前）

_CORE = pathlib.Path(__file__).resolve().parent
if str(_CORE) not in sys.path:
    sys.path.insert(0, str(_CORE))

import rolekit  # noqa: E402
import spseam  # noqa: E402

SHAPE = "g3"   # 座が載る修正の形
SEATS = {"tdd": "tdd", "fix": "implementer", "fix-ruled": "implementer"}   # 役の印の名 → 節の名
HEAD = "## 借りたスキルの座（修正の形 g3）"
SCENE = "works の修正の段。流れ・機械の関門・commit は線が持つ。TDD の輪で直した単位は輪の要約に在る"
NO_REPORT_FILE = "ファイルに書かない。返答は指示書の『返答の欄』の JSON"
WINS = "この指示書の段の約束（返す JSON・機械の関門・段の順）と下の読み替えは、借りた文に勝つ"   # どちらの種類の座も同じ 1 段落
SKILL_LEAD = "Skill の道具で `{skill}` を読み、その手順で進めよ。"   # skill の座だけが WINS の前に足す 1 文
APPLIES, NOT_APPLIES = "効く所:", "効かない所（従わない）:"
PROMPT_HEAD = "### 下請けの型（superpowers の {file}。works の節で包んだ物）"
ITEM = "superpowers"   # borrow.json の借りる物の名


def carries(node: str, shape: str) -> bool:
    """役 node に形 shape で座が載るか"""
    return shape == SHAPE and node in SEATS


def skill_of(seam: dict) -> str:
    """use_as が skill の節の files[0]（skills/<名>/…）の <名>。skill の節でなければ ValueError"""
    files = seam.get("files") or []
    parts = pathlib.PurePosixPath(files[0]).parts if files else ()
    if seam.get("use_as") != "skill" or len(parts) < 3 or parts[0] != "skills":
        raise ValueError(f"スキルの節でない（use_as {seam.get('use_as')!r}・files {files}）")
    return parts[1]


def _bullets(rows) -> str:
    return "\n".join(f"- {r}" for r in rows)


def pinned() -> tuple[dict, pathlib.Path]:
    """借りる物（borrow.json の superpowers）と写しの置き場。写しが固定と合わなければ ValueError（spseam.pin_problems を名指す）。
    支度は重い仕事と書き込みの前にこれを呼ぶ"""
    borrow = spseam.BORROW_DIR
    item = json.loads((borrow / "borrow.json").read_text(encoding="utf-8"))[ITEM]
    src = spseam.vendored_dir(item, borrow)
    bad = spseam.pin_problems(src, item)
    if bad:
        raise ValueError(f"借りた写し {src} が固定（borrow.json の pin）と合わない: {'; '.join(bad)}")
    return item, src


def section(node: str, shape: str, values: dict[str, str] | None = None) -> str:
    """役 node の座の文。載らなければ（carries が偽）空。prompt の節は values で型の穴を埋め、values が None なら ValueError。
    写しが固定と違う・穴が埋まらなければ ValueError（名指す）"""
    if not carries(node, shape):
        return ""
    seams = spseam.load_seams(spseam.BORROW_DIR)
    sid = SEATS[node]
    if sid not in seams:
        raise ValueError(f"座 {node} の節 {sid} が {spseam.SEAMS_FILE} に無い")
    sec = seams[sid]
    if sec.get("use_as") == "prompt" and values is None:
        raise ValueError(f"座 {node}（節 {sid}）の型の穴の値が無い")
    item, src = pinned()
    if sec.get("use_as") == "skill":
        body = [SKILL_LEAD.format(skill=skill_of(sec)) + WINS, APPLIES + "\n\n" + _bullets(sec.get("applies") or []),
                NOT_APPLIES + "\n\n" + _bullets(sec.get("not_applies") or [])]
    else:
        filled = spseam.fill(sid, values, src, item, seams)
        body = [WINS, PROMPT_HEAD.format(file=sec["files"][0]), filled.rstrip("\n")]
    return "\n\n".join([HEAD, *body, rolekit.skill_overlay().rstrip("\n")]) + "\n"
