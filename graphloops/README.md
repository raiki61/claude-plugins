# graphloops

収束ループ（結果が動かなくなるまで回す手順）のグラフ実行版。同じリポジトリの convergence-loops が配る 4 本のコマンド（`/review-loop`・`/research-loop`・`/doctor-loop`・`/firstread-loop`）は、回す手順を散文の手順書に書き、それを LLM が読んで従う。graphloops は同じループを「節（工程）＋依存＋周回条件」の JSON に写し、機械（engine）が盤面を持って回す。回す側の LLM は、渡された節を実行して返すだけになる。

実行版は `/research-graph`（`/research-loop` の実行版）と `/review-graph`（`/review-loop` の実行版）の 2 本。既存の 4 コマンドのうち 3 本（`commands/doctor-loop.md`・`research-loop.md`・`review-loop.md`（リポジトリのルート基準。プラグインとして入れた実体には無いので、clone か GitHub で見る: https://github.com/raiki61/claude-plugins））を触った——Read を持つ役には本文を貼らず path を渡す旨の文（doctor 1 行・research 1 行・review 2 行）と、`review-loop.md` の基準点の決め方の 1 行。計 5 行の差し替えで、allowed-tools と `firstread-loop.md` は不変（`git diff <BASE> --stat -- commands/` で確かめられる。以前は「渡し方の 1 行だけ」と書いていて実差分と食い違い、目的監査がそれを根拠に R2 を止めた）。本体は隣に置く。記録の形と検証器（convergence-loops の `scripts/<loop>-record.py`）は共通で、これが新旧の橋——同じ対象で両方を回し、同じ検証器に通した記録を比べるのが受け入れ試験である。

## 3 層

| 層 | 場所 | 持つもの |
|---|---|---|
| engine | `scripts/loop.py` | 盤面・波・扇・条件・穴埋め・型検査・汎用の書き込み・被覆・作業ツリー突合・人に聞く・昇格・痕跡 |
| graph | `graphs/<loop>.json` | 節・依存・役・prompt_file・schema・writes・cond・reads。最上位に plugin（役割 agent と検証器を持つ plugin）・runners（回す側の run_by）・thickness.tiers / default / deciders（段）・deliver.path_tools（自分で読める道具） |
| rules | `rules/<loop>.py` | 記録の初期形・扇の項目の選び方・機械の節・整合の後検査・仕上げ |

engine はループの節名も記録の欄名も持たない。graph が名前で指し、engine が名前で rules を呼ぶ。JSON に書けないのは算術（件数の等式・連続カウント・無作為の抜き取り・記録の形に固有の書き込み）だけで、それが rules にある。

プロンプトは `prompts/<loop>/<節>.md`。穴（`{{record.claims | pick id,claim}}` のような形）は graph の `reads` に宣言されたものしか埋まらない——「渡してはいけないもの」を、貼らないことで守る。`out.<節>` は自分より前の節の出力、`prev.<節>` はその節が最後に走った前の周の出力（穴でも `ref:` でも同じ範囲。同じ接頭に 2 つの意味を持たせない）、`file:` はファイル本文、`section:<path>#<見出し>` は markdown の 1 節（どちらも道具なしの役に貼るため。上限を超えたら切って記録に残す）。engine は loop の語（役の名前・段の名前・道具の名前・プラグイン名）を持たない——全部 graph の最上位が宣言し、graphcheck が欠けを見る。`ref:record` `ref:out.<節>` `ref:prev.<節>` `ref:raw` は本文でなく置き場のパスと 1 行の要約——回す側の節に使う（回す側は返答を受け取った時に一度読んでいるので、貼り直すと文脈を 2 回使う）。役の返答の置き場も engine が決める（`next` の `out_path`。運び手がそこへ書けば `done` は `--output` 無しで読み、回す側の文脈を返答が通らない）。役へのプロンプトの渡し方も engine が決める（`next` の `deliver`）: 役の定義の `tools` が graph の `deliver.path_tools` のどれかを持てば path（回す側は本文に触れない）、持たなければ paste。同じ agent を続ける節（`same_context_as`）は、前の節の `done --agent-id` で残した id を engine が持ち回る。

## 回すとどうなるか

`init` で盤面（`$(git rev-parse --git-dir)/graphloops/<loop>/<run-id>/`。作業ツリーの外）を作り、`next` が「いま走らせてよい節」をプロンプトごと JSON で返す。回す側は役割 agent の節を Agent で並列に起動し、自分の節は自分でやり、返答を `done` で返す。engine は返答を型で検査し、記録に写し、扇の被覆（返した答えが項目を全部覆っているか）を数え、機械の節（件数突合・収束判定）を走らせ、次の周を開くか、止めるか、人に聞く。最後の `report` の前に記録を仕上げて検証器を回し、通らなければ `report` を出さない。

