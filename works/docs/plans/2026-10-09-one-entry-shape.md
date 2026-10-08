<!-- coldwrite:skip 内部の設計書。語は「目的と語」の節と works/README.md で定義 -->
# 入口を 1 つの形にする（依頼・手元の変更・PR を同じ入力に揃え、後ろは入力の中身だけで決める）

状態: 設計と計画だけ（コードは変えていない）。並行の片付けの 5 束が出荷した後に入れる。7 節の決め事は持ち主の原則（下）に沿って自分で決めた。Task は 10 節。

## 平たく言うと（3 行）

- 今の入口は「依頼だけ・変更だけ・両方」の 3 種（`entry`）を start が決め、種で盤面の始め方・依頼を積む時期・頭の行・ブロックの空の受け方・canary の確かめが分かれている。分かれの元は「依頼を P1 の前に積むと P1 の役が外れる」という写しの核の決まりで、works はそれを避けるために依頼を後から積む道（`both`）を作った。
- 案: どの入口も start で 1 つの入力の形（差分の根・差分（空でもよい）・依頼の行（空でもよい）・PR などの添え物・仕様の段を挟むか）に揃え、盤面の印「P1 を外す」は種でなく「差分が空か」で立てる。依頼はいつも盤面を作る時に積む。後ろの段は入力の中身だけを読む。
- 振る舞いはほぼ今のまま（差分が空の run は今の「依頼だけ」、差分が在る run は今の「変更だけ・両方」と同じ役が回る）。消えるのは種の分かれのコードと、それが生んだ 2 つの穴（差分が空の「両方」・「変更だけ」が空差分の柵で止まる）。仕様の段（blk-spec）は入口の種に依らない任意の段として線に配線する。

## 目的と語

持ち主の決め（2026-10-09）: 「依頼と変更と PR と抽象化するとやることは同じはず。なんで分岐するの… プログラムでも同じでしょ。どの入り口でも最終的に環境変数に何をセットするのかだけみたいな」。入口ごとに流れを分けない。どの入口（依頼のファイル・手元の変更 `--base`・`--pr`）も 1 つの入力の形に揃え、後ろの段は入力の中身だけで決める。仕様（spec）は入口の種でなく、要件を固める要る時に判定の前へ挟む段として扱う（別の入口にしない）。

読む前提: works（このリポジトリの `works/`。修正依頼を直して出荷する工場 darkfactory。Archon v0.11.1 の上で動く）の全体は `works/README.md` と `works/docs/darkfactory-flow.md`。線は 1 周（`entry.start` の `stop_after_round=1`）。

語:

- 入力の形: start が作り、`r1/start.json` の欄 `input` に固める 1 つの dict（2 節）。run の間は変えない（呼び直しは控えから読み直し、測り直さない）
- 差分の根: P1 の役が差分を取る起点の版（`record.base`）。今の `_change_base` の merge-base、依頼だけなら HEAD
- 差分: 差分の根から run の作業ツリーの今の姿（未追跡も含む。写しの核の `_worktree_tree` と同じ測り方）までの変更。空でもよい
- 依頼の行: 依頼のファイルの findings の行。空でもよい
- 添え物: 判定・目的の役が読む文や事実のうち、依頼の行でない物（PR の番号・題・本文、依頼の answers・prior_failures）
- 印: 写しの核の `record.process.request_entry`（本流の語は「入口の印」）。立っている周は P1 の役が na になる。この文書の後、works では「差分が空の印」と読む
- 種: 今の `entry`（`request`・`change`・`both`）。この文書で消す物
- 写しの核: `works/.shared/core/graphloops/`（本流 graphloops 0.21.0 の写し。手直しは台帳 `COPIED_FROM` の `!` 行だけ）。works の差し替えは `entry.CORE_OVERRIDES`（盤面を開くたびに写しの大域の名を替える。台帳は変えない）

## 1. 今の分かれ方（事実。行は 22d98fdc）

種を決める所と、種で分かれる所:

1. `works/.shared/core/entry.py:1196` `kind = "both" if change and inp["items"] else "change" if change else "request"`。`:1200` `items=None if change else inp["items"]`（変更が在れば盤面を作る時に依頼を積まない）
2. `works/.shared/core/board.py:772-836` `DiskBoard.begin`: items を渡せば `add_request`、渡さなければ積まない。写しの核の `add`（`review-loop.py:123-165`）は `entry_opens`（`:172-174`。1 周目・`p1.worktree_before` が待ち・印が無い）の時に印を立てる
3. `entry.py:966-990` `add_pending_request`: 種が `both` の run だけ、`p1.worktree_before` が済んだ後（印の立たない所）に依頼を積む。`_drain` の終わり（`:966`）と `resume_after_ci` から呼ぶ
4. `entry.py:1028` `ENTRIES`・`:1149-1155` `_entry_words`（頭の行の入口の文を種で選ぶ）・`:1047-1050` `_request_text`（依頼の文が在れば PR の題と本文を捨てる）
5. `works/.shared/core/conflict.py:221-224`（と `:233-236` に同じ定義がもう 1 つ）`change_only`: 種が `change` の run だけ、依頼を読むブロック（`blk-judge`・`blk-premises`・`blk-purpose` の `scripts/intake.py`）が空の依頼を受ける
6. `works/darkfactory/darkfactory.yaml:134` start の出口の `entry`（enum の 3 語。どの `when:` も読まない）
7. `works/darkfactory/nodes.json` P1 の 9 行の reason の文（「依頼だけ」「両方は版が固まった後に積む」）
8. `works/dev/canary.sh:66-89,136-163,218` の語 `--request change`（0.2.49）と `works/dev/canary_check.py:17-19,66-95,151-154,750-763`（種が `request` の run の (h)(j) を `not_exercised` に、語 `change` だけ (h)(j) で終了コード）

印で分かれる所（写しの核。どれも印 1 本を読む `request_entry` を通る）: 3.1 節。

種が生んだ穴（今壊れている）:

- **差分が空の「両方」は柵で止まる**: `--base` か `--pr` の差分が空で依頼も在る run は、印が立たない（依頼を後から積む）ので、`p1.worktree_before` の空差分の柵（`review-loop.py:1437-1445`。印が無ければ止める）で止まる。依頼だけで始めれば通る run が、差分の根を名指しただけで止まる
- **差分が空の「変更だけ」は CI の後に止まる**: 依頼も差分も無い run を start が拒まず、修正前の CI を走らせた後に同じ柵で止まる
- **canary の依頼の語が局所レビューを回さない**: 0.2.49 で語 `change` を足して回り道した
- **仕様の段に依頼が届かない**: blk-spec を配線すると、`both` の依頼は `p1.worktree_before`（`spec.freeze` の後）まで積まれないので、`spec.write` が依頼の行を見ない

## 2. 1 つの入力の形

