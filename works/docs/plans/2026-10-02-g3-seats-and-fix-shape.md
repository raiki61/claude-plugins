# 借りたスキルの座と修正の形の切り替え（G3 の載せ口・fix_shape・測る関数）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

## この文書の読み方（初めて読む人向け。本文の語はここで全部定める）

置き場と道具:
- このリポジトリ（claude-plugins）は Claude Code のプラグインを集めた物。パスは、断りが無ければリポジトリの根からの相対。`CLAUDE.md:20` は根の `CLAUDE.md`（このリポジトリの作業の決まり）の 20 行目。
- 本流: リポジトリの根の `graphloops/` フォルダに在る別のプラグイン（AI のレビューと修正の工程を回す物）。works はその graph と規則をバイト単位で写して使う（写しは `works/.shared/core/graphloops/`・`works/.shared/core/gl-prompts/`）。本流も写しも、この計画では変えない。
- works: リポジトリの `works/` に在るプラグイン。Archon（AI の作業の流れを YAML で回す外の道具。記録は SQLite のファイル archon.db）の上で、人の修正依頼を直す工程を回す。run は works の工程の 1 回の実行。
- darkfactory: works の線（YAML `works/darkfactory/darkfactory.yaml`）。判定 → 修正案 → 修正 → 差分の審査 → 手直し → 最後のテスト → 最後の人の関所、と回す。
- 盤面: run ごとの状態の置き場（`$ARTIFACTS_DIR/board/`。JSON のファイルの集まり）。周（round）ごとの作業ファイルは `board/r<N>/<名>` に在る。線の境の節（名が `h-` で始まる節。例: 修正の前の `h-fix`）が、盤面で次に回せる節（ready）を見て次のブロックを回すかを決める。
- 包み（adapter）: `works/.shared/core/adapter.py`。Archon と本物の claude の間に入る殻。起動ごとに `--settings` に拒否（柵）を足す。切符（`works/.shared/core/ticket.py`。線の start が書く小さな JSON で、盤面の置き場を持つ）が在る起動だけに柵が効く。役の節は `output_format.description` に印 `works-node: <節の名>` を持ち、包みはその名で節を見分ける。
- 試験の段: `works/tests/tiers.py` の FAST（速い段）と HEAVY（重い段: git のリポジトリ・盤面・子のプロセスを使う）。手元で回すのは速い段だけ。重い段の全部と変異テストは GitHub の CI だけ。

依頼（works の直しを works 自身の工程に流す頼みごとの 1 件。番号で呼ぶ）。この文書は 220 番を実装する。220 は 214 番（座）と 215 番（形の切り替え）を吸収した物。関わる依頼と、この計画が頼る所（どれも本文の Interfaces に名と形を書き写した）:
- 216: superpowers（下の語）の版 6.4.2 の使うファイルを `works/.shared/borrow/superpowers/6.4.2/` に写して固定し、包む節（下の語）を `works/.shared/borrow/seams.json` に置く。照合と穴埋めの模块 `works/.shared/core/spseam.py`。計画は `../claude-plugins-work1-sdd5/works/docs/plans/2026-10-02-superpowers-pin-and-seam.md`。
- 217: 修正案の項目に欄（受け入れのテスト `tests`・書き換えてよい既存のテスト `rewrite_tests`・整えの申告 `refactor`・振り分け `route`）を足し、項目ごとの brief を修正役の要求の正本にする。取り込み済み（この枝の起点 10ae035d）。
- 218: 修正案からの外れの機械の検査と、差分の審査の 2 判定（準拠と品質）。計画は書いている途中（`../claude-plugins-work1-sdd7`）。
- 219: TDD の輪の 1 周期を修正案の欄で回す（赤の種類の照合・名指しの書き換え・`test_cmd` の関門・整えの申告）。計画は `../claude-plugins-work1-sdd6/works/docs/plans/2026-10-02-tdd-cycle.md`。
- 211: 食い違いの申し出の種類と、裁定 `fix_plan_item`。計画は書いている途中（`../claude-plugins-work1-sdd8`）。
- 221: 後の依頼。依頼ごとに修正の形を選ぶ振り分け（router）と、大きな依頼を run の中で小さな作業に割る SDD の道（lane）。この計画は作らず、継ぎ目だけを残す（末尾の節）。

持ち主の手元の資料（`~/.cache/works-dogfood/`。要る所はこの文書に書き写した。開かなくても実装できる）:
- `req-220.json`: この依頼の文。
- `design-205e.json`: 独立設計（目的だけから作った設計。設計だけの run 205e の出力）。節は ■ と番号で呼ぶ。この計画が拠る節は次の 5 つ。
  - ■8: G1・G2・G3 の比べと決定。
  - ■9: 試し（入力による切り替え）。
  - ■10: G3 の層（版の固定・継ぎ目・線）。
  - ■11: 当事者の日常の動線（撤収）。
  - ■12: 後の小さな run への割り方。
  設計の中身の記号 A〜F は、A: brief を要求の正本にする（217）・B: 案からの外れの機械の検査（218）・C: 受け入れのテストの事前決定と赤→緑（217・219）・D: 名指しの既存テストの書き換え（217・219）・E: 整えは申告の時だけ（219）・F: 差分の審査の 2 判定（218）。
- `plan-review-205e.json`: 同じ run の事前審査（前の案を別の目が叩いた返答。faces は穴の一覧、shrink は小さく閉じる案）。
- `judgment-205e.json`: 同じ run の判定（根本の単位と処方）。
- `keep-essence.txt`: どの形でも残す works の強み 11 項目（Global Constraints に名を写した）。

works の中の語:
- 修正の工程: 線のうち `fixing`（ブロック blk-fix: TDD の輪・修正役・裁定・2 回目の修正役）・`reviewing`（blk-delta: 差分の審査）・`refixing`（blk-refix: 手直し）の 3 つ。Archon の出来事の `step_name` の頭は `fixing__`・`reviewing__`・`refixing__`。
- TDD の輪: blk-fix の節 `tdd-loop`。判定の単位ごとに、振り分け → 落ちるテストを書く → 直す → 整える を AI の役 `tdd` に返させ、機械（`works/blk-fix/lib/tddloop.py`）が赤・緑を確かめる。拒否が 3 回続いた単位は作業ツリーを戻して direct（輪の後の修正役が直に直す道）に回す。
- 修正案: 直す前に案を書く AI の役（盤面の節 `p2.fix_plan`）の返答。項目の並び。事前審査と人の関所を通った物を「承認済みの修正案」と呼ぶ。欄は 217 の上の 4 つ。
- brief: 217 が承認済みの修正案の 1 項目を Markdown に切り出し、sha256 で凍結した物（`works/blk-fix/lib/planbrief.py`）。
- 219 の名: `red_kind` は受け入れのテストが落ちる形（`assertion`・`exception`・`unknown`・例外の名）。`GATE_OFF` は `test_cmd` の関門を回さない印。`calls` は輪の 1 回の確かめごとの記録の行。`_unnamed_edits` は名指していない既存のテストの関数の変更を探す関数。
- superpowers: Claude Code のプラグインのスキル集（MIT）。SDD はその中の subagent-driven-development（下請けの AI に作業を割り、実装役と審査役を回す手順）。
- 節（seam）: 216 の `seams.json` の 1 項目（`tdd`・`implementer`・`task-review`・`receiving-review`）。スキル 1 本か部品 1 ファイル（SDD の実装役・審査役の指示書の型）を包み、効く部分（`applies`）・効かない部分（`not_applies`）・読み替えの錨・穴（`[BRIEF_FILE]` などの角括弧の埋め草）・出口の語（`words`）を持つ。
- 座: 節を役に載せる口。YAML の `skills:` と、指示書の 1 節。この計画が作る。
- 読み替え（overlay）: 216 の `works/.shared/borrow/unattended.md`。superpowers の文が人や調整役を前提にする所を、無人の役でどう読むかの決まり。`rolekit.skill_overlay()` が頭の 1 行と全文を返す。役への直の指示で、スキルの文より勝つ。

この計画の語:
- 形（fix_shape）と腕: 修正の工程の作り方の 4 つ。試しでは形ごとの run を「腕」と呼ぶ。
  - `current`: 比べの基準。A〜E を修正の段で切った形。
  - `af`: A〜F を works 自身の文で回す形（217〜219・218・211 を取り込んだ今の形）。
  - `g3`: af に借りたスキルの座を足した形（既定）。
  - `g1`: 修正役 1 つが SDD の型で下請けを回し、機械の確かめを事後に当てる形。
- 平の run: 形が current の run。`fixshape.plain(board_dir)` が真。
- 事後の関門の束（battery）: この計画で足す `works/blk-fix/lib/fixgates.py`。修正の受け付け（節 fix-accept）で、base（修正の起点の版）から今の木までを相手に、受け入れのテストの赤→緑と既存テストの変更を確かめる。
- 固定材料（fixture）: h-fix の時の盤面の写しと、その時の木の hash の組。同じ依頼を腕ごとに同じ所から始めるのに使う。
- 抜け（gate miss）: 束が見つけた物。腕の中の流れ（TDD の輪・g1 の下請け）が通したのに、外側の関門で落ちた物。
- 混ざり（contamination）: その腕で拒んだはずの道具（g3 以外の Skill、g1 以外の Agent）の呼び出しが Archon の出来事に在ること。柵が効いていない印。

---

**Goal:** 216 で固定した superpowers の節を、修正の工程の役（TDD の役・修正役・差分の審査役・手直しの役）に載せる座を作り、run の入力 `fix_shape`（current・af・g3・g1。既定 g3）で修正の工程の形を切り替える。同じ依頼を固定材料（凍結した判定・承認済みの修正案・起点の木）から腕ごとに回し、項目あたりの作り直し・費用・節の時間・裁定と申し出・機械の関門の抜け・記録の欠け・保守量を機械で数え、試しの前に決めた採否の決まりで判定する。

**Architecture:** 形は 1 か所に記録し、どこでもそこから読む。

- 線の `start` が入力 `fix_shape` を確かめて盤面の控え `r1/start.json` に置く。新しい模块 `fixshape` が盤面の置き場から読む（ブロックの YAML に入力を通さない）。後の振り分けが選んだ形を置く控え `r1/fix-shape.json` も、同じ読み口が先に読む（この計画では誰も書かない）。
- 座は模块 `seat` が 216 の `seams.json` から組み、各ブロックの指示書の組み立て（`fixrules`・`refix.cut`・`refixrules`）が「節」として載せる（2 回目からは差分の形 delta に乗る）。g3 の時だけ文が出る。
- YAML の AI の節は腕ごとに分けない。`skills:`・`Skill`・`Agent` は静的に宣言し、包みが切符の盤面から形を読んで、その腕で使わない道具を `permissions.deny` で拒む。
- 機械の関門は全部の腕で同じ。TDD の輪の中にだけ在った関門（受け入れのテストの赤→緑・名指しの外の既存テストの変更）を、束が修正の受け付けで事後にもう 1 度当てる。束が見つけた物を抜けとして数える。
- 固定材料は h-fix の時の盤面の写し。次の run は入力 `fix_fixture` で写しを取り込み、判定・修正案を作り直さずに修正から始める。
- 測る関数と採否の判定は開発の殻 `works/dev/fixmeasure.py`（archon.db と盤面を読むだけ）。

