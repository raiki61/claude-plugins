# 修正の輪の最後の回は単位を止めるだけで、盤面を止めない（依頼 242「止まった run も仕事を捨てない」）Implementation Plan

状態: 入れた（works 0.2.25。`blk-fix/lib/parking.py`）。

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** works（このリポジトリの `works/` に在るプラグイン。外の道具 Archon の上で、人の修正依頼を AI の役に直させる工程 darkfactory を回す）の修正の段（AI の修正役が返した直しを、機械が確かめてから受ける段）で、修正役の 3 回目の返答も拒む時に、拒否の行を直す単位（判定役が切った 1 つの欠陥）に結んで、その単位だけを止めて持ち越す。受けた単位は残し、工程は差分の審査・最後の人の関所・報告まで進む。

**Architecture:** 決まりは 1 つ。「最後の回の拒否の行は、証拠が名指す単位に結ぶ。結べない行は直す義務の全部の単位に結ぶ。結んだ単位のうち義務の内の物は止めて持ち越し、義務の外の単位にだけ結んだ行は拒否に数えない」。止める単位を選ぶ仕事は新しい lib `works/blk-fix/lib/parking.py` の純な関数が持ち、受け付けのスクリプト `works/blk-fix/scripts/accept.py` はそれを 1 か所で呼ぶ。今の受け付けに在る、止めない行の表・共有のファイルでの諦め・戻す手の取り消し・外れた単位の行の別の道は消える。

**Tech Stack:** Python 3.12（標準ライブラリだけ）、unittest、git

**Spec:** 依頼 242（works を works 自身の修正に使う「自分食い」の依頼に振る連番の 242 番）。本文の要る所は、この文書の「この文書の読み方」「根本の原因」「決めたこと」に全部書き写した。

## この文書の読み方（初めて読む人向け。本文の語はここで全部定める）

読み手: この計画の Task を 1 つずつ実装する AI の役（実装役）と、それを審査する役。どちらもリポジトリ claude-plugins の作業ツリー `/Users/p03623/src/claude-plugins-work1-sdd17`（枝 `wip/sdd-242`。起点の commit 20d784a8 = works の版 0.2.23）を手元に持つ。本文の「今」は起点の commit のコードの振る舞いで、名指したファイルが正本。

番号と名:
- 依頼 241: 先に入った自分食いの依頼。裁定で外れた単位の 1 回目の直しを、作業ツリーから戻さないようにした（計画は `works/docs/plans/2026-10-03-held-units-exit.md`）。
- run 195f・195d・195c・222・226b・184・222f: 自分食いの run の名（依頼の番号と試みの印）。各 run で何が起きたかは、この文書の節「根本の原因」に書いた。

置き場と道具:
- パスは、断りが無ければ `works/` からの相対。`accept.py:541` はそのファイルの 541 行目（起点の版）。
- 盤面: run ごとの状態の置き場（`$ARTIFACTS_DIR/board/`）。工程の節（`p3.fix` は修正の節）は 1 周に 1 度だけ返答を受ける。盤面を止めると（`b.stop(理由, by=...)`）後ろの段は境の節（ブロックの間で盤面を読んで次を決める節）が飛ばし、報告の結末は `stopped_by_line` になる。
- 修正の段: 修正のブロック `blk-fix/`（節を並べた YAML `blk-fix.yaml` と、その script と lib）。1 回の run に 2 度起きることがある（1 回目の段と、裁定の後の 2 回目の段。同じブロックの 2 度目の include）。
- 段の頭の木: 修正の段の最初の節 ignored-before が走った時の作業ツリーの姿（git の木の sha）。2 回目の段は自分の物を持つ。
- 写し: `.shared/core/graphloops/` は本流 graphloops（別のプラグイン）のバイト単位の写し。この計画は変えない。写しの受け付け（盤面の `p3.fix` の型と規則）の拒否の文は、単位の行なら頭に `unit_key[:60]` を置く。
- 試験の段: `tests/tiers.py` が試験の模块を FAST（速い段）と HEAVY（重い段）に分ける。
- 根の柵: リポジトリの根の試験の一式 `sh ~/.cache/works-dogfood/rootfences.sh`。

修正の段の語:
- 修正役: 直す役の AI。返答の `changes` に、直した単位ごとに 1 行（`unit_key`・`files`・`what` など）を書く。
- 修正の受け付け: `blk-fix/scripts/accept.py` の `accept_fix`。確かめを全部回し、拒否の行を表 `CHECKS` の id（frozen・writes・conflict・pack・duplicate・not_opened・accepted・excused・scope・tests・gates・copy）で積み、最後に 1 回だけ拒む。
- 輪: 拒まれた修正役は同じ会話で出し直す。上限 3 回（`GIVE_UP_AFTER`）。3 回目が「最後の回」。
- 直す義務・義務の外: `conflict.fix_duty(b)`（`.shared/core/conflict.py`）が返す (owed, excused)。owed が直す義務の単位。excused は義務の外の単位 {key: 理由}（答え待ちの問いの出どころ・裁定 ask_human か fix_plan_item を受けた単位・2 回目の段では 1 回目に受け付けた単位）。
- 止める（park）: 単位の直しを作業ツリーから戻して控えの patch（盤面の `fix-parked-<n>.patch`）に残し、`conflict.park` で裁定 ask_human（人に回す）を付けて義務の外にする。止めた単位は最後の人の関所（final-gate）と報告に並び、次の run の依頼の下書き `next-request.json` に裁定の文のまま載る（`.shared/core/report.py` の `next_request` の「人に回した単位」の行。今ある道）。
- 足跡: 単位が今の段で触ったパスの集合 = 返答の行の `files` ∪ 今の段の TDD の輪の状態（`tddloop.states(board)`。単位ごとに `files`・`test_files`）の物。
- 届く試験: 単位の足跡を起点にした `impact.map(repo, rev, seeds=足跡)` の `tests`（import と言及を逆に辿って届くテストのファイル。`.shared/core/impact.py`）。
- TDD の輪: 修正役の前に、単位ごとにテストを先に書いて赤を確かめ、直して緑を確かめる段（`blk-fix/lib/tddloop.py`）。緑にした単位のテストのファイルを凍らせる（`frozen`・`frozen_tree`）。
- keep-essence: `docs/keep-essence.md` の、どの作りでも残す works の 11 の仕組み。

## 根本の原因

