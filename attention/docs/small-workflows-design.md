# works-factory の block を小さな Workflow に分けて持ってくる設計（最初の 1 本は世界の解）

- **状態（2026-11-20）**: 案。頼み c36cfd（この設計を依頼した要求の番号）。実装・版上げ・実走はしていない。
- **読み手と求める物**: 読み手は持ち主。求めるのは、次のセクション「持ち主に決めてほしい点」の 2 点への可否の返事。
- **何の文書か**:
  - works-factory（持ち主の別のリポジトリ。以下「工場」）は、レビューの判定を block（単独で回せる部品の流れ）を並べて回している。
  - この文書は、その block を 1 本ずつ小さな Workflow（Claude Code の dynamic workflow。script が裏のエージェントを決まった順に回す仕組み。以下 DW）にして attention に持ってくる形を決める。
  - superpowers のスキル集のように、小さな部品を 1 本ずつでも、並べても使える形にする。
  - 最初に作る 1 本は世界の解（世の中の実務家がその種類の問題をどう解いているか）の DW で、その設計を詳しく書く。
- **今の重い版との関係**: 今の重い版 `/attention:my-turn-deep`（attention 0.72.0。Workflow `my-turn-dig`。設計は [my-turn-dig-redesign.md](my-turn-dig-redesign.md)）は残す。この文書は重い版を変えない。
- **例に使う PR と番号**:
  - #2555・#2635・#2637 は、重い版を走らせた guided-resolver の PR の番号。
  - L9・L6 などの L の番号は、重い版の記録の指摘の台帳の 1 件。N79・N63 などの N の番号は、重い版の問いの木の 1 つの問い（ノード）。記録は `~/src/github.com/IL-SW-AI/guided-resolver/.git/attention/my-turn/<PR>.json`。
  - どの番号が見落としかは、窓口（持ち主と話して部署に仕事を配る会話）が 2026-11-20 に重い版の記録と照合した結果（`/tmp/dig-analysis/recheck-<PR>.md`。英語）による。一時の置き場で、消えうる。この文書は要る所をその場に書き写した。
- **工場の読んだ版**: 工場のファイルは全部 commit `fe793dd96fba966a339dc6a78aa5647f49d0e394`（観点の写しの台帳 `attention/perspectives/COPIED_FROM` と同じ commit）で読んだ。以下、工場のファイルはこの commit のパスで書く。

## 持ち主に決めてほしい点

1. **世界の解の DW の実装と、1 回の測りに進んでよいか**:
   - 次の頼みで、セクション 3 の世界の解の DW と、それを手で起動するスキルを実装する。
   - その後、#2555 で 1 回走らせ、重い版の前の記録と並べて比べる（セクション 8）。いちばん大きな見落としを拾えなければ、外れた段を直した版をもう 1 回だけ走らせる（合わせて 2 回まで）。
   - 見込みの額は 1 回 10〜25 USD（2 回なら 20〜50 USD）。重い版は前の記録を使うので走らせない。
   - 推しは「可」。PR #2555 のいちばん大きな見落としを、世界の解の DW が拾えるかを最初に確かめたい。
     - 見落としの中身: PR は処理を止めて答えを受けて再開する仕組みを自作したが、世の中の普通の作りは、LLM が聞く専用のツールを呼び、そのツールの中で止める。重い版はこれを指摘にできなかった。
2. **下書きの前の照合を、どこまで機械に任せるか**:
   - 案 A（推し）: 照合の DW（セクション 2 の 8 番目の verify）だけにする。
     - 照合の DW は、持ち主の「妥当か確認して」と同じ 3 つの問い（前提が成り立つか・比べた相手は正しいか・投稿の価値があるか）を、下書きの候補の 1 件ずつに、書いた目と別の目で問う。
     - 下書きは投稿されず、持ち主はどのみち読んで決める。
     - そのため、途中で持ち主に止めて聞く所を足さない。
   - 案 B: 照合の DW の後でも、持ち主の目の照合を待ってから下書きを出す。
     - PR #2635 では、持ち主の「妥当か確認して」で下書き 8 件のうち 5 件が崩れたので、照合の DW の効き目が測れるまで人の目を残す。
     - そのかわり、持ち主の手間は今と同じになる。
   - どちらでも、照合の DW そのものは作る。分かれるのは、照合の DW の後に止まるかだけ。

後で問うこと（今は決めなくてよい）: セクション 8 の測りの後で、重い版の問いの木で世界の解を問う部分（木のルートの類 5）を、世界の解の DW に替えるか。

## この文書の要点

- **DW から DW は呼べるが、使わない**（セクション 1）:
  - 呼ぶ口 `workflow()` は、Claude Code の中にある書き方の参照（workflow-authoring）にだけ在り、公開の文書には無い。
  - 呼べる深さは 1 段だけ。
  - 公開の文書は、段の間で人が見るなら段ごとに別の Workflow にせよと書いている。
  - そのため、並べるのは手順書（スキル）にし、DW の間の受け渡しと照合は機械（Python の台本）がする。
- **小さな DW は 8 本で、工場の judge の順に並べる**（セクション 2）:
  1. lines（PR を依頼の行にする）
  2. premises（前提の測り直し）
  3. purpose（目的の 1 文）
  4. world（世界の解）
  5. prior（前の決め）
  6. lens（観点で見る）
  7. findings（指摘にまとめる）
  8. verify（下書きの前の照合）
  - prior と lens は並べて回す。
- **世界の解の DW は、重い版の世界の解が #2555 で落とした 3 つの原因（3.1）を止める**（セクション 3）:
  - 問いを PR の形から切り離す。
  - 比べる相手を「依存しているライブラリと上流 → 同じ種類の製品 → 標準 → 一般の構造」の順に、相手ごとに答えさせる。
  - 答えの 1 件ずつに、比べた相手と層（作り・外との約束・実装）を付けさせる。
  - 抜き書きは、機械が同じ URL から取り直して照合する。取り直すのは、Python の台本を打つだけの安いエージェント（haiku）で、照合するのは台本。
- **重い版の部品の使い回し**（セクション 4）:
  - 使い回す物: 前処理・根拠の写しの照合・指摘の台帳・反証・報告の照合・起動の合図の止め。
  - 使い回さない物: 問いの木とその上限、種類の 1 文、17 段の流れ。

## 語

- **DW**: Claude Code の dynamic workflow。JavaScript の script が裏のエージェントを順に回す。script 自身はファイルもシェルも触れない（https://code.claude.com/docs/en/workflows の「Behavior and limits」）。
- **block**: 工場の、単独で回せる部品の流れ。入力と出力（port）を持ち、AI の段と機械の段を並べる。
- **依頼の行**: 工場の block が受ける入力の 1 行 `{where, text}`。この文書では、PR が作る仕組みと、PR が書いた主張を 1 行ずつにした物を指す。
- **問題の種類**: 依頼の行を、解き方と対象の名前を外して言い直した物。工場の語では「類」（class）。
- **比べる相手**: 世界の解を探す先。依存（依存しているライブラリと上流）・製品（同じ種類の製品）・標準・一般の構造（差分を見せない目が目的から描いた形）の 4 つ。
- **層**: 比べる高さ。
  - 作り: どの部品がどの責任を持つか、処理がどこで止まり、誰が聞くか。
  - 外との約束: ほかの部品や相手から見える形。API・プロトコル・仕様・HTTP の状態など。
  - 実装: 1 つの部品の中のコードの書き方。
