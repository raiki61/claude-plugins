# 線 A: darkfactory の 1 回の run を強くする Implementation Plan

状態: 入れた（works 0.2.0）。対応表 `.shared/core/gl_map.json` は 2026-10-09 に外した。

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. 下請けは実装・審査・再審査の全部を opus で回す（台帳 R22）。

**Goal:** darkfactory の 1 回の run（人の依頼 → 判定 → 修正 → 審査 → テスト → 報告を 1 周だけ流す）に、graphloops 0.21.0 の review-graph と同じ工程を足す。判定の前に並行 PR の交差の検査（任せ先は読むだけの役）と前提の実測、修正の前に「修正案 → 事前審査 → 能力を減らす案なら人の関所」、修正の後に機械の数え直しと、修正役の異議を判定役の会話の続きで同じ周に再審する口、差分の審査と手直しの 2 往復、外からの止め札、起動の関所、Claude の包み（起動ごとの柵・読んだ記録・判定役の会話の継ぎ）、読んだ証拠、手厚さの入力（標準だけ）、機械が組む短い報告。盤面は盤面の層（`DiskBoard`）に置き、graphloops の engine と同じ記録を残す。

**Architecture:** ラインは `launch`（起動の関所）→ `start` → ブロック（判定・修正案・修正・中のテスト・審査・手直し・最後のテスト）→ `report`。ブロックの間に**境の節**（`darkfactory/scripts/edge.py`。いつも走る script の節）を置く。境の節は、止め札と関所の答えを盤面に書き、盤面の `ready`（次に待っている節）から「次のブロックを回すか」を 1 つの真偽 `go` で返す。YAML の `when:` と関所の文は境の節の欄だけを読む。役の返答は各ブロックの受け付けが `DiskBoard.done(節, 返答)` で盤面に渡し、機械の節（版を固める・差分を切る・義務を組む・人の関所の項目・周の記録・収束）は盤面の `settle` が engine と同じ順で回す。works が自前で規則を書き直す所は無い。

**Tech Stack:** Archon v0.11.1（固定の実行ファイル）・YAML・Python 3（pack の中は標準ライブラリだけ、テストだけ PyYAML）・uv（script の節）・git・graphloops 0.21.0（a1202d0）の写しと盤面の層（`works/.shared/core/board.py`）。

**Spec:** `works/docs/specs/2026-09-27-darkfactory-single-run-design.md`（改訂 3 まで。以下「仕様 N 節」）。1 版への審査 作業の控え（scratchpad）の `trackA-plan-review.md`（Approve with changes）の直しは末尾の「改訂 2」、持ち主の朝の 4 つの答え（2026-09-27）の直しは末尾の「改訂（持ち主の答え 2026-09-27）」。会話の継ぎの試しは 作業の控え（scratchpad）の `resume-probe-summary.md`（以下〔継試〕）。土台は盤面の層の仕様 `works/docs/specs/2026-09-26-board-layer-design.md`（以下「盤仕様 N 節」）と計画 `works/docs/plans/2026-09-26-board-layer.md`。仕様と計画は Task 1 で `works/docs/specs/2026-09-27-darkfactory-single-run-design.md`・`works/docs/plans/2026-09-27-darkfactory-single-run.md` に置いた。作業の控え（scratchpad） = 設計の会話の一時フォルダ `/private/tmp/claude-1341252503/-Users-p03623-src-claude-plugins-work1/c495892b-6158-4a8d-ad53-ea7a3361cb23/scratchpad`（リポジトリには入っていない）。

## 平易版（3 行）

- darkfactory の 1 回の run に、graphloops の review-graph と同じ「判定の前の前提の実測と並行 PR の検査」「直す前の計画と事前の審査」「直した後の機械の数え直し」「修正役の異議を同じ判定役に同じ周で再審させる口」「審査と手直しの 2 往復」を足し、外から理由つきで止められるようにし、AI が読んだファイルと書いてはいけない場所の柵を記録する。番号は 26 個（Task 10 を 10a・10b に分け、Task 22〜25 を足した）。Task 20 は閉じたので、動く作業は 25 個。うち Task 23（同じ周の再審）は本線の 3-5・3-6 を写し直した後、Task 25（名前を本線に揃える）は本線の 3-7 の後。
- 試験では本物の AI を 1 回も起こさない（お金 0）。AI の返答は固定の見本で差し、Archon は模擬実行だけで回す。本物の AI を使うのは最後の 2 つ（Task 18 の試しと Task 19 の実走）だけで、どちらも持ち主が費用を了承してから撃つ。
- 持ち主の答え（2026-09-27）で、「軽量」は下げない（Task 20 は閉じた）、並行 PR は読むだけの役で申し送りを報告に載せる（Task 21 を普通の作業にした）、前提の実測を足す（Task 22）、同じ周の再審を包みの会話の継ぎで足す（Task 5 と Task 23）と決まった。再審の形は本線の 3-6（3 往復）に揃え、写し直しの後に入れる（回す側の指示）。

## 前提（着手の時に 1 度だけ確かめる）

- 盤面の層の計画の Task 1〜10 が枝 `wip/works-board` に入っている。特に次の口がある: `DiskBoard.begin`・`open(allow_halted=, overrides=, validator_runner=)`・`accept`・`done`・`run_engine`・`settle`・`answer`・`stop`・`finalize`・`run_validator`・`work`、`Progress`、`NodeTable.load`・`check`、`BoardGap`・`BoardMismatch`・`RecordInvalid`、写しの `report_accepts`・`AnswerReject`、`base_output`、`accept.py` の移し替え（`DiskBoard.scratch`）。2026-09-27 の時点で Task 6 まで済んだ（97a8ee7。`RecordInvalid` の直し 18e37a2）。`begin`・`base_output` は盤面の層の Task 8 で、まだ無い（この計画の `begin` の引数は、盤面の層の計画 Task 8 の宣言と同じ）。着手は盤面の層の Task 10 の後。
- 枝と置き場: `wip/works-board` の先頭から枝 `wip/works-single` を worktree `/Users/p03623/src/claude-plugins-work1-single` に切る:
  `git -C /Users/p03623/src/claude-plugins-work1-board worktree add /Users/p03623/src/claude-plugins-work1-single -b wip/works-single wip/works-board`
- 以下の Run はどれも `cd /Users/p03623/src/claude-plugins-work1-single &&` を頭に付けて打つ。
- 線 B（周の輪）は枝を別に持ち、`darkfactory-rounds/` に周の輪のラインを作る（台帳 R25）。線 B は `blk-judge` の判定 v2 に着手する前に、この計画の Task 2 を待つ（盤仕様 6 節「A が波 1 に 1 度」）。

## Global Constraints

- **AI の役は既定の opus で回る**。YAML に `model:` を書かない（台帳 R18・R22・R28）。開発の殻は opus に固定済み（481ab9d）。
- **試験で本物の AI を起こさない**（お金 0）。役の返答は `tests/replies/` の見本と模擬実行の stub で差す。`archon workflow run` を `--dry-run` 無しで打つのは Task 18・19 だけ。
- **費用の了承が要る作業は 2 つだけ**（持ち主に聞いてから撃つ。了承が無ければ飛ばし、その下の予備の道で終える）:
  - Task 18 の試し P13（`tool_called` の Read に `file_path` が載るか）・P14（包みの柵が Edit・Write にも効くか）・P15（包みのプロセスグループで claude の孫まで止まるか）と P11 の AI の節の分。見込みは合わせて 1 ドル未満（名目）。
  - Task 19 の実走。見込みは opus で 2 回・合わせて 3 ドル以下（名目。仕様 9.4）。
- **P13・P14・P15 の結果に頼る所は、結果が出る前でも動く形で作る**（予備の道を先に作り、結果で強い側へ切り替える）:
  - P13 が不可なら、読んだ証拠の出どころは包みのフックだけ（`sources.events: false` を報告の冒頭に出す）。
  - P14 が不可なら、柵は「Archon の sandbox だけ」と報告の冒頭に出す（包みの `denyWrite` を記録だけに下げる）。
  - P15 が不可なら、取り消し（`cancel`）は「非常用・子が残りうる」と SKILL に書き、止め札を普段の道にする。
- **pack の中の Python は標準ライブラリだけ**。`*/scripts/*.py` の頭はちょうど次の 4 行（`test_script_headers.py` が見る）: `# /// script`・`# requires-python = ">=3.10"`・`# dependencies = []`・`# ///`。前置きは v1 と同じ（`sys.dont_write_bytecode = True` の後に `.shared/core` を `sys.path` の 0 番へ。台帳 R7）。包み（`.shared/core/claude-adapter`）だけは uv を通さない `#!/usr/bin/env python3` で、名前を `.js` で終わらせない。
- **期限**: script・bash の節は `timeout: 1728000000`、AI の節は `idle_timeout: 1728000000`。これ以外の期限を足さない（`subprocess` の `timeout=` も使わない）。止める時の猶予は既存の `tree_run.KILL_GRACE`（2 秒。台帳 R31）を使い、新しい値を作らない。試験の中の「孫が消えるまで待つ上限」は試験の外を縛らないので対象外。
- **写し（`works/.shared/core/graphloops/**`・`works/.shared/core/scripts/**`・`COPIED_FROM`）は 1 バイトも変えない**（盤仕様 BL2）。規則を直したくなったら、盤面の層の `overrides` を使う（この計画では使う所が無い）。`board.py`・`accept.py` も触らない（盤面の層の持ち物。読む・import するのはよい）。
- **決め方の方針**（台帳 Owner policy）: review-graph（0.21.0）と比べて同等以上になる物は推しで決めて先へ進む。能力が下がる物だけを持ち主に聞く（費用と外への書き込みは前と同じく聞く）。この計画の中で決めた物は「裁定」TA1〜TA14 に書いた。
- **持ち物**（盤仕様 6 節の表のとおり）:
  - 線 A だけが触る: `darkfactory/**`（`nodes.json`・`downgrades.json` を含む）・`blk-plan/**`・`blk-refix/**`・`blk-premises/**`・`blk-rejudge/**`・`blk-pr/**`・`blk-fix/**`・`blk-delta/**`・`blk-tests/**`・`.shared/core/{claude-adapter,adapter.py,record-read.py}`・`dev/stop.sh`・`dev/report.sh`・`.shared/core/{recount,halt,reads,plan,refix,entry,policy,report,ticket,node_marker,premises,rejudge,prcheck}.py`・`.shared/core/gl_map.json`（線 B は自分の行を線 B の最後の共有の commit で足す）・`tests/replies/fix2_*`・`tests/replies/plan*`・`tests/replies/premises_*`・`tests/replies/rejudge_*`・`tests/replies/pr_*`。
  - 線 A の新しい試験のファイル（盤仕様の表に名前が無いが、他の線と重ならない名前）: `tests/test_entry.py`・`test_ticket.py`・`test_adapter.py`・`test_reads.py`・`test_halt.py`・`test_policy.py`・`test_node_marker.py`・`test_blk_plan.py`・`test_blk_refix.py`・`test_blk_premises.py`・`test_blk_rejudge.py`・`test_blk_pr.py`・`test_report.py`・`test_line_a.py`・`test_gl_map.py`・`tests/linekit.py`・`tests/adapter/**`・`tests/events/**`。v1 の試験のうち線 A のブロックを見る `tests/test_blk_fix.py`・`tests/test_blk_tests_delta.py` も線 A が直す。
  - 線 B の物に 1 度だけ触る: `blk-judge/blk-judge.yaml`（入力 `policy_paste`・`premises_file` を足し、判定役の `output_format` に印 `works-node: judge` を付ける）と `blk-judge/commands/diagnose.md`（その 2 つの入力を読む 2 段落）と `tests/test_blk_judge.py`（`output_format` を比べる試験 1 つを、印を外して比べる形にする）。Task 2 の 1 commit だけ。
  - **共有のファイルは Task 17 の 1 commit でだけ触る**: `tests/test_yaml_rules.py`・`tests/yaml_good/**`・`tests/yaml_bad/**`・`tests/test_line.py`・`tests/test_script_headers.py`・`tests/run.sh`・`dev/check.sh`・`dev/mktarget.sh`・`dev/real-run.sh`・`dev/archon.sh`・`dev/guard.sh`・`skills/works/SKILL.md`・`README.md`・`archon-plugin.json`・`docs/specs/2026-09-26-darkfactory-design.md`（冒頭の 1 行）。
  - 触らない: `blk-judge/`（Task 2 の 2 ファイルを除く）・`darkfactory-rounds/**`・`blk-close/**`・`mutgate/**`・`blk-mut-triage/**`・`.shared/core/{board,accept,script_io,tree_run,rounds,judge2,close,mutcore}.py`・盤面の層の試験（`test_board*.py`・`test_core_verbatim.py`・`test_accept_v1_golden.py`・`boardreplay.py`・`tests/boards/**`）・`tests/replies/` の v1 の見本（読むのはよい）。
- **途中の commit の決まり**（裁定 TA2）: ブロックの YAML と線の YAML を新しい形へ替えるのは Task 17 の 1 commit だけ。それまでの Task は、スクリプト・モジュール・指示書・線 A の試験と、今の共有の試験で通る YAML（`blk-plan`）だけを commit する。途中の commit でも `works/tests/run.sh` と `works/dev/check.sh` は緑。ただし Task 12〜15 の後は、1 本目のラインを本物で走らせると盤面が無くて止まる（ブロックの受け付けが盤面を要るため）。途中の枝で実走しない。
- **関所**: `decisions` を持つ関所は `approve`・`continue`・`stop`・`reject` の 4 つを持ち、`approve` は `continue` と、`reject` は `stop` と同じに扱う（台帳 R32、試し P8・P16）。起動の関所 `launch` は `decisions` を持たない（まだ何も走っていないので `reject` で取り消されてよい）。
- **飛ばされうる節の読み方**（試し P7・P16）: `when:` と関所の文と bash の本文は、いつも走る節（`start`・境の節）の欄だけを読む。script の節が飛ばされうる節を読むときは `{from: "$x.output", if_skipped: null}` で受け、届く値は文字列 `null` を「開かなかった」と読む。
- **ブロックは周の番号を仮定しない**（線 B の約束 2。裁定 TA17）。作業ファイルは `b.work(名)`（今の周の `r<N>/`）、役の出力のパスは `state.outputs[節]["file"]`、engine が走らせた節のログは `run_engine` の返り（`runs[].out`・`err`）から引く。`r1/`・`out/r1/`・`runs/r1/` をコードにも試験の期待にも書かない（試験は周 2 の盤面でも 1 本ずつ回す）。
- **ブロックの既定の動きは 1 本目と同じに保つ**（裁定 TA4・I1）。特に `blk-tests` は線 C の `mutgate` が `include: blk-tests`・`with: {cmd}` だけで使う（盤面なし・`cmd` 必須・ログは `board/tests.log`・出口 `{ok, green, log}`）。新しい動きは明示の入力（`mode: mid`・`final`）の後ろだけに置き、既定（`mode: plain`）は変えない。
- **スクリプトが読む環境変数は定数に置く**（裁定 TA16）。各 script（`start.py`・`edge.py`・`report.py`・ブロックの受け付けと集める節）は、読む `INPUTS_*` の名前の組を `INPUTS = (...)` の定数に持つ。Task 17 の試験が YAML の `with:` の鍵と突き合わせる。
- 盤面に書くのは `DiskBoard` の口を通してだけ。works が自分で書く作業ファイルは `b.work(名)`（`r<N>/`）と、盤仕様 3 節で線 A に予約された名前（`STOP`・`launches.jsonl`・`report.md`・`next-request.json`）だけ。書くときは一時ファイルから `os.replace`、JSON は `ensure_ascii=False`。
- 受け付けのスクリプトは、役の返答の中身の誤り（写しの `AnswerReject`）だけを終了コード 0 の `{"ok": false, "reason": …}` 1 行で役に返す。止めた run への書き込みなど、ほかの `Reject` と `BoardGap` は回す側の誤りとして終了コード 2（裁定 TA19。engine の `cmd_done` と同じ分け方）。入力が読めないときも 2。拒まれた `DiskBoard` の入れ物は捨てる（盤仕様 4.1）。
- **`accept.py` に検査を足さない**（TA25）。works だけの検査はブロックの受け付けのスクリプトに置き、Task 24 の対応表に載せる。
- 止める時の猶予は works の 2 秒（`tree_run.KILL_GRACE`）のまま。本線は猶予を呼ぶ側が選べる形（既定 5 秒）にする予定だが、Archon の取り消しの猶予 5 秒より短くするため、works は 2 秒を持つ（渡す）。
- `__pycache__` を作らない（テストは `PYTHONDONTWRITEBYTECODE=1`）。テストは `nice -n 19` で前景。プロセスを止めるときは pid と cwd を確かめ、`pkill -f` を使わない。使い捨ての対象・開発の家・切符の置き場を `/private/tmp/claude-*` の下に置かない（`${WORKS_DEV_HOME:-$HOME/.cache/works-dev}` の下）。
- unittest の `-k` は 1 つの語ずつ渡す（`-k 'a or b'` は 0 件に当たる。線 C の審査 I2）。複数なら `-k a -k b`。
- commit の末尾に `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`。push・tag・merge はしない。台帳（`.superpowers/`）は触らない（裁定の写しは持ち主の会話の側が行う）。
- 持ち主の答え（2026-09-27）の後: Task 20 は閉じた（作業なし。拒否の文の直しは Task 7 に入れた）。Task 21・22 は普通の作業としてこの枝の中で行う（共有のファイルに触る所は Task 17 の 1 commit へ回す）。Task 23（写し直しの後）と Task 25（本線の 3-7 の後）は Task 17 より後になるので、各々の最後の 1 commit でだけ共有に触る。M11 の「別の枝」は取り下げた。
- **役の節の `output_format` には印を付ける**（裁定 TA20）。`node_marker.mark(role_schema(節), 名[, cont=…][, flags=…])` の値を貼り、試験は `node_marker.strip` で外してから graph の schema と比べる。

## Review Focus（噛みつきやすい入力の 5 つの種類）

1. **人の答えの形**: 関所の出力が文字列 `null`（関所が開かなかった）、`approve`・`continue`・`stop`・`reject` のどれか、一言に引用符・改行・`$(`・日本語が入る。→ `approve`/`continue` は同じ、`reject`/`stop` は同じ。一言は盤面の `process.human_items` と報告に 1 バイトも変わらずに届く。`null` を答えと取り違えない（Task 10a `test_gate_null_means_not_opened`・`test_gate_note_roundtrip`・`test_reject_is_stop`）。
2. **判定の渡し替え**: 1 本目の受け付けが通した `judgment.json` を、盤面の受け付け（`check_record`・番号の読み替えを含む）が拒む。線 B の判定 v2 が入った後で、盤面に `p2.diagnose` が既に在る。→ 拒まれたら書く役を起こす前に理由つきで止まり報告が出る。既に在れば 2 度受けない（Task 10b `test_bridge_rejected_stops_before_writer`・`test_bridge_skips_when_done`）。
3. **対象のテストの宣言**: `.review-checks.json` が無い（`test_cmd` だけ）・在るが読めない・計画の後に中身が変わる・どちらも無い。→ 無いときは `by: "role"` を記録して `test_cmd` を走らせる。読めないときは engine と同じく走らせずに返答を組む。変わったら走らせずに計画し直す。どちらも無ければ AI を起こす前に `start` が止める。線 C の `mutgate` のように `cmd` だけを渡す include は、盤面なしの 1 本目の動きのまま（Task 7 `test_start_refuses_no_tests`、Task 14 `test_final_declaration_changed_relaunches`・`test_plain_mode_is_mutgate_contract`）。
4. **止め札の時機と中身**: 理由が空・空白だけ、2 度目の止め札、ブロックの出し直しの輪の途中で置く、関所の `stop` と同じ run に止め札も在る。→ 理由の無い止め札は置かれない。最初の理由が正で、後の理由は trace にだけ残る。次の境の節で必ず止まり、`report` が走る（Task 8、Task 10a `test_stop_flag_and_gate_stop_first_wins`・`test_stop_flag_after_halt_goes_to_trace`）。
5. **包みが受ける引数と切符**: `--settings` の 3 つの綴り（`--settings <JSON>`・`--settings=<JSON>`・ファイルのパス）、`--settings` が 2 つ、壊れた JSON、切符が無い・別の run の切符。→ 見分けられない物は 1 バイトも変えずに素通しし、理由を `launches.jsonl` に書く。この run の役の起動が包みを通っていなければ、書く役を起こす前に止める（`adapter: optional` のときだけ通して報告に出す）（Task 5、Task 10b `test_adapter_missing_stops_before_writer`）。
6. **会話の継ぎ**: `--json-schema` の 2 つの綴り・印の無い起動（題の生成の `--tools ""`）・SDK が既に `--resume` か `--session-id` を付けた判定役の起動（線 B の判定の 2 回目）・`continue` の先の id が無い・切符が無い起動。→ 印の無い起動は 1 バイトも変えない。判定役は SDK の id をそのまま記録し、無い時だけ包みが作る。`continue` は SDK の 5 つの旗を外して `--resume <id>`、id が無ければ子を起こさず exit 3。切符が無くても継ぐ（Task 5 `test_continue_missing_id_fails_closed`・`test_session_splice_in_passthrough`、Task 23 `test_precheck_stops_before_role`）。

## 裁定（仕様との差。能力は review-graph 0.21.0 の同じ所と比べた）

