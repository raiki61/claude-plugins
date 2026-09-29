"""dev/use.sh の既定の家を clone ごとに分けた後の、家をまたぐ面の検査。Archon と herdr は偽物（sh の台本）。

見る物:
- herdr の枠の集計（lib.sh works_dev_herdr_sync）は、渡された控えの置き場の全部からその枠の run を数え、状態の分からない run は
  その run の家の Archon の一覧（WORKS_DEV_HOME をその家にして引く）で引く。同じ置き場を 2 度渡しても 1 度に数える。
- use.sh は今の家と既定の家の全部（前の既定の家 works/use と clone ごとの works/use-<印>）を渡す。1 つの枠から 2 つの clone の run を
  起こした時、clone A の人の番の合図が clone B の終わりで消えない。
- 家の目印 <家>/target: 家を作った clone の実際のパスを 1 行。後から別の clone が同じ家を名指しても書き直さない。
"""
import hashlib
import json
import os
import pathlib
import subprocess
import tempfile
import unittest

import hermetic
import test_use as base

DEV = base.DEV
setUpModule = base.setUpModule
tearDownModule = base.tearDownModule


def fake_herdr(tmp):
    """herdr の偽物: 受けた引数を 1 行ずつ控える。(PATH の頭に足すフォルダ, 控えのファイル)"""
    bin_dir = tmp / "herdr-bin"
    bin_dir.mkdir()
    log = tmp / "herdr.txt"
    (bin_dir / "herdr").write_text(f'#!/bin/sh\necho "$*" >> "{log}"\nexit 0\n')
    (bin_dir / "herdr").chmod(0o755)
    return bin_dir, log


def herdr_calls(log):
    return log.read_text().splitlines() if log.exists() else []


class HerdrAcrossHomes(unittest.TestCase):
    """lib.sh works_dev_herdr_sync を直に起こす（git なし）"""

    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.tmp = pathlib.Path(self._td.name).resolve()
        self.addCleanup(self._td.cleanup)
        self.herdr_bin, self.herdr_log = fake_herdr(self.tmp)
        # 偽の Archon: 一覧は呼び手の WORKS_DEV_HOME の家の listed.json（家ごとに別の Archon の形）
        self.archon = self.tmp / "archon.sh"
        self.archon.write_text('#!/bin/sh\ncat "$WORKS_DEV_HOME/listed.json" 2>/dev/null || echo \'{"runs": []}\'\n')

    def home(self, name, **status_by_run):
        h = self.tmp / name
        (h / "runs").mkdir(parents=True)
        for rid in status_by_run:
            (h / "runs" / f"{rid}.json").write_text(json.dumps({"run_id": rid, "herdr_pane": "pane-7"}))
        self.set_status(h, **status_by_run)
        return h

    def set_status(self, h, **status_by_run):
        (h / "listed.json").write_text(json.dumps({"runs": [{"id": r, "status": s} for r, s in status_by_run.items()]}))

    def sync(self, dirs, *known):
        env = hermetic.child_env(PATH=f"{self.herdr_bin}{os.pathsep}{os.environ.get('PATH', '')}", HERDR_ENV="1",
                                 HERDR_PANE_ID="pane-7")
        self.herdr_log.unlink(missing_ok=True)
        r = subprocess.run(["sh", "-c", '. "$1"; shift; works_dev_herdr_sync "$@"', "sh", str(DEV / "lib.sh"),
                            str(self.archon), "\n".join(str(d) for d in dirs), *known],
                           capture_output=True, text=True, encoding="utf-8", env=env)
        self.assertEqual(r.returncode, 0, r.stderr)
        return herdr_calls(self.herdr_log)

    def test_waiting_run_in_other_home_keeps_pane_blocked(self):
        a = self.home("home-a", **{"run-a": "paused"})
        b = self.home("home-b", **{"run-b": "completed"})
        calls = self.sync([a / "runs", b / "runs"], "run-b=completed")
        self.assertFalse(any(c.startswith("release-agent") for c in calls), calls)
        reports = [c for c in calls if c.startswith("report-agent")]
        self.assertEqual(len(reports), 1, calls)
        self.assertIn("--state blocked", reports[0])
        self.assertIn("人の番 1・走る 0・終わった 1", reports[0])
        # A も終わった時だけ release
        self.set_status(a, **{"run-a": "completed"})
        calls = self.sync([a / "runs", b / "runs"], "run-b=completed")
        self.assertTrue(any(c.startswith("release-agent pane-7") for c in calls), calls)

    def test_same_home_given_twice_counts_once(self):
        a = self.home("home-a", **{"run-a": "running"})
        (self.tmp / "link").symlink_to(a)
        calls = self.sync([a / "runs", self.tmp / "link" / "runs", self.tmp / "missing" / "runs"])
        reports = [c for c in calls if c.startswith("report-agent")]
        self.assertEqual(len(reports), 1, calls)
        self.assertIn("走る 1・終わった 0", reports[0])