**Tech Stack:** Python 3.12 以降の標準ライブラリ（`json`・`hashlib`・`pathlib`・`shutil`・`sqlite3`・`subprocess`）、works の盤面の層（`entry`・`board`・`conflict`・`planmarks`）、216 の `spseam`、219 の `tddloop` の関数、POSIX sh（`works/dev/dogfood.sh`）、unittest（`works/tests`）。

**Spec:**
- 依頼の文 `req-220.json`（鍵 `text`・`mechanism`）。
- 独立設計 `design-205e.json` の ■8・■9・■10 の層 2（継ぎ目）と層 3（線）・■11・■12 の 9〜10。
- 先に塞ぐ穴（`plan-review-205e.json`）:
  - face `overlay-already-shared-move-is-churn`: 読み替えの配達の口は `rolekit.skill_overlay` のまま呼ぶだけ。試験 `test_sp_skills` の配達の検査を直す。節に `Skill` を足す。
  - face `tdd-skill-on-direct-fix-node`: direct の修正役に test-driven-development を宣言しない。
  - face `delta-review-cannot-carry-compliance`: 審査役の材料は `refix.cut` の brief に足す。
  - shrink `shrink-call-overlay-not-move`。
- 判定 `judgment-205e.json` の単位 `borrow.json skills`・`direct.md+tdd.md plan_file` の処方 [4]（比べる試し）。

## Global Constraints

- 本流 `graphloops/` と、works の中の写し `works/.shared/core/graphloops/`・`works/.shared/core/gl-prompts/` は変えない（`CLAUDE.md:20`）。
- 216 の物は使うだけで変えない: `works/.shared/borrow/**`（`seams.json`・`unattended.md`・`borrow.json`・写し）・`works/.shared/core/spseam.py`・`works/dev/toolset.py`。節の名と欄（`use_as`・`files`・`applies`・`not_applies`・`placeholders`・`words`）は 216 の計画の Task 1・4 のとおり。
- works の強み 11 項目はどの腕でも外さない: 赤緑の機械の判定・元から赤の区別・凍結と許しの 1 本の道・3 回で戻す・書き込みの出どころ・受け付けで選んで回す試験・class_query の数え直し・申し出と裁定・独立設計と R1〜R4・守りのファイルと最後の関所・単位ごとの記録。どの腕も同じ外側の関門（修正の受け付け・束・差分の審査・最後のテスト・最後の関所）を通る。g1 では赤緑と凍結が輪の中に無いので、束がそれを受け持つ。
- 期限・タイムアウトを新しく足さない。止めるのは条件だけ。時間は測って報告するだけで、採否の条件にしない。
- 今ある能力を減らさない: `fix_shape` が空の run は g3、前の版で作った盤面（`r1/start.json` に `fix_shape` が無い）は af として動く（座は出ず、道具の振る舞いは 220 の前と同じ）。
- 後の振り分けを塞がない: 形はいつも `fixshape.shape_at` の 1 つの読み口から引く。ブロック・包み・測る関数が `start.json` を直に読まない。腕ごとの違いは `SHAPES`・`denied_tools` の表・`seat.SEATS` の表で持ち、語を決め打ちする分かれを散らさない。
- 並行の枝と重ねる所（取り込みの衝突を小さくする）:
  - `works/blk-fix/lib/tddloop.py`（219・211 が大きく変える）: 触るのは `start` の頭の 1 分岐（g1）・`plan_contract` の頭の 1 行（平の run）・`_fix` の整えの条件の 1 項（平の run）・`start` の test_cmd の関門の決め方の 1 分岐（平の run）・`prep` の座の 1 引数と、公開の別名 `unnamed_edits = _unnamed_edits` だけ。
  - `works/blk-fix/lib/fixrules.py`: `fix_parts`・`tdd_parts`・`tdd_render`・`tdd_prompt`・`fix_prompt` の `seat=""` の引数と、新しい関数 `implementer_values`・`g1_values` だけ。
  - `works/blk-fix/scripts/accept.py`: `accept_fix` の最後の 1 段（束）と `INPUTS` の 1 語だけ。
  - `works/.shared/core/refix.py`（218 が brief に欄を足す）: `cut` の brief の辞書に鍵 `seat_file` を 1 つ足すだけ。
  - `works/darkfactory/darkfactory.yaml`・`works/blk-fix/blk-fix.yaml`（219 が `test_cmd` を通す）: 入力 2 つ・start の `with` 2 行・fix-accept の `with` 1 行・節の `skills:`・`allowed_tools` だけ。
- 層（`works/tests/test_layers.py` の表 MOD。上の層は同じ層か下の層だけを import する。L2 は包み、L3 は盤面と受け付けの共有の部品、L4 はブロックの模块、L8 は dev）: `fixshape` は L2（包みが読む。標準ライブラリだけ）、`seat` と `fixture` は L3（`fixture` は `entry`・`board` を import しない。`entry` が読む）、`fixgates` は blk-fix の L4、`fixmeasure` は dev（L8）。
- Python 3.12 が下限。新しい注記・docstring・指示書の文は日本語。新しい模块は `from __future__ import annotations` で始める。
- 焦点の試験: `cd works/tests && PYTHONDONTWRITEBYTECODE=1 python3 -m unittest <module>[.<Class>]`（重い段の模块は、この計画で足した class か試験だけを名指して回してよい）。組の仕上げ: `WORKS_TESTS=fast nice -n 19 sh works/tests/run.sh` と、リポジトリのルートの軽い柵 `sh ~/.cache/works-dogfood/rootfences.sh`（ルートの `tests/run.sh` から文書の定数・数の突き合わせ・写しの一致の検査だけを抜いて当てる殻）。
- 役の返答の型・ブロックの入力・script の `with` を変えた Task は、同じ Task の中で筋書きの返答（`works/tests/replies/*.json`・`works/tests/linekit.py` の線の写し・`works/*/fixtures/*.stubs.yaml`）と表の試験（`test_line_inputs`・`test_blk_fix_tdd.TestYaml`・`test_line.LineShapeCase`）を合わせる。
- CHANGELOG は `works/CHANGELOG.md` の `[Unreleased]` に、Task 8（最初の組の終わり）と Task 10 で足す。版は上げない。
- commit のメッセージの末尾に `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`。push はしない。

## 採否の決まり（試しの前に固定。この計画の事前審査に掛け、試しの後に動かさない）

Task 8 の `fixmeasure.verdict` がこの決まりをそのまま実装し、試験が数を縛る。

1. 材料: 固定材料を 3 件以上（`MIN_FIXTURES = 3`）。どれも修正案の項目が 2 つ以上で、tdd の項目を 1 つ以上含む依頼から持ち主が選ぶ。4 つの腕を各固定材料で 1 回ずつ回す。
2. 行の有効性: 次の行は比べに使わない。同じ（腕・固定材料）を 1 回だけ回し直す。回し直しても有効でなければ、判定は `incomplete` で、欠けた組を名指す。
   - run が終わっていない（Archon の run が completed でない・盤面に報告が無い）。
   - 混ざりが 1 件以上（柵が効いていない。試しを止めて柵を直す）。
   - 記録の欠けが 1 件以上。
   - 実行器（入力 `tdd_suite`）が無く、束の赤緑が回っていない。
3. 抜け: 抜けが 1 件でも在る腕は既定にしない（■8 の「機械の関門の抜けを 1 件でも出せば採らない」を全部の腕に当てる）。
4. g3 と af: 項目あたりの作り直し（`redo_per_item`）と項目あたりの費用（`cost_per_item`）で比べる。どちらも全固定材料の和を項目の数の和で割る。次の全部が成り立てば既定は g3 のまま（`keep_g3`）。どれか 1 つでも成り立たなければ既定を af に替える（`switch_to_af`）。
   - g3 の抜けが 0。
   - `redo_per_item(g3) <= redo_per_item(af)`。
   - `cost_per_item(g3) <= COST_MARGIN * cost_per_item(af)`。`COST_MARGIN = 1.10`。
   g3 と af の両方に抜けが在れば `fix_gates_first`（強みの関門に穴が在る。採否より先に直す）。
5. g1: 既定にはしない（■8）。g1 の抜けが 0 で、勝った腕（4 の結果）に対して作り直しが少ないか、費用が `G1_MARGIN = 0.90` 倍以下なら、勝った指標の名を `import_from_g1` に並べる。G3 の節に取り込む次の依頼の種にする。
6. current: 比べの基準。勝った腕と current の差を指標ごとに `vs_current` に出すだけで、決定には使わない。
7. 報告だけの値（決定に使わない）: 修正の工程の AI の節の時間・裁定と申し出の件数と種類・保守量・修正だけ（`fixing__`）の費用。

## Review Focus

1. 前の版で作った盤面を再開した run（`r1/start.json` に `fix_shape` が無い）→ af として動く。座の節は出ず、柵は af の表どおり。（Task 1 の `test_shape_at_reads_start_record`、Task 3 の `test_denied_tools_table`）
2. Archon の再開で、呼び直しの `fix_shape` が最初の控えと違う → 盤面を作り直さず `InputRefused`（腕を黙って替えない。test_cmd と同じ扱い）。（Task 1 の `test_resume_with_other_fix_shape_refused`）
3. 固定材料を、違う木（works の版が違う・手元に変更が在る）・違う依頼・違う test_cmd・書き換えた写しで取り込もうとした → 盤面を作らずに理由を名指して `InputRefused`。（Task 5 の `test_adopt_refuses_*`）
4. g3 以外の run の役が Skill を、g1 以外の run の修正役が Agent を呼ぼうとする → 柵が拒む。それでも出来事に呼び出しが在れば、測る関数が混ざりに数え、その行を比べから外す。（Task 3 の `test_fence_denies_by_shape`、Task 8 の `test_contamination_invalidates_row`）
5. 216 の写しが pin（版・ファイルごとの sha256 の固定）と合わないか、部品の型の穴が埋まらない → g3・g1 の支度は af の文へ黙って逃げず、名指して止まる（支度の script の終了コード 2）。（Task 2 の `test_fix_seat_refuses_broken_pin`）

---

### Task 1: 修正の形の入力と盤面の控え（`fixshape`）

**Files:**
- Create: `works/.shared/core/fixshape.py`
- Create: `works/tests/test_fixshape.py`（FAST。一時の置き場の JSON を読むだけ）
- Modify: `works/.shared/core/entry.py`（`check_inputs` に `fix_shape`、`start` の呼び直しの確かめと `out`・頭の行）
- Modify: `works/darkfactory/darkfactory.yaml`（入力 `fix_shape`、節 `start` の `with` と `output_format` の `fix_shape`）・`works/darkfactory/scripts/start.py`（`INPUTS`・`OPTIONAL`）・`works/tests/linekit.py`（start の `with` の写し）
- Modify: `works/dev/dogfood.sh`（env `WORKS_FIX_SHAPE`）
- Modify: `works/tests/test_layers.py`（`MOD` に `"fixshape": (2, None)`）・`works/tests/tiers.py`（FAST に `test_fixshape`）・`works/tests/test_line_inputs.py`・`works/tests/test_line.py`（`LineShapeCase` の入力の集合）・`works/tests/test_entry.py`・`works/tests/test_dev.py`

