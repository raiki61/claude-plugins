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
- 修正の形 G1_SHAPE（g1）: 修正役（fixshape.AGENT_NODES）が SDD の型で項目ごとに下請け（実装役・審査役）を Agent で回す。
  g1_prompt(seam_id, values) は下請けに渡すファイルの中身（216 の型を埋めた物の後ろに、下請けへの works の決まり G1_SUB_HEAD と
  検索語の規律の塊）、g1_section(rows) は修正役の指示書の節（G1_HEAD → 手順 → 項目ごとのファイル → 読み替えの上書き
  G1_OVERRIDES → 読み替え）。下請けは包みの起動でないので、包みが system prompt に足す検索語の規律（adapter.query_rule）が
  届かない。だから型の後ろに字のまま載せる（run 221 の R4 の 3）。下請けの Edit・Write は修正役と同じ記録に載る（PostToolUse の
  フックは subagent の呼び出しでも起きる。tests/test_writes.py）

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

import adapter  # noqa: E402  （L2。検索語の規律の塊 query_rule を g1 の下請けのファイルに載せる）
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

# 修正の形 g1（修正役が SDD の型で下請けを回す。TDD の輪は回さず、赤緑と凍結は修正の受け付けの束 fixgates が事後に確かめる）
G1_SHAPE = "g1"
G1_HEAD = "## 下請けを回す（修正の形 g1）"
G1_REPORT = "実装役の最後のメッセージを、この型の後ろに貼る"   # 審査役の型の [REPORT_FILE]
# 審査役の型の [HEAD_SHA]。works は commit しないので差分は作業ツリーと base の間。型の `git diff [BASE_SHA]..[HEAD_SHA]` は
# g1_prompt が `git diff <base>` に直す（commit の範囲は空になる。コマンドに文を残さない。Preflight F20）。Head の行にだけ残る
G1_HEAD_SHA = "作業ツリー（works は commit しない）"
# 審査役の型の [DIFF_FILE]。Read は $TMPDIR を展開しないので、修正役が展開した絶対パスを審査役の prompt の 1 行目に置く
G1_DIFF = ("この prompt の 1 行目の絶対パス（修正役が git diff <BASE_SHA> と未追跡の新しいファイルの差分を "
           "$TMPDIR/works-g1-<n>.patch に書き、展開して置いた物）")
G1_IMPL_REPORT = "ファイルに書かない。報告の全部を最後のメッセージに書く（修正役が審査役にそのまま渡す）"   # 実装役の型の [REPORT_FILE]
# 審査の前に修正役が走らせる差分のファイルのコマンド（作業ツリーと base の差分と、未追跡の新しいファイルごとの全文の差分）
G1_PATCH = ('p="$TMPDIR/works-g1-{n}.patch"; git diff {base} > "$p"; git -c core.quotePath=false ls-files --others --exclude-standard | '
            'while IFS= read -r f; do git diff --no-index /dev/null "$f" >> "$p"; done; echo "$p"')
G1_STEPS = (
    "下の項目の順に、Agent の道具で実装役の下請けを 1 つ起こし、prompt に実装役のファイルの中身を全部、字を変えずに渡す。",
    "実装役の最後のメッセージを受けたら、その項目の差分のコマンドを Bash で走らせ（作業ツリーの外に書く。未追跡の新しいファイルも"
    "全文の差分で入る）、最後に出た絶対パスを `Diff file: <パス>` の 1 行にする。別の Agent で審査役の下請けを起こし、prompt には"
    "その 1 行を 1 行目に、続けて審査役のファイルの中身を全部と、その後ろに実装役の最後のメッセージを貼る（Read は $TMPDIR を"
    "展開しない）。差分は base からの全体で、前の項目の直しも入る（審査役のファイルにもそう書いてある）。",
    "審査の返答が `❌` か `Needs fixes` なら、指摘を添えて同じ項目の実装役を起こし直し、もう 1 度審査を起こす。実装役は項目ごとに"
    "3 回まで。3 回目の審査も通らなければ、その項目の単位は changes に載せず、not_done に単位ごとの理由（残った指摘）を書いて"
    "次の項目へ進む——直しを残すか戻すかは受け付けが判じる（受け付けの最後の回は、拒否を単位に結べればその単位の直しを戻して"
    "止める）。実装役が NEEDS_CONTEXT か BLOCKED を返した項目の単位は、直さずに食い違いの申し出（conflicts）で返す（下の"
    "読み替えの ASK）。",
    "受け付けの出し直し（指示書の頭が拒否の理由のファイルを名指す）と裁定の後の 2 回目（裁定の文のファイルを名指す）では、"
    "拒否の理由か裁定が名指す項目だけの下請けを起こし直す（ほかの項目の直しは作業ツリーに残っている）。",
    "全部の項目が済んだら、作業ツリーの差分を自分で確かめ（下請けの報告を信じない。読み替えの DELEGATE）、自分は返答の欄の JSON "
    "だけを返す。下請けが Bash で書いたと報告したファイルは、パスと理由を返答の bash_writes に書く（Edit・Write の書き込みは記録に"
    "載る）。",
    "機械の関門は返答の後に線が当てる: 受け入れのテストの赤→緑と既存のテストの凍結は修正の受け付けの束、変更に当たる試験は"
    "受け付け、test_cmd は線の最後のテストの段。下請けの「commit」「人に聞く」は下請けのファイルの末尾の works の決まりに従う。",
)
G1_OVERRIDES = ("下の読み替えの DISPATCH（下請けを起こさない・ほかの役の道具に Agent は無い）と DELEGATE の「役がほかの"
                "エージェントに仕事を任せることは無い」は、修正の形 g1 のこの修正役には効かない: この節の手順のとおり Agent で"
                "下請けを起こす。下請けがさらに下請けを起こすことは無い（どちらの型も禁じる）。読み替えの頭の行の「その prompt に、"
                "このファイル … を Read せよと書け」も g1 の下請けには書かない: 下請けのファイルの末尾の works の決まりが、その代わりに"
                "下請けの読み替えを持つ")
