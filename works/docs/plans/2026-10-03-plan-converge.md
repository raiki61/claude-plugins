# 事前審査の block を修正案の役に返して固める（依頼 231・依頼 230 を含む）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

## この文書の読み方（初めて読む人向け。本文の語はここで全部定める）

読み手: この計画を 1 Task ずつ実装する役と、各 Task を審査する役。リポジトリ（claude-plugins）を手元に持ち、名指したファイルを開いて確かめられる。本文の「今どおり」「今の〜」は、この枝 `wip/sdd-231`（`wip/works-next` の commit dcf9a81d から切った枝。`git log` で確かめられる）の今のコードの振る舞いのまま、の意味で、名指したファイルが正本。

置き場と道具:
- パスは、断りが無ければリポジトリの根からの相対。`works/x.py:20` は 20 行目。
- works: `works/` のプラグイン。Archon（AI の作業の流れを YAML で回す外の道具。版 v0.11.1）の上で、人の修正依頼を直す工程を回す。run は 1 回の実行。
- 線: `works/darkfactory/darkfactory.yaml`。節（YAML の nodes の 1 つ）が一方向に並んだ流れ。判定 → 修正案と事前審査（`planning`。`include: blk-plan`）→ 修正の前の人の関所（`policy-gate`）→ 修正 → … → 報告。
- ブロック: `works/blk-*/`。線が `include` で差し込む節の束。この計画の主役は `works/blk-plan/blk-plan.yaml`（独立設計・修正案・事前審査）。
- 輪（loop_group）: Archon の、節の組を `until_bash` が真になるまで回す節。`max_iterations` が必須で、works の決まり（`works/tests/test_yaml_rules.py`）は 3 に固定する。輪の中に関所（approval）は置けない。今の役はどれも「役の節 1 つ・支度の節・受け付けの節」の輪の中に居て、受け付けが 3 回拒むと `done` で抜ける（裁定 R50: `max_iterations` で落とさない）。
- 盤面: run ごとの状態の置き場（`$ARTIFACTS_DIR/board/`）。今の周（round）の作業ファイルは `b.work(名)`＝`board/r<N>/<名>`。盤面の節（`p2.fix_plan`＝修正案・`p2.plan_review`＝事前審査・`p2.human_gate`＝修正前の関所の項目を組む機械の節・`p3.fix`＝修正）は本流 graphloops の review-loop の graph の写しで、出力は 1 周に 1 度だけ受ける（例外は 1 つ: 修正の前の壁打ちで、後ろの節がまだ 1 つも走っていない役の節 `p2.fix_plan`・`p2.plan_review` を同じ周の待ちに戻す時。Task 3）。役の返答は受け付けが `entry.take` で盤面に渡し、渡すと盤面が次の節を進める（settle）。`p2.plan_review` を渡すと、その場で `p2.human_gate` が走る。
- `Board.rewind(nids, by)`: 写しの engine（`works/.shared/core/graphloops/engine/board.py:228`）の、今の周の節を待ちに戻す公式の口。機械の節（`p2.human_gate` など）は戻せない（die）。返答の置き場は `.stale-r<周>` に退ける。
- 包み: `works/.shared/core/adapter.py`。役の節の `output_format` の頭の印 `works-node: <名>[ continue=<名>]` を読み、`continue=X` の節を X の会話の続きで起こす（今の例: `blk-fix` の `fix-ruled`（`continue=fix`）、`blk-rejudge` の `rejudge`（`continue=judge`））。
- 写し: `works/.shared/core/graphloops/`・`gl-prompts/` は本流のバイト単位の写し。この計画は変えない。
- 試験の段: `works/tests/tiers.py` の FAST（速い段）と HEAVY（重い段）。手元で回すのは速い段と、この計画で触った重い段の模块を名指した物だけ（重い段の全部は GitHub の CI）。

役と目:
- 修正案の役（節 `plan`・盤面の節 `p2.fix_plan`）: 判定の後、直し方の案を書く。
- 事前審査の役（節 `plan-review`・`p2.plan_review`）: 判定をした役とは別の目で案の穴（faces）を挙げる。穴の重さ `severity` は `block`（直しへ進めない）か `suggest`。指示書の頭に独立設計を貼り、構造の食い違いを `contract_drift`・`block` で挙げさせている（`planblk.DESIGN_ASK`）。
- 独立設計（`r2-design`）: 修正案を見ずに目的だけから作る設計。修正の後の独立の目 R2 がそれと差分を比べる。
- keep-essence: `works/docs/keep-essence.md` の、どの形でも残す works の強み 11 項目（4＝3 回拒まれたら諦める・9＝独立設計と R1〜R4・11＝単位ごとの記録が報告と最後の関所に届く、ほか）。

この計画が作る語:
- **壁打ち**: 事前審査が `block` を挙げた時に、修正案の役へ同じ会話で返して案を直させ、新しい会話の事前審査に掛け直す輪。
- **往復**: 壁打ちの 1 回分（案 → 事前審査）。1 往復目は今の修正案と事前審査。2 往復目からは直した案と審査し直し。
- **直しの役**（節 `plan-revise`）: 2 往復目から案を直す修正案の役。印 `works-node: plan-revise continue=plan` で、修正案の役の会話の続きとして起きる。盤面の節は `p2.fix_plan` のまま。
- **壁打ちの抜け方**（`outcome`）: `clean`（最後の審査に block が無い）・`persisted`（前の往復の block の key が今の往復でも block で挙がった）・`unsettled`（柵の往復でも別の block が残った）・`again`（もう 1 往復）。`persisted` と `unsettled` をまとめて**止まった壁打ち**と呼ぶ。
- **柵の往復**: Archon が輪に必ず求める `max_iterations` と同じ 3（`rolekit.GIVE_UP_AFTER`）。新しい定数ではない。
- **設計だけの行**: 今の `gatemarks.DESIGN_ONLY_ITEM`。修正前の関所を開けて「continue で修正へ・stop で報告へ」を聞く行（設計だけの run＝入力 `design_only` の run で使う）。

持ち主の手元にだけ在る資料（読み手は開けなくてよい。要る所はこの文書に書き写した）:
- `~/.cache/works-dogfood/req-231.json`・`req-230.json`: 依頼の文。要旨は Goal と「決めた事」に書き写した。
- `~/.cache/works-dogfood/carry/design-231/`・`design-230/`: 2 つの依頼を設計だけの run（修正をせずに判定・修正案・事前審査・独立設計だけを作る run）に流した出力。design-231 の事前審査は、その run の修正案に block 5 件を挙げた。5 件の中身は下の節「事前審査の 5 件の受け持ち」に 1 件ずつ書き写し、この計画はその 5 件を全部避ける形にした。

---

**Goal:** 事前審査が `block` を挙げた案を直しへ進めず、修正案の役に同じ会話で返して直させ、新しい会話の事前審査に掛け直す。直しへ進むのは最後の審査に `block` の無い案だけにし、同じ `block` が続いた（か柵の往復でも消えない）案は、設計だけの run と同じく修正前の関所で止めて、案・往復ごとの審査・独立設計を並べる。依頼 230（工場が自分で設計を先に通す）はこの 1 つの決まりに寄せ、別の決まりを作らない。

**Architecture:**

- 決まりは 1 つ:「最後の事前審査に `block` が残った案は直しへ進まない（設計だけの行で関所を開く）」。壁打ちを続けるかは事実で決める: `block` が無ければ抜ける（clean）、前の往復の `block` の key がまた `block` なら抜ける（persisted）、柵の往復に達したら抜ける（unsettled）、それ以外はもう 1 往復（again）。この判定は新しい core の模块 `works/.shared/core/converge.py`（標準ライブラリだけ）の純粋な関数 `decide` 1 つが持ち、`blk-plan` の受け付け・修正前の関所（`gatemarks.plan_gate_items`）・報告・最後の関所が同じ控えを読む。
- 盤面の扱い: どの往復の事前審査の返答も、同じ口で盤面が受ける（作業ツリーの比べ・型・番号の読み替え・post_check・記録の検査）。ただし受けた後の settle はまだ回さず、先に往復を記録する。again なら役の節 2 つ（`p2.fix_plan`・`p2.plan_review`）を `Board.rewind` で同じ周の待ちに戻してから settle する（`p2.human_gate` は走らない）。clean・persisted・unsettled ならそのまま settle する（`p2.human_gate` が走り、記録を読む）。だから関所は最後の案と最後の審査だけを見る。機械の節は戻さない。後ろの節が既に受けていれば戻さずに落とす（BoardGap）。写しの graph に辺を足さない。
- Archon の形: `blk-plan.yaml` の事前審査の輪を、新しい外の輪 `converge-loop` の中に移し、その前に直しの役の輪 `plan-revise-loop` を置く（輪の中の輪）。外の輪の終わりの script の節 `converge-check` が `done` を返す。独立設計の輪と最初の修正案の輪は外の輪の外のまま（独立設計は 1 度だけ作り、案を見ない。keep-essence 9）。
- 同じ会話: 直しの役は印 `continue=plan` で修正案の役の会話の続きとして起きる（包みの今の口）。事前審査はどの往復も新しい会話。
- key の揃え: 2 往復目からの事前審査の指示書に前の往復の `block`（key・kind・where・why）と直しの役の答え（fixed／disputed）を貼り、前の `block` の key ごとに「消えた（`resolved` に入れる）か、同じ key で `block` に挙げ直す」かを必ず書かせる。受け付けは、どちらにも無い前の key を拒む。新しい欄 `resolved`（事前審査）と `block_answers`（直しの役）は役の型にだけ在り、盤面へ渡す前に外す（`gatemarks` の決め手の欄と同じ道）。
- 記録: 往復ごとの案・審査・指示書・拒否の控えを `b.work("plan-converge/pass-<k>/")` に上書きせずに写し、抜け方と往復の並びを `b.work("plan-converge.json")` に置く。報告の冒頭 1 と最後の関所の文に壁打ちの行が並ぶ（keep-essence 11）。

**Tech Stack:** Python 3.12 以降の標準ライブラリ、works の盤面の層（`entry`・`board`・`rolekit`・`gatemarks`・`planmarks`・`report`）、Archon の YAML（loop_group の入れ子・include・approval）、unittest（`works/tests`）。

