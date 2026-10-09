"""ライブラリの文書を 2 つの出どころ（手元の版・公式）から機械が引いて盤面にファイルで控え、指示書に貼る節（ファイルの一覧）を組む。
層 L3（共有）。

持ち主 2026-10-08「全部使う」（設計 works/docs/plans/2026-10-08-libdocs-sources.md）。2026-10-09 に持ち主が Context7 をやめると
決めた（3 つめの出どころだった。手元と公式は残す）。役が自分で引く口（WebSearch・WebFetch）とは別に、支度の script の節
（Claude の sandbox の外）が、単位が使うライブラリの文書を先に取って指示書に入れる。出どころは次の順で、どれも登録も鍵も要らない:
1. 手元の版（libdocs_local。網に出ない）: run の作業ツリーと同じ git の main の作業ツリーに入っている .venv・venv・.tox・.nox・
   node_modules の中のライブラリを import せずに読んだ、単位が使う名の署名と説明。読めた版を以後の版にする（宣言の版より正しい）
2. 公式（libdocs_web）: PyPI の README と docs の場所の llms.txt、npm は GitHub の版の tag の README と homepage の llms.txt。
   問いはライブラリの名・版と registry の答えに在った URL だけ。鍵は付けない。輸入の名と配る名が違えば手元の dist-info の配る名で
   問う。転送は https の公の host の名にだけ付いていく（webget.SafeRedirect）
どこからも取れなかったライブラリは節の頭に名指し、役に自分で引けと言う。
文書はファイルで渡す（持ち主 2026-10-09）: 取れた文書は、ライブラリごとに今の周の置き場 libdocs/<名>@<版>/ に丸ごと書き
（手元は local-<digest>.md、公式は 1 本ずつ official-<番>-<種>.md）、節にはライブラリごとの名・入っている版・出どころ・ファイルのパスと、
安く取れる要点（単位が使う名・公式の README の頭の 1 行）だけを並べる。本文は貼らず、量の上限も持たない（前の版の 4000 トークンの
上限は、Context7 の口が tokens を求め、本文を指示書に貼っていたから在った）。役は API の詳細が要る時にそのファイルを Read で読む。
読むべき物（reads の must）には数えないので、読まなくても読んだ証拠の欠けにならない。

見つけ方（detect）: 単位のファイルの import（Python は impact.py_imports、JS/TS は import・require の字）から、標準ライブラリ
（sys.stdlib_module_names・node の組み込み）と作業ツリーで定義された物（相対の import・作業ツリーのどこかに同じ名の .py・パッケージのフォルダ・JS は package.json の name）を除いた物。
版は根の依存の宣言（pyproject.toml・requirements*.txt・package.json）から引く。宣言のファイル自体が単位なら、宣言の全部が対象。
行の uses は単位が使う名（from の名と import した名の属性。libdocs_local.py_uses・js_uses）で、手元の版の読む名を選び、節にも並べる
（役がファイルの中を探す手がかり）。

口（標準ライブラリだけ。網は get で差し替える。期限は足さない——節の宣言の 20 日だけ）:
- detect(repo, files) -> {libs, counts, unreadable}
- unit_files(repo, judgment_file, keys=None) -> (files, why): 判定の単位の字に現れる追跡中の file（impact.seeds_from_units）
- section(board, repo, files, *, get=None, env=None, now=None) -> str: 指示書に貼る節（文書のファイルの一覧）。公式の取れた物と見つからない
  物は盤面の今の周の置き場 libdocs/<名>@<版>.official.json に控え（board.work）、前の周の控えも読む（同じ run の中は網に出ない）。
  取れなかった物・見つからない物・上限で取らない物・読めない file・手元に入っていない物は節の頭に数と名前で書く（黙って落とさない）。
  WORKS_LIBDOCS_WEB=off は網に出ない（公式を引かない。手元は読む）
- run をまたぐ控え（env に包みの家 webget.SHARED_ENV が在る時だけ。置き場の理由は webget の頭、長さの理由は定数の注記。読み書きは
  core の webget.Store）: 公式の
  取れた物と見つからない物を、取った時刻と一緒に <包みの家>/libdocs/ にも書き、同じ家の後の run は SHARED_TTL（7 日）の内なら網に出ずに使う（盤面の今の周にも写す）。
  前の版が同じ置き場に残した Context7 の控え（<名>@<版>.json・<名>@<版>-<問いの digest>.json・枠切れの印 _quota.json）は、名が
  公式の控えの名（尾 OFFICIAL_SUFFIX）と違うので読まない（消しもしない）
"""
import hashlib
import json
import os
import pathlib
import re
import sys
import tempfile
import time

