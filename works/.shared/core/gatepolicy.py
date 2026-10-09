"""人の関所と無人の方針（考え human-gates）の住処。層 L1（標準ライブラリと startrec だけ）。

run の入力の 2 つの語、最後の人の関所の開き方（final_gate）と無人の run か（unattended）の語・既定・確かめと、読む口を持つ。
書き手は線の入口（入口のブロックの節 open。中身は core の entry.start）の 1 か所で、check で確かめた語を始めの記録
（startrec）に置く。読み手（境の節・修正前の関所の決め手・案の直し・報告）は始めの記録をこのモジュールの口で読み、線の節ごとに
入力を写さない（入口を 1 つの入力の形にそろえる。後ろの段は入口の控えだけを読む）。

- FINAL_KEY・UNATTENDED_KEY: 線の入力と始めの記録の欄の名
- FINAL_GATES（ALWAYS・WHEN_NEEDED・PROTECTED_ONLY）: 最後の関所の開き方。空の既定は ALWAYS（P1-R3: 必ず止まれる所を残す）。
  WHEN_NEEDED は開ける理由（最後のテストが緑でない・盤面が人に聞いている…）が在る時だけ、PROTECTED_ONLY は守りのファイルを
  触った時だけ開く（ほかの理由は報告の冒頭に並ぶだけ）
- UNATTENDED・UNATTENDED_WORDS: 無人の語（true）と受ける語（空は人の居る run）
- FINAL_KIND: 最後の関所の答えを残す process.human_items の行の kinds
- check(final, unattended, *, spec) -> {FINAL_KEY, UNATTENDED_KEY}: 入口の語の確かめ（語の外・仕様の段と無人の組みは Refused）
- final_mode(board_dir)・unattended(board_dir): 始めの記録からの読み（記録が無い・欄が空なら既定。記録の開き方が語の外なら
  ValueError——入口が確かめた後なので配線の誤り）
- opens(mode, *, reasons, guarded): 最後の関所を開くか
- head_words(doc): 報告の頭の行の句（始めの記録の dict から。開き方が無ければ空）
"""
from __future__ import annotations

import startrec

FINAL_KEY = "final_gate"
UNATTENDED_KEY = "unattended"
FINAL_GATES = ("always", "when_needed", "protected_only")
ALWAYS, WHEN_NEEDED, PROTECTED_ONLY = FINAL_GATES
UNATTENDED = "true"
UNATTENDED_WORDS = ("", UNATTENDED)
FINAL_KIND = FINAL_KEY


class Refused(ValueError):
    """入口の語が受けられない（入口が InputRefused にする）"""


def check(final, unattended, *, spec) -> dict:
    """入口の 2 つの語を確かめて {FINAL_KEY: 開き方（空は ALWAYS）, UNATTENDED_KEY: 語} を返す"""
    mode = (final or "").strip() or ALWAYS
    if mode not in FINAL_GATES:
        raise Refused(f"{FINAL_KEY}={final!r} は知らない値（{' / '.join(FINAL_GATES)}）")
    alone = (unattended or "").strip()
    if alone not in UNATTENDED_WORDS:
        raise Refused(f"{UNATTENDED_KEY}={unattended!r} は知らない値（空か {UNATTENDED}）")
    if spec and alone:
        raise Refused(f"spec=on と無人の run（{UNATTENDED_KEY}）は組めない——仕様の承認は人の関所で、無人の run は関所で止めるので"
                      "仕様が固まらずに止まる（人の居る run で回す）")
    return {FINAL_KEY: mode, UNATTENDED_KEY: alone}


def final_mode(board_dir) -> str:
    """始めの記録の最後の関所の開き方（無い・空は ALWAYS。語の外は ValueError）"""
    mode = str(startrec.read(board_dir).get(FINAL_KEY) or "").strip() or ALWAYS
    if mode not in FINAL_GATES:
        raise ValueError(f"始めの記録の {FINAL_KEY}={mode!r} は知らない値（{' / '.join(FINAL_GATES)}）")
    return mode


def unattended(board_dir) -> bool:
    """run が無人で回っているか（始めの記録の欄。読めなければ人の居る run）"""
    return startrec.read(board_dir).get(UNATTENDED_KEY) == UNATTENDED


def opens(mode: str, *, reasons, guarded: bool) -> bool:
    """最後の関所を開くか: ALWAYS はいつも、WHEN_NEEDED は開ける理由が在る時、PROTECTED_ONLY は守りのファイルを触った時"""
    if mode == WHEN_NEEDED:
        return bool(reasons)
    if mode == PROTECTED_ONLY:
        return bool(guarded)
    return True


def head_words(doc: dict) -> str:
    """報告の頭の行の句（始めの記録の dict の開き方。無ければ空）"""
    mode = doc.get(FINAL_KEY) if isinstance(doc, dict) else None
    return f"最後の関所: {mode}" if mode else ""
