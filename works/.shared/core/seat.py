"""借りたスキルの座（計画 220 Task 2）: 216 の節（seams.json の 1 項目）を、修正の工程の役の指示書に載せる 1 節の文を組む。

語:
- 節（seam）: .shared/borrow/seams.json の 1 項目。use_as が skill（スキル 1 本を Skill の道具で読ませる）か prompt（部品の型の
  穴を埋めて指示書に置く）。
- 座: 節を役に載せる口。SEATS（役の印の名 → 節の名）が表で持つ。
- 読み替え: rolekit.skill_overlay()（.shared/borrow/unattended.md の頭の 1 行と全文）。座の末尾にいつも載る。

口:
- SEATS・carries(node): どの節に座が載るか。SKILL_NODES・AGENT_NODES: 座が skill の節と、Agent を持つ修正役の節
- skill_of(seam): skill の節の files[0]（skills/<名>/…）の <名>
- pinned(): 写しが固定と合うかを照らし、(item, 写しの置き場) を返す（合わなければ ValueError）
- section(node, values): 座の文。載らなければ空。HEAD → 節の種類ごとの本文 → 読み替え。勝つ物の段落は WINS（役の
  指示書に組み込まれる座）か、座のファイルを別に読む役では指示書を名指す WINS_OF の文。差分の審査役（review）の型
  VERDICT_SEAM は本文の後ろに words_table（型の判定の語がどの欄のどの値に当たるか。VERDICT_WORDS と NOTE_ROWS）を持つ
- 申し出の種類の手引き DIVERGENCE_HINT: 型の状態の語 NEEDS_CONTEXT・BLOCKED（216 の works の語 conflict.WORD）に当たる時、
  食い違いの申し出をどの kind（conflict.DIV_KINDS。211）で返すかを 1 語に 1 行で言う。語に conflict.WORD を持つ節（implementer。
  修正役の fix・fix-ruled）の座の本文の後ろと、下請けを回す修正役の節（下請けの実装役がそう返した時）に載る。各語の決まりの正本は
  指示書の『食い違いの申し出』の節（writerules/common.md）で、ここは場面の引き当てだけ
- 座の節: TDD の役（tdd）と手直しの役（refix・refix2。receiving-review）は skill、修正役（fix・fix-ruled。implementer）と 1 回目の
  差分の審査役（review。task-review）は prompt。2 回目の審査役（review2）には座が無い（返答に判定の欄が無く、判定の語の表を
  持つ型とぶつかる）。手直しの役の座は手直しの支度（blk-refix/scripts/prep.py）が、審査役の座は審査の支度（refix.cut）が置く
- 下請けを回す修正役（依頼 243 の 2。名の G1_ は、修正役が SDD の型で項目ごとに下請けを回した前の形 g1 から来た）: 修正役
  （fix・fix-ruled）が輪の後に直す単位ごとに、下請け（実装役・審査役）を Agent の新しい会話で起こす。g1_prompt(seam_id, values) は
  下請けに渡すファイルの中身（216 の型を埋めた物の後ろに、下請けへの works の決まり G1_SUB_HEAD と検索語の規律の塊）、
  g1_section(rows) は修正役の指示書の節（G1_HEAD → 手順 → 輪で直した単位に下請けを起こさない旨 G1_LOOP_NOTE → 項目ごとの
  ファイル → 申し出の種類の手引き DIVERGENCE_HINT → 読み替えの上書き G1_OVERRIDES → 読み替え）。2 つ目からの項目の実装役には、修正役が前の項目の報告から書く
  引き継ぎの節（G1_HANDOFF_HEAD）を足させる（前の項目の会話の履歴は渡らない）。下請けは包みの起動でないので、包みが system prompt に
  足す検索語の規律（adapter.query_rule）が届かない。だから型の後ろに字のまま載せる（run 221 の R4 の 3）。下請けの
  Edit・Write は修正役と同じ記録に載る（PostToolUse のフックは subagent の呼び出しでも起きる。tests/test_writes.py）
  項目の並べ（依頼 243 の並べ）は修正役の下請けでなく、修正役の外の Archon の節（修正役の並べの枝 fix-lane-<n>。blk-fix の fixlanes。
  docs/plans/2026-10-07-fix-lane-nodes.md）が持つ。修正役の下請けはどれも run の作業ツリーで順に働く。並べの枝の役が起こす審査役の
  下請けのファイルは、枝の単位の worktree の中で読む決まり G1_TREE_RULE_OF を持つ（g1_prompt の tree）。差分のコマンドは g1_diff_cmd

座を組む前に、写し（spseam.vendored_dir）が固定（borrow.json の superpowers.pin）と合うかを spseam.pin_problems で照らす。
食い違い・型の穴の埋め残り（spseam.fill）は ValueError で名指す（af の文へ黙って逃げない。支度の script は 2 で落ちる）。
写しと節の契約は spseam.BORROW_DIR から呼ぶたびに読む。層は L3（rolekit・spseam と同じ）。
"""
from __future__ import annotations

