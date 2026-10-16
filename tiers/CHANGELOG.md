# 変更の記録（tiers）

tiers（`/tiers:check` スキルと `bin/tiers`）の版ごとの、利用者に効く違いを新しい順に並べる。形は [Keep a Changelog 1.1.0](https://keepachangelog.com/ja/1.1.0/) に従い、版の番号は [Semantic Versioning](https://semver.org/lang/ja/) の形（x.y.z）で振る。

版の出し方（この記録を書き足す段。git の tag は作らない）は、リポジトリのルートの `docs/releasing.md` に在る。

## [Unreleased]

## [0.1.0] - 2026-10-16

### Added

- 要る道具の段ごとの点検 `tiers --tier N [--launcher 命令 ...] [--json]`。段 0: Claude Code、段 1: gh（入っているか・ログイン済みか）、段 2: herdr（入っているか・動いているか）とアカウントの起こし方の命令、段 3: Archon。足りない物と、OS ごとの入れ方を返し、何も入れない。
- 人が同じ点検を走らせる `/tiers:check` スキル。
