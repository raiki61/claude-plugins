"""superpowers（Claude Code のプラグインのスキル集。MIT）から借りたスキルの写しの検査。

置き場は works/.shared/superpowers/<版>/（版の置き場はちょうど 1 つ）。持ち主が決めた借りる一覧（BORROW）だけを、
プラグインのキャッシュからバイト単位でそのまま写す（写しは直さない。無人の役のための読み替えは別のファイル unattended.md）。

- 写しの元の記録 COPIED_FROM: 1 行目の最初の語が版、2 語目が写した元の置き場（プラグインのキャッシュの根
  ${CLAUDE_CONFIG_DIR:-~/.claude}/plugins/cache/ からの相対パス。機械ごとの絶対パスを持たない）。2 行目から写した
  ファイル（版の置き場からの相対パス）。形は .shared/core/COPIED_FROM と同じ読み方（空行と # の行を除き、ln.split()[0]）。
  graphloops の写しの COPIED_FROM がファイルの hash を持たないので、こちらも持たない。
- バイトの一致: 写しの元が無ければ飛ばさずに赤にする（tests/test_core_copy.py の test_copies_are_byte_identical_to_the_commit
  と同じ扱い。あちらは元の commit を引けなければ git show が失敗して赤になる）。同じ版の superpowers の checkout を
  WORKS_SP_SOURCE に渡せば、そこを元として比べる。
- NOTICE（works/NOTICE）: superpowers が MIT であることと、LICENSE の著作権者の行をそのまま持つ。
- 無人の読み替え（works/.shared/superpowers/unattended.md）: 写しの .md の中で、人か調整役（下請けを起こす親の会話）を
  前提にする言い回しの目印（TRIGGERS）に当たる行を全部、行の索引に 1 行ずつ持つ（パス・行番号・読み替えの決まりの名・
  その行の文そのもの）。索引に無い行・索引にあるのに今の写しに無い行・文が違う行は赤。新しい版の写しが人への問いを
  足したり行を動かしたりすると、ここが赤くなり、読み替えを見直させる。
- 写し入れ（works/dev/skills.sh <Claude の設定の置き場>）: 写しの skills/<名>/ を <置き場>/skills/<名>/ へバイトのまま写す。
  同じ名前の古い物は入れ替え、ほかの名前の物には触らない。dev/archon.sh が隔離した CLAUDE_CONFIG_DIR へ毎回呼ぶ
  （呼ぶことの検査は tests/test_dev.py の test_archon_sh_installs_borrowed_skills）。
"""
import os
import pathlib
import re
import subprocess
import tempfile
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


OVERLAY = SP / "unattended.md"
# 人か調整役を前提にする言い回しの目印（大文字小文字を問わない）。広めに取り、当たっただけで関係の無い行は
# 索引で決まり NA（対象外）に振る。目印を狭めると新しい版の人への問いを見落とすので、狭めるときは理由を書く
TRIGGERS = re.compile(
    r"partner|\bhuman\b|\buser\b|\bask\b|clarif|discuss|approv|permission"
    r"|commit|\bpush\b|\bPR\b|pull request|\bmerge"
    r"|superpowers:|subagent|dispatch|spawn|delegat|\bagents?\b|coordinator"
    r"|\bgh\b|github|\bgit (?:rev-parse|log|diff|show|worktree|merge-base)", re.I)
ROUTING_HEAD = "**義務の単位の行き先**: "   # 読み替えと blk-fix/commands/fix.md が同じ行で持つ決まりの頭
ROW = re.compile(r"^(?P<path>skills/[^ :]+\.md):(?P<line>[0-9]+) \[(?P<rule>[A-Z0-9-]+)\] (?P<text>.*)$")


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


def cache_root():
    """プラグインのキャッシュの根（Claude Code の設定の置き場の plugins/cache）"""
    cfg = os.environ.get("CLAUDE_CONFIG_DIR") or str(pathlib.Path.home() / ".claude")
    return pathlib.Path(cfg) / "plugins" / "cache"


def files_under(base):
    return sorted(p.relative_to(base).as_posix() for p in base.rglob("*") if p.is_file())


class PinnedCopyCase(unittest.TestCase):
    def test_version_dir_matches_copied_from(self):
        version, source, _ = copied_from()
        self.assertEqual(pinned().name, version)
        self.assertEqual(source.name, version, "写しの元の置き場の末尾が版でない")
        self.assertFalse(source.is_absolute(), "写しの元はキャッシュの根からの相対パスで書く（機械ごとの絶対パスを持たない）")

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
        src = pathlib.Path(os.environ.get("WORKS_SP_SOURCE") or cache_root() / source)
        self.assertNotEqual(src.resolve(), pinned().resolve(), "写しそのものを元に渡した（自分と比べて緑になる）")
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


