"""works のテストの段（fast・heavy）の一覧と、段を 1 つ選んで回す入口。

run.sh が WORKS_TESTS=fast|heavy のときに `python3 tests/tiers.py <段> [unittest の引数]` で起こす
（WORKS_TESTS が空なら run.sh は従来どおり全部を unittest discover で回し、ここを通らない）。
TDD の実行器 dev/tdd-suite.sh（pytest で回す）は `python3 tests/tiers.py paths <段>` で段のファイルの一覧を引く。
fast と heavy は重ならず、合わせるとちょうど全部（tests/test_*.py）になる。どのモジュールも FAST か HEAVY の
どちらかに書く。書き忘れ・両方に書いた・消したモジュールが残っている、のどれかがあると、段を選んだ実行は
終了コード 2 で止まり、test_tiers も赤になる（新しい重いテストが黙って fast に入らないように）。

heavy に置く物: 試験ごとに git のリポジトリを作る（git init・commit・mktarget・dogfood の clone）・uv run を起こす・
Archon を起こす・golden を再生する・プロセスの木を起こす・決まった秒を待つ。短くても、これらを使うモジュールは heavy に置く
（負荷の高い機械では git と子のプロセスが遅れの元になる）。種の git を tests/gitkit.py の型（プロセスに 1 回だけ作る）の
写しで配るだけなら、試験ごとに作るに当たらない。段は使う物の形で分ける（決まっていて、読めば確かめられる）。
fast は秒の上限ではない（負荷の高い機械では fast の中の git・子のプロセスも遅れる）。下の秒は目安で、2026-09-27 に
nice -n 19 で 1 本ずつ測った（負荷は各行）。gitkit を使う 5 本（accept・blk_fix（線 A Task 12 で盤面を作るので heavy へ移した）・blk_judge・blk_tests_delta・dev）は、
gitkit に替えた後の値（前と続けて回した組。計測の shim 込み）。
"""
import os
import pathlib
import sys
import unittest

TESTS = pathlib.Path(__file__).resolve().parent
PATTERN = "test_*.py"   # run.sh の discover と同じ

# 秒は 1 本ずつ回した壁時計（負荷は測った時の 1 分平均）
FAST = frozenset({
    "test_blk_judge",       # 3.8 秒（負荷 15）種の git は gitkit の型の写し・スクリプトを子で起こす
    "test_core_copy",       # 1〜3 秒
    "test_core_verbatim",   # 写しと元の commit のバイト一致（git show で読むだけ。リポジトリを作らない）
    "test_gl_map",          # 線 A: 対応表の JSON と accept.py を読むだけ
    "test_gitkit",          # 1 秒未満（gitkit の型を 1 回作って 2 回写す）
    "test_layers",          # 層と依存の向き（裁定 R59）: pack のファイルと YAML を読むだけ
    "test_halt",            # 線 A: 止め札を一時の盤面に置く・stop.sh を偽の Archon（sh の台本）で起こす・python を 8 本同時に起こす（git・uv・木なし）
    "test_node_marker",     # 線 A: 印の文字列を組んで読むだけ
    "test_sp_skills",       # superpowers の写し: 写しと元（プラグインのキャッシュ）を読んで比べる・sh を起こす（git なし）
    "test_script_io",       # 2 秒（python を 1 本起こすだけ。git は使わない）
    "test_tiers",           # 8 秒（偽の uv・枠の台本で run.sh を起こす）
    "test_yaml_rules",      # 3 秒
})