**Spec:**
- 依頼 231 `~/.cache/works-dogfood/req-231.json`（前半の壁打ち。同じ block が続いたら設計だけの run と同じ振る舞い。回数の上限ではなく事実の 1 つの決まり。期限・タイムアウトは足さない。keep-essence 11 を外さない）。
- 依頼 230 `~/.cache/works-dogfood/req-230.json`（工場が自分で設計だけの振る舞いに入る。231 の決まりに寄せる）。
- design-231 の報告 `~/.cache/works-dogfood/carry/design-231/report.md` と、その判定・独立設計 §1〜§7・事前審査の 5 件。design-230 の判定・独立設計 §1〜§6。
- 持ち主の決定: 判断の軸は 1 つ（目的と keep-essence 11 を保って全体がより簡潔か。場合分けを足さない。`works/docs/keep-essence.md`）。review-graph の上位互換で、能力を落とさない。期限・タイムアウトを足さない。壁打ちは superpowers の brainstorming（問いと答えで案を固める）を下敷きにしてよい。

## 決めた事（開いていた問いへの裁定）

1. **柵と「回数の上限でなく事実」**（design-231 の判定の役が人に問うと保留にした問い。その推し A を採る）: 抜ける本体は事実（clean・persisted）。Archon が求める `max_iterations: 3` は柵として置き、柵に当たっても block の残った案を直しへ進めない（unsettled も同じ設計だけの行で関所を開く）。だから「回数で諦めて先へ進む」道は無い。柵の数は `rolekit.GIVE_UP_AFTER` を引数で渡し、`converge` は数の定数を持たない（試験で縛る）。
2. **依頼 230 の決め方**: 230 の 2 案のうち「判定の役の出口の 1 欄」は採らない（判定は修正案と独立設計より前に走るので構造の一致を見られない。判定の型は写しでバイト一致に縛られる）。「事前審査が独立設計との構造の食い違いを block で挙げた事実」は、壁打ちの決まりがそのまま含む（構造の食い違いも block の 1 つで、直しで消えなければ止まる）。230 だけの別の決まり・別の kind・別の述語は作らない。選ばなかった案と理由は CHANGELOG と流れの図の文に 1 文ずつ残す（Task 6）。
3. **盤面の戻し方**（事前の照らし F1・F7 で改めた）: どの往復の事前審査も盤面が settle なしで受け、往復を記録してから、again なら役の節 2 つ（`p2.fix_plan`・`p2.plan_review`）を `Board.rewind` で戻して settle する。again の返答も、ほかの往復と同じく読むだけの役の作業ツリーの比べ（TA11）と盤面の受け付けを通る。戻す前に、後ろの節（`p2.human_gate`・`p3.lane_merge`）が今の周に受けていれば BoardGap で落とす（戻しは後ろへ伝わらないので、前提を機械で縛る）。依頼 226（下の「依頼 226 との重なり」）の計画は `Board.rewind` を使わないと決めたが、その理由（`p3.fix` を戻して直した単位が報告から消えた・機械の節を戻した・写しの守りを `!` 行なしで消した）は修正の後の戻りの話で、修正より前で後ろの節が 1 つも走っていない 231 の戻しには当たらない。写しの rules も同じ周の節の巻き戻しにこの口を使っている（`graphloops/rules/review-loop.py:1693`）。
4. **Archon の形**: 輪の中の輪。Archon v0.11.1 の検査は輪の中の輪を受ける（バイナリの文に「wait nodes nested below another loop_group are not supported」が在り、入れ子の輪そのものは受ける）が、走らせて確かめた記録が works に無い。だから実装の前に運び役（会話で SDD を回す controller）が測る（下の「始める前に」）。測りが通らなければ実装に入らずに運び役へ返す（別の形は今決めない）。
5. **disputed**: 直しの役が block に異を唱え（disputed）、審査がその block を挙げ直した時も persisted（役どうしの意見が割れた事実なので人が決める）。
6. **壁打ちの途中で役が 3 回とも拒まれた時**: 今の修正案の諦めと同じく、出口の `collect` が盤面を止める（keep-essence 4。関所は開かない）。壁打ちの記録は報告に並ぶ。
7. **関所で continue した時**: 今どおり直しへ進み、残った block は修正役の `plan_faces` に申し送られる（人の決定は `process.human_items` に残る）。今の能力（block を残したまま直す）は人の答えの後ろに残る。
8. **依頼 226 の案の直し（replan）**: 壁打ちは最初の修正案（盤面の `p2.fix_plan`）にだけ当てる。226 が `blk-plan` を `replan` の入力で 2 度目に include した時は、壁打ちの節は `go: false`・`done: true` で素通しになる。素通しは replan の場合分けでなく、壁打ちの記録の事実だけで決まる（その include では控えに again の往復が無いので、`plan-revise-snap` は go 偽、`converge-check` は done 真。F2）。案の直しにも壁打ちを当てるかは別の依頼にする。

## 事前審査の 5 件の受け持ち（design-231 の事前審査が、その run の修正案に挙げた block）

1. `human-gate-settles-before-plan-gate`（事前審査を盤面に渡すと関所の節が先に走り、戻した後の案が関所を素通りするか輪が落ちる）→ 盤面は settle なしで受け、again なら役の節 2 つを戻してから settle する（Task 3 の `test_again_does_not_settle_human_gate`）。
2. `same-block-key-never-matches`（新しい会話の審査は前の key を知らず、同じ穴に同じ key を付けない）→ 前の block と答えを貼り、前の key の行き先を必ず書かせる（Task 1 の `resolved_gaps`・Task 3 の `test_rereview_must_account_for_every_previous_block`）。
3. `design-drift-persisted-block-to-fix`（柵の最後の回に block を残したまま直しへ流す。2 つの役を 1 つの輪にまとめると、修正案の役を同じ会話で呼べない）→ unsettled も関所（裁定 1）。役ごとの輪を残し、直しの役は印 `continue=plan`（Task 5）。
4. `line-fixtures-and-format-test-not-followed`（YAML の形の試験と、線の模擬実行の stub が新しい節に追従しない）→ Task 5 が `test_output_format_matches_graph`・`stub_keys`・fixtures の全部を同じ commit で直す。
5. `merged-loop-shares-retry-budget`（1 本の輪で、修正案の拒否・事前審査の拒否・戻しの 3 つが拒否の回数を分け合う）→ 役ごとの輪のまま。往復を進める時に、その往復の拒否の控えを壁打ちの記録へ移す（Task 3 の `rolekit.take_rejects`）。どの往復も役ごとに 3 回まで出し直せる。

## 事前の照らし（F1〜F14）の受け持ち

運び役が計画の版 60253306 を、今のコードと 226 の枝に照らした結果（F1〜F14。置き場は `.superpowers/sdd/2026-10-03-plan-converge/progress.md` の「Pre-flight scan」。運び役が全部を採った）。Task 1 の文は、その実装が先に始まったので変えていない。Task 1 に当たる物は Task 2 以降に置いた。
- F1（again の返答も盤面の受け付けと作業ツリーの比べを通す。役の節 2 つを戻す。`drop_last` と事前審査の snap の特別な条件をやめる）→ Architecture・裁定 3・Task 3。Task 1 が作る `drop_last` は Task 3 で外す。
- F2（直しの役の分かれを replan の分かれより先に置き、記録の事実だけで決める）→ 裁定 8・依頼 226 との重なり・Task 4。
- F3（直しの役の受け付けが自分の作業ツリーの写しと比べる）→ Task 4。
- F4（止めた盤面では `converge-check` が done）→ Task 4。
- F5（記録の取り消しの漏れ）→ F1 で取り消し自体が無くなる（Task 3）。
- F6（往復の写しに `plan-fields.json`）→ Task 3。
- F7（戻す前の守り・「1 周に 1 度」の文）→ この文書の頭の盤面の説明・裁定 3・Task 3・Task 6 の文書。
- F8（入れ子の輪を持つブロックを 2 度 include する測り）→ 「始める前に」の 6（Task 5 より前）・Task 5 の fixtures。
- F9（226 の replan の読んだ証拠の輪の名）→ 依頼 226 との重なり。
- F10（形の試験の 2 つの外れ）→ Task 5。
- F11（無人の run の振る舞いが変わることを書く）→ Global Constraints。
- F12（最後の関所の行の頭の「- 」が二重になる）→ Task 2（Task 1 の `LINE_PASS` は変えず、`line_edge` の側で付け方を決める）。
- F13（試験の下書きの helper の名と見本の key）→ Task 2・3・4・6 の下書き。
- F14（印の付いていない型から直しの役の型を作る）→ Task 4。

## 依頼 226 との重なり（226 が先に入る）

依頼 226 は同じ works への別の依頼で、中身は「修正の後に、裁定役が修正案の項目の誤りと裁いた項目を、同じ run の中で修正案の役に直させる道（案の直し・replan）」。枝 `wip/sdd-226` で作業中で、その計画の文書 `works/docs/plans/2026-10-03-in-run-replan.md` はその枝にだけ在る（要る所はこの節に書き写した）。226 は 231 より先に `wip/works-next` に入る。231 は最後の審査の前に 226 の上へ rebase する。重なるファイルと、rebase で気をつける所:
- `works/blk-plan/blk-plan.yaml`: 226 は入力 `replan` と、script `snap`・`prep`・`accept`・`reads`・`collect` を回す節の全部（`r2-design-snap`・`r2-design-loop` の中の節・`plan-snap`・`plan-prep`・`plan-accept`・`plan-review-snap`・`plan-review-prep`・`plan-review-accept`・`plan-reads`・`collect`）の `with` に `replan: $INPUTS.replan` を足す。231 は `plan-review-snap`・`plan-review-loop` を `converge-loop` の中へ移し、節を足す。rebase では移した節に 226 の `with` を載せ直し、231 の新しい節（`plan-revise-snap`・`plan-revise-prep`・`plan-revise-accept`・`converge-check`）にも `replan: $INPUTS.replan` を足す（裁定 8）。
- `works/blk-plan/lib/planblk.py`: 226 は `snap`・`prep`・`main_accept`・`collect`・`collect_reads` の頭に replan の分かれと、公開の `planblk.design_only(b) -> str`（今の `_design_part` を公開した物）を足す。231 は独立設計の役と同じ形で直しの役の分かれ（`REVISE_ROLE`）を足す。直しの役の分かれは replan の分かれより**先**に置く（226 の replan の口は役 `plan-revise` を知らず BoardGap で落ちるため。直しの役は壁打ちの記録の事実だけで go を決め、replan の include では go 偽になる。F2）。226 の `collect_reads` の replan の分かれも、事前審査の輪の名を `reads.node_path(include, f"{role}-loop", role)` で組んでいる。231 で `plan-review-loop` が `converge-loop` の中に入るので、両方の分かれで入れ子の輪の名（「始める前に」の測り 4 の形）を渡す（F9。直さないと replan の読んだ証拠が黙って空になる）。
- `works/blk-plan/scripts/*`: 226 は今の 5 本の `OPTIONAL` に `INPUTS_REPLAN` を足す。231 は新しい `converge.py` を足す（rebase の後に同じ `OPTIONAL` を持たせる）。
- `works/.shared/core/report.py`（226 は持ち越しの節 `REPLAN_HEAD`・`replanned_lines` を消す。231 は `head_decisions` に 1 行）・`works/darkfactory/lib/line_edge.py`（226 は境の節の at を足す。231 は `_final_text` に 1 行）。
- `works/darkfactory/darkfactory.yaml`（226 は修正と再審の間に案の直しの鎖を足す。231 は `policy-gate` の文と `design_only` の説明だけ）・`works/darkfactory/fixtures/*.stubs.yaml`（両方が 13 本の全部を直す）・`works/tests/test_line.py` の `stub_keys`・`works/tests/linekit.py`・`works/tests/test_blk_plan.py` の入力の集合。
- 文書: `works/docs/darkfactory-flow.md`・`works/CHANGELOG.md`。
- 重ならない: `converge.py`（新しい）・`gatemarks.py`・`rolekit.py`・`entry.py`・`test_plan_gate.py`・`test_converge.py`。

