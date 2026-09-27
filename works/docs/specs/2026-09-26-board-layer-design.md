# 盤面の層（works の 3 本の線の共通の土台）の設計（2026-09-26・下書き 4 版）

状態: **下書き 4 版**（審査 `scratchpad/board-layer-review.md` を「改訂 1」、再審査 `board-layer-rereview.md` を「改訂 2」、再審査 2 回目 `board-layer-rereview2.md` の P1〜P3・m8〜m12 を「改訂 3」で反映）。線 A・B・C の下書きの食い違いは 10 節の裁定 BL1〜BL29 で決めた。**持ち主に聞く物が 2 つ在る**（13 節）: ① 線 A の「軽量」が graph で optional でない節を省く件（仮の裁定: 案 1＝標準だけ）、② 並行 PR の検査の任せ先の役が他人の PR に申し送りを投稿するか（仮の裁定: この層は engine_run と任せ先の配管だけを出し、`p0.parallel_pr` の持ち方は答えの後に線 A・B が決める）。どちらの答えも、この層の Task 1〜10 には要らない。実装計画は `scratchpad/board-layer-plan-draft.md`。

**この文書で決めたこと（要約）**: 盤面は graphloops の engine の盤面と同じ形でディスクに置き、`DiskBoard` は写した engine の `Board` を継ぎ、engine と同じ控え（役ごとの instance を含む）を残す。ラインは「節の表」で graph の 60 節の全部を「役・機械の返答・engine が走らせる節・機械の節・このラインに無い」に振り、盤面は engine と同じ順で機械の節を回す。「このラインに無い」は毎周の記録の隣に必ず出る。写しは 1 バイトも変えない。

## 平易版（3 行）

- works の 3 本の作業（線 A・B・C）は、どれも「run の途中の状態を置く場所（盤面）」と「graphloops から写した規則をその盤面に当てる口」を要る。先に 1 つだけ作るのがこの「盤面の層」。
- 形は graphloops（このリポジトリの既存のプラグイン）の engine が実際に使う盤面そのものにし、engine の部品を継いで使う。テストの実行も engine と同じ手順で記録し、「CI は engine が確かめた」という印まで同じに残す。
- 正しさは、graphloops 自身の台本（偽の AI で回す試験）を回し、engine の中で 1 手ずつ記憶の中の状態を撮っておき、works の盤面に同じ手を当てて同じ結果になるかで確かめる。

## 0. 略記と出典

- **盤面**: run の間ずっと残る状態の置き場 `$ARTIFACTS_DIR/board/`（`$ARTIFACTS_DIR` は Archon が run ごとに用意するフォルダ）。
- **写し**: `works/.shared/core/` の下に graphloops から写した engine・規則・graph・検証器。写し元は graphloops 0.21.0 の commit **a1202d0**。写し直しは枝 `wip/works-core-021`（worktree `/Users/p03623/src/claude-plugins-work1-core`、先頭 1833773。`scripts/comment-ratio.sh`・根の `REVIEW.md`・`graphloops/scripts/parallel-pr.py` も a1202d0 から同じバイトで写し済み）。
- **RL**: 写しの規則 `graphloops/rules/review-loop.py`。**RR**: 写しの検証器 `scripts/review-record.py`。**graph**: 写しの `graphloops/graphs/review-loop.json`（60 節、うち機械の節 17、optional の節 10。graph_sha は **f9897bb07384**＝engine の `util.sha`（sha256 の先頭 12 桁））。
- **engine の語**（盤面の `state.json` の中の物。この文書で使う分だけ）:
  - **周の箱 rd**: `state.rounds[-1]`。節の状態を箱に分けて持つ——`done`（済んだ）・`na`（条件に当たらず走らせない。理由つき）・`skipped`（回す側が省いた。理由つき）・`stopped`（人が止めた）・`empty`。どの箱にも無い節は **pending**（待ち）。
  - **instance**: 役の節を「出した」控え。`rd["instances"][id] = {id, node, status, out_path, …}`。受けると `status: done`。RL は「今の周に走った節」をここから読む。
  - **機械の節**: graph で `run_by: driver` の節。中身は RL の `BUILTINS`（版を固める・差分を切る・周の記録を組む・収束を決める等）。
  - **engine が走らせる節（engine_run）**: graph で `engine_run` を持つ節（`p0.local_checks`・`p4.ci`・`p0.parallel_pr`）。engine が対象リポジトリの宣言 `.review-checks.json` の語を走らせ、RL の `ENGINE_RUNS[…].reply` が返答を組み、`process.checks[節] = {round, by: "engine", …}` を記録する。宣言が無ければ任せ先（AI）の節に落ち、`by: "role"` を記録する。
  - **受け付けの検査**: graph の節の `post_check`（RL の `POST_CHECKS`）。**記録への書き込み**: graph の節の `writes`（engine の `record.apply_writes`）。
- **DiskBoard**: この文書で作る、ディスクの盤面を開く works の入れ物（`works/.shared/core/board.py`）。
- **節の表**: ラインごとの 1 ファイル。graph の全部の節を、このラインでどう持つかに振る（4.2）。
- **線 A・B・C**: 持ち主の決定（台帳の最後の順）で並べて回す 3 本。A＝1 回の run を強くする、B＝周の輪、C＝変異の関門のライン。**v1**: いまの darkfactory（枝 `wip/archon-pack`）。
- 出典の印:
  - scratchpad = `/private/tmp/claude-1341252503/-Users-p03623-src-claude-plugins-work1/c495892b-6158-4a8d-ad53-ea7a3361cb23/scratchpad`
  - 〔A〕= `scratchpad/trackA-spec-draft.md`、〔B〕= `scratchpad/rounds-spec-draft.md`（3 版）、〔B計〕= `scratchpad/rounds-plan-draft.md`、〔C〕= `scratchpad/trackC-spec-draft.md`、〔審〕= `scratchpad/board-layer-review.md`、〔再審〕= `scratchpad/board-layer-rereview.md`、〔再審2〕= `scratchpad/board-layer-rereview2.md`（記号で指す）
  - 〔台帳〕= `.superpowers/sdd/2026-09-26-darkfactory-v1/progress.md`（Ruling R1〜R30 と Owner decision）
  - 〔GL〕= 写しの中のファイル（`works/.shared/core/graphloops/<パス>`。a1202d0 と同じバイト）。〔SIM〕= `git show a1202d0:graphloops/tests/simulate_review.py`（写しには無い）
  - 〔盤見本〕= `scratchpad/board-fixtures/`（実物の盤面 37 個と `sim/`。`MANIFEST.md`）
  - 〔写枝〕= 写し直しの枝 `wip/works-core-021`

## 1. 前提（調べた事実）

1. **写しの規則は engine の盤面の口に広く頼る**。RL が盤面 `b` から読む物: `b.round`（99 か所）・`b.record`（68）・`b.loop_state`（63）・`b.state`（28）・`b.output_of_round`（20）・`b.rd`（15。周の箱と `rd["instances"]`）・`b.nodes`（13）・`b.dir`（13）・`b.cond`（10）・`b.latest_output`・`b.node_state`・`b.graph`・`b.porcelain`・`b.run_validator`・`b.rewind`・`b.outputs`・`b.is_runner`。
2. **RL は instance の控えを読んで判断する**〔審 C1〕: `check_record` の「今の周に走った節」と「判定が済んだ後か」（RL `check_record`）、`add` の描き直しと `_diagnose_started`、`p1.local_review` の skills。instance が無いと「判定の後の工程が台帳に無い人待ちを新しく立てたら拒む」検査が黙って効かない。
3. **今の偽の盤面は継ぎ足しで持たせている**。v1 の `accept.py` の `_Board` は周 1・節は全部 pending の入れ物で、〔写枝〕が `cond`・`nodes`・`is_runner` を足した。
4. **engine の盤面の意味で、真似るとずれやすい所**〔GL: engine/board.py〕:
   - `output_of_round(nid, rnd)` は `state.outputs[nid]`（節ごとに最新の 1 件）の周が `rnd` のときだけ返す。
   - `node_state` は周の箱で決まり、`once` の節は `done_ever` で済みになる。
   - 条件（`cond`）は宣言した欄だけが見える入れ物（`CondView`）で呼ぶ。
   - `save()` は読んだ時の版（`state.rev`）と突き合わせ、先に進められていたら書かずに落とす（`BoardConflict`）。`halted` の run には書かない。
5. **engine が役の返答を受ける順**〔GL: engine/commands.py `accept_output`・`pending_instance`〕: 止めた run（`halted`）なら拒む → instance が待っているか → 依存 → 型 → 番号の読み替え（`pointers.resolve`）→ `post_check` → `apply_writes` → `check_record` → `out/r<N>/<id>.json` → `state.outputs[nid] = {file, round, instance}` → instance を `done`（`done_at`・`output_file`）→ 周の箱の `done`・`done_ever` → `save()`。`done` は `advance` を呼ばない。
6. **engine の `next`**〔GL: commands.py `cmd_next`〕: `halted` なら何もしない。終わった状態で待ちが無ければ何もしない。`pending_human` が立っていれば進めない。どれでもなければ `accept_tree_change` を盤面に渡して `advance`（graph の順に、依存が済んだ節の条件を見て `na`、機械の節はその場で走らせ、`ask` なら `pending_human`、`next_round` なら周を開く）→ 最後に 1 度だけ `save()`。
7. **engine が走らせる節**〔GL: advance.py `plan_engine_run`・`helper_argv`、commands.py `launch_engine_run`・`engine_run_refusal`・`_engine_fallback`、RL `checks_*`・`parallel_pr_*`〕:
   - 出す時（`next`）に `plan` で語を固める。`plan` の返りは 4 つの形: `steps`（対象の宣言の語）・`helper`（engine に同梱の語。今は `parallel-pr.py` だけ。`[engine の Python, <engine の置き場>/scripts/<名前>, 引数…]` で走らせ、宣言と突き合わせない）・`blocked`（走らせずに返答を組む）・`fallback`（任せ先（AI）の節として出す）。
   - launch の時に、`engine_run_refusal`（宣言の sha の照合。拒めば `ok: false` と「relaunch で計画し直せ」を返し、節は待ちのまま）→ `run_steps`（別のプロセスグループ・期限なし）→ `reply` → `accept_output`。`reply` が `fallback` を返すか受け付けが拒めば、**盤面を読み直してから**任せ先の節として出し直す（`_engine_fallback`。拒まれた入れ物は保存しない）。
   - 宣言が無ければ `checks_fallback` が `by: "role"` を記録する。`parallel_pr_reply` は、並行 PR と交差した時に `fallback` を返す。`parallel_pr_plan` は、remote が GitHub でない・`gh` が無い時に `fallback` を返す。
   - `p0.parallel_pr` の任せ先の役（graph の `run_by: writer`・`delegate`）は、指示書 `prompts/review-loop/p0.parallel_pr.md` の 6 段の全部をする。6 段目は「担当 PR に申し送り、本ループのスコープから外す」で、`gh` で**他人の PR にコメントを投稿する**（外への書き込み。graph の note は gates プラグインの門番が掛かると書く）。返答の型は `conflicts[].handed_over`。同梱の `parallel-pr.py` 自身は読むだけ〔再審2 P1〕。
   - engine の `cmd_done` は、任せ先に落ちる前の engine_run の節への外からの `done` を拒む（結果は engine が組む）〔再審2 m10〕。
