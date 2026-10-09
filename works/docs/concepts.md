<!-- coldwrite:skip 内部の設計の地図。語は冒頭の「語」の節で定義 -->
# 考えの住処の地図（works の設計の考えが、どこに 1 つの形で住んでいるか）

状態: 2026-10-09 の版 22d98fdc の事実で作った初版を、0.2.52（04137594）で柵を走らせて確かめ直し、既知の漏れのうちコードの重なり（読んだ証拠の名・止め札の名・宣言のファイルの名・申し出の欄の名）と、core とブロックが境の節の名を書いていた所を住処へ寄せた。0.2.55 の後に `carry-over` を `.shared/core/carry.py` へまとめて住処ありにした。行のパスは試験（`tests/test_concept_fences.py`）が在ることを確かめる（予定の物は「予定」と書き、試験は見ない）。

## 平たく言うと（3 行）

- works の設計の考え（「run の結末」「止めの理由」「無人で回す時の方針」など）ごとに、それを 1 か所で持つ部品（住処）と、その考えを知ってよい所を 1 行ずつ並べた地図。
- 住処の在る考えは、住処の外に漏れたら試験で分かるようにする（柵。計画 `docs/plans/2026-10-09-structure-viewpoint.md` の Task 1）。住処の無い考え（散らばり）は、まとめる計画へのリンクを持つ。
- 直す人（人も AI も）は、設計を始める前にここを読み、触る考えの住処を使う。住処の無い考えに足す時は、散らばりを増やさない形を先に選ぶ。

## 語

- 考え（concept）: 設計の 1 つの決まりごと。名前を付けて話せる単位（例: 「run の結末は 10 語のどれか」「止め札を見たら後ろを飛ばして報告へ」）
- 住処（home）: その考えを 1 か所で持つ部品。モジュール・ブロック（`blk-*`）・schema・表のどれか。考えを変える時に触るのはここだけ、になっている所
- 約束（contract）: 住処の外の人がその考えに触れる時の形を決めたファイルか欄（JSON Schema・YAML の出口の型・定数の表）
- 知ってよい所（allowed places）: 住処のほかに、その考えの語・欄の名・値を書いてよい所。普通は住処・約束・その考えの入口（殻）だけ。柵が照らす一覧は表 `docs/concepts.json` の `allowed` で、その全部を地図の行（住処・約束・知ってよい所）が字で名指す（試験が照らす）
- 漏れ（leak）: 知ってよい所の外に、その考えの語・欄の名・値が書かれていること。漏れた所は、考えが変わった時に一緒に直す必要があるのに、誰もそれを知らない所になる
- 散らばり: 住処の無い考え。同じ考えを複数の所がそれぞれの形で知っている状態
- 柵（fence）: 漏れを見つける安い試験。考えの語の形（正規表現）と知ってよい所を表に書き、表の外で語が見つかったら赤にする。今ある漏れは「既知の漏れ」として件数と理由つきで表に置き、減らす向きにだけ動かす（`tests/blockblind.py` と同じ型）
- 状態: `住処あり`（住処が在り、柵を掛けられる）か `散らばり`（住処が無い。計画へのリンクを持つ）

works の用語（全体は `README.md` と `docs/darkfactory-flow.md`）のうち、ここで使う物:

- 線: 工程を並べた 1 本の流れ（ライン `darkfactory/darkfactory.yaml`）。ブロック（`blk-*`）は線に差し込む部品で、ほかのブロックを知らない
- 役: AI を起こす節。盤面: run の記録（`state.json` と周ごとの作業ファイル）。関所: 人に答えを聞いて止まる所
- 包み: AI の起動を間に入って包む殻（`.shared/core/adapter.py`）。殻: 人が打つ入口のシェル（`dev/use.sh` ほか）
- 印: 役の出力の型の頭に置く 1 行の名札（`.shared/core/node_marker.py`）

パスは全部 `works/` からの相対（このリポジトリの `works/` の下）。`写し` は本流 graphloops から写した、バイト一致で縛られた部分（`.shared/core/graphloops/` と台帳 `.shared/core/COPIED_FROM`）で、works は直さない。

