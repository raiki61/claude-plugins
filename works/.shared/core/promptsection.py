"""役の指示書に機械が貼る節の見出しの宣言（考え prompt-sections。標準ライブラリだけ）。

宣言を 2 つに分け、それぞれの持ち主の側に置く:
- Section（節の宣言）: 見出しの字そのものの str の子。出どころ（source）か、役の指示書に機械が貼らない理由（human）を欄に持つ。
  共有の定数は受け手の名も入る条件も持たない（基礎の層が個々のブロックを知らないため）
- Receive（受け手の宣言）: (role, section, when)。役の印の名 ← 節 ← 入る条件を判じる関数。受けるとは、節がその役の文脈に届くこと
  （指示書に貼られる、または指示書が名指すファイルで渡る）。受け手の役の指示書を組むモジュールの直下の
  表 RECEIVES に行を置く（ブロックの lib のモジュールの行はそのブロックの役。指示書を組む core のモジュールの行は、役を印に持つ
  ちょうど 1 つの工程の役）。when は入る条件を持つ関数の完全な名 `<モジュール>.<関数>`。条件の式は今の分岐 1 か所に残し、ここへ
  写さない。入る条件の関数が節の出どころ（source の fn:）と同じなら when は省き、行は出どころの関数を入る条件として持つ（違う時だけ書く）

source の 3 形（機械が貼らない節は source を持たず、human にその理由を書く。人が読む報告の見出し・指示書から節を切り出す探し字・
役が自分で書く節の見出しなど）:
- `input:<名>`: ブロックの入力。ブロックの lib に在る Section だけが使え、<名> はそのブロックの YAML の inputs: に在る
- `board:<モジュール>.<定数>`: 盤面のファイル。持ち主の定数を指し、ファイルの名の字を写さない
- `fn:<モジュール>.<関数>`: 機械の計算。節の中身を作る関数
"""
from dataclasses import dataclass
from typing import Any, List, Tuple


class Section(str):
    """見出しの字そのもの。f-string・.format・==・dict の鍵には素の str と同じに入り、欄で出どころか貼らない理由を持つ"""

    def __new__(cls, text: str = "", *, source: str = "", human: str = "") -> "Section":
        self = super().__new__(cls, text)
        self.source = source
        self.human = human
        return self

    def __getnewargs_ex__(self):   # copy.deepcopy・pickle の往復で欄を残す
        return (str(self),), {"source": self.source, "human": self.human}


@dataclass(frozen=True)
class Receive:
    """受け手の役 role が、節 section を、関数 when が判じる条件で受ける。when を省けば節の出どころ（fn:）の関数"""
    role: str
    section: Section
    when: str = ""

    def __post_init__(self):
        if not self.when:
            source = getattr(self.section, "source", "")
            kind, _, fn = source.partition(":")
            if kind != "fn":
                raise ValueError(f"受け手の行 {self.role} の when が無く、節の出どころが関数（fn:）でない: {source!r}")
            object.__setattr__(self, "when", fn)


def declared_sections(module: Any) -> List[Tuple[str, Section]]:
    """モジュールの直下の Section の値を、定数の名と並べて (名, 値) の列で返す（素の str は数えない）"""
    return [(name, value) for name, value in vars(module).items() if isinstance(value, Section)]
