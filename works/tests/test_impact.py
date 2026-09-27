"""変更の周りの地図（.shared/core/impact.py）と、その土台の写し（.shared/core/changemap.py）の検査。

- 写し: changemap.py は attention の変更の地図の部品（attention/scripts/lib/changemap.py）のバイト単位の写しで、
  COPIED_FROM.changemap の 1 行目の commit と同じ（手直しは DEVIATIONS だけ）
- 地図: 使い捨ての小さなリポジトリ（gitkit の型の写し）で、逆向きの import・テストの見分け・名前の言及・YAML の参照・
  読めない物 → all_tests_required・盤面の置き場の使い回し（当たり・変わった file だけ読み直す）・予算つきの描画が決まって同じ
- 選ぶ: select_tests が速い段と選んだテストの和を返し、分からない時は全部。miss が JUnit と地図から取りこぼしを出す
"""
import json
import pathlib
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
CORE = ROOT / ".shared" / "core"
sys.path.insert(0, str(CORE))

import changemap  # noqa: E402
import impact  # noqa: E402
from gitkit import committed_copy, git  # noqa: E402

# 写しの works の手直し。{写しのパス（core から）: [(元のバイト, 写しのバイト)]}。COPIED_FROM.changemap の行の注記にも書く
DEVIATIONS = {
    # git の呼び出しの上限 15 秒 → 20 日（works の期限は 20 日だけ。裁定 R4）
    "changemap.py": [(b"timeout=15, env=None", b"timeout=1728000, env=None")],
}

# 使い捨てのリポジトリの中身（path → 中身）
PROJ = {
    "pkg/__init__.py": "",
    "pkg/core.py": "def compute_total(x):\n    return x + 1\n\n\ndef helper():\n    return 2\n",
    "pkg/mid.py": "from pkg.core import compute_total\n\n\ndef use():\n    return compute_total(1)\n",
    "pkg/rel.py": "from . import core\n",
    "app/main.py": "import sys\nfrom pkg import mid\n\nprint(mid.use(), sys.argv)\n",
    "tests/test_core.py": "import unittest\n\nfrom pkg import core\n\n\nclass T(unittest.TestCase):\n    def test_a(self):\n"
                          "        self.assertEqual(core.helper(), 2)\n",
    "tests/test_mid.py": "from pkg.mid import use\n\nassert use() == 2\n",
    "tests/test_other.py": "import json\n\nassert json.loads('1') == 1\n",
    "tests/test_cli.py": "import subprocess\n\nsubprocess.run(['sh', 'scripts/run-job.sh'], check=False)\n",
    "tests/helper.py": "import os\n",
    "scripts/run-job.sh": "#!/bin/sh\npython3 app/main.py\n",
    ".github/workflows/ci.yml": "jobs:\n  t:\n    steps:\n      - run: sh scripts/run-job.sh\n",
    "docs/guide.md": "# guide\n\nSee `pkg/core.py` and compute_total.\n",
    "docs/設計.md": "core.py の中身は pkg/core.py にある\n",
    "conf/settings.json": '{"entry": "app/main.py"}\n',
    "lonely/solo.py": "def lonely_function():\n    pass\n",
    "web/widget.js": "export function widget() { return 1 }\n",
}

_SRC = None


def setUpModule():
    global _SRC
    _SRC = pathlib.Path(tempfile.mkdtemp(prefix="works-impact-src-"))
    for rel, text in PROJ.items():
        p = _SRC / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")


def tearDownModule():
    shutil.rmtree(_SRC, ignore_errors=True)


