# works

持ち主の普段の作業を Archon（AI の工程を YAML で書いて機械が順に回す道具）の上に移す pack。最初の生産ライン `darkfactory` は、人の修正依頼を判定 → 修正 → テスト → 人の承認 → 修正の審査の順に流す。並べ方は Archon に任せ、差を付けるのは各節の受け付け——graphloops（このリポジトリの既存のプラグイン）の規則と記録の検証器を `.shared/core/` に写して使い、中身が通ったときだけ次へ進める。

## 入れ方

```
archon plugin install raiki61/claude-plugins/works@<tag>
```

## 開発の回し方

テストは `works/tests/run.sh`。実際に Archon の上で回す手順（実行ファイルの取得・使い捨ての対象作り・`archon workflow test` 相当の検査）は `works/dev/` を見る。

## 仕様

設計の正本は [`docs/specs/2026-09-26-darkfactory-design.md`](docs/specs/2026-09-26-darkfactory-design.md)。実装計画は [`docs/plans/2026-09-26-darkfactory-v1.md`](docs/plans/2026-09-26-darkfactory-v1.md)。
