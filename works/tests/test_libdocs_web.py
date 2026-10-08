"""公式の文書を登録なしの口で引く（.shared/core/libdocs_web.py）の検査。網には出ない（HTTP の口は偽物を渡す）。

- Python: PyPI の JSON（版つき、無ければ版なし）の info.description（その版の README）と、project_urls の docs の場所の
  llms-full.txt・llms.txt（docs の場所の下、次に host の根。`# ` で始まる文書だけを受け、HTML は捨てる）
- JS: npm の registry（版つき、無ければ latest）の readme と homepage の llms*.txt。readme が無く手元にも README が無ければ、
  repository が GitHub の時だけ raw.githubusercontent.com の v<版>・<版> の tag の README.md
- 送る URL はライブラリの名・版と registry の答えに在った URL だけ（使う名もコードの字も送らない）。鍵は付けない。https だけ
- 断片: 文書を見出しで切り、使う名を含む節を先に、残りを文書の順に並べる
"""
import json
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.dont_write_bytecode = True
sys.path.insert(0, str(ROOT / ".shared" / "core"))

import libdocs_web  # noqa: E402

README = ("# Requests\n\nRequests is an elegant and simple HTTP library.\n\n## Installing\n\npip install requests\n\n"
          "## Sessions\n\nUse a Session to persist cookies: `s = requests.Session()`.\n")
PYPI = {"info": {"name": "requests", "version": "2.32.3", "description": README,
                 "description_content_type": "text/markdown",
                 "project_urls": {"Documentation": "https://requests.readthedocs.io/en/latest/",
                                  "Source": "https://github.com/psf/requests"},
                 "home_page": "https://requests.readthedocs.io"}}
LLMS = "# Requests\n\n> HTTP for Humans.\n\n## Docs\n\n- [Quickstart](https://requests.readthedocs.io/q.md): first steps\n"


class Http:
    def __init__(self, routes):
        self.routes = routes
        self.calls = []

    def __call__(self, url, headers):
        self.calls.append((url, dict(headers)))
        if url in self.routes:
            code, body = self.routes[url]
            return code, body if isinstance(body, bytes) else (json.dumps(body) if isinstance(body, dict) else body).encode()
        return 404, b"Not Found"

    def urls(self):
        return [u for u, _ in self.calls]


def pylib(version="2.32.3"):
    return {"name": "requests", "search": "requests", "lang": "python", "uses": ["requests.Session"], "version": version}


