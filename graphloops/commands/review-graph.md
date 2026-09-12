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

役割 agent は convergence-loops に同梱の役の定義（`convergence-loops:judge` のように接頭辞付きで指す）と、依存で入る `pr-review-toolkit:comment-analyzer` を使う。engine が返す `agent_type` をそのまま Agent の `subagent_type` に渡せ。モデル・道具は役の定義が正本で、この手順書にもグラフにも書かない。

## 手順

1. **始める**。何をレビューするか（PR 番号・ブランチ・一言）を依頼文として渡す:

   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/scripts/loop.py" init --loop review-loop --request "<何をレビューするか>"
   ```

   返ってきた `dir`（盤面の置き場）を **以降の全部の呼び出しに `--dir <DIR>` で渡せ**。省くと engine は `current` から推測するが、同じリポジトリに別の run が在ると取り違えて拒む（別ループの run が並ぶと exit 2）。名指しが既定の導線である。

   検証器は同じリポジトリの `scripts/review-record.py` か、インストール済みの convergence-loops から engine が探す（見つからなければ `--validator <path>`）。無人で走るなら `--unattended`。返ってきた `overview` を読め——ループ全体の形はここだけで渡す。

2. **回す**。`next` を呼び、返った `ready` を全部こなし、`done` で返す。`status` が converged か stopped になって `ready` が空になるまで繰り返す:

   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/scripts/loop.py" next --dir <DIR>
   ```

   `ready` の各要素は 1 つの節で、`mode` が 4 種類ある:
   - **cli** —— 道具ゼロの遮断系（`cold-reader` / `blind-judge`）。`launch.argv` を**そのまま**実行し、標準入力に `launch.stdin` のファイルを流して、標準出力を `out_path` に保存する（例: `"${launch.argv[@]}" < <launch.stdin> > <out_path>`）。**Agent ツールで起こすな**——ハーネスが subagent に CLAUDE.md 階層を注入し、それを止める設定が公式に存在しない（公式文書 code.claude.com/docs/en/sub-agents、2026-09-12 取得: 『Explore and Plan are the only subagents that omit CLAUDE.md and git status. There is no frontmatter field or per-agent setting to change which agents skip them.』）。実測 2026-09-12: 道具ゼロの `cold-reader` が利用者の CLAUDE.md の 1 項目を逐語で引用した。`--setting-sources ""` は CLAUDE.md ごと外す（同日の対照実験——フラグ無しでは目印が見え、付けると消えた）。材料は貼らず標準入力で渡るので、貼る上限に当たらない（2026-09-12 にこの環境——macOS・claude 2.1.269——で観測: 748,883 バイトと 774,021 バイトの入力が先頭・末尾とも欠けずに届いた。測定の記録は docs/loop-contract.md の T 節。上限の値は目安で、入り切らなければ API が落として done が拒む）。組織管理の CLAUDE.md だけは外せないので、完全な遮断とは名乗らない。
   - **agent** —— `subagent_type` に `agent_type` を渡して起動する。**起動は運び手に任せろ**——小さな汎用 agent（最小のモデルでよい）を「運び手: `<prompt_file>` を `deliver` の渡し方で `<agent_type>` に渡し、返答を一字も変えず `<out_path>` に書け。あなたには wrote とだけ返せ」の 1 文で立てる。役の返答はあなたの文脈を通らず、`done --node <id>` は `--output` 無しで置き場を読む。貼るのがあなたでも運び手でも写しの忠実さは同じで、違うのはあなたの文脈が減ることだけ。`deliver` が `path` なら運び手は「`<prompt_file>` を Read し、その指示にそのまま従え。返答は指示どおりの JSON だけ」の 1 文で役を起動し、`paste` なら本文をそのまま貼る。 どちらも**本文に足すな・削るな・言い換えるな**（貼ってよいものは engine がグラフの宣言に従って埋めてある。足した一言が遮断を壊す）。**`done` に `--agent-id <その agent の id>` を添えろ**——判定（`p2.diagnose`）と履歴の突合（`p2.history`）は同じ judge が続けるので、id が無いと新しい会話になる（engine が記録に残す）。
   - **agent_continue** —— `agent_id` の agent に SendMessage で続ける（渡し方は `deliver` のとおり）。
   - **runner** —— あなたの仕事。`prompt_file` の指示に従って自分でやり、返答の JSON（`report` と `report.human_items` は本文そのもの）を `out_path` に保存する。skill を回す節（局所レビュー）は、skill の本文をあなたが読まずに済むよう、汎用 agent に skill ごと任せて結果だけ `out_path` に書かせてよい。`skills` があればその skill を呼ぶ（局所レビュー）。記録や役の返答は本文でなく置き場のパスと 1 行の要約で渡される——要る所だけ Read で読む。

   同じ `ready` に載った節は互いに依存が無い。**agent は 1 つのメッセージで並列に起動しろ**。返答を保存したら:

   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/scripts/loop.py" done --node "<id>" --output <返答のファイル> [--agent-id <id>] --dir <DIR>
   ```

   `done` が exit 1 で拒んだら理由を読んで直す。agent の節なら、理由を添えて**同じ役を起動し直して返させろ**——あなたが JSON を補ったり判定を書き換えたりしてはいけない。runner の節なら自分の返答を直す。`ready` が空で `status` が running なら、もう一度 `next`（機械の節——作業ツリー突合・素材の穴埋め・再発火の計算・周の記録・検証器——が進んで次の波が出る）。機械の節が「作業ツリーが変わっている」と言ったら、戻してから `next`——自分の変更（engine をその場で直した等）なら `next --accept-tree-change "<理由>"` で痕跡付きで通す（stash で退避しても stash の一覧が突合に入るので通らない）。

3. **人に聞く番**。`next` が `awaiting_human` を返したら、`ask` の中身（問いの台帳で保留のもの）を依頼者に見せて答えをもらい、返す。答えの本文は `--note` に入れる（次の周の judge の再審に渡る）:

   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/scripts/loop.py" answer --text continue --note "<答え>" --dir <DIR>
   python3 "${CLAUDE_PLUGIN_ROOT}/scripts/loop.py" answer --text stop --dir <DIR>
   ```

   **聞き方**: 質問の道具（選択肢を並べて選ばせる型）を使うな。依頼者はループの間ずっと別の作業をしていて、答える時点で文脈を持っていない。選択肢だけ並んだ問いは初見では決められない。散文で、次を冒頭にまとめて出せ: ①何のループが・何を調べていて・どこで止まったか ②なぜ止まったか（きっかけの実物——どの問いが・何周目に・何から立ったか）③答えの候補ごとに何が起きるか ④あなたの推奨と根拠（`escalate` は judge が「人でないと決められない」と確定したものなので推奨を書くな。書いてよいのは台帳の `options` と `reason` だけ）。内部の語彙（節の名前・安定キー・stuck 等の種別名）は使うなら初出で中身から言え。答えは自由な文で受け、`answer` の語に写すのはあなたの仕事である。

