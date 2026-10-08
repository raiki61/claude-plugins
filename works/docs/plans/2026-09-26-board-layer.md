# 盤面の層（works の共通の土台）Implementation Plan

状態: 入れた（works 0.2.0。`.shared/core/board.py` の `DiskBoard` と手本 `tests/boards/golden-a1202d0/`）。

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. 下請けは全部 opus（台帳 Ruling R22）。

**Goal:** 線 A・B・C が後から直さずに使える盤面の層を作る。graphloops の engine と同じ形の盤面をディスクに置き、写した engine の `Board` を継いだ `DiskBoard` が、engine と同じ控え（instance）を残して節を受け、engine と同じ順で機械の節を回し、engine が走らせる節（CI）を engine と同じ記録で走らせる。v1 の `accept.py` は振る舞いを変えずに偽の盤面から移す。

**Architecture:** `works/.shared/core/board.py` 1 本に、節の表（`NodeTable`）・誤りの型（`BoardGap`・`BoardMismatch`）・`DiskBoard`（engine の `Board` を継ぐ。上書きは `__init__`・`save`・`run_validator` だけ）・盤面なしの口（`rules_module`・`graph_expanded`）を置く。盤面を進める口は、settle しない物（`accept`・`step_builtin`・`run_engine`）と、settle まで回す物（`done`・`run_builtin`・`answer`・`skip`）に分ける。正しさは、a1202d0 の graphloops の台本を回し、engine の中で手の前後の記憶を撮った手本（`works/tests/boards/golden-a1202d0/`）に、同じ手を当てて比べる。

**Tech Stack:** Python 3（pack の中は標準ライブラリだけ）・git・graphloops 0.21.0（a1202d0）の写し・graphloops の台本 `simulate_review.py`（手本を撮るときだけ。AI 0・お金 0）。

**Spec:** `works/docs/specs/2026-09-26-board-layer-design.md`（以下「仕様 N 節」）。

**前提（波 0。着手の時に 1 度だけ確かめる）:**
- 済み: 写し直しの枝 `wip/works-core-021`（a1202d0 の写し。先頭 1833773）に、`scripts/comment-ratio.sh`・根の `REVIEW.md`（3a89a95）と `graphloops/scripts/parallel-pr.py`（1833773）が同じバイトで入った（`COPIED_FROM` に載り、`test_core_copy.py` がバイトの一致を見る）。
- 写し直しの枝が `wip/archon-pack` の先頭に載り直して合流している。この計画の枝 `wip/works-board` はその先頭から切る。
- 持ち主の答え（仕様 13 節の 1・2）は要らない。この計画の Task 1〜10 はどちらの答えにも依らない:
  - 1（軽量）: 仮の裁定は案 1（標準だけ）。この層は optional の節しか省かせない。答えが案 2 なら、別の小さな計画で `downgrade` を足す。
  - 2（並行 PR の申し送り）: 仮の裁定は「この層は engine_run と任せ先の配管だけ」。`p0.parallel_pr` の表の行と役は、答えの後に線 A・B が決める。この計画の試験は、試験用の表で `p0.parallel_pr` を absent と engine_run（`fallback: role`）の両方で見るだけで、役も投稿も作らない。

## Global Constraints

- 触ってよいのは `works/` の下だけ。graphloops・convergence-loops・リポジトリ直下の共有ファイル・台帳（`.superpowers/`）は触らない（台帳への裁定の写しは計画の外で持ち主の会話の側が行う）。graphloops の台本は a1202d0 を `git archive` で使い捨ての場所に出して回すだけ。
- **写し（`works/.shared/core/graphloops/**`・`works/.shared/core/scripts/**`・`COPIED_FROM`・`works/tests/test_core_copy.py`）は 1 バイトも変えない**（仕様 BL2）。
- 持ち物（仕様 6 節）: この計画が触るのは `board.py`・`accept.py`（Task 9 の 1 度だけ）・`works/tests/test_board*.py`・`works/tests/test_core_verbatim.py`・`works/tests/test_accept_v1_golden.py`・`works/tests/boardreplay.py`・`works/tests/boards/**`・`works/dev/board-goldens/**`・`works/docs/specs/2026-09-26-board-layer-design.md`。共有のファイル（仕様 6 節の一覧）は最後の 1 commit で `works/README.md` だけ。ブロック・ライン・`blk-*`・`darkfactory*`・`tests/replies/` は触らない。
- pack の中の Python は標準ライブラリだけ。`__pycache__` を作らない（テストは `PYTHONDONTWRITEBYTECODE=1`）。`works/dev/` と `works/*/scripts/` の直に起こす Python の頭には PEP 723 の塊。**例外**: `works/dev/board-goldens/sitecustomize.py` は Python が起動の時に import する物で、`uv run` で起こさないので塊を持たない（`test_script_headers.py` の対象の外に置けないなら、塊を付けても害は無いので付ける）。
- 新しい期限を足さない（足すなら 1728000000 だけ。この計画では足す所が無い）。
- 変異テストを回さない。手本を撮る場面から、変異の実行器を起こす場面を外す。
- AI を起こさない。お金 0。
- 盤面への書き込みは一時ファイルから `os.replace`（engine の `write_json`）。拒否（`Reject`）の回は盤面を書かず、その入れ物は捨てる。
- テストは `nice -n 19` で前景。プロセスを止めるときは pid と cwd を確かめる。`pkill -f` を使わない。
- 使い捨ての置き場は `${WORKS_DEV_HOME:-$HOME/.cache/works-dev}/board-goldens/` の下。`/private/tmp/claude-*` の下に置かない。
- commit の末尾に `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`。push・tag はしない。

## 並べ方

```
波 0:  写し直しの線の足し算（comment-ratio.sh・REVIEW.md・parallel-pr.py。済み。着手の時に 1 度だけ確かめる）
波 1:  T1 節の表 ─┬─ T2a 実物の盤面の写し ─┬─ T2b 手本の作り手           （3 つ並べてよい。ファイルが重ならない）
波 2:  T3 開く・作る・保存（T1・T2a の後）
波 3:  T4a accept と instance（T2b・T3 の後）─┬─ T9 accept.py の移し替え（T3 の後）   （2 つ並べてよい）
波 4:  T4b settle と機械の節（T4a の後）
波 5:  T5 run_engine（T4b の後）
波 6:  T6 答え・省く・止める・依頼・添え書き（T5 の後）
波 7:  T7 通しの再生（T6 の後。board.py を直しうる）
波 8:  T8 begin（T7 の後）
波 9:  T10 仕様の置き直しと README
```

- `board.py` を触るのは T1・T3・T4a・T4b・T5・T6・T7・T8 で、この順に直列。T9 は `board.py` を読むだけ。並べた物は各々の worktree で回し、審査の後に cherry-pick する（台帳 R6・R8）。

## Review Focus

