# run が前の run の落ちた理由を忘れる件を直す計画 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

## 何の計画か（初めて読む人向け）

works はこのリポジトリの `works/` に在るプラグインで、外の道具 Archon の上で、生産ライン darkfactory を回す。darkfactory は、人が JSON のファイルに書いた修正依頼を受け、判定役・修正案の役・修正役などの AI の役に順に仕事をさせ、最後に報告と「次の run の依頼の下書き」（`next-request.json`）を書く。1 回の実行を run と呼ぶ。

困っていること: run は前の run が落ちた理由を覚えていない。持ち主の申告では、ある依頼で同じ落ち方を 9 回くり返した（回数は申告で、測っていない）。忘れている理由は 2 つ。

1. 受け付けが最後まで通さなかった理由。受け付けとは、AI の役の返答を機械が規則で照らす段で、拒めば理由を書き、役は同じ会話で出し直す（多くは 3 回まで）。
2. 独立設計の目（記録の名は R2）が「作り直しが要る」（status `redesign-needed`）と言った理由。R2 は、修正とは別に一から設計した案と、修正の構造を突き合わせる AI の役。

この計画では、報告の段がこの 2 つを 1 つの成果物「前の run の落ちた理由」（記録の名 `prior_failures`）にまとめ、`next-request.json` に載せる。次の run では、判定役と修正案の役の材料にだけ貼る。前の run の判断を知らずに考える役（目的の役と R2 の独立設計）には渡さない。渡すと、独立に考えずに前の判断を追認するだけになるからである。

部品の間の受け渡しは、部品ごとの `manifest.json` に「読む物（consumes）」と「出す物（produces）」を宣言する仕組み（型は `works/.shared/core/manifest.schema.json`）に乗せる。

持ち主の機械の上に元の資料が在る（依頼 `~/.cache/works-dogfood/req-240.json`、独立設計 `~/.cache/works-dogfood/carry/240/design.json`、事前審査 `~/.cache/works-dogfood/carry/240/plan-converge/pass-2/p2.plan_review.json`）。この計画が頼る所は全部この文書に書き写したので、読まなくてよい。

**Tech Stack:** Python 3.12・標準ライブラリ・unittest

## 語の定め

- **受け付けの出口**: 受け付けが 1 行の JSON を出す所。口は次のとおり。
  - `script_io.emit_result`: 理由を `<scope の根>/reject-<fn>-<n>.txt` に書く。修正役の受け付け `fix-accept` など、`script_io.main` を通る受け付けが使う。
  - `rolekit.accept_role`: 盤面（run の記録の置き場）の節の受け付け。理由のファイルは上と同じ形で、控えは周の作業ファイル `role-rejects.json` に積む。
  - `rolekit.with_done`: 盤面の節でない受け付け。控えは盤面の根の `rejects-<名>.json`。
  - `ci_role`・`rejudge`・`blk-eyes`: それぞれ自分の控えを持つ。
- **include と scope の根**: include は、ブロック（`blk-*` のフォルダ。部品）をライン（`darkfactory/darkfactory.yaml`）に差し込む単位。scope の根は include ごとの置き場 `<盤面>/<include の名>/` で、ラインの最上段なら盤面の根（`script_io.scope_dir`）。
- **最後まで通らなかった**: その run でその受け付けの最後の結果が ok でないこと（3 回目の拒否で輪を抜けた・run がそこで止まった）。出し直して通った拒否は数えない。
- **独立の目**: 前の run の判断を知らずに考える役。目的の役（`blk-purpose`。依頼のファイルを生のまま読む）と、R2 の独立設計（`blk-plan` の `r2.design`。依頼の生は読まず、`design.py` が貼る節だけを読む）。

## 根本の原因（今の main のコードで確かめた）

