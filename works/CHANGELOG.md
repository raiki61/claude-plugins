# 変更の記録（works）

works（Archon の上の生産ライン darkfactory の pack と、Claude Code 側の入口 `/works` スキル）の版ごとの、利用者に効く違いを新しい順に並べる。形は [Keep a Changelog 1.1.0](https://keepachangelog.com/ja/1.1.0/) に従い、版の番号は [Semantic Versioning](https://semver.org/lang/ja/) の形（x.y.z）で振る。節は Added（足した）・Changed（変えた）・Deprecated（やめる予定）・Removed（消した）・Fixed（直した）・Security（安全の直し）のうち、中身の有るものだけを使う。

版を名指しする git の tag（例: `works--v0.2.0`）の名前の決まり・付け方と、この記録を書き足す段は、リポジトリのルートの `docs/releasing.md` に在る。0.1.0 はこの記録に無い。

## [Unreleased]

### Changed

- 素材集めの p1.local_review の受け付けが、必須のレンズを起こさなかった返答と、そのまま material を awaiting_human にした返答を拒み、同じ会話で起こし直させる。拒みが 3 回目に届いた時だけ人に渡す。今までは最初の失敗で run が人待ちに止まっていた。レンズのプラグインが隔離した設定に入っていない時は、起こし直しても毎回落ちるので、プラグインを名指してすぐ人に渡す。`/simplify` の持ち越し（`simplify_carried: true`）は、本流と同じ条件（前の周から 1 ファイルも変わっていない周）の時だけ認める。写しは本流の `changed_since_prev_round` を出さないので、写しが周ごとに残す周の頭の版の木を前の周と比べて決める。写しの指示書の「ロジック変更が無いなら持ち越してよい」より狭く、どれかのファイルが変わった周と 1 周目は `/simplify` を起こし直させる（役への読み替えの文にもそう書く）。条件付きのレンズ（`/security-review`）の失敗は今までどおり受ける。

### Security

- Claude の包みが、道具を持つ役の system prompt に「検索語に対象の名前を載せるな」の規律（写しの `agents/judge.md` の塊を字のまま）を足す。今までは works の役の指示書にこの規律が無く、WebSearch・WebFetch の問い合わせに対象のリポジトリ名・本文が載りえた。SDK が `--append-system-prompt-file` を渡す起動と、規律の正本を読めない起動は起こさない。包み無しの run には載らない。
- Claude の包みが、対象リポジトリの `.claude/settings.json`・`.claude/settings.local.json` の `permissions.deny` を役の `--settings` に写す。今までは役が隔離した設定で起きるため持ち主の禁止（例: e2e の一式を手元で回さない）が役に効かなかった。ファイルが読めない・形が違う時は、そのファイルを名指して役を起こさない。包み無しの run には載らない。
- Claude の包みが、AI の役の子の env に `GRAPHLOOPS_ENGINE_CHILD=1`（graphloops の engine と同じ目印）を立てる。今までは works の役に目印が無く、対象の重い一式（e2e・変異の撃ち）が AI の役からの起動を見分けて拒めなかった。線の節が走らせる最後のテストと、包み無しの run には立たない。

## [0.2.2] - 2026-09-28

### Added

- ラインの入力 `lang`（報告の言語）。AI の報告の指示書が読む `inputs.lang` に渡る（graphloops の `--lang` と同じ）。空なら今までどおり依頼文の言語（利用者の言語）で書く。機械の報告 `report.md` の定型文は日本語のまま（AI の報告が落ちた時の予備）。
- `use.sh show` が、走っている run の今までの費用（Archon が run に持つ和 `metadata.total_cost_usd`）を出す。

### Changed

- darkfactory の独立の目（R1〜R4）を、最後の人の関所の後から前へ移した（最後のテスト → 独立の目 → 最後の関所 → 報告）。関所の全文に目の判定と、R4 が人に聞く問いが載る。人は審査の結果を見てから答える（graphloops が r4.human_gate で聞くのと同じ順）。`final_gate: when_needed` でも、目が阻害（redesign-needed・unverifiable・premise-invalid）を返せば関所が開く。関所の `continue` は R4 の問いには答えない（問いは今までどおり報告の冒頭と次の run の依頼の下書きへ渡る）。`stop` しても目の費用は戻らない（目はもう回っている）。
- 報告の費用の行: 節の費用は Archon の `node_completed` の `cost_usd` だけを読む（推測の別名 `costUsd`・`total_cost_usd` は読まない）。合計は節の和でなく Archon の run の和（`workflow_completed` の `cost_usd`）にし、節の和と食い違えば両方を出す（包みの節と子を二重に数えうるため）。run の和がまだ無い run は、節の和を「途中」と添えて出す。

### Fixed

- 判定役の欠陥を数える問い（class_query）に「当たる例・当たらない例」を添えられるようにし、判定の時点で例を問いに当てて、合わない問いを単位の名指しで拒む（Semgrep の規則の試験と同じ形）。例の無い問いは今までどおり受ける。
- 修正の返答が輪の最後の回に数え合わせで拒まれた時、その単位だけを人に回して（裁定 ask_human）残りの直しを受ける。今までは 1 単位の食い違いで run 全体が止まった。
- 借りる道具（superpowers・coldwrite・pr-review-toolkit）を、Claude Code が実際に読み込む scope の `installed_plugins.json` の行から取る。知らない形の `installed_plugins.json` や、勝った scope の置き場が消えている時は、下の scope へ戻らずに名指しで止まる。入れたが無効にした物も今までどおり借り、有効・無効を記録に残す。
- 修正の受け付けが、裁定 `fix_test_scope` が認めた範囲の中の凍ったテストの変更を拒まなくなった。直す単位が全部人に回った run が、空の申告で止まらずに最後の関所へ進む。

## [0.2.1] - 2026-09-28

### Changed

- 入れ方を、Claude Code のプラグインを 4 つ入れる（works・superpowers・coldwrite・pr-review-toolkit）だけにした。リポジトリの clone も、その場所を置く環境変数も要らない。`/works` スキルの行は、入れたプラグインの置き場の `dev/use.sh`・`stop.sh`・`report.sh` を起こす。
- AI の役が借りる superpowers のスキル・coldwrite・pr-review-toolkit を、利用者が Claude Code に入れた版から取るようにした（本線の graphloops と同じ。版は Claude Code が今に保つ）。確かめるのは works が名前で使うスキル・agent・hook が在ることだけ。入っていない物があれば、`use.sh check`・`start` は AI を起こす前に、足りない物ごとの 1 行と入れるコマンドを出して止まる。使った版と置き場は今までどおり `.works-toolset.json` と run ごとの `versions.json` に残る。

### Removed

- works の中に置いていた superpowers（6.4.2）のスキルと pr-review-toolkit の写しと、その使用許諾の表示のファイル（NOTICE）を消した。works は第三者の物を同梱しない。

### Fixed

- Claude Code のプラグインのキャッシュに入った works から `use.sh` を起こすと、coldwrite の元（works の外の marketplace.json）が無くて `check` も `start` も止まっていたのを直した。
- pack の出どころの控え（`.works-source.json`）が、works が git で追跡されていない時に別のリポジトリの commit を works の版として書くことがあったのを直した。その時は commit を null にし、プラグインの版を書く。

## [0.2.0] - 2026-09-28

### Added

- darkfactory の線を、判定の前後と修正の後ろまで広げた。前提の実測・目的の文・素材集め → 判定 → 修正案と事前審査 → 修正 → 差分の審査 → 手直し → 最後のテスト → 人の最後の関所 → 独立の目 → AI が書く報告と初見検査、の順に流れる。自分食いの run（dd68321e）で、図の最初から最後まで通り、結末 fixed になった。
- 修正の段に、単位ごとの TDD の輪を足した。テストを書く → 機械が赤を確かめる → 直す → 機械が緑を確かめる → 整える、を単位ごとに回す。テストの実行器が無い対象は、今までどおり直接直す。
- 修正役と TDD の役が「依頼・テスト・コードが食い違っている」と証拠つきで申し出る出口と、それを裁く読むだけの役を足した。裁けない物・能力を下げる物だけが最後の人の関所に上がる。
- 守りのファイル（works 自身の試験・柵・受け付けの口）の一覧を足した。run の差分がこれに触れると、最後の人の関所が必ず開き、冒頭にファイルと規則が並ぶ。
- 修正役の指示書を、共通の決まりと道ごとの決まりから機械で組む形にした。同じ会話の続きには、決まりの全文でなく差分だけを渡す（包みが起動の時に選ぶ）。
- 変えたファイルから影響するソースとテストを機械で引く地図（`.shared/core/impact.py`）と、変えたファイルが使うライブラリの今の文書を Context7 から取って修正の指示書に貼る口を足した（`WORKS_CONTEXT7=off` で止める。役が自分で Context7 を引く口は既定で切り、`WORKS_CONTEXT7_MCP=on` で入れる）。
- 他のリポジトリで使う起動の殻 `works/dev/use.sh`（`check`・`start`・`show`）と、`/works` スキルの入口の説明を足した。
- run ごとの版の一覧（`versions.json`）を、盤面の隣に書く。
- 見張りごとの軽い自己点検 `works/dev/selfcheck.py`（見張りの 1 行を壊して、見張る試験が赤になるかを確かめる）を足した。

### Changed

- AI の役は全部、選んだ物だけを置いた隔離した Claude Code の設定（借りた superpowers の 5 つのスキル・coldwrite・pr-review-toolkit）を読む。
- 役の道具を、本線（graphloops review-graph）の同じ役以上にした。判定・修正案・事前審査・修正・手直しの役が Web を引ける。
- 役の出し直しの輪は、3 回目の拒否で理由を書いて盤面を止め、報告まで届く（run ごと落とさない）。
- 最後の人の関所は、線の最後（最後のテストの後）に 1 つだけ置く。
- 自分食いの殻 `works/dev/dogfood.sh` は、既定で包みを通して役を起こす。

### Fixed

- Claude Code が役の作業フォルダに作る `.claude/.cc-writes/`（どの深さでも）を、読むだけの役の作業ツリーの見張りが変更と数えて拒んでいた。
- 修正役が判定に異議を書くと、再審の節が線に無いため最後のテストが走らなかった。
- 節が落ちると報告も出口も残らなかった。今は機械の報告と次の run の依頼の下書きを必ず残し、Archon の run の状態は失敗のままにする。
- 修正案の役が直す単位を番号で指すと、役の出口の型が文字列だけを許していたため毎回拒まれていた。
