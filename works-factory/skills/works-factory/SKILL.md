---
name: works-factory
description: 人の修正依頼を、修正の工場 works-factory（raiki61/works-factory）に、今いるリポジトリを対象にして回す。「works-factory に回して」「工場で直して」と言われたときに使う。起動の 1 行（このプラグインの bin/works-factory）・依頼の渡し方・承認ノードでの答え方・報告の見方・差分の当て方を書く。今の /works（darkfactory）とは別の入口。
---

# works-factory

works-factory は修正依頼か GitHub issue を受け、検証した変更と報告を返す。対象は今いるリポジトリ。

工場は AI と機械の処理をグラフで回す基盤 Archon で動く。起動スクリプト（殻）が固定版を取り寄せるので、Archon は別に入れなくてよい。

流れ: 起動 → 承認 → 報告 → 差分を当てる。起動後と承認して進めた後に AI が動き、費用が掛かる。

## 0. 要る物

- macOS・Linux・Windows の WSL2、Python 3.12 以上、git、`bun`（工場の基盤 Archon の起動に使う）、`uv`（工場のノードが台本を走らせるのに使う）、Claude Code の `claude`。
- WSL2 でない素の Windows（Git Bash・Cygwin・MSYS2 の上も含む。WSL の中の Linux は含まない）では動かない。殻（1. の、このプラグインの `bin/works-factory`）は工場を取ってくるところまで進むが、取ってきた工場の入口（工場の `bin/works-factory`・`bin/apply`）が「works-factory: 素の Windows では動かない（…）」の 1 行を標準エラーに出し、run を起こす前に止まる。訳は 2 つ: 素の Windows では Claude Code の sandbox が効かず、工場が役ごとに決めた書き込みの制限が黙って外れる。Archon も git worktree とシェルの段に WSL2 を要る。WSL2 を入れ（`wsl --install`）、WSL の中の Linux でこのプラグインを使う。
- 足りない物は、殻（1. の `bin/works-factory`）が入れ方のコマンドを出して止まる。打ってから起動し直す。`uv` だけは殻が確かめず（仕様の表から進める起動、2. の `spec_table`、を除く）、run の最初のノードで落ちるので、先に入れておく。
- PR を開く run（5. の `deliver=pr`）は `gh` も要る。
- 認証: 既定は `claude` と `gh` のログインのまま。keychain・API キー・ゲートウェイ・`apiKeyHelper` で動く・認証で止まる・429 が返る（`WORKS_FACTORY_CLAUDE_CONCURRENCY` で絞る）・会話のキャッシュの寿命（既定 5 分）を変える時は、[references/auth.md](references/auth.md) を読む。

## 1. 殻

殻はこのプラグインの `bin/works-factory`（`${CLAUDE_PLUGIN_ROOT}` の下）。

- 初回は、止めた commit（`${CLAUDE_PLUGIN_ROOT}/PIN` に書いた 40 桁）の raiki61/works-factory を、`${XDG_CACHE_HOME:-~/.cache}/works-factory-plugin/<commit>` に取ってくる。2 回目からは取り置きを使う。
- 引数は取り置いた工場の `bin/works-factory` にそのまま渡る。Archon の旗はコマンドの後ろに置く。
- `apply` だけは、差分を当てる口（工場の `bin/apply`）に渡る。

以下、`WF` は `${CLAUDE_PLUGIN_ROOT}/bin/works-factory` を指す。

## 2. 起動する

```
WF workflow run works-factory-line --cwd <対象のリポジトリ> --input request=<依頼のファイル> [--input test_cmd=<試験のコマンド>] [--from <枝か commit>]
```

