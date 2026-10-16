# 版を出す手順

このリポジトリ（marketplace）で plugin の版を出すときの段を書く。配る plugin の全部（`.claude-plugin/marketplace.json` の `plugins[]` に並ぶ全部）に同じ段が当たる。保守する人向けの文書で、利用者が読む物ではない。いつ出すか（頻度）は [ADR 0022](adr/0022-release-often.md) に在る。

## 平易版（3 行）

- 版は works-dispatch の `--land`（部署の枝を main に入れる命令）が上げる。版を上げる commit で、上げる plugin ごとの版の番号・marketplace の版の番号・上げる plugin ごとの変更の記録（`CHANGELOG.md`）の 3 つを一緒に直し、その commit を枝の最後に置く。
- 出荷は main への push で終わる。`--land` は CI を待たない（持ち主の方針 2026-10-16。会社の形 `.claude/company.toml` の `[land]` のコメント）。CI は入った後の赤を見つける。git の tag は作らない（持ち主の決め 2026-09-29「タグはつくりません」）。
- 作業枝では、利用者に効く違いをその plugin の変更の記録の `## [Unreleased]` に書き足していく。

## 置き場

どの plugin の置き場も、`.claude-plugin/marketplace.json` の `plugins[]` の `source` が指す plugin の根から決まる（一覧の正本はこの 1 か所で、ここに plugin ごとの表は写さない）。どの plugin も自分のフォルダを根に持ち、リポジトリの根を `source` にしない（根を配ると、キャッシュに写るのがリポジトリの木の全部になる。`tests/run.sh` が赤にする）。

- plugin の版: `<根>/.claude-plugin/plugin.json` の `version`。
- 変更の記録: `<根>/CHANGELOG.md`。プラグインのキャッシュに入るのは根の下の木だけなので、根に置く。
- marketplace の版: `.claude-plugin/marketplace.json` の `metadata.version`。catalog（plugin の一覧）の版で、plugin の版を上げるたびに一緒に上げる。

## 作業枝で