class UseHomes(unittest.TestCase):
    """use.sh を偽の Archon で起こす（対象は種の git の写し）"""

    setUp = base.UseShell.setUp
    set_runs = base.UseShell.set_runs
    target = base.UseShell.target
    use = base.UseShell.use

    def default_home(self, t):
        mark = hashlib.sha256(os.path.realpath(t).encode()).hexdigest()[:8]
        return self.tmp / "state" / "works" / ("use-" + mark)

    def test_home_marker_names_clone_that_made_it(self):
        a, b = self.target("a"), self.target("b")
        (self.tmp / "link").symlink_to(a)
        state = str(self.tmp / "state")
        self.use("check", str(self.tmp / "link"), XDG_STATE_HOME=state, WORKS_USE_HOME=None)
        self.assertEqual((self.default_home(a) / "target").read_text(), f"{os.path.realpath(a)}\n")
        # 名指した家を 2 つの clone で使っても、目印は家を作った clone のまま
        self.use("check", str(a))
        self.use("check", str(b))
        self.assertEqual((self.home / "target").read_text(), f"{os.path.realpath(a)}\n")

    def test_herdr_pane_counts_runs_of_every_default_home(self):
        a, b = self.target("a"), self.target("b")
        state = self.tmp / "state"
        home_a, home_b, old = self.default_home(a), self.default_home(b), state / "works" / "use"
        for h, rid, t, status in ((home_a, "run-a", a, "paused"), (home_b, "run-b", b, "completed"),
                                  (old, "run-old", a, "completed")):
            (h / "runs").mkdir(parents=True, exist_ok=True)
            (h / "runs" / f"{rid}.json").write_text(json.dumps({"run_id": rid, "target": str(t), "herdr_pane": "pane-7"}))
            (h / "listed.json").write_text(json.dumps({"runs": [
                {"id": rid, "workflow_name": "darkfactory", "status": status, "working_path": "/wt/" + rid}]}))
        self.fake.write_text('#!/bin/sh\ncase "$*" in "workflow runs --json") cat "$WORKS_DEV_HOME/listed.json" ;; esac\n'
                             "exit 0\n")
        herdr_bin, herdr_log = fake_herdr(self.tmp)
        pane = dict(PATH=f"{herdr_bin}{os.pathsep}{os.environ.get('PATH', '')}", HERDR_ENV="1", HERDR_PANE_ID="pane-7")
        # clone B の run が終わっても、同じ枠から起こした clone A の run が関所で待つ: release せず blocked
        r = self.use("wait", str(b), "run-b", XDG_STATE_HOME=str(state), WORKS_USE_HOME=None, CLAUDE_CODE_OAUTH_TOKEN=None,
                     WORKS_USE_WAIT_SECONDS="1", **pane)
        self.assertEqual(r.returncode, 5, r.stdout + r.stderr)
        calls = herdr_calls(herdr_log)
        self.assertFalse(any(c.startswith("release-agent") for c in calls), calls)
        reports = [c for c in calls if c.startswith("report-agent")]
        self.assertTrue(reports and "--state blocked" in reports[-1], calls)
        self.assertIn("人の番 1・走る 0・終わった 2", reports[-1])


if __name__ == "__main__":
    unittest.main()
