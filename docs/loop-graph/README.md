# 収束ループをグラフで表す（読み方）

## この場所は何か

`convergence-loops` は、このリポジトリが配る Claude Code のプラグイン（AI 開発支援ツール Claude Code に足す拡張）で、4 本のコマンド——`/review-loop`（コード変更のレビュー）・`/research-loop`（見立ての一次情報での校正）・`/doctor-loop`（リポジトリの現状診断）・`/firstread-loop`（文書が初見の人に通じるかの検証）——を持つ。それぞれが「結果が動かなくなるまで回す」ループで、回す手順は手順書（`commands/<コマンド名>.md`）に散文で、記録の検証は Python の検証器（`scripts/<コマンド名>-record.py`）に書いてある。この 2 つが**正本**（本当の定義）で、この場所にあるファイルはその**写し**である。

ループごとに 2 ファイル 1 組:

| ループ | 機械が読む側（`graphloops/graphs/`） | 人が読む側（ここ） | 実行 |
|---|---|---|---|
| review | `review-loop.json` | `review-loop.md` | `/review-graph` |
| research | `research-loop.json` | `research-loop.md` | `/research-graph` |
| doctor | （まだ無い） | `doctor-loop.md` | 写しだけ |
| firstread | （まだ無い） | `firstread-loop.md` | 写しだけ |

JSON は各ループを「節（工程）＋依存＋外側の周回条件」のグラフとして持ち、グラフ実行版プラグイン `graphloops`（`graphloops/README.md`）の `scripts/graphcheck.py` が機械で確かめる。research と review の JSON は実行用の欄（節ごとのプロンプト・返答の型・書き込み規則）も持ち、同じプラグインの engine で回せる。**doctor と firstread の JSON はこの差分から取り下げた**——engine の実行経路に乗らない写し 1,123 行が、凍結した目的（review と research の 2 本）の外に積まれていた。別 issue に落として、実行版を作る周に一緒に入れる（『既存かつこの変更と無関係』でないので split でなく取り下げが正しい形。実測 2026-09-13: BASE に無い本差分の増分で、本差分の `graphloops/tests/run.sh` が検査面に入れていた）。md は図と、図に落ちない説明（変わったこと・記録と検証器・既知の未決）を持つ。写しでも腐りにくい部分（節の名前・依存・役・記録の欄名）だけを持ち、腐りやすい部分（役の道具・観点の本文・行番号）は持たない。道具は `agents/<役>.md`、観点は `REVIEW.md`、出典は手順書の見出し（各節の `source`）で指す。

4 本を横断して拾い上げた規律の一覧と、LLM（大規模言語モデル）を使うアプリとしての性質は、`docs/loop-contract.md` に置く（graphloops と同じ変更で書いた**作業記録**であって、規律の権威ではない——各規律の根拠は、その節が引く手順書・検証器・実測の側にある）。

## 凡例

- **回す側** — ループを実行するメインのセッション（Claude Code の会話そのもの）。手順書ごとに呼び名が違う: review は **writer**（実装者）、research は **surveyor**（調査者）、doctor は **prospector**（走査者）、firstread は **author**（文書の作者。手順書は「あなた」と呼ぶ）
- **役割 agent** — 回す側とは別の context（子の会話）で動く subagent。`agents/*.md` の 6 本——`inspector`（読むだけ）・`investigator`（読む＋shell＋web）・`judge`（覆せない判定を下す）・`blind-judge`（道具なし・渡されたものだけから導出）・`cold-reader`（道具なし・初見の読み手）・`reader`（firstread の読み役）。持てる道具は各ファイルの `tools:` が正本
- **記録** — ループの実行結果を書く JSON。検証器はこれを読んで「収束を妨げるもの」を列挙し、終了コード 0（阻害なし）／1（阻害あり）／2（記録が不正）で返す。機械は不合格だけを宣言し、合格は宣言しない
- **版** — プラグインの `.claude-plugin/plugin.json` にある `version` が正本。この文書には写さない（写した時点で固定され、次の pull で嘘になる）。実際にコマンドとして動く実体はインストール済みキャッシュで、作業ツリー（いま開いているリポジトリの中身）や `origin/main`（GitHub 上の最新）と版が違うことがある——見比べるなら、それぞれの `plugin.json` の `version` を見る

JSON の欄:

- **節** `nodes.<id>` — 工程 1 つ。`run_by` は回す側か、役割 agent の名前か、`skill`（Claude Code の別のコマンド）
- **`deps`** — 「これが終わってから」。`deps` に無い節どうしは同時に走らせてよい。機械検査が同時に走らせてよい組を「波」として出す
- **`fresh_context`** — その節はラウンドごとに新しい context で起動する（前ラウンドを知らない）。`same_context_as` は逆に、指定した節と同じ context で続ける
- **`inputs` / `forbidden_inputs`** — 渡すもの・渡してはいけないもの。節固有の遮断はここに書く。道具の遮断は役の定義側
- **`unblockable_context`** — 渡していないのに読み役の context に入るもの（firstread だけが実測して書いている）
- **`outputs`** — 記録の欄名。検証器が要求する欄と機械で突き合わせる
- **`optional` / `when` / `active_in`** — 条件付きの節。`active_in` は厚みの段（軽量・標準・重厚——research / doctor が持つ、検査の厚さの 3 段階）
- **`retry`** — その節から前の節へ差し戻す条件（明示返答の欠落で採点役を再起動する等）
- **`asks_human`** — 人の入力を待つ節。無人実行では読み替えが要る
- **`verdict_is_copy`** — 判定を出しているように見えるが、写すだけの節（記録を書く節・機械の出力を読む節）
- **`runner_judgment_by_design`** — 手順書が回す側の仕事と定めた分類（firstread の詰まりの型分け）。採点ではない
- **`source`** — 手順書の見出し（行番号は腐るので書かない）
- **`round`** — 外側の周回。`unit`・`max_rounds`・`converge`（収束の述語と誰が数えるか）・`exit_states` か `stops`・`per_round_rules`
- **`record`** — 記録の置き場・検証器の呼び方・語彙の正本・終了コードの契約

