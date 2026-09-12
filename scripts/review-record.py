#!/usr/bin/env python3
"""レビューループのラウンド記録を検証し、収束を妨げているものを列挙する。

**この道具は不合格しか宣言しない。** 「阻害なし」は収束の宣言ではなく、機械で
見つけられる阻害要因が無いという意味にすぎない。収束を宣言するのは人。

守備範囲は、明示返答を要求する欄が埋まっているか（素材・R1〜R4 の verdict）と、
前ラウンドとの突合（連続 2 ラウンド・持ち越しの連鎖・defer 台帳・残存 [block]）。
欄が空なら検証エラーで落ちる——約束を守ったかを、守ると書くのでなく確かめられる
形にするのが目的。**確かめられるのは形だけで、中身は機械が保証しない**——`false` / `0` / `[]`
のような縮退値も、`[nit]` 1 件だけの units も、欄としては埋まっている。中身を見る目は judge と
R1 で、ここではない。記録に載らない懸念の有無も今も人が見る。

使い方:
    python3 review-record.py <記録のディレクトリ>

**入口はこれ 1 つ。** 以前はファイル 1〜2 個を渡す入口も在ったが、隣り合う 1 ラウンドしか
見ないので、**1 ラウンド書かずに飛ばすだけで defer 台帳と過去の [block] の縛りが外れた**。手順書は
最初からディレクトリ渡ししか教えておらず、検査だけがその入口を生かしていた。

ディレクトリを渡すと `round-<N>.json` を全部読み、最新を今ラウンドとして検証・突合した
うえで、**全ラウンドの履歴**（キーごとの判定の推移・直したのに再出現した回数・
問いの台帳の推移・scalar の推移）を出す。履歴は P2 の judge に渡す入力で、人には最終
報告の冒頭で見せる——同じ指摘が毎回来る理由（コードか・レビュアーか・規約か）も、
露呈の回収で目的の外へ膨らんでいることも、数周して初めて見える傾向で、隣のラウンドと
だけ比べる形では誰にも見えなかった。

**問いの台帳**（`questions`）は人に聞く候補の置き場で、**載せた周には聞かない**。次の周の
judge が、その周の材料と独立再導出（台帳を見ずに同じ欠陥を採点した目が、同じ岐路を立てたか）で
再審し、答えた・自明・まだ・人でないと決められない、に振り分ける。機械が縛るのは——前の周の
保留（held / escalate）が黙って消えないこと、保留の出どころ（origin と depends）が記録に実在
すること、同じ [block] が 2 ラウンド連続で残ったら未決の stuck か fork で台帳に載っていること、
人の起動待ちの素材と人に諮る verdict が台帳に載っていること、そして阻害要因を「保留の問いに
帰属する」と「しない」に分けて、**前の周から持ち越した**保留にだけ帰属を認め、帰属する阻害が
在って帰属しない阻害が 0 なら「答え無しに進める仕事は無い——ここで止めて聞け」と出すこと
（前提不成立が escalate で確定したときだけは、件数に依らず先に出す）。**人に聞く時を writer が
数えない**ための道具。

**ただし機械が塞ぐのは 1 周で通る経路だけである。** 帰属の述語は記録の `origin` / `depends` と
いう自己申告で、機械には writer と judge の区別が見えない——2 周かければ、1 周目に出どころを
持たない問いを 1 件置いておくだけで帰属を作れる（実測で再現した）。2 周目以降の正しさを支えるのは
**台帳を書くのが judge であることと、R1 が台帳を監査すること**の 2 枚であって、ここではない。
この主張を広く書いていたとき、3 周にわたって「機械側の入口を 1 つずつ塞ぐ」処方が当てられ、
毎周べつの入口から同じ逃げ道が通った。**塞ぐべきは入口ではなく主張の側だった。**

初回ラウンド（N=1）は「前ラウンドの記録が無い」が阻害要因として 1 件返る（収束は連続
2 ラウンドの比較を要するので、初回が 0 になることはない。初回に阻害が無ければ、2
ラウンド目で連続 2 ラウンドが成立する）。

終了コード:
    0  阻害要因なし——今ラウンドにも前ラウンドにも無い（連続 2 ラウンド。収束の宣言ではない）
    1  阻害要因あり
    2  記録が不正（欄の欠落・値の不正・読めない・引数が違う）——1 と取り違えるな

**1 は「記録は読めたが収束を妨げるものがある」だけに使う。** 読めなかった・引数が
違ったといった計測不成立を 1 に混ぜると、非収束と区別が付かず、記録を直せば済む
状態が「まだ直っていない」と読まれて収束を永久に宣言できない。Python の未処理例外は
exit 1 なので、**例外を素通しした時点でこの契約は破れる。**

**この契約を担保するのは末尾の例外境界 1 つだけ。** 個々の型検査は診断メッセージを
具体的にするために在るのであって、契約の保証ではない——起きうる不正値を列挙する方式は
列挙の完了が原理的に保証されず、実際に列挙を 5 本足した直後に同じファイル内で 2 箇所
（`status` / `key` が unhashable な場合）と `scalars`・深いネストの JSON が漏れた。
検査を足すときは境界に頼れ。**列挙を増やして塞いだつもりになるな。**

検証を JSON Schema で宣言せず手書きにしてあるのは 2 点の理由による。①検証の半分は
ラウンド間の突合（`base` 一致・`round` 連番・持ち越しの連鎖・defer 台帳・scalar の
増分）で、**単一ドキュメントに閉じないので Schema では原理的に表現できない**。
②`jsonschema` の導入は pip を要し、README が配布上の売り文句にしている「必須は
git / python3 / bash だけ」「セットアップは要らない」と正面から衝突する。入れても①は
手書きのまま残るため、依存だけが増える。`research-loop.md` が Schema の語彙を使うのは、
あちらの検証をハーネスが持っているため。
"""

import collections
import json
import os
import re
import sys

# Windows の既定コンソールは cp932 等で、本文の記号（—）を encode できずに落ちる。
# 落ちると終了コードが 1 になり「阻害要因あり」と区別が付かないため、収束を永久に
# 宣言できなくなる。出力を UTF-8 に固定して塞ぐ。
for _stream in (sys.stdout, sys.stderr):
    # **ここは例外境界より前（インポート時）に走る。** `hasattr` はメソッドの有無しか見ないので、
    # detach 済み・クローズ済みのストリームでは `reconfigure` が例外を投げ、未捕捉のまま
    # 終了コード 1 になる——この行が塞ごうとしている当の状態（1 と区別が付かない）を、
    # 塞ぐ処理自体が作る。出力の文字化けは致命ではないので、失敗したら黙って諦める。
    try:
        _stream.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError, OSError):
        pass

def fail(msg):
    print(f"記録が不正: {msg}", file=sys.stderr)
    sys.exit(2)


# 明示返答を要求する素材。ここが正本で、手順書は列挙を持たない。
# **P1 の観点だけでなく、P0 の各段のうち他に検査経路を持たないものも含める**——
# 手順書に「報告しろ」と書くだけでは、writer が省略しても誰も気づかない（④注記）。
# 欄を要求すれば欠落が exit 2 になる（③仕組み）。P0-3（前提の実測）と P0-4（目的テキスト）は
# 既に別の検査経路を持つので入れない: 前者は R2 が所与として理想解を導くことで露見し、
# 後者は grader のレビューと `unverifiable` の分岐がある。
MATERIALS = (
    "base_determination",  # BASE をどの規則で決めたか（P0-1）
    "local_checks",  # CI のテスト・lint のローカル実行（P0-2）
    "parallel_pr",  # 並行 PR 衝突チェック（P0-5）
    "prior_decisions",  # 先行議論の突合（P0-6）——決着済み論点の蒸し返し防止
    "local_review",  # 局所レビュー（公式 skill）
    "consistency",
    "bypass",  # 標準機構の迂回
    "hygiene",  # コード衛生（文脈遮断）
    "external_standards",  # 外部標準照合＋手元の依存
    "procedure_trace",  # 手順トレース
    "gate_efficacy",  # 新設ゲートの赤の確認
    "test_double_fidelity",  # 代役の忠実性
    "main_path_observation",  # 主経路の実行観測
    "provenance",  # 根拠の出所検査
    "fix_closure",  # 修正の閉鎖実証（P3）——直したと書くだけでなく閉じたことを確かめたか
)