### 2.1 欄

`r1/start.json` の欄 `input`（start の返りにも同じ物）:

```json
{"base": {"rev": "<40 桁>", "from": "head|base|pr", "name": "<名指した版の名・PR の番号・空>"},
 "head_rev": "<start の時の HEAD。修正の起点>",
 "diff": {"empty": false, "files": 3, "stat": "3 files changed, 10 insertions(+), 2 deletions(-)"},
 "requests": 2, "request_file": "<絶対パスか空>",
 "pr": {"number": "12", "title": "…"} ,
 "spec": false}
```

- `base`: 差分の根。`from` は誰が決めたか（`head` は名指し無し＝HEAD、`base` は `--base`、`pr` は PR の base との merge-base）。種ではなく出どころの名札で、後ろの段は分岐に使わない（頭の行と報告に書くだけ）
- `diff`: 差分の根から作業ツリーの今の姿までの測り（2.2 の 3）。`empty` だけが分岐に使われる欄
- `requests`: 依頼の行の数（行そのものは今どおり盤面の `record.process.request_findings`）。`request_file` は今の欄のまま
- `pr`: PR の番号と題（本文は盤面の依頼の文と、盤面の根の `github.json` に在る。控えに本文を写さない）。PR でなければ `null`
- `spec`: 仕様の段を挟むか（4 節）

今の欄 `entry`・`entry_words`・`change` は消す。今の `base_rev`（修正の起点）・`requests`・`request_file`・入力の控えの欄（`test_cmd`・`thickness` ほか）はそのまま。

### 2.2 作る所と、入口ごとの埋め方

作るのは `entry.start` の 1 か所（`entry.build_input(raw, repo, reads) -> dict`。今の `check_inputs` の続き）。順:

1. 差分の根: `--base` と `--pr` の両方は今どおり拒む。`--base` は `_merge_base(repo, base)`、`--pr` は今の `_change_base` の PR の道（head が HEAD と同じか・base の版が在るかの確かめも今どおり）、どちらも無ければ HEAD。PR の読み方（隔離の前の `ghreads` か run の中の `gh` か）は並行の束が決める物で、この形は「PR の base・head・題・本文が引けた」ことだけを前提にする
2. 依頼の行と添え物: 今の `_read_request`（依頼のファイルが無ければ空）。PR の題と本文は添え物
3. 差分: `board.diff_of(repo, base_rev) -> {"empty", "files", "stat"}`（新設。写しの核の `_worktree_tree` を `util.GIT_CWD=repo` で呼んだ木と `git rev-parse <base_rev>^{tree}` を比べ、違えば `git diff --numstat <base_rev> <木>` で数える）。版を固める `p1.worktree_before` と同じ測り方なので、start の測りと柵の測りは食い違わない
4. 拒む（`check_inputs` の中。start の頭）: 差分が空で依頼の行も空なら `InputRefused`（「直す物も審査する物も無い——依頼を名指すか、差分の在る base・PR を名指す」）。盤面を作る前で、CI も走らせない
5. 盤面の依頼の文（`request_text`）: 依頼のファイルの文と PR の題・本文を、在る物だけ見出し付きで並べる（今は依頼の文が在ると PR の文を捨てる）。どちらも無ければ今の「変更（base X）の審査」

入口ごとに埋まる物（後ろの段はこの表を知らない）:

- 依頼のファイルだけ: base=HEAD（`from: head`）・差分は空（`use.sh` は手元の未 commit の変更を包んだ commit から run を切るので、run の作業ツリーは HEAD と同じ）・依頼の行あり
- `--base X`（と依頼）: base=merge-base(X, HEAD)・差分は X からの変更（包んだ未 commit の変更を含む）・依頼の行は有っても無くても
- `--pr N`（と依頼）: base=merge-base(PR の base, HEAD)・差分は PR の変更・`pr` に番号と題・依頼の文に PR の題と本文

### 2.3 盤面の始め方（1 本）

`DiskBoard.begin` は依頼の行が在ればいつも渡す（`items=inp["items"] or None`）。新しい引数 `diff_empty: bool | None`（`None` は本流の振る舞い。線 A は start の測りを渡す）を `state.works.begin` に控え、呼び直しの見分けの引数に入れる。

印を立てる条件は works の差し替え 1 本で変える: `CORE_OVERRIDES["entry_opens"]`（`board.rl_builder`。写しの `entry_opens(b)` が真で、かつ `state.works.begin.diff_empty` が真の時だけ真。`None` なら写しのまま）。写しの `add` は大域の名 `entry_opens` を呼ぶので、差し替えだけで「依頼を P1 の前に積んでも、差分が在れば印を立てない」になる。台帳の `!` 行は足さない。

結果:

- 差分が空・依頼あり → 印が立つ → 今の「依頼だけ」と同じ（P1 の役は na、空差分の柵は通る、並行 PR の範囲は依頼の where）
- 差分あり・依頼あり → 印は立たない → P1 の役が差分に回り、依頼は 1 周目の判定に届く（今の「両方」と同じ。積む時期が版を固める前になるだけ）
- 差分あり・依頼なし → 今の「変更だけ」と同じ
- 差分が空・依頼なし → start が拒む（2.2 の 4）

消す物: `add_pending_request`・`PENDING_WAIT_NODE`・`ENTRIES`・`_entry_words` の種の分け・`_drain` の中の積み・`conflict.change_only`（2 つとも）。

## 3. 分かれ目ごとの置き換え

### 3.1 写しの核（印を読む所。どれも変えない）

写しの核は印 1 本（`request_entry` と、それを呼ぶ物）で決めていて、種を知らない。印が「差分が空」の意味になれば、下の全部が入力の中身で決まる。写しは 1 バイトも変えない。

- `review-loop.py:177-190` `request_entry`（印が在り、修正がまだ入っていない周）→ 「1 周目で入力の差分が空」
- `:1093-1097` `not_request_entry`（`p1.local_review`・`p1.consistency_bypass`・`p1.hygiene` の cond。`graphs/review-loop.json:1675,1892,1974`）→ 「差分が在る」
- `:1100-1108` `external_standards_due`・`:1111-1117` `provenance_due`・`:1129-1150` `_deep_due`（`procedure_trace_due`・`gate_efficacy_due`・`test_double_fidelity_due`）・`:1161-1170` `main_path_observation_due` → 「差分が在り、その上でそれぞれの条件」（昇格した周は今どおり勝つ）
- `:193-200` `entry_first_fix`・`:1197-1202` `parallel_pr_due` → 「差分が空で始めた run の、最初に修正が入った次の周」（1 周の線では来ない）
- `:203-210` `request_wheres`・`:2291-2300` `_pr_files`（並行 PR の範囲）→ 「差分が空なら依頼の where」
- `:213-220` `_entry_skipped`・`:1728-1734`（素材の穴埋めの理由）→ 「差分が空なので P1 の役を起こしていない」（文は写しのまま「判定から入る run」。7 節の決め事 6）
- `:1437-1445` 空差分の柵 → 「差分が空で、依頼も無い（start が先に拒む）か、P3 が差分を全部戻した」。柵は残る
- `:298-306` 依頼の移し替え（印の周は履歴へ移さない）→ 1 周の線では効かない
- `:123-165` `add` の文（「判定から入る run として始まる」）→ 差し替えの後も文は写しのまま