1. 次の依頼の下書きを作る `report.next_request`（`works/.shared/core/report.py`）が積むのは、手直しの穴・修正がやらなかった単位・テストの赤・残り・レンズ・再審・人に回した単位・関所の問いだけ。受け付けの拒否の理由は積まない。
2. 拒否の理由のファイルは、受け付けが走った scope の根に在る。報告の節 `report` はラインの最上段で走るので、自分の scope の根を読んでも include の中の拒否は 1 件も見えない（事前審査が名指した穴 `reject_reasons_read_from_report_scope_only`）。
3. `reject-*.txt` は出し直しの 1 回ごとに書かれ、通った後も残る。全部を積むと、次の run の役は、もう通った返答の形の誤りまで突き合わせることになる（同じく `carried_rejects_include_recovered_retries`）。控えの形も口ごとに 5 通りあり、「最後に通ったか」を一様に読める所が無い。
4. R2 の作り直しの理由は、今は報告の残り（`report.residue` の「R2 が redesign-needed: …」の行）として `next-request.json` の findings（直す穴の行）に載る。findings は次の run の依頼そのものなので、目的の役が生のまま読み、その目的の文が R2 の独立設計の入力になる。前の run の判断が独立の目に届く道が、既に 1 本在る（同じく `design_drift_carried_rows_to_judge`）。

## 決めたこと（決まりは 1 つ。場合分けを持たない）

決まり: 「受け付けの出口は、その受け付けの最後の結果を scope の根の 1 つの控えに上書きで残す。run の終わりに最後の結果が ok でない物だけを、前の run の落ちた理由とする」。

- **決め 1（1 つの控え）:** どの口も `script_io.note_last(board, fn, out)` を 1 回呼ぶ。これは scope の根の `accept-last.json`（`{<fn の名>: {ok, reason_file, at}}`）の自分の行を上書きする。通れば ok が真の行で上書きされるので、出し直して通った拒否は消える。口の数は変えず、各口に 1 行足すだけ。
- **決め 2（1 つの成果物）:** 報告の段（`report.build`）が `prior_failures(b)` で、全部の scope の根（`scopes.scope_roots(b)` と盤面の根）の `accept-last.json` を読む。ok でない行の最後の理由の本文と、R2 が `redesign-needed` の reason を `[{where, text}]` にして `<盤面>/prior-failures.json` に書く。`darkfactory/manifest.json` の produces に `{"name": "prior-failures.json", "format": "json", "schema": "schemas/prior-failures.schema.json", "at": "root"}` を足す。報告の本文には 1 節（件数と行）を出す。
- **決め 3（次の依頼へ）:** `next-request.json` を常に object `{"findings": [...], "prior_failures": [...]}` にする。「配列か object か」を oneOf で書いても、engine の照らし（`validate_schema`）は oneOf を読まない（事前審査の穴 `next_request_schema_oneof_ignored`）。形を 1 つにすれば `type: object` で照らせる。依頼の型の正本 `ghreads.KEYS` に `prior_failures` を足し、`request_parts` が `[{where, text}]` を確かめて返す。R2 の作り直しの行は findings から外し、prior_failures にだけ載せる（根本の原因 4 を閉じる）。
- **決め 4（読み手は宣言で絞る）:** 入口（`entry.check_inputs`）が依頼の prior_failures を盤面の根の `prior-failures-in.json` に置く（`darkfactory/manifest.json` の produces、`at: root`）。consumes に宣言するのは `blk-judge` と `blk-plan` だけ。判定の材料（`judge-brief`）と修正案の役（`p2.fix_plan`）の材料に、「前の run で最後まで通らなかった物（直す穴ではない。同じ所で落ちない返答を出すための注意）」の節として貼る。ブロックはほかのブロックの名を書かず、配線は `darkfactory.yaml` だけが持つ。
- **決め 5（独立の目に届けない）:** 目的の役の指示書（`blk-purpose/commands/purpose.md`）に 1 行「依頼の `prior_failures` は前の run の判断で、目的の出典に使わない」を足す。R2 の独立設計は依頼の生を読まないので変えない。試験で「目的の役と `r2.design` の材料に prior_failures の字が無い」を見る。

## Global Constraints

- 編まない物: `works/blk-fix/lib/tddloop.py`・`works/dev/tdd-suite.sh`・`works/blk-fix/lib/fixgates.py`・blk-fix の fix／tdd の会話の扱い・`.github/`（並行の作業が持つ）。`fix-accept` は `script_io.emit_result` を通るので、決め 1 は blk-fix を編まずに効く。
- `blk-*` にほかのブロックの名を書かない。
- 写しの graphloops（本流から写した規則と engine）は変えない。
- 盤面の照らし（`scopes`）: `accept-last.json` は各 scope の根の私物、`prior-failures.json`・`prior-failures-in.json` は公開の produces。`tests/test_scopes.py` の名の一覧を合わせる。
- TDD・`PYTHONDONTWRITEBYTECODE=1`・`nice -n 19`。触った試験の後に `WORKS_TESTS=fast sh tests/run.sh` を 1 回、リポジトリの根で `sh ~/.cache/works-dogfood/rootfences.sh` を 1 回。

