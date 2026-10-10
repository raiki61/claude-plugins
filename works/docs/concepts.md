<!-- coldwrite:skip 内部の設計の地図。語は冒頭の「語」の節で定義 -->
# 考えの住処の地図（works の設計の考えが、どこに 1 つの形で住んでいるか）

状態: 2026-10-09 の版 22d98fdc の事実で作った初版を、0.2.52（04137594）で柵を走らせて確かめ直し、既知の漏れのうちコードの重なり（読んだ証拠の名・止め札の名・宣言のファイルの名・申し出の欄の名）と、core とブロックが境の節の名を書いていた所を住処へ寄せた。0.2.55 の後に `carry-over` を `.shared/core/carry.py` へ、`stop-reasons` を `.shared/core/stopby.py` へまとめて住処ありにし、残りの散らばりにも数の歯止め（今の知る場所の数が増えない柵）を掛けた。`entry-kind` と `start-record` は入口のブロック `blk-entry` と core の `entryshape`・`startrec` へまとめて住処ありにした（計画 one-entry-shape）。`human-gates` は core の `gatepolicy` へまとめて住処ありにした（境の節は線の入力を写さず始めの記録を読む）。行のパスは試験（`tests/test_concept_fences.py`）が在ることを確かめる（予定の物は「予定」と書き、試験は見ない）。

## 平たく言うと（3 行）

- works の設計の考え（「run の結末」「止めの理由」「無人で回す時の方針」など）ごとに、それを 1 か所で持つ部品（住処）と、その考えを知ってよい所を 1 行ずつ並べた地図。
- 住処の在る考えは、住処の外に漏れたら試験で分かるようにする（柵。計画 `docs/plans/2026-10-09-structure-viewpoint.md` の Task 1）。住処の無い考え（散らばり）は、まとめる計画へのリンクを持ち、今の知る場所の数が増えない歯止め（数の歯止め）を持つ。
- 直す人（人も AI も）は、設計を始める前にここを読み、触る考えの住処を使う。住処の無い考えに足す時は、散らばりを増やさない形を先に選ぶ。

## 語