証拠の置き場（自分食いの機械の上。要る所はこの節に書き写した）: `~/.cache/works-dogfood/detached/run-<名>.log`、盤面 `/private/var/folders/sz/ry75t4r93s9d8bhdfb248gbn7z3rwq/T/works-dev/archon-home/workspaces/run-<名>/origin/artifacts/runs/<id>/board/`（195f・195d だけ残る。0.2.23 からは拒否の文は `fixing/reject-accept_fix-*.txt`）、`~/.cache/works-dogfood/boards/run-<名>/`（古い run は `state.json` の `stop.reason` だけ）。

依頼 242 が挙げた 9 本の run のうち、文「3 回拒まれ、どの単位にも結べない拒否で諦めた」で盤面が止まったのは 6 本（194 は人が関所で止め、175-a2・180-g1 は止まっていない）。6 本の最後の回の行と、結べなかった訳:

| run | 最後の回の行 | 結べなかった訳 | 失った単位 |
|---|---|---|---|
| 195f | tests 1 | 文が試験を点の名で言う | 6（受けた 0） |
| 195d | conflict 1・tests 1 | conflict は止めない表 | 4（全部義務の外） |
| 195c | scope 2 | 外れた単位の輪の残り | 義務の 3 |
| 222 | copy 1 | 共有のファイルで諦め | 5 |
| 226b | conflict 1 | conflict は止めない表 | 1（義務の外） |
| 184 | copy 1 | 共有のファイルで諦め | 4 |

訳の中身:
- tests（195f・195d）: 文は `tests.test_report.HeadCase::test_…` のような点の名で試験を言い、テストのファイルのパスも、どの単位の `files` も名指さない。今の結び（`accept.bind_problems`）は文の中の `unit_key` か `changes[].files` のパスしか引かないので、赤の試験は必ず結べない。証拠は在る: 195f の赤の試験 `tests/test_report.py` は import で `report.py`・`scopes.py` に届き、それを触った単位が在る。195d の赤 11 件は、外れた単位 build の TDD の輪の受け入れのテスト（輪の状態の `test_files`）。
- conflict（195d・226b）: 申し出の対象は、もう ask_human で義務の外の単位。表 `CHECKS` で conflict は「止めてよくない」なので、結ぶ前に諦める。
- scope（195c）: 外れた単位の TDD の輪が書いたファイルが作業ツリーに残り、返答の行に無いので結べない（依頼 241 の後は範囲がこの行を出さないが、同じ型の行は義務の外の単位の物）。
- copy（222・184）: `unit_key[:60]` で 1 単位に結べたが、その単位がファイルをほかの単位と共にするので `park_bound_units` が None を返して諦めた。195f も結べていれば同じ訳で諦めた（`report.py` を 4 単位が共にする）。
- 依頼の一覧の外の run 222f: 写しの返答そのものの欄の行（`p3.fix: 修正案の事前審査への応答が揃わない`）。単位の行でない。

どの run でも、諦めると `blk-fix/scripts/assert_changed.py` が盤面を止め（by `works:fix`）、受けた単位も含めて直しは作業ツリーに残ったまま審査されず、報告は「止まった」としか言わない。

答え（根本）: 最後の回の扱いが「全部の行がちょうど 1 単位に結べ、止めてよい表の確かめで、ファイルを共にしない時だけ止める。ほかは盤面を止める」という、出口の多い形になっている。出口ごとに場合を足してきた（表の真偽・`drop_excused_units`・`_held_files`・戻す手の取り消し）。そのどれでもない形の行が来るたびに盤面が止まる。

## 決めたこと（どれも 1 つの軸「目的と keep-essence を保って全体がより簡潔か」で選んだ）

関わる keep-essence は 3（テストの凍結）・4（3 回拒まれたら、作業ツリーをその単位を始めた時の版に戻し、理由を残す）・6（受け付けで変更に当たる試験を回す）。この計画は 4 を、TDD の輪だけでなく修正の受け付けにも同じ形で当てる。

- **決め 1（決まりは 1 つ）:** 最後の回の行を `parking.bind` で単位の集合に結ぶ。結び先は、文が名指す `unit_key`（か `unit_key[:60]`）と、文が名指すパスを足跡か届く試験に持つ単位の和。空なら直す義務の全部の単位（理由を名指す）。結び先から義務の外の単位を引いて残った単位を止める。残らない行は拒否に数えない。止めた単位は義務の外になるので、受け付けを頭から通し直すと同じ行は数えずに済み、通し直しは必ず終わる。
  - これで消える物: 表 `CHECKS` の真偽の列と `parkable()`、`park_bound_units` の None の出口、`_held_files`、`unrevert_units` と戻す手（`undo`）と PARK_UNDONE_OP、最後の回の `drop_excused_units` の別の道（義務の外の単位の行を外すのは同じ決まりの半分になる）、`bind_problems` の「ちょうど 1 単位」。
  - 足す分かれは無い。止めてよくない確かめも、行が結べる単位で同じに扱う（duplicate・not_opened・conflict は文が `unit_key` を名指す。pack は誰にも結べないので義務の全部）。