8. **CI の緑を engine が確かめたか**: RL の `converge` は、検証器が阻害なし・CI clean でも、`process.checks["p4.ci"]` が今の周の `by: "engine"` でなければ `ask ci_unverified` を返す〔GL: RL `_ci_by_engine`・`_converge`〕。
9. **省いた節の記録**: engine の `finalize` が周の箱の `skipped` を `process.skipped` に写す。ただし条件に当たらない節は `na` になり `skipped` に載らない〔審 I5〕。
10. **graph で省ける節は optional の 10 個だけ**（`p0.purpose_review`・`p0.prior_decisions`・`p1.procedure_trace`・`p1.gate_efficacy`・`p1.test_double_fidelity`・`p2.history`・`r1.comment_candidates`・`stop.premise_check`・`p2.rejudge`・`p2.rejudge_third`）。engine の `skip` は optional でない節を拒む。a1202d0 の graph は段（thickness）を持たない。
11. **検証器の置き場から引く物**: `validator_module(b)` が `state.validator` を import して表を引き、RL の `on_init` が `inputs.scripts_dir`（検証器の親。`p4.scalars` が `comment-ratio.sh` を探す）と `inputs.review_md`（親の親の `REVIEW.md`）を組む〔審 I4〕。写しは `scripts/comment-ratio.sh`・`REVIEW.md`（3a89a95）と、engine に同梱の語 `graphloops/scripts/parallel-pr.py`（1833773）を持った。
12. **レンズの当て方の控え**〔再審 N1〕: engine は役の節を出す時に、条件つきのレンズ（graph の `skills[].applies_cond`）を評価し、`inst.skills[].applies`・`applies_why` に置く〔GL: advance.py `emit_instance`〕。RL の `local_review_covers_lenses` は `inst.skills` を読み、無ければ graph の生の宣言に倒して「当てる」側に読む。a1202d0 で当たるのは `p1.local_review` の `/security-review`（`applies_cond: security_surface_touched`）。
13. **方針の文書**: RL の `on_init` が `policy_input.resolve` で方針の文書を固め、写しを盤面の `policy/<sha256>.md` に**絶対パスで**記録する。`inputs.rounds_dir` も絶対パス〔審 I2〕。
14. **盤面の見本**〔盤見本〕: `sim/` の 4 個は fbd40e3（graph_sha 8676692bbcb2）。実物 37 個のうち graph が a1202d0 と同じ（f9897bb07384）物は `claude-plugins__wt-ci-skip__20260926-103155` と `claude-plugins__wt-layer1__20260926-103145` の 2 個（判定から入る run・修正案・事前審査・関所の答え・2 往復の手直し・`--stop-after-round 2` を通った。engine は 0.21.0 の途中の 696a49d）。どれも `state.works` を持たない。
15. **graphloops の台本**〔SIM〕: 偽の AI の返答を `loop.py` に子プロセスで渡して回す。台本のリポジトリは既定で `.review-checks.json`（緑の 1 段）を置くので、`p0.local_checks`・`p4.ci` は毎周 engine が走らせる。`test_delta_conditions` と `test_fix_counts_by_engine` は `loop.py` を通らず、偽の盤面で規則を直に呼ぶ。`loop.py patch`（盤面の欄を手で書く）・`loop.py finalize` を使う Run がある（`test_rejudge_path`・`test_request_entry` の 4 本・`test_stop_after_round`）。`init` で拒まれて盤面を作らない Run がある（`test_policy_reaches_roles` の policy-missing・`test_stop_after_round` の stop0・`test_gates_merge` の知らない値と綴り違い）。周の途中の問い（`p2.human_gate` の ask → 答え）を通るのは `test_human_gate` と `test_policy_reaches_roles`。1 つの場面に `Run` が複数在る物がある（`test_request_entry` 5・`test_stop_midround` 5・`test_gates_merge` 5・`test_stop_after_round` 4）。

## 2. 狙いと範囲

- 狙い: A・B・C が盤面を後から直さずに済む土台を、1 回で作る。review-graph より黙って下がる所を作らない。
- 入れる物: 盤面の置き方（3 節）・`DiskBoard`・節の表・誤りの型（4 節）・`begin()`（5 節）・v1 の `accept.py` の移し替え（7 節）・手本とそれに当てる試験（9 節）。
- 入れない物（持ち主は 6 節の表）: 周の輪の段の決め方・関所の置き方・冪等の決まり（B）／止め札のファイルと境の節・Claude の包み・読んだ証拠・ブロック（A）／収束を止めない宣言 `not_in_line` の意味（B。土台は口だけ。BL5）／変異の関門の記録（C）。

## 3. 盤面の置き方

```
$ARTIFACTS_DIR/board/
  state.json          engine の形（loop_name・run_id・graph・graph_sha・status・round・rounds・max_rounds・inputs・validator・
                      outputs・done_ever・loop・rev）＋ works の欄:
                      works: {board_version, line, table_sha, core: {commit, path}, not_in_line: [...], overrides: [...]}
  record.json         記録（RL の init_record の形）
  trace.jsonl         engine と works の出来事。works も board.trace(op, …) で同じ行の形で書く
  out/r<N>/<節>.json  節の出力（engine と同じ名前: safe_name(instance の id)）
  rounds/round-<N>.json   周の記録（RL の record_round が書き、RR がディレクトリごと読む）
  rounds/works/round-<N>.json   works の周の添え書き（このラインに無い節・engine が走らせた節の結果。4.5）
                      ——RR は rounds/ の下のディレクトリを読み飛ばす
  runs/r<N>/<id>.a<k>/    engine が走らせた語の標準出力・標準エラー（engine と同じ置き場）
  policy/             方針の文書の写し（RL の on_init・関所が書く）
  lanes/              並行の線の置き場（RL の gates_cut が作る）
  diff-r<N>.patch・changed-r<N>.txt・diff-r<N>-after-fix.patch・changed-r<N>-after-fix.txt・
  fix-delta-r<N>.patch・fix-delta2-r<N>.patch   RL の機械の節が書く
  count-cache.json・count-budget.json   RL の数え直しが書く
  reads.jsonl         役が Read したファイル（A の包みのフックが書く。RL の hook_evidence が b.dir から読む）
  r<N>/               works が書く周の作業ファイル（board.work(名) が返す置き場）
  --- 土台の外の持ち物（名前だけ予約する）---
  STOP・launches.jsonl・report.md・next-request.json（A）／ finished（B）／ mutation/（C。DiskBoard は触らない）
  --- v1 の受け付けだけが書く（移し替えで動かさない。BL8）---
  request.json・judge-snapshot.json・judgment.json・fix.diff・delta-snapshot.json・delta-review.json・tests.log
```

- engine の関数が書く物は engine が決めた置き場のまま（写しを変えないため。BL2）。works が新しく書く作業ファイルは `r<N>/` に置く。
- `state.json` の中の pack のパス（`graph`・`validator`・`inputs.scripts_dir`・`inputs.review_md`）は、開くときにその時の pack の写しのパスで記憶の中だけ読み替える（Archon は run ごとに pack を写すので、パスは変わりうる。4.4）。

## 4. 口

### 4.1 `DiskBoard`（`works/.shared/core/board.py`）

- 写した engine の `Board` を継ぐ。engine の `Board` の属性と関数（`dir`・`state`・`record`・`graph`・`nodes`・`rules`・`round`・`rd`・`loop_state`・`node_state`・`deps_ok`・`deps_met`・`applicable`・`cond`・`output_of_round`・`latest_output`・`outputs`・`ctx`・`ref`・`porcelain`・`validator_tables`・`rewind`・`is_runner`・`trace`）はそのまま使う。
- **上書きする関数の一覧**（これ以外は上書きしない）:
  - `__init__`（4.4 の読み替えと、渡された dict から組む道）
  - `save`（`scratch` の入れ物なら `BoardGap`。他は engine の `save` を呼ぶ）
  - `run_validator`（`validator_runner` を渡した盤面だけ、それを呼ぶ。渡さなければ engine と同じ。BL5）
- 開き方と作り方:

```python
DiskBoard.create(dir, *, repo, table, inputs, request_text, max_rounds=None, stop_after_round=None,
                 overrides=None, validator_runner=None) -> DiskBoard
DiskBoard.open(dir, *, table, repo=None, overrides=None, validator_runner=None, allow_halted=False) -> DiskBoard
DiskBoard.scratch(board, *, review_rev, record=None, loop_state=None) -> DiskBoard   # v1 の受け付けだけが使う。保存できない
DiskBoard.edit(dir, **open_kw)      # context manager。抜けるときに save、例外なら書かない
```

  - `create`: engine の `cmd_init` と同じ順と入口の検査〔審 I2・M3〕:
    1. RL の `check_inputs(inputs)`・engine の `choice_input_errors(graph, inputs)`・パスの入力（`path_inputs`）の絶対化。engine の `required_inputs_missing` は graph のプロンプトの穴から要る入力を導く物で、写しはプロンプトを持たない（works の役は Archon の指示書で起きる）ので呼ばない。
    2. `inputs` に engine と同じ既定を足す: `request`（`request_text`）・`document`（None）・`lang`（engine の既定の文）・`cwd`（`repo` の実体のパス）。
    3. 最終の置き場を `mkdir(exist_ok=False)` で作り、`state.json`・`record.json`（RL の `init_record`）・`trace.jsonl` の init の行を書く。
    4. 盤面を開いて RL の `on_init` を呼び、`save`。ここまでのどこかで例外なら置き場を `rmtree` して投げ直す（engine と同じ「空の盤面を残さない」）。`inputs.rounds_dir` と `process.policy.copy` は最終の置き場の下を指す。
    5. `state.validator` は写しの RR。`state.works` に `board_version`・`line`・`table_sha`・`core`（`COPIED_FROM` の先頭の commit と写しのパス。engine の `engine_changed` を持たない代わり〔審 M8〕）・`not_in_line`（表の absent の全部。4.5）を書く。
  - `open`: 開いた時に `util.GIT_CWD` を `inputs.cwd`（`repo` を渡せばそれ）にする（engine の `Board` と同じ）。`state.works.core` を今の写しで書き直す。
  - `allow_halted=True` は、止めた run の盤面に報告や仕上げを書く呼び出しだけが渡す（engine の `allow_halted` と同じ意味）。
  - `scratch(board, …)`: v1 の偽の盤面の代わり（7 節）。周 1・空の周の箱の engine の形を記憶の中だけに組む。`dir` は渡された盤面の置き場（RL の count-cache・hook_evidence が読み書きする）、`state.validator` は写しの RR〔審 I9〕。`save()` は `BoardGap`。`GIT_CWD` は触らない（v1 は `_in_repo` で向ける）。