## 一覧

| id | 考え | 状態 |
| --- | --- | --- |
| `outcome` | run の結末 | 住処あり |
| `depth` | 単位ごとの深さ（軽量・標準） | 住処あり |
| `features` | 機能の切り替え | 住処あり |
| `hinge` | 境の節（`h-*`） | 住処あり |
| `halt` | 止め札（外から止める） | 住処あり |
| `scope` | 部品の置き場と宣言 | 住処あり |
| `reads` | 読んだ証拠 | 住処あり |
| `conflict` | 食い違いの申し出 | 住処あり |
| `injectors` | 包みが足す system prompt の塊 | 住処あり |
| `replycontract` | 返答の契約（本文で返させて型を確かめる） | 住処あり |
| `writes` | 役の返答を盤面に書く規則 | 住処あり |
| `marks` | 返答の足し欄（写しの型が持てない works の欄） | 住処あり |
| `entry-kind` | 入口の種類（依頼・変更・PR） | 散らばり |
| `start-record` | 始めの記録 `r1/start.json` | 散らばり |
| `carry-over` | 次の run への持ち越し | 住処あり |
| `human-gates` | 人の関所と無人の方針 | 散らばり |
| `ai-launch` | AI の起こし方（模型・effort・道具・隔離） | 散らばり |
| `ledger` | 費用と時間の帳簿 | 散らばり |
| `prompt-assembly` | 指示書の組み立て | 散らばり |
| `lanes` | 並べの枝 | 住処あり |
| `marks` | 返答の足し欄 | 住処あり |
| `plan-scope` | 修正案の項目の範囲の照らし | 住処あり |
| `test-files` | テストのファイルの見分け | 住処あり |
| `stop-reasons` | 止めの理由 | 散らばり |
| `core-seams` | 写しの核の差し替えの口 | 散らばり |

---

## 住処あり

### `outcome` run の結末

- 状態: 住処あり
- 住処: `.shared/core/report.py` の `OUTCOMES`（10 語）と `decide_outcome`（盤面と止めの印から 1 語を決める）
- 約束: `darkfactory/darkfactory.yaml` の報告の節の出口 `outcome` の enum
- 知ってよい所: 住処・約束・`skills/works/SKILL.md`（利用者への説明）・`dev/`（測りの殻）
- 今: 結末の語（`"no_fix_needed"` など）を文字列で持つ `.py` は住処だけ（22d98fdc で数えた）

### `depth` 単位ごとの深さ

- 状態: 住処あり
- 住処: `darkfactory/lib/depth.py`（`unit_depth`・`decide_doc`・`raise_doc`・`skip_reason`）。口は `darkfactory/scripts/depth.py`
- 約束: ブロックへは平の入力 `skip`・`skip_optional`（省く理由の文）だけを渡す。ブロックは深さの語を知らない
- 知ってよい所: ライン `darkfactory/` の中（住処・`darkfactory/darkfactory.yaml`）と `.shared/core/entry.py`（入力 `thickness` の語を確かめる。柵の語の形には当たらない）

### `features` 機能の切り替え

- 状態: 住処あり
- 住処: `.shared/core/entry.py` の `FEATURES`（語 → 説明）と `features_off`・`features_on`
- 約束: `darkfactory/darkfactory.yaml` の入力 `features_off`・`features_on` と、start の出口の同じ名の欄（ブロックへは on・off・auto の平の入力）
- 知ってよい所: 住処・約束・殻（`dev/use.sh`・`dev/dogfood.sh`）

### `hinge` 境の節

- 状態: 住処あり
- 住処: `darkfactory/lib/line_edge.py`（中身）と `darkfactory/scripts/edge.py`（口）
- 約束: `darkfactory/darkfactory.yaml` の `h-*` 節の `output_format`
- 知ってよい所: ライン `darkfactory/` の中と測りの殻 `dev/`。ブロックと core は境の節の名を書かない（docstring・コメント・YAML の説明・誤りの文も。入力と振る舞いを形で述べ、どの節が呼ぶか・渡すかは線の側に書く）。柵は `h-<語>` の形の全部を見るので、節を足しても表を直さない

