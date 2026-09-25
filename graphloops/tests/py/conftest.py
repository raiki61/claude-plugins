"""graphloops の pytest の置き場（graphloops/tests/py/）の共通の支度。

- engine を import できるように graphloops/ を sys.path の先頭に足す。mutmut は graphloops/ を graphloops/mutants/ に
  写して走らせるので、この置き場から 2 つ上（写しの側の graphloops/）を足せば、壊した写しの engine を読む
- 検証器（リポジトリの根の scripts/review-record.py）は、根を上へ辿って探す（mutants/ の写しからも同じ根に届く）
- 柵（飛ばしは失敗・件数の突合）は fence.py。件数の定数はここに置く（tests/run.sh の ratchet.py が
  検査の置き場の大文字の整数の定数を拾い、突合の行が 1 か所で緩んでいないかを見る）
"""
import importlib.util
import json
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

pytest_plugins = ("pytester",)

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
    return tmp


def run_graphcheck(sandbox, g):
    """差し替えた review-loop の graph を置き場に書いて graphcheck に通す ——（通ったか, 出力の全文）"""
    path = sandbox / "graphs" / "review-loop.json"
    path.write_text(json.dumps(g, ensure_ascii=False), encoding="utf-8")
    lines = []
    ok = graphcheck.check(path, str(REVIEW_VALIDATOR), emit=lines.append)
    return ok, "\n".join(map(str, lines))

# 全件を回したときに集まるべきテストの数。上げるときも下げるときも実測値を書く
EXPECTED_ITEMS = 224


def pytest_configure(config):
    fence.install(config, HERE, EXPECTED_ITEMS)
