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
    python3 review-record.py <今ラウンドの記録.json> [<前ラウンドの記録.json>]

ディレクトリを渡すと `round-<N>.json` を全部読み、最新を今ラウンドとして検証・突合した
うえで、**全ラウンドの履歴**（キーごとの判定の推移・直したのに再出現した回数・
`ask_human` の推移・scalar の推移）を出す。履歴は P2 の judge に渡す入力で、人には最終
報告の冒頭で見せる——同じ指摘が毎回来る理由（コードか・レビュアーか・規約か）も、
露呈の回収で目的の外へ膨らんでいることも、数周して初めて見える傾向で、隣のラウンドと
だけ比べる形では誰にも見えなかった。

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
    "found": ("count", "detail"),  # 見つかった
    "clean": ("checked",),  # 今ラウンドに見たが無かった（何を見たかを要求する）
    # 前ラウンドの判定を流用した。**`clean` と分ける**——`clean` は「今回見た」で、
    # 持ち越しを `clean` に入れると最後に実際に見たラウンドが誰にも見えなくなる
    # （実例: 持ち越しを `clean` で書いた記録が 3 素材あった）。`from_round` は実際に
    # 見たラウンドで、持ち越しが続いても動かない（連鎖は下の突合で検査する）。
    "carried_over": ("from_round", "reason"),
    "not_applicable": ("reason",),  # 条件に当たらない
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
    "premise-invalid": ("reason",),  # R2 だけ。解くべき問いが立っていない——即ユーザーへ
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

# nit / question / info は**意図的に**阻害要因にしない。ここを塞ぐと、受容して
# 再修正を止めるという連鎖の断ち方が使えなくなる。
LABELS = ("block", "suggest", "nit", "question", "info")

# judge が「コードを直す」以外の出口を要るときに付ける印。ループは止めず、履歴に溜めて
# 最終報告の冒頭で人にまとめて聞く（ラウンドごとに聞くと毎回止まる。数周して judge が
# 引き戻せば自然に消える）。
#   split — 修正が露呈させた既存の欠陥で、凍結した目的の外。別 PR に積むかを人が決める。
#           露呈の回収は既定のまま（REVIEW.md「別 Issue への先送りを既定にするな」）で、
#           これは例外の申請。目的の内側でないかは R1 が監査する。
#   rule  — 同じ指摘が新証拠なく再燃し、原因がコードでなく観点の誤発火。REVIEW.md の
#           どの観点かを reason に書く。剪定するかは人（「この規約の育て方」）。
# **[block] と do-now には付けられない**——人に聞く前に直す義務が消えると逃げ道になる。
# 付けるなら defer か nit / question / info に落とし、理由を書け。
ASK_HUMAN = ("split", "rule")


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
    """持ち越しの from_round が、今ラウンドより前の実在しうるラウンドを指すか。"""
    fr = entry.get("from_round")
    if not is_int(fr) or fr < 1:
        fail(f"{path}: {what} の from_round が 1 以上の整数でない: {fr!r}")
    if fr >= rec["round"]:
        fail(f"{path}: {what} の from_round（{fr}）が今ラウンド（{rec['round']}）より前でない")


def validate(rec, path, hint=None):
    # 型を見るのは診断メッセージを具体的にするため（保証は末尾の境界。冒頭 docstring 参照）。
    if not isinstance(rec, dict):
        fail(f"{path}: 記録の最上位が object でない")
    for key in ("base", "round", "materials", "units", "reviews"):
        if key not in rec:
            fail(f"{path}: 必須の欄 '{key}' が無い" + (f"。{hint}" if hint else ""))
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
            if not m.get(field):
                fail(
                    f"{path}: 素材 '{name}' は status={status} なので '{field}' が要る"
                )
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
            if not r.get(field):
                fail(f"{path}: {name} は status={status} なので '{field}' が要る")
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
        ask = u.get("ask_human")
        if ask is not None:
            if ask not in ASK_HUMAN:
                fail(f"{path}: units[{i}] の ask_human が不正: {ask!r}（{'/'.join(ASK_HUMAN)}）")
            if is_open(u):
                fail(
                    f"{path}: units[{i}] は {u['label']}"
                    f"{'/do-now' if u['label'] == 'suggest' else ''} なので ask_human を付けられない"
                    "（人に聞く前に直す義務が消える。defer か nit に落として理由を書け）"
                )
            if not u.get("reason"):
                fail(f"{path}: units[{i}] の ask_human={ask} に reason が無い")