## Global Constraints

- 期限・タイムアウトを新しく足さない。新しい script の節の `timeout: 1728000000` と AI の節の `idle_timeout: 1728000000` は YAML の決まり（`test_yaml_rules.py`）が求める決まった値で、新しい期限ではない。
- 止める決まりは 1 つ（最後の審査に block が残った案は直しへ進まない）。往復の数を数える定数を足さない（`converge` に整数の定数が無いことを試験が縛る）。柵は `rolekit.GIVE_UP_AFTER` を引数で渡す。
- 写し（`works/.shared/core/graphloops/`・`gl-prompts/`）と本流の `graphloops/` は変えない。graph に辺を足さない。
- keep-essence の 11 項目を保つ。4: 役ごとの輪の 3 回の拒否は往復ごとに数える。9: 独立設計は壁打ちの外で 1 度だけ作り、案も往復の記録も渡さない。最後の R1〜R4 は今どおり回る。11: 往復ごとの記録が報告の冒頭 1 と最後の関所の文に届く。
- 上位互換: 入力 `design_only`・入力 `unattended`・関所の continue で直しへ進む道・修正役の `plan_faces` の申し送りは、入力も道も残す。振る舞いの変わる所は 1 つだけで、明示する: 無人の run で壁打ちが止まった（同じ block が続いた・柵の往復でも消えない）時は、今のように直しへ進まず、関所で止まって報告へ進む（Task 6・CHANGELOG に書く。F11）。
- 層（`works/tests/test_layers.py` の `MOD`）: `converge` は L3（`"converge": (3, None)`）で、標準ライブラリだけを import する（`gatemarks` が `converge` を import し、`entry` が `gatemarks` を import するので、`converge` が `entry`・`rolekit`・`gatemarks` を import すると輪になる）。盤面を書き換える手（`rewind`・`settle`・`entry.take`）は `planblk` が持つ。
- 関所と報告の文は平易な名を主語にし、盤面の節の名は括弧の「記録の名」の後ろに置く（`tests/test_plan_gate.py` の `PlainSubjectCase` と同じ決まり）。状態の語 `pass` などを括弧の外に出さない。
- 新しい試験の模块は `works/tests/tiers.py` の FAST か HEAVY に書く（`test_converge` は FAST）。試験はどれも `unittest.TestCase` のクラスの中に置く。
- 新しい模块は `from __future__ import annotations` で始め、注記・docstring・指示書の文・拒否の文は日本語。Python 3.12 が下限。
- 役の返答の型・script の `with` を変えた Task は、同じ Task の中で表の試験（`test_blk_plan`・`test_yaml_rules`・`test_script_contract`・`test_tool_parity`）を合わせる。
- 試験の回し方（どれも `works/` で）: 模块ごと `PYTHONDONTWRITEBYTECODE=1 WORKS_TESTSLOT= python3 -m unittest tests.<module>[.<Class>]`。HEAVY の模块も同じ書き方で、名指した物だけを回す。組の仕上げ（Task 2・5・6 の終わり）に速い段 `WORKS_TESTS=fast sh tests/run.sh`。
- CHANGELOG は `works/CHANGELOG.md` の `[Unreleased]` だけに足す（Task 6）。版は上げない。
- commit のメッセージは日本語で、末尾に `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`。push はしない。

## Review Focus

1. 事前審査が同じ穴に別の key を付ける（key の揺れ）→ 前の往復の block の key が `resolved` にも今の faces にも無ければ受け付けが拒み、役が出し直す。黙って「新しい穴」と読んで往復を続けない。（Task 3 の `test_rereview_must_account_for_every_previous_block`）
2. 直しの役が案を変えずに出し直す・全部に disputed と答える → 審査が同じ key で block を挙げ直し、persisted で関所に止まる。柵まで空回りしない。（Task 1 の `test_block_from_any_earlier_pass_persists`、Task 6 の `test_same_block_stops_at_policy_gate_then_report`）
3. 2 往復目以降に関所の節が古い案で走る・again の返答が受け付けの検査を素通りする → again の返答も盤面が settle なしで受け（読むだけの役の作業ツリーの比べと post_check を通る）、役の節 2 つを戻してから settle するので、`p2.human_gate` は走らず、`pending_human` も立たない。無人の run でも盤面は止まらない。（Task 3 の `test_again_does_not_settle_human_gate`・`test_again_reply_still_checked_by_board_and_tree`）
4. 壁打ちの途中で直しの役か事前審査の役が 3 回とも拒まれる → 今の諦めと同じく出口が盤面を止め、壁打ちの記録（往復ごとの写し）は残って報告に並ぶ。（Task 4 の `test_revise_give_up_stops_board_and_keeps_record`）
5. 前の版で作った盤面の再開・線の 2 周目（darkfactory-rounds の盤面の周 2）→ 控えが無い・周が違う控えは 1 往復目と読んで落ちない。1 周目に設計だけの行へ continue と答えても、2 周目に別の理由で止まった壁打ちは関所を開け直す（答え済みは行の全文で比べる）。（Task 1 の `test_read_without_record_is_first_pass`、Task 2 の `test_continue_answers_only_that_reason`）

## ファイルの地図

- Create `works/.shared/core/converge.py`: 壁打ちの決まり（`decide`）・控えの読み書き・役の型の欄・指示書の節・関所と報告の文。盤面を書き換えない。
- Create `works/blk-plan/scripts/converge.py`: 節 `converge-check` の入口（`planblk.converge_check` を呼ぶ）。
- Modify `works/.shared/core/gatemarks.py`: 設計だけの行の出どころに止まった壁打ちを足す（`design_item`）。
- Modify `works/.shared/core/rolekit.py`: `take_rejects`（往復を進める時に拒否の控えを移す）。
- Modify `works/.shared/core/entry.py`: `take` に keyword `settle`（偽なら盤面は受けるが settle しない。F1）。
- Modify `works/.shared/core/report.py`・`works/darkfactory/lib/line_edge.py`: 壁打ちの行を 1 行ずつ繋ぐ。
- Modify `works/blk-plan/lib/planblk.py`: 事前審査の受け付けの壁打ちの包み・直しの役（支度・受け付け）・`converge_check`・読んだ証拠。
- Modify `works/blk-plan/blk-plan.yaml`・`works/blk-plan/fixtures/*.stubs.yaml`・`works/darkfactory/darkfactory.yaml`・`works/darkfactory/fixtures/*.stubs.yaml`。
- Modify 文書: `works/docs/darkfactory-flow.md`・`works/docs/specs/2026-09-29-structure-block-design.md` の 7 節・`works/CHANGELOG.md`。
- Test: `works/tests/test_converge.py`（新しい・FAST）・`test_plan_gate.py`・`test_report.py`・`test_edge.py`・`test_rolekit.py`・`test_blk_plan.py`・`test_yaml_rules.py`・`test_line.py`・`test_line_a.py`・`linekit.py`・`test_layers.py`・`tiers.py`。

---

## 始める前に（運び役の測り。Task 3 より前）

Task 3 から先は Archon の輪の中の輪を前提にする（Task 3 の受け付けが盤面を待ちに戻すので、外の輪が無いと run が止まる）。だから運び役が Archon v0.11.1 で、AI を使わない最小の工程（include の中の輪の中に輪。中の節は script だけ）と、AI の節を 1 つだけ持つ工程を回し、結果を `.superpowers/sdd/2026-10-03-plan-converge/progress.md` に書く。測る事:

1. 検査: `include` → `loop_group` → `loop_group` の工程を Archon が受ける。
2. 走り: 外の輪が 3 周回る間、中の輪は外の周ごとに 1 周目から回り直す。中の輪の `when` が同じ外の周の兄弟の節の出力を読む（前の外の周の値を読まない）。外の輪の `until_bash` が外の輪の本体の script の節の出力を読む。
3. 模擬実行（dry-run）の stub の鍵: include の中の入れ子の輪の節の名（`<include>__<id>` か、名前空間なしの id か）。`tests/test_line.py` の `stub_keys` と fixtures の名をこれに合わせる。
4. 出来事の節の名（`step_name`）: 入れ子の輪の中の節の名の形（今の 1 段は `<include>__<輪>.<節>`。`works/.shared/core/reads.py:128`）。`planblk.collect_reads` が渡す輪の名をこれに合わせる。
5. 会話: 中の輪の AI の節（`fresh_context: true` の輪）が、外の 2 周目でも SDK の会話の旗（`--resume`・`--session-id` の継ぎ）なしで新しい会話で起きる（包みの起動の記録で見る）。

6.（Task 5 より前。F8）入れ子の輪を持つブロックを 2 度 include する工程（226 の形 A が `blk-plan` を `planning` と `replanning` の 2 度 include するのと同じ形）: 2 つ目の include の入れ子の輪の中の節の出力の参照と出来事の `step_name` が 1 つ目と混ざらないか、模擬実行の stub の鍵の形（入れ子の輪の中の節が `<include>__<id>` か名前空間なしの id か。名前空間なしなら、`plan-review-snap`・`converge-check` などの鍵が 2 つの include で同じになり、1 つの stub の値が両方の go・done に効く）、2 つ目の include の AI の節が 1 つ目の会話を継がないか（226 の測り P4 が残した注）。結果は同じ `progress.md` に書く。

