# モデルと effort の目安: 部署を立てるときに model と effort を選ぶ

- 5.5 世代（Opus 5.5・Sonnet 5.5・Haiku 5.5。最上位は Fable 5.1）
- 5.5 では未測定（前の世代ではこうだった）
- 書き足し方
- 出典

dispatch のスキル（works-dispatch のプラグイン）の別ファイル。部署（作業ごとの worktree と、そこで働く Claude Code の会話の組）を立てる前に、会社の形（`.claude/company.toml`）の役や受け持ちに書く `model`・`effort`（書き方は同じフォルダの roles.md の「役の中身と起動方法」のセクション）の値を選ぶときに読む。

ここに在るのは事実の側だけで、「この仕事でこの格（Haiku・Sonnet・Opus・Fable）・effort なら、これだけの成績と費用だった」を並べる。どれを採るかの重み付け（正確さと費用のどちらを重く見るか）は書かない。それは会社ごとの会社の形と、会社ごとのリポジトリの AGENTS.md で決める。effort は、1 つのモデルの中で、考える量・ツールを使う回数・自分で確かめる量をまとめて決める設定で[^effort]、段は low・medium・high・xhigh・max の順に重くなる。数はどれも、断りの無い限り Anthropic か評価を作った会社が測ったもので、Anthropic は自分の仕事で測り直すよう書き、前の世代の設定を持ち越さないよう書く[^sweep]。そのため世代ごとに見出しを分ける。各数の出典（原典の URL・確かめた日・原文の一句）は、末尾の脚注に在る。

## 5.5 世代（Opus 5.5・Sonnet 5.5・Haiku 5.5。最上位は Fable 5.1）

2026-10-19 にまとめた。原典を確かめた日は脚注ごとに書く。

### 格の順・値段・既定の effort

- 費用と能力の順は、安い方から Haiku 5.5、Sonnet 5.5、Opus 5.5、Fable 5.1（最上位）である[^order]。
- 値段（100 万トークンあたりの入力・出力）は、Fable 5.1 が $10・$50、Opus 5.5 が $4・$20、Sonnet 5.5 が $2・$10、Haiku 5.5 が $0.10・$0.50（プロンプトが 10 万トークンまで）である[^price]。文脈の長さは 4 つとも 100 万トークン、出力の上限は 12.8 万トークンである[^context]。
- 既定の effort は、Opus 5.5 と Haiku 5.5 が medium、Sonnet 5.5 と Fable 5.1 が high である[^default][^default-table]。Sonnet 5.5 は low・medium・high で thinking（答える前にモデルが考えを書き出す仕組み）を切れるが、Opus 5.5 は thinking の切り替えを受け付けない、と CodeRabbit（コードレビューの製品の会社）は書く[^thinking-toggle]。
- Anthropic は、たいていのエージェントの仕事を Opus 5.5 の medium で始め、Opus 5.5 を上の段にしても足りないときに Fable 5.1 を使うよう書く[^start]。モデルを替える前に effort を調整するほうが効くことが多いとも書く[^effort-lever]。

### 定額の契約（Pro・Max）での重さ

- Claude Code の使用量の記事は、Opus は 1 ターンあたり Sonnet の数倍、Sonnet は Haiku より多く使うと書く[^plan-weight]。ただしこの記事の使用量の表が挙げるのは Enterprise の席と API キーで、Pro と Max に当たるとは言い切れない。定額の契約の上限に対するモデルごとの具体的な倍率は、ヘルプセンターの記事に書かれていない（2026-10-16 に探した範囲）[^plan-searched]。
- effort を上げると上限に早く届く[^plan-effort]。Max では Fable を週の上限の 50% まで使える[^plan-fable]。

### エージェントのコーディング

