# 同じ run の中で修正案の項目を直す道（依頼 226・道 (a)）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

## この文書の読み方（初めて読む人向け。本文の語はここで全部定める）

置き場と道具:
- パスは、断りが無ければリポジトリの根からの相対。`CLAUDE.md:20` は根の `CLAUDE.md` の 20 行目。
- works: `works/` のプラグイン。Archon（AI の作業の流れを YAML で回す外の道具。版 v0.11.1）の上で、人の修正依頼を直す工程を回す。run は 1 回の実行。
- 線: `works/darkfactory/darkfactory.yaml`。節が一方向に並んだ DAG（巡回の無いグラフ）。判定 → 修正案と事前審査 → 修正の前の人の関所 → 修正 → 再審 → 差分の審査 → 手直し → 最後のテスト → 独立の目 → 最後の人の関所 → 報告、の順。
- 盤面: run ごとの状態の置き場（`$ARTIFACTS_DIR/board/`）。周（round）ごとの作業ファイルは `board/r<N>/<名>`（`b.work(名)`）。盤面の節（`p2.fix_plan`・`p2.plan_review`・`p2.human_gate`・`p3.fix` など）は、本流 graphloops の review-loop の graph の写しで、出力は 1 周に 1 度だけ受ける。
- 境の節: 線の `h-*` の節。どれも `darkfactory/scripts/edge.py` を `at` を替えて回し（中身は `darkfactory/lib/line_edge.py` の `edge`）、盤面を読んで次のブロックを回すか（`go`）と関所を開くか（`ask`）を決める。いつも走る。`when:` と関所の文はこの節の出力だけを読む。
- ブロック: `works/blk-*/`。線が `include` で使う。修正案は `blk-plan`、修正は `blk-fix`。
- 写し: `works/.shared/core/graphloops/`・`works/.shared/core/gl-prompts/` は本流のバイト単位の写し。手直しは台帳 `works/.shared/core/COPIED_FROM` の `!` 行（形は `copyledger.py`）だけで入れる。この計画は写しを変えない。
- 試験の段: `works/tests/tiers.py` の FAST（速い段）と HEAVY（重い段: git・盤面・子のプロセスを使う）。手元で回すのは速い段と、この計画で触った重い段の模块を名指した物だけ。重い段の全部は GitHub の CI。

依頼と関わる番号:
- 211: 食い違いの申し出の種類と、裁定 `fix_plan_item`（承認済みの修正案の項目そのものが誤り）。今は、そう裁かれた項目の単位を直す義務から外し、次の run に持ち越す。
- 217: 修正案の項目の works の欄（`route`・`tests`・`rewrite_tests`・`refactor`）と、項目ごとの brief（要求の正本。`works/blk-fix/lib/planbrief.py`）。
- 218: 範囲の欄 `allowed_paths`・`out_of_scope` と、修正の受け付けの照らし（`works/blk-fix/lib/planscope.py`）。
- 224c: 修正役の返答の形の誤りを 1 回の拒否に全部並べる。227: 受け入れのテストの id を既存の置き方に合わせる。どちらもこの枝に入っている。
- 226: この計画。226b・226c は同じ依頼を工場自身に回した run（226b は申し出の unit_key の一字違いで止まり、226c は R1〜R4 の全部が作り直しと言った）。

works の中の語:
- 単位: 判定役が切った 1 つの欠陥。key で呼ぶ。
- 申し出と裁定: 修正役・TDD の役が「依頼・テスト・コードのどれかが同時に成り立たない」と名指しで返す物が申し出。読むだけの裁定役が 5 つ（`fix_test_scope`・`fix_code_as`・`ask_human`・`replace_query`・`fix_plan_item`）のどれかに裁く。控えは `b.work("conflicts.json")`、模块は `works/.shared/core/conflict.py`。
- 直す義務: 修正役が今直す単位の集合（`conflict.fix_duty(b)` の 1 つ目）。外れた単位と理由が 2 つ目（excused）。
- 修正の段の 1 回目・2 回目: この計画で、線の `fixing`（今の修正の段）を 1 回目、案を直した後に足す `refitting` を 2 回目と呼ぶ。どちらも `blk-fix`。
- 案の直し（replan）: `fix_plan_item` と裁かれた項目を、同じ run の中で修正案の役に直させ、事前審査と人の関所の決まりを通して、2 回目の修正の段に戻すこと。この計画が作る。
- 案の直しを待つ単位: `fix_plan_item` の裁定が外した単位（申し出の単位と、同じ項目に載る単位の全部。`conflict.ruled_units`）。
- 約束の欄・手段の欄: 修正案の項目の欄の 2 つの組。約束の欄は人に約束した事（どの単位を・何を狭め・何を消し・どこを書き・どこを触らず・どの既存テストの期待を変えるか・受け入れのテストが確かめる振る舞い）。手段の欄はどう直し、どう確かめるか（やり方・足す識別子・テストの id・置き場・赤の種類など）。
- 1 回目に受け付けた返答の控え: 1 回目の修正の段の受け付けが、待つ単位が在るので盤面の `p3.fix` に渡さずに置いた返答（`b.work("fix-held-reply.json")`）。

持ち主の手元の資料（要る所はこの文書に書き写した。開かなくても実装できる）:
- `~/.cache/works-dogfood/req-226.json`・`req-226b.json`・`req-226c.json`: 依頼の文。226b の関所の答え「上限で諦めた時は裁定の文を ask_human の行と次の run の依頼に字のまま載せる。REPLAN_HEAD の専用の節と line_edge の専用の文は消してよい」。
- run 226（設計だけ）の独立設計 `.../run-226/.../board/design.json`: この計画の主な拠り所。節を ■1〜■8 で呼ぶ。
- run 226c の独立設計 `.../run-226c/.../board/design.json`（■0〜■7）と最後の関所 `.../run-226c/.../board/r1/final-gate.md`: R2 の 4 点の出どころ。差分 `diff-r1-after-fix.patch` は、やらない事の見本（盤面の節を戻す・写しの `board.py` を `!` 行なしで変える・新しい定数 `REPLAN_LIMIT`・戻る道より先に持ち越しの道を消す）。
- `works/docs/keep-essence.md`: どの形でも残す 11 項目。

---

**Goal:** `fix_plan_item` の裁定が出た時、その項目を次の run に持ち越さず、同じ run の中で修正案の役に戻して項目だけを直させ、事前審査と、1 つの決まりで開く人の関所を通してから、2 回目の修正の段で直す。持ち越しの専用の道（報告の `REPLAN_HEAD` の節・最後の関所の専用の文・結末 `round_limit` の分かれ）を消し、直せなかった単位は既存の ask_human の道に合流させる。

**Architecture:**

- 線の `fixing` と `h-rejudge` の間に 6 節を足す: `h-replan`（境の節）→ `replanning`（`blk-plan` を `replan: "true"` で include）→ `h-regate`（境の節）→ `replan-gate`（approval。最上段）→ `h-refit`（境の節）→ `refitting`（`blk-fix` を `include_id: refitting` で include）。
- 盤面の節は戻さない。待つ単位が在る間、1 回目の受け付けは `p3.fix` を盤面に渡さずに返答を控え、2 回目の受け付けが控えの行と新しい行を合わせて渡す。案を直さずに終わった時は `h-rejudge` が控えをそのまま渡す。
- 直した項目は works 側の控え `plan-fields.json` に重ねる（鍵 `amended`。凍結の印は今の `SAVED_OP` のまま）。承認済みの項目を読む口（`planmarks.approved_items`・新しい `planmarks.plan_items`）が重ねた形を返し、brief は凍結の印が新しくなった時だけ切り直す。
- 案の直しの段の全部（束ねる・指示書・受け付け・関所の決まり・答え・締め）は新しい core の模块 `works/.shared/core/replan.py`（層 L3）が持つ。`blk-plan` は役の節をそのまま使い、入力 `replan` が真なら snap・prep・accept・collect を `replan` の口へ回す（独立設計の役を `design` の口へ回すのと同じ形）。
- 待つ単位の状態は `conflicts.json` の裁定の行の欄 `replan`（`waiting`・`amended`・`gave_up`）。`amended` の行だけが直す義務を外さない。`gave_up` の行は ask_human の行と同じ道（最後の関所・報告・次の run の依頼）に載り、裁定の文は字のまま。

**Tech Stack:** Python 3.12 以降の標準ライブラリ（`json`・`hashlib`・`pathlib`）、works の盤面の層（`entry`・`board`・`conflict`・`planmarks`・`rolekit`・`recount`）、Archon の YAML（loop_group・include・approval）、unittest（`works/tests`）。

**Spec:**
- 依頼の文 `req-226.json`・`req-226b.json`（関所の答え）・`req-226c.json`（申し出の unit_key は一字も変えずに写す）。
- run 226 の独立設計 ■1〜■7（道 (a)・消す物と残す物・日々の動線）。
- run 226c の R2 が名指した 4 点（下の「R2 の 4 点の受け持ち」）と、226c の独立設計 ■2・■4（渡す物を絞る・約束の欄と手段の欄の 1 つの決まり）。
- R3: 写しの手直しは `!` 行だけ。

## 設計からの外れ（実物と照らした結果。どれも 1 つの軸「目的と keep-essence を保って全体がより簡潔か」で選んだ）

- **外れ D1（戻る回数）: 案の段に戻るのは 1 run に 1 回。数える定数を持たない。** 226c の R2 は「共通の GIVE_UP_AFTER で、事前審査の拒否による戻りも数える」と求め、226 の ■4 は「1 単位につき 1 run に 1 回・run 全体にも小さな上限」と言う。実物では、戻る鎖（修正案の役 → 事前審査の役 → 人の関所 → 修正の段）を run の中で繰り返せない。
  - 線は巡回の無い DAG で、節を回し直す道が無い（226c の R1 が指摘）。
  - 人の関所は loop_group の本体に置けない（Archon #3532。`works/tests/test_yaml_rules.py` が縛る）。
  - 1 つの輪には AI の節を 1 つだけ置く（裁定 TA13。修正案の役と事前審査の役を同じ輪に置くと、事前審査が修正案の会話を継ぐ恐れもある）。
  - include を輪の中に置く形は works のどこにも無く、確かめられていない。
  - だから鎖は線の上に 1 本だけ足す。数えても 1 にしかならないので、数える物も定数も作らない（新しい定数を足さないことは R2 の言うとおり）。各役の出し直しは今の輪（`max_iterations: 3` = `rolekit.GIVE_UP_AFTER`）がそのまま縛る。事前審査が人に聞く種類の穴を挙げた直しは、今の鎖と同じく人の関所に出る。人が退ければ、その項目の単位は諦めて、ask_human の道に載る。2 回目の修正の段で同じ単位が再び `fix_plan_item` と裁かれた時も同じく諦める。諦める道は 1 本で、決めるのは「待つ単位が残ったまま鎖を抜けたか」だけ。