1〜5 のどれかが通らなければ、Task 3 に入らずに運び役へ返す（形を今ここで決め直さない）。6 が通らなければ Task 5 に入らずに返す。Task 1・2 は輪に依らないので、測りの結果を待たずに進めてよい。Task 3・4 は 6 に依らない。

---

### Task 1: 壁打ちの決まりと控え（core の `converge`）

**Files:**
- Create: `works/.shared/core/converge.py`
- Modify: `works/tests/test_layers.py`（`MOD` に `"converge": (3, None)`）・`works/tests/tiers.py`（FAST に `"test_converge"`）
- Test: `works/tests/test_converge.py`（class `DecideCase`・`RecordCase`・`FieldsCase`・`TextCase`）

**Interfaces:**
- Consumes: 盤面の `b` のうち `b.round`・`b.dir`・`b.work(name) -> pathlib.Path`・`b.trace(op, **kw)` だけ（試験は `types.SimpleNamespace` の偽の盤面で足りる）。
- Produces（`converge`）:
  - 定数: `RECORD = "plan-converge.json"`・`PASS_DIR = "plan-converge"`・`BY = "works:plan-converge"`・`OP = "plan_converge"`・`CLEAN, AGAIN, PERSISTED, UNSETTLED = "clean", "again", "persisted", "unsettled"`・`STUCK = (PERSISTED, UNSETTLED)`・`ANSWERS = "block_answers"`・`RESOLVED = "resolved"`・`HANDLED = ("fixed", "disputed")`。整数の定数は持たない。
  - 往復の行: `{"pass": k, "blocks": [key], "faces": [{"key","kind","where","why"}], "suggests": [key], "answers": [{"key","handled","how"}], "resolved": [key], "persists": [key], "outcome": 語, "files": {名: パス}, "rejects": [行]}`。控え: `{"round": n, "passes": [行], "outcome": 語 | None, "open": {"answers": [...]}}`。
  - `block_faces(review: dict) -> list[dict]` — `severity == "block"` の face（key で重複を除き、順を保つ）。
  - `decide(passes: list[dict], *, fence: int) -> str` — 最後の行の `blocks` が空なら `CLEAN`。それより前のどの行かの `blocks` と重なれば `PERSISTED`。`len(passes) >= fence` なら `UNSETTLED`。ほかは `AGAIN`。
  - `read(b) -> dict` — 今の周の控え。無い・読めない・`round` が違うなら `{"round": b.round, "passes": [], "outcome": None, "open": {}}`。
  - `pass_no(b) -> int` — 次の事前審査の往復の番号（`len(passes) + 1`）。
  - `note_answers(b, answers: list) -> None` — 直しの役の答えを `open` に置く（次の `record_pass` が往復の行へ移す）。
  - `record_pass(b, review: dict, *, resolved: list, fence: int, files: dict) -> dict` — 往復の行を足して `decide` で `outcome` を決め、控えを書き（一時のファイルから `os.replace`）、`files` の各ファイルを `b.work(PASS_DIR)/pass-<k>/` に写して行の `files` に写した先を置き、`b.trace(OP, round=, pass_=k, outcome=, blocks=, persists=)` を書く。返りは足した行。
  - `drop_last(b) -> None` — 最後の往復の行を外し、`outcome` を 1 つ前の行の物（無ければ None）に、`open.answers` を外した行の `answers` に戻す（盤面が返答を受けなかった時の取り消し）。
  - `stash_rejects(b, rows: list) -> None` — 最後の往復の行の `rejects` に足す。
  - `held(b) -> dict | None` — `outcome == AGAIN` の時の最後の行。
  - `answer_gaps(b, answers) -> list[str]` — `held(b)` の `blocks` の key ごとに、`key` が一字違わず、`handled` が `HANDLED` のどれかで、`how` が 10 字以上の行がちょうど 1 つ在るか。外れの行の文（例「block の key {key} への答えが無い」「{key} は前の往復の block に無い」）。
  - `resolved_gaps(b, faces: list, resolved: list) -> list[str]` — 1 往復目は `[]`。2 往復目から、前のどの往復かで block だった key が `resolved` にも `faces` の key にも無ければ「前の block {key} を resolved に入れるか、同じ key で faces に挙げ直せ」。`resolved` の key が前の block に無い・`resolved` と block の face の両方に在るのも行にする。
  - `with_fields(role: str, schema: dict) -> dict` — `"plan-revise"` なら必須の `block_answers`（要素は `{key: string minLength 8, handled: enum HANDLED, how: string minLength 10}`、`additionalProperties: false`）を、`"plan-review"` なら任意の `resolved`（文字列の配列）を足した写し。ほかの役はそのまま。
  - `split(role: str, reply: dict) -> tuple[dict, list]` — 返答から上の欄を外した写しと、外した値（無ければ `[]`）。
  - `REVISE_ASK`・`REREVIEW_ASK`（下の字のまま）と `revise_section(b) -> str`（`REVISE_ASK` と、`held(b)` の block の face を 1 件 1 節〔key・kind・where・why〕と suggest の key の一覧）・`review_section(b) -> str`（1 往復目は `""`。2 往復目から `REREVIEW_ASK` と、前の往復ごとの block の face と答え）。
  - `stuck_reason(b) -> str` — `outcome` が `PERSISTED` なら `PERSISTED_WHY`、`UNSETTLED` なら `UNSETTLED_WHY` を埋めた文。ほかは `""`。
  - `lines(b) -> list[str]` — 往復が無ければ `[]`。在れば `LINE_HEAD` の 1 行と、往復ごとに `LINE_PASS` の 1 行。
- 字のまま置く文:
  - `REVISE_ASK`: 「事前審査（別の目）が、お前の修正案に下の block（直しへ進めない穴）を挙げた。block ごとに、案を直したなら handled に fixed、how に直した所を、直さずに異を唱えるなら handled に disputed、how に根拠を、block_answers に 1 行ずつ書け（key は下の key を一字も変えずに写す）。そのうえで直した案を丸ごと plan に返せ（前の案と同じ型。直さない項目もそのまま入れる）。suggest の穴は採っても採らなくてもよい。直した案は新しい会話の事前審査に掛かり、同じ block が残れば直しへ進まずに人の関所で止まる。」
  - `REREVIEW_ASK`: 「下は前の往復で挙がった block と、修正案の役の答え（fixed＝直した・disputed＝異を唱えた）。今の案を読み、前の block の key ごとに、穴が消えたなら resolved にその key を入れ、残っていれば同じ key のまま faces に severity block で挙げ直せ（同じ穴に別の key を付けない。key は一字も変えずに写す）。新しい穴は新しい key で挙げよ。前の block が 1 つでも block のまま残ると、案は直しへ進まず人の関所で止まる。」
  - `PERSISTED_WHY`: 「事前審査（記録の名 p2.plan_review）の同じ block が、案を直した後も残った（{keys}。壁打ち {n} 往復。往復ごとの案と審査: {path}）」
  - `UNSETTLED_WHY`: 「事前審査（記録の名 p2.plan_review）の block が、壁打ち {n} 往復でも消えない（往復ごとに別の穴が出た。最後の block: {keys}。往復ごとの案と審査: {path}）」
  - `LINE_HEAD`: 「事前審査の壁打ち: {n} 往復・抜け方は{word}（記録の名 {outcome}）・続いた block: {persists}（往復ごとの案と審査: {path}）」。`word` は `clean`→「block が消えた」・`persisted`→「同じ block が続いた」・`unsettled`→「柵の往復でも block が消えない」・`again`→「途中」、`persists` は無ければ「無い」。
  - `LINE_PASS`: 「  - {k} 往復目: block {keys}・修正案の役の答え fixed {f} 件・disputed {d} 件・審査が消えたと言った key {resolved}」（無い物は「無い」）。

- [ ] **Step 1: 落ちる試験を書く**

```python
class DecideCase(unittest.TestCase):
    def test_no_block_is_clean(self):
        self.assertEqual(converge.decide([{"blocks": ["a"]}, {"blocks": []}], fence=3), converge.CLEAN)

    def test_new_blocks_only_go_again_before_fence(self):
        self.assertEqual(converge.decide([{"blocks": ["a"]}, {"blocks": ["b"]}], fence=3), converge.AGAIN)

    def test_block_from_any_earlier_pass_persists(self):
        self.assertEqual(converge.decide([{"blocks": ["a"]}, {"blocks": ["a", "b"]}], fence=3), converge.PERSISTED)
        self.assertEqual(converge.decide([{"blocks": ["a"]}, {"blocks": ["b"]}, {"blocks": ["a"]}], fence=3),
                         converge.PERSISTED)   # 消えた穴がまた出た

    def test_fence_with_new_blocks_is_unsettled(self):
        self.assertEqual(converge.decide([{"blocks": ["a"]}, {"blocks": ["b"]}, {"blocks": ["c"]}], fence=3),
                         converge.UNSETTLED)

    def test_module_has_no_count_constant(self):
        self.assertEqual([n for n, v in vars(converge).items() if type(v) is int], [])

class RecordCase(unittest.TestCase):   # 偽の盤面: SimpleNamespace(round=1, dir=tmp, work=lambda n: tmp / "r1" / n, trace=…)
    def test_read_without_record_is_first_pass(self): ...        # 控え無し・round 違い・壊れた JSON → passes [] で pass_no 1
    def test_record_pass_keeps_every_pass_and_copies_files(self): ...
        # 2 往復を記録 → passes 2 行・pass-1/ と pass-2/ に写し・1 往復目の写しは 2 往復目で上書きされない・trace に OP 2 行
    def test_drop_last_undoes_one_pass(self): ...                  # 2 往復目を外すと outcome は 1 往復目の again・open.answers が戻る
    def test_answers_move_from_open_to_pass(self): ...

class FieldsCase(unittest.TestCase):
    def test_answer_gaps_need_one_answer_per_block(self): ...      # 欠け・余分な key・handled の外れ・how の短さを全部並べる
    def test_resolved_gaps_need_every_previous_block_accounted(self): ...
        # 1 往復目は []。2 往復目: 前の key が resolved にも faces にも無い → 行。resolved と block の両方 → 行。前に無い key → 行
    def test_with_fields_and_split_round_trip(self): ...           # plan-revise は block_answers 必須・plan-review は resolved 任意

class TextCase(unittest.TestCase):
    def test_stuck_reason_names_keys_and_record(self): ...
        # persisted → PERSISTED_WHY に key と往復の数と pass の置き場。clean・again・控え無し → ""
    def test_lines_summarize_passes(self): ...                     # 往復無し → []。在れば LINE_HEAD 1 行と往復ごとの行
    def test_texts_keep_record_names_in_parens(self): ...
        # stuck_reason と lines の行を test_plan_gate.internal_subjects に掛けて [] （記録の名は括弧の中だけ）
    def test_review_section_empty_on_first_pass(self): ...
```

