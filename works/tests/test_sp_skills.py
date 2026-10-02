"""superpowers（Claude Code のプラグインのスキル集）から借りるスキルの一覧と、借りた物を包む節（seams.json）の契約と、
無人の役のための読み替えの検査。

借りるスキルは、works に写した superpowers（.shared/borrow/superpowers/<版>/）から dev/toolset.py が隔離した設定の skills/ へ写す。
写しの版・commit・ファイルごとの sha256 は borrow.json の superpowers.pin に固定し、入れる前に写しのバイトを固定と照合する
（利用者が Claude Code に入れた版は run に使わない）。隔離した設定への写し入れの検査は tests/test_toolset.py（偽の利用者の設定で回す）。

- 写し（VendoredCopyCase）: works は superpowers の使うファイルと LICENSE を .shared/borrow/superpowers/<版>/ に直さずに持つ
  （写しを作り直すのは dev/toolset.py vendor だけ）。写しのバイトは borrow.json の superpowers.pin の sha256 と同じで、
  写しの台帳（COPIED_FROM）と 1 本ずつ合い、版のフォルダは 1 つだけ。
- 節（SeamTableCase）: .shared/borrow/seams.json の 4 つの節（tdd・implementer・task-review・receiving-review）の錨・穴・出口の語が
  本物の写しで成り立つ（spseam.contract_problems）。部品（PARTS）は使わないと決めたスキルのファイルで、ちょうど 1 つの節が包む。
  部品の型の本文の角括弧の語は、どれも節の穴（placeholders）か、埋めない語として節に並べた物（literals）。

- 借りる一覧（BORROW）: .shared/borrow/borrow.json の superpowers.skills と同じで、使わないと決めたスキル（NEVER）・
  読んで参考にするだけのスキル（REFERENCE_ONLY）と重ならない。
- 無人の読み替え（works/.shared/borrow/unattended.md）: 決まりの見出しは 1 つずつ。直す義務の単位の行き先は、修正の決まりの
  正本（.shared/core/writerules/common.md）と同じ行を持つ。持ち主が名指した読み替え（人に聞く・commit・superpowers: の参照・3 回の失敗）
  の決まりが在る。
"""
import json
import os
import pathlib
import re
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.dont_write_bytecode = True
if str(ROOT / ".shared" / "core") not in sys.path:
    sys.path.insert(0, str(ROOT / ".shared" / "core"))
import copyledger  # noqa: E402
import spseam  # noqa: E402

# 持ち主が決めた借りる一覧（2026-09-27）。requesting-code-review の code-reviewer.md はテストの審査役の手引きに使う
BORROW = frozenset({"test-driven-development", "systematic-debugging", "verification-before-completion",
                    "receiving-code-review", "requesting-code-review"})
REFERENCE_ONLY = frozenset({"writing-plans"})       # 読んで参考にするだけ。借りない
# スキルとして読まない（skills: に宣言しない・隔離した設定の skills/ に写さない）。部品のファイルは PARTS に並べ、sha256 で
# 固定して節で包む場合に限り使う
NEVER = frozenset({"brainstorming", "subagent-driven-development", "executing-plans", "using-git-worktrees",
                   "finishing-a-development-branch", "dispatching-parallel-agents", "writing-skills",
                   "using-superpowers", "diagnosing-superpowers"})

# 部品（parts）: スキルとしては使わず、中の文（部品の型）を役の指示書に使うファイル。スキルの名 → ファイルの名
PARTS = {"subagent-driven-development": frozenset({"implementer-prompt.md", "task-reviewer-prompt.md"})}

OVERLAY = ROOT / ".shared" / "borrow" / "unattended.md"
ROUTING_HEAD = "**義務の単位の行き先**: "   # 読み替えと修正の決まりの正本 .shared/core/writerules/common.md が同じ行で持つ決まりの頭


class BorrowListCase(unittest.TestCase):
    def test_borrow_list_is_exactly_the_chosen_skills(self):
        item = json.loads((ROOT / ".shared" / "borrow" / "borrow.json").read_text(encoding="utf-8"))["superpowers"]
        self.assertEqual(set(item["skills"]), set(BORROW))
        self.assertEqual(len(item["skills"]), len(BORROW), "同じスキルを 2 度並べた")
        self.assertFalse(BORROW & (NEVER | REFERENCE_ONLY))


