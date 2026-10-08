"""手元に入っている版のライブラリの文書（.shared/core/libdocs_local.py）の検査。

一時の置き場に偽の仮想環境（.venv/lib/python3.x/site-packages）と node_modules を作って読む（網・git・子のプロセスなし）。
- 使う名: 単位のファイルの import と、import した名の属性（requests.get）を ast で拾う。JS は名の import と名前空間の属性
- 探し方: 単位のファイルの置き場から根まで上へ辿り、各段の .venv・venv・.tox/*・.nox/*・node_modules を見る。根は run の作業
  ツリーと、同じ git の main の作業ツリー（.git のファイルの gitdir: と commondir から。git を起こさない）
- 読み方: import しない（ast で静的に読む。__init__.py の頭の raise SystemExit が在っても読める）。再輸出（from .api import get）は
  辿る。版は dist-info の METADATA・package.json の version。環境の置き場の外を指す symlink は読まない
"""
import json
import os
import pathlib
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.dont_write_bytecode = True
sys.path.insert(0, str(ROOT / ".shared" / "core"))

import libdocs_local  # noqa: E402

REQ_INIT = '''raise SystemExit("imported the target's library")
"""Requests HTTP Library."""
from .api import get, post
from . import sessions
from .sessions import Session
__version__ = "2.32.3"
'''
REQ_API = '''"""requests.api: the API."""
from . import sessions


def get(url, params=None, **kwargs):
    r"""Sends a GET request.

    :param url: URL for the new :class:`Request` object.
    :return: :class:`Response <Response>` object
    """
    return request("get", url, params=params, **kwargs)


def post(url, data=None, json=None, **kwargs):
    """Sends a POST request."""


def _private():
    pass
'''
REQ_SESSIONS = '''class Session(SessionRedirectMixin):
    """A Requests session.

    Provides cookie persistence, connection-pooling, and configuration.
    """

    def __init__(self):
        self.headers = {}

    def get(self, url: str, **kwargs) -> "Response":
        """Sends a GET request. Returns :class:`Response` object."""

    def mount(self, prefix, adapter):
        """Registers a connection adapter to a prefix."""

    def _hidden(self):
        pass
'''


def write(base, rel, text):
    p = pathlib.Path(base) / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    return p