### 3.2 works の側（種を読む所と、その置き換え）

盤面と線（run の中）:

- `entry.py:1028` `ENTRIES`・`:1149-1155` `_entry_words`・`:1196` 種を決める行・`:1200` `items=None if change` → 消す。頭の行は `entry.input_words(input)`（5.2）。依頼の行はいつも渡す（2.3）
- `entry.py:966-990` `add_pending_request`・`:963` `PENDING_WAIT_NODE`・`:966` `_drain` の中の積み → 消す（依頼は begin で積む）
- `entry.py:1047-1050` `_request_text`（依頼の文が在れば PR の文を捨てる）→ 在る物を全部並べる（7 節の決め事 5）
- `entry.py:591-620` `_change_base` の返り `change: {from, name, text}` → `base: {rev, from, name}` と `pr: {number, title, body} | None`（PR の確かめは今のまま）
- `darkfactory/lib/line_edge.py:919-922` h-mat の「依頼を積めない（`waiting`）なら止める」→ 消す（止める理由 `PENDING_REQUEST_BY`（`:109`）も）
- `.shared/core/ci_role.py:360`・`blk-ci/blk-ci.yaml:14,184-185` `resume_after_ci` の `pr_go`（中で `add_pending_request` を呼んでいた）→ 呼び口はそのまま。積みが無くなるだけ
- `.shared/core/conflict.py:221-224` と `:233-236`（同じ定義が 2 つ）`change_only`（種が `change`）→ 1 つの `no_requests(board_dir)`（`input.requests == 0`）
- `blk-judge/scripts/intake.py:49`・`blk-premises/scripts/intake.py:55`・`blk-purpose/scripts/intake.py:49` `no_request = … and conflict.change_only(board)` → `conflict.no_requests(board)`。入力の説明の文（`blk-judge/blk-judge.yaml:15`・`blk-premises/blk-premises.yaml:25`・`blk-purpose/blk-purpose.yaml:17`「変更から入った run だけ」）→「依頼の行が無い run だけ」
- `blk-judge/commands/diagnose.md:9`（空の依頼＝「変更 base・pr から入った」）・`blk-purpose/commands/purpose.md:13,23` → 「依頼の行が無い run」と中身で書く
- `blk-purpose`: 役が受けるのは線の `$INPUTS.request`（依頼のファイルのパス）だけで、`--pr` だけの run では空。指示書は出典の 1 番に「① PR 説明」を挙げるが、PR の題と本文を役に渡す道が無い（`entry._change_base` の docstring は渡すと書くが、渡すコードは無い）→ start が盤面の根に `pr.md`（PR の番号・題・本文。PR でなければ書かない）を置き、線が `pr_file: $start.output.pr_file` で blk-purpose に渡す（Task 4）。並行の束が PR の文を run の中で読んで役へ渡す道を先に作っていれば、その道を使い、この項目は落とす
- `darkfactory/darkfactory.yaml:134` start の出口 `entry`（enum 3 語。どの `when:` も読まない）→ 消して `input`（object）・`pr_file`（string）を足す。13 本の `darkfactory/fixtures/*.stubs.yaml` の `head_line`（`入口: 判定から（依頼 2 件）…`）→ 新しい文に
- `darkfactory/nodes.json:11-18` P1 の 9 行の reason の文 → 「差分が空の run の 1 周目は印で na（本線と同じ条件。印は入力の差分が空の時だけ立つ）」
- `.shared/core/report.py:1110` `head_entry` が `entry_words` を読む → `input` から `entry.input_words`。`input` の無い控えは「入口: 控えに入力の形が無い」（run の中では起きない。9 節）
- `darkfactory/darkfactory.yaml:22-31` inputs の説明（「request・base・pr の少なくとも 1 つが要る」）→「依頼の行か差分の少なくとも 1 つが要る」（拒むのは start）

run の外（dev・文書）:

- `dev/use.sh:810-814` の表示「入口: 変更から（…）」→「差分の根: …」。`:244-249` の拒み（依頼が `-` で `--base`・`--pr` も無い）は残す（start でも同じ物を拒むが、Archon を起こす前に止まる方が安い）
- `dev/canary.sh:66-89,136-163,218-247`・`dev/canary_check.py:17-19,66-95,134,151-154,749-763,886` → 5.3
- `dev/launch.py:393-404`（起動と run を結ぶ鍵を、依頼の写し → 読み出しのファイル → 無ければ結ばない、の順で選ぶ）→ 変えない。流れの分岐でなく、殻が run を見つける鍵の選び方
- `dev/lib.sh:567-588`・`dev/dogfood.sh`・`dev/real-run.sh` → 変えない（種を読まない）
- `skills/works/SKILL.md:56,75-80`・`README.md:224,265-267`・`docs/darkfactory-flow.md` の入口の節 → 入力の形の文に

変えない物: `forge.py`・`dev/hostgh.py`・`ghreads.py`（PR の読み口。並行の束の範囲）、`prcheck.py:200-201` と `blk-pr/commands/pr-check.md:11`（差分が空なら依頼の where。印で決まる写しの `request_wheres` をそのまま使う）、`blk-material`（印は写しの条件のまま届く）、`blk-report/prompts/review-loop/report.md:16`（5.2）。

種を固める試験（書き換える物。Task の赤の元）:

- `tests/test_entry.py`: `test_start_records_request_and_entry`（1038）・`test_start_head_line`（1061）・`test_start_change_only_is_normal_run`（1203）・`test_start_request_and_change_keeps_p1`（1225）・`test_start_object_request_and_change_adds_findings`（1245）・`test_both_waits_for_frozen_revision_then_adds`（1259）・`test_request_only_keeps_request_entry`（1276）・`test_start_script_success_one_line`（1508）
- `tests/test_entry_inputs.py`: `test_change_only_accepted_with_merge_base`・`test_request_and_change_resolves_base`・`test_needs_request_or_change_and_not_both_changes`・`test_pr_uses_github_base_oid_and_carries_description`
- `tests/test_line_inputs.py`: `test_check_inputs_passes_every_start_name`（`FROM_CHANGE`）
- `tests/test_script_io.py::test_change_only_lives_in_conflict`（317）・`tests/test_report.py::test_entry_words_from_start_doc`（920）
- `tests/test_canary.py`（788・1390・1414・1425）・`tests/test_canary_sh.py`（83・95・103）・`tests/test_use.py::test_start_change_entry_flags`（202）
- 印の試験（`test_board_begin.py:179,181,225`・`test_board_replay.py::test_replay_request_entry`・`test_board_steps.py` の request_entry の段・`test_blk_material.py` の 453・632・`test_edge.py::test_entry_edge_flags`）は写しの振る舞いの試験で、そのまま通る見込み（印の立て方を差し替えるのは線 A の start の道だけ）
- 穴: 依頼を読む 3 ブロックの試験に、空の依頼を受ける道の試験が無い（Task 3 で足す）

