"""世界の解のブロック（blk-world。計画 docs/plans/2026-10-09-world-solution.md の W5・5.2 節・5.4 節・5.5 節）。

- 中身（blk-world/lib/worldblk.py）: 言い直す役の受け付け（依頼の全部の行に 1 つ・対象の識別子を拒む・語の直しだけの行は where が
  全部文書の時だけ）・控えを引く（控えに当たった類は集めない・web が off なら集めない・類の上限）・照らし・判断する役の受け付け
  （differs の challenge・basis と sources・依頼の解き方の無い行の verdict）・出口（行を書き、web の行だけを控えに足す）
- YAML と筋書き: 入力は形で述べ、ほかのブロック・役・段を名指さない（tests/blockblind.py の柵）・節とスクリプトと指示書の揃い・
  4 つの筋書き（pass・offline・cache-hit・wording）の stub が節の output_format に合う。Archon で回すのは dev/check.sh
- 節の口（scripts/*.py）: web が off の run を、本物のスクリプトを子で起こして出口まで回す（網に出ない）
一時の置き場のファイルと子の python だけ（網・git なし）。
"""
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
import webget  # noqa: E402
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


def klass(finding=1, **kw):
    row = {"finding": finding, "class_id": "", "problem": PROBLEM, "activity": "テストを先に書く開発",
           "proposed": "読むだけの役を足して生のログから判じさせる", "queries": ["test-first red phase compile error stub"],
           "wording": False}
    row.update(kw)
    return row


def wording(finding=2):
    return {"finding": finding, "class_id": "", "problem": "文書の誤字を直す", "activity": "文書の校正", "proposed": "",
            "queries": [], "wording": True}


