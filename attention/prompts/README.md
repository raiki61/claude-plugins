# my-turn-dig の指示文

`attention/workflows/my-turn-dig.js`（/my-turn の掘る流れの Workflow の script）が段ごとのエージェントに渡す英語の指示文を、1 つの定数に 1 本の md で置く。script はファイルを読めない（https://code.claude.com/docs/en/workflows の「No direct filesystem or shell access from the workflow itself」）ので、生成器 `attention/scripts/gen-prompts.mjs` が md から JS の関数を作り、script の頭の区画（`// ==== prompts (section 3) ====` から `// ==== end of prompts ====` まで）に書き戻す。区画は手で直さない。

- `<定数の名前>.md`: エージェントに届く英語の文。正本はこれ。
- `<定数の名前>.ja.md`: 持ち主が読む日本語の訳。頭の `source_sha256` は、訳した時の英語の md の sha256。`about` は、その文がどの段の何かの説明。エージェントには届かない。

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
- `{{#if x}}…{{else}}…{{/if}}`: 文字は空でない、一覧は 1 件以上、flag は真のときに前を出す。`{{else}}` は省ける。タグだけの行は、その行の改行ごと消える
- `[s6.1]` の形の印は、前の版の手順の文の番号で、そのまま残す（`tests/my-turn-dig-map.json` が照合する）

`form: list` を書いた md（`SMELL_QUESTIONS.md`）は、本文の `- ` の行が文字の一覧の定数になる。

## 止まる物

生成器は次の md を書き戻さずに止める。

- `vars:` に無い値を本文で使う・`vars:` に在る値を本文で使わない
- 知らないフィルタ・閉じの無い `{{#if}}`

作った関数は、`vars:` の値が渡されないか型が違うと、文を作らずに例外を投げる（`undefined` の字をエージェントに渡さない）。