- **決め 2（試験の赤の結び）:** tests の行はテストのファイルごとに 1 行にし、文にテストのファイルのパス（根からの相対）を書く。結びは決め 1 のパスの結びと同じ 1 本で、TDD の輪の `test_files`（足跡）と、import で届く試験（届く試験）がそのパスを持つ単位に結ぶ。traceback の中のパスは使わない（同じファイルを共にする単位は決め 3 でどうせ一緒に止まり、精度が上がらない）。
- **決め 3（ファイルの共有）:** ファイルは単位ごとに分けて戻せない。だから止める単位と今の段の足跡を共にする単位も一緒に止める（共有の閉包）。今は諦めていた形（222・184・195f）が、その組だけを止める形になる。義務の外の単位（依頼 241 で作業ツリーに残す外れた単位の直し）が閉包に入れば、そのファイルの直しも控えの patch に移り、止める単位の文にその名を載せる。何も消えない。
- **決め 4（戻す先は段の頭の木）:** 止めた単位の足跡は段の頭の木に戻す。今のように修正前の版や `frozen_tree` には戻さない。凍ったテストのファイルも戻すので、止めた単位の受け入れのテストが作業ツリーに赤のまま残らない。2 回目の段の頭の木は 1 回目に受けた直しを含むので、それを壊さない（今の `_held_files` の守りが要らなくなる）。凍結の行（frozen）は止めた単位に結ぶので数えない。keep-essence 4 の「その単位を始めた時の版に戻す」と同じ形。
- **決め 5（最後の土台）:** 義務の単位を全部止めても写しが返答を受けない時がある（222f の返答の欄の行）。その時は役の返答を捨て、機械の空の返答（`entry.empty_fix_reply`。境の節 h-plan が直す物の無い周に渡す物と同じ）を渡す。修正案の事前審査が在る周は、その穴と別案に `declared`（残す理由 = 止めた事実）で答える。これで受け付けは最後の回に必ず通る。`assert_changed.py` の「受け付けが通らないまま輪を抜けた」の出口（`GiveUp` を投げる所）と、`collect.py` の受け付けの ok: false の分かれを消す。
- **決め 6（結末は新しい語を作らない）:** 止めた単位は ask_human の単位なので、結末は今の `needs_human`（直さずに残した単位が在る）になる。差分を対象に当てる口 `use.sh apply` は `needs_human` の差分を当てるので、受けた単位は使える。部分であることは、報告の冒頭の 1 行目と最後の関所の冒頭の 1 行目に「受けた単位・止めて持ち越した単位」を名指して書く。
- **決め 7（変えない物）:** 写しと本流の graphloops。`assert_changed.py` のほかの止め（申告が空・申告したファイルが変わっていない）。最後の回でない回の拒否（全部を並べて出し直させる）。1 回目の段の申し出を裁定へ渡す出口（`take_conflicts` の parked）。案の直しを待つ返答の控え（`hold_fix`）。`darkfactory/lib/line_edge.py` の止まりの伝わり方（盤面が止まらなくなるだけ）。

## Global Constraints

- 期限・タイムアウトを新しく足さない（定数・引数・YAML のどれにも）。
- 写し `.shared/core/graphloops/` と本流の `graphloops/` は変えない。写しの台帳 `.shared/core/COPIED_FROM` に行を足さない。
- keep-essence の 3・4・6 の確かめは弱めない（凍結・選んだ試験の赤は最後の回でも行として出し、単位を止める理由になる）。
- 新しい模块は `blk-fix/lib/parking.py` の 1 つだけ。試験の模块は足さない（`tests/tiers.py` を変えない）。試験はどれも `unittest.TestCase` のクラスの中に置く。
- 注記・docstring・拒否の文・報告の文は日本語。Python 3.12 が下限。標準ライブラリだけ。
- 試験は、各 Task では触った模块だけを回す: `works/` から `PYTHONDONTWRITEBYTECODE=1 WORKS_TESTSLOT= python3 -m unittest tests.<module>[.<Class>]`。速い段（`WORKS_TESTS=fast sh tests/run.sh`）と根の柵は最後の Task で 1 回だけ回す。
- CHANGELOG は `CHANGELOG.md` の `[Unreleased]` だけに足す。版は上げない。
- commit のメッセージは日本語で、末尾に `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`。push はしない。

## Review Focus

1. 止めた単位が TDD の輪で緑にした単位で、受け入れのテストのファイルを受けた単位と共にする → 共有の閉包で両方止まり、テストのファイルは段の頭の木に戻り、受け付けは空の `changes` で通る（一方だけを戻して赤を残さない）。（Task 1 の `test_shared_test_file_parks_both_and_leaves_no_red`）
2. 2 回目の修正の段で止めた単位が、1 回目に受けた単位とファイルを共にする → 1 回目の直しは段の頭の木に在るので残り、2 回目の段の変更だけが patch に入る。（Task 1 の `test_second_pass_park_keeps_first_pass_work`）
3. 修正役が `.archon/`（Archon の置き場。動いている工程の写しが在る）の下を変えた最後の回（pack の行は誰にも結べない）→ 義務の全部を止め、`.archon/` の下は戻さず、受け付けは通る。（Task 1 の `test_pack_row_parks_all_and_never_touches_archon`）
4. 義務の単位を全部止めても、修正案の事前審査への応答が欠けた返答 → 機械の空の返答で通り、境の節 h-mid は役の修正と数えない（差分の審査は空の差分を回さない）。（Task 2 の `test_reply_level_rows_hand_the_machine_empty_reply`）
5. 止めた単位の控えの patch のパスが、次の run の依頼の下書きと最後の関所の文の両方に字のまま載る（人が後で当て直せる）。（Task 3 の `test_parked_patch_reaches_next_request_and_gate`）

---

### Task 1: 最後の回は行を単位に結んで止め、受けた単位で通す（195f の型）

**Files:**
- Create: `blk-fix/lib/parking.py`
- Modify: `blk-fix/scripts/accept.py`（`CHECKS` の値を見出しの文字列だけにする・`accept_fix` の `parkable`・`refuse`・`excused` の分かれ（648-657 行）・`bind_problems`（446-461）・`revert_units`（464-486）・`unrevert_units`（489-494）・`_held_files`（515-531）・`drop_excused_units`（534-538）・`park_bound_units`（541-579）・PARK_UNDONE_OP（117）・docstring の 29-31・62-63・78-85 行）
- Modify: `blk-fix/lib/tddloop.py`（`selected_problems` の赤の文をテストのファイルごとの行にする。`snapshot` を `leftovers` へ移して名を残す）
- Modify: `blk-fix/lib/planscope.py`（27 行の docstring の名指しだけ）
- Modify: `.shared/core/leftovers.py`（`snapshot` を受け、`record_ignored` が段の頭の木を控える）
- Test: `tests/test_fix_accept_all.py`（新しい class `StopsKeepWorkCase`。既存の直しは Step 5）
- Test（既存の直しだけ）: `tests/test_blk_fix.py`・`tests/test_fix_rules.py`・`tests/test_fix_duty.py`・`tests/test_blk_fix_conflict.py`・`tests/test_writes.py`・`tests/test_tdd_outside.py`