- ラインが盤面を進める口（右は engine のどのコマンドと同じか）:

```python
b.add_request(items: list, origin: str) -> dict            # loop.py add（RL の add）
b.accept(nid: str, output: dict) -> str                     # accept_output と同じ範囲（settle しない）
b.done(nid: str, output: dict) -> Progress                  # accept → settle（loop.py done → next）
b.run_engine(nid: str, *, runner=None, plan=None) -> dict   # launch の engine_run（4.3）→ 受け付けまで（settle しない）
b.step_builtin(nid: str) -> dict                            # 機械の節を 1 つ（run_driver_node。settle しない）
b.run_builtin(nid: str) -> Progress                         # 表で explicit の機械の節: step_builtin → settle
b.settle(accept_tree_change: str | None = None) -> Progress # loop.py next の advance から、役の節の控えを出すだけにした物
b.answer(ans: str, note: str = "") -> Progress              # loop.py answer → next
b.skip(nid: str, reason: str) -> Progress                   # loop.py skip → next（graph の optional の節だけ）
b.stop(reason: str, by: str) -> dict                        # loop.py stop の盤面の部分（子を止めるのは含まない）
b.finalize() -> None                                        # loop.py finalize の記録の部分（engine の validator.finalize）
b.work(name: str) -> pathlib.Path                           # r<N>/<name>（ディレクトリを作る）
```

  - `Progress` は `{"round": int, "ready": [節], "asking": {...} | None, "halted": {...} | None, "notes": [str]}`。`ready` は依存が済んで待っている、表で `role`・`machine`・`engine_run` の節（ラインが次に作る物）。`asking` は `state.pending_human`。
  - `done`・`run_builtin`・`answer`・`skip` は最後に `settle()` を呼んで、その `Progress` を返す。settle しない記録の部分は内部の口 `_answer_record(ans, note)`・`_skip_record(nid, reason)`（engine の `cmd_answer`・`cmd_skip` と同じ範囲。`cmd_answer` は周の終わりの答えで `open_next_round` を含み、`advance` は含まない）で、1 手ずつの試験が当てる〔再審2 m9〕。
  - **instance の控え**〔審 C1〕: `settle` が節を `ready` に出すとき、engine と同じ id（扇でない節は節の名前）で最小の instance `{id, node, run_by, status: "pending", emitted_at, out_path, skills?}` を `rd["instances"]` に置く（`out_path` は `out/r<N>/<safe_name(id)>.json`。受けるまで在らない＝RL の `_started` は偽）。`skills` は engine の `emit_instance` と同じく、graph の節の `skills` を写し、`applies_cond` を持つ要素だけ `b.cond()` で評価して `applies`・`applies_why` を置く〔再審 N1〕。プロンプトの描画・起動の欄は持たない。`accept` は engine と同じくその instance を `{status: "done", done_at, output_file}` にし、`state.outputs[nid]["instance"]` を書く。
  - `accept` の順は 1 の 5 と同じ（頭で `halted` の run を拒む〔再審 m7〕）。**ラインの `accept`・`done` は、`engine_fallback` を持たない engine_run の節を `BoardGap` で拒む**（engine の `cmd_done` と同じ。`run_engine` の中の受け付けは内部の口 `_accept_engine_reply` を通るので当たらない〔再審2 m10〕）。番号の読み替えは engine と同じく `pointers.resolve(output, n.get("pointers"), None)` を呼ぶ〔審 I1〕: 役が名前で書けばそのまま通り、整数で書けば「一覧を固めていない instance への番号」として engine の文で拒まれる（graph の型は `expand_refs` で番号も通すので、ここで止める）。
  - 拒み方は 2 つ:
    - 役の返答の中身が悪い（型・番号・`post_check`・`check_record`）→ `Reject`（engine の `AnswerReject` と同じ文）。盤面は書かない。**拒んだ後のその入れ物は捨てる**（`base_valid`・`r2_design` の `post_check` は記録を書くので、記憶が汚れている。`edit` を抜けて開き直す〔審 M11〕）。
    - ラインの配線が悪い（表で受けられない種類の節・待っている instance が無い・依存が済んでいない）→ `BoardGap`（内部の誤り。スクリプトは終了コード 2）。
  - 同じ周に同じ節を受け直すときは、先に継いだ `rewind([nid], by)` で待ちに戻す（engine と同じ。機械の節は戻せない）。
- `settle(accept_tree_change=None)` のすること〔審 I3・I8・M2〕:
  1. 入口の止め方（engine の `cmd_next` と同じ）: `halted` なら何もせず返す。終わった状態で待ちが無ければ返す。`pending_human` が立っていれば進めずに返す。
  2. 読んだ物の控え（`_out_cache`・`_porcelain`・`_vtables`）を消す（同じ入れ物で受けた直後に読むため）。`accept_tree_change` を盤面の属性に置く（RL の `worktree_compare` が読む）。
  3. engine の `advance` の輪を、graph の節の順に、進む物が無くなるまで回す。待ちで依存が済んだ節について:
     - 条件に当たらなければ `na`（engine の `applicable` の理由の文）。
     - 条件に当たれば表で振り分ける: `absent` → 周の箱の `skipped` に表の理由（`done_ever` も engine の `skip` と同じく書く）／`builtin`（既定 `auto`）→ その場で engine の `run_driver_node`（`ask` なら `pending_human` で止まる、`next_round` なら周を開く、`stop_after_round` の周なら `halted` で止まる）／`builtin`（`explicit`）→ 待ちのまま `ready` に出し、**graph の順でその後ろの節は、この輪では評価しない**（壁。機械の節の結果を見る前に後ろの条件を評価しない〔審 I8〕）／`role`・`machine`・`engine_run` → instance を出して `ready`。
  4. 周の記録（`p4.record`）が済んだ輪では、works の周の添え書き（4.5）を書く。
  5. 止まったら理由を `notes` に入れ、最後に 1 度だけ `save()`。
- 盤面なしで写しを読む口（線 C と受け付けの型の組み立て用）:

```python
rules_module(graph: Path | None = None)              # 写しの RL を読み込んだ module（毎回新しく読む。engine の load_rules）
graph_expanded(graph: Path | None = None) -> dict    # $ref を開いた graph（engine の load_graph）
```

### 4.2 節の表（ラインごとの `<ライン>/nodes.json`）

```json
{"line": "darkfactory", "graph_sha": "f9897bb07384",
 "nodes": {
   "p0.base":            {"by": "machine", "where": "start（begin の base_output）"},
   "p0.local_checks":    {"by": "engine_run", "fallback": "machine", "where": "start"},
   "p1.worktree_before": {"by": "builtin"},
   "p2.diagnose":        {"by": "role", "where": "blk-judge"},
   "p2.history":         {"by": "role", "where": "blk-judge", "skippable": true},
   "p4.ci":              {"by": "engine_run", "fallback": "machine", "where": "blk-tests"},
   "p4.record":          {"by": "builtin", "run": "explicit"},
   "r1.minimality":      {"by": "absent", "reason": "R1〜R4 はこのラインに無い", "comes_with": "R 系のブロック（未定）"}
 }}
```

- `by` は 5 つ:
  - `role`: ラインの AI の役が返す。
  - `machine`: ラインの script が組んだ返答を `done` で渡す。
  - `engine_run`: graph で `engine_run` を持つ節だけ。ラインが `run_engine` で走らせる（4.3）。`fallback` は、計画か返答が任せ先に落ちたときの持ち方（`machine`＝ラインの script が組んだ結果を `done` で渡す、`role`＝ラインの AI の役が engine の任せ先の仕事をして `done` で渡す、`absent`＝このラインに無い）。`p0.parallel_pr` の任せ先の仕事は「交差した hunk を読んで担当の PR に申し送る」判断なので、`fallback` は `role` か `absent`（`machine` は不可）。
  - `builtin`: graph で `run_by: driver` の節だけ。`run` は `auto`（既定）か `explicit`。
  - `absent`: このラインに無い。`reason` 必須、`comes_with` は入る予定の線かブロック。
- `skippable: true`: ラインが `skip(nid, 理由)` で省いてよい節。**graph で optional の節にだけ付けられる**〔審 I6〕。
- 縛り（盤面を開く時と単体テストで見る。どれも `BoardGap`）:
  1. graph の全部の節が表にちょうど 1 度ずつ在る。
  2. 表の `graph_sha` が写しの graph と同じ。
  3. `builtin` は driver の節だけ、`engine_run` は graph で `engine_run` を持つ節だけ、`role`・`machine` はそのどちらでもない節だけ。
  4. `absent` の `reason` が空でない。`engine_run` の `fallback` は必須で `machine`・`role`・`absent` のどれか（`p0.parallel_pr` は `role` か `absent`）。
  5. `skippable` は graph で optional の節だけ。
- 表の持ち主はラインの線（darkfactory は A、darkfactory-rounds は B）。土台は形と縛りだけを持つ。

### 4.3 engine が走らせる節 `run_engine`〔審 C2・再審 N2・N3・m2・m5〕

```python
b.run_engine(nid, *, runner=None, plan=None) -> dict   # 返り {ok, node, fallback?, blocked?, runs?, why?, relaunch?}
```

- 順は engine の「出す時の計画」と「launch」を 1 つの呼び出しにつないだ物:
  1. `plan` を渡されなければ、RL の `ENGINE_RUNS[builtin].plan(b, nid)`（渡された `plan` は試験が差し込む撮った計画）。
  2. `fallback` → 7 へ。
  3. `blocked` → 走らせずに 5 へ（`launch = {blocked}`）。
  4. `steps` → engine の `engine_run_refusal`（対象のルートの宣言の sha の照合）を、計画から組んだ最小の instance（`{launch: {steps, sha}}`）に当てる。拒めば engine と同じく `{ok: false, why, relaunch: true}` を返し、盤面は書かず、節は待ちのまま（ラインは `run_engine` を呼び直す＝計画し直す）。通れば `runner(steps, cwd, log_dir)` で走らせる。
     `helper` → engine の `helper_argv(名前, 引数)` で語を組む（`[今の Python, <写しの graphloops>/scripts/<名前>, …]`。engine と同じく宣言と突き合わせない）。走らせる物は写しに在る（1833773）。
  5. RL の `ENGINE_RUNS[builtin].reply(b, nid, launch, runs)`。返りが `fallback` → 7 へ。
  6. 返りの `reply` を `accept` に通す。拒まれたら 7 へ。
  7. **任せ先へ落とす**: 記憶の入れ物を捨て、ディスクから盤面を読み直し（engine の `_engine_fallback` と同じ〔再審 N3〕）、RL の `ENGINE_RUNS[builtin].fallback` が在れば呼び（`checks_fallback` は `process.checks[nid] = {by: "role", why}`）、instance に `engine_fallback`（理由）を書いて保存する。**保存の後、読み直した `state`・`record`・`seen_rev`・`halted_at_read` を `self` に入れ直し、読んだ物の控え（`_out_cache`・`_porcelain`・`_vtables`）を消す**（呼び出し側は同じ入れ物のまま `settle` してよい。入れ直さないと次の `save` が `BoardConflict` で落ちる〔再審2 P2〕）。その後は表の `fallback` のとおり: `machine`・`role` なら節は待ちのまま `ready` に残り、ラインが `done` で渡す／`absent` なら `skipped` に表の理由。