1. `settle` の `na` の付け方と機械の節の順が engine の `advance` と同じ。通しの再生（T7）で、盤面を engine から写し直さずに周の終わりまで一致する。
2. `accept` が instance を `done` にし、`check_record` の「判定の後の人待ち」の検査が engine と同じ文で効く（T4a `test_awaiting_after_judge_rejected`）。
3. `run_engine` が `process.checks["p4.ci"].by == "engine"` を残し、宣言の中身が変われば走らせない（T5）。
4. 拒否（`Reject`）の回に盤面が 1 バイトも変わらない（T4a）。
5. 節の表が全部の節をちょうど 1 度ずつ持ち、`skippable` は optional の節だけ（T1）。
6. 表の absent が、条件で `na` の周も含めて毎周の添え書きに出る（T6）。
7. 写しが a1202d0 と 1 バイトも違わない（T3）。v1 の `check_*` の返りが全文で同じ（T9）。
8. 比べない欄の表（`NOT_REPRODUCED`）が名前と理由を持ち、試験の出力に毎回並ぶ（T4a・T7）。
9. 任せ先へ落とす時は、拒まれた入れ物を捨ててディスクから読み直す（T5 `test_reject_falls_back_from_disk`）。engine に同梱の語（`parallel-pr.py`）と `reply` の `fallback` も engine と同じ道（T5）。
10. 手本は `patch`・`finalize`・`init` の手を持ち、`init` で拒まれた Run を期待どおりの拒否として残し、30 MB に収まる（T2b）。

---

### Task 1: 節の表と誤りの型（並べてよい: T2a・T2b）

**Files:**
- Create: `works/.shared/core/board.py`（`NodeTable`・`NodeEntry`・`BoardGap`・`BoardMismatch` だけ）
- Create: `works/tests/boards/tables/`（悪い見本: `missing-node.json`・`duplicate-node.json`・`role-on-driver.json`・`builtin-on-role.json`・`engine-run-on-plain.json`・`absent-no-reason.json`・`bad-fallback.json`・`missing-fallback.json`・`parallel-pr-machine.json`・`skippable-not-optional.json`・`wrong-graph-sha.json`・`unknown-by.json`）
- Test: `works/tests/test_board_table.py`

**Interfaces:**
- `class BoardGap(Exception)`、`class BoardMismatch(BoardGap)`
- `@dataclass(frozen=True) class NodeEntry: by: str; run: str = "auto"; fallback: str = ""; skippable: bool = False; reason: str = ""; where: str = ""; comes_with: str = ""`
- `@dataclass(frozen=True) class NodeTable: line: str; graph_sha: str; nodes: Mapping[str, NodeEntry]`
  - `NodeTable.load(path: Path) -> NodeTable`（同じ鍵 2 度・形の誤りは `BoardGap`）
  - `NodeTable.everything(graph: dict, graph_sha: str) -> NodeTable`（driver は `builtin/auto`、`p0.local_checks`・`p4.ci` は `engine_run/fallback=machine`、`p0.parallel_pr` は `engine_run/fallback=role`、他は `role`。手本の再生用）
  - `NodeTable.check(graph: dict, graph_sha: str) -> list[str]`（仕様 4.2 の縛り 1〜5）
  - `NodeTable.absent() -> list[dict]`（`[{node, reason, comes_with}]`）・`NodeTable.sha() -> str`

- [ ] **Step 1: 失敗するテストを書く**

```python
def test_everything_covers_graph(self):        # 60 節、driver 17 が builtin、p0.local_checks・p4.ci・p0.parallel_pr が engine_run
def test_missing_node_named(self):             # 抜けた節の名前が文に
def test_duplicate_node_rejected_on_load(self):# 同じ鍵 2 度 → BoardGap
def test_kind_matches_graph(self):             # role-on-driver・builtin-on-role・engine-run-on-plain の 3 つがどれも誤り
def test_absent_needs_reason(self):            # 空・空白だけ → 誤り
def test_engine_run_fallback_values(self):     # fallback が無い・machine・role・absent 以外 → 誤り。p0.parallel_pr に machine → 誤り、role・absent → 通る
def test_skippable_only_optional(self):        # p2.plan_review に skippable → 誤り、p2.history に skippable → 通る
def test_graph_sha_mismatch(self):             # 両方の値が文に在る
def test_unknown_by(self):
def test_absent_list_and_sha(self):            # absent() が表の absent の全部、理由を 1 字替えると sha が変わる
```

- [ ] **Step 2: 赤を確かめる** — Run: `nice -n 19 sh works/tests/run.sh -k board_table` / Expected: FAIL（`board` が無い）
- [ ] **Step 3: 書く** — graph は写しの `review-loop.json` を読む（`run_by`・`engine_run`・`optional` だけを見る）。graph_sha は写しの engine の `sha(graph_text(path))`。
- [ ] **Step 4: 緑を確かめる** — Run: `nice -n 19 sh works/tests/run.sh` / Expected: `OK`
- [ ] **Step 5: Commit** — `git commit -m "feat(works): 盤面の層の節の表（graph の全部の節の持ち方を先に固める）"`

---

### Task 2a: 実物の盤面の写し（並べてよい: T1・T2b）

**Files:**
- Create: `works/tests/boards/real/wt-ci-skip/`・`works/tests/boards/real/wt-layer1/`（〔盤見本〕の同名の盤面から `state.json`・`record.json`・`out/`・`rounds/`・在れば `reads.jsonl`・`policy/`）
- Create: `works/tests/boards/foreign/<名>/state.json`（graph の違う実物 35 個と `sim/` 4 個の `state.json` だけ）
- Create: `works/tests/boards/README`（元のパスと graph_sha を 1 行ずつ）
- Test: `works/tests/test_board_fixtures_real.py`

- [ ] **Step 1: 失敗するテストを書く**

```python
def test_real_boards_on_same_graph(self):     # real/ の 2 個の state.graph_sha == "f9897bb07384"、state.works が無い
def test_real_boards_have_track_a_nodes(self):# 2 個の out/r1 に p2.fix_plan・p2.plan_review・p2.human_gate・p3.fix・p3.delta_owed2 が在る
def test_foreign_boards_differ(self):         # foreign/ の 39 個は全部 graph_sha が違う
def test_readme_lists_all(self):              # README の行が real/ と foreign/ の全部を名指す
```

- [ ] **Step 2: 赤を確かめる** — Run: `nice -n 19 sh works/tests/run.sh -k fixtures_real` / Expected: FAIL
- [ ] **Step 3: 写す** — `rsync` で要る物だけ。見本は後で書き換えない。
- [ ] **Step 4: 緑を確かめる** — Run: `nice -n 19 sh works/tests/run.sh` / Expected: `OK`
- [ ] **Step 5: Commit** — `git commit -m "test(works): graphloops の実物の盤面を写す（同じ graph の 2 個と、開かない試験用の 39 個）"`

---

### Task 2b: 手本の作り手（並べてよい: T1・T2a）