- 考え（concept）: 設計の 1 つの決まりごと。名前を付けて話せる単位（例: 「run の結末は 10 語のどれか」「止め札を見たら後ろを飛ばして報告へ」）
- 住処（home）: その考えを 1 か所で持つ部品。モジュール・ブロック（`blk-*`）・schema・表のどれか。考えを変える時に触るのはここだけ、になっている所
- 約束（contract）: 住処の外の人がその考えに触れる時の形を決めたファイルか欄（JSON Schema・YAML の出口の型・定数の表）
- 知ってよい所（allowed places）: 住処のほかに、その考えの語・欄の名・値を書いてよい所。普通は住処・約束・その考えの入口（殻）だけ。柵が照らす一覧は表 `docs/concepts.json` の `allowed` で、その全部を地図の行（住処・約束・知ってよい所）が字で名指す（試験が照らす）
- 漏れ（leak）: 知ってよい所の外に、その考えの語・欄の名・値が書かれていること。漏れた所は、考えが変わった時に一緒に直す必要があるのに、誰もそれを知らない所になる
- 散らばり: 住処の無い考え。同じ考えを複数の所がそれぞれの形で知っている状態
- 柵（fence）: 漏れを見つける安い試験。考えの語の形（正規表現）と知ってよい所を表に書き、表の外で語が見つかったら赤にする。今ある漏れは「既知の漏れ」として件数と理由つきで表に置き、減らす向きにだけ動かす（`tests/blockblind.py` と同じ型）
- 状態: `住処あり`（住処が在り、柵を掛けられる）か `散らばり`（住処が無い。計画へのリンクを持つ）。どちらも柵を持つ
- 結んだ写し（bound）: 流れの道具が値を決まった置き場からしか読まないなど、写しを消せない時に、源の値とちょうど揃うことを試験が縛った写しの行。柵の表の bound（{paths, lines, by, why}）に置き、by の試験が表の行を読んで「縛った行ちょうど」であることを確かめる。柵はその行を数えない（`.shared/core/conceptfence.py` の `count_lines`）。縛りを証せない行は数えたまま
- 数の歯止め: 散らばりの考えの柵。知ってよい所が空で、今その考えを知っている所を全部既知の漏れとして件数つきで表に置く。まとめるたびに数が減り、増やす差分は試験が赤にする。住処ありにした時は、知ってよい所に住処を書いて柵を住処の柵に替える

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
| `entry-kind` | 入口の種類（依頼・変更・PR） | 住処あり |
| `start-record` | 始めの記録 `r1/start.json` | 住処あり |
| `carry-over` | 次の run への持ち越し | 住処あり |
| `human-gates` | 人の関所と無人の方針 | 住処あり |
| `ai-launch` | AI の起こし方（模型・effort・道具・隔離） | 散らばり |
| `ledger` | 費用と時間の帳簿 | 散らばり |
| `prompt-assembly` | 指示書の組み立て | 散らばり |
| `prompt-sections` | 指示書に機械が貼る節の見出しの宣言 | 住処あり |
| `lanes` | 並べの枝 | 住処あり |
| `marks` | 返答の足し欄 | 住処あり |
| `plan-scope` | 修正案の項目の範囲の照らし | 住処あり |
| `test-files` | テストのファイルの見分け | 住処あり |
| `web-get` | 機械の web の取得と run をまたぐ控え | 住処あり |
| `world` | 世界の解（問題の類ごとの定石と、依頼の解き方との比べ） | 住処あり |
| `stop-reasons` | 止めの理由 | 住処あり |
| `core-seams` | 写しの核の差し替えの口 | 散らばり |
| `lang-names` | 特定の言語・テストの実行器の名 | 散らばり |

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
- 住処: `.shared/core/reads.py`（集める口と、盤面の置き場の名の口 `evidence_name`（役ごとの証拠）・`index_name`（集めた側の索引）・`is_index`・`EVIDENCE_GLOB`。置き場の名を使う所はこの口から引く。引けない所は柵の表の既知の漏れ。役が web を引いた記録 `web_fetches`（取得した URL）・`web_searches`（検索の問い）も出来事から引き、証拠の欄 `web` に書く）
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
- 知ってよい所: 住処と約束だけが控えの名を書き、欄を手で足す・外す。欄の意味（欄の型・欠けと誤りの検査・控えの中身の形・読んだ後の使い方）は欄を持つモジュール（`.shared/core/gatemarks.py`・`.shared/core/planmarks.py`・`.shared/core/deltamarks.py`・`.shared/core/converge.py`・`.shared/core/querytest.py`・`.shared/core/outpurpose.py`・`.shared/core/prcheck.py`・依頼の解き方 `means` の `.shared/core/worldmark.py`）が持ち、手順は住処を呼ぶ。手直しの役の申告 `bash_writes` は種 `writes` で `.shared/core/refix.py` が足す（外すのは `.shared/core/writes.py`、控えは書き込みの記録）。`.shared/core/converge.py` は外した欄を足し欄の控えでなく壁打ちの往復の記録に置く。役の印は `.shared/core/node_marker.py`（別の考え）
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

### `web-get` 機械の web の取得と run をまたぐ控え

- 状態: 住処あり
- 住処: `.shared/core/webget.py`（層 L1。網に出してよい URL `safe_url`・転送の決まり `SafeRedirect`・取得 `http_get`（期限を持たない）・網に出ない切り替え `is_off`・run をまたぐ控えの置き場 `shared_root` と控え `Store`（名ごとの JSON。schema・状態・期限で選ぶ））
- 約束: 口の形だけ（切り替えの名・控えの schema と期限・読む量の上限は呼ぶ側が持つ）
- 知ってよい所: 住処だけが網の素の口（`urllib.request`・`http.client`・`urlopen`）を使う（写しの graphloops は柵の外。表の exclude）。使う所はライブラリの文書の節 `.shared/core/libdocs.py`（切り替え `WORKS_LIBDOCS_WEB`・控えの期限 7 日・読む量の上限）と公式の文書の口 `.shared/core/libdocs_web.py`（`safe_url` で docs の場所を選ぶ）と世界の解のブロック（`blk-world/lib/worldblk.py` が取り直し（`fetch`）・`blk-world/lib/worldcheck.py` が転送の決まり `safe_url` と取れない時の例外）で、どれも住処を呼ぶ。役が自分で引く web（道具の WebSearch・WebFetch）は別の考えで、その記録は `reads`（`web_fetches`・`web_searches`）
- 今: 計画 `docs/plans/2026-10-09-world-solution.md` の W1 で libdocs の中から寄せた（振る舞いは同じ）。同じ計画の W5 で世界の解のブロックが 2 つめの使う所になった

