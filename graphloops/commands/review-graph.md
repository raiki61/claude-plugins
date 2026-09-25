---
description: コード変更後の自動レビュー・修正サイクルのグラフ実行版。実装完了時、リファクタリング後、バグ修正後に使用する。回す手順は機械（engine）が持ち、この手順書は engine の呼び方だけを書く。
allowed-tools: Bash, Agent, Skill, Read, Write, Edit, Grep, Glob
---

## これは何か

コード変更を、採点する目（別の会話で動く役割 agent）と直す手（あなた）を分けて、指摘が出なくなるまで回すレビューループである。このプラグイン graphloops は、同じマーケットプレイスの姉妹プラグイン convergence-loops が配る散文の手順書 `/review-loop` を、機械が読めるグラフに写したもので、目的も、周ごとの記録の形（`round-<N>.json` をディレクトリに積み、検証器 `review-record.py` がディレクトリごと読んで阻害要因を列挙する）も同じである。違いは手順の置き場だけ:

- **グラフ**（このプラグインの `graphs/review-loop.json`）—— 工程（節）・依存・役・各節のプロンプトと返答の型
- **engine**（このプラグインの `scripts/loop.py`）—— グラフを読んで盤面を持つ機械。どの節が終わったか・同時に走らせてよい組・各節に渡してよいもの（グラフの `reads` の宣言に無いものはプロンプトに貼らない）・作業ツリーの前後突合・走らせなかった素材の欄・R1/R2 の再発火・周の記録の組み立て・検証器の 3 分岐の読み取り・周の上限
- **rules**（このプラグインの `rules/review-loop.py`）—— グラフに書けない算術。記録の欄と語彙は検証器の定数を写さず import する

この手順書は、あなたが engine をどう呼ぶかだけを書く。`${CLAUDE_PLUGIN_ROOT}` は Claude Code がこのプラグインの置き場に展開する変数である。

このループを回す session が **writer（実装者）**で、それはあなたである。あなたがするのは、基準点・目的・前提の固定、局所レビューの skill の実行、機械が返す節の起動、修正必須の指摘（[block]）と今直すと判定された提案（do-now）の修正と閉鎖の実証、CI と規模指標の取得、最終報告の執筆。**ラベル確定・根本診断・収束判定はしない。** 判定は役割 agent が返し、engine がそれを記録に写す。異議があるなら自分で覆さず、次の周の新しい judge に再判定させる。

役割 agent は convergence-loops に同梱の役の定義（`convergence-loops:judge` のように接頭辞付きで指す）と、依存で入る `pr-review-toolkit:comment-analyzer` を使う。役は engine が `loop.py launch` で起こす（役の定義を読んで起こすので、あなたは役の名前を扱わない）。engine が起こせない役だけ、`agent_type` をそのまま Agent の `subagent_type` に渡す。モデル・道具は役の定義が正本で、この手順書にもグラフにも書かない。

## 手順

