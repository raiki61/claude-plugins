# 裁定で外れた単位の直しを、裁定の後の修正の段で戻さない（依頼 241）Implementation Plan

状態: 入れた（works 0.2.22）。最後の回の扱い（`drop_excused_units`・`park_bound_units`）は依頼 242 で替えた（works/docs/plans/2026-10-04-stops-keep-work.md）。

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

## この文書の読み方（初めて読む人向け。本文の語はここで全部定める）

読み手: この計画の Task を 1 つずつ実装する AI の役（実装役）と、それを審査する役。どちらもリポジトリ claude-plugins の作業ツリー（枝 `wip/sdd-241`。起点の commit b8783d8c）を手元に持ち、名指したファイルを開ける。本文の「今」は起点の commit のコードの振る舞いで、名指したファイルが正本。外の資料は、要る所をこの文書に書き写した。開かなくても実装できる。

番号と名:
- works: リポジトリの `works/` に在るプラグイン。Archon（AI の作業の流れを YAML で回す外の道具）の上で、人の修正依頼を直す工程（ライン darkfactory）を回す。run はその 1 回の実行。works 0.2.20 は works の版の番号（`works/CHANGELOG.md`）で、起点の commit がその版。
- 依頼 241: この計画の元の依頼の番号（works を works 自身の修正に使う「自分食い」の依頼に振る連番）。依頼 224 と 226 は先に入った依頼で、224 は修正の受け付けが誤りを 1 回の拒否に並べる形、226 は下の「案の直し」。
- run 195d: works 0.2.20 で回した自分食いの run の 1 つで、この不具合を見つけた run。
- blk-fix: `works/blk-fix/` に在る修正のブロック（修正の段の節を並べた YAML `blk-fix.yaml` と、その script と lib）。
- TDD: テスト駆動開発（先にテストを書いて落ちることを見てから直す）。
- MEAN・CLAMP: 試験の種のリポジトリ（`works/dev/target-seed`）の 2 つの単位の key。`stats.py` の関数 `mean` の分母の誤りと、`clamp` の上限の枝の誤り。`works/tests/test_blk_fix.py` の定数。

置き場と道具:
- パスは、断りが無ければリポジトリの根からの相対。`accept.py:541` はそのファイルの 541 行目（起点の版）。
- 盤面: run ごとの状態の置き場（`$ARTIFACTS_DIR/board/`）。工程の節（例 `p3.fix` は修正の節）は 1 周に 1 度だけ返答を受ける。
- 写し: `works/.shared/core/graphloops/` と `works/.shared/core/gl-prompts/` は、本流の graphloops のバイト単位の写し。この計画は写しを変えない。
- 試験の段: `works/tests/tiers.py` が試験のモジュールを FAST（速い段）と HEAVY（重い段。git・盤面・子のプロセスを使う）に分ける。手元で回すのは速い段と、この計画で触ったモジュール。

