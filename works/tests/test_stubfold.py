"""筋書き（fixtures/*.stubs.yaml）の共通の stub の置き場（dev/stubfold.py）の検査。YAML とテキストを読み、git show で main の版を読むだけ。

- 合わせ方（RFC 7386 の形）: 筋書きの置き場に共通の基（base.yaml）が在れば、筋書き 1 本の stub ＝ 基の stub に筋書きの stub を
  重ねた物。写像どうしは入れ子まで鍵ごとに重ね、写像でない値（列・字・数・流れの形 {…}）は丸ごと置き替え、筋書きの値が空（null）の
  鍵は落とす（最上位でも入れ子でも）。葉の行は元の字のまま。基が無ければ筋書きのまま
- ラインの筋書きは筋書きごとの違いだけを持つ（基と同じ値の欄を、入れ子の中でも持たない。基は fixture を持たない）
- 寄せの差分の間だけ（main に基が無い置き場か、dev/stubfold.py が main と違う時）、合わせた stub が main の版を main の
  stubfold で合わせた物と解析の後で同じ（どちらでもなければ比べない。固めた歴史は確かめ直さない）
- 模擬実行に渡す前の写し（stubfold.py materialize）は、写しの筋書きを合わせた物に書き替え、基を消す
"""
import pathlib
import shutil
import subprocess
import sys
import tempfile
import textwrap
import types
import unittest

import yaml

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.dont_write_bytecode = True
sys.path.append(str(ROOT / "dev"))   # 筋書きの合わせ方（dev/stubfold.py）
import stubfold  # noqa: E402
if str(ROOT / ".shared" / "core") not in sys.path:
    sys.path.insert(0, str(ROOT / ".shared" / "core"))
import conceptfence  # noqa: E402  （main から分かれた所 fork_ref）

LINE_FIXTURES = ROOT / "darkfactory" / "fixtures"


def _git(*args):
    return subprocess.run(["git", "-C", str(ROOT), *args], capture_output=True, text=True, encoding="utf-8", check=False)


def _value(block):
    """stubfold の塊の値（解析した物）"""
    return yaml.safe_load(textwrap.dedent(block["line"] + "".join(block["body"])))[block["key"]]


def _same_as_base(base_text, own_text, depth=0, where=""):
    """筋書きが基と同じ値で持つ欄のパスの一覧（写像どうしの所は中へ下りる。空の鍵は落とす印なので数えない）"""
    _, base, _ = stubfold._blocks(base_text, depth)
    _, own, _ = stubfold._blocks(own_text, depth)
    at = {b["key"]: b for b in base}
    out = []
    for o in own:
        b = at.get(o["key"])
        if b is None or o["kind"] == "null":
            continue
        if o["kind"] == "map" and b["kind"] == "map":
            out += _same_as_base("".join(b["body"]), "".join(o["body"]), o["child"], f"{where}{o['key']}.")
        elif _value(o) == _value(b):
            out.append(where + o["key"])
    return out


