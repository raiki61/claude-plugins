"""人の方針と前提の実測を役に届ける口の検査（仕様 3.1・3.6・8 節、裁定 TA10）。

この Task（計画 Task 2）では blk-judge の分だけ:
- blk-judge の入口に policy_paste・premises_file（どちらも既定は空・required でない）が在り、指示書 diagnose.md が
  それぞれをちょうど 1 度読む。節の id の並びは見ない（線 B の判定 v2 が節を組み替えても赤にならない。TA18 の 4）
- 貼った方針は囲みの行の間に在り、方針の中の見出し（##）が指示書の節を切らない
- policy_paste を渡す側は、前の節の出力の欄の直の参照（$<節>.output.<欄>）1 つで渡す。Archon は $INPUTS の値を
  差し込んだ後に指示書全体の $<節>.output… と $CONTEXT を置き換えるので、run の入力や $INPUTS 経由で渡すと、
  方針の中の $… が消えるか節が落ちる。節の出力の参照は 1 回だけ置き換わり、差し込んだ中身は読み直されない
  （Task 2 の直し 1 の試し。Archon v0.11.1 の dry-run）
- 判定役の output_format は印 `works-node: judge` を持ち、印を外すと graph の role_schema("p2.diagnose") と同じ（TA20）
"""
import pathlib
import re
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


FENCE_BEGIN = "=====人の方針ここから====="
FENCE_END = "=====人の方針ここまで====="
# policy_paste に渡してよい値: 前の節の出力の欄の直の参照 1 つ（$INPUTS は節ではない）
SAFE_POLICY_REF = re.compile(r"\$(?!INPUTS\.)[A-Za-z_][A-Za-z0-9_-]*\.output\.[A-Za-z_][A-Za-z0-9_]*")


def include_nodes(nodes):
    """include の節を loop_group の中まで辿って返す"""
    for n in nodes or []:
        if "include" in n:
            yield n
        yield from include_nodes((n.get("loop_group") or {}).get("nodes"))


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

    def test_policy_paste_is_fenced(self):
        lines = diagnose_md().splitlines()
        self.assertEqual(lines.count(FENCE_BEGIN), 1)
        self.assertEqual(lines.count(FENCE_END), 1)
        i = lines.index(FENCE_BEGIN)
        self.assertEqual(lines[i + 1:i + 3], ["$INPUTS.policy_paste", FENCE_END])
        # 囲みは指示書の末尾。方針の中の見出しの後ろに、指示書の節が続かない
        self.assertEqual([s for s in lines[i + 3:] if s.strip()], [])

    def test_policy_paste_callers_pass_node_output_ref(self):
        yamls = sorted(ROOT.glob("*/*.yaml"))
        self.assertGreaterEqual(len(yamls), 5)
        for y in yamls:
            wf = yaml.safe_load(y.read_text(encoding="utf-8"))
            for n in include_nodes(wf.get("nodes")):
                if n["include"] != "blk-judge" or "policy_paste" not in (n.get("with") or {}):
                    continue
                with self.subTest(f"{y.parent.name}:{n['id']}"):
                    self.assertRegex(str(n["with"]["policy_paste"]), r"\A" + SAFE_POLICY_REF.pattern + r"\Z")

    def test_safe_policy_ref_pattern(self):
        whole = re.compile(r"\A" + SAFE_POLICY_REF.pattern + r"\Z")
        for ok in ("$start.output.policy_paste", "$h-judge.output.policy"):
            self.assertRegex(ok, whole)
        for bad in ("$INPUTS.policy", "$INPUTS.output.policy", "$start.output", "方針の本文", "$start.output.policy_paste 追記", ""):
            with self.subTest(bad):
                self.assertNotRegex(bad, whole)

    def test_diagnose_reads_premises_file(self):
        text = diagnose_md()
        self.assertEqual(text.count("$INPUTS.premises_file"), 1)
        self.assertIn("仮説", text)
        self.assertIn("測り直した値を採り", text)

    def test_judge_output_format_marked(self):
        fmt = find_node(judge_yaml()["nodes"], "judge")["output_format"]
        self.assertEqual(parse(fmt.get("description")), {"name": "judge", "cont": None, "flags": frozenset()})
        self.assertEqual(strip(fmt), role_schema("p2.diagnose"))



# ---------------------------------------------------------------- start が組む方針の文（計画 Task 7。policy.brief）
# 方針の文書の固定は盤面を作る時の写しの on_init（policy_input.resolve: 共通の git の置き場の graphloops/policy.md を盤面の
# policy/<sha256>.md に写す）。brief はその写し（record.process.policy.copy）から役に貼る本文と置き場を組むだけ
import json  # noqa: E402
import tempfile  # noqa: E402

sys.path.insert(0, str(ROOT / "tests"))
import entry  # noqa: E402
import engine.util as engine_util  # noqa: E402
import linekit  # noqa: E402
import policy  # noqa: E402
from board import DiskBoard  # noqa: E402


class BriefCase(unittest.TestCase):
    def setUp(self):
        self._old_cwd = engine_util.GIT_CWD
        self._tmp = tempfile.TemporaryDirectory(dir=linekit.work_home())
        self.tmp = pathlib.Path(self._tmp.name)
        self.repo = linekit.seed_repo(self.tmp / "repo")

    def tearDown(self):
        engine_util.GIT_CWD = self._old_cwd
        self._tmp.cleanup()

    def board(self, text=None):
        if text is not None:
            pol = self.repo / ".git" / "graphloops" / "policy.md"
            pol.parent.mkdir(parents=True, exist_ok=True)
            pol.write_text(text, encoding="utf-8")
        return DiskBoard.create(self.tmp / "board", repo=self.repo, table=entry.load_table("darkfactory"), inputs={}, request_text="依頼")

    def test_brief_paste_and_path(self):
        b = self.board("# 方針\n\n- テストを消さない\n")
        got = policy.brief(b)
        self.assertEqual(got["paste"], "# 方針\n\n- テストを消さない\n")
        path = pathlib.Path(got["path"])
        self.assertEqual(path.parent, b.dir / "policy")
        self.assertEqual(path.read_text(encoding="utf-8"), got["paste"])
        self.assertEqual(got["path"], b.record["process"]["policy"]["copy"])

    def test_brief_capped(self):
        """5 万バイトの方針 → paste は 40000 バイト以下で、続きの置き場を言う"""
        b = self.board("あ" * 16667 + "\n")   # 3 バイト × 16667 = 50001 バイト
        got = policy.brief(b)
        self.assertEqual(policy.PASTE_CAP, 40000)
        self.assertLessEqual(len(got["paste"].encode("utf-8")), policy.PASTE_CAP)
        self.assertIn("続きは", got["paste"])
        self.assertIn(got["path"], got["paste"])
        self.assertTrue(got["paste"].startswith("あ" * 1000))

    def test_brief_empty_without_policy(self):
        self.assertEqual(policy.brief(self.board()), {"paste": "", "path": ""})


if __name__ == "__main__":
    unittest.main()