### `halt` 止め札

- 状態: 住処あり
- 住処: `.shared/core/halt.py`（`place`・`seen`・`over`・`STOP_FILE`）
- 約束: 盤面の `STOP`（`{reason, by, at}` の JSON）
- 知ってよい所: 住処・置く殻 `dev/stop.sh`・見る境の節 `darkfactory/lib/line_edge.py`

### `scope` 部品の置き場と宣言

- 状態: 住処あり
- 住処: `.shared/core/scopes.py`（manifest を読んで照らす・公開の名・持ち主。宣言のファイルの名は `MANIFEST`）
- 約束: `.shared/core/manifest.schema.json` と、ブロックとラインごとの `manifest.json`
- 知ってよい所: 住処・`.shared/core/entry.py`（盤面を開く口が scope を登録する）

### `reads` 読んだ証拠

- 状態: 住処あり
- 住処: `.shared/core/reads.py`（集める口と、盤面の置き場の名の口 `evidence_name`（役ごとの証拠）・`index_name`（集めた側の索引）・`is_index`・`EVIDENCE_GLOB`。置き場の名を使う所はこの口から引く。引けない所は柵の表の既知の漏れ）
- 約束: `.shared/core/reads.schema.json`
- 知ってよい所: 住処・包み `.shared/core/adapter.py`（読んだ記録の置き場）・Read のフックの殻 `.shared/core/record-read.py`・各ブロックの口 `blk-*/scripts/reads.py`（`blk-delta`・`blk-fix`・`blk-plan`・`blk-pr`・`blk-refix`）・それらの宣言 `blk-*/manifest.json`

### `conflict` 食い違いの申し出

- 状態: 住処あり
- 住処: `.shared/core/conflict.py`（`FIELDS`（欄の名 `WHY_FIELD`・`WHICH_FIELD`・`KIND_FIELD` を含む）・`DECISIONS`・`FIX_DECISIONS`・`fix_duty`）
- 約束: 住処の定数の表（申し出の欄と裁定の語）
- 知ってよい所: 住処・申し出を書いて裁く修正のブロック `blk-fix/`。直す義務の持ち主のモジュール（`tests/test_duty_owner.py` の `OWNERS`）は義務の集合を作るが、申し出の欄の名は書かない

### `injectors` 包みが足す system prompt の塊

- 状態: 住処あり
- 住処: `.shared/core/adapter.py` の `INJECTORS`（行ごとに 名・条件・作り方・必須か）と `inject`
- 約束: 表の行の形 `Injector`（同じファイル）
- 知ってよい所: 住処と、包みを起こす殻 `.shared/core/claude-adapter`。塊を足すのは表に行を足すことで、起動の分岐を足さない

### `replycontract` 返答の契約

- 状態: 住処あり
- 住処: `.shared/core/replycontract.py`
- 約束: 包みの旗 `text-reply`（印は `.shared/core/node_marker.py`）
- 知ってよい所: 住処・`.shared/core/adapter.py`（旗を見て呼ぶ）・`.shared/core/diverted.py`（下請けが返答の道具 StructuredOutput を継ぐ形を述べる）

### `writes` 役の返答を盤面に書く規則

- 状態: 住処あり（写し）
- 住処: `.shared/core/graphloops/engine/record.py` の `apply_writes`（写し。works は直さない）
- 約束: graph の節の `writes`（`.shared/core/graphloops/graphs/review-loop.json`）と rules の `WRITE_OPS`
- 知ってよい所: 写しの中だけ。works の側は盤面の口（`.shared/core/board.py`）を通す

### `lanes` 並べの枝

