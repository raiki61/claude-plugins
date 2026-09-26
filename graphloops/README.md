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

`init` で盤面（`$(git rev-parse --git-dir)/graphloops/<loop>/<run-id>/`。作業ツリーの外）を作り、`next` が「いま走らせてよい節」をプロンプトごと JSON で返す。回す側は役の節と任せ先の付いた節（`launch` を持つ節）を `loop.py launch` で engine に起こさせ（engine が子の終了を直接待ち、返答を書き、受け付けまで済ませる。拒まれたら同じ会話に出し直させる。時間の上限は付けない）、自分の節は自分でやり、返答を `done` で返す。**任せ先は OS の sandbox の中で起こす**——作業ディレクトリは本物の写しで、本物の作業ツリー・gitdir の実体・共通の `.git`・他の作業ツリー・盤面には書けない（Agent ツールで起こした任せ先が本物の作業ツリーで `git reset --hard` を打ち、回す側の未コミットの修正を消した事故への直し。2026-09-25）。docker を使うなど柵の中でできない仕事が要る run だけ、人が `init --unfenced-delegates "<理由>"` で柵を外せる（外した事実は盤面と `next` の notes に残る）。その run の任せ先は回す側が Agent ツールの前景で起こし、その返りを終了として待つ（背景の任せ先は待たない）。人が途中で止めるなら `loop.py stop --reason` で、止めた理由が記録に残り報告の節だけが走る。落ちた試行は `loop.py relaunch` で起こし直す——新しい試行を書いてから engine が起こした前の試行の子を木ごと止め、試行の回数と理由が盤面と trace に残る。engine は返答を型で検査し、記録に写し、扇の被覆（返した答えが項目を全部覆っているか）を数え、機械の節（件数突合・収束判定）を走らせ、次の周を開くか、止めるか、人に聞く。最後の `report` の前に記録を仕上げて検証器を回し、通らなければ `report` を出さない。

散文の手順書より機械が守れるようになるもの: 依存と波、渡してはいけないもの、役の指定、上限、連続カウント、無言の省略（被覆の突合）、圧縮後の再開（盤面はディスク）、作業ツリーの前後突合（**射程は 2 軸で狭い**——git が映す範囲だけ〈.git/ 配下・ignore 対象・リポジトリ外は見えない〉と、P1 の前後という時点だけ〈判定や修正の最中の書き換えは見ない。実測 2026-09-13: この run の判定の最中に engine が 1 か所書き換わり、盤面は何も止めなかった〉）。**『回す側の降格の禁止』はここに入らない**——機械が縛るのは graphcheck の検査 2（節の run_by が判定の欄に触れない）までで、回す側が段を下げる・役を起こさずに自分で答える・役の返答を書き換える経路を engine は見ていない（BASE の `docs/loop-contract.md` の規律 U も同じ項目を『散文だけのもの』と書いている。この README の次の段落「守れないまま残るもの」が並べる受容と食い違っていた）。

