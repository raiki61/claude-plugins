# 修正の受け付けが確かめを全部回し、誤りを 1 回の拒否に並べる（依頼 224・works の側）Implementation Plan

状態: 入れた（works 0.2.20。`DiskBoard.vet`・`tests/test_fix_accept_all.py`）。

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

## この文書の読み方（初めて読む人向け。本文の語はここで全部定める）

読み手: この計画を 1 Task ずつ実装する役。リポジトリ（claude-plugins）を手元に持ち、名指したファイルを開いて確かめられる。本文の「今」「今どおり」は、この枝 `wip/sdd-224`（起点 `wip/works-next` の dcf9a81d）のコードの振る舞いのことで、名指したファイルが正本。外の資料は要る所をこの文書に書き写した。開かなくても実装できる。

置き場と道具:
- パスは、断りが無ければリポジトリの根からの相対。`accept.py:430` はそのファイルの 430 行目（起点の版）。
- works: `works/` のプラグイン。Archon（AI の作業の流れを YAML で回す外の道具）の上で、人の修正依頼を直す工程を回す。run は 1 回の実行。
- 盤面: run ごとの状態の置き場（`$ARTIFACTS_DIR/board/`）。盤面の節（`p3.fix` など）は、本流 graphloops の review-loop の graph の写しで、1 周に 1 度だけ返答を受ける。盤面の口は `works/.shared/core/board.py` の `DiskBoard` と、それを包む `works/.shared/core/entry.py` の `take`。
- 写し: `works/.shared/core/graphloops/`・`works/.shared/core/gl-prompts/` は本流のバイト単位の写し。手直しは台帳 `works/.shared/core/COPIED_FROM` の `!` 行だけで入れる。この計画は写しを変えない。
- 修正の受け付け: `works/blk-fix/scripts/accept.py` の `accept_fix`。修正役の返答を確かめ、通れば盤面の `p3.fix` に渡す（`recount.accept_fix` → `entry.take`）。拒めば終了コード 0 の `{"ok": false, "reason", "reason_file", "changes": [], "done"}` を 1 行出し、理由の本文は盤面の `reject-accept_fix-<連番>.txt`（`script_io.emit_result`）。
- 写しの照らし: 盤面が `p3.fix` を受ける時に当てる写しの検査（graph の型・番号の読み替え・post_check `fix_covers_open_units`・記録の整合）。224c で、`fix_covers_open_units` は形の誤りを全部溜めて 1 回で返す形になった（見出し `FIX_REJECT_HEADING`）。
- 輪: 修正役の返答が受け付けに通るまで、同じ節の組を最大 3 回まわす（`accept.GIVE_UP_AFTER = 3`。`with_done` が 3 回目の拒否で抜ける旗 `done` を立てる）。1 回目の修正を `first`、裁定の後の 2 回目の修正役 fix-ruled を `ruled` と呼ぶ（環境変数 `INPUTS_PASS`）。
- 試験の段: `works/tests/tiers.py` の FAST（速い段）と HEAVY（重い段: git・盤面・子のプロセスを使う）。手元で回すのは速い段と、この計画で触った重い段のモジュールだけ。重い段の全部は GitHub の CI。

今の受け付けの確かめ（`accept_fix` の順。左の名は下の表 `CHECKS` の id にする）:
1. `frozen`: TDD の輪で凍ったテストのファイルを書き換えていないか（`tddloop.frozen_problems`）。今は当たれば即 `refuse`。
2. （`ruled` の時だけ）`revert_ruled_units`: 裁定が止めた単位の 1 回目の直しを作業ツリーから戻し、受け付けを頭から通し直す。確かめではなく「戻して頭から通し直す手」。
3. `writes`: 書き込みの出どころ（`check_writes` → `writes.check`）。今は当たれば即 `refuse`。
4. `conflict`: 食い違いの申し出（`take_conflicts`）。名指しが現物に無ければ拒否、在れば盤面の控えに積む。`first` で裁かれていない申し出が在れば `{ok: true, parked: true}` で輪を抜けて裁定へ（parked の出口）。
5. `pack`: `.archon/` の下を変えた（`check_pack_copy`）。即 `_reject`。
6. `duplicate`・`not_opened`: 同じ unit_key の重なり・直す単位に無い key。最初の 1 種だけで即 `_reject`。
7. `excused`: 直す義務から外れた単位の行。最後の回は `drop_excused_units` で外して頭から通し直す（戻して通し直す手）。それ以外は即 `_reject`。
8. `scope`: 承認済みの修正案の範囲（`check_plan_scope`）。即 `refuse`。
9. `tests`: 変更に当たる試験を機械が走らせた赤（`check_tests`）。即 `refuse`。
10. `gates`: 事後の関門の束（`fixgates.problems`。計画 220）。即 `refuse`。
11. `unitrows.take`（数え直しの前段。確かめではない）→ `copy`: 写しの照らし（`recount.accept_fix`）。拒めば、最後の回は `refuse`、それ以外は写しの文のまま返す。
- `refuse`: 最後の回なら、拒否の文が全部どれかの単位に結べる時に、その単位を止めて（`park_bound_units`。直しを戻し ask_human に積む）残りで頭から通し直す。結べなければ返答全体を拒む。`_reject` で返す確かめ（`conflict`・`pack`・`duplicate`・`not_opened`・`excused`）は最後の回も単位に結ばない。

依頼と関わる番号:
- 224: この計画。224・224b・224c は写しの照らしを 1 回に並べた（224c で済み、この枝に入っている）。224d・224e は works の段を工場（darkfactory 自身の run）に回して外れた。224e の最後の関所の答え: 「取り込まない。拒否の時に申し出の park を盤面ごと戻すので、形の誤りがあると申し出が裁定に届かない（keep-essence 8 が崩れる）。226 の後に会話の SDD で作る」。
- 222f: 2026-10-03 の run。修正の受け付けが 3 回とも別の確かめで拒んだ（下の Spec）。この計画の固定材料の型。
- 226（`wip/sdd-226`。先に入る）: 同じ run の中で修正案の項目を直す道。`accept.py` に「待つ単位が在れば盤面に渡さずに控える」分かれ（`hold_fix`）を足す。
- 236（工場で走っている）: 拒否の控えの行に確かめの id（check）を足す。「check の id は拒否の文を組む所で 1 か所に表として持つ」。

keep-essence: `works/docs/keep-essence.md` の、どの形でも残す works の強み 11 項目。この計画に関わるのは 3（テストの凍結）・4（3 回拒まれたら諦める）・5（書き込みの出どころ）・6（受け付けで選んで回す試験）・7（数え直し）・8（食い違いの申し出と、読むだけの裁定役）。

---