def is_open(u):
    """まだ手を付けるべきユニット（[block] か do-now）。"""
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
    if rec["round"] != prev["round"] + 1:
        fail(f"ラウンドが連番でない: {prev['round']} の次が {rec['round']}")

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
        elif ps in CARRYABLE or (what in REVIEWS and ps == "pass"):
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
    return ledger


def blockers(rec, prev=None, ledger=None, prev_blocks=None):
    """今ラウンドの阻害要因。prev を渡すと **[block] の行に** 過去ラウンド比の注記
    （新規 / 残存）を、台帳に在るキーには（既受容の再審）を添える。判定そのものは
    prev に依存しない。prev_blocks を渡すとそれを「過去に [block] だったキー」として
    使う（渡さなければ prev の 1 ラウンド分。ディレクトリ渡しでは全ラウンドの和）。"""
    out = []
    ledger = ledger or {}
    if prev_blocks is None:
        prev_blocks = (
            {u["key"] for u in prev["units"] if u["label"] == "block"} if prev else set()
        )

    for name in MATERIALS:
        m = rec["materials"][name]
        if m["status"] in BLOCKING:
            label = "人の起動待ち" if m["status"] == "awaiting_human" else "未実施"
            out.append(f"素材 '{name}' が{label}: {m['reason']}")

    # 「見つけた」と書いた素材が 1 つでも在るのに units が空なら、judge が根本ユニットに
    # 落としていないか、落とした結果が記録に載っていない。中身は解釈しないが、
    # 「正直に見つけたと書いたのに 1 件も挙げていない」という形だけは数えられる。
    if not rec["units"]:
        got = [n for n in MATERIALS if rec["materials"][n]["status"] == "found"]
        if got:
            out.append(
                f"素材が found なのに units が空: {', '.join(got)}"
                "（見つけたものを根本ユニットに落としたか確かめろ）"
            )

    for u in rec["units"]:
        if not is_open(u):
            continue
        head = "[block] 未解消" if u["label"] == "block" else "[suggest] do-now 未対応"
        note = ""
        if prev is not None:
            if u["key"] in ledger:
                note = f"（既受容 defer の再審。新証拠: {u['reopen_evidence']}）"
            elif u["label"] == "block" and u["key"] in prev_blocks:
                note = "（残存——過去のラウンドにも在った。stuck の疑い）"
            elif u["label"] == "block":
                note = "（新規）"
        out.append(f"{head}{note}: {u['key']}")

    for name in REVIEWS:
        r = rec["reviews"][name]
        if r["status"] in REVIEW_BLOCKING:
            out.append(f"{name} が {r['status']}: {r['reason']}")
        elif r["status"] in REVIEW_TO_HUMAN:
            out.append(f"{name} が {r['status']}（収束を宣言せずユーザーに諮れ）: {r['reason']}")

    # R3 / R4 の not_applicable は「P-R に到達していない」の意味なので、到達を妨げる
    # 阻害要因が他に無いなら、P-R を飛ばしたことになる。
    if not out:
        for name in REVIEWS:
            r = rec["reviews"][name]
            if r["status"] == "not_applicable":
                out.append(
                    f"{name} が not_applicable だが、P-R への到達を妨げる阻害要因が記録に無い"
                    f"（[block] 0・素材の未実施 0 なら P-R を実行しろ）: {r['reason']}"
                )
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
    import os
    import re

    found = {}
    for name in sorted(os.listdir(path)):
        m = re.fullmatch(r"round-(\d+)\.json", name)
        if m:
            n = int(m.group(1))
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
            if u.get("ask_human"):
                state += f" ask:{u['ask_human']}"
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
    open_counts = [sum(1 for u in r["units"] if is_open(u)) for r in rounds]
    ask_counts = [sum(1 for u in r["units"] if u.get("ask_human")) for r in rounds]
    out.append("要対応（[block]＋do-now）の件数: " + " → ".join(map(str, open_counts)))
    if any(ask_counts):
        out.append("人に聞く印（split / rule）の件数: " + " → ".join(map(str, ask_counts)))
    for name in sorted({k for r in rounds for k in (r.get("scalars") or {})}):
        vals = [(r.get("scalars") or {}).get(name) for r in rounds]
        out.append(f"scalar '{name}': " + " → ".join("—" if v is None else str(v) for v in vals))
    return out


