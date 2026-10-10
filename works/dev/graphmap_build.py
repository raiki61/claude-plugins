"""works/dev/graphmap_build.py — 工程の地図の元（入口の YAML の隣の <名>.graph.json）と設計図の文書を書く・古さを確かめる（開発の道具）。

  uv run --no-project --with pyyaml python3 works/dev/graphmap_build.py build <pack> [<入口の名>…]
  uv run --no-project --with pyyaml python3 works/dev/graphmap_build.py check <pack> [<入口の名>…]

pack の宣言 archon-plugin.json の entrypoints の入口ごとに、部品 .shared/core/graphmap の build で地図の元を組む（入口の名を
省けば全部）。build は書き、check は書かずに、今の YAML から組んだ物と字で違う（か無い）元を名指して終了コード 1 で抜ける。
YAML を替えたら build で書き直す（包みは古い元の地図を足さない。試験 tests/test_graphmap.py が古い元を赤にする）。
pack のモジュールは標準ライブラリだけなので、YAML を読む PyYAML はこの道具が渡す。

役の指示書に機械が貼る節の宣言（promptsection.Section）を 1 つ以上持つ pack には、同じ入口の設計図の文書
<pack>/docs/<入口の名>-design.md も、graphmap.design で作って同じに書く・確かめる（build / check）。宣言を持たない pack では
書かず、飛ばしたことを 1 行で出す。宣言の集め方は section_rows。manifest が壊れていれば名指して終了コード 1 で抜ける。
"""
import contextlib
import importlib.util
import pathlib
import sys

sys.dont_write_bytecode = True
CORE = pathlib.Path(__file__).resolve().parent.parent / ".shared" / "core"
sys.path.insert(0, str(CORE))

import graphmap  # noqa: E402
import promptsection  # noqa: E402
import scopes  # noqa: E402

# 役の支度を持ちうるモジュール（core は Section の置き場と、指示書を core のモジュールが組む役の受け手の表 RECEIVES の置き場、
# ブロックの lib は受け手の表 RECEIVES の置き場）
PREP_GLOBS = (".shared/core/*.py", "blk-*/lib/*.py", "blk-*/scripts/*.py", "darkfactory/lib/*.py", "darkfactory/scripts/*.py")


@contextlib.contextmanager
def _import_path(pack: pathlib.Path, near: pathlib.Path):
    """支度のモジュールを読む間の import の道。読んだ後に道と、pack の中の私的な読み込みを戻す（同じ名の別の置き場の物と取り違えない）"""
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
            if f and not pathlib.Path(f).resolve().is_relative_to(CORE.resolve()):
                del sys.modules[name]


def _load(pack: pathlib.Path, path: pathlib.Path):
    name = "_prep_" + "_".join(path.relative_to(pack).with_suffix("").parts).replace("-", "_").replace(".", "_")
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    with _import_path(pack, path.parent):
        spec.loader.exec_module(mod)
    return mod


def _key(sec) -> tuple:
    return (str(sec), sec.source, sec.human)


def section_rows(pack: pathlib.Path):
    """(sections, receives): graphmap.design に渡す行。sections は貼る節の宣言 {module, name, heading, source, human}
    （promptsection.declared_sections が返す Section を、定義の置き場の core を先に、同じ宣言は 1 度だけ）、receives は各ブロックの lib（と、指示書を core の
    モジュールが組む役の core のモジュール）の表 RECEIVES の行 {workflow, role, module, name, when}（受け手は宣言から読み、コードの参照から推さない）"""
    pack = pathlib.Path(pack).resolve()
    files = []
    for pat in PREP_GLOBS:
        files.extend(sorted(pack.glob(pat)))
    mods = {p: _load(pack, p) for p in files if p.name != "promptsection.py" and "promptsection" in p.read_text(encoding="utf-8")}
    sections, where = [], {}   # where: Section の値 → (モジュール, 定数の名)。同じ宣言は、読み込みが二重でも 1 つ
    for p, mod in mods.items():
        for name, sec in promptsection.declared_sections(mod):
            if _key(sec) not in where:
                where[_key(sec)] = (p.stem, name)
                sections.append({"module": p.stem, "name": name, "heading": str(sec), "source": sec.source, "human": sec.human})
    receives = []
    homes = None   # 役の印の名 → それを持つ工程（指示書を core のモジュールが組む役の表の行が、どの工程の役かを引く）
    for p, mod in mods.items():
        in_lib = p.parent.name == "lib" and p.parent.parent.name.startswith("blk-")
        in_core = p.parent == pack / ".shared" / "core"
        if not (in_lib or in_core) or not getattr(mod, "RECEIVES", ()):
            continue
        for row in mod.RECEIVES:
            if _key(row.section) not in where:
                raise ValueError(f"{p.relative_to(pack)} の RECEIVES の行 {row.role} が、宣言（Section の定数）でない見出しを指している")
            module, name = where[_key(row.section)]
            if in_lib:
                workflow = p.parent.parent.name
            else:
                homes = homes if homes is not None else _role_homes(pack)
                if len(homes.get(row.role, ())) != 1:
                    raise ValueError(f"{p.relative_to(pack)} の RECEIVES の行の役 {row.role!r} が、1 つの工程の役として graph に無い")
                workflow = next(iter(homes[row.role]))
            receives.append({"workflow": workflow, "role": row.role, "module": module, "name": name, "when": row.when})
    return sections, receives


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


def main(argv) -> int:
    for stream in (sys.stdout, sys.stderr):   # 場所の設定が ASCII・cp1252 でも日本語の行で落ちない
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    if len(argv) < 2 or argv[0] not in ("build", "check"):
        print("usage: graphmap_build.py build|check <pack> [<入口の名>…]", file=sys.stderr)
        return 2
    import yaml

    pack = pathlib.Path(argv[1]).resolve()
    eps = graphmap.entrypoints(pack)
    names = list(argv[2:]) or sorted(eps)
    unknown = [n for n in names if n not in eps]
    if unknown:
        print(f"graphmap_build: 入口に無い名 {', '.join(unknown)}（在るのは {', '.join(sorted(eps))}）", file=sys.stderr)
        return 2
    resolve = graphmap.pack_resolver(pack, yaml.safe_load)
    sections, receives = section_rows(pack)
    if not sections:
        print("graphmap_build: 設計図は節の宣言（Section）を持たない pack なので飛ばした")
    else:
        try:
            manifests = scopes.manifests(pack)
        except scopes.ManifestBroken as e:
            print(f"graphmap_build: manifest が読めない: {e}", file=sys.stderr)
            return 1
    bad = 0
    for name in names:
        graph = graphmap.build(pack / eps[name], resolve, pack, yaml.safe_load)
        written = [(graphmap.graph_path(pack, eps[name]), graphmap.dumps(graph), name)]
        if sections:
            try:
                design = graphmap.design(graph, sections, receives, manifests)
            except ValueError as e:
                print(f"graphmap_build: 設計図を出せない: {e}", file=sys.stderr)
                return 1
            written.append((pack / "docs" / f"{name}-design.md", design, name))
        for out, text, entry in written:
            if argv[0] == "build":
                out.parent.mkdir(parents=True, exist_ok=True)
                out.write_text(text, encoding="utf-8")
                print(f"graphmap_build: {out.relative_to(pack)} を書いた")
            elif not out.is_file() or out.read_text(encoding="utf-8") != text:
                print(f"graphmap_build: {out.relative_to(pack)} が古い（graphmap_build.py build {argv[1]} {entry} で書き直す）",
                      file=sys.stderr)
                bad = 1
    return bad


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