- **外れ D2（事前審査の「拒否」）: 事前審査は案を修正案の役へ差し戻さない。** 226c ■3 は「事前審査が拒んだら修正案の役へ戻す」と言う。D1 と同じ理由で戻せない。今の鎖でも事前審査は差し戻さず、後退（regression）と方針の穴（policy）を人の関所に出し、ほかの穴は修正役が `plan_faces` で答える。案の直しでも同じに扱う。人に聞く種類の穴は関所の決まりの 2 つ目の条件になり、ほかの穴は 2 回目の修正役の材料に載る。
- **外れ D3（盤面の節を戻さない）: `Board.rewind` も写しの `board.py` も使わず、変えもしない。** 226c は `p2.fix_plan`・`p2.plan_review`・`p2.human_gate`・`p3.fix` を戻し、機械の節を戻せない守り（`die`）を写しから `!` 行なしで消した（R3）。しかも戻しが `p3.fix` の出力の指しを外し、1 回目に直した単位の記録が報告から消えた（R1）。この計画は `p3.fix` を待つ単位が片付くまで渡さない。盤面の 1 周に 1 度の約束をそのまま使う。
- **外れ D4（brief の名）: 直した項目の brief は `brief-<n>.md` の名のまま切り直す。** 226 ■7 の `brief-1.amend-1.md` の名は使わない。前の項目と直した項目の両方は、案の直しの記録 `replan.json` に残る。読む側（修正役・TDD の役・差分の審査）の分かれを作らないため。

## R2 の 4 点の受け持ち

1. 承認済みの案を変えた時に、人に聞かずに通す範囲を 1 つの決まりで決める（約束の欄と手段の欄。欄を比べて決めるのはコード）→ Task 1（欄の表と `contract_diff`）・Task 7（`replan.gate`）。
2. 修正案の役に渡すのは、誤りと裁かれた項目・申し出の文・裁定の文だけ。返答はその項目の id に限り、差し替えるのはコード → Task 6（`replan.prep`・`replan.accept_reply`）・Task 1（`planmarks.amend`）。
3. 案の直しの後に、待つ単位を直す義務へ戻す継ぎ目と、待つ単位を残したまま run を終えない不変条件 → Task 3（状態と `held_by_rulings`）・Task 4（`replan.settle` の不変条件）・Task 7（`replan.answer`）・Task 8（2 回目の修正の段）。
4. 戻りを共通の GIVE_UP_AFTER で数え、事前審査の拒否も数える。新しい定数は足さない → 外れ D1・D2 のとおり。新しい定数を足さないことは Task 4〜7 の試験が縛る（`replan` に回数の定数が無い）。

## Global Constraints

- 期限・タイムアウトを新しく足さない。止めるのは条件だけ。新しい script の節の `timeout: 1728000000` と、AI の節の `idle_timeout: 1728000000` は YAML の決まり（`test_yaml_rules.py`）が求める決まった値で、新しい期限ではない。approval・include・loop_group の節は期限を持たない。
- 写し（`works/.shared/core/graphloops/`・`gl-prompts/`）と本流 `graphloops/` は変えない。どうしても要れば `COPIED_FROM` に `!` 行（path・old・new・why）を足し、`python3 works/dev/core-sync.py --check` を緑にする。この計画の Task はどれも写しを変えない。
- keep-essence の 11 項目を保つ（1〜3 は 2 回目の修正の段でも同じ TDD の輪と凍結。4 は修正の単位の 3 回の諦めのまま。8 の裁定役の語 `fix_plan_item` は残し、意味だけを「同じ run で案に戻す」に変える。9 の独立設計は案の直しの事前審査に貼り、R1〜R4 は修正の後の差分にそのまま回る。10 の最後の関所は、諦めた単位を ask_human の行として並べる。11 は案の直しの記録の行を最後の関所と報告に載せる）。
- 事前審査を通り、関所の決まりで人が承認した（か、聞く要の無い）項目だけで直す。2 回目の修正の段の要求の正本は、直した項目から切り直した brief。
- 盤面の 1 周に 1 度の節の約束を崩さない（`Board.rewind` を呼ばない）。
- 層（`works/tests/test_layers.py` の表 `MOD`）: `replan` は L3（`"replan": (3, None)`）。L3 どうしの import で輪を作らない（`conflict` と `planmarks` は `replan` を import しない。`replan` が両方を import する）。`planbrief`（blk-fix の L4）は `replan` から呼ばない（brief の切り直しは blk-fix の `planbrief.cut` が自分で気づく。Task 2）。
- 新しい試験の模块は `works/tests/tiers.py` の FAST か HEAVY に書く（`test_replan` は HEAVY: 種の git と盤面を作る）。
- 受け入れのテストの id はクラスの中（`<パス>::<クラス>::<名>`。227 の決まり）。この計画の試験もどれも `unittest.TestCase` のクラスの中に置く。
- 新しい模块は `from __future__ import annotations` で始め、注記・docstring・指示書の文・拒否の文は日本語。
- Python 3.12 が下限。
- 役の返答の型・ブロックの入力・script の `with` を変えた Task は、同じ Task の中で表の試験（`test_blk_plan`・`test_blk_fix` の YAML の突き合わせ・`test_script_contract`・`test_line.LineShapeCase`・`tests/linekit.py` の `LINE_ORDER`）を合わせる。
- 焦点の試験: `cd works/tests && PYTHONDONTWRITEBYTECODE=1 python3 -m unittest <module>[.<Class>]`。組の仕上げ（Task 4・9・10 の終わり）: `WORKS_TESTS=fast nice -n 19 sh works/tests/run.sh` と `sh ~/.cache/works-dogfood/rootfences.sh`（根の `tests/run.sh` の速い柵だけを当てる殻）。
- CHANGELOG は `works/CHANGELOG.md` の `[Unreleased]` だけに足す（Task 10）。版は上げない。
- commit のメッセージは日本語で、末尾に `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`。push はしない。

## Review Focus

1. 2 回目の修正役が、1 回目の TDD の輪が凍らせた既存のテストのファイル（`tdd-1/state.json` の frozen）を書き換える → 拒む（凍結は run の全部の輪で効く）。ただし直した項目の単位の古い受け入れのテストは、承認された直しが新しい約束なので外す。（Task 8 の `test_second_pass_cannot_touch_first_loop_frozen_tests`・`test_amended_units_old_tests_are_not_frozen`）
2. Archon の再開で境の節（`h-refit`・`h-rejudge`）が 2 度走る → 項目を 2 度差し替えない・`p3.fix` を 2 度渡さない・`process.human_items` に行を積み増さない。（Task 7 の `test_answer_twice_is_idempotent`、Task 5 の `test_settle_twice_hands_once`）
3. 修正案の役が、渡していない項目を返す・項目を足す/落とす・unit_keys を一字でも変える（番号で書く・別の key）→ 誤りを全部並べて 1 回で拒む。差し替えるのは渡した項目だけ。（Task 6 の `test_reply_limited_to_handed_items`）
4. 待つ単位を残したまま鎖を抜ける（修正案の役が 3 回とも拒まれた・事前審査の役が 3 回とも拒まれた・関所が開かなかった・人が退けた・2 回目の修正の段で再び `fix_plan_item`）→ どれも諦めて ask_human の行に載り、裁定の文は字のまま最後の関所と次の run の依頼に届く。`h-rejudge` の後に `waiting` の行が残れば BoardGap で落ちる。（Task 4 の `test_settle_closes_waiting_rows`・`test_unsettled_is_board_gap`、Task 7 の `test_gave_up_paths_reach_ask_human_verbatim`）
5. この版の前に作った盤面を再開する（裁定の行に欄 `replan` が無い・`plan-fields.json` に鍵 `amended` が無い）→ 欄の無い `fix_plan_item` の行は `waiting` と読み、鍵の無い控えは直しの無い案と読む。落ちない。（Task 1 の `test_old_fields_file_has_no_amendments`、Task 3 の `test_row_without_state_reads_as_waiting`）

---

### Task 1: 約束の欄と手段の欄・承認済みの項目の差し替え（`planmarks`）

**Files:**
- Modify: `works/.shared/core/planmarks.py`（表 2 つと関数 4 つ。`save` に keyword 1 つ。`approved_items` を `plan_items` 経由に）
- Test: `works/tests/test_plan_fields.py`（FAST のまま。新しい class `TestContractFields`・`TestAmend`）

**Interfaces:**
- Consumes: 今の `planmarks.save`・`read`・`frozen`・`_saved_mark`・`approved_items`・`KEYS`・`FieldsBroken`
- Produces:
  - `CONTRACT_KEYS = ("unit_keys", "narrows", "removes", "allowed_paths", "out_of_scope", "rewrite_tests")`
  - `CONTRACT_TEST_KEYS = ("behavior",)`（`tests[]` の行のうち約束の欄）
  - `MEANS_KEYS = ("approach", "adds", "shrink_first", "route", "route_why", "tests", "refactor")`（`tests` は `CONTRACT_TEST_KEYS` の外の欄だけが手段）
  - `AMENDED_KEY = "amended"`（`plan-fields.json` の鍵。`{"<項目の番号>": {核の欄}}`。核の欄＝項目のうち `KEYS` の外）
  - `AMENDED_PLAN = "plan-amended.json"`（`r<N>/` の置き場。`{"plan": plan_items(b)}`。2 回目の修正の段の `plan_file`）
  - `contract_diff(old: dict, new: dict) -> list[str]` — 約束の欄のうち違う物の名を `CONTRACT_KEYS` の順に返し、最後に `tests[].behavior` の並び（並べ替えた物）が違えば `"tests.behavior"`。比べは `json.dumps(…, sort_keys=True, ensure_ascii=False)` の字。`unit_keys` は並べ替えて比べる。欄が無いのと空の並びは同じと読む。
  - `save(board, rnd: int, fields: list, amended: dict | None = None) -> None` — `amended` が在れば鍵 `AMENDED_KEY` に置く（無ければ書かない。今の控えとバイトが同じ）。印は今どおり `SAVED_OP`。
  - `amended(b) -> dict[int, dict]` — 今の周の控えの `AMENDED_KEY`（番号を int に）。印と食い違えば `frozen` と同じ `FieldsBroken`。控えに鍵が無ければ `{}`。
  - `plan_items(b) -> list | None` — 盤面の今の周の `p2.fix_plan` の `plan` に、`amended(b)` の核の欄を番号ごとに重ねた並び（無ければ None）。
  - `approved_items(b)` — `plan_items(b)` と `frozen(b)` を合わせる（形は今と同じ `{"item", **核, **KEYS の欄}`）。
  - `amend(b, items: dict[int, dict]) -> pathlib.Path` — `items` は `{番号: 直した項目（核の欄と KEYS の欄の全部）}`。今の控え（`frozen(b)`。食い違えば `FieldsBroken`）の `fields[n-1]` を直した項目の `KEYS` の欄に替え、核の欄を `AMENDED_KEY[n]` に置いて `save` し直し、`r<round>/plan-amended.json` を書いてそのパスを返す。知らない番号・unit_keys が元と違う項目は `ValueError`（受け付けが先に拒む物。ここに届けば配線の誤り）。

