"""役の支度のモジュール（役の指示書を組む・貼る節を宣言するモジュール）の読み口と受け手の表の行の道具（tests/test_graphmap.py・
tests/test_lanekit.py が使う）。

- prep_files(pack)・declaring_files(pack): 支度を持ちうるモジュールの場所と、そのうち promptsection を使う物
- import_path(pack, near)・load(pack, path): 支度のモジュールを場所から読む（同じ名の別の置き場の物と取り違えない）
- receive_rows(pack): 表 RECEIVES の行を (場所, 工程, 行) で。core の行の工程は、役を印に持つちょうど 1 つの工程
- drawn(test, role, text, off=()): ブロックの試験が描いた役の指示書（本物の支度の出力）を表と照らす。本文に現れた宣言済みの見出しは
  その役の行に在り、その役の行の節で本文に現れない物は、入る条件の関数が off（この描きの本文に入らない関数）に在る物だけ
_role_homes が YAML を読む PyYAML は試験の殻 tests/run.sh が渡す。
"""
import contextlib
import importlib.util
import pathlib
import re
import string
import sys

sys.dont_write_bytecode = True
CORE = pathlib.Path(__file__).resolve().parents[1] / ".shared" / "core"
if str(CORE) not in sys.path:
    sys.path.insert(0, str(CORE))

import graphmap  # noqa: E402
import promptsection  # noqa: E402

PACK = CORE.parents[1]

# 役の支度を持ちうるモジュール（core は Section の置き場と、指示書を core のモジュールが組む役の受け手の表 RECEIVES の置き場、
# ブロックの lib は受け手の表 RECEIVES の置き場）
PREP_GLOBS = (".shared/core/*.py", "blk-*/lib/*.py", "blk-*/scripts/*.py", "darkfactory/lib/*.py", "darkfactory/scripts/*.py")
# 手で書く役の指示書の本文の在り処（描いた本文に同じ見出しが在っても、機械が貼った節とは言えない）
PROMPT_SOURCES = ("blk-*/prompts/**/*.md", "blk-*/rules/**/*.md", "blk-*/commands/**/*.md", ".shared/core/gl-prompts/**/*.md",
                  ".shared/core/graphloops/prompts/**/*.md", ".shared/core/agents/**/*.md", ".shared/borrow/**/*.md",
                  ".shared/core/writerules/*.md")


def prep_files(pack: pathlib.Path) -> list:
    """役の支度を持ちうるモジュールの場所（PREP_GLOBS の順。写しの graphloops/・gl-prompts/（core の下の子の置き場）は入らない）"""
    return [p for pat in PREP_GLOBS for p in sorted(pathlib.Path(pack).glob(pat))]


def declaring_files(pack: pathlib.Path) -> list:
    """promptsection を使う支度のモジュール（Section を宣言する物・RECEIVES を持つ物）"""
    return [p for p in prep_files(pack) if p.name != "promptsection.py" and "promptsection" in p.read_text(encoding="utf-8")]


@contextlib.contextmanager
def import_path(pack: pathlib.Path, near: pathlib.Path):
    """支度のモジュールを読む間の import の道（core・読む物の隣・ブロックの lib）。読んだ後に道と、pack の中の私的な読み込み
    （この道具の core の物を除く）を戻す（同じ名の別の置き場の物と取り違えない）"""
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
            if here and here.is_relative_to(pack) and not here.is_relative_to(CORE.resolve()):
                del sys.modules[name]


def load(pack: pathlib.Path, path: pathlib.Path):
    """支度のモジュールを場所から読む（読み込み名は _prep_<pack からの相対パス>。同じ名の別の置き場の物と取り違えない）"""
    pack, path = pathlib.Path(pack).resolve(), pathlib.Path(path).resolve()
    name = "_prep_" + "_".join(path.relative_to(pack).with_suffix("").parts).replace("-", "_").replace(".", "_")
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    with import_path(pack, path.parent):
        spec.loader.exec_module(mod)
    return mod


def receive_rows(pack: pathlib.Path) -> list:
    """(読んだ物の場所, 工程の名, 行): 各ブロックの lib（と、指示書を core のモジュールが組む役の core のモジュール）の表 RECEIVES の行。
    lib の行の工程はそのブロック、core の行の工程は、行の役を印に持つちょうど 1 つの工程（graph の印から引く。0 か 2 つ以上なら
    ValueError）"""
    pack = pathlib.Path(pack).resolve()
    mods = {p: load(pack, p) for p in declaring_files(pack)}
    out, homes = [], None   # homes: 役の印の名 → それを持つ工程
    for p, mod in mods.items():
        in_lib = p.parent.name == "lib" and p.parent.parent.name.startswith("blk-")
        in_core = p.parent == pack / ".shared" / "core"
        if not (in_lib or in_core):
            continue
        for row in getattr(mod, "RECEIVES", ()):
            if in_lib:
                out.append((p, p.parent.parent.name, row))
                continue
            homes = homes if homes is not None else _role_homes(pack)
            if len(homes.get(row.role, ())) != 1:
                raise ValueError(f"{p.relative_to(pack)} の RECEIVES の行の役 {row.role!r} が、1 つの工程の役として graph に無い")
            out.append((p, next(iter(homes[row.role])), row))
    return out