- 既定の `runner` は works の `tree_run` で 1 段ずつ走らせる（shell を通さない・別のプロセスグループ・期限なし・`uv run` の環境を外す〔台帳 R23〕・止める時は SIGTERM → `KILL_GRACE`（2 秒）→ SIGKILL）。返りの行は engine の `run_steps` と同じ鍵 `{name, argv, exit, wall_s, out, err, tail, error?}`。ログは `runs/r<N>/<id>.a1/`（`out`・`err` はそのファイルのパス。`parallel_pr_reply` は `out` のファイルを読む）。`tree_run` が止められて `Stopped` を投げたら、盤面を書かずに投げ直す（Archon の取り消し・Ctrl-C。節は待ちのまま）〔再審 m5〕。
- 引数の `runner` は試験が撮った `runs` を返す偽の runner を、`plan` は撮った計画を差し込むためにある（sha の照合の試験は、撮った計画の後に宣言を書き換えて当てる〔再審 m2〕）。
- これで `p4.ci` が engine と同じ `process.checks["p4.ci"] = {round, by: "engine", sha, runs}` を残し、線 B は engine と同じ条件で収束できる。宣言が無い対象では engine と同じく `by: "role"` になり、`converge` は `ci_unverified` を聞く（review-graph と同じ）。
- engine との違いは計画の時機だけ（engine は `next` の中、DiskBoard は `run_engine` の中）。`checks_fallback` の記録が早いか遅いかの差で、周の終わりの記録は同じ（9.3 の通しの再生で見る）。

### 4.4 開くときの検査と読み替え〔審 I7〕

- 順:
  1. `state.graph_sha` と写しの graph の `sha(graph_text(...))` を比べる。違えば `BoardMismatch`（文に両方の値）。
  2. `state.works.board_version` を知らなければ（無いも含む）`BoardMismatch`。
  3. 表の縛り（4.2）を当てる。
  4. 記憶の中だけで読み替える: `state.graph`（写しの graph）・`state.validator`（写しの RR）・`inputs.scripts_dir`（写しの `scripts/`）・`inputs.review_md`（写しの `REVIEW.md`）。
  5. `overrides` を当てる。
- `overrides`（`{名前: (関数, 理由)}`）は、読み込んだ RL の module の**大域の名前**を差し替え、`state.works.overrides` に名前と理由を書く。RL の `BUILTINS`・`CONDS`・`POST_CHECKS`・`ENGINE_RUNS` の dict は読み込み時に関数を掴むので、その dict の値になっている関数の名前を渡したら `BoardGap`（差し替えても効かないため〔審 M5〕）。RL は開くたびに新しく読むので、差し替えは他の盤面に漏れない。土台自身は差し替えを 1 つも持たない。
- 実物の盤面（`state.works` を持たない）を試験で開くときは、一時の写しに `state.works = {board_version: 1, …}` を足してから開く（ディスクの見本は変えない）。

### 4.5 「このラインに無い」を毎周の記録の隣に出す〔審 I5・C2〕

- `state.works.not_in_line` は表の absent の全部 `[{node, reason, comes_with}]`。`create` が書く。
- 周の記録（`p4.record`）が済むたび、止めた周の記録（`stop` の `on_stop`）を書いたとき、`settle`・`stop` が `rounds/works/round-<N>.json` を書く:
  `{round, line, table_sha, not_in_line: [{node, reason, comes_with, in_round: "skipped"|"na"|"pending", materials: {素材: status}}], skipped_optional: [{node, reason}], checks: {節: {by, why?}}}`
  - `in_round` は、その周の周の箱で absent の節がどう終わったか（条件に当たらない周は `na`——それでも「このラインに無い」ことは行として残る）。
  - `checks` は `process.checks` の今の周の分（CI を engine が確かめたか・自己申告か）。
- `process.skipped` は engine と同じ意味のまま（条件に当たって省いた節だけ）。報告の冒頭は `state.works.not_in_line` と周の添え書きから読む。
- 写しの周の記録（`rounds/round-<N>.json`）に works の欄を足すと RR が拒む・写しを変えることになるので、隣のディレクトリに置く。B の検証器の包みはこの添え書きを読める（BL5）。

### 4.6 誤りの型

- `BoardGap(Exception)`: 内部の誤り（表の欠け・配線の誤り・保存できない盤面への保存・効かない差し替え）。役に返しても直らない。
- `BoardMismatch(BoardGap)`: 盤面を開かない（graph_sha・`board_version`・表の graph_sha）。文に両方の値を出す。
- 役の返答の誤りは engine の `Reject` のまま（受け付けのスクリプトの今の約束を変えない）。

## 5. `begin()`（線 A と B の `start` が共通に使う入口）

```python
DiskBoard.begin(dir, *, repo, table, items, origin, base_rev, request_text, inputs=None,
                max_rounds=None, stop_after_round=None, overrides=None, validator_runner=None) -> tuple[DiskBoard, Progress]
base_output(repo: Path, base_rev: str) -> dict      # p0.base の返答を機械が組む
```

- 順: `create` → `add_request(items, origin)` → `accept("p0.base", base_output(repo, base_rev))` → `settle()`。
- 判定から入る run になる（RL の `add` が 1 周目の P1 より前の最初の依頼で入口の印を立てる）。`settle` が P1 の役の節を engine と同じ理由の `na` にする。`begin` の後の `ready` は表しだい〔再審2 m11〕:
  - `start` は、`ready` に在る engine_run の節を**全部** `run_engine` し、`settle()` する（`p0.local_checks`＝修正前の CI。表が `p0.parallel_pr` を engine_run にしていればそれも。`p1.consistency_bypass` が `p0.parallel_pr` に依存するので、P1 の `na` もその後に付く）。
  - 任せ先に落ちた節は、表の `fallback` の持ち主が `done` で渡す（`p0.local_checks` の `fallback: machine` なら、線 A の `start` が `test_cmd` を走らせた結果を渡す。8.1）。
  - その後 `p1.worktree_before`（版を固める）・`p1.worktree_after`（作業ツリーの突合と素材の欄の埋め）が走る。試験用の表（`entry-line.json`。`p0.parallel_pr` は absent）なら、ここで `ready` は `["p2.diagnose"]` になる。
- `base_output`（graphloops の実物の p0.base の返答と同じ書き方〔盤見本: wt-ci-skip・wt-layer1 の out/r1/p0.base.json〕）:
  - `base_sha`: `base_rev`、空なら `HEAD`（Ruling R2）の commit。`method`: `4 依頼者の名指し`。`commits`・`merge_commit`: `git rev-list` で数える。`intent_to_add`: 空。
  - `touches_*` の 4 つ: 全部 true（機械には判定できないので走らせる側に倒す。実物の writer も「迷って true」）。走らせない節は表の absent が理由を書く。
  - `material`: `{"status": "found", "count": <commits>, "detail": "<版>（base_rev の名指し。空なら HEAD）"}`。
- 冪等: 置き場に盤面が既に在り、記録の依頼が同じ（sha256）なら、作らずに開いて返す。違えば `BoardGap`。
- 1 周の run（A）は `stop_after_round=1`（graphloops の `--stop-after-round 1` と同じ。BL19）。

## 6. 持ち物（どの線がどのファイルを触ってよいか）〔審 I10〕

| ファイル | 持ち主 | 他の線 |
|---|---|---|
| `.shared/core/graphloops/**`・`.shared/core/scripts/**`・`COPIED_FROM`・`tests/test_core_copy.py` | 写し直し | 触らない |
| `.shared/core/board.py` | 土台 | 読むだけ |
| `.shared/core/accept.py` | 土台（1 度） | 触らない |
| `tests/test_board*.py`・`tests/test_core_verbatim.py`・`tests/test_accept_v1_golden.py`・`tests/boardreplay.py`・`tests/boards/**` | 土台 | 読むだけ |
| `dev/board-goldens/**` | 土台 | 触らない |
| `darkfactory/**`（`nodes.json` を含む） | A | 触らない |
| `blk-plan/**`・`blk-refix/**`・`blk-fix/**`・`blk-delta/**`・`blk-tests/**` | A | 触らない |
| `.shared/adapter/**`・`dev/stop.sh`・`dev/report.sh` | A | 読むだけ |
| `.shared/core/{recount,halt,reads,plan,refix,entry,policy,report,ticket}.py` | A | 読むだけ |
| `tests/replies/fix2_*`・`tests/replies/plan*` | A | 読むだけ |
| `blk-judge/**` | B（A が波 1 に 1 度） | — |
| `darkfactory-rounds/**`（`nodes.json`・`declarations.json` を含む）・`blk-close/**` | B | 触らない |
| `.shared/core/{rounds,judge2,close}.py`・B の検証器の包み | B | 触らない |
| `tests/replies/judge2_*` | B | 読むだけ |
| `mutgate/**`・`blk-mut-triage/**`・`tests/fixtures/mut-target/**` | C | 触らない |
| 下の「共有」の一覧 | 共有 | 各線の最後の 1 commit |

- **共有**（各線の最後の 1 commit でだけ触る。merge の順は 写し直し → 土台 → A → B → C）:
  - `tests/test_yaml_rules.py`・`tests/yaml_good/**`・`tests/yaml_bad/**`
  - `tests/test_line.py`・`tests/test_script_headers.py`・`tests/run.sh`
  - `dev/check.sh`・`dev/mktarget.sh`・`dev/real-run.sh`・`dev/archon.sh`・`dev/guard.sh`
  - `skills/works/SKILL.md`・`README.md`・`archon-plugin.json`
  - `docs/specs/2026-09-26-darkfactory-design.md`（冒頭の「続きの仕様」の 1 行だけ）
- 写しは誰も直さない（BL2）。直したくなったら、写しの外に置く道（`overrides`・`validator_runner`）を使う。写しに足りないファイルは写し直しの線に頼む（BL21）。
- `accept.py` は土台が 7 節の移し替えを 1 度だけ行い、その後は凍る（BL7）。使われなくなった `check_*` を消すのは 3 本の合流の後の片付け（どの線の仕事でもない）。
- `blk-judge/` は B の持ち物。A は波 1（B が判定 v2 に着手する前）に、入力 `policy_file` と方針を貼る `brief` の節だけを入れる〔A〕8 節。
- 台帳（`.superpowers/…/progress.md`、`works/` の外）への書き込みは計画の外で、持ち主の会話の側（coordinator）が行う。

## 7. v1 の `accept.py` の移し替え（振る舞いを変えない）