- **TA1 ラインの `when:` は境の節の欄だけを読む**。境の節は盤面の `ready` から `go` を決める。ブロックの出口の欄で分けない（仕様 2 節の「ブロックの出口の欄を比べる」を改める）。理由: 盤面が正本で、飛ばされうる節の欄を読んで落ちる道（試し P7）が無くなる。能力: 同じ（分かれ道は engine の条件そのもの）。
- **TA2 YAML の切り替えは最後の 1 commit**（Task 17）。盤仕様 6 節の「共有のファイルは各線の最後の 1 commit」と、1 本目の試験 `test_line.py` が 1 本目のラインの形と役の見本を縛っていることから、ブロックの YAML を途中で替えると共有の試験が赤になる。途中は線 A の試験だけで確かめ、Task 16 で Archon を使わずにスクリプトを線の順に回す通しの試験を置いて、切り替えの前に全部の道を通す。能力: 同じ。
- **TA3 判定は盤面へ渡し替える**（境の節 `h-plan`）。`blk-judge` は線 B の持ち物で、今は 1 本目の受け付け（偽の盤面）で受ける。`h-plan` が受け付けた `judgment.json` を `done("p2.diagnose", …)` で盤面に渡す。盤面に既に在れば渡さない（線 B の判定 v2 が盤面で受けた後でも動く）。拒まれたら書く役の前で止める。能力: 同じ（同じ規則を 2 度当てるだけ）。
- **TA4 1 本目の中の関所（テストの後・審査の前）は残す**（台帳 R26）。入力 `mid_gate`（`always`・`when_needed`、既定 `always`）。`when_needed` は中のテストが赤か走れなかった時だけ開く。関所の前に、修正の後のテストを 1 度走らせる（ブロック `blk-tests` の `mode: mid`。盤面の `p4.ci` とは別で、盤面の節に書かない）。`blk-tests` の既定は `mode: plain`（1 本目と同じ。盤面なし・`cmd` 必須・`board/tests.log`）のままにし、線 C の `mutgate` の include を変えない（審査 I1）。能力: 上（review-graph に無い止める所を 1 本目から残す）。
- **TA5 最後のテストは盤面の `run_engine("p4.ci")`**（盤仕様 8.1。`blk-tests` の `mode: final` を線 A のラインが明示で渡す）。宣言が無く任せ先に落ちたら、`test_cmd` を走らせた結果を `done("p4.ci", …)` で渡す（表の `fallback: machine`）。能力: 同じ（宣言が在れば `by: "engine"`）。
- **TA6 直す物が無い判定の run も周を締める**。`p2.fix_plan` が条件で `na` になった run では、境の節が「直す義務 0 件」の `p3.fix` の空の返答を機械で渡し、盤面が差分の審査を `na` にし、最後のテスト・周の記録と検証器・収束まで回す。結末は `no_fix_needed` のまま。1 本目は修正から後を全部飛ばしていた（台帳 R21）。能力: 上（review-graph と同じく周の記録と検証器を通る。1 本目より最後のテストが 1 回増える）。
- **TA7 手厚さは「標準」だけを受ける**（持ち主の決定 2026-09-27: 案 1。graph で optional でない節は省かない）。`軽量` は「軽量は受けない: graph で省けない節を省くことになる（持ち主の決定 2026-09-27）」、`重厚` は「重厚で足す工程がまだ無い」の 1 行で、`start` が AI を起こす前に止める。入力 `thickness` は記録に残す。省く配管（`downgrade`）は作らない。効かない入力になる `thickness_decider` は置かない（1 版から消した）。Task 20 は閉じた。能力: 同じ。
- **TA8 `p0.parallel_pr` は `engine_run`・`fallback: role`**（持ち主の決定 2026-09-27: 案 (a)。盤仕様 BL25・BL28）。`start` が engine で 1〜5 段を走らせ、任せ先に落ちた時だけ読むだけの opus の役（`blk-pr`）が 6 段をする。6 段目は申し送りの下書きを `conflicts[].note` に書き `handed_over: false`（真は受け付けが拒む）。下書きは報告の冒頭 1、下げた事実は `darkfactory/downgrades.json` と報告の冒頭 2 と仕様 10 節の表。Task 3 の間は absent（理由「線 A Task 21 で入る」）で、Task 21 が行を替える。能力: 交差の検査は同じ、申し送りの投稿だけ下（持ち主が選んだ・黙らない）。
- **TA9 包みの有無は、判定の前の境の節 `h-judge` が見る**（1 版は `h-plan`。Task 22 で移す）。前提の役と並行 PR の任せ先の役（Bash を持つが読むだけ。作業ツリーの写しで確かめる）は包みの確かめより先に走るが、判定役と書く役は必ず確かめた後に走る。この run の役の起動が `launches.jsonl` に無く、入力 `adapter` が `optional` でなければ、`h-judge` が理由つきで止める（台帳の決定「包みの無い run は既定で拒む」）。能力: 同じ（柵が要るのは書く役）。
- **TA10 方針の文書は、ブロックの入力で役に届ける**。`start` が盤面の固めた写し（`process.policy.copy`）から、貼る文（`policy_paste`。4 万バイトまで、超えたら先頭と続きのパス）と、パス（`policy_path`）を組む。読む役（判定・事前審査・審査）には貼り、書く役（修正案・修正・手直し）にはパスを渡す（0.21.0 と同じ）。`blk-judge` には節を足さず、入力 1 つと指示書の 1 段落だけを足す（仕様 3.1・8 節の「`brief` の節」を改める。1 本目のラインと `test_line.py` を壊さないため）。能力: 同じ。
- **TA11 読むだけの役の「作業ツリーを変えていない」検査は 1 本目の写しを残す**（台帳 R14）。盤面の受け付けは役の起動の前後の突合を持たない（盤仕様 9.3 の比べない欄 `tree_before`）ので、修正案・事前審査・審査・2 回目の審査の受け付けは、1 本目と同じ `accept.snapshot_tree` の比べを盤面に渡す前に行う。能力: 同じ。
- **TA12 報告の結末の語を足す**: `fixed`・`no_fix_needed`（1 本目と同じ）に、`stopped_by_request`（止め札）・`stopped_by_human`（関所の `stop`・`reject`）・`stopped_by_line`（包みが無い・判定の渡し替えが拒まれた、など機械が止めた）・`needs_human`（最後に盤面が人に聞いたまま終わった。例: run の途中で方針の文書が変わり R4 の関所が開いた）・`record_invalid`（記録が報告の前の検証器を通らない、か周の記録が組めなかった。TA15）・`interrupted`（取り消し・`abandon`・役の出し直しの上限で run が落ち、`dev/report.sh` で後から作った報告）を足す。1 本目の出口の欄は全部残す（上位互換。台帳の持ち主の条件）。
- **TA13 AI の役の順は「役はその出し直しの輪の中のただ 1 つの AI の節」**。1 つのブロックに役の輪が 2 つ以上並ぶ（`blk-plan` に 2 つ、`blk-refix` に 3 つ）。Archon は輪の 1 回目をいつも新しい会話で起こす（dag-executor.ts:5069。`test_yaml_rules.py` の注記）ので、前の輪の会話を引き継がない。共有の試験の「ブロックの中で役より前に AI の節が無い」を、Task 17 で「役は自分の輪のただ 1 つの AI の節で、輪の外の AI の節は `context: fresh` を持つ」に替える。能力: 同じ（graphloops の `fresh_context: true` に当たる）。
- **TA15 報告の前に必ず検証器を通す**（審査 I3）。表で `report` を absent にするので、盤面の `settle` は graph の `report` の `pre: finalize` の関所（`_pre_finalize` → `RecordInvalid`）に届かない。そこで `report.build` が engine の `loop.py finalize` と同じ順を自分で踏む: `settle`（止めた盤面は飛ばす）→ `finalize()` → `run_validator()`（盤面の口。線 B の包みも効く）→ 終了コードが `report_accepts` に入るか。入らない・`p4.record` か `converge` が今の周に済んでいない（止めた run と直す物の無い周を除く）なら、結末は `record_invalid` で、冒頭 1 に検証器の出力の末尾と記録の痕跡の欄（`traces`）を出す。**どの道も、記録が検証器を通らない run に `fixed`・`no_fix_needed` を出さない**。能力: 同じ（engine の `cmd_finalize` と同じ関所）。
- **TA16 YAML とスクリプトの配線を機械で縛る**（審査 I4）。各 script は読む `INPUTS_*` を定数 `INPUTS` に持ち、Task 17 の試験が「YAML のその節の `with:` の鍵 ＝ 定数」を全部の script の節で見る。Task 16 の `run_line` は同じ定数と、YAML から読んだ節の順を使う（手で書き写さない）。模擬実行の筋書きのうち 2 本（`standard`・`start-refused`）は `start` を stub せずに本物で回し、`with:` が届くことを 1 本目の `finish` と同じく模擬実行で見る。能力: 同じ〜上。
- **TA17 ブロックは周の番号を仮定しない**（審査 I2。線 B の約束 2）。Global Constraints のとおり。能力: 同じ（線 B が同じブロックを周 2 以上で使える）。
- **TA18 線 B の申し送り 1〜4 を入れる**（審査 I2。線 B の仕様 5 節）: 1. `entry.open_board` がラインの置き場の `board_hook.py`（`board_kwargs(table) -> dict`）が在れば読み、`overrides`・`validator_runner` を `DiskBoard.open` に渡す（Task 3）。2. 修正前の CI の任せ先の素材を組む関数を `entry.local_checks_material` として `start` の外から呼べる口にする（Task 7）。3. 報告の部品（読んだ証拠と包みの行・見る所の行・このラインに無い節の行）を `report.py` の関数にする（Task 15）。4. Task 2 の試験は「`policy_paste` の入口が在り、指示書が読む」だけを見る（線 B の判定 v2 が `intake` を消しても赤にならない）。線 A の筋書きも `judging` の中の節を名指しで stub しない（`judging__collect` の出口だけを差す）。能力: 同じ。
- **TA19 役に返すのは中身の誤りだけ**（審査 M2）。`take` は写しの `AnswerReject` だけを `{ok: false}` で役に返し、止めた run への書き込みなどほかの `Reject` と `BoardGap` は終了コード 2 で回す側へ上げる（engine と同じ分け方）。能力: 同じ。
- **TA14 前提 `p0.premises` は線 A に入れ、目的 `p0.purpose` は線 B に入れる**（持ち主の決定 2026-09-27）。前提は判定の前のブロック `blk-premises`（Task 22。写しの schema と `measured_needs_output` に、依頼の `measured` の測り直しの検査 `request_claims_covered` を足す）。目的の文は線 A の表で absent のまま（理由「目的の文は線 B の blk-purpose で入る。線 A のラインへの取り込みは未定」）。Task 3 の間は `p0.premises` も absent（理由「線 A Task 22 で入る」）で、Task 22 が行を替える。能力: 前提は同じ〜上、目的の文は下（黙らない）。
- **TA20 役の節は印を持つ**（〔継試〕）。`output_format` の一番上の `description` に `works-node: <名>[ continue=<名>][ no-post]`。作るのは `.shared/core/node_marker.py`（Task 2）。包みは argv の `--json-schema` から読み、印の無い起動には触らない。能力: 同じ（graph の schema の中身は変えない）。
- **TA21 同じ周の再審は包みで判定役の会話を継ぎ、形は本線の 3-6 にする**（持ち主の決定 2026-09-27。〔継試〕。形は回す側の指示 2026-09-27、〔本〕3.3）。判定役は包みが作る `--session-id` で起こし（SDK が付けた id が在ればそれ）、`adapter.session_path(cwd, "judge")` に記録する。再審 `rejudge`・`rejudge2`・`rejudge3`（印 `continue=judge`・YAML は `context: fresh`）は SDK の会話の旗を外して `--resume <id>`。id が無ければ包みは exit 3（fail closed）。修正役の再異議 `rejudge-reply`・`rejudge-reply2` と第三の目 `rejudge-third` は新しい会話。どの節を何回回すかは盤面の ready（3-6 の写しの `rejudge*_open`・`rejudge_reply*_due`・`rejudge_exhausted`・`REJUDGE_PASSES`）が決める。0.21.0 の形（2 節）は第三の目が立たない穴があるので写さず、**再審は写し直しの後に入れる**（Task 23 は「写し直しへの依存」の後）。包みの会話の継ぎ（Task 5）は写しに依らないので先に作る。能力: 写し直しの後に上（0.21.0 の review-graph は 1 往復で止まる）。それまでは absent（下・宣言）。
- **TA22 会話の id が無い時は、役を起こす前に止めて聞く**。境の節 `h-rejudge` が `session_path` を確かめ、無ければ `b.stop(…, by="works:rejudge-session")` と報告の冒頭 1 の問い、異議は `next-request.json` へ。包みの exit 3 だと Archon が約 12 回・約 40 秒起こし直す（AI の費用 0）ので、そこへ行かせない。能力: 条件付き（id が在る限り同じ。無い時は下がるが黙らない）。
- **TA23 再審で判定役はどの単位も変えてよい**（柵を足さない）。受け付けの後に前後の単位を比べ、争点（その回の異議の文に key が現れる単位）でない単位の変化を `rejudge-diff.json`（往復ごとに 1 行）と報告の冒頭 1 に出す。能力: 上（review-graph は出さない）。
- **TA25 受け付けの口は本線の 3-8 まで `accept.py` のまま、works だけの検査はブロックのスクリプトに置く**（回す側の指示 2026-09-27。本線からの知らせ: `gl.py` はまだ `accept.py` を置き換えられない）。`accept.py`（盤面の層の持ち物）に検査を足さない。works だけの検査（依頼の実測の測り直し `check_claims`・申し送りを投稿しない `check_no_post`）は、そのブロックの受け付けのスクリプト（`blk-premises/scripts/accept.py`・`blk-pr/scripts/accept.py`）に置く。読むだけの役の作業ツリーの確かめ（TA11）は `accept.snapshot_tree` を読むだけ。`accept.py` から `gl.py` への対応表は Task 24（`gl` に足りない 4 つ: 依頼に依らない検査の口・役の schema から注記を外す口・判定の受け付け・差分を切る段）。能力: 同じ。
- **TA26 ブロックの名前と `where` は今は works の仮の名、本線の 3-7 が来たら揃える**（回す側の指示 2026-09-27）。本線のブロックの置き場と名前は 3-7 が落ち着いてから決まる。今は works の名（`blk-plan`・`blk-refix`・`blk-premises`・`blk-pr`・`blk-rejudge`）で作り、節の表の `where` も works の置き場だけを書く。3-7 が版に入ったら、名前と `where` を揃える小さな作業（Task 25）をする。能力: 同じ。
- **TA24 費用は継いだ起動の分を引いて出す**（〔継試〕: 再開した会話の `total_cost_usd` は累積で、Archon の節の費用の表示は判定役の分を重ねる）。報告の費用の行は、`launches.jsonl` の `session.mode == "continued"` の起動について、同じ会話の直前の起動の表示を引く。費用が出来事から取れなければその 1 行（P19）。能力: 同じ（数え方の誤りを報告で直すだけ）。

## 並べ方

```
波 1:  T1 仕様と計画を置く
波 2:  T2 blk-judge に方針の入力（線 B の着手の前）─┬─ T3 節の表 ─┬─ T4 切符 ─┬─ T8 止め札      （4 つ並べてよい）
波 3:  T5 Claude の包み（T4 の後）
波 4:  T6 読んだ証拠（T5 の後）─┬─ T7 start（T3・T4 の後）
波 5:  T9 盤面に受ける口（T7 の後）
波 6:  T10a 境の節の芯（T8・T9 の後）→ T10b h-plan の仕事（T6・T10a の後）
波 7:  T11 blk-plan ─┬─ T12 blk-fix ─┬─ T13 blk-delta と blk-refix ─┬─ T14 blk-tests   （T9・T6 の後。4 つ並べてよい）
       T21 並行 PR（T9・T10b の後）→ T22 前提（T21 の後）   （この 2 つは直列。T11〜T14 とは並べてよい）
波 8:  T15 報告（T10a〜T14・T21・T22 の後）─┬─ T24 accept.py から gl への対応表（いつでも。文書と試験だけ）
波 9:  T16 通しの試験（全部の後）
波 10: T17 切り替え（YAML・筋書き・共有のファイル。線 A の切り替えの共有の commit）
波 11: T18 AI の試し（費用の了承）─┬─ T19 実走（費用の了承。T18 の後）
------ 本線の 3-5・3-6 が版に入り、写し直しの線が写し直した後（「写し直しへの依存」）------
波 12: T23 同じ周の再審（本線 3-6 の形。T5・T12・T22 と写し直しの後。最後の 1 commit で共有に触る）
------ 本線の 3-7（ブロックの宣言）が版に入った後 ------
波 13: T25 ブロックの名前と where を本線に揃える（小さな作業。最後の 1 commit で共有に触る）
閉じた: T20 軽量（持ち主の答え: 下げない。作業なし）
```

- `.shared/core/entry.py` を触るのは T3・T7・T9・T21 で、この順に直列。`halt.py` は T8・T10a・T10b・T22・T23。`darkfactory/nodes.json` は T3・T21・T22・T23・T25。`ticket.py` は T4・T5。`.shared/core/{claude-adapter,adapter.py,record-read.py}` は T5 だけ（T21 の `no-post` の柵も T5 で作る）。`reads.py` は T6 だけ（T10b は読むだけ）。T21・T22 が直列なのは、この 2 つが `entry.py`・`nodes.json` を同じ順で足すため。T23・T25 は写し直し・3-7 を待つので、切り替え（T17）の後になる。並べた物は各々の worktree で回し、審査の後に cherry-pick する（台帳 R6・R8）。
- `tests/linekit.py`（試験の手助け）を作るのは T3。後の Task は足すだけ（関数を消さない・引数を変えない）。並べた Task が同時に足すときは、cherry-pick の時に並べ直す。

## 盤面の上の線 A のファイル（`$B` = `$ARTIFACTS_DIR/board`）

- 盤面の層が持つ物（線 A は `DiskBoard` の口で読み書きする）: `state.json`・`record.json`・`trace.jsonl`・`out/r<N>/*.json`・`rounds/`・`policy/`・`runs/`・`reads.jsonl`（包みのフックが書き、RL の `hook_evidence` が読む）。
- 線 A に予約された名前（盤仕様 3 節）: `$B/STOP`（T8）・`$B/launches.jsonl`（T5）・`$B/report.md`・`$B/next-request.json`（T15）。
- 線 A の作業ファイル（`b.work(名)` = 今の周の `$B/r<N>/<名>`。周の番号をコードに書かない。TA17）: `start.json`（T7）・`gate.md`（T10a）・`mid-gate.md`・`mid-gate-answer.json`（T10a）・`plan-snapshot.json`・`review-snapshot.json`（T11）・`review1-snapshot.json`・`review2-snapshot.json`（T13）・`reads-<役>.json`（T6）・`mid-tests.log`・`mid-tests.json`（T14）・`changes.json`（T12）・`pr-snapshot.json`（T21）・`premises-snapshot.json`（T22）・`rejudge-snapshot.json`・`third-snapshot.json`・`rejudge-brief.json`・`rejudge-units-before.json`・`rejudge-diff.json`（T23）。
- 盤面の外の置き場（包みの家 `ticket.home()` の下。T5）: `sessions/<cwd の realpath の sha256 の先頭 16 字>/<節の名>.id`（判定役ほか印を持つ役の会話 id）。役の出力（`p2.fix_plan`・`p3.fix`・`p3.delta_review` など）は盤面の `state.outputs[節]["file"]` から引き、works は写しを作らない。
- 1 本目と同じ置き場: `$B/tests.log`（`blk-tests` の既定の `mode: plain`。線 C の `mutgate` の約束。TA4）。
- 1 本目の受け付けが書く物（Task 17 まで動かさない。盤仕様 BL8）: `request.json`・`judge-snapshot.json`・`judgment.json`（判定は線 B の持ち物のまま、1 本目の受け付けが書く）。

---

### Task 1: 仕様と計画を置く

**Files:**
- Create: `works/docs/specs/2026-09-27-darkfactory-single-run-design.md`（`works/docs/specs/2026-09-27-darkfactory-single-run-design.md` を置く。作業の控えを指す出典は「作業の控え（scratchpad）の …」と書く）
- Create: `works/docs/plans/2026-09-27-darkfactory-single-run.md`（この計画を置く）

**Interfaces:** 無し（文書だけ）。

- [ ] **Step 1: 置く** — 2 つのファイルを写す。仕様の冒頭の「状態」から「下書き N 版」の札を外し、計画と同じ commit で置いたと書く。
- [ ] **Step 2: 確かめる** — Run: `nice -n 19 sh works/tests/run.sh` / Expected: `OK`（文書だけなので数は前と同じ）
- [ ] **Step 3: Commit** — `git commit -m "docs(works): 1 回の run を強くする線 A の設計と実装計画を置く"`

---

### Task 2: blk-judge に方針と前提の入力と、判定役の印を足す（線 B の着手の前。並べてよい: T3・T4・T8）

線 B の持ち物に線 A が触る唯一の commit（盤仕様 6 節「A が波 1 に 1 度」）。節は足さない（裁定 TA10）。印は、線 A の再審（Task 23）が判定役の会話を継ぐのに要る（TA20・TA21）。線 B の判定 v2 の前でも継げるように、ここで付ける。

**Files:**
- Create: `works/.shared/core/node_marker.py`
- Modify: `works/blk-judge/blk-judge.yaml`（入力 `policy_paste`・`premises_file` を足す。どちらも `default: ""`。判定役 `judge` の `output_format` を `node_marker.mark(role_schema("p2.diagnose"), "judge")` の値にする）
- Modify: `works/blk-judge/commands/diagnose.md`（2 つの入力を読む 2 段落を足す）
- Modify: `works/tests/test_blk_judge.py`（`test_judge_output_format_matches_role_schema` の 1 つだけを、`node_marker.strip` で外して比べる形にする。ほかの試験は触らない）
- Test: `works/tests/test_policy.py`（この Task では blk-judge の分だけ）・`works/tests/test_node_marker.py`

**Interfaces:**
- Produces（`node_marker.py`）:
  - `PREFIX = "works-node: "`
  - `mark(schema: dict, name: str, *, cont: str | None = None, flags: tuple[str, ...] = ()) -> dict` — 写しを作り、一番上の `description` に `works-node: <name>[ continue=<cont>][ <flag>…]` を置く（元の `description` が在れば `ValueError`。graph の schema の一番上は `description` を持たない）。
  - `parse(description: str | None) -> dict | None` — `{"name": str, "cont": str | None, "flags": frozenset[str]}`。印でなければ None。名と `cont` は `[a-z0-9-]+` だけ、知らない `flag` は None（見分けられない物は印でないと見なす）。
  - `strip(schema: dict) -> dict` — 印の `description` を外した写し。
  - `from_argv(argv: list[str]) -> dict | None` — `--json-schema <値>` と `--json-schema=<値>` の両方の綴りを読み、`parse` を返す（包みと試験が使う）。
- Produces（blk-judge の入口）: `policy_paste`（文字列、既定は空）。空でなければ「人の方針（固めた版の本文。役は代償として決めない）」として指示書に貼られる。`premises_file`（文字列、既定は空）。空でなければ前提の実測のファイル（盤面の `p0.premises` の出力）。
- 指示書の段落（文言の芯）:
  - 「人の方針（空なら方針の文書は無い）: $INPUTS.policy_paste ——方針とぶつかる単位は、その単位の `reason` に方針のどの行とぶつかるかを書け。方針を理由に単位を消すな（判断は人がする）」。
  - 「前提（実測。空なら無い）: $INPUTS.premises_file を Read せよ。`kind=仮説` の行を所与にするな。依頼の数字と測り直した値が違えば、測り直した値を採り、違いを単位の `reason` に書け」。

- [ ] **Step 1: 失敗する試験を書く**

```python
# test_policy.py
def test_judge_block_declares_policy_paste(self):   # blk-judge.yaml の inputs に policy_paste（default ""・required でない）
def test_diagnose_reads_policy_paste(self):         # diagnose.md に "$INPUTS.policy_paste" がちょうど 1 度
def test_judge_block_policy_entry_only(self):       # blk-judge.yaml の入口に policy_paste・premises_file が在り、diagnose.md がそれを読む。節の id の並びは見ない
                                                    #   （線 B の判定 v2 が intake を消しても赤にならない。TA18 の 4）
def test_diagnose_reads_premises_file(self):        # diagnose.md に "$INPUTS.premises_file" がちょうど 1 度、「仮説」の語が在る
def test_judge_output_format_marked(self):          # judge の output_format の description が parse で {"name": "judge", "cont": None}、strip した値 == role_schema("p2.diagnose")
# test_node_marker.py
def test_mark_parse_roundtrip(self):                # mark(s, "rejudge", cont="judge", flags=("no-post",)) → parse で同じ 3 つ
def test_mark_refuses_existing_description(self):   # description を持つ schema → ValueError
def test_parse_rejects_unknown(self):               # "works-node: Judge"・"works-node: judge continue=" ・知らない flag・印でない文 → None
def test_strip_restores(self):                      # strip(mark(s, …)) == s
def test_from_argv_both_spellings(self):            # ["--json-schema", 値] と ["--json-schema=値"] の両方で同じ、無ければ None、壊れた JSON は None
```

- [ ] **Step 2: 赤を確かめる** — Run: `nice -n 19 sh works/tests/run.sh -k test_policy -k test_node_marker` / Expected: FAIL（入力と印が無い）
- [ ] **Step 3: 書く** — YAML は `inputs:` に 6 行を足し、`output_format` を印つきの値に替える。1 本目のライン（`darkfactory.yaml`）は 2 つの入力を渡さないので既定の空で動く。印は Archon の読み込みと返答の型の検査に影響しない（`description` は JSON Schema の注記。〔継試〕で Archon がそのまま SDK に渡すことを確かめた）。
- [ ] **Step 4: 緑を確かめる** — Run: `nice -n 19 sh works/tests/run.sh` と `sh works/dev/check.sh` / Expected: 両方緑（`test_line.py` の `test_include_with_matches_block_inputs` と、直した `test_blk_judge.py` も緑）
- [ ] **Step 5: Commit** — `git commit -m "feat(works): 判定の指示書に人の方針と前提の実測を読む入力を足し、判定役に節の印を付ける（線 A から 1 度だけ）"`

---

### Task 3: 線の節の表（並べてよい: T2・T4・T8）

**Files:**
- Create: `works/darkfactory/nodes.json`（graph の 60 節の全部を 1 度ずつ）
- Create: `works/.shared/core/entry.py`（この Task では表の読みと開き方だけ）
- Create: `works/tests/linekit.py`（試験の手助け。`test_*` でないので発見されない）
- Test: `works/tests/test_entry.py`（表の分）

**Interfaces:**
- Consumes: `board.NodeTable.load(path)`・`NodeTable.check(graph, graph_sha)`・`board.graph_expanded()`・`board.GRAPH_SHA`・`board.DiskBoard.open(d, *, table, allow_halted=False)`・`BoardMismatch`。
- Produces（`entry.py`）:
  - `PACK = Path(__file__).resolve().parents[2]`、`TABLE_NAME = "nodes.json"`
  - `load_table(line: str = "darkfactory") -> NodeTable` — `PACK/<line>/nodes.json` を読み、縛り（盤仕様 4.2）に 1 つでも当たれば `BoardGap`（文に全部の誤り）。
  - `open_board(board_dir: Path, *, allow_halted: bool = False) -> DiskBoard` — `state.json` の `works.line` から表を引き、表の sha が `state.works.table_sha` と違えば `BoardMismatch`（文に両方の値）。ラインの置き場に `board_hook.py` が在れば読み込み（毎回新しく。`sys.modules` に残さない）、その `board_kwargs(table) -> dict` の返り（`overrides`・`validator_runner` だけを許す。ほかの鍵は `BoardGap`）を `DiskBoard.open` に渡す（線 B の申し送り 1。TA18）。ブロックのスクリプトはラインの名前を知らずにこれで開く（線 B のラインでも同じブロックが動く）。
  - `hook_kwargs(line: str) -> dict` — 上の `board_hook.py` の読み込みだけ（無ければ `{}`）。`begin` を呼ぶ側（`start`）も同じ物を渡す。
- Produces（`nodes.json` の中身。仕様 4 節・裁定 TA8・TA14）:
  - `machine`: `p0.base`（`start` の `begin`）
  - `engine_run`（`fallback: machine`）: `p0.local_checks`（`start`）・`p4.ci`（`blk-tests`）
  - `builtin`（全部 `auto`）: graph の driver の 17 節
  - `role`: `p2.diagnose`（where「blk-judge → 境の節 h-plan が盤面に渡す」）・`p2.fix_plan`・`p2.plan_review`（blk-plan）・`p3.fix`（blk-fix）・`p3.delta_review`（blk-delta）・`p3.delta_fix`・`p3.delta_review2`・`p3.delta_fix2`（blk-refix）
  - `where` は works の置き場（ブロックの名・`start`）だけを書く。ブロックの名は仮の名で、本線の 3-7 が来たら Task 25 で揃える（TA26）。
  - `absent`（理由と `comes_with` つき）: `p0.parallel_pr`（「並行 PR の検査はまだ入っていない」、`comes_with`「線 A Task 21（持ち主の決定 2026-09-27: 読むだけの役）」。T21 が engine_run に替える）・`p0.premises`（「前提の実測はまだ入っていない」、`comes_with`「線 A Task 22」。T22 が role に替える）・`p0.purpose`（「目的の文は線 B の blk-purpose で入る。線 A のラインへの取り込みは未定」、`comes_with`「線 B」）・`p0.purpose_review`・`p0.prior_decisions`・`p1.*` の役 9 つ（「P1 の目はこのラインに無い。判定から入る 1 周目は条件でも na」）・`p2.history`（「周の 2 回目の判定。1 周の run の 1 周目は条件でも na」、`comes_with` 線 B）・`p2.rejudge`・`p2.rejudge_third`（「判定への異議を同じ周で再審する口はまだ入っていない（本線 3-6 の形で、写し直しの後に入る）」、`comes_with`「線 A Task 23（持ち主の決定 2026-09-27: 包みで判定役の会話を継ぐ）」。写し直しで増える再審の 4 節も同じ行で持ち、T23 が 6 節を role に替える）・`p3.delta_gates`・`p4.final_gates`（線 C）・`r1.*`・`r2.*`・`r3.coherence`・`r4.hidden_scope`・`stop.premise_check`（R 系のブロック・未定）・`report.human_items`・`report.cold_check`・`report`（「AI が書く報告と初見検査は後。review-graph と同等と言う前に要る」台帳 R27）・`spec.write`・`spec.review`・`spec.revise`（別の入口 `darkfactory-spec`）