修正の段の語:
- 修正役: 直す役の AI。返答の `changes` に、直した単位ごとに 1 行（`unit_key`・`files` など）を書く。単位は判定役が切った 1 つの欠陥。
- 修正の受け付け: `works/blk-fix/scripts/accept.py` の関数 `accept_fix`。修正役の返答を確かめ、通れば盤面に渡す。確かめは全部回して誤りを 1 回の拒否に並べる（凍ったテスト・書き込みの出どころ・食い違いの申し出の形・範囲・選んだ試験の赤など。表 `CHECKS`）。
- 輪: 拒まれた修正役は同じ会話で出し直す。上限 3 回（`GIVE_UP_AFTER`）。3 回目の拒否は、拒否の行が全部どれかの返答の行に結べる時だけ、その単位を止めて残りを通す（`park_bound_units`。行を結ぶのは `bind_problems`）。結べなければ諦め、`works/blk-fix/scripts/assert_changed.py` が盤面を止める（文「3 回拒まれ、どの単位にも結べない拒否で諦めた」）。
- 1 回目の段と裁定の後の段: 修正役は直す代わりに「食い違いの申し出」（依頼・テスト・コードが同時に成り立たないという証拠つきの申告）を返してよい。申し出が在ると、読むだけの裁定役が裁き、裁定の後に同じ修正役がもう一度出し直す。受け付けの環境変数 `INPUTS_PASS` は 1 回目が `first`、裁定の後が `ruled`。
- 裁定 `ask_human`（人に回す）と `fix_plan_item`（承認済みの修正案の項目そのものが誤り）: どちらも、その場では単位を直させない裁定。`fix_plan_item` はその項目に載る単位の全部を直させない。この 2 つが直させない単位を「外れた単位」と呼び、関数 `conflict.held_by_rulings(b)`（`works/.shared/core/conflict.py`）が {単位の key: 理由} で返す。外れていない開いた単位が「直す義務」の単位（`conflict.fix_duty(b)` の 1 つ目）。
- 案の直し（依頼 226）: `fix_plan_item` の項目を、同じ run の中で修正案の役に直させる道。修正の段が通って抜けると、線の境の節 h-replan が `replan.material(b)`（`works/.shared/core/replan.py`。返りの `go` が真なら回す）で待つ行を束ねて回す。直せた項目（状態 AMENDED）は 2 回目の修正の段（同じブロックの 2 度目の起動）で直し、直せなかった項目（状態 GAVE_UP）は ask_human と同じく最後の人の関所に出る。
- 控えて渡す（`hold_fix`）: 案の直しを待つ単位が在る間、受け付けは通った返答を盤面に渡さずに控えのファイル `conflict.HELD_REPLY` に置き、`{ok: true, done: true, parked: true}` を返す。案の直しの後に機械が盤面へ渡す。
- TDD の輪: 修正役の前に、単位ごとにテストを先に書いて赤（直す前の版で落ちる）を機械が確かめ、直して緑を確かめる段（`works/blk-fix/lib/tddloop.py`）。輪の状態のファイルに、緑にした単位の受け入れのテストのファイルの hash（`frozen`）と、輪が済んだ時の木（`frozen_tree`）を残す。受け付けはそのファイルの書き換えを拒む（凍結）。
- 1 回目の直し: 裁定の前に TDD の輪と 1 回目の修正役が作業ツリーに書いた直し。
- 範囲の照らし: `works/blk-fix/lib/planscope.py`。承認済みの修正案の各項目の `allowed_paths`（書いてよいパス）と、版からの変わったパスを照らす。今、単位の全部が外れた項目は範囲を与えず（関数 `_all_held`）、拒んだパスがその項目の範囲に入れば「その項目の直しなら作業ツリーから戻せ」と添える（関数 `_held_note`）。
- `revert_ruled_units`（`accept.py:541-572`）: 今、裁定の後の受け付けの頭で、申し出を返した回の返答の控え（`conflict.PARKED_REPLY`）の行のうち、外れた単位の行のファイルを修正前の版に戻し（凍ったテストのファイルは `frozen_tree` に戻す）、受け付けを頭から通し直す手。戻すファイルをほかの単位の行と共にすれば何もしない。trace の行の名は `accept.RULED_REVERTED_OP`（`"fix_ruled_reverted"`）。

試験の手助け（どれも `works/tests/` に在る既存の物）:
- `test_blk_fix.py`: `BoardCase`（種の git と盤面を試験ごとに作る。`fix_ready` は修正の節が待つ盤面、`edit_tree` は `stats.py` の書き換え）・`load("fix2_ok")`（修正役の返答の見本。行は MEAN と CLAMP の 2 つ）・`PLAN_FIELDS`（修正案の項目の欄の見本。受け入れのテスト `test_stats.py::TestStats::test_mean_of_two`）。
- `test_blk_fix_tdd.py`: `SUITE`（小さな試験の実行器の本文）・`OPEN`（開いた単位の JSON）・`NEW_TEST`（`test_mean_of_two` の本文）・`LoopCase`（輪を回す手 `route`・`red`・`fix_mean`）。
- `test_blk_fix_conflict.py`: `ConflictBoardCase.accept_script`（受け付けのスクリプトを子のプロセスで起こす）・`conflict_on_mean()`（MEAN の申し出）・`only_clamp_reply()`（CLAMP の行だけの返答）・`CLAMP_FIX`（CLAMP の直しの置き換え）・`ReplanCase`（`fix_plan_item` に裁いた盤面を作る。`ReplanCase.SHARED_ITEM` が真なら MEAN と CLAMP を 1 項目に載せる）・`split_plan_reply`（2 項目の修正案）・`CLAMP_FIELDS`（項目 2 の欄）。

## 根本の原因（run 195d）