### 3.3 差分が空の時に回る役

1 周目に回る: P0 の全部（`p0.local_checks`・`p0.parallel_pr`（範囲は依頼の where）・`p0.premises`・`p0.purpose`・`p0.purpose_review`（出典 ③ の時）・`p0.prior_decisions`（1 周目は真））と、判定から後の全部。

1 周目に回らない: P1 の 9 役全部（`p1.local_review`・`p1.consistency_bypass`・`p1.hygiene`・`p1.external_standards`・`p1.procedure_trace`・`p1.gate_efficacy`・`p1.test_double_fidelity`・`p1.main_path_observation`・`p1.provenance`）。素材は `not_applicable`（理由は「P1 の役を起こしていない」）。本流と同じ（P1 は 1 周の費用の約 8 割で、既存のコードへ回す物ではない。本流 `graphloops/commands/review-graph.md:135`）。線は 1 周なので、修正が入った後の周で P1 が戻る形は来ない——修正の差分は修正の後の差分の審査（`p3.delta_review`）と独立の目（R1〜R4）が見る（今と同じ）。

## 4. 仕様の段（任意）

### 4.1 何が選ぶか

入力の欄 `spec`（真偽）だけが選ぶ。埋め方は 1 つ: 線の入力 `spec`（`use.sh start --spec`、Archon の `--input spec=on`）。盤面へは `inputs.flow="spec"`（写しの核の唯一の選び口。本流も `--input flow=spec` だけ）。入口の種とは無関係で、依頼だけ・`--base`・`--pr` のどれとも組める（本流 `review-graph.md:203-211` も「判定から入る run と一緒に使ってよい」）。

選べない組（start が拒む）:

- `spec` と依頼の文が無い（依頼のファイルも PR の本文も無い）: 仕様の書き手が読む物が無い
- `spec` と `unattended`: 仕様の承認は人の関所で、無人の run は関所で止める（`use.sh` は関所に stop を答える）ので、仕様が固まらずに止まるだけ
- `spec` と `fix_fixture`: 固定材料は修正の直前の盤面で、仕様の段より後

役が自分で「要件を固める要る」と決める道は作らない（7 節の決め事 3）。

### 4.2 線のどこに挟むか

写しの graph は `spec.write` を `p0.base`・`p0.local_checks` の後に、`p1.worktree_before` を `spec.freeze` の後に置いている。線では `h-entry`（CI が済んだ後）の後、`pr-checking` と判定の前:

```
start → ci-checking → h-entry → speccing（blk-spec。when: $h-entry.output.spec_go）→ h-spec（境の節。いつも走る）
      → pr-checking（when: $h-spec.output.pr_go）→ premising → h-judge → …
```

- `speccing`: `include: blk-spec`、`depends_on: [h-entry]`、`when: "$h-entry.output.spec_go == true"`（`line_edge.entry_edge` は既に `spec_go` を出している）
- `h-spec`（新しい境の節。`at: "spec"`）: `depends_on: [h-entry, speccing]`・`trigger_rule: none_failed_min_one_success`。盤面の engine の節を回し直し（今の `entry.resume_after_ci` と同じ輪。`p0.parallel_pr` は `spec.freeze` の後に出る）、`pr_go` を出す。仕様の無い run では何もせずに今の `h-entry` と同じ `pr_go` を出す。`pr-checking` の `when:` は `h-spec` だけを読む（1 本の道）
- 依頼の行は盤面を作る時に積む（2.3）ので、`spec.write` は依頼の行を読める（今の `both` の積み方では読めなかった）
- 仕様の書き手は受け入れ条件のテストを対象のリポジトリに書く。版を固める前なので 1 周目の差分に入る。印は start の測り（差分が空か）で立っているので変わらない。P1 が回る run（差分あり）では、P1 の役が仕様のテストも差分として読む（本流と同じ）

### 4.3 配線に要る物

1. 入力: `darkfactory.yaml` の inputs に `spec`、start の `with:` に `spec: $INPUTS.spec`、`entry.check_inputs` が語（空か `on`）を確かめ、`begin(inputs={…, "flow": "spec"})`
2. 節の表: `darkfactory/nodes.json` の `spec.write`・`spec.review`・`spec.revise` を `{"by": "role", "where": "blk-spec"}` に（今は absent。`tests/test_blk_spec.py:82-90` の試験用の表と同じ形）。`darkfactory.graph.json`・`tests/linekit.py` の節の順・線の fixtures を同じ commit で
3. `tests/test_script_contract.py:60-62` の `UNWIRED` から blk-spec を外す
4. 承認: blk-spec の `spec-gate`（include の中の Archon の approval）が v0.11.1 で止まるかを、線の模擬実行（stub）と本物の run で確かめる（`docs/plans/2026-10-03-in-run-replan.md:789` が測る物に挙げた形）
5. `spec.check`（修正の後に受け入れ条件のテストのファイルが変わったかを照らし、変わっていれば周の途中の問い `spec_changed`）: 今の線には答える道が無く、問いが残ると線が止まる。最後の関所（`h-final` → `final-gate`）の項目に載せ、関所の答えで答える（continue＝変わったテストを認めて amendments に残す、stop＝止める）。`line_edge` の `h-final` が今「この関所の答えはこの問いに答えない」と書く所（`line_edge.py:542-547`）を、`spec.check` の問いだけ答える形に替える
6. 関所の語: `gatemarks.KIND_WORDS` に `spec_approval`（仕様の承認）・`spec_changed`（承認の後に受け入れ条件のテストが変わった）
7. 頭の行: 入口の文に「・仕様の段あり」

写しのままで要らない物: 写しの核の `spec_flow`・`spec_approve`・`spec_freeze`・`spec_check` は変えない。`spec.freeze` は受け入れ条件を依頼の行のバッチ（出どころ `SPEC_ORIGIN`）として積み、印は立てない（本流のまま）。

## 5. 控え・報告・canary

### 5.1 控え

- `r1/start.json`: 欄 `input`（2.1）を足し、`entry`・`entry_words`・`change` を消す。`requests`・`request_file`・`base_rev`（修正の起点）は残す
- `state.works.begin`: 引数 `diff_empty` を足す（2.3）
- `record.process.request_entry`: 名も形も写しのまま。works の文書では「差分が空の印」と読む（`works/README.md` の語の節に 1 行）
- start の返り・`darkfactory.yaml` の start の `output_format`: `entry` を消し、`input` を足す（`h-*` の `when:` はどれも読まないので、線の分岐は変わらない）