1. **始める**。何をレビューするか（PR 番号・ブランチ・一言）を依頼文として渡す:

   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/scripts/loop.py" init --loop review-loop --request "<何をレビューするか>"
   ```

   返ってきた `dir`（盤面の置き場）を **以降の全部の呼び出しに `--dir <DIR>` で渡せ**。省くと engine は `current` から推測するが、同じリポジトリに別の run が在ると取り違えて拒む（別ループの run が並ぶと exit 2）。名指しが既定の導線である。

   検証器は同じリポジトリの `scripts/review-record.py` か、インストール済みの convergence-loops から engine が探す（見つからなければ `--validator <path>`）。**`--validator` で外のファイルを指すときは、隣に `record_common.py` も置け**——検証器 4 本が共有する土台を自分の隣から import するので、検証器 1 本だけ写すと `ModuleNotFoundError` で落ちる（実測 2026-09-15）。無人で走るなら `--unattended`。返ってきた `overview` を読め——ループ全体の形はここだけで渡す。

2. **回す**。`next` を呼び、返った `ready` を全部こなし、`done` で返す。`status` が converged か stopped になって `ready` が空になるまで繰り返す:

   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/scripts/loop.py" next --dir <DIR>
   ```

   `ready` の各要素は 1 つの節で、`mode` が 4 種類ある（cli・agent・agent_continue・runner）。**役の節（runner 以外）は、`launch` を持っていれば engine が起こす**:

   - **`launch` を持つ節（cli・agent・agent_continue）** —— **`loop.py launch` を呼べ**。engine が役を `claude -p` の子プロセスとして起こし（`--node` で 1 節だけ、省くと同じ波の `launch` を持つ節を全部並列に）、**子の終了を直接待ち**、返答を `out_path` に書き、受け付け（`done` の中身）まで済ませる。受け付けが返答の形を拒んだら、同じ会話（`--resume <会話の番号>`）に理由を渡して出し直させる（回数の上限は graph の `launch.resume_on_reject`）。期限（`deadline_at`。graph の `deadline_minutes` の幅を起こした時刻から取り直す）を過ぎたら子を木ごと止める。同じ役を続ける節（agent_continue）は、前の節の会話の番号（`session_id`）で再開する。起こし直しの回数と理由は盤面の instance の `attempt_log` に、1 起動ごとの要約（会話の番号・往復数・所要時間・費用・トークン・権限で拒まれた道具）は盤面の `trace.jsonl` に `op` が `role_run` の行で残る。
     ```bash
     python3 "${CLAUDE_PLUGIN_ROOT}/scripts/loop.py" launch --dir <DIR>
     ```
     **Bash の背景実行（run_in_background）で立て、プロセスの終了の知らせを待て**——`launch` は期限（30〜120 分）まで戻らないことがあり、前景では Bash の上限で切られる。プロセスの終了はハーネスが必ず知らせるので、役の完了の通知が迷って止まる形にならない。返るのは 1 件 1 行の要約（`ok`・`why`・`session_id`・続きを頼んだ回数・費用）だけで、**役の返答の本文はあなたの文脈に入らない**。`ok` の節は受け付け済みなので `done` は要らない——そのまま `next`。
     - **ok でなければ `why` を読め**: 期限切れ（`expired`）・拒否が上限まで続いた・子が落ちた、なら `loop.py relaunch --node <id> --reason <理由>` で起こし直してから `launch`。`stderr` の `with-auth: auth=…` が `none` / `keychain-miss(…)` なら認証が足りていない（`keychain(…)` / `inherited(…)` なら役の側）。作業ツリーの突合で止まった（investigator が作業ツリーを変えた等）なら、返答は `out_path` に在るので、戻してから `done --node <id>`（自分の変更なら `--accept-tree-change`）。engine が起こせない節（`why` が『前置ではない』『旗が無い』『権限の形』『定義が読めない』『claude が無い』）は、迂回を組まず人に渡せ。
     - **自分の Bash から `claude` を起こすな**: 出力をファイルに落とす綴りは auto mode の分類器が『Auto-Mode Bypass』で止める（実測 2026-09-15）。止められても別の綴りを探すな。**Agent ツールで起こすな**——ハーネスが subagent に CLAUDE.md 階層を注入し、それを止める設定が公式に存在しない（公式文書 code.claude.com/docs/en/sub-agents、2026-09-12 取得: 『Explore and Plan are the only subagents that omit CLAUDE.md and git status. There is no frontmatter field or per-agent setting to change which agents skip them.』）。役の返答の本文もあなたの文脈に入る。
     - **engine がどう起こすか**（何を起こすかは engine の柵 `launch_refusal` が argv から機械で縛る。graph の宣言は柵の根拠にしない）: 前置は認証だけを足す層（`scripts/with-auth.py`。**子は対話の claude の認証を継がない**——実測 2026-09-12: 『Failed to authenticate…』の 1 行・73 バイトが返った）。**道具ゼロの役**（`cold-reader` / `blind-judge`）は `--tools ""` と `--setting-sources ""` で起こす（実測 2026-09-12: Agent ツールで起こした道具ゼロの `cold-reader` が利用者の CLAUDE.md の 1 項目を逐語で引用した。`--setting-sources ""` を付けると消えた）。組織管理の CLAUDE.md だけは外せないので、完全な遮断とは名乗らない。**道具つきの役**（judge・inspector・investigator）も同じ綴りで起こす: 役の定義（`agents/<役>.md`）の本文を system prompt に足し、道具・モデル・effort を定義どおりに argv に並べ、権限を engine が道具から決めて明示する——既定は先に許した道具だけの `dontAsk`、コマンドを走らせる道具（Bash）を持つ役は分類器に掛ける `auto`、どちらも聞く先を持たない（`--permission-prompts none`）。分類器は外への書き込みを拒むが、読むだけの `gh` も拒む（実測 2026-09-25）ので、investigator は子では GitHub を WebFetch で読む。定義が道具の一覧を持たない役（comment-analyzer）・ファイルを書く道具を持つ役は engine が起こさない（下の「`launch` を持たない agent」）。道具つきの役にも **CLAUDE.md は読ませない**（`--setting-sources ""`）。理由は graph の `launch.tooled.why`: 役が見る物は graph の `reads` が宣言した物だけにする（観点の REVIEW.md は `reads` で渡している）／利用者の CLAUDE.md は回す側に向けた出力の作法で、JSON だけを返す契約とぶつかる（実測 2026-09-25）／利用者とプラグインのフックが子で発火しないので、読了の記録（`reads.jsonl`）が回す側の読みだけになる。材料は標準入力で渡るので、貼る上限に当たらない（2026-09-12 にこの環境——macOS・claude 2.1.269——で 748,883 バイトと 774,021 バイトの入力が欠けずに届いた。測定の記録は docs/loop-contract.md の T 節。リポジトリのルート基準で、プラグインとして入れた実体には無いので clone か GitHub で見る: https://github.com/raiki61/claude-plugins）。
   - **`launch` を持たない agent / agent_continue** —— 役の定義がこの環境に無い・定義が道具の一覧を持たない（`pr-review-toolkit:comment-analyzer`）・ファイルを書く道具を持つ・モデルか effort を名指ししない役と、Agent で起こした旧い盤面の続き。engine は起こさないので、`subagent_type` に `agent_type` を渡して Agent ツールで**直接**起こし（`deliver` が `path` なら「`<prompt_file>` を Read し、その指示にそのまま従え。返答は指示どおりの JSON だけ」の 1 文、`paste` なら本文をそのまま貼る。**本文に足すな・削るな・言い換えるな**）、返答を `out_path` に書いて `done --node <id> --agent-id <役の id>`。agent_continue なら `agent_id` に SendMessage で続ける。このときだけ役の返答があなたの文脈に入る。
   - **runner** —— あなたの仕事。**`delegate` が付いた節は自分でやるな**——`delegate.model` の汎用 agent（Agent ツールの `model` にその名前）を「`<prompt_file>` を Read し、その指示どおりにやれ。作業ツリーのファイルを変えるな（書いてよいのは `<out_path>` だけ）。返答を `<out_path>` に書き、私には wrote とだけ返せ」の 1 文で立て、終わったら `done --node <id>` だけ打て。コマンドの出力や読んだ本文があなたの文脈に入らず、周を回す文脈が長持ちする（`delegate.why` が任せてよい理由）。**`delegate.background` が真の節は待つな**——任せ先を背景で立て（Agent ツールの背景実行。起こすのは役ではなく汎用の任せ先なので、上の「Agent ツールで起こすな」には当たらない——engine が子プロセスとして起こして終了を直接待つのは `launch` を持つ役の節だけで、この線は engine も回す側も待たない）、プロンプトが名指す受領をすぐ `out_path` に書いて `done` しろ。その節の結果は engine の instance を通らず、置き場（盤面の `lanes/`）に落ちて、書き終えた後の周の機械の節が読む（このループでは変異の検算とテストの書き足しの線 `p3.delta_gates`。周の締めも次の周もこの線を待たない。線の中で閉じなかった見逃しは次の周の判定に、足したテストは修正の前に作業ツリーへ重なる）。任せ先が落ちても周は止まらない——収束を言う前の最後の関門（`p4.final_gates`）が最終のコードで撃ち直す。`delegate` の無い runner の節（基準点・目的・前提・修正・報告）は、あなたの判断そのものなので自分でやる。`prompt_file` の指示に従って自分でやり、返答の JSON（`report` と `report.human_items` は本文そのもの）を `out_path` に保存する。`skills` があればその skill を**あなたが**呼ぶ（局所レビュー）——任せ先の agent に skill ごと任せるな（skill は中でさらに役を背景で起こすので、孫の完了の知らせが任せ先に届かず待ち続ける。graph は skills を持つ節に delegate を書けない）。期限（`deadline_at`）を持つ節の任せ先を背景で起こしたら、`next` の `how` のとおり `loop.py wait` を背景で立てて待ち、期限切れなら `loop.py relaunch` で起こし直せ。記録や役の返答は本文でなく置き場のパスと 1 行の要約で渡される——要る所だけ Read で読む。

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

