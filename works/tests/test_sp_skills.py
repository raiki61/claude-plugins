"""superpowers（Claude Code のプラグインのスキル集。MIT）から借りたスキルの写しの検査。

置き場は works/.shared/superpowers/<版>/（版の置き場はちょうど 1 つ）。持ち主が決めた借りる一覧（BORROW）だけを、
プラグインのキャッシュからバイト単位でそのまま写す（写しは直さない。無人の役のための読み替えは別のファイル unattended.md）。

- 写しの元の記録 COPIED_FROM: 1 行目の最初の語が版、2 語目が写した元の置き場（プラグインのキャッシュ）。2 行目から写した
  ファイル（版の置き場からの相対パス）。形は .shared/core/COPIED_FROM と同じ読み方（空行と # の行を除き、ln.split()[0]）。
  graphloops の写しの COPIED_FROM がファイルの hash を持たないので、こちらも持たない。
- バイトの一致: 写しの元が無ければ飛ばさずに赤にする（tests/test_core_copy.py の test_copies_are_byte_identical_to_the_commit
  と同じ扱い。あちらは元の commit を引けなければ git show が失敗して赤になる）。同じ版の superpowers の checkout を
  WORKS_SP_SOURCE に渡せば、そこを元として比べる。
- NOTICE（works/NOTICE）: superpowers が MIT であることと、LICENSE の著作権者の行をそのまま持つ。
"""
import os
import pathlib
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
SP = ROOT / ".shared" / "superpowers"

# 持ち主が決めた借りる一覧（2026-09-27）。requesting-code-review の code-reviewer.md はテストの審査役の手引きに使う
BORROW = frozenset({"test-driven-development", "systematic-debugging", "verification-before-completion",
                    "receiving-code-review", "requesting-code-review"})
REFERENCE_ONLY = frozenset({"writing-plans"})       # 読んで参考にするだけ。写さない
NEVER = frozenset({"brainstorming", "subagent-driven-development", "executing-plans", "using-git-worktrees",
                   "finishing-a-development-branch", "dispatching-parallel-agents", "writing-skills",
                   "using-superpowers", "diagnosing-superpowers"})


def pinned():
    """版の置き場（works/.shared/superpowers/<版>/）。ちょうど 1 つでなければ例外"""
    dirs = sorted(p for p in SP.iterdir() if p.is_dir())
    if len(dirs) != 1:
        raise AssertionError(f"superpowers の版の置き場がちょうど 1 つでない: {[d.name for d in dirs]}")
    return dirs[0]


def copied_from():
    """(版, 写しの元の置き場, 写したファイルの一覧)"""
    lines = (pinned() / "COPIED_FROM").read_text(encoding="utf-8").splitlines()
    head = lines[0].split()
    listed = [ln.split()[0] for ln in lines[1:] if ln.strip() and not ln.startswith("#")]
    return head[0], pathlib.Path(head[1]), listed


def files_under(base):
    return sorted(p.relative_to(base).as_posix() for p in base.rglob("*") if p.is_file())


class PinnedCopyCase(unittest.TestCase):
    def test_version_dir_matches_copied_from(self):
        version, source, _ = copied_from()
        self.assertEqual(pinned().name, version)
        self.assertEqual(source.name, version, "写しの元の置き場の末尾が版でない")

    def test_borrow_list_is_exactly_the_pinned_skills(self):
        names = {p.name for p in (pinned() / "skills").iterdir() if p.is_dir()}
        self.assertEqual(names, set(BORROW))
        self.assertFalse(names & (NEVER | REFERENCE_ONLY))
        for n in names:
            self.assertTrue((pinned() / "skills" / n / "SKILL.md").is_file(), n)

    def test_copied_from_lists_exactly_the_pinned_files(self):
        """写したファイルは全部 COPIED_FROM に並び、並んだ物は全部在る（写しの置き場に余分な物を置かない）"""
        _, _, listed = copied_from()
        on_disk = [f for f in files_under(pinned()) if f != "COPIED_FROM"]
        self.assertEqual(sorted(listed), on_disk)
        self.assertIn("LICENSE", listed)
        self.assertIn("skills/requesting-code-review/code-reviewer.md", listed)

    def test_copy_is_byte_identical_to_the_source(self):
        """写しは元とバイト単位で同じで、実行の権限も同じ。元の借りるスキルのファイルは全部写してある。
        元が無ければ飛ばさずに赤（写しを確かめないまま緑にしない）"""
        version, source, listed = copied_from()
        src = pathlib.Path(os.environ.get("WORKS_SP_SOURCE") or source)
        self.assertTrue((src / "LICENSE").is_file(),
                        f"写しの元が無い（{src}）。superpowers {version} をプラグインのキャッシュに入れ直すか、"
                        f"同じ版の checkout を WORKS_SP_SOURCE に渡す")
        want = ["LICENSE"] + sorted(f"skills/{n}/{f}" for n in BORROW for f in files_under(src / "skills" / n))
        self.assertEqual(sorted(listed), sorted(want))
        for rel in listed:
            with self.subTest(rel):
                a, b = pinned() / rel, src / rel
                self.assertEqual(a.read_bytes(), b.read_bytes())
                self.assertEqual(os.access(a, os.X_OK), os.access(b, os.X_OK), "実行の権限が違う")

    def test_notice_names_mit_and_the_copyright_holder(self):
        holder = next(ln for ln in (pinned() / "LICENSE").read_text(encoding="utf-8").splitlines()
                      if ln.startswith("Copyright"))
        notice = (ROOT / "NOTICE").read_text(encoding="utf-8")
        self.assertIn("superpowers", notice)
        self.assertIn("MIT", notice)
        self.assertIn(holder, notice)
        self.assertIn(f".shared/superpowers/{pinned().name}/LICENSE", notice)


if __name__ == "__main__":
    unittest.main()