- `request` は依頼を書いた JSON のファイルのパス。文を渡すとファイル名として読まれて止まる。ファイルは対象の外に置いて絶対パスで渡す（相対パスは run の作業ツリーの根から読まれ、対象の中に置いた commit していないファイルは、run が作業ツリーを切る元の commit に自動で commit されて入り、依頼の差分が混ざる）。PR の差分だけを見せる時は [references/pr.md](references/pr.md)。
  - 形: `{"findings": [{"where": "<ファイル:行>", "text": "<何が困っているか・どうなってほしいか>"}], "pr": [<番号>], "issue": [<番号>]}`。`pr`・`issue` は省ける。前の run の答え（依頼 JSON の鍵 `answers`。工場が次の run の依頼のファイルに書く）だけを渡す時は `findings` も省ける。ただし仕様の段（人と固めた仕様から進める 2. の設定 `spec=on`）は、`findings` か PR の題・本文が無いと止まる。
  - `text` には問題と目的を書き、直し方は書かない。案は `text` の中に「案: …」と分けて添える（工場は案を世の中の定石と比べる）。
  - `findings` の形は `workflows/.shared/schemas/request.schema.json`。依頼の全項目と省略は `lib/carry.py` の `parts()`。
- 人と固めた仕様から進める時は、`request` の代わりに `--input spec_table=<仕様の表>` を渡す。準備と必須の審査は [references/spec.md](references/spec.md) を読む。
- run の作業ツリーは、対象の今の姿から切られる。殻が `--from` を足す。
  - 汚れていない対象なら `HEAD`（PR のブランチを checkout すればそこから）。
  - commit していない変更が在れば、それを包んだ commit から切る。対象の作業ツリーとブランチは動かさない。
  - 別の所から切るなら `--from <版>` を名指す。`--base` か `--branch` を名指した時は殻が足さず、切り元は Archon（工場を動かす基盤。冒頭の説明を参照）が決める。
  - 殻（`bin/works-factory`、コマンドの `WF`）が Archon に `--from` を渡す run は、起動の前に remote（対象の `.archon/config.yaml` の `worktree.remote`、無ければ origin、それも無ければただ 1 つの remote）に届くかを確かめ、「<remote> に届くかを確かめている」の 1 行を出す（待ちの上限は無いので、止めるなら Ctrl-C）。一時の拒みは 3 回まで打ち直し、届かなければ AI を起こさずに「<remote> に届かない」（<remote> は remote の名）の訳で止まる。訳が「対象の git の remote に無い」と言う時は、`.archon/config.yaml` の `worktree.remote` と `git remote -v` を見比べる。
- `test_cmd` は、工場の中で走らせる試験のコマンド。
  - 変更に関わる試験だけを走らせるコマンドがあれば渡す。
  - 省くと `.review-checks.json` を使う。それも無ければ、AI が対象の CI の定義から試験の実行器を書き、工場は変更に関わる試験だけを走らせる（選べない時は全部）。全部の試験は CI と人に任せる。`test_cmd` も `.review-checks.json` も無く AI が実行器を書いた時の緑は機械が確かめた緑には数えない。未実行を緑とは扱わない。
  - 対象の手元（元の clone・ほかの作業ツリー）を絶対パスや `~` で指す形は、直しでなく手元を試してしまう。run は AI を起動する前に止まり、訳が `WF workflow status` に出る。git が無視する物（`.venv` など）を相対で指す形は注意の行が報告に載る（そのパスが `test_cmd` の最初の語なら判定（直す物を決める段）の前で止まる）。どちらも作業ツリーの中で環境を作る 1 行（依存を入れてから試験を走らせるなど）にする。
- 試験のコマンドは、利用者の家（HOME と設定の置き場）で走る。AI が書いた試験のコードが利用者の権限で走り、書く物も家に入る（殻が起動のたびに告げる）。守りが要れば工場ごとコンテナか VM で回す。
  - 新しい作業ツリーで準備が要るツールは、対象の `.review-checks.json` の `suite` の横に `setup`（argv の並び）を書く。修正の前の試験が 1 段も走らない時は、判定の前で止まり、ツールの誤りの文と準備の案内を出す。