4. **終わり**。最後の節 `report` の前に engine が記録を仕上げて検証器を回す。`report` の本文は盤面の置き場の `report.md` に保存される。それを依頼者の言語でそのまま出せ。ループが途中で終わったら、基準点の節で `git add -N` したパスを `git reset -- <path>` で戻せ（この手順が index を変える唯一の書き込み）。

## 守ること

- 周の記録（`rounds/round-<N>.json`）を直接編集しない。判定の欄は役の返答から engine だけが書く。手当ては `loop.py patch`（痕跡が残る最終手段）。
- 済んだ節に `done` し直さない（同じ周で採点役を回し直して有利な判定を採らない。やり直しは次の周）。
- 探す役に「ここは見るな」の線を引かない（プロンプトを書き換えない）。削るのは judge の仕事である。
- 会話が圧縮されて場所を見失ったら `loop.py status --dir <DIR>` → `loop.py next --dir <DIR>`。盤面はディスクにある。
- 盤面の置き場は `git rev-parse --git-dir` の下（作業ツリーの外）。investigator の前後と P1 の前後で engine が作業ツリーを突き合わせる。自分の変更なら `done --accept-tree-change "<理由>"` で痕跡付きで通す。
- 報告は依頼者の言語で書く。この手順書が日本語なのは理由にならない。
