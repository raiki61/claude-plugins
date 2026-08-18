#!/usr/bin/env python3
"""初読ループの周の記録を検証し、収束を妨げているものを列挙する。

**この道具は不合格しか宣言しない。** 「阻害なし」は収束の宣言ではなく、機械で
見つけられる阻害要因が無いという意味にすぎない。収束を宣言するのは人。

守備範囲は、読み役から集めた 7 種の明示返答と、周をまたいで残った詰まりの突合だけ。
**詰まりの中身が正しく分類されたかは見ない**——そちらは今も人が見る。

使い方:
    python3 firstread-record.py <今の周の記録.json> [<前の周の記録.json>]

初回（round=1）は前の周の記録が無いので第 2 引数を省略しろ。省略すると「前の周の
記録が無い」が阻害要因として 1 件返る。**1 人が詰まらなかったことは誰も詰まらない
証拠にならない**ので、初回が阻害なしになることはない。

終了コード:
    0  阻害要因なし（収束の宣言ではない）
    1  阻害要因あり
    2  記録が不正（欄の欠落・値の不正・読めない・引数が違う）——1 と取り違えるな

**1 は「記録は読めたが収束を妨げるものがある」だけに使う。** 読めなかった・引数が
違ったといった計測不成立を 1 に混ぜると、非収束と区別が付かず、記録を直せば済む
状態が「まだ直っていない」と読まれて収束を永久に宣言できない。Python の未処理例外は
exit 1 なので、**例外を素通しした時点でこの契約は破れる。**

**この契約を担保するのは末尾の例外境界 1 つだけ。** 個々の型検査は診断メッセージを
具体的にするために在るのであって、契約の保証ではない。検査を足すときは境界に頼れ。

検証を JSON Schema で宣言せず手書きにしてあるのは、検証の半分が周をまたぐ突合
（`target` 一致・`round` 連番・同じ key の残存・行数の増減）で**単一ドキュメントに
閉じないため**と、`jsonschema` の導入が README の「必須は git / python3 / bash だけ」と
衝突するため。姉妹の記録器と同じ判断。

## この道具が固有に見るもの

**範囲の外へ倒したものに行き先を要求する。** 読み役はリポジトリ全体を探すので、詰まりも全体
から出る。今回の変更が作ったのではない詰まりまで直すと変更が際限なく膨らむので範囲外に置ける
ようにしてあるが、**範囲外は捨て場になりうる**——「対象外」と書けば何でも避けられる。行き先
（issue・台帳・次のブランチ）を欄として要求して、書かずに落とせなくする。範囲外の詰まりは
次の周でもまた出るので、**収束の判定からは外す**。直していないものがまた出るのは当然で、
直し方が効いていない証拠ではない。

**「足す側にしか倒れていないか」を測る。** 詰まりの直し方は「説明を足す」に偏りやすく、
周を重ねるほど文書が膨らみ、膨らみ自体が次の周の詰まりになる。行数が増え続けて削除も
移動も 1 件も無い状態を検出して報告する。**ただし阻害要因にはしない**——測れるものを
ゲートにすると、直し方が測れるものへ寄る。増減の正当化を求める相手は人であって
この道具ではない。

**叩かせていない直しを記録に書けなくする。** 集める側（読み役）には検証の機構が積んで
あるのに、直す側は回し手 1 人の無検証だった——直した本人はその直しの良さを判定できない
のに（読みと同じ原理）。直しごとに置き場の根拠と検証役の判定を欄で要求し、「通す」以外の
判定で当てたなら理由（押し切りか、代案への作り直しか）を書かせる。依頼者の指定で税を
省いたなら「省略（依頼者の指定）」と申告させる。**導線の引き金（構造を疑う 4 つ）も毎周の欄にする**——見て
いない引き金は「立っていない」と記録の上で区別が付かないため。どちらも詰まりと同じ規律を
直しの側へ通しただけである。
"""

import json
import os
import sys

# Windows の既定コンソールは cp932 等で、本文の記号（—）を encode できずに落ちる。
# 落ちると終了コードが 1 になり「阻害要因あり」と区別が付かないため、収束を永久に
# 宣言できなくなる。出力を UTF-8 に固定して塞ぐ。
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8")