### `world` 世界の解（問題の類ごとの定石と、依頼の解き方との比べ）

- 状態: 住処あり
- 住処: `.shared/core/worldmark.py`（行の欄の名 `FIELDS`・行のファイルの名 `WORLD_FILE`・控えの名 `STATE_FILE`・語 `VERDICTS`・`BASES`・名指しの句 `NOT_WEB`・先例の出どころの頭の字 `SOURCE_PREFIX`・読み書き `rows`・`read`・`write`・`stage_rows`・頭の節 `section`・答えの要る行 `needs`・`need`・`unanswered`・依頼の解き方との比べの文 `challenges`・関所の軸 `world_ok`・関所の行 `gate_line`・報告の節「世界の解」の行 `report_lines`・先例の出どころが実在の行かの照らし `ref_problems`。依頼の解き方の足し欄 `MEANS` の意味 `with_means`・`split_means`・`write_means`・`means_of`。足す・外す・置く手順は考え `marks` の種 `means`）
- 約束: `blk-world/world-row.schema.json`（欄と語が住処の定数と揃うことは `tests/test_worldmark.py` が縛る）
- 知ってよい所: 住処・約束・ブロック `blk-world/` の中・線 `darkfactory/`（出口を盤面の根の控えに写す境の節）・控えを読むブロックの宣言 `blk-*/manifest.json`（consumes。盤面の読み書きの約束）
- 今: 計画 `docs/plans/2026-10-09-world-solution.md` の W4〜W10 で入った。行を書くのはブロック `blk-world`（W5）で、線は目的の後・判定の前に 1 回だけ回し、境の節が出口を盤面の根の控えに写す（W7）。読むのは全部住処の口で、判定の支度 `blk-judge/lib/judgebrief.py`（頭の節）・修正案の頭 `blk-plan/lib/planblk.py`（頭の節と答えの頼み）・修正案の受け付けの答えの表 `.shared/core/planrange.py`（`answer_tables`）・関所の軸 `.shared/core/gatemarks.py`（`axes`）・報告 `.shared/core/report.py`（節「世界の解」）。判定の受け付け（`blk-judge/lib/judgetake.py` と core の `.shared/core/accept.py` の `check_judge`）は、先例の出どころ `world:<類の id>` が実在の行かを住処の口 `ref_problems` で照らす。依頼の解き方を目的の文から分けるのは目的の受け付け `.shared/core/purpose.py`（W6）。段の時間は控えに持たず、報告の節にも出さない（考え `ledger` の散らばりを増やさない。流れの道具の出来事から作れる値で、費用は報告の「費用」の節が節ごとに、段の時間は測りの殻 `dev/canary_check.py` が段ごとに出す）。柵は行のファイルと控えの名の字

### `stop-reasons` 止めの理由

