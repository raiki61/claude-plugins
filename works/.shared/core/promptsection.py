"""役の指示書に機械が貼る節の見出しの宣言（考え prompt-sections。標準ライブラリだけ）。

宣言を 2 つに分け、それぞれの持ち主の側に置く:
- Section（節の宣言）: 見出しの字そのものの str の子。出どころ（source）と人向けの理由（human）を欄に持つ。
  共有の定数は受け手の名も入る条件も持たない（基礎の層が個々のブロックを知らないため）
- Receive（受け手の宣言）: (role, section, when)。受け手の役の指示書を組むブロックの lib のモジュールの直下の表 RECEIVES に
  行を置く。when は入る条件を持つ関数の完全な名 `<モジュール>.<関数>`。条件の式は今の分岐 1 か所に残し、ここへ写さない

source の 3 形（人向けの節は source を持たず、human に役の文脈でない理由を書く）:
- `input:<名>`: ブロックの入力。ブロックの lib に在る Section だけが使え、<名> はそのブロックの YAML の inputs: に在る
- `board:<モジュール>.<定数>`: 盤面のファイル。持ち主の定数を指し、ファイルの名の字を写さない
- `fn:<モジュール>.<関数>`: 機械の計算。節の中身を作る関数
"""
from dataclasses import dataclass
from typing import Any, List, Tuple


class Section(str):
    """見出しの字そのもの。f-string・.format・==・dict の鍵には素の str と同じに入り、欄で出どころと理由を持つ"""

    def __new__(cls, text: str = "", *, source: str = "", human: str = "") -> "Section":
        self = super().__new__(cls, text)
        self.source = source
        self.human = human
        return self

    def __getnewargs_ex__(self):   # copy.deepcopy・pickle の往復で欄を残す
        return (str(self),), {"source": self.source, "human": self.human}


@dataclass(frozen=True)
class Receive:
    """受け手の役 role が、節 section を、関数 when が判じる条件で受ける"""
    role: str
    section: Section
    when: str


def declared_sections(module: Any) -> List[Tuple[str, Section]]:
    """モジュールの直下の Section の値を、定数の名と並べて (名, 値) の列で返す（素の str は数えない）"""
    return [(name, value) for name, value in vars(module).items() if isinstance(value, Section)]
