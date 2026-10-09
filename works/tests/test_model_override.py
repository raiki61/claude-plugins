"""run の模型を明示した run（env の WORKS_DEV_MODEL が空でない）で、包み（.shared/core/claude-adapter）が前付けの無い役の段
（core の表 stage-models.json の段）を明示の模型で起こすこと（adapter.py の頭の 19）。

段の YAML は AI の段の全部に model: を書く（持ち主 2026-10-06）ので、Archon の設定の模型（archon.sh が書く run の模型）は段に
効かない。前は前付けの無い段が設定の模型で走り、WORKS_DEV_MODEL=opus でその段を opus にできた。その力を包みが戻す:
- 明示の模型が在る時だけ、表の段の起動の `--model` を明示の値に替える。effort は段の値のまま
- 前付けを持つ役の段（judge・blind-judge・inspector・investigator・cold-reader。表の外）は替えない
- 既定（明示しない run。WORKS_DEV_MODEL が空か無い）は何も替えない
- 起動の記録（launches）の model は子に渡した値、替えた時だけ model_declared に段の宣言を残す（報告の「## 模型」が両方を出す）
- 明示の模型が在るのに表が読めない起動は起こさない（明示を黙って落とさない）。明示が無ければ表を読まない
偽の claude は一時の置き場の python（受けた argv を書くだけ）。git・Archon・決まった秒の待ちは無い。
"""
import json
import os
import pathlib
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parents[1]
CORE = ROOT / ".shared" / "core"
ADAPTER = CORE / "claude-adapter"
sys.dont_write_bytecode = True
sys.path.insert(0, str(CORE))

import adapter  # noqa: E402
import test_tool_parity  # noqa: E402

FAKE = """#!/usr/bin/env python3
import json, os, sys
with open(os.environ["FAKE_ARGV"], "w", encoding="utf-8") as f:
    json.dump(sys.argv[1:], f)
"""


def sdk_argv(node, model="sonnet", eq=False, twice=False):
    """SDK 0.3.282 の並び（test_adapter.sdk_argv と同じ形）。役の節の印 works-node: <node> を持つ道具ゼロの起動"""
    schema = {"type": "object", "description": f"works-node: {node}", "properties": {"a": {"type": "string"}}}
    flag = [f"--model={model}"] if eq else ["--model", model]
    first = (["--model", "haiku"] if twice else [])
    return ["--output-format", "json", "--verbose", *first, *flag, "--effort", "high",
            "--json-schema", json.dumps(schema), "--tools", "", "--setting-sources=project,user",
            "--permission-mode", "bypassPermissions"]


class RunModelPlanCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = pathlib.Path(self._tmp.name).resolve()
        self.cwd = self.tmp / "wt"
        self.cwd.mkdir()
        self.home = self.tmp / "adapter-home"

    def plan(self, argv, **env):
        base = {"PATH": os.environ.get("PATH", "")}
        base.update(env)
        return adapter.plan(argv, str(self.cwd), self.home, "true", new_id=lambda: "s-1", env=base)

    def test_explicit_model_runs_stage_without_frontmatter(self):
        """表の段（前付けの無い役。fix は sonnet・high を宣言）は明示の模型で起こし、effort は段の値のまま"""
        p = self.plan(sdk_argv("fix"), WORKS_DEV_MODEL="opus")
        self.assertEqual(p.mode, "merged", p.why)
        self.assertEqual(adapter.requested_flag(p.argv, "--model"), "opus")
        self.assertEqual(adapter.requested_flag(p.argv, "--effort"), "high")
        self.assertEqual(p.model_declared, "sonnet")
        row = adapter.launch_row(p, self.cwd, 1, "2026-10-06T00:00:00+09:00")
        self.assertEqual((row["model"], row["model_declared"], row["effort"]), ("opus", "sonnet", "high"))

    def test_every_flag_spelling_is_replaced(self):
        """`--model=v` の形も、2 つ在る `--model` も全部替える（CLI は後の指定が勝つが、前の値を残さない）"""
        for kw in ({"eq": True}, {"twice": True}):
            with self.subTest(**kw):
                p = self.plan(sdk_argv("plan", model="opus", **kw), WORKS_DEV_MODEL="sonnet")
                self.assertEqual([v for _, _, v, _ in adapter.find_opt(p.argv, "--model")],
                                 ["sonnet"] * (2 if kw.get("twice") else 1))
                self.assertEqual(p.model_declared, "opus")
                if kw.get("eq"):
                    self.assertIn("--model=sonnet", p.argv)

    def test_frontmatter_roles_keep_their_model(self):
        """前付けを持つ役の段（表の外）は明示の模型でも替えない。記録に model_declared を持たない"""
        for node, model in (("judge", "opus"), ("r2-compare", "opus"), ("review", "sonnet"), ("report-write-cold", "sonnet")):
            with self.subTest(node):
                p = self.plan(sdk_argv(node, model=model), WORKS_DEV_MODEL="haiku")
                self.assertEqual(adapter.requested_flag(p.argv, "--model"), model)
                self.assertIsNone(p.model_declared)
                self.assertNotIn("model_declared", adapter.launch_row(p, self.cwd, 1, "t"))

    def test_default_run_changes_nothing(self):
        """明示しない run（空・無い）と、明示の値が段の宣言と同じ起動は argv の --model を替えず、記録も今のまま"""
        for env in ({}, {"WORKS_DEV_MODEL": ""}, {"WORKS_DEV_MODEL": "sonnet"}):
            with self.subTest(env=env):
                p = self.plan(sdk_argv("fix"), **env)
                self.assertEqual(adapter.requested_flag(p.argv, "--model"), "sonnet")
                self.assertIsNone(p.model_declared)
                self.assertNotIn("model_declared", adapter.launch_row(p, self.cwd, 1, "t"))

    def test_unmarked_launch_is_untouched(self):
        """印の無い起動（run の題の生成など）は明示の模型でも替えない"""
        argv = ["-p", "--model", "sonnet", "--tools", ""]
        p = self.plan(argv, WORKS_DEV_MODEL="opus")
        self.assertEqual(p.argv, argv)

    def test_overridable_nodes_are_the_stage_table(self):
        """包みが替える段の名は、試験の表 STAGE_MODEL（同じ stage-models.json）の段の名とちょうど同じ"""
        self.assertEqual(adapter.run_model_nodes(), frozenset(place[1] for place in test_tool_parity.STAGE_MODEL))

    def test_unreadable_table_refuses_only_explicit_runs(self):
        """明示の模型が在るのに表が読めない起動は起こさない（明示を黙って落とさない）。明示が無い起動は表を読まずに起こす"""
        for body in (None, "{", json.dumps({"stages": ["fix"]}), json.dumps({"stages": {"fix": "light"}})):
            with self.subTest(body=body):
                bad = self.tmp / "stage-models.json"
                if body is None:
                    bad.unlink(missing_ok=True)
                else:
                    bad.write_text(body, encoding="utf-8")
                with mock.patch.object(adapter, "STAGE_MODELS_FILE", bad):
                    p = self.plan(sdk_argv("fix"), WORKS_DEV_MODEL="opus")
                    self.assertEqual(p.mode, "refused")
                    self.assertIn("stage-models.json", p.why)
                    self.assertEqual(self.plan(sdk_argv("fix")).mode, "merged")


class RunModelChildCase(unittest.TestCase):
    """包みを子で起こし、本物の claude（偽物）が受けた argv と起動の記録を見る"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = pathlib.Path(self._tmp.name).resolve()
        self.home = self.tmp / "adapter-home"
        self.cwd = self.tmp / "wt"
        self.cwd.mkdir()
        self.fake = self.tmp / "fake-claude"
        self.fake.write_text(FAKE, encoding="utf-8")
        self.fake.chmod(self.fake.stat().st_mode | stat.S_IXUSR)
        self.seen = self.tmp / "argv.json"

    def run_adapter(self, node, **kw):
        env = {k: v for k, v in os.environ.items() if not k.startswith("WORKS_")}
        env.update(WORKS_ADAPTER_HOME=str(self.home), WORKS_REAL_CLAUDE=str(self.fake), FAKE_ARGV=str(self.seen),
                   PYTHONDONTWRITEBYTECODE="1", **kw)
        r = subprocess.run([str(ADAPTER), *sdk_argv(node)], cwd=str(self.cwd), env=env, input="",
                           capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(r.returncode, 0, r.stderr)
        rows = adapter.read_launches(self.cwd, self.home)
        return json.loads(self.seen.read_text(encoding="utf-8")), rows[-1]

    def test_child_gets_explicit_model_and_row_keeps_declared(self):
        argv, row = self.run_adapter("tdd", WORKS_DEV_MODEL="opus")
        self.assertEqual(adapter.requested_flag(argv, "--model"), "opus")
        self.assertEqual((row["node"], row["model"], row["model_declared"]), ("tdd", "opus", "sonnet"))

    def test_child_without_explicit_model_gets_declared(self):
        argv, row = self.run_adapter("tdd")
        self.assertEqual(adapter.requested_flag(argv, "--model"), "sonnet")
        self.assertEqual(row["model"], "sonnet")
        self.assertNotIn("model_declared", row)


if __name__ == "__main__":
    unittest.main()