4. **終わり**。最後の節 `report` の前に engine が記録を仕上げて検証器を回す。`report` の本文は盤面の置き場の `report.md` に保存される。それを依頼者の言語でそのまま出せ。ループが途中で終わったら、基準点の節で `git add -N` したパスを `git reset -- <path>` で戻せ（この手順が index を変える唯一の書き込み）。

## 判定から入る（人の修正依頼）

人が「これを直して」と頼むときの入口。依頼を判定（`p2.diagnose`）へ流すので、判定役の反証・零処方からの列挙・先行例、修正案の事前審査、修正差分の審査と変異の検算が依頼にもそのまま当たる。P1（素材集め）の役は起こさない——P1 は 1 周の費用の大半で、依頼 1 件のために既存のコードへ回す物ではない。

**使い分け**: 依頼を直せば機構の新設・共有面の拡大（複数の消費者が使う仕組み・engine・共通設定）に及ぶなら、判定から入る——[REVIEW.md](../../REVIEW.md)「処方の最小性」はそれを修正でなく設計作業とし、零処方からの列挙なしに実装することを禁じている。それ以外（1 か所の誤字・局所のバグ）は、ループを回さず直接直せ。

1. 依頼を、判定役が読む findings の型の JSON 配列で書く。欄は `where`・`text`（必須）と `mechanism`・`measured`・`false_positive_if`（任意）だけで、ほかの欄は拒まれる:

   ```json
   [{"where": "graphloops/engine/commands.py: cmd_skip", "text": "…が無い", "mechanism": "…だから", "measured": "2026-09-25: …で見た", "false_positive_if": "…なら誤り"}]
   ```