- 人が承認ノードで答えない run は `--input unattended=true`。始める時の承認ノードは飛ばし、ほかを開くはずの時は、項目の推し（承認ノードの項目ごとに AI が付ける「進む」か「止める」の勧め）が全部「進む」なら進み、そうでなければ開かずに止める（報告は出る）。最後の承認ノードは、開く理由が R2 の問い（下の「依頼がはっきり指定した解き方」の項）だけで、その全部の行の推しが「進む」の時だけ進み、採った推しを `gates/gate-final.json` の欄 `pushed` に残す。ほかの理由（守りのパス・最後の試験が緑でない・独立の目が通さない・R4 の問い・差分を封じられない）が 1 つでも在るか、`final_gate=always` なら止まる（差分を当てるなら 5. の `--allow-stopped`）。計画と審査の往復が上限 20 周で止まった時も推しで越えない。`spec=on` とは組めない。
  - 直す前の承認ノードが人の答えを待って止まった run は、報告に「固定材料（修正前の承認ノードで止まった所の写し）: <フォルダ>」の行が出る。そのフォルダを新しい run の `--input fix_fixture=<フォルダ>`（相対なら対象の根から）に渡すと、判定と計画を回し直さずに直す前の承認ノードを写しの値で開き直し、答えると修正へ進む。依頼とほかの入力は前の run と同じにする（変えてよいのは `unattended` と `final_gate`〔最後の承認ノードの開き方〕だけ）。前の run と依頼・入力が違う時や、無いフォルダ・前の版の工場の写しは、start が AI を起動する前に止める。仕様の段（`spec=on`）や、何周もつなぐ run（周の鎖）とは組めない。
- 起動は長いので Bash の run_in_background で打ち、終わりの知らせで次の手を打つ。`nohup` や `&` で切り離さない（知らせが来ず、承認ノードで止まった run に気づけない）。
- run の記録（Archon の家）は対象のリポジトリごとに分かれる。対象の外から打つ時は、WF のどのコマンドにも `--cwd <対象>` を付ける。`WORKS_FACTORY_HOME`（絶対パス）で家を替えて起動した run は、後の `respond`・`get`・`status`・`apply` にも同じ値を付ける（Bash の呼び出しの間で環境は継がれない）。
- 何周もつなぐ時（周の鎖）は [references/chain.md](references/chain.md) を読む。
- 部品（block。工場の中の観点 1 つ分の作業。例 `works-factory-world`）を `works-factory-line`（2. の起動）の外で 1 つだけ回す時は、取り置いた工場（1. で殻が取ってきた clone）の `README.md` の「Running one block on its own」を読む。単独で使える 6 部品の入力・打ち方の例・返る物の読み方・測った時間と費用が在る。`plan-review` と `diagnose` は、工場の README が測った 1 回で 3〜4 ドル掛かった。`--cwd` は `works-factory-line` と同じパスにし（run の記録はパスごとに分かれる）、工場がまだ触っていない対象で同時に何本も起動しない（最初の run の `Running workflow:` の行を待ってから残りを起動する。[references/spec.md](references/spec.md) の 5 部品も同じ。この 5 部品は 6 部品から `diagnose` を除いた物）。

## 3. 承認ノードで答える

run は 4 か所（対話モードは 5 か所）で止まり、人の答えを待つ: 始める時・直す前（聞く必要がある時だけ）・修正の途中で計画が変わる時（承認した範囲や受け入れの試験が変わるか、審査役が問う時）・最後。最後の開き方は `--input final_gate=always|when_needed|protected_only` で選ぶ（既定は always、無人の run は when_needed）。守りのパス（対象の `.works-protected.json` に書いた物）に当たった時などはどれでも開き、`protected_only` はその時だけ開く（全部は工場の README「Choosing the approval nodes」）。