# 素材の状態と、その状態で追加に要求する欄。
# **属性は行に持つ。** 以前は「収束を妨げるか」「持ち越しの元になれるか」「どの俯瞰で使えるか」を
# 表の外の 5 本のリストで持っていた。**リストへの追記を忘れると、その状態は黙って緩む側に倒れる**
# ——実測: 状態を 1 つ足して「妨げる」リストへの追記だけ忘れた版で、記録に「主経路は外部都合で
# 動かせない」と書いてあるのに「阻害要因は無い」と出て exit 0 になり、検査 529 件も全部通った。
# 行に持てば、**属性を書き忘れた時点で namedtuple の生成が落ちる**（起動時に必ず落ちるので、
# 記録がその状態を使うまで待たない）。同じ形の直しは問いの種類の表で 1 度効いている。
Rule = collections.namedtuple("Rule", "fields blocks carryable")


def _rows(what, cls, rows):
    """状態の表を組む。**属性の書き忘れをここで落とす。** 素の namedtuple で組むと、
    書き忘れは TypeError になるが**末尾の例外境界より前（インポート時）**なので未処理例外の
    exit 1 になり、「阻害要因あり」と区別が付かない——契約の 3 値が 1 つ潰れる。"""
    out = {}
    for name, args in rows.items():
        try:
            out[name] = cls(*args)
        except TypeError as e:
            fail(f"{what} の '{name}' の行が不完全（属性の書き忘れ）: {e}")
    return out
# 「やらなかった」を 3 値に割ってあるのが要点——散文だと awaiting_human（手順どおりの停止）と
# not_run（逸脱）が同じ「未実施」に潰れ、さらに not_applicable にまで化ける。
# not_applicable は持ち越しでなく not_applicable と書く（条件に当たらないのは今ラウンドの
# 事実で、前ラウンドの判定の流用ではない）。
STATUS = _rows("素材の状態", Rule, {
    "found": (("count", "detail"), False, True),
    # 今ラウンドに見たが無かった（何を見たかを要求する）。
    "clean": (("checked",), False, True),
    # 前ラウンドの判定を流用した。**`clean` と分ける**——`clean` は「今回見た」で、
    # 持ち越しを `clean` に入れると最後に実際に見たラウンドが誰にも見えなくなる
    # （実例: 持ち越しを `clean` で書いた記録が 3 素材あった）。
    "carried_over": (("from_round", "reason"), False, True),
    "not_applicable": (("reason",), False, False),
    "awaiting_human": (("reason",), True, False),  # 人の起動待ちで止まっている
    "not_run": (("reason",), True, False),  # やるべきだったが飛ばした
})

# P-R の俯瞰。収束条件の半分がここに載る。以前は「人が見る」として記録の外に置いていたが、
# それは手順書自身が禁じる形——書いてあるだけの約束は writer が省略しても誰も気づかない。
REVIEWS = ("R1", "R2", "R3", "R4")
# `only_for` は「この判定を使える俯瞰」。R1 / R2 は第 1 ラウンドで必ず走り以降は再発火条件で
# 回る、R3 / R4 は P-R でのみ走る——「条件に当たらない」の意味が役ごとに違うので値を絞る。
RRule = collections.namedtuple("RRule", "fields blocks carryable only_for")
# **`carryable` に `unverifiable` / `premise-invalid` を入れるな**——blockers() はその回の
# status しか見ないので、1 度持ち越した時点で人に諮る義務が阻害要因から消え、2 ラウンド目に
# exit 0 が出る（実測: round 1 を unverifiable、round 2・3 を carried_over(from_round=1) にした
# 記録で「阻害要因は、今ラウンドにも前ラウンドにも無い」）。諮る義務が続く限り、同じ値を
# そのラウンドにもう一度書けばよい（それが「今も諮っている」の正直な記録である）。
REVIEW_STATUS = _rows("俯瞰の判定", RRule, {
    "pass": (("reason",), False, True, REVIEWS),
    "redesign-needed": (("reason",), True, False, REVIEWS),
    # 独立に確かめられない——収束でも再設計でもなく人へ。
    "unverifiable": (("reason",), True, False, REVIEWS),
    # R2 だけ。解くべき問いが立っていない——judge が根拠を検算してから人へ。
    "premise-invalid": (("reason",), True, False, ("R2",)),
    "carried_over": (("from_round", "reason"), False, True, ("R1", "R2")),
    # R3 / R4 だけ。[block] が残り P-R に到達していない。
    "not_applicable": (("reason",), False, False, ("R3", "R4")),
    "not_run": (("reason",), True, False, REVIEWS),  # やるべきだったが飛ばした
})
# 収束を宣言せずユーザーに諮る値 → それを載せる台帳の種類。同じ対応が集合・順方向・逆方向の
# 3 表現に散っていると、逆向きだけ直し忘れたときに落ちない穴になる（表 1 つに畳む）。
KIND_FOR_REVIEW_STATUS = {"unverifiable": "unverifiable", "premise-invalid": "premise"}
REVIEW_STATUS_FOR_KIND = {k: s for s, k in KIND_FOR_REVIEW_STATUS.items()}
# 逆引きは値が重複すると**後勝ちで黙って 1 件に潰れる**。今は 1:1 なので壊れていないが、
# 潰れた側の status は台帳の縛りから外れ、しかも何も鳴らない。生成の直後に長さで落とす。
assert len(REVIEW_STATUS_FOR_KIND) == len(KIND_FOR_REVIEW_STATUS), \
    "KIND_FOR_REVIEW_STATUS の値が重複している（逆引きが後勝ちで潰れる）"
# 阻害要因として数える（exit 1）が、見出しを分ける。上の表で blocks=True になっていることが
# 前提で、両方が要る——blocks が行を出し、ここが見出しを選ぶ。
REVIEW_TO_HUMAN = tuple(KIND_FOR_REVIEW_STATUS)
assert all(REVIEW_STATUS[st].blocks for st in REVIEW_TO_HUMAN), \
    "人に諮る値が blocks=False になっている（阻害要因の行が出ない）"

# nit / question / info は**意図的に**阻害要因にしない。ここを塞ぐと、受容して
# 再修正を止めるという連鎖の断ち方が使えなくなる。
LABELS = ("block", "suggest", "nit", "question", "info")

# 種類 → (origin の域, その種類で追加に要求する欄)。**域を表の中に持つ**のが要点——
# 以前は域を ORIGIN_UNIT / ORIGIN_MATERIAL / ORIGIN_REVIEW の 3 タプルに分けて if/elif で
# 振り分けていたが、3 本が全種類を覆っているかを誰も検査しておらず、覆いが崩れたときの
# 倒れ方が「制限なし」ではなく**全検査を素通り**（origin の型も実在も NO_OPEN_ORIGIN も
# 一度に外れる）だった。実測: thrash が 3 本のどこにも属さず、origin に何を書いても通り、
# 帰属と stuck の縛りを同時に外せた。表なら、種類を足して域を書き忘れた時点で下の検査が落ちる。
# 域: unit=units の key ／ material=素材名 ／ review=R1〜R4 ／ none=出どころを持たない。
# 「聞く時」の分岐を外の道具（graphloops の rules 等）が読めるように定数で持つ。**文言を直すときはここを直す**
# ——本文に生リテラルで書くと、読む側が部分一致で写しを持ち、文言を変えた周に分岐が黙って倒れる。
STOP_PREMISE = "前提不成立が確定（escalate）"
STOP_WORK_EXHAUSTED = "答え無しに進める仕事は無い"