- Produces（`linekit.py`）:
  - `seed_repo(into: Path, *, declared: bool = False, broken_declaration: bool = False) -> Path` — `dev/target-seed/` を写して git の初めの commit を作る（名前と時刻は固定の環境）。`declared` なら `.review-checks.json`（`suite` 1 段 `["python3", "-m", "unittest", "test_stats"]`）も commit する。
  - `reply(name: str) -> dict` — `tests/replies/<name>.json`
  - `git_env() -> dict`、`work_home() -> Path`（`${WORKS_DEV_HOME:-$HOME/.cache/works-dev}/single/`）

- [ ] **Step 1: 失敗する試験を書く**

```python
def test_table_passes_board_rules(self):          # load_table() が BoardGap を出さない（盤面の層の縛り 1〜5）
def test_every_graph_node_once(self):             # 表の鍵の集合 == graph の節の集合（60）
def test_absent_rows_have_reason_and_comes_with(self):  # absent の全部で reason と comes_with が空でない
def test_later_rows_name_their_task(self):       # p0.parallel_pr・p0.premises・p2.rejudge・p2.rejudge_third が absent、comes_with に "Task 21"・"Task 22"・"Task 23"（T21〜T23 がこの試験を行の形の試験に替える）
def test_purpose_declared_absent(self):           # p0.purpose が absent、reason に「線 B」（TA14）
def test_rejudge_reason_names_the_gap(self):      # p2.rejudge・p2.rejudge_third の reason が「異議」を含み、「線 B」だけの文でない（審査 I5）
def test_roles_are_track_a_nodes(self):           # role の集合 == {p2.diagnose, p2.fix_plan, p2.plan_review, p3.fix, p3.delta_review, p3.delta_fix, p3.delta_review2, p3.delta_fix2}
def test_ci_nodes_fall_back_to_machine(self):     # p0.local_checks・p4.ci は engine_run・fallback machine
def test_no_skippable_yet(self):                  # skippable の行が 0（手厚さは標準だけ。TA7）
def test_open_board_uses_state_line(self):        # linekit の種で create した盤面を open_board で開ける。state.works.table_sha を 1 字替えると BoardMismatch（文に両方の値）
def test_open_board_applies_board_hook(self):     # 一時の pack の置き場のラインに board_hook.py（validator_runner を返す）→ open_board の盤面の run_validator がそれを呼ぶ。
                                                  #   board_hook.py が知らない鍵を返す → BoardGap。board_hook.py が無いラインは {} で開く
def test_report_absent_so_record_invalid_unreachable(self):  # 表で report・report.human_items・report.cold_check が absent。graph の pre: finalize の節は report だけ
                                                  #   → settle の報告の前の関所（RecordInvalid）は線 A で起きない。代わりの関所は report.build（TA15。Task 15）
```

- [ ] **Step 2: 赤を確かめる** — Run: `nice -n 19 sh works/tests/run.sh -k test_entry` / Expected: FAIL（`entry` が無い）
- [ ] **Step 3: 書く** — 表は手で書き、試験が graph と突き合わせる。`where` にはどのブロックかを書く（盤仕様 4.2 の例と同じ書き方。仮の名。TA26）。
- [ ] **Step 4: 緑を確かめる** — Run: `nice -n 19 sh works/tests/run.sh` / Expected: `OK`
- [ ] **Step 5: Commit** — `git commit -m "feat(works): darkfactory の節の表（graph の全部の節の持ち方と、このラインに無い理由）"`

---

### Task 4: 切符（並べてよい: T2・T3・T8）

包みが盤面の場所と守る場所を知るための小さなファイル（仕様 5.1、〔輪〕12.3）。

**Files:**
- Create: `works/.shared/core/ticket.py`
- Test: `works/tests/test_ticket.py`

**Interfaces:**
- Produces:
  - `home() -> Path` — `${WORKS_ADAPTER_HOME:-${XDG_STATE_HOME:-$HOME/.local/state}/works/adapter}`
  - `ticket_path(cwd: Path) -> Path` — `home()/tickets/<cwd の realpath の sha256 の先頭 16 桁>.json`
  - `protected_paths(repo_cwd: Path, board_dir: Path) -> list[str]` — 共通の `.git`（`--git-common-dir`）・この worktree の gitdir の実体（`--absolute-git-dir`）・`git worktree list` の他の worktree と元の作業ツリー（**役の cwd の worktree 自身は除く**）・盤面・`home()`・pack の置き場・git とシェルの設定（`~/.gitconfig`・`~/.config/git`・`~/.bashrc`・`~/.zshrc`・`~/.profile`）・Claude の設定の置き場（`~/.claude`）。綴りと realpath の両方を入れ、重複を除き、並べて返す。git が引けなければ `TicketError`。
  - `write(board_dir: Path, repo_cwd: Path, run_id: str) -> Path` — `{run_id, board, cwd, protected, written_at}` を一時ファイルから `os.replace`。
  - `read(cwd: Path) -> dict | None` — 無い・壊れていれば None。
  - `class TicketError(Exception)`

- [ ] **Step 1: 失敗する試験を書く**

```python
def test_protected_excludes_own_worktree(self):   # 元の作業ツリーと worktree 2 つの使い捨てのリポジトリ: 役の cwd の worktree は含まれず、元と他方は含まれる
def test_protected_has_git_dirs_and_board(self):  # --git-common-dir・--absolute-git-dir・盤面・home() が含まれる
def test_protected_both_spellings(self):          # /var と /private/var のように綴りと realpath が違う場所は両方
def test_write_read_roundtrip(self):              # write → read が同じ中身、ファイル名は cwd の realpath の sha256 の先頭 16 桁
def test_read_broken_is_none(self):               # 壊れた JSON → None
def test_not_git_raises(self):                    # git でない cwd → TicketError
```

- [ ] **Step 2: 赤を確かめる** — Run: `nice -n 19 sh works/tests/run.sh -k test_ticket` / Expected: FAIL
- [ ] **Step 3: 書く** — git は `subprocess.run([...], check=True, capture_output=True)`（`timeout=` を付けない）。
- [ ] **Step 4: 緑を確かめる** — Run: `nice -n 19 sh works/tests/run.sh` / Expected: `OK`
- [ ] **Step 5: Commit** — `git commit -m "feat(works): 包みの切符（盤面の場所と、役が書いてはいけない場所を git から引く）"`

---

### Task 5: Claude の包み（T4 の後）

仕様 5.1・〔輪〕12 節・〔継試〕。Archon が起こす Claude Code の実行ファイルを包みに差し替え、包みが本物の claude を起こす。足すのは Read のフック・起動ごとの柵・プロセスグループ・判定役の会話の継ぎの 4 つだけ。P14・P15 は Task 18（費用の了承）で確かめ、それまでは偽の claude で振る舞いを縛る。会話の継ぎは〔継試〕で本物の claude と Archon で確かめた形をそのまま作る（TA20・TA21）。

**Files:**
- Create: `works/.shared/core/claude-adapter`（`#!/usr/bin/env python3`・実行可能・拡張子なし）
- Modify: `works/.shared/core/ticket.py`（`session_path` を足す）
- Create: `works/.shared/adapter/record-read.py`（`a1202d0:graphloops/hooks/record-read.py` の写し。書く先を切符の盤面の `reads.jsonl` にする所だけ変える）・`works/.shared/adapter/COPIED_FROM`（元の commit とパス、変えた行の説明）
- Create: `works/tests/adapter/fake-claude`（受けた argv・環境・`--settings` の中身をファイルに書き、背景に `sleep` の孫を 1 つ置き、標準入力を標準出力に写して終わる）・`works/tests/adapter/argv/*.json`（〔包試〕`argv.log` と〔継試〕の `argv.log`（13 回の起動。題の生成・印あり・`continue`・輪の中・fork 付き）からプロンプトの本文を消して写した実物の argv）
- Test: `works/tests/test_adapter.py`

**Interfaces:**
- Consumes: `ticket.read(cwd)`・`ticket.home()`、`tree_run.stop_group`・`tree_run.KILL_GRACE`（2 秒）、`node_marker.from_argv`（T2）。
- Produces（`ticket.py`）: `session_path(cwd: Path, node: str) -> Path` — `home()/sessions/<cwd の realpath の sha256 の先頭 16 字>/<node>.id`。T23 の境の節の先の確かめと、線 B の境の節が同じ関数を使う。
- Produces:
  - 包み: `claude-adapter <SDK の argv…>`。本物の claude は `WORKS_REAL_CLAUDE`、無ければ PATH の実行ファイルの `claude`（関数・別名は飛ばす）。
  - `--settings` と `--setting-sources` を `--flag 値`・`--flag=値` の両方の綴りで読む。`--setting-sources` は読むだけで変えない。`--settings` の値（JSON の文字列かファイルのパス）に、`hooks.PostToolUse`（`matcher: "Read"`、`record-read.py`）を配列に足し、sandbox の塊が在る起動だけ `sandbox.filesystem.denyWrite` と `permissions.deny`（`Edit(<場所>/**)`・`Write(<場所>/**)`）に切符の守る場所を足す。他の鍵は上書きしない。`--settings` が無ければフックだけの `--settings` を足す。
  - 見分けられない形（`--settings` が 2 つ・JSON でも読めるファイルでもない・知らない綴り）と、切符が無い・壊れている・`run_id` が盤面の物と違う起動は、argv を 1 バイトも変えずに素通しし、stderr に 1 行の警告。
  - 本物の claude を `start_new_session=True` で起こし、標準入出力を継がせ、子の終了コードで終わる。SIGTERM・SIGINT・SIGHUP を受けたらグループへ送り、`KILL_GRACE` の後に SIGKILL。子が終わった後も残る背景の孫を止める。自分の親が 1 になったら止める。
  - **会話の継ぎ**（仕様 5.1 の 1〜5。`--settings` の扱いと別に、切符が無い起動でも行う）: `node_marker.from_argv(argv)` が None の起動は argv を 1 バイトも変えない。印あり・`cont` なし: argv に `--resume`（`--resume=`）が在ればその id を、`--session-id`（`--session-id=`）が在ればその id を、どちらも無ければ `uuid4` を作って `--session-id=<uuid>` を足し、`session_path(cwd, 名)` に一時ファイルから `os.replace` で書く（子を起こす前）。印あり・`cont` あり: `--resume`・`--resume=…`・`--session-id`・`--session-id=…`・`--fork-session` を外し、`session_path(cwd, cont)` の id で `--resume <id>` を足す。id のファイルが無い・空なら、stderr に 1 行 `works: 会話 <cont> の id が無い: <path>` を出し、子を起こさずに exit 3。
  - **印 `no-post`**: `--settings` を足せる起動（merged）で、`permissions.deny` に `Bash(gh pr comment:*)`・`Bash(gh pr review:*)`・`Bash(gh pr edit:*)`・`Bash(gh pr create:*)`・`Bash(gh pr close:*)`・`Bash(gh pr merge:*)`・`Bash(gh issue comment:*)`・`Bash(gh issue create:*)`・`Bash(gh api -X:*)`・`Bash(gh api --method:*)` を足す（定数 `NO_POST_DENY`）。
  - `$B/launches.jsonl` の 1 行（切符が無ければ `home()/orphans.jsonl`）: `{ts, pid, cwd, run_id, node?, mode: "merged"|"passthrough", why?, added: {hook: bool, deny_write: int, permissions_deny: int}, tools_empty: bool, session?: {mode: "new"|"sdk-resume"|"sdk-session"|"continued"|"refused", id, of?}}`。引数の本文は書かない。

- [ ] **Step 1: 失敗する試験を書く**（〔輪〕12.6 の 7 つ）

```python
def test_settings_three_spellings_merged(self):   # --settings <JSON>・--settings=<JSON>・ファイルのパス: フックが足され、SDK の sandbox の鍵がそのまま、denyWrite と permissions.deny に切符の守る場所
def test_setting_sources_untouched(self):         # --setting-sources=project,user と --setting-sources "" がそのまま子に届く
def test_no_settings_gets_hook_only(self):        # --settings が無い → フックだけ、柵は足さない、launches の added.deny_write == 0
def test_unknown_shape_passthrough(self):         # --settings が 2 つ・壊れた JSON → 子の argv が 1 バイトも同じ、stderr に警告、launches に mode passthrough と why
def test_missing_or_foreign_ticket_passthrough(self):  # 切符が無い → orphans.jsonl に理由。run_id 違い → passthrough と理由
def test_sigterm_kills_group(self):               # 包みに SIGTERM → 偽の claude と sleep の孫が消える（pid を os.kill(pid, 0) で確かめる）、終了コードが 128+15
def test_sigterm_ignoring_grandchild_killed_before_5s(self):  # trap '' TERM の孫も KILL_GRACE の後の SIGKILL で 5 秒より前に消える（試し P11）
def test_stdio_passthrough(self):                 # 標準入力の 3 行が標準出力にそのまま
def test_exit_code_passthrough(self):             # 偽の claude の終了コード 3 → 包みも 3
def test_name_not_js(self):                       # 包みのファイル名が .js で終わらない、先頭行が #!/usr/bin/env python3、実行可能
def test_real_argv_samples_recognised(self):      # argv/*.json の全部が mode merged（見分けられない形が実物に無い）
def test_tools_empty_launch_marked(self):         # --tools "" の起動は tools_empty: true
def test_record_read_copy_differs_only_in_sink(self):  # record-read.py と a1202d0 の元の差が、COPIED_FROM に書いた行だけ（a1202d0 が引けなければ理由を出して skip）
# 会話の継ぎ（〔継試〕の形）
def test_unmarked_untouched(self):                # 題の生成の argv（--tools ""・印なし）→ 子の argv が 1 バイトも同じ、sessions/ に何も書かない
def test_judge_gets_session_id_and_records(self): # 印 judge・SDK の id なし → 子の argv に --session-id=<uuid>、session_path(cwd, "judge") の中身が同じ uuid、launches の session.mode "new"
def test_judge_sdk_resume_records_same_id(self):  # 印 judge・SDK が --resume=X（線 B の判定の 2 回目）→ 子の argv は同じ、記録は X、mode "sdk-resume"。--session-id Y → 記録は Y
def test_continue_strips_and_resumes(self):       # 印 "rejudge continue=judge"・SDK が --resume=Z と --fork-session → 子の argv から両方が消え、末尾に --resume <judge の id>、mode "continued"・of "judge"
def test_continue_keeps_settings_and_sources(self):  # 継いだ起動にも --settings（sandbox の塊）と --setting-sources=project,user が残る（〔継試〕の (3)）
def test_continue_missing_id_fails_closed(self):  # judge の id が無い → 終了コード 3、stderr 1 行にパス、偽の claude が起きていない（記録のファイルが無い）、mode "refused"
def test_session_splice_in_passthrough(self):     # 切符が無い起動でも continue の差し替えは行う（--settings は素通し）
def test_session_path_per_cwd(self):              # 2 つの cwd の judge の id が別のファイル、同じ cwd の後の judge が前の id を書き直す
def test_no_post_denies_gh_writes(self):          # 印 "pr-check no-post" → permissions.deny に NO_POST_DENY の全部、印の無い起動には足さない
def test_real_resume_argv_samples(self):          # 〔継試〕の argv の見本の全部で、印の見分けと差し替えが〔継試〕の記録と同じ（題の生成は素通し）
```

- [ ] **Step 2: 赤を確かめる** — Run: `nice -n 19 sh works/tests/run.sh -k test_adapter` / Expected: FAIL
- [ ] **Step 3: 書く** — 包みは `.shared/core` を自分の実体からの相対で `sys.path` に入れて `tree_run`・`ticket`・`node_marker` を import する。`exec` しない。フックのコマンドは包みと同じ置き場の `record-read.py` の絶対パス。会話の継ぎは argv だけで決める（stdin を中継しない。〔継試〕: 指示書は initialize の後に stdin に来るので、起動の前には読めない）。
- [ ] **Step 4: 緑を確かめる** — Run: `nice -n 19 sh works/tests/run.sh` / Expected: `OK`。試験の後に `ps` で `fake-claude`・`sleep` が残っていない（pid と cwd で確かめる）。
- [ ] **Step 5: Commit** — `git commit -m "feat(works): Claude の包み（Read の記録・起動ごとの柵・プロセスグループ・判定役の会話の継ぎ）"`

---

### Task 6: 読んだ証拠（T5 の後）

仕様 5.2・〔輪〕5.3。役の出し直しの輪の後に、機械が渡したパスを役が読んだかを 2 つの出どころ（包みのフックの記録と、Archon の `tool_called` の出来事）で集める。受け付けの条件にはしない。

**Files:**
- Create: `works/.shared/core/reads.py`
- Create: `works/tests/events/*.json`（`archon workflow get --verbose --events --json` の見本。〔試P〕P13 の `probe.json` と P10 の include の名前から作る。`tool_called` の行は形を推測して足し、`# 推測（P13 の AI の分で取り直す）` を見本の `_note` に書く）
- Test: `works/tests/test_reads.py`

**Interfaces:**
- Consumes: 写しの RL の `hook_evidence`（`rules_module()` から引く）、`entry.open_board`、`$B/launches.jsonl`（T5 の形）。
- Produces:
  - `events_for(run_id: str) -> list[dict] | None` — `json.loads(os.environ["ARCHON_CLI_COMMAND"]) + ["workflow", "get", run_id, "--verbose", "--events", "--json"]` を呼び、出力の `events` を返す。変数が無い・呼べない・`events` が無いときは None（試し P13）。
  - `node_path(include: str, loop: str, node: str) -> str` — 出来事の上の節の名前（例 `planning__plan-loop.plan`。推測。P13 の AI の分で確かめる）。
  - `EVENTS_VERIFIED = False` — `tool_called` の Read の形を P13（Task 18）で確かめるまで偽。偽の間は、出来事が取れても出どころを `"unverified"` と書き、各行の `event` を `null`（「読んでいない」と取り違えない）にする（審査 I6）。
  - `collect(board_dir: Path, role: str, node_path: str, must_read: list[str], events: list[dict] | None) -> dict` — `b.work(f"reads-{役}.json")`（今の周の置き場）に `{role, node_path, rows: [{path, hook: "read"|"stale"|"partial"|"absent"|"none", event: bool | None}], sources: {hook: bool, events: "verified"|"unverified"|"none"}, missing: [path]}` を書き、`{"ok": True, "sources": {...}, "missing": [...], "reads_file": str}` を返す。`missing` はフックで `read` でも `stale`・`partial` でもない物（出来事は `verified` の時だけ数える）。
  - `adapter_seen(board_dir: Path, run_id: str) -> dict` — `{"seen": bool, "merged": int, "passthrough": int, "whys": [str]}`（`launches.jsonl` のこの run の行のうち `tools_empty` でない物を数える）。
  - ブロックの `<役>-reads` の節が呼ぶ入口: `main_for(role: str, include: str, loop: str, node: str) -> int`（環境変数 `ARTIFACTS_DIR`・`WORKFLOW_ID`・`INPUTS_MUST`（JSON の配列）を読み、`collect` の結果を 1 行で出して 0。変数が欠けたら 2）。

- [ ] **Step 1: 失敗する試験を書く**

```python
def test_states_from_hook_and_events(self):      # reads.jsonl（実物の行の形）と events の見本、EVENTS_VERIFIED を真に差し替え → 各パスの hook と event
def test_stale_when_file_changed(self):          # 読んだ後にファイルを書き換える → hook == "stale"
def test_missing_sources_reported(self):          # events None → sources.events "none"。reads.jsonl が無い → sources.hook False。両方無し → missing が must_read の全部
def test_included_node_path(self):                # node_path("planning", "plan-loop", "plan") == "planning__plan-loop.plan"、events の見本のその名前の行だけを数える
def test_events_for_without_cli_is_none(self):    # ARCHON_CLI_COMMAND が無い → None（例外を出さない）
def test_events_for_calls_cli_with_verbose(self): # 偽の CLI（受けた argv を書く小さなスクリプト）→ argv の末尾が workflow get <id> --verbose --events --json
def test_adapter_seen_counts(self):               # launches.jsonl に merged 2・passthrough 1・別の run 1・tools_empty 1 → seen True・merged 2・passthrough 1
def test_not_an_acceptance_condition(self):       # 全部 missing でも collect は ok True
def test_events_unverified_until_p13(self):       # EVENTS_VERIFIED が偽 → events の見本が在っても sources.events == "unverified"、各行の event は None、missing は hook だけで決まる
```

- [ ] **Step 2: 赤を確かめる** — Run: `nice -n 19 sh works/tests/run.sh -k test_reads` / Expected: FAIL
- [ ] **Step 3: 書く** — `hook_evidence` は写しの物を呼ぶ（書き直さない）。出来事の Read の `file_path` の位置は見本の推測に合わせ、1 か所の関数 `_read_paths(events, node_path)` に閉じ込める（P13 の結果で直すのはここだけ）。
- [ ] **Step 4: 緑を確かめる** — Run: `nice -n 19 sh works/tests/run.sh` / Expected: `OK`
- [ ] **Step 5: Commit** — `git commit -m "feat(works): 役が読んだ証拠を集める（包みの記録と Archon の出来事）"`

---

### Task 7: `start`（T3・T4 の後）

仕様 4 節。依頼と入力を確かめ、盤面を開き、修正前のテストを盤面に記録し、方針の文を組み、切符を書く。

**Files:**
- Modify: `works/.shared/core/entry.py`（入力の検査と `start`）
- Create: `works/.shared/core/policy.py`
- Create: `works/darkfactory/scripts/start.py`
- Test: `works/tests/test_entry.py`（足す）・`works/tests/test_policy.py`（足す）

**Interfaces:**
- Consumes: `DiskBoard.begin(d, *, repo, table, items, origin, base_rev, request_text, inputs, stop_after_round=1, overrides=, validator_runner=)`（返り `(board, Progress)`。`overrides`・`validator_runner` は `entry.hook_kwargs(line)` から）・`b.run_engine(nid, *, runner=None)`・`b.done(nid, output)`・`b.settle()`・`b.work(name)`、`tree_run.run`・`tree_run.outside_env`、`ticket.write`、写しの `engine/declared.py`（宣言の読み方）。
- Produces（`entry.py`）:
  - `THICKNESS = ("軽量", "標準", "重厚")`・`MID_GATES = ("always", "when_needed")`・`ADAPTER_MODES = ("", "optional")`・`GATES = ("", "merge")`
  - `class InputRefused(Exception)` — 文は人に向けた 1 行。
  - `check_inputs(raw: dict, repo: Path) -> dict` — 返り `{request_file, items, request_text, test_cmd, thickness, gates, mid_gate, adapter, policy_md}`。拒む物: 依頼が読めない・JSON の配列でない、`thickness` が `軽量`（文「軽量は受けない: graph で省けない節を省くことになる（持ち主の決定 2026-09-27）」）・`重厚`（文「重厚で足す工程がまだ無い」）・知らない値、`mid_gate`・`adapter`・`gates` が語の外、`test_cmd` が空で対象の根に読める `.review-checks.json` の `suite` も無い（文「テストを飛ばさない: test_cmd か .review-checks.json の suite が要る」）。
  - `local_checks_material(repo: Path, test_cmd: str, log_path: Path) -> dict` — 任せ先に落ちた CI の節（`p0.local_checks`・`p4.ci`）に渡す素材を組む公開の口（線 B の申し送り 2。TA18）。`test_cmd` を `["bash", "-c", test_cmd]` で `tree_run` に走らせ、`{"material": {"status": "clean"|"found", "count": 0|1, "detail": <ログの末尾>}}` を返す。`test_cmd` が空なら `{"material": {"status": "not_run", "reason": "…"}}`。
  - `run_ci(b, nid: str, *, test_cmd: str, runner=None) -> dict` — `b.run_engine(nid)` を呼び、返りを全部扱う（M7）: `relaunch: True` は 1 度だけ呼び直し、2 度目も同じなら `CiRefused`（文に `why`）。`fallback` で任せ先に落ちたら `local_checks_material` を `b.done(nid, …)`。`ok: False` で `relaunch` も `fallback` も無い（`why` だけ。例: 対象の根が引けない）なら `CiRefused`。返り `{by: "engine"|"role", log: <run_engine の返りの runs[].out か任せ先のログのパス>}`。`start` と `blk-tests` の `final` が共に使う。
  - `start(board_dir: Path, repo: Path, raw: dict, *, run_id: str, runner=None) -> dict` — 順: `check_inputs` → `DiskBoard.begin(..., origin="works/darkfactory", base_rev="", inputs={"gates": …, "policy_md": … or None}, stop_after_round=1, **hook_kwargs(line))` → `ready` の engine_run の節を全部 `run_ci`（`runner` は試験の差し込み。`CiRefused` は `InputRefused` と同じく AI を起こす前に止める）→ `settle` → `ticket.write` → `b.work("start.json")` に入力の控え。返り `{ok: True, base_rev, test_cmd, policy_paste, policy_path, mid_gate, adapter, thickness, gates, head_line}`（T21 が `pr_go`、T22 が `premises_go` を足す）。`head_line` は「入口: 判定から（依頼 N 件）・段: 標準・gates: 空・このラインに無い節: M 個」（T21 が「下げている所: K 個」を足す）。
