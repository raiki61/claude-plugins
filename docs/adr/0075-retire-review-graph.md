# 0075. /review-graph を退役させる（使う人は /works-factory へ移る。graphloops を受け持つ部署「見直し」が 2026-10-19 に /review-graph のスキルを消した）

- 状態: 採用
- 日付: 2026-10-18
- 決めた人: 人（このリポジトリの持ち主。2026-10-18 の「なら一旦reviewgraphだけまずは退役させるか」「それをworksfactoryにがっつり置き換えたらいいと思う」〔reviewgraph は `/review-graph`、worksfactory は `/works-factory` のこと〕と、消すのは works-factory の issue #712 が直ってから・予告は今始めてよい、の決めと、予告で案内する先を `/works-factory` にする案への持ち主の答え「ok」）。[0002](0002-backward-compatibility.md)（今ある能力と使い方を減らさない）の例外として持ち主が決めた。予告の形・消す日・消す手順は、graphloops を受け持つ部署「見直し」の担当が持ち主の決めと [0073](0073-land-bumps-and-no-tags.md) から導いた
- 実装: 消した（2026-10-19。最後の形は 58c6d08b: https://github.com/raiki61/claude-plugins/tree/58c6d08b/graphloops/skills/review-graph ）。予告も同じ 2026-10-19 に入れた。消す日を 2026-11-18 から早めた訳は「消す日を早めた（2026-10-19）」のセクション

## 文脈

- 語: graphloops は、このリポジトリのプラグインの 1 つで、`/review-graph` と `/research-graph` と、その 2 つの段を回す engine を持つ。works は、このリポジトリの works プラグイン（`/works`。工場 darkfactory を回す今の入口）。works-factory は、別のリポジトリ raiki61/works-factory の新しい工場で、このリポジトリからは works-factory プラグイン（`/works-factory`）の薄い入口で配る。2 つは別の物で、退役の代わりは works-factory。
- graphloops のスキル `/review-graph`（コードの変更のレビューと人の修正依頼を、engine が段ごとに回す入口。フォルダは `graphloops/skills/review-graph/`）の役目は、置き換え先の works-factory（修正の工場。claude-plugins の marketplace で `/works-factory` の薄い入口として配っている。工場の中身は raiki61/works-factory）が引き継ぎつつある。残すと、2 つの仕組みを保守し続けることになる。
- リポジトリは公開で、世の中に使っている人がいるかもしれない。入れた人の数を作者が知る仕組みは Claude Code に無い。いきなり消すと、その人を困らせる。
- [0002](0002-backward-compatibility.md) は、今ある能力と使い方を減らさないと決めている。入口を消すのは使い方を減らすことなので、持ち主が例外として決めた。
- 2026-10-18 に、works-factory の本物の run 4 本が、最後の報告を書くノードで模型の提供元の安全の判定に止められていた（works-factory の issue #712）。直る前に消すと、移った人が最後の報告で止まる。#712 は 2026-10-18 に PR #718 の後の本物の run で確かめて閉じた。
- 2026-10-19 の時点で、works-factory の受け入れの一覧（works-factory の `docs/design.md` の「受け入れの一覧（review-graph と同じ能力）」）は、チェックの付いた行が 39 行のうち 2 行だけである。ただし、証の正本の節の表（works-factory の `docs/nodes.json`）では、review-graph の 60 のノードのうち 53 に試験の名の証が有る。残りの 7 は absent（works-factory に無い）で、4 つ（`p2.history`・`p3.delta_gates`・`p4.final_gates`・`p2.rejudge_third`）は今の works にも無く、持ち主が決めて落とした物、3 つ（`p4.assemble`・`p4.record`・`converge`）は、review-graph がレビューと直しを結果が変わらなくなるまで何回も回して回ごとに記録するのに対し、works-factory の run は 1 回で終わり、回ごとの記録を持たないことによる。ほかに、review-graph より狭めた所が 7 つ有る（`docs/nodes.json` の `downgrades`）。この 2 つの数は、移る人の目安として書いた。消す条件には入れていない（消す条件は日付と #712 だけ）。

## 決定

