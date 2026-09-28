"""ブロックは組み替えの部品で、ほかのブロックを知らない（README「層と依存の向き」）。その決まりの散文の側の柵。

test_layers の決まり 3（name）は L1〜L5 のコードの文字列の定数だけを見る。ここはその外——YAML の説明・docstring・
コメント・指示書の md——で、自分以外の blk-<名> を名指しする行を数え、今ある破れを許可表（ファイル:相手の名 → 件数と理由）に
固定する。件数が表より増えても・減っても・表に無い組が出ても赤（減る向きにだけ動かす。KNOWN と同じ ratchet）。
同じ形で、役の指示書（blk-*/commands・rules・写しでない prompts。深さは問わない。lib が組む文・YAML・scripts は見ない）が
ほかの役・段を前提にする語（閉じた一覧 ROLE_TERMS。自分の名乗りの文の語は除く）の行を ROLE_KNOWN（ファイル:語 → 件数と理由）に固定する。
中身は tests/blockblind.py（ここは試験だけ）。
"""
import pathlib
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]


def bb():
    import blockblind   # 柵の中身（遅らせて読む。無ければその試験だけが落ちる）
    return blockblind


class BlockNamesInTree(unittest.TestCase):
    """本物の works の木: 今ある破れは許可表とちょうど揃う"""

    def test_tree_matches_known(self):
        m = bb()
        found = m.block_refs(ROOT, m.tracked(ROOT))
        self.assertEqual(m.verdict(found, m.BLOCK_KNOWN), [], m.report(found, m.BLOCK_KNOWN))

    def test_known_rows_have_reason(self):
        m = bb()
        for key, (n, why) in m.BLOCK_KNOWN.items():
            self.assertGreater(n, 0, key)
            self.assertTrue(why.strip(), key)

    def test_blocks_come_from_folders(self):
        m = bb()
        self.assertEqual(m.blocks(ROOT), sorted(p.name for p in ROOT.glob("blk-*") if p.is_dir()))


