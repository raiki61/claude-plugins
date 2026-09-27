# 0069. 局所レビューの skill の節も engine が起こし、背景の線は回し手が立てる

- 状態: 採用
- 日付: 2026-09-27（補足 2026-09-28）
- 決めた人: 人（回し役の道を消す決定 2026-09-27 と、この run の修正前の関所の答え——round 1 の条件 1〜8・round 2 の条件 1〜7・round 3 の条件 1〜4）。関所の答えの多くは親（会話）が推しで決め、人が覆せる形で通した。形の細部は wip/drvless の run の判定・事前審査・修正
- 実装: graphloops の [Unreleased]（回し役なしの run——init の既定。`--no-engine-runners` の run を除く——の局所レビュー。背景の線は受領の形を持つ盤面の全部）

## 文脈

- [0068](0068-engine-launches-runner-nodes.md) は「局所レビューの skill と背景の線は、今どおり会話に返す」と決めた。回し役なしの run でも、局所レビューが毎周 13 で会話に返り、会話の文脈を最も多く食った（09-27 の試験運用の 3 本すべて）。
- 公式の headless の文書は、`-p` の子でも利用者が呼ぶ skill が動くと書く。

## 決定

- 局所レビュー（skill を持つ回す側の節）は、Read・Glob・Grep・Bash・Skill・Agent を持ち書く道具を持たない子（`role_run.skill_permission`。sandbox の形のときだけ）で起こす。利用者の設定・プラグインは読ませない（[0065](0065-roles-without-user-settings.md)）。
  - プラグインの agent のレンズは名前で起きないので、engine が定義の本文を盤面に写し、子が Agent の汎用の子に読ませて起こす。`--plugin-dir` でプラグインを読ませる形は採らない。
  - Agent の子の待ちの上限（`CLAUDE_CODE_PRINT_BG_WAIT_CEILING_MS`）は子の環境で 0（上限なし）にする。
- 背景の任せ先（変異の検算の線）は、graph の `delegate.receipt` の受領を回し手が `done` して、`loop.py launch --node` を切り離して立てる（`runner._Runner.start_lane`）。

## 補足（3 周目の判定と人の関所の答え 2026-09-28）: 13 は engine の不具合だけにする

最初の形は、engine が起こせない状態（起こせないレンズ・入れ子の sandbox の書く節・柵を外した任せ先・受領の形の無い線）を 13 で会話に返していた。受け皿ごとに例外の型（`HandBack`）・宣言の語（`launch.on_fail: handoff`）・盤面の語（handback）が増え、入口ごとに検査の素通りが生まれた（判定の一撃）。そこで、この版で init した回し役なしの盤面（`state.engine_runners.handoff` の印）では:

- engine が起こせない節は、起こせない理由を instance の `unlaunched` に書いて人に渡す（`run` の 14）——sandbox の立たない場・別の作業ツリーの下の作業ツリーの書く節と局所レビュー、必須のレンズの定義が無い局所レビュー、語を組めない役の節。持ち主が外し方を当てたら `relaunch` で出し直す。
- 入れ子の sandbox は、sandbox の中で走る子（語の `--settings` の `sandbox.enabled`）の前で確かめの子（道具は Bash だけ）が測る。立たない場では書き換える子・skill の子・任せ先を起こさずに外し方を名指して 14 で止め（環境の予定どおりの止まりとして記録器には渡さない）、読むだけの子は起こして Bash で測れていないことを記録に残す。
- 局所レビューの子の返答（本文が子の置き場の中身と同じ返答——`done` の読み口に依らない）は、必須のレンズの行に `invoked: true` を求め、`material` の awaiting_human を拒む。拒みは同じ会話への続きで、上限まで続けば 14。条件付きのレンズを起こさなかった行は受け付けて、報告の『未確認のレンズ』に並べる。`/simplify` の持ち越しは、周の頭の版が前の周から 1 ファイルも変わっていない周だけ受け付ける。
- 柵を外した run（`init --unfenced-delegates`）の任せ先は、engine が sandbox の設定を持たない形（`role_run.unfenced_delegate_permission`）で起こす。柵はその形を、盤面の印が在るときだけ通す。作業ディレクトリは今までどおり本物の写し。
- 13 は、launch も理由も持たない節（盤面の矛盾）だけになり、回し手が記録器に 1 行残す。graph の側は graphcheck が縛る（launch.runner を宣言する graph では、任せ先には `launch.delegate`、背景の任せ先には受領の形、engine_run の節には任せ先、役の節には起こす語が要る）。
- 前の版の engine で始めた盤面は、印が在っても今までどおり 13 で会話に返し、`next` の notes で知らせる（人の方針『旧い盤面は警告して通す』と round 3 の条件 2）。
- 背景の線の試行は、今の周の表でなく全周から id と置き場で引く（周をまたいで走る線が落ちても `lane_failed` が書かれる）。線の launch は起こした印を盤面に書く前に自分の印を置き、締めの後に消す——印が在るのに launch も子も居ない線は、読む側（run の報告と rules の線の読み）が落ちたと導く（`role_run.lane_failure`）。launch を立てた回し手が先に抜けた後の落ちも出る。