- 状態: 住処あり
- 住処: `.shared/core/stopby.py`（層 L1。標準ライブラリだけ。機械の語の頭 `HEAD`（`works:`）と頭の読み `is_line`、決まりが core に在る段の語と 2 つ以上の持ち主が共に書く語の表 `REASONS`（名 → 意味）とその定数 `ADAPTER`・`FIX` など、ブロックとラインが自分だけの語を足す口 `declare`（表の名・別の意味で足された名を拒む）と `declared`）
- 約束: 語の字は盤面の `state.stop.by`・答えを待つ `process.human_items` の行の `node`・裁定の `by`・trace の行の `by` に残るので変えない（寄せる前の字の一覧を `tests/test_stopby.py` が縛る）。報告の結末の口 `.shared/core/report.py` の `stop_outcome` は `is_line` の語を `stopped_by_line` と読む
- 知ってよい所: 住処だけ。core の書き手は住処の定数を引き、自分の定数に写さない。ブロックとラインの自分だけの語は `declare("名", "意味")` で足して返りを自分の定数に置く（例 `blk-eyes/lib/eyes.py` の `STOP_BY`・`darkfactory/lib/line_edge.py` の `PROTECTED_BY`。ほかのブロックの語は引かない）
- 今: 寄せる前は 24 の `.py` が 35 行で語を字のまま持ち、同じ語を重ねて持っていた（`works:adapter` は 4 か所、`works:fix` は 3 か所。線は前提と目的の語を別の名の定数に写していた）。柵は語の字（`"works:<名>"`・頭の `"works:"`・f-string の頭）と、住処の定数を別の名に写す形（`X = stopby.ADAPTER`・`from stopby import`・`import stopby as`）を見る。人の止め（`human:`・`request:`・`answer`）は人の関所の考え `human-gates` の物で、ここには入れない

### `entry-kind` 入口の種類

- 状態: 住処あり
- 住処: 入口のブロック `blk-entry`（線の最初のブロック。起動の関所 launch と節 open。中身は core の `entry.start`）と、その中身が入口の種類に触れる core の唯一のモジュール `.shared/core/entryshape.py`（差分の根の名指しの解き `change_base`・差分も依頼の行も無い入力の拒み `refuse_empty`・入口の入力の形を作る `build`・盤面の依頼の文 `request_text`・名指した PR と issue の読み `named`・`github_reads`・PR の添え物の置き `write_pr_file`）
- 約束: `blk-entry/schemas/input.schema.json`（入口の入力の形。始めの記録の欄 `input` と節 open の出口の欄 `input`。後ろの段はこの中身——差分が空か・依頼の行の数・PR の添え物・仕様の段を挟むか——だけを読む。`base.from` は表示の名札で、出どころの文は `base.label`）
- 知ってよい所: 住処と約束と、生の事実を集める殻 `dev/use.sh`（旗 `--base`・`--pr` を入力に写す）・`dev/canary.sh`（旗 `--diff` を `use.sh` の `--base` に写す試しの殻）と、線の入力を宣言して入口のブロックへ渡すだけの `darkfactory/darkfactory.yaml`。どの起動にも付ける起動の印 `launch_mark` は入口の種類でない生の事実（`dev/launch.py` は印か依頼の写しで run を結び、入口の種類で分かれない。計画 clean-whole の段 4.1）
- 今: 入口の種（`entry` の request・change・both）と、依頼を版が固まった後に積む道（`add_pending_request`）・種で空の依頼を受ける問い（`change_only`）・頭の行の種の文（`entry_words`）は消した。判定から入るか（P1 の役を起こさないか）は入力の差分が空かだけで決まり（`entry.CORE_OVERRIDES` の `entry_opens`。写しの核の印を立てる所の差し替え）、依頼を読むブロックが空の依頼を受けるかは依頼の行の数で決まる（`conflict.no_requests`）。柵は、差分の根の名指しを読む・渡す形と、入口の種類で分かれる形・消した種の名の 2 本。計画 `docs/plans/2026-10-09-one-entry-shape.md`（2.5 節）と `docs/plans/2026-10-09-clean-whole.md` の段 4

### `start-record` 始めの記録 `r1/start.json`