- CursorBench 4.0（実際の Cursor の会話から取った、複数のファイルにまたがる仕事）で、Opus 5.5 は medium 52.5%、high と xhigh 56.0%、max 57.8% だった[^cursor-opus]。medium は 1 タスク約 3 ドルで、max の Fable 5.1 より上だった[^cursor-cost]。
- 同じ評価で、Sonnet 5.5 は medium 39.2%、high 47.8%、xhigh 53.1%、max 55.5% だった[^cursor-sonnet]。medium から max までの差は、Sonnet 5.5 が 16.3 点、Opus 5.5 が 5.3 点である（上の数から引いた値）。Sonnet 5.5 の 1 タスクの費用は原典に無い。
- FrontierCode（マージできる差分を書けるかの評価。範囲外の変更を減点する）では、Opus 5.5 は medium より上の段で点が下がる[^frontiercode]。
- Terminal-Bench 4.0（コマンドラインの込み入った仕事）では、既定の段の Opus 5.5 が、max の Opus 5 を約 5 分の 1 の費用で上回った[^terminal]。外部の評価機関 Artificial Analysis の測りでは、Opus 5.5 の Terminal-Bench 4.0 は low 31%・medium 53%・high 57%・max 60% である[^aa-tools]。
- 込み入ったエージェントのコーディングには Sonnet 5.5 と Opus 5.5 が向き、Haiku 5.5 は範囲の狭い仕事に向く、と Haiku 5.5 の発表記事は書く[^haiku-scope]。
- Sonnet 5.5 は、低い effort では、プロンプトが求めない限り、確かめを走らせずに変更を済んだと報告することがある、と CodeRabbit は Anthropic の手引きから書く[^sonnet-low-check]。
- 顧客が自社で測った声として、Factory は medium を既定にしてよいと思えた初めてのモデルだと書き[^factory]、Deloitte はいちばん低い段の Opus 5.5 が high の Opus 5 より多くバグを見つけたと書く[^deloitte]。

### ツール使い・業務の流れ・長い文脈

- Artificial Analysis の 10 の評価では、Opus 5.5 の low から medium への伸びが medium から high への伸びより大きい評価が 7 つだった（表の数から数えた）[^aa-step]。ただし、10 のうち SciCode・AA-Omniscience・AA-LCR の 3 つは段の差が 1〜4 点で、表の数は整数に丸めてあるので、丸める前の値なら判定が変わりうる。Zapier の AutomationBench を Artificial Analysis が走らせた AutomationBench-AA（業務アプリを REST API のツールで回す。下の、Anthropic のシステムカードが載せる AutomationBench の数とは別の測り）は low 53%・medium 61%・high 63%・max 70% である[^aa-tools]。1 タスクの費用は low $0.55・medium $1.34・high $1.82、時間は約 80 秒・200 秒・273 秒である[^aa-cost]。
- 約 10 万トークンの長い文書を読んで答える AA-LCR では、Opus 5.5 は 81%・84%・83%・85%（low・medium・high・max）で、100 問の評価なので段の差は見分けられない（問題の数からの見立てで、原典がそう書いているのではない。同じ 100 問を全部の段が解く比べなので、揺れはこの見立てより小さいこともある）[^aa-lcr]。
- Zapier が作った AutomationBench を Anthropic がシステムカードに載せた数で、Sonnet 5.5 は max 44.7%（API の既定のフォールバック〔安全の仕組みが止めた仕事を代わりのモデルで続ける仕組み〕あり）、断りで終わった仕事をフォールバックありで走らせ直した Opus 5.5 は 42.5% だった[^automation-sonnet][^fallback]。
- 電子カルテのツールを使う医療のエージェントの仕事（PhysicianBench）では、Sonnet 5.5 の low と medium は見分けられず（27.2% と 30.0%）、その上は段ごとに伸びる[^physician]。医療の質問に答えるだけの評価では、回答の長さで補正した点なら low でほぼ全部の点が出て、補正しない点は max がいちばん高い[^health-qa]。

### 調べもの・知識の仕事

- 調べものの評価（DRACO）、知識の難問の評価（HLE）、物理の問題集で、Opus 5.5 の 1 体のエージェントは、low にすると medium より 13.3 点・3.4 点・14.0 点低く、典型の仕事の時間は 84%・30%・47% 減った[^research-low]。Opus 5.5 の medium と high を調べもので比べた数は、調べた範囲に無い。
- 長い調べもの（DeepResearch Bench II）では、Fable 5.1 は low・medium・high でほぼ同じ点で、1 タスクの費用だけが low の $4.66 から high の $7.12 に上がった[^fable-research]。
- Haiku 5.5 は、理科の難しい選択問題の評価（GPQA Diamond）で Opus 5.5 の約 20 分の 1 の費用で、正答率 85%（Opus 5.5 は 91%）だった[^gpqa]。Haiku 5.5 を low にすると、長いエージェントのプロンプトで検索を飛ばす・早く止める・確かめを飛ばすことが増え、Anthropic は知識の仕事と長いエージェントの仕事に high を勧める[^haiku-low]。
- 検索なしで答える事実性の試験（AA-Omniscience）の純スコア（正答の割合から誤答の割合を引いた値で、答えを控えると 0 点）は、Opus 5.5 が 0.58[^fact-opus]、Sonnet 5.5 が 0.35[^fact-sonnet]、Haiku 5.5 が 0.12[^fact-haiku] である。

### コードレビュー

