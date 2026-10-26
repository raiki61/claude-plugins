# 変更の記録（works-factory）

works-factory の Claude Code 側の入口（`/works-factory` スキルと殻 `bin/works-factory`）の版ごとの、利用者に効く違いを新しい順に並べる。形は [Keep a Changelog 1.1.0](https://keepachangelog.com/ja/1.1.0/) に従い、版の番号は [Semantic Versioning](https://semver.org/lang/ja/) の形（x.y.z）で振る。節は Added（足した）・Changed（変えた）・Deprecated（やめる予定）・Removed（消した）・Fixed（直した）・Security（安全の直し）のうち、中身の有るものだけを使う。

版の出し方（この記録を書き足す段。git の tag は作らない）は、リポジトリのルートの `docs/releasing.md` に在る。

## [Unreleased]

## [0.12.0] - 2026-10-26

### Changed

- 工場の固定 commit（`works-factory/PIN`）を 062cd124 に上げた。取り込んだ PR は raiki61/works-factory#876。差分は https://github.com/raiki61/works-factory/compare/e52a1b452d33...062cd124bb59 。

## [0.11.0] - 2026-10-26

### Changed

- 工場の固定 commit（`works-factory/PIN`）を e52a1b45 に上げた。取り込んだ PR は raiki61/works-factory#841・#839・#840・#847・#850・#842・#848・#852・#854・#853・#844・#856・#858・#857・#843・#859・#860・#865・#866・#867・#861・#870・#869・#872・#874・#875。差分は https://github.com/raiki61/works-factory/compare/1b5d8b709f69...e52a1b452d33 。
- 利用者に効く違い: Claude Code の設定の `env`（利用者の `settings.json` と会社が配る managed settings のファイル）に書いた接続の値（接続先・資格・proxy・証明書・モデルの別名、Bedrock・Mantle・Vertex の決まった名の変数）が、工場の中の AI の役に運ばれるようになった（raiki61/works-factory#859・#860。前は運ばれず、殻を起動する環境に置く必要があった）。`CLAUDE_BIN_PATH` に、普段 Claude を起動するラッパースクリプトを指せるようになった。対象の `.review-checks.json` の `suite` の横に、試験を走らせずに一覧だけを出す `list` を書ける（試験が無いと決めるのに使う）。
- `skills/works-factory/references/auth.md` の「API キーかゲートウェイで動く人」の、設定の `env` の値は運ばれないという文を直し、Bedrock・Mantle・Vertex の選び方と工場の README への指しを書き足した。

## [0.10.1] - 2026-10-26

### Fixed

- 認証の手順（`references/auth.md`）の、keychain の項目を確かめる `security find-generic-password` が macOS だけのコマンドだと書いた。

## [0.10.0] - 2026-10-23

### Changed

- 工場の固定 commit（`works-factory/PIN`）を 1b5d8b70 に上げた。取り込んだのは raiki61/works-factory#835。工場の中の AI の役の会話のキャッシュの寿命が、Claude の加入でログインした人では既定の 1 時間から 5 分になった（run の設定の層の env に `CLAUDE_CODE_PROMPT_CACHE_TTL=5m` を載せる）。殻を起動する環境・`--config` の `env:`・対象の `.archon/config.yaml` の `env:` で寿命を選んでいれば上書きせず、`--adopt` の起動では載せない。報告（`report-ai.md`）の「費用」のセクションに、工程ごとのトークン数（入力・出力・キャッシュの読み・書き）の行が出る。
- 寿命を変える時の書き方を `skills/works-factory/references/auth.md` の「会話のキャッシュの寿命を変える時」に書き、スキルの本文の「認証」の行から指した。本文の長さの上限（5000 字）に収めるため、「1. 殻」の置き場の文を短くした。

## [0.9.0] - 2026-10-23

### Changed

- 工場の固定 commit（`works-factory/PIN`）を 3b44770d に上げた。取り込んだ物は 3 つ。対話モードの入力の名を `design_only` から `design_talk` に替えた（raiki61/works-factory#829。動きは同じ。古い名を本線か周の鎖に渡すと、殻が Archon を起こさずに止まり、`--input design_talk=true` を案内する）。同じ対象に 2 本以上を同時に起動しても落ちなくなった（raiki61/works-factory#826。使う人の手順は変わらない）。`--detach` なしの `workflow run` が終わると（承認ノードで止まった時も）、標準エラーに `works-factory: 記録の置き場: <パス>` を 1 行出す（raiki61/works-factory#831）。
- スキルの本文と `skills/works-factory/references/chain.md` の `design_only` を `design_talk` に替え、「4. 報告を読む」に記録の置き場の 1 行を書き足した。空の `revise` の聞き直しを「2 回まで」と書き直した（前の「3 度目は止まる」と同じ振る舞い）。本文の長さの上限（5000 字）に収めるため、ほかの文を短くした。

## [0.8.0] - 2026-10-23

### Added

- 対話モード（`--input design_only=true` で、無人でない run）の設計の相談の承認ノード `gate-design` と、その答え `revise <一言>` をスキルの「3. 承認ノードで答える」に書いた。計画と事前審査の往復が終わるたびに設計案と審査の結果を見せ、`approve` で同じ run のまま修正へ進み（直す前の承認ノードは合意した設計の項目を聞き直さない）、`stop` で止まり、`revise <一言>` で設計し直して事前審査をやり直し、もう一度聞く。一言が空なら聞き直し（2 回まで）、往復は 20 周まで。無人の run で `design_only=true` を付けた時は今までどおり直す前で止まる。

### Changed

- 工場の固定 commit（`works-factory/PIN`）を 5a376672 に上げた。上の設計の相談（raiki61/works-factory#824）と、試験を回す仕組みの直し（raiki61/works-factory#825。使う人の手順は変わらない）を取り込んだ。通常の run と無人の run の止まり方は変わらない。
- 周の鎖（何周もつなぐ run）の手順を、スキルの本文から `skills/works-factory/references/chain.md` に移した。`design_only=true` と組めないことを書き足した。
- 本文の長さの上限（5000 字）に収めるため、API キーの時に `WORKS_FACTORY_KEYCHAIN_ITEM` を付けない注意（`references/auth.md` に同じ注意が在る）と、深さの段ごとの違いの括弧書き（工場の `docs/design/line.md` の 5.1 に在る）を本文から外した。

## [0.7.0] - 2026-10-22

### Changed

- `skills/works-factory/references/spec.md` の、業界の定石との比較の run が全部の行に答えているかの照合の説明で、「依頼の行」が表の `design`（設計書）と `acceptance` の各行を指すこと、照合する行が部品の返す `rows` の行であることを書き足した。

## [0.6.0] - 2026-10-22

### Changed

- 工場の固定 commit（`works-factory/PIN`。殻が使う raiki61/works-factory の commit）を fd33cb45 に上げた。人と固めた仕様を審査する部品のうち、設計を業界の定石と比べる部品（`works-factory-world`）が、仕様の表（YAML）の `design` と `acceptance` の各要素に評価の行を 1 つずつ返し、本線の起動時の照合も全部の要素に行が在るかを確かめるようになった。前の PIN の工場で回したこの部品の run は、行が欠けていれば本線の起動で止まるので、使う人がこの部品だけを回し直す。手順は `skills/works-factory/references/spec.md` の 2 に書いた。

## [0.5.0] - 2026-10-22

### Added

- 人と固めた設計書と YAML の表から修正へ進む入口 `spec_table` を案内した。会話の中で仕様を計画・独立設計・前提・過去の決定・業界の定石の 5 部品で審査し、実際の run の記録と照合してから修正の流れに渡す手順を `skills/works-factory/references/spec.md` に置いた。

### Changed

- 工場の固定 commit（`works-factory/PIN`）を e04500cd に更新した。判定と計画を 1 回ずつ回す仕様入力の道、変更に関わる試験の実行器を使う試験の段、報告の冒頭に対象への反映状況と判断の短い題を出す改善を取り込んだ。通常の依頼の入口も残る。
- 依頼の参照先を用途別に示した。`findings` の形は `workflows/.shared/schemas/request.schema.json`、依頼の全項目と省略の扱いは、今も在る `lib/carry.py` の `parts()`。

### Fixed

- 複数回の修正をつなぐ実行（周の鎖）を `--detach` なしで起動して cancel した後、各回の修正を担う子の run が running のまま残る件を、工場の停止処理の更新で直した。子の abandon は作業ツリーと未コミットの変更を消すため、止めた鎖は resume で続けず新しい run にする、と停止の案内を合わせた。

## [0.4.0] - 2026-10-20

### Changed

- `works-factory/PIN`（殻が使う raiki61/works-factory の commit）を 687a6057 に上げ、殻が `apiKeyHelper`（Claude Code の設定の、API キーを出すコマンドの欄）のコマンドを走らせて得たキーで工場の中の AI の役を起動する道と、同時数の上限 `WORKS_FACTORY_CLAUDE_CONCURRENCY`（429 が返る時）をスキルの `references/auth.md` に書いた。API キーとゲートウェイ（API の中継先）の値は殻を起動する環境に置き、設定の `env` に書いた値は工場の中の AI の役に運ばれない、と説明を直した。

## [0.3.0] - 2026-10-20

### Changed

- `works-factory/PIN`（このプラグインが取ってくる工場の commit）を raiki61/works-factory の e87f40a3 に上げた。工場の流れ（本線のグラフ）を部品に分けて組み直した版（raiki61/works-factory の issue #765・PR #794）で、プラグインから起動する run（工場の 1 回の実行）はこの版で回る。起動の形は変わらない。スキルを新しい工場に合わせた:
  - 承認ノード（run が止まって人の答えを待つ所）は 4 か所になった: 始める時・直す前・修正の途中で計画が変わる時（今回増えた）・最後。
  - 最後の承認ノードをいつ開くかを `--input final_gate=` で選べる: `always`（毎回。人が答える run の既定）・`when_needed`（訳が在る時だけ。無人の run の既定）・`protected_only`（守りのパス〔対象の `.works-protected.json` に書いたファイル〕に当たった時など）。
  - `--input design_only=true` を付けると、直す前の承認ノードがいつも開き、修正の前に計画を見られる。
  - 無人の run（`--input unattended=true`）は始める時の承認ノードを飛ばす。最後の承認ノードを開くはずなら止まり、差分は対象に当てない。
  - 工場の設計書の置き場が `docs/design/` になった。
  - 走っている run を cancel で止めた後の扱いを `skills/works-factory/references/stop.md` に分けた。
  - `test_cmd` を渡さないと、工場が全試験を何度も走らせて遅くなる（実地で 90 分の run が 300 分になった）ので、変更に関わる試験だけを走らせるコマンドがあれば渡す、と書いた。

## [0.2.0] - 2026-10-20

### Changed

- スキルの認証の項目を別ファイル `skills/works-factory/references/auth.md` に分け、Claude のログインでなく API キーで Claude Code を使う人の起こし方を足した。殻の振る舞いは変えていない。キーは環境変数 `ANTHROPIC_API_KEY` に置く。Claude Code の設定 `settings.json` の `apiKeyHelper`（API キーを出すコマンドを書く欄）は今の殻が読まないので、それだけでキーを渡している人も `ANTHROPIC_API_KEY` に置く（殻が読むようにする直しは raiki61/works-factory の issue #795 で、まだ入っていない）。

## [0.1.11] - 2026-10-18

### Fixed

- `works-factory/PIN` を raiki61/works-factory の 4082a4e0 に上げた。報告の書き手が 2026-10-17 から模型の提供元の安全の判定に止められ、報告の本文が書かれていなかった。報告の書き手に渡す引き継ぎのメモの欄の名を替え、この上げで通るようにした。cancel した run の AI のプロセスが残って使用量を使い続けていたのを、殻が cancel の後に子の run の分まで止め、止めた物と残った物を 1 行ずつ出すようにした。計画の事前審査の返答が書式の訳だけで拒まれ続け、run が直しの前で止まる件を塞いだ。守りのファイルに当たった一覧も先頭の数行と件数に切った（当たりが数万本でも承認ノードの文と出力が膨らまない）。

### Changed

- 同じ上げで、工場が使う Archon を upstream の 64ec0c2e に上げた（timeout を書かないノードが 2 分で打ち切られない版。使用枠が切れた run は今までどおり落ちる）。報告の冒頭 3 行（起きたこと・差分を当ててよいか・人が決めることの件数）を機械が run の記録から組み、詳しい中身を `report-detail.md` に分けた。報告の書き手が落ちた run は failed で終わり、使用枠切れなら別のアカウントで resume すると書き手から先だけが走り直す。対象の試験のコマンドはいつも利用者の家で走り（`WORKS_FACTORY_TARGET_USER_ENV=1` の道は無くなった。殻が起動のたびに 1 行で告げる）、修正の前の試験が 1 段も走らない時は判定の前で止まる（新しい作業ツリーの準備は `.review-checks.json` の `setup` に書く）。`test_cmd` の形の確かめを殻から run の頭のノードへ移した。工場の内側の語を対象のコードに書かない照らしを差分の審査に足した。計画の事前審査の往復は、直さずに進むと壊れる指摘が無くなれば通し、2 往復目からは差分と影響だけを見る。差分を hash で封じた後のノードが落ちた run も、`apply --allow-failed` を付ければ封じた hash を照らして当てられる。run を起こす時に `--model @wf-<群>=<模型>` で役の群の模型を付け替えられる。
- スキルを上に合わせた: cancel の止め方と resume・abandon、試験の環境と `setup`、`test_cmd` の止まり方、報告の冒頭と書き手が落ちた時、`apply` の旗。

## [0.1.10] - 2026-10-17

### Fixed

- `works-factory/PIN` を raiki61/works-factory の 56032b5a に上げた。修正役の後始末（clean）が消したファイルを最後の承認ノードの文と報告に全部並べていたため、消した本数が数万になると、ノードの出力が Archon の上限を越えて run が終われなかった。一覧を「先頭 5 本・ほかの件数・全件の置き場のパス」に切った（取り込むと消えるファイル・新しい名の一覧も同じ）。報告の書き手を周ごとに新しい会話で起こし、引き継ぎのメモで渡す直しも入る。

## [0.1.9] - 2026-10-17

### Changed

- `works-factory/PIN` を raiki61/works-factory の 1e60d4b1 に上げた。工場が使う Archon を upstream の 355f1867 に上げた（承認ノードは新しい待ちの形で、答え方の命令は今までと同じ。使用枠が切れた run は今までどおり落ち、別のアカウントで resume して続ける）。run の深さを依頼の行ごとの未知の種類で選ぶ・計画を書く役が周をまたいで引き継ぎのメモを渡す・計画の段の最初の答えが同じ形で拒まれる件を減らし、出し直しの回数を報告に出す・公開ベンチの台の起動前の確かめ、などが入る。

## [0.1.8] - 2026-10-16

### Changed

- `works-factory/PIN` を raiki61/works-factory の 2e5e55c7 に上げた。run の深さを軽量・標準・重厚の 3 段にし、計画の事前審査を深さで飛ばす道を外した（重厚は判定の裏取りと木の事前審査を足す）・無人の run（`unattended=true`）は承認ノードで推しを採って進み、計画の壁打ちが安全の上限に届いた時は止める・計画の足す物と消す物をファイル構成の行にし、行ごとに考えの住処と退けた置き場を持たせる・修正の組の子の run が落ちたら run を止め、resume で続きから回す・受け付けに拒まれた出し直しを同じ役の会話の続きで直させる・字のぶつかりの印をファイルの中身と重ならない長さで書いて照らす、などが入る。
- スキルの深さの説明を 3 段に合わせ、無人の run の起こし方を書いた。

## [0.1.7] - 2026-10-15

### Changed

- 変更の記録の冒頭の、版の出し方の案内を直した（git の tag は作らない）。利用者に効く違いは無い。

## [0.1.6] - 2026-10-15

### Changed

- `works-factory/PIN` を raiki61/works-factory の 9365c286 に上げた。軽い依頼では run の頭で深さを決めて計画の事前審査を飛ばす（代わりに独立の目を必ず回す）・承認済みの受け入れ条件のテストが変わったら承認し直すかを人に問う・今の works から落ちていた能力の総点検と戻し・試験が走ったかを証拠が在る時だけ言う直しの残り・公開ベンチの台（プロキシの要る網・remote の無い課題・submodule の在る課題）が入る。
- スキルに、`findings` を省ける依頼と仕様の段の止め、報告の入口の深さの 1 行を書いた。

## [0.1.5] - 2026-10-14

### Changed

- `works-factory/PIN` を raiki61/works-factory の bfc23c48 に上げた。run の作業ツリーを対象の今の姿（commit していない変更を含む）から切る・一部の CI の系統が回せない時も回せた系統で進む・手元を指す `test_cmd` を起こす前に止める・「試験が走らなかった」を証拠が在る時だけ言う、が入る。
- スキルの起動の説明を、上の作業ツリーの起点と `test_cmd` の確かめに合わせた。

## [0.1.4] - 2026-10-14

### Changed

- `works-factory/PIN` を raiki61/works-factory の 53213e16 に上げた。試験が走らなかった時に報告の冒頭で名指す・試験のコマンドの環境を利用者が明示した時だけ家の設定に戻す・全部の AI ノードの出し直し・認証の案内・公開ベンチの台の直しが入る。
- スキルに、試験が家の設定を要る時の 2 つの道（手元で回す・`WORKS_FACTORY_TARGET_USER_ENV=1` を付ける）と、付けると資格に届くことを書いた。

## [0.1.3] - 2026-10-14

### Fixed

- スキルの起動の説明を実物に合わせた: 依頼は JSON のファイルのパスで渡す（文は受けない）。作業ツリーは `--from` を付けないと既定の枝から切られる。`test_cmd` を省いた時の動き。

## [0.1.2] - 2026-10-14

### Changed

- スキルに、keychain の項目の名を Claude Code の `settings.json` の `env` に `WORKS_FACTORY_KEYCHAIN_ITEM=<項目の名>` に当たる組を書いて渡す道と、「認証が無い」で止まった時に項目の名を推して試さず人に聞くことを書いた。

## [0.1.1] - 2026-10-14

### Changed

- 止めた commit（`works-factory/PIN`）を raiki61/works-factory の eefaa6c2 に上げる。周の鎖（`works-factory-chain`。頼まれた周の数まで回し、最後の差分と周ごとの表 chain.md を出す）・組の合わせ（並べた組を合わせて赤になったら合わせ役が直し、直せなければ裁定へ）・記録された方針だけを方針として扱う直し・審査する変更とこの run の直しの出どころを分ける直しが入る。

## [0.1.0] - 2026-10-14

### Added

- `/works-factory` スキル: 今いるリポジトリを対象に、修正依頼を works-factory（raiki61/works-factory）へ回す入口。今の `/works` には触らず、並べて置く（持ち主の決め `coexist-before-switch`）。
- 殻 `bin/works-factory`: 止めた commit（`works-factory/PIN`。raiki61/works-factory の 909588a9）を `${XDG_CACHE_HOME:-~/.cache}/works-factory-plugin/<commit>` に取り置き、その殻に引数をそのまま渡す。`apply` は差分を当てる口 `bin/apply` に渡す。
