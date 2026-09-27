"""script の節の本物の出力と YAML の output_format の約束（run 25 の再発止め）。

Archon は script の節の標準出力を節の output_format に当て、合わなければ節を落とす（additionalProperties: false の型に無い欄が
1 つでも在れば落ちる）。dev/check.sh の模擬実行は script の節を stub で置き換えるので、このずれは見えない。run 25 は
blk-delta の review-accept が entry.take の欄（ready・asking・halted・out_file）をそのまま出し、宣言の型に無くて落ちた。

ここでは tests/scriptline.py が線 darkfactory を YAML のとおりに本物のスクリプトで回し（役と関所だけを見本で置き換える）、
起こした全部の script の節の標準出力を節の output_format に当てる。筋書きは出口の道を分ける:
- full: 全部の役の 1 回目を拒ませ（受け付けの拒否の出口）、TDD の輪（実行器あり・全部 direct）・2 回目の差分の審査を通す
- ci-final-stop: テストの宣言が無い種（CI の任せ先の役 blk-ci）・最後の関所の stop（AI の報告のブロックが走る）
- give-up: 修正案の役が 3 回とも拒まれて諦める（盤面が止まり、残りは飛んで報告だけが走る）
- fix-give-up・unchanged-file: 修正の輪が 3 回とも拒まれる・申告したファイルが変わっていない（run 26）→ assert-changed が
  盤面を止め、run は落ちずに報告まで届く（R50）
- no-fix・policy-stop・stop-flag: 修正の無い周・修正の前の関所の stop・止め札
- <役>-give-up（GIVE_UPS の役: 並行 PR の任せ先・前提の実測・目的・差分の審査・手直し・2 回目の審査）: 役が 3 回とも拒まれる →
  輪は受け付けの done で 3 周目に抜け（max_iterations に当てない）、出口が盤面を止め、run は落ちずに報告まで届く（R50）。
  盤面が止まった後はどの役も起きない（並行 PR の任せ先が諦めた後の前提の実測役も）
網羅: 線と線が include する全部のブロックの script の節（output_format を持つ物）を、(ブロック・スクリプト・output_format) の
組で 1 回は起こす（同じスクリプトと同じ型の節は、役の名だけが違う同じ口——例えば素材集めの P1 の役は判定から入る run の
周では起きないが、prep・accept は同じスクリプトと同じ型で prior-decisions が通る）。受け付けのスクリプトは通る出口と拒む
出口の両方を起こす。
"""
import json
import pathlib
import sys
import tempfile
import unittest

TESTS = pathlib.Path(__file__).resolve().parent
ROOT = TESTS.parent
sys.dont_write_bytecode = True
sys.path.insert(0, str(ROOT / "darkfactory" / "lib"))
sys.path.insert(0, str(ROOT / ".shared" / "core"))
sys.path.insert(0, str(TESTS))

import linekit  # noqa: E402
import scriptline  # noqa: E402
import test_blk_fix_tdd as TT  # noqa: E402
import test_line_a as TL  # noqa: E402
from test_edge import CLEAN_REVIEW, DELTA_FACE  # noqa: E402

# 線に include されていないブロック（線の run では起きない。自分の試験が口の関数を見る）。線に入れたらここから消す
UNWIRED = {
    "blk-spec": "仕様から入る道（flow: spec）はまだ線に配線していない（P1-R2）。test_blk_spec が口の関数を見る",
    "blk-rejudge": "再判定のブロックはまだ線に配線していない。test_blk_rejudge が口の関数を見る",
}


def refix_edit(repo):
    """手直しの役の代わり: 頭の docstring の clamp の行を直した後の振る舞いに書き直す（差分の審査の穴 DELTA_FACE を fixed にする）"""
    p = repo / "stats.py"
    s = p.read_text(encoding="utf-8")
    p.write_text(s.replace("上限を超えたときに lo を返している（正しくは hi）。", "上限を超えたときに hi を返す。"), encoding="utf-8")


REFIX_FIXED = {"handled": [{"key": DELTA_FACE, "handled": "fixed", "files": ["stats.py"],
                            "how": "頭の docstring の clamp の行を直した後の振る舞いに書き直した"}]}