- 依頼がはっきり指定した解き方（工場の語で「頼みの解き方」）と、目的の 1 文だけから別に作った設計（独立設計）が食い違う所は、どちらも自動では勝たせず、問いになる。計画の側の食い違いは直す前の承認ノードに、計画を審査する AI の推し（項目ごとの「進む」「止める」の推奨）を付けて出る（無人の run は、全部の項目の推しが「進む」の時だけ進む。「止める」の推しか、推しの無い項目〔計画の審査が終わらなかった時など〕が 1 件でも在れば止まる）。修正の後に R2（差分と独立設計を比べる独立の目）が見つけた「頼みの解き方に従った結果、独立設計と食い違った所」は、`final_gate` の値が何でも最後の承認ノードを開く。無人の run は、`final_gate=always` でなく、ほかに開く理由が無く、問いの全部の行に R2 の「進む」の推しが付いている時だけ推しを採って進み、「止める」か推しの無い行が 1 件でも在れば止まる。

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
- run の記録（工場が土台にする workflow エンジン Archon の log と、AI のノードの会話）を 1 本の trace にして手元の Phoenix（Arize 社の OSS で、OpenTelemetry の trace を見る画面）などへ送って見るのは、工場の `viewer/runtrace.py`（手順は工場の README「Seeing a run in Phoenix」）。会話の中身が載るので、`localhost` でない送り先は `--remote` なしでは断られる。
- 送らずに手元で 1 枚の HTML のページで見るのは、工場の `viewer/runpage.py`（段・部品（block）・周・ノードで畳んだ run と、block ごとの受けた値と返した値・分かれ道の条件・差し戻された記録・承認の答えが載る。どこへも送らず、ファイルも書かない。ページは標準出力に出るので `> run.html` のようにリダイレクトする。手順は工場の README「Seeing a run as one page」）。
- 報告の入口のセクションに、工場が依頼から決めた深さ（軽量・標準・重厚）と根拠、飛ばしたノードが 1 行で出る（段ごとの違いは工場の `docs/design/line.md` の 5.1）。

## 5. 差分を当てる

```
WF apply <run> --cwd <対象>
```

- 人が最後の承認ノードで見た差分は、hash で封じてある。当てる前にその hash を照合し、違えば止まって何も変えない。
- 無人の run が最後の承認ノードを推しで通した答え（`gates/gate-final.json` に `pushed` が在る）は人の通しと見なさず、当てる前に、答えの無い run と同じに緑・独立の目・差分の指紋・守りのパスを確かめる。
- 最後の承認ノードで止めた run は `--allow-stopped`、封じた後のノードが落ちた run は `--allow-failed` を付ける。
- 独立の目に差し戻された後の段が止まった・落ちた run は、差し戻し前の状態が封じてある。差し戻し後の段の書き換えは run の置き場の `eyes-back-kept.patch` に控えてあり（`git apply` で戻せる）、在りかは最後の承認ノードと報告が名指す。
- 差分を当てる代わりに PR を開くのは、起動に `--input deliver=pr` を足した run だけ（既定は差分を残すだけで対象に書かない）。`gh` を入れ、その今のアカウント（`gh auth status` の active）を対象に PR を開けるアカウントにしておく。PR を作る Archon の部品 `archon-pr` は、GitHub 用の forge プラグイン（Archon の GitHub 連携の部品）`archon-forge-github` を使って PR を作る。殻が、PIN で固定した版の Archon の源（1. で取ってきた物）から `bun` で 1 度だけそのプラグインを作って渡す（作る段はネットワークに出ない）。PATH に `archon-forge-github` が既に在ればそれを使う。作れない時は殻が 1 行告げ、その run は PR を作る前に断られる。push は git が run の環境で見つける認証だけを使う。全部は取り置いた工場の `README.md` の、「Opening a PR」で始まる項。

## 6. 詳しい事

詳細は取り置きの `README.md`・`docs/design/line.md`、持ち主の決定は `docs/owner-decisions.md` に在る。