- [ ] **Step 1: 落ちる試験を書く**（helper `item()` は `test_blk_fix.PLAN_FIELDS[0]` に核の欄（unit_keys・approach・adds・removes・shrink_first・narrows）を足した 1 項目、`REWRITE_ROW` は `rewrite_tests` の正しい 1 行）

```python
class TestContractFields(PlanFieldsCase):
    def test_keys_cover_item_schema(self):
        it = accept.role_schema("p2.fix_plan")["properties"]["plan"]["items"]["properties"]
        self.assertEqual(set(planmarks.CONTRACT_KEYS) | set(planmarks.MEANS_KEYS), set(it))
        self.assertFalse(set(planmarks.CONTRACT_KEYS) & set(planmarks.MEANS_KEYS))

    def test_means_only_change_is_empty(self):
        old = item()                                   # 既存の PLAN_FIELDS[0] と核の欄を合わせた 1 項目（試験の helper）
        new = copy.deepcopy(old)
        new["tests"][0]["red_kind"] = "exception"      # 224b の型
        new["tests"][0]["id"] = "test_stats.py::TestStats::test_mean_of_two_values"   # 225 の型
        new["approach"] = new["approach"] + "（直した）"
        self.assertEqual(planmarks.contract_diff(old, new), [])

    def test_contract_change_is_named(self):
        old = item()
        wider = {**copy.deepcopy(old), "allowed_paths": old["allowed_paths"] + ["lib/**/*.py"]}
        self.assertEqual(planmarks.contract_diff(old, wider), ["allowed_paths"])        # 195b の型
        rw = {**copy.deepcopy(old), "rewrite_tests": [REWRITE_ROW]}
        self.assertEqual(planmarks.contract_diff(old, rw), ["rewrite_tests"])           # 194c の型
        beh = copy.deepcopy(old); beh["tests"][0]["behavior"] = "3 つの値の平均"
        self.assertEqual(planmarks.contract_diff(old, beh), ["tests.behavior"])

class TestAmend(PlanFieldsCase):
    def test_amend_swaps_one_item_and_refreezes(self): ...
        # 2 項目の盤面の偽物（SimpleNamespace(dir, round, output_of_round)）。項目 2 の red_kind と approach を直して amend
        # → approved_items の項目 2 は新しい値・項目 1 は前のまま・frozen は通る・trace の SAVED_OP が 2 行
        # → r1/plan-amended.json の plan[1]["approach"] が新しい値
        # → 控えを手で書き換えると approved_items が FieldsBroken
    def test_amend_refuses_changed_unit_keys(self): ...   # unit_keys を変えた項目は ValueError（"unit_keys" を含む）
    def test_old_fields_file_has_no_amendments(self): ...  # AMENDED_KEY の無い控え → amended(b) == {}・plan_items は盤面のまま
```

- [ ] **Step 2: 落ちることを確かめる**

Run: `cd works/tests && PYTHONDONTWRITEBYTECODE=1 python3 -m unittest test_plan_fields.TestContractFields test_plan_fields.TestAmend`
Expected: FAIL（`AttributeError: module 'planmarks' has no attribute 'CONTRACT_KEYS'`）

- [ ] **Step 3: 表と関数を書く**（`planmarks` は今どおり `entry`・`conflict` を import しない。`amend` は渡された `b` の `dir`・`round`・`output_of_round` だけを読む）

- [ ] **Step 4: 通ることを確かめる**

Run: `cd works/tests && PYTHONDONTWRITEBYTECODE=1 python3 -m unittest test_plan_fields`
Expected: PASS（前からの試験も全部）

- [ ] **Step 5: Commit**

```bash
git add works/.shared/core/planmarks.py works/tests/test_plan_fields.py
git commit -m "feat(works): 修正案の項目の約束の欄と手段の欄の表・欄の比べと、承認済みの項目を凍結し直して差し替える口（226 Task 1）"
```

---

### Task 2: 差し替えの後の brief の切り直し（`planbrief`）

**Files:**
- Modify: `works/blk-fix/lib/planbrief.py`（`_plan` を `planmarks.plan_items` に、`cut` に切り直しの条件）
- Test: `works/tests/test_plan_brief.py`（HEAVY のまま。新しい class `TestRecutAfterAmend`）

**Interfaces:**
- Consumes: Task 1 の `planmarks.plan_items(b)`・`planmarks.amend(b, items)`・`planmarks.SAVED_OP`
- Produces:
  - `RECUT_OP = "brief_recut"`（切り直した印の trace の行 `{round, items: [番号…]}`。直後に今どおりの `CUT_OP` の行も書く）
  - `cut(b)` の決まり（1 つ）: 今の周の trace で、最後の `SAVED_OP` の行が最後の `CUT_OP` の行より後に在れば（承認された直しで欄が凍結し直された）、控えの全項目を今の承認済みの項目から描き直し、文が変わった項目だけファイルを書き、控えと `CUT_OP` の印を置き直して `RECUT_OP` を 1 行。そうでなければ今どおり（書き戻すだけ）。brief や控えを手で書き換えた盤面は今どおり `LedgerBroken`・書き戻し。

- [ ] **Step 1: 落ちる試験を書く**（helper `count_ops(board, op)` は盤面の `trace.jsonl` の、今の周のその op の行の数）

```python
class TestRecutAfterAmend(BriefCase):
    def test_recut_after_amend(self):
        b = self.board_with_plan()                  # 既存の BriefCase の盤面（1 項目）
        first = planbrief.cut(b)
        new = {**planmarks.approved_items(b)[0]}
        new["tests"] = [{**new["tests"][0], "red_kind": "exception", "red_why": "今は ZeroDivisionError が出ない"}]
        planmarks.amend(b, {1: new})
        b = entry.open_board(self.board)
        again = planbrief.cut(b)
        text = pathlib.Path(again[0]["file"]).read_text(encoding="utf-8")
        self.assertIn("exception", text)
        self.assertNotEqual(first[0]["sha256"], again[0]["sha256"])
        self.assertEqual(count_ops(self.board, planbrief.RECUT_OP), 1)

    def test_no_recut_without_amend(self):
        b = self.board_with_plan()
        planbrief.cut(b); planbrief.cut(entry.open_board(self.board))
        self.assertEqual(count_ops(self.board, planbrief.RECUT_OP), 0)
        self.assertEqual(count_ops(self.board, planbrief.CUT_OP), 1)

    def test_tamper_after_recut_is_restored(self): ...   # 切り直した brief-1.md を書き換え → cut が直した文に書き戻す（RESTORED_OP）
```

- [ ] **Step 2: 落ちることを確かめる**

Run: `cd works/tests && PYTHONDONTWRITEBYTECODE=1 python3 -m unittest test_plan_brief.TestRecutAfterAmend`
Expected: FAIL（`exception` が brief に無い・`RECUT_OP` が無い）

- [ ] **Step 3: 切り直しを書く**（trace の行の順は行の並びで決める。時刻で比べない）

- [ ] **Step 4: 通ることを確かめる**