証拠の置き場（自分食いの機械の上。要る所は下に書き写した）: `~/.cache/works-dogfood/carry/195d/` の `reject-accept_fix-1..3.txt`・`state.json`・`report.md` と、その run の盤面の `r1/conflict-rulings.md`・`r1/conflicts.json`・`r1/briefs.json`・`r1/fix-parked-reply.json`・`tdd-1/state.json`・`plan-fields.json`・`trace.jsonl`。

起きたこと:
1. 判定の開いた単位は 4 つ（`report.py+build`・`lens.py+_findings`・`report.py+gate_record`・`report.py+residue`）。承認済みの修正案は項目 1 つで、前の 3 つだけを載せた。`residue` はどの項目にも無い。
2. TDD の輪は `build` を緑にし（受け入れのテスト 11 本。凍ったファイルは `test_report_head.py`・`test_blk_lens.py`・`test_line_a.py`）、`residue` は TDD を通さない道（direct）にした。1 回目の修正役は `build`・`gate_record`・`residue` を直して返し、`lens` を申し出た。裁定役は項目 1 を `fix_plan_item` に裁き、項目 1 の 3 単位が外れた。裁定の後の段の初めの直す義務は `residue` 1 つで、全部が外れたのではない。
3. 控えの返答では、外れた `build`・`gate_record` の行と義務の `residue` の行が `report.py`・`line_edge.py` を共にする。だから `revert_ruled_units` は何もしなかった（機械は戻さなかった）。
4. 裁定の後の段の拒否:
   - 1 回目: 範囲。`lens.py`・`report.py`・`delta-review.md`・`line_edge.py` が外れた項目 1 の範囲にしか無く、拒否の文は「その項目の直しなら作業ツリーから戻せ」。直しを残した木は拒まれた。
   - 2 回目: 凍結。修正役が言われたとおり項目 1 の直しを手で戻し、凍ったテストのファイルにも手を入れた。同じ返答の `residue` の申し出（範囲の外が要る）は通って ask_human に積まれ（申し出 c1-4）、直す義務は空になった。
   - 3 回目（指示書の直す義務は空の配列）: 選んだ試験の赤 11 件。11 件とも `build` の受け入れのテスト（`tdd-1/state.json` の `tests` と同じ 11 本）。直しは戻ったのに、輪が「直す前の版で赤」を確かめたテストは凍ったまま残ったので、赤は必ず出る。加えて、2 回目に積んだ申し出を「丸ごと出し直せ」のとおり出し直したため、「今の直す義務の単位に無い」の行（止めてよくない確かめ conflict）も並んだ。
5. 3 回目の行は返答の行に結べない（返答の `changes` は空。外れた単位は返答の行になれない）。`assert_changed.py` が盤面を止め（by `works:fix`）、h-replan は飛ばされ、待っていた案の直しは諦めた行にされた。

答え:
- (a) 裁定の後の段が修正役を起こしたのは、段の初めには `residue` が義務に在ったから。義務が 2 回目の申し出で空になった後も、輪に「義務が空なら抜ける」道が無く、3 回目も修正役を起こした。ただし 3 回目を飛ばしても通らない（(b) の 3 つ目の行き止まりが残る）。
- (b) 外れた単位の 1 回目の直しを、受け付けはどの姿でも通さない。残せば範囲が拒む（外れた項目は範囲を与えない）。テストに手を入れれば凍結が拒む。直しを戻せば、輪が赤を確かめた受け入れのテストが赤になり、選んだ試験の赤で拒む（機械が `revert_ruled_units` で戻しても同じ。凍ったファイルは `frozen_tree` に戻すのでテストは残る）。この 3 つの行は外れた単位の物で、外れた単位は返答の行にならないので、`bind_problems` はどれも結べない。195d は 3 回で 3 つの行き止まりを順に踏んだ。
- (c) 決まりは 1 つ: **裁定の後の修正の段は、外れた単位の 1 回目の直しを戻さず、範囲の照らしも外れた項目をほかの項目と同じに扱う。** 外れた単位の直しは作業ツリーに 1 回目のまま残り、行き先は案の直しが決める（AMENDED は 2 回目の修正の段がその上で直し、GAVE_UP は最後の人の関所に出る）。

## 決めたこと（どれも 1 つの軸「目的と keep-essence を保って全体がより簡潔か」で選んだ）