**Interfaces:**
- Consumes: `conflict.fix_duty(b) -> (set, dict)`・`conflict.park(b, rows, *, source, ruling)`・`conflict.write_rulings(b)`・`impact.map(repo, rev="HEAD", seeds=(), diff=False, cache_dir=None) -> dict`（欄 `tests`）・`impact.tree_files(repo)`・`impact.is_test(path)`・`impact._junit_module(case)`・`impact._mod(name)`・`tddloop.states(board) -> list`・`tddloop.load_state(p) -> dict`・`tddloop.restore_paths(repo, tree, paths)`。試験の手助け（どれも `tests/` に在る）: `test_blk_fix.BoardCase`（種の git と盤面を試験ごとに作る。`fix_ready`・`edit_tree`）・`test_blk_fix.TestAccept.run_it`（受け付けのスクリプトを子のプロセスで起こす）・`test_blk_fix.ParkBoundBase.parked_units`（trace の止めた単位）・`test_blk_fix.TestGiveUpOnBoard.changed`（assert-changed を起こす）・`test_blk_fix_tdd.SUITE`（小さな試験の実行器の本文）・`test_blk_fix_tdd.OPEN`・`test_blk_fix.load("fix2_ok")`（修正役の返答の見本。行は MEAN と CLAMP）・`test_blk_fix.MEAN`・`CLAMP`（種の `stats.py` の 2 つの単位の key）
- Produces:
  - `parking.footprint(rows: list[dict], loop_states: list, repo) -> dict[str, set[str]]` — 単位の key → 足跡（根からの相対パス。`.archon/` の下は入れない）
  - `parking.reach(repo, rev: str, files: set[str], cache_dir) -> set[str]` — 届く試験（`impact.map(...)["tests"]`。`files` が空なら空）
  - `parking.bind(text: str, keys: set[str], feet: dict[str, set[str]], reached: dict[str, set[str]]) -> set[str]` — 文が名指す単位の集合（決め 1・2。パスの名指しは今の `bind_problems` と同じ境の正規表現）
  - `parking.unbound_why(text: str) -> str` — 結べない行の理由の文（「行が単位の key も、どの単位の足跡・届く試験のパスも名指さない」に、文が名指した根からのパスを添える）
  - `parking.closure(keys: set[str], feet: dict[str, set[str]]) -> set[str]` — 足跡を共にする単位を辿った閉包
  - `class parking.Settlement(NamedTuple)`: `park: dict[str, list[str]]`（止める単位 → 理由の文の列）・`absorbed: list[str]`（数えない行の文）・`unbound: dict[str, str]`（結べなかった行の文 → 理由）・`files: set[str]`（戻すパス = 閉包の足跡 ∪ 結べなかった行が名指した、足跡の外の変わったパス。`.archon/` の下は除く）
  - `parking.settle(texts: list[str], *, keys: set[str], feet, reached, owed: set[str], out_of_duty: set[str], changed: set[str]) -> Settlement`
  - `leftovers.snapshot(repo) -> str`（`tddloop.snapshot` から移す。`tddloop.snapshot` は同じ物の別名として残す）
  - `leftovers.head_tree(board, before_name: str = IGNORED_BEFORE_FILE) -> str | None` — `record_ignored` が `fix-ignored-before.json` に書いた欄 `head_tree`。無ければ None（古い盤面。呼び手は修正前の版の木に倒す）
  - `accept.CHECKS: dict[str, str]`（id → 見出し）。`accept.note` と `found`（`(id, 文)` の列）の形は今のまま
  - `accept.PARKED_OP = "fix_bound_parked"`（今の BOUND_PARKED_OP を名替え。値は同じ。行の欄は `unit_keys`・`patch`・`reasons`（{key: [文]}）・`unbound`（{文: 理由}））、`accept.ABSORBED_OP = "fix_excused_dropped"`（今の EXCUSED_DROPPED_OP を名替え。欄 `dropped`（行を外した義務の外の単位の key）・`absorbed`（数えなかった文））
  - `accept.revert_units(board, base_rev, repo, files: set[str]) -> str`（控えの patch のパス）
  - 最後の回の `accept_fix` の返りは、Task 2 の土台を除けば必ず `ok: True`

- [ ] **Step 1: 落ちる試験を書く（195f の型。言うことを聞かない修正役）**

`tests/test_fix_accept_all.py` に `StopsKeepWorkCase(test_blk_fix.BoardCase)` を置く。手 `reddening_fixer(self) -> tuple[str, dict]`（(輪の状態のファイル, 返答)）の組み方:
1. `linekit.seed_repo` を `mock.patch.object` で包んで `self.fix_ready()` を呼ぶ。包みの中で、本物の種の後に `bounds.py`（定数 `BOUNDS` = `def width(lo, hi):\n    return hi - lo\n`）と `test_bounds.py`（`from bounds import width` と `TestBounds.test_width`: `width(2, 5) == 3`）を書いて `linekit.git(repo, "add", "-A")`・`linekit.git(repo, "commit", "-q", "--amend", "--no-edit")`。二つは修正前の版で緑。
2. `self.tmp / "suite.py"` に `test_blk_fix_tdd.SUITE` を書き、`tddloop.start(self.board, self.repo, str(suite), test_blk_fix_tdd.OPEN)` の `go` が真。route の段で MEAN と CLAMP を両方 direct にする（`why` は 10 字以上）。
3. 言うことを聞かない修正役（3 回とも同じ木・同じ返答）: `edit_tree` は mean の 1 か所（`"sum(xs) / (len(xs) - 1)": "sum(xs) / len(xs)"`）だけ。`bounds.py` を `return lo - hi` に書き換える（既存の `test_width` が赤になる）。返答は `load("fix2_ok")` の MEAN の行（`files` は `["stats.py"]`）と、CLAMP の行の `files` を `["bounds.py"]` に替えた物。

