"""世界の解のブロック（blk-world。計画 docs/plans/2026-10-09-world-solution.md の W5・5.2 節・5.4 節・5.5 節）。

- 中身（blk-world/lib/worldblk.py）: 言い直す役の受け付け（依頼の全部の行に 1 つ・対象の識別子を、web の役に渡る proposed も含めて
  拒む・全部の行に検索語）・取る類を決める（類の上限）・web の役の受け付け（differs の challenge・sources が返答の excerpts を指す・
  依頼の解き方の無い行の verdict・抜き書きを取り直した本文で照らし、字のまま無い抜き書きを指す根拠を外して、印 basis を機械が付ける・
  web が off の run は取り直さない）・出口（行を書く）。出し直しの輪の拒否は rolekit の控えに積む
- YAML と筋書き: 入力は形で述べ、ほかのブロック・役・段を名指さない（tests/blockblind.py の柵）・節とスクリプトと指示書の揃い・
  役は言い直す役（道具ゼロ）と web の役（web の検索と取得だけ）の 2 つ・2 つの筋書き（pass・offline）の stub が節の output_format に
  合う。Archon で回すのは dev/check.sh
- 節の口（scripts/*.py）: web が off の run を、本物のスクリプトを子で起こして出口まで回す（網に出ない）。配線の誤りは 2
一時の置き場のファイルと子の python だけ（網・git なし）。
"""
import inspect
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import unittest

import yaml

