# Archon の挙動への回り道

works（Archon の上の pack「darkfactory」）が、Archon v0.11.1 の挙動に合わせて自前で持っている回り道の一覧。項目ごとに、Archon が何をするか・works がどう避けているか・回り道の在りか（ファイル）・いつ外せるかを書く。Archon の開発元へは連絡しない（持ち主の決め 2026-09-28）。挙動が変わるのを知るのは Archon の版を上げる時なので、版を上げる時にこの一覧の「外せる時」を上から確かめる。

- 調べた版: Archon v0.11.1（dev の先頭 879c99fe、2026-09-25）。挙動の最終の確認: 2026-10-01（28〜31 は 2026-10-07〜08）。回り道の在りかは 2026-10-09 に今のコードで確かめた。
- 影響の列: 「今」は今の works で壊れている（「包みなし」は包みを通さない run で）、「余地」は条件がそろうと壊れる、「無し」は works には効かない。

## 一覧

| # | Archon の挙動 | works への影響 | 確かめ |
|---|---|---|---|
| 1 | 節の標準出力 1 MiB の上限 | 余地 | コード・実測 |
| 2 | 本文の `$節.output.欄` の欄を読み込みで照らさない | 余地 | コード・実測 |
| 3 | 誰も読まない出力の欄を指摘しない | 余地 | コード |
| 4 | 差し込んだ値をもう一度置き換える | 余地 | コード・実測 |
| 5 | 節の孫のプロセスを止めない | 余地 | コード・実測 |
| 6 | すぐ死ぬ節で run が running のまま固まる | 余地 | 実測 |
| 7 | network の `strictAllowlist` を黙って捨てる | 今（包みなし） | コード・実測 |
| 8 | 書く役に柵が無い | 余地（包みなし） | コード |
| 9 | 輪の中で会話を継げない | 余地（包みなし） | コード |
| 10 | 包みの失敗の種類を伝えられない | 余地 | 実測 |
| 11 | 下流が上流の失敗を読めない・打ち消せない | 余地 | 記述 |
| 12 | loop_group の出力に型が無い | 余地 | コード |
| 13 | 模擬実行が出し直しの輪を 1 回で打ち切る | 余地 | コード |
| 14 | 模擬実行で関所の答えを差せない | 余地 | コード |
| 15 | 関所の答えに構造の値を載せられない | 余地 | 記述 |
| 16 | 走っている run の成果物の置き場を CLI が返さない | 無し | 実測 |
| 17 | 次の境で止める依頼・取り消し後の最後の節が無い | 無し | 検索のみ |
| 18 | 期限の上限を検査しない | 無し | コード |
| 19 | origin の無い対象で worktree を切れない | 無し | 実測 |
| 20 | 同じリポジトリの clone を 1 つの家に 1 つしか置けない | 無し | 記述 |
| 21 | MCP の相対パスが対象の根から引かれる | 無し | 文書 |
| 22 | 役に読ませる Claude の設定を選べない | 無し | コード（一部） |
| 23 | 名前が `.js` の実行ファイルに `--no-env-file` を足す | 無し | コード |
| 24 | 同梱の工程が validate で必ず赤 | 無し | 記述 |
| 25 | script の節（runtime: uv）が対象の uv の設定を読む | 余地 | 記述 |
| 26 | 輪の本体の関所の後の再開で止まった回の会話が欠ける | 無し | コード |
| 27 | 節の費用と模型を会話の累計の引き算で決め、補助の模型を節の模型と名乗る | 無し（包みが見せ直す） | コード・実測 |
| 28 | `mutates_checkout: false` の節だけの層を順に回す | 余地 | 実測 |
| 29 | resume が all_done で受け止めた上流の失敗を回し直し、輪の周の位置を持たない | 余地（回り道あり） | コード |
| 30 | AI の節が前の AI の節の会話を黙って継ぐ | 余地（試験で縛る） | コード・実測 |
| 31 | Claude の節の返答を返答の道具に強い、出し直さない | 余地（回り道あり） | コード・実測 |