keep-essence は `works/docs/keep-essence.md` の、どの作りでも残す works の 11 の仕組み。この計画に関わるのは 3（テストの凍結）・4（3 回拒まれたら諦める）・6（受け付けで変更に当たる試験を選んで回す）。

- **決め 1（候補の比べ）:** 依頼の 3 つの候補は、どれも 1 つだけでは 195d を通さない。
  - 「義務が空なら修正役を飛ばして案の直しへ」: 195d は段の初めに義務が在った。3 回目を飛ばしても、受け付けを回せば (b) の赤で拒み、回さなければ 2 回目までの手の戻しと凍ったテストへの手入れがそのまま案の直しに渡る。輪に「飛ばす」分かれも足す。
  - 「受け付けが外れた単位のファイルを機械で戻す」: 戻すほど、輪が赤を確かめたテストが赤になる。テストまで戻せば凍結が拒み、凍結を外す分かれが要る。共にするファイル（195d の `report.py`）では義務の単位の直しも消える。
  - 「拒否を外れた単位に結び、最後の回に止める」: 止めても直しが戻るだけで赤は消えない。外れた単位はもう止まっているので、止め直す意味も無い。
  - 選んだ決まり（直しを戻さない）は、`revert_ruled_units` とその通し直し・戻す手と、`planscope.py` の外れた項目の分かれ（`_all_held`・`_held_note`・引数 `held`）を消す。足す分かれは無い。範囲の照らしは 1 回目の段と同じ決まりになる。
- **決め 2（守りの置き場）:** 外れた単位を直させない守りは、返答の行の確かめ（`accept.py` の `check_excused_units`。外れた単位を `changes` に書いた返答を拒む）と、指示書の約束だけに置く。裁定の後の段で修正役が外れた項目のファイルを行に書かずに触っても、範囲では拒まない。その直しは、AMENDED なら 2 回目の修正の段の範囲の照らし（直した項目の範囲と、修正前の版からの差分）が、GAVE_UP なら最後の人の関所が見る。
- **決め 3（約束の文）:** 裁定の文（修正役が読む `conflict-rulings.md`。`conflict.write_rulings` が書く）の `fix_plan_item` の約束と `conflict.LATE_REPLAN_PROMISE` の「作業ツリーから戻す（機械も戻す）」を「作業ツリーにそのまま残す（戻すな・触るな）」に替える。195d の裁定 c1-2 の文（「既に前の段で実装と赤→緑を済ませた単位として扱う」）も、直しが残る前提で書かれていた。
- **決め 4（変えない物）:** 最後の回の `drop_excused_units`（修正役が外れた単位を `changes` に書いた時の戻し）・`park_bound_units`・事後の関門の束（`fixgates`）の義務の外の項目の飛ばし・差分の審査の材料の印（`.shared/core/refix.py` が読む `conflict.held_item`）は変えない。

## Global Constraints

- 期限・タイムアウトを新しく足さない（定数・引数・YAML のどれにも）。
- 写しと本流 `graphloops/` は変えない。写しの台帳 `works/.shared/core/COPIED_FROM` に行を足さない。
- keep-essence の 3・4・6 は今の確かめのまま（凍結・3 回で諦める・選んだ試験）。
- 新しいモジュールは作らない。試験はどれも `unittest.TestCase` のクラスの中に置く。
- 注記・docstring・拒否の文・約束の文は日本語。Python 3.12 が下限。
- 焦点の試験は `works/` から `PYTHONDONTWRITEBYTECODE=1 WORKS_TESTSLOT= python3 -m unittest tests.<module>[.<Class>]`。速い段は `works/` から `WORKS_TESTS=fast sh tests/run.sh`。根の柵は `sh ~/.cache/works-dogfood/rootfences.sh`。
- CHANGELOG は `works/CHANGELOG.md` の `[Unreleased]` だけに足す。版は上げない。
- commit のメッセージは日本語で、末尾に `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`。push はしない。

## Review Focus