ROOT = pathlib.Path(__file__).resolve().parents[1]
BLK = ROOT / "blk-world"
sys.dont_write_bytecode = True
for p in (ROOT / ".shared" / "core", ROOT / ".shared" / "core" / "graphloops", BLK / "lib"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import blockblind  # noqa: E402
import prepkit  # noqa: E402
import rolekit  # noqa: E402
import worldblk  # noqa: E402
import worldmark  # noqa: E402
from engine.schema import validate_schema  # noqa: E402

T = 1_800_000_000.0
URL = "https://example.org/guide/tdd"
PAGE = ("<html><body><p>Write a failing test first. A compile error is not a red test: add the smallest stub so the test runs"
        " and fails on the expected assertion.</p></body></html>").encode()
GOOD = "A compile error is not a red test: add the smallest stub so the test runs and fails on the expected assertion."
FINDINGS = [
    {"where": "src/red_check.py:40", "text": "赤の判定がコンパイルの要る対象で読み込みの失敗を赤に数える。読むだけの役を足して生のログから判じさせる"},
    {"where": "docs/guide.md", "text": "手引きの誤字（赤を緑と書いている）"},
]
PROBLEM = "テストを先に書く開発で、まだ無い機能を呼ぶテストを、コンパイルの要る対象でどう赤にするか"
DOC_PROBLEM = "文書の誤字を直す"


def klass(finding=1, **kw):
    row = {"finding": finding, "problem": PROBLEM, "activity": "テストを先に書く開発",
           "proposed": "読むだけの役を足して生のログから判じさせる", "queries": ["test-first red phase compile error stub"]}
    row.update(kw)
    return row


def doc_class(finding=2, **kw):
    row = {"finding": finding, "problem": DOC_PROBLEM, "activity": "文書の校正", "proposed": "",
           "queries": ["proofreading documentation typos practice"]}
    row.update(kw)
    return row


def doc_row(finding=2):
    return {"finding": finding, "problem": "文書の誤字を直す", "activity": "文書の校正", "proposed": "", "queries": [],
            "wording": True}


def judged(finding=1, **kw):
    row = {"finding": finding, "practice": "読み込みの失敗は赤に数えず、最小の仮の実装で走らせてから期待違いの失敗を赤とする",
           "sources": [], "applies": "赤の判定の直し", "not_applies": "", "verdict": "differs",
           "challenge": "依頼は読む役を足す、定石は仮の実装で走らせる。読み込みの失敗が赤でない訳が無い限り定石を選ぶ"}
    row.update(kw)
    return row


def accepted(fn, **kw):
    """fn が受ける名前の引数だけ残す（口の形が替わる前後の両方で、補助の関数が同じ呼び方で呼べるように）"""
    params = inspect.signature(fn).parameters
    return {k: v for k, v in kw.items() if k in params}


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = pathlib.Path(self.tmp.name)
        self.out = self.dir / "world"
        self.req = self.dir / "req.json"
        self.req.write_text(json.dumps(FINDINGS, ensure_ascii=False), encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def intake(self, web="on", findings=None, purpose=""):
        if findings is not None:
            self.req.write_text(json.dumps(findings, ensure_ascii=False), encoding="utf-8")
        return worldblk.intake(self.out, request=str(self.req), purpose_file=purpose, web=web, cwd=self.dir,
                               **accepted(worldblk.intake, cache_root="", env={}, now=T))

    def classes(self, reply):
        worldblk.classes_prep(self.out)
        return worldblk.classes_accept(self.out, reply)

    def plan(self):
        return worldblk.plan(self.out)

    def judge(self, rows, excerpts=(), get=lambda u: (200, PAGE)):
        """web の役の返答（rows と excerpts）を受け付けに渡す。抜き書きは get が返す本文で取り直して照らす"""
        return worldblk.judge_accept(self.out, {"rows": list(rows), "excerpts": list(excerpts)}, get)

    def finish(self):
        return worldblk.finish(self.out, **accepted(worldblk.finish, now=T))


class Classes(Base):
    def test_every_finding_needs_a_class(self):
        self.intake()
        got = self.classes({"classes": [klass(1)]})
        self.assertFalse(got["ok"])
        self.assertIn("行の無い依頼の行: [2]", got["reason"])
        self.assertFalse(got["done"])

    def test_class_text_with_target_identifier_is_refused(self):
        self.intake()
        got = self.classes({"classes": [klass(1, queries=["red_check.py compile error"]), doc_row()]})
        self.assertFalse(got["ok"])
        self.assertIn("red_check.py", got["reason"])

    def test_every_row_needs_queries(self):
        """文書だけの依頼の行でも、言い直しの行に検索語が無ければ拒む（語の直しだけの行の例外は無い）"""
        self.intake()
        worldblk.classes_prep(self.out)
        got = worldblk.classes_accept(self.out, {"classes": [klass(1), {**doc_class(2), "wording": True, "queries": []}]})
        self.assertFalse(got["ok"], got)
        self.assertIn("queries が無い", got["reason"])

    def test_wording_flag_is_not_an_exception(self):
        """語の直しの申告は無い: wording を申し出ても検索語の要る行のまま（where の確かめの文も出ない）"""
        self.intake()
        got = self.classes({"classes": [klass(1, wording=True, queries=[]), doc_class()]})
        self.assertFalse(got["ok"])
        self.assertNotIn("wording は where", got["reason"])
        self.assertIn("queries が無い", got["reason"])
        self.assertTrue(self.classes({"classes": [klass(1), doc_class()]})["ok"])

    def test_reply_class_id_is_ignored(self):
        """類の id は機械が問題の文の hash で付ける: 返答の class_id は見ない（控えに無い id でも拒まず、行の id は hash）"""
        self.intake()
        got = self.classes({"classes": [klass(1, class_id="w-nope"), doc_class()]})
        self.assertTrue(got["ok"], got)
        rows = json.loads((self.out / worldblk.CLASSES).read_text(encoding="utf-8"))
        self.assertEqual(rows[0]["class_id"], worldblk.class_id(PROBLEM))

    def test_queries_needed_on_every_row_and_capped(self):
        self.intake()
        got = self.classes({"classes": [klass(1, queries=[]), {**doc_class(2), "wording": True, "queries": []}]})
        self.assertIn("classes[0]", got["reason"])
        self.assertIn("classes[1]", got["reason"], "文書だけの行も例外にしない")
        self.assertIn("queries が無い", got["reason"])
        got = self.classes({"classes": [klass(1, queries=["a b", "c d", "e f", "g h"]), doc_class()]})
        self.assertIn(f"{worldblk.MAX_QUERIES} 本まで", got["reason"])

    def test_third_rejection_gives_up(self):
        self.intake()
        reasons = []
        for n in (1, 2, 3):
            got = self.classes({"classes": []})
            reasons.append(got["reason"])
        self.assertEqual((got["ok"], got["done"]), (False, True))
        first = (self.out / worldblk.PROMPT.format(role=worldblk.CLASSES_ROLE, n=2)).read_text(encoding="utf-8")
        self.assertTrue(first.startswith(rolekit.with_reject("", reasons[0])), "拒んだ理由を次の指示書の頭に rolekit の形で置く")
        prepkit.drawn(self, "world-classes", first)

    def test_rejections_counted_by_rolekit(self):
        """拒否は rolekit の控えに積まれ、3 回目で done。諦めの文は rolekit が返し、役ごとの手書きの輪の控えは作らない"""
        self.intake()
        reasons = []
        for n in range(1, rolekit.GIVE_UP_AFTER + 1):
            got = self.classes({"classes": []})
            self.assertEqual(got["done"], n == rolekit.GIVE_UP_AFTER, n)
            reasons.append(got["reason"])
        self.assertTrue(rolekit.given_up_reason(self.out, worldblk.CLASSES_ROLE), "諦めた理由を rolekit が返す")
        self.assertEqual(rolekit.rejected(self.out, worldblk.CLASSES_ROLE), reasons)
        self.assertFalse((self.out / f"{worldblk.CLASSES_ROLE}-state.json").exists())
        second = (self.out / worldblk.PROMPT.format(role=worldblk.CLASSES_ROLE, n=2)).read_text(encoding="utf-8")
        self.assertTrue(second.startswith(rolekit.with_reject("", reasons[0])))

    def test_class_ids_are_stable_by_text(self):
        self.intake()
        self.assertTrue(self.classes({"classes": [klass(1, problem=f" {PROBLEM} "), doc_class()]})["ok"])
        rows = json.loads((self.out / worldblk.CLASSES).read_text(encoding="utf-8"))
        self.assertEqual(rows[0]["class_id"], worldblk.class_id(PROBLEM), "前後の空白違いの同じ字の問題は同じ id")
        self.assertNotIn("cached", rows[0])
        self.assertEqual(rows[1]["class_id"], worldblk.class_id(DOC_PROBLEM))
        self.assertEqual(worldblk.class_id(DOC_PROBLEM), worldblk.class_id(f" {DOC_PROBLEM} "))

    def test_purpose_means_are_shown(self):
        p = self.dir / "purpose.json"
        p.write_text(json.dumps({"purpose_text": "赤を言語に依らず判じる", "means": ["読むだけの役を足す"]}, ensure_ascii=False),
                     encoding="utf-8")
        self.intake(purpose=str(p))
        prompt = worldblk.classes_prep(self.out)["prompt"]
        self.assertIn("赤を言語に依らず判じる", prompt)
        self.assertIn("読むだけの役を足す", prompt)


class Plan(Base):
    def test_plan_holds_only_taken_and_over(self):
        """run をまたぐ控えも集める役の起こしを決める道も無い: 取った類は全部 web の役に回り、返りは judge_due だけ、
        plan.json は取った類と越えた行だけ（控えの欄・集める類の欄・web の切り替えは無い。切り替えは intake.json 1 か所）"""
        self.intake()
        self.assertTrue(self.classes({"classes": [klass(1), doc_class()]})["ok"])
        self.assertEqual(worldblk.plan(self.out), {"judge_due": True})
        pl = json.loads((self.out / worldblk.PLAN).read_text(encoding="utf-8"))
        self.assertEqual(set(pl), {"over", "taken"})

    def test_doc_only_rows_still_go_to_judge(self):
        """文書だけの行も飛ばさない: web の役に回る"""
        self.intake(findings=[FINDINGS[1]])
        self.assertTrue(self.classes({"classes": [doc_class(1)]})["ok"])
        self.assertEqual(worldblk.plan(self.out), {"judge_due": True})

    def test_judge_prompt_has_no_target_names(self):
        """web の役の指示書は言い直しの行（類の id・問題・作業・検索語・依頼の解き方）だけで、依頼の行の本文と where を貼らない。
        その全部が対象の名を持たない: 依頼の解き方 proposed に依頼の行の識別子が在る言い直しも受け付けが拒む"""
        self.intake()
        got = self.classes({"classes": [klass(1, proposed="red_check.py に読むだけの役を足す"), doc_class()]})
        self.assertFalse(got["ok"], got)
        self.assertIn("proposed に依頼の行の識別子", got["reason"])
        self.assertIn("red_check.py", got["reason"])
        self.assertTrue(self.classes({"classes": [klass(1), doc_class()]})["ok"])
        worldblk.plan(self.out)
        prompt = worldblk.judge_prep(self.out)["prompt"]
        prepkit.drawn(self, "world-judge", prompt, off=("rolekit.with_reject",))
        for want in (worldblk.class_id(PROBLEM), worldblk.class_id(DOC_PROBLEM), PROBLEM, "test-first red phase compile error stub",
                     klass()["proposed"]):
            self.assertIn(want, prompt)
        for finding in FINDINGS:
            self.assertNotIn(finding["text"], prompt)
            self.assertNotIn(finding["where"], prompt)

    def test_web_off_collects_nothing_and_still_judges(self):
        """web が off の run も web の役に回り、指示書は道具を使うなと言う（on の指示書は抜き書きの返し方を言う）"""
        prompts = {}
        for web in ("on", "off"):
            self.intake(web=web)
            self.classes({"classes": [klass(1), doc_class()]})
            self.assertEqual(worldblk.plan(self.out), {"judge_due": True})
            prompts[web] = worldblk.judge_prep(self.out)["prompt"]
        self.assertFalse(json.loads((self.out / worldblk.INTAKE).read_text(encoding="utf-8"))["web"])
        self.assertIn("web は off", prompts["off"])
        self.assertNotIn("excerpts に", prompts["off"])
        self.assertNotIn("web は off", prompts["on"])
        self.assertIn("excerpts に", prompts["on"])

    def test_web_off_never_refetches(self):
        """web が off の run は取り直さない（取り直しの口が呼ばれない）: 照らしの控えは空で、網に届かなかった扱いにもならない"""
        self.intake(web="off")
        self.classes({"classes": [klass(1), doc_class()]})
        worldblk.plan(self.out)
        worldblk.judge_prep(self.out)

        def never(url):
            raise AssertionError(f"web が off なのに取り直した: {url}")
        self.assertTrue(self.judge([judged(), judged(2, verdict="none", challenge="")], get=never)["ok"])
        doc = json.loads((self.out / worldblk.VERIFIED).read_text(encoding="utf-8"))
        self.assertEqual((doc["kept"], doc["dropped"], doc["offline"]), ([], [], False))
        self.assertNotIn("網に届かなかった", self.finish()["reason"])

    def test_class_cap_counts_over(self):
        many = [{"where": f"src/m{i}.py", "text": f"直し {i}"} for i in range(worldblk.MAX_CLASSES + 2)]
        self.intake(findings=many)
        reply = {"classes": [klass(i + 1, problem=f"類の文 その{i}", queries=[f"問い {i}"]) for i in range(len(many))]}
        self.assertTrue(self.classes(reply)["ok"])
        worldblk.plan(self.out)
        pl = json.loads((self.out / worldblk.PLAN).read_text(encoding="utf-8"))
        self.assertEqual(len(pl["taken"]), worldblk.MAX_CLASSES)
        self.assertEqual(pl["over"], [worldblk.MAX_CLASSES + 1, worldblk.MAX_CLASSES + 2])

    def test_missing_plan_reports_failed(self):
        """言い直しが通った後に類を決める節が落ちた（plan.json が無い）run は、行が無いのを ok と言わない"""
        self.intake()
        self.classes({"classes": [klass(1), doc_class()]})
        got = worldblk.finish(self.out)
        self.assertEqual(got["status"], "failed")
        self.assertIn("類を決める節", got["reason"])

    def test_classes_given_up_skips_everything(self):
        self.intake()
        for _ in range(rolekit.GIVE_UP_AFTER):
            self.classes({"classes": []})
        self.assertEqual(self.plan()["judge_due"], False)
        got = worldblk.finish(self.out)
        self.assertEqual(got["status"], "failed")
        self.assertIn("言い直す役", got["reason"])

    def test_failed_loop_keeps_last_reject_reason(self):
        """拒否が諦めの数に届かないまま輪が落ちた周でも、出口の reason に最後の拒否の文が載る"""
        self.intake()
        rejected = self.classes({"classes": []})
        self.assertFalse(rejected["done"])
        got = worldblk.finish(self.out)
        self.assertEqual(got["status"], "failed")
        self.assertIn(rejected["reason"], got["reason"])


class Verify(Base):
    """web の役の受け付けが、返答の抜き書きを機械が取り直した本文で照らす（役の取得の記録は引かない）"""

    def setUp(self):
        super().setUp()
        self.intake(findings=FINDINGS[:1])
        self.classes({"classes": [klass(1)]})
        self.plan()
        worldblk.judge_prep(self.out)

    def verified(self):
        return json.loads((self.out / worldblk.VERIFIED).read_text(encoding="utf-8"))

    def final_rows(self):
        return worldmark.rows(self.finish()["world_file"])

    def test_verify_keeps_fetched_excerpt_and_caps_total(self):
        """取り直した本文に字のまま在る抜き書きは残り、行は id で引く。越えた分（返答の全部で上限×取った類の数）は頭から取って数を残す。
        字のまま無い抜き書き（言い換え）は落ち、それだけを指す行の根拠は外れて印は knowledge になる。残る根拠が在れば web のまま"""
        ex = {"id": "x1", "url": URL, "excerpt": GOOD}
        made_up = {"id": "x2", "url": URL, "excerpt": "Nothing like this sentence is on that page at all."}
        with self.subTest("残る"):
            self.assertTrue(self.judge([judged(sources=["x1"])], [ex])["ok"])
            self.assertEqual([k["id"] for k in self.verified()["kept"]], ["x1"])
            row = self.final_rows()[0]
            self.assertEqual((row["basis"], row["sources"]), ("web", [ex]))
        with self.subTest("上限"):
            many = [{"id": f"x{i}", "url": URL, "excerpt": GOOD} for i in range(1, worldblk.MAX_EXCERPTS + 3)]
            self.assertTrue(self.judge([judged(sources=["x1"])], many)["ok"])
            doc = self.verified()
            self.assertEqual((len(doc["kept"]), doc["over_excerpts"]), (worldblk.MAX_EXCERPTS, 2))
            self.assertEqual(self.finish()["dropped"], 2)
        with self.subTest("落ちた根拠だけ"):
            self.assertTrue(self.judge([judged(sources=["x2"])], [made_up])["ok"])
            row = self.final_rows()[0]
            self.assertEqual((row["basis"], row["sources"]), ("knowledge", []))
            self.assertEqual(self.finish()["dropped"], 1)
        with self.subTest("落ちた根拠と残る根拠"):
            self.assertTrue(self.judge([judged(sources=["x1", "x2"])], [ex, made_up])["ok"])
            row = self.final_rows()[0]
            self.assertEqual(([s["id"] for s in row["sources"]], row["basis"]), (["x1"], "web"))

    def test_verified_fields_offline_and_web_off(self):
        """役の取得の記録は引かない: 照らしの控えは残した物・落とした物・網の有無・越えた数だけ（出来事の欄も note も無い）。
        網に届かない run（取り直しが全部落ちる）は止めず、行は知識だけで書く。web が off の run は道具を持つ役が抜き書きを返しても
        取り直さず、根拠を外して印を knowledge にする（印は機械が決める）"""
        ex = {"id": "x1", "url": URL, "excerpt": GOOD}
        with self.subTest("控えの欄"):
            self.assertTrue(self.judge([judged(sources=["x1"])], [ex])["ok"])
            self.assertEqual(set(self.verified()), {"kept", "dropped", "offline", "over_excerpts"})

        def down(url):
            raise worldblk.webget.FetchError("網に届かない")
        with self.subTest("網に届かない"):
            self.assertTrue(self.judge([judged(sources=["x1"])], [ex], get=down)["ok"])
            self.assertTrue(self.verified()["offline"])
            self.assertEqual(self.final_rows()[0]["basis"], "knowledge")
            self.assertIn(worldmark.NOT_WEB, self.finish()["reason"])
        with self.subTest("web が off"):
            self.intake(findings=FINDINGS[:1], web="off")
            self.classes({"classes": [klass(1)]})
            self.plan()
            worldblk.judge_prep(self.out)
            calls = []
            got = self.judge([judged(sources=["x1"])], [ex], get=lambda u: calls.append(u) or (200, PAGE))
            self.assertTrue(got["ok"], got)
            self.assertEqual(calls, [])
            row = self.final_rows()[0]
            self.assertEqual((row["basis"], row["sources"]), ("knowledge", []))

    def test_malformed_reply_is_named(self):
        """返答が無い・形の違う返答は拒否の文で名指す: rows の欠け・excerpts の形・返答の中で重なる id・excerpts に無い id を指す sources"""
        ex = {"id": "x1", "url": URL, "excerpt": GOOD}
        self.assertIn("rows", worldblk.judge_accept(self.out, None)["reason"])
        self.assertIn("excerpts は", worldblk.judge_accept(self.out, {"rows": [judged()], "excerpts": "x"})["reason"])
        self.assertIn("excerpts[0]", self.judge([judged()], [{"id": "x1"}])["reason"])
        self.assertIn("重なる", self.judge([judged()], [ex, ex])["reason"])
        self.assertIn("excerpts の id でない", self.judge([judged(sources=["x9"])], [ex])["reason"])


class Judge(Base):
    def setUp(self):
        super().setUp()
        self.intake(findings=FINDINGS[:1])
        self.classes({"classes": [klass(1)]})
        self.plan()
        self.cid = worldblk.class_id(PROBLEM)
        self.prompt = worldblk.judge_prep(self.out)["prompt"]

    def accept(self, *rows):
        return worldblk.judge_accept(self.out, {"rows": list(rows)})

    def test_prompt_asks_for_excerpts_without_target_text(self):
        """抜き書きは web の役が運ぶ物で、指示書には載らない（返し方に excerpts の形が在る）。web の役に渡る文は名を外す:
        依頼の行の本文も where も載らない"""
        self.assertIn(PROBLEM, self.prompt)
        self.assertIn("excerpts に", self.prompt)
        self.assertNotIn(GOOD, self.prompt)
        self.assertNotIn(FINDINGS[0]["text"], self.prompt)
        self.assertNotIn(FINDINGS[0]["where"], self.prompt)

    def test_differs_needs_challenge(self):
        got = self.accept(judged(challenge="短い"))
        self.assertFalse(got["ok"])
        self.assertIn("challenge", got["reason"])

    def test_basis_is_set_by_machine_only(self):
        """役の返答に basis は無く（返しても見ない）、指示書も basis を頼まない。行の basis は機械が照らして残った根拠から付ける:
        残れば web、無ければ knowledge。返答の excerpts に無い id を指す sources は今どおり拒む"""
        self.assertNotIn("basis", self.prompt)
        self.assertIn("excerpts の id でない", self.accept(judged(sources=["x9"]))["reason"])
        self.assertTrue(self.accept(judged(basis="web"))["ok"], "返答の basis は受け付けが見ない")
        self.assertEqual(worldmark.rows(worldblk.finish(self.out)["world_file"])[0]["basis"], "knowledge")
        self.assertTrue(self.judge([judged(basis="knowledge", sources=["x1"])], [{"id": "x1", "url": URL, "excerpt": GOOD}])["ok"])
        self.assertEqual(worldmark.rows(worldblk.finish(self.out)["world_file"])[0]["basis"], "web")

    def test_verdict_none_only_without_proposed(self):
        self.assertIn("verdict none", self.accept(judged(verdict="none", challenge=""))["reason"])

    def test_practice_with_target_identifier_is_refused(self):
        self.assertIn("src/red_check.py", self.accept(judged(practice="src/red_check.py を直す"))["reason"])

    def test_every_judged_row_needed(self):
        self.assertIn("行の無い依頼の行: [1]", self.accept()["reason"])

    def test_knowledge_row_is_written(self):
        self.assertTrue(self.accept(judged())["ok"])
        got = worldblk.finish(self.out)
        self.assertEqual(got["status"], "ok")
        rows = worldmark.rows(got["world_file"])
        self.assertEqual([(r["basis"], r["versus"]["verdict"]) for r in rows], [("knowledge", "differs")])

    def test_web_row_carries_kept_sources(self):
        self.assertTrue(self.judge([judged(sources=["x1"])], [{"id": "x1", "url": URL, "excerpt": GOOD}])["ok"])
        got = worldblk.finish(self.out)
        rows = worldmark.rows(got["world_file"])
        self.assertEqual(rows[0]["sources"], [{"id": "x1", "url": URL, "excerpt": GOOD}])
        self.assertEqual(rows[0]["where"], FINDINGS[0]["where"])
        self.assertEqual(rows[0]["versus"]["proposed"], klass()["proposed"], "依頼の解き方は言い直しの行から機械が写す")
        self.assertEqual((got["classes"], got["dropped"]), (1, 0))

    def test_exit_has_no_cache_or_skip_counts(self):
        """出口は {ok, world_file, status, reason, classes, dropped} だけ。入口の控えに cached・cache_root が無く、行に cached が無い"""
        self.assertTrue(self.judge([judged(sources=["x1"])], [{"id": "x1", "url": URL, "excerpt": GOOD}])["ok"])
        got = self.finish()
        self.assertEqual(set(got), {"ok", "world_file", "status", "reason", "classes", "dropped"})
        intake_doc = json.loads((self.out / worldblk.INTAKE).read_text(encoding="utf-8"))
        self.assertFalse({"cached", "cache_root"} & set(intake_doc), sorted(intake_doc))
        rows = worldmark.rows(got["world_file"])
        self.assertTrue(rows)
        for r in rows:
            self.assertEqual(set(r), set(worldmark.FIELDS))
            self.assertNotIn("cached", r)

    def test_judge_given_up_reports_failed(self):
        for _ in range(rolekit.GIVE_UP_AFTER):
            worldblk.judge_prep(self.out)
            self.accept()
        got = worldblk.finish(self.out)
        self.assertEqual(got["status"], "failed")
        self.assertIn("判断する役", got["reason"])
        self.assertEqual(worldmark.rows(got["world_file"]), [])


class Intake(Base):
    def test_unreadable_request_reports_failed_without_stopping(self):
        got = worldblk.intake(self.out, request="none.json", purpose_file="", web="on", cwd=self.dir)
        self.assertFalse(got["due"])
        fin = worldblk.finish(self.out)
        self.assertEqual((fin["ok"], fin["status"]), (True, "failed"))
        self.assertIn("none.json", fin["reason"])

    def test_empty_request_is_not_due_and_ok(self):
        got = worldblk.intake(self.out, request="", purpose_file="", web="on", cwd=self.dir)
        self.assertEqual(got["due"], False)
        self.assertEqual(worldblk.finish(self.out)["status"], "ok")

    def test_intake_has_no_cache_root(self):
        """控えの置き場は無い: 入口の控えに cache_root も控えの類も書かない"""
        worldblk.intake(self.out, request=str(self.req), purpose_file="", web="on", cwd=self.dir)
        doc = json.loads((self.out / worldblk.INTAKE).read_text(encoding="utf-8"))
        self.assertFalse({"cache_root", "cached"} & set(doc), sorted(doc))

    def test_bad_web_word_is_reported(self):
        self.assertIn("web", self.intake(web="maybe")["reason"])


def flow():
    return yaml.safe_load((BLK / "blk-world.yaml").read_text(encoding="utf-8"))


def walk(nodes):
    for n in nodes:
        yield n
        if "loop_group" in n:
            yield from walk(n["loop_group"]["nodes"])


class Yaml(unittest.TestCase):
    def test_inputs_described_by_shape(self):
        """ほかのブロック・役・段を名指さない（入力は形で述べる。tests/blockblind.py の柵の数えで 0）"""
        files = [f for f in blockblind.tracked(ROOT) if f.startswith("blk-world/")]
        self.assertTrue(files)
        self.assertEqual({k: v for k, v in blockblind.block_refs(ROOT, files).items() if k.startswith("blk-world/")}, {})
        self.assertEqual({k: v for k, v in blockblind.role_refs(ROOT, files).items() if k.startswith("blk-world/")}, {})
        self.assertEqual(set(flow()["inputs"]), {"request", "purpose_file", "web"})

    def test_contract_has_no_cache_or_wording(self):
        """入力に cache_root が無く、言い直す役の型に wording・class_id が無く、出口の型に cached・skipped が無く、受け付けの節の型が
        {ok, done, reason}、支度の節の型が {prompt, prompt_file}"""
        doc = flow()
        self.assertNotIn("cache_root", doc["inputs"])
        nodes = {n["id"]: n for n in walk(doc["nodes"])}
        self.assertNotIn("cache_root", nodes["world-intake"]["with"])
        row = nodes["world-classes"]["output_format"]["properties"]["classes"]["items"]
        self.assertFalse({"wording", "class_id"} & (set(row["properties"]) | set(row["required"])))
        exit_format = nodes["collect"]["output_format"]
        self.assertEqual(set(exit_format["properties"]), {"ok", "world_file", "status", "reason", "classes", "dropped"})
        self.assertEqual(set(exit_format["required"]), set(exit_format["properties"]))
        for nid in ("world-classes-accept", "world-judge-accept"):
            self.assertEqual(set(nodes[nid]["output_format"]["properties"]), {"ok", "done", "reason"}, nid)
            self.assertEqual(set(nodes[nid]["output_format"]["required"]), {"ok", "done", "reason"}, nid)
        for nid in ("world-classes-prep", "world-judge-prep"):
            self.assertEqual(set(nodes[nid]["output_format"]["properties"]), {"prompt", "prompt_file"}, nid)

    def test_scripts_and_commands_exist(self):
        nodes = list(walk(flow()["nodes"]))
        for n in nodes:
            with self.subTest(node=n["id"]):
                if "script" in n:
                    self.assertTrue((BLK / "scripts" / f"{n['script']}.py").is_file())
                if "command" in n:
                    self.assertTrue((BLK / "commands" / f"{n['command']}.md").is_file())
        cmds = {n["command"] for n in nodes if "command" in n}
        self.assertEqual(cmds, {"world-classes", "world-judge"}, "役は言い直す役と web の役の 2 つ")
        self.assertEqual(sorted(p.name for p in (BLK / "commands").glob("*.md")), ["world-classes.md", "world-judge.md"])
        self.assertEqual(sorted(p.name for p in (BLK / "scripts").glob("*.py")),
                         sorted(f"{n['script']}.py" for n in nodes if "script" in n))

    def test_roles_are_isolated_or_web_only(self):
        """言い直す役は道具ゼロ（対象の名を見る役に網を持たせない）、web の役は web の検索と取得だけ（対象の木を読まない）。
        集める役・照らしの節・控えを引く節は無い"""
        nodes = {n["id"]: n for n in walk(flow()["nodes"])}
        self.assertEqual(nodes["world-classes"]["allowed_tools"], [], "対象の木を読まない（上に上がる）")
        self.assertIn("isolated", nodes["world-classes"]["output_format"]["description"])
        web = nodes["world-judge"]
        self.assertEqual(sorted(web["allowed_tools"]), ["WebFetch", "WebSearch"])
        self.assertNotIn("isolated", web["output_format"]["description"])
        props = web["output_format"]["properties"]
        self.assertEqual(set(web["output_format"]["required"]), {"rows", "excerpts"})
        self.assertEqual(set(props["excerpts"]["items"]["required"]), {"id", "url", "excerpt"})
        self.assertIn("sources", props["rows"]["items"]["required"])
        self.assertNotIn("basis", props["rows"]["items"]["properties"], "basis は機械だけが付ける")
        self.assertFalse({"world-collect", "world-verify", "world-cache"} & set(nodes))
        self.assertEqual(set(nodes["world-plan"]["output_format"]["properties"]), {"judge_due"})

    def test_two_scenarios_match_output_formats(self):
        """筋書きは pass と offline の 2 本（控えに当たる筋書きも語の直しの筋書きも無い）で、stub が節の型に合う"""
        self.assertEqual(sorted(p.name for p in (BLK / "fixtures").glob("*.stubs.yaml")), ["offline.stubs.yaml", "pass.stubs.yaml"])
        nodes = {n["id"]: n for n in walk(flow()["nodes"])}
        for name in ("pass", "offline"):
            with self.subTest(fixture=name):
                doc = yaml.safe_load((BLK / "fixtures" / f"{name}.stubs.yaml").read_text(encoding="utf-8"))
                reached = doc["fixture"]["reached"]
                self.assertEqual(reached[-1], "collect")
                stubs = {k: v for k, v in doc.items() if k != "fixture"}
                self.assertEqual(set(stubs), set(reached), "reached の節の全部に stub が在り、ほかの節の stub を置かない")
                for nid, out in stubs.items():
                    fmt = dict(nodes[nid]["output_format"])
                    fmt.pop("description", None)
                    self.assertEqual(validate_schema(out, fmt), [], f"{name}: {nid}")


class Scripts(Base):
    """本物の節の口を子で起こす（web が off の run を出口まで。網に出ない）"""

    def spawn(self, name, **inputs):
        env = {k: v for k, v in os.environ.items() if not k.startswith(("INPUTS_", "ARCHON_", "WORKS_ADAPTER_"))}
        env.update({"ARTIFACTS_DIR": str(self.dir / "art"), "PYTHONDONTWRITEBYTECODE": "1",
                    **{f"INPUTS_{k.upper()}": v for k, v in inputs.items()}})
        return subprocess.run([sys.executable, str(BLK / "scripts" / f"{name}.py")], cwd=self.dir, env=env,
                              capture_output=True, text=True, encoding="utf-8")

    def run_script(self, name, **inputs):
        p = self.spawn(name, **inputs)
        self.assertEqual(p.returncode, 0, p.stderr)
        return json.loads(p.stdout)

    def test_wiring_error_exits_2(self):
        """入口の控えが無い置き場で支度のスクリプトを起こすと、配線の誤りとして標準エラーに 1 行で終了コード 2（標準出力は空）"""
        p = self.spawn("classes_prep")
        self.assertEqual(p.returncode, 2, p.stderr)
        self.assertEqual(p.stdout, "")
        self.assertEqual(len(p.stderr.strip().splitlines()), 1, p.stderr)

    def test_web_off_run_reaches_exit(self):
        nodes = {n["id"]: n for n in walk(flow()["nodes"])}

        def check(nid, out):
            fmt = dict(nodes[nid]["output_format"])
            self.assertEqual(validate_schema(out, fmt), [], nid)
            return out
        got = check("world-intake", self.run_script("intake", request="req.json", purpose_file="", web="off"))
        self.assertTrue(got["due"])
        prep = check("world-classes-prep", self.run_script("classes_prep"))
        self.assertEqual(set(prep), {"prompt", "prompt_file"})
        acc = check("world-classes-accept", self.run_script("classes_accept",
                                                             reply=json.dumps({"classes": [klass(1), doc_class()]}, ensure_ascii=False)))
        self.assertTrue(acc["ok"], acc)
        self.assertEqual(set(acc), {"ok", "done", "reason"})
        plan = check("world-plan", self.run_script("plan"))
        self.assertEqual(plan, {"judge_due": True})
        prep = check("world-judge-prep", self.run_script("judge_prep"))
        self.assertIn("web は off", prep["prompt"])
        acc = check("world-judge-accept", self.run_script("judge_accept", reply=json.dumps(
            {"rows": [judged(), judged(2, verdict="none", challenge="")], "excerpts": []}, ensure_ascii=False)))
        self.assertTrue(acc["ok"], acc)
        fin = check("collect", self.run_script("collect"))
        self.assertEqual(set(fin), {"ok", "world_file", "status", "reason", "classes", "dropped"})
        self.assertEqual(fin["status"], "ok")
        self.assertIn(worldmark.NOT_WEB, fin["reason"])
        self.assertEqual([r["basis"] for r in worldmark.rows(fin["world_file"])], ["knowledge", "knowledge"])


if __name__ == "__main__":
    unittest.main()
