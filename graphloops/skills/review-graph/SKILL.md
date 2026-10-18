---
description: コード変更後の自動レビュー・修正サイクルのグラフ実行版で、人の修正依頼（既存のコードへの「これを直して」「この仕組みを直したい」。差分が無くても始められる）を判定（根本診断）から入れて直させる入口も持つ（同梱の手順の「判定から入る（人の修正依頼）」）。起動するのは、人が /review-graph と打ったときか「工程に回して」と言ったときだけ——AI は自分から起動せず、実装完了時・リファクタリング後・バグ修正後と、誤字・コメント・文言の直しでない直す依頼に当たったら、この工程に回すことを人に提案する。回す手順は機械（engine）が持ち、この手順書は engine の呼び方だけを書く。
allowed-tools: Bash, Agent, Skill, Read, Write, Edit, Grep, Glob
---

# review-graph

## これは何か

コード変更を、採点する目（別の会話で動く役割 agent）と直す手（あなた）を分けて、指摘が出なくなるまで回すレビューループである。このプラグイン graphloops は、同じマーケットプレイスの姉妹プラグイン convergence-loops が配る散文の手順書 `/review-loop` を、機械が読めるグラフに写したもので、目的も、周ごとの記録の形（`round-<N>.json` をディレクトリに積み、検証器 `review-record.py` がディレクトリごと読んで阻害要因を列挙する）も同じである。違いは手順の置き場だけ:

- **グラフ**（このプラグインの `graphs/review-loop.json`）—— 工程（節）・依存・役・各節のプロンプトと返答の型
- **engine**（このプラグインの `scripts/loop.py`）—— グラフを読んで盤面を持つ機械。どの節が終わったか・同時に走らせてよい組・各節に渡してよいもの（グラフの `reads` の宣言に無いものはプロンプトに貼らない）・作業ツリーの前後突合・走らせなかった素材の欄・R1/R2 の再発火・周の記録の組み立て・検証器の 3 分岐の読み取り・周の上限
- **rules**（このプラグインの `rules/review-loop.py`）—— グラフに書けない算術。記録の欄と語彙は検証器の定数を写さず import する

この手順書は、あなたが engine をどう呼ぶかだけを書く。このプラグインの置き場は `${CLAUDE_PLUGIN_ROOT}` である（スキルを読み込んだ時に実際のパスへ置き換わる）。下の `references/` はこのファイルと同じフォルダの中にある。別ファイルの命令に書いた `CLAUDE_PLUGIN_ROOT`（`$` と波括弧で囲んだ形）は Bash の環境変数には無いので、この置き場に読み替えて打て。

