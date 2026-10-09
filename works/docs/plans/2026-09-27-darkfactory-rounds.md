# darkfactory 周の輪（線 B）Implementation Plan（盤面の層に載せ替え）

状態: 合流させずに置いた（線 B の枝 wip/works-trackB は 2026-09-27 の 4ed5887b で止まり、main には無い）。

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. 下請けは全部 opus（台帳 Ruling R22）。

> この計画の `works/.shared/core/rounds.py` は線 B の枝（wip/works-trackB）にだけ在り、main にはまだ合流していない。

**Goal:** 別の入口 `darkfactory-rounds` を作り、graphloops の review-graph と同じ芯の規則で「直ったと言えるまで何周も回す」。周の中の順・周の記録・収束の判定は盤面の層（土台）が engine と同じに回し、線 B は周の間の人への問い（早く聞く・周の終わりに要るときだけ）・判定からのやり直し・集めない工程の宣言・mutgate の記録を読む最後の関門だけを足す。

**Architecture:** 土台の `DiskBoard`（`works/.shared/core/board.py`。engine の盤面を継ぐ）の上に、線 B のモジュール 4 つを置く: `rounds.py`（節の表と宣言の導き・start・状態ファイル・境の節・答え・`close_early`）、`close.py`（宣言の差し込み・周の締め・最後の関門）、`judge2.py`（判定の 1 回目と 2 回目）、`rounds_validator.py`（写しの検証器を記憶の中で包み `not_in_line` を足す）。写しは 1 バイトも変えず、土台の `overrides`（`validator_module`・`fill_materials`）と `validator_runner` だけで差し込む。ラインは輪の外の `launch`・`start`・`report` と、周の輪 `rounds`（`open` → blk-judge v2 → 境の節と線 A のブロック 5 つ → blk-close → `ask` → 唯一の末端の関所 `gate`）。どのブロックを走らせるかは境の節が盤面の ready から決める。

**Tech Stack:** Archon v0.11.1（公式の実行ファイル）・YAML・Python 3（pack の中は標準ライブラリだけ。テストだけ PyYAML を `uv run --with`）・uv・git・graphloops 0.21.0（a1202d0）の写し。

**Spec:** `works/docs/specs/2026-09-27-darkfactory-rounds-design.md`（改訂 6 まで。以下「仕様 N 節」）。持ち主の朝の 4 つの答え（2026-09-27）と回す側の指示の直しは末尾の「改訂（持ち主の答え 2026-09-27）」。会話の継ぎの試しは 作業の控え（scratchpad）の `resume-probe-summary.md`（以下〔継試〕）、本線の調べは 作業の控え（scratchpad）の `mainline-blocks-survey.md`（以下〔本〕）。仕様とこの計画は線 A の計画の Task 1 と同じ commit で置いた（T13 は試しの結果と実装で変わった所を仕様に書き戻す）。土台の仕様 `works/docs/specs/2026-09-26-board-layer-design.md`（以下〔土〕）、線 A の設計 `works/docs/specs/2026-09-27-darkfactory-single-run-design.md`（以下〔A〕）と計画 `works/docs/plans/2026-09-27-darkfactory-single-run.md`（以下〔A計〕。線 A の関数の名前はここから）、mutgate の設計 `works/docs/specs/2026-09-26-mutgate-design.md`（枝 `wip/works-mutgate`。以下〔C〕）。

**前提（波 0。着手の時に 1 度だけ確かめる）:**
- 土台の計画（〔土〕の計画 `works/docs/plans/2026-09-26-board-layer.md`）の Task 1〜10 が済み、写し直し → 土台 → 線 A の順で積まれている。確かめ: `works/.shared/core/board.py` に `DiskBoard.begin`・`answer`・`stop`・`finalize`・`_write_round_note`・`RecordInvalid` が在る。
- **枝の切り方（審査 I7）**: この計画の枝 `wip/works-rounds`（worktree `/Users/p03623/src/claude-plugins-work1-rounds`）は、**線 A の枝の先から切る**。条件は、線 A の Task 2（`blk-judge` に入力 `policy_paste`。〔A計〕T2）と TA18 の 4 件（`entry.open_board` が `board_hook.py` を読む・`entry.hook_kwargs`・`entry.local_checks_material` と `entry.run_ci`・`report.py` の `head_*` と `gate_record`・線 A の T2 の試験が `intake` に頼らない）が線 A の枝に commit されていること。どれかが無ければ切らずに coordinator に報告する。切った直後に `nice -n 19 sh works/tests/run.sh` と `sh works/dev/check.sh` が緑。
- 線 A のブロックの YAML（〔A計〕T17 の切り替え）が要るのは T11 から。T10 の前にこの枝を線 A の枝の先へ載せ直し、載せ直した直後に `sh works/dev/check.sh` を 1 度通す（線 A の 1 周のラインが v2 の blk-judge で緑か。審査 I7 の 3）。T1〜T9 は線 A の物を引数で差し込める形にし、試験は偽物でも回るようにする。
- 持ち主の答え（2026-09-27。仕様 1.3）: 軽量は下げない（線 B は手厚さの入力を持たない）。並行 PR・前提・目的・同じ周の再審は T15〜T17 で入れる。T1〜T14 はその前の形（該当の行は absent・理由に入る Task）で作り、T15〜T17 が行とラインを替える。再審（T17）は本線の 3-5・3-6 の写し直しの後（「写し直しへの依存」）。
- 線 A の物が要る: T15 は線 A の T21・T22（`prcheck`・`blk-pr`・`premises`・`blk-premises`・`judge_edge` と同じ決まり）、T17 は線 A の T5（包みの会話の継ぎ・`ticket.session_path`）と T23（`rejudge`・`blk-rejudge`）が線 A の枝に在ること。
- 費用のかかる物は 2 つだけで、どちらも持ち主の了承を取ってから: T8 の数セントの試し（P6b・P6c・P6e）と T14 の実走。

## Global Constraints

- 触ってよいのは `works/` の下の、線 B の持ち物だけ（〔土〕6 節）: `works/darkfactory-rounds/**`（`board_hook.py`・`downgrades.json` を含む）・`works/blk-close/**`・`works/blk-purpose/**`・`works/blk-judge/**`・`works/.shared/core/{rounds,close,judge2,rounds_validator}.py`・`works/tests/test_rounds_*.py`・`works/tests/test_blk_close.py`・`works/tests/test_blk_purpose.py`・`works/tests/test_blk_judge.py`・`works/tests/replies/purpose_*`・`works/tests/roundskit.py`・`works/tests/replies/judge2_*`・`works/tests/replies/rounds/**`・`works/tests/fixtures/mutgate-records/**`・`works/dev/probes/rounds/**`・`works/docs/specs/2026-09-27-darkfactory-rounds-design.md`。共有のファイル（〔土〕6 節の一覧: `tests/test_yaml_rules.py`・`tests/yaml_good/**`・`tests/yaml_bad/**`・`tests/test_line.py`・`tests/test_script_headers.py`・`tests/run.sh`・`dev/check.sh` などの開発の殻・`skills/works/SKILL.md`・`README.md`・`archon-plugin.json`・1 本目の仕様の冒頭の 1 行）は T13 の 1 commit でだけ触る。
- 土台の物（`board.py`・`accept.py`・`tests/test_board*.py`・`tests/boardreplay.py`・`tests/boards/**`・`dev/board-goldens/**`）と線 A の物（〔土〕6 節の A の行）は読むだけ（import してよい）。直したくなったら直さず、申し送りの文を Task の報告に書く（台帳への写しは持ち主の会話の側が行う）。
- **写し（`works/.shared/core/graphloops/**`・`works/.shared/core/scripts/**`・`COPIED_FROM`）は 1 バイトも変えない**（〔土〕BL2）。差し替えは土台の `overrides` に渡す RL の大域の名前 `validator_module`・`fill_materials` の 2 つだけ。写しの関数を呼ぶ所は線 B のモジュールの中の薄い関数 1 つずつに集める。
- pack の中の Python は標準ライブラリだけ。直に起こすスクリプト（`works/*/scripts/*.py`・`works/dev/**/*.py`・`rounds_validator.py`）は頭に PEP 723 の塊。`__pycache__` を作らない（テストは `PYTHONDONTWRITEBYTECODE=1`）。
- 新しい期限を足さない。足すなら `1728000000` だけ（bash・script の節の `timeout`、AI の節の `idle_timeout`。台帳 R4）。`loop_group` の `max_iterations` は判定の内の輪 6・周の輪 20。
- AI の節は `output_format`・`sandbox: {enabled: true, allowUnsandboxedCommands: false}`（R12）・`settingSources: []` を持ち、**`model:` を書かない**（利用者の選択。開発の殻の既定が opus）。役の節は自分の出し直しの輪の中のただ 1 つの AI の節で、`context: fresh` を書かない。関所の `decisions` は `reject` を持つ（R32）。
- include の id とブロックの中の節の id を重ねない（R17）。筋書きが stub する節の id は輪の本体の全部の include をまたいで一意（R19）。指示書は `$LOOP_PREV.<役>-accept.output.*` を本文で直に読む（R16）。
- 試験はお金 0: 単体テスト（Archon 不要）と `--dry-run` の筋書き。Archon の実行ファイルを AI 無しで回す試し（AI の節を bash に置き換えた工程）は前例（P7〜P16）どおり許す。**AI を起こす物（T8 の数セントの試し・T14 の実走）は持ち主の費用の了承の後だけ**。変異テストは回さない（mutgate の記録は見本のファイル）。
- テストは `nice -n 19` で前景。プロセスを止めるときは pid と cwd を確かめる。`pkill -f` を使わない。対象・開発の家・origin・切符の置き場を `/private/tmp/claude-*` の下に置かない（使い捨ての置き場は `${WORKS_DEV_HOME:-$HOME/.cache/works-dev}/rounds/`）。
- 盤面への書き込みは一時ファイルから `os.replace`。拒否（`Reject`）の回は盤面を書かず、その入れ物は捨てる（〔土〕4.1）。受け付けのスクリプトは拒否も終了コード 0 で `{"ok": false, "reason": "..."}`、入力が読めないときと内部の誤り（`BoardGap`）だけ 2。JSON は `ensure_ascii=False`。
- ブロックと script の入口は、いつも走る節（輪の外の `start`・`open`・境の節 `h-*`）の欄か盤面からだけ渡す。飛ばされうる節の欄を `with:` で読まない（仕様 2.1 の C1）。各 script は読む `INPUTS_*` を定数 `INPUTS` に持つ（線 A の TA16 と同じ。T11 が YAML の `with:` と突き合わせる）。役の出力と作業ファイルは周の番号を決め打ちにせず、`state.outputs[節]["file"]`・`b.work(名)` から引く。
- `$LOOP_PREV` は `with: {prev: "$LOOP_PREV.gate.output"}` の文字列の束ねでだけ読む（`from:` は Archon が読み込みで拒む。仕様 4.2）。
- **`accept.py` に検査を足さない**（回す側の指示 2026-09-27。受け付けの口は本線の 3-8 まで `accept.py` のまま）。線 B の受け付けは線 B のモジュール（`judge2`・`close`）とブロックのスクリプトに置き、線 A の対応表 `works/.shared/core/gl_map.json`（〔A計〕Task 24）に線 B の行を T13 で足す。
- ブロックの名前と節の表の `where` は works の仮の名（`blk-close`・`blk-purpose`）。本線の 3-7 の後に T18 で揃える。
- 止める猶予は works の 2 秒（`tree_run.KILL_GRACE`）のまま（本線は呼ぶ側が選べる形・既定 5 秒にする）。
- 役の節の `output_format` は線 A の `node_marker.mark(…, 名)` の印つき（〔A計〕TA20）。試験は `node_marker.strip` で外して比べる。
- 決め方: review-graph（0.21.0）と能力で同等以上なら推しで決めて Task の報告に書く。能力が下がる・費用がかかる・外へ書く物は止めて持ち主に聞く（下請けは coordinator に返す）。
- commit の末尾に `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`。push・tag・merge はしない。

## 並べ方

```
波 1:  T1 節の表と宣言 ─┬─ T2 検証器の包み ─┬─ T8 Archon の試し（AI 費用 0 の分）     （3 つ並べてよい）
波 2:  T3 宣言の差し込みと収束の道（T1・T2 の後）
波 3:  T9 blk-judge v2（T3 の後）─┬─ T4 start と境の節（T3 の後。Step 0 で TA18 を確かめる）─┬─ T6 最後の関門（T3 の後）
                                                                                       （3 つ並べてよい）
波 4:  T5 答え・一時停止・close_early（T4 の後）
波 5:  T7 blk-close（T5・T6 の後）
------ 線 A の枝の先（T17 の後）へ載せ直し、check.sh を 1 度通す ------
波 6:  T10 報告（T7 の後）
波 7:  T11 ライン（T9・T10 の後）
波 7b: T15 周の頭の並行 PR と前提（線 A の T21・T22 の後）→ T16 目的の文（T15 の後）
波 8:  T12 筋書き（T16 の後）
波 9:  T13 共有のファイルと仕様の置き直し（全部の後。線 B の最後の commit）
波 10: T14 実走（持ち主の費用の了承の後）
------ 本線の 3-5・3-6 が版に入り、写し直した後（「写し直しへの依存」）。線 A の T23 の後 ------
波 11: T17 同じ周の再審（線 A の blk-rejudge を輪の中に。最後の 1 commit で共有に触る）
------ 本線の 3-7 が版に入った後（線 A の T25 と同じ時に）------
波 12: T18 ブロックの名前と where を本線に揃える（小さな作業）
```

- `rounds.py` を触るのは T1 → T3 → T4 → T5 → T10 → T15 → T16 → T17 の順に直列。`close.py` は T3 → T6 → T7 の順に直列。`judge2.py` と `blk-judge/**` は T9・T11（`judge-reads` を足すだけ）・T16（入口 `purpose_file`）。`darkfactory-rounds/nodes.json` は T1・T15・T16・T17・T18。T15・T16 は T12（筋書き）の前に入れ、筋書きが周の頭の道も見られるようにする（T12 の番号は変えない）。並べた物は各々の worktree で回し、審査の後に cherry-pick する（台帳 R6・R8）。
- T9 は線 A のライン（1 本目の名前で blk-judge を include し、判定を境の節で盤面へ渡し替える〔A計〕TA3）を壊さない形にする（仕様 5 節の逆向きの依存）。T9 の Step 4 で線 A の 1 周のラインの試験を v2 で回し直す（審査 I7 の 3）。
- 試しの結果で形が変わる所: P6a・P6e → T9、P17 → T11。T8 を波 1 で先に撃つ。数セントの分（P6b・P6c・P6e）は了承待ちの間、T9 を案 (d) の形で作り、崩れた時の案 (c) への倒し方だけ Task に書いておく。

## Review Focus