- 状態: 住処あり
- 住処: `blk-fix/lib/lanekit.py`（枝の数 `MAX_LANES`・節の名 `node_names`・締めの語 `JOINED`・`MERGED`・`BACK`・分け方 `groups`・実行器の読み替え `relocate`・出口 `fork_out`・切る `plant`・指しの確かめ `tree_ok`・印 `mark`・戻す `revert_strays`・当てる `merge`・`merge_in_order`・`shared`・`carry`・申し出 `claim_problems`・`park`・片付け `remove`）。単位の worktree の下回りは `blk-fix/lib/unitlanes.py`
- 約束: 段のモジュール `blk-fix/lib/tddlanes.py`・`blk-fix/lib/fixlanes.py` は差し替え口だけを持つ（何を枝に分けるか・枝の控えの形と置き場・枝の役の指示書・枝の確かめ・当てる時の段の照らし・当てた後の確かめ）。計画 `docs/plans/2026-10-09-lanes-home.md`
- 知ってよい所: 住処と `blk-fix/lib/unitlanes.py`。枝の数の写し（`blk-fix/blk-fix.yaml` の `<段>-lane-loop-1..3`、core の表 `.shared/core/adapter.py` の `KEYED_NODES`・`.shared/core/seat.py` の `SEATS`・`SKILL_NODES`・`AGENT_NODES`・`.shared/core/stage-models.json`）は字で並べる（Archon の YAML は節を字で並べ、core はブロックを読めない）。試験が `MAX_LANES` とちょうど揃うことを縛る（`tests/test_lanekit.py`・`tests/test_tdd_lane_wiring.py`・`tests/test_fix_lane_wiring.py`・`tests/test_adapter_lane.py`）
- 今: 同じ語 `lanes` が `blk-eyes/lib/eyes.py` の `LANES`（独立の目の筋）という別の考えにも使われている（この考えではない。柵の語の形には当たらない）

### `marks` 返答の足し欄

- 状態: 住処あり
- 住処: `.shared/core/marks.py`（種の表 `KINDS`＝節か役 → 行の在り処・盤面の控えの名・置き場、と手順の口 `add`（役の型に足す）・`rows`・`split`（受け付けが盤面へ渡す前に外す）・`path_of`・`write`・`load`（控えに置く・読み戻す））
- 約束: 盤面の控えの宣言 `blk-*/manifest.json`・`darkfactory/manifest.json` と控えの型 `blk-plan/schemas/gate-marks.schema.json`・`blk-plan/schemas/plan-fields.schema.json`・`blk-delta/schemas/delta-verdicts.schema.json`・`blk-judge/schemas/out-of-purpose.schema.json`・`blk-pr/schemas/pr-excluded.schema.json`
- 知ってよい所: 住処と約束だけが控えの名を書き、欄を手で足す・外す。欄の意味（欄の型・欠けと誤りの検査・控えの中身の形・読んだ後の使い方）は欄を持つモジュール（`.shared/core/gatemarks.py`・`.shared/core/planmarks.py`・`.shared/core/deltamarks.py`・`.shared/core/converge.py`・`.shared/core/querytest.py`・`.shared/core/outpurpose.py`・`.shared/core/prcheck.py`）が持ち、手順は住処を呼ぶ。手直しの役の申告 `bash_writes` は種 `writes` で `.shared/core/refix.py` が足す（外すのは `.shared/core/writes.py`、控えは書き込みの記録）。`.shared/core/converge.py` は外した欄を足し欄の控えでなく壁打ちの往復の記録に置く。役の印は `.shared/core/node_marker.py`（別の考え）
- 今: 修正役の欄（`.shared/core/recount.py` が足し、`.shared/core/writes.py`・`blk-fix/scripts/accept.py`・`blk-fix/lib/fixlanes.py`・`blk-fix/lib/unitrows.py` が外す）と報告の書き手の `terms`（`blk-report/lib/report_roles.py`）、報告が並行 PR の控えを自分の名で読む `.shared/core/report.py` は、同じ手順をまだ手で書く（柵の表の既知の漏れ。`blk-fix/lib/unitrows.py` の外し方は柵の字の形に当たらない。並行の作業が触っているので後で寄せる）。控えのパスを持ち主の定数で組む所（`.shared/core/accept.py`・`blk-plan/lib/planblk.py`・`.shared/core/refix.py`・`dev/canary_check.py`）は名を持たないが、`marks.path_of` に寄せられる
- 計画: `docs/plans/2026-10-09-marks-home.md`

### `plan-scope` 修正案の項目の範囲の照らし