**Interfaces:**
- Consumes: `entry.START_FILE`（`"start.json"`）・`entry.InputRefused`
- Produces（`fixshape`。標準ライブラリだけ）:
  - `SHAPES = ("current", "af", "g3", "g1")`・`DEFAULT = "g3"`・`BEFORE = "af"`（記録の無い盤面の形）・`KEY = "fix_shape"`・`START_REL = "r1/start.json"`・`CHOICE_REL = "r1/fix-shape.json"`（後の振り分けが選んだ形の控え `{shape, by, why}`。この計画では試験のほか誰も書かない）
  - `word(raw: str) -> str` — 前後の空白を除き、空なら `DEFAULT`。SHAPES の外は `ValueError("fix_shape=<値> は知らない値（current / af / g3 / g1）")`
  - `shape_at(board_dir) -> str` — 読む順: `CHOICE_REL` の `shape` → `START_REL` の `KEY` → `BEFORE`。ファイルが無い・鍵が無いなら次へ。JSON が読めない・値が SHAPES の外なら `ValueError`（黙って既定にしない）
  - `choose(board_dir, shape: str, *, by: str, why: str) -> None` — `CHOICE_REL` を書く（`shape` は SHAPES の内、`by`・`why` は空でない。外れは `ValueError`）。後の振り分けの書き口
  - `plain(board_dir) -> bool` — `shape_at(board_dir) == "current"`
  - `entry.check_inputs` の返りに `"fix_shape"`（`word` の値。`ValueError` は `InputRefused`）。`r1/start.json` に載る（今の `keep` の道）
  - `entry.start`: 呼び直しで前の控えの `fix_shape` が今の値と違えば `InputRefused`。返り `out` に `"fix_shape"`。頭の行に `・修正の形: <形>`（入力が空なら `（既定）` を足す）
  - darkfactory の入力 `fix_shape`（既定 `""`、説明は 4 つの語と既定 g3）。start の出口に `fix_shape: {type: string}`
  - `dogfood.sh`: `WORKS_FIX_SHAPE` が空でなければ 4 つの語のどれかか確かめ（外は使い方の誤りで 2）、`--input fix_shape=<値>` を足す（`WORKS_DESIGN_ONLY` の行の隣）

- [ ] **Step 1: 落ちる試験を書く**

```python
# test_fixshape.py
def test_word_default_and_refuses_outside(self):
    self.assertEqual(fixshape.word(""), "g3")
    self.assertEqual(fixshape.word(" af "), "af")
    with self.assertRaises(ValueError) as cm:
        fixshape.word("g2")
    self.assertIn("current / af / g3 / g1", str(cm.exception))

def test_shape_at_reads_start_record(self):
    self.assertEqual(fixshape.shape_at(self.tmp), "af")                       # start.json が無い（前の版の盤面）
    put(self.tmp / "r1" / "start.json", {"test_cmd": ""})
    self.assertEqual(fixshape.shape_at(self.tmp), "af")                       # 鍵が無い
    put(self.tmp / "r1" / "start.json", {"fix_shape": "g1"})
    self.assertEqual(fixshape.shape_at(self.tmp), "g1")
    self.assertFalse(fixshape.plain(self.tmp))
    for bad in ('{"fix_shape": "x"}', "{壊れた"):
        (self.tmp / "r1" / "start.json").write_text(bad, encoding="utf-8")
        with self.assertRaises(ValueError):
            fixshape.shape_at(self.tmp)

def test_choice_wins_over_input(self):
    put(self.tmp / "r1" / "start.json", {"fix_shape": "g3"})
    fixshape.choose(self.tmp, "af", by="test", why="振り分けの継ぎ目の確かめ")
    self.assertEqual(fixshape.shape_at(self.tmp), "af")
    with self.assertRaises(ValueError):
        fixshape.choose(self.tmp, "x", by="test", why="知らない語")

def test_start_rel_is_round_one_start_file(self):
    self.assertEqual(fixshape.START_REL, f"r1/{entry.START_FILE}")

# test_line_inputs.py（check_inputs を直に呼ぶ既存の class に）
def test_fix_shape_default_and_refused(self):
    self.assertEqual(entry.check_inputs(self.raw(), self.repo)["fix_shape"], "g3")
    with self.assertRaises(entry.InputRefused) as cm:
        entry.check_inputs(self.raw(fix_shape="g2"), self.repo)
    self.assertIn("fix_shape", str(cm.exception))

# test_entry.py（重い段。この 1 本を名指して回す）
def test_resume_with_other_fix_shape_refused(self): ...   # fix_shape=af で start → 同じ盤面に fix_shape=g3 で start → InputRefused（"fix_shape" を含む）。af で呼び直すと通り、out["fix_shape"] == "af"
```

`test_line.LineShapeCase.test_signature` の入力の集合に `"fix_shape"` を足す。`test_line_inputs` の TA16 の表（start の `with` の鍵と `start.INPUTS` の突き合わせ）は、YAML と script を足せば揃う。`test_dev.py` の `test_dogfood_design_only_appends_input_only_when_asked` の隣に `test_dogfood_fix_shape_appends_input_only_when_asked`（値 `af` → 引数に `fix_shape=af`・空 → 載らない・`g2` → 終了コード 2）。

- [ ] **Step 2: 落ちることを確かめる**

Run: `cd works/tests && PYTHONDONTWRITEBYTECODE=1 python3 -m unittest test_fixshape test_line_inputs`（と `test_entry` の上の 1 本を、既存の start の試験の class の名で名指す）
Expected: FAIL（`No module named 'fixshape'`・`fix_shape` の鍵が無い）

- [ ] **Step 3: `fixshape.py` を書き、入力を配線する**（上の Interfaces のとおり。`start.py` の `OPTIONAL` に `INPUTS_FIX_SHAPE` を足す——前の版の `with:` で再開した run は渡さない。`linekit` の start の `with` に `"fix_shape": "$INPUTS.fix_shape"`）

- [ ] **Step 4: 通ることを確かめる**

Run: `cd works/tests && PYTHONDONTWRITEBYTECODE=1 python3 -m unittest test_fixshape test_line_inputs test_line_wiring test_layers test_tiers` と Step 2 の重い段の 1 本。`python3 -m py_compile works/tests/test_dev.py works/tests/test_line.py`、`sh -n works/dev/dogfood.sh`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add works/.shared/core/fixshape.py works/.shared/core/entry.py works/darkfactory works/dev/dogfood.sh works/tests/test_fixshape.py works/tests/test_layers.py works/tests/tiers.py works/tests/linekit.py works/tests/test_line_inputs.py works/tests/test_line.py works/tests/test_entry.py works/tests/test_dev.py
git commit -m "feat(works): 線の入力 fix_shape（current・af・g3・g1。既定 g3）を確かめて盤面の start の控えに置き、fixshape が盤面から読む"
```

---

### Task 2: blk-fix の座（TDD の役に test-driven-development、修正役に implementer の型。g3 だけ）

**Files:**
- Create: `works/.shared/core/seat.py`
- Create: `works/tests/test_seat.py`（FAST。216 の写しと `seams.json` を読むだけ）
- Modify: `works/.shared/core/fixshape.py`（`SKILL_NODES`）
- Modify: `works/blk-fix/lib/fixrules.py`（`fix_parts`・`tdd_parts`・`fix_prompt`・`tdd_prompt`・`tdd_render` の `seat=""`、`prep` で座を組む、新しい `implementer_values`）
- Modify: `works/blk-fix/lib/tddloop.py`（`prep` が `seat.section("tdd", 形)` を `tdd_render` に渡す）
- Modify: `works/blk-fix/blk-fix.yaml`（節 `tdd` に `skills: [test-driven-development]` と `allowed_tools` の `Skill`、注記 1 行）
- Modify: `works/tests/test_sp_skills.py`（`OverlayDeliveryCase.test_every_node_that_can_read_skills_is_a_role_that_gets_the_overlay` を座の表も見る形に）・`works/tests/test_fix_rules.py`・`works/tests/test_blk_fix_tdd.py`（`TestStart` に 2 本）・`works/tests/test_layers.py`（`"seat": (3, None)`）・`works/tests/tiers.py`

**Interfaces:**
- Consumes: 216 の `spseam.load_seams() -> dict`・`spseam.fill(seam_id, values, src, item, seams) -> str`（sha256 の照合と穴の残りで `ValueError`）・`spseam.vendored_dir(item)`・`spseam.BORROW_DIR`、`borrow.json` の `superpowers`（item）、`rolekit.skill_overlay() -> str`、Task 1 の `fixshape.shape_at`。217 の `planbrief.cut`・`for_units`・`head_text`。
- Produces:
  - `fixshape.SKILL_NODES = frozenset({"tdd"})`（座が skill の節。Task 3 の柵が読む。Task 9 が足す）
  - `seat.SEATS: dict[str, str]`（印の節の名 → 節の名）。この Task では `{"tdd": "tdd", "fix": "implementer", "fix-ruled": "implementer"}`。Task 9 が足す
  - `seat.HEAD = "## 借りたスキルの座（修正の形 g3）"`・`seat.SCENE`・`seat.NO_REPORT_FILE`（下の固定の文）
  - `seat.skill_of(seam: dict) -> str` — `use_as == "skill"` の節の `files[0]`（`skills/<名>/…`）の `<名>`
  - `seat.section(node: str, shape: str, values: dict[str, str] | None = None) -> str` — `shape != "g3"` か `node` が SEATS に無ければ `""`。在れば HEAD → 節の種類ごとの本文 → `rolekit.skill_overlay()`。
    - どちらの種類の節も、頭に同じ 1 段落 `seat.WINS`（「この指示書の段の約束（返す JSON・機械の関門・段の順）と下の読み替えは、借りた文に勝つ」）を置く。
    - skill の節: `seat.WINS` の前に `seat.SKILL_LEAD`（「Skill の道具で `<スキル>` を読み、その手順で進めよ。」）の 1 文だけを足した段落、「効く所」に `applies` の各行、「効かない所（従わない）」に `not_applies` の各行。
    - prompt の節: `seat.WINS` の段落の後に、`spseam.fill(SEATS[node], values, …)` の文を「下請けの型（superpowers の <ファイル>。works の節で包んだ物）」の見出しの下に字のまま置く。`values` が None なら `ValueError`
  - `fixrules.fix_parts(values, kinds=None, libdocs="", seat="")`・`tdd_parts(values, kinds=None, seat="")` — `seat` が空でなければ節 `("seat", seat, ALWAYS + "（修正の形 g3 の座）")` を、fix は `fix-reply` の直前、tdd は `tdd-remap` の後に置く。`fix_prompt`・`tdd_prompt`・`tdd_render` は `seat=""` を素通し
  - `fixrules.implementer_values(b, values: dict, repo, owed: list[str]) -> dict[str, str]` — 216 の implementer の 5 つの穴の値。
    - `[task name]`: `直す義務の単位 <n> 件（修正案の項目 <番号の並び>）`（項目が無ければ括弧を省く）
    - `[BRIEF_FILE]`: 今の周の作業ファイル `seat-briefs.md`（`planbrief.head_text(planbrief.for_units(planbrief.cut(b), owed))` を書いた物）のパス。brief が無い run は `values["judgment_file"]`
    - `[Scene-setting: where this fits, dependencies, architectural context]`: `seat.SCENE`（「works の修正の段。流れ・機械の関門・commit は線が持つ。TDD の輪で直した単位は輪の要約に在る」）と、`values["summary_file"]` が空でなければそのパス
    - `[directory]`: 対象の根（`repo`）
    - `[REPORT_FILE]`: `seat.NO_REPORT_FILE`（「ファイルに書かない。返答は指示書の『返答の欄』の JSON」）
  - `fixrules.prep`: `shape = fixshape.shape_at(board_dir)`。g3 なら `seat.section("fix", shape, implementer_values(...))` を full と delta の両方の組み立てに渡す（2 回目の修正役 `pass_="ruled"` も同じ）。`ValueError` は捕まえず、支度の script が今の誤りの道（名指して 2）で落ちる
  - `tddloop.prep`: `seat.section("tdd", fixshape.shape_at(盤面))` を `tdd_render(..., seat=…)` に。盤面の無い置き場（`state.json` の 2 つ上に盤面が無い）は `""`

- [ ] **Step 1: 落ちる試験を書く**

```python
# test_seat.py
def test_section_empty_unless_g3(self):
    for shape in ("current", "af", "g1"):
        self.assertEqual(seat.section("tdd", shape), "")
    self.assertEqual(seat.section("rule", "g3"), "")              # 座の無い節