**Files:**
- Create: `works/dev/board-goldens/make.py`（PEP 723。a1202d0 を書き出し、台本を回し、撮った物を置く）
- Create: `works/dev/board-goldens/sitecustomize.py`（仕様 9.2 の 2 の包み方。`WORKS_GOLDEN_OUT` が無ければ何もしない）
- Create: `works/dev/board-goldens/README`（作り方の 1 行・撮る場面・撮らない場面と理由・正規化の規則）
- Create: `works/tests/boards/golden-a1202d0/`（`MANIFEST.json`・`blobs/<sha256>`・`steps/<場面>.json`）
- Test: `works/tests/test_board_goldens_fixture.py`

**Interfaces:**
- `make.py [--graphloops-rev a1202d0] [--out works/tests/boards/golden-a1202d0] [--work <置き場>] [場面 ...]`
  - 既定の場面（仕様 9.2 の 6）: `test_converges test_runaway test_awaiting test_rejections test_request_entry test_fix_plan_review test_human_gate test_policy_reaches_roles test_stop_midround test_stop_after_round test_gates_merge test_rejudge_path`
  - 場面は 1 つずつ呼ぶ（台本の `main()` を使わない）。Run は `Run.dir` で見分けて番号を振る。
  - 撮らない場面（仕様 9.2 の 7）は `MANIFEST.json` の `skipped_scenarios` に理由つき。
  - 終了コード 1 は「`init` が通った Run で手が 0」「包んだ関数が 1 度も呼ばれない場面」のときだけ（仕様 9.2 の 9）。
- `sitecustomize.py`: `sys.argv[0]` が `loop.py` で `WORKS_GOLDEN_OUT` が在るときだけ働く。書き出した graphloops の engine の module を先に import し、`engine.commands.Board` を `RecordingBoard` に替え、仕様 9.2 の 3 の関数（`cmd_init`・`cmd_patch`・`cmd_finalize` を含む）を module の属性で包む。`RecordingBoard.applicable()` の上書きで `na` を `{node, why}` として撮る。
- 手の行（`steps/<場面>.json.gz` の要素）: `{seq, run, kind, node?, args, raised?: {type, text}, memory?: {before: 差分, after: 差分}, na?: {node, why}, disk?: {before: 目録の差分, after: 目録の差分}, repo_before?: 目録の差分, engine_run?: {plan, runs}}`
  - `raised.text` は `Reject` ならその文、`die`（`SystemExit`）なら engine の `util.LAST_DIE`（`SystemExit` の文は `"2"` になるため）
  - `kind`: `init`・`accept`・`builtin`・`na`・`open_round`・`add`・`answer`・`skip`・`stop`・`patch`・`finalize`・`engine_run`
  - `memory` の差分は `[{path: [鍵…], op: "set" | "del", value?}]`。`before` は前の手の `after`（拒まれた手なら前の手の `before`）から、`after` はその手の `before` から。Run の最初の手だけ `memory.base`（丸ごと）を持つ。
  - 目録はパス → sha256。記憶と同じく Run の最初の手だけ丸ごと（`disk.base`・`repo.base`）、以後は前の目録からの差分 `{add: {パス: sha}, drop: [パス]}`（変わらなければ省く）。中身は `blobs/<sha256>.gz`。`repo` は作業ツリーと `.git` の `objects`・`refs`・`HEAD`・`index`。
  - パスの置き換え: `@BOARD@`・`@REPO@`・`@CORE@`・`@PY@`（`/var` と `/private/var` の両方の綴り）。
- `MANIFEST.json`: `{graphloops_rev, graph_sha, made_at, git_env, scenarios: {名: {runs: {番号: {steps, bytes, kinds: {kind: 数}, init_rejected: bool}}}}, skipped_scenarios: {名: 理由}, uncovered: [節の名前], total_bytes}`
  - `uncovered`: 線 A・B が使う機械の節と engine が走らせる節（`p1.worktree_before`・`p1.worktree_after`・`p2.human_gate`・`p3.lane_merge`・`p3.fix_delta`・`p3.fix_delta2`・`p3.delta_owed`・`p3.delta_owed2`・`p3.gates_cut`・`p4.scalars`・`p4.assemble`・`p4.record`・`converge`・`p0.local_checks`・`p4.ci`・`p0.parallel_pr`）のうち、撮れた手に 1 度も出ない物

- [ ] **Step 1: 失敗するテストを書く**

```python
def test_manifest_names_source(self):         # graphloops_rev == "a1202d0"、graph_sha == "f9897bb07384"、git_env が在る
def test_every_initialized_run_has_steps(self):  # init_rejected でない全部の run で steps > 1
def test_init_rejected_runs_recorded(self):   # policy-missing・stop0・gates の知らない値と綴り違いの run が、raised を持つ init の 1 手だけで在る
def test_skipped_scenarios_reasoned(self):    # test_delta_conditions・test_fix_counts_by_engine・test_lane_end_to_end が理由つきで在る
def test_memory_diffs_apply(self):            # 各 run で base に差分を順に当てると、builtin の手の before と after が違い、最後の after が撮った最後の盤面の記憶と同じ
def test_na_steps_are_light(self):            # kind=na の手は memory を持たず na: {node, why} だけ
def test_kinds_cover_round_turn(self):        # builtin に p4.record・converge、open_round が 1 つ以上
def test_kinds_cover_in_round_ask(self):      # p2.human_gate の builtin の手の after で pending_human.in_round が真、同じ run でそれに続く answer が 1 つ以上
def test_kinds_cover_patch_finalize(self):    # test_rejudge_path に patch、test_stop_after_round に finalize の手
def test_engine_run_split(self):              # engine_run の手が plan と runs（out の中身つき）を持ち、同じ run の直後に同じ節の accept の手が在る
def test_rejected_steps_present(self):        # test_rejections の accept に raised を持つ手が 1 つ以上
def test_multi_run_numbered(self):            # test_request_entry の run が 2 つ以上、run ごとに dir が違う
def test_blobs_referenced_exist(self):        # 目録の sha が全部 blobs/ に在り、解いた中身の sha256 が名前と一致
def test_no_absolute_paths(self):             # 解いた blobs に /var/folders・/private/var・/private/tmp・$HOME・撮った機械の Python のパスの生の綴りが無い
def test_uncovered_listed(self):              # uncovered が MANIFEST に在り（空でもよい）、試験の出力に並ぶ
def test_manifest_diffs_apply(self):          # 各 run で disk・repo の base に差分を順に当てると、最後の目録が撮った最後の盤面・リポジトリのファイルの一覧と sha に一致
def test_die_text_from_last_die(self):        # init の die で拒まれた run の raised.text が "2" でなく engine の文
def test_size_budget(self):                   # total_bytes（blobs と steps/*.json.gz）≤ 30 MB。超えたら場面ごとの bytes の内訳を文に出す
```

