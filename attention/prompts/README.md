# my-turn-dig の指示文

`attention/workflows/my-turn-dig.js`（/my-turn の掘る流れの Workflow の script）が段ごとのエージェントに渡す英語の指示文のうち、観点（段が何を見て、どう判定するか）を、1 つの定数に 1 本の md で置く。データの並べ方と運び役の文は md にせず、script の中に書く（下の「md にする物・しない物」）。script はファイルを読めない（https://code.claude.com/docs/en/workflows の「No direct filesystem or shell access from the workflow itself」）ので、生成器 `attention/scripts/gen-prompts.mjs` が md から JS の関数を作り、script の頭の区画（`// ==== prompts (section 3) ====` から `// ==== end of prompts ====` まで）に書き戻す。区画は手で直さない。

- `<定数の名前>.md`: エージェントに届く英語の文。正本はこれ。
- `<定数の名前>.ja.md`: 持ち主が読む日本語の訳。頭の `source_sha256` は、訳した時の英語の md の sha256。`about` は、その文がどの段の何かの説明。エージェントには届かない。

## md にする物・しない物

md にするのは観点だけ。持ち主が資産として直す文で、訳を添える。データの並べ方の文と、運び役の文は md にせず、値を組むコードの隣に script の関数か式で書く。訳も付けない（持ち主 2026-11-18。頼み 0e03c3）。

- 並べ方の文: 値を決まった順に並べるだけで、何を見るかも、どう判定するかも言わない文。script の `stageText`（段の文の枠）・`PR_FILES_TEXT`（PR の差分と会話の置き場の一覧）・`leafClaim`・`smellClaim`・`fixClaim`・`groupClaim`（W10 が崩しにかかる主張の並べ方）。
- 運び役の文: 決まったコマンドを打たせて、その出力を返させるだけの文。script の `quotesText`（根拠の照合の段）。

## 読み方

- 各 md は、エージェントに渡す 1 本の文の部品（テンプレート）。単体で読むと `{{x}}` が展開されておらず、読む物（PR の差分）と返す形（出力のスキーマ）も入っていない。実行時に script が値を埋め、部品を繋ぐ。
- 繋ぎ方は script の `stageText` が決める。共通の決まり（`RULES.md`）、「## Stage <段>」の見出し、段の文（`W1_PROMPT.md` など）の順。W2 だけは共通の決まりを付けない。
- 段の文の頭の `{{prFiles}}` には、script の `PR_FILES_TEXT`（PR の差分と会話の置き場の一覧）が入る。md の頭のコメントの「the PR_FILES text」はこれを指す。
- W1〜W10 は掘る流れの段の名前（設計書 `attention/docs/my-turn-workflow-design.md` のセクション 3）。
- 用語（英語の md にも `.ja.md` にも、ここで 1 度だけ説明する）:
  - PR: pull request。「この PR」は、段の文の頭の `{{prFiles}}`（script の `PR_FILES_TEXT`）が指す PR。
  - 段: 掘る流れの 1 工程。W1 構造・W2 一般の構造・W3 比べる・W4 コードの臭い・W5 ルートを組む・W6 木を掘る・W7 束ねる・W8 漏れの点検・W9 直し方の案と相乗り・W10 反証。根拠の照合の段（Quotes）もある。W5 は script のコードが問いを組み、ほかの段はエージェントが答える（W4 は問いごと、W6 はノードごと、W10 は主張ごとに 1 つ立つ）。
  - 木・ノード・親・兄弟・葉（leaf）: W5 が作る「問いの木」。ノードは問い 1 つで、親は 1 つ上の問い、兄弟は同じ親の下の問い。葉は実物で確かめて答えが 1 つに決まった問い。
  - 掘る・鍵（key）: 問いを子の問いに分けて答えを出していくことを「掘る」と言う。鍵は木の中で問い 1 つを指す名前（id）。W7 は、新しい問いが木に既にある問いと同じなら、既存の鍵に束ねる。
  - 直しの案・組（group）・相乗り: どれも W9 が返す。直しの案（fix）は、決まった葉から組む直し方。組は、1 つの直しで一緒に片づく案か葉の束（one-fix）と、ほかの答えを壊す案（conflict）。相乗りは、同じ環境・仕組みを作る予定の open な issue・PR を探し、向こうに乗れるか・向こうがこちらの部品を使えるかを言う物（W9 が返すフィールドの名前は outside）。
  - 判定の語: W4 の verdict は、問題なら "smell"、問題でないなら "none"、読んでも決まらないなら "unverified"。何を臭いとみなすかの基準は、問いの文（`SMELL_QUESTIONS.md` の 5 問と W1 が足した問い）が決める。
  - `W6_SHARED.md`・`W6_PROMPT.md`: W6 の全ノードに共通の文と、ノード 1 つの文。`{{shared}}` に `W6_SHARED.md` の文が入り、`{{question}}`（そのノードの問い）・`{{paths}}`（ルートからの道）・`{{parentLocs}}`（親が見た在り処）は script の `w6Input` が組む。W7・W8・W9 の行のフィールドも同様に script が組む。
  - `{{limit}}`・`{{round}}`・`{{extraSmells}}` などの数: 実行時に script が渡す。md には値が無い。
  - `W5_*.md`: W5 が木のルートに置く問いの文。区分ごとに 1 本（align・prior・world・realTool・selfMade・removePremise・smell）。
  - W10 の主張: 反証の段（W10）が崩しにかかる主張の文。script の `leafClaim`・`smellClaim`・`fixClaim`・`groupClaim` が、順に、葉の答え・コードの臭いの答え・直しの案・直しの組を並べ、`W10_PROMPT.md` の `{{text}}` に入る。`W10_PROMPT.md` の頭のコメントの W10_LEAF・W10_SMELL・W10_FIX・W10_GROUP は、この 4 つの前の名前。
  - 根拠の「写し」（quote）と印: 根拠が指した行から 1 字も変えずに写した字。照合用に JSON の 1 行ずつに付く印は、script が付ける。
  - 「前の回」: 同じ PR に /my-turn を前に走らせた回。差分は、その回の head から今の head まで。
  - 「設計のセクション N」: 設計書 `attention/docs/my-turn-workflow-design.md` のセクション N。
