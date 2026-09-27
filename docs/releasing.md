# 版を出す手順

このリポジトリ（marketplace）で graphloops の版を出すときの段を書く。保守する人向けの文書で、利用者が読む物ではない。いつ出すか（頻度）は [ADR 0022](adr/0022-release-often.md)、tag と変更の記録の形を選んだ理由は [ADR 0066](adr/0066-release-tags-and-changelog.md) に在る。

## 平易版（3 行）

- 版を上げる commit で、plugin の版の番号・marketplace の版の番号・変更の記録（`graphloops/CHANGELOG.md`）の 3 つを一緒に直す。
- main に入ったその commit に、`graphloops--v<版>` の名前の tag を付ける。tag を作って push するのは人。
- 作業枝では、利用者に効く違いを変更の記録の `## [Unreleased]` に書き足していく。

## 版の番号の置き場

- plugin の版: `graphloops/.claude-plugin/plugin.json` の `version`。
- marketplace の版: `.claude-plugin/marketplace.json` の `metadata.version`。catalog（plugin の一覧）の版で、graphloops の版を上げるたびに一緒に上げてきた。

## 作業枝で

- 利用者に効く違い（足した口・変えた動き・直した不具合）を、`graphloops/CHANGELOG.md` の `## [Unreleased]` の下の節（Added・Changed・Fixed など）に 1 行ずつ書き足す。
- commit の id と作業枝の名前は書かない。作業枝の commit は main に入るときに作り直されるので、id は main から辿れない。この記録は利用者の手元（プラグインのキャッシュ）に届き、そこには git の履歴が無い。

## 版を上げる

1. `graphloops/.claude-plugin/plugin.json` の `version` と、`.claude-plugin/marketplace.json` の `metadata.version` を上げる。
2. 同じ commit で、`graphloops/CHANGELOG.md` の `## [Unreleased]` の中身を、新しい見出し `## [<版>] - <YYYY-MM-DD>` の下へ移す。`## [Unreleased]` の見出しは空で残す。
3. 版を上げる commit を作る（件名の形は今までどおり `chore(graphloops): 版を上げる（graphloops <版> / marketplace <版>）`）。
4. その commit を main に入れる。

`tests/run.sh` は、`plugin.json` の今の版の見出し（`## [<版>] - <YYYY-MM-DD>`）が `graphloops/CHANGELOG.md` に在ることを確かめる。見るのは見出しが在ることまでで、中身が `## [Unreleased]` に残ったままの形は見ない。

## tag を付ける

- 名前は `graphloops--v<版>`（例: `graphloops--v0.21.1`）。Claude Code の公式の形 `<plugin の名前>--v<版>` に従う（[公式の文書の Create a release tag](https://code.claude.com/docs/en/plugins/dependencies)）。1 つのリポジトリの複数の plugin が、それぞれの版の歴を持てる形である。
- 付ける commit は、main に入った版上げの commit。その commit の `graphloops/.claude-plugin/plugin.json` の `version` が、tag の名前の版と一致していること。
- marketplace の版（`metadata.version`）には tag を付けない。catalog ごと固定したい利用者は、plugin の tag をそのまま ref に渡せば、その commit の catalog 全体を固定できる。
- tag を作って push するのは人（外への書き込み）。作り方:
  - 版上げの commit が今の HEAD なら、公式の `claude plugin tag` で作る（作る前に、版の一致・作業ツリーがきれいなこと・同じ名前の tag が無いことを確かめる）。
  - 過去の commit に付けるなら `git tag graphloops--v<版> <commit>`。
  - 作ったら `git push origin graphloops--v<版>`。
- 一度 push した tag は動かさない・消さない。tag で固定して入れている利用者が壊れる。
