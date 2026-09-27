"""works のテストの段（fast・heavy）の一覧と、段を 1 つ選んで回す入口。

run.sh が WORKS_TESTS=fast|heavy のときに `python3 tests/tiers.py <段> [unittest の引数]` で起こす
（WORKS_TESTS が空なら run.sh は従来どおり全部を unittest discover で回し、ここを通らない）。
fast と heavy は重ならず、合わせるとちょうど全部（tests/test_*.py）になる。どのモジュールも FAST か HEAVY の
どちらかに書く。書き忘れ・両方に書いた・消したモジュールが残っている、のどれかがあると、段を選んだ実行は
終了コード 2 で止まり、test_tiers も赤になる（新しい重いテストが黙って fast に入らないように）。

heavy に置く物: git のリポジトリを作る（git init・commit・mktarget・dogfood の clone）・Archon を起こす・
golden を再生する・プロセスの木を起こす。短くても、これらを使うモジュールは heavy に置く（負荷の高い機械では
git と子のプロセスが遅れの元になる）。秒は 2026-09-27 に負荷 60〜110 の機械で nice -n 19・`-p <モジュール>` で測った。
"""
import os
import pathlib
import sys
import unittest

TESTS = pathlib.Path(__file__).resolve().parent
PATTERN = "test_*.py"   # run.sh の discover と同じ

# 秒は 1 本ずつ回した壁時計（負荷は測った時の 1 分平均）
FAST = frozenset({
    "test_core_copy",       # 1〜3 秒
    "test_script_io",       # 2 秒（python を 1 本起こすだけ。git は使わない）
    "test_tiers",           # 8 秒（偽の uv・枠の台本で run.sh を起こす）
    "test_yaml_rules",      # 3 秒
})

HEAVY = frozenset({
    "test_accept",          # 140 秒（負荷 110）git
    "test_blk_fix",         # 116 秒（負荷 90）git・修正の後のテストを子で回す
    "test_blk_judge",       # 67 秒（負荷 87）git
    "test_blk_tests_delta", # 113 秒（負荷 87）git・プロセスの木
    "test_dev",             # 195 秒（負荷 60〜80）mktarget・dogfood の clone・偽の Archon
    "test_line",            # 5 秒（負荷 64）git init
    "test_script_headers",  # 5 秒（負荷 64）git・uv run
    "test_tree_run",        # 20 秒（負荷 62）プロセスの木
})

TIERS = {"fast": FAST, "heavy": HEAVY}


def modules():
    """unittest discover（-s tests -p test_*.py）が拾うモジュールの名前。tests/ の下に package は置かない"""
    return sorted(p.stem for p in TESTS.glob(PATTERN))


def problems():
    """段の一覧の食い違いを文の一覧で返す（空なら揃っている）"""
    found = set(modules())
    out = []
    unclassified = sorted(found - FAST - HEAVY)
    if unclassified:
        out.append("段の一覧に無いテストのモジュール: " + ", ".join(unclassified)
                   + "（tests/tiers.py の FAST か HEAVY に足す。git のリポジトリ・Archon・golden・プロセスの木を使うなら HEAVY）")
    both = sorted(FAST & HEAVY)
    if both:
        out.append("FAST と HEAVY の両方に在る: " + ", ".join(both))
    gone = sorted((FAST | HEAVY) - found)
    if gone:
        out.append("段の一覧に在るのにファイルが無い: " + ", ".join(gone))
    return out


class TierLoader(unittest.TestLoader):
    """discover の中で、段に入っていないモジュールのテストを空にする（-k・-p などの引数は discover がそのまま扱う）"""

    def __init__(self, keep):
        super().__init__()
        self.keep = keep

    def loadTestsFromModule(self, module, *args, **kwargs):
        if module.__name__ not in self.keep:
            return self.suiteClass([])
        return super().loadTestsFromModule(module, *args, **kwargs)


def main(argv):
    if len(argv) < 2 or argv[1] not in TIERS:
        print("tiers: 段は fast か heavy（使い方: python3 tests/tiers.py <段> [unittest の引数]）", file=sys.stderr)
        return 2
    bad = problems()
    if bad:
        print("tiers: " + " / ".join(bad), file=sys.stderr)
        return 2
    # `python3 -m unittest` と同じ sys.path の頭（作業フォルダ）にする。tests/ は discover が頭に足す
    sys.path[0] = os.getcwd()
    unittest.main(module=None, testLoader=TierLoader(TIERS[argv[1]]),
                  argv=["python -m unittest", "discover", "-s", str(TESTS), "-p", PATTERN, *argv[2:]])
    return 0  # unittest.main が終了コードで抜けるので、ここには来ない


if __name__ == "__main__":
    sys.exit(main(sys.argv))