### 5.2 報告

- 頭の行（`entry.start` の `head_line`）と冒頭 2（`report.head_entry`、`report.py:1110` の `entry_words` を読む所）: 入口の文を入力の形から 1 本の関数 `entry.input_words(input) -> str` で作る。例: `入口: 差分 1a2b3c4d5e6f..HEAD（3 ファイル・base main）・依頼 2 件` ／ `入口: 差分なし（HEAD）・依頼 2 件——P1 の役は起こさない` ／ `入口: 差分 …（PR #12「題」）・依頼 0 件・仕様の段あり`
- 報告の書き手の指示書（`blk-report/prompts/review-loop/report.md:16`。印が在れば「判定から入った run」の 1 行）は変えない（印の意味は「P1 の役を起こしていない」のままなので文は正しい）

### 5.3 canary

語 `--request change` は要らなくなる。canary の語は「どの種とどの依頼か」の 1 軸に戻し、差分を持たせるかは別の旗 `--diff`（今の `change` と同じ 1 行の未 commit の変更と `--base <種を写した commit>`）にする。`canary.sh --request fix --diff` が今の `--request change` と同じ run。語 `change` は「`--request fix --diff` に替わった」と 1 行で拒む。

`canary_check.py` は語で確かめを選ばず、控えの入力で選ぶ: (h) 記録のフック・(j) 返答の契約は `input.diff.empty` が偽の run で終了コードに数え、真の run では今の `not_exercised`。(a)〜(g)・(k) は今どおり語で選ぶ（種と依頼で決まる確かめ）。`start_entry`・`REQUEST_ENTRY` は `input.diff.empty` を読む関数に替える。

## 6. 本流（review-graph）との比べ

本流（`graphloops/`）の入口は既に 1 つの形に近い: 入力は自由文の依頼と依頼の行の一覧（`process.request_findings`）だけで、PR は依頼の文の中の名指し（専用の入口が無い）。P1 を外すかは別の欄の印 1 本で決め、engine は run の種を持たない（本流 `docs/loop-graph/review-loop.md:119`）。仕様の道も `--input flow=spec` 1 か所で選び、入口と組める。

違い（works が本流から外れる所）は 1 つ: 本流は「1 周目の P1 より前の最初の add」で印を立てる（差分が在っても、P1 の前に依頼を積めば P1 を外す）。works は「入力の差分が空」で立てる。本流が差分の空で決めなかった理由は 2 つ（本流 `docs/feedback/review-loop-remaining-findings.md:289-311`）——依頼の無い空差分は本当の誤り、P3 の後の空差分は修正が全部戻した印——で、どちらも works の形で残る（前者は start が拒み、後者は写しの柵がそのまま見る）。本流の形では「差分の在る run に依頼を足す」と P1 が外れるので、works はそれを避けるために種と後積みを作った。持ち主の原則（入力の中身で決める）では、差分が在れば P1 が見るのが筋で、後積みの回り道が要らなくなる。

## 7. 決め事（自分で決めた。推しのとおり）

1. **印を残し、立てる条件だけ差し替える**（推し）。写しの核の印を読む所は約 30 か所で、条件の関数は読む欄を `cond_reads` で宣言するので、`request_entry` を「差分が空」を読む関数に替えると呼び手の宣言が全部ずれる。印を立てる 1 か所（`entry_opens`）を差し替えれば、写しを 1 バイトも変えずに全部が中身で決まる。案 B（写しの条件を全部差し替える）は台帳の手直しか差し替えが 10 本を超え、本流の写し直しのたびに当て直しになる
2. **差分の測りは start の 1 回で固める**（推し）。呼び直し（Archon の再開）では修正が作業ツリーを進めているので、測り直すと別の値になる。今の `base_rev` と同じく最初の控えから読む
3. **仕様は明示の入力だけで選ぶ**（推し）。役が「要件が足りない」と決めて挟む道は、無人の run で人の関所を勝手に開けることになり、費用（仕様の 3 役＋承認）も読めなくなる。本流も明示だけ。要る声が出たら、判定役の出口の問いから次の run の `--spec` を勧める形を後で考える
4. **既定の差分の根は HEAD のまま**（推し）。本流の p0.base は「未 commit の変更が在れば HEAD、無ければ既定の枝との merge-base」を既定にするが、works で既定を変えると依頼だけの run が黙って P1（1 周の約 8 割）を払うようになる。手元の変更を審査させたい人は `--base` を名指す（`use.sh` は包んだ未 commit の変更を表示している）
5. **PR の題と本文は依頼の文に足す**（推し）。今は依頼のファイルが在ると PR の文を捨てる。添え物は在る物を全部渡す。固定材料の照らし（依頼の文の sha256）は PR の無い canary の固定材料では変わらない
6. **素材の穴埋めの文と add の文は写しのまま**（推し）。「判定から入る run」の文は意味として正しい（P1 を起こしていない）。文のために台帳の手直しを足さない
7. **canary は差分を旗で持たせ、確かめは入力で選ぶ**（推し。5.3）。語 `change` を残すと、種（入口の形）で分ける形が canary に残る
8. **語 `change` を拒む文に替わりの打ち方を書く**（推し）。黙って `fix --diff` に読み替えない（打った人が古い手順を直せるように）

## 8. 危険

今壊れている物（1 節の穴）はこの案で消える。入れた後に起こりうる物:

1. **start の測りと柵の測りがずれる**: start の後・版を固める前に作業ツリーが変わると（仕様の書き手のテストのファイル・CI が作る未追跡のファイル）、start は空と測り、柵は差分ありと見る。印は立っているので柵は通り、P1 は外れたまま（今の「依頼だけ」と同じ）。逆（start が差分ありと測り、柵で空）は、start が `.gitignore` の外の物を見た時だけ起きうるが、測り方が同じ関数なので起きない見込み。起きれば柵が「対象差分が空」で止める（見える止まり方）
2. **差分も依頼も無い run を拒むことで、今動いていた使い方が止まる**: 今それは CI の後に柵で止まっていたので、使えていた使い方は無い
3. **差し替え `entry_opens` が本流の写し直しで効かなくなる**: 写しが関数の名を替えると、`_apply_overrides` が「RL の大域の名前に無い」で BoardGap にする（黙って効かなくはならない）
4. **仕様の承認が include の中の approval で止まらない**: v0.11.1 で未確かめ（4.3 の 4）。止まらなければ、承認を線の最上段の approval（`policy-gate` と同じ形）に移す
5. **仕様のテストが P1 の差分に混ざる**: 差分ありの run で仕様を挟むと、P1 の役が仕様の書き手のテストも審査する。本流と同じで、害は費用だけ
6. **報告や dev の道具が古い控えの `entry` を読む**: run は start の時の works の写しで動くので、run の中の道（盤面・ブロック・報告）に古い盤面の互換は要らない。run の外で過去の盤面を読む道具（`dev/canary_check.py`・`dev/fixmeasure.py` など、終わった run の控えを読む物）だけは、`input` の無い控えを「分からない」として扱う（`not_exercised` と同じ扱い。落ちない）