QUESTION_KINDS = {
    # 設計の岐路——処方が機構の新設・共有面の拡大に及び、候補が複数（手順書 P2「処方の列挙」）。
    # 選択肢は帰結まで書く。零処方（取り下げ・既存の機構 1 つ）が落ちる理由は reason に。
    "fork": ("unit", ("options",)),
    # 修正が露呈させた既存の欠陥で、凍結した目的の外。別 PR に積むかを人が決める。
    # 露呈の回収は既定のまま（REVIEW.md「別 Issue への先送りを既定にするな」）で、
    # これは例外の申請。目的の内側でないかは R1 が監査する。
    "split": ("unit", ()),
    # 同じ指摘が新証拠なく再燃し、原因がコードでなく観点の誤発火。REVIEW.md の
    # どの観点かを reason に書く。剪定するかは人（「この規約の育て方」）。
    "rule": ("unit", ()),
    # 処方の誤りか設計の問題か——下の stuck_unlisted が発火の条件と要求を持つ。
    "stuck": ("unit", ()),
    # 新規 [block] が出続けて収束に向かわない。アプローチの誤りか。件数が落ちれば resolved。
    # **出どころを持たない**——件数の推移で見えるもので、特定のユニットに紐づかない。
    "thrash": ("none", ()),
    # R2 が premise-invalid。blind-judge は道具を持たないので、根拠に目的テキストの外の仮定が
    # 混じる——別 context の judge が仮定を実態で検算したかが再審の中身。
    "premise": ("review", ()),
    # 元の目的を独立に取れない（R が unverifiable）。
    "unverifiable": ("review", ()),
    # 素材が awaiting_human（未観測・打ち切られた一覧・洗えなかった決定記録・走らせられない CI）。
    # 「打ち切られた」は上限を上げれば済むことが多く、人に聞く前に再審で消える。
    "awaiting": ("material", ()),
}
ORIGIN_DOMAINS = ("unit", "material", "review", "none")
# **書ける欄を閉じる。** `depends` を `depend` と書くと、帰属も実在検査も開き禁止も**全部
# 黙って効かなくなる**（実測。exit 1 で素通りした）。`ask_human` だけを名指しで弾いていた
# ので、読む人には「他の綴り違いも弾かれる」と見えるのも悪い。**知らない欄は落とす**——
# 綴り違いが黙って無効になる側でなく、書いた本人に返る側へ倒す。
QUESTION_FIELDS = ("key", "kind", "status", "reason", "resolution", "options", "depends", "origin")
UNIT_FIELDS = ("key", "label", "disposition", "reason", "reopen_evidence")
# **状態は 2 軸である**——「決着したか」と「出どころの欠陥がまだ記録に開いて残っているか」。
# 1 つの平坦な値に潰していたとき、**判断も処方も付いた問いを「保留」と書き続けるほか無かった**
# （下の stuck_unlisted が未決の記載を要求し、P3 は「見つけた周の記録は直していても判定どおり
# 書け」と要求するので、同じ周に必ず衝突する）。その結果 `held` が帰属に乗り、決着済みしか
# 残らない周に「答え無しに進める仕事は無い——ここで止めて聞け」が偽で出て、最終報告の冒頭
# （人が決めること）にも決着済みが並んだ。**2 軸目は欄にせず記録から判定する**——書き手の
# 自己申告にすると、また 1 つ書くだけで縛りが外れる。
QUESTION_STATUS = {
    "held": (),  # 未決——次の周の judge が再審する
    # ループが決めたが、**出どころの欠陥がまだ開いている**。決着済みなので帰属にも
    # 「人が決めること」にも乗らないが、台帳からは降りない（下の TRACKED）。
    "decided": ("resolution",),
    # ループが決め、**出どころも閉じた**。次の周の台帳から落としてよい。
    # 何を根拠に決めてよいか（答えた材料か、零処方が落ちない／目的の内側／実測で優越のいずれかの
    # 規律）は手順書 P2「履歴との突合」が正本。
    "resolved": ("resolution",),
    "escalate": (),  # 再審の結果、人でないと決められない（好み・方針・可逆性の低い合意・目的の書き換え）
}
# split / rule は [block] と do-now のユニットに付けられない——人に聞く前に直す義務が消えると
# 逃げ道になる。fork / stuck は [block] に付く。**問いは阻害要因を消さない**——当のユニットは
# [block] のまま阻害要因に数え、「保留の問いに帰属」の印が付くだけ。答えが出るまで収束しない。
# **origin だけでなく depends にも当てる**——帰属の入口は 2 つで、片方だけ塞ぐと開いた [block]
# を depends に書くだけで同じ逃げ道が通る（実測で再現した）。
NO_OPEN_ORIGIN = ("split", "rule")
# **まだ人に聞く気がある**（帰属・「聞く時」・最終報告の冒頭はこれで絞る）。`decided` を
# 入れるな——決着済みが「あなたが決めること」として報告の冒頭に並ぶ。
ASKING = ("held", "escalate")
# **台帳から降りていない**（連続性・出どころの実在・stuck の振り分け・R1 の再発火はこれ）。
# `resolved` を入れるな——1 件置くだけで stuck の振り分け要求が永久に黙った（実測）。
# `decided` を入れないと、判断の付いた問いを `held` と書くほか無くなる（上の 2 軸）。
TRACKED = ("held", "escalate", "decided")
# 数で埋める欄。**欄の名前で持つ**——「整数なら空でない」と型だけで免除すると、文を要求する
# 欄に `0` を書けてしまい、`素材 'x' が未実施: 0` のような診断が出る（実測）。`count: 0` は
# 「見たが 0 件」で正当、`from_round: 0` は範囲外で validate_carry が別の診断を出す。
NUMERIC_FIELDS = ("count", "from_round")


def load(path):
    """記録を読む。**読めないことは記録の不正（2）で、非収束（1）ではない。**"""
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except OSError as e:
        fail(f"{path}: 開けない（{e.strerror}）")
    except json.JSONDecodeError as e:
        fail(f"{path}: JSON として読めない（{e}）")
    except UnicodeDecodeError as e:
        fail(f"{path}: UTF-8 として読めない（{e}）")


def is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def require_fields(obj, fields, what, why, cond):
    """`what` が `cond` なので `fields` が要る、を検査する。**欠落と空を別の診断に分ける**——
    `not obj.get(...)` だと 0 や "" を欠落と同じ扱いにし、入れてある欄について「要る」と
    嘘の診断を出して、書き手が探す先を間違える（`from_round: 0` で実際に起きた）。

    素材・俯瞰・問いの台帳の 3 箇所が同じ骨格を持つので 1 本にしてある。3 つに写していた
    とき、空の定義だけが 1 箇所で `in ("", None, [])` に分かれて、同じファイルの中に空の
    意味が 2 つある状態になった。"""
    for field in fields:
        if field not in obj:
            fail(f"{what} は {cond} なので '{field}' が要る")
        # **縮退値を「埋まっている」と扱わない。** 免除の単位は型でなく欄の名前（理由と実測は
        # NUMERIC_FIELDS の定義）。docstring に「中身は機械が保証しない」と書くのは ④注記で、
        # 書いても構造は変わらない。
        v = obj[field]
        if field in NUMERIC_FIELDS:
            if not is_int(v):
                fail(f"{what} の '{field}' は数で書け: {v!r}")
        elif not isinstance(v, (str, list)) or not v:
            fail(f"{what} の '{field}' が空（{why}）")


def validate_carry(entry, rec, path, what):
    # **型は見ない。** `from_round` は NUMERIC_FIELDS なので、ここに来る時点で
    # require_fields が整数であることを保証している（2 箇所で見ると片方が恒真になる）。
    # ここが持つのは範囲だけ——1 以上で、今ラウンドより前。
    fr = entry["from_round"]
    if fr < 1:
        fail(f"{path}: {what} の from_round が 1 以上でない: {fr!r}")
    if fr >= rec["round"]:
        fail(f"{path}: {what} の from_round（{fr}）が今ラウンド（{rec['round']}）より前でない")