def test_tdd_seat_names_skill_applies_and_overlay(self):
    text = seat.section("tdd", "g3")
    s = spseam.load_seams()["tdd"]
    for w in (seat.HEAD, "Skill", "test-driven-development", *s["applies"], *s["not_applies"], rolekit.skill_overlay().strip()):
        self.assertIn(w, text)

def test_fix_seat_fills_implementer(self):
    values = {p: f"<{i}>" for i, p in enumerate(spseam.load_seams()["implementer"]["placeholders"])}
    text = seat.section("fix", "g3", values)
    self.assertIn("<1>", text)
    self.assertNotRegex(text, r"\[[A-Z][A-Z_]+\]")
    with self.assertRaises(ValueError):
        seat.section("fix", "g3", None)

def test_fix_seat_refuses_broken_pin(self):
    with mock.patch.object(seat.spseam, "fill", side_effect=ValueError("implementer-prompt.md: 中身が固定と違う")):
        with self.assertRaises(ValueError):
            seat.section("fix", "g3", {"[BRIEF_FILE]": "x"})

def test_skill_seats_are_the_fenced_nodes(self):
    seams = spseam.load_seams()
    self.assertTrue(set(seat.SEATS.values()) <= set(seams))
    self.assertEqual({n for n, s in seat.SEATS.items() if seams[s]["use_as"] == "skill"}, fixshape.SKILL_NODES)

def test_yaml_skill_seats_declare_the_skill(self):
    """座の skill の節は YAML で skills: にちょうどそのスキルを持ち、allowed_tools に Skill を持つ。prompt の座の節は skills: を持たない
    （direct の修正役に test-driven-development を宣言しない。事前審査 tdd-skill-on-direct-fix-node）"""
    ...   # blk-fix.yaml の節を id で引く: tdd → skills == ["test-driven-development"]・"Skill" in allowed_tools。fix・fix-ruled → "skills" not in node

# test_fix_rules.py
def test_seat_part_only_when_given(self):
    tdd = [pid for pid, _, _ in fixrules.tdd_parts(tdd_values(), seat="S")]
    self.assertEqual(tdd[tdd.index("tdd-remap") + 1], "seat")
    fix = [pid for pid, _, _ in fixrules.fix_parts(VALUES, seat="S")]
    self.assertEqual(fix[fix.index("fix-reply") - 1], "seat")
    self.assertNotIn("seat", [pid for pid, _, _ in fixrules.fix_parts(VALUES)])

# test_blk_fix_tdd.TestStart（重い段。この 2 本を名指して回す）
def test_g3_tdd_prompt_carries_seat(self): ...    # fixshape.shape_at を "g3" に mock → tddloop.prep の指示書に seat.HEAD と読み替えの頭の行
def test_af_tdd_prompt_has_no_seat(self): ...     # "af" → seat.HEAD が無い
```

`test_sp_skills.OverlayDeliveryCase` の YAML の走査の試験は、期待を `{素材集めの Skill を持つ役} | fixshape.SKILL_NODES` に直し、docstring を「借りたスキルを読める節は、素材集めの道具の表で Skill を持つ役か、座の表（seat.SEATS）の skill の節。前者は material.prep が、後者は修正の支度（fixrules・tddloop の prep）が読み替えを載せる」に直す。

- [ ] **Step 2: 落ちることを確かめる**

Run: `cd works/tests && PYTHONDONTWRITEBYTECODE=1 python3 -m unittest test_seat test_fix_rules test_sp_skills`
Expected: FAIL（`No module named 'seat'`・`tdd_parts() got an unexpected keyword argument 'seat'`）

- [ ] **Step 3: `seat.py` を書き、`fixrules`・`tddloop` に配線し、YAML の節 `tdd` に宣言を足す**（`seat` は `spseam` に item を渡すため、`borrow.json` を `spseam.BORROW_DIR` から読む）

- [ ] **Step 4: 通ることを確かめる**

Run: `cd works/tests && PYTHONDONTWRITEBYTECODE=1 python3 -m unittest test_seat test_fix_rules test_sp_skills test_yaml_rules test_layers test_tiers` と `test_blk_fix_tdd.TestStart`
Expected: PASS（`test_yaml_rules` の skills: の柵は borrow の一覧の内なので通る）

- [ ] **Step 5: Commit**

```bash
git add works/.shared/core/seat.py works/.shared/core/fixshape.py works/blk-fix works/tests/test_seat.py works/tests/test_fix_rules.py works/tests/test_sp_skills.py works/tests/test_blk_fix_tdd.py works/tests/test_layers.py works/tests/tiers.py
git commit -m "feat(works): 修正の形 g3 で TDD の役に test-driven-development の座、修正役に implementer の型の座を載せる（216 の節と読み替えを使う）"
```

---

### Task 3: 形ごとの道具の柵（包みが g3 以外で Skill を、g1 以外で Agent を拒む）

**Files:**
- Modify: `works/.shared/core/fixshape.py`（`AGENT_NODES`・`denied_tools`）
- Modify: `works/.shared/core/adapter.py`（`_with_hook` の柵の段に 1 項、模块の docstring の柵の一覧に 1 項目）
- Modify: `works/tests/test_fixshape.py`・`works/tests/test_adapter.py`（新しい class `ShapeFenceCase`）

**Interfaces:**
- Consumes: Task 1 の `shape_at`、Task 2 の `SKILL_NODES`。包みの `Marker.name`（印の節の名）・`run_place_of` と同じ切符の `board`・`add_deny(doc, rules) -> int`
- Produces:
  - `fixshape.AGENT_NODES = frozenset({"fix", "fix-ruled"})`（Task 7 で YAML に Agent を足す節。先に拒む）
  - `fixshape.denied_tools(shape: str, node: str) -> tuple[str, ...]` — `node in SKILL_NODES and shape != "g3"` なら `"Skill"`、`node in AGENT_NODES and shape != "g1"` なら `"Agent"`（この順）
  - 包み: 切符が在り、印の名が在る起動で、`denied_tools(shape_at(<切符の board>), <印の名>)` が空でなければ `permissions.deny` に足し、`fence["shape_deny"]` に足した数を残す。`shape_at` の `ValueError` は起動を拒む（壊れた切符と同じ道。理由に `fix_shape` を含める）

- [ ] **Step 1: 落ちる試験を書く**

```python
# test_fixshape.py
def test_denied_tools_table(self):
    rows = {("g3", "tdd"): (), ("af", "tdd"): ("Skill",), ("current", "tdd"): ("Skill",), ("g1", "tdd"): ("Skill",),
            ("g1", "fix"): (), ("g1", "fix-ruled"): (), ("g3", "fix"): ("Agent",), ("af", "fix-ruled"): ("Agent",),
            ("af", "judge"): (), ("g3", "local-review"): ()}
    for (shape, node), want in rows.items():
        self.assertEqual(fixshape.denied_tools(shape, node), want, (shape, node))

# test_adapter.ShapeFenceCase（重い段。この class を名指して回す。既存の切符つきの起動の helper を使う）
def test_fence_denies_by_shape(self): ...     # 盤面の r1/start.json が af・印 tdd の起動 → 子に渡る --settings の permissions.deny に "Skill"・記録の fence.shape_deny == 1。g3 → "Skill" が無い
def test_no_record_means_af(self): ...        # start.json が無い盤面 → af と同じ（印 tdd で "Skill"、印 fix で "Agent" を拒む）
def test_choice_file_steers_fence(self): ...  # start.json が af でも fixshape.choose で g3 → 印 tdd で "Skill" を拒まない
def test_broken_shape_refuses_launch(self): ...   # start.json の fix_shape が "x" → 子を起こさず、理由に fix_shape
def test_no_ticket_unchanged(self): ...       # 切符の無い起動は今どおり（shape_deny の鍵が無い）
```

- [ ] **Step 2: 落ちることを確かめる**

Run: `cd works/tests && PYTHONDONTWRITEBYTECODE=1 python3 -m unittest test_fixshape test_adapter.ShapeFenceCase`
Expected: FAIL（`denied_tools` が無い・deny に Skill が無い）

- [ ] **Step 3: 柵を書く**（包みは L2 なので、L2 の `fixshape` を import するだけ。ほかの柵の順と記録の形は変えない）

- [ ] **Step 4: 通ることを確かめる**

Run: Step 2 と同じ ＋ `test_layers`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add works/.shared/core/fixshape.py works/.shared/core/adapter.py works/tests/test_fixshape.py works/tests/test_adapter.py
git commit -m "feat(works): 包みが盤面の修正の形を読み、g3 以外の座の節の Skill と g1 以外の修正役の Agent を permissions.deny で拒む"
```

---

### Task 4: 事後の関門の束（`fixgates`。受け入れのテストの赤→緑と既存テストの変更を、全部の腕で修正の受け付けに当てる）

**Files:**
- Create: `works/blk-fix/lib/fixgates.py`
- Create: `works/tests/test_fix_gates.py`（HEAVY。種の git `linekit.seed_repo` と盤面）
- Modify: `works/blk-fix/scripts/accept.py`（`INPUTS` に `INPUTS_TDD_SUITE`（無くてよい）、`accept_fix` の最後の段、docstring の段の一覧）
- Modify: `works/blk-fix/lib/tddloop.py`（公開の別名 `unnamed_edits = _unnamed_edits` の 1 行と注記）
- Modify: `works/blk-fix/blk-fix.yaml`（節 `fix-accept`・`fix-ruled-accept` の `with` に `tdd_suite: $INPUTS.tdd_suite`）
- Modify: `works/tests/test_blk_fix_tdd.py`（`TestYaml.test_script_inputs` の表）・`works/tests/tiers.py`