これは round 1 の条件 1（子が届かなければ会話の道の 13 に戻す）と round 2 の条件 1（入れ子の sandbox の書く節と skill の節は 13）を改める狭めで、round 3 の関所で通した。

## 比べた案

- `--plugin-dir` でプラグインを読ませ、agent を名前で起こす: hooks・mcpServers・settings.json・bin/ など argv の柵の外で子を変える部品まで入る（事前審査 2026-09-27）ので採らない。
- レンズの agent 4 本を、comment-analyzer と同じく道具つきの役の節に分ける: 局所レビューの節を 2 つに割り、記録の素材と受け付けの柵を作り直す設計作業になるので、この決定では採らない。
- 走ったことを stream-json の起動の跡で照らす: 続きの往復をまたいだ跡の持ち方と、レンズの名前の綴りの対応が決まらない（事前審査 2026-09-27）ので、今回は役の申告のまま（会話が回していた頃と同じ）にする。
- 13 の受け皿ごとに語を足し続ける（前の周の一撃）: 受け皿が増えるたびに型・印・写しが増え、`on_fail` と例外の型の 2 層が残った。13 を不具合専用にし、受け皿を 14・報告・engine の中へ移す形を採った。
- 任意の役の節の定義が無い回を 14 でなく省く（事前審査の別案）: 省くかは人が関所で決めた 14 の形を変えるので、この補足では採らない。

## 理由

[0063](0063-roles-as-child-processes.md) と同じ（会話を中継に挟まない）。失敗は自動の続き（拒みの続き）と人の判断を待つ明示の止まり（14）に分け、呼び元の会話に仕事を差し戻す手番を持たない（ワークフローの実行器の定番の形）。

## 結果

- 回し役なしの run で会話に残る手番は、init・`run` の打ち直し・人の関所の答え・14（会話がまず受け、推しで済む物をこなし、取捨だけを人に上げる）になる。
- 子の中の局所レビューは、利用者の CLAUDE.md・設定のプラグイン・MCP・網を使えない（人が通した狭め）。
- 手元で e2e の一式と変異を撃たない方針（人の方針『テスト（今だけ）』『変異テストは手元で撃たない』と round 1 の条件 3）は、3 つで守る。
  - 方針の段: 起こす子の形ごとの段（`launch.append`）が、コマンドを走らせる子に方針とテストの範囲を届ける。
  - 入口の拒み: engine が起こす子の環境に印（`role_run.ENGINE_CHILD_ENV`）を足し、このリポジトリの入口（`tests/run.sh`・`graphloops/tests/run.sh`・`tests/mutate.py` の `--check` のほか・台本の一式を絞らずに走らせる `graphloops/tests/parallel.py` の `run_all`）がそれを見て拒む。CI は印を持たないので今どおり走る。これは事故を防ぐ第二の網で、境界ではない——子の Bash が印を外せば（`env -u`）抜ける。公式の permissions の文書が文字列に依らない強制として挙げるのは sandbox と PreToolUse のフックである。
  - 宣言の deny: このリポジトリの `.claude/settings.json` の `permissions.deny` に e2e の一式の 4 綴り（`Bash(bash tests/run.sh:*)`・`Bash(bash graphloops/tests/run.sh:*)`・`Bash(./tests/run.sh:*)`・`Bash(./graphloops/tests/run.sh:*)`）を置く（round 1 の条件 3・6。対話の会話にも効く）。engine はこの deny を子に写す。**まだ置いていない**——`.claude` の下は engine の書く子に書けない保護された置き場なので、人の手で置く（問いの台帳の field の問い）。
- 人の方針『テスト（今だけ）』を解くときは、入口の拒み（上の 4 か所の頭の段）と、置いていれば宣言の deny を消す。

## 見直す条件

- 子で組み込みの skill が起きない・Agent の子が親の sandbox を継がない、と実走で分かったとき（局所レビューが毎周 14 に止まる）。
- 前の版の engine で始めた盤面が残っていないと言えたとき（13 の日常の道と、前の版の語——handback・`on_fail`・`runner_unlaunched`——の読みを消せる）。

## 出どころ

- この run の記録（判定の単位「skill の節と背景の任せ先が engine に起こされず会話に返る」「回し役なしの run でも会話に返す（13）道が残り…」と修正前の関所の答え）。[review-graph の手順書の早見](../../graphloops/commands/review-graph.md#早見)と「[回し役なしで回す](../../graphloops/commands/review-graph.md#回し役なしで回す)」。
