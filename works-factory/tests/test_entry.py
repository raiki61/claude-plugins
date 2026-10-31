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


@unittest.skipIf(os.name == "nt" and sys.version_info < (3, 12), "Windows では入口を試験の python で直に起動するので、3.12 以上が要る")
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
            path.write_text(stub, encoding="utf-8")
            path.chmod(0o755)
        self.git("init", "-q")
        self.git("add", ".")
        self.git("-c", "user.name=Test", "-c", "user.email=test@example.invalid", "commit", "-qm", "fixture")
        self.pin = self.git("rev-parse", "HEAD").stdout.strip()
        (self.plugin / "PIN").write_text(self.pin + "\n", encoding="utf-8")
        self.env = dict(os.environ, XDG_CACHE_HOME=str(self.root / "cache"), WORKS_FACTORY_PLUGIN_REPO=str(self.source))
        # sh で起動する時に頭が選ぶ python を PATH の頭の見本の置き場に寄せ、手元の PATH の python の版に依らずに回す
        self.fake = self.root / "fake-bin"
        self.fake.mkdir()
        self.log = self.root / "picked"
        if os.name != "nt":
            self.fake_command("python3", f"exec '{sys.executable}' \"$@\"")
        self.env["PATH"] = f"{self.fake}{os.pathsep}{self.env['PATH']}"

    def fake_command(self, name, body):
        """PATH の頭に、呼ばれた名前を記録してから body を走らせる見本のコマンドを置く。"""
        path = self.fake / name
        path.write_text(f"#!/bin/sh\necho {name} >> '{self.log}'\n{body}\n", encoding="utf-8")
        path.chmod(0o755)

    def picked(self):
        return self.log.read_text().split() if self.log.exists() else []

    def git(self, *args):
        return subprocess.run(["git", "-C", str(self.source), *args], check=True, text=True, encoding="utf-8", capture_output=True)

    def invoke(self, *args, shell=False):
        """入口を起動する。既定は試験を回す python で直に起動し（Windows の PowerShell から打つ形と同じ）、shell=True は sh で起動して
        頭の python の選びから通す（試験の python が 3.12 より古い時も sh で起動し、頭が PATH の 3.12 以上を選ぶ）。bash を裸の名前で起動しないのは、Windows では CreateProcess が PATH より先にシステムのディレクトリを探し、
        Git の bash でなく WSL の起動口（C:\\Windows\\System32\\bash.exe）に当たるため（tests/mutate.py の BASH と同じ訳）"""
        head = ["sh"] if shell or sys.version_info < (3, 12) else [sys.executable]
        return subprocess.run([*head, str(self.plugin / "bin/works-factory"), *args], env=self.env,
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

    def test_passes_exit_code_of_factory(self):
        # 工場の入口の終わりのコードをそのまま返す（Windows は子を待って返し、ほかは exec で入れ替わる）
        (self.source / "bin/works-factory").write_text("import sys\nsys.exit(7)\n", encoding="utf-8")
        self.git("add", ".")
        self.git("-c", "user.name=Test", "-c", "user.email=test@example.invalid", "commit", "-qm", "exit 7")
        self.pin = self.git("rev-parse", "HEAD").stdout.strip()
        (self.plugin / "PIN").write_text(self.pin, encoding="utf-8")
        self.assertEqual(self.invoke("workflow", "status").returncode, 7)

    def test_failed_fetch_leaves_no_temporary_folder(self):
        # 取り寄せが落ちたら git の終わりのコードで止まり、取り置きの置き場に一時のフォルダを残さない
        self.env["WORKS_FACTORY_PLUGIN_REPO"] = str(self.root / "missing")
        result = self.invoke("workflow", "status")
        self.assertNotEqual(result.returncode, 0)
        cache = self.root / "cache/works-factory-plugin"
        self.assertEqual(list(cache.iterdir()) if cache.exists() else [], [])

    def test_bad_pin_stops_before_fetch(self):
        for pin in ("", "1234", "g" * 40):
            with self.subTest(pin=pin):
                (self.plugin / "PIN").write_text(pin, encoding="utf-8")
                result = self.invoke("workflow", "status")
                self.assertEqual(result.returncode, 2)
                self.assertFalse((self.root / "cache").exists())

    @unittest.skipIf(os.name == "nt", "sh の見本のコマンドは Windows の CreateProcess から起動できない")
    def test_picks_first_python_that_is_new_enough(self):
        # python3・python は古く、版の付いた名前は 3.20 から 3.13 まで起きず、下限の 3.12 だけが起きる
        for name in ["python3", "python"] + [f"python3.{n}" for n in range(20, 12, -1)]:
            self.fake_command(name, "exit 1")
        self.fake_command("python3.12", f"exec '{sys.executable}' \"$@\"")
        result = self.invoke("workflow", "status", shell=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["args"], ["workflow", "status"])
        # 版を見る起動が順に並び、最後に選んだ python3.12 でこの台本を起動し直す（その先は起動し直した python のまま）
        tried = ["python3", "python"] + [f"python3.{n}" for n in range(20, 11, -1)]
        self.assertEqual(self.picked(), tried + ["python3.12"])

    @unittest.skipIf(os.name == "nt", "sh の見本のコマンドは Windows の CreateProcess から起動できない")
    def test_no_python_stops_before_fetch(self):
        for name in ["python3", "python", "py"] + [f"python3.{n}" for n in range(20, 11, -1)]:
            self.fake_command(name, "exit 1")
        result = self.invoke("workflow", "status", shell=True)
        self.assertEqual(result.returncode, 2)
        self.assertIn("python 3.12 以上が見つからない", result.stderr)
        self.assertEqual(len(result.stderr.strip().splitlines()), 1)
        self.assertFalse((self.root / "cache").exists())

    @unittest.skipIf(os.name == "nt", "git の見本（sh の台本）は Windows の CreateProcess から起動できない")
    def test_keeps_cache_placed_by_concurrent_launch(self):
        # 取り寄せの途中で、同時に起動した別の殻が置き場を先に置いた形を、checkout の後に置く git の見本で作る
        cached = self.root / "cache/works-factory-plugin" / self.pin
        other = "import json, sys\nprint(json.dumps({'entry': 'other', 'args': sys.argv[1:]}))\n"
        self.fake_command("git", f"""'{shutil.which("git")}' "$@" || exit $?
case " $* " in *" checkout "*)
  mkdir -p '{cached}/bin'
  printf '%s' "{other}" > '{cached}/bin/works-factory'
  chmod +x '{cached}/bin/works-factory' ;;
esac""")
        result = self.invoke("workflow", "status")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["entry"], "other")
        self.assertEqual(sorted(p.name for p in cached.parent.iterdir()), [self.pin])

    def test_replaces_incomplete_cache(self):
        # 前に中身が欠けたまま残った置き場は、消して置き直す
        cached = self.root / "cache/works-factory-plugin" / self.pin
        (cached / "bin").mkdir(parents=True)
        (cached / "leftover").write_text("")
        result = self.invoke("workflow", "status")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["args"], ["workflow", "status"])
        self.assertFalse((cached / "leftover").exists())
        self.assertEqual(sorted(p.name for p in cached.parent.iterdir()), [self.pin])

    def test_skill_body_and_reference_links(self):
        text = (PLUGIN / "skills/works-factory/SKILL.md").read_text(encoding="utf-8")
        body = text.split("---", 2)[2].lstrip("\n")
        self.assertLess(len(body.splitlines()), 500)
        for name in ("auth.md", "stop.md", "spec.md", "pr.md"):
            self.assertIn(f"(references/{name})", body)
            self.assertTrue((PLUGIN / "skills/works-factory/references" / name).is_file())


if __name__ == "__main__":
    unittest.main()