**Interfaces:**
- Consumes: 219 の `tddloop.run_suite(exe, repo, work, n, args=())`（結末の行に `fail_type`・`fail_message`）・`tddloop.red_kind(case) -> str`・`tddloop.KIND_UNKNOWN`・`tddloop.test_functions(src, path)`・`tddloop._unnamed_edits(repo, tree, files, allowed)`・`tddloop._abs_ids`・`tddloop._function_span`、217 の `planmarks.frozen(b)`（項目の欄。`tests[].id`・`red_kind`・`route`）・`planmarks.rewrites(b)`・`conflict.ruled_test_limits(b)`・`conflict.parse_limit`、Task 1 の `fixshape.shape_at`・`plain`
- Produces（`fixgates`）:
  - `LEDGER = "fix-gates.json"`（今の周の作業ファイル `{"rows": [{attempt, shape, gate, id, detail}], "skipped": [{attempt, why}]}`。受け付けの回ごとに積む）
  - `GATES = ("red_green", "test_edits")`
  - `NO_SUITE = "テストの実行器（入力 tdd_suite）が無い run——受け入れのテストの事後の赤緑は確かめない"`
  - `REJECT = "修正の後の木に、輪の中の関門が通さない物が在る（事後の関門の束）: "`
  - `problems(board_dir, repo, base_rev: str, suite: str, attempt: int) -> list[dict]` — 行 `{gate, id, detail}`。行と飛ばした理由を LEDGER に積む。
    - red_green: 平の run でなく、修正案の欄が在る時だけ。route が tdd の項目の `tests[].id` ごとに確かめる。今の木で一式を走らせて緑（`passed`）。base の木（一時の `git worktree add --detach`。今の木のテストのファイルだけを写す）で `failure` かつ `red_kind` が案の値と同じ（`unknown` は通す）。外れれば行で、detail は「base で緑」「base で <種類>（案は <種類>）」「今の木で <結末>」のどれか。実行器が無ければ `skipped` に NO_SUITE
    - test_edits: base から今の木で変わった `.py` のうち、base に在ったテストの関数の源が変わった・消えた物。許すのは `planmarks.rewrites(b)` の id（平の run では無し）と、`conflict.ruled_test_limits(b)` の範囲を含む関数。外れの id ごとに行
    - 一時の worktree は成否に関わらず消す
  - `reject_text(rows: list[dict]) -> str` — REJECT と、行ごとの `<gate> <id>: <detail>`
  - `accept_fix`: 今の確かめが全部通った後に `fixgates.problems(board, repo, base_rev, os.environ.get("INPUTS_TDD_SUITE", ""), int(INPUTS_ITERATION))`。行が在れば今の拒否の道（理由のファイル・3 回目で諦め）で `reject_text` を返す

- [ ] **Step 1: 落ちる試験を書く**（種のリポジトリの `stats.mean` は len-1 で割る誤りを持つ。欄の形は 217 の `test_plan_brief.FIELDS` と同じ）

```python
class FixGatesCase(tbf.BoardCase):
    def test_real_red_green_passes(self):
        b = self.ready_with_fields()                  # 項目 1: tdd・tests=[test_mean_of_two（red_kind assertion）]
        self.add_test_mean_of_two(); self.edit_tree(MEAN_FIX)
        self.assertEqual(fixgates.problems(self.board, self.repo, self.base, SUITE, 1), [])

    def test_test_green_at_base_is_a_miss(self):
        b = self.ready_with_fields()
        self.add_test_that_passes_on_base("test_mean_of_two")
        rows = fixgates.problems(self.board, self.repo, self.base, SUITE, 1)
        self.assertEqual([(r["gate"], r["id"]) for r in rows], [("red_green", "test_stats.py::TestStats::test_mean_of_two")])
        self.assertIn("base で緑", rows[0]["detail"])

    def test_wrong_red_kind_is_a_miss(self): ...         # 新しいテストが base で NameError → detail に "NameError" と "assertion"
    def test_unnamed_existing_edit_is_a_miss(self): ...  # test_mean_of_three の期待を書き換える → ("test_edits", その id)
    def test_named_rewrite_and_ruled_limit_pass(self): ...   # 同じ書き換えを rewrite_tests に名指す → []。裁定の範囲 test_stats.py:8 → []
    def test_no_suite_skips_and_records(self):
        b = self.ready_with_fields(); self.add_test_that_passes_on_base("test_mean_of_two")
        self.assertEqual([r for r in fixgates.problems(self.board, self.repo, self.base, "", 1) if r["gate"] == "red_green"], [])
        led = json.loads(entry.open_board(self.board).work(fixgates.LEDGER).read_text(encoding="utf-8"))
        self.assertEqual(led["skipped"][0]["why"], fixgates.NO_SUITE)

    def test_plain_run_ignores_plan_fields(self): ...    # start.json の fix_shape=current → base で緑のテストでも red_green の行が無い
    def test_worktree_removed_after(self): ...           # problems の後 git worktree list が 1 行

    def test_accept_rejects_with_battery_last(self): ...  # accept.py を spec_from_file_location で読み、fixgates.problems を行を返す mock にして accept_fix → ok False・理由が REJECT で始まる。ほかの確かめが拒む時は problems を呼ばない
```

- [ ] **Step 2: 落ちることを確かめる**

Run: `cd works/tests && PYTHONDONTWRITEBYTECODE=1 python3 -m unittest test_fix_gates`
Expected: FAIL（`No module named 'fixgates'`）

- [ ] **Step 3: `fixgates.py` を書き、受け付けと YAML を配線する**（`test_functions`・`_unnamed_edits` の読みを新しく作らない。裁定の範囲を含む関数は `tddloop._function_span` と同じ読み）

- [ ] **Step 4: 通ることを確かめる**

Run: `cd works/tests && PYTHONDONTWRITEBYTECODE=1 python3 -m unittest test_fix_gates test_blk_fix_tdd.TestYaml test_layers test_tiers`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add works/blk-fix works/tests/test_fix_gates.py works/tests/test_blk_fix_tdd.py works/tests/tiers.py
git commit -m "feat(works): 修正の受け付けで、受け入れのテストの赤→緑と名指しの外の既存テストの変更を base からの差分に事後にもう 1 度当てる（全部の腕で同じ関門）"
```

---

### Task 5: 固定材料（h-fix で盤面を写し、入力 `fix_fixture` で次の run が同じ所から始める）

**Files:**
- Create: `works/.shared/core/fixture.py`
- Create: `works/tests/test_fixture.py`（HEAVY。種の git と盤面）
- Modify: `works/.shared/core/entry.py`（`check_inputs` に `fix_fixture`、`start` の分かれ）
- Modify: `works/darkfactory/lib/line_edge.py`（境 fix の go の後に写す 1 段）
- Modify: `works/darkfactory/darkfactory.yaml`（入力 `fix_fixture`・start の `with`）・`works/darkfactory/scripts/start.py`（`INPUTS`・`OPTIONAL`）・`works/tests/linekit.py`・`works/tests/test_line.py`
- Modify: `works/dev/dogfood.sh`（env `WORKS_FIX_FIXTURE`）・`works/tests/test_dev.py`
- Modify: `works/tests/test_line_a.py`（線を 2 回通す 1 本）・`works/tests/test_layers.py`（`"fixture": (3, None)`）・`works/tests/tiers.py`

**Interfaces:**
- Consumes: `entry.START_FILE`・`ticket.write`・`script_io.BOARD_DIR`、Task 1 の `fixshape.CHOICE_REL`。盤面を開いた時の `state.graph_sha` の照合（`entry.open_board` が既に持つ）
- Produces（`fixture`。`entry`・`board` を import しない）:
  - `DIR = "fix-fixture"`（`$ARTIFACTS_DIR` の下。盤面の隣）・`MANIFEST = "fixture.json"`・`TRACE_OP = "fixture_adopted"`・`class FixtureRefused(Exception)`
  - `capture(board_dir, repo, *, run_id: str, pack_root) -> dict` — 盤面を `<board_dir の親>/DIR/board/` へ丸ごと写し、写しの横に MANIFEST `{source_run, head, tree, board_root, repo_root, pack_root, request_sha256, test_cmd, files: {相対パス: sha256}}` を書いて返す（`head`・`tree` は `git rev-parse HEAD`・`HEAD^{tree}`、`request_sha256` は盤面の依頼の文の sha256、`test_cmd` は start の控え）。時刻を書かない。既に在れば書き直さない
  - `adopt(board_dir, src, repo, *, run_id: str, pack_root, request_text: str, test_cmd: str, fix_shape: str) -> dict` — 拒む（`FixtureRefused`。理由は 1 行で何が違うかを名指す）: MANIFEST が無い・読めない／ファイルの sha256 が違う・足りない・多い／`board_dir` が空でない／今の `HEAD^{tree}` が `tree` と違う／作業ツリーに変更が在る／`request_text` の sha256 が違う／`test_cmd` が違う。通れば次をして、`r1/start.json` の doc を返す。
    - 写しを `board_dir` へ写す。
    - UTF-8 で読めるファイルの中の `board_root`・`repo_root`・`pack_root`・`head` を新しい値に置き換える。
    - 写しに `fixshape.CHOICE_REL` が在れば消す（腕の形は今の入力で決める）。
    - `r1/start.json` の `run_id` と `fix_shape` を今の値にし、鍵 `fixture: {source_run, manifest_sha256}` を足す。
  - `entry.check_inputs` の返りに `"fix_fixture"`（空か、在るフォルダの絶対パス。相対なら対象の根から。無ければ `InputRefused`）
  - `entry.start`: `fix_fixture` が在れば、`DiskBoard.begin`・`_drain` の代わりに次の順で進める。返りは今と同じ形の `out`（`ci_role_go` は False・`pr_go` は控えの値）。
    1. `fixture.adopt`（`FixtureRefused` は `InputRefused`）。
    2. `entry.open_board`（graph_sha が違えば `InputRefused`:「固定材料と works の版が違う」）。
    3. 盤面の trace に TRACE_OP。
    4. `ticket.write`。
  - `line_edge.edge`（at fix）: `go` が真・周が 1・start の控えに `fixture` が無い時だけ `fixture.capture`。`OSError` は盤面の trace に `fixture_capture_failed` を 1 行残して続ける（run を止めない）
  - `dogfood.sh`: `WORKS_FIX_FIXTURE` が空でなければ在るフォルダか確かめ（無ければ 2）、`--input fix_fixture=<絶対パス>`

- [ ] **Step 1: 落ちる試験を書く**

```python
class FixtureCase(tbf.BoardCase):
    def test_capture_then_adopt_elsewhere_rewrites_roots(self):
        self.fix_ready()                                       # 盤面が p3.fix を待つ所まで
        man = fixture.capture(self.board, self.repo, run_id="run-1", pack_root=PACK)
        other_repo = self.clone_same_tree()                    # 同じ木で別の置き場・別の commit
        new_board = self.tmp / "b2" / "board"
        doc = fixture.adopt(new_board, self.board.parent / fixture.DIR, other_repo, run_id="run-2", pack_root=PACK,
                            request_text=REQUEST_TEXT, test_cmd="", fix_shape="af")
        self.assertEqual((doc["run_id"], doc["fix_shape"], doc["fixture"]["source_run"]), ("run-2", "af", "run-1"))
        texts = [p.read_text(encoding="utf-8", errors="ignore") for p in new_board.rglob("*") if p.is_file()]
        for old in (str(self.board), str(self.repo), man["head"]):
            self.assertFalse(any(old in t for t in texts), old)
        self.assertIn("p3.fix", entry.open_board(new_board).ready())

    def test_adopt_drops_router_choice(self): ...        # 写す前の盤面に fixshape.choose(..., "g1") → 取り込んだ盤面の shape_at は今の入力 af
    def test_adopt_refuses_other_tree(self): ...         # 種の木にファイルを 1 つ足して commit → FixtureRefused（"tree"）
    def test_adopt_refuses_dirty_tree(self): ...         # 手元に変更 → FixtureRefused
    def test_adopt_refuses_edited_copy(self): ...        # 写しの state.json を書き換え → FixtureRefused（そのパス）
    def test_adopt_refuses_other_request_or_test_cmd(self): ...
    def test_adopt_refuses_non_empty_board(self): ...
    def test_capture_once(self): ...                     # 2 度目の capture は manifest を書き直さない