## 各項目の中身

### 1. 節の標準出力が 1 MiB を超えると節が落ちる
- Archon の挙動: script・bash の節の子に maxBuffer を渡さず、Node の既定の 1 MiB を超えた所で maxBuffer の誤りになる（dag-executor.ts:3425-3437、packages/git/src/exec.ts:94）。上限は文書にも validate にも無い。works では修正の途中で 2 回落ちた。
- works の回り道: 出力を切る・全件はファイルに書いて件数だけ出す。`works/blk-structure/lib/eye.py` の `_cut`、`works/.shared/core/leftovers.py`・`works/blk-fix/scripts/clean.py`（fix-removed.json）。
- 外せる時: Archon が上限を設定で上げられるか、超えた出力をファイルに逃がすようになった版。それまでは標準出力に大きな物を出さない作りを続ける。

### 2. 本文に直に書いた `$節.output.欄` の欄を読み込みで照らさない
- Archon の挙動: 読み込み（loader.ts:922-966）は節の有無しか見ない。`with: {from: …}` の欄は照らす（1164 行）。本文の欄違いは実行時に落ちるので、AI にお金を使った後になりうる。
- 手元の確かめ: 存在しない節への参照は ERROR、存在しない欄への参照は素通り。
- works の回り道: 速い段の試験 `works/tests/test_line_inputs.py` の `test_output_refs_name_real_fields` が、ラインとブロックの YAML と指示書（commands/）の `$節.output.欄` を、同じ工程に在る節とその出力の型（include はブロックの出口の型）で照らし、無い節・無い欄・型の無い節の欄を赤にする（コメントの中の参照も見る）。
- 外せる時: Archon が本文の参照も相手の `output_format` で照らすようになった版。それまでは試験を残す。

### 3. 誰も読まない出力の欄を指摘しない
- Archon の挙動: `output_format` に宣言したのに、どの節も参照しない欄を指摘しない。works では 2026-10-01 の監査で、作ったのに誰も読まない記録が取りこぼしの主な形だった（ただし多くは Archon の外の盤面のファイルで、works 側の作りの問題でもある）。
- works の回り道: 同じ試験の `test_line_outputs_have_readers` が、ラインの節の出力の欄（include はブロックの出口の欄。同じブロック・同じスクリプトの節はまとめて見る）に、ラインのどこかの読み手（`$節.output.欄` の名指しか、出力を丸ごと受けた節のコードが欄の名を字で書く）が在るかを見る。今ある読み手の無い欄は、理由つきの表 `UNREAD_OUTPUTS` に置き、減る向きにだけ動かす。丸ごと渡しの読みは字の当たりで見る緩い近似で（`reason` のようなありふれた名はどこかに当たる）、偽の赤は出さないが見逃しはありうる。ブロックの中の節どうしの欄と、盤面のファイルの読み手は見ない。
- 外せる時: Archon の validate が読み手の無い欄を警告するようになった版。

### 4. 差し込んだ値をもう一度置き換えに通す
- Archon の挙動: 輪の中で `$LOOP_PREV` を置き換えた結果を、もう一度置き換えに通す（dag-executor.ts:4616-4618 → 2257・3777）。役の返答に `$ARTIFACTS_DIR` や `$x.output.y` があると黙って化けるか OutputRefError で落ちる。
- works の回り道: 拒否の本文は `$LOOP_PREV` で貼らず、script の節が指示書の頭に貼る（`works/.shared/core/rolekit.py` の `with_reject`）。盤面のパスが `$` を含めば節を 2 で断る（`works/.shared/core/script_io.py` の `board_dir`、`works/blk-judge/scripts/brief.py`・`verify.py`）。
- 外せる時: Archon が置き換えた結果をもう一度置き換えに通さなくなった版。

