"""写しの柵（道具 .shared/core/copyfence.py・表 docs/copies.json）。

名前の付いた考えの柵（docs/concepts.json）は、地図に名の在る考えの漏れだけを見る。名の無い中身の写し（同じ行の並びを別の所に
貼った物）はそこを素通りするので、言語に依らない行の窓で見る: 行の頭と尾の空白を落とし、空行と注記だけの行（頭が #・//・/*・*・
<!-- など）を飛ばした「正規化した行」の、表の window 行の並びが、木の 2 か所以上（別のファイルでも同じファイルでも）に在れば写しと
数える。ファイルごとに写しに掛かった正規化した行の数を、表の既知（パス → [行の数, 理由]）とちょうど揃うかで見る（増えても・減っても・
表に無いファイルが出ても赤。減る向きにだけ動かす。考えの柵と同じ型）。表そのものも main の表より増えない: 既知の行の数の和が
増えず、main の既知に無いパスは、寄せ元（既知の値の 3 つ目の欄 from）がどれも main の既知に在り、その減りで埋まる時だけ通る。
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


def cf():
    import conceptfence   # 表の読み・追跡・グロブ当て・既知とのずれ・main の表の口（写しの柵も直に使う）
    return conceptfence


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

    def test_peers_name_the_other_spots(self):
        """同じ並びを 2 つのファイルに置くと、各ファイルの相手はもう片方。同じファイルの中の繰り返しは印で示し、写しの無いファイルは載せない"""
        a, b = self.put("a.py", BLOCK), self.put("b.py", BLOCK)
        c = self.put("c.py", "".join(f"other_{i} = 1\n" for i in range(10)))
        d = self.put("d.yaml", BLOCK + "middle: 1\n" + BLOCK)
        got = cpf().peers(self.root, [a, b, c], 10, {})
        self.assertEqual(got, {a: [b], b: [a]})
        self.assertEqual(cpf().peers(self.root, [d], 10, {}), {d: [cpf().SAME_FILE]})
        self.assertEqual(set(cpf().peers(self.root, [a, b, c, d], 10, {})), set(self.scan(a, b, c, d)))

    def test_new_copy_not_on_known_list_is_red(self):
        a, b = self.put("a.py", BLOCK), self.put("b.py", BLOCK)
        found = self.scan(a, b)
        self.assertEqual(cf().verdict(found, {a: [10, "理由"], b: [10, "理由"]}), [])
        self.assertTrue(cf().verdict(found, {a: [10, "理由"]}))       # b は表に無い
        self.assertTrue(cf().verdict({}, {a: [10, "理由"]}))          # 直ったのに表が残る

    def test_growth_is_the_known_total(self):
        m = cpf()
        main = {"known": {"a.py": [10, "x"]}}
        self.assertEqual(m.growth(main, {"known": {"a.py": [10, "x"]}}), [])
        self.assertTrue(m.growth(main, {"known": {"b.py": [8, "y"]}}))      # main に無いパスは、和が減っても寄せ元が無ければ赤
        self.assertTrue(m.growth(main, {"known": {"a.py": [10, "x"], "b.py": [1, "y"]}}))

    def test_growth_lets_a_new_path_take_over_named_sources(self):
        """main に無いパスは、寄せ元 from がどれも main の既知に在り、その減りの和が行の数以上の時だけ通る"""
        m = cpf()
        main = {"known": {"a.py": [10, "x"], "c.py": [6, "z"]}}
        self.assertEqual(m.growth(main, {"known": {"b.py": [8, "y", ["a.py"]], "c.py": [6, "z"]}}), [])
        self.assertEqual(m.growth(main, {"known": {"a.py": [2, "x"], "b.py": [8, "y", ["a.py", "a.py"]], "c.py": [6, "z"]}}), [])
        # 和は 16 から 13 に減るが、寄せ元 a.py の減り 7 が b.py の 8 行に足りない（c.py の減りは寄せ元に名指していない）
        self.assertTrue(m.growth(main, {"known": {"a.py": [3, "x"], "b.py": [8, "y", ["a.py"]], "c.py": [2, "z"]}}))
        self.assertTrue(m.growth(main, {"known": {"a.py": [10, "x"], "b.py": [4, "y", ["d.py"]]}}))   # 寄せ元が main に無い
        self.assertTrue(m.growth(main, {"known": {"a.py": [10, "x"], "b.py": [4, "y", []]}}))         # 寄せ元が空

    def test_growth_hands_out_each_source_once(self):
        """同じ寄せ元の減りは 1 度だけ配る: 寄せ元を分け合う新しいパスの組では、行の和がその組の寄せ元の減りの和を超えたら赤
        （名指していない別の写しの減りで和の検査だけが通る抜け道を塞ぐ）"""
        m = cpf()
        main = {"known": {"a.py": [10, "x"], "c.py": [10, "z"]}}
        self.assertTrue(m.growth(main, {"known": {"X.py": [10, "y", ["a.py"]], "Y.py": [10, "y", ["a.py"]]}}))
        self.assertEqual(m.growth(main, {"known": {"X.py": [5, "y", ["a.py"]], "Y.py": [5, "y", ["a.py"]], "c.py": [10, "z"]}}), [])
        # 組は寄せ元でつながる: X は a と c、Y は c を名指す。組の減りは 20 で、行の和 20 まで通る
        self.assertEqual(m.growth(main, {"known": {"X.py": [12, "y", ["a.py", "c.py"]], "Y.py": [8, "y", ["c.py"]]}}), [])
        self.assertTrue(m.growth(main, {"known": {"X.py": [12, "y", ["a.py", "c.py"]], "Y.py": [9, "y", ["c.py"]]}}))
        self.assertEqual(m.growth(None, {"known": {"a.py": [99, "x"]}}), [])   # main に表が無い（初めて掛ける柵）


class TableHolds(unittest.TestCase):
    """本物の works の木: 写しは表の既知とちょうど揃う"""

    def setUp(self):
        self.m, self.cf = cpf(), cf()
        self.table = self.cf.read_table(ROOT / TABLE)

    def test_table_shape(self):
        self.assertIsInstance(self.table["window"], int)
        self.assertGreaterEqual(self.table["window"], 6)
        for glob, why in self.table["exclude"].items():
            with self.subTest(exclude=glob):
                self.assertTrue(why.strip(), "見ない所に理由が無い")
        for path, (n, why, *rest) in self.table["known"].items():
            with self.subTest(known=path):
                self.assertGreater(n, 0)
                self.assertTrue(why.strip(), "既知の写しに理由が無い")
                self.assertLessEqual(len(rest), 1, "既知の値は [行の数, 理由] か [行の数, 理由, 寄せ元]")
                for sources in rest:
                    self.assertTrue(sources and all(isinstance(x, str) and x for x in sources), "寄せ元はパスの字の列")

    def test_reasons_carry_no_peer_list(self):
        """既知の理由は写しの相手を手で持たない（相手は走査が出す。持つと写しが動いた時に黙って古くなる）"""
        for path, (_, why, *_rest) in self.table["known"].items():
            with self.subTest(known=path):
                self.assertNotIn("相手:", why)

    def test_excludes_are_live(self):
        """見ない所のグロブは、どれも追跡されたファイルに当たる（当たらない行は消す）"""
        paths = self.cf.tracked(ROOT)
        for glob in self.table["exclude"]:
            with self.subTest(glob):
                self.assertTrue(any(self.cf.hit(p, [glob]) for p in paths), "どのファイルにも当たらない")

    def test_copies_match_known(self):
        paths, window, exclude = self.cf.tracked(ROOT), self.table["window"], self.table["exclude"]
        found = self.m.scan(ROOT, paths, window, exclude)
        problems = self.cf.verdict(found, self.table["known"])
        if problems:
            near = self.m.peers(ROOT, paths, window, exclude)
            problems = problems + [f"  写しの相手 {p}: {'・'.join(near[p])}" for p in sorted(near)
                                   if found.get(p) != self.table["known"].get(p, [None])[0]]
        self.assertEqual(problems, [],
                         "写しが表の既知と揃わない。新しい写しは 1 か所へ寄せる（寄せられない訳があれば理由つきで表に置く）。"
                         "減った所は表を減らす")


class NotAboveMain(unittest.TestCase):
    """表の既知の行の数の和が、main から分かれた所の表（HEAD と origin/main の分かれ目の docs/copies.json）より増えない。
    run の途中で main が数を下げても run の直しの赤にしない（main へ入れる時は分かれ目が main の頭）。main に表が無ければ
    初めて掛ける柵なので比べない"""

    def test_known_not_above_main(self):
        m = cpf()
        if subprocess.run(["git", "-C", str(ROOT), "rev-parse", "--verify", f"{m.MAIN_REF}^{{commit}}"],
                          capture_output=True).returncode != 0:
            self.skipTest(f"SKIP git-history: {m.MAIN_REF} を引けない（浅い clone か ref が無い）")
        main, _why = cf().main_table(ROOT, cf().fork_ref(ROOT), TABLE)
        self.assertEqual(m.growth(main, cf().read_table(ROOT / TABLE)), [])


if __name__ == "__main__":
    unittest.main()