class VendoredCopyCase(unittest.TestCase):
    """本物の写し（.shared/borrow/superpowers/<版>/）を読む。手の直し・足したファイルはここで名指して赤"""

    def test_vendored_copy_matches_ledger_and_pin(self):
        sp = json.loads((ROOT / ".shared/borrow/borrow.json").read_text(encoding="utf-8"))["superpowers"]
        base = ROOT / ".shared" / "borrow" / "superpowers"
        v = sp["pin"]["version"]
        self.assertEqual(sorted(p.name for p in base.iterdir()), sorted([v, "COPIED_FROM"]))   # 写しの版は 1 つだけ
        self.assertEqual(spseam.pin_problems(base / v, sp), [])                                # バイトが pin と同じ
        on_disk = sorted(r.as_posix() for r in (p.relative_to(base / v) for p in (base / v).rglob("*") if p.is_file())
                         if r.name not in spseam.IGNORED and not spseam.MARKERS & set(r.parts))   # spseam と同じく数えない物を除く
        self.assertEqual(on_disk, sorted(sp["pin"]["files"]))                                  # 余分なファイルが無い
        led = copyledger.read(base / "COPIED_FROM")
        self.assertEqual(led.commit, sp["pin"]["commit"])
        self.assertEqual(led.deviations, {})                                                   # 直さない写し
        self.assertEqual(sorted(led.rows), sorted((f"{v}/{f}", f) for f in sp["pin"]["files"]))

    def test_licence_is_mit_with_the_notice(self):
        v = json.loads((ROOT / ".shared/borrow/borrow.json").read_text(encoding="utf-8"))["superpowers"]["pin"]["version"]
        text = (ROOT / ".shared" / "borrow" / "superpowers" / v / "LICENSE").read_text(encoding="utf-8")
        self.assertTrue(text.startswith("MIT License"))
        self.assertIn("Copyright (c) 2025 Jesse Vincent", text)

    @unittest.skipIf(os.name == "nt", "SKIP posix-mode: 実行の権限は POSIX だけ")
    def test_scripts_in_the_copy_keep_exec_bit(self):
        """写しの .sh は実行できる（写しと git の mode 100755 が権限を落とさない）"""
        sp = json.loads((ROOT / ".shared/borrow/borrow.json").read_text(encoding="utf-8"))["superpowers"]
        base = ROOT / ".shared" / "borrow" / "superpowers" / sp["pin"]["version"]
        scripts = [f for f in sp["pin"]["files"] if f.endswith(".sh")]
        self.assertTrue(scripts)
        for f in scripts:
            with self.subTest(f):
                self.assertTrue(os.access(base / f, os.X_OK))


