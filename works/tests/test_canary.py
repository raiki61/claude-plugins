"""canary（dev/canary.sh・dev/canary-seed/・dev/canary-request.json・dev/canary_check.py）の検査（FAST）。

- 種: 種の写しで、種のテストは緑・依頼の 2 件のバグと CHANGELOG の行の欠けは在る（下の PROBES が赤）・試験の中だけに持つ参照の
  直し（FIXES）を当てると当てた件の PROBES だけが緑になり、全部当てれば全部緑で種のテストも緑のまま。
- (b) の前提: 種のテストのファイルは test_lib.py の 1 本で、README の決まりがテストをモジュールごとのクラスに足させる。2 件の
  受け入れのテストの参照（LANE_TESTS。各クラスの末尾に足す）は、種では自分の件だけ赤（TDD の赤）で、2 つの枝の test_lib.py は
  3 方向で字の食い違いなしに合い、合わせた木は全部の直しの後に緑。2 つの枝が同じ末尾（main の前）に足しても挿しだけの食い違い
  （union で合う）。test_lib.py はモジュールを 1 行ずつ import の形で読み、2 項目が共にする行が無い。CHANGELOG.md の [Unreleased]
  はモジュールごとの見出し（### calc・### textfmt。間に変わらない行）を持ち、README の決まりが 1 行を直したモジュールの見出しの
  下に足させるので、2 件の CHANGELOG の 1 行も別の所になり 3 方向で合う（2 件をまとめた前後 3 行の差分では 1 つの塊に見える）。
  種の写しの git（gitkit の型）で件ごとの枝を切って参照の直しと受け入れのテストを commit し、git merge でも枝の締めの口
  （unittrees.diff・unittrees.apply）でも食い違わない。依頼の 2 件は別のコードのファイルを名指す（計画役が分ければ項目は
  モジュールごと・重なりは test_lib.py と CHANGELOG.md の別の所だけ。分けるかは計画役が決め、種では縛れない）。
- 依頼は入口の依頼の型（写しの RL の REQUEST_SCHEMA）を通り、where のファイルが種に在る。項目を分けてと文で頼まず、各件は
  CHANGELOG.md を allowed_paths にも out_of_scope にも名指さないと言い、1 行を足す見出しを名指す。0.2.35 までの訳（相談が
  「修正案が明示に外したパス」として断る）は今の相談に合わないので言わない。
- canary-request-fix.json（canary.sh --request fix。修正役の並べの枝を本物で通す）: 種で docstring の無い公開の関数は依頼の 2 件
  （calc.py:clamp・textfmt.py:squeeze）だけで、件ごとの参照の直し（docstring と CHANGELOG の自分の見出しの下の 1 行）は独立に
  効き、振る舞いを変えない（種のテストは緑・既定の依頼の約束は赤のまま）。2 本の枝の CHANGELOG の 1 行は 3 方向で合う。種の README の
  決まりがテストに docstring を縛らせず docstring の直しにも CHANGELOG の 1 行を求め、依頼は道（route）も項目の分け方も言わない。
  殻の --request は知らない語・値の無い旗・2 度の旗を何も作らずに拒む。
- 確かめ役 canary_check.py: 一時の置き場に sqlite の偽の archon.db（Archon の 2 つの表の要る列だけ）と偽の盤面（trace.jsonl・
  plan-fields.json・tdd-<k>/state.json と枝の差分の控え・run-place の相談の記録・report.md）を置き、(a)〜(d) の判じ・案の重なり・
  項目ごとのファイル・費用と取れない節・結末・時間・終了コードと、読むだけで何も書かないことを見る。(e) 修正役の並べは
  偽の包みの起動の記録（home/adapter/launches/*.jsonl）も置き、植えた枝・枝の輪の同時・枝の中の相談・答えの節の旗 fork を見る。
- 固定材料 canary-fixture-units/（canary.sh --request units）: 写しが控えのとおり・seed/ の木が控えの tree・request.json が控えの依頼
  （canary_fixture.problems。書き換えれば名指す）・この機械の置き場の字が無い・案が tdd の 1 項目に 2 単位。seed/ の写しの git（gitkit の型）に
  use.sh と同じ入力で線の start（entry.start）が写しを取り込み、修正の直前の盤面を開いて置き場の印を残さない（works の表・graph・置き場の版が
  写した時と違えば、canary_fixture.stale と start の拒みが同じ物を名指す）。確かめ役の (f)（covered_by で閉じた単位・申し出・裁定）。
子のプロセスは python3（種のテストと PROBES）と git merge-file と、種の写しの git（gitkit の型の写し。リポジトリを作らない）と、
拒みだけを見る sh canary.sh だけ（固定材料の木は canary_fixture.tree_of が git を起こさずに求める）。
"""
import ast
import hashlib
import json
import pathlib
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.dont_write_bytecode = True   # 下の import が pack の中に __pycache__ を作らないように
sys.path.insert(0, str(ROOT / "dev"))
sys.path.insert(0, str(ROOT / ".shared" / "core"))

import adapter  # noqa: E402
import canary_check  # noqa: E402
import canary_fixture  # noqa: E402
import entry  # noqa: E402
import fixture  # noqa: E402
import gitkit  # noqa: E402
import hermetic  # noqa: E402
import unittrees  # noqa: E402

SEED = ROOT / "dev" / "canary-seed"
REQUEST = ROOT / "dev" / "canary-request.json"
REQUEST_FIX = ROOT / "dev" / "canary-request-fix.json"   # canary.sh --request fix（修正役の並べの枝を本物で通す）
CANARY_SH = ROOT / "dev" / "canary.sh"
# canary.sh --request units の固定材料（1 つの修正案の項目に 2 つの単位。本物の run 245042a7 の修正の直前の盤面と、その run の種と依頼）
UNITS = ROOT / "dev" / "canary-fixture-units"
MACHINE = ("/Users/", "/private/", "/var/folders/", "/tmp/claude-")   # この機械の置き場の字（固定材料に残さない）
TOOL = ROOT / "dev" / "canary_check.py"
TESTS = "test_lib.py"   # 種のただ 1 本のテストのファイル（README の決まり）


def _changelog_has(name):
    return ("import pathlib; s = pathlib.Path('CHANGELOG.md').read_text(encoding='utf-8'); "
            "u = s.split('## [Unreleased]', 1)[1].split('\\n## ', 1)[0]; "
            f"assert any(l.startswith('- ') and {name!r} in l for l in u.splitlines())")


# 依頼の 2 件の約束（依頼の text・measured のとおり）と CHANGELOG の行。種では全部赤、参照の直しの後は緑
PROBES = {
    "mean": "import calc; assert calc.mean([1, 2, 3]) == 2 and calc.mean([5]) == 5",
    "initials": "import textfmt; assert textfmt.initials('dark factory line') == 'DFL' and textfmt.initials('') == ''",
    "changelog_mean": _changelog_has("mean"),
    "changelog_initials": _changelog_has("initials"),
}
# 参照の直し（件 → [(ファイル, 前, 後)]）。種には置かない（直しの答えを対象に渡さない）
FIXES = {
    "mean": [("calc.py", "return sum(xs) / (len(xs) - 1)", "return sum(xs) / len(xs)"),
             ("CHANGELOG.md", "### calc\n", "### calc\n\n- mean: 分母を個数にした（算術平均を返す）\n")],
    "initials": [("textfmt.py", 'return "".join(w[0] for w in words(s))', 'return "".join(w[0].upper() for w in words(s))'),
                 ("CHANGELOG.md", "### textfmt\n", "### textfmt\n\n- initials: 頭の字を大文字にした\n")],
}
# 件ごとの CHANGELOG の [Unreleased] の見出し（README の決まり: 直したモジュールの見出しの下に 1 行）
SUBHEADING = {"mean": "### calc", "initials": "### textfmt"}
FIX_PROBES = {"mean": {"mean", "changelog_mean"}, "initials": {"initials", "changelog_initials"}}
# 枝ごとの受け入れのテストの参照（件 → (足す所の後ろの字, 足すテスト)）。README の決まりどおりモジュールのクラスの末尾に足す
CLASS_END = {"mean": "\n\n\nclass TestTextfmt(", "initials": '\n\n\nif __name__ == "__main__":'}
LANE_TESTS = {
    "mean": "\n\n    def test_mean_arithmetic(self):\n        self.assertEqual(calc.mean([1, 2, 3]), 2)\n",
    "initials": "\n\n    def test_initials_lowercase(self):\n        self.assertEqual(textfmt.initials(\"dark factory line\"), \"DFL\")\n",
}
# canary-request-fix.json の 2 件（docstring の欠け）の約束と CHANGELOG の行。種では全部赤、参照の直しの後は緑。振る舞いは変えない
DOC_PROBES = {
    "clamp_doc": "import calc; assert (calc.clamp.__doc__ or '').strip()",
    "squeeze_doc": "import textfmt; assert (textfmt.squeeze.__doc__ or '').strip()",
    "changelog_clamp": _changelog_has("clamp"),
    "changelog_squeeze": _changelog_has("squeeze"),
}
DOC_FIXES = {
    "clamp": [("calc.py", "def clamp(x, lo, hi):\n", 'def clamp(x, lo, hi):\n    """x を [lo, hi] に収める"""\n'),
              ("CHANGELOG.md", "### calc\n", "### calc\n\n- clamp: docstring を足した\n")],
    "squeeze": [("textfmt.py", 'def squeeze(s, ch=" "):\n', 'def squeeze(s, ch=" "):\n    """ch の連なりを 1 つにする"""\n'),
                ("CHANGELOG.md", "### textfmt\n", "### textfmt\n\n- squeeze: docstring を足した\n")],
}
DOC_FIX_PROBES = {"clamp": {"clamp_doc", "changelog_clamp"}, "squeeze": {"squeeze_doc", "changelog_squeeze"}}
PROBE_RUN = """
import json, sys
out = {}
for name, src in json.loads(sys.argv[1]).items():
    try:
        exec(src, {})
        out[name] = True
    except Exception:
        out[name] = False
print(json.dumps(out))
"""


