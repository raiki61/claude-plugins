# 0066. 版ごとに plugin の tag と変更の記録を残す

- 状態: 採用
- 日付: 2026-09-27
- 決めた人: 判定役（review-graph の判定から入る run の 1 周目）。marketplace の版に tag を付けないことは判定役の推し。tag の名前の形は、tag を前提に入れる別の作業が形を名指ししていないことを、人の側が確かめた
- 実装: 作業枝で済み（main の版には未収録）
- 広げた日: 2026-09-27。graphloops だけだった記録・tag の一覧・見出しの検査を、配る全部の plugin に広げた（review-graph の判定から入る run の 1 周目。人の依頼「他のリリース物もある」）

## 文脈

- 版の tag が 1 本も無く、変更の記録も無かった。版は「fix か feat の 1 commit と版上げの 1 commit」で main に入り、版の中身は commit の本文にしか残らなかった。
- engine は版の番号を報告の頭と intake の記録に刻むが、利用者の手元（プラグインのキャッシュ）には git の履歴が無く、版の番号から中身へ辿れない。
- Claude Code の固定の口（marketplace の ref・plugin の source の ref）と依存の版の範囲の解決は、名前の付いた ref を前提にする。tag を前提に入れる別の作業も現れた。
- [0022](0022-release-often.md) で版を 1 日 1 回ほどの速さで出すので、版と中身の対応が無い害が速く積もる。

## 決定