守れないまま残るもの: **遮断系（道具ゼロの役）の文脈遮断は完全ではない**——`--setting-sources ""` が外せるのは user / project / local の 3 つだけで、組織管理（managed-settings.json・MDM・コンソール）由来の設定は外せない。とくに SessionStart / UserPromptSubmit のフックの標準出力は、道具を 1 つも持たない役にもプレーンテキストとして文脈へ足される（公式の hooks の仕様。道具の呼び出しに紐付かないので `--tools ""` でも止まらない）。`--bare` は同じ目的の単発フラグだが、認証を API キー経由に限定し OAuth と keychain を読まないので単純な置き換えにならず、採っていない。／**子は対話の claude の認証を継がない**ので、`launch.argv` には認証だけを足す薄い層（`scripts/with-auth.py`）が前置してある（実測 2026-09-12: 『Failed to authenticate』の 1 行 73 バイトで周が止まった）。段は「親の環境に在る認証を尊重 → mac は Keychain → どの段でも `CLAUDE_CONFIG_DIR` を子へ明示」で、**Keychain の無い環境では最後の段だけが効く**（＝その config-dir に認証が無ければ救えない。そのときは `with-auth: auth=…` の 1 行が標準エラーに出るので、役の返答の不良と取り違えずに済む）。／**役は engine が起こす**（`loop.py launch`）。回す側が Bash から起こす形は、出力をファイルに落とす綴りだと auto mode の分類器が止めるため（実測 2026-09-15: 同じ層でも出力が会話に出る形は通り、`< 材料 > out_path` は『Auto-Mode Bypass』で拒否された。gates が同じ起動を通せているのはフックが分類器の見ない経路だからで、認証の差ではない）。起動が engine に入るぶん、**何を起こすかは engine が機械で縛る**——自分のインタプリタと同梱の層以外は起こさず、claude の後ろの語は形ごとの旗の許可表で読む（表に無い語——公式の別名・`--flag=value` の綴り・`--add-dir`・`--mcp-config`・`--agents`・権限を外す旗・位置引数——と、同じ旗の 2 度目を拒む）。値は engine が決めた物だけ: 道具ゼロの役は `--tools ""` と `--setting-sources ""`、道具つきの役は `--setting-sources ""`・`--permission-prompts none`・権限の形と先に許す道具と設定（`--settings`。Bash を持つ役の sandbox）が engine の決めた値（`role_run.tooled_permission`）・渡す道具が役の定義と一致しファイルを書く道具を含まない。共通にモデル・effort・system prompt の本文が役の定義と一致し、続ける会話は engine が決めた物だけ（形は起こす時に読み直した役の定義で決める。graph の宣言を読んで判断する柵は、graph を書ける人が柵ごと書き換えられるので柵にならない）。**道具つきの役にも CLAUDE.md を読ませない**（`--setting-sources ""`）: 役が見る物は graph の `reads` が宣言した物だけにする（観点の REVIEW.md は `reads` で渡す）／利用者の CLAUDE.md は回す側向けの出力の作法で、JSON だけを返す契約とぶつかる（実測 2026-09-25: 読ませると目印が返答の頭に付いた）／利用者とプラグインのフックが子で発火せず、読了の記録が回す側の読みだけになる。代償として、プロジェクトの CLAUDE.md の規約も役に届かない（要る規約は `reads` で渡す）。子はプラグインを読まないので、役の定義の本文は engine が `agents/<役>.md` から盤面に写して system prompt に足し、道具・モデル・effort・権限は argv に並べる（権限を決める事実を柵の読む argv の外に置かない）。／回す側が engine を飛ばす・プロンプトを書き換える（trace と prompt の hash は残るので検出はできる。塞ぐなら Agent の PreToolUse hook で hash を照合する——未実装）。**同じ受容に含まれるもの**: 実行の正本をレビュー対象の木と環境変数から取ること（起こす語の旗と値は engine の許可表で縛るが、起こす相手の実体（claude の在処）は PATH から引き、rules の相対パスは graph のディレクトリ配下に封じ込めていない。`<PLUGIN>_ROOT` / `CLAUDE_CONFIG_DIR` が exec 対象・役定義・scripts の置き場を切り替える。観点の `REVIEW.md` は BASE でなく作業ツリーから取る）——自己レビューでは回す側が自分を回す graph / rules / 観点を編集できる立場に在る。**盤面の保存経路**: 版の突合は後勝ちを止めるが、読んでから書くまでの窓と state.json / record.json の 2 ファイル確定の非アトミック性は残る（並行実行は運用で禁じる）。役の判断の質そのもの。

## 踏んだ問題を残す（/graphloops:intake）

利用者の環境で踏んだ問題を、会話を貼って運ばなくても 1 件 1 行で残す（設計は [docs/feedback/intake.md](../docs/feedback/intake.md) の段階 1・2。リポジトリのルート基準で、プラグインとして入れた実体には無い）。記録器は `engine/intake.py` の 1 本で、来歴（プラグインの名前・版・取れればコミット・run の番号と周）はそこだけが組む。

- **自動で残る物**: `loop.py` が非 0 で終わった呼び出し（日常の拒否 exit 1 も含む）と、`loop.py launch` で役が落ちた・拒否が上限まで続いた行（launch 自身は exit 0 のまま。行は終了コードの代わりに落ち方の種類を持ち、鍵もそれで分かれる——`commands.launch_cause`）。`loop.py` を通らない物（`with-auth.py`・`graphcheck.py`・`parallel-pr.py`・フックの `record-read.py`）は残らない
- **手で残す口**: `/graphloops:intake <1 行>`。たまった分は `export <書き出し先>` で 1 ファイルにまとめて手渡す。届け先を `set-url <URL>` で決めると `send` で POST する（`{"text": 要約, "records": 行}`。受けを立てる段 3 は作っていない）。どれも `loop.py intake` の旗
- **置き場**: Claude Code の持続の置き場 `${CLAUDE_PLUGIN_DATA}` の `intake.jsonl`（更新で消えない。アンインストールの最後の 1 回では消える）。Bash のコマンドには渡らないので、自動の口は engine の置き場 `<plugins>/cache/<marketplace>/<plugin>/<version>` から Claude Code と同じ規則で `<plugins>/data/<plugin>-<marketplace>` を導く。`--plugin-dir` で読んだ回・checkout から直に走らせた回は導けないので、自動の行は残らない（手の口は手順書の本文が置き場を渡すので残る）
- **欄と秘匿**: 既定は構造化した欄だけ——プラグインの名前・版・取れればコミット・OS と Python の版・呼び口（節の id まで。項目の鍵とパスは落とす）・終了コード・例外の型と上げた関数・run の番号と周・人が書いた 1 行。本文・差分・記録の中身は残さない。同じ問題を数える鍵は版を含まない。標準エラーの頭は環境変数 `GRAPHLOOPS_INTAKE_STDERR=1` のときだけ残し、書き出しと送る本文からは既定で落とす
- **止めない**: 残す処理は何が起きても、元の終了コードと出力を変えない。認証もネットワークも使わない（使うのは利用者が明示に呼ぶ send だけで、期限は付けない）
- **報告の頭**: `save_text_as` の節（両ループの最終報告）を保存するとき、engine が 1 行目に来歴（`graphloops <版> (<commit>) / <loop> run <run_id> / round <周> / graph <sha>`）を刻む