- **抜き書き**: 一次の出典から字のまま写した文。機械が同じ URL から取り直し、字のまま在るかを照合する。
- **受け付け**: AI の答えを機械が照合し、決まりに外れれば理由を付けて差し戻す段。工場は 3 回差し戻すと諦める。
- **台帳**: 掘って見つけた指摘を、機械が 1 件ずつに並べた一覧。黙って落とせないようにする（重い版の段 11）。
- **重い版の流れ**: 重い版 `my-turn-dig` は 17 の段（前処理・前提・問いの木・台帳・反証・下書きなど）を 1 本の Workflow で回す。段 11 などはその段の番号。
- **問いの木**: 重い版が、PR から問いを立て、子の問いに割って掘る木。1 つの問いがノード（N の番号）。ノードの数に上限（80）があり、上限で削られた問いは掘られない。
- **観点**: レビューで見る角度（例: 前の決めとの食い違い・テスト・名前）ごとの指示文。工場の観点の指示文 19 本を attention に写してある（`attention/perspectives/`）。工場の judge は、そのうち 10 本を「素材の観点」（下書きの材料を出す観点）として並べて回す。
- **judge**: 工場の、レビューの判定の流れ（block を並べた物。`workflows/judge/works-factory-judge.yaml`）。この文書の小さな DW の順の元にする。
- **FNV の照合の値**: 文の字から機械が数える短い指紋（FNV というハッシュの数え方）。受け渡しの途中で字が変わっていないかを、値を数え直して照合する。重い版も根拠の写しの照合で使う。
- **haiku・sonnet・opus**: Claude のモデルの名。安い順に haiku・sonnet・opus。
- **MRTR**: MCP（AI がツールを呼ぶ共通の仕様）の仕様の 1 つ。サーバーはツールの呼び出し（`tools/call`）を受けたとき、仕事に入る前に「入力が要る」という返事（`InputRequiredResult`）を返せる。クライアントは答えを付けて同じ呼び出しを送り直し、サーバーは続きから再開する。
- **W1・W2・W10**: 重い版の段（エージェントの役）の番号。W1 は仕組みと前提を出す構造の段、W2 は遮断の目、W10 は反証の 2 体。
- **体**: エージェント 1 つの呼び出しを数える単位。
- **定義の側のモデル**: エージェントの定義ファイル（`convergence-loops:blind-judge` など）に書かれたモデル。呼ぶ側で上書きしない。
- **遮断の目（W2）**: 重い版の遮断の目の段。差分もリポジトリも見ずに、目的から設計を描く（セクション 4）。
- **行（rows）**: 世界の解の DW が返す 1 件。比べる相手 1 つ・層 1 つにつき 1 行。工場の「依頼の行」（上）とは別物。
- **unchecked・garbled・over**: 抜き書きの数え方（3.6・3.8）。unchecked は取り直しが走れず照合できなかった数。garbled は FNV の値が合わず、写し違えと分かった数。over は類ごとの上限（6）を超え、取らずに数えただけの数。
- **種類の 1 文（`kind`）**: 重い版が PR ごとに書く、PR がどの種類の問題を解くかの 1 文。依頼の行の `kind`（仕組みか主張か）とは別物。

## 1 DW から DW を呼べるか

### 1.1 答え

技術の上では呼べる。ただし公開の文書に無い口で、深さは 1 段だけ。

- workflow-authoring（Claude Code に入っている、DW の script を書くための参照）に `workflow(nameOrRef, args?)` が在る。
  - 「run another workflow inline as a sub-step and return whatever it returns」
  - 「The child shares this run's concurrency cap, agent counter, abort signal, and token budget」
  - 「Nesting is one level only: workflow() inside a child throws」
- 公開の文書（https://code.claude.com/docs/en/workflows ）には `workflow()` の記述が無い。2026-11-20 に取り直した本文で探した。
  - 同じ文書の「Behavior and limits」の表には「No mid-run user input」と在る。
  - その行の対処の列は「For sign-off between stages, run each stage as its own workflow」。
  - 同じ表に「No direct filesystem or shell access from the workflow itself | Agents read, write, and run commands」とも在る。
- Agent SDK の参照（https://code.claude.com/docs/en/agent-sdk/typescript の「Workflow」）には、Workflow のツールの入力（`script`・`name`・`scriptPath`・`args`・`resumeFromRunId`）だけが在り、入れ子の記述は無い。

### 1.2 並べる形の決め: 手順書（スキル）が DW を順に呼ぶ

`workflow()` で束ねる DW は作らない。手順書（スキル）が DW を 1 本ずつ起動し、機械の台本が前の結果を次の入力に組む。理由は次の 4 つ。

1. **公開の文書が、段の間で止める形を「段ごとに別の Workflow」としている**。持ち主に決めてほしい点 2 の案 B のように、照合の DW の後で人が見る道を残すには、この形が要る。
2. **DW の間に、シェルとファイルの要る機械の照合が入る**。依存の取り出し・根拠の写しの照合・台帳の照合などで、DW の script はシェルもファイルも触れない。スキルの手順なら、台本をそのまま打てる。
3. **1 本ずつ単独で回せる**。束ねる DW から呼ばれる子は、その中でさらに `workflow()` を呼べない（深さ 1 段）。部品を 1 本でも並べても使う形（superpowers の形）と合う。
4. **公開の文書に無い口に、流れの全部を乗せない**。`workflow()` の振る舞いが変わっても、部品は 1 本ずつ動く。

この形の弱い所と、その手当て:
- 前の DW の返りを、スキルの会話が写して次の DW に渡すと、写し違いが起きうる。
  - 手当て: 台本（セクション 2.2 の `steps-prep.py --next`）が次の args の JSON を組み、FNV の照合の値（重い版の根拠の照合で使う短い指紋）を付ける。
  - DW は script の中で同じ値を数え直し、合わなければエージェントを立てずに止める。
- 会話の文脈が DW の返りで膨らむ。
  - 手当て: 返りはファイルに保存し、会話には件数と止まった理由だけを読ませる（重い版の `--save-record` と同じ形）。
- 段ごとに起動の許しを聞かれる（許しの形は公開の文書の「Approve the plan before it runs」）。
  - 手動で打つ前提なので、そのままにする。

後で束ねる DW が要るか: セクション 8 の測りの後に、段の間で止める要が無いと分かってから考える。そのときも、束ねる DW の中から呼ぶのは機械の照合の要らない区切りだけにする。

## 2 小さな DW の一覧と並べる順

### 2.1 並べる順と、工場の judge との対応

工場の judge（`workflows/judge/works-factory-judge.yaml`）の順は次のとおり。
1. 依頼の取り込み（spec）
2. 並びの PR の点検（parallel-pr）
3. premises
4. purpose
5. world
6. 10 の素材の観点を並べて回す（prior-decisions を含む）
7. diagnose
8. verify

前の段の答えが固まってから、次の段が問う。この順は、前の段の答えを次の段の入力にするためにある。

- premises が測った制約を purpose が受ける（judge の YAML の 103〜110 行）。
- purpose の目的と手段を world が受ける（同じ YAML の 112〜121 行）。
- 観点の全部が diagnose に集まる（同じ YAML の 216〜279 行）。

ここに並べる順:

```text
lines → premises → purpose → world → ┬ prior ┬ → findings → verify → （スキルが下書きを書く）
                                     └ lens  ┘
```

工場との違いと理由:
- **lines を足した**: 工場の judge は依頼の行を入力で受けるが、PR のレビューでは依頼の行が無い。PR が作る仕組みと PR が書いた主張を、ここで行にする。
- **依頼の取り込み（spec）と並びの PR の点検（parallel-pr）は持ってこない**: 
  - spec は工場の受け入れの条件を書く段で、PR のレビューに当たる物が無い。
  - parallel-pr は、重い版の相乗りの段（同じ件を扱う open な issue・PR を探す段）が持つ。小さな DW に分けるのは、測りの後にする。
- **lens は、工場の lens block でなく、judge の素材の観点にした**:
  - 工場の lens block（`workflows/lens/`）は、直しの後の差分を利用者の入れたレビューの役で見る物で、judge に無い（`docs/design/lens.md`）。
  - judge で観点の役をするのは、素材の観点 10 本（judge の YAML の 123〜215 行）。そのうち `prior-decisions-run` は prior の DW が持つので、lens は残りの 9 本に当たる。
  - 観点の本文は、attention に写してある観点（`attention/perspectives/` の 19 本）を使う。工場の素材の観点は block の名で、写した観点は指示文の名なので、1 対 1 には揃わない。対応の表は、lens の DW の実装の頼みで作る（セクション 10）。
- **findings は工場の diagnose に当たる**: 観点の答えを指摘の単位にまとめる段。候補の一覧に無かったが、台帳と反証の置き場として要る。

### 2.2 DW の間の受け渡し

- 置き場:
  - 前の段の返りは、PR のリポジトリの git dir の中の `attention/my-turn/<PR>-steps/<DW の名>.json` に置く。
  - 重い版の `recordDir` と同じ所で、commit されない。
- 保存: スキルが DW の終わりの知らせの出力のファイルを、台本 `steps-prep.py --save <DW の名> <出力のファイル>` に渡して書く。
  - 台本は、返りの形（その DW の JSON Schema）を照合してから書く。
  - 照合に外れたら書かずに止める。
- 次の入力: `steps-prep.py --next <DW の名>` が、保存した前の段の返りから次の args を組んで出す。
  - FNV の照合の値も付け、スキルはその JSON をそのまま Workflow の args に渡す。
  - 入力の形の正本はこの台本 1 か所に置く。
- 台本の名前と置き場（`attention/scripts/steps-prep.py`）は実装の頼みで決め直してよい。
- 共有のコード:
  - DW の script は `import()` を使えない（公開の文書の「No module loading」）。
  - DW の間で同じ JS の関数（FNV・手段の語の取り出し・起動の合図の止めなど）を使うときは、重い版の `gen-prompts.mjs`（指示文を script に埋める生成の台本）を広げて、生成のときに各 DW へ埋める。
  - 埋めた写しが元と同じかは、試験で照合する。

### 2.3 DW ごとの中身

