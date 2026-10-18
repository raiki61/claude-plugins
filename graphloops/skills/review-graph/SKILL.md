---
description: 退役予定（早くて 2026-11-18 に消す。代わりは /works-factory）。コード変更後の自動レビュー・修正サイクルのグラフ実行版で、人の修正依頼（既存のコードへの「これを直して」「この仕組みを直したい」。差分が無くても始められる）を判定（根本診断）から入れて直させる入口も持つ（同梱の手順の「判定から入る（人の修正依頼）」）。起動するのは、人が /review-graph と打ったときか「工程に回して」と言ったときだけ——AI は自分から起動せず、実装完了時・リファクタリング後・バグ修正後と、誤字・コメント・文言の直しでない直す依頼に当たったら、この工程に回すことを人に提案する。回す手順は機械（engine）が持ち、この手順書は engine の呼び方だけを書く。
allowed-tools: Bash, Agent, Skill, Read, Write, Edit, Grep, Glob
---

# review-graph

**退役の予告**: `/review-graph` は早くて 2026-11-18 に消す。代わりは `/works-factory`（works-factory プラグイン）。呼ばれたら、手を動かす前にこの 2 文を利用者に見せる。

## これは何か

コード変更を、採点する目（別の会話で動く役割 agent）と直す手（あなた）を分けて、指摘が出なくなるまで回すレビューループである。この本文が読み込まれているのは、人が `/review-graph` と打ったか「工程に回して」と言った後で、回すのはあなたである。語: ノード＝グラフの工程の 1 つ、run＝ループ 1 回分の実行、周＝採点から修正までの 1 巡、盤面＝engine が run の状態を置くフォルダ、役＝別の会話で採点する agent、阻害＝収束を止める指摘。このプラグイン graphloops は、同じマーケットプレイスの姉妹プラグイン convergence-loops が配る散文の手順書 `/review-loop` を、機械が読めるグラフに写したもので、目的も、周ごとの記録の形（`round-<N>.json` と検証器 `review-record.py`）も同じである。違いは手順の置き場だけ:

- 置き場（グラフ・engine・rules がそれぞれ何を持つか）は [references/rules.md](references/rules.md) の頭

このプラグインの置き場は `${CLAUDE_PLUGIN_ROOT}` である（読み込み時に実際のパスへ置き換わる）。下の `references/` はこのファイルと同じフォルダにある。別ファイルのコマンドに書いた `CLAUDE_PLUGIN_ROOT`（`$` と波括弧で囲んだ形）は置き換わらず Bash の環境変数にも無いので、ここに出たパス（置き換わらずに見えているなら、このファイル（`skills/review-graph/SKILL.md`）のフォルダの 2 つ上、graphloops のルート）に読み替えて打て。