def _env():
    return hermetic.child_env(PYTHONDONTWRITEBYTECODE="1")


def with_lane_tests(text: str, *names) -> str:
    """test_lib.py の中身に、件ごとの受け入れのテストを各クラスの末尾に足した物"""
    for name in names:
        anchor = CLASS_END[name]
        assert text.count(anchor) == 1, anchor
        text = text.replace(anchor, LANE_TESTS[name].rstrip("\n") + anchor)
    return text


class SeedTest(unittest.TestCase):
    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp(prefix="canary-seed-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def copy(self, fixes=(), tests=()):
        d = self.tmp / "-".join(["seed", *fixes, "t", *tests])
        shutil.copytree(SEED, d)
        for name in fixes:
            for rel, old, new in {**FIXES, **DOC_FIXES}[name]:
                p = d / rel
                text = p.read_text(encoding="utf-8")
                self.assertEqual(text.count(old), 1, f"参照の直し {name} の前の字が {rel} に 1 つだけ在る")
                p.write_text(text.replace(old, new), encoding="utf-8")
        if tests:
            p = d / TESTS
            p.write_text(with_lane_tests(p.read_text(encoding="utf-8"), *tests), encoding="utf-8")
        return d

    def probes(self, d, probes=PROBES) -> dict:
        got = subprocess.run([sys.executable, "-c", PROBE_RUN, json.dumps(probes)], cwd=d, env=_env(),
                             capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(got.returncode, 0, got.stderr)
        return json.loads(got.stdout)

    def suite(self, d) -> tuple:
        got = subprocess.run([sys.executable, "-m", "unittest", "-v"], cwd=d, env=_env(), capture_output=True, text=True,
                             encoding="utf-8")
        failed = sorted(line.split(" ", 1)[0] for line in got.stderr.splitlines()
                        if line.endswith(" ... FAIL") or line.endswith(" ... ERROR"))
        return got.returncode, failed, got.stderr

    def suite_green(self, d):
        rc, failed, err = self.suite(d)
        self.assertEqual((rc, failed), (0, []), err[-2000:])
        self.assertIn("OK", err)

    def test_seed_suite_green_and_every_bug_present(self):
        """種のテストは緑（バグを突くテストはまだ無い）で、依頼の 2 件の約束と CHANGELOG の行は全部赤"""
        d = self.copy()
        self.suite_green(d)
        self.assertEqual(self.probes(d), {k: False for k in PROBES})

    def test_each_reference_fix_flips_only_its_own_probes(self):
        """参照の直しは件ごとに独立: 1 件を当てるとその件の約束と CHANGELOG の行だけが緑になる"""
        for name in FIXES:
            with self.subTest(name):
                got = self.probes(self.copy((name,)))
                self.assertEqual({k for k, v in got.items() if v}, FIX_PROBES[name])

    def test_all_reference_fixes_pass_and_keep_suite_green(self):
        d = self.copy(tuple(FIXES))
        self.assertEqual(self.probes(d), {k: True for k in PROBES})
        self.suite_green(d)

    def test_lane_tests_are_red_on_seed_only_for_their_own_bug(self):
        """TDD の赤: 件ごとの受け入れのテストは種では自分のテストだけ落ち、自分の件の直しで緑になる"""
        for name, test in (("mean", "test_mean_arithmetic"), ("initials", "test_initials_lowercase")):
            with self.subTest(name):
                rc, failed, err = self.suite(self.copy(tests=(name,)))
                self.assertEqual((rc != 0, failed), (True, [test]), err[-2000:])
                self.suite_green(self.copy((name,), (name,)))

    def merge(self, base: str, ours: str, theirs: str, *flags) -> tuple:
        for n, text in (("base", base), ("ours", ours), ("theirs", theirs)):
            (self.tmp / n).write_text(text, encoding="utf-8")
        got = subprocess.run(["git", "merge-file", "-p", *flags, str(self.tmp / "ours"), str(self.tmp / "base"),
                              str(self.tmp / "theirs")], capture_output=True, text=True, encoding="utf-8")
        return got.returncode, got.stdout

    def test_two_lanes_tests_merge_cleanly_in_one_test_file(self):
        """(b) の前提: 2 つの枝が test_lib.py の別々のクラスの末尾に足すテストは、3 方向で字の食い違いなしに合い（重なりの
        ファイル）、合わせた test_lib.py は全部の直しの後に緑"""
        base = (SEED / TESTS).read_text(encoding="utf-8")
        ours, theirs = with_lane_tests(base, "mean"), with_lane_tests(base, "initials")
        rc, merged = self.merge(base, ours, theirs)
        self.assertEqual(rc, 0, "字の食い違いが出た")
        self.assertEqual(merged, with_lane_tests(base, "mean", "initials"))
        d = self.copy(tuple(FIXES))
        (d / TESTS).write_text(merged, encoding="utf-8")
        self.suite_green(d)

    def test_tests_appended_to_same_tail_are_insertion_only_conflicts(self):
        """(b) の前提の続き: 2 つの枝が test_lib.py の同じ末尾（main の前）に足すテストは挿しだけの食い違いで、union で両方残る"""
        base = (SEED / TESTS).read_text(encoding="utf-8")
        tail = '\n\n\nif __name__ == "__main__":'
        self.assertEqual(base.count(tail), 1)
        add = "\n\n\nclass Test{0}(unittest.TestCase):\n    def test_{1}(self):\n        self.assertTrue(True)"
        ours = base.replace(tail, add.format("Mean", "mean") + tail)
        theirs = base.replace(tail, add.format("Initials", "initials") + tail)
        rc, _ = self.merge(base, ours, theirs)
        self.assertGreater(rc, 0, "末尾の挿しが食い違わないなら union の道を通らない")
        rc, merged = self.merge(base, ours, theirs, "--union")
        self.assertEqual(rc, 0)
        self.assertIn("class TestMean", merged)
        self.assertIn("class TestInitials", merged)

    def test_changelog_has_a_subheading_per_module_apart(self):
        """(b) の前提: CHANGELOG.md の [Unreleased] はモジュールごとの見出し（### calc・### textfmt）を持ち、2 つの見出しの間に
        変わらない行が在る。README の決まりは 1 行を直したモジュールの見出しの下に足させる。run 245042a7 では見出しの無い
        [Unreleased] の下に 2 件とも 1 行ずつ足す形で、2 つの足しが同じ所（同じ塊）になり、計画役が項目の組み方の『同じ塊』に
        当てて 2 つの単位を 1 項目にまとめた"""
        text = (SEED / "CHANGELOG.md").read_text(encoding="utf-8")
        unreleased = text.split("## [Unreleased]\n", 1)[1].split("\n## ", 1)[0].splitlines()
        heads = [ln for ln in unreleased if ln.startswith("### ")]
        self.assertEqual(heads, [SUBHEADING["mean"], SUBHEADING["initials"]])
        self.assertGreaterEqual(unreleased.index(heads[1]) - unreleased.index(heads[0]), 2, "見出しの間に変わらない行が無い")
        readme = (SEED / "README.md").read_text(encoding="utf-8")
        for head in heads:
            self.assertEqual(text.count(head + "\n"), 1, head)
            self.assertIn(f"`{head}`", readme)

    def test_changelog_lines_of_two_lanes_merge_cleanly(self):
        """(b) の前提の続き: 2 つの枝が CHANGELOG.md の自分のモジュールの見出しの下に足す 1 行は、3 方向で字の食い違いなしに合い、
        合わせた物は 2 件の CHANGELOG の約束を満たす（見出しの無い前の形では同じ所への挿しで食い違った）"""
        base = (SEED / "CHANGELOG.md").read_text(encoding="utf-8")
        sides = []
        for name in ("mean", "initials"):
            (_, old, new), = [f for f in FIXES[name] if f[0] == "CHANGELOG.md"]
            sides.append(base.replace(old, new))
        rc, merged = self.merge(base, *sides)
        self.assertEqual(rc, 0, "字の食い違いが出た:\n" + merged)
        d = self.copy()
        (d / "CHANGELOG.md").write_text(merged, encoding="utf-8")
        got = self.probes(d)
        self.assertEqual((got["changelog_mean"], got["changelog_initials"]), (True, True))

    def test_two_unit_branches_merge_without_conflict(self):
        """(b) の前提を本物の git で: 種の写し（gitkit の型）から件ごとの枝を切り、各枝に参照の直しと受け入れのテストを commit して、
        2 つの枝を git merge で合わせても、片方の枝の差分を他方の枝の上に枝の締めの口（unittrees.diff と unittrees.apply。union なしの
        3 方向）で当てても食い違わない。合わせた木は約束が全部緑で、種のテストと受け入れのテストも緑"""
        repo = self.tmp / "repo"
        gitkit.committed_copy(repo, SEED)
        base = gitkit.git(repo, "rev-parse", "HEAD")
        for name in ("mean", "initials"):
            gitkit.git(repo, "checkout", "-q", "-b", name, base)
            for rel, old, new in FIXES[name]:
                p = repo / rel
                text = p.read_text(encoding="utf-8")
                self.assertEqual(text.count(old), 1, f"参照の直し {name} の前の字が {rel} に 1 つだけ在る")
                p.write_text(text.replace(old, new), encoding="utf-8")
            p = repo / TESTS
            p.write_text(with_lane_tests(p.read_text(encoding="utf-8"), name), encoding="utf-8")
            gitkit.git(repo, "commit", "-q", "-am", name)
        patch = unittrees.diff(repo, base)   # 今の姿は枝 initials
        gitkit.git(repo, "checkout", "-q", "mean")
        got = subprocess.run(["git", *gitkit.GIT_ID, "-C", str(repo), "merge", "--no-ff", "--no-edit", "-q", "initials"],
                             capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(got.returncode, 0, got.stdout + got.stderr)
        self.assertEqual(self.probes(repo), {k: True for k in PROBES})
        self.suite_green(repo)
        merged = gitkit.git(repo, "rev-parse", "HEAD^{tree}")
        gitkit.git(repo, "checkout", "-q", "-b", "applied", "mean")
        self.assertEqual(unittrees.apply(repo, patch), (True, ""))
        gitkit.git(repo, "add", "-A")
        self.assertEqual(gitkit.git(repo, "write-tree"), merged, "当てた木が git merge の木と違う")

    def test_request_passes_entry_schema_and_names_separate_modules(self):
        """依頼は入口の型を通り、where は種に在る別々のコードのファイルを名指す（項目はモジュールごと・重なりはテストのファイル）。
        種のテストのファイルは 1 本で README がその置き方を決める。範囲の相談を通すため、各件は CHANGELOG.md を allowed_paths にも
        out_of_scope にも入れないと修正案に言い、1 行を足すモジュールの見出しを名指す"""
        _, _, items, _, _ = entry._read_request(str(REQUEST), SEED, entry.board_rules())
        files = [it["where"].split(":", 1)[0] for it in items]
        for f in files:
            self.assertTrue((SEED / f).is_file(), f)
        self.assertEqual(sorted(files), ["calc.py", "textfmt.py"])
        self.assertEqual(sorted(p.name for p in SEED.glob("test*.py")), [TESTS])
        readme = (SEED / "README.md").read_text(encoding="utf-8")
        for word in (TESTS, "TestCalc", "TestTextfmt", "CHANGELOG.md"):
            self.assertIn(word, readme)
        heads = {"calc.py": SUBHEADING["mean"], "textfmt.py": SUBHEADING["initials"]}
        for it in items:
            for word in ("CHANGELOG.md", "allowed_paths", "out_of_scope", "範囲の相談", TESTS,
                         heads[it["where"].split(":", 1)[0]]):
                self.assertIn(word, it["text"], it["where"])
            # run 54d81ef1: 計画役が「範囲の外」を out_of_scope に写した。範囲の外と言わない
            self.assertNotIn("範囲の外", it["text"], it["where"])
            # 0.2.36 から相談は out_of_scope に当たる頼みを断らずに答えの節へ回す。前の訳（相談が断る）を工場に言わない
            self.assertNotIn("明示に外したパス", it["text"], it["where"])
            # (b) は種の形で起こす。項目を分けてと文で頼まない（run 01004d2e で効かなかった）
            self.assertNotIn("別の項目", it["text"], it["where"])
        self.assertIn("## [Unreleased]", (SEED / "CHANGELOG.md").read_text(encoding="utf-8"))

    def test_two_items_share_no_line_in_the_test_file(self):
        """(b) の前提の続き: test_lib.py はモジュールを 1 行ずつ import の形で読み（from の行に名を足す形でない）、README も
        そう決める。2 項目が同じ行（run 01004d2e の『同じ import の行』）を触る形を種が作らない"""
        text = (SEED / TESTS).read_text(encoding="utf-8")
        lines = text.splitlines()
        self.assertEqual([ln for ln in lines if ln.startswith(("import ", "from "))], ["import unittest", "import calc", "import textfmt"])
        readme = (SEED / "README.md").read_text(encoding="utf-8")
        self.assertIn("`import calc` の形", readme)
        self.assertIn("`from calc import …` の行は書かない", readme)
        for name in LANE_TESTS:
            self.assertEqual(text.count(CLASS_END[name]), 1, name)

    def test_doc_gaps_present_and_each_doc_fix_is_independent(self):
        """canary-request-fix.json の前提: 種では 2 件の docstring の欠けと CHANGELOG の行が赤。件ごとの参照の直し（docstring を
        足して CHANGELOG の自分の見出しの下に 1 行）はその件の約束だけを緑にし、2 件とも当てても振る舞いは変わらない（種のテストは
        緑のまま・canary-request.json の 2 件の約束は赤のまま）"""
        self.assertEqual(self.probes(self.copy(), DOC_PROBES), {k: False for k in DOC_PROBES})
        for name in DOC_FIXES:
            with self.subTest(name):
                got = self.probes(self.copy((name,)), DOC_PROBES)
                self.assertEqual({k for k, v in got.items() if v}, DOC_FIX_PROBES[name])
        d = self.copy(tuple(DOC_FIXES))
        self.assertEqual(self.probes(d, DOC_PROBES), {k: True for k in DOC_PROBES})
        self.assertEqual(self.probes(d), {k: False for k in PROBES})
        self.suite_green(d)

    def test_doc_changelog_lines_of_two_lanes_merge_cleanly(self):
        """2 本の修正役の枝が CHANGELOG.md の自分のモジュールの見出しの下に足す 1 行は 3 方向で食い違わずに合う（締めの shared）"""
        base = (SEED / "CHANGELOG.md").read_text(encoding="utf-8")
        sides = [base.replace(old, new) for name in DOC_FIXES for rel, old, new in DOC_FIXES[name] if rel == "CHANGELOG.md"]
        rc, merged = self.merge(base, *sides)
        self.assertEqual(rc, 0, "字の食い違いが出た:\n" + merged)
        d = self.copy()
        (d / "CHANGELOG.md").write_text(merged, encoding="utf-8")
        got = self.probes(d, DOC_PROBES)
        self.assertEqual((got["changelog_clamp"], got["changelog_squeeze"]), (True, True))

    def test_only_the_requested_functions_lack_a_docstring(self):
        """種の公開の関数で docstring の無い物は canary-request-fix.json の 2 件だけ（README の決まり: 公開の関数は docstring に約束を
        書く）。ほかの欠けを種が作らない"""
        missing = []
        for mod in ("calc.py", "textfmt.py"):
            tree = ast.parse((SEED / mod).read_text(encoding="utf-8"))
            missing += [f"{mod}:{f.name}" for f in tree.body if isinstance(f, ast.FunctionDef)
                        and not f.name.startswith("_") and ast.get_docstring(f) is None]
        self.assertEqual(missing, ["calc.py:clamp", "textfmt.py:squeeze"])

    def test_readme_rules_make_doc_fixes_test_free_and_logged(self):
        """種の README の決まりが、docstring の直しを先に落ちるテストの無い直し（テストは振る舞いだけを確かめ、docstring の有無や字を
        縛らない）にし、CHANGELOG.md の見出しの下の 1 行を求める。工場の語（route・direct・tdd）で決めない"""
        readme = (SEED / "README.md").read_text(encoding="utf-8")
        for word in ("公開の関数は docstring", "docstring の有無や字はテストで確かめない", "docstring を足した・直した直しも"):
            self.assertIn(word, readme)
        for word in ("route", "direct", "tdd", "TDD"):
            self.assertNotIn(word, readme)

    def test_fix_request_names_doc_gaps_in_separate_modules_and_no_route(self):
        """canary-request-fix.json は入口の型を通り、where は別々のモジュールの docstring の無い関数を名指す。範囲の相談を通すため
        各件は CHANGELOG.md を allowed_paths にも out_of_scope にも名指さないと言い、1 行を足す見出しを名指す。道（route）や
        項目の分け方を文で頼まない（種の README の決まりと docstring の欠けで素直な案が決まる）"""
        _, _, items, _, _ = entry._read_request(str(REQUEST_FIX), SEED, entry.board_rules())
        self.assertEqual(sorted(it["where"] for it in items), ["calc.py:clamp", "textfmt.py:squeeze"])
        heads = {"calc.py": SUBHEADING["mean"], "textfmt.py": SUBHEADING["initials"]}
        for it in items:
            for word in ("CHANGELOG.md", "allowed_paths", "out_of_scope", "範囲の相談", "docstring",
                         heads[it["where"].split(":", 1)[0]]):
                self.assertIn(word, it["text"], it["where"])
            blob = json.dumps(it, ensure_ascii=False)
            for word in ("範囲の外", "明示に外したパス", "別の項目", "route", "direct", "tdd", "TDD", "テストを先に", "並べ", "枝"):
                self.assertNotIn(word, blob, it["where"])

    def test_seed_holds_no_request_pack_or_answers(self):
        """種は対象にそのまま写る: 依頼・pack の写し・参照の直しを持たない"""
        names = {p.relative_to(SEED).as_posix() for p in SEED.rglob("*") if p.is_file()}
        self.assertEqual(names, {".gitignore", "README.md", "CHANGELOG.md", "calc.py", "textfmt.py", TESTS})


class UnitsFixtureTest(unittest.TestCase):
    """canary.sh --request units の固定材料（dev/canary-fixture-units/）: 種の写し seed/・依頼 request.json・盤面の写し fix-fixture/"""

    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp(prefix="canary-units-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def manifest(self, root=UNITS):
        return json.loads((root / canary_fixture.FIXTURE / fixture.MANIFEST).read_text(encoding="utf-8"))

    def test_fixture_is_whole_and_matches_its_seed_and_request(self):
        """写しは控えのとおり（書き換え・欠け・多いファイルが無い）・seed/ の木が控えの tree・request.json の sha256 が控えの依頼"""
        self.assertEqual(canary_fixture.problems(UNITS), [])
        self.assertEqual(sorted(p.name for p in UNITS.iterdir()), ["fix-fixture", "request.json", "seed"])

    def test_fixture_holds_no_path_of_the_machine_it_came_from(self):
        """置き場のパスは控えの置き場の字（board_root・repo_root・pack_root）ごと置き換えの印の下にあり、取り込みが新しい置き場に
        置き換える。この機械の家・一時の置き場の字は残さない"""
        home = str(pathlib.Path.home())
        for p in sorted(UNITS.rglob("*")):
            if p.is_file():
                text = p.read_bytes().decode("utf-8", "replace")
                for word in (*MACHINE, home):
                    self.assertNotIn(word, text, p)
        man = self.manifest()
        for key in ("board_root", "repo_root", "pack_root"):
            self.assertTrue(man[key].startswith(canary_fixture.PORTABLE + "/"), (key, man[key]))

    def test_plan_is_one_tdd_item_holding_two_units(self):
        """狙いの形: 承認済みの修正案は tdd の 1 項目で、判定の 2 つの単位を両方持ち、受け入れのテストは test_lib.py に 2 本"""
        board = UNITS / canary_fixture.FIXTURE / fixture.COPY
        fields = json.loads((board / "plan-fields.json").read_text(encoding="utf-8"))["fields"]
        self.assertEqual(len(fields), 1)
        self.assertEqual(fields[0]["route"], "tdd")
        units = json.loads((board / "r1" / "structure-units.json").read_text(encoding="utf-8"))
        self.assertEqual(sorted(fields[0]["unit_keys"]), sorted(u["id"] for u in units))
        self.assertEqual(len(units), 2)
        self.assertEqual([t["id"].split("::", 1)[0] for t in fields[0]["tests"]], [TESTS, TESTS])

    def test_problems_name_a_changed_seed_request_or_board(self):
        """種・依頼・盤面の写しのどれかを書き換えた固定材料は、何が違うかを名指す"""
        for what, rel, word in (("seed", "seed/calc.py", "tree"), ("request", "request.json", "依頼"),
                                ("board", "fix-fixture/board/plan-fields.json", "書き換わった")):
            with self.subTest(what):
                root = self.tmp / what
                shutil.copytree(UNITS, root)
                with (root / rel).open("a", encoding="utf-8") as f:
                    f.write("\n")
                got = canary_fixture.problems(root)
                self.assertTrue(any(word in p for p in got), got)

    def test_fixture_adopts_on_its_seed_or_is_named_stale(self):
        """use.sh が渡す入力（canary.sh --request units の形）で、seed/ を commit した対象に線の start が写しを取り込み、修正の直前の
        盤面を開く（判定・修正案の役は起こさない）。置き場の印の字は新しい置き場になる。今の works の表・graph・置き場の版が写した
        時と違えば、canary_fixture.stale が名指し、start も「固定材料と works の版が違う」で拒む（どちらも同じ物を見る）"""
        repo = self.tmp / "repo"
        gitkit.committed_copy(repo, UNITS / "seed")
        self.assertEqual(gitkit.git(repo, "rev-parse", "HEAD^{tree}"), self.manifest()["tree"])
        request = self.tmp / "request.json"
        shutil.copy(UNITS / "request.json", request)
        raw = {"request": str(request), "test_cmd": "python3 -m pytest -q", "tdd_suite": "", "adapter": "",
               "final_gate": "protected_only", "unattended": "true", "fix_fixture": str(UNITS / canary_fixture.FIXTURE)}
        board = self.tmp / "artifacts" / "runs" / "run-units" / "board"
        stale = canary_fixture.stale(UNITS)
        if stale:
            with self.assertRaises(entry.InputRefused) as cm:
                entry.start(board, repo, raw, run_id="run-units")
            self.assertIn(entry.FIXTURE_MISMATCH, str(cm.exception))
            return
        out = entry.start(board, repo, raw, run_id="run-units")
        self.assertTrue(out["ok"])
        self.assertIn(f"固定材料から（run {self.manifest()['source_run']} の修正の前", out["head_line"])
        self.assertIn("p3.fix", entry.open_board(board).ready())
        for p in sorted(board.rglob("*")):
            if p.is_file():
                text = p.read_bytes().decode("utf-8", "replace")
                for mark in ("artifacts", "worktree", "pack"):
                    self.assertNotIn(f"{canary_fixture.PORTABLE}/{mark}", text, p)


class CanaryShTest(unittest.TestCase):
    """canary.sh の --request（tdd は canary-request.json・fix は canary-request-fix.json）。知らない語・値の無い旗は何も作らずに 2"""

    def test_unknown_or_missing_request_is_refused_before_anything(self):
        tmp = pathlib.Path(tempfile.mkdtemp(prefix="canary-sh-"))
        self.addCleanup(shutil.rmtree, tmp, True)
        for name, args in {"知らない語": ("--request", "nope"), "値が無い": ("--request",), "空の語": ("--request", ""),
                           "空の語の後の旗": ("--request", "", "--request", "fix"),
                           "旗が 2 度": ("--request", "fix", "--request", "tdd")}.items():
            with self.subTest(name):
                place = tmp / "place"
                got = subprocess.run(["sh", str(CANARY_SH), "--build-only", *args, *([str(place)] if args[-1] != "--request" else [])],
                                     capture_output=True, text=True, encoding="utf-8", env=_env())
                self.assertEqual(got.returncode, 2, got.stdout + got.stderr)
                self.assertEqual(len(got.stderr.strip().splitlines()), 1, got.stderr)
                self.assertFalse(place.exists())

    def test_each_request_word_names_an_existing_request_file(self):
        """canary.sh の頭の語と依頼のファイルの対応が、在るファイルを名指す"""
        text = CANARY_SH.read_text(encoding="utf-8")
        for word, path in (("tdd", REQUEST), ("fix", REQUEST_FIX)):
            self.assertIn(f"{word}) REQUEST=\"$DEV_DIR/{path.name}\"", text)
            self.assertTrue(path.is_file(), path)

    def test_units_starts_from_the_fixture_with_its_own_seed_and_request(self):
        """--request units は固定材料のフォルダの種・依頼を使い、起動に WORKS_USE_FIX_FIXTURE を付け、作る前に
        canary_fixture.py check で確かめる。ほかの語では利用者の殻に残った WORKS_USE_FIX_FIXTURE を外す"""
        text = CANARY_SH.read_text(encoding="utf-8")
        block = text.split("  units)\n", 1)[1].split(";;", 1)[0]
        self.assertIn(f'UNITS="$DEV_DIR/{UNITS.name}"', block)
        for line, rel in (('SEED="$UNITS/seed"', "seed"), ('REQUEST="$UNITS/request.json"', "request.json"),
                          (f'FIXTURE="$UNITS/{canary_fixture.FIXTURE}"', canary_fixture.FIXTURE)):
            self.assertIn(line, block)
            self.assertTrue((UNITS / rel).exists(), rel)
        self.assertIn('canary_fixture.py" check "$UNITS"', text)
        self.assertIn('${FIXTURE:+ WORKS_USE_FIX_FIXTURE=$FIXTURE}', text)
        self.assertIn("unset WORKS_USE_FIX_FIXTURE", text)


# ---------------------------------------------------------------- 偽の archon.db と盤面
RUN = "run-canary"


def at(sec):
    """出来事の created_at（2026-10-07 の 10 時から sec 秒後。Archon の形の秒の粒）"""
    s = 10 * 3600 + sec
    return f"2026-10-07 {s // 3600:02d}:{s // 60 % 60:02d}:{s % 60:02d}"


def ev(kind, step, sec, **data):
    return (kind, step, data, at(sec))


def task(step, tid, start, end, kind="local_agent"):
    return [ev("task_activity", step, start, task_id=tid, activity="started", task_type=kind),
            ev("task_activity", step, end, task_id=tid, activity="completed")]


def node(step, start, end, usd=0.5, kind="agent"):
    cost = {"source": "provider", "value": usd} if usd is not None else {"source": "unavailable", "reason": "x"}
    return [ev("node_started", step, start, node={"id": step, "kind": kind}),
            ev("node_completed", step, end, node={"id": step, "kind": kind}, spend={"costUsd": cost})]


def make_db(path, output_root, events, run=RUN):
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE remote_agent_workflow_runs (id TEXT PRIMARY KEY, workflow_name TEXT, status TEXT, "
                "started_at TEXT, completed_at TEXT, output_root TEXT)")
    con.execute("CREATE TABLE remote_agent_workflow_events (id TEXT PRIMARY KEY, workflow_run_id TEXT, event_order INTEGER, "
                "event_type TEXT, step_index INTEGER, step_name TEXT, data TEXT, created_at TEXT)")
    con.execute("INSERT INTO remote_agent_workflow_runs VALUES (?, 'darkfactory', 'completed', ?, ?, ?)",
                (run, at(0), at(600), str(output_root)))
    for n, (kind, step, data, when) in enumerate(events, 1):
        con.execute("INSERT INTO remote_agent_workflow_events VALUES (?, ?, ?, ?, NULL, ?, ?, ?)",
                    (f"{run}-{n}", run, n, kind, step, json.dumps(data, ensure_ascii=False), when))
    con.commit()
    con.close()


def write(path, doc):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(doc if isinstance(doc, str) else json.dumps(doc, ensure_ascii=False), encoding="utf-8")


U_MEAN, U_INITIALS = "calc.py:mean 分母", "textfmt.py:initials 大文字"
ITEMS = [{"route": "tdd", "unit_keys": [U_MEAN], "allowed_paths": ["calc.py"],
          "tests": [{"id": "test_lib.py::TestCalc::test_mean_arithmetic"}]},
         {"route": "tdd", "unit_keys": [U_INITIALS], "allowed_paths": ["textfmt.py"],
          "tests": [{"id": "test_lib.py::TestTextfmt::test_initials_lowercase"}]}]


def make_board(board, *, lanes=None, units=None, asks=(), unsettled=(), replans=0, items=ITEMS, patches=None, report=None,
               skipped=(), fix_lanes=None, planted=()):
    write(board / "plan-fields.json", {"round": 1, "fields": items})
    trace = [{"t": "x", "op": "init"}]
    trace += [{"t": "x", "op": "lanes_skipped", **r, "scope": "fixing"} for r in skipped]
    trace += [{"t": "x", "op": "fix_lanes_planted", "node": "fix-fork", **r, "scope": "fixing"} for r in planted]
    if fix_lanes is not None:   # 修正役の並べの締めの行（fixlanes.SETTLED_OP）
        trace.append({"t": "x", "op": "fix_lanes_settled", "node": "fix-join", "parked": [], "reverted": [], "outcomes": [],
                      **fix_lanes, "scope": "fixing"})
    if units is not None:
        trace.append({"t": "x", "op": "units_settled", "node": "fix-units", "machine": [], "carried": 0, **units,
                      "scope": "fixing"})
    trace += [{"t": "x", "op": "plan_scope_asked", **a, "scope": "fixing"} for a in asks]
    trace += [{"t": "x", "op": "replan_state", "id": f"c1-{n}", "state": "amended"} for n in range(replans)]
    write(board / "trace.jsonl", "\n".join(json.dumps(r, ensure_ascii=False) for r in trace) + "\n{broken\n")
    if lanes is not None:
        write(board / "tdd-1" / "state.json", {"phase": "fix", "lanes": lanes})
    for n, files in (patches or {}).items():
        write(board / "tdd-1" / "lanes" / f"item-{n}.patch", "".join(f"diff --git a/{f} b/{f}\n--- a/{f}\n+++ b/{f}\n"
                                                                      for f in files))
    if report is not None:
        write(board / "report.md", report)
    write(board / "tdd-2" / "state.json", {"phase": "route"})   # 並べなかった輪は数えない
    if unsettled:
        write(board.parent / "run-place" / "fixing" / "ask-plan" / "exchanges.jsonl",
              "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in unsettled))


FULL_LANES = {"rows": [{"n": 1, "unit_keys": [U_MEAN]}, {"n": 2, "unit_keys": [U_INITIALS]}, {"n": 3, "unit_keys": ["u3"]}],
              "shared": ["test_lib.py"], "expect": [[1, 2]],
              "out": [{"unit_key": U_MEAN, "outcome": "merged", "lane": 1, "merge": "clean"},
                      {"unit_key": U_INITIALS, "outcome": "merged", "lane": 2, "merge": "clean"},
                      {"unit_key": "u3", "outcome": "merged", "lane": 3, "merge": "union"}]}
FULL_PATCHES = {1: ["calc.py", "test_lib.py"], 2: ["test_lib.py", "textfmt.py"]}
FULL_REPORT = "# 報告（run x）\n\n起きたこと: 直した（fixed）\n決めてほしいこと: 無い\n"
ANSWERED = {"id": 1, "item": "1", "status": "answered", "decision": "allow", "paths": ["CHANGELOG.md"],
            "granted_paths": ["CHANGELOG.md"]}


def lane(n, start, end, usd=0.25):
    """枝の輪 n（輪の節と中の支度・役・確かめ。docs/plans/2026-10-07-lane-nodes.md）"""
    loop = f"fixing__tdd-lane-loop-{n}"
    return [*node(loop, start, end, usd=None, kind="loop_group"), *node(f"{loop}.tdd-lane-prep-{n}", start, start + 1, kind="exec"),
            *node(f"{loop}.tdd-lane-{n}", start + 1, end - 1, usd=usd), *node(f"{loop}.tdd-lane-step-{n}", end - 1, end, kind="exec")]


def full_events():
    tdd = "fixing__tdd-loop.tdd"
    fix = "fixing__fix-loop.fix"
    return [*node("start", 0, 5, kind="exec"), *node(tdd, 10, 15, usd=0.5),
            *lane(1, 20, 100), *lane(2, 21, 90), *lane(3, 22, 80),
            *node(fix, 210, 400, usd=2.0), *task(fix, "f1", 220, 300), *task(fix, "f2", 250, 380),
            *node("fixing__fix-loop", 205, 405, usd=3.25, kind="loop_group"), *node("report", 410, 420, usd=None),
            ev("tool_called", fix, 600)]


PLANNER = "planner-session"
CREATED, LATER = "2026-10-07T10:00:00+09:00", "2026-10-07T10:05:00+09:00"   # 盤面を作った時刻と、その後の起動の時刻
WORKTREE = "/nonexistent/works-canary/worktrees/task-darkfactory-1"   # 盤面の state.json の inputs.cwd（run の worktree）
DOC_ITEMS = [{"route": "direct", "unit_keys": ["calc.py:clamp docstring"], "allowed_paths": ["calc.py"], "tests": []},
             {"route": "direct", "unit_keys": ["textfmt.py:squeeze docstring"], "allowed_paths": ["textfmt.py"], "tests": []}]


def fixer_lane(n, start, end):
    """修正役の並べの枝の輪 n（輪の節と中の支度・役・相談の 3 節・確かめ。docs/plans/2026-10-07-fix-lane-nodes.md）"""
    loop = f"fixing__fix-lane-loop-{n}"
    return [*node(loop, start, end, usd=None, kind="loop_group"),
            *node(f"{loop}.fix-lane-prep-{n}", start, start + 1, kind="exec"),
            *node(f"{loop}.fix-lane-{n}", start + 1, end - 4, usd=0.5),
            *node(f"{loop}.fix-lane-consult-{n}", end - 4, end - 3, kind="exec"),
            *node(f"{loop}.plan-answer-lane-{n}", end - 3, end - 2, usd=0.1),
            *node(f"{loop}.fix-lane-consult-check-{n}", end - 2, end - 1, kind="exec"),
            *node(f"{loop}.fix-lane-step-{n}", end - 1, end, kind="exec")]


class CheckTest(unittest.TestCase):
    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp(prefix="canary-check-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.root = self.tmp / "canary"
        self.out_root = self.tmp / "origin"
        self.board = self.out_root / "artifacts" / "runs" / RUN / "board"
        self.db = self.root / "home" / "archon-home" / "archon.db"
        self.db.parent.mkdir(parents=True)

    def run_tool(self, *args):
        return subprocess.run([sys.executable, str(TOOL), *args], capture_output=True, text=True, encoding="utf-8", env=_env())

    def full(self):
        make_db(self.db, self.out_root, full_events())
        make_board(self.board, lanes=FULL_LANES, asks=[ANSWERED], patches=FULL_PATCHES, report=FULL_REPORT,
                   units={"applied": [1, 2], "conflict": [], "unmerged": [], "shared": [], "union": []})
        write(self.root / "home" / "runs" / f"{RUN}.json", {})
        write(self.root / "home" / "diffs" / f"run-{RUN}.diff",
              "diff --git a/calc.py b/calc.py\n--- a/calc.py\n+++ b/calc.py\n"
              "diff --git a/CHANGELOG.md b/CHANGELOG.md\n")

    def test_full_run_reports_every_feature_and_exits_zero(self):
        """canary の置き場の形（run-id は控えの一番新しい物・差分は home/diffs）から読み、(a)(b)(c) が yes なら 0"""
        self.full()
        got = self.run_tool(str(self.root), "--json")
        self.assertEqual(got.returncode, 0, got.stdout + got.stderr)
        doc = json.loads(got.stdout)
        f = doc["features"]
        self.assertEqual([f[k]["status"] for k in ("a_parallel", "b_overlap", "c_consult", "d_replan")],
                         ["yes", "yes", "yes", "no"])
        self.assertIn("TDD の輪の枝 3 本・枝の輪の同時の最大 3", f["a_parallel"]["why"])
        self.assertIn("修正役が当てた項目 2・修正役の下請けの同時の最大 2", f["a_parallel"]["why"])
        self.assertEqual(doc["agents"], {"fixing__fix-loop.fix": {"tasks": 2, "parallel": 2}})
        self.assertEqual(doc["lane_nodes"], {"lanes": 3, "parallel": 3}, "枝の輪と中の節は枝ごとに 1 本の区間")
        self.assertEqual([(i["item"], i["files"], i["test_files"]) for i in doc["plan_items"]],
                         [(1, ["calc.py", "test_lib.py"], ["test_lib.py"]), (2, ["test_lib.py", "textfmt.py"], ["test_lib.py"])])
        self.assertEqual(doc["planned_overlap"], {"test_lib.py": [1, 2]}, "項目はモジュールごと・重なりはテストのファイル")
        self.assertIn("案の重なり test_lib.py 項目 [1, 2]", f["b_overlap"]["why"])
        self.assertEqual([(r["lane"], r["items"], r["files"]) for r in doc["tdd_lanes"][0]["rows"]],
                         [(1, [1], ["calc.py", "test_lib.py"]), (2, [2], ["test_lib.py", "textfmt.py"]), (3, [], None)])
        self.assertEqual(doc["outcome"], "fixed")
        # 費用は AI の節だけ（loop_group と exec は足さない）・報告の無い節は名と理由つきで数える・時間は出来事の最初から最後まで
        missing = doc["spend"].pop("cost_missing")
        self.assertEqual(doc["spend"], {"cost_usd": 3.25, "cost_missing_nodes": 1, "minutes": 10.0})
        self.assertEqual([m["node"] for m in missing], ["report"])
        self.assertIn("unavailable", missing[0]["why"])
        self.assertEqual(doc["nodes"]["parallel"], 6, "22 秒: 枝の輪 3 本と中の役 2 つと支度 1 つ（輪の節と中の節を別に数える）")
        self.assertEqual(doc["diff_files"], ["calc.py", "CHANGELOG.md"])
        self.assertEqual(doc["tdd_lanes"][0]["loop"], "tdd-1")
        self.assertEqual(len(doc["tdd_lanes"]), 1)
        text = self.run_tool(str(self.root), RUN)
        self.assertEqual(text.returncode, 0)
        self.assertIn("(c) 範囲の相談: yes", text.stdout)
        self.assertIn("差分のファイル: calc.py・CHANGELOG.md", text.stdout)
        self.assertIn("結末 fixed", text.stdout)
        self.assertIn("  1 tdd 範囲 ['calc.py']・テスト ['test_lib.py']・枝の差分 tdd-1 枝 1 ['calc.py', 'test_lib.py']", text.stdout)
        self.assertIn("取れない節 1: report", text.stdout)

    def test_reads_only(self):
        """db・盤面・置き場のどのファイルも書き換えない"""
        self.full()

        def snap():
            return {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(self.tmp.rglob("*")) if p.is_file()}

        before = snap()
        self.assertEqual(self.run_tool(str(self.root)).returncode, 0)
        self.assertEqual(snap(), before)

    def test_serial_lanes_and_unanswered_consults_are_not_yes(self):
        """枝が 2 本でも枝の輪が順（端が触れるだけ）なら (a) は no。見込みだけで字の食い違いで戻ったなら (b) は attempted。
        断った・聞けなかった相談だけなら (c) は attempted。終了コードは 1"""
        make_db(self.db, self.out_root, [*lane(1, 10, 50), *lane(2, 50, 90)])
        lanes = {"rows": [{"n": 1}, {"n": 2}], "shared": [], "expect": [[1, 2]],
                 "out": [{"lane": 1, "outcome": "merged", "merge": "clean"}, {"lane": 2, "outcome": "serial", "merge": "conflict"}]}
        refused = "CHANGELOG.md は項目 1 の out_of_scope（CHANGELOG.md）に当たる"
        make_board(self.board, lanes=lanes, asks=[{**ANSWERED, "status": "refused", "decision": "", "why_refused": refused}],
                   unsettled=[{"id": 2, "item": "1", "status": "unavailable"}], replans=1)
        got = self.run_tool("--db", str(self.db), "--run", RUN, "--json")
        self.assertEqual(got.returncode, 1, got.stderr)
        f = json.loads(got.stdout)["features"]
        self.assertEqual([f[k]["status"] for k in ("a_parallel", "b_overlap", "c_consult", "d_replan")],
                         ["no", "attempted", "attempted", "yes"])
        self.assertIn("refused・unavailable", f["c_consult"]["why"])
        self.assertIn(f"断った訳: {refused}", f["c_consult"]["why"], "断った相談の訳を添える")

    def test_unsettled_consult_counts_and_trace_wins_on_same_id(self):
        """受け付けがまだ trace へ写していない run-place の答えも数える。同じ scope と id は trace の行だけ"""
        make_db(self.db, self.out_root, [])
        make_board(self.board, asks=[{**ANSWERED, "status": "refused"}],
                   unsettled=[{**ANSWERED}, {**ANSWERED, "id": 2, "decision": "deny", "granted_paths": []}])
        doc = canary_check.check(RUN, {"status": "completed"}, [], self.board)
        self.assertEqual([(r["id"], r["status"], r["settled"]) for r in doc["consults"]],
                         [(1, "refused", True), (2, "answered", False)])
        self.assertEqual(doc["features"]["c_consult"]["status"], "yes")
        self.assertEqual(doc["features"]["a_parallel"]["status"], "no")
        self.assertEqual(doc["features"]["b_overlap"]["status"], "attempted", "案の重なりだけで合わせの記録が無い")
        self.assertIn("案の重なり test_lib.py 項目 [1, 2]", doc["features"]["b_overlap"]["why"])
        self.assertEqual(doc["spend"], {"cost_usd": 0.0, "cost_missing_nodes": 0, "cost_missing": [], "minutes": None})
        self.assertEqual(doc["outcome"], "", "報告が無い")

    def test_plan_without_shared_file_is_no_overlap(self):
        """計画役が同じファイルの単位を 1 項目にまとめ、項目どうしがファイルを共にしなければ (b) は no で、そう言う
        （run 01004d2e の形: calc の項目と textfmt の 2 単位の項目。テストも別のファイル）"""
        make_db(self.db, self.out_root, [])
        merged = [{"route": "tdd", "unit_keys": [U_MEAN], "allowed_paths": ["calc.py", "test_calc.py"]},
                  {"route": "tdd", "unit_keys": [U_INITIALS, "u3"], "allowed_paths": ["textfmt.py", "test_textfmt.py"]}]
        make_board(self.board, items=merged, report="起きたこと: 決めた周の数のうちに直しきれずに止まった（round_limit）\n")
        doc = canary_check.check(RUN, {}, [], self.board)
        self.assertEqual(doc["planned_overlap"], {})
        self.assertEqual(doc["features"]["b_overlap"]["status"], "no")
        self.assertIn("1 項目にまとめた", doc["features"]["b_overlap"]["why"])
        self.assertEqual(doc["outcome"], "round_limit")

    def test_lanes_skip_reason_is_named_when_a_is_no(self):
        """(a) が no の時、TDD の輪が並べなかった理由（盤面の trace の lanes_skipped。節 tdd-step が積む）を (a) の why と出力に出す"""
        make_db(self.db, self.out_root, [])
        why = "単位 2 つを修正案の項目でまとめた枝が 1 本で、範囲の引ける枝が 1 本（並べは 2 本から）"
        make_board(self.board, skipped=[{"reason": "lanes", "why": why, "loop": "tdd-1"}])
        doc = canary_check.check(RUN, {}, [], self.board)
        a = doc["features"]["a_parallel"]
        self.assertEqual(a["status"], "no")
        self.assertIn(f"TDD の輪が並べなかった理由: fixing tdd-1 lanes（{why}）", a["why"])
        self.assertEqual(doc["lanes_skipped"], [{"scope": "fixing", "loop": "tdd-1", "reason": "lanes", "why": why}])
        make_board(self.board)
        self.assertEqual(canary_check.check(RUN, {}, [], self.board)["lanes_skipped"], [])
        self.assertNotIn("並べなかった理由", canary_check.check(RUN, {}, [], self.board)["features"]["a_parallel"]["why"])

    def test_fix_lanes_not_planted_reason_is_named_when_a_is_no(self):
        """(a) が no の時、修正役の並べを切らなかった理由（盤面の trace の fix_lanes_planted の lanes 0。節 fix-fork が積む）も
        (a) の why と出力に出す。TDD の輪の lanes_skipped と並べて読む"""
        make_db(self.db, self.out_root, [])
        why = "並べる枝が 2 本に満たない（範囲の在る項目 1・枝 1）"
        make_board(self.board, planted=[{"lanes": 0, "why": why}],
                   skipped=[{"reason": "units", "why": "TDD の輪で直す単位が 1 つ（並べは 2 つから）", "loop": "tdd-1"}])
        doc = canary_check.check(RUN, {}, [], self.board)
        a = doc["features"]["a_parallel"]
        self.assertEqual(a["status"], "no")
        self.assertIn(f"修正役の並べを切らなかった理由: fixing（{why}）", a["why"])
        self.assertIn("TDD の輪が並べなかった理由", a["why"])
        self.assertEqual(doc["fix_lanes_skipped"], [{"scope": "fixing", "why": why}])
        make_board(self.board, planted=[{"lanes": 2, "items": {"1": [1], "2": [2]}, "rest": [], "expect": []}])
        doc = canary_check.check(RUN, {}, [], self.board)
        self.assertEqual(doc["fix_lanes_skipped"], [])
        self.assertNotIn("切らなかった理由", doc["features"]["a_parallel"]["why"])

    def test_fixer_lanes_count_for_parallel_and_overlap(self):
        """修正役の並べの枝の輪（fix-lane-loop-<n> と中の節）が同時に 2 本以上走り、締めの行の枝が 2 本以上なら (a) の yes。締めの行の
        shared・union は (b) の yes（docs/plans/2026-10-07-fix-lane-nodes.md）"""
        def fix_lane(n, start, end):
            loop = f"fixing__fix-lane-loop-{n}"
            return [*node(loop, start, end, usd=None, kind="loop_group"),
                    *node(f"{loop}.fix-lane-prep-{n}", start, start + 1, kind="exec"),
                    *node(f"{loop}.fix-lane-{n}", start + 1, end - 3, usd=0.5),
                    *node(f"{loop}.plan-answer-lane-{n}", end - 3, end - 2, usd=0.1),
                    *node(f"{loop}.fix-lane-step-{n}", end - 1, end, kind="exec")]
        make_db(self.db, self.out_root, [*fix_lane(1, 10, 60), *fix_lane(2, 12, 50)])
        make_board(self.board, fix_lanes={"lanes": 2, "merged": [1, 2], "back": [], "shared": ["test_lib.py"], "union": []})
        row, events = canary_check.read_run(self.db, RUN)
        got = canary_check.check(RUN, row, events, self.board)
        f = got["features"]
        self.assertEqual(f["a_parallel"]["status"], "yes", f["a_parallel"]["why"])
        self.assertIn("修正役の並べの枝 2 本", f["a_parallel"]["why"])
        self.assertEqual(got["fix_lane_nodes"], {"lanes": 2, "parallel": 2})
        self.assertEqual(f["b_overlap"]["status"], "yes")
        self.assertIn("test_lib.py", f["b_overlap"]["why"])
        self.db.unlink()
        make_db(self.db, self.out_root, [*fix_lane(1, 10, 30), *fix_lane(2, 30, 50)])
        row, serial = canary_check.read_run(self.db, RUN)
        self.assertEqual(canary_check.check(RUN, row, serial, self.board)["features"]["a_parallel"]["status"], "no",
                         "枝の輪が順に走っただけなら並べの証拠でない")

    def fixer_run(self, *, fork=True, asks=None, launches=True, planted=2, second=(12, 50), answer=None):
        """修正役の並べの run の形（canary-request-fix.json の狙い）: 枝の輪 2 本・植えた行と締めの行・枝の中の相談・包みの起動の記録"""
        make_db(self.db, self.out_root, [*fixer_lane(1, 10, 60), *fixer_lane(2, *second)])
        planted_rows = ([{"lanes": planted, "items": {"1": [1], "2": [2]}, "rest": [], "expect": []}] if planted
                        else [{"lanes": 0, "why": "並べる枝が 2 本に満たない（範囲の在る項目 0・枝 0）"}])
        lane_asks = [{**ANSWERED, "id": n, "item": str(n), "pass": f"lane-{n}", "node": f"plan-answer-lane-{n}"}
                     for n in (1, 2)] if asks is None else asks
        make_board(self.board, items=DOC_ITEMS, planted=planted_rows, asks=lane_asks,
                   fix_lanes={"lanes": 2, "merged": [1, 2], "back": [], "shared": ["CHANGELOG.md"], "union": []}
                   if planted else None, report=FULL_REPORT)
        write(self.root / "home" / "runs" / f"{RUN}.json", {})
        write(self.board / "state.json", {"created": CREATED, "inputs": {"cwd": WORKTREE}})
        if launches:
            # 同じ worktree の前の run の行（盤面を作る前）は読まない
            rows = [{"at": "2026-10-07T09:00:00+09:00", "node": "plan-answer-lane-1",
                     "session": {"mode": "continued", "id": "old", "of": "fix-planner", "from": "old-planner"}},
                    {"at": LATER, "node": "premises", "session": {"mode": "new", "id": "s0"}},
                    {"at": LATER, "node": "plan", "session": {"mode": "new", "id": PLANNER}}]
            for n in (1, 2):
                s = {"mode": "continued", "id": f"fork-{n}", "of": "fix-planner", "from": PLANNER}
                s = {**s, "fork": True} if fork else {**s, "id": PLANNER}
                rows.append({"at": LATER, "node": f"plan-answer-lane-{n}", "session": {**s, **(answer or {})}})
            launches_dir = self.root / "home" / "adapter" / "launches"
            write(launches_dir / f"{adapter.cwd_key(WORKTREE)}.jsonl",
                  "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows))
            # ほかの worktree の起動の記録は読まない
            write(launches_dir / f"{adapter.cwd_key(WORKTREE + '-other')}.jsonl",
                  json.dumps({"at": LATER, "node": "plan-answer-lane-1", "session": {"mode": "continued", "id": PLANNER}}) + "\n")

    def test_fixer_lane_run_reports_lanes_consults_and_fork(self):
        """(e) 修正役の並べ: 植えた枝 2 本・枝の輪の同時の最大 2・枝の中の相談（pass が lane-<n>）の答え・答えの節の起動が旗 fork
        （包みの起動の記録の session が mode continued・fork true・元は修正案の役の会話・新しい id）なら yes。--request fix は
        (e) も終了コードに入れる"""
        self.fixer_run()
        got = self.run_tool(str(self.root), "--request", "fix", "--json")
        self.assertEqual(got.returncode, 0, got.stdout + got.stderr)
        doc = json.loads(got.stdout)
        e = doc["features"]["e_fix_lanes"]
        self.assertEqual(e["status"], "yes", e["why"])
        for word in ("植えた枝 2 本", "枝の輪の同時の最大 2", "枝の中の相談 2（答えた 2）", "旗 fork の起動 2/2"):
            self.assertIn(word, e["why"])
        fl = doc["fix_lane_run"]
        self.assertEqual((fl["planted"], fl["items"], fl["parallel"]), (2, {"1": [1], "2": [2]}, 2))
        self.assertEqual(fl["settled"], {"lanes": 2, "merged": [1, 2], "back": [], "parked": [], "shared": ["CHANGELOG.md"],
                                         "union": []})
        self.assertEqual([(r["lane"], r["status"], r["decision"]) for r in fl["consults"]],
                         [("lane-1", "answered", "allow"), ("lane-2", "answered", "allow")])
        self.assertEqual([(r["node"], r["mode"], r["fork"], r["of"], r["from"], r["id"]) for r in fl["answer_launches"]],
                         [("plan-answer-lane-1", "continued", True, "fix-planner", PLANNER, "fork-1"),
                          ("plan-answer-lane-2", "continued", True, "fix-planner", PLANNER, "fork-2")])
        self.assertEqual(doc["features"]["a_parallel"]["status"], "yes")
        self.assertEqual(doc["features"]["b_overlap"]["status"], "yes", "2 本の枝の CHANGELOG.md を締めが合わせた")
        text = self.run_tool(str(self.root), "--request", "fix")
        self.assertEqual(text.returncode, 0)
        self.assertIn("(e) 修正役の並べ: yes", text.stdout)
        self.assertIn("  plan-answer-lane-1 continued fork 元 fix-planner", text.stdout)

    def test_fixer_lane_answer_without_fork_is_attempted(self):
        """答えの節の起動が旗 fork でない（元の会話に積んだ）なら (e) は attempted で、その節を名指す。--request fix の終了コードは 1、
        --request が無ければ (e) は終了コードに入れない"""
        self.fixer_run(fork=False)
        got = self.run_tool(str(self.root), "--request", "fix", "--json")
        self.assertEqual(got.returncode, 1, got.stderr)
        e = json.loads(got.stdout)["features"]["e_fix_lanes"]
        self.assertEqual(e["status"], "attempted")
        self.assertIn("旗 fork の起動 0/2", e["why"])
        self.assertIn("plan-answer-lane-1", e["why"])
        self.assertEqual(self.run_tool(str(self.root)).returncode, 0, "既定の canary は (a)〜(c) だけで終了コードを決める")

    def test_fixer_lanes_without_lane_consult_or_launches_are_attempted(self):
        """枝が並んでも、枝の中の相談が無い（修正の輪の相談だけ）か、包みの起動の記録が無ければ (e) は attempted"""
        self.fixer_run(asks=[{**ANSWERED, "pass": "first", "node": "plan-answer"}])
        e = json.loads(self.run_tool(str(self.root), "--json").stdout)["features"]["e_fix_lanes"]
        self.assertEqual(e["status"], "attempted")
        self.assertIn("枝の中の相談 0", e["why"])
        shutil.rmtree(self.root / "home" / "adapter")
        doc = json.loads(self.run_tool(str(self.root), "--json").stdout)
        self.assertEqual(doc["features"]["e_fix_lanes"]["status"], "attempted")
        self.assertIn("包みの起動の記録が無い", doc["features"]["e_fix_lanes"]["why"])
        self.assertEqual(doc["fix_lane_run"]["answer_launches"], [])

    def test_fork_must_copy_the_planner_conversation(self):
        """答えの節の起動が fork でも、元（of）が修正案の役の会話（fix-planner）でないか、写しの元 from が修正案の役（節 plan）の
        起動の id でなければ attempted"""
        for name, over in {"of": {"of": "fix"}, "from": {"from": "someone-else"}}.items():
            with self.subTest(name):
                self.db.unlink(missing_ok=True)
                self.fixer_run(answer=over)
                e = json.loads(self.run_tool(str(self.root), "--json").stdout)["features"]["e_fix_lanes"]
                self.assertEqual(e["status"], "attempted")
                self.assertIn("旗 fork の起動 0/2（fork でない: plan-answer-lane-1・plan-answer-lane-2）", e["why"])

    def test_fixer_lanes_serial_or_not_planted_are_not_yes(self):
        """枝の輪が順に走っただけなら attempted。植えなければ no で、fix-fork の理由を添える"""
        self.fixer_run(second=(60, 100))
        e = json.loads(self.run_tool(str(self.root), "--json").stdout)["features"]["e_fix_lanes"]
        self.assertEqual(e["status"], "attempted")
        self.assertIn("枝の輪の同時の最大 1", e["why"])
        shutil.rmtree(self.tmp)
        self.tmp.mkdir()
        self.db.parent.mkdir(parents=True)
        self.fixer_run(planted=0, asks=[])
        got = self.run_tool(str(self.root), "--request", "fix", "--json")
        self.assertEqual(got.returncode, 1)
        e = json.loads(got.stdout)["features"]["e_fix_lanes"]
        self.assertEqual(e["status"], "no")
        self.assertIn("並べる枝が 2 本に満たない（範囲の在る項目 0・枝 0）", e["why"])

    def test_db_mode_reads_launches_dir(self):
        """--db の形は --launches <包みの起動の記録の置き場> で起動の記録を読む（無ければ読まない）"""
        self.fixer_run()
        launches = self.root / "home" / "adapter" / "launches"
        got = self.run_tool("--db", str(self.db), "--run", RUN, "--launches", str(launches), "--request", "fix", "--json")
        self.assertEqual(got.returncode, 0, got.stdout + got.stderr)
        got = self.run_tool("--db", str(self.db), "--run", RUN, "--request", "fix", "--json")
        self.assertEqual(got.returncode, 1)
        self.assertIn("包みの起動の記録が無い", json.loads(got.stdout)["features"]["e_fix_lanes"]["why"])

    def test_fixer_union_counts_as_overlap(self):
        """修正役の締めの行の union（試験のファイルの挿しだけの合わせ）も (b) の yes"""
        make_db(self.db, self.out_root, [])
        make_board(self.board, units={"applied": [1, 2], "conflict": [], "unmerged": [], "shared": ["test_lib.py"],
                                      "union": ["test_lib.py"]})
        f = canary_check.check(RUN, {}, [], self.board)["features"]
        self.assertEqual(f["b_overlap"]["status"], "yes")
        self.assertIn("union ['test_lib.py']", f["b_overlap"]["why"])

    def units_run(self, *, covered=True, parks=0, rules=0, conflict_calls=0, items=None):
        """--request units の形の run: 1 項目 2 単位の案・TDD の輪の状態（先の単位が緑、後の単位は covered_by で閉じた）・
        食い違いの申し出の段の呼び・trace の conflict_parked・conflict_ruled の行・裁定役（節 rule）の起動"""
        items = items if items is not None else [{"route": "tdd", "unit_keys": [U_MEAN, U_INITIALS],
                                                  "allowed_paths": ["calc.py", "textfmt.py", "test_lib.py", "CHANGELOG.md"]}]
        rule = "fixing__rule-loop.rule"
        events = [*node("fixing__tdd-loop.tdd", 10, 60)] + [e for n in range(rules) for e in node(rule, 70 + n * 10, 75 + n * 10)]
        make_db(self.db, self.out_root, events)
        make_board(self.board, items=items, report=FULL_REPORT)
        second = {"route": "tdd", "red": "ok", "green": "ok", "covered_by": [U_MEAN]} if covered else \
            {"route": "tdd", "red": "ok", "green": "", "covered_by": None}
        calls = [{"n": 1, "phase": "route", "ok": True}, {"n": 2, "phase": "test", "unit_key": U_MEAN, "ok": True}]
        calls += [{"n": 3 + n, "phase": "conflict", "unit_key": U_MEAN, "ok": True} for n in range(conflict_calls)]
        write(self.board / "tdd-1" / "state.json", {"phase": "done", "done": True, "calls": calls,
                                                    "units": {U_MEAN: {"route": "tdd", "red": "ok", "green": "ok"},
                                                              U_INITIALS: second}})
        with (self.board / "trace.jsonl").open("a", encoding="utf-8") as f:
            for op, n in (("conflict_parked", parks), ("conflict_ruled", rules)):
                f.writelines(json.dumps({"t": "x", "op": op, "id": f"c{k}"}) + "\n" for k in range(n))
        write(self.root / "home" / "runs" / f"{RUN}.json", {})

    def test_units_closed_by_machine_without_conflict_is_yes(self):
        """(f) 1 項目 2 単位（--request units の狙い。0.2.38）: 後の単位が covered_by で閉じ（一緒に直した先の単位は緑）、
        食い違いの申し出（TDD の輪の段 conflict の呼び・trace の conflict_parked）も裁定（conflict_ruled・節 rule の起動）も
        無ければ yes。--request units の終了コードは (f) だけで決める（1 項目なので (a)〜(c) は通らない形）"""
        self.units_run()
        got = self.run_tool(str(self.root), "--request", "units", "--json")
        self.assertEqual(got.returncode, 0, got.stdout + got.stderr)
        doc = json.loads(got.stdout)
        f = doc["features"]["f_item_units"]
        self.assertEqual(f["status"], "yes")
        self.assertIn(f"閉じた単位 {U_INITIALS}（covered_by {U_MEAN}）", f["why"])
        self.assertEqual(doc["item_units"]["items"], [{"item": 1, "units": 2}])
        self.assertEqual({k: doc["item_units"][k] for k in ("conflict_calls", "conflict_parked", "conflict_ruled", "rule_runs")},
                         {"conflict_calls": 0, "conflict_parked": 0, "conflict_ruled": 0, "rule_runs": 0})
        self.assertEqual(doc["features"]["a_parallel"]["status"], "no")
        self.assertEqual(self.run_tool(str(self.root)).returncode, 1, "既定の canary は (a)〜(c) で決める")
        text = self.run_tool(str(self.root), "--request", "units").stdout
        self.assertIn("(f) 1 つの項目の 2 つの単位: yes", text)

    def test_units_with_conflict_or_rule_are_attempted(self):
        """後の単位を閉じなかった・申し出が在った・裁定役が起きたなら attempted で、数を名指す（run 245042a7 の形: 2 単位とも
        parked・申し出 2・裁定 2）"""
        for name, kw, word in (("閉じない", {"covered": False}, "covered_by で閉じた単位が無い"),
                               ("申し出", {"conflict_calls": 2, "parks": 2}, "申し出 2・conflict_parked 2"),
                               ("裁定", {"rules": 2}, "conflict_ruled 2・裁定役の起動 2")):
            with self.subTest(name):
                shutil.rmtree(self.tmp)
                self.tmp.mkdir()
                self.db.parent.mkdir(parents=True)
                self.units_run(**kw)
                got = self.run_tool(str(self.root), "--request", "units", "--json")
                self.assertEqual(got.returncode, 1, got.stderr)
                f = json.loads(got.stdout)["features"]["f_item_units"]
                self.assertEqual(f["status"], "attempted")
                self.assertIn(word, f["why"])

    def test_units_without_tdd_state_or_two_unit_item_is_no(self):
        """TDD の輪の状態が無ければ no。案に 2 単位以上の項目が無ければ no（狙いの形でない）"""
        make_db(self.db, self.out_root, [])
        make_board(self.board)
        f = canary_check.check(RUN, {}, [], self.board)["features"]["f_item_units"]
        self.assertEqual(f["status"], "no")
        self.assertIn("2 つ以上の単位を持つ項目が無い", f["why"])
        self.db.unlink()
        self.units_run(items=[{"route": "tdd", "unit_keys": [U_MEAN, U_INITIALS]}])
        (self.board / "tdd-1" / "state.json").unlink()
        f = canary_check.check(RUN, {}, [], self.board)["features"]["f_item_units"]
        self.assertEqual(f["status"], "no")
        self.assertIn("TDD の輪の状態が無い", f["why"])

    def test_refusals_exit_two_with_one_line(self):
        make_db(self.db, self.out_root, [])
        cases = {
            "引数なし": (),
            "--db と置き場の両方": ("--db", str(self.db), "--run", RUN, str(self.root)),
            "--db に --run が無い": ("--db", str(self.db)),
            "知らない旗": (str(self.root), RUN, "--nope"),
            "run が無い": ("--db", str(self.db), "--run", "missing"),
            "db が無い": ("--db", str(self.tmp / "none.db"), "--run", RUN),
            "控えが無い": (str(self.root),),
            "盤面が無い": ("--db", str(self.db), "--run", RUN),
            "知らない依頼の形": (str(self.root), "--request", "nope"),
            "置き場の形に --launches": (str(self.root), "--launches", str(self.tmp)),
        }
        for name, args in cases.items():
            with self.subTest(name):
                got = self.run_tool(*args)
                self.assertEqual(got.returncode, 2, got.stdout + got.stderr)
                self.assertEqual(got.stdout, "")
                self.assertEqual(len(got.stderr.strip().splitlines()), 1, got.stderr)
                self.assertTrue(got.stderr.startswith("canary_check.py: "))


if __name__ == "__main__":
    unittest.main()
