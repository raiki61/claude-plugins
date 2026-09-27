# 0069. 局所レビューの skill の節も engine が起こし、背景の線は回し手が立てる

- 状態: 採用
- 日付: 2026-09-27
- 決めた人: 人（回し役の道を消す決定 2026-09-27 と、この run の修正前の関所の答え 2026-09-27 の条件 1〜4）。形の細部は wip/drvless の run の判定・事前審査・修正
- 実装: graphloops の [Unreleased]（回し役なしの run——init の既定。`--no-engine-runners` の run を除く——の局所レビュー。背景の線は受領の形を持つ盤面の全部）

## 文脈

- [0068](0068-engine-launches-runner-nodes.md) は「局所レビューの skill と背景の線は、今どおり会話に返す」と決めた。回し役なしの run でも、局所レビューが毎周 13 で会話に返り、会話の文脈を最も多く食った（09-27 の試験運用の 3 本すべて）。
- 公式の headless の文書は、`-p` の子でも利用者が呼ぶ skill が動くと書く。

## 決定

- 局所レビュー（skill を持つ回す側の節）は、Read・Glob・Grep・Bash・Skill・Agent を持ち書く道具を持たない子（`role_run.skill_permission`。sandbox の形のときだけ）で起こす。利用者の設定・プラグインは読ませない（[0065](0065-roles-without-user-settings.md)）。
  - プラグインの agent のレンズは名前で起きないので、engine が定義の本文を盤面に写し、子が Agent の汎用の子に読ませて起こす。`--plugin-dir` でプラグインを読ませる形は採らない。
  - Agent の子の待ちの上限（`CLAUDE_CODE_PRINT_BG_WAIT_CEILING_MS`）は子の環境で 0（上限なし）にする。
  - 子が起こせないレンズを awaiting_human で返した回と、当たるレンズ（必須と、条件が真の周の条件付き）の行に invoked: true が無い回は、受け付けずに節を会話に返す（`util.HandBack`）。拒みが上限まで続いた・子が落ちた回も会話に返す（`launch.on_fail: handoff` は、届かなかった回に launch の締めが書く語の既定）。振り分けは instance の attempt_log の最後の語（handback）だけを読む `runner.classify` の 1 か所で、語を書くのは launch の締めと done の受け付け。
  - 入れ子の sandbox（Claude Code の sandbox の中の engine が起こす子で、Bash の呼び出しごとに sandbox の初期化が落ちる場）は、確かめの子の返答に初期化の失敗の文が在ったときだけそう決め、局所レビューと書き換える節を会話に返し、任せ先は外し方を名指して拒む（`commands._sandbox_probe`。人の関所 round 2 の条件 1）。
- 背景の任せ先（変異の検算の線）は、graph の `delegate.receipt` の受領を回し手が `done` して、`loop.py launch --node` を切り離して立てる（`runner._Runner.start_lane`）。受領の形を持たない旧い盤面の線は、今どおり会話に返す。

## 比べた案

- `--plugin-dir` でプラグインを読ませ、agent を名前で起こす: hooks・mcpServers・settings.json・bin/ など argv の柵の外で子を変える部品まで入る（事前審査 2026-09-27）ので採らない。
- レンズの agent 4 本を、comment-analyzer と同じく道具つきの役の節に分ける: 局所レビューの節を 2 つに割り、記録の素材と受け付けの柵を作り直す設計作業になるので、この決定では採らない。
- 走ったことを stream-json の起動の跡で照らす: 続きの往復をまたいだ跡の持ち方と、レンズの名前の綴りの対応が決まらない（事前審査 2026-09-27）ので、今回は役の申告のまま（会話が回していた頃と同じ）にする。

## 理由

[0063](0063-roles-as-child-processes.md) と同じ（会話を中継に挟まない）。子で起こせない回は会話に戻るので、会話が起こせていた能力は減らない（人の関所の答え 2026-09-27 の条件 1）。

## 結果

- 回し役なしの run で 13 に返るのは、sandbox が立たない場の節・子が届かなかった局所レビュー・受領の形を持たない旧い線・柵を外した任せ先だけになる。
- 子の中の局所レビューは、利用者の CLAUDE.md・設定のプラグイン・MCP・網を使えない（人が通した狭め）。
- 手元で変異を撃たない方針は、対象リポジトリの `.claude/settings.json` と `.claude/settings.local.json` の `permissions.deny`（Claude Code と同じく合わせる）を engine が子に写す形と、方針の段で守る（このリポジトリの run は `gates=merge` で起こすので線は立たない）。
- このリポジトリの `.claude/settings.json` の `permissions.deny` には、e2e の一式の 4 綴り（`Bash(bash tests/run.sh:*)`・`Bash(bash graphloops/tests/run.sh:*)`・`Bash(./tests/run.sh:*)`・`Bash(./graphloops/tests/run.sh:*)`）を置く（人の関所 round 1 の条件 3・6。対話の会話にも効く）。人の方針『テスト（今だけ）』を解くときに、この deny を消す。`tests/mutate.py` の撃つ形は前置の照合で `--check` と分けられない（旗なしの素の呼びも撃つ）ので deny に書かない。

## 見直す条件

- 子で組み込みの skill が起きない・Agent の子が親の sandbox を継がない、と実走で分かったとき（どちらも 13 に戻るだけで壊れはしないが、会話に返る回が減らない）。

## 出どころ

- この run の記録（判定の単位「skill の節と背景の任せ先が engine に起こされず会話に返る」と修正前の関所の答え）。[review-graph の手順書の早見](../../graphloops/commands/review-graph.md#早見)と「回し役なしで回す」。