1. 写しを 1 バイトも変えない。差し替えは `validator_module`・`fill_materials` の 2 つだけで、`state.works.overrides` に理由つきで残る（T3 `test_overrides_recorded`・`test_copy_untouched`）。
2. 宣言した省略が観測した値を隠さない。検証器の包みの縛り ①〜③（T2）。宣言した素材は `not_run` でなく `not_in_line`、判定から入る周 1 の P1 の素材は engine の `not_applicable` のまま（T3）。
3. 線 B の表で収束の道が engine と同じに通る: `merge` → `gates_deferred`、`in_run` → mutgate の記録で `converged`、締めた周の次から連続 2 周を数え直す（T3・T5・T6）。
4. 周の番号を上げるのは engine だけ。関所の答えは 1 度だけ当たり、答えを失った resume は同じ関所を聞き直す（T4 `test_boundary_never_writes_round`・T5 `test_answer_once`・`test_lost_answer_reasks`）。
5. 境の節は ready だけからブロックを選び、問い・一時停止・止め札が在れば後ろを全部飛ばす（T4）。
6. `rejudge` は同じ周の判定を回し直さない（T5 `close_early`・T9 の resume の形）。
7. 判定の 1 回目か 2 回目かは盤面の instance で決まり、拒否の回に盤面が 1 バイトも変わらない（T9）。
8. 最後の関門: mutgate の記録の版・木・範囲・種類・人の答えを確かめ、判定は写しの `_final_gate_problems` に任せる（T6）。突き合わせの道具は盤面を変えない。
9. `p0.parallel_pr` は T15 まで表の absent の 1 行、T15 の後は線 A と同じ行（`engine_run`・`fallback: role`）で、申し送りは投稿しない（T15 `test_parallel_pr_row_matches_track_a`・`test_downgrade_in_report_head`）。
10. ライン: 関所は唯一の末端・until_bash は盤面のファイルだけ・ブロックの `when:` は境の節の `run` だけ・AI の節に `model:` が無い（T11・T13）。
11. ブロックの入口がいつも走る節からだけ渡り、方針の文書が役に届く（T4・T11 `test_block_inputs_from_always_run_nodes`・`test_policy_reaches_roles`）。関所の後の回に判定のブロックが飛んでも輪が落ちない（T12 `resume-in-round`）。
12. `rejudge` は `continue` の副作用（上限を上げる・腕 0 本の同意）を持たない（T5）。報告は検証器を通らなければ収束を名乗らない（T10）。判定 v2 は盤面のラインの表で開く（T9）。
13. 同じ周の再審は周ごとに今の周の判定役の会話を継ぎ、会話が無い周は役を起こす前に一時停止で聞く（T17 `test_rejudge_continues_this_rounds_judge`・`test_no_session_pauses`）。

---

### Task 1: 節の表と、表から導く宣言（並べてよい: T2・T8）

**Files:**
- Create: `works/darkfactory-rounds/nodes.json`
- Create: `works/.shared/core/rounds.py`（この Task では表と宣言の部分だけ）
- Test: `works/tests/test_rounds_table.py`

**Interfaces:**
- `works/darkfactory-rounds/nodes.json`: 〔土〕4.2 の形。`{"line": "darkfactory-rounds", "graph_sha": "f9897bb07384", "nodes": {...}}`。持ち方は仕様 3.1 のとおり（`p0.base`・`p4.final_gates` は machine、`p0.local_checks`・`p4.ci` は engine_run `fallback: machine`、役の 9 節は role、driver は builtin で `p4.record` だけ `run: explicit`、他は absent）。absent の行は `reason` と `comes_with` を持つ。〔答〕で入る節（`p0.parallel_pr`・`p0.premises`・`p0.purpose`・`p2.rejudge`・`p2.rejudge_third`）の `comes_with` は入る Task（T15・T16・T17。T17 は「本線 3-6 の写し直しの後」）。各行の `where` はブロックの名前か `start`（works の仮の名。T18 で本線に揃える）。
- `rounds.py`:
  - `TABLE_PATH: pathlib.Path`（上の表）
  - `BLOCKS = ("judging", "planning", "fixing", "reviewing", "refixing", "testing", "closing")`
  - `WHERE_TO_BLOCK = {"blk-judge": "judging", "blk-plan": "planning", "blk-fix": "fixing", "blk-delta": "reviewing", "blk-refix": "refixing", "blk-tests": "testing", "blk-close": "closing"}`
  - `load_table() -> board.NodeTable`
  - `nodes_of_block(table: NodeTable, block: str) -> frozenset[str]`
  - `declarations(table: NodeTable, graph: dict) -> dict` — `{"nodes": [absent の節], "materials": [書く節が全部 absent の素材], "reviews": [書く節が absent の目]}`（名前の順に並べる。素材の書き手は graph の節の `materials` と `writes` の `to: materials.*`、目の書き手は `writes` の `to: reviews.*`）

- [ ] **Step 1: 失敗するテストを書く**

```python
def test_table_passes_board_checks(self):   # NodeTable.load(TABLE_PATH).check(graph_expanded(), "f9897bb07384") == []
def test_where_names_blocks(self):          # role・machine・engine_run の行の where が WHERE_TO_BLOCK の鍵か "start"
def test_explicit_only_record(self):        # builtin の run が explicit の行は p4.record だけ
def test_absent_rows_reasoned(self):        # absent の全部の行で reason と comes_with が空白でない
def test_declarations_derived(self):        # materials が 12 個（local_checks・base_determination・fix_closure が無い）、
                                            #   reviews == ["R1","R2","R3","R4"]、nodes == [x["node"] for x in table.absent()] を並べた物
def test_role_row_changes_declarations(self):  # 表の p1.hygiene を role（where blk-plan）にした一時の表で、hygiene が materials から消える
def test_later_rows_name_their_task(self):  # p0.parallel_pr・p0.premises・p0.purpose・p2.rejudge・p2.rejudge_third が absent、comes_with に "T15"・"T16"・"T17"
                                            #   （T15〜T17 がこの試験を行の形の試験に替える）
def test_roles_match_track_a(self):         # works/darkfactory/nodes.json が在れば、両方で role の節の by と where が同じ
                                            #   （違ってよいのは p2.history・p4.record・p4.final_gates・p0.purpose と、入る Task の前の〔答〕の節）。無ければ理由を出して skip
```

- [ ] **Step 2: 赤を確かめる** — Run: `nice -n 19 sh works/tests/run.sh -k rounds_table` / Expected: FAIL（`rounds` が無い）
- [ ] **Step 3: 書く** — 表は `NodeTable.everything(graph, sha)` の出力を下敷きにして、仕様 3.1 のとおり行を替える。absent の理由は仕様 11.2 の区分（P0 の目・P1 の目・R1〜R4・周の中の変異の線・AI が書く報告・仕様から入る道・〔答〕で後の Task に入る節）ごとに 1 つの文を使い、`comes_with` に入る予定（「R 系のブロック（未定）」「線 C（mutgate）でまとめて撃つ」「線 B T15」「線 B T17（本線 3-6 の写し直しの後）」など）。
- [ ] **Step 4: 緑を確かめる** — Run: `nice -n 19 sh works/tests/run.sh` / Expected: `OK`
- [ ] **Step 5: Commit** — `git commit -m "feat(works): 周の輪の節の表と、表から導く宣言（このラインが集めない物）"`

---

### Task 2: 検証器の包み `rounds_validator.py`（並べてよい: T1・T8）

**Files:**
- Create: `works/.shared/core/rounds_validator.py`（PEP 723。直に起こす）
- Test: `works/tests/test_rounds_validator.py`

**Interfaces:**
- `load(declared: dict) -> types.ModuleType` — 写しの RR を毎回新しい module として読み込み、記憶の中の `STATUS` と `REVIEW_STATUS` に `not_in_line`（`reason` 必須・`blocks=False`・`carryable=False`・`machine_written=True`・目は `only_for=REVIEWS`）を足した物を返す。ファイルは変えない。
- `declared_errors(rounds: list[dict], notes: list[dict], declared: dict, V) -> list[str]` — 仕様 4.6 の縛り ①〜③。①② は各周の `materials`・`reviews` に当て、③ は `rounds/works/round-<N>.json`（土台の周の添え書き）の `not_in_line` の節の集合が周どうしで同じかと、`declared["nodes"]` と同じかを見る。
- `main(argv: list[str]) -> int` — `rounds_validator.py <rounds_dir> --declared <json のファイル>`。`declared_errors` が在れば出力に並べて 2。無ければ包んだ module で RR の `main` と同じ判定をして、その終了コード（0・1・2）と出力を返す。
- `runner(declared: dict) -> Callable[[DiskBoard, pathlib.Path | None], dict]` — 土台の `validator_runner` に渡す関数を返す。`[sys.executable, <このファイル>, <target か b.dir/"rounds">, "--declared", <盤面の r<N>/declared.json>]` を `PYTHONDONTWRITEBYTECODE=1` で走らせ、`{"exit": int | None, "out": str}`（engine の `run_validator` と同じ鍵）。

- [ ] **Step 1: 失敗するテストを書く**

```python
# 基の周の記録は、土台の手本 works/tests/boards/golden-a1202d0/ の test_converges の run 1 の最後の盤面の rounds/ を
# boardreplay.restore で一時の置き場に戻して使う（手本は変えない。書き換えは一時の置き場で）
def test_rr_file_untouched(self):           # load の前後で写しの review-record.py の sha256 が同じ、load を 2 度で別の module
def test_not_in_line_in_tables(self):       # STATUS["not_in_line"]・REVIEW_STATUS["not_in_line"] の欄（blocks False・carryable False・machine_written True）
def test_declared_round_passes(self):       # 宣言した素材 12 と R1〜R4 を not_in_line にした周の記録 → exit が 0 か 1、出力の阻害要因に not_in_line の名が無い
def test_undeclared_not_in_line_fails(self):# 宣言に無い local_checks を not_in_line → exit 2、出力に local_checks
def test_observed_on_declared_material_fails(self):  # 宣言した hygiene に clean → exit 2
def test_real_verdict_on_declared_review_fails(self):# 宣言した R2 に機械が書かない本物の判定 → exit 2
def test_not_run_on_declared_is_allowed(self):       # 宣言した R1 が not_run（止めた周）→ 縛りでは落ちない（exit は 0 か 1）
def test_declarations_changed_midrun_fails(self):    # rounds/works/round-1.json と round-2.json の not_in_line の節の集合が違う → exit 2
def test_runner_shape(self):                # runner(declared)(盤面, None) の返りの鍵 == {"exit", "out"}、r<N>/declared.json が書かれる
```

- [ ] **Step 2: 赤を確かめる** — Run: `nice -n 19 sh works/tests/run.sh -k rounds_validator` / Expected: FAIL
- [ ] **Step 3: 書く** — RR の読み込みは `importlib.util.spec_from_file_location` で毎回新しい名前にする。RR の `main` が表を大域の名前で引くことを先に確かめ、足した表が判定に効くかを `test_declared_round_passes` で見る（効かない作りなら、RR の関数を包みの側から同じ表で呼ぶ形に替え、その理由を Task の報告に書く）。
- [ ] **Step 4: 緑を確かめる** — Run: `nice -n 19 sh works/tests/run.sh` / Expected: `OK`
- [ ] **Step 5: Commit** — `git commit -m "feat(works): 写しの検証器を記憶の中で包み、このラインが集めない印 not_in_line を足す"`

---

### Task 3: 宣言の差し込みと収束の道（T1・T2 の後）

**Files:**
- Modify: `works/.shared/core/rounds.py`（`board_kwargs`・`open_board`）
- Create: `works/.shared/core/close.py`（`declare_reviews`・`fill_materials_declared`・`validator_module_declared`・`abandon_unrun_lanes`）
- Create: `works/darkfactory-rounds/board_hook.py`（`board_kwargs(table) -> dict` を `rounds.board_kwargs` に渡すだけ。線 A の `entry.open_board` が読む口。仕様 5 節の約束 1）
- Create: `works/tests/roundskit.py`（試験の道具: 使い捨ての対象・盤面・返答の見本の読み込み）
- Create: `works/tests/replies/rounds/`（`r1_judge_block.json`・`r1_fix.json`・`r1_delta_review.json`・`r2_judge_clean.json`・`r2_history_clean.json`・`r2_fix_none.json`・`r3_judge_clean.json`・`r3_history_clean.json`・`r1_plan.json`・`r1_plan_review.json`・`r1_refix_none.json`・`r_judge_escalate.json`・`r_judge_fork_held.json`・`r_judge_fork_decided.json`・`r_judge_held_split.json`・`r_judge_stuck.json`。周 3 までの役の返答と、問いの状態ごとの判定。直す単位 0 の周の `p3.fix` は線 A の `empty_fix_reply` を使うので見本を持たない。形は土台の手本の同じ節の返答から写して手で直す）
- Test: `works/tests/test_rounds_declare.py`

**Interfaces:**
- `rounds.board_kwargs(table: NodeTable) -> dict` — `{"table", "overrides": {"validator_module": (close.validator_module_declared, 理由), "fill_materials": (close.fill_materials_declared, 理由)}, "validator_runner": rounds_validator.runner(declarations(table, graph))}`。`DiskBoard.begin`・`open` にそのまま渡す。
- `rounds.open_board(board_dir: Path, *, repo: Path | None = None, allow_halted: bool = False) -> DiskBoard`
- `close.fill_materials_declared(b) -> None` — 宣言した素材のうち、まだ記録に無く、書く節がこの周に `na` でない物を `{status: "not_in_line", reason: <表の理由>}` で置いてから、写しの `fill_materials` を呼ぶ（写しの関数は `rounds_module` を開いたときの元の関数を掴んでおく）。
- `close.validator_module_declared(b) -> types.ModuleType` — `rounds_validator.load(declarations(...))`（盤面ごとに 1 度だけ読む）。
- `close.declare_reviews(b) -> list[str]` — 宣言した目のうち、この周の記録に無い物を `not_in_line` で置き、置いた名を返す。
- `close.abandon_unrun_lanes(b, reason: str) -> list[str]` — `inputs.gates` が `merge` でない run で、`loop.lanes` の `running` の線を `abandoned`（`why` に理由）にし、その版の一覧を返す。
- `roundskit`:
  - `make_target(tmp: Path, *, declared_ci: bool = True, red: bool = False) -> Path` — `works/dev/target-seed` を写した使い捨ての git リポジトリ（`.review-checks.json` で CI を engine が走らせる。`red` で赤）
  - `begin(tmp, repo, *, gates: str = "merge", max_rounds: int = 5) -> DiskBoard` — `rounds.board_kwargs` で `DiskBoard.begin`
  - `reply(name: str, **subst) -> dict`、`drive(b, repo, script: list[tuple]) -> Progress` — 手の列（`("done", 節, 返答の名)`・`("engine", 節)`・`("builtin", 節)`・`("declare",)`）を順に当てる

- [ ] **Step 1: 失敗するテストを書く**

