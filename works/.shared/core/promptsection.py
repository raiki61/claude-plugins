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

宣言の読み口（試験と開発の道具が、支度のモジュールを場所から読んで宣言を集める）:
- prep_files(pack)・declaring_files(pack): 支度を持ちうるモジュールの場所（core・各フォルダの lib と scripts）と、そのうち
  promptsection を使う物
- import_path(pack, near)・load(pack, path): 支度のモジュールを場所から読む（同じ名の別の置き場の物と取り違えない）
受け手の表の行を工程に結ぶ receive_rows は、役を印に持つ工程を地図から引くので graphmap に在る（graphmap → promptsection の向き）
"""
import contextlib
import importlib.util
import pathlib
import sys
from dataclasses import dataclass
from typing import Any, Iterator, List, Tuple

CORE = pathlib.Path(__file__).resolve().parent
# 役の支度を持ちうるモジュール（core は Section の置き場と、指示書を core のモジュールが組む役の受け手の表 RECEIVES の置き場、
# ブロックの lib は受け手の表 RECEIVES の置き場。写しの graphloops/・gl-prompts/（core の下の子の置き場）は入らない）。
# lib・scripts は pack の直下の全部のフォルダから拾う（ラインの名を L1 の字に書かないため）。pack の直下に lib・scripts を持つ
# 支度でないフォルダを足せば、それも拾う
PREP_GLOBS = (".shared/core/*.py", "*/lib/*.py", "*/scripts/*.py")


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


def prep_files(pack: pathlib.Path) -> List[pathlib.Path]:
    """役の支度を持ちうるモジュールの場所（PREP_GLOBS の順）"""
    return [p for pat in PREP_GLOBS for p in sorted(pathlib.Path(pack).glob(pat))]


def declaring_files(pack: pathlib.Path) -> List[pathlib.Path]:
    """promptsection を使う支度のモジュール（Section を宣言する物・RECEIVES を持つ物）"""
    return [p for p in prep_files(pack) if p.name != "promptsection.py" and "promptsection" in p.read_text(encoding="utf-8")]


@contextlib.contextmanager
def import_path(pack: pathlib.Path, near: pathlib.Path) -> Iterator[None]:
    """支度のモジュールを読む間の import の道（core・読む物の隣・ブロックの lib）。読んだ後に道と、pack の中の私的な読み込み
    （この core の物を除く）を戻す（同じ名の別の置き場の物と取り違えない）"""
    pack = pathlib.Path(pack).resolve()
    added = [str(pack / ".shared" / "core"), str(near), *map(str, sorted(pack.glob("blk-*/lib")))]
    before = set(sys.modules)
    sys.path[:0] = added
    try:
        yield
    finally:
        for a in added:
            sys.path.remove(a)
        for name in set(sys.modules) - before:
            f = getattr(sys.modules[name], "__file__", None) or ""
            here = pathlib.Path(f).resolve() if f else None
            if here and here.is_relative_to(pack) and not here.is_relative_to(CORE):
                del sys.modules[name]


def load(pack: pathlib.Path, path: pathlib.Path) -> Any:
    """支度のモジュールを場所から読む（読み込み名は _prep_<pack からの相対パス>。同じ名の別の置き場の物と取り違えない）"""
    pack, path = pathlib.Path(pack).resolve(), pathlib.Path(path).resolve()
    name = "_prep_" + "_".join(path.relative_to(pack).with_suffix("").parts).replace("-", "_").replace(".", "_")
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    with import_path(pack, path.parent):
        spec.loader.exec_module(mod)
    return mod