import json
import pathlib
import shlex
import sys

sys.dont_write_bytecode = True   # 下の import が pack の中に __pycache__ を作らないように（必ず import より前）

_CORE = pathlib.Path(__file__).resolve().parent
if str(_CORE) not in sys.path:
    sys.path.insert(0, str(_CORE))

import adapter  # noqa: E402  （L2。検索語の規律の塊 query_rule を下請けのファイルに載せる）
import conflict  # noqa: E402  （同じ L3。申し出の種類の語 DIV_KINDS と状態の語の読み替え WORD）
import rolekit  # noqa: E402
import spseam  # noqa: E402

SEATS = {"tdd": "tdd", "tdd-rest": "tdd", "tdd-lane-1": "tdd", "tdd-lane-2": "tdd", "tdd-lane-3": "tdd",   # 役の印の名 → 節の名
         "fix": "implementer", "fix-ruled": "implementer",
         "review": "task-review", "refix": "receiving-review", "refix2": "receiving-review"}
# 座が skill の節（借りたスキルを Skill の道具で読む役の印の名。SEATS のうち use_as が skill の物。試験が一致を縛る）と、修正役の節
# （単位ごとの下請けを Agent で起こす役 fix・fix-ruled と、審査役の下請けを起こす修正役の並べの枝の役 fix-lane-<n>。blk-fix の
# fixlanes.MAX_LANES と同じ数。YAML で Agent を持つ節はこれだけ）
SKILL_NODES = frozenset({"tdd", "tdd-rest", "tdd-lane-1", "tdd-lane-2", "tdd-lane-3", "refix", "refix2"})
AGENT_NODES = frozenset({"fix", "fix-ruled", "fix-lane-1", "fix-lane-2", "fix-lane-3"})
NONE = "（無し）"   # 型の穴に入れる物が無い時の値（人の方針の文書が無い run の [GLOBAL_CONSTRAINTS] など）
# 差分の審査役の型（task-review）の出口の語（216 の works の語）→ 差分の審査の返答の 2 判定の欄（deltamarks.KEYS）と欄の語
# （deltamarks.COMPLIANCE・QUALITY）。審査役の座の型の後ろに words_table の表で載り、役は型の語をこの欄に書く
VERDICT_SEAM = "task-review"
VERDICT_WORDS = {"compliance_pass": ("compliance", "pass"), "compliance_fail": ("compliance", "fail"),
                 "compliance_unverifiable": ("compliance", "unverifiable"),
                 "quality_pass": ("quality", "pass"), "quality_fail": ("quality", "fail")}
WORDS_HEAD = ("### 判定の語の欄（型の語がどの欄のどの値に当たるかを示すだけ。欄の値は commands/delta-review.md の『2 つの判定』の"
              "決まりで返答の行から決まり、この表と食い違えば指示書が勝つ）")
# 表の後ろの注の行（型の語に依らずに欄の値が決まる場合。deltamarks.gaps の決まり）: (場合, 欄の値)
NOTE_ROWS = (("材料の plan_items が空", "`compliance.verdict`: `not_applicable`"),
             ("準拠の行に結ばれない穴が faces に 1 つでも在る", "`quality.verdict`: `fail`"))
