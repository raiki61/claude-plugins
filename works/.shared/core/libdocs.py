"""ライブラリの今の文書（Context7）を機械が引き、指示書に貼る節を組む。層 L3（共有）。

持ち主 2026-09-28「Context7 を使っていこう。機械で渡してくれるんだよね」。役が自分で引く口（Context7 の MCP）とは別に、
支度の script の節（Claude の sandbox の外）が、単位が使うライブラリの文書を先に取って指示書に入れる。

Context7 の口（2026-09-28 に https://context7.com/docs/api-guide で確かめた。報告に引用）:
- GET https://context7.com/api/v2/libs/search?libraryName=<名>&query=<問い> → {results: [{id, title, versions, …}]}
- GET https://context7.com/api/v2/context?libraryId=<id>[/<版>]&query=<問い>&type=json → {codeSnippets, infoSnippets}
  （断片ごとに codeTokens・contentTokens を持つので、貼る量はその数で数える）
- 認証は `Authorization: Bearer <鍵>`（env の CONTEXT7_API_KEY。無ければ鍵なしの低い上限で回す。OpenAPI の security は {} も許す）
- 問い（query）は Context7 に貯められ、並べ替えに LLM へ渡される（Data Privacy）。だから問いには対象のコードの字を載せず、
  ライブラリの名と、そのライブラリから import した名（公開の API の名）だけを書く

見つけ方（detect）: 単位のファイルの import（Python は impact.py_imports、JS/TS は import・require の字）から、標準ライブラリ
（sys.stdlib_module_names・node の組み込み）と作業ツリーで定義された物（相対の import・作業ツリーのどこかに同じ名の .py・パッケージのフォルダ・JS は package.json の name）を除いた物。
版は根の依存の宣言（pyproject.toml・requirements*.txt・package.json）から引く。宣言のファイル自体が単位なら、宣言の全部が対象。

口（標準ライブラリだけ。網は get で差し替える。期限は足さない——節の宣言の 20 日だけ）:
- detect(repo, files) -> {libs, counts, unreadable}
- unit_files(repo, judgment_file, keys=None) -> (files, why): 判定の単位の字に現れる追跡中の file（impact.seeds_from_units）
- notice(board) -> str | None: 429（枠切れ）の印が盤面に在れば人に見せる 1 行（報告の冒頭 report.head_entry が使う）。無ければ None
- section(board, repo, files, *, get=None, env=None, budget=BUDGET) -> str: 指示書に貼る節。取れた物は盤面の今の周の
  置き場 libdocs/<名>@<版>.json に控え（board.work）、前の周の控えも読む（同じ run の中は網に出ない）。枠切れ（429）で取らなかった物（1 本受けたら以後は問い合わせず、
  節の TITLE の次の行にも書く）・取れなかった物・Context7 に無い物・版の合わない物・上限で取らない物・読めない file は節の頭に数と名前で書く（黙って落とさない）
"""
import json
import os
import pathlib
import re
import sys
import urllib.error
import urllib.parse
import urllib.request

import impact

API = "https://context7.com/api"
ENV_KEY = "CONTEXT7_API_KEY"
ENV_SWITCH = "WORKS_CONTEXT7"          # off で網に出ない（出ないことを節に書く）
BUDGET = 4000                          # 節に貼る断片の量の上限（Context7 の codeTokens・contentTokens の和）
MAX_LIBS = 8                           # 1 回に引くライブラリの数の上限（超えた物は名前で言う）
TITLE = "## ライブラリの今の文書（Context7）"
CACHE_DIR = "libdocs"                  # 盤面の周の置き場の下の控え
RECORD = "libdocs.json"                # 今の周の見つけた物と取れた物の控え
SCHEMA = "works-libdocs/1"
QUERY_MAX = 500                        # Context7 の query の上限（OpenAPI の maxLength）
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
JS_NAMED = re.compile(r"""\bimport\s*\{([^}]*)\}\s*from\s*['"]([^'"\n]+)['"]""")
PEP508 = re.compile(r"^\s*([A-Za-z0-9][A-Za-z0-9._-]*)\s*(?:\[[^\]]*\])?\s*(.*)$")
EXACT = re.compile(r"===?\s*v?([0-9][0-9A-Za-z.+-]*)")
LOWER = re.compile(r"(?:>=|~=|\^|~|>)\s*v?([0-9][0-9A-Za-z.+-]*)")
BARE = re.compile(r"^v?([0-9][0-9A-Za-z.+-]*)$")