- [ ] **Step 2: 落ちることを確かめる**

Run: `PYTHONDONTWRITEBYTECODE=1 WORKS_TESTSLOT= python3 -m unittest tests.test_converge`
Expected: FAIL（`ModuleNotFoundError: No module named 'converge'`）

- [ ] **Step 3: `converge.py` を書き、`MOD` と `FAST` に足す**

- [ ] **Step 4: 通ることを確かめる**

Run: `PYTHONDONTWRITEBYTECODE=1 WORKS_TESTSLOT= python3 -m unittest tests.test_converge tests.test_layers` と `WORKS_TESTS=fast sh tests/run.sh`（`tiers.py` の分け漏れの検査を含む）
Expected: PASS・失敗 0

- [ ] **Step 5: Commit**

```bash
git add works/.shared/core/converge.py works/tests/test_converge.py works/tests/test_layers.py works/tests/tiers.py
git commit -m "feat(works): 事前審査の壁打ちの決まり・往復の控え・役の型の欄・関所と報告の文を core の converge に置く（依頼 231 Task 1）"
```

---

### Task 2: 止まった壁打ちで修正前の関所を開け、報告と最後の関所に並べる

**Files:**
- Modify: `works/.shared/core/gatemarks.py`（`plan_gate_items`・`_design_only_answered`・新しい `design_item`・頭の docstring の設計だけの節）
- Modify: `works/.shared/core/report.py`（`head_decisions` の `lines += gatemarks.lines(b)` の次に 1 行）
- Modify: `works/darkfactory/lib/line_edge.py`（`_final_text` の「直す前の関所で通した項目」の塊の次に 1 行）
- Test: `works/tests/test_plan_gate.py`（class `ConvergeGateCase(GateBase)`）・`works/tests/test_report.py`・`works/tests/test_edge.py`（`FinalGateCase`）

**Interfaces:**
- Consumes: Task 1 の `converge.stuck_reason`・`converge.lines`。
- Produces:
  - `gatemarks.design_item(b) -> str` — 理由＝`converge.stuck_reason(b)`。`design_only(b)` も理由も無ければ `""`。`design_only(b)` だけなら `DESIGN_ONLY_ITEM` そのまま（今の文と同じバイト）。止まった壁打ちが在れば `f"{DESIGN_ONLY_ITEM}。理由: {reason}"`（入力と壁打ちの両方でも 1 行）。
  - `gatemarks._design_only_answered(b, item: str) -> bool` — `process.human_items` に、節 `p2.human_gate`・答え `continue`・`asked` に `item` と同じ文の行が在るか（行の全文で比べる。理由が変われば聞き直す）。
  - `plan_gate_items(b)` の末尾は「`item = design_item(b)`。`item` が空でなく答え済みでなければ `(DESIGN_ONLY_KIND, item)` を足す」の 1 か所だけ。決め手の濾しにも無人の濾しにも掛けない（今の設計だけの行と同じ。無人の run は関所で `works/dev/use.sh:718-723` が stop を返し、報告へ進む）。`KIND_WORDS`・`DESIGN_ONLY_KIND`・`DESIGN_ONLY_ITEM` は変えない。
  - `gatemarks` の頭の docstring の設計だけの節に 1 文:「設計だけの行の出どころは 2 つ（入力 design_only と、事前審査の壁打ちが止まった事実＝converge.stuck_reason）。行は design_item の 1 か所で組む」。import の説明の行に `converge`（L3・標準ライブラリだけ）を足す。
  - `report.head_decisions`: `lines += converge.lines(b)`（`gatemarks.lines(b)` の次）。
  - `line_edge._final_text`: `lines += [x if x[:1].isspace() else f"- {x}" for x in converge.lines(b)]`（「直す前の関所で通した項目」の塊の次）。`LINE_PASS` の行は自分で「  - 」を持つので頭に足さない（「-   - 」と重ならない。F12。Task 1 の `LINE_PASS` は変えない）。
- 固定の行の承認（`works/blk-report/glossary.json` の `reviewed`）: 足す固定の行は無い。`tests/test_blk_report.py` の `fixed_lines` は `line_edge.py`・`report_roles.py` の中の字の断片を拾うが、足す行の字は `"- "`（字も数字も含まない）だけで、文は core の `converge` に在る（拾わない）。`line_edge.py` か `report_roles.py` に字の見出し（例「- 事前審査の壁打ち:」）を足すなら、その行を `reviewed` に足し、行に現れる一覧の語（「関所」など）を並べる。

- [ ] **Step 1: 落ちる試験を書く**

```python
class ConvergeGateCase(GateBase):
    def converged(self, outcome, blocks=("a-key-001",)):
        """b.work の控えに往復と抜け方を置く（converge.record_pass を往復の数だけ）。GateBase の偽の盤面は trace を
        持たないので、この Case の gate() は偽の盤面に trace=lambda op, **kw: None を足す（F13）"""

    def test_stuck_opens_design_item_with_reason(self):
        self.converged(converge.PERSISTED)
        got, b = self.gate()
        self.assertEqual(got["ask"]["kinds"], ["design_only"])
        self.assertTrue(got["ask"]["items"][0].startswith(gatemarks.DESIGN_ONLY_ITEM + "。理由: "))
        self.assertIn("a-key-001", got["ask"]["items"][0])

    def test_clean_or_again_does_not_open(self): ...         # clean・again → {"ok": True}（今どおり項目が無ければ開かない）
    def test_stuck_opens_even_when_unattended(self): ...     # start の控え unattended=true でも設計だけの行は載る
    def test_design_only_and_stuck_give_one_line(self): ...  # design_only=true と persisted → 行は 1 つ・理由つき
    def test_design_only_alone_keeps_todays_text(self): ...  # 入力だけ → 項目の文は DESIGN_ONLY_ITEM と同じバイト
    def test_continue_answers_only_that_reason(self):
        # 行に continue → 2 度聞かない。控えの理由が変わる（別の key で persisted）→ もう一度開く
```

`test_report.py` に `test_head_lists_converge_lines`（`head_decisions` の返りに `converge.lines(b)` の各行が在る）、`test_edge.py` の `FinalGateCase` に `test_final_text_lists_converge_lines`（最後の関所の文に「- 事前審査の壁打ち: 」で始まる行が在り、「-   - 」で始まる行が無い）を足す。

- [ ] **Step 2: 落ちることを確かめる**

Run: `PYTHONDONTWRITEBYTECODE=1 WORKS_TESTSLOT= python3 -m unittest tests.test_plan_gate.ConvergeGateCase`
Expected: FAIL（`AttributeError: module 'gatemarks' has no attribute 'design_item'` か、関所が開かない）

- [ ] **Step 3: `design_item` と 2 つの繋ぎを書く**

- [ ] **Step 4: 通ることを確かめる**

Run: `PYTHONDONTWRITEBYTECODE=1 WORKS_TESTSLOT= python3 -m unittest tests.test_plan_gate tests.test_report tests.test_edge tests.test_blk_report tests.test_layers` と `WORKS_TESTS=fast sh tests/run.sh`
Expected: PASS・失敗 0

- [ ] **Step 5: Commit**

```bash
git add works/.shared/core/gatemarks.py works/.shared/core/report.py works/darkfactory/lib/line_edge.py works/tests/test_plan_gate.py works/tests/test_report.py works/tests/test_edge.py
git commit -m "feat(works): 事前審査の壁打ちが止まった案で修正前の関所を設計だけの行で開け、報告の冒頭と最後の関所に往復を並べる（依頼 231 Task 2）"
```

---

### Task 3: 事前審査のどの往復も盤面が受け、again なら役の節 2 つを同じ周の待ちに戻す

**Files:**
- Modify: `works/.shared/core/entry.py`（`take` に keyword `settle`）
- Modify: `works/.shared/core/rolekit.py`（`take_rejects`）
- Modify: `works/.shared/core/converge.py`（Task 1 が作った `drop_last` とその試験を外す。F1 で使わなくなったため。Task 1 の文は変えず、ここで外す）
- Modify: `works/blk-plan/lib/planblk.py`（`take` に keyword・`take("plan-review")` を包む `with_converge`・戻す前の守り `rewind_roles`・`prep` の事前審査の頭・`output_format("plan-review")`）
- Test: `works/tests/test_entry.py`（`test_take_without_settle_accepts_but_does_not_advance`）・`works/tests/test_rolekit.py`（`test_take_rejects_moves_only_named_nodes`）・`works/tests/test_converge.py`（`drop_last` の試験を外す）・`works/tests/test_blk_plan.py`（class `ConvergeReviewCase`）

