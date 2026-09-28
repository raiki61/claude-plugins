"""写し直しの道具 dev/core-sync.py の検査（sync と --check）。

偽の正本（使い捨ての git に commit を積んだ物。モジュールに 1 回だけ作り、試験は git show で読むだけ）と、
偽の works の置き場（git なし。台帳 5 つと写しだけ）で回す。本物の写し直しはしない。
- --check: 写しが台帳の 1 行目の commit と手直し（COPIED_FROM の ! 行）から作ったバイトと同じで、graphloops を元にする
  4 つの台帳の commit が揃っていれば 0。1 バイトの書き換え・台帳の commit の割れは 1。何も書かない
- sync <rev>: graphloops の 4 つの台帳の写しを <rev> から取り直し、手直しを当て、台帳の 1 行目を替える（changemap の台帳は触らない）。
  手直しが当たらない・import と graph の $ref がたどる物が台帳に無い、のどちらかなら何も書かずに 1
"""
import json
import pathlib
import shutil
import subprocess
import sys
import tempfile
import unittest

import hermetic
from gitkit import git

ROOT = pathlib.Path(__file__).resolve().parents[1]
TOOL = ROOT / "dev" / "core-sync.py"

DEV = {"path": "graphloops/rules/r.py", "old": "SUITE_TIMEOUT = 1800        #", "new": "SUITE_TIMEOUT = 1728000     #",
       "why": "一式 1 回の上限を 20 日に"}

BASE = {
    "graphloops/engine/__init__.py": "",
    "graphloops/engine/a.py": "X = 1\n",
    "graphloops/rules/r.py": "SUITE_TIMEOUT = 1800        # 秒\n",
    "graphloops/graphs/g.json": json.dumps({"nodes": {}}) + "\n",
    "graphloops/prompts/policy.md": "方針 1\n",
    "graphloops/prompts/review-loop/spec.write.md": "仕様 1\n",
    "graphloops/prompts/review-loop/report.md": "報告 1\n",
    "attention/scripts/lib/changemap.py": "TIMEOUT = 15\n",
}
# 台帳の写しのパス（works の根から）と元のパス（正本の根から）
COPIES = {
    ".shared/core/graphloops/engine/__init__.py": "graphloops/engine/__init__.py",
    ".shared/core/graphloops/engine/a.py": "graphloops/engine/a.py",
    ".shared/core/graphloops/rules/r.py": "graphloops/rules/r.py",
    ".shared/core/graphloops/graphs/g.json": "graphloops/graphs/g.json",
    ".shared/core/gl-prompts/prompts/policy.md": "graphloops/prompts/policy.md",
    "blk-spec/prompts/spec.write.md": "graphloops/prompts/review-loop/spec.write.md",
    "blk-report/prompts/review-loop/report.md": "graphloops/prompts/review-loop/report.md",
    ".shared/core/changemap.py": "attention/scripts/lib/changemap.py",
}
GL_LEDGERS = (".shared/core/COPIED_FROM", ".shared/core/gl-prompts/COPIED_FROM",
              "blk-spec/prompts/COPIED_FROM", "blk-report/prompts/COPIED_FROM")

UP = None   # 偽の正本の置き場
REV = {}    # 名 → commit


def _commit(name, files):
    for rel, text in files.items():
        p = UP / rel
        if text is None:
            p.unlink()
            continue
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
    git(UP, "add", "-A")
    git(UP, "commit", "-q", "-m", name)
    REV[name] = git(UP, "rev-parse", "HEAD")


def setUpModule():
    global UP
    home = pathlib.Path(tempfile.mkdtemp(prefix="works-coresync-"))
    UP = home / "up"
    UP.mkdir()
    git(UP, "init", "-q")
    _commit("a", BASE)
    # b: 写しの元が進んだ（手直しの元は残る）
    git(UP, "checkout", "-q", "-b", "b")
    _commit("b", {"graphloops/engine/a.py": "X = 2\n", "graphloops/prompts/policy.md": "方針 2\n",
                  "graphloops/prompts/review-loop/spec.write.md": "仕様 2\n",
                  "graphloops/prompts/review-loop/report.md": "報告 2\n",
                  "graphloops/rules/r.py": "SUITE_TIMEOUT = 1800        # 秒\nY = 1\n"})
    # c: 手直しの元が消えた
    git(UP, "checkout", "-q", "-b", "c", REV["a"])
    _commit("c", {"graphloops/rules/r.py": "SUITE_TIMEOUT = 900  # 秒\n"})
    # d: 写しの .py が台帳に無い物を相対 import する
    git(UP, "checkout", "-q", "-b", "d", REV["a"])
    _commit("d", {"graphloops/engine/a.py": "from .extra import Y\nX = Y\n", "graphloops/engine/extra.py": "Y = 3\n"})
    # e: 写しの graph が台帳に無い物を $ref でたどる
    git(UP, "checkout", "-q", "-b", "e", REV["a"])
    _commit("e", {"graphloops/graphs/g.json": json.dumps({"nodes": {"x": {"$ref": "../blocks/x/block.json"}}}) + "\n",
                  "graphloops/blocks/x/block.json": json.dumps({"id": "x"}) + "\n"})
    git(UP, "checkout", "-q", REV["a"])


def tearDownModule():
    shutil.rmtree(UP.parent, ignore_errors=True)