# 詰まり。**範囲の内外を割り振るのはこの 4 つだけ**——疑問・着想・読み飛ばしは
# 「今回の変更が作ったか」で切れる性質のものではない。
STUCK = ("stopped", "guessed", "misunderstood", "unreachable")

# 読み役から集める素材。ここが正本で、手順書は列挙を持たない。
# **後半 3 つ（疑問・着想・読み飛ばし）を欄として要求するのが要点**——これらは
# 読み役が黙っていても「詰まりゼロ」に見えてしまい、散文の報告では省略が省略として
# 見えない。欄にすれば欠落が exit 2 になる。
MATERIALS = (
    "stopped",  # 止まった場所
    "guessed",  # 推測で埋めた場所
    "misunderstood",  # 読んだ後の誤解（4 つの質問との突合で出る）
    "unreachable",  # 辿り着けなかった先
    "questions",  # 読みながら湧いた疑問
    "ideas",  # 読みながら思いついたこと
    "skipped",  # 読み飛ばした場所——**これだけが「減らす」材料**
)

# 素材の状態と、その状態で追加に要求する欄。
# **`none` に `asked` を要求するのが「無言の省略を『なし』と読まない」の実装。**
# 聞いていないから出てこなかったのか、聞いた上で無かったのかは、記録の上では
# 同じ「空」に見える。何を聞いたかを書かせて初めて区別が付く。
STATUS = {
    "found": ("items",),  # 出てきた
    "none": ("asked",),  # 聞いたが無かった（何を聞いたかを要求する）
    "not_asked": ("reason",),  # 聞くべきだったが聞かなかった
}

# 収束を妨げる状態。**「聞かなかった」を潰さずに残すのが要点**——散文だと
# 「無かった」と「聞いていない」が同じ空欄になり、後から見分けられない。
BLOCKING = ("not_asked",)

# 回収されなかった疑問の仕分け。**設計の穴は阻害要因にしない**——このループでは
# 直せないものと決めてあり、ゲートにすると「直せないから収束できない」で
# 永久に止まる。書き落としだけが直す対象。
VERDICTS = ("missing_writeup", "design_gap")

# 直しを当てる前に叩かせる検証役の判定語彙。「通す」以外の判定で当てるなら
# 理由（override_reason。押し切ったのか、代案に作り直したのか）が要る——判定を
# 鵜呑みにする必要はないが、黙って無視はできない形にする。
# 「省略（依頼者の指定）」は税をかけていない申告——依頼者が明示に指定したときだけ
# 使える建前で、指定の中身は tax_reason に書かせる（本当に指定があったかは人が見る）。
TAX_VERDICTS = ("通す", "置き場が違う", "根本が別にある", "作る詰まりの懸念", "省略（依頼者の指定）")


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