## 9. 移り方

- run は start の時に works の写しを取るので、run の中の道（`entry.py`・`board.py`・ブロック・報告）は新しい形だけを読む。古い盤面の `entry` を読む互換の道は書かない
- 固定材料（`fix_fixture`）は start の控えを写して始めるので、古い固定材料（`input` が無い）は取り込みで拒む（今の `FIXTURE_MISMATCH` の道。canary の `units` の固定材料は Task 7 で作り直す）
- 盤面の層の golden（`tests/boards/`）は `state.works.begin` の引数が増えるので作り直す（作り直しの道具は今の物）
- 並行の束（PR・issue の読みを run の中へ移す束）とは `entry._change_base` の PR の道でぶつかる。その束の出荷の後に入れ、PR の欄の埋め方はその束の読み口を使う

## 10. Task（TDD の順）

試験の段: `test_entry`・`test_entry_inputs`・`test_board_begin` は今の段のまま（`test_board_begin` は HEAVY）。線の模擬実行（`test_line_*`）と `test_blk_spec` は HEAVY（手元では回さず CI に任せる。持ち主の決まり）。各 Task は赤い試験から書き、通してから commit する。実装する者へ: Task ごとに superpowers:subagent-driven-development（推し。Task の間の口が Interfaces で決まっているので、Task ごとの新しい目の審査が効く）か superpowers:executing-plans で回す。1 人なら 1 → 8 の順。2 人なら A が 1 → 2 → 3 → 4、B が 2 の commit の後から 5 → 6 を並べ、7・8 は両方が済んだ後に 1 人で（7 は 3 と 5 の文を読む）。

### 10.1 全体の縛り（どの Task にも効く）

- 写しの核（`works/.shared/core/graphloops/`）と台帳 `COPIED_FROM` は変えない。写しの振る舞いを替えるのは `entry.CORE_OVERRIDES` だけ
- 後ろの段（盤面・ブロック・境の節・報告）は入力の形の中身（`diff.empty`・`requests`・`pr`・`spec`）だけを読む。`from` は表示だけに使う
- 入力の形は最初の start で 1 度だけ作り、呼び直しは `r1/start.json` の `input` を読む（測り直さない）
- 試験は日本語の docstring・`unittest`・今の helper（`tests/linekit.py`・`tests/gitkit.py`）。HEAVY の試験は手元で回さず CI に任せる（push して `gh run` で見る）
- 版上げは最後の commit で、`VERSION_BUMP_STRICT=1` を手元でも（works の出荷の順）

### 10.2 見張る所（どの Task の試験も直に打たないが、使う人が踏みやすい物）

1. `--base` が HEAD と同じ版で、依頼が在る run（今の穴）: 判定から入り、空差分の柵で止まらない → Task 2 の `test_base_equal_head_with_request_enters_from_judging`
2. `--pr` の run で依頼のファイルも在る: 依頼の文に依頼と PR の題・本文の両方が載る → Task 1 の `test_request_text_carries_request_and_pr`
3. 呼び直し（Archon の再開）で修正が作業ツリーを変えた後: 入力は控えのまま、begin が別の引数と言わない → Task 2 の `test_resume_after_fix_keeps_frozen_input`
4. 仕様の段を選び、仕様の書き手が受け入れ条件のテストを書いた run: 印は start の測りのまま、柵で止まらない → Task 5 の `test_spec_tests_do_not_flip_the_mark`
5. 終わった run の古い控え（`input` が無い）を canary の確かめが読む: 落ちずに `not_exercised` → Task 7 の `test_old_start_doc_without_input_is_not_exercised`

### Task 1: 入力の形を作る（測りと拒み）

**Files:** Modify `works/.shared/core/board.py`（`diff_of` を `base_output` の隣に）・`works/.shared/core/entry.py`（`check_inputs`・`_change_base`・`_request_text`・`build_input`）。Test `works/tests/test_entry_inputs.py`・`works/tests/test_line_inputs.py`

**Interfaces:**
- Produces: `board.diff_of(repo: pathlib.Path, base_rev: str) -> dict`（`{"empty": bool, "files": int, "stat": str}`。写しの `_worktree_tree` を `util.GIT_CWD=repo` で呼び、終わったら戻す。木が引けなければ `Reject`）
- Produces: `check_inputs` の返りの `change` を `base`（`{"rev", "from", "name"}`）と `pr`（`{"number", "title", "body"} | None`）に替える。`base_rev` は今どおり（無ければ HEAD の 40 桁）
- Produces: `entry.build_input(inp: dict, repo: pathlib.Path) -> dict`（2.1 の形。`diff` は `diff_of`、`head_rev` は HEAD）
- Produces: `entry.EMPTY_REFUSED`（拒みの文の頭「直す物も審査する物も無い」）

- [ ] 赤: `test_diff_of_clean_head_is_empty`（種の git で `diff_of(repo, HEAD) == {"empty": True, "files": 0, …}`）・`test_diff_of_counts_untracked`（未追跡 1 本で `files == 1`。`.gitignore` の物は数えない）・`test_empty_diff_and_no_requests_refused`（`--base HEAD` だけ → `InputRefused` で文が `EMPTY_REFUSED` で始まり、盤面を作らない）・`test_request_text_carries_request_and_pr`（依頼のファイルと PR → `_request_text` が両方の見出しと本文を持つ）・`test_build_input_from_each_entry`（依頼だけ: `base.from == "head"`・`diff.empty`、`--base`: `from == "base"`・`files >= 1`、`--pr`: `pr.number == "7"`・`pr.title`）。今の `test_change_only_accepted_with_merge_base` ほか 4 本を `base`・`pr` の欄で書き直す。`test_line_inputs.FROM_CHANGE` を `{"base_rev", "base", "pr"}` に
- [ ] 回して赤を見る: `python3 works/tests/tiers.py fast -k test_entry_inputs`（または `python3 -m unittest works.tests.test_entry_inputs`）
- [ ] 入れる: `diff_of`・`build_input`・`check_inputs` の拒み（差分が空で依頼の行も空。`check_inputs` の中で `diff_of` を呼ぶ）・`_request_text`（在る物を「## 依頼」「## PR #N の題と本文」の見出しで並べる）
- [ ] 回して緑。commit `feat(works): 入口の入力を 1 つの形に揃える（差分の根・差分・依頼の行・PR を start が測って拒む）`