- 状態: 住処あり
- 住処: `.shared/core/planrange.py`（項目の範囲 `inside`・`out_of_scope` の当たり `oos_hit`・`oos_hit_for`・範囲の相談の合意 `with_agreed`・許しのパス `permit_paths`・単位に結べないパスの外れ `outside`・盤面で照らす `check_paths`）
- 約束: 修正案の項目の欄 `allowed_paths`・`out_of_scope`（`blk-plan/schemas/plan-fields.schema.json`）
- 知ってよい所: 住処と、glob の当て方の下回りと項目の欄の読みを持つ `.shared/core/planmarks.py`（`glob_match`・`test_paths`）。使う所は修正の受け付けの照らし `blk-fix/lib/planscope.py`（単位に結べる行と欠けの照らしはそちら）と手直しの受け付け `.shared/core/refix.py`（`check_paths`）で、どちらも住処を呼ぶ
- 今: 同じ当て方を手で書く所が残る（`.shared/core/holeties.py`・`blk-fix/lib/consult.py`・`blk-plan/lib/ripple.py`。柵の表の既知の漏れ）。`.shared/core/protect.py` は守りのファイルの型を同じ下回りで当てる別の考え

### `test-files` テストのファイルの見分け

- 状態: 住処あり
- 住処: 名の慣習は `.shared/core/impact.py` の `is_test`（`TEST_NAME`・`TEST_STEM`・`TEST_TAIL`・`TEST_DIRS`。言語の表でなく名の形）、宣言と慣習を合わせた見分けは `blk-fix/lib/tddloop.py` の `declared_test_files`・`is_test_file`（宣言＝役の申告の test_files と修正案の受け入れのテスト・書き換えの名指しのパス）
- 約束: 文書の宣言は対象の git の属性 `linguist-documentation`（`impact` が読む）
- 知ってよい所: 住処だけが名の型を書く。`blk-fix/lib/tddloop.py` の `PYTEST_FILE` は pytest の既定の python_files（実行器が pytest の時の名指しの型）で、同じ住処に置く。使う所（`blk-fix/lib/fixgates.py`・`blk-plan/lib/ripple.py`・`blk-fix/lib/planscope.py`）は住処の口を呼ぶ
- 今: `.shared/core/entry.py` の `GATE_FILE_PATTERNS`（検証ゲートの定義のファイルの広めの型）は別の考えで、テストの名の型の字を含む（柵の表の既知の漏れ）。計画 `docs/plans/2026-10-09-lang-neutral-red.md`

### `carry-over` 次の run への持ち越し

- 状態: 住処あり
- 住処: `.shared/core/carry.py`（層 L1。依頼の容器の欄の名 `KEYS`・`ANSWER_KEYS`・`PRIOR_KEYS`、下書きの印 `DRAFT_KEYS` と `is_draft`・`draft`、盤面の根のファイルの名 `NEXT_REQUEST_FILE`・`PRIOR_FAILURES_FILE`・`PRIOR_IN_FILE`、依頼の解き方 `parts`・`without_prior`・`carry_ci`（殻の口 `carry-ci`）、次の依頼の中身 `compose`・行の鍵 `row_key`、照らしてから置く `save`・`place_prior`、役に貼る節 `prior_section`）
- 約束: `.shared/core/next-request.schema.json`・`.shared/core/prior-failures.schema.json`（住処が読み、書き手は書く前に照らし、読み手は前の失敗の行を照らす。欄の名の定数と Schema の欄が揃うことは `tests/test_carry_home.py` が縛る）と、盤面の根の置き場の宣言 `darkfactory/manifest.json`（書く物）・`blk-*/manifest.json`（読む物の consumes）
- 知ってよい所: 住処と約束だけ。何を運ぶかの決めは書き手の側が持ち、形は住処を呼ぶ: 残りの行と前の失敗の行は `.shared/core/report.py`（`next_request`・`prior_failures`・`next_doc`）、答えの下書きの選びは `.shared/core/gatemarks.py`（`answer_drafts`）、目的の外の所見の行は `.shared/core/outpurpose.py`（`next_items`）。読み手（`.shared/core/entry.py`・`blk-judge/scripts/intake.py`・`blk-premises/scripts/intake.py`・`blk-purpose/scripts/intake.py`・`blk-judge/lib/judgebrief.py`・`blk-plan/lib/planblk.py`・殻 `dev/lib.sh`）も住処の名と口を引く。`gatemarks.carried_section`（修正前の関所で人が通した行を同じ run の R4 に貼る）は run の中の受け渡しで、この考えではない
- 今: 欄の出どころの名 `source` は別の考え（目的の役の出どころ・素材の出どころ・プラグインの置き場）にも同じ名が多いので、柵は下書きの印を作りと読みの形（`"draft": True`・`"draft" in` など）で見る。容器の欄の名 `findings`・`answers`・`pr`・`issue` も別の考え（壁打ちの往復の `answers` など）と同じ字なので柵に入れず、呼び手が住処の定数（`carry.FINDINGS` など）を引く決まりだけで守る。利用者と役に読ませる文（`.shared/core/gatemarks.py` の答え方の案内 `ANSWER_HOW`・役の指示書・`skills/works/SKILL.md`）は容器の形を字で書く。計画 `docs/plans/2026-10-09-chained-rounds.md` の Task 1（作業の手順は `docs/plans/2026-10-09-carry-home.md`）。人が関所で決めた答えの持ち越しと、依頼の答えを問いに結ぶ所は同じ計画の Task 2

