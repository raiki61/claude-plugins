# Archon に返す候補（ためておく所）

works（Archon の上の pack「darkfactory」）が、Archon の不具合や欠けのために自前で回り道をしている所の一覧。本来は Archon がやるべき物の候補をここにためる。

- **まだ送っていない。** Archon の開発元への issue・PR・連絡は、持ち主が決めるまで出さない。ここは送る前の控え。
- 調べた版: Archon v0.11.1（dev の先頭 879c99fe、2026-09-25）。最終の確認: 2026-10-01。
- 「Archon の issue」の「無い」は、全 issue と PR のタイトル（約 3,300 件）と単語の検索で見つからなかった、の意味。本文までの全文の照合はしていない。
- 「今」は今の works で壊れている、「余地」は条件がそろうと壊れる、「無し」は works には効かない。

## 一覧

| # | 候補 | Archon の issue | works への影響 | 確かめ |
|---|---|---|---|---|
| 1 | 節の標準出力 1 MiB の上限 | 無い | 余地 | コード・実測 |
| 2 | 本文の `$節.output.欄` の欄を読み込みで照らさない | 無い（近い #3521） | 余地 | コード・実測 |
| 3 | 誰も読まない出力の欄を指摘しない | 無い | 余地 | コード |
| 4 | 差し込んだ値をもう一度置き換える | 無い | 余地 | コード・実測 |
| 5 | 節の孫のプロセスを止めない | #1242・#3552 open | 余地 | コード・実測 |
| 6 | すぐ死ぬ節で run が running のまま固まる | 近い #3397 open | 余地 | 実測 |
| 7 | network の `strictAllowlist` を黙って捨てる | 無い | 今（包みなし） | コード・実測 |
| 8 | 書く役に柵が無い | #1988 open | 余地（包みなし） | コード |
| 9 | 輪の中で会話を継げない | 無い | 余地（包みなし） | コード |
| 10 | 包みの失敗の種類を伝えられない | #3524 open | 余地 | 実測 |
| 11 | 下流が上流の失敗を読めない・打ち消せない | #3538・#2320・#3306 open | 余地 | 記述 |
| 12 | loop_group の出力に型が無い | #3306 open | 余地 | コード |
| 13 | 模擬実行が出し直しの輪を 1 回で打ち切る | 近い #2707・#1333 open | 余地 | コード |
| 14 | 模擬実行で関所の答えを差せない | 無い | 余地 | コード |
| 15 | 関所の答えに構造の値を載せられない | #2707・#3140 open | 余地 | 記述 |
| 16 | 走っている run の成果物の置き場を CLI が返さない | 無い（近い #3541） | 無し | 実測 |
| 17 | 次の境で止める依頼・取り消し後の最後の節が無い | 無い | 無し | 検索のみ |
| 18 | 期限の上限を検査しない | 無い（近い #2724） | 無し | コード |
| 19 | origin の無い対象で worktree を切れない | #2374・#2380 closed | 無し | 実測 |
| 20 | 同じリポジトリの clone を 1 つの家に 1 つしか置けない | #1192 open | 無し | 記述 |
| 21 | MCP の相対パスが対象の根から引かれる | #1604・#2843 open | 無し | 文書 |
| 22 | 役に読ませる Claude の設定を選べない | #1118・#2842 open | 無し | コード（一部） |
| 23 | 名前が `.js` の実行ファイルに `--no-env-file` を足す | 無い | 無し | コード |
| 24 | 同梱の工程が validate で必ず赤 | 近い #2283・#3526 open | 無し | 記述 |
| 25 | script の節（runtime: uv）が対象の uv の設定を読む | 無い | 余地 | 記述 |
| 26 | 輪の本体の関所の後の再開で止まった回の会話が欠ける | #3532 open（直しの試み PR #3534） | 無し | コード |
| 27 | 節の費用と模型を会話の累計の引き算で決め、補助の模型を節の模型と名乗る | 無い（引き算は #3504 で入った） | 無し（包みが見せ直す） | コード・実測 |
| 28 | `mutates_checkout: false` の節だけの層を順に回す | 直しの PR #3606 merged（2026-10-03。v0.11.1 の後で未リリース） | 余地 | 実測 |
| 29 | resume が all_done で受け止めた上流の失敗を回し直し、輪の周の位置を持たない | 無い（近い #2746・#3468 open） | 余地（回り道あり） | コード |

## 送るなら先に出す物

上から順に、利用者に効く度合いが大きい物。