Run: `cd works/tests && PYTHONDONTWRITEBYTECODE=1 python3 -m unittest test_plan_brief`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add works/blk-fix/lib/planbrief.py works/tests/test_plan_brief.py
git commit -m "feat(works): 承認された項目の直しで欄が凍結し直された時だけ brief を切り直す（226 Task 2）"
```

---

### Task 3: 裁定の行の案の直しの状態と、1 回目に受け付けた返答の控え（`conflict`）

**Files:**
- Modify: `works/.shared/core/conflict.py`
- Test: `works/tests/test_conflict_kinds.py`（FAST のまま。新しい class `TestReplanState`・`TestHeldReply`）

**Interfaces:**
- Consumes: 今の `conflict.items`・`ruled_units`・`held_by_rulings`・`asked`・`human_lines`・`fix_duty`・`apply_rulings`・`recount.FIX_NODE`（`"p3.fix"`。`conflict` は `recount` を import しない。節の名は `"p3.fix"` の字で持つ）
- Produces:
  - `REPLAN_STATE = "replan"`（裁定の行の欄）・`WAITING = "waiting"`・`AMENDED = "amended"`・`GAVE_UP = "gave_up"`・`REPLAN_WHY = "replan_why"`・`REPLAN_OP = "replan_state"`（trace の行 `{id, unit_key, state, why}`）
  - `apply_rulings`: 裁定が `REPLAN` の行に `REPLAN_STATE: WAITING` を置く。
  - `replan_state(row) -> str | None` — `REPLAN` の行の状態（欄の無い前の形の行は `WAITING`）。ほかの裁定は None。
  - `waiting(b) -> list` — 状態が `WAITING` の行。
  - `amended_keys(b) -> set` — 状態が `AMENDED` の行の `ruled_units` の全部。
  - `set_replan(b, ids: list[str], state: str, *, why: str = "") -> None` — `WAITING` の行だけを `AMENDED` か `GAVE_UP` に替える（`GAVE_UP` は `why` が空でない）。ほかの移りは BoardGap。同じ状態への移りは何もしない（再開）。
  - `held_by_rulings(b)`: 状態が `AMENDED` の行を外す（それ以外は今どおり）。
  - `asked(b)`: 直す裁定でない裁定（`FIX_DECISIONS` の外）の行のうち、状態が `WAITING`・`AMENDED` でない物（ask_human と、諦めた `fix_plan_item`）。
  - `human_lines(b)`: 行に `REPLAN_WHY` が在れば末尾の括弧に `・案の直し: <why>` を足す。裁定の文は今どおり字のまま。
  - `HELD_REPLY = "fix-held-reply.json"`・`ACCEPTED_WHY = "1 回目の修正の段で受け付けた（控え {path}。この単位の行は機械が足す）"`
  - `held_reply(b) -> tuple[dict | None, pathlib.Path]` — 今の周に `p3.fix` を受けていない時だけ控えを読む（受けた後・控えが無いなら None）。壊れていれば BoardGap。
  - `accepted_units(b) -> set` — `held_reply` の `changes`・`not_done` の `unit_key`。
  - `fix_duty(b)`: 1 つ目（直す義務）から `accepted_units` を引き、2 つ目に `ACCEPTED_WHY` の理由で足す。`owed_units_but_asked`（盤面の検証器の差し替え）は変えない——盤面は全部の単位の行を要る。
  - `with_held(b, reply: dict) -> dict` — 控えが無ければ `reply` のまま。在れば `changes`・`not_done` を「控えの行のうち `reply` に無い単位の行」＋「`reply` の行」にした写し。ほかの欄は `reply` の物。

- [ ] **Step 1: 落ちる試験を書く**（`test_conflict_kinds` の偽の盤面: `SimpleNamespace(work=…, trace=…, round=1, state={"outputs": {}})` と一時の `conflicts.json`。helper `fake_with_rows(rows)` はその盤面に行を置いた物、`row(id, key, decision, *, state=None, text=…, plan_units=())` は裁いた行 1 つ、`mean_row()` は MEAN の changes の 1 行）

```python
class TestReplanState(unittest.TestCase):
    def test_ruling_starts_waiting_and_holds(self):
        b = fake_with_rows([row("c1-1", MEAN, None)])                # 裁いていない申し出の行
        conflict.apply_rulings(b, {"c1-1": {"decision": "fix_plan_item", "text": "x" * 20, "limits": [],
                                            "plan_items": [1], "plan_units": [MEAN, CLAMP]}}, by="t")
        self.assertEqual(conflict.items(b)[0]["replan"], "waiting")
        self.assertEqual([r["id"] for r in conflict.waiting(b)], ["c1-1"])
        self.assertEqual(set(conflict.held_by_rulings(b)), {MEAN, CLAMP})
        self.assertEqual(conflict.asked(b), [])

    def test_amended_rows_return_units_to_duty(self):
        b = fake_with_rows([row("c1-1", MEAN, "fix_plan_item", state="waiting")])
        conflict.set_replan(b, ["c1-1"], conflict.AMENDED)
        self.assertEqual(conflict.held_by_rulings(b), {})
        self.assertEqual(conflict.amended_keys(b), {MEAN})

    def test_gave_up_rows_join_ask_human_verbatim(self):
        text = "受け入れのテストの id を\nクラス付きにする（test_tiers.py:136-143）"
        b = fake_with_rows([row("c1-1", MEAN, "fix_plan_item", state="waiting", text=text)])
        conflict.set_replan(b, ["c1-1"], conflict.GAVE_UP, why="人が関所で直した項目を退けた: 範囲が広い")
        line = conflict.human_lines(b)[0]
        self.assertIn(text, line)                                  # 字のまま（改行も）
        self.assertIn("案の直し: 人が関所で直した項目を退けた: 範囲が広い", line)

    def test_bad_transition_is_board_gap(self): ...            # GAVE_UP → AMENDED・why の無い GAVE_UP は BoardGap
    def test_row_without_state_reads_as_waiting(self): ...     # 欄 replan の無い fix_plan_item の行 → waiting に数える

class TestHeldReply(unittest.TestCase):
    def test_accepted_units_leave_duty_but_not_board_owed(self): ...
        # 控え {changes: [CLAMP の行]} を置いた偽の盤面 → fix_duty の owed に CLAMP が無く、excused[CLAMP] に "1 回目の修正の段で受け付けた"
    def test_with_held_merges_rows_by_unit(self):
        merged = conflict.with_held(b, {"changes": [mean_row()], "not_done": [], "fix_closure": {"status": "clean"}})
        self.assertEqual([c["unit_key"] for c in merged["changes"]], [CLAMP, MEAN])
        self.assertEqual(merged["fix_closure"], {"status": "clean"})
    def test_held_reply_ignored_after_board_took_fix(self): ...  # state.outputs に今の周の p3.fix → held_reply は (None, パス)
```

- [ ] **Step 2: 落ちることを確かめる**

Run: `cd works/tests && PYTHONDONTWRITEBYTECODE=1 python3 -m unittest test_conflict_kinds.TestReplanState test_conflict_kinds.TestHeldReply`
Expected: FAIL（`AttributeError: … 'waiting'`）

- [ ] **Step 3: 状態と控えの口を書く**（どの状態も `set_replan` の 1 か所で移す。`gave_up` を持つ行は誰も作らないので、この Task の後も run の動きは変わらない）

- [ ] **Step 4: 通ることを確かめる**

Run: `cd works/tests && PYTHONDONTWRITEBYTECODE=1 python3 -m unittest test_conflict_kinds test_plan_scope && python3 -m unittest test_blk_fix_conflict.TestFixPlanItem test_blk_fix_conflict.TestFixPlanItemWholeItem`
Expected: PASS（前からの `fix_plan_item` の試験も全部）

- [ ] **Step 5: Commit**

```bash
git add works/.shared/core/conflict.py works/tests/test_conflict_kinds.py
git commit -m "feat(works): fix_plan_item の裁定の行に案の直しの状態（待つ・直した・諦めた）と、1 回目に受け付けた返答の控えの口を持たせる（226 Task 3）"
```

---

### Task 4: 諦めの道を 1 本にする（`replan.close`・`settle` と、持ち越しの道を消す）

この Task の後、`fix_plan_item` の単位は次の run へ持ち越されない。`h-rejudge` で諦めた単位として ask_human の道に載る（関所の答えの「上限で諦めた時」と同じ姿）。同じ run で直す道は Task 6〜9 で足す。

**Files:**
- Create: `works/.shared/core/replan.py`（この Task では `STOP_BY`・`CLOSE_WHY`・`UNSETTLED`・`close`・`settle` だけ）
- Modify: `works/darkfactory/lib/line_edge.py`（`edge` の at `rejudge` の頭で `replan.settle`。`_replan_text` と `final_edge` の `replanned` を消す）
- Modify: `works/.shared/core/report.py`（`REPLAN_HEAD`・`replanned_lines`・`_replanned`・`_replanned_units`・`_plan_nums`・`_from_unit`・`decide_outcome` の `round_limit` の分かれ・`next_request` の fix_plan_item の行・冒頭 1 の節を消す。ask_human の行は `ruled_units` の全部の単位に、裁定の文を字のまま載せる）
- Modify: `works/tests/test_layers.py`（`MOD` に `"replan": (3, None)`）
- Create: `works/tests/test_replan.py`（HEAVY。`works/tests/tiers.py` の HEAVY に `"test_replan"` を足す）
- Modify: `works/tests/test_blk_fix_conflict.py`（`TestFixPlanItemReport`・`TestFixPlanItemWholeItem` の持ち越しを縛る試験を、諦めの道を縛る試験に書き換える）・`works/tests/test_report_head.py`（`REPLAN_HEAD` を読む試験があれば同じく）

**Interfaces:**
- Consumes: Task 3 の `conflict.waiting`・`set_replan`・`GAVE_UP`・`asked`・`human_lines`・`ruled_units`
- Produces（`replan`。L3。`entry`・`conflict`・`planmarks`・`recount`・`rolekit`・`board` を import してよい）:
  - `STOP_BY = "works:replan"`
  - `CLOSE_WHY = "同じ run の中で案の直しを終えられなかった（案の段に戻るのは 1 run に 1 回）"`
  - `UNSETTLED = "案の直しを待つ単位を残したまま修正の段を抜けようとした: {ids}"`
  - `close(b, why: str) -> list[str]` — `waiting(b)` の行を全部 `GAVE_UP`（`why`）にし、id を返す。
  - `settle(board_dir, repo) -> dict` — `{"closed": [id…], "handed": bool}`。順: 1. 盤面を `allow_halted` で開き `close(b, CLOSE_WHY)`（止まった盤面でも締める）。2.（Task 5 で足す: 控えの渡し）。3. `waiting` の行が残れば `BoardGap(UNSETTLED.format(ids=…))`。
  - `line_edge.edge`: at が `rejudge` なら、止まっているかを見る前に `replan.settle(board_dir, repo)` を呼び、盤面を開き直す。
  - `report.next_request`: `asked` の行ごとに、`ruled_units(r)` の単位ごとに `{"where": <単位>, "text": "<単位>（食い違いの申し出を人に回した——直さずに残した。裁定の文: <字のまま>。名指し <…>[。案の直し: <why>]）"}`。`_one_line` を通さない。
  - `report.decide_outcome`: `_replanned` の分かれを消す（諦めた単位は `_asked` で `needs_human`）。

- [ ] **Step 1: 落ちる試験を書く**

```python
# test_replan.py
from test_blk_fix_conflict import ReplanCase, only_clamp_reply, PLAN_TEXT, MEAN, CLAMP

class TestSettle(ReplanCase):
    def test_settle_closes_waiting_rows(self):
        self.replanned()
        self.assertTrue(self.accept_script(only_clamp_reply(), pass_="ruled")["ok"])
        got = replan.settle(self.board, self.repo)
        self.assertEqual(len(got["closed"]), 1)
        b = entry.open_board(self.board, allow_halted=True)
        self.assertEqual(conflict.waiting(b), [])
        self.assertIn(PLAN_TEXT, conflict.human_lines(b)[0])

    def test_unsettled_is_board_gap(self):
        self.replanned()
        with mock.patch.object(replan, "close", return_value=[]):
            with self.assertRaises(board.BoardGap) as cm:
                replan.settle(self.board, self.repo)
        self.assertIn("案の直しを待つ単位を残したまま", str(cm.exception))

    def test_no_new_count_constant(self):
        self.assertFalse([n for n in dir(replan) if "LIMIT" in n or n == "GIVE_UP_AFTER"])

# test_blk_fix_conflict.py（TestFixPlanItemReport を書き換える）
    def test_gave_up_unit_goes_to_gate_and_next_request_verbatim(self):
        self.replanned()
        self.assertTrue(self.accept_script(self.clamp_reply(), pass_="ruled")["ok"])
        replan.settle(self.board, self.repo)
        b = entry.open_board(self.board)
        got = line_edge.final_edge(b, self.repo, run_id="run-12", mode="when_needed", tests={"ok": True, "green": True})
        self.assertTrue(got["ask"])                                       # ask_human と同じく関所を開ける
        items = report.next_request(entry.open_board(self.board))
        self.assertTrue(any(i["where"] == MEAN and PLAN_TEXT in i["text"] for i in items), items)
        self.assertFalse(hasattr(report, "REPLAN_HEAD"))
    def test_outcome_is_needs_human_not_round_limit(self): ...
    def test_whole_item_units_each_get_a_row(self): ...                   # SHARED_ITEM: MEAN と CLAMP の両方の行（ruled_units）