# test_line_a.py
def test_fixture_run_starts_at_fix(self):
    """1 回目の線の h-fix が固定材料を写し、2 回目の線（fix_fixture・fix_shape=af）は判定・修正案の役を起こさずに修正へ進む"""
    first = self.run_line(replies=clean_replies())
    src = first.artifacts / fixture.DIR
    second = self.run_line(replies=fix_only_replies(), inputs={"fix_fixture": str(src), "fix_shape": "af"})
    self.assertNotIn("judge", second.roles_called); self.assertNotIn("plan", second.roles_called)
    self.assertIn("fix", second.roles_called)
```

（`run_line` の返りの名は `linekit` の今の物に合わせる。役を呼んだ記録が無ければ、stub の消費の記録から引く）

- [ ] **Step 2: 落ちることを確かめる**

Run: `cd works/tests && PYTHONDONTWRITEBYTECODE=1 python3 -m unittest test_fixture`（と `test_line_a` の上の 1 本を、既存の class の名で名指す）
Expected: FAIL（`No module named 'fixture'`）

- [ ] **Step 3: `fixture.py` を書き、start と境の節と殻を配線する**

- [ ] **Step 4: 通ることを確かめる**

Run: Step 2 と同じ ＋ `test_line_inputs test_line_wiring test_layers test_tiers`、`python3 -m py_compile works/tests/test_dev.py works/tests/test_line.py`、`sh -n works/dev/dogfood.sh`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add works/.shared/core/fixture.py works/.shared/core/entry.py works/darkfactory works/dev/dogfood.sh works/tests/test_fixture.py works/tests/test_line_a.py works/tests/test_line.py works/tests/linekit.py works/tests/test_dev.py works/tests/test_layers.py works/tests/tiers.py
git commit -m "feat(works): h-fix の盤面を固定材料に写し、入力 fix_fixture で同じ木・同じ依頼の run を判定と修正案を作り直さずに修正から始める"
```

---

### Task 6: current の腕（修正案の欄を修正の段に渡さない・整えはいつも・test_cmd の関門を切る）

**Files:**
- Modify: `works/blk-fix/lib/planbrief.py`（`cut` の頭の 1 行）
- Modify: `works/blk-fix/lib/tddloop.py`（`plan_contract` の頭の 1 行・`_fix` の整えの条件の 1 項・`start` の test_cmd の関門の 1 分岐）
- Modify: `works/tests/test_plan_brief.py`・`works/tests/test_blk_fix_tdd.py`（新しい class `TestPlainShape(LoopCase)`）

**Interfaces:**
- Consumes: Task 1 の `fixshape.plain`。219 の `plan_contract`・`_fix`・`GATE_OFF`・`st["test_cmd_note"]`
- Produces:
  - `planbrief.cut(b)`: `fixshape.plain(b.dir)` なら `[]`（LEDGER を書かない）
  - `tddloop.plan_contract`: 平の run なら `{}`
  - `tddloop._fix`: 平の run なら申告に関わらず refactor へ進む（219 の前の振る舞い）
  - `tddloop.start`: 平の run なら `GATE_OFF`、`test_cmd_note = PLAIN_NOTE = "修正の形 current——test_cmd の関門は回さない（比べの基準）"`
  - 束（Task 4）は既に平の run の欄を見ない

- [ ] **Step 1: 落ちる試験を書く**

```python
class TestPlainShape(LoopCase):
    def setUp(self):
        super().setUp(); self.shape("current")            # 盤面の r1/start.json に fix_shape=current
    def test_no_contract_and_always_refactor(self):
        self.route(); self.red(); self.fix_mean()          # 申告なし
        self.assertEqual(self.st()["phase"], "refactor")
        self.assertEqual(self.st()["contract"], {})
    def test_test_cmd_gate_off_with_note(self): ...        # start(test_cmd="false") → test_cmd_gate == GATE_OFF・note == PLAIN_NOTE

# test_plan_brief.BriefCase
def test_plain_shape_cuts_no_brief(self): ...              # 欄を置いても current なら cut(b) == [] で LEDGER が無い
```

- [ ] **Step 2: 落ちることを確かめる**

Run: `cd works/tests && PYTHONDONTWRITEBYTECODE=1 python3 -m unittest test_blk_fix_tdd.TestPlainShape test_plan_brief.BriefCase.test_plain_shape_cuts_no_brief`
Expected: FAIL

- [ ] **Step 3: 4 つの切り替えを書く**（どれも `fixshape.plain` の 1 か所の読み。ほかの腕の振る舞いは変えない）

- [ ] **Step 4: 通ることを確かめる**

Run: Step 2 と同じ ＋ `test_blk_fix_tdd.TestRefactorGate test_blk_fix_tdd.TestTestCmdGate`（219 の試験が af で今どおり）
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add works/blk-fix/lib/planbrief.py works/blk-fix/lib/tddloop.py works/tests/test_plan_brief.py works/tests/test_blk_fix_tdd.py
git commit -m "feat(works): 修正の形 current では修正案の欄を修正の段に渡さず、整えをいつも回し、test_cmd の関門を切る（比べの基準）"
```

---

### Task 7: g1 の腕（TDD の輪を飛ばし、修正役が SDD の型で下請けを回す）

**Files:**
- Modify: `works/.shared/core/seat.py`（`G1_HEAD`・`G1_REPORT`・`G1_HEAD_SHA`・`G1_DIFF`・`g1_section`）
- Modify: `works/blk-fix/lib/fixrules.py`（`g1_values`、`prep` の g1 の分かれ）
- Modify: `works/blk-fix/lib/tddloop.py`（`start` の頭の g1 の分かれ、`G1_NO_LOOP`）
- Modify: `works/blk-fix/blk-fix.yaml`（節 `fix`・`fix-ruled` の `allowed_tools` に `Agent`、注記 1 行）
- Modify: `works/tests/test_seat.py`・`works/tests/test_blk_fix.py`（`TestFixPrep` に 1 本）・`works/tests/test_blk_fix_tdd.py`（`TestStart` に 1 本）

**Interfaces:**
- Consumes: Task 2 の `seat`・`implementer_values`、Task 3 の柵（g1 の run だけ Agent が通る）、Task 4 の束（g1 の赤緑と凍結を受け持つ外側の関門）、216 の `spseam.fill("implementer", …)`・`spseam.fill("task-review", …)`、217 の `planbrief.cut`・`for_units`
- Produces:
  - `tddloop.G1_NO_LOOP = "修正の形 g1——TDD の輪は回さない（修正役が下請けを回し、赤緑と凍結は修正の受け付けの束が事後に確かめる）"`。`start` は形が g1 なら何も書かずに `{"go": False, "reason": G1_NO_LOOP, ...}`（実行器の無い run と同じ出口の形）
  - `fixrules.g1_values(b, values: dict, repo, owed: list[str], base_rev: str) -> list[dict]` — brief の項目ごとに今の周の作業ファイルを 2 つ書き、`{item, impl_file, review_file}` の並びを返す。brief の無い run は判定の単位を 1 項目とみなし、`[BRIEF_FILE]` を判定のファイルにする。
    - `g1-impl-<n>.md`: `spseam.fill("implementer", …)`。`[BRIEF_FILE]` はその項目の brief、ほかは `implementer_values` と同じ。
    - `g1-review-<n>.md`: `spseam.fill("task-review", …)`。`[BRIEF_FILE]` は同じ brief、`[GLOBAL_CONSTRAINTS]` は人の方針の文書のパスか `（無し）`、`[REPORT_FILE]` は `seat.G1_REPORT`（「実装役の最後のメッセージを、この型の後ろに貼る」）、`[BASE_SHA]` は base_rev、`[HEAD_SHA]` は `seat.G1_HEAD_SHA`（「審査を起こす直前の git rev-parse HEAD」）、`[DIFF_FILE]` は `seat.G1_DIFF`（「審査を起こす前に git diff <BASE_SHA> を $TMPDIR/works-g1-<n>.patch に書いたパス」）。
  - `seat.G1_HEAD = "## 下請けを回す（修正の形 g1）"`・`seat.g1_section(rows: list[dict]) -> str` — 見出しの下に次を書き、項目ごとの 2 ファイルを並べ、最後に `rolekit.skill_overlay()`:
    1. 項目の順に、Agent で下請けを 1 つ起こし、prompt に `impl_file` の中身を全部渡す。
    2. 下請けの最後のメッセージを受けたら、別の Agent で審査役を起こし、`review_file` の中身とその報告を渡す。
    3. 審査が `❌` か `Needs fixes` なら、指摘を添えて同じ項目の実装役を起こし直す。項目ごとに 3 回まで。
    4. 全部の項目が済んだら、自分は返答の欄の JSON だけを返す。
    5. 機械の関門（赤緑・凍結・test_cmd）は返答の後に線が当てる。下請けの「commit」「人に聞く」は読み替えに従う。
  - `fixrules.prep`: 形が g1 なら `seat.g1_section(g1_values(...))` を座の節として渡す（g3 の implementer の座の代わり）

- [ ] **Step 1: 落ちる試験を書く**

```python
# test_seat.py
def test_g1_section_lists_files_and_overlay(self):
    rows = [{"item": 1, "impl_file": "/b/r1/g1-impl-1.md", "review_file": "/b/r1/g1-review-1.md"}]
    text = seat.g1_section(rows)
    for w in (seat.G1_HEAD, "Agent", "/b/r1/g1-impl-1.md", "/b/r1/g1-review-1.md", rolekit.skill_overlay().strip()):
        self.assertIn(w, text)

# test_blk_fix.TestFixPrep（重い段。この 1 本を名指して回す）
def test_g1_prep_writes_filled_parts_per_item(self): ...   # fix_shape=g1・修正案の欄あり → g1-impl-1.md・g1-review-1.md が在り、どちらも [A-Z_]+ の穴が残らず、指示書に seat.G1_HEAD

# test_blk_fix_tdd.TestStart
def test_g1_skips_loop(self): ...                          # fix_shape=g1・実行器あり → go False・reason == G1_NO_LOOP・state_file ""
```

`test_seat.test_yaml_skill_seats_declare_the_skill` に「節 `fix`・`fix-ruled` の allowed_tools に Agent が在り、その節の名の集合が `fixshape.AGENT_NODES` と同じ」を足す。

- [ ] **Step 2: 落ちることを確かめる**

Run: `cd works/tests && PYTHONDONTWRITEBYTECODE=1 python3 -m unittest test_seat test_blk_fix_tdd.TestStart.test_g1_skips_loop test_blk_fix.TestFixPrep.test_g1_prep_writes_filled_parts_per_item`
Expected: FAIL

- [ ] **Step 3: g1 の分かれを書く**

- [ ] **Step 4: 通ることを確かめる**

Run: Step 2 と同じ ＋ `test_yaml_rules test_tool_parity`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add works/.shared/core/seat.py works/blk-fix works/tests/test_seat.py works/tests/test_blk_fix.py works/tests/test_blk_fix_tdd.py
git commit -m "feat(works): 修正の形 g1 では TDD の輪を飛ばし、修正役が SDD の実装役と審査役の型で項目ごとに下請けを回す（関門は修正の受け付けの束）"
```