- [ ] **Step 2: 赤を確かめる** — Run: `nice -n 19 sh works/tests/run.sh -k goldens_fixture` / Expected: FAIL
- [ ] **Step 3: 書く・回す** — `make.py` は台本を同じプロセスで import し、場面の関数を 1 つずつ呼ぶ（〔盤見本〕`sim/gl-sim-driver.py` と同じ作り: 実物の claude を起こしたら印を書いて 97 で落ちる偽の `claude` を PATH の頭に置く）。子プロセスの `loop.py` に `PYTHONPATH=<board-goldens>` と `WORKS_GOLDEN_*` を渡す（台本の `Run.env` が `None` なら親の環境が継がれる。環境を組む呼び出しも `os.environ` を含む）。回したら `nice -n 19 uv run works/dev/board-goldens/make.py` の出力を commit する。大きさの見積りは目録を含めて 8〜20 MB（仕様 9.2 の 5）。
- [ ] **Step 4: 緑を確かめる** — Run: `nice -n 19 sh works/tests/run.sh` / Expected: `OK`。`git status` に書き出しの残りが無い。
- [ ] **Step 5: Commit** — `git commit -m "test(works): 盤面の手本（graphloops 0.21.0 の台本の手を engine の中で前後に撮る）"`

---

### Task 3: 開く・作る・保存（T1・T2a の後）

**Files:**
- Modify: `works/.shared/core/board.py`（`DiskBoard` の `__init__`・`create`・`open`・`scratch`・`edit`・`save`・`run_validator`・`work`・overrides、`rules_module`・`graph_expanded`）
- Test: `works/tests/test_board_open.py`・`works/tests/test_core_verbatim.py`

**Interfaces:**
- `BOARD_VERSION = 1`、`GRAPH_PATH`・`VALIDATOR_PATH`・`CORE_DIR`
- `class DiskBoard(engine.board.Board)`:
  - `__init__(self, d, *, state, record, table, overrides=None, validator_runner=None, allow_halted=False, scratch=False)`
  - `open(cls, d, *, table, repo=None, overrides=None, validator_runner=None, allow_halted=False)`（仕様 4.4 の順）
  - `create(cls, d, *, repo, table, inputs, request_text, max_rounds=None, stop_after_round=None, overrides=None, validator_runner=None)`（仕様 4.1 の 1〜5）
  - `scratch(cls, board, *, review_rev, record=None, loop_state=None)`
  - `edit(cls, d, **open_kw)`（context manager）
  - `save(self)`・`run_validator(self, target=None)`・`work(self, name) -> Path`
- `rules_module(graph=None)`・`graph_expanded(graph=None)`

- [ ] **Step 1: 失敗するテストを書く**

```python
def test_attrs_superset_of_engine(self):        # real/ の 2 個を一時の写しに（state.graph・validator を写しに、state.works を足して）
                                                #   engine の Board と DiskBoard で開く: DiskBoard の vars の鍵 ⊇ engine の鍵
def test_reads_match_engine_board(self):        # 同じ 2 個: round・rd・loop_state・record・全節×全周の output_of_round・node_state が同じ
def test_foreign_board_refused_by_graph(self):  # foreign/ の 39 個 → BoardMismatch、文に両方の graph_sha（board_version の理由でない）
def test_no_works_field_refused(self):          # real/ をそのまま（state.works 無し）→ BoardMismatch、文に board_version
def test_table_gap_refused_on_open(self):       # 節の抜けた表 → BoardGap
def test_create_like_engine_init(self):         # 使い捨ての git リポジトリで create: state の鍵 ⊇ engine の cmd_init の鍵、inputs に request・document・lang・cwd、
                                                #   inputs.rounds_dir と process.policy.copy が最終の置き場の下、state.works.core.commit == "a1202d0"、
                                                #   state.works.not_in_line == table.absent()
def test_create_rejects_bad_inputs(self):       # gates=x → Reject、置き場が残らない
def test_create_refuses_existing(self):         # 置き場が在れば BoardGap
def test_paths_rewritten_in_memory(self):       # state.graph・validator・inputs.scripts_dir・inputs.review_md を別のパスにした盤面 → 写しのパスで読む、ディスクは同じ
def test_copy_has_scalars_and_review_md(self):  # 写しの scripts/comment-ratio.sh と REVIEW.md が在り、inputs.scripts_dir・review_md の読み替え先がそれを指す（波 0 で済み）
def test_edit_discards_on_exception(self):
def test_board_conflict(self):
def test_halted_needs_allow(self):
def test_scratch_has_dir_and_validator(self):   # scratch(board, …): dir == board、state.validator == 写しの RR、save → BoardGap、GIT_CWD を変えない
def test_work_path(self):                       # round 2 で work("x.json") == dir/"r2"/"x.json"
def test_overrides_global_only(self):           # _final_gate_problems の差し替えは効き、state.works.overrides に理由。converge（BUILTINS の値）を渡すと BoardGap
def test_overrides_isolated(self):              # 別に開いた盤面の rules は元のまま
def test_validator_runner_used(self):           # validator_runner を渡した盤面の run_validator はそれを呼び、state.validator は写しの RR のまま
def test_rules_module_fresh(self):              # 2 度で別の module、_unproven と _lane_errors を持つ
def test_graph_expanded_has_lane_reply(self):   # $defs に lane_reply と gate_arm
# test_core_verbatim.py
def test_copy_is_verbatim(self):                # COPIED_FROM の 2 行目から（空行と # の行を除き ln.split()[0]）の各ファイルが git show a1202d0:<同じパス> と同じバイト。
                                                #   a1202d0 が引けなければ理由を出して skip
```

- [ ] **Step 2: 赤を確かめる** — Run: `nice -n 19 sh works/tests/run.sh -k "board_open or core_verbatim"` / Expected: FAIL
- [ ] **Step 3: 書く** — `__init__` は engine の `Board.__init__`（`dir`・`state`・`util.GIT_CWD`・`seen_rev`・`halted_at_read`・`record`・`graph`（`load_graph`）・`nodes`・`refuse_expression_conds`・`rules`）を同じ順で組む。`create` は engine の `cmd_init` の順（仕様 4.1）。`overrides` は RL の module の大域の名前を差し替え、`BUILTINS`・`CONDS`・`POST_CHECKS`・`ENGINE_RUNS` の値の関数と同じ物を渡されたら `BoardGap`。
- [ ] **Step 4: 緑を確かめる** — Run: `nice -n 19 sh works/tests/run.sh` / Expected: `OK`
- [ ] **Step 5: Commit** — `git commit -m "feat(works): DiskBoard（engine の盤面を継ぎ、版の違う盤面を開かない）"`

---

### Task 4a: `accept` と instance（T2b・T3 の後。並べてよい: T9）

**Files:**
- Modify: `works/.shared/core/board.py`（`accept`・instance の控えを出す内部の関数 `_emit(nid)`）
- Create: `works/tests/boardreplay.py`（手本を戻す・記憶から盤面を組む・正規化・比べる・`NOT_REPRODUCED`）
- Test: `works/tests/test_board_steps.py`（この Task では accept の手）