def trigger_lines():
    """写しの .md の目印に当たる行: {(パス, 行番号): 前後の空白を除いた行の文}"""
    base = pinned()
    found = {}
    for f in sorted((base / "skills").rglob("*.md")):
        for i, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
            if TRIGGERS.search(line):
                found[(f.relative_to(base).as_posix(), i)] = line.strip()
    return found


def overlay_rows():
    """行の索引: {(パス, 行番号): (決まりの名, 文)}。同じ行を 2 度書いたら例外"""
    rows = {}
    for ln in OVERLAY.read_text(encoding="utf-8").splitlines():
        m = ROW.match(ln)
        if m:
            key = (m["path"], int(m["line"]))
            if key in rows:
                raise AssertionError(f"索引に同じ行が 2 度ある: {key}")
            rows[key] = (m["rule"], m["text"])
    return rows


class UnattendedOverlayCase(unittest.TestCase):
    def test_triggers_catch_human_asks(self):
        """目印の自己検査: 人への問い・commit・下請け・superpowers の参照の典型を拾い、ただの文は拾わない"""
        for s in ("ask your human partner", "Check with the user first", "commit the fix", "Dispatch a reviewer",
                  "Use the `superpowers:x` skill", "Discuss before continuing", "open a pull request",
                  "Get approval", "BASE=$(git rev-parse HEAD)"):
            with self.subTest(s):
                self.assertTrue(TRIGGERS.search(s))
        for s in ("Write the test first.", "Watch it fail.", "task list", "asking"):
            with self.subTest(s):
                self.assertFalse(TRIGGERS.search(s))

    def test_every_trigger_line_has_a_row_with_its_text(self):
        found = trigger_lines()
        rows = overlay_rows()
        self.assertTrue(found, "目印に 1 行も当たらない（走査の空回り）")
        self.assertEqual(sorted(set(found) - set(rows)), [], "索引に無い目印の行（読み替えを足す）")
        self.assertEqual(sorted(set(rows) - set(found)), [], "索引にあるのに今の写しに目印の行が無い（古い行を消す）")
        for key, text in found.items():
            with self.subTest(f"{key[0]}:{key[1]}"):
                self.assertEqual(rows[key][1], text, "索引の文が写しの行と違う（行が動いたか中身が変わった）")

    def test_every_rule_is_defined_once(self):
        body = OVERLAY.read_text(encoding="utf-8")
        heads = re.findall(r"^## ([A-Z0-9-]+) ", body, re.M)
        self.assertEqual(len(heads), len(set(heads)), heads)
        used = {r for r, _ in overlay_rows().values()}
        self.assertEqual(sorted(used - set(heads)), [], "索引が使う決まりの名に見出しが無い")
        self.assertEqual(sorted(set(heads) - used), [], "どの行にも使わない決まりがある")

    def test_named_replacements(self):
        """持ち主が名指した読み替え: 人に聞く → not_done か再審・commit → 修正役は commit しない・
        superpowers: の参照 → 無視・3 回の失敗で人と話す → not_done と理由"""
        rows = overlay_rows()
        want = {("skills/test-driven-development/SKILL.md", 24): "ASK",
                ("skills/receiving-code-review/SKILL.md", 45): "ASK",
                ("skills/verification-before-completion/SKILL.md", 54): "COMMIT",
                ("skills/systematic-debugging/SKILL.md", 177): "SP-REF",
                ("skills/systematic-debugging/SKILL.md", 210): "THREE-FAILS"}
        for key, rule in want.items():
            with self.subTest(f"{key[0]}:{key[1]}"):
                self.assertEqual(rows[key][0], rule)
        body = OVERLAY.read_text(encoding="utf-8")
        for word in ("not_done", "rejudge_requested", "commit しない", "無視"):
            self.assertIn(word, body)

    def test_owed_unit_routing_is_one_rule_in_overlay_and_fix_prompt(self):
        """直す義務の単位の行き先は 1 つの決まり（行 ROUTING）で、読み替えと修正役の指示書（blk-fix/commands/fix.md。
        読み替えより勝つ）が同じ行を持つ。義務の単位を not_done で終わらせない（受け付け fix_covers_open_units が拒む）。
        ASK・THREE-FAILS・POLICY・PUSHBACK と fix.md の方針の項はその行を名指しし、not_done に触れる文は
        免除か義務の外に限る"""
        fix = (ROOT / "blk-fix" / "commands" / "fix.md").read_text(encoding="utf-8")
        body = OVERLAY.read_text(encoding="utf-8")
        lines = [ln for ln in fix.splitlines() if ln.startswith(f"- {ROUTING_HEAD}")]
        self.assertEqual(len(lines), 1, "fix.md に行き先の行がちょうど 1 つ無い")
        self.assertIn(lines[0], body.splitlines(), "読み替えが fix.md と同じ行き先の行を持たない")
        for word in ("`changes`", "`rejudge_requested`", "`not_done`", "fork の出どころ"):
            self.assertIn(word, lines[0])
        policy = [ln for ln in fix.splitlines() if ln.startswith("- 人の方針に反するもの")]
        self.assertEqual(len(policy), 1)
        parts = {"fix.md の方針の項": policy[0]}
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

    def test_overlay_names_the_pinned_version(self):
        self.assertIn(f"superpowers {pinned().name}", OVERLAY.read_text(encoding="utf-8").split("\n", 3)[2])