2. `init` の直後、最初の `next` より前に、依頼を置く。`--reason` は出どころ（誰の・どこからの依頼か）で、依頼は記録の `process.request_findings` に周（`round`）と出どころ（`origin`）つきのバッチとして積まれる:

   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/scripts/loop.py" add --file <依頼.json> --reason "<出どころ>" --dir <DIR>
   ```

   この位置（1 周目の P1 より前）の最初の `add` だけが、run を「判定から入る run」にする（入口の印 `process.request_entry` が立ち、戻らない）。BASE は作業ツリーと同じ commit でよい——依頼は既存のコードに向くので差分が空なのが普通で、入口の run は空の差分で止まらない。

3. あとは上の手順 2 と同じに回す。判定のプロンプトには依頼が「人の修正依頼」として役の観察と分けて載り、飛ばした P1 の素材は「判定から入る run のため、P1 の役を起こしていない」の理由つきで条件外（not_applicable）になる。

**途中の周で依頼や観点を足す**: `add` は、その周の判定役（`p2.diagnose`）が起きる前なら、どの周でも何度でも受ける（入口の run でも通常の run でも）。積んだ依頼はその周の判定役にだけ届き、次の周の頭で `process.request_history` に移る（前の周の依頼の扱いは、単位と台帳を通して履歴の突合が運ぶ）。途中の周の `add` は P1 を外さない——P1 を外すのは、上の手順 2 の位置で始めた run だけである。判定役が起きた後の `add` は拒まれる: 次の周が来るならその判定の前に足し、来ない（収束した・終わった）なら、新しい run を判定から始めよ。

**代償**: 依頼の外を見る目（衛生・手順トレース・外部標準・ゲートの検算など）はその周に無い。依頼の周りの別の欠陥を拾えるのは判定役と修正前後の審査だけである。入口が効くのは修正が入るまでで、修正が 1 ファイルでも入った次の周からは、通常の run と同じく P1 が修正差分を見る（修正が 0 行のまま周が進めば、次の周も P1 は外れたままで、1 周目の依頼もその周の判定役に届き続ける。判定が依頼を全部却下すれば、P1 を起こさないまま収束して報告まで届く）。報告の冒頭には判定から入った run であることと、どの周に何件の依頼が積まれたかが載る。`loop.py patch` は手当ての口として、依頼の欄（`process.request_findings`）も入口の印（`process.request_entry`）も書ける（痕跡は `state.patches` に残る）。型の検査は add と rules の読む口（依頼の一覧は移し替え・素材の理由の件数・次の add、印は入口の判定）にだけ在る——依頼の一覧は型が崩れていれば移し替えにも件数にも使わず次の add も拒み、印は型が崩れていれば入口にならない。判定のプロンプトは欄をそのまま載せるので、patch で依頼を置くなら add と同じ型（`[{round, origin, findings}]`）にせよ。

## 守ること

- 周の記録（`rounds/round-<N>.json`）を直接編集しない。判定の欄は役の返答から engine だけが書く。手当ては `loop.py patch`（痕跡が残る最終手段）。
- 済んだ節に `done` し直さない（同じ周で採点役を回し直して有利な判定を採らない。やり直しは次の周）。
- 探す役に「ここは見るな」の線を引かない（プロンプトを書き換えない）。削るのは judge の仕事である。
- 会話が圧縮されて場所を見失ったら `loop.py status --dir <DIR>` → `loop.py next --dir <DIR>`。盤面はディスクにある。
- 数える問い（判定者の `class_query`・修正の `coverage` の `how`）は engine が数える——判定者の件数は周に固定した版で、修正の前後は p3.fix の done で。回す側が数える口は置いていない（置いていた数えるサブコマンドは、engine の数え方と揃わない入口として 4 回繕われ、使う側が無かったので消した）。
- **Web を読む調べ（先行例・一次情報の確かめ）は自分でやるな**——読み役（`convergence-loops:investigator`）を起こして任せ、返った結論と出典だけを受け取れ。ページの本文があなたの文脈に入ると、周を回す文脈が先に尽きる。
- 盤面の置き場は `git rev-parse --git-dir` の下（作業ツリーの外）。investigator の前後と P1 の前後で engine が作業ツリーを突き合わせる。自分の変更なら `--accept-tree-change "<理由>"` で痕跡付きで通す——investigator の instance の突合で止まったなら `done` に、P1 後の機械の節で止まったなら `next` に付ける（そのとき pending の instance は無いので `done` では通せない）。
- 報告は依頼者の言語で書く。この手順書が日本語なのは理由にならない。
