# 変更の記録（works-dispatch）

works-dispatch（`/works-dispatch:dispatch` スキルと、`dispatch/` のスクリプト）の版ごとの、利用者に効く違いを新しい順に並べる。形は [Keep a Changelog 1.1.0](https://keepachangelog.com/ja/1.1.0/) に従い、版の番号は [Semantic Versioning](https://semver.org/lang/ja/) の形（x.y.z）で振る。節は Added（足した）・Changed（変えた）・Deprecated（やめる予定）・Removed（消した）・Fixed（直した）・Security（安全の直し）のうち、中身の有るものだけを使う。

版を名指しする git の tag の名前の決まり・付け方と、この記録を書き足す段は、リポジトリのルートの `docs/releasing.md` に在る。

## [Unreleased]

### Added

- `/works-dispatch:dispatch` スキルと `dispatch/dispatch.py`。自分の番の PR（attention の whose-turn）を、PR ごとの作業場（代表の clone から作る `<名前>-pr-<番号>` の clone と、同じ名前の herdr の作業場）に開き、週の使用率のリセットが近いアカウント（95% を超えるものは外す）で Claude Code を起こして、`/<プラグイン名>:catchup <番号>` と設定の 2 ターン目の文を送る。AI は使わない。開いている会話は閉じず、同じリポジトリとブランチの会話が開いていれば飛ばす。引数は `--dry-run`・`--pr N`・`--no-second`・`--clean [--apply]`・`--init`・`--check`。前提と、試しの実行で確かめた外の道具の振る舞いは README に在る。