### Task 2: 盤面の始め方を 1 本にする（種を消す）

**Files:** Modify `works/.shared/core/board.py`（`DiskBoard.begin` の `diff_empty`）・`works/.shared/core/entry.py`（`CORE_OVERRIDES["entry_opens"]`・`start`・`_drain`・`resume_after_ci`、消す: `add_pending_request`・`PENDING_WAIT_NODE`・`ENTRIES`・`_entry_words`）・`works/darkfactory/lib/line_edge.py:109,919-922`。Test `works/tests/test_entry.py`・`works/tests/test_board_begin.py`・`works/tests/test_edge.py`。golden の作り直し（`tests/boards/`）

**Interfaces:**
- Consumes: Task 1 の `build_input`
- Produces: `DiskBoard.begin(…, diff_empty: bool | None = None)`（`state.works.begin.diff_empty` に控え、呼び直しの見分けに入る）
- Produces: `entry.entry_opens_by_diff(rl)`（`board.rl_builder`。写しの `entry_opens(b)` かつ `b.state["works"]["begin"].get("diff_empty") is True`。`None` なら写しのまま）
- Produces: `r1/start.json` と start の返りの欄 `input`（2.1）。欄 `entry`・`entry_words`・`change` は無い

- [ ] 赤（`test_entry.py`。種で名付けた 7 本を中身で名付けて書き直す）: `test_empty_diff_with_requests_sets_mark`（印が立ち、P1 の 9 節が依存の後に na）・`test_diff_with_requests_keeps_p1`（依頼のバッチが begin の時に 1 本・印なし・P1 が na でない・`start` の呼び直しで 2 本にならない）・`test_diff_without_requests_is_plain_review`・`test_base_equal_head_with_request_enters_from_judging`（今の穴。`--base HEAD` と依頼 → 印が立ち、`p1.worktree_before` が柵で止まらない）・`test_resume_after_fix_keeps_frozen_input`（start の後に作業ツリーへ 1 行足して start を呼び直す → `input` が同じ・BoardGap にならない）・`test_start_doc_has_input_not_entry`（控えに `input` が在り `entry` が無い）・`test_ci_role_wait_does_not_hold_requests`（今の `test_both_waits_for_frozen_revision_then_adds` の替わり: CI の任せ先を待つ run でも依頼は begin で積まれている）。`test_board_begin.py` に `test_begin_diff_empty_is_part_of_args`（同じ置き場で `diff_empty` だけ違う begin は BoardGap）・`test_entry_opens_override_needs_diff_empty`（`diff_empty=False` で items を渡すと印が立たない、`True` で立つ、`None` は写しのまま立つ）
- [ ] 回して赤を見る（`test_board_begin` は HEAVY なので、手元は `test_entry` だけ回し、`test_board_begin` は push して CI）
- [ ] 入れる: begin の引数、差し替え、start は `items=inp["items"] or None`・`diff_empty=input["diff"]["empty"]`、呼び直しは盤面の置き場の `r1/start.json` を begin の前に読んで `input` を使う。`_drain` から積みを消す。`line_edge` の h-mat の待ちの止めを消す。消す名を参照する物が残っていないことを `grep -rn "add_pending_request\|PENDING_WAIT_NODE\|ENTRIES\|_entry_words" works/` で見る
- [ ] golden の盤面を作り直す（`state.works.begin` に `diff_empty`）
- [ ] 回して緑。commit `refactor(works): 入口の種をやめ、依頼はいつも盤面を作る時に積み、印は入力の差分が空の時だけ立てる`

### Task 3: 種を読んでいた所を中身で読む

**Files:** Modify `works/.shared/core/conflict.py`（`change_only` 2 つ → `no_requests` 1 つ）・`blk-judge/scripts/intake.py`・`blk-premises/scripts/intake.py`・`blk-purpose/scripts/intake.py` と 3 本の yaml の入力の説明・`blk-judge/commands/diagnose.md:9`・`blk-purpose/commands/purpose.md:13,23`・`works/.shared/core/report.py:1110`・`works/.shared/core/entry.py`（`input_words`・頭の行）・`works/darkfactory/darkfactory.yaml`（start の出口・inputs の説明）・`works/darkfactory/fixtures/*.stubs.yaml`（13 本の `head_line`）・`works/darkfactory/nodes.json`（P1 の reason）。Test `works/tests/test_script_io.py`・`works/tests/test_report.py`・`works/tests/test_blk_judge.py`・`works/tests/test_blk_premises.py`・`works/tests/test_blk_purpose.py`

**Interfaces:**
- Consumes: Task 2 の控えの `input`
- Produces: `conflict.no_requests(board_dir) -> bool`（控えの `input.requests == 0`。控えが無い・欄が無ければ偽＝今どおり空を欠けと見る）
- Produces: `entry.input_words(input: dict) -> str`（5.2 の例の 3 形。差分が空なら「——P1 の役は起こさない」を付ける）

- [ ] 赤: `test_no_requests_lives_in_conflict`（`change_only` が無く `no_requests` が 1 つ）・3 ブロックに `test_intake_accepts_empty_request_when_input_has_no_requests` と `test_intake_refuses_empty_request_when_input_has_requests`（今の穴を埋める）・`test_input_words_shapes`（3 形の文）・`test_entry_words_from_start_doc` を `test_entry_line_from_input` に書き直す
- [ ] 回して赤（`test_blk_*` のうち HEAVY の物は CI）
- [ ] 入れる。stubs の `head_line` は `入口: 差分なし（HEAD）・依頼 2 件——P1 の役は起こさない` に揃える
- [ ] 回して緑（線の模擬実行の HEAVY は CI）。commit `refactor(works): 依頼の空の受け方・頭の行・報告の入口を入力の中身で決める`

### Task 4: PR の題と本文を目的の役へ渡す（並行の束が渡していなければ）

**Files:** Modify `works/.shared/core/entry.py`（start が盤面の根に `pr.md`）・`works/blk-purpose/blk-purpose.yaml`（入力 `pr_file`、空を受ける）・`works/blk-purpose/scripts/intake.py`・`works/blk-purpose/commands/purpose.md`（① PR 説明の出どころとして `pr_file`）・`works/darkfactory/darkfactory.yaml`（purposing の `with: pr_file: $start.output.pr_file`）。Test `works/tests/test_entry.py`・`works/tests/test_blk_purpose.py`

- [ ] 先に確かめる: 並行の束の出荷の後の `works/blk-purpose` と `ghreads` に PR の文を役へ渡す道が在れば、この Task は落とし、10 節の頭の順から外す
- [ ] 赤: `test_start_writes_pr_file_only_for_pr`（PR の run だけ盤面の根に `pr.md`、出口の `pr_file` がそのパス、ほかは空）・`test_purpose_intake_passes_pr_file`（役の指示書に PR の題と本文の置き場が載る）
- [ ] 入れる・緑・commit `feat(works): PR の題と本文を目的の役へ渡す（出典 ① PR 説明が --pr の run で空だった）`