---

### Task 8: 測る関数と採否の判定（`dev/fixmeasure.py`）

**Files:**
- Create: `works/dev/fixmeasure.py`
- Create: `works/tests/test_fixmeasure.py`（FAST。一時の置き場に sqlite の偽の archon.db と偽の盤面を作る）
- Modify: `works/tests/tiers.py`・`works/CHANGELOG.md`

**Interfaces:**
- Consumes:
  - archon.db: 表 `remote_agent_workflow_runs`（`id`・`status`）と `remote_agent_workflow_events`。後者は `event_type` が `node_completed` の行の `data.timing.durationMs`・`data.spend.costUsd.value`、`tool_called` の行の `data.tool_name`、どちらも `step_name`。
  - 盤面: `fixshape.shape_at`、start の控えの `fixture`、`planmarks.frozen`、各周の `role-rejects.json`（`rolekit.REJECTS_NAME`）、`tdd-*/state.json`（219 の `units`・`calls`）、`conflict.items`、`fixgates.LEDGER`、`planbrief.LEDGER`、差分の審査の出力（`p3.delta_review` の faces）、手直しの周（`p3.delta_fix` の出力の数）。
- Produces（読むだけ。何も書かない。網に出ない）:
  - `FIX_STAGE = ("fixing__", "reviewing__", "refixing__")`・`MIN_FIXTURES = 3`・`COST_MARGIN = 1.10`・`G1_MARGIN = 0.90`
  - `row(db: pathlib.Path, run_id: str, board: pathlib.Path) -> dict` — 1 run の行:
    - `run_id`・`shape`・`fixture`（`source_run` か `""`）・`complete: bool`・`items`（欄の項目の数。欄が無ければ直す義務の単位の数）
    - `redo`: `{fix_rejects, tdd_rejects, battery_rejects, delta_faces, refix_rounds}` と `redo_total`
      - fix_rejects は p3.fix の拒否の行、tdd_rejects は 219 の `calls` の `ok: false` の行、battery_rejects は束の行の在る受け付けの回、delta_faces は差分の審査が受け付けた穴、refix_rounds は手直しの往復
    - `cost_usd: {fix_stage, fixing}`（FIX_STAGE の頭の節の費用の和と、`fixing__` だけの和）
    - `secs: {step_name: 秒}`（FIX_STAGE の頭の AI の節。秒は小数 1 桁）
    - `rulings: {裁定の語: 件}`・`divergences: {種類: 件}`（211 の前は種類の無い申し出を `"unkinded"` に数える）
    - `gate_misses`（束の行の数）
    - `record_gaps: list[str]`（例: tdd の節の `node_completed` の数と `calls` の行の数が違う・tdd の項目の単位に輪の単位の行が無い・平の run でないのに修正案の欄が在って brief の控えが無い・start の控えに `fix_shape` が無い）
    - `contamination: {"Skill": 件, "Agent": 件}`（FIX_STAGE の節の `tool_called` のうち、その形で拒む道具。`fixshape.denied_tools` と同じ表で、`step_name` の最後の区切りを印の節の名として見る）
    - `red_green_checked: bool`（束の `skipped` に NO_SUITE が無い）
  - `maintenance(root: pathlib.Path) -> dict[str, int]` — 腕ごとの、その腕で読む文の行の数。
    - own: 修正の工程の works の決まりのファイル（`blk-fix/rules/*.md`・`blk-delta/commands/delta-review.md`・`blk-refix/rules/*.md`）。current と af は own。
    - g3: own と、座の節の `seams.json` の項目と `unattended.md` の行。
    - g1: own と、implementer・task-review の部品と `seat.G1_HEAD` の節の行。
  - `verdict(rows: list[dict]) -> dict` — 上の「採否の決まり」のとおり。返り `{"decision": "keep_g3" | "switch_to_af" | "fix_gates_first" | "incomplete", "missing": [[腕, 固定材料]], "invalid": [[run_id, 理由]], "per_item": {腕: {redo, cost}}, "misses": {腕: 件}, "import_from_g1": [指標], "vs_current": {指標: 差}, "report_only": {...}}`
  - CLI: `python3 works/dev/fixmeasure.py row <archon.db> <run_id> <盤面>`（JSON の 1 行）・`verdict <行の jsonl>`（JSON）・`maintenance`（JSON）。誤りは 2、ほかは 0

- [ ] **Step 1: 落ちる試験を書く**

```python
def rows4(fixtures=("f1", "f2", "f3"), over=None):
    """各腕・各固定材料の有効な行（items 2・抜け 0・欠け 0・混ざり 0）。over[(腕, 材料)] の辞書で欄を上書き"""
    ...

def test_row_reads_cost_time_tools_from_events(self):
    db = make_db(self.tmp, run="r1", events=[node("fixing__fix-loop.fix", ms=1500, usd=0.4),
                                             node("reviewing__delta-loop.review", ms=500, usd=0.1),
                                             node("judging__judge-loop.judge", ms=900, usd=9.0),
                                             tool("fixing__tdd-loop.tdd", "Skill")])
    board = make_board(self.tmp, shape="af", items=2)
    r = fixmeasure.row(db, "r1", board)
    self.assertEqual(r["cost_usd"], {"fix_stage": 0.5, "fixing": 0.4})
    self.assertEqual(r["secs"]["fixing__fix-loop.fix"], 1.5)
    self.assertEqual(r["contamination"], {"Skill": 1, "Agent": 0})   # af で Skill

def test_row_counts_redo_rulings_misses_and_gaps(self): ...   # 拒否 2・束の行 1・裁定 fix_test_scope 1・calls と出来事の数の食い違い → 各欄
def test_row_without_shape_record_is_a_gap(self): ...

def test_verdict_keeps_g3_when_not_worse(self):
    self.assertEqual(fixmeasure.verdict(rows4())["decision"], "keep_g3")

def test_verdict_cost_margin(self):
    fs = ("f1", "f2", "f3")
    af = {("af", f): {"cost_usd": {"fix_stage": 1.0, "fixing": 1.0}} for f in fs}
    over = {**af, **{("g3", f): {"cost_usd": {"fix_stage": 1.11, "fixing": 1.0}} for f in fs}}
    self.assertEqual(fixmeasure.verdict(rows4(over=over))["decision"], "switch_to_af")
    at = {**af, **{("g3", f): {"cost_usd": {"fix_stage": 1.10, "fixing": 1.0}} for f in fs}}
    self.assertEqual(fixmeasure.verdict(rows4(over=at))["decision"], "keep_g3")

def test_verdict_one_miss_rejects_g3(self): ...           # g3 の 1 行に gate_misses 1 → switch_to_af
def test_verdict_both_missing_means_fix_gates_first(self): ...
def test_verdict_g1_never_default_but_named_for_import(self): ...   # g1 が作り直し最少・抜け 0 → decision は g3 か af のまま、import_from_g1 == ["redo_per_item"]
def test_verdict_g1_with_miss_not_imported(self): ...
def test_contamination_invalidates_row(self): ...         # 混ざり 1 の行 → invalid に名指し、その組が missing、decision == "incomplete"
def test_verdict_rows_without_red_green_are_incomplete(self): ...
def test_verdict_needs_three_fixtures(self): ...          # 2 件 → incomplete
def test_vs_current_is_report_only(self): ...             # current の作り直しが最少でも decision は変わらない

def test_maintenance_counts_lines_per_arm(self):
    m = fixmeasure.maintenance(ROOT)
    self.assertEqual(m["current"], m["af"])
    self.assertGreater(m["g3"], m["af"]); self.assertGreater(m["g1"], m["af"])

def test_cli_writes_nothing(self): ...                    # row・verdict の後、置き場のファイルのバイトが同じ
```

- [ ] **Step 2: 落ちることを確かめる**

Run: `cd works/tests && PYTHONDONTWRITEBYTECODE=1 python3 -m unittest test_fixmeasure`
Expected: FAIL（`No module named 'fixmeasure'`）

- [ ] **Step 3: `fixmeasure.py` を書く**（sqlite は `file:<path>?mode=ro` の URI で開く。盤面は `entry.open_board(…, allow_halted=True)` で読み、開けなければ `record_gaps` に名指す。同じ入力なら同じ出力: 時刻を入れない・辞書は書いた順）

- [ ] **Step 4: 通ることを確かめる**

Run: `cd works/tests && PYTHONDONTWRITEBYTECODE=1 python3 -m unittest test_fixmeasure test_tiers`
Expected: PASS

- [ ] **Step 5: CHANGELOG を書く**

`[Unreleased]` に `### Added` を 1 項目（次の 6 点）と、`### Changed` を 1 項目（既定の run は g3 で、前の版の盤面は af として動くこと。本流 graphloops は変えていないこと）。
- 線の入力 `fix_shape`（current・af・g3・g1。既定 g3）で修正の工程の形を切り替えること。
- g3 は TDD の役に superpowers の test-driven-development を、修正役に SDD の実装役の型を、216 の節と読み替えで包んで載せること。g1 は修正役が SDD の型で下請けを回すこと。
- 包みが形に合わない Skill・Agent を拒むこと。
- 修正の受け付けで、受け入れのテストの赤→緑と名指しの外の既存テストの変更を、全部の腕で事後にもう 1 度当てること。
- h-fix の盤面を固定材料に写し、入力 `fix_fixture` で同じ所から始めること。
- `dev/fixmeasure.py` が腕ごとの作り直し・費用・時間・裁定・抜け・欠け・保守量を数え、計画に固定した採否の決まりで判定すること。

- [ ] **Step 6: 速い段の全部とルートの柵を回す**

Run: `WORKS_TESTS=fast nice -n 19 sh works/tests/run.sh` と `sh ~/.cache/works-dogfood/rootfences.sh`
Expected: 失敗 0（最後の要約の行が OK）・柵は何も出さずに 0

- [ ] **Step 7: Commit**

```bash
git add works/dev/fixmeasure.py works/tests/test_fixmeasure.py works/tests/tiers.py works/CHANGELOG.md
git commit -m "feat(works): 修正の形の腕ごとに作り直し・費用・時間・裁定・抜け・欠け・保守量を数え、試しの前に決めた採否の決まりで判定する dev/fixmeasure.py"
```

ここまでが 216・219 の取り込みの後に出せる組。218・211 を待たない。

---

### Task 9: 218 の後: 差分の審査の座（task-review の型）・手直しの役の座（receiving-code-review）・current の外れの検査を切る

**前提:** 218 が取り込まれている。この Task の最初に 218 の計画と実装から次の 3 つの名を引き、下の `<218: …>` を置き換える。
- 差分の審査の返答の 2 判定の欄と語（準拠・品質）。
- 外れの機械の検査が修正の受け付けで呼ばれる 1 か所。
- 品質が落ちた時に手直しへ渡る道。