- 替えるのは、規則に渡す入れ物だけ。`_Board` を消し、`DiskBoard.scratch(board, …)` に替える。関数の名前・引数・返り値・拒否の文・盤面に書くファイル（直下の `request.json` など）は変えない。
- 関数ごとに記憶の中に組む物（今の `_Board` に渡していた物と同じ）:

| 関数 | review_rev | 記憶の中に置く物 |
|---|---|---|
| `check_request` | 空 | 依頼 |
| `check_judge` | 固めた版 | 依頼 |
| `check_fix` | 固めた版 | units・questions |
| `check_delta` | 固めた版 | `loop.fix_delta` |

- 出どころは今と同じ: 依頼は直下の `request.json`、units・questions は `judgment.json`、`loop.fix_delta` は `{round: 1, files: touched_files(...)}`。
- `check_delta` が今渡している `outputs={"p3.fix": {}}` は渡さない（RL の `_closed_keys` が None を空に倒す）。この主張は 9.4 の手本の一致で確かめる。
- v1 の受け付けは instance を使わない（`scratch` の周の箱は空）。今の偽の盤面と同じ。
- 盤面のファイルは今までどおり: `state.json` は作らない。

## 8. 各線の使い方と、各線の下書きへの申し送り

### 8.1 線 A（1 回の run を強くする）

- 〔A〕の冒頭と 1 節の 2 の「共通の土台は〔輪〕3 節」を、この文書に差し替える。
- `start` は `DiskBoard.begin(..., stop_after_round=1)`。依頼の受け付けと方針の固定（RL の `on_init`）もここで済む。表が `p0.local_checks` を `engine_run`（`fallback: machine`）にすれば修正前の CI も engine と同じに記録される。宣言が無く任せ先に落ちたときは、`start` が `test_cmd` を `tree_run` で走らせ、`{"material": …}` を `done("p0.local_checks", …)` で渡す（`process.checks` は engine と同じく `by: "role"`）。
- 役の返答は各ブロックの受け付けで `b.done(nid, 返答)`。拒否は `Reject` のまま `{"ok": false}` に写し、その入れ物は捨てる。
- 自前で版を固めない。修正後の版と `loop.fix_delta`（`p3.fix_delta`）・義務の組み立て（`p3.delta_owed`）・関所の項目（`p2.human_gate`）は `settle` が RL の機械の節で作る。
- 修正前の関所: `p2.human_gate` が項目を持てば `settle` が `asking` を返す（周の途中の問い）。Archon の関所の答えは次の境の節が `b.answer("continue" | "stop", 一言)` で渡す（RL の `on_answer_in_round` → `human_gate_answered`）。
- **テストは `run_engine("p4.ci")`**（〔A〕3.5 の「宣言を読んで tree_run で走らせる」をこの口に置き換える）。宣言が無く `test_cmd` を人が渡した対象では、`run_engine` が `by: "role"` を記録した後、blk-tests が `test_cmd` を走らせた結果を `done("p4.ci", …)` で渡す（表の `fallback: "machine"`）。
- **並行 PR の検査 `p0.parallel_pr`** の持ち方は、持ち主の答え（13 節の 2）の後に決める（BL28）。この層は `engine_run`・任せ先の配管（`fallback: role` も `absent` も）を出すだけ。答えしだいの形: (a) 読むだけの役（6 段の全部。6 段目は申し送りの下書きを報告に載せ `handed_over: false`）、(b) 門番を通して `gh` で投稿する役、(c) 表で absent。どれでも役は opus（台帳 R22）で、仕事は指示書 `p0.parallel_pr.md` の 6 段の全部（任せ先に回った理由は instance の `engine_fallback`。GitHub でない remote・`gh` が無い時も 1〜6 段を役がする）。
- 手厚さは、持ち主が答えるまで「標準」だけ（13 節の仮の裁定）。
- 手厚さ（〔A〕4 節）で省けるのは graph で optional の節だけ（`skippable`）。事前審査・差分の審査と手直しを省く「軽量」は 13 節で持ち主に聞く。
- 止め札を見た境の節は `b.stop(理由, by)`。止めた後の `report` は `DiskBoard.open(..., allow_halted=True)`。
- **足される能力**: `p4.ci` を受けた後の `settle` が `p4.scalars`・`p4.assemble`・`p4.record`（周の記録と検証器）・`converge` まで engine と同じに回し、`stop_after_round=1` で止まる。〔A〕10 節で「下」にしていた「周の記録と検証器」が 1 周の run でも付く。

### 8.2 線 B（周の輪）

- 基準の版を a1202d0 に替える（〔B〕は fbd40e3。BL1）。
- 〔B計〕T1（盤面）は土台に、T7・T9・T10・T11 は A に移る（BL13）。T2（写しへの `not_in_line` の書き込み）は写しの外に作り直す: 検証器の包み（RR を import し、状態の表に `not_in_line` を足す）を `validator_runner` で走らせ、RL が表を引く `validator_module` を `overrides` で包みの module に向け、収束の最後の関門を宣言で省く所も `overrides` で差し替える（BL5）。`state.validator` は写しの RR のまま（`inputs.scripts_dir`・`review_md` を壊さない）。
- 〔B〕4.4 の `darkfactory/declarations.json` は `darkfactory-rounds/declarations.json` に置く（`darkfactory/**` は A の持ち物）。宣言の `nodes` は節の表の absent と同じ物にする（2 つの一覧を持たない）。
- 周の頭と締めは `settle` が engine と同じ順で回す。Archon の段の境を置きたい機械の節（例: `p4.record`・`converge`）は表で `explicit` にして `b.run_builtin` で呼ぶ（壁になるので、後ろの条件の評価は engine と同じ時機に保たれる）。
- `p0.parallel_pr` は、持ち主の答えの後に A と同じ持ち方にする（役のブロックが要るなら A の物を include する）。
- テストは `run_engine("p4.ci")`。宣言の在る対象なら、収束の周で `ci_unverified` を聞かずに収束できる（review-graph と同じ）。
- 周の関所の答えは `b.answer`。`rejudge` は engine に無い語なので B が持つ。周の番号・関所の段・冪等の決まり（〔B〕3.3）は B の `rounds.py` が持つ。
- ラインは `darkfactory-rounds/`（台帳 R25）。

### 8.3 線 C（変異の関門）

- 盤面の層を使わない。mutgate の記録は engine の盤面でない（〔C〕7 節）。置き場 `board/mutation/` の名前は土台が予約する。
- 規則の関数（`_unproven`・`_lane_errors`・`_final_gate_problems` の芯）と型（`$defs.lane_reply`・`gate_arm`）は、写しから `rules_module()`・`graph_expanded()` で読む。書き直した写しを持たない。a1202d0 の `_lane_errors(b, out, rev, final)` は `b` を読まないので `None` を渡してよい。
- 宣言は写しの `engine/declared.py`。〔C〕6.1・12 節の「declared.py を別に写す・0.20.3 の写しを替えない」は取り下げ（BL1・BL14）。仕分けの役は opus（台帳 R28）。

## 9. テスト

### 9.1 単体（Archon 不要。`works/tests/run.sh`）

1. 節の表: 縛り 1〜5 の良い見本と悪い見本（節の抜け・重複・driver に role・engine_run の無い節に engine_run・理由の無い absent・graph_sha 違い・optional でない節に skippable）。
2. 開く: 実物 2 個（wt-ci-skip・wt-layer1）を一時の写しに `state.works` を足して開き、engine の `Board` と `DiskBoard` で `round`・`rd`・`loop_state`・`record`・全部の節と周の `output_of_round`・`node_state` が同じ。`DiskBoard` の属性の鍵は engine の鍵を全部含む。
3. 開かない: graph の違う実物 35 個と `sim/` 4 個で `BoardMismatch`、文に両方の graph_sha。graph が同じで `state.works` の無い盤面は `board_version` の理由。
4. 作る: `inputs.rounds_dir` と `process.policy.copy` が最終の置き場の下。入口の検査で拒めば置き場が残らない。
5. 保存: `edit` の中の例外で盤面が変わらない。`BoardConflict`。`halted` の盤面は `allow_halted` 無しで保存しない。`scratch` は保存しない。
6. `accept`: instance が `done` になり `state.outputs[nid].instance` が書かれる。`halted` の run では拒む〔再審 m7〕。レンズの条件が偽の周に `invoked: false`・`failed` で返した `p1.local_review` を通す（`inst.skills[].applies` が効く〔再審 N1〕）。判定を受けた後に台帳に無い人待ちの素材を書く `p3.fix` を engine と同じ文で拒む〔審 C1〕。番号で書いた `unit_keys` を拒む〔審 I1〕。型・`post_check` の拒否で盤面が変わらない。absent の節・待っていない節は `BoardGap`。
7. `settle`: 人に聞いている間の `done` が `p2.human_gate` を走らせ直さない〔審 I3〕。`p4.record` を explicit にしても、`converge` 以降の `na` の付け方が auto と同じ〔審 I8〕。
8. `run_engine`: 宣言の在る使い捨てのリポジトリで `process.checks["p4.ci"].by == "engine"`。撮った計画の後に宣言を書き換えて当てると `{ok: false, relaunch: true}` で盤面が変わらない。宣言が無ければ `by: "role"` と `engine_fallback`。受け付けが拒んだ時は、読み直した盤面に `by: "role"` が書かれ、他の欄はディスクの前と同じ〔再審 N3〕。`helper` の計画（`p0.parallel_pr`。偽の `gh` と偽の remote）で写しの `parallel-pr.py` が走り、交差が在れば `reply` の `fallback` で任せ先へ落ちる〔再審 N2〕。`Stopped` で盤面を書かない。
9. 周の添え書き: 表の absent の全部が `rounds/works/round-<N>.json` の `not_in_line` に在る（条件で `na` の周も）。`na` でない absent は `process.skipped` にも在る。
10. `overrides`: 大域の名前だけが差し替わり、`state.works.overrides` に理由つきで残る。dict の値の関数の名前は `BoardGap`。別の盤面には効かない。
11. 写しを変えない: `COPIED_FROM` の各行のファイルが `git show a1202d0:<元のパス>` と同じバイト（行の読み方は `tests/test_core_copy.py` と同じ式——2 行目から、空行と `#` の行を除き、`ln.split()[0]`——を使う〔審 M12〕。a1202d0 が引けなければ理由を出して飛ばす）。

### 9.2 手本の撮り方（`works/dev/board-goldens/`。お金 0、AI 0、graphloops には触らない）〔審 C3・再審 N4〜N6・m1・m3・m4〕