**Goal:** 修正の受け付けが、確かめの途中で返さずに全部を回し、見つけた誤りを確かめごとの見出しの下に 1 回の拒否で並べる。役は 1 回の出し直しで全部を直せ、3 回の枠は形の誤りを 1 つずつ知るためでなく、直しが収束するために使われる。

**Architecture:**

- 盤面に「乾いた照らし」を足す: `DiskBoard.vet` は受け付けの検査（型・番号の読み替え・post_check・記録の整合）を全部当てて、保存しない。`entry.take(…, commit=False)` と `recount.accept_fix(…, commit=False)` がそれを通す。写しは変えない。通る返答は今どおり `commit=True` の 1 回だけで盤面に渡す。
- 拒否の見出しと id の表を `accept.py` に 1 つ置く（`CHECKS`: id → 見出しの短い名・最後の回に単位に結んで止めてよいか）。行は確かめの作り手の文を字のまま使う。拒否の本文の形は `render_rejects` の 1 本で、出口に行ごとの `{check, text}`（`rejects`）を足す。
- `accept_fix` は確かめを `return` せず、表の id を付けて 1 本の並び `found` に積む。最後に、積んだ物が在れば写しの照らしも乾いた形で並べ、1 回だけ拒む。無ければ今どおり盤面に渡す。
- 戻して頭から通し直す 3 つの手（`revert_ruled_units`・最後の回の `drop_excused_units`・`park_bound_units`）は今の位置と条件のまま。積んだ誤りに依らず走り、通し直しが頭から積み直す。
- 申し出は今の位置で、前の確かめの誤りに依らず取り込む。1 回目に裁かれていない申し出が通れば、積んだ誤りが在っても今の parked の出口で裁定へ抜ける。拒否で申し出の控えを巻き戻さない。

**Tech Stack:** Python 3.12 以降の標準ライブラリ、works の盤面の層（`board`・`entry`・`recount`・`conflict`・`writes`・`tddloop`・`planscope`・`fixgates`・`unitrows`）、Archon の YAML（`blk-fix.yaml` の script の節の output_format）、unittest（`works/tests`）。

**Spec:**
- 依頼の文 `~/.cache/works-dogfood/req-224.json`〜`req-224e.json`。要る所の写し: 「1 回の拒否で、その返答の形の誤りを全部並べて返す。3 回の枠は残す（keep-essence 4）」（224）・「revert_ruled_units と take_conflicts は今の位置（形の検査より前）に残し、食い違いの申し出は形の誤りがあっても今どおり裁定へ渡す（keep-essence 8）。順に依る段はその単位の後続だけを飛ばす。最後の回の park_bound_units が単位に結べる文の形（unit_key を頭に）は保つ」（224e）。
- run 222f の拒否の文（盤面の `reject-accept_fix-1〜3.txt`）。1 回目「TDD の輪で凍ったテストのファイルを書き換えた: ['works/tests/tiers.py']」、2 回目「承認済みの修正案の項目から外れた…: works/.shared/core/gatemarks.py は項目 2 の out_of_scope に当たる / …はどの項目の allowed_paths にも無い / …修正案のどの項目の tests にも無いテストを足した」（11 行）、3 回目「precedent に problem と source が要る / p3.fix: 修正案の事前審査への応答が揃わない: 事前審査の '…' に応答が無い」（12 行。最後の回で結べずに " / " でつないだ文）。3 つとも 1 回目の木に既に在った。
- run 224e の最後の関所（`~/.cache/works-dogfood/boards/run-224e/…/board/r1/final-gate.md`）の R2: 「設計は申し出の受け渡しを拒否から独立させ、出し直しを冪等にする。差分は拒否と一緒に巻き戻す」。事前審査の 3 つの穴（裁定の後の申し出が拒否で巻き戻る・最後の回の外れた単位と結べる誤りの同居で全体が拒まれる・凍結の誤りで `revert_ruled_units` が飛ばされる）。
- 持ち主の決め: 判断の軸は 1 つ（目的と keep-essence 11 項目を保って、全体がより簡潔か。場合分けを足さない）。review-graph の上位互換で能力を落とさない。期限・タイムアウトを足さない。写しは `!` 行だけで直す。
- 工場の構造の目（run 224e の report.md の「構造の目」）: 「accept_fix は検査と、盤面や作業ツリーを書く段が交互に並んでいる。7 か所の早期 return をそのまま溜める形に変えると、拒み方が 2 つ並ぶか、書く段に番を差し込むことになる」。この計画は、書く段のうち拒否で戻すべき物が「戻して頭から通し直す手」だけ（どれも今の位置で今の条件）であることを使い、確かめの側だけを溜める形にした。申し出の積みは戻さない（R2 のとおり）。

## 決めたこと（どれも 1 つの軸「目的と keep-essence を保って全体がより簡潔か」で選んだ）