class Base(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = pathlib.Path(self._tmp.name).resolve()
        self.repo = self.tmp / "repo"
        self.repo.mkdir()

    def tearDown(self):
        self._tmp.cleanup()

    def venv(self, base=None, rel=".venv"):
        sp = (base or self.repo) / rel / "lib" / "python3.12" / "site-packages"
        write(sp, "requests/__init__.py", REQ_INIT)
        write(sp, "requests/api.py", REQ_API)
        write(sp, "requests/sessions.py", REQ_SESSIONS)
        write(sp, "requests-2.32.3.dist-info/METADATA", "Metadata-Version: 2.1\nName: requests\nVersion: 2.32.3\n"
                                                         "Summary: Python HTTP for Humans.\n\nlong text\n")
        write(sp, "PyYAML-6.0.1.dist-info/METADATA", "Metadata-Version: 2.1\nName: PyYAML\nVersion: 6.0.1\n")
        write(sp, "PyYAML-6.0.1.dist-info/top_level.txt", "_yaml\nyaml\n")
        write(sp, "yaml/__init__.py", "from .loader import *\n\ndef safe_load(stream):\n    \"\"\"Parse the first YAML document.\"\"\"\n")
        return sp

    def node(self, base=None):
        nm = (base or self.repo) / "node_modules"
        write(nm, "zod/package.json", json.dumps({"name": "zod", "version": "3.23.8", "types": "./index.d.ts"}))
        write(nm, "zod/index.d.ts", 'export * from "./lib/types";\nexport { z } from "./lib/external";\n')
        write(nm, "zod/lib/types.d.ts",
              "/**\n * Creates an object schema.\n */\nexport declare function object<T>(shape: T): ZodObject<T>;\n"
              "export declare class ZodString {\n    min(n: number): ZodString;\n    max(n: number): ZodString;\n}\n"
              "export declare function unrelated(): void;\n")
        write(nm, "zod/lib/external.d.ts", "export declare namespace z {\n    const string: () => ZodString;\n}\n")
        write(nm, "zod/README.md", "# Zod\n\nTypeScript-first schema validation with static type inference.\n")
        return nm

    def lib(self, name, lang="python", uses=(), search=None):
        return {"name": name, "search": search or name, "lang": lang, "uses": list(uses), "version": None}


class UsesCase(unittest.TestCase):
    def test_python_uses_from_imports_and_attributes(self):
        got = libdocs_local.py_uses("import requests as rq\nfrom requests.adapters import HTTPAdapter\n"
                                    "from yaml import safe_load\nimport os\nr = rq.get('x')\nrq.Session().mount('a', 1)\n")
        self.assertEqual(got["requests"], ["requests.adapters.HTTPAdapter", "requests.get", "requests.Session"])
        self.assertEqual(got["yaml"], ["yaml.safe_load"])
        self.assertIsNone(libdocs_local.py_uses("def (:\n"))

    def test_js_uses_named_and_namespace(self):
        got = libdocs_local.js_uses("import { object, ZodString as S } from 'zod';\nimport * as fs from 'node:fs';\n"
                                    "import express from 'express';\nconst app = express.Router();\n"
                                    "import * as R from '@scope/pkg/sub';\nR.pick(1);\n")
        self.assertEqual(got["zod"], ["object", "ZodString"])
        self.assertEqual(got["express"], ["default", "Router"])
        self.assertEqual(got["@scope/pkg"], ["pick"])


class PythonCase(Base):
    def test_reads_signatures_and_docstrings_without_importing(self):
        self.venv()
        write(self.repo, "app.py", "")
        got = libdocs_local.read([self.repo], self.lib("requests", uses=["requests.get", "requests.Session"]), ["app.py"])
        self.assertEqual(got["status"], "ok", got)
        self.assertEqual(got["version"], "2.32.3")
        self.assertEqual(pathlib.Path(got["where"]), self.repo / ".venv")
        text = "\n".join(f["text"] for f in got["fragments"])
        self.assertIn("def get(url, params=None, **kwargs)", text)
        self.assertIn("Sends a GET request.", text)
        self.assertIn("class Session(SessionRedirectMixin)", text)
        self.assertIn("def mount(self, prefix, adapter)", text)
        self.assertIn("def get(self, url: str, **kwargs) -> 'Response'", text)
        self.assertNotIn("_hidden", text)
        self.assertNotIn("request(", text, "関数の中身は貼らない（署名と docstring だけ）")
        titles = [f["title"] for f in got["fragments"]]
        self.assertEqual(titles, ["requests.get", "requests.Session"])
        self.assertTrue(all(f["source"].endswith((".py", ".pyi")) for f in got["fragments"]))
        self.assertTrue(all(set(f) == {"title", "source", "text"} for f in got["fragments"]), "量の数（tokens）は持たない")

    def test_dist_name_differs_from_import_name(self):
        self.venv()
        got = libdocs_local.read([self.repo], self.lib("yaml", uses=["yaml.safe_load"], search="pyyaml"), [])
        self.assertEqual((got["status"], got["version"]), ("ok", "6.0.1"))
        self.assertIn("def safe_load(stream)", got["fragments"][0]["text"])

    def test_no_uses_gives_module_docstring_and_summary(self):
        self.venv()
        got = libdocs_local.read([self.repo], self.lib("requests"), [])
        self.assertEqual(got["status"], "ok")
        text = got["fragments"][0]["text"]
        self.assertIn("Python HTTP for Humans.", text)

    def test_unresolved_name_is_said(self):
        self.venv()
        got = libdocs_local.read([self.repo], self.lib("requests", uses=["requests.nothing_here"]), [])
        self.assertEqual(got["status"], "ok")
        self.assertIn("requests.nothing_here", got["note"])

    def test_absent_when_not_installed(self):
        got = libdocs_local.read([self.repo], self.lib("requests"), ["app.py"])
        self.assertEqual(got["status"], "absent")

    def test_env_near_the_unit_file_in_a_monorepo(self):
        self.venv(rel="backend/.venv")
        got = libdocs_local.read([self.repo], self.lib("requests"), ["backend/app/main.py"])
        self.assertEqual(got["status"], "ok")
        self.assertEqual(pathlib.Path(got["where"]), self.repo / "backend" / ".venv")
        self.assertEqual(libdocs_local.read([self.repo], self.lib("requests"), ["web/x.py"])["status"], "absent",
                         "ほかの枝の下の環境は見ない（単位のファイルから根までの段だけ）")

    def test_tox_env(self):
        self.venv(rel=".tox/py312")
        self.assertEqual(libdocs_local.read([self.repo], self.lib("requests"), ["a.py"])["status"], "ok")

    def test_symlink_out_of_the_env_is_not_read(self):
        sp = self.venv()
        secret = write(self.tmp, "outside/secret.py", 'def get(url):\n    """TOP SECRET"""\n')
        api = sp / "requests" / "api.py"
        api.unlink()
        api.symlink_to(secret)
        got = libdocs_local.read([self.repo], self.lib("requests", uses=["requests.get"]), [])
        self.assertNotIn("TOP SECRET", json.dumps(got, ensure_ascii=False))

    def test_env_dir_symlinked_out_of_the_root_is_not_read(self):
        outside = self.tmp / "elsewhere"
        self.venv(base=outside)
        (self.repo / ".venv").symlink_to(outside / ".venv")
        got = libdocs_local.read([self.repo], self.lib("requests", uses=["requests.get"]), [])
        self.assertEqual(got["status"], "absent", "環境の置き場が根の外を指せば読まない")
        nm = self.node(base=outside)
        (self.repo / "node_modules").symlink_to(nm)
        self.assertEqual(libdocs_local.read([self.repo], self.lib("zod", lang="js"), [])["status"], "absent")

    def test_reports_the_distribution_name(self):
        self.venv()
        got = libdocs_local.read([self.repo], self.lib("yaml", uses=["yaml.safe_load"]), [])
        self.assertEqual((got["version"], got["dist"]), ("6.0.1", "PyYAML"), "輸入の名 yaml から配る名 PyYAML を引く")

    def test_main_worktree_is_a_root(self):
        main = self.tmp / "main"
        (main / ".git" / "worktrees" / "run1").mkdir(parents=True)
        (main / ".git" / "worktrees" / "run1" / "commondir").write_text("../..\n", encoding="utf-8")
        run = self.tmp / "run"
        run.mkdir()
        (run / ".git").write_text(f"gitdir: {main / '.git' / 'worktrees' / 'run1'}\n", encoding="utf-8")
        self.assertEqual(libdocs_local.roots(run), [run, main])
        self.assertEqual(libdocs_local.roots(main), [main], "main の作業ツリーは自分だけ")
        self.venv(base=main)
        got = libdocs_local.read(libdocs_local.roots(run), self.lib("requests"), ["app.py"])
        self.assertEqual((got["status"], pathlib.Path(got["where"])), ("ok", main / ".venv"))


class NodeCase(Base):
    def test_reads_typings_for_named_imports(self):
        self.node()
        got = libdocs_local.read([self.repo], self.lib("zod", lang="js", uses=["object", "ZodString"]), ["web/app.ts"])
        self.assertEqual((got["status"], got["version"]), ("ok", "3.23.8"))
        text = "\n".join(f["text"] for f in got["fragments"])
        self.assertIn("Creates an object schema.", text)
        self.assertIn("export declare function object<T>(shape: T): ZodObject<T>;", text)
        self.assertIn("min(n: number): ZodString;", text)
        self.assertNotIn("unrelated", text)

    def test_no_uses_gives_the_readme_excerpt(self):
        self.node()
        got = libdocs_local.read([self.repo], self.lib("zod", lang="js"), ["app.ts"])
        self.assertIn("TypeScript-first schema validation", "\n".join(f["text"] for f in got["fragments"]))

    def test_readme_symlink_out_of_node_modules_is_not_read(self):
        nm = self.node()
        secret = write(self.tmp, "outside/id_rsa", "PRIVATE KEY\n")
        (nm / "zod" / "README.md").unlink()
        (nm / "zod" / "README.md").symlink_to(secret)
        got = libdocs_local.read([self.repo], self.lib("zod", lang="js"), ["app.ts"])
        self.assertNotIn("PRIVATE KEY", json.dumps(got))

    def test_types_package(self):
        nm = self.repo / "node_modules"
        write(nm, "lodash/package.json", json.dumps({"name": "lodash", "version": "4.17.21"}))
        write(nm, "@types/lodash/package.json", json.dumps({"name": "@types/lodash", "version": "4.17.0", "types": "index.d.ts"}))
        write(nm, "@types/lodash/index.d.ts", "export declare function pick(o: object, ...k: string[]): object;\n")
        got = libdocs_local.read([self.repo], self.lib("lodash", lang="js", uses=["pick"]), ["a.js"])
        self.assertEqual(got["version"], "4.17.21")
        self.assertIn("export declare function pick", got["fragments"][0]["text"])


if __name__ == "__main__":
    unittest.main()