各 DW の中で AI が受ける指示文は英語で書く（AI だけが読む文。ルートの CLAUDE.md の「会話」）。持ち主に見せるフィールドの言語は、args の `lang` で決める。

工場から写す物の置き場と台帳は、どの DW も同じ形にする（世界の解の DW の形は 3.10）。
- 写す先は `attention/steps/<DW の名>/`。写した元は台帳 `attention/steps/<DW の名>/COPIED_FROM` に残す。
- 台帳の 1 行目は工場の commit。この文書の版では全部 `fe793dd96fba966a339dc6a78aa5647f49d0e394`。2 行目から、ファイルごとの写した元のパスと sha256 と「字のまま」か「書き替えた」か。
- 字のまま写した物は、試験で写しの sha256 が台帳と同じかを照合する。書き替えた物は、変えた所をこの文書の当たるセクションが正とする。
- 下の各 DW の「写す物」は、この台帳に載せる物の一覧。

#### 1. lines（PR を依頼の行にする）

- 問い: この PR は何の仕組みを作り、何を主張しているか。仕組みと主張を 1 行ずつ書く。
- 入力:
  - 前処理の値: PR の本文・差分・会話の写しのパス（重い版の手順 6・7 と同じ）。
  - 前の段の返り: 無い。
- 出力: `lines: [{n, where, text, kind: mechanism|claim, measured?}]`。
  - `measured` は、行が数・大きさ・在る無いを言うときに、その主張の字を写した物。
- 止める条件: 差分が空なら行を返さず `ok: true`・`lines: []` にし、後の DW は回さない。受け付けを 3 回外れたら `failed`。
- 機械でする所: `where` が差分に在るパスか `PR本文` かの照合・行の重なりの照合。
- AI でする所: 1 体（opus）。重い版の W1 と同じモデル（`attention/workflows/my-turn-dig.js:456`）。後の DW は全部この行から問うので、ここを安くしない。ツールは Read・Grep・Glob だけ。
- 写す物: 工場に当たる block が無い。重い版の構造の段（W1）の仕組みと前提（`mechanisms`）の指示を元にし、PR の種類の 1 文（`kind`）は持たない（理由はセクション 4）。

#### 2. premises（前提の測り直し）

- 問い: 依頼の行が言う数・大きさ・在る無い・届きうるを、この作業場で測り直すと本当か。
- 入力: `lines`、前に決着した指摘（`carried`）。
- 出力: `constraints: [{text, measured_how, kind: 実測|仮説, measured_output?, contradicts?}]`。`contradicts` は食い違った行の番号。
- 止める条件: 次のどれかに外れたら差し戻し、3 回で `failed`。
  - `measured` を持つ行に対応する制約が無い。
  - 実測の行の出力が空。
  - `contradicts` が、依頼の行のどれにも無い番号を指す。
  - 作業ツリーが測りの間に変わった（これだけは DW の外。下の機械でする所）。
- 機械でする所:
  - 上の初めの 3 つは、DW の script の受け付けにする（工場 `workflows/premises/src/steps.py:111-167` の `check_claims`・`measured_needs_output`・`contradicts_unknown` を JS に移す）。
  - 作業ツリーの照合（工場の `_tree_unchanged`。git とファイルを読む）は、DW の script ではできない（script はシェルもファイルも触れない）。`steps-prep.py --next premises` が作業ツリーの状態の値を控え、`steps-prep.py --save premises` が同じ値かを照合し、違えば保存せずに止める。差し戻しでなく止めになるのは工場と違う所で、測り直すには DW を打ち直す。
- AI でする所: 1 体（sonnet）。ツールは Read・Grep・Glob・Bash（読むだけを指示の文で縛る）・WebSearch・WebFetch。
- 写す物:
  - `workflows/premises/prompts/premises.md` を元にする。
  - 部品の `query-rule`・`rejected`・`sandbox-shell` は `workflows/.shared/prompts/` から。
  - 工場の実測の 2 例（4MB と書いて実は 5,411 バイト・「CI が無い」と書いて `test.yml` が在った）も持ってくる。

#### 3. purpose（目的の 1 文）

- 問い: この PR の本来の目的を、手段を外して 1 文で書く。
- 入力: `lines`・PR の本文・`constraints`。
- 出力: `{purpose_text, source, means[], known_weaknesses[], leaked[]}`。
  - `source` の値は「PR 説明・計画・タスク記述・作者の要約・目的不明」のどれか。
- 止める条件:
  - 手段の語が目的の文に残ったら、語を添えて 1 回問い直す（重い版の `leaksOf`。`attention/workflows/my-turn-dig.js:1172-1189`）。
  - 問い直しても残れば `leaked` に入れて進む。
  - 目的の出典が無いときは「目的不明」で進む（工場と同じく止めない）。
- 機械でする所: 手段の語の照合（重い版の `meansWords` をそのまま使う）・出典のファイルが追跡されている普通のファイルかの照合（工場 `workflows/purpose/src/sourcefiles.py`）。
- AI でする所: 1 体（opus）。ツールは Read・Grep・Glob・WebSearch・WebFetch。
- 写す物: `workflows/purpose/prompts/purpose.md`・`src/sourcefiles.py`。
- 種類の 1 文は返さない: #2555 では、種類の 1 文にまた PR の解（止めて再開する）が入った。世界の解の DW は種類の 1 文でなく、問題の種類から問う（セクション 3）。

#### 4. world（世界の解）

セクション 3 に詳しく書く。
- 入力: `lines`・`purpose_text`・`means`・依存の一覧。
- 出力: 行ごとの比べの一覧で、相手と層つき。

#### 5. prior（前の決め）

- 問い: 差分が触る所について、ADR・先送りの台帳・断った issue と PR・閉じた issue に、決まった事は在るか。依頼の行がそれを覆さないか。
- 入力: `lines`・差分の範囲（base と head）。
- 出力:
  - `settled: [{topic, decision, reason, revisit, where}]`
  - `conflicts: [{decision, where, why}]`
  - `checked`・`searched[]`
- 止める条件:
  - いつも回す（工場の「当たらない」を許さない形。`workflows/prior-decisions/src/viewpoint.py:15`）。
  - 探せなかったら `checked: false` で返し、止めない。
- 機械でする所: 根拠の写しの照合（重い版の `--quotes`）。
- AI でする所: 1 体（sonnet）。ツールは Read・Grep・Glob・Bash（`git log`・`gh` を読むだけ）。
- 写す物:
  - 工場の `workflows/prior-decisions/prompts/prior-decisions.md`。
  - attention に写してある観点 `prior-decisions-check`。
- verify もこの返りを使う。#2637 の L9 は、持ち主が認めた #2542 の設計を覆していた。

#### 6. lens（観点で見る）

- 問い: 観点ごとに、差分をその観点だけで見る。
- 入力: 差分・`purpose_text`（観点が目的を伏せるもの〔`code-hygiene-review`〕には渡さない）・`constraints`。
- 出力: 観点ごとに `findings: [{where, cite, why, layer?}]`。
- 止める条件:
  - 返らなかった観点は `missing` に名を入れて進む（工場の judge の `diagnose-in` と同じ）。
  - 差分が空なら回さない。
- 機械でする所:
  - 観点の選びと埋め込み。重い版の LENSES と同じく、script が観点を名指して渡す。
  - 根拠の写しの照合。
- AI でする所: 観点ごとに 1 体。並べて回す。モデルは観点ごとに決める（重い版の段の表に倣う）。
- 写す物:
  - 観点の本文は写してある 19 本（`attention/perspectives/COPIED_FROM`）から選ぶ。
  - 当てる観点の組は、工場の素材の観点 10 本から `prior-decisions-run` を除いた 9 本を元にする（`docs/design/judge-eyes.md:90-91`）。
    - 9 本: `purpose-review`・`local-review`・`consistency-bypass`・`hygiene`・`external-standards`・`procedure-trace`・`test-double-fidelity`・`main-path-observation`・`provenance`。
    - 名の近い写しが在る物（例: `test-double-fidelity`・`code-hygiene-review`・`citation-provenance`）も、中身が同じかは実装の頼みで読み比べてから決める。
- コードの行の不具合を探す観点は入れない（セクション 6）。

#### 7. findings（指摘にまとめる）

- 問い:
  - premises の食い違い・world の違い・prior の衝突・lens の答えを、指摘の単位にまとめる。
  - 1 件ずつ、この PR の設計で決めることか、細部か、好みかを決める。
- 入力: 前の 6 本の返り全部。
- 出力: 台帳 `ledger: [{id, state, claim, locations, evidence, from, verdict, label, level, route, why}]`。形は重い版の台帳と同じ（`attention/skills/my-turn-deep/SKILL.md` の材料の説明）。
- 止める条件:
  - 前の段の答えのうち、どの件にも入らず、落とす決まりも名指さない物が在れば、その答えを報告だけの件として台帳に足す。
    - #2555 では、答えを持つ N79・N80 が台帳に載らなかった。
  - 反証の段のモデルが、書いた段と同じなら止める（重い版の `refuter model equals writer model`）。