1. 外れた単位の輪の直しと義務の単位の直しがファイルを共にする（195d の `report.py`）→ どちらも残り、義務の単位の行だけで受け付けが通る。（Task 1 の `test_shared_file_with_owed_unit_keeps_both`）
2. 裁定の後の段で修正役が外れた単位の行を `changes` に書く → 今どおり確かめ `excused` で拒む（守りは行の確かめ。決め 2）。（既存の `TestFixPlanItem.test_fixing_a_replanned_unit_is_rejected` が通ったままであること）
3. 外れた単位の受け入れのテストが凍ったファイルに在り、試験の実行器の在る run → 3 回目まで試験の赤が出ず、受け付けは控えて（`hold_fix`）案の直しの `go` が立つ。（Task 1 の `test_ruled_pass_keeps_held_tdd_work_and_holds_for_replan`）
4. 直す義務が空の盤面（全部の単位が外れた）→ 空の `changes` の返答が通る（`conflict.nothing_owed_but_excused`）。（Task 1 の主の試験が、義務が空の返答で確かめる）
5. 修正役が読む約束が「戻せ」のまま残り、修正役が手で戻して凍結や赤を踏む → 裁定の文と範囲の拒否の文のどちらにも「機械も戻す」「作業ツリーから戻せ」が無い。（Task 2 の `test_rulings_say_keep_held_work` と Task 2 Step 4 の grep）

---

### Task 1: 裁定の後の段は外れた単位の直しを戻さず、範囲は外れた項目も与える（195d の型）

**Files:**
- Modify: `works/blk-fix/scripts/accept.py`（`revert_ruled_units`（541-572 行）と `accept_fix` の中の呼び（660-668 行）と `accept.RULED_REVERTED_OP`（135 行）を消す。docstring の 32-36 行・52 行）
- Modify: `works/blk-fix/lib/planscope.py`（`_all_held`・`_held_note` を消し、`problems` の引数 `held` を消して範囲を全部の項目から与える。`check` の `held=conflict.held_by_rulings(b)` も消す）
- Modify: `works/tests/test_blk_fix_conflict.py`（`ConflictBoardCase.accept_script` に引数 `tdd_state`・`tdd_suite`。新しい class `TestHeldWorkStays(ReplanCase)`。下の Step 5 の既存の試験の直し）
- Modify: `works/tests/test_plan_scope.py`（class `HeldItemCase`）
- Modify: `works/tests/test_fix_accept_all.py`（`SeamCase.test_frozen_error_does_not_stop_ruled_revert` を消す）

**Interfaces:**
- Consumes: 上の「試験の手助け」、`tddloop.start(board, repo, suite, open_units) -> dict`（`go`・`state_file`）・`tddloop.step(state_file, reply, repo) -> dict`、`replan.material(b) -> dict`、`conflict.HELD_REPLY`
- Produces:
  - `ConflictBoardCase.accept_script(self, reply, *, iteration="1", pass_="first", pass_tag="", tdd_state="", tdd_suite="")` — `tdd_state` を環境変数 `INPUTS_TDD_STATE`（輪の状態のファイル）に、`tdd_suite` を `INPUTS_TDD_SUITE`（試験の実行器）に渡す。空は今どおり
  - `TestHeldWorkStays.held_tdd_board(self) -> tuple[str, str]` — (輪の状態のファイル, 実行器のパス)。Task 2 も使う
  - `planscope.problems(items, rows, changes, *, permits=(), loop=None) -> tuple[list[str], dict]` — 範囲（`allowed_paths`・tests の名）は全部の項目が与える。ほかの決まりと文は今のまま
  - `accept.py` に `revert_ruled_units` と `accept.RULED_REVERTED_OP` は無い。盤面の trace に `fix_ruled_reverted` の行は書かれない

- [ ] **Step 1: 落ちる試験を書く**（`works/tests/test_blk_fix_conflict.py`。`ReplanCase` の後に置く）

`held_tdd_board` の組み方:
1. `self.SHARED_ITEM = True`・`self.fix_ready()`。`self.tmp / "suite.py"` に `test_blk_fix_tdd.SUITE` を書き、`tddloop.start(self.board, self.repo, str(suite), test_blk_fix_tdd.OPEN)` の `go` が真。
2. 輪で MEAN を緑にする（`LoopCase` の `route`・`red`・`fix_mean` と同じ 3 つの `tddloop.step`: route は MEAN を tdd・CLAMP を direct、test は `NEW_TEST` を `test_stats.py` に足して `test_stats.py::TestStats::test_mean_of_two`、fix は `stats.py` の `sum(xs) / (len(xs) - 1)` を `sum(xs) / len(xs)` に）。返りの `done` が真で、状態の `frozen` の鍵が `["test_stats.py"]`。
3. 1 回目の修正役の返答: `load("fix2_ok")` の MEAN の行だけ（`files` は `["stats.py", "test_stats.py"]`）に、CLAMP の申し出 `{**conflict_on_mean(), "unit_key": CLAMP}` を欄 `conflicts` で添える。`self.accept_script(reply, tdd_state=state, tdd_suite=str(suite))` が `ok` 真・`parked` 真。
4. `ReplanCase.replanned` の後半と同じに、`planmarks.save`（`test_blk_fix.PLAN_FIELDS`）・`planbrief.cut_at`・CLAMP の申し出を `fix_plan_item` に裁く（`grounds` は `brief-1.md:1`）。MEAN と CLAMP の両方が `conflict.held_by_rulings` に在ることを断言する。