```python
class StopsKeepWorkCase(test_blk_fix.BoardCase):
    """run 195f の型: 修正役の直しが既存の試験を赤にし、3 回とも同じ返答を出す。最後の回は赤の試験を import で届く単位に結び、
    その単位だけを止めて持ち越し、受けた単位で通す。盤面は止まらない"""

    run_it = test_blk_fix.TestAccept.run_it
    parked_units = test_blk_fix.ParkBoundBase.parked_units
    changed = test_blk_fix.TestGiveUpOnBoard.changed

    def test_reddened_existing_test_parks_its_unit_and_keeps_the_rest(self):
        state, reply = self.reddening_fixer()
        for it in ("1", "2"):
            r = json.loads(self.run_it(reply, INPUTS_ITERATION=it, INPUTS_TDD_STATE=state)[1])
            self.assertEqual((r["ok"], r["done"]), (False, False), r)
            self.assertIn("test_bounds.py", r["reason"], "赤の行はテストのファイルのパスを名指す")
        r = json.loads(self.run_it(reply, INPUTS_ITERATION="3", INPUTS_TDD_STATE=state)[1])
        self.assertEqual((r["ok"], r["done"]), (True, True), r)
        self.assertEqual([c["unit_key"] for c in r["changes"]], [MEAN], "受けた単位は残る")
        self.assertEqual(self.parked_units(), [CLAMP], "赤の試験 test_bounds.py は bounds.py を触った CLAMP にだけ届く")
        self.assertEqual((self.repo / "bounds.py").read_text(encoding="utf-8"), BOUNDS, "止めた単位は段の頭の木に戻る")
        self.assertIn("sum(xs) / len(xs)", (self.repo / "stats.py").read_text(encoding="utf-8"))
        patch = next(self.board.rglob("fix-parked-1.patch")).read_text(encoding="utf-8")
        self.assertIn("return lo - hi", patch, "止めた直しは控えに残る")
        b = entry.open_board(self.board)
        self.assertFalse(b.state.get("stop") or b.state.get("halted"), "盤面は止まらない")
        self.assertIn(CLAMP, conflict.fix_duty(b)[1], "止めた単位は義務の外（ask_human）")
        self.assertIs(json.loads(self.changed(r)[1])["ok"], True)
```

同じ class に、Review Focus の 3 本と結びの 2 本を置く:
- `test_shared_test_file_parks_both_and_leaves_no_red`: route の段で MEAN を tdd にして輪で緑にする（`test_blk_fix_tdd.LoopCase` の `route`・`red`・`fix_mean` と同じ 3 つの `tddloop.step`。凍ったファイルは `test_stats.py`）。CLAMP の行の `files` を `["stats.py", "test_stats.py", "bounds.py"]` にし、`bounds.py` を赤にする。最後の回は `ok` 真・`changes` 空・止めた単位は MEAN と CLAMP の両方・`test_stats.py` と `stats.py` と `bounds.py` が修正前の版の中身。3 回目の拒否の行に frozen と tests が在っても通る。
- `test_second_pass_park_keeps_first_pass_work`: `test_blk_fix_conflict.ReplanCase`（`fix_plan_item` に裁いた盤面を作る手）で、1 回目に MEAN を受けた控えが在る 2 回目の修正の段（`INPUTS_PASS=ruled`）を作り、2 回目の段の頭の木を `leftovers.record_ignored` で控えた後に CLAMP の行を `bounds.py` で赤にする。最後の回は CLAMP だけを止め、`stats.py` の 1 回目の mean の直しが残る。
- `test_pack_row_parks_all_and_never_touches_archon`: `test_blk_fix.TestAccept` の pack の試験と同じ形で `.archon/` の下を変えた返答の最後の回。`ok` 真・止めた単位は義務の全部（MEAN・CLAMP）・`PARKED_OP` の行の `unbound` に pack の文が在る・`.archon/` の下は変えたまま。
- `test_red_test_binds_by_import_closure`（`parking` を直に呼ぶ）: `feet = {MEAN: {"stats.py"}, CLAMP: {"bounds.py"}}`、`reached` は各単位の `parking.reach` で引いた物。テストのファイル `test_bounds.py` を名指す文の `parking.bind` は `{CLAMP}`、`test_stats.py` を名指す文は `{MEAN}`、頭に `CLAMP[:60]` を置く文は `{CLAMP}`。
- `test_unbound_row_parks_every_owed_unit_and_says_why`: `parking.settle(["誰も名指さない文"], keys={MEAN, CLAMP}, feet=…, reached=…, owed={MEAN, CLAMP}, out_of_duty=set(), changed=set())` の `park` の鍵が両方で、`unbound` の理由が `parking.unbound_why` の文。`out_of_duty={CLAMP}` で CLAMP だけを名指す文は `absorbed` に入り、`park` は空。

- [ ] **Step 2: 落ちることを確かめる**

Run: `works/` から `PYTHONDONTWRITEBYTECODE=1 WORKS_TESTSLOT= python3 -m unittest tests.test_fix_accept_all.StopsKeepWorkCase`
Expected: 主の試験は 3 回目に FAIL（`(ok, done)` が `(False, True)`。今の `bind_problems` は点の名の試験を結べず、返答全体を拒む = 195f と同じ）。`parking` を呼ぶ試験は ImportError。主の試験が別の理由で落ちたら、盤面の組み方を直してから進む。

- [ ] **Step 3: `leftovers.snapshot`・`leftovers.head_tree` と、`record_ignored` の欄 `head_tree`**

`tddloop.snapshot` の本体を `leftovers.snapshot` へ移し、`tddloop.snapshot = leftovers.snapshot`。`record_ignored` は控えの dict に `"head_tree": snapshot(repo)` を足す。返りの形は今のまま。

- [ ] **Step 4: `parking.py` と、`accept.py` の最後の回を 1 本にする**

`tddloop.selected_problems` は、元で赤でなかった赤をテストのファイルごとに 1 行にする。文は今の文の頭と「（ファイル <根からのパス>）: [そのファイルの id]」。ファイルは、赤の case の `impact._junit_module` が `impact._mod(p)` に等しいテストのファイル（`impact.tree_files` と `impact.is_test` で引く）。見つからなければ今と同じ 1 行（パスを名指さない。誰にも結べない）。返りの形 `(list[str], str)` は変えない。

`accept_fix` の最後の回の決まり。下が手順の正本で、これ以外の分かれを足さない:
1. 確かめ -3〜1e は今のまま積む。`excused` の行は最後の回も積む（今の 648-657 行の分かれを消し、いつも `note(found, "excused", …)`）。
2. 積んだ行が在り最後の回なら、返答の行（名前に戻した `changes`）と `tddloop.states(board)` から `parking.footprint`、各単位の `parking.reach`（rev は `writes.base_rev`、cache は輪の状態の `work` の下の `impact`。輪が無ければ盤面の今の scope の置き場の `impact`）を組み、`conflict.fix_duty` の (owed, excused) で `parking.settle` を回す。`keys` は盤面の単位の key と返答の key の和、`changed` は `writes.changed(repo, rev)`。
3. `settle.park` が空でなければ止める: `revert_units` が `settle.files` の今の木との差分を `fix-parked-<n>.patch` に控えてから（今の控えの書き方のまま）、段の頭の木（`leftovers.head_tree`。None なら修正前の版の木）へ `tddloop.restore_paths` で戻す。止める単位ごとに今の `park_bound_units` と同じ形で `conflict.park`（裁定 ask_human・文は `BOUND_PARKED` + 理由 + 控えのパス）、`conflict.write_rulings`、trace に `PARKED_OP`。止めた単位と義務の外の単位の行（と止めた足跡の `bash_writes`）を外した返答で `accept_fix` を頭から呼び直し、その返りを返す。
4. `settle.park` が空なら、義務の外の単位の行を `changes` から外し（直しは作業ツリーに残す）、`found` を空にして先へ進む（写しの照らしは commit=True で回る）。外した単位か数えなかった文が在れば、受けた時に trace へ `ABSORBED_OP` を 1 行。
5. 写しの受け付けが最後の回に拒めば、その行を 2 と同じに回す（3 か 4）。止める単位が無いのに写しが拒むなら、この Task では今どおり `rejected(found)` を返す（Task 2 が土台に替える）。

