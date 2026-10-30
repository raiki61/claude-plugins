"""固定した工場の取り寄せと引数の受け渡しを、ローカルの見本で確かめる。"""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


PLUGIN = Path(__file__).resolve().parents[1]


class EntryTests(unittest.TestCase):
    def setUp(self):
        job_dir = os.environ.get("CLAUDE_JOB_DIR")
        temp_dir = None
        if job_dir is not None:
            temp_dir = Path(job_dir) / "tmp"
            temp_dir.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=temp_dir)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.plugin = self.root / "plugin"
        (self.plugin / "bin").mkdir(parents=True)
        shutil.copy2(PLUGIN / "bin/works-factory", self.plugin / "bin/works-factory")
        self.source = self.root / "source"
        (self.source / "bin").mkdir(parents=True)
        stub = "import json, sys\nprint(json.dumps({'entry': __file__, 'args': sys.argv[1:]}))\n"
        for name in ("works-factory", "apply"):
            path = self.source / "bin" / name
            path.write_text(stub)
            path.chmod(0o755)
        self.git("init", "-q")
        self.git("add", ".")
        self.git("-c", "user.name=Test", "-c", "user.email=test@example.invalid", "commit", "-qm", "fixture")
        self.pin = self.git("rev-parse", "HEAD").stdout.strip()
        (self.plugin / "PIN").write_text(self.pin + "\n")
        self.env = dict(os.environ, XDG_CACHE_HOME=str(self.root / "cache"), WORKS_FACTORY_PLUGIN_REPO=str(self.source))

    def git(self, *args):
        return subprocess.run(["git", "-C", str(self.source), *args], check=True, text=True, encoding="utf-8", capture_output=True)

    def invoke(self, *args):
        return subprocess.run(["bash", str(self.plugin / "bin/works-factory"), *args], env=self.env,
                              text=True, encoding="utf-8", capture_output=True)

    def test_fetches_exact_commit_and_keeps_arguments(self):
        self.git("-c", "user.name=Test", "-c", "user.email=test@example.invalid",
                 "commit", "--allow-empty", "-qm", "newer fixture")
        self.assertNotEqual(self.git("rev-parse", "HEAD").stdout.strip(), self.pin)
        args = ["workflow", "run", "works-factory-line", "--input", "spec_table=a b.yaml"]
        result = self.invoke(*args)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["args"], args)
        cached = self.root / "cache/works-factory-plugin" / self.pin
        head = subprocess.run(["git", "-C", str(cached), "rev-parse", "HEAD"], check=True, text=True, encoding="utf-8", capture_output=True)
        self.assertEqual(head.stdout.strip(), self.pin)

    def test_reuses_cache_without_repository(self):
        self.assertEqual(self.invoke("workflow", "status").returncode, 0)
        self.env["WORKS_FACTORY_PLUGIN_REPO"] = str(self.root / "missing")
        result = self.invoke("workflow", "status")
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_apply_uses_apply_entry(self):
        result = self.invoke("apply", "run-id", "--cwd", "a b", "--allow-stopped")
        self.assertEqual(result.returncode, 0, result.stderr)
        output = json.loads(result.stdout)
        self.assertEqual(Path(output["entry"]).name, "apply")
        self.assertEqual(output["args"], ["run-id", "--cwd", "a b", "--allow-stopped"])

    def test_bad_pin_stops_before_fetch(self):
        for pin in ("", "1234", "g" * 40):
            with self.subTest(pin=pin):
                (self.plugin / "PIN").write_text(pin)
                result = self.invoke("workflow", "status")
                self.assertEqual(result.returncode, 2)
                self.assertFalse((self.root / "cache").exists())

    @unittest.skipIf(os.name == "nt", "shebang の見本は Git Bash の外で動かない")
    @unittest.skipIf(sys.version_info < (3, 12), "試験を回す python が 3.12 より古い")
    def test_skips_python_that_is_too_old(self):
        fake = self.root / "fake-bin"
        fake.mkdir()
        log = self.root / "picked"
        for name in ("python3", "python"):
            path = fake / name
            path.write_text(f"#!/bin/sh\necho {name} >> '{log}'\nexit 1\n")
            path.chmod(0o755)
        newest = fake / "python3.20"
        newest.write_text(f"#!/bin/sh\necho python3.20 >> '{log}'\nexec '{sys.executable}' \"$@\"\n")
        newest.chmod(0o755)
        self.env["PATH"] = f"{fake}{os.pathsep}{self.env['PATH']}"
        result = self.invoke("workflow", "status")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["args"], ["workflow", "status"])
        self.assertEqual(log.read_text().split(), ["python3", "python", "python3.20", "python3.20"])

    def test_skill_body_and_reference_links(self):
        text = (PLUGIN / "skills/works-factory/SKILL.md").read_text()
        body = text.split("---", 2)[2].lstrip("\n")
        self.assertLess(len(body.splitlines()), 500)
        for name in ("auth.md", "stop.md", "spec.md", "pr.md"):
            self.assertIn(f"(references/{name})", body)
            self.assertTrue((PLUGIN / "skills/works-factory/references" / name).is_file())


if __name__ == "__main__":
    unittest.main()