---

## 散らばり

### `entry-kind` 入口の種類

- 状態: 散らばり
- 今: 種（`request`・`change`・`both`）を `.shared/core/entry.py` が決め、盤面の始め方・依頼を積む時期・頭の行・`.shared/core/conflict.py` の `change_only`・`dev/canary.sh`・`dev/canary_check.py` が種で分かれる
- 予定の住処: 入口ブロック `blk-entry`（予定）と出口の約束 `darkfactory/schemas/input.schema.json`（予定）。後ろの段は種を知らず、入力の中身（差分が空か・依頼の行が在るか）だけを読む
- 計画: `docs/plans/2026-10-09-one-entry-shape.md`（枝 `wip/one-entry-plan`。この版にはまだ無い）

### `start-record` 始めの記録 `r1/start.json`

- 状態: 散らばり
- 今: 置き場の名を 3 か所が定める（`.shared/core/entry.py` の `START_FILE`・`.shared/core/adapter.py` の `START_REL`（`.shared/core/fixture.py` はこれを引く）・`.shared/core/gatemarks.py` の `START_FILE`）。約束 `darkfactory/schemas/start.schema.json` は `{"type": "object"}` だけで何も縛らない。読み手は `gatemarks.start_doc` のほか、`.shared/core/adapter.py`・`.shared/core/fixture.py`・`.shared/core/entry.py` と殻 `dev/canary_check.py`・`dev/launch.py` が直に読む
- 予定の住処: 入口ブロック `blk-entry`（予定）。置き場の名と読む口を 1 つにし、約束を控えの全体に広げる
- 計画: `docs/plans/2026-10-09-one-entry-shape.md` の 2.5 節（枝 `wip/one-entry-plan`）

### `human-gates` 人の関所と無人の方針

- 状態: 散らばり
- 今: 「無人の run か」は `gatemarks.unattended`（`.shared/core/gatemarks.py`）が 1 本で読むが、無人の時に何を変えるかは `.shared/core/replan.py`（範囲を広げるだけの直しを聞かずに通す）・`.shared/core/gatemarks.py`（問いを項目に載せない）・`.shared/core/board.py`（engine の `--unattended`）に分かれる。最後の関所を開く方針（`final_gate`）は `.shared/core/entry.py`・`.shared/core/report.py`・`darkfactory/lib/line_edge.py`・`darkfactory/darkfactory.yaml` が持つ。同じ語 `unattended` が、借りたスキルの読み替え `.shared/borrow/unattended.md`（どの run でも当たる）という別の考えにも使われている
- 計画: まだ無い

### `ai-launch` AI の起こし方（模型・effort・道具・隔離）