`render_rejects` の `for check, (head, _)` を `CHECKS` の新しい形に合わせる。`bind_problems`・`unrevert_units`・`_held_files`・`drop_excused_units`・`park_bound_units`・`parkable`・PARK_UNDONE_OP を消す。`revert_units` から `frozen_tree` の分かれを消す。模块の docstring の 29-31・62-63・78-85 行を、決め 1・3・4 の 3 行に替える。`planscope.py:27` の「accept.bind_problems が単位に結ぶ」を「最後の回に parking.bind が単位に結ぶ」に直す。

- [ ] **Step 5: 今の振る舞いを縛っていた試験を直す**
  - `test_fix_accept_all.AllChecksCase.test_last_round_unbindable_line_rejects_whole` → 名を `test_last_round_duplicate_and_copy_park_their_units` にし、`(ok, done)` が `(True, True)`・止めた単位が MEAN と CLAMP・`changes` が空。
  - `test_fix_accept_all.RenderCase.test_table_values_are_the_ruled_ones` → `CHECKS` の値が見出しの文字列だけ。
  - `test_blk_fix.py` の `bind_problems` を呼ぶ試験（1294 行の辺り）→ `parking.bind` を呼び、結果が `{MEAN}`。
  - `test_fix_rules.py` の `revert_units`・`unrevert_units`・PARK_UNDONE_OP を mock する試験（645-688 行と 750-800 行の class）→ 戻す手の取り消しを縛る試験は消し、ほかは `revert_units` の新しい引数に合わせる。
  - `test_fix_duty.TestAcceptExcused`: `test_last_round_with_failing_rest_touches_nothing` は消す。`test_last_round_with_unparkable_row_keeps_the_excused_fix` → 名を `test_last_round_duplicate_parks_and_excused_row_is_absorbed` にし、`ok` 真・MEAN を止め・HELD の行は外れて直しは残る。`test_key_outside_duty_and_excused_is_not_opened` → `ok` 真・作り話の単位を止める（`x.py` が戻る）。`test_last_round_drops_only_the_excused_unit` の trace の op は `ABSORBED_OP`。
  - `test_blk_fix_conflict.py:1229` の `park_bound_units` の直の呼び → 受け付けのスクリプトの最後の回で同じ盤面を回し、同じ単位が止まることを見る。
  - `test_writes.py:420-437`・`test_tdd_outside.py:145-183` の赤の文の断言 → 行がテストのファイルごとで、文がそのパスを名指す。

- [ ] **Step 6: 通ることを確かめる**

Run: `works/` から `PYTHONDONTWRITEBYTECODE=1 WORKS_TESTSLOT= python3 -m unittest tests.test_fix_accept_all tests.test_blk_fix tests.test_fix_rules tests.test_fix_duty tests.test_blk_fix_conflict tests.test_writes tests.test_tdd_outside tests.test_blk_fix_tdd tests.test_fix_gates`
Expected: PASS・失敗 0

- [ ] **Step 7: Commit**

```bash
git add works/blk-fix/lib/parking.py works/blk-fix/scripts/accept.py works/blk-fix/lib/tddloop.py works/blk-fix/lib/planscope.py works/.shared/core/leftovers.py works/tests/
git commit -m "fix(works): 修正の輪の最後の回は拒否の行を単位に結んで止め、受けた単位で通す。赤の試験は import で届く単位に結び、戻す先は段の頭の木（run 195f の型。依頼 242 Task 1）"
```

---

### Task 2: 全部止めても写しが受けない時は機械の空の返答。諦めの出口を消す

**Files:**
- Modify: `.shared/core/entry.py`（`empty_fix_reply`。`EMPTY_FIX_OP`・`EMPTY_FIX_BY`・`trace_empty_fix` を `darkfactory/lib/line_edge.py` から移す）
- Modify: `darkfactory/lib/line_edge.py`（その 3 つは `entry` の物の別名にする）
- Modify: `blk-fix/scripts/accept.py`（Task 1 の手順 5 の土台）
- Modify: `blk-fix/scripts/assert_changed.py`（`declared_files` の `accepted.get("ok") is False` の `GiveUp`。docstring の該当の行）
- Modify: `blk-fix/scripts/collect.py`（`accepted.get("ok") is not True or` を消し、受け付けが ok: false なら `Unreadable` で 2）
- Test: `tests/test_fix_accept_all.py`（`StopsKeepWorkCase` に 1 本）・`tests/test_blk_fix.py`（`TestGiveUpOnBoard` の直し）

**Interfaces:**
- Consumes: Task 1 の `StopsKeepWorkCase.reddening_fixer`・`parking.settle`・`accept.PARKED_OP`
- Produces:
  - `entry.empty_fix_reply(b=None, why: str = EMPTY_FIX_REASON) -> dict` — `b` が在り、今の周の `p2.plan_review` の出力が在れば、`plan_faces` に `faces` と `shrink` の key ごとに `{"key": k, "handled": "declared", "how": why}`（写しの型は `how` に 20 字以上を求める）。`fix_closure.reason` も `why`。`b` が無ければ今と同じ返り
  - `entry.EMPTY_FIX_OP = "empty_fix"`・`entry.EMPTY_FIX_BY = "works:empty-fix"`・`entry.trace_empty_fix(b) -> None`
  - `accept.EMPTY_HANDED = "修正の輪の最後の回に、直す義務の単位を全部止めても返答が写しの受け付けを通らなかったので、役の返答の代わりに機械の空の返答を渡した: "`（後ろに残った行を " / " でつなぐ）

