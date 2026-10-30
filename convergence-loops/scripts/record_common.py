#!/usr/bin/env python3
"""検証器 4 本（<loop>-record.py）が共有する土台——契約の 3 値を守る口と、出力を UTF-8 にする口と、記録を読む口と、型を確かめる部品。

**なぜ共有できるか。** 検証器は graphloops の find_validator が
`scripts/<loop>-record.py` としてプラグインの中から解決する（`<PLUGIN>_ROOT` → 同じリポジトリ →
インストール済みキャッシュ）。どの経路でも `scripts/` ごと在るので、隣を import できる。
以前は「1 本ずつ配る前提で共有モジュールを持たない」として写していたが、**写しは黙って割れた**
（実測 2026-09-14: `fail` が `_rows` より後ろに在る本が 1 つあり、契約の 3 値のうち exit 2 が潰れて
未処理例外の exit 1 になっていた）。順序の不変条件はここに 1 回だけ在ればよい。

**代償**（承知の上で受ける）: `--validator /どこか/自作.py` で外のファイルを指すときは、この本文も
隣に置くことになる。単体で持ち出せる性質が 1 つ減る。

契約の 3 値: 0 = 収束 / 1 = 阻害要因あり / 2 = 記録が不正。**`fail` はこのファイルの先頭に置く**
——`_rows` と `_tables` はインポート時に呼ばれるので、`fail` が後ろに在ると属性の書き忘れが
NameError（未処理例外の exit 1）になり、「記録が不正」と「阻害要因あり」の区別が付かなくなる。
"""
import json
import sys

def fail(msg):
    print(f"記録が不正: {msg}", file=sys.stderr)
    sys.exit(2)

def run(main):
    """`main` を走らせる。**終了コードの契約を担保するのはここ 1 箇所**——想定外の例外は未処理のままだと exit 1
    （阻害要因あり）になるので、記録の不正（2）に倒す。"""
    try:
        main()
    except SystemExit:
        raise
    except Exception as e:
        fail(f"想定外の例外（{type(e).__name__}）: {e}")

def utf8_output():
    """標準出力と標準エラーを UTF-8 に固定する。各本が import の直後（例外境界 `run` より前）に 1 回呼ぶ。

    Windows の既定コンソールは cp932 等で、本文の記号（—）を encode できずに落ちる。落ちると終了コードが 1 になり
    「阻害要因あり」と区別が付かないため、収束を永久に宣言できなくなる。

    **try で包む。** ここは例外境界より前（インポート時）に走る。`hasattr` で守ってもメソッドの有無しか見ないので、
    detach 済み・クローズ済みのストリームでは `reconfigure` が例外を投げ、未捕捉のまま終了コード 1 になる
    ——塞ごうとしている当の状態を、塞ぐ処理自体が作る。出力の文字化けは致命ではないので、失敗したら黙って諦める。
    以前は 4 本が同じ try/except を 1 つずつ写していた（2026-10-26、頼み 0ed9d5 で寄せた）。
    """
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError, OSError):
            pass   # 出力の文字化けは致命でないので諦める（1 で落とすより良い）

def load(path):
    """記録を読む。**読めないことは記録の不正（2）で、発行阻害（1）ではない。**"""
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except OSError as e:
        fail(f"{path}: 開けない（{e.strerror}）")
    except json.JSONDecodeError as e:
        fail(f"{path}: JSON として読めない（{e}）")
    except UnicodeDecodeError as e:
        fail(f"{path}: UTF-8 として読めない（{e}）")

def _rows(what, cls, rows):
    """状態の表を組む。**属性の書き忘れをここで落とす。** 素の namedtuple で組むと、書き忘れは TypeError に
    なるが**末尾の例外境界より前（インポート時）**なので未処理例外の exit 1 になり、「阻害要因あり」と
    区別が付かない——契約の 3 値が 1 つ潰れる。

    4 本の検証器が同じ物を呼ぶ（以前は本ごとの写しで、順序が割れて実際に潰れた）。
    """
    out = {}
    for name, args in rows.items():
        try:
            out[name] = cls(*args)
        except TypeError as e:
            fail(f"{what} の '{name}' の行が不完全（属性の書き忘れ）: {e}")
    return out