```python
def test_overrides_recorded(self):          # begin の後の state.works.overrides に validator_module・fill_materials と理由
def test_entry_round_keeps_not_applicable(self):   # 周 1 の p1.worktree_after の後、P1 の素材は engine の not_applicable（理由は判定から入る run）
def test_declared_materials_not_in_line_after_entry(self):  # 入口が終わった後の周の p1.worktree_after の後、宣言した素材が not_in_line・理由が表の理由
def test_declare_reviews_before_record(self): # declare_reviews → run_builtin("p4.record") → rounds/round-1.json の R1〜R4 が not_in_line、検証器の exit が 0 か 1
def test_converges_to_gates_deferred(self):  # 周 1 に block → 修正 → 周 2・周 3 が阻害なし、gates=merge → status "stopped"・loop.stop_reason "gates_deferred"・round 3
def test_in_run_waits_final_gates(self):     # gates なし → 周 3 の p4.record の後の ready == ["p4.final_gates"]、status "running"
def test_lanes_abandoned_in_run(self):       # gates なしの周で p3.gates_cut が載せた線が abandon_unrun_lanes の後 abandoned・why が在る。merge では loop.lanes が空
def test_stop_round_record_passes(self):     # 周 2 の途中で b.stop("試験", "request") → 止めた周の記録が包みの検証器を通り（目は not_run）、報告の節が出せる
def test_round_notes_list_absent(self):      # 各周の rounds/works/round-<N>.json の not_in_line が表の absent の全部
def test_copy_untouched(self):               # 試験の後に写しの review-loop.py・review-record.py の sha256 が a1202d0 と同じ（土台の test_core_verbatim と同じ式で引く）
def test_board_hook_matches(self):           # board_hook.board_kwargs(表) の overrides の名と validator_runner が rounds.board_kwargs と同じ
def test_open_without_overrides_is_loud(self):  # 差し替え無しで開いた盤面で p4.record → 検証器の exit 2（not_in_line を知らない）で settle が止まり notes に理由（黙らない）
```

- [ ] **Step 2: 赤を確かめる** — Run: `nice -n 19 sh works/tests/run.sh -k rounds_declare` / Expected: FAIL
- [ ] **Step 3: 書く** — 返答の見本が写しの受け付けに拒まれたら、見本を直す（規則は直さない）。拒否の文は Task の報告に残す。周 2 以降の P1 の節が ready になる時機（判定から入る run の入口が終わる周）は写しの規則どおりで、試験はその周を盤面の `record.process.request_entry` から引いて当てる。
- [ ] **Step 4: 緑を確かめる** — Run: `nice -n 19 sh works/tests/run.sh` / Expected: `OK`
- [ ] **Step 5: Commit** — `git commit -m "feat(works): 宣言を盤面に差し込み、周の輪の表で収束の道が engine と同じに通る"`

---

### Task 4: `start` と境の節（T3 の後。並べてよい: T6・T9）

**Files:**
- Modify: `works/.shared/core/rounds.py`（`start`・`load_state`・`save_state`・`boundary`・`write_finished`）
- Create: `works/darkfactory-rounds/scripts/start.py`・`works/darkfactory-rounds/scripts/boundary.py`（PEP 723。`INPUTS_*`・`ARTIFACTS_DIR` を読み、1 行の JSON を出す数行）
- Test: `works/tests/test_rounds_boundary.py`

**Interfaces:**
- `start(board_dir: Path, *, repo: Path, request_path: str, test_cmd: str, base_rev: str, max_rounds: int = 5, gates: str = "merge", run_id: str, run_ci=None, ticket=None, policy_brief=None) -> dict` — 仕様 4.1。返り `{"ok": bool, "round": int, "ready": list, "base_rev": str, "test_cmd": str, "policy_paste": str, "policy_path": str, "reason"?: str}`。`gates` は `merge`・`in_run` だけ（他は `ok: False`）。線 A の部品は引数で受け、既定は線 A のモジュールを遅れて import する: `run_ci(b, nid, *, test_cmd) -> dict`（〔A計〕`entry.run_ci`。任せ先に落ちたら `entry.local_checks_material` の素材を渡す）・`ticket(board_dir, repo, run_id)`（`ticket.write`）・`policy_brief(b) -> {"paste", "path"}`（`policy.brief`）。`works-rounds.json` に `test_cmd` を控える（仕様 4.1。審査 m10）。
- `load_state(board_dir) -> dict`・`save_state(board_dir, st) -> None` — `works-rounds.json`（仕様 3.2 の形。`version: 1`）。知らない版は `BoardGap`。
- `boundary(board_dir: Path, at: str, *, repo: Path, run_id: str = "", adapter_mode: str = "", halt_seen=None, adapter_seen=None, take=None, empty_fix_reply=None) -> dict` — 仕様 2.2 の 1〜6。返り `{"ok": True, "stop": bool, "run": bool, "ask": bool, "round": int, "why": str, "judgment_file": str, "open_units": str, "plan_file": str, "human_notes": str}`（後ろの 4 つはブロックの入口。盤面の `state.outputs[節]["file"]` と今の周の記録から組む。無ければ空の文字列。仕様 2.1 の C1）。`at` は `rounds.BLOCKS` のどれか。線 A の部品は引数で受け、既定は線 A のモジュールを遅れて import する: `halt_seen(board_dir) -> dict | None`（〔A計〕`halt.seen`）・`adapter_seen(board_dir, run_id) -> {"seen": bool, …}`（`reads.adapter_seen`）・`take(board_dir, nid, reply, repo) -> dict`（`entry.take`）・`empty_fix_reply() -> dict`（`entry.empty_fix_reply`）。止め札は `b.stop(理由, by)`、包みが無い run は `b.stop("包みが通っていない: …", by="works:adapter")`（`h-plan` だけ）。
- `write_finished(board_dir: Path, why: str) -> None`
- スクリプトの出口: `start.py` → `start` の返り（`ok` が偽なら終了コード 1）、`boundary.py` → `boundary` の返り（入力 `at`）。各 script は読む環境変数を定数 `INPUTS`（例: `start.py` は `("INPUTS_REQUEST", "INPUTS_TEST_CMD", "INPUTS_BASE_REV", "INPUTS_MAX_ROUNDS", "INPUTS_GATES", "INPUTS_ADAPTER")`）に持つ。

- [ ] **Step 0: 線 A の TA18 が在ることを確かめる**（審査 I7 の 2）— Run: `nice -n 19 sh works/tests/run.sh -k "test_entry or test_report or test_policy"` と、`python3 -c` で `entry.open_board`・`entry.hook_kwargs`・`entry.local_checks_material`・`entry.run_ci`・`report.head_decisions`・`report.head_entry`・`report.head_stop`・`report.head_reads`・`report.head_where`・`report.gate_record` を import できるかを見る / Expected: 全部在り、線 A の試験が緑（`test_open_board_applies_board_hook`・`test_local_checks_material_callable_alone`・`test_head_parts_callable`・`test_judge_block_policy_entry_only` を含む）。1 つでも無ければ止めて coordinator に報告する。
- [ ] **Step 1: 失敗するテストを書く**

```python
def test_start_begins_once(self):            # 2 度呼んでも盤面 1 つ・依頼 1 バッチ、works-rounds.json の version 1
def test_start_rejects_bad_request(self):    # accept.check_request が拒む依頼 → ok False・reason、盤面の置き場が無い
def test_start_gates_mapping(self):          # merge → state.inputs.gates == "merge"、in_run → 鍵が無い、"x" → ok False
def test_start_local_checks_by_engine(self): # 宣言の在る対象 → process.checks["p0.local_checks"].by == "engine"、ready == ["p2.diagnose"]
def test_start_local_checks_fallback(self):  # 宣言の無い対象 → 注入した local_checks が 1 度呼ばれ、ready == ["p2.diagnose"]
def test_start_writes_ticket(self):          # 注入した ticket が (board_dir, repo, run_id) で呼ばれる
def test_start_policy_outputs(self):         # 方針の文書が在る対象 → policy_paste・policy_path が空でない（policy_brief の返り）。無い対象では両方 ""
def test_start_keeps_test_cmd(self):         # works-rounds.json の test_cmd と返りの test_cmd が入力と同じ
def test_boundary_block_inputs(self):        # h-plan の返りの judgment_file == state.outputs["p2.diagnose"]["file"]、h-fix の返りの plan_file・open_units・human_notes が盤面と合う。
                                             #   周 2 の盤面でも r1 の置き場を指さない
def test_boundary_by_ready(self):            # roundskit.drive で段を進め、各段で「ready の節の where がその段」のときだけ run True（7 段の全部）
def test_boundary_asking_blocks_all(self):   # pending_human の在る盤面 → 7 段の全部で run False・ask True
def test_boundary_pause_blocks_all(self):    # works-rounds.json の gate が applied False → 同じ
def test_boundary_stop_flag(self):           # 注入した halt_seen が {reason, by} → state.stop の理由と by、stop True、finished が在り中身が理由
def test_boundary_adapter_missing_stops(self): # h-plan で注入した adapter_seen が seen False・adapter_mode "" → stop True、state.stop.by == "works:adapter"。optional なら止めない
                                             #   （T15 が確かめを h-judge へ動かし、この試験の段を judging に替える。線 A の TA9 と同じ）
def test_boundary_no_units_empty_fix(self):  # p2.fix_plan が na の周の h-fix → 注入した take が ("p3.fix", empty_fix_reply()) で 1 度呼ばれ、fixing は run False
def test_boundary_finished_board(self):      # status converged・stopped、halted の盤面 → stop True、finished
def test_boundary_never_writes_round(self):  # 同じ盤面に boundary を 20 回 → state.round・rev が変わらない
def test_scripts_have_pep723(self):          # darkfactory-rounds/scripts/*.py の頭に # /// script
```

- [ ] **Step 2: 赤を確かめる** — Run: `nice -n 19 sh works/tests/run.sh -k rounds_boundary` / Expected: FAIL
- [ ] **Step 3: 書く** — `boundary` は盤面を読むのが基本で、書くのは止め札（`b.stop`）・包みの無い run（`b.stop`）・直す単位 0 の周（`take`）の 3 つだけ。試験では線 A の部品を偽物で差す（線 A はまだ合流していない）。盤面の終わりの見分けは `state.status in ("converged", "stopped")` か `state.halted`。
- [ ] **Step 4: 緑を確かめる** — Run: `nice -n 19 sh works/tests/run.sh` / Expected: `OK`
- [ ] **Step 5: Commit** — `git commit -m "feat(works): 周の輪の start（盤面を begin で開く）と、盤面の ready でブロックを選ぶ境の節"`

---

### Task 5: 答え・一時停止・close_early（T4 の後）

**Files:**
- Modify: `works/.shared/core/rounds.py`（`detect_judge_asks`・`open_gate`・`apply_answer`・`close_early`・`record_human`・`open_step`）
- Create: `works/darkfactory-rounds/scripts/open.py`（PEP 723。`with: {prev: "$LOOP_PREV.gate.output"}` の文字列を受ける。空の文字列は「開かなかった」か「答えを失った」で、見分けは `works-rounds.json` の `applied`。`INPUTS = ("INPUTS_PREV", "INPUTS_ADAPTER")`）
- Test: `works/tests/test_rounds_answers.py`

**Interfaces:**
- `detect_judge_asks(b, st: dict) -> dict | None` — 仕様 2.3・4.4。条件は「`status` が `held`・`escalate`（RR の `ASKING`）で、かつ `status == "escalate"` か `kind == "fork"`」で、`answered` に `key|status` が無い物。返り `{"kind": "judge_asks", "items": [問いの行]}`。
- `detect_questions_open(b, st: dict) -> dict | None` — 仕様 2.3 の `questions_open`（審査 I3）。`held`・`escalate` の問いで `answered` に `key|status` が無い物。返り `{"kind": "questions_open", "items": [...]}`。T7 の `round_end_pauses` が呼ぶ。
- `open_gate(board_dir, kind: str, source: str, items: list) -> dict` — `works-rounds.json` の `gate` に `{seq, kind, source: "board"|"pause", round, items, applied: False}`。`seq` は `<周>-<kind>-<数>`。
- `apply_answer(board_dir, decision: str, text: str) -> dict` — 仕様 2.3 の表（6 行）。`max_rounds`・`final_gate_empty` の問いへの `rejudge` は `reask`（`b.answer` を呼ばない。上限も `final_gate_empty_ok` も変えない。審査 I4）。engine の問いと一時停止が同じ関所に在れば、engine の問いへ先に `b.answer` し、同じ答えで一時停止も閉じる（審査 m9）。答えた問いは `answered` に `key|status` で足す。返り `{"ok": True, "applied": bool, "stop": bool, "action": "continue"|"next_round"|"close_early"|"stop"|"reask"|"final_gate"}`。`approve` は `continue`、`reject` は `stop`。開いた関所が無い・`applied` が真なら `applied: False` で何もしない。`final_gate` の答えは `mutgate=<パス>` を `works-rounds.json` の `final_gate.record` に置くだけ（受けるのは T7 の `close-record`）。
- `record_human(b, kinds: list, items: list, answer: str, note: str, *, to_answers: bool) -> None` — RL の `human_gate_answered` と同じ形の行を `record.process.human_items` に、`to_answers` なら `process.human_answers` にも積む。
- `close_early(b, reason: str, note: str) -> Progress` — 仕様 4.4 の 1〜5（`pending_human` は `answer: "rejudge"` の行で `human_items` に残す。審査 m4）。写しの `_stopped_round_record` が理由を返したら盤面を戻して `BoardGap` でなく `{"refused": 理由}` を持つ `Progress` の `notes` に入れ、周を開かない。
- `open_step(board_dir, prev: str, *, repo: Path, halt_seen=None, ticket=None) -> dict` — `open` の節の中身（止め札 → 盤面の終わり → 答え → 切符 → `boundary(…, "judging")`）。`prev` は `$LOOP_PREV.gate.output` の文字列（JSON なら `decision`・`text` を読む）。答えを失った resume（開いた関所・`applied` が偽・`prev` が空）は `{"run": False, "ask": True}`。

- [ ] **Step 1: 失敗するテストを書く**