- [ ] **Step 1: 落ちる試験を書く**

```python
    def test_reply_level_rows_hand_the_machine_empty_reply(self):
        """run 222f の型: 修正案の事前審査への応答（plan_faces）を 3 回とも欠いた返答。最後の回は義務の全部を止め、
        機械の空の返答を盤面に渡す。h-mid は役の修正と数えない"""
        state, reply = self.reddening_fixer(faces=True)
        reply["plan_faces"] = []
        r = json.loads(self.run_it(reply, INPUTS_ITERATION="3", INPUTS_TDD_STATE=state)[1])
        self.assertEqual((r["ok"], r["done"], r["changes"]), (True, True, []), r)
        self.assertEqual(sorted(self.parked_units()), sorted([MEAN, CLAMP]))
        b = entry.open_board(self.board)
        self.assertEqual(b.node_state("p3.fix"), "done")
        out = json.loads((self.board / b.state["outputs"]["p3.fix"]["file"]).read_text(encoding="utf-8"))
        self.assertTrue(out["plan_faces"] and all(f["handled"] == "declared" for f in out["plan_faces"]))
        self.assertIn(accept_mod.EMPTY_HANDED, out["fix_closure"]["reason"])
        ops = [json.loads(x) for x in (self.board / "trace.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()]
        self.assertTrue(any(o.get("op") == entry.EMPTY_FIX_OP and o.get("by") == entry.EMPTY_FIX_BY for o in ops))
        self.assertIs(json.loads(self.changed(r)[1])["ok"], True, "空の申告は義務の外の単位だけの正しい返答")
```

`accept_mod` は `test_fix_accept_all.accept_module` で読んだ受け付けの模块。`reddening_fixer` に引数 `faces: bool = False` を足し、真なら `p2.plan_review` を穴 1 つ以上の見本（`linekit.reply("plan_review_regression")`）で受けた盤面にする（`fix_ready` の事前審査の見本 `PLAN_REVIEW_OK` は穴を持たないことがあるため）。

- [ ] **Step 2: 落ちることを確かめる**

Run: `works/` から `PYTHONDONTWRITEBYTECODE=1 WORKS_TESTSLOT= python3 -m unittest tests.test_fix_accept_all.StopsKeepWorkCase.test_reply_level_rows_hand_the_machine_empty_reply`
Expected: FAIL（`ok` が偽。Task 1 の手順 5 が `rejected(found)` を返す）

- [ ] **Step 3: 土台と、消す出口**

Task 1 の手順 5 で止める単位が無いのに写しが拒んだら、`entry.empty_fix_reply(b, why=EMPTY_HANDED + 残った行)` を `recount.accept_fix(…, commit=True)` で渡し、`entry.trace_empty_fix(b)` を書いて、その返りを返す。それも通らなければ回す側の誤り（`ValueError` を投げ、入口が 2 にする）。`assert_changed.py` の `GiveUp` の送り（受け付けが ok: false）を消す。`GiveUp` の class とほかの止めは残す。`collect.py` は受け付けの ok: false を入力の誤りとして 2 にする。docstring は 2 か所とも、決め 5 の 1 行に替える。

- [ ] **Step 4: 縛っていた試験を直す**

`test_blk_fix.TestGiveUpOnBoard` のうち、受け付けの出力 `{"ok": false, …}` を assert-changed と collect に渡して盤面が止まることを見る試験 → assert-changed は 2（`Unreadable`）、collect は 2、盤面は止まらない、に替える。申告が空・申告したファイルが変わっていないので止まる試験は今のまま。

- [ ] **Step 5: 通ることを確かめる**

Run: `works/` から `PYTHONDONTWRITEBYTECODE=1 WORKS_TESTSLOT= python3 -m unittest tests.test_fix_accept_all tests.test_blk_fix tests.test_edge tests.test_entry`
Expected: PASS・失敗 0

- [ ] **Step 6: Commit**

```bash
git add works/.shared/core/entry.py works/darkfactory/lib/line_edge.py works/blk-fix/scripts/accept.py works/blk-fix/scripts/assert_changed.py works/blk-fix/scripts/collect.py works/tests/test_fix_accept_all.py works/tests/test_blk_fix.py
git commit -m "fix(works): 修正の輪の最後の回に義務の全部を止めても写しが受けなければ機械の空の返答を渡し、受け付けが通らないまま盤面を止める出口を消す（依頼 242 Task 2）"
```

---

### Task 3: 報告と最後の関所に、受けた単位と止めて持ち越した単位を名指す。工程は先へ進む

**Files:**
- Modify: `.shared/core/report.py`（`fix_split`・`split_line` を足し、`head3` の 1 行目に添える）
- Modify: `darkfactory/lib/line_edge.py`（`_final_head` の「起きたこと」に添える）
- Test: `tests/test_fix_accept_all.py`（`StopsKeepWorkCase` に 2 本）

**Interfaces:**
- Consumes: Task 1 の `accept.PARKED_OP` の trace の行（`unit_keys`・`patch`・`reasons`）と `StopsKeepWorkCase.reddening_fixer`。今ある口: `line_edge.edge(board_dir, at, repo, *, run_id, adapter_mode, final_gate, …)`・`line_edge.final_edge(b, repo, *, run_id, mode, tests)`・`report.decide_outcome(b, gate, …)`・`report.next_request(b, *, tests=None, left=None)`・`report.head3(b, outcome, *, left=None, next_items=None)`
- Produces:
  - `report.fix_split(b) -> dict` — `{"kept": [今の周の p3.fix の出力の changes の unit_key], "parked": [{"unit_key", "why", "patch"}]}`（parked は今の周の `PARKED_OP` の行から。行の順）
  - `report.split_line(b) -> str` — parked が在る時だけ「修正の段は N 単位（key…）を受け、M 単位（key…）を止めて持ち越した（直しの控え <patch>…。次の run の依頼に載る）」。無ければ ""

- [ ] **Step 1: 落ちる試験を書く**

