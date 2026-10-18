# このリポジトリを直す人へ

プラグインを使うだけの人は読まなくてよい（入れ方は [README.md](README.md)）。ここは、このリポジトリの試験の回し方と、レビューの役が読む検証のツールの宣言を置く。

## プラグインの分け方

配るプラグインは並列の関係にあり、一覧の正本は `.claude-plugin/marketplace.json`（ルートの README の表はその要約）。convergence-loops・gates・graphloops の 3 本は規律（読み役は毎回新規・文脈遮断・点数を測らない）を共有するが、別々に有効化する——ループ集を入れたら投稿や書き込みの挙動が黙って変わる、を避けるため。attention はこの規律の外で、読み役を立てず GitHub の記録だけを機械で畳む。

## 標準

プラグインをまたぐ書き方と作りの揃え方（配る形・スキルの書き方など）は [docs/standards/README.md](docs/standards/README.md) の一覧に在る。プラグインを作る・直す前に、変える物に当たる標準を開いて合わせる（一覧の各項目の括弧に何を決めた標準かが書いてある）。

## 動作確認

まっさらな環境（macOS・Windows・Linux）でプラグインを入れて、説明書だけで使えるかを試した記録は、索引 [docs/trials/README.md](docs/trials/README.md) から辿れる（試しに使う Windows の VM の手引きも同じ所）。

**これはこのプラグイン自身を開発・改造する人向けの検証で、利用者が対象リポジトリで走らせるものではない。** `/plugin install` で入れた場合、実体はプラグインのキャッシュに置かれて作業ディレクトリには現れないので、`tests/run.sh` は clone しないと存在しない。

```bash
git clone https://github.com/raiki61/claude-plugins
cd claude-plugins
bash tests/run.sh
uv run --no-project --with pytest --with pytest-xdist python -m pytest -n auto graphloops/tests/py   # pytest の置き場（開発の間だけ入れる。方針は graphloops/README.md の「Checks」節）
uv run --no-project --with pytest python -m pytest tests/py   # ルートの pytest の置き場（convergence-loops/scripts/review-record.py の表の検査）。CI は別の起動で回す
```

検査するもの——`review-record.py`・`research-record.py`・`doctor-record.py`・`firstread-record.py` の終了コードの区別、`review-record.py` の履歴（全ラウンドの推移）と問いの台帳の縛り（保留が黙って消えない・出どころが記録に実在する・同じ [block]（必ず直す指摘）が 3 ラウンドの記録に続けて残る行き詰まり（手順書の言う stuck）になったら、それを出どころにした問いを解決済み（resolved）にせずに台帳に載せておく〔載っていなければ落ちる〕・帰属は前の周から持ち越した保留にだけ付く・問いが新しく載った周は台帳を監査する R1 を走らせる）、（記録が不正・読めない・引数違い・想定外の例外を非収束と混ぜないこと。後者は「収束の偽装だけを塞ぎ、停止の正直な申告は通す」ことも含む）、`comment-ratio.sh` の注釈カウントと計測漏れの扱い、依存の宣言と marketplace の許可リストの整合、マニフェストの必須フィールド、配る全部の plugin（marketplace.json の一覧）の今の版の見出しが、それぞれのルートの変更の記録（`CHANGELOG.md`）に在るか（版の出し方は [docs/releasing.md](docs/releasing.md)）、文書とコメントが名指しする `REVIEW.md` のセクションと機械の定数が実在するか（ファイル名つきの名指しは、そのファイルに在ることまで見る）、手順書が名指しする役割 agent が `agents/` に実在し・どの役も書くツールを持たず・遮断系はツールゼロで・手順書にモデル名の写しが戻っていないか、手順書に自作の導入コマンドと `-R` 無しの `gh` が戻っていないか、配布物に固有の技術名と、このリポジトリの検証のツールの名前（下の宣言のセクションが名指しする物）が混ざっていないか。件数はここに書き写さない（腐るので、走らせた出力を見てほしい）。CI が Linux / Windows で上の 3 行と同じものを回す（macOS は 2026-10-16 に外した。runner が動き出さず出荷が止まったため）。