```

- [ ] **Step 2: 落ちることを確かめる**

Run: `cd works/tests && PYTHONDONTWRITEBYTECODE=1 python3 -m unittest test_replan test_blk_fix_conflict.TestFixPlanItemReport`
Expected: FAIL（`ModuleNotFoundError: No module named 'replan'`）

- [ ] **Step 3: `replan.py` を書き、境の節と報告を繋ぎ替える**（報告の冒頭 1 と最後の関所の文の `replanned` の節は消すだけで、代わりの節は Task 7 の `replan.lines`）

- [ ] **Step 4: 通ることを確かめる**

Run: `cd works/tests && PYTHONDONTWRITEBYTECODE=1 python3 -m unittest test_replan test_blk_fix_conflict test_report_head test_layers` と `WORKS_TESTS=fast nice -n 19 sh works/tests/run.sh` と `sh ~/.cache/works-dogfood/rootfences.sh`
Expected: PASS・失敗 0

- [ ] **Step 5: Commit**

```bash
git add works/.shared/core/replan.py works/.shared/core/report.py works/darkfactory/lib/line_edge.py works/tests/test_replan.py works/tests/tiers.py works/tests/test_layers.py works/tests/test_blk_fix_conflict.py works/tests/test_report_head.py
git commit -m "feat(works): fix_plan_item の単位を次の run へ持ち越さず、h-rejudge で締めて ask_human の道に合流させる（裁定の文は字のまま。226 Task 4）"
```

---

### Task 5: 待つ単位が在る間は `p3.fix` を渡さずに控える

**Files:**
- Modify: `works/blk-fix/scripts/accept.py`（手順 3 の前の分かれ 1 つ）
- Modify: `works/.shared/core/recount.py`（`fix_reply` を足し、`collect` が使う）
- Modify: `works/.shared/core/replan.py`（`settle` の手順 2）
- Test: `works/tests/test_replan.py`（class `TestHold`）

**Interfaces:**
- Consumes: Task 3 の `conflict.waiting`・`HELD_REPLY`・`held_reply`、Task 4 の `replan.settle`
- Produces:
  - 受け付け（`accept.py`）の決まり: 手順 2（`unitrows.take`）の後、`recount.accept_fix` の前に、`conflict.waiting(b)` が空でなければ、盤面に渡す形の返答を `b.work(conflict.HELD_REPLY)` に書き（一時のファイルから `os.replace`）、`{"ok": true, "done": true, "parked": true, "reason": "", "reason_file": "", "changes": [V1 の行]}` を返す。trace に `HELD_OP = "fix_held"` を 1 行（`accept.py` の定数）。
  - `recount.fix_reply(b) -> tuple[dict, pathlib.Path]` — 今の周の盤面の `p3.fix` か、無ければ `conflict.held_reply` の控え。どちらも無ければ `Unreadable`。`collect` はこれを読む（`fix_file` は読んだ方のパス）。
  - `replan.settle` の手順 2: 盤面が止まっておらず、今の周の `p3.fix` を受けておらず、控えが在れば、`recount.accept_fix(控え, board_dir, "", repo)` で渡す。盤面が受けなければ `b.stop("1 回目に受け付けた修正の返答を盤面が受けない: <理由>", by=STOP_BY)`。返りの `handed` は渡した時だけ真。

- [ ] **Step 1: 落ちる試験を書く**

```python
class TestHold(ReplanCase):
    def test_waiting_unit_holds_fix_reply(self):
        self.replanned()
        r = self.accept_script(only_clamp_reply(), pass_="ruled")
        self.assertEqual((r["ok"], r.get("parked")), (True, True))
        b = entry.open_board(self.board)
        self.assertNotIn("p3.fix", b.state["outputs"])                    # 盤面に渡していない
        self.assertTrue(b.work(conflict.HELD_REPLY).is_file())
        self.assertEqual(recount.fix_reply(b)[1], b.work(conflict.HELD_REPLY))

    def test_settle_hands_held_reply(self):
        self.replanned(); self.accept_script(only_clamp_reply(), pass_="ruled")
        got = replan.settle(self.board, self.repo)
        self.assertTrue(got["handed"])
        b = entry.open_board(self.board)
        self.assertEqual([c["unit_key"] for c in recount._fix_output(b)[0]["changes"]], [CLAMP])

    def test_settle_twice_hands_once(self): ...      # 2 度目の settle は handed False・trace の accept の行は 1 つ
    def test_no_waiting_hands_as_before(self): ...   # ask_human だけの盤面では今どおり受け付けが p3.fix を渡す（parked 無し）
```

- [ ] **Step 2: 落ちることを確かめる**

Run: `cd works/tests && PYTHONDONTWRITEBYTECODE=1 python3 -m unittest test_replan.TestHold`
Expected: FAIL（`parked` が無い・`fix_reply` が無い）

- [ ] **Step 3: 控えと渡しを書く**

- [ ] **Step 4: 通ることを確かめる**

Run: `cd works/tests && PYTHONDONTWRITEBYTECODE=1 python3 -m unittest test_replan test_blk_fix_conflict test_blk_fix`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add works/blk-fix/scripts/accept.py works/.shared/core/recount.py works/.shared/core/replan.py works/tests/test_replan.py
git commit -m "feat(works): 案の直しを待つ単位が在る間は修正の返答を盤面に渡さずに控え、h-rejudge で渡す（226 Task 5）"
```

---

### Task 6: 案の直しの役（`blk-plan` の replan の口）

**Files:**
- Modify: `works/.shared/core/replan.py`（束ね・指示書・受け付け・出口）
- Modify: `works/blk-plan/blk-plan.yaml`（入力 `replan`。`plan-snap`・`plan-prep`・`plan-accept`・`plan-review-snap`・`plan-review-prep`・`plan-review-accept`・`collect` の `with` に `replan: $INPUTS.replan`）
- Modify: `works/blk-plan/lib/planblk.py`（`snap`・`prep`・`main_accept`・`collect` の頭で `replan` の口へ回す 1 分岐ずつ）・`works/blk-plan/scripts/{snap,prep,accept,collect}.py`（`INPUTS` に `INPUTS_REPLAN`。空は今どおり）
- Test: `works/tests/test_replan.py`（class `TestReplanRoles`）・`works/tests/test_blk_plan.py`（YAML と `INPUTS` の突き合わせ）

**Interfaces:**
- Consumes: Task 1 の `planmarks.approved_items`・`gaps`・`HEAD`・`REVIEW_ASK`、Task 3 の `conflict.waiting`、`planblk.head`・`design_section`・`output_format`、`rolekit.with_done`・`parse_reply`・`given_up_reason`、`accept.role_schema`、`gatemarks.narrow_gaps`、`entry.snapshot`
- Produces（`replan`）:
  - `TRIP_FILE = "replan.json"`（`b.work`。`{"round": n, "items": [行]}`。行は `{"item", "units", "rows", "old", "brief", "new", "review", "contract_changed", "human_faces", "ask", "answer", "result", "why"}`。まだ無い値は null か空）
  - `PLAN_NODE = "replan.fix_plan"`・`REVIEW_NODE = "replan.plan_review"`（盤面に無い節の名。`rolekit.with_done` の控えと指示書の名 `prompt-replan.fix_plan.md`・`prompt-replan.plan_review.md`）
  - `ROLES = {"plan": PLAN_NODE, "plan-review": REVIEW_NODE}`
  - `material(b) -> dict` — `{"go": bool, "items": [番号…]}`。`waiting(b)` の行を、裁定の欄 `plan_items` の番号ごとに束ねて `TRIP_FILE` を書く（項目 1 つに行 1 つ。同じ項目の単位は `ruled_units` の和）。`old` は `planmarks.approved_items(b)[n-1]`。`TRIP_FILE` が今の周に在れば書き直さない（再開）。今の周の `p3.fix` を受けている・盤面が止まっている・待つ行が無いなら go False。
  - `snap(board_dir, role, repo) -> dict` — `{"ok", "go", "snapshot_file"}`。`plan`: `new` の無い項目が在れば go。`plan-review`: `new` が在り `review` の無い項目が在れば go。
  - `prep(board_dir, role, repo, excluded_file="") -> dict` — `{"prompt_file", "attempt", "out_path", "node", "already"}`（`planblk.prep` と同じ鍵）。指示書は次だけを、この順で並べる。
    1. `planblk.head(role, …)`
    2. `plan` なら `REPLAN_ASK` と `planmarks.HEAD`、`plan-review` なら `planblk.design_section(b)` と `REVIEW_ASK_REPLAN` と `planmarks.REVIEW_ASK`
    3. 項目ごとの節: 番号・unit_keys（字のまま）・前の項目の JSON・brief のパス・申し出の行（`between`・`why_both_cannot_hold`・`kind`・`which_is_right`）・裁定の文（字のまま）・`plan-review` なら直した項目の JSON
    
    ほかの項目・判定の全文・差分・前の会話は貼らない。拒否の後は `rolekit.compose` の 1 行目で前の理由のファイルを名指す。
  - `REPLAN_ASK`（字のまま）: 「承認済みの修正案の項目のうち、下に貼った項目だけを直せ。修正の段で修正役がこの項目の誤りを申し出て、裁定役が fix_plan_item（案の項目そのものの誤り）と裁いた。申し出の文と裁定の文を読み、裁定の文が名指した所を直した項目を返せ。plan は下に貼った項目と同じ数・同じ順で、各項目の unit_keys は貼った文字列を一字も変えずに写せ（番号で書かない）。ほかの項目は返すな。直した項目は事前審査に掛かり、約束の欄（unit_keys・narrows・removes・allowed_paths・out_of_scope・rewrite_tests・tests の behavior）を変えた時は人の関所に出る。」
  - `REVIEW_ASK_REPLAN`（字のまま）: 「下は承認済みの修正案の項目の前の形と、修正の段の申し出と裁定を受けて修正案の役が直した形。直した形が裁定の文の指摘を直したか、新しい後退（regression）や方針とのぶつかり（policy）を作らないかを見よ。前の形に在った穴を挙げ直さない。穴は faces に挙げよ。」
  - `accept_reply(board_dir, role, raw, repo) -> dict` — `{"ok", "done", "give_up", "reason", "node"}`（`design.accept_reply` と同じ形。`rolekit.with_done(…, give_up_after=rolekit.GIVE_UP_AFTER)`）。
    - `plan` の受け付け: 次の誤りを全部並べて 1 回で拒む（頭 `REPLAN_REJECT = "直した項目の返答に誤りが在る（下の行を全部直して出し直せ）:"`）。誤りが無ければ、項目ごとに `new` を `TRIP_FILE` に置く。
      - 数が違う: `plan[] は {k} 項目（貼った項目の数）`
      - unit_keys が違う: `plan[{i}].unit_keys が貼った {old} と違う（一字も変えずに写す）`
      - `planmarks.gaps` の行
      - `gatemarks.narrow_gaps` の行
      - 型（`accept.role_schema("p2.fix_plan")`）の外れ
    - `plan-review` の受け付け: 型（`accept.role_schema("p2.plan_review")`）を当て、項目ごとに `review` を置く。
    - どちらも、役を起こす前の作業ツリーの写しと比べ、変わっていれば拒む（`planblk` と同じ読むだけの役の決まり）。
  - `collect(board_dir) -> dict` — `blk-plan` の出口と同じ鍵 `{"ok": true, "plan_file": "", "review_file": "", "asks_human": false, "gate_kinds": [], "reads_file": <reads の索引か "">, "gave_up": false, "reason_file": ""}`（役の諦めは盤面を止めず、Task 7 の `gate` が項目ごとに読む）。
  - `planblk`: `replan` の入力が空でなく `"null"` でもなければ、`snap`・`prep`・`main_accept`・`collect` を `replan` の同名の口へ回す。独立設計の輪は今どおり `design.due` で飛ぶ。