- **決め 1（写しの照らし）: 写しの照らしは、拒む時も乾いた形で当てて並べる。** 222f の 3 回目の誤りは写しの照らしで、works の確かめが先に拒む限り 1 回目には見えない。写しを変えずに見せる道は、盤面の受け付けを保存せずに当てること（`DiskBoard.vet`）。盤面の `_accept` を「当てる」と「書く」に割るだけで、検査の決まりは 1 か所のまま（写しの照らしを works に書き写さない）。通る返答は今どおり 1 回だけ当てる（数える量の上限 `COUNT_BUDGET` 300 回を倍に食わない）。
- **決め 2（重い確かめ）: `tests`・`gates` は、ほかの誤りが在っても回す。** 224e は「形の誤りが在る時は走らせない」分かれを足した。分かれは場合分けで、1 回目に赤を知れないと 2 回目でまた 1 種を知る。走る回数の上は今と同じく 3 回の枠の中。
- **決め 3（申し出の継ぎ目）: 申し出は前の確かめの誤りに依らず取り込み、拒否で巻き戻さない。** 1 回目（`first`）に裁かれていない申し出が通れば、積んだ誤りが在っても今の parked の出口で裁定へ抜ける。積んだ誤りは、裁定の後の受け付け（`ruled`）が同じ作業ツリーを頭から確かめ直して全部並べるので落ちない。`ruled` の新しい申し出は今どおり ask_human に裁いて積み、拒否でも残す。同じ申し出の出し直しは `conflict.park` が積み増さない（同じ単位・名指し・理由の行は 1 つ）。凍ったテストが誤りだという申し出が凍結の誤りと同居する時も、裁定（`fix_test_scope`）に先に届く。
- **決め 4（順に依る段）: 飛ばすのは入力が無い時だけ。** `fix_unit_keys` が None（盤面が待っていない・番号を名前に戻せない）なら `pack`・`duplicate`・`not_opened`・`excused`・`scope` を飛ばす（今と同じ）。224e の「単位ごとの飛ばし集合」は作らない（どの確かめも前の確かめの値を読まない。同じ単位に 2 つの見出しで行が並ぶのは、どちらも本当の誤り）。`duplicate` と `not_opened` は両方を並べる。
- **決め 5（戻して頭から通し直す手）: 今の位置・今の条件のまま。** `revert_ruled_units`（`ruled`）と最後の回の `drop_excused_units` は、積んだ誤りに依らず今の位置で走り、通し直しが頭から積み直す（外の呼びが積んだ物は捨てる。二重に載らない）。224e の事前審査の 3 つの穴はこれで起きない。
- **決め 6（最後の回）: 止めてよい確かめの行だけなら `park_bound_units`、1 つでも止めない確かめの行が在れば返答全体を拒み、全部を並べる。** 今の結果（止めない確かめは `_reject` で即返す）と同じで、並ぶ行が増えるだけ。
- **決め 7（文と id）: 行は作り手の文を字のまま、見出しは表 `accept.CHECKS` の短い名。** 作り手（`tddloop`・`writes`・`planscope`・`fixgates`・`conflict`・写し）の文と `accept.py` の頭の定数（`DUPLICATE`・`NOT_OPENED`・`EXCUSED`・`PACK_COPY`・`CONFLICT_BAD`）は変えない（最後の回の結び `bind_problems` と、今の試験の `assertIn` がそのまま効く）。236 の「1 か所の表」は `accept.CHECKS`。出口の `rejects` が行ごとに 1 つの id を持つ。
- **決め 8（226 の控え）: 積んだ誤りが無い時だけ控える。** 誤りが在れば控えずに拒み、写しの照らしも乾いた形で並べる（Task 5）。
- **決め 9（ほかのブロックの受け付け）: この計画では変えない。** 調べた結果、ほかの受け付け（`planblk.take`・`refix.accept_review`・`judgetake.take`・`blk-pr`・`blk-premises`・`purpose`・`material`・`rejudge`・`ci_role`・`specblk`・`eyes`・`report_roles`・`design`・`ruling`・`tddloop.step`）も前段で返すが、拒否が枠を使い切った観測は修正の受け付けだけ。乾いた照らしの口（`entry.take` の `commit`）は共通なので、各ブロックは後の小さな run で同じ形（積む → 乾いた照らし → 1 回で拒む）に寄せる。並べ方の関数 `render_rejects` は、2 つ目の使い手が出た時に core へ移す。

## 226・236 との重なり

- 226 は先に入る。224 は最後の審査の前に、226 が入った `wip/works-next` に載せ直す（Task 5）。
- 重なるファイル: `works/blk-fix/scripts/accept.py`（226 は `unitrows.take` の後・`recount.accept_fix` の前に `conflict.waiting` の分かれと `hold_fix` を置き、受けた時の 4 つの trace を `traced()` の閉包にまとめた。`resolved_changes` を `named_reply` 経由にした）・`works/.shared/core/recount.py`（226 は `fix_reply`・`v1_changes` を足す。224 は `accept_fix` に keyword `commit` を足す。同じ関数の別の行）・`works/tests/test_blk_fix_conflict.py`・`test_fix_duty.py`・`test_fix_rules.py`（226 は数行。224 は mock の引数の形だけ）。
- 重ならない: `board.py`・`entry.py` の `take`・`blk-fix.yaml`・新しい試験のモジュール `test_fix_accept_all.py`（226 の試験の手助け `ReplanCase` に依らない。226 の分かれは mock で確かめる）。
- 236: 236 が先に入り、修正の受け付けの確かめの id の表を別の所に置いていれば、Task 5 で `CHECKS` の見出しと「止めてよいか」をその表に寄せ、表を 2 つにしない。236 が `role-rejects.json` の行を作る時は、出口の `rejects` の `check` を読めばよい。

## Global Constraints

- 期限・タイムアウトを新しく足さない（定数・引数・YAML のどれにも）。
- 写し（`works/.shared/core/graphloops/`・`gl-prompts/`）と本流 `graphloops/` は変えない。`COPIED_FROM` に行を足さない。
- keep-essence の 11 項目を保つ。3・5・6・7 の確かめは全部の回で走る。4 は `GIVE_UP_AFTER` と `with_done` を変えない。8 は決め 3。
- 拒んだ受け付けは盤面の状態（`state.json`・`out/`・instance）を書かない。書いてよいのは今も書く物だけ（数え直しの量と控え `count-budget.json`・`count-cache.json`、事後の関門の束の帳面 `fixgates.LEDGER`、`revert_ruled_units`・`park_bound_units` の今の書き戻し、申し出の控え）。
- 層（`works/tests/test_layers.py`）を変えない。新しいモジュールは作らない（試験のモジュール 1 本を除く）。
- 新しい試験のモジュール `test_fix_accept_all` は HEAVY（`test_blk_fix.BoardCase` で種の git と盤面を作る）。`works/tests/tiers.py` の HEAVY に 1 行足す。
- 試験はどれも `unittest.TestCase` のクラスの中に置く。
- 注記・docstring・拒否の文は日本語。
- Python 3.12 が下限。
- 焦点の試験は works/ から `PYTHONDONTWRITEBYTECODE=1 WORKS_TESTSLOT= python3 -m unittest tests.<module>[.<Class>]`。速い段は works/ から `WORKS_TESTS=fast sh tests/run.sh`。根の柵は `sh ~/.cache/works-dogfood/rootfences.sh`（Task 5）。
- CHANGELOG は `works/CHANGELOG.md` の `[Unreleased]` だけに足す（Task 5）。版は上げない。
- commit のメッセージは日本語で、末尾に `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`。push はしない。

## Review Focus

1. 乾いた照らしが盤面を書く（`apply_writes` が記録を、post_check が `loop.coverage_after` を入れ物に書く）→ 拒否の後も `state.json` は同じ・`p3.fix` は待ちのまま・`out/` に何も無い。入れ物は使い回さない。（Task 1 の `test_dry_take_lists_copy_errors_and_writes_nothing`・`test_dry_take_of_clean_reply_leaves_board_waiting`）
2. 通る返答で写しの照らしが 2 度走る（数える量を倍に食い、上限 300 回に早く届く）→ 通る道は `commit=True` の 1 回だけ。（Task 3 の `test_clean_reply_takes_once`）
3. 1 回目に、申し出と凍結の誤りが同じ返答に在る → 申し出は裁定に届き（parked の出口・`conflicts.json` に 1 行）、拒否の文は書かない。同じ返答をもう一度出しても行は増えない。（Task 4 の `test_first_pass_conflict_reaches_ruling_with_frozen_error`・`test_same_conflict_twice_parks_once`）
4. 最後の回に、単位に結べる行と結べない行（重なり・開いていない key）が混ざる → 何も止めず、返答全体を拒んで全部の行を並べる。申し出の控えと作業ツリーは前のまま。（Task 3 の `test_last_round_unbindable_line_rejects_whole`）
5. 226 の待つ単位が在る盤面で、誤りが在る返答 → 控えずに拒む（控えの返答 `conflict.HELD_REPLY` を書かない）。誤りが無ければ今どおり控える。（Task 5 の `test_waiting_board_rejects_instead_of_holding`）