import impact
import libdocs_local
import libdocs_web
import scopes
import webget

ENV_SWITCH = "WORKS_LIBDOCS_WEB"       # off で網に出ない（出ないことを節に書く）
MAX_LIBS = 8                           # 1 回に引くライブラリの数の上限（超えた物は名前で言う）
TITLE = "## ライブラリの文書（手元の版・公式）"
CACHE_DIR = "libdocs"                  # 盤面の周の置き場の下の控えと文書のファイル（run をまたぐ控えも同じ名の置き場）
# ライブラリごとの置き場の下の、手元の版の署名と説明のファイルの名（local-<中身の sha256 の頭 8 桁>.md）。中身は単位が使う名で
# 変わり、並べの枝（同じ周の置き場を分け合う）が別の単位で同じライブラリを書くので、中身で名を分けて互いに上書きしない
LOCAL_FILE = "local-{digest}.md"
SUMMARY_MAX = 160                      # 公式の要約の 1 行の字数の上限
# 控えを使う長さ: 7 日。版を指した控え（<名>@<版>.official.json）の中身はその版の文書で、版が替われば名も替わる。版の無い控え（@any）は
# 今の文書なので古びるが、1 日に何本も回す run の間で使い回せば同じ問いを繰り返さずに済み、週ごとに取り直せば古びは 1 週に収まる
SHARED_TTL = 7 * 24 * 3600
RECORD = "libdocs.json"                # 今の周の見つけた物と取れた物の控え
OFFICIAL_SUFFIX = ".official.json"     # 公式の文書の控えの名の尾（<名>@<版>.official.json。名と版だけで引く）
MAX_BODY = 4 * 1024 * 1024             # 網の答え 1 本を読む上限（バイト。llms-full.txt は大きい物がある）
SCHEMA = "works-libdocs/1"
PY_SUFFIXES = frozenset({".py", ".pyi"})
JS_SUFFIXES = frozenset({".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs"})
MANIFESTS = ("pyproject.toml", "package.json")
REQ_RE = re.compile(r"requirements[^/]*\.txt$")
# 輸入の名と配る名が違う物（よく出る物だけ。当たらなければ輸入の名のまま引き、版の分からない物として数える）
PY_DIST = {"yaml": "pyyaml", "bs4": "beautifulsoup4", "PIL": "pillow", "sklearn": "scikit-learn",
           "cv2": "opencv-python", "dateutil": "python-dateutil", "dotenv": "python-dotenv", "jwt": "pyjwt"}
NODE_BUILTINS = frozenset({
    "assert", "async_hooks", "buffer", "child_process", "cluster", "console", "crypto", "dgram", "dns", "domain", "events",
    "fs", "http", "http2", "https", "inspector", "module", "net", "os", "path", "perf_hooks", "process", "punycode",
    "querystring", "readline", "repl", "stream", "string_decoder", "timers", "tls", "tty", "url", "util", "v8", "vm",
    "wasi", "worker_threads", "zlib"})