**Interfaces:**
- Consumes: Task 1 の `converge.*`（`drop_last` を除く）、`entry.take`・`entry.open_board`・`Board.rewind`・`DiskBoard.accept`・`DiskBoard.settle`。
- Produces:
  - `entry.take(board_dir, nid, reply, repo, *, snapshot_name=None, settle: bool = True) -> dict` — `settle` が偽なら `b.done` の代わりに `b.accept`（型 → 番号の読み替え → post_check → writes → check_record → 保存。settle しない）を呼ぶ。作業ツリーの比べ・止めた run の拒否・AnswerReject の扱いは今と同じ。返りは `{"ok": True, "reason": "", "ready": [], "asking": False, "halted": False, "out_file": …}`（settle しないので進んだ物は無い）。既定の真は今と同じバイトの振る舞い。
  - `rolekit.take_rejects(b, nids) -> list` — 今の周の `REJECTS_NAME` の控えから `node` が `nids` の行を外して書き直し、外した行を返す（往復ごとに 3 回まで出し直せるようにする。keep-essence 4）。
  - `planblk.take(role, *, snapshot: str | None = None, settle: bool = True)` — 今の `take(role)` に 2 つの keyword。`snapshot` は `entry.take` に渡す写しの名（既定は `snapshot_name(role)`。Task 4 の直しの役が使う。F3）、`settle` はそのまま `entry.take` へ。
  - `planblk.rewind_roles(b) -> None`（F7）— `p2.human_gate`・`p3.lane_merge` のどれかが今の周の `b.rd["done"]` に在れば、盤面を止めて（by `converge.BY`）BoardGap（戻しは後ろへ伝わらないので、後ろが受けた後に戻さない）。無ければ `b.rewind(["p2.fix_plan", "p2.plan_review"], by=converge.BY)` と `b.settle()`。機械の節は渡さない（渡せば engine が die する）。
  - `planblk.with_converge(run)` — 事前審査の take の包み。`run` は `take("plan-review", settle=False)`。順:
    1. 形の崩れた返答（dict でない・`faces` が list でない）は `run` に渡す（今どおり `entry.take` が拒み、出し直しの道に乗る）。
    2. `converge.split("plan-review", reply)` で `resolved` を外す。`converge.resolved_gaps` の行が在れば `{"ok": False, "reason": RESOLVED_REJECT + 行}`（盤面へ渡さない）。`RESOLVED_REJECT` は字のまま「前の往復の block の行き先が書かれていない（下の行を全部直して出し直せ）:」。
    3. 外した返答を `run(board, bare, repo)` に渡す（どの往復も同じ口: 作業ツリーの比べ・盤面の受け付け。settle しない）。拒まれたら記録を書かずに拒否を返す（記録の取り消しは要らない。F5 は無くなる）。
    4. 盤面が受けたら `converge.record_pass(b, bare, resolved=, fence=GIVE_UP_AFTER, files={"p2.fix_plan.json": 今の周の修正案の出力, "p2.plan_review.json": 今受けた事前審査の出力, "plan-fields.json": 盤面の根の修正案の欄の控え, "prompt-p2.plan_review.md": 今の指示書})`（`plan-fields.json` は往復ごとに置き直されるので写す。F6）。
    5. 抜け方が `AGAIN` なら `converge.stash_rejects(b, rolekit.take_rejects(b, ["p2.fix_plan", "p2.plan_review"]))` と `rewind_roles(b)`。返り `{"ok": True, "again": True, "reason": "", "ready": [], "asking": False, "halted": False, "out_file": ""}`（受け付けは `done`。中の輪を抜ける）。
    6. ほかの抜け方は `b.settle()` を回し（`p2.human_gate` が走り、記録を読んで設計だけの行を組む）、その進みを返りの `ready`・`asking`・`halted` に置く。
  - 事前審査の snap には特別な条件を足さない（again の後、`p2.plan_review` の待ちの instance は `p2.fix_plan` が受けられるまで出ないので、今の `snap` がそのまま go 偽を返す。F1）。
  - `planblk.prep(..., "plan-review", ...)` の頭の節は `design_section(b) + converge.review_section(b)`（1 往復目は今と同じバイト）。往復ごとに待ちの instance が新しいので、起こした印（`mark_launched`）も往復ごとに付く。
  - `planblk.output_format("plan-review")` は `converge.with_fields("plan-review", <今の値>)`。

- [ ] **Step 1: 落ちる試験を書く**

`ConvergeReviewCase` は `ScriptCase` と同じ種の盤面（`p2.fix_plan` を受けた所）から、`plan-review` の支度と受け付けを子のプロセスで回す（`ScriptCase` の helper を使う。節の状態は `entry.open_board(...).node_state(nid)` で読む——`ScriptCase.state()` は引数を取らない。F13）。返答の見本は `tests/replies/plan_review_regression.json`（block 1 件。key は「clamp の上限の意味が変わる」。試験では見本から `faces[0]["key"]` で引く）と `plan_review_ok.json`（block 無し）。

```python
class ConvergeReviewCase(ScriptCase):
    def test_clean_review_taken_as_today(self):
        got = self.review(reply("plan_review_ok"))
        b = self.board_obj()
        self.assertTrue(got["done"]); self.assertEqual(b.node_state("p2.plan_review"), "done")
        self.assertEqual(converge.read(b)["outcome"], converge.CLEAN)

    def test_again_does_not_settle_human_gate(self):
        got = self.review(reply("plan_review_regression"))
        b = self.board_obj()
        self.assertTrue(got["done"]); self.assertTrue(got.get("again"))
        self.assertNotIn("p2.human_gate", b.rd["done"]); self.assertFalse(b.state.get("pending_human"))
        self.assertIsNotNone(planblk._pending(b, "p2.fix_plan"))          # 修正案は同じ周の待ちに戻った
        self.assertIsNone(planblk._pending(b, "p2.plan_review"))          # 審査の待ちは案を受けるまで出ない
        self.assertEqual(converge.read(b)["outcome"], converge.AGAIN)
        self.assertTrue((b.work(converge.PASS_DIR) / "pass-1" / "plan-fields.json").is_file())

    def test_again_reply_still_checked_by_board_and_tree(self): ...
        # block を持つ返答で (a) 審査の役が作業ツリーを変えた → 拒否（読むだけの役の柵）・(b) unit_keys の誤りで post_check が拒む
        # → どちらも ok False・往復は記録されない・修正案は戻らない
    def test_rewind_refused_when_later_node_done(self): ...
        # 偽に p2.human_gate を今の周の done に置いた盤面で rewind_roles → BoardGap・盤面は止まり・p2.fix_plan は戻らない
    def test_rejects_restart_per_pass(self): ...
        # 1 往復目に事前審査を 2 回拒ませてから again → role-rejects.json に p2.plan_review の行が無く、往復の行の rejects に 2 行
    def test_persisted_review_taken_and_gate_opens_design_item(self): ...
        # again → 直した案を受けた盤面（Task 4 の前なので entry.take で直に渡す）→ 同じ key の block → settle で
        # pending_human の items に design_item の行
    def test_rereview_must_account_for_every_previous_block(self): ...
        # 2 往復目の返答が前の key を resolved にも faces にも持たない → ok False・RESOLVED_REJECT・往復は増えない
    def test_rereview_prompt_carries_previous_blocks_and_answers(self): ...
        # 2 往復目の prompt-p2.plan_review.md に REREVIEW_ASK・前の block の key・where・why
    def test_first_pass_prompt_unchanged(self): ...         # 1 往復目の事前審査の指示書は今の版と同じバイト（converge の節が空）
```

- [ ] **Step 2: 落ちることを確かめる**

Run: `PYTHONDONTWRITEBYTECODE=1 WORKS_TESTSLOT= python3 -m unittest tests.test_blk_plan.ConvergeReviewCase tests.test_rolekit tests.test_entry`
Expected: FAIL（`again` が無い・`p2.human_gate` が走る・`take_rejects` と keyword `settle` が無い）

- [ ] **Step 3: `entry.take` の keyword・`take_rejects`・`rewind_roles`・`with_converge` を書き、`take`・`prep`・`output_format` を繋ぎ、`converge.drop_last` を外す**

- [ ] **Step 4: 通ることを確かめる**

Run: `PYTHONDONTWRITEBYTECODE=1 WORKS_TESTSLOT= python3 -m unittest tests.test_blk_plan.ConvergeReviewCase tests.test_blk_plan.ScriptCase tests.test_rolekit tests.test_entry tests.test_converge tests.test_plan_gate`
Expected: PASS（`YamlCase` の `test_output_format_matches_graph` は Task 5 で YAML を直すまで赤でよい。赤の 1 本を Task 5 へ申し送ると commit のメッセージに書く）

- [ ] **Step 5: Commit**

```bash
git add works/.shared/core/entry.py works/.shared/core/rolekit.py works/.shared/core/converge.py works/blk-plan/lib/planblk.py works/tests/test_blk_plan.py works/tests/test_rolekit.py works/tests/test_entry.py works/tests/test_converge.py
git commit -m "feat(works): 事前審査のどの往復も盤面が settle なしで受けて記録し、again なら役の節 2 つを守りつきで同じ周の待ちに戻す（依頼 231 Task 3。YAML の形の突き合わせは Task 5）"
```

---

### Task 4: 直しの役（修正案の役の会話の続き）と壁打ちの出口

**Files:**
- Modify: `works/blk-plan/lib/planblk.py`（`REVISE_ROLE` の分かれを `snap`・`prep`・`main_accept`・`known_role`・`snapshot_name`・`output_format`・`collect_reads` に。どの関数でも分かれの頭に置く。新しい `converge_check`）
- Create: `works/blk-plan/scripts/converge.py`（`snap.py` と同じ作り。読む入力は無い。226 の rebase の後に `OPTIONAL` の `INPUTS_REPLAN`）
- Test: `works/tests/test_blk_plan.py`（class `ConvergeReviseCase`）

**Interfaces:**
- Consumes: Task 1 の `converge.*`、Task 3 の `with_converge`・`rolekit.take_rejects`・`take(role, *, snapshot=, settle=)`、今の `with_plan_fields`・`plan_slots_section`・`rolekit.compose`・`rolekit.last_reject_file`。
- Produces:
  - `planblk.REVISE_ROLE = "plan-revise"`。盤面の節は `p2.fix_plan`（`known_role(REVISE_ROLE) == "p2.fix_plan"`・`snapshot_name(REVISE_ROLE) == "plan-revise-snapshot.json"`。どちらも今は役 `plan-revise` で BoardGap になるので分かれを足す。F3）。`NODE_OF`・`ROLES` には足さない（`collect` の役の並びは今のまま）。
  - 分かれの順（F2）: `snap`・`prep`・`main_accept` では、直しの役の分かれを独立設計の分かれと並べて関数の頭に置く。226 の rebase の後も replan の分かれより先にする。直しの役が起きるかは壁打ちの記録の事実（`converge.held(b)`）だけで決め、入力 `replan` は見ない（replan の include では again の往復が無いので go 偽になる）。
  - `planblk.output_format(REVISE_ROLE)` — `converge.with_fields("plan-revise", accept.role_schema("p2.fix_plan", numbered=True))`（印の付いていない型から作る。`output_format("plan")` は既に印の description を持ち、`node_marker.mark` が 2 度目の印で落ちる。F14）に印 `works-node: plan-revise continue=plan`（印の組み立ては `node_marker` の今の口で、`continue=` は `rejudge.output_format` と同じ渡し方）。
  - `snap(..., REVISE_ROLE, ...)` — `converge.held(b)` が在り `p2.fix_plan` が待っていれば作業ツリーの写し `plan-revise-snapshot.json` を置いて `go: true`。ほかは `go: false`。
  - `prep(..., REVISE_ROLE, ...)` — 指示書 `b.work(f"prompt-plan-revise-{k}.md")`（`k = converge.pass_no(b)`）に `rolekit.compose([HEAD["plan"] の 1 段落目（読むだけの役の決まり）, converge.revise_section(b), plan_slots_section(b)], reject_file=rolekit.last_reject_file(b, "p2.fix_plan"))` を書き、`b.mark_launched("p2.fix_plan", attempts, pointers=b.pointer_rows("p2.fix_plan")["pointers"])`。返り `{prompt_file, attempt, out_path, node, already}`（`plan` と同じ鍵）。独立設計の節は貼らない。
  - 直しの役の受け付け — `rolekit.main_accept("p2.fix_plan", give_up_after=GIVE_UP_AFTER, take=revise_take())`。`take=` を渡すと `accept_role` は `snapshot_name` を使わないので、作業ツリーの比べは take の中で行う。`revise_take()` の順: `converge.split("plan-revise", reply)` で `block_answers` を外す → `converge.answer_gaps` の行が在れば拒む（頭は字のまま「block への答えに誤りが在る（下の行を全部直して出し直せ）:」）→ 外した返答を `take("plan", snapshot=snapshot_name(REVISE_ROLE))`（`with_plan_fields` で包んだ物。比べる写しは直しの役の snap が置いた `plan-revise-snapshot.json`。1 往復目の `plan-snapshot.json` ではない。F3）に渡す → 盤面が受けたら `converge.note_answers(b, answers)`。
  - `planblk.converge_check(board_dir) -> dict` — `{"ok": True, "done": bool, "outcome": str, "record_file": str}`。`done` は「控えの `outcome` が `AGAIN` でない」か「今の往復で `p2.fix_plan` か `p2.plan_review` の拒否が `GIVE_UP_AFTER` 件に達した」か「盤面が止まっている（`halted` か `stop`）」（止まった盤面では snap・prep が役を起こさず抜け方が again のまま残るので、輪を `max_iterations` で落とさずに抜ける。裁定 R50。F4。報告は今どおり `collect` が出す）。`outcome` は控えの語（無ければ `""`）。止めた盤面でも開ける（`allow_halted=True`）。
  - `collect_reads` — 直しの役の指示書が今の周に在れば役 `plan-revise` の読んだ証拠を `reads-plan-revise.json` に書き、索引に足す。輪の名は測り 4 の形（入れ子の輪の節の名）に合わせて渡す。`plan-review` の輪の名も同じ形に直す。
  - `collect` は変えない（役の節が待ったままなら今どおり最後の拒否の理由で盤面を止める）。