- 機械でする所:
  - 台帳の組み立てと、落ちた物の足し戻し。
  - 下書きの決まり（`draftToReport`。`attention/workflows/my-turn-dig.js:1643-1644`）。
  - 根拠の写しの照合。
- AI でする所:
  - まとめる役 1 体（opus）。
  - 件ごとに反証 2 体。重い版の W10 で、誤検出だと示そうとする目と、具体の失敗の筋書きを組む目。
  - 行き先を決める役 1 体。重い版の段 13。
- 写す物:
  - 工場の diagnose（`workflows/diagnose/`）からは、素材が返らなかった観点の名を台帳に残す決まりだけを持ってくる。
  - diagnose の本体（$3.18・11 分。`docs/standalone-blocks.json`）は、重い版の台帳と反証の方が attention の報告に合うので写さない。

#### 8. verify（下書きの前の照合）

セクション 5 に詳しく書く。
- 入力: 台帳で行き先が `draft` の件と、前の段の返り。
- 出力: 件ごとに `{id, keep|rewrite|drop, premise, against, worth, why, rewrite?}`。
- この返りを受けて、スキルが下書きを書く。
- 止める条件:
  - `draft` の件が 0 なら、エージェントを立てずに空の返りを返す。
  - 件の目の答えが受け付け（3 つの問いの答えが全部在る・`drop` と `rewrite` には理由が在る）に 3 回外れたら、その件を `missing` に入れて `keep` にしない。スキルは `missing` の件を下書きにせず、報告に「照合できなかった」と書く。
  - 照合の目のモデルが、件を書いた段（findings のまとめる役）と同じなら止める（findings の DW と同じ照合）。
- 機械でする所: 受け付け・`against` と `layer` の照合（5.2 の 2）・開き直した URL の抜き書きの照合（3.6 の台本）。
- AI でする所: 件ごとに 1 体（sonnet。まとめる役の opus と別にする）と、件の間の食い違いを見る 1 体。
- 写す物: 工場の `workflows/verify/prompts/judge-verify.md` と `src/steps.py` の形（5.4）。

## 3 世界の解の DW（最初の 1 本）

### 3.1 役と、重い版の世界の解との違い

依頼の行ごとに、世の中の実務家がその種類の問題をどう解いているかを、一次の出典の抜き書きつきで集め、PR の解き方と比べる。

重い版の世界の解は、仕組みの 1 件ずつに 1 つの問いを立てて木に入れていた。
- 問いの文は「World's solution: how do OSS, standard tools and standard procedures solve the problem this mechanism solves: <仕組み>?」（`attention/workflows/my-turn-dig.js:297`）。
- 問いの文に PR の仕組みの文がそのまま入るので、答えは PR の形を枠にしやすい。
- 木のルートの類 5 として、ほかの問いとノードの上限 80 を取り合った。
- #2555 では、10 件のうち 8 件（N81〜N88）が上限で削られた。答えた 2 件（N79・N80）も、PR の形を枠にして答えた（`/tmp/dig-analysis/recheck-2555.md` の 5 と 2）。

この DW は次の 4 つの手で、上の 3 つの原因（問いの文に PR の形が入る・上限の取り合い・答えが PR の形を枠にする）を止める。1 と 2 は 1 つ目と 3 つ目、3 は 3 つ目、4 は 2 つ目に当たる。
1. 問いを、解き方と対象の名前を外した問題の種類に言い直してから立てる（3.3）。
2. 世の中の解を探す役に、PR の解き方を渡さない。比べるのは別の役にする（3.4・3.5）。
3. 比べる相手を順に、相手ごとに答えさせ、答えに相手と層を付けさせる（3.4）。
4. 類の数に上限を置かず、ほかの DW と上限を取り合わない（工場 `docs/design/world.md` の 9.1 の 12 と同じ）。

### 3.2 入力

args の値（`steps-prep.py --next world` が組む）:
- `caller`: 起動の合図（セクション 7）。
- `sum`: args の FNV の照合の値。
- `lines`: lines の DW の返り。`[{n, where, text, kind}]`。
- `purpose`: purpose の DW の `purpose_text`。
- `means`: purpose の DW の `means`。
- `deps`: 依存の一覧。`[{name, version, ecosystem, imported_by_touched}]`。
  - 前処理の機械が、差分が触るファイルに近いマニフェスト（`package.json`・`pyproject.toml` など）とロックファイル（`uv.lock`・`pnpm-lock.yaml`・`package-lock.json` など）から取る。
  - `imported_by_touched` は、差分が触るファイルが import しているか。
  - 取れない言語は、宣言された依存だけを並べ、その旨を `deps_note` に書く。
- `lang`: 持ち主に見せるフィールドの言語。
- `models`: 段ごとのモデル。既定は 3.9。

依存の一覧を足した理由:
- 工場の世界の解は、対象を読まずに上の類へ上がる形で、依存も読まない（`docs/design/world.md` のセクション 6 の終わり）。
- 一方、#2637 の L9 は、この画面が使う assistant-ui を比べる相手に入れなかった。#2555 の正しい形（assistant-ui の `onResumeToolCall`・LangGraph の interrupt）も依存の中に在った。
- ここでも AI には対象を読ませない。機械が第三者の名と版だけを取り出して渡す。
- 外への検索に第三者の名を入れてよいのは、工場の検索の決まり（`workflows/.shared/prompts/query-rule.md`）が許している。

### 3.3 段の並び

1. **起動の合図と args の照合**（機械）: `caller` が許された値でないか、`sum` が合わなければ、エージェントを立てずに止める。
2. **言い直し**（AI 1 体・opus・ツールなし。受け付けで最大 3 回）:
   - 依頼の行ごとに、問題の種類の文・活動・検索語（3 つまで）・この種類に関わる依存の名を返す。
   - PR の解き方の文（`proposed`）も返す。これは比べる役にだけ渡り、探す役には渡らない。
3. **手段の漏れの照合**（機械と AI 1 体・sonnet・ツールなし）:
   - 機械: 依頼の行の識別子と、手段の語（重い版の `meansWords`）が、問題の種類の文と検索語に無いかを照合する。
   - AI: 「この問題の種類の文は、PR の解き方を前提にしているか」を問う。言い直しと別のモデルにする。
     - #2555 の「処理を止め、答えを受けて続きから再開する」のように、識別子でない言い方で解き方が残る物を拾う。
   - どちらかに当たれば、理由を付けて 2 に差し戻す（この差し戻しも、2 の受け付けの最大 3 回の 1 回に数える）。
4. **類を決める**（機械）: 言い直しに出た類を全部、出た順に並べる。上限を置かない。
5. **探す役**（類ごとに AI 1 体・sonnet・ツールは WebSearch・WebFetch だけ。受け付けで最大 3 回。類の間は `pipeline()` で並べる）:
   - 類の文・検索語・関わる依存の名と版だけを渡す。依頼の行・PR の解き方・目的は渡さない。
   - 3.4 の順に相手ごとの行を返す。
6. **抜き書きの取り直し**（類ごとに AI 1 体・haiku・ツールは Bash だけ。3.6）:
   - 台本を 1 回打ち、出力をそのまま返すだけの役。
   - 合わなかった抜き書きを落とす。依存の行の抜き書きが全部落ちたら、理由を付けて 5 に 1 回差し戻す（この差し戻しも、5 の受け付けの最大 3 回の 1 回に数える）。
7. **一般の構造**（類ごとに AI 1 体・ツールなし・遮断の目）:
   - 類の文だけから、この種類の問題を持つ物は普通どう分けて作るかを描かせる。
   - 重い版の W2 の遮断の目（`attention/workflows/my-turn-dig.js:1220-1229` の `askW2`）の決まりを使い回す。目は差分もリポジトリも PR の文も見ない。目のエージェントは、重い版と同じく convergence-loops の `blind-judge`（args の `blindJudge`）で、無ければツールを禁じた既定のエージェントにする。
   - 指示の文は W2 の物（`attention/prompts/W2_PROMPT.md`。script に埋めた形は `my-turn-dig.js:222-236`）をそのまま使わない。W2 は PR 全体の種類の 1 文と目的を受け、後半で目的からのゼロからの設計を毎回問う。類ごとに 10 回呼ぶと、目的全体の設計を 10 回描かせることになる。ここでは W2 の前半（部品の分け方・流れ・正本の置き場・依存の向き・境目を理由つきで）だけを、類の文を受ける形に書き替える。
   - 5 と並べて回す。