def validate(rec, path):
    # 型を見るのは診断メッセージを具体的にするため（保証は末尾の境界。冒頭 docstring 参照）。
    if not isinstance(rec, dict):
        fail(f"{path}: 記録の最上位が object でない")
    for key in ("target", "round", "scope", "reader_profile", "pre_answers", "errands", "materials"):
        if key not in rec:
            fail(f"{path}: 必須の欄 '{key}' が無い")
    if not isinstance(rec["round"], int) or isinstance(rec["round"], bool):
        fail(f"{path}: 'round' が整数でない: {rec['round']!r}")
    # 連番検査は間隔しか見ないので、基点を押さえないと負値から始めて連番のまま
    # 永久に素通りできる。手順書は「1 から 1 ずつ」。
    if rec["round"] < 1:
        fail(f"{path}: 'round' が 1 以上でない: {rec['round']!r}")
    # **範囲は読ませる前に書くもの。** 詰まりを見てから狭められると、都合の悪いものを
    # 外に出す道具になる。書かれていること自体はここで、書いた時期は人が見る。
    if not rec.get("scope"):
        fail(f"{path}: 'scope' が空（今回直す範囲を先に書かないと、後から動かせる）")
    if not rec.get("reader_profile"):
        fail(f"{path}: 'reader_profile' が空（前提の線を引かないと、詰まりが読み役のせいにされる）")

    # **答えを見る前に書いたことは機械では確かめられないが、書いたこと自体は確かめられる。**
    # 頭の中に置くだけを許すと、答えを見てから正解を決める後付けになる。
    pre = rec["pre_answers"]
    if not isinstance(pre, str) or not pre:
        fail(f"{path}: 'pre_answers' に先に書いた答えのパスが無い")
    if not os.path.exists(pre):
        fail(f"{path}: 'pre_answers' の指す先が無い: {pre}")

    if not isinstance(rec["errands"], list) or not rec["errands"]:
        fail(f"{path}: 'errands' が空（用事を渡さないと、探せるかを測れない）")
    for i, e in enumerate(rec["errands"]):
        if not isinstance(e, dict):
            fail(f"{path}: errands[{i}] が object でない")
        for field in ("errand", "expected", "reached"):
            if field not in e:
                fail(f"{path}: errands[{i}] に '{field}' が無い")
        if not isinstance(e.get("found"), bool):
            fail(f"{path}: errands[{i}] の 'found' が真偽値でない")
        # 見つからなかったこと自体は阻害要因として後で数える。ここでは記録の形だけ見る。
        if e["found"] and not e["reached"]:
            fail(f"{path}: errands[{i}] は found なのに 'reached' が空")

    if not isinstance(rec["materials"], dict):
        fail(f"{path}: 'materials' が object でない")
    for name in MATERIALS:
        m = rec["materials"].get(name)
        if not isinstance(m, dict):
            fail(f"{path}: 素材 '{name}' の返答が無い（明示返答は全素材に要る）")
        status = m.get("status")
        if status not in STATUS:
            fail(f"{path}: 素材 '{name}' の status が不正: {status!r}（{'/'.join(STATUS)}）")
        for field in STATUS[status]:
            if not m.get(field):
                fail(f"{path}: 素材 '{name}' は status={status} なので '{field}' が要る")
        if status == "found":
            if not isinstance(m["items"], list):
                fail(f"{path}: 素材 '{name}' の 'items' が配列でない")
            for j, it in enumerate(m["items"]):
                if not isinstance(it, dict):
                    fail(f"{path}: 素材 '{name}' の items[{j}] が object でない")
                # key は周をまたいだ突合に使う。無いと「同じ場所でまた詰まった」が測れない。
                if not it.get("key"):
                    fail(f"{path}: 素材 '{name}' の items[{j}] に key が無い（周をまたぐ突合に使う）")
                # 読み役の原文。要約すると手触りが消えるので、欄として要求する。
                if not it.get("verbatim"):
                    fail(f"{path}: 素材 '{name}' の items[{j}] に 'verbatim'（読み役の原文）が無い")
                if name in STUCK:
                    if not isinstance(it.get("in_scope"), bool):
                        fail(f"{path}: 素材 '{name}' の items[{j}] の 'in_scope' が真偽値でない")
                    # 行き先の無い「範囲外」は、消したのと同じ（冒頭 docstring 参照）。
                    if not it["in_scope"] and not it.get("disposition"):
                        fail(
                            f"{path}: 素材 '{name}' の items[{j}] は範囲外なので "
                            "'disposition'（行き先: issue・台帳・次のブランチ）が要る"
                        )
                    # 印だけ付けて理由を書かせないと、再出を消す逃げ道になる（冒頭 docstring 参照）。
                    if "structural" in it and not (isinstance(it["structural"], str) and it["structural"]):
                        fail(
                            f"{path}: 素材 '{name}' の items[{j}] の 'structural' は、"
                            "読み役の性質で再出する理由を書いた文字列でなければならない"
                        )

    for i, u in enumerate(rec.get("unresolved") or []):
        if not isinstance(u, dict):
            fail(f"{path}: unresolved[{i}] が object でない")
        if not u.get("question"):
            fail(f"{path}: unresolved[{i}] に 'question' が無い")
        if u.get("verdict") not in VERDICTS:
            fail(f"{path}: unresolved[{i}] の verdict が不正: {u.get('verdict')!r}（{'/'.join(VERDICTS)}）")
        if u["verdict"] == "missing_writeup":
            if not isinstance(u.get("written"), bool):
                fail(f"{path}: unresolved[{i}] は書き落としなので、書き足したかの 'written' が要る")
            # **収束を判定するのは範囲内だけ**——手順書と同じ規則をここにも通す。既定は
            # 範囲内（黙って外へ倒せないように）で、外へ倒すなら行き先を書かせる。
            if u.get("in_scope") is False and not u.get("disposition"):
                fail(f"{path}: unresolved[{i}] は範囲外の書き落としなので 'disposition'（行き先）が要る")

    # **直しの側にも、集める側と同じ規律を通す**（冒頭 docstring 参照）。
    # 直していない周は空配列——欄自体が無いのは「直したのに書いていない」と
    # 区別が付かないので許さない。
    fixes = rec.get("fixes")
    if not isinstance(fixes, list):
        fail(f"{path}: 'fixes' が配列でない（直していない周は空配列 []。欄の省略は許さない）")
    for i, fx in enumerate(fixes):
        if not isinstance(fx, dict):
            fail(f"{path}: fixes[{i}] が object でない")
        for field, why in (
            ("key", "どの詰まりへの直しか（詰まりの key）"),
            ("file", "どのファイルへ書いたか"),
            ("why_there", "そのファイルの役割・寿命にどう収まるか"),
            ("tax_verdict", "当てる前に叩かせた検証役の判定"),
            ("tax_reason", "検証役の理由"),
        ):
            if not fx.get(field):
                fail(f"{path}: fixes[{i}] に '{field}' が無い（{why}）")
        if fx["tax_verdict"] not in TAX_VERDICTS:
            fail(
                f"{path}: fixes[{i}] の tax_verdict が不正: {fx['tax_verdict']!r}"
                f"（{'/'.join(TAX_VERDICTS)}）"
            )
        # 「通す」以外の判定で当てたなら、理由を書かないと落ちる。押し切ったのか、
        # 判定が示した代案に作り直したのかは、記録の上では同じ空欄に見える。
        # 「省略」は判定に反していないので override_reason は要らない（指定の中身は
        # tax_reason 側。上の必須欄検査が既に要求している）。
        if fx["tax_verdict"] not in ("通す", "省略（依頼者の指定）") and not fx.get("override_reason"):
            fail(
                f"{path}: fixes[{i}] は検証役が『{fx['tax_verdict']}』なのに当てている——"
                "'override_reason'（押し切ったのか、代案に作り直したのか）が要る"
            )

    # 導線の引き金。見たかどうかを毎周書く——見ていない引き金は「立っていない」と
    # 記録の上で区別が付かない（聞いていない素材の 'asked' と同じ理屈）。
    gate = rec.get("structure_gate")
    if not isinstance(gate, dict):
        fail(f"{path}: 'structure_gate' が無い（導線の引き金 4 つを見たかどうかは毎周書く）")
    if not gate.get("checked"):
        fail(f"{path}: structure_gate.checked が空（4 つの引き金をそれぞれ何で見たか）")
    if not isinstance(gate.get("fired"), bool):
        fail(f"{path}: structure_gate.fired が真偽値でない")
    if gate["fired"] and not gate.get("decision"):
        fail(f"{path}: structure_gate は fired なのに 'decision'（構造の判断と根拠）が無い")

    size = rec.get("size")
    if not isinstance(size, dict):
        fail(f"{path}: 'size' が object でない（行数で増減を記録しろ）")
    for field in ("lines_before", "lines_after"):
        v = size.get(field)
        if not isinstance(v, int) or isinstance(v, bool) or v < 0:
            fail(f"{path}: size.{field} が 0 以上の整数でない: {v!r}")