1. a1202d0 の graphloops を使い捨ての場所に `git archive` で出す（台本 `simulate_review.py` は写しに無いため）。
2. `make.py` は台本の場面を**1 つずつ**呼ぶ（台本の `main()` は場面を並べて回すので使わない）。場面の中の `Run` は `Run.dir`（`--dir` の置き場）で見分け、`run` の番号を振る。
3. 子プロセスの `loop.py` に `sitecustomize.py` を読ませ、**engine の中で、手の前後に記憶の中の `b.state` と `b.record` を撮る**（ディスクの `state.json` は `advance` の最後にしか書かれないため）。
   - `sitecustomize.py` は、起こされたのが `loop.py`（`sys.argv[0]` の名前）で、`WORKS_GOLDEN_OUT` が在るときだけ働く（台本のテストの語や検証器の子にも `PYTHONPATH` が継がれるため〔再審 m3〕）。
   - 包み方: 書き出した graphloops の engine の module を先に import し、`engine.commands.Board` を記録つきの子クラス `RecordingBoard` に替え、module の属性で次を包む（`loop.py` は後で同じ module を import し、サブコマンドの関数は `main()` の中で引くので、包んだ物が使われる）: `advance.run_driver_node`・`advance.open_next_round` と `commands.open_next_round`・`commands.accept_output`・`cmd_init`・`cmd_add`・`cmd_answer`・`cmd_skip`・`cmd_stop`・`cmd_patch`・`cmd_finalize`・`commands.launch_engine_run`〔再審 N4〕。
   - 条件の `na` は `advance` の中の直の代入で、関数として包めない。`RecordingBoard` が `applicable()` を上書きし、理由を返した時に `{node, why}` を撮る（`na` の手の後は「前 ＋ `rd.na[node] = why`」で決まるので記憶を撮らない〔再審 m1〕）。
   - 撮る物: 手の種類・節・引数（返答の本文・答え・理由・`accept_tree_change`・patch の path と値）・拒んだなら文、手の前後の記憶、手の前後のディスクの `out/`・`rounds/`・`count-*.json`・`policy/`・`lanes/`・`runs/` の目録、手の前の対象リポジトリ（作業ツリーと `.git` の `objects`・`refs`・`HEAD`・`index`）。
   - engine が走らせる節は「走らせる」と「受け付け」に分けて撮る: `plan` の結果と `run_steps` の返り（`runs`。`out` のファイルの中身も）、`reply` の前の記憶、続く `accept_output` の手。
   - `init` で拒まれた Run（盤面を作らない）は、`raised` を持つ `init` の 1 手として残す（期待どおりの拒否の見本。作り手を止めない〔再審 N5〕）。
4. 版の id を揃えるため、撮る時は git の名前と時刻を固定した環境（`GIT_AUTHOR_*`・`GIT_COMMITTER_*`）で回し、再生も同じ環境で回す。
5. **置き方と大きさ**〔再審 N6〕:
   - 中身は全部 `blobs/<sha256>.gz`（gzip。同じ中身は 1 度だけ）。ディスクの目録とリポジトリの目録（パス → sha256）も、記憶と同じく Run の頭だけ丸ごと、以後は前の目録からの差分（足した・替えた・消したパス）で持つ〔再審2 P3〕。`steps/<場面>.json` も gzip（`steps/<場面>.json.gz`）。
   - 記憶は、各 Run の最初の手の `before` だけを丸ごと持つ。以後は、手の `before` を「前の手の `after`（拒まれた手なら前の手の `before`）からの差分」、`after` を「その手の `before` からの差分」で持つ。差分は JSON の置き換えの一覧 `[{path: [鍵…], op: "set" | "del", value?}]`（深い所の 1 欄の変更は 1 行）。`na` の手は `{node, why}` だけ。
   - 絶対パスは `@BOARD@`・`@REPO@`・`@CORE@`・`@PY@`（撮った機械の Python。台本の宣言の語が `sys.executable` のため〔再審 m4〕）に置き換える。macOS の `/var/…` と `/private/var/…` の両方の綴りを置き換える。`@PY@` を含む宣言の sha（`process.checks[..].sha`・`launch.sha`）は、再生の時に今の Python のパスで計算し直してから比べる。
   - 見積り（推測。見本 `sim/` の実物から）: 最後の `state.json` は `test_converges` で 219 KB（gzip で 20 KB、約 11 分の 1）、`test_runaway` で 457 KB（32 KB）。手の数は trace の行で 140・280。1 手の記憶の差分は数 KB（gzip で 1 KB 未満）。目録は、最後の時点で対象の範囲のファイルが `test_converges` 89 個・`test_runaway` 171 個（1 行約 110 バイト）で、丸ごと持てば Run 1 本で 1.4〜5 MB になるが、差分なら 1 手に数行（`.git` の新しい object を含めて数十行まで）で、gzip の後は 1 手 1 KB 前後。Run 1 本で記憶 0.1〜0.3 MB・目録 0.1〜0.3 MB・blobs の中身 0.1〜0.2 MB。Run は 12 場面で約 30 本（`init` で拒まれた短い Run を含む）なので、合わせて **8〜20 MB**。上限は **30 MB**。作り手は場面ごとの大きさを目録に書き、試験は 30 MB を超えたら場面ごとの内訳つきで落ちる。
6. 撮る場面: `test_converges`・`test_runaway`・`test_awaiting`・`test_rejections`・`test_request_entry`・`test_fix_plan_review`・`test_human_gate`・`test_policy_reaches_roles`・`test_stop_midround`・`test_stop_after_round`・`test_gates_merge`・`test_rejudge_path`。
7. 撮らない場面と理由（目録の `skipped_scenarios`）: `test_delta_conditions`・`test_fix_counts_by_engine`（`loop.py` を通らず偽の盤面で規則を直に呼ぶ）、`test_lane_end_to_end` など変異の実行器を起こす場面（変異テストを回さない決まり）。
8. 目録の頭: graphloops の commit・graph_sha・撮った日・場面と Run ごとの手の数と大きさ・手の種類ごとの数・`init` で拒まれた Run の一覧・**撮れた手本が通らない道**（`uncovered`。線 A・B が使う機械の節と engine が走らせる節のうち、1 度も出ない物）。
9. 作り手が失敗で止まるのは、`init` が通った Run で手が 0 のとき・包んだ関数が 1 度も呼ばれない場面があるとき（包み方が効いていない）だけ。

### 9.3 手本での再生

- **1 手ずつ**（`test_board_steps.py`）: 手の前の記憶とディスクとリポジトリを一時の場所に戻し、`DiskBoard`（表は `NodeTable.everything(graph)`。driver は builtin/auto、engine_run の節は engine_run、他は role）を記憶から組む → 同じ手を **settle しない口** で当てる（役の返答 → `accept`、機械の節 → `step_builtin`、周の開き → 前の `converge` の手を `step_builtin`、engine が走らせた節 → 撮った計画と `runs` を差し込んで `run_engine`、依頼 → `add_request`、答え・省く・止める → `answer`・`skip`・`stop` の中の記録の部分、`finalize` → `b.finalize()`）→ 手の後の記憶とディスクと比べる。`na` の手は節を 1 つだけ評価する内部の口 `_settle_node(nid)` で比べる〔再審 m1〕。`patch` の手は works の口を持たないので、撮った差分（その手の `after`）をそのまま記憶に当てて次へ進む（手本の engine の手そのものでなく、人が盤面を手で書いた事実を写すだけ）。`init` の手は `create`（同じ入力）の結果と比べ、拒まれた `init` は `create` が同じ文で拒むことを見る。
- **通し**（`test_board_replay.py`）: `Run` の頭（`init` の手の後）の盤面から、撮った手の順に `done`・`run_engine`・`answer`・`skip`・`stop`・`add_request`・`finalize` を当て続け（`patch` の手は上と同じく撮った差分を当てる）、機械の節と `na` は `settle` に任せる。各手の前に対象リポジトリだけは撮った物に戻す（役が作業ツリーを変えた分）。**盤面を engine の側から写し直すことは一度もしない**。各周の終わりと最後で engine と同じか（周の箱の `done`・`na`・`skipped` の節と理由・`loop`・`record`・`status`）。
- **比べない欄の表**（`boardreplay.py` の `NOT_REPRODUCED`。名前と理由を持ち、試験の出力に毎回並べる〔審 I12〕）:
  - 時刻: `at`・`t`・`created`・`done_at`・`emitted_at`・`launched_at`
  - 盤面の版: `state.rev`・`run_id`
  - engine の周の頭の痕跡（`graph_changed`・`engine_changed`・`frozen_outputs_stale` を持たないため）: `state.engine`・`engine_changes`・`stale_frozen`・`graph_changes`
  - instance の起動の欄（描画・起動を持たないため）: `prompt_sha`・`prompt_file`・`launch`（engine_run の `steps`・`sha` は比べる）・`tree_before`・`attempts`・`attempt_log`・`pointers`・`delegate`・`agent_id`・`read_from`（`skills` は比べる〔再審 N1〕）
  - engine が走らせた節の `checks_fallback` を書いた時機（計画の時機が違うため。周の終わりの値は比べる）
  - 実行の時間: `runs[].wall_s`、ログのパス `runs[].out`・`err`
  - `state.works`（works だけの欄）
- ずれを見つけたら `board.py` を直す。手本と比べない欄の表は、理由を書いて足す時だけ直す。

### 9.4 v1 の振る舞いの一致（`test_accept_v1_golden.py`）

- 移し替えの前の commit で、`tests/replies/` の全部の返答と依頼を `check_*` に通し、結果を撮る。移し替えの後に同じ入力で同じ結果（`ok`・`reason` の全文・`open_units`・書いたファイルの名前）。

## 10. 裁定（A・B・C の下書きの食い違いと、審査への答え）