class FetchError(Exception):
    """網に届かない・答えが読めない（文は 1 行）"""


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
    """単位のファイルが使うライブラリ。返り {libs: {鍵: {name, search, version, manifest, symbols, lang, files, via}},
    counts: {files, stdlib, local, imports, manifest}, unreadable: [{path, reason}]}"""
    repo = pathlib.Path(repo)
    deps, bad = manifests(repo)
    own = _own_names(repo)
    libs, unreadable = {}, list(bad)
    counts = {"files": 0, "stdlib": 0, "local": 0, "imports": 0, "manifest": 0}
    stdlib = set(getattr(sys, "stdlib_module_names", ())) | {"__future__"}

    def add(key, lang, path, symbols=(), dist=None, via="import"):
        d = deps.get(_norm(dist or key))
        row = libs.setdefault(key, {"name": key, "search": d["name"] if d else (dist or key),
                                    "version": d["version"] if d else None, "manifest": d["manifest"] if d else None,
                                    "symbols": [], "lang": lang, "files": [], "via": via})
        for s in symbols:
            if s not in row["symbols"] and s != "*":
                row["symbols"].append(s)
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
            for mod, level, _line, _text, names in imports:
                counts["imports"] += 1
                top = (mod or "").split(".")[0]
                if level or not top:
                    counts["local"] += 1
                elif top in stdlib:
                    counts["stdlib"] += 1
                elif top in own["python"]:
                    counts["local"] += 1
                else:
                    add(top, "python", rel, names if mod == top else (), dist=PY_DIST.get(top))
            continue
        named = {}
        for m in JS_NAMED.finditer(text):
            named.setdefault(m.group(2), []).extend(
                w.split(" as ")[0].strip() for w in m.group(1).split(",") if w.strip())
        for spec in dict.fromkeys(m.group(1) for m in JS_IMPORT.finditer(text)):
            counts["imports"] += 1
            if spec.startswith((".", "/", "~/", "@/")) or _js_package(spec) in own["js"]:
                counts["local"] += 1
            elif spec.startswith("node:") or spec.split("/")[0] in NODE_BUILTINS:
                counts["stdlib"] += 1
            else:
                add(_js_package(spec), "js", rel, named.get(spec, ()))
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
    """(状態の番号, 本文)。網に届かなければ FetchError。期限は足さない（節の宣言だけ）"""
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req) as r:  # noqa: S310  宛先は定数の API だけ
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read() or b""
    except (urllib.error.URLError, OSError, ValueError) as e:
        raise FetchError(f"{type(e).__name__}: {e}"[:200]) from None


def _query(lib: dict) -> str:
    q = f"{lib['search']} usage and API reference"
    if lib["symbols"]:
        q += ": " + ", ".join(lib["symbols"][:8])
    return q[:QUERY_MAX]


def _call(get, path: str, params: dict, headers: dict) -> tuple:
    status, body = get(f"{API}{path}?{urllib.parse.urlencode(params)}", headers)
    try:
        doc = json.loads(body.decode("utf-8")) if body else {}
    except (ValueError, UnicodeDecodeError):
        doc = None
    return status, doc


def _why(status, doc) -> str:
    if isinstance(doc, dict) and (doc.get("error") or doc.get("message")):
        return f"HTTP {status}: {doc.get('error') or ''} — {doc.get('message') or ''}".strip()[:200]
    return f"HTTP {status}"


def _vnorm(v: str) -> str:
    return v[1:] if v[:1] in "vV" else v


