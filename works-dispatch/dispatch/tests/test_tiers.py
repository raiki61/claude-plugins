"""--check が要る道具の段の点検（tiers プラグイン）を呼ぶ形と、その口 tierx の試験。tiers そのものは起こさない。"""

import json
import os
import pathlib
import tempfile
import types
import unittest

from . import DISPATCH  # noqa: F401
from .test_dispatch import FakePorts, make_cfg, run_main
import tierx


def result(*bad):
    checks = [{"tier": 1, "name": n, "ok": False, "problem": f"{n} が無い", "fix": [f"{n} を入れる"], "manual": True} for n in bad]
    return {"schema": 1, "tier": 2, "ok": not bad, "missing": len(bad), "checks": checks}


class CheckCallsTiers(unittest.TestCase):
    def setUp(self):
        self.cfg, self.root = make_cfg()

    def ports(self, answer):
        ports = FakePorts([])
        ports.asked, ports.preflighted = [], False
        real_preflight = ports.preflight

        def tier_check(launchers):
            ports.asked.append(launchers)
            if isinstance(answer, Exception):
                raise answer
            return answer

        def preflight(cfg, task=False):
            ports.preflighted = True
            return real_preflight(cfg, task)
        ports._tier_check = tier_check
        ports.preflight = preflight
        return ports

    def test_missing_tools_stop_with_how_to_install_before_the_rest(self):
        ports = self.ports(result("gh"))
        rc, out = run_main(["--config", self.cfg, "--check"], ports)
        self.assertEqual(rc, 2)
        self.assertIn("- 段 1 gh: gh が無い（入れ方（手で）: gh を入れる）", out)
        self.assertFalse(ports.preflighted)

    def test_launch_commands_of_the_accounts_are_passed(self):
        ports = self.ports(result())
        rc, out = run_main(["--config", self.cfg, "--check"], ports)
        self.assertEqual(rc, 0, out)
        self.assertEqual(ports.asked, [["claude-a1"]])
        self.assertTrue(ports.preflighted)

    def test_without_the_part_it_notes_and_keeps_the_old_check(self):
        ports = self.ports(tierx.TierError("段の点検の部品が見つからない"))
        rc, out = run_main(["--config", self.cfg, "--check"], ports)
        self.assertEqual(rc, 0, out)
        self.assertIn("段の点検の部品が見つからない", out)
        self.assertIn("足りない物は無い", out)
        self.assertTrue(ports.preflighted)


class Locate(unittest.TestCase):
    def test_path_entry_wins_and_has_no_extension(self):
        with tempfile.TemporaryDirectory() as d:
            entry = pathlib.Path(d) / "tiers"
            entry.write_text("", encoding="utf-8")
            self.assertEqual(tierx.locate({"PATH": os.pathsep.join(["", d])}, here=__file__), str(entry))

    def test_falls_back_to_the_sibling_plugin_in_the_checkout(self):
        here = pathlib.Path(tierx.__file__)
        got = tierx.locate({"PATH": ""}, here=here)
        self.assertEqual(pathlib.Path(got), here.resolve().parent.parent.parent / "tiers" / "bin" / "tiers")

    def test_none_when_nowhere(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertIsNone(tierx.locate({"PATH": d}, here=pathlib.Path(d) / "a" / "b.py"))


class Check(unittest.TestCase):
    def runner(self, stdout, code=0):
        seen = []

        def run(argv, **kw):
            seen.append(argv)
            return types.SimpleNamespace(returncode=code, stdout=stdout, stderr="")
        return run, seen

    def test_asks_for_tier_2_in_json_with_each_launcher(self):
        run, seen = self.runner(json.dumps(result()))
        got = tierx.check(["claude-x", "claude-y"], env={"PATH": ""}, runner=run)
        self.assertTrue(got["ok"])
        self.assertEqual(seen[0][2:], ["--tier", "2", "--json", "--launcher", "claude-x", "--launcher", "claude-y"])

    def test_missing_tools_are_a_result_not_an_error(self):
        run, _ = self.runner(json.dumps(result("herdr")), code=1)
        got = tierx.check([], env={"PATH": ""}, runner=run)
        self.assertEqual(tierx.problems(got), ["段 1 herdr: herdr が無い（入れ方（手で）: herdr を入れる）"])

    def test_not_json_or_other_shape_is_an_error(self):
        for out in ("Traceback ...", json.dumps({"schema": 2, "checks": []})):
            run, _ = self.runner(out, code=1)
            with self.assertRaises(tierx.TierError):
                tierx.check([], env={"PATH": ""}, runner=run)

    def test_no_entry_is_an_error(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(tierx.TierError):
                tierx.check([], env={"PATH": d}, here=pathlib.Path(d) / "a" / "b.py")


if __name__ == "__main__":
    unittest.main()