1. **7（網の柵を黙って捨てる）**: 設定を書いた人は網を絞ったつもりで、実際は開いている。安全に関わる。
2. **1（出力 1 MiB の上限）**: 上限が文書にも validate にも無く、利用者の run が修正の途中で落ちる（works で 2 回起きた）。
3. **5（孫が残る）**: 中断や再開で副作用が二重に走る。#3552 が open。
4. **2・3（参照と出力の静的な確かめ）**: AI にお金を使った後で落ちる・情報が黙って捨てられる。works の 2026-10-01 の監査で、捨てられた情報の多くは「誰も読まない出力」の形だった。
5. **4（値の再置き換え）**: 役の返答に `$` を含む文があると黙って化けるか落ちる。

## 各候補の中身

### 1. 節の標準出力が 1 MiB を超えると節が落ちる
- 足りない物: script・bash の節の子に maxBuffer を渡さず、Node の既定の 1 MiB を超えた所で maxBuffer の誤りになる（dag-executor.ts:3425-3437、packages/git/src/exec.ts:94）。上限は文書にも validate にも無い。
- works の回り道: 出力を切る・全件はファイルに書いて件数だけ出す。`works/blk-structure/lib/eye.py` の `_cut`、`works/.shared/core/leftovers.py`・`works/blk-fix/scripts/clean.py`（fix-removed.json）。
- 求めたい物: 上限を設定できるか、超えたら出力をファイルに逃がす。少なくとも上限を文書と誤りの文に出す。

### 2. 本文に直に書いた `$節.output.欄` の欄を読み込みで照らさない
- 足りない物: 読み込み（loader.ts:922-966）は節の有無しか見ない。`with: {from: …}` の欄は照らす（1164 行）。本文の欄違いは実行時に落ちるので、AI にお金を使った後になりうる。
- 手元の確かめ: 存在しない節への参照は ERROR、存在しない欄への参照は素通り。
- 求めたい物: 本文の参照も相手の `output_format` で照らす。

### 3. 誰も読まない出力の欄を指摘しない
- 足りない物: `output_format` に宣言したのに、どの節も参照しない欄を指摘しない。
- 求めたい物: validate の警告。works では 2026-10-01 の監査で、作ったのに誰も読まない記録が取りこぼしの主な形だった（ただし多くは Archon の外の盤面のファイルで、works 側の作りの問題でもある）。

### 4. 差し込んだ値をもう一度置き換えに通す
- 足りない物: 輪の中で `$LOOP_PREV` を置き換えた結果を、もう一度置き換えに通す（dag-executor.ts:4616-4618 → 2257・3777）。役の返答に `$ARTIFACTS_DIR` や `$x.output.y` があると黙って化けるか OutputRefError で落ちる。
- works の回り道: 理由の本文は渡さずファイルのパスだけ渡す、`$` を含むパスを拒む（`works/.shared/core/rolekit.py:199-200`、`works/.shared/core/script_io.py`）。
- 関連: #1132・#1585・#2488（closed）。

### 5. 節の孫のプロセスを止めない
- 足りない物: 期限・Ctrl-C・cancel が直下の子にしか届かず、uv・bun を挟んだ孫が残る。中断した run を再開すると副作用が二重になる。
- works の回り道: プロセスの木ごと止める `works/.shared/core/tree_run.py`、AI の節の子の Bash は包みで止める、役に背景の作業をさせない（`CLAUDE_CODE_DISABLE_BACKGROUND_TASKS`）。
- 残る余地: 盤面を書く境の節は二重に走りうる（2 度答えない作りで害は一部和らぐ）。
- Archon 側: #1242 open（直しの PR #1248 は merge されずに closed）、#3552 open、#2737 open（AI の節の背景の作業）。

### 6. 節がすぐ死ぬと run が running のまま固まる
- 実測: すぐ死ぬ節で 3 回中 3 回固まり、resume できなかった。
- works の回り道: 止めた後に 1 秒待ってから抜ける（tree_run.py・adapter.py）。
- Archon 側: 近いのは #3397 open（持ち主が抜けた後も Running と出す）。

### 7. network の `strictAllowlist` を黙って捨てる
- 足りない物: sandbox.network の型が知らない鍵を落とす（dag-node.ts:91-100）。役は bypassPermissions 固定（provider.ts:864）なので、allowedDomains に無い宛先にも通信が通る。
- works の回り道: 包みが `strictAllowlist: true` を足す（`works/.shared/core/adapter.py`）。works の線は包みの無い run を既定で拒む。
- 求めたい物: 鍵を通すか、知らない鍵を validate の誤りにする。