class UnattendedOverlayCase(unittest.TestCase):
    def test_every_rule_is_defined_once(self):
        heads = re.findall(r"^## ([A-Z0-9-]+) ", OVERLAY.read_text(encoding="utf-8"), re.M)
        self.assertTrue(heads)
        self.assertEqual(len(heads), len(set(heads)), heads)

    def test_named_replacements(self):
        """持ち主が名指した読み替え: 人に聞く → not_done か再審・commit → 修正役は commit しない・
        superpowers: の参照 → 無視・3 回の失敗で人と話す → not_done と理由"""
        body = OVERLAY.read_text(encoding="utf-8")
        for rule in ("ASK", "COMMIT", "SP-REF", "THREE-FAILS"):
            self.assertRegex(body, rf"(?m)^## {rule} ")
        for word in ("not_done", "rejudge_requested", "commit しない", "無視"):
            self.assertIn(word, body)

    def test_owed_unit_routing_is_one_rule_in_overlay_and_fix_prompt(self):
        """直す義務の単位の行き先は 1 つの決まり（行 ROUTING）で、読み替えと修正の決まりの正本（.shared/core/writerules/common.md。
        機械が修正役の指示書に組み込む。読み替えより勝つ）が同じ行を持つ。義務の単位を not_done で終わらせない（受け付け
        fix_covers_open_units が拒む）。ASK・THREE-FAILS・POLICY・PUSHBACK と正本の方針の項はその行を名指しし、not_done に
        触れる文は免除か義務の外に限る"""
        fix = (ROOT / ".shared" / "core" / "writerules" / "common.md").read_text(encoding="utf-8")
        body = OVERLAY.read_text(encoding="utf-8")
        lines = [ln for ln in fix.splitlines() if ln.startswith(f"- {ROUTING_HEAD}")]
        self.assertEqual(len(lines), 1, "正本に行き先の行がちょうど 1 つ無い")
        self.assertIn(lines[0], body.splitlines(), "読み替えが正本と同じ行き先の行を持たない")
        for word in ("`changes`", "`rejudge_requested`", "`not_done`", "fork の出どころ"):
            self.assertIn(word, lines[0])
        policy = [ln for ln in fix.splitlines() if ln.startswith("- 人の方針に反するもの")]
        self.assertEqual(len(policy), 1)
        parts = {"正本の方針の項": policy[0]}
        for rule in ("ASK", "THREE-FAILS", "POLICY", "PUSHBACK"):
            m = re.search(rf"^## {rule} .*?(?=^## )", body, re.M | re.S)
            parts[rule] = m.group(0)
        for name, text in parts.items():
            with self.subTest(name):
                self.assertIn(ROUTING_HEAD.strip("*: "), text, "行き先の決まりを名指ししない")
                for sentence in re.split(r"。", text):
                    if "`not_done`" in sentence:
                        self.assertTrue("義務の外" in sentence or "免除" in sentence,
                                        f"not_done に触れる文が免除・義務の外に限っていない: {sentence.strip()}")

    def test_tdd_exception_is_not_decided_by_the_role(self):
        m = re.search(r"^## ASK .*?(?=^## )", OVERLAY.read_text(encoding="utf-8"), re.M | re.S)
        self.assertNotIn("省くなら", m.group(0))
        self.assertIn("役は決めない", m.group(0))


class SeamTableCase(unittest.TestCase):
    def setUp(self):
        self.sp = json.loads((ROOT / ".shared" / "borrow" / "borrow.json").read_text(encoding="utf-8"))["superpowers"]
        self.seams = spseam.load_seams()

    def test_contract_holds_on_the_vendored_copy(self):          # 錨・穴・語を本物の写しに当てる（CI でも回る）
        overlay = OVERLAY.read_text(encoding="utf-8")
        self.assertEqual(spseam.contract_problems(spseam.vendored_dir(self.sp), self.sp, self.seams, overlay), [])

    def test_parts_are_only_the_wrapped_files_of_never_skills(self):
        self.assertEqual(set(self.sp["parts"]), {f"skills/{s}/{f}" for s, fs in PARTS.items() for f in fs})
        self.assertTrue(set(PARTS) <= NEVER)                       # 部品を借りても、スキルとしては使わない
        self.assertFalse(any(p.endswith("/SKILL.md") for p in self.sp["parts"]))
        used = [f for s in self.seams.values() if s["use_as"] == "prompt" for f in s["files"]]
        self.assertEqual(sorted(used), sorted(self.sp["parts"]))   # 部品はちょうど 1 つの節が包む

    def test_every_seam_file_is_pinned_and_skill_seams_use_borrowed_skills(self):
        self.assertEqual(set(self.seams), {"tdd", "implementer", "task-review", "receiving-review"})
        for name, s in self.seams.items():
            with self.subTest(name):
                self.assertTrue(set(s["files"]) <= set(self.sp["pin"]["files"]))
                self.assertTrue(s["applies"] and s["not_applies"] and s["anchors"])
                if s["use_as"] == "skill":
                    self.assertTrue(all(f.split("/")[1] in BORROW for f in s["files"]))
                else:
                    self.assertTrue(s["placeholders"] and s["words"])

    def test_status_words_cover_the_four_and_route_asks_to_divergence(self):
        w = self.seams["implementer"]["words"]
        self.assertEqual(set(w), {"DONE", "DONE_WITH_CONCERNS", "NEEDS_CONTEXT", "BLOCKED"})
        self.assertEqual((w["NEEDS_CONTEXT"], w["BLOCKED"]), ("divergence", "divergence"))

    def test_every_bracketed_token_in_part_bodies_is_a_placeholder_or_listed_literal(self):
        """部品の型の本文の角括弧の語（[task name] の類いの小文字の語も）は、どれも節の穴か埋めない語（literals）。数えるのは
        spseam（contract_problems・fill。版を上げる前の下見も同じ規則）で、ここは本物の写しで破れが無いことと、同じ語を両方に
        並べていないことを見る"""
        overlay = OVERLAY.read_text(encoding="utf-8")
        self.assertEqual(spseam.contract_problems(spseam.vendored_dir(self.sp), self.sp, self.seams, overlay), [])
        for name, s in self.seams.items():
            with self.subTest(name):
                self.assertFalse(set(s.get("placeholders", [])) & set(s.get("literals", [])), "穴と埋めない語の両方に並べた")