- 状態: 住処あり
- 住処: `.shared/core/startrec.py`（層 L1。置き場の名 `NAME`・`REL` と `path`、型つきの読み口 `read`・入口の入力の形の読み `shape`・`diff_empty`・`requests`、入口の文 `words`）
- 約束: `blk-entry/schemas/start.schema.json`（記録の全体。欄 `input` は `input.schema.json` と同じ形で、試験 `tests/test_entry_block.py` が揃いを縛る）と、書き手の宣言 `blk-entry/manifest.json`（読み手の宣言は `blk-*/manifest.json` の consumes）
- 知ってよい所: 住処と約束だけ。書き手は入口のブロックの節 open（core の `entry.start`）と固定材料の取り込み（`.shared/core/fixture.py`）で、どちらも置き場は住処から引く。読み手（`.shared/core/gatemarks.py`・`.shared/core/conflict.py`・`.shared/core/report.py`・`.shared/core/adapter.py`・`darkfactory/lib/depth.py`・`darkfactory/lib/line_edge.py`・殻 `dev/canary_check.py`・`dev/fixmeasure.py`・`dev/canary_fixture.py`）も住処の口を引く
- 今: 標準ライブラリだけで pack の兄弟を import しない殻の決まりの 2 か所（`dev/launch.py` の起動直後の結び・`dev/lib.sh` の python の 1 行）は置き場の字を自分で持ち、表の既知の漏れに置く。柵は置き場の名を字で書く形・置き場の名の別名（START_REL・START_FILE の名）・別の読み口（start_doc の名。前の版に在った名で、今は無い）

### `human-gates` 人の関所と無人の方針

- 状態: 住処あり
- 住処: `.shared/core/gatepolicy.py`（層 L1。線の入力と始めの記録の欄の名 `FINAL_KEY`・`UNATTENDED_KEY`、最後の関所の開き方の語 `FINAL_GATES`（既定 `ALWAYS`）と無人の語 `UNATTENDED`、入口の語の確かめ `check`（仕様の段と無人の組みも拒む）、始めの記録からの読み `final_mode`・`unattended`、最後の関所を開くかの決め `opens`、報告の頭の行の句 `head_words`、最後の関所の答えの行の kinds `FINAL_KIND`）
- 約束: 始めの記録 `blk-entry/schemas/start.schema.json` の 2 つの欄（書き手は入口の 1 か所。入口のブロックの出口には出さない）
- 知ってよい所: 住処と約束と、線の入力を受けて住処の `check` に渡す入口のブロック `blk-entry`（入力の宣言と、環境変数の名から入力の名への写し）。読み手（境の節 `darkfactory/lib/line_edge.py`・修正前の関所の決め手 `.shared/core/gatemarks.py`・案の直し `.shared/core/replan.py`・報告 `.shared/core/report.py`）は住処の口で始めの記録を読み、線の節ごとに入力を写さない
- 今: 前は境の節 18 か所が線の入力 `final_gate` を写して受け、入口・境の節が語の表を別々に持ち、無人の語と読みは `gatemarks` に在った（考えの知る場所 116 行・16 ファイル）。残る既知の漏れは、線の入力の宣言（`darkfactory/darkfactory.yaml`）・生の事実を集める殻の旗と既定（`dev/use.sh` は protected_only、`dev/dogfood.sh` は always で、線の既定 always と違う。計画 `docs/plans/2026-10-09-clean-whole.md` の段 5 の 2 の残り）と、写しの engine の init `--unattended` に当たる盤面の欄（`.shared/core/board.py`。engine の語）。人の止めの語（`human:`・`request:`・`answer`）・止める 4 種の柵の印・語 unattended の 2 つの意味の分け（借りたスキルの読み替え `.shared/borrow/unattended.md` はどの run でも当たる別の考え）は同じ段の残り。柵は語の字（住処の口 `gatepolicy.<名>` は数えない）と、住処の定数を別の名に写す形

---

## 散らばり

散らばりの考えは、どれも数の歯止めを持つ: 表 `docs/concepts.json` に語の形（`pattern`）と今の知る場所（`known`。ファイル → 行の数と理由）を置き、知ってよい所（`allowed`）は空。試験 `tests/test_concept_fences.py` が、今の木の数が表とちょうど揃うこと（増えても減っても赤）と、考えごとの既知の漏れの件数の和が main から分かれた所の表（HEAD と `origin/main` の分かれ目の同じファイル。`conceptfence.fork_ref`）より増えず、main に無いパスも出ないことを見る（main の表が引けない時は名前つきで見送る。CI の works の job は全履歴で取るので見送らない）。まとめる計画は `docs/plans/2026-10-09-clean-whole.md` の段 5。

