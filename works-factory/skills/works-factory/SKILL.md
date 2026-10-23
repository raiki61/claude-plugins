---
name: works-factory
description: 人の修正依頼を、修正の工場 works-factory（raiki61/works-factory）に、今いるリポジトリを対象にして回す。「works-factory に回して」「工場で直して」と言われたときに使う。起動の 1 行（このプラグインの bin/works-factory）・依頼の渡し方・承認ノードでの答え方・報告の見方・差分の当て方を書く。今の /works（darkfactory）とは別の入口。
---

# works-factory

works-factory は修正依頼か GitHub issue を受け、検証した変更と報告を返す。対象は今いるリポジトリ。

工場は AI と機械の処理をグラフで回す基盤 Archon で動く。起動スクリプト（殻）が固定版を取り寄せるので、Archon は別に入れなくてよい。

流れ: 起動 → 承認 → 報告 → 差分を当てる。起動後と承認して進めた後に AI が動き、費用が掛かる。

今の `/works`（works プラグインの darkfactory）とは別の工場。

## 0. 要る物

- macOS か Linux、Python 3.12 以上、git、`bun`（工場の基盤 Archon の起動に使う）、Claude Code の `claude`。
- 足りない物は、殻が入れ方のコマンドを出して止まる。打ってから起動し直す。
- 認証: 既定は `claude` と `gh` のログインのまま。keychain・API キー・ゲートウェイ・`apiKeyHelper` で動く・認証で止まる・429 が返る（`WORKS_FACTORY_CLAUDE_CONCURRENCY` で絞る）時は、[references/auth.md](references/auth.md) を読む。

## 1. 殻

殻はこのプラグインの `bin/works-factory`。Claude Code が入れたプラグインの置き場（`${CLAUDE_PLUGIN_ROOT}`）に在る。

- 初回は、止めた commit（`${CLAUDE_PLUGIN_ROOT}/PIN` に書いた 40 桁）の raiki61/works-factory を、`${XDG_CACHE_HOME:-~/.cache}/works-factory-plugin/<commit>` に取ってくる。2 回目からは取り置きを使う。
- 引数は取り置いた工場の `bin/works-factory` にそのまま渡る。Archon の旗はコマンドの後ろに置く。
- `apply` だけは、差分を当てる口（工場の `bin/apply`）に渡る。

以下、`WF` は `${CLAUDE_PLUGIN_ROOT}/bin/works-factory` を指す。

## 2. 起動する

```
WF workflow run works-factory-line --cwd <対象のリポジトリ> --input request=<依頼のファイル> [--input test_cmd=<試験のコマンド>] [--from <枝か commit>]
```

- `request` は依頼を書いた JSON のファイルのパス。文を渡すとファイル名として読まれて止まる。
  - 形: `{"findings": [{"where": "<ファイル:行>", "text": "<何が困っているか・どうなってほしいか>"}], "pr": [<番号>], "issue": [<番号>]}`。`pr`・`issue` は省ける。前の run の答え（`answers`）や PR だけを渡す時は `findings` も省ける。ただし仕様の段（`spec=on`）は、`findings` か PR の題・本文が無いと止まる。
  - `text` には問題と目的を書き、直し方は書かない。案は `text` の中に「案: …」と分けて添える（工場は案を世の中の定石と比べる）。
  - `findings` の形は `workflows/.shared/schemas/request.schema.json`。依頼の全項目と省略は `lib/carry.py` の `parts()`。
- 人と固めた仕様から進める時は、`request` の代わりに `--input spec_table=<仕様の表>` を渡す。準備と必須の審査は [references/spec.md](references/spec.md) を読む。
- run の作業ツリーは、対象の今の姿から切られる。殻が `--from` を足す。
  - 汚れていない対象なら `HEAD`（PR のブランチを checkout すればそこから）。
  - commit していない変更が在れば、それを包んだ commit から切る。対象の作業ツリーとブランチは動かさない。
  - 別の所から切るなら `--from <版>` を名指す。`--base` か `--branch` を名指した時は殻が足さず、切り元は Archon が決める。
- `test_cmd` は、工場の中で走らせる試験のコマンド。
  - 変更に関わる試験だけを走らせるコマンドがあれば渡す。
  - 省くと `.review-checks.json` を使い、無ければ AI が試験の実行器を用意する。関係する試験が無ければ通常は省くが、選べない・絞れない場合や実行器が試験結果を JUnit 形式で出せるか確かめる時は全試験が走る。未実行を緑とは扱わない。
  - 対象の手元（元の clone・ほかの作業ツリー）を絶対パスや `~` で指す形は、直しでなく手元を試してしまう。run は AI を起動する前に止まり、訳が `WF workflow status` に出る。git が無視する物（`.venv` など）を相対で指す形は注意の行が報告に載る（そのパスが `test_cmd` の最初の語なら判定（直す物を決める段）の前で止まる）。どちらも作業ツリーの中で環境を作る 1 行（依存を入れてから試験を走らせるなど）にする。
