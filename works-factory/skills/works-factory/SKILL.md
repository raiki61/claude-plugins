---
name: works-factory
description: 人の修正依頼を、修正の工場 works-factory（raiki61/works-factory）に、今いるリポジトリを対象にして回す。「works-factory に回して」「工場で直して」と言われたときに使う。起動の 1 行（このプラグインの bin/works-factory）・依頼の渡し方・承認ノードでの答え方・報告の見方・差分の当て方を書く。今の /works（darkfactory）とは別の入口。
---

# works-factory

works-factory は、直してほしい事（修正依頼か GitHub の issue）を受け取り、確かめ済みの変更と報告を返す工場。今いるリポジトリを対象にして回す。

工場は Archon の上で動く。Archon は、AI の役と機械の確かめを並べたグラフ（ノードとエッジ）を回す外の実行基盤。工場の殻が止めた版の Archon の源を自分で取ってきて起こすので、別に入れなくてよい。

流れ: 起動する → 承認ノードで答える → 報告を読む → 差分を対象へ当てる。回すと費用が掛かる（AI の役を起こすのは、起動の後と、承認ノードで進めた後）。

今の `/works`（works プラグインの darkfactory）とは別の工場で、並べて置いてある。どちらを使うかは人が選ぶ。

## 0. 要る物

- macOS か Linux、Python 3.12 以上、git、`bun`（Archon の源を起こすのに使う）、Claude Code の `claude`。
- 足りない物は、殻が入れる命令を 1 行ずつ出して止まる。出た命令を打ってから、もう一度起こす。
- 認証: 普段の `claude` と `gh` のログインのまま動く。Claude のアカウントを macOS の keychain の項目で選ぶ時は、`WORKS_FACTORY_KEYCHAIN_ITEM=<項目の名>` を付ける（値は表示も保存もしない）。

## 1. 殻

殻はこのプラグインの `bin/works-factory`。Claude Code が入れたプラグインの置き場（`${CLAUDE_PLUGIN_ROOT}`）に在る。

- 初回は、止めた commit（`${CLAUDE_PLUGIN_ROOT}/PIN` に書いた 40 桁）の raiki61/works-factory を、`${XDG_CACHE_HOME:-~/.cache}/works-factory-plugin/<commit>` に取ってくる。2 回目からは取り置きを使う。
- 引数は、そのまま工場の殻（取り置いた works-factory の `bin/works-factory`）に渡る。工場の殻は Archon の命令の引数をそのまま受ける（旗は命令の後ろに置く）。
- `apply` だけは、差分を当てる口（工場の `bin/apply`）に渡る。

以下、`WF` は `${CLAUDE_PLUGIN_ROOT}/bin/works-factory` を指す。

## 2. 起動する

```
WF workflow run works-factory-line --cwd <対象のリポジトリ> --input request=<依頼>
```

- 依頼は、直してほしい事の文か、GitHub の issue の URL。
- 起動は長くかかるので、Claude Code の Bash の run_in_background で起こし、終わりの知らせで次の手を打つ。`nohup` や `&` で切り離さない（知らせが来ないので、承認ノードで止まった run に気づけない）。
- run の記録（Archon の家）は対象のリポジトリごとに分かれる。対象の外から打つ時は、どの命令にも `--cwd <対象>` を付ける。
- 何周もつなぐ時（周の鎖）: `WF workflow run works-factory-chain --cwd <対象> --input rounds=<1〜5> --input request=<依頼>`（費用の上限は `--input budget_usd=<USD>`）。1 周が子の run 1 本で、残りが在れば次の周を起こす。周の中の承認ノードには子の run の id で答える（`WF workflow status --cwd <対象>` で見る）。当てるのは鎖の run（`WF apply <鎖の run> --cwd <対象>`）で、採る周までの最後の差分と、周ごとの表 `chain.md` が置き場に出る。

## 3. 承認ノードで答える

run は 3 か所で止まり、人の答えを待つ: 始める時・直す前（聞く必要がある時だけ）・最後。

1. 何を聞かれているかを見る: `WF workflow get <run> --cwd <対象>`
2. 答える: `WF workflow respond <run> approve|stop [一言] --cwd <対象>`
   - `approve`: 進める。
   - `stop`: 止める。後ろを飛ばして報告を出す（`workflow reject <run>` も同じ）。
- 承認ノードの間で走っている run は `WF workflow cancel <run> --cwd <対象>` で止まる。ただし報告は出ない。

## 4. 報告を読む

- 状態: `WF workflow status --cwd <対象>`
- 結果と報告の在りか: `WF workflow get <run> --cwd <対象>`
- 報告の冒頭 3 行に、起きたこと・決めてほしいこと・推しが在る。

## 5. 差分を当てる

```
WF apply <run> --cwd <対象>
```

- 人が最後の承認ノードで見た差分は、hash で封じてある。当てる前にその hash を照らし、違えば止まって何も変えない。

## 6. 詳しい事

工場の作り・選べる道（環境変数）・持ち主の決めの記録は、取り置いた works-factory の `README.md`・`docs/design.md`・`docs/owner-decisions.md` に在る。