### 5. 節の孫のプロセスを止めない
- Archon の挙動: 期限・Ctrl-C・cancel が直下の子にしか届かず、uv・bun を挟んだ孫が残る。中断した run を再開すると副作用が二重になる。
- works の回り道: プロセスの木ごと止める `works/.shared/core/tree_run.py`、AI の節の子の Bash は包みで止める、役に背景の作業をさせない（`CLAUDE_CODE_DISABLE_BACKGROUND_TASKS`。`works/.shared/core/adapter.py`）。
- 残る余地: 盤面を書く境の節は二重に走りうる（2 度答えない作りで害は一部和らぐ）。
- 外せる時: Archon が期限・中断を孫まで届けるようになった版。背景の作業を切るのは AI の節の背景の作業を Archon が扱うまで残す。

### 6. 節がすぐ死ぬと run が running のまま固まる
- 実測: すぐ死ぬ節で 3 回中 3 回固まり、resume できなかった。
- works の回り道: 止めた後に 1 秒待ってから抜ける（`works/.shared/core/tree_run.py` の LINGER。包み `works/.shared/core/adapter.py` も同じ値を使う）。
- 外せる時: すぐ死ぬ節でも run が固まらない版。確かめは同じ実測（すぐ死ぬ節を 3 回）。

### 7. network の `strictAllowlist` を黙って捨てる
- Archon の挙動: sandbox.network の型が知らない鍵を落とす（dag-node.ts:91-100）。役は bypassPermissions 固定（provider.ts:864）なので、allowedDomains に無い宛先にも通信が通る。設定を書いた人は網を絞ったつもりで、実際は開いている。
- works の回り道: 包みが `strictAllowlist: true` を足す（`works/.shared/core/adapter.py`）。works の線は包みの無い run を既定で拒む。
- 外せる時: Archon が鍵を通すか、知らない鍵を validate の誤りにする版。

### 8. 書く役に柵が無い
- Archon の挙動: 役は bypassPermissions 固定で、Edit・Write に OS の柵が掛からない。
- works の回り道: 包みが permissions.deny と denyWrite を足す（`works/.shared/core/adapter.py`）、受け付けで作業ツリーの写しを比べる。
- 外せる時: Archon が節の役ごとに書ける所を区切れるようになった版。

### 9. 輪の中で会話を継げない
- Archon の挙動: 輪の中の `context.resume` を拒み（loader.ts:1058）、継ぐ時は fork が必須（1587）。同じ会話に積み増す形が無い。
- works の回り道: 包みの印 `continue=<節>` で `--resume` する（再審の判定役の会話の続きなど。`works/.shared/core/adapter.py`）。
- 外せる時: Archon が輪の中でも同じ会話に積み増せるようになった版。

### 10. 包みの失敗の種類を伝えられない
- Archon の挙動: 0 でない終了は全部一時の失敗として約 12 回起こし直される。1 手も進まずに終わった起動は起こし直されない。
- works の回り道: 1 手も進まない終わりは終了コード 75 で返す（`works/.shared/core/adapter.py`）、再審の前に会話の id を確かめる（`works/.shared/core/rejudge.py`）。
- 外せる時: Archon が包みから失敗の種類（起こし直すか）を受け取れるようになった版。

### 11. 下流が上流の失敗を読めない・打ち消せない
- Archon の挙動: `trigger_rule: all_done` で後ろの節が走っても、親の run は失敗のまま残る。`when:` から節の状態を読めない。
- works の回り道: run の中から `workflow get --events` で出来事を読む（`works/.shared/core/reads.py`）、落ちた筋を盤面から推す。
- works で確かめる事: 修正の後の局所レビューのブロック（blk-lens）の集め役が all_done で受けている。レンズが 1 本落ちた時に run 全体が失敗扱いになるか。
- 外せる時: Archon の `when:` が節の状態を読めるか、all_done で受け止めた失敗を run の失敗から外せる版。

### 12. loop_group の出力に型が無い
- Archon の挙動: 出力は最後の節の生の文字だけ（loader.ts:175）。
- works の回り道: 各ブロックの輪の後ろに集める節を置く（`works/blk-*/scripts/collect.py`）。
- 外せる時: loop_group の出力に型を宣言できる版。集める節は型の確かめのほかの仕事も持つので、全部は外れない。

