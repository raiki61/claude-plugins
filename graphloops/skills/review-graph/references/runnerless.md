# review-graph を回し役なしで回すとき（engine が起こせない節が 14 に出る訳）

## 回し役なしで回す

回し役なしの run（旗の無い `init`）では、回し手が writer の節と局所レビューの skill の節も起こし、背景の線（変異の検算）も受領を `done` して切り離して立てる。人が柵を外した run（`init --unfenced-delegates`）の任せ先も、engine が sandbox の外で起こす。手番は本文の「早見」。会話に返す 13 は engine の不具合だけで、engine が起こせない節は理由を持って 14 に出る（各行の `why`）:

- sandbox が立たない場（Windows のネイティブ・bwrap の無い Linux）と、作業ツリーが別の作業ツリーの下に在る形（`<repo>/.claude/worktrees/<名前>`）の、作業ツリーを書き換える節（修正・手直し・仕様）と局所レビュー——instance の `unlaunched` が理由。sandbox の立つ機械か、別の作業ツリーの下でない作業ツリーで回し直す
- 入れ子の sandbox（Claude Code の sandbox の中で `loop.py run` を打った場。子は起きるが Bash の呼び出しごとに sandbox の初期化で落ちる）と engine の確かめの子が測った run の、作業ツリーを書き換える節・局所レビュー・任せ先——理由に外し方（起こす側の sandbox から `loop.py` を外す `sandbox.excludedCommands` か、sandbox の外で `run` を打つ）が在る。外した後に `loop.py relaunch --node <id> --reason <理由> --reprobe` で測り直すと engine が起こす。読むだけの子は起こし、Bash で測れていないことを記録に残す
- engine が語を組めない役の節（別 plugin の役の定義がこの環境に無い・道具つきで起こせない形）と、必須のレンズの定義がこの環境に無い局所レビュー——`unlaunched` が理由。プラグインを入れたら `relaunch`
- 局所レビューの子が、必須のレンズを起こさなかった・`material` を `awaiting_human` にした返答を返し続けた（受け付けが拒み、同じ会話の続きが上限まで届かなかった）回。条件付きのレンズを起こさなかった行は受け付けられ、報告の『未確認のレンズ』に並ぶ

前の版の engine で始めた盤面（`next` の `notes` が知らせる）は今までどおり: 上の節と、受領の形を持たない背景の線・柵を外した run の任せ先・子が届かなかった局所レビューが 13 で会話に返り、あなたがこなして `done` する（各行の `handoff_why`）。

会話の手番の注意（engine の中の起こし方・一時の置き場・申告の突合・起こし直しの条件の正本は、engine の `role_run.runner_permission`・`role_run.skill_permission`・commands の `CHILD_TMP_PARENT` と `_sandbox_probe` の段の注記と graph の `launch.runner.why`。ここに写さない。14 の手当ては本文の「早見」）:

- 子は git の index に書けないので `git add -N` を打てない。局所レビューをあなたがこなすとき（14 から引き取った・前の版の盤面で 13 に返った）は、基準点の `intent_to_add` のパスを skill を呼ぶ前にあなたが `git add -N` せよ（engine の周の版は未追跡も載せるので、差分と規模には要らない。engine が起こす局所レビューの子には、変更ファイルの一覧の未追跡のファイルを Read で読ませる）。
- 子は別の役を起こせないので、修正の先行例の Web の調べは判定者の行を採るか、調べていないと書く（修正の返答の `precedent`）。
- 子ではフックが動かないので、子の読了は `reads.jsonl` に載らない（記録の `loop.wrote_refs_reads` の `unrecorded` と報告の人向けの項目に出る）。
- 書き換える節の申告と作業ツリーの食い違い（`process.git_mismatches` の `kind: declared`）と、作業ツリーの外に残った物（`kind: outside_tmp`）は、受け付けたうえで記録に残り、次の周の判定役が読む——あなたは手を打たない。