---

### Task 1: 盤面の乾いた照らし（`DiskBoard.vet`・`entry.take` と `recount.accept_fix` の `commit`）

**Files:**
- Modify: `works/.shared/core/board.py:964-1053`（`_accept` を「当てる」`_vetted` と「書く」に割る。`vet` を足す。型・番号の読み替え・記録の整合の `AnswerReject` に `problems`）
- Modify: `works/.shared/core/entry.py:961-983`（`take` に keyword `commit`。docstring の頭の一覧 `take(…)` の行も）
- Modify: `works/.shared/core/recount.py:80-91`（`accept_fix` に keyword `commit`）
- Create: `works/tests/test_fix_accept_all.py`（class `DryTakeCase`）
- Modify: `works/tests/tiers.py`（HEAVY に `"test_fix_accept_all",  # 修正の受け付けが確かめを全部回して並べる: test_blk_fix の BoardCase で試験ごとに種の git と盤面を作る`）

**Interfaces:**
- Consumes: 今の `DiskBoard._accept`・`entry.take`・`recount.accept_fix`・`engine.util.AnswerReject(msg, problems)`
- Produces:
  - `DiskBoard._vetted(self, nid: str, output: dict, *, engine_reply: bool) -> tuple[dict, list[str], dict]` — `_accept` の頭から `check_record` までを当て、(読み替えた返答, notes, instance) を返す。保存しない。`_accept` はこれを呼んでから今どおり書く（振る舞いと文は同じ）。
  - `DiskBoard.vet(self, nid: str, output: dict) -> AnswerReject | None` — `_vetted(nid, output, engine_reply=False)` を当て、`AnswerReject` は投げずに返す。通れば None。`BoardGap`・ほかの `Reject`（止めた run など）は今どおり投げる。呼んだ後の入れ物は中が書かれうるので捨てる（docstring に書く）。
  - 型の誤り・番号の読み替えの誤り・記録の整合の誤りの `AnswerReject` は `problems=errs`（1 誤り 1 要素。文は今と同じ）。
  - `entry.take(board_dir, nid, reply, repo, *, snapshot_name=None, commit=True) -> dict` — `commit` が偽なら、開いた入れ物で `vet` を当てて捨てる。返り `{"ok": bool, "reason": str, "dry": True}` に、拒否なら `problems`（例外の `problems`。空なら `[reason]`）。止めた run・読むだけの役の作業ツリーの比べは `commit` に依らず今どおり先に当てる。
  - `recount.accept_fix(reply, board, base_rev, repo, *, commit=True) -> dict` — 偽なら `entry.take(…, commit=False)` の返りに `"changes": []` を足して返す（盤面を読み直さない）。
  - 試験のモジュールの頭の手助け（後の Task も使う）: `accept_module(name) -> module`（`blk-fix/scripts/accept.py` を `spec_from_file_location` で別名に読む。`test_blk_fix.TestAccept.accept_module` と同じ形）・`sha(path) -> str`（ファイルの sha256）。

- [ ] **Step 1: 落ちる試験を書く**（`test_blk_fix` の `BoardCase`・`load`・`FIXED`・`board_shas` を使う）

```python
class DryTakeCase(test_blk_fix.BoardCase):
    def two_copy_errors(self):
        reply = test_blk_fix.load("fix2_ok")
        reply["changes"][0]["bypass_tried"] = "なし"       # 写しの照らしの誤り 1（mean の行）
        reply["changes"][1]["breaks"]["result"] = "なし"   # 写しの照らしの誤り 2（clamp の行）
        return reply

    def test_dry_take_lists_copy_errors_and_writes_nothing(self):
        self.fix_ready(); self.edit_tree(test_blk_fix.FIXED)
        before = test_blk_fix.board_shas(self.board)
        got = recount.accept_fix(self.two_copy_errors(), self.board, "", self.repo, commit=False)
        self.assertEqual((got["ok"], got["dry"], got["changes"]), (False, True, []), got)
        self.assertEqual(len(got["problems"]), 2, got)
        self.assertEqual(test_blk_fix.board_shas(self.board), before)
        self.assertEqual(entry.open_board(self.board).node_state("p3.fix"), "pending")

    def test_dry_take_of_clean_reply_leaves_board_waiting(self):
        # 乾いた照らしが通る返答は、後で commit しても同じく通る（当てる物が同じ）
        self.fix_ready(); self.edit_tree(test_blk_fix.FIXED)
        before = test_blk_fix.board_shas(self.board)
        got = recount.accept_fix(test_blk_fix.load("fix2_ok"), self.board, "", self.repo, commit=False)
        self.assertEqual((got["ok"], got["dry"]), (True, True), got)
        self.assertEqual(test_blk_fix.board_shas(self.board), before)
        self.assertIs(recount.accept_fix(test_blk_fix.load("fix2_ok"), self.board, "", self.repo)["ok"], True)
        self.assertNotEqual(entry.open_board(self.board).node_state("p3.fix"), "pending")

    def test_schema_errors_carry_one_problem_each(self):
        self.fix_ready(); self.edit_tree(test_blk_fix.FIXED)
        reply = test_blk_fix.load("fix2_ok"); del reply["interactions"]; del reply["wrote_refs"]
        got = entry.take(self.board, "p3.fix", reply, self.repo, commit=False)
        self.assertIn("返答が型に合わない", got["reason"])
        self.assertEqual(len(got["problems"]), 2, got)
```

- [ ] **Step 2: 落ちることを確かめる**

Run: works/ から `PYTHONDONTWRITEBYTECODE=1 WORKS_TESTSLOT= python3 -m unittest tests.test_fix_accept_all.DryTakeCase`
Expected: FAIL（`TypeError: accept_fix() got an unexpected keyword argument 'commit'`）

- [ ] **Step 3: `_vetted`・`vet`・`commit` を書く**（`_accept` の中の検査の順と文は変えない。`vet` は `_vetted` を呼ぶだけで、`settle`・`save`・`trace` を呼ばない）

- [ ] **Step 4: 通ることを確かめる**

Run: works/ から `PYTHONDONTWRITEBYTECODE=1 WORKS_TESTSLOT= python3 -m unittest tests.test_fix_accept_all tests.test_entry tests.test_fix_rules` と `WORKS_TESTS=fast sh tests/run.sh`
Expected: PASS（前からの試験も。`test_fix_rules.FixCoversOpenUnitsAllErrorsCase` は `entry.take` の commit の道のまま通る）

