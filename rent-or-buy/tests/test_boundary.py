"""境目の 4 つの決まり（設計書 1.1）。外れたら赤にする。"""
import ast
import pathlib
import re
import sys
import unittest

PLUGIN = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PLUGIN))
import rent_or_buy  # noqa: E402


def sources(folder):
    return [(p, p.read_text(encoding="utf-8")) for p in sorted(folder.glob("*.py"))]


def imports(tree):
    """(モジュール名, 取り込む名前の一覧, 相対か) を並べる。"""
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                yield a.name, [], False
        elif isinstance(node, ast.ImportFrom):
            yield node.module or "", [a.name for a in node.names], node.level > 0


class BoundaryTest(unittest.TestCase):
    def test_1_algorithm_reads_only_stdlib_and_itself(self):
        for path, text in sources(PLUGIN / "rent_or_buy"):
            for mod, _, relative in imports(ast.parse(text)):
                top = mod.split(".")[0]
                self.assertTrue(relative or top in sys.stdlib_module_names or top == "rent_or_buy", (path.name, mod))

    def test_2_cache_layer_uses_only_the_public_names(self):
        public = set(rent_or_buy.__all__)
        for path, text in sources(PLUGIN / "prompt_cache"):
            for mod, names, _ in imports(ast.parse(text)):
                if mod.split(".")[0] == "rent_or_buy":
                    self.assertEqual(mod, "rent_or_buy", "中のファイルを直に読んでいる: %s %s" % (path.name, mod))
                    self.assertLessEqual(set(names), public, (path.name, names))

    def test_3_nothing_outside_imports_the_modules(self):
        root = PLUGIN.parent
        pat = re.compile(r"^\s*(from|import)\s+(rent_or_buy|prompt_cache)\b", re.M)
        skip = {".git", "node_modules", "__pycache__"}
        hits = []
        for p in root.rglob("*.py"):
            rel = p.relative_to(root)
            if rel.parts[0] == PLUGIN.name or skip & set(rel.parts):
                continue
            if pat.search(p.read_text(encoding="utf-8", errors="replace")):
                hits.append(str(rel))
        self.assertEqual(hits, [], "プラグインの外は bin/rent-or-buy を通す")

    def test_4_algorithm_has_no_claude_words(self):
        words = re.compile(r"claude|token|cache|compact|keepalive", re.I)
        for path, text in sources(PLUGIN / "rent_or_buy"):
            self.assertIsNone(words.search(text), "%s に Claude の語: %s" % (path.name, words.search(text)))


if __name__ == "__main__":
    unittest.main()
