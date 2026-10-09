"""blk-refix（手直し 2 往復）の検査と、blk-delta・blk-refix が共に使う盤面の組み立て（DeltaBoardCase）。

盤面は linekit の種（dev/target-seed/ の stats.py に 2 つのバグ）で start し、前提・並行 PR・判定（judge_ok）・修正案・
事前審査（穴 1 件: clamp の docstring）・修正（作業ツリーの stats.py を本当に直し、p3.fix を受ける）まで entry.take で進める。
その後の差分を切る・義務を組むのは盤面の機械の節（写しの RL の fix_delta・delta_owed）で、ここは refix の口で役の返答を渡す。
役の返答の見本は tests/replies/fix2_delta_*.json。YAML（blk-refix.yaml）は Task 17 で書くので、ここは口・スクリプト・指示書を見る。
"""
import json
import os
import pathlib
import re
import subprocess
import sys
import unittest
from unittest import mock

import yaml

TESTS = pathlib.Path(__file__).resolve().parent
ROOT = TESTS.parent
CORE = ROOT / ".shared" / "core"
sys.dont_write_bytecode = True
sys.path.insert(0, str(CORE))
sys.path.insert(0, str(TESTS))

import accept  # noqa: E402
from board import BoardGap, rules_module  # noqa: E402
import entry  # noqa: E402
import linekit  # noqa: E402
import node_marker  # noqa: E402
import planmarks  # noqa: E402
import refix  # noqa: E402
import rulebook  # noqa: E402
import seat  # noqa: E402
import test_entry as TE  # noqa: E402

K1 = "stats.py mean: 分母が len(xs) - 1 になっている"
K2 = "stats.py clamp: 上限を超えた値に lo を返す"
PR_KEY = "stats.py clamp: docstring が上限の枝の約束を書いていない"   # 事前審査の穴（修正が absorbed と答える）
F1 = "stats.py clamp: docstring が下限の枝の約束を書いていない"       # 差分の審査の穴（fix2_delta_review_faces）
F2 = "stats.py clamp: docstring が境の値の扱いを書いていない"         # 2 回目の審査の穴（fix2_delta_review2_faces）
FIXED_DOC = '    """上限を超えた値は hi を返す"""\n'
REFIXED_DOC = '    """下限を下回った値は lo を、上限を超えた値は hi を返す"""\n'
REFIX_DIR = ROOT / "blk-refix"
DELTA_DIR = ROOT / "blk-delta"
# blk-refix の中の輪の役と受け付け（輪の中の id は全部の include をまたいで一意。台帳 R19）
LOOPS = {"refix-loop": ("refix", "refix-accept"), "review2-loop": ("review2", "review2-accept"),
         "refix2-loop": ("refix2", "refix2-accept")}


def plan_reply() -> dict:
    return {"plan": [
        {"unit_keys": [K1], "approach": "mean の分母を len(xs) に直す（算術平均の定義どおり）", "adds": [], "removes": [],
         "shrink_first": "足す物は無い。分母の式を 1 か所直すだけで足りる", "narrows": []},
        {"unit_keys": [K2], "approach": "clamp の上限の枝の戻り値を hi に直す（numpy.clip と同じ）", "adds": [], "removes": [],
         "shrink_first": "足す物は無い。戻り値の 1 語を直すだけで足りる", "narrows": []}]}


def plan_review_reply() -> dict:
    return {"faces": [{"key": PR_KEY, "unit_keys": [K2], "kind": "contract_drift", "where": "stats.py clamp",
                       "why": "上限の枝を直しても docstring が約束を書かないので読む側が古い想定のまま残る", "severity": "suggest"}],
            "shrink": [], "reason": "2 つの案を読み、足す物が無いことと、docstring のずれを 1 件見た"}


def one_item_plan_reply() -> dict:
    """mean と clamp の 2 単位を 1 項目に載せた修正案（項目の単位の一部だけが裁定で外れる盤面の材料）"""
    return {"plan": [
        {"unit_keys": [K1, K2], "approach": "mean の分母を len(xs) に、clamp の上限の枝の戻り値を hi に直す", "adds": [],
         "removes": [], "shrink_first": "足す物は無い。式と戻り値を 1 か所ずつ直すだけで足りる", "narrows": []}]}


def _change(key, site, remaining=None) -> dict:
    c = {"unit_key": key, "what": "式を定義どおりに直した", "files": ["stats.py"],
         "closure": {"mechanism": "式の取り違え", "fix_mechanism": "式を定義どおりに", "verified_how": "退行を注入して赤→戻して緑",
                     "sites": [{"site": site, "red_seen": True}]},
         "precedent": {"verdict": "adopt", "reason": "判定者の先行例を採った", "from_judge_row": True},
         "root_or_symptom": {"kind": "root", "why": "式そのものを直した"},
         "bypass_tried": "修正を残したまま空でない列と境の値を通した——どれも期待どおり",
         "breaks": {"how": "grep -n 'mean(' *.py", "result": "呼び元は test_stats.py だけで緑"}}
    if remaining:
        c["coverage"] = {"remaining": remaining}
    return c


def fix_reply() -> dict:
    """種の stats.py の 2 つの直し（apply_fix）に合う p3.fix の返答（0.21.0 の型。事前審査の穴に absorbed で答える）"""
    return {"changes": [_change(K1, "stats.py:mean"),
                        _change(K2, "stats.py:clamp", remaining="残る return lo は下限の枝で、欠陥でない（正しい戻り値）")],
            "not_done": [], "interactions": [{"surface": "stats.py", "checked": "mean と clamp は別の関数で互いを呼ばない。順序で結果は変わらない"}],
            "fix_closure": {"status": "clean", "checked": "退行を注入して赤→戻して緑"}, "mechanism_changed": False,
            "premise_drift": False, "gates_changed": False, "seams_changed": False, "security_surface_changed": False,
            "path_changed": False, "wrote_refs": [],
            "plan_faces": [{"key": PR_KEY, "handled": "absorbed", "how": "clamp に上限を超えた値は hi を返すと docstring を書いた"}]}