- [ ] **Step 5: Commit**

```bash
git add works/.shared/core/board.py works/.shared/core/entry.py works/.shared/core/recount.py works/tests/test_fix_accept_all.py works/tests/tiers.py
git commit -m "feat(works): 盤面の受け付けの検査を保存せずに当てる口（DiskBoard.vet・entry.take と recount.accept_fix の commit）（224 Task 1）"
```

---

### Task 2: 拒否の見出しと id の表・並べ方（`accept.CHECKS`・`render_rejects`・`rejected`）

**Files:**
- Modify: `works/blk-fix/scripts/accept.py`（表 1 つ・定数 1 つ・関数 3 つ。`accept_fix` はまだ変えない）
- Modify: `works/blk-fix/blk-fix.yaml:605-614`・`:793-802`（`fix-accept`・`fix-ruled-accept` の output_format の properties に `rejects: {type: array}` と注記 1 行）
- Test: `works/tests/test_fix_accept_all.py`（class `RenderCase`）

**Interfaces:**
- Consumes: なし（純な関数）
- Produces:
  - `CHECKS: dict[str, tuple[str, bool]]` — 確かめの id → (見出しの短い名, 最後の回に単位に結んで止めてよいか)。並びは受け付けが回す順。修正の受け付けの拒否の見出しと id の表はここ 1 か所（236 の表）。値:

    | id | 見出し | 止めてよいか |
    |---|---|---|
    | `frozen` | TDD の輪で凍ったテストのファイル | True |
    | `writes` | 書き込みの出どころ | True |
    | `conflict` | 食い違いの申し出の形 | False |
    | `pack` | .archon/ の下の変更 | False |
    | `duplicate` | 同じ unit_key の重なり | False |
    | `not_opened` | 今の周に直す単位に無い unit_key | False |
    | `excused` | 直す義務から外れた単位 | False |
    | `scope` | 承認済みの修正案の範囲 | True |
    | `tests` | 変更に当たる試験の赤 | True |
    | `gates` | 事後の関門の束 | True |
    | `copy` | 写しの受け付け（graph の p3.fix の型と規則） | True |

  - `REJECT_HEAD = "受け付けは確かめを全部回した。見出しごとに並べた行を全部直した返答を丸ごと出し直せ（直した所だけを返すな。1 回の出し直しで全部を直せ）:"`
  - `note(found: list, check: str, texts) -> None` — `found` に `(check, 文)` を足す。空の文は足さない。表に無い id は `ValueError`（配線の誤り。入口が 2 にする）。
  - `render_rejects(found: list[tuple[str, str]]) -> str` — `REJECT_HEAD` の後に、表の順で行の在る確かめごとに `## <見出し>（確かめ <id>・<件数> 件）` と、行 `  - <文>` を並べる。同じ (id, 文) は 1 つ。文の中の改行は次の行の頭に 4 字の空白を置いて続ける。
  - `rejected(found) -> dict` — `{"ok": False, "reason": render_rejects(found), "rejects": [{"check": id, "text": 文}…], "changes": []}`。`rejects` は本文の `  - ` の行と同じ数・同じ順。

- [ ] **Step 1: 落ちる試験を書く**（`accept_module` は `test_blk_fix.TestAccept.accept_module` と同じく `spec_from_file_location` で読む関数をモジュールの頭に置く）

```python
class RenderCase(unittest.TestCase):
    acc = accept_module("blk_fix_accept_render")

    def test_groups_follow_table_order(self):
        found = []
        self.acc.note(found, "copy", ["c1"]); self.acc.note(found, "frozen", ["f1", ""]); self.acc.note(found, "copy", ["c2", "c1"])
        text = self.acc.render_rejects(found)
        self.assertTrue(text.startswith(self.acc.REJECT_HEAD))
        self.assertLess(text.index(self.acc.CHECKS["frozen"][0]), text.index(self.acc.CHECKS["copy"][0]))
        self.assertIn("（確かめ copy・2 件）", text)
        self.assertEqual([x for x in text.splitlines() if x.startswith("  - ")], ["  - f1", "  - c1", "  - c2"])

    def test_rejected_carries_one_check_per_line(self):
        found = []
        self.acc.note(found, "scope", ["s1"]); self.acc.note(found, "frozen", ["f1"])
        out = self.acc.rejected(found)
        self.assertEqual((out["ok"], out["changes"]), (False, []))
        self.assertEqual([r["check"] for r in out["rejects"]], ["frozen", "scope"])
        self.assertEqual(len(out["rejects"]), out["reason"].count("\n  - "))

    def test_multiline_text_is_indented(self):
        found = []
        self.acc.note(found, "copy", ["返答が型に合わない:\n  - a"])
        self.assertIn("  - 返答が型に合わない:\n      - a", self.acc.render_rejects(found))

    def test_unknown_check_is_value_error(self):
        with self.assertRaises(ValueError):
            self.acc.note([], "nope", ["x"])

    def test_yaml_names_rejects_on_both_accept_nodes(self):
        # blk-fix.yaml を読み、fix-accept と fix-ruled-accept の output_format の properties に rejects が在る
        ...
```

- [ ] **Step 2: 落ちることを確かめる**

Run: works/ から `PYTHONDONTWRITEBYTECODE=1 WORKS_TESTSLOT= python3 -m unittest tests.test_fix_accept_all.RenderCase`
Expected: FAIL（`AttributeError: module 'blk_fix_accept_render' has no attribute 'note'`）

- [ ] **Step 3: 表と関数を書き、YAML の 2 つの節に `rejects` を足す**

- [ ] **Step 4: 通ることを確かめる**