- 試験のコマンドは、利用者の家（HOME と設定の置き場）で走る。AI が書いた試験のコードが利用者の権限で走り、書く物も家に入る（殻が起動のたびに告げる）。守りが要れば工場ごとコンテナか VM で回す。
  - 新しい作業ツリーで準備が要るツールは、対象の `.review-checks.json` の `suite` の横に `setup`（argv の並び）を書く。修正の前の試験が 1 段も走らない時は、判定の前で止まり、ツールの誤りの文と準備の案内を出す。
- 人が承認ノードで答えない run は `--input unattended=true`。始める時の承認ノードは飛ばし、ほかを開くはずの時は、項目の推しが全部「進む」なら進み、そうでなければ開かずに止める（報告は出る）。最後の承認ノードは推しが無く、開くはずなら止まる（差分を当てるなら 5. の `--allow-stopped`）。計画と審査の往復が上限 20 周で止まった時も推しで越えない。`spec=on` とは組めない。
- 起動は長いので Bash の run_in_background で打ち、終わりの知らせで次の手を打つ。`nohup` や `&` で切り離さない（知らせが来ず、承認ノードで止まった run に気づけない）。
- run の記録（Archon の家）は対象のリポジトリごとに分かれる。対象の外から打つ時は、どれにも `--cwd <対象>` を付ける。
- 何周もつなぐ時（周の鎖）は [references/chain.md](references/chain.md) を読む。

## 3. 承認ノードで答える

run は 4 か所（対話モードは 5 か所）で止まり、人の答えを待つ: 始める時・直す前（聞く必要がある時だけ）・修正の途中で計画が変わる時（承認した範囲や受け入れの試験が変わるか、審査役が問う時）・最後。最後の開き方は `--input final_gate=always|when_needed|protected_only` で選ぶ（既定は always、無人の run は when_needed）。守りのパス（対象の `.works-protected.json` に書いた物）に当たった時などはどれでも開き、`protected_only` はその時だけ開く（全部は工場の README「Choosing the approval nodes」）。

`--input design_talk=true` で無人でない run は対話モード。`gate-design` が計画と事前審査の往復の終わるたびに開き、設計案と審査の結果を見せる。無人の run と組むと開かず、直す前で止まる（報告は出る）。

1. 何を聞かれているかを見る: `WF workflow get <run> --cwd <対象>`
2. 答える: `WF workflow respond <run> approve|stop|revise [一言] --cwd <対象>`
   - `approve`: 進める。`gate-design` では同じ run のまま修正へ進み、直す前は合意した設計の項目を聞き直さない。
   - `stop`: 止める。後ろを飛ばして報告を出す（`workflow reject <run>` も同じ）。
   - `revise <一言>`: `gate-design` だけ。直す所の一言で設計と事前審査をやり直し、もう一度聞く。空の一言は 2 回まで聞き直し、次は止まる。20 回目の往復の `revise` も止まる（`stop` と同じ）。
- 承認ノードの間で走る run は `WF workflow cancel <run> --cwd <対象>` で止まる（報告は出ない）。`<run>` に入れる id・止めた後・Ctrl-C の時は [references/stop.md](references/stop.md) を読む。

## 4. 報告を読む

- 状態: `WF workflow status --cwd <対象>`
- 結果と報告の在りか: `WF workflow get <run> --cwd <対象>`
- run のファイル（`review.json` など）の置き場: `--detach` なしの `workflow run` が終わると（承認ノードで止まった時も）、標準エラーに `works-factory: 記録の置き場: <ディレクトリ>` が出る。
- 人に向けた報告（`report-ai.md`）の冒頭は機械が組む: 起きたこと・差分を当ててよいか・壊れた所と対象へ当てたか・判断が要る件数。判断が無ければ次に大事な事実を出す。その下に判断の短い題が並び、本文は `report-detail.md` の「人が決めること」を含む見出しに置く。
- 報告の書き手が落ちた run は failed で終わり、冒頭に訳が出る。使用枠切れなら冒頭の resume のコマンドを別のアカウントの keychain の項目で打つと、報告の書き手から先だけが走り直す。
- 報告の入口のセクションに、工場が依頼から決めた深さ（軽量・標準・重厚）と根拠、飛ばしたノードが 1 行で出る（段ごとの違いは工場の `docs/design/line.md` の 5.1）。

## 5. 差分を当てる

```
WF apply <run> --cwd <対象>
```

- 人が最後の承認ノードで見た差分は、hash で封じてある。当てる前にその hash を照合し、違えば止まって何も変えない。
- 最後の承認ノードで止めた run は `--allow-stopped`、封じた後のノードが落ちた run は `--allow-failed` を付ける。

## 6. 詳しい事

詳細は取り置きの `README.md`・`docs/design/line.md`、持ち主の決定は `docs/owner-decisions.md` に在る。
