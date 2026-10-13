# 変更の記録（works-factory）

works-factory の Claude Code 側の入口（`/works-factory` スキルと殻 `bin/works-factory`）の版ごとの、利用者に効く違いを新しい順に並べる。形は [Keep a Changelog 1.1.0](https://keepachangelog.com/ja/1.1.0/) に従い、版の番号は [Semantic Versioning](https://semver.org/lang/ja/) の形（x.y.z）で振る。節は Added（足した）・Changed（変えた）・Deprecated（やめる予定）・Removed（消した）・Fixed（直した）・Security（安全の直し）のうち、中身の有るものだけを使う。

版を名指しする git の tag の名前の決まり・付け方と、この記録を書き足す段は、リポジトリのルートの `docs/releasing.md` に在る。

## [Unreleased]

## [0.1.0] - 2026-10-14

### Added

- `/works-factory` スキル: 今いるリポジトリを対象に、修正依頼を works-factory（raiki61/works-factory）へ回す入口。今の `/works` には触らず、並べて置く（持ち主の決め `coexist-before-switch`）。
- 殻 `bin/works-factory`: 止めた commit（`works-factory/PIN`。raiki61/works-factory の 909588a9）を `${XDG_CACHE_HOME:-~/.cache}/works-factory-plugin/<commit>` に取り置き、その殻に引数をそのまま渡す。`apply` は差分を当てる口 `bin/apply` に渡す。
