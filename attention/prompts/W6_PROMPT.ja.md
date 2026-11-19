---
source_sha256: 9fe2ae29fcbc715975ad6ff9bfdf61c62f98bab2ffd45fc410515737b28a23df
about: W6 の 1 つのノードの文（セクション 6 が下に渡す物）。shared は W6_SHARED の文。paths・parentLocs の行は script の w6Input が組む。 lenses はルートの区分ごとの観点の文、again は段 9 の掘り直しのときだけ入る（設計書 my-turn-dig-redesign.md の段 7・段 9）。
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

{{lenses}}
{{#if again}}

このノードは前に "unverified" と答えられた。その答えと、何を読めば決まると書いたか:
{{again}}
それを手がかりに、もう 1 度答える。分けない: 子を返さず、"split" 以外の status を返す。
{{/if}}

あなたの問い（ここで決める。子には、その答えがあなたの答えを変える問いだけを渡す）:
{{question}}