Run: works/ から `PYTHONDONTWRITEBYTECODE=1 WORKS_TESTSLOT= python3 -m unittest tests.test_fix_accept_all tests.test_blk_fix.TestBlockYaml tests.test_script_contract`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add works/blk-fix/scripts/accept.py works/blk-fix/blk-fix.yaml works/tests/test_fix_accept_all.py
git commit -m "feat(works): 修正の受け付けの拒否の見出しと確かめの id の表と、確かめごとに並べる文の形（224 Task 2）"
```

---

### Task 3: 申し出より後の確かめを全部回して並べ、最後の回は止めてよい行だけで止める

**Files:**
- Modify: `works/blk-fix/scripts/accept.py:430-520`（`accept_fix` と `refuse`。docstring の頭 :5-69 の「順は」と「done は…」の段）
- Modify: `works/tests/test_fix_gates.py:385-396`（`recount.assert_not_called()` → `commit=False` で 1 回。`startswith(fixgates.REJECT)` → `assertIn`）
- Modify: `works/tests/test_fix_rules.py:577`・`:667`・`:777-779`・`:873`、`works/tests/test_fix_duty.py:109`（`recount.accept_fix` の mock が keyword `commit` を受ける形に。呼びを数える試験は `commit=True` の呼びだけを「盤面に渡した」と数える）
- Test: `works/tests/test_fix_accept_all.py`（class `AllChecksCase`）

**Interfaces:**
- Consumes: Task 1 の `recount.accept_fix(…, commit=)`、Task 2 の `CHECKS`・`note`・`rejected`
- Produces:
  - `accept_fix` の中の並び `found: list[tuple[str, str]]`。申し出（`take_conflicts`）より後の確かめは `return` せずに `note`: `pack`（`check_pack_copy` の文）・`duplicate`（`DUPLICATE + k` を key ごと）・`not_opened`（`NOT_OPENED + k`）・`excused`（最後の回でない時、`f"{EXCUSED}{k}（{why}）"`）・`scope`（`check_plan_scope` の行）・`tests`（`check_tests` の赤）・`gates`（`fixgates.reject_lines`）。`fix_unit_keys` が None なら今どおり `pack`〜`scope` を飛ばす。`take_conflicts` の拒否（`{ok: false}`）は `note(found, "conflict", [reason])`、parked の出口は今どおり返す。
  - `unitrows.take` の後: `out = recount.accept_fix(reply, board, base_rev, repo, commit=not found)`。拒否なら `note(found, "copy", out.get("problems") or [reason])`。`found` が在れば `return refuse(found)`。無ければ今どおり受けた時の trace を書いて `out` を返す。
  - `refuse(found)`: 最後の回で、`whole` が dict で、`found` の全部の id が表で止めてよい物なら、文の並びを `park_bound_units` に渡す（今の止めて通し直す道）。そうでなければ `rejected(found)`。
  - 凍結と書き込みの出どころは、この Task ではまだ今の位置で `note` して即 `refuse(found)`（Task 4 で積む形にする）。

- [ ] **Step 1: 落ちる試験を書く**（`AllChecksCase(test_blk_fix.BoardCase)` に `run_it = test_blk_fix.TestAccept.run_it`・`scope_ready = test_blk_fix.TestAccept.scope_ready`・`parked_units = test_blk_fix.ParkBoundBase.parked_units` を借りる。クラスの手助け: `acc = accept_module("blk_fix_accept_all")`・`env(iteration="1", pass_="first", state="")`（`mock.patch.dict(os.environ, {INPUTS_ITERATION, INPUTS_TDD_STATE, INPUTS_PASS, INPUTS_TDD_SUITE: ""})` を返す）・`accept_direct(reply, **env) -> dict`（`env` の中で `acc.accept_fix(reply, self.board, "", self.repo)`）。Task 4 の `SeamCase` はこのクラスを継がずに同じ手助けを借りる）

```python
    def test_duplicate_and_unopened_listed_together(self):
        self.fix_ready(); self.edit_tree(FIXED)
        reply = load("fix2_ok")
        reply["changes"] += [reply["changes"][0], extra_row(INVENTED)]
        got = self.accept_direct(reply)          # iteration 1・first・state 空・suite 空
        checks = [r["check"] for r in got["rejects"]]
        self.assertFalse(got["ok"])
        self.assertTrue({"duplicate", "not_opened"} <= set(checks), checks)
        self.assertIn(INVENTED, got["reason"])

    def test_scope_and_copy_listed_together(self):
        self.scope_ready(["docs/**"]); self.edit_tree(FIXED)
        reply = load("fix2_ok"); reply["changes"][1]["breaks"]["result"] = "なし"
        with mock.patch.object(self.acc.recount, "accept_fix", wraps=self.acc.recount.accept_fix) as rc:
            got = self.accept_direct(reply)
        self.assertEqual([r["check"] for r in got["rejects"]][:1], ["scope"])
        self.assertIn("copy", [r["check"] for r in got["rejects"]])
        rc.assert_called_once(); self.assertIs(rc.call_args.kwargs["commit"], False)
        self.assertEqual(entry.open_board(self.board).node_state("p3.fix"), "pending")

    def test_tests_and_gates_run_with_form_errors(self):
        # 決め 2: 重なりの誤りが在っても、選んだ試験と事後の関門の束を 1 回ずつ回す
        ... mock check_tests（([], "")）と fixgates.problems（[]）を数え、重なりの返答で両方が 1 回ずつ呼ばれ、拒否に duplicate が載る

    def test_clean_reply_takes_once(self):
        ... fix2_ok で recount.accept_fix（wraps）が 1 回だけ・commit=True・ok True

    def test_last_round_parks_units_bound_by_two_checks(self):
        # 最後の回: mean の行は範囲の外の other.py（scope）、clamp の行は breaks.result「なし」（copy）。2 つの確かめの行が
        # それぞれ別の単位に結べるので、両方を止めて残りで通す（ParkBoundMultiLineCase と同じ盤面の形）
        self.scope_ready(["stats.py"]); self.edit_tree(FIXED)
        (self.repo / "other.py").write_text("x = 1\n", encoding="utf-8")
        reply = load("fix2_ok"); reply["changes"][0]["files"].append("other.py"); reply["changes"][1]["breaks"]["result"] = "なし"
        r = json.loads(self.run_it(reply, INPUTS_ITERATION="3")[1])
        self.assertTrue(r["ok"], r)
        self.assertEqual(sorted(self.parked_units()), sorted([MEAN, CLAMP]))

    def test_last_round_unbindable_line_rejects_whole(self):
        # 最後の回: 重なり（止めない確かめ）と clamp の写しの誤り（止めてよい確かめ）→ 何も止めず全体を拒み、両方を並べる
        ... ok False・done True・parked_units() == []・checks に duplicate と copy・conflicts.json は無いまま