- 変更の記録は Keep a Changelog 1.1.0 の形で、各 plugin の根（`.claude-plugin/marketplace.json` の `plugins[].source` が指す置き場）の `CHANGELOG.md` に置く。プラグインのキャッシュに入るのは source の木だけなので、そこに置く。source が `./` の convergence-loops は、リポジトリのルートの `CHANGELOG.md` になる。
- tag の名前は Claude Code の公式の形 `<plugin の名前>--v<版>`（graphloops なら `graphloops--v<版>`）。付ける commit は main に入った版上げの commit で、その commit の plugin.json の版と tag の名前の版が一致すること。
- marketplace の版（`metadata.version`）には tag を付けない。
- 版上げの commit で変更の記録の見出しを足し、`tests/run.sh` が marketplace.json の一覧に在る全部の plugin について、今の版の見出しの在ることを確かめる。
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
- 過去の版に付ける tag（人が付ける）。main（0fd3032 まで）の first-parent の履歴で、plugin.json の version が変わった commit を台本で引いた。各 commit の plugin.json の name と version が tag の名前と一致することを確かめてある。1 つの commit が複数の plugin の版を上げた所は、同じ commit に plugin ごとの tag を付ける。
- convergence-loops の 0.1.0〜0.7.2 の 9 版は、その commit の plugin.json の name が review-loops（0.8.0 で convergence-loops に改名）なので、`convergence-loops--v` の tag を付けない。公式の解決は marketplace の plugin の名前の tag を版の範囲で引くので、付けると名前の違う plugin の中身が convergence-loops として入りうる。記録（ルートの CHANGELOG.md）には版を残す。gates の前身の coldread（coldread 0.1.0）にも tag を付けない。
- 版の番号は飛ぶことがある（convergence-loops の 0.39.0 は main に無い）。表に無い版に tag を付けない。

  convergence-loops（51 版。新しい順）:

  | tag | commit |
  |---|---|
  | convergence-loops--v0.41.0 | 97c464c |
  | convergence-loops--v0.40.0 | 25d6338 |
  | convergence-loops--v0.38.0 | 9c8ef5d |
  | convergence-loops--v0.37.0 | a58681e |
  | convergence-loops--v0.36.2 | c94aad8 |
  | convergence-loops--v0.36.1 | ba5d79a |
  | convergence-loops--v0.36.0 | d33370d |
  | convergence-loops--v0.35.1 | 7613e2a |
  | convergence-loops--v0.35.0 | 77a7ced |
  | convergence-loops--v0.34.1 | f06d880 |
  | convergence-loops--v0.34.0 | 0061eeb |
  | convergence-loops--v0.33.3 | 64b3255 |
  | convergence-loops--v0.33.2 | d1537c1 |
  | convergence-loops--v0.33.1 | 1edff0d |
  | convergence-loops--v0.33.0 | fd4fd5a |
  | convergence-loops--v0.32.0 | 4c1fc14 |
  | convergence-loops--v0.31.1 | 73fda8a |
  | convergence-loops--v0.31.0 | a27f0e9 |
  | convergence-loops--v0.30.1 | 9d9d69b |
  | convergence-loops--v0.30.0 | 68bac1e |
  | convergence-loops--v0.29.0 | 26f8b77 |
  | convergence-loops--v0.28.0 | a554252 |
  | convergence-loops--v0.27.0 | e6951cb |
  | convergence-loops--v0.26.0 | 5a27245 |
  | convergence-loops--v0.25.1 | f47003e |
  | convergence-loops--v0.25.0 | 9fed278 |
  | convergence-loops--v0.24.0 | 092e59a |
  | convergence-loops--v0.23.0 | 4bb8d62 |
  | convergence-loops--v0.22.0 | b5783c4 |
  | convergence-loops--v0.21.0 | e67a5f0 |
  | convergence-loops--v0.20.1 | 935b205 |
  | convergence-loops--v0.20.0 | 584997a |
  | convergence-loops--v0.19.0 | 202b7e5 |
  | convergence-loops--v0.18.1 | e3193a2 |
  | convergence-loops--v0.18.0 | 62a2e2d |
  | convergence-loops--v0.17.1 | af5302f |
  | convergence-loops--v0.17.0 | 62c04d9 |
  | convergence-loops--v0.16.1 | 993c3cc |
  | convergence-loops--v0.16.0 | e74cc32 |
  | convergence-loops--v0.15.2 | 53f7d18 |
  | convergence-loops--v0.15.1 | 77a55f1 |
  | convergence-loops--v0.15.0 | 395d14b |
  | convergence-loops--v0.14.0 | 695ca02 |
  | convergence-loops--v0.13.0 | f3f0e0f |
  | convergence-loops--v0.12.0 | 15b28fe |
  | convergence-loops--v0.11.0 | ae56efd |
  | convergence-loops--v0.10.0 | 0ecc17b |
  | convergence-loops--v0.9.0 | 4c1af9c |
  | convergence-loops--v0.8.2 | 18e41d5 |
  | convergence-loops--v0.8.1 | 72ae70b |
  | convergence-loops--v0.8.0 | 43d78b7 |

  gates（21 版。新しい順）:

  | tag | commit |
  |---|---|
  | gates--v0.11.3 | b93a039 |
  | gates--v0.11.2 | 742a61d |
  | gates--v0.11.1 | e997521 |
  | gates--v0.11.0 | 9c8ef5d |
  | gates--v0.10.1 | f943f95 |
  | gates--v0.10.0 | a31bf06 |
  | gates--v0.9.0 | 2e43941 |
  | gates--v0.8.0 | e0b0f81 |
  | gates--v0.7.0 | f742d41 |
  | gates--v0.6.0 | 4364c0e |
  | gates--v0.5.1 | b151cd3 |
  | gates--v0.5.0 | c3581b5 |
  | gates--v0.4.0 | 7cf8d2f |
  | gates--v0.3.2 | 64991af |
  | gates--v0.3.1 | 751fa3b |
  | gates--v0.3.0 | ed80383 |
  | gates--v0.2.2 | f41ab4c |
  | gates--v0.2.1 | b7bbb16 |
  | gates--v0.2.0 | 48299c9 |
  | gates--v0.1.1 | cbd7426 |
  | gates--v0.1.0 | 18381f9 |

  coldwrite（4 版。新しい順）:

  | tag | commit |
  |---|---|
  | coldwrite--v0.1.3 | e5fd3a3 |
  | coldwrite--v0.1.2 | 7f0c312 |
  | coldwrite--v0.1.1 | 492a3ef |
  | coldwrite--v0.1.0 | 68ed2eb |

  attention（39 版。新しい順）:

  | tag | commit |
  |---|---|
  | attention--v0.25.1 | e997521 |
  | attention--v0.25.0 | 6b85169 |
  | attention--v0.24.1 | 200f00e |
  | attention--v0.24.0 | 6ea02ca |
  | attention--v0.23.0 | de47b86 |
  | attention--v0.22.3 | b27cb3d |
  | attention--v0.22.2 | e6484de |
  | attention--v0.22.1 | af25f31 |
  | attention--v0.22.0 | e824033 |
  | attention--v0.21.0 | 2971ea2 |
  | attention--v0.20.0 | ef2e574 |
  | attention--v0.19.0 | f95c0ca |
  | attention--v0.18.1 | 01c8234 |
  | attention--v0.18.0 | 9191386 |
  | attention--v0.17.0 | 6d9907f |
  | attention--v0.16.0 | 9283979 |
  | attention--v0.15.0 | a65947a |
  | attention--v0.14.1 | 616dc75 |
  | attention--v0.14.0 | 6afcff9 |
  | attention--v0.13.0 | c15dc79 |
  | attention--v0.12.0 | d1c4b2f |
  | attention--v0.11.0 | 56e4efb |
  | attention--v0.10.1 | 3258a1a |
  | attention--v0.10.0 | c74fc8e |
  | attention--v0.9.0 | d5b2ac4 |
  | attention--v0.8.0 | db9f63a |
  | attention--v0.7.1 | 9910b96 |
  | attention--v0.7.0 | 739be12 |
  | attention--v0.6.0 | 1017287 |
  | attention--v0.5.2 | 6c6c171 |
  | attention--v0.5.1 | 8973233 |
  | attention--v0.5.0 | dc4a2af |
  | attention--v0.4.0 | d96b13c |
  | attention--v0.3.3 | f813751 |
  | attention--v0.3.2 | aa8f65d |
  | attention--v0.3.1 | 612f73f |
  | attention--v0.3.0 | 667ac4b |
  | attention--v0.2.0 | 53c2cac |
  | attention--v0.1.0 | c0ce2c9 |

  graphloops（41 版。新しい順）:

  | tag | commit |
  |---|---|
  | graphloops--v0.21.5 | e908a2d |
  | graphloops--v0.21.4 | c7e8b7f |
  | graphloops--v0.21.3 | 25e2dc7 |
  | graphloops--v0.21.2 | 98ae029 |
  | graphloops--v0.21.1 | 0fd3032 |
  | graphloops--v0.21.0 | a1202d0 |
  | graphloops--v0.20.3 | fbd40e3 |
  | graphloops--v0.20.2 | 32dfd94 |
  | graphloops--v0.20.1 | 1449a38 |
  | graphloops--v0.20.0 | 5dfb0bf |
  | graphloops--v0.19.0 | 6c09193 |
  | graphloops--v0.18.0 | 25d6338 |
  | graphloops--v0.15.0 | 8439513 |
  | graphloops--v0.14.1 | e997521 |
  | graphloops--v0.14.0 | 39b7045 |
  | graphloops--v0.13.1 | d3a8935 |
  | graphloops--v0.13.0 | e2d3bc5 |
  | graphloops--v0.12.0 | 6b2c3a3 |
  | graphloops--v0.11.0 | 1e5f498 |
  | graphloops--v0.10.0 | 6b7364a |
  | graphloops--v0.9.3 | 7a61a94 |
  | graphloops--v0.9.2 | 1a8c100 |
  | graphloops--v0.9.1 | 94eea13 |
  | graphloops--v0.9.0 | 15f0356 |
  | graphloops--v0.8.1 | 574c1a0 |
  | graphloops--v0.8.0 | 9c8ef5d |
  | graphloops--v0.6.0 | a58681e |
  | graphloops--v0.5.1 | ba5d79a |
  | graphloops--v0.5.0 | d33370d |
  | graphloops--v0.4.5 | 7613e2a |
  | graphloops--v0.4.4 | df634b0 |
  | graphloops--v0.4.3 | 9baecb3 |
  | graphloops--v0.4.2 | f253acc |
  | graphloops--v0.4.1 | 77a7ced |
  | graphloops--v0.4.0 | 0061eeb |
  | graphloops--v0.3.3 | 64b3255 |
  | graphloops--v0.3.2 | d1537c1 |
  | graphloops--v0.3.1 | 1edff0d |
  | graphloops--v0.3.0 | ebf6bc3 |
  | graphloops--v0.2.0 | fd4fd5a |
  | graphloops--v0.1.0 | 4c1fc14 |

- 今の版の tag: graphloops--v0.23.0（この行を書き換えた版上げの commit に付ける。1 つ前の版は graphloops--v0.22.0（6f16f9d）で、graphloops の表の先頭の graphloops--v0.21.5 はその前の版）・convergence-loops--v0.41.0（上の表の先頭の行）と、gates--v0.11.4・coldwrite--v0.1.4・attention--v0.25.2。後の 3 本は、この行を足した版上げの commit（main の 97c464c の次の commit）に付ける。gates・coldwrite・attention の表の先頭の行（gates--v0.11.3・coldwrite--v0.1.3・attention--v0.25.1）は 1 つ前の版で、今の版ではない。

## 見直す条件

- Claude Code の公式の tag の形が変わったとき。
- marketplace の版を名指しして入れる利用者が現れたとき（marketplace の tag を足す）。

## 出どころ

- 手順の正本: [docs/releasing.md](../releasing.md)。
- 公式の文書: https://code.claude.com/docs/en/plugins/dependencies（Create a release tag）・https://keepachangelog.com/en/1.1.0/