- **BL1 写しの元は a1202d0 の 1 つ**。〔B〕の fbd40e3、〔C〕の「0.20.3 の写しに 0.21.0 の断片を足す」を置き換える。能力: 0.21.0 の工程が使えるので上。
- **BL2 写しは 1 バイトも変えない**。works の足し算は写しの外（`overrides`・`validator_runner`・`accept.py` の中の言い換え）。〔B計〕T2 を置き換える。能力: 同じ。
- **BL3 盤面は engine の盤面そのもの**。`DiskBoard` は engine の `Board` を継ぎ、instance の控えも engine と同じに残す。〔B〕3.2 の自前の読み口を置き換える。能力: 同じ〜上（graphloops の盤面を同じ道具で開ける）。
- **BL4 節の表 1 つで、A の「省いた印」と B の「宣言の nodes」を兼ねる**。表に無い節があれば開かない。能力: 上（省く理由が run の前に固まる）。
- **BL5 収束を止めない宣言（〔B〕の `not_in_line`）は B が写しの外で作る**。土台は口だけ: `validator_runner`（検証器を走らせる所）と `overrides`（RL の大域の名前。`validator_module` を含む）。`state.validator` は写しの RR のまま。能力: 持ち主の決定（案 B）のまま。
- **BL6 機械の節は engine と同じく `settle` が回す**。段の境に置きたい節だけ `explicit`（壁）。〔A〕3.3 の自前の版固め・〔B〕4.1 の自前の `_snapshot` を置き換える。周の頭と締めの専用の手助けは作らない。能力: 同じ。
- **BL7 `accept.py` は土台が 1 度だけ移し替え、その後は凍る**。能力: 同じ。
- **BL8 作業ファイル: engine が書く物は engine の置き場、works が書く物は `r<N>/`、v1 の物は直下のまま**。
- **BL9 依頼の正本は記録の `process.request_findings`**。`request.json` は v1 の受け付けだけ。
- **BL10 止める意味は土台の `stop()`**（engine の `cmd_stop` と同じ）。止め札と境の節は A。
- **BL11 人の答えは土台の `answer()`**（engine の `cmd_answer` と同じ）。`rejudge` は B。
- **BL12 周の輪は別の入口 `darkfactory-rounds/`**（台帳 R25）。
- **BL13 数え直し・止め札・包み・読んだ証拠は A が作る**（〔A〕8 節の割り当て）。
- **BL14 線 C は盤面の層を使わず、写しの関数を読むだけ**。`board/mutation/` は予約。
- **BL15 C の仕分けの役は opus**（台帳 R28）。
- **BL16 盤面の手本は a1202d0 の台本を撮り直して作る**。`sim/`（fbd40e3）と graph の違う実物は「開かない」の試験に、graph が同じ実物 2 個は読み口の一致と返答の形に使う。
- **BL17 `accept` は engine と同じく番号の読み替え（`pointers.resolve`）を通す**（1 版の「読み替えない」を改める〔審 I1〕）。一覧を固めた instance を持たないので、番号で書いた返答は engine の文で拒まれ、名前で書いた返答はそのまま通る。
- **BL18 省けるのは graph で optional の節だけ**（1 版の「表が許せば何でも省ける」を改める〔審 I6〕）。engine の `skip` と同じ強さ。optional でない節を手厚さで省く件は 13 節。
- **BL19 1 周の run は `stop_after_round=1`**。
- **BL20 engine が走らせる節は、表の種類 `engine_run` と `run_engine` で engine と同じ記録を残す**〔審 C2〕。走らせる所だけ works の `tree_run`（`uv run` の環境を外す。台帳 R23）に替える。能力: 同じ（`by: "engine"` の CI、宣言の sha の突き合わせ、宣言が無ければ任せ先と同じ `by: "role"`）。
- **BL21 写しに無い `scripts/comment-ratio.sh` と根の `REVIEW.md` は、写し直しの線に「a1202d0 から同じバイトで足す」と頼む**〔審 I4〕。RL が検証器の置き場から引く所（`p4.scalars` の規模の数値・`inputs.review_md`）が engine と同じに動く。能力: 同じ。足されるまでは `p4.scalars` が「測れない」を記録に残す（RL の決まりどおり黙らない）。
- **BL22 「このラインに無い」は毎周の添え書き `rounds/works/round-<N>.json` に必ず出す**〔審 I5〕。`process.skipped` は engine の意味のまま。能力: 上（graphloops の記録に無い「このラインの形」が周ごとに残る）。
- **BL23 手本は engine の中の記憶を撮り、再生で盤面を engine から写し直さない**〔審 C3〕。`loop.py` を通らない 2 場面は撮らず理由を書く。周の途中の問いを通る 2 場面を足す。
- **BL24 v1 の受け付けの入れ物（`scratch`）は instance を持たない**。今の偽の盤面と同じで、振る舞いを変えない決まり（7 節）を優先する。v1 の判定の受け付けで「判定の後の人待ち」の検査が効かないのは今と同じで、新しい線（A・B）は `accept` を使うので効く。
- **BL25 engine に同梱の語（`helper`。今は `parallel-pr.py`）も `run_engine` が engine と同じに走らせ、`reply` の `fallback` も任せ先へ落とす**〔再審 N2〕。`parallel-pr.py` は写しに入った（1833773）。表の `fallback` に `role` を足した。能力: 配管として同じ。`p0.parallel_pr` をどう持つか（能力が同じになるか）は BL28。
- **BL26 手本は差分と gzip の内容の置き場で持ち、上限 30 MB（見積り 5〜15 MB）**〔再審 N6〕。`patch`・`finalize`・`init` も手として撮り、`init` で拒まれた Run は期待どおりの拒否の見本として残す〔再審 N4・N5〕。
- **BL27 「軽量」は、持ち主が答えるまで案 1（標準だけ）**。この層は optional の節しか省かせない（BL18）ので、案 1 のままなら層を直さずに済む。
- **BL28 並行 PR の検査の持ち方は決めない**〔再審2 P1〕。review-graph の任せ先の役は他人の PR に申し送りを投稿する（外への書き込み）ので、方針により持ち主に聞く（13 節の 2）。仮の裁定: この層は engine_run と任せ先の配管だけを出し、線 A・B は答えの後に `p0.parallel_pr` の表の行を決める。この層の Task 1〜10 は答えに依らない（試験用の表では `p0.parallel_pr` を absent と engine_run の両方で見る）。
- **BL29 `run_engine` は任せ先へ落とした後、読み直した盤面を呼び出し側の入れ物に入れ直す**〔再審2 P2〕。engine は `next` ごとに盤面を開き直すので、同じ入れ物で続ける works の側だけが要る足し算。能力: 同じ。

## 11. 危うい所

- **今壊れている物**: 無い（この層はまだ無く、v1 は偽の盤面のまま動いている）。
- **壊れる余地**:
  - `settle` は engine の `advance` の輪を、役の控えを出すだけの形に書き直す。順や条件の評価の時機がずれうる。9.3 の通しの再生で見る（盤面を写し直さないので、どの段のずれも最後まで残って見える）。
  - 手本は偽の AI の返答で作る。本物の opus の返答の形のずれは実物 2 個でしか見ない。
  - 手本の撮り方は、台本が `loop.py` を子プロセスで起こし、`sitecustomize.py` が engine の module を先に読めることに頼る。撮れた手が 0 の場面があれば作り手が失敗で止まる。
  - `run_engine` の既定の runner は engine の `run_steps` でなく works の `tree_run`。返りの行の形を同じにする試験（9.1 の 8）で縛る。子の止め方は `tree_run` の決まり（SIGTERM → `KILL_GRACE` 2 秒 → SIGKILL・親が替わったら止める。止められたら `Stopped` を投げ、盤面は書かない）で、engine の `pgid_file`・`still_mine`（起こし直しの検知）は持たない（Archon の run が 1 つの持ち主のため）。
  - `p4.record` の検証器が exit 2 を返すと、`settle` はそこで止まり `notes` に理由を出す（engine と同じ）。A の 1 周の run では、まだ無い工程の素材が `not_run` で埋まるので exit 1 が普通の見込み（推測。A の単体テストで 1 度通す）。
  - `DiskBoard` は engine の `Board.__init__` を上書きする。写し直しで `Board.__init__` が属性を増やすと足し損ねうる。9.1 の 2 で落ちる。
  - 手本が通らない道（目録の `uncovered`）は、単体テストと実物 2 個でしか守られない。
  - 並行 PR の検査の任せ先の仕事（申し送り）は、持ち主の答え（13 節の 2）まで線 A・B に無い。その間 A・B の表は `p0.parallel_pr` を決めていない（線 A・B の着手の前に答えが要る。この層の着手には要らない）。
  - `patch` の手の再生は、手本の記憶をそのまま当てる。works の線は `patch` を持たないので、そこだけは engine との一致でなく「当てた後の続きが一致するか」だけを見る。

## 12. review-graph（0.21.0）との能力の差（この層だけ）

- 同じ: 盤面の形・節の状態・instance の控え・受ける順・番号の読み替え・機械の節の順・周の開き・人の答え・止める意味・省ける節（optional だけ）・engine が走らせる CI の記録（`by: "engine"`）と宣言の突き合わせ・保存の衝突の検知。
- 上:
  - 節の表で、graph の全部の節の持ち方と「このラインに無い」理由が run の前に固まり、毎周の添え書きに出る。
  - 盤面を開くときに graph の版を突き合わせて止める。
- 形を変えて持つ:
  - 役のプロンプトの描画・起動・役ごとの作業ツリーの前後の突合は、engine でなく Archon と works のブロックが持つ（作業ツリーの突合は v1 の写し。台帳 R3・R14）。
  - engine が走らせる語は works の `tree_run` で走らせる（止め方は同じく木ごと。起こし直しの検知は持たない）。
  - 依頼を足せるのは `begin` の時だけ（engine は判定役を起こすまで何度でも足せる）。works の線はどれも依頼を run の頭にだけ受ける形なので、足す口を開けていない。
  - engine が走らせる節の計画を立てる時機（engine は `next`、works は `run_engine`）。周の終わりの記録は同じ。
  - 宣言の sha が合わない時: engine と同じく走らせずに `{ok: false, relaunch}` を返す（ラインが呼び直す＝計画し直す）。
- 下: この層には無い。13 節の 2 つは線 A・B の表の選択で決まる: 「軽量」を案 2 にすれば省いた run だけ下がる。並行 PR を (a) にすれば「申し送りを投稿しない（下書きを報告に載せる）」、(c) にすれば「並行 PR の検査が無い」が下がり、どちらも毎周の添え書きと報告の冒頭に出る。

## 13. 持ち主に聞くこと

1. **線 A の「軽量」で、graph で optional でない節（事前審査 `p2.plan_review`、差分の審査 `p3.delta_review`・`p3.delta_review2`、手直し `p3.delta_fix`・`p3.delta_fix2`）を省いてよいか**。review-graph ではこれらは省けない（engine の `skip` は optional の節しか省かない）ので、省けば能力が下がる。
   - **答えが来るまでの仮の裁定: 案 1**（BL27）。この層は optional の節しか省かせず、A は「標準」だけで始める。
   - 案 1（推し）: 省かせない。「軽量」は今は作らない。能力は review-graph と同じ。
   - 案 2: 依頼者が明示したときだけ省かせる。節の表に `downgrade: "<理由>"` の欄を足し、省いた節を `state.works.downgrades` と毎周の添え書きと報告の冒頭に必ず出す。能力はその run だけ下がり、下がったことは全部の記録に残る（この層に小さな足し算が要る）。
   - 案 3: 「軽量」は optional の節（`p2.history`・`r1.comment_candidates` など）だけを省く形にする。今の A の線ではほとんど効かない。
2. **並行 PR の検査（`p0.parallel_pr`）の任せ先の役に、他人の PR へ申し送りを投稿させるか**〔再審2 P1〕。review-graph の任せ先の役は、並行 PR と変更が交差したとき（と、remote が GitHub でない・`gh` が無いとき）、指示書の 6 段目で担当の PR に `gh` でコメントを投稿する。これは run ごとの外への書き込みになる。
   - **答えが来るまでの仮の裁定**（BL28）: この層は engine_run と任せ先の配管（`fallback: role`・`absent`）だけを出す。線 A・B は答えの後に `p0.parallel_pr` の表の行と役を決める。この層の Task 1〜10 は答えに依らない。
   - 案 (a)（推し）: 読むだけの役にする。6 段の全部をするが、6 段目は申し送りの下書きを報告に載せ、`handed_over: false` で返す。外への書き込みは無い。「申し送りを投稿しない」は review-graph より下がるので、`downgrade` として毎周の添え書きと報告の冒頭に出す。後で (b) に上げても層は変わらない。
   - 案 (b): review-graph と同じにする。gates プラグインの門番を通して `gh` で投稿する。能力は同じだが、交差の在る run ごとに外へ書く。
   - 案 (c): `p0.parallel_pr` をこのラインに無い（absent）にする。並行 PR との交差の検査そのものが無くなり、毎周の添え書きと報告の冒頭に出る。

