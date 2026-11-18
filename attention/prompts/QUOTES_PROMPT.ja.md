---
source_sha256: ef7d035f99742b90fa88d163b286f84b5988cbef3be6bc8f366eac85a242a87b
about: 写しの照合（セクション 3）。my-turn-prep.py は /my-turn の下ごしらえの script で、--quotes は根拠の引用が指した行に在るかを照合する。照合はコード（my-turn-prep.py --quotes）がし、この段は打って結果を写すだけ。command は <<'MY_TURN_QUOTES_END' から MY_TURN_QUOTES_END の行までのヒアドキュメント。
---
下のコマンドを、書いてあるとおりに 1 回だけ打ち、ほかに何もしない。どの行も 1 字も変えない（JSON の行の 1 つずつに印が付いていて、写し違えた行は照合されずに数えられる）。

```bash
{{command}}
```

コマンドは JSON のオブジェクトを 1 つ出す。その checked・missing（1 件ずつ {id, why}）・garbled をそのまま写し、ran を true、error を空にして返す。コマンドが失敗したか JSON を出さなかったなら、ran を false、checked を 0、missing と garbled を空にし、error にエラーの文を書いて返す。