- Produces（`policy.py`）:
  - `PASTE_CAP = 40000`
  - `brief(board) -> dict` — `record.process.policy` の `copy` から `{"paste": str, "path": str}`。方針の文書が無ければ `{"paste": "", "path": ""}`。4 万バイトを超えたら先頭と「続きは <path>」。
- Produces（`darkfactory/scripts/start.py`）: 環境変数 `INPUTS_REQUEST`・`INPUTS_TEST_CMD`・`INPUTS_THICKNESS`・`INPUTS_GATES`・`INPUTS_MID_GATE`・`INPUTS_ADAPTER`・`INPUTS_POLICY_MD`・`ARTIFACTS_DIR`・`WORKFLOW_ID` を読み、`entry.start` の結果を 1 行で出して 0。`InputRefused` は理由を stderr に 1 行出して 1（AI を起こす前に run を止める。1 本目の intake と同じ）。環境変数が欠けたら 2。

- [ ] **Step 1: 失敗する試験を書く**

```python
# test_entry.py
def test_inputs_defaults(self):                   # 依頼だけ → thickness 標準・gates ""・mid_gate always・adapter ""、返りに thickness_decider が無い
def test_light_refused_by_owner_decision(self):   # thickness=軽量 → InputRefused、文に "持ち主の決定" と "省けない節"
def test_heavy_refused(self):                     # 重厚 → InputRefused、文に "重厚で足す工程がまだ無い"
def test_unknown_words_refused(self):             # thickness=x・mid_gate=x・adapter=x・gates=x → それぞれ InputRefused（gates は RL の check_inputs の文）
def test_start_refuses_no_tests(self):            # test_cmd 空・宣言無し → InputRefused、盤面の置き場が作られない
def test_start_with_declaration_by_engine(self):  # seed_repo(declared=True) → start → process.checks["p0.local_checks"].by == "engine"、ready == ["p2.diagnose"]
def test_start_without_declaration_runs_test_cmd(self):  # 宣言無し・test_cmd="python3 -m unittest test_stats" → by == "role"、素材 found（種は赤 2 件）、ready == ["p2.diagnose"]
def test_start_broken_declaration_not_fallback(self):  # 読めない宣言 → engine が返答を組み（任せ先に落ちない）、test_cmd を走らせない
def test_run_ci_relaunch_once(self):              # 1 度目 relaunch・2 度目通る偽の run_engine → 通る。2 度とも relaunch → CiRefused、文に why
def test_run_ci_why_only_refused(self):           # {ok: False, why} だけの返り → CiRefused（黙って素通りしない）
def test_local_checks_material_callable_alone(self):  # 盤面なしで local_checks_material(種, "python3 -m unittest test_stats", log) → found・count 1・detail にログの末尾
def test_start_records_request_and_entry(self):   # record.process.request_findings に 1 バッチ、request_entry.origin == "works/darkfactory"
def test_start_stop_after_round_one(self):        # state の stop_after_round が 1
def test_start_writes_ticket(self):               # ticket.read(repo) の run_id・board が一致
def test_start_head_line(self):                   # head_line に "判定から"・"標準（既定）"・absent の数
def test_start_script_refusal_exit_1(self):       # start.py を子で起こす: 軽量 → 終了コード 1、stderr 1 行、stdout 空
# test_policy.py
def test_brief_paste_and_path(self):              # 共通の git の置き場の graphloops/policy.md を置いた種 → paste が本文、path が盤面の policy/ の下の写し
def test_brief_capped(self):                      # 5 万バイトの方針 → paste が 40000 バイト以下で "続きは" とパス
def test_brief_empty_without_policy(self):        # 方針の文書が無い → paste と path が空
```

- [ ] **Step 2: 赤を確かめる** — Run: `nice -n 19 sh works/tests/run.sh -k test_entry -k test_policy` / Expected: FAIL
- [ ] **Step 3: 書く** — `test_cmd` は 1 本目の blk-tests と同じく `["bash", "-c", test_cmd]` を `tree_run.run` で（環境は `outside_env`、`PYTHONDONTWRITEBYTECODE=1`）。宣言の `suite` が読めるかは写しの `engine/declared.py` で見る（書き直さない）。
- [ ] **Step 4: 緑を確かめる** — Run: `nice -n 19 sh works/tests/run.sh` / Expected: `OK`
- [ ] **Step 5: Commit** — `git commit -m "feat(works): start（入力の確かめ・盤面を開く・修正前のテストの記録・方針の文・切符）"`

---

### Task 8: 止め札（並べてよい: T2・T3・T4）

仕様 5.3。

**Files:**
- Create: `works/.shared/core/halt.py`（この Task では止め札だけ）
- Create: `works/dev/stop.sh`
- Create: `works/tests/events/get-running.json`・`get-finished.json`（`archon workflow get --json` の見本。〔試P〕`p10-get.json` と走っている run の形。`output_root` を持つ）
- Test: `works/tests/test_halt.py`

**Interfaces:**
- Produces（`halt.py`）:
  - `STOP_FILE = "STOP"`
  - `place(board_dir: Path, reason: str, by: str) -> dict` — 理由が空・空白だけなら書かずに `{"ok": False, "reason": "理由が要る"}`。在れば上書きせず trace にだけ積み `{"ok": True, "first": False}`。無ければ `{reason, by, at}` を一時ファイルから `os.replace` で書き `{"ok": True, "first": True}`。trace は盤面の `trace.jsonl` に 1 行（`DiskBoard` の `trace` と同じ行の形）。
  - `seen(board_dir: Path) -> dict | None` — `STOP` の中身。
- Produces（`dev/stop.sh <run-id> <理由…>`）: 盤面を `archon workflow get <run> --json` の `output_root` + `artifacts/runs/<run-id>/board` で組み、`board/` が無ければ書かずに 2。理由が無ければ 2。在れば `halt.place`（`by` は `$USER`）。Archon を呼ぶ殻は `WORKS_DEV_ARCHON`（既定 `dev/archon.sh`。試験は偽物を差す）。

- [ ] **Step 1: 失敗する試験を書く**

```python
def test_place_requires_reason(self):             # "" と "  " → ok False、STOP が無い
def test_first_reason_wins(self):                 # 2 度目 → first False、STOP の中身は 1 度目、trace に 2 度目の理由
def test_place_atomic(self):                      # 書いた後に .tmp が残らない
def test_stop_sh_refuses_empty_reason(self):      # 終了コード 2、STOP が無い
def test_stop_sh_board_from_output_root(self):    # 偽の archon が get-running.json を返す → output_root/artifacts/runs/<id>/board/STOP ができる
def test_stop_sh_refuses_missing_board(self):     # board/ が無い → 2、何も書かない
```

- [ ] **Step 2: 赤を確かめる** — Run: `nice -n 19 sh works/tests/run.sh -k test_halt` / Expected: FAIL
- [ ] **Step 3: 書く** — `stop.sh` は `set -eu`、JSON は `python3 -c` で読む（標準ライブラリだけ）。
- [ ] **Step 4: 緑を確かめる** — Run: `nice -n 19 sh works/tests/run.sh` / Expected: `OK`
- [ ] **Step 5: Commit** — `git commit -m "feat(works): 止め札（理由必須・最初の理由が正・盤面の場所は output_root から）"`

---

### Task 9: 盤面に受ける共通の口（T7 の後）

各ブロックの受け付けが使う 1 つの口。役の返答を盤面に渡し、拒まれたら理由を返し、通ったら次に待っている節を返す。

**Files:**
- Modify: `works/.shared/core/entry.py`（`take`・`snapshot`・`empty_fix_reply`）
- Test: `works/tests/test_entry.py`（足す）

**Interfaces:**
- Consumes: `entry.open_board`・`DiskBoard.done(nid, output) -> Progress`・`Reject`（写しの engine の拒否）・`BoardGap`、`accept.snapshot_tree(repo)`（1 本目の写し。TA11）。
- Produces:
  - `snapshot(board_dir: Path, name: str, repo: Path) -> Path` — `accept.snapshot_tree(repo)` を `b.work(name)`（今の周の置き場）に書く（読むだけの役を起こす前）。
  - `take(board_dir: Path, nid: str, reply: dict, repo: Path, *, snapshot_name: str | None = None) -> dict` — 順: `snapshot_name` が在れば今の作業ツリーと比べ、違えば `{"ok": False, "reason": "読むだけの役が作業ツリーを変えた: …"}`（1 本目と同じ文の形）→ `open_board` → `done(nid, reply)`。返り `{"ok": True, "reason": "", "ready": [...], "asking": bool, "halted": bool, "out_file": <state.outputs[nid]["file"]>}`。写しの `AnswerReject`（中身の誤り）だけを `{"ok": False, "reason": 文}` にする（盤面は書かれない。入れ物は捨てる）。ほかの `Reject`（止めた run への書き込みなど）と `BoardGap` は投げ直す（スクリプトは終了コード 2。回す側の誤りは役に返しても直らない。TA19）。
  - `main_take(nid: str, *, snapshot_name: str | None = None) -> int` — ブロックの受け付けのスクリプトの入口（`script_io.main` と同じ環境変数の約束。`INPUTS_REPLY`・`INPUTS_BASE_REV`・`ARTIFACTS_DIR`）。
  - `empty_fix_reply() -> dict` — 直す義務 0 件の周の `p3.fix` の返答（`changes: []`、`fix_closure.status` は `not_applicable`、他の必須の欄は空の値。TA6）。写しの `p3.fix` の schema と `fix_covers_open_units` を通る形。

- [ ] **Step 1: 失敗する試験を書く**

```python
def test_take_accepts_and_reports_ready(self):    # start の後の盤面に judge_ok を take("p2.diagnose") → ok、ready に p2.fix_plan
def test_take_reject_leaves_board(self):          # 型の崩れた返答 → ok False、盤面の全ファイルの sha が前のまま
def test_take_readonly_tree_changed(self):        # snapshot の後に作業ツリーを書き換えて take → ok False、文に「作業ツリーを変えた」、盤面は前のまま
def test_take_gap_raises(self):                   # 表で absent の節（p0.purpose）→ BoardGap
def test_take_on_halted_raises_not_role_reject(self):  # 止めた盤面に take → AnswerReject でない Reject が投げ直される（ok False で役に返さない）
def test_take_round_two(self):                    # 周 2 の盤面（手本 test_converges の周 2 の頭から組む）で take → out_file が out/r2/ の下（周を仮定しない）
def test_take_pointer_integer_rejected(self):     # p2.fix_plan の unit_keys に整数 → ok False（engine の番号の文。盤仕様 BL17）
def test_main_take_exit_codes(self):              # 受け付けのスクリプトとして子で起こす: 中身の拒否は 0 で 1 行、止めた盤面・BoardGap・環境変数の欠けは 2
def test_empty_fix_passes_rule(self):             # judge_no_fix を受けた盤面で empty_fix_reply() を done("p3.fix") → 通り、settle の後 ready に p4.ci、p3.delta_review は na
```

- [ ] **Step 2: 赤を確かめる** — Run: `nice -n 19 sh works/tests/run.sh -k test_entry` / Expected: FAIL（足した試験）
- [ ] **Step 3: 書く** — `take` は `DiskBoard.edit` を使わず、`open_board` → `done` の 1 回で閉じる（`done` の中で保存される）。拒否の後は入れ物を捨てる（盤仕様 4.1）。
- [ ] **Step 4: 緑を確かめる** — Run: `nice -n 19 sh works/tests/run.sh` / Expected: `OK`
- [ ] **Step 5: Commit** — `git commit -m "feat(works): 役の返答を盤面に渡す共通の口（拒否は盤面を書かない・読むだけの役の作業ツリーの確かめ）"`

---

### Task 10a: 境の節の芯（止め札・関所の答え・次のブロックの決め方。T8・T9 の後）

仕様 2 節・裁定 TA1・TA4。いつも走る script の節 1 本を、ラインの中で `at` を替えて使う（この Task で 8 つ。T22 が `judge`、T23 が `rejudge` を足して 10）。この Task では `h-plan` の固有の仕事（包みの確かめ・判定の渡し替え・直す物が無い周の締め）を除いた全部を作る（それは T10b）。

**Files:**
- Modify: `works/.shared/core/halt.py`（`edge`）
- Create: `works/.shared/core/plan.py`（この Task では関所の文 `gate_text` だけ）
- Create: `works/darkfactory/scripts/edge.py`
- Test: `works/tests/test_halt.py`（足す）

**Interfaces:**
- Consumes: `entry.open_board(allow_halted=)`・`DiskBoard.answer(ans, note) -> Progress`・`DiskBoard.stop(reason, by) -> dict`・`b.settle()`・`b.work(名)`・`b.trace(op, **kw)`・`state.outputs[節]["file"]`、`halt.seen`、`Progress["asking"]`（`state.pending_human`）。
- Produces（`halt.py`）:
  - `AT = ("plan", "gate", "fix", "mid", "midgate", "review", "refix", "tests")`（T22・T23 が `"judge"`・`"rejudge"` を足す。並びはラインの順）
  - `edge(board_dir: Path, at: str, repo: Path, *, run_id: str, adapter_mode: str, mid_gate: str, judged: dict | None = None, gate: dict | None = None, mid: dict | None = None) -> dict` — 返り `{"ok": True, "stop": bool, "go": bool, "ask": bool, "gate_text": str, "judgment_file": str, "open_units": str, "plan_file": str, "notes": str, "why": str}`（使わない欄は空の値。`judgment_file`・`open_units` は `h-plan` が受けた判定の出口を後ろの境の節へ運ぶため、どの `at` でも盤面の `r<N>/start.json` と判定の出口の控え `r<N>/judged.json` から埋める。M4）。順:
    1. 盤面を `allow_halted=True` で開く。既に止まっている（`halted`・`state.stop`）なら、止め札が在ってもその理由は trace にだけ書き（`b.trace("stop_flag_after_halt", …)`）、`{stop: True, go: False}` を返す（`b.stop` を 2 度呼ばない。止めた盤面への `b.stop` は Reject になるため。M3）。
    2. `at == "fix"` で `gate` が dict → `decision` が `approve`/`continue` なら `b.answer("continue", text)`、`stop`/`reject` なら `b.answer("stop", text or "関所で止めた")`（盤面は `halted.by == "answer"`）。`gate` が None（文字列 `null` から）なら何もしない。
    3. `at == "review"` で `gate` が dict → `stop`/`reject` なら `b.stop(text or "中の関所で止めた", by="human:mid-gate")`。`continue`/`approve` なら `b.work("mid-gate-answer.json")` に `{decision, text}`。
    4. 2・3 で盤面が止まったら、止め札が在ってもその理由は trace にだけ書いて `{stop: True}`（関所の答えが先。M3）。止まっていなければ、止め札（`halt.seen`）が在れば `b.stop(理由, by)` → `{stop: True}`。
    5. `at == "plan"`: T10b の関数 `plan_edge(b, …)` を呼ぶ（この Task では「`p2.fix_plan` が `ready` なら `go: True`」だけの形で置き、T10b で中身を足す）。
    6. `at == "gate"`: `pending_human` が在れば `ask: True` と `gate_text = plan.gate_text(asking)`、`b.work("gate.md")` に同じ文。
    7. `at == "fix"`: `go` = `p3.fix` が `ready`。`notes` = 今の周の `human_items` の `note` を並べた文、`plan_file` = `state.outputs["p2.fix_plan"]["file"]`（無ければ空）。
    8. `at == "mid"`: `go` = 今の周の `p3.fix` を役が出した（空の返答でない。空の返答は `state.works` でなく盤面の trace の `by: "works:empty-fix"` で見分ける）。
    9. `at == "midgate"`: `mid` は中のテストの出口（None なら開かない）。`ask` = `mid_gate == "always"`、または `when_needed` で `mid.green` が偽か `mid.ok` が偽。`gate_text` は緑赤・ログのパス・修正の要約・run の worktree の場所。`b.work("mid-gate.md")` に同じ文。
    10. `at == "review"`: `go` = `p3.delta_review` が `ready`。`at == "refix"`: `go` = `p3.delta_fix` が `ready`。`at == "tests"`: `go` = `p4.ci` が `ready`。
- Produces（`plan.py`）: `gate_text(asking: dict) -> str` — 盤面の問い（`question`・`items`・`kinds`）を、答え方の 1 行（`archon workflow respond <id> continue "<通す範囲と条件>"`／`stop "<理由>"`、`reject --reason` でも止まる）つきの文にする。
- Produces（`darkfactory/scripts/edge.py`）: `INPUTS = ("INPUTS_AT", "INPUTS_JUDGED", "INPUTS_GATE", "INPUTS_MID", "INPUTS_ADAPTER", "INPUTS_MID_GATE")`。これと `ARTIFACTS_DIR`・`WORKFLOW_ID` を読み（どの `INPUTS_*` も文字列 `null` は None）、`edge` の結果を 1 行で出して 0。欠けたら 2。

- [ ] **Step 1: 失敗する試験を書く**（盤面は linekit の種で `start` → 見本の返答を `take` で進めて作る）

```python
def test_gate_asks_with_text(self):               # plan_review_regression を受けた盤面 → ask True、gate_text に項目と "respond" の 1 行、b.work("gate.md")
def test_gate_null_means_not_opened(self):        # at fix・gate None → answer を呼ばない、go は p3.fix の ready で決まる
def test_gate_continue_reaches_fixer(self):       # gate {"decision": "continue", "text": "x"} → human_items に continue と x、notes に x、go True
def test_reject_is_stop(self):                    # gate {"decision": "reject", "text": "y"} → halted.by == "answer"、stop True、以後の edge も全部 stop
def test_gate_note_roundtrip(self):               # 一言に引用符・改行・$(・日本語 → human_items の note が 1 バイトも同じ
def test_midgate_always_and_when_needed(self):    # always → 緑でも ask。when_needed → 緑なら ask False、赤か ok False なら ask True、mid None → ask False
def test_mid_gate_stop_is_human_stop(self):       # at review・gate stop → state.stop.by == "human:mid-gate"
def test_stop_flag_stops_at_next_edge(self):      # STOP を置いた後の edge → stop True、state.stop の理由が STOP の理由
def test_stop_flag_and_gate_stop_first_wins(self):  # 関所の stop と STOP が同じ edge に在る → 関所の答えが先に盤面に入り、STOP の理由は trace だけ、Reject を出さない
def test_stop_flag_after_halt_goes_to_trace(self):  # 止めた盤面で STOP が在る → b.stop を呼ばず trace に 1 行、stop True
def test_plan_file_from_outputs(self):            # at fix の plan_file == state.outputs["p2.fix_plan"]["file"]、周 2 の盤面でも out/r2/ の下
def test_judgment_carried_to_later_edges(self):   # at plan で受けた judged の judgment_file・open_units が at fix の返りに在る
def test_edge_script_null_strings(self):          # edge.py を子で起こし、INPUTS_GATE="null" → None として扱う、1 行で 0
def test_edge_script_inputs_constant(self):       # edge.py の INPUTS の組が上の 6 つ（Task 17 の配線の試験が使う）
```

- [ ] **Step 2: 赤を確かめる** — Run: `nice -n 19 sh works/tests/run.sh -k test_halt` / Expected: FAIL（足した試験）
- [ ] **Step 3: 書く** — 盤面を読むのは `open_board` の 1 回。`answer`・`stop` は盤面の層の口をそのまま呼ぶ（止め方の意味は engine と同じ。盤仕様 BL10・BL11）。
- [ ] **Step 4: 緑を確かめる** — Run: `nice -n 19 sh works/tests/run.sh` / Expected: `OK`
- [ ] **Step 5: Commit** — `git commit -m "feat(works): 境の節（止め札・関所の答え・次のブロックを盤面から決める）"`

---

### Task 10b: h-plan の仕事（包みの確かめ・判定の渡し替え・直す物が無い周の締め。T6・T10a の後）

裁定 TA3・TA6・TA9。包みの確かめ（手順 1）は、T22 が `h-judge`（前提の役の後・判定の前）へ移す。この Task では `h-plan` に置き、T22 が関数ごと `judge_edge` へ動かして、この Task の試験 `test_adapter_missing_stops_before_writer`・`test_adapter_optional_passes` の `at` を `judge` に替える。

**Files:**
- Modify: `works/.shared/core/halt.py`（`plan_edge`）
- Test: `works/tests/test_halt.py`（足す）

**Interfaces:**
- Consumes: `entry.take`・`entry.empty_fix_reply`、`reads.adapter_seen`、T10a の `edge`。
- Produces（`halt.py`）: `plan_edge(b, board_dir: Path, repo: Path, *, run_id: str, adapter_mode: str, judged: dict | None) -> dict` — `edge` の手順 5 の中身。順:
  1. 包みの確かめ: `adapter_seen(board_dir, run_id)` が偽で `adapter_mode != "optional"` → `b.stop("包みが通っていない: …（SKILL の 1 行）", by="works:adapter")`、`{stop: True}`。
  2. 判定の控え: `judged` を `b.work("judged.json")` に書く（後ろの境の節が `judgment_file`・`open_units` を返すため。M4）。
  3. 判定の渡し替え: 盤面の `p2.diagnose` が今の周に済んでいなければ、`judged.judgment_file` を読んで `take(board_dir, "p2.diagnose", 判定, repo)`。`ok: False` なら `b.stop("盤面が判定を受けない: <文>", by="works:judge-bridge")`、`{stop: True}`。
  4. `p2.fix_plan` が `ready` なら `go: True`。`p3.fix` が `ready` で `p2.fix_plan` が `na` なら `take(board_dir, "p3.fix", empty_fix_reply(), repo)` し、trace に `by: "works:empty-fix"` を 1 行書いて `go: False`（TA6）。

- [ ] **Step 1: 失敗する試験を書く**

```python
def test_plan_goes_when_units_open(self):         # judge_ok を渡した後 → go True、盤面の p2.diagnose が done
def test_bridge_skips_when_done(self):            # 盤面に p2.diagnose が既に在る → 2 度受けない（trace に accept が 1 行）
def test_bridge_rejected_stops_before_writer(self):  # 盤面の型に合わない judgment.json → stop True、state.stop.by == "works:judge-bridge"
def test_no_fix_closes_round(self):               # judge_no_fix → go False、p3.fix が空の返答で done、ready に p4.ci、trace に works:empty-fix（TA6）
def test_adapter_missing_stops_before_writer(self):  # launches.jsonl にこの run の行が無い・adapter "" → stop True、by "works:adapter"
def test_adapter_optional_passes(self):           # 同じで adapter "optional" → stop False
```

- [ ] **Step 2: 赤を確かめる** — Run: `nice -n 19 sh works/tests/run.sh -k test_halt` / Expected: FAIL（足した試験）
- [ ] **Step 3: 書く**
- [ ] **Step 4: 緑を確かめる** — Run: `nice -n 19 sh works/tests/run.sh` / Expected: `OK`
- [ ] **Step 5: Commit** — `git commit -m "feat(works): 境の節 h-plan（包みの確かめ・判定の渡し替え・直す物が無い周の締め）"`

---

### Task 11: blk-plan（T9・T6 の後。並べてよい: T12・T13・T14）

仕様 3.1。修正案（読むだけ）と事前審査（読むだけ）の 2 つの役。人の関所の項目は盤面の `p2.human_gate`（機械の節）が組むので、このブロックは持たない。今の共有の試験で通る YAML なので、このブロックだけは YAML と筋書きまで今 commit する（TA2）。

**Files:**
- Create: `works/blk-plan/blk-plan.yaml`・`works/blk-plan/commands/plan.md`・`works/blk-plan/commands/plan-review.md`（0.21.0 の `prompts/review-loop/p2.fix_plan.md`・`p2.plan_review.md` から、盤面に無い物を削って書き直す。1 本目の仕様 6 節と同じやり方）
- Create: `works/blk-plan/scripts/accept_plan.py`・`accept_review.py`・`reads.py`・`collect.py`
- Create: `works/blk-plan/fixtures/pass.stubs.yaml`・`plan-rejected.stubs.yaml`
- Modify: `works/.shared/core/plan.py`（`collect`）
- Create: `works/tests/replies/plan_ok.json`・`plan_missing_unit.json`・`plan_two_units_one_plan_dup.json`・`plan_review_ok.json`・`plan_review_regression.json`・`plan_review_no_add.json`（実物の盤面 wt-ci-skip の `out/r1/p2.fix_plan.json`・`p2.plan_review.json` の形から、種の stats.py に合わせて手で直す）
- Test: `works/tests/test_blk_plan.py`

**Interfaces:**
- Consumes: `entry.main_take`・`entry.snapshot`、`reads.main_for`、`accept.role_schema("p2.fix_plan")`・`role_schema("p2.plan_review")`、`node_marker.mark`（T2。`output_format` には印つきの値を貼る。TA20）。
- Produces（ブロックの入口）: `judgment_file`（必須）・`base_rev`（既定 `""`）・`policy_paste`・`policy_path`（既定 `""`）。
- Produces（中の節。輪の中の id は全部の include をまたいで一意。台帳 R19）:
  1. `plan-snap`（script）: `entry.snapshot(board, "plan-snapshot.json", repo)`（置き場は `b.work`。今の周）
  2. `plan-loop`（`loop_group`、`max_iterations: 3`、`until_bash: test $plan-accept.output.ok = true`）: 役 `plan`（`command: plan`・`allowed_tools: [Read, Grep, Glob]`・`settingSources: []`・sandbox・`idle_timeout: 1728000000`・`output_format` = `mark(role_schema("p2.fix_plan"), "plan")`）＋ `plan-accept`（`script: accept_plan` → `main_take("p2.fix_plan", snapshot_name="plan-snapshot.json")`）
  3. `review-snap`（script）
  4. `plan-review-loop`: 役 `plan-review`（読むだけ）＋ `plan-review-accept`（`main_take("p2.plan_review", snapshot_name="review-snapshot.json")`）
  5. `plan-reads`（script。`reads.main_for` を `plan`・`plan-review` の 2 つに）
  6. `collect`（script）: `plan.collect(board)` → `{ok, plan_file, review_file, asks_human, gate_kinds, reads_file}`（`plan_file`・`review_file` は `state.outputs[節]["file"]`）