def make_works(dest):
    """偽の works の置き場を、正本の a の写しで作る（手直しは COPIED_FROM の ! 行）"""
    a = REV["a"][:7]
    ledgers = {
        ".shared/core/COPIED_FROM": [f"{a}  graphloops 0.1.0", "graphloops/engine/__init__.py", "graphloops/engine/a.py",
                                     "graphloops/rules/r.py  # works の手直し 1 か所", "graphloops/graphs/g.json",
                                     "! " + json.dumps(DEV, ensure_ascii=False)],
        ".shared/core/gl-prompts/COPIED_FROM": [f"{a}  graphloops 0.1.0 の指示書", "prompts/policy.md"],
        "blk-spec/prompts/COPIED_FROM": [f"{a}  graphloops 0.1.0 の仕様の道の指示書", "spec.write.md"],
        "blk-report/prompts/COPIED_FROM": [f"{a}  graphloops 0.1.0 の最終報告の指示書", "review-loop/report.md"],
        ".shared/core/COPIED_FROM.changemap": [f"{a}  attention の変更の地図", "changemap.py  attention/scripts/lib/changemap.py"],
    }
    for rel, lines in ledgers.items():
        p = dest / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    for rel, src in COPIES.items():
        text = BASE[src]
        if src == DEV["path"]:
            text = text.replace(DEV["old"], DEV["new"])
        p = dest / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")


def snapshot(d):
    return {str(p.relative_to(d)): p.read_bytes() for p in sorted(d.rglob("*")) if p.is_file()}


def run(works, *args):
    r = subprocess.run([sys.executable, str(TOOL), "--works", str(works), "--upstream", str(UP), *args],
                       capture_output=True, text=True, encoding="utf-8", env=hermetic.child_env(PYTHONDONTWRITEBYTECODE="1"))
    return r.returncode, r.stdout + r.stderr


class CoreSyncCheckCase(unittest.TestCase):
    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp(prefix="works-coresync-w-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.w = self.tmp / "works"
        make_works(self.w)

    def test_check_passes_on_this_repo(self):
        """このリポジトリの写し（正本は同じリポジトリの根）で --check が 0"""
        r = subprocess.run([sys.executable, str(TOOL), "--check"], capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_check_fails_on_one_byte_change_and_writes_nothing(self):
        rc, out = run(self.w, "--check")
        self.assertEqual(rc, 0, out)
        p = self.w / ".shared/core/graphloops/engine/a.py"
        p.write_text("X = 9\n", encoding="utf-8")
        before = snapshot(self.w)
        rc, out = run(self.w, "--check")
        self.assertEqual(rc, 1, out)
        self.assertIn("graphloops/engine/a.py", out)
        self.assertEqual(snapshot(self.w), before, "--check が書いた")

    def test_check_fails_when_graphloops_ledgers_disagree_on_commit(self):
        """4 つの台帳の写しがそれぞれの 1 行目の commit と一致していても、commit が割れていれば 1"""
        led = self.w / "blk-spec/prompts/COPIED_FROM"
        lines = led.read_text(encoding="utf-8").splitlines()
        lines[0] = f"{REV['b'][:7]}  graphloops 0.2.0 の仕様の道の指示書"
        led.write_text("\n".join(lines) + "\n", encoding="utf-8")
        (self.w / "blk-spec/prompts/spec.write.md").write_text("仕様 2\n", encoding="utf-8")
        rc, out = run(self.w, "--check")
        self.assertEqual(rc, 1, out)
        self.assertIn("blk-spec/prompts/COPIED_FROM", out)


class CoreSyncSyncCase(unittest.TestCase):
    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp(prefix="works-coresync-w-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.w = self.tmp / "works"
        make_works(self.w)

    def test_sync_copies_applies_deviations_and_bumps_ledgers(self):
        before = snapshot(self.w)
        rc, out = run(self.w, "sync", REV["b"], "--version", "0.2.0", "--skip-goldens")
        self.assertEqual(rc, 0, out)
        for rel, src in COPIES.items():
            if rel == ".shared/core/changemap.py":
                continue
            with self.subTest(rel):
                want = subprocess.run(["git", "-C", str(UP), "show", f"{REV['b']}:{src}"], capture_output=True,
                                      check=True).stdout
                if src == DEV["path"]:
                    want = want.replace(DEV["old"].encode(), DEV["new"].encode())
                self.assertEqual((self.w / rel).read_bytes(), want)
        for led in GL_LEDGERS:
            with self.subTest(led):
                old = before[led].decode().splitlines()
                new = (self.w / led).read_text(encoding="utf-8").splitlines()
                head = new[0].split()[0]
                self.assertGreaterEqual(len(head), 7)
                self.assertTrue(REV["b"].startswith(head), new[0])
                self.assertIn("0.2.0", new[0])
                self.assertEqual(new[1:], old[1:], "一覧と手直しの行は残す")
        # 別の系統（attention）の台帳と写しは触らない
        for rel in (".shared/core/COPIED_FROM.changemap", ".shared/core/changemap.py"):
            self.assertEqual((self.w / rel).read_bytes(), before[rel], rel)
        rc, out = run(self.w, "--check")
        self.assertEqual(rc, 0, out)

    def _assert_stops(self, rev, name):
        before = snapshot(self.w)
        rc, out = run(self.w, "sync", REV[rev], "--version", "0.3.0", "--skip-goldens")
        self.assertEqual(rc, 1, out)
        self.assertIn(name, out)
        self.assertEqual(snapshot(self.w), before, "止まったのに書いた")

    def test_sync_stops_when_deviation_does_not_apply(self):
        self._assert_stops("c", "graphloops/rules/r.py")

    def test_sync_stops_on_missing_relative_import(self):
        self._assert_stops("d", "graphloops/engine/extra.py")

    def test_sync_stops_on_missing_graph_ref(self):
        self._assert_stops("e", "graphloops/blocks/x/block.json")


if __name__ == "__main__":
    unittest.main()