**Files:**
- Modify: `works/.shared/core/seat.py`（`SEATS` に `review`・`review2`（task-review）と `refix`・`refix2`（receiving-review）、`VERDICT_WORDS`、`words_table`）
- Modify: `works/.shared/core/fixshape.py`（`SKILL_NODES` に `refix`・`refix2`）
- Modify: `works/.shared/core/refix.py`（`cut`: 形が g3 なら `review<n>-seat.md` を書き、brief の辞書に `seat_file`。g3 でなければ `seat_file: ""`）
- Modify: `works/blk-delta/commands/delta-review.md`（1 行: brief の `seat_file` が空でなければ Read で全部読み、その型の手順で審査する。返す JSON の形はこのコマンドの形で、判定の語は型の後ろの対応表のとおり欄に書く）
- Modify: `works/blk-refix/lib/refixrules.py`（`parts(n, values, seat="")`。座の節は `refix-keep` の後）・`works/blk-refix/blk-refix.yaml`（節 `refix`・`refix2` に `skills: [receiving-code-review]` と `Skill`）
- Modify: `<218: 外れの機械の検査の 1 か所>`（`fixshape.plain` なら呼ばない）
- Modify: `works/dev/fixmeasure.py`（`redo` に `compliance_fails`・`quality_fails`）
- Modify: `works/tests/test_seat.py`・`works/tests/test_blk_delta.py`（cut の 1 本）・`works/tests/test_blk_refix.py`（parts の 1 本）・`works/tests/test_fixmeasure.py`（`test_sp_skills` は期待を `fixshape.SKILL_NODES` から引くので直す所は無い）

**Interfaces:**
- Consumes: 216 の `seams.json` の `task-review` の `placeholders`・`words`（`"✅ Spec compliant": "compliance_pass"` ほか 5 語）、`receiving-review` の `applies`・`not_applies`。218 の返答の 2 判定の欄
- Produces:
  - `seat.VERDICT_WORDS: dict[str, tuple[str, str]]` — 216 の works の語 → `(<218 の欄>, <218 の語>)`。5 語の全部を持つ
  - `seat.words_table(seam_id: str) -> str` — 型の語・works の語・欄の値の 3 列の Markdown の表。語の対応に無い語が在れば `ValueError`
  - `seat.section("review", "g3", values)` — task-review の型を埋めた文と `words_table("task-review")`。values の 6 つの穴:
    - `[BRIEF_FILE]` は 218 が brief に足す修正案の brief の控え。
    - `[GLOBAL_CONSTRAINTS]` は人の方針の文書のパスか `（無し）`。
    - `[REPORT_FILE]` は修正役の返答の出力のファイル。
    - `[BASE_SHA]`・`[HEAD_SHA]` は cut が切った版。
    - `[DIFF_FILE]` は cut の `diff_file`。
  - 審査役の節は `skills:` も Skill も持たない（部品の型は役が読むファイルで、スキルとしては読まない。216 の NEVER の定め直しのとおり）

- [ ] **Step 1: 落ちる試験を書く**

```python
def test_verdict_words_cover_task_review_words(self):
    self.assertEqual(set(spseam.load_seams()["task-review"]["words"].values()), set(seat.VERDICT_WORDS))

def test_review_seat_has_filled_part_and_table(self): ...   # 6 つの穴を埋めた文に [A-Z_]+ が残らず、"✅ Spec compliant" と 218 の準拠の欄の行が表に在る

# test_blk_delta.py
def test_cut_writes_seat_file_only_in_g3(self): ...         # g3 → brief の seat_file が在るファイルで seat.HEAD を含む。af → seat_file == ""

# test_blk_refix.py
def test_refix_seat_after_keep(self): ...                   # parts(1, values, seat="S") の "refix-keep" の次が "seat"

# test_fixmeasure.py
def test_row_counts_two_verdicts(self): ...                 # 審査の出力に準拠 fail 1・品質 fail 1 → redo の 2 欄
```

- [ ] **Step 2: 落ちることを確かめる**

Run: `cd works/tests && PYTHONDONTWRITEBYTECODE=1 python3 -m unittest test_seat test_fixmeasure test_blk_refix`（`test_blk_delta` は cut の 1 本を名指す）
Expected: FAIL

- [ ] **Step 3: 座と切り替えを書く**（手直しの役の座は、`refixrules` の呼び手（refix の支度）が `fixshape.shape_at` で引いて渡す。current の切り替えは 218 の検査の呼び出しの 1 か所だけ）

- [ ] **Step 4: 通ることを確かめる**

Run: Step 2 と同じ ＋ `test_sp_skills test_yaml_rules test_layers`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add works/.shared/core works/blk-delta works/blk-refix works/blk-fix works/dev/fixmeasure.py works/tests
git commit -m "feat(works): 修正の形 g3 で差分の審査役に task-reviewer の型、手直しの役に receiving-code-review の座を載せ、current では外れの検査を切る"
```

---

### Task 10: 211 の後: 申し出の種類を座の文と測る関数に通す

**前提:** 211 が取り込まれている。最初に 211 の申し出の種類の欄の名と語（設計の 4 つ: `brief_vs_judgment`・`unnamed_test_broke`・`not_red`・`scope_needed`）と、裁定 `fix_plan_item` の控えの置き場を引く。

**Files:**
- Modify: `works/.shared/core/seat.py`（`DIVERGENCE_HINT`: implementer の語 `NEEDS_CONTEXT`・`BLOCKED`（216 で `divergence`）に当たる時、どの種類で申し出るかの 4 行。座の implementer と g1 の節に載る）
- Modify: `works/dev/fixmeasure.py`（`divergences` を 211 の種類で数える。`rulings` に `fix_plan_item`）
- Modify: `works/tests/test_seat.py`・`works/tests/test_fixmeasure.py`・`works/CHANGELOG.md`

**Interfaces:**
- Consumes: 211 の種類の語の並び（名は 211 の実装に合わせる）
- Produces: `seat.DIVERGENCE_HINT`（種類の語を全部含む）。`fixmeasure.row` の `divergences` は 211 の語ごとの件数と、種類の無い前の行の `"unkinded"`

- [ ] **Step 1: 落ちる試験を書く**

```python
def test_divergence_hint_names_every_kind(self):
    for k in KINDS_211:                     # 211 の実装の種類の並び
        self.assertIn(k, seat.DIVERGENCE_HINT)
    self.assertIn(seat.DIVERGENCE_HINT, seat.section("fix", "g3", FIX_VALUES))

def test_row_counts_divergence_kinds_and_plan_item_rulings(self): ...
```

- [ ] **Step 2: 落ちることを確かめる** — Run: `cd works/tests && PYTHONDONTWRITEBYTECODE=1 python3 -m unittest test_seat test_fixmeasure` / Expected: FAIL
- [ ] **Step 3: 書く**
- [ ] **Step 4: 通ることを確かめる** — Run: Step 2 と同じ ＋ `WORKS_TESTS=fast nice -n 19 sh works/tests/run.sh` と `sh ~/.cache/works-dogfood/rootfences.sh` / Expected: PASS・失敗 0
- [ ] **Step 5: CHANGELOG** — `[Unreleased]` の Task 8 の項目に「差分の審査役・手直しの役の座（218 の後）と、申し出の種類の数え（211 の後）」を 1 文足す
- [ ] **Step 6: Commit**

```bash
git add works/.shared/core/seat.py works/dev/fixmeasure.py works/tests/test_seat.py works/tests/test_fixmeasure.py works/CHANGELOG.md
git commit -m "feat(works): 座の文に申し出の種類を名指し、測る関数が申し出を種類ごとに、裁定 fix_plan_item を数える"
```

---

## 試しの回し方（実装の後。この計画の Task ではない）

1. 固定材料を作る: 選んだ 3 件の依頼を、Task 10 までを取り込んだ works の HEAD で `dogfood.sh` で 1 回ずつ回す（形は何でもよい）。各 run の `$ARTIFACTS_DIR/fix-fixture/` を控える。
2. 同じ works の HEAD のまま、各固定材料について `WORKS_FIX_FIXTURE=<控え> WORKS_FIX_SHAPE=<腕>` で 4 つの腕を回す（12 本。切り離して回す殻 `~/.cache/works-dogfood/detach.sh`・`go.sh` を使う）。
3. 各 run を `fixmeasure.py row` で行にし、`fixmeasure.py verdict` に掛ける。`incomplete` なら名指された組だけを 1 回回し直す。
4. 判定（`keep_g3`・`switch_to_af`・`fix_gates_first`）と `import_from_g1`・`vs_current` を持ち主に報告する。決まりの数は動かさない。

## 決定の後（別の計画。今は作らない）

- 入力から `g1`・`current` を外す: `fixshape.SHAPES` を `("af", "g3")` にし、外した語は `InputRefused`（「試しは済んだ」と名指す）。前の盤面の `current`・`g1` は読めるように `shape_at` だけ受ける。
- 外す物: Task 6 の 4 つの切り替え・Task 7 の g1 の分かれ（`G1_NO_LOOP`・`g1_values`・`g1_section`・節 `fix`・`fix-ruled` の `Agent`）・柵の Agent の行。
- 残す物: af（撤収の退路。■11）・g3・束・固定材料・測る関数。af の文は固定材料で通る状態に保つ。判定が `switch_to_af` なら `DEFAULT` を af に替える。
- `import_from_g1` が在れば、勝った要素を G3 の節に取り込む依頼を 1 本起こす。

## 後の依頼 221 への継ぎ目（依頼ごとの振り分けと SDD の道。この計画では作らない）

- 形を選ぶ口: `fixshape.choose(board_dir, shape, by=…, why=…)` が `r1/fix-shape.json` を書き、`shape_at` は入力より先にそれを読む（Task 1）。座・柵・束・current の切り替え・測る関数は全部 `shape_at` から引くので、選んだ形にそのまま従う。
- 振り分けを置く所: 境の節 h-fix（`line_edge.edge` の at fix）の、`go` を決めた後・固定材料を写す前。判定の出力（直す義務の単位の数・食い違いの申し出・構造の目の単位 `structure-units.json` と独立設計の要否）がここで全部そろう。入力 `fix_shape` が空の時だけ選ぶ形にすれば、形を名指した run と固定材料の run（Task 5 は取り込みで選んだ形の控えを消す）は今と同じに動く。
- 既定は変わらない: 振り分けが無ければ `fix-shape.json` は書かれず、入力（空なら g3）のまま。
- SDD の道: 形の語を 1 つ足し（`SHAPES` に足す）、`denied_tools` の表と `seat.SEATS` に行を足す形で入る。g1 の分かれ（Task 7: 輪を飛ばす・修正役が下請けを回す・束が事後に当てる）が最も近い下敷き。writing-plans（今は借りる一覧の外）を使うかは 221 と 216 の取り決め。
- 測る関数は形の語を表で持つので、新しい形の行もそのまま数えられる。`verdict` の決まりはこの試しの 4 つの腕のための物で、221 は自分の決まりを先に固定する。

## この計画が扱わない物

- 216 の物（写し・pin・節の中身・`unattended.md` の決まり・`toolset.py`）。借りる一覧のうち座の無いスキル（systematic-debugging・verification-before-completion・requesting-code-review）を一覧から外すかは 216 か別の依頼。
- `use.sh`（利用者の殻）に `fix_shape`・`fix_fixture` を出すこと。試しは自分食いの殻 `dogfood.sh` だけで回す。
- 試しの実行そのもの・固定材料の依頼の選定（持ち主）。
- 振り分け（router）と SDD の道（lane）（221）。