```python
def test_answer_table(self):                # 仕様 2.3 の表の 6 行 × continue・rejudge・stop・reject と approve（見本の盤面を作って当て、action と盤面の変化を行ごとに見る）
def test_rejudge_no_continue_side_effects(self):  # max_rounds の問いへの rejudge → reask、state.max_rounds が変わらない。final_gate_empty への rejudge → reask、loop.final_gate_empty_ok が無い
def test_overlapping_ask_and_pause(self):   # 上限の問いと tests_red が同じ関所 → continue で b.answer が先、一時停止も閉じる。stop で両方止まる
def test_prev_string_forms(self):           # prev が ""・JSON の文字列・一言に引用符と改行と $(x) を含む JSON → open_step が正しく読み、壊れない
def test_answer_once(self):                 # 同じ seq の答えを 2 度 → human_items の行は 1 つ、2 度目は applied False
def test_lost_answer_reasks(self):          # 開いた関所（applied False）・prev None → open_step が run False・ask True、盤面が変わらない
def test_judge_asks_escalate_fork(self):    # escalate の問い・held の fork で開く、decided の fork では開かない（審査 I2）、答えた key|status では開き直さず、状態が変われば開く
def test_questions_open_held(self):         # held の split の問いが答えの無いまま周の終わりに残る → detect_questions_open が返す。答えた後の周では返さない
def test_continue_note_reaches_records(self):  # judge_asks の continue の一言が human_items と human_answers に在り、node と kinds が在る
def test_close_early_next_round(self):      # 判定の後の rejudge → rounds/round-N.json の素材が not_run か not_in_line・目が not_in_line、round == N+1、
                                            #   human_answers に kinds rejudge、works-rounds.json の rejudge に N、rounds/works/round-N.json が在る
def test_close_early_breaks_streak(self):   # 締めた周の次の周が阻害なしでも収束しない（その次の周で初めて gates_deferred）
def test_close_early_refused_keeps_round(self):  # 検証器が拒むよう壊した盤面 → round が変わらず、notes に理由、関所をもう一度開く
def test_close_early_from_human_gate(self): # p2.human_gate の問いへの rejudge → pending_human が消え、human_items に answer "rejudge" の行、その項目は「通した」に数えられない、次の周
def test_round_end_rejudge_marks(self):     # converge の問いへの rejudge → b.answer("continue") と同じ周の移り、human_answers の一言の頭が「判定のやり直しを求める」
def test_tests_red_answer_on_new_round(self):  # tests_red の continue の一言が新しい周の human_answers に在る
def test_stop_and_reject(self):             # engine の問い → answer stop、線 B の一時停止 → b.stop(by="human")、どちらも finished と stopped の盤面
def test_max_rounds_continue_extends_once(self):  # 上限の問いへの continue で state.max_rounds が 1 だけ上がる
def test_final_gate_answer_needs_path(self):      # final_gate への continue で mutgate= が無い → action reask、在れば works-rounds.json の final_gate.record
```

- [ ] **Step 2: 赤を確かめる** — Run: `nice -n 19 sh works/tests/run.sh -k rounds_answers` / Expected: FAIL
- [ ] **Step 3: 書く** — `close_early` は写しの `_stopped_round_record`・engine の `open_next_round`・`STOPPED_BY` を import して呼ぶ（書き写さない）。印の付け方を土台の手本 `test_stop_midround` の `stop` の手の後の盤面（`rd.stopped`・instance の `stopped`）と比べる試験を 1 本足す。盤面の保存 → `applied` を真、の順に書く（仕様 3.3 の 2）。
- [ ] **Step 4: 緑を確かめる** — Run: `nice -n 19 sh works/tests/run.sh` / Expected: `OK`
- [ ] **Step 5: Commit** — `git commit -m "feat(works): 周の輪の関所の答え・判定の直後の問い・周を締めて次の周へ（close_early）"`

---

### Task 6: 最後の関門（mutgate の記録を読む。T3 の後。並べてよい: T4・T9）

**Files:**
- Modify: `works/.shared/core/close.py`（`check_mutgate`・`final_gate_reply`・`mutgate_command`・`post_hoc`）
- Create: `works/darkfactory-rounds/scripts/final_gate.py`（PEP 723）
- Create: `works/tests/fixtures/mutgate-records/good.json`（〔C〕7 節の形。版・木・範囲は `@REV@`・`@TREE@`・`@BASE@` の穴で、試験が埋める）
- Test: `works/tests/test_rounds_final_gate.py`

**Interfaces:**
- `check_mutgate(b, record: dict) -> list[str]` — 仕様 4.7 の 3 の確かめ（`kind`・`outcome`・`rev`・`tree`・今の作業ツリーの木・`from`・`gate.human`）。空なら受けてよい。
- `final_gate_reply(b, path: str) -> dict` — 記録を読み、`check_mutgate` が空なら記録の `lane` を返す。空でなければ `Reject`（理由を全部つないだ文）。
- `mutgate_command(b, test_cmd: str) -> str` — `test_cmd` は `works-rounds.json` に `start` が控えた物（審査 m10）。 `archon workflow run raiki61/works:mutgate --from <gates_cut.rev> --input base_rev=<base> --input head_rev=<gates_cut.rev> --input test_cmd=<test_cmd>`。
- `post_hoc(board_dir: Path, record_path: str) -> dict` — 盤面を `allow_halted=True` で開き、記憶の中の写しの盤面に `check_mutgate` と写しの `_final_gate_problems` と同じ判定を当てる。ただし「今の作業ツリーの木」は見ず、`gates_cut.rev` の木と記録の `tree` だけを比べる（run の worktree が片付いた後でも判じられる。仕様 4.7。審査 m5）。返り `{"verdict": "passes"|"next_round"|"empty"|"refused", "problems": [...], "tree": str}`。盤面の `state.json`・`record.json` は書かず、`final-gate-<tree12>.json` だけ書く。
- `final_gate.py --board <dir> --mutgate <record.json>` — `post_hoc` の返りを標準出力に 1 行。読めない入力は終了コード 2。

- [ ] **Step 1: 失敗するテストを書く**

```python
def test_good_record_converges(self):       # in_run の盤面を p4.final_gates まで進め、good.json（穴を埋めた物）→ b.done("p4.final_gates", final_gate_reply(...)) → status "converged"
def test_wrong_rev_refused(self):           # rev が gates_cut.rev と違う → Reject、文に両方の版
def test_wrong_tree_refused(self):
def test_wrong_from_refused(self):          # from が record.base の版と違う
def test_not_run_refused(self):             # outcome "not_run"
def test_human_reject_refused(self):        # gate.human "reject"
def test_wrong_kind_refused(self):
def test_needs_test_next_round(self):       # lane.handled に needs_test → converge が next_round、理由に「最後の関門」
def test_zero_arms_asks_empty(self):        # lane.arms が空 → asking の kinds == ["final_gate_empty"]
def test_worktree_changed_after_cut(self):  # 記録は良いが、受ける前に作業ツリーを変えた → 受けても converge が next_round（写しの文）
def test_post_hoc_without_worktree(self):   # run の worktree を消した後でも post_hoc が verdict を出す（木は gates_cut.rev から）
def test_post_hoc_readonly(self):           # gates_deferred の盤面で post_hoc → verdict "passes"、state.json・record.json の sha256 が前と同じ、final-gate-<tree12>.json が在る
def test_mutgate_command_line(self):        # --from と head_rev が gates_cut.rev、base_rev が record.base の版
```

- [ ] **Step 2: 赤を確かめる** — Run: `nice -n 19 sh works/tests/run.sh -k rounds_final_gate` / Expected: FAIL
- [ ] **Step 3: 書く** — `lane` の型の検査と `_lane_errors(final=True)` は `b.done` の中の写しの `final_gates_output` に任せる（線 B で書き直さない）。`post_hoc` は `gates_deferred` の盤面（`p4.final_gates` が `na`）でも判じられるよう、記憶の中だけで `loop.gates` を外した写しの盤面に当て、`_final_gate_problems` を呼ぶ（ディスクは書かない）。
- [ ] **Step 4: 緑を確かめる** — Run: `nice -n 19 sh works/tests/run.sh` / Expected: `OK`
- [ ] **Step 5: Commit** — `git commit -m "feat(works): 周の輪の最後の関門が mutgate の記録を読む（run の中と、後からの突き合わせ）"`

---

### Task 7: blk-close（周の締め。T5・T6 の後）

**Files:**
- Modify: `works/.shared/core/close.py`（`close_round`・`round_end_pauses`）
- Create: `works/blk-close/blk-close.yaml`・`works/blk-close/scripts/declare.py`・`works/blk-close/scripts/record.py`・`works/blk-close/scripts/collect.py`（PEP 723）
- Create: `works/blk-close/fixtures/next-round.stubs.yaml`・`works/blk-close/fixtures/ask.stubs.yaml`（配線だけ: 3 つの script の節の出口を stub する）
- Test: `works/tests/test_blk_close.py`

**Interfaces:**
- `close_round(board_dir: Path) -> dict` — 仕様 4.5 の 2・3: `b.run_builtin("p4.record")` → ready に `p4.final_gates` が在れば `works-rounds.json` の `final_gate.record` で `final_gate_reply` → `b.done`（拒めば理由を持って一時停止 `final_gate` を開き直す）、無ければ一時停止 `final_gate` → 返り `{"ok": True, "decision": "finished"|"next_round"|"ask", "reason": str, "kinds": list, "round": int}`。`finished` なら `write_finished`。検証器の exit 2（`settle` が止まり `notes` に理由）は `{"ok": False, "reason"}`（スクリプトは終了コード 2）。
- `round_end_pauses(b, st: dict, closed_round: int) -> dict | None` — `closed_round` の `local_checks` が `found` なら `tests_red`、その周で `kind: stuck` の問いが新しく立てば `stuck`、`detect_questions_open` が返せば `questions_open`（審査 I3。重なれば 1 つの関所に項目を並べる）。
- 止めた周の線: 境の節と `report` が `b.stop` の後に `abandon_unrun_lanes` を当てる（審査 m3。T4 の `boundary` と T10 の `report` に 1 行ずつ）。
- `blk-close.yaml`: 入口なし（`$ARTIFACTS_DIR` だけ）。節 `close-declare`（`declare_reviews` と `abandon_unrun_lanes`）→ `close-record` → `close-collect`。`returns: close-collect`・`outcome_field: ok`。script の節は全部 `timeout: 1728000000`。

- [ ] **Step 1: 失敗するテストを書く**

```python
def test_close_next_round(self):            # 周 1 の終わり（block あり）→ decision next_round、round 2
def test_close_asks_max_rounds(self):       # max_rounds 1 の run → decision ask、kinds ["max_rounds"]
def test_close_tests_red_pause(self):       # CI が赤の周 → decision ask、kinds ["tests_red"]、works-rounds.json に開いた関所
def test_close_stuck_pause(self):           # その周に kind stuck の問いが立った見本 → kinds に "stuck"
def test_close_questions_open_pause(self):  # held の問いが答えの無いまま残る周 → kinds に "questions_open"
def test_stop_abandons_lanes(self):         # in_run の周で gates_cut の後に止め札 → running の線が abandoned
def test_close_final_gate_pause(self):      # in_run・記録なし → kinds ["final_gate"]、関所の項目に mutgate_command の 1 行
def test_close_final_gate_takes_record(self):  # in_run・works-rounds.json に good.json のパス → decision finished、status converged
def test_close_finished_deferred(self):     # merge の run で周 3 → decision finished、finished の中身に gates_deferred
def test_record_exit2_fails_node(self):     # 検証器が exit 2 を返す盤面 → ok False、record.py の終了コード 2、関所を開かない
def test_block_yaml_rules(self):            # 1 本目の test_yaml_rules.check_file が blk-close.yaml に誤りを出さない
```

- [ ] **Step 2: 赤を確かめる** — Run: `nice -n 19 sh works/tests/run.sh -k blk_close` と `sh works/dev/check.sh` / Expected: FAIL
- [ ] **Step 3: 書く** — `close-declare` は `p4.record` が ready のときだけ書く（他の段で呼ばれても何もしない）。`close-collect` の `decision` は盤面から決める（`close-record` の出口を `with:` で読まない）。
- [ ] **Step 4: 緑を確かめる** — 同じ / Expected: 緑（`check.sh` は blk-close の 2 本の筋書きが期待どおり）
- [ ] **Step 5: Commit** — `git commit -m "feat(works): 周の締めのブロック blk-close（宣言・記録・最後の関門・赤と詰まりは周の終わりに人へ）"`

---

### Task 8: Archon の試し（AI 費用 0 の分は波 1。数セントの分は持ち主の了承の後）

**Files:**
- Create: `works/dev/probes/rounds/p6a/p6a.yaml`・`works/dev/probes/rounds/p17/p17.yaml`（AI の節を bash に置き換えた工程）
- Create: `works/dev/probes/rounds/p6b/p6b.yaml`・`p6c/p6c.yaml`・`p6e/p6e.yaml`（AI の節を 1 つずつ持つ小さな工程。`model:` を書かない）
- Create: `works/dev/probes/rounds/run.sh`（`mktarget.sh` の対象の `.archon/workflows/` に 1 本写して v0.11.1 で前景で回し、ログを `$WORKS_DEV_HOME/probes/rounds/<名>.log` に置く。`dev/` の直下には YAML を置かない）

**Interfaces:**
- 各試しの問いと合否は仕様 10.2 のとおり。結果は「P<n>: 動く／条件付き／動かない・根拠のログ」の 1 行ずつを Task の報告に書く（台帳と仕様 10.2 への写しは coordinator と T13）。
- P17 の工程: 周の輪の中に、ブロック 7 つ（各々出し直しの輪を 1 つ持ち、中身は bash）・境の節 6 つ・`ask`・`gate`（`decisions: approve, continue, rejudge, stop, reject`）。盤面の代わりに `$ARTIFACTS_DIR/ready.txt` を bash が読み書きする。見る物: `gate` が唯一の末端と認められる（読み込みの警告が until_bash の 1 つだけ）・ブロックの `when:` が境の節の出力だけで選ばれる・`respond continue` の後に同じ周の続きのブロックから入る・途中の Ctrl-C → `resume` で同じブロックから回る。加えて（審査 m1）: `with: {prev: "$LOOP_PREV.gate.output"}` が JSON の文字列で届き、1 回目は空、人の一言に引用符・改行・`$(x)` が在っても壊れない。`when:` で飛ばされた `gate` が回を終えて次の回に入る。include の `with:` が境の節と `start` の欄を読む形で、判定のブロックが飛ぶ回でも落ちない。

- [ ] **Step 1: AI 費用 0 の試し（P6a・P17）を書いて回す** — Run: `sh works/dev/probes/rounds/run.sh p6a` と `… p17`。前景。止めるときは pid と cwd を確かめる。
- [ ] **Step 2: 結果を報告に書く** — P6a が「resume の後に内の輪の 1 回目が新しい会話になる」形なら T9 の resume の形（仕様 4.3）のまま。P17 で `gate` が唯一の末端と認められなければ止めて報告（ラインの形が変わる）。
- [ ] **Step 3: 数セントの試し（P6b・P6c・P6e）の費用の了承を coordinator 経由で持ち主に聞く** — 見込みは合わせて 1 ドル未満（名目）。線 A の P14・P15 と一緒に聞く。了承が無ければ Step 4 を飛ばし、T9 は案 (d) の形のまま作り、崩れた時の倒し方（仕様 4.3 の予備の案 (c)）だけを残す。
- [ ] **Step 4: 了承の後に回す** — Run: `sh works/dev/probes/rounds/run.sh p6b`（p6c・p6e も）。P6e では、内の輪で script の節 `judge-stage` が `judge` の前に在っても 2 回目が 1 回目の会話を継ぐかも見る（審査 m1）。P6e で和の型か会話の続きが崩れたら T9 を案 (c)（2 回目を別の節にし、型を分ける）に倒す（持ち主が決めた予備なので推しで進め、報告に書く）。
- [ ] **Step 5: Commit** — `git commit -m "test(works): 周の輪の Archon の試し（判定の内の輪の上限・この版の輪の形・和の出力の型）"`

