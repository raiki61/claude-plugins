"""境目の 4 つの決まり（プラグインの docs/design.md の 2.1）。外れたら赤にする。各決まりは、検査する関数を違反の見本に当てて赤になることも確かめる。"""
import ast
import pathlib
import re
import sys
import unittest

PLUGIN = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PLUGIN))
import rent_or_buy  # noqa: E402

SKIP_DIRS = {".git", "node_modules", "__pycache__"}
WORDS = re.compile(r"claude|token|cache|compact|keepalive|キャッシュ|トークン|要約", re.I)
# Python の読み込みの形だけを見る（設計書や README が名前を文で書くのは構わない）
IMPORT_FORM = re.compile(
    r"^\s*(from|import)\s+(rent_or_buy|prompt_cache)\b|import_module\(\s*[\"'](rent_or_buy|prompt_cache)\b", re.M)


def sources(folder):
    found = [(p, p.read_text(encoding="utf-8")) for p in sorted(folder.rglob("*.py")) if "__pycache__" not in p.parts]
    assert found, "%s に .py が 1 つも無い（検査が空振りしている）" % folder
    return found


def imports(tree):
    """(モジュール名, 取り込む名前の一覧, 相対の段数) を並べる。"""
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                yield a.name, [], 0
        elif isinstance(node, ast.ImportFrom):
            yield node.module or "", [a.name for a in node.names], node.level


def check_algorithm_imports(tree):
    """決まり 1: 標準ライブラリと自分だけ。相対は 1 段（同じフォルダの中）まで。"""
    bad = []
    for mod, _, level in imports(tree):
        if level > 1:
            bad.append("relative level %d" % level)
        elif level == 0 and mod.split(".")[0] not in sys.stdlib_module_names | {"rent_or_buy"}:
            bad.append(mod)
    return bad


def check_public_names_only(tree, public):
    """決まり 2: rent_or_buy は表の口の名前だけ。from の形と、import した名前の属性アクセスの両方を見る。"""
    bad, aliases = [], set()
    for mod, names, _ in imports(tree):
        if mod.split(".")[0] == "rent_or_buy":
            if mod != "rent_or_buy":
                bad.append("inner module %s" % mod)
            bad += [n for n in names if n not in public]
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            aliases |= {a.asname or a.name for a in node.names if a.name == "rent_or_buy"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id in aliases:
            if node.attr not in public:
                bad.append("rent_or_buy.%s" % node.attr)
        elif isinstance(node, ast.ImportFrom) and node.level > 0:
            # prompt_cache の中の `from .. import rent_or_buy`（相対で外の口を取る形）
            if node.level >= 2 and any(a.name == "rent_or_buy" for a in node.names):
                bad.append("relative import of rent_or_buy")
        elif isinstance(node, ast.Call) and node.args and isinstance(node.args[0], ast.Constant):
            fn, arg = node.func, node.args[0].value
            if isinstance(fn, ast.Name) and fn.id == "__import__" and isinstance(arg, str) and arg.split(".")[0] == "rent_or_buy" and arg != "rent_or_buy":
                bad.append("inner module %s" % arg)
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "getattr"
                and len(node.args) >= 2 and isinstance(node.args[0], ast.Name) and node.args[0].id in aliases
                and isinstance(node.args[1], ast.Constant) and node.args[1].value not in public):
            bad.append("rent_or_buy.%s" % node.args[1].value)
    return bad


def check_no_outside_import(text):
    """決まり 3: プラグインの外の文書・コードが Python で読み込んでいないか。"""
    return [m.group(0).strip() for m in IMPORT_FORM.finditer(text)]


def check_no_claude_words(text):
    """決まり 4: アルゴリズムに Claude の語を書かない。"""
    m = WORDS.search(text)
    return [m.group(0)] if m else []


def text_files_outside(root, plugin):
    for p in sorted(root.rglob("*")):
        rel = p.relative_to(root)
        if SKIP_DIRS & set(rel.parts) or rel.parts[0] == plugin.name or p.is_symlink() or not p.is_file():
            continue
        try:
            data = p.read_bytes()
            if b"\0" in data:
                continue
            yield rel, data.decode("utf-8")
        except (OSError, UnicodeDecodeError):
            continue  # 読めない物・文字列でない物は見ない


class BoundaryTest(unittest.TestCase):
    def test_1_algorithm_reads_only_stdlib_and_itself(self):
        for path, text in sources(PLUGIN / "rent_or_buy"):
            self.assertEqual(check_algorithm_imports(ast.parse(text)), [], path.name)
        for snippet in ("import requests", "from ..prompt_cache import x", "from prompt_cache import x"):
            self.assertTrue(check_algorithm_imports(ast.parse(snippet)), snippet)
        self.assertEqual(check_algorithm_imports(ast.parse("from . import core\nimport os")), [])

    def test_2_cache_layer_uses_only_the_public_names(self):
        public = set(rent_or_buy.__all__)
        for path, text in sources(PLUGIN / "prompt_cache"):
            self.assertEqual(check_public_names_only(ast.parse(text), public), [], path.name)
        for snippet in ("from rent_or_buy.policies import fixed", "from rent_or_buy import POLICIES",
                        "import rent_or_buy\nrent_or_buy.POLICIES", "import rent_or_buy as r\nr.core",
                        "import rent_or_buy\ngetattr(rent_or_buy, 'POLICIES')",
                        "__import__('rent_or_buy.policies')", "from .. import rent_or_buy"):
            self.assertTrue(check_public_names_only(ast.parse(snippet), public), snippet)
        self.assertEqual(check_public_names_only(ast.parse("import rent_or_buy\nrent_or_buy.decide"), public), [])
        self.assertEqual(check_public_names_only(ast.parse("import rent_or_buy\ngetattr(rent_or_buy, 'decide')"), public), [])
        self.assertEqual(check_public_names_only(ast.parse("__import__('rent_or_buy')"), public), [])

    def test_3_nothing_outside_imports_the_modules(self):
        scanned, hits = 0, []
        for rel, text in text_files_outside(PLUGIN.parent, PLUGIN):
            scanned += 1
            if check_no_outside_import(text):
                hits.append(str(rel))
        self.assertGreater(scanned, 0, "検査が空振りしている")
        self.assertEqual(hits, [], "プラグインの外は bin/rent-or-buy を通す")
        for snippet in ("import rent_or_buy", "  from prompt_cache.prices import x",
                        "importlib.import_module('prompt_cache')"):
            self.assertTrue(check_no_outside_import(snippet), snippet)
        self.assertEqual(check_no_outside_import("the rent_or_buy module imports nothing"), [])

    def test_4_algorithm_has_no_claude_words(self):
        for path, text in sources(PLUGIN / "rent_or_buy"):
            self.assertEqual(check_no_claude_words(text), [], path.name)
        for snippet in ("# Claude", "token = 1", "キャッシュ", "トークン", "要約", "x = 'compact'", "keepalive"):
            self.assertTrue(check_no_claude_words(snippet), snippet)


if __name__ == "__main__":
    unittest.main()
