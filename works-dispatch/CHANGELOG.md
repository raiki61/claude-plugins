# 変更の記録（works-dispatch）

works-dispatch（`/works-dispatch:dispatch` スキルと、`dispatch/` のスクリプト）の版ごとの、利用者に効く違いを新しい順に並べる。形は [Keep a Changelog 1.1.0](https://keepachangelog.com/ja/1.1.0/) に従い、版の番号は [Semantic Versioning](https://semver.org/lang/ja/) の形（x.y.z）で振る。節は Added（足した）・Changed（変えた）・Deprecated（やめる予定）・Removed（消した）・Fixed（直した）・Security（安全の直し）のうち、中身の有るものだけを使う。

版を名指しする git の tag の名前の決まり・付け方と、この記録を書き足す段は、リポジトリのルートの `docs/releasing.md` に在る。0.1.0 は出していない。作った時に付けた版の後に変更を積んだので、初めて出す版を 0.1.1 にした。

## [Unreleased]

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
