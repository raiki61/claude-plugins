---
source_sha256: 925083fcde9a173dcd180c1fc8bae88052ad0ab91cb30cfd72afed422a670a2a
about: dig-world（/attention:check-world が起動する、頼みの手段をほかのやり方と比べる Workflow の script）の層の決まり。相手の行（依存・同じ種類の製品・標準・頼みを見ずに描いた一般の構造が、問題をどう解くかの 1 行）を探す段（SEARCH_PROMPT）と比べる段（COMPARE_PROMPT）の両方に入る。層は architecture（誰が何をするか）・contract（境界を何が渡るか）・implementation（1 つの部品の中のやり方）の 3 つ。
---
## 層

どの行も、ちょうど 1 つの層で比べる:
- `architecture`: 誰が何をするか。部品の分け方と、どの部品がその仕事を持つか。
- `contract`: 境界を何が越えるか。部品の間を行き来する要求・応答・状態の形と、それぞれをいつ送ってよいか。
- `implementation`: 1 つの部品が中で仕事をどうするか。

相手が 2 つの層で言うことを持つなら、行を 2 つ出す。1 つの層の答えを、別の層の結論の代わりにしない: contract が許すことは、どの部品がその仕事をすべきかを言わない。一般の構造は、製品が何をするかを言わない。