```python
class TestHeldWorkStays(ReplanCase):
    """run 195d の型: 裁定 fix_plan_item が、TDD の輪で緑にした単位（受け入れのテストが凍ったファイルに在る）を含む項目を外した。
    裁定の後の段は、その単位の 1 回目の直しを戻さず（戻せば輪が赤を確かめたテストが赤になり、どの行にも結べず諦める）、
    範囲でも外れた項目をほかの項目と同じに扱い、空の changes の返答を控えて案の直しへ渡す"""

    def test_ruled_pass_keeps_held_tdd_work_and_holds_for_replan(self):
        state, suite = self.held_tdd_board()
        empty = only_clamp_reply() | {"changes": []}
        for it in ("1", "2", "3"):   # 195d は 3 回とも拒まれ、3 回目で諦めた
            got = self.accept_script(empty, pass_="ruled", iteration=it, tdd_state=state, tdd_suite=suite)
            if got["ok"]:
                break
        self.assertEqual((got["ok"], got["done"], got.get("parked")), (True, True, True), got)
        self.assertIn("sum(xs) / len(xs)", (self.repo / "stats.py").read_text(encoding="utf-8"), "外れた単位の直しを戻した")
        b = entry.open_board(self.board, allow_halted=True)
        self.assertTrue(b.work(conflict.HELD_REPLY).is_file(), "控えて案の直しへ渡す")
        import replan
        self.assertTrue(replan.material(b)["go"], "h-replan が回る")
        ops = [json.loads(x).get("op") for x in (self.board / "trace.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()]
        self.assertNotIn("fix_ruled_reverted", ops)
```

`test_shared_file_with_owed_unit_keeps_both`（今も通る守りの試験。直しの後も通ることを見る）: `held_tdd_board` の 1・2 を使い（`ReplanCase.SHARED_ITEM` は偽で、`split_plan_reply` の 2 項目。項目 1 は MEAN、項目 2 は CLAMP）、3 は木に `CLAMP_FIX` を当ててから `only_clamp_reply([conflict_on_mean()])`（輪で緑にした MEAN を、輪の後に申し出る）、4 は `planmarks.save` に `test_blk_fix.PLAN_FIELDS + [CLAMP_FIELDS]` を置いて MEAN の申し出を `fix_plan_item` に裁く（`ReplanCase.replanned` の既定と同じ）。外れた MEAN の輪の直しと義務の CLAMP の直しが `stats.py` を共にする。裁定の後の返答は `only_clamp_reply()`（`tdd_state`・`tdd_suite` つき）。断言は `ok` が真・`stats.py` に `sum(xs) / len(xs)` と `return hi` の両方が在る。

- [ ] **Step 2: 落ちることを確かめる**

Run: `works/` から `PYTHONDONTWRITEBYTECODE=1 WORKS_TESTSLOT= python3 -m unittest tests.test_blk_fix_conflict.TestHeldWorkStays`
Expected: 主の試験は FAIL（`ok` が偽で、理由に「元で赤でなかった試験が赤」と `test_mean_of_two`。195d の 3 回目と同じ行）。`test_shared_file_with_owed_unit_keeps_both` は PASS（控えの返答に外れた単位の行が無く、今も戻さない。直しの後も通ることを Step 6 で見る）。主の試験が別の理由で落ちたら、盤面の組み方を直してから進む。なお Step 3 だけを当てた途中では、主の試験は「allowed_paths」の範囲の行（195d の 1 回目と同じ）で落ち、Step 4 で通る

- [ ] **Step 3: `accept.py` から `revert_ruled_units` を消す**