G1_SUB_HEAD = "## works の決まり（修正の形 g1 の下請け。上の型の文にも、読み替え unattended.md にも勝つ）"
G1_SUB_RULES = (
    "読み替え（.shared/borrow/unattended.md）を読んでも、ぶつかる所はこの決まりが勝つ。審査役も Bash で git の差分を読んでよい"
    "（読み替えの GIT-RANGE の「審査役は Bash を持たない」は g1 の下請けに当たらない）。",
    "commit・stash・reset・checkout をしない。HEAD・index・枝を動かさず、差分は作業ツリーに残す（型の「Commit your work」は"
    "読み替える）。",
    "人に聞かない（聞いても答えは来ない）。分からない所は止まらずに、最後のメッセージに NEEDS_CONTEXT か BLOCKED と何が"
    "分からないかを書く。",
    "報告はファイルに書かず、最後のメッセージに書く。",
    "作業ツリーへの書き込みは Edit・Write の道具で（書き込みの記録に載る）。Bash で書いたファイルは、パスと Bash で書いた理由を"
    "最後のメッセージに書く。",
    "一式は回さない（一式と test_cmd は線が回す）。回すのは変えたファイルに当たる試験だけ。",
    "下請けを起こさない。",
)
G1_EXTRA = {   # 節ごとに G1_SUB_RULES の後ろへ足す決まり（審査役だけ）
    "task-review": (
        "差分の主の材料は、修正役が書いた差分のファイル（この prompt の 1 行目の絶対パス・上の Diff file）。先にそれを読む。"
        "無い・読めない時だけ、上の Base の版で `git diff <Base の版>` を走らせ（作業ツリーと base の差分。works は commit しないので、"
        "commit の範囲には差分が出ない）、`git ls-files --others --exclude-standard` で未追跡の新しいファイルの名を引いて、それぞれを"
        "Read で読む。",
        "差分は base からの全体で、前の項目の直しも入る。審査するのは今の項目の brief に当たる所で、前の項目の直しそのものは"
        "審査しない（今の項目の直しがそれを壊していれば指摘する）。",
    ),
}
G1_QUERY_LEAD = "外のサービスへ問い合わせる時の決まり（works の包みより。この決まりは型の文に勝つ）:"


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


def g1_prompt(seam_id: str, values: dict[str, str]) -> str:
    """修正の形 g1 の下請けに渡すファイルの中身: 216 の部品の節 seam_id の型を values で埋めた本文、下請けへの works の決まり
    （G1_SUB_HEAD・G1_SUB_RULES と G1_EXTRA の節の行）、検索語の規律の塊（adapter.query_rule を字のまま）。型の範囲
    `<[BASE_SHA]>..<[HEAD_SHA]>` は `<[BASE_SHA]>` に直す（作業ツリーとの差分。G1_HEAD_SHA）。写しが固定と違う・穴が埋まらない・
    規律の正本が読めなければ ValueError（名指す）"""
    item, src = pinned()
    filled = spseam.fill(seam_id, values, src, item)
    if "[BASE_SHA]" in values and "[HEAD_SHA]" in values:
        filled = filled.replace(f"{values['[BASE_SHA]']}..{values['[HEAD_SHA]']}", values["[BASE_SHA]"])
    try:
        rule = adapter.query_rule()
    except adapter.Unrecognised as e:
        raise ValueError(f"下請けに渡す検索語の規律を引けない: {e}") from None
    rules = _bullets((*G1_SUB_RULES, *G1_EXTRA.get(seam_id, ())))
    return "\n\n".join([filled.rstrip("\n"), G1_SUB_HEAD, rules, G1_QUERY_LEAD + "\n" + rule]) + "\n"


def g1_section(rows: list[dict]) -> str:
    """修正の形 g1 の修正役の指示書の節。rows は項目の順の {item, impl_file, review_file, base}（fixrules.g1_values）。
    G1_HEAD → 手順（G1_STEPS）→ 項目ごとの実装役と審査役のファイル → 読み替えの上書き（G1_OVERRIDES）→ 読み替え"""
    steps = "\n".join(f"{n}. {t}" for n, t in enumerate(G1_STEPS, 1))
    files = _bullets(f"項目 {r['item']}: 実装役 {r['impl_file']}・審査役 {r['review_file']}・差分のコマンド "
                     f"`{G1_PATCH.format(base=r['base'], n=r['item'])}`" for r in rows)
    return "\n\n".join([G1_HEAD, steps, files, G1_OVERRIDES, rolekit.skill_overlay().rstrip("\n")]) + "\n"