# 申し出の種類の手引き: 語ごとの場面（conflict.DIV_KINDS と同じ語・同じ順。試験が照らす）。欄と語の決まりの正本は指示書の
# 『食い違いの申し出』の節（writerules/common.md）で、ここは状態の語から kind を引き当てる 1 行ずつ
DIVERGENCE_SCENES = {
    conflict.BRIEF_VS_JUDGMENT: "brief と、判定・依頼・修正の前に人が答えた条件が食い違う（`between` にその単位の brief の行）",
    conflict.UNNAMED_TEST_BROKE: "修正案にも裁定にも名指されていない既存のテストが、直すと落ちる・外すしかない",
    conflict.NOT_RED: "受け入れのテスト・名指しの書き換えが、案どおりに書いても赤にならない・赤の種類が案と違う",
    conflict.SCOPE_NEEDED: ("brief や案の範囲の外を触らないと緑にならない・判定者の問いの数え直しが閉じない（範囲の相談の節が"
                            "在れば、先に返答の consult で相談して許されなかった時。下請けは相談が要ることをまとめ役に報告する）"),
    conflict.QUERY_HITS_FIXED: (f"判定者の問いが直した後の正しい形にも当たる（`{conflict.WHICH_FIELD}` は {conflict.QUERY}・"
                                f"`{conflict.CORRECT}` が要る）"),
    conflict.NEEDS_CONTEXT: (f"方針・依頼の意図・どれが正しいかが材料から決められず、人か依頼の答えが要る"
                             f"（`{conflict.WHICH_FIELD}` は {conflict.UNKNOWN}）"),
}
DIVERGENCE_HINT = "\n".join([
    f"実装役の型の状態の語 NEEDS_CONTEXT・BLOCKED（works の語 {conflict.WORD}）に当たる時は、その単位を直したことにせず、"
    f"食い違いの申し出 conflicts の 1 件で返す。`{conflict.KIND_FIELD}` は起きた場面で次のどれか（欄の決まりは指示書の"
    "『食い違いの申し出』の節）:",
    *(f"- `{k}`: {DIVERGENCE_SCENES[k]}" for k in conflict.DIV_KINDS)])
HEAD = "## 借りたスキルの座"
SCENE = "works の修正の段。流れ・機械の関門・commit は線が持つ。TDD の輪で直した単位は輪の要約に在る"
NO_REPORT_FILE = "ファイルに書かない。返答は指示書の『返答の欄』の JSON"
WINS = "この指示書の段の約束（返す JSON・機械の関門・段の順）と下の読み替えは、借りた文に勝つ"   # どちらの種類の座も同じ 1 段落
# 座のファイルを指示書と別に読む役（座の中の「この指示書」が座のファイルを指して読める）は、勝つ指示書を名指す段落に替える
WINS_OF = {"review": "役の指示書 commands/delta-review.md の約束（返す JSON・読む義務・判定の欄の値の決め方）と下の読み替えは、"
                     "借りた文に勝つ"}
SKILL_LEAD = "Skill の道具で `{skill}` を読み、その手順で進めよ。"   # skill の座だけが WINS の前に足す 1 文
APPLIES, NOT_APPLIES = "効く所:", "効かない所（従わない）:"
PROMPT_HEAD = "### 下請けの型（superpowers の {file}。works の節で包んだ物）"
ITEM = "superpowers"   # borrow.json の借りる物の名

# 下請けを回す修正役の節（依頼 243 の 2）
G1_HEAD = "## 下請けを回す"
# 2 つ目からの項目の実装役の prompt の後ろに修正役が足す節の見出し（前の項目の会話の履歴の代わりの引き継ぎ。依頼 243 の 2）
G1_HANDOFF_HEAD = "## 前の項目の引き継ぎ（修正役が前の項目の実装役の報告から書いた物）"
# 修正役の節に載る 1 段落（修正役の前に TDD の輪が単位を直す。輪で直した単位は項目に載らない。fixrules.prep）
G1_LOOP_NOTE = ("TDD の輪で直した単位（輪の要約のファイルの「輪で直した単位」）は下の項目に載らない。その単位には下請けを"
                "起こさず、指示書の『読む物』の TDD の輪の結果のとおり changes に 1 行を書く")
