"""ライブラリの文書を 2 つの出どころ（手元の版・公式）から機械が引き、指示書に貼る節を組む。層 L3（共有）。

持ち主 2026-10-08「全部使う」（設計 works/docs/plans/2026-10-08-libdocs-sources.md）。2026-10-09 に持ち主が Context7 をやめると
決めた（3 つめの出どころだった。手元と公式は残す）。役が自分で引く口（WebSearch・WebFetch）とは別に、支度の script の節
（Claude の sandbox の外）が、単位が使うライブラリの文書を先に取って指示書に入れる。出どころは次の順で、どれも登録も鍵も要らない:
1. 手元の版（libdocs_local。網に出ない）: run の作業ツリーと同じ git の main の作業ツリーに入っている .venv・venv・.tox・.nox・
   node_modules の中のライブラリを import せずに読んだ、単位が使う名の署名と説明。読めた版を以後の版にする（宣言の版より正しい）
2. 公式（libdocs_web）: PyPI の README と docs の場所の llms.txt、npm は GitHub の版の tag の README と homepage の llms.txt。
   問いはライブラリの名・版と registry の答えに在った URL だけ。鍵は付けない。輸入の名と配る名が違えば手元の dist-info の配る名で
   問う。転送は https の公の host の名にだけ付いていく（SafeRedirect）
どこからも取れなかったライブラリは節の頭に名指し、役に自分で引けと言う。量は BUDGET を文書の取れたライブラリで割り、1 本の分を
手元 1/2・公式の残り（1/2）で先に分けて、余りを手元 → 公式の順に埋める（_allocate）。手元は入っている版のコードそのもので先に
置き、Context7 の取り分だった 1/4 は公式に寄せた（公式が空なら手元が全部を使える）。

見つけ方（detect）: 単位のファイルの import（Python は impact.py_imports、JS/TS は import・require の字）から、標準ライブラリ
（sys.stdlib_module_names・node の組み込み）と作業ツリーで定義された物（相対の import・作業ツリーのどこかに同じ名の .py・パッケージのフォルダ・JS は package.json の name）を除いた物。
版は根の依存の宣言（pyproject.toml・requirements*.txt・package.json）から引く。宣言のファイル自体が単位なら、宣言の全部が対象。
行の uses は単位が使う名（from の名と import した名の属性。libdocs_local.py_uses・js_uses）で、手元と公式の断片を選ぶのに使う。

口（標準ライブラリだけ。網は get で差し替える。期限は足さない——節の宣言の 20 日だけ）:
- detect(repo, files) -> {libs, counts, unreadable}
- unit_files(repo, judgment_file, keys=None) -> (files, why): 判定の単位の字に現れる追跡中の file（impact.seeds_from_units）
- section(board, repo, files, *, get=None, env=None, budget=BUDGET, now=None) -> str: 指示書に貼る節。公式の取れた物と見つからない
  物は盤面の今の周の置き場 libdocs/<名>@<版>.official.json に控え（board.work）、前の周の控えも読む（同じ run の中は網に出ない）。
  取れなかった物・見つからない物・上限で取らない物・読めない file・手元に入っていない物は節の頭に数と名前で書く（黙って落とさない）。
  WORKS_LIBDOCS_WEB=off は網に出ない（公式を引かない。手元は読む）
- run をまたぐ控え（env の SHARED_ENV が在る時だけ。置き場と長さの理由は定数の注記）: 公式の取れた物と見つからない物を、取った
  時刻と一緒に <包みの家>/libdocs/ にも書き、同じ家の後の run は SHARED_TTL（7 日）の内なら網に出ずに使う（盤面の今の周にも写す）。
  前の版が同じ置き場に残した Context7 の控え（<名>@<版>.json・<名>@<版>-<問いの digest>.json・枠切れの印 _quota.json）は、名が
  公式の控えの名（尾 OFFICIAL_SUFFIX）と違うので読まない（消しもしない）
"""
import json
import os
import pathlib
import re
import sys
import tempfile
import time
import urllib.error
import urllib.request

