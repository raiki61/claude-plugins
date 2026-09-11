#!/usr/bin/env python3
"""レビューループのラウンド記録を検証し、収束を妨げているものを列挙する。

**この道具は不合格しか宣言しない。** 「阻害なし」は収束の宣言ではなく、機械で
見つけられる阻害要因が無いという意味にすぎない。収束を宣言するのは人。

守備範囲は、明示返答を要求する欄が埋まっているか（素材・R1〜R4 の verdict）と、
前ラウンドとの突合（連続 2 ラウンド・持ち越しの連鎖・defer 台帳・残存 [block]）。
欄が空なら検証エラーで落ちる——約束を守ったかを、守ると書くのでなく確かめられる
形にするのが目的。記録に載らない懸念の有無は今も人が見る。

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
再審し、答えた・自明・まだ・人でないと決められない、に振り分ける。機械が縛るのは 3 つ——
前の周の保留（held / escalate）が黙って消えないこと、同じ [block] が 2 ラウンド連続で残ったら
台帳に載っていること、阻害要因を「保留の問いに帰属する」と「しない」に分けて、帰属しない
阻害が 0 なら「答え無しに進める仕事は無い——ここで止めて聞け」と出すこと。**人に聞く時を
writer が数えない**ための道具で、writer が「もう聞くしかない」と決める経路を塞ぐ。

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

import json
import os
import re
import sys

# Windows の既定コンソールは cp932 等で、本文の記号（—）を encode できずに落ちる。
# 落ちると終了コードが 1 になり「阻害要因あり」と区別が付かないため、収束を永久に
# 宣言できなくなる。出力を UTF-8 に固定して塞ぐ。
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8")

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
STATUS = {
    "found": ("count", "detail"),
    "clean": ("checked",),  # 今ラウンドに見たが無かった（何を見たかを要求する）
    # 前ラウンドの判定を流用した。**`clean` と分ける**——`clean` は「今回見た」で、
    # 持ち越しを `clean` に入れると最後に実際に見たラウンドが誰にも見えなくなる
    # （実例: 持ち越しを `clean` で書いた記録が 3 素材あった）。`from_round` は実際に
    # 見たラウンドで、持ち越しが続いても動かない（連鎖は下の突合で検査する）。
    "carried_over": ("from_round", "reason"),
    "not_applicable": ("reason",),
    "awaiting_human": ("reason",),  # 人の起動待ちで止まっている
    "not_run": ("reason",),  # やるべきだったが飛ばした
}

# 収束を妨げる状態。**「やらなかった」を 3 値に割ってあるのが要点**——散文だと
# awaiting_human（手順どおりの停止）と not_run（逸脱）が同じ「未実施」に潰れ、
# さらに not_applicable にまで化ける。潰すと報告上で見分けられなくなる。
BLOCKING = ("awaiting_human", "not_run")

# 持ち越しの元になれる状態。not_applicable は持ち越しでなく not_applicable と書く
# （条件に当たらないのは今ラウンドの事実で、前ラウンドの判定の流用ではない）。
CARRYABLE = ("found", "clean", "carried_over")

# P-R の俯瞰。収束条件の半分（R1〜R4 が全て pass）がここに載る。以前は「人が見る」と
# して記録の外に置いていたが、それは手順書自身が禁じる形——書いてあるだけの約束は
# writer が省略しても誰も気づかない——だった。手順書の P-R が定義する語彙に、素材と
# 同じ「やらなかった」の区別を足してある。
REVIEWS = ("R1", "R2", "R3", "R4")
REVIEW_STATUS = {
    "pass": ("reason",),
    "redesign-needed": ("reason",),
    "unverifiable": ("reason",),  # 独立に確かめられない——収束でも再設計でもなく人へ
    "premise-invalid": ("reason",),  # R2 だけ。解くべき問いが立っていない——judge が根拠を検算してから人へ
    "carried_over": ("from_round", "reason"),  # R1 / R2 だけ。再発火条件に当たらない
    "not_applicable": ("reason",),  # R3 / R4 だけ。[block] が残り P-R に到達していない
    "not_run": ("reason",),  # やるべきだったが飛ばした
}
# R1 / R2 は第 1 ラウンドで必ず走り、以降は再発火条件で回す（手順書 P4）。R3 / R4 は
# P-R でのみ走る。どちらも「条件に当たらない」の意味が違うので、値の許可を役ごとに絞る。
STATUS_ONLY_FOR = {
    "premise-invalid": ("R2",),
    "carried_over": ("R1", "R2"),
    "not_applicable": ("R3", "R4"),
}
REVIEW_BLOCKING = ("redesign-needed", "not_run")
# 収束を宣言せずユーザーに諮る値。阻害要因として数える（exit 1）が、見出しを分ける。
REVIEW_TO_HUMAN = ("unverifiable", "premise-invalid")
# 俯瞰（R1〜R4）で持ち越しの元になれる値。素材用の CARRYABLE を流用すると、found / clean は
# 俯瞰に存在しないので到達不能な条件になる。**REVIEW_TO_HUMAN を入れるな**——blockers() は
# その回の status しか見ないので、`unverifiable` を 1 度持ち越した時点で人に諮る義務が
# 阻害要因から消え、2 ラウンド目に exit 0 が出る（実測: round 1 を unverifiable、round 2・3 を
# carried_over(from_round=1) にした記録で「阻害要因は、今ラウンドにも前ラウンドにも無い」）。
# 素材側が CARRYABLE から BLOCKING を外しているのと同じ対称性。諮る義務が続く限り、
# 同じ値をそのラウンドにもう一度書けばよい（それが「今も諮っている」の正直な記録である）。
REVIEW_CARRYABLE = ("pass", "carried_over")

# nit / question / info は**意図的に**阻害要因にしない。ここを塞ぐと、受容して
# 再修正を止めるという連鎖の断ち方が使えなくなる。
LABELS = ("block", "suggest", "nit", "question", "info")

# 問いの台帳——人に聞く候補の置き場。**載せた周には聞かない**。次の周の judge が再審する
# （ラウンドごとに聞くと毎回止まる。立った周の目にだけ難しかった問いは、次の周の材料と
# 独立再導出で消える）。実測: 前回のレビューで岐路として立った 2 件——写しの範囲を絞るか・
# 記録の入口をどちらにするか——は、どちらも後の周で選択肢の外の零処方（仕掛けごと落とす・
# 片方の入口を消す）で消えた。立った周に人へ返していたら、その選択肢からは選ばれなかった。
QUESTIONS = "questions"
# 種類と、その種類で追加に要求する欄。
QUESTION_KINDS = {
    # 設計の岐路——処方が機構の新設・共有面の拡大に及び、候補が複数（手順書 P2 の 6）。
    # 選択肢は帰結まで書く。零処方（取り下げ・既存の機構 1 つ）が落ちる理由は reason に。
    "fork": ("options",),
    # 修正が露呈させた既存の欠陥で、凍結した目的の外。別 PR に積むかを人が決める。
    # 露呈の回収は既定のまま（REVIEW.md「別 Issue への先送りを既定にするな」）で、
    # これは例外の申請。目的の内側でないかは R1 が監査する。
    "split": (),
    # 同じ指摘が新証拠なく再燃し、原因がコードでなく観点の誤発火。REVIEW.md の
    # どの観点かを reason に書く。剪定するかは人（「この規約の育て方」）。
    "rule": (),
    # 同じ [block] が 2 ラウンド連続で残った（3 ラウンドの記録に続けて在る）。処方の誤りか
    # 設計の問題か——下の main() が台帳への記載を要求する。
    "stuck": (),
    # 新規 [block] が出続けて収束に向かわない。アプローチの誤りか。件数が落ちれば resolved。
    "thrash": (),
    # R2 が premise-invalid。blind-judge は道具を持たないので、根拠に目的テキストの外の仮定が
    # 混じる——別 context の judge が仮定を実態で検算したかが再審の中身。
    "premise": (),
    # 元の目的を独立に取れない（R が unverifiable）。
    "unverifiable": (),
    # 素材が awaiting_human（未観測・打ち切られた一覧・洗えなかった決定記録・走らせられない CI）。
    # 「打ち切られた」は上限を上げれば済むことが多く、人に聞く前に再審で消える。
    "awaiting": (),
}
QUESTION_STATUS = {
    "held": (),  # 保留——次の周の judge が再審する
    # ループが決めた——答えた材料か、決める規律（零処方が落ちない／目的の内側／実測で優越）を
    # 要求する。最終報告に「ループが自分で決めたこと」として並び、人が覆せる。
    "resolved": ("resolution",),
    "escalate": (),  # 再審の結果、人でないと決められない（好み・方針・可逆性の低い合意・目的の書き換え）
}
# 問いの出どころ。阻害要因の帰属（blockers）はここから引く。
ORIGIN_UNIT = ("fork", "split", "rule", "stuck")  # origin は units の key
ORIGIN_MATERIAL = ("awaiting",)  # origin は素材名
ORIGIN_REVIEW = ("premise", "unverifiable")  # origin は R1〜R4
# split / rule は [block] と do-now のユニットに付けられない——人に聞く前に直す義務が消えると
# 逃げ道になる。fork / stuck は [block] に付く。**問いは阻害要因を消さない**——当のユニットは
# [block] のまま阻害要因に数え、「保留の問いに帰属」の印が付くだけ。答えが出るまで収束しない。
NO_OPEN_ORIGIN = ("split", "rule")
ASKING = ("held", "escalate")


def fail(msg):
    print(f"記録が不正: {msg}", file=sys.stderr)
    sys.exit(2)


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


def validate_carry(entry, rec, path, what):
    fr = entry.get("from_round")
    if not is_int(fr) or fr < 1:
        fail(f"{path}: {what} の from_round が 1 以上の整数でない: {fr!r}")
    if fr >= rec["round"]:
        fail(f"{path}: {what} の from_round（{fr}）が今ラウンド（{rec['round']}）より前でない")


def validate(rec, path, hint=None):
    # 型を見るのは診断メッセージを具体的にするため（保証は末尾の境界。冒頭 docstring 参照）。
    if not isinstance(rec, dict):
        fail(f"{path}: 記録の最上位が object でない")
    for key in ("base", "round", "materials", "units", "reviews", QUESTIONS):
        if key not in rec:
            fail(
                f"{path}: 必須の欄 '{key}' が無い"
                + ("（0.28 で足した問いの台帳。人に聞く候補が無いなら空の配列を書け）" if key == QUESTIONS else "")
                + (f"。{hint}" if hint else "")
            )
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
    if not isinstance(rec[QUESTIONS], list):
        fail(f"{path}: 'questions' が配列でない（人に聞く候補が無いなら空の配列）")

    for name in MATERIALS:
        m = rec["materials"].get(name)
        if not isinstance(m, dict):
            fail(f"{path}: 素材 '{name}' の返答が無い（明示返答は全素材に要る）")
        status = m.get("status")
        if status not in STATUS:
            fail(
                f"{path}: 素材 '{name}' の status が不正: {status!r}（{'/'.join(STATUS)}）"
            )
        for field in STATUS[status]:
            # `not m.get(...)` だと 0 や "" を欠落と同じ扱いにし、入れてある欄について
            # 「要る」と嘘の診断を出す。欠落と空を分けて、writer が探す先を間違えないようにする。
            if field not in m:
                fail(f"{path}: 素材 '{name}' は status={status} なので '{field}' が要る")
            if m[field] == "" or m[field] is None:
                fail(f"{path}: 素材 '{name}' の '{field}' が空（何を見たかを書け）")
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
        allowed = STATUS_ONLY_FOR.get(status)
        if allowed and name not in allowed:
            fail(
                f"{path}: {name} は {status} にできない（許されるのは {'/'.join(allowed)}）"
            )
        for field in REVIEW_STATUS[status]:
            # 素材側と同じ形にする。`not r.get(...)` だと from_round: 0 が「欄が無い」という
            # 嘘の診断になり、writer が探す先を間違える。
            if field not in r:
                fail(f"{path}: {name} は status={status} なので '{field}' が要る")
            if r[field] == "" or r[field] is None:
                fail(f"{path}: {name} の '{field}' が空（何を見たかを書け）")
        if status == "carried_over":
            validate_carry(r, rec, path, name)

    seen_keys = {}
    for i, u in enumerate(rec["units"]):
        if not isinstance(u, dict):
            fail(f"{path}: units[{i}] が object でない")
        if not u.get("key"):
            fail(f"{path}: units[{i}] に key が無い（ラウンド間の突合に使う）")
        # key は突合と台帳の識別子なので、同じラウンドに 2 つ在ると履歴も台帳も
        # 後勝ちで潰れる（重い方が消え、受容していないものが受容扱いになる）。
        if u["key"] in seen_keys:
            fail(
                f"{path}: units[{i}] の key が units[{seen_keys[u['key']]}] と同じ: "
                f"{u['key']}（突合の識別子なので 1 ラウンドに 1 つ）"
            )
        seen_keys[u["key"]] = i
        if u.get("label") not in LABELS:
            fail(f"{path}: units[{i}] の label が不正: {u.get('label')!r}")
        if u["label"] == "suggest":
            if u.get("disposition") not in ("do-now", "defer"):
                fail(f"{path}: units[{i}] は suggest なので disposition が要る")
            if u["disposition"] == "defer" and not u.get("reason"):
                fail(f"{path}: units[{i}] の defer に構造的理由が無い")
        # 0.27 までの印。台帳に移した——ユニットに付いた印は再審の跡を持てず、消えたことも
        # 誰にも見えなかった。
        if "ask_human" in u:
            fail(
                f"{path}: units[{i}] に ask_human が在る——人に聞く候補は questions（問いの台帳）に"
                f" kind={u['ask_human']} / origin=このユニットの key で載せろ"
            )

    validate_questions(rec, path, seen_keys)


def validate_questions(rec, path, unit_index):
    """問いの台帳の 1 ラウンド内の整合。出どころが今ラウンドの記録に実在し、人の起動待ちの
    素材・人に諮る verdict は必ず台帳に載っている（聞く候補が散文にだけ在って、台帳を
    見た人が「無い」と読む形を塞ぐ）。"""
    seen = set()
    for i, q in enumerate(rec[QUESTIONS]):
        where = f"{path}: questions[{i}]"
        if not isinstance(q, dict):
            fail(f"{where} が object でない")
        if not q.get("key"):
            fail(f"{where} に key が無い（周をまたぐ突合に使う。何を決めるかを一文で）")
        if q["key"] in seen:
            fail(f"{where} の key が重複: {q['key']}（突合の識別子なので 1 ラウンドに 1 つ）")
        seen.add(q["key"])
        kind = q.get("kind")
        if kind not in QUESTION_KINDS:
            fail(f"{where} の kind が不正: {kind!r}（{'/'.join(QUESTION_KINDS)}）")
        status = q.get("status")
        if status not in QUESTION_STATUS:
            fail(f"{where} の status が不正: {status!r}（{'/'.join(QUESTION_STATUS)}）")
        for field in ("reason",) + QUESTION_KINDS[kind] + QUESTION_STATUS[status]:
            if field not in q:
                fail(f"{where} は kind={kind} / status={status} なので '{field}' が要る")
            if q[field] in ("", None, []):
                fail(f"{where} の '{field}' が空（きっかけ・根拠を書け）")
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
        if kind in ORIGIN_UNIT:
            if not origin:
                fail(f"{where} は kind={kind} なので origin（units の key）が要る")
            # origin の実在は defer 台帳込みで見るので main() 側（question_origins_exist）。
            if (
                status in ASKING
                and kind in NO_OPEN_ORIGIN
                and origin in unit_index
                and is_open(rec["units"][unit_index[origin]])
            ):
                fail(
                    f"{where}: {kind} の origin が [block] / do-now: {origin}"
                    "（人に聞く前に直す義務が消える。defer か nit に落として理由を書け）"
                )
        elif kind in ORIGIN_MATERIAL:
            if origin not in MATERIALS:
                fail(f"{where} は kind={kind} なので origin は素材名: {origin!r}")
            if status in ASKING and rec["materials"][origin]["status"] != "awaiting_human":
                fail(
                    f"{where}: awaiting の origin '{origin}' が awaiting_human でない"
                    "（動かせた・確かめられたなら resolved にして根拠を書け）"
                )
        elif kind in ORIGIN_REVIEW:
            if origin not in REVIEWS:
                fail(f"{where} は kind={kind} なので origin は R1〜R4: {origin!r}")
            want = "premise-invalid" if kind == "premise" else "unverifiable"
            if status in ASKING and rec["reviews"][origin]["status"] != want:
                fail(f"{where}: {kind} の origin {origin} が {want} でない（解けたなら resolved にしろ）")
    # 逆向き。人の起動待ちの素材と人に諮る verdict は、台帳に問いとして載っていること——
    # 載っていないと「聞く時」の判定（帰属）に乗らず、聞かれないまま暴走ガードまで回る。
    origins = {(q["kind"], q.get("origin")) for q in rec[QUESTIONS]}
    for name in MATERIALS:
        if rec["materials"][name]["status"] == "awaiting_human" and ("awaiting", name) not in origins:
            fail(
                f"{path}: 素材 '{name}' が awaiting_human なのに問いの台帳に無い"
                "（何を誰に聞くかを questions に kind=awaiting で書け。再審で消えることが多い）"
            )
    for name in REVIEWS:
        st = rec["reviews"][name]["status"]
        if st in REVIEW_TO_HUMAN:
            kind = "premise" if st == "premise-invalid" else "unverifiable"
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
            "2 つの記録の base が違う（基準点を動かすな）。"
            "別のレビューの記録が同じディレクトリに混ざっていないか——"
            "混ざっているなら消さずに別ディレクトリへ退避してから始めろ"
        )
    # 持ち越しの連鎖。from_round は「実際に見たラウンド」なので、前ラウンドも持ち越し
    # なら同じ値、前ラウンドで実際に見たなら前ラウンドの番号。未実施・条件外からは
    # 持ち越せない（持ち越しは判定の流用であって、無かった判定は流用できない）。
    for what, now, before in (
        *((f"素材 '{n}'", rec["materials"][n], prev["materials"][n]) for n in MATERIALS),
        *((n, rec["reviews"][n], prev["reviews"][n]) for n in REVIEWS),
    ):
        if now["status"] != "carried_over":
            continue
        ps = before["status"]
        if ps == "carried_over":
            if now["from_round"] != before["from_round"]:
                fail(
                    f"{what} の持ち越しが連鎖していない: 前ラウンドは round "
                    f"{before['from_round']} から、今ラウンドは round {now['from_round']} から"
                )
        elif ps in (REVIEW_CARRYABLE if what in REVIEWS else CARRYABLE):
            if now["from_round"] != prev["round"]:
                fail(
                    f"{what} の from_round（{now['from_round']}）が前ラウンド"
                    f"（{prev['round']}）でない——前ラウンドは実際に見ている"
                )
        else:
            fail(f"{what} は前ラウンドが {ps} なので持ち越せない（判定が無い）")

    # defer 台帳。**前ラウンドまでに** defer と確定したキーが再び [block] / do-now に
    # 上がるのは、新しい根拠が付いたときだけ（手順書 P4）。根拠の欄が無い再出現は、judge が
    # 台帳を渡されていないか無視したかで、記録を直して（judge を台帳つきで回して）出し直す。
    # carried は「それより前のラウンドまでの台帳」。隣の 1 ラウンドだけを見ると、
    # 1 ラウンド記録から落とすだけで再審の縛りが外れる（受容済みの論点が新証拠なしに戻る）。
    ledger = dict(carried or {})
    ledger.update({
        u["key"]: u.get("reason")
        for u in prev["units"]
        if u["label"] == "suggest" and u.get("disposition") == "defer"
    })
    for u in rec["units"]:
        if u["key"] in ledger and is_open(u) and not u.get("reopen_evidence"):
            fail(
                f"既受容（defer）のキーが再び {u['label']} になったが reopen_evidence が無い: "
                f"{u['key']}（前ラウンドの defer 理由: {ledger[u['key']]}）"
            )

    # 問いの台帳の連続性。前ラウンドで保留（held / escalate）だった問いは、今ラウンドにも
    # 載っていなければならない——held のまま・resolved・escalate のどれか。黙って落ちるのは
    # 「消えた [block]」と同じ形で、聞くはずだった問いが誰にも聞かれずに終わる。
    now_q = {q["key"] for q in rec[QUESTIONS]}
    for q in prev[QUESTIONS]:
        if q["status"] in ASKING and q["key"] not in now_q:
            fail(
                f"前ラウンドの問い（{q['status']}）が今ラウンドの台帳に無い: {q['key']}"
                "（再審して held / resolved / escalate のどれかで書け。黙って落とすな）"
            )
    return ledger


def question_origins_exist(rec, ledger):
    """保留中の問いの出どころ（units の key）が、今ラウンドの units か defer 台帳に在ること。
    defer は受容が続く限り記録から落ちてよい（台帳が持つ）ので、units だけを見ると
    正当な記録を弾く。どちらにも無ければ、欠陥は直ったのに問いだけが生き残っている。"""
    here = {u["key"] for u in rec["units"]}
    for i, q in enumerate(rec[QUESTIONS]):
        if q["kind"] in ORIGIN_UNIT and q["status"] in ASKING and q["origin"] not in here | set(ledger):
            fail(
                f"round {rec['round']}: questions[{i}] の origin が今ラウンドの units にも defer 台帳にも無い: "
                f"{q['origin']}（直ったなら resolved にして根拠を書け）"
            )


def blockers(rec, prev=None, ledger=None, prev_blocks=None):
    """今ラウンドの阻害要因を (本文, 帰属) の組で返す。帰属は、その阻害要因が保留中の問い
    （held / escalate の origin か depends）に帰属するか——帰属する阻害は「答えを待っている」、
    帰属しない阻害は「まだ仕事が在る」。人に聞く時はこの 2 つの数で決まり、writer は数えない。
    prev を渡すと **[block] の行に** 過去ラウンド比の注記（新規 / 残存）を、台帳に在るキーには
    （既受容の再審）を添える。判定そのものは prev に依存しない。prev_blocks を渡すとそれを
    「過去に [block] だったキー」として使う（渡さなければ prev の 1 ラウンド分。ディレクトリ
    渡しでは全ラウンドの和）。"""
    out = []
    ledger = ledger or {}
    asked = set()
    for q in rec[QUESTIONS]:
        if q["status"] in ASKING:
            asked.add(q.get("origin"))
            asked.update(q.get("depends", ()))
    if prev_blocks is None:
        prev_blocks = (
            {u["key"] for u in prev["units"] if u["label"] == "block"} if prev else set()
        )

    for name in MATERIALS:
        m = rec["materials"][name]
        if m["status"] in BLOCKING:
            label = "人の起動待ち" if m["status"] == "awaiting_human" else "未実施"
            out.append((f"素材 '{name}' が{label}: {m['reason']}", name in asked))

    # 「見つけた」と書いた素材が 1 つでも在るのに units が空なら、judge が根本ユニットに
    # 落としていないか、落とした結果が記録に載っていない。中身は解釈しないが、
    # 「正直に見つけたと書いたのに 1 件も挙げていない」という形だけは数えられる。
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
        out.append((f"{head}{note}: {u['key']}", u["key"] in asked))

    for name in REVIEWS:
        r = rec["reviews"][name]
        if r["status"] in REVIEW_BLOCKING:
            out.append((f"{name} が {r['status']}: {r['reason']}", False))
        elif r["status"] in REVIEW_TO_HUMAN:
            out.append((
                f"{name} が {r['status']}（収束を宣言せずユーザーに諮れ）: {r['reason']}",
                name in asked,
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
        listed = {q.get("origin") for q in rounds[i][QUESTIONS]}
        out.extend((rounds[i]["round"], k) for k in sorted(chain - listed))
    return out


def carry_summary(rec):
    """持ち越しの一覧。機械は中身を見ないので、何ラウンド前の判定かを見せるだけ。"""
    out = []
    for what, entries in (("素材", rec["materials"]), ("俯瞰", rec["reviews"])):
        for name in MATERIALS if what == "素材" else REVIEWS:
            e = entries[name]
            if e["status"] == "carried_over":
                age = rec["round"] - e["from_round"]
                out.append(f"{what} {name}: round {e['from_round']} の判定を流用（{age} ラウンド前）")
    return out


def scalar_changes(rec, prev):
    """前ラウンド比で増えた scalar。**相殺の有無は判定せず、R1 へ渡すだけ。**

    これを阻害要因に混ぜないこと——測れるものをゲートにすると、規則が測れるものへ
    寄る。増分の正当化を求める相手は人（R1）であって、この道具ではない。
    """
    if prev is None:
        return []
    out = []
    for name, now in (rec.get("scalars") or {}).items():
        before = (prev.get("scalars") or {}).get(name)
        if (
            isinstance(before, (int, float))
            and isinstance(now, (int, float))
            and now > before
        ):
            out.append(f"scalar '{name}': {before} → {now}")
    return out


def load_dir(path):
    """`round-<N>.json` を番号順に全部読む。連番の穴は記録の不正（消したか、番号を飛ばした）。"""
    found = {}
    for name in sorted(os.listdir(path)):
        m = re.fullmatch(r"round-(\d+)\.json", name)
        if m:
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
        seq = " → ".join(
            f"r{r}:{by_round[r]}" if r in by_round else f"r{r}:—" for r in range(1, n + 1)
        )
        seen = [r in by_round for r in range(1, n + 1)]
        gaps = reappeared_after_gap(seen)
        note = f"（消えて {gaps} 回戻った）" if gaps else ""
        out.append(f"{key}\n      {seq}{note}")
    qkeys = {}
    for rec in rounds:
        for q in rec[QUESTIONS]:
            qkeys.setdefault(q["key"], {})[rec["round"]] = f"{q['status']}({q['kind']})"
    for key, by_round in qkeys.items():
        seq = " → ".join(
            f"r{r}:{by_round[r]}" if r in by_round else f"r{r}:—" for r in range(1, n + 1)
        )
        out.append(f"問い: {key}\n      {seq}")
    open_counts = [sum(1 for u in r["units"] if is_open(u)) for r in rounds]
    out.append("要対応（[block]＋do-now）の件数: " + " → ".join(map(str, open_counts)))
    if qkeys:
        out.append("問いの台帳の件数（保留・人へ・ループが決めた）: " + " → ".join(
            "・".join(
                str(sum(1 for q in r[QUESTIONS] if q["status"] == s))
                for s in ("held", "escalate", "resolved")
            )
            for r in rounds
        ))
    for name in sorted({k for r in rounds for k in (r.get("scalars") or {})}):
        vals = [(r.get("scalars") or {}).get(name) for r in rounds]
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

    for n, k in stuck_unlisted(rounds):
        fail(
            f"round {n}: 同じ [block] が 3 ラウンドの記録に続けて在る（2 ラウンド連続の残存＝stuck）のに"
            f"問いの台帳に無い: {k}（処方の誤りか設計の問題かを judge に振り分けさせ、stuck か fork として載せろ）"
        )

    if rec[QUESTIONS]:
        print("問いの台帳（人に聞く候補。載せた周には聞かない——次の周の judge が再審する。"
              "目的の内側でないかは R1 が監査）:")
        for q in rec[QUESTIONS]:
            tag = {"held": "保留", "escalate": "人へ", "resolved": "ループが決めた"}[q["status"]]
            tail = q["resolution"] if q["status"] == "resolved" else q["reason"]
            print(f"  - [{tag}] {q['kind']}: {q['key']} — {tail}")

    if rounds:
        lines = history(rounds)
        if lines:
            print(f"履歴（round 1〜{rec['round']}。P2 の judge に渡せ。機械は解釈しない）:")
            for line in lines:
                print(f"  - {line}")

    prev_blocks = None
    if rounds is not None:
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
        # 理由の 2 通りの検討は手順書 P2 の 8 が持つ。ここに写すと片方が腐る）。
        gone = [k for k in sorted(prev_blocks or ()) if k not in here]
        if gone:
            print("過去のラウンドの [block] で今ラウンドの記録に無いキー"
                  "（直ったのか、記録から落ちたのかは機械には見えない。P2 の 8 でルーターに掛けろ）:")
            for k in gone:
                print(f"  - {k}")

    # 連続 2 ラウンド。今ラウンドが阻害なしでも、前ラウンドに阻害があれば 1 ラウンド目。
    # **これを writer に数えさせない**——採点を自己申告にしないのと同じ理由。
    # 帰属は None——保留の問いへの帰属でも、仕事でもない（回せば消える）。
    if prev is None:
        found.append(("前ラウンドの記録が無い（連続 2 ラウンドの 1 ラウンド目。収束は次ラウンド以降）", None))
    else:
        prev_found = blockers(prev)
        if prev_found:
            found.append((
                f"前ラウンドに阻害要因が {len(prev_found)} 件あった"
                "（連続 2 ラウンドの 1 ラウンド目。今ラウンドが阻害なしでも収束は次ラウンド）",
                None,
            ))

    if found:
        print(f"収束を妨げるもの {len(found)} 件:")
        for msg, asked in found:
            print(f"  - {msg}" + ("（保留の問いに帰属——答えを待っている）" if asked else ""))
        # 人に聞く時。**writer が数えるな**——聞くのが早すぎると、次の周の目が解けた問いで
        # 人を止める。遅すぎることは無い（帰属しない阻害が 0 になった瞬間に出る）。
        work = [m for m, a in found if a is False]
        waiting = [m for m, a in found if a is True]
        if any(q["kind"] == "premise" and q["status"] == "escalate" for q in rec[QUESTIONS]):
            print("前提不成立が再審で確定——残る仕事は全てその答えに従属する。"
                  "ここで止めて聞け（最終報告の冒頭）。")
        elif waiting and not work:
            print(f"残る阻害要因は保留の問いに帰属するものだけ（{len(waiting)} 件）——"
                  "答え無しに進める仕事は無い。ここで止めて聞け（最終報告の冒頭）。")
        elif waiting:
            print(f"保留の問いに帰属する阻害要因 {len(waiting)} 件は聞くのを待て——"
                  f"帰属しない {len(work)} 件を先に直せ（聞くのはまだ）。")
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
