"""筋書き（fixtures/*.stubs.yaml）の共通の stub の置き場（dev/stubfold.py）の検査。YAML とテキストを読み、git show で前の版を読むだけ。

- 合わせ方: 筋書きの置き場に共通の基（base.yaml）が在れば、筋書き 1 本の stub ＝ 基の stub に筋書きの stub を鍵ごと丸ごと
  上書きした物（筋書きの値が空（null）の鍵は落とす。基に在っても、その筋書きでは stub しない節）。基が無ければ筋書きのまま
- ラインの筋書きは筋書きごとの違いだけを持つ（基と同じ値の鍵を持たない。基は fixture を持たない）
- 畳んだ版で、合わせた stub が畳む前の筋書きと解析の後で同じ（基を足した commit とその親を git show で読んで比べる）
- 模擬実行に渡す前の写し（stubfold.py materialize）は、写しの筋書きを合わせた物に書き替え、基を消す
"""
import pathlib
import shutil
import subprocess
import sys
import tempfile
import unittest

import yaml

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.dont_write_bytecode = True
sys.path.append(str(ROOT / "dev"))   # 筋書きの合わせ方（dev/stubfold.py）
import stubfold  # noqa: E402

LINE_FIXTURES = ROOT / "darkfactory" / "fixtures"
BASE_REL = f"darkfactory/fixtures/{stubfold.BASE}"


def _git(*args):
    return subprocess.run(["git", "-C", str(ROOT), *args], capture_output=True, text=True, encoding="utf-8", check=False)


class MergeRuleCase(unittest.TestCase):
    def test_scenario_replaces_whole_key_and_null_drops(self):
        base = "# 基の頭\na:\n  x: 1\n  y: 2\n# b の注記\nb: 1\nc: keep\n"
        scen = "# 筋書きの頭\nfixture:\n  expect: completed\na:\n  x: 9\nb:\nd: new\n"
        got = yaml.safe_load(stubfold.merge_text(base, scen))
        self.assertEqual(got, {"fixture": {"expect": "completed"}, "a": {"x": 9}, "c": "keep", "d": "new"})

    def test_null_spellings_drop(self):
        for spelled in ("b:", "b: null", "b: ~", "b:   # この筋書きでは本物で回す"):
            with self.subTest(spelled):
                self.assertEqual(yaml.safe_load(stubfold.merge_text("b: 1\nc: 2\n", spelled + "\n")), {"c": 2})

    def test_no_base_is_the_file_itself(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = pathlib.Path(tmp) / "fixtures" / "x.stubs.yaml"
            p.parent.mkdir()
            p.write_text("a: 1\n", encoding="utf-8")
            self.assertEqual(stubfold.load(p), {"a": 1})

    def test_repeated_top_key_refused(self):
        with self.assertRaises(ValueError):
            stubfold.merge_text("a: 1\na: 2\n", "")


class LineFoldCase(unittest.TestCase):
    def scenarios(self):
        return sorted(LINE_FIXTURES.glob("*.stubs.yaml"))

    def test_line_scenarios_hold_only_differences(self):
        """ラインの筋書きは基と同じ値の鍵を持たない（共通の stub は基に 1 度だけ。新しい段の stub は基に足す）"""
        base_path = LINE_FIXTURES / stubfold.BASE
        self.assertTrue(base_path.is_file(), f"ラインの筋書きの共通の基 {BASE_REL} が無い")
        base = yaml.safe_load(base_path.read_text(encoding="utf-8"))
        self.assertNotIn("fixture", base, "筋書きの宣言（fixture）は筋書きごとに持つ")
        for p in self.scenarios():
            own = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
            with self.subTest(p.name):
                same = sorted(k for k, v in own.items() if k in base and base[k] == v)
                self.assertEqual(same, [], "基と同じ値の stub を筋書きが持つ（筋書きから消す）")
                self.assertIn("fixture", own)

    def test_fold_kept_every_scenario(self):
        """基を足した commit で合わせた stub は、その親の筋書きと解析の後で同じ（畳んで振る舞いを変えていない）。
        基がまだ commit されていなければ、作業ツリーの合わせた stub を HEAD の筋書きと比べる"""
        if _git("rev-parse", "--verify", "HEAD").returncode != 0:
            self.skipTest("SKIP git-history: HEAD を引けない")
        added = _git("log", "--diff-filter=A", "--format=%H", "--", BASE_REL).stdout.split()
        if added:
            rev, before = added[-1], f"{added[-1]}^"
            names = _git("ls-tree", "--name-only", rev, "darkfactory/fixtures/").stdout.split()
            read_now = lambda rel: _git("show", f"{rev}:./{rel}").stdout  # noqa: E731
        else:
            self.assertTrue((LINE_FIXTURES / stubfold.BASE).is_file(), f"{BASE_REL} がどの版にも作業ツリーにも無い")
            before = "HEAD"
            names = [str(p.relative_to(ROOT)) for p in sorted(LINE_FIXTURES.iterdir())]
            read_now = lambda rel: (ROOT / rel).read_text(encoding="utf-8")  # noqa: E731
        scen = [n for n in names if n.endswith(".stubs.yaml")]
        self.assertGreaterEqual(len(scen), 10)
        base_text = read_now(BASE_REL)
        for rel in scen:
            with self.subTest(rel):
                old = _git("show", f"{before}:./{rel}")
                self.assertEqual(old.returncode, 0, old.stderr)
                self.assertEqual(yaml.safe_load(stubfold.merge_text(base_text, read_now(rel))), yaml.safe_load(old.stdout))


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