### Task 5: 仕様の段を線に配線する

**Files:** Modify `works/darkfactory/darkfactory.yaml`（inputs `spec`・start の `with:`・`speccing`・`h-spec`・`pr-checking` の `when:` と `depends_on`）・`works/.shared/core/entry.py`（`check_inputs` の語 `spec` と拒む組・`begin(inputs={…, "flow": "spec"})`・`input.spec`）・`works/darkfactory/lib/line_edge.py`（`spec_edge`）・`works/darkfactory/scripts/edge.py`（`at: "spec"`）・`works/darkfactory/nodes.json`（`spec.write`・`spec.review`・`spec.revise` を role・blk-spec）・`works/darkfactory/darkfactory.graph.json`・`works/tests/linekit.py`（節の順）・`works/.shared/core/gatemarks.py`（`KIND_WORDS` に `spec_approval`）・`works/dev/use.sh`（`--spec`）。Test `works/tests/test_entry_inputs.py`・`works/tests/test_entry.py`・`works/tests/test_edge.py`・`works/tests/test_script_contract.py`（`UNWIRED` から blk-spec を外す）・`works/tests/test_blk_spec.py`（試験用の表を線の表に替える）・`works/tests/test_use.py`・線の模擬実行の fixture（`works/darkfactory/fixtures/spec.stubs.yaml` を新設）

**Interfaces:**
- Consumes: Task 2 の begin と控え
- Produces: 線の入力 `spec`（空か `on`）。`input.spec: bool`
- Produces: `line_edge.spec_edge(b) -> dict`（`{"go": True, "pr_go": <_pr_go の 3 値を真偽に>}`。中で `entry.resume_after_ci(b)` と同じ輪を回す。仕様の無い run では `entry_edge` と同じ値）

- [ ] 赤: `test_spec_word_checked`（`spec=yes` は拒む・`on` は通る）・`test_spec_refused_without_request_text`・`test_spec_refused_when_unattended`・`test_spec_refused_with_fixture`・`test_spec_reaches_board_flow`（盤面の `inputs.flow == "spec"`・`loop.flow == "spec"`・`spec.write` が ready）・`test_spec_tests_do_not_flip_the_mark`（差分が空・依頼ありで仕様の段 → 書き手の stub がテストのファイルを足した後も印が在り、`p1.worktree_before` が通る）・`test_spec_edge_drains_parallel_pr`（`spec.freeze` の後に `spec_edge` が `p0.parallel_pr` を回して `pr_go` を出す）・`test_spec_write_sees_request_rows`（`spec.write` の指示書に依頼の行が載る）・`test_use_spec_flag`（`use.sh start --spec` が `--input spec=on`）
- [ ] 回して赤（`test_blk_spec`・線の模擬実行は HEAVY で CI）
- [ ] 入れる
- [ ] 線の模擬実行で、include の中の approval（blk-spec の `spec-gate`）で run が止まり、答えで続くことを確かめる（stub の run。止まらなければ、承認を線の最上段の approval に移す形に替え、この文書の 4.3 の 4 を書き直す）
- [ ] 回して緑。commit `feat(works): 仕様の段（blk-spec）を入口の種に依らない任意の段として線に配線する（入力 spec）`

### Task 6: 修正の後の受け入れ条件の変わりを最後の関所で答える

**Files:** Modify `works/darkfactory/lib/line_edge.py:542-547`（h-final が `spec.check` の問いを関所の項目に載せる）・最後の関所の答えを盤面へ渡す所（今の final-gate の答えの節の script）・`works/.shared/core/gatemarks.py`（`KIND_WORDS` に `spec_changed`）。Test `works/tests/test_edge.py`

- [ ] 赤: `test_final_gate_answers_spec_changed`（`spec.check` が `spec_changed` を問う盤面で、h-final の関所の文に変わったファイルが載り、continue で `record.process.spec.amendments` に 1 行・stop で盤面が止まる）・`test_final_gate_still_ignores_other_pending`（ほかの問いには今どおり「この関所の答えはこの問いに答えない」）
- [ ] 入れる・緑・commit `feat(works): 修正の後に受け入れ条件のテストが変わった問いを最後の関所で答える`

### Task 7: canary・文書・版上げ

**Files:** Modify `works/dev/canary.sh`（`--diff`、語 `change` を拒む）・`works/dev/canary_check.py`（(h)(j) を `input.diff.empty` で選ぶ）・`works/dev/use.sh:810-814`（表示）・`works/skills/works/SKILL.md`・`works/README.md`・`works/docs/darkfactory-flow.md`・`works/CHANGELOG.md`・版の控え。Test `works/tests/test_canary.py`・`works/tests/test_canary_sh.py`

- [ ] 赤: `test_diff_flag_adds_one_uncommitted_line_and_base`（今の 83 を書き直す）・`test_change_word_refused_with_replacement`（文に `--request fix --diff`）・`test_local_review_checks_follow_input_diff`（`input.diff.empty` が偽なら (h)(j) が終了コードに入る、真なら `not_exercised`）・`test_old_start_doc_without_input_is_not_exercised`
- [ ] 入れる。`canary_check.REQUESTS` から `change` を消す。canary の固定材料（`dev/canary-fixture-units/`）は新しい控えの形で作り直す（`fix_fixture` の取り込みが古い控えを拒むため。作り直しの手順は `canary.sh` の頭の注記の今の物）
- [ ] 文書: 入口の節を入力の形で書き直す。CHANGELOG の [Unreleased] に「入口の種（`entry`）をやめ、入力の形 `input` に」「差分が空の `--base`・`--pr` と依頼の run が柵で止まっていた穴」「差分も依頼も無い run を CI の前に拒む」「仕様の段（`--spec`）」「canary の `--request change` → `--request fix --diff`」
- [ ] 最後の commit で版を上げる（`VERSION_BUMP_STRICT=1`）。push して `gh run` で CI（HEAVY を含む）が緑かを見る

### Task 8: 本物の run で確かめる（コードの変更なし）

- [ ] `canary.sh --request fix --diff`: (a)〜(e) と (h)(j) が yes
- [ ] `canary.sh --request fix`（差分なし）: 頭の行が「差分なし（HEAD）・依頼 N 件——P1 の役は起こさない」、(h)(j) は `not_exercised`
- [ ] 仕様の段の run（canary の種に `--spec`）: 仕様の承認の関所で止まり、答えで判定へ進み、判定の材料に受け入れ条件のバッチ（出どころ `SPEC_ORIGIN`）が在る
- [ ] 結果をこの文書の末尾の節に書き、状態の行を「入れた」に替える
