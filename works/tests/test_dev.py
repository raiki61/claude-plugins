"""works/dev/ の開発の殻（固定した版の Archon を隔離して回す・使い捨ての対象を作る）の骨組みの検査。

archon 本体のダウンロードやネットワークは伴わない範囲だけを見る:
- mktarget.sh が作る使い捨ての対象に、pack が dev 用ファイル抜き・ゴミファイル抜きで入り、
  全部 commit 済みで、仕込んだバグのせいでテストが赤になること。
- archon.sh が、キャッシュにある実行ファイルの sha256 が違えばネットワークに出ずに拒むこと。
- archon.sh が keychain（ここでは偽物に差し替える。本物には触らない）を、HOME を隔離する
  前の元の HOME で読むこと。
- check.sh が works 自身の工程（works/<d>/<d>.yaml）だけを 1 本ずつ validate し、`workflow test works` を回し、
  どれか 1 つでも赤なら終了コード 1 になること（Archon は偽物の記録係に差し替える。Ruling R10）。
"""
import os
import pathlib
import subprocess
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
DEV = ROOT / "dev"


def git(cwd, *args):
    result = subprocess.run(
        ["git", "-C", str(cwd), *args], capture_output=True, text=True, check=True
    )
    return result.stdout.strip()


def run_tests(cwd):
    """対象リポジトリの中身（target-seed の写し）を unittest discover で回す。"""
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    return subprocess.run(
        ["python3", "-m", "unittest", "discover", "-s", ".", "-p", "test_*.py"],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        env=env,
    )