- CodeRabbit の難しい既知の欠陥 13 件で、Opus 5.5 は 8〜10 件を、Sonnet 5.5 は 6 件を見つけ、精度（出した指摘のうち、判定役が当たりとした割合）も Opus 5.5 が上だった[^cr-catch]。Opus 5.5 の数は CodeRabbit が同じ 13 件を 9 月に測った物で、8〜10 件は記事の表の 2 つの設定（「Standard」が 8 件、「Max」が 10 件。何の設定かは記事に説明が無い）の幅である[^cr-opus-sep]。13 件は向きを見るには足り、決めるには足りないと記事は書く[^cr-small]。Sonnet 5.5（thinking あり）の 1 回のレビューの費用は約 $0.47 で、Opus 5.5 の費用は記事に無い[^cr-cost]。
- Sonnet 5.5 で thinking をありにすると、なしより費用が約 15% 増え、見つけた件が 1 つ増えた[^cr-thinking]。
- CodeRabbit は、易しいレビューと中くらいのレビューを Sonnet 5.5 に移していると書く[^cr-move]。

### 要約・分類・サブエージェント

- Haiku 5.5 の発表記事は、Opus 5.5 と Sonnet 5.5 のコーディングのサブエージェントとして組むとよいと書く[^haiku-sub]。API の文書は、分類・抽出・振り分けのような量が多く待ち時間に敏感な仕事を挙げる[^price-haiku]。
- 安いモデルが回して難所だけ上のモデルに聞く形（advisor）の計測では、Haiku 5.5 と Sonnet 5.5 は Opus 5.5 の advisor に 198 問のどれでも聞かなかった[^advisor]。

### 間違えたときの見分け

- 文脈が揃っていて真面目に試しても間違えたなら上の格のモデルを、ファイルを飛ばす・テストを走らせないなど手を抜いて間違えたなら上の effort を、と Anthropic は書く[^wrong]。決まりきった仕事（正確に言い表せる編集、機械的な変更）には小さいモデルを選ぶ、とも書く[^routine]。

## 5.5 では未測定（前の世代ではこうだった）

次は、5.5 世代で測った数が見つからない所である。前の世代の数は、5.5 の数として読まない。

- 仕事の種類ごとの Opus と Sonnet の差: 5.5 では未測定。Zhou ほかの論文「Agent-as-a-Router」の表（コーディングの仕事を種類に分けて 8 つのモデルを測った物。下の数は、何手も要るエージェントの仕事を除く 9 の種類〔コードの生成・補完・リファクタリングなど〕で、1 問に 1 回答えた点）では、Opus 4.6 と Sonnet 4.6 は、リファクタリング・バグの修正・多言語・理解・テストの生成で差が小さく（0.015 以下）、補完とデータサイエンスで大きかった[^task-type]。このうちリファクタリング・理解・テストの生成の 3 つは、コードを動かして採らず、代わりの指標に LLM の採点を足して測る[^task-judge]。計画やファイルの行き来を何手も要するエージェントの仕事では、解いた率が Opus 4.6 57.14%、Sonnet 4.6 49.11% だった[^task-ood]。
- ソフトウェアの設計: どの世代でも、モデルの段ごとに測った数は見当たらない（2026-10-19 に探した範囲）。
- レビューで Opus から Sonnet に替えた差: 5.5 は CodeRabbit の 13 件だけ（上の「コードレビュー」）。Opus 5 と Sonnet 5 では、CRBugBench（Microsoft と Microsoft Research の論文の測りで、人が確かめて直したバグを入れた PR をレビューのエージェントに見せ、上位の指摘で拾えた割合を数える）の上位 5 件の指摘で拾えた割合が、マージ前に見つかったバグで Opus 5 79.6%・Sonnet 5 64.7%、マージ後に見つかったバグで 64.2%・45.2% だった[^crb-table]。指摘の並びのいちばん上の 1 件だけで数えると、マージ前は 48.3% と 47.8% でほぼ並び、マージ後は 36.2% と 30.6% である[^crb-table]。HarnessEval（Dave Sifry が個人で測って公開した、AI のコードレビューの設定の比べ。テストで確かめたバグ 147 件で採点する）では、3 段の effort の平均で拾ったバグが、1 つのプロンプトで答えさせる one-shot で Opus 5 45.7 件・Sonnet 5 25 件、レビューを何段かに分けて回すオープンソースの 2 つの実行の形（ハーネス）のうち metareview で 69.3 件・40.7 件、Compound Engineering で 71.7 件・17.3 件だった[^he-mean]。
- レビューの effort を high から medium に下げた差: 5.5 では未測定。8 つのモデルを測った HarnessEval は、同じモデル・同じ実行の形の high と medium を 22 組比べ（22 の内訳は原典に無い）、17 組で見分けられなかった[^review-effort]。high が F1（拾ったバグと誤報の釣り合いを取る点）を有意に上げたのは 4 組、有意に下げたのは 1 組である[^review-effort-sig]。Claude の Opus 5 と Sonnet 5 では、ハーネスの実行の 4 組は見分けられず、one-shot の 2 組は high が有意に上だった（F1 で Opus 5 が +0.237、Sonnet 5 が +0.089。Sonnet 5 の metareview の +0.09 は区間が 0 をまたぐ別の組）[^review-effort-claude]。
- 調べもの・知識の仕事での medium と high: 5.5（Opus・Sonnet・Haiku）では未測定。Fable 5 で測った 4 つのベンチマークでは、low は 1〜3 点を落として費用を 3 分の 1 から半分減らし、既定の段は medium より測れるほど上がらなかった[^fable5-knowledge]。長いコーディングでは effort が正確さを買う、と Anthropic は書く[^long-coding]。
- 指示を細かくしたときの Opus と Sonnet・effort の段: どの世代でも、比べた数は無い（2026-10-19 に探した範囲）。
- Sonnet 5.5 の low、Haiku 5.5 の段ごとの点: Sonnet 5.5 の CursorBench の low はシステムカードの図の中にだけあり[^sonnet-low-figure]、Haiku 5.5 の段ごとの点は見つからない。
- 調べていない所: モデルごとの出力の速さ、Fable 5.1 の API での提供条件。