class BlockNamesFence(unittest.TestCase):
    """仮の works の木で柵そのものを見る"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self.tmp.name)
        self.put("blk-a/blk-a.yaml", "name: blk-a\ndescription: 自分の名は書いてよい（blk-a）\n")
        self.put("blk-b/blk-b.yaml", "name: blk-b\n")
        self.put("darkfactory/darkfactory.yaml", "nodes:\n  - include: blk-a\n  - include: blk-b\n")

    def tearDown(self):
        self.tmp.cleanup()

    def put(self, rel, text):
        p = self.root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")

    def found(self):
        m = bb()
        files = sorted(str(p.relative_to(self.root)) for p in self.root.rglob("*") if p.is_file())
        return m.block_refs(self.root, files)

    def test_clean_tree_has_nothing(self):
        self.assertEqual(self.found(), {})

    def test_other_block_in_yaml_description_is_counted(self):
        self.put("blk-a/blk-a.yaml", "name: blk-a\ninputs:\n  f:\n    description: 判定のファイル（blk-b の出口）\n")
        self.assertEqual(self.found(), {"blk-a/blk-a.yaml:blk-b": 1})

    def test_docstring_comment_and_md_are_counted_by_line(self):
        self.put("blk-a/lib/m.py", '"""blk-b が書いた盤面を読む"""\n# blk-b と同じ約束\nX = 1  # blk-b blk-b\n')
        self.put("blk-a/commands/role.md", "お前は判定役。blk-b の返答を読む。\n")
        self.assertEqual(self.found(), {"blk-a/lib/m.py:blk-b": 3, "blk-a/commands/role.md:blk-b": 1})

    def test_own_name_and_unknown_names_are_not_counted(self):
        self.put("blk-a/lib/m.py", "# blk-a の節。blk-zz はフォルダが無いので名ではない\n")
        self.assertEqual(self.found(), {})

    def test_copied_folder_is_skipped(self):
        self.put("blk-a/prompts/COPIED_FROM", "abc123  写し\n")
        self.put("blk-a/prompts/x.md", "blk-b の出口を読む\n")
        self.assertEqual(self.found(), {})

    def test_outside_blocks_is_not_counted(self):
        self.put("darkfactory/notes.md", "blk-a の出口を blk-b に渡す\n")
        self.assertEqual(self.found(), {})

    def test_verdict_new_pair_more_and_fewer_are_red(self):
        m = bb()
        known = {"blk-a/blk-a.yaml:blk-b": (2, "理由")}
        self.assertEqual(m.verdict({"blk-a/blk-a.yaml:blk-b": 2}, known), [])
        self.assertTrue(m.verdict({"blk-a/blk-a.yaml:blk-b": 3}, known))       # 増えた
        self.assertTrue(m.verdict({"blk-a/blk-a.yaml:blk-b": 1}, known))       # 減ったのに表が残る
        self.assertTrue(m.verdict({}, known))                                   # 直ったのに行が残る
        self.assertTrue(m.verdict({"blk-a/blk-a.yaml:blk-b": 2, "blk-a/x.md:blk-b": 1}, known))   # 表に無い組

    def test_report_names_the_fix(self):
        m = bb()
        text = m.report({"blk-a/blk-a.yaml:blk-b": 1}, {})
        self.assertIn("blk-a/blk-a.yaml:blk-b", text)
        self.assertIn("形と約束", text)
        self.assertIn("darkfactory", text)


class RoleTermsInTree(unittest.TestCase):
    """本物の works の木: 役の指示書がほかの役・段を前提にする行は許可表とちょうど揃う"""

    def test_tree_matches_known(self):
        m = bb()
        found = m.role_refs(ROOT, m.tracked(ROOT))
        self.assertEqual(m.verdict(found, m.ROLE_KNOWN), [], m.report(found, m.ROLE_KNOWN))

    def test_known_rows_have_reason(self):
        m = bb()
        for key, (n, why) in m.ROLE_KNOWN.items():
            self.assertGreater(n, 0, key)
            self.assertTrue(why.strip(), key)
            self.assertIn(key.rsplit(":", 1)[1], m.ROLE_TERMS, key)


class RoleTermsFence(unittest.TestCase):
    """仮の works の木で、役・段の語の柵そのものを見る（語の一覧は閉じた集合・自分の役は名乗りの文から取る）"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self.tmp.name)
        self.put("blk-a/blk-a.yaml", "name: blk-a\n")

    def tearDown(self):
        self.tmp.cleanup()

    def put(self, rel, text):
        p = self.root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")

    def found(self):
        m = bb()
        files = sorted(str(p.relative_to(self.root)) for p in self.root.rglob("*") if p.is_file())
        return m.role_refs(self.root, files)

    def test_self_roles_come_from_the_name_line(self):
        m = bb()
        self.assertEqual(m.self_roles("お前は実測役。判定役がお前の一覧を読む。\n"), {"実測役"})
        self.assertEqual(m.self_roles("<!-- 節 tdd-head -->\nあなたは修正役。判定役が切った判定を読む。\n"), {"修正役"})
        self.assertEqual(m.self_roles("お前は新しく呼ばれた別の判定役（第三の目）。判定役と修正役の往復\n"), {"判定役"})
        self.assertEqual(m.self_roles("## 直し方\n修正役は直す。\n"), set())

    def test_other_role_is_counted_and_own_role_is_not(self):
        self.put("blk-a/commands/judge.md", "お前は判定役（judge）。修正役が覆せない判定を下す。\n判定役として読む。\n")
        self.assertEqual(self.found(), {"blk-a/commands/judge.md:修正役": 1})

    def test_file_without_name_line_counts_every_term(self):
        self.put("blk-a/rules/common.md", "## 直し方\n最後の人の関所まで。修正役は直す。\n")
        self.assertEqual(self.found(), {"blk-a/rules/common.md:関所": 1, "blk-a/rules/common.md:修正役": 1})

    def test_term_counted_once_per_line(self):
        self.put("blk-a/commands/x.md", "お前は実測役。\n判定役と判定役が読む。次の段の後段へ。\n")
        self.assertEqual(self.found(), {"blk-a/commands/x.md:判定役": 1, "blk-a/commands/x.md:後段": 1})

    def test_words_outside_the_closed_list_are_not_counted(self):
        self.put("blk-a/commands/x.md", "お前は代役の忠実性の役。最終手段は使わない。\n")
        self.assertEqual(self.found(), {})

    def test_uncopied_prompts_are_counted_and_copies_are_skipped(self):
        self.put("blk-a/prompts/p.md", "# CI の役\n判定役にも渡る。\n")
        self.put("blk-a/other/COPIED_FROM", "abc  写し\n")
        self.put("blk-a/other/q.md", "判定役にも渡る。\n")
        self.put("blk-b/prompts/COPIED_FROM", "abc  写し\n")
        self.put("blk-b/prompts/r.md", "判定役にも渡る。\n")
        self.assertEqual(self.found(), {"blk-a/prompts/p.md:判定役": 1})

    def test_nested_folders_under_role_dirs_are_counted(self):
        self.put("blk-a/prompts/loop/p.md", "判定役にも渡る。\n")
        self.put("blk-a/commands/sub/deep/c.md", "お前は実測役。修正役が読む。\n")
        self.assertEqual(self.found(), {"blk-a/prompts/loop/p.md:判定役": 1, "blk-a/commands/sub/deep/c.md:修正役": 1})

    def test_self_role_is_the_sentence_not_the_line(self):
        self.put("blk-a/commands/d.md", "お前は判定役。修正役が読む。\n")
        self.assertEqual(self.found(), {"blk-a/commands/d.md:修正役": 1})

    def test_self_role_sentence_spans_lines(self):
        self.put("blk-a/commands/e.md", "お前は\n判定役。修正役が読む。\n")
        self.assertEqual(self.found(), {"blk-a/commands/e.md:修正役": 1})

    def test_yaml_lib_and_scripts_are_out_of_scope(self):
        self.put("blk-a/blk-a.yaml", "name: blk-a\ndescription: 判定役を起こす\n")
        self.put("blk-a/lib/m.py", '"""判定役を起こさない"""\n')
        self.put("blk-a/scripts/s.py", "# 修正役の後\n")
        self.assertEqual(self.found(), {})


if __name__ == "__main__":
    unittest.main()