- [ ] **Step 1: 落ちる試験を書く**

```python
class ConvergeReviseCase(ScriptCase):
    def again(self):
        """1 往復目の事前審査を block で受けて again にした盤面（Task 3 の道）。REGRESSION_KEY は見本
        plan_review_regression.json の faces[0]["key"]（「clamp の上限の意味が変わる」）から引く（F13）"""

    def test_revise_snap_only_after_again(self): ...          # again の前・控え無し・clean・persisted は go False・again の後は go True
    def test_revise_compares_its_own_snapshot(self): ...
        # 直しの役が作業ツリーを変えた → 拒否（比べる写しは plan-revise-snapshot.json）
    def test_revise_prompt_names_blocks_and_keys(self):
        self.again()
        p = pathlib.Path(self.prep(planblk.REVISE_ROLE)["prompt_file"]).read_text(encoding="utf-8")
        self.assertIn(converge.REVISE_ASK, p); self.assertIn(REGRESSION_KEY, p)
        self.assertNotIn("=====独立設計ここから=====", p)      # 独立設計は直しの役に渡さない
    def test_revise_reply_must_answer_every_block(self): ...  # block_answers が無い・key 違い → 拒否の文に全部の行
    def test_revise_takes_plan_with_fields_and_notes_answers(self): ...
        # 正しい返答 → p2.fix_plan が done・plan-fields.json が置き直され凍結の印が新しい・converge の open.answers に答え
    def test_check_done_unless_again(self): ...                # 控え無し・clean・persisted → done True。again → done False
    def test_check_done_on_stopped_board(self): ...            # again のまま盤面を止める → done True（F4）
    def test_revise_give_up_stops_board_and_keeps_record(self):
        # 直しの役を 3 回拒ませる → converge_check の done True → collect が盤面を止める（by works:plan）・
        # plan-converge/pass-1/ の写しが残り・report の head_decisions に LINE_HEAD の行
    def test_reads_include_revise_prompt(self): ...
    def test_revise_mark_continues_plan(self):
        self.assertEqual(planblk.output_format(planblk.REVISE_ROLE)["description"], "works-node: plan-revise continue=plan")
```

- [ ] **Step 2: 落ちることを確かめる**

Run: `PYTHONDONTWRITEBYTECODE=1 WORKS_TESTSLOT= python3 -m unittest tests.test_blk_plan.ConvergeReviseCase`
Expected: FAIL（`AttributeError: module 'planblk' has no attribute 'REVISE_ROLE'`）

- [ ] **Step 3: 直しの役の分かれと `converge_check`・script を書く**

- [ ] **Step 4: 通ることを確かめる**

Run: `PYTHONDONTWRITEBYTECODE=1 WORKS_TESTSLOT= python3 -m unittest tests.test_blk_plan.ConvergeReviseCase tests.test_blk_plan.ConvergeReviewCase tests.test_blk_plan.ScriptCase tests.test_layers`
Expected: PASS（`YamlCase` は Task 5 まで赤でよい。Task 3 と同じく commit のメッセージに書く）

- [ ] **Step 5: Commit**

```bash
git add works/blk-plan/lib/planblk.py works/blk-plan/scripts/converge.py works/tests/test_blk_plan.py
git commit -m "feat(works): 事前審査の block を修正案の役の会話の続きで直させる役 plan-revise と、壁打ちの出口 converge-check の口（依頼 231 Task 4。YAML は Task 5）"
```

---

### Task 5: `blk-plan` の輪の中の輪と、線・fixtures・形の試験

**Files:**
- Modify: `works/blk-plan/blk-plan.yaml`（下の形。頭の description の役の並びと出口の説明に壁打ちを足す）
- Modify: `works/blk-plan/fixtures/{pass,give-up,plan-rejected}.stubs.yaml`・`works/darkfactory/fixtures/*.stubs.yaml`（13 本の全部。新しい節の stub。鍵の名は測り 3 と測り 6 の形。測り 6 で入れ子の輪の中の節の鍵が名前空間なしと分かったら、`planning` と 226 の `replanning` の 2 つの include で `plan-review-snap`・`converge-check` などの鍵が重なり、1 つの stub の値が両方の go・done に効くことを、fixtures の頭の注記に名指す。F8）
- Modify: `works/darkfactory/darkfactory.yaml`（`policy-gate` の文の 1 行目の括弧に「事前審査の block が残った案」を足す。入力 `design_only` の description に「事前審査の壁打ちが止まった run も、入力に依らず同じ行で止まる」を足す）
- Modify: `works/tests/test_blk_plan.py`（`YamlCase`）・`works/tests/test_yaml_rules.py`（`RoleSessionCase` が入れ子の輪の役も探す・直しの役を道具の表に）・`works/tests/test_line.py`（`walk` を入れ子へ、`stub_keys` を測り 3 の形へ）・`works/tests/test_tool_parity.py`（直しの役の道具は `plan` と同じ）
- Test: 上の 4 本

**Interfaces:**
- Consumes: Task 3・4 の口（`snap`・`prep`・`accept` の script に `role: plan-revise`、`converge` の script）。
- Produces（`blk-plan.yaml` の並び。`plan-snap`・`plan-loop` までは今のまま）:

```yaml
  # 壁打ち: 事前審査が block を挙げたら修正案の役に同じ会話で返して直させ、新しい会話で審査し直す。抜けるのは
  # converge-check の done（block が無い・同じ block が続いた・柵の往復・役の諦め）。max_iterations で落とさない（R50）
  - id: converge-loop
    depends_on: [plan-snap, plan-loop]
    trigger_rule: none_failed_min_one_success
    loop_group:
      max_iterations: 3
      fresh_context: true
      until_bash: test $converge-check.output.done = true
      nodes:
        - id: plan-revise-snap        # script snap・with {role: plan-revise}・出口 {ok, go, snapshot_file}
        - id: plan-revise-loop
          depends_on: [plan-revise-snap]
          when: "$plan-revise-snap.output.go == true"
          loop_group:
            max_iterations: 3
            fresh_context: false      # 出し直しも修正案の役の会話に積む（印 continue=plan）
            until_bash: test $plan-revise-accept.output.done = true
            nodes:
              - id: plan-revise-prep   # script prep・with {role: plan-revise, excluded_file: $INPUTS.excluded_file}
              - id: plan-revise        # plan の節と同じ道具・settingSources・sandbox・mutates_checkout・idle_timeout。
                                       # output_format は planblk.output_format("plan-revise")（印 works-node: plan-revise continue=plan）
              - id: plan-revise-accept # script accept・with {role: plan-revise, reply: {from: "$plan-revise.output"}}
        - id: plan-review-snap        # 今の節。depends_on: [plan-revise-snap, plan-revise-loop]・trigger_rule: none_failed_min_one_success
        - id: plan-review-loop        # 今の輪のまま（中の 3 節も今のまま。output_format だけ resolved を足した値）
        - id: converge-check          # script converge・depends_on: [plan-review-snap, plan-review-loop]・
                                      # trigger_rule: none_failed_min_one_success・出口 {ok, done, outcome, record_file}
  - id: plan-reads                    # depends_on: [converge-loop]・trigger_rule: none_failed_min_one_success
  - id: collect                       # 今のまま
```

  - 直しの役の節 `plan-revise` に `context` は書かない（`blk-fix` の `fix-ruled` と同じ形。会話を継ぐのは包み）。`plan-revise` は `test_yaml_rules.ROLES`（ブロックの最初の AI の節の一覧）に入れない（`fix-ruled` と同じ扱い）。
  - 新しい script の節と AI の節は、今の同じ種類の節と同じ `runtime`・`timeout`・`idle_timeout`・`sandbox`。

- [ ] **Step 1: 落ちる試験を書く**

