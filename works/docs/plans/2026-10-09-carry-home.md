<!-- coldwrite:skip 内部の作業計画。語は計画 docs/plans/2026-10-09-chained-rounds.md と docs/concepts.md で定義 -->
# 持ち越しの住処 carry.py（周をつなぐ計画の Task 1 の作業の手順）

> **実装する者へ:** superpowers:executing-plans で回す。手順は `- [ ]` で追う。親の計画は `docs/plans/2026-10-09-chained-rounds.md` の 11 節 Task 1（以下「親」）。

状態: 済み（2026-10-09、枝 `wip/carry-home`）。

**目的:** 次の run への持ち越し（考え `carry-over`）の形を 1 つのモジュール `.shared/core/carry.py` に集め、書き手（報告）と読み手（依頼の入口）が同じ欄の名を引き、同じ JSON Schema を読む。振る舞いは変えない（`next-request.json`・`prior-failures.json`・`prior-failures-in.json` はバイト一致）。

**作り:** `carry.py` は層 L1（標準ライブラリと写しの `engine.schema` だけ。Python 3.9 で動く）。形（欄の名・ファイルの名・下書きの印・Schema の読みと照らし・依頼の解き方・置き場への読み書き）だけを持ち、何を運ぶかの決め（残りの行・答えの下書きの選び）は今の呼び手（`report`・`gatemarks`・`outpurpose`）に残す。

**仕様:** 親の 4.8 節と 11 節 Task 1。考えの地図 `docs/concepts.md` の `carry-over`。

## 決め（親から変えた所と、その訳）

1. Schema の置き場を core へ移す（`darkfactory/schemas/{next-request,prior-failures}.schema.json` → `.shared/core/`）。訳: core はラインの名を書けない（`tests/test_layers.py` の name）。core の Schema をラインの宣言から `../.shared/core/…` で指す形は `reads.schema.json` に先例が在る。中身は変えない（題の書き手の名だけ直す）
2. 書き手は書く前に Schema で照らし、合わなければ ValueError（works の不具合。黙って約束の外の物を置かない）。読み手は今の手書きの確かめ（文の誤りの字は今のまま）に、`prior_failures` の行を同じ Schema で照らす 1 段を足す。欄の名の定数と Schema の欄が揃うことは試験が縛る
3. `prior_section` は盤面の層を知らない（L1）ので、読めない時に投げる例外の型を呼び手が渡す（`gap=BoardGap`）
4. 殻の口 `carry-ci` は `carry.py` へ移す。`ghreads.py` を口として起こした時は、移った先を 1 行で言って 2 で終わる（前の打ち方を黙って通さず、能力も減らさない）
5. `dev/lib.sh` の下書きの数えは `carry.is_draft`（入口が拒む行と同じ決まり。`draft` か `source` の在る行）に揃える
6. `row_key` は親の Interfaces に在るので入れる（Task 3 が使う）
7. `ghreads` は `carry` を import しない（親の 4.8 は「ghreads が import する」と書いたが、依頼の容器を解く所は全部 `carry` を直に引くので、`ghreads` に残るのは PR・issue の読みだけになった）

## Task 1: carry.py（振る舞いは変えない）

**Files:** Create `.shared/core/carry.py`・`tests/test_carry_home.py`。Move `darkfactory/schemas/next-request.schema.json`・`prior-failures.schema.json` → `.shared/core/`。Modify `.shared/core/{ghreads,report,entry,gatemarks,outpurpose,purpose}.py`・`blk-judge/lib/judgebrief.py`・`blk-plan/lib/planblk.py`・`blk-{judge,premises,purpose}/scripts/intake.py`・`darkfactory/manifest.json`・`dev/lib.sh`・`skills/works/SKILL.md`・`docs/concepts.{md,json}`・`tests/test_layers.py`・`tests/tiers.py`・今の試験の import 先

**Interfaces（Produces）:**
- 名: `FINDINGS`・`ANSWERS`・`PRIOR`・`DRAFT`・`SOURCE`（欄の名）、`KEYS`・`ANSWER_KEYS`・`DRAFT_KEYS`・`PRIOR_KEYS`・`CI_WHERE`、`NEXT_REQUEST_FILE`・`PRIOR_FAILURES_FILE`・`PRIOR_IN_FILE`・`PRIOR_HEAD`
- `schema(name) -> dict`・`errors(doc, name) -> list[str]`（name は `NEXT_SCHEMA`・`PRIOR_SCHEMA`）
- `parts(doc) -> dict`（今の `ghreads.request_parts`）・`without_prior(doc)`・`carry_ci(doc, ids) -> dict`
- `is_draft(row) -> bool`・`draft(row, source, note="") -> dict`・`compose(findings, prior, drafts) -> dict`・`row_key(row) -> str`
- `save_next(board_dir, doc) -> Path`・`save_prior(board_dir, rows) -> Path`・`place_prior(board_dir, rows) -> None`・`prior_section(board_dir, gap=ValueError) -> str`

- [x] 金型を取る: 変える前の木で、持ち越しのファイルを書く試験（test_report・test_entry・test_gate_drafts・test_out_of_purpose・test_carry_ci・test_blk_purpose・test_blk_judge・test_blk_premises・test_line_a・test_edge・test_use・test_dev）を、`os.replace` の先が 3 つの名の時に中身を写す sitecustomize を差して回し、写しを残す
- [x] 赤: `tests/test_carry_home.py` に `test_carry_names_live_in_carry`（柵の表の `carry-over` が通る）・`test_compose_then_parts_roundtrip`・`test_row_key_ignores_reason_tail`・`test_ghreads_keeps_only_github_reads`・`test_constants_match_schemas`・`test_writer_refuses_off_contract`・`test_prior_section_raises_given_gap`
- [x] 回して赤を見る: `python3 tests/tiers.py fast -k test_carry_home`
- [x] 移す。古い名を残さない（`grep -rn "ghreads.request_parts\|ghreads.DRAFT_KEYS\|entry.place_prior\|entry.PRIOR_IN_FILE\|report.NEXT_REQUEST_FILE" works/` が 0 件）
- [x] 地図と表: `carry-over` を住処ありにし、柵（ファイルの名・欄の名の字・下書きの印の作りと読み）を掛ける
- [x] 緑: 速い段・`dev/check.sh`・根の柵・触ったモジュールの重い試験。金型を取り直して変える前と同じ
- [x] commit `refactor(works): 次の run への持ち越しの形を core の carry に 1 つにまとめる（書き手・読み手・置き場が同じ名と Schema を引く）`

## 見張る所

1. 依頼の誤りの文が変わる（利用者が見る 1 行）→ 今の文の試験（test_gate_drafts・test_carry_ci・test_entry）をそのまま通す
2. `python3 -I carry.py` が写しの engine を読めない（`-I` は置き場を sys.path に足さない）→ test_carry_ci の CLI の試験を carry.py に向けて通す
3. 報告が Schema の照らしで落ちる（今まで通っていた行が Schema の外）→ 触ったモジュールの重い試験の緑と、金型（変える前の木で書いた持ち越しのファイル）の一致で見る