G1_REPORT = "実装役の最後のメッセージを、この型の後ろに貼る"   # 審査役の型の [REPORT_FILE]
# 審査役の型の [HEAD_SHA]。works は commit しないので差分は作業ツリーと base の間。型の `git diff [BASE_SHA]..[HEAD_SHA]` は
# g1_prompt が `git diff <base>` に直す（commit の範囲は空になる。コマンドに文を残さない。Preflight F20）。Head の行にだけ残る
G1_HEAD_SHA = "作業ツリー（works は commit しない）"
G1_IMPL_REPORT = "ファイルに書かない。報告の全部を最後のメッセージに書く（修正役が審査役にそのまま渡す）"   # 実装役の型の [REPORT_FILE]
# 審査の前に修正役が走らせる差分のファイルのコマンド。{patch} は支度が決めた run ごとの置き場（盤面の隣の run-place。包みが
# sandbox で書けるようにする所。盤面そのものは守る場所で書けない）の絶対パス（shell の字で囲んだ物）で、審査役の型の [DIFF_FILE]
# も同じパス。リポジトリの根で、作業ツリーと base の差分と、未追跡の新しいファイルごとの全文の差分を書き、最後にそのパスを出す
# （最後の git diff --no-index は差分が在ると 1 を返すので、echo で終えて 0 にする。修正役が Bash の失敗と読まない）。最初の
# git diff が落ちれば（base の版が無いなど）そこで 1 で終える（差分の無いファイルを審査役に渡さない）
G1_PATCH = ('p={patch}; top="$(git rev-parse --show-toplevel)"; '
            'git -C "$top" -c core.quotePath=false diff {base} > "$p" || exit 1; '
            'git -C "$top" -c core.quotePath=false ls-files --others --exclude-standard | while IFS= read -r f; do '
            'git -C "$top" -c core.quotePath=false diff --no-index /dev/null "$f" >> "$p"; done; echo "$p"')
G1_STEPS = (
    "下の項目の順に、Agent の道具で実装役の下請けを 1 つ起こし、prompt に実装役のファイルの中身を全部、字を変えずに渡す。"
    "下請けは項目ごとに新しい会話で起きる（前の項目の会話の履歴は持たない）。2 つ目からの項目では、ファイルの中身の後ろに見出し "
    f"`{G1_HANDOFF_HEAD}` の節を足し、済んだ項目ごとに 1 行（項目の番号・実装役の報告に在る変えたファイルと緑にしたテスト）を"
    "書く。前の項目の直しは作業ツリーに在るので、戻したり作り直したりさせない。",
    "実装役の最後のメッセージを受けたら、その項目の差分のコマンドを Bash で走らせ（run ごとの置き場の絶対パスに書く。未追跡の"
    "新しいファイルも全文の差分で入る）、別の Agent で審査役の下請けを起こす。prompt には審査役のファイルの中身を全部と、その後ろに"
    "実装役の最後のメッセージを貼る。差分は base からの全体で、前の項目の直しも入る（審査役のファイルにもそう書いてある）。",
    "審査の返答が `❌` か `Needs fixes` なら、指摘を添えて同じ項目の実装役を起こし直し、もう 1 度審査を起こす。実装役は項目ごとに"
    "3 回まで。3 回目の審査も通らなくても、その項目の直す義務の単位はどの形とも同じく changes に載せる（直す義務の単位はいつも "
    "changes に 1 行）。残った指摘は、その行の root_or_symptom の kind を symptom にして why に書く。受け付けがその単位を拒めば、"
    "受け付けの最後の回はその単位の直しだけを戻して止める（ほかの単位は通る）。単位をまったく直せない（人の答えが無いと直し方が"
    "決まらない）時と、実装役が NEEDS_CONTEXT か BLOCKED を返した時だけ、直さずに食い違いの申し出（conflicts）で返す（下の"
    "読み替えの ASK）。",
    "受け付けの出し直し（指示書の頭が拒否の理由のファイルを名指す）と裁定の後の 2 回目（裁定の文のファイルを名指す）では、"
    "拒否の理由か裁定が名指す項目だけの下請けを起こし直す（ほかの項目の直しは作業ツリーに残っている）。",
    "全部の項目が済んだら、作業ツリーの差分を自分で確かめ（下請けの報告を信じない。読み替えの DELEGATE）、自分は返答の欄の JSON "
    "だけを返す。下請けが Bash で書いたと報告したファイルは、パスと理由を返答の bash_writes に書く（Edit・Write の書き込みは記録に"
    "載る）。",
    "機械の関門は返答の後に線が当てる: 受け入れのテストの赤→緑と既存のテストの凍結は修正の受け付けの束、変更に当たる試験は"
    "受け付け、test_cmd は線の最後のテストの段。下請けの「commit」「人に聞く」は下請けのファイルの末尾の works の決まりに従う。",
)
# 修正役の並べの枝の単位の worktree で読む下請けのファイルの決まり（g1_prompt の tree。枝の役が起こす審査役）
G1_TREE_RULE_OF = ("この項目は修正役の並べの枝の単位の worktree {tree} で直した（ほかの枝と同時に走る）。読む・試験を回すのは全部この "
                   "worktree の中で行い（Bash は最初に cd する）、run の作業ツリーとほかの枝の worktree は書かない。差分はこの worktree と "
                   "base の間で、同じ枝の前の項目の直しも入る。")