### 8. 書く役に柵が無い
- 足りない物: 役は bypassPermissions 固定で、Edit・Write に OS の柵が掛からない。
- works の回り道: 包みが permissions.deny と denyWrite を足す、受け付けで作業ツリーの写しを比べる。
- Archon 側: #1988 open（節の役ごとに区画を切る）。

### 9. 輪の中で会話を継げない
- 足りない物: 輪の中の `context.resume` を拒み（loader.ts:1058）、継ぐ時は fork が必須（1587）。同じ会話に積み増す形が無い。
- works の回り道: 包みの印で `--resume` する（再審の判定役の会話の続き）。

### 10. 包みの失敗の種類を伝えられない
- 足りない物: 0 でない終了は全部一時の失敗として約 12 回起こし直される。1 手も進まずに終わった起動は起こし直されない。
- works の回り道: 1 手も進まない終わりは終了コード 75 で返す、再審の前に会話の id を確かめる。
- Archon 側: #3524 open。

### 11. 下流が上流の失敗を読めない・打ち消せない
- 足りない物: `trigger_rule: all_done` で後ろの節が走っても、親の run は失敗のまま残る。`when:` から節の状態を読めない。
- works の回り道: run の中から `workflow get --events` で出来事を読む、落ちた筋を盤面から推す。
- works で確かめる事: 修正の後の局所レビューのブロック（blk-lens）の集め役が all_done で受けている。レンズが 1 本落ちた時に run 全体が失敗扱いになるか。
- Archon 側: #3538・#2320・#3306 open。

### 12. loop_group の出力に型が無い
- 足りない物: 出力は最後の節の生の文字だけ（loader.ts:175）。
- works の回り道: 各ブロックの輪の後ろに集める節を置く。
- Archon 側: #3306 open。

### 13. 模擬実行が出し直しの輪を 1 回で打ち切る
- 足りない物: 模擬実行（dry-run.ts:852-893）は `until_bash` を評価しない。「拒否→出し直し→通過」の筋書きを確かめられない。
- works の回り道: 自前の模擬 `works/tests/scriptline.py`。
- Archon 側: 近いのは #2707・#1333 open。

### 14. 模擬実行で関所の答えを差せない
- 足りない物: 自動承認の出力が文字列 `'approved'` で、`{decision, text}` の形にならない（dry-run.ts:1183-1207）。
- works の回り道: 関所の後ろの節の stub で答えを差す。

### 15. 関所の答えに構造の値を載せられない
- works の回り道: 無い。同梱の graphloops の写し（0.21.0）が answer_detail を持たないので、`use.sh answer` は `--exclude` を拒み、外したい単位と理由は一言に書く（修正役に届くが、直す義務の数からは外れない）。写しを answer_detail を持つ版に上げた時に口を足す。
- Archon 側: #2707・#3140 open。

### 16〜26（works に効かない・小さい物）
- 16: 走っている run の成果物の置き場を CLI が返さない。works は `output_root` に `/artifacts/runs/<id>` を足して組む。
- 17: 「次の境で止めて」の依頼と、取り消し後に走る最後の節が無い。works は止め札と、外から報告を組む殻で代わりにしている。
- 18: 期限は正で有限かしか見ない。2^31−1 ms を超える値が検査を通り、実行ですぐ失敗する。
- 19: origin の無い対象では worktree を切れない（#2374・#2380 で直ったのは誤りの文言だけ）。
- 20: 同じリポジトリの clone を 1 つの家に 1 つしか置けない（#1192）。
- 21: MCP の相対パスが対象の根から引かれる（#1604・#2843）。
- 22: run の題を作る処理が節の設定を見ずに CLAUDE.md を読む。プラグインを節ごとに絞れない（#1118・#2842）。
- 23: 名前が `.js` で終わる実行ファイルに `--no-env-file` を足す（provider.ts:769-843）。
- 24: 同梱の工程 archon-smart-pr-review が validate で必ず赤（0.12.0 で古い同梱の工程は外れる予定、#3526）。
- 25: script の節（runtime: uv）が対象の uv の設定を読む。
- 26: 本体が approval の関所で終わる loop_group の再開が、止まった回の会話を引き継がない（#3532 open。直しの試みの PR は #3534）。works の関所は全部輪の外の最上段なので影響は無い。縛る試験は `works/tests/test_yaml_rules.py` の `YamlRulesCase.test_each_bad_yaml_is_red`（見本 `yaml_bad/approval_in_loop.yaml`）と `test_pack_yaml_is_green`。