---

### Task 9: blk-judge v2（判定の 1 回目と 2 回目。T3 の後。並べてよい: T4・T6）

**Files:**
- Modify: `works/blk-judge/blk-judge.yaml`（`intake` を消す・内の輪 `judge-loop` に `judge-stage`・`judge`・`judge-accept`、`max_iterations: 6`、`judge` の `output_format` は 2 つの型の和に線 A の印 `works-node: judge` を付けた物（`node_marker.mark(union_schema(graph), "judge")`。線 A の再審が判定役の会話を継ぐのに要る）。入口の `request`・`base_rev`（受けて使わない）と `policy_paste`・`premises_file`（線 A の T2）を残す。節の id は 1 本目の `judge-loop`・`judge`・`judge-accept`・`collect` を残す）
- Modify: `works/blk-judge/commands/diagnose.md`（1 本で 1 回目の指示＋「末尾の機械の一言が空でなければそれに従え」。2 回目の指示は graphloops の `prompts/review-loop/p2.history.md` から作り、`judge-accept` が `next` で貼る）
- Create: `works/blk-judge/scripts/stage.py`
- Modify: `works/blk-judge/scripts/accept.py`・`works/blk-judge/scripts/collect.py`（1 本目の欄を全部残し `asks_human` を足す）
- Delete: `works/blk-judge/scripts/intake.py`・`works/blk-judge/fixtures/bad-request.stubs.yaml`（依頼の拒否は `start` の筋書きへ。T12）
- Create: `works/.shared/core/judge2.py`
- Create: `works/tests/replies/judge2_diagnose_r2.json`・`judge2_history_ok.json`・`judge2_history_drops_question.json`・`judge2_history_defer_no_evidence.json`（土台の手本の `p2.diagnose`・`p2.history` の返答の形から）
- Modify: `works/tests/test_blk_judge.py`
- Modify: `works/blk-judge/fixtures/*.stubs.yaml`（`pass`・`pass2`・`bad-reply`）

**Interfaces:**
- `judge2.open_board(board_dir: Path, *, allow_halted: bool = False, entry_open=None) -> DiskBoard` — 仕様 4.3 の「盤面の開き方」（審査 I6）。`entry_open` を渡せばそれ（線 A の `entry.open_board`）を使い、無ければ同じ決まりを線 B の中で行う: `state.works.line` から `works/<line>/nodes.json` を引き、表の sha が `state.works.table_sha` と違えば `BoardMismatch`、ラインの置き場に `board_hook.py` が在ればその `board_kwargs(table)` を `DiskBoard.open` に渡す。線 B の表を決め打ちにしない。
- `judge2.pass_of(b) -> dict` — `{"pass": "diagnose"|"history", "fresh_second": bool}`。`p2.diagnose` の instance が待っていれば diagnose、`p2.diagnose` が済み `p2.history` が待っていれば history。`fresh_second` は内の輪の 1 回目で history になったとき（resume の後。仕様 4.3）。
- `judge2.check(reply: dict, board_dir: Path, *, pass_: str, fresh_second: bool = False) -> dict` — 返り `{"ok": bool, "done": bool, "pass": str, "reason": str, "next": str}`。1 回目は `b.done("p2.diagnose", reply)`、2 回目は `b.done("p2.history", reply)`。`Reject` は `ok: False`・盤面を書かない。1 回目が通って ready に `p2.history` が在れば `done: False`・`next` に履歴の束。`fresh_second` なら `next` に 1 回目の返答ファイルのパスを足し、盤面の trace に `p2.history: 新しい会話で 2 回目` を 1 行。
- `judge2.history_bundle(b) -> dict`（graph の `p2.history` の reads の全部。`r<N>/history.json` にも書く）・`judge2.render_next(bundle: dict, *, cap: int = 40000, path: Path) -> str`（超えたら先頭と「続きは <path>」）
- `judge2.union_schema(graph: dict) -> dict` — `p2.diagnose` と `p2.history` の `schema` の欄の和（`required` は共通の欄だけ・`additionalProperties: false`）。YAML の `output_format` はこれと同じ物（試験が比べる）。
- `judge2.asks_human(b) -> bool` — まだ答えていない `escalate`・`fork` の問いが在る（`rounds.load_state` の `answered` を見る）。
- ブロックの出口（`collect`）: 1 本目の `{ok, judgment_file, need_fix, open_units, …}` を全部残し（`judgment_file` は盤面の `out/r<N>/p2.diagnose.json`）、`asks_human` を足す（`reads_file` は T11）。

- [ ] **Step 1: 失敗するテストを書く**

```python
def test_round1_needs_no_history(self):         # 周 1、判定の見本 → done True（p2.history は na）
def test_round2_asks_history_pass(self):        # 周 2、1 回目が通る → done False・pass "history"・next に問いの台帳と defer 台帳
def test_history_rejects_dropped_question(self):# 前の周の未決の問いが 2 回目の返答に無い → ok False（写しの文）
def test_history_rejects_defer_without_evidence(self):
def test_reject_leaves_board_untouched(self):   # 拒否の回の後、盤面の全ファイルの sha256 が前と同じ
def test_pass_from_board_instances(self):       # instance の状態だけで pass が決まる（盤面の他の欄を変えても同じ）
def test_bundle_covers_history_reads(self):     # history_bundle の鍵が graph の p2.history の reads の全部を覆う（覆えない物は理由つきの一覧）
def test_next_is_capped(self):                  # 40,000 バイトを超える束 → 先頭と続きのパス、r<N>/history.json に全文
def test_fresh_second_after_resume(self):       # 1 回目が済んだ盤面で内の輪の 1 回目 → fresh_second True、next に 1 回目の返答のパス、trace に 1 行
def test_asks_human_from_ledger(self):          # escalate・fork の問いで True、answered に在れば False
def test_output_format_is_union(self):          # blk-judge.yaml の judge の output_format を strip した値 == union_schema(graph)、印が {name: judge, cont: None}
def test_judge_is_only_ai_node_in_inner_loop(self):
def test_exit_keeps_v1_fields(self):            # collect の出口の required ⊇ 1 本目の collect の required
def test_no_intake_in_block(self):              # blk-judge.yaml に intake の節が無い、scripts/intake.py が無い
def test_inputs_compatible_with_track_a(self):   # 入口に request・base_rev・policy_paste・premises_file（どれも required でない）、節の id に judge-loop・judge・judge-accept・collect
def test_track_a_bridge_skips(self):             # v2 で p2.diagnose を受けた盤面では、盤面に p2.diagnose が済んでいる（線 A の渡し替え〔A計〕TA3 が「既に在る」と見る条件）
def test_v2_on_track_a_table_board(self):        # 線 A の形の表（p2.history absent・board_hook 無し）で作った盤面 → 1 回目が通り done True、2 回目を求めない、state.works.overrides が増えない
def test_wrong_table_refused(self):              # state.works.table_sha と違う表を差す → BoardMismatch、盤面が変わらない
```

筋書き（`--dry-run`）: `pass`（周 1。`judge` に見本、`judge-stage` と `judge-accept` は本物）・`pass2`（周 2 の盤面を置き、`judge` の stub は同じ値しか返せないので `judge-accept` を stub して 2 回目の道の配線だけを見る）・`bad-reply`（`fail-node: collect`、R11）。

- [ ] **Step 2: 赤を確かめる** — Run: `nice -n 19 sh works/tests/run.sh -k blk_judge` と `sh works/dev/check.sh` / Expected: FAIL
- [ ] **Step 3: 書く** — 線 A の T2 の `policy_paste`・`premises_file` と指示書の 2 段落と、判定役の印は残す（線 A の T2 が `test_blk_judge.py` の `test_judge_output_format_matches_role_schema` を印を外して比べる形にしている。v2 で型が和になるので、この試験は `test_output_format_is_union` に置き換える）。線 A の試験 `test_judge_block_nodes_unchanged`（`intake` が在るかを見る）が赤になるので、線 A への申し送り（仕様 5 節の申し送り 4）を報告に書く（線 A の試験は直さない）。P6e が崩れた結果なら、2 回目を別の節 `judge-history`（新しい会話・型を分ける）に倒す（仕様 4.3 の予備）。線 A の 1 周のラインもこのブロックを使うので、出口の欄は 1 本目の物を 1 つも消さない。
- [ ] **Step 4: 緑を確かめる** — 同じ / Expected: 緑。**続けて線 A の 1 周のラインの試験を v2 で回し直す**（審査 I7 の 3）— Run: `nice -n 19 sh works/tests/run.sh -k "test_line_a or test_halt or test_entry"`（線 A の通しの試験 `run_line` を含む）と `sh works/dev/check.sh` / Expected: 緑。赤なら v2 を直す（線 A のファイルは直さない。直せない形なら止めて報告）。
- [ ] **Step 5: Commit** — `git commit -m "feat(works): 判定のブロック v2（盤面のラインの表で開き、同じ会話で 1 回目と履歴の 2 回目）"`

---

### Task 10: 報告（線 A の合流の上に載せ直した後。T7 の後）

**Files:**
- Modify: `works/.shared/core/rounds.py`（`report_head`・`report`）
- Create: `works/darkfactory-rounds/scripts/report.py`（PEP 723。ラインの `report` の節と、run の外から `--board <盤面>` で走る口の両方）
- Test: `works/tests/test_rounds_report.py`

**Interfaces:**
- `report(board_dir: Path, *, interrupted: bool = False) -> dict` — 仕様 4.9。盤面を `allow_halted=True` で開き、線 A の `report.gate_record(b)`（止めていない盤面は `settle` → `finalize` → `run_validator` → `report_accepts`。審査 I5）を通す → 線 A の `head_*` で冒頭を組み、線 B の欄を足す。返り `{ok, outcome, judgment_file, review_file?, diff_file?, faces?, rounds, stop_reason?, gates, final_gate_record?, report_file, validator_exit}`。
- 結末の決め方（上から先に当たった物。`outcome` の語は線 A の TA12 に揃える）:
  - 検証器が受理集合の外 → `record_invalid`
  - `interrupted=True`（run の外から、取り消し・`abandon` の後に作る）→ `interrupted`
  - `state.stop.by` が止め札 → `stopped_by_request`
  - `state.stop.by` が `human`・`answer` → `stopped_by_human`
  - `state.stop.by` が `works:*` → `stopped_by_line`
  - `status` が `converged` → `converged`
  - `loop.stop_reason` が `gates_deferred` → `gates_deferred`
  - `loop.stop_reason` が `max_rounds` → `stopped_at_cap`
  - ほかの `stopped` → `stopped`
- `report_head(b, st: dict) -> list[str]` — 仕様 4.9 の ① 〜 ⑥ の順の行。② は節の表の absent と毎周の添え書きの `in_round` から機械で並べる。① は `gates_deferred` なら `mutgate_command` と `final_gate.py` の 1 行ずつ。
- 線 A の部品の口の名前は線 A の計画に合わせる。線 B が要る口（報告の冒頭に線ごとの行を足す）が無ければ止めて申し送り（仕様 5 節）。

- [ ] **Step 1: 失敗するテストを書く**

```python
def test_report_contains_finish_fields(self):  # 1 本目の finish の required ⊆ report の返りの鍵
def test_report_outcomes(self):                # 上の結末の表の全部の行の盤面で outcome が各々
def test_report_runs_validator(self):          # validator_runner に受理集合の外の exit を返す偽（board_hook で差す）→ outcome record_invalid、冒頭 1 行目に出力の末尾、converged を名乗らない（審査 I5）
def test_report_stop_abandons_lanes(self):     # 止めた in_run の盤面の報告の後、process.lanes に running が無い
def test_report_head_order(self):              # 冒頭の行が ①〜⑥ の順、② に表の absent の全部
def test_deferred_head_has_next_steps(self):   # gates_deferred で ① に mutgate を撃つ 1 行と final_gate.py の 1 行
def test_report_standalone_on_board(self):     # run の外から --board で同じ返り（取り消した run の盤面の見本）
def test_report_lists_later_rows(self):        # ② に、入る Task の前の〔答〕の節（p0.parallel_pr・p0.premises・p0.purpose・再審の節）が「このラインに無い節」として理由つきで在る
def test_report_head_uses_track_a_parts(self):  # 線 A の head_cost・declared_downgrades を呼び、downgrades.json が無いラインでは下げた行が 0
```

- [ ] **Step 2: 赤を確かめる** — Run: `nice -n 19 sh works/tests/run.sh -k rounds_report` / Expected: FAIL
- [ ] **Step 3: 書く** — 冒頭は線 A の `head_decisions`・`head_entry`・`head_stop`・`head_reads`・`head_where` をこの順に呼び、線 B の行（集めなかった物の周ごとの `in_round`・周ごとの 1 行・`gates_deferred` の次の 1 行）を ② と ④ に差し込む。結末は上の表の順に 1 つの関数で決める（表を試験と共有する）。
- [ ] **Step 4: 緑を確かめる** — Run: `nice -n 19 sh works/tests/run.sh` / Expected: `OK`
- [ ] **Step 5: Commit** — `git commit -m "feat(works): 周の輪の報告（集めなかった物・結末・周ごとの行を冒頭に）"`

---

### Task 11: ライン `darkfactory-rounds`（T9・T10 の後。P17 の結果を見てから。周の頭は T15・T16、再審は T17 が足す）

**Files:**
- Create: `works/darkfactory-rounds/darkfactory-rounds.yaml`（仕様 2.1 の形。`launch`・`start`・`rounds`［`open`・`judging`・`h-plan`・`planning`・`h-fix`・`fixing`・`h-review`・`reviewing`・`h-refix`・`refixing`・`h-tests`・`testing`・`h-close`・`closing`・`ask`・`gate`］・`report`。`returns: report`）
- Create: `works/darkfactory-rounds/scripts/ask.py`（PEP 723）
- Modify: `works/blk-judge/blk-judge.yaml`（出し直しの輪の後・`collect` の前に `judge-reads`。中身は線 A の `.shared/core/reads.py`）・`works/blk-judge/scripts/reads.py`（数行）・`works/blk-judge/scripts/collect.py`（`reads_file`）
- Test: `works/tests/test_rounds_line.py`

