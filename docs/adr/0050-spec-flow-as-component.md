# 0050. 仕様の流れは部品として 1 度書き、元の graph と TDD の版の 2 つの入口で重ねる

- 状態: 採用
- 日付: 2026-09-26
- 決めた人: 回す側の推し（12:30、仕様の流れの run の岐路。人の「自明なものは推しで」の委任による。覆せる）
- 実装: 未（部品で重ねる run は止めたまま）

## 文脈

- [0049](0049-spec-flow-on-tdd.md) の字面（仕様は TDD の上だけ）どおりにすると、TDD を使わない仕様の run が消える。

## 決定

- 仕様の節を部品として 1 度書き、「元の graph＋仕様」「TDD の版＋仕様」の 2 つの入口で重ねる（Kustomize の component に倣う）。
- 同じ run の関所: graph の差し替えを 2 段重ねる engine の直しで「壊れた親の graph で run が落ちる」と予測された件は、狭めない塞ぎ方（sha 用の本文は壊れた段でも落ちずに返す＋台本）を条件に通した。

## 比べた案

- (b) の字面どおり、仕様は TDD の版の上だけ（[0049](0049-spec-flow-on-tdd.md)）。

## 理由

上位互換（[0002](0002-backward-compatibility.md)）: TDD を使わない仕様の run を残す。

## 結果

- graph の JSON で部品を重ねる形の次の run は止めたまま（Archon の YAML に移るなら捨てる側。[0032](0032-archon-migration-decided-by-trial.md)）。
- 手順 3 のブロックでは、仕様は差し込み口 spec のブロックとして表す（BLOCKS の R2）。

## 見直す条件

- Archon の YAML に移るかの決定（[0032](0032-archon-migration-decided-by-trial.md)）。

## 出どころ

- 記録した時点の出どころ（リポジトリの外の作業メモ。消えうる）: `MORNING.md` の 12:30、`HANDOFF.md` の「今日の人の方針」、`blocks/BLOCKS.md` の R2 の注。
