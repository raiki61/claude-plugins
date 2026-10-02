"""ラインの入力の名の集合を正本（darkfactory.yaml の inputs）に縛る。YAML とスクリプトを読み、entry.check_inputs を直に呼び、
linekit.LineRun を種の git を差し替えて組むだけ（FAST。git・子のプロセスなし）。前は重い段の test_line にしか無く、名の食い違いが速い段で見えなかった。

- yaml の inputs の名 == ラインの節（inputs の外の全部の値）が参照する $INPUTS.<名>（test_yaml_inputs_are_all_referenced）
- 線とブロックの全部の script の節で、with: の鍵を INPUTS_<大文字> にした集合 == スクリプトの定数 INPUTS（TA16。
  test_script_inputs_match_with）。既定の在る入力は定数 OPTIONAL_INPUTS に名指した物だけ with: に無くてよい
- start.py の INPUTS の名ごとに、entry.check_inputs が渡した値を同じ名で返す（test_check_inputs_passes_every_start_name）。
  変更の入口の base・pr だけは base_rev・change に解いて返す（merge-base は差し替え、pr は番号でない値の拒みで読みを見る）
- 報告の言語 lang がラインから start の with に渡り、start.py が読み、空は空のまま返る（LangInputCase）
- 器 linekit.LineRun が start へ渡す入力の鍵は LINE_ORDER の start の with から導く（test_linerun_inputs_follow_line_order_start。
  種の git は作らない）
"""
import ast
import contextlib
import copy
import importlib.util
import json
import pathlib
import re
import sys
import tempfile
import unittest
from unittest import mock

import yaml

TESTS = pathlib.Path(__file__).resolve().parent
ROOT = TESTS.parent
LINE = ROOT / "darkfactory"
sys.dont_write_bytecode = True
sys.path.insert(0, str(ROOT / ".shared" / "core"))
sys.path.insert(0, str(TESTS))
import entry  # noqa: E402
import linekit  # noqa: E402

# 既定の在る入力で、with: に書かなくてよい物: {(フォルダ, スクリプト): {INPUTS_*}}
OPTIONAL_INPUTS = {}
# 定数 INPUTS をまだ持たないスクリプト（裁定 TA16 の縛りの外。減らす方向にだけ変える。持ったら消す）
NO_INPUTS_CONSTANT = frozenset({
    "blk-fix/scripts/ignored_before.py", "blk-fix/scripts/clean.py", "blk-fix/scripts/assert_changed.py",
    "blk-judge/scripts/intake.py", "blk-judge/scripts/accept.py", "blk-judge/scripts/collect.py",
    "blk-purpose/scripts/intake.py", "blk-purpose/scripts/accept.py", "blk-purpose/scripts/collect.py",
})
# check_inputs が start の名のほかに返す欄（依頼のファイルを読んだ結果）
READ_FROM_REQUEST = {"request_file", "items", "request_text"}
# 同じ名で返さず、変更の入口として解いて返す start の名と、その返りの欄（解き方の正本の試験は test_entry_inputs.ChangeInputsCase）
CHANGE_INPUTS = {"base", "pr"}
FROM_CHANGE = {"base_rev", "change"}
# check_inputs でなく entry.start が読む start の名（隔離の前の読み出しのファイル。start が盤面へ写し、写しを check_inputs の
# reads に渡す。解き方の正本の試験は test_ghreads）
START_ONLY = {"github_reads"}
# pr の名を読む時に渡す、殻が隔離の前に読んだ写し（HEAD と PR の head は同じ版）
PR_READS = {"version": 1, "pr": {"7": {"baseRefOid": "b" * 40, "headRefOid": "h" * 40, "title": "", "body": ""}}, "issue": {}}


def _fake_git():
    """entry の git を読む口を偽物にする（FAST の段は git も子のプロセスも起こさない）。PR の base・head は PR_READS から"""
    stack = contextlib.ExitStack()
    stack.enter_context(mock.patch.object(entry, "_git", return_value="h" * 40))
    stack.enter_context(mock.patch.object(entry.subprocess, "run", return_value=mock.Mock(returncode=0, stdout="", stderr="")))
    return stack


def load(path):
    return yaml.safe_load(pathlib.Path(path).read_text(encoding="utf-8"))


def line():
    return load(LINE / "darkfactory.yaml")


def walk(nodes):
    """(節, 輪の中か) を入れ子も辿って"""
    for n in nodes:
        yield n, False
        if "loop_group" in n:
            for m in n["loop_group"]["nodes"]:
                yield m, True