```python
    def test_line_continues_with_kept_and_parked_named(self):
        state, reply = self.reddening_fixer()
        for it in ("1", "2", "3"):
            self.run_it(reply, INPUTS_ITERATION=it, INPUTS_TDD_STATE=state)
        import line_edge, report
        mid = line_edge.edge(self.board, "mid", self.repo, run_id="run-12", adapter_mode="optional", final_gate="when_needed")
        self.assertEqual((mid["stop"], mid["go"]), (False, True), "差分の審査へ進む")
        b = entry.open_board(self.board, allow_halted=True)
        self.assertEqual(report.fix_split(b)["kept"], [MEAN])
        self.assertEqual([p["unit_key"] for p in report.fix_split(b)["parked"]], [CLAMP])
        self.assertEqual(report.decide_outcome(b, {"accepted": True, "round_closed": True}), "needs_human")
        head = report.head3(b, "needs_human", next_items=report.next_request(b))
        self.assertIn("1 単位", head[0]); self.assertIn("止めて持ち越した", head[0])

    def test_parked_patch_reaches_next_request_and_gate(self):
        state, reply = self.reddening_fixer()
        for it in ("1", "2", "3"):
            self.run_it(reply, INPUTS_ITERATION=it, INPUTS_TDD_STATE=state)
        import line_edge, report
        b = entry.open_board(self.board, allow_halted=True)
        patch = report.fix_split(b)["parked"][0]["patch"]
        items = [i for i in report.next_request(b) if i["where"] == CLAMP]
        self.assertTrue(items and patch in items[0]["text"], items)
        gate = line_edge.final_edge(b, self.repo, run_id="run-12", mode="when_needed", tests={"ok": True, "green": True})
        self.assertTrue(gate["ask"])
        self.assertIn("止めて持ち越した", gate["gate_text"].splitlines()[0]); self.assertIn(patch, gate["gate_text"])
```

`line_edge` の import の道は、`tests/test_edge.py` が `darkfactory/lib` を `sys.path` に足すのと同じ手で足す。`edge` の at mid の引数の形が上と違えば、`test_edge.py` の at mid の試験の呼びに合わせる（断言は変えない）。

- [ ] **Step 2: 落ちることを確かめる**

Run: `works/` から `PYTHONDONTWRITEBYTECODE=1 WORKS_TESTSLOT= python3 -m unittest tests.test_fix_accept_all.StopsKeepWorkCase.test_line_continues_with_kept_and_parked_named tests.test_fix_accept_all.StopsKeepWorkCase.test_parked_patch_reaches_next_request_and_gate`
Expected: FAIL（`report.fix_split` が無い）

- [ ] **Step 3: `fix_split`・`split_line` を足し、`head3` の 1 行目と `_final_head` の「起きたこと」の末尾に `split_line(b)` を「。」でつなぐ（空なら何も足さない）。`OUTCOME_WORDS` と `OUTCOMES` は変えない（決め 6）**

- [ ] **Step 4: 通ることを確かめる**

Run: `works/` から `PYTHONDONTWRITEBYTECODE=1 WORKS_TESTSLOT= python3 -m unittest tests.test_fix_accept_all tests.test_report_head tests.test_report tests.test_edge`
Expected: PASS・失敗 0

- [ ] **Step 5: Commit**

```bash
git add works/.shared/core/report.py works/darkfactory/lib/line_edge.py works/tests/test_fix_accept_all.py
git commit -m "fix(works): 報告と最後の関所の冒頭に、修正の段が受けた単位と止めて持ち越した単位（控えの patch）を名指す（依頼 242 Task 3）"
```

---

### Task 4: 決まりの文・CHANGELOG・仕上げ

**Files:**
- Modify: `blk-fix/blk-fix.yaml`（description の「拒めば理由を貼って同じ会話で出し直し、上限 3 回」の後に決め 1 の 1 文。fix-accept・assert-changed・collect の節の説明のうち「諦めた輪の後は盤面を止める」の文）
- Modify: `docs/keep-essence.md`（4 に「修正の受け付けの 3 回目も同じ: 結べる単位を段の頭の木に戻して止め、理由と控えを残し、受けた単位で先へ進む」の 1 文）
- Modify: `CHANGELOG.md`（`[Unreleased]` の `### Fixed`）

**Interfaces:**
- Consumes: Task 1-3 の全部
- Produces: CHANGELOG の 1 項目（下書き）: 「修正の受け付けが 3 回目も拒んだ時、盤面を止めなくなった。拒否の行を、名指した単位・テストのファイルが import で届く単位・TDD の輪のテストの持ち主に結び、その単位とファイルを共にする単位だけを段の頭の木に戻して控えの patch に残し、人に回して次の run の依頼に載せる。ほかの単位は受けて、差分の審査・最後の関所・報告へ進む。結べない行は直す義務の全部の単位を止め、理由を名指す。全部を止めても返答が受けられなければ、機械の空の返答を渡す。今までは、試験の赤・裁定で外れた単位への申し出・ファイルを共にする単位の行が来ると、受けた単位も含めて捨てて run が止まった（run 195f・195d・195c・222・226b・184）」

- [ ] **Step 1: 文を書き換え、CHANGELOG に上の項目を足す**

- [ ] **Step 2: 古い言い方が残っていないことを確かめる**

Run: 根から `grep -rn "どの単位にも結べない拒否で諦めた\|bind_problems\|park_bound_units\|PARK_UNDONE\|_held_files\|drop_excused_units" works --include=*.py --include=*.yaml --include=*.md | grep -v docs/plans | grep -v CHANGELOG`
Expected: 何も出ない

- [ ] **Step 3: 速い段と根の柵を 1 回だけ通す**

Run: `works/` から `WORKS_TESTS=fast sh tests/run.sh`、根から `sh ~/.cache/works-dogfood/rootfences.sh`
Expected: どちらも失敗 0

- [ ] **Step 4: Commit**

```bash
git add works/blk-fix/blk-fix.yaml works/docs/keep-essence.md works/CHANGELOG.md
git commit -m "docs(works): 修正の受け付けの最後の回は単位を止めて先へ進む決まりを YAML の説明・keep-essence・CHANGELOG に書く（依頼 242 Task 4）"
```

---

## この計画が扱わない物

- `assert_changed.py` のほかの止め（申告が空・申告したファイルが変わっていない）。修正役が「済んだ」と偽った形で、6 本の証拠には無い。同じ決まりで単位を止める形に寄せられる見込みはあるが、別の小さな run に回す。
- 赤の試験の traceback の中のパスで結びを細かくすること（決め 2）。
- 最後の回でない回の拒否の形（全部を並べて丸ごと出し直させる）。
- 止めた単位の控えの patch を次の run が自動で当て直すこと。今は次の run の依頼の下書きに、パスと理由が字のまま載るだけ。