def validate(rec, path, hint=None):
    if not isinstance(rec, dict):
        fail(f"{path}: 記録の最上位が object でない")
    for key in ("base", "round", "materials", "units", "reviews", "questions"):
        if key not in rec:
            extra = "（問いの台帳。人に聞く候補が無いなら空の配列を書け）" if key == "questions" else ""
            fail(f"{path}: 必須の欄 '{key}' が無い{extra}"
                 + (f"。旧世代の記録なら欄を足せ。{hint}" if hint else ""))
    if not is_int(rec["round"]):
        fail(f"{path}: 'round' が整数でない: {rec['round']!r}")
    # 連番検査（`rec["round"] != prev["round"] + 1`）は間隔しか見ないので、基点を
    # 押さえないと負値から始めて連番のまま永久に素通りできる。手順書は「1 から 1 ずつ」。
    if rec["round"] < 1:
        fail(f"{path}: 'round' が 1 以上でない: {rec['round']!r}")
    if not isinstance(rec["materials"], dict):
        fail(f"{path}: 'materials' が object でない")
    if not isinstance(rec["units"], list):
        fail(f"{path}: 'units' が配列でない")
    if not isinstance(rec["reviews"], dict):
        fail(f"{path}: 'reviews' が object でない")
    if not isinstance(rec["questions"], list):
        fail(f"{path}: 'questions' が配列でない（人に聞く候補が無いなら空の配列）")
    # `scalars` は任意の欄だが、**在るなら object**（無いと `"scalars": null` が「想定外の例外」
    # になり、書き手に何を直せばよいかが伝わらない）。
    if "scalars" in rec:
        if not isinstance(rec["scalars"], dict):
            fail(f"{path}: 'scalars' が object でない（規模指標の名前 → 数値。無いなら欄ごと省け）")
        # **値が数であることも見る。** 器の型だけ守っていたとき、`"doc_lines": "135"` と書くと
        # scalar_changes の isinstance が黙って弾いて「増えた scalar」が一生出ず、R1 に膨張が
        # 見えなかった（exit 2 にも 1 にもならない）。`bool` は int の派生なので別に落とす
        # ——`True` を通すと `False → True` が「増えた」として混ざる。
        for k, v in rec["scalars"].items():
            if not isinstance(v, (int, float)) or isinstance(v, bool):
                fail(f"{path}: scalar '{k}' が数でない: {v!r}（規模指標は R1 が増分を見る）")

    for name in MATERIALS:
        m = rec["materials"].get(name)
        if not isinstance(m, dict):
            fail(f"{path}: 素材 '{name}' の返答が無い（明示返答は全素材に要る）")
        status = m.get("status")
        if status not in STATUS:
            fail(
                f"{path}: 素材 '{name}' の status が不正: {status!r}（{'/'.join(STATUS)}）"
            )
        require_fields(m, STATUS[status].fields, f"{path}: 素材 '{name}'",
                       "何を見たかを書け", f"status={status}")
        if status == "carried_over":
            validate_carry(m, rec, path, f"素材 '{name}'")

    for name in REVIEWS:
        r = rec["reviews"].get(name)
        if not isinstance(r, dict):
            fail(f"{path}: {name} の verdict が無い（R1〜R4 は全て明示返答が要る）")
        status = r.get("status")
        if status not in REVIEW_STATUS:
            fail(
                f"{path}: {name} の status が不正: {status!r}（{'/'.join(REVIEW_STATUS)}）"
            )
        allowed = REVIEW_STATUS[status].only_for
        if name not in allowed:
            fail(
                f"{path}: {name} は {status} にできない（許されるのは {'/'.join(allowed)}）"
            )
        require_fields(r, REVIEW_STATUS[status].fields, f"{path}: {name}",
                       "何を見たかを書け", f"status={status}")
        if status == "carried_over":
            validate_carry(r, rec, path, name)

    seen_keys = {}
    for i, u in enumerate(rec["units"]):
        if not isinstance(u, dict):
            fail(f"{path}: units[{i}] が object でない")
        if not u.get("key"):
            fail(f"{path}: units[{i}] に key が無い（ラウンド間の突合に使う）")
        # 後勝ちで潰れると、重い方が消えて受容していないものが受容扱いになる。
        if u["key"] in seen_keys:
            fail(
                f"{path}: units[{i}] の key が units[{seen_keys[u['key']]}] と同じ: "
                f"{u['key']}（突合の識別子なので 1 ラウンドに 1 つ）"
            )
        seen_keys[u["key"]] = i
        # **移行の案内を先に出す。** 下の閉世界検査より前に置かないと、`ask_human` が
        # 「知らない欄」に丸められて、移し先（問いの台帳）を書いた診断が読み手に届かない。
        if "ask_human" in u:
            fail(
                f"{path}: units[{i}] に ask_human が在る——人に聞く候補は questions（問いの台帳）に"
                f" kind={u['ask_human']} / origin=このユニットの key で載せろ"
            )
        unknown = sorted(set(u) - set(UNIT_FIELDS))
        if unknown:
            fail(f"{path}: units[{i}] に知らない欄が在る: {', '.join(unknown)}"
                 f"（書けるのは {'/'.join(UNIT_FIELDS)}）")
        if u.get("label") not in LABELS:
            fail(f"{path}: units[{i}] の label が不正: {u.get('label')!r}")
        if u["label"] == "suggest":
            if u.get("disposition") not in ("do-now", "defer"):
                fail(f"{path}: units[{i}] は suggest なので disposition が要る")
            if u["disposition"] == "defer" and not u.get("reason"):
                fail(f"{path}: units[{i}] の defer に構造的理由が無い")

    validate_questions(rec, path, seen_keys)


def targets(q):
    """この問いが指す出どころ全部を **(欄名, 域, 値)** で返す。**帰属・実在検査・開き禁止・
    stuck の振り分けの 4 箇所が必ず同じ集合を見る**ための 1 本。以前は 3 箇所が別々に走査していて、`depends` を足した
    修正が 2 箇所にしか当たらず、残った 1 箇所（帰属）から同じ逃げ道がそのまま通った——
    しかもその修正は「不変条件を共有する箇所を先に全部挙げた」と書いていた（実測で再現）。
    入口が増えたときに 1 箇所だけ直し忘れる形を、走査を 1 本にして構造で消す。

    **値だけでなく域を返す。** 出どころの名前空間は 4 つ（units の key ／素材名 ／R 名 ／
    無し）在るのに、以前は平坦な文字列の集合で突き合わせていた。unit の key をリテラル
    `"R2"` にすると、別の域の問いがそのユニットを指したことになり、3 ラウンド続いた [block]
    の振り分け要求を黙らせられた。**名前を禁じるのでなく、域を持ち回って組で照合する**——
    禁じる形は、禁じる集合（素材名・R 名）が増えるたびに過去の記録の意味が変わる。

    消費者は 4 つで、**`stuck_unlisted` の `listed` だけは `origin` かつ域が unit のものに
    絞る**——stuck の振り分けた跡は「その問いがそのユニットを出どころとして立っている」
    ことで、`depends`（答え待ちで手が止まるユニット）では成立しないから。"""
    domain = QUESTION_KINDS[q["kind"]][0]
    out = [("origin", domain, q["origin"])] if "origin" in q else []
    # **`depends` は域に依らずユニットの key**（手順書 P2「履歴との突合」が正本）。問いの
    # key でも素材名でもない——ここを域と同じに扱うと、綴り違いが黙って無効になる。
    out.extend(("depends", "unit", d) for d in q.get("depends", []))
    return out