### 13. 模擬実行が出し直しの輪を 1 回で打ち切る
- Archon の挙動: 模擬実行（dry-run.ts:852-893）は `until_bash` を評価しない。「拒否→出し直し→通過」の筋書きを確かめられない。
- works の回り道: 自前の模擬 `works/tests/scriptline.py`。
- 外せる時: Archon の模擬実行が `until_bash` を評価する版。

### 14. 模擬実行で関所の答えを差せない
- Archon の挙動: 自動承認の出力が文字列 `'approved'` で、`{decision, text}` の形にならない（dry-run.ts:1183-1207）。
- works の回り道: 関所の後ろの節の stub で答えを差す（`works/darkfactory/fixtures/*.stubs.yaml`）。
- 外せる時: Archon の模擬実行で関所の答えを差せる版。

### 15. 関所の答えに構造の値を載せられない
- works の回り道: 無い。同梱の graphloops の写し（0.21.0）が answer_detail を持たないので、`use.sh answer` は `--exclude` を拒み（`works/dev/use.sh`）、外したい単位と理由は一言に書く（修正役に届くが、直す義務の数からは外れない）。
- 外せる時: Archon の関所の答えに構造の値を載せられ、写しを answer_detail を持つ版に上げた時に口を足す。

### 16〜26（works に効かない・小さい物）
- 16: 走っている run の成果物の置き場を CLI が返さない。works は `output_root` に `/artifacts/runs/<id>` を足して組む（`works/dev/canary_check.py` など）。
- 17: 「次の境で止めて」の依頼と、取り消し後に走る最後の節が無い。works は止め札（`works/dev/stop.sh`・`works/.shared/core/halt.py`）と、外から報告を組む殻（`works/dev/report.sh`）で代わりにしている。
- 18: 期限は正で有限かしか見ない。2^31−1 ms を超える値が検査を通り、実行ですぐ失敗する。works は期限の値を試験で縛る（`works/tests/test_yaml_rules.py`、見本 `yaml_bad/timeout_25days.yaml`）。
- 19: origin の無い対象では worktree を切れない（直ったのは誤りの文言だけ）。
- 20: 同じリポジトリの clone を 1 つの家に 1 つしか置けない。
- 21: MCP の相対パスが対象の根から引かれる。
- 22: run の題を作る処理が節の設定を見ずに CLAUDE.md を読む。プラグインを節ごとに絞れない。
- 23: 名前が `.js` で終わる実行ファイルに `--no-env-file` を足す（provider.ts:769-843）。
- 24: 同梱の工程 archon-smart-pr-review が validate で必ず赤（0.12.0 で古い同梱の工程は外れる予定）。
- 25: script の節（runtime: uv）が対象の uv の設定を読む。回り道は持たず、既知の限界として `works/README.md` の「入れ方」の節に書く。
- 26: 本体が approval の関所で終わる loop_group の再開が、止まった回の会話を引き継がない。works の関所は全部輪の外の最上段なので影響は無い。縛る試験は `works/tests/test_yaml_rules.py` の `YamlRulesCase.test_each_bad_yaml_is_red`（見本 `yaml_bad/approval_in_loop.yaml`）と `test_pack_yaml_is_green`。