## Review Focus

- 決め 1 の上書きが、同じ fn の名を 2 つの include が使う時に混ざらないか（scope の根が別なので混ざらない見込み。試験で確かめる）。
- 決め 3 で `next-request.json` の形を変えるのは利用者に効く変更（Changed）。`dev/use.sh`・`skills/works` の文・報告の文にある「そのまま次の依頼にする」が object でも通るか。
- 決め 5 で目的の役が指示書を守らない時、受け付けに柵は無い。目的の文に prior_failures の字が混ざったかを受け付けで照らすかは、審査で決める。

### Task 1: 受け付けの最後の結果の控え `accept-last.json`

**Files:** Modify `.shared/core/script_io.py`（`note_last`・`emit_result`）・`.shared/core/rolekit.py`（`accept_role`・`with_done`）・`.shared/core/ci_role.py`・`.shared/core/rejudge.py`・`blk-eyes/lib/eyes.py`。Test `tests/test_script_io.py`・`tests/test_rolekit.py`

- [x] 赤: 拒否 2 回の後に通った fn は ok 真／3 回拒んだ fn は ok 偽で最後の reason_file／2 つの scope の同じ fn は別の行
- [x] 緑: `note_last` を書き、6 つの口から 1 行ずつ呼ぶ

### Task 2: 報告の成果物 `prior-failures.json` と報告の節

**Files:** Modify `.shared/core/report.py`（`prior_failures`・`build`）・`darkfactory/manifest.json`。Create `darkfactory/schemas/prior-failures.schema.json`。Test `tests/test_report.py`・`tests/test_scopes.py`

- [x] 赤: include の scope の根の ok 偽の行が載る／通った行は載らない／R2 が redesign-needed なら reason が載り、findings からは外れる
- [x] 緑

### Task 3: `next-request.json` を `{findings, prior_failures}` に、依頼の型に `prior_failures`

**Files:** Modify `.shared/core/report.py`（`build` の書き出し）・`darkfactory/schemas/next-request.schema.json`・`.shared/core/ghreads.py`（`KEYS`・`request_parts`）。Test `tests/test_report.py`・`tests/test_ghreads.py`

- [x] 赤: 書いた next-request.json を `request_parts` が読める／prior_failures の行の形の誤りを ValueError で拒む
- [x] 緑

### Task 4: 判定役と修正案の役にだけ貼る

**Files:** Modify `.shared/core/entry.py`（`check_inputs` が `prior-failures-in.json` を置く）・`darkfactory/manifest.json`・`blk-judge/manifest.json`・`blk-plan/manifest.json`（consumes）・`blk-judge/lib/judgebrief.py`・blk-plan の修正案の材料と指示書・`blk-judge/commands/diagnose.md`・`blk-purpose/commands/purpose.md`・`darkfactory/darkfactory.yaml`（要れば with の配線）。Test 判定・修正案・manifest の照らしの試験

- [x] 赤: 判定の材料と修正案の材料に節が在る／目的の役・R2 の材料に無い／consumes の照らしが通る
- [x] 緑。stubs の線（`darkfactory/fixtures/standard.stubs.yaml`）で、依頼に prior_failures を書いた run が報告まで通る

### Task 5: CHANGELOG と仕上げ

- [x] `[Unreleased]` に Added（prior_failures）と Changed（next-request.json の形）。版上げは出荷の最後の commit で別に行う

## 実装で決めたこと（2026-10-06・実装の時の決めの記録）

