"""ルートの pytest の置き場（tests/py/）の共通の支度。

- 柵（飛ばしは失敗・件数の突合）は graphloops の置き場の fence.py をそのまま使う（読むだけ）。fence は固定の名前で
  自分を登録するので、1 回の起動に 2 つの置き場は載らない——置き場ごとに別の起動で回す（CI の段 pytest と pytest-root）
- 件数の定数はここに置く（tests/run.sh の ratchet.py が検査の置き場の大文字の整数の定数を拾い、突合の行を見る）
"""
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.append(str(HERE.parents[1] / "graphloops" / "tests" / "py"))
import fence  # noqa: E402

# 全件を回したときに集まるべきテストの数。上げるときも下げるときも実測値を書く
EXPECTED_ITEMS = 166


def pytest_configure(config):
    fence.install(config, HERE, EXPECTED_ITEMS)