def _tables(what, build):
    """プロンプトに貼る表を組む。**組み立ての失敗をここで落とす。**

    module 直下で素に組むと、`v.fields[0]` の IndexError や `ORIGIN_NOTE[…]` の KeyError が
    **末尾の例外境界より前（インポート時）**に起き、未処理例外の exit 1 になる——契約の 3 値
    （0 収束・1 阻害要因あり・2 記録が不正）のうち exit 2 が潰れ、「記録が不正」と「阻害要因あり」の
    区別が付かない。`_rows` が表の行について既にやっていることを、表の**組み立て**にも当てる。
    """
    try:
        return build()
    except (IndexError, KeyError, TypeError) as e:
        fail(f"{what} の組み立てに失敗（正本の表と写しが割れている）: {e!r}")

def is_int(v):
    """bool でない int。bool は int の派生なので、素の isinstance では True が 1 として通る"""
    return isinstance(v, int) and not isinstance(v, bool)

def is_str_list(v):
    """空でない文字列だけの配列（配列そのものは空でよい）"""
    return isinstance(v, list) and all(isinstance(s, str) and s.strip() for s in v)

def require_record(rec, path, keys):
    """記録の最上位が object で、必須のフィールド `keys` が全部在ること"""
    if not isinstance(rec, dict):
        fail(f"{path}: 記録の最上位が object でない")
    for key in keys:
        if key not in rec:
            fail(f"{path}: 必須のフィールド '{key}' が無い")

def require_round(rec, path):
    """周の番号。連番検査（`rec["round"] != prev["round"] + 1`）は間隔しか見ないので、基点を
    押さえないと負値から始めて連番のまま永久に素通りできる。手順書は「1 から 1 ずつ」。"""
    if not is_int(rec["round"]):
        fail(f"{path}: 'round' が整数でない: {rec['round']!r}")
    if rec["round"] < 1:
        fail(f"{path}: 'round' が 1 以上でない: {rec['round']!r}")

def require_labels(name, labels, keys):
    """表示の語の表 `labels` が、キー `keys` を全部持つこと（インポート時に呼ぶ）"""
    missing = [k for k in keys if k not in labels]
    if missing:
        fail(f"表示の語の表 {name} にキーが無い: {missing}")

def print_list(header, lines, item=lambda s: f"  - {s}"):
    """見出しと項目の行。項目が無ければ何も出さない"""
    if lines:
        print(header)
        for line in lines:
            print(item(line))

def require_dict(v, what, note=""):
    if not isinstance(v, dict):
        fail(f"{what} が object でない{note}")
    return v

def require_str_list(v, what):
    if not is_str_list(v):
        fail(f"{what} が文字列の配列でない")
    return v

def require_str(rec, key, where):
    v = rec.get(key)
    if not isinstance(v, str) or not v.strip():
        fail(f"{where}: '{key}' が空か文字列でない")
    return v

def require_int(rec, key, where, minimum=0):
    v = rec.get(key)
    if not is_int(v) or v < minimum:
        fail(f"{where}: '{key}' が {minimum} 以上の整数でない")
    return v

def require_bool(rec, key, where):
    v = rec.get(key)
    if not isinstance(v, bool):
        fail(f"{where}: '{key}' が bool でない")
    return v

def not_applicable(v):
    """「該当なし」の共通形。理由なしの該当なしは認めない。"""
    return (
        isinstance(v, dict)
        and v.get("status") == "not_applicable"
        and isinstance(v.get("reason"), str)
        and v["reason"].strip()
    )

# ---- doctor と research の記録が同じ形で持つ物（厚みの三段・ゲート・抜き取り・収束）。値はキー、表示の語は各本の LABELS ----
THICKNESS = ("light", "standard", "heavy")
DECIDERS = ("requester", "default")
GATE_VERDICTS = ("pass", "redesign-needed", "unverifiable")