def stuck_items(rec):
    """この周に出た**範囲内の**詰まりを key → 中身で返す。

    範囲外を混ぜないこと——直していないものが次の周でまた出るのは当然で、
    「同じ場所でまた詰まった（直し方が効いていない）」とは別の事象。
    """
    items = {}
    for name in STUCK:
        m = rec["materials"][name]
        if m["status"] == "found":
            for it in m["items"]:
                if it["in_scope"]:
                    items[it["key"]] = it
    return items


def repeated_skips(rec, prev):
    """2 周続けて読み飛ばされた場所。**阻害要因にはしない。**

    1 周だけの読み飛ばしは、その読み役が通った経路に固有の雑音でありうる。**別の
    読み役が同じ場所をまた読まずに済ませて初めて信号になる。** 突合の機構は詰まりの
    ために既に在るのに、読み飛ばしには使っていなかった。読み飛ばしは「減らす」側の
    唯一の材料なので、拾い落とすと直し方が足す側にしか倒れない。
    """
    if prev is None:
        return []

    def keys(r):
        m = r["materials"]["skipped"]
        return {it["key"] for it in m["items"]} if m["status"] == "found" else set()

    return sorted(keys(rec) & keys(prev))


def structural_recurrence(rec, prev):
    """読み役の性質で再出したと印を付けたもの。**阻害要因ではない。人が見ろ。**"""
    if prev is None:
        return []
    now, before = stuck_items(rec), stuck_items(prev)
    return [
        f"{key}: {now[key]['structural']}"
        for key in sorted(set(now) & set(before))
        if now[key].get("structural")
    ]