旗の無い `init` は**回し役（ノードを自分でこなす会話）の要らない回し方**になる（下の「[早見](#早見)」）: writer のノード（基準点・目的・前提・修正案・修正・手直し・報告）と局所レビューの skill のノードも engine が `claude -p` の子として起動し、背景の線（周と並べて走らせる変異の検算）も回し手（`run` が背景に立てる engine のプロセス）が立てる。あなたは起動・`run` の打ち直し・人のゲートへの答えと、人に渡ったノード（`run` の終了コード 14）の手当てだけをする（終了コード 13 は engine の不具合）。`init --no-engine-runners` の run は今までどおり**会話で回す**（持ち主の決定 2026-09-27 で消す予定の道）——このループを回す session が **writer（実装者）**で、それはあなたである（ノードのこなし方は [references/conversation-run.md](references/conversation-run.md)）。どちらの run でも、**ラベル確定（指摘を阻害とするかの判定）・根本診断・収束判定はしない。** 判定は役割 agent が返し、engine がそれを記録に写す。異議があるなら自分で覆さず、次の周の新しい judge に再判定させる。

役割 agent は convergence-loops に同梱の役の定義（`convergence-loops:judge` のように接頭辞付きで指す）と、依存で入る `pr-review-toolkit:comment-analyzer` を使う。役は engine が `loop.py launch` で起動する（役の定義を読んで起動するので、あなたは役の名前を扱わない）。モデル・ツールは役の定義が正本。

## 早見

回し役なしの run（旗の無い `init`）の会話のターンはこれで足りる——ターンの手引きはここ 1 か所で、値の表の正本は engine の `runner.CODES`・`HOW`。細部は下の「場面ごとに読むファイル」の別ファイルに在る。

1. `init` する（`loop.py` は `${CLAUDE_PLUGIN_ROOT}/scripts/loop.py`。要れば `--input gates=merge`・`--stop-after-round N`）。返った `dir` を以降の全部の呼び出しに `--dir` で渡す。直す依頼なら最初の `next` の前に `add`（[references/judgment-entry.md](references/judgment-entry.md)）。run の間ずっと省く optional のノード（engine が走らせる CI のノードなど）は、最初の `run` の前に `loop.py skip --node <id> --reason <理由> --every-round --dir <DIR>` を打つ——回し手はノードが出た瞬間に起動するので、出た後の `skip` では間に合わない。CI のノードを省いた run の止まり方は [references/rules.md](references/rules.md)——省けば回り切るわけではない。
2. `loop.py run --dir <DIR>` を前景で打ち（540 秒で必ず戻る。完了の知らせに頼らない。端末・CI・台本なら `run --foreground` が止まるまで戻らない）、終了コードで次の手を決める:
   - **20**: 何もせずにもう一度 `run`
   - **13**: engine の不具合（盤面の矛盾——engine が子を起動するコマンド（`claude -p` の引数）も、起動できない理由も持たないノード）。記録器に残る。`handoff` の各行を、その行の `handoff_why` のとおりにこなし（返答は別のファイルに書いて `done --node <id> --output <file>`）、もう一度 `run`。前の版の engine で始めた盤面と `--no-engine-runners` の run では、今までどおり会話がこなすノードで 13 が返る（前の版の決まった戻りで、不具合ではない。[references/runnerless.md](references/runnerless.md)）
   - **10**: `ask` を人に見せ（[references/steps.md](references/steps.md) の 3「人に聞くターン」の聞き方）、`answer` してからもう一度 `run`
   - **14**: `needs_human` は**まずあなたが受ける**。各行の `why` を読み、推しで済む物（人の取捨が要らない物）はあなたがこなして `run` を打ち直す——理由が外し方を名指す行（入れ子の sandbox〔OS の囲い sandbox の中で `run` を打った〕・プラグインが無い・sandbox の立たない場）は、その外し方（sandbox の設定・プラグインを入れる・回す場を移す）を当ててから `loop.py relaunch --node <id> --reason <理由>`（入れ子の sandbox なら `--reprobe` も）。engine が起動した子の返答をあなたが引き取るなら、返答を別のファイルに書いて `done --output`（子が置き場 `out_path` に残した本文は、どう渡しても子の返答と同じ厳しさで検査される）。作業ツリーを書き換えるノード（修正・手直し・仕様）の子が落ちた・受け付けの拒み（返答の形が合わない）が graph の上限の回数まで続いた行（回し手の自動の起動し直し `relaunch --if-untouched` が効かなかった回を含む）は、**作業ツリーを確かめてから** `relaunch`——途中まで書いた編集の上に、それを知らない新しい会話が重ねて書く。人に上げるのは取捨（能力を手放す・人の方針を変える）の行だけ
   - **0**・**11**・**12**: ここで初めてターンを終えてよい（0 なら盤面の `report.md` を依頼者の言語で出す。11 は周の止めで、続けるなら `loop.py resume`。12 は行き詰まりで、`run` の出力の `detail` を読んで直す）。14 でターンを終えるのは、取捨の行を人に上げたときだけ
   - 1・2（run そのものが拒まれた・盤面が読めない）は標準エラーを読んで直してから、128 以上（信号で止まった）はそのまま、もう一度 `run`——続きは盤面から拾う
3. 次の周で直せる赤（テストの失敗・受け付けの拒み）は人に上げない——engine が次の周の判定に渡す。人に見せるのは 10 の `ask` と、14 のうち取捨の行だけ。
4. 人が止めてと言ったら `loop.py stop --reason <理由> --dir <DIR>`。

## 場面ごとに読むファイル

この本文はターンと読むファイルだけを持つ。**場面に当たったら、そのファイルを読んでから手を動かせ。**

- 始める・`run` の出力の読み方・人に聞くターンと周の途中のゲート・人が止める・子の残り・終わり: [references/steps.md](references/steps.md)
- `run` が 13 か 14 を返した（engine が起動できないノードの訳と外し方）: [references/runnerless.md](references/runnerless.md)
- ノードを自分でこなす（`--no-engine-runners` の run・13 と 14 で引き取ったノード。`mode` ごとの扱い・`launch`・任せ先・`done`）: [references/conversation-run.md](references/conversation-run.md)
- 人の修正依頼を判定から入れる・途中の周で依頼を足す: [references/judgment-entry.md](references/judgment-entry.md)
- `init` で流れを選ぶ（`gates=merge`・TDD・`flow=spec`）・run の成果を重ねる: [references/flows.md](references/flows.md)
- 人の方針の文書の置き場・届く先・書き換え: [references/policy.md](references/policy.md)
- 始める前に 1 度（人の居ないターンで消す操作を打たない、などの回す側の手の心得）と、版の上げ下げ・記録の手当て（`patch`）・CI のノードを省く・作業ツリーの突合・Web の調べ・大きな差分: [references/rules.md](references/rules.md)

## どのターンでも

- 場所を見失ったら `loop.py status --dir <DIR>` → `loop.py next --dir <DIR>`。盤面はディスクにある。
- 済んだノードに `done` し直さない（同じ周で採点役を回し直して有利な判定を採らない。やり直しは次の周）。
