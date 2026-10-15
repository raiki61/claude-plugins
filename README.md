# claude-plugins

[![test](https://github.com/raiki61/claude-plugins/actions/workflows/test.yml/badge.svg)](https://github.com/raiki61/claude-plugins/actions/workflows/test.yml)

raiki61 のプラグインマーケットプレイス。配るプラグインは 7 本で、並列の関係にある。一覧の正本は `.claude-plugin/marketplace.json` で、下の表はその要約である。

| プラグイン | 何を配るか | 効き方 |
|---|---|---|
| **convergence-loops** | 収束するまで回す 4 つのループ（/review-loop・/research-loop・/doctor-loop・/firstread-loop） | 呼んだときに効く（コマンド）→ [convergence-loops/README.md](convergence-loops/README.md) |
| **gates** | 外に出る操作を、検査が通るまで止める門番。1 本目は coldread——手元の文書（md など）は書いた後に読んでターンの終わりに指摘を返し、gh の投稿本文(issue・PR・release notes・gist 等)を、別プロセスの読み手に初見で読ませて、詰まりが直るまで投稿を止める(新規作成は文脈ゼロで、既に在るスレッドへの返信は画面に見えているもの——題・状態・本文・変更ファイル・元の指摘・これまでの返信・参照する番号の題——を渡して読ませる。画面が既知にするのは指す先であって語彙ではない)。2 本目は destgate——投稿の宛先を人が管理する許可一覧で縛る（既定で眠る） | 有効化した環境で常時効く（フック）→ [gates/README.md](gates/README.md) |
| **attention** | 並行作業を見渡して戻るための道具 3 本。open 全件から誰の番かを出す /whose-turn、1 件の PR / issue に戻る /catchup（該当ブランチへ移る。手元に無ければ origin から取る。説明の後ろに系の前後の絵）、いま居るセッションが何のスレッドだったかを思い出す /what-am-i-doing | 呼んだときに効く（コマンド）→ [attention/README.md](attention/README.md) |
| **graphloops** | 収束ループのグラフ実行版。convergence-loops の 4 ループを「節＋依存＋周回条件」の JSON に写し、機械が盤面・波・遮断・件数・収束を持って回す。実行版は /research-graph（/research-loop の実行版）と /review-graph（/review-loop の実行版）の 2 本（既存のコマンドは残し、本体は隣に置く。触った範囲は graphloops/README.md） | 呼んだときに効く（コマンド）→ [graphloops/README.md](graphloops/README.md) |
| **works** | 人の修正依頼を、今いるリポジトリを対象に、Archon（AI の作業の流れを回す外の道具）の上の生産ライン darkfactory に回す /works スキル | 呼んだときに効く（スキル）→ [works/README.md](works/README.md) |
| **works-factory** | 修正の工場 works-factory（別のリポジトリ raiki61/works-factory）へ依頼を回す /works-factory スキル。/works と並べて置く | 呼んだときに効く（スキル） |
| **works-dispatch** | 自分の番の PR を、PR ごとの作業場（clone と herdr の作業場）に開き、使用率に余裕のあるアカウントの Claude Code で /catchup と 2 ターン目の文を送る /works-dispatch:dispatch スキル。AI を使わない | 呼んだときに効く（スキル）→ [works-dispatch/README.md](works-dispatch/README.md) |

convergence-loops・gates・graphloops の 3 本は規律（読み役は毎回新規・文脈遮断・点数を測らない）を
共有するが、別々に有効化する——ループ集を入れたら投稿や書き込みの挙動が黙って変わる、を避けるため。
attention はこの規律の外で、読み役を立てず GitHub の記録だけを機械で畳む。
各プラグインの説明は、それぞれのフォルダの README.md に在る（convergence-loops は [convergence-loops/README.md](convergence-loops/README.md)）。以下は、このリポジトリを開発する人向けの確かめ方。

## 動作確認

**これはこのプラグイン自身を開発・改造する人向けの検証で、利用者が対象リポジトリで走らせるものではない。** `/plugin install` で入れた場合、実体はプラグインのキャッシュに置かれて作業ディレクトリには現れないので、`tests/run.sh` は clone しないと存在しない。

```bash
git clone https://github.com/raiki61/claude-plugins
cd claude-plugins
bash tests/run.sh
uv run --no-project --with pytest --with pytest-xdist python -m pytest -n auto graphloops/tests/py   # pytest の置き場（開発の間だけ入れる。方針は graphloops/README.md の「検査」節）
```

検査するもの——`review-record.py`・`research-record.py`・`doctor-record.py`・`firstread-record.py` の終了コードの区別、`review-record.py` の履歴（全ラウンドの推移）と問いの台帳の縛り（保留が黙って消えない・出どころが記録に実在する・stuck は未決の記載が要る・帰属は前の周から持ち越した保留にだけ付く・問いが新しく載った周は台帳を監査する R1 を走らせる）、（記録が不正・読めない・引数違い・想定外の例外を非収束と混ぜないこと。後者は「収束の偽装だけを塞ぎ、停止の正直な申告は通す」ことも含む）、`comment-ratio.sh` の注釈カウントと計測漏れの扱い、依存の宣言と marketplace の許可リストの整合、マニフェストの必須欄、配る全部の plugin（marketplace.json の一覧）の今の版の見出しが、それぞれの根の変更の記録（`CHANGELOG.md`）に在るか（版の出し方は [docs/releasing.md](docs/releasing.md)）、文書とコメントが名指しする `REVIEW.md` のセクションと機械の定数が実在するか（ファイル名つきの名指しは、そのファイルに在ることまで見る）、手順書が名指しする役割 agent が `agents/` に実在し・どの役も書く道具を持たず・遮断系は道具ゼロで・手順書にモデル名の写しが戻っていないか、手順書に自作の導入コマンドと `-R` 無しの `gh` が戻っていないか、配布物に固有の技術名と、このリポジトリの検証の道具の名前（下の宣言の節が名指しする物）が混ざっていないか。件数はここに書き写さない（腐るので、走らせた出力を見てほしい）。CI が Linux / macOS / Windows で上の 2 行と同じものを回す。

検査が空振りした場合も `exit 2` で落ちるので、対象が空でも緑になる穴は塞いである。**ゲートは違反をわざと作って赤を確認したものだけを「機能している」と扱う**（`REVIEW.md` の「読むより動かす」を自分に適用した）。**赤を確認していないガードはまだ複数残っている**——腕を 1 本ずつ壊して測った結果、`comment-ratio.sh` の `python3` 不在ガードと例外境界、`git` の 120 秒タイムアウト分岐、`tests/run.sh` 自身の件数検知（`ran` と `EXPECTED_CHECKS` の不一致。最後の砦にその上の砦は無い）、そして `origin` の域が表に無い種類を落とす条件が、壊しても緑のままだった。最後のものは**網羅性検査**（種類を足して域を書き忘れたら落ちる形）で、到達しないのが正常な状態である。件数をここに書き写さない——数えて書いた瞬間に腐る。確かめたいなら、当該ガードを壊して `bash tests/run.sh` が赤くなるかを見てほしい。

環境（OS・道具・権限）のせいで走れなかった検査は、合格の行と別に `# SKIP <能力>: <理由>` の印つきの行（欠けた能力の名前が頭に付く。例: `fifo`・`process-group`・`shellcheck`）で出て、末尾に「見送り N 件」の一覧が出る。見送りを失敗に数えるなら `FAIL_ON_SKIP=1 bash tests/run.sh`（既定では数えない）。そのうえで欠けてよい能力の一覧（空白かカンマ区切り。既定は空＝何も許さない）を `FAIL_ON_SKIP=1 SKIP_ALLOW="fifo process-group" bash tests/run.sh` の形で渡すと、名前がその一覧に在る見送りだけを失敗から除く——名前の無い見送りと一覧に無い名前は失敗に数える。CI は 3 OS とも `FAIL_ON_SKIP=1` を渡し、欠けてよい能力の一覧は OS ごとに `.github/workflows/test.yml` の matrix（`skip_allow`）が持つ（その OS で本当にできない物だけ。道具で無くせる見送りは道具を入れて無くす）。例外は `version-bump` の 1 つで、OS でなく枝の都合で 3 OS とも許す——plugin の中身を変えたのに `plugin.json` の version が据え置きなら赤にする検査は、CI が main か `release/*` の枝を見ているときと、手元で `VERSION_BUMP_STRICT=1` を渡したときだけ赤にし、ほかの枝では据え置きの一覧を見送りの行に出す。

`review-record.py` の終了コードは `0`（今ラウンドにも前ラウンドにも阻害なし＝連続 2 ラウンド）/ `1`（阻害あり）/ `2`（記録が不正）の 3 値。**2 と 1 を取り違えないこと**——2 は記録を直して再実行する合図で、非収束の判定ではない。

### review-loop が読む検証の道具（このリポジトリの宣言）

`/review-loop`・`/review-graph` の手順書・グラフ・プロンプトは、テスト一式・件数の柵・変異テストの実行器を能力の言葉（期限を受ける口・前の結果を持ち越す口など）でしか書かない。どの道具でそれをするかは対象リポジトリの側が名指しし、役は `REVIEW.md` の「固有規約の把握」の読む先から拾う。テスト一式と変異テストの実行器は機械が読む書式の宣言を持つ（テスト一式は engine が走らせる。変異の実行器は `/review-graph` の engine が役のプロンプトに名指しとして貼る）。このリポジトリの宣言はこの節である——`REVIEW.md` は convergence-loops の配布物としてほかのリポジトリでも観点の正本として読まれるので、そこには書かない。

- **テスト一式**: ルートの `.review-checks.json`（`{"suite": [{"name": …, "argv": […]}]}`）。`/review-graph` の engine は、この宣言の語を人の承認なしに shell を通さずに走らせ、終了コードから CI の欄（`p0.local_checks`・`p4.ci`）を書く。段が正常に終わった後も、その段が残した背景のプロセス（グループの外へ出た孫など）は、試行（全段）の終わりに engine が 1 回まとめて止める。試行の外で使う背景のプロセスを残す段（次の段までは宣言が無くても残る）は `"keep_background": true` を宣言する（その段だけ正常終了の片付けをしない。時間切れ・止める信号・異常終了の止め方は宣言に依らない。書式の正本は `graphloops/engine/declared.py`）。全段が緑で終わった一式は、作業ツリーの中身・段の定義・OS と CPU とカーネルの版・段に渡る環境変数（結果に効かないと分かっている会話や端末の識別子などを除く全部）・各段の頭の語の道具が同じなら、別の run・別の worktree でも走らせずにその結果を使い回す（赤は使い回さない。`keep_background` の段を含む一式は毎回走らせる。使い回した回は CI の欄に元の結果の時刻と盤面が載る）。必ず走らせるなら `loop.py launch` の環境に `GRAPHLOOPS_RERUN_CHECKS=1` を付ける（指紋に入れる物・入れない物と理由・置き場の消し方の正本は `graphloops/engine/checks_cache.py`）。宣言の語は Claude Code の許可の仕組みを通らない——他人のリポジトリ・他人の PR を回すときは、宣言とそれが呼ぶスクリプトを先に読め（承認を外した理由・守られなくなった物・残る物は `graphloops/engine/declared.py` の冒頭の注記）。宣言が無いリポジトリでは任せ先が CI の定義から走らせ、その周の CI は engine が確かめていない自己申告として、収束の前に人に諮られる。宣言は CI の定義 `.github/workflows/test.yml` の段の写しで（手元は pytest を uv で入れ、CI は pip で入れるので語は揃えない。並べ方も揃えない——宣言は `-n 4`、CI は `-n auto`。手元では run が並ぶので、run の数だけ worker が増えて機械を飽和させない）、宣言の段の名前が CI の run を持つ段に在ることを `tests/run.sh` の CI の設定の検査（CI_LINT_OK の行）が見る。shellcheck は CI だけが段として回す（手元では `tests/run.sh` が在れば回す）
- **件数の柵**: `EXPECTED_CHECKS`・`EXPECTED_TESTS`・`VOCAB_REACHED`・`EXPECTED_ITEMS`・`EXPECTED_SIM_CHECKS`・`EXPECTED_SIM_REACHED`。置き場と突合の式は `tests/run.sh` のラチェットの表が導く。検査を足した・消した差分は、同じ差分で実測に合わせる。この行の名前がラチェットの表とずれると `tests/run.sh` が赤くなる
- **変異テスト**: ルートの `.review-checks.json` の `mutation` の段（`{"argv": […], "arms": "<腕の一覧のパス>"}`）。腕の一覧は `tests/mutations.json`、実行器は `tests/mutate.py`。engine はこの段を走らせず、ゲートの検算・変異の検算の線・最後の関門の役に名指しとして貼る（段が無いリポジトリでは、役が対象リポジトリの側の散文を探す）。段の書き損じはこの段だけの誤りになり、テスト一式は止めない。道具名の柵（`tests/run.sh`）は禁止語をこの宣言から導く。口（変わったファイルの腕だけ撃つ・起点の版から機械で腕を作る・期限を受ける・前の結果を持ち越す・返答の形を組む）の綴りは `python3 tests/mutate.py --help` が正本。腕の字列が今の版に在るかは `tests/run.sh` が毎回見る
- **変異テストを手元で撃たない決まり**: このリポジトリは変異テストを CI だけで撃つ（持ち主の方針。置き場は `git rev-parse --git-common-dir` の下の `graphloops/policy.md`）。`/review-graph` の run は、その決まりが効いている間、`init` に `--input gates=merge` を足す

## ライセンス

MIT。