class OverlayDeliveryCase(unittest.TestCase):
    """無人の読み替えは、借りたスキルを読める役（道具に Skill を持つ役）の指示書に機械で載る（役への直の指示はスキルに勝つ。
    superpowers の using-superpowers の User Instructions）。盤面は作らず、素材集めの支度（material.prep）の盤面の口を偽物に替えて、
    書かれた指示書を読む（git・子のプロセスなし）"""

    @staticmethod
    def _material():
        import sys
        for p in (ROOT / ".shared" / "core", ROOT / "blk-material" / "lib"):
            if str(p) not in sys.path:
                sys.path.insert(0, str(p))
        import material
        return material

    def _prep(self, role: str) -> str:
        import contextlib
        import tempfile
        from unittest import mock
        material = self._material()
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        d = pathlib.Path(tmp.name)
        board = mock.Mock(dir=d, round=1)
        board.work.side_effect = lambda name: d / name
        board.mark_launched.return_value = {"attempt": 1, "out_path": str(d / "out.json"), "already": False}
        with mock.patch.object(material, "_locked", lambda _d: contextlib.nullcontext()), \
                mock.patch.object(material, "_open", return_value=board), \
                mock.patch.object(material, "_stopped", return_value=None), \
                mock.patch.object(material, "_waiting", return_value={"attempts": 1}), \
                mock.patch.object(material, "_rejects", return_value=[]), \
                mock.patch.object(material, "render", return_value="役の本文\n"):
            got = material.prep(d, role, None, "")
        return pathlib.Path(got["prompt_file"]).read_text(encoding="utf-8")

    def test_skill_role_prompt_carries_unattended_overlay(self):
        """Skill を持つ役（local-review）の指示書は読み替えの全文を含み、Skill を持たない役の指示書は含まない"""
        material = self._material()
        overlay = OVERLAY.read_text(encoding="utf-8")
        self.assertIn("Skill", material.TOOLS["local-review"])
        text = self._prep("local-review")
        self.assertIn("役の本文", text)
        self.assertIn(overlay.strip(), text)
        self.assertNotIn("Skill", material.TOOLS["consistency-bypass"])
        self.assertNotIn(overlay.splitlines()[0], self._prep("consistency-bypass"))

    def test_every_node_that_can_read_skills_is_a_role_that_gets_the_overlay(self):
        """works の YAML の節のうち、借りたスキルを読める節（allowed_tools に Skill か skills: を持つ）は、どれも素材集めの道具の表で
        Skill を持つ役（指示書に読み替えが載る役）。載せる道の無い節を足したら赤"""
        import yaml
        material = self._material()

        def walk(x):
            if isinstance(x, dict):
                if "Skill" in (x.get("allowed_tools") or []) or x.get("skills"):
                    yield x
                for v in x.values():
                    yield from walk(v)
            elif isinstance(x, list):
                for v in x:
                    yield from walk(v)
        found = set()
        for y in sorted(ROOT.glob("*/*.yaml")):    # pack の YAML の集め方は test_yaml_rules と同じ（darkfactory も含む）
            for node in walk(yaml.safe_load(y.read_text(encoding="utf-8"))):
                found.add((y.name, node.get("command") or node.get("id")))
        self.assertTrue(found)
        self.assertEqual({c for _, c in found}, {r for r, t in material.TOOLS.items() if "Skill" in t}, found)


if __name__ == "__main__":
    unittest.main()
