#!/usr/bin/env python3
"""IT の仕事で定着した語でない言い方を見つけ、定着語に直す。

持ち主の CLAUDE.md の「日本語は IT 業界の定着語を使う」を、エージェントが書く文（指示ファイル・役の本文・ツールの出力・納品）で
守らせる。TERMS は、textlint-rule-prh の辞書（prh.yml）と同じく、正しい表記（expected）と、それに当たる言い方の正規表現
（patterns）の組を並べる（https://github.com/textlint-rule/textlint-rule-prh）。語は my_notes の tools/checks/terms.py と
同じにそろえ（「本流」は、my_notes では master、ここでは会社ごとに名前の違うメインブランチと書く）、claude-plugins に多い
4 つ（持ち手・関門・柵・根）を足した。

見ないもの: 引用（`>` の行）と脚注の定義の行と、「」の中（人の言葉やほかの文書の見出しをそのまま引く）と、`` ` `` の中
（コマンド・パス・コード）と、コードブロック（``` か ~~~ で囲んだ所）の中。

使い方:
    python3 terms.py <ファイル>...                  # 当たった行を出す（当たれば 1、読めないファイルが在れば 2 で終わる）
    python3 terms.py --fix [--main 語] <ファイル>...  # 活用ごとの置き換えで直し、直せなかった行を出す
    python3 terms.py --deliver                      # 納品の検査（会社の形の役の deliver_check）として、標準入力の JSON の summary を見る

--fix は機械の置き換えなので、直した後に差分を読み、意味の違う所（「本流」が元にした別のプロジェクトを指す、グラフの「節」は
ノード、など）を手で直す。--main は「本流」を直す語（既定はメインブランチ。ブランチの名前が決まっている文書なら main）。
--deliver は、--deliver の組み込みの検査の後に走る納品の検査（会社の形の役の deliver_check。標準入力に要約の入った JSON が来る）
として打つ。リポジトリ全体の検査は claude-plugins の scripts/terms.py。
"""

import json
import pathlib
import re
import sys

MAIN = "メインブランチ"
# 起こす のうち、引き起こす・掘り起こす・呼び起こす・思い起こすと、障害などを「起こす」（生じさせる）は直さない
_START = "(?<![きりびい])(?<!障害を)(?<!問題を)(?<!事故を)(?<!混乱を)(?<!エラーを)"
# 番 のうち、番号の意味（一番・連番・欠番・何番・番号・番目）と、門番・交番・定番・出番・順番と、attention の画面の名前の
# 「自分の番」「私の番」は直さない
_TURN = r"(?<![一二三四五六七八九十順当本交輪週張定出門連欠何0-9])(?<![0-9] )(?<!自分の)(?<!相手の)(?<!私の)番(?![号目地組人兵台])"

# (正しい表記, 当たる言い方の正規表現)
TERMS = (
    ("セクション", r"(?<![季調関使礼文音])節(?![約度目句分])"),
    ("ターン", r"手番|" + _TURN),
    ("評価実行", r"試し走り"),
    ("ブランチ", r"(?<![「`])枝(?![」`])"),
    (MAIN, r"本流"),
    ("ページ", r"頁"),
    ("キャッシュ", r"溜め(?![るずなてたまれ込こ])"),
    ("ピクセル", r"画素"),
    ("ネットワーク（検出の範囲の意味ならゲートかテスト）", r"(?<!安全)網(?![羅掛目])"),
    ("リベース", r"載せ直"),
    ("fast-forward", r"早送り"),
    ("ゲート", r"関所|関門"),
    ("ツール", r"道具"),
    ("コマンド", r"命令"),
    ("照合する", r"照ら[さしすせ]"),
    ("起動する", _START + r"起こ[さしすせ]"),
    ("フィールド", r"(?<!空)欄(?!外)"),
    ("サブエージェント", r"作業役"),
    ("担当者", r"持ち手"),
    ("チェック", r"柵"),
    ("ルート", r"(?<![屋垣大羽心球尾草禍性精島箱])根(?![拠本気性底幹深元源っ強絶回菜付差づ])"),
)
PATTERNS = tuple((expected, re.compile(p)) for expected, p in TERMS)
SKIPPED_LINE = re.compile(r"^\s*(>|\[\^[^\]]+\]:)")
# 「」と `` の中は見ない（人の言葉・見出しの引用と、コマンド・パス・コード）
PROTECTED = re.compile(r"「[^」\n]*」|`[^`\n]*`")
# コードブロック（``` か ~~~ で囲んだ所）の中は見ない（設定の例の文字列などを書き換えないため）
FENCE = re.compile(r"^\s*(```|~~~)")