```python
class YamlCase(unittest.TestCase):   # 足す・直す物
    def test_converge_loop_wraps_revise_and_review(self):
        top = {n["id"]: n for n in self.y["nodes"]}
        inner = {m["id"]: m for m in top["converge-loop"]["loop_group"]["nodes"]}
        self.assertEqual(list(inner), ["plan-revise-snap", "plan-revise-loop", "plan-review-snap", "plan-review-loop",
                                       "converge-check"])
        self.assertEqual(top["converge-loop"]["loop_group"]["max_iterations"], planblk.GIVE_UP_AFTER)
        self.assertEqual(top["converge-loop"]["loop_group"]["until_bash"], "test $converge-check.output.done = true")
        ids = [n["id"] for n in self.y["nodes"]]
        self.assertLess(ids.index(f"{planblk.DESIGN_ROLE}-loop"), ids.index("converge-loop"))   # 独立設計は輪の外で先に 1 度

    def test_revise_continues_plan_conversation(self): ...
        # plan-revise の output_format == planblk.output_format("plan-revise")・印 continue=plan・context 無し・輪は fresh_context false
    # test_output_format_matches_graph: 入れ子の輪も辿り、役の集合を {plan, plan-revise, plan-review, r2-design} にする。
    #   plan-review・plan-revise は converge.with_fields を当てた値と比べ、strip して欄を外した物が写しの role_schema
    # test_loops_fresh_single_ai_and_give_up: 入れ子の輪も辿り、役の輪は 1 輪 1 AI の節・諦めの数 == max_iterations。
    #   外れは 2 つだけで、試験の中に名指す（試験を弱めたと読まれないため。F10）:
    #   - converge-loop は AI の節を直に持たない外の輪。見るのは中の節の並び・until_bash・max_iterations だけ
    #   - plan-revise-loop は fresh_context false（blk-fix の fix-ruled-loop と同じ。会話を継ぐのは印 continue=plan）
    # test_fixtures: 3 本の筋書きが新しい節を stub する
```

`test_yaml_rules.RoleSessionCase` は役を入れ子の輪の中からも探す（`plan-review` は `converge-loop` の中の `plan-review-loop` に居る）。`test_yaml_rules.WEB_READERS`（web を引く読むだけの役の表）に `("blk-plan", "blk-plan.yaml", "plan-revise")` を足す（F10）。`test_line.walk` は入れ子を辿り、`stub_keys` は測り 3 の名の形で鍵を作る。

- [ ] **Step 2: 落ちることを確かめる**

Run: `PYTHONDONTWRITEBYTECODE=1 WORKS_TESTSLOT= python3 -m unittest tests.test_blk_plan.YamlCase`
Expected: FAIL（`KeyError: 'converge-loop'`）

- [ ] **Step 3: YAML・fixtures・線の文・形の試験を直す**

- [ ] **Step 4: 通ることを確かめる**

Run: `PYTHONDONTWRITEBYTECODE=1 WORKS_TESTSLOT= python3 -m unittest tests.test_blk_plan tests.test_yaml_rules tests.test_line tests.test_tool_parity tests.test_script_contract tests.test_layers` と `WORKS_TESTS=fast sh tests/run.sh`
Expected: PASS・失敗 0（Task 3・4 で申し送った赤も緑）

- [ ] **Step 5: Commit**

```bash
git add works/blk-plan works/darkfactory/darkfactory.yaml works/darkfactory/fixtures works/tests
git commit -m "feat(works): blk-plan の事前審査を壁打ちの輪 converge-loop の中に置き、直しの役の輪と出口を繋ぐ（輪の中の輪は運び役の測りの形。依頼 231 Task 5）"
```

---

### Task 6: 線を通す筋書き（184i の型・止まる型・無人）と文書

**Files:**
- Modify: `works/tests/linekit.py`（`blk_plan` を、設計 → 案 → 壁打ちの輪 → 出口の順に、`planblk` の支度と受け付けの口で回す。役の返答は `replies["plan-review"]`・`replies["plan-revise"]` を 1 つか往復ごとの列で受け、列が尽きたら最後を繰り返す——今の `blk_judge` と同じ読み方。`replies["plan-revise"]` が無ければ、修正案の見本に、前の block の key ごとの `disputed` の答えを足した物）
- Modify: `works/tests/test_line_a.py`（class `ConvergeLineCase`。今の筋書きのうち事前審査の見本が block を持つ物は、壁打ちで同じ block が続いて関所に設計だけの行が 1 行増える——項目の数・種類を断言する試験をその形に直す）
- Modify: `works/docs/darkfactory-flow.md`・`works/docs/specs/2026-09-29-structure-block-design.md`（7 節の 90 行の後に 1 項）・`works/CHANGELOG.md`（`[Unreleased]`）
- Test: `works/tests/test_line_a.py`

**Interfaces:**
- Consumes: Task 1〜5 の全部。
- Produces（文書の字。要旨は下のまま、言い回しは近くの文に合わせてよい）:
  - 流れの図: `PRV -. "細部の穴（予定）" .-> FP` を実線 `PRV -- "block が在る時<br/>（修正案の役に同じ会話で返し、<br/>新しい会話で審査し直す）" --> FP` に。`PRV -. "直し方の形そのものに穴（予定）" .-> DS` は点線のまま（先例の調べが入るまで、形の穴も FP へ戻る）。`PLAN -- ... --> PG` の字に「事前審査の同じ block が続いた時」を足す。
  - 工程 10 に「事前審査が block を挙げたら、修正案の役に同じ会話で返して直させ、新しい会話の事前審査に掛け直す（壁打ち）。直しへ進むのは最後の審査に block の無い案だけ」。工程 11 に「同じ block が続いた（か 3 往復でも消えない）案も、設計だけの run と同じくここで止まる。無人の run も止まって報告へ進む。依頼 230（工場が自分で設計を先に通す）はこの決まりに寄せた——判定の役の出口に欄を足す案は、判定が案と独立設計より前に走るので採らない」。保守の注の「予定の流れ」から事前審査からの戻り（細部の穴）を外し、元にした版を今の commit に。
  - 構造のブロックの設計書 7 節:「2026-10-03 の持ち主の決定（依頼 231）で、細部の穴を修正の段で吸収する形をやめ、事前審査の block は壁打ちで修正案へ戻す。graph の写しに辺は足さず、engine の Board.rewind で役の節 2 つ（修正案と事前審査）だけを同じ周の待ちに戻す。後ろの節（直す前の関所の節など）が受けた後は戻さない（守りが BoardGap で落とす）。同じ block が続いた案は修正前の関所で止まる。依頼 226 の『Board.rewind を使わない』は修正の後の戻り（修正の出力・機械の節が絡む）についての決まりで、後ろの節がまだ走っていない修正の前の戻しには当たらない」（F7）。
  - CHANGELOG `[Unreleased]` の `### Changed`: 壁打ち（同じ会話・新しい会話の審査・key の揃え）・止まる決まり（同じ block・柵の往復も関所。期限は足さない）・振る舞いの変わる所として、無人の run で壁打ちが止まった時は直しへ進まず報告へ進むこと（F11）・報告と最後の関所の往復の行・依頼 230 を寄せたことと選ばなかった案と理由・226 の案の直しには当てない（別の依頼）。

- [ ] **Step 1: 落ちる試験を書く**

```python
class ConvergeLineCase(LineBase):
    def test_block_fixed_on_second_pass_goes_to_fix(self):
        """184i の型: 1 往復目に block、直しの役が fixed、2 往復目の審査が resolved → 関所を開かずに直しへ"""
        r = clean_replies()
        key = reply("plan_review_regression")["faces"][0]["key"]   # 見本の key（F13）
        r["plan-review"] = [reply("plan_review_regression"), {**CLEAN_REVIEW, "resolved": [key]}]
        got = self.run_line(replies=r)
        self.assertNotIn("policy-gate", got["trail"]); self.assertIn("fixing", got["trail"])
        b = entry.open_board(got["board_dir"], allow_halted=True)
        self.assertEqual(converge.read(b)["outcome"], converge.CLEAN)

    def test_same_block_stops_at_policy_gate_then_report(self):
        got = self.run_line(replies=replies(), gates={"policy-gate": {"decision": "stop", "text": "設計を見直す"}})
        self.assertIn(gatemarks.DESIGN_ONLY_ITEM + "。理由: ", got["out"]["h-gate"]["gate_text"])
        for nid in ("fixing", "reviewing", "testing", "final-gate"):
            self.assertNotIn(nid, got["trail"])
        self.assertEqual(got["outcome"], "stopped_by_human")
        # 報告の冒頭 1 に LINE_HEAD の行（抜け方 persisted）

    def test_same_block_continue_goes_to_fix(self): ...       # continue → 直しへ・関所は 1 度・修正役の plan_faces に残った block
    def test_unattended_same_block_stops(self): ...           # inputs unattended=true・関所の答え stop（use.sh と同じ）→ 報告へ
    def test_new_blocks_each_pass_unsettled_at_fence(self): ...
        # 往復ごとに別の key の block → 3 往復で unsettled・関所の行の理由に UNSETTLED_WHY の頭
```

- [ ] **Step 2: 落ちることを確かめる**

Run: `PYTHONDONTWRITEBYTECODE=1 WORKS_TESTSLOT= python3 -m unittest tests.test_line_a.ConvergeLineCase`
Expected: FAIL（`linekit` が壁打ちを回さず、関所に理由の行が無い）

- [ ] **Step 3: `linekit.blk_plan` と筋書き・今の筋書きの断言・文書を直す**

- [ ] **Step 4: 通ることを確かめる**

Run: `PYTHONDONTWRITEBYTECODE=1 WORKS_TESTSLOT= python3 -m unittest tests.test_line_a tests.test_line tests.test_blk_plan tests.test_report tests.test_edge` と `WORKS_TESTS=fast sh tests/run.sh`
Expected: PASS・失敗 0

- [ ] **Step 5: Commit**

```bash
git add works/tests/linekit.py works/tests/test_line_a.py works/docs/darkfactory-flow.md works/docs/specs/2026-09-29-structure-block-design.md works/CHANGELOG.md
git commit -m "feat(works): 線の筋書きで壁打ちの 3 つの抜け方を通し、流れの図・設計書・CHANGELOG を壁打ちに合わせる（依頼 230 を寄せた。依頼 231 Task 6）"
```

---

## 最後に（運び役）

1. 226 が `wip/works-next` に入ったら、この枝を 226 の上へ rebase する（上の「依頼 226 との重なり」の順で載せ直す）。rebase の後に、226 の `replan` の入力で壁打ちの節が素通しになる試験 `test_replan_mode_skips_converge`（`ConvergeReviseCase`。`replan: "true"` で `plan-revise-snap` の go が偽・`converge-check` の done が真）を足す。
2. 枝全体の最後の審査（`--base` は rebase の後の `wip/works-next`）。
3. 入れた後の測り直し: 依頼 231 の数え方（盤面の残る run の `out/r1/p2.plan_review.json` と最後の R2）に、`plan-converge.json` の抜け方と往復の数を足して数える。R2 の作り直しの率（今 62/154）が下がったか、clean で抜けても R2 が作り直しと言う run（block と R2 の理由が 1 対 1 でない 184i の型）が残るかを見る。