- **next-request.json の形（決め 3 の確定）:** いつも object `{"findings": [...], "prior_failures": [...]}` にする。落ちた物が無い run も `prior_failures: []` を書き、配列の形に戻さない。理由: 形を 1 つにすれば `next-request.schema.json` を `type: object` で照らせる（engine の照らしは oneOf を読まない）。読む側（`ghreads.request_parts`）は配列の形も今どおり読むので、前の版の下書きや手書きの配列の依頼は通る。findings が空の下書きが依頼の型（空でない findings）を通らないのは前の配列の形と同じで、変えない。
- **accept-last.json の行の欄:** `{ok, reason_file, reason, at}`。計画の 3 つに `reason`（本文の写し）を足した。CI の任せ先と再審の受け付けは拒否の本文を作業ファイルに積み、理由のファイルを書かないので、`reason_file` だけでは本文を引けない。報告は理由のファイルを先に読み、読めなければ `reason` を使う。
- **note_last を呼ぶ所:** `script_io.emit_result`・`rolekit.accept_role`・`ci_role`（行の名 `ci_<節>`）・`rejudge`（行の名 `rejudge_<節>`）の 4 か所。`rolekit.with_done` と blk-eyes は自分では呼ばない: どちらも出口が `emit_result` を通る（`script_io.main` の finish と、`rolekit.script_main` の take）ので、そこで 1 行になる。自分でも呼ぶと、同じ受け付けが別の名の 2 行になり、通った時に片方だけが上書きされうる。
- **TDD の輪の受け付け（blk-fix の tdd-step）は控えに書かない（0.2.30 の直し）:** tdd-step も `emit_result` を通るが、`last=False` で `note_last` を飛ばす。輪の拒否・投げ出しは、その単位を修正役へ引き渡す印で、run の落ちた理由ではない。行の名が単位を問わず 1 つ（`tdd_step`）なので、書くと ①投げ出した単位を後で修正役が直し、`fix-accept` が通っても ok 偽の行が残って次の run の prior_failures に載り、②前の単位の投げ出しが後の単位の通過で上書きされて消える。単位ごとの行に分けて「後で修正役の受け付けが通った単位の行を落とす」案も考えたが採らなかった: 輪の最後の結果を次の run に運ぶ理由が無い（修正役が直せなければ `fix-accept` の行が ok 偽で残り、それが落ちた理由になる）。
- **報告が読む scope の根:** 計画の `scopes.scope_roots(b)` ではなく、盤面の根と根の直下のフォルダの `accept-last.json` を全部読む。scope の登録（scopes.json）は周ごとで、盤面を開く前に scope の根へ書く受け付け（依頼の受け付けの前の役）は登録より先に書く。置き場を見れば、周も登録の有無も問わずに拾える。
- **R2 の行:** 残り（`report.residue`）の行のうち text が「R2 が redesign-needed」で始まる物を、where「独立の目 R2」の 1 行にまとめて prior_failures に載せる（独立の目の形を先に採り、検証器の同じ目の行は二重に載せない）。findings からは外すが、結末（round_limit）と報告の冒頭の残りの行は今どおり。
- **prior-failures-in.json を置く所:** `entry.check_inputs` は盤面を作らないので、置くのは `entry.start`（盤面を作った直後）。start の控え（start.json）には残さない。固定材料から始める run（fix_fixture）は判定と修正案を写しから使い、役を起こさないので置かない。
- **貼る口:** 節の文は `entry.prior_section` 1 か所で作り、blk-judge の判定の材料（judge-materials.md の末尾）と blk-plan の修正案の役の指示書の頭（同じ run の中の案の直しの修正案も）が呼ぶ。事前審査・案の直し（plan-revise。修正案の役と同じ会話の続きで、頭は会話に在る）・独立設計には貼らない。YAML の with の配線は要らなかった（どちらも盤面の根を読む）。
- **目的の役の柵（Review Focus の 3）:** 指示書に 1 行足しただけで、受け付けの照らしは足していない。試験は線の試験（`test_line_a` の PriorFailuresLineCase）で、判定の材料と修正案の指示書に在り、独立設計の指示書に無いことを見る。目的の役の返答は試験では見本なので、柵の要否は審査で決める。

## この計画が扱わない物（理由つき）

- **同じ理由で続けて落ちたら、会話で回す開発（superpowers の subagent-driven-development）や人の直書きへ渡すよう勧めること。** prior_failures が入った後なら、「今回の prior-failures.json の行と同じ where・同じ text の行が、依頼の prior_failures に在る」を 1 つの決まりにできる。ただ、役の key と理由の字は run ごとに変わる。照らしの字を何に固定するかは、実際の run の prior_failures を見てから決める。
- **run が裁いた問い（問いの台帳の decided）の引き継ぎ。** 独立設計は、この行を「人に問う関所だけへ」渡すよう分けている。関所の側の口は依頼の `answers` の欄が既に持つので、要るかどうかは prior_failures の運用を見て決める。
