"""考えの住処の柵（地図 docs/concepts.md と表 docs/concepts.json）。

考えごとに（住処ありも散らばりも）、その考えの語の形（正規表現）が「知ってよい所」と除く所の外の
追跡されたファイルに何行あるかを数え、表の既知の漏れ（ファイル → 件数と理由）とちょうど揃うことを見る。件数が
表より増えても・減っても・表に無いファイルが出ても赤（減る向きにだけ動かす。tests/blockblind.py の許可表と同じ型）。
散らばりの柵は知ってよい所が空の数の歯止め。表そのものも main の表（origin/main）より件数の和が増えない（NotAboveMain）。
あわせて地図と表の id と状態が揃うこと・住処ありの考えが柵を持つこと・地図に書いたパスが在ることを見る（地図が
古くなるのを防ぐ一番安い同期）。
中身は core の .shared/core/conceptfence.py（ここは試験だけ。run の中の構造のブロックも同じ道具を対象の表に当てる）。計画は docs/plans/2026-10-09-structure-viewpoint.md の 3 節と Task 1。
"""
import glob
import pathlib
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.dont_write_bytecode = True
if str(ROOT / ".shared" / "core") not in sys.path:
    sys.path.insert(0, str(ROOT / ".shared" / "core"))
MD = (ROOT / "docs" / "concepts.md").read_text(encoding="utf-8")
PATH_HEADS = (".shared/", "blk-", "darkfactory/", "dev/", "tests/", "skills/")   # works の地図の行のパスの頭（works の並べ方）


def cf():
    import conceptfence   # 柵の中身（遅らせて読む。無ければその試験だけが落ちる）
    return conceptfence


class MapAndTable(unittest.TestCase):
    """地図と表が揃う"""

    def setUp(self):
        self.table = cf().load(ROOT)

    def test_ids_and_status_agree(self):
        self.assertEqual(cf().map_ids(MD), {k: v["status"] for k, v in self.table["concepts"].items()})

    def test_every_concept_has_fence(self):
        """どの考えも柵を持つ。散らばり（住処が無い）の柵は知ってよい所が空で、今の知る場所を全部既知の漏れに置く数の歯止め
        （減る向きにだけ動く。計画 docs/plans/2026-10-09-clean-whole.md の Task 3.1）"""
        for k, v in self.table["concepts"].items():
            with self.subTest(concept=k):
                self.assertTrue(v["fences"], k)
                if v["status"] == "散らばり":
                    self.assertEqual([f["allowed"] for f in v["fences"]], [[]] * len(v["fences"]), k)
                    self.assertTrue(all(f["known"] for f in v["fences"]), f"{k}: 散らばりの柵が何も数えていない（語の形が今の知る場所に当たらない）")

    def test_allowed_named_in_map(self):
        """表の allowed（柵が照らす知ってよい所）は、地図のその考えの「住処」「約束」「知ってよい所」の行に字で在る（2 か所が食い違わない）"""
        rows = {lab: cf().map_rows(MD, lab) for lab in ("住処", "約束", "知ってよい所")}
        for k, v in self.table["concepts"].items():
            words = {w.rstrip("/") for lab in rows for w in cf().CODE.findall(rows[lab].get(k, ""))}
            for f in v["fences"]:
                for a in f["allowed"]:
                    with self.subTest(concept=k, allowed=a):
                        self.assertIn(a.removesuffix("/**"), words)

    def test_map_paths_exist(self):
        paths = cf().map_paths(MD, PATH_HEADS)
        self.assertTrue(paths)
        missing = [p for p in paths if not (glob.glob(str(ROOT / p)) if "*" in p else (ROOT / p).exists())]
        self.assertEqual(missing, [])

    def test_known_rows_have_reason(self):
        for k, v in self.table["concepts"].items():
            for f in v["fences"]:
                for path, (n, why) in f["known"].items():
                    self.assertGreater(n, 0, (k, path))
                    self.assertTrue(why.strip(), (k, path))


class FencesHold(unittest.TestCase):
    """本物の works の木: 住処の外の漏れは表の既知とちょうど揃う"""

    def test_every_fence(self):
        m = cf()
        table = m.load(ROOT)
        paths = m.tracked(ROOT)
        for k, v in table["concepts"].items():
            for f in v["fences"]:
                with self.subTest(concept=k, what=f["what"]):
                    found = m.scan(ROOT, paths, f, table["exclude"])
                    self.assertEqual(m.verdict(found, f["known"]), [], f"{k}: {f['what']}")


class NotAboveMain(unittest.TestCase):
    """表そのものが増えない: 考えごとの既知の漏れは、main の表（origin/main の docs/concepts.json）より件数の和が増えず、
    main に無いパスも出ない（計画 docs/plans/2026-10-09-clean-whole.md の Task 3.2）。main で柵を持たない考え（柵を
    初めて掛ける差分）は比べない。main の表が読めない（浅い clone・ref が無い）時は名前つきで見送る（CI の works の job は
    全履歴で取るので見送らない。見送りは FAIL_ON_SKIP=1 で赤）"""

    def test_known_not_above_main(self):
        m = cf()
        main, why = m.main_table(ROOT)
        if main is None:
            self.skipTest(f"SKIP git-history: main の柵の表を引けない（{m.MAIN_REF}。浅い clone か ref が無い）: {why}")
        self.assertEqual(m.growth(main, m.load(ROOT)), [])

    def test_missing_ref_is_reported_not_raised(self):
        got, why = cf().main_table(ROOT, "refs/heads/no-such-ref-for-concept-fences")
        self.assertIsNone(got)
        self.assertTrue(why)


