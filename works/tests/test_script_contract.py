"""script の節の本物の出力と YAML の output_format の約束（run 25 の再発止め）。

Archon は script の節の標準出力を節の output_format に当て、合わなければ節を落とす（additionalProperties: false の型に無い欄が
1 つでも在れば落ちる）。dev/check.sh の模擬実行は script の節を stub で置き換えるので、このずれは見えない。run 25 は
blk-delta の review-accept が entry.take の欄（ready・asking・halted・out_file）をそのまま出し、宣言の型に無くて落ちた。

ここでは tests/scriptline.py が線 darkfactory を YAML のとおりに本物のスクリプトで回し（役と関所だけを見本で置き換える）、
起こした全部の script の節の標準出力を節の output_format に当てる。筋書きは出口の道を分ける:
- full: 全部の役の 1 回目を拒ませ（受け付けの拒否の出口）、TDD の輪（実行器あり・全部 direct）・2 回目の差分の審査を通す
- ci-final-stop: テストの宣言が無い種（CI の任せ先の役 blk-ci）・最後の関所の stop（AI の報告のブロックが走る）
- give-up: 修正案の役が 3 回とも拒まれて諦める（盤面が止まり、残りは飛んで報告だけが走る）
- material-give-up: 素材集めの役が 3 回とも拒まれて諦める（run 30）。判定の支度が止まった盤面を見て判定役を起こさず、報告まで届く
- fix-give-up・unchanged-file: 修正の輪が 3 回とも拒まれる・申告したファイルが変わっていない（run 26）→ assert-changed が
  盤面を止め、run は落ちずに報告まで届く（R50）
- no-fix・policy-stop・stop-flag: 修正の無い周・修正の前の関所の stop・止め札
- plan-converge（依頼 231）: 事前審査が block を挙げ、壁打ちの外の輪が直しの役（修正案の役の会話の続き）を起こし、直した案を
  2 度目の事前審査が同じ穴を suggest に下げて通す（輪の中の輪・converge-check の done で抜ける）→ 報告 fixed
- conflict: 修正役が食い違いを申し出て parked → 裁定の輪（1 回目は拒む）→ fix_code_as → 2 回目の修正役が全部を直す
- rejudge（run 28）: 修正役が判定に異議 → 再審の輪（1 回目は拒む。判定役の会話の続き）→ 差分の審査 → 手直し → 2 回目の審査 →
  2 回目の手直し → 最後のテスト（ラインの test_cmd）→ 独立の目 → 最後の関所 → 報告 fixed
- rejudge-no-session: 同じ異議で判定役の会話が無い → h-rejudge が盤面を止め、後ろは飛んで報告は stopped_by_line
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


def clamp_only(repo):
    """修正役の 1 回目の代わり: clamp だけを直す（mean は食い違いとして申し出る）"""
    p = repo / "stats.py"
    p.write_text(p.read_text(encoding="utf-8").replace("    if x > hi:\n        return lo", "    if x > hi:\n        return hi"),
                 encoding="utf-8")


def conflict_fix():
    """修正役の 1 回目: clamp の行だけと、mean の食い違いの申し出（名指しは種の stats.py:9・test_stats.py:9）"""
    from test_edge import fix_reply
    r = fix_reply(faces=True)
    r["changes"] = [c for c in r["changes"] if c["unit_key"] == TT.CLAMP]
    r["interactions"] = []
    r["conflicts"] = [{"unit_key": TT.MEAN, "between": ["stats.py:9", "test_stats.py:9"],
                       "why_both_cannot_hold": "テストは算術平均を期待し、今の式は分母が 1 少ない——どちらかを曲げないと緑にならない",
                       "which_is_right": "test", "kind": "unnamed_test_broke"}]
    return r


# 修正案の役の返答の works の欄（route・tests・rewrite_tests・refactor・allowed_paths・out_of_scope。planmarks）。線を本物のスクリプトで回すと、修正案は
# blk-plan の受け付け（planmarks.gaps）を通り、欄が欠ければ 3 回とも拒まれて盤面が止まる（by works:plan）。test_edge.plan_reply は
# 受け付けが欄を外した後の形（entry.take を直に呼ぶ linekit の道の物）なので、ここで欄を足す。種の test_stats.py は 3 件のうち
# 2 件が今の 2 つのバグで赤なので、受け入れのテストを先に足さず direct で直す（TDD の輪の返答 TDD_ALL_DIRECT とも揃う）
PLAN_FIELDS = {"route": "direct",
               "route_why": "種の test_stats.py の 3 件のうち 2 件が今の 2 つのバグで赤になり、直した後の振る舞いを既に確かめている",
               "tests": [], "rewrite_tests": [], "refactor": {"declared": False, "why": ""},
               "allowed_paths": ["stats.py", "test_stats.py"], "out_of_scope": []}


# 修正案の works の欄を控えた run の 1 回目の差分の審査の準拠（deltamarks。承認済みの項目と照らし、落ちた行は無い）
REVIEW_COMPLIANCE = {"verdict": "pass", "items": [],
                     "read": "承認済みの修正案の項目 1 の approach・allowed_paths と差分の stats.py を読み、足りない物も範囲の外の物も無い"}


def line_replies(**kw) -> dict:
    """TL.replies の修正案を、役そのものの返答（項目に works の欄 PLAN_FIELDS を足した物）に替え、1 回目の差分の審査の準拠を
    控えの在る run の pass（REVIEW_COMPLIANCE）に替えた返答の組（品質は TL.replies の物のまま: 穴が在れば fail）。事前審査の
    穴は severity suggest にする（block の穴は壁打ちで修正案の役へ返るので、1 往復で関所まで進む筋書きはこの形。kind regression
    の穴は suggest でも関所で聞く。壁打ちの往復は筋書き plan-converge）"""
    r = TL.replies(**kw)
    r["plan"] = {"plan": [{**row, **PLAN_FIELDS} for row in r["plan"]["plan"]]}
    r["plan-review"] = {**r["plan-review"], "faces": [{**f, "severity": "suggest"} for f in r["plan-review"]["faces"]]}
    r["review"] = {**r["review"], "compliance": REVIEW_COMPLIANCE}
    return r


# 事前審査の壁打ち（依頼 231）: 1 往復目の審査は regression の穴を block で挙げ、直しの役（修正案の役の会話の続き）が直した案を
# 2 往復目の審査が読んで、同じ key の穴を suggest に下げる（block が消えて直しへ進む。穴は関所で聞き、修正役が塞ぐのは
# ほかの筋書きと同じ）
CONVERGE_BLOCK = linekit.reply("plan_review_regression")
CONVERGE_KEY = CONVERGE_BLOCK["faces"][0]["key"]


def converge_review(n: int) -> dict:
    return CONVERGE_BLOCK if n == 1 else line_replies()["plan-review"]


def converge_revise() -> dict:
    return {**line_replies()["plan"], "block_answers": [{"key": CONVERGE_KEY, "handled": "fixed",
                                                         "how": "clamp の上限の枝を hi に直すと決めた理由を approach に書き足した"}]}


PR_AWAITING = {"material": {"status": "awaiting_human", "reason": "origin が GitHub でないローカルの bare リポジトリで、PR の一覧を読めない"},
               "repo": "", "listed": 0, "truncated": False, "conflicts": [], "excluded": []}

RULING_CODE = {"rulings": [{"id": "c1-1", "decision": "fix_code_as", "text": "依頼とテストが正しい。分母を len(xs) に直せ",
                            "limits": ["stats.py:9"]}]}


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
    full = {**line_replies(), "refix": REFIX_FIXED, "review2": REVIEW2_OK, "tdd": TDD_ALL_DIRECT}
    nofix = {**line_replies(review=CLEAN_REVIEW), "judge": linekit.reply("judge_no_fix")}
    judged = linekit.reply("judge_ok")["units"]
    objection = {**line_replies(), "fix": {**line_replies()["fix"], "rejudge_requested": TL.OBJECTION},
                 "refix": REFIX_FIXED, "review2": TL.REVIEW2_FACES, "refix2": TL.REFIX2_DECLARED,
                 "rejudge": {"verdict": "退ける", "new_facts": "stats.py の clamp の上限の枝を読み、hi を返すのが定義だと確かめた",
                             "units": [{k: u[k] for k in ("key", "label", "disposition", "reason") if k in u} for u in judged]}}
    return {
        "full": dict(replies=full, edits={**edits, "refix": refix_edit}, bad_first=ai_keys(),
                     inputs={"tdd_suite": str(suite)}, gates={"policy-gate": {"decision": "continue", "text": "$x `y` \"z\""}}),
        "ci-final-stop": dict(replies={**line_replies(), "ci": linekit.reply("ci_found")}, edits=edits, declared=False,
                              bad_first={"blk-ci/ci", "blk-report/report-items", "blk-report/report-cold", "blk-report/report-write"},
                              gates={"final-gate": {"decision": "stop", "text": "差分を人が読み直す"}}),
        "give-up": dict(replies={**line_replies(), "plan": lambda n: {}}, edits=edits),
        # run 30: 素材集めの役が 3 回とも拒まれて諦め、素材集めのブロックが盤面を止める。同じ境の節（h-mat）の後ろの判定の
        # ブロックは支度 judge-brief が止まった盤面を見て判定役を起こさず（go: false）、報告と出口まで落ちずに届く
        "material-give-up": dict(replies={**line_replies(), "prior-decisions": lambda n: {}}, edits=edits),
        # 同じ止めで、並行 PR の素材が awaiting_human（run 30 の姿）: 判定の前に止めた周の記録は検証器を通らない（awaiting を
        # 問いの台帳に載せる判定役が走っていない）。本線と同じく報告の節（AI の報告）は出ず、機械の報告がその理由を言う
        "material-give-up-awaiting": dict(replies={**line_replies(), "prior-decisions": lambda n: {}, "pr-check": PR_AWAITING},
                                          edits=edits),
        "fix-give-up": dict(replies={**line_replies(), "fix": lambda n: {}}, edits=edits),
        "unchanged-file": dict(replies={**line_replies(), "fix": unchanged_file_fix()}, edits=edits),
        "no-fix": dict(replies=nofix, edits={}),
        "plan-converge": dict(replies={**line_replies(), "plan-review": converge_review,
                                       "plan-revise": converge_revise(), "refix": REFIX_FIXED, "review2": REVIEW2_OK},
                              edits={**edits, "refix": refix_edit}),
        "policy-stop": dict(replies=line_replies(), edits=edits, gates={"policy-gate": {"decision": "stop", "text": "範囲が広い"}}),
        "stop-flag": dict(replies=line_replies(), edits=edits, stop_at="h-review"),
        # 食い違いの申し出: 1 回目の修正役が mean を申し出て parked → 裁定役（1 回目は拒む）が fix_code_as → 2 回目の修正役が全部を直す
        "conflict": dict(replies={**line_replies(), "fix": conflict_fix(), "rule": RULING_CODE, "fix-ruled": line_replies()["fix"]},
                         edits={"fix": clamp_only, "fix-ruled": TL.fix_tree}, bad_first={"blk-fix/rule"}),
        # run 28: 修正役の異議の後に再審を回さないと p2.rejudge が待ったままで p4.ci が出ず、最後のテストが走らなかった
        "rejudge": dict(replies=objection, edits={**edits, "refix": refix_edit}, inputs={"test_cmd": TL.TEST_CMD},
                        bad_first={"blk-rejudge/rejudge"}, sessions=True),
        "rejudge-no-session": dict(replies=objection, edits={**edits, "refix": refix_edit}, inputs={"test_cmd": TL.TEST_CMD}),
        **{name: dict(replies={**line_replies(), "refix": REFIX_FIXED, "review2": REVIEW2_OK, key: lambda n: {}},
                      edits={**edits, "refix": refix_edit})
           for key, name in GIVE_UPS.items()},
    }


OUTCOMES = {"plan-converge": "fixed", "material-give-up": "stopped_by_line", "material-give-up-awaiting": "stopped_by_line", "conflict": "fixed", "fix-give-up": "stopped_by_line", "unchanged-file": "stopped_by_line", "full": "fixed", "ci-final-stop": "stopped_by_human", "give-up": "stopped_by_line", "no-fix": "no_fix_needed",
            "policy-stop": "stopped_by_human", "stop-flag": "stopped_by_request", "rejudge": "fixed",
            "rejudge-no-session": "stopped_by_line",
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

    def test_stop_before_judge_reaches_report(self):
        """素材集めが諦めて盤面を止めた（run 30）: 判定役は起きず（judge-brief が go 偽）、境の節と報告と出口が走る。
        止めた周の記録が検証器を通らない時は、本線と同じく報告の節を出さず、機械の報告の冒頭 3 がその理由を言う"""
        for name in ("material-give-up", "material-give-up-awaiting"):
            with self.subTest(name):
                got = self.got[name]
                brief = next(r for r in got["runs"] if r["node"] == "judge-brief")
                self.assertIs(brief["out"]["go"], False)
                self.assertNotIn("blk-judge/judge", got["trail"])
                self.assertIn("darkfactory/report", got["trail"])
                self.assertEqual(got["trail"][-1], "darkfactory/result")
        self.assertIs(self.got["material-give-up"]["out"]["report"]["ai_report_go"], True)
        rep = self.got["material-give-up-awaiting"]["out"]["report"]
        self.assertIs(rep["ai_report_go"], False)
        text = pathlib.Path(rep["report_file"]).read_text(encoding="utf-8")
        self.assertIn("報告の節は出ない（本線の止めと同じ）: 止めた周の記録が検証器を通らない", text)
        self.assertIn("素材 'parallel_pr' が awaiting_human なのに問いの台帳に無い", text)

    def test_objection_reaches_final_tests(self):
        """run 28 の形（修正役の異議 → 再審 → 手直し 2 回）を本物のスクリプトで: h-tests が go 真で最後のテストがラインの
        test_cmd で走り、周が締まって独立の目と報告が回る（record_invalid・「最後のテスト: 走っていない」にならない）。
        判定役の会話が無ければ h-rejudge が止め、再審・最後のテストは飛んで stopped_by_line"""
        got = self.got["rejudge"]
        out = got["out"]
        self.assertIs(out["h-rejudge"]["go"], True)
        self.assertIs(out["h-tests"]["go"], True)
        for key in ("blk-rejudge/collect", "blk-refix/refix2-accept", "blk-tests/run", "blk-eyes/eyes-collect",
                    "darkfactory/report"):
            self.assertIn(key, got["trail"])
        self.assertEqual(out["start"]["test_cmd"], TL.TEST_CMD)
        self.assertIs(out["report"]["tests_green"], True)
        self.assertNotIn(TL.NOT_RUN, pathlib.Path(out["report"]["report_file"]).read_text(encoding="utf-8"))
        stopped = self.got["rejudge-no-session"]
        self.assertIs(stopped["out"]["h-rejudge"]["stop"], True)
        for key in ("blk-rejudge/collect", "blk-tests/run", "blk-eyes/eyes-collect"):
            self.assertNotIn(key, stopped["trail"])

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

    def test_plan_converge_loops_back_to_revise(self):
        """事前審査の壁打ち（依頼 231）を本物のスクリプトで: 1 往復目の block で converge-check が done 偽を返して外の輪が回り、
        2 周目に直しの役（plan-revise）が 1 度起き、事前審査が 2 度目に同じ穴を suggest に下げて done 真で抜ける。
        ほかの筋書きは 1 周目で抜け、直しの役は起きない"""
        got = self.got["plan-converge"]
        checks = [r["out"] for r in got["runs"] if r["node"] == "converge-check"]
        self.assertEqual([(c["done"], c["outcome"]) for c in checks], [(False, "again"), (True, "clean")])
        self.assertEqual(got["trail"].count("blk-plan/plan-revise"), 1)
        self.assertEqual(got["trail"].count("blk-plan/plan-review"), 2)
        snaps = [r["out"]["go"] for r in got["runs"] if r["node"] == "plan-revise-snap"]
        self.assertEqual(snaps, [False, True])
        for name, other in self.got.items():
            if name != "plan-converge":
                with self.subTest(name):
                    self.assertNotIn("blk-plan/plan-revise", other["trail"])

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