def _role_homes(pack: pathlib.Path) -> dict:
    """役の印の名 → それを持つ工程の名の集まり（入口ごとの graph の印から）"""
    import yaml

    resolve = graphmap.pack_resolver(pack, yaml.safe_load)
    homes: dict = {}
    for rel in graphmap.entrypoints(pack).values():
        graph = graphmap.build(pack / rel, resolve, pack, yaml.safe_load)
        for marker, places in graphmap.markers(graph).items():
            homes.setdefault(marker, set()).update(wf for wf, _ in places)
    return homes


_TABLE: dict = {}


def _pattern(heading: str):
    """見出しの型（.format の穴を持つ。行を丸ごと占める穴の中身は複数行でもよい）が本文の行の頭から現れるかの正規表現。1 行目に
    記号・空白・穴の外の字が無い型（`### {key}`）はどの見出しにも当たるので照らせず None"""
    head = heading.strip("\n")
    parts = list(string.Formatter().parse(head))
    first = "".join(lit for lit, *_ in parts).split("\n")[0]
    if not first.strip("# "):
        return None
    body = ""
    for k, (lit, field, *_) in enumerate(parts):
        body += re.escape(lit)
        if field is not None:   # 行を丸ごと占める穴は複数行の中身を、行の中の穴は 1 行の中身を受ける
            after = parts[k + 1][0] if k + 1 < len(parts) else ""
            whole = (not lit or lit.endswith("\n")) and (not after or after.startswith("\n"))
            body += "[\\s\\S]*?" if whole else "[^\\n]*?"
    return re.compile(r"(?m)^" + body + r"(?=\n|\Z)")


def _table(pack: pathlib.Path = PACK):
    """(役 → {節の字: 入る条件の関数の集まり}, [(節の字, 正規表現)]): 受け手の表と、照らせる機械が貼る宣言済みの見出し（human の
    無い物。手で書く役の指示書の本文の元（PROMPT_SOURCES）に同じ見出しが在る物は、本文に現れても機械が貼ったとは言えないので外す）"""
    key = pathlib.Path(pack).resolve()
    if key not in _TABLE:
        roles: dict = {}
        for _, _, row in receive_rows(key):
            roles.setdefault(row.role, {}).setdefault(str(row.section), set()).add(row.when)
        heads = {str(sec) for p in declaring_files(key) for _, sec in promptsection.declared_sections(load(key, p)) if not sec.human}
        docs = [p.read_text(encoding="utf-8") for pat in PROMPT_SOURCES for p in sorted(key.glob(pat))]
        _TABLE[key] = (roles, [(h, rx) for h in sorted(heads)
                               if (rx := _pattern(h)) is not None and not any(rx.search(d) for d in docs)])
    return _TABLE[key]


def drawn(test, role: str, text: str, off=()) -> None:
    """役 role の描いた指示書 text を受け手の表と照らす（試験 test の断言で落とす）。off は、この描きの本文に入らない節の入る条件の
    関数の完全な名（この描きで条件が偽の物・包みが本文でなく system prompt に足す物・本文でなく指示書が名指すファイルで渡す物。ファイルの中身を描ける所は text につないで照らす）"""
    roles, heads = _table()
    mine = roles.get(role, {})
    seen = {h for h, rx in heads if rx.search(text)}
    stray = sorted(h.splitlines()[0] for h in seen if h not in mine)
    test.assertEqual(stray, [], f"役 {role} の指示書に、{role} の行の無い宣言済みの見出しが在る")
    checkable = {h for h, _ in heads}
    unseen = sorted(h.splitlines()[0] for h, whens in mine.items() if h in checkable and h not in seen and not whens & set(off))
    test.assertEqual(unseen, [], f"役 {role} の行の節が指示書に無い（この描きで入る条件が偽なら、その関数を off に名指す）")
    named = {w for whens in mine.values() for w in whens}
    test.assertEqual(sorted(set(off) - named), [], f"off に、役 {role} の行の入る条件でない関数がある")