## 書き足し方

- 新しいモデルが出たら、その世代の見出しを「5.5 世代」の上に足し、数を測り直した原典から書く。前の世代の段の勧めは持ち越さない[^sweep]。
- 新しい世代で測った数が出た項目は、「未測定」の項から外す。前の世代の見出しは、新しい世代の数が揃うまで残す。
- 数を足すときは、脚注に原典の URL・確かめた日・原文の一句を書く。重み付け（どれを採るか）は書かない。

## 出典

脚注の形は「原典の URL（確かめた日）"原文の一句"」。

[^effort]: https://claude.com/blog/claude-model-and-effort-level-in-claude-code （2026-10-13）"Effort level controls how much work Claude does on your request overall."
[^sweep]: https://platform.claude.com/docs/en/build-with-claude/effort （2026-10-13）"Run an effort sweep on your own evals rather than carrying settings over from an earlier model"
[^order]: https://platform.claude.com/docs/en/about-claude/models/optimizing-for-cost-and-intelligence （2026-10-13）"From lowest to highest cost and capability, the current models are Claude Haiku 5.5, Claude Sonnet 5.5, Claude Opus 5.5, and Claude Fable 5.1 (the frontier model)"
[^price-haiku]: https://platform.claude.com/docs/en/about-claude/models/overview （2026-10-13）"Claude Haiku 5.5 For high-volume, latency-sensitive tasks such as classification, extraction, and routing"
[^price]: https://platform.claude.com/docs/en/about-claude/pricing （2026-10-13）"Claude Fable 5.1 For demanding reasoning and long-horizon agentic work $10 / MTok $50 / MTok" "Claude Opus 5.5 For long-running agentic coding and knowledge work $4 / MTok $20 / MTok" "Claude Sonnet 5.5 The best combination of speed and intelligence $2 / MTok $10 / MTok" "Claude Haiku 5.5 ... $0.10 / MTok for prompts up to 100,000 tokens $0.50 / MTok"
[^context]: https://platform.claude.com/docs/en/about-claude/models/overview （2026-10-13）"Context window 1M tokens 1M tokens 1M tokens 1M tokens" "Max output 128K tokens 128K tokens 128K tokens 128K tokens"
[^default-table]: https://platform.claude.com/docs/en/about-claude/models/overview （2026-10-13）の表の行（Fable 5.1・Opus 5.5・Sonnet 5.5・Haiku 5.5 の順）"Default effort high medium high medium"
[^default]: https://platform.claude.com/docs/en/build-with-claude/effort （2026-10-13）"Claude Opus 5.5 and Claude Haiku 5.5 default to medium."
[^thinking-toggle]: https://www.coderabbit.ai/blog/sonnet-5-5-model-review （2026-10-17。元の URL が取得の時に応えなかったので、Wayback Machine の保存 https://web.archive.org/web/20261014230630/https://www.coderabbit.ai/blog/sonnet-5-5-model-review から読んだ。以下の CodeRabbit の脚注も同じ）"Unlike Opus 5.5, which rejects explicit thinking toggles, Sonnet 5.5 allows thinking off at low, medium, and high effort"
[^start]: https://platform.claude.com/docs/en/about-claude/models/optimizing-for-cost-and-intelligence （2026-10-13）"For most agent workloads, start with Claude Opus 5.5 at its default effort ( medium ), and use Claude Fable 5.1 for demanding reasoning and long-horizon agentic work, or when your evals on Claude Opus 5.5 at higher effort still fall short."
[^effort-lever]: https://platform.claude.com/docs/en/about-claude/models/choosing-a-model （2026-10-13）"Tuning effort is often a better lever than switching models."
[^plan-weight]: https://support.claude.com/en/articles/14552983 （2026-10-16）"Opus costs several times more per turn than Sonnet, and Sonnet more than Haiku."
[^plan-effort]: https://support.claude.com/en/articles/8664678 （2026-10-16）"Higher effort means more thorough responses, but they take longer and use more tokens, so you'll reach your usage limits faster."
[^plan-searched]: 探した記事は https://support.claude.com/en/articles/11647753 、 https://support.claude.com/en/articles/11145838 、 https://support.claude.com/en/articles/11049741 、 https://support.claude.com/en/articles/15424964 、 https://support.claude.com/en/articles/14552983 、 https://support.claude.com/en/articles/8664678 、 https://support.claude.com/en/articles/12429409 、 https://support.claude.com/en/articles/9797557 の 8 本（2026-10-16）。本文を "times"・"ratio"・"faster"・"more of your"・"Haiku"・"token" で探した。倍率が無いことの確かめなので、原文の一句は無い
[^plan-fable]: https://support.claude.com/en/articles/15424964 （2026-10-16）"You can use up to 50% of your weekly usage limits on Fable models at no extra cost."
[^cursor-opus]: https://www-cdn.anthropic.com/fc1b44717c85dc068bc6ba5024219938094694bd/Claude%20Opus%205.5%20System%20Card.pdf （2026-10-18）"Opus 5.5 scored 57.8% on CursorBench at max effort, 56.0% at xhigh and high, and 52.5% at medium."
[^cursor-cost]: https://www-cdn.anthropic.com/fc1b44717c85dc068bc6ba5024219938094694bd/Claude%20Opus%205.5%20System%20Card.pdf （2026-10-18）"At medium effort it scores 52.5% for about $3 per task, still above Claude Fable 5.1 at max effort"
[^cursor-sonnet]: https://www-cdn.anthropic.com/870c8f525702625d2c62fc6dd04c857e3250bec1/Claude%20Sonnet%205.5%20System%20Card.pdf （2026-10-18）"Sonnet 5.5 scored 55.5% on CursorBench at max effort, 53.1% at xhigh, 47.8% at high, and 39.2% at medium."
[^frontiercode]: https://www-cdn.anthropic.com/fc1b44717c85dc068bc6ba5024219938094694bd/Claude%20Opus%205.5%20System%20Card.pdf （2026-10-18）"There is a decline in model performance on FrontierCode (Main and Extended) above medium effort. The evaluation is designed around writing mergeable code diffs without requiring human edits, so its grading penalizes out-of-scope changes that may be unnecessary"
[^terminal]: https://www.anthropic.com/news/claude-opus-5-5 （2026-10-18）"Opus 5.5 at default effort beats Opus 5 at max effort for about a fifth of the cost."
[^aa-step]: https://artificialanalysis.ai/models/comparisons/claude-opus-5-5-low-vs-claude-opus-5-5-medium と https://artificialanalysis.ai/models/comparisons/claude-opus-5-5-medium-vs-claude-opus-5-5-high （2026-10-18）の表を並べて数えた。low と medium の表 "Intelligence Index 42 51 AA-Briefcase v1.1 1280 1625 GDPval-AA v2.1 1235 1584 AutomationBench-AA 53% 61% Terminal-Bench 4.0 31% 53% SciCode 59% 59% Humanity's Last Exam 48% 55% GDP.pdf 26% 26% CritPt 18% 28% AA-Omniscience 39 40 AA-LCR v1.1 81% 84%"、medium と high の表 "Intelligence Index 51 54 AA-Briefcase v1.1 1625 1686 GDPval-AA v2.1 1584 1704 AutomationBench-AA 61% 63% Terminal-Bench 4.0 53% 57% SciCode 59% 60% Humanity's Last Exam 55% 56% GDP.pdf 26% 29% CritPt 28% 31% AA-Omniscience 40 41 AA-LCR v1.1 84% 83%"。数え方は、総合点（Intelligence Index）を除く 10 の評価で、隣の段の値を引いた差を比べた。low→medium が大きいのは AA-Briefcase・GDPval-AA・AutomationBench-AA・Terminal-Bench 4.0・Humanity's Last Exam・CritPt・AA-LCR の 7 つ、小さいのは SciCode と GDP.pdf の 2 つ、同じは AA-Omniscience の 1 つ
[^aa-tools]: https://artificialanalysis.ai/models/comparisons/claude-opus-5-5-low-vs-claude-opus-5-5-medium と https://artificialanalysis.ai/models/comparisons/claude-opus-5-5-high-vs-claude-opus-5-5 （2026-10-18）"AutomationBench-AA 53% 61% ... Terminal-Bench 4.0 31% 53%"（low・medium）、"AutomationBench-AA 63% 70% Terminal-Bench 4.0 57% 60%"（high・max）。AutomationBench-AA の中身は https://artificialanalysis.ai/methodology/intelligence-benchmarking （2026-10-18）"AutomationBench-AA is Artificial Analysis' run of Zapier's AutomationBench. It tests whether models can complete realistic SaaS workflows that span multiple simulated business apps, using REST APIs as the tool interface."
[^aa-cost]: https://artificialanalysis.ai/models/comparisons/claude-opus-5-5-low-vs-claude-opus-5-5-medium と https://artificialanalysis.ai/models/comparisons/claude-opus-5-5-medium-vs-claude-opus-5-5-high （2026-10-18）"Cost per Task $0.55 $1.34" "Time per Task 79.81s 200.44s"（low・medium）、"Cost per Task $1.34 $1.82" "Time per Task 200.44s 273.24s"（medium・high）
[^aa-lcr]: https://artificialanalysis.ai/models/comparisons/claude-opus-5-5-low-vs-claude-opus-5-5-medium と https://artificialanalysis.ai/models/comparisons/claude-opus-5-5-high-vs-claude-opus-5-5 （2026-10-18）"AA-LCR v1.1 81% 84%"（low・medium）、"AA-LCR v1.1 83% 85%"（high・max）。問題の数は https://artificialanalysis.ai/methodology/intelligence-benchmarking （2026-10-18）"100 hard text-based questions spanning 7 categories of documents"
[^haiku-scope]: https://www.anthropic.com/claude-haiku-5-5 （2026-10-13）"Sonnet 5.5 and Opus 5.5 remain better choices for complex agentic coding tasks like those measured by Terminal-Bench 4.0. By contrast, Haiku 5.5 is best suited to more narrowly scoped tasks"
[^sonnet-low-check]: https://www.coderabbit.ai/blog/sonnet-5-5-model-review （2026-10-17）"at low effort it can report a code change as done without running a check unless the prompt asks for one."
[^factory]: https://www.anthropic.com/news/claude-opus-5-5 （2026-10-18）"Claude Opus 5.5 is the first model we'd default to at medium effort."
[^deloitte]: https://www.anthropic.com/news/claude-opus-5-5 （2026-10-18）"Even at its lowest effort setting, Claude Opus 5.5 caught 72% of known bugs in our code reviews to Opus 5's 56% at high effort"
[^automation-sonnet]: https://www-cdn.anthropic.com/870c8f525702625d2c62fc6dd04c857e3250bec1/Claude%20Sonnet%205.5%20System%20Card.pdf （2026-10-18）"At max effort, Sonnet 5.5 scored 44.7%, with the API's default fallbacks enabled. Claude Opus 5.5 scored 42.5% after the tasks that had ended in a refusal were re-run with default fallbacks enabled"
[^fallback]: https://www.anthropic.com/news/claude-opus-5-5 （2026-10-18）"These runs were performed without fallback models, so safeguard interventions were considered failures"
[^physician]: https://www-cdn.anthropic.com/870c8f525702625d2c62fc6dd04c857e3250bec1/Claude%20Sonnet%205.5%20System%20Card.pdf （2026-10-18）"low and medium effort are not distinguishable (27.2% and 30.0%), and every step above that is a gain"
[^health-qa]: https://www-cdn.anthropic.com/870c8f525702625d2c62fc6dd04c857e3250bec1/Claude%20Sonnet%205.5%20System%20Card.pdf （2026-10-18）"For current public question-answering benchmarks in health, low effort already gives nearly all of the length-adjusted score, and the raw score is highest at max effort"
[^research-low]: https://platform.claude.com/docs/en/about-claude/models/optimizing-for-cost-and-intelligence （2026-10-13）"At low effort, the single agent scored 13.3 points lower on DRACO, 3.4 on HLE, and 14.0 on the physics set than at medium, and the typical task took 84%, 30%, and 47% less time."
[^fable-research]: https://platform.claude.com/docs/en/about-claude/models/optimizing-for-cost-and-intelligence （2026-10-13）"Claude Fable 5.1 scored nearly the same at low, medium, and high while the cost per task rose from $4.66 USD to $7.12 USD"
[^gpqa]: https://platform.claude.com/docs/en/about-claude/models/optimizing-for-cost-and-intelligence （2026-10-13）"at about a twentieth of Claude Opus 5.5's cost per question, with 85% accuracy compared with 91% for Opus 5.5 run the same way."
[^haiku-low]: https://platform.claude.com/docs/en/build-with-claude/effort （2026-10-13）"In long agent prompts, the model is more likely to skip a search, stop early, or skip a check at low. Use high for knowledge work, longer agent tasks, and strict instruction following."
[^fact-opus]: https://www-cdn.anthropic.com/fc1b44717c85dc068bc6ba5024219938094694bd/Claude%20Opus%205.5%20System%20Card.pdf （2026-10-13）"Claude Opus 5.5 received a net score of 0.58"、純スコアの定義は "Net score is the fraction of correct responses minus the fraction of incorrect responses on AA-Omniscience. Abstentions receive a score of zero."
[^fact-sonnet]: https://www-cdn.anthropic.com/870c8f525702625d2c62fc6dd04c857e3250bec1/Claude%20Sonnet%205.5%20System%20Card.pdf （2026-10-13）"Claude Sonnet 5.5 received a net score of 0.35"
[^fact-haiku]: https://www-cdn.anthropic.com/e1080d6bf5ae2018ea3c2f414064be03232f5be5/Claude%20Haiku%205.5%20System%20Card.pdf （2026-10-13）"Claude Haiku 5.5 received a net score of 0.12"
[^cr-catch]: https://www.coderabbit.ai/blog/sonnet-5-5-model-review （2026-10-17）"Opus 5.5 caught 8 to 10 issues where Sonnet 5.5 caught 6, at higher precision."、精度の定義は "Actionable precision is passing actionable comments divided by all actionable comments."
[^cr-opus-sep]: https://www.coderabbit.ai/blog/sonnet-5-5-model-review （2026-10-17）"Opus 5.5 figures are from our September evaluation of the same cases."。8 件と 10 件は Figure 1 の表の「Opus 5.5 Standard」8/13 と「Opus 5.5 Max」10/13（表の値で、原文の一句は無い）
[^cr-small]: https://www.coderabbit.ai/blog/sonnet-5-5-model-review （2026-10-17）"Thirteen cases is enough to see direction, not to settle a decision."
[^cr-thinking]: https://www.coderabbit.ai/blog/sonnet-5-5-model-review （2026-10-17）"Thinking on added about 15% to the bill over thinking off and bought one more catch and a little more precision."
[^cr-cost]: https://www.coderabbit.ai/blog/sonnet-5-5-model-review （2026-10-17）の Figure 3。Signal の 13 回で Sonnet 5.5 の thinking ありが計 $6.16（1 回あたり約 $0.47）。図の値で、原文の一句は無い
[^cr-move]: https://www.coderabbit.ai/blog/sonnet-5-5-model-review （2026-10-17）"We are moving simple and moderate reviews over now, and more in the coming weeks."
[^haiku-sub]: https://www.anthropic.com/claude-haiku-5-5 （2026-10-13）"It pairs well with Opus 5.5 and Sonnet 5.5 as a subagent on coding work."
[^advisor]: https://platform.claude.com/docs/en/about-claude/models/optimizing-for-cost-and-intelligence （2026-10-13）"Claude Haiku 5.5 and Claude Sonnet 5.5 called the Opus 5.5 advisor on none of the 198 questions"
[^wrong]: https://claude.com/blog/claude-model-and-effort-level-in-claude-code （2026-10-13）"If Claude has all the pertinent context, clearly tried, and still got it wrong, that's a signal to pick a more capable model."
[^routine]: https://claude.com/blog/claude-model-and-effort-level-in-claude-code （2026-10-13）"Pick a smaller model when the work is routine. For example, edits you can describe precisely, mechanical changes, or questions about code that's already in context."
[^task-type]: https://arxiv.org/html/2606.22902v3 （2026-10-19）の付録の表 9（分布の内の試験の組 2,919 件）の行。列は順にコードの生成・アルゴリズムの設計・バグの修正・補完・リファクタリング・データサイエンス・多言語・コードの理解・テストの生成・平均 "Claude Opus 4.6 .337 .275 .722 .837 .612 .109 .432 .190 .388 .438" と "Claude Sonnet 4.6 .311 .296 .707 .729 .600 .035 .431 .177 .391 .413"
[^task-judge]: https://arxiv.org/html/2606.22902v3 （2026-10-19）"Seven dimensions use execution-based scoring (pass@1 in sandboxed environments) for evaluations, while three dimensions use proxy metrics supplemented by LLM-as-Judge."、表 1 の行 "Code Refactoring Improve code quality Bugs2Fix, CanItEdit Proxy+"。3 つの次元の名（リファクタリング・コードの理解・テストの生成）は表 1 の採点の列から読んだ物で、原文の一句はリファクタリングの行だけ引く
[^task-ood]: https://arxiv.org/html/2606.22902v3 （2026-10-19）表 14 "Claude Opus 4.6 57.14 79.46 19.0 $89.28 Claude Sonnet 4.6 49.11 68.75 16.4 $77.23"
[^review-effort]: https://dsifry.github.io/harnesseval/ （2026-10-17）"When a confidence interval includes zero, this sample cannot tell high and medium apart. That happened in 17 of 22 comparisons."、8 つのモデルは "Eight models each reviewed the same pull requests three ways"
[^review-effort-sig]: https://dsifry.github.io/harnesseval/ （2026-10-17）"The dot is the change in F1, a score that balances bugs found against false alarms." "High effort significantly improved F1 in four comparisons and significantly reduced it in one."
[^review-effort-claude]: https://dsifry.github.io/harnesseval/ （2026-10-17）頁の末尾の比べの行 "cost: 1.3 d: 0.237 fw: one-shot hi: 0.389 label: Opus 5 · one-shot lo: 0.083"、本文 "The largest F1 gain was Opus 5 as a one-shot prompt (+0.24, interval +0.08 to +0.39)." "For example, Sonnet 5 running metareview shows a gain of +0.09, but its interval goes from −0.07 to +0.26."。Sonnet 5 の one-shot の +0.089（区間 +0.011〜+0.175）と、Opus 5 のハーネスの 2 組（+0.008・+0.004）、Sonnet 5 の Compound Engineering（−0.082）は、同じ頁の末尾の比べの行の値（原文の一句は無い）
[^crb-table]: https://arxiv.org/html/2610.13668v1 （2026-10-17）表 1。列の並び "Run Track Recall Review Tokens Cost Latency @1 @3 @5 @10 Count Words In Cache Out ($) (min) (K) (M) (M) (K)"、行 "claude-opus-5 Cmt. 48.3 71.2 79.6 86.0 5.76 1.08 2.43 2.34 34.3 2.55 8.6 Fix 36.2 55.4 64.2 68.6 6.78 1.28 3.37 3.27 43.9 3.38 11.1" と "claude-sonnet-5 Cmt. 47.8 62.5 64.7 65.7 2.65 0.69 3.26 3.18 35.1 1.18 9.1 Fix 30.6 43.2 45.2 45.6 3.04 0.80 4.56 4.46 45.9 1.60 11.7"。Cmt. はマージの前にレビューの指摘で見つかったバグ、Fix はマージの後に直しの PR で見つかったバグの組
[^he-mean]: https://dsifry.github.io/harnesseval/ （2026-10-17）"Each row is a model; marks show the mean across the three effort levels, out of 147 verified bugs." と頁の末尾の Sonnet 5 の行 "ce: 17.3 model: Sonnet 5 mrv: 40.7 oneshot: 25"。Opus 5 の行は同じ所の値で oneshot 45.7・ce 71.7・mrv 69.3（ce は Compound Engineering、mrv は metareview）
[^sonnet-low-figure]: https://www-cdn.anthropic.com/870c8f525702625d2c62fc6dd04c857e3250bec1/Claude%20Sonnet%205.5%20System%20Card.pdf （2026-10-18）の 8.8 節の図。図の値で、原文に low の数が無い（本文の CursorBench の一文は medium から max までの 4 つの数だけ）
[^fable5-knowledge]: https://platform.claude.com/docs/en/about-claude/models/optimizing-for-cost-and-intelligence （2026-10-13）"low gave up 1 to 3 points for a third to a half off the cost per task, medium matched the default's accuracy at about 70% to 87% of its cost, and the default bought nothing measurable over medium on any of the four."
[^long-coding]: https://platform.claude.com/docs/en/about-claude/models/optimizing-for-cost-and-intelligence （2026-10-13）"Long-horizon coding is where effort genuinely buys accuracy."
