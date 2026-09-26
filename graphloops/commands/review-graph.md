---
description: コード変更後の自動レビュー・修正サイクルのグラフ実行版で、人の修正依頼（既存のコードへの「これを直して」「この仕組みを直したい」。差分が無くても始められる）を判定（根本診断）から入れて直させる入口も持つ（本文の「判定から入る（人の修正依頼）」）。起動するのは、人が /review-graph と打ったときか「工程に回して」と言ったときだけ——AI は自分から起動せず、実装完了時・リファクタリング後・バグ修正後と、誤字・コメント・文言の直しでない直す依頼に当たったら、この工程に回すことを人に提案する。回す手順は機械（engine）が持ち、この手順書は engine の呼び方だけを書く。
allowed-tools: Bash, Agent, Skill, Read, Write, Edit, Grep, Glob
---

## これは何か

コード変更を、採点する目（別の会話で動く役割 agent）と直す手（あなた）を分けて、指摘が出なくなるまで回すレビューループである。このプラグイン graphloops は、同じマーケットプレイスの姉妹プラグイン convergence-loops が配る散文の手順書 `/review-loop` を、機械が読めるグラフに写したもので、目的も、周ごとの記録の形（`round-<N>.json` をディレクトリに積み、検証器 `review-record.py` がディレクトリごと読んで阻害要因を列挙する）も同じである。違いは手順の置き場だけ:

- **グラフ**（このプラグインの `graphs/review-loop.json`）—— 工程（節）・依存・役・各節のプロンプトと返答の型
- **engine**（このプラグインの `scripts/loop.py`）—— グラフを読んで盤面を持つ機械。どの節が終わったか・同時に走らせてよい組・各節に渡してよいもの（グラフの `reads` の宣言に無いものはプロンプトに貼らない）・作業ツリーの前後突合・走らせなかった素材の欄・R1/R2 の再発火・周の記録の組み立て・検証器の 3 分岐の読み取り・周の上限
- **rules**（このプラグインの `rules/review-loop.py`）—— グラフに書けない算術。記録の欄と語彙は検証器の定数を写さず import する

この手順書は、あなたが engine をどう呼ぶかだけを書く。`${CLAUDE_PLUGIN_ROOT}` は Claude Code がこのプラグインの置き場に展開する変数である。

このループを回す session が **writer（実装者）**で、それはあなたである。あなたがするのは、基準点・目的・前提の固定、局所レビューの skill の実行、機械が返す節の起動、修正必須の指摘（[block]）と今直すと判定された提案（do-now）の修正と閉鎖の実証（CI の再実行と規模指標は engine が走らせる——宣言の無いリポジトリの CI だけ任せ先）、最終報告の執筆。**ラベル確定・根本診断・収束判定はしない。** 判定は役割 agent が返し、engine がそれを記録に写す。異議があるなら自分で覆さず、次の周の新しい judge に再判定させる。

役割 agent は convergence-loops に同梱の役の定義（`convergence-loops:judge` のように接頭辞付きで指す）と、依存で入る `pr-review-toolkit:comment-analyzer` を使う。役は engine が `loop.py launch` で起こす（役の定義を読んで起こすので、あなたは役の名前を扱わない）。engine が起こせない役だけ、`agent_type` をそのまま Agent の `subagent_type` に渡す。モデル・道具は役の定義が正本で、この手順書にもグラフにも書かない。

## 手順