def judged(finding=1, **kw):
    row = {"finding": finding, "practice": "読み込みの失敗は赤に数えず、最小の仮の実装で走らせてから期待違いの失敗を赤とする",
           "sources": [], "applies": "赤の判定の直し", "not_applies": "", "verdict": "differs",
           "challenge": "依頼は読む役を足す、定石は仮の実装で走らせる。読み込みの失敗が赤でない訳が無い限り定石を選ぶ",
           "basis": "knowledge"}
    row.update(kw)
    return row


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = pathlib.Path(self.tmp.name)
        self.out = self.dir / "world"
        self.cache = self.dir / "cache"
        self.req = self.dir / "req.json"
        self.req.write_text(json.dumps(FINDINGS, ensure_ascii=False), encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def intake(self, web="on", findings=None, purpose=""):
        if findings is not None:
            self.req.write_text(json.dumps(findings, ensure_ascii=False), encoding="utf-8")
        return worldblk.intake(self.out, request=str(self.req), purpose_file=purpose, cache_root=str(self.cache), web=web,
                               cwd=self.dir, env={}, now=T)

    def classes(self, reply):
        worldblk.classes_prep(self.out)
        return worldblk.classes_accept(self.out, reply)

    def put_cache(self, cid, **kw):
        doc = {"schema": worldblk.SCHEMA, "status": "ok", "at": T - 10, "class_id": cid, "problem": PROBLEM,
               "activity": "テストを先に書く開発", "practice": "控えの定石", "sources": [{"url": URL, "excerpt": GOOD}], "basis": "web"}
        doc.update(kw)
        self.assertEqual(worldblk.store(self.cache).put(f"{cid}.json", doc), "")


class Classes(Base):
    def test_every_finding_needs_a_class(self):
        self.intake()
        got = self.classes({"classes": [klass(1)]})
        self.assertFalse(got["ok"])
        self.assertIn("行の無い依頼の行: [2]", got["reason"])
        self.assertFalse(got["done"])

    def test_class_text_with_target_identifier_is_refused(self):
        self.intake()
        got = self.classes({"classes": [klass(1, queries=["red_check.py compile error"]), wording()]})
        self.assertFalse(got["ok"])
        self.assertIn("red_check.py", got["reason"])

    def test_wording_needs_doc_only_where(self):
        self.intake()
        got = self.classes({"classes": [klass(1, wording=True, queries=[]), wording()]})
        self.assertFalse(got["ok"])
        self.assertIn("wording は where が全部文書のファイルの行だけ", got["reason"])
        self.assertTrue(self.classes({"classes": [klass(1), wording()]})["ok"])

    def test_queries_needed_except_for_wording(self):
        self.intake()
        got = self.classes({"classes": [klass(1, queries=[]), wording()]})
        self.assertIn("queries が無い", got["reason"])
        got = self.classes({"classes": [klass(1, queries=["a b", "c d", "e f", "g h"]), wording()]})
        self.assertIn(f"{worldblk.MAX_QUERIES} 本まで", got["reason"])

    def test_third_rejection_gives_up(self):
        self.intake()
        for n in (1, 2, 3):
            got = self.classes({"classes": []})
        self.assertEqual((got["ok"], got["done"], got["give_up"], got["attempt"]), (False, True, True, 3))
        first = (self.out / worldblk.PROMPT.format(role=worldblk.CLASSES_ROLE, n=2)).read_text(encoding="utf-8")
        self.assertIn(worldblk.REJECTED_HEAD, first, "拒んだ理由を次の指示書の頭に置く")

    def test_class_ids_are_stable_and_reuse_cache_by_text(self):
        self.put_cache("w-cached00001")
        self.intake()
        prompt = worldblk.classes_prep(self.out)["prompt"]
        self.assertIn("w-cached00001", prompt)
        self.assertTrue(worldblk.classes_accept(self.out, {"classes": [klass(1), wording()]})["ok"])
        rows = json.loads((self.out / worldblk.CLASSES).read_text(encoding="utf-8"))
        self.assertEqual(rows[0]["class_id"], "w-cached00001", "控えの類と同じ字の問題は控えの id")
        self.assertTrue(rows[0]["cached"])
        self.assertEqual(rows[1]["class_id"], worldblk.class_id("文書の誤字を直す"))
        self.assertEqual(worldblk.class_id("文書の誤字を直す"), worldblk.class_id(" 文書の誤字を直す "))

    def test_unknown_class_id_is_refused(self):
        self.intake()
        got = self.classes({"classes": [klass(1, class_id="w-nope"), wording()]})
        self.assertIn("class_id は控えの類の id か空", got["reason"])

    def test_purpose_means_are_shown(self):
        p = self.dir / "purpose.json"
        p.write_text(json.dumps({"purpose_text": "赤を言語に依らず判じる", "means": ["読むだけの役を足す"]}, ensure_ascii=False),
                     encoding="utf-8")
        self.intake(purpose=str(p))
        prompt = worldblk.classes_prep(self.out)["prompt"]
        self.assertIn("赤を言語に依らず判じる", prompt)
        self.assertIn("読むだけの役を足す", prompt)


class Plan(Base):
    def test_cache_hit_skips_collect(self):
        self.put_cache(worldblk.class_id(PROBLEM))
        self.intake()
        self.assertTrue(self.classes({"classes": [klass(1), wording()]})["ok"])
        got = worldblk.plan(self.out, T)
        self.assertEqual((got["collect_due"], got["judge_due"], got["prompt"]), (False, True, ""))
        rows = worldblk._judge_rows(self.out)
        self.assertEqual([s["url"] for s in rows[0]["sources"]], [URL], "控えの抜き書きを判断する役に渡す")
        self.assertEqual(rows[0]["cached_practice"], "控えの定石")

    def test_expired_cache_is_collected(self):
        self.put_cache(worldblk.class_id(PROBLEM), at=T - worldblk.TTL - 1)
        self.intake()
        self.classes({"classes": [klass(1), wording()]})
        got = worldblk.plan(self.out, T)
        self.assertTrue(got["collect_due"])
        self.assertIn(worldblk.class_id(PROBLEM), got["prompt"])
        self.assertIn("test-first red phase compile error stub", got["prompt"])

    def test_web_off_collects_nothing_and_still_judges(self):
        self.intake(web="off")
        self.classes({"classes": [klass(1), wording()]})
        self.assertEqual(worldblk.plan(self.out, T), {"collect_due": False, "judge_due": True, "prompt": ""})

    def test_no_reply_is_not_noted_when_nothing_was_collected(self):
        self.intake(web="off")
        self.classes({"classes": [klass(1), wording()]})
        worldblk.plan(self.out, T)
        worldblk.verify(self.out, None, set(), lambda u: (200, PAGE))
        self.assertEqual(json.loads((self.out / worldblk.VERIFIED).read_text(encoding="utf-8"))["note"], "")

    def test_all_wording_ends_after_classes(self):
        self.intake(findings=[FINDINGS[1]])
        self.assertTrue(self.classes({"classes": [wording(1)]})["ok"])
        self.assertEqual(worldblk.plan(self.out, T), {"collect_due": False, "judge_due": False, "prompt": ""})
        got = worldblk.finish(self.out, T)
        self.assertEqual((got["status"], got["skipped"], got["classes"]), ("ok", 1, 0))
        self.assertEqual(worldmark.rows(got["world_file"]), [])

    def test_class_cap_counts_over(self):
        many = [{"where": f"src/m{i}.py", "text": f"直し {i}"} for i in range(worldblk.MAX_CLASSES + 2)]
        self.intake(findings=many)
        reply = {"classes": [klass(i + 1, problem=f"類の文 その{i}", queries=[f"問い {i}"]) for i in range(len(many))]}
        self.assertTrue(self.classes(reply)["ok"])
        worldblk.plan(self.out, T)
        pl = json.loads((self.out / worldblk.PLAN).read_text(encoding="utf-8"))
        self.assertEqual(len(pl["taken"]), worldblk.MAX_CLASSES)
        self.assertEqual(pl["over"], [worldblk.MAX_CLASSES + 1, worldblk.MAX_CLASSES + 2])

    def test_missing_plan_reports_failed(self):
        """言い直しが通った後に控えを引く節が落ちた（plan.json が無い）run は、行が無いのを ok と言わない"""
        self.intake()
        self.classes({"classes": [klass(1), wording()]})
        got = worldblk.finish(self.out, T)
        self.assertEqual(got["status"], "failed")
        self.assertIn("控えを引く節", got["reason"])

    def test_classes_given_up_skips_everything(self):
        self.intake()
        for _ in range(worldblk.MAX_ATTEMPTS):
            self.classes({"classes": []})
        self.assertEqual(worldblk.plan(self.out, T)["judge_due"], False)
        got = worldblk.finish(self.out, T)
        self.assertEqual(got["status"], "failed")
        self.assertIn("言い直す役", got["reason"])


class Verify(Base):
    def setUp(self):
        super().setUp()
        self.intake()
        self.classes({"classes": [klass(1), wording()]})
        worldblk.plan(self.out, T)
        self.cid = worldblk.class_id(PROBLEM)

    def test_verify_keeps_fetched_excerpt_and_caps_per_class(self):
        rows = [{"class": self.cid, "url": URL, "excerpt": GOOD}] * (worldblk.MAX_EXCERPTS + 2)
        rows += [{"class": "w-other", "url": URL, "excerpt": GOOD}]
        got = worldblk.verify(self.out, {"excerpts": rows}, {URL}, lambda u: (200, PAGE))
        self.assertEqual((got["kept"], got["offline"]), (worldblk.MAX_EXCERPTS, False))
        doc = json.loads((self.out / worldblk.VERIFIED).read_text(encoding="utf-8"))
        self.assertEqual(doc["over_excerpts"], 2)

    def test_missing_events_drop_everything_with_a_note(self):
        got = worldblk.verify(self.out, {"excerpts": [{"class": self.cid, "url": URL, "excerpt": GOOD}]}, None, lambda u: (200, PAGE))
        self.assertEqual(got["kept"], 0)
        self.assertIn("出来事", json.loads((self.out / worldblk.VERIFIED).read_text(encoding="utf-8"))["note"])

    def test_no_reply_is_noted(self):
        worldblk.verify(self.out, None, set(), lambda u: (200, PAGE))
        self.assertIn("集める役の返答が無い", json.loads((self.out / worldblk.VERIFIED).read_text(encoding="utf-8"))["note"])


class Judge(Base):
    def setUp(self):
        super().setUp()
        self.intake()
        self.classes({"classes": [klass(1), wording()]})
        worldblk.plan(self.out, T)
        self.cid = worldblk.class_id(PROBLEM)
        worldblk.verify(self.out, {"excerpts": [{"class": self.cid, "url": URL, "excerpt": GOOD}]}, {URL}, lambda u: (200, PAGE))
        self.prompt = worldblk.judge_prep(self.out)["prompt"]

    def accept(self, *rows):
        return worldblk.judge_accept(self.out, {"rows": list(rows)})

    def test_prompt_carries_kept_excerpts(self):
        self.assertIn("x1", self.prompt)
        self.assertIn(GOOD, self.prompt)

    def test_differs_needs_challenge(self):
        got = self.accept(judged(challenge="短い"))
        self.assertFalse(got["ok"])
        self.assertIn("challenge", got["reason"])

    def test_basis_web_needs_own_sources(self):
        self.assertIn("basis web は sources が 1 つ以上", self.accept(judged(basis="web"))["reason"])
        self.assertIn("照らして残った抜き書きでない", self.accept(judged(basis="web", sources=["x9"]))["reason"])
        self.assertTrue(self.accept(judged(basis="web", sources=["x1"]))["ok"])

    def test_verdict_none_only_without_proposed(self):
        self.assertIn("verdict none", self.accept(judged(verdict="none", challenge=""))["reason"])

    def test_practice_with_target_identifier_is_refused(self):
        self.assertIn("src/red_check.py", self.accept(judged(practice="src/red_check.py を直す"))["reason"])

    def test_every_judged_row_needed(self):
        self.assertIn("行の無い依頼の行: [1]", self.accept()["reason"])

    def test_knowledge_rows_not_cached(self):
        self.assertTrue(self.accept(judged())["ok"])
        got = worldblk.finish(self.out, T)
        self.assertEqual(got["status"], "ok")
        rows = worldmark.rows(got["world_file"])
        self.assertEqual([(r["basis"], r["versus"]["verdict"]) for r in rows], [("knowledge", "differs")])
        self.assertEqual(worldblk.store(self.cache).names(T + 1), [], "knowledge の行は控えに足さない")

    def test_web_rows_are_cached_and_read_back(self):
        self.assertTrue(self.accept(judged(basis="web", sources=["x1"]))["ok"])
        got = worldblk.finish(self.out, T)
        rows = worldmark.rows(got["world_file"])
        self.assertEqual(rows[0]["sources"], [{"id": "x1", "url": URL, "excerpt": GOOD}])
        self.assertEqual(rows[0]["where"], FINDINGS[0]["where"])
        self.assertEqual(rows[0]["versus"]["proposed"], klass()["proposed"], "依頼の解き方は言い直しの行から機械が写す")
        self.assertEqual(worldblk.store(self.cache).names(T + 1), [f"{self.cid}.json"])
        self.assertEqual((got["classes"], got["cached"], got["skipped"], got["dropped"]), (1, 0, 1, 0))

    def test_judge_given_up_reports_failed(self):
        for _ in range(worldblk.MAX_ATTEMPTS):
            worldblk.judge_prep(self.out)
            self.accept()
        got = worldblk.finish(self.out, T)
        self.assertEqual(got["status"], "failed")
        self.assertIn("判断する役", got["reason"])
        self.assertEqual(worldmark.rows(got["world_file"]), [])


class Intake(Base):
    def test_unreadable_request_reports_failed_without_stopping(self):
        got = worldblk.intake(self.out, request="none.json", purpose_file="", cache_root="", web="on", cwd=self.dir, env={}, now=T)
        self.assertFalse(got["due"])
        fin = worldblk.finish(self.out, T)
        self.assertEqual((fin["ok"], fin["status"]), (True, "failed"))
        self.assertIn("none.json", fin["reason"])

    def test_empty_request_is_not_due_and_ok(self):
        got = worldblk.intake(self.out, request="", purpose_file="", cache_root="", web="on", cwd=self.dir, env={}, now=T)
        self.assertEqual(got["due"], False)
        self.assertEqual(worldblk.finish(self.out, T)["status"], "ok")

    def test_cache_root_defaults_to_adapter_home(self):
        worldblk.intake(self.out, request=str(self.req), purpose_file="", cache_root="", web="on", cwd=self.dir,
                        env={webget.SHARED_ENV: str(self.dir)}, now=T)
        doc = json.loads((self.out / worldblk.INTAKE).read_text(encoding="utf-8"))
        self.assertEqual(doc["cache_root"], str(self.dir / worldblk.CACHE_SUB))

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
        self.assertEqual(set(flow()["inputs"]), {"request", "purpose_file", "cache_root", "web"})

    def test_scripts_and_commands_exist(self):
        nodes = list(walk(flow()["nodes"]))
        for n in nodes:
            with self.subTest(node=n["id"]):
                if "script" in n:
                    self.assertTrue((BLK / "scripts" / f"{n['script']}.py").is_file())
                if "command" in n:
                    self.assertTrue((BLK / "commands" / f"{n['command']}.md").is_file())
        cmds = {n["command"] for n in nodes if "command" in n}
        self.assertEqual(cmds, {"world-classes", "world-collect", "world-judge"})

    def test_roles_are_isolated_or_web_only(self):
        nodes = {n["id"]: n for n in walk(flow()["nodes"])}
        for nid in ("world-classes", "world-judge"):
            self.assertEqual(nodes[nid]["allowed_tools"], [], "対象の木を読まない（上に上がる）")
            self.assertIn("isolated", nodes[nid]["output_format"]["description"])
        self.assertEqual(sorted(nodes["world-collect"]["allowed_tools"]), ["WebFetch", "WebSearch"])

    def test_four_scenarios_match_output_formats(self):
        nodes = {n["id"]: n for n in walk(flow()["nodes"])}
        for name in ("pass", "offline", "cache-hit", "wording"):
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

    def run_script(self, name, **inputs):
        env = {k: v for k, v in os.environ.items() if not k.startswith(("INPUTS_", "ARCHON_"))}
        env.update({"ARTIFACTS_DIR": str(self.dir / "art"), "PYTHONDONTWRITEBYTECODE": "1",
                    **{f"INPUTS_{k.upper()}": v for k, v in inputs.items()}})
        p = subprocess.run([sys.executable, str(BLK / "scripts" / f"{name}.py")], cwd=self.dir, env=env,
                           capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(p.returncode, 0, p.stderr)
        return json.loads(p.stdout)

    def test_web_off_run_reaches_exit(self):
        nodes = {n["id"]: n for n in walk(flow()["nodes"])}

        def check(nid, out):
            fmt = dict(nodes[nid]["output_format"])
            self.assertEqual(validate_schema(out, fmt), [], nid)
            return out
        got = check("world-intake", self.run_script("intake", request="req.json", purpose_file="", cache_root=str(self.cache),
                                                     web="off"))
        self.assertTrue(got["due"])
        check("world-classes-prep", self.run_script("classes_prep"))
        acc = check("world-classes-accept", self.run_script("classes_accept",
                                                             reply=json.dumps({"classes": [klass(1), wording()]}, ensure_ascii=False)))
        self.assertTrue(acc["ok"], acc)
        plan = check("world-cache", self.run_script("cache"))
        self.assertEqual((plan["collect_due"], plan["judge_due"]), (False, True))
        check("world-verify", self.run_script("verify", reply=""))
        check("world-judge-prep", self.run_script("judge_prep"))
        acc = check("world-judge-accept", self.run_script("judge_accept", reply=json.dumps({"rows": [judged()]}, ensure_ascii=False)))
        self.assertTrue(acc["ok"], acc)
        fin = check("collect", self.run_script("collect"))
        self.assertEqual(fin["status"], "ok")
        self.assertIn(worldmark.NOT_WEB, fin["reason"])
        self.assertEqual([r["basis"] for r in worldmark.rows(fin["world_file"])], ["knowledge"])


if __name__ == "__main__":
    unittest.main()
