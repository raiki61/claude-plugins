"""手元に入っている版のライブラリから、単位が使う名の署名と説明を静的に読む（網に出ない）。層 L3（共有）。

持ち主 2026-10-08「全部使う」の 1 つめの出どころ（設計 works/docs/plans/2026-10-08-libdocs-sources.md）。支度の script の節
（Claude の sandbox の外）が libdocs.section から呼ぶ。仮想環境・node_modules を作らない・入れない。在る物だけを読む。

探し方: 根（roots: run の作業ツリーと、同じ git の main の作業ツリー）ごとに、単位のファイルの置き場から根まで上へ辿り、
各段の .venv・venv・.tox/*・.nox/*（Python。その下の lib/python*/site-packages と Lib/site-packages）と node_modules（JS/TS）を見る
（近い段が先）。読み方:
- Python は import しない（対象のコードを走らせない）。ast で読み、関数は署名と docstring、class は署名・docstring・公開の
  メソッドの署名と docstring の頭の段落。名がそのモジュールに無ければ from の再輸出（from .api import get・from .x import *）を辿る。
  版は dist-info の METADATA（Name が配る名か、top_level.txt に輸入の名が在る物）。同じ場所の .pyi が在ればそちらを読む
- JS/TS は package.json の types・typings・exports["."].types（無ければ index.d.ts・main の .d.ts、無ければ @types/<名>）から
  export … from の相対の先を辿った .d.ts の中の、使う名の宣言（前の /** */ ごと）。使う名が無い・当たらなければ README の頭
- 環境の置き場（.venv・node_modules など）は実パスが根の中に在る物だけ（置き場そのものか途中のフォルダが symlink で根の外を指せば
  見ない）。読むファイルは置き場の実パスの中の物だけ（symlink で外を指す物は読まない）、1 本 MAX_FILE まで
- 返りの dist は dist-info の METADATA の Name（配る名）。libdocs は輸入の名と違えば、公式にこの名で問う

口（標準ライブラリだけ）:
- roots(repo) -> [Path]: repo と、repo が git の作業ツリー（.git がファイル）なら main の作業ツリー（git を起こさない）
- py_uses(text) -> {最上位の名: [点で繋いだ名]} | None（構文の誤り）。js_uses(text) -> {パッケージ: [名]}
- read(roots, lib, files) -> {status: ok|absent|error, version, dist（Python だけ）, where, fragments: [{title, source, tokens, text}], note}
  （lib は libdocs.detect の行: name・search・lang・uses。files は単位のファイルの根からの相対）
"""
import ast
import inspect
import json
import os
import pathlib
import re

MAX_FILE = 1_000_000          # 読むファイル 1 本の上限（バイト）
DOC_MAX = 1200                # docstring 1 本の上限（字）
README_MAX = 3000             # README の頭の上限（字）
MAX_USES = 16                 # 1 本のライブラリで解く名の上限
MAX_METHODS = 20              # class の公開のメソッドの上限
MAX_DTS = 40                  # 辿る .d.ts の本数の上限
MAX_BLOCK = 80                # .d.ts の宣言 1 つの行の上限
MAX_HOPS = 4                  # 再輸出を辿る深さ
PY_ENV_DIRS = (".venv", "venv")
PY_ENV_GLOBS = (".tox", ".nox")