### 27. 節の費用と模型を会話の累計の引き算で決め、補助の模型を節の模型と名乗る
- Archon の挙動: claude の provider は result の `total_cost_usd`（Claude Code の会話の累計）から、`--resume` に渡した会話の id で覚えた前の result の累計を引いて節の費用にし、引くと負なら費用なし（`not_reported`）、覚えていない id（Archon を起こし直した後など）でも費用なしにする（バンドルの `Ixt.baselineFor`・`F4n`。resume の後の問い合わせごとの費用の仕組み）。節の模型（`binding.model.resolved`）は `modelUsage` の模型ごとの `outputTokens` の増えた分が一番多い物で決める（`tHo`）ので、主の模型の増えた分が 0 以下になると、Claude Code が裏で使う補助の模型（claude-haiku-4-5。数十 token）を節の模型と名乗る。引き算の元が Claude Code の本当に継いだ会話と食い違うと、費用も模型も黙って違う値になる。
- 実測: run 01004d2e（canary 2026-10-07）で、包みが単位の切れ目で新しい会話にした tdd-lane-2 の 5 回目が費用なし・模型 claude-haiku-4-5（transcript の手は全部 claude-sonnet-5-5）、範囲の相談の答えの節 plan-answer が費用なし、裁定の後の修正役 fix-ruled の 1 回目（Archon は新しい会話と思う）が修正役の会話の累計 1.87 ドルを節の費用にした（本当は 0.90 ドル）。run の合計は Archon の 10.76 ドルに対して会話の記録の合計 10.21 ドル。
- works の回り道: 包みが会話ごとの本当の累計と見せた累計を残し、Archon の引き算がその起動の本当の費用と模型になる値を result に置いて写す（`works/.shared/core/adapter.py` の頭の 20。試験は `works/tests/test_adapter_spend.py` で、Archon の引き算の写しを縛る）。
- 外せる時: Archon が節の模型を `system/init` の行か assistant の `message.model` で決め（引き算から推さない）、費用を result の `modelUsage` の模型ごとの `costUSD` か問い合わせの初めの累計から引くようになった版。外す前に `works/tests/test_adapter_spend.py` の引き算の写しを新しい版の形に合わせて確かめる。

### 28. `mutates_checkout: false` の節だけの層を順に回す
- Archon の挙動: v0.11.1 の層の割り振りは、層に `mutates_checkout: false` の節が 1 つでも在れば層ごと順に回す（`layer.some(node => node.mutates_checkout === false)`）。書かない節だけの層（読むだけの目を同じ checkout に並べる、この鍵の一番の使い道）も、知らせ無しに 1 つずつ走る。
- 実測: 持ち主の測り（2026-10-07）で、書かない節だけの層は v0.11.1 で順に走った。兄弟の loop_group の節は同時に走る（loop_group は鍵の外で「書きうる節」に数える）。
- works の回り道: 並べたい節は loop_group の中に置き、同じ層に `mutates_checkout: false` の節を置かない（TDD の輪の並べの枝の輪 `tdd-lane-loop-<n>`。`works/blk-fix/blk-fix.yaml` の注記と `works/docs/plans/2026-10-07-lane-nodes.md`）。最上段に置いた書かない節（`works/blk-lens/blk-lens.yaml` のレンズ）は今 1 本なので効かないが、2 本目を並べると順になる。
- 外せる時: 書かない節だけの層を同時に回す直し（Archon の PR #3606。2026-10-03 に merge、v0.11.1 の後の版）を含む版に上げた時。上がったら、並べを loop_group に置く形を外せるかを確かめる。