class PythonCase(unittest.TestCase):
    def test_pypi_readme_and_llms_txt(self):
        http = Http({"https://pypi.org/pypi/requests/2.32.3/json": (200, PYPI),
                     "https://requests.readthedocs.io/en/latest/llms.txt": (200, LLMS)})
        got = libdocs_web.fetch(pylib(), "2.32.3", http)
        self.assertEqual(got["status"], "ok", got)
        self.assertEqual([(d["kind"], d["url"]) for d in got["docs"]],
                         [("readme", "https://pypi.org/project/requests/2.32.3/"),
                          ("llms", "https://requests.readthedocs.io/en/latest/llms.txt")])
        self.assertEqual(http.urls(), ["https://pypi.org/pypi/requests/2.32.3/json",
                                       "https://requests.readthedocs.io/en/latest/llms-full.txt",
                                       "https://requests.readthedocs.io/en/latest/llms.txt"])
        self.assertTrue(all("Authorization" not in h for _, h in http.calls), "鍵は付けない")
        self.assertTrue(all("Session" not in u for u in http.urls()), "使う名を URL に載せない")

    def test_html_is_not_an_llms_txt(self):
        http = Http({"https://pypi.org/pypi/requests/2.32.3/json": (200, PYPI),
                     "https://requests.readthedocs.io/en/latest/llms-full.txt": (200, "<!doctype html><html>SPA</html>"),
                     "https://requests.readthedocs.io/en/latest/llms.txt": (200, "<html></html>"),
                     "https://requests.readthedocs.io/llms-full.txt": (200, "not a heading\nfoo")})
        got = libdocs_web.fetch(pylib(), "2.32.3", http)
        self.assertEqual([d["kind"] for d in got["docs"]], ["readme"])
        self.assertIn("https://requests.readthedocs.io/llms.txt", http.urls(), "host の根も見る")

    def test_unknown_version_falls_back_to_the_project(self):
        http = Http({"https://pypi.org/pypi/requests/json": (200, PYPI)})
        got = libdocs_web.fetch(pylib("2"), "2", http)
        self.assertEqual(got["status"], "ok")
        self.assertEqual(http.urls()[:2], ["https://pypi.org/pypi/requests/2/json", "https://pypi.org/pypi/requests/json"])
        self.assertIn("版 2 が registry に無い", got["note"])

    def test_not_on_the_registry(self):
        got = libdocs_web.fetch(pylib(None), None, Http({}))
        self.assertEqual(got["status"], "not_found")

    def test_registry_error_is_an_error(self):
        got = libdocs_web.fetch(pylib(), "2.32.3", Http({"https://pypi.org/pypi/requests/2.32.3/json": (503, "busy")}))
        self.assertEqual(got["status"], "error")
        self.assertIn("HTTP 503", got["error"])

        def broken(url, headers):
            raise OSError("nodename nor servname provided")
        got = libdocs_web.fetch(pylib(), "2.32.3", broken)
        self.assertEqual(got["status"], "error")
        self.assertIn("nodename", got["error"])

    def test_plain_http_and_code_hosts_are_not_docs_sites(self):
        doc = json.loads(json.dumps(PYPI))
        doc["info"]["project_urls"] = {"Documentation": "http://insecure.example/docs/", "Source": "https://github.com/psf/requests"}
        doc["info"]["home_page"] = ""
        http = Http({"https://pypi.org/pypi/requests/2.32.3/json": (200, doc)})
        got = libdocs_web.fetch(pylib(), "2.32.3", http)
        self.assertEqual(http.urls(), ["https://pypi.org/pypi/requests/2.32.3/json"])
        self.assertEqual([d["kind"] for d in got["docs"]], ["readme"])

    def test_long_docs_are_kept_bounded(self):
        doc = json.loads(json.dumps(PYPI))
        doc["info"]["description"] = "# Big\n\n" + "x" * (libdocs_web.KEEP_CHARS + 500)
        got = libdocs_web.fetch(pylib(), "2.32.3", Http({"https://pypi.org/pypi/requests/2.32.3/json": (200, doc)}))
        self.assertLessEqual(len(got["docs"][0]["text"]), libdocs_web.KEEP_CHARS)