# 網 は、通信の意味（ネットワーク）と検出の範囲の意味（「網に掛かる」はゲート・テスト）で訳が分かれるので、見つけるだけで直さない
# 直し方（活用ごとに、長い形から先に当てる）。英字の語は前後を \x01・\x02 で挟み、和文の字に接していれば空白にする
_NOUN = r"(?=[のがはをも〔][^な]|[のがはをも〔]$)"   # 連用形が名詞として使われている（「照らしの結果」）
FIXES = (
    # 起こす → 起動する（_START の除外は直さない）
    (_START + r"起こし直", "起動し直"),
    (_START + r"起こし方", "起動方法"),
    (_START + r"起こさ(?=ない|なく|なけれ|なかっ)", "起動し"),
    (_START + r"起こさず", "起動せず"),
    (_START + r"起こさ(?=[れせ])", "起動さ"),
    (_START + r"起こせれば", "起動できれば"),
    (_START + r"起こせば", "起動すれば"),
    (_START + r"起こせ(?=[るなたてま])", "起動でき"),
    (_START + r"起こそう", "起動しよう"),
    (_START + rf"起こし{_NOUN}", "起動"),
    (_START + r"起こし", "起動し"),
    (_START + r"起こす", "起動する"),
    # 照らす → 照合する
    (r"照らし合わせる", "照合する"),
    (r"照らし合わせた", "照合した"),
    (r"照らし合わせて", "照合して"),
    (r"照らし合わせ", "照合"),
    (r"照らさ(?=ない|なく|なけれ|なかっ)", "照合し"),
    (r"照らさず", "照合せず"),
    (r"照らさ(?=[れせ])", "照合さ"),
    (r"照らせれば", "照合できれば"),
    (r"照らせば", "照合すれば"),
    (r"照らせ(?=[るなたてま])", "照合でき"),
    (rf"照らし{_NOUN}", "照合"),
    (r"照らし", "照合し"),
    (r"照らす", "照合する"),
    # 載せ直す → リベースする
    (r"載せ直さ(?=ない|なく|なけれ|なかっ)", "リベースし"),
    (r"載せ直さず", "リベースせず"),
    (r"載せ直さ(?=[れせ])", "リベースさ"),
    (r"載せ直せれば", "リベースできれば"),
    (r"載せ直せ(?=[るなたてま])", "リベースでき"),
    (r"載せ直し(?=[のがはをもとにで・。）〔]|$)", "リベース"),
    (r"載せ直し", "リベースし"),
    (r"載せ直す", "リベースする"),
    (r"早送り", "\x01fast-forward\x02"),
    (r"手番", "ターン"),
    (r"試し走り", "評価実行"),
    (r"作業役", "サブエージェント"),
    (r"持ち手", "担当者"),
    (r"関所|関門", "ゲート"),
    (r"道具", "ツール"),
    (r"命令", "コマンド"),
    (r"タブ欄", "タブバー"),
    (r"(?<!空)欄(?!外)", "フィールド"),
    (r"柵", "チェック"),
    (r"頁", "ページ"),
    (r"画素", "ピクセル"),
    (r"溜め(?![るずなてたまれ込こ])", "キャッシュ"),
    (r"(?<![「`])枝(?![」`])", "ブランチ"),
    (r"(?<![屋垣大羽心球尾草禍性精島箱])根(?![拠本気性底幹深元源っ強絶回菜付差づ])", "ルート"),
    (r"(?<=書) ?(\d+(?:\.\d+)*) ?節(?![約度目句分])", "のセクション \\1\x02"),
    (r"(?<=の) (\d+(?:\.\d+)*) ?節(?![約度目句分])", "セクション \\1\x02"),
    (r"(\d+(?:\.\d+)*) ?節(?![約度目句分])", "セクション \\1\x02"),
    (r"(?<![季調関使礼文音])節(?![約度目句分])", "セクション"),
    (_TURN, "ターン"),
)
FIX_PATTERNS = tuple((re.compile(p), r) for p, r in FIXES)
# 和文の字（中黒「・」と長音「ー」の隣には空白を置かない）と、守る部分の閉じ
_CJK = "\u3040-\u30fa\u30fd-\u30ff\u3400-\u9fff\uff66-\uff9f"


def _fix(text, main):
    for pattern, repl in FIX_PATTERNS:
        text = pattern.sub(repl, text)
    ascii_main = main.isascii()
    return text.replace("本流", f"\x01{main}\x02" if ascii_main else main)