```

- [ ] **Step 2: 落ちることを確かめる**

Run: works/ から `PYTHONDONTWRITEBYTECODE=1 WORKS_TESTSLOT= python3 -m unittest tests.test_fix_accept_all.AllChecksCase`
Expected: FAIL（`KeyError: 'rejects'`。今は最初の確かめの文だけで返す）

- [ ] **Step 3: `accept_fix` と `refuse` を書き換える**（戻して頭から通し直す手 `revert_ruled_units`・最後の回の `drop_excused_units` は今の位置・今の条件のまま。通し直しの結果をそのまま返し、外の `found` は捨てる。docstring の「順は」を「確かめは返さずに表の id で積み、最後に 1 回だけ拒む」に書き直し、各段の「拒む」の語を「積む」に合わせる）

- [ ] **Step 4: 通ることを確かめる**

Run: works/ から `PYTHONDONTWRITEBYTECODE=1 WORKS_TESTSLOT= python3 -m unittest tests.test_fix_accept_all tests.test_blk_fix tests.test_blk_fix_conflict tests.test_fix_gates tests.test_fix_rules tests.test_fix_duty tests.test_duty_sets`
Expected: PASS（`ParkBound*Case`・`TestGiveUpOnBoard`・`test_revert_is_undone_when_the_reply_is_rejected` を含む）

- [ ] **Step 5: Commit**

```bash
git add works/blk-fix/scripts/accept.py works/tests/test_fix_accept_all.py works/tests/test_fix_gates.py works/tests/test_fix_rules.py works/tests/test_fix_duty.py
git commit -m "feat(works): 修正の受け付けが申し出より後の確かめを全部回し、写しの照らしも乾いた形で当てて 1 回の拒否に並べる（224 Task 3）"
```

---

### Task 4: 凍結と書き込みの出どころも積み、申し出は誤りに依らず裁定へ渡す（222f の型）

**Files:**
- Modify: `works/blk-fix/scripts/accept.py`（`accept_fix` の凍結・書き込みの出どころの即 `refuse` をやめて `note`。docstring の -3〜-1 の段と、申し出の継ぎ目の 3 行）
- Test: `works/tests/test_fix_accept_all.py`（class `SeamCase`）

**Interfaces:**
- Consumes: Task 3 の `accept_fix` の並び `found`・`refuse`
- Produces:
  - 凍結（`frozen`）と書き込みの出どころ（`writes`）は `note` して先へ進む。`check_writes` は誤りが在っても `bash_writes` を外した返答を返す（今の `writes.check` の形のまま）ので、後の確かめはその返答を使う。
  - `revert_ruled_units`（`ruled`）は、凍結の誤りを積んだ後でも今の位置で走る（決め 5）。
  - `take_conflicts` は積んだ誤りに依らず走る。1 回目の parked の出口は、積んだ誤りが在っても返す（決め 3）。`ruled` の新しい申し出は ask_human に裁いて積み、拒否の後も残る。

- [ ] **Step 1: 落ちる試験を書く**（`SeamCase(test_blk_fix.BoardCase)`。`acc`・`env`・`accept_direct` は `AllChecksCase` から、`tdd_frozen`・`scope_ready` は `test_blk_fix.TestAccept` から借りる（`tdd_frozen` は `scope_ready` を呼ぶ）。凍結の誤りは `tdd_frozen()` で作るか、`mock.patch.object(self.acc.tddloop, "frozen_problems", return_value=[FROZEN_LINE])` で置く（モジュールの定数 `FROZEN_LINE = "TDD の輪で凍ったテストのファイルを書き換えた: ['test_stats.py']（輪で直した単位のテストは変えない）"`）。申し出は `test_blk_fix_conflict.conflict_on_mean()` と `only_clamp_reply()`。`conflict_items(board) -> list[dict]` は盤面の今の周の `conflict.FILE` の `items`）

```python
    def test_222f_three_classes_in_one_rejection(self):
        # run 222f の 3 回の拒否（凍ったテストのファイル・修正案の範囲・写しの照らし）を、1 回の拒否に並べる
        state = self.tdd_frozen()                                            # test_stats.py を凍らせ、FIXED を当てた木
        (self.repo / "test_stats.py").write_text((self.repo / "test_stats.py").read_text(encoding="utf-8") + "\n# 凍った後の書き換え\n",
                                                 encoding="utf-8")         # 1 回目の型
        (self.repo / "other.py").write_text("x = 1\n", encoding="utf-8")     # 2 回目の型（allowed_paths は stats.py だけ）
        reply = load("fix2_ok"); reply["changes"][0]["files"].append("other.py")
        reply["changes"][1]["breaks"]["result"] = "なし"                     # 3 回目の型（写しの fix_covers_open_units）
        before = sha(self.board / "state.json")
        with mock.patch.object(self.acc, "check_tests", return_value=([], "")), self.env(state=state):
            got = self.acc.accept_fix(reply, self.board, "", self.repo)
        checks = [r["check"] for r in got["rejects"]]
        self.assertFalse(got["ok"])
        self.assertEqual([c for c in self.acc.CHECKS if c in {"frozen", "scope", "copy"}],
                         [c for c in dict.fromkeys(checks) if c in {"frozen", "scope", "copy"}], checks)
        self.assertTrue(any("test_stats.py" in r["text"] for r in got["rejects"] if r["check"] == "frozen"))
        self.assertTrue(any("other.py" in r["text"] for r in got["rejects"] if r["check"] == "scope"))
        self.assertTrue(any(r["text"].startswith(CLAMP[:60]) for r in got["rejects"] if r["check"] == "copy"))
        self.assertEqual(sha(self.board / "state.json"), before)

    def test_frozen_error_does_not_stop_ruled_revert(self):
        # 決め 5: ruled で凍結の誤りが在っても revert_ruled_units は今の位置で呼ばれる（224e の事前審査の穴 3）
        ... frozen_problems を 1 行に、revert_ruled_units を mock（None を返す）にして INPUTS_PASS=ruled → revert が 1 回呼ばれ、拒否に frozen

    def test_first_pass_conflict_reaches_ruling_with_frozen_error(self):
        self.fix_ready(); self.edit_tree(FIXED)
        with mock.patch.object(self.acc.tddloop, "frozen_problems", return_value=[FROZEN_LINE]), self.env():
            got = self.acc.accept_fix(only_clamp_reply([conflict_on_mean()]), self.board, "", self.repo)
        self.assertEqual((got["ok"], got.get("parked")), (True, True), got)
        self.assertEqual([(i["unit_key"], i["status"]) for i in conflict_items(self.board)], [(MEAN, "parked")])

    def test_same_conflict_twice_parks_once(self):
        ... 上と同じ返答を 2 度 → conflicts.json の行は 1 つ

    def test_ruled_pass_conflict_parked_despite_writes_error(self):
        # ruled で書き込みの出どころの誤り（check_writes を mock で 1 行に）と新しい申し出 → 拒否に writes が載り、申し出は
        # ask_human の裁定つきで積まれたまま残る（拒否で巻き戻さない。224e の R2）。同じ返答をもう一度出しても行は 1 つ
        ...