- 返す形（`structure`・`notFound`・`comparable` などのフィールド）は script 側の出力スキーマで決まり、md には書かない。

## 指示文を直す手順

1. 英語の `<定数の名前>.md` を直す。受け取る値を足す・消すときは、頭の `vars:` も直し、呼ぶ側（`my-turn-dig.js` の区画の後のコード）で値を渡す。
2. `node attention/scripts/gen-prompts.mjs` を打って script の区画を書き戻す。壊れた md（下の「止まる物」）なら、書かずに理由を出して止まる。訳が古いと `warning:` の行に、`.ja.md` に書く `source_sha256` の値が出る。
3. `<定数の名前>.ja.md` の訳を英語に合わせて直し、`source_sha256` を 2 の値に書き替える。`node tests/my-turn-dig-dry.mjs prompts` を打ち、終わりの行が「PROMPTS_OK」なら揃っている。

訳だけを直すときは 3 だけでよい（ハッシュは英語の md の物なので変わらない）。英語だけを直して 2 か 3 を忘れると、main へ入れるゲート（空回しの試験の `prompts`）で止まる。

## md の書き方

頭（front matter）の `vars:` に、文が受け取る値と型を 1 行ずつ書く。`#` から後はコメント。

- `text`: 文字か数。`{{x}}` でそのまま入る
- `list`: 文字の一覧。`{{x|join:", "}}` で繋ぐか、`{{x|bullets}}` で 1 件ずつ `- ` を付けた行にする（空なら `- (none)`）
- `flag`: 真か偽。`{{#if x}}` の中でだけ使える
- 型の後に `?` を付けると null を許す（`{{#if x != null}}` で分けられる）

本文で使える物:

- `{{x}}`・`{{x|join:"区切り"}}`・`{{x|bullets}}`
- `{{x|or:"代わり"}}`: 値が空の文字か null（一覧なら繋いだ結果が空）のときに代わりの字を出す。`join` の後に繋げる
- `{{#if x}}…{{else}}…{{/if}}`: 文字は空でない、一覧は 1 件以上、flag は真のときに前を出す。`{{else}}` は省ける。`{{#if …}}`・`{{else}}`・`{{/if}}` だけを書いた行は、その行の改行ごと消える（`{{x}}` だけを書いた行は消えず、改行も残る）
- `[s6.1]` の形の印は、前の版の手順の文の番号で、そのまま残す（`tests/my-turn-dig-map.json` が照合する）

`form: list` を書いた md（`SMELL_QUESTIONS.md`）は、本文の `- ` の行が文字の一覧の定数になる。

## 止まる物

生成器は次の md を書き戻さずに止める。

- `vars:` に無い値を本文で使う・`vars:` に在る値を本文で使わない
- 知らないフィルタ・閉じの無い `{{#if}}`

作った関数は、`vars:` の値が渡されないか型が違うと、文を作らずに例外を投げる（`undefined` の字をエージェントに渡さない）。