8. **比べる役**（類ごとに AI 1 体・opus・ツールなし）:
   - 5〜7 の行と、2 の `proposed`（PR の解き方）を受け、相手の行ごとに同じ・違う・解き方なしを返す。7 の一般の構造の行にも付ける。
   - 違えば「PR は X をする。定石は Y。…でない限り Y を選ぶ」の形の文を返す。
   - 違ってよいかは決めない（それは verify の問い）。
9. **終わり**（機械）:
   - 行を組み、根拠の印（web か knowledge）を付ける。
   - 返らなかった類・諦めた類・照合できなかった抜き書きの数を名指す。

探す役と比べる役を分けた理由:
- 工場の web の役は、類と一緒に依頼の解き方（`proposed`）も受け、探しながら比べる（`workflows/world/prompts/parts/world-judge.md`）。
- 探す目が先に PR の形を知ると、その形に合う出典を探しやすい。#2555 の 3.1 の 3 つ目の原因（世界の解の問いも、PR の形を枠にして答えた）がこれに当たる。
- 比べる役はツールを持たないので、費用は類ごとにツールなしの 1 回だけ増える。

### 3.4 比べる相手の順と層

探す役は、類ごとに次の順で相手を探し、相手ごとに 1 行を返す。

1. **依存と上流**: 言い直しが「この類に関わる」とした依存の 1 つずつについて、その依存の公式の文書か公式のリポジトリ（版に合う物）で、この類の問題をどう解く口を持つかを探す。
   - 口が無ければ、探した検索語と開いたページを添えて「口が無い」と返す。
   - 上流（PR が包んでいる相手の仕様。プロトコルや API）もここに入れる。
2. **同じ種類の製品**: 同じ種類の問題を持つ公開の製品（OSS）を 2 つ以上名指し、それぞれがどう解くかを返す。
   - 見つからなければ、探した検索語を添えて「見つからない」と返す。
3. **標準**: この類に当たる標準（RFC・仕様・公式のガイド）が在れば、その箇所を返す。無ければ無いと返す。
4. **一般の構造**: 3.3 の 7 の遮断の目が描いた形。web を使わないので、根拠の印はいつも knowledge になる。

順に並べた理由:
- 近い相手ほど、PR が採れる直し方の費用が小さい。依存が既に持つ口を使うのがいちばん安い。
- 写してある観点 `reinvention-check` の「Only declared dependencies count as "already at hand"」と、手元に在って使っていない口を探す決まりも、この順の根拠。
- 遠い相手（一般の構造）だけで決めると、#2637 の L6 のように、どの製品もしていない形（他人の id を 404 で隠す）を推してしまう。

行ごとに付けるフィールド:
- `against`: `{kind: dependency|product|standard|general, name, version?}`。どの相手と比べたか。
- `layer`: `architecture|contract|implementation`（作り・外との約束・実装）。どの層で比べたか。1 行に 1 つ。同じ相手を 2 つの層で比べるなら 2 行にする。
- `practice`: その相手がその層でどう解くか（1〜3 文。対象の名前なし）。
- `sources`: 抜き書きの id。
- `applies`・`not_applies`: この依頼にどう当たるか・当たらないか。

層を分ける決まり（探す役と比べる役の指示に書き、後の DW が使う）:
- ある層の答えを、別の層の結論に使わない。
  - #2555: 外との約束の層の「MRTR はサーバーが仕事の前に問いを返せる」は、作りの層の「誰が聞くか」を決めない。
  - #2555 で比べる段が「違ってよい」とした理由は、この取り違えだった。
- 一般の構造の層の答えを、「製品はこうする」という結論に使わない（#2637 の L6）。
- `not_applies` の理由に、リポジトリの今の状態（設定・CI・置き方・今は無いツール）を使わない。
  - 探す役は対象を読まないが、依頼の行に今の状態が書かれていることがある。
  - #2635 の N63 は、版を上げるボットが無いという今の状態を土台に「世の中と同じ」とした。
  - 機械の照合: `not_applies` が空でない行は、その行自身の抜き書きを 1 つ以上持つ（外の事実で当たらないと示す）。
  - 抜き書きを持たずに返した行は、探す役に差し戻す（3.7）。
  - 抜き書きは在ったが取り直し（3.6）で全部落ちた行は、差し戻さずに `not_applies_unchecked: true` を付けて返す。探す役が直せる誤りか、ネットワークの都合かを DW は分けられないため。verify の DW は、この印の付いた行を「当たらない」の根拠に使わない（5.2 の 2）。

### 3.5 言い直しの決まり

工場の言い直しの役（`workflows/world/prompts/world-classes.md`）の決まりに、次を足す。
- 依頼の行ごとに 1 つずつ。番号は依頼の行の番号。1 つの依頼の行に 2 つの類を付けない（工場のまま）。
- `problem`・`activity`・検索語に、依頼の行の識別子（パス・ファイル・関数・フィールド・環境変数・部品の名・run の id）を書かない（工場の `banned_tokens`。`workflows/world/src/excerpts.py`）。
- 同じフィールドに手段の語を書かない（重い版の `meansWords`）。
- 解き方を前提にした言い方をしない。例: 「止めて再開する仕組み」でなく「処理の途中で人の答えが要る問題」と書く。AI の照合が見る（3.3 の 3）。
- この類に関わる依存の名を、渡した依存の一覧の中から選ぶ。一覧に無い名は弾く。`imported_by_touched` が真の依存を選ばないときは、理由を 1 文書く。
- `proposed`（PR の解き方）は、手段の文から写す（工場のまま）。

### 3.6 抜き書きの取り直し: 誰が取り直すか

DW の script は web を開けない（公開の文書の「No direct filesystem or shell access from the workflow itself」）。取り直す形は 3 つ考えた。

- 案 a（採る）: haiku のエージェントが台本を 1 回打つ。
  - 台本は工場の `lib/webget.py` と `workflows/world/src/excerpts.py` を字のまま写した Python（標準のライブラリだけ）と、その 2 つを呼ぶ入口の小さな台本（新しく書く）。
  - 上限の定数（`MAX_BODY`・`MAX_EXCERPTS`）は工場では `workflows/world/src/steps.py:51-53` に在り、写す 2 つには無い。入口の台本に同じ値を置き、台帳に `steps.py` の sha256 と「定数だけ写した」を書く。
  - エージェントは、渡されたコマンドを字のまま打ち、出力の JSON をそのまま返すだけ。
  - 行ごとに FNV の照合の値を付け、写し違えた行は照合せずに数える。
  - 重い版の根拠の写しの照合（`attention/workflows/my-turn-dig.js:1400-1440` の Quotes の段）と同じ形。
- 案 b（採らない）: WebFetch を持つエージェントに取り直させて比べさせる。
  - WebFetch は取ったページを小さなモデルで処理して返す（公式の文書 https://code.claude.com/docs/en/tools-reference の「WebFetch tool behavior」: 「Claude receives the result of that call rather than the raw page」「This makes WebFetch lossy by design」）。
  - 字のままの照合にならない。比べる目も AI になり、機械の照合でなくなる。
- 案 c（採らない）: スキルの会話が DW の後で台本を打つ。
  - 照合が DW の外に出る。そのため、合わなかった依存の行を探す役に差し戻す道（3.3 の 6）が DW の中で回らない。

案 a の台本がすること（工場と同じ）:
- https だけを開く。IP の直書きと localhost を断る（`webget.safe_url`）。
- 本文は 2 MB まで（`MAX_BODY`）。
- 本文を正規化してから、抜き書きが字のまま在るかを照合する（`excerpts.normalize`）。
  - 正規化の中身: HTML のタグと script を消す・NFKC・引用符とダッシュを揃える・Markdown の飾りを消す。
- 20 字より短い抜き書きは落とす（`MIN_EXCERPT`）。
- 類ごとの抜き書きは 6 つまで（`MAX_EXCERPTS`）。超えた分は取らずに数える。

案 a の弱い所:
- 走らせる側の Bash がネットワークに出られない設定（sandbox など）だと、台本が全部の取り直しに失敗する。
  - そのときは `ran: false` を返し、その類の行の根拠の印を全部 knowledge にして、照合できなかった数を返りに書く。黙って web の印を付けない。
- JavaScript で描くページは、取り直しの本文に抜き書きが無いことがある。
  - 落ちた割合は、セクション 8 の測りで数える。

### 3.7 受け付けの決まり（機械）

言い直し（3.3 の 2）:
- 行の数と番号が依頼の行と 1 つずつ合う。重なりが無い。
- 識別子と手段の語が、問題・活動・検索語に無い（3.5）。
- 検索語は類ごとに 3 つまで（工場の `MAX_QUERIES`）。
- 依存の名が依存の一覧に在る。

探す役（3.3 の 5）:
- 言い直しが関わるとした依存の 1 つずつに、`against.kind` が `dependency` で `name` がその依存の行が在る。口が無い行でもよい。
  - #2637 の L9 は、依存の assistant-ui を数に入れなかった。