## 検査

```bash
python3 graphloops/scripts/graphcheck.py graphloops/graphs/research-loop.json scripts/research-record.py
bash graphloops/tests/run.sh
```

`graphcheck` は graph の形（依存の実在と循環・回す側が判定を出していない・検証器の欄が節の出力に現れる・穴が reads に宣言されている・回す側の writes が判定の欄に触れない・名前が engine か rules にある）を見る。`tests/run.sh` はそれに加えて、役の返答を台本で差し替えた模擬実行を端から端まで回す——research は収束・無人の停止・有人の諮り・軽量の打ち切り・拒むべき返答の拒否、review は連続 2 ラウンドの収束・前提不成立で人へ・保留の問いに帰属して人へ・答えを渡して続行・上限で停止・拒むべき返答の拒否（周の記録は本物の検証器 review-record.py にディレクトリ渡しで通す）。役の判断の質は見ない（それは実走）。

### pytest の置き場（graphloops/tests/py/）

関数を直に呼ぶ単体の検査は pytest に置く。依存は開発の間だけで、その場で入れる（プラグインの利用者の必須には足さない）。pytest-xdist の `-n` でプロセス単位に並べる（`-n` を外しても同じ柵が当たる）:

```bash
uv run --no-project --with pytest --with pytest-xdist python -m pytest -n auto graphloops/tests/py
```

**置き場の方針**: 単体の検査（関数を直に呼ぶ物）は、新しく書くなら、また既存の物を触るなら pytest に書く。bash の側から pytest へ移し終えた検査は、同じ変更で bash の側を消し、両方の件数の定数（bash の台本の `EXPECTED_CHECKS` ほかと、`graphloops/tests/py/conftest.py` の `EXPECTED_ITEMS`）と、その検査を当てにする変異の腕（`tests/mutations.json` の `tests`）を同じ変更で直す——ただし腕の実行器 `tests/mutate.py` はまだ bash の台本しか回せない（撃つ台本の表は `tests/run.sh` と `graphloops/tests/run.sh` の 2 本）ので、bash 側を消す最初の変更で実行器に pytest の口を足す。それまでは腕が pytest の写しでも落ちることを手で確かめる（今の `engine/schema.py` の腕 11 本は 2026-09-25 に全部落ちた）。盤面を端から端まで回す台本（`tests/simulate.py`・`tests/simulate_review.py`）を載せる土台は pytest の側に在る（下の「盤面を回す台本の土台」）が、台本はまだ移していないので、移すまでは今の置き場に足す（移す段で bash 側を消し、上の実行器の口も足す）。今の pytest 側の中身は `engine/schema.py` の検査（差し替えの版の重ね方 `test_graph_extends.py` を含む）と、`engine/role_run.py` の `unwrap`（役の標準出力を解く）の検査と、TDD の流れの赤・緑の判定（`test_review_tdd.py`）と、走らせるだけの節と宣言（`test_engine_run.py`）・人の方針の関所（`test_policy_gate.py`）・review-loop の rules の欠けた入力（`test_review_rules.py`）・engine の守りの口（`test_engine_guards.py`）・子を止める部品（`test_role_run_stop.py`）・盤面の loop の形（graph の `state_schema` を graphcheck が照らす・engine が保存の時に照らす。`test_state_schema.py`）の検査で、そのうち `test_schema.py`・`test_schema_graphcheck.py` は bash 側の同じ検査の写し（bash 側はまだ消していない。移し終えるまでは片方を直したらもう片方も直す——ずれを見る柵は無い）。