### 29. resume が all_done で受け止めた上流の失敗を回し直し、輪の周の位置を持たない
- Archon の挙動: resume は落ちた節を回し直し、それに依る済んだ節も古いと数えて回し直す（v0.11.1 の `dag-executor.ts:9657` getStaleCachedDependencies。落ちた依り先は値によらず古い）。`trigger_rule: all_done` の節が上流の失敗を受け止めて先へ進めた後でも同じで、落ちた上流は、後ろの節が状態を進めた後の世界でもう 1 度起きる。loop_group は関所・待ちの再開のほかは 1 周目から（4657）、本体は全部回し直し（5062）、1 周目は新しい会話（5069）で、周の位置も止まった周の役の返答も残さない。script の節の副作用と輪の済みの記録は 1 つにまとまらない（確かめの節が状態に「済んだ」を書いた直後に止まると、輪は済んでいないとして 1 周目から起きる）。
- 実測: 初めはコードを読み、works の節の script を resume の順に呼んで再現した（`works/tests/test_tdd_lanes.py`・`test_fix_lanes.py` の `TestResume`）。直す前は TDD の輪の並べの枝が 1 本落ちた run が何度 resume しても続かず、修正役の並べでは回し直された締めが当てた差分を作業ツリーから戻した。2026-10-08 に canary の run 7d95d3bc（`dev/canary.sh --request large`。TDD の輪の枝 2 の役の `claude` だけを止めて枝の輪を落とした）を `workflow resume` で続けて確かめた: 回し直したのは落ちた枝の輪（支度が `go: false`・役は飛び・確かめが done）と、それに依る `tdd-join`（`node_prior_cache_invalidated`。同じ出口）と、落ちた `result` だけで、後ろの節は前の済みのまま使われた。ただ、依り先の出口が替わらない済んだ節は、前の試みの失敗を出来事から読んでいても回し直されない: works の機械の報告 `report` は落ちた節を出来事で見て結末 interrupted を書くので、`result` が前の試みの interrupted を読んで何度 resume しても落ち、run は completed にならなかった（works は `report` に `always_run: true` を付けて直した）。また、resume は run を始めた時に Archon が写した工程の元（`<workspace>/workflow-source/runs/<run id>/`。digest を run の行と突き合わせる。`workflow-source.ts` の loadWorkflowSource）で走るので、始めた後に pack を入れ替えても、その run の resume には効かない。
- works の回り道: 輪の位置を盤面の状態に持ち、済んだ枝の輪は支度の `go: false` で役を飛ばして抜け、締めは前の出口を返す（`works/docs/plans/2026-10-07-lane-nodes.md` の 4、`2026-10-07-fix-lane-nodes.md` の 2）。TDD の順の輪の短い窓（上の「直後に止まる」）も、済んだ輪の支度が `go: false` を返して同じ形で抜ける（2026-10-08）。上流の落ちを出来事で読む `report` は `always_run: true` で resume のたびに回し直す。
- 外せる時: Archon が、all_done の節が受け止めた失敗の上流を resume で回さない選び（節ごとの鍵など）か、回し直す節に「回し直し」と前の周の番号を知らせる口を持ち、script の節の終わりと輪の済みの記録を 1 つにまとめた（until_bash を回し直しの前に評価する）版。それまでは輪の位置を盤面に持つ形と `report` の `always_run: true` を残す。

### 30. AI の節が前の AI の節の会話を黙って継ぐ
- Archon の挙動: v0.11.1 は、直前に終わった AI の節の会話を次の AI の節に継がせるのを既定にする（`dag-executor.ts` の `lastSequentialSession`。10424-10437 で選び、10813 で更新）。輪の中に限らず、script・bash の節を挟んでも続き、切れるのは節が 2 つ以上の層（9783）・節の `context: fresh`・組み込んだブロックの入口の節（`include-expander.ts:770` の `blockEntry`）・provider が替わる時だけ。入口の切れ目は AI の節の会話を選ぶ所でしか見ないので、入口が script の節のブロック（works のブロックは全部この形）では、中の最初の AI の節が組み込んだ側の前の AI の節の会話を継ぐ。継ぐ時は fork なので、前の節の履歴を全部持って起きる。どの節がどの会話を継ぐかは層の形で決まり、YAML の線（`depends_on`）からは読めない。輪（`loop_group`）の 1 周目は外の会話を継がずに新しい会話（5069）、輪の節の出力は会話の id を持たない（5416）ので、輪の中の節は外へ会話を渡さない。
- 実測: canary の家 17 個（2026-10-07〜08。どれも 0.2.46 の直しの前）の Archon の記録（`node_started` の `binding.sessionOrigin`）と包みの起動の記録（`session.from` の持ち主）で、ほかの節の会話を継いだのは報告の書き手の輪の初見の読み手と書き手の組だけ（直したのは 0.2.46。下の回り道）。輪の外の AI の節 2 つ（判定の裏取りの束ね役・局所レビューのレンズ）は全部新しい会話。ただしレンズは `context: fresh` を持たず、新しい会話なのは、前に在る修正のブロックの並べの層（TDD の輪と修正役の並べの枝）が会話を切っていたからだけで、並べが無くなると判定の裏取りの束ね役の会話を継ぐ形だった。
- works の回り道: 本流の review-graph（役ごとに新しい `claude -p`、会話を継ぐのは `same_context_as` などで宣言した時だけ）と同じに、どの AI の節も会話を宣言させる。輪の外の AI の節は `context: fresh` か包みの印 `continue=<相手>`、輪の中で最初に走る節は輪の `fresh_context` を書く、輪の中のほかの節は `continue=<相手>` か `context: fresh`、会話を継ぐ輪に AI の節が 2 つ以上なら頭は旗 `self-resume` か `continue=` か `context: fresh`（`works/tests/test_yaml_rules.py` の `SessionCase`。`works/README.md` の「会話の決まり」）。
- 外せる時: 外さない。会話の宣言は本流と同じ決まりとして残す。Archon の既定が新しい会話になり、継ぐのが節の `context`（`shared`・`resume`）で宣言した時だけになれば、試験が縛る物が Archon の既定と同じになる。