def apply_fix(repo: pathlib.Path) -> None:
    """修正役の代わり: 種の 2 つのバグを直し、clamp に docstring を足す"""
    p = repo / "stats.py"
    s = p.read_text(encoding="utf-8").replace("(len(xs) - 1)", "len(xs)")
    s = s.replace("    if x > hi:\n        return lo", "    if x > hi:\n        return hi")
    s = s.replace("def clamp(x, lo, hi):\n", "def clamp(x, lo, hi):\n" + FIXED_DOC)
    p.write_text(s, encoding="utf-8")


def apply_refix(repo: pathlib.Path) -> None:
    """手直しの役の代わり: clamp の docstring の 1 行だけを書き直す"""
    p = repo / "stats.py"
    p.write_text(p.read_text(encoding="utf-8").replace(FIXED_DOC, REFIXED_DOC), encoding="utf-8")


def load_refixrules():
    """手直しの役の組み立て（blk-refix/lib/refixrules.py）"""
    if str(REFIX_DIR / "lib") not in sys.path:
        sys.path.insert(0, str(REFIX_DIR / "lib"))
    import refixrules
    return refixrules


def workflow_nodes(path: pathlib.Path):
    """YAML の全部の節（loop_group の中も）を (id, 輪の中か) で"""
    def walk(nodes, inner):
        for n in nodes or []:
            yield n.get("id"), inner
            yield from walk((n.get("loop_group") or {}).get("nodes"), True)
    return list(walk(yaml.safe_load(path.read_text(encoding="utf-8")).get("nodes"), False))


class DeltaBoardCase(TE.TakeCaseBase):
    """差分の審査の前後まで進めた盤面（置き場は self.art / board。$ARTIFACTS_DIR の形）"""

    def fixed(self, *, before_fix=None, plan=None):
        """p3.fix まで受けた盤面（ready に p3.delta_review）。before_fix(repo) は修正の返答を渡す前に作業ツリーへ当てる。plan は
        修正案の返答（無ければ plan_reply）"""
        repo, _ = self.judged()
        for nid, reply in (("p2.fix_plan", plan or plan_reply()), ("p2.plan_review", plan_review_reply())):
            TE.launch(self.board, nid)
            got = entry.take(self.board, nid, reply, repo)
            self.assertTrue(got["ok"], got)
        apply_fix(repo)
        if before_fix:
            before_fix(repo)
        TE.launch(self.board, "p3.fix")
        got = entry.take(self.board, "p3.fix", fix_reply(), repo)
        self.assertTrue(got["ok"], got)
        self.assertIn("p3.delta_review", got["ready"])
        return repo

    def reviewed(self, name="fix2_delta_review_faces", **kw):
        """1 回目の差分の審査（name の見本）まで受けた盤面"""
        repo = self.fixed(**kw)
        self.assertTrue(refix.cut(self.board, 1, repo)["ok"])
        got = refix.accept_review(linekit.reply(name), self.board, "", repo, n=1)
        self.assertTrue(got["ok"], got)
        return repo, got

    def refixed(self, name="fix2_delta_fix_ok", *, edit=True):
        """1 回目の手直し（name の見本）まで受けた盤面。edit なら手直しの代わりに docstring の 1 行を書き直す"""
        repo, _ = self.reviewed()
        self.assertTrue(refix.prep_fix(self.board, 1, repo)["ok"])
        if edit:
            apply_refix(repo)
        got = refix.accept_fix(linekit.reply(name), self.board, "", repo, n=1)
        self.assertTrue(got["ok"], got)
        return repo, got

    def plan_fields(self, scoped, keys=(K1, K2)):
        """盤面に修正案の欄の控えを置く（keys の 1 つごとに 1 行。scoped が偽なら 217 番の形: 範囲の欄 allowed_paths・
        out_of_scope が無い）"""
        rows = []
        for key in keys:
            row = {"route": "direct", "route_why": "見本。先にテストを書かない理由", "tests": [], "rewrite_tests": [],
                   "refactor": {"declared": False, "why": ""}, "unit_keys": [key]}
            if scoped:
                row.update(allowed_paths=["stats.py"], out_of_scope=[])
            rows.append(row)
        planmarks.save(self.board, entry.open_board(self.board).round, rows)

    def run_script(self, blk, name, repo, **inputs):
        env = {k: v for k, v in os.environ.items() if not k.startswith("INPUTS_")}
        env.update({f"INPUTS_{k.upper()}": v for k, v in inputs.items()})
        env.update({"ARTIFACTS_DIR": str(self.art), "PYTHONDONTWRITEBYTECODE": "1"})
        env = {k: v for k, v in env.items() if v is not None}
        return subprocess.run([sys.executable, str(ROOT / blk / "scripts" / f"{name}.py")], cwd=str(repo), env=env,
                              capture_output=True, text=True, encoding="utf-8", stdin=subprocess.DEVNULL)


