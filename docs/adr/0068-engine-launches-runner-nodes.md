# 0068. 回す側の節と comment-analyzer も engine が claude -p で起こす（手順 H3）

- 状態: 採用
- 日付: 2026-09-27
- 決めた人: 人（H3 の順番は計画の手順 H。読むだけの節を investigator と同じ形にそろえること、局所レビューの skill と背景の線を会話に返すことは人の答え 2026-09-27）。それ以外の形の細部は wip/h3-writer の run の判定と修正
- 実装: 0.21.4 に入った（`init --engine-runners` を選んだ run だけ。既定は今のまま会話が回す）

## 文脈

- [0063](0063-roles-as-child-processes.md) の結果は「定義が道具の一覧を持たない役（comment-analyzer）・ファイルを書く道具を持つ役は engine が起こさず、回す側が Agent ツールで起こす形が残る」と書いた。[0018](0018-delegates-in-sandbox.md) の残りも「comment-analyzer は今も Agent ツールで起こし柵が無い」を挙げた。
- 0.21.4 でこの 2 つが変わった。ADR を読む人が今の形と逆のことを読まないよう、0018・0063 を継ぐ記録を置く。

## 決定

- 回す側の節も engine が `claude -p` で起こせる（`init --engine-runners`）。graph の `launch.runner` と `role_run.runner_permission` が形を決める。
  - 読むだけの節は investigator と同じ形（sandbox の中で測るコマンドが走る）。
  - 書き換える節（修正・手直し・仕様・TDD のテストを書く節）は `dontAsk`・`Edit(./**)`・`Write(./**)`・sandbox の中の Bash で起こす。sandbox の書き込みの拒否は、守る場所から作業ツリーの根だけを外し、根の下の `.git` を足した一覧。作業ツリーが別の作業ツリーの下に在る形と、sandbox の立たない場は起こさず会話に返す。
  - 起こす瞬間に柵（`commands._runner_refusal`）が形を組み直して突き合わせ、起こす前後の git の状態（HEAD・枝・stash・作業ツリーの一覧）が違えば受け付けない。書き換える子が落ちても、回し手は自動で起こし直さない。
- comment-analyzer は graph の `launch.tooled.narrow` で読むだけに狭めて、engine が起こす。
- 局所レビューの skill と背景の線は、今どおり会話に返す。

## 比べた案

作業メモに記載なし。

## 理由

[0063](0063-roles-as-child-processes.md) と同じ（止まっても気づかない・中継の写し違いを、構造で消すため）。書き換える子は、[0018](0018-delegates-in-sandbox.md) と同じく規律でなく OS の sandbox で分ける。

## 結果

- 0063 の「comment-analyzer・ファイルを書く道具を持つ役は回す側が Agent ツールで起こす形が残る」は、`--engine-runners` を選んだ run では当たらない。0018 の残りの「comment-analyzer は今も Agent ツールで起こし柵が無い」は、読むだけに狭めた形で閉じた。
- 残り（0.21.4 の時点）: 既定を `--engine-runners` にする切り替え・背景の線を回し手が立てる形・research-graph の surveyor の節・Linux と WSL2 の実機での書き換える子の sandbox。書き換える子が作業ツリーの外（sandbox の既定で書ける利用者ごとの一時の置き場）へ書いた物と、作業ツリーの中の申告に無い書き込みを見つける層は、この決定の時点で無かった（後の run の判定で開いた）。
- 補足（後の run の判定と人の答え 2026-09-27）: 決定の 3 つ目の git の柵は、全作業ツリーで共有する stash と作業ツリーの一覧（git-worktree の REFS 節）を拒否から外して trace に残し、この作業ツリーの HEAD・枝だけで拒む形になった——並行の run が作業ツリーを足しただけで書く子が止まった。書き換える子の launch が受け付けの前に居なくなった回は、前の試行の子を止め切った後で作業ツリーと HEAD・枝が起こした時点と同じなら、回し手が 1 回だけ起こし直す（`relaunch --if-untouched`）。『自動で起こし直さない』が防ぐのは途中の編集に新しい会話が重ねることで、触っていないと測れた回には防ぐ物が無い。子が落ちた・拒否が上限まで続いた書き換える子（launch は締めまで済んだ）は今までどおり人に渡す。

## 見直す条件

作業メモに記載なし。

## 出どころ

- リポジトリの中: 0.21.4（eb8f11d）。[計画の文書の H3〜H5 の実施](../graphloops-rearchitecture.md)の段、[review-graph の手順書](../../graphloops/commands/review-graph.md)の engine の起こし方。