- 各 script は読む `INPUTS_*` を定数 `INPUTS` に持つ（TA16）。
- 指示書が読む物: `$INPUTS.judgment_file`・`$INPUTS.policy_path`（修正案）・`$INPUTS.policy_paste`（事前審査）・`$LOOP_PREV.plan-accept.output.reason`（台帳 R16）。事前審査は案のファイルのパス（`$plan-accept` の出口の `out_file`＝盤面の `state.outputs["p2.fix_plan"]["file"]`）を読む。

- [ ] **Step 1: 失敗する試験を書く**

```python
def test_plan_ok_accepted(self):                  # 判定を受けた盤面に plan_ok → ok、ready に p2.plan_review
def test_plan_missing_unit_rejected(self):        # 単位の書き落とし → ok False、文に単位の key（写しの fix_plan_covers_units の文）
def test_plan_dup_unit_rejected(self):            # 1 単位が 2 案に → ok False
def test_plan_review_ok_passes_gate(self):        # plan_review_ok → settle の後 asking None、ready に p3.fix
def test_plan_review_regression_asks(self):       # regression の穴 → asking の kinds に regression、collect の asks_human True
def test_plan_review_entrance_needs_no_add(self): # no_add の無い入口の穴 → ok False
def test_plan_narrows_asks(self):                 # 案の narrows → asking（事前審査が穴 0 件でも）
def test_policy_change_asks(self):                # start の後に方針の文書を書き換える → asking の kinds に policy_changed
def test_readonly_tree_changed_rejected(self):    # plan-snap の後に作業ツリーを変える → plan-accept が ok False
def test_output_format_matches_graph(self):       # blk-plan.yaml の plan・plan-review の output_format を strip した値 == role_schema の値、印の名が plan・plan-review
def test_loop_ids_unique_across_blocks(self):     # blk-plan の輪の中の id が他の全部のブロックの輪の中の id と重ならない
def test_roles_only_ai_in_their_loop(self):       # 各輪の AI の節は役 1 つだけ、context を持たない（TA13 の形）
def test_prompts_read_loop_prev_reason(self):     # plan.md に $LOOP_PREV.plan-accept.output.reason、plan-review.md に $LOOP_PREV.plan-review-accept.output.reason
def test_fixture_stubs_match_samples(self):       # pass.stubs.yaml の plan・plan-review が plan_ok・plan_review_ok と同じ
```

- [ ] **Step 2: 赤を確かめる** — Run: `nice -n 19 sh works/tests/run.sh -k test_blk_plan` / Expected: FAIL
- [ ] **Step 3: 書く** — 筋書きは 1 本目の流儀（include で入った script の節は stub、`exec-code: true`、`reached` に `collect`）。`plan-rejected` は `plan-accept` の stub を拒否にして輪の形だけを見る（模擬実行は輪を 1 回で済んだと見なす。線 C の MG25）。
- [ ] **Step 4: 緑を確かめる** — Run: `nice -n 19 sh works/tests/run.sh` と `sh works/dev/check.sh` / Expected: 両方緑（blk-plan は今の共有の試験の決まりで通る）
- [ ] **Step 5: Commit** — `git commit -m "feat(works): blk-plan（修正案と事前審査。人の関所の項目は盤面が組む）"`

---

### Task 12: blk-fix を数え直しに替える（スクリプトと指示書。YAML は T17。並べてよい: T11・T13・T14）

仕様 3.2。受け付けを `done("p3.fix")` に替える。数え直しは写しの `fix_covers_open_units`（graph の `p3.fix` の受け付けの検査）が盤面の上で行う。

**Files:**
- Create: `works/.shared/core/recount.py`
- Modify: `works/blk-fix/scripts/accept.py`（`recount.accept_fix` を呼ぶ）・`works/blk-fix/scripts/collect.py`（欄を足すだけ）
- Create: `works/blk-fix/scripts/reads.py`
- Modify: `works/blk-fix/commands/fix.md`（0.21.0 の `p3.fix.md` から、盤面に無い物を削って書き直す。`$INPUTS.plan_file`・`$INPUTS.human_notes`・`$INPUTS.policy_path` を読む）
- Create: `works/tests/replies/fix2_ok.json`・`fix2_count_not_dropped.json`・`fix2_sites_mismatch.json`・`fix2_silent_closure.json`（実物の `out/r1/p3.fix.json` の形から、種の stats.py の 2 つの直しに合わせる）
- Modify: `works/tests/test_blk_fix.py`

**Interfaces:**
- Consumes: `entry.take`、`accept.role_schema("p3.fix")`、`accept.touched_files(repo, rev)`。
- Produces（`recount.py`）:
  - `FIX_NODE = "p3.fix"`、`FIX_OUTPUT_FORMAT = mark(role_schema("p3.fix"), "fix")`（T17 で YAML に貼る値。試験が一致を見る。`rejudge_requested` の欄は graph の schema に元から在り、T23 の再審の起点になる）
  - `accept_fix(reply: dict, board: Path, base_rev: str, repo: Path) -> dict` — `take(board, "p3.fix", reply, repo)` の結果に、1 本目の出口のための `changes`（`[{unit_key, files, what}]`。`p3.fix` の `changes[]` から写す）を足す。拒否のときの `changes` は空（1 本目と同じ）。
  - `collect(board: Path, accepted: dict, changed: dict) -> dict` — 1 本目の `{ok, files, changes_file}` を全部残し、`fix_file`（`state.outputs["p3.fix"]["file"]`）・`not_done`（件数）・`coverage`（単位ごとの `{before, after}`。盤面の `loop.coverage_after` から）・`reads_file` を足す。`changes_file` は `b.work("changes.json")`。
  - 各 script は読む `INPUTS_*` を定数 `INPUTS` に持つ（TA16）。
- Produces（ブロックの入口。T17 で YAML に書く）: 1 本目の `judgment_file`・`open_units`・`base_rev` に、`plan_file`・`human_notes`・`policy_path`（どれも既定 `""`）を足す。

- [ ] **Step 1: 失敗する試験を書く**

```python
def test_recount_accepts_real_fix(self):          # 種の stats.py を直した作業ツリーと fix2_ok → ok、盤面の loop.coverage_after に 2 単位、ready に p3.delta_review
def test_recount_rejects_count_not_dropped(self): # 直していない作業ツリー → ok False、文に単位の key と数
def test_recount_rejects_sites_mismatch(self):    # closure.sites の数と母数が合わない → ok False
def test_recount_rejects_silent_closure(self):    # changes が在るのに fix_closure が not_applicable → ok False（写しの文）
def test_human_notes_recorded_before_fix(self):   # 関所で continue "x" を答えた盤面 → p3.fix の受け付けが human_items を読んで通る
def test_wrote_refs_reads_from_board(self):       # 盤面に reads.jsonl（実物の行の形）を置く → 数え直しの wrote_refs_reads の state が read
def test_exit_keeps_v1_fields(self):              # collect の返りの鍵 ⊇ {ok, files, changes_file}、changes.json が 1 本目の形
def test_output_format_constant_matches_graph(self):  # strip(FIX_OUTPUT_FORMAT) == role_schema("p3.fix")、印の名が fix
def test_fix_prompt_reads_inputs(self):           # fix.md に $INPUTS.plan_file・$INPUTS.human_notes・$INPUTS.policy_path・$LOOP_PREV.fix-accept.output.reason
```

- [ ] **Step 2: 赤を確かめる** — Run: `nice -n 19 sh works/tests/run.sh -k test_blk_fix` / Expected: FAIL
- [ ] **Step 3: 書く** — `assert_changed.py` は変えない。1 本目の試験のうち、偽の盤面の `check_fix` を前提にしていた物は、同じ主張を盤面の上で確かめる形に書き直す（主張を減らさない）。
- [ ] **Step 4: 緑を確かめる** — Run: `nice -n 19 sh works/tests/run.sh` と `sh works/dev/check.sh` / Expected: 両方緑（YAML はまだ 1 本目のままで、模擬実行は受け付けを stub するので変わらない）
- [ ] **Step 5: Commit** — `git commit -m "feat(works): 修正の受け付けを盤面の数え直し（fix_covers_open_units）に替える"`

---

### Task 13: blk-delta と blk-refix（スクリプトと指示書。YAML は T17。並べてよい: T11・T12・T14）

仕様 3.3・3.4。版を固める・差分を切る・義務を組むのは盤面の機械の節（`p3.fix_delta`・`p3.delta_owed`・`p3.fix_delta2`・`p3.delta_owed2`）。ブロックは役の返答を渡し、盤面が書いた差分のパスを役に見せるだけ。

**Files:**
- Create: `works/.shared/core/refix.py`
- Modify: `works/blk-delta/scripts/cut.py`（盤面の `loop.fix_delta` のファイルを出す）・`accept.py`（`refix.accept_review(n=1)`）・`collect.py`（欄を足す）
- Create: `works/blk-delta/scripts/reads.py`
- Modify: `works/blk-delta/commands/delta-review.md`（0.21.0 の `p3.delta_review.md` から。事前審査の穴と修正役の `plan_faces` を読む）
- Create: `works/blk-refix/scripts/cut2.py`・`accept_refix.py`・`accept_review2.py`・`route.py`・`reads.py`・`collect.py`
- Create: `works/blk-refix/commands/refix.md`・`review2.md`・`refix2.md`（0.21.0 の `p3.delta_fix.md`・`p3.delta_review2.md`・`p3.delta_fix2.md` から）
- Create: `works/tests/replies/fix2_delta_review_faces.json`・`fix2_delta_review_none.json`・`fix2_delta_review_policy_kind.json`・`fix2_delta_fix_ok.json`・`fix2_delta_fix_missing_key.json`・`fix2_delta_review2_ok.json`・`fix2_delta_review2_faces.json`・`fix2_delta_fix2_ok.json`
- Modify: `works/tests/test_blk_tests_delta.py`（審査の分）
- Test: `works/tests/test_blk_refix.py`

**Interfaces:**
- Consumes: `entry.take`・`entry.snapshot`、写しの RL の `DELTA_PASSES`（`rules_module()` から引く。節の名前を works に持たない。仕様 7 節）。
- Produces（`refix.py`）:
  - `passes() -> dict[int, dict]` — `DELTA_PASSES` から `{n: {"cut", "review", "owed", "fix", "state_key", "owed_key"}}`。
  - `cut(board: Path, n: int, repo: Path) -> dict` — 盤面の `loop.<state_key>`（今の周）のファイルと触ったファイルを返し、読むだけの役の前の写しを撮る。返り `{ok, files, diff_file, rev}`。無ければ `{ok: False, reason}`（配線の誤りなので呼ぶ側は 2）。
  - `accept_review(reply, board, base_rev, repo, *, n: int) -> dict` — `take(board, passes()[n]["review"], reply, repo, snapshot_name=f"review{n}-snapshot.json")`。
  - `accept_fix(reply, board, base_rev, repo, *, n: int) -> dict` — `take(board, passes()[n]["fix"], reply, repo)`。
  - 各 script は読む `INPUTS_*` を定数 `INPUTS` に持つ（TA16）。
  - `route(board: Path) -> dict` — `{"review2": bool, "refix2": bool, "owed": int, "owed2": int}`（盤面の `ready` と `loop.delta_owed`・`delta_owed2`）。
  - `collect_delta(board) -> dict` — 1 本目の `{ok, faces, review_file, diff_file}` に `owed`・`fix_rev`・`reads_file` を足す。
  - `collect_refix(board) -> dict` — `{ok, handled_file, review2_file, owed2, fixed2, files, reads_file}`。`review2_file` は 2 回目の審査を回さなかった run では空。
- Produces（blk-refix の中の節。T17 で YAML に書く）: `refix-loop`（役 `refix`・書く）→ `route1`（`route`）→ `cut2`（`when: $route1.output.review2 == true`）→ `review2-loop`（役 `review2`・読むだけ。`when:` 同じ）→ `route2`（`trigger_rule: none_failed_min_one_success`）→ `refix2-loop`（役 `refix2`・書く。`when: $route2.output.refix2 == true`）→ `refix-reads` → `collect`。**3 往復目は無い**（graphloops と同じ）。役の `output_format` は `mark(role_schema(節), 役の名)`（`refix`・`review2`・`refix2`。TA20）。
- 手直し 2 回目が `fixed` と言った穴の検算の行き先は報告の `next-request.json`（T15。仕様 3.4）。

- [ ] **Step 1: 失敗する試験を書く**

```python
# test_blk_tests_delta.py（審査の分）
def test_cut_reads_board_fix_delta(self):         # fix2_ok を受けた盤面 → cut(1) の diff_file == 盤面の loop.fix_delta.file、files が stats.py（名前を組み立てない）
def test_review_faces_make_owed(self):            # fix2_delta_review_faces → settle の後 loop.delta_owed に穴、ready に p3.delta_fix、collect_delta の owed ≥ 1
def test_review_none_skips_refix(self):           # fix2_delta_review_none（faces_none）→ ready に p3.delta_fix が無い、owed 0
def test_review_policy_kind_rejected(self):       # regression・policy の語の穴 → ok False（事前審査だけの kind）
def test_review_readonly_tree_changed(self):      # 写しの後に作業ツリーを変える → ok False
def test_delta_exit_keeps_v1_fields(self):        # collect_delta の鍵 ⊇ {ok, faces, review_file, diff_file}
# test_blk_refix.py
def test_refix_answers_every_owed_key(self):      # fix2_delta_fix_ok → ok、route の review2 は fixed が在れば True
def test_refix_missing_key_rejected(self):        # 義務の key を 1 つ答えない → ok False
def test_cut2_is_refix_only_diff(self):           # 手直しで 1 行変えた後 → cut(2) の差分に修正（p3.fix）の行が無く、手直しの行だけ
def test_review2_then_refix2(self):               # fix2_delta_review2_faces → route の refix2 True → fix2_delta_fix2_ok → ready に p4.ci
def test_no_third_pass(self):                     # 手直し 2 回目の後に穴が残っても ready に 3 回目の節が無い（p4.ci に進む）
def test_route_uses_delta_passes_table(self):     # passes() の節の名前が写しの DELTA_PASSES と同じ（works に名前の写しを持たない）
def test_prompts_read_loop_prev_reason(self):     # refix.md・review2.md・refix2.md がそれぞれの $LOOP_PREV.<役>-accept.output.reason を読む
def test_loop_ids_unique_across_blocks(self):     # refix-loop・review2-loop・refix2-loop の中の id が他の全部のブロックと重ならない
```

- [ ] **Step 2: 赤を確かめる** — Run: `nice -n 19 sh works/tests/run.sh -k test_blk_tests_delta -k test_blk_refix` / Expected: FAIL
- [ ] **Step 3: 書く** — 盤面の差分のファイルの名前は写しの RL が決める（盤仕様 3 節）。works は `loop.<state_key>.file` を読むだけで、名前を組み立てない。
- [ ] **Step 4: 緑を確かめる** — Run: `nice -n 19 sh works/tests/run.sh` と `sh works/dev/check.sh` / Expected: 両方緑
- [ ] **Step 5: Commit** — `git commit -m "feat(works): 差分の審査と 2 往復の手直し（版固めと義務は盤面の機械の節）"`

---

### Task 14: blk-tests に明示の 2 つの形を足す（既定は 1 本目のまま。スクリプト。YAML は T17。並べてよい: T11・T12・T13）

仕様 3.5・裁定 TA4・TA5。**既定の形（`mode: plain`）は 1 本目と線 C の `mutgate` の約束のまま変えない**（審査 I1）: 盤面なし・`cmd` 必須・ログは `$ARTIFACTS_DIR/board/tests.log`・出口 `{ok, green, log}`。

**Files:**
- Modify: `works/blk-tests/scripts/run_tests.py`
- Modify: `works/tests/test_blk_tests_delta.py`（テストの分）

**Interfaces:**
- Consumes: `entry.open_board`・`entry.run_ci`（T7。`run_engine` の返りを全部扱う）・`b.settle()`・`b.work(名)`、`tree_run.run`・`outside_env`、写しの `engine/declared.py`。
- Produces（ブロックの入口。T17 で YAML に書く）: `cmd`（**必須のまま**。1 本目と同じ）・`mode`（`plain`・`mid`・`final`。**既定 `plain`**）。線 A のラインは `mode: mid`・`final` を明示で渡し、`cmd` には `$start.output.test_cmd`（空でよい。空の `cmd` を許すのは `mid`・`final` の時だけ）を渡す。
- Produces（`run_tests.py`）: `INPUTS = ("INPUTS_CMD", "INPUTS_MODE")`（TA16。`INPUTS_MODE` が無い呼び出しは `plain`）。出口は 1 本目の `{ok, green, log}` を全部残し、`mid`・`final` の時だけ `suites`（段ごとの `{name, exit}`）・`by`（`engine`・`role`・`mid`）を足す。
  - `plain`（既定。1 本目と同じ）: 盤面を開かない。`cmd` を `bash -c` で `tree_run` に走らせ、ログは `$ARTIFACTS_DIR/board/tests.log`。`cmd` が空なら節を落とす（1 本目と同じ）。
  - `mid`: 宣言の `suite` が在れば段を 1 つずつ shell を通さずに `tree_run` で、無ければ `cmd` を `bash -c` で走らせる。ログは `b.work("mid-tests.log")`、結果は `b.work("mid-tests.json")`。盤面の節には触らない。
  - `final`: `entry.run_ci(b, "p4.ci", test_cmd=cmd)`（`relaunch` は 1 度だけ呼び直し、`why` だけの返りと任せ先で空の `cmd` は終了コード 1・理由を stderr）→ `settle`。`green` は素材の `status == "clean"`。ログは `run_ci` の返りの `log`（engine が走らせた時は `run_engine` の返りの `runs[].out`、任せ先の時は `b.work("tests.log")`。周の番号を書かない）。
  - どの形も赤で止めない（`ok: True`・`green: False`）。

- [ ] **Step 1: 失敗する試験を書く**

```python
def test_plain_mode_is_mutgate_contract(self):    # 盤面の無い ARTIFACTS_DIR・INPUTS_MODE 無し・cmd だけ → 盤面を作らず（state.json が無い）、log == <ARTIFACTS_DIR>/board/tests.log、
                                                  #   出口の鍵 == {ok, green, log}（線 C の mutgate の include の約束を固定する。線 C の筋書きの log の形と同じ）
def test_plain_mode_empty_cmd_fails(self):        # plain で cmd 空 → 1 本目と同じく節を落とす
def test_mid_runs_declared_suite_without_shell(self):  # 宣言の在る種 → suites に unit、by "mid"、盤面の process.checks が変わらない
def test_mid_runs_cmd_when_no_declaration(self):  # 宣言無し → cmd を bash で、赤（種は赤 2 件）→ green False・ok True
def test_final_by_engine(self):                   # 修正を当てた種・宣言在り → process.checks["p4.ci"].by == "engine"、green True
def test_final_fallback_runs_cmd(self):           # 宣言無し → by "role"、素材が done、green は cmd の結果
def test_final_declaration_changed_relaunches(self):  # 計画の後に宣言を書き換える（差し込み）→ 1 度呼び直して通る
def test_final_empty_cmd_on_fallback_fails(self): # 宣言無し・cmd 空 → 終了コード 1、stderr に理由
def test_final_settles_to_record(self):           # final の後の盤面で p4.record と converge が済み、halted.by == "stop_after_round"
def test_final_log_from_run_engine(self):         # engine が走らせた時の log が run_engine の返りの runs[0].out と同じ（runs/r<N>/ を組み立てない）
def test_exit_keeps_v1_fields(self):              # 出口の鍵 ⊇ {ok, green, log}
```

- [ ] **Step 2: 赤を確かめる** — Run: `nice -n 19 sh works/tests/run.sh -k test_blk_tests_delta` / Expected: FAIL（足した試験）
- [ ] **Step 3: 書く** — `outside_env` は `tree_run` の物を使う（台帳の MERGE NOTE: `run_tests.py` に在った写しは `tree_run.py` に寄せ済み）。
- [ ] **Step 4: 緑を確かめる** — Run: `nice -n 19 sh works/tests/run.sh` と `sh works/dev/check.sh` / Expected: 両方緑
- [ ] **Step 5: Commit** — `git commit -m "feat(works): テストのブロックに明示の形 mid と final を足す（既定は 1 本目と線 C のまま）"`

---

### Task 15: 報告（T10a〜T14・T21・T22 の後）

仕様 6 節・裁定 TA12・TA15。AI は書かない。**記録が検証器を通らない run に `fixed`・`no_fix_needed` を出す道を作らない**（審査 I3）。

**Files:**
- Create: `works/.shared/core/report.py`
- Create: `works/darkfactory/scripts/report.py`
- Create: `works/dev/report.sh`（取り消し・`abandon` の後に盤面から報告を作る）
- Test: `works/tests/test_report.py`

**Interfaces:**
- Consumes: `entry.open_board(allow_halted=True)`・`b.settle()`・`b.finalize()`・`b.run_validator()`（盤面の口。`board_hook.py` の包みも効く）・写しの `report_accepts(b)`・`state.works.not_in_line`・`rounds/works/round-<N>.json`・`b.work("reads-*.json")`・`launches.jsonl`・`b.work("mid-gate-answer.json")`・`record.process.human_items`・`record.process.delta_fix2`・`record.process.traces`（痕跡の欄）・`p3.fix` の `not_done`、`accept.check_request`（試験だけ）、`<ライン>/downgrades.json`・`record.process.parallel_pr`（T21）・`record.process.constraints` と `premises.claims`（T22）・`b.work("rejudge-diff.json")`・`record.process.rejudge`・`loop.rejudge_requested`（T23）、`reads.events_for`（T6）。
- Produces（`report.py`）:
  - `OUTCOMES = ("fixed", "no_fix_needed", "stopped_by_request", "stopped_by_human", "stopped_by_line", "needs_human", "record_invalid", "interrupted")`
  - `gate_record(b) -> dict` — 報告の前の関所（TA15。engine の `cmd_finalize` と同じ順）: 止めていない盤面は先に `settle`（止め札の後に待ちのまま残る節を片付ける。M9）→ `finalize()` → `run_validator()` → `{"exit", "accepted": exit ∈ report_accepts(b), "tail": 出力の末尾, "traces": record.process.traces, "round_closed": p4.record と converge が今の周に済んだか}`。
  - `decide_outcome(b, gate: dict, *, tests: dict | None) -> str` — 順: 止め札 → `stopped_by_request`、関所の `stop`・`reject`（`halted.by == "answer"` か `state.stop.by` が `human:` で始まる）→ `stopped_by_human`、`state.stop.by` が `works:` で始まる → `stopped_by_line`、`gate.accepted` が偽か `round_closed` が偽 → `record_invalid`、`pending_human` が残る → `needs_human`、直す物が無い周 → `no_fix_needed`、他 → `fixed`。**`fixed`・`no_fix_needed` は `accepted` と `round_closed` が真の時だけ**。
  - 報告の部品（線 B の報告も呼ぶ口。線 B の申し送り 3。TA18）: `head_decisions(b, gate) -> list[str]`（冒頭 1。並行 PR の申し送りの下書き・再審で争点でない単位の変化・依頼の実測のうち `仮説` になった物・再審できずに止めた時の問いも、この関数が盤面から組む）・`head_entry(b, start) -> list[str]`（冒頭 2。このラインに無い節の数と一覧のパス、下げている所の数と一覧。下げた物は `declared_downgrades(line)` から）・`head_stop(b) -> list[str]`（冒頭 3）・`head_reads(board_dir, run_id) -> list[str]`（冒頭 4。読んだ証拠と包みの行。出来事が `unverified` なら「出来事: 未確認（P13）」。会話を継いだ起動の数）・`head_where(b) -> list[str]`（冒頭 5。見る所の行。ファイルは `state.outputs[節]["file"]` から）・`head_cost(board_dir, run_id) -> list[str]`（冒頭の後の費用の行）。どれも盤面を書かない。
  - `declared_downgrades(line: str) -> list[dict]` — `PACK/<line>/downgrades.json`（`[{node, what, versus}]`。無ければ `[]`）。
  - `COST_FIELD_VERIFIED = False` — 出来事に節の費用の欄が載るかを P19 で確かめるまで偽。偽の間、`head_cost` は取れた値に「（欄の形は未確認）」を添える。
  - `cost_rows(events: list[dict] | None, launches: list[dict]) -> list[dict]` — `[{node, reported, actual, continued_from}]`。`launches` の `session.mode == "continued"` の起動は、同じ `session.id` の直前の起動の `reported` を引いた値を `actual` にする（〔継試〕: 再開した会話の `total_cost_usd` は累積）。出来事と起動は節の名と順で結ぶ。`events` が None か費用の欄が無ければ `[]`。
  - `build(board_dir: Path, *, judged: dict | None, tests: dict | None, start: dict) -> dict` — `gate_record` → `decide_outcome` → 部品で `report.md`・`next-request.json` を書き、1 本目の `finish` の欄（`ok`・`outcome`・`judgment_file`・在れば `review_file`・`diff_file`・`faces`）に `report_file`・`next_request_file`・`tests_green`・`validator_exit` を足して返す。`record_invalid` の時は冒頭 1 に検証器の出力の末尾と `traces` を出す。
  - `report.md` の冒頭の並び: 1. 人が決めること（関所の答え・テストの赤・次の run に渡す物の件数・`needs_human` の問い）2. 入口・段・決めた人・gates と、このラインに無い節の数と一覧のパス 3. 止めたか（止め札・関所の stop・機械の止め。理由と止めた所）4. 読んだ証拠と包み（`sources` の有無・素通しの起動の数と理由・「包み無し」）5. 見る所（判定・修正案・事前審査・審査・差分のファイルと run の worktree の場所）。続けて周の記録の検証器の終了コードと、TA14 と仕様 10 節の「このラインに無い」の一覧。
  - `next_request(board) -> list[dict]` — 手直し 2 回目が `fixed` と言った穴（検算が要る）・`declared` で残した穴・修正の `not_done`・テストが赤なら赤の事実・再審されずに残った異議の文（写し直しの前で再審の節が無い run と、会話が無くて止めた run。盤面の異議の欄から）・第三の目が「方針の岐路」と書いた争点。どれも 1 本目の依頼の型（`where`・`text`、任意で `mechanism` など）。