```

- [ ] **Step 2: 落ちることを確かめる**

Run: works/ から `PYTHONDONTWRITEBYTECODE=1 WORKS_TESTSLOT= python3 -m unittest tests.test_fix_accept_all.SeamCase`
Expected: FAIL（凍結・書き込みの出どころが即返すので、`test_222f_…` は frozen だけ・`test_first_pass_…` は ok False・`test_ruled_pass_…` は申し出が積まれない）

- [ ] **Step 3: 凍結と書き込みの出どころを積む形にする**

- [ ] **Step 4: 通ることを確かめる**

Run: works/ から `PYTHONDONTWRITEBYTECODE=1 WORKS_TESTSLOT= python3 -m unittest tests.test_fix_accept_all tests.test_blk_fix tests.test_blk_fix_conflict tests.test_blk_fix_tdd tests.test_fix_rules tests.test_fix_duty tests.test_writes` と `WORKS_TESTS=fast sh tests/run.sh`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add works/blk-fix/scripts/accept.py works/tests/test_fix_accept_all.py
git commit -m "feat(works): 凍ったテストと書き込みの出どころの誤りも積み、食い違いの申し出は誤りに依らず裁定へ渡す（224 Task 4）"
```

---

### Task 5: 226 に載せ直して控えの分かれと合わせる・CHANGELOG・仕上げ

226 が `wip/works-next` に入った後に行う。236 が入っていれば同じく載せ直す。

**Files:**
- Modify: `works/blk-fix/scripts/accept.py`（載せ直しの衝突の解き。226 の `conflict.waiting` の分かれを「`found` が空の時だけ `hold_fix`」にし、`found` が在れば `recount.accept_fix(…, commit=False)` を当てて `refuse(found)`。受けた時の trace は 226 の `traced()` のまま）
- Modify: 236 が修正の受け付けの id の表を別に置いていれば、その表と `CHECKS` を 1 つにする（236 の置き場に見出しと止めてよいかを足し、`accept.py` はそれを読む）
- Modify: `works/CHANGELOG.md`（`[Unreleased]` の `### Changed`）
- Test: `works/tests/test_fix_accept_all.py`（class `HoldCase`）

**Interfaces:**
- Consumes: 226 の `conflict.waiting(b)`・`named_reply(reply, board)`・`hold_fix(named, whole, b, traced)`・`conflict.HELD_REPLY`、Task 1〜4 の物
- Produces:
  - `unitrows.take` の後の順: `named = named_reply(reply, board) if conflict.waiting(b) else None` → `found` が空で `named` が在れば `hold_fix` → それ以外は `recount.accept_fix(…, commit=not found and named is None)` → 拒否なら `copy` を積む → `found` が在れば `refuse(found)`。`named` が在るのに `found` が空でない時は控えない（決め 8）。
  - CHANGELOG の 1 項目（下書き）: 「修正の受け付けは、確かめの途中で返さずに全部（凍ったテスト・書き込みの出どころ・申し出の形・.archon/ の下・単位の key・外れた単位・修正案の範囲・選んだ試験・事後の関門の束・写しの照らし）を回し、誤りを確かめごとの見出しの下に 1 回の拒否で並べる。出口に行ごとの確かめの id（`rejects`）を足した。写しの照らしは、拒む時も盤面に保存せずに当てる（`DiskBoard.vet`）。食い違いの申し出は、ほかの誤りに依らず裁定へ渡し、拒否で巻き戻さない。3 回拒まれたら諦める決まりと、最後の回に単位に結べる誤りだけでその単位を止める決まりは今のまま」

- [ ] **Step 1: 載せ直す**

```bash
git fetch . wip/works-next && git rebase wip/works-next
```

衝突は `accept.py` の `accept_fix` の末（226 の `traced()`・`hold_fix` と 224 の `found`）と、試験の mock の引数に出る見込み。上の Produces の順で解く。

- [ ] **Step 2: 落ちる試験を書く**

```python
class HoldCase(test_blk_fix.BoardCase):
    def test_waiting_board_rejects_instead_of_holding(self):
        # 226 の待つ単位が在る盤面（conflict.waiting を真に、named_reply を返答そのままに置く）で、重なりの誤りが在る返答
        # → 控えずに拒む（hold_fix を呼ばない・HELD_REPLY を書かない）。写しの照らしは commit=False で 1 回
        ...

    def test_waiting_board_holds_clean_reply(self):
        # 同じ盤面で誤りの無い返答 → 今どおり hold_fix（recount.accept_fix は呼ばない）
        ...
```

- [ ] **Step 3: 落ちることを確かめ、解きを直して通す**

Run: works/ から `PYTHONDONTWRITEBYTECODE=1 WORKS_TESTSLOT= python3 -m unittest tests.test_fix_accept_all.HoldCase`
Expected: 解く前の形によっては FAIL（`found` が在っても控える）。解いた後は PASS

- [ ] **Step 4: 全部の焦点と柵を通す**

Run: works/ から `PYTHONDONTWRITEBYTECODE=1 WORKS_TESTSLOT= python3 -m unittest tests.test_fix_accept_all tests.test_blk_fix tests.test_blk_fix_conflict tests.test_blk_fix_tdd tests.test_fix_gates tests.test_replan tests.test_fix_rules tests.test_fix_duty tests.test_duty_sets tests.test_entry` と `WORKS_TESTS=fast sh tests/run.sh` と `sh ~/.cache/works-dogfood/rootfences.sh`
Expected: PASS・失敗 0

- [ ] **Step 5: Commit**

```bash
git add works/blk-fix/scripts/accept.py works/tests/test_fix_accept_all.py works/CHANGELOG.md
git commit -m "feat(works): 待つ単位の控えは誤りの無い返答だけにし、誤りが在れば写しの照らしも並べて拒む（226 との継ぎ目）。CHANGELOG（224 Task 5）"
```

---

## この計画が扱わない物

- ほかのブロックの受け付けを積む形に寄せること（決め 9）。調べた一覧: `blk-plan/lib/planblk.py:take`（narrows の欠け → 直す義務に無い単位 → 盤面）と `with_plan_fields`（欄の欠け）・`.shared/core/refix.py:accept_review`・`blk-judge/lib/judgetake.py:take`・`.shared/core/accept.py:check_judge`・`blk-pr/scripts/accept.py:take`・`blk-premises/scripts/accept.py`・`.shared/core/purpose.py:check_purpose`・`blk-material/lib/material.py:take`・`.shared/core/rejudge.py:take`・`.shared/core/ci_role.py:take`・`blk-spec/lib/specblk.py:take`・`blk-eyes/lib/eyes.py:accept`・`blk-report/lib/report_roles.py:accept`・`.shared/core/design.py:check_design`・`blk-fix/lib/ruling.py:accept_rule`（型の後は既に全部を溜める）・`blk-fix/lib/tddloop.py:step`（段の分かれは段ごとに読む物が違うので意図した物）。全部を溜めるのは `blk-structure/lib/eye.py:accept` だけ。
- 写しの `FIX_REJECT_HEADING` の置き場・`reject_with_problems` の「唯一の置き場」の語・`_run_query` の試験（224d の副題。224e で外した）。
- 拒否を run をまたいで数えること（236）。
- 自分食いの run の pack の写し（`.archon/workflows/works`）は、版を固める段の物で、この計画では触らない。