G1_TOP = 'top="$(git rev-parse --show-toplevel)"'   # G1_PATCH の作業ツリーの根（単位の worktree の項目は tree に替える）
G1_OVERRIDES = ("下の読み替えの DISPATCH（下請けを起こさない・ほかの役の道具に Agent は無い）と DELEGATE の「役がほかの"
                "エージェントに仕事を任せることは無い」は、この修正役には効かない: この節の手順のとおり Agent で"
                "下請けを起こす。下請けがさらに下請けを起こすことは無い（どちらの型も禁じる）。読み替えの頭の行の「その prompt に、"
                "このファイル … を Read せよと書け」も下請けには書かない: 下請けのファイルの末尾の works の決まりが、その代わりに"
                "下請けの読み替えを持つ")
G1_SUB_HEAD = "## works の決まり（下請け。上の型の文にも、読み替え unattended.md にも勝つ）"
G1_SUB_RULES = (
    "読み替え（.shared/borrow/unattended.md）を読んでも、ぶつかる所はこの決まりが勝つ。審査役も Bash で git の差分を読んでよい"
    "（読み替えの GIT-RANGE の「審査役は Bash を持たない」はこの下請けに当たらない）。",
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
        "差分の主の材料は、修正役が書いた差分のファイル（上の Diff file の絶対パス）。先にそれを読む。"
        "無い・読めない時だけ、上の Base の版で `git diff <Base の版>` を走らせ（作業ツリーと base の差分。works は commit しないので、"
        "commit の範囲には差分が出ない）、`git ls-files --others --exclude-standard` で未追跡の新しいファイルの名を引いて、それぞれを"
        "Read で読む。",
        "差分は base からの全体で、前の項目の直しも入る。審査するのは今の項目の brief に当たる所で、前の項目の直しそのものは"
        "審査しない（今の項目の直しがそれを壊していれば指摘する）。",
    ),
}
G1_QUERY_LEAD = "外のサービスへ問い合わせる時の決まり（works の包みより。この決まりは型の文に勝つ）:"


def carries(node: str) -> bool:
    """役 node に座が載るか"""
    return node in SEATS


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


def words_table(seam_id: str) -> str:
    """節 seam_id の出口の語の表（型の語・works の語・欄の値の 3 列の Markdown。見出し WORDS_HEAD つき）。works の語が
    VERDICT_WORDS に無ければ ValueError（推して埋めない）"""
    words = spseam.load_seams(spseam.BORROW_DIR)[seam_id].get("words") or {}
    lack = sorted(w for w in words.values() if w not in VERDICT_WORDS)
    if lack:
        raise ValueError(f"節 {seam_id} の語 {lack} が判定の欄の語の対応（seat.VERDICT_WORDS）に無い")
    rows = [f"| {said} | {w} | `{VERDICT_WORDS[w][0]}.verdict`: `{VERDICT_WORDS[w][1]}` |" for said, w in words.items()]
    notes = [f"| （{case}） | — | {value}（型の語に依らない） |" for case, value in NOTE_ROWS]
    return "\n".join([WORDS_HEAD, "", "| 型の語 | works の語 | 欄の値 |", "| --- | --- | --- |", *rows, *notes])


