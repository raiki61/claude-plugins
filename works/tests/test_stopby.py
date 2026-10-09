"""止めの理由の住処（.shared/core/stopby.py。考え stop-reasons）の検査。

表の名と定数が揃うこと・ブロックとラインが足す口（declare）の決まり・pack の中の declare の名が重ならないこと・
語の字が変わっていないこと（盤面・報告・固定材料に残る字。前の盤面の止めを読み違えない）・住処の外に語の字が漏れないことを見る。
関数を直に呼ぶのと、pack の .py を ast で読むだけ（git ls-files のほか、盤面・子のプロセスなし）。
"""
import ast
import pathlib
import sys
import unittest

TESTS = pathlib.Path(__file__).resolve().parent
ROOT = TESTS.parent
CORE = ROOT / ".shared" / "core"
sys.dont_write_bytecode = True
sys.path.insert(0, str(CORE))
sys.path.insert(0, str(TESTS))

# 盤面の state.stop.by などに残る語の字（住処へ寄せる前の 7aa922e0 の木の定数と字の値。変えると前の盤面を読み違える）
WORDS = frozenset({
    "works:adapter", "works:ci", "works:conflict", "works:delta", "works:empty-fix", "works:fix", "works:lens",
    "works:plan-converge", "works:pr", "works:premises", "works:purpose", "works:refix", "works:rejudge",
    "works:rejudge-session", "works:replan", "works:scope-check",
    # ブロックとラインが declare で足す語
    "works:judge", "works:judge-verify", "works:fix-accept", "works:rule-give-up", "works:eyes", "works:spec",
    "works:material", "works:plan", "works:protected", "works:judge-bridge", "works:pending-request",
})
SKIP = (".shared/core/graphloops/", ".shared/borrow/")


def stopby():
    import stopby as m   # 住処（遅らせて読む。無ければその試験だけが落ちる）
    return m


def pack_py():
    """pack（dev・tests・docs と写しの外）の .py"""
    for p in sorted(ROOT.rglob("*.py")):
        rel = p.relative_to(ROOT).as_posix()
        if rel.split("/")[0] in ("dev", "tests", "docs") or rel.startswith(SKIP):
            continue
        yield rel, ast.parse(p.read_text(encoding="utf-8"))


def declares():
    """[(ファイル, 名, 意味)]: pack の stopby.declare("名", "意味") の呼び出し（字の定数だけ）"""
    out = []
    for rel, tree in pack_py():
        for n in ast.walk(tree):
            if (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "declare"
                    and isinstance(n.func.value, ast.Name) and n.func.value.id == "stopby"):
                args = [a.value if isinstance(a, ast.Constant) else None for a in n.args]
                out.append((rel, *args))
    return out


class Table(unittest.TestCase):
    def test_constants_match_table(self):
        """定数はちょうど表の名に頭を付けた語（名の - は _、大文字）"""
        m = stopby()
        consts = {k: v for k, v in vars(m).items() if k.isupper() and isinstance(v, str) and v.startswith(m.HEAD) and v != m.HEAD}
        self.assertEqual(consts, {n.upper().replace("-", "_"): m.HEAD + n for n in m.REASONS})
        for n, why in m.REASONS.items():
            self.assertTrue(m.NAME.fullmatch(n), n)
            self.assertTrue(why.strip(), n)

    def test_word_refuses_unknown(self):
        with self.assertRaises(KeyError):
            stopby().word("no-such-reason")

    def test_is_line(self):
        m = stopby()
        self.assertTrue(m.is_line(m.FIX))
        for by in ("human:final-gate", "request:me", "answer", "hand-placed", "", None, 3):
            self.assertFalse(m.is_line(by), by)


class Declare(unittest.TestCase):
    def setUp(self):
        self.m = stopby()
        saved = dict(self.m._DECLARED)   # 足した名を試験の外へ持ち越さない（読み込んだブロックが足した名は戻す）
        self.m._DECLARED.clear()

        def back():
            self.m._DECLARED.clear()
            self.m._DECLARED.update(saved)
        self.addCleanup(back)

    def test_declare_returns_word_and_is_idempotent(self):
        self.assertEqual(self.m.declare("t-own", "試験の語"), "works:t-own")
        self.assertEqual(self.m.declare("t-own", "試験の語"), "works:t-own")   # 読み直し（reload・2 度の import）
        self.assertEqual(self.m.declared(), {"t-own": "試験の語"})
        self.assertEqual(self.m.word("t-own"), "works:t-own")

    def test_declare_refuses(self):
        self.m.declare("t-own", "試験の語")
        for name, meaning in (("t-own", "別の意味"), ("fix", "修正の段"), ("Bad", "x"), ("a--b", "x"), ("t-x", " "),
                              ("works:x", "x")):
            with self.subTest(name=name), self.assertRaises(ValueError):
                self.m.declare(name, meaning)


class Pack(unittest.TestCase):
    def test_declares_are_literal_unique_and_outside_table(self):
        """pack の declare は字の定数で、名は 1 つの持ち主だけが足し、core の表の名でない"""
        m = stopby()
        rows = declares()
        self.assertTrue(rows)
        for rel, name, meaning in rows:
            with self.subTest(file=rel, name=name):
                self.assertIsInstance(name, str)
                self.assertIsInstance(meaning, str)
                self.assertTrue(m.NAME.fullmatch(name), name)
                self.assertNotIn(name, m.REASONS)
        owners = {}
        for rel, name, _ in rows:
            owners.setdefault(name, set()).add(rel)
        self.assertEqual({n: f for n, f in owners.items() if len(f) > 1}, {})

    def test_words_unchanged(self):
        """表と declare の語の字は寄せる前と同じ"""
        m = stopby()
        got = {m.HEAD + n for n in m.REASONS} | {m.HEAD + n for _, n, _ in declares()}
        self.assertEqual(got, WORDS)

    def test_attributes_exist(self):
        """pack が引く stopby.<名> は住処に在る（字の誤りを走る前に見る）"""
        m = stopby()
        for rel, tree in pack_py():
            for n in ast.walk(tree):
                if isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name) and n.value.id == "stopby":
                    with self.subTest(file=rel, attr=n.attr):
                        self.assertTrue(hasattr(m, n.attr))


class Fence(unittest.TestCase):
    def test_stop_words_live_in_stopby(self):
        """柵の表の stop-reasons（語の字・住処の定数を別の名に写す）が住処の外で既知の漏れと揃う"""
        import conceptfence as cf
        table = cf.load(ROOT)
        row = table["concepts"]["stop-reasons"]
        self.assertEqual(row["status"], "住処あり")
        paths = cf.tracked(ROOT)
        for f in row["fences"]:
            self.assertIn(".shared/core/stopby.py", f["allowed"])
            self.assertEqual(cf.verdict(cf.scan(ROOT, paths, f, table["exclude"]), f["known"]), [], f["what"])


if __name__ == "__main__":
    unittest.main()
