# 版を出す手順

このリポジトリ（marketplace）で plugin の版を出すときの段を書く。配る plugin の全部（convergence-loops・gates・coldwrite・attention・graphloops）に同じ段が当たる。保守する人向けの文書で、利用者が読む物ではない。いつ出すか（頻度）は [ADR 0022](adr/0022-release-often.md)、tag と変更の記録の形を選んだ理由と、過去の版に付ける tag の一覧は [ADR 0066](adr/0066-release-tags-and-changelog.md) に在る。

## 平易版（3 行）

- 版を上げる commit で、その plugin の版の番号・marketplace の版の番号・その plugin の変更の記録（`CHANGELOG.md`）の 3 つを一緒に直す。
- main に入ったその commit に、`<plugin の名前>--v<版>` の名前の tag を付ける。tag を作って push するのは人。
- 作業枝では、利用者に効く違いをその plugin の変更の記録の `## [Unreleased]` に書き足していく。

## 置き場

どの plugin の置き場も、`.claude-plugin/marketplace.json` の `plugins[]` の `source` が指す plugin の根から決まる（一覧の正本はこの 1 か所で、ここに plugin ごとの表は写さない）。`source` が `./` の plugin（convergence-loops）は、リポジトリのルートが根になる。

- plugin の版: `<根>/.claude-plugin/plugin.json` の `version`。
- 変更の記録: `<根>/CHANGELOG.md`。プラグインのキャッシュに入るのは根の下の木だけなので、根に置く。
- marketplace の版: `.claude-plugin/marketplace.json` の `metadata.version`。catalog（plugin の一覧）の版で、plugin の版を上げるたびに一緒に上げる（これまでも大半の版上げで一緒に上げてきたが、上げなかった版もある）。

## 作業枝で

- 利用者に効く違い（足した口・変えた動き・直した不具合）を、その plugin の `<根>/CHANGELOG.md` の `## [Unreleased]` の下の節（Added・Changed・Fixed など）に 1 行ずつ書き足す。1 つの変更が複数の plugin に効くなら、それぞれの記録に書く。
- commit の id と作業枝の名前は書かない。作業枝の commit は main に入るときに作り直されるので、id は main から辿れない。この記録は利用者の手元（プラグインのキャッシュ）に届き、そこには git の履歴が無い。

## 版を上げる

1. `<根>/.claude-plugin/plugin.json` の `version` と、`.claude-plugin/marketplace.json` の `metadata.version` を上げる。
2. 同じ commit で、`<根>/CHANGELOG.md` の `## [Unreleased]` の中身を、新しい見出し `## [<版>] - <YYYY-MM-DD>` の下へ移す。`## [Unreleased]` の見出しは空で残す。
3. 版を上げる commit を作る。件名の形は `chore(<plugin の名前>): 版を上げる（<plugin の名前> <版> / marketplace <版>）`（graphloops が 0.20.0 から使っている形。それより前と、ほかの plugin の過去の版は、機能の commit の件名に版を括弧で添えていた）。
4. その commit を main に入れる。

1 つの commit で複数の plugin の版を上げるときは、上げた plugin のそれぞれで 1 と 2 をする（記録の見出しは plugin ごとに足す）。件名には上げた plugin を全部並べる。

`tests/run.sh` は、marketplace.json の一覧に在る全部の plugin について、`plugin.json` の今の版の見出し（`## [<版>] - <YYYY-MM-DD>`）がその plugin の `CHANGELOG.md` に在ることを確かめる。見るのは見出しが在ることまでで、中身が `## [Unreleased]` に残ったままの形は見ない。

## tag を付ける

- 名前は `<plugin の名前>--v<版>`（例: `gates--v0.11.3`・`graphloops--v0.21.1`）。Claude Code の公式の形に従う（[公式の文書の Create a release tag](https://code.claude.com/docs/en/plugins/dependencies)）。1 つのリポジトリの複数の plugin が、それぞれの版の歴を持てる形である。
- 付ける commit は、main に入った版上げの commit。その commit の `<根>/.claude-plugin/plugin.json` の `name` と `version` が、tag の名前の plugin と版に一致していること。1 つの commit で複数の plugin の版を上げたなら、その commit に plugin ごとの tag をそれぞれ付ける。
- marketplace の版（`metadata.version`）には tag を付けない。catalog ごと固定したい利用者は、plugin の tag をそのまま ref に渡せば、その commit の catalog 全体を固定できる。
- tag を作って push するのは人（外への書き込み）。作り方:
  - 版上げの commit が今の HEAD なら、公式の `claude plugin tag` で作る（作る前に、版の一致・作業ツリーがきれいなこと・同じ名前の tag が無いことを確かめる）。plugin の根で打つ。根が `./` の plugin（convergence-loops）はリポジトリのルートから打つ。
  - 過去の commit に付けるなら `git tag <plugin の名前>--v<版> <commit>`。付ける commit の一覧は [ADR 0066](adr/0066-release-tags-and-changelog.md) の「結果」に在る。
  - 作ったら `git push origin <plugin の名前>--v<版>`。
- 一度 push した tag は動かさない・消さない。tag で固定して入れている利用者が壊れる。
- どの版に tag が在るかは、リポジトリの tag の一覧（GitHub の tags か `git ls-remote --tags origin`）で確かめる。
