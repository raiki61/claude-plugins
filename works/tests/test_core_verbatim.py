"""写しを変えない（仕様 BL2・9.1 の 11）。

COPIED_FROM に並ぶ写しは、1 行目の commit（写した graphloops の版。写し直しは dev/core-sync.py sync）の同じパスとバイト単位で同じ。
盤面の層は写しを継ぐ（DiskBoard は engine の Board を継ぎ、差し替えは overrides で記憶の中だけ）ので、写しの中身を直していないことを
ここで縛る。例外は COPIED_FROM の ! 行に並ぶ works の手直し（行の注記にも書く）だけ。当て方は tests/test_core_copy.py の expected_copy。
台帳は写し直しの道具と同じ読み口 .shared/core/copyledger.py で読む。
"""
import pathlib
import subprocess
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from test_core_copy import copyledger, expected_copy  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parents[1]
CORE = ROOT / ".shared" / "core"


def _git(*args):
    return subprocess.run(["git", "-C", str(ROOT), *args], capture_output=True, check=False)


class CoreVerbatimCase(unittest.TestCase):
    def test_copy_is_verbatim(self):
        led = copyledger.read(CORE / "COPIED_FROM")
        commit = led.commit
        r = _git("cat-file", "-e", f"{commit}^{{commit}}")
        if r.returncode != 0:
            self.skipTest(f"SKIP git-history: このリポジトリから {commit} を引けない（浅い clone か、graphloops の履歴を持たない）: "
                          f"{r.stderr.decode('utf-8', 'replace').strip()[-200:]}")
        listed = [rel for rel, _ in led.rows]
        self.assertGreaterEqual(len(listed), 20)
        for rel in listed:
            with self.subTest(rel):
                src = _git("show", f"{commit}:{rel}")
                self.assertEqual(src.returncode, 0, src.stderr.decode("utf-8", "replace"))
                self.assertEqual((CORE / rel).read_bytes(), expected_copy(rel, src.stdout))


if __name__ == "__main__":
    unittest.main()
