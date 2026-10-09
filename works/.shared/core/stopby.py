"""止めの理由の住処（考え stop-reasons。地図 docs/concepts.md）。層 L1: 標準ライブラリだけ（works のほかの物を import しない）。
Python 3.9 で動く。

機械（線・ブロック・core）が盤面の state.stop.by に書く語は、頭 HEAD（works:）に名を付けた 1 語。報告の結末の口
（report.stop_outcome）はこの頭の語を「線が止めた」（stopped_by_line）と読む（is_line）。同じ語は、答えを待つ
process.human_items の行の node（conflict・replan・守りのファイル）・裁定の by（機械が人に回した裁定）・trace の行の by
（empty-fix）にも使う。どれも「機械がした」の印で、名の空間は 1 つ（2 つの持ち主が同じ名を別の意味で使わない）。

- HEAD: 機械の語の頭。is_line(by): 機械が止めた語か（頭で見る）
- REASONS: core（.shared/core）が書く語と、2 つ以上の持ち主が共に書く語の表（名 → 意味）。定数（ADAPTER など）は
  この表の名に HEAD を付けた語で、呼び手はその定数を引く（自分の定数に写さない）
- declare(name, meaning): ブロックとラインが自分だけの語を足す口（表の名と、ほかの持ち主が別の意味で足した名は拒む）。
  返りの語を自分の定数に置いてよい（ほかのブロックの語は引かない。ブロックの独立）
- declared(): declare で足された語の表の写し（名 → 意味）

語の字（盤面・報告・固定材料に残る）は変えない。名を変えると前の盤面の止めを読み違える。
"""
import re

HEAD = "works:"
NAME = re.compile(r"[a-z][a-z0-9]*(-[a-z0-9]+)*")   # 名の形（小文字と数字を - でつなぐ）

REASONS = {
    "adapter": "包みの確かめが通らない（この run の役の起動が包みを通っていない・宣言した包みの形が読めない・役の起動に柵が掛かっていない）",
    "ci": "CI の任せ先の役の返答を受けられなかった（3 回とも拒まれた・輪が回らなかった）か、CI の役の後に start の輪へ戻れない",
    "conflict": "食い違いの申し出が答えを待つまま止めた（その答えの行の node も同じ語）",
    "delta": "差分の審査の段が止めた（審査役が 3 回とも拒まれた・受けた 2 判定の控えを置けない・修正案の欄の控えの壊れを見た）",
    "empty-fix": "止めでなく trace の行の by: 直す義務 0 件の周で、機械が修正の節に空の返答を渡した",
    "fix": "修正の段が止めた（受け付けた返答が作業ツリーを変えていない・brief の控えが壊れた・修正案の欄の控えが凍結と食い違った）",
    "lens": "レンズの集め役が終わらなかった",
    "plan-converge": "事前審査の壁打ちが収まらずに止めた・案の節を巻き戻した",
    "pr": "並行 PR の任せ先の役が 3 回とも拒まれて輪を抜けた",
    "premises": "前提の実測が盤面に無い・実測の役が諦めた",
    "purpose": "目的の文が盤面に無い・目的の役が諦めた",
    "refix": "手直しの段が止めた（手直し・2 回目の審査の役が 3 回とも拒まれた・修正案の欄の控えの壊れを見た）",
    "rejudge": "再審の節の返答を受けられなかった（3 回とも拒まれた・回した後も待ちのまま）",
    "rejudge-session": "判定役の会話が見つからず、再審せずに止めた",
    "replan": "同じ run の中の案の直しで止めた（その答えの行の node も同じ語）",
    "scope-check": "窓の照らし（部品の置き場と宣言）が誤りを見て止めた",
}
_DECLARED = {}


def word(name: str) -> str:
    """表の名（か declare で足した名）の語。知らない名は KeyError（字の誤りで黙って新しい語を作らない）"""
    if name not in REASONS and name not in _DECLARED:
        raise KeyError(f"止めの理由の名 {name!r} は表 REASONS にも declare にも無い")
    return HEAD + name


def declare(name: str, meaning: str) -> str:
    """ブロックかラインが自分だけの語を足して、その語を返す。同じ名と同じ意味の 2 度目は同じ語を返す（読み直し）。
    名の形が違う・意味が空・表の名・別の意味で足された名は ValueError"""
    if not isinstance(name, str) or not NAME.fullmatch(name):
        raise ValueError(f"止めの理由の名 {name!r} の形が違う（小文字と数字を - でつなぐ）")
    if not isinstance(meaning, str) or not meaning.strip():
        raise ValueError(f"止めの理由 {name!r} に意味が要る")
    if name in REASONS:
        raise ValueError(f"止めの理由の名 {name!r} は core の表に在る（定数を引く）")
    if _DECLARED.setdefault(name, meaning) != meaning:
        raise ValueError(f"止めの理由の名 {name!r} は別の意味で足されている（{_DECLARED[name]}）")
    return HEAD + name


def declared() -> dict:
    """declare で足された {名: 意味} の写し"""
    return dict(_DECLARED)


def is_line(by) -> bool:
    """機械（線・ブロック・core）が書いた語か"""
    return isinstance(by, str) and by.startswith(HEAD)


ADAPTER = word("adapter")
CI = word("ci")
CONFLICT = word("conflict")
DELTA = word("delta")
EMPTY_FIX = word("empty-fix")
FIX = word("fix")
LENS = word("lens")
PLAN_CONVERGE = word("plan-converge")
PR = word("pr")
PREMISES = word("premises")
PURPOSE = word("purpose")
REFIX = word("refix")
REJUDGE = word("rejudge")
REJUDGE_SESSION = word("rejudge-session")
REPLAN = word("replan")
SCOPE_CHECK = word("scope-check")