def main():
    if not 2 <= len(sys.argv) <= 3:
        print(__doc__, file=sys.stderr)
        fail(f"引数は 1 個か 2 個（受け取った数: {len(sys.argv) - 1}）")

    import os

    rounds = None
    if len(sys.argv) == 2 and os.path.isdir(sys.argv[1]):
        rounds = load_dir(sys.argv[1])
        rec = rounds[-1]
        prev = rounds[-2] if len(rounds) > 1 else None
        ledger = {}
        # 連鎖と台帳は隣り合う全ての組で突合する（履歴の途中で壊れていても最新だけ見ると通る）。
        # 台帳は**代入でなく累積**する。組ごとに置き換えると隣の 1 ラウンドしか残らず、
        # 1 ラウンド記録から落とすだけで再審の縛りが消える（手順書は全ラウンドの和と書いている）。
        for a, b in zip(rounds, rounds[1:]):
            ledger = validate_against(b, a, ledger)
    else:
        rec = load(sys.argv[1])
        # **突合より先に両方を検証する。** 逆順にすると、欄が欠けた記録で比較が KeyError を
        # 投げ、境界が 2 に倒すとはいえ「必須の欄が無い」より読みにくいメッセージになる。
        validate(rec, sys.argv[1])

        prev = None
        ledger = {}
        if len(sys.argv) > 2:
            prev = load(sys.argv[2])
            validate(prev, sys.argv[2])
            ledger = validate_against(rec, prev)

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

    asks = [u for u in rec["units"] if u.get("ask_human")]
    if asks:
        print("人に聞く印（ループは止めない。最終報告の冒頭にまとめろ。目的の内側でないかは R1 が監査）:")
        for u in asks:
            print(f"  - {u['ask_human']}: {u['key']} — {u['reason']}")

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
        dropped = [k for k in ledger if k not in {u["key"] for u in rec["units"]}]
        if dropped:
            print("前ラウンドの defer で今ラウンドの記録に無いキー（台帳には残る。最終報告に載せろ）:")
            for k in dropped:
                print(f"  - {k}")

    # 連続 2 ラウンド。今ラウンドが阻害なしでも、前ラウンドに阻害があれば 1 ラウンド目。
    # **これを writer に数えさせない**——採点を自己申告にしないのと同じ理由。
    if prev is None:
        found.append("前ラウンドの記録が無い（連続 2 ラウンドの 1 ラウンド目。収束は次ラウンド以降）")
    else:
        prev_found = blockers(prev)
        if prev_found:
            found.append(
                f"前ラウンドに阻害要因が {len(prev_found)} 件あった"
                "（連続 2 ラウンドの 1 ラウンド目。今ラウンドが阻害なしでも収束は次ラウンド）"
            )

    if found:
        print(f"収束を妨げるもの {len(found)} 件:")
        for b in found:
            print(f"  - {b}")
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