- Produces（`darkfactory/scripts/report.py`）: `INPUTS = ("INPUTS_JUDGED", "INPUTS_TESTS", "INPUTS_START")`（TA16。文字列 `null` は None）と `ARTIFACTS_DIR` を読み、`build` の結果を 1 行で出して 0（`record_invalid` も 0。結末で知らせる）。盤面が開けないときだけ理由を stderr に 1 行出して 1。
- Produces（`dev/report.sh <run-id>`）: `stop.sh` と同じ組み方で盤面を探し、`report.build(..., interrupted=True)` を当てる。結末は `interrupted`（冒頭 3 に「run が途中で終わった: 取り消し・abandon・役の出し直しの上限のどれか。Archon の run の状態は <状態>」）。記録の関所（`gate_record`）は同じく通し、通らなければ冒頭 1 に出す（M8）。

- [ ] **Step 1: 失敗する試験を書く**（盤面は T10a〜T14 の試験と同じ組み方で、道ごとに作る）

```python
def test_fixed_run_head_order(self):              # 標準の全部の道 → outcome fixed、report.md の冒頭 5 節の見出しがこの順、validator_exit ∈ report_accepts
def test_no_fix_run(self):                        # judge_no_fix → outcome no_fix_needed、周の記録（rounds/round-<N>.json）が在る（TA6）
def test_validator_rejects_never_fixed(self):     # validator_runner に受理集合の外の exit を返す偽を渡した盤面（board_hook で差す）→ outcome record_invalid、冒頭 1 に出力の末尾と traces
def test_round_not_closed_never_fixed(self):      # p4.record の record_round が ok False で settle が止まった盤面（halted でも asking でもない）→ record_invalid、fixed を出さない
def test_settle_before_finalize_after_stop(self): # 止め札で止めた盤面 → report.* の節の扱いが settle の後の形（M9）、outcome stopped_by_request
def test_head_parts_callable(self):               # head_reads・head_where を盤面だけで呼べ、盤面の全ファイルの sha が変わらない（線 B が呼ぶ）
def test_round_two_paths(self):                   # 周 2 の盤面で build → report.md の見る所のパスが out/r2/ の下（周を仮定しない）
def test_stopped_by_request(self):                # 止め札 → outcome stopped_by_request、冒頭 3 に理由と止めた境の節
def test_stopped_by_human_gate_and_mid(self):     # 関所の stop・reject、中の関所の stop → stopped_by_human、冒頭 1 に一言
def test_stopped_by_line(self):                   # 包みが無い → stopped_by_line、冒頭 4 に「包みが通っていない」
def test_needs_human(self):                       # 最後の settle で pending_human が残った盤面 → needs_human、冒頭 1 に問い
def test_not_in_line_listed(self):                # 冒頭 2 の数 == state.works.not_in_line の数、p0.parallel_pr と p0.purpose の行が一覧に在る
def test_next_request_passes_v1_intake(self):     # next-request.json を一時の盤面で accept.check_request → ok（次の run にそのまま渡せる）
def test_next_request_keys_roundtrip(self):       # 穴の key に引用符・日本語・$( → next-request.json の text に 1 バイトも同じで在る
def test_exit_keeps_finish_fields(self):          # 返りの鍵 ⊇ 1 本目の finish の必須の欄、outcome ∈ OUTCOMES
def test_report_sh_after_cancel(self):            # 盤面だけ残った run（halted でない）に report.sh → report.md ができ、outcome == "interrupted"、冒頭 3 に「途中で終わった」の 1 行
def test_handover_drafts_and_downgrade(self):     # p0.parallel_pr を任せ先で受けた盤面（conflicts 2 件・note つき）→ 冒頭 1 に 2 件の下書き、冒頭 2 に downgrades.json の 1 行
def test_rejudge_undisputed_changes_head(self):   # rejudge-diff.json の undisputed_changed が 1 件 → 冒頭 1 にその単位の key と前後
def test_rejudge_session_stop_asks(self):         # state.stop.by == "works:rejudge-session" → outcome stopped_by_line、冒頭 1 に問い、next-request.json に異議の文
def test_premises_claims_hypothesis_head(self):   # 依頼の measured が仮説になった制約 1 件 → 冒頭 1 に where と「測り直せなかった」
def test_cost_subtracts_continued(self):          # 出来事の見本（judge 0.0284・rejudge 0.0615）と launches（rejudge が continued of judge・同じ id）→ rejudge の actual が約 0.0331、行に「判定役の累積を引いた」
def test_cost_unavailable_line(self):             # events None → 費用の行が「取れない」の 1 行
```

- [ ] **Step 2: 赤を確かめる** — Run: `nice -n 19 sh works/tests/run.sh -k test_report` / Expected: FAIL
- [ ] **Step 3: 書く** — 文は機械の定型だけ。検証器は `gate_record` で必ず 1 度走らせる（`rounds/` の記録から読むだけで済ませない。TA15）。
- [ ] **Step 4: 緑を確かめる** — Run: `nice -n 19 sh works/tests/run.sh` / Expected: `OK`
- [ ] **Step 5: Commit** — `git commit -m "feat(works): 機械が組む短い報告と、次の run に渡す依頼の下書き"`

---

### Task 16: 通しの試験（Archon を使わず、スクリプトを線の順に回す。全部の後）

切り替え（T17）の前に、線の全部の道を本物のスクリプトと盤面で通す。Archon の配線は T17 の模擬実行で見る。

**Files:**
- Modify: `works/tests/linekit.py`（`run_line`）
- Test: `works/tests/test_line_a.py`

**Interfaces:**
- Produces（`linekit.py`）:
  - `LINE_ORDER: list[dict]` — 線の節の並び（`{id, kind: "script"|"include"|"approval", script?, block?, at?, with: {鍵: 出どころ}}`）。T17 の YAML はこの並びと同じに書き、T17 の試験 `test_line_order_matches_linekit` が YAML と突き合わせる（手で 2 か所に書き写したまま放さない。TA16）。
  - `run_line(tmp: Path, *, replies: dict[str, dict | list[dict]], gates: dict[str, dict | None], inputs: dict, stop_at: str | None = None, edits: dict[str, callable] | None = None, pr_runner=None) -> dict`（T23 が `sessions` を足す）（`pr_runner` は `p0.parallel_pr` の engine の走りを差す偽。交差を返せば任せ先に落ちる） — `start.py` → 並行 PR の任せ先（落ちた時だけ）→ 前提 → 判定（1 本目の `blk-judge` の受け付けと `collect` を子で）→ 境の節と各ブロックのスクリプトを、`LINE_ORDER` の順で子のプロセスとして回す。環境変数は各 script の定数 `INPUTS` の名前だけを、`LINE_ORDER` の `with:` の出どころから組む（定数に無い名前を渡さない）。役の返答は `replies[役]`（配列なら拒否 → 出し直しの順）、役が作業ツリーに当てる変更は `edits[役]`、関所の答えは `gates[関所]`（None は開かなかった）、`stop_at` の境の節の前に止め札を置く。返り `{outcome, report, board_dir, trail: [節の id]}`。

- [ ] **Step 1: 失敗する試験を書く**

```python
def test_standard_full_path(self):                # 修正案 → 事前審査（穴なし）→ 修正 → 中のテスト → 中の関所 continue → 審査（穴）→ 手直し → 2 回目の審査 → 手直し 2 回目 → 最後のテスト
                                                  #   → outcome fixed、trail が仕様 2 節の順、halted.by == "stop_after_round"、N = state.round で rounds/round-<N>.json と rounds/works/round-<N>.json
def test_no_fix_path(self):                       # 判定が直す物なし → trail に planning・fixing・reviewing・refixing が無く testing が在る、outcome no_fix_needed
def test_policy_gate_continue(self):              # plan_review_regression → policy-gate が開き continue "範囲" → 修正役の入力に "範囲"、human_items に 1 行
def test_policy_gate_stop_and_reject(self):       # stop・reject のどちらも → trail の最後が report、outcome stopped_by_human
def test_mid_gate_when_needed_green_skips(self):  # mid_gate=when_needed・緑 → mid-gate が開かない
def test_mid_gate_stop(self):                     # 中の関所 stop → reviewing が無い、stopped_by_human
def test_stop_flag_each_edge(self):               # stop_at を 9 つの境の節で 1 つずつ（T23 の後は 10）→ どれも outcome stopped_by_request、止めた境の節が報告に
def test_rejected_then_accepted(self):            # 修正の返答を [fix2_count_not_dropped, fix2_ok] → 2 回目で通り、盤面の trace に拒否 1・受け付け 1
def test_no_silent_gap(self):                     # 標準・直す物なし・止め札・関所の stop の各道の後: graph の全部の節が、周の箱の done・na・skipped のどれかに在るか、
                                                  #   止めた後の待ちとして halted か state.stop の理由を持つ（止めた道にも当てる。M9）
def test_env_only_declared_inputs(self):          # run_line が子に渡した INPUTS_* の名前 ⊆ その script の定数 INPUTS（偽の子で受けた環境を記録して見る）
def test_absent_nodes_in_round_note(self):        # rounds/works/round-<N>.json（N = state.round）の not_in_line == 表の absent の全部
def test_blk_judge_unchanged_path(self):          # 判定は 1 本目の受け付けのまま（judgment.json）で、盤面には境の節が渡している（trace の by）
def test_premises_before_judge(self):             # trail で premising が judging より前、判定役の入口 premises_file == state.outputs["p0.premises"]["file"]
def test_parallel_pr_fallback_path(self):         # pr_runner が交差 1 件 → pr-checking が走り、handed_over false の返答で通り、報告の冒頭 1 に下書き・冒頭 2 に下げた行
def test_parallel_pr_engine_only(self):           # pr_runner が交差 0 → pr-checking が trail に無い、process.checks["p0.parallel_pr"].by == "engine"
def test_objection_waits_for_recopy(self):       # 修正の返答に rejudge_requested（写し直しの前）→ 再審の節は absent で走らず、報告の冒頭 2 の「このラインに無い節」に再審の行、異議の文は next-request.json
```

- [ ] **Step 2: 赤を確かめる** — Run: `nice -n 19 sh works/tests/run.sh -k test_line_a` / Expected: FAIL
- [ ] **Step 3: 書く・直す** — ずれが出たら、直すのはスクリプトとモジュール（試験の主張は減らさない）。この Task で直したファイルは、そのファイルを作った Task の持ち物の範囲内。
- [ ] **Step 4: 緑を確かめる** — Run: `nice -n 19 sh works/tests/run.sh` / Expected: `OK`
- [ ] **Step 5: Commit** — `git commit -m "test(works): 線 A の全部の道をスクリプトと盤面で通す（Archon を使わない通しの試験）"`

---

### Task 17: 切り替え（YAML・筋書き・共有のファイル。線 A の切り替えの共有の commit。T23・T25 は後に各々 1 commit で触る）

裁定 TA2・TA13・TA16。この Task だけが共有のファイルに触る。途中で commit しない（手順ごとに試験を回し、最後に 1 commit）。**審査の区切り**: Step 2・3・4 の終わりで試験を回し、その手順の差分を審査役（opus）が読んでから次へ進む（1 commit のまま、審査は 3 回）。

**Files:**
- Modify: `works/blk-fix/blk-fix.yaml`（入口に `plan_file`・`human_notes`・`policy_path`、役 `fix` の `output_format` を `recount.FIX_OUTPUT_FORMAT` の値に、`fix-reads` を `collect` の前に、`collect` の出口に足した欄）・`works/blk-fix/fixtures/*.stubs.yaml`
- Modify: `works/blk-delta/blk-delta.yaml`（`cut` を盤面から、`review` の `output_format` を `mark(role_schema("p3.delta_review"), "review")` に、入口に `policy_paste`、`review-reads`、出口の欄）・`works/blk-delta/fixtures/*.stubs.yaml`
- Modify: `works/blk-tests/blk-tests.yaml`（入口 `mode` を足す。既定 `plain`。`cmd` は必須のまま。出口は 1 本目の必須の欄のまま、`suites`・`by` は任意の欄で足す）・`works/blk-tests/fixtures/*.stubs.yaml`（1 本目の `green` はそのまま、`mid`・`final` を 1 本ずつ足す）
- Create: `works/blk-refix/blk-refix.yaml`・`works/blk-refix/fixtures/one-pass.stubs.yaml`・`two-passes.stubs.yaml`
- Modify: `works/darkfactory/darkfactory.yaml`（下の形）・`works/darkfactory/fixtures/*.stubs.yaml`（下の 10 本）
- Create: `works/blk-premises/blk-premises.yaml`・`works/blk-premises/fixtures/pass.stubs.yaml`（T22）・`works/blk-pr/blk-pr.yaml`・`works/blk-pr/fixtures/pass.stubs.yaml`（T21）。どちらも Bash を持つ読むだけの役を持ち、今の共有の試験の決まりでは通らないので、YAML はこの commit で入れる（スクリプトと指示書と試験は各 Task で入っている）
- Delete: `works/darkfactory/scripts/finish.py`（`report.py` が継ぐ）
- Modify（共有）: `works/tests/test_yaml_rules.py`（書く役の一覧・役の一覧・TA13 の役の輪の決まり・下の 3 つの検査）・`works/tests/yaml_bad/`（新しい検査に 1 本ずつ）・`works/tests/yaml_good/all_kinds.yaml`（`decisions` の関所）・`works/tests/test_line.py`（新しい線の形・筋書き・出口）・`works/dev/real-run.sh`（`CLAUDE_BIN_PATH` を包みに、`WORKS_REAL_CLAUDE` を本物の claude に）・`works/skills/works/SKILL.md`・`works/README.md`・`works/archon-plugin.json`（入口は `darkfactory` のまま。支えの工程に `blk-plan`・`blk-refix` が在ることの確かめだけ）・`works/docs/specs/2026-09-26-darkfactory-design.md`（冒頭に「続きの仕様: 2026-09-27-darkfactory-single-run-design.md」の 1 行）

**Interfaces:**
- Produces（`darkfactory.yaml`。`interactive: true`、`returns: report`、`outcome_field: ok`）:
  - 入力: `request`（必須）・`test_cmd`・`thickness`（既定 `標準`）・`gates`・`mid_gate`（既定 `always`）・`adapter`・`policy_md`（既定はどれも `""` か上の値）
  - **線 C の include の約束を変えない**: `mutgate/mutgate.yaml` の `control`（`include: blk-tests`・`with: {cmd: $INPUTS.test_cmd}`）は既定の `mode: plain` で 1 本目と同じに動く（T14 `test_plain_mode_is_mutgate_contract`）。
  - 節（合流の節は `depends_on: [start, <前の境の節>, <前のブロック>]` と `trigger_rule: none_failed_min_one_success`）。`with:` は全部いつも走る節（`start`・境の節）から取る（M4）:

```
launch        approval（decisions なし。文言に「続けるには archon workflow approve <id> --detach」）
start         script start          depends_on [launch]
pr-checking   include blk-pr        depends_on [start]   when: "$start.output.pr_go == true"   with: base_rev: $start.output.base_rev
premising     include blk-premises  depends_on [start, pr-checking]   when: "$start.output.premises_go == true"   with: request_file・base_rev: $start.output の欄
h-judge       script edge (at judge) depends_on [start, pr-checking, premising]   with: at: judge・adapter・mid_gate: $start.output の欄
judging       include blk-judge     depends_on [start, h-judge]   when: "$h-judge.output.go == true"
                                    with: request: $INPUTS.request・base_rev・policy_paste: $start.output の欄・premises_file: $h-judge.output.premises_file
h-plan        script edge (at plan) depends_on [start, h-judge, judging]      with: at: plan・judged: {from: "$judging.output", if_skipped: null}・adapter・mid_gate: $start.output の欄
planning      include blk-plan      when: "$h-plan.output.go == true"   with: judgment_file: $h-plan.output.judgment_file・base_rev: $start.output.base_rev・
                                    policy_paste・policy_path: $start.output の欄
h-gate        script edge (at gate) depends_on [start, h-plan, planning]
policy-gate   approval decisions [approve, continue, stop, reject]   when: "$h-gate.output.ask == true"   文言は $h-gate.output.gate_text
h-fix         script edge (at fix)  depends_on [start, h-gate, policy-gate]   with: gate: {from: "$policy-gate.output", if_skipped: null}
fixing        include blk-fix       when: "$h-fix.output.go == true"   with: judgment_file・open_units・plan_file・human_notes: $h-fix.output の欄・
                                    base_rev・policy_path: $start.output の欄
h-mid         script edge (at mid)  depends_on [start, h-fix, fixing]      （T23 が h-rejudge と rejudging をここに挟む）
mid-testing   include blk-tests     when: "$h-mid.output.go == true"   with: mode: mid・cmd: $start.output.test_cmd
h-midgate     script edge (at midgate) depends_on [start, h-mid, mid-testing]   with: mid: {from: "$mid-testing.output", if_skipped: null}
mid-gate      approval decisions [approve, continue, stop, reject]   when: "$h-midgate.output.ask == true"   文言は $h-midgate.output.gate_text
h-review      script edge (at review) depends_on [start, h-midgate, mid-gate]   with: gate: {from: "$mid-gate.output", if_skipped: null}
reviewing     include blk-delta     when: "$h-review.output.go == true"   with: base_rev・policy_paste: $start.output の欄
h-refix       script edge (at refix) depends_on [start, h-review, reviewing]
refixing      include blk-refix     when: "$h-refix.output.go == true"   with: base_rev・policy_paste・policy_path: $start.output の欄
h-tests       script edge (at tests) depends_on [start, h-refix, refixing]
testing       include blk-tests     when: "$h-tests.output.go == true"   with: mode: final・cmd: $start.output.test_cmd
report        script report         depends_on [start, h-tests, testing]   with: judged・tests は {from:, if_skipped: null}、start: {from: "$start.output"}
```

- Produces（`test_yaml_rules.py` に足す 4 つの検査。試し P7・P8・P16、審査 M5）:
  1. `decisions` を持つ関所は `reject` を持つ。
  2. 関所の文と bash の本文は、いつも走る節（`start`・境の節）以外の節の欄（`$x.output.<欄>`）を読まない。
  3. script の節の `with:` が、`when:` を持つ節か `when:` を持つ節の中の節を読むなら `if_skipped` を持つ。
  4. `when:` を持つ節に `depends_on` する節は `trigger_rule: none_failed_min_one_success` を持つ（線とブロックの両方。`blk-refix` の `route2`・`refix-reads`・`collect` も）。
- Produces（`test_line.py` に足す配線の検査。TA16・審査 I4）:
  - `test_script_inputs_match_with`: 線とブロックの全部の script の節で、`with:` の鍵を `INPUTS_<鍵の大文字>` にした集合 == そのスクリプトの定数 `INPUTS`（`plain` を既定に持つ `INPUTS_MODE` のように、既定の在る入力は `with:` に無くてよい、を定数の側の `OPTIONAL_INPUTS` で明示）。
  - `test_line_order_matches_linekit`: YAML の節の id・種類・include 先・`at`・`with:` の鍵の並び == `linekit.LINE_ORDER`。
  - `test_judging_stubs_follow_block`: 筋書きの判定の stub の鍵は、試験の時に `blk-judge.yaml` から組んだ stub できる節の集合を含む（線 B の判定 v2 が節の名前を替えた時は、この試験が赤になって知らせる。1 本目の JUDGE_ONLY の決め打ちは持たない。TA18 の 4）。
- Produces（`test_yaml_rules.py` の定数）: 書く道具を持ってよい節 `{(blk-fix, fix), (blk-refix, refix), (blk-refix, refix2)}`、Bash を持つ読むだけの役 `{(blk-premises, premises), (blk-pr, pr-check)}`（作業ツリーの写しで確かめる受け付けを持つことも見る）、役の一覧に `plan`・`plan-review`・`refix`・`review2`・`refix2`・`premises`・`pr-check` を足し、`RoleSessionCase` を TA13 の形に替える。全部の役の節の `output_format` が印を持ち、印の名が全部のブロックをまたいで一意であること（包みの会話の id の置き場が節の名で分かれるため）。印の `continue=` を持つ役は T23 まで無い（T23 が「`continue=` を持つ役だけは `context: fresh` を持つ」の決まりを足す）。
- Produces（線の筋書き 10 本。どれも `exec-code: true`。関所は模擬実行で自動で通るので、関所の後の答えは境の節の stub で差す）: `no-fix`・`standard`・`policy-continue`・`policy-stop`（`h-fix` の stub が `stop: true`）・`policy-reject`・`mid-when-needed-green`・`mid-stop`・`stop-flag`（`h-review` の stub が `stop: true`）・`start-refused`・`pr-fallback`（`start` の stub が `pr_go: true`）。T23 が `rejudge`・`rejudge-no-session` を足す。
  - **本物で回す節を残す**（1 本目の `finish` と同じ役目。TA16）: `standard` と `start-refused` は `start` を stub せず本物で回す（`with:` → `INPUTS_*` が模擬実行で届くことを見る）。`standard` の `start` は模擬実行の対象（`mktarget.sh` の種。`test_cmd` を渡す）に本物の盤面を作り、後ろの節は全部 stub。`start-refused` は `thickness: 軽量` を渡し、`expect: failed`・`reached` の最後が `start`（AI を起こす前に止まる）。ほかの 8 本は全部の節を stub。

- [ ] **Step 1: 共有の試験を先に新しい形へ書き直す（赤）** — `test_yaml_rules.py`・`yaml_bad`・`test_line.py` を新しい線の形・検査で書く。Run: `nice -n 19 sh works/tests/run.sh -k test_yaml_rules -k test_line` / Expected: FAIL（YAML がまだ 1 本目）
- [ ] **Step 2: ブロックの YAML を替える** — 役の `output_format` は各モジュールの定数（`recount.FIX_OUTPUT_FORMAT` など）の値を貼る。`blk-tests` は既定 `plain` を変えない。Run: `nice -n 19 sh works/tests/run.sh -k test_yaml_rules -k test_blk` / Expected: ブロックの分が緑。**審査の区切り 1**
- [ ] **Step 3: 線の YAML と筋書きを替える** — Run: `nice -n 19 sh works/tests/run.sh` と `sh works/dev/check.sh` / Expected: 両方緑（`check.sh` の模擬実行で `start-refused` のほかの 9 本が `reached` の最後に `report`。線 C の `mutgate` の筋書きがこの枝に在れば、それも緑）。**審査の区切り 2**（Step 2 の終わりが区切り 1）
- [ ] **Step 4: 開発の殻・スキル・README** — `real-run.sh` を包みに向ける（本物の claude の場所の見分け方は今の `real-run.sh` と同じ）。SKILL に: 起動の関所の越え方（`approve <id> --detach`）、並行 PR の申し送りは報告の下書きを人が投稿すること、判定への異議は写し直しまで次の run の依頼に回ること（報告の `next-request.json`）、止め札（`dev/stop.sh`。出し直しの輪の中では効かず次の境の節で止まる）、関所で待っている run は `cancel` でなく `respond … stop`、包みの有効化（`assistants.claude.claudeBinaryPath`）と `adapter: optional`、他人のリポジトリの `.review-checks.json` は人が先に読む（0.21.0 の注意）、`thickness` は標準だけ（持ち主の決定）、P14・P15 が未確認の間の取り消しの扱い、取り消し・`abandon`・役の出し直しの上限で落ちた run の報告は `dev/report.sh`（結末 `interrupted`）。README に入力の表（短い値だけ）と報告の冒頭の読み方。Run: `nice -n 19 sh works/tests/run.sh` / Expected: `OK`。**審査の区切り 3**
- [ ] **Step 5: 緑を確かめる** — Run: `nice -n 19 sh works/tests/run.sh` と `sh works/dev/check.sh` / Expected: 両方緑。`git status` に `__pycache__`・一時ファイルが無い。
- [ ] **Step 6: Commit** — `git commit -m "feat(works): darkfactory を 1 回の run を強くした形に切り替える（ブロックと線の YAML・筋書き・共有の試験・スキル）"`

---

### Task 18: AI の試し P13・P14・P15・P18 と、費用 0 の P19（**AI の分は費用の了承が要る**。T17 の後）

- **持ち主に聞いてから撃つ**。見込みは合わせて 1 ドル未満（名目。〔輪〕9.2）。了承が無ければこの Task は飛ばし、Global Constraints の予備の道のまま終える（SKILL と報告の冒頭は「未確認」のまま）。
- P19（AI 費用 0。bash の節だけの run の出来事を読む）は了承なしで先に撃ってよい。
- 変えてよいのは線 A の持ち物だけ（`reads.py` の `_read_paths`・`node_path`、`report.py` の `COST_FIELD_VERIFIED` と `cost_rows` の欄の読み方、`tests/events/`・`tests/adapter/argv/`、包み、`docs/specs/2026-09-27-…`）。SKILL・README（共有）に書き足す物が出たら、この線の外の小さな後続の 1 commit に回す。

**Files:**
- Modify: `works/.shared/core/reads.py`（P13 の結果で `_read_paths`・`node_path` を直す）
- Modify: `works/.shared/core/report.py`（P19 の結果で `COST_FIELD_VERIFIED` と費用の欄の読み方を直す）
- Modify: `works/tests/events/*.json`（`tool_called` の実物で取り直す。`_note` の「推測」を消す）
- Modify: `works/docs/specs/2026-09-27-darkfactory-single-run-design.md`（9.3 の結果の行）