- `not_applies` が空でない行は、その行自身の抜き書きを 1 つ以上持つ（3.4）。
- 製品の行が 1 つ以上在るか、探した検索語つきの「見つからない」が在る。
- どの行も `layer` が 3 つの値のどれか。
- `practice` と検索語に識別子が無い。
- 抜き書きは 20 字以上。`sources` の id は返した抜き書きの id。
- `url` は fetch で開いたページだけ（指示の文で縛る。機械では見えない）。

比べる役（3.3 の 8）:
- 行ごとの `verdict` が `same|differs|none` のどれか。
- `differs` なら `challenge` が 20 字以上（工場の `MIN_CHALLENGE`）。
- 「違ってよい」に当たる 4 つ目の値は持たない。

差し戻しの理由の文は前の回の分も全部、古い順に渡す（工場の 9.1 の 6）。3 回外れたら、その類を諦めて `missing` に入れ、ほかの類は続ける。

類を諦めたときの決め（工場と違う所）:
- 工場は、行が依頼の行と 1 つずつ揃わなければ、世界の解の全体を `failed` にして行を返さない（9.1 の 12）。一部だけ渡すより、落ちたと名指す側に倒すため。
- この DW は、揃わなくても揃った行を返し、`status: partial` と `missing`（諦めた類と最後の差し戻しの理由）を返す。
- 理由: 後の findings の DW が `missing` を「確かめていない」の件として台帳に足すので、黙って落ちない。全部を捨てると、#2555 で答えた 2 件のような答えまで消える。

### 3.8 返す形

```text
{
  ok, status: ok|partial|failed, reason,
  rows: [{
    n, where, class_id, problem, proposed,
    comparisons: [{
      against: {kind, name, version?}, layer,
      practice, sources: [{id, url, excerpt}], basis: web|knowledge,
      applies, not_applies,
      verdict: same|differs|none, challenge
    }],
  }],
  missing: [{n, why}],
  excerpts: {kept, dropped, unchecked, garbled, over},
  deps_note,
  counts: {classes, agents, stages}
}
```

- 行のフィールドは、工場の世界の解の行（`lib/world-row.schema.json` の finding・where・class_id・problem・activity・practice・sources・applies・not_applies・versus・basis）を、相手ごと・層ごとの `comparisons` に分けた物。
- 工場の 1 行に 1 つの `versus` は、相手ごとの `verdict` と `challenge` になる。
- 一般の構造（3.3 の 7）も `comparisons` の 1 行にする。`against.kind` は `general`・`name` は `blind`・`basis` はいつも `knowledge`。`layer` は遮断の目が描いた形の層（多くは `architecture`）で、比べる役が `verdict` を付ける。こうすると、5.2 の機械の照合（`general` の行だけで「違う」とした件を `report` に替える）が、ほかの相手と同じ形で組める。

### 3.9 モデルと費用の見込み

段ごとのモデル（工場の `docs/standalone-blocks.json` の world の「Claude Opus, effort high」と「Claude Sonnet, effort medium」の組に倣う）:
- 言い直し: opus。
- 漏れの照合: sonnet。言い直しと別のモデルにする。
- 探す役: sonnet。
- 取り直し: haiku。
- 一般の構造: `blind-judge` のモデル（定義の側の物）。無ければ重い版の `W2fallback`（W2 の遮断の目の代わりのモデル。opus・effort medium）と同じ。
- 比べる役: opus。PR の解き方と定石が同じか違うかの判断で、重い版がここで外したため。

1 回のエージェントの数（類が 10 のとき）:
- 言い直し: 1〜3 体
- 漏れの照合: 1〜3 体
- 探す役: 10〜30 体
- 取り直し: 10〜30 体
- 一般の構造: 10 体
- 比べる役: 10 体
- 合わせて約 40〜85 体

費用:
- 工場の実測は 1 回 0.19 USD・85 秒（`docs/standalone-blocks.json`。1 回だけ。類の数は記録に無い）。
- 重い版は 1 回 270〜300 体で約 100 USD（1 体あたり約 0.35 USD）。
- この DW は、探す役が web のページを読む分だけ 1 体が重いとみて、1 回 10〜25 USD を見込む。算出は、約 40〜85 体 × 約 0.35 USD で約 14〜30 USD。そこから、10〜30 体が安い取り直し（haiku）である分を見て下に寄せた見当で、厳密な計算ではない。実測で直す。

### 3.10 工場から写す物と台帳

写す先は `attention/steps/world/`。写した元は台帳 `attention/steps/world/COPIED_FROM` に残す。
- 1 行目に工場の commit（`fe793dd96fba966a339dc6a78aa5647f49d0e394`）。
- 2 行目から、ファイルごとの写した元のパスと sha256。
- 観点の写し（`attention/perspectives/COPIED_FROM`）と同じ形。

字のまま写す物（試験で写しの sha256 が台帳と同じかを照合する）:
- `lib/webget.py`（136 行）
- `workflows/world/src/excerpts.py`（146 行）
- `lib/world-row.schema.json`（22 行。3.8 の形の元として残す）
- `workflows/.shared/prompts/query-rule.md`（14 行）
- `workflows/.shared/prompts/rejected.md`（7 行）

元にして書き替える物（台帳に元の sha256 と「書き替えた」を書き、変えた所はこの文書の 3.3〜3.7 が正）:
- `workflows/world/prompts/world-classes.md`（41 行）: 手段の語の決まり・解き方を前提にしない決まり・依存を選ぶフィールドを足す。
- `workflows/world/prompts/parts/world-judge.md`（42 行）: 探す役と比べる役に分け、相手の順と層のフィールドを足す。
- `workflows/world/src/steps.py`（453 行）:
  - 受け付け（`class_problems`・`judge_problems`・`_check_excerpts`）と定数 `MAX_QUERIES`・`MIN_CHALLENGE`（`:51-52`）は、DW の script の JS に移す。
  - 定数 `MAX_EXCERPTS`・`MAX_BODY`（`:51`・`:53`）は、取り直しの入口の台本に置く（3.6）。
  - 写した Python の `excerpts.py` と同じ答えを出すかを、同じ入力で比べる試験を置く。

写さない物と理由:
- 工場の block の YAML と script の段（`intake.py`・`pick.py`・`finish.py` など）: 工場の実行の殻（Archon）の形で、DW では script の中の順になる。
- 工場の web が off の道（`world-judge-offline`）: DW は args の値で探す役を飛ばせるが、最初の実装では作らない。web の使えない会話では、取り直しと同じく、根拠の印を knowledge にして返る。

## 4 重い版の部品の使い回し

使い回す物:
- **前処理**（`attention/scripts/my-turn-prep.py` の `prep()`）:
  - head の食い違いで止める・base と差分を取る・`recordDir` を決める。
  - `CLAUDE_CODE_WORKFLOW_SUBAGENT_MODEL` が置かれていたら止める（反証を別のモデルにできないため）。
  - 差分を使う DW（lines・premises・prior・lens・findings・verify）の前に 1 回打つ。
  - 世界の解の DW の依存の取り出しは、この台本に足す。
- **根拠の写しの照合**（`--quotes -` と haiku の Quotes の段）: premises・prior・lens・findings・verify の根拠に使う。世界の解の抜き書きの取り直しも同じ形で作る（3.6）。
- **指摘の台帳と下書きの決まり**（段 11 の台帳・段 13 の行き先・`draftToReport`）: findings の DW に移す。
- **反証の 2 体**（W10。誤検出だと示そうとする目と、失敗の筋書きを組む目）と、反証と書いた段が同じモデルなら止める照合: findings の DW で使う。
- **報告の照合**（`--check-report`）: 並べる手順書の最後に打つ。台帳の番号と下書きの `ファイル:行` の漏れを見る。
- **起動の合図の止め**（`args.caller`）: 全部の DW に入れる（セクション 7）。
- **観点の写し**（`attention/perspectives/` と `gen-prompts.mjs` で指示文に埋める形）: lens と prior の DW で使う。
- **遮断の目**（W2。差分もリポジトリも見せずに描かせる役）: 目の決まりとエージェントの選び（`blind-judge`）を、世界の解の DW の一般の構造で使う。指示の文は前半だけを類の文向けに書き替える（3.3 の 7）。
- **下書きの書き方**（重い版のスキルの手順 12。直し方を書かない・印の決まり・箇所ごと）: 並べる手順書がそのまま使う。

使い回さない物と理由:
- **問いの木と、その上限**（W6〜W8 の木・ノードの上限 80・類ごとの割り当て）:
  - 木の上限を、世界の解の問いとほかの問いが取り合った。#2555 は世界の解の 10 件のうち 8 件、#2637 は 15 の問いが上限で削られた。
  - 小さな DW は DW ごとに範囲が決まり、上限を取り合わない。