検査が空振りした場合も `exit 2` で落ちるので、対象が空でも緑になる穴は塞いである。**ゲートは違反をわざと作って赤を確認したものだけを「機能している」と扱う**（`REVIEW.md` の「読むより動かす」を自分に適用した）。**赤を確認していないガードはまだ複数残っている**——腕を 1 本ずつ壊して測った結果、`comment-ratio.sh` の `python3` 不在ガードと例外境界、`git` の 120 秒タイムアウト分岐、`tests/run.sh` 自身の件数検知（`ran` と `EXPECTED_CHECKS` の不一致。最後の砦にその上の砦は無い）、そして `review-record.py` の問いの種類の表で、出どころ（`origin` 列）が指せる先の区分〔ユニット・素材・R1〜R4 のどれか・何も指さない、の 4 通り。コードでは域と呼ぶ〕が 4 通りのどれでもない種類を落とす条件が、壊しても緑のままだった。最後のものは**網羅性検査**（種類を足して指せる先を書き忘れたら落ちる形）で、到達しないのが正常な状態である。件数をここに書き写さない——数えて書いた瞬間に腐る。確かめたいなら、当該ガードを壊して `bash tests/run.sh` が赤くなるかを見てほしい。

環境（OS・ツール・権限）のせいで走れなかった検査は、合格の行と別に `# SKIP <能力>: <理由>` の印つきの行（欠けた能力の名前が頭に付く。例: `fifo`・`process-group`・`shellcheck`）で出て、末尾に「見送り N 件」の一覧が出る。見送りを失敗に数えるなら `FAIL_ON_SKIP=1 bash tests/run.sh`（既定では数えない）。そのうえで欠けてよい能力の一覧（空白かカンマ区切り。既定は空＝何も許さない）を `FAIL_ON_SKIP=1 SKIP_ALLOW="fifo process-group" bash tests/run.sh` の形で渡すと、名前がその一覧に在る見送りだけを失敗から除く——名前の無い見送りと一覧に無い名前は失敗に数える。CI（試験の job は ubuntu と windows の 2 つ）はどちらの OS でも `FAIL_ON_SKIP=1` を渡し、欠けてよい能力の一覧は OS ごとに `.github/workflows/test.yml` の matrix（`skip_allow`）が持つ（その OS で本当にできない物だけ。ツールで無くせる見送りはツールを入れて無くす）。例外は `version-bump` の 1 つで、OS でなくブランチの都合で両方の OS で許す——plugin の中身を変えたのに `plugin.json` の version が据え置きなら赤にする検査は、CI が main か `release/*` のブランチを見ているときと、手元で `VERSION_BUMP_STRICT=1` を渡したときだけ赤にし、ほかのブランチでは据え置きの一覧を見送りの行に出す。

`review-record.py` の終了コードは `0`（今ラウンドにも前ラウンドにも阻害なし＝連続 2 ラウンド）/ `1`（阻害あり）/ `2`（記録が不正）の 3 値。**2 と 1 を取り違えないこと**——2 は記録を直して再実行する合図で、非収束の判定ではない。

### review-loop が読む検証のツール（このリポジトリの宣言）

`/review-loop`・`/review-graph` の手順書・グラフ・プロンプトは、テスト一式・件数のチェック・変異テストの実行器を能力の言葉（期限を受ける口・前の結果を持ち越す口など）でしか書かない。どのツールでそれをするかは対象リポジトリの側が名指しし、役は `REVIEW.md` の「固有規約の把握」の読む先から拾う。テスト一式と変異テストの実行器は機械が読む書式の宣言を持つ（テスト一式は engine が走らせる。変異の実行器は `/review-graph` の engine が役のプロンプトに名指しとして貼る）。このリポジトリの宣言はこのセクションである——`REVIEW.md` は convergence-loops の配布物としてほかのリポジトリでも観点の正本として読まれるので、そこには書かない。