## 改訂 1（審査 `board-layer-review.md` への対応）

- **C1**（instance の控えが無い）: `settle` が `ready` に出す時に最小の instance を置き、`accept` が engine と同じく `done`・`output_file`・`state.outputs[nid].instance` を書く（4.1）。1 の 2 に事実を足し、12 節の「形を変えて持つ」から外した。試験 9.1 の 6。v1 の `scratch` は持たない理由を BL24 に書いた。
- **C2**（CI を engine が確かめた印が落ちる）: 表の種類 `engine_run` と `run_engine`（4.3・BL20）。宣言が無い対象は engine と同じ `by: "role"`。線 A・B の申し送り（8.1・8.2）を `run_engine` に替えた。
- **C3**（手本の撮り方）: engine の中で記憶の中の状態を撮る形に替えた（9.2）。`accept`・`step_builtin` など settle しない口を足し、1 手ずつはそれに当てる（4.1・9.3）。engine が走らせる節は走らせる所と受け付けに分けて撮り、撮った `runs` で再生する。盤面の写し直しはやめた（9.3・BL23）。`loop.py` を通らない 2 場面は撮らず理由を書き、`test_human_gate`・`test_policy_reaches_roles` を足した。場面の中の `Run` ごとに番号を振る。
- **I1**（番号の読み替え）: `accept` が `pointers.resolve` を通す（4.1・BL17）。試験 9.1 の 6。
- **I2**（`create` の順）: engine と同じく最終の置き場で `on_init`、失敗なら `rmtree`（4.1）。試験 9.1 の 4。
- **I3**（`cmd_next` の入口の止め方）: `settle` の 1 に 3 つの止め方、`accept_tree_change` を引数に（4.1）。試験 9.1 の 7。
- **I4**（検証器の包みの置き場）: `state.validator` は写しの RR のまま。包みは `validator_runner` と `overrides` の `validator_module`（BL5・8.2）。読み替えに `inputs.scripts_dir`・`review_md` を足した（4.4）。`comment-ratio.sh`・`REVIEW.md` は写し直しの線に頼む（BL21）。
- **I5**（absent が na に隠れる）: `state.works.not_in_line` と毎周の添え書き `rounds/works/round-<N>.json`（4.5・BL22）。試験 9.1 の 9 を 2 つの主張に分けた。
- **I6**（optional でない節の省き）: 縛り 5（`skippable` は optional の節だけ。4.2・BL18）。線 A の「軽量」は持ち主に聞く（13 節）。
- **I7**（開く時の検査の順）: graph_sha → board_version → 表（4.4）。実物は一時の写しに `state.works` を足して開く。
- **I8**（explicit と条件の時機）: explicit の節は壁にし、後ろを評価しない（4.1）。試験 9.1 の 7。
- **I9**（`scratch` の置き場と検証器）: `scratch(board, …)`、`state.validator` は写しの RR（4.1・7 節）。
- **I10**（持ち物の表）: 共有のファイルを全部並べ、`declarations.json` を B の置き場へ、A の参照の差し替えを申し送り、台帳への書き込みは計画の外と書いた（6 節・8 節）。
- **I11**（計画の並べ方・場面）: 通しの再生（計画 T7）の Files に `board.py` を足し、`begin`（T8）と直列にした。場面は C3 のとおり差し替え、周の途中の問いを見る試験を足した（計画 T2b `test_kinds_cover_in_round_ask`・T6 `test_answer_in_round_continue`・T7 `test_replay_human_gate`）。
- **I12**（比べない欄）: `NOT_REPRODUCED` の表を名前と理由つきで置き、毎回並べる（9.3）。リポジトリの目録に `.git` の objects・refs を含め、`/var` と `/private/var` を両方置き換える（9.2）。
- **M1**: 「上書きする関数の一覧」にした（4.1）。
- **M2**: `settle` の頭で読んだ物の控えを消す（4.1 の 2）。
- **M3**: `create` が `check_inputs`・`choice_input_errors`・パスの絶対化・`request`/`document`/`lang` の既定を行う。`required_inputs_missing` を呼ばない理由を書いた（4.1）。`check_graph` は graph_sha の照合で代える。
- **M4**: 置き場に `runs/`・`*-after-fix` を足した（3 節）。
- **M5**: `overrides` は大域の名前だけ、dict の値の名前は `BoardGap`（4.4）。
- **M6**: 属性の鍵は「engine の鍵を全部含む」（9.1 の 2）。
- **M7**: `sitecustomize.py` は PEP 723 の決まりの例外と計画に書き、包み方を 9.2 に書いた。
- **M8**: `state.works.core`（4.1）。
- **M9**: 計画の T2 を「実物の写し（T2a）」と「手本の作り手（T2b）」に、T4 を「`accept`（T4a）」と「`settle`（T4b）」に分け、`run_engine` を T5 に独立させた。
- **M10**: 計画の T3 の依存を「T1・T2a の後」にした。
- **M11**: 拒んだ後の入れ物は捨てる（4.1）。
- **M12**: 写しの一致の試験は `test_core_copy.py` と同じ `COPIED_FROM` の読み方の式を使う（あちらは関数でなく式なので import できない。9.1 の 11）。`test_core_copy.py` は写し直しの持ち物なので触らない。

## 改訂 2（再審査 `board-layer-rereview.md` への対応）

- **N1**（instance に `skills[].applies` が無い）: `_emit` が engine の `emit_instance` と同じく `skills` を組み、`applies_cond` を `b.cond()` で評価する（4.1・1 の 12）。`NOT_REPRODUCED` から `skills` を外した（9.3）。試験 9.1 の 6。
- **N2**（`helper` と `reply` の `fallback`）: `run_engine` が計画の 4 つの形を全部扱い、`reply` の `fallback` も任せ先へ落とす（4.3）。`parallel-pr.py` は写し直しの線に足してもらう（BL25・計画の波 0）。表の `fallback` に `role` を足し、A・B は `p0.parallel_pr` を `engine_run`・`fallback: role` で持つ（8.1・8.2）。能力は review-graph と同じなので持ち主に聞く物は増えない。
- **N3**（拒まれた後の入れ物）: 任せ先へ落とす時は記憶を捨て、ディスクから読み直してから `fallback` を当てる（4.3 の 7）。試験 9.1 の 8。
- **N4**（`patch`・`finalize`・`init` を撮らない）: 手の種類に足し、`cmd_patch`・`cmd_finalize`・`cmd_init` を包む（9.2 の 3）。再生は `finalize` → `b.finalize()`、`init` → `create` と比べる、`patch` → 撮った差分を当てる（9.3）。
- **N5**（`init` で拒まれる Run）: `raised` を持つ `init` の 1 手として残す。作り手が止まるのは「`init` が通った Run で手が 0」のときだけ（9.2 の 3・9）。
- **N6**（大きさ）: 記憶は Run の頭だけ丸ごと、以後は差分。中身は gzip の内容の置き場。`na` の手は `{node, why}` だけ。見積り 5〜15 MB、上限 30 MB（9.2 の 5・BL26）。
- **m1**（`na` を包めない）: `RecordingBoard.applicable()` の上書きで撮る。1 手ずつは `_settle_node(nid)` に当てる（9.2 の 3・9.3）。
- **m2**（sha の照合の差し込み口）: `run_engine(…, plan=)` で撮った計画を差し込む。照合で拒んだら engine と同じく `{ok: false, relaunch: true}` で節は待ちのまま（4.3・12 節）。
- **m3**（`sitecustomize` の範囲・場面の見分け）: `sys.argv[0]` が `loop.py` のときだけ働く。場面は 1 つずつ呼び、Run は `Run.dir` で見分ける（9.2 の 2・3）。
- **m4**（宣言の Python のパス）: `@PY@` に置き換え、再生で sha を計算し直して比べる（9.2 の 5）。
- **m5**（`tree_run` の猶予）: 2 秒に直し、`Stopped` は盤面を書かずに投げ直すと書いた（4.3・11 節）。
- **m6**（着手の前提）: 写しは 3a89a95 で `comment-ratio.sh`・`REVIEW.md` を持った（0 節・1 の 11）。計画の波 0 を「済み」に直し、残りの `parallel-pr.py` だけを波 0 に置いた。
- **m7**（止めた run の拒否）: `accept` の順の頭に `halted` の拒否を足した（1 の 5・4.1）。
- 持ち主に聞く「軽量」の件は、答えが来るまで案 1（標準だけ）を仮の裁定にした（13 節・BL27）。

## 改訂 3（再審査 2 回目 `board-layer-rereview2.md` への対応）

- **P1**（並行 PR の任せ先の役の仕事と外への書き込み）: 決めずに持ち主に聞く（13 節の 2。案 (a)(b)(c)）。仮の裁定は「この層は engine_run と任せ先の配管だけ、`p0.parallel_pr` の持ち方は答えの後に線 A・B が決める」（BL28）。1 の 7 に役の仕事（6 段の全部・6 段目が他人の PR への投稿）を事実として足し、8.1・8.2・BL25・11・12 節の「読むだけの役で同じ」を取り下げた。計画の Task 1〜10 は答えに依らない（試験用の表で absent と engine_run の両方を見る）。
- **P2**（任せ先へ落ちた後の古い入れ物）: `run_engine` が読み直した盤面を `self` に入れ直す（4.3 の 7・BL29）。計画の T5 `test_fallback_then_settle_same_board`、T8 `test_begin_without_declaration`。
- **P3**（大きさの見積りに目録が無い）: 目録も Run の頭だけ丸ごと、以後は差分。`steps/*.json` も gzip。見積りを目録の分を含めて 8〜20 MB に直した（上限 30 MB。9.2 の 5）。
- **m8**（`boardreplay` の口）: `memory_at(run_steps, seq, which)` を足し、`board_from_memory` はその返りを受ける（計画 T4a）。
- **m9**（settle しない答え・省く）: 内部の口 `_answer_record`・`_skip_record`（4.1、計画 T6）。
- **m10**（engine_run の節への外からの `done`）: 任せ先に落ちる前は `BoardGap`（1 の 7・4.1、計画 T5 `test_done_on_engine_run_refused`）。
- **m11**（`begin` の後の `ready`・波 0 の古い文）: 5 節を「`ready` の engine_run を全部 `run_engine`、任せ先は表の `fallback` の持ち主が渡す」に直した。`p0.local_checks` の `fallback: machine` で A の `start` が渡す物を 8.1 に書いた。写しの先頭を 1833773 に直し、`parallel-pr.py` は写し済みにした（0 節・1 の 11・4.3・BL25、計画の波 0）。
- **m12**: 4.1 の口の一覧の `run_engine` に `plan=None` を足した。`init` の `die` の文は `util.LAST_DIE` から取る（計画 T2b）。