def validate_questions(rec, path, unit_index):
    """問いの台帳の 1 ラウンド内の整合。素材・R 由来の出どころは実在と状態まで見る。
    units 由来の出どころ（origin と depends）の実在は defer 台帳が要るので main() 側
    （question_origins_exist）。人の起動待ちの素材・人に諮る verdict は必ず台帳に
    載っている（聞く候補が散文にだけ在って、台帳を見た人が「無い」と読む形を塞ぐ）。"""
    seen = set()
    for i, q in enumerate(rec["questions"]):
        where = f"{path}: questions[{i}]"
        if not isinstance(q, dict):
            fail(f"{where} が object でない")
        if not q.get("key"):
            fail(f"{where} に key が無い（周をまたぐ突合に使う。何を決めるかを一文で）")
        if q["key"] in seen:
            fail(f"{where} の key が重複: {q['key']}（突合の識別子なので 1 ラウンドに 1 つ）")
        seen.add(q["key"])
        unknown = sorted(set(q) - set(QUESTION_FIELDS))
        if unknown:
            fail(f"{where} に知らない欄が在る: {', '.join(unknown)}"
                 f"（書けるのは {'/'.join(QUESTION_FIELDS)}。綴り違いは黙って無効になる）")
        kind = q.get("kind")
        if kind not in QUESTION_KINDS:
            fail(f"{where} の kind が不正: {kind!r}（{'/'.join(QUESTION_KINDS)}）")
        status = q.get("status")
        if status not in QUESTION_STATUS:
            fail(f"{where} の status が不正: {status!r}（{'/'.join(QUESTION_STATUS)}）")
        domain, extra_fields = QUESTION_KINDS[kind]
        require_fields(q, ("reason",) + extra_fields + QUESTION_STATUS[status], where,
                       "きっかけ・根拠を書け", f"kind={kind} / status={status}")
        if kind == "fork":
            opts = q["options"]
            if (
                not isinstance(opts, list)
                or len(opts) < 2
                or not all(isinstance(o, str) and o for o in opts)
            ):
                fail(f"{where} の options は選択肢 2 つ以上の配列（各項に帰結まで書け）")
        deps = q.get("depends", [])
        if not isinstance(deps, list) or not all(isinstance(d, str) and d for d in deps):
            fail(f"{where} の depends は、この答え待ちで手を止めるユニットの key の配列")
        origin = q.get("origin")
        # **2 軸目を記録から判定する。** 決着した問い（`decided` / `resolved`）は、出どころの
        # 欠陥がまだ開いているかで書き分ける。書き手の申告に任せると、`resolved` を 1 件置いて
        # stuck の振り分け要求を黙らせる形（実測で再現した穴）がそのまま戻る。
        if status in ("decided", "resolved") and domain == "unit" and origin in unit_index:
            still_open = is_open(rec["units"][unit_index[origin]])
            if status == "resolved" and still_open:
                fail(f"{where}: 出どころが [block] / do-now のまま resolved（決着したが欠陥が"
                     "残っているなら decided。resolved は出どころも閉じた問いだけ）")
            if status == "decided" and not still_open:
                fail(f"{where}: 出どころが閉じているのに decided（欠陥が記録から消えたなら"
                     "resolved にして、次の周の台帳から降ろせ）")
        # **開き禁止は域の枝の外に置く。** `NO_OPEN_ORIGIN` の 2 種類はどちらも域が unit なので
        # 中に置いても今は等価だが、非 unit 域の種類をこの表に足した瞬間に柵が黙って外れる
        # （`depends` は域に依らずユニットの key なので、その種類でも開いたユニットを指せる）。
        # 「表に足して書き忘れたら落ちる」という当のファイルの規律の、例外になっていた。
        if status in ASKING and kind in NO_OPEN_ORIGIN:
            for _, _domain, k in targets(q):
                if k in unit_index and is_open(rec["units"][unit_index[k]]):
                    fail(
                        f"{where}: {kind} の origin / depends が [block] / do-now: {k}"
                        "（人に聞く前に直す義務が消える。defer にして構造的理由を書け）"
                    )
        if domain == "unit":
            if not origin:
                fail(f"{where} は kind={kind} なので origin（units の key）が要る")
        elif domain == "material":
            if origin not in MATERIALS:
                fail(f"{where} は kind={kind} なので origin は素材名: {origin!r}")
            if status in ASKING and rec["materials"][origin]["status"] != "awaiting_human":
                fail(
                    f"{where}: awaiting の origin '{origin}' が awaiting_human でない"
                    "（動かせた・確かめられたなら resolved にして根拠を書け）"
                )
        elif domain == "review":
            if origin not in REVIEWS:
                fail(f"{where} は kind={kind} なので origin は R1〜R4: {origin!r}")
            want = REVIEW_STATUS_FOR_KIND[kind]
            if status in ASKING and rec["reviews"][origin]["status"] != want:
                fail(f"{where}: {kind} の origin {origin} が {want} でない（解けたなら resolved にしろ）")
        elif domain == "none":
            # **origin も depends も持てない。** origin だけ塞いでいたとき、同じ紐づけが
            # depends から通って開いた [block] 全件に帰属が付いた（実測で再現）。
            if targets(q):
                fail(
                    f"{where} は kind={kind} なので origin / depends を持てない（出どころを"
                    "持たない種類。特定のユニットに紐づけると、帰属と stuck の縛りをそこから外せる）"
                )
        else:
            # 種類を足して域を書き忘れたらここで落ちる（列挙の覆いを人の注意に頼らない）。
            fail(f"{where}: kind={kind} の origin の域が不正: {domain!r}（{'/'.join(ORIGIN_DOMAINS)}）")
    # 載っていないと「聞く時」の判定（帰属）に乗らず、聞かれないまま暴走ガードまで回る。
    # **未決で**数えるのは、resolved を数えると素材が awaiting_human のままでも要求が満たされるから。
    origins = {
        (q["kind"], q.get("origin")) for q in rec["questions"] if q["status"] in ASKING
    }
    for name in MATERIALS:
        if rec["materials"][name]["status"] == "awaiting_human" and ("awaiting", name) not in origins:
            fail(
                f"{path}: 素材 '{name}' が awaiting_human なのに問いの台帳に無い"
                "（何を誰に聞くかを questions に kind=awaiting で書け。再審で消えることが多い）"
            )
    for name in REVIEWS:
        st = rec["reviews"][name]["status"]
        if st in REVIEW_TO_HUMAN:
            kind = KIND_FOR_REVIEW_STATUS[st]
            if (kind, name) not in origins:
                fail(
                    f"{path}: {name} が {st} なのに問いの台帳に無い"
                    f"（questions に kind={kind} / origin={name} で載せ、judge の再審に掛けろ）"
                )


def is_open(u):
    return u["label"] == "block" or (
        u["label"] == "suggest" and u.get("disposition") == "do-now"
    )


def validate_against(rec, prev, carried=None):
    """前ラウンドとの突合のうち、記録の不正（2）に倒すもの。"""
    if prev["base"] != rec["base"]:
        fail(
            f"round {rec['round']}: 2 つの記録の base が違う（基準点を動かすな）。"
            "別のレビューの記録が同じディレクトリに混ざっていないか——"
            "混ざっているなら消さずに別ディレクトリへ退避してから始めろ"
        )
    # 持ち越しの連鎖。from_round は「実際に見たラウンド」なので、前ラウンドも持ち越し
    # なら同じ値、前ラウンドで実際に見たなら前ラウンドの番号。未実施・条件外からは
    # 持ち越せない（持ち越しは判定の流用であって、無かった判定は流用できない）。
    # **域を持ち回る。** 以前は `what`（診断に出す表示名）を `what in REVIEWS` で判別に使って
    # いた——素材側だけ `素材 '…'` の接頭辞が付くので偶然当たっていただけで、**俯瞰側の表示を
    # 整えた瞬間に判別が恒偽になり、全ての俯瞰が素材の規則で検査される**（例外も差分も出ない）。
    # `targets()` で潰したのと同じ「平坦な文字列を域をまたいで比べる」形が、ここに残っていた。
    for domain, what, now, before in (
        *(("material", f"素材 '{n}'", rec["materials"][n], prev["materials"][n]) for n in MATERIALS),
        *(("review", n, rec["reviews"][n], prev["reviews"][n]) for n in REVIEWS),
    ):
        if now["status"] != "carried_over":
            continue
        ps = before["status"]
        if ps == "carried_over":
            if now["from_round"] != before["from_round"]:
                fail(
                    f"round {rec['round']}: {what} の持ち越しが連鎖していない: 前ラウンドは "
                    f"round {before['from_round']} から、今ラウンドは round {now['from_round']} から"
                )
        elif (REVIEW_STATUS[ps].carryable if domain == "review" else STATUS[ps].carryable):
            if now["from_round"] != prev["round"]:
                fail(
                    f"round {rec['round']}: {what} の from_round（{now['from_round']}）が前ラウンド"
                    f"（{prev['round']}）でない——前ラウンドは実際に見ている"
                )
        else:
            fail(f"round {rec['round']}: {what} は前ラウンドが {ps} なので持ち越せない（判定が無い）")

    # defer 台帳。**前ラウンドまでに** defer と確定したキーが再び [block] / do-now に
    # 上がるのは、新しい根拠が付いたときだけ（手順書 P4）。根拠の欄が無い再出現は、judge が
    # 台帳を渡されていないか無視したかで、記録を直して（judge を台帳つきで回して）出し直す。
    # carried は「それより前のラウンドまでの台帳」。隣の 1 ラウンドだけを見ると、
    # 1 ラウンド記録から落とすだけで再審の縛りが外れる（受容済みの論点が新証拠なしに戻る）。
    # **理由と一緒にラウンド番号を持つ。** 台帳は全ラウンドの和なので「前ラウンドの defer 理由」
    # は前ラウンドとは限らず、書き手は存在しない周の記録を探しに行った（実測: round 2 で defer・
    # round 3/4 は記録に無し・round 5 で block の形で「前ラウンドの」と出た）。
    ledger = dict(carried or {})
    ledger.update({
        u["key"]: (u.get("reason"), prev["round"])
        for u in prev["units"]
        if u["label"] == "suggest" and u.get("disposition") == "defer"
    })
    for u in rec["units"]:
        if u["key"] in ledger and is_open(u) and not u.get("reopen_evidence"):
            why, at = ledger[u["key"]]
            fail(
                f"round {rec['round']}: 既受容（defer）のキーが再び {u['label']} になったが "
                f"reopen_evidence が無い: {u['key']}（round {at} の defer 理由: {why}）"
            )

    # 問いの台帳の連続性。黙って落ちるのは「消えた [block]」と同じ形で、聞くはずだった問いが
    # 誰にも聞かれずに終わる。
    now_q = {q["key"] for q in rec["questions"]}
    for q in prev["questions"]:
        if q["status"] in TRACKED and q["key"] not in now_q:
            fail(
                f"round {rec['round']}: 前ラウンドの問い（{q['status']}）が今ラウンドの台帳に"
                f"無い: {q['key']}（再審して held / resolved / escalate のどれかで書け）"
            )
    # **台帳を監査する経路は R1 しか無い。** 再発火条件の正本は手順書 P-R の R1 で、そこに
    # 台帳の条件が無かった理由と実測もあちらが持つ。散文の条件に 1 行足しても読み落としは
    # 誰にも見えないので、機械の側からも縛る。
    # 見るのは「行が増えたか」でなく「**監査対象が変わったか**」——同じ述語を、票の持ち越しを
    # 決める定番（Gerrit の copyCondition は `changekind` で中身の変化を見る／GitHub の保護
    # ブランチは差分を変える push で承認を stale にする）が使っている。key の新規性だけを
    # 見ていたとき、**同じ key のまま kind / origin / options を総取り替えする周**と、
    # **resolved を held に戻す周**が、どちらも監査を素通りした（実測）。`reason` は入れない
    # ——書き足しただけで毎周再発火すると、持ち越しの意味が薄れる。
    if ledger_shape(rec) != ledger_shape(prev) and rec["reviews"]["R1"]["status"] == "carried_over":
        fail(
            f"round {rec['round']}: 台帳の未決の問いが前ラウンドから変わったのに R1 が "
            "carried_over（台帳を監査するのは R1 だけ。台帳が動いた周は R1 を走らせろ）"
        )
    return ledger