- **テスト一式**: ルートの `.review-checks.json`（`{"suite": [{"name": …, "argv": […]}]}`）。`/review-graph` の engine は、この宣言の語を人の承認なしに shell を通さずに走らせ、終了コードから CI のフィールド（`p0.local_checks`・`p4.ci`）を書く。段が正常に終わった後も、その段が残した背景のプロセス（グループの外へ出た孫など）は、試行（全段）の終わりに engine が 1 回まとめて止める。試行の外で使う背景のプロセスを残す段（次の段までは宣言が無くても残る）は `"keep_background": true` を宣言する（その段だけ正常終了の片付けをしない。時間切れ・止める信号・異常終了の止め方は宣言に依らない。書式の正本は `graphloops/engine/declared.py`）。全段が緑で終わった一式は、作業ツリーの中身・段の定義・OS と CPU とカーネルの版・段に渡る環境変数（結果に効かないと分かっている会話や端末の識別子などを除く全部）・各段のコマンドの先頭の語（`argv[0]`。`python3` や `bash` など）が指す実ファイル（パス・大きさ・更新時刻で見る）が同じなら、別の run・別の worktree でも走らせずにその結果を使い回す（赤は使い回さない。`keep_background` の段を含む一式は毎回走らせる。使い回した回は CI のフィールドに元の結果の時刻と盤面が載る）。必ず走らせるなら `loop.py launch` の環境に `GRAPHLOOPS_RERUN_CHECKS=1` を付ける（指紋に入れる物・入れない物と理由・置き場の消し方の正本は `graphloops/engine/checks_cache.py`）。宣言の語は Claude Code の許可の仕組みを通らない——他人のリポジトリ・他人の PR を回すときは、宣言とそれが呼ぶスクリプトを先に読め（承認を外した理由・守られなくなった物・残る物は `graphloops/engine/declared.py` の冒頭の注記）。宣言が無いリポジトリでは任せ先が CI の定義から走らせ、その周の CI は engine が確かめていない自己申告として、収束の前に人に諮られる。宣言は CI の定義 `.github/workflows/test.yml` の段の写しで（手元は pytest を uv で入れ、CI は pip で入れるので語は揃えない。並べ方も揃えない——宣言は `-n 4`、CI は `-n auto`。手元では run が並ぶので、run の数だけ worker が増えて機械を飽和させない）、宣言の段の名前が CI の run を持つ段に在ることを `tests/run.sh` の CI の設定の検査（CI_LINT_OK の行）が見る。shellcheck は CI だけが段として回す（手元では `tests/run.sh` が在れば回す）
- **件数のチェック**: `EXPECTED_CHECKS`・`EXPECTED_TESTS`・`VOCAB_REACHED`・`EXPECTED_ITEMS`・`EXPECTED_SIM_CHECKS`・`EXPECTED_SIM_REACHED`。置き場と突合の式は `tests/run.sh` のラチェットの表が導く。検査を足した・消した差分は、同じ差分で実測に合わせる。この行の名前がラチェットの表とずれると `tests/run.sh` が赤くなる
- **変異テスト**: ルートの `.review-checks.json` の `mutation` の段（`{"argv": […], "arms": "<腕の一覧のパス>"}`）。腕の一覧は `tests/mutations.json`、実行器は `tests/mutate.py`。engine はこの段を走らせず、ゲートの検算・変異の検算の線・最後のゲートの役に名指しとして貼る（段が無いリポジトリでは、役が対象リポジトリの側の散文を探す）。段の書き損じはこの段だけの誤りになり、テスト一式は止めない。ツール名のチェック（`tests/run.sh`）は禁止語をこの宣言から導く。口（変わったファイルの腕だけ撃つ・起点の版から機械で腕を作る・期限を受ける・前の結果を持ち越す・返答の形を組む）の綴りは `python3 tests/mutate.py --help` が正本。腕の字列が今の版に在るかは `tests/run.sh` が毎回見る
- **変異テストを手元で撃たない決まり**: このリポジトリは変異テストを CI だけで撃つ（持ち主の方針。置き場は `git rev-parse --git-common-dir` の下の `graphloops/policy.md`）。`/review-graph` の run は、その決まりが効いている間、`init` に `--input gates=merge` を足す