import impact
import libdocs_local
import libdocs_web
import scopes

ENV_SWITCH = "WORKS_LIBDOCS_WEB"       # off で網に出ない（出ないことを節に書く）
BUDGET = 4000                          # 節に貼る断片の量の上限（断片の tokens の和。手元・公式は字の数の 1/4 で数える）
MAX_LIBS = 8                           # 1 回に引くライブラリの数の上限（超えた物は名前で言う）
TITLE = "## ライブラリの文書（手元の版・公式）"
CACHE_DIR = "libdocs"                  # 盤面の周の置き場の下の控え（run をまたぐ控えも同じ名の置き場）
# run をまたぐ控えの置き場: 包みの家（開発の殻 dev/archon.sh が利用の家ごとに export する WORKS_ADAPTER_HOME）の下の CACHE_DIR。
# 利用の家ごとに分かれ、run を重ねても残り、切符（ticket.py）が役に書かせない場所なので、役が控えを書き換えて後の run の指示書に
# 混ぜることはできない。env に無ければ（包みを外した run・試験）run をまたぐ控えは使わない（盤面の控えだけ）
SHARED_ENV = "WORKS_ADAPTER_HOME"
# 控えを使う長さ: 7 日。版を指した控え（<名>@<版>.official.json）の中身はその版の文書で、版が替われば名も替わる。版の無い控え（@any）は
# 今の文書なので古びるが、1 日に何本も回す run の間で使い回せば同じ問いを繰り返さずに済み、週ごとに取り直せば古びは 1 週に収まる
SHARED_TTL = 7 * 24 * 3600
RECORD = "libdocs.json"                # 今の周の見つけた物と取れた物の控え
OFFICIAL_SUFFIX = ".official.json"     # 公式の文書の控えの名の尾（<名>@<版>.official.json。名と版だけで引く）
MAX_BODY = 4 * 1024 * 1024             # 網の答え 1 本を読む上限（バイト。llms-full.txt は大きい物がある）
# 1 本のライブラリの分の中の、出どころごとの先の取り分（手元 1/2・公式の残り）。余りは手元 → 公式の順に埋める
SOURCES = ("local", "official")
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
class SafeRedirect(urllib.request.HTTPRedirectHandler):
    """転送は libdocs_web.safe_url を通る先（https・公の host の名）にだけ付いていく（ほかは 3xx のまま返す）"""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not libdocs_web.safe_url(newurl):
            return None
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def http_get(url: str, headers: dict) -> tuple:
    """(状態の番号, 本文の頭 MAX_BODY バイトまで)。網に届かなければ FetchError。期限は足さない（節の宣言だけ）"""
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.build_opener(SafeRedirect).open(req) as r:  # noqa: S310  宛先は公式の口（https だけ）
            return r.status, r.read(MAX_BODY)
    except urllib.error.HTTPError as e:
        return e.code, e.read(MAX_BODY) or b""
    except (urllib.error.URLError, OSError, ValueError) as e:
        raise FetchError(f"{type(e).__name__}: {e}"[:200]) from None


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


def shared_dir(env) -> pathlib.Path | None:
    """run をまたぐ控えの置き場（SHARED_ENV の絶対パスの下の CACHE_DIR）。env に無い・相対なら None（使わない）"""
    home = env.get(SHARED_ENV) or ""
    return pathlib.Path(home) / CACHE_DIR if os.path.isabs(home) else None


def _read_doc(path: pathlib.Path):
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return doc if isinstance(doc, dict) and doc.get("schema") == SCHEMA else None


def _fresh(doc, now: float, span: float) -> bool:
    at = doc.get("at")
    return isinstance(at, (int, float)) and not isinstance(at, bool) and 0 <= now - at < span


def _shared_get(sd, name: str, now: float, statuses=("ok", "not_found")):
    """run をまたぐ控えの 1 本（statuses の状態で、SHARED_TTL の内の物）。無ければ None"""
    doc = _read_doc(sd / name) if sd is not None else None
    return doc if doc and doc.get("status") in statuses and _fresh(doc, now, SHARED_TTL) else None