- 利用者に効く違い（足した口・変えた動き・直した不具合）を、その plugin の `<根>/CHANGELOG.md` の `## [Unreleased]` の下の節（Added・Changed・Fixed など）に 1 行ずつ書き足す。1 つの変更が複数の plugin に効くなら、それぞれの記録に書く。
- commit の id と作業枝の名前は書かない。この記録は利用者の手元（プラグインのキャッシュ）に届き、そこには git の履歴が無い。
- 中身の無い版（`## [Unreleased]` が空のまま見出しだけ足して上げる版）は作らない。plugin の根の下のファイルを変えたら、文面だけの直しでも、何が変わったかを `## [Unreleased]` に 1 行書く。版を上げずに済ませる道は無い（marketplace は版が変わった時だけ中身を取り直すので、上げなければ変えた中身が利用者に届かない。`tests/run.sh` の `VERSION_BUMP_OK` も、ファイルを変えたのに版が据え置きの plugin を、main と release/* の CI で赤にする）。works-dispatch の `--land`（部署の枝を main に入れる命令。使い方は `works-dispatch/skills/dispatch/SKILL.md` の「本流に入れる: `--land 部署`」、順と決まりの全部は `works-dispatch/docs/land.md`）は、版を上げる段で、ファイルを変えたのに `## [Unreleased]` が空の plugin を見つけると、版を上げずに止める（違いを書き足して commit し、`--land` を打ち直す）。

## 版を上げる

ふだんは `--land` が上げる。部署は版を上げずに枝を出し、`--land <部署の名前>` を打つ。`--land` は会社の形（`.claude/company.toml`）の `[land]` に従って、次をする（`bump = "marketplace"`・`gate = "check"` のとき。順の全部は `works-dispatch/docs/land.md`）。

1. 一時の場所（枝に乗らない git worktree）で、部署の枝の先頭の上に版を上げる commit を作る。上げるのは、版を最後に上げた後にフォルダの中のファイルを 1 つでも変えた plugin だけ（試験や文書だけの直しも入る。そのときの上げ幅は patch）。上げ幅は下の「上げ幅の決め方」による。`## [Unreleased]` の中身を新しい見出し `## [<版>] - <YYYY-MM-DD>` の下へ移し、`## [Unreleased]` の見出しは空で残す。件名の形は `chore(<plugin の名前>, …): 版を上げる（<plugin の名前> <版> / … / marketplace <版>）`。
2. その場所で、`[land]` の `check` のコマンド（関門）を回す。全段の試験は回さない。
3. 関門が緑なら、main をその commit へ早送りして push する。CI は待たない。

版上げの後に plugin の中身を変える commit を積むと、main の CI が赤になる（中身を変えたのに版が据え置きの plugin を、`tests/run.sh` の `VERSION_BUMP_OK` が赤にする）。`--land` は版を上げる commit を必ず枝の最後に置くので、この形にならない。

`--land` を通さずに手で上げるときは、上の 1 を手でし、2 の `check` のコマンドも手で回してから、その commit を枝の最後に置いたまま main に push する。版上げの順の検査は main と release/* の CI でだけ厳しくなるので、手元では `VERSION_BUMP_STRICT=1 bash tests/run.sh` で確かめる。

1 つの commit で複数の plugin の版を上げるときは、上げた plugin のそれぞれで版の番号と記録の見出しを直す（記録の見出しは plugin ごとに足す）。件名には上げた plugin を全部並べる。`--land` もこの形で上げる。

`tests/run.sh` は、marketplace.json の一覧に在る全部の plugin について、`plugin.json` の今の版の見出し（`## [<版>] - <YYYY-MM-DD>`）がその plugin の `CHANGELOG.md` に在ることを確かめる。見るのは見出しが在ることまでで、中身が `## [Unreleased]` に残ったままの形は見ない。

## 上げ幅の決め方

版の番号は x.y.z（[Semantic Versioning](https://semver.org/lang/ja/) の形）。上げるのは、版を最後に上げた後にフォルダの中のファイルを変えた plugin だけ（「版を最後に上げた後」は、`plugin.json` の `version` が今の値になった commit より後。数え方は `tests/run.sh` の `VERSION_BUMP_OK` と同じ）。手で上げるときも、works-dispatch の `--land` が上げるときも、上げ幅は次の順で決める。

1. 版を最後に上げた後にその plugin の中で変えたファイルが、試験と文書（下の一覧）だけなら、patch（x.y.Z）を上げる。`## [Unreleased]` にどの節が有っても patch にする。Semantic Versioning の minor は機能を足したときに上げる物で、利用者が動かす物を変えていない直しには当たらないため。
2. そうでなければ、`## [Unreleased]` に Added・Changed・Deprecated・Removed のどれかの節が有れば minor（x.Y.0）を上げ、無ければ（Fixed・Security だけなら）patch を上げる。`## [Unreleased]` に中身が無いときは上げない（上の「作業枝で」の節。`--land` も止まる）。
3. marketplace の版は、同じ commit で上げる plugin のうち minor を上げた物が 1 つでも有れば minor、無ければ patch を上げる。

試験と文書に数えるのは次の物で、深さによらず、plugin のフォルダの中のどこに在っても同じ:

- `tests`・`test`・`docs` という名前のフォルダの下のファイル
- `test_*.py`・`*_test.py`・`conftest.py`
- plugin のフォルダの直下の `README.md`・`CHANGELOG.md`・`CONTRIBUTING.md`・`LICENSE`（直下だけ。`skills/foo/README.md` は入らない）
- `.claude-plugin/plugin.json` のうち、説明（`description`）の字だけを変えたとき（版を最後に上げた時の中身と比べて、`description` のほかの欄が同じ）

これ以外は全部、利用者が動かす物に数える。`SKILL.md`・エージェントの `.md` と、`description` のほかの欄も変えた `plugin.json` もそちら（Claude Code が読んで動く物なので）。この一覧の正本は `works-dispatch/dispatch/nodes/bump.py` の `quiet` と `manifest_text_only`（`plugin.json` の説明の字だけの直し）で、ずれたらそちらが正しい。`--land` が 1 に当たって patch にしたときは、画面に注記を出す。

major（X.0.0）は `--land` では上がらない。今の版はどれも 0.x で（Semantic Versioning では、0.y.z の間は何が変わってもよい扱い）、互換を壊す変更（Removed など）も minor を上げる。

## tag を作らない理由と、依存の版の範囲

- graphloops は `dependencies` に convergence-loops の版の範囲（下限）を書いている。Claude Code の文書は、範囲に合う git の tag から入れると書くが、相対パスの plugin（このリポジトリの全部）で範囲に合う tag が無いときは、marketplace の今の写しを使い、読み込むときに範囲を確かめ、外れていれば依存する側を無効のままにする（[公式の文書](https://code.claude.com/docs/en/plugins/dependencies)）。tag を作らないこのリポジトリでは、依存は main の今の版で解決する。
- だから graphloops の下限を上げるのは、graphloops が新しい版の口を呼ぶようになったときだけにし、上げるなら同じ main に convergence-loops のその版が先に入っていること。下限が main の版より上だと、graphloops が読み込まれない。`graphloops/tests/py/test_intake.py` が、下限がリポジトリの convergence-loops の版以下であることを確かめる。
- [ADR 0066](adr/0066-release-tags-and-changelog.md) は tag の名前の形（`<plugin の名前>--v<版>`）と付ける commit を決めたが、tag は 1 つも作っていない（2026-10-15 に `git ls-remote --tags origin` で 0 件）。その決めは [ADR 0073](adr/0073-land-bumps-and-no-tags.md) が置き換えた。