- 状態: 散らばり
- 今: 模型と effort の正本は 2 つ（前付けを持つ役は `.shared/core/agents/*.md`、持たない役は `.shared/core/stage-models.json`）で、各ブロックの YAML の節が値を写し、`tests/test_tool_parity.py` が食い違いを縛る。道具（`allowed_tools`）は YAML の節ごと、道具ゼロの隔離は印の旗 `isolated`（`.shared/core/node_marker.py`）と `blk-eyes/lib/eyes.py` の `TOOLS`・`ISOLATED_RUN_BY`。run の明示の模型 `WORKS_DEV_MODEL` は `.shared/core/adapter.py` と殻（`dev/archon.sh`・`dev/guard.sh`・`dev/launch.py`）が読む
- 計画: まだ無い

### `ledger` 費用と時間の帳簿

- 状態: 散らばり
- 今: 会話ごとの費用は `.shared/core/adapter.py`（`spend/` の控え・`restate_result`）、報告の費用は `.shared/core/report.py`（Archon の出来事の `data.spend.costUsd`）、再審の実額は `.shared/core/rejudge.py`（`actual_costs`）、時間は段ごとの `wall_s`（`.shared/core/structmark.py`・`blk-structure/lib/eye.py`）、測りは `dev/fixmeasure.py`・`dev/canary_check.py`・`dev/lib.sh` がそれぞれ読む
- 計画: まだ無い

### `prompt-assembly` 指示書の組み立て

- 状態: 散らばり
- 今: 写しの指示書を描く所は `.shared/core/rolekit.py` の `render_body` 1 つだが、「頭の節 → `---` → 写しの本文 → 役の定義 → 前の拒否」の並べはブロックごとに組む（`blk-plan/lib/planblk.py` の `head`・`brief_head`、`blk-eyes/lib/eyes.py` の `prep`、`blk-judge/lib/judgebrief.py`、`blk-material/lib/material.py`、`blk-spec/lib/specblk.py`、`blk-report/lib/report_roles.py`、`.shared/core/rejudge.py`、`.shared/core/design.py`）。「機械が貼った」節の見出しも各所の定数
- 計画: まだ無い

### `stop-reasons` 止めの理由

- 状態: 散らばり
- 今: 盤面の `state.stop.by` の語（`works:<名>`）を、26 の `.py` がそれぞれの定数で持つ（例 `.shared/core/lens.py` の `STOP_BY`・`.shared/core/premises.py` の `STOP_BY`・`blk-fix/scripts/assert_changed.py` の `STOP_BY`）。同じ値を別の所が重ねて持つ（`works:adapter` は `.shared/core/ci_role.py`・`.shared/core/report.py`・`blk-material/lib/material.py`、`works:fix` は 3 か所）。結末への写し（`works:` の頭なら `stopped_by_line`）は `outcome` の住処 `decide_outcome` に在る
- 計画: まだ無い

### `core-seams` 写しの核の差し替えの口

- 状態: 散らばり
- 今: 口が 2 種類ある。走る時に写しの名を替える `.shared/core/entry.py` の `CORE_OVERRIDES`（組み手の印は `.shared/core/board.py` の `rl_builder`）と、写しのバイトを替える台帳 `.shared/core/COPIED_FROM` の `!` 行。どちらを使うかの決まりは文書に無く、`CORE_OVERRIDES` は入口のモジュールに同居している
- 計画: まだ無い

---

## この地図の育て方

- 設計を始める時: 計画の「考えの棚卸し」の節（`docs/plans/2026-10-09-structure-viewpoint.md` の 4 節）で、触る考えの id をここから引く。無ければ新しい行を足す
- 出荷の前: 触った考えの行（住処・知ってよい所・状態）を今の姿に直す
- 散らばりを住処へまとめたら: 状態を `住処あり` にし、柵を表 `docs/concepts.json` に足す
- 行のパスは試験 `tests/test_concept_fences.py` が在ることを確かめる。地図と表の id・状態の食い違いと、住処の外の漏れ（表の既知の漏れより増えた・減った・表に無い）も同じ試験が赤にする。既知の漏れの一覧と理由は表だけが持つ
