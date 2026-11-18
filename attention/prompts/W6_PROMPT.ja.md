---
source_sha256: 9fe2ae29fcbc715975ad6ff9bfdf61c62f98bab2ffd45fc410515737b28a23df
about: W6 の 1 つのノードの文（セクション 6 が下に渡す物）。shared は W6_SHARED の文。paths・parentLocs の行は script の w6Input が組む。
---
{{shared}}

## あなたのノード {{id}}

ルートからの道（問い・答え・仮定した物。祖先が決めた事を決め直さない。ただし前提は疑ってよい）:
{{paths|join:"\n"|or:"- （これはルート）"}}

親が見た所（在り処だけ）:
{{parentLocs|bullets}}
{{#if where}}

まず見る所: {{where}}
{{/if}}

あなたの問い（ここで決める。子には、その答えがあなたの答えを変える問いだけを渡す）:
{{question}}