**Interfaces:** 変えない（中身だけ）。

- [ ] **Step 1: 撃つ**（使い捨ての対象で、包みを通した `dev/real-run.sh`。1 つの run で 3 つを見る）
  - P13: 役の節の `tool_called` の Read に `file_path` が載るか、節が終わってから揃うまでの遅れ（`<役>-reads` の時点で揃っているか）。
  - P14: 修正役が守る場所（盤面・共通の `.git`）へ Edit・Write・Bash で書こうとして拒まれるか（指示書に 1 行の試しを足した一時の YAML で）。
  - P15（と P11 の AI の節の分）: 役の節が Bash で起こした `sleep` の孫が、`archon workflow cancel` の後に残らないか。
  - P18: 並行 PR の任せ先の役（`pr_go` を stub で真にした一時の YAML）が sandbox の下で `gh pr list`・`gh pr view` を読めるか（このリポジトリの公開の PR を読むだけ）。`no-post` の柵は、PATH の先頭に受けた argv を書くだけの偽の `gh` を置いた別の起動で、`gh pr comment` を打たせて偽の `gh` に届かないか（柵で拒まれるか）を見る。外へは書かない。
  - P19（AI 費用 0）: `archon workflow get <id> --verbose --events --json` の `node_completed` の出来事に節の費用（`cost_usd` か同じ意味の欄）が載るか。
  - P20（本物の修正役の異議で再審が判定役の会話を継ぐか・費用の引き算が DB の値と合うか）は、再審が入る Task 23（写し直しの後）の後に、同じ費用の了承で撃つ。
- [ ] **Step 2: 結果で直す** — 可なら強い側へ（`sources.events` を信じる・柵を「効く」と書く・`cancel` を普段の道に並べる・`COST_FIELD_VERIFIED` を真に）。不可なら予備の道のまま、仕様 11 節に「不可・根拠のログ」を書く。
- [ ] **Step 3: 緑を確かめる** — Run: `nice -n 19 sh works/tests/run.sh` と `sh works/dev/check.sh` / Expected: 両方緑
- [ ] **Step 4: Commit** — `git commit -m "test(works): AI の試し P13・P14・P15・P18・P19 の結果で、読んだ証拠・包み・費用の扱いを確かめる"`

---

### Task 19: 実走（**費用の了承が要る**。T18 の後）

- **持ち主に聞いてから撃つ**。見込みは opus で 2 回・合わせて 3 ドル以下（名目。仕様 9.4）。了承が無ければ撃たない。
- 変えてよいのは線 A の持ち物だけ。直しが要る物が見つかったら、この Task の中で直さずに持ち主の会話の側へ一覧で渡す（直しは別の小さな計画）。

**Files:**
- Modify: `works/docs/specs/2026-09-27-darkfactory-single-run-design.md`（9.4 の結果: run の id・費用・結末・見つけた物）

- [ ] **Step 1: 撃つ** — `dev/real-run.sh`（包みを通す）で使い捨ての対象に 2 本:
  1. 修正が今ある能力を狭めるバグを仕込み、修正前の関所が開く筋（`continue` で通す）。
  2. 標準で 2 往復目まで行く筋。途中の境の節の前で 1 度止め札を置き、`stopped_by_request` の報告が出ることを見る（止め札の分だけ別の run でもよい）。
- [ ] **Step 2: 見る** — どちらも報告の冒頭の 5 つ、読んだ証拠が 2 つの出どころで出ること、`launches.jsonl` に素通しが無いこと・全部の役の起動に `node` が在ること、`process.checks["p4.ci"].by`・`process.checks["p0.parallel_pr"].by`、前提の制約の `kind=実測` に出力が在ること、周の記録の検証器の終了コード、費用の内訳（異議が出た run なら継いだ起動の引き算）。
- [ ] **Step 3: Commit** — `git commit -m "docs(works): 線 A の実走 2 本の結果を仕様に書く"`

---

### Task 20: 「軽量」（**閉じた**。持ち主の答え 2026-09-27: 案 1＝下げない）

- 作業は無い。graph で optional でない節は省かない。受けるのは標準だけで、`軽量`・`重厚` は理由つきで拒む（裁定 TA7）。
- 1 版で案 2 のために書いていた配管（盤面の層の `downgrade` の欄・`state.works.downgrades`・`edge` の `skipped_by_thickness`・事前審査の輪の `when:`・報告の「省いた節と決めた人」）は作らない。
- 拒否の文の直し（「持ち主の答え待ち」→「持ち主の決定」）と `thickness_decider` を消すことは Task 7 に入れた（`test_light_refused_by_owner_decision`）。筋書き `start-refused`（Task 17）は `thickness: 軽量` のまま、拒否の道の見本として残す。

---

### Task 21: 並行 PR の検査 `p0.parallel_pr`（持ち主の答え 2026-09-27: 案 (a)。T9・T10b の後。T22 の前）

仕様 3.8・裁定 TA8。`p0.parallel_pr` を `engine_run`・`fallback: role` にする。交差 0 は engine で済み、任せ先に落ちた時だけ読むだけの opus の役が 6 段をする。申し送りは投稿せず、下書きを報告に載せる。YAML は T17（役が Bash を持ち、今の共有の試験の決まりで通らないため）。

**Files:**
- Create: `works/.shared/core/prcheck.py`
- Modify: `works/.shared/core/entry.py`（`start` が `prcheck.run_helper` を呼び、返りに `pr_go` を足す。`head_line` に下げている所の数）
- Modify: `works/darkfactory/nodes.json`（`p0.parallel_pr` を `engine_run`・`fallback: role`・where「start（engine）→ blk-pr（任せ先）」）
- Create: `works/darkfactory/downgrades.json`（`[{"node": "p0.parallel_pr", "what": "担当の PR へ申し送りを投稿しない（下書きを報告の冒頭 1 に載せる）", "versus": "review-graph は任せ先の役が gh で投稿する"}]`）
- Create: `works/blk-pr/commands/pr-check.md`（a1202d0 の `prompts/review-loop/p0.parallel_pr.md` の 6 段を写し、6 段目を「投稿せず、申し送りの下書きを `conflicts[].note` に書き、`handed_over: false`」に替える。`gh` は必ず `-R`。書き込みの `gh` を打つなと書く）
- Create: `works/blk-pr/scripts/snap.py`・`accept.py`・`reads.py`・`collect.py`
- Create: `works/tests/replies/pr_ok.json`・`pr_handed_over.json`・`pr_no_conflicts.json`（0.21.0 の `p0.parallel_pr` の schema の形）
- Modify: `works/tests/test_entry.py`（Task 3 の `test_later_rows_name_their_task` から `p0.parallel_pr` を外し、行の形の試験に替える）
- Test: `works/tests/test_blk_pr.py`

**Interfaces:**
- Consumes: `b.run_engine("p0.parallel_pr", runner=)`（盤面の層。写しの `parallel-pr.py` を走らせ、交差・GitHub でない remote・`gh` が無い時は `fallback`）・`entry.take`・`entry.snapshot`・`reads.main_for`・`node_marker.mark`・`accept.role_schema("p0.parallel_pr")`。
- Produces（`prcheck.py`）:
  - `NODE = "p0.parallel_pr"`、`OUTPUT_FORMAT = mark(role_schema("p0.parallel_pr"), "pr-check", flags=("no-post",))`
  - `run_helper(b, *, runner=None) -> dict` — `ready` に `p0.parallel_pr` が在れば `run_engine`。`relaunch` は 1 度だけ呼び直す（`entry.run_ci` と同じ扱い。2 度目も同じなら `CiRefused`）。返り `{"by": "engine"|"role", "role_needed": bool, "why": str}`。ready に無ければ `{"by": "", "role_needed": False}`。線 B の境の節も同じ関数を呼ぶ。
  - `collect(board: Path) -> dict` — `{ok, pr_file, conflicts, drafts, material_status, reads_file}`（`drafts` は `note` を持つ交差の件数）。
- Produces（`blk-pr/scripts/accept.py`。works だけの検査はブロックのスクリプトに置く。TA25）:
  - `check_no_post(reply: dict) -> list[str]` — `conflicts[].handed_over` が真の行の `pr` を並べた誤り（空なら通す）。
  - `main()` — 順: `check_no_post`（誤りが在れば `{"ok": false, "reason": "このラインは申し送りを投稿しない（持ち主の決定 2026-09-27）。下書きを note に書き handed_over を false にせよ: <pr の一覧>"}` を 1 行で出して 0）→ `entry.main_take(prcheck.NODE, snapshot_name="pr-snapshot.json")`。
- Produces（`entry.start` の返りに足す欄）: `pr_go`（`run_helper` の `role_needed`）。`start` は `run_ci` の後・`settle` の前に `run_helper` を呼ぶ。
- Produces（blk-pr の入口と中の節。YAML は T17）: 入口 `base_rev`。`pr-snap`（script）→ `pr-loop`（`max_iterations: 3`）: 役 `pr-check`（`allowed_tools: [Read, Grep, Glob, Bash]`・sandbox・`settingSources: []`・`output_format` = `prcheck.OUTPUT_FORMAT`）＋ `pr-accept` → `pr-reads` → `collect`。各 script は読む `INPUTS_*` を定数 `INPUTS` に持つ（TA16）。

- [ ] **Step 1: 失敗する試験を書く**

```python
def test_parallel_pr_row_engine_run_fallback_role(self):  # nodes.json の p0.parallel_pr が engine_run・fallback role・where に blk-pr
def test_parallel_pr_helper_runs_first(self):     # 偽の runner が交差 0 を返す → start の後 process.checks["p0.parallel_pr"].by == "engine"、pr_go False、役を起こさない
def test_fallback_sets_pr_go(self):               # 偽の runner が交差 1 件（か gh が無い）→ pr_go True、盤面の p0.parallel_pr の instance が任せ先で待つ
def test_fallback_role_reads_only(self):          # pr-snap の後に作業ツリーを変えて accept → ok False、文に「作業ツリーを変えた」
def test_handed_over_true_rejected(self):         # pr_handed_over（handed_over true が 1 件）→ ok False、文に pr と「投稿しない」、盤面が前のまま
def test_handover_draft_accepted(self):           # pr_ok（handed_over false・note つき）→ ok、ready の先に P1 の na が付き p2.diagnose へ進む
def test_output_format_marked_no_post(self):      # strip(OUTPUT_FORMAT) == role_schema("p0.parallel_pr")、parse の flags に no-post
def test_prompt_step6_no_post(self):              # pr-check.md の 6 段目に「投稿せず」と handed_over false、gh の書き込みの語（comment・review・api -X）を打つなの 1 行
def test_downgrades_declared(self):               # downgrades.json の 1 行が p0.parallel_pr、start の head_line に「下げている所: 1 個」
def test_run_helper_relaunch_once(self):          # 1 度目 relaunch・2 度目通る → 通る。2 度とも relaunch → CiRefused
```

- [ ] **Step 2: 赤を確かめる** — Run: `nice -n 19 sh works/tests/run.sh -k test_blk_pr -k test_entry` / Expected: FAIL
- [ ] **Step 3: 書く** — 1〜5 段は写しの `parallel-pr.py` を盤面の層の `run_engine` が走らせる（works は書き直さない）。役は 6 段の全部を指示書どおりにするが、投稿の段だけ下書きに替える。`gh` の通信が sandbox で拒まれた時は、役が `material.status` を `not_run`（理由つき）で返してよい（写しの schema が許す）。
- [ ] **Step 4: 緑を確かめる** — Run: `nice -n 19 sh works/tests/run.sh` と `sh works/dev/check.sh` / Expected: 両方緑（YAML はまだ無いので模擬実行は変わらない）
- [ ] **Step 5: Commit** — `git commit -m "feat(works): 並行 PR の検査（engine の 1〜5 段と、読むだけの任せ先の役。申し送りは報告の下書き）"`

---

### Task 22: 前提の実測 `p0.premises`（持ち主の答え 2026-09-27。T21 の後）

仕様 3.6・裁定 TA14・TA9。判定の前に `blk-premises` を回し、判定役に前提のファイルを渡す。境の節 `h-judge` を足し、包みの確かめを `h-plan` から `h-judge` へ移す。YAML は T17。

**Files:**
- Create: `works/.shared/core/premises.py`
- Create: `works/blk-premises/commands/premises.md`（a1202d0 の `prompts/review-loop/p0.premises.md` を写し、依頼の `measured` の測り直しの 1 段落を足す。仕様 3.6）
- Create: `works/blk-premises/scripts/snap.py`・`accept.py`・`reads.py`・`collect.py`
- Modify: `works/.shared/core/entry.py`（`start` の返りに `premises_go`）
- Modify: `works/.shared/core/halt.py`（`AT` に `"judge"`、`judge_edge`。T10b の包みの確かめを `judge_edge` へ動かす）
- Modify: `works/darkfactory/scripts/edge.py`（返りに `premises_file`）
- Modify: `works/darkfactory/nodes.json`（`p0.premises` を role・where `blk-premises`）
- Create: `works/tests/replies/premises_ok.json`・`premises_measured_no_output.json`・`premises_claim_missing.json`・`premises_claim_hypothesis.json`（0.21.0 の `p0.premises` の schema の形。種の依頼に `measured` を 1 行持たせた物に合わせる）
- Modify: `works/tests/test_entry.py`（`test_later_rows_name_their_task` から `p0.premises` を外す・`test_roles_are_track_a_nodes` に `p0.premises`）・`works/tests/test_halt.py`（T10b の包みの 2 つの試験の `at` を `judge` に）
- Test: `works/tests/test_blk_premises.py`

**Interfaces:**
- Consumes: `entry.take`・`entry.snapshot`・`reads.main_for`・`reads.adapter_seen`・`node_marker.mark`・`accept.role_schema("p0.premises")`・盤面の `record.process.request_findings`（依頼の行）。
- Produces（`premises.py`）:
  - `NODE = "p0.premises"`、`OUTPUT_FORMAT = mark(role_schema("p0.premises"), "premises")`
  - `claims(items: list[dict]) -> list[dict]` — 依頼の行のうち `measured` を持つ物の `{where, measured}`。
  - `collect(board: Path) -> dict` — `{ok, premises_file, constraints, measured, hypotheses, claims, claims_hypothesis, reads_file}`。
- Produces（`blk-premises/scripts/accept.py`。works だけの検査はブロックのスクリプトに置く。TA25）:
  - `check_claims(reply: dict, items: list[dict]) -> list[str]` — `request_claims_covered`: 各 `premises.claims(items)` の `where` を `text` に含む制約が無い物を並べる。
  - `main()` — 順: `check_claims`（誤りが在れば `{"ok": false, "reason": "依頼の実測を測り直した制約が無い: <where の一覧>。text に where をそのまま入れよ"}` を 1 行で出して 0）→ `entry.main_take(premises.NODE, snapshot_name="premises-snapshot.json")`（作業ツリーの確かめと、写しの `measured_needs_output` と schema が盤面の上で当たる）。
- Produces（`halt.py`）: `judge_edge(b, board_dir, repo, *, run_id, adapter_mode) -> dict` — 順: 1. 包みの確かめ（T10b の手順 1 をここへ。`by="works:adapter"`）。2. 表で `p0.premises` が role なのに盤面で済んでいなければ `b.stop("前提の実測が盤面に無い: …", by="works:premises")`。3. `go: True`・`premises_file = state.outputs["p0.premises"]["file"]`。`plan_edge` から包みの確かめを外す。
- Produces（`entry.start` の返りに足す欄）: `premises_go`（`ready` に `p0.premises`）。
- Produces（blk-premises の入口と中の節。YAML は T17）: 入口 `request_file`・`base_rev`。`premises-snap` → `premises-loop`（`max_iterations: 3`）: 役 `premises`（`allowed_tools: [Read, Grep, Glob, Bash]`・sandbox・`output_format` = `premises.OUTPUT_FORMAT`）＋ `premises-accept` → `premises-reads` → `collect`。各 script は `INPUTS` の定数を持つ（TA16）。
- 判定役への届け方: `h-judge` の返りの `premises_file` を、線の YAML が `blk-judge` の入口 `premises_file`（T2）へ渡す（T17）。

- [ ] **Step 1: 失敗する試験を書く**

```python
def test_premises_ok_accepted(self):              # start の後の盤面に premises_ok → ok、record.process.constraints に行、ready に p2.diagnose（か P1 の na の後に）
def test_measured_needs_output_rejected(self):    # kind 実測で measured_output が無い → ok False（写しの measured_needs_output の文）
def test_request_claim_missing_rejected(self):    # 依頼に measured の行が在るのに、その where を含む制約が無い → ok False、文に where
def test_request_claim_hypothesis_passes(self):   # 測り直せず kind 仮説にした行 → ok、collect の claims_hypothesis == 1
def test_premises_readonly_tree_changed(self):    # premises-snap の後に作業ツリーを変える → ok False
def test_output_format_marked(self):              # strip(OUTPUT_FORMAT) == role_schema("p0.premises")、印の名 premises
def test_prompt_measures_request_claims(self):    # premises.md に「measured」「where をそのまま」「仮説」の段落、a1202d0 の本文を全部含む
def test_start_premises_go(self):                 # start の返りの premises_go True、盤面の ready に p0.premises
def test_judge_edge_returns_premises_file(self):  # premises を受けた盤面で edge(at="judge") → go True、premises_file == state.outputs["p0.premises"]["file"]
def test_judge_edge_stops_without_premises(self): # premises を受けていない盤面で edge(at="judge") → stop True、state.stop.by "works:premises"
def test_adapter_check_moved_to_judge(self):      # launches.jsonl にこの run の行が無い・adapter "" → at judge で stop（by works:adapter）、at plan では包みを見ない
def test_premises_row_is_role(self):              # nodes.json の p0.premises が role・where blk-premises、p0.purpose は absent で reason に「線 B」
```

- [ ] **Step 2: 赤を確かめる** — Run: `nice -n 19 sh works/tests/run.sh -k test_blk_premises -k test_halt -k test_entry` / Expected: FAIL
- [ ] **Step 3: 書く** — `measured_needs_output` は写しの物が盤面の `done` の中で当たる（works は書き直さない）。works が足すのは `check_claims` だけ。T10b の包みの確かめは関数ごと動かし、試験の主張は減らさない。
- [ ] **Step 4: 緑を確かめる** — Run: `nice -n 19 sh works/tests/run.sh` と `sh works/dev/check.sh` / Expected: 両方緑
- [ ] **Step 5: Commit** — `git commit -m "feat(works): 判定の前に前提を実測する役（依頼の実測の測り直しを含む）と境の節 h-judge"`

---

### Task 23: 判定への異議の同じ周の再審（本線 3-6 の形。**写し直しの後**。T5・T12・T22 の後）

仕様 3.7・裁定 TA21〜TA23。本線の 3-5・3-6 を写した盤面で、修正役の `rejudge_requested` から始まる同じ周の往復（再審 3 回・修正役の再異議 2 回・第三の目）を回す。再審は判定役の会話の続き（包みの `continue=judge`）、再異議と第三の目は新しい会話。会話の id が無ければ役を起こす前に止めて聞く。この Task は切り替え（T17）の後なので、YAML・線・筋書き・共有の試験の決まりまでを持ち、共有のファイルは最後の 1 commit でだけ触る。

**Files:**
- Create: `works/.shared/core/rejudge.py`
- Create: `works/blk-rejudge/blk-rejudge.yaml`・`works/blk-rejudge/fixtures/settled.stubs.yaml`・`three-passes.stubs.yaml`
- Create: `works/blk-rejudge/commands/rejudge.md`・`rejudge2.md`・`rejudge3.md`・`rejudge-reply.md`・`rejudge-reply2.md`・`rejudge-third.md`（写し直しで入る本線の `p2.rejudge*.md`・`p3.rejudge_reply*.md`・`p2.rejudge_third.md` を写し、`{{…}}` を `rejudge-brief.json` のパスを読む形に替える）
- Create: `works/blk-rejudge/scripts/route.py`・`snap.py`・`accept.py`・`reads.py`・`collect.py`
- Modify: `works/.shared/core/halt.py`（`AT` に `"rejudge"`、`rejudge_edge`）・`works/darkfactory/darkfactory.yaml`（`h-rejudge`・`rejudging` を `fixing` と `h-mid` の間に）・`works/darkfactory/fixtures/`（`rejudge`・`rejudge-no-session` の 2 本）・`works/darkfactory/nodes.json`（再審の 6 節を role・where `blk-rejudge`）
- Modify: `works/tests/linekit.py`（`LINE_ORDER` に 2 節、`run_line` に `sessions: bool = True`＝判定の役の返答を差す時に `adapter.session_path(repo, "judge")` へ偽の id を書く）・`works/tests/test_line_a.py`・`works/tests/test_entry.py`
- Create: `works/tests/replies/fix2_rejudge_requested.json`・`rejudge_partial.json`（一部採る・争点でない単位を 1 つ変える）・`rejudge_settled.json`・`rejudge_empty_facts.json`・`rejudge_reply_again.json`・`rejudge_reply_withdraw.json`・`rejudge_third_ok.json`（写し直した graph の schema の形）
- Modify（共有。最後の 1 commit）: `works/tests/test_yaml_rules.py`（役の一覧に 6 つ、「`continue=` を持つ役だけ `context: fresh` を持つ」の決まり、`yaml_bad/` に 1 本）・`works/tests/test_line.py`（線の形）・`works/skills/works/SKILL.md`（包みが判定役の会話を継ぐこと・Archon の run の費用の合計は継いだ節で判定役の分を重ねること（報告の費用の行が正）・会話の id が無くて止まった run の扱い）
- Test: `works/tests/test_blk_rejudge.py`

**Interfaces:**
- Consumes: `entry.take`・`entry.snapshot`・`entry.main_take`・`reads.main_for`・`adapter.session_path`（T5）・`node_marker.mark`・`accept.role_schema(節)`（写し直しで $ref を開ける形になっている前提。「写し直しへの依存」）・写しの RL の `REJUDGE_PASSES`（`rules_module()` から引く。works に数も名前も持たない）。
- Produces（`rejudge.py`）:
  - `passes() -> list[dict]` — 写しの `REJUDGE_PASSES` と第三の目から、ラインの順に `[{node, role, cont}]`（例 `{node: "p2.rejudge", role: "rejudge", cont: "judge"}`・`{node: "p3.rejudge_reply", role: "rejudge-reply", cont: None}`…`{node: "p2.rejudge_third", role: "rejudge-third", cont: None}`）。節の名前は写しから引き、役の名は works の対応表（`ROLE_OF = {節: 役}`）で持つ。表と写しの節がずれたら `BoardGap`。
  - `OUTPUT_FORMATS: dict[str, dict]` — 役ごとに `mark(role_schema(節), 役, cont=…)`（再審の 3 つは `cont="judge"`）。
  - `route(board: Path) -> dict` — `{"next": 役 | "", "why": str}`（盤面の `ready` のうち再審の節の最初の 1 つ）。
  - `session_ready(repo: Path) -> dict` — `{"ok": bool, "path": str}`（`adapter.session_path(repo, "judge")` が在って空でない）。線 B の境の節も呼ぶ。
  - `brief(b) -> Path` — `b.work("rejudge-brief.json")` に、今の回の異議・今の周の単位と台帳（key・label・disposition と key・kind・status）・判定の見立て（framing・one_shot）・これまでの往復（`process.rejudge`）・直前の再審の答えを書く。同じ時に `b.work("rejudge-units-before.json")` に今の単位を写す。
  - `diff_units(before: list[dict], after: list[dict], objection: str) -> dict` — `{"disputed": [key], "changed": [{key, field, before, after, disputed}], "undisputed_changed": [key]}`。`disputed` は `objection` に key がそのまま現れる単位。1 つも無ければ変化の全部を争点でない側に置く。
  - `collect(board: Path) -> dict` — `{ok, passes, verdicts, undisputed_changed, diff_file, reads_file}`。回した後に再審の節のどれかがまだ ready なら `ok: False`・`reason`（engine の順で起きない形）。
- Produces（`blk-rejudge/scripts/accept.py`）: `main(role)` — `entry.main_take(節, snapshot_name="rejudge-snapshot.json")`（写しの `rejudge_output`。再異議の 2 節は schema だけ）。通った再審の回だけ `diff_units` を `b.work("rejudge-diff.json")` に 1 行足す。works だけの検査は足さない（TA25）。
- Produces（`halt.py`）: `rejudge_edge(b, repo) -> dict` — `route` の `next` が `rejudge`（1 回目の再審）で `session_ready` が偽なら `b.stop("判定役の会話が見つからない: <path>。再審せずに止めた", by="works:rejudge-session")`・`{stop: True, go: False}`。2・3 回目は 1 回目と同じ id を継ぐので、ブロックの中では確かめ直さない。`next` が在れば `go: True`。
- Produces（blk-rejudge の入口と中の節）: 入口 `base_rev`・`policy_paste`・`policy_path`。段ごとに `rj-route<k>`（script）→ `<役>-loop`（`when: $rj-route<k>.output.next == '<役>'`・`max_iterations: 3`。役 1 つ＋受け付け 1 つ）を 6 段（`rejudge`・`rejudge-reply`・`rejudge2`・`rejudge-reply2`・`rejudge3`・`rejudge-third`）。役の前に `rejudge-snap`（作業ツリーの写しと `brief`）。合流の節は `trigger_rule: none_failed_min_one_success`。最後に `rejudge-reads` → `collect`。再審の 3 役は判定役と同じ `allowed_tools`・**`context: fresh`**・印 `continue=judge`。再異議の 2 役は `[Read, Grep, Glob]`（作業ツリーを変えない）。第三の目は判定役と同じ道具・新しい会話。指示書は `$rejudge-snap.output.brief_file`・`$INPUTS.policy_paste`（判定役と第三の目）・`$INPUTS.policy_path`（再異議）・`$LOOP_PREV.<役>-accept.output.reason` を読む。
- Produces（線）: `h-rejudge  script edge (at rejudge)  depends_on [start, h-fix, fixing]`、`rejudging  include blk-rejudge  when: "$h-rejudge.output.go == true"  with: base_rev・policy_paste・policy_path: $start.output の欄`、`h-mid` の `depends_on` を `[start, h-rejudge, rejudging]` に。
- 出し直し（拒否の後）の回も包みが判定役の会話を継ぐので、同じ会話に前の返答と拒否の理由が残る（〔継試〕: fork なしなら判定役の会話 id は変わらない）。