- `/review-graph` を退役させる。退役させるのは `/review-graph` だけで、`/review-loop`（convergence-loops）は退役させず、予告も出さない。`/research-graph` と engine は残す。
- 予告は 2026-10-19 に入れた（この ADR を足した commit と同じ）。`/review-graph` のスキルの description と本文の頭に「退役予定・消す日・代わりは `/works-factory`」を書き、呼ばれたら手を動かす前に利用者に見せさせる。graphloops の README と CHANGELOG（Deprecated）にも書く。
- 消す日は、予告を入れた日（2026-10-19）から 30 日の後の 2026-11-18 以降で、かつ works-factory の #712 が閉じたままであること。#712 は 2026-10-18 に閉じたので、今の見込みは 2026-11-18。（2026-10-19 に、持ち主の答えで日付の条件を外し、#712 の条件だけで消した。下の「消す日を早めた（2026-10-19）」）
- 消すのはスキル `/review-graph` のフォルダ `graphloops/skills/review-graph/` だけにする。review-loop のグラフ・rules・prompts・blocks（`graphs/review-loop*.json` など）は残す。engine の試験の多く（`graphloops/tests/` の 136 のファイル）が review-loop のグラフを材料に使い、`/research-graph` もそれと同じ engine の上で動くから。グラフまで消すかは、この ADR の外で別に決める。
- 置き場のフォルダは作らず、git の履歴をアーカイブにする。tag は作らない（[0073](0073-land-bumps-and-no-tags.md)。持ち主 2026-09-29「タグはつくりません」）。代わりに、消す commit の 1 つ前の main の commit の id を、graphloops の CHANGELOG の Removed と、この ADR の実装の欄に書く。その commit の `https://github.com/raiki61/claude-plugins/tree/<commit>/graphloops/skills/review-graph` で、最後の形をいつでも開ける。
- 人の方針の置き場の説明（`graphloops/skills/review-graph/references/policy.md` の「## 人の方針」）は、`/research-graph` も使うので、消すときに `graphloops/skills/research-graph/references/policy.md` へ移し、指しているリンクを全部張り替える。

## 消す日を早めた（2026-10-19）

- 持ち主の言葉（2026-10-19。社長室〔持ち主への中継の部署。持ち主のノートのリポジトリ my_notes に在る〕がこの部署へ送った頼みの記録。受付〔部署どうしの頼みを運ぶ works-dispatch が頼みに付ける ID〕20261018-230520-783e24 と、その頼みに後から書き足した足し 20261018-230540-7fb192・20261018-230551-17474d）: 「もう退役して置き換えていいよ。」「またずにいますぐ退役してよい。」「以降はarchiveでメンテ不要」。
- その前に持ち主へ出した問い: works-factory が review-graph より狭い所（2 種類で計 14 か所。1 つは、review-graph の 60 のノードのうち works-factory に試験で確かめた証が無いノード 7 つで、うち 4 つは持ち主が前に落とすと決めた物。もう 1 つは、それとは別の、review-graph より働きを狭めた所 7 つ。中身は文脈の「2026-10-19 の時点で」で始まる項目）を受け入れて消すか。持ち主はこの 14 か所を受け入れた。
- 前の決め（社長室の足し 20261018-043529-736097）の「予告から 30 日」は、持ち主の言葉ではなく、社長室が頼みの文（社長室がこの部署へ送った頼みの本文）に足した制約だった。持ち主は外の利用者が移る時間が短くなるのを承知で「またずにいますぐ」と言ったので、この答えで置き換えた。
- 手順は下の「消すときの手順」をそのまま使い、手順 1（日付を見る）だけを持ち主の答えで置き換えた。手順 2（#712）は省かず、2026-10-19 に `CLOSED` を確かめてから消した。
- 「以降はarchiveでメンテ不要」は、消した後の `/review-graph` を保守しないことと読んだ。アーカイブの形は「決定」のとおり、置き場のフォルダを作らず git の履歴をアーカイブにし、tag は作らない。残す部品（review-loop のグラフ・rules・prompts・blocks と engine の試験）は、持ち主の言葉が指していないので「決定」の切り分けのまま残した。
- 下の「見直す条件」（消す日までに works-factory の不具合が見つかったら延ばす）は、消した時点で役目を終えた。

## 消すときの手順

消すのは graphloops を受け持つ部署「見直し」（[0074](0074-graphloops-edits-by-desk-and-land.md)）で、--land（部署のブランチを main に入れる works-dispatch のコマンド）で main に入れる。