def check_thickness(rec, path, shown):
    """厚みとその決め手。`shown` は診断の文に出す許す値の一覧（本ごとに表示の語の付け方が違う）"""
    if rec["thickness"] not in THICKNESS:
        fail(f"{path}: 'thickness' が不正: {rec['thickness']!r}（{shown}）")
    if rec["thickness_decider"] not in DECIDERS:
        fail(f"{path}: 'thickness_decider' が不正: {rec['thickness_decider']!r}")

def check_gate(g, v, path):
    """走ったゲート 1 つの形。cold_reader は周ごとの判定の並び、他は判定と理由"""
    require_dict(v, f"{path}: gates.{g}")
    if g == "cold_reader":
        rounds = v.get("rounds")
        if not isinstance(rounds, list) or not rounds:
            fail(f"{path}: cold_reader の rounds が空")
        for i, r in enumerate(rounds):
            if not isinstance(r, dict) or r.get("verdict") not in GATE_VERDICTS:
                fail(f"{path}: cold_reader rounds[{i}] の verdict が不正")
            require_int(r, "findings", f"{path}: cold_reader rounds[{i}]")
    else:
        if v.get("verdict") not in GATE_VERDICTS:
            fail(f"{path}: {g} の verdict が不正: {v.get('verdict')!r}")
        require_str(v, "reason", f"{path}: gates.{g}")

def check_sampling(smp, path, field, known, noun):
    """抜き取りは status=done か「該当なし+理由」。`field` は抜いた物の一覧の鍵、`known` はその母集団、`noun` は診断の呼び名"""
    if not_applicable(smp):
        return
    if isinstance(smp, dict) and smp.get("status") == "done":
        sampled = smp.get(field)
        if not isinstance(sampled, list) or not sampled:
            fail(f"{path}: sampling.{field} が空")
        unknown = [s for s in sampled if s not in known]
        if unknown:
            fail(f"{path}: sampling.{field} に無い{noun}: {unknown}")
        require_int(smp, "overturned", f"{path}: sampling")
    else:
        fail(f"{path}: 'sampling' は status=done か「該当なし+理由」のどちらかの形")

def check_lists(rec, path, specs):
    """`(フィールド名, 各項に要る文字列のフィールド)` の組ごとに、配列で、各項が object で文字列が埋まっていること"""
    for name, fields in specs:
        if not isinstance(rec[name], list):
            fail(f"{path}: '{name}' が配列でない")
        for i, item in enumerate(rec[name]):
            require_dict(item, f"{path}: {name}[{i}]")
            for k in fields:
                require_str(item, k, f"{path}: {name}[{i}]")

def check_convergence(conv, path, outcomes):
    """周の数・連続ゼロの数・結末と、止まったときの理由"""
    require_int(conv, "rounds_total", f"{path}: convergence", 1)
    require_int(conv, "consecutive_zero", f"{path}: convergence")
    if conv.get("outcome") not in outcomes:
        fail(f"{path}: convergence.outcome が不正（{'/'.join(outcomes)}）")
    if conv["outcome"] == "stopped":
        require_str(conv, "stopped_reason", f"{path}: convergence（outcome=stopped）")

def publish_main(doc, validate, blockers, unsettled, closing):
    """doctor と research の main。`unsettled` は停止の申告の括弧の中の語、`closing` は阻害が無いときの結びの文"""
    if len(sys.argv) != 2:
        print(doc, file=sys.stderr)
        fail(f"引数は 1 個（受け取った数: {len(sys.argv) - 1}）")

    rec = load(sys.argv[1])
    validate(rec, sys.argv[1])

    found = blockers(rec)
    if found:
        print_list(f"発行を妨げるもの {len(found)} 件:", found)
        sys.exit(1)
    if rec["convergence"]["outcome"] == "stopped":
        print(
            f"停止（{unsettled}）の申告つきで発行できる: {rec['convergence']['stopped_reason']}——"
            "諮りたかった内容は散文の冒頭に「要人間判断」として列挙しろ。"
        )
        return
    print("機械で見つけられる発行の阻害は無い。**これは品質・飽和の宣言ではない**——" + closing)