### 27. 節の費用と模型を会話の累計の引き算で決め、補助の模型を節の模型と名乗る
- 足りない物: claude の provider は result の `total_cost_usd`（Claude Code の会話の累計）から、`--resume` に渡した会話の id で覚えた前の result の累計を引いて節の費用にし、引くと負なら費用なし（`not_reported`）、覚えていない id（Archon を起こし直した後など）でも費用なしにする（バンドルの `Ixt.baselineFor`・`F4n`。#3504 の「resume の後の問い合わせごとの費用」）。節の模型（`binding.model.resolved`）は `modelUsage` の模型ごとの `outputTokens` の増えた分が一番多い物で決める（`tHo`）ので、主の模型の増えた分が 0 以下になると、Claude Code が裏で使う補助の模型（claude-haiku-4-5。数十 token）を節の模型と名乗る。引き算の元が Claude Code の本当に継いだ会話と食い違うと、費用も模型も黙って違う値になる。
- 実測: run 01004d2e（canary 2026-10-07）で、包みが単位の切れ目で新しい会話にした tdd-lane-2 の 5 回目が費用なし・模型 claude-haiku-4-5（transcript の手は全部 claude-sonnet-5-5）、範囲の相談の答えの節 plan-answer が費用なし、裁定の後の修正役 fix-ruled の 1 回目（Archon は新しい会話と思う）が修正役の会話の累計 1.87 ドルを節の費用にした（本当は 0.90 ドル）。run の合計は Archon の 10.76 ドルに対して会話の記録の合計 10.21 ドル。
- works の回り道: 包みが会話ごとの本当の累計と見せた累計を残し、Archon の引き算がその起動の本当の費用と模型になる値を result に置いて写す（`works/.shared/core/adapter.py` の頭の 20。試験は `works/tests/test_adapter_spend.py` で、Archon の引き算の写しを縛る）。
- 求めたい物: 節の模型は `system/init` の行か assistant の `message.model` で決める（引き算から推さない）。費用は result の `modelUsage` の模型ごとの `costUSD` か、問い合わせの初めの累計を Claude Code から引く形にし、引けない時は費用なしの理由に「元が知れない」と出す。

### 28. `mutates_checkout: false` の節だけの層を順に回す
- 足りない物: v0.11.1 の層の割り振りは、層に `mutates_checkout: false` の節が 1 つでも在れば層ごと順に回す（`layer.some(node => node.mutates_checkout === false)`）。書かない節だけの層（読むだけの目を同じ checkout に並べる、この鍵の一番の使い道）も、知らせ無しに 1 つずつ走る。
- 実測: 持ち主の測り（2026-10-07）で、書かない節だけの層は v0.11.1 で順に走った。兄弟の loop_group の節は同時に走る（loop_group は鍵の外で「書きうる節」に数える）。
- works の回り道: 並べたい節は loop_group の中に置き、同じ層に `mutates_checkout: false` の節を置かない（TDD の輪の並べの枝の輪 `tdd-lane-loop-<n>`。`works/blk-fix/blk-fix.yaml` の注記と `works/docs/plans/2026-10-07-lane-nodes.md`）。最上段に置いた書かない節（`works/blk-lens/blk-lens.yaml` のレンズ）は今 1 本なので効かないが、2 本目を並べると順になる。
- Archon 側: PR #3606（fix(workflows): parallel read-only nodes no longer run one at a time）が 2026-10-03 に merge 済み。書かない節だけの層は同時に走り、書く節と混ざった層だけ順に回す。v0.11.1 の後の版でリリースされるまでは今の形のまま。上がったら回り道を外せるかを確かめる（候補として送る物ではなく、版上げの時の確かめ）。