# ---------------------------------------------------------------- 盤面の上の往復
class RefixCase(DeltaBoardCase):
    def test_refix_answers_every_owed_key(self):
        """fix2_delta_fix_ok（義務 2 件に fixed）→ ok。route の review2 は fixed が在るので True、owed は 2"""
        repo, _ = self.reviewed()
        before = refix.route(self.board)
        self.assertEqual((before["owed"], before["review2"], before["refix2"]), (2, False, False))
        got = refix.prep_fix(self.board, 1, repo)
        self.assertEqual((got["ok"], got["owed"]), (True, 2))
        brief = json.loads(pathlib.Path(got["brief_file"]).read_text(encoding="utf-8"))
        self.assertEqual({r["key"] for r in brief["owed"]}, {F1, PR_KEY})
        self.assertEqual(brief["diff_file"], entry.open_board(self.board).loop_state["fix_delta"]["file"])
        apply_refix(repo)
        got = refix.accept_fix(linekit.reply("fix2_delta_fix_ok"), self.board, "", repo, n=1)
        self.assertTrue(got["ok"], got)
        self.assertIn("p3.delta_review2", got["ready"])
        r = refix.route(self.board)
        self.assertEqual((r["review2"], r["refix2"], r["owed"], r["owed2"]), (True, False, 2, 0))

    def test_compliance_fail_reaches_refix_brief(self):
        """準拠の外れを穴 F1 に結んだ審査 → 義務に F1、手直しの材料に plan_items と準拠の行（face_key F1）"""
        repo = self.fixed()
        self.plan_fields(scoped=True)
        self.assertTrue(refix.cut(self.board, 1, repo)["ok"])
        reply = linekit.reply("fix2_delta_review_faces")
        reply["compliance"] = {"verdict": "fail", "read": "修正案の項目 1 と差分の stats.py を読み、項目と差分を照らした",
                               "items": [{"item": 1, "kind": "misunderstood", "face_key": F1,
                                          "why": "brief は docstring も直すと書くが、差分は式だけを直した"}]}
        reply["quality"] = {"verdict": "pass", "why": "準拠に結ばれていない穴は無く、テストの形の問題も見当たらない"}
        got = refix.accept_review(reply, self.board, "", repo, n=1)
        self.assertTrue(got["ok"], got)
        brief = json.loads(pathlib.Path(refix.prep_fix(self.board, 1, repo)["brief_file"]).read_text(encoding="utf-8"))
        self.assertIn(F1, {r["key"] for r in brief["owed"]})
        self.assertEqual([r["face_key"] for r in brief["compliance"]], [F1])
        self.assertEqual([it["item"] for it in brief["plan_items"]], [1, 2])
        self.assertIn("項目 1", {x["key"]: x["branches"] for x in brief["ties"]}.get(F1) or [])   # 準拠の行が結ぶ枝の名札

    def test_broken_plan_fields_halt_at_refix_prep(self):
        """審査の後に修正案の欄の控えが凍結の印と食い違う → 手直しの支度が控えを名指す BoardGap で、手直しの段の印で盤面を止める"""
        repo = self.fixed()
        self.plan_fields(scoped=False)   # 範囲の欄の無い控え: 審査は not_applicable で通る
        self.assertTrue(refix.cut(self.board, 1, repo)["ok"])
        self.assertTrue(refix.accept_review(linekit.reply("fix2_delta_review_faces"), self.board, "", repo, n=1)["ok"])
        (self.board / planmarks.FIELDS_FILE).write_text("{}", encoding="utf-8")
        with self.assertRaises(BoardGap) as cm:
            refix.prep_fix(self.board, 1, repo)
        self.assertIn(planmarks.FIELDS_FILE, str(cm.exception))
        self.assertEqual(entry.open_board(self.board, allow_halted=True).state["stop"]["by"], refix.REFIX_BY)

    def test_refix2_brief_keeps_its_shape(self):
        """2 回目の手直しの材料は変えない（plan_items・compliance を載せない。2 判定は 1 回目の審査だけ）。穴の枝の名札 ties は
        どの回にも載る（線の木の段 4a）"""
        repo, _ = self.refixed()
        self.assertTrue(refix.cut(self.board, 2, repo)["ok"])
        self.assertTrue(refix.accept_review(linekit.reply("fix2_delta_review2_faces"), self.board, "", repo, n=2)["ok"])
        brief = json.loads(pathlib.Path(refix.prep_fix(self.board, 2, repo)["brief_file"]).read_text(encoding="utf-8"))
        self.assertEqual(set(brief), {"node", "diff_file", "owed", "reads", "policy", "ties"})
        self.assertEqual([x["key"] for x in brief["ties"]], [r["key"] for r in brief["owed"]])

    def test_refix_missing_key_rejected(self):
        """義務の key を 1 つ答えない → ok False（写しの delta_fix_output の文）、盤面は前のまま"""
        repo, _ = self.reviewed()
        refix.prep_fix(self.board, 1, repo)
        before = TE.board_shas(self.board)
        got = refix.accept_fix(linekit.reply("fix2_delta_fix_missing_key"), self.board, "", repo, n=1)
        self.assertFalse(got["ok"])
        self.assertIn("応答が無い", got["reason"])
        self.assertIn(PR_KEY[:40], got["reason"])
        self.assertEqual(TE.board_shas(self.board), before)

    def _scoped_refix(self, *, before_fix=None, out_of_scope=()):
        """範囲の欄の在る修正案（どの項目も stats.py だけを許す）で、1 回目の手直しの支度まで進めた作業ツリー"""
        repo = self.fixed(before_fix=before_fix)
        self.plan_fields(scoped=True)
        if out_of_scope:
            rows = json.loads((self.board / planmarks.FIELDS_FILE).read_text(encoding="utf-8"))["fields"]
            rows[0]["out_of_scope"] = [{"glob": g, "why": "見本。この項目は触らない"} for g in out_of_scope]
            planmarks.save(self.board, entry.open_board(self.board).round, rows)
        self.assertTrue(refix.cut(self.board, 1, repo)["ok"])
        reply = linekit.reply("fix2_delta_review_faces")
        reply["compliance"] = {"verdict": "pass", "read": "修正案の項目 1・2 と差分の stats.py を読み、項目と差分を照らした",
                               "items": []}
        reply["quality"] = {"verdict": "fail", "why": "docstring が下限の枝の約束を書いていない穴が準拠の外に残っている"}
        got = refix.accept_review(reply, self.board, "", repo, n=1)
        self.assertTrue(got["ok"], got)
        self.assertTrue(refix.prep_fix(self.board, 1, repo)["ok"])
        apply_refix(repo)
        return repo

    def test_refix_outside_plan_scope_rejected(self):
        """keep-essence の 5 の例外を消す: 手直しも修正の段と同じ範囲の照らし（承認済みの修正案の項目の範囲の和・直す裁定が
        広げたパス・範囲の相談の合意。単位に結べないので全部の項目で照らす）を機械で受ける。外れは拒み、盤面は前のまま"""
        repo = self._scoped_refix()
        (repo / "extra.py").write_text("X = 1\n", encoding="utf-8")
        before = TE.board_shas(self.board)
        got = refix.accept_fix(linekit.reply("fix2_delta_fix_ok"), self.board, "", repo, n=1)
        self.assertFalse(got["ok"], got)
        self.assertIn("extra.py", got["reason"])
        self.assertIn("allowed_paths", got["reason"])
        self.assertEqual(TE.board_shas(self.board), before)

    def test_refix_out_of_scope_glob_rejected(self):
        repo = self._scoped_refix(out_of_scope=["test_stats.py"])
        (repo / "test_stats.py").write_text((repo / "test_stats.py").read_text(encoding="utf-8") + "\n# x\n",
                                            encoding="utf-8")
        got = refix.accept_fix(linekit.reply("fix2_delta_fix_ok"), self.board, "", repo, n=1)
        self.assertFalse(got["ok"], got)
        self.assertIn("out_of_scope", got["reason"])

    def test_refix_inside_plan_scope_passes(self):
        repo = self._scoped_refix()
        got = refix.accept_fix(linekit.reply("fix2_delta_fix_ok"), self.board, "", repo, n=1)
        self.assertTrue(got["ok"], got)

    def test_refix_is_not_blamed_for_the_fix_files(self):
        """修正の段が触ったファイル（修正の差分の files）は手直しの照らしに入れない（修正の受け付けがその段の決まりで照らした物）"""
        repo = self._scoped_refix(before_fix=lambda r: (r / "fixextra.py").write_text("Y = 2\n", encoding="utf-8"))
        got = refix.accept_fix(linekit.reply("fix2_delta_fix_ok"), self.board, "", repo, n=1)
        self.assertTrue(got["ok"], got)

    def test_refix_without_plan_scope_is_not_checked(self):
        """修正案の範囲の欄が無い run（修正案の無い run・217 番の形の控え）は照らさない（修正の段と同じ）"""
        repo, _ = self.reviewed()
        self.assertTrue(refix.prep_fix(self.board, 1, repo)["ok"])
        apply_refix(repo)
        (repo / "extra.py").write_text("X = 1\n", encoding="utf-8")
        self.assertTrue(refix.accept_fix(linekit.reply("fix2_delta_fix_ok"), self.board, "", repo, n=1)["ok"])

    def test_refix_needs_launch_mark(self):
        """prep_fix（起こした印）を通さずに手直しの返答を渡す → BoardGap（役に返さない。回す側の誤り）"""
        repo, _ = self.reviewed()
        with self.assertRaises(BoardGap):
            refix.accept_fix(linekit.reply("fix2_delta_fix_ok"), self.board, "", repo, n=1)

    def test_cut2_is_refix_only_diff(self):
        """手直しで docstring の 1 行を変えた後 → cut(2) の差分は手直しの行だけ（修正の mean・clamp の行が無い）"""
        repo, _ = self.refixed()
        got = refix.cut(self.board, 2, repo)
        self.assertTrue(got["ok"], got)
        b = entry.open_board(self.board)
        self.assertEqual(got["diff_file"], b.loop_state["fix_delta2"]["file"])
        self.assertEqual(got["files"], ["stats.py"])
        patch = pathlib.Path(got["diff_file"]).read_text(encoding="utf-8")
        self.assertIn("+" + REFIXED_DOC.rstrip("\n"), patch)
        self.assertIn("-" + FIXED_DOC.rstrip("\n"), patch)
        changed = [x for x in patch.splitlines() if x[:1] in "+-" and not x.startswith(("+++", "---"))]
        self.assertEqual(len(changed), 2, patch)   # 手直しの 1 行の前と後だけ
        for line in ("len(xs)", "return hi", "return lo"):   # 修正（p3.fix）の行は載らない
            self.assertFalse([x for x in changed if line in x], (line, patch))
        self.assertNotEqual(got["diff_file"], b.loop_state["fix_delta"]["file"])
        self.assertTrue(b.work(refix.snapshot_name(2)).is_file())
        self.assertTrue(b.rd["instances"]["p3.delta_review2"].get("launched_at"))

    def test_review2_then_refix2(self):
        """fix2_delta_review2_faces → route の refix2 True → fix2_delta_fix2_ok → ready に p4.ci"""
        repo, _ = self.refixed()
        self.assertTrue(refix.cut(self.board, 2, repo)["ok"])
        got = refix.accept_review(linekit.reply("fix2_delta_review2_faces"), self.board, "", repo, n=2)
        self.assertTrue(got["ok"], got)
        r = refix.route(self.board)
        self.assertEqual((r["review2"], r["refix2"], r["owed2"]), (False, True, 1))
        got = refix.prep_fix(self.board, 2, repo)
        self.assertEqual((got["ok"], got["owed"]), (True, 1))
        got = refix.accept_fix(linekit.reply("fix2_delta_fix2_ok"), self.board, "", repo, n=2)
        self.assertTrue(got["ok"], got)
        self.assertIn("p4.ci", got["ready"])
        out = refix.collect_refix(self.board)
        self.assertEqual((out["ok"], out["owed2"], out["fixed2"], out["files"]), (True, 1, 0, ["stats.py"]))
        b = entry.open_board(self.board)
        self.assertEqual(out["handled_file"], str(self.board / b.state["outputs"]["p3.delta_fix"]["file"]))
        self.assertEqual(out["review2_file"], str(self.board / b.state["outputs"]["p3.delta_review2"]["file"]))

    def test_review2_none_skips_refix2(self):
        """2 回目の審査が穴 0 件・検算が全部塞がった → refix2 False、ready に p4.ci"""
        repo, _ = self.refixed()
        refix.cut(self.board, 2, repo)
        got = refix.accept_review(linekit.reply("fix2_delta_review2_ok"), self.board, "", repo, n=2)
        self.assertTrue(got["ok"], got)
        self.assertIn("p4.ci", got["ready"])
        r = refix.route(self.board)
        self.assertEqual((r["refix2"], r["owed2"]), (False, 0))

    def test_declared_only_skips_review2(self):
        """手直しが全部 declared（fixed 0 件）→ 2 回目の審査は条件で na。route の review2 False、collect の review2_file は空"""
        repo, _ = self.reviewed()
        refix.prep_fix(self.board, 1, repo)
        declared = {"handled": [{**r, "handled": "declared", "how": "誤検知でなく残す: 次の run の判定者に振り分けを任せる"}
                                for r in linekit.reply("fix2_delta_fix_ok")["handled"]]}
        for r in declared["handled"]:
            r.pop("files")
        got = refix.accept_fix(declared, self.board, "", repo, n=1)
        self.assertTrue(got["ok"], got)
        self.assertIn("p4.ci", got["ready"])
        r = refix.route(self.board)
        self.assertEqual((r["review2"], r["refix2"]), (False, False))
        out = refix.collect_refix(self.board)
        self.assertEqual((out["review2_file"], out["owed2"], out["fixed2"], out["files"]), ("", 0, 0, []))

    def test_no_third_pass(self):
        """2 回目の手直しが fixed と言って作業ツリーを変えても、3 回目の節は出ない（p4.ci に進む）。fixed2 は報告の
        next-request.json へ渡す数（T15）"""
        repo, _ = self.refixed()
        refix.cut(self.board, 2, repo)
        refix.accept_review(linekit.reply("fix2_delta_review2_faces"), self.board, "", repo, n=2)
        refix.prep_fix(self.board, 2, repo)
        p = repo / "stats.py"
        p.write_text(p.read_text(encoding="utf-8").replace(REFIXED_DOC, REFIXED_DOC.replace("返す", "返し、境の値はそのまま返す")),
                     encoding="utf-8")
        fixed2 = {"handled": [{"key": F2, "handled": "fixed", "how": "docstring に境の値はそのまま返すと書き足した",
                               "files": ["stats.py"]}]}
        got = refix.accept_fix(fixed2, self.board, "", repo, n=2)
        self.assertTrue(got["ok"], got)
        self.assertEqual([x for x in got["ready"] if x.startswith("p3.")], [])
        self.assertIn("p4.ci", got["ready"])
        self.assertEqual(sorted(refix.passes()), [1, 2])
        self.assertEqual(refix.collect_refix(self.board)["fixed2"], 1)
        self.assertEqual(refix.route(self.board)["refix2"], False)

    def test_reads_all_calls_reads_per_role_ran(self):
        """refix-reads: この周に受けた役（手直し・2 回目の審査）ごとに reads.collect を呼ぶ（Task 6 の口。偽の reads で見る）。
        回さなかった 2 回目の手直しは呼ばない。出口の reads_file は手直しの役の物"""
        repo, _ = self.refixed()
        refix.cut(self.board, 2, repo)
        refix.accept_review(linekit.reply("fix2_delta_review2_ok"), self.board, "", repo, n=2)
        calls = []

        class FakeReads:
            @staticmethod
            def events_for(run_id):
                calls.append(("events", run_id))
                return []

            @staticmethod
            def node_here(loop, node):   # 今の scope（Archon の節の居場所）は線の include refixing
                return f"refixing__{loop}.{node}"

            @staticmethod
            def collect(board_dir, role, node_path, must_read, events):
                p = entry.open_board(board_dir).work(f"reads-{role}.json")
                p.write_text("{}", encoding="utf-8")
                calls.append((role, node_path, must_read, events))
                return {"ok": True, "reads_file": str(p)}
        got = refix.reads_all(self.board, FakeReads, "run-7")
        self.assertEqual(sorted(got["reads_files"]), ["refix", "review2"])
        self.assertEqual(calls[0], ("events", "run-7"))
        rows = {c[0]: c for c in calls[1:]}
        self.assertEqual(rows["refix"][1], "refixing__refix-loop.refix")
        self.assertEqual(rows["review2"][1], "refixing__review2-loop.review2")
        self.assertEqual(rows["review2"][2], refix.must(self.board, "review2"))
        self.assertEqual(len(rows["review2"][2]), 2)   # brief・差分（2 回目の審査役に座は無い）
        out = refix.collect_refix(self.board)
        self.assertEqual(out["reads_file"], got["reads_files"]["refix"])
        self.assertEqual(out["reads_files"], got["reads_files"])
        # スクリプトは core の reads.py（Task 6）を読む（スクリプト自身を読まない。R7）。出来事は ARCHON_CLI_COMMAND が無いので none
        with mock.patch.dict(os.environ, {"WORKFLOW_ID": "run-7"}):
            os.environ.pop("ARCHON_CLI_COMMAND", None)
            # 審査の読んだ証拠の節は線の include reviewing の中の節（出来事を引く include の名を core が Archon の居場所から引く）
            with mock.patch.dict(os.environ, {"ARCHON_NODE_EXECUTION": json.dumps({"path": "reviewing__delta-loop.review-reads"})}):
                delta = self.run_script("blk-delta", "reads", repo, must="[]")
            again = self.run_script("blk-refix", "reads", repo)
        self.assertEqual(delta.returncode, 0, delta.stderr)
        self.assertEqual(pathlib.Path(json.loads(delta.stdout)["reads_file"]).name, "reads-review.json")
        self.assertEqual(again.returncode, 0, again.stderr)
        self.assertEqual(sorted(json.loads(again.stdout)["reads_files"]), ["refix", "review2"])
        self.assertEqual(json.loads(pathlib.Path(json.loads(again.stdout)["reads_files"]["refix"]).read_text(
            encoding="utf-8"))["sources"]["events"], "none")

    def test_prep_removes_stale_outputs(self):
        """支度は前の試みの自分の出力（brief・reads-<役>.json）を消してから書く。支度に要る物が無ければ ok False"""
        repo, _ = self.reviewed()
        self.assertFalse(refix.prep_fix(self.board, 2, repo)["ok"])   # 2 回目の手直しはまだ待っていない
        b = entry.open_board(self.board)
        stale_reads = b.work("reads-refix.json")
        stale_reads.write_text('{"stale": true}', encoding="utf-8")
        b.work("refix1-brief.json").write_text('{"owed": [{"key": "前の試み"}]}', encoding="utf-8")
        got = refix.prep_fix(self.board, 1, repo)
        self.assertFalse(stale_reads.exists())
        brief = json.loads(pathlib.Path(got["brief_file"]).read_text(encoding="utf-8"))
        self.assertEqual({r["key"] for r in brief["owed"]}, {F1, PR_KEY})
        self.assertEqual(refix.must(self.board, "refix"), [got["brief_file"], brief["diff_file"]])

    def test_prep_writes_the_composed_prompt(self):
        """prompt（呼び手のブロックの組み立て）を渡した支度は、brief と差分のパスと run の値で組んだ指示書を prompt-<節>.md に
        書き、prompt_file と must に足す。渡さない支度は前の試みの指示書を消す"""
        repo, _ = self.reviewed()
        seen = []

        def build(n, values):
            seen.append((n, values))
            return f"指示書 {values['brief_file']} {values['policy_path']}\n"
        got = refix.prep_fix(self.board, 1, repo, prompt=build, values={"policy_path": "/p.md"})
        lang = refix.rolekit.lang_line(entry.open_board(self.board).state.get("inputs"))
        self.assertEqual(seen, [(1, {"policy_path": "/p.md", "brief_file": got["brief_file"], "diff_file": got["diff_file"],
                                     "lang": lang})])
        self.assertEqual(pathlib.Path(got["prompt_file"]).read_text(encoding="utf-8"), f"指示書 {got['brief_file']} /p.md\n")
        self.assertEqual(got["must"][-1], got["prompt_file"])
        self.assertEqual(refix.must(self.board, "refix"), got["must"])
        again = refix.prep_fix(self.board, 1, repo)
        self.assertNotIn("prompt_file", again)
        self.assertFalse(pathlib.Path(got["prompt_file"]).exists())
        self.assertEqual(refix.must(self.board, "refix"), again["must"])

    def test_prep_script_carries_refix_seat(self):
        """手直しの支度（scripts/prep.py）は receiving-code-review の座を組んだ指示書の refix-keep の後に載せる。2 回目の審査役には
        座が無い（返答に判定の欄が無く、判定の語の表の型とぶつかる）ので、2 回目の審査の支度は座のファイルを書かない"""
        import importlib.util
        spec = importlib.util.spec_from_file_location("blk_refix_prep", REFIX_DIR / "scripts" / "prep.py")
        prep = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(prep)
        repo, _ = self.reviewed()
        env = {"INPUTS_PASS": "1", "INPUTS_POLICY_PATH": ""}
        text = pathlib.Path(prep.run(self.board, repo, env)["prompt_file"]).read_text(encoding="utf-8")
        self.assertIn(seat.section("refix"), text)
        self.assertIn("receiving-code-review", text)
        apply_refix(repo)
        self.assertTrue(refix.accept_fix(linekit.reply("fix2_delta_fix_ok"), self.board, "", repo, n=1)["ok"])
        got = refix.cut(self.board, 2, repo)
        brief = json.loads(pathlib.Path(got["brief_file"]).read_text(encoding="utf-8"))
        self.assertEqual(brief["seat_file"], "")
        self.assertEqual(got["must"], [got["brief_file"], got["diff_file"]])