**Interfaces:**
- 入口: `request`（絶対パス）・`test_cmd`・`max_rounds`（既定 5）・`gates`（`merge`｜`in_run`、既定 `merge`）・`adapter`（線 A と同じ意味。既定は台帳の決定どおり包みを要る）。`interactive: true`。
- `ask.py` → `{"ok", "open": bool, "message": str, "kind": str, "stop": bool}`。盤面と `works-rounds.json` だけを読む（仕様 4.8）。`gate` は `approval.decisions: [approve, continue, rejudge, stop, reject]`・`when: $ask.output.open == true`・文言は `$ask.output.message` だけ。
- 合流する節は `depends_on: [open, <直前の境の節>, <直前のブロック>]`・`trigger_rule: none_failed_min_one_success`。ブロックの `when:` は `$h-<段>.output.run == true`（`judging` は `$open.output.run == true`）。
- `open` は `with: {prev: "$LOOP_PREV.gate.output"}`（文字列の束ね。`from:` は使わない。仕様 4.2）。
- ブロックの `with:`（仕様 2.1 の表のとおり。どれも `start`・`open`・`h-*` の欄だけ）:
  - `judging`: `request`・`base_rev`・`policy_paste` ← `$start.output.*`
  - `planning`: `judgment_file` ← `$h-plan.output.judgment_file`、`base_rev`・`policy_paste`・`policy_path` ← `$start.output.*`
  - `fixing`: `judgment_file`・`open_units`・`plan_file`・`human_notes` ← `$h-fix.output.*`、`base_rev`・`policy_path` ← `$start.output.*`
  - `reviewing`: `policy_paste` ← `$start.output.policy_paste`（ほかは線 A の blk-delta の入口に同じ）
  - `refixing`: `base_rev`・`policy_path` ← `$start.output.*`
  - `testing`: `mode: final`・`cmd` ← `$start.output.test_cmd`（blk-tests の既定 `plain` は使わない）
- until_bash は `test -f "$ARTIFACTS_DIR/board/finished"` だけ。

- [ ] **Step 1: 失敗するテストを書く**

```python
def test_line_shape(self):                  # 輪の中の関所が唯一の末端、境の節が 6 つで when を持たない、合流点は none_failed_min_one_success
def test_block_inputs_from_always_run_nodes(self):  # 全部の include の with: の参照先が start・open・h-* だけ（審査 C1）
def test_script_inputs_match_with(self):    # 線 B の各 script の INPUTS の定数 == YAML のその節の with: の鍵
def test_policy_reaches_roles(self):        # 方針の文書の在る対象で start → planning・fixing・reviewing の with: に渡る policy_paste・policy_path が空でない（指示書がそれを読む）
def test_open_prev_is_string_binding(self): # open の with: の prev が "$LOOP_PREV.gate.output" の文字列で、from: を使わない
def test_testing_mode_final(self):          # testing の with: の mode が final
def test_blocks_when_reads_boundary_only(self):  # 各ブロックの when が直前の境の節（judging は open）の run だけを読む
def test_until_bash_reads_board_only(self):
def test_gate_declares_reject(self):
def test_no_model_in_ai_nodes(self):        # include で開いた全部の AI の節に model が無い
def test_stub_ids_unique(self):             # 輪の本体を include で開いたとき、役の節と受け付けの節の id が一意（R19）
def test_track_a_open_board_uses_hook(self):  # 線 B の盤面を線 A の entry.open_board で開くと、state.works.overrides の名の差し替えが効いている（仕様 5 節の約束 1。落ちたら申し送り 1）
def test_track_a_blocks_round2(self):       # 周 2 の盤面（roundskit）で線 A の各ブロックの受け付けのスクリプトが r2/ に書き、entry.take で盤面を進める
def test_track_a_empty_fix_round(self):     # 直す単位 0 の周で boundary が entry.empty_fix_reply を take し、ready に p4.ci（仕様 5 節の約束 4）
def test_judge_reads_present(self):         # blk-judge に judge-reads が在り、collect の出口に reads_file
def test_ask_message_sources(self):         # ask.py が asking・一時停止の各 kind で文を組み、飛ばされうる節の欄を読まない
```

- [ ] **Step 2: 赤を確かめる** — Run: `nice -n 19 sh works/tests/run.sh -k rounds_line` と `sh works/dev/check.sh` / Expected: FAIL
- [ ] **Step 3: 書く** — 線 A のブロックの約束（仕様 5 節の 1〜8）が破れていたら、線 A のファイルを直さずに止めて申し送りの文を報告に書く。`boundary.py` の既定の部品を線 A の本物（`halt.seen`・`reads.adapter_seen`・`entry.take`・`entry.empty_fix_reply`）につなぐ。
- [ ] **Step 4: 緑を確かめる** — 同じ / Expected: 緑。`archon validate workflows darkfactory-rounds` の WARNING は until_bash の「`$gate.output.decision` を見よ」だけ（仕様 2.4 で受け入れる）。
- [ ] **Step 5: Commit** — `git commit -m "feat(works): 周の輪のライン darkfactory-rounds（盤面の ready で段を選び、関所は唯一の末端）"`

---

### Task 12: 筋書き（`--dry-run`。T11 の後）

**Files:**
- Create: `works/darkfactory-rounds/fixtures/*.stubs.yaml`（下の道）
- Create: `works/darkfactory-rounds/fixtures/requests/`（筋書きの依頼。1 本目の `dev/target-seed` の依頼の形）

**Interfaces:**
- 筋書き（`--dry-run` は until_bash を回さないので 1 回の中の道だけ〔R11〕。stub するのは役の節と受け付けの節だけで、`start`・境の節・`collect` などは本物を走らせる）:
  - `judge-asks`: 判定が escalate の問い → `h-plan` が一時停止 → `ask` → `gate`
  - `plan-gate`: 修正案が narrows → `p2.human_gate` の問い → `gate`
  - `full-round`: 判定 → 修正案 → 修正 → 審査 → 手直し → テスト → 締め → next_round（`gate` は飛ぶ）
  - `red-asks`: テストが赤 → 締め → `tests_red` → `gate`
  - `stopped`（配線だけ）: `h-fix` の出口を stub して `{stop: true, run: false}` → 後ろのブロックが全部飛び、`ask` と `report` が走る。止め札の置き方と `report` の結末 `stopped_by_request` は単体テスト（T4 `test_boundary_stop_flag`・T10 `test_report_outcomes`）が見る（模擬実行では run の頭の前に盤面へ止め札を置けないため。筋書きのために工程を変えない）
  - `bad-request`: `start` が依頼を拒む → `fail-node: start`
  - `head-first-round`（T15・T16）: 周 1 で `open`（交差 0）→ `h-pre` → `premising` → `h-purpose` → `purposing` → `h-judge` → `judging`。`pr-fallback`: `open` の stub が `run: true` → `pr-checking` が走る
  - `resume-in-round`（審査 C1）: `start` の後に周 1 の判定まで済んだ盤面を置く形の代わりに、`open` の出口を stub して `run: false`（判定のブロックが飛ぶ回）→ `h-plan` が本物で `planning` を選び、`planning` の `with:` が `start`・`h-plan` の欄だけで落ちない。同じ形で `h-fix` から `fixing` に入る筋も 1 本
- 筋書きごとに stub する鍵（審査 m6。正本は `--stubs-init` の出力）: `head-first-round` は `premises`・`premises-accept`・`purpose`・`purpose-accept`・`judge`・`judge-accept`、`pr-fallback` は `open` と `pr-check`・`pr-accept`、`judge-asks` は `judge`・`judge-accept`、`plan-gate` は `judge`・`judge-accept`・`plan`・`plan-accept`・`plan-review`・`plan-review-accept`、`full-round` はそれに `fix`・`fix-accept`・`review`・`review-accept`・`refix`・`refix-accept`、`red-asks` は `full-round` と同じで対象のテストを赤に、`stopped` は `h-fix`、`resume-in-round` は `open`（と入る先のブロックの役・受け付け）、`bad-request` は無し。

- [ ] **Step 1: 失敗する筋書きを書く**（期待の出口と `fail-node` を先に書く）
- [ ] **Step 2: 赤を確かめる** — Run: `sh works/dev/check.sh` / Expected: 新しい筋書きが FAIL（stub の鍵は `archon.sh workflow run darkfactory-rounds --dry-run --stubs-init <path>` が出す物を正本に）
- [ ] **Step 3: 書く** — 役の stub の返答は T3 の `tests/replies/rounds/` の見本をそのまま使う。`reached` に期待の節の並び、`fail-node` は `bad-request` だけ。
- [ ] **Step 4: 緑を確かめる** — Run: `sh works/dev/check.sh` と `nice -n 19 sh works/tests/run.sh` / Expected: 緑（筋書きが全部期待どおり）。`check.sh` が `darkfactory-rounds` を自動で拾わなければ、T13 で足すと報告に書く。
- [ ] **Step 5: Commit** — `git commit -m "test(works): 周の輪の筋書き（判定の直後の問い・修正前の問い・1 周・赤・止め札・依頼の拒否・同じ周の続き）"`

---

### Task 13: 共有のファイルと仕様の置き直し（全部の後。線 B の最後の commit）

**Files:**
- Modify: `works/.shared/core/gl_map.json`（線 A の対応表に線 B の行: `judge2.check` → `gl accept p2.diagnose`・`p2.history`（判定の受け付けは本線 3-8 待ちの `missing`）、`close.final_gate_reply` → `gl accept p4.final_gates`、`rounds_validator` → `works-only`）・`works/tests/test_gl_map.py`（線 B の行の分）
- Modify: `works/tests/test_yaml_rules.py`・`works/tests/yaml_bad/`・`works/tests/yaml_good/`（仕様 10.4 の決まりのうち、線 A がまだ足していない物だけ。1 本 1 違反の悪い見本: `gate_not_leaf.yaml`・`until_reads_node.yaml`・`loop_max_odd.yaml`・`ai_model_set.yaml` ほか）
- Modify: `works/tests/test_line.py`（`darkfactory-rounds` を検査の対象に）・`works/dev/check.sh`（T12 で自動で拾えなかったときだけ）
- Modify: `works/skills/works/SKILL.md`（周の輪の入口・関所の開く時と答え〔仕様 2.3〕・`gates` の 2 つと mutgate の 1 行・止め方は線 A の節を指す）・`works/README.md`（周の輪の 1 節と、仕様 11 節の要約）・`works/archon-plugin.json`（`darkfactory-rounds` を載せる形なら）
- Modify: `works/docs/specs/2026-09-27-darkfactory-rounds-design.md`（線 A の計画の Task 1 で置いた仕様に、試しの結果を 10.2 に、実装で変わった所を書き戻す。作業の控え（scratchpad）を指す出典は残す物と消す物を分ける）
- Modify: `works/docs/specs/2026-09-26-darkfactory-design.md`（冒頭の「続きの仕様」に 1 行だけ）

- [ ] **Step 1: 失敗するテストを書く** — 悪い見本ごとに「1 本 1 違反で落ちる」試験と、`test_skill_mentions_rounds`（SKILL に `darkfactory-rounds`・`rejudge`・`gates`・`mutgate=` が在る）
- [ ] **Step 2: 赤を確かめる** — Run: `nice -n 19 sh works/tests/run.sh -k "yaml or line or skill"` / Expected: FAIL
- [ ] **Step 3: 書く** — `check_file` の決まりは、線 A が T17 で足した物（`reject`・飛ばされうる欄・`if_skipped`・`trigger_rule`）を先に読み、重ねない。足すのは周の輪だけの物（輪の中の関所は唯一の末端・until_bash は盤面だけ・`max_iterations` の値・`$LOOP_PREV` を `from:` で読まない）。SKILL は線 A の「止め方」の節を指し、周の輪の関所の表（仕様 2.3）を写す。
- [ ] **Step 4: 緑を確かめる** — Run: `nice -n 19 sh works/tests/run.sh` と `sh works/dev/check.sh` / Expected: 緑。README から仕様への相対リンクが開ける。
- [ ] **Step 5: Commit** — `git commit -m "docs(works): 周の輪の仕様を置き、YAML の決まり・スキル・README に周の輪を足す"`

---

### Task 14: 実走（持ち主の費用の了承を取ってから）

**Files:**
- Create: `works/dev/target-seed-rounds/`（周 1 で block が出て周 2・3 で消えるバグ・判定の後に問いを出させる依頼。1 本目の `dev/target-seed` と同じ作り）
- Modify: `works/docs/specs/2026-09-27-darkfactory-rounds-design.md`（10.5 に結果。共有の README は触らない）

**Interfaces:**
- 2 本: ① 3 周で `gates_deferred` まで行く筋（`gates=merge`。終わった後に `final_gate.py` を偽の mutgate の記録で当てる。本物の mutgate は撃たない。周 1 の頭で前提と目的が作られ、周 2 から飛ぶことも見る）② 判定の後に問い → `continue` と `rejudge` を 1 回ずつ → 途中で止め札 → `report` が `stopped_by_request`。同じ周の再審は T17（写し直しの後）の後に、線 A の P20 と同じ費用の了承で 1 本足す。
- 開発の殻（`dev/real-run.sh`。線 A が包みを通す形にした物）で、`--input` に `max_rounds`・`gates` を渡す。

- [ ] **Step 1: 持ち主に「opus で最大 2 回、合わせて 10 ドル（名目）の実走を撃ってよいか」を聞く**（仕様 12 節の 2。coordinator 経由）。了承が無ければここで止める。
- [ ] **Step 2: 撃つ** — 前景。止めるときは pid と cwd を確かめる。
- [ ] **Step 3: 見る** — 周の番号と段の移り・関所が要る時だけ開く・`close_early` の後の周・報告の冒頭（省略・理由・読んだ証拠が 2 つの出どころ・素通しの起動 0）・役の会話が役ごとに新しい（`binding.sessionOrigin`）・所要と費用。
- [ ] **Step 4: 結果を仕様の 10.5 に書く**（所要・費用・拒否の回数・周の数・赤になった所）。赤なら直す課題として報告に並べる。
- [ ] **Step 5: Commit** — `git commit -m "docs(works): 周の輪の実走の結果"`

---

### Task 15: 周の頭の並行 PR と前提（線 A の blk-pr・blk-premises を輪の頭に。T11 の後・T12 の前。線 A の T21・T22 の後）

仕様 1.3・4.12・2.2。`p0.parallel_pr` と `p0.premises` を線 A と同じ行にし、輪の頭に `pr-checking`・`h-pre`・`premising` を置く。包みの確かめを `h-plan` から `h-judge` へ動かす（線 A の TA9 と同じ）。

**Files:**
- Modify: `works/darkfactory-rounds/nodes.json`（`p0.parallel_pr` を `engine_run`・`fallback: role`・where `blk-pr`、`p0.premises` を role・where `blk-premises`）
- Create: `works/darkfactory-rounds/downgrades.json`（線 A の `darkfactory/downgrades.json` と同じ 1 行）
- Modify: `works/.shared/core/rounds.py`（`rounds.BLOCKS`・`rounds.WHERE_TO_BLOCK` に `pr-checking`・`premising`、`open_step` が `prcheck.run_helper` を呼ぶ、`boundary` の包みの確かめを `judging` の段へ、`premises_file` を返りに）
- Modify: `works/darkfactory-rounds/darkfactory-rounds.yaml`（輪の頭に `pr-checking`・`h-pre`・`premising`・`h-judge`。`judging` の `when:` を `$h-judge.output.run`、`with:` に `premises_file`）
- Modify: `works/tests/test_rounds_table.py`（`test_later_rows_name_their_task` から 2 節を外す）・`works/tests/test_rounds_boundary.py`・`works/tests/test_rounds_line.py`
- Test: `works/tests/test_rounds_head.py`