1. **始める**。何をレビューするか（PR 番号・ブランチ・一言）を依頼文として渡す:

   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/scripts/loop.py" init --loop review-loop --request "<何をレビューするか>"
   ```

   **人から直す依頼を持って来たなら**、最初の `next` の前に、下の「[判定から入る（人の修正依頼）](#判定から入る人の修正依頼)」の手順で依頼を `add` せよ——run が判定から入るのは 1 周目の P1 より前の `add` だけで、最初の `next` の前が確実である。

   返ってきた `dir`（盤面の置き場）を **以降の全部の呼び出しに `--dir <DIR>` で渡せ**。省くと engine は `current` から推測するが、同じリポジトリに別の run が在ると取り違えて拒む（別ループの run が並ぶと exit 2）。名指しが既定の導線である。

   検証器は同じリポジトリの `scripts/review-record.py` か、インストール済みの convergence-loops から engine が探す（見つからなければ `--validator <path>`）。**`--validator` で外のファイルを指すときは、隣に `record_common.py` も置け**——検証器 4 本が共有する土台を自分の隣から import するので、検証器 1 本だけ写すと `ModuleNotFoundError` で落ちる（実測 2026-09-15）。無人で走るなら `--unattended`。**N 周目で止める**なら `--stop-after-round N`——N 周目の締め（周の記録・検証器・収束の判定）まで済ませ、次の周を開かずに止まる（`status` が stopped、盤面と `status` の `halted` が `by: stop_after_round`。止めた後の `next` は節を出さず、報告も書かない）。並べた run を 1 周で止めて合流させるとき・プログラムが周の数を決めて回すときに使う。収束・人に聞く番（上限・前提不成立）はそれより先に来る。返ってきた `overview` を読め——ループ全体の形はここだけで渡す。

2. **回す**。`next` を呼び、返った `ready` を全部こなし、`done` で返す。`status` が converged か stopped になって `ready` が空になるまで繰り返す:

   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/scripts/loop.py" next --dir <DIR>
   ```

   `ready` の各要素は 1 つの節で、`mode` が 5 種類ある（cli・agent・agent_continue・engine_run・runner）。**役の節（runner 以外）は、`launch` を持っていれば engine が起こす**:

   - **`engine_run`（走らせるだけの節）** —— CI の再実行（`p0.local_checks`・`p4.ci`）と並行 PR の交差（`p0.parallel_pr`）。engine が語を走らせ、終了コードから返答を組んで受け付けまで済ませる。**これも `loop.py launch` で走らせ、役と同じく背景実行で立てて終了を待て**（一式は数分〜30 分かかる。期限は無い）。**`done` は拒まれる**——結果を回す側や任せ先が書く道を閉じてある（任せ先が写していた頃、走り切る前の件数で clean と書く・一部の系統を飛ばす・数値を写し違える、が 1 周目で止めた run の全部で出た。実測 2026-09-25）。何を走らせるかは対象リポジトリのルートの宣言 `.review-checks.json` の `suite` で、人の承認は要らない（任意の `mutation` の段——変異の実行器の呼び方の頭 `argv` と腕の一覧のパス `arms`——は engine は走らせず、変異を撃つ役のプロンプトに名指しとして貼る。書式の正本はプラグインの `engine/declared.py`）。engine は走らせる直前にルートの宣言を読み直し、instance の語と一致するときだけ走らせる（一致しない——emit の後に宣言が変わった——なら launch の `why` がそう言うので、`loop.py relaunch` で今の宣言から計画し直してから `launch`）。宣言の語は Claude Code の許可の仕組みを通らないので、**他人のリポジトリ・他人の PR を回すなら、宣言とそれが呼ぶスクリプトを先に読め**（守られなくなった物と残る物はプラグインの `engine/declared.py` の冒頭の注記）。宣言の書式が読めなければ engine は走らせずにその誤りを書く（P0 は人待ち、P4 は not_run）。宣言の最上位に engine の知らない段が在っても、知っている段は走らせる——P0 は走らせた結果を添えて人待ちにし（綴り違いを run の頭で捕まえる）、段の名前は報告の人向けの項目にも載る。宣言が無いリポジトリ・GitHub でない remote・並行 PR と交差した周は、`engine_fallback` に理由を付けた任せ先の節（runner）として出る——宣言の無いリポジトリの CI は engine が確かめていない自己申告として記録（`process.checks`）に残り、収束の前に人に諮られる。launch の `why` が『任せ先の節に回した』なら次は `next`。

   - **`launch` を持つ節（cli・agent・agent_continue と、任せ先の付いた runner）** —— **`loop.py launch` を呼べ**。engine が役を `claude -p` の子プロセスとして起こし（`--node` で 1 節だけ、省くと同じ波の `launch` を持つ節を全部並列に）、**子の終了を直接待ち**、返答を `out_path` に書き、受け付け（`done` の中身）まで済ませる。受け付けが返答の形を拒んだら、同じ会話（`--resume <会話の番号>`）に理由を渡して出し直させる（回数の上限は graph の `launch.resume_on_reject`）。**時間の上限は付けない**——役が終わるまで待つ（外した理由は [docs/graphloops-rearchitecture.md](../../docs/graphloops-rearchitecture.md#期限を外した)）。同じ役を続ける節（agent_continue）は、前の節の会話の番号（`session_id`）で再開する。起こし直しの回数と理由は盤面の instance の `attempt_log` に、1 起動ごとの要約（会話の番号・往復数・所要時間・費用・トークン・権限で拒まれた道具）は盤面の `trace.jsonl` に `op` が `role_run` の行で残る。
     ```bash
     python3 "${CLAUDE_PLUGIN_ROOT}/scripts/loop.py" launch --dir <DIR>
     ```
     `launch` は役が終わるまで戻らず、前景では Bash の上限（10 分）で切られるので、Bash の背景実行（run_in_background）に回す——**回したら手番を終えるな**。背景の出力のファイル（ハーネスが返す置き場。自分でリダイレクトしない）に `launch` の要約（`"launched"` の JSON）が出るまで、前景で 1 回 10 分未満の見に行くコマンドを繰り返せ（例: `for i in $(seq 1 54); do grep -q '"launched"' <出力のファイル> && break; sleep 10; done`）。完了の知らせは待たない——engine と役の間は子の終了を直接待つ形にしたが、回す側と `launch` の間の知らせは届かないことがある（実測 2026-09-25: 判定役は盤面で済んでいたのに、知らせを待った回す側が 25 分止まった）。先頭が `sleep` のコマンドは Bash が拒み、上限の無い `until` ループは背景に回ると止まらないので使わない。返るのは 1 件 1 行の要約（`ok`・`why`・`session_id`・続きを頼んだ回数・費用）だけで、**役の返答の本文はあなたの文脈に入らない**。`ok` の節は受け付け済みなので `done` は要らない——そのまま `next`。
     - **ok でなければ `why` を読め**: 拒否が上限まで続いた・子が落ちた、なら `loop.py relaunch --node <id> --reason <理由>` で起こし直してから `launch`。relaunch は新しい試行を書いてから前の試行の子（とその孫の木）を止める（書く前に前の試行の印を確かめ、確かめられなければ新しい試行を作らない）——役が戻らないまま止めたいときも、`launch` の背景プロセスでなく relaunch で止めよ（`launch` を止めると同じ波の兄弟の役まで止まる。受領を done した背景の任せ先だけは例外で、relaunch が拒むので下の「線を止めるとき」の手で止める）。`why` が『起こし直された古い試行』の行は次の手が要らない（止めたのが relaunch なら新しい試行の `launch` を待ち、人が `loop.py stop` で止めたなら次は `next`）。落ち方は行の `cause` に在る: `launch_auth` なら認証が足りていない、`launch_child_failed` なら認証は足りていて役の側、`launch_auth_unread` なら標準エラーから認証の段が読めなかった（`stderr` の `with-auth:` の行で確かめる）。作業ツリーの突合で止まった（investigator が作業ツリーを変えた等）なら、返答は `out_path` に在るので、戻してから `done --node <id>`（自分の変更なら `--accept-tree-change`）。包みを解けなかった回（『誤りで終わった』『result が無い』『標準出力が空』）と子が exit 0 以外で終わった回は、何が返ったかが盤面の `trace.jsonl` の `op` が `role_run` の行（`stdout_head`・`subtype`）に在る。包みでない出力を本文として読んだ回はその行の `envelope` が false で、会話の番号・費用などの要約が無く、拒まれても同じ会話に続きを頼まない。engine が起こせない節（`why` が『前置ではない』『旗が無い』『権限の形』『定義が読めない』『claude が無い』）は、迂回を組まず人に渡せ。
     - **自分の Bash から `claude` を起こすな**: 出力をファイルに落とす綴りは auto mode の分類器が『Auto-Mode Bypass』で止める（実測 2026-09-15）。止められても別の綴りを探すな。**Agent ツールで起こすな**——ハーネスが subagent に CLAUDE.md 階層と git status を注入する。CLAUDE.md は役の定義の `omitClaudeMd` で省けるが、git status は止められない（公式文書 code.claude.com/docs/en/sub-agents、2026-09-25 取得: 『Every other built-in and custom subagent loads both, unless its definition sets the omitClaudeMd field to skip the user, project, and local CLAUDE.md files.』『You can't change which subagents receive git status. Only Explore and Plan skip it.』）。役の返答の本文もあなたの文脈に入る。
     - **engine がどう起こすか**（何を起こすかは engine の柵 `launch_refusal` が argv から機械で縛る。graph の宣言は柵の根拠にしない）: 前置は認証だけを足す層（`scripts/with-auth.py`。**子は対話の claude の認証を継がない**——実測 2026-09-12: 『Failed to authenticate…』の 1 行・73 バイトが返った）。**道具ゼロの役**（`cold-reader` / `blind-judge`）は `--tools ""` と `--setting-sources ""` で起こす（実測 2026-09-12: Agent ツールで起こした道具ゼロの `cold-reader` が利用者の CLAUDE.md の 1 項目を逐語で引用した。`--setting-sources ""` を付けると消えた）。組織管理の CLAUDE.md だけは外せないので、完全な遮断とは名乗らない。**道具つきの役**（judge・inspector・investigator）も同じ綴りで起こす: 役の定義（`agents/<役>.md`）の本文を system prompt に足し、道具・モデル・effort を定義どおりに argv に並べ、権限を engine が道具から決めて明示する——先に許した物だけが通る `dontAsk` で、聞く先を持たない（`--permission-prompts none`）。コマンドを走らせる道具（Bash）を持つ役（investigator）には Bash を丸ごと許さず、読むだけのコマンドの前置（gh の issue・pr の list と view・pr diff・search・repo view と git remote get-url）だけを許す。書く gh・`gh api` は拒まれる。既にある計器（テスト一式・台本）は、OS の sandbox が使える環境（macOS、bwrap が名前空間を作れる Linux）では sandbox の中で動く——作業ツリー・`.git`・ほかの作業ツリー・盤面への書き込みと外への通信は OS が止め、gh は sandbox の外で上の前置だけが通る。sandbox を使えない環境では計器の実行は拒まれる（読むだけの形に落ちる。どちらの形かは instance の `launch.form`）。形と実測の正本は engine の `role_run.tooled_permission`、理由は graph の `launch.tooled.why`。子は盤面の `inputs.cwd`（レビュー対象の作業ツリー）で起こす。定義が道具の一覧を持たない役（comment-analyzer）・ファイルを書く道具を持つ役は engine が起こさない（下の「`launch` を持たない agent」）。道具つきの役にも **CLAUDE.md は読ませない**（`--setting-sources ""`）。理由は graph の `launch.tooled.why`: 役が見る物は graph の `reads` が宣言した物だけにする（観点の REVIEW.md は `reads` で渡している）／利用者の CLAUDE.md は回す側に向けた出力の作法で、JSON だけを返す契約とぶつかる（実測 2026-09-25）／利用者とプラグインのフックが子で発火しないので、読了の記録（`reads.jsonl`）が回す側の読みだけになる。材料は標準入力で渡るので、貼る上限に当たらない（2026-09-12 にこの環境——macOS・claude 2.1.269——で 748,883 バイトと 774,021 バイトの入力が欠けずに届いた。測定の記録は docs/loop-contract.md の T 節。リポジトリのルート基準で、プラグインとして入れた実体には無いので clone か GitHub で見る: https://github.com/raiki61/claude-plugins）。
   - **`launch` を持たない agent / agent_continue** —— 役の定義がこの環境に無い・定義が道具の一覧を持たない（`pr-review-toolkit:comment-analyzer`）・ファイルを書く道具を持つ・モデルか effort を名指ししない役と、Agent で起こした旧い盤面の続き。engine は起こさないので、`subagent_type` に `agent_type` を渡して Agent ツールで**直接**起こし（`deliver` が `path` なら「`<prompt_file>` を Read し、その指示にそのまま従え。返答は指示どおりの JSON だけ」の 1 文、`paste` なら本文をそのまま貼る。**本文に足すな・削るな・言い換えるな**）、返答を `out_path` に書いて `done --node <id> --agent-id <役の id>`。agent_continue なら `agent_id` に SendMessage で続ける。このときだけ役の返答があなたの文脈に入る。
   - **runner** —— あなたの仕事。**`delegate` が付いた節は自分でやるな**——その節は `launch` を持ち、engine が任せ先を `claude -p` の子として **OS の sandbox の中で**起こす（`loop.py launch`。役の節と同じく背景で立て、プロセスの終了を待つ）。コマンドの出力や読んだ本文があなたの文脈に入らず、周を回す文脈が長持ちする（`delegate.why` が任せてよい理由）。**Agent ツールで起こすな**——Agent の子はあなたの作業ディレクトリと権限をそのまま継ぎ、1 回ごとに sandbox を掛ける口が無い（公式の sandboxing 文書: subagent は親と同じ sandbox の設定を使う）。配布先で、指示書に「作業ツリーのファイルを変えるな」と書いた任せ先が本物の作業ツリーで `git checkout` と `git reset --hard` を打ち、回す側の未コミットの修正を消した（2026-09-25）。engine が起こす任せ先は、作業ディレクトリが本物の写し（作業ツリーの今の姿。`.gitignore` の対象は無い）で、sandbox が本物の作業ツリー・gitdir の実体・共通の `.git`・他の作業ツリー・盤面・利用者の git とシェルの設定・engine 自身への書き込みを拒む。ファイルを書く道具は持たず、sandbox の外に落ちた Bash は聞く先が無く拒まれる。返答は engine が `out_path` に書き、受け付けまで済ませる。**`delegate.background` が真の節は待つな**——プロンプトが名指す受領をすぐ `out_path` に書いて `done` し、その後で `loop.py launch --node <id>` を背景で立てよ（engine は任せ先の返答を受け付けに回さず、graph の `delegate.result_to` が名指す置き場——盤面の `lanes/`——に置く。期限で止めない）。その節の結果は engine の instance を通らず、書き終えた後の周の機械の節が読む（このループでは変異の検算とテストの書き足しの線 `p3.delta_gates`。周の締めも次の周もこの線を待たない。線の中で閉じなかった見逃しは次の周の判定に、足したテストは修正の前に作業ツリーへ重なる）。任せ先が落ちても周は止まらない——収束を言う前の最後の関門（`p4.final_gates`）が最終のコードで撃ち直す。**線を止めるとき**は、背景の任せ先を止めてから、止めたことを盤面の線の台帳に書け。止める先は、その線を起こした `loop.py launch --node <id>` のプロセスで、止める信号（SIGTERM・SIGINT・SIGHUP）を受けると engine が子を木ごと止めてから抜ける。周ごとの線はどれも同じコマンド行で立つので、コマンド行で探さず、線の版から辿れ——台帳のその版の結果の置き場（`result`）の名前に `.tmp.pgid` を足したファイルが、生きている子のグループの番号（`pgid`）の印で、その番号のプロセスの親が止める先である（印が無ければ子はまだ起きていないか、もう終わっている）。`loop.py stop` と `loop.py relaunch` は背景の線を止めない（stop が止めるのは待っている試行だけで、relaunch は受領を done した節を拒む。線は run の止めから独立させてある）。台帳への書き方: `loop.py patch --path state.loop.lanes.<版>.state` に `"abandoned"`、`--path state.loop.lanes.<版>.why` に理由（どちらも `--reason` に同じ理由。行を丸ごと書き換えると他の欄が消え、その行は読めない行として判定に渡る）。止めた線は後から結果が届いても重ねず、判定へも渡さず、記録の `process.lanes` に `abandoned` と理由で残る（時間で止める形は無い）。止めた線を同じ周に起こし直すな——置き場は版ごとに 1 つで、2 人目の書き手になる（最終の版は最後の関門が BASE から撃ち直す）。**柵の中でできない仕事**（docker を使う・sandbox の立たない場——Windows のネイティブ・bubblewrap の無い Linux。sandbox が立たなければ子は起動時に落ち、`launch` の `why` に出る）が要るなら、迂回を組まず人に渡せ。人が run ごとに明示したときだけ `init --unfenced-delegates "<理由>"` で柵を外せる——そのときだけ任せ先の instance は `launch` の代わりに `unfenced`（外した時刻と理由）を持ち、あなたが `delegate.model` の汎用 agent を Agent ツールで立てて「`<prompt_file>` を Read し、その指示どおりにやれ。返答を `<out_path>` に書き、私には wrote とだけ返せ」の 1 文で渡し、終わったら `done --node <id>`（背景の節は Agent の背景実行で立てて待たずに受領を done）。外した事実は盤面の state と trace と `next` の `notes` に毎回出る。任せ先の節が `launch` も `unfenced` も持たない（graph に `launch.delegate` が無い）なら、柵を組めない——Agent で起こさず人に渡せ。`delegate` の無い runner の節（基準点・目的・前提・修正・報告）は、あなたの判断そのものなので自分でやる。`prompt_file` の指示に従って自分でやり、返答の JSON（`report` と `report.human_items` は本文そのもの）を `out_path` に保存する。`skills` があればその skill を**あなたが**呼ぶ（局所レビュー）——任せ先に skill ごと任せるな（skill は中でさらに役を背景で起こすので、孫の完了の知らせが任せ先に届かず待ち続ける。graph は skills を持つ節に delegate を書けない）。柵を外した run で `background` でない任せ先を Agent ツールで起こすときは**前景で**起こせ——その呼び出しの返りが任せ先の終了で、背景の完了の知らせ（入れ子や上限落ちで消える）に頼らない。任せ先が書かずに返った・落ちたら `loop.py relaunch --node <id> --reason <理由>` で新しい置き場を作って起こし直す（engine は Agent で起こした前の試行を止められないので、前の試行が残っていれば止めてから）。記録や役の返答は本文でなく置き場のパスと 1 行の要約で渡される——要る所だけ Read で読む。

   同じ `ready` に載った節は互いに依存が無い。`launch` を持つ節は 1 回の `launch` でまとめて並列に起こる。runner の節（と `launch` を持たない agent の節）は、返答を保存したら:

   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/scripts/loop.py" done --node "<id>" --output <返答のファイル> [--agent-id <id>] --dir <DIR>
   ```

   `done` が exit 1 で拒んだら理由を読んで直す。役の節なら、理由を添えて**同じ役に返させろ**（`launch` で起こした節は engine が同じ会話に出し直させる。上限まで拒まれたら `relaunch` で起こし直す）——あなたが JSON を補ったり判定を書き換えたりしてはいけない。runner の節なら自分の返答を直す。`ready` が空で `status` が running なら、もう一度 `next`（機械の節——作業ツリー突合・素材の穴埋め・再発火の計算・周の記録・検証器——が進んで次の波が出る）。機械の節が「作業ツリーが変わっている」と言ったら、戻してから `next`——自分の変更（engine をその場で直した等）なら `next --accept-tree-change "<理由>"` で痕跡付きで通す（stash で退避しても stash の一覧が突合に入るので通らない）。

3. **人に聞く番**。`next` が `awaiting_human` を返したら、`ask` の中身（問いの台帳で保留のもの）を依頼者に見せて答えをもらい、返す。答えの本文は `--note` に入れる（次の周の judge の再審に渡る）:

   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/scripts/loop.py" answer --text continue --note "<答え>" --dir <DIR>
   python3 "${CLAUDE_PLUGIN_ROOT}/scripts/loop.py" answer --text stop --dir <DIR>
   ```

   **聞き方**: 質問の道具（選択肢を並べて選ばせる型）を使うな。依頼者はループの間ずっと別の作業をしていて、答える時点で文脈を持っていない。選択肢だけ並んだ問いは初見では決められない。散文で、次を冒頭にまとめて出せ: ①何のループが・何を調べていて・どこで止まったか ②なぜ止まったか（きっかけの実物——どの問いが・何周目に・何から立ったか）③答えの候補ごとに何が起きるか ④あなたの推奨と根拠（`escalate` は judge が「人でないと決められない」と確定したものなので推奨を書くな。書いてよいのは台帳の `options` と `reason` だけ）。内部の語彙（節の名前・安定キー・stuck 等の種別名）は使うなら初出で中身から言え。答えは自由な文で受け、`answer` の語に写すのはあなたの仕事である。

   **周の途中の関所**（人の決定権の関所）: 今ある能力を減らす・狭める変更と、人の方針（下の「人の方針」）とぶつかる変更は、役が代償として決めない。修正の前（`p2.human_gate`）は修正案が自分で書いた狭め（`narrows`）と事前審査の後退（regression）・方針（policy）の穴を、修正の後（`r4.human_gate`）は R4 が BASE から消えたと見た能力と人の方針とのぶつかり（`policy_conflicts`。どちらも前に人が通した同じ文の行は除く）を、どちらも方針の文書が固定した版から変わっていればそれも（前後の写しと差分の置き場を添えて）、`next` が `awaiting_human`（`ask.in_round` が真）で返す。答え方は仕様の道の承認と同じ——`answer --text continue --note "<通す範囲と条件>"` は同じ周のまま先へ進み（答えは記録の `process.human_items` に残り、同じ周の修正役のプロンプトに届く。方針の文書の変更を通すとその版を固定し直す）、`answer --text stop` は run をその場で止める。無人（`--unattended`）ではここで止まる。**直す義務の単位をこの周の修正から外す**なら、修正の前の関所（`p2.human_gate`）への continue に `--detail <JSON のファイル>` を添える（`{"exclude": [{"unit": <番号か key>, "why": <理由>}]}`。番号は関所の問いが並べた番号）——外した単位と理由は記録の `process.human_items` に残り、修正役は直さずに `not_done` に書き、次の周の判定役（`p2.history`）が理由を見て振り分ける。note の自由文からは外さない。関所は後退・方針の穴か方針の文書の変化が在る周にだけ立つので、立たない周に単位を外したいなら、次の周の判定の前に `add` で依頼し、判定役に決めさせる。修正差分の審査は後退・方針の語を使えない（削除は今の姿に引く字列が無く、手直しの義務に入ると人より先に修正役が決めるため）——修正の後の後退と方針とのぶつかりは R4 が受ける。

   **人が途中で止める**（人に聞いていない時点でも）: 依頼者が「止めて」と言ったら、理由を添えて止める——止めた事実と理由は盤面の `stop` と記録の `process.halted` に残り、次の `next` は graph が宣言する後始末の節（最上位の `stop.node` の下流＝報告の節）だけを出す。止めた周に走らなかった節は止めた印（`process.stopped_nodes`。省いた機構 `process.skipped` とは別）になり、engine が起こし中の役の子は木ごと止まる（Agent・任せ先で起こした試行は engine が持たないので、出力が名指しした物を回す側が止める）。今の止め方（人に聞いている番の `answer --text stop`・init の `--stop-after-round N`・`next` を打たずに置いて盤面から再開する）はそのまま使える。init の版の graph に `stop` の宣言が無い run は、報告の節を出さずに止まる（`halted` の `by: stop`。記録の検証は `loop.py finalize`）:

   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/scripts/loop.py" stop --reason "<依頼者の止める理由>" --dir <DIR>
   ```

4. **終わり**。最後の節 `report` の前に engine が記録を仕上げて検証器を回す。`report` の本文は盤面の置き場の `report.md` に保存される。それを依頼者の言語でそのまま出せ。ループが途中で終わったら、基準点の節で `git add -N` したパスを `git reset -- <path>` で戻せ（この手順が index を変える唯一の書き込み）。

## 判定から入る（人の修正依頼）

人が「これを直して」と頼むときの入口。依頼を判定（`p2.diagnose`）へ流すので、判定役の反証・零処方からの列挙・先行例、修正案の事前審査、修正差分の審査と変異の検算が依頼にもそのまま当たる。P1（素材集め）の役は起こさない——P1 は 1 周の費用の大半で、依頼 1 件のために既存のコードへ回す物ではない。

**使い分け**（人の決定 2026-09-25）: 直す依頼は、できるだけ判定から入れる。ループを回さず直接直すのは、誤字・コメント・文言の直しだけである。とくに機構の新設・共有面の拡大（複数の消費者が使う仕組み・engine・共通設定）に及ぶ直しは、[REVIEW.md](../../REVIEW.md)「処方の最小性」が修正でなく設計作業とし、零処方からの列挙なしに実装することを禁じている。

1. 依頼を、判定役が読む findings の型の JSON 配列で書く。欄は `where`・`text`（必須）と `mechanism`・`measured`・`false_positive_if`（任意）だけで、ほかの欄は拒まれる:

   ```json
   [{"where": "graphloops/engine/commands.py: cmd_skip", "text": "…が無い", "mechanism": "…だから", "measured": "2026-09-25: …で見た", "false_positive_if": "…なら誤り"}]
   ```

2. `init` の直後、最初の `next` より前に、依頼を置く。`--reason` は出どころ（誰の・どこからの依頼か）で、依頼は記録の `process.request_findings` に周（`round`）と出どころ（`origin`）つきのバッチとして積まれる:

   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/scripts/loop.py" add --file <依頼.json> --reason "<出どころ>" --dir <DIR>
   ```

   この位置（1 周目の P1 より前）の最初の `add` だけが、run を「判定から入る run」にする（入口の印 `process.request_entry` が立ち、戻らない）。BASE は作業ツリーと同じ commit でよい——依頼は既存のコードに向くので差分が空なのが普通で、入口の run は空の差分で止まらない。

3. あとは上の手順 2 と同じに回す。判定のプロンプトには依頼が依頼の入口のバッチ（出どころ `origin` つき）として役の観察と分けて載り、飛ばした P1 の素材は「判定から入る run のため、P1 の役を起こしていない」の理由つきで条件外（not_applicable）になる。

**途中の周で依頼や観点を足す**: `add` は、その周の判定役（`p2.diagnose`）が起きる前なら、どの周でも何度でも受ける（入口の run でも通常の run でも）。`next` が判定役の節を出していても、起こす前（`launch` していない・返答の置き場が空）なら受け、積んだ依頼を読む節のうち起きていない物を engine が新しい試行として描き直す（`add` の返りが描き直した `prompt_file` と `out_path` を言う。engine が起こさない節は、前の試行を起こしていたら止めてから新しい `prompt_file` で起こせ）。依頼は `add` で積め——`loop.py patch` で積んだ依頼は描き直されず、出たまま起こしていない判定役のプロンプトに入らない。積んだ依頼はその周の判定役にだけ届き、次の周の頭で `process.request_history` に移る（前の周の依頼の扱いは、単位と台帳を通して履歴の突合が運ぶ）。途中の周の `add` は P1 を外さない——P1 を外すのは、上の手順 2 の位置で始めた run だけである。判定役が起きた後（起こした・返答が在る・済んだ）の `add` は拒まれる: 次の周が来るならその判定の前に足し、来ない（収束した・終わった）なら、新しい run を判定から始めよ。

**代償**: 依頼の外を見る目（衛生・手順トレース・外部標準・ゲートの検算など）はその周に無い。依頼の周りの別の欠陥を拾えるのは判定役と修正前後の審査だけである。入口が効くのは修正が入るまでで、修正が 1 ファイルでも入った次の周からは、通常の run と同じく P1 が修正差分を見る（修正が 0 行のまま周が進めば、次の周も P1 は外れたままで、1 周目の依頼もその周の判定役に届き続ける。判定が依頼を全部却下すれば、P1 を起こさないまま収束して報告まで届く）。報告の冒頭には判定から入った run であることと、どの周に何件の依頼が積まれたかが載る。`loop.py patch` は手当ての口として、依頼の欄（`process.request_findings`）も入口の印（`process.request_entry`）も書ける（痕跡は `state.patches` に残る）。型の検査は add と rules の読む口（依頼の一覧は移し替え・素材の理由の件数・次の add、印は入口の判定）にだけ在る——依頼の一覧は型が崩れていれば移し替えにも件数にも使わず次の add も拒み、印は型が崩れていれば入口にならない。判定のプロンプトは欄をそのまま載せるので、patch で依頼を置くなら add と同じ型（`[{round, origin, findings}]`）にせよ。

## 変異の検算を合流でまとめる（選んだときだけ）

並べた run を後で 1 つの版に合流させるとき、各 run が自分で変異の検算を撃つと、合流した版での撃ち直しと負荷を食い合う（実測 2026-09-25: 4 本が各自撃って負荷 99）。選ぶのは `init` の指定 1 か所だけで、既定（指定しない run）は今のまま撃つ:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/loop.py" init --loop review-loop --request "<依頼>" --input gates=merge
```

`gates` に `merge` 以外の値を渡すと init が盤面を作る前に拒む（選べる値は graph の `inputs` の宣言。`flow` も同じ）。graph の `inputs` に宣言の無い鍵（`gating=merge` のような綴り）は拒まずに受け付けるが、どの節も読まず効かない——init が stderr と返りの `notes`、盤面の `notes` に「効かない」と出し、報告の人向けの項目にも載るので、綴りを確かめよ（rules が埋める入力——graph の `inputs` の `by: rules` で `input: true` の無い鍵——を渡したときも同じ）。選んだ run では、P1 のゲートの検算（`p1.gate_efficacy`。差分がゲートに触れた周に同じ実行器を撃つ）と、変異の検算の並行の線（`p3.delta_gates`）と最後の関門（`p4.final_gates`）が理由つきの条件外（na）で閉じ、線は立たない（盤面の線の台帳に載らない）。P1 の検算の素材は、ゲートに触れた差分でも合流でまとめる理由と残る義務を書いた not_applicable になる（昇格した周でも撃たない）。関門は消えていない——検証器が阻害なしで CI が緑の周に来ても収束を名乗らず、`converge` が `stopped`（記録の `process.stop_reason` が `gates_deferred`）で止まる。**残る義務**: 合流した版を `gates=merge` 無しの run で回し、そこで最後の関門を撃つ（差分がゲートに触れていれば P1 のゲートの検算も撃つ）。収束と言えるのはその run だけである。TDD の流れ（下）と一緒に選ぶと、線が立たないので周ごとの効き目の `lane_missed` は埋まらない（撃っていない）。

## 人の方針

人が決めた、どの run にも効く決まり（例: 今ある能力を減らさない・期限を足さない）は、依頼文に毎回書き写さず、1 つの文書に置く。既定の置き場は対象リポジトリの共有の git ディレクトリ（`git rev-parse --git-common-dir` が指す所。worktree からも本体の `.git`）の下の `graphloops/policy.md` で、在れば `init` が拾う。別の文書を使うなら `init --input policy_md=<パス>`（無いファイルを名指しすると init が止まる）。置き場の決め方の正本は `rules/policy_input.py`。

- **作業ツリーの外に置く理由**: 採点する版・差分・作業ツリーの突合に入らず、run の途中に人が書き足しても P1 の撃ち直しにならない。同じリポジトリの worktree の run は全部同じ文書を読む。リポジトリの中の決定記録（先行議論の突合 `p0.prior_decisions` が洗う物）とは別物——方針は run をまたいで効く人の決まりで、決定記録はリポジトリの中の個々の論点の決着
- **届く先**: 役の節には、節を出す時点の本文が貼られる（run の途中の人の書き足しも後の節に届く）——判定（`p2.diagnose`・`p2.history`・再判定）・審査（`p2.plan_review`・`p3.delta_review`・`p3.delta_review2`）・R1・R2 の設計・R3・R4。回す側の節には置き場が渡る（在れば先に全部読む）——修正案（`p2.fix_plan`）・修正（`p3.fix`）・手直し（`p3.delta_fix`・`p3.delta_fix2`）。段落の正本は `prompts/policy-paste.md`（本文を貼る）・`prompts/policy-path.md`（置き場を渡す）・`prompts/policy.md`（規則）で、graph の `prompt_append` が各節に足す。research-graph の判定と適用の節にも同じ段落が届く
- **書き換え**: 方針は人が書く。init の時点の版を `record.process.policy` に固定し（sha と写しの置き場）、変わっていれば上の関所で人に聞く（通せば新しい版を固定し、履歴は `amendments`）。最後の関所の後に変わったまま終わった run は、記録の `process.policy_change` と報告に出る
- **中身は engine と graph に書かない**: 比べる元（init と関所で固定した版）の写しは盤面の `policy/` に sha256 の名前で置き、変化を見つけたら差分のファイルも同じ置き場に置く。記録と関所の行には置き場だけを載せる（本文を載せると、人の答えの台帳を通って回す側の節に貼られる）

## TDD の流れで回す（選んだときだけ）

修正（P3）を 2 段に割る版。既定は今の流れで、選ぶのは run の始めの 1 か所だけ——`init` の `--loop review-loop-tdd` と、テスト一式を走らせる実行ファイルを渡す `--input tdd_suite=<パス>`:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/loop.py" init --loop review-loop-tdd --input tdd_suite=<実行ファイル> --request "<何をレビューするか>"
```

`tdd_suite` は、JUnit XML の書き先を第 1 引数に受けてテスト一式を走らせる実行ファイル（例: テストの実行器に JUnit XML の書き先として `$1` を渡す 1 行のシェルスクリプト。`.py` なら engine の Python で走る）。engine はリポジトリのルートで走らせ、書かれた XML をテスト 1 件ごとに読む。無ければ init が盤面を作る前に止まる。JUnit を出さないテスト（このリポジトリなら bash の台本）で確かめる単位は、名指しできないので direct に回る。

流れ（graph は `graphs/review-loop-tdd.json`。今の `graphs/review-loop.json` の差分だけを持つ）:

1. **元の結末を取る**（`p3.tdd_start`、機械）——テストを書く前の版を固め、一式を 1 回走らせる。元から落ちているテストは以降の確かめで問わない（記録に残る）。
2. **テストだけを書く**（`p3.tdd_tests`、あなたの仕事）——直す単位ごとに、使う側の呼び口で今は落ちるテストを書いて名指しする。書きにくさ（準備が重い・内部に手を入れる・名前から意図が読めない）を単位ごとに記録し、呼び口・名前を直すならテストの側で先に決める。件数の定数もこの段で合わせる。先にテストを書けない単位は理由をつけて今の修正の流れ（direct）に回す。
3. **赤の確認**（`p3.tdd_red`、機械）——名指しのテストが全部 failure で落ち、元の結末で通っていたテストは通ることを確かめる。読み込み・準備の失敗（error）・一式に居ない・もう通る・飛ばされた、は失格。テストのファイルの外に触れていても失格。通らなければ 2 に差し戻る。
4. **実装**（`p3.fix`、あなたの仕事）——今の修正の指示書の後ろに TDD の段落が足され、2 の返答と 3 の結果がそこに貼られる（engine が会話を続けるのではない）。名指しのテストを通す。テストのファイルは書き換えない（テストが誤りなら `rejudge_requested` へ）。
5. **緑の確認**（`p3.tdd_green`、機械）——名指しのテストと元の結末で通っていたテストが全部通り（元の一式が 0 で終わっていたなら一式も 0 で終わる）、テストのファイルが赤の確認の版から変わっていないことを確かめる。通らなければ 4 に差し戻る。

赤・緑の確認は同じ周に 3 回通らなければ TDD を諦めて今の流れで進み（止まらない）、理由は記録と次の周の判定役に渡る。修正差分の審査（`p3.delta_review`）には書きにくさの記録が渡る。効き目は `record.process.tdd.rounds.<周>` に残る（元から赤いテスト・振り分け・赤緑の結果・その周の修正差分への変異の見逃しの本数 `lane_missed`・その周の修正が作った指摘の件数 `faces_created_by_this_fix`。後の 2 つは並行の線と次の周の記録から後で埋まる）。

## 仕様から入る（選んだときだけ）

新しい仕組みを作る依頼で、**何が成り立てば完成かを案より前に固める**入口。既定（下の指定をしない run）は今の流れのままで、何も変わらない。選ぶのは `init` の指定 1 か所だけ:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/loop.py" init --loop review-loop --request "<依頼>" --input flow=spec
```

`flow` に `spec` 以外の値を渡すと init が拒む。判定から入る run（上の節）と一緒に使ってよい（init の直後に `add` する）。

1. **仕様を書く**（`spec.write`。あなたの runner の節）: 要件を 1 件ずつ書き、要件ごとに受け入れ条件を**実行できるテストとして対象リポジトリに書く**（Given/When/Then をテストの中に書く。CI が走らせる場所に置く）。返答は要件と、テストの置き場（`file`・`name`）と走らせるコマンド（`run`）だけ——本文を返答に写すな。修正の前なので、テストは赤になるのが正しい。
2. **仕様の審査**（`spec.review`。engine が judge を起こす）: 抜けている条件・曖昧さ・範囲の外を挙げる。穴があれば **仕様を直す**（`spec.revise`。runner）で key ごとに absorbed / declared と答え、直した仕様の全体を返す。
3. **人の承認**（`spec.approve`）: engine が各テストの `run` のコマンドの字面を添えて（承認の前には走らせない——writer が書いたコマンドを、人が見る前に engine の中で走らせない）、`next` が `awaiting_human` を返す（`ask.in_round` が真）。上の「人に聞く番」と同じ作法で依頼者に見せ、`answer --text continue --note "<承認の言葉>"` か `answer --text stop` を返す。**continue は周を進めない**——同じ周のまま P1 へ進む。**stop は run をその場で止め**（`next` が `halted` を返す）、報告も書かない。仕様を直すなら新しい run で始めよ。無人（`--unattended`）ではここで止まる。
4. 承認した仕様は `record.process.spec` に固定され（テストの置き場・sha・承認の直後に各 `run` を走らせた終了コード）、受け入れ条件は 1 周目の判定に依頼の入口のバッチ（出どころ『仕様（人が承認した受け入れ条件…）』。1 件ごとの本文の頭にも出どころ）として 1 度だけ届く。赤から緑にするのは修正で、2 周目以降に受け入れ条件の緑を engine が確かめる節は無い（判定役が依頼として読む。緑を収束の条件にするかは、選べる流れの選び方の決着で決める）。
5. **承認の後にテストを変えたら**、その周の修正の後に `spec.check` が人に諮り直す（`in_round` の問い）。continue なら新しい sha を固定し、変更の履歴を `process.spec.amendments` に残す。

## 合流の線引き（run の成果を重ねるとき）

複数の run の枝を 1 本に重ねるときの決まり（決定の正本は [設計の文書](../../docs/graphloops-rearchitecture.md#7b-運用の決定2026-09-25人) の 7b・7c）:

- **後から追いつかせる変更は並行の線に置く**——テストの書き足しと変異の検算は、ほかの作業を待たせずに線で回し、合流した版の最後の関門（`p4.final_gates`）で合わせる。
- **振る舞いを変える変更は次の工程の前に合流させる**——後の run の判定と修正が、重ねた後の振る舞いを見るように。
- **重ねるために振る舞いを変えたら、判定に流す**——重ねる担当が自分で解いてよいのは、文の衝突・件数の定数・両側の意図がそのまま両立する重ね方だけ。意味を変えた箇所は理由を添えて次の run（判定から入る run か合流の run）の依頼にする。両側の意図がぶつかってどちらかを捨てるなら、重ねずに止めて人に見せる。
- 並行の線が見つけた、テストでは閉じない見逃し（コードの欠陥の疑い）は、次の周の判定に、人の依頼と同じ入口（`process.request_findings`。出どころ `origin` は線で、1 件ごとの本文の頭にも人の依頼でないと書く）で届く。テストを書けなかった見逃し・使えない結果・当たらない patch は、前の周の宣言の穴として 1 件ずつ振り分けられる。

## 守ること

- **run の途中でプラグインの版を上げても、走っている run の graph は init の時の版のまま**: 盤面は init の時の graph を、その置き場（インストールされた版のディレクトリ）の絶対パスで持ち、graph・指示書・rules・検証器をそこから読み続ける。置き場のファイルそのものが書き換わる形（`--plugin-dir` などでその場から読み込んだプラグイン）では graph も変わり、変わった周は `next` の `notes` と `process.graph_changes` に出る。engine（`loop.py`）は今インストールされている版で動き、役の定義（convergence-loops の `agents/<役>.md` の道具・モデル・effort・system prompt に足す本文）は節を描くたび（`next` が節を出すとき）に今見つかる版から読む——どの engine が周を回したかは、替わった周の `next` の `notes` に出る。新しい版の graph や指示書の動きが要るなら、走っている run を仕上げてから新しい run を始めよ。盤面を別の版の graph へ付け替える手順は用意していない（`loop.py patch` で state を書き換えれば変わるが、それは手当ての口で、この用途には案内しない）。更新で置き換わった古い版のディレクトリは後で掃除されることがあり（公式の plugins の読み込みの文書『Cleanup of previous versions』）、消えるとその run は開けなくなる。古い版の graph が役を `--output-format text` で起こしても、engine は包みでない標準出力を本文として読むので、返答は受け付けまで届く。
- 周の記録（`rounds/round-<N>.json`）を直接編集しない。判定の欄は役の返答から engine だけが書く。手当ては `loop.py patch`（痕跡が残る最終手段）: `--path` は記録の欄（`record.` を付けても付けなくても同じ所）か `state.<盤面の欄>`、`--file <json>` で書くか `--delete` で在る鍵を消す（無い鍵は拒む。綴りを誤って書いた鍵も消せる）。
- 済んだ節に `done` し直さない（同じ周で採点役を回し直して有利な判定を採らない。やり直しは次の周）。
- 探す役に「ここは見るな」の線を引かない（プロンプトを書き換えない）。削るのは judge の仕事である。
- 会話が圧縮されて場所を見失ったら `loop.py status --dir <DIR>` → `loop.py next --dir <DIR>`。盤面はディスクにある。
- 数える問い（判定者の `class_query`・修正の `coverage` の `how`）は engine が数える——判定者の件数は周に固定した版で、修正の前後は p3.fix の done で。回す側が数える口は置いていない（置いていた数えるサブコマンドは、engine の数え方と揃わない入口として 4 回繕われ、使う側が無かったので消した）。
- **Web を読む調べ（先行例・一次情報の確かめ）は自分でやるな**——読み役（`convergence-loops:investigator`）を起こして任せ、返った結論と出典だけを受け取れ。ページの本文があなたの文脈に入ると、周を回す文脈が先に尽きる。外へ送る検索語に対象の名前を載せない規律は、役の定義（convergence-loops の `agents/investigator.md` と `agents/judge.md`）が持つ。
- 盤面の置き場は `git rev-parse --git-dir` の下（作業ツリーの外）。investigator の前後と P1 の前後で engine が作業ツリーを突き合わせる。自分の変更なら `--accept-tree-change "<理由>"` で痕跡付きで通す——investigator の instance の突合で止まったなら `done` に、P1 後の機械の節で止まったなら `next` に付ける（そのとき pending の instance は無いので `done` では通せない）。
- 報告は依頼者の言語で書く。この手順書が日本語なのは理由にならない。