class TestDevShell(unittest.TestCase):
    def test_mktarget_places_pack_without_dev_files(self):
        with tempfile.TemporaryDirectory() as tmp_str:
            tmp = pathlib.Path(tmp_str)
            out = subprocess.run(
                ["sh", str(DEV / "mktarget.sh"), str(tmp)],
                capture_output=True,
                text=True,
                check=True,
            )
            printed = pathlib.Path(out.stdout.strip())
            self.assertEqual(printed.resolve(), tmp.resolve())

            pack = tmp / ".archon" / "workflows" / "works"
            self.assertTrue((pack / "archon-plugin.json").exists())
            self.assertTrue((pack / ".shared" / "core" / "COPIED_FROM").exists())
            for d in ("tests", "dev", "docs"):
                self.assertFalse((pack / d).exists())
            self.assertEqual(list(pack.rglob("__pycache__")), [])
            self.assertEqual(list(pack.rglob(".DS_Store")), [])
            self.assertEqual(git(tmp, "status", "--porcelain"), "")  # 全部 commit 済み
            self.assertEqual(run_tests(tmp).returncode, 1)  # 仕込んだバグで赤

    def test_archon_sh_refuses_wrong_checksum(self):
        with tempfile.TemporaryDirectory() as tmp_str:
            dev_home = pathlib.Path(tmp_str)
            bin_dir = dev_home / "bin"
            bin_dir.mkdir(parents=True)
            (bin_dir / "archon-darwin-arm64").write_bytes(b"not the real archon binary")

            env = dict(os.environ)
            env["WORKS_DEV_HOME"] = str(dev_home)
            env["WORKS_DEV_NO_AUTH"] = "1"

            result = subprocess.run(
                ["sh", str(DEV / "archon.sh"), "version"],
                capture_output=True,
                text=True,
                env=env,
            )
            self.assertEqual(result.returncode, 1)
            self.assertIn("sha256", result.stderr)

    def test_archon_sh_reads_keychain_before_home_is_isolated(self):
        """keychain（偽物）を読む時点の $HOME が、隔離した偽の HOME ではなく元の HOME であること。

        本物の keychain には一切触れない: PATH の先頭に置いた偽の `security` が実物の代わりに
        呼ばれる。実行ファイルの中身は意図的に違うものにして、認証を読んだすぐ後の sha256 の
        確かめで exit 1 になる（読み込みが exec より前で起きたことの観測に、本物の 77MB の
        実行ファイルは要らない）。
        """
        with tempfile.TemporaryDirectory() as tmp_str:
            tmp = pathlib.Path(tmp_str)

            dev_home = tmp / "dev-home"
            (dev_home / "bin").mkdir(parents=True)
            (dev_home / "bin" / "archon-darwin-arm64").write_bytes(b"not the real archon binary")

            fake_bin = tmp / "fake-bin"
            fake_bin.mkdir()
            record_file = tmp / "security-home.txt"
            security_script = fake_bin / "security"
            security_script.write_text(
                "#!/bin/sh\n"
                f'echo "$HOME" > "{record_file}"\n'
                "echo dummy-token-for-test\n"
            )
            security_script.chmod(0o755)

            original_home = "/tmp/works-dev-test-original-home"  # 実在しなくてよい、印の値
            env = dict(os.environ)
            env.pop("CLAUDE_CODE_OAUTH_TOKEN", None)
            env.pop("WORKS_DEV_NO_AUTH", None)
            env["HOME"] = original_home
            env["WORKS_DEV_HOME"] = str(dev_home)
            env["PATH"] = str(fake_bin) + os.pathsep + env.get("PATH", "")

            result = subprocess.run(
                ["sh", str(DEV / "archon.sh"), "version"],
                capture_output=True,
                text=True,
                env=env,
            )

            # 偽の security を呼んだ時点の $HOME は、隔離前の元の HOME のまま。
            self.assertEqual(record_file.read_text().strip(), original_home)
            # 中身の違う実行ファイルなので、keychain を読んだ後の sha256 の確かめで落ちる。
            self.assertEqual(result.returncode, 1)
            self.assertIn("sha256", result.stderr)


    def _run_check(self, fail_on=""):
        """check.sh を偽の Archon（引数と cwd を記録し、引数に fail_on を含めば終了コード 1）で回す"""
        with tempfile.TemporaryDirectory() as tmp_str:
            tmp = pathlib.Path(tmp_str)
            log = tmp / "calls.txt"
            fake = tmp / "fake-archon.sh"
            fake.write_text(
                "#!/bin/sh\n"
                f'printf \'%s|%s|%s\\n\' "$(pwd -P)" "${{WORKS_DEV_NO_AUTH:-}}" "$*" >> "{log}"\n'
                f'case "$*" in *"{fail_on or "@@never@@"}"*) exit 1 ;; esac\n'
                "exit 0\n"
            )
            # 偽物を使わず本物の archon.sh へ落ちても、ネットワークにも keychain にも出ずに sha256 で止まるようにしておく
            dev_home = tmp / "dev-home"
            (dev_home / "bin").mkdir(parents=True)
            (dev_home / "bin" / "archon-darwin-arm64").write_bytes(b"not the real archon binary")
            env = dict(os.environ, WORKS_DEV_ARCHON=str(fake), TMPDIR=str(tmp), WORKS_DEV_HOME=str(dev_home),
                       CLAUDE_CODE_OAUTH_TOKEN="dummy-token-for-test")
            env.pop("WORKS_DEV_NO_AUTH", None)
            result = subprocess.run(["sh", str(DEV / "check.sh")], capture_output=True, text=True, env=env)
            calls = [line.split("|", 2) for line in log.read_text().splitlines()] if log.exists() else []
            return result, calls

    def test_check_validates_only_works_workflows(self):
        ours = sorted(p.parent.name for p in ROOT.glob("*/*.yaml") if p.stem == p.parent.name)
        self.assertIn("blk-judge", ours)
        result, calls = self._run_check()
        self.assertEqual(result.returncode, 0, result.stderr)
        args = [c[2] for c in calls]
        self.assertEqual(args, [f"validate workflows {n}" for n in ours] + ["workflow test works"])
        for cwd, no_auth, a in calls:
            with self.subTest(a):
                self.assertIn("works-check", cwd)   # 使い捨ての対象の中で回す
                self.assertEqual(no_auth, "1" if a.startswith("validate") else "")

    def test_check_fails_when_one_workflow_is_red(self):
        result, calls = self._run_check(fail_on="validate workflows blk-fix")
        self.assertEqual(result.returncode, 1)
        self.assertIn("workflow test works", [c[2] for c in calls])   # 赤でも残りは回す


if __name__ == "__main__":
    unittest.main()
