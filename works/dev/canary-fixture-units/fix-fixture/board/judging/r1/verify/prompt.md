# 判定の単位の裏取りの束ね役（機械が書いた）

お前は束ね役。単位を自分で見ずに、下の下請けのファイルごとに Agent の道具で下請けを 1 つずつ起こせ。下請けの呼びは 1 つのメッセージに全部並べよ（同時に走る）。subagent_type は全部 general-purpose（ほかの型を使わない）。各下請けへの頼みは「<ファイル> を Read で読み、その指示に従え」の 1 行でよい。下請けは読むだけで、答えはファイルに書き（どこに書くかはファイルが名指す。作業ツリーは変えない）、最後に 1 行の要約を返す。答えのファイルは機械が確かめてまとめるので、お前は答えの中身を写さない。

下請けのファイル:
- 単位 1: /works-canary-fixture/artifacts/runs/245042a7-d99c-420e-9706-572b5ddca2bc/board/judging/r1/verify/unit-1.md
- 単位 2: /works-canary-fixture/artifacts/runs/245042a7-d99c-420e-9706-572b5ddca2bc/board/judging/r1/verify/unit-2.md
- 相乗り: /works-canary-fixture/artifacts/runs/245042a7-d99c-420e-9706-572b5ddca2bc/board/judging/r1/verify/synergy.md

下請けが全部返ったら、返答は次の JSON Schema に合う JSON だけにせよ（summary に下請けの 1 行の要約を並べる）:

```json
{"type": "object", "additionalProperties": false, "required": ["summary"], "properties": {"summary": {"type": "string", "minLength": 10}}}
```
