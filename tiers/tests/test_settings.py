"""tiers_settings（tiers-settings setup）の試験。一時のフォルダの settings.json に書く。"""

import io
import json
import pathlib
import sys
import tempfile
import unittest

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "lib"))
import tiers_settings  # noqa: E402


class Setup(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = pathlib.Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)

    def run_setup(self, *dirs, env=None):
        out, err = io.StringIO(), io.StringIO()
        argv = ["setup"] + [x for d in dirs for x in ("--config-dir", str(d))]
        return tiers_settings.main(argv, stdout=out, stderr=err, env=env or {}), out.getvalue(), err.getvalue()

    def test_adds_the_setting_keeps_other_keys_and_leaves_a_backup(self):
        d = self.home / ".claude-a"
        d.mkdir()
        (d / "settings.json").write_text('{"model": "opus"}', encoding="utf-8")
        code, out, _ = self.run_setup(d)
        self.assertEqual(code, 0)
        self.assertEqual(json.loads((d / "settings.json").read_text(encoding="utf-8")),
                         {"model": "opus", "feedbackDrafts": "off", "permissions": {"deny": ["AskUserQuestion"]}})
        backups = list(d.glob("settings.json.bak.*-tiers"))
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0].read_text(encoding="utf-8"), '{"model": "opus"}')
        self.assertIn("off にした", out)
        self.assertIn("AskUserQuestion を足した", out)

    def test_a_second_run_changes_nothing(self):
        d = self.home / ".claude-a"
        d.mkdir()
        self.run_setup(d)
        code, out, _ = self.run_setup(d)
        self.assertEqual(code, 0)
        self.assertIn("前からそろっている", out)
        self.assertFalse(list(d.glob("settings.json.bak.*")))   # 1 回目は settings.json が無かったので残す物も無い

    def test_missing_folder_and_broken_json_are_not_written(self):
        broken = self.home / ".claude-b"
        broken.mkdir()
        (broken / "settings.json").write_text('{"model": ', encoding="utf-8")
        code, _, err = self.run_setup(self.home / ".claude-none", broken)
        self.assertEqual(code, 1)
        self.assertIn("フォルダが無い", err)
        self.assertIn("JSON として読めない", err)
        self.assertFalse((self.home / ".claude-none").exists())
        self.assertEqual((broken / "settings.json").read_text(encoding="utf-8"), '{"model": ')

    def test_a_settings_json_that_cannot_be_read_is_reported_not_raised(self):
        d = self.home / ".claude-a"
        (d / "settings.json").mkdir(parents=True)
        code, _, err = self.run_setup(d)
        self.assertEqual(code, 1)
        self.assertIn("JSON として読めない", err)

    def test_without_config_dir_it_uses_claude_config_dir(self):
        d = self.home / ".claude-env"
        d.mkdir()
        code, _, _ = self.run_setup(env={"CLAUDE_CONFIG_DIR": str(d)})
        self.assertEqual(code, 0)
        self.assertEqual(json.loads((d / "settings.json").read_text(encoding="utf-8")), {"feedbackDrafts": "off", "permissions": {"deny": ["AskUserQuestion"]}})

    def test_deny_is_appended_at_the_end_and_other_permissions_stay(self):
        d = self.home / ".claude-a"
        d.mkdir()
        before = {"feedbackDrafts": "off", "permissions": {"allow": ["WebFetch"], "deny": ["Artifact"], "defaultMode": "auto"}}
        (d / "settings.json").write_text(json.dumps(before), encoding="utf-8")
        code, out, _ = self.run_setup(d)
        self.assertEqual(code, 0)
        self.assertEqual(json.loads((d / "settings.json").read_text(encoding="utf-8")),
                         {"feedbackDrafts": "off", "permissions": {"allow": ["WebFetch"], "deny": ["Artifact", "AskUserQuestion"],
                                                                   "defaultMode": "auto"}})
        self.assertNotIn("off にした", out)

    def test_permissions_of_a_wrong_shape_write_nothing(self):
        d = self.home / ".claude-a"
        d.mkdir()
        (d / "settings.json").write_text('{"permissions": {"deny": "Artifact"}}', encoding="utf-8")
        code, _, err = self.run_setup(d)
        self.assertEqual(code, 1)
        self.assertIn("permissions.deny が並び（[]）でない", err)
        self.assertEqual((d / "settings.json").read_text(encoding="utf-8"), '{"permissions": {"deny": "Artifact"}}')
        self.assertFalse(list(d.glob("settings.json.bak.*")))


if __name__ == "__main__":
    unittest.main()
