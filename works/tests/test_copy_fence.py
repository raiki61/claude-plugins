"""写しの柵（道具 .shared/core/copyfence.py・表 docs/copies.json）。

名前の付いた考えの柵（docs/concepts.json）は、地図に名の在る考えの漏れだけを見る。名の無い中身の写し（同じ行の並びを別の所に
貼った物）はそこを素通りするので、言語に依らない行の窓で見る: 行の頭と尾の空白を落とし、空行と注記だけの行（頭が #・//・/*・*・
<!-- など）を飛ばした「正規化した行」の、表の window 行の並びが、木の 2 か所以上（別のファイルでも同じファイルでも）に在れば写しと
数える。ファイルごとに写しに掛かった正規化した行の数を、表の既知（パス → [行の数, 理由]）とちょうど揃うかで見る（増えても・減っても・
表に無いファイルが出ても赤。減る向きにだけ動かす。考えの柵と同じ型）。表そのものも main の表より既知の行の数の和が増えない。
見ない所（表の exclude。グロブ → 理由）は、元の写しを変えない約束の写し・作った物・記録した材料。
"""
import pathlib
import subprocess
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.dont_write_bytecode = True
if str(ROOT / ".shared" / "core") not in sys.path:
    sys.path.insert(0, str(ROOT / ".shared" / "core"))
TABLE = "docs/copies.json"   # works 自身の写しの柵の表（道具は置き場を持たない）


def cpf():
    import copyfence   # 柵の中身（遅らせて読む。無ければその試験だけが落ちる）
    return copyfence


BLOCK = "".join(f"value_{i} = compute({i}, 'x')\n" for i in range(10))


class Synthetic(unittest.TestCase):
    """仮の置き場で柵そのものを見る（git を使わず、scan にパスの一覧を渡す）"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def put(self, rel, text):
        p = self.root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
        return rel

    def scan(self, *paths, window=10, exclude=None):
        return cpf().scan(self.root, list(paths), window, exclude or {})

    def test_same_run_in_two_files_counts_both(self):
        """空白の違い・空行・注記だけの行を挟んでも同じ並びと見て、両方のファイルに行の数が付く"""
        a = self.put("a.py", "head_a()\n" + BLOCK + "tail_a()\n")
        spaced = "".join(("    " + ln + "  \n\n# 注記\n// note\n") for ln in BLOCK.splitlines())
        b = self.put("b.txt", "head_b\n" + spaced + "tail_b\n")
        self.assertEqual(self.scan(a, b), {a: 10, b: 10})

    def test_shorter_than_window_is_not_a_copy(self):
        nine = "".join(BLOCK.splitlines(keepends=True)[:9])
        a, b = self.put("a.py", nine + "x\n"), self.put("b.py", nine + "y\n")
        self.assertEqual(self.scan(a, b), {})

    def test_repeat_inside_one_file_counts(self):
        a = self.put("a.yaml", BLOCK + "middle: 1\n" + BLOCK)
        self.assertEqual(self.scan(a), {a: 20})

    def test_excluded_paths_are_not_read(self):
        a, b = self.put("a.py", BLOCK), self.put("copy/b.py", BLOCK)
        self.assertEqual(self.scan(a, b, exclude={"copy/**": "元の写し"}), {})

    def test_new_copy_not_on_known_list_is_red(self):
        a, b = self.put("a.py", BLOCK), self.put("b.py", BLOCK)
        found = self.scan(a, b)
        self.assertEqual(cpf().verdict(found, {a: [10, "理由"], b: [10, "理由"]}), [])
        self.assertTrue(cpf().verdict(found, {a: [10, "理由"]}))       # b は表に無い
        self.assertTrue(cpf().verdict({}, {a: [10, "理由"]}))          # 直ったのに表が残る

    def test_growth_is_the_known_total(self):
        m = cpf()
        main = {"known": {"a.py": [10, "x"]}}
        self.assertEqual(m.growth(main, {"known": {"a.py": [10, "x"]}}), [])
        self.assertEqual(m.growth(main, {"known": {"b.py": [8, "y"]}}), [])
        self.assertTrue(m.growth(main, {"known": {"a.py": [10, "x"], "b.py": [1, "y"]}}))
        self.assertEqual(m.growth(None, {"known": {"a.py": [99, "x"]}}), [])   # main に表が無い（初めて掛ける柵）


class TableHolds(unittest.TestCase):
    """本物の works の木: 写しは表の既知とちょうど揃う"""

    def setUp(self):
        self.m = cpf()
        self.table = self.m.load(ROOT / TABLE)

    def test_table_shape(self):
        self.assertIsInstance(self.table["window"], int)
        self.assertGreaterEqual(self.table["window"], 6)
        for glob, why in self.table["exclude"].items():
            with self.subTest(exclude=glob):
                self.assertTrue(why.strip(), "見ない所に理由が無い")
        for path, (n, why) in self.table["known"].items():
            with self.subTest(known=path):
                self.assertGreater(n, 0)
                self.assertTrue(why.strip(), "既知の写しに理由が無い")

    def test_excludes_are_live(self):
        """見ない所のグロブは、どれも追跡されたファイルに当たる（当たらない行は消す）"""
        paths = self.m.tracked(ROOT)
        for glob in self.table["exclude"]:
            with self.subTest(glob):
                self.assertTrue(any(self.m.hit(p, [glob]) for p in paths), "どのファイルにも当たらない")

    def test_copies_match_known(self):
        found = self.m.scan(ROOT, self.m.tracked(ROOT), self.table["window"], self.table["exclude"])
        self.assertEqual(self.m.verdict(found, self.table["known"]), [],
                         "写しが表の既知と揃わない。新しい写しは 1 か所へ寄せる（寄せられない訳があれば理由つきで表に置く）。"
                         "減った所は表を減らす")


class NotAboveMain(unittest.TestCase):
    """表の既知の行の数の和が main の表（origin/main の docs/copies.json）より増えない。main に表が無ければ初めて掛ける柵なので比べない"""

    def test_known_not_above_main(self):
        m = cpf()
        if subprocess.run(["git", "-C", str(ROOT), "rev-parse", "--verify", f"{m.MAIN_REF}^{{commit}}"],
                          capture_output=True).returncode != 0:
            self.skipTest(f"SKIP git-history: {m.MAIN_REF} を引けない（浅い clone か ref が無い）")
        self.assertEqual(m.growth(m.main_table(ROOT, TABLE), m.load(ROOT / TABLE)), [])


if __name__ == "__main__":
    unittest.main()
