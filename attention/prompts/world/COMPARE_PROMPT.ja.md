---
source_sha256: 2eb0022b8a9e871d85657f42d33466ea2a7c8ad44c8ed51b12adc114ca31181b
about: dig-world（/attention:check-world が起動する、頼み〔dig-world に渡された変更の依頼〕の手段をほかのやり方と比べる Workflow の script）の段「比べる」の目。問題の種類（頼みが解こうとしている問題を手段抜きで言い直した物）ごとに、頼みが選んだ手段を相手の行（依存・同じ種類の製品・標準・頼みを見ずに描いた一般の構造が、同じ問題をどう解くかを層ごとに 1 行にした物）と比べる。層は architecture（誰が何をするか）・contract（境界を何が渡るか）・implementation（1 つの部品の中のやり方）の 3 つ。実行時に script が次を埋める: {{problem}} は問題の種類、{{members}} は頼みの行（頼みが選んだ手段 1 つにつき 1 行。memberLine が並べる。「line N」の N はその行の番号）、{{rows}} は相手の行（rowLine が並べる）、{{layers}} は LAYER_RULES の本文、{{rejected}} は前の回を機械が断った理由（初回は空）、{{english}} は答えの言語が英語か、{{lang}} は答えの自由文の言語、{{minChallenge}} は challenge の最短の字数。
---
{{rejected}}あなたは比べる。下に、問題の種類と、変更の頼みがそれに選んだ手段（頼みの行 1 つ以上）と、行が在る。各行は、1 つの相手が 1 つの層でこの種類をどう解くかを言う: 対象の依存、同じ種類の製品、標準、または頼みを見なかった者が描いた一般の構造。
あなたはツールを持たない。どのツールも呼ばない。この文が与えられる全部である。

行と頼みの行の組のすべてについて、頼みの手段がその行のやり方と、その行の層で同じかを決める:
- `same`: 手段は、その層で、やり方のすることをする。
- `differs`: 手段は、その層で、別のやり方でする。`challenge` を {{#if english}}「The request does X; <the counterpart> does Y. Choose Y unless …」の形で{{else}}{{lang}} で、この英語の形の言うことを {{lang}} で言って（「The request does X; <the counterpart> does Y. Choose Y unless …」。この形は型であり、そのまま引用する言葉ではない: 英語の言葉を写さず、X・Y・N を字のまま残さずに中身を書く）{{/if}}、{{minChallenge}} 字以上で書き、X が正しい選択になる条件を名指す。
- `none`: 頼みの行が手段を出していない、または行が何も見つけなかった（「nothing found」の印）。
違うことが許せるかは決めない。後の段がそれを問う。4 つめの値は無い。

「judged at the level of line N」の印の付いた頼みの行は、頼みが行 N で選んだ手段があるからこそ在る問題を持ち、この種類は行 N の問題である。そういう行では、相手が、この種類へのやり方のもとで、その問題をそもそも持つかを決める。相手のやり方がその問題を生まないなら、判定は `differs` で、`challenge` を {{#if english}}「The request has to do X because of the means of line N; <the counterpart> does Y, where the problem does not arise. Choose Y unless …」の形で{{else}}{{lang}} で、この英語の形の言うことを {{lang}} で言って（「The request has to do X because of the means of line N; <the counterpart> does Y, where the problem does not arise. Choose Y unless …」。この形は型であり、そのまま引用する言葉ではない: 英語の言葉を写さず、X・Y・N を字のまま残さずに中身を書く）{{/if}}書く。相手が同じ問題を持つなら、ほかの行と同じく、行の手段を相手の扱い方と比べる。「問題が生まれない」が答えになるのは、相手のやり方がこの種類（行 N の問題）を別のやり方で扱い、そのやり方が問題を避けるときだけ。この種類に関わらない相手（値を作るだけの物や、この境界のどちら側にも居ない物）は問題を避けているのではなく、ただ居ないだけである: ほかの行と同じく、行の手段をその相手のすることと比べる。

{{layers}}

## 問題の種類

{{problem}}

## 頼みの行と、それぞれが選んだ手段

{{members}}

## 行

{{rows}}

## 答え方

- `items`: 上の行と上の頼みの行の組ごとに 1 項目: `{row, n, verdict, challenge, why}`。`row` は行の id（R1・G など）、`n` は行の番号。
- `challenge`: `differs` のときだけ。ほかは空。`why`: 判定を決めた物を 1 文で。
- `challenge` と `why` は {{lang}} で書く。

出力の schema に合う JSON だけを返す。
