"""works/.shared/core/ の写しが graphloops の受け付けの核として動くかの骨組みの検査。

Task 1 の受け入れ試験: engine/rules の写しから `load_rules` が通ること・写した元の
commit が記録されていること・pack の manifest（archon-plugin.json）の形。
Task 9: works のスキル（SKILL.md の frontmatter と本文の起動名）と Claude Code の plugin.json の形。
"""
import json
import os
import pathlib
import re
import subprocess
import sys
import tempfile
import unittest

import yaml

ROOT = pathlib.Path(__file__).resolve().parents[1]
CORE = ROOT / ".shared" / "core"

# 写しの works の手直しは台帳（COPIED_FROM）の ! 行だけに置く。写し直しの道具 dev/core-sync.py と同じ読み口で読む
sys.path.insert(0, str(CORE))
import copyledger  # noqa: E402
# 修正の段の TDD（仕様 tdd-spec 1.2 節）で足した写し
TDD_COPIES = ("graphloops/graphs/review-loop-tdd.json", "graphloops/rules/review-loop-tdd.py",
              "graphloops/prompts/review-loop/tdd/p3.delta_review.md", "graphloops/prompts/review-loop/tdd/p3.fix.md",
              "graphloops/prompts/review-loop/tdd/p3.tdd_tests.md")


def expected_copy(rel: str, src: bytes) -> bytes:
    """元の commit の中身 src に台帳の ! 行の手直しを当てた、写しが持つべきバイト（元のバイトが 1 度でなければ LedgerError）"""
    return copyledger.apply(copyledger.read(CORE / "COPIED_FROM"), rel, src)