def ledger_shape(rec):
    """未決の問いの中身（`reason` を除く）。R1 の再発火条件に使う——**中身が同じ周だけが
    監査を持ち越せる**。`reason` を外すのは、書き足しただけの周で毎回再発火させないため。"""
    return {
        (q["key"], q["kind"], q.get("origin"), tuple(q.get("depends", [])),
         q["status"], tuple(q.get("options", [])))
        for q in rec["questions"] if q["status"] in TRACKED
    }


def question_origins_exist(rec, ledger):
    """保留中の問いの出どころ（units の key）が、今ラウンドの units か defer 台帳に在ること。
    defer は受容が続く限り記録から落ちてよい（台帳が持つ）ので、units だけを見ると
    正当な記録を弾く。どちらにも無ければ、欠陥は直ったのに問いだけが生き残っている。

"""
    known = {u["key"] for u in rec["units"]} | set(ledger)
    for i, q in enumerate(rec["questions"]):
        if q["status"] not in TRACKED:
            continue
        for what, domain, key in targets(q):
            # 見るのは域が unit のものだけ（素材名・R 名は units に無くて当然）。`depends` は
            # 域に依らず unit なので、どの種類の問いでも実在を見る——ここを種類で絞っていた
            # とき、綴り違いが黙って無効になり 1 文字で「聞く時」の結論が反転した（実測）。
            if domain != "unit":
                continue
            if key not in known:
                fail(
                    f"round {rec['round']}: questions[{i}] の {what} が今ラウンドの units にも "
                    f"defer 台帳にも無い: {key}（直ったなら resolved にして根拠を書け）"
                )


def _row(msg, target, asked, fresh, note_fresh):
    """阻害要因の 1 行を (本文, 帰属) にする。`target` は `(域, 値)` の組で、**平坦な文字列に
    しない**——unit の key がリテラル `"R2"` や素材名だと、別の域の問いがその行を掴む。
    帰属しないが今ラウンドの問いが指しているものには、なぜ「仕事」のままなのかを本文に添える。"""
    if target in asked:
        return (msg, True)
    return (msg + note_fresh if target in fresh else msg, False)


def blockers(rec, prev=None, ledger=None, prev_blocks=None):
    """今ラウンドの阻害要因を (本文, 帰属) の組で返す。**帰属は真偽の 2 値だけ**——
    帰属する阻害は「答えを待っている」、しない阻害は「まだ仕事が在る」。連続 2 ラウンドの
    会計のような合成行は帰属の概念を持たないので、ここには混ぜない（main() が別に持つ）。

    **帰属を認めるのは、前の周にも同じ key で保留だった問いが今ラウンドで指す出どころだけ。**
    今ラウンドに初めて立った問いは、まだ再審を 1 周もくぐっていないので「答えを待っている」では
    ない。縛っているのは**問いの key の同一性**であって出どころの固定ではない——再審で
    `thrash` から `fork` へ振り替えて出どころを書き直すのは正当な記録なので、そこは弾かない。ここを今ラウンド
    だけで見ていたとき、機械は問いが立ったその周に「ここで止めて聞け」と出していた——
    「載せた周には聞かない」という当の設計が、同じ出力の中で破れていた（実測）。
    prev が無い初回ラウンドでは帰属が空になり、原理的に聞かない（収束が次ラウンド以降なのと同じ既定）。

    prev を渡すと **[block] の行に** 過去ラウンド比の注記（新規 / 残存）を、台帳に在るキーには
    （既受容の再審）を添える。prev_blocks は「過去に [block] だったキー」の集合（全ラウンドの和）。"""
    out = []
    ledger = ledger or {}
    carried_q = (
        {q["key"] for q in prev["questions"] if q["status"] in ASKING} if prev else set()
    )
    asked, fresh = set(), set()
    for q in rec["questions"]:
        if q["status"] not in ASKING:
            continue
        where = asked if q["key"] in carried_q else fresh
        where.update((domain, k) for _, domain, k in targets(q))
    # 今ラウンドに立った問いの出どころには、帰属でなくこの印を付ける。**印が要るのは、
    # 問いが付いているのに「仕事」に数えられている理由が、これが無いと読み手に見えないから。**
    # 肯定の文言なので、「立った周には聞かない」が効いていることを検査で positive に確かめられる。
    note_fresh = "（今ラウンドに立った問い——再審は次の周）"
    prev_blocks = prev_blocks or set()

    for name in MATERIALS:
        m = rec["materials"][name]
        if STATUS[m["status"]].blocks:
            label = "人の起動待ち" if m["status"] == "awaiting_human" else "未実施"
            out.append(_row(f"素材 '{name}' が{label}: {m['reason']}",
                            ("material", name), asked, fresh, note_fresh))

    # 「見つけた」と書いた素材が 1 つでも在るのに units が空なら、judge が根本ユニットに
    # 落としていないか、落とした結果が記録に載っていない。中身は解釈しないが、
    # 「正直に見つけたと書いたのに 1 件も挙げていない」という形だけは数えられる。
    # **[nit] を 1 件置けば形は満たせる。中身は機械が保証しない**——記録を弱く書けば黙るのは
    # 「開いたユニットを記録から落とす」のと同じ族で、どちらも key と label が履歴と最終報告に
    # 残るので人が見る。**「開いた unit が 0」に変えるな**——[nit] だけ・defer だけで終わる周は
    # 正当な収束の形（defer は定義上この PR で直さない）なので、素材を found と正直に書いた
    # 周に限って exit 0 が原理的に出なくなり、記録を偽る以外の収束経路が消える。
    if not rec["units"]:
        got = [n for n in MATERIALS if rec["materials"][n]["status"] == "found"]
        if got:
            out.append((
                f"素材が found なのに units が空: {', '.join(got)}"
                "（見つけたものを根本ユニットに落としたか確かめろ）",
                False,
            ))

    for u in rec["units"]:
        if not is_open(u):
            continue
        head = "[block] 未解消" if u["label"] == "block" else "[suggest] do-now 未対応"
        note = ""
        if prev is not None:
            if u["key"] in ledger:
                note = f"（既受容 defer の再審。新証拠: {u['reopen_evidence']}）"
            elif u["label"] == "block" and u["key"] in prev_blocks:
                # 「stuck の疑い」とは書かない——手順書の stuck は 2 ラウンド連続で、
                # 全ラウンドの和で見るこの印はそれより広く発火する（一度消えて別原因で
                # 戻った場合にも付き、履歴側の「消えて N 回戻った」と矛盾する）。
                note = "（残存——過去のラウンドにも在った）"
            elif u["label"] == "block":
                note = "（新規）"
        out.append(_row(f"{head}{note}: {u['key']}", ("unit", u["key"]), asked, fresh, note_fresh))

    for name in REVIEWS:
        r = rec["reviews"][name]
        if not REVIEW_STATUS[r["status"]].blocks:
            continue
        if r["status"] not in REVIEW_TO_HUMAN:
            out.append((f"{name} が {r['status']}: {r['reason']}", False))
        else:
            out.append(_row(
                f"{name} が {r['status']}（収束を宣言せずユーザーに諮れ）: {r['reason']}",
                ("review", name), asked, fresh, note_fresh,
            ))

    # R3 / R4 の not_applicable は「P-R に到達していない」の意味なので、到達を妨げる
    # 阻害要因が他に無いなら、P-R を飛ばしたことになる。
    if not out:
        for name in REVIEWS:
            r = rec["reviews"][name]
            if r["status"] == "not_applicable":
                out.append((
                    f"{name} が not_applicable だが、P-R への到達を妨げる阻害要因が記録に無い"
                    f"（[block] 0・素材の未実施 0 なら P-R を実行しろ）: {r['reason']}",
                    False,
                ))
    return out


