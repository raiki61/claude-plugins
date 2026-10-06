# canary-lib

小さな数の道具（calc.py）と字の道具（textfmt.py）。標準ライブラリだけで書き、テストは `python3 -m pytest -q`（unittest の形）で回す。

## 決まり

- 利用者に見える振る舞いを変えた直しは、CHANGELOG.md の `[Unreleased]` に 1 行足す（何を直したかを関数の名で書く）。