class TestCoreCopy(unittest.TestCase):
    def test_rules_load_from_copy(self):
        sys.path.insert(0, str(CORE / "graphloops"))
        from engine.rules import load_rules
        gp = CORE / "graphloops" / "graphs" / "review-loop.json"
        rules = load_rules(gp, json.loads(gp.read_text()))
        for name in ("judge_output", "fix_plan_covers_units", "delta_review_output"):
            self.assertIn(name, rules.POST_CHECKS)
        self.assertTrue(hasattr(rules, "add"))

    def test_copied_from_names_commit(self):
        """1 行目は写した commit（短い hash）と graphloops の版。版の固定は持たない（写し直しは dev/core-sync.py sync が 1 行目を進める）"""
        led = copyledger.read(CORE / "COPIED_FROM")
        self.assertRegex(led.commit, r"^[0-9a-f]{7,40}$")
        self.assertRegex(led.head, r"^\S+\s+graphloops \d+\.\d+\.\d+")

    def test_copied_from_lists_existing_files(self):
        """COPIED_FROM の 2 行目以降に並ぶ写した物が、全部 core の下に在る（0.21.0 で足した 4 本を含む）"""
        listed = [rel for rel, _ in copyledger.read(CORE / "COPIED_FROM").rows]
        for rel in ("graphloops/engine/declared.py", "graphloops/engine/intake.py", "graphloops/engine/pointers.py",
                    "graphloops/rules/policy_input.py"):
            self.assertIn(rel, listed)
        for rel in listed:
            self.assertTrue((CORE / rel).is_file(), rel)
        # 検証器が読む物（盤面の層の scalars の段が要る。0.21.0 の写しで足した）
        for rel in ("scripts/comment-ratio.sh", "REVIEW.md", "graphloops/scripts/parallel-pr.py"):
            self.assertIn(rel, listed)
        for rel in TDD_COPIES:
            self.assertIn(rel, listed)

    def test_role_definitions_resolve_from_pack_without_plugins(self):
        """graph の plugin の役（回す側・driver・別 plugin の役を除く全部）の定義は、plugin の無い CLAUDE_CONFIG_DIR と
        <PLUGIN>_ROOT の無い環境（dogfood の隔離）でも、pack の写し（core/agents/。COPIED_FROM に並び、元の commit とバイト一致）
        から rolekit.agent_def で引ける（run 31: 隔離した設定に convergence-loops が無く、独立の目の支度が BoardGap で落ちた）。
        引いた後に置き場の環境変数を残さない（対象の試験の子へ漏らさない）"""
        roles = set()
        runners = set(json.loads((CORE / "graphloops" / "graphs" / "review-loop.json").read_text(encoding="utf-8"))["runners"])
        for name in ("review-loop.json", "review-loop-tdd.json"):   # TDD 版は extends で節を足す
            g = json.loads((CORE / "graphloops" / "graphs" / name).read_text(encoding="utf-8"))
            roles |= {n["run_by"] for n in g.get("nodes", {}).values()   # 上書きだけの節は run_by を持たない
                      if n.get("run_by") and not n.get("agent_type") and n["run_by"] not in runners | {"driver"}}
        self.assertEqual(roles, {"judge", "blind-judge", "inspector", "investigator", "cold-reader"})
        listed = [rel for rel, _ in copyledger.read(CORE / "COPIED_FROM").rows]
        for r in sorted(roles):
            self.assertIn(f"agents/{r}.md", listed)
        code = ("import json, os, sys; sys.path.insert(0, sys.argv[1]); import rolekit\n"
                "got = {r: rolekit.agent_def('convergence-loops:' + r) for r in sys.argv[2:]}\n"
                "print(json.dumps({'defs': {r: d and {'file': d['file'], 'tools': d['tools'], 'body': bool(d['body'])}"
                " for r, d in got.items()}, 'env': os.environ.get('CONVERGENCE_LOOPS_ROOT')}))")
        with tempfile.TemporaryDirectory() as cfg:
            env = {k: v for k, v in os.environ.items() if k != "CONVERGENCE_LOOPS_ROOT"}
            env.update(CLAUDE_CONFIG_DIR=cfg, PYTHONDONTWRITEBYTECODE="1")
            r = subprocess.run([sys.executable, "-c", code, str(CORE), *sorted(roles)], env=env, capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(r.returncode, 0, r.stderr)
        out = json.loads(r.stdout)
        self.assertIsNone(out["env"], "置き場の環境変数を残した")
        for role in sorted(roles):
            with self.subTest(role):
                d = out["defs"][role]
                self.assertIsNotNone(d, f"{role} の定義が pack から引けない")
                self.assertEqual(pathlib.Path(d["file"]), (CORE / "agents" / f"{role}.md").resolve())
                self.assertTrue(d["body"])
        self.assertEqual(out["defs"]["blind-judge"]["tools"], [], "遮断系（道具ゼロ）が写しの定義から決まる")

    def test_tdd_rules_load_from_copy(self):
        """写しの TDD 版の graph から load_rules が通り、TDD の機械の節・返答の検査が表に在る。一式の上限は 20 日"""
        sys.path.insert(0, str(CORE / "graphloops"))
        from engine.rules import load_rules
        from engine.schema import load_graph
        gp = CORE / "graphloops" / "graphs" / "review-loop-tdd.json"
        g, why = load_graph(str(gp))
        self.assertFalse(why)
        rules = load_rules(str(gp), g)
        for name in ("tdd_start", "tdd_red", "tdd_green"):
            self.assertIn(name, rules.BUILTINS)
        self.assertIn("tdd_tests_output", rules.POST_CHECKS)
        self.assertEqual(rules.SUITE_TIMEOUT, 1728000)
        # TDD 版の指示書（tdd/ の下。graph の置き場からの相対）は写しの中に在る。元の版の指示書（p3.fix.md など）は写さない
        # （works の役は各ブロックの commands/ の指示書で起こす）
        refs = {p for n in g["nodes"].values() for p in [n.get("prompt_file"), *(n.get("prompt_append") or [])]
                if p and "/tdd/" in p}
        self.assertEqual(len(refs), 3)
        for p in refs:
            self.assertTrue((gp.parent / p).resolve().is_file(), p)

    def test_tdd_suite_reads_parse_junit_from_copy(self):
        """TDD の実行器の試験は、写しの rules（graphloops/rules/review-loop-tdd.py）の parse_junit で読む。本線の関数の写しと、
        その写しを縛る版の固定（MAINLINE・MAINLINE_RULES）を持たない（写しの rules が入った今、版の印を 1 つ余計に残す）"""
        import ast
        src = (ROOT / "tests" / "test_tdd_suite.py").read_text(encoding="utf-8")
        tree = ast.parse(src)
        defs = [n.name for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
        self.assertNotIn("parse_junit", defs, "本線の parse_junit の写しを持っている（写しの rules から読む）")
        assigned = {t.id for n in tree.body if isinstance(n, ast.Assign) for t in n.targets if isinstance(t, ast.Name)}
        self.assertEqual(assigned & {"MAINLINE", "MAINLINE_RULES"}, set(), "本線の版の固定を持っている")
        self.assertIn("review-loop-tdd.json", src, "写しの TDD 版の graph から rules を読んでいない")

    def test_deviations_are_recorded(self):
        """手直しの在る写しは COPIED_FROM の行の注記に『works の手直し』と書く。! 行の写しは COPIED_FROM に並ぶ"""
        led = copyledger.read(CORE / "COPIED_FROM")
        listed = {rel for rel, _ in led.rows}
        rows = {ln.split()[0]: ln for ln in led.path.read_text(encoding="utf-8").splitlines()[1:]
                if ln.split() and ln.split()[0] in listed}
        self.assertTrue(led.deviations)
        for rel in led.deviations:
            self.assertIn(rel, rows)
            self.assertIn("works の手直し", rows[rel])
        self.assertEqual(sorted(rel for rel, ln in rows.items() if "works の手直し" in ln), sorted(led.deviations))

    def test_copies_are_byte_identical_to_the_commit(self):
        """COPIED_FROM に並ぶ写しは、1 行目の commit の同じパスの中身とバイト単位で同じ（写しは直さない。! 行の手直しだけを除く）"""
        led = copyledger.read(CORE / "COPIED_FROM")
        commit = led.commit
        listed = [rel for rel, _ in led.rows]
        for rel in listed:
            with self.subTest(rel):
                src = subprocess.run(["git", "-C", str(ROOT), "show", f"{commit}:{rel}"],
                                     capture_output=True, check=True).stdout
                self.assertEqual((CORE / rel).read_bytes(), expected_copy(rel, src))

    def test_main_auth_copy_names_works_core_as_a_copy(self):
        """本流の認証の写し（.shared/core/claude_auth.py）が在り、その本文（正本と同じバイト）の写し先の一覧が works/.shared/core/ を名指す。
        一覧に無い写しは、正本を直す人が配り先に気づかない"""
        copy = CORE / "claude_auth.py"
        self.assertTrue(copy.is_file(), copy)
        import ast
        doc = ast.get_docstring(ast.parse(copy.read_text(encoding="utf-8"))) or ""
        listed = next((l for l in doc.splitlines() if l.startswith("写しは")), "")
        self.assertIn("`works/.shared/core/`", listed, doc[:400])

    def test_manifest(self):
        m = json.loads((ROOT / "archon-plugin.json").read_text())
        self.assertEqual(m["name"], "works")
        self.assertEqual(m["kind"], "workflow-pack")
        self.assertEqual(m["entrypoints"], {"darkfactory": "darkfactory/darkfactory.yaml"})
        self.assertEqual(m["compatibility"], {"archon": ">=0.11.1 <0.12.0"})

    def test_skill_frontmatter(self):
        text = (ROOT / "skills" / "works" / "SKILL.md").read_text()
        self.assertTrue(text.startswith("---\n"))
        _, fm, body = text.split("---\n", 2)
        meta = yaml.safe_load(fm)
        self.assertEqual(meta["name"], "works")
        self.assertTrue(meta.get("description"))
        # ほかのリポジトリの入口は起動の殻 use.sh（入れる・確かめる・起動・差分の出し直し）。Archon を直に打つ形は案内しない
        for line in ('dev/use.sh" check', 'dev/use.sh" start', 'dev/use.sh" show', "claude plugin install works@raiki61"):
            self.assertIn(line, body)
        # 殻はプラグインの入った置き場から起こす（Claude Code がスキルを読む時に ${CLAUDE_PLUGIN_ROOT} を置き場の絶対パスに
        # 置き換える）。リポジトリの clone（WORKS_REPO）を前提にしない
        shells = re.findall(r'sh "([^"]*/dev/[a-z]+\.sh)"', body)
        self.assertEqual(sorted({pathlib.PurePosixPath(x).name for x in shells}), ["report.sh", "stop.sh", "use.sh"])
        for x in shells:
            self.assertTrue(x.startswith("${CLAUDE_PLUGIN_ROOT}/dev/"), x)
        self.assertNotIn("WORKS_REPO", body)
        # 借りる 3 つも入れる行が在る（名は borrow.json の <名>@<marketplace>）
        borrow = json.loads((ROOT / ".shared" / "borrow" / "borrow.json").read_text(encoding="utf-8"))
        for name, item in borrow.items():
            if item["kind"] in ("skills", "plugin"):
                self.assertIn(f"claude plugin install {name}@{item['marketplace']}", body)
                self.assertIn(f"claude plugin marketplace add {item['marketplace_repo']}", body)
        self.assertNotIn("archon workflow run raiki61/works:darkfactory", body)
        p = json.loads((ROOT / ".claude-plugin" / "plugin.json").read_text())
        self.assertEqual(p["name"], "works")
        self.assertEqual(p["version"], "0.2.6")
        self.assertTrue(p.get("description"))


if __name__ == "__main__":
    unittest.main()
