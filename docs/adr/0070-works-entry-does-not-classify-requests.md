# 0070. /works の入口は依頼を分類しない（何をどう直すかはラインが単位ごとに決める）

- 状態: 採用
- 日付: 2026-09-28
- 決めた人: 人（darkfactory の自分食い run 46 の依頼と、修正前の関所の答え (4)(5)）
- 実装: 作業枝で済み（[works の手順書](../../works/skills/works/SKILL.md)）

## 文脈

- /works の手順書（`works/skills/works/SKILL.md`）の description と冒頭は「誤字・コメント・文言の直しは回さず手で直す」と依頼を入口で分類し、description にラインの内部の段の列も並べていた。これは [0010](0010-judgment-entry-for-fix-requests.md) の review-graph での使い分けを写した物。
- description は Claude がスキルを選ぶ時に読む文なので、この分類が「回さない」判断の根拠として読まれる経路が在る。
- works のラインは判定の単位ごとに、テストを先に書く輪（tdd）か直に直す（direct）かを振り分け、直す物が無ければ `no_fix_needed` で終わる。入口で分ける理由が無い。

## 決定

- /works の入口は依頼を分類しない。何を直すか・どう直すかはラインの判定が単位ごとに決める。
- description は「何をするか」と「いつ使うか」だけにし、ラインの内部の段の列は書かない（正本は darkfactory.yaml と設計の文書）。
- [0010](0010-judgment-entry-for-fix-requests.md) の使い分け（直接直すのは誤字・コメント・文言だけ）は graphloops の review-graph の手順書に残り、works の入口には掛けない。0010 は置き換えない。

## 比べた案

- 入口の分類を残す（0010 の写しのまま）: ラインが単位ごとに振り分ける依頼まで工場の外へ逸らすので採らない。
- 分類や段の語が SKILL.md に無いことを見る試験を足す: 語の言い換えが次の入口になり、試験が文言を縛るので採らない。

## 理由

- Anthropic の Skill authoring best practices（[platform.claude.com の best practices](https://platform.claude.com/docs/en/agents-and-tools/agent-skills/best-practices)の「Concise is key」「Writing effective descriptions」）は、description に何をするかといつ使うかを書き、Claude が持たなくてよい文脈を書かないとする。
- 入口とラインで同じ判断を二重に持つと、ずれる元になる。

## 結果

- 誤字・コメント・文言だけの依頼も darkfactory に回りうる。判定が振り分けるまでの AI の費用が掛かる（人が通した代償）。
- スキルを読むだけではラインの工程の順が見えない。工程を知りたい時は正本を読む。
- 消える口・欄は無いので、後方互換の論点は当たらない。

## 見直す条件

- 入口で分けないために、安い直しの依頼が目に見えて費用を食うと測れたとき。

## 出どころ

- darkfactory の自分食い run 46 の判定の単位「works/skills/works/SKILL.md description・冒頭: 手順書が依頼を分類し内部の段を並べ、ラインが単位ごとに振り分ける依頼まで工場の外へ逸らす」と、修正前の関所の答え (4)(5)（2026-09-28）。
