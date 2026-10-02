"""借りる superpowers の照合と包みの部品（.shared/core/spseam.py）の検査（FAST: 一時の置き場の偽の版のフォルダを読むだけ）。

- wrapped_files・pin_of・pin_problems: 版のフォルダの包むファイル（借りるスキルの下の全ファイル・部品・LICENSE）の sha256 を
  固定（pin）と比べ、違う・無い・余計なファイルをパスの順に名指す。Claude Code が版のフォルダに置く印（.in_use・.orphaned_at）と
  .DS_Store は数えない
- paragraph・para_sha256: 錨（決まりの根拠の引用）を含む行がちょうど 1 行の時だけ、その段落を返す
- contract_problems: 錨・読み替えの決まり・穴（prompt の型の [名]）・出口の語・固定に無いファイルの破れを節ごとに名指す
- fill・word: 部品の型の穴を全部埋める（固定の sha256 を先に確かめる）・出口の語を works の語に読む（無い語は推さない）
"""
import json
import pathlib
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
CORE = ROOT / ".shared" / "core"
sys.dont_write_bytecode = True
sys.path.insert(0, str(CORE))

import spseam  # noqa: E402

TDD = "skills/test-driven-development/SKILL.md"
IMPL = "skills/subagent-driven-development/implementer-prompt.md"
TDD_TEXT = "# TDD\n\nRun it.\n\n**\"Other tests\" means the project's suite, not just your file.** A\nlong line\n\nAsk your human partner.\n"
IMPL_TEXT = ("# Implementer\n\n```\nSubagent (general-purpose):\n  model: [MODEL]\n  prompt: |\n    Read your task brief first: [BRIEF_FILE]\n"
             "    Work from: [directory]\n    - **Status:** DONE | DONE_WITH_CONCERNS | BLOCKED | NEEDS_CONTEXT\n```\n")
ITEM = {"skills": ["test-driven-development"], "parts": ["skills/subagent-driven-development/implementer-prompt.md"],
        "licence_file": "LICENSE"}


def make_version(base: pathlib.Path, files: dict[str, str]) -> pathlib.Path:
    """偽の版のフォルダ base に files（{相対パス: 中身}）を書いて base を返す"""
    for rel, text in files.items():
        p = base / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
    return base


class SeamCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = pathlib.Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_wrapped_files_and_pin_problems(self):
        src = make_version(self.tmp / "1.0.0", {TDD: TDD_TEXT, IMPL: IMPL_TEXT, "LICENSE": "MIT License\n",
                                                "skills/brainstorming/SKILL.md": "x"})
        item = {**ITEM, "pin": spseam.pin_of(src, ITEM, "1.0.0", None, "2026-10-02")}
        self.assertEqual(sorted(item["pin"]["files"]), ["LICENSE", IMPL, TDD])   # 借りないスキルは数えない
        self.assertEqual(spseam.pin_problems(src, item), [])
        (src / TDD).write_text("changed\n", encoding="utf-8")
        (src / "skills/test-driven-development/new.md").write_text("n\n", encoding="utf-8")
        (src / IMPL).unlink()
        got = spseam.pin_problems(src, item)
        self.assertEqual([g.split(":")[0] for g in got], [IMPL, TDD, "skills/test-driven-development/new.md"])
        self.assertIn("固定に在るのに手元に無い", got[0]); self.assertIn("中身が固定と違う", got[1]); self.assertIn("固定に無いファイル", got[2])

    def test_pin_ignores_markers(self):
        src = make_version(self.tmp / "1.0.0", {TDD: TDD_TEXT, IMPL: IMPL_TEXT})
        item = {**ITEM, "pin": spseam.pin_of(src, ITEM, "1.0.0", None, "2026-10-02")}
        for rel in ("skills/test-driven-development/.DS_Store", ".in_use/4242", "skills/test-driven-development/.in_use/1", ".orphaned_at"):
            (src / rel).parent.mkdir(parents=True, exist_ok=True); (src / rel).write_text("x", encoding="utf-8")
        self.assertEqual(spseam.pin_problems(src, item), [])

    def test_paragraph_needs_exactly_one_line(self):
        self.assertEqual(spseam.paragraph(TDD_TEXT, "means the project's suite"),
                         "**\"Other tests\" means the project's suite, not just your file.** A\nlong line")
        self.assertIsNone(spseam.paragraph(TDD_TEXT + "Ask your human partner.\n", "Ask your human partner."))
        self.assertIsNone(spseam.paragraph(TDD_TEXT, "not in the text"))

    def test_contract_problems_names_each_break(self):
        src = make_version(self.tmp / "1.0.0", {TDD: TDD_TEXT, IMPL: IMPL_TEXT})
        item = {**ITEM, "pin": spseam.pin_of(src, ITEM, "1.0.0", None, "2026-10-02")}
        seams = {"tdd": {"use_as": "skill", "files": [TDD], "applies": ["a"], "not_applies": ["b"], "words": {},
                         "anchors": [{"rule": "SUITE", "file": TDD, "quote": "means the project's suite",
                                      "para_sha256": spseam.para_sha256(TDD_TEXT, "means the project's suite")}]},
                 "implementer": {"use_as": "prompt", "files": [IMPL], "applies": ["a"], "not_applies": ["b"], "anchors": [],
                                 "placeholders": ["[BRIEF_FILE]", "[directory]"], "words": {"DONE": "done", "BLOCKED": "divergence"}}}
        overlay = "## SUITE 一式\n"
        self.assertEqual(spseam.contract_problems(src, item, seams, overlay), [])
        broken = json.loads(json.dumps(seams))
        broken["tdd"]["anchors"][0]["para_sha256"] = "0" * 64                     # 段落が変わった
        broken["tdd"]["anchors"].append({"rule": "ASK", "file": TDD, "quote": "nope", "para_sha256": "0" * 64})   # 引用が無い
        broken["implementer"]["placeholders"].append("[REPORT_FILE]")              # 穴が無い
        broken["implementer"]["words"]["SKIPPED"] = "x"                            # 語が無い
        broken["implementer"]["files"].append("skills/x/y.md")                     # 固定に無いファイル
        got = "\n".join(spseam.contract_problems(src, item, broken, overlay))
        for want in ("tdd: 錨 SUITE", "段落が固定の時と違う", "tdd: 錨 ASK", "が無い", "決まり ASK が unattended.md に無い",
                     "implementer: 穴 [REPORT_FILE]", "implementer: 語 SKIPPED", "implementer: skills/x/y.md が pin.files に無い"):
            self.assertIn(want, got)

    def test_fill_replaces_every_placeholder_and_checks_the_pin(self):
        src = make_version(self.tmp / "1.0.0", {TDD: TDD_TEXT, IMPL: IMPL_TEXT})
        item = {**ITEM, "pin": spseam.pin_of(src, ITEM, "1.0.0", None, "2026-10-02")}
        seams = {"implementer": {"use_as": "prompt", "files": [IMPL], "placeholders": ["[BRIEF_FILE]", "[directory]"], "words": {}}}
        got = spseam.fill("implementer", {"[BRIEF_FILE]": "/b/brief-1.md", "[directory]": "/w"}, src, item, seams)
        self.assertTrue(got.startswith("Read your task brief first: /b/brief-1.md\nWork from: /w\n"))
        self.assertNotIn("[MODEL]", got); self.assertNotIn("Subagent", got)     # 型の枠は本文に入らない
        for values in ({"[BRIEF_FILE]": "x"}, {"[BRIEF_FILE]": "x", "[directory]": "y", "[REPORT_FILE]": "z"}):
            with self.subTest(values), self.assertRaises(ValueError):
                spseam.fill("implementer", values, src, item, seams)
        (src / IMPL).write_text(IMPL_TEXT + "more\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "固定"):
            spseam.fill("implementer", {"[BRIEF_FILE]": "x", "[directory]": "y"}, src, item, seams)

    def test_word_maps_known_and_refuses_unknown(self):
        seams = {"implementer": {"words": {"DONE": "done", "NEEDS_CONTEXT": "divergence"}}}
        self.assertEqual(spseam.word("implementer", "NEEDS_CONTEXT", seams), "divergence")
        with self.assertRaises(ValueError):
            spseam.word("implementer", "MAYBE", seams)


if __name__ == "__main__":
    unittest.main()
