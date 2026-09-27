"""写しを変えない（仕様 BL2・9.1 の 11）。

COPIED_FROM に並ぶ写しは、1 行目の commit（graphloops 0.21.0 = a1202d0）の同じパスとバイト単位で同じ。盤面の層は写しを継ぐ
（DiskBoard は engine の Board を継ぎ、差し替えは overrides で記憶の中だけ）ので、写しの中身を直していないことをここで縛る。
例外は tests/test_core_copy.py の DEVIATIONS に並ぶ works の手直し（COPIED_FROM の行の注記にも書く）だけ。
行の読み方は tests/test_core_copy.py と同じ式（2 行目から、空行と # の行を除き、ln.split()[0]）。
"""
import pathlib
import subprocess
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from test_core_copy import expected_copy  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parents[1]
CORE = ROOT / ".shared" / "core"
COMMIT = "a1202d0"


def _git(*args):
    return subprocess.run(["git", "-C", str(ROOT), *args], capture_output=True, check=False)


class CoreVerbatimCase(unittest.TestCase):
    def test_copy_is_verbatim(self):
        lines = (CORE / "COPIED_FROM").read_text(encoding="utf-8").splitlines()
        self.assertEqual(lines[0].split()[0], COMMIT)
        r = _git("cat-file", "-e", f"{COMMIT}^{{commit}}")
        if r.returncode != 0:
            self.skipTest(f"このリポジトリから {COMMIT} を引けない（浅い clone か、graphloops の履歴を持たない）: "
                          f"{r.stderr.decode('utf-8', 'replace').strip()[-200:]}")
        listed = [ln.split()[0] for ln in lines[1:] if ln.strip() and not ln.startswith("#")]
        self.assertGreaterEqual(len(listed), 20)
        for rel in listed:
            with self.subTest(rel):
                src = _git("show", f"{COMMIT}:{rel}")
                self.assertEqual(src.returncode, 0, src.stderr.decode("utf-8", "replace"))
                self.assertEqual((CORE / rel).read_bytes(), expected_copy(rel, src.stdout))


if __name__ == "__main__":
    unittest.main()