**盤面を回す台本の土台**（`graphloops/tests/py/glharness.py`。`conftest.py` が plugin として載せる）: 台本の本文（`Run`・`drive`・`check`・代役の claude）は写さず、台本のモジュールを import して使う。

- **2 つの口**（`--gl-driver=cli|inproc`、既定は cli）: cli は今と同じく子プロセスで `loop.py` を起こす。inproc は台本のモジュールの `subprocess` の名前を差し替え、`loop.py` を起こす `subprocess.run` だけを同じプロセスの `loop.cli()` に回す（`Popen` で起こす腕は子プロセスのまま——警告を出す）。inproc は呼ぶたびに engine の大域の状態（`glharness.RESTORED` の表: `util.GIT_CWD`・`role_run.LIVE`・検証器の読み込みの控え・`tempfile.tempdir`・signal の口・cwd・環境変数・標準入出力）を戻す。signal を触るので主スレッドでしか呼べず、並べ方はスレッドでなく pytest-xdist のプロセス単位
- **fixture**: `gl_script("review")`（台本のモジュールを選んだ口で返す）・`gl_run(kind, 名前, **Run の引数)`・`gl_check`（台本と同じ `check`・`skip` と、到達を記す `reach`）・`fake_claude`（代役の claude を PATH の先頭に置いた環境）・`gl_tmp`（一時の置き場の環境変数 TMPDIR を `tmp_path` に向ける——台本の作業場・engine の置き場・子プロセス・`parallel.rm` の基点が同じ所を見る。後始末は `tmp_path` に任せる）
- **check の数え方**: 行の形と数え方の正本は台本の `check`。pytest の側は各テストの前後で台本の件数と失敗の差を読み、失敗が 1 件でもあればそのテストを失敗にし、環境変数 GL_CHECK_LOG の置き場に `  FAIL <desc>` を 1 行ずつ足す
- **2 つの口の突合**（`test_harness.py` の `test_drivers_agree`）: 同じ筋書きを 2 つの口で回し、盤面（`state.json`・`record.json`・周の記録）を run の番号・時刻・作業場の根・所要・プロンプトの要約（本文が作業場のパスを貼る）で正規化して突き合わせる。所要は測って出すだけ（2026-09-26・負荷 100 前後で review の標準の筋書きが cli 354 秒・inproc 145 秒）
- **大きさの印**（Google の Test Sizes）: `small` は子プロセスとスリープを呼んだら失敗（握り潰しても失敗）。`medium` は子プロセス・git・盤面を回すテストで、手で撃つ mutmut は選ばない（`graphloops/setup.cfg`）。時間の上限と、落ちたテストの自動の再試行は入れない

**柵**（`graphloops/tests/py/fence.py`）: 飛ばしは失敗にする（テスト単位の skip・xfail と、モジュール丸ごとの skip・importorskip の両方）。集めたテストの数を `EXPECTED_ITEMS` と `!=` で突き合わせる——置き場のテストのファイルを全部集めた回だけで、パス・node id・`--ignore` などでファイルを絞った回は柵を外して、外した旨を 1 行出す（`-k` は集めた後で選ぶので柵は付いたまま）。台本の検査が走った件数を `EXPECTED_SIM_CHECKS` と、到達した値の数を `EXPECTED_SIM_REACHED` と `!=` で突き合わせる——全件の回で、しかも `-k`・`-m` で 1 件も選び外さなかった回だけ。`-n` の回は worker が数えた値を controller が集めて当てる（worker から届く node id の一覧では、テストを全部消したファイルが見えない）。CI は置き場を丸ごと回す。

**変更に関係するテストだけ回す道具（pytest-testmon）**: 使うなら手元の速回しだけで、commit 前と CI は全件。testmon はファイルを集めないので、上の柵はその回を「絞った回」と見なして外す。測った事実（2026-09-25、Python 3.14・pytest-testmon 2.2.0・coverage 7.16.1）: 設定のままでは rootdir（`graphloops/tests/py/`）の外にある `engine/` の変更を追わず、`schema.py` を壊しても 1 件も選ばなかった。`--rootdir=graphloops` にすると追うが、Python 3.14 の既定（coverage の `COVERAGE_CORE=sysmon`）では落ちるべきテストを選び漏らし、`COVERAGE_CORE=ctrace` で正しく選んだ。graph の JSON・プロンプトの変更には効かない:

```bash
cd graphloops/tests/py && COVERAGE_CORE=ctrace uv run --no-project --with pytest --with pytest-testmon python -m pytest --rootdir=../.. -c pytest.ini --testmon .
```