## 基準にした版

写しは作業ツリーの手順書（`commands/<loop>.md`）と検証器（`scripts/<loop>-record.py`）から取った。4 本とも同じ作業ツリーが基準で、版番号はここに写さない——正本は `.claude-plugin/plugin.json` の `version` で、写せば pull のたびに腐る。写しが手元の検証器と合っているかは、版番号でなく `graphcheck.py`（下の「機械で確かめられること」）が検証器の必須欄と節の `outputs` を突き合わせて見る。

## 規律 → グラフの属性

`docs/loop-contract.md` は規律に A〜Q（4 本共通）と R〜AB（LLM アプリ固有の性質）の記号を振っている。それがグラフのどこに落ちるか:

- **A 役の遮断** → `run_by`（道具は `agents/<役>.md`）。**T 塞げない注入** → `unblockable_context`
- **B 回す側は採点しない** → 判定を出す節の `run_by` が回す側でない（機械検査 2）。例外は `verdict_is_copy` と `runner_judgment_by_design`
- **C 回し直さない** → `per_round_rules`。**`retry`** は回し直しではなく差し戻し
- **D 前ラウンドを渡さない** → `fresh_context` と `forbidden_inputs`。review の「履歴と台帳は judge にだけ確定後に」は `p2.history` の `same_context_as` と `inputs` の順序
- **E 記録の欄** → `outputs`（機械検査 3 で検証器の必須欄と突合）
- **H 連続 2 ラウンド** → `round.converge.counted_by`（review / firstread は機械、research / doctor は申告）
- **I 暴走ガード** → `round.max_rounds`（グラフ実行版は engine が機械で守る。散文の 4 本は散文だけ。firstread は null）
- **J 人に諮る条件** → review は `round.stops`（3 つ）と `ledger_kinds_not_stops`、他は `round.exit_states`
- **K 無人実行** → `round.unattended` と `asks_human`
- **L 並行の単位** → `deps`。波は機械検査 1 が出す。firstread の「1 周の中だけ」と doctor の「生やした親を同じラウンドの P2b に」は周回側の規律
- **M 作業ツリーの保護** → review の `p1.worktree_before / after`、doctor の `mod.before / after`、firstread の `s1.git_before / s4.git_after`、research は `per_round_rules`
- **N 厚み** → `thickness` と `active_in`
- **R 盤面はディスク** → `record` と firstread の `pre_answers`
- **S 採点のゆらぎ** → `round.converge` の「連続 2」、抜き取り検査の節、3 票
- **V subagent の無言の失敗** → research の `harness_note`・review P2 と doctor P1 の `retry`
- **Z 別の LLM 門番** → review の `p0.parallel_pr`・firstread の `s4.apply` の `note`

グラフに落ちないもの（散文に残る）: なぜその遮断が要るか・観点の本文・処方の最小性・報告の書き方・実測の記録。

## 機械で確かめられること

```bash
python3 graphloops/scripts/graphcheck.py graphloops/graphs/research-loop.json scripts/research-record.py
python3 graphloops/scripts/graphcheck.py graphloops/graphs/review-loop.json scripts/review-record.py
```

`graphcheck.py` は Python の標準ライブラリだけで、①`deps` の実在と循環（`graphlib.TopologicalSorter`。波も出す）②判定を出す節の `run_by` に回す側が無いこと ③検証器の `MATERIALS` / `REQUIRED` / 必須欄が `outputs` に現れること ④`fresh_context` で `forbidden_inputs` を持たない節の一覧 ⑤`active_in` が段名の中——を見る。件数は走らせた出力を見る（ここに写すと腐る）。2026-09-12 に 4 本とも通した。

## 決めたこと・決めてもらうこと

以下のうち「決めた」と付いた行は決着済みで、蒸し返すなら新証拠が要る（2026-09-13 の台帳の再審で、保留していた 9 件のうち 8 件がこの形で決着した——人にしか決められないものは 0 件だった）。残りが人の判断を待っている分。

- **正本の宣言（決めた・2026-09-12）**: 散文版（`/review-loop` 等 4 本）の正本は `commands/<loop>.md` と `scripts/<loop>-record.py`。グラフ実行版（`/review-graph`・`/research-graph`）の正本は `graphloops/graphs/<loop>.json` で、engine と `graphcheck` が読む。両方を生かす間はズレうる——ズレは同じ対象で両方を回し、共通の検証器に通した記録の差で見る（受け入れ試験）。他の文書はこの宣言を参照して写さない。検証器が守らない規律（暴走ガードの上限・前ラウンドを渡さない・回す側は採点しない・回し直さない）は、グラフ実行版では engine が守る