- [ ] **Step 1: 落ちる試験を書く**

試験の helper（`test_replan.py` に置き、Task 7〜9 も使う）:
- `fixed_item()`: 前の項目 1 の写しで、手段の欄だけを直した物。`red_kind_fixed()` は受け入れのテストの `red_kind` を `"exception"` に、`red_why` を今のコードで赤になる理由に直した物（224b の型）。
- `wider_paths()`: `allowed_paths` に 1 行を足した物（約束の欄が変わる。195b の型）。`clamp_item()` は項目 2 の写し。
- `no_faces()`: 事前審査の空の返答（`faces: []`・`shrink: []`・型の残りの欄）。`only_mean_reply()` は `only_clamp_reply` の MEAN 版。
- `TripCase(ReplanCase)`: setUp は「`replanned()` → 1 回目の受け付け → `replan.material`」まで済ませた盤面。`self.trip(new=, review=)` は 2 つの役の `prep`・`accept_reply` を通す。`self.approve(new)` はそれに `gate` と `answer(b, None)` を足す。`self.play_role(role, reply)` は 1 つの役の `prep` と `accept_reply`。

```python
class TestReplanRoles(ReplanCase):
    def setUp(self):
        super().setUp()
        self.replanned(); self.accept_script(only_clamp_reply(), pass_="ruled")
        self.b = entry.open_board(self.board)

    def test_material_groups_by_item(self):
        got = replan.material(self.b)
        self.assertEqual(got, {"go": True, "items": [1]})
        trip = json.loads(self.b.work(replan.TRIP_FILE).read_text(encoding="utf-8"))
        self.assertEqual(trip["items"][0]["units"], [MEAN])

    def test_prompt_has_only_the_item_and_texts(self):
        replan.material(self.b)
        p = pathlib.Path(replan.prep(self.board, "plan", self.repo)["prompt_file"]).read_text(encoding="utf-8")
        self.assertIn(PLAN_TEXT, p)                                  # 裁定の文（字のまま）
        self.assertIn(MEAN, p)
        self.assertNotIn(CLAMP, p)                                    # ほかの項目の単位を貼らない
        self.assertIn("一字も変えずに写せ", p)

    def test_reply_limited_to_handed_items(self):
        replan.material(self.b); replan.prep(self.board, "plan", self.repo)
        two = {"plan": [fixed_item(), clamp_item()]}                 # 項目を足した返答
        got = replan.accept_reply(self.board, "plan", json.dumps(two), self.repo)
        self.assertFalse(got["ok"]); self.assertIn("plan[] は 1 項目", got["reason"])
        renamed = {"plan": [{**fixed_item(), "unit_keys": [1]}]}    # 番号で書いた
        got = replan.accept_reply(self.board, "plan", json.dumps(renamed), self.repo)
        self.assertIn("一字も変えずに写す", got["reason"])

    def test_good_reply_is_stored_not_swapped(self): ...
        # 正しい返答 → TRIP_FILE の new に入り、planmarks.approved_items はまだ前の項目（差し替えは Task 7 の承認の後）
    def test_third_rejection_gives_up(self): ...       # 3 回拒むと done・give_up が真（GIVE_UP_AFTER の輪のまま）
    def test_review_role_sees_design_and_both_forms(self): ...
```

- [ ] **Step 2: 落ちることを確かめる**

Run: `cd works/tests && PYTHONDONTWRITEBYTECODE=1 python3 -m unittest test_replan.TestReplanRoles`
Expected: FAIL（`AttributeError: module 'replan' has no attribute 'material'`）

- [ ] **Step 3: 口を書き、`blk-plan` を配線する**（`planning` の include は `replan` を渡さないので今どおり）

- [ ] **Step 4: 通ることを確かめる**

Run: `cd works/tests && PYTHONDONTWRITEBYTECODE=1 python3 -m unittest test_replan test_blk_plan test_yaml_rules test_script_contract`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add works/.shared/core/replan.py works/blk-plan works/tests/test_replan.py works/tests/test_blk_plan.py
git commit -m "feat(works): 案の直しの役に誤りと裁かれた項目・申し出・裁定の文だけを渡し、返答を渡した項目に限る（blk-plan の replan の口。226 Task 6）"
```

---

### Task 7: 人の関所の 1 つの決まりと答え（`replan.gate`・`answer`・`lines`）

**決まり（1 つ）:** run の中で直した項目は、約束の欄が承認済みの物と字のまま同じで（`planmarks.contract_diff` が空）、事前審査が人に聞く種類の穴（写しの rules の `HUMAN_FACE_KINDS`: regression・policy）を挙げなかった時だけ、人に聞かずに通す。それ以外は関所 `replan-gate` で人に聞く。役には決めさせず、コードが欄を比べて決める。

**Files:**
- Modify: `works/.shared/core/replan.py`
- Test: `works/tests/test_replan.py`（class `TestGateRule`・`TestAnswer`）

**Interfaces:**
- Consumes: Task 1 の `planmarks.contract_diff`・`amend`・`AMENDED_PLAN`、Task 3 の `conflict.set_replan`・`AMENDED`・`GAVE_UP`、Task 6 の `TRIP_FILE`・`PLAN_NODE`・`REVIEW_NODE`、`rolekit.given_up_reason`、写しの rules の `HUMAN_FACE_KINDS`（`board.rules_module(pathlib.Path(b.state["graph"]))` から読む）
- Produces:
  - `GATE_FILE = "replan-gate.md"`・`NOTES_FILE = "replan-notes.md"`・`HUMAN_KIND = "replan"`（`process.human_items` の行の kinds。node は `STOP_BY`）
  - `PLAN_GAVE_UP_WHY = "修正案の役の直しが 3 回とも拒まれた: {reason}"`・`REVIEW_GAVE_UP_WHY = "事前審査の役の返答が 3 回とも拒まれた: {reason}"`・`REFUSED_WHY = "人が関所で直した項目を退けた: {text}"`・`NO_GATE_WHY = "人に聞く直しなのに関所の答えが無い（関所が開かなかった）"`
  - `AMEND_HEAD = "同じ run の中で直した修正案の項目"`
  - `gate(b, *, run_id: str) -> dict` — `{"ask": bool, "gate_text": str, "gate_file": str}`。`new` の無い項目と `review` の無い項目は、その場で諦める（`set_replan(…, GAVE_UP, why=PLAN_GAVE_UP_WHY / REVIEW_GAVE_UP_WHY)`。理由は `rolekit.given_up_reason`）。残りの項目ごとに `contract_changed`・`human_faces`（その種類の穴の key）・`ask`（どちらかが在る）を `TRIP_FILE` に置く。`ask` の項目が 1 つでも在れば `GATE_FILE` を書く。文の頭の 3 行は字のまま次のとおり。
    1. `案の項目を run の中で直した（{k} 件。人に聞くのは {m} 件）。人に聞く理由: 約束の欄が変わった・事前審査が人に聞く穴を挙げた`
    2. `決めてほしいこと: 直した項目を使って修正に戻すか、退けるか（退けた項目の単位は直さずに最後の関所へ回り、run は続く）`
    3. `答え方: continue "<一言>" で直した項目を使う。stop "<理由>" で退ける。approve は continue、reject は stop と同じ`
    
    その後に、聞く項目ごとの節を置く。節が持つ物: 約束の欄の変化の名・人に聞く穴・申し出の文・裁定の文（字のまま）・前の項目と直した項目の JSON。
  - `answer(b, gate: dict | None) -> dict` — `{"returned": [単位…], "plan_file": str, "notes_file": str}`。項目ごとの扱い:
    - `ask` が偽の項目は直しを採る。
    - `ask` が真の項目は、`gate` の decision が continue・approve なら採る。stop・reject なら `REFUSED_WHY` で諦める。`gate` が None なら `NO_GATE_WHY` で諦める。
    - 採った項目は、まとめて `planmarks.amend(b, {n: new})` で差し替える。その項目の行は `set_replan(…, AMENDED)` に、`TRIP_FILE` の `result` は `"amended"` にする。
    - 関所が開いた時は `process.human_items` に 1 行を足す: `{round, kinds: [HUMAN_KIND], asked: [GATE_FILE], answer: "continue"|"stop", note: 一言, node: STOP_BY}`。
    - `NOTES_FILE` には、人の一言と、採った項目の事前審査の穴のうち人に聞く種類でない物を書く（無ければ書かずに ""）。
    - `plan_file` は `AMENDED_PLAN` のパス。採った項目が無ければ ""。
    - `TRIP_FILE` の全項目に `result` が在れば、何も書き換えずに前の結果を返す（Archon の再開）。
  - `lines(b) -> list[str]` — `TRIP_FILE` の項目ごとに 1 行: `案の項目 {n}（単位 {units}）: {直した——人が承認した / 直した——聞かずに通した（手段の欄だけ） / 直さずに諦めた: {why}}`。最後の関所の文（`line_edge.final_edge`）と報告の冒頭 1 が、見出し `AMEND_HEAD` の下に並べる（関所を開ける理由には数えない）。

- [ ] **Step 1: 落ちる試験を書く**

```python
class TestGateRule(TripCase):        # TripCase: TestReplanRoles の setUp に、修正案の役と事前審査の役の受け付けを通した盤面
    def test_means_only_passes_without_asking(self):     # 224b・225 の型（red_kind・id のクラス）
        self.trip(new=red_kind_fixed(), review=no_faces())
        got = replan.gate(entry.open_board(self.board), run_id="r")
        self.assertFalse(got["ask"])

    def test_contract_change_asks(self):                 # 195b の型（allowed_paths を広げた）
        self.trip(new=wider_paths(), review=no_faces())
        got = replan.gate(entry.open_board(self.board), run_id="r")
        self.assertTrue(got["ask"])
        self.assertIn("allowed_paths", pathlib.Path(got["gate_file"]).read_text(encoding="utf-8"))
        self.assertTrue(got["gate_text"].startswith("案の項目を run の中で直した（1 件。人に聞くのは 1 件）"))

    def test_human_kind_face_asks(self): ...             # 手段の欄だけの直しでも、事前審査が regression の穴を挙げたら聞く