class MergeRuleCase(unittest.TestCase):
    def merged(self, base, scen):
        return yaml.safe_load(stubfold.merge_text(base, scen))

    def test_nested_mapping_merges_by_key_and_null_drops(self):
        base = "# 基の頭\na:\n  x: 1\n  y: 2\n  z:\n    p: 1\n    q: 2\n# b の注記\nb: 1\nc: keep\n"
        scen = "# 筋書きの頭\nfixture:\n  expect: completed\na:\n  x: 9\n  y:\n  z:\n    q: 3\nb:\nd: new\n"
        self.assertEqual(self.merged(base, scen), {"fixture": {"expect": "completed"}, "a": {"x": 9, "z": {"p": 1, "q": 3}},
                                                   "c": "keep", "d": "new"})

    def test_non_mappings_replace_whole(self):
        """列・流れの形・字・塊の字は丸ごと置き替え（中を合わせない）。写像と写像でない物の組も筋書きの値で置き替える"""
        base = "a:\n  l:\n  - 1\n  - 2\n  f: {x: 1, y: 2}\n  s: old\n  t: |\n    one\n    two\n  m:\n    k: 1\n  n: 5\n"
        scen = "a:\n  l:\n  - 3\n  f: {x: 9}\n  s: new\n  t: |\n    three\n  m: 7\n  n:\n    k: 2\n"
        self.assertEqual(self.merged(base, scen),
                         {"a": {"l": [3], "f": {"x": 9}, "s": "new", "t": "three\n", "m": 7, "n": {"k": 2}}})

    def test_leaf_lines_kept_verbatim(self):
        """葉の行は元の字のまま並ぶ（こちらの解析で書き直さない）"""
        out = stubfold.merge_text("a:\n  x: '007'\n  y: 2\n", "a:\n  y:   \"two\"  # 注記\n")
        self.assertIn("  x: '007'\n", out)
        self.assertIn('  y:   "two"  # 注記\n', out)

    def test_null_spellings_drop(self):
        for spelled in ("b:", "b: null", "b: ~", "b:   # この筋書きでは本物で回す"):
            with self.subTest(spelled):
                self.assertEqual(self.merged("b: 1\nc: 2\n", spelled + "\n"), {"c": 2})
                self.assertEqual(self.merged("a:\n  b: 1\n  c: 2\n", "a:\n  " + spelled + "\n"), {"a": {"c": 2}})

    def test_no_base_is_the_file_itself(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = pathlib.Path(tmp) / "fixtures" / "x.stubs.yaml"
            p.parent.mkdir()
            p.write_text("a: 1\n", encoding="utf-8")
            self.assertEqual(stubfold.load(p), {"a": 1})

    def test_refused_shapes(self):
        """同じ字下げの鍵の 2 度書き・引用した鍵・合わせる写像どうしの字下げの違いは拒む"""
        for base, scen in (("a: 1\na: 2\n", ""), ("a:\n  x: 1\n", "a:\n  x: 2\n  x: 3\n"),
                           ("a:\n  x: 1\n", "a:\n  'x': 2\n"), ("a:\n  x: 1\n", "a:\n    x: 2\n")):
            with self.subTest(scen=scen), self.assertRaises(ValueError):
                stubfold.merge_text(base, scen)


class LineFoldCase(unittest.TestCase):
    def scenarios(self):
        return sorted(LINE_FIXTURES.glob("*.stubs.yaml"))

    def test_line_scenarios_hold_only_differences(self):
        """ラインの筋書きは基と同じ値の欄を持たない（入れ子の中も。共通の stub は基に 1 度だけ。新しい段の stub は基に足す）"""
        base_path = LINE_FIXTURES / stubfold.BASE
        self.assertTrue(base_path.is_file(), f"ラインの筋書きの共通の基 {base_path.relative_to(ROOT)} が無い")
        base_text = base_path.read_text(encoding="utf-8")
        self.assertNotIn("fixture", yaml.safe_load(base_text), "筋書きの宣言（fixture）は筋書きごとに持つ")
        for p in self.scenarios():
            own_text = p.read_text(encoding="utf-8")
            with self.subTest(p.name):
                self.assertEqual(_same_as_base(base_text, own_text), [], "基と同じ値の stub を筋書きが持つ（筋書きから消す）")
                self.assertIn("fixture", yaml.safe_load(own_text) or {})

    def test_fold_kept_every_scenario(self):
        """寄せの差分の間だけ、合わせた stub が main と同じことを縛る。基の在る置き場（走査で導く）ごとに、main から分かれた所
        （conceptfence.fork_ref）にその置き場の基が無いか dev/stubfold.py がそこと違う時だけ、そこの筋書きをそこの stubfold で
        合わせた物（基が無ければ筋書きのまま）と、今の木の stubfold.load を解析の後で比べる（そこに無い筋書きは新しい物で比べない）"""
        ref = conceptfence.fork_ref(ROOT)
        if _git("rev-parse", "--verify", f"{ref}^{{commit}}").returncode != 0:
            self.skipTest(f"SKIP git-history: {ref} を引けない（浅い clone か ref が無い）")
        src = _git("show", f"{ref}:./dev/stubfold.py")
        then = None
        if src.returncode == 0:
            then = types.ModuleType("stubfold_then")
            exec(compile(src.stdout, f"{ref}:dev/stubfold.py", "exec"), then.__dict__)   # noqa: S102  （main の版の合わせ方）
        moved = src.returncode != 0 or src.stdout != (ROOT / "dev" / "stubfold.py").read_text(encoding="utf-8")
        for base in sorted(ROOT.glob(f"**/fixtures/{stubfold.BASE}")):
            place = base.parent.relative_to(ROOT).as_posix()
            then_base = _git("show", f"{ref}:./{place}/{stubfold.BASE}")
            if then_base.returncode == 0 and not moved:
                continue
            compared = 0
            for p in sorted(base.parent.glob(f"*{stubfold.SUFFIX}")):
                own = _git("show", f"{ref}:./{place}/{p.name}")
                if own.returncode != 0:
                    continue
                text = (then.merge_text(then_base.stdout, own.stdout) if then is not None and then_base.returncode == 0
                        else own.stdout)
                with self.subTest(f"{place}/{p.name}"):
                    self.assertEqual(stubfold.load(p), yaml.safe_load(text) or {})
                compared += 1
            self.assertGreater(compared, 0, f"{place}: 比べる筋書きが 1 本も無い")


class LoadPathCase(unittest.TestCase):
    def test_tests_read_scenarios_through_load(self):
        """試験は筋書きを stubfold.load で読む（素の safe_load だと、基を置いた置き場で合わせていない違いだけを読む）。
        数えるのは、safe_load と筋書きの名の尾（stubfold.SUFFIX）が同じ行に在る行。前の行で名を受けて次の行で解析する形と、
        ほかの解析の口は見ない。この試験自身は、合わせない読みと比べる行を持つので外す"""
        found = []
        for p in sorted((ROOT / "tests").glob("*.py")):
            if p.name == pathlib.Path(__file__).name:
                continue
            for n, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
                if "safe_load" in line and stubfold.SUFFIX in line:
                    found.append(f"{p.name}:{n}")
        self.assertEqual(found, [], "筋書きは stubfold.load で読む（置き場に基が在っても合わせた stub を読むため）")


class MaterializeCase(unittest.TestCase):
    def test_materialize_writes_merged_and_drops_base(self):
        with tempfile.TemporaryDirectory() as tmp:
            pack = pathlib.Path(tmp) / "pack"
            shutil.copytree(LINE_FIXTURES, pack / "darkfactory" / "fixtures")
            done = stubfold.materialize(pack)
            out = pack / "darkfactory" / "fixtures"
            self.assertFalse((out / stubfold.BASE).exists())
            scen = sorted(LINE_FIXTURES.glob("*.stubs.yaml"))
            self.assertEqual(len(done), len(scen))
            for p in scen:
                with self.subTest(p.name):
                    self.assertEqual(yaml.safe_load((out / p.name).read_text(encoding="utf-8")), stubfold.load(p))


if __name__ == "__main__":
    unittest.main()
