# 0066. 版ごとに plugin の tag と変更の記録を残す

- 状態: 採用
- 日付: 2026-09-27
- 決めた人: 判定役（review-graph の判定から入る run の 1 周目）。marketplace の版に tag を付けないことは判定役の推し。tag の名前の形は、tag を前提に入れる別の作業が形を名指ししていないことを、人の側が確かめた
- 実装: 作業枝で済み（main の版には未収録）

## 文脈

- 版の tag が 1 本も無く、変更の記録も無かった。版は「fix か feat の 1 commit と版上げの 1 commit」で main に入り、版の中身は commit の本文にしか残らなかった。
- engine は版の番号を報告の頭と intake の記録に刻むが、利用者の手元（プラグインのキャッシュ）には git の履歴が無く、版の番号から中身へ辿れない。
- Claude Code の固定の口（marketplace の ref・plugin の source の ref）と依存の版の範囲の解決は、名前の付いた ref を前提にする。tag を前提に入れる別の作業も現れた。
- [0022](0022-release-often.md) で版を 1 日 1 回ほどの速さで出すので、版と中身の対応が無い害が速く積もる。

## 決定

- 変更の記録は Keep a Changelog 1.1.0 の形で `graphloops/CHANGELOG.md` に置く。プラグインのキャッシュに入るのは marketplace の source の `./graphloops` の木だけなので、そこに置く。
- tag の名前は Claude Code の公式の形 `<plugin の名前>--v<版>`（graphloops なら `graphloops--v<版>`）。付ける commit は main に入った版上げの commit で、その commit の plugin.json の版と tag の名前の版が一致すること。
- marketplace の版（`metadata.version`）には tag を付けない。
- 版上げの commit で変更の記録の見出しを足し、`tests/run.sh` が今の版の見出しの在ることを確かめる。
- tag を作って push するのは人。手順の正本は [docs/releasing.md](../releasing.md)。

## 比べた案

- commit の件名で代える（捨てた案）: 利用者のキャッシュには git の履歴が無い。main の履歴には試用の枝の commit も混じり、版の区切りが件名から機械で出ない。
- GitHub Releases の本文で代える（捨てた案）: 外への書き込みで、プラグインのキャッシュに入らない。社内の git や共有フォルダで配る道では読めない。
- 変更の記録を生成の道具（git-cliff・release-please・changesets）で作る（捨てた案）: 新しい依存になり、日本語の本文から起こす目的に届かない。
- marketplace の版にも tag を付ける（今は採らない）: catalog は plugin の tag で固定できる。後から足すのは既存を壊さない追加だが、一度配った tag を消すと利用者が壊れるので、付けない方を既定にした。
- 変更の記録の各版に、marketplace の版・版上げの commit の id・tag の名前の行を書く（捨てた案）: 版上げの commit は自分の id を自分の中に書けない。作業枝の commit は main に入るときに作り直される。marketplace の版は版上げの commit が持ち、tag の名前は版から導ける。

## 理由

世の中の解が揃っていた。変更の記録は Keep a Changelog、1 つのリポジトリで複数の plugin を配るときの tag の形は Claude Code の公式の形で、形を選び直す岐路が無かった。記録を手順に書くだけでは次の版上げで書き忘れるので、版の見出しの在ることだけは検査で縛る。

## 結果

- 利用者は手元の版の番号から、変更の記録の同じ見出しへ辿れる。tag が付けば、版を名指しして入れられる。
- 版を上げる人には、同じ commit で変更の記録の見出しを足す義務が立つ。
- 過去の版に付ける tag（人が付ける。main の版上げの commit で、各 commit の plugin.json の版が tag の名前と一致することを確かめた）:

  | tag | commit |
  |---|---|
  | graphloops--v0.20.0 | 5dfb0bf |
  | graphloops--v0.20.1 | 1449a38 |
  | graphloops--v0.20.2 | 32dfd94 |
  | graphloops--v0.20.3 | fbd40e3 |
  | graphloops--v0.21.0 | a1202d0 |
  | graphloops--v0.21.1 | 0fd3032 |

- ほかの plugin（convergence-loops・gates・coldwrite・attention）の変更の記録と tag は、この決定の外に置いた。持つときは同じ形（`<plugin の名前>--v<版>`）にする。

## 見直す条件

- Claude Code の公式の tag の形が変わったとき。
- marketplace の版を名指しして入れる利用者が現れたとき（marketplace の tag を足す）。

## 出どころ

- 手順の正本: [docs/releasing.md](../releasing.md)。
- 公式の文書: https://code.claude.com/docs/en/plugins/dependencies（Create a release tag）・https://keepachangelog.com/en/1.1.0/