def _space(text):
    text = re.sub(rf"(?<=[{_CJK}」`])\x01", " ", text).replace("\x01", "")
    return re.sub(rf"\x02(?=[{_CJK}「`])", " ", text).replace("\x02", "")


def line_problems(line):
    """1 行の中の言い方ごとに、(当たった語, 正しい表記) を返す。"""
    if SKIPPED_LINE.match(line):
        return []
    text = PROTECTED.sub(lambda m: m.group(0)[0] + m.group(0)[-1], line)
    return [(m.group(0), expected) for expected, pattern in PATTERNS for m in pattern.finditer(text)]


def text_problems(text):
    """複数行の文の中の言い方ごとに、(行の番号, 当たった語, 正しい表記) を返す。"""
    out, fenced = [], False
    for n, line in enumerate((text or "").splitlines(), start=1):
        if FENCE.match(line):
            fenced = not fenced
        elif not fenced:
            out += [(n, found, expected) for found, expected in line_problems(line)]
    return out


def fix_line(line, main=MAIN, quoted=False):
    """1 行の言い方を直した行。守る部分（「」と ``）の中は quoted のときだけ直す。引用の行はそのまま返す。"""
    if SKIPPED_LINE.match(line):
        return line
    if quoted:
        out = PROTECTED.sub(lambda m: m.group(0)[0] + _fix(m.group(0)[1:-1], main) + m.group(0)[-1], line)
        return _space(_fix(out, main))
    # 守る部分を 1 つずつ \x00 で伏せて直し、伏せた所に元の字を戻す
    kept = [m.group(0) for m in PROTECTED.finditer(line)]
    parts = _fix(PROTECTED.sub("\x00", line), main).split("\x00")
    out = parts[0] + "".join(k + p for k, p in zip(kept, parts[1:]))
    return _space(out)


def fix_text(text, main=MAIN, quoted=False):
    out, fenced = [], False
    for x in text.splitlines(keepends=True):
        if FENCE.match(x):
            fenced = not fenced
        elif not fenced:
            x = fix_line(x.rstrip("\n"), main, quoted) + ("\n" if x.endswith("\n") else "")
        out.append(x)
    return "".join(out)


def deliver_problems(payload):
    """納品の検査に渡る JSON（payload）の要約の、言い方ごとの違反の文の並び。"""
    summary = payload.get("summary") if isinstance(payload, dict) else None
    return [f"{n} 行目: 「{found}」は IT の定着語でない。「{expected}」と書く"
            for n, found, expected in text_problems(summary if isinstance(summary, str) else "")]


def main(argv):
    if argv[:1] == ["--deliver"]:
        try:
            payload = json.load(sys.stdin)
        except ValueError as e:
            print(f"納品の検査の JSON を読めない（{e}）")
            return 2
        bad = deliver_problems(payload)
        if bad:
            print("\n".join(["要約に IT の定着語でない言い方がある（引くときは「」で囲む）:"] + [f"  {x}" for x in bad]))
        return 1 if bad else 0
    fix, quoted, word, paths = False, False, MAIN, []
    args = iter(argv)
    for x in args:
        if x == "--fix":
            fix = True
        elif x == "--quoted":
            quoted = True
        elif x == "--main":
            word = next(args, None)
            if not word:
                print("--main の後に、本流と書いた所に入れる語を書く（例: --main main）")
                return 2
        else:
            paths.append(x)
    bad, unread = 0, 0
    for p in paths:
        path = pathlib.Path(p)
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as e:
            # 無いパス・読めないファイルを飛ばして 0 で終わると、打ち損じたパスが「当たり無し」と読める
            print(f"{p}: 読めない（{e}）", file=sys.stderr)
            unread += 1
            continue
        if fix:
            fixed = fix_text(text, word, quoted)
            if fixed != text:
                path.write_text(fixed, encoding="utf-8")
            text = fixed
        for n, found, expected in text_problems(text):
            print(f"{p}:{n}: 「{found}」は IT の定着語でない。「{expected}」と書く")
            bad = 1
    return 2 if unread else bad


if __name__ == "__main__":
    # 日本語を出すので、Windows の既定のコードページ（cp1252 など）に依らず UTF-8 で書く（読み込む側の出力は変えない）
    for _s in (sys.stdout, sys.stderr):
        if hasattr(_s, "reconfigure"):
            _s.reconfigure(encoding="utf-8")
    sys.exit(main(sys.argv[1:]))
