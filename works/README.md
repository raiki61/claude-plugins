# works

持ち主の普段の作業を Archon（AI の工程を YAML で書いて機械が順に回す道具）の上に移す pack。最初の生産ライン `darkfactory` は、人の修正依頼を判定 → 修正 → テスト → 人の承認 → 修正の審査の順に流す。並べ方は Archon に任せ、差を付けるのは各節の受け付け——graphloops（このリポジトリの既存のプラグイン）の規則と記録の検証器を `.shared/core/` に写して使い、中身が通ったときだけ次へ進める。

## 入れ方

```
archon plugin install raiki61/claude-plugins/works@<tag>
```

## Claude Code のスキル

`skills/works/SKILL.md`（`/works`）に、依頼の JSON の書き方・起動の 1 行・人の関所での答え方を置く。Claude Code のプラグインの定義は `.claude-plugin/plugin.json`。

持ち主に確かめること: Claude Code のプラグインとして配るには、リポジトリ直下の `.claude-plugin/marketplace.json` に works の 1 行が要る。共有のファイルなので、まだ足していない。

## 開発の回し方

テストは `works/tests/run.sh`。実際に Archon の上で回す手順（実行ファイルの取得・使い捨ての対象作り・`archon workflow test` 相当の検査）は `works/dev/` を見る。

`works/dev/archon.sh`（固定した版の Archon を隔離して回す殻）の認証に既定の口座は無い。AI を呼ぶ実行（`workflow run`・`workflow test`・`dev/check.sh`）の前に、次のどちらかを設定する:

1. `CLAUDE_CODE_OAUTH_TOKEN`（`claude setup-token` で作るトークン）
2. `WORKS_KEYCHAIN_ITEM`（そのトークンを入れた macOS の keychain の項目名。`security find-generic-password -s <名> -w` で読む）

両方あれば 1 を使う。どちらも無ければ、案内を 1 行出して止まる。`WORKS_DEV_NO_AUTH=1` のときは認証を読まない（テスト・`validate` 用）。

## 仕様

設計の正本は [`docs/specs/2026-09-26-darkfactory-design.md`](docs/specs/2026-09-26-darkfactory-design.md)。実装計画は [`docs/plans/2026-09-26-darkfactory-v1.md`](docs/plans/2026-09-26-darkfactory-v1.md)。