旗の無い `init` は**回し役の要らない回し方**になる（下の「[早見](#早見)」）: writer の節（基準点・目的・前提・修正案・修正・手直し・報告）と局所レビューの skill の節も engine が `claude -p` の子として起こし、背景の線〔変異の検算〕も回し手が立てる。あなたは起動・`run` の打ち直し・人の関所への答えと、人に渡った節（14）の手当てだけをする（13 は engine の不具合）。`init --no-engine-runners` の run は今までどおり**会話で回す**（人の決定 2026-09-27 で消す予定の道）——このループを回す session が **writer（実装者）**で、それはあなたである（節のこなし方は [references/conversation-run.md](references/conversation-run.md)）。どちらの run でも、**ラベル確定・根本診断・収束判定はしない。** 判定は役割 agent が返し、engine がそれを記録に写す。異議があるなら自分で覆さず、次の周の新しい judge に再判定させる。

役割 agent は convergence-loops に同梱の役の定義（`convergence-loops:judge` のように接頭辞付きで指す）と、依存で入る `pr-review-toolkit:comment-analyzer` を使う。役は engine が `loop.py launch` で起こす（役の定義を読んで起こすので、あなたは役の名前を扱わない）。定義が道具の一覧を持たない役（`pr-review-toolkit:comment-analyzer`）も、graph の `launch.tooled.narrow` の値で読むだけ（Read・Glob・Grep と読むだけの Bash）に狭めて engine が起こす。engine が起こせない役だけ、`agent_type` をそのまま Agent の `subagent_type` に渡す。モデル・道具は役の定義が正本で、この手順書にもグラフにも書かない。

## 早見

回し役なしの run（旗の無い `init`）の会話の手番はこれで足りる——手番の手引きはここ 1 か所で、値の表の正本は engine の `runner.CODES`・`HOW`。細部は下の「場面ごとに読むファイル」の別ファイルに在る。

1. `init` する（要れば `--input gates=merge`・`--stop-after-round N`）。返った `dir` を以降の全部の呼び出しに `--dir` で渡す。直す依頼なら最初の `next` の前に `add`（[references/judgment-entry.md](references/judgment-entry.md)）。run の間ずっと省く optional の節（engine が走らせる CI の節など）は、最初の `run` の前に `loop.py skip --node <節> --reason <理由> --every-round --dir <DIR>` を打つ——回し手は節が出た瞬間に起こすので、出た後の `skip` では間に合わない。CI の節を省いた run は、収束の手前で CI の問いを 1 度だけ人に聞き、答えた後は聞き直さずに、残る阻害が CI 未確認だけの周で止まる（盤面の `stop_reason` が `ci_unverified_stopped`）——省けば回り切るわけではない。
2. `loop.py run --dir <DIR>` を前景で打ち（540 秒で必ず戻る。完了の知らせに頼らない。端末・CI・台本なら `run --foreground` が止まるまで戻らない）、終了コードで次の手を決める:
   - **20**: 何もせずにもう一度 `run`
   - **13**: engine の不具合（盤面の矛盾——engine が起こす語も、起こせない理由も持たない節）。記録器に残る。`handoff` の各行を、その行の `handoff_why` のとおりにこなし（返答は別のファイルに書いて `done --node <id> --output <file>`）、もう一度 `run`。前の版の engine で始めた盤面と `--no-engine-runners` の run では、今までどおり会話がこなす節で 13 が返る（[references/runnerless.md](references/runnerless.md)）
   - **10**: `ask` を人に見せ（[references/steps.md](references/steps.md) の 3「人に聞く番」の聞き方）、`answer` してからもう一度 `run`
   - **14**: `needs_human` は**まずあなたが受ける**。各行の `why` を読み、推しで済む物はあなたがこなして `run` を打ち直す——理由が外し方を名指す行（入れ子の sandbox・プラグインが無い・sandbox の立たない場）は、外し方を当ててから `loop.py relaunch --node <id> --reason <理由>`（入れ子の sandbox なら `--reprobe` も）。engine が起こした子の返答をあなたが引き取るなら、返答を別のファイルに書いて `done --output`（置き場 `out_path` の子の返答は、どう渡しても子の返答として照らされる）。作業ツリーを書き換える節（修正・手直し・仕様）の子が落ちた・拒みが上限まで続いた行（回し手の自動の起こし直し `relaunch --if-untouched` が効かなかった回を含む）は、**作業ツリーを確かめてから** `relaunch`——途中まで書いた編集の上に、それを知らない新しい会話が重ねて書く。人に上げるのは取捨（能力を手放す・人の方針を変える）の行だけ
   - **0**・**11**・**12**: ここで初めて手番を終えてよい（0 なら盤面の `report.md` を依頼者の言語で出す。11 は周の止めで、続けるなら `loop.py resume`。12 は `detail` を読む）。14 で手番を終えるのは、取捨の行を人に上げたときだけ
   - 1・2（run そのものが拒まれた・盤面が読めない）は標準エラーを読んで直してから、128 以上（信号で止まった）はそのまま、もう一度 `run`——続きは盤面から拾う
3. 次の周で直せる赤（テストの失敗・受け付けの拒み）は人に上げない——engine が次の周の判定に渡す。人に見せるのは 10 の `ask` と、14 のうち取捨の行だけ。
4. 人が止めてと言ったら `loop.py stop --reason <理由> --dir <DIR>`。

## 場面ごとに読むファイル

この本文は手番と読むファイルだけを持つ。**場面に当たったら、そのファイルを読んでから手を動かせ。**

- 始める・`run` の出力の読み方・人に聞く番と周の途中の関所・人が止める・子の残り・終わり: [references/steps.md](references/steps.md)
- `run` が 13 か 14 を返した（engine が起こせない節の訳と外し方）: [references/runnerless.md](references/runnerless.md)
- 節を自分でこなす（`--no-engine-runners` の run・13 と 14 で引き取った節。`mode` ごとの扱い・`launch`・任せ先・`done`）: [references/conversation-run.md](references/conversation-run.md)
- 人の修正依頼を判定から入れる・途中の周で依頼を足す: [references/judgment-entry.md](references/judgment-entry.md)
- `init` で流れを選ぶ（`gates=merge`・TDD・`flow=spec`）・run の成果を重ねる: [references/flows.md](references/flows.md)
- 人の方針の文書の置き場・届く先・書き換え: [references/policy.md](references/policy.md)
- 始める前に 1 度（人の居ない手番で消す操作を打たない、などの回す側の手の心得）と、版の上げ下げ・記録の手当て（`patch`）・CI の節を省く・作業ツリーの突合・Web の調べ・大きな差分: [references/rules.md](references/rules.md)

## どの手番でも

- 会話が圧縮されて場所を見失ったら `loop.py status --dir <DIR>` → `loop.py next --dir <DIR>`。盤面はディスクにある。
- 済んだ節に `done` し直さない（同じ周で採点役を回し直して有利な判定を採らない。やり直しは次の周）。