- **PR の種類の 1 文**（Purpose の段の `kind`）:
  - #2555 で 2 度続けて PR の解き方が入った。
  - 世界の解の DW は類の文から問うので要らない（3.1）。
- **17 段の流れそのもの**（`my-turn-dig.js` の段の順）: 重い版として残し、小さな DW の中には持ち込まない。
- **ヘッドレスの形**（`my-turn-headless.py`。設定・フック・CLAUDE.md を読まない `claude -p` で回す）:
  - 最初の実装では使い回さない。小さな DW は 1 回が短く安く、会話の中で回して返りを見ながら直す方が速い。
  - ただし、裏のエージェントには作業場の CLAUDE.md が足される（workflow-authoring の「Subagents get the same CLAUDE.md files injected」）。探す役が対象の名前を知りうる。
  - セクション 8 の測りで、実際の検索語に対象の名前が出たら、世界の解の DW をヘッドレスの形でも回せるようにする。
- **記録の形の版 3**（`lib/my_turn_record.py`）: 木の形の記録で、小さな DW の返りと形が違う。DW ごとのファイル（2.2）にする。前の回の使い回し（`--prior`）は、測りの後に要るかを決める。

## 5 下書きの前の照合（verify の DW）

### 5.1 置く所

findings の DW の後、スキルが下書きを書く前に置く。照合するのは、台帳で行き先が `draft` の件だけ。`report` の件は照合しない（投稿しないので、持ち主の「妥当か確認して」が崩したのは下書きだった）。

### 5.2 問うこと

件ごとに、書いた段と別の目（モデルも変える）に、持ち主の「妥当か確認して」と同じ 3 つを問う。#2635 で崩れた 5 件と #2637 で落とした 3 件を、どの問いが拾うかを添える。

1. **前提が成り立つか**:
   - 件が立つ事実を、head のコードとツールの原典で確かめ直す。
   - ほかの所で既に守られていないか。
   - 件の筋書きが自分と食い違っていないか。
   - 拾う例:
     - #2635 の L7: 409 行目が既に守っていた。
     - #2635 の L10: 下書き自身が要るとした行を咎めた。
     - #2635 の L6: GitHub は最後の鍵を消させないので、筋書きが自分と食い違った。
     - #2635 の L4: 通知の話なのに、承認の話の行（`release-to-production.adoc:43`）を場所にしていた。
     - #2555 の L8: 「実の LLM で試していない」が、作者の 11/19 の実走で古くなっていた。
2. **比べた相手は正しいか**:
   - 件が根拠にした世界の解の行の、相手と層が、件の結論の相手と層に合うか。
   - 依存の行を飛ばしていないか。
   - リポジトリの今の状態を根拠にしていないか。
   - `not_applies_unchecked` の印の付いた行（3.4）を「当たらない」の根拠にしていないか。
   - 拾う例:
     - #2637 の L9: 依存の assistant-ui を数に入れなかった。
     - #2637 の L6: 一般の構造の層の話を、製品の層の結論にした。
     - #2635 の N63: 今の状態を土台に「世の中と同じ」とした。
   - 機械の照合: 世界の解の行が付ける `against` と `layer` を見る。`against.kind` が `general` の行だけで「違う」とした件は、`draft` から `report` に替える。
3. **投稿の価値があるか**:
   - この PR が触る部品の話か。
   - 持ち主が前に認めた決め（prior の DW の `settled`）を覆していないか。
   - 作者がこの件で何を直せばよいかが分かるか。
   - 拾う例:
     - #2637 の L3: 見積りのコメントにリリースの話を持ち込んだ。
     - #2637 の L9: 持ち主が認めた #2542 の設計を覆した。
     - #2555 の 1（`/tmp/dig-analysis/recheck-2555.md` の項目 1「下書きが多すぎる」）: 下書きは 9 件出たが、走らせた後の会話で、窓口は 9 件とも投稿しないよう勧めた（会話の後の勧め）。投稿する価値のある件が 0 件だった。

ほかに、件と件の食い違いを 1 体が見る（工場の verify の synergy の役）。#2637 の L2 と L32 は食い違ったまま残った。

### 5.3 答えの形と、その後

- 件ごとに `keep`（そのまま下書きにする）・`rewrite`（書き直す。直す所を `rewrite` に書く）・`drop`（下書きから外し、理由を付けて報告に回す）のどれかを返す。
- 世界の解の URL は、照合の目が自分で開き直す。開いた URL の抜き書きは、3.6 の台本で照合する。
  - #2635 と #2637 では、直し方の案の世界の解の URL を、案を書いた目が開いていなかった（「私は開いていない」）。
- スキルは `keep` と `rewrite` の件だけを下書きにし、`drop` の件は理由と一緒に報告に書く。
- 持ち主に決めてほしい点 2 が案 B なら、ここでスキルが止まり、照合の結果を見せて持ち主の答えを待つ。

### 5.4 工場から写す物

- 工場の verify（`workflows/verify/`）の形を写す。件ごとに 1 体と件の間の 1 体を並べて立て、答えのファイルを書かせる形（`prompts/judge-verify.md`・`src/steps.py`）。
- 問いの中身は工場と違う。工場の verify は、件を直すと依頼の症状が消えるか・理由が指す事実がコードに在るか・`key` の場所が直す場所かを問う。ここでは 5.2 の 3 つにする。
- 工場は verify を既定で切っている。元の works で 11 回・27 件が後ろの段を一度も変えなかったため（`docs/design/verify.md:84`）。
- ここで既定で回す理由: 重い版の下書きは、持ち主の照合で #2635 の 8 件のうち 5 件が崩れた。工場の測りと逆の事実が在る。
- 効き目はセクション 8 の後の測りで見る。後ろの段を変えないと分かったら、工場と同じく切る。

## 6 コードの行の不具合は `/code-review` に任せる

- 小さな DW は、コードの行の不具合（状態の取り違え・例外の道の漏れ・資源の漏れなど、1 か所の行で決まる誤り）を探さない。
  - #2637 で、別の `/code-review xhigh` が 4 件を拾い、重い版は拾わなかった。
  - 同じ所を 2 つの手順で探すと費用が二重になる。
- 分担の書き方:
  1. 並べる手順書のスキルの description と本文の冒頭に、「コードの行の不具合は探さない。それは `/code-review` が見る」と書く。
  2. 持ち主への報告の冒頭の 3 行の直後に、毎回 1 行で「コードの行の不具合は見ていない。`/code-review <PR 番号>` を別に打つ」と書く。手順書は `/code-review` を自分で起動しない（費用と強さの段階は持ち主が選ぶ）。
  3. lens の DW の観点の組に、行の不具合を探す観点を入れない。
  4. findings の DW で、反証の目が「1 か所の行の誤り」とした件は、落とさずに行き先を `report` にし、報告の「`/code-review` に回す物」のセクションに並べる。
  5. 持ち主が先に `/code-review` を打っていたら、その指摘を前の指摘（重い版の `priorFindings` の形）として渡し、同じ件の下書きを作らない。
     - 今の `kind` の値は `earlier`・`received`・`prior-run` の 3 つ（`attention/skills/my-turn-deep/SKILL.md:52`）で、`code-review` は無い。値を 1 つ足す（実装の頼みで、スキル・script・`my-turn-prep.py` を合わせて直す）。

## 7 起動は手動のみ

重い版と同じ 2 つで止める。
- **スキル**: 手で起動するスキルは、全部の frontmatter に `disable-model-invocation: true` を書く。
  - DW ごとに 1 本ずつ（例: `/attention:check-world`）と、並べる手順書 1 本（例: `/attention:my-turn-steps`）。
  - AI は自分から起動しない（https://code.claude.com/docs/en/skills の frontmatter の `disable-model-invocation`）。
- **DW の起動の合図の止め**:
  - 各 DW は、args の `caller` が許された値の一覧（その DW の手で起動するスキルの名と、並べる手順書の名）に無ければ、エージェントを立てずに `{stopped: 'caller', message}` を返す。
  - 重い版の `attention/workflows/my-turn-dig.js:434-440` と同じ形。
  - これは、AI が自分から Workflow のツールを呼んだときの歯止めで、鍵ではない（値を写せば通る）。
  - 人が DW を名前で直に打ったとき（プラグインの DW は `/attention:<名>` で打てる。公開の文書の「Distribute a workflow in a plugin」）も、`caller` が無いので止まる。
  - DW の `meta` には `disable-model-invocation` に当たる項目が無い（attention 0.72.0 の CHANGELOG）ので、`whenToUse` に「人が手順書を打ったときだけ」と書く。
- 並べる手順書は、ほかの手で起動するスキルを Skill のツールで呼ばない（`disable-model-invocation` のスキルは AI から呼べない）。DW を直に起動し、その `caller` には並べる手順書の名を入れる。