`accept_fix` の `note(found, "frozen", …)` の次の 9 行（`got = revert_ruled_units(…)` から `return out` まで）・関数 `revert_ruled_units`・定数 `accept.RULED_REVERTED_OP` を消す。モジュールの docstring の「裁定の後（INPUTS_PASS が ruled）は、凍ったテストの検査の次に revert_ruled_units …」の 5 行（32-36 行）を消し、1d の「単位の全部が直す義務から外れた項目（conflict.held_by_rulings。fix_plan_item ならその項目）は範囲を与えない。」（52 行）を「外れた単位の項目も範囲を与える（裁定の後の段は外れた単位の 1 回目の直しを戻さない。依頼 241）。」に替える。`drop_excused_units` と `_held_files` は今のまま。

- [ ] **Step 4: `planscope.py` の外れた項目の分かれを消す**

`_all_held`・`_held_note` を消し、`problems` から引数 `held` と範囲を与える項目の絞り（`granting`）を消して `items` の全部で範囲を与える（`_held_note(...)` を足していた 2 か所の文は末尾を外すだけ）。`check` の呼びから `held=` を消す。モジュールの docstring の「外れた項目」の段（10-13 行）と `problems` の docstring の `held` の行を、「裁定で外れた単位の項目も範囲を与える（依頼 241。外れた単位を直させない守りは受け付けの check_excused_units）」の 1 行に替える。`import conflict` は `test_permits` などでまだ使う。

- [ ] **Step 5: 今の振る舞いを縛っていた試験を直す**
  - `test_blk_fix_conflict.TestFixPlanItemWholeItem.test_parked_fix_of_a_held_unit_is_reverted` → 名を `test_parked_fix_of_a_held_unit_stays` にし、「機械も戻す」の断言を消し、断言を「`ok` が真・`stats.py` に `return hi` が残る・控えの返答（`conflict.PARKED_REPLY`）は変わらない・trace に `fix_ruled_reverted` の行が無い」に替える。
  - 同じ class の `test_revert_is_undone_when_the_reply_is_rejected` を消す（戻す手が無い）。
  - `TestFixPlanItem.test_test_of_the_held_item_is_not_in_scope` → 名を `test_test_of_the_held_item_is_in_scope` にし、`ok` が真を断言する。docstring に決め 2 を 1 行で書く。
  - `test_blk_fix_conflict.py:814` の `mock.patch.object(mod, "revert_ruled_units", …)` を消す。
  - `test_plan_scope.HeldItemCase`: `test_held_item_grants_no_paths_or_tests` を `test_held_item_grants_like_any_item`（`held` を渡さない呼びで、`mean_util.py` と `test_mean_of_two` が拒まれない・`out_of_scope` の `legacy.py` は拒まれる）に替え、`test_path_in_held_item_names_item_and_ruling` と `test_item_with_an_owed_unit_still_grants` を消す。class の docstring を決め 2 の 1 行にする。

- [ ] **Step 6: 通ることを確かめる**

Run: `works/` から `PYTHONDONTWRITEBYTECODE=1 WORKS_TESTSLOT= python3 -m unittest tests.test_blk_fix_conflict tests.test_plan_scope tests.test_fix_accept_all tests.test_replan tests.test_fix_duty tests.test_fix_rules tests.test_fix_gates tests.test_blk_fix tests.test_blk_tests_delta`
Expected: PASS・失敗 0

- [ ] **Step 7: Commit**

```bash
git add works/blk-fix/scripts/accept.py works/blk-fix/lib/planscope.py works/tests/test_blk_fix_conflict.py works/tests/test_plan_scope.py works/tests/test_fix_accept_all.py
git commit -m "fix(works): 裁定の後の修正の段は外れた単位の 1 回目の直しを戻さず、範囲は外れた項目も与える（run 195d の型。依頼 241 Task 1）"
```

---

### Task 2: 約束の文を「戻すな」に揃える・CHANGELOG・仕上げ

**Files:**
- Modify: `works/.shared/core/conflict.py`（`write_rulings` の約束の表の `REPLAN` の文（584 行）・`LATE_REPLAN_PROMISE`（139-143 行）・`held_units`・`held_item` の docstring の「blk-fix の planscope」の名指し）
- Modify: `works/tests/test_blk_fix_conflict.py`（class `TestHeldWorkStays` に 1 本）
- Modify: `works/CHANGELOG.md`（`[Unreleased]` の `### Fixed`）

