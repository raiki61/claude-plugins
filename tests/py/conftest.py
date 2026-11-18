"""ルートの pytest の置き場（tests/py/）の共通の支度。

- チェック（飛ばしは失敗・テストが 1 件も無いファイルは失敗）は graphloops の置き場の fence.py をそのまま使う（読むだけ）。fence は固定の名前で
  自分を登録するので、1 回の起動に 2 つの置き場は載らない——この置き場は python3 -m pytest tests/py の別の起動で回す
  （その起動を載せた門の有無は MIGRATION.md の「門と CI の段」）
- 集めたテストの数の定数は置かない（2026-11-18 にやめた。理由は fence.py の頭）
"""
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.append(str(HERE.parents[1] / "graphloops" / "tests" / "py"))
import fence  # noqa: E402


def pytest_configure(config):
    fence.install(config, HERE)