class NodeCase(unittest.TestCase):
    def jslib(self):
        return {"name": "zod", "search": "zod", "lang": "js", "uses": ["object"], "version": "3.23.8"}

    def test_npm_readme_from_github_tag(self):
        """本物の registry の版の文書（/<名>/<版>・/latest）は readme を持たない（2026-10-08 に zod・express・@types/node で
        確かめた）ので、README は repository が GitHub の時の版の tag（v<版>、次に <版>、次に gitHead の commit）から引く"""
        meta = {"name": "zod", "version": "3.23.8", "homepage": "https://zod.dev",
                "repository": {"type": "git", "url": "git+https://github.com/colinhacks/zod.git"}}
        http = Http({"https://registry.npmjs.org/zod/3.23.8": (200, meta),
                     "https://zod.dev/llms.txt": (200, "# Zod\n\n> schemas\n"),
                     "https://raw.githubusercontent.com/colinhacks/zod/3.23.8/README.md": (200, "# Zod\n\nobject() makes it.\n")})
        got = libdocs_web.fetch(self.jslib(), "3.23.8", http)
        self.assertEqual([(d["kind"], d["url"]) for d in got["docs"]],
                         [("readme", "https://raw.githubusercontent.com/colinhacks/zod/3.23.8/README.md"),
                          ("llms", "https://zod.dev/llms.txt")])
        self.assertIn("https://raw.githubusercontent.com/colinhacks/zod/v3.23.8/README.md", http.urls())

    def test_monorepo_directory_and_git_head(self):
        lib = {"name": "@upstash/context7-sdk", "search": "@upstash/context7-sdk", "lang": "js", "uses": [], "version": None}
        meta = {"name": "@upstash/context7-sdk", "version": "0.2.1", "gitHead": "abc1234",
                "repository": {"type": "git", "url": "https://github.com/upstash/context7", "directory": "packages/sdk"}}
        http = Http({"https://registry.npmjs.org/@upstash%2Fcontext7-sdk/latest": (200, meta),
                     "https://raw.githubusercontent.com/upstash/context7/abc1234/packages/sdk/README.md": (200, "# SDK\n\nhi\n")})
        got = libdocs_web.fetch(lib, None, http)
        self.assertEqual(got["status"], "ok")
        self.assertEqual(got["docs"][0]["url"], "https://raw.githubusercontent.com/upstash/context7/abc1234/packages/sdk/README.md")
        self.assertEqual(len(http.urls()), 4, "registry 1・tag 2・gitHead 1")

    def test_registry_readme_is_used_when_present(self):
        http = Http({"https://registry.npmjs.org/zod/3.23.8": (200, {"version": "3.23.8", "readme": "# Zod\n\nhello\n"})})
        got = libdocs_web.fetch(self.jslib(), "3.23.8", http)
        self.assertEqual(got["docs"][0]["url"], "https://www.npmjs.com/package/zod/v/3.23.8")
        self.assertEqual(http.urls(), ["https://registry.npmjs.org/zod/3.23.8"])


class SafetyCase(unittest.TestCase):
    def test_ip_literal_and_localhost_are_not_docs_sites(self):
        for url in ("https://10.0.0.5/docs", "https://169.254.169.254/latest", "https://localhost/docs", "https://[::1]/x",
                    "https://intranet/docs"):
            with self.subTest(url=url):
                self.assertEqual(libdocs_web.https_site(url), "")
        self.assertEqual(libdocs_web.https_site("https://docs.example.org/en/"), "https://docs.example.org/en")

    def test_redirects_only_to_public_https(self):
        self.assertTrue(libdocs_web.safe_url("https://docs.example.org/llms.txt"))
        for url in ("http://docs.example.org/llms.txt", "https://127.0.0.1/llms.txt", "ftp://x.example/y", "https://localhost/"):
            with self.subTest(url=url):
                self.assertFalse(libdocs_web.safe_url(url))


class FragmentsCase(unittest.TestCase):
    def test_sections_with_used_names_come_first(self):
        docs = [{"kind": "readme", "url": "https://pypi.org/project/requests/2.32.3/", "text": README}]
        got = libdocs_web.fragments(docs, ["requests.Session"])
        self.assertEqual(got[0]["title"], "Sessions")
        self.assertIn("requests.Session()", got[0]["text"])
        self.assertEqual(got[0]["source"], "https://pypi.org/project/requests/2.32.3/")
        self.assertEqual([g["title"] for g in got[1:]], ["Requests", "Installing"])
        self.assertTrue(all(g["tokens"] > 0 for g in got))

    def test_long_section_is_split(self):
        text = "# Long\n\n" + "\n\n".join("para %d " % i + "y" * 300 for i in range(40))
        got = libdocs_web.fragments([{"kind": "llms", "url": "https://x.example/llms.txt", "text": text}], [])
        self.assertGreater(len(got), 1)
        self.assertTrue(all(len(g["text"]) <= libdocs_web.CHUNK_MAX for g in got))


if __name__ == "__main__":
    unittest.main()
