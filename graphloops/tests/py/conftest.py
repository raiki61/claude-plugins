"""graphloops の pytest の置き場（graphloops/tests/py/）の共通の支度。

- engine を import できるように graphloops/ を sys.path の先頭に足す。mutmut は graphloops/ を graphloops/mutants/ に
  写して走らせるので、この置き場から 2 つ上（写しの側の graphloops/）を足せば、壊した写しの engine を読む
- 検証器（リポジトリの根の scripts/review-record.py）は、根を上へ辿って探す（mutants/ の写しからも同じ根に届く）
- 柵（飛ばしは失敗・件数の突合・台本の検査の件数と到達）は fence.py。件数の定数はここに置く（tests/run.sh の ratchet.py が
  検査の置き場の大文字の整数の定数を拾い、突合の行が 1 か所で緩んでいないかを見る）
- 盤面を端から端まで回す台本（graphloops/tests/simulate.py・simulate_review.py）を pytest から回す土台（fixture・選択肢
  --gl-driver・大きさの印・check の数え方）は glharness.py、途中の盤面を控えて 1 手から始める fixture wave は waves.py、
  層 2 の筋書き（出来事の列と回し手）の fixture scene は scenes.py、台本の check から移した先の印 moved_from と台帳は ledger.py
  （4 つとも pytest_plugins で載せる）
"""
import importlib.util
import json
import os
import pathlib
import shutil
import sys

import fence
import pytest

HERE = pathlib.Path(__file__).resolve().parent
PLUGIN = HERE.parents[1]
sys.path.insert(0, str(PLUGIN))
REPO = next((p for p in PLUGIN.parents if (p / "scripts" / "review-record.py").is_file()), None)
if REPO is None:
    raise RuntimeError(f"{PLUGIN} の上に scripts/review-record.py が無い——リポジトリの根が見つからない")

pytest_plugins = ("pytester", "glharness", "waves", "scenes", "ledger")
# 止める猶予の環境変数（engine/role_run.py の GRACE_ENV）は外して走る——外の土台の下で engine がこの一式を走らせると値を継ぎ、
# 既定の 5 秒を前提に子を止める検査が、その下でだけ崩れる（読めない値なら engine の import で全部落ちる）
os.environ.pop("GL_KILL_GRACE", None)

# graphcheck を同じプロセスで呼ぶ口（変異の道具 mutmut が差し替えた engine を見るため。別プロセスで走らせる検査は bash 側）
_spec = importlib.util.spec_from_file_location("graphcheck", PLUGIN / "scripts" / "graphcheck.py")
graphcheck = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(graphcheck)
REVIEW_GRAPH_PATH = PLUGIN / "graphs" / "review-loop.json"
REVIEW_VALIDATOR = REPO / "scripts" / "review-record.py"


@pytest.fixture(scope="module")
def sandbox(tmp_path_factory):
    """graphcheck はプロンプトと rules を graph の隣から読むので、graph を差し替える置き場に写しておく"""
    tmp = tmp_path_factory.mktemp("graphcheck")
    (tmp / "graphs").mkdir()
    shutil.copytree(PLUGIN / "prompts", tmp / "prompts")
    shutil.copytree(PLUGIN / "rules", tmp / "rules")
    shutil.copytree(PLUGIN / "blocks", tmp / "blocks")
    return tmp


def run_graphcheck(sandbox, g):
    """差し替えた review-loop の graph を置き場に書いて graphcheck に通す ——（通ったか, 出力の全文）"""
    path = sandbox / "graphs" / "review-loop.json"
    path.write_text(json.dumps(g, ensure_ascii=False), encoding="utf-8")
    lines = []
    ok = graphcheck.check(path, str(REVIEW_VALIDATOR), emit=lines.append)
    return ok, "\n".join(map(str, lines))

# 全件を回したときに集まるべきテストの数。上げるときも下げるときも実測値を書く
EXPECTED_ITEMS = 1645
# 全件を回したときに台本の check が走るべき件数と、到達すべき値の数（fence.py の 3）。上げるときも下げるときも実測値を書く
EXPECTED_SIM_CHECKS = 28
EXPECTED_SIM_REACHED = 2


# 変異の実行器（リポジトリの根の tests/mutate.py）の印の写しの pytest の回だけ立つ環境変数。立っていれば、各テストの間その値を
# テストの node id にする——印は行を通したテストをこの値で名指す（子のプロセスにも環境で届く）。名前の正本は tests/mutate.py の
# PYTEST_MARK（揃いは test_mutate_mark.py が縛る）
MUTATE_MARK = "GL_MARK_PYTEST"


@pytest.hookimpl(wrapper=True)
def pytest_runtest_protocol(item, nextitem):
    if MUTATE_MARK not in os.environ:
        return (yield)
    os.environ[MUTATE_MARK] = item.nodeid
    try:
        return (yield)
    finally:
        os.environ[MUTATE_MARK] = "?"


def pytest_configure(config):
    fence.install(config, HERE, EXPECTED_ITEMS)
    fence.expect_sim(config, EXPECTED_SIM_CHECKS, EXPECTED_SIM_REACHED)