JS_IMPORT = re.compile(r"""(?:\bfrom\s*|\bimport\s*\(?\s*|\brequire\s*\(\s*)['"]([^'"\n]+)['"]""")
PEP508 = re.compile(r"^\s*([A-Za-z0-9][A-Za-z0-9._-]*)\s*(?:\[[^\]]*\])?\s*(.*)$")
EXACT = re.compile(r"===?\s*v?([0-9][0-9A-Za-z.+-]*)")
LOWER = re.compile(r"(?:>=|~=|\^|~|>)\s*v?([0-9][0-9A-Za-z.+-]*)")
BARE = re.compile(r"^v?([0-9][0-9A-Za-z.+-]*)$")


# ---------------------------------------------------------------- 見つける
def _norm(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def _version(spec) -> str | None:
    """依存の宣言の字から版（== は その版、^・~・>=・~= は下の端、字だけの版はそのまま）。分からなければ None"""
    if not isinstance(spec, str):
        return None
    s = spec.split(";", 1)[0].strip()
    for rx in (EXACT, LOWER, BARE):
        m = rx.search(s)
        if m:
            return m.group(1).rstrip(".")
    return None


def _pep508(line: str):
    m = PEP508.match(line.split("#", 1)[0])
    return (m.group(1), _version(m.group(2))) if m else None


def manifests(repo: pathlib.Path) -> tuple:
    """根の依存の宣言 → ({配る名の正規形: {name, version, manifest}}, 読めない宣言 [{path, reason}])"""
    repo = pathlib.Path(repo)
    deps, bad = {}, []

    def put(name, version, where):
        deps.setdefault(_norm(name), {"name": name, "version": version, "manifest": where})
    for p in sorted(repo.iterdir()) if repo.is_dir() else []:
        if not p.is_file():
            continue
        try:
            if p.name == "pyproject.toml":
                import tomllib
                doc = tomllib.loads(p.read_text(encoding="utf-8"))
                proj = doc.get("project") or {}
                for line in list(proj.get("dependencies") or []) + [x for v in (proj.get("optional-dependencies") or {}).values()
                                                                   for x in v]:
                    got = _pep508(line)
                    if got:
                        put(*got, p.name)
                for name, spec in ((doc.get("tool") or {}).get("poetry") or {}).get("dependencies", {}).items():
                    if name != "python":
                        put(name, _version(spec.get("version") if isinstance(spec, dict) else spec), p.name)
            elif REQ_RE.fullmatch(p.name):
                for line in p.read_text(encoding="utf-8").splitlines():
                    if line.strip() and not line.lstrip().startswith(("#", "-")):
                        got = _pep508(line)
                        if got:
                            put(*got, p.name)
            elif p.name == "package.json":
                doc = json.loads(p.read_text(encoding="utf-8"))
                for key in ("dependencies", "devDependencies", "peerDependencies", "optionalDependencies"):
                    for name, spec in (doc.get(key) or {}).items():
                        put(name, _version(spec), p.name)
        except (OSError, ValueError, ImportError, AttributeError, TypeError) as e:
            bad.append({"path": p.name, "reason": f"{type(e).__name__}: {e}"[:200]})
    return deps, bad


def _js_package(spec: str) -> str:
    parts = spec.split("/")
    return "/".join(parts[:2]) if spec.startswith("@") and len(parts) > 1 else parts[0]


SKIP_DIRS = frozenset({".git", "node_modules", ".venv", "venv", "__pycache__", ".tox", "dist", "build"})


def _tree_files(repo: pathlib.Path) -> list:
    """作業ツリーの file（impact.tree_files の一覧。git が使えなければ置き場の走査）。repo からの相対（/ 区切り）"""
    listed = impact.tree_files(repo)
    if listed is not None:
        return listed
    out = []
    for root, dirs, names in os.walk(repo):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        out += [pathlib.Path(root, n).relative_to(repo).as_posix() for n in names]
    return out


def _own_names(repo: pathlib.Path) -> dict:
    """作業ツリーで定義された名前。{python: {import できる最上位の名}, js: {package.json の name}}"""
    files = _tree_files(repo)
    pkgs = {str(pathlib.PurePosixPath(f).parent) for f in files if pathlib.PurePosixPath(f).name == "__init__.py"}
    py, js = set(), set()
    for f in files:
        path = pathlib.PurePosixPath(f)
        if path.suffix in PY_SUFFIXES:
            py.add(path.stem)
            if len(path.parts) > 1 and path.parts[0] != "src":
                py.add(path.parts[0])           # 根の下の名前空間の置き場
            elif len(path.parts) > 2:
                py.add(path.parts[1])
        elif path.name == "package.json":
            try:
                name = json.loads((repo / f).read_text(encoding="utf-8")).get("name")
            except (OSError, ValueError, AttributeError):
                continue
            if isinstance(name, str) and name:
                js.add(name)
    py |= {pathlib.PurePosixPath(d).name for d in pkgs
           if d != "." and str(pathlib.PurePosixPath(d).parent) not in pkgs}
    py.discard("__init__")
    return {"python": py, "js": js}


def detect(repo, files) -> dict:
    """単位のファイルが使うライブラリ。返り {libs: {鍵: {name, search, version, manifest, uses, lang, files, via}},
    counts: {files, stdlib, local, imports, manifest}, unreadable: [{path, reason}]}"""
    repo = pathlib.Path(repo)
    deps, bad = manifests(repo)
    own = _own_names(repo)
    libs, unreadable = {}, list(bad)
    counts = {"files": 0, "stdlib": 0, "local": 0, "imports": 0, "manifest": 0}
    stdlib = set(getattr(sys, "stdlib_module_names", ())) | {"__future__"}

    def add(key, lang, path, dist=None, via="import", uses=()):
        d = deps.get(_norm(dist or key))
        row = libs.setdefault(key, {"name": key, "search": d["name"] if d else (dist or key),
                                    "version": d["version"] if d else None, "manifest": d["manifest"] if d else None,
                                    "uses": [], "lang": lang, "files": [], "via": via})
        for u in uses:
            if u not in row["uses"]:
                row["uses"].append(u)
        if path not in row["files"]:
            row["files"].append(path)
    for rel in dict.fromkeys(str(f) for f in files):
        p = repo / rel
        name = pathlib.PurePosixPath(rel).name
        suffix = pathlib.PurePosixPath(rel).suffix
        if not (suffix in PY_SUFFIXES or suffix in JS_SUFFIXES or name in MANIFESTS or REQ_RE.fullmatch(name)):
            continue
        counts["files"] += 1
        try:
            text = p.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as e:
            unreadable.append({"path": rel, "reason": type(e).__name__})
            continue
        if name in MANIFESTS or REQ_RE.fullmatch(name):
            if rel != name:           # 根の宣言だけを読む（deps も根の物だけ）
                unreadable.append({"path": rel, "reason": "根でない依存の宣言は読まない"})
            else:
                for d in deps.values():
                    if d["manifest"] == name and d["name"] not in own["js" if name == "package.json" else "python"]:
                        counts["manifest"] += 1
                        add(d["name"], "js" if name == "package.json" else "python", rel, dist=d["name"], via="manifest")
            continue
        if suffix in PY_SUFFIXES:
            imports = impact.py_imports(text)
            if imports is None:
                unreadable.append({"path": rel, "reason": "Python の構文の誤り"})
                continue
            uses = libdocs_local.py_uses(text) or {}
            for mod, level, _line, _text, _names in imports:
                counts["imports"] += 1
                top = (mod or "").split(".")[0]
                if level or not top:
                    counts["local"] += 1
                elif top in stdlib:
                    counts["stdlib"] += 1
                elif top in own["python"]:
                    counts["local"] += 1
                else:
                    add(top, "python", rel, dist=PY_DIST.get(top), uses=uses.get(top, ()))
            continue
        uses = libdocs_local.js_uses(text)
        for spec in dict.fromkeys(m.group(1) for m in JS_IMPORT.finditer(text)):
            counts["imports"] += 1
            if spec.startswith((".", "/", "~/", "@/")) or _js_package(spec) in own["js"]:
                counts["local"] += 1
            elif spec.startswith("node:") or spec.split("/")[0] in NODE_BUILTINS:
                counts["stdlib"] += 1
            else:
                add(_js_package(spec), "js", rel, uses=uses.get(_js_package(spec), ()))
    return {"libs": libs, "counts": counts, "unreadable": unreadable}


def unit_files(repo, judgment_file, keys=None) -> tuple:
    """判定の単位（keys が在ればその key の物だけ）の字に現れる追跡中の file。(file の一覧, 読めない理由)"""
    try:
        doc = json.loads(pathlib.Path(judgment_file).read_text(encoding="utf-8"))
        units = [u for u in (doc.get("units") or []) if isinstance(u, dict) and (keys is None or u.get("key") in keys)]
        return impact.seeds_from_units(repo, units), ""
    except Exception as e:  # noqa: BLE001  読めない理由は節に出す（落とさない）
        return [], f"単位のファイルを引けない（{type(e).__name__}: {e}）"[:300]




# ---------------------------------------------------------------- 引く
def http_get(url: str, headers: dict) -> tuple:
    """既定の網の口 get(url, headers): webget.http_get を MAX_BODY で呼ぶ（転送・誤りの扱いは webget。期限は足さない）"""
    return webget.http_get(url, headers, MAX_BODY)


# ---------------------------------------------------------------- 控え
def _cached(board, name: str, statuses=("ok", "not_found")):
    """一番新しい周の控え（scopes.all_rounds。scope の根に分かれた物も見る）"""
    for p in reversed(scopes.all_rounds(pathlib.Path(board.dir), f"{CACHE_DIR}/{name}")):
        try:
            doc = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(doc, dict) and doc.get("schema") == SCHEMA and doc.get("status") in statuses:
            return doc
    return None


def _official_name(lib: dict) -> str:
    """公式の文書の控えの名（盤面の周・包みの家）: ライブラリの名と版だけ（公式の問いは名と版しか持たない）"""
    return _lib_dir(lib) + OFFICIAL_SUFFIX


def _official(board, lib: dict, get, store, now: float, keep, share) -> tuple:
    """公式の文書（盤面の控え → 家の控え store → 網の順）。(控えの形の dict, 出どころ board|shared|net)。取れた物と見つからない物だけ控える"""
    name = _official_name(lib)
    got = _cached(board, name)
    if got is not None:
        return got, "board"
    got = store.get(name, now, ("ok", "not_found"))
    if got is not None:
        keep(name, got)
        return got, "shared"
    got = {"schema": SCHEMA, "source": "official", "lib": {"name": lib["name"], "version": lib["version"]},
           **libdocs_web.fetch(lib, lib["version"], get), "at": now}
    if got["status"] in ("ok", "not_found"):
        keep(name, got)
        share(name, got)
    return got, "net"


# ---------------------------------------------------------------- ファイル
def _lib_dir(lib: dict) -> str:
    """ライブラリごとの文書の置き場の名（<名>@<版>。版が分からなければ @any）"""
    return re.sub(r"[^A-Za-z0-9._@-]", "_", f"{lib['name']}@{lib['version'] or 'any'}")


def _local_text(lib: dict, local: dict) -> str:
    head = [f"# {lib['search']} {local.get('version') or lib['version'] or '（版不明）'}（手元の版。import せずに読んだ署名と説明）",
            f"置き場: {local.get('where') or ''}"]
    return "\n\n".join(["\n".join(head)] + [f"## {f['title']}\n出典: {f['source'] or '（無し）'}\n\n{f['text']}".rstrip()
                                             for f in local.get("fragments") or []]) + "\n"


def _summary(docs) -> str:
    """公式の文書の頭の、見出し・バッジ・HTML でない最初の 1 行（SUMMARY_MAX 字まで）。無ければ空"""
    for d in docs or []:
        for line in (d.get("text") or "").splitlines():
            s = line.strip()
            if s and not s.startswith(("#", "<", "[", "!", "```", "=", "-", ">", "|")):
                return s if len(s) <= SUMMARY_MAX else s[:SUMMARY_MAX - 1] + "…"
    return ""


def _write(path: pathlib.Path, text: str) -> None:
    """一時のファイルに書いて置き換える（並べの枝が同じ名を同時に書いても、読む役は書きかけを見ない）"""
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".tmp-", suffix=path.suffix)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def _save(board, lib: dict, local: dict, official: dict) -> dict:
    """取れた文書を今の周の libdocs/<名>@<版>/ に丸ごと書く。返り {local: パス|None, official: [(URL, 種, パス, 字数)]}。
    公式のファイルの名は番と種だけ（中身は名と版で決まる）、手元のファイルの名は中身の digest（LOCAL_FILE）"""
    base = f"{CACHE_DIR}/{_lib_dir(lib)}"
    out = {"local": None, "official": []}
    if local.get("status") == "ok" and local.get("fragments"):
        text = _local_text(lib, local)
        p = board.work(f"{base}/" + LOCAL_FILE.format(digest=hashlib.sha256(text.encode("utf-8")).hexdigest()[:8]))
        _write(p, text)
        out["local"] = p
    if official.get("status") == "ok":
        for n, d in enumerate(official.get("docs") or [], 1):
            kind = re.sub(r"[^a-z0-9-]", "_", str(d.get("kind") or "doc"))
            p = board.work(f"{base}/official-{n}-{kind}.md")
            _write(p, f"<!-- 出典: {d.get('url') or ''} -->\n{d.get('text') or ''}")
            out["official"].append((d.get("url") or "", kind, p, len(d.get("text") or "")))
    return out