**Interfaces:**
- Consumes: 線 A の `prcheck.run_helper(b, *, runner=None)`・`prcheck.NODE`・`blk-pr`（入口 `base_rev`）・`blk-premises`（入口 `request_file`・`base_rev`）・`reads.adapter_seen`・`report.declared_downgrades`。
- Produces（`rounds.py`）:
  - `rounds.BLOCKS` に `"pr-checking"`・`"premising"` を足す（並びはラインの順）。`rounds.WHERE_TO_BLOCK` に `"blk-pr": "pr-checking"`・`"blk-premises": "premising"`。
  - `open_step(...)`: 切符の後に、ready の `p0.parallel_pr` を `prcheck.run_helper(b, runner=)` で走らせ（`runner` は試験の差し込み）、`boundary(…, "pr-checking")` の返りを返す（任せ先に落ちた時だけ `run: true`）。
  - `boundary(…, at="judging")`: 包みの確かめ（`h-plan` から移す）。表で `p0.premises` が role なのに盤面で済んでいなければ `b.stop("前提の実測が盤面に無い: …", by="works:premises")`。返りに `premises_file`（`state.outputs["p0.premises"]["file"]`。無ければ `""`）。
- Produces（ライン）: `open` → `pr-checking`（`when: $open.output.run == true`、`with: base_rev ← $start.output`）→ `h-pre`（`boundary(…, "premising")`）→ `premising`（`when: $h-pre.output.run == true`、`with: request_file・base_rev ← $start.output`）→ `h-judge`（`boundary(…, "judging")`）→ `judging`（`with:` に `premises_file ← $h-judge.output.premises_file`）。合流の節は `trigger_rule: none_failed_min_one_success`。

- [ ] **Step 1: 失敗するテストを書く**

```python
def test_parallel_pr_row_matches_track_a(self):  # 両方の表で p0.parallel_pr が engine_run・fallback role・where blk-pr、p0.premises が role・where blk-premises
def test_open_runs_parallel_pr_engine(self):     # 偽の runner が交差 0 → open の返りの run False、process.checks["p0.parallel_pr"].by == "engine"
def test_open_fallback_runs_block(self):         # 偽の runner が交差 1 件 → run True、盤面の p0.parallel_pr が任せ先で待つ
def test_premises_first_round_only(self):        # 周 1 は h-pre の run True、周 2 は p0.premises が once で ready に無く run False
def test_adapter_check_moved_to_judging(self):   # launches.jsonl にこの run の行が無い・adapter "" → boundary(at="judging") で stop、at="planning" では見ない
def test_judging_stops_without_premises(self):   # 表で role の p0.premises が盤面で済んでいない → boundary(at="judging") が stop、by "works:premises"
def test_premises_file_reaches_judge(self):      # YAML の judging の with: premises_file が $h-judge.output.premises_file、h-judge の返りが state.outputs と合う
def test_downgrade_in_report_head(self):         # 報告の冒頭 ② に downgrades.json の 1 行
```

- [ ] **Step 2: 赤を確かめる** — Run: `nice -n 19 sh works/tests/run.sh -k rounds_head -k rounds_boundary -k rounds_line` / Expected: FAIL
- [ ] **Step 3: 書く** — 線 A のブロックとモジュールは読むだけ（直さない）。約束が破れていたら止めて申し送る（仕様 5 節の 10）。
- [ ] **Step 4: 緑を確かめる** — Run: `nice -n 19 sh works/tests/run.sh` と `sh works/dev/check.sh` / Expected: 緑
- [ ] **Step 5: Commit** — `git commit -m "feat(works): 周の輪の頭に並行 PR の検査と前提の実測（線 A のブロック）を置く"`

---

### Task 16: 目的の文 `p0.purpose`（blk-purpose。T15 の後・T12 の前）

仕様 4.10。1 周目の判定の前に目的の文を作り、判定役に渡す。

**Files:**
- Create: `works/blk-purpose/blk-purpose.yaml`・`works/blk-purpose/commands/purpose.md`（a1202d0 の `prompts/review-loop/p0.purpose.md` を写し、`{{…}}` を入口のファイルを読む形に）・`works/blk-purpose/scripts/snap.py`・`accept.py`・`reads.py`・`collect.py`・`works/blk-purpose/fixtures/pass.stubs.yaml`
- Modify: `works/darkfactory-rounds/nodes.json`（`p0.purpose` を role・where `blk-purpose`）
- Modify: `works/.shared/core/rounds.py`（`rounds.BLOCKS`・`rounds.WHERE_TO_BLOCK` に `purposing`、`boundary(…, "purposing")` が `premises_file` を、`boundary(…, "judging")` が `purpose_file` を返す）
- Modify: `works/blk-judge/blk-judge.yaml`（入口 `purpose_file`。`default: ""`）・`works/blk-judge/commands/diagnose.md`（その入口を読む 1 段落）
- Modify: `works/darkfactory-rounds/darkfactory-rounds.yaml`（`h-purpose`・`purposing` を `premising` と `h-judge` の間に、`judging` の `with:` に `purpose_file`）
- Create: `works/tests/replies/purpose_ok.json`・`purpose_bad_source.json`・`purpose_writer_summary.json`（出典 ③）
- Test: `works/tests/test_blk_purpose.py`

**Interfaces:**
- Consumes: 線 A の `entry.main_take`・`entry.snapshot`・`reads.main_for`・`node_marker.mark`・`accept.role_schema("p0.purpose")`。
- Produces（blk-purpose）: 入口 `request_file`・`base_rev`・`premises_file`。`purpose-snap` → `purpose-loop`（`max_iterations: 3`）: 役 `purpose`（`[Read, Grep, Glob]`・sandbox・`settingSources: []`・`output_format` = `mark(role_schema("p0.purpose"), "purpose")`）＋ `purpose-accept`（`main_take("p0.purpose", snapshot_name="purpose-snapshot.json")`。works だけの検査は足さない）→ `purpose-reads` → `collect`（`{ok, purpose_file, source, reads_file}`）。
- Produces（blk-judge の入口）: `purpose_file`（文字列、既定は空）。指示書の段落の芯: 「目的の文（凍った版。空なら無い）: `$INPUTS.purpose_file` を Read せよ。split・fork・resolved の判定に使え」（graph の `p0.purpose` の note と同じ理由）。
- Produces（報告）: 出典が「③writer の要約」か「目的不明」の時、冒頭 ① に「目的の文は役の要約（出典 ③）で、別の目の審査（`p0.purpose_review`）が無い」の 1 行（T10 の `report_head` に足す）。

- [ ] **Step 1: 失敗するテストを書く**

```python
def test_purpose_ok_accepted(self):              # 前提を受けた盤面に purpose_ok → ok、record.process.purpose、ready に p2.diagnose
def test_purpose_schema_rejects(self):           # purpose_bad_source（enum の外の source）→ ok False、盤面が前のまま
def test_purpose_readonly_tree_changed(self):    # purpose-snap の後に作業ツリーを変える → ok False
def test_purpose_first_round_only(self):         # 周 2 は h-purpose の run False
def test_purpose_file_reaches_judge(self):       # judging の with: purpose_file が $h-judge.output.purpose_file、diagnose.md が $INPUTS.purpose_file を 1 度読む
def test_writer_summary_head_line(self):         # purpose_writer_summary → 報告の冒頭 ① に「出典 ③」「審査が無い」の 1 行
def test_output_format_marked(self):             # strip した値 == role_schema("p0.purpose")、印の名 purpose
def test_purpose_row_is_role(self):              # nodes.json の p0.purpose が role・where blk-purpose、p0.purpose_review は absent
```

- [ ] **Step 2: 赤を確かめる** — Run: `nice -n 19 sh works/tests/run.sh -k blk_purpose -k rounds_line` / Expected: FAIL
- [ ] **Step 3: 書く** — `blk-purpose` の役は Bash を持たず作業ツリーを変えないので、今の共有の試験の決まりで通る（YAML もこの Task で入れる）。線 A の 1 周のラインは `purpose_file` を渡さないので、blk-judge は既定の空で動く（線 A の試験を v2 で回し直して確かめる）。
- [ ] **Step 4: 緑を確かめる** — Run: `nice -n 19 sh works/tests/run.sh` と `sh works/dev/check.sh` / Expected: 緑（線 A の `test_line_a` も緑）
- [ ] **Step 5: Commit** — `git commit -m "feat(works): 周の輪の 1 周目に目的の文を作る blk-purpose と、判定役への入口"`

---

### Task 17: 同じ周の再審（線 A の blk-rejudge を輪の中に。**写し直しの後**。線 A の T23 の後）

仕様 4.11・2.3。本線 3-6 の往復（再審 3 回・修正役の再異議 2 回・第三の目）を周の輪の修正の後に置く。会話の id が無い周は一時停止 `rejudge_no_session` で聞く。この Task は T13（線 B の最後の共有の commit）の後なので、共有のファイルは最後の 1 commit でだけ触る。

**Files:**
- Modify: `works/darkfactory-rounds/nodes.json`（写し直しの後の再審の 6 節を role・where `blk-rejudge`）
- Modify: `works/.shared/core/rounds.py`（`rounds.BLOCKS`・`rounds.WHERE_TO_BLOCK` に `rejudging`、`boundary(…, "rejudging")` の先の確かめ、一時停止 `rejudge_no_session` と答えの表の行）
- Modify: `works/darkfactory-rounds/darkfactory-rounds.yaml`（`h-rejudge`・`rejudging` を `fixing` と `h-review` の間に）・`works/darkfactory-rounds/scripts/ask.py`（文に `rejudge_no_session` の行）・`works/darkfactory-rounds/fixtures/`（`rejudge`・`rejudge-no-session` の 2 本）
- Modify（共有。最後の 1 commit）: `works/tests/test_line.py`（周の輪の形）・`works/skills/works/SKILL.md`（周の輪の関所の表に `rejudge_no_session` の行）
- Test: `works/tests/test_rounds_rejudge.py`

**Interfaces:**
- Consumes: 線 A の `rejudge.route`・`rejudge.session_ready`・`blk-rejudge`（入口 `base_rev`・`policy_paste`・`policy_path`）・`ticket.session_path`、土台の `b.skip`。
- Produces（`rounds.py`）:
  - `boundary(…, at="rejudging")`: `rejudge.route(board_dir)` の `next` が 1 回目の再審で `session_ready` が偽なら、ブロックを回さず `open_gate(board_dir, "rejudge_no_session", "pause", [異議の行])`・`{run: False, ask: True}`。`next` が在れば `run: True`。
  - `apply_answer` の表に `rejudge_no_session` の行: `continue` → `b.skip("p2.rejudge", "判定役の会話が無い: 人が飛ばすと答えた")`（graph で optional）で同じ周の続き、`rejudge` → `close_early`、`stop`・`reject` → 止める。
- Produces（ライン）: `h-rejudge`（`boundary(…, "rejudging")`）→ `rejudging`（`when: $h-rejudge.output.run == true`、`with: base_rev・policy_paste・policy_path ← $start.output`）→ `h-review`（`depends_on` に `h-rejudge`・`rejudging`）。

- [ ] **Step 0: 写し直しと線 A の T23 を確かめる** — 写しに 3-6 の再審の節と `REJUDGE_PASSES` が在り、線 A の枝に `rejudge.py`・`blk-rejudge` と `test_blk_rejudge.py` の緑が在る。無ければ止めて報告する。
- [ ] **Step 1: 失敗するテストを書く**

```python
def test_rejudge_in_round_two(self):             # 周 2 の盤面で異議 → boundary(at="rejudging") の run True、blk-rejudge のスクリプトで 1 回目を通す → record.process.rejudge に行、ready に p3.delta_review
def test_rejudge_continues_this_rounds_judge(self):  # 包みの偽の起動で周 1・周 2 の判定役が judge.id を書き直す → 周 2 の再審の起動の --resume が周 2 の id
def test_no_session_pauses(self):                # judge.id が無い → run False・ask True、works-rounds.json の gate.kind "rejudge_no_session"、p2.rejudge は待ちのまま
def test_no_session_continue_skips(self):        # その関所に continue → p2.rejudge が skipped、同じ周の差分の審査へ、次の周の p2.history が異議を読む（写しの規則のまま）
def test_no_session_rejudge_closes_round(self):  # rejudge → close_early で次の周
def test_no_session_stop(self):                  # stop → 止まり finished
def test_ask_message_no_session(self):           # ask.py の文に「判定役の会話が見つからない」と答え方 3 つ
def test_rows_are_roles(self):                   # nodes.json の再審の 6 節が role・where blk-rejudge、線 A の表と同じ
```

- [ ] **Step 2: 赤を確かめる** — Run: `nice -n 19 sh works/tests/run.sh -k rounds_rejudge` / Expected: FAIL
- [ ] **Step 3: 書く** — 線 A のブロックとモジュールは読むだけ。再審の順と数は盤面の ready だけで決める（線 B は持たない）。
- [ ] **Step 4: 緑を確かめる** — Run: `nice -n 19 sh works/tests/run.sh` と `sh works/dev/check.sh` / Expected: 緑
- [ ] **Step 5: Commit** — `git commit -m "feat(works): 周の輪に同じ周の再審（本線 3-6 の形・会話が無い周は一時停止）を置く"`

---

### Task 18: ブロックの名前と `where` を本線に揃える（**本線の 3-7 が版に入った後**。線 A の T25 と同じ時に。小さな作業）

回す側の指示（2026-09-27）。本線のブロックの置き場と名前（`graphloops/blocks/review-loop/<ブロック>/block.json`）が 3-7 で決まったら、線 B の仮の名（`blk-close`・`blk-purpose`）と節の表の `where` を揃える。

**Files（3-7 の中身しだい）:**
- Modify: `works/darkfactory-rounds/nodes.json`（`where` に本線のブロック名。形は線 A の T25 と同じ）・`works/.shared/core/rounds.py`（`rounds.WHERE_TO_BLOCK` を `where` の works の置き場の側で引く）
- Rename（要る時だけ。`blk-close` は本線の close と 1 対 1 の見込み、`blk-purpose` は本線の prereq の一部）
- Test: `works/tests/test_rounds_table.py`（`test_where_matches_mainline_blocks`）

- [ ] **Step 1〜5**: 失敗する試験 → 赤 → 書く → 緑（`nice -n 19 sh works/tests/run.sh` と `sh works/dev/check.sh`）→ Commit `git commit -m "refactor(works): 周の輪のブロックの名前と節の表の where を本線に揃える"`

---

## 写し直しへの依存（本線 3-5・3-6。回す側の指示 2026-09-27。線 B の作業ではない）

写し直しは本線の 3-5（27a818a）と 3-6（d1b863f の続き）が版に入るまで見送り、入ったら写し直しの線が 1 回で写す。要る物の一覧は線 A の計画の同じ名の節（1〜7）が正本。線 B に関わる所だけを写す:

- `darkfactory-rounds/nodes.json` の graph_sha と、新しい機械の節 `p2.fix_units`（builtin）と再審の 4 節（T17 まで absent）の行。線 B の手本（`tests/replies/rounds/` の返答の見本と roundskit の盤面）を新しい graph で通し直す。
- 盤面の層の受け付けが engine の `commands.post_check` を通す形に替わる（新しい返り `{ok: false}`）。線 B の `judge2.check` と `close.final_gate_reply` はその口を通して盤面に渡すので、形は変えずに試験を回し直す。
- 3-5 で規則が `loop.gates_cut` でなく `p3.gates_cut` の出力を読む。線 B の `close.mutgate_command`・`check_mutgate`・`post_hoc` が読む `loop.gates_cut.rev` を `p3.gates_cut` の出力へ替える（仕様 8 節の薄い関数の 1 か所）。線 C の `mutcore` も同じ直しが要る（線 C の持ち物）。
- `accept.py` の `DeltaPass.state_key` が消える（盤面の層と線 A の `refix.passes()` の直し。線 B は触らない）。
- 検証器の包み `rounds_validator.py` は写しの RR を読み込むので、写し直しの後に `test_rr_file_untouched` と縛り ①〜③ を回し直す。
- 止める猶予は works の 2 秒のまま。

## 改訂（盤面の層に載せ替え）（2026-09-27）

1 版（15 Task。作業の控え（scratchpad）の `rounds-plan-draft.v1.md`）は、線 B が自前の盤面を作り、写しに足し算をし、止め札・包み・読んだ証拠・数え直しも作る前提だった。盤面の層（土台）の実装と、線 A への割り当て（〔土〕BL13）に合わせて 14 Task に組み直した。

- **前提と決まりの替わった所**: 写し元を fbd40e3 から a1202d0 に（〔土〕BL1）。写しは 1 バイトも変えない（BL2。1 版の `COPIED_FROM` に足し算を記す決まりを取り下げ）。ラインは `darkfactory/` の書き換えでなく別の入口 `darkfactory-rounds/`（R25）。`model:` を YAML に書かない決まりを足した（R22・R28）。数セントの試しも持ち主の費用の了承の後に回した。
- **並べ方**: 1 版の波 1 の「T1 盤面」は土台の計画が済ませるので、前提（波 0）に移した。線 A の物が要る Task（T10 以降）の前に、枝を線 A の合流の上に載せ直す段を置いた。blk-judge v2 は線 A も使うので早い波（波 3）に置いた。

1 版の Task との対応:

- 1 版 T1（盤面の見本と DiskBoard・`accept.py` の差し替え）→ **土台へ**（〔土〕の計画 T1〜T9）。線 B は前提として使うだけ。
- 1 版 T2（写しの検証器と規則に `not_in_line`）→ **新 T1**（節の表と、表から導く宣言）＋**新 T2**（検証器の包み。写しは変えない）＋**新 T3**（`overrides` 2 つと目の宣言で盤面に差し込み、収束の道を通す）。最後の関門の宣言（`final_gate: true`）は取り下げ、**新 T6**（mutgate の記録）に替えた。
- 1 版 T3（周の頭 `start`・`open`）→ **新 T4**（`start` は `DiskBoard.begin`、境の節は ready で選ぶ）＋**新 T5**（`open` の答えの当て方・一時停止・`close_early`）。周の頭の版固めと `on_new_round` は土台の `settle` が回すので、線 B の `_snapshot` と「周の番号を上げる」決まりは消えた。
- 1 版 T4（blk-close）→ **新 T7**。`record_round`・`converge` は土台の `run_builtin`・`settle` を呼ぶだけになり、engine と同じかの差分の試験は土台の通しの再生（〔土〕の計画 T7）が持つ。検証器の exit 2 を `stuck_unlisted` の問いに写す形は取り下げ（a1202d0 は判定の受け付けで縛る）、`stuck` の問いが立った周で聞く形に替えた。
- 1 版 T5（Archon の試し P6a〜c・P7〜P15）→ **新 T8**。P7〜P13・P16 は済み。P11 の AI の節の分・P13 の `tool_called`・P14・P15 は**線 A へ**（〔A〕9.3）。P17（この版の輪の形）と P6e（判定の出力の型の和）を足した。
- 1 版 T6（blk-judge v2）→ **新 T9**。受け付けを `b.done` に、回の見分けを盤面の instance に替え、出力の型の和と resume の時の新しい会話の 2 回目を足した。`judge-reads` は線 A の部品が要るので **新 T11** に分けた。
- 1 版 T7（blk-fix の数え直し）→ **線 A へ**（〔土〕BL13、〔A〕3.2）。線 B は約束（開いた単位 0 の周で通る）を新 T11 で確かめる。
- 1 版 T8（blk-tests・blk-delta を周の置き場へ）→ **線 A と土台へ**（作業ファイルの `r<N>/` は土台の `board.work()`、ブロックは線 A）。周 2 で動くかは新 T11 の約束の試験で見る。
- 1 版 T9（止め札と境の節）→ 止め札・`stop.sh`・`report.sh`・`halt.py` は**線 A へ**（BL10・BL13）。境の節は **新 T4** の `boundary`（線 A の `halt.seen` を読み、土台の `stop()` を呼ぶ）。
- 1 版 T10（Claude の包み）→ **線 A へ**（BL13）。
- 1 版 T11（読んだ証拠の節）→ **線 A へ**。判定の `judge-reads` だけ線 B が **新 T11** で置く。
- 1 版 T12（ライン v2・`ask`・`report`）→ **新 T10**（報告）＋**新 T11**（ライン `darkfactory-rounds.yaml`・`ask`）。
- 1 版 T13（筋書きと YAML の決まり）→ **新 T12**（筋書き）＋**新 T13**（YAML の決まりは共有のファイルなので最後の 1 commit に）。
- 1 版 T14（スキル・README・仕様の置き直し）→ **新 T13**。
- 1 版 T15（実走）→ **新 T14**（結果は共有の README でなく線 B の仕様に書く）。

新しく足した物: **新 T6**（最後の関門が mutgate の記録を読む。台帳 R30）と、`close_early`（**新 T5**。rejudge を写しの `_stopped_round_record` と engine の `open_next_round` で組む）。

線 A の計画（〔A計〕）に揃えた所: 境の節は線 A の部品（`halt.seen`・`reads.adapter_seen`・`entry.take`・`entry.empty_fix_reply`）を引数で受ける（新 T4）。直す単位 0 の周は修正の役を起こさず空の返答を渡す（〔A計〕TA6）。blk-judge v2 は線 A のラインが渡す `request`・`base_rev`・`policy_paste` と 1 本目の節の名前を残す（新 T9）。線 A のブロックが線 B の盤面を開くときの口 `board_hook.py` を新 T3 で置き、効くかを新 T11 で確かめる。

持ち主の答え待ちの扱い: 軽量は標準だけ（手厚さの入力を持たない）、並行 PR は `p0.parallel_pr` の表の 1 行を absent にして他に語を置かない（新 T1 の試験で縛る）、`p2.rejudge` は absent（仕様 12 節の 1 の案 1。答えが案 2・3 なら `blk-rejudge` を足す小さな後の Task）。

## 改訂 5（審査 作業の控え（scratchpad）の `rounds-plan-review.md`「Approve with changes」への対応。2026-09-27）

回す側の裁定に従い、C1・I1〜I7・m1〜m10 を直した。線 A の計画と仕様の改訂 2（`works/docs/plans/2026-09-27-darkfactory-single-run.md`・`works/docs/specs/2026-09-27-darkfactory-single-run-design.md`）の口にも揃えた。Task の数は 14 のまま。前の版は 作業の控え（scratchpad）の `rounds-plan-draft.v2.md`。仕様の側の直しは仕様の「改訂 5」。

- **C1**（ブロックの入口の配線と方針の文書）: Global Constraints に「入口はいつも走る節の欄か盤面からだけ」を足した。T4 の `start` の返りに `base_rev`・`test_cmd`・`policy_paste`・`policy_path`、`boundary` の返りに `judgment_file`・`open_units`・`plan_file`・`human_notes` を足した（`test_start_policy_outputs`・`test_boundary_block_inputs`）。T11 にブロックごとの `with:` を全部書き、`test_block_inputs_from_always_run_nodes`・`test_policy_reaches_roles` を足した。T12 に判定のブロックが飛ぶ回の筋書き `resume-in-round` を足した。
- **I1**（`$LOOP_PREV`）: T5 の `open.py` と T11 の `open` を `with: {prev: "$LOOP_PREV.gate.output"}` の文字列に替えた（`test_prev_string_forms`・`test_open_prev_is_string_binding`）。P17 に確かめる物を足した（T8）。
- **I2**（決着した `fork`）: T5 の `detect_judge_asks` の条件を直し、`answered` を `key|status` にした（`test_judge_asks_escalate_fork`）。
- **I3**（`held` の問い）: 持ち主の決定どおり `questions_open` を足した（T5 `detect_questions_open`・`test_questions_open_held`、T7 `round_end_pauses`・`test_close_questions_open_pause`）。持ち主に聞く物ではない。
- **I4**（`rejudge` の副作用）: T5 の `apply_answer` で `max_rounds`・`final_gate_empty` への `rejudge` を `reask` にした（`test_rejudge_no_continue_side_effects`）。
- **I5**（報告の前の検証器）: T10 の `report` が線 A の `gate_record` を通し、外なら `record_invalid`。結末の決め方の表を足した（`test_report_runs_validator`）。
- **I6**（判定 v2 の盤面の開き方）: T9 に `judge2.open_board`（ラインの表・`table_sha` の突き合わせ・`board_hook.py`）を足した（`test_v2_on_track_a_table_board`・`test_wrong_table_refused`）。
- **I7**（線 A との並べ方）: 前提に「線 B の枝は線 A の T2 と TA18 の 4 件の後に、線 A の枝の先から切る」を書いた。T4 に Step 0（TA18 の 4 件の在りかと線 A の試験の緑を確かめる）を足した。T9 の Step 4 で線 A の 1 周のラインの試験を v2 で回し直す。T10 の前の載せ直しの直後に `check.sh` を 1 度通す。
- **m1**: T8 の P17・P6e に確かめる物を足した。**m2**: 土台への申し送り（差し替え無しで開いたら `BoardGap`）は仕様 5 節に書き、台帳の側で土台へ渡す。**m3**: 止めた周の線を `abandoned` にする（T7・T10 `test_stop_abandons_lanes`・`test_report_stop_abandons_lanes`）。**m4**: `p2.human_gate` への `rejudge` は `answer: "rejudge"` の行（T5）。**m5**: `post_hoc` は `gates_cut.rev` の木だけで比べる（T6 `test_post_hoc_without_worktree`）。**m6**: T3 の返答の見本の名前を全部書き、T10 に結末の表、T12 に筋書きごとの stub の鍵、T12・T13 の Step 3 に手掛かりを書いた。**m7**: 締めた周も上限と 3 周の数に入る（仕様 4.4・11.3）。**m8**: 仕様の `entry.take` の引数を直した。**m9**: engine の問いと一時停止が重なった回（T5 `test_overlapping_ask_and_pause`）。**m10**: `start` が `test_cmd` を控え、`mutgate_command` がそれを使う（T4・T6）。線 A の名前（`entry.local_checks_material`・`entry.run_ci`）に揃えた。
- **線 A の改訂 2 に揃えた所**: blk-tests は `mode: final` を明示で渡し、既定の `plain`（1 本目と mutgate の約束）は使わない（T11 `test_testing_mode_final`）。`start` は `entry.run_ci` を使う。`open_board` は線 A の `entry.open_board`（`board_hook.py` を読む）と同じ決まり。報告は `head_*` と `gate_record`、結末に `record_invalid`・`interrupted`・`stopped_by_line`。各 script の `INPUTS` の定数を YAML の `with:` と突き合わせる（T11 `test_script_inputs_match_with`）。作業ファイルと役の出力は `b.work`・`state.outputs[節]["file"]` から引き、`r1` を決め打ちにしない。方針の入口は `policy_paste`・`policy_path`（旧 `policy_file`＋`brief` は使わない）。
- 持ち主に聞く物は増えていない（`p2.rejudge` は仕様 12 節の 1 のまま、仮の扱い absent）。

## 改訂（持ち主の答え 2026-09-27）

朝の 4 つの答えと、回す側の指示（本線の調べ〔本〕と本線からの知らせ）を入れた。仕様の側は「改訂 6」。線 A の計画の同じ名の節の口に揃えた。番号は 18 個（T15〜T18 を足した）。回す順は T11 → T15 → T16 → T12 → T13 → T14、写し直しの後に T17、本線の 3-7 の後に T18。

- **1. 軽量は案 1（下げない）**: 前提の段を直しただけ（線 B は手厚さの入力を持たないまま）。
- **2. 並行 PR は案 (a)**: T15 を足した（`p0.parallel_pr` を線 A と同じ `engine_run`・`fallback: role` に、`open` が線 A の `prcheck.run_helper` を呼び、任せ先に落ちた周だけ線 A の `blk-pr`、`downgrades.json`）。T1 の `test_parallel_pr_isolated`（語を表の 1 行に閉じ込める）を `test_later_rows_name_their_task` に替え、Review Focus の 9 を直した。
- **3. 前提と目的**: 前提は T15（線 A の `blk-premises` を輪の頭に・包みの確かめを `h-judge` へ）、目的は T16（新しい `blk-purpose`・blk-judge の入口 `purpose_file`・出典 ③ の報告の 1 行）。T9 は線 A の T2 の入口 `premises_file` を残す。
- **4. 同じ周の再審は上位互換**: T17 を足した（線 A の `blk-rejudge` を修正の後に、会話の id が無い周は一時停止 `rejudge_no_session`、`continue` は `b.skip("p2.rejudge")`）。T9 の判定役に線 A の印 `works-node: judge` を残す（`test_output_format_is_union` は印を外して比べる）。Review Focus の 13 を足した。
- **回す側の指示**:
  - 再審は本線の 3-6（3 往復と第三の目）の形で、写し直しの後に入れる（T17 は写し直しと線 A の T23 の後）。
  - 受け付けの口は本線の 3-8 まで `accept.py` のまま。線 B も検査を足さず、線 A の対応表 `gl_map.json` に線 B の行を T13 で足す（Global Constraints・T13）。
  - ブロックの名前と `where` は works の仮の名。本線の 3-7 の後に T18 で揃える。
  - 写し直しに要る物を「写し直しへの依存」に控えた（線 B の作業ではない。線 B の側で直す所は `loop.gates_cut` を読む薄い関数と節の表と手本）。
  - 止める猶予は works の 2 秒のまま。
- **線 A との口**（〔A計〕の改訂の「線 B との口」と同じ一覧）: `node_marker`（A T2）・`ticket.session_path`（A T5）・`prcheck.run_helper`・`blk-pr`（A T21）・`premises`・`blk-premises`（A T22）・`rejudge.route`・`rejudge.session_ready`・`blk-rejudge`（A T23）・`report.head_cost`・`declared_downgrades`（A T15）・`gl_map.json`（A T24）。