1. 今日が 2026-11-18 以降かを見る。前なら消さない。
2. `gh issue view 712 -R raiki61/works-factory --json state -q .state` が `CLOSED` かを見る。開き直されていたら、閉じるまで消さない。
3. `git fetch origin` の後の `git rev-parse origin/main` を控える（最後の形の commit）。
4. `graphloops/skills/review-graph/references/policy.md` を `graphloops/skills/research-graph/references/policy.md` へ移し、review-graph にしか当たらない文を research-graph の言い方に直す。
5. 人の方針へのリンクを、手順 4 の置き場へ張り替える。`git grep -n "review-graph/references/policy.md" -- . ':!works'` で、相対のリンク（research-graph の `references/rules.md` の `../../review-graph/references/policy.md#人の方針`）も、`docs/adr/` の ADR（0002〜0014・0018・0020・0023・0045・0047 など）と `docs/adr/README.md` の「正本はどれか」のリンクも出る。出た行が、過去の版の CHANGELOG の項目とこの ADR だけになるまで直す。
6. `graphloops/skills/review-graph/` を消す。graphloops の試験 `graphloops/tests/simulate_review.py` は、手順書を名前の組 `("review-graph", "research-graph")` で開くので、組から `review-graph` を外す（パスの字が続いて現れないので、手順 7 の grep には出ない）。
7. 残ったリンクを直す。`git grep -n "skills/review-graph" -- . ':!works'` で出る行のうち、リンクと案内（graphloops の README・ルートの CLAUDE.md・CONTRIBUTING.md・`docs/` の文書）を、手順 3 の commit の GitHub の URL へ向ける（フォルダは `https://github.com/raiki61/claude-plugins/tree/<commit>/graphloops/skills/review-graph`、ファイルと見出しは `https://github.com/raiki61/claude-plugins/blob/<commit>/<パス>#<見出し>`）。過去の版の CHANGELOG の項目とこの ADR は、その時の記録なので直さない。ルートの `tests/run.sh` の ENTRY_SURFACE_OK の検査と、`tests/mutations.json` の同じ検査の変異は、スキルごと無くなるので消す（ルートの `tests/` は点検〔CI とルートの `tests/` を受け持つ部署。会社の形 `.claude/company.toml`〕の受け持ちなので、点検に頼む）。`works/` の中の言及は works の設計の記録と写しで、写しは `works/.shared/core/COPIED_FROM` の commit から git で読むので、消しても壊れない。直さない。
8. graphloops の CHANGELOG の Unreleased に Removed を書き、手順 3 の commit の id と、そこを開く URL を添える。この ADR の実装の欄を「消した（最後の形は <commit>）」に直す。
9. README の退役の予告を、消したことと最後の形の開き方に書き換える。

## 比べた案

- 消す直前の commit に tag（例 `archive/review-graph`）を打つ（捨てた案）: 持ち主の決め「タグはつくりません」（2026-09-29）と [0073](0073-land-bumps-and-no-tags.md) に反する。commit の id を CHANGELOG と ADR に書けば、tag が無くても最後の形を開ける。
- 置き場のフォルダ（`archive/` など）に写して残す（捨てた案）: 写しは古いまま残り、保守する物が減らない。git の履歴で足りる。
- review-loop のグラフ・rules・prompts も一緒に消す（今は採らない）: engine の試験の材料で、`/research-graph` を残すと決めた engine の確かめが崩れる。
- 予告なしで消す（捨てた案）: 世の中の利用者が移る前に入口が消える。

## 理由

- 持ち主の決め（退役させる・移り先は works-factory・消すのは #712 が直ってから・予告は今始めてよい）を、0002 の例外として 1 か所に記録するため。
- 予告の期間を 30 日にするのは、社長室（持ち主への中継の部署。持ち主のノートのリポジトリ my_notes に在る）が持ち主に出した案のとおり。持ち主は案を読んで退役を決めた。（2026-10-19 に、持ち主の答えで 30 日を待たずに消した。「消す日を早めた（2026-10-19）」）

## 結果

- 楽になる: 消した後は、`/review-graph` の入口の手順書を保守しなくてよい。
- 難しくなる: 消した後に `/review-graph` を使いたい人は、works-factory に移るか、手順 3 の commit の版を自分で入れる。works-factory には review-graph より狭めた所が有る（文脈の「2026-10-19 の時点で」で始まる項目）。
- 0002 の決まりは、ほかの直しにはそのまま効く。

## 見直す条件

- 消す日までに、works-factory で review-graph の使い方が通らない事（#712 のように run が止まる不具合）が見つかったら、消す日を延ばす。（2026-10-19 に消したので役目を終えた。「消す日を早めた（2026-10-19）」）

## 出どころ

- 持ち主の言葉と社長室の案: my_notes の社長室の受付 20261018-042638-c91210、足し 20261018-042808-72000a・20261018-043003-e5c6a6・20261018-043529-736097。
- works-factory の #712: https://github.com/raiki61/works-factory/issues/712
- 受け入れの一覧と節の表: raiki61/works-factory の main の `docs/design.md` と `docs/nodes.json`（2026-10-19 に読んだ）。