def _render(rows: list) -> list:
    """文書のファイルが在るライブラリごとの段（名・版・出どころ・ファイルのパス・要点）"""
    parts = []
    for r in rows:
        saved = r["saved"]
        if not (saved["local"] or saved["official"]):
            continue
        lib = r["lib"]
        block = [f"### {lib['search']} {lib['version'] or '（版の宣言なし）'}"]
        if lib.get("uses"):
            block.append("- 単位が使う名: " + "、".join(lib["uses"][:8]) + (" ほか" if len(lib["uses"]) > 8 else ""))
        if saved["local"]:
            n = len(r["local"].get("fragments") or [])
            block.append(f"- 手元の版: {r['local'].get('where') or ''} → {saved['local']}（署名と説明 {n} 件）")
        for url, kind, path, chars in saved["official"]:
            block.append(f"- 公式: {url} → {path}（{'README' if kind == 'readme' else kind}・{chars} 字）")
        summary = _summary(r["official"].get("docs")) if saved["official"] else ""
        if summary:
            block.append(f"- 公式の要約: {summary}")
        parts.append("\n".join(block))
    return parts


def _names(rows, pick) -> str:
    return "、".join(pick(r) for r in rows)


def _count(label: str, rows: list, pick) -> str:
    """「<label> N 本（名、名）」（0 本なら括弧なし）"""
    return f"{label} {len(rows)} 本" + (f"（{_names(rows, pick)}）" if rows else "")