**Interfaces:**
- `DiskBoard.accept(self, nid: str, output: dict) -> str` — 仕様 1 の 5 の順（`halted` の拒否 → instance → 依存 → 型 → `pointers.resolve(output, n.get("pointers"), None)` → `post_check` → `apply_writes` → `check_record` → out → `state.outputs[nid] = {file, round, instance}` → instance を done → rd.done・done_ever → trace → save）。settle しない。
- `DiskBoard._emit(self, nid: str) -> dict` — 最小の instance `{id, node, run_by, status: "pending", emitted_at, out_path, skills?}`（仕様 4.1。`skills` は engine の `emit_instance` と同じく `applies_cond` を `b.cond()` で評価して `applies`・`applies_why` を置く）。
- `boardreplay.py`:
  - `restore(run_steps, seq, which, into) -> tuple[Path, Path]`（`manifest_at` の目録でディスクとリポジトリを戻し、`@BOARD@`・`@REPO@`・`@CORE@`・`@PY@` を実パスに）
  - `memory_at(run_steps: list, seq: int, which: "before" | "after") -> dict`（Run の頭の `memory.base` に差分を順に当て、その手の前か後の `{state, record}` を返す。`na` の手の「前」もこれで引く）
  - `manifest_at(run_steps, seq, which, kind: "disk" | "repo") -> dict`（目録も同じく）
  - `board_from_memory(mem: dict, board_dir, table) -> DiskBoard`（`memory_at` の返りから組む）
  - `normalize(obj) -> obj`、`NOT_REPRODUCED: dict[str, str]`（欄の名前 → 理由。仕様 9.3）
  - `compare(board: DiskBoard, step) -> list[str]`（記憶の `after` とディスクの `after` の目録の違いの文。`NOT_REPRODUCED` を除く）
  - `git_env() -> dict`

- [ ] **Step 1: 失敗するテストを書く**

```python
def test_accept_steps(self):                   # kind=accept の全部の手: 戻す → 記憶から組む（表=everything）→ accept(node, 手の返答) → compare が空
def test_accept_reject_leaves_board(self):     # raised を持つ手: accept が Reject、文が raised.text と同じ、ディスクの全ファイルの sha が前のまま
def test_awaiting_after_judge_rejected(self):  # 判定を accept した後、台帳に無い人待ちの素材を書く p3.fix → engine と同じ文で Reject（仕様 C1）
def test_pointer_integer_rejected(self):       # p2.fix_plan の plan[].unit_keys に整数 → Reject（engine の番号の文）
def test_instance_done_and_output_link(self):  # accept の後 rd.instances[nid].status == "done"、output_file、state.outputs[nid].instance == nid
def test_emit_skills_like_engine(self):         # 手本の accept の手の前の instance の skills（applies・applies_why）と、_emit が組む skills が同じ
def test_lens_not_applied_passes(self):        # security_surface_touched が偽の盤面で、/security-review を invoked: false・failed で返した p1.local_review を accept が通す
def test_accept_on_halted_rejected(self):      # halted の盤面で accept → Reject（engine の _refuse_halted の文）
def test_accept_absent_is_gap(self):           # 表で absent の節 → BoardGap
def test_accept_without_instance_is_gap(self): # 待っている instance が無い → BoardGap
def test_not_reproduced_listed(self):          # 試験の出力に NOT_REPRODUCED の名前と理由が並ぶ
```

- [ ] **Step 2: 赤を確かめる** — Run: `nice -n 19 sh works/tests/run.sh -k board_steps` / Expected: FAIL
- [ ] **Step 3: 書く** — engine の `accept_output` の中の、instance の描画・起動に関わる所（`read_from`・`agent_id`・`tree_before`・扇の被覆・段の昇格・`save_text_as`）は持たない。持たない物は `NOT_REPRODUCED` に名前と理由で載せる。
- [ ] **Step 4: 緑を確かめる** — Run: `nice -n 19 sh works/tests/run.sh` / Expected: `OK`
- [ ] **Step 5: Commit** — `git commit -m "feat(works): 盤面が engine と同じ控え（instance）を残して役の返答を受ける"`

---

### Task 4b: `settle` と機械の節（T4a の後）

**Files:**
- Modify: `works/.shared/core/board.py`（`Progress`・`settle`・`step_builtin`・`run_builtin`・`done`・`_settle_pass`（輪の 1 段））
- Modify: `works/tests/test_board_steps.py`（builtin・na・open_round の手と settle の単体）

**Interfaces:**
- `Progress = TypedDict(...)`（仕様 4.1）
- `DiskBoard.step_builtin(self, nid) -> dict` — engine の `run_driver_node`（settle しない）。
- `DiskBoard.run_builtin(self, nid) -> Progress` — 表で `explicit` の節だけ（他は `BoardGap`）: 条件に当たらなければ `na`、当たれば `step_builtin` → `settle`。
- `DiskBoard.settle(self, accept_tree_change=None) -> Progress` — 仕様 4.1 の 1〜5（添え書きの 4 は T6）。
- `DiskBoard.done(self, nid, output) -> Progress` — `accept` → `settle`。
- `DiskBoard._settle_pass(self) -> bool` — `advance` の輪の 1 段（進んだか）。
- `DiskBoard._settle_node(self, nid) -> str | None` — 節を 1 つだけ評価する（`na` にしたら理由を返す）。1 手ずつの試験が `na` の手に当てる。

- [ ] **Step 1: 失敗するテストを書く**

```python
def test_builtin_steps(self):                 # kind=builtin の全部の手: 記憶から組む → step_builtin → compare が空
                                              #   （worktree_snapshot・worktree_compare・human_gate・lane_merge・fix_delta・delta_owed・gates_cut・scalars・assemble・record_round・converge）
def test_open_round_steps(self):              # converge の手で next_round の物: step_builtin の後の round・新しい周の箱・loop・record が open_round の手の after と同じ（on_new_round）
def test_na_steps(self):                      # kind=na の手: memory_at(…, "before") から組んで _settle_node(node) → 返りの理由 == 手の why、rd.na[node] == why
def test_settle_entry_halted(self):           # halted の盤面で settle → 何もせず halted を返す
def test_settle_entry_pending_human(self):    # pending_human の間に別の節を done → p2.human_gate を走らせ直さない、pending_human が同じ
def test_settle_passes_accept_tree_change(self):  # 作業ツリーを変えた後の worktree_compare が accept_tree_change="理由" で通り、git_mismatches に accepted
def test_explicit_is_wall(self):              # p4.record を explicit にした表と auto の表で同じ盤面を settle → explicit 側は p4.record で止まり、run_builtin の後の
                                              #   converge 以降の na と結果が auto 側と同じ
def test_settle_stops_at_ask(self):           # asking に kinds・items、human_gate は done でない
def test_settle_stop_after_round(self):       # stop_after_round の周の converge の後 → halted.by == "stop_after_round"、round は増えない
def test_settle_clears_read_caches(self):     # rewind の後に同じ out のパスへ書いた出力を、同じ入れ物の settle が新しい中身で読む
```

