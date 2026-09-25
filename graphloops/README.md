# graphloops

収束ループ（結果が動かなくなるまで回す手順）のグラフ実行版。同じリポジトリの convergence-loops が配る 4 本のコマンド（`/review-loop`・`/research-loop`・`/doctor-loop`・`/firstread-loop`）は、回す手順を散文の手順書に書き、それを LLM が読んで従う。graphloops は同じループを「節（工程）＋依存＋周回条件」の JSON に写し、機械（engine）が盤面を持って回す。回す側の LLM は、渡された節を実行して返すだけになる。

実行版は `/research-graph`（`/research-loop` の実行版）と `/review-graph`（`/review-loop` の実行版）の 2 本。既存の 4 コマンドのうち 3 本（`commands/doctor-loop.md`・`research-loop.md`・`review-loop.md`（リポジトリのルート基準。プラグインとして入れた実体には無いので、clone か GitHub で見る: https://github.com/raiki61/claude-plugins））を触った——Read を持つ役には本文を貼らず path を渡す旨の文（doctor 1 行・research 1 行・review 2 行）と、`review-loop.md` の基準点の決め方の 1 行。計 5 行の差し替えで、allowed-tools と `firstread-loop.md` は不変（`git diff <BASE> --stat -- commands/` で確かめられる。以前は「渡し方の 1 行だけ」と書いていて実差分と食い違い、目的監査がそれを根拠に R2 を止めた）。本体は隣に置く。記録の形と検証器（convergence-loops の `scripts/<loop>-record.py`）は共通で、これが新旧の橋——同じ対象で両方を回し、同じ検証器に通した記録を比べるのが受け入れ試験である。

## 3 層

| 層 | 場所 | 持つもの |
|---|---|---|
| engine | `scripts/loop.py` | 盤面・波・扇・条件・穴埋め・型検査・汎用の書き込み・被覆・作業ツリー突合・人に聞く・昇格・痕跡 |
| graph | `graphs/<loop>.json` | 節・依存・役・prompt_file・schema・writes・cond（条件の関数の名前）・reads。最上位に plugin（役割 agent と検証器を持つ plugin）・runners（回す側の run_by）・thickness.tiers / default / deciders（段）・deliver.path_tools（自分で読める道具） |
| rules | `rules/<loop>.py` | 記録の初期形・扇の項目の選び方・節の条件（CONDS。読む欄を宣言した関数）・機械の節・整合の後検査・仕上げ |

engine はループの節名も記録の欄名も持たない。graph が名前で指し、engine が名前で rules を呼ぶ。JSON に書けないのは算術（件数の等式・連続カウント・無作為の抜き取り・記録の形に固有の書き込み）だけで、それが rules にある。

