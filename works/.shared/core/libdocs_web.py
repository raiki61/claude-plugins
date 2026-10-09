"""ライブラリの公式の文書を、登録の要らない口から引く（PyPI・npm の registry・docs の場所の llms.txt・GitHub の raw）。層 L3（共有）。

持ち主 2026-10-08「全部使う」の 2 つめの出どころ（設計 works/docs/plans/2026-10-08-libdocs-sources.md）。支度の script の節が
libdocs.section から呼ぶ。控え（盤面・包みの家）と文書のファイルは libdocs が持つ。ここは引くことだけ（断片には切らない）。

引く物:
- Python: PyPI の JSON（https://pypi.org/pypi/<名>/<版>/json。版が無い・その版が無ければ /pypi/<名>/json）の info.description
  （その版の README）と、project_urls の docs の場所（鍵に doc を含む物、docs_url、home_page・Homepage の順）の llms.txt
- JS/TS: npm の registry（https://registry.npmjs.org/<名>/<版>。版が無い・その版が無ければ latest）と、homepage の llms.txt。
  版の文書は今の registry では readme を持たない（2026-10-08 に zod・express・@types/node で確かめた。在れば使う）ので、README は
  repository が GitHub の時の https://raw.githubusercontent.com/<持ち主>/<名>/<ref>/[<directory>/]README.md（ref は v<版>、
  次に <版>、次に版の文書の gitHead の commit。最初に取れた 1 本）
- llms.txt: docs の場所の下の llms-full.txt・llms.txt、次に host の根の同じ 2 つ。最初に受けた 1 本だけ（ライブラリ 1 本の問いは
  PyPI で多くて 6 本、npm で 9 本）。llms.txt の決まり
  （https://llmstxt.org。頭は `# ` の H1）どおり、空でない最初の行が `# ` で始まる物だけを受け、HTML（SPA の 200）は捨てる
- docs の場所は safe_url（core の webget の物。https・点を持つ host の名。IP の字・localhost・点の無い社内の名は不可）を通る物
  だけ。コードの置き場（github.com・gitlab.com・bitbucket.org）と registry の頁は docs の場所に数えない。転送の先も同じ確かめ
  （webget.http_get）

送る物: URL はライブラリの名・版と、registry の答えに在った URL だけ（使う名も対象のコードの字も送らない）。鍵は付けない。
読む量は get（libdocs.http_get が webget.http_get を上限つきで呼ぶ）に任せ、控える文書 1 本は KEEP_CHARS 字まで。期限は足さない（R4）。

口（標準ライブラリだけ。網は get(url, headers) -> (状態の番号, 本文) で差し替える。get の例外は取れなかった理由になる）:
- https_site(url) -> str: docs の場所に使える URL（網に出してよいかの safe_url は webget に在り、ここでも同じ名で引ける）
- fetch(lib, version, get) -> {status: ok|not_found|error, docs: [{kind: readme|llms, url, text}], error, note}
"""
import json
import re
import urllib.parse

from webget import safe_url

PYPI = "https://pypi.org/pypi"
NPM = "https://registry.npmjs.org"
RAW = "https://raw.githubusercontent.com"
HEADERS = {"User-Agent": "works-libdocs", "Accept": "*/*"}
KEEP_CHARS = 400_000         # 控える文書 1 本の上限（字）
CODE_HOSTS = ("github.com", "gitlab.com", "bitbucket.org", "pypi.org", "npmjs.com", "www.npmjs.com", "registry.npmjs.org")
LLMS = ("llms-full.txt", "llms.txt")
GITHUB = re.compile(r"(?:github\.com[/:]|^github:)([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+?)(?:\.git)?(?:[/#?].*)?$")


def _get_text(get, url: str):
    """(状態の番号, 字)。get の例外はそのまま上へ"""
    status, body = get(url, HEADERS)
    return status, (body or b"").decode("utf-8", errors="replace")


def _keep(text: str) -> str:
    return text if len(text) <= KEEP_CHARS else text[:KEEP_CHARS]


def https_site(url) -> str:
    """docs の場所に使える URL（safe_url を通り、コードの置き場・registry の頁でない物。末尾の / を落とした物）か空"""
    if not safe_url(url):
        return ""
    p = urllib.parse.urlsplit(url.strip())
    host = (p.hostname or "").lower()
    if host in CODE_HOSTS or host.endswith(tuple("." + h for h in CODE_HOSTS)):
        return ""
    return urllib.parse.urlunsplit(("https", p.netloc, p.path.rstrip("/"), "", ""))


def _llms_candidates(site: str) -> list:
    p = urllib.parse.urlsplit(site)
    origin = f"https://{p.netloc}"
    out = []
    for base in (site, origin):
        for name in LLMS:
            u = f"{base}/{name}"
            if u not in out:
                out.append(u)
    return out


def _is_llms(text: str) -> bool:
    for line in text.lstrip("﻿").splitlines():
        if line.strip():
            return line.startswith("# ")
    return False


def _llms(get, sites) -> dict | None:
    """docs の場所の最初の 1 つで llms*.txt を探す（受けた最初の 1 本）。網の誤りは探すのをやめる（主の答えは取れている）"""
    for site in sites[:1]:
        for url in _llms_candidates(site):
            try:
                status, text = _get_text(get, url)
            except Exception:  # noqa: BLE001  llms.txt は在れば足す物。取れなくても registry の答えは使う
                return None
            if status == 200 and _is_llms(text):
                return {"kind": "llms", "url": url, "text": _keep(text)}
    return None