def out_of_scope(rec):
    """範囲の外へ倒したものと、その行き先。**阻害要因にはしない。**"""
    out = []
    for name in STUCK:
        m = rec["materials"][name]
        if m["status"] == "found":
            out.extend(
                f"{it['key']} → {it['disposition']}"
                for it in m["items"]
                if not it["in_scope"]
            )
    return out


def blockers(rec, prev):
    out = []

    for name in MATERIALS:
        m = rec["materials"][name]
        if m["status"] in BLOCKING:
            out.append(f"素材 '{name}' を聞いていない: {m['reason']}")

    for e in rec["errands"]:
        if not e["found"]:
            out.append(f"用事が片づいていない: {e['errand']}（想定した行き先: {e['expected']}）")

    for u in rec.get("unresolved") or []:
        # 設計の穴は直さないまま残すのが正しいので、阻害要因にしない（冒頭 VERDICTS 参照）。
        # **範囲外の書き落としも外す**——収束を判定するのは範囲内だけ、という手順書の規則を
        # ここにも通す。既定は範囲内なので、黙って外へ倒すことはできない。
        if u["verdict"] == "missing_writeup" and u.get("in_scope", True) and not u["written"]:
            out.append(f"書き落としのまま: {u['question']}")

    if rec.get("git_status_match") is not True:
        out.append("読み役がファイルを書き換えていないことを確かめていない")

    if prev is None:
        out.append("前の周の記録が無い（1 人が詰まらなかったことは、誰も詰まらない証拠にならない）")
        return out

    now, before = stuck_items(rec), stuck_items(prev)

    for key in sorted(set(now) - set(before)):
        out.append(f"新しい詰まり: {key}")

    # **同じ key がまた出たら、直し方が効いていない。** 言い換えで塗り直しても
    # 消えないので、作りを変えるまで阻害要因として残す。ただし読み役の性質で
    # 永久に再出するもの（例: 読み役がその技術を元々知っていた）は印を付けて外す
    # ——直しようのない再出が、唯一の機械的な収束信号を汚す。**印が効くのは突合の
    # 側だけで、新しい詰まりには効かない。** 理由の記入は validate 側で必須。
    for key in sorted(set(now) & set(before)):
        if now[key].get("structural"):
            continue
        out.append(f"同じ場所でまた詰まった（直し方が効いていない）: {key}")

    return out


def growth(rec, prev):
    """足す側にしか倒れていないかを見る。**阻害要因にはしない**（冒頭 docstring 参照）。"""
    if prev is None:
        return []
    delta = rec["size"]["lines_after"] - rec["size"]["lines_before"]
    if delta <= 0:
        return []
    removed = rec.get("removed") or []
    moved = rec.get("moved") or []
    if removed or moved:
        return []
    prev_delta = prev["size"]["lines_after"] - prev["size"]["lines_before"]
    if prev_delta <= 0:
        return [f"{delta} 行増え、削除も移動も 0 件"]
    return [
        f"{delta} 行増え、削除も移動も 0 件（前の周も {prev_delta} 行増）。"
        "**2 周続けて足す側にしか倒れていない**"
    ]