- [ ] **Step 2: 赤を確かめる** — Run: `nice -n 19 sh works/tests/run.sh -k board_steps` / Expected: FAIL（足した試験）
- [ ] **Step 3: 書く** — `settle` は engine の `advance` の輪（graph の順・進む物が無くなるまで）を、役の節は `_emit` だけにし、`graph_changed`・`engine_changed`・`frozen_outputs_stale` を除いて書く（除いた物は `NOT_REPRODUCED`）。機械の節は `run_driver_node` をそのまま呼ぶ。explicit の節に当たったら、その段の輪で graph の順の後ろを評価しない。
- [ ] **Step 4: 緑を確かめる** — Run: `nice -n 19 sh works/tests/run.sh` / Expected: `OK`
- [ ] **Step 5: Commit** — `git commit -m "feat(works): 盤面が engine と同じ順で機械の節を回し、周を開く"`

---

### Task 5: `run_engine`（T4b の後）

**Files:**
- Modify: `works/.shared/core/board.py`（`run_engine`・既定の runner `tree_runner`）
- Modify: `works/tests/test_board_steps.py`（engine_run の手）
- Test: `works/tests/test_board_engine_run.py`

**Interfaces:**
- `DiskBoard.run_engine(self, nid, *, runner=None, plan=None) -> dict` — 仕様 4.3 の 1〜7（計画の 4 つの形・`reply` の `fallback`・拒まれたら読み直して任せ先へ、読み直した盤面を `self` に入れ直す・sha の照合で拒めば `{ok: false, relaunch: true}`・`Stopped` は盤面を書かずに投げ直す）。返り `{ok, node, fallback?, blocked?, runs?, why?, relaunch?}`。settle しない。
- `DiskBoard._accept_engine_reply(self, nid, reply) -> str` — `run_engine` の中の受け付け（engine_run の節の外からの `done` の拒否に当たらない口）。
- `tree_runner(steps: list[dict], cwd: Path, log_dir: Path) -> list[dict]` — works の `tree_run`（`.shared/core/tree_run.py`。止める猶予は `KILL_GRACE` 2 秒）で 1 段ずつ。返りの行は engine の `run_steps` と同じ鍵（`name`・`argv`・`exit`・`wall_s`・`out`・`err`・`tail`・起こせなければ `error`）。

- [ ] **Step 1: 失敗するテストを書く**

```python
def test_engine_run_steps(self):              # kind=engine_run と続く accept の手: 撮った plan と runs を差し込んで run_engine → compare が空（process.checks・素材）
def test_ci_by_engine_recorded(self):         # 宣言（.review-checks.json・緑の 1 段）の在る使い捨てのリポジトリで run_engine("p4.ci") → process.checks["p4.ci"] == {round, by: "engine", sha, runs}
def test_red_suite_found(self):               # 赤の段 → local_checks が found、count
def test_declaration_changed_refused(self):   # 撮った plan を差し込み、宣言の中身を書き換えてから run_engine → {ok: False, relaunch: True}、why が engine_run_refusal の文、
                                              #   何も走らず盤面が変わらず、節は待ちのまま
def test_reject_falls_back_from_disk(self):   # reply は通るが accept が拒む返答（偽の reply）→ 読み直した盤面で process.checks["p4.ci"].by == "role"・instance.engine_fallback、
                                              #   他の欄はディスクの前と同じ（拒まれた入れ物の by: engine は残らない）
def test_reply_fallback(self):                # p0.parallel_pr: 偽の gh と偽の GitHub の remote、交差の在る印字を返す runner → fallback、表の fallback=role なら ready に残る
def test_helper_runs_copied_script(self):     # p0.parallel_pr の helper の計画で、runner に渡る argv が [今の Python, <写し>/graphloops/scripts/parallel-pr.py, …]、そのファイルが在る（波 0）
def test_stopped_writes_nothing(self):        # runner が Stopped を投げる → 投げ直し、盤面が変わらない
def test_fallback_then_settle_same_board(self):  # 宣言の無いリポジトリで run_engine("p4.ci") の後、同じ入れ物の settle が BoardConflict にならず、ready に p4.ci が残る
def test_done_on_engine_run_refused(self):   # engine_fallback の無い engine_run の節（p4.ci）へのラインの done → BoardGap。任せ先に落ちた後の done は受ける
def test_parallel_pr_table_both_ways(self):  # 試験用の表で p0.parallel_pr を absent にすると skipped に表の理由、engine_run（fallback=role）にすると交差の fallback の後 ready に残る（役は作らない）
def test_no_declaration_falls_back(self):     # 宣言が無い → process.checks["p4.ci"].by == "role"、instance.engine_fallback、表の fallback=machine なら ready に残る
def test_fallback_absent_skips(self):         # 表の fallback=absent → skipped に表の理由
def test_tree_runner_shape(self):             # tree_runner の行の鍵 == engine の run_steps の行の鍵（起こせない argv では exit None と error）
def test_tree_runner_strips_uv_env(self):     # VIRTUAL_ENV・UV_RUN_RECURSION_DEPTH が子に渡らない（台帳 R23 と同じ）
```

- [ ] **Step 2: 赤を確かめる** — Run: `nice -n 19 sh works/tests/run.sh -k "board_engine_run or board_steps"` / Expected: FAIL
- [ ] **Step 3: 書く** — `plan`・`fallback`・`reply` は RL の `ENGINE_RUNS[graph の engine_run.builtin]` から引く（名前を works に持たない）。走らせる直前の突き合わせは engine の `engine_run_refusal` に最小の instance（`{launch: {steps, sha}}`）を渡して呼ぶ。ログは `runs/r<N>/<id>.a1/`。
- [ ] **Step 4: 緑を確かめる** — Run: `nice -n 19 sh works/tests/run.sh` / Expected: `OK`
- [ ] **Step 5: Commit** — `git commit -m "feat(works): engine が走らせる節を engine と同じ記録で走らせる（CI は engine が確かめた）"`

---

### Task 6: 答え・省く・止める・依頼・仕上げ・周の添え書き（T5 の後）

**Files:**
- Modify: `works/.shared/core/board.py`（`add_request`・`answer`・`skip`・`stop`・`finalize`・周の添え書き `_write_round_note(n)`）
- Modify: `works/tests/test_board_steps.py`（add・answer・skip・stop の手）
- Test: `works/tests/test_board_round_note.py`