# ---------------------------------------------------------------- スクリプト（子で起こす）
class RefixScriptCase(DeltaBoardCase):
    def test_scripts_round_trip(self):
        """prep → accept_refix → route → cut2 → accept_review2 → route → collect をスクリプトで。拒否は 0 と 1 行、
        配線の誤り（支度の前・往復の番号の誤り・環境変数の欠け）は 2 で標準出力は空"""
        repo, _ = self.reviewed()
        r = self.run_script("blk-refix", "cut2", repo)                    # 2 回目の差分はまだ無い
        self.assertEqual((r.returncode, r.stdout), (2, ""), r.stderr)
        r = self.run_script("blk-refix", "prep", repo, policy_path="", **{"pass": "3"})
        self.assertEqual((r.returncode, r.stdout), (2, ""), r.stderr)
        r = self.run_script("blk-refix", "prep", repo, **{"pass": "1"})   # policy_path の欠け（配線の誤り）
        self.assertEqual((r.returncode, r.stdout), (2, ""), r.stderr)
        r = self.run_script("blk-refix", "prep", repo, policy_path="", **{"pass": "1"})
        self.assertEqual(r.returncode, 0, r.stderr)
        prepped = json.loads(r.stdout)
        self.assertEqual(prepped["owed"], 2)
        composed = pathlib.Path(prepped["prompt_file"]).read_text(encoding="utf-8")
        self.assertIn(f"`{prepped['brief_file']}`", composed)
        self.assertIn(prepped["prompt_file"], prepped["must"])
        r = self.run_script("blk-refix", "accept_refix", repo, reply=json.dumps(linekit.reply("fix2_delta_fix_missing_key")),
                            base_rev="", **{"pass": "1"})
        self.assertEqual(r.returncode, 0, r.stderr)
        got = json.loads(r.stdout)
        self.assertFalse(got["ok"])
        self.assertEqual(pathlib.Path(got["reason_file"]).read_text(encoding="utf-8"), got["reason"])
        apply_refix(repo)
        r = self.run_script("blk-refix", "accept_refix", repo, reply=json.dumps(linekit.reply("fix2_delta_fix_ok")),
                            base_rev="", **{"pass": "1"})
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(json.loads(r.stdout)["ok"], r.stdout)
        r = self.run_script("blk-refix", "route", repo)
        self.assertEqual(json.loads(r.stdout), {"review2": True, "refix2": False, "owed": 2, "owed2": 0})
        r = self.run_script("blk-refix", "cut2", repo)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(json.loads(r.stdout)["files"], ["stats.py"])
        r = self.run_script("blk-refix", "accept_review2", repo, reply=json.dumps(linekit.reply("fix2_delta_review2_ok")),
                            base_rev="")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(json.loads(r.stdout)["ok"], r.stdout)
        r = self.run_script("blk-refix", "route", repo)
        self.assertEqual(json.loads(r.stdout)["refix2"], False)
        r = self.run_script("blk-refix", "collect", repo)
        self.assertEqual(r.returncode, 0, r.stderr)
        out = json.loads(r.stdout)
        self.assertTrue({"ok", "handled_file", "review2_file", "owed2", "fixed2", "files", "reads_file"} <= set(out))
        self.assertTrue(out["review2_file"])
        env_less = subprocess.run([sys.executable, str(REFIX_DIR / "scripts" / "collect.py")], cwd=str(repo),
                                  env={k: v for k, v in os.environ.items() if k != "ARTIFACTS_DIR"},
                                  capture_output=True, text=True, encoding="utf-8", stdin=subprocess.DEVNULL)
        self.assertEqual((env_less.returncode, env_less.stdout), (2, ""))
        self.assertFalse([*CORE.rglob("__pycache__")])