def _snippets(doc: dict) -> list:
    out = []
    for s in doc.get("codeSnippets") or []:
        code = "\n\n".join(f"```{c.get('language') or ''}\n{c.get('code') or ''}\n```" for c in s.get("codeList") or [])
        text = "\n".join(x for x in (s.get("codeDescription") or "", code) if x)
        out.append({"title": s.get("codeTitle") or s.get("pageTitle") or "", "source": s.get("codeId") or "",
                    "tokens": int(s.get("codeTokens") or len(text) // 4), "text": text})
    for s in doc.get("infoSnippets") or []:
        text = s.get("content") or ""
        out.append({"title": s.get("breadcrumb") or "", "source": s.get("pageId") or "",
                    "tokens": int(s.get("contentTokens") or len(text) // 4), "text": text})
    return out


def fetch(lib: dict, get, headers: dict) -> dict:
    """1 本を引く。返り {status: ok|not_found|quota（HTTP 429＝枠切れ）|error, id, version_note, snippets, error}"""
    out = {"status": "error", "id": "", "version_note": "", "snippets": [], "error": ""}
    q = _query(lib)
    try:
        status, doc = _call(get, "/v2/libs/search", {"libraryName": lib["search"], "query": q}, headers)
        if status == 404 or (status == 200 and isinstance(doc, dict) and not doc.get("results")):
            return {**out, "status": "not_found"}
        if status != 200 or not isinstance(doc, dict):
            return {**out, "status": "quota" if status == 429 else "error", "error": _why(status, doc)}
        results = [r for r in doc["results"] if isinstance(r, dict) and r.get("id")]
        want = _norm(lib["search"])
        best = next((r for r in results if _norm(str(r.get("title") or "")) == want
                     or _norm(r["id"].rstrip("/").rsplit("/", 1)[-1]) == want), results[0] if results else None)
        if best is None:
            return {**out, "status": "not_found"}
        lid = best["id"]
        if lib["version"]:
            vs = [v for v in best.get("versions") or [] if isinstance(v, str)]
            hit = next((v for v in vs if _vnorm(v) == lib["version"]), None) or \
                next((v for v in vs if _vnorm(v).startswith(lib["version"] + ".")), None)
            if hit:
                lid = f"{lid}/{hit}"
            else:
                out["version_note"] = (f"{lib['search']} {lib['version']} の版は Context7 に無い（在る版: "
                                       f"{', '.join(vs[:5]) or '無し'}）。版を指さずに引いた")
        status, doc = _call(get, "/v2/context", {"libraryId": lid, "query": q, "type": "json"}, headers)
        if status == 404:
            return {**out, "status": "not_found", "id": lid}
        if status != 200 or not isinstance(doc, dict):
            return {**out, "id": lid, "status": "quota" if status == 429 else "error", "error": _why(status, doc)}
        return {**out, "status": "ok", "id": lid, "snippets": _snippets(doc)}
    except FetchError as e:
        return {**out, "error": str(e)}


# ---------------------------------------------------------------- 節
def _cache_name(lib: dict) -> str:
    return re.sub(r"[^A-Za-z0-9._@-]", "_", f"{lib['name']}@{lib['version'] or 'any'}") + ".json"


def _round_of(p: pathlib.Path) -> int:
    tail = p.parent.parent.name[1:]
    return int(tail) if tail.isdigit() else -1


def _cached(board, name: str):
    for p in sorted(pathlib.Path(board.dir).glob(f"r*/{CACHE_DIR}/{name}"), key=_round_of, reverse=True):
        try:
            doc = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(doc, dict) and doc.get("schema") == SCHEMA and doc.get("status") in ("ok", "not_found"):
            return doc
    return None


QUOTA_MARK = "_quota.json"            # 枠切れ（429）を受けた印。応答の控えでなく run の状態
QUOTA_NOTICE = ("ライブラリの文書は枠切れで取れていない（Context7 が HTTP 429 を返したので、この run では以後問い合わせない）")


def _mark_quota(board, reason: str) -> None:
    board.work(f"{CACHE_DIR}/{QUOTA_MARK}").write_text(
        json.dumps({"schema": SCHEMA, "reason": reason}, ensure_ascii=False) + "\n", encoding="utf-8")


def notice(board) -> str | None:
    """枠切れの印が盤面（どの周でも）に在れば、人にも見せる 1 行。無ければ None"""
    if any(pathlib.Path(board.dir).glob(f"r*/{CACHE_DIR}/{QUOTA_MARK}")):
        return QUOTA_NOTICE
    return None


def _render_docs(rows: list, budget: int) -> tuple:
    """取れた物の断片を量の上限の中で並べる。(本文の段, 貼った数, 使った量, 切った数)"""
    ok = [r for r in rows if r["status"] == "ok"]
    if not ok:
        return [], 0, 0, 0
    per = budget // len(ok)
    parts, shown, used, cut = [], 0, 0, 0
    for r in ok:
        lib = r["lib"]
        parts.append(f"### {lib['search']} {lib['version'] or '（版の宣言なし）'} — Context7 {r['id']}")
        spent = 0
        for s in r["snippets"]:
            if spent + s["tokens"] > per:
                cut += 1
                continue
            spent += s["tokens"]
            shown += 1
            parts.append(f"#### {s['title']}\n出典: {s['source'] or '（無し）'}\n{s['text']}".rstrip())
        used += spent
    return parts, shown, used, cut


def _names(rows, pick) -> str:
    return "、".join(pick(r) for r in rows)


def section(board, repo, files, *, get=None, env=None, budget: int = BUDGET) -> str:
    """指示書に貼る節（TITLE で始まる）。組めない時も節を返し、理由を書く"""
    env = os.environ if env is None else env
    get = http_get if get is None else get
    try:
        text = _section(board, repo, files, get, env, budget)
        flag = notice(board)
        if flag:
            first, _, rest = text.partition("\n")
            text = f"{first}\n{flag}\n{rest}"
        return text
    except Exception as e:  # noqa: BLE001  組めなかったことは節に書く（黙って落とさない）
        return f"{TITLE}\n\n組めなかった（{type(e).__name__}: {e}）。この節の文書は無い。"[:1000]


def _section(board, repo, files, get, env, budget) -> str:
    head = [TITLE, "",
            "機械が Context7（https://context7.com）の HTTP API から取った、この単位のファイルが使うライブラリの今の文書の断片"
            "（出典つき）。Context7 の断片は各ライブラリの持ち主の文書を集めた物で、正しさの保証は無い——根拠にするなら出典を"
            "開いて確かめよ。足りなければ WebSearch・WebFetch で公式の文書を自分で引け。"]
    if repo is None:
        return "\n".join(head + ["", "対象のリポジトリが渡されていないので、ライブラリを見つけられない（0 本）。"])
    det = detect(pathlib.Path(repo), files)
    c, libs = det["counts"], det["libs"]
    unread = (f"／読めないファイル {len(det['unreadable'])} 本（"
              + _names(det["unreadable"], lambda u: f"{u['path']}: {u['reason']}") + "）") if det["unreadable"] else ""
    if not libs:
        return "\n".join(head + ["", f"単位のファイル {c['files']} 本の import は標準ライブラリとリポジトリの中の物だけ"
                                     f"（標準 {c['stdlib']}・リポジトリの中 {c['local']}）。Context7 から取る物は無い（0 本）{unread}。"])
    keys = sorted(libs)
    if str(env.get(ENV_SWITCH, "")).strip().lower() == "off":
        return "\n".join(head + ["", f"{ENV_SWITCH}=off なので取らない（見つけたライブラリ {len(keys)} 本: {'、'.join(keys)}）{unread}。"])
    take, over = keys[:MAX_LIBS], keys[MAX_LIBS:]
    headers = {"User-Agent": "works-libdocs", "Accept": "application/json"}
    if env.get(ENV_KEY):
        headers["Authorization"] = f"Bearer {env[ENV_KEY]}"
    rows, hits = [], 0
    halted = notice(board) is not None
    for k in take:
        lib = libs[k]
        name = _cache_name(lib)
        got = _cached(board, name)
        if got is not None:
            hits += 1
        elif halted:
            got = {"schema": SCHEMA, "lib": lib, "status": "quota", "id": "", "version_note": "", "snippets": [],
                   "error": "問い合わせを飛ばした（この run は枠切れ）"}
        else:
            got = {"schema": SCHEMA, "lib": lib, **fetch(lib, get, headers)}
            if got["status"] in ("ok", "not_found"):
                board.work(f"{CACHE_DIR}/{name}").write_text(json.dumps(got, ensure_ascii=False, indent=1) + "\n",
                                                            encoding="utf-8")
            elif got["status"] == "quota":
                _mark_quota(board, got["error"])
                halted = True
        rows.append({**got, "lib": lib})
    ok = [r for r in rows if r["status"] == "ok"]
    nf = [r for r in rows if r["status"] == "not_found"]
    err = [r for r in rows if r["status"] == "error"]
    quota = [r for r in rows if r["status"] == "quota"]
    vm = [r for r in rows if r.get("version_note")]
    parts, shown, used, cut = _render_docs(rows, budget)
    nums = (f"数: 見つけた {len(keys)} 本（単位のファイル {c['files']} 本の import {c['imports']}・宣言 {c['manifest']}。"
            f"標準 {c['stdlib']}・リポジトリの中 {c['local']} は除いた）／取れた {len(ok)} 本（盤面の控えから {hits} 本）／"
            f"Context7 に無い {len(nf)} 本／枠切れで取らなかった {len(quota)} 本／取れなかった {len(err)} 本／版が合わない {len(vm)} 本／"
            f"上限 {MAX_LIBS} 本を超えて取らない {len(over)} 本{unread}")
    lines = head + ["", nums, f"貼った断片 {shown} 本・{used} トークン（予算 {budget}。切った断片 {cut} 本）"]
    if nf:
        lines.append("- Context7 に無い: " + _names(nf, lambda r: r["lib"]["search"]))
    if quota:
        lines.append("- 枠切れで取らなかった: " + _names(quota, lambda r: f"{r['lib']['search']}（{r['error']}）"))
    if err:
        lines.append("- 取れなかった: " + _names(err, lambda r: f"{r['lib']['search']}（{r['error']}）"))
    for r in vm:
        lines.append(f"- 版が合わない: {r['version_note']}")
    if over:
        lines.append("- 上限を超えて取らない: " + "、".join(over))
    record = board.work(RECORD)
    record.write_text(json.dumps({"schema": SCHEMA, "detect": det, "rows": [
        {k: v for k, v in r.items() if k != "snippets"} for r in rows], "over": over}, ensure_ascii=False, indent=1) + "\n",
        encoding="utf-8")
    lines.append(f"- 控え: {record}")
    return "\n".join(lines + ([""] + parts if parts else []))
