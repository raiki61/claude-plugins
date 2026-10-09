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
- 出力の側（OutputNamesCase。Archon の穴 #2・#3）: 本文の $<節>.output.<欄> が同じ工程の節と出力の型の欄を名指す
  （test_output_refs_name_real_fields）。ラインの節の出力の欄に読み手が在る（無い欄は UNREAD_OUTPUTS に理由つき。
  test_line_outputs_have_readers）
"""
import ast
import collections
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

# 既定の在る入力で、with: に書かなくてよい物: {(フォルダ, スクリプト): {INPUTS_*}}（減らす方向にだけ変える）
OPTIONAL_INPUTS = {}
# 読まない入力を残してよいブロック（理由つき）
UNREAD_INPUTS = {"blk-spec": {"base_rev"}}   # blk-spec を残すかは持ち主の決め待ち（2026-10-09）。触らない
# 定数 INPUTS をまだ持たないスクリプト（裁定 TA16 の縛りの外。減らす方向にだけ変える。持ったら消す）
NO_INPUTS_CONSTANT = frozenset({
    "blk-fix/scripts/assert_changed.py",
    "blk-judge/scripts/intake.py", "blk-judge/scripts/accept.py", "blk-judge/scripts/collect.py",
    "blk-purpose/scripts/intake.py", "blk-purpose/scripts/accept.py", "blk-purpose/scripts/collect.py",
})
# check_inputs が start の名のほかに返す欄（依頼のファイルを読んだ結果）
READ_FROM_REQUEST = {"request_file", "items", "request_text", "answers", "prior_failures"}
# 同じ名で返さず、差分の根（と PR の添え物）として解いて返す start の名と、その返りの欄（解き方の正本の試験は test_entry_inputs.ChangeInputsCase）
CHANGE_INPUTS = {"base", "pr"}
FROM_CHANGE = {"base_rev", "base", "pr"}
# pr の名を読む時に渡す、start が run の中で読んだ読み出し（HEAD と PR の head は同じ版。読み方の正本の試験は test_ghreads）
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


# 殻だけが読む入力（どの節も読まない。Archon が run の metadata.inputs に残し、use.sh が起動を run に結ぶ印。test_launch）
SHELL_ONLY = {"launch_mark"}


class InputNamesCase(unittest.TestCase):
    def test_yaml_inputs_are_all_referenced(self):
        """宣言した入力はどれもどこかで使われ、使う名はどれも宣言されている（with だけでなく when・関所の文言・prompt も見る）。
        殻だけが読む入力（SHELL_ONLY）はどの節も使わない"""
        doc = line()
        used = set(re.findall(r"\$INPUTS\.([A-Za-z_]\w*)", yaml.safe_dump(doc["nodes"], allow_unicode=True)))
        self.assertEqual(used, set(doc["inputs"]) - SHELL_ONLY)
        self.assertLessEqual(SHELL_ONLY, set(doc["inputs"]))

    def test_block_inputs_are_all_referenced(self):
        """ブロックの宣言した入力はどれも、そのブロックの YAML か指示書（commands/）のどこかで $INPUTS.<名> として使われる
        （読まない入力をラインが渡し続けない。2026-10-09 の整理で、読まない base_rev・policy_paste などを消した）"""
        for path in sorted(ROOT.glob("blk-*/blk-*.yaml")):
            folder = path.parent
            doc = yaml.safe_load(path.read_text(encoding="utf-8"))
            texts = [path.read_text(encoding="utf-8")] + [p.read_text(encoding="utf-8") for p in sorted((folder / "commands").glob("*.md"))]
            used = {m for t in texts for m in re.findall(r"\$INPUTS\.([A-Za-z_]\w*)", t)}
            unread = set(doc.get("inputs") or {}) - used - UNREAD_INPUTS.get(folder.name, set())
            with self.subTest(folder.name):
                self.assertEqual(unread, set(), "宣言したが読まない入力（ラインの渡す口ごと消す）")

    def test_fixture_inputs_are_declared(self):
        """ブロックとラインの筋書き（fixtures/*.stubs.yaml）の fixture.inputs は、その工程が宣言した入力だけ（Archon の workflow test は
        宣言の無い入力の筋書きを回さずに落とす。dev/check.sh でしか分からなかった）"""
        for path in sorted(ROOT.glob("*/fixtures/*.stubs.yaml")):
            wf = path.parent.parent
            doc = yaml.safe_load((wf / f"{wf.name}.yaml").read_text(encoding="utf-8"))
            given = set(((yaml.safe_load(path.read_text(encoding="utf-8")) or {}).get("fixture") or {}).get("inputs") or {})
            with self.subTest(str(path.relative_to(ROOT))):
                self.assertEqual(given - set(doc.get("inputs") or {}), set())

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
        """start.py が読む名ごとに、その名だけに既定と違う妥当な値を渡すと、check_inputs が同じ名でその値を返す（差分の根の入口の
        base・pr は base_rev・base・pr に解いて返す）。_word(raw, <名>) の名の取り違え・返しの足し忘れを、名ごとに赤にする"""
        names = set(start_script().INPUTS.values())
        with tempfile.TemporaryDirectory() as tmp:
            repo = pathlib.Path(tmp)
            (repo / "req.json").write_text(json.dumps([{"where": "a.py", "text": "直す"}]), encoding="utf-8")
            (repo / "policy.md").write_text("方針\n", encoding="utf-8")
            (repo / "fx").mkdir()   # 固定材料のフォルダ（fix_fixture は在るフォルダだけを受ける）
            given = {"test_cmd": "x", "thickness": "標準", "gates": "merge", "final_gate": "when_needed", "adapter": "optional",
                     "policy_md": "policy.md", "lang": "English", "base": "main", "pr": "7", "unattended": "true",
                     "design_only": "true", "fix_fixture": "fx",
                     "features_off": "tdd_lanes, judge_verify", "features_on": "review_tree judge_verify"}
            want = {**given, "policy_md": str(repo / "policy.md"), "fix_fixture": str(repo / "fx"),
                    "features_off": ["judge_verify", "tdd_lanes"], "features_on": ["judge_verify", "review_tree"]}
            self.assertEqual(set(given) | CHANGE_INPUTS, names - {"request"}, "start.py の名に、渡す値を決めていない名がある")
            base = entry.check_inputs({"request": "req.json"}, repo)
            self.assertEqual(set(base), (names - {"request"} - CHANGE_INPUTS) | READ_FROM_REQUEST)
            self.assertEqual(base["request_file"], str((repo / "req.json").resolve()))
            for name, value in given.items():
                with self.subTest(name):
                    if name in CHANGE_INPUTS:   # 同じ名でなく差分の根 base の name に返る（git は偽物、PR は run の中の読み出し）
                        with _fake_git():
                            got = entry.check_inputs({"request": "req.json", name: value}, repo, reads=PR_READS)
                        self.assertEqual(got["base"]["from"], name)
                        self.assertEqual(got["base"]["name"], want[name])
                        continue
                    self.assertNotEqual(base[name], want[name], "既定と同じ値では素通しを確かめられない")
                    got = entry.check_inputs({"request": "req.json", name: value}, repo)
                    self.assertEqual(got[name], want[name])
            with self.subTest("base"), mock.patch.object(entry, "_merge_base", lambda r, ref: f"fork-of-{ref}"):
                got = entry.check_inputs({"request": "req.json", "base": "main"}, repo)
                self.assertEqual(set(got) - set(base), FROM_CHANGE)
                self.assertEqual((got["base"]["from"], got["base"]["name"], got["base_rev"]),
                                 ("base", "main", "fork-of-main"))
            with self.subTest("pr"):   # 番号でない値の拒みで名を読んでいることを見る（gh を起こさない）
                with self.assertRaises(entry.InputRefused) as cm:
                    entry.check_inputs({"request": "req.json", "pr": "main"}, repo)
                self.assertIn("pr='main'", str(cm.exception))


# 出口の参照 $<節>.output[.<欄>]（輪の中の前の回 $LOOP_PREV.<節>.output.<欄> も）。本文（when・until・指示書・コメント）の参照は
# Archon が読み込みで欄を照らさない（Archon の穴 #2。with: の from だけは照らす）
OUTPUT_REF = re.compile(r"\$(?:LOOP_PREV\.)?([A-Za-z][\w-]*)\.output(?:\.([A-Za-z_]\w*))?")
# ラインの節の出力の欄のうち、ラインのどこも読まない物 {作り手: (欄の組, 理由)}。作り手は include の id でなくブロックの名、script の
# 節はスクリプトの名（同じスクリプトの境の節 h-* は 1 つの出口の型を分ける）。減らす方向にだけ変える（読み手を付けたら消す。
# test_line_outputs_have_readers が今の姿と字のまま照らす）。ラインの出口（returns の節）は殻が run の結果として読むので見ない
BOARD_CARRIED = ("ラインは盤面で受け渡す（後ろの境の節が盤面を読む）。ブロックの出口の欄は Archon の run の記録と、盤面を持たない"
                 "ラインのための形で、このラインは読まない")
UNREAD_OUTPUTS = {
    "blk-delta": ({"diff_file", "faces", "fix_rev", "owed", "reads_file", "review_file"}, BOARD_CARRIED),
    "blk-fix": ({"changes_file", "coverage", "files", "fix_file", "not_done", "reads_file", "reason", "removed"}, BOARD_CARRIED),
    "blk-lens": ({"lens_file", "reason"}, BOARD_CARRIED),
    "blk-material": ({"reason"}, BOARD_CARRIED),
    "blk-plan": ({"asks_human", "gate_kinds", "gave_up", "plan_file", "reads_file", "reason_file", "review_file", "ripple_file"},
                 BOARD_CARRIED),
    "blk-pr": ({"conflicts", "drafts", "excluded", "excluded_file", "material_status", "pr_file", "reads_file", "reason"},
               BOARD_CARRIED),
    "blk-purpose": ({"purpose_file", "purpose_text", "source"}, BOARD_CARRIED),
    "blk-refix": ({"files", "fixed2", "handled_file", "owed2", "reads_file", "reads_files", "review2_file"}, BOARD_CARRIED),
    "blk-rejudge": ({"diff_file", "lowered", "new_open_units", "objection", "passes", "reads_file", "reason", "unnamed_changed",
                     "unsettled", "verdicts"}, BOARD_CARRIED),
    "blk-report": ({"facts_file", "text_file"}, "AI の報告の材料と本文のファイル。出口 result は report_file だけを選ぶ"),
    "depth": ({"depth_file"}, "盤面の depth.json のパス。報告は h-redepth の lines だけを読む（run の記録に残すだけ）"),
    "edge": ({"spec_go"}, "仕様のブロック blk-spec は一つの入口の計画（docs/plans/2026-10-09-one-entry-shape.md）のために残し、"
                          "まだ線に無い。読み手は計画の段 4 で付く（持ち主 2026-10-09: blk-spec を残す）"),
    "structure": ({"design_file", "ok", "reason", "status", "wall_s"},
                  "構造の境 h-structure は順の結び目（修正案の段が depends_on で待つ）。控えは盤面の structure-state.json で、出口は "
                  "run の記録に残すだけ"),
}


def _deep(nodes):
    for n in nodes:
        yield n
        yield from _deep((n.get("loop_group") or {}).get("nodes") or ())


def _exit_node(block_name):
    doc = load(ROOT / block_name / f"{block_name}.yaml")
    return next(n for n in _deep(doc["nodes"]) if n["id"] == doc["returns"]), doc


def _fields(node):
    """節の出力の欄の名の組（include はブロックの出口の節の型）。型の無い節は None"""
    if "include" in node:
        node = _exit_node(node["include"])[0]
    fmt = node.get("output_format")
    return set((fmt or {}).get("properties") or ()) if fmt else None


class OutputNamesCase(unittest.TestCase):
    """出力の側の柵（読まない入力の柵 test_block_inputs_are_all_referenced の対。Archon の穴 #2・#3。docs/archon-feedback.md）"""

    def test_output_refs_name_real_fields(self):
        """ラインとブロックの YAML と指示書（commands/）の $<節>.output.<欄> は、同じ工程に在る節と、その節の出力の型に在る欄を
        名指す（綴りの違い・消えた欄・ほかの工程の節の名指しを、実行の前に赤にする。Archon は本文の参照の欄を照らさない）"""
        for folder, doc in workflows():
            nodes = {n["id"]: n for n in _deep(doc["nodes"])}
            texts = [(folder / f"{folder.name}.yaml")] + sorted((folder / "commands").glob("*.md"))
            bad = []
            for path in texts:
                for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                    for m in OUTPUT_REF.finditer(line):
                        nid, field = m.group(1), m.group(2)
                        where = f"{path.relative_to(ROOT)}:{i} {m.group(0)}"
                        if nid not in nodes:
                            bad.append(f"{where}: 節 {nid} がこの工程に無い")
                            continue
                        got = _fields(nodes[nid])
                        if field and got is not None and field not in got:
                            bad.append(f"{where}: 欄 {field} が節 {nid} の出力の型に無い（在るのは {sorted(got)}）")
                        elif field and got is None:
                            bad.append(f"{where}: 節 {nid} は出力の型を持たない（欄を読めない）")
            with self.subTest(folder.name):
                self.assertEqual(bad, [])

    def test_line_outputs_have_readers(self):
        """ラインの節の出力の欄は、ラインのどこかが読む: $<節>.output.<欄> で名指すか、出力を丸ごと渡した節（{from: $<節>.output}）
        の受け手のコード（作り手のフォルダの外の .py）が欄の名を字で書く（丸ごと渡しは緩い近似で、偽の赤は出さない）。
        同じ作り手（ブロック・スクリプト）の節はまとめて見る。読まない欄は UNREAD_OUTPUTS に理由つきで名指す（減らす方向だけ）"""
        doc = line()
        text = (LINE / "darkfactory.yaml").read_text(encoding="utf-8")
        nodes = {n["id"]: n for n in doc["nodes"]}
        maker = {nid: n.get("include") or n.get("script") or nid for nid, n in nodes.items()}
        named, whole = collections.defaultdict(set), set()
        for m in OUTPUT_REF.finditer(text):
            if m.group(1) in nodes:
                (named[maker[m.group(1)]].add(m.group(2)) if m.group(2) else whole.add(maker[m.group(1)]))
        pys = [(p, p.read_text(encoding="utf-8", errors="replace")) for p in sorted(ROOT.rglob("*.py"))
               if p.relative_to(ROOT).parts[0] != "tests" and "graphloops" not in p.relative_to(ROOT).parts]

        def read_elsewhere(field, own):
            lit = re.compile(r"[\"']" + re.escape(field) + r"[\"']")
            return any(p.relative_to(ROOT).parts[0] != own and lit.search(t) for p, t in pys)
        unread = {}
        for nid, n in nodes.items():
            if nid == doc["returns"]:
                continue
            fields = _fields(n) or set()
            own = n["include"] if "include" in n else "darkfactory"
            outcome = _exit_node(n["include"])[1].get("outcome_field") if "include" in n else None
            for f in sorted(fields - named[maker[nid]] - {outcome}):
                if maker[nid] in whole and read_elsewhere(f, own):
                    continue
                unread.setdefault(maker[nid], set()).add(f)
        known = {k: v[0] for k, v in UNREAD_OUTPUTS.items()}
        self.assertEqual(unread, known, "読み手の無い出力の欄（読む所を付けるか、出力から消すか、UNREAD_OUTPUTS に理由つきで"
                                        "名指す。読み手を付けた欄は UNREAD_OUTPUTS から消す）")
        for k, (_f, why) in UNREAD_OUTPUTS.items():
            self.assertTrue(why.strip(), k)


class FeaturesOffCase(unittest.TestCase):
    """切る機能と入れる機能（入力 features_off・features_on。持ち主の依頼 2026-10-07: 同じ依頼を機能を替えて回して比べる）:
    check_inputs が語を確かめて語の順の配列にし、start の出口の機能ごとの on・off・auto（entry.feature_words）を線がブロックの
    切り替えの入力へ写す。既定は持ち主の決め 2026-10-08（測りで後の段を変えなかった判定の裏取りは off・事前審査の木は開いた項目が
    2 つ以上の往復だけ＝auto・ほかは on）。名指した語は既定に勝ち、同じ語を両方に名指せば拒む"""
    DEFAULTS = {"fix_lanes": "on", "graph_map": "on", "judge_verify": "off", "review_tree": "auto", "tdd_lanes": "on"}
    # 機能 → (線の節, ブロックの入力の名)（ブロックは on・off の平の入力だけを受け、線の語を知らない）
    WIRING = {"judge_verify": [("judging", "verify")],
              "review_tree": [("planning", "review_tree"), ("replanning", "review_tree")],
              "tdd_lanes": [("fixing", "tdd_lanes"), ("refitting", "tdd_lanes")],
              "fix_lanes": [("fixing", "fix_lanes"), ("refitting", "fix_lanes")],
              "graph_map": []}   # 工程の地図はブロックへ写さず、包みが start の控えを読む（adapter.graph_map_block）

    def check(self, word, key="features_off", **more):
        with tempfile.TemporaryDirectory() as tmp:
            repo = pathlib.Path(tmp)
            (repo / "req.json").write_text(json.dumps([{"where": "a.py", "text": "直す"}]), encoding="utf-8")
            raw = {"request": "req.json", **more} if word is None else {"request": "req.json", key: word, **more}
            return entry.check_inputs(raw, repo)[key]

    def test_default_judge_verify_off_review_tree_auto(self):
        self.assertEqual(self.check(None), [])
        self.assertEqual(self.check("  "), [])
        self.assertEqual(self.check(None, "features_on"), [])
        self.assertEqual(entry.feature_words([]), self.DEFAULTS)
        self.assertEqual(entry.feature_words([], []), self.DEFAULTS)
        self.assertEqual(entry.features_part([]), "機能: judge_verify off・review_tree auto")

    def test_words_are_split_sorted_and_deduplicated(self):
        self.assertEqual(self.check("tdd_lanes,judge_verify tdd_lanes、fix_lanes"), ["fix_lanes", "judge_verify", "tdd_lanes"])
        self.assertEqual(self.check("review_tree,judge_verify review_tree", "features_on"), ["judge_verify", "review_tree"])
        got = entry.feature_words(["review_tree"])
        self.assertEqual(got, {**self.DEFAULTS, "review_tree": "off"})
        self.assertEqual(entry.features_part(["judge_verify", "review_tree"]), "機能: judge_verify off・review_tree off")

    def test_old_off_words_still_mean_off(self):
        """前からの入力 features_off=judge_verify（既定と同じ off）は拒まずに off のまま"""
        self.assertEqual(self.check("judge_verify"), ["judge_verify"])
        self.assertEqual(entry.feature_words(["judge_verify"])["judge_verify"], "off")

    def test_named_words_beat_defaults(self):
        """features_on は既定の off・auto を on にし、features_off は既定の auto を off にする（名指した語が既定に勝つ）"""
        got = entry.feature_words([], ["judge_verify", "review_tree"])
        self.assertEqual(got, {k: "on" for k in entry.FEATURES})
        self.assertEqual(entry.features_part([], ["judge_verify", "review_tree"]), "機能: 全部 on")
        self.assertEqual(entry.feature_words(["tdd_lanes"], ["judge_verify"]),
                         {**self.DEFAULTS, "judge_verify": "on", "tdd_lanes": "off"})
        self.assertEqual(entry.features_part(["tdd_lanes"], ["judge_verify"]), "機能: review_tree auto・tdd_lanes off")
        self.assertEqual(entry.feature_words([], ["fix_lanes"]), self.DEFAULTS)   # 既定で on の語を入れても同じ

    def test_same_word_in_both_is_refused(self):
        with self.assertRaises(entry.InputRefused) as cm:
            self.check("judge_verify,tdd_lanes", features_on="judge_verify")
        self.assertIn("features_on", str(cm.exception))
        self.assertIn("features_off", str(cm.exception))
        self.assertIn("judge_verify", str(cm.exception))
        self.assertNotIn("tdd_lanes", str(cm.exception))

    def test_unknown_word_is_refused_before_the_board(self):
        for key in ("features_off", "features_on"):
            with self.subTest(key), self.assertRaises(entry.InputRefused) as cm:
                self.check("judge_verify,hole_labels", key)
            self.assertIn(key, str(cm.exception))
            self.assertIn("hole_labels", str(cm.exception))
            self.assertIn("judge_verify", str(cm.exception))   # 名指せる語を並べる

    def test_features_on_of_reads_any_board(self):
        """features_on_of（canary_check がどの版の盤面も読む口）: features_on の欄の無い前の版の控えは、その版の既定（全部 on）で
        読む"""
        old = {"features_off": ["tdd_lanes"]}
        self.assertEqual(entry.features_on_of(old), ["judge_verify", "review_tree"])
        self.assertEqual(entry.features_on_of({"features_off": ["judge_verify"]}), ["review_tree"])
        self.assertEqual(entry.features_on_of({"features_off": [], "features_on": []}), [])
        self.assertEqual(entry.features_cut([], []), ["judge_verify"])
        self.assertEqual(entry.features_cut(["tdd_lanes"], ["judge_verify"]), ["tdd_lanes"])

    def test_resume_with_other_features_is_refused(self):
        """呼び直しで切る機能・入れる機能を替えない"""
        self.assertEqual(entry._resumed_features({"features_off": ["tdd_lanes"], "features_on": []}, ["tdd_lanes"], []), [])
        entry._resumed_features({"features_off": [], "features_on": []}, [], [])
        entry._resumed_features({"features_off": [], "features_on": ["judge_verify"]}, [], ["judge_verify"])
        for prev, off, on in (({"features_off": ["tdd_lanes"], "features_on": []}, [], []),
                              ({"features_off": [], "features_on": []}, ["fix_lanes"], []),
                              ({"features_off": [], "features_on": ["judge_verify"]}, [], []),
                              ({"features_off": [], "features_on": []}, [], ["review_tree"])):
            with self.subTest(prev=prev, off=off, on=on), self.assertRaises(entry.InputRefused) as cm:
                entry._resumed_features(prev, off, on)
            self.assertIn("features_o", str(cm.exception))

    def test_line_wires_each_feature_to_a_block_switch(self):
        doc = line()
        nodes = {n["id"]: n for n in doc["nodes"]}
        for key in ("features_off", "features_on"):
            self.assertEqual(doc["inputs"][key].get("default"), "")
            self.assertEqual(nodes["start"]["with"][key], f"$INPUTS.{key}")
        props = nodes["start"]["output_format"]["properties"]
        self.assertEqual(set(self.WIRING), set(entry.FEATURES))
        for name in entry.FEATURES:
            with self.subTest(name):
                words = ["on", "off", "auto"] if self.DEFAULTS[name] == "auto" else ["on", "off"]
                self.assertEqual(props[name], {"type": "string", "enum": words})
                for nid, key in self.WIRING[name]:
                    self.assertEqual(nodes[nid]["with"].get(key), f"$start.output.{name}", f"{nid}.{key}")
                    block = load(ROOT / nodes[nid]["include"] / f"{nodes[nid]['include']}.yaml")
                    self.assertEqual(block["inputs"][key].get("default"), "", "ブロックの既定は空（on＝今どおり）")

    def test_fixture_may_change_features(self):
        """固定材料から始める run は切る機能を替えて比べてよい（腕と同じく今の値にする欄）"""
        import fixture
        self.assertIn("features_off", fixture.CURRENT)
        self.assertIn("features_on", fixture.CURRENT)


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