名前（`check-<DW の名>`・`my-turn-steps`・DW の `dig-<名>`）は仮で、実装の頼みで決め直してよい。プラグインの DW とスキルは同じ `/attention:<名>` の形で並ぶので、同じ名を付けない。

## 8 効き目の測り方

### 8.1 測る PR と、比べる相手

- 測るのは #2555。
  - 重い版の前の版と今の版（0.72.0）が、同じ head `c0c1848` で走っている。作者の直しで決着した見落としが無く、比べやすい（`/tmp/dig-analysis/recheck-2555.md` の冒頭）。
  - いちばん大きな見落とし（普通の作りは、LLM が聞く専用のツールを呼び、その中で止める）が、世界の解の問いで拾うべき物だった。
  - #2637 は新しい版の後に作者が `d2923f646` を push したので、head が揃わない。
- 比べる相手は、重い版の前の記録（`~/src/github.com/IL-SW-AI/guided-resolver/.git/attention/my-turn/2555.json`。版 3）。
  - 世界の解の問い 10 件（木のルートの類 5）の結果を使う。
  - 答えた 2 件は N79・N80、上限で削られた 8 件は N81〜N88。
  - 重い版は走らせ直さない。
- 世界の解の DW の入力:
  - 同じ記録の `structure.mechanisms` の 10 件を依頼の行にする。
  - `purpose.purpose` を目的にし、`purpose.means` を手段にする。
  - 依存の一覧は、同じ head で前処理が取る。
  - lines と purpose の DW はまだ無いので、記録の値を写す台本で args を組む。
  - 重い版と同じ材料から始めて、世界の解の段の違いだけを測るためで、記録の種類の 1 文（`kind`）は渡さない。

### 8.2 先に書いておく正解の札

走らせる前に、前の記録の後に、持ち主がその会話で深掘りして出た次の 3 つを、正解の札としてファイルに書いて commit する（走らせた後に札を変えない）。
1. 誰が聞くか（作りの層）: 普通の作りは、親の LLM が聞く専用のツールを 1 つ持ち、その中で止める。
   - 例: LangGraph の interrupt、assistant-ui の `onResumeToolCall`、Open WebUI の聞くツール。
   - `recheck-2555.md` の 5。
2. 再開の形（外との約束の層）: MRTR は続きからの再開を前提にし、LangGraph はノードを走らせ直す。PR の守りは、世の中の部品の上に乗る自作の 1 つ。
   - `recheck-2555.md` の 4。
3. 仕事の前に聞く（外との約束の層）: MRTR では、サーバーが仕事の前に `tools/call` へ問いを返せる。
   - `recheck-2555.md` の新しい件 L2。

### 8.3 数えること

- **拾えたか**（主な物差し）: 正解の札 3 つのそれぞれに当たる行が、`differs` で、正しい相手の種類（依存か標準）と正しい層で出たか。
  - 札 1 は、比べる相手が依存の LangGraph か assistant-ui の行が在り、作りの層で `differs` か。
  - 重い版の答えは、N79 が PR の形と同じとした（札 1 を外した）。
- **答えた数**: 依頼の行 10 件のうち、行を返した数と `missing` の数。重い版は 2 件。
- **手段の漏れ**: 言い直しの問題の文と検索語に、手段の語が残った数（機械で数える）と、漏れの照合で差し戻した回数。
- **抜き書き**: 残った数・落ちた数・照合できなかった数。根拠の印が web の行の割合。
- **検索語の漏れ**: 探す役が実際に打った検索語（DW の各エージェントの記録 `agent-<id>.jsonl` に残る WebSearch の呼び出し）に、対象の名前（リポジトリ名・パス・社内の部品名）が出た数。0 でなければ、セクション 4 のヘッドレスの形を足す。
- **費用と時間**: DW の全体の費用・時間・エージェント数。
  - 重い版の世界の解の部分の費用は、記録が段ごとの額を持たないので比べない。
  - 重い版の 1 回の全体（約 100 USD）の何割かだけを書く。

### 8.4 合否と、その後

- 合: 札 1 に当たる行が、8.3 の形（依存の LangGraph か assistant-ui の行・作りの層・`differs`）で出た。
  - 次の頼みで、重い版の世界の解の部分を替えるか（持ち主に後で問うこと）と、次の DW（lines・premises・purpose）の実装に進む。
- 否: 札 1 に当たる行が無いか、`same`・`none` だった。
  - 外れた段を、DW の各エージェントの記録から 1 つに決める（言い直しに解き方が残った・探す役が依存の行を返さなかった・比べる役が `same` とした、のどれか）。
  - その段だけを直し、同じ入力でもう 1 回走らせる。これが 8.5 の 1 対の 2 回目になる。
- 札 2・札 3 は合否に使わず、拾えた数を書くだけにする。札 1 が #2555 のいちばん大きな見落としで、世界の解の DW を作る理由だから。

### 8.5 額と回数

- 走らせるのは世界の解の DW の 1 回。8.4 で否なら、外れた段を直した版をもう 1 回だけ走らせる。合わせて 2 回までで、見込みは 1 回 10〜25 USD（3.9）、2 回なら 20〜50 USD。
- ルートの CLAUDE.md の「1 つの直しにつき 1 対まで」（確かめの試しは、前の版と直した版に 1 回ずつ頼む 1 対までにする決まり）の中に入る。1 対は、世界の解の DW の最初の版と、否のときに直した版の 2 回。重い版は前の記録を使うので、新しく走らせない。
- 会話の中の Workflow なので、`--max-budget-usd` は付けられない。
  - 歯止めは、類の数（依頼の行 10 件）と、受け付けの 3 回の上限。
  - 見込みの 2 倍（50 USD）を超えたら、測りの結果に書き、次の頼みで受け付けの回数か類ごとの抜き書きの上限を見直す。
- この頼み（c36cfd。冒頭の依頼の番号）では走らせない。持ち主に決めてほしい点 1 が可なら、実装の頼みの中で走らせる。

## 9 自分で決めた事と根拠

ルートの CLAUDE.md の「判断の線」（業界の定石・前に決めた事で 1 つに決まる物は、根拠を書いて自分で進める）で決めた物。

- **並べる形をスキルにした**: 公開の文書の「For sign-off between stages, run each stage as its own workflow」と「No direct filesystem or shell access」（セクション 1.2）。
- **lens を judge の素材の観点にした**: 工場の lens block は judge に無く、直しの後の差分を見る物（`docs/design/lens.md`・`workflows/judge/works-factory-judge.yaml:123-215`）。
- **lines と findings を足した**: PR のレビューには依頼の行が無いため。観点の答えを台帳にまとめる段が要るため（重い版の段 11 の決め）。
- **種類の 1 文を持たない**: #2555 で 2 度続けて解き方が入った。世界の解は類の文から問う。
- **探す役と比べる役を分けた**: 探す目が PR の形を知らないようにする。工場の「The request lines themselves are not given to you」（`workflows/world/prompts/parts/world-judge.md`）を、解き方にまで広げた。
- **依存の名と版を機械が渡す**: 工場の検索の決まりが第三者の名を許す（`workflows/.shared/prompts/query-rule.md`）。写してある観点 `reinvention-check` が、宣言された依存を先に見ると決めている。
- **類を諦めても揃った行を返す**: 返りの `missing` で名指し、後の DW が台帳に足すので、黙って落ちない（3.7）。
- **verify を既定で回す**: 工場の「既定で切る」の測り（27 件が後ろを変えなかった）と逆の事実（#2635 で 8 件のうち 5 件）が在る（5.4）。
- **測る PR を #2555 にした**: head が揃い、いちばん大きな見落としが世界の解の物（8.1）。

## 10 未確認

- `workflow()` に、ほかのプラグインの DW の名（`attention:dig-world` など）を渡せるか。この設計では使わない。
- DW の裏のエージェントに `agentType` で CLAUDE.md の足されない役を当てられるか。workflow-authoring には、組み込みの Explore と Plan が足さないとだけ在る。探す役に対象の名前を知らせない手として、測りの後に確かめる。
- 依存の取り出しの台本が、マニフェストの無い言語・モノレポの入れ子の `package.json` でどこまで取れるか。#2555 の作業場で実装のときに確かめる。
- 取り直しの台本を打つ haiku のエージェントの Bash が、持ち主の設定でネットワークに出られるか（3.6）。
- 世界の解の DW の args の大きさ（依頼の行 10 件・依存 数百件のとき）に上限があるか。
- prior・lens・findings・verify の DW の費用は見込みも書いていない。世界の解の DW の測りの後に、1 本ずつ設計を詰めるときに書く。
- 工場の素材の観点 9 本（`prior-decisions-run` を除く）と、attention に写した観点 19 本の対応。名の近い物も中身は読み比べていない。lens の DW の実装の頼みで表にする（2.1）。
