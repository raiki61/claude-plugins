"""graphloops の pytest の置き場（graphloops/tests/py/）の共通の支度。

- engine を import できるように graphloops/ を sys.path の先頭に足す。mutmut は graphloops/ を graphloops/mutants/ に
  写して走らせるので、この置き場から 2 つ上（写しの側の graphloops/）を足せば、壊した写しの engine を読む
- 検証器（リポジトリの根の scripts/review-record.py）は、根を上へ辿って探す（mutants/ の写しからも同じ根に届く）
- 柵（飛ばしは失敗・件数の突合）は fence.py。件数の定数はここに置く（tests/run.sh の ratchet.py が
  検査の置き場の大文字の整数の定数を拾い、突合の行が 1 か所で緩んでいないかを見る）
"""
import pathlib
import sys

import fence

HERE = pathlib.Path(__file__).resolve().parent
PLUGIN = HERE.parents[1]
sys.path.insert(0, str(PLUGIN))
REPO = next((p for p in PLUGIN.parents if (p / "scripts" / "review-record.py").is_file()), None)
if REPO is None:
    raise RuntimeError(f"{PLUGIN} の上に scripts/review-record.py が無い——リポジトリの根が見つからない")

pytest_plugins = ("pytester",)

# 全件を回したときに集まるべきテストの数。上げるときも下げるときも実測値を書く
EXPECTED_ITEMS = 76


def pytest_configure(config):
    fence.install(config, HERE, EXPECTED_ITEMS)