def _shared_put(sd, name: str, doc: dict) -> str:
    """run をまたぐ控えに書く（同じ家で同時に走る run と読み合うので、一時のファイルに書いて置き換える）。書けなければ理由の 1 行"""
    try:
        sd.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=sd, prefix=".tmp-", suffix=".json")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(json.dumps(doc, ensure_ascii=False, indent=1) + "\n")
            os.replace(tmp, sd / name)
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)
    except OSError as e:
        return f"{name}: {type(e).__name__}: {e}"[:200]
    return ""


def _official_name(lib: dict) -> str:
    """公式の文書の控えの名（盤面の周・包みの家）: ライブラリの名と版だけ（公式の問いは名と版しか持たない）"""
    return re.sub(r"[^A-Za-z0-9._@-]", "_", f"{lib['name']}@{lib['version'] or 'any'}") + OFFICIAL_SUFFIX


def _official(board, lib: dict, get, sd, now: float, keep, share) -> tuple:
    """公式の文書（盤面の控え → 家の控え → 網の順）。(控えの形の dict, 出どころ board|shared|net)。取れた物と見つからない物だけ控える"""
    name = _official_name(lib)
    got = _cached(board, name)
    if got is not None:
        return got, "board"
    got = _shared_get(sd, name, now)
    if got is not None:
        keep(name, got)
        return got, "shared"
    got = {"schema": SCHEMA, "source": "official", "lib": {"name": lib["name"], "version": lib["version"]},
           **libdocs_web.fetch(lib, lib["version"], get), "at": now}
    if got["status"] in ("ok", "not_found"):
        keep(name, got)
        share(name, got)
    return got, "net"


# ---------------------------------------------------------------- 節
def _groups(r: dict) -> dict:
    """1 本のライブラリの出どころごとの断片（手元・公式。取れなかった出どころは空）"""
    local, official = r["local"], r["official"]
    return {"local": list(local.get("fragments") or []) if local.get("status") == "ok" else [],
            "official": libdocs_web.fragments(official.get("docs"), r["lib"].get("uses"))
            if official.get("status") == "ok" else []}