散文の手順書より機械が守れるようになるもの: 依存と波、渡してはいけないもの、役の指定、上限、連続カウント、無言の省略（被覆の突合）、圧縮後の再開（盤面はディスク）、作業ツリーの前後突合（**射程は 2 軸で狭い**——git が映す範囲だけ〈.git/ 配下・ignore 対象・リポジトリ外は見えない〉と、P1 の前後という時点だけ〈判定や修正の最中の書き換えは見ない。実測 2026-09-13: この run の判定の最中に engine が 1 か所書き換わり、盤面は何も止めなかった〉）。**『回す側の降格の禁止』はここに入らない**——機械が縛るのは graphcheck の検査 2（節の run_by が判定の欄に触れない）までで、回す側が段を下げる・役を起こさずに自分で答える・役の返答を書き換える経路を engine は見ていない（BASE の `docs/loop-contract.md` の規律 U も同じ項目を『散文だけのもの』と書いている。25 行目の受容と食い違っていた）。

守れないまま残るもの: **遮断系（道具ゼロの役）の文脈遮断は完全ではない**——`--setting-sources ""` が外せるのは user / project / local の 3 つだけで、組織管理（managed-settings.json・MDM・コンソール）由来の設定は外せない。とくに SessionStart / UserPromptSubmit のフックの標準出力は、道具を 1 つも持たない役にもプレーンテキストとして文脈へ足される（公式の hooks の仕様。道具の呼び出しに紐付かないので `--tools ""` でも止まらない）。`--bare` は同じ目的の単発フラグだが、認証を API キー経由に限定し OAuth と keychain を読まないので単純な置き換えにならず、採っていない。／回す側が engine を飛ばす・プロンプトを書き換える（trace と prompt の hash は残るので検出はできる。塞ぐなら Agent の PreToolUse hook で hash を照合する——未実装）。**同じ受容に含まれるもの**: 実行の正本をレビュー対象の木と環境変数から取ること（graph の `launch.isolated.argv` に allowlist は無く、rules の相対パスは graph のディレクトリ配下に封じ込めていない。`<PLUGIN>_ROOT` / `CLAUDE_CONFIG_DIR` が exec 対象・役定義・scripts の置き場を切り替える。観点の `REVIEW.md` は BASE でなく作業ツリーから取る）——自己レビューでは回す側が自分を回す graph / rules / 観点を編集できる立場に在る。**盤面の保存経路**: 版の突合は後勝ちを止めるが、読んでから書くまでの窓と state.json / record.json の 2 ファイル確定の非アトミック性は残る（並行実行は運用で禁じる）。役の判断の質そのもの。

## 検査

```bash
python3 graphloops/scripts/graphcheck.py graphloops/graphs/research-loop.json scripts/research-record.py
bash graphloops/tests/run.sh
```

`graphcheck` は graph の形（依存の実在と循環・回す側が判定を出していない・検証器の欄が節の出力に現れる・穴が reads に宣言されている・回す側の writes が判定の欄に触れない・名前が engine か rules にある）を見る。`tests/run.sh` はそれに加えて、役の返答を台本で差し替えた模擬実行を端から端まで回す——research は収束・無人の停止・有人の諮り・軽量の打ち切り・拒むべき返答の拒否、review は連続 2 ラウンドの収束・前提不成立で人へ・保留の問いに帰属して人へ・答えを渡して続行・上限で停止・拒むべき返答の拒否（周の記録は本物の検証器 review-record.py にディレクトリ渡しで通す）。役の判断の質は見ない（それは実走）。

## ループを足すには

1. `graphs/<loop>.json` に `exec: true` と `rules` を書き、各節に `prompt_file`・`schema`（か `text: true`）・`reads`・`writes` を足す。写しだけの graph（`exec` 無し）は graphcheck の写しの形の検査だけ通ればよい。
2. `prompts/<loop>/` に節ごとのプロンプト。散文の手順書の「なぜ」を前書きに残す（指示だけに削ると、規律は守られても判断の質が落ちる）。
3. `rules/<loop>.py` に `init_record`・`FAN_OUT`・`WRITE_OPS`・`BUILTINS`・`POST_CHECKS`・`check_record`・`finalize`・`on_answer`・`on_unattended`・`on_thickness`・`add`（要るものだけ）。
4. `tests/simulate.py` に台本を足す。
5. `commands/<loop>-graph.md` は engine の呼び方だけ。

残りの 2 本（doctor・firstread）の graph はこの差分に**入れていない**。写しだけのグラフを先に積むと、engine の実行経路に乗らない 1,123 行が凍結した目的の外に残る——実行版を作る周に、回せる形で一緒に入れる（追跡は別 issue）。

## 未実装

- 相違の 3 票の増し掛け（散文の「結論の芯を書き換える相違は独立 3 票で 2/3」）。既定の 1 票だけ。
- Agent の起動プロンプトを engine の出した hash と照合する hook。
- doctor・firstread の実行版。
- review の最終報告の初見検査は 1 回だけ（散文の「詰まりが残るうちは出すな」の往復は report の節の中で writer が直す形）。