class TestAnswer(TripCase):
    def test_approved_item_returns_units_and_swaps(self):
        self.trip(new=red_kind_fixed(), review=no_faces())
        b = entry.open_board(self.board); replan.gate(b, run_id="r")
        got = replan.answer(entry.open_board(self.board), None)
        self.assertEqual(got["returned"], [MEAN])
        b = entry.open_board(self.board)
        self.assertEqual(planmarks.approved_items(b)[0]["tests"][0]["red_kind"], "exception")
        self.assertNotIn(MEAN, conflict.held_by_rulings(b))
        self.assertEqual(json.loads(pathlib.Path(got["plan_file"]).read_text(encoding="utf-8"))["plan"][0]["unit_keys"], [MEAN])

    def test_gave_up_paths_reach_ask_human_verbatim(self):
        for case in ("refused", "no_gate", "plan_gave_up", "review_gave_up"):
            with self.subTest(case): ...   # どれも returned は空・行は gave_up・human_lines に PLAN_TEXT と why

    def test_answer_twice_is_idempotent(self): ...       # 2 度目の answer は同じ返り・SAVED_OP の行は増えない・human_items は 1 行
    def test_lines_name_each_item(self): ...
```

- [ ] **Step 2: 落ちることを確かめる**

Run: `cd works/tests && PYTHONDONTWRITEBYTECODE=1 python3 -m unittest test_replan.TestGateRule test_replan.TestAnswer`
Expected: FAIL（`AttributeError: … 'gate'`）

- [ ] **Step 3: 決まりと答えを書き、`final_edge` と報告の冒頭 1 に `lines` を並べる**

- [ ] **Step 4: 通ることを確かめる**

Run: `cd works/tests && PYTHONDONTWRITEBYTECODE=1 python3 -m unittest test_replan test_blk_fix_conflict.TestFixPlanItemReport`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add works/.shared/core/replan.py works/.shared/core/report.py works/darkfactory/lib/line_edge.py works/tests/test_replan.py
git commit -m "feat(works): 直した項目を人に聞かずに通すのは約束の欄が同じで人に聞く穴が無い時だけ、の 1 つの決まりと関所の答え（226 Task 7）"
```

---

### Task 8: 2 回目の修正の段（`blk-fix`）

**Files:**
- Modify: `works/blk-fix/blk-fix.yaml`（入力 `include_id`。既定 `fixing`。`fix-reads` の `with` に渡す）・`works/blk-fix/scripts/reads.py`（`INPUTS_INCLUDE_ID` を読み、`recount.READS` の include の段を替える）
- Modify: `works/blk-fix/scripts/accept.py`（手順 2 の前に `conflict.with_held`。手順 1b を盤面の TDD の状態の全部に当てる）
- Modify: `works/blk-fix/lib/tddloop.py`（`states`・`frozen_problems` の `skip_units`）
- Modify: `works/blk-fix/lib/fixrules.py`（控えの節）
- Test: `works/tests/test_replan.py`（class `TestSecondPass`）・`works/tests/test_blk_fix_tdd.py`（凍結の 2 つ）・`works/tests/test_blk_fix.py`（YAML と `INPUTS` の突き合わせ）

**Interfaces:**
- Consumes: Task 3 の `conflict.with_held`・`held_reply`・`accepted_units`・`amended_keys`、Task 7 の `answer` の返り
- Produces:
  - `tddloop.states(board_dir) -> list[pathlib.Path]` — 盤面の根の `tdd-<k>/state.json` を番号順に。
  - `tddloop.frozen_problems(state_file, repo, allowed=(), skip_units=())` — `skip_units` の単位の状態の `test_files` は確かめない。
  - 受け付けの手順 1b: `tddloop.states(盤面)` の各状態に今の 1b を当てる（許しと `skip_ids` は今どおり状態ごと）。今の輪の状態（入力 `tdd_state`）でない状態には `skip_units=conflict.amended_keys(b)` を渡す。
  - 受け付けの手順 2 の前: `reply = conflict.with_held(b, reply)`（-3〜1d の検査は役の返答そのものに当てる。合わせた返答を手順 2・3 と盤面に渡す）。
  - `fixrules.HELD_HEAD = "## 1 回目の修正の段で受け付けた返答（機械が貼った）"`・`fixrules.HELD_ASK`（字のまま）: 「控え {path} を Read で読め。直す義務は下の『直す義務の単位』（案を直して戻った単位）だけで、控えの単位の行は機械が足す——changes と not_done に控えの単位を書くな。changes と not_done の外の欄（fix_closure・mechanism_changed・plan_faces など）は、1 回目と今回を合わせた差分の全体について書け（控えの値から始めよ）。」。`conflict.held_reply` が控えを返す時だけ、修正役の指示書（`fix_parts`）の brief の節の後に置く。
  - `blk-fix` の入力 `include_id`（既定 `"fixing"`）。読んだ証拠はこの include の名で引く。

- [ ] **Step 1: 落ちる試験を書く**

```python
class TestSecondPass(TripCase):
    def test_second_pass_duty_is_returned_units_and_merges(self):
        self.approve(red_kind_fixed())                       # Task 7 の answer まで通した盤面
        owed, excused = conflict.fix_duty(entry.open_board(self.board))
        self.assertEqual(owed, {MEAN}); self.assertIn("1 回目の修正の段で受け付けた", excused[CLAMP])
        self.edit_tree(MEAN_FIX)
        r = self.accept_script(only_mean_reply(), pass_="first")
        self.assertTrue(r["ok"], r)
        out, _ = recount._fix_output(entry.open_board(self.board))
        self.assertEqual(sorted(c["unit_key"] for c in out["changes"]), sorted([MEAN, CLAMP]))
        self.assertIn("len(xs)", (self.repo / "stats.py").read_text(encoding="utf-8"))   # 差分が空でない

    def test_second_pass_rejects_rows_for_accepted_units(self): ...   # 役が CLAMP の行を書けば check_excused_units が拒む
    def test_fix_prompt_names_held_reply(self): ...                   # HELD_HEAD と控えのパス

# test_blk_fix_tdd.py
    def test_second_pass_cannot_touch_first_loop_frozen_tests(self): ...  # tdd-1 の凍ったファイルを 2 回目で変える → 拒む
    def test_amended_units_old_tests_are_not_frozen(self): ...           # 直した項目の単位の tdd-1 の test_files は外す
```

- [ ] **Step 2: 落ちることを確かめる**

Run: `cd works/tests && PYTHONDONTWRITEBYTECODE=1 python3 -m unittest test_replan.TestSecondPass test_blk_fix_tdd`
Expected: FAIL

- [ ] **Step 3: 書く**（`tdd-start` は変えない。2 回目の直す義務が戻った単位だけになるので、輪は戻った単位だけを振り分ける）

- [ ] **Step 4: 通ることを確かめる**