def section(node: str, values: dict[str, str] | None = None) -> str:
    """役 node の座の文。載らなければ（carries が偽）空。prompt の節は values で型の穴を埋め、values が None なら ValueError。
    写しが固定と違う・穴が埋まらなければ ValueError（名指す）"""
    if not carries(node):
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
        body = [SKILL_LEAD.format(skill=skill_of(sec)) + WINS_OF.get(node, WINS), APPLIES + "\n\n" + _bullets(sec.get("applies") or []),
                NOT_APPLIES + "\n\n" + _bullets(sec.get("not_applies") or [])]
    else:
        filled = spseam.fill(sid, values, src, item, seams)
        body = [WINS_OF.get(node, WINS), PROMPT_HEAD.format(file=sec["files"][0]), filled.rstrip("\n"),
                *([words_table(sid)] if sid == VERDICT_SEAM else []),
                *([DIVERGENCE_HINT] if conflict.WORD in (sec.get("words") or {}).values() else [])]
    return "\n\n".join([HEAD, *body, rolekit.skill_overlay().rstrip("\n")]) + "\n"


def g1_prompt(seam_id: str, values: dict[str, str], tree: str | None = None) -> str:
    """修正役が起こす下請けに渡すファイルの中身: 216 の部品の節 seam_id の型を values で埋めた本文、下請けへの works の決まり
    （G1_SUB_HEAD・G1_SUB_RULES と G1_EXTRA の節の行）、検索語の規律の塊（adapter.query_rule を字のまま）。型の範囲
    `<[BASE_SHA]>..<[HEAD_SHA]>` は `<[BASE_SHA]>` に直す（作業ツリーとの差分。G1_HEAD_SHA）。写しが固定と違う・穴が埋まらない・
    規律の正本が読めなければ ValueError（名指す）。tree は修正役の並べの枝の単位の worktree（枝の役が起こす審査役。決まりの最後に G1_TREE_RULE_OF）"""
    item, src = pinned()
    filled = spseam.fill(seam_id, values, src, item)
    if "[BASE_SHA]" in values and "[HEAD_SHA]" in values:
        filled = filled.replace(f"{values['[BASE_SHA]']}..{values['[HEAD_SHA]']}", values["[BASE_SHA]"])
    try:
        rule = adapter.query_rule()
    except adapter.Unrecognised as e:
        raise ValueError(f"下請けに渡す検索語の規律を引けない: {e}") from None
    tree_rule = (G1_TREE_RULE_OF.format(tree=tree),) if tree else ()
    rules = _bullets((*G1_SUB_RULES, *G1_EXTRA.get(seam_id, ()), *tree_rule))
    return "\n\n".join([filled.rstrip("\n"), G1_SUB_HEAD, rules, G1_QUERY_LEAD + "\n" + rule]) + "\n"


def g1_section(rows: list[dict]) -> str:
    """下請けを回す修正役の指示書の節。rows は項目の順の {item, impl_file, review_file, base, patch}（fixrules.g1_values）。
    G1_HEAD → 手順（G1_STEPS）→ G1_LOOP_NOTE → 項目ごとの実装役と審査役のファイル → 申し出の種類の手引き（DIVERGENCE_HINT）→
    読み替えの上書き（G1_OVERRIDES）→ 読み替え"""
    steps = "\n".join(f"{n}. {t}" for n, t in enumerate(G1_STEPS, 1))
    files = _bullets(_g1_row(r) for r in rows)
    return "\n\n".join([G1_HEAD, steps, G1_LOOP_NOTE, files, DIVERGENCE_HINT, G1_OVERRIDES,
                        rolekit.skill_overlay().rstrip("\n")]) + "\n"


def g1_diff_cmd(base: str, patch: str, tree: str | None = None) -> str:
    """審査役に渡す差分のファイルを書くコマンド（G1_PATCH）。tree（修正役の並べの枝の単位の worktree）を渡せば、根をその worktree にする"""
    cmd = G1_PATCH.format(base=base, patch=shlex.quote(patch))
    return cmd.replace(G1_TOP, f"top={shlex.quote(tree)}") if tree else cmd


def _g1_row(r: dict) -> str:
    """g1_section の項目の 1 行"""
    return f"項目 {r['item']}: 実装役 {r['impl_file']}・審査役 {r['review_file']}・差分のコマンド `{g1_diff_cmd(r['base'], r['patch'])}`"
