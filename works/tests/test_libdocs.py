"""ライブラリの文書（.shared/core/libdocs.py。手元の版・公式・Context7 の 3 つの出どころを機械が引いて指示書に貼る）の検査。

網には出ない（HTTP の口は偽物を渡す）。盤面は周の置き場（dir・work）だけを持つ偽物。
- 見つけ方: 単位のファイルの import（Python・JS/TS）から標準ライブラリとリポジトリの中の物を除き、依存の宣言
  （pyproject.toml・requirements*.txt・package.json）から版を引く。宣言のファイル自体が単位なら宣言の全部が対象
- 取り方: libs/search で id と版を決め、context（type=json）で断片を取る。版が Context7 に在ればその版を指す
- 盤面の控え: 取れた物（と Context7 に無い物）はライブラリ＋版の鍵で周の置き場に書き、次は網に出ない（前の周の控えも読む）
- 数で言う: 枠切れ（429）で取らなかった・取れなかった・Context7 に無い・版が無い・上限で取らない物は節の頭に数と名前で出す
  （黙って落とさない）。枠切れは TITLE の次の行にも出し、1 本受けたら以後は（次の周も）問い合わせない
  （test_quota_stops_later_calls_and_leads_the_section。報告の冒頭 2 の 1 行は test_report の test_context7_quota_line_in_head_entry）
- 標準ライブラリだけの対象は何も取らず、取らないことを書く。WORKS_CONTEXT7=off も取らないことを書く
- 組み立て: 修正役の指示書（fixrules.fix_prompt）と修正案の役の頭（planblk.head）に節が入る
- 出どころ（SourcesCase。設計 works/docs/plans/2026-10-08-libdocs-sources.md）: 手元の版 → 公式 → Context7 の順に並べ、量の上限の
  中で分ける。手元で読んだ版で公式と Context7 に問う。どこからも取れなかった物は名指して役に自分で引けと言う。off でも手元は読む。
  公式の取れた物と見つからない物は盤面と家に控える（取れなかった物は控えない）。Context7 の鍵は Context7 の URL にだけ付ける
"""
import json
import pathlib
import re
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.dont_write_bytecode = True
for p in (ROOT / ".shared" / "core", ROOT / "blk-fix" / "lib", ROOT / "blk-plan" / "lib"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import libdocs  # noqa: E402


class FakeBoard:
    """周の置き場だけを持つ盤面（DiskBoard.work と同じ形: <dir>/r<N>/<name>）"""

    def __init__(self, d, rnd=1):
        self.dir = pathlib.Path(d)
        self.round = rnd

    def work(self, name):
        p = self.dir / f"r{self.round}" / name
        p.parent.mkdir(parents=True, exist_ok=True)
        return p


SEARCH = {"results": [{"id": "/psf/requests", "title": "Requests", "versions": ["v2.31.0", "v2.32.3"], "state": "finalized"},
                      {"id": "/other/requests-mock", "title": "requests-mock", "versions": []}]}
CONTEXT = {
    "codeSnippets": [
        {"codeTitle": "Session with retries", "codeDescription": "Mount an adapter", "codeLanguage": "python",
         "codeTokens": 120, "codeId": "https://github.com/psf/requests/blob/main/docs/user/advanced.rst#_snippet_1",
         "pageTitle": "Advanced", "codeList": [{"language": "python", "code": "s = requests.Session()"}]},
        {"codeTitle": "Huge example", "codeDescription": "too big", "codeLanguage": "python",
         "codeTokens": 9000, "codeId": "https://example.invalid/huge", "pageTitle": "Huge",
         "codeList": [{"language": "python", "code": "x = 1"}]},
    ],
    "infoSnippets": [{"pageId": "https://requests.readthedocs.io/en/latest/user/quickstart/", "breadcrumb": "Quickstart",
                      "content": "Requests is an elegant HTTP library.", "contentTokens": 40}],
}


class FakeHttp:
    def __init__(self, routes=None):
        self.calls = []
        self.routes = routes or {}

    def __call__(self, url, headers):
        self.calls.append(url)
        for key, (code, doc) in self.routes.items():
            if key in url:
                return code, (doc if isinstance(doc, str) else json.dumps(doc)).encode()
        return 404, json.dumps({"error": "library_not_found", "message": "no"}).encode()


def ok_http():
    return FakeHttp({"/v2/libs/search": (200, SEARCH), "/v2/context": (200, CONTEXT)})


class Base(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = pathlib.Path(self._tmp.name)
        self.repo = self.tmp / "repo"
        self.repo.mkdir()
        self.board = FakeBoard(self.tmp / "board")
        self.env = {}

    def tearDown(self):
        self._tmp.cleanup()

    def write(self, rel, text):
        p = self.repo / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
        return rel


class DetectCase(Base):
    def test_python_imports_split_into_stdlib_local_and_libraries(self):
        self.write("helper.py", "X = 1\n")
        f = self.write("app.py", "import os, json\nimport helper\nfrom . import sibling\nimport requests\n"
                                 "from yaml import safe_load\n")
        self.write("requirements.txt", "requests==2.32.3\nPyYAML>=6.0\n")
        got = libdocs.detect(self.repo, [f])
        self.assertEqual(sorted(got["libs"]), ["requests", "yaml"])
        self.assertEqual(got["libs"]["requests"]["version"], "2.32.3")
        self.assertEqual(got["libs"]["yaml"]["version"], "6.0")      # 輸入の名 yaml → 配る名 PyYAML
        self.assertEqual(got["libs"]["yaml"]["symbols"], ["safe_load"])
        self.assertEqual(got["counts"]["stdlib"], 2)
        self.assertEqual(got["counts"]["local"], 2)

    def test_nested_own_python_package_is_not_a_library(self):
        self.write("backend/app/__init__.py", "")
        self.write("backend/app/core.py", "V = 1\n")
        f = self.write("backend/tests/test_x.py", "import app\nfrom app.core import V\nimport requests\n")
        self.write("requirements.txt", "requests==2.32.3\n")
        got = libdocs.detect(self.repo, [f])
        self.assertEqual(sorted(got["libs"]), ["requests"], "作業ツリーで定義された app を外のライブラリとして引かない")
        self.assertEqual(got["counts"]["local"], 2)

    def test_own_js_workspace_package_is_not_a_library(self):
        self.write("packages/ui/package.json", json.dumps({"name": "@acme/ui"}))
        f = self.write("web/app.ts", "import { Button } from '@acme/ui';\nimport { z } from 'zod';\n")
        self.write("package.json", json.dumps({"dependencies": {"zod": "^3.23.8"}}))
        got = libdocs.detect(self.repo, [f])
        self.assertEqual(sorted(got["libs"]), ["zod"], "workspace の自分のパッケージ名を外のライブラリとして引かない")
        self.assertEqual(got["counts"]["local"], 1)

    def test_js_imports_and_package_json(self):
        f = self.write("web/app.ts", "import { z } from 'zod';\nimport fs from 'node:fs';\nimport x from './x';\n"
                                     "const r = require(\"@upstash/context7-sdk\");\nimport path from 'path';\n")
        self.write("package.json", json.dumps({"dependencies": {"zod": "^3.23.8"},
                                               "devDependencies": {"@upstash/context7-sdk": "~0.2.0"}}))
        got = libdocs.detect(self.repo, [f])
        self.assertEqual(sorted(got["libs"]), ["@upstash/context7-sdk", "zod"])
        self.assertEqual(got["libs"]["zod"]["version"], "3.23.8")
        self.assertEqual(got["counts"]["stdlib"], 2)
        self.assertEqual(got["counts"]["local"], 1)

    def test_touched_manifest_brings_all_its_dependencies(self):
        f = self.write("pyproject.toml", '[project]\nname = "x"\ndependencies = ["httpx==0.27.0", "rich"]\n')
        got = libdocs.detect(self.repo, [f])
        self.assertEqual(sorted(got["libs"]), ["httpx", "rich"])
        self.assertEqual(got["libs"]["httpx"]["version"], "0.27.0")
        self.assertIsNone(got["libs"]["rich"]["version"])

    def test_unreadable_files_are_counted(self):
        f = self.write("bad.py", "def (:\n")
        got = libdocs.detect(self.repo, [f, "missing.py"])
        self.assertEqual(sorted(u["path"] for u in got["unreadable"]), ["bad.py", "missing.py"])


class SectionCase(Base):
    def section(self, files, http, **kw):
        return libdocs.section(self.board, self.repo, files, get=http, env=self.env, **kw)

    def test_library_detected_gives_section_with_sources(self):
        f = self.write("app.py", "import requests\n")
        self.write("requirements.txt", "requests==2.32.3\n")
        http = ok_http()
        text = self.section([f], http)
        self.assertTrue(text.startswith(libdocs.TITLE), text)
        self.assertIn("https://github.com/psf/requests/blob/main/docs/user/advanced.rst#_snippet_1", text)
        self.assertIn("s = requests.Session()", text)
        self.assertIn("/psf/requests/v2.32.3", text)          # 版を指した id
        self.assertIn("取れた 1 本", text)
        self.assertNotIn("x = 1", text, "予算を超える断片は貼らない")
        self.assertIn("切った断片 1 本", text)
        ctx = [u for u in http.calls if "/v2/context" in u]
        self.assertEqual(len(ctx), 1)
        self.assertIn("type=json", ctx[0])
        self.assertNotIn("import+requests", ctx[0], "対象のコードの字を問いに載せない")

    def test_cache_hit_does_not_touch_the_network(self):
        f = self.write("app.py", "import requests\n")
        self.write("requirements.txt", "requests==2.32.3\n")
        first = self.section([f], ok_http())
        self.board.round = 2          # 次の周も前の周の控えを読む
        http = FakeHttp()
        again = self.section([f], http)
        self.assertEqual(http.calls, [])
        self.assertIn("盤面の控えから 1 本", again)
        self.assertIn("s = requests.Session()", again)
        self.assertTrue(first)
        self.assertTrue(list((self.board.dir / "r1" / libdocs.CACHE_DIR).glob("requests@2.32.3*.json")))

    def test_failure_is_declared_by_number_and_not_cached(self):
        f = self.write("app.py", "import requests\nimport flask\n")
        http = FakeHttp({"libraryName=requests": (429, {"error": "rate_limited", "message": "slow down"}),
                         "libraryName=flask": (200, {"results": []})})
        text = self.section([f], http)
        self.assertIn("枠切れで取らなかった 1 本", text)
        self.assertIn("取れなかった 0 本", text)
        self.assertIn("requests（HTTP 429", text)
        self.assertIn("Context7 に無い 1 本", text)
        self.assertIn("flask", text)
        self.assertFalse([p for p in self.board.dir.glob(f"r*/{libdocs.CACHE_DIR}/requests@*.json")
                          if not p.name.endswith(libdocs.OFFICIAL_SUFFIX)], "失敗は控えない（次に取り直す）")

    def test_quota_stops_later_calls_and_leads_the_section(self):
        f = self.write("app.py", "import requests\nimport flask\nimport yaml\n")
        http = FakeHttp({"libraryName=flask": (429, {"error": "quota", "message": "Monthly quota exceeded"})})
        text = self.section([f], http)
        self.assertEqual(len([u for u in http.calls if "libraryName=" in u]), 1, "1 本目の 429 で以後は網に出ない")
        self.assertEqual(text.splitlines()[1], libdocs.QUOTA_NOTICE)
        self.assertIn("枠切れで取らなかった 3 本", text)
        again = FakeHttp()
        self.board.round = 2
        self.section([f], again)
        self.assertEqual(again.calls, [], "次の周も印を読んで網に出ない")

    def test_network_error_is_declared(self):
        f = self.write("app.py", "import requests\n")

        def broken(url, headers):
            raise libdocs.FetchError("URLError: nodename nor servname provided")
        text = self.section([f], broken)
        self.assertIn("取れなかった 1 本", text)
        self.assertIn("URLError", text)

    def test_stdlib_only_fetches_nothing_and_says_so(self):
        self.write("util.py", "V = 1\n")
        f = self.write("app.py", "import os\nimport util\n")
        http = FakeHttp()
        text = self.section([f], http)
        self.assertEqual(http.calls, [])
        self.assertIn("取る物は無い（0 本）", text)
        self.assertIn("標準 1", text)

    def test_switch_off_is_declared(self):
        f = self.write("app.py", "import requests\n")
        self.env = {libdocs.ENV_SWITCH: "off"}
        http = FakeHttp()
        text = self.section([f], http)
        self.assertEqual(http.calls, [])
        self.assertIn(f"{libdocs.ENV_SWITCH}=off", text)

    def test_version_not_in_context7_is_declared(self):
        f = self.write("app.py", "import requests\n")
        self.write("requirements.txt", "requests==1.0.0\n")
        text = self.section([f], ok_http())
        self.assertIn("版が合わない 1 本", text)
        self.assertIn("requests 1.0.0", text)

    def test_api_key_goes_in_the_header_only(self):
        f = self.write("app.py", "import requests\n")
        self.env = {libdocs.ENV_KEY: "ctx7sk-test"}
        seen = []

        def http(url, headers):
            seen.append((url, dict(headers)))
            return ok_http()(url, headers)
        self.section([f], http)
        c7 = [h for u, h in seen if u.startswith(libdocs.API)]
        self.assertTrue(c7)
        self.assertTrue(all(h.get("Authorization") == "Bearer ctx7sk-test" for h in c7))
        self.assertTrue([u for u, _ in seen if not u.startswith(libdocs.API)], "公式の口にも問う")
        self.assertTrue(all("Authorization" not in h for u, h in seen if not u.startswith(libdocs.API)),
                        "鍵は Context7 の URL にだけ付ける（公式の口に送らない）")
        self.assertTrue(all("ctx7sk" not in u for u, _ in seen))


PYPI = {"info": {"name": "requests", "version": "2.32.3",
                 "description": "# Requests\n\nHTTP for Humans.\n\n## Sessions\n\nUse `requests.Session` to keep cookies.\n",
                 "project_urls": {"Documentation": "https://requests.readthedocs.io/en/latest/"}}}
REQ_SP = ".venv/lib/python3.12/site-packages"


class SourcesCase(Base):
    """3 つの出どころ（手元の版・公式・Context7）を順に並べ、量の上限の中で合わせる"""

    def install(self, base=None):
        base = base or self.repo
        sp = base / REQ_SP
        (sp / "requests").mkdir(parents=True)
        (sp / "requests" / "__init__.py").write_text(
            'raise SystemExit("never import")\nfrom .sessions import Session\n', encoding="utf-8")
        (sp / "requests" / "sessions.py").write_text(
            'class Session:\n    """A Requests session (LOCAL DOCSTRING)."""\n\n    def mount(self, prefix, adapter):\n'
            '        """Registers a connection adapter."""\n', encoding="utf-8")
        (sp / "requests-2.32.3.dist-info").mkdir()
        (sp / "requests-2.32.3.dist-info" / "METADATA").write_text("Name: requests\nVersion: 2.32.3\n", encoding="utf-8")

    def all_http(self):
        return FakeHttp({"/v2/libs/search": (200, SEARCH), "/v2/context": (200, CONTEXT),
                         "pypi.org/pypi/requests/2.32.3/json": (200, PYPI)})

    def test_detect_records_the_used_names(self):
        f = self.write("app.py", "import requests\nfrom yaml import safe_load\nrequests.get('u')\n")
        got = libdocs.detect(self.repo, [f])
        self.assertEqual(got["libs"]["requests"]["uses"], ["requests.get"])
        self.assertEqual(got["libs"]["yaml"]["uses"], ["yaml.safe_load"])
        self.assertEqual(got["libs"]["requests"]["symbols"], [], "Context7 の問い（と控えの名）は今までどおり")
        g = self.write("web/a.ts", "import { object } from 'zod';\n")
        self.assertEqual(libdocs.detect(self.repo, [g])["libs"]["zod"]["uses"], ["object"])

    def test_three_sources_in_order_with_the_installed_version(self):
        self.install()
        f = self.write("app.py", "from requests import Session\n")
        http = self.all_http()
        text = libdocs.section(self.board, self.repo, [f], get=http, env={})
        local, official, c7 = (text.index("LOCAL DOCSTRING"), text.index("Use `requests.Session` to keep cookies"),
                               text.index("s = requests.Session()"))
        self.assertLess(local, official)
        self.assertLess(official, c7)
        self.assertIn("- 手元の版: 読めた 1 本（requests 2.32.3）", text)
        self.assertIn("- 公式の文書: 取れた 1 本", text)
        self.assertIn("/psf/requests/v2.32.3", text, "宣言が無くても手元の版で Context7 の版を指す")
        self.assertIn("https://pypi.org/pypi/requests/2.32.3/json", http.calls)
        self.assertIn(str(self.repo / REQ_SP / "requests" / "sessions.py"), text, "手元の断片の出典はファイル")
        self.assertNotIn("- どこからも文書が無い", text)

    def test_budget_is_shared_and_local_comes_first(self):
        self.install()
        f = self.write("app.py", "from requests import Session\n")
        text = libdocs.section(self.board, self.repo, [f], get=self.all_http(), env={}, budget=60)
        self.assertIn("LOCAL DOCSTRING", text)
        self.assertNotIn("s = requests.Session()", text, "量の上限を超える分は後の出どころから切る")
        m = re.search(r"貼った断片 \d+ 本・(\d+) トークン（予算 60。切った断片 (\d+) 本）", text)
        self.assertIsNotNone(m, text)
        self.assertLessEqual(int(m.group(1)), 60)
        self.assertGreater(int(m.group(2)), 0)

    def test_libraries_without_any_docs_are_named_for_the_roles(self):
        f = self.write("app.py", "import requests\nimport flask\n")
        text = libdocs.section(self.board, self.repo, [f], get=FakeHttp(), env={})
        self.assertIn("- どこからも文書が無い: flask、requests", text)
        self.assertIn("WebSearch・WebFetch", text)
        self.assertIn("- 手元の版: 読めた 0 本／入っていない 2 本（flask、requests）", text)
        self.assertIn("- 公式の文書: 取れた 0 本", text)
        self.assertIn("見つからない 2 本（flask、requests）", text)

    def test_installed_distribution_name_is_what_the_registry_is_asked(self):
        """輸入の名と配る名が違い（import serial・配る名 pyserial）、宣言にも表 PY_DIST にも無い時、手元で読んだ配る名で PyPI に問う
        （輸入の名で問うと別のプロジェクトの README を公式として貼る）"""
        sp = self.repo / REQ_SP
        (sp / "serial").mkdir(parents=True)
        (sp / "serial" / "__init__.py").write_text('"""pySerial."""\n', encoding="utf-8")
        (sp / "pyserial-3.5.dist-info").mkdir()
        (sp / "pyserial-3.5.dist-info" / "METADATA").write_text("Name: pyserial\nVersion: 3.5\n", encoding="utf-8")
        (sp / "pyserial-3.5.dist-info" / "top_level.txt").write_text("serial\n", encoding="utf-8")
        f = self.write("app.py", "import serial\n")
        http = FakeHttp()
        libdocs.section(self.board, self.repo, [f], get=http, env={})
        pypi = [u for u in http.calls if "pypi.org" in u]
        self.assertEqual(pypi[0], "https://pypi.org/pypi/pyserial/3.5/json")
        self.assertFalse([u for u in pypi if "/pypi/serial/" in u])

    def test_switch_off_still_reads_the_installed_version(self):
        self.install()
        f = self.write("app.py", "from requests import Session\n")
        http = FakeHttp()
        text = libdocs.section(self.board, self.repo, [f], get=http, env={libdocs.ENV_SWITCH: "off"})
        self.assertEqual(http.calls, [])
        self.assertIn("LOCAL DOCSTRING", text)
        self.assertIn(f"{libdocs.ENV_SWITCH}=off", text)
        g = self.write("other.py", "import flask\n")
        text = libdocs.section(self.board, self.repo, [g], get=http, env={libdocs.ENV_SWITCH: "off"})
        self.assertIn("- どこからも文書が無い: flask（手元に入っていない。網には出ていない", text)
        self.assertNotIn("公式と Context7 から取れなかった", text)

    def test_official_docs_are_cached_on_the_board_and_in_the_home(self):
        self.install()
        f = self.write("app.py", "from requests import Session\n")
        home = self.tmp / "home"
        env = {libdocs.SHARED_ENV: str(home)}
        libdocs.section(self.board, self.repo, [f], get=self.all_http(), env=env, now=1_800_000_000.0)
        self.board.round = 2
        http = FakeHttp()
        text = libdocs.section(self.board, self.repo, [f], get=http, env=env, now=1_800_000_060.0)
        self.assertEqual(http.calls, [], "次の周は盤面の控えを読む")
        self.assertIn("Use `requests.Session` to keep cookies", text)
        other = FakeBoard(self.tmp / "board2")
        http = FakeHttp()
        text = libdocs.section(other, self.repo, [f], get=http, env=env, now=1_800_000_120.0)
        self.assertEqual(http.calls, [], "同じ家のほかの run は家の控えを読む")
        self.assertIn("Use `requests.Session` to keep cookies", text)
        self.assertTrue((home / libdocs.CACHE_DIR / ("requests@2.32.3" + libdocs.OFFICIAL_SUFFIX)).is_file())

    def test_official_failure_is_not_cached(self):
        f = self.write("app.py", "import requests\n")
        text = libdocs.section(self.board, self.repo, [f], get=FakeHttp({"pypi.org": (503, {"m": "busy"})}), env={})
        self.assertIn("取れなかった 1 本（requests: PyPI: HTTP 503）", text)
        self.assertFalse(list(self.board.dir.glob(f"r*/{libdocs.CACHE_DIR}/*{libdocs.OFFICIAL_SUFFIX}")))

    def test_declared_version_differs_from_the_installed_one(self):
        self.install()
        f = self.write("app.py", "from requests import Session\n")
        self.write("requirements.txt", "requests==2.31.0\n")
        text = libdocs.section(self.board, self.repo, [f], get=FakeHttp(), env={})
        self.assertIn("requests: 宣言の版 2.31.0 と入っている版 2.32.3 が違う（入っている版で引いた）", text)

    def test_record_keeps_the_version_read_and_no_doc_text(self):
        self.install()
        f = self.write("app.py", "from requests import Session\n")
        libdocs.section(self.board, self.repo, [f], get=self.all_http(), env={})
        rec = json.loads((self.board.dir / "r1" / libdocs.RECORD).read_text(encoding="utf-8"))
        row = rec["rows"][0]
        self.assertEqual(row["local"]["version"], "2.32.3")
        self.assertEqual(row["official"]["status"], "ok")
        self.assertNotIn("LOCAL DOCSTRING", json.dumps(rec))


class RedirectCase(unittest.TestCase):
    def test_redirects_keep_the_key_on_the_same_host_only_and_refuse_http(self):
        import urllib.request
        req = urllib.request.Request(libdocs.API + "/v2/libs/search", headers={"Authorization": "Bearer ctx7sk-k"})
        h = libdocs.SafeRedirect()
        other = h.redirect_request(req, None, 302, "Found", {}, "https://elsewhere.example/x")
        self.assertNotIn("Authorization", other.headers, "host が替わる転送では鍵を落とす")
        same = h.redirect_request(req, None, 302, "Found", {}, libdocs.API + "/v2/libs/search?x=1")
        self.assertEqual(same.headers.get("Authorization"), "Bearer ctx7sk-k")
        for url in ("http://elsewhere.example/x", "https://10.1.2.3/x"):
            with self.subTest(url=url):
                self.assertIsNone(h.redirect_request(req, None, 302, "Found", {}, url))


class ComposerCase(Base):
    def test_fix_prompt_carries_the_section(self):
        import fixrules
        vals = {k: "" for k in fixrules.FIX_VALUES}
        f = self.write("app.py", "import requests\n")
        sec = libdocs.section(self.board, self.repo, [f], get=ok_http(), env={})
        text = fixrules.fix_prompt(vals, libdocs=sec)
        self.assertIn(libdocs.TITLE, text)
        self.assertIn('"id": "libdocs"', text)
        self.assertNotIn(libdocs.TITLE, fixrules.fix_prompt(vals))

    def test_plan_head_carries_the_section(self):
        import planblk
        f = self.write("app.py", "import requests\n")
        sec = libdocs.section(self.board, self.repo, [f], get=ok_http(), env={})
        for role in planblk.ROLES:
            with self.subTest(role):
                self.assertIn(libdocs.TITLE, planblk.head(role, "", sec))
                self.assertNotIn(libdocs.TITLE, planblk.head(role, ""))

    def test_fix_prep_section_uses_unit_files_and_the_network_mock(self):
        """修正役の支度（fixrules.lib_section）: 単位のファイルから見つけ、網の口（http_get）で引き、節を返す"""
        import fixrules
        from unittest import mock
        self.write("app.py", "import requests\n")
        judgment = self.tmp / "judgment.json"
        judgment.write_text(json.dumps({"units": [{"key": "app.py: 例", "label": "block"}]}), encoding="utf-8")
        vals = {"judgment_file": str(judgment), "open_units": json.dumps(["app.py: 例"])}
        http = ok_http()
        with mock.patch.object(libdocs, "unit_files", return_value=(["app.py"], "")) as uf, \
                mock.patch.object(libdocs, "http_get", http):
            text = fixrules.lib_section(self.board, self.repo, vals)
        self.assertEqual(uf.call_args.args[2], {"app.py: 例"}, "直す義務の単位だけを見る")
        self.assertIn("取れた 1 本", text)
        self.assertTrue(http.calls)

    def test_plan_prep_section_reads_the_judgment_on_the_board(self):
        import planblk
        from unittest import mock
        self.write("app.py", "import requests\n")
        (self.board.dir / "out").mkdir(parents=True)
        (self.board.dir / "out" / "diagnose.json").write_text(json.dumps({"units": []}), encoding="utf-8")
        self.board.state = {"outputs": {"p2.diagnose": {"file": "out/diagnose.json"}}}
        with mock.patch.object(libdocs, "unit_files", return_value=(["app.py"], "")) as uf, \
                mock.patch.object(libdocs, "http_get", ok_http()):
            text = planblk.lib_section(self.board, self.repo)
        self.assertEqual(uf.call_args.args[1], str(self.board.dir / "out" / "diagnose.json"))
        self.assertIn("取れた 1 本", text)
        self.board.state = {"outputs": {}}
        self.assertIn("判定の出力が盤面に無い", planblk.lib_section(self.board, self.repo))


class SharedCacheCase(Base):
    """run をまたぐ控え（利用の家の包みの家 WORKS_ADAPTER_HOME の下 libdocs/）: 同じ家のほかの run が取った物を TTL の間は網に出ずに
    使い、枠切れ（429）の印も QUOTA_HOLD の間はほかの run に効かせる（run ごとに同じライブラリで枠を使い切っていた。利用者の家で
    4 つの run の r1/libdocs/_quota.json が月の枠切れ）"""
    T = 1_800_000_000.0

    def setUp(self):
        super().setUp()
        self.home = self.tmp / "adapter-home"
        self.env = {libdocs.SHARED_ENV: str(self.home)}
        self.f = self.write("app.py", "import requests\n")
        self.write("requirements.txt", "requests==2.32.3\n")

    def run_section(self, board_name, http, now):
        board = FakeBoard(self.tmp / board_name)
        return board, libdocs.section(board, self.repo, [self.f], get=http, env=self.env, now=now)

    def test_later_run_uses_the_shared_cache_without_the_network(self):
        self.run_section("run1", ok_http(), self.T)
        http = FakeHttp()
        board, text = self.run_section("run2", http, self.T + 3600)
        self.assertEqual(http.calls, [])
        self.assertIn("ほかの run の控えから 1 本", text)
        self.assertIn("s = requests.Session()", text)
        self.assertTrue(list((board.dir / "r1" / libdocs.CACHE_DIR).glob("requests@2.32.3*.json")),
                        "使った物は盤面の周の置き場にも写す（run の中で同じ物を読む）")

    def test_cache_is_keyed_by_the_query_symbols(self):
        """問い（query）は単位のファイルが使う名を持ち、Context7 は問いに合う断片を返す。名の違う問いの run は前の run の控えを
        使わずに取り直し、同じ問いの run は使う（控えの名に問いの digest を入れる）"""
        self.run_section("run1", ok_http(), self.T)
        self.f = self.write("app.py", "from requests import Session, adapters\n")
        http = ok_http()
        self.run_section("run2", http, self.T + 60)
        self.assertTrue([u for u in http.calls if "/v2/context" in u], "名の違う問いは取り直す")
        again = FakeHttp()
        _, text = self.run_section("run3", again, self.T + 120)
        self.assertEqual(again.calls, [], "同じ問いは家の控えを使う")
        self.assertIn("ほかの run の控えから 1 本", text)

    def test_not_found_is_kept_per_library_whatever_the_query(self):
        """Context7 に無いライブラリは問いに依らない: 名の違う問いの run も、前の run の『無い』の控えを使って網に出ない（匿名の
        枠を名の組ごとに使い直さない）。前の版の名だけの控えの ok は、問いを見ていないので使わない"""
        self.run_section("run1", FakeHttp(), self.T)   # 何を問うても 404（Context7 に無い）
        self.f = self.write("app.py", "from requests import Session, adapters\n")
        http = FakeHttp()
        _, text = self.run_section("run2", http, self.T + 60)
        self.assertEqual(http.calls, [], "無いと分かったライブラリは問いが違っても問い直さない")
        self.assertIn("Context7 に無い 1 本", text)
        sd = self.home / libdocs.CACHE_DIR
        for p in sd.glob("*.json"):
            p.unlink()
        old = {"schema": libdocs.SCHEMA, "lib": {}, "status": "ok", "id": "/psf/requests", "version_note": "",
               "snippets": [], "at": self.T}
        (sd / "requests@2.32.3.json").write_text(json.dumps(old), encoding="utf-8")
        http = ok_http()
        self.run_section("run3", http, self.T + 120)
        self.assertTrue([u for u in http.calls if "/v2/context" in u], "問いを見ていない前の版の ok の控えは使わない")

    def test_shared_cache_expires_after_the_ttl(self):
        self.run_section("run1", ok_http(), self.T)
        http = ok_http()
        _, text = self.run_section("run2", http, self.T + libdocs.SHARED_TTL + 1)
        self.assertTrue([u for u in http.calls if "/v2/context" in u], "TTL を過ぎた控えは使わずに取り直す")
        self.assertIn("ほかの run の控えから 0 本", text)

    def test_no_home_means_no_shared_cache(self):
        self.env = {}
        self.run_section("run1", ok_http(), self.T)
        http = ok_http()
        self.run_section("run2", http, self.T + 60)
        self.assertTrue(http.calls, "家が無ければ run ごとの控えだけ（今までどおり）")
        self.assertFalse(self.home.exists())

    def test_failures_are_not_shared(self):
        self.run_section("run1", FakeHttp({"/v2/libs/search": (500, {"error": "boom"})}), self.T)
        http = ok_http()
        _, text = self.run_section("run2", http, self.T + 60)
        self.assertTrue(http.calls)
        self.assertIn("取れた 1 本", text)

    def test_broken_shared_entry_is_ignored(self):
        self.run_section("run1", ok_http(), self.T)
        for p in (self.home / libdocs.CACHE_DIR).glob("requests@*.json"):
            p.write_text("{not json", encoding="utf-8")
        http = ok_http()
        _, text = self.run_section("run2", http, self.T + 60)
        self.assertTrue(http.calls)
        self.assertIn("取れた 1 本", text)

    def test_quota_mark_holds_other_runs_for_a_window_then_retries(self):
        quota = FakeHttp({"/v2/libs/search": (429, {"error": "Quota Exceeded", "message": "Monthly quota exceeded"})})
        self.run_section("run1", quota, self.T)
        held = FakeHttp()
        board, text = self.run_section("run2", held, self.T + 3600)
        self.assertEqual(held.calls, [], "窓の間はほかの run も網に出ない")
        self.assertEqual(text.splitlines()[1], libdocs.QUOTA_NOTICE)
        self.assertIn("枠切れで取らなかった 1 本", text)
        self.assertIn("- 枠切れの印: ほかの run が ", text)
        self.assertIsNotNone(libdocs.notice(board), "盤面にも印を写す（報告の冒頭の 1 行が読む）")
        later = ok_http()
        _, text = self.run_section("run3", later, self.T + libdocs.QUOTA_HOLD + 1)
        self.assertTrue(later.calls, "窓を過ぎたら問い合わせ直す")
        self.assertIn("取れた 1 本", text)

    def test_anonymous_quota_mark_does_not_hold_a_keyed_run(self):
        quota = FakeHttp({"/v2/libs/search": (429, {"error": "Quota Exceeded", "message": "Monthly quota exceeded"})})
        self.run_section("run1", quota, self.T)
        self.env = {**self.env, libdocs.ENV_KEY: "ctx7sk-test"}
        keyed = ok_http()
        _, text = self.run_section("run2", keyed, self.T + 60)
        self.assertTrue(keyed.calls, "鍵なしの枠切れは鍵の在る起動を止めない（上限が別）")
        self.assertIn("取れた 1 本", text)
        self.assertNotIn("ctx7sk", "".join(p.read_text(encoding="utf-8") for p in (self.home / libdocs.CACHE_DIR).glob("*.json")),
                         "鍵の値は控えに書かない")

    def test_quota_mark_does_not_flag_a_run_served_from_the_shared_cache(self):
        self.run_section("run1", ok_http(), self.T)
        quota = FakeHttp({"/v2/libs/search": (429, {"error": "Quota Exceeded", "message": "Monthly quota exceeded"})})
        f2 = self.write("other.py", "import flask\n")
        libdocs.section(FakeBoard(self.tmp / "run1b"), self.repo, [f2], get=quota, env=self.env, now=self.T + 10)
        held = FakeHttp()
        board, text = self.run_section("run2", held, self.T + 60)
        self.assertEqual(held.calls, [])
        self.assertIn("取れた 1 本", text)
        self.assertIsNone(libdocs.notice(board), "家の控えで全部取れた run に枠切れの印を立てない")
        self.assertNotIn(libdocs.QUOTA_NOTICE, text)


if __name__ == "__main__":
    unittest.main()