### `ai-launch` AI の起こし方（模型・effort・道具・隔離）

- 状態: 散らばり
- 今: 模型と effort の正本は 2 つ（前付けを持つ役は `.shared/core/agents/*.md`、持たない役は `.shared/core/stage-models.json`）。各ブロックの YAML の AI の段の `model:`・`effort:` は Archon が段の YAML からしか読まない写しで、`tests/test_tool_parity.py` が全部の段で正本とちょうど揃うことを縛るので、柵の結んだ写しに数える（数えない）。道具（`allowed_tools`）は YAML の節ごとで、本線の役の定義とちょうど同じ段だけのファイル（`blk-delta`・`blk-lens`・`blk-rejudge`・`blk-structure`・`blk-world`）は同じ試験が縛るので結んだ写し、本線より広い道具の段を持つファイルは縛りを証せないので数えたまま。道具ゼロの隔離は印の旗 `isolated`（`.shared/core/node_marker.py`）と `blk-eyes/lib/eyes.py` の `TOOLS`・`ISOLATED_RUN_BY`。run の明示の模型 `WORKS_DEV_MODEL` は `.shared/core/adapter.py` と殻（`dev/archon.sh`・`dev/guard.sh`・`dev/launch.py`）が読む。知る場所の数は 2026-10-10 に結んだ写しを外して 230 行・37 ファイルから 107 行・32 ファイルになった（main の表は 221 行・36 ファイル）
- 計画: まだ無い

### `ledger` 費用と時間の帳簿

- 状態: 散らばり
- 今: 会話ごとの費用は `.shared/core/adapter.py`（`spend/` の控え・`restate_result`）、報告の費用は `.shared/core/report.py`（Archon の出来事の `data.spend.costUsd`）、再審の実額は `.shared/core/rejudge.py`（`actual_costs`）、時間は段ごとの `wall_s`（`.shared/core/structmark.py`・`blk-structure/lib/eye.py`）、測りは `dev/fixmeasure.py`・`dev/canary_check.py`・`dev/lib.sh` がそれぞれ読む
- 計画: まだ無い

### `prompt-assembly` 指示書の組み立て

- 状態: 散らばり
- 今: 写しの指示書を描く所は `.shared/core/rolekit.py` の `render_body` 1 つだが、「頭の節 → `---` → 写しの本文 → 役の定義 → 前の拒否」の並べはブロックごとに組む（`blk-plan/lib/planblk.py` の `head`・`brief_head`、`blk-eyes/lib/eyes.py` の `prep`、`blk-judge/lib/judgebrief.py`、`blk-material/lib/material.py`、`blk-spec/lib/specblk.py`、`blk-report/lib/report_roles.py`、`.shared/core/rejudge.py`、`.shared/core/design.py`）。貼る節の見出しの宣言は考え `prompt-sections` に寄せた。印「機械が貼った」は AI 向けの慣わしで付け方がそろわないので、範囲の定義には使わない
- 計画: まだ無い

### `prompt-sections` 指示書に機械が貼る節の見出しの宣言