class Synthetic(unittest.TestCase):
    """仮の置き場で柵そのものを見る（git を使わず、scan にパスの一覧を渡す）"""

    FENCE = {"what": "語", "pattern": r"\bWORD\b", "allowed": ["home.py"], "known": {}}

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self.tmp.name)
        self.put("a.py", "x = 'WORD'\ny = 1\nz = WORD\nWORDS = 2\n")
        self.put("home.py", "WORD = 1\n")
        self.put("tests/t.py", "WORD\n")

    def tearDown(self):
        self.tmp.cleanup()

    def put(self, rel, text):
        p = self.root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")

    def test_counts_only_outside_allowed_and_exclude(self):
        self.assertEqual(cf().scan(self.root, ["a.py", "home.py", "tests/t.py"], self.FENCE, ["tests/**"]), {"a.py": 2})

    def test_star_crosses_slash(self):
        self.put("blk-x/deep/b.py", "WORD\n")
        fence = dict(self.FENCE, allowed=["blk-*/b.py"])
        self.assertEqual(cf().scan(self.root, ["blk-x/deep/b.py"], fence, []), {})

    def test_skips_binary_and_missing(self):
        (self.root / "bin.dat").write_bytes(b"\xff\xfeWORD\x00")
        self.assertEqual(cf().scan(self.root, ["bin.dat", "gone.py"], self.FENCE, []), {})

    def test_ratchet(self):
        m = cf()
        self.assertEqual(m.verdict({"a.py": 2}, {"a.py": [2, "理由"]}), [])
        self.assertTrue(m.verdict({"a.py": 1}, {"a.py": [2, "理由"]}))              # 減ったのに表が残る
        self.assertTrue(m.verdict({"a.py": 3}, {"a.py": [2, "理由"]}))              # 増えた
        self.assertTrue(m.verdict({"a.py": 2, "b.py": 1}, {"a.py": [2, "理由"]}))   # 表に無い漏れ

    @staticmethod
    def table(**concepts):
        return {"concepts": {k: {"status": "散らばり", "fences": [{"what": "語", "pattern": "x", "allowed": [], "known": kn}]}
                             for k, kn in concepts.items()}}

    def test_growth_same_or_less_is_quiet(self):
        main = self.table(a={"x.py": [2, "理由"], "y.py": [1, "理由"]})
        self.assertEqual(cf().growth(main, main), [])
        self.assertEqual(cf().growth(main, self.table(a={"x.py": [2, "理由"]})), [])          # 減った
        self.assertEqual(cf().growth(main, self.table(a={"x.py": [1, "理由"], "y.py": [2, "理由"]})), [])  # 和が同じ

    def test_growth_more_lines_or_new_path_is_red(self):
        main = self.table(a={"x.py": [2, "理由"]})
        self.assertTrue(cf().growth(main, self.table(a={"x.py": [3, "理由"]})))               # 和が増えた
        self.assertTrue(cf().growth(main, self.table(a={"x.py": [1, "理由"], "z.py": [1, "理由"]})))  # main に無いパス

    def test_growth_skips_concepts_without_main_fence(self):
        main = {"concepts": {"a": {"status": "散らばり", "fences": []}}}
        now = self.table(a={"x.py": [5, "理由"]}, b={"y.py": [1, "理由"]})
        self.assertEqual(cf().growth(main, now), [])   # 初めて柵を掛ける差分（main は柵が空・考えが無い）は比べない

    def test_map_ids_take_first_status_word(self):
        md = ("### `a` 一つ\n\n- 状態: 住処あり（写し）\n- 住処: x\n\n"
              "### `b` 二つ\n- 住処: y\n- 状態: 散らばり（部分の住処あり）\n- 状態: 住処あり\n")
        self.assertEqual(cf().map_ids(md), {"a": "住処あり", "b": "散らばり"})

    def test_map_rows_take_first_labeled_line(self):
        md = "### `a` 一つ\n- 住処: `x.py`\n- 住処: `y.py`\n### `b` 二つ\n- 状態: 散らばり\n"
        self.assertEqual(cf().map_rows(md, "住処"), {"a": "`x.py`"})

    def test_map_paths_skip_planned_and_branch_lines(self):
        md = ("- 住処: `.shared/core/x.py` と `blk-a/` と `dev/*.sh`、`OUTCOMES`、`docs/y.md`\n"
              "- 予定の住処: `blk-entry`（予定）\n"
              "- 計画: `docs/p.md`（枝 `wip/x`）と `darkfactory/schemas/in.json`\n"
              "- 繰り返し: `.shared/core/x.py`\n")
        self.assertEqual(cf().map_paths(md, PATH_HEADS), [".shared/core/x.py", "blk-a", "dev/*.sh"])


if __name__ == "__main__":
    unittest.main()