HEAVY = frozenset({
    "test_accept_v1_golden",# 盤面の層: golden の盤面・再生・種の git
    "test_board_begin",     # 盤面の層: golden の盤面・再生・種の git
    "test_board_engine_run",# 盤面の層: golden の盤面・再生・種の git
    "test_board_fixtures_real",# 盤面の層: golden の盤面・再生・種の git
    "test_board_goldens_fixture",# 盤面の層: golden の盤面・再生・種の git
    "test_board_open",      # 盤面の層: golden の盤面・再生・種の git
    "test_board_replay",    # 盤面の層: golden の盤面・再生・種の git
    "test_board_round_note",# 盤面の層: golden の盤面・再生・種の git
    "test_board_steps",     # 盤面の層: golden の盤面・再生・種の git
    "test_board_table",     # 盤面の層: golden の盤面・再生・種の git
    "test_adapter",         # 包み: 包みと偽の claude を子で起こす・プロセスの木・git のリポジトリ
    "test_blk_eyes",        # 独立の目（R11）: golden の盤面の再生（boardreplay）・一時の pack の写し・スクリプトを子で起こす
    "test_blk_ci",          # 線 A: 試験ごとの種の git（linekit.seed_repo）・スクリプトを子で起こす
    "test_blk_fix",         # 線 A Task 12: 試験ごとの種の git（linekit.seed_repo）と盤面（entry.start）・スクリプトを子で起こす
    "test_blk_pr",          # 線 A: 試験ごとの git のリポジトリ・golden の盤面の再生（boardreplay）
    "test_blk_material",    # 素材集め（R3）: 種の git（linekit.seed_repo）で盤面を 2 種類作る（クラスに 1 回）・スクリプトを子で起こす
    "test_blk_purpose",     # 試験ごとの git のリポジトリ（git init）・スクリプトを子で起こす
    "test_blk_refix",       # 線 A: 試験ごとの種の git（linekit.seed_repo）で盤面を差分の審査まで進める・スクリプトを子で起こす
    "test_blk_rejudge",     # 線 A: golden の盤面の再生（rejudgekit）・スクリプトを子で起こす
    "test_entry",           # 線 A: 試験ごとの種の git（linekit.seed_repo）・プロセスの木（tree_run）
    "test_edge",            # 線 A: 試験ごとの種の git（linekit.seed_repo）・golden の盤面の再生（boardreplay）・スクリプトを子で起こす
    "test_policy",          # 線 A: 試験ごとの種の git（linekit.seed_repo）
    "test_rejudge",         # 線 A: golden の盤面の再生（rejudgekit）・git
    "test_reads",           # 線 A Task 6: 種の git（linekit.seed_repo）と盤面（entry.start。クラスに 1 回）・フックとスクリプトを子で起こす
    "test_ticket",          # 線 A: git のリポジトリと worktree 2 つを作る（クラスに 1 回）
    "test_accept",          # 15.3 秒（負荷 15）うち 11.5 秒は受け付けの racy-git の待ち（accept.py。決まった秒）
    "test_blk_tests_delta", # 12.0 秒（負荷 15）uv run・プロセスの木・止めた後に 4 秒待つ
    "test_dev",             # 17.1 秒（負荷 14）mktarget・dogfood の clone・偽の Archon
    "test_line",            # 5 秒（負荷 64）git init
    "test_script_headers",  # 5 秒（負荷 64）git・uv run
    "test_tree_run",        # 20 秒（負荷 62）プロセスの木
    "test_tdd_suite",       # TDD の実行器 dev/tdd-suite.sh: uv run で本物の pytest を起こす（偽の小さな試験だけを回す）
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


def paths(tier):
    """段のモジュールのファイル（works の根から。名前の順）。dev/tdd-suite.sh が pytest に渡す"""
    return sorted(f"{TESTS.name}/{m}.py" for m in TIERS[tier])


def main(argv):
    if len(argv) >= 2 and argv[1] == "paths":
        if len(argv) != 3 or argv[2] not in TIERS:
            print("tiers: 使い方: python3 tests/tiers.py paths <fast|heavy>", file=sys.stderr)
            return 2
        bad = problems()
        if bad:
            print("tiers: " + " / ".join(bad), file=sys.stderr)
            return 2
        print("\n".join(paths(argv[2])))
        return 0
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