def section(board, repo, files, *, get=None, env=None, now: float | None = None) -> str:
    """指示書に貼る節（TITLE で始まる）。組めない時も節を返し、理由を書く。now は run をまたぐ控えの時刻の比べ（既定は今）"""
    env = os.environ if env is None else env
    get = http_get if get is None else get
    now = time.time() if now is None else now
    try:
        return _section(board, repo, files, get, env, now)
    except Exception as e:  # noqa: BLE001  組めなかったことは節に書く（黙って落とさない）
        return f"{TITLE}\n\n組めなかった（{type(e).__name__}: {e}）。この節の文書は無い。"[:1000]


HEAD = ("機械が、この単位のファイルが使うライブラリの文書を 2 つの出どころから取り、盤面にファイルで丸ごと控えた（本文はここに"
        "貼っていない。ライブラリごとに下の段に名・版・出どころ・ファイルのパスを並べた）: "
        "(1) 手元の版——run の作業ツリーか同じリポジトリの main の作業ツリーに入っている版のコードを、import せずに読んだ署名と"
        "説明（入っている版のコードそのもの） (2) 公式——ライブラリの持ち主の文書（PyPI・npm の README、docs の場所の llms.txt。"
        "版を合わせられる物は合わせた）。API の署名・引数・使い方が要る時は、そのライブラリのファイルを Read で読め（読むかは"
        "要るかで決めてよい。単位が使う名で探せ）。下の「どこからも文書が無い」のライブラリと、ここで足りない所は "
        "WebSearch・WebFetch で公式の文書を自分で引け。")