### 29. resume が all_done で受け止めた上流の失敗を回し直し、輪の周の位置を持たない
- 足りない物: resume は落ちた節を回し直し、それに依る済んだ節も古いと数えて回し直す（v0.11.1 の `dag-executor.ts:9657` getStaleCachedDependencies。落ちた依り先は値によらず古い）。`trigger_rule: all_done` の節が上流の失敗を受け止めて先へ進めた後でも同じで、落ちた上流は、後ろの節が状態を進めた後の世界でもう 1 度起きる。loop_group は関所・待ちの再開のほかは 1 周目から（4657）、本体は全部回し直し（5062）、1 周目は新しい会話（5069）で、周の位置も止まった周の役の返答も残さない。script の節の副作用と輪の済みの記録は 1 つにまとまらない（確かめの節が状態に「済んだ」を書いた直後に止まると、輪は済んでいないとして 1 周目から起きる）。
- 実測: 初めはコードを読み、works の節の script を resume の順に呼んで再現した（`works/tests/test_tdd_lanes.py`・`test_fix_lanes.py` の `TestResume`）。直す前は TDD の輪の並べの枝が 1 本落ちた run が何度 resume しても続かず、修正役の並べでは回し直された締めが当てた差分を作業ツリーから戻した。2026-10-08 に canary の run 7d95d3bc（`dev/canary.sh --request large`。TDD の輪の枝 2 の役の `claude` だけを止めて枝の輪を落とした）を `workflow resume` で続けて確かめた: 回し直したのは落ちた枝の輪（支度が `go: false`・役は飛び・確かめが done）と、それに依る `tdd-join`（`node_prior_cache_invalidated`。同じ出口）と、落ちた `result` だけで、後ろの節は前の済みのまま使われた。ただ、依り先の出口が替わらない済んだ節は、前の試みの失敗を出来事から読んでいても回し直されない: works の機械の報告 `report` は落ちた節を出来事で見て結末 interrupted を書くので、`result` が前の試みの interrupted を読んで何度 resume しても落ち、run は completed にならなかった（works は `report` に `always_run: true` を付けて直した）。また、resume は run を始めた時に Archon が写した工程の元（`<workspace>/workflow-source/runs/<run id>/`。digest を run の行と突き合わせる。`workflow-source.ts` の loadWorkflowSource）で走るので、始めた後に pack を入れ替えても、その run の resume には効かない。
- works の回り道: 輪の位置を盤面の状態に持ち、済んだ枝の輪は支度の `go: false` で役を飛ばして抜け、締めは前の出口を返す（`works/docs/plans/2026-10-07-lane-nodes.md` の 4、`2026-10-07-fix-lane-nodes.md` の 2）。TDD の順の輪の短い窓（上の「直後に止まる」）も、済んだ輪の支度が `go: false` を返して同じ形で抜ける（2026-10-08）。上流の落ちを出来事で読む `report` は `always_run: true` で resume のたびに回し直す。
- Archon 側: 近いのは #2746（resume で選んだ節を古いと数えて回し直す。逆向きの選び）と #3468（口座の上限で落とさず、戻るまで待つ。入れば上限で枝の輪が落ちる形がそもそも起きない）。どちらも open（2026-10-08 にタイトルを検索）。
- 求めたい物: all_done の節が受け止めた失敗の上流を resume で回さない選び（節ごとの鍵など）か、resume で回し直す節に「回し直し」と前の周の番号を知らせる環境変数。script の節の終わりと輪の済みの記録を 1 つにまとめる（until_bash を回し直しの前に評価する）。

## works 側で直す物（Archon に返す物ではない）

調べの途中で見つかった、Archon に既にある機能を works が使っていない所と、古い記述。

1. 節の段の `mutates_checkout: false`（v0.11.1、#2771）が使える。設計書（`works/docs/specs/2026-09-26-darkfactory-design.md:173`、`works/docs/plans/2026-09-26-darkfactory-v1.md:50`）の「include で落とされるので当てにしない」は工程の段の鍵の話で、節の段には当たらない。読むだけの役に重ねて付ける。依頼 183 で、Bash・Edit・Write を持たない読むだけの AI の節に付け、設計書と計画の記述を直した（Bash を持つ読む役に付けないのは依頼 183 の人の答え）。
2. 節の `mcp:` が在る。包みの `--mcp-config` を置き換えられるかは未確認（env での切り替えは Archon にできない）。
3. `works/darkfactory/darkfactory.yaml:64` の「関所の文は `$WORKFLOW_ID` しか置き換えない」は不正確（`$節.output` も置き換わる）。依頼 183 で直した（今は :67）。
4. design.md:181 の「人の関所を持つラインは外から cancel もできない」は今の形と合わない。依頼 183 で直した（single-run 設計 5.3 を指す）。
5. 節の間の大きな受け渡しは `archon_artifact` の指しで渡すと設計書が決めていたが、今は使う所が 0 件。依頼 178 で扱う。
