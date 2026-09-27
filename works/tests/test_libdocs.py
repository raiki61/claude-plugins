"""ライブラリの今の文書（.shared/core/libdocs.py。Context7 の HTTP API を機械が引いて指示書に貼る）の検査。

網には出ない（HTTP の口は偽物を渡す）。盤面は周の置き場（dir・work）だけを持つ偽物。
- 見つけ方: 単位のファイルの import（Python・JS/TS）から標準ライブラリとリポジトリの中の物を除き、依存の宣言
  （pyproject.toml・requirements*.txt・package.json）から版を引く。宣言のファイル自体が単位なら宣言の全部が対象
- 取り方: libs/search で id と版を決め、context（type=json）で断片を取る。版が Context7 に在ればその版を指す
- 盤面の控え: 取れた物（と Context7 に無い物）はライブラリ＋版の鍵で周の置き場に書き、次は網に出ない（前の周の控えも読む）
- 数で言う: 取れなかった・Context7 に無い・版が無い・上限で取らない物は節の頭に数と名前で出す（黙って落とさない）
- 標準ライブラリだけの対象は何も取らず、取らないことを書く。WORKS_CONTEXT7=off も取らないことを書く
- 組み立て: 修正役の指示書（fixrules.fix_prompt）と修正案の役の頭（planblk.head）に節が入る
"""
import json
import pathlib
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
                return code, json.dumps(doc).encode()
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
        self.assertIn("取れなかった 1 本", text)
        self.assertIn("requests（HTTP 429", text)
        self.assertIn("Context7 に無い 1 本", text)
        self.assertIn("flask", text)
        self.assertFalse(list(self.board.dir.glob(f"r*/{libdocs.CACHE_DIR}/requests@*.json")), "失敗は控えない（次に取り直す）")

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
        self.assertTrue(all(h.get("Authorization") == "Bearer ctx7sk-test" for _, h in seen))
        self.assertTrue(all("ctx7sk" not in u for u, _ in seen))


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


if __name__ == "__main__":
    unittest.main()