- 状態: 住処あり
- 住処: `.shared/core/promptsection.py`（層 L1。標準ライブラリだけ。節の宣言 `Section`——見出しの字そのものの str の子で、出どころ `source` と人向けの理由 `human` の欄を持つ——と、受け手の宣言 `Receive`（役の印の名・節の定数・入る条件を判じる関数の完全な名）、宣言を並べる口 `declared_sections`）
- 約束: 受け手の側の表 `RECEIVES`（その役の指示書を組むブロックの lib のモジュール `blk-*/lib/*.py` の直下）。共有の定数は受け手も条件も持たず、受け手と条件は受け手の側の表だけが知る。出どころの 3 形は `input:<名>`（ブロックの入力。ブロックの lib の節だけ）・`board:<モジュール>.<定数>`（盤面のファイルの名を持つ定数を指し、字を写さない）・`fn:<モジュール>.<関数>`（節の中身を作る関数）
- 知ってよい所: 住処だけ。見出しの定数は役の支度のモジュール（`blk-*/lib/*.py`・`blk-*/scripts/*.py`・`darkfactory/lib/*.py`・`darkfactory/scripts/*.py`・`.shared/core/*.py`）の直下で `promptsection.Section(...)` の最初の引数に置く。型と口の定義が住処の外に写されないことを柵が見る
- 今: 範囲の正本は ast の柵 `tests/test_graphmap.py` の `RealLineCase.test_machine_headings_are_declared_sections`: 上のモジュールの docstring でない字面のうち、`#` の見出しの行を持つ物（f-string の穴の先に字が在る形も）は全部 `Section` の最初の引数に在る。見出しを貼るのでなく読む所（`re` の関数・文字列の照らしの method の引数・比べの項）は外す。穴を持つ見出しは `.format` の型にして呼び手が `X.format(...)` で埋める。宣言が解けること（`test_section_declarations_resolve`）と、受け手の表が現物と合うこと（`test_receives_match_the_code`）も同じ試験が見る
- 計画: 無し

### `core-seams` 写しの核の差し替えの口

- 状態: 散らばり
- 今: 口が 2 種類ある。走る時に写しの名を替える `.shared/core/entry.py` の `CORE_OVERRIDES`（組み手の印は `.shared/core/board.py` の `rl_builder`）と、写しのバイトを替える台帳 `.shared/core/COPIED_FROM` の `!` 行。どちらを使うかの決まりは文書に無く、`CORE_OVERRIDES` は入口のモジュールに同居している
- 計画: まだ無い

### `lang-names` 特定の言語・テストの実行器の名

- 状態: 散らばり
- 今: 役の指示書（`blk-*/commands`・`rules`・`prompts`）と core に特定の言語・テストの実行器の名を書かず、対象に依らない言い方にする（持ち主の決定 `lang-neutral`。事実上の標準の形式の名は名指してよいので数えない）。今その名を持つ所は、TDD の輪と実行器の口（`blk-fix/lib/tddloop.py` ほか）・言語ごとの読み方（`.shared/core/impact.py`・`.shared/core/libdocs.py`）・役の指示書の 3 本（`.shared/core/writerules/common.md`・`blk-fix/rules/tdd.md`・`blk-premises/commands/premises.md`）・試しの種と殻（`dev/`）・コメントと docstring。柵は言語と実行器の名の語（表 `docs/concepts.json`）で、新しい役の指示書が名を書けば赤になる（世界の解のブロックの指示書 `blk-world/commands` も、この柵で縛る）
- 計画: `docs/plans/2026-10-09-clean-whole.md` の Task 3.8（この柵）と `docs/plans/2026-10-09-lang-neutral-red.md`（赤の判定の言語中立）

---

## この地図の育て方

- 設計を始める時: 計画の「考えの棚卸し」の節（`docs/plans/2026-10-09-structure-viewpoint.md` の 4 節）で、触る考えの id をここから引く。無ければ新しい行を足す
- 出荷の前: 触った考えの行（住処・知ってよい所・状態）を今の姿に直す
- 散らばりを住処へまとめたら: 状態を `住処あり` にし、表 `docs/concepts.json` の柵の知ってよい所に住処を書き、残った既知の漏れを今の姿に直す（数は main の表より増やせない）
- 名の無い中身の写し（同じ行の並びを別の所に貼った物）は、地図に名の在る考えの柵には掛からない。それは写しの柵（表 `docs/copies.json`・道具 `.shared/core/copyfence.py`・試験 `tests/test_copy_fence.py`）が言語に依らない行の窓で見る。新しい写しは 1 か所へ寄せ、寄せられない訳があれば理由つきで表の既知に置く（既知の行の数の和は main の表より増やせない）
- 行のパスは試験 `tests/test_concept_fences.py` が在ることを確かめる。地図と表の id・状態の食い違いと、住処の外の漏れ（表の既知の漏れより増えた・減った・表に無い）も同じ試験が赤にする。既知の漏れの一覧と理由は表だけが持つ