REVIEW2_OK = {"faces": [], "faces_none": "手直しの差分 1 行（頭の docstring）と clamp の本体を読んだ。ずれは無い",
              "checks": [{"key": DELTA_FACE, "closed": True, "why": "頭の docstring が hi を返すと書き、直した後の振る舞いと揃った"}]}
DIRECT = "文書の直しと同じで、先にテストを書けない単位"
TDD_ALL_DIRECT = {"phase": "route", "units": [{"unit_key": TT.MEAN, "route": "direct", "why": DIRECT},
                                              {"unit_key": TT.CLAMP, "route": "direct", "why": DIRECT}]}


def unchanged_file_fix():
    """修正役が変えていないファイル（test_stats.py）も申告した返答（受け付けは通り、assert-changed が通らない。run 26 の形）"""
    from test_edge import fix_reply
    r = fix_reply(faces=True)
    r["changes"][0]["files"] = [*r["changes"][0]["files"], "test_stats.py"]
    return r


# 3 回とも拒ませる役（<ブロック>/<節>）→ 筋書きの名。2 回目の手直し（refix2）は 2 回目の審査が穴を残す周でしか起きないので、
# 輪の形は test_role_give_up が、出口の諦めの腕は refix.collect_refix の同じ式（手直し 1・審査 2 と同じ行）が受け持つ
GIVE_UPS = {"blk-pr/pr-check": "pr-give-up", "blk-premises/premises": "premises-give-up",
            "blk-purpose/purpose": "purpose-give-up", "blk-delta/review": "review-give-up",
            "blk-refix/refix": "refix-give-up", "blk-refix/review2": "review2-give-up"}


def ai_keys():
    """線が include するブロックの役の節の鍵（<ブロック>/<節>）"""
    return {f"{b}/{n['id']}" for b in scriptline.wired_blocks() for n, _ in scriptline.walk(scriptline.flow(b)["nodes"])
            if any(k in n for k in scriptline.AI_KEYS)}


def scenarios(tmp: pathlib.Path) -> dict:
    """筋書きの名 → ScriptLine の引数"""
    suite = tmp / "suite.py"
    suite.write_text(TT.SUITE, encoding="utf-8")
    edits = {"fix": TL.fix_tree}
    full = {**TL.replies(), "refix": REFIX_FIXED, "review2": REVIEW2_OK, "tdd": TDD_ALL_DIRECT}
    nofix = {**TL.replies(review=CLEAN_REVIEW), "judge": linekit.reply("judge_no_fix")}
    return {
        "full": dict(replies=full, edits={**edits, "refix": refix_edit}, bad_first=ai_keys(),
                     inputs={"tdd_suite": str(suite)}, gates={"policy-gate": {"decision": "continue", "text": "$x `y` \"z\""}}),
        "ci-final-stop": dict(replies={**TL.replies(), "ci": linekit.reply("ci_found")}, edits=edits, declared=False,
                              bad_first={"blk-ci/ci", "blk-report/report-items", "blk-report/report-cold", "blk-report/report-write"},
                              gates={"final-gate": {"decision": "stop", "text": "差分を人が読み直す"}}),
        "give-up": dict(replies={**TL.replies(), "plan": lambda n: {}}, edits=edits),
        "fix-give-up": dict(replies={**TL.replies(), "fix": lambda n: {}}, edits=edits),
        "unchanged-file": dict(replies={**TL.replies(), "fix": unchanged_file_fix()}, edits=edits),
        "no-fix": dict(replies=nofix, edits={}),
        "policy-stop": dict(replies=TL.replies(), edits=edits, gates={"policy-gate": {"decision": "stop", "text": "範囲が広い"}}),
        "stop-flag": dict(replies=TL.replies(), edits=edits, stop_at="h-review"),
        **{name: dict(replies={**TL.replies(), "refix": REFIX_FIXED, "review2": REVIEW2_OK, key: lambda n: {}},
                      edits={**edits, "refix": refix_edit})
           for key, name in GIVE_UPS.items()},
    }