def stuck_unlisted(rounds):
    """同じ [block] キーが 3 ラウンドの記録に続けて在る（＝2 ラウンド連続の残存。手順書の stuck）
    のに、問いの台帳に無いもの。judge が処方の誤りか設計の問題かを振り分けた跡（stuck か fork）が
    無いまま回すと、暴走ガードまで同じ修正が繰り返される。隣り合う全ての 3 つ組で見る。"""
    out = []
    for i in range(2, len(rounds)):
        chain = set.intersection(
            *({u["key"] for u in r["units"] if u["label"] == "block"} for r in rounds[i - 2:i + 1])
        )
        # **台帳から降りていない問いだけを数える**（`resolved` を 1 件置くと永久に黙った——実測。
        # 一方 `decided` を外すと、判断の付いた問いを `held` と書くほか無くなる）。**種類（stuck / fork）では絞らない**
        # ——絞っているのは下の `what == "origin" and domain == "unit"`（域）である。`split` / `rule` は
        # 開いた出どころを持てない（NO_OPEN_ORIGIN）ので、連鎖のキー（必ず [block]＝開いている）を
        # origin に置けるのは結局 stuck と fork だけになり、種類の絞りは恒真だった。恒真な柵を
        # 残すと読む人は 2 本で守られていると信じる（REVIEW.md「導線を作る手段の優先順位」）。
        listed = {
            k
            for q in rounds[i]["questions"]
            if q["status"] in TRACKED
            for what, domain, k in targets(q)
            if what == "origin" and domain == "unit"
        }
        out.extend((rounds[i]["round"], k) for k in sorted(chain - listed))
    return out


def carry_summary(rec):
    """持ち越しの一覧。機械は中身を見ないので、何ラウンド前の判定かを見せるだけ。"""
    out = []
    # 表示名から域を復元しない（上の validate_against と同じ理由）。名前の並びを域と一緒に持つ。
    for label, entries, names in (
        ("素材", rec["materials"], MATERIALS),
        ("俯瞰", rec["reviews"], REVIEWS),
    ):
        for name in names:
            e = entries[name]
            if e["status"] == "carried_over":
                age = rec["round"] - e["from_round"]
                out.append(f"{label} {name}: round {e['from_round']} の判定を流用（{age} ラウンド前）")
    return out


def scalar_changes(rec, prev):
    """前ラウンド比で増えた scalar。**相殺の有無は判定せず、R1 へ渡すだけ。**

    これを阻害要因に混ぜないこと——測れるものをゲートにすると、規則が測れるものへ
    寄る。増分の正当化を求める相手は人（R1）であって、この道具ではない。
    """
    if prev is None:
        return []
    out = []
    # `or {}` で正規化しない。**非 dict は末尾の例外境界で exit 2 に倒すのが正しい**——
    # falsy を黙って空 dict に読み替えると、`"scalars": 0` のような壊れた記録が「scalar なし」
    # として通る（冒頭 docstring の「検査を足すときは境界に頼れ」と同じ理由）。
    for name, now in rec.get("scalars", {}).items():
        before = prev.get("scalars", {}).get(name)
        if (
            isinstance(before, (int, float))
            and isinstance(now, (int, float))
            and now > before
        ):
            out.append(f"scalar '{name}': {before} → {now}")
    return out


def load_dir(path):
    """`round-<N>.json` を番号順に全部読む。**入口をこれ 1 つにした理由は冒頭 docstring。**"""
    found = {}
    for name in sorted(os.listdir(path)):
        # 受理は厳しく: `\d` は Unicode の桁（`round-\u0661.json` 等）を拾い `int()` も
        # それを解釈するので、**正規でない綴りが黙って受理される**。ASCII の桁に限る。
        m = re.fullmatch(r"round-([0-9]+)\.json", name)
        if not m:
            # **検知は受理の補集合で持つ。** 「正規名に近い」を正規表現の軸（桁・英字の大小）
            # で定義していたとき、桁の軸を塞いだら区切り・語・拡張子の軸から同じ逃げ道が
            # 通った（実測: `round\u20111.json`〈非改行ハイフン〉・`\uff52ound-1.json`・
            # `round-1.js\u03bfn`〈ギリシャ文字 o〉はどれも黙って捨てられた）。軸を足す形は
            # 足すたびに残りの軸から通られるので、**受理しなかったものを全部鳴らす**。
            # 除くのは 2 つだけ——ディレクトリは退避先（`archive-<BASE>`）で、下位は読まない
            # 規約。ドットで始まるものは OS・道具の成果物で記録ではない。
            if not os.path.isdir(os.path.join(path, name)) and not name.startswith("."):
                fail(f"{path}: {name} は記録の名前でない（`round-<N>.json`。N は ASCII の数字）"
                     "——綴り違いが黙って捨てられると、1 ラウンド書かずに飛ばしたのと同じに"
                     "なる。記録でないファイルをこのディレクトリに置くな")
            continue
        n = int(m.group(1))
        # 0 番は下の range(1, ...) から外れ、読まれも検証もされずに捨てられる。
        # 連番の穴は落とすのに 0 番だけ黙って消えるのは、同じ形の取りこぼし。
        if n < 1:
            fail(f"{path}: {name} は 1 から始まる番号でない（round-1.json から始めろ）")
        # ゼロ詰めの別名（round-01.json）は同じ番号に潰れ、片方が読まれもせずに
        # 捨てられる。連番の穴は落とすのに重複が通ると、静かに別の記録を検証する。
        if n in found:
            fail(f"{path}: {name} と {os.path.basename(found[n])} が同じ番号 {n} を指している")
        found[n] = os.path.join(path, name)
    if not found:
        fail(f"{path}: round-<N>.json が 1 つも無い")
    rounds = []
    for n in range(1, max(found) + 1):
        if n not in found:
            fail(f"{path}: round-{n}.json が無い（前ラウンド分を消すな。連番の穴は履歴を壊す）")
        rec = load(found[n])
        # 前のレビューの記録が残っていると、古い schema の欄不足か base の不一致で
        # ここから先へ進めない。手順書は記録を消すなと言っているので、退避先を案内する。
        validate(rec, found[n], hint="別のレビューの記録が混ざっていないか——"
                                     "混ざっているなら消さずに別ディレクトリへ退避しろ")
        if rec["round"] != n:
            fail(f"{found[n]}: 'round' が {rec['round']}——ファイル名の番号と違う")
        rounds.append(rec)
    return rounds


def reappeared_after_gap(seen):
    """直したはずのキーが再出現した回数。judge に理由（コード／レビュアー／規約）を問わせる材料。

    seen[i] は round i+1 の記録にそのキーが在ったか。初出は「戻った」ではないので、
    それ以前に一度でも在ったことを条件に入れる。
    """
    return sum(
        1 for i in range(1, len(seen)) if seen[i] and not seen[i - 1] and any(seen[:i - 1])
    )


def timeline(by_round, n):
    """キーごとの「r1:… → r2:…」の系列。ユニットと問いで同じ形を 2 度書かない。"""
    return " → ".join(
        f"r{r}:{by_round[r]}" if r in by_round else f"r{r}:—" for r in range(1, n + 1)
    )


def history(rounds):
    """全ラウンドの傾向。**機械は解釈しない**——judge が読んで、再燃の原因（コード／
    レビュアー／規約）や目的の外への膨張を判断する材料にする。人には最終報告の冒頭。"""
    if len(rounds) < 2:
        return []
    out = []
    keys = {}
    for rec in rounds:
        for u in rec["units"]:
            state = u["label"]
            if u["label"] == "suggest":
                state += "/" + u["disposition"]
            keys.setdefault(u["key"], {})[rec["round"]] = state
    n = rounds[-1]["round"]
    for key, by_round in keys.items():
        seen = [r in by_round for r in range(1, n + 1)]
        gaps = reappeared_after_gap(seen)
        note = f"（消えて {gaps} 回戻った）" if gaps else ""
        out.append(f"{key}\n      {timeline(by_round, n)}{note}")
    qkeys = {}
    for rec in rounds:
        for q in rec["questions"]:
            qkeys.setdefault(q["key"], {})[rec["round"]] = f"{q['status']}({q['kind']})"
    for key, by_round in qkeys.items():
        out.append(f"問い: {key}\n      {timeline(by_round, n)}")
    open_counts = [sum(1 for u in r["units"] if is_open(u)) for r in rounds]
    out.append("要対応（[block]＋do-now）の件数: " + " → ".join(map(str, open_counts)))
    if qkeys:
        out.append("問いの台帳の件数（保留・人へ・ループが決めた）: " + " → ".join(
            "・".join(
                str(sum(1 for q in r["questions"] if q["status"] == s))
                for s in ("held", "escalate", "resolved")
            )
            for r in rounds
        ))
    for name in sorted({k for r in rounds for k in r.get("scalars", {})}):
        vals = [r.get("scalars", {}).get(name) for r in rounds]
        out.append(f"scalar '{name}': " + " → ".join("—" if v is None else str(v) for v in vals))
    return out