Run: `cd works/tests && PYTHONDONTWRITEBYTECODE=1 python3 -m unittest test_replan test_blk_fix test_blk_fix_tdd test_blk_fix_conflict test_tdd_suite`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add works/blk-fix works/tests/test_replan.py works/tests/test_blk_fix_tdd.py works/tests/test_blk_fix.py
git commit -m "feat(works): 2 回目の修正の段は戻った単位だけを直し、1 回目に受け付けた行を機械が合わせて渡す。凍結は run の全部の輪で効く（226 Task 8）"
```

---

### Task 9: 線に繋ぐ（6 節・境の節・linekit）と 224b・225 の型の筋書き

**Files:**
- Modify: `works/darkfactory/darkfactory.yaml`（`fixing` の後に 6 節。`h-rejudge` の `depends_on` に `h-refit`・`refitting`）
- Modify: `works/darkfactory/lib/line_edge.py`（`AT` に `"replan"`・`"regate"`・`"refit"`。`GATE_AT` に `"refit"`。at ごとの中身）
- Modify: `works/tests/linekit.py`（`LINE_ORDER` に 6 節。`Line.run` は include の id が `replanning`・`refitting` の行を `Line.replanning`・`Line.refitting` で回す）・`works/tests/test_line.py`（`LineShapeCase`）
- Test: `works/tests/test_replan.py`（class `TestLineReplay`）・`works/tests/test_edge.py`（at の 3 つの配線）

**Interfaces:**
- Consumes: Task 4〜8 の全部
- Produces（YAML。境の節の出口の型は今の境の節と同じ欄の全部）:
  - `h-replan`: `script: edge`・`at: "replan"`・`depends_on: [start, h-fix, fixing]`・`trigger_rule: none_failed_min_one_success`。中身は `go = replan.material(b)["go"]`。
  - `replanning`: `include: blk-plan`・`depends_on: [h-replan]`・`when: "$h-replan.output.go == true"`・`with: {judgment_file: $h-replan.output.judgment_file, base_rev: $start.output.base_rev, policy_paste: $start.output.policy_paste, policy_path: $start.output.policy_path, include_id: replanning, replan: "true"}`。
  - `h-regate`: `at: "regate"`・`depends_on: [start, h-replan, replanning]`。中身は `replan.gate(b, run_id=…)`（`ask`・`gate_text`・`gate_file`）。`h-replan` の go が偽の周は何もせず ask 偽。
  - `replan-gate`: approval。`depends_on: [h-regate]`・`when: "$h-regate.output.ask == true"`・decisions は approve・continue・stop・reject。message（字のまま）:
    ```
    修正の段で誤りと裁いた修正案の項目を、run の中で直した。約束の欄が変わったか、事前審査が人に聞く穴を挙げた。
    全文と答え方: $h-regate.output.gate_file（Read して答える）。
    continue "<一言>" で直した項目を使って修正に戻る。stop "<理由>" で直した項目を退ける（その単位は直さずに最後の関所へ回り、run は続く）。approve は continue、reject は stop と同じ。
    ```
  - `h-refit`: `at: "refit"`・`depends_on: [start, h-regate, replan-gate]`・`gate: {from: $replan-gate.output, if_skipped: null}`。中身は `replan.answer(b, gate)`。返りの `go` は「`returned` が空でない」かつ「`p3.fix` が盤面で待っている」。`open_units` は `returned` の JSON。ほかに `plan_file`・`notes_file` と、h-plan の控えからの `judgment_file` を返す。h-regate が何もしなかった周は go 偽。
  - `refitting`: `include: blk-fix`・`depends_on: [h-refit]`・`when: "$h-refit.output.go == true"`。`with` は `fixing` と同じ鍵で、`open_units`・`plan_file`・`notes_file`・`judgment_file` は `$h-refit.output.*`。足すのは `include_id: refitting`。
  - `h-rejudge` の `depends_on: [start, h-fix, fixing, h-refit, refitting]`（`replan.settle` は Task 4 のまま）。
  - 線の description の並びの文に「修正 →（裁定が案の項目の誤りなら）案の直し → 案の直しの関所（要る時だけ）→ 2 回目の修正」を足す。
  - 無人の run（`unattended`）・設計だけの run（`design_only`）に特別な分かれを作らない。設計だけの run は修正に入らないので案の直しも起きない。無人の run の `replan-gate` は `policy-gate` と同じに開く。

- [ ] **Step 1: 落ちる試験を書く**

```python
class TestLineReplay(ReplanCase):
    """224b・225 の型: 唯一直す項目の受け入れのテストの赤の種類・id の形が誤りと裁かれても、同じ run で直して差分が空でない"""
    def run_trip(self, new_item, gate=None):
        self.replanned(); self.accept_script(only_clamp_reply(), pass_="ruled")
        e = lambda at, **kw: line_edge.edge(self.board, at, self.repo, run_id="r", adapter_mode="optional",
                                            final_gate="", **kw)
        self.assertTrue(e("replan")["go"])
        self.play_role("plan", {"plan": [new_item]}); self.play_role("plan-review", no_faces())
        g = e("regate")
        r = e("refit", gate=gate if g["ask"] else None)
        return g, r

    def test_means_only_fix_same_run(self):
        g, r = self.run_trip(red_kind_fixed())
        self.assertFalse(g["ask"]); self.assertTrue(r["go"]); self.assertEqual(json.loads(r["open_units"]), [MEAN])
        self.edit_tree(MEAN_FIX)
        self.assertTrue(self.accept_script(only_mean_reply(), pass_="first")["ok"])
        line_edge.edge(self.board, "rejudge", self.repo, run_id="r", adapter_mode="optional", final_gate="")
        self.assertNotEqual(linekit.git(self.repo, "diff", "--", "stats.py"), "")
        b = entry.open_board(self.board)
        self.assertEqual(conflict.asked(b), [])
        self.assertTrue(any("直した" in x for x in replan.lines(b)))

    def test_contract_change_refused_goes_to_human(self):
        g, r = self.run_trip(wider_paths(), gate={"decision": "stop", "text": "範囲が広い"})
        self.assertTrue(g["ask"]); self.assertFalse(r["go"])
        line_edge.edge(self.board, "rejudge", self.repo, run_id="r", adapter_mode="optional", final_gate="")
        self.assertIn(PLAN_TEXT, conflict.human_lines(entry.open_board(self.board))[0])

    def test_second_ruling_in_refit_gives_up(self): ...   # 2 回目で同じ単位が再び fix_plan_item → h-rejudge の settle が CLOSE_WHY で諦める

# test_line.py の LineShapeCase: 節の順に 6 節・replan-gate が最上段の approval・h-rejudge の depends_on
```

- [ ] **Step 2: 落ちることを確かめる**

Run: `cd works/tests && PYTHONDONTWRITEBYTECODE=1 python3 -m unittest test_replan.TestLineReplay test_line.LineShapeCase`
Expected: FAIL（`BoardGap: 知らない at` など）

- [ ] **Step 3: YAML・境の節・linekit を書く**

- [ ] **Step 4: 通ることを確かめる**

Run: `cd works/tests && PYTHONDONTWRITEBYTECODE=1 python3 -m unittest test_replan test_line test_line_a test_edge test_yaml_rules` と `WORKS_TESTS=fast nice -n 19 sh works/tests/run.sh` と `sh ~/.cache/works-dogfood/rootfences.sh`
Expected: PASS・失敗 0

- [ ] **Step 5: Commit**

```bash
git add works/darkfactory works/tests/linekit.py works/tests/test_line.py works/tests/test_replan.py works/tests/test_edge.py
git commit -m "feat(works): 線の修正の後に案の直し・その関所・2 回目の修正を繋ぐ（224b・225 の型が同じ run で直る。226 Task 9）"
```

---

### Task 10: 役の決まりと記述を新しい意味に合わせる・CHANGELOG

**Files:**
- Modify: `works/blk-fix/rules/principles.md:15`・`works/blk-fix/rules/ruler.md:38`（`fix_plan_item` は「同じ run の中で修正案の役がこの項目だけを直し、事前審査と関所の決まりを通ってから 2 回目の修正の段で直す」。`text` には項目のどこをどう直すかを書く——修正案の役に字のまま渡る）
- Modify: `works/.shared/core/conflict.py`（docstring の頭・`REPLAN` の注記・`write_rulings` の `REPLAN` の約束・`NOTHING_OWED`）・`works/.shared/core/entry.py:142-143`・`works/.shared/core/deltamarks.py:126`・`works/blk-refix/rules/refix.md:9`・`works/blk-delta/commands/delta-review.md`（「次の run の修正案で決める」→「最後の人の関所で人が決める」）・`works/blk-fix/blk-fix.yaml:18,726` の記述
- Modify: `works/CHANGELOG.md`（`[Unreleased]` の `### Changed`）
- Test: `works/tests/test_conflict_kinds.py`（class `TestReplanWords`）

**Interfaces:**
- Consumes: Task 3〜9 の振る舞い
- Produces:
  - `write_rulings` の `REPLAN` の約束（字のまま）: 「案の項目そのものが誤りと裁いた。この単位も「項目の単位」に並べた同じ項目の単位も、今は直すな（機械が直す義務から外した）。この run の中で修正案の役がこの項目だけを直し、事前審査と人の関所の決まりを通ってから、2 回目の修正の段で直す。changes に書くな。1 回目に直した項目の単位の直しは作業ツリーから戻す（機械も戻す）」
  - CHANGELOG の 1 項目（下書き）: 「修正役の申し出を裁定役が `fix_plan_item`（承認済みの修正案の項目そのものの誤り）と裁いた時、その項目を次の run に持ち越さず、同じ run の中で修正案の役に戻す。役に渡すのはその項目・申し出の文・裁定の文だけで、返答はその項目に限り、差し替えは機械がする。直した項目は事前審査に掛かり、約束の欄（単位・狭め・消す物・書いてよいパス・触らない物・既存テストの書き換え・受け入れのテストの振る舞い）が同じで人に聞く種類の穴が無ければ聞かずに、そうでなければ新しい関所 `replan-gate` で人に聞いてから、2 回目の修正の段で直す。案の段に戻るのは 1 run に 1 回。直せなかった単位は ask_human と同じく最後の関所と次の run の依頼に、裁定の文を字のまま載せる。報告の『案の項目の誤りと裁いて直さずに残した単位』の節と、それだけで結末を round_limit にする分かれは消した」

- [ ] **Step 1: 落ちる試験を書く**

```python
class TestReplanWords(unittest.TestCase):
    def test_no_carry_over_words_left(self):
        for p in (CORE / "conflict.py", CORE / "entry.py", CORE / "deltamarks.py", BLK_FIX / "rules" / "principles.md",
                  BLK_FIX / "rules" / "ruler.md", BLK_FIX / "blk-fix.yaml", BLK_REFIX / "rules" / "refix.md"):
            with self.subTest(p.name):
                self.assertNotIn("次の run の修正案", p.read_text(encoding="utf-8"))

    def test_ruler_says_same_run(self):
        self.assertIn("同じ run の中で修正案の役", fixrules.sections(fixrules.RULER)["ruler-reply"])
```

- [ ] **Step 2: 落ちることを確かめる**

Run: `cd works/tests && PYTHONDONTWRITEBYTECODE=1 python3 -m unittest test_conflict_kinds.TestReplanWords`
Expected: FAIL

- [ ] **Step 3: 文を直し、CHANGELOG を書く**

- [ ] **Step 4: 通ることを確かめる**

Run: `WORKS_TESTS=fast nice -n 19 sh works/tests/run.sh` と `sh ~/.cache/works-dogfood/rootfences.sh` と `cd works/tests && PYTHONDONTWRITEBYTECODE=1 python3 -m unittest test_replan test_blk_fix_conflict test_blk_plan test_line`
Expected: PASS・失敗 0

- [ ] **Step 5: Commit**

```bash
git add works/blk-fix works/.shared/core works/blk-refix works/blk-delta works/CHANGELOG.md works/tests/test_conflict_kinds.py
git commit -m "docs(works): fix_plan_item の意味を同じ run の案の直しに合わせ、持ち越しの語を消す。CHANGELOG（226 Task 10）"
```

---

## この計画が扱わない物

- (b)「案の段で誤りを機械で先に弾く」: 採らない（run 226 の ■6。誤りの種類ごとに検査が増え、`test_tiers` の決まりを 2 か所に書き、持ち越しの道も残る）。
- 2 回目の修正の段の読んだ証拠と指示書のファイル（`reads-fix.json`・`prompt-p3.fix*.md`）は、1 回目の物を同じ名で上書きする。1 回目の物を別の名で残す要が出たら別の依頼にする。
- 開発の殻 `works/dev/fixmeasure.py` の節の数え（`fixing__` の頭）は `refitting__` を数えない。測る要が出たら別の依頼にする。
- 自分食いの run の pack の写し（`.archon/workflows/works`）は、版を固める段の物で、この計画では触らない。
