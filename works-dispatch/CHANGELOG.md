# 変更の記録（works-dispatch）

works-dispatch（`/works-dispatch:dispatch` スキルと、`dispatch/` のスクリプト）の版ごとの、利用者に効く違いを新しい順に並べる。形は [Keep a Changelog 1.1.0](https://keepachangelog.com/ja/1.1.0/) に従い、版の番号は [Semantic Versioning](https://semver.org/lang/ja/) の形（x.y.z）で振る。節は Added（足した）・Changed（変えた）・Deprecated（やめる予定）・Removed（消した）・Fixed（直した）・Security（安全の直し）のうち、中身の有るものだけを使う。

版の出し方（この記録を書き足す段。git の tag は作らない）は、リポジトリのルートの `docs/releasing.md` に在る。0.1.0 は出していない。作った時に付けた版の後に変更を積んだので、初めて出す版を 0.1.1 にした。

## [Unreleased]

## [0.3.0] - 2026-10-15

### Added

- PR ごとの作業場の一生を、引数なしの 1 つのコマンドで回すようにした。
  - 会話の開いている自分の番の PR は、前に送った後に相手の新しい返事（コメント・レビュー・commit。Bot は数えない）が有り、会話が手すきで未コミットの変更も push していない commit も無ければ、古い会話を終えてペインを畳み、同じフォルダに新しい作業場と会話を立てて `/catchup` から送り直す（結末 `refreshed`）。送り直さなかった理由は `no_news`・`busy`・`dirty`・`unpushed` で出る。
  - 閉じた（merge・close した）PR の作業場は、最後に片付ける。会話が手すきで手元の作業も無ければ、会話を終えてから消す。名前が同じでも origin が別のリポジトリの clone には触らない。`--dry-run` は片付ける物を並べるだけ。
  - 自分が作者でレビュアーの付いていない PR は開かない（`own_unreviewed`）。`--pr` で指せば開く。

### Fixed

- `/catchup` の返事が終わっても、会話が裏に待ちのコマンドを残していると、2 ターン目が送られず、報告も出なかったのを直した。herdr は画面の下の行で作業中かを決めるので、作業中と見続けていた。1 ターン目の終わりを、Claude Code 自身が返す会話の状態（`claude agents --json`）で見るようにした。

## [0.2.1] - 2026-10-15

### Changed

- 写した共通の部品（`dispatch/vendor/claude_auth.py`）の注記と、変更の記録の冒頭の案内を直した。利用者に効く違いは無い。

## [0.2.0] - 2026-10-15

### Changed

- PR を 1 つのアカウントに全部入れず、アカウントの使用率の残りに合わせて割り振るようにした。全部の PR の `/catchup` は同時に走るので、始める前に件数を決める。各アカウントに、週と 5 時間の枠の使用率が上限（既定 95%）に届かない件数まで入れ、あふれた分を次のアカウントへ回す。1 件あたりの使用率は、dispatch が毎回、始める前と全部の `/catchup` の後に使用率を問い合わせて（出力 0 トークン）測り、`<limits_dir>/dispatch-cost.json` に覚える。まだ測っていないうちは、選べるアカウントに 1 件ずつ順に配る。報告の頭に、何をもとに割り振ったかを 1 行で出す。`--dry-run` は問い合わせない。

## [0.1.4] - 2026-10-15

### Fixed

- Windows で、`--clean --apply` が PR ごとの clone を消せなかった。Windows の git は `.git/objects/` の中を読み取り専用で作るので、そのままでは消せない。読み取り専用を外して消し直す。作業場を作りかけで失敗したときの片付けも同じ理由で作りかけを残し、次の回にそれを別のリポジトリのフォルダとみなしていた。これも直した。
- Windows で、作業場のペインのシェルを POSIX のシェル（`/bin/sh`）で起こそうとして落ちていた。POSIX のシェルが無ければ、コマンドは PATH の上で探し、ペインは既定のフォルダとみなす。
- Windows の `\` の区切りのパスで、消えたプラグインのパスの検出（`--check`）が古いパスを見落とすか、別のパスを報告していた。手元のパスの origin から OWNER/NAME を取れず、作った clone の読み戻しが落ちていた。`limits.py herdr-config` が出す行も、`\` を含むパスで herdr の TOML を壊していた。

### Changed

- `--clean --apply` は、1 件でも消せなければ終了コード 1 で終わる（前は 0）。

## [0.1.3] - 2026-10-15

### Fixed

- herdr のタブ欄に貼った `limits.py` の行が、macOS で起動できずに何も出さなかった。herdr がタブ欄のコマンドに渡す PATH では、`python3` が OS に付いてくる Python 3.9 になり、設定の TOML を読む `tomllib`（3.11 から）が無い。`limits.py herdr-config` がアカウントの一覧の写し（`<limits_dir>/accounts.json`）を書き、タブ欄の行は TOML の代わりにそれを読むようにした。行は PATH の `python3` か `python` を使い、マシンごとの絶対パスは書かない。前の版の行を貼った人は、`herdr-config` を走らせ直して行を貼り直す。

## [0.1.2] - 2026-10-15

### Fixed

- 週か 5 時間の使用率がちょうど上限（既定 95%）のアカウントを、選べる側に残していた。使用率は 1% 刻みの整数で届くので、95 と書かれたアカウントは 95% を超えている見込みがある。上限に達したアカウントは外す。設定の `limit_percent` の意味も「これに達したら使わない」に変わる。

## [0.1.1] - 2026-10-15

### Added

- `/works-dispatch:dispatch` スキルと `dispatch/dispatch.py`。自分の番の PR（attention の whose-turn）を、PR ごとの作業場（代表の clone から作る `<名前>-pr-<番号>` の clone と、同じ名前の herdr の作業場）に開き、週の使用率のリセットが近いアカウント（95% を超えるものは外す）で Claude Code を起こして、`/<プラグイン名>:catchup <番号>` と設定の 2 ターン目の文を送る。AI は使わない。開いている会話は閉じず、同じリポジトリとブランチの会話が開いていれば飛ばす。引数は `--dry-run`・`--pr N`・`--no-second`・`--clean [--apply]`・`--init`・`--check`。前提と、試しの実行で確かめた外の道具の振る舞いは README に在る。
- アカウントの書き方を 3 通りにした。`claude` をそのまま使う形、設定のフォルダを分ける形（鍵の Keychain の項目の名前を `keychain_service` で上書きできる）、使用率の枠の無い形（`limits = false`。Ollama・Foundry など）。数に決まりは無い。
- `dispatch/limits.py`（任意）。アカウントごとの使用率の控えを作り、herdr のタブ欄に 1 行ずつ出す。`herdr-config` が herdr の設定に貼る行を出す。
- `dispatch/activity.py`（任意）。Claude Code のフックから、herdr のサイドバーに会話ごとの作業内容を出す。`activity.py settings` が settings.json に足す hooks の塊を出す。
- `--check` が、アカウントごとの herdr の連携と、herdr の設定やフックが消えたプラグインのフォルダを指していないかも見る。