# ---------------------------------------------------------------- 表・指示書・配線（盤面なし）
class RefixStaticCase(unittest.TestCase):
    def test_route_uses_delta_passes_table(self):
        """passes() の節の名前が写しの DELTA_PASSES と同じ（works に名前の写しを持たない）"""
        want = {n: {k: getattr(p, k) for k in refix.PASS_KEYS} for n, p in rules_module().DELTA_PASSES.items()}
        self.assertEqual(refix.passes(), want)
        self.assertEqual(sorted(want), [1, 2])
        src = (CORE / "refix.py").read_text(encoding="utf-8")
        for p in want.values():
            for k in ("cut", "review", "owed", "fix"):
                self.assertNotIn(f'"{p[k]}"', src)   # 節の名前の字を refix.py に書かない

    def test_refix_seat_after_keep(self):
        """手直しの役の座は手直しだけの決まり（refix-keep）の次に載る。空の座は載せない"""
        mod = load_refixrules()
        values = {"brief_file": "/b.json", "diff_file": "/d.patch", "policy_path": ""}
        ids = [pid for pid, _, _ in mod.parts(1, values, seat="S")]
        self.assertEqual(ids[ids.index("refix-keep") + 1], "seat")
        self.assertEqual(dict((pid, t) for pid, t, _ in mod.parts(2, values, seat="S"))["seat"], "S")
        self.assertNotIn("seat", [pid for pid, _, _ in mod.parts(1, values)])
        self.assertIn("S", mod.build(1, values, seat="S"))

    def test_refix_head_names_plan_items_and_compliance(self):
        """1 回目の手直しの指示書の頭（節 refix-head-1）が材料の plan_items と compliance を読ませる。2 回目の頭は載せない"""
        sec = rulebook.sections(REFIX_DIR / "rules" / "refix.md")
        for w in ("`plan_items`", "`compliance`", "`face_key`", "`ruled_paths`"):
            self.assertIn(w, sec["refix-head-1"])
            self.assertNotIn(w, sec["refix-head-2"])
        self.assertIn("`held` の在る項目に向けて直すな", sec["refix-head-1"])
        self.assertIn("`held_units` の単位に向けて直すな", sec["refix-head-1"])

    def test_output_format_marks_roles(self):
        """役の output_format は mark(role_schema(節), 役の名)（TA20）。strip すれば graph の schema"""
        for role, node in (("review", "p3.delta_review"), ("refix", "p3.delta_fix"), ("review2", "p3.delta_review2"),
                           ("refix2", "p3.delta_fix2")):
            with self.subTest(role):
                fmt = refix.output_format(role)
                self.assertEqual(node_marker.parse(fmt["description"])["name"], role)
                self.assertEqual({k: v for k, v in fmt.items() if k != "description"}, accept.role_schema(node))

    def test_prompts_read_loop_prev_reason(self):
        """review2.md と、書く役 refix・refix2 の節の prompt（支度が組んだ指示書を Read させる）が、それぞれの受け付けの拒否の
        理由（reason_file のパス。裁定 R44）を読む。$<節>.output の節は blk-refix の中の節（支度と差分）、$INPUTS は入口の
        policy_paste（読む役）だけ。書く役の方針の置き場 policy_path は支度の節の with: で受け、組んだ指示書に入る"""
        nodes = {}
        for n in yaml.safe_load((REFIX_DIR / "blk-refix.yaml").read_text(encoding="utf-8"))["nodes"]:
            nodes[n["id"]] = n
            for m in (n.get("loop_group") or {}).get("nodes") or []:
                nodes[m["id"]] = m
        want = {"refix": ("refix-accept", "$refix-prep.output", None),
                "review2.md": ("review2-accept", "$cut2.output", "$INPUTS.policy_paste"),
                "refix2": ("refix2-accept", "$refix2-prep.output", None)}
        for name, (acc, own, pol) in want.items():
            with self.subTest(name):
                if name.endswith(".md"):
                    body = (REFIX_DIR / "commands" / name).read_text(encoding="utf-8")
                else:
                    body = nodes[name]["prompt"]
                    self.assertNotIn("command", nodes[name])
                    self.assertIn(f"`{own}.prompt_file` を Read で", body)
                    self.assertEqual(nodes[own[1:-len(".output")]]["with"]["policy_path"], "$INPUTS.policy_path")
                self.assertIn(f"$LOOP_PREV.{acc}.output.reason_file", body)
                self.assertNotIn(f"$LOOP_PREV.{acc}.output.reason ", body)
                refs = set(re.findall(r"\$[A-Za-z_][A-Za-z0-9_.-]*[A-Za-z0-9_]", body))
                if pol:
                    self.assertIn(pol, refs)
                self.assertTrue(any(r.startswith(own + ".") for r in refs), refs)
                allowed = (f"$LOOP_PREV.{acc}.output.reason_file", pol)
                self.assertEqual({r for r in refs if not r.startswith(own + ".")} - set(allowed), set(), refs)
                self.assertNotIn("{{", body)
        for n, role in refix.FIX_ROLE.items():
            self.assertIn(role, [r for r, _ in LOOPS.values()])

    def test_pasted_policy_closes_prompt(self):
        """方針の本文を貼る読む役（review2.md）は、囲みを指示書の末尾に 1 つだけ置く（blk-judge の diagnose.md と
        同じ決まり: 方針の中の見出しの後ろに指示書の節が続かない。tests/test_policy.py）"""
        for path in (REFIX_DIR / "commands" / "review2.md",):   # delta-review.md は brief の policy を読む（test_blk_tests_delta）
            with self.subTest(path.name):
                lines = path.read_text(encoding="utf-8").splitlines()
                begin, end = "=====人の方針ここから=====", "=====人の方針ここまで====="
                self.assertEqual((lines.count(begin), lines.count(end)), (1, 1))
                i = lines.index(begin)
                self.assertEqual(lines[i + 1:i + 3], ["$INPUTS.policy_paste", end])
                self.assertEqual([s for s in lines[i + 3:] if s.strip()], [])

    def test_loop_ids_unique_across_blocks(self):
        """refix-loop・review2-loop・refix2-loop の中の id が他の全部のブロックの節の id と重ならない（台帳 R19）"""
        mine = [x for r, a in LOOPS.values() for x in (r, a)]
        self.assertEqual(len(mine), len(set(mine)))
        others = {}
        for y in sorted(ROOT.glob("*/*.yaml")):
            if y.parent.name == y.stem and y.parent.name != "blk-refix":
                for nid, _ in workflow_nodes(y):
                    others.setdefault(nid, y.parent.name)
        self.assertEqual({x: others[x] for x in mine if x in others}, {})

    def test_scripts_hold_inputs(self):
        """各スクリプトは読む INPUTS_* を定数 INPUTS に持つ（TA16）。頭の 4 行は PEP 723"""
        want = {"prep": ("INPUTS_PASS", "INPUTS_POLICY_PATH"), "accept_refix": ("INPUTS_REPLY", "INPUTS_BASE_REV", "INPUTS_PASS"),
                "cut2": (), "accept_review2": ("INPUTS_REPLY", "INPUTS_BASE_REV"), "route": (), "reads": (),
                "collect": ()}
        for name, inputs in want.items():
            with self.subTest(name):
                src = (REFIX_DIR / "scripts" / f"{name}.py").read_text(encoding="utf-8")
                self.assertEqual(src.splitlines()[:4], ["# /// script", '# requires-python = ">=3.10"',
                                                        "# dependencies = []", "# ///"])
                m = re.search(r"^INPUTS = (\(.*?\))", src, re.M)
                self.assertIsNotNone(m, name)
                self.assertEqual(eval(m.group(1)), inputs)   # noqa: S307（自分のリポジトリの定数の字）
                for v in re.findall(r"INPUTS_[A-Z_]+", src):
                    self.assertIn(v, inputs)


if __name__ == "__main__":
    unittest.main()