**Interfaces:**
- `_answer_record(self, ans, note="") -> None`・`_skip_record(self, nid, reason) -> None`（settle しない記録の部分。engine の `cmd_answer`・`cmd_skip` と同じ範囲。1 手ずつの試験が当てる）
- `add_request(self, items, origin) -> dict`・`answer(self, ans, note="") -> Progress`（`_answer_record` → `settle`）・`skip(self, nid, reason) -> Progress`（`_skip_record` → `settle`）・`stop(self, reason, by) -> dict`・`finalize(self) -> None`（仕様 4.1。engine の `cmd_add`・`cmd_answer`・`cmd_skip`・`cmd_stop`・`validator.finalize` と同じ記録）
- `_write_round_note(self, n: int) -> Path` — `rounds/works/round-<n>.json`（仕様 4.5 の形）。`settle` が `p4.record` の済んだ輪で、`stop` が止めた周の記録を書いた後に呼ぶ。

- [ ] **Step 1: 失敗するテストを書く**

```python
def test_add_steps(self):                     # kind=add → compare が空
def test_answer_steps(self):                  # kind=answer: _answer_record(ans, note) → compare が空。周の途中の問い（human_gate）の answer の手を含む
def test_answer_in_round_continue(self):      # test_human_gate の手本: human_gate の ask の後 answer("continue", note) → human_items に node・answer・note、pending_human が消え、
                                              #   続く settle で p3.fix が ready
def test_answer_in_round_stop_halts(self):    # stop → halted.by == "answer"、以後の save は allow_halted 無しで Reject
def test_answer_without_question(self):       # pending_human が無い → Reject
def test_skip_steps(self):                    # kind=skip の手（在れば）: _skip_record(node, reason) → compare が空。無ければ MANIFEST の uncovered に skip が載る
def test_skip_optional_only(self):            # p2.history（optional）は skip できる、p2.plan_review は表で skippable にできないので BoardGap
def test_skip_needs_reason(self):
def test_stop_steps(self):                    # kind=stop → compare が空（state.stop・rd.stopped・process.halted・止めた周の記録）
def test_finalize_copies_skipped(self):       # na でない absent は process.skipped に在る
# test_board_round_note.py
def test_note_after_record(self):             # p4.record の後に rounds/works/round-1.json、not_in_line が表の absent の全部（na の周の節も in_round="na" で）
def test_note_checks(self):                   # checks に p4.ci の by（engine か role）
def test_note_after_stop(self):               # 止めた周にも添え書き
def test_validator_ignores_note_dir(self):    # 写しの RR に rounds/ を渡して、works/ の下を読み飛ばす（exit が添え書きの有無で変わらない）
```

- [ ] **Step 2: 赤を確かめる** — Run: `nice -n 19 sh works/tests/run.sh -k "board_steps or round_note"` / Expected: FAIL
- [ ] **Step 3: 書く** — `cmd_answer`・`cmd_stop`・`cmd_skip`・`cmd_add` は argparse の引数を取り盤面を自分で開くので呼べない。同じ手順を書き、engine の部品（`hook`・`open_next_round`・`stop_descendants`・`STOPPED_BY`・`ANSWER_ACTIONS`・`IN_ROUND_ACTIONS`）は import する。`skip` は graph の optional と表の skippable の両方を見る。
- [ ] **Step 4: 緑を確かめる** — Run: `nice -n 19 sh works/tests/run.sh` / Expected: `OK`
- [ ] **Step 5: Commit** — `git commit -m "feat(works): 盤面の答え・省く・止める・依頼と、このラインに無い節の周の添え書き"`

---

### Task 7: 通しの再生（T6 の後）

**Files:**
- Modify: `works/.shared/core/board.py`（ずれが出たときの直し）
- Modify: `works/tests/boardreplay.py`（`replay`）
- Test: `works/tests/test_board_replay.py`

**Interfaces:**
- `boardreplay.replay(scenario: str, run: int, into: Path) -> ReplayResult` — `Run` の頭（`init` の手の後）の盤面から、撮った手の順に `done`・`run_engine`（撮った `plan` と `runs`）・`answer`・`skip`・`stop`・`add_request`・`finalize` を当て（`patch` の手は撮った差分を記憶に当てる）、機械の節と `na` は `settle` に任せる。各手の前に対象リポジトリだけを撮った物に戻す。盤面を engine の側から写し直さない。`ReplayResult = {rounds: {N: {rd, loop, record}}, final: {state, record}}`。
- 表は `NodeTable.everything`。

- [ ] **Step 1: 失敗するテストを書く**

```python
def test_replay_converges(self):          # 各周の終わりの rd（done・na・skipped の節と理由）・loop・record と最後の status == "converged"
def test_replay_runaway(self):            # 上限の ask まで
def test_replay_awaiting(self):           # 周の終わりの問い → continue → 収束
def test_replay_request_entry(self):      # 全部の run: P1 の na の理由の文と、修正の後に入口が終わる周
def test_replay_fix_plan(self):           # 修正案 → 事前審査 → 関所 → 修正の順と human_items
def test_replay_human_gate(self):         # 周の途中の問い → continue の一言が human_items に残り、同じ周の修正へ
def test_replay_policy(self):             # 方針の文書の固定（process.policy）と、変化を通した後の amendments
def test_replay_stop(self):               # test_stop_midround・test_stop_after_round の全部の run: state.stop・halted
def test_replay_gates_merge(self):        # gates_deferred で止まる
def test_replay_rejudge(self):
def test_replay_patch_steps(self):        # test_rejudge_path・test_request_entry の patch の手: 撮った差分を当てた後の続き（p2.rejudge が出る等）が engine と同じ
def test_replay_finalize(self):           # test_stop_after_round の finalize の手の後の record（process.skipped・outcome など）が同じ
def test_replay_init_matches_create(self):  # 全部の init の手: 同じ入力の create の state・record が after と同じ（NOT_REPRODUCED を除く）、拒まれた init は create が同じ文で拒む
def test_replay_never_resyncs(self):      # replay の中で board のディスクへ手本の after を書く道が無い（boardreplay の書き込みは restore の頭の 1 度とリポジトリだけ）
```

- [ ] **Step 2: 赤を確かめる** — Run: `nice -n 19 sh works/tests/run.sh -k board_replay` / Expected: FAIL
- [ ] **Step 3: 書く・直す** — ずれが出たら `board.py` を直す（手本・試験は直さない）。`NOT_REPRODUCED` に足すのは、理由を書ける時だけ。
- [ ] **Step 4: 緑を確かめる** — Run: `nice -n 19 sh works/tests/run.sh` / Expected: `OK`
- [ ] **Step 5: Commit** — `git commit -m "test(works): 盤面の通しの再生（写し直さずに周の頭・締め・次の周が engine と同じ）"`

---

### Task 8: `begin` と `base_output`（T7 の後）

**Files:**
- Modify: `works/.shared/core/board.py`（`begin`・`base_output`）
- Create: `works/tests/boards/tables/entry-line.json`（試験用の表: p0.base は machine、p0.local_checks・p4.ci は engine_run（fallback machine）、p2.diagnose・p2.fix_plan・p2.plan_review・p3.fix・p3.delta_review・p3.delta_fix・p3.delta_review2・p3.delta_fix2 は role、p2.history は role（skippable）、driver は builtin、他は absent（理由つき））
- Test: `works/tests/test_board_begin.py`

