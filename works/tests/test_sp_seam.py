"""借りる superpowers の照合と包みの部品（.shared/core/spseam.py）の検査（FAST: 一時の置き場の偽の版のフォルダを読むだけ）。

- wrapped_files・pin_of・pin_problems: 版のフォルダの包むファイル（借りるスキルの下の全ファイル・部品・LICENSE）の sha256 を
  固定（pin）と比べ、違う・無い・余計なファイルをパスの順に名指す。Claude Code が版のフォルダに置く印（.in_use・.orphaned_at）と
  .DS_Store は数えない
- paragraph・para_sha256: 錨（決まりの根拠の引用）を含む行がちょうど 1 行の時だけ、その段落を返す
- contract_problems: 錨・読み替えの決まり・穴（prompt の型の [名]）・出口の語・固定に無いファイルの破れを節ごとに名指す
- fill・word: 部品の型の穴を全部埋める（固定の sha256 を先に確かめる）・出口の語を works の語に読む（無い語は推さない）
"""
import json
import os
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
        for want in ("tdd: 錨 SUITE「means the project's suite」の段落が固定の時と違う", f"tdd: 錨 ASK「nope」が {TDD} に無い",
                     "tdd: 読み替えの決まり ASK が unattended.md に無い",
                     f"implementer: 穴 [REPORT_FILE] が {IMPL} の prompt の本文に無い", "implementer: 語 SKIPPED",
                     "implementer: skills/x/y.md が pin.files に無い", "implementer: ファイル skills/x/y.md が無い"):
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
        got = spseam.fill("implementer", {"[BRIEF_FILE]": "[X_Y]", "[directory]": "w"}, src, item, seams)
        self.assertIn("Read your task brief first: [X_Y]\n", got)          # 値の中の角括弧は置き換えも残りの検査もしない
        (src / IMPL).write_text(IMPL_TEXT + "more\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "固定"):
            spseam.fill("implementer", {"[BRIEF_FILE]": "x", "[directory]": "y"}, src, item, seams)
        (src / IMPL).write_text(IMPL_TEXT.replace("[directory]\n", "[directory] [EXTRA]\n"), encoding="utf-8")
        item = {**ITEM, "pin": spseam.pin_of(src, ITEM, "1.0.0", None, "2026-10-02")}   # 固定し直す: 埋め残しだけが残る
        with self.assertRaisesRegex(ValueError, r"\[EXTRA\]"):
            spseam.fill("implementer", {"[BRIEF_FILE]": "x", "[directory]": "y"}, src, item, seams)

    def test_bracketed_tokens_outside_placeholders_and_literals_are_named_and_refused(self):
        """型の本文の角括弧の語は、どれも穴（placeholders）か埋めない語（literals）。小文字の語（[task name] の類い）も数える。
        どちらでもない語は contract_problems が名指し、fill は ValueError。本文に無い literals も名指す。literals は空白の続きを
        1 つの空白にして比べる（行をまたぐ語も 1 行で書ける）"""
        text = IMPL_TEXT.replace("[directory]\n", "[directory] [task name] [Approved |\n      Needs fixes]\n")
        src = make_version(self.tmp / "1.0.0", {TDD: TDD_TEXT, IMPL: text})
        item = {**ITEM, "pin": spseam.pin_of(src, ITEM, "1.0.0", None, "2026-10-02")}
        seams = {"implementer": {"use_as": "prompt", "files": [IMPL], "anchors": [], "words": {},
                                 "placeholders": ["[BRIEF_FILE]", "[directory]"],
                                 "literals": ["[Approved | Needs fixes]", "[gone]"]}}
        got = spseam.contract_problems(src, item, seams, "")
        self.assertEqual(got, [f"implementer: 穴でも literals でもない角括弧の語 [task name] が {IMPL} の prompt の本文に在る",
                               f"implementer: literals [gone] が本文に無い（{IMPL} の prompt）"])
        with self.assertRaisesRegex(ValueError, r"\[task name\]"):
            spseam.fill("implementer", {"[BRIEF_FILE]": "x", "[directory]": "y"}, src, item, seams)
        seams["implementer"]["placeholders"].append("[task name]")
        seams["implementer"]["literals"].remove("[gone]")
        self.assertEqual(spseam.contract_problems(src, item, seams, ""), [])
        got = spseam.fill("implementer", {"[BRIEF_FILE]": "x", "[directory]": "[lower case]", "[task name]": "t"}, src, item, seams)
        self.assertIn("[lower case] t [Approved |", got)             # 値の中の角括弧と literals は埋め残しに数えない

    def test_anchor_found_twice_is_named(self):
        src = make_version(self.tmp / "1.0.0", {TDD: TDD_TEXT + "Ask your human partner.\n", IMPL: IMPL_TEXT})
        item = {**ITEM, "pin": spseam.pin_of(src, ITEM, "1.0.0", None, "2026-10-02")}
        seams = {"tdd": {"use_as": "skill", "files": [TDD], "words": {},
                         "anchors": [{"rule": "ASK", "file": TDD, "quote": "Ask your human partner.", "para_sha256": "0" * 64}]}}
        self.assertEqual(spseam.contract_problems(src, item, seams, "## ASK 聞かない\n"),
                         [f"tdd: 錨 ASK「Ask your human partner.」が {TDD} に 2 回在る"])

    def test_anchor_file_must_be_pinned(self):
        other = "skills/brainstorming/SKILL.md"
        src = make_version(self.tmp / "1.0.0", {TDD: TDD_TEXT, IMPL: IMPL_TEXT, other: "Run it.\n"})
        item = {**ITEM, "pin": spseam.pin_of(src, ITEM, "1.0.0", None, "2026-10-02")}
        seams = {"tdd": {"use_as": "skill", "files": [TDD], "words": {},
                         "anchors": [{"rule": "RUN", "file": other, "quote": "Run it.", "para_sha256": spseam.para_sha256("Run it.\n", "Run it.")}]}}
        got = spseam.contract_problems(src, item, seams, "## RUN 回す\n")
        self.assertEqual(len(got), 1)
        self.assertIn(f"tdd: 錨 RUN の {other} が pin.files に無い", got[0])

    def test_paths_outside_the_version_folder_are_named_not_read(self):
        (self.tmp / "outside.md").write_text("Run it.\n", encoding="utf-8")
        src = make_version(self.tmp / "1.0.0", {TDD: TDD_TEXT, IMPL: IMPL_TEXT})
        absolute = str(self.tmp / "outside.md")
        item = {**ITEM, "parts": [IMPL, "../outside.md", absolute]}
        item["pin"] = spseam.pin_of(src, item, "1.0.0", None, "2026-10-02")
        self.assertEqual(sorted(item["pin"]["files"]), [IMPL, TDD])          # 外は数えない
        got = spseam.pin_problems(src, item)
        self.assertEqual(sorted(g.split(": ")[0] for g in got), sorted(["../outside.md", absolute]))
        self.assertTrue(all("版のフォルダの外を指す" in g for g in got), got)
        item["pin"]["files"]["../outside.md"] = "0" * 64                    # 固定の鍵が外を指す
        self.assertEqual(len(spseam.pin_problems(src, item)), 2)
        item = {**ITEM, "pin": spseam.pin_of(src, ITEM, "1.0.0", None, "2026-10-02")}
        seams = {"tdd": {"use_as": "skill", "files": [TDD, "../outside.md"], "words": {},
                         "anchors": [{"rule": "RUN", "file": absolute, "quote": "Run it.", "para_sha256": "0" * 64}]},
                 "implementer": {"use_as": "prompt", "files": ["../outside.md"], "placeholders": [], "words": {}}}
        got = "\n".join(spseam.contract_problems(src, item, seams, "## RUN 回す\n"))
        self.assertIn("tdd: ../outside.md が版のフォルダの外を指す", got)
        self.assertIn(f"tdd: 錨 RUN の {absolute} が版のフォルダの外を指す", got)
        self.assertIn("implementer: ../outside.md が版のフォルダの外を指す", got)
        self.assertNotIn("段落", got)                                          # 外のファイルは読まない
        with self.assertRaisesRegex(ValueError, "外を指す"):
            spseam.fill("implementer", {}, src, item, seams)

    def test_symlinks_are_named_not_followed(self):
        (self.tmp / "outside").mkdir()
        (self.tmp / "outside" / "x.md").write_text("x\n", encoding="utf-8")
        src = make_version(self.tmp / "1.0.0", {TDD: TDD_TEXT, IMPL: IMPL_TEXT})
        item = {**ITEM, "pin": spseam.pin_of(src, ITEM, "1.0.0", None, "2026-10-02")}
        (src / "skills/test-driven-development/link.md").symlink_to(self.tmp / "outside" / "x.md")
        (src / "skills/test-driven-development/linkdir").symlink_to(self.tmp / "outside", target_is_directory=True)
        self.assertNotIn("skills/test-driven-development/link.md", spseam.wrapped_files(src, item))
        got = spseam.pin_problems(src, item)
        self.assertEqual([g.split(": ")[0] for g in got],
                         ["skills/test-driven-development/link.md", "skills/test-driven-development/linkdir"])
        self.assertTrue(all("symlink が在る" in g for g in got), got)
        seams = {"implementer": {"use_as": "prompt", "files": [IMPL], "placeholders": [], "words": {}}}
        (src / IMPL).unlink()
        (src / IMPL).symlink_to(self.tmp / "outside" / "x.md")
        self.assertIn(f"{IMPL}: symlink が在る", "\n".join(spseam.pin_problems(src, item)))
        with self.assertRaisesRegex(ValueError, "symlink"):
            spseam.fill("implementer", {}, src, item, seams)

    def test_paragraph_splits_only_on_newline(self):
        text = "a\n\nfoo bar quote\x0cmore\nnext\n\nz\n"
        self.assertEqual(spseam.paragraph(text, "quote"), "foo bar quote\x0cmore\nnext")

    def test_word_maps_known_and_refuses_unknown(self):
        seams = {"implementer": {"words": {"DONE": "done", "NEEDS_CONTEXT": "divergence"}}}
        self.assertEqual(spseam.word("implementer", "NEEDS_CONTEXT", seams), "divergence")
        with self.assertRaises(ValueError):
            spseam.word("implementer", "MAYBE", seams)


    def test_word_must_be_a_whole_word(self):
        """出口の語は語として在ること。DONE は DONE_WITH_CONCERNS の中に数えない"""
        only_long = IMPL_TEXT.replace("DONE | DONE_WITH_CONCERNS", "DONE_WITH_CONCERNS")
        src = make_version(self.tmp / "1.0.0", {TDD: TDD_TEXT, IMPL: only_long})
        item = {**ITEM, "pin": spseam.pin_of(src, ITEM, "1.0.0", None, "2026-10-02")}
        seams = {"implementer": {"use_as": "prompt", "files": [IMPL], "anchors": [], "placeholders": ["[BRIEF_FILE]", "[directory]"],
                                 "words": {"DONE": "done", "DONE_WITH_CONCERNS": "done", "BLOCKED": "divergence"}}}
        got = spseam.seam_problems(src, item, seams, "")
        self.assertEqual([g for g in got if "語 " in g], [f"implementer: 語 DONE が {IMPL} に無い"])

    def test_seam_problems_leave_pin_lines_to_pin_problems(self):
        """contract_problems は pin_problems と seam_problems をこの順につないだ物。seam_problems は固定との食い違いを含まない"""
        src = make_version(self.tmp / "1.0.0", {TDD: TDD_TEXT, IMPL: IMPL_TEXT})
        item = {**ITEM, "pin": spseam.pin_of(src, ITEM, "1.0.0", None, "2026-10-02")}
        seams = {"tdd": {"use_as": "skill", "files": [TDD], "words": {}, "anchors": []}}
        (src / TDD).write_text("changed\n", encoding="utf-8")
        pp = spseam.pin_problems(src, item)
        sp = spseam.seam_problems(src, item, seams, "")
        self.assertTrue(pp)
        self.assertFalse(any("中身が固定と違う" in ln for ln in sp))
        self.assertEqual(spseam.contract_problems(src, item, seams, ""), pp + sp)

    def test_pin_problems_names_listed_files_missing_from_the_pin(self):
        """借りる一覧のスキルの SKILL.md と部品は pin.files に在るべき。無ければ（手元にも無くても）名指す"""
        src = make_version(self.tmp / "1.0.0", {TDD: TDD_TEXT, IMPL: IMPL_TEXT})
        item = {**ITEM, "pin": spseam.pin_of(src, ITEM, "1.0.0", None, "2026-10-02")}
        wider = dict(item, skills=[*item["skills"], "brainstorming"], parts=[*item["parts"], "skills/x/part.md"])
        why = "借りる一覧（borrow.json の skills・parts）が名指すのに、固定（pin.files）にその sha256 が無い（dev/toolset.py vendor で写し直す）"
        self.assertEqual(spseam.pin_problems(src, wider),
                         [f"skills/brainstorming/SKILL.md: {why}",
                          f"skills/x/part.md: {why}"])

    def test_copy_problems_names_absent_listed_files_and_skips_paths_under_bad_dirs(self):
        """写し元の版のフォルダに無い借りる一覧の SKILL.md と部品を、vendor の場面の語でパスの順に名指す。
        symlink のスキルのフォルダは bad の行だけ。その下の SKILL.md を『無い』とは名指さない"""
        src = make_version(self.tmp / "1.0.0", {TDD: TDD_TEXT, IMPL: IMPL_TEXT})
        wider = {**ITEM, "skills": [*ITEM["skills"], "brainstorming"], "parts": [*ITEM["parts"], "skills/x/part.md"]}
        got = spseam.copy_problems(src, wider)
        absent = "写し元の版のフォルダに無い"
        self.assertEqual([g.split(": ")[0] for g in got], ["skills/brainstorming/SKILL.md", "skills/x/part.md"])
        self.assertTrue(all(g.split(": ", 1)[1].startswith(absent) for g in got), got)
        self.assertFalse(any(TDD in g or IMPL in g for g in got), got)
        self.assertFalse(any("pin.files" in g or "dev/toolset.py vendor で写し直す" in g for g in got), got)
        if os.name != "nt":
            (self.tmp / "outside").mkdir()
            (self.tmp / "outside" / "SKILL.md").write_text("x\n", encoding="utf-8")
            (src / "skills" / "linked").symlink_to(self.tmp / "outside", target_is_directory=True)
            got = spseam.copy_problems(src, {**ITEM, "skills": [*ITEM["skills"], "linked"]})
            self.assertIn("skills/linked: symlink が在る（たどらない）", got)
            self.assertFalse(any(g.startswith("skills/linked/SKILL.md") for g in got), got)


if __name__ == "__main__":
    unittest.main()