def workflows():
    """(フォルダ, YAML) の全部（ラインとブロック）"""
    for p in sorted(ROOT.glob("*/*.yaml")):
        if p.stem == p.parent.name:
            yield p.parent, load(p)


def script_inputs(path: pathlib.Path):
    """スクリプトの定数 INPUTS（tuple か dict の鍵。モジュールの頭の文字列の定数の名前も解く）。定数が無ければ None"""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names = {}
    for n in tree.body:
        if isinstance(n, ast.Assign) and len(n.targets) == 1 and isinstance(n.targets[0], ast.Name):
            if isinstance(n.value, ast.Constant) and isinstance(n.value.value, str):
                names[n.targets[0].id] = n.value.value
            if n.targets[0].id == "INPUTS":
                if isinstance(n.value, (ast.Tuple, ast.List)):
                    return {names[e.id] if isinstance(e, ast.Name) else ast.literal_eval(e) for e in n.value.elts}
                return set(ast.literal_eval(n.value))
    return None


def start_script():
    spec = importlib.util.spec_from_file_location("start_script", LINE / "scripts" / "start.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class InputNamesCase(unittest.TestCase):
    def test_yaml_inputs_are_all_referenced(self):
        """宣言した入力はどれもどこかで使われ、使う名はどれも宣言されている（with だけでなく when・関所の文言・prompt も見る）"""
        doc = line()
        used = set(re.findall(r"\$INPUTS\.([A-Za-z_]\w*)", yaml.safe_dump(doc["nodes"], allow_unicode=True)))
        self.assertEqual(used, set(doc["inputs"]))

    def test_script_inputs_match_with(self):
        """線とブロックの全部の script の節で、with: の鍵を INPUTS_<大文字> にした集合 == スクリプトの定数 INPUTS（TA16）"""
        for folder, y in workflows():
            for n, _ in walk(y["nodes"]):
                if "script" not in n:
                    continue
                path = folder / "scripts" / f"{n['script']}.py"
                rel = path.relative_to(ROOT).as_posix()
                with self.subTest(f"{folder.name}/{n['id']}"):
                    want = script_inputs(path)
                    if want is None:
                        self.assertIn(rel, NO_INPUTS_CONSTANT, f"{rel} に定数 INPUTS が無い")
                        continue
                    self.assertNotIn(rel, NO_INPUTS_CONSTANT, f"{rel} は定数 INPUTS を持った。NO_INPUTS_CONSTANT から消す")
                    got = {f"INPUTS_{k.upper()}" for k in (n.get("with") or {})}
                    optional = OPTIONAL_INPUTS.get((folder.name, n["script"]), set())
                    self.assertLessEqual(want - got, optional, f"with: に無い INPUTS: {sorted(want - got)}")
                    self.assertEqual(got - want, set(), f"スクリプトが読まない with: の鍵: {sorted(got - want)}")

    def test_check_inputs_passes_every_start_name(self):
        """start.py が読む名ごとに、その名だけに既定と違う妥当な値を渡すと、check_inputs が同じ名でその値を返す（変更の入口の
        base・pr は base_rev・change に解いて返す）。_word(raw, <名>) の名の取り違え・返しの足し忘れを、名ごとに赤にする"""
        names = set(start_script().INPUTS.values())
        with tempfile.TemporaryDirectory() as tmp:
            repo = pathlib.Path(tmp)
            (repo / "req.json").write_text(json.dumps([{"where": "a.py", "text": "直す"}]), encoding="utf-8")
            (repo / "policy.md").write_text("方針\n", encoding="utf-8")
            (repo / "fx").mkdir()   # 固定材料のフォルダ（fix_fixture は在るフォルダだけを受ける）
            given = {"test_cmd": "x", "thickness": "標準", "gates": "merge", "final_gate": "when_needed", "adapter": "optional",
                     "policy_md": "policy.md", "lang": "English", "base": "main", "pr": "7", "unattended": "true",
                     "design_only": "true", "fix_shape": "af", "fix_fixture": "fx"}
            want = {**given, "policy_md": str(repo / "policy.md"), "fix_fixture": str(repo / "fx")}
            self.assertEqual(set(given) | CHANGE_INPUTS, names - {"request"} - START_ONLY, "start.py の名に、渡す値を決めていない名がある")
            base = entry.check_inputs({"request": "req.json"}, repo)
            self.assertEqual(set(base), (names - {"request"} - CHANGE_INPUTS - START_ONLY) | READ_FROM_REQUEST)
            self.assertEqual(base["request_file"], str((repo / "req.json").resolve()))
            for name, value in given.items():
                with self.subTest(name):
                    if name in CHANGE_INPUTS:   # 同じ名でなく change の name に返る（git は偽物、PR は隔離の前の写し）
                        with _fake_git():
                            got = entry.check_inputs({"request": "req.json", name: value}, repo, reads=PR_READS)
                        self.assertEqual(got["change"]["from"], name)
                        self.assertEqual(got["change"]["name"], want[name])
                        continue
                    if name == "thickness":   # 受ける値が既定の 標準 だけなので、拒む値で名を読んでいることを見る
                        with self.assertRaises(entry.InputRefused):
                            entry.check_inputs({"request": "req.json", name: "軽量"}, repo)
                    else:
                        self.assertNotEqual(base[name], want[name], "既定と同じ値では素通しを確かめられない")
                    got = entry.check_inputs({"request": "req.json", name: value}, repo)
                    self.assertEqual(got[name], want[name])
            with self.subTest("base"), mock.patch.object(entry, "_merge_base", lambda r, ref: f"fork-of-{ref}"):
                got = entry.check_inputs({"request": "req.json", "base": "main"}, repo)
                self.assertEqual(set(got) - set(base), FROM_CHANGE)
                self.assertEqual((got["change"]["from"], got["change"]["name"], got["base_rev"]),
                                 ("base", "main", "fork-of-main"))
            with self.subTest("pr"):   # 番号でない値の拒みで名を読んでいることを見る（gh を起こさない）
                with self.assertRaises(entry.InputRefused) as cm:
                    entry.check_inputs({"request": "req.json", "pr": "main"}, repo)
                self.assertIn("pr='main'", str(cm.exception))

    def test_fix_shape_default_and_refused(self):
        """修正の形 fix_shape: 空は既定の g3 を返し、4 つの語の外は名を言って拒む（盤面を作る前に止める）"""
        with tempfile.TemporaryDirectory() as tmp:
            repo = pathlib.Path(tmp)
            (repo / "req.json").write_text(json.dumps([{"where": "a.py", "text": "直す"}]), encoding="utf-8")
            self.assertEqual(entry.check_inputs({"request": "req.json"}, repo)["fix_shape"], "g3")
            with self.assertRaises(entry.InputRefused) as cm:
                entry.check_inputs({"request": "req.json", "fix_shape": "g2"}, repo)
            self.assertIn("fix_shape", str(cm.exception))


class LangInputCase(unittest.TestCase):
    """報告の言語を利用者が渡す口（本線 loop.py の --lang の写し）: ラインの入力 lang が start の with に渡り、
    入口の check_inputs がそれを返す（空は空のまま。盤面の既定 LANG_DEFAULT が効く。空でない値の素通しは
    test_check_inputs_passes_every_start_name が名ごとに見る）"""

    def test_line_passes_lang_to_start(self):
        doc = line()
        self.assertIn("lang", doc["inputs"])
        start = next(n for n in doc["nodes"] if n["id"] == "start")
        self.assertEqual(start["with"].get("lang"), "$INPUTS.lang")

    def test_start_script_reads_lang(self):
        self.assertEqual(start_script().INPUTS.get("INPUTS_LANG"), "lang")

    def test_check_inputs_keeps_empty_lang(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = pathlib.Path(tmp)
            (repo / "req.json").write_text(json.dumps([{"where": "a.py", "text": "直す"}]), encoding="utf-8")
            self.assertEqual(entry.check_inputs({"request": "req.json", "lang": ""}, repo).get("lang"), "")


class LineRunInputsCase(unittest.TestCase):
    def test_linerun_inputs_follow_line_order_start(self):
        """LineRun が start へ渡す入力の鍵は LINE_ORDER の start の with から request を除いた物（手で重ねない）。
        種の git は作らない（seed_repo を差し替える）"""
        order = copy.deepcopy(linekit.LINE_ORDER)
        start = next(r for r in order if r["id"] == "start")
        start["with"]["new_knob"] = "$INPUTS.new_knob"
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.object(linekit, "LINE_ORDER", order), \
                mock.patch.object(linekit, "seed_repo", lambda into, **_: pathlib.Path(into)):
            run = linekit.LineRun(tmp, replies={}, inputs={"lang": "English"})
        self.assertEqual(set(run.inputs), set(start["with"]) - {"request"})
        self.assertEqual(run.inputs["new_knob"], "")
        self.assertEqual(run.inputs["adapter"], "optional")
        self.assertEqual(run.inputs["lang"], "English")


if __name__ == "__main__":
    unittest.main()