def _norm(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def _tokens(text: str) -> int:
    return max(1, len(text) // 4)


# ---------------------------------------------------------------- 根と環境の置き場
def roots(repo) -> list:
    """repo と、repo が linked worktree なら main の作業ツリー（.git のファイルの gitdir: と、その下の commondir から）"""
    repo = pathlib.Path(repo)
    out = [repo]
    dotgit = repo / ".git"
    try:
        if not dotgit.is_file():
            return out
        line = dotgit.read_text(encoding="utf-8").strip()
        if not line.startswith("gitdir:"):
            return out
        gd = pathlib.Path(line[len("gitdir:"):].strip())
        gd = gd if gd.is_absolute() else repo / gd
        common = gd
        if (gd / "commondir").is_file():
            rel = (gd / "commondir").read_text(encoding="utf-8").strip()
            common = pathlib.Path(rel) if os.path.isabs(rel) else gd / rel
        common = common.resolve()
        main = common.parent
        if common.name == ".git" and main.is_dir() and main != repo.resolve():
            out.append(main)
    except (OSError, UnicodeDecodeError):
        pass
    return out


def _chain(root: pathlib.Path, files) -> list:
    """単位のファイルの置き場から根までの段（近い段が先。重ねない）。files が空なら根だけ"""
    out = []
    for rel in list(files) or [""]:
        parts = pathlib.PurePosixPath(str(rel)).parts[:-1] if rel else ()
        if any(p in ("..", "/") for p in parts):
            parts = ()
        for i in range(len(parts), -1, -1):
            d = root.joinpath(*parts[:i])
            if d not in out:
                out.append(d)
    return out


def _env_dirs(roots_, files, lang: str) -> list:
    """環境の置き場（近い段が先）。実パスが根の実パスの中に在る物だけ（置き場そのものか途中のフォルダが symlink で根の外を指す物は
    読まない。修正役の書いた symlink が支度の節に sandbox の外を読ませないように）"""
    out = []
    for root in roots_:
        try:
            root_real = pathlib.Path(root).resolve()
        except OSError:
            continue
        for d in _chain(pathlib.Path(root), files):
            if lang == "js":
                cands = [d / "node_modules"]
            else:
                cands = [d / n for n in PY_ENV_DIRS]
                for g in PY_ENV_GLOBS:
                    try:
                        cands += sorted(p for p in (d / g).iterdir() if p.is_dir()) if (d / g).is_dir() else []
                    except OSError:
                        pass
            out += [c for c in cands if c.is_dir() and c not in out and _inside(c, root_real)]
    return out


def _site_packages(env: pathlib.Path) -> list:
    try:
        found = sorted((env / "lib").glob("python*/site-packages"), reverse=True)
    except OSError:
        found = []
    win = env / "Lib" / "site-packages"
    return [p for p in found if p.is_dir()] + ([win] if win.is_dir() else [])


def _inside(path: pathlib.Path, base_real: pathlib.Path) -> bool:
    try:
        return path.resolve().is_relative_to(base_real)
    except (OSError, ValueError):
        return False


def _read(path: pathlib.Path, base_real: pathlib.Path):
    """環境の置き場の中の、MAX_FILE までのファイルの字。外を指す・大きい・読めなければ None"""
    try:
        if not path.is_file() or not _inside(path, base_real) or path.stat().st_size > MAX_FILE:
            return None
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


# ---------------------------------------------------------------- 使う名
def py_uses(text: str):
    """{最上位の名: [点で繋いだ名]}（from の名と、import した名の属性。出てくる順）。構文の誤りは None"""
    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError):
        return None
    alias, hits = {}, []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                alias[a.asname or a.name.split(".")[0]] = a.name if a.asname else a.name.split(".")[0]
        elif isinstance(node, ast.ImportFrom) and not node.level and node.module:
            for a in node.names:
                if a.name != "*":
                    hits.append((node.lineno, node.col_offset, f"{node.module}.{a.name}"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id in alias:
            hits.append((node.lineno, node.col_offset, f"{alias[node.value.id]}.{node.attr}"))
    out = {}
    for _l, _c, name in sorted(hits):
        row = out.setdefault(name.split(".")[0], [])
        if name not in row:
            row.append(name)
    return out


def _js_package(spec: str) -> str:
    parts = spec.split("/")
    return "/".join(parts[:2]) if spec.startswith("@") and len(parts) > 1 else parts[0]


JS_NAMED = re.compile(r"""\bimport\s+(?:type\s+)?(?:(\w+)\s*,\s*)?\{([^}]*)\}\s*from\s*['"]([^'"\n]+)['"]""")
JS_NS = re.compile(r"""\bimport\s+(?:(\w+)\s*,\s*)?\*\s+as\s+(\w+)\s+from\s*['"]([^'"\n]+)['"]""")
JS_DEFAULT = re.compile(r"""\bimport\s+(\w+)\s+from\s*['"]([^'"\n]+)['"]""")
JS_REQUIRE = re.compile(r"""\b(?:const|let|var)\s+(\w+)\s*=\s*require\s*\(\s*['"]([^'"\n]+)['"]\s*\)""")


def js_uses(text: str) -> dict:
    """{パッケージ: [名]}（名の import・既定の import は default・名前空間と既定の名の属性。出てくる順）"""
    hits, alias = [], {}
    for m in JS_NAMED.finditer(text):
        pkg = _js_package(m.group(3))
        if m.group(1):
            hits.append((m.start(), pkg, "default"))
            alias[m.group(1)] = pkg
        for w in m.group(2).split(","):
            w = re.sub(r"^type\s+", "", w.strip()).split(" as ")[0].strip()
            if w:
                hits.append((m.start(), pkg, w))
    for m in JS_NS.finditer(text):
        alias[m.group(2)] = _js_package(m.group(3))
        if m.group(1):
            hits.append((m.start(), _js_package(m.group(3)), "default"))
            alias[m.group(1)] = _js_package(m.group(3))
    for rx in (JS_DEFAULT, JS_REQUIRE):
        for m in rx.finditer(text):
            if m.group(1) in ("type",):
                continue
            pkg = _js_package(m.group(2))
            alias[m.group(1)] = pkg
            if rx is JS_DEFAULT:
                hits.append((m.start(), pkg, "default"))
    for name, pkg in alias.items():
        for m in re.finditer(r"(?<![\w.$])" + re.escape(name) + r"\.(\w+)", text):
            hits.append((m.start(), pkg, m.group(1)))
    out = {}
    for _p, pkg, name in sorted(hits, key=lambda h: h[0]):   # 同じ所の名は書いた順のまま（sorted は安定）
        row = out.setdefault(pkg, [])
        if name not in row:
            row.append(name)
    return out


# ---------------------------------------------------------------- Python
def _metadata(text: str) -> dict:
    out = {}
    for line in text.splitlines():
        if not line.strip():
            break
        k, sep, v = line.partition(":")
        if sep and k in ("Name", "Version", "Summary") and k not in out:
            out[k] = v.strip()
    return out


def _py_dist(sp: pathlib.Path, real: pathlib.Path, lib: dict):
    """(版, Summary, 配る名) か None。METADATA の Name が配る名・輸入の名か、top_level.txt に輸入の名が在る dist-info"""
    want = {_norm(lib.get("search") or lib["name"]), _norm(lib["name"])}
    try:
        infos = sorted(sp.glob("*.dist-info"))
    except OSError:
        return None
    for info in infos:
        meta = _metadata(_read(info / "METADATA", real) or "")
        top = (_read(info / "top_level.txt", real) or "").split()
        if _norm(meta.get("Name") or "") in want or lib["name"] in top:
            return meta.get("Version"), meta.get("Summary") or "", meta.get("Name") or ""
    return None


def _module_file(sp: pathlib.Path, real: pathlib.Path, parts) -> pathlib.Path | None:
    base = sp.joinpath(*parts)
    stubs = sp.joinpath(parts[0] + "-stubs", *parts[1:])
    for p in (stubs / "__init__.pyi", stubs.with_suffix(".pyi") if len(parts) > 1 else None,
              base / "__init__.pyi", base / "__init__.py", base.with_suffix(".pyi"), base.with_suffix(".py")):
        if p is not None and p.is_file() and _inside(p, real):
            return p
    return None


def _parse(path: pathlib.Path, real: pathlib.Path, memo: dict | None = None):
    """ファイルの ast（読めない・構文の誤りは None）。memo を渡せば同じファイルを 2 度読まない（* の再輸出を辿る時）"""
    if memo is not None and path in memo:
        return memo[path]
    text = _read(path, real)
    tree = None
    if text is not None:
        try:
            tree = ast.parse(text)
        except (SyntaxError, ValueError):
            tree = None
    if memo is not None:
        memo[path] = tree
    return tree


def _doc(node, limit=DOC_MAX) -> str:
    d = ast.get_docstring(node, clean=True) if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef,
                                                                 ast.AsyncFunctionDef)) else None
    d = inspect.cleandoc(d) if d else ""
    return d if len(d) <= limit else d[:limit].rstrip() + " …"


def _sig(fn) -> str:
    ret = f" -> {ast.unparse(fn.returns)}" if fn.returns is not None else ""
    head = "async def" if isinstance(fn, ast.AsyncFunctionDef) else "def"
    return f"{head} {fn.name}({ast.unparse(fn.args)}){ret}"


def _indent(text: str, pad: str) -> str:
    return "\n".join(pad + ln if ln else ln for ln in text.splitlines())


def _render_def(node) -> str:
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        doc = _doc(node)
        return _sig(node) + (":\n" + _indent(f'"""{doc}"""', "    ") if doc else ": ...")
    if isinstance(node, ast.ClassDef):
        bases = [ast.unparse(b) for b in node.bases] + [ast.unparse(k) for k in node.keywords]
        lines = [f"class {node.name}" + (f"({', '.join(bases)})" if bases else "") + ":"]
        doc = _doc(node)
        if doc:
            lines.append(_indent(f'"""{doc}"""', "    "))
        shown = 0
        for m in node.body:
            if isinstance(m, (ast.FunctionDef, ast.AsyncFunctionDef)) and (m.name == "__init__" or not m.name.startswith("_")):
                if shown >= MAX_METHODS:
                    lines.append("    # …（公開のメソッドはまだ在る）")
                    break
                shown += 1
                first = _doc(m, 400).split("\n\n")[0]
                lines.append("    " + _sig(m) + (":\n" + _indent(f'"""{first}"""', "        ") if first else ": ..."))
        return "\n".join(lines)
    return ast.unparse(node)[:400]


def _defined(tree, name: str):
    """モジュールの頭の段で name を定める節（def・class・代入）。無ければ None"""
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and node.name == name:
            return node
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            if any(isinstance(t, ast.Name) and t.id == name for t in targets):
                return node
    return None


def _from_parts(mod_parts, is_pkg: bool, node: ast.ImportFrom):
    if not node.level:
        return node.module.split(".") if node.module else None
    base = list(mod_parts) if is_pkg else list(mod_parts[:-1])
    if node.level > 1:
        base = base[:len(base) - (node.level - 1)] if len(base) >= node.level - 1 else None
    if base is None:
        return None
    return base + (node.module.split(".") if node.module else [])


def _resolve_py(sp, real, mod_parts, name, hops=0, memo=None, seen=None):
    """(節, ファイル) か (None, None)。モジュール mod_parts の name を、定め・再輸出・サブモジュールの順で探す。memo はファイルの
    ast の控え、seen は辿り済みの (モジュール, 名)（* の再輸出の輪と、同じ所の辿り直しを止める）"""
    memo = {} if memo is None else memo
    seen = set() if seen is None else seen
    key = (tuple(mod_parts), name)
    if key in seen:
        return None, None
    seen.add(key)
    path = _module_file(sp, real, mod_parts)
    if path is None or hops > MAX_HOPS:
        return None, None
    tree = _parse(path, real, memo)
    if tree is None:
        return None, None
    found = _defined(tree, name)
    if found is not None:
        return found, path
    is_pkg = path.stem == "__init__"
    stars = []
    for node in tree.body:
        if not isinstance(node, ast.ImportFrom):
            continue
        target = _from_parts(mod_parts, is_pkg, node)
        if not target or target[0] != mod_parts[0]:
            continue
        for a in node.names:
            if a.name == "*":
                stars.append(target)
            elif (a.asname or a.name) == name:
                got = _resolve_py(sp, real, target, a.name, hops + 1, memo, seen)
                if got[0] is not None:
                    return got
                sub = _module_file(sp, real, target + [a.name])
                if sub is not None:
                    return _parse(sub, real, memo), sub
    for target in stars:
        got = _resolve_py(sp, real, target, name, hops + 1, memo, seen)
        if got[0] is not None:
            return got
    sub = _module_file(sp, real, list(mod_parts) + [name])
    if sub is not None:
        return _parse(sub, real, memo), sub
    return None, None


def _py_fragment(title, node, path) -> dict:
    if isinstance(node, ast.Module):
        doc = _doc(node)
        code = f'"""{doc}"""' if doc else "（モジュールの docstring は無い）"
    else:
        code = _render_def(node)
    text = f"```python\n{code}\n```"
    return {"title": title, "source": str(path), "tokens": _tokens(text), "text": text}


def _read_python(roots_, lib, files) -> dict | None:
    for env in _env_dirs(roots_, files, "python"):
        real = env.resolve()
        for sp in _site_packages(env):
            init = _module_file(sp, real, [lib["name"]])
            if init is None:
                continue
            dist = _py_dist(sp, real, lib)
            version, summary, dist_name = dist if dist else (None, "", "")
            frags, missing, memo = [], [], {}
            for use in list(dict.fromkeys(lib.get("uses") or []))[:MAX_USES]:
                parts = use.split(".")
                node = path = None
                for i in range(len(parts) - 1, 0, -1):
                    if _module_file(sp, real, parts[:i]) is not None:
                        node, path = _resolve_py(sp, real, parts[:i], parts[i], memo=memo)
                        break
                if node is None:
                    missing.append(use)
                else:
                    frags.append(_py_fragment(use, node, path))
            if not frags:
                tree = _parse(init, real, memo)
                doc = _doc(tree) if tree is not None else ""
                body = "\n\n".join(x for x in (summary, doc) if x) or "（説明は無い）"
                text = f"{lib['name']}: {body}"
                frags.append({"title": f"{lib['name']}（モジュールの説明）", "source": str(init), "tokens": _tokens(text),
                              "text": text})
            note = ("手元の版に見つからない名: " + "、".join(missing)) if missing else ""
            return {"status": "ok", "version": version, "dist": dist_name, "where": str(env), "fragments": frags, "note": note}
    return None


# ---------------------------------------------------------------- JS/TS
DTS_FROM = re.compile(r"""\b(?:export|import)\b[^;'"]*?\bfrom\s*['"](\.{1,2}/[^'"\n]+)['"]""")


def _json(path, real):
    try:
        doc = json.loads(_read(path, real) or "null")
    except ValueError:
        return None
    return doc if isinstance(doc, dict) else None


def _types_entry(pkg_dir: pathlib.Path, doc: dict) -> pathlib.Path | None:
    exports = doc.get("exports")
    dot = exports.get(".") if isinstance(exports, dict) else None
    cands = [doc.get("types"), doc.get("typings"), dot.get("types") if isinstance(dot, dict) else None, "index.d.ts"]
    main = doc.get("main")
    if isinstance(main, str) and main:
        cands.append(re.sub(r"\.(c|m)?js$", "", main) + ".d.ts")
    for c in cands:
        if isinstance(c, str) and c:
            p = pkg_dir / c
            if p.is_file():
                return p
    return None


def _dts_next(path: pathlib.Path, spec: str) -> pathlib.Path | None:
    base = (path.parent / spec)
    stem = re.sub(r"\.(c|m)?js$", "", str(base))
    for p in (pathlib.Path(stem + ".d.ts"), pathlib.Path(stem + ".d.mts"), pathlib.Path(stem) / "index.d.ts",
              pathlib.Path(str(base))):
        if p.is_file() and p.name.endswith(".ts"):
            return p
    return None


def _dts_files(entry: pathlib.Path, real: pathlib.Path) -> list:
    out, todo = [], [entry]
    while todo and len(out) < MAX_DTS:
        p = todo.pop(0)
        if p in [x for x, _ in out]:
            continue
        text = _read(p, real)
        if text is None:
            continue
        out.append((p, text))
        for m in DTS_FROM.finditer(text):
            nxt = _dts_next(p, m.group(1))
            if nxt is not None:
                todo.append(nxt)
    return out


def _decl_re(name: str):
    return re.compile(r"^[ \t]*(?:export[ \t]+)?(?:declare[ \t]+)?(?:default[ \t]+)?(?:abstract[ \t]+)?(?:async[ \t]+)?"
                      r"(?:function|class|interface|type|const|let|var|enum|namespace)[ \t]+" + re.escape(name) + r"\b",
                      re.M)


def _block(lines, i) -> str:
    start = i
    if start > 0 and lines[start - 1].rstrip().endswith("*/"):
        j = start - 1
        while j >= 0 and "/**" not in lines[j]:
            j -= 1
        if j >= 0:
            start = j
    depth, out = 0, []
    for ln in lines[i:i + MAX_BLOCK]:
        out.append(ln)
        depth += ln.count("{") - ln.count("}")
        if depth <= 0 and ln.rstrip().endswith((";", "}")):
            break
    return "\n".join(lines[start:i] + out)


def _js_fragments(files, uses) -> tuple:
    frags, missing = [], []
    for name in uses:
        if name == "default":
            continue
        rx, hit = _decl_re(name), None
        for p, text in files:
            m = rx.search(text)
            if m:
                lines = text.splitlines()
                hit = (p, _block(lines, text.count("\n", 0, m.start())))
                break
        if hit is None:
            missing.append(name)
        else:
            body = f"```ts\n{hit[1]}\n```"
            frags.append({"title": name, "source": str(hit[0]), "tokens": _tokens(body), "text": body})
    return frags, missing


def _readme(pkg_dir: pathlib.Path, real: pathlib.Path):
    for n in ("README.md", "readme.md", "Readme.md", "README", "README.markdown"):
        text = _read(pkg_dir / n, real)
        if text:
            return pkg_dir / n, (text[:README_MAX].rstrip() + (" …" if len(text) > README_MAX else ""))
    return None, ""


def _read_js(roots_, lib, files) -> dict | None:
    name = lib["name"]
    for nm in _env_dirs(roots_, files, "js"):
        real = nm.resolve()
        pkg_dir = nm.joinpath(*name.split("/"))
        doc = _json(pkg_dir / "package.json", real)
        if doc is None:
            continue
        version = doc.get("version") if isinstance(doc.get("version"), str) else None
        entry = _types_entry(pkg_dir, doc)
        if entry is None:
            tdir = nm / "@types" / name.lstrip("@").replace("/", "__")
            tdoc = _json(tdir / "package.json", real) or {}
            entry = _types_entry(tdir, tdoc)
        uses = list(dict.fromkeys(lib.get("uses") or []))[:MAX_USES]
        dts = _dts_files(entry, real) if entry is not None and _inside(entry, real) else []
        frags, missing = _js_fragments(dts, uses)
        if not frags:
            src, text = _readme(pkg_dir, real)
            if text:
                frags.append({"title": "README（頭）", "source": str(src), "tokens": _tokens(text), "text": text})
        notes = []
        if missing:
            notes.append("手元の版の型の宣言に見つからない名: " + "、".join(missing))
        if not dts:
            notes.append("型の宣言（.d.ts）が無い")
        if not frags:
            return {"status": "error", "version": version, "where": str(nm), "fragments": [],
                    "note": "；".join(notes + ["README も無い"])}
        return {"status": "ok", "version": version, "where": str(nm), "fragments": frags, "note": "；".join(notes)}
    return None


def read(roots_, lib: dict, files) -> dict:
    """手元に入っている lib の版と、使う名の署名・説明の断片。入っていなければ status absent"""
    try:
        got = (_read_js if lib.get("lang") == "js" else _read_python)(roots_, lib, files)
    except Exception as e:  # noqa: BLE001  読めない理由は節に出す（落とさない）
        return {"status": "error", "version": None, "where": "", "fragments": [], "note": f"{type(e).__name__}: {e}"[:200]}
    return got or {"status": "absent", "version": None, "where": "", "fragments": [], "note": ""}