OUTCOMES = {"fix-give-up": "stopped_by_line", "unchanged-file": "stopped_by_line", "full": "fixed", "ci-final-stop": "stopped_by_human", "give-up": "stopped_by_line", "no-fix": "no_fix_needed",
            "policy-stop": "stopped_by_human", "stop-flag": "stopped_by_request",
            **{name: "stopped_by_line" for name in GIVE_UPS.values()}}


def signature(block, node) -> tuple:
    n = next(m for m, _ in scriptline.walk(scriptline.flow(block)["nodes"]) if m["id"] == node)
    return block, n["script"], json.dumps(n["output_format"], sort_keys=True, ensure_ascii=False)


class ScriptContractCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory(dir=linekit.work_home())
        base = pathlib.Path(cls._tmp.name)
        cls.got = {}
        for name, kw in scenarios(base).items():
            cls.got[name] = scriptline.ScriptLine(base / name, **kw).run()

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def test_every_script_stdout_matches_output_format(self):
        """全部の筋書きで、起こした script の節の標準出力が節の output_format を通る（型に無い欄・欠けた必須の欄・型の違い）"""
        for name, got in self.got.items():
            with self.subTest(name):
                bad = [f"{r['block']}/{r['node']}: {r['errors']} 出力の欄 {sorted(r['out'])}" for r in got["runs"] if r["errors"]]
                self.assertEqual(bad, [])

    def test_scenarios_complete_with_expected_outcome(self):
        """どの筋書きも節が落ちずに出口まで届き（終了コード 0 と JSON・輪は until_bash で抜ける）、結末が筋書きどおり"""
        for name, got in self.got.items():
            with self.subTest(name):
                self.assertTrue(got["completed"], got["failure"])
                self.assertEqual(got["out"]["result"]["outcome"], OUTCOMES[name])

    def test_every_script_signature_ran(self):
        """線と線が include する全部のブロックの script の節（output_format を持つ物）を、(ブロック・スクリプト・型) の組で
        1 回は起こした。線に無いブロックは UNWIRED に理由つきで名指す"""
        blocks = sorted({p.parent.name for p in ROOT.glob("blk-*/blk-*.yaml") if p.stem == p.parent.name})
        self.assertEqual(set(blocks) - set(scriptline.wired_blocks()), set(UNWIRED))
        want = {signature(b, n) for b in scriptline.wired_blocks() + [scriptline.LINE] for n in scriptline.script_nodes(b)}
        ran = {signature(r["block"], r["node"]) for got in self.got.values() for r in got["runs"]
               if "output_format" in next(m for m, _ in scriptline.walk(scriptline.flow(r["block"])["nodes"])
                                          if m["id"] == r["node"])}
        missing = sorted(f"{b}/{s}" for b, s, _ in want - ran)
        self.assertEqual(missing, [])

    def test_role_gives_up_after_three_rejections(self):
        """3 回とも拒まれた役は 3 回だけ起き（輪は done で抜ける）、盤面が止まった後はどの役も起きない（報告の役を除く）"""
        ai = {k for k in ai_keys() if not k.startswith("blk-report/")}
        for key, name in GIVE_UPS.items():
            with self.subTest(name):
                trail = self.got[name]["trail"]
                self.assertEqual(trail.count(key), 3, trail)
                after = trail[len(trail) - trail[::-1].index(key):]
                self.assertEqual([t for t in after if t in ai], [])

    def test_accepts_take_both_exits(self):
        """役の返答の受け付けのスクリプト（YAML の with: に reply を持つ節）は、通る出口と拒む出口の両方を起こした"""
        seen = {}
        for got in self.got.values():
            for r in got["runs"]:
                n = next(m for m, _ in scriptline.walk(scriptline.flow(r["block"])["nodes"]) if m["id"] == r["node"])
                if "reply" in (n.get("with") or {}) and r["out"] is not None:
                    seen.setdefault((r["block"], n["script"]), set()).add(r["out"].get("ok"))
        self.assertTrue(seen)
        for key, oks in sorted(seen.items()):
            with self.subTest("/".join(key)):
                self.assertEqual(oks, {True, False})


if __name__ == "__main__":
    unittest.main()