def _allocate(groups: dict, share: int) -> tuple:
    """1 本の分（share トークン）を出どころに分けて断片を選ぶ。先に手元 1/2・公式の残りの取り分の中で、入る断片を順に取り
    （大きすぎる断片は飛ばす）、余りを手元 → 公式の順に、入らなかった断片で埋める。
    ({出どころ: [選んだ断片（元の順）]}, 使った量, 切った数)"""
    caps = {"local": share // 2}
    caps["official"] = share - caps["local"]
    chosen = {src: set() for src in SOURCES}
    used = 0
    for src in SOURCES:
        spent = 0
        for i, f in enumerate(groups.get(src) or []):
            if spent + f["tokens"] <= caps[src]:
                chosen[src].add(i)
                spent += f["tokens"]
        used += spent
    for src in SOURCES:
        for i, f in enumerate(groups.get(src) or []):
            if i not in chosen[src] and used + f["tokens"] <= share:
                chosen[src].add(i)
                used += f["tokens"]
    picked = {src: [f for i, f in enumerate(groups.get(src) or []) if i in chosen[src]] for src in SOURCES}
    cut = sum(len(groups.get(src) or []) - len(picked[src]) for src in SOURCES)
    return picked, used, cut


LABELS = {"local": "手元の版", "official": "公式"}


def _render_docs(rows: list, budget: int) -> tuple:
    """文書の取れたライブラリごとに、手元 → 公式の順に断片を量の上限の中で並べる。(本文の段, 貼った数, 使った量, 切った数)"""
    have = [r for r in rows if any(r["groups"].values())]
    if not have:
        return [], 0, 0, 0
    per = budget // len(have)
    parts, shown, used, cut = [], 0, 0, 0
    for r in have:
        lib = r["lib"]
        picked, spent, c = _allocate(r["groups"], per)
        used += spent
        cut += c
        froms = []
        if r["groups"]["local"]:
            froms.append(f"手元の版 {r['local'].get('where') or ''}".rstrip())
        if r["groups"]["official"]:
            froms.append("公式 " + "・".join(d["url"] for d in r["official"].get("docs") or []))
        parts.append(f"### {lib['search']} {lib['version'] or '（版の宣言なし）'}\n出どころ: {'／'.join(froms)}")
        for src in SOURCES:
            for s in picked[src]:
                shown += 1
                parts.append(f"#### {LABELS[src]}: {s['title']}\n出典: {s['source'] or '（無し）'}\n{s['text']}".rstrip())
    return parts, shown, used, cut


def _names(rows, pick) -> str:
    return "、".join(pick(r) for r in rows)


def _count(label: str, rows: list, pick) -> str:
    """「<label> N 本（名、名）」（0 本なら括弧なし）"""
    return f"{label} {len(rows)} 本" + (f"（{_names(rows, pick)}）" if rows else "")


def section(board, repo, files, *, get=None, env=None, budget: int = BUDGET, now: float | None = None) -> str:
    """指示書に貼る節（TITLE で始まる）。組めない時も節を返し、理由を書く。now は run をまたぐ控えの時刻の比べ（既定は今）"""
    env = os.environ if env is None else env
    get = http_get if get is None else get
    now = time.time() if now is None else now
    try:
        return _section(board, repo, files, get, env, budget, now)
    except Exception as e:  # noqa: BLE001  組めなかったことは節に書く（黙って落とさない）
        return f"{TITLE}\n\n組めなかった（{type(e).__name__}: {e}）。この節の文書は無い。"[:1000]


HEAD = ("機械が、この単位のファイルが使うライブラリの文書を 2 つの出どころから順に取って貼った（どの断片にも出典）: "
        "(1) 手元の版——run の作業ツリーか同じリポジトリの main の作業ツリーに入っている版のコードを、import せずに読んだ署名と"
        "説明（入っている版のコードそのもの） (2) 公式——ライブラリの持ち主の文書（PyPI・npm の README、docs の場所の llms.txt。"
        "版を合わせられる物は合わせた）。下の「どこからも文書が無い」のライブラリと、ここで足りない所は "
        "WebSearch・WebFetch で公式の文書を自分で引け。")


def _section(board, repo, files, get, env, budget, now) -> str:
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
    off = str(env.get(ENV_SWITCH, "")).strip().lower() == "off"
    take, over = keys[:MAX_LIBS], keys[MAX_LIBS:]
    rows, unshared = [], []
    official_from = {"board": 0, "shared": 0, "net": 0}
    sd = shared_dir(env)
    roots = libdocs_local.roots(pathlib.Path(repo))

    def keep(name, doc):
        board.work(f"{CACHE_DIR}/{name}").write_text(json.dumps(doc, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")

    def share(name, doc):
        why = _shared_put(sd, name, doc) if sd is not None else ""
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
            official, origin = _official(board, lib, get, sd, now, keep, share)
            official_from[origin] += 1 if official["status"] == "ok" else 0
        row = {"lib": lib, "local": local, "official": official}
        row["groups"] = _groups(row)
        rows.append(row)
    by_local = {st: [r for r in rows if r["local"]["status"] == st] for st in ("ok", "absent", "error")}
    by_official = {st: [r for r in rows if r["official"]["status"] == st] for st in ("ok", "not_found", "error")}
    none = [r for r in rows if not any(r["groups"].values())]
    parts, shown, used, cut = _render_docs(rows, budget)
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
    lines.append(f"貼った断片 {shown} 本・{used} トークン（予算 {budget}。切った断片 {cut} 本）")
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
            "local": {**{k: v for k, v in local.items() if k != "fragments"},
                      "fragments": [{"title": f["title"], "source": f["source"], "tokens": f["tokens"]}
                                    for f in local.get("fragments") or []]},
            "official": {**{k: v for k, v in r["official"].items() if k not in ("docs", "lib")},
                         "docs": [{"kind": d.get("kind"), "url": d.get("url"), "chars": len(d.get("text") or "")}
                                  for d in r["official"].get("docs") or []]}}
