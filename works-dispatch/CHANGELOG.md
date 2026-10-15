# 変更の記録（works-dispatch）

works-dispatch（`/works-dispatch:dispatch` スキルと、`dispatch/` のスクリプト）の版ごとの、利用者に効く違いを新しい順に並べる。形は [Keep a Changelog 1.1.0](https://keepachangelog.com/ja/1.1.0/) に従い、版の番号は [Semantic Versioning](https://semver.org/lang/ja/) の形（x.y.z）で振る。節は Added（足した）・Changed（変えた）・Deprecated（やめる予定）・Removed（消した）・Fixed（直した）・Security（安全の直し）のうち、中身の有るものだけを使う。

版の出し方（この記録を書き足す段。git の tag は作らない）は、リポジトリのルートの `docs/releasing.md` に在る。0.1.0 は出していない。作った時に付けた版の後に変更を積んだので、初めて出す版を 0.1.1 にした。

## [Unreleased]

## [0.3.2] - 2026-10-15

### Fixed

- 起動のたびに `herdr.py` が SyntaxWarning（文字列の中の不正なエスケープ）を出していた。Python の先の版では読めなくなる形なので直し、works-dispatch の Python が警告なしに読めることを柵（tests/fences.py の compiles_clean）で縛った。
- 0.3.1 の直し（受け取ったパスを入口でそろえる）に、試験の期待が追いついておらず、Windows の CI が赤のままだった。試験の期待もそろえた形に合わせた。

## [0.3.1] - 2026-10-15

### Changed

- 前に送った後に相手の動き（自分以外のコメント・レビュー・commit。Bot は数えない）が無い PR は、会話が開いていなくても開き直さない（`no_news`）。返事待ちの PR を、会話を閉じただけでもう一度レビューしていた。PR の head が前に送った時と違えば（作者の push。force-push で古い時刻の commit が来ても）動きとして数える。`--pr N` で名指したときは今までどおり開く。
- 会話の開いている PR を送り直すかの判断でも、PR の head が前に送った時と違えば、新しい返事が有るとみなす（会話の開いていない PR の判断とそろえた）。

### Fixed

- Windows で、herdr や git が `/` 区切りで返す場所のパスと、手元で組んだ `\` 区切りのパスが食い違い、同じ場所を別の場所と見ていた。受け取った所で 1 回だけ区切りをそろえる。

## [0.3.0] - 2026-10-15

### Added

- `--issue N`。issue から始める作業の入口。issue に結んだ枝（`gh issue develop --list`）の作業場を開き、1 ターン目の `/catchup N` まで送って止める（2 ターン目の文は送らない）。結んだ枝が見えなければ、その issue を閉じる開いた PR の枝を使い、それも無ければ既定の枝から GitHub に枝を作って issue に結ぶ（`gh issue develop`）。報告の行は `issue #N` で始め、枝を出す。閉じた issue には枝を作らず `issue_closed` で止める。`--pr` とは一緒に使えない。
- 作業場の一生を 1 つのコマンドで回すようにした（引数なしで回すとき）。自分が作者でレビュアーの付いていない PR は開かない（`own_unreviewed`）。会話の開いている PR は、前に送った後に相手の新しい返事が有り、会話が手すきで手元の作業も無ければ、古い会話を終えて同じ場所で送り直す（`refreshed`）。閉じた PR の場所は最後に片付ける。送り直しも片付けも、終える会話は herdr が見ている会話のペインの物だけで（herdr の外の会話は終えない）、閉じる作業場はその場所の worktree の作業場だけ（ほかの作業場のペインがそのフォルダに cd していても閉じない）。その作業場にシェルでない物が居れば閉じない（`close_failed`）。片付けは、会話が 2 つ以上なら残し、会話を終えた後に一覧を取り直して居ないことを確かめてから消す。作者が force-push した枝は、場所の HEAD が前に送った時の head のままで場所がきれいなら、`git reset --keep` で origin に揃える（前に送った時の控え `dispatch-sent.json` に head も書く）。1 ターン目の終わりは、herdr の画面の見立てでなく Claude Code の会話の状態で見る。

### Changed

- 作業場を、PR ごとの clone（`<clone_root>/<名前>-pr-<番号>`）から、枝ごとの git worktree に替えた。代表の clone（設定の `source`）から、herdr（会話を走らせる端末を作業場とペインに分けて並べる道具）の `herdr worktree create` で作り、置き場は herdr の設定の `worktrees.directory`（既定 `~/.herdr/worktrees/<リポジトリ>/<枝>`）に任せる。作るときも使い直すときも、origin の今の head へ早送りしてから `/catchup` に渡す（手元にしか無い commit が有れば動かさない）。代表の clone 自身がその枝を開いていれば作らず `branch_busy` と報告する。fork の PR は作らず `provision_failed` と報告する。
- 報告の行の 3 つ目の欄を、作業場のフォルダの名前から枝の名前に替えた。
- `--check` は、設定の `source` が本体の clone か（linked worktree でないか）も確かめる。
- 片付け（`--clean`・一覧で回したときの最後）は、代表の clone の linked worktree だけを見る。枝の PR が閉じていて、会話が無く、手元の作業（未コミットの変更・git に足していないファイル・その枝の stash）も無く、手元の枝の先頭が PR の head と同じ場所だけ、worktree と手元の枝を消す。PR の無い枝は消さない。設定の `copy_files` のうち写し元と中身が違うファイルが有る場所は残して名指し、ほかの git が追わないファイル（依存・生成物）は一緒に捨てる。会話や herdr を読めなければ、traceback で止めずに、その場所を残して報告に書く。
- 1 件あたりの使用率の見積もりは、1 ターン目の終わりまで待った件だけから取る。`--no-second` と `--issue` の件は 1 ターン目を送ってすぐ測るので、`/catchup` がまだ使用率を使っていない時点の差（ほぼ 0）を 1 件あたりとして覚え、見積もりを小さくしていた。

### Removed

- 設定の `clone_root`。読まなくなった（設定に残っていても止めない。消してよい）。前の版が作った `<名前>-pr-<番号>` の clone は、この版の片付けの対象にならない。要らなければ手で消す。

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

- `/works-dispatch:dispatch` スキルと `dispatch/dispatch.py`。自分の番の PR（attention の whose-turn）を、PR ごとの作業場（代表の clone から作る `<名前>-pr-<番号>` の clone と、同じ名前の herdr の作業場）に開き、週の使用率のリセットが近いアカウント（95% を超えるものは外す）で Claude Code を起こして、`/<attention のプラグイン名>:catchup <番号>` と設定の 2 ターン目の文を送る。AI は使わない。開いている会話は閉じず、同じリポジトリとブランチの会話が開いていれば飛ばす。引数は `--dry-run`・`--pr N`・`--no-second`・`--clean [--apply]`・`--init`・`--check`。前提と、試しの実行で確かめた外の道具の振る舞いは README に在る。
- アカウントの書き方を 3 通りにした。`claude` をそのまま使う形、設定のフォルダを分ける形（鍵の Keychain の項目の名前を `keychain_service` で上書きできる）、使用率の枠の無い形（`limits = false`。Ollama・Foundry など）。数に決まりは無い。
- `dispatch/limits.py`（任意）。アカウントごとの使用率の控えを作り、herdr のタブ欄に 1 行ずつ出す。`herdr-config` が herdr の設定に貼る行を出す。
- `dispatch/activity.py`（任意）。Claude Code のフックから、herdr のサイドバーに会話ごとの作業内容を出す。`activity.py settings` が settings.json に足す hooks の塊を出す。
- `--check` が、アカウントごとの herdr の連携と、herdr の設定やフックが消えたプラグインのフォルダを指していないかも見る。