プロンプトは `prompts/<loop>/<節>.md`（loop をまたいで同じ段落——人の方針の段落 `prompts/policy*.md`——は `prompts/` の直下に置き、graph の `prompt_append` で節に足す。置き場の決め方は両 loop の rules が共有する `rules/policy_input.py`。回し方は [commands/review-graph.md の「人の方針」](commands/review-graph.md#人の方針)）。穴（`{{record.claims | pick id,claim}}` のような形）は graph の `reads` に宣言されたものしか埋まらない——「渡してはいけないもの」を、貼らないことで守る。`out.<節>` は自分より前の節の出力、`prev.<節>` はその節が最後に走った前の周の出力（穴でも `ref:` でも同じ範囲。同じ接頭に 2 つの意味を持たせない）、`file:` はファイル本文、`section:<path>#<見出し>` は markdown の 1 節（どちらも道具なしの役に貼るため。上限を超えたら切って記録に残す）。engine は loop の語（役の名前・段の名前・道具の名前・プラグイン名）を持たない——全部 graph の最上位が宣言し、graphcheck が欠けを見る。`ref:record` `ref:out.<節>` `ref:prev.<節>` `ref:raw` は本文でなく置き場のパスと 1 行の要約——回す側の節に使う（回す側は返答を受け取った時に一度読んでいるので、貼り直すと文脈を 2 回使う）。役の返答の置き場も engine が決める（`next` の `out_path`。役は engine が `loop.py launch` で起こし、返答をそこへ書いて受け付けまで済ませるので、回す側の文脈を返答が通らない）。役へのプロンプトの渡し方も engine が決める（`next` の `deliver`）: 役の定義の `tools` が graph の `deliver.path_tools` のどれかを持てば path（回す側は本文に触れない）、持たなければ paste。同じ役を続ける節（`same_context_as`）は、前の節を `launch` で起こしたときの会話の番号（`session_id`）を engine が持ち回り、`--resume` で同じ会話を続ける（Agent で起こした節なら `done --agent-id` で残した id）。

## 回すとどうなるか

`init` で盤面（`$(git rev-parse --git-dir)/graphloops/<loop>/<run-id>/`。作業ツリーの外）を作り、`next` が「いま走らせてよい節」をプロンプトごと JSON で返す。回す側は役の節（`launch` を持つ節）を `loop.py launch` で engine に起こさせ（engine が子の終了を直接待ち、返答を書き、受け付けまで済ませる。拒まれたら同じ会話に出し直させる。時間の上限は付けない）、自分の節は自分でやり、返答を `done` で返す。任せ先（delegate）は回す側が Agent ツールの前景で起こし、その返りを終了として待つ。落ちた試行は `loop.py relaunch` で起こし直す——新しい試行を書いてから engine が起こした前の試行の子を木ごと止め、試行の回数と理由が盤面と trace に残る。engine は返答を型で検査し、記録に写し、扇の被覆（返した答えが項目を全部覆っているか）を数え、機械の節（件数突合・収束判定）を走らせ、次の周を開くか、止めるか、人に聞く。最後の `report` の前に記録を仕上げて検証器を回し、通らなければ `report` を出さない。

散文の手順書より機械が守れるようになるもの: 依存と波、渡してはいけないもの、役の指定、上限、連続カウント、無言の省略（被覆の突合）、圧縮後の再開（盤面はディスク）、作業ツリーの前後突合（**射程は 2 軸で狭い**——git が映す範囲だけ〈.git/ 配下・ignore 対象・リポジトリ外は見えない〉と、P1 の前後という時点だけ〈判定や修正の最中の書き換えは見ない。実測 2026-09-13: この run の判定の最中に engine が 1 か所書き換わり、盤面は何も止めなかった〉）。**『回す側の降格の禁止』はここに入らない**——機械が縛るのは graphcheck の検査 2（節の run_by が判定の欄に触れない）までで、回す側が段を下げる・役を起こさずに自分で答える・役の返答を書き換える経路を engine は見ていない（BASE の `docs/loop-contract.md` の規律 U も同じ項目を『散文だけのもの』と書いている。この README の次の段落「守れないまま残るもの」が並べる受容と食い違っていた）。

守れないまま残るもの: **遮断系（道具ゼロの役）の文脈遮断は完全ではない**——`--setting-sources ""` が外せるのは user / project / local の 3 つだけで、組織管理（managed-settings.json・MDM・コンソール）由来の設定は外せない。とくに SessionStart / UserPromptSubmit のフックの標準出力は、道具を 1 つも持たない役にもプレーンテキストとして文脈へ足される（公式の hooks の仕様。道具の呼び出しに紐付かないので `--tools ""` でも止まらない）。`--bare` は同じ目的の単発フラグだが、認証を API キー経由に限定し OAuth と keychain を読まないので単純な置き換えにならず、採っていない。／**子は対話の claude の認証を継がない**ので、`launch.argv` には認証だけを足す薄い層（`scripts/with-auth.py`）が前置してある（実測 2026-09-12: 『Failed to authenticate』の 1 行 73 バイトで周が止まった）。段は「親の環境に在る認証を尊重 → mac は Keychain → どの段でも `CLAUDE_CONFIG_DIR` を子へ明示」で、**Keychain の無い環境では最後の段だけが効く**（＝その config-dir に認証が無ければ救えない。そのときは `with-auth: auth=…` の 1 行が標準エラーに出るので、役の返答の不良と取り違えずに済む）。／**役は engine が起こす**（`loop.py launch`）。回す側が Bash から起こす形は、出力をファイルに落とす綴りだと auto mode の分類器が止めるため（実測 2026-09-15: 同じ層でも出力が会話に出る形は通り、`< 材料 > out_path` は『Auto-Mode Bypass』で拒否された。gates が同じ起動を通せているのはフックが分類器の見ない経路だからで、認証の差ではない）。起動が engine に入るぶん、**何を起こすかは engine が機械で縛る**——自分のインタプリタと同梱の層以外は起こさず、claude の後ろの語は形ごとの旗の許可表で読む（表に無い語——公式の別名・`--flag=value` の綴り・`--add-dir`・`--mcp-config`・`--agents`・権限を外す旗・位置引数——と、同じ旗の 2 度目を拒む）。値は engine が決めた物だけ: 道具ゼロの役は `--tools ""` と `--setting-sources ""`、道具つきの役は `--setting-sources ""`・`--permission-prompts none`・権限の形と先に許す道具と設定（`--settings`。Bash を持つ役の sandbox）が engine の決めた値（`role_run.tooled_permission`）・渡す道具が役の定義と一致しファイルを書く道具を含まない。共通にモデル・effort・system prompt の本文が役の定義と一致し、続ける会話は engine が決めた物だけ（形は起こす時に読み直した役の定義で決める。graph の宣言を読んで判断する柵は、graph を書ける人が柵ごと書き換えられるので柵にならない）。**道具つきの役にも CLAUDE.md を読ませない**（`--setting-sources ""`）: 役が見る物は graph の `reads` が宣言した物だけにする（観点の REVIEW.md は `reads` で渡す）／利用者の CLAUDE.md は回す側向けの出力の作法で、JSON だけを返す契約とぶつかる（実測 2026-09-25: 読ませると目印が返答の頭に付いた）／利用者とプラグインのフックが子で発火せず、読了の記録が回す側の読みだけになる。代償として、プロジェクトの CLAUDE.md の規約も役に届かない（要る規約は `reads` で渡す）。子はプラグインを読まないので、役の定義の本文は engine が `agents/<役>.md` から盤面に写して system prompt に足し、道具・モデル・effort・権限は argv に並べる（権限を決める事実を柵の読む argv の外に置かない）。／回す側が engine を飛ばす・プロンプトを書き換える（trace と prompt の hash は残るので検出はできる。塞ぐなら Agent の PreToolUse hook で hash を照合する——未実装）。**同じ受容に含まれるもの**: 実行の正本をレビュー対象の木と環境変数から取ること（起こす語の旗と値は engine の許可表で縛るが、起こす相手の実体（claude の在処）は PATH から引き、rules の相対パスは graph のディレクトリ配下に封じ込めていない。`<PLUGIN>_ROOT` / `CLAUDE_CONFIG_DIR` が exec 対象・役定義・scripts の置き場を切り替える。観点の `REVIEW.md` は BASE でなく作業ツリーから取る）——自己レビューでは回す側が自分を回す graph / rules / 観点を編集できる立場に在る。**盤面の保存経路**: 版の突合は後勝ちを止めるが、読んでから書くまでの窓と state.json / record.json の 2 ファイル確定の非アトミック性は残る（並行実行は運用で禁じる）。役の判断の質そのもの。

## 検査

```bash
python3 graphloops/scripts/graphcheck.py graphloops/graphs/research-loop.json scripts/research-record.py
bash graphloops/tests/run.sh
```

`graphcheck` は graph の形（依存の実在と循環・回す側が判定を出していない・検証器の欄が節の出力に現れる・穴が reads に宣言されている・回す側の writes が判定の欄に触れない・名前が engine か rules にある）を見る。`tests/run.sh` はそれに加えて、役の返答を台本で差し替えた模擬実行を端から端まで回す——research は収束・無人の停止・有人の諮り・軽量の打ち切り・拒むべき返答の拒否、review は連続 2 ラウンドの収束・前提不成立で人へ・保留の問いに帰属して人へ・答えを渡して続行・上限で停止・拒むべき返答の拒否（周の記録は本物の検証器 review-record.py にディレクトリ渡しで通す）。役の判断の質は見ない（それは実走）。

### pytest の置き場（graphloops/tests/py/）

関数を直に呼ぶ単体の検査は pytest に置く。依存は開発の間だけで、その場で入れる（プラグインの利用者の必須には足さない）:

```bash
uv run --no-project --with pytest python -m pytest graphloops/tests/py
```

**置き場の方針**: 単体の検査（関数を直に呼ぶ物）は、新しく書くなら、また既存の物を触るなら pytest に書く。bash の側から pytest へ移し終えた検査は、同じ変更で bash の側を消し、両方の件数の定数（bash の台本の `EXPECTED_CHECKS` ほかと、`graphloops/tests/py/conftest.py` の `EXPECTED_ITEMS`）と、その検査を当てにする変異の腕（`tests/mutations.json` の `tests`）を同じ変更で直す——ただし腕の実行器 `tests/mutate.py` はまだ bash の台本しか回せない（撃つ台本の表は `tests/run.sh` と `graphloops/tests/run.sh` の 2 本）ので、bash 側を消す最初の変更で実行器に pytest の口を足す。それまでは腕が pytest の写しでも落ちることを手で確かめる（今の `engine/schema.py` の腕 11 本は 2026-09-25 に全部落ちた）。盤面を端から端まで回す台本（`tests/simulate.py`・`tests/simulate_review.py`）は、台本の土台がまだ pytest に無いので、土台を移すまでは今の置き場に足す。今の pytest 側の中身は `engine/schema.py` の検査（差し替えの版の重ね方 `test_graph_extends.py` を含む）と、`engine/role_run.py` の `unwrap`（役の標準出力を解く）の検査と、TDD の流れの赤・緑の判定（`test_review_tdd.py`）と、走らせるだけの節と宣言（`test_engine_run.py`）・人の方針の関所（`test_policy_gate.py`）・review-loop の rules の欠けた入力（`test_review_rules.py`）・engine の守りの口（`test_engine_guards.py`）・子を止める部品（`test_role_run_stop.py`）の検査で、そのうち `test_schema.py`・`test_schema_graphcheck.py` は bash 側の同じ検査の写し（bash 側はまだ消していない。移し終えるまでは片方を直したらもう片方も直す——ずれを見る柵は無い）。

**柵**（`graphloops/tests/py/fence.py`）: 飛ばしは失敗にする（テスト単位の skip・xfail と、モジュール丸ごとの skip・importorskip の両方）。集めたテストの数を `EXPECTED_ITEMS` と `!=` で突き合わせる——置き場のテストのファイルを全部集めた回だけで、パス・node id・`--ignore` などでファイルを絞った回は柵を外して、外した旨を 1 行出す（`-k` は集めた後で選ぶので柵は付いたまま）。CI は置き場を丸ごと回す。

**変更に関係するテストだけ回す道具（pytest-testmon）**: 使うなら手元の速回しだけで、commit 前と CI は全件。testmon はファイルを集めないので、上の柵はその回を「絞った回」と見なして外す。測った事実（2026-09-25、Python 3.14・pytest-testmon 2.2.0・coverage 7.16.1）: 設定のままでは rootdir（`graphloops/tests/py/`）の外にある `engine/` の変更を追わず、`schema.py` を壊しても 1 件も選ばなかった。`--rootdir=graphloops` にすると追うが、Python 3.14 の既定（coverage の `COVERAGE_CORE=sysmon`）では落ちるべきテストを選び漏らし、`COVERAGE_CORE=ctrace` で正しく選んだ。graph の JSON・プロンプトの変更には効かない:

```bash
cd graphloops/tests/py && COVERAGE_CORE=ctrace uv run --no-project --with pytest --with pytest-testmon python -m pytest --rootdir=../.. -c pytest.ini --testmon .
```

**変異テスト**: 手書きの腕（`tests/mutate.py` と `tests/mutations.json`）は、呼び出しを足す変異・デコレータ付きの関数・JSON・Markdown・シェルを狙う腕と、どの検査で落ちたかの突き合わせのために残す。pytest が覆うモジュールを丸ごと撃つのは既製の mutmut で、設定は `graphloops/setup.cfg`（鍵の名前は mutmut 3 の物で、2 系の `paths_to_mutate` などとは違う。版を固定して回す）。mutmut は作業用の写しを回した場所の `mutants/` に作り、前回の「殺した」結果を持ち越すので、**作業ツリーの一時の写しの上で、毎回新しく**撃つ（作業ツリーに `mutants/` を作ると、ファイルシステムを直に走査する `tests/run.sh` の柵がその写しまで数える）。Windows では動かない:

```bash
tmp=$(mktemp -d) && git ls-files -co --exclude-standard | tar -cf - -T - | tar -xf - -C "$tmp"
cd "$tmp/graphloops" && uv run --no-project --with mutmut==3.8.0 --with pytest mutmut run --max-children 4 && uv run --no-project --with mutmut==3.8.0 --with pytest mutmut results
```

`mutmut results` が挙げる生き残りのうち、実害のある物を pytest 側のテストで殺す。CI では回さない（生き残りの数で落とす形は作れず——文言だけの変異が残る——、報告だけのジョブは誰も読まない。落とす柵は手書きの腕の側に在る）。

## ループを足すには

1. `graphs/<loop>.json` に `exec: true` と `rules` を書き、各節に `prompt_file`・`schema`（か `text: true`）・`reads`・`writes` を足す。写しだけの graph（`exec` 無し）は graphcheck の写しの形の検査だけ通ればよい。
2. `prompts/<loop>/` に節ごとのプロンプト。散文の手順書の「なぜ」を前書きに残す（指示だけに削ると、規律は守られても判断の質が落ちる）。
3. `rules/<loop>.py` に `init_record`・`FAN_OUT`・`WRITE_OPS`・`BUILTINS`・`POST_CHECKS`・`check_record`・`finalize`・`on_answer`・`on_unattended`・`on_thickness`・`add`（要るものだけ）。
4. `tests/simulate.py` に台本を足す（盤面を回す台本の土台はまだそこにしか無い。関数を直に呼ぶ検査なら `tests/py/` に pytest で書く——上の「pytest の置き場」）。
5. `commands/<loop>-graph.md` は engine の呼び方だけ。

## 流れの一部を差し替えた版を足すには

同じループの一部の節だけを別の流れに差し替える版（例: 修正を TDD の流れにした `graphs/review-loop-tdd.json`）は、元の graph を写さずに差分だけを書く。最上位に `"extends": "<元の graph のファイル名>"` を書くと、engine（`engine/schema.py` の `load_graph`）が元の graph に RFC 7396（JSON Merge Patch）で重ねる: object は鍵ごとに重なり、`null` は鍵を消し、配列は置き換わる。

- 元は同じ置き場（`graphs/`）のファイルだけで、重ねは 1 段だけ。継いだ節の `prompt_file`・`rules` の相対パスが同じ置き場を基準に読まれるため。
- 差し替えた節の `deps`・`reads` は元の要素も書く（配列は置き換わる）。元の要素を落とすと graphcheck が止める——元の graph に後から足した依存が、差し替えの版で黙って消えないように。
- 元の指示書に段落を足すなら、節の `prompt_append`（指示書の後ろに続けるファイルの一覧）に書く。元の指示書は写さない。
- rules を足すなら別のファイルに置き、元の rules を読み込んで表（`CONDS`・`BUILTINS`・`POST_CHECKS`）に足した写しを出す（`rules/review-loop-tdd.py` の頭の形）。元の rules は触らない。
- どの版で回すかは `init --loop <版の名前>` で選ぶ。元の graph で回す run は、差し替えの版があってもなくても同じに動く。

残りの 2 本（doctor・firstread）の graph はこの差分に**入れていない**。写しだけのグラフを先に積むと、engine の実行経路に乗らない 1,123 行が凍結した目的の外に残る——実行版を作る周に、回せる形で一緒に入れる（追跡は別 issue）。

## 未実装

- 相違の 3 票の増し掛け（散文の「結論の芯を書き換える相違は独立 3 票で 2/3」）。既定の 1 票だけ。
- Agent の起動プロンプトを engine の出した hash と照合する hook。
- doctor・firstread の実行版。
- review の最終報告の初見検査は 1 回だけ（散文の「詰まりが残るうちは出すな」の往復は report の節の中で writer が直す形）。
