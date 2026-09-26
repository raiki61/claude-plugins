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

## 実走

本物の AI でライン `darkfactory` を 1 回回す殻が `works/dev/real-run.sh`（費用が掛かる。回す前に持ち主の了承を取る）。

1. `WORKS_KEYCHAIN_ITEM=<keychain の項目名> sh works/dev/real-run.sh [<dir>]` を前景で打つ。使い捨ての対象を作り、隔離した Archon の設定に既定の模型（`WORKS_DEV_MODEL`、既定は opus）を書き、人の関所で止まって戻る。
2. 関所の文面の「テストが緑か」「テストのログ」と、殻が出す「修正の差分がある worktree」を見る。修正は対象ではなく、Archon が run ごとに切った worktree の中にある。
3. 殻が出す approve のコマンドを打つ。承認はその場で続き（差分の審査）を回して終わる。`resume` は失敗・中断から続けるときだけ要る。

### 結果（2026-09-26・Archon v0.11.1・opus・3 回）

| run | 仕掛け | 関所まで | 承認から終わり | 費用 | 拒否 | 審査の穴 |
|---|---|---|---|---|---|---|
| 4d11a59b | 無し | 3分00秒 | 1分20秒 | $0.59 | 0 | 0 |
| 3e5bcda1 | 未追跡のファイル | 3分00秒 | 1分02秒 | $0.66 | 2 | 2 |
| 62915c41 | 空の commit | 1分44秒 | 50秒 | $0.45 | 0 | 0 |

費用は Archon が節ごとに記録した額（OAuth の名目の額）の合計で、3 回で $1.70。1 回の内訳はおおよそ判定 $0.15〜0.22・修正 $0.16〜0.20・審査 $0.14〜0.16。

- 赤になった所は無い。3 回とも判定の輪が通り、修正の後の `python3 -m unittest -q` が緑、関所で止まり、承認の後に差分の審査が `ok: true` で終わった。
- run 3e5bcda1 では、読むだけの役（判定・審査）の 1 周目の間だけ worktree に未追跡のファイルを置き、受け付けに 1 回ずつ拒ませた。2 周目のプロンプトに拒んだ理由がそのまま貼られ（1 周目は空）、2 周目は 1 周目の会話の続き（Archon が 1 周目の会話を fork して続ける）で出し直し、通った。
- run 62915c41 では、依頼の受け付けの後に worktree で空の commit を打って HEAD を動かした。判定の受け付けは HEAD ではなく周の頭の版（`base` の出力）で数えた。ラインの `base_rev` が script の節まで届いている。
- 判定役・修正役・審査役は 3 回とも別々の新しい会話で始まった（前の役の会話を引き継がない）。
- run 3e5bcda1 の審査が挙げた 2 件は本物の指摘: 修正役が docstring に「statistics.mean・numpy.clip と同じ定義」と書き足したが、空の列・`lo > hi` のときは一致しない（宣言と実装のずれ）。
- 回すのに要った準備: Archon は run ごとに切る worktree の元を remote から取るので、remote の無い対象では止まる（`real-run.sh` が対象の外に裸のリポジトリを作って origin にする）。隔離した HOME からは `~/.local/bin/claude` を見つけられないので、`CLAUDE_BIN_PATH` を渡す。

## 仕様

設計の正本は [`docs/specs/2026-09-26-darkfactory-design.md`](docs/specs/2026-09-26-darkfactory-design.md)。実装計画は [`docs/plans/2026-09-26-darkfactory-v1.md`](docs/plans/2026-09-26-darkfactory-v1.md)。
