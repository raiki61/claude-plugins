"""canary の殻 dev/canary.sh が対象を作って use.sh start を起こす形の検査（HEAVY）。

canary.sh を子で起こし、置き場に対象の git（git init・commit・裸の origin への push）を作らせる。use.sh は WORKS_DEV_USE で
偽物（受けた引数と、起こされた時の対象の木の形を書き出すだけの sh）に差し替え、Archon・認証・費用を使わない。canary.sh の
前の確かめ「python3 -I で pytest が読めるか」は試験を回す解釈系に依るので（uv run の環境に pytest は無い）、PATH の頭の偽の
python3 がその 1 つの形だけに 0 で答え、ほかは試験の解釈系へ渡す（pytest が無い時の拒みはここでは見ない）。
--request change（変更から入る canary）: 種と依頼は fix の物で、対象は種を 1 回 commit した上に commit しない 1 行の変更
（calc.py の docstring の字）を持ち、use.sh start に --base <その commit> を付ける。ほかの語（tdd）は --base を付けず、木は
きれいなまま。--build-only は同じ対象を作り、起動の行に --base を出す。終わりの canary_check.py の行には同じ語を付ける。
"""
import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.dont_write_bytecode = True   # 下の import が pack の中に __pycache__ を作らないように
sys.path.insert(0, str(ROOT / "tests"))

import hermetic  # noqa: E402

CANARY_SH = ROOT / "dev" / "canary.sh"
REQUEST_FIX = ROOT / "dev" / "canary-request-fix.json"
REQUEST_TDD = ROOT / "dev" / "canary-request.json"
TEST_CMD = "python3 -m pytest -q"

# 偽の use.sh: 受けた引数・対象の HEAD・未 commit の変更（numstat と差分）を WORKS_USE_HOME/fake-use.json に書き、run の控えを
# 1 つ置いて 7 で終わる（canary.sh が終了コードをそのまま返すかを見る）
FAKE_USE = r"""#!/bin/sh
set -eu
for a in "$@"; do repo=$a; [ -d "$a/.git" ] && break; done
mkdir -p "$WORKS_USE_HOME/runs"
python3 -I - "$WORKS_USE_HOME/fake-use.json" "$repo" "$@" <<'EOF'
import json, subprocess, sys
out, repo, args = sys.argv[1], sys.argv[2], sys.argv[3:]
def git(*a):
    return subprocess.run(["git", "-C", repo, *a], capture_output=True, text=True, encoding="utf-8", check=True).stdout
json.dump({"args": args, "head": git("rev-parse", "HEAD").strip(), "status": git("status", "--porcelain"),
           "numstat": git("diff", "--numstat"), "diff": git("diff")}, open(out, "w", encoding="utf-8"), ensure_ascii=False)
EOF
echo '{}' > "$WORKS_USE_HOME/runs/fake-run.json"
exit 7
"""


# 偽の python3: canary.sh の pytest の確かめ（python3 -I -c "import pytest"）だけに 0 で答え、ほかは試験の解釈系へ渡す
FAKE_PYTHON = """#!/bin/sh
if [ "$#" -eq 3 ] && [ "$1" = -I ] && [ "$2" = -c ] && [ "$3" = "import pytest" ]; then
  exit 0
fi
exec "{python}" "$@"
"""


class CanaryShStartTest(unittest.TestCase):
    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp(prefix="canary-sh-start-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.fake = self.tmp / "fake-use.sh"
        self.fake.write_text(FAKE_USE, encoding="utf-8")
        self.bin = self.tmp / "bin"
        self.bin.mkdir()
        python = self.bin / "python3"
        python.write_text(FAKE_PYTHON.format(python=sys.executable), encoding="utf-8")
        python.chmod(0o755)

    def canary(self, *args, place):
        base = hermetic.child_env()
        env = hermetic.child_env(PYTHONDONTWRITEBYTECODE="1", WORKS_DEV_USE=str(self.fake),
                                 WORKS_KEYCHAIN_ITEM="works-test-not-a-real-item",
                                 PATH=os.pathsep.join([str(self.bin), base.get("PATH", "")]))
        return subprocess.run(["sh", str(CANARY_SH), *args, str(place)], capture_output=True, text=True, encoding="utf-8",
                              env=env)

    def head(self, repo):
        return subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"], capture_output=True, text=True,
                              encoding="utf-8", check=True).stdout.strip()

    def test_diff_flag_adds_one_uncommitted_line_and_base(self):
        """--diff は語の種と依頼のまま、commit しない 1 行の変更と --base <種を写した commit> を足す（前の --request change と同じ run）"""
        place = self.tmp / "change"
        got = self.canary("--request", "fix", "--diff", place=place)
        self.assertEqual(got.returncode, 7, got.stdout + got.stderr)
        seen = json.loads((place / "home" / "fake-use.json").read_text(encoding="utf-8"))
        repo = (place / "repo").resolve()
        self.assertEqual(seen["args"], ["start", "--base", seen["head"], str(repo), str(REQUEST_FIX), TEST_CMD])
        self.assertEqual(seen["status"], " M calc.py\n", "変更は commit しない calc.py の 1 か所だけ")
        self.assertEqual(seen["numstat"], "1\t1\tcalc.py\n")
        self.assertIn("+    \"\"\"中央値（個数が偶数なら、並べた真ん中の 2 つの平均）", seen["diff"])
        self.assertIn("canary_check.py " + str(place.resolve()) + " fake-run --request fix", got.stdout)

    def test_change_word_refused_with_replacement(self):
        """前の語 change は黙って読み替えず、替わりの打ち方（--request fix --diff）を書いて 2 で拒む（何も作らない）"""
        place = self.tmp / "old"
        got = self.canary("--request", "change", place=place)
        self.assertEqual(got.returncode, 2, got.stdout + got.stderr)
        self.assertIn("--request fix --diff", got.stderr)
        self.assertFalse(place.exists())

    def test_other_words_start_without_base_on_a_clean_tree(self):
        place = self.tmp / "tdd"
        got = self.canary("--request", "tdd", place=place)
        self.assertEqual(got.returncode, 7, got.stdout + got.stderr)
        seen = json.loads((place / "home" / "fake-use.json").read_text(encoding="utf-8"))
        self.assertEqual(seen["args"], ["start", str((place / "repo").resolve()), str(REQUEST_TDD), TEST_CMD])
        self.assertEqual(seen["status"], "")

    def test_build_only_change_prints_the_start_line_with_base(self):
        place = self.tmp / "build"
        got = self.canary("--build-only", "--request", "fix", "--diff", place=place)
        self.assertEqual(got.returncode, 0, got.stdout + got.stderr)
        repo = (place / "repo").resolve()
        self.assertFalse((place / "home" / "fake-use.json").exists(), "--build-only は use.sh を起こさない")
        self.assertIn(f"start --base {self.head(repo)} {repo} {REQUEST_FIX}", got.stdout)
        status = subprocess.run(["git", "-C", str(repo), "status", "--porcelain"], capture_output=True, text=True,
                                encoding="utf-8", check=True).stdout
        self.assertEqual(status, " M calc.py\n")


if __name__ == "__main__":
    unittest.main()