def _registry(get, urls) -> tuple:
    """(状態の番号, JSON, 使った URL)。最初の URL が 404 なら次へ"""
    status, doc, used = 404, None, ""
    for url in urls:
        status, text = _get_text(get, url)
        used = url
        if status != 404:
            break
    if status == 200:
        try:
            doc = json.loads(text)
        except ValueError:
            doc = None
    return status, doc, used


def _pypi(lib, version, get) -> dict:
    name = urllib.parse.quote(lib.get("search") or lib["name"], safe="")
    urls = ([f"{PYPI}/{name}/{urllib.parse.quote(version, safe='')}/json"] if version else []) + [f"{PYPI}/{name}/json"]
    status, doc, used = _registry(get, urls)
    out = {"status": "not_found", "docs": [], "error": "", "note": ""}
    if status == 404:
        return out
    if status != 200 or not isinstance(doc, dict) or not isinstance(doc.get("info"), dict):
        return {**out, "status": "error", "error": f"PyPI: HTTP {status}" + ("（JSON が読めない）" if status == 200 else "")}
    if version and used != urls[0]:
        out["note"] = f"版 {version} が registry に無い（版を指さずに引いた）"
    info = doc["info"]
    got_version = info.get("version") if isinstance(info.get("version"), str) else ""
    desc = info.get("description") if isinstance(info.get("description"), str) else ""
    if desc.strip() and desc.strip() != "UNKNOWN":
        page = f"https://pypi.org/project/{name}/" + (f"{urllib.parse.quote(got_version, safe='')}/" if got_version else "")
        out["docs"].append({"kind": "readme", "url": page, "text": _keep(desc)})
    urls_ = info.get("project_urls") if isinstance(info.get("project_urls"), dict) else {}
    sites = [urls_[k] for k in urls_ if "doc" in str(k).lower()] + [info.get("docs_url")] + \
        [urls_[k] for k in urls_ if str(k).lower() in ("homepage", "home", "home page")] + [info.get("home_page")]
    sites = list(dict.fromkeys(s for s in map(https_site, sites) if s))
    got = _llms(get, sites)
    if got:
        out["docs"].append(got)
    return {**out, "status": "ok" if out["docs"] else "not_found"}


def _github(repo) -> tuple:
    url = repo.get("url") if isinstance(repo, dict) else repo
    directory = repo.get("directory") if isinstance(repo, dict) and isinstance(repo.get("directory"), str) else ""
    m = GITHUB.search(url.strip()) if isinstance(url, str) else None
    if m is None and isinstance(url, str) and re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", url.strip()):
        m = re.match(r"([^/]+)/(.+)", url.strip())
    if m is None:
        return None
    directory = directory.strip("/")
    return m.group(1), m.group(2), (directory if re.fullmatch(r"[A-Za-z0-9_./-]+", directory or "x") and ".." not in directory
                                    else "")


def _npm(lib, version, get) -> dict:
    raw_name = lib.get("search") or lib["name"]
    name = urllib.parse.quote(raw_name, safe="@")
    urls = ([f"{NPM}/{name}/{urllib.parse.quote(version, safe='')}"] if version else []) + [f"{NPM}/{name}/latest"]
    status, doc, used = _registry(get, urls)
    out = {"status": "not_found", "docs": [], "error": "", "note": ""}
    if status == 404:
        return out
    if status != 200 or not isinstance(doc, dict):
        return {**out, "status": "error", "error": f"npm: HTTP {status}" + ("（JSON が読めない）" if status == 200 else "")}
    if version and used != urls[0]:
        out["note"] = f"版 {version} が registry に無い（latest を引いた）"
    got_version = doc.get("version") if isinstance(doc.get("version"), str) else ""
    readme = doc.get("readme") if isinstance(doc.get("readme"), str) else ""
    page = f"https://www.npmjs.com/package/{raw_name}" + (f"/v/{got_version}" if got_version else "")
    if readme.strip() and not readme.startswith("ERROR: No README"):
        # 版の文書（/<名>/<版>・/latest）は今の registry では readme を持たない（2026-10-08 に確かめた）。在れば使う
        out["docs"].append({"kind": "readme", "url": page, "text": _keep(readme)})
    elif (gh := _github(doc.get("repository"))) and got_version:
        owner, repo, directory = gh
        head = doc.get("gitHead") if isinstance(doc.get("gitHead"), str) and re.fullmatch(r"[0-9a-f]{7,40}", doc["gitHead"]) \
            else ""
        for ref in [f"v{got_version}", got_version] + ([head] if head else []):
            url = "/".join(x for x in (RAW, owner, repo, urllib.parse.quote(ref, safe=""), directory, "README.md") if x)
            try:
                status, text = _get_text(get, url)
            except Exception:  # noqa: BLE001  README は在れば足す物
                break
            if status == 200 and text.strip():
                out["docs"].append({"kind": "readme", "url": url, "text": _keep(text)})
                break
    got = _llms(get, [s for s in [https_site(doc.get("homepage"))] if s])
    if got:
        out["docs"].append(got)
    return {**out, "status": "ok" if out["docs"] else "not_found"}


def fetch(lib: dict, version, get) -> dict:
    """公式の文書。返り {status: ok|not_found|error, docs, error, note}。not_found は registry に無いか、文書が 1 本も無い"""
    try:
        if lib.get("lang") == "js":
            return _npm(lib, version, get)
        return _pypi(lib, version, get)
    except Exception as e:  # noqa: BLE001  取れなかった理由は節に出す（落とさない）
        return {"status": "error", "docs": [], "error": f"{type(e).__name__}: {e}"[:200], "note": ""}