### 31. Claude の節の返答を返答の道具に強い、出し直さない
- Archon の挙動: v0.11.1 は節の `output_format` を SDK の `outputFormat` にし（`dag-executor.ts` ~1809・`providers/claude/provider.ts` ~715-720）、SDK 0.3.282 は schema を argv の `--json-schema` と stdin の initialize の `jsonSchema` の両方で Claude Code に渡す。Claude Code はそれで返答の道具 StructuredOutput を足し、fork で走る skill（組み込みの `code-review`）も道具を継いで、所見を親に本文で返さずに道具へ書いて終わる。Archon は Claude を型を強いる provider と数えて出し直さず（~2289-2296 の `maxReasks` が 0。出し直しは Pi・Copilot だけ）、`structured_output` が無ければ節を `output_contract` で落とす（~3054）。節の型の決まりが、節の中で起こした下請けの返り方まで変える。
- 実測: 利用者の 6 つの works の家の会話の記録で、`/code-review` の fork 19 本の全部が所見を返答の道具に書き、親の Skill の結果は『Skill execution completed』だけだった（0.2.46 の CHANGELOG。利用者の run f57a5374 で所見 10 件が消えた）。
- works の回り道: 0.2.48 から、局所レビューの節を本流 review-graph と同じ返答の契約で受ける: 包みが両方から schema を外し、返答の形を system prompt で渡し、result の本文を確かめ、合わなければ同じ子に理由を返して出し直させ（2 回まで）、合えば `structured_output` を置いて写す（`works/.shared/core/adapter.py` の頭の 21・`replycontract.py`。設計 `works/docs/plans/2026-10-08-reply-contract.md`）。0.2.46 で入れた記録のフックで fork の書いた物を拾い戻す形（`works/.shared/core/diverted.py`）は、包みを外した run と旗の無い起動の予備として残る。
- 外せる時: Archon が節ごとに返答の受け方（道具で強いる・本文で受けて確かめる）を選べ、Claude でも型の誤りで出し直す（best-effort の provider と同じ出し直しの口）版。

## Archon の機能の使い方の控え（回り道ではない物）

調べの途中で見つかった、Archon に既にある機能の works での使い方。

1. 節の段の `mutates_checkout: false`（v0.11.1）は使える。設計書（`works/docs/specs/2026-09-26-darkfactory-design.md:173`、`works/docs/plans/2026-09-26-darkfactory-v1.md:50`）の「include で落とされるので当てにしない」は工程の段の鍵の話で、節の段には当たらない。依頼 183 で、Bash・Edit・Write を持たない読むだけの AI の節に付け、設計書と計画の記述を直した（Bash を持つ読む役に付けないのは依頼 183 の人の答え）。
2. 節の間の大きな受け渡しは `archon_artifact` の指しで渡すと設計書が決めていたが、今は使う所が 0 件。依頼 178 で扱う。