def install(dest):
    return subprocess.run(["sh", str(ROOT / "dev" / "skills.sh"), str(dest)], capture_output=True, text=True)


class InstallCase(unittest.TestCase):
    def test_install_copies_every_borrowed_skill_byte_for_byte(self):
        with tempfile.TemporaryDirectory() as tmp:
            r = install(tmp)
            self.assertEqual(r.returncode, 0, r.stderr)
            dest = pathlib.Path(tmp) / "skills"
            self.assertEqual({p.name for p in dest.iterdir()}, set(BORROW))
            for n in BORROW:
                src = pinned() / "skills" / n
                self.assertEqual(files_under(dest / n), files_under(src), n)
                for rel in files_under(src):
                    with self.subTest(f"{n}/{rel}"):
                        a, b = dest / n / rel, src / rel
                        self.assertEqual(a.read_bytes(), b.read_bytes())
                        self.assertFalse(a.is_symlink())
                        self.assertEqual(os.access(a, os.X_OK), os.access(b, os.X_OK))

    def test_install_restores_exec_bit(self):
        """中身が同じでも実行の権限だけずれた写しは直す（diff -r は権限を見ない）"""
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(install(tmp).returncode, 0)
            f = pathlib.Path(tmp) / "skills" / "systematic-debugging" / "find-polluter.sh"
            f.chmod(0o644)
            r = install(tmp)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertTrue(os.access(f, os.X_OK))

    def test_install_refuses_config_that_leaks_into_user_scope(self):
        """settingSources: [user] は置き場の CLAUDE.md・設定・rules・agents・commands・plugins も読ませるので、
        どれかが在れば名前を出して終了コード 2（何も写さない）。借りる一覧の外のスキルが在っても止める"""
        cases = [("CLAUDE.md", "file"), ("settings.json", "file"), ("settings.local.json", "file"),
                 ("rules", "dir"), ("agents", "dir"), ("commands", "dir"), ("plugins", "dir"), ("skills/mine", "dir")]
        for name, kind in cases:
            with self.subTest(name), tempfile.TemporaryDirectory() as tmp:
                p = pathlib.Path(tmp) / name
                if kind == "dir":
                    p.mkdir(parents=True)
                    if name.startswith("skills/"):
                        (p / "SKILL.md").write_text("x\n", encoding="utf-8")
                else:
                    p.write_text("x\n", encoding="utf-8")
                r = install(tmp)
                self.assertEqual(r.returncode, 2, r.stderr)
                self.assertIn(name.split("/")[-1], r.stderr)
                self.assertFalse((pathlib.Path(tmp) / "skills" / "test-driven-development").exists(), "止まる前に写した")
        # 設定でない物（Claude Code が自分で書く状態のファイル）は止めない
        with tempfile.TemporaryDirectory() as tmp:
            for n in ("remote-settings.json", "policy-limits.json"):
                (pathlib.Path(tmp) / n).write_text("{}\n", encoding="utf-8")
            (pathlib.Path(tmp) / "projects").mkdir()
            r = install(tmp)
            self.assertEqual(r.returncode, 0, r.stderr)

    def test_install_replaces_stale_copy(self):
        with tempfile.TemporaryDirectory() as tmp:
            dest = pathlib.Path(tmp) / "skills"
            stale = dest / "test-driven-development"
            stale.mkdir(parents=True)
            (stale / "SKILL.md").write_text("古い\n", encoding="utf-8")
            (stale / "extra.md").write_text("余分\n", encoding="utf-8")
            r = install(tmp)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertEqual(files_under(stale), files_under(pinned() / "skills" / "test-driven-development"))
            self.assertEqual((stale / "SKILL.md").read_bytes(),
                             (pinned() / "skills" / "test-driven-development" / "SKILL.md").read_bytes())
            self.assertEqual(sorted(p.name for p in dest.iterdir()), sorted(BORROW), "作業の一時の置き場が残っている")
            # 2 回目（中身が同じ）も緑で、中身は変わらない
            r = install(tmp)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertEqual(sorted(p.name for p in dest.iterdir()), sorted(BORROW))

    def test_install_usage(self):
        r = subprocess.run(["sh", str(ROOT / "dev" / "skills.sh")], capture_output=True, text=True)
        self.assertEqual(r.returncode, 2)
        self.assertIn("usage: skills.sh", r.stderr)


if __name__ == "__main__":
    unittest.main()
