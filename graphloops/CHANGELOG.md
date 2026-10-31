# 変更の記録（graphloops）

graphloops の版ごとの、利用者に効く違いを新しい順に並べる。形は [Keep a Changelog 1.1.0](https://keepachangelog.com/ja/1.1.0/) に従い、版の番号は [Semantic Versioning](https://semver.org/lang/ja/) の形（x.y.z）で振る。節は Added（足した）・Changed（変えた）・Deprecated（やめる予定）・Removed（消した）・Fixed（直した）・Security（安全の直し）のうち、中身の有るものだけを使う。

版の出し方（この記録を書き足す段。git の tag は作らない）は、リポジトリのルートの `docs/releasing.md` に在る（プラグインとして入れた実体には無いので、clone か GitHub で見る: https://github.com/raiki61/claude-plugins/blob/main/docs/releasing.md）。0.19.0 以前の版はこの記録に無い。git の履歴の「版を上げる」の commit を見る。

## [Unreleased]

## [0.46.2] - 2026-10-31

### Fixed
- 利用者の動きは変わらない直し（試験だけ）。CI の Windows で欠けてよい能力の一覧（リポジトリの `.github/workflows/test.yml` と `mutation.yml` に書く物）に `posix-os` を足した。リポジトリのルートの `tests/run.sh` が、macOS と Linux だけで動く works-factory の試験を Windows で見送るときの名前。`tests/py/test_mutate_shard.py` は、mutation.yml の Windows の一覧が test.yml の物と同じ字かを見ていて、その見本の字（`WIN_ALLOW`）を同じ一覧にそろえた。

## [0.46.1] - 2026-10-31

### Fixed
- 利用者の動きは変わらない直し（試験だけ）。模擬実行の試験 `tests/simulate.py` の `test_answer_vocabulary` は、engine（graphloops の中核 `engine/`）が人に問いを出す前に、問いの選択肢に engine の扱えない語が無いかを確かめて拒むことを見る。そのために、試験は `rules/research-loop.py` の写しを書き換えて、選択肢に扱えない語 `halt` を入れる。0.46.0 の重複のまとめ（graphloops のコードで同じ中身が複数の所に写してあった物を 1 つの関数にした変更）で、選択肢の字 `["continue", "stop"]` が `_ask_decision` という関数の引数へ移った。そのため書き換えが何にも当たらず、選択肢は正しい語のままで、engine は拒まなかった。拒むはずと見ていた試験はそこで失敗し、main の CI が赤になっていた。書き換える所を `_ask_decision` の中の 1 か所（上限に達したときの問いも、収束していないときの問いも、ここで選択肢を組む）に替えた。その 1 か所が見つからないときは、試験がその旨を出してすぐに失敗する。

## [0.46.0] - 2026-10-30

### Changed
- 利用者の動きは変わらない直し（コードの簡潔化。このリポジトリの持ち主の 2026-10-30 の頼み「気になるとこに並列でsimplifyかけまくっていって」）。engine（graphloops の中核のモジュール群 `engine/`）で、同じ中身のコードが複数の所に写してあった物を 1 つの関数にまとめた。主な物は次のとおり。役を `claude -p` で起動するコマンドの組み立てで、コマンドの雛形の差し込み先（`{prompt_file}` などの置き換える欄）に入れる値を作る処理と、役への指示文を盤面の `roles/` に書き出す処理（`advance.py` の `launch_holes`・`write_role`）。起動してよいコマンドかを確かめて拒む検査のうち、コマンドの頭の形・`--resume` の値・標準入力に渡すファイルの 3 つ（`commands.py` の `_prefix_refusal`・`_resume_ids`・`_stdin_refusal`）。盤面の `trace.jsonl` に 1 行足す処理（`util.py` の `append_trace`。`commands.py`・`children.py`・`runner.py` の 3 か所を置き換えた）。loop.py を親から切り離して起動する 3 か所（`runner.py` の `_spawn_loop`）。子のプロセスを孫まで止める後始末（`role_run.py` の `_kill_or_say`）。`rules/review-loop.py`・`rules/research-loop.py`・`scripts/graphcheck.py`・`scripts/gl.py` の写しもまとめ、使っていない import と、別の枝と同じ中身の分岐を消した。画面や記録に出す文・JSON の形・終了コードは変えていない。違いは 1 つで、`runner_launch_spec` が役を起動せずに返るとき、空の `roles/` フォルダを作らなくなった（engine にも利用者にも、このフォルダが在るかを見る所は無い）。
- `skills/research-graph/references/rules.md` の「人の方針」の段を消した。同じ中身が `references/policy.md` に在り、SKILL.md もそちらを指している。

## [0.45.5] - 2026-10-29

### Fixed
- 利用者の動きは変わらない直し。`tests/py/test_intake.py` の `test_claude_drift_compares_the_claude_on_path_with_the_pinned_version` の Windows での見送りの理由が「SKIP <能力>:」の形でなく、飛ばしが失敗に数えられて main の CI の windows の pytest が赤だった。理由をほかの試験と同じ `SKIP posix-mode:` の形にした（`posix-mode` は CI の Windows の欠けてよい能力の一覧に在る）。

## [0.45.4] - 2026-10-29

### Fixed
- 利用者の動きは変わらない直し。変異テストの道具 mutmut は、試験を graphloops の一時の写し（`mutants/`）の中で走らせ、写しには `setup.cfg` の `[mutmut]` の `also_copy`（一緒に写すファイルとフォルダの一覧）に書いた物と mutmut が決まって写す物（`setup.cfg` など）だけが入る。この一覧に `README.md` が無く、README の見出しを読む試験（`test_the_notices_point_at_a_readme_section_that_names_the_live_check`）が写しの中で README を見つけられずに落ち、main の CI の変異テスト（mutmut の job）が赤だった。一覧に `README.md` を足した。一覧の抜けを手元の試験で止める `tests/py/test_mutmut_config.py`（graphloops 直下に在る物が、一覧か、試験の中の「試験が読まない物」の表（`NOT_READ`）のどちらかに載っているかを見る）は、これまでフォルダだけを見ていたので README.md の抜けを止められなかった。直下のファイル（今は `README.md`・`CHANGELOG.md`・`setup.cfg`）も見るようにした。

## [0.45.3] - 2026-10-29

### Fixed
- 利用者の動きは変わらない直し。消す口（`shutil.rmtree`）に届いてよい所の表（`tests/py/test_harness.py` の `RMTREE_ALLOWED`）に、リポジトリのルートの `scripts/works-factory-pin.py` の `land_pin`（同じ関数が `mkdtemp` で作った一時の置き場を finally で消す）を足した。表に無いので `test_rmtree_is_reached_only_from_named_sites` が落ち、main の CI が赤だった。

## [0.45.2] - 2026-10-26

### Fixed
- `hooks/run-python.sh` が、`python3`・`python` の後に版の付いた名前（`python3.20` から要る版の `python3.12` まで新しい順）も試すようにした。uv で入れた Python は `python3.14` のような版の付いた名前でだけ PATH に在り、PATH の `python3` が macOS 付属の 3.9 のとき、入っているのにフックとコマンドが「入れる」と言って止まっていた。止まるときの 1 行には、入っているのに PATH に無いときの直し方（入れた場所を PATH に足す）を足した（docs/standards/cross-os.md の決まり 1）。

## [0.45.1] - 2026-10-26

### Fixed
- README の「Installation」に、シェルの `claude plugin install` だけで入れる機械では、先に `claude plugin marketplace add anthropics/claude-plugins-official` を打つことを足した（依存の convergence-loops が公式の marketplace の `pr-review-toolkit` に依存していて、登録が無いと両方とも読み込まれない）。

## [0.45.0] - 2026-10-26

### Changed
- 利用者の動きは変わらない直し。review-loop の周の締め（`rules/review-loop.py` の `_converge`）で、周を止めて人に諮るときの問いの頭を、止める訳ごとの表 `STOP_QUESTION` から引くようにした。以前は `premise_escalate` とそれ以外の 2 通りで書き分けており、convergence-loops の検証器の `STOP_KEYS` に訳を足すと、足した訳の問いが関係のない `work_exhausted` の文になった。`STOP_QUESTION` に文の無い訳は、検証器（`convergence-loops/scripts/review-record.py`）の表 `STOP_KEYS` に訳ごとに書かれた文で聞く。

## [0.44.0] - 2026-10-26

### Changed
- 利用者の動きは変わらない直し。`rules/review-loop.py` の止める訳の分岐が、検証器（`convergence-loops/scripts/review-record.py`。以下 `V`）の止める訳の表 `STOP_KEYS` のキー 2 つ（`premise_escalate`・`work_exhausted`）を文字列で書き写していたのを、`V.STOP_KEYS` から読む形にした。表にキーを足したときに、写した側だけ古く残るのを防ぐ。

## [0.43.0] - 2026-10-26

### Changed
- 利用者の動きは変わらない直し。engine と rules から、どこからも読まれていない名前を消した（`rules/review-loop.py` の `collections` の import と `LANE_HANDLED`、`engine/record.py` の import の `takes_view`、`rules/research-loop.py` の finalize の中の `ls`）。research-loop の graph の `vocab_owner` に、厚みなどの語の一覧（THICKNESS / DECIDERS / GATE_VERDICTS）が convergence-loops の `scripts/record_common.py` に移ったことを書き足した。

## [0.42.1] - 2026-10-26

### Fixed
- Windows で、Python を python.org の入れ方などで入れ、`python3` の名前が Microsoft Store へ誘う代わりの物（起動すると案内を出して終わる物）に当たる機械では、読了の記録のフック（`hooks/record-read.py`）が Read のたびに落ち、`/research-graph` と `/graphloops:intake` の手順書のコマンドも落ちていた。どれも素の `python3` を起動していたため。
  - 新しい `hooks/run-python.sh` が、`python3`・`python`・`py -3` の順に、実際に起きて 3.12 以上の物を選んで起動する（works-dispatch の `hooks/run-python.sh` と同じ選び方）。フックの登録、手順書のコマンドの行、engine が会話に出す次の手（init の `next` と、intake の知らせのコマンド）を、この入口を通す形にした。
  - 選べなければ、訳と直し方（Windows の「アプリ実行エイリアス」で代わりの物を切る）を 1 行で出す。フックでは、この知らせを会話ごとに 1 回だけ出す。

## [0.42.0] - 2026-10-19

### Changed
- claude の形（graphloops が子の claude を起動するときに頼るオプション・設定のキー・返す JSON のフィールド）の確かめ方を、README のセクション「When the claude version changes」1 か所に置いた。graphloops が利用者に出す次の 3 つの知らせは、確かめのコマンドを書かず、このセクションを指す（何を打つかはそのセクションに書いた）: `loop.py init` が出す、手元の claude の版が engine を確かめた claude の版と違うという知らせ（0.41.0 で足した物）、`loop.py status` と run の報告の費用（`cost_usd`）の `unknown.why`（engine が読むフィールドが claude の出力に無かったときだけ出る）、`scripts/quality-ledger.py` の「claude の出力の包みに engine が読むフィールドが無い行」。
  - 理由: 確かめのコマンドは、graphloops を開発するリポジトリ claude-plugins の検証のツール（`tests/` の下のファイル）で、そのリポジトリの clone でしか動かない。claude-plugins の決まりで、engine とスクリプトの中の文字列と、役（子の claude）が読む文には、claude-plugins の検証のツールの名前（`tests/` の下のファイルのパスなど）を書かない（claude-plugins の直下の `tests/run.sh` のチェック。README は人が読む説明なので書いてよい）。知らせの文がそのファイルのパスを書いていたので、main の CI が赤だった。

### Fixed
- 利用者の動きは変わらない直し。main の CI で赤だった次の 3 つを直した（はじめの 2 つは試験だけの直し）。
  - `test_delegate_fence.py` の 1 本が、claude（Claude Code のコマンド）が PATH に無い機械（CI）で落ちていた。engine は claude を PATH で探し、見つからないと起動の指定に「claude が無い」印（`missing`）を付ける。この試験はその印が無いことも確かめていたので、試験の中で PATH の探しを差し替え、claude が見つかったことにしてから確かめる形にした（見つからないときの印は別の試験が見る）。
  - `test_review_rules.py` の 1 本が、Windows だけで落ちていた。試験が置く代わりの検証器が、和文を既定の文字コード（cp1252）で書こうとして落ちていた。本物の検証器と同じく、標準出力を UTF-8 にしてから書く形にした。
  - `scripts/graphcheck.py` が、遮断系の役（ツールを持たない役）の起動の種類（kind）の名前 2 つ（`isolated`・`isolated_read`）を手で並べていた。`engine/launch_words.py` に `ISOLATED_KINDS` を置き、そこから読む形にした（engine の表に在る名前をほかの所で文字列で並べ直すと、表に名前を足したときに並べた側だけ古く残るので、claude-plugins の直下の `tests/run.sh` のチェックが赤にする）。

## [0.41.1] - 2026-10-19

### Fixed
- 開発の側の直しで、graphloops を使う側の振る舞いは変わらない。graphloops の試験は、古い形の台本（`tests/simulate.py`・`tests/simulate_review.py` の関数。engine を順に呼んで結果を確かめる）を、層 2 の筋書き（`tests/py/scenes.py` の形。engine への呼び出しを「出来事の列」〔以下、列〕としてデータに書き、回し手が打つ。規範はリポジトリのルートの `docs/adr/0067-test-migration-layer2-and-removal-conditions.md`）へ移している。手で起動する CI の `.github/workflows/cover-moved.yml` は `graphloops/tests/py/cover_moved.py` を回し、移した後も能力が落ちていないかを 3 段で確かめる。cover の段は、古い台本が通った行を列の試験も通るか（被覆の包含）を見る。timing inproc と timing cli の段は、古い台本の Run（engine の 1 回の実行）と、同じ Run の列を打った結果の盤面（`state.json` などの実行の記録）を突き合わせる。古い台本が engine を同じプロセスで呼ぶか（inproc）、子プロセスで呼ぶか（cli）で 2 段ある。この 3 段が、初めて回した 2026-10-18 に全部赤だった（https://github.com/raiki61/claude-plugins/actions/runs/39173245893 ）。突き合わせは緩めずに、次の 5 つを直した。
  - 列の init を、古い台本の Run と同じ run_id で打たせる。research-loop（graphloops の調査のループ）が抜き取りに使う乱数の種は run_id から作る。起動した秒が違うと抜き取る id が割れていた。
  - プロセスで 1 度だけ走る行（検証器の読み込みなど）は、最初に走った台本の手柄になる。そこで台本ごとの包含からは外し、全体の包含で見る。
  - Linux の GNU readline は、C の環境に環境変数 COLUMNS・LINES を書く。それを外す。cli の子がこれを継ぎ、検査結果の控えのハッシュ（指紋）が割れていた。
  - 列が渡すファイルの書き方（非 ASCII の文字を \uXXXX に逃がすか・中身）を、古い台本と同じにする。
  - 止まった run の列の名前を、古い台本の Run の名前（`stop-early-standard`・`stop-early-heavy`）にそろえる。古い台本の側は、厚み〔run の重さの段階〕の値が ASCII になった時に名前が変わっていた。

## [0.41.0] - 2026-10-19

### Added
- `loop.py init`（graphloops の run〔ループの 1 回の実行〕を始めるコマンド）が、手元の claude の版（`claude --version` の出力）を、graphloops の作者が確かめた claude の版と比べ、違えば `注意:` で始まる行で知らせる。作者が確かめたのは、graphloops が claude を起動するときに頼る形——オプション・設定のキー・`claude -p --output-format json` が返す JSON のフィールド——で、確かめた版は `graphloops/tests/py/cli/versions.json` に書いてある。確かめた版は、作者が見本（claude のヘルプの全文と、ログインしていない回に返る JSON。`python3 graphloops/tests/py/cli_contract.py --capture` で採る）を採り直すときに書き換わる。
  - 知らせには、確かめのコマンド `python3 graphloops/tests/py/cli_contract.py --live` を添える。これは、graphloops を含むリポジトリ claude-plugins の clone のルートで打つ。確かめるのは clone の側の graphloops なので、知らせの行には、今の run が使っている graphloops の版も出す。先に clone を、その版の graphloops が入った commit に切り替えておく。このコマンドは手元の claude を、資格情報の無い空の設定のフォルダ（`CLAUDE_CONFIG_DIR`）を渡してログインしていない状態にしたうえで、graphloops と同じオプションで起動する。そして、オプションと設定が受け付けられるか・返る JSON の形が見本と合うかを見る。ログインしていない claude も、`is_error` が真で `result` が「Not logged in」の JSON を、ログインした回と同じフィールドの形で返す。見本の JSON もログインしていない回に採った物なので、同じ条件で形を比べられる。ログインしていない claude は API を呼ばずに返すので、利用の費用は掛からない。
  - clone を持たない利用者向けに、知らせの行は別の道も示す。`loop.py intake --what '<1 行の説明>'` を打って、engine（graphloops のループを回す本体。`scripts/loop.py` と `engine/`）の失敗の記録（`intake.jsonl`）に 1 行を足し、その記録を、`init` が出す手順に沿って作者へ渡す道。
  - 止めずに知らせるだけにした。claude は自動で更新され、版が違っても多くはそのまま動くため。
  - 比べるのは、Claude Code がプラグインを入れた置き場（`~/.claude/plugins/cache/` などの下）から graphloops が走るときだけで、git の clone から直に走らせる試験・開発のときは比べない。claude が PATH に無いときも知らせない（そのときは graphloops が claude を起動する所で失敗するので、そちらで分かる）。
- 宣言した検査の一式（`.review-checks.json` の `suite`）が全て通った（緑だった）結果を使い回すキャッシュ（`.git/graphloops/checks-cache/`）に、保存期間の上限（7 日）を付けた。今までは上限が無く、記録が溜まり続けた。
  - 書いてから 7 日を過ぎた記録は使わずに、検査を回し直す。キャッシュを使わなかった訳は、盤面（run ごとの状態を置くディレクトリ）に置く、検査の一式を回した段（段はループの 1 つの手順）の控え `cache.json` の `causes` に、キー `old`（記録が 7 日より古い）として残る。
  - キャッシュを使えずに一式を実際に回し終えるたびに（結果が緑でも赤でも。キャッシュを使った回は片付けない）、7 日を過ぎた記録と、同じ置き場に残った一時のディレクトリ（書きかけの記録の `.tmp-` と、壊れた記録の `.broken-` で始まる物）を消す。
  - 使われなくなったリポジトリの置き場は誰も片付けないので、要らなければ `.git/graphloops/checks-cache/` を丸ごと消す。

### Fixed
- 開発の側の直しで、graphloops を使う側の振る舞いは変わらない。main で落ちていた pytest の試験 2 本を直した。
  - `graphloops/tests/py/test_agent_frontmatter.py` の、linked worktree（`git worktree add` で足した作業ツリー）の `.git` ファイルに相対の `gitdir:` が書かれた場合の試験。読了のフック（`hooks/record-read.py`。ループの段を受け持つエージェントが読んだファイルを、いま回っている run の盤面に書く Claude Code のフック）は、commit da5c0619 の直し（0.39.0 に入った）で、まだ終わっていない run（盤面の `state.json` の状態で見分ける）の盤面にだけ書く形に変わった。ところが試験は `state.json` の無い盤面を置いたままだったので、フックがその盤面に書かず、試験が落ちていた。試験が `state.json` に状態「回っている」（`running`）を書くように直した。
  - `graphloops/tests/py/test_ledger.py`。この試験は、`graphloops/tests/py/MIGRATION.md` の表が今のコードと合っているかを見る。MIGRATION.md には、bash の側の試験の台本から pytest へ移した検査の表（`<!-- ledger:begin -->` と `<!-- ledger:end -->` の間。機械で作る）があり、元の検査が在った `graphloops/tests/simulate.py` の行番号を載せている。その行番号が古いままだったので落ちていた。`python3 graphloops/tests/py/ledger.py` で表を作り直した。

## [0.40.0] - 2026-10-19

### Removed
- `/review-graph` のスキル（`skills/review-graph/`）を消した。2026-11-18 以降に消す予定だったのを、持ち主の答え（2026-10-19「もう退役して置き換えていいよ。」「またずにいますぐ退役してよい。」「以降はarchiveでメンテ不要」）で早めた。代わりは `/works-factory`（同じ marketplace の works-factory プラグイン）。消した後の `/review-graph` は保守しない。最後の形は commit 58c6d08b で、https://github.com/raiki61/claude-plugins/tree/58c6d08b/graphloops/skills/review-graph で開ける（使うなら、その commit の graphloops を自分で入れる）。`/research-graph` と engine（グラフを読んで段を順に回す機械。`scripts/loop.py` と `engine/`）と、engine の試験の材料の review-loop のグラフ（`graphs/review-loop*.json`）・rules・prompts・blocks は残す。人の方針（利用者が書く、どの run にも効く決まりの文書。例: 今ある能力を減らさない）の置き場と届き方の説明は `skills/research-graph/references/policy.md` へ移した。訳と手順はルートの `docs/adr/0075-retire-review-graph.md`（https://github.com/raiki61/claude-plugins/blob/main/docs/adr/0075-retire-review-graph.md ）。

## [0.39.1] - 2026-10-19

### Fixed
- 開発の側の直しで、graphloops を使う側の振る舞いは変わらない。変異テストのツール mutmut（engine のコードをわざと壊した版を作り、試験が落ちるかで試験の強さを測る。CI の `.github/workflows/mutation.yml` の mutmut の job で週 1 回撃つ）が、2026-09-28・10-05・10-12 の 3 回とも、試験を集める所で落ちて 1 本も撃てていなかった。mutmut は graphloops/ の中身のうち、設定ファイル `graphloops/setup.cfg` の `also_copy`（写しに一緒に写す置き場の一覧）に並べた物だけを写し（`graphloops/mutants/`）に写して試験を走らせる。graph（ループの段とつなぎを書いた JSON）は `$ref`（別のファイルの定義を指す参照）で `blocks/` を指すが、`blocks/` が一覧に無く、写しの中で graph が読めなかった。`also_copy` に `blocks/` を足した。あわせて、写しの中でもリポジトリのルートと、同じリポジトリに並ぶプラグイン convergence-loops（graphloops の試験が使う、役の定義と記録の検証器を持つ）を見つけられるように試験を直した。同じ壊れ方が戻らないように、試験 `graphloops/tests/py/test_mutmut_config.py` を足した。この試験は、試験が読む置き場が `also_copy` に無いときと、試験がリポジトリのルートを graphloops の 1 つ上と決め打ちしているときに落ちる。ふつうの pytest の実行で落ちるので、CI の mutmut を待たずに気づける

## [0.39.0] - 2026-10-19

### Added
- 子の claude（engine が `claude -p` で起動する claude）に足す認証を Keychain の項目から読んだとき、その項目のトークンの切れる日が近い（30 日前から）か過ぎていれば、`loop.py next` の `notes`・`loop.py status` と `loop.py run` の出力の `auth_expiry`・`loop.py launch` の行の `auth.expiry` に、作り直し方（`claude setup-token`）と一緒に出す。トークンは書き換えた日から 1 年で切れる見込みとして数える。認証を足す前置の層（`scripts/with-auth.py`）も標準エラーに同じ 1 行を出す。

### Fixed
- `--output-format json` で起動した子が、JSON でない短い 1 行（認証切れの「Failed to authenticate…」や使用枠の上限の 1 行。どちらも終了コード 0 で返る）を返したとき、その 1 行を返答として受け付けていた。受け付けの検査が緩いノードでは、済んでいないのに済に見えた。今は失敗に数え、`loop.py launch` の行の `cause` を `launch_short_line` にして、`why` に出力の頭を添える（認証切れと決めつけない）。

## [0.38.1] - 2026-10-19

### Fixed

- claude の起動の形を確かめる台本（`tests/py/cli_contract.py`）が、Windows で claude の出力を既定の cp1252 で読み、日本語を書くと落ちうるので、子の出力を UTF-8 で読み、自分の標準出力も UTF-8 に直す。

## [0.38.0] - 2026-10-19

壊れても誰にも知らせが来なかった所を、ループを回している人に見える形にした（ルートの `docs/standards/breakage-detection.md` の決まり 1「ログに書くだけは知らせではない」・3「外の形に頼る所は、実物から採った見本で試験し、知らない値を起動時に知らせる」・4「入っている版とずれた物を見つける」・5「足し続ける物は、上限か片付けの持ち主を決める」に合わせた）。この節の語: engine はループを回す本体（`scripts/loop.py`）、run はループの 1 回の実行、盤面は run ごとの状態を置くディレクトリ（`$(git rev-parse --git-dir)/graphloops/<ループ>/<run の番号>/`）、作者は graphloops の作者。

### Added
- `loop.py init` と `loop.py status` が、engine の失敗の記録（`intake.jsonl`）のうち、まだ作者へ手渡していない行の件数・一番古い日・多い種類・ファイルの場所と、書き出すか既読にする打ち方を出す。これまでは書くだけで読む所が無く、作者の手元の Claude Code の 3 つのアカウントに 68 行が誰にも渡らずに溜まっていた。既読にする口 `loop.py intake --seen`（`/graphloops:intake seen`）を足した。既読にしても行は消えず、`intake.jsonl` に残る（次の `init`・`status` から数えないだけ）。記録は 1,000 行までにし、超えたら古い行から捨てる（捨てた行の数も知らせに出る）。
- `loop.py init` が、Read の記録のフック（`hooks/record-read.py`。Claude Code の Read の後に走り、何を読んだかを盤面に書く）が、`hooks/hooks.json` に登録した形のまま動いて、この run の盤面を見つけて行を書けるかを確かめ、だめなら `init` の出力の JSON の `notes`（利用者への知らせの欄）と標準エラーで知らせる。盤面の置き場を `--dir` で決めた run では確かめない（フックは既定の置き場の盤面だけを探すため）。
- 盤面が linked worktree（`git worktree add` で足した作業ツリー）の git の置き場（`<共有の git ディレクトリ>/worktrees/<名前>/`）に在るときは、`init` と `status` が「`git worktree remove` で盤面も消える」ことと、消す前に盤面を共有の git ディレクトリ（`<共有の git ディレクトリ>/graphloops/boards-archive/`）へ写す `cp -R` のコマンドを出す。
- 子の claude（engine が `claude -p` で起動する claude）の JSON の出力に、engine が読むフィールド（`total_cost_usd`・`session_id`・`subtype`・`is_error`・`permission_denials`）が無いときは、盤面の `trace.jsonl` のその子の行に欠けたフィールドの名前（`missing`）を残し、費用の集計（`status` と、run の最後に出る報告）の `cost_usd.unknown` に出す。これまでは費用を黙って 0 と数えていた。
- `scripts/quality-ledger.py` が、試験結果の控え（checks-cache）の当たりの率と外れの訳、読み通しの検査（research-loop で、資料を読む役（engine が起動する子の claude）が資料を最後まで読んだかを先頭・中間・末尾の標本で確かめる検査）が成り立たなかった数、子の出力に欠けたフィールドの数を、版ごとに出す。
- 試験: graphloops が `claude` に渡すオプション（`--output-format` などの旗）とその値・設定のキーと、読む出力のフィールドを、実物から採った見本（Claude Code 2.1.303 の `claude --help` と `claude -p --output-format json` の出力。`tests/py/cli/`）と照合する。claude を入れ替えたら `python3 tests/py/cli_contract.py --live` で入っている claude と照合し、要れば `--capture` で見本を採り直す。

### Changed
- 試験結果の控えの照合の鍵（指紋）から、会話ごとに変わる環境変数を外した。端末・接続・会話ごとの識別子（`HERDR_PANE_ID`・`TMUX_PANE`・`SSH_CONNECTION`・`CLAUDE_CODE_SESSION_ID` など。全部の名前は `engine/checks_cache.py` の `IGNORED_ENV`）は鍵に入れず（試験のコマンドには渡す）、`CLAUDE_CODE_EXECPATH`・`AI_AGENT`・`CLAUDE_JOB_DIR`・`__MISE_*` は試験のコマンドに渡さない（渡さないので、鍵から外しても違う環境の結果を使い回さない）。`PATH` は並びの順や重複でなく、コマンドがどこで見つかるかで比べる。控えの形の版を 3 に上げたので、前の控えは当たらない。外れたときは、同じ作業ツリーと手順の控えとの違う環境変数の名前（値は出さない）か、作業ツリーや手順が違うことを出す。
- graphloops が自分の検査の部品（validator・役の定義など）を引く版を選ぶとき、`plugins/cache` のフォルダ名の大きい物でなく、Claude Code の `installed_plugins.json` の `installPath` を読む。消す印 `.orphaned_at` の付いた場所は使わない。台帳でプロジェクトの範囲（scope が `project` か `local`）の行が別の版を指すリポジトリでは、その版を使う。台帳（`installed_plugins.json`）から決まらなければ止めて訳を出す。

### Fixed
- Read の記録のフックが、止めた run と、収束して（結果が変わらなくなって）終わった run の盤面にも書いていた（止まった後に、関係の無い会話の行が 1,310 行書かれていた）。動いている run にだけ書く。

## [0.37.0] - 2026-10-19

### Changed

- **convergence-loops 0.50.0 以上が要る**（`dependencies` の下限を上げた）。下の 2 つが、convergence-loops の検証器 `review-record.py` と `comment-ratio.sh` に足した `--json` を呼ぶため。古い convergence-loops のままだと、周の記録が検証器を通らずに止まる。
- review-loop の周（レビューと直しの 1 回分）の行き先の 4 つ（収束する・仕事が残る・前提不成立で止める・答え待ちで止める）を、`review-record.py --json` が返す `stop`（ASCII のキー）で決める。答え待ちで止めるのは、残る阻害（収束を止める指摘）がどれも人への問いの答え待ちで、答えを待たずに進められる仕事が無いとき。前は人向けの出力から止める訳の文言の行を探しており、文言を直すと黙って「仕事が残る」に倒れた。`stop` が無い・知らないキーのときは、周を進めずに訳を返す。graph の `record.validator_output` が `json` のとき、engine は検証器に `--json` を渡す。
- review-loop の書いた行の割合の数（`scalars`）を、`comment-ratio.sh --json` から読む。数でない値・知らないキーを黙って捨てていたのをやめ、要る値（added_lines・comment_lines）が欠けたら数を書かずに訳を残す。数えられなかったファイル（`unmeasured`）が在れば、数は書いたうえで訳にも残す。
- 前の周の判定を据え置いたレビューの行の印を、reason の末尾の添え書きでなく `held_from`（据え置いた元の周の番号）のフィールドで持つ。`held_from` の無い前の版の記録だけは、今までどおり末尾の添え書きで見分ける（版を上げる前に始めた run を続けるときと、品質の台帳 quality-ledger.py が過去の記録を数えるとき）。
- 修正の後のレビュー（R4）が人に問う行（消えた能力と、人の方針とのぶつかり）のうち、人が前に通した行を、モデルが写した文の一致でなく `same_as`（前に人に問うた行の ID）のフィールドで見分ける。R4 の返答の 2 つの配列（`capability_inventory.lost`・`policy_conflicts`）の要素は文字列から `{text, same_as}` の object にした。前の版の返答（要素が文字列）と `same_as` の無い行は、もう一度人に問う（安全な側）。
- グラフ（`graphs/*.json`）とブロック（関係するノードをまとめた部品）の出口（ほかのブロックが読む出力）の schema の、選んで書く値（列挙）を日本語の語から ASCII のキーに変えた（docs/standards/machine-readable-values.md の決まり 3）。例は、厚み 軽量/標準/重厚→light/standard/heavy・決めた人 依頼者指定/既定→requester/default・反証の判定 確証/反証→confirmed/contradicted・事実の種類 実測/仮説→measured/hypothesis・目的の出典 PR 説明→pr_description・再燃の原因 規約→convention。プロンプトはキーを書くよう指す。人に見せる文言は表示の語の表（research-loop の `thickness.labels`）から引くので、止まる理由などの文は変わらない。`loop.py init` の `--thickness`・`--decider` と `thicken --to` は、キーと表示の語のどちらでも受ける。前の版の語で書いた盤面（engine が run の状態を置くフォルダ）・記録は schema に通らない。
- engine が起動する役の返答を、`--json-schema` でノードの schema を渡し、包みの `structured_output` で受けるようにした（engine だけが読む `note`・`x-reducer`〔盤面の状態のキーごとの合わせ方〕は外して渡す）。schema の無いノードと背景の任せ先（周〔レビューと直しの 1 回分〕と並べて背景で走らせる、`delegate.background` が真のノード）は今までどおり `result` で受ける。`--json-schema` で起動したのに `structured_output` が無い回は、`result` に倒さずに読めない理由で止める。
- 起動する語（役を `claude -p` で起動するときのコマンドの引数の並び `argv`・同じ会話を再開する語 `resume`・認証を足してから起動する前置の層 `scripts/with-auth.py` を通す指定）を graph から外し、engine の `engine/launch_words.py` の 1 か所に置いた。チェックの許可表も同じ所から組む。graph の `launch.<形>`（形は起動する子の種類で、ツールゼロの `isolated`・ツールつきの `tooled` など）は前置きの文・モデルなどだけを持ち、`argv`・`resume`・`via`（前置の層を通す指定）を書くと graphcheck（graph の形の検査）が落とす。
- 前置の層（`scripts/with-auth.py`）は、足した認証の段を環境変数 `GRAPHLOOPS_AUTH_NOTE` が名指すファイルに JSON で書く。engine の `launch` の行の `cause` はこの段で決め、標準エラーの文は読まない。行に `auth`（段。読めなければ null）を足した。
- sandbox の確かめの子の返答も `--json-schema` で受け、sandbox が有効になったかを決めるとき、sandbox の初期化の失敗の文を探す先を、返答の `error` のフィールドと子の出力だけにした。

### Added

- graphcheck が `thickness.labels` を検査する。キーは厚みの段と decider の値ちょうどで、表示の語は空でなく、重ならず、キーとかぶらない。

### Fixed

- 役の定義（agents/<役>.md）の frontmatter を、YAML のブロックの形のリスト（`tools:` の次の行の `  - Read`）でも読むようにした。前は 1 行の形しか読めず、ツールの一覧が空になって役が黙ってツール無しで起動した。読めない形の frontmatter は止まる。
- loop.py run の回し手（ループを回すプロセス）は、自分が起動した launch ごとに、どの試行を起動したかを書いたファイル（盤面の `runner-launch/<pid>.json`）を置く。前は、このファイルが壊れていると黙って待ち続けるか、ファイルを消して先へ進み、中の試行を誰も拾い直さなかった。今はファイルを残し、訳を添えて `stuck` で終わる（ファイルを確かめて消してから run を打ち直す）。loop.py run が最後に出す JSON は、読めなかった record.json・runner.json を `unreadable` に出す。
- 並行 PR の数え（review-loop の p0.parallel_pr）が、変更ファイルが 100 件を超える PR で一覧を黙って切っていたのを、全部を読み、読み切れなければ確かめられなかったと返すようにした。
- 読み記録のフック（hooks/record-read.py）が、linked worktree の `.git` の相対の `gitdir:` を解くようにした。

## [0.36.0] - 2026-10-19

### Deprecated
- `/review-graph` を退役させる。早くて 2026-11-18 に消す（代わりの works-factory に、移った人が止まる不具合が残っていれば延ばす）。代わりは `/works-factory`（同じ marketplace の works-factory プラグイン。`/plugin install works-factory@raiki61` で入れる）。`/research-graph` と engine は残す。この版から、`/review-graph` を呼ぶと最初にこの予告が出る（`skills/review-graph/SKILL.md` の頭と description）。消した後も最後の形は git の履歴で開ける。消すときに、最後の形の commit をこの記録の Removed に書く（git の tag は作らない）。理由と消す手順は、リポジトリのルートの `docs/adr/0075-retire-review-graph.md`（プラグインとして入れた実体には無いので、clone か GitHub で見る: https://github.com/raiki61/claude-plugins/blob/main/docs/adr/0075-retire-review-graph.md）。

## [0.35.0] - 2026-10-19

### Added

- 共有の認証の部品 `scripts/claude_auth.py`（ルートの scripts/claude_auth.py の写し。プラグインが別の claude を `claude -p` で起動するときに、その claude に認証を足す部品）に、関数を 2 つ足した。足したのは、トークンが切れたときに、起動した claude が黙って失敗し、起動した側がそれを「済んだ」と数えるのを防ぐため。この版では呼ぶ所が無く、利用者から見た動きは変わらない。呼ぶ所は、claude を起動する処理を持つプラグインの担当が後の版で足す。
  - `expiry_note(項目の名前)`: 利用者が Keychain（macOS の資格情報の保管庫）に自分で入れたトークンが、入れた日から 335 日を過ぎていれば、作り直しを促す 1 行を返す。過ぎていなければ None。このトークンは `claude setup-token`（CI などで使う長持ちのトークンを作る Claude Code のコマンド）で作る物で、寿命は 1 年。
  - `auth_failed(出力)`: 起動した claude の標準出力が認証の失敗の形なら真を返す。真になるのは 2 つ: 300 バイト以下の 1 行で JSON として読めない文と、JSON の結果のうち `is_error`（失敗の印）が真で `result`（返答の文）に authenticate か /login を含む物。複数行の文・300 バイトを超える文・失敗でない JSON は偽。認証の切れた claude は、この形の文を出して終了の値 0 で終わり、終了の値では見分けられないため。

## [0.34.0] - 2026-10-19

### Changed
- review-loop の判定者（judge）に渡すプロンプト `prompts/review-loop/p2.history.md` で、原因の意味で使っていた「根」を「根本原因」に、「枝」を「ユニット」に書き換えた。1 行目には、初見読みの検査（gates の coldread）を飛ばす印を足した。このファイルは判定者に渡すひな形で、読むのはエージェントと保守する人だけのため。判定者への指示の中身は変えていない。

## [0.33.1] - 2026-10-19

### Fixed
- `/review-graph` のスキルの本文（`skills/review-graph/SKILL.md` の、先頭の設定の行を除いた部分）を 5,000 字以下に縮めた。このリポジトリでは、スキルの本文は 5,000 字以下と決めていて（`docs/standards/skill-authoring.md` の決まり 1）、自動の試験が 5,000 字を超えた本文を失敗にするため。振る舞いは変えていない。

## [0.33.0] - 2026-10-19

### Changed

- 前の版で置き換えずに残した 6 本（research-graph の SKILL.md と、review-graph の references の flows.md・policy.md・runnerless.md と、review-loop のプロンプトの p2.history.md・report.md）も IT の定着語に置き換えた。振る舞いは変えていない。

## [0.32.0] - 2026-10-19

### Changed

- `scripts/claude_auth.py`（ルートの scripts/claude_auth.py の写し）の `account_token` が、設定のフォルダの `.credentials.json` を使わなかった訳を、探した所の並びに `file-miss`（無い）・`file-error`（読めない）・`file-malformed`（在るがトークンの形でない）で出す。前は無いときと同じに見えた。トークンを渡すかどうかは変えていない。

## [0.31.0] - 2026-10-19

### Changed

- スキル・コマンド・プロンプトの文書を IT の定着語に置き換えた。前の版で置き換えた engine・グラフの言い方とそろう。グラフの「節」はノード、文書の区切りの「節」はセクションにした。振る舞いは変えていない。research-graph の SKILL.md と、review-graph の references の flows.md・policy.md・runnerless.md と、review-loop のプロンプトの p2.history.md・report.md の 6 本は、まだ置き換えていない。

## [0.30.0] - 2026-10-19

### Changed

- engine・スクリプト・ルール・グラフ・ブロックと試験の文を IT の定着語に置き換えた。グラフの「節」はノード、文書の区切りの「節」はセクションにした。ほかの例は、起こす→起動する・道具→ツール・欄→フィールド・柵→チェック・枝→ブランチか分岐・根→ルートか根本。engine とスクリプトが出す文言も変わる。出力の文字列を読んでいる所があれば、新しい文言に合わせる。判定と流れの振る舞いは変えていない。スキルとプロンプトの文書は、まだ置き換えていない。

## [0.29.0] - 2026-10-19

### Changed

- `scripts/claude_auth.py`（ルートの scripts/claude_auth.py の写し）の説明とコメントを IT の定着語に置き換えた（起こす→起動する・柵→チェック・根→ルート）。動きは変えていない。

## [0.28.3] - 2026-10-18

### Changed

- README を英語の 1 版に書き直した（日本語の版は置かない）。スキルとコマンドの名前・説明・本文は日本語のまま。決めは根の docs/readme-language.md。

## [0.28.2] - 2026-10-18

### Fixed

- 同梱の試験の台帳（`tests/py/MIGRATION.md` の、元の台本の check ごとの移し先の表）を刷り直した。0.28.0 で元の台本の 1 本（`tests/simulate_review.py`）の行がずれたのに表の行番号が古いままで、台帳の試験（`test_ledger.py`）が赤だった。graphloops の振る舞いは変わらない。

## [0.28.1] - 2026-10-18

### Fixed

- `/review-graph` の別ファイル 3 本（`references/flows.md`・`conversation-run.md`・`judgment-entry.md`）が、プラグインの外（リポジトリの `docs/graphloops-rearchitecture.md` と `convergence-loops/REVIEW.md`）を相対リンクで指していたのを、GitHub の URL に替えた。marketplace から入れた利用者の手元にはプラグインの中だけが写されるので、相対リンクの先が無かった。`judgment-entry.md` には、指した先の「零処方」の中身（削除で解く・既存のフラグか機構 1 つで解く・主張を狭めて解く）を書き足した

## [0.28.0] - 2026-10-18

### Changed

- 2 本の手順書（`/review-graph`・`/research-graph`）を `commands/<名前>.md` から `skills/<名前>/` へ移し、本文（`SKILL.md`）を 5,000 字以下にして、場面ごとの手順を `skills/<名前>/references/` の別ファイルに分けた。本文には `loop.py run`（engine に run を回させ、止まった訳を終了コードで返す命令）の終了コードごとの次の手と、どの場面でどのファイルを読むかだけを置く。呼び出しの名前は変わらない。会話が長くなって圧縮されると、Claude Code はスキルの頭の 5,000 トークンだけを付け直すので、今までは後ろの手順を失ったまま回っていた。手順の中身は削っていない（別ファイルの命令に出る `${CLAUDE_PLUGIN_ROOT}` は Bash では空になるので、本文が置き場への読み替えを言う）。`/review-graph` の description が名指す入口は「同梱の手順の『判定から入る（人の修正依頼）』」になった（`skills/review-graph/references/judgment-entry.md` の節）。

## [0.27.0] - 2026-10-17

### Changed

- plugin.json に作者（`author`）を書き、説明（`description`）を plugin.json の 1 か所にした。marketplace の項目の説明は外した（両方に在ると利用者の `/plugin` の画面には marketplace の項目の方が出て、片方だけ直すと画面が変わらないため）。plugin.json の説明は、今まで画面に出ていた marketplace の項目の言い回しに揃えた。README に入れ方の 2 行（「インストール」の節）を足した。振る舞いは変わらない。

## [0.26.1] - 2026-10-17

### Changed

- 文書だけの直し: README が指す convergence-loops の命令書の置き場を、根の `commands/` から今の `convergence-loops/commands/` に直す。差分を確かめる `git diff` には移す前と後の両方の置き場を渡す。振る舞いは変わらない。

## [0.26.0] - 2026-10-16

### Changed

- 同梱の試験の 1 件（段の任意の鍵が宣言の説明に載っているかを見る物）を、説明の置き場がリポジトリの根の README から CONTRIBUTING.md に移ったのに合わせて直した。graphloops の振る舞いは変わらない。

## [0.25.0] - 2026-10-16

### Changed

- 同梱の試験の件数の柵（集まるべき試験の数）を、0.24.5 で足した試験の 1 件に合わせて直した。graphloops の振る舞いは変わらない。

## [0.24.5] - 2026-10-16

### Changed

- 同梱の試験（CI の設定の形を見る物）を、リポジトリの CI が macOS で回らなくなったのに合わせて直した。graphloops の振る舞いは変わらない。

## [0.24.4] - 2026-10-16

### Fixed

- Windows で、プロセスが居るか・いつ始まったかの確かめ（子の残りを止める `loop.py children`・試し直しの前の確かめ・止めた後の確かめが使う）が、負荷の高い機械で答えを返さず「確かめられない」になり、止めるべき子を見送ることがあった。PowerShell（`Get-CimInstance`）を起こすのをやめ、Win32 の `OpenProcess`・`GetProcessTimes` をその場で呼ぶようにした。終わったがハンドルの残っているプロセスは「居ない」と読む。

## [0.24.3] - 2026-10-15

### Changed

- 設定のフォルダ（`CLAUDE_CONFIG_DIR`）の決め方を、engine の 1 か所（共通の部品 `claude_auth` の写し）に寄せた。振る舞いは変わらない。
- 隣の plugin の convergence-loops を、`<リポジトリ>/convergence-loops/.claude-plugin/plugin.json` の name で確かめるようにした（convergence-loops の置き場がリポジトリの根から移ったため）。

## [0.24.2] - 2026-10-15

### Changed

- 写しの `scripts/claude_auth.py` を、正本（リポジトリのルートの `scripts/claude_auth.py`）の convergence-loops 0.43.1 の変更に合わせた。graphloops の振る舞いは変わらない。

## [0.24.1] - 2026-09-29

### Changed

- 認証の段（`claude_auth.py`）の冒頭の写し先の一覧に、works の写し（`works/.shared/core/`）を足した。説明の 1 行だけで、動きは変わらない。

## [0.24.0] - 2026-09-28

### Changed

- （開発）旧い bash の台本を消す条件（docs/adr/0067）を、必須は台帳と被覆の包含（集合の包含で読む）、変異で期待の強さを確かめるのは任意にした。人の決定（2026-09-28、リポジトリの持ち主が運用の会話で「変異CIはしなくていい」と言い、REDESIGN の Q1〜Q4 を「すべてどうぞ」で採った）。
- （開発）変異の workflow（mutation.yml）は push で起こさず、schedule（週 1 回の全腕）と workflow_dispatch だけで 3 OS の組と mutmut を撃つ。手書きの変異の腕は、移した先の pytest の node id を名指して先に撃つ。

### Removed

- （開発）層 2 へ移した bash の台本 6 関数（simulate.py の test_stop_midway、simulate_review.py の test_deferjudge・test_final_gate_empty_asks_human・test_no_new_awaiting_after_judge・test_runaway・test_tdd_gives_up_without_dead_end）。台帳と被覆の包含がそろった物だけで、同じ筋書きは pytest の層 2 が確かめる。子プロセスで loop.py を起こす第二の網と、変異で期待の強さを確かめることは、この 6 関数の分だけ外れた。
- 残した物: 通しに残す 10 本の 1 つ（test_stop_midround）、golden の作り直しの口（golden_make.py の SIM_TESTS）が名指す 5 関数、関数ごとの被覆の帰属に欠けが出た 3 関数（simulate.test_attended_stuck_answer・test_gate_arms、simulate_review.test_awaiting。集合の包含では消せるが、関数ごとに測り直してから次の run で消す）、判定語彙の到達の柵の値をそれだけが到達させていた 3 関数（simulate.test_stopped_before_gates_reports、simulate_review.test_awaiting_origin_guards・test_ci_red_runaway。柵の値は下げない）、root の台本の review-record.py の節（第二の網）。理由は graphloops/tests/py/MIGRATION.md の「消す段」。

## [0.23.0] - 2026-09-28

### Added

- 回し役なしの run で、局所レビューの skill の節も engine が子で起こす。子は Skill と Agent を持つ読むだけの形で、sandbox の中で動く。プラグインの agent のレンズは、engine が写した定義を汎用の子に読ませて起こす。子の返答（本文が子の置き場の中身と同じ返答。`done` の読み口に依らない）は、必須のレンズの行に `invoked: true` を求め、`material` の awaiting_human を拒む（同じ会話に続きを頼み、上限まで続けば 14）。条件付きのレンズを起こさなかった行は受け付け、報告の知らせに『未確認のレンズ』として並べる。`/simplify` の持ち越しは、周の頭の版が前の周から 1 ファイルも変わっていない周だけ受け付ける。
- 背景の線（変異の検算）は、受領の形（graph の `delegate.receipt`）を持つ節なら `loop.py run` の回し手が受領を `done` して切り離して立てる。線の launch が結果を書かずに終わった（柵が拒んだ・子が落ちた・例外か止める信号で抜けた・回し手が起こせなかった）ときは、結果の置き場に落ちた印を書き、記録では『結果が使えない』の線に、`loop.py run` の報告では `lanes_failed` に並べる。線の試行は全部の周から引く——周が進んだ後に落ちた線にも印が付く。launch が印を書く前に居なくなった線（回し手が先に抜けた後の落ちも）は、読む側が launch の印と子の生死から導く。
- 回し役なしの run では、会話に返す 13 は engine の不具合（盤面の矛盾）だけになる。engine が起こせない節（sandbox の立たない場・別の作業ツリーの下の作業ツリーの書く節と局所レビュー、定義の無い役・レンズ）は、理由を instance の `unlaunched` に書いて 14 で人に渡し、`loop.py relaunch` で出し直せる。回し役なしの run の 13 は回し手が記録器に残す。前の版の engine で始めた盤面は今までどおり 13 で会話に返し、`next` が知らせる。
- 柵を外した run（`init --unfenced-delegates`）の任せ先も、回し役なしの run では engine が sandbox の外で起こす（作業ディレクトリは本物の写しのまま）。柵はその形を、盤面の印が在るときだけ通す。
- graphcheck: `launch.runner` を宣言する graph では、任せ先に `launch.delegate`、背景の任せ先に受領の形、engine_run の節に任せ先、役の節に起こす語が要る（会話に返す節を静的に作らない）。
- engine が起こす子の環境に印（`GRAPHLOOPS_ENGINE_CHILD=1`）を足す。対象リポジトリの入口（テスト一式・変異の実行器の台本）は、それを見て engine の子から走らせてはいけない形を拒める。
- 対象リポジトリが `.claude/settings.json` と `.claude/settings.local.json` の `permissions.deny` に置いた規則を、Claude Code と同じく合わせて、engine が起こす Bash を持つ子（道具つきの役・回す側の節の子・任せ先）に写す。読めない・形が壊れているときは、その子を起こさずに直すファイルを名指す。
- graph の `launch.append`: 起こす子の形（コマンドを走らせる子・道具を持つ子）ごとに指示書の末尾へ段を足す。人の方針の置き場と手元で走らせてよい範囲が、任せ先と Bash を持つ役にも届く。依頼の本文は貼らない。段は節の指示書の正本に入り、graphcheck の節の検査（回す側の節に本文を貼らない柵を含む）と必須の入力の導出を通る。段と同じファイルを節の `prompt_append` に書くと graphcheck が拒む。
- 入れ子の sandbox（Claude Code の sandbox の中の engine が起こす子で、Bash が sandbox の初期化で落ちる場）を、sandbox の中で走る子の前に確かめの子（道具は Bash だけ）で測り、返答に初期化の失敗の文が在ったときだけそう決める。その場では書き換える子・局所レビューの子・任せ先を起こさずに外し方を名指して止め（14）、読むだけの子は起こして Bash で測れていないことを記録に残す。子が Bash を呼ばなかっただけの回は決めずに次の launch で測り直す（run に 3 回まで）。`loop.py relaunch --reprobe` で固めた結果を測り直す。
- 修正前の関所: 判定役が持ち主の本文（init の依頼か、人が continue で答えた関所の行の ID）と結んだ狭め（`named_narrowings`）を、修正案が同じ単位・同じ what で指せば、聞かずに通して報告に並べる。
- 道具を持つ子に、盤面のファイル（作業ディレクトリの外に在りうる）の読み方の段を届ける。
- `init` が、走らせるだけの節を持つのに対象リポジトリの `.review-checks.json` が無い・読めないこと、と、もっと新しい版が入っていることを知らせる（止めない）。
- `loop.py status` と `loop.py run` の報告に、走っている子の起こしてからの経過（`launched_min`）と子が生きているか（`alive`）、engine が起こした子の費用（`cost_usd`。会話そのものの分は入らない）を出す。
- 開発元のリポジトリ（raiki61/claude-plugins）の `.claude/settings.json` の `permissions.deny` で、手元の e2e の一式（`bash`・`sh`・直の `./` の呼び）を対話の会話からも engine の子からも拒む。人の方針『テストの設計の作り直しが済むまで手元で e2e を回さない』の実装で、方針を解く時に消す。変異の実行器は `--check` だけを残して撃つ形を拒む規則が書けない（allow は deny に例外を作れない）ので deny に入れず、入口の柵（`GRAPHLOOPS_ENGINE_CHILD=1`）に任せる。利用者のリポジトリには効かない。

### Changed

- 旗の無い `init` を回し役なしの run（回す側の節も engine が起こす）にした。会話で回す道は `init --no-engine-runners` で選ぶ。`launch.runner` を持たない graph（research-loop）の旗の無い `init` は今までどおり。
- 人の関所は、人が continue で一度通した行（同じ出どころの ID。ID を持たない旧い盤面の行は同じ本文）を、周と関所を問わず聞き直さない。R4 が前に通した狭め・事前審査の穴を頭ごと写した行も、写した元と同じ ID で照らす。
- CI の節を省いた run の CI の問いは 1 度だけ聞き、答えた後は聞き直さずに、残る阻害が CI 未確認だけの周で止める（盤面の `stop_reason` が `ci_unverified_stopped`。報告に 1 項が立つ）。問いには省いた理由を添える。
- `status` と `run` の報告の費用（`by_node`）は、同じ会話を続ける節の分を、会話が始まった節でなく費用を生んだ節に付ける。`launch` の要約の `cost_usd` もその試行の分だけ。
- `loop.py relaunch` は、engine が起こせない理由を持つ節を `--reprobe` 無しでも出し直す。
- 局所レビューの子の前置きは skill の節の前置きだけで組む（書く子の前置きを継がない）。
- 版の並べ方を SemVer 2.0.0 の優先順位にした（プレリリースは同じ本体の正式版より下）。
- `status` と `run` の報告の費用に、数えなかった trace の行の数（`skipped`）を出す。
- 役の返答の番号の欄に名前の列に無い文字列が残っていれば、どの受け付けの拒みにも、前方一致する番号の候補と番号と名前の対応を添える。
- 依存の convergence-loops に版の下限（0.41.0 以上）を書いた。古い組み合わせは run の途中でなく読み込みの時点で止まる。
- `review-graph` の手順書の頭に早見を置き、会話の手番の手引きをそこ 1 か所にした（終了コードの表の写しと回し役なしの手順を消した）。会話で回す run の節のこなし方を後ろの節に分けた。engine の中の起こし方の写しを正本（engine の注記と graph の why）への指しに替えた。
- `loop.py run` が 14 で返したときの案内: 14 はまず会話が受け、推しで済む物（外し方を当てて `relaunch`・子の返答を引き取って `done --output`）をこなし、人に上げるのは取捨だけにする。書き換える節は作業ツリーを確かめてから起こし直す。

### Deprecated

- `init --no-engine-runners`（回す側の節を会話がこなす道）。人の決定（2026-09-27）で消す予定で、打つと注意を出す。

## [0.22.0] - 2026-09-27

### Added

- `loop.py skip --every-round`: optional の節を run の間ずっと、出す前に省く（回し切りの口）。
- `loop.py relaunch --if-untouched`: 前の試行の子を止め切り、作業ツリーと HEAD・枝が起こした時点と同じときだけ書き換える子を起こし直す。engine は落ちた書き換える子をこの確かめを通して 1 回だけ自動で起こし直す。
- 書き換える節の申告（graph の `declared_files`）: 返答が名乗ったファイルと、作業ツリーで実際に変わったファイルを両方向で突き合わせ、食い違いを記録に残す。次の周の判定者が読む。

### Changed

- 書く子が申告の外に書いても受け付けを拒まず、記録と所見に残す（回し役の居ない run を止めない）。
- git の状態の柵は、自分の作業ツリーの HEAD と枝だけを比べる。全作業ツリーで共有する stash と作業ツリーの一覧は、並行の run が動かしても受け付けて trace に残す。P1 の前後の突合の基準から stash の一覧を外した。
- 作業ツリーの前後の突合は、状態とパスの並びに加えて中身の木の id も比べる。読むだけの節・skill の節は作業ツリーへ書く手に数えない。
- engine が起こす書く子に、子ごとの一時の置き場を渡す。sandbox の中で書けない版なら共有の置き場へ戻す。
- 書く子の指示書に、人の方針・宣言した検査の回し方・申告の決まりを届ける。
- 義務の行（`rows`）を持たない旧い版の出力は、止めずに差分レビューの出力から数え直し、測れなかった痕跡を残す。
- （開発）pytest の層 2 の筋書き（上限で止まる類と、止める・人待ちの筋書き）を足した。bash の台本はまだ残る。

### Fixed

- Windows で、申告のファイル名が作業ツリーと違うドライブを指すと受け付けが落ちていた。
- UTF-8 でないファイル名の綴りが、Windows でだけ盤面に別の綴りで残っていた。

## [0.21.5] - 2026-09-27

### Added

- 宣言した検査の一式（`.review-checks.json` の `suite`）が全段緑で終わったら、同じ指紋（作業ツリーの中身・段の定義・実行の土台）の間は別の run でも走らせずに使い回す。必ず走らせるなら `launch` の環境に `GRAPHLOOPS_RERUN_CHECKS=1`。
- 子を止める猶予を環境変数 `GL_KILL_GRACE=<秒>` で選べる。
- ブロックの約束の置き場 `blocks/`。graph は節の出口の型を `$ref` で指し、graphcheck が所属・出口・並列の上書き・共有の核を照らす。
- 外から規則を呼ぶ口 `scripts/gl.py`。
- 盤面を横断して run の質を engine の版ごとに数える、読み取り専用の台本 `scripts/quality-ledger.py`。
- 変更の記録（この文書）と、版を出す手順（リポジトリの `docs/releasing.md`）。

### Changed

- 規則の関数を読み口と effects の形へ移し始めた。run の状態（盤面の `loop`）は graph の `state_schema` の合わせ方（`x-reducer`）と effect の口だけで書き、`loop.py patch` で `loop` を変えた手当ては合わせ方を飛ばした痕跡を残す。
- 同じ周の擦り合わせを 3 往復まで回す（回ごとに回す側が再異議を書く節を置いた）。3 回とも決着しなければ第三の目が立つ。
- 手順書に回す側の手の心得（人の居ない手番で消す操作を打たない・背景はハーネスの背景実行で・結果は盤面で見る）を足した。

## [0.21.4] - 2026-09-27

### Added

- engine が走らせる CI の節（`p0.local_checks`・`p4.ci`）を人の命令で省く口。
- `init --engine-runners`: 回す側の節を engine が `claude -p` で起こす（書き換える節は OS の sandbox の中で作業ツリーだけに書ける）。

### Changed

- `loop.py patch` が親を新設したときにそう言う。盤面・trace に書く値の引数の読めないバイトは入口で拒む。
- comment-analyzer を読むだけに狭めて engine が起こす。

## [0.21.3] - 2026-09-27

### Added

- `loop.py children`: 盤面の印から子の残りを一覧し、止める。
- 審査の役に貼る差分が `launch.input_budget_bytes` を超えた周は、節を要約した写しを貼り、全文は Read 1 本で読ませる。

### Changed

- ブロックの出口の値を盤面の `loop` から節の出力へ移した（`hist.snapshot`・`hist.after_fix` で読む）。旧い盤面の鍵は警告して次の周の頭で外す。
- 消す口の柵を graphloops・tests・scripts の全部に広げた。

## [0.21.2] - 2026-09-27

### Added

- `loop.py run`: 回し手が engine の起こせる節を回し続け、会話に返す節・人の答え待ち・周の止め・終わりでだけ終了コードで戻る。1 つの run に回し手は 1 本で、盤面の置き場の錠で決まる。`init --stop-after-round` で止めた run は `loop.py resume` で次の周へ進める。
- `loop.py patch` で節の最新の出力の欄を書ける（`out.<節>.<欄>`。節の返答の型で照らす）。`--delete` もこの形に通る。
- 周をまたぐ値を記録の履歴から作る、読み取り専用の口（`hist.`）。patch でこの値は書けない。
- 設計の決定の記録（ADR）をリポジトリの `docs/adr/` に置き、先行議論を洗う役（`p0.prior_decisions`）がそこを読む。

### Changed

- 盤面の保存を置き場の錠の下で「読み直し→比べる→書く」にした。回し手・会話・人が同時に書いても割り込まれない。
- 盤面の `loop` を片付けた。`flow`・`gates` などの値は `loop` に写さず、`inputs` と節の出力から読む。
- 背景の任せ先の線を止める手順を手順書に書いた。止めた線は同じ周に起こし直さない。

## [0.21.1] - 2026-09-27

### Added

- `answer --detail`: 修正の前の人の関所で、直す義務の単位をその周の修正から外せる。外した単位と理由は記録に残る。
- `loop.py patch --delete` と、`--path` の `record.` 接頭（付けても付けなくても同じ所を指す）。
- `loop.py launch` が落ち方を `cause` の 3 値（`launch_auth`・`launch_child_failed`・`launch_auth_unread`）で返す。
- 盤面の `loop` の形を graph の `state_schema` に宣言し、graphcheck が読みを照らし、engine が保存の時に照らす。
- 修正の入口を単位の番号にした（`p2.fix_units`）。役は一覧を番号で指し、engine が名前に戻す。
- graph の `extends` を何段でも重ねられる。
- 検査の宣言に engine の知らない段が在っても、知っている段は走らせ、P0 で人に確かめる。engine の知らせ（notices）が報告に載る。

### Changed

- 変異の関門を Google 型にした（変わった行だけ・1 行 1 本・行を通した台本だけで撃つ）。
- CI の見送りに能力の名前を持たせ、OS ごとの「欠けてよい能力」の一覧で数える。
- 修正役が当たった先行例を、次の周の判定役へ渡す。問いの key の重複を拒む。

### Fixed

- 子を止める口が、グループの外へ出た孫と、ゾンビだけのグループを取り違えない。正常に終わった試行の残りの子も止める。
- 人が関所で単位を外した周に、外した単位を直さない修正が拒まれていた。
- windows-latest の CI の赤（0.21.0 の 12 件と pytest の 13 件）を直し、3 OS で緑に戻した。

## [0.21.0] - 2026-09-26

### Added

- `init --stop-after-round N`: N 周目の締めまで済ませて止まる。
- `init --input gates=merge`: 変異の検算を run の中で撃たず、合流した版でまとめて撃つ。
- engine が走らせる節: CI の再実行（`p0.local_checks`・`p4.ci`）は、対象リポジトリのルートの宣言 `.review-checks.json` のコマンドを engine が走らせ、終了コードから結果を組む。
- `loop.py stop`: 人が途中で止める口。止めた理由が記録に残り、報告の節だけが走る。
- 人の方針: run をまたいで効く人の決まりを 1 つの文書に置き、各節に届ける。今ある能力を減らす変更と方針とぶつかる変更は、修正の前後の関所（`p2.human_gate`・`r4.human_gate`）で人に聞く。
- 踏んだ問題を利用者の環境に 1 件 1 行で残す記録器と `/graphloops:intake`。
- Bash を持つ役を OS の sandbox の中で起こす。外へ問い合わせを出せる役に検索語の規律を持たせた。

### Changed

- 宣言のコマンドを走らせる前の人の承認を外し、走らせる直前に宣言と突き合わせる。
- 検証器だけが持っていた判定の規則を、役の返答の受け付けでも当てる。graphcheck が節の知らない鍵を照らす。
- `/security-review` のレンズを、条件の関数で当てる。

### Fixed

- テストの台本が `launch` の失敗時に `/` を消しにいく欠陥を塞いだ。

## [0.20.3] - 2026-09-26

### Fixed

- windows-latest の CI の赤 6 件を直し、3 OS で緑に戻した。直したのはテストの台本・代役・変異の道具だけで、製品のコードは変えていない。

## [0.20.2] - 2026-09-26

### Added

- `init --unfenced-delegates <理由>`: 人が run ごとに明示したときだけ、任せ先の sandbox を外す。外した事実は盤面に残る。

### Changed

- 重い工程のコマンドの説明を「起動は人が打ったときか『工程に回して』と言ったときだけ・AI は提案まで」に揃えた。`/review-graph` の説明が、人の修正依頼を判定から入れる入口を指す。

### Fixed

- 任せ先を engine が OS の sandbox の中で起こす。作業ディレクトリは本物の写しで、本物の作業ツリーと `.git` には書けない。0.20.1 では、Agent ツールで起こした任せ先が本物の作業ツリーで `git checkout` と `git reset --hard` を打ち、回す側の未コミットの修正を消した。
- CI を 3 OS で緑に戻した（git の名前とメールの無い環境・Windows の文字コードと symlink）。

## [0.20.1] - 2026-09-25

### Fixed

- 役の標準出力が `claude -p` の JSON の包みでなくても、全文を本文として受け付けに回す。途中で engine だけ上げた run で、役の所見が捨てられていた。
- research-graph: ゲートの前に止まった run でも報告が出る。
- research-graph: 未解決の開いた問いが残っていれば、収束の文言を「閉じた主張の検証は収束した」と「開いた問い K 件は未解決」に分ける。案内の中の存在しないコマンド名を `add` に直した。

## [0.20.0] - 2026-09-25

### Added

- 判定から入る入口: `loop.py add` で人の修正依頼を置くと、素材集め（P1）を外して判定から始まる。
- 役を engine が `claude -p` の子プロセスとして起こし、子の終了を直接待つ（`loop.py launch`）。拒まれた返答は同じ会話に出し直させる。
- 変異の検算を並行の線に出し、周の締めは待たない。収束の前に、最終の版で撃ち直す関門を置く。
- pytest の土台（`graphloops/tests/py/`）。
