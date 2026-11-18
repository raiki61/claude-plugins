---
source_sha256: 2466f9de597517dd60f9998b5e9e4cde5ede08a073980f4f64d8d787be94759e
about: 段が読む PR の差分・前の回からの差分・会話の置き場の一覧（段の文の頭の {{prFiles}} に入る）。lock file は依存関係の固定ファイル。W1・W3・W4・W6・W8・W9・W10 の文の頭に置く。
---
- 差分のファイル（commit の一覧・--stat・-U10 の差分）: {{diff}}{{#if excluded}}（本文から外した lock file。--stat には在る: {{excluded|join:", "}}）{{/if}}
{{#if priorDiff}}
- 前の回の head {{priorHead7}} からの差分: {{priorDiff}}。そこに載る物は前の回の後に足された物。
{{/if}}
- PR の会話（本文・コメント・レビュー）: {{thread}}