**Interfaces:**
- `DiskBoard.begin(cls, d, *, repo, table, items, origin, base_rev, request_text, inputs=None, max_rounds=None, stop_after_round=None, overrides=None, validator_runner=None) -> tuple[DiskBoard, Progress]`
- `base_output(repo: Path, base_rev: str) -> dict`

- [ ] **Step 1: 失敗するテストを書く**

```python
def test_begin_ready_local_checks_then_judge(self):  # 宣言の在る使い捨てのリポジトリで begin → ready == ["p0.local_checks"]、run_engine → settle → ready == ["p2.diagnose"]
def test_begin_p1_na_like_engine(self):       # p1.local_review などの na の理由が「cond not_request_entry:」で始まる
def test_begin_absent_skipped_and_listed(self):  # absent の節が skipped か na、state.works.not_in_line が表の absent の全部
def test_begin_freezes_revision(self):        # inputs.review_rev == loop.head_revs["1"]、その木 == 作業ツリーの木、diff-r1.patch
def test_begin_records_request(self):         # request_findings に 1 バッチ、request_entry.origin
def test_begin_policy_fixed(self):            # 共通の git の置き場の graphloops/policy.md → process.policy.sha256・copy が盤面の policy/ の下
def test_begin_idempotent(self):              # 同じ items で 2 度 → 盤面 1 つ・依頼 1 バッチ。違う items → BoardGap
def test_begin_stop_after_round(self):
def test_base_output_shape(self):             # graph の p0.base の schema を通る、method == "4 依頼者の名指し"、touches_* 全部 True
def test_base_output_empty_rev_is_head(self):
def test_base_output_bad_rev(self):           # Reject（文に版の名前）
def test_begin_without_declaration(self):     # 宣言の無いリポジトリで begin → run_engine("p0.local_checks")（任せ先に落ちる）→ 同じ入れ物で done("p0.local_checks", 素材) → settle が通り ready == ["p2.diagnose"]
def test_begin_ready_with_parallel_pr(self):  # p0.parallel_pr を engine_run（fallback=role）にした表では begin の後の ready に p0.parallel_pr も在る
def test_single_round_runs_to_record(self):   # 手本 test_request_entry の最初の run の最初の手の前のリポジトリで begin(stop_after_round=1)
                                              #   → 表の役の節に同じ run の返答を手の順に done（各手の前にリポジトリを戻す）、p4.ci は撮った runs で run_engine
                                              #   → settle が p4.record・converge まで回り halted.by == "stop_after_round"、rounds/round-1.json と
                                              #   rounds/works/round-1.json、p4.record の exit が 0 か 1、process.checks["p4.ci"].by == "engine"
```

- [ ] **Step 2: 赤を確かめる** — Run: `nice -n 19 sh works/tests/run.sh -k board_begin` / Expected: FAIL
- [ ] **Step 3: 書く** — `begin` は `create` → `add_request` → `accept("p0.base", base_output(...))` → `settle`（仕様 5 節）。冪等の見分けは記録の最初の依頼のバッチの `findings` の sha256。
- [ ] **Step 4: 緑を確かめる** — Run: `nice -n 19 sh works/tests/run.sh` / Expected: `OK`
- [ ] **Step 5: Commit** — `git commit -m "feat(works): 盤面の入口 begin（線 A・B の start の共通。判定から入る run を engine と同じに開く）"`

---

### Task 9: `accept.py` の移し替え（T3 の後。並べてよい: T4a〜）

**Files:**
- Create: `works/dev/board-goldens/v1_accept_golden.py`（PEP 723）
- Create: `works/tests/boards/v1-accept-golden.json`
- Modify: `works/.shared/core/accept.py`（`_Board` を消し `DiskBoard.scratch(board, …)` に替える。他は変えない）
- Test: `works/tests/test_accept_v1_golden.py`

**Interfaces:**
- `accept.py` の公開の口（`check_request`・`check_judge`・`check_fix`・`check_delta`・`role_schema`・`snapshot_tree`・`touched_files`・`cut_delta`・定数）は名前・引数・返り値とも変えない。
- `v1-accept-golden.json`: `[{fn, input: {reply|items の名, base_rev, 前の手}, result: {ok, reason, open_units?}, files: [盤面に書いたファイルの名前]}]`（手順は `test_accept.py` の `AcceptCase` と同じ種・同じ順）

- [ ] **Step 1: 手本を撮る（移し替えの前）** — Run: `nice -n 19 uv run works/dev/board-goldens/v1_accept_golden.py --out works/tests/boards/v1-accept-golden.json`。台本と撮った物を先に commit: `git commit -m "test(works): v1 の受け付けの返りを移し替えの前に撮る"`
- [ ] **Step 2: 失敗するテストを書く**

```python
def test_v1_results_unchanged(self):          # 全部の入力で ok・reason の全文・open_units・書いたファイルの名前が同じ（check_delta の outputs を外しても同じことを含む）
def test_no_fake_board_left(self):            # accept.py に _Board の名前が無い
def test_check_request_writes_only_request(self):  # state.json を作らない
def test_scratch_board_dir_used(self):        # check_judge の後の count-cache.json が渡した盤面の置き場に在る（数え直しが b.dir に書く）
```

- [ ] **Step 3: 赤を確かめる** — Run: `nice -n 19 sh works/tests/run.sh -k accept_v1_golden` / Expected: `test_no_fake_board_left` が FAIL
- [ ] **Step 4: 書く** — 仕様 7 節の表のとおり。
- [ ] **Step 5: 緑を確かめる** — Run: `nice -n 19 sh works/tests/run.sh` / Expected: `OK`（`test_accept.py`・`test_blk_*.py` を含む全部）。`sh works/dev/check.sh` も緑。
- [ ] **Step 6: Commit** — `git commit -m "refactor(works): 受け付けの偽の盤面を DiskBoard.scratch に替える（返りは変えない）"`

---

### Task 10: 仕様の置き直しと README（全部の後）

**Files:**
- Create: `works/docs/specs/2026-09-26-board-layer-design.md`（`scratchpad/board-layer-spec-draft.md` を置き、実装で変わった所を書き戻す。手本の手の数と `uncovered` を 9.2 に。持ち主の答え（13 節）を書く）
- Modify: `works/README.md`（「盤面の層」の節: 何か・どこか・線 A・B・C が何を使うか・手本の撮り直し方の 1 行）

- [ ] **Step 1: 置く** — 出典の印のうち scratchpad を指す物は、残す物（下書き）と消す物を分ける。裁定 BL1〜BL29 の台帳への写しは、持ち主の会話の側に一覧で渡す（この計画は台帳を書かない）。
- [ ] **Step 2: 確かめる** — Run: `nice -n 19 sh works/tests/run.sh` / Expected: `OK`。README から仕様への相対リンクが開ける。
- [ ] **Step 3: Commit** — `git commit -m "docs(works): 盤面の層の設計を置き、README に使い方を足す"`