class RepoCase(unittest.TestCase):
    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp(prefix="works-impact-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.repo = self.tmp / "repo"
        self.head = committed_copy(self.repo, _SRC)
        self.cache = self.tmp / "cache"

    def write(self, rel, text):
        p = self.repo / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")

    def map(self, seeds=(), **kw):
        return impact.map(self.repo, seeds=seeds, **kw)


class CopyCase(unittest.TestCase):
    def test_copied_from_names_source_and_commit(self):
        lines = (CORE / "COPIED_FROM.changemap").read_text(encoding="utf-8").splitlines()
        commit = lines[0].split()[0]
        self.assertEqual(commit, "742a61d")
        rows = [ln.split() for ln in lines[1:] if ln.strip() and not ln.startswith("#")]
        self.assertEqual([(r[0], r[1]) for r in rows], [("changemap.py", "attention/scripts/lib/changemap.py")])
        self.assertIn("works の手直し", lines[1])

    def test_copy_is_byte_identical_except_deviations(self):
        lines = (CORE / "COPIED_FROM.changemap").read_text(encoding="utf-8").splitlines()
        commit = lines[0].split()[0]
        r = subprocess.run(["git", "-C", str(ROOT), "cat-file", "-e", f"{commit}^{{commit}}"], capture_output=True)
        if r.returncode != 0:
            self.skipTest(f"このリポジトリから {commit} を引けない（浅い clone）")
        for row in (ln.split() for ln in lines[1:] if ln.strip() and not ln.startswith("#")):
            rel, src_rel = row[0], row[1]
            src = subprocess.run(["git", "-C", str(ROOT), "show", f"{commit}:{src_rel}"],
                                 capture_output=True, check=True).stdout
            for old, new in DEVIATIONS.get(rel, ()):
                self.assertEqual(src.count(old), 1, f"{rel}: 手直しの元 {old!r} が 1 度だけでない")
                src = src.replace(old, new)
            self.assertEqual((CORE / rel).read_bytes(), src, rel)

    def test_copy_has_no_short_deadline(self):
        self.assertNotIn("timeout=15", (CORE / "changemap.py").read_text(encoding="utf-8"))


class ReverseImportCase(RepoCase):
    def test_reverse_imports_are_transitive_and_relative(self):
        m = self.map(["pkg/core.py"])
        self.assertEqual(m["seeds"]["files"], ["pkg/core.py"])
        rev = set(m["reverse_imports"])
        self.assertTrue({"pkg/mid.py", "pkg/rel.py", "app/main.py", "tests/test_core.py", "tests/test_mid.py"} <= rev, rev)
        self.assertNotIn("tests/test_other.py", rev)
        self.assertNotIn("lonely/solo.py", rev)
        self.assertEqual(m["reach"]["pkg/mid.py"]["depth"], 1)
        self.assertEqual(m["reach"]["app/main.py"]["depth"], 2)
        self.assertEqual(m["reach"]["app/main.py"]["parent"]["from"], "pkg/mid.py")
        # 当たりの行は 1 文字も変えずに持つ
        edge = next(e for e in m["edges"] if e["path"] == "pkg/mid.py" and e["dep"] == "pkg/core.py")
        self.assertEqual(edge["kind"], "import")
        self.assertEqual(edge["hits"], [[1, "from pkg.core import compute_total"]])

    def test_tests_are_detected_and_selected(self):
        m = self.map(["pkg/core.py"])
        # test_cli は sh を起こし、sh が app/main.py を起こし、main が mid を、mid が core を読む（言及を挟むので候補）
        self.assertEqual(m["tests"], ["tests/test_cli.py", "tests/test_core.py", "tests/test_mid.py"])
        self.assertFalse(m["reach"]["tests/test_core.py"]["candidate"])
        self.assertTrue(m["reach"]["tests/test_cli.py"]["candidate"])
        self.assertEqual(m["reach"]["tests/test_cli.py"]["parent"]["from"], "scripts/run-job.sh")
        self.assertNotIn("tests/helper.py", m["tests"])
        self.assertFalse(m["all_tests_required"], m["all_tests_reasons"])
        sel = impact.select_tests(m, fast=["test_other"])
        self.assertFalse(sel["run_all"])
        self.assertEqual(sel["selected"], ["tests/test_cli.py", "tests/test_core.py", "tests/test_mid.py"])
        self.assertEqual(sel["modules"], ["test_cli", "test_core", "test_mid", "test_other"])
        self.assertEqual(impact.select_tests(m, scope="tests/test_c")["modules"], ["test_cli", "test_core"])


class MentionCase(RepoCase):
    def test_mentions_and_symbol_hits_are_candidates(self):
        m = self.map(["pkg/core.py"])
        self.assertIn("docs/guide.md", m["refs"])
        hits = [e for e in m["edges"] if e["path"] == "docs/guide.md"]
        self.assertEqual({e["kind"] for e in hits}, {"path", "symbol"})
        self.assertTrue(all(e["candidate"] for e in hits))
        self.assertIn([3, "See `pkg/core.py` and compute_total."], hits[0]["hits"])
        # 日本語の名前は引用形にならない（core.quotePath=false と同じ）
        self.assertIn("docs/設計.md", m["refs"])

    def test_yaml_refs_and_shell_mentions_reach_tests(self):
        m = self.map(["scripts/run-job.sh"])
        self.assertIn(".github/workflows/ci.yml", m["refs"])
        e = next(e for e in m["edges"] if e["path"] == ".github/workflows/ci.yml")
        self.assertEqual(e["hits"], [[4, "      - run: sh scripts/run-job.sh"]])
        self.assertEqual(m["tests"], ["tests/test_cli.py"])
        self.assertTrue(m["reach"]["tests/test_cli.py"]["candidate"])
        m2 = self.map(["app/main.py"])
        self.assertIn("conf/settings.json", m2["refs"])
        self.assertIn("scripts/run-job.sh", m2["mentions"])
        # sh の言及から先へ伸びる（sh → test_cli）
        self.assertIn("tests/test_cli.py", m2["tests"])

    def test_name_seed_is_searched_as_symbol(self):
        m = self.map(["compute_total"])
        self.assertEqual(m["seeds"]["names"], ["compute_total"])
        self.assertIn("docs/guide.md", m["refs"])
        self.assertIn("pkg/core.py", m["mentions"])
        # mid は名前を書き（symbol）、core も読む（import）。届いた file の分類は import が先
        self.assertIn("pkg/mid.py", m["reverse_imports"])
        self.assertTrue(any(e["path"] == "pkg/mid.py" and e["kind"] == "symbol" and e["dep"] == "compute_total"
                            for e in m["edges"]))


class UnanalysableCase(RepoCase):
    def test_unknown_language_seed_requires_all(self):
        m = self.map(["web/widget.js"])
        self.assertTrue(m["all_tests_required"])
        self.assertTrue(any("unknown-language" in r for r in m["all_tests_reasons"]))
        sel = impact.select_tests(m, fast=["test_other"], all_modules=["test_a", "test_b"])
        self.assertTrue(sel["run_all"])
        self.assertEqual(sel["modules"], ["test_a", "test_b"])

    def test_unanalysable_outside_the_neighbourhood_is_only_counted(self):
        m = self.map(["lonely/solo.py"])
        self.assertFalse(m["all_tests_required"])
        self.assertEqual(m["tests"], [])
        self.assertEqual(m["not_seen"]["unanalysable"].get("unknown-language"), 1)

    def test_dynamic_import_in_the_neighbourhood_requires_all(self):
        self.write("plug/loader.py", "import importlib\nfrom pkg import core\n\n\ndef load(name):\n"
                                     "    return importlib.import_module(name)\n")
        m = self.map(["pkg/core.py"])
        self.assertTrue(m["all_tests_required"])
        u = next(u for u in m["unanalysable"] if u["path"] == "plug/loader.py")
        self.assertEqual((u["reason"], u["line"]), ("dynamic-import", 6))
        self.assertTrue(u["in_neighbourhood"])

    def test_constant_dynamic_import_is_an_import(self):
        self.write("plug/fixed.py", "import importlib\n\nmod = importlib.import_module('pkg.core')\n")
        m = self.map(["pkg/core.py"])
        self.assertFalse(m["all_tests_required"], m["all_tests_reasons"])
        self.assertIn("plug/fixed.py", m["reverse_imports"])

    def test_parse_error_that_may_import_requires_all(self):
        self.write("pkg/broken.py", "from pkg import core\ndef (:\n")
        m = self.map(["pkg/core.py"])
        self.assertTrue(m["all_tests_required"])
        self.assertIn("py-parse-error", {u["reason"] for u in m["unanalysable"] if u["path"] == "pkg/broken.py"})


class PrecisionCase(RepoCase):
    """自分の木（works を含むリポジトリ）で回して見つけた取り違えの留め"""

    def test_sys_path_suffix_picks_the_nearest_copy(self):
        # alpha/tool.py は alpha を sys.path に足す。beta/alpha も同じ字で終わるが、近いのは alpha
        for root in ("alpha", "beta/alpha"):
            self.write(f"{root}/engine/__init__.py", "")
            self.write(f"{root}/engine/advance.py", "X = 1\n")
        self.write("alpha/tool.py", "import pathlib\nimport sys\n\nROOT = pathlib.Path(__file__).parents[1]\n"
                                    "sys.path.insert(0, str(ROOT / 'alpha'))\nimport engine.advance\n")
        near = self.map(["alpha/engine/advance.py"])
        self.assertIn("alpha/tool.py", near["reverse_imports"])
        e = next(e for e in near["edges"] if e["path"] == "alpha/tool.py" and e["kind"] == "import")
        self.assertEqual(e["resolution"], "sys.path")
        far = self.map(["beta/alpha/engine/advance.py"])
        self.assertNotIn("alpha/tool.py", far["reach"])

    def test_names_stay_inside_their_project(self):
        self.write("other/pyproject.toml", "[project]\nname = 'other'\n")
        self.write("other/uses.py", "compute_total = None\n")
        self.write("pyproject.toml", "[project]\nname = 'root'\n")
        m = self.map(["pkg/core.py"])
        self.assertNotIn("other/uses.py", m["reach"])
        self.assertGreaterEqual(m["not_seen"]["ambiguous_mentions"], 1)

    def test_symbol_hits_are_leaves(self):
        # 関数名を書いただけの sh は届くが、その sh を呼ぶテストへは伸ばさない（使う側は import で辿る）
        self.write("scripts/calls-total.sh", "echo compute_total\n")
        self.write("tests/test_calls.py", "import subprocess\n\nsubprocess.run(['sh', 'scripts/calls-total.sh'])\n")
        m = self.map(["pkg/core.py"])
        self.assertIn("scripts/calls-total.sh", m["mentions"])
        self.assertNotIn("tests/test_calls.py", m["tests"])
        # 名前の起点なら伸ばす
        self.assertIn("tests/test_calls.py", self.map(["compute_total"])["tests"])

    def test_fixture_data_is_a_leaf_and_plain_lowercase_names_are_not_keys(self):
        self.write("tests/fixtures/data.json", '{"runs": "scripts/run-job.sh"}\n')
        self.write("tests/test_fix.py", "open('tests/fixtures/data.json').read()\n")
        m = self.map(["scripts/run-job.sh"])
        self.assertIn("tests/fixtures/data.json", m["refs"])
        self.assertNotIn("tests/test_fix.py", m["tests"])
        self.write("pkg/extra.py", "def problems():\n    pass\n\n\nclass DiskThing:\n    pass\n")
        self.write("docs/extra.md", "problems and DiskThing\n")
        m2 = self.map(["pkg/extra.py"])
        self.assertEqual({(e["kind"], e["key"]) for e in m2["edges"] if e["path"] == "docs/extra.md"},
                         {("symbol", "DiskThing")})

    def test_test_names_are_not_dependencies(self):
        # テストの名を書いた文書・設定はテストに依らない（テストから先へ伸ばさない）
        self.write("conf/list.yaml", "suite: tests/test_core.py\n")
        self.write("tests/test_conf.py", "open('conf/list.yaml').read()\n")
        m = self.map(["pkg/core.py"])
        self.assertNotIn("conf/list.yaml", m["reach"])
        self.assertNotIn("tests/test_conf.py", m["tests"])


class CacheCase(RepoCase):
    def test_hit_then_incremental(self):
        m1 = self.map(["pkg/core.py"], cache_dir=self.cache)
        self.assertEqual(m1["stats"]["cache"], "miss")
        self.assertEqual(m1["stats"]["scanned"], m1["counts"]["files"])
        path = pathlib.Path(m1["path"])
        self.assertTrue(path.is_file())
        self.assertEqual(path.parent, self.cache)
        self.assertIn(m1["key"], path.name)
        m2 = self.map(["pkg/core.py"], cache_dir=self.cache)
        self.assertEqual(m2["stats"]["cache"], "hit")
        self.assertEqual(m2["key"], m1["key"])
        self.assertEqual(impact.render(m2), impact.render(m1))
        # 1 本だけ書き換える → 鍵が変わり、読み直すのはその 1 本だけ
        self.write("pkg/mid.py", "def use():\n    return 2\n")
        m3 = self.map(["pkg/core.py"], cache_dir=self.cache)
        self.assertNotEqual(m3["key"], m1["key"])
        self.assertEqual(m3["stats"]["cache"], "miss")
        self.assertEqual(m3["stats"]["scanned"], 1)
        self.assertEqual(m3["stats"]["reused"], m3["counts"]["files"] - 1)
        self.assertNotIn("pkg/mid.py", m3["reverse_imports"])
        self.assertNotIn("tests/test_mid.py", m3["tests"])
        # 新しい file（未追跡）も数に入り、読み直すのはそれだけ
        self.write("tests/test_new.py", "from pkg import core\n")
        m4 = self.map(["pkg/core.py"], cache_dir=self.cache)
        self.assertEqual(m4["stats"]["scanned"], 1)
        self.assertIn("tests/test_new.py", m4["tests"])

    def test_diff_seeds_and_frames(self):
        self.write("pkg/core.py", PROJ["pkg/core.py"].replace("return x + 1", "return x + 2"))
        m = self.map(diff=True)
        self.assertEqual(m["seeds"]["from_diff"], ["pkg/core.py"])
        self.assertEqual(m["seeds"]["files"], ["pkg/core.py"])
        blocks = m["frames"]["pkg/core.py"]["blocks"]
        self.assertTrue(any("    return x + 2" in b for b in blocks), blocks)
        self.assertTrue(any(ln.startswith("def compute_total") for b in blocks for ln in b))   # 関数まるごと

    def test_deleted_and_renamed_seeds_keep_their_importers(self):
        # 消した file も、import する側はまだ名を書いている（その側とテストを選ぶ）
        (self.repo / "pkg/core.py").unlink()
        m = self.map(diff=True)
        self.assertEqual(m["seeds"]["missing"], ["pkg/core.py"])
        self.assertIn("pkg/mid.py", m["reverse_imports"])
        self.assertIn("tests/test_core.py", m["tests"])
        git(self.repo, "checkout", "--", "pkg/core.py")
        git(self.repo, "mv", "pkg/core.py", "pkg/core2.py")
        m2 = self.map(diff=True)
        self.assertEqual(m2["seeds"]["from_diff"], ["pkg/core.py", "pkg/core2.py"])
        self.assertIn("pkg/mid.py", m2["reverse_imports"])

    def test_seeds_from_units(self):
        units = [{"key": "直す", "reason": "pkg/core.py の compute_total が 1 足りない。solo.py は無関係"},
                 {"key": "別", "reason": "無い file nothere.py", "prescriptions": ["pkg/mid.py を直す"]}]
        self.assertEqual(impact.seeds_from_units(self.repo, units), ["lonely/solo.py", "pkg/core.py", "pkg/mid.py"])


class RenderCase(RepoCase):
    def test_render_is_deterministic_and_within_budget(self):
        self.write("pkg/core.py", PROJ["pkg/core.py"].replace("return x + 1", "return x + 2"))
        m = self.map(["pkg/core.py"], diff=True)
        a = impact.render(m, budget=4000)
        self.assertEqual(a, impact.render(json.loads(json.dumps(m)), budget=4000))
        self.assertLessEqual(len(a), 4000)
        self.assertIn("tests/test_core.py", a)
        self.assertIn("from pkg.core import compute_total", a)   # 当たりの行はそのまま
        self.assertIn("┏", a)                                     # 変更の枠（関数まるごと）
        self.assertIn("all_tests_required: false", a)
        small = impact.render(m, budget=600)
        self.assertLessEqual(len(small), 600)
        self.assertIn("この描画で出していない", small)
        self.assertNotIn("┏", small)   # 枠は丸ごと入らないなら出さない（途中で切らない）

    def test_render_budget_too_small_for_header_still_says_so(self):
        m = self.map(["pkg/core.py"])
        out = impact.render(m, budget=50)
        self.assertLessEqual(len(out), 50)


class MissCase(RepoCase):
    JUNIT = """<?xml version="1.0" encoding="utf-8"?>
<testsuites><testsuite name="s">
<testcase classname="tests.test_core.T" name="test_a"><failure message="x"/></testcase>
<testcase classname="tests.test_other.T" name="test_b"><error message="y"/></testcase>
<testcase classname="tests.test_mid.T" name="test_c"/>
<testcase classname="" name="odd"><failure/></testcase>
</testsuite></testsuites>
"""

    def test_miss_is_failed_but_not_selected(self):
        m = self.map(["pkg/core.py"])
        out = impact.miss(m, self.JUNIT)
        self.assertEqual(out["schema"], "works-impact-miss/1")
        self.assertEqual(out["key"], m["key"])
        self.assertEqual(out["failed"], 3)
        self.assertEqual([x["module"] for x in out["misses"]], ["test_other"])
        self.assertEqual(out["caught"], ["tests.test_core.T::test_a"])
        self.assertEqual(len(out["unmapped"]), 1)
        # 速い段に入っていれば取りこぼしではない
        self.assertEqual(impact.miss(m, self.JUNIT, fast=["test_other"])["misses"], [])


if __name__ == "__main__":
    unittest.main()
