# canary-lib-large

小さな道具の集まり（数の `stats.py`・字の `textfmt.py`・単位の換算の `units.py`・お金の `money.py`・URL の部品の `slugs.py`）。標準ライブラリだけで書き、テストは `python3 -m pytest -q`（unittest の形）で回す。
公開の関数は docstring に約束を書き、関数の約束は各関数の docstring が正本（`help()` で利用者に見える）。

## 決まり

- テストは `test_lib.py` の 1 本に置く。モジュールごとのクラス（`stats.py` は `TestStats`、`textfmt.py` は `TestTextfmt`、`units.py` は `TestUnits`、`money.py` は `TestMoney`、`slugs.py` は `TestSlugs`）の中に足し、新しいテストのファイルやクラスは作らない。モジュールは `import stats` の形で読み、関数は `stats.median` のように呼ぶ（`from stats import …` の行は書かない）。
- テストは関数の振る舞いを確かめる物だけで、docstring の有無や字はテストで確かめない。