def main():
    if not 2 <= len(sys.argv) <= 3:
        print(__doc__, file=sys.stderr)
        fail(f"引数は 1 個か 2 個（受け取った数: {len(sys.argv) - 1}）")

    rec = load(sys.argv[1])
    # **突合より先に両方を検証する。** 逆順にすると、欄が欠けた記録で比較が KeyError を
    # 投げ、境界が 2 に倒すとはいえ「必須の欄が無い」より読みにくいメッセージになる。
    validate(rec, sys.argv[1])

    prev = None
    if len(sys.argv) > 2:
        prev = load(sys.argv[2])
        validate(prev, sys.argv[2])
        if prev["target"] != rec["target"]:
            fail("2 つの記録の target が違う（対象を動かすな）")
        if rec["round"] != prev["round"] + 1:
            fail(f"周が連番でない: {prev['round']} の次が {rec['round']}")

    outside = out_of_scope(rec)
    if outside:
        print("範囲の外へ出したもの（阻害要因ではない。行き先まで書かれているかを人が見ろ）:")
        for line in outside:
            print(f"  - {line}")

    again = repeated_skips(rec, prev)
    if again:
        print("2 周続けて読み飛ばされた（阻害要因ではない。消す・場所を変える・見出しを付けるのどれかをしたか）:")
        for line in again:
            print(f"  - {line}")

    fixed = structural_recurrence(rec, prev)
    if fixed:
        print("読み役の性質による再出として収束信号から外したもの（阻害要因ではない。理由が本当かを人が見ろ）:")
        for line in fixed:
            print(f"  - {line}")

    grew = growth(rec, prev)
    if grew:
        print("直し方が足す側に偏っている（阻害要因ではない。消す・場所を変える・並べ替えるを見たか）:")
        for line in grew:
            print(f"  - {line}")

    # 押し切りと引き金は阻害要因にしない——検証役の判定は鵜呑みにするものではなく、
    # 引き金は構造の判断（このループの外で実行されうる）へ渡すものだから。人が見る。
    pushed = [
        f"{fx['key']} → 検証役『{fx['tax_verdict']}』: {fx['override_reason']}"
        for fx in rec["fixes"]
        if fx["tax_verdict"] not in ("通す", "省略（依頼者の指定）")
    ]
    if pushed:
        print("「通す」以外の判定で当てた直し（阻害要因ではない。押し切りか代案採用かを人が見ろ）:")
        for line in pushed:
            print(f"  - {line}")

    untaxed = [
        f"{fx['key']} → {fx['tax_reason']}"
        for fx in rec["fixes"]
        if fx["tax_verdict"] == "省略（依頼者の指定）"
    ]
    if untaxed:
        print("検証税を省いた直し（阻害要因ではない。依頼者の指定が本当にあったかを人が見ろ）:")
        for line in untaxed:
            print(f"  - {line}")

    if rec["structure_gate"]["fired"]:
        print("導線の引き金が立った（阻害要因ではない。構造の判断がこの周の文章の直しより先）:")
        print(f"  - {rec['structure_gate']['decision']}")

    found = blockers(rec, prev)
    if found:
        print(f"収束を妨げるもの {len(found)} 件:")
        for b in found:
            print(f"  - {b}")
        sys.exit(1)
    print(
        "機械で見つけられる阻害要因は無い。**これは収束の宣言ではない**——"
        "続けて何人が詰まらなかったか、この読み役では出なかったが出そうな詰まりが無いかは人が見ろ。"
    )


if __name__ == "__main__":
    # **終了コードの契約を担保するのはここ 1 箇所**（理由は冒頭 docstring）。
    try:
        main()
    except SystemExit:
        raise
    except Exception as e:
        fail(f"想定外の例外（{type(e).__name__}）: {e}")
