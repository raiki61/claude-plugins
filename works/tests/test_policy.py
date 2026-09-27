"""人の方針と前提の実測を役に届ける口の検査（仕様 3.1・3.6・8 節、裁定 TA10）。

この Task（計画 Task 2）では blk-judge の分だけ:
- blk-judge の入口に policy_paste・premises_file（どちらも既定は空・required でない）が在り、指示書 diagnose.md が
  それぞれをちょうど 1 度読む。節の id の並びは見ない（線 B の判定 v2 が節を組み替えても赤にならない。TA18 の 4）
- 判定役の output_format は印 `works-node: judge` を持ち、印を外すと graph の role_schema("p2.diagnose") と同じ（TA20）
"""
import pathlib
import sys
import unittest

import yaml

ROOT = pathlib.Path(__file__).resolve().parents[1]
BLK_JUDGE = ROOT / "blk-judge"
sys.dont_write_bytecode = True   # 下の import が pack の中に __pycache__ を作らないように
sys.path.insert(0, str(ROOT / ".shared" / "core"))

from accept import role_schema  # noqa: E402
from node_marker import parse, strip  # noqa: E402


def judge_yaml():
    return yaml.safe_load((BLK_JUDGE / "blk-judge.yaml").read_text(encoding="utf-8"))


def diagnose_md():
    return (BLK_JUDGE / "commands" / "diagnose.md").read_text(encoding="utf-8")


def find_node(nodes, nid):
    for n in nodes or []:
        if n.get("id") == nid:
            return n
        hit = find_node((n.get("loop_group") or {}).get("nodes"), nid)
        if hit is not None:
            return hit
    return None


class JudgeBlockPolicyCase(unittest.TestCase):
    def test_judge_block_declares_policy_paste(self):
        spec = judge_yaml()["inputs"]["policy_paste"]
        self.assertEqual(spec.get("default"), "")
        self.assertFalse(spec.get("required", False))

    def test_judge_block_declares_premises_file(self):
        spec = judge_yaml()["inputs"]["premises_file"]
        self.assertEqual(spec.get("default"), "")
        self.assertFalse(spec.get("required", False))

    def test_diagnose_reads_policy_paste(self):
        text = diagnose_md()
        self.assertEqual(text.count("$INPUTS.policy_paste"), 1)
        self.assertIn("方針を理由に単位を消すな", text)

    def test_judge_block_policy_entry_only(self):
        inputs = judge_yaml()["inputs"]
        text = diagnose_md()
        for name in ("policy_paste", "premises_file"):
            with self.subTest(name):
                self.assertIn(name, inputs)
                self.assertIn(f"$INPUTS.{name}", text)

    def test_diagnose_reads_premises_file(self):
        text = diagnose_md()
        self.assertEqual(text.count("$INPUTS.premises_file"), 1)
        self.assertIn("仮説", text)
        self.assertIn("測り直した値を採り", text)

    def test_judge_output_format_marked(self):
        fmt = find_node(judge_yaml()["nodes"], "judge")["output_format"]
        self.assertEqual(parse(fmt.get("description")), {"name": "judge", "cont": None, "flags": frozenset()})
        self.assertEqual(strip(fmt), role_schema("p2.diagnose"))


if __name__ == "__main__":
    unittest.main()