- [ ] **Step 0: 写し直しを確かめる** — 写しに `REJUDGE_PASSES`・`p3.rejudge_reply`・`p2.rejudge2`・`p2.rejudge3` と `rejudge*_open`・`rejudge_reply*_due` が在り、盤面の層がそれを通して緑（「写し直しへの依存」の 1〜5 が済んでいる）。無ければ止めて報告する。
- [ ] **Step 1: 失敗する試験を書く**

```python
def test_objection_makes_rejudge_ready(self):     # fix2_rejudge_requested を受けた盤面 → route の next "rejudge"
def test_no_objection_no_rejudge(self):           # fix2_ok → route の next ""、h-rejudge の go False
def test_precheck_stops_before_role(self):        # 異議の在る盤面・session_path(repo, "judge") が無い → edge(at="rejudge") が stop True、state.stop.by "works:rejudge-session"、p2.rejudge は待ちのまま
def test_precheck_passes_with_session(self):      # 同じ盤面に judge の id を置く → go True
def test_settled_first_pass(self):                # rejudge_settled（採る）→ 再異議の節は条件で na、collect の passes 1
def test_partial_then_reply_then_rejudge2(self):  # rejudge_partial → route の next "rejudge-reply" → rejudge_reply_again → next "rejudge2"
def test_reply_withdraw_ends(self):               # rejudge_partial → rejudge_reply_withdraw（rejudge_requested なし）→ 2 回目は条件で na、next ""
def test_three_partials_reach_third(self):        # 一部採る × 3 と再異議 × 2 → next "rejudge-third"、第三の目の前に会話を確かめない
def test_empty_facts_rejected(self):              # rejudge_empty_facts → ok False（写しの rejudge_output の文）、盤面が前のまま
def test_undisputed_change_recorded(self):        # rejudge_partial が異議に名の無い単位の label を変える → rejudge-diff.json の undisputed_changed にその key
def test_no_key_in_objection_all_undisputed(self):# 異議の文に key が 1 つも無い → 変化の全部が undisputed_changed
def test_collect_fails_if_still_ready(self):      # 回した後も再審の節が ready の盤面（差し込み）→ collect の ok False
def test_passes_from_copied_rules(self):          # rejudge.py に 3 の数も節の名の並びも書かない（写しの REJUDGE_PASSES から引く）、ROLE_OF と写しがずれたら BoardGap
def test_output_formats_marked(self):             # 再審の 3 つは strip した値が写しの schema・cont "judge"、再異議と第三の目は cont None
def test_rejudge_path_line(self):                 # run_line: 修正の返答に rejudge_requested → trail が h-rejudge → rejudging → h-mid、record.process.rejudge に行
def test_rejudge_without_session_stops(self):     # run_line(sessions=False) → rejudging が trail に無く、outcome stopped_by_line、next-request.json に異議
def test_context_fresh_only_for_continue(self):   # test_yaml_rules の新しい決まり: continue= を持つ役は context fresh を持つ、持たない役は持たない（yaml_bad の 1 本で落ちる）
```

- [ ] **Step 2: 赤を確かめる** — Run: `nice -n 19 sh works/tests/run.sh -k test_blk_rejudge -k test_halt -k test_line_a` / Expected: FAIL
- [ ] **Step 3: 書く** — どの節を回すかは盤面の `ready` だけで決める。単位の変化に柵を足さない（TA23）。会話の継ぎは包みの仕事で、このブロックは印を付けて先に id を確かめるだけ。共有のファイル（`test_yaml_rules.py`・`test_line.py`・SKILL）は最後の手順でまとめて触る。
- [ ] **Step 4: 緑を確かめる** — Run: `nice -n 19 sh works/tests/run.sh` と `sh works/dev/check.sh` / Expected: 両方緑（筋書き 12 本）
- [ ] **Step 5: Commit** — `git commit -m "feat(works): 判定への異議を同じ周に判定役の会話の続きで再審する（本線 3-6 の 3 往復・第三の目・会話が無い時は止めて聞く）"`

---

### Task 24: `accept.py` から本線の `gl.py` への対応表（回す側の指示 2026-09-27。いつでも。文書と試験だけ）

裁定 TA25。受け付けの口は本線の 3-8 まで `accept.py` のまま。本線の `gl.py`（`cond`・`accept`・`machine`・`exit`）へ載せ替える日のために、対応と足りない物を機械で読める表にする。

**Files:**
- Create: `works/.shared/core/gl_map.json`（`[{works, gl, status, note}]`。`status` は `ready`（gl に同じ口が在る）・`missing`（gl に無い）・`works-only`（graphloops に無い works だけの検査））
- Test: `works/tests/test_gl_map.py`

**Interfaces:**
- 表の行（芯）:
  - `accept.check_request` → 無い（`missing`: 依頼に依らない検査の口が gl に無い）
  - `accept.role_schema` → `gl exit <節>`（`missing` の部分: 役の schema から注記を外す口が gl に無い）
  - `accept.check_judge` → `gl accept p2.diagnose`（`missing`: 判定の受け付けは本線でまだ旧い形。3-6 の続き・3-8 待ち）
  - `accept.cut_delta` → 無い（`missing`: 差分を切る段が gl に無い）
  - `accept.check_fix` → `gl accept p3.fix`・`accept.check_delta` → `gl accept p3.delta_review`（`ready` 見込み。3-6 で新しい形に移った）
  - `entry.take`（盤面の `done`）→ `gl accept <節>` と effects（盤面の層が engine の `commands.post_check` を通す形になった後。「写し直しへの依存」の 3）
  - works だけの検査（`works-only`）: `accept.snapshot_tree` の比べ（読むだけの役の作業ツリー）・`blk-premises/scripts/accept.py` の `check_claims`・`blk-pr/scripts/accept.py` の `check_no_post`
  - 線 B の行（線 B の最後の共有の commit で足す）: `judge2.check`・`close.final_gate_reply`・`rounds_validator`

- [ ] **Step 1: 失敗する試験を書く**

```python
def test_every_accept_function_mapped(self):      # accept.py の公開の関数の全部が表の works に 1 度ずつ
def test_missing_four_named(self):                # status missing の行に、依頼に依らない検査・注記を外す・判定の受け付け・差分を切る の 4 つが在る
def test_works_only_checks_listed(self):          # check_claims・check_no_post・snapshot_tree の行が works-only
def test_no_new_checks_in_accept(self):           # accept.py の公開の関数の集合が、この Task の時点の控え（表の works の accept.* の集合）と同じ（足したら赤）
```

- [ ] **Step 2: 赤を確かめる** — Run: `nice -n 19 sh works/tests/run.sh -k test_gl_map` / Expected: FAIL
- [ ] **Step 3: 書く** — 本線の `gl.py`（d1b863f の 208 行）と本線の知らせ（3-6 の続きと 3-8 で足りない物が入る）を読んで表を埋める。`note` に読んだ本線の sha を書く。
- [ ] **Step 4: 緑を確かめる** — Run: `nice -n 19 sh works/tests/run.sh` / Expected: `OK`
- [ ] **Step 5: Commit** — `git commit -m "docs(works): accept.py から本線の gl.py への対応表（足りない 4 つと works だけの検査）"`

---

### Task 25: ブロックの名前と `where` を本線に揃える（**本線の 3-7 が版に入った後**。小さな作業）

裁定 TA26。本線のブロックの置き場と名前（`graphloops/blocks/review-loop/<ブロック>/block.json`）が 3-7 で決まったら、works の仮の名と節の表の `where` を揃える。

**Files（3-7 の中身しだい）:**
- Modify: `works/darkfactory/nodes.json`（`where` に本線のブロック名。形は 3-7 の後に決める。案: `"<本線のブロック> / <works の置き場>"`）
- Rename（要る時だけ）: 本線と 1 対 1 に当たる新しいブロックで名が違う物（今の仮の名のうち `blk-premises`・`blk-pr`・`blk-refix` は本線の prereq・material・delta の一部なので、1 対 1 には当たらない見込み。当たらない物は名を残し `where` だけ揃える）
- Modify（共有。最後の 1 commit）: `works/tests/test_line.py`・`works/tests/test_yaml_rules.py`（名を替えた時だけ）
- Test: `works/tests/test_entry.py`（`test_where_matches_mainline_blocks`: 写した `graphloops/blocks/**` の `nodes` と表の `where` の本線の名が全部の節で合う）

- [ ] **Step 1〜5**: 失敗する試験 → 赤 → 書く → 緑（`nice -n 19 sh works/tests/run.sh` と `sh works/dev/check.sh`）→ Commit `git commit -m "refactor(works): ブロックの名前と節の表の where を本線のブロックの宣言に揃える"`

---

## 写し直しへの依存（本線 3-5・3-6。回す側の指示 2026-09-27。線 A の作業ではない）

写し直しは本線の 3-5（27a818a）と 3-6（d1b863f の続き）が版に入るまで見送り、入ったら写し直しの線が 1 回で写す（〔本〕5 の 1）。その時に要る物を、ここに依存として控える（線 A はこれを待つ Task 23 の Step 0 で確かめるだけ）。

1. graph_sha が変わる: 全部の節の表（`darkfactory/nodes.json`・`darkfactory-rounds/nodes.json`・盤面の層の試験の表）と、盤面の層の手本（`tests/boards/golden-a1202d0`）を撮り直す。実物の盤面の見本は開かなくなる（BoardMismatch。設計どおり）。
2. 新しい機械の節 `p2.fix_units`（0.21.1）と、3-6 の再審の 4 節（`p3.rejudge_reply`・`p2.rejudge2`・`p3.rejudge_reply2`・`p2.rejudge3`）を全部の節の表に足す（線 A は T23 まで absent、T23 で role）。
3. 盤面の層の受け付け（`board.py` の 701〜712 行の `DiskBoard.accept`）が写しの `POST_CHECKS` を直に呼んでいる。3-6 の新しい形は `{ok: false, …}` を返すので、そのままだと拒否を注記として通す。engine の `commands.post_check`（新旧を読み分けて effects も返す）を通す形に替える（盤面の層の持ち物）。
4. `accept.py` の `DeltaPass.state_key` が 3-5 で消える（`accept.py:440` が AttributeError）。3-6 で `POST_CHECKS` の第 1 引数が読み口になる（`accept.py:415`・`:442`）。盤面の層の持ち物。線 A の側は `refix.passes()`（`state_key` を読む 1 か所）を直す。
5. 線 C の `mutcore` の `_GateView` が `loop.gates_cut` を渡している。3-5 で規則が `p3.gates_cut` の出力を読むようになるので、それに替える（線 C の持ち物）。
6. 写す物が増える: `engine/hist.py`・`engine/effects.py`・`engine/filelock.py`（DiskBoard の保存が錠を使う）・`graphloops/blocks/**`（役の schema の $ref の先。`role_schema` が開けるように）・`scripts/gl.py`。`COPIED_FROM` に足す。DiskBoard の答え（`_answer_record`）を 0.21.1 の `answer --detail`（`answer_detail`）に揃える。
7. 猶予: 本線は子を止める猶予を呼ぶ側が選べる形（既定 5 秒）にする。works は 2 秒（`tree_run.KILL_GRACE`）を持つ（Archon の取り消しの猶予 5 秒より短くするため）。

## 持ち主に聞く（この計画の中）

- 新しく聞く事は無い。
- 決まった物（2026-09-27 の朝の答え。末尾の「改訂（持ち主の答え 2026-09-27）」）: 「軽量」は下げない（Task 20 は閉じた）、並行 PR は読むだけの役で申し送りを報告に（Task 21）、前提は線 A・目的は線 B（Task 22）、同じ周の再審は包みで判定役の会話を継ぐ（Task 5・23）。
- 前から保留の物（どれもこの計画の形を変えない）:
  - P13（`tool_called` の分）・P14・P15 の費用 → Task 18。P18・P20（AI 要）もここに足した。見込みは合わせて 1 ドル未満のまま。
  - 線 A の実走の費用（opus 2 回・3 ドル以下の目安）→ Task 19。
- 本線を待つ物（聞く物ではない）: 本線の 3-5・3-6 の版（写し直し → Task 23）、3-7 の版（Task 25）、3-8（`accept.py` を `gl.py` へ載せ替える日。Task 24 の表）。

## 改訂 2（審査 作業の控え（scratchpad）の `trackA-plan-review.md`「Approve with changes」への対応）

1 版からの直しを、審査の指摘ごとに並べる。回す側の裁定（I1〜I4 の直し方・I5・I6・Task 17 の審査の区切り）に従った。M12（試験は名前と 1 行の意図まで）はそのまま受けた。

- **I1**（blk-tests の既定が線 C の mutgate を壊す）: `blk-tests` の既定を `mode: plain`（1 本目と同じ。盤面なし・`cmd` 必須・`board/tests.log`・出口 `{ok, green, log}`）にし、線 A のラインが `mode: mid`・`final` を明示で渡す形にした（裁定 TA4・TA5、Global Constraints、Task 14、Task 17）。T14 に `test_plain_mode_is_mutgate_contract`・`test_plain_mode_empty_cmd_fails` を足し、T17 の Interfaces に「線 C の include の約束を変えない」を書いた。
- **I2**（線 B の申し送りと周の番号）: 裁定 TA17・TA18 を足した。1. `entry.open_board` が `board_hook.py` を読む（Task 3 `test_open_board_applies_board_hook`）。2. `entry.local_checks_material` と `entry.run_ci` を公開の口にした（Task 7）。3. 報告の部品 `head_*` を関数にした（Task 15 `test_head_parts_callable`）。4. Task 2 の試験を `test_judge_block_policy_entry_only` に替え、筋書きの判定の stub を `blk-judge.yaml` から組む形にした（Task 17 `test_judging_stubs_follow_block`）。周の番号は、作業ファイルを `b.work`、役の出力を `state.outputs[節]["file"]`、engine の走りのログを `run_engine` の返りから引く形に全部替え、周 2 の盤面の試験を足した（Task 9 `test_take_round_two`、Task 10a `test_plan_file_from_outputs`、Task 15 `test_round_two_paths`）。線 B の計画の `policy_file`＋`brief` の古さは線 B の側の話なので、ここでは直さない（台帳の側で B に知らせる）。
- **I3**（報告の前の検証器が素通り）: 裁定 TA15 を足した。`report.gate_record` が engine の `cmd_finalize` と同じく `settle` → `finalize` → `run_validator` → `report_accepts` を踏み、通らない・周の記録が組めていない盤面は結末 `record_invalid` にする。`fixed`・`no_fix_needed` はその関所を通った時だけ出す（Task 15 `test_validator_rejects_never_fixed`・`test_round_not_closed_never_fixed`）。表で `report` を absent にするので `settle` の `RecordInvalid` が線 A で起きないことを Task 3 `test_report_absent_so_record_invalid_unreachable` で固定した。
- **I4**（YAML とスクリプトの配線）: 裁定 TA16 を足した。各 script が読む `INPUTS_*` を定数 `INPUTS` に置き（Task 10a・11〜15）、Task 17 の `test_script_inputs_match_with` が YAML の `with:` と突き合わせる。Task 16 の `run_line` は `linekit.LINE_ORDER` と定数から環境を組み（`test_env_only_declared_inputs`）、Task 17 の `test_line_order_matches_linekit` が YAML と突き合わせる。模擬実行の筋書き `standard`・`start-refused` は `start` を本物で回す（1 本目の `finish` と同じ役目）。
- **I5**（`p2.rejudge`・`p2.rejudge_third` の行）: 仕様 10 節の表と「残る欠け」に行を足し、持ち主の答え待ち（線 B が聞いた。案は 3 つ）と書いた。節の表の理由を「線 B」から、何が無いかを言う文に替えた（Task 3 `test_rejudge_reason_names_the_gap`）。
- **I6**（試しの結果が前提の「上」「同」）: 仕様 10 節の 3 行（読んだ証拠・起動ごとの柵・子を木ごと止める）を条件付きにし、試しが不可の時の評価も書いた。`reads.py` は `EVENTS_VERIFIED` が偽の間、出来事の出どころを `unverified`・各行の `event` を `null` にし、報告の冒頭 4 に「出来事: 未確認（P13）」と出す（Task 6 `test_events_unverified_until_p13`、Task 15 の `head_reads`）。
- **M1**: 前提の段を、盤面の層は Task 6 まで入った（97a8ee7・18e37a2）、`begin`・`base_output` はその Task 8 でまだ無い、に直した。
- **M2**: 裁定 TA19 を足した。`take` は写しの `AnswerReject` だけを役に返し、ほかの `Reject` と `BoardGap` は終了コード 2（Task 9 `test_take_on_halted_raises_not_role_reject`）。盤面の仕様 8.1 の「Reject のまま」の文は盤面の層の持ち物なので、回す側から盤面の層へ渡してほしい。
- **M3**: Task 10a の手順 1・4 に、止めた盤面へ `b.stop` を 2 度呼ばず、止め札の理由は `allow_halted` で開いた盤面の trace にだけ書く、を書いた（`test_stop_flag_after_halt_goes_to_trace`）。
- **M4**: Task 17 の線の `with:` を全部書いた（`judgment_file`・`open_units` は `h-plan` が控えて後ろの境の節が返す。`planning`・`reviewing`・`refixing` の `with:` も明記）。Task 10a の返りに `judgment_file`・`open_units` を足した（`test_judgment_carried_to_later_edges`）。
- **M5**: Task 17 の YAML の検査に 4 つ目「`when:` を持つ節に `depends_on` する節は `trigger_rule: none_failed_min_one_success`」を足した。
- **M6**: `take` の呼び方を全部 `take(board, nid, reply, repo, …)` に揃え、作業ファイルの一覧に `review1-snapshot.json`・`review2-snapshot.json` を足した。
- **M7**: `entry.run_ci` が `run_engine` の返りを全部扱う（`relaunch` は 1 度だけ呼び直し、`why` だけの返りは止める）。`start` と `blk-tests` の `final` が共に使う（Task 7 `test_run_ci_relaunch_once`・`test_run_ci_why_only_refused`）。
- **M8**: 結末に `interrupted` を足し、`dev/report.sh` が取り消し・`abandon`・役の出し直しの上限で落ちた run に使う形にした（Task 15）。SKILL にも書く（Task 17 Step 4 の対象）。
- **M9**: `report.gate_record` が止めていない盤面を先に `settle` し、Task 16 の `test_no_silent_gap` を止めた道にも当てた。
- **M10**: Task 10 を 10a（止め札・関所の答え・次のブロックの決め方）と 10b（`h-plan` の仕事）に分けた。作業の数は 22 になった。
- **M11**: Task 20・21 は答えの後の別の小さな計画と枝で行う、と Global Constraints と両 Task に書いた。
- **M12**: 受けた（直さない）。
- **Task 17 の審査の区切り**: 1 commit のまま、Step 2・3・4 の終わりで試験を回し、その手順の差分を審査役が読む（区切り 1〜3）と書いた。

## 改訂（持ち主の答え 2026-09-27）

朝の 4 つの答えを入れた（仕様の同じ名の節も見よ）。番号は 24 個（1〜23 のうち 10 を 10a・10b に分けた）。Task 20 は閉じて作業が無いので、動く作業は 23 個。回す順の変更は「並べ方」の波 7 と、Task 21 を「後」から枝の中へ入れたこと。

- **1. 軽量は案 1（下げない）**: 裁定 TA7 を「持ち主の決定」にした。Task 20 は作業なしで閉じた（1 版の案 2 の配管は作らない）。Task 7 は拒否の文を「持ち主の決定」に替え、効かなくなった `thickness_decider` を入力・返り・`start.py`・線の YAML（Task 17）から消した（`test_light_refused_by_owner_decision`）。
- **2. 並行 PR は案 (a)**: 裁定 TA8 を書き替えた。Task 21 を答え待ちの枝分かれから普通の作業にした（`prcheck.py`・`blk-pr`・`downgrades.json`。`start` が engine の 1〜5 段を走らせ、任せ先に落ちた時だけ読むだけの opus の役。`handed_over: true` は受け付けが拒む）。YAML は Task 17。報告の冒頭 1 に下書き、冒頭 2 に下げた行（Task 15）。Global Constraints の M11（答えの後は別の枝）は取り下げた。
- **3. 前提と目的**: 裁定 TA14 を書き替えた。Task 22 を足した（`premises.py`・`blk-premises`・境の節 `h-judge`・`request_claims_covered`）。Task 2 に入口 `premises_file` と指示書の段落を足した（線 B の物への 1 度の手入れのまま）。目的 `p0.purpose` は線 B に入り、線 A の表では absent のまま。包みの確かめを `h-plan` から `h-judge` へ移した（裁定 TA9。Task 10b に注記、Task 22 で動かす）。
- **4. 同じ周の再審は上位互換**: 裁定 TA20〜TA24 を足した。Task 2 に `node_marker.py` と判定役の印を足した（線 A の再審が線 B の判定 v2 より前でも継げるように。`test_blk_judge.py` の 1 つの試験の比べ方も同じ commit で直す）。Task 5 に会話の継ぎ（印の読み方・判定役の id の記録・`continue` の差し替え・id が無い時の exit 3・切符が無くても継ぐ・`no-post` の柵）と `adapter.session_path` を足した。Task 23 を足した（`rejudge.py`・`blk-rejudge`・境の節 `h-rejudge` の先の確かめ・争点でない単位の変化の記録）。Task 15 に費用の引き算（`cost_rows`・`head_cost`）と、再審・申し送り・前提の冒頭の行を足した。
- **印を全部の役に**（TA20）: Task 11・12・13 の役の `output_format` を `mark(role_schema(…), 名)` にし、試験は `strip` して比べる形にした。Task 17 の YAML の検査に「全部の役が印を持ち、名が一意」「`continue=` を持つ役だけ `context: fresh`」「Bash を持つ読むだけの役の一覧」を足した。
- **境の節**: `h-judge`（T22）・`h-rejudge`（T23）を足した。Task 10a の `AT` の注記、Task 16 の止め札の試験、Task 17 の線の形（`pr-checking`・`premising`・`h-judge`）と筋書きを直した（数は下の回す側の指示の項）。
- **試し**: Task 18 に P18（任せ先の役が sandbox の下で `gh` を読めるか・`no-post` の柵。偽の `gh` で見るので外へは書かない）・P19（AI 費用 0。出来事に節の費用が載るか）・P20（本物の修正役の異議で再審が判定役の会話を継ぐか・費用の引き算）を足した。〔継試〕の結果（包みの会話の継ぎは平らな線と輪の中で動く）は前提として使う。
- **線 B との口**: 線 B が使う物を 1 か所ずつにした: `node_marker`（T2）・`adapter.session_path`（T5）・`prcheck.run_helper`（T21）・`premises.*` とブロック `blk-premises`（T22）・`rejudge.route`・`rejudge.session_ready` とブロック `blk-rejudge`（T23）・報告の部品 `head_cost`・`declared_downgrades`（T15）・`gl_map.json`（T24。線 B は自分の行を線 B の最後の共有の commit で足す）。線 B の計画の同じ名の節がこれらに揃えた。
- **回す側の指示（本線の調べ 作業の控え（scratchpad）の `mainline-blocks-survey.md` と本線からの知らせ。2026-09-27）**:
  - 再審は本線の 3-6（d1b863f）の形（`p2.rejudge` → `p3.rejudge_reply` → `p2.rejudge2` → `p3.rejudge_reply2` → `p2.rejudge3` → `p2.rejudge_third`）。0.21.0 の形は第三の目が立たない穴があるので写さない。包みの `--resume` の仕組みはそのまま。そのため Task 23 を「写し直しの後」に動かし、Task 16・17 から再審の分を外して Task 23 へ移した（筋書きは切り替えの時 10 本、Task 23 の後 12 本。境の節は 9、Task 23 の後 10）。裁定 TA21 を書き替えた。それまで再審の節は absent（下・宣言）。
  - 受け付けの口は本線の 3-8 まで `accept.py` のまま。`gl.py` にはまだ依頼に依らない検査の口・役の schema から注記を外す口・判定の受け付け・差分を切る段が無い。`accept.py` に検査を足さず、works だけの検査はブロックの受け付けのスクリプトに置いた（`check_claims` は `blk-premises/scripts/accept.py`、`check_no_post` は `blk-pr/scripts/accept.py`）。対応表の Task 24 を足した（裁定 TA25）。
  - ブロックの置き場と名前は本線の 3-7 が落ち着いてから決まる。今は works の仮の名で作り、`where` も works の置き場だけ。3-7 の後に揃える Task 25 を足した（裁定 TA26）。
  - 写し直しは 3-5・3-6 が版に入ってから 1 回で。その時に要る物（節の表と手本の graph_sha・`p2.fix_units` と再審の 4 節・盤面の層の受け付けを `commands.post_check` に・`DeltaPass.state_key` が消える・線 C の `mutcore` が `p3.gates_cut` の出力を読む・写す物が増える）を「写し直しへの依存」に控えた（線 A の作業ではない）。
  - 止める猶予: 本線は呼ぶ側が選べる形（既定 5 秒）にする。works は 2 秒のまま（Global Constraints）。
