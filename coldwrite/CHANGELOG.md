# 変更の記録（coldwrite）

coldwrite の版ごとの、利用者に効く違いを新しい順に並べる。形は [Keep a Changelog 1.1.0](https://keepachangelog.com/ja/1.1.0/) に従い、版の番号は [Semantic Versioning](https://semver.org/lang/ja/) の形（x.y.z）で振る。節は Added（足した）・Changed（変えた）・Deprecated（やめる予定）・Removed（消した）・Fixed（直した）・Security（安全の直し）のうち、中身の有るものだけを使う。

版を名指しする git の tag（例: `coldwrite--v0.1.3`）の名前の決まり・付け方・付ける commit の一覧への案内と、この記録を書き足す段は、リポジトリのルートの `docs/releasing.md` に在る（プラグインとして入れた実体には無いので、clone か GitHub で見る: https://github.com/raiki61/claude-plugins/blob/main/docs/releasing.md）。

## [Unreleased]

## [0.1.3] - 2026-08-30

### Fixed

- 詰まりで止められるとターンが終わり、人が次に話すまで書き手が直せなかった。6 つのフックすべてを止めた後も続ける設定にした（Claude Code 2.1.210 以降の既定の変化への対応）。

## [0.1.2] - 2026-08-28

### Added

- 1 回限りの逃げ道: 書く中身の 1 行目に `coldwrite:skip` を書くと通す。2 行目以降に書いても効かない。

### Changed

- 通過と対象外が外から区別できないこと、coldread との二重の検査になることを、試作の制約として README に書いた。

## [0.1.1] - 2026-08-28

### Changed

- 対象を散文の 6 拡張子（.md・.mdx・.adoc・.asciidoc・.rst・.txt）に広げた。それ以外の拡張子では判定モデルを起こさない。

## [0.1.0] - 2026-08-28

### Added

- Write で書かれる .md・.adoc の散文を、書き込む前に coldreader（文脈を持たない初見の読み手）に読ませ、詰まりが直るまで止める prompt 型のフック。短い文書やコードが主体の文書は通す。
- Edit は対象外。判定モデルは指定せず、既定の高速モデルに従う。
