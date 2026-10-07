# canary-lib

小さな数の道具（calc.py）と字の道具（textfmt.py）。標準ライブラリだけで書き、テストは `python3 -m pytest -q`（unittest の形）で回す。
公開の関数は docstring に約束を書き、関数の約束は各関数の docstring が正本（`help()` で利用者に見える）。

## 決まり

- テストは `test_lib.py` の 1 本に置く。モジュールごとのクラス（calc.py は `TestCalc`、textfmt.py は `TestTextfmt`）の中に足し、新しいテストのファイルやクラスは作らない。モジュールは `import calc` の形で読み、関数は `calc.mean` のように呼ぶ（`from calc import …` の行は書かない）。テストは関数の振る舞いを確かめる物だけで、docstring の有無や字はテストで確かめない。
- 利用者に見える振る舞いを変えた直しは、CHANGELOG.md の `[Unreleased]` の、直したモジュールの見出し（calc.py は `### calc`、textfmt.py は `### textfmt`）の下に 1 行足す（何を直したかを関数の名で書く。1 関数 1 行）。docstring を足した・直した直しも、`help()` で利用者に見える約束が変わるので同じく 1 行足す。