**Interfaces:**
- Consumes: Task 1 の `TestHeldWorkStays.held_tdd_board`
- Produces:
  - `REPLAN` の約束の末尾（字のまま）: 「changes に書くな。1 回目に直した項目の単位の直しは作業ツリーにそのまま残す（戻すな・触るな。機械も戻さない。案を直した後の 2 回目の修正の段がその上で直す）」
  - `LATE_REPLAN_PROMISE` の末尾（字のまま）: 「changes に書くな。この段までに直した項目の単位の直しは作業ツリーにそのまま残す（戻すな・触るな。最後の人の関所で人が見る）」
  - CHANGELOG の 1 項目（下書き）: 「裁定役が案の項目の誤り（`fix_plan_item`）と裁いた時、その項目の単位の 1 回目の直しを裁定の後の修正の段で戻さなくなった。戻すと TDD の輪が直す前に赤を確かめた受け入れのテストが赤になり、修正の受け付けがどの単位にも結べない拒否を 3 回出して run を止め、同じ run の中の案の直しが走らなかった（run 195d）。直しは作業ツリーに残り、案を直した項目は 2 回目の修正の段がその上で直し、直せなかった項目は最後の人の関所に出る。修正案の範囲の照らしは、外れた項目もほかの項目と同じに扱う」

- [ ] **Step 1: 落ちる試験を書く**

```python
    def test_rulings_say_keep_held_work(self):
        self.held_tdd_board()
        text = entry.open_board(self.board).work(conflict.RULINGS_FILE).read_text(encoding="utf-8")
        self.assertIn("作業ツリーにそのまま残す（戻すな・触るな", text)
        self.assertNotIn("機械も戻す", text)
        self.assertNotIn("作業ツリーから戻す", conflict.LATE_REPLAN_PROMISE)
```

- [ ] **Step 2: 落ちることを確かめる**

Run: `works/` から `PYTHONDONTWRITEBYTECODE=1 WORKS_TESTSLOT= python3 -m unittest tests.test_blk_fix_conflict.TestHeldWorkStays.test_rulings_say_keep_held_work`
Expected: FAIL（裁定の文に「機械も戻す」が在る）

- [ ] **Step 3: 約束の 2 つの文を上の Produces の字に替え、`conflict.py` の docstring の「blk-fix の planscope と差分の審査の材料が読む」を「差分の審査の材料（refix）が読む」に直す。CHANGELOG に上の項目を足す**

- [ ] **Step 4: 焦点・速い段・根の柵を通す**

Run: `works/` から `PYTHONDONTWRITEBYTECODE=1 WORKS_TESTSLOT= python3 -m unittest tests.test_blk_fix_conflict tests.test_conflict_kinds tests.test_replan` と `WORKS_TESTS=fast sh tests/run.sh` と `sh ~/.cache/works-dogfood/rootfences.sh`
Expected: PASS・失敗 0。`grep -rn "機械も戻す\|作業ツリーから戻せ" works --include=*.py --include=*.md | grep -v docs/plans | grep -v CHANGELOG` が何も出さない

- [ ] **Step 5: Commit**

```bash
git add works/.shared/core/conflict.py works/tests/test_blk_fix_conflict.py works/CHANGELOG.md
git commit -m "fix(works): fix_plan_item の約束を「1 回目の直しはそのまま残す（戻すな）」に揃え、CHANGELOG（依頼 241 Task 2）"
```

---

## この計画が扱わない物

- 裁定の後の段の申し出の出し直し: 拒まれた返答の中の新しい申し出は ask_human に積まれて残り、「丸ごと出し直せ」のとおり同じ申し出を出し直すと、その単位はもう義務に無いので「今の直す義務の単位に無い」（止めてよくない確かめ conflict）で拒む。195d の 3 回目にも並んだ。この計画の後は 195d の型では起きにくいが、同じ形で最後の回を諦める道は残る。直し方の見込みは、`take_conflicts`（`accept.py`）が `conflict.park` と同じ「同じ申し出」の決まりで、もう積んだ申し出を確かめから外すこと。別の小さな run に回す。
- 義務が空の段で修正役を起こさない道（決め 1 の 1 つ目の候補）。修正役を 1 回余分に起こすだけで止まらないので、この計画では足さない。
- `residue` のように、どの項目にも載らない開いた単位が承認済みの修正案を通ること（修正案の受け付けの側の問い）。
- 最後の回の `drop_excused_units`・`park_bound_units`（決め 4）。
