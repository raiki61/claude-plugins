<!-- coldwrite:skip 内部の設計書。語は「目的と語」の節と works/README.md で定義 -->
# 修正の段を単位ごとに新しい会話で回す（依頼 243 の 2）

状態: 設計と最初の一切れ（前の単位の引き継ぎの節）。会話の切り方はまだ入れていない。

## 目的と語

読む前提: works（このリポジトリの works/ にある、修正依頼を直して出荷する仕組み）の全体は works/README.md と works/docs/specs/2026-09-27-darkfactory-single-run-design.md に在る。依頼の番号（依頼 243 など）は works を works 自身で直す自分食いの依頼の通し番号、run の名（run 195g など）はその試験運用の 1 回の実行の名。

依頼 243（darkfactory の遅さの根本対策）の項目 2: 修正の段で、直す単位（判定が見つけた根本の 1 件。単位の key で呼ぶ）ごとに新しい会話で役を起こし、前の単位が変えた物は会話の履歴でなく機械が書いた引き継ぎ（単位の key・触ったファイル・緑にしたテスト）で渡す。superpowers の subagent-driven-development（SDD。仕事 1 件ごとに新しい下請けを起こす型）と同じ考え。

この文書の語:

- superpowers: Claude Code のプラグインの 1 つ。開発の型（TDD・SDD など）をスキルとして持つ
- 節: Archon のワークフローの 1 つの手（AI を起こす節と、script を走らせる節がある）
- 判定: 修正の前の段で判定役が欠陥の根本を見つけ、単位に分けた結果（盤面の judgment.json）
- 食い違いの申し出: 役が「テスト・依頼・コードのどれかを曲げないと緑にできない」と、行を名指して返す物
- 柵: 包みが役に掛ける道具・書き込みの制限
- 緑・整え: テストが通った状態と、通った後の refactor
- darkfactory: works の生産ライン。Archon（YAML の DAG で AI の節と script の節を回すワークフローの実行器）の上で動く
- 修正のブロック: `works/blk-fix/blk-fix.yaml`。その中の役は 2 つ: TDD の輪の役（節 tdd。単位ごとにテスト・赤・直し・緑・整えの段を回す）と修正役（節 fix。輪で直さなかった単位を直す）。裁定役（節 rule）は食い違いの申し出を裁き、2 回目の修正役（節 fix-ruled）がその裁定で直す
- 輪: Archon の `loop_group`。中の節を `until_bash` が真になるまで繰り返す。1 回の繰り返しを「周」と呼ぶ。`fresh_context` は周ごとに新しい会話で起こすかの真偽値
- 包み: `works/.shared/core/claude-adapter` と `adapter.py`。Archon が起こす claude の前に挟まり、会話の id を記録し、柵を足す。会話の継ぎ方は起動の記録の `session.mode` に残る: `new`（新しい会話）・`sdk-fork`（Archon が `--resume <前の会話> --fork-session` で前の会話の履歴を写した新しい会話を起こした）・`continued`（印 `continue=<節>` で包みがその節の会話を `--resume` で継いだ）
- 指示書の全文版・差分版: 支度の script の節が書く役への指示書。差分版は前の周の会話が全文を読み切っている時だけ包みが選ぶ。記録の理由 `full-not-read` は「前の会話が全文を読み切った記録が無いので全文版」、`rules-changed` は「決まりが変わったので全文版」
- 盤面: run の状態のファイルの置き場。`p3.fix` は修正役の返答を受ける盤面の欄
- 修正の形: 修正の段の作り方の 4 つ（current・af・g3・g1。works/.shared/core/fixshape.py の SHAPES）。入力が空の run は g3（TDD の輪の役が借りたスキルを読む形）、g1 は修正役 1 つが SDD の型で項目ごとの下請けを Agent の道具で起こす形
- R44・R50: works の裁定の番号。R44 は「拒否の理由の文を Archon の `$LOOP_PREV` で貼らず、ファイルに書いて次の指示書で名指す」、R50 は「輪を max_iterations の上限で落とさず、done の旗で抜ける」
- 持ち主: このリポジトリの持ち主（works の方針を決める人）
- run 195g: 2026-10-05 の自分食い（works 自身を darkfactory で直す試験運用）の run。5 つの単位を直した

## 今の会話の流れ（run 195g の起動の記録から）

包みの起動の記録（環境変数 `WORKS_DEV_HOME` が指す開発の置き場の `adapter/launches/<cwd の hash>.jsonl`。run 195g は f8f61973be7354fd.jsonl）の節 tdd・fix・fix-ruled の行:

- tdd: 13:12 に new、そのあと周 2〜24 が全部 `sdk-fork`。輪が `fresh_context: false` なので、Archon が毎周前の周の会話の履歴を写して起こす。13:24 の new は run の起こし直し。5 つの単位と振り分け・テスト・直し・整えの全段が 1 本の鎖に積もる。指示書は 24 回とも全文版で、差分版は 1 度も選ばれていない。
- fix: 14:48 に new の起動が 1 回だけ（周 1）。次の起動（rule）は 16:14。修正役は全部の単位を 1 回の起動・1 つの会話で直し、86 分かかった。
- fix-ruled: 印 `continue=fix` で、包みが修正役の会話（a349bf3b）を `--resume` で継ぐ（3 回とも `continued`）。

仕組みの出どころ:

- `works/blk-fix/blk-fix.yaml`: tdd-loop・fix-loop・rule-loop・fix-ruled-loop が全部 `fresh_context: false`。fix-loop の周は出し直し（上限 3）であって単位ではない。節 fix は義務の単位を全部 1 つの指示書で受け、受け付け（fix-accept → 盤面の p3.fix）も全単位を 1 度に受ける。
- `works/.shared/core/adapter.py` の `plan()`（頭の注記の 1 と 9）: 会話の継ぎは起動の引数だけで決める（Archon の SDK が付ける `--resume`・`--fork-session`・`--session-id` と印の `continue=`）。指示書の全文版・差分版は子を起こした後に標準入力の最初の行で選ぶので、そこで会話を切ることはできない。
- `works/blk-fix/lib/tddloop.py` の `prep`: 今の単位は状態の `queue[cur]`。単位が替わる所は `_next_unit`（単位の頭の木を新しくする）。拒否の理由は R44 どおり次の指示書に書くので、指示書は周ごとに自分だけで読める形に近い。

## Archon の輪の選び方

Archon の `loop_group` の `fresh_context` は輪の全部の周に掛かる真偽値 1 つだけ（`docs/loop-graph/README.md`。graphloops の engine の語も同じ）。「単位が替わった周だけ新しい会話」という選び方は無い。したがって道は 2 つ:

- 道 A: tdd-loop を `fresh_context: true` にする。周ごとに新しい会話になるので、同じ単位のテスト → 直し → 整えの間も履歴が無い
- 道 B: 包みが単位の切れ目だけ会話を切る（下の案）

## 案（道 B を採る）

### TDD の輪

1. 引き継ぎの節（この一切れで入れた）: `tddloop.prep` が、今の単位より前に済んだ単位の 1 行（単位の key・直したファイル・緑にしたテスト・整えの結末。諦めて direct に回した単位・申し出で止めた単位はそう書く）を `## 前の単位の引き継ぎ（機械が状態から書いた物）` の節に書く。会話を継いでいる今も害は無く、会話を切った後はこれが前の単位の唯一の渡し口になる。
2. 切れ目の印: `tddloop.prep` が状態の置き場に `session-key`（今の単位の key。振り分けの段は `route`）を書く。
3. 包みの `plan()`: 印の名が tdd の起動で、切符の run の置き場から引ける `session-key` が、この節の会話の id と一緒に記録した key と違えば、SDK の会話の旗を外して新しい会話にする（`_strip_session_flags` と new の道。記録は `sessions/<cwd>/tdd.id` の隣に key を足す）。読めない時は今どおり継ぐ（会話を切るのは節約で守りではないので、読めない時に止めない。理由は起動の記録の `session` に残す）。
4. Archon は子の出力の session_id を拾って次の周を継ぐので、切った後の周は新しい会話の続きになる。要確認: Archon v0.11.1 の provider が `--fork-session` の元に前の周の出力の session_id を使うこと（run 195g の鎖の `from` が毎回前の周の id なので、そう動いていると読める）。

### 修正役（fix）

86 分の本体はこちら。単位ごとに新しい会話にするには、節 fix を単位ごとに起こす必要がある。

1. fix-loop の周を「単位 × 出し直し」にする: fix-prep が今の単位 1 つの指示書を書き、fix-accept は今の単位の行だけを確かめて盤面の途中の控えに積む。全部の単位が済んだ周で p3.fix に渡す。max_iterations は Archon では静的なので、義務の単位の上限 × 3 を書き、超えたら R50 と同じく done で抜ける。
2. その輪を `fresh_context: true` にすれば Archon だけで単位ごとに新しい会話になる。出し直しの周も新しい会話になるが、拒否の理由は指示書に書くので動きは保てる。
3. 引き継ぎ: TDD の輪と同じ形の節を fix-prep が途中の控えから書く。
4. fix-ruled の `continue=fix` は「最後の単位の会話」を継ぐことになるので、`continue` を外して新しい会話で裁定の文を読ませる（裁定の文はファイルで渡るので履歴は要らない）。

すでに在る道: 修正の形 g1 では修正役が項目ごとの下請けを新しい会話で起こしている（`works/.shared/core/seat.py` の `g1_section`）。既定の形 入力が空の run（g3）で同じことをするなら、上の 1 の代わりに g1 の下請けの節を g3 にも載せる方が変更は小さい（道具の柵 `works/.shared/core/fixshape.py` の `DENY` の Agent の行を広げる）。どちらを採るかは持ち主が決める。

## 危険

- 会話を切ると、同じ単位の中で役が読んだ物（コード・赤の出力）が消え、読み直しで時間とトークンが増えうる。道 A はこれが大きい。
- fix-accept と盤面の p3.fix を単位ごとに分けるのは、受け付けの規則（写した accept・recount）に触る大きな変更。`works/blk-fix/lib/fixgates.py` と tddloop の `_run`・`run_suite` は並行で別の手が変えているので、この変更はその後に回す。
- 包みの会話の判断は全部の印のある起動に効く。tdd 以外の節に効かないよう、印の名で絞る。

## 最初の一切れ（入れた物）

- `works/blk-fix/lib/tddloop.py`: `HANDOFF_HEAD`・`handoff_lines(st)`、`prep` が今の単位の節の後に引き継ぎの節を足す
- `works/tests/test_blk_fix_tdd.py`: `test_tdd_prep_hands_off_finished_units`