def main():
    if len(sys.argv) != 2:
        print(__doc__, file=sys.stderr)
        fail(f"引数は記録のディレクトリ 1 個（受け取った数: {len(sys.argv) - 1}）")
    if not os.path.isdir(sys.argv[1]):
        fail(f"{sys.argv[1]}: ディレクトリでない（記録は round-<N>.json をまとめた"
             "ディレクトリごと渡せ。ファイル 1〜2 個を渡す入口は消した——"
             "隣り合う 1 ラウンドしか見ないので、1 ラウンド書かずに飛ばすだけで"
             "defer 台帳と過去の [block] の縛りが外れた）")

    rounds = load_dir(sys.argv[1])
    rec = rounds[-1]
    prev = rounds[-2] if len(rounds) > 1 else None
    ledger = {}
    # 連鎖と台帳は隣り合う全ての組で突合する（履歴の途中で壊れていても最新だけ見ると通る）。
    # 台帳は**代入でなく累積**する。組ごとに置き換えると隣の 1 ラウンドしか残らず、
    # 1 ラウンド記録から落とすだけで再審の縛りが消える（手順書は全ラウンドの和と書いている）。
    question_origins_exist(rounds[0], ledger)
    for a, b in zip(rounds, rounds[1:]):
        ledger = validate_against(b, a, ledger)
        question_origins_exist(b, ledger)

    grew = scalar_changes(rec, prev)
    if grew:
        print("増えた scalar（阻害要因ではない。相殺する削除があるか R1 に見せろ）:")
        for line in grew:
            print(f"  - {line}")

    carried = carry_summary(rec)
    if carried:
        print("持ち越し（機械は中身を見ない。古いものほど、見直す理由が無いかを疑え）:")
        for line in carried:
            print(f"  - {line}")

    if rec["questions"]:
        print("問いの台帳（人に聞く候補。載せた周には聞かない——次の周の judge が再審する。"
              "目的の内側でないかは R1 が監査）:")
        for q in rec["questions"]:
            tag = {"held": "未決", "escalate": "人へ", "decided": "ループが決めた（欠陥は残存）",
                   "resolved": "ループが決めた"}[q["status"]]
            tail = q["reason"] if q["status"] in ASKING else q["resolution"]
            print(f"  - [{tag}] {q['kind']}: {q['key']} — {tail}")

    # `if rounds:` は書かない——`load_dir` が空なら fail するので恒真だった。
    lines = history(rounds)
    if lines:
        print(f"履歴（round 1〜{rec['round']}。P2 の judge に渡せ。機械は解釈しない）:")
        for line in lines:
            print(f"  - {line}")

    # **落とすのは、直すのに要るものを出し切ってから。** 他の exit 2 の経路は印字より前に在るが、
    # この 1 本だけは「どのキーが 3 周続いたか」を履歴で見ないと直しようがない。印字の前に
    # 落としていたとき、この 1 行以外の診断が何も出なかった。
    for n, k in stuck_unlisted(rounds):
        fail(
            f"round {n}: 同じ [block] が 3 ラウンドの記録に続けて在る（2 ラウンド連続の残存＝stuck）のに"
            f"問いの台帳に無い: {k}（処方の誤りか設計の問題かを judge に振り分けさせ、stuck か fork として載せろ）"
        )

    prev_blocks = {
        u["key"] for r in rounds[:-1] for u in r["units"] if u["label"] == "block"
    }
    found = blockers(rec, prev, ledger, prev_blocks)
    if prev is not None:
        here = {u["key"] for u in rec["units"]}
        dropped = [k for k in ledger if k not in here]
        if dropped:
            print("前ラウンドの defer で今ラウンドの記録に無いキー（台帳には残る。最終報告に載せろ）:")
            for k in dropped:
                print(f"  - {k}")
        # **機械はこれを数えない**——一覧は判定でなく P2 の judge への入力である（数えられない
        # 理由の 2 通りの検討は手順書 P2「履歴との突合」が持つ。ここに写すと片方が腐る）。
        gone = [k for k in sorted(prev_blocks) if k not in here]
        if gone:
            print("過去のラウンドの [block] で今ラウンドの記録に無いキー"
                  "（直ったのか、記録から落ちたのかは機械には見えない。P2「履歴との突合」でルーターに掛けろ）:")
            for k in gone:
                print(f"  - {k}")

    # 連続 2 ラウンドの会計。今ラウンドが阻害なしでも、前ラウンドに阻害があれば 1 ラウンド目。
    # **これを writer に数えさせない**——採点を自己申告にしないのと同じ理由。
    # これは今ラウンドの阻害ではなく帰属の概念を持たないので、blockers の戻り値に混ぜず
    # ここで別に持つ（混ぜると呼び出し側が 3 値目を書かされ、表示は真偽・判定は 3 値という
    # 2 通りの読み方が同じ欄に同居する）。回せば消えるので「仕事」にも数えない。
    accounting = []
    if prev is None:
        accounting.append("前ラウンドの記録が無い（連続 2 ラウンドの 1 ラウンド目。収束は次ラウンド以降）")
    else:
        prev_found = blockers(prev)
        if prev_found:
            accounting.append(
                f"前ラウンドに阻害要因が {len(prev_found)} 件あった"
                "（連続 2 ラウンドの 1 ラウンド目。今ラウンドが阻害なしでも収束は次ラウンド）"
            )

    if found or accounting:
        print(f"収束を妨げるもの {len(found) + len(accounting)} 件:")
        for msg, asked in found:
            print(f"  - {msg}" + ("（保留の問いに帰属——答えを待っている）" if asked else ""))
        for msg in accounting:
            print(f"  - {msg}")
        # 人に聞く時。**writer が数えるな**——聞くのが早すぎると、次の周の目が解けた問いで
        # 人を止める。遅すぎることは無い（帰属しない阻害が 0 になった瞬間に出る）。
        waiting = sum(1 for _, a in found if a)
        work = len(found) - waiting
        if any(q["kind"] == "premise" and q["status"] == "escalate" for q in rec["questions"]):
            # 「再審で」と書くな——この短絡は持ち越しを条件にしないので、問いが立った
            # その周にも発火する（手順書がそう設計している。premise だけの例外）。同じ出力に
            # 「今ラウンドに立った問い——再審は次の周」と並ぶと、読み手には矛盾にしか見えない。
            print(f"{STOP_PREMISE}——残る仕事は全てその答えに従属する。"
                  "ここで止めて聞け（最終報告の冒頭）。")
        elif waiting and not work:
            print(f"残る阻害要因は保留の問いに帰属するものだけ（{waiting} 件）——"
                  f"{STOP_WORK_EXHAUSTED}。ここで止めて聞け（最終報告の冒頭）。")
        elif waiting:
            print(f"保留の問いに帰属する阻害要因 {waiting} 件は聞くのを待て——"
                  f"帰属しない {work} 件を先に直せ（聞くのはまだ）。")
    # 台帳に未決が残っていれば、人が決めることは残っている。**exit 0 と exit 1 の両方で言う**
    # ——「聞く時」の 3 分岐は帰属する阻害が在るときにしか通らないので、`thrash` / `split` /
    # `rule` のように出どころで手を止めない問いだけが残る周も、阻害要因が 0 の周も、台帳が
    # 黙ったまま終わっていた（同梱の雛形 3 周がまさにその形だった）。数え直しを片側にだけ
    # 置くと、同じ非対称がそのまま戻る。
    open_q = [q for q in rec["questions"] if q["status"] in ASKING]
    if open_q:
        to_human = sum(1 for q in open_q if q["status"] == "escalate")
        print(f"台帳に未決の問いが {len(open_q)} 件（うち人へ {to_human} 件）——"
              "阻害要因の有無に依らず、最終報告の冒頭に載せろ。")
    if found or accounting:
        sys.exit(1)
    print(
        "機械で見つけられる阻害要因は、今ラウンドにも前ラウンドにも無い（連続 2 ラウンド）。"
        "**これは収束の宣言ではない**——記録に載らない懸念の有無と、持ち越しが古すぎないかは人が見ろ。"
    )


if __name__ == "__main__":
    # **終了コードの契約を担保するのはここ 1 箇所**（理由は冒頭 docstring）。
    try:
        main()
    except SystemExit:
        raise
    except Exception as e:
        fail(f"想定外の例外（{type(e).__name__}）: {e}")