**変異テスト**: 差分から機械で作る腕（`tests/mutate.py --auto`）は、印の写しで行を通した台本だけで撃つ。どの台本が通したかは台本の土台 `parallel.py` が付ける印（台本を走らせるスレッドの名前と、印の写しの回だけ作業場の名前に挟む台本名）で見分けるので、子のプロセスは台本の作業場を cwd にして起こせば帰属する（作業場の外で起こした子は帰属できず、その腕は台本一式で撃つ）。手書きの腕（`tests/mutate.py` と `tests/mutations.json`）は、呼び出しを足す変異・デコレータ付きの関数・JSON・Markdown・シェルを狙う腕と、どの検査で落ちたかの突き合わせのために残す。pytest が覆うモジュールを丸ごと撃つのは既製の mutmut で、設定は `graphloops/setup.cfg`（鍵の名前は mutmut 3 の物で、2 系の `paths_to_mutate` などとは違う。版を固定して回す）。mutmut は作業用の写しを回した場所の `mutants/` に作り、前回の「殺した」結果を持ち越すので、**作業ツリーの一時の写しの上で、毎回新しく**撃つ（作業ツリーに `mutants/` を作ると、ファイルシステムを直に走査する `tests/run.sh` の柵がその写しまで数える）。Windows では動かない:

```bash
tmp=$(mktemp -d) && git ls-files -co --exclude-standard | tar -cf - -T - | tar -xf - -C "$tmp"
cd "$tmp/graphloops" && uv run --no-project --with mutmut==3.8.0 --with pytest mutmut run --max-children 4 && uv run --no-project --with mutmut==3.8.0 --with pytest mutmut results
```

`mutmut results` が挙げる生き残りのうち、実害のある物を pytest 側のテストで殺す。CI では回さない（生き残りの数で落とす形は作れず——文言だけの変異が残る——、報告だけのジョブは誰も読まない。落とす柵は手書きの腕の側に在る）。

## ループを足すには

1. `graphs/<loop>.json` に `exec: true` と `rules` を書き、各節に `prompt_file`・`schema`（か `text: true`）・`reads`・`writes` を足す。rules が盤面の loop（`b.loop_state`）に鍵を書くなら、鍵の名前を rules の `LOOP_KEYS` に、形を graph の最上位の `state_schema`（`type: object`・`additionalProperties: false` の JSON Schema。周ごとに名前の変わる鍵は `patternProperties`）に書く——graphcheck が両方をそろえ、loop を読む path を最後の欄まで照らし、engine は保存の時に照らして外れを `state.loop_drift` に残す（止めない）。写しだけの graph（`exec` 無し）は graphcheck の写しの形の検査だけ通ればよい。
2. `prompts/<loop>/` に節ごとのプロンプト。散文の手順書の「なぜ」を前書きに残す（指示だけに削ると、規律は守られても判断の質が落ちる）。
3. `rules/<loop>.py` に `init_record`・`FAN_OUT`・`WRITE_OPS`・`BUILTINS`・`POST_CHECKS`・`check_record`・`finalize`・`on_answer`・`on_unattended`・`on_stop`・`on_thickness`・`add`（要るものだけ）。人が途中で止める口（`loop.py stop`）で報告まで届かせるなら、graph の最上位に `stop`（止めた後に『済んだ』と見なす機械の節。下流に報告の節が要る——graphcheck が見る）を書く。
4. `tests/simulate.py` に台本を足す（台本はまだそこに在る。pytest の側の土台は台本を import して回せるが、移すのは次の段。関数を直に呼ぶ検査なら `tests/py/` に pytest で書く——上の「pytest の置き場」）。
5. `commands/<loop>-graph.md` は engine の呼び方だけ。

## 流れの一部を差し替えた版を足すには

同じループの一部の節だけを別の流れに差し替える版（例: 修正を TDD の流れにした `graphs/review-loop-tdd.json`）は、元の graph を写さずに差分だけを書く。最上位に `"extends": "<元の graph のファイル名>"` を書くと、engine（`engine/schema.py` の `load_graph`）が元の graph に RFC 7396（JSON Merge Patch）で重ねる: object は鍵ごとに重なり、`null` は鍵を消し、配列は置き換わる。

- 元は同じ置き場（`graphs/`）のファイルだけ。継いだ節の `prompt_file`・`rules` の相対パスが同じ置き場を基準に読まれるため。
- 差し替えの版の上にさらに差し替えの版を重ねてよい（`engine/schema.py` の `extends_chain`）。鎖は根元から順に重なり、後の段が勝つ。輪（自分を指すのも含む）は拒み、途中の段の誤りはその段のファイル名で言う。
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
