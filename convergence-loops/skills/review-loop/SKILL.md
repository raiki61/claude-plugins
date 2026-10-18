---
description: コード変更後の自動レビュー・修正サイクル。起動するのは、人が /review-loop と打ったときか「工程に回して」と言ったときだけ——AI は自分から起動せず、実装完了時・リファクタリング後・バグ修正後に当たったら人に提案する。
allowed-tools: Bash, Agent, Skill, Read, Write, Edit, Grep, Glob
---

# review-loop

コード変更を、レビューと修正を繰り返して阻害要因が出なくなるまで回す。採点は別 context の役に置き、収束はラウンドごとの記録（`.claude/review-rounds/round-<N>.json`）を機械（`${CLAUDE_PLUGIN_ROOT}/scripts/review-record.py`）で突き合わせて決める。

このプラグインの置き場は `${CLAUDE_PLUGIN_ROOT}` である。別ファイルの命令やパスに書いた `CLAUDE_PLUGIN_ROOT`（`$` と波括弧で囲んだ形）は Bash の環境変数には無いので、この置き場に読み替えて使え。

## 役割分担（最重要）

このループを回す session が **writer（実装者）**。**writer は局所レビューを機械的に実行して findings を集めることはできるが、ラベル確定・根本診断・収束判定はしない。** それらは全て別 context の **grader subagent** が行う（writer ≠ grader）。writer は grader が確定した `[block]` を直すだけで、ラベルを自分で上げ下げできない。grader の判定を覆したい時も自分で決めず、別 context の grader に再判定させろ。

**grader を都合よく使うな**: 同一ラウンドで grader を回し直して有利な結果を採るな（やり直しは次ラウンドのみ）。grader subagent の生出力（根本ユニットのキー集合・各 verdict）は最終報告にそのまま転記しろ。

レビュー観点とラベルの正本は `REVIEW.md`（[references/tools.md](references/tools.md) の「道具と正本の場所」で定義した 2 つ。以降 `REVIEW.md` と書いたものはその併用を指す）。grader はレビュー開始前に `REVIEW.md` を読むこと。ただし道具を持たない隔離 grader（文脈遮断）は自分では読めないため、writer が該当セクションの本文をプロンプトに貼って渡せ。

武器の使い分け: **局所レビューは公式 skill に委譲**し再実装するな。ただし**欠陥と品質は別の道具**で、片方はもう片方を代替しない——欠陥（correctness）は `pr-review-toolkit:review-pr`、品質（reuse / 簡素化 / 効率 / altitude）は `/simplify` が担当する（`/simplify` は「バグは探さない」と自ら明記している）。**両方走らせろ**——「簡素化」は `review-pr` の観点にも含まれるが、観点が重なることは片方を省く理由にならない。根本診断・整合性・俯瞰は grader subagent で行う（公式に相当機能がない）。

## 段ごとに読むファイル

この本文は段の順と読むファイルだけを持ち、手順の中身は持たない。**段に入るたびに、その段のファイルを読んでから手を動かせ。** 会話が圧縮されて前に読んだ手順が見えなくなったら、今いる段のファイルを読み直せ。

1. 始める前に 1 度: [references/tools.md](references/tools.md)（スクリプトと記録の置き場、前のレビューの記録の退避、観点の正本、役の起こし方と渡し方、依存の扱い）
2. P0 基準点と元の目的: [references/p0-baseline.md](references/p0-baseline.md)（BASE の決め方、手元の CI、前提の実測、目的テキストの凍結、並行 PR、先行議論）
3. P1 素材集め: [references/p1-materials.md](references/p1-materials.md)（局所レビューと各 grader の起こし方、渡す物と渡さない物、作業ツリーの突合）
4. P2 診断: [references/p2-diagnosis.md](references/p2-diagnosis.md)（judge への入力、木探索、ラベルと disposition、処方、安定キー、履歴と問いの台帳の再審）
5. P3 修正: [references/p3-fix.md](references/p3-fix.md)（根本ユニット単位で直す、閉鎖の実証、問いに挙がったユニットを実装しない）
6. P4 再採点: [references/p4-rescore.md](references/p4-rescore.md)（P1〜P2 のやり直し、`review-record.py` の突合と終了コード、台帳と scalar の記録、次への分岐、R1・R2 の再発火条件）
7. P-R 俯瞰: [references/p-r-overview.md](references/p-r-overview.md)（R1〜R4 の起こし方と verdict の写し方）
8. P4 の判定のたびに: [references/stop.md](references/stop.md)（収束の条件、収束以外で止まる 3 つ——総ラウンドが 5 を超えたら必ず止める暴走ガードを含む——、問いの種類ごとの再審）
9. 最終報告: [references/report.md](references/report.md)（冒頭に置く人が決めること、初見で決められる問いの形、出す前の確かめ、必ず含める項目）

1 ラウンド＝P1→P4 の 1 周。P4 の判定で P3 に戻るか P-R へ進み、P-R で `redesign-needed` が出たら P1 から次のラウンドに入る。

## どの段でも踏むと壊れる所

- 記録の欄と値の正本は `review-record.py`。`not_applicable`（条件に当たらない）と `not_run`（飛ばした）を混ぜると、無言の省略が「なし」に化ける。
- 前のラウンドの記録を消すな。突合が `exit 2`（記録が不正）で止まる。`exit 1`（阻害要因あり）と取り違えるな。
- 前のラウンドの grader の出力や修正の経緯を、次のラウンドの P1・P2 の役に渡すな（追認になる）。
- 人に聞く候補は、立った周に止めて聞かず問いの台帳に載せる。止めて聞くのは機械がそう出したときだけ（例外は stop.md）。