def _section(board, repo, files, get, env, now) -> str:
    head = [TITLE, "", HEAD]
    if repo is None:
        return "\n".join(head + ["", "対象のリポジトリが渡されていないので、ライブラリを見つけられない（0 本）。"])
    det = detect(pathlib.Path(repo), files)
    c, libs = det["counts"], det["libs"]
    unread = (f"／読めないファイル {len(det['unreadable'])} 本（"
              + _names(det["unreadable"], lambda u: f"{u['path']}: {u['reason']}") + "）") if det["unreadable"] else ""
    if not libs:
        return "\n".join(head + ["", f"単位のファイル {c['files']} 本の import は標準ライブラリとリポジトリの中の物だけ"
                                     f"（標準 {c['stdlib']}・リポジトリの中 {c['local']}）。ライブラリの文書を取る物は無い（0 本）{unread}。"])
    keys = sorted(libs)
    off = webget.is_off(env, ENV_SWITCH)
    take, over = keys[:MAX_LIBS], keys[MAX_LIBS:]
    rows, unshared = [], []
    official_from = {"board": 0, "shared": 0, "net": 0}
    store = webget.Store(webget.shared_root(env, CACHE_DIR), SCHEMA, SHARED_TTL)
    roots = libdocs_local.roots(pathlib.Path(repo))

    def keep(name, doc):
        board.work(f"{CACHE_DIR}/{name}").write_text(json.dumps(doc, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")

    def share(name, doc):
        why = store.put(name, doc)
        if why:
            unshared.append(why)
    for k in take:
        lib = libs[k]
        # 1. 手元の版（網に出ない。off でも読む）。読めた版を以後の版にする（宣言の版は下の端のことがある）
        local = libdocs_local.read(roots, lib, lib["files"])
        if local["status"] == "ok" and local["version"] and local["version"] != lib["version"]:
            lib = {**lib, "version": local["version"], "declared": lib["version"]}
        # 輸入の名と配る名が違い（import serial・配る名 pyserial）宣言にも PY_DIST にも無い時は、手元の配る名で問う（輸入の名で問うと
        # registry の別のプロジェクトを公式として貼る）
        if local["status"] == "ok" and local.get("dist") and _norm(local["dist"]) != _norm(lib["search"]):
            lib = {**lib, "search": local["dist"]}
        # 2. 公式の文書
        if off:
            official = {"status": "off", "docs": [], "error": "", "note": ""}
        else:
            official, origin = _official(board, lib, get, store, now, keep, share)
            official_from[origin] += 1 if official["status"] == "ok" else 0
        rows.append({"lib": lib, "local": local, "official": official, "saved": _save(board, lib, local, official)})
    by_local = {st: [r for r in rows if r["local"]["status"] == st] for st in ("ok", "absent", "error")}
    by_official = {st: [r for r in rows if r["official"]["status"] == st] for st in ("ok", "not_found", "error")}
    none = [r for r in rows if not (r["saved"]["local"] or r["saved"]["official"])]
    parts = _render(rows)
    saved = sum((1 if r["saved"]["local"] else 0) + len(r["saved"]["official"]) for r in rows)
    name = lambda r: r["lib"]["search"]  # noqa: E731
    nums = (f"数: 見つけた {len(keys)} 本（単位のファイル {c['files']} 本の import {c['imports']}・宣言 {c['manifest']}。"
            f"標準 {c['stdlib']}・リポジトリの中 {c['local']} は除いた）／上限 {MAX_LIBS} 本を超えて取らない {len(over)} 本{unread}")
    lines = head + ["", nums, "- 手元の版: " + "／".join((
        _count("読めた", by_local["ok"], lambda r: f"{name(r)} {r['local']['version'] or '版不明'}"),
        _count("入っていない", by_local["absent"], name),
        _count("読めなかった", by_local["error"], lambda r: f"{name(r)}: {r['local']['note']}")))]
    if off:
        lines.append(f"- 公式の文書: {ENV_SWITCH}=off なので網に出ない（引かない。見つけたライブラリ {len(keys)} 本: {'、'.join(keys)}）")
    else:
        lines.append("- 公式の文書: " + "／".join((
            _count("取れた", by_official["ok"], name),
            f"控えから {official_from['board'] + official_from['shared']} 本（盤面 {official_from['board']} 本・"
            f"ほかの run {official_from['shared']} 本）",
            _count("見つからない", by_official["not_found"], name),
            _count("取れなかった", by_official["error"], lambda r: f"{name(r)}: {r['official']['error']}"))))
    lines.append(f"控えたファイル {saved} 本（ライブラリごとの下の段にパス）")
    if none:
        why = f"網には出ていない（{ENV_SWITCH}=off）" if off else "公式から取れなかった"
        lines.append(f"- どこからも文書が無い: {_names(none, name)}（手元に入っていない。{why}。"
                     "WebSearch・WebFetch で公式の文書を自分で引け）")
    for r in rows:
        if r["lib"].get("declared") and r["lib"]["declared"] != r["lib"]["version"]:
            lines.append(f"- 手元の版の注: {name(r)}: 宣言の版 {r['lib']['declared']} と入っている版 {r['lib']['version']} が違う"
                         "（入っている版で引いた）")
        if r["local"]["status"] == "ok" and r["local"].get("note"):
            lines.append(f"- 手元の版の注: {name(r)}: {r['local']['note']}")
        if r["official"].get("note"):
            lines.append(f"- 公式の文書の注: {name(r)}: {r['official']['note']}")
    if over:
        lines.append("- 上限を超えて取らない: " + "、".join(over))
    if unshared:
        lines.append("- run をまたぐ控えに書けなかった（次の run は取り直す）: " + "、".join(unshared))
    record = board.work(RECORD)
    record.write_text(json.dumps({"schema": SCHEMA, "detect": det, "rows": [_record_row(r) for r in rows], "over": over},
                                 ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    lines.append(f"- 控え: {record}")
    return "\n".join(lines + ([""] + parts if parts else []))


def _record_row(r: dict) -> dict:
    """libdocs.json の行: 見つけた物と出どころごとの結果（文書の字は載せない。手元は読んだ版と置き場、断片は名と出典だけ）"""
    local = r["local"]
    return {"lib": r["lib"],
            "files": [str(p) for p in ([r["saved"]["local"]] if r["saved"]["local"] else [])
                      + [x[2] for x in r["saved"]["official"]]],
            "local": {**{k: v for k, v in local.items() if k != "fragments"},
                      "fragments": [{"title": f["title"], "source": f["source"]}
                                    for f in local.get("fragments") or []]},
            "official": {**{k: v for k, v in r["official"].items() if k not in ("docs", "lib")},
                         "docs": [{"kind": d.get("kind"), "url": d.get("url"), "chars": len(d.get("text") or "")}
                                  for d in r["official"].get("docs") or []]}}
