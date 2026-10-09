# 同じ run の中で修正案の項目を直す道（依頼 226・道 (a)）Implementation Plan

状態: 入れた（works 0.2.20。2 回目の修正の段 `refitting`）。回の印 `pass_tag` は依頼 239 で消した（works 0.2.23）。

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

## この文書の読み方（初めて読む人向け。本文の語はここで全部定める）

読み手: この計画を 1 Task ずつ実装する役。リポジトリ（claude-plugins）を手元に持ち、名指したファイルを開いて確かめられる。本文の「今どおり」「今の〜」は、この枝 `wip/sdd-226`（起点 d9893a98）の今のコードの振る舞いのまま、の意味で、名指したファイルが正本。外の資料（依頼の文・前の run の設計）は、要る所をこの文書に書き写した。開かなくても実装できる。

置き場と道具:
- パスは、断りが無ければリポジトリの根からの相対。`CLAUDE.md:20` は根の `CLAUDE.md` の 20 行目。
- works: `works/` のプラグイン。Archon（AI の作業の流れを YAML で回す外の道具。版 v0.11.1）の上で、人の修正依頼を直す工程を回す。run は 1 回の実行。
- 線: `works/darkfactory/darkfactory.yaml`。節が一方向に並んだ DAG（巡回の無いグラフ）。判定 → 修正案と事前審査 → 修正の前の人の関所 → 修正 → 再審 → 差分の審査 → 手直し → 最後のテスト → 独立の目 → 最後の人の関所 → 報告、の順。線は節（YAML の nodes の 1 つ）の並びで、節の 1 種類が include（ブロックを差し込む節）。
- ブロック: `works/blk-*/`。線が `include` で使う、節の束。修正案は `blk-plan`、修正は `blk-fix`。ブロックの中の輪（loop_group）は、役の返答が受け付けに通るまで同じ節の組を最大 3 回まわす。
- 盤面: run ごとの状態の置き場（`$ARTIFACTS_DIR/board/`）。周（round）ごとの作業ファイルは `board/r<N>/<名>`（`b.work(名)`）。節の出力は `board/out/r<N>/`。盤面の節（`p2.fix_plan`・`p2.plan_review`・`p2.human_gate`・`p3.fix` など）は、本流 graphloops の review-loop の graph の写しで、出力は 1 周に 1 度だけ受ける。線の節と盤面の節は別物で、線のブロックが盤面の節の返答を作って渡す。
- 境の節: 線の `h-*` の節。どれも `darkfactory/scripts/edge.py` を `at` を替えて回し（中身は `darkfactory/lib/line_edge.py` の `edge`）、盤面を読んで次のブロックを回すか（`go`）と関所を開くか（`ask`）を決める。いつも走る。`when:` と関所の文はこの節の出力だけを読む。
- 写し: `works/.shared/core/graphloops/`・`works/.shared/core/gl-prompts/` は本流（リポジトリの根の `graphloops/` プラグイン）のバイト単位の写し。手直しは台帳 `works/.shared/core/COPIED_FROM` の `!` 行（形は `copyledger.py`）だけで入れる。この計画は写しを変えない。
- 試験の段: `works/tests/tiers.py` の FAST（速い段）と HEAVY（重い段: git・盤面・子のプロセスを使う）。手元で回すのは速い段と、この計画で触った重い段の模块を名指した物だけ。重い段の全部は GitHub の CI。

役（AI の節。どれも JSON の返答だけを返し、機械の受け付けが確かめる）:
- 修正案の役: 判定の後、直し方の案（項目の並び）を書く。事前審査の役: 別の目で案の穴（faces）を挙げる。案と事前審査を通り、修正の前の関所（`policy-gate`。聞く事が在る時だけ開く）を抜けた案を「承認済みの修正案」と呼ぶ。
- 修正役: 作業ツリーを書き換えて直す。TDD の役: 修正役の前に、単位ごとに落ちるテストを書いて直す輪の役。裁定役: 申し出を読むだけで裁く。
- 独立の目 R1〜R4: 修正の後の差分を 4 つの観点で見る役（R1 直しが最小か・R2 目的だけから作った独立設計と構造が合うか・R3 前提と全体の筋・R4 依頼の範囲を超えないか）。

依頼と関わる番号（依頼は、works の直しを works 自身の工程に流す頼みごとの 1 件）:
- 211: 食い違いの申し出の種類と、裁定 `fix_plan_item`（承認済みの修正案の項目そのものが誤り）。今は、そう裁かれた項目の単位を直す義務から外し、次の run に持ち越す。
- 217: 修正案の項目の works の欄（`route`・`tests`・`rewrite_tests`・`refactor`）と、項目ごとの brief（要求の正本。`works/blk-fix/lib/planbrief.py`）。
- 218: 範囲の欄 `allowed_paths`・`out_of_scope` と、修正の受け付けの照らし（`works/blk-fix/lib/planscope.py`）。
- 224c: 修正役の返答の形の誤りを 1 回の拒否に全部並べる。227: 受け入れのテストの id を既存の置き方に合わせる。どちらもこの枝に入っている。
- 226: この計画。中身は Goal に書いた。226b・226c は同じ依頼を工場自身に回した run（226b は申し出の unit_key の一字違いで止まり、226c は R1〜R4 の全部が作り直しと言った）。過去の run 224b・225・195b・194c は、案の項目の小さな誤り（赤の種類・クラスの無いテストの id・狭すぎる範囲・足りない `rewrite_tests`）で差分が空のまま終わった run。

works の中の語:
- 単位: 判定役が切った 1 つの欠陥。key で呼ぶ。
- 申し出と裁定: 修正役・TDD の役が「依頼・テスト・コードのどれかが同時に成り立たない」と名指しで返す物が申し出。裁定役が 5 つ（`fix_test_scope`・`fix_code_as`・`ask_human`・`replace_query`・`fix_plan_item`）のどれかに裁く。控えは `b.work("conflicts.json")`、模块は `works/.shared/core/conflict.py`。
- 直す義務: 修正役が今直す単位の集合（`conflict.fix_duty(b)` の 1 つ目）。外れた単位と理由が 2 つ目（excused）。
- 修正の段の 1 回目・2 回目: 線の `fixing`（今の修正の段）を 1 回目、案を直した後の修正を 2 回目と呼ぶ。どちらも `blk-fix` の節で回る（形は Task 9 の測りで決める）。
- 案の直し（replan）: `fix_plan_item` と裁かれた項目を、同じ run の中で修正案の役に直させ、事前審査と人の関所の決まりを通して、2 回目の修正の段に戻すこと。この計画が作る。
- 案の直しを待つ単位: `fix_plan_item` の裁定が外した単位（申し出の単位と、同じ項目に載る単位の全部。`conflict.ruled_units`）。
- 約束の欄・手段の欄: 修正案の項目の欄の 2 つの組。約束の欄は人に約束した事（どの単位を・何を狭め・何を消し・どこを書き・どこを触らず・どの既存テストの期待を変えるか・受け入れのテストが確かめる振る舞い）。手段の欄はどう直し、どう確かめるか（やり方・足す識別子・テストの id・置き場・赤の種類など）。
- 1 回目に受け付けた返答の控え: 1 回目の修正の段の受け付けが、待つ単位が在るので盤面の `p3.fix` に渡さずに置いた返答（`b.work("fix-held-reply.json")`）。
- 回の印（pass_tag）: 2 回目の修正の段が今の周に置く 1 回ごとのファイル（指示書・delivered・variants・拒否の理由・裁定の文）の名に足す印。1 回目は空で、今の名のまま。
- keep-essence: `works/docs/keep-essence.md` の、どの形でも残す works の強み 11 項目（1 赤緑の機械の判定・2 元から赤の区別・3 テストの凍結・4 3 回拒まれたら諦める・5 書き込みの出どころの突き合わせ・6 受け付けで選んで回す試験・7 class_query の数え直し・8 申し出と裁定・9 独立設計と R1〜R4・10 守りのファイルと最後の関所・11 単位ごとの記録）。

持ち主の手元の資料（要る所はこの文書に書き写した）:
- `~/.cache/works-dogfood/req-226.json`・`req-226b.json`・`req-226c.json`: 依頼の文。226b の関所の答え「上限で諦めた時は裁定の文を ask_human の行と次の run の依頼に字のまま載せる。REPLAN_HEAD の専用の節と line_edge の専用の文は消してよい」。
- run 226（設計だけ）の独立設計 `.../run-226/.../board/design.json`: この計画の主な拠り所。節を ■1〜■8 で呼ぶ。要点は Architecture と下の外れ D1〜D4 に書き写した。
- run 226c の独立設計（■0〜■7）と最後の関所 `final-gate.md`: R2 の 4 点の出どころ（下の「R2 の 4 点の受け持ち」に書き写した）。226c の差分は、やらない事の見本（盤面の節を戻す・写しの `board.py` を `!` 行なしで変える・新しい定数 REPLAN_LIMIT・戻る道より先に持ち越しの道を消す）。
- 事前の照らし `.superpowers/sdd/2026-10-03-in-run-replan/preflight.md` の P1〜P23 と、運び役（会話で SDD を回す controller）の裁定（同じ置き場の `progress.md`）。この計画の今の版は P1〜P23 の全部と 3 つの裁定を本文に入れた。

---

**Goal:** `fix_plan_item` の裁定が出た時、その項目を次の run に持ち越さず、同じ run の中で修正案の役に戻して項目だけを直させ、事前審査と、1 つの決まりで開く人の関所を通してから、2 回目の修正の段で直す。持ち越しの専用の道（報告の REPLAN_HEAD の節・最後の関所の専用の文・結末 `round_limit` の分かれ）を消し、直せなかった単位は既存の ask_human の道に合流させる。

**Architecture:**

- 線の `fixing` と `h-rejudge` の間に、案の直しの鎖を足す: 案を束ねる → 修正案の役（項目だけ）→ 事前審査の役 → 関所を開くかを決める → 関所 `replan-gate`（要る時だけ）→ 答えを受ける → 2 回目の修正の段。鎖の形（ブロックを 2 度 include する形 A か、1 つの include に回の入力で載せる形 B か）は、Task 9 の前に運び役が Archon v0.11.1 で測った結果で決める（Task 9）。
- 盤面の節は戻さない。待つ単位が在る間、1 回目の受け付けは `p3.fix` を盤面に渡さずに返答を控え、2 回目の受け付けが控えの行と新しい行を合わせて渡す。案を直さずに終わった時（諦めた・人が止めた）は、控えをそのまま渡す。報告は盤面の `p3.fix` が無ければ控えを読む（1 回目に直した単位の記録を落とさない）。
- 直した項目は works 側の控え `plan-fields.json` に重ねる（鍵 `amended`）。差し替えは `planmarks.amend` だけがし、trace に印 `plan_amended` を書く。承認済みの項目を読む口（`planmarks.approved_items`・新しい `planmarks.plan_items`）が重ねた形を返し、brief はその印の後だけ切り直す。2 回目の修正役の `plan_file` は盤面の `p2.fix_plan` の出力のまま（事前審査の返答が隣に在る）で、直した項目は切り直した brief と覚え書きで届く。
- 案の直しの段の全部（束ねる・指示書・受け付け・関所の決まり・答え・締め）は新しい core の模块 `works/.shared/core/replan.py`（層 L3）が持つ。指示書の頭（役の定義・独立設計の節）は呼び手が組んで渡す（`replan` は blk の lib を import しない）。
- 待つ単位の状態は `conflicts.json` の裁定の行の欄 `replan`（`waiting`・`amended`・`gave_up`）。`amended` の行だけが直す義務を外さない。`gave_up` の行は ask_human の行と同じ道（最後の関所・報告・次の run の依頼）に載り、裁定の文は字のまま。
- 関所 `replan-gate` の答えの語は、ほかの関所と同じ意味: continue・approve は直した項目で修正に戻る。stop・reject は run を止める（1 回目に直した単位の差分は報告に残る）。

**Tech Stack:** Python 3.12 以降の標準ライブラリ（`json`・`hashlib`・`pathlib`）、works の盤面の層（`entry`・`board`・`conflict`・`planmarks`・`rolekit`・`recount`・`gatemarks`）、Archon の YAML（loop_group・include・approval）、unittest（`works/tests`）。

**Spec:**
- 依頼の文 `req-226.json`・`req-226b.json`（関所の答え）・`req-226c.json`（申し出の unit_key は一字も変えずに写す）。
- run 226 の独立設計 ■1〜■7（道 (a)・消す物と残す物・日々の動線）。
- run 226c の R2 が名指した 4 点（下の「R2 の 4 点の受け持ち」）と、226c の独立設計 ■2・■4（渡す物を絞る・約束の欄と手段の欄の 1 つの決まり）。
- R3: 写しの手直しは `!` 行だけ。
- 運び役の裁定（`progress.md`）: 決定 1（D1 を採る）・決定 2（約束の欄はこの計画の表のまま）・決定 3（`replan-gate` の stop は run を止める）・P1〜P23 を提案どおり採る。

## 設計からの外れ（今のコードと Archon の決まりに照らした結果。どれも 1 つの軸「目的と keep-essence を保って全体がより簡潔か」で選んだ）

- **外れ D1（戻る回数）: 案の段に戻るのは 1 run に 1 回。数える定数を持たない。** 226c の R2 は「共通の GIVE_UP_AFTER（`rolekit.GIVE_UP_AFTER = 3`）で、事前審査の拒否による戻りも数える」と求め、226 の ■4 は「1 単位につき 1 run に 1 回・run 全体にも小さな上限」と言う。今のコードと Archon の決まりでは、戻る鎖（修正案の役 → 事前審査の役 → 人の関所 → 修正の段）を run の中で繰り返せない。
  - 線は巡回の無い DAG で、節を回し直す道が無い（226c の R1 が指摘）。
  - 人の関所は loop_group の本体に置けない（Archon #3532。`works/tests/test_yaml_rules.py` が縛る）。
  - 1 つの輪には AI の節を 1 つだけ置く（裁定 TA13。修正案の役と事前審査の役を同じ輪に置くと、事前審査が修正案の会話を継ぐ恐れもある）。
  - include を輪の中に置く形は works のどこにも無く、確かめられていない。
  - だから鎖は 1 本だけ足す。数えても 1 にしかならないので、数える物も定数も作らない（新しい定数を足さないことは R2 の言うとおり）。各役の出し直しは今の輪（`max_iterations: 3` = `rolekit.GIVE_UP_AFTER`）がそのまま縛る。事前審査が人に聞く種類の穴を挙げた直しは、今の鎖と同じく人の関所に出る。人が stop と答えれば、ほかの関所と同じく run を止める（1 回目に直した単位の差分は報告に残る）。2 回目の修正の段で同じ単位が再び `fix_plan_item` と裁かれた時と、役が 3 回とも拒まれた時は、その単位を諦めて ask_human の道に載せる。諦める道は 1 本で、決めるのは「待つ単位が残ったまま鎖を抜けたか」だけ。
- **外れ D2（事前審査の「拒否」）: 事前審査は案を修正案の役へ差し戻さない。** 226c ■3 は「事前審査が拒んだら修正案の役へ戻す」と言う。D1 と同じ理由で戻せない。今の鎖でも事前審査は差し戻さず、後退（regression）と方針の穴（policy）を人の関所に出し、ほかの穴は修正役が `plan_faces` で答える。案の直しでも同じに扱う。人に聞く種類の穴は関所の決まりの 2 つ目の条件になり、ほかの穴は 2 回目の修正役の材料に載る。
- **外れ D3（盤面の節を戻さない）: `Board.rewind` も写しの `board.py` も使わず、変えもしない。** 226c は `p2.fix_plan`・`p2.plan_review`・`p2.human_gate`・`p3.fix` を戻し、機械の節を戻せない守り（`die`）を写しから `!` 行なしで消した（R3）。しかも戻しが `p3.fix` の出力の指しを外し、1 回目に直した単位の記録が報告から消えた（R1）。この計画は `p3.fix` を待つ単位が片付くまで渡さない。盤面の 1 周に 1 度の約束をそのまま使う。
- **外れ D4（brief の名）: 直した項目の brief は `brief-<n>.md` の名のまま切り直す。** 226 ■7 の `brief-1.amend-1.md` の名は使わない。前の項目と直した項目の両方は、案の直しの記録 `replan.json` に残る。読む側（修正役・TDD の役・差分の審査）の分かれを作らないため。

## R2 の 4 点の受け持ち

1. 承認済みの案を変えた時に、人に聞かずに通す範囲を 1 つの決まりで決める（約束の欄と手段の欄。欄を比べて決めるのはコード）→ Task 1（欄の表と `contract_diff`）・Task 7（`replan.gate`）。
2. 修正案の役に渡すのは、誤りと裁かれた項目・申し出の文・裁定の文だけ。返答はその項目の id に限り、差し替えるのはコード → Task 6（`replan.prep`・`replan.accept_reply`）・Task 1（`planmarks.amend`）。
3. 案の直しの後に、待つ単位を直す義務へ戻す継ぎ目と、待つ単位を残したまま run を終えない不変条件 → Task 3（状態と `held_by_rulings`）・Task 4（`replan.settle` の不変条件と、報告の組み立ての締め）・Task 7（`replan.answer`）・Task 8（2 回目の修正の段）。
4. 戻りを共通の GIVE_UP_AFTER で数え、事前審査の拒否も数える。新しい定数は足さない → 外れ D1・D2 のとおり。新しい定数を足さないことは Task 4 の試験が縛る（`replan` に回数の定数が無い）。

## Global Constraints

- 期限・タイムアウトを新しく足さない。止めるのは条件だけ。新しい script の節の `timeout: 1728000000` と、AI の節の `idle_timeout: 1728000000` は YAML の決まり（`test_yaml_rules.py`）が求める決まった値で、新しい期限ではない。approval・include・loop_group の節は期限を持たない。
- 写し（`works/.shared/core/graphloops/`・`gl-prompts/`）と本流 `graphloops/` は変えない。どうしても要れば `COPIED_FROM` に `!` 行（path・old・new・why）を足し、`python3 works/dev/core-sync.py --check` を緑にする。この計画の Task はどれも写しを変えない。
- keep-essence の 11 項目を保つ（1〜3 は 2 回目の修正の段でも同じ TDD の輪と凍結。凍結は run の全部の輪で効く。4 は修正の単位の 3 回の諦めを回ごとに数える。5〜7 は控えの道でも同じ trace を書き、1 回目の Bash の書き込みの申告を 2 回目の突き合わせに渡す。8 の裁定役の語 `fix_plan_item` は残し、意味だけを「同じ run で案に戻す」に変える。9 の独立設計は案の直しの事前審査に貼り、R1〜R4 は修正の後の差分にそのまま回る。10 の最後の関所は、諦めた単位を ask_human の行として並べ、承認された直しの `rewrite_tests` も守りのファイルの行に並べる。11 は案の直しの記録の行を最後の関所と報告に載せ、run が止まっても 1 回目に直した単位を報告に残す）。
- 事前審査を通り、関所の決まりで人が承認した（か、聞く要の無い）項目だけで直す。2 回目の修正の段の要求の正本は、直した項目から切り直した brief。
- 盤面の 1 周に 1 度の節の約束を崩さない（`Board.rewind` を呼ばない）。
- 層（`works/tests/test_layers.py` の表 `MOD`。上の層は同じ層か下の層だけを import する）: `replan` は L3（`"replan": (3, None)`）。L3 どうしの import で輪を作らない（`conflict`・`planmarks` は `replan` を import しない。`report` は `replan.lines`・`replan.close_at` を呼ぶので `report` → `replan` の向きだけで、`replan` は `report` を import しない）。`replan` は blk の lib（`planblk`・`planbrief`・`fixrules`・`tddloop`）を import しない。
- 新しい試験の模块は `works/tests/tiers.py` の FAST か HEAVY に書く（`test_replan` は HEAVY: 種の git と盤面を作る）。
- 受け入れのテストの id はクラスの中（`<パス>::<クラス>::<名>`。227 の決まり）。この計画の試験もどれも `unittest.TestCase` のクラスの中に置く。
- 新しい模块は `from __future__ import annotations` で始め、注記・docstring・指示書の文・拒否の文は日本語。
- Python 3.12 が下限。
- 役の返答の型・ブロックの入力・script の `with` を変えた Task は、同じ Task の中で表の試験（`test_blk_plan`・`test_blk_fix` の YAML の突き合わせ・`test_script_contract`・`test_line.LineShapeCase`・`tests/linekit.py` の `LINE_ORDER`）を合わせる。
- 焦点の試験: `cd works/tests && PYTHONDONTWRITEBYTECODE=1 python3 -m unittest <module>[.<Class>]`。組の仕上げ（Task 4・9・10 の終わり）: `WORKS_TESTS=fast nice -n 19 sh works/tests/run.sh` と `sh ~/.cache/works-dogfood/rootfences.sh`（根の `tests/run.sh` の速い柵だけを当てる殻）。
- CHANGELOG は `works/CHANGELOG.md` の `[Unreleased]` だけに足す（Task 10）。版は上げない。
- commit のメッセージは日本語で、末尾に `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`。push はしない。

## Review Focus

1. 2 回目の修正役が、1 回目の TDD の輪が凍らせた既存のテストを書き換える → 拒む（凍結は run の全部の輪で効く）。2 回目の輪が同じファイルに新しい受け入れのテストを足すのは通し、外すのは直した項目の単位の古い受け入れのテストの関数の範囲だけ。（Task 8 の `test_second_pass_cannot_touch_first_loop_frozen_tests`・`test_second_loop_may_add_test_to_first_loop_file`・`test_amended_units_old_test_span_is_not_frozen`）
2. Archon の再開で境の節（答えを受ける節・`h-rejudge`）が 2 度走る → 項目を 2 度差し替えない・`p3.fix` を 2 度渡さない・`process.human_items` に行を積み増さない。（Task 7 の `test_answer_twice_is_idempotent`、Task 5 の `test_settle_twice_hands_once`）
3. 修正案の役が、渡していない項目を返す・項目を足す/落とす・unit_keys を一字でも変える（番号で書く・別の key）→ 誤りを全部並べて 1 回で拒む。差し替えるのは渡した項目だけ。（Task 6 の `test_reply_limited_to_handed_items`）
4. 待つ単位を残したまま鎖を抜ける（修正案の役が 3 回とも拒まれた・事前審査の役が 3 回とも拒まれた・関所が開かなかった・2 回目の修正の段で再び `fix_plan_item`・`fixing` が落ちて `h-rejudge` が飛ばされた）→ どれも諦めて ask_human の行に載り、裁定の文は字のまま最後の関所と次の run の依頼に届く。run が止まった盤面でも待つ行は締める。`h-rejudge` の後に `waiting` の行が残れば BoardGap で落ちる。（Task 4 の `test_settle_closes_waiting_rows`・`test_unsettled_is_board_gap`・`test_report_build_closes_waiting_rows`、Task 7 の `test_gave_up_paths_reach_ask_human_verbatim`）
5. この版の前に作った盤面を再開する（裁定の行に欄 `replan` が無い・`plan-fields.json` に鍵 `amended` が無い）→ 欄の無い `fix_plan_item` の行は `waiting` と読み、鍵の無い控えは直しの無い案と読む。落ちない。（Task 1 の `test_old_fields_file_has_no_amendments`、Task 3 の `test_row_without_state_reads_as_waiting`）

---

### Task 1: 約束の欄と手段の欄・承認済みの項目の差し替え（`planmarks`）

**Files:**
- Modify: `works/.shared/core/planmarks.py`（表 3 つと関数 4 つ。`save` に keyword 1 つ。`approved_items` を `plan_items` 経由に）
- Test: `works/tests/test_plan_fields.py`（FAST のまま。新しい class `TestContractFields`・`TestAmend`）

**Interfaces:**
- Consumes: 今の `planmarks.save`・`read`・`frozen`・`_saved_mark`・`approved_items`・`split`・`KEYS`・`FieldsBroken`
- Produces:
  - `CORE_KEYS = ("unit_keys", "approach", "adds", "removes", "shrink_first", "narrows")`（写しの graph の項目の欄。`amended` に置く物。`approved_items` が足す鍵 `item` は含めず、置く前に外す）
  - `CONTRACT_KEYS = ("unit_keys", "narrows", "removes", "allowed_paths", "out_of_scope", "rewrite_tests")`
  - `CONTRACT_TEST_KEYS = ("behavior",)`（`tests[]` の行のうち約束の欄）
  - `MEANS_KEYS = ("approach", "adds", "shrink_first", "route", "route_why", "tests", "refactor")`（`tests` は `CONTRACT_TEST_KEYS` の外の欄だけが手段）
  - `AMENDED_KEY = "amended"`（`plan-fields.json` の鍵。`{"<項目の番号>": {CORE_KEYS の欄}}`）
  - `AMEND_OP = "plan_amended"`（`amend` だけが書く trace の行 `{round, items: [番号…]}`。`SAVED_OP` の行の直後に書く）
  - `contract_diff(old: dict, new: dict) -> list[str]` — 約束の欄のうち違う物の名を `CONTRACT_KEYS` の順に返し、最後に `tests[].behavior` の並び（並べ替えた物）が違えば `"tests.behavior"`。比べは `json.dumps(…, sort_keys=True, ensure_ascii=False)` の字。`unit_keys` は並べ替えて比べる。欄が無いのと空の並びは同じと読む。呼び手は narrows を関所の決め手の欄を外した形（`gatemarks.split` の後）で渡す（Task 6・7）。
  - `save(board, rnd: int, fields: list, amended: dict | None = None) -> None` — `amended` が在れば鍵 `AMENDED_KEY` に置く（無ければ書かない。今の控えとバイトが同じ）。印は今どおり `SAVED_OP`。
  - `amended(b) -> dict[int, dict]` — 今の周の控えの `AMENDED_KEY`（番号を int に）。印と食い違えば `frozen` と同じ `FieldsBroken`。控えに鍵が無ければ `{}`。
  - `plan_items(b) -> list | None` — 盤面の今の周の `p2.fix_plan` の `plan` に、`amended(b)` の核の欄を番号ごとに重ねた並び（無ければ None）。
  - `approved_items(b)` — `plan_items(b)` と `frozen(b)` を合わせる（形は今と同じ `{"item", **核, **KEYS の欄}`）。
  - `amend(b, items: dict[int, dict], repo) -> None` — `items` は `{番号: 直した項目（CORE_KEYS と KEYS の欄の全部。鍵 item は外す）}`。直した項目を `split({"plan": [項目]}, repo)` に通して欄の行を作り直す（`adds` の名と `rewrite_tests[].limit` を repo から引き直す。引かずに写すと、承認された書き換えが許しにならない）。今の控え（`frozen(b)`。食い違えば `FieldsBroken`）の `fields[n-1]` をその行に替え、核の欄を `AMENDED_KEY[n]` に置いて `save` し直し、`AMEND_OP` の行を書く。知らない番号・unit_keys が元と違う項目は `ValueError`（受け付けが先に拒む物。ここに届けば配線の誤り）。

- [ ] **Step 1: 落ちる試験を書く**（今の helper `item(**over)`・`REWRITE`・`PLAN_KEYS` を使う。`import copy` を足す）

```python
class TestContractFields(PlanFieldsCase):
    def test_keys_cover_item_schema(self):
        it = accept.role_schema("p2.fix_plan")["properties"]["plan"]["items"]["properties"]
        self.assertEqual(set(planmarks.CONTRACT_KEYS) | set(planmarks.MEANS_KEYS), set(it))
        self.assertFalse(set(planmarks.CONTRACT_KEYS) & set(planmarks.MEANS_KEYS))
        self.assertEqual(set(planmarks.CORE_KEYS), PLAN_KEYS)

    def test_means_only_change_is_empty(self):
        old = item()
        new = copy.deepcopy(old)
        new["tests"][0]["red_kind"] = "exception"      # 224b の型
        new["tests"][0]["id"] = "test_stats.py::TestStats::test_mean_of_two_values"   # 225 の型
        new["approach"] = new["approach"] + "（直した）"
        self.assertEqual(planmarks.contract_diff(old, new), [])

    def test_contract_change_is_named(self):
        old = item()
        self.assertEqual(planmarks.contract_diff(old, item(allowed_paths=["stats.py", "lib/**/*.py"])), ["allowed_paths"])  # 195b の型
        self.assertEqual(planmarks.contract_diff(old, item(rewrite_tests=[REWRITE])), ["rewrite_tests"])                    # 194c の型
        beh = copy.deepcopy(old); beh["tests"][0]["behavior"] = "3 つの値の平均"
        self.assertEqual(planmarks.contract_diff(old, beh), ["tests.behavior"])

class TestAmend(PlanFieldsCase):
    def test_amend_swaps_one_item_and_refreezes(self): ...
        # 2 項目の盤面の偽物（SimpleNamespace(dir, round, output_of_round)）。項目 2 の red_kind と approach を直して amend
        # → approved_items の項目 2 は新しい値・項目 1 は前のまま・frozen は通る・trace に SAVED_OP が 2 行と AMEND_OP が 1 行
        # → 控えの AMENDED_KEY["2"] に鍵 item が無い
        # → 控えを手で書き換えると approved_items が FieldsBroken
    def test_amend_rebuilds_rewrite_limit_and_adds(self): ...
        # REWRITE を足した直し → rewrites(b) に REWRITE の id が limit 付きで載る・欄の adds が新しい名
    def test_amend_refuses_changed_unit_keys(self): ...   # unit_keys を変えた項目は ValueError（"unit_keys" を含む）
    def test_old_fields_file_has_no_amendments(self): ...  # AMENDED_KEY の無い控え → amended(b) == {}・plan_items は盤面のまま
```

- [ ] **Step 2: 落ちることを確かめる**

Run: `cd works/tests && PYTHONDONTWRITEBYTECODE=1 python3 -m unittest test_plan_fields.TestContractFields test_plan_fields.TestAmend`
Expected: FAIL（`AttributeError: module 'planmarks' has no attribute 'CONTRACT_KEYS'`）

- [ ] **Step 3: 表と関数を書く**（`planmarks` は今どおり `entry`・`conflict`・`gatemarks` を import しない。`amend` は渡された `b` の `dir`・`round`・`output_of_round` だけを読む）

- [ ] **Step 4: 通ることを確かめる**

Run: `cd works/tests && PYTHONDONTWRITEBYTECODE=1 python3 -m unittest test_plan_fields`
Expected: PASS（前からの試験も全部）

- [ ] **Step 5: Commit**

```bash
git add works/.shared/core/planmarks.py works/tests/test_plan_fields.py
git commit -m "feat(works): 修正案の項目の約束の欄と手段の欄の表・欄の比べと、承認済みの項目を凍結し直して差し替える口（226 Task 1）"
```

---

### Task 2: 差し替えの後の brief の切り直し（`planbrief`）

**Files:**
- Modify: `works/blk-fix/lib/planbrief.py`（`_plan` を `planmarks.plan_items` に、`cut` に切り直しの条件）
- Test: `works/tests/test_plan_brief.py`（HEAVY のまま。新しい class `TestRecutAfterAmend`。今の `test_cut_keeps_frozen_text_when_sources_change` はそのまま通る）

**Interfaces:**
- Consumes: Task 1 の `planmarks.plan_items(b)`・`planmarks.amend(b, items, repo)`・`planmarks.AMEND_OP`
- Produces:
  - `RECUT_OP = "brief_recut"`（切り直した印の trace の行 `{round, items: [番号…]}`。直後に今どおりの `CUT_OP` の行も書く）
  - `cut(b)` の決まり（1 つ）: 今の周の trace で、最後の `planmarks.AMEND_OP` の行が最後の `CUT_OP` の行より後に在れば、その行の `items` の項目を今の承認済みの項目から描き直し、文が変わった項目だけファイルを書き、控えと `CUT_OP` の印を置き直して `RECUT_OP` を 1 行。そうでなければ今どおり（書き戻すだけ。`amend` を通らない `save` し直しでは切り直さない）。brief や控えを手で書き換えた盤面は今どおり `LedgerBroken`・書き戻し。

- [ ] **Step 1: 落ちる試験を書く**（helper は今の `BriefCase.ready()`。`count_ops(board, op)` は盤面の `trace.jsonl` の、今の周のその op の行の数）

```python
class TestRecutAfterAmend(BriefCase):
    def test_recut_after_amend(self):
        b = self.ready()
        first = planbrief.cut(b)
        new = {k: v for k, v in planmarks.approved_items(b)[0].items() if k != "item"}
        new["tests"] = [{**new["tests"][0], "red_kind": "exception", "red_why": "今は ZeroDivisionError が出ない"}]
        planmarks.amend(b, {1: new}, self.repo)
        again = planbrief.cut(entry.open_board(self.board))
        text = pathlib.Path(again[0]["file"]).read_text(encoding="utf-8")
        self.assertIn("exception", text)
        self.assertNotEqual(first[0]["sha256"], again[0]["sha256"])
        self.assertEqual(count_ops(self.board, planbrief.RECUT_OP), 1)

    def test_no_recut_without_amend(self):
        b = self.ready()
        planbrief.cut(b); planbrief.cut(entry.open_board(self.board))
        self.assertEqual(count_ops(self.board, planbrief.RECUT_OP), 0)
        self.assertEqual(count_ops(self.board, planbrief.CUT_OP), 1)

    def test_tamper_after_recut_is_restored(self): ...   # 切り直した brief-1.md を書き換え → cut が直した文に書き戻す（RESTORED_OP）
```

- [ ] **Step 2: 落ちることを確かめる**

Run: `cd works/tests && PYTHONDONTWRITEBYTECODE=1 python3 -m unittest test_plan_brief.TestRecutAfterAmend`
Expected: FAIL（`exception` が brief に無い・`RECUT_OP` が無い）

- [ ] **Step 3: 切り直しを書く**（trace の行の順は行の並びで決める。時刻で比べない）

- [ ] **Step 4: 通ることを確かめる**

Run: `cd works/tests && PYTHONDONTWRITEBYTECODE=1 python3 -m unittest test_plan_brief`
Expected: PASS（`test_cut_keeps_frozen_text_when_sources_change` を含む）

- [ ] **Step 5: Commit**

```bash
git add works/blk-fix/lib/planbrief.py works/tests/test_plan_brief.py
git commit -m "feat(works): 承認された項目の差し替えの印の後だけ brief を切り直す（226 Task 2）"
```

---

### Task 3: 裁定の行の案の直しの状態と、1 回目に受け付けた返答の控え（`conflict`）

**Files:**
- Modify: `works/.shared/core/conflict.py`
- Test: `works/tests/test_conflict_kinds.py`（FAST のまま。新しい class `TestReplanState`・`TestHeldReply`）

**Interfaces:**
- Consumes: 今の `conflict.items`・`ruled_units`・`held_by_rulings`・`asked`・`human_lines`・`fix_duty`・`apply_rulings`（`conflict` は `recount` を import しない。節の名は `"p3.fix"` の字で持つ）
- Produces:
  - `REPLAN_STATE = "replan"`（裁定の行の欄）・`WAITING = "waiting"`・`AMENDED = "amended"`・`GAVE_UP = "gave_up"`・`REPLAN_WHY = "replan_why"`・`REPLAN_OP = "replan_state"`（trace の行 `{id, unit_key, state, why}`）
  - `apply_rulings`: 裁定が `REPLAN` の行に `REPLAN_STATE: WAITING` を置く。
  - `replan_state(row) -> str | None` — `REPLAN` の行の状態（欄の無い前の形の行は `WAITING`）。ほかの裁定は None。
  - `waiting(b) -> list` — 状態が `WAITING` の行。
  - `amended_keys(b) -> set` — 状態が `AMENDED` の行の `ruled_units` の全部。
  - `set_replan(b, ids: list[str], state: str, *, why: str = "") -> None` — `WAITING` の行だけを `AMENDED` か `GAVE_UP` に替える（`GAVE_UP` は `why` が空でない）。ほかの移りは BoardGap。同じ状態への移りは何もしない（再開）。
  - `held_by_rulings(b)`: 状態が `AMENDED` の行を外す（それ以外は今どおり）。
  - `asked(b)`: 直す裁定でない裁定（`FIX_DECISIONS` の外）の行のうち、状態が `WAITING`・`AMENDED` でない物（ask_human と、諦めた `fix_plan_item`）。
  - `human_lines(b)`: 行に `REPLAN_WHY` が在れば末尾の括弧に `・案の直し: <why>` を足す。裁定の文は今どおり字のまま。
  - `HELD_REPLY = "fix-held-reply.json"`（中身は盤面に渡す形の返答に、役が申告した `bash_writes` を残した物）・`ACCEPTED_WHY = "1 回目の修正の段で受け付けた（控え {path}。この単位の行は機械が足す）"`
  - `held_reply(b) -> tuple[dict | None, pathlib.Path]` — 今の周に `p3.fix` を受けていない時だけ控えを読む（受けた後・控えが無いなら None）。壊れていれば BoardGap。
  - `accepted_units(b) -> set` — `held_reply` の `changes`・`not_done` の `unit_key`。
  - `held_writes(b) -> list` — `held_reply` の `bash_writes`（無ければ空）。2 回目の書き込みの出どころの突き合わせ（手順 -2）が、役の申告に足して読む（Task 8）。
  - `fix_duty(b)`: 1 つ目（直す義務）から `accepted_units` を引き、2 つ目に `ACCEPTED_WHY` の理由で足す。`owed_units_but_asked`（盤面の検証器の差し替え）は変えない——盤面は全部の単位の行を要る。
  - `with_held(b, reply: dict) -> dict` — 控えが無ければ `reply` のまま。在れば `changes`・`not_done` を「控えの行のうち `reply` に無い単位の行」＋「`reply` の行」にした写し。ほかの欄は `reply` の物。

- [ ] **Step 1: 落ちる試験を書く**（`test_conflict_kinds` の偽の盤面: `SimpleNamespace(work=…, trace=…, round=1, state={"outputs": {}})` と一時の `conflicts.json`。helper `fake_with_rows(rows)` はその盤面に行を置いた物、`row(id, key, decision, *, state=None, text=…, plan_units=())` は行 1 つ、`mean_row()` は MEAN の changes の 1 行。模块の頭に `MEAN`・`CLAMP` の 2 つの key の定数を置く。`fix_duty` を呼ぶ試験は `conflict.owed_units_but_asked` と `gatemarks.withheld_by` を `mock.patch.object` で差す——偽の盤面は `state["graph"]` を持たない）

```python
class TestReplanState(unittest.TestCase):
    def test_ruling_starts_waiting_and_holds(self):
        b = fake_with_rows([row("c1-1", MEAN, None)])                # 裁いていない申し出の行
        conflict.apply_rulings(b, {"c1-1": {"decision": "fix_plan_item", "text": "x" * 20, "limits": [],
                                            "plan_items": [1], "plan_units": [MEAN, CLAMP]}}, by="t")
        self.assertEqual(conflict.items(b)[0]["replan"], "waiting")
        self.assertEqual([r["id"] for r in conflict.waiting(b)], ["c1-1"])
        self.assertEqual(set(conflict.held_by_rulings(b)), {MEAN, CLAMP})
        self.assertEqual(conflict.asked(b), [])

    def test_amended_rows_return_units_to_duty(self):
        b = fake_with_rows([row("c1-1", MEAN, "fix_plan_item", state="waiting")])
        conflict.set_replan(b, ["c1-1"], conflict.AMENDED)
        self.assertEqual(conflict.held_by_rulings(b), {})
        self.assertEqual(conflict.amended_keys(b), {MEAN})

    def test_gave_up_rows_join_ask_human_verbatim(self):
        text = "受け入れのテストの id を\nクラス付きにする（test_tiers.py:136-143）"
        b = fake_with_rows([row("c1-1", MEAN, "fix_plan_item", state="waiting", text=text)])
        conflict.set_replan(b, ["c1-1"], conflict.GAVE_UP, why="修正案の役の直しが 3 回とも拒まれた: 数が違う")
        line = conflict.human_lines(b)[0]
        self.assertIn(text, line)                                  # 字のまま（改行も）
        self.assertIn("案の直し: 修正案の役の直しが 3 回とも拒まれた: 数が違う", line)

    def test_bad_transition_is_board_gap(self): ...            # GAVE_UP → AMENDED・why の無い GAVE_UP は BoardGap
    def test_row_without_state_reads_as_waiting(self): ...     # 欄 replan の無い fix_plan_item の行 → waiting に数える

class TestHeldReply(unittest.TestCase):
    def test_accepted_units_leave_duty_but_not_board_owed(self): ...
        # 控え {changes: [CLAMP の行]} を置いた偽の盤面（owed_units_but_asked は {MEAN, CLAMP}、withheld_by は {} に差す）
        # → fix_duty の owed は {MEAN}・excused[CLAMP] に "1 回目の修正の段で受け付けた"
    def test_with_held_merges_rows_by_unit(self):
        merged = conflict.with_held(b, {"changes": [mean_row()], "not_done": [], "fix_closure": {"status": "clean"}})
        self.assertEqual([c["unit_key"] for c in merged["changes"]], [CLAMP, MEAN])
        self.assertEqual(merged["fix_closure"], {"status": "clean"})
    def test_held_writes_are_kept(self): ...                   # 控えの bash_writes を held_writes が返す
    def test_held_reply_ignored_after_board_took_fix(self): ...  # state.outputs に今の周の p3.fix → held_reply は (None, パス)
```

- [ ] **Step 2: 落ちることを確かめる**

Run: `cd works/tests && PYTHONDONTWRITEBYTECODE=1 python3 -m unittest test_conflict_kinds.TestReplanState test_conflict_kinds.TestHeldReply`
Expected: FAIL（`AttributeError: … 'waiting'`）

- [ ] **Step 3: 状態と控えの口を書く**（どの状態も `set_replan` の 1 か所で移す。`gave_up` を持つ行は誰も作らないので、この Task の後も run の動きは変わらない）

- [ ] **Step 4: 通ることを確かめる**

Run: `cd works/tests && PYTHONDONTWRITEBYTECODE=1 python3 -m unittest test_conflict_kinds test_plan_scope && python3 -m unittest test_blk_fix_conflict.TestFixPlanItem test_blk_fix_conflict.TestFixPlanItemWholeItem`
Expected: PASS（前からの `fix_plan_item` の試験も全部）

- [ ] **Step 5: Commit**

```bash
git add works/.shared/core/conflict.py works/tests/test_conflict_kinds.py
git commit -m "feat(works): fix_plan_item の裁定の行に案の直しの状態（待つ・直した・諦めた）と、1 回目に受け付けた返答の控えの口を持たせる（226 Task 3）"
```

---

### Task 4: 諦めの道を 1 本にする（`replan.close`・`settle` と、持ち越しの道を消す）

この Task の後、`fix_plan_item` の単位は次の run へ持ち越されない。`h-rejudge`（と報告の組み立て）で諦めた単位として ask_human の道に載る（関所の答えの「上限で諦めた時」と同じ姿）。同じ run で直す道は Task 6〜9 で足す。

**Files:**
- Create: `works/.shared/core/replan.py`（この Task では `STOP_BY`・`CLOSE_WHY`・`HALTED_WHY`・`UNSETTLED`・`close`・`close_at`・`settle` だけ）
- Modify: `works/darkfactory/lib/line_edge.py`（`edge` の at `rejudge` の頭で `replan.settle`。`_replan_text` と `final_edge` の `replanned` を消す）
- Modify: `works/.shared/core/report.py`（REPLAN_HEAD・`replanned_lines`・`_replanned`・`_replanned_units`・`_plan_nums`・`_from_unit`・`decide_outcome` の `round_limit` の分かれ・`next_request` の fix_plan_item の行・冒頭 1 の節を消す。ask_human の行は `ruled_units` の全部の単位に、裁定の文を字のまま載せる。`build` の頭で `replan.close_at`）
- Modify: `works/tests/test_layers.py`（`MOD` に `"replan": (3, None)`）
- Create: `works/tests/test_replan.py`（HEAVY。`works/tests/tiers.py` の HEAVY に `"test_replan"` を足す）
- Modify（持ち越しを縛る試験を、諦めの道を縛る試験に書き換える）: `works/tests/test_blk_fix_conflict.py` の `TestFixPlanItemReport`・`TestFixPlanItemWholeItem`・`TestFixPlanItemBothUnits`（:1281 の 2 件の裁定の報告と次の依頼の試験）、`works/tests/test_report_head.py` の :122 と :556（`report._replanned` を `mock.patch.object` で差す 2 か所。差しを外し、試験の言う事を新しい道に合わせる）

**Interfaces:**
- Consumes: Task 3 の `conflict.waiting`・`set_replan`・`GAVE_UP`・`asked`・`human_lines`・`ruled_units`
- Produces（`replan`。L3。`entry`・`conflict`・`planmarks`・`recount`・`rolekit`・`board`・`gatemarks`・`accept` を import してよい。`report` と blk の lib は import しない）:
  - `STOP_BY = "works:replan"`
  - `CLOSE_WHY = "同じ run の中で案の直しを終えられなかった（案の段に戻るのは 1 run に 1 回）"`
  - `HALTED_WHY = "run が止まった（{by}: {reason}）ので、案の直しを終えなかった"`（止まった盤面で締める行の理由。`by`・`reason` は盤面の止めの物）
  - `UNSETTLED = "案の直しを待つ単位を残したまま修正の段を抜けようとした: {ids}"`
  - `close(b, why: str) -> list[str]` — `waiting(b)` の行を全部 `GAVE_UP`（`why`）にし、id を返す。待つ行が無ければ何もせず `[]`。
  - `close_at(board_dir) -> list[str]` — 盤面を `allow_halted` で開き、止まっていれば `HALTED_WHY`、そうでなければ `CLOSE_WHY` で `close`（何度呼んでも同じ。報告の組み立ては必ず走るので、`fixing` が落ちて `h-rejudge` が飛ばされた run でも待つ行が落ちない）。
  - `settle(board_dir, repo) -> dict` — `{"closed": [id…], "handed": bool}`。順: 1. `close_at(board_dir)`。2.（Task 5 で足す: 控えの渡し）。3. `waiting` の行が残れば `BoardGap(UNSETTLED.format(ids=…))`。
  - `line_edge.edge`: at が `rejudge` なら、止まっているかを見る前に `replan.settle(board_dir, repo)` を呼び、盤面を開き直す。
  - `report.build`: 盤面を読む前に `replan.close_at(board_dir)`。
  - `report.next_request`: `asked` の行ごとに、`ruled_units(r)` の単位ごとに `{"where": <単位>, "text": "<単位>（食い違いの申し出を人に回した——直さずに残した。裁定の文: <字のまま>。名指し <…>[。案の直し: <why>]）"}`。`_one_line` を通さない。
  - `report.decide_outcome`: `_replanned` の分かれを消す（諦めた単位は `_asked` で `needs_human`）。

- [ ] **Step 1: 落ちる試験を書く**

```python
# test_replan.py
from test_blk_fix_conflict import ReplanCase, only_clamp_reply, PLAN_TEXT, MEAN, CLAMP

class TestSettle(ReplanCase):
    def test_settle_closes_waiting_rows(self):
        self.replanned()
        self.assertTrue(self.accept_script(only_clamp_reply(), pass_="ruled")["ok"])
        got = replan.settle(self.board, self.repo)
        self.assertEqual(len(got["closed"]), 1)
        b = entry.open_board(self.board, allow_halted=True)
        self.assertEqual(conflict.waiting(b), [])
        self.assertIn(PLAN_TEXT, conflict.human_lines(b)[0])

    def test_unsettled_is_board_gap(self):
        self.replanned()
        with mock.patch.object(replan, "close", return_value=[]):
            with self.assertRaises(board.BoardGap) as cm:
                replan.settle(self.board, self.repo)
        self.assertIn("案の直しを待つ単位を残したまま", str(cm.exception))

    def test_closed_on_halted_board_names_the_stop(self): ...   # 止めた盤面 → 行の why が "run が止まった（" で始まる
    def test_report_build_closes_waiting_rows(self): ...        # h-rejudge を通らずに report.build → 待つ行が gave_up・next_request に PLAN_TEXT

    def test_no_new_count_constant(self):
        self.assertFalse([n for n in dir(replan) if "LIMIT" in n or n == "GIVE_UP_AFTER"])

# test_blk_fix_conflict.py（TestFixPlanItemReport を書き換える）
    def test_gave_up_unit_goes_to_gate_and_next_request_verbatim(self):
        self.replanned()
        self.assertTrue(self.accept_script(self.clamp_reply(), pass_="ruled")["ok"])
        replan.settle(self.board, self.repo)
        b = entry.open_board(self.board)
        got = line_edge.final_edge(b, self.repo, run_id="run-12", mode="when_needed", tests={"ok": True, "green": True})
        self.assertTrue(got["ask"])                                       # ask_human と同じく関所を開ける
        items = report.next_request(entry.open_board(self.board))
        self.assertTrue(any(i["where"] == MEAN and PLAN_TEXT in i["text"] for i in items), items)
        self.assertFalse(hasattr(report, "REPLAN_HEAD"))
    def test_outcome_is_needs_human_not_round_limit(self): ...
    def test_whole_item_units_each_get_a_row(self): ...                   # SHARED_ITEM: MEAN と CLAMP の両方の行（ruled_units）
```

- [ ] **Step 2: 落ちることを確かめる**

Run: `cd works/tests && PYTHONDONTWRITEBYTECODE=1 python3 -m unittest test_replan test_blk_fix_conflict.TestFixPlanItemReport`
Expected: FAIL（`ModuleNotFoundError: No module named 'replan'`）

- [ ] **Step 3: `replan.py` を書き、境の節と報告を繋ぎ替える**（報告の冒頭 1 と最後の関所の文の `replanned` の節は消すだけで、代わりの節は Task 7 の `replan.lines`）

- [ ] **Step 4: 通ることを確かめる**

Run: `cd works/tests && PYTHONDONTWRITEBYTECODE=1 python3 -m unittest test_replan test_blk_fix_conflict test_report_head test_layers test_report` と `WORKS_TESTS=fast nice -n 19 sh works/tests/run.sh` と `sh ~/.cache/works-dogfood/rootfences.sh`
Expected: PASS・失敗 0

- [ ] **Step 5: Commit**

```bash
git add works/.shared/core/replan.py works/.shared/core/report.py works/darkfactory/lib/line_edge.py works/tests/test_replan.py works/tests/tiers.py works/tests/test_layers.py works/tests/test_blk_fix_conflict.py works/tests/test_report_head.py
git commit -m "feat(works): fix_plan_item の単位を次の run へ持ち越さず、h-rejudge と報告の組み立てで締めて ask_human の道に合流させる（裁定の文は字のまま。226 Task 4）"
```

---

### Task 5: 待つ単位が在る間は `p3.fix` を渡さずに控える

**Files:**
- Modify: `works/blk-fix/scripts/accept.py`（手順 3 の前の分かれ 1 つ）
- Modify: `works/.shared/core/recount.py`（`fix_reply` を足し、`collect` が使う）
- Modify: `works/.shared/core/replan.py`（`settle` の手順 2 と `hand_held`）
- Modify: `works/.shared/core/report.py`（`p3.fix` を読む 3 か所——今の :280・:315〜318・:456 の `_output(b, "p3.fix")`——を `recount.fix_reply` に。`next_request` の not_done も同じ口）
- Test: `works/tests/test_replan.py`（class `TestHold`）

**Interfaces:**
- Consumes: Task 3 の `conflict.waiting`・`HELD_REPLY`・`held_reply`、Task 4 の `replan.settle`
- Produces:
  - 受け付け（`accept.py`）の決まり: 手順 2（`unitrows.take`）の後、`recount.accept_fix` の前に、`conflict.waiting(b)` が空でなければ、盤面に渡す形の返答（役の申告した `bash_writes` は残す）を `b.work(conflict.HELD_REPLY)` に書く（一時のファイルから `os.replace`）。続けて、受けた時と同じ 4 つの trace を書く: `writes.trace`・`TESTS_OP`（`ci_left` 付き）・`planscope.SCOPE_OP`（在る時）・`CLOSURE_OP`（行が在る時）。その上で trace に `HELD_OP = "fix_held"` を 1 行（`accept.py` の定数）書き、`{"ok": true, "done": true, "parked": true, "reason": "", "reason_file": "", "changes": [V1 の行]}` を返す。
  - `recount.fix_reply(b) -> tuple[dict, pathlib.Path]` — 今の周の盤面の `p3.fix` か、無ければ `conflict.held_reply` の控え（`bash_writes` を外した写し）。どちらも無ければ `Unreadable`。`collect` と報告はこれを読む（`fix_file` は読んだ方のパス）。
  - `replan.hand_held(board_dir, repo) -> bool` — 盤面が止まっておらず、今の周の `p3.fix` を受けておらず、控えが在れば、`bash_writes` を外した控えを `recount.accept_fix(控え, board_dir, "", repo)` で渡して真。盤面が受けなければ `b.stop("1 回目に受け付けた修正の返答を盤面が受けない: <理由>", by=STOP_BY)` して偽。渡す物が無ければ偽。
  - `replan.settle` の手順 2: `hand_held(board_dir, repo)`。返りの `handed` はその値。

- [ ] **Step 1: 落ちる試験を書く**

```python
class TestHold(ReplanCase):
    def test_waiting_unit_holds_fix_reply(self):
        self.replanned()
        r = self.accept_script(only_clamp_reply(), pass_="ruled")
        self.assertEqual((r["ok"], r.get("parked")), (True, True))
        b = entry.open_board(self.board)
        self.assertNotIn("p3.fix", b.state["outputs"])                    # 盤面に渡していない
        self.assertTrue(b.work(conflict.HELD_REPLY).is_file())
        self.assertEqual(recount.fix_reply(b)[1], b.work(conflict.HELD_REPLY))

    def test_hold_writes_accepted_traces(self):
        self.replanned(); self.accept_script(only_clamp_reply(), pass_="ruled")
        ops = trace_ops(self.board)                                       # trace.jsonl の op の並び
        self.assertLessEqual({accept_mod.TESTS_OP, accept_mod.HELD_OP}, set(ops))

    def test_settle_hands_held_reply(self):
        self.replanned(); self.accept_script(only_clamp_reply(), pass_="ruled")
        got = replan.settle(self.board, self.repo)
        self.assertTrue(got["handed"])
        b = entry.open_board(self.board)
        self.assertEqual([c["unit_key"] for c in recount._fix_output(b)[0]["changes"]], [CLAMP])

    def test_report_reads_held_reply_when_board_stopped(self): ...   # 控えを置いて盤面を止める → 報告の changes の行に CLAMP
    def test_settle_twice_hands_once(self): ...      # 2 度目の settle は handed False・trace の accept の行は 1 つ
    def test_no_waiting_hands_as_before(self): ...   # ask_human だけの盤面では今どおり受け付けが p3.fix を渡す（parked 無し）
```

- [ ] **Step 2: 落ちることを確かめる**

Run: `cd works/tests && PYTHONDONTWRITEBYTECODE=1 python3 -m unittest test_replan.TestHold`
Expected: FAIL（`parked` が無い・`fix_reply` が無い）

- [ ] **Step 3: 控えと渡しを書く**

- [ ] **Step 4: 通ることを確かめる**

Run: `cd works/tests && PYTHONDONTWRITEBYTECODE=1 python3 -m unittest test_replan test_blk_fix_conflict test_blk_fix test_report`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add works/blk-fix/scripts/accept.py works/.shared/core/recount.py works/.shared/core/replan.py works/.shared/core/report.py works/tests/test_replan.py
git commit -m "feat(works): 案の直しを待つ単位が在る間は修正の返答を盤面に渡さずに控え（受けた時と同じ trace を書く）、h-rejudge で渡す。報告は控えも読む（226 Task 5）"
```

---

### Task 6: 案の直しの役（`blk-plan` の replan の口）

**Files:**
- Modify: `works/.shared/core/replan.py`（束ね・指示書・受け付け・出口）
- Modify: `works/.shared/core/planmarks.py`（`gaps` に keyword `exists`）
- Modify: `works/blk-plan/blk-plan.yaml`（入力 `replan`。同じ script を回す節の全部——`r2-design-snap`・`r2-design-loop` の中の節（今の :44・:67・:129 の並び）・`plan-snap`・`plan-prep`・`plan-accept`・`plan-review-snap`・`plan-review-prep`・`plan-review-accept`・`plan-reads`・`collect`——の `with` に `replan: $INPUTS.replan`）
- Modify: `works/blk-plan/lib/planblk.py`（`snap`・`prep`・`main_accept`・`collect`・`collect_reads` の頭で `replan` の口へ回す 1 分岐ずつ。新しい関数 `design_only(b) -> str`＝今の `_design_part(b)` を公開した物）・`works/blk-plan/scripts/{snap,prep,accept,collect,reads}.py`（`OPTIONAL` に `INPUTS_REPLAN`。無い・空は今どおり）
- Test: `works/tests/test_replan.py`（class `TestReplanRoles`）・`works/tests/test_blk_plan.py`（:100 の入力の集合に `replan`、YAML と `INPUTS`・`OPTIONAL` の突き合わせ）

**Interfaces:**
- Consumes: Task 1 の `planmarks.approved_items`・`gaps`・`REVIEW_ASK`、Task 3 の `conflict.waiting`、`rolekit.with_done`・`parse_reply`・`given_up_reason`・`script_main`・`compose`、`accept.role_schema`、`gatemarks.narrow_gaps`・`gatemarks.split`、`entry.snapshot`
- Produces（`replan`）:
  - `TRIP_FILE = "replan.json"`（`b.work`。`{"round": n, "items": [行]}`。行は `{"item", "units", "rows", "old", "brief", "new", "new_marks", "review", "contract_changed", "human_faces", "ask", "answer", "result", "why"}`。まだ無い値は null か空。`new` は関所の決め手の欄を外した項目、`new_marks` は外した欄）
  - `PLAN_NODE = "replan.fix_plan"`・`REVIEW_NODE = "replan.plan_review"`（盤面に無い節の名。`rolekit.with_done` の控えと指示書の名 `prompt-replan.fix_plan.md`・`prompt-replan.plan_review.md`）
  - `ROLES = {"plan": PLAN_NODE, "plan-review": REVIEW_NODE}`
  - `material(b) -> dict` — `{"go": bool, "items": [番号…]}`。`waiting(b)` の行を、裁定の欄 `plan_items` の番号ごとに束ねて `TRIP_FILE` を書く（項目 1 つに行 1 つ。同じ項目の単位は `ruled_units` の和）。`old` は `planmarks.approved_items(b)[n-1]`（鍵 item を外す）。`TRIP_FILE` が今の周に在れば書き直さない（再開）。今の周の `p3.fix` を受けている・盤面が止まっている・待つ行が無いなら go False。
  - `snap(board_dir, role, repo) -> dict` — `{"ok", "go", "snapshot_file"}`。`plan`: `new` の無い項目が在れば go。`plan-review`: `new` が在り `review` の無い項目が在れば go。
  - `prep(board_dir, role, repo, *, head: str, design_part: str = "") -> dict` — `{"prompt_file", "attempt", "out_path", "node", "already"}`（`planblk.prep` と同じ鍵）。`head` は呼び手の `planblk.head(role, excluded_file, lib_docs)` の文（`plan` の頭は `planmarks.HEAD` を既に含むので、`replan` は足さない）。`design_part` は `plan-review` の時だけ `planblk.design_only(b)`（独立設計の節だけ。全項目の欄を貼る `planmarks.review_section` は入れない）。指示書は次だけを、この順で並べる。
    1. `head`
    2. `plan` なら `REPLAN_ASK`、`plan-review` なら `design_part` と `REVIEW_ASK_REPLAN` と `planmarks.REVIEW_ASK`
    3. 項目ごとの節: 番号・unit_keys（字のまま）・前の項目の JSON・brief のパス・申し出の行（`between`・`why_both_cannot_hold`・`kind`・`which_is_right`）・裁定の文（字のまま）・`plan-review` なら直した項目の JSON（`new` に `new_marks` を戻した形）
    
    ほかの項目・判定の全文・差分・前の会話は貼らない。拒否の後は `rolekit.compose` の 1 行目で前の理由のファイルを名指す。
  - `REPLAN_ASK`（字のまま）: 「承認済みの修正案の項目のうち、下に貼った項目だけを直せ。修正の段で修正役がこの項目の誤りを申し出て、裁定役が fix_plan_item（案の項目そのものの誤り）と裁いた。申し出の文と裁定の文を読み、裁定の文が名指した所を直した項目を返せ。plan は下に貼った項目と同じ数・同じ順で、各項目の unit_keys は貼った文字列を一字も変えずに写せ（番号で書かない）。ほかの項目は返すな。直した項目は事前審査に掛かり、約束の欄（unit_keys・narrows・removes・allowed_paths・out_of_scope・rewrite_tests・tests の behavior）を変えた時は人の関所に出る。」
  - `REVIEW_ASK_REPLAN`（字のまま）: 「下は承認済みの修正案の項目の前の形と、修正の段の申し出と裁定を受けて修正案の役が直した形。直した形が裁定の文の指摘を直したか、新しい後退（regression）や方針とのぶつかり（policy）を作らないかを見よ。前の形に在った穴を挙げ直さない。穴は faces に挙げよ。」
  - `accept_reply(board_dir, role, raw, repo) -> dict` — `{"ok", "done", "give_up", "reason", "node"}`（`design.accept_reply` と同じ形。`rolekit.with_done(…, give_up_after=rolekit.GIVE_UP_AFTER)`）。入口は `rolekit.script_main(…, ("INPUTS_REPLY",), fence=True, take="plan")`（r2-design と同じ包み。拒否の理由は `reason_file` に書く）。
    - `plan` の受け付け: 次の誤りを全部並べて 1 回で拒む（頭 `REPLAN_REJECT = "直した項目の返答に誤りが在る（下の行を全部直して出し直せ）:"`）。誤りが無ければ、項目ごとに `gatemarks.split` で決め手の欄を外した `new` と、外した `new_marks` を `TRIP_FILE` に置く。
      - 数が違う: `plan[] は {k} 項目（貼った項目の数）`
      - unit_keys が違う: `plan[{i}].unit_keys が貼った {old} と違う（一字も変えずに写す）`
      - `planmarks.gaps` の行。ただし受け入れのテストが「既に在る」かは、作業ツリーでなく修正の起点の版（盤面の `state.inputs.review_rev`）の木で見る（TDD の輪で止めた単位は、書いたテストを作業ツリーに残す。同じ id のまま手段の欄だけを直す返答を拒まない）。`planmarks.gaps(reply, repo, *, exists=None)` に、その版の木でテストの定義を引く口を渡す（`exists` が None なら今どおり作業ツリー）
      - `gatemarks.narrow_gaps` の行
      - 型（`accept.role_schema("p2.fix_plan")`）の外れ
    - `plan-review` の受け付け: 型（`accept.role_schema("p2.plan_review")`）を当て、項目ごとに `review` を置く。
    - どちらも、役を起こす前の作業ツリーの写しと比べ、変わっていれば拒む（`planblk` と同じ読むだけの役の決まり）。
  - `collect(board_dir) -> dict` — `blk-plan` の出口と同じ鍵 `{"ok": true, "plan_file": "", "review_file": "", "asks_human": false, "gate_kinds": [], "reads_file": <reads の索引か "">, "gave_up": false, "reason_file": ""}`（役の諦めは盤面を止めず、Task 7 の `gate` が項目ごとに読む）。
  - `planblk`: `replan` の入力が空でなく `"null"` でもなければ、`snap`・`prep`・`main_accept`・`collect` を `replan` の同名の口へ回す（`prep` は `head`・`design_part` を組んで渡す）。独立設計の輪は今どおり `design.due` で飛ぶ。`collect_reads` は replan の時、役の名 `replan-plan`・`replan-plan-review` で読んだ証拠を `reads-replan-plan.json`・`reads-replan-plan-review.json` に、索引を `reads-replan-block.json` に書く（1 回目の `reads-plan.json` などを上書きしない）。

- [ ] **Step 1: 落ちる試験を書く**

試験の helper（`test_replan.py` に置き、Task 7〜9 も使う）:
- `fixed_item()`: 前の項目 1 の写しで、手段の欄だけを直した物。`red_kind_fixed()` は受け入れのテストの `red_kind` を `"exception"` に、`red_why` を今のコードで赤になる理由に直した物（224b の型）。
- `wider_paths()`: `allowed_paths` に 1 行を足した物（約束の欄が変わる。195b の型）。`clamp_item()` は項目 2 の写し。
- `no_faces()`: 事前審査の空の返答（`faces: []`・`shrink: []`・型の残りの欄）。`only_mean_reply()` は `only_clamp_reply` の MEAN 版。
- `TripCase(ReplanCase)`: setUp は「`replanned()` → 1 回目の受け付け → `replan.material`」まで済ませた盤面。`self.trip(new=, review=)` は 2 つの役の支度（`planblk.prep(…, replan="true")`）と `accept_reply` を通す。`self.approve(new)` はそれに `gate` と `answer(self.board, self.repo, None)` を足す。`self.play_role(role, reply)` は 1 つの役の支度と `accept_reply`。

```python
class TestReplanRoles(ReplanCase):
    def setUp(self):
        super().setUp()
        self.replanned(); self.accept_script(only_clamp_reply(), pass_="ruled")
        self.b = entry.open_board(self.board)

    def prep(self, role):
        return planblk.prep(self.board, role, self.repo, replan="true")

    def test_material_groups_by_item(self):
        got = replan.material(self.b)
        self.assertEqual(got, {"go": True, "items": [1]})
        trip = json.loads(self.b.work(replan.TRIP_FILE).read_text(encoding="utf-8"))
        self.assertEqual(trip["items"][0]["units"], [MEAN])

    def test_prompt_has_only_the_item_and_texts(self):
        replan.material(self.b)
        p = pathlib.Path(self.prep("plan")["prompt_file"]).read_text(encoding="utf-8")
        self.assertIn(PLAN_TEXT, p)                                  # 裁定の文（字のまま）
        self.assertIn(MEAN, p)
        self.assertNotIn(CLAMP, p)                                    # ほかの項目の単位を貼らない
        self.assertIn("一字も変えずに写せ", p)
        self.assertEqual(p.count(planmarks.HEAD), 1)                  # 欄の節を 2 度貼らない

    def test_reply_limited_to_handed_items(self):
        replan.material(self.b); self.prep("plan")
        two = {"plan": [fixed_item(), clamp_item()]}                 # 項目を足した返答
        got = replan.accept_reply(self.board, "plan", json.dumps(two), self.repo)
        self.assertFalse(got["ok"]); self.assertIn("plan[] は 1 項目", got["reason"])
        renamed = {"plan": [{**fixed_item(), "unit_keys": [1]}]}    # 番号で書いた
        got = replan.accept_reply(self.board, "plan", json.dumps(renamed), self.repo)
        self.assertIn("一字も変えずに写す", got["reason"])

    def test_same_test_id_left_in_tree_is_accepted(self): ...
        # 作業ツリーに受け入れのテスト test_mean_of_two を書いておく（TDD の輪で止めた単位の残り）→ 同じ id で red_kind だけ直した返答が通る
    def test_good_reply_is_stored_not_swapped(self): ...
        # 正しい返答 → TRIP_FILE の new に入り（narrows の決め手の欄は new_marks へ）、planmarks.approved_items はまだ前の項目
    def test_third_rejection_gives_up(self): ...       # 3 回拒むと done・give_up が真（GIVE_UP_AFTER の輪のまま）
    def test_review_role_sees_design_only_and_both_forms(self): ...
        # 事前審査の指示書に独立設計の節と前後の項目、ほかの項目の欄（planmarks.REVIEW_HEAD の節）は無い
    def test_replan_reads_do_not_overwrite_planning_reads(self): ...
```

- [ ] **Step 2: 落ちることを確かめる**

Run: `cd works/tests && PYTHONDONTWRITEBYTECODE=1 python3 -m unittest test_replan.TestReplanRoles`
Expected: FAIL（`AttributeError: module 'replan' has no attribute 'material'`）

- [ ] **Step 3: 口を書き、`blk-plan` を配線する**（`planning` の include は `replan` を渡さないので今どおり）

- [ ] **Step 4: 通ることを確かめる**

Run: `cd works/tests && PYTHONDONTWRITEBYTECODE=1 python3 -m unittest test_replan test_blk_plan test_yaml_rules test_script_contract test_layers test_plan_fields`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add works/.shared/core/replan.py works/.shared/core/planmarks.py works/blk-plan works/tests/test_replan.py works/tests/test_blk_plan.py
git commit -m "feat(works): 案の直しの役に誤りと裁かれた項目・申し出・裁定の文だけを渡し、返答を渡した項目に限る（blk-plan の replan の口。226 Task 6）"
```

---

### Task 7: 人の関所の 1 つの決まりと答え（`replan.gate`・`answer`・`lines`）

**決まり（1 つ）:** run の中で直した項目は、約束の欄が承認済みの物と字のまま同じで（`planmarks.contract_diff` が空。narrows は決め手の欄を外して比べる）、事前審査が人に聞く種類の穴（写しの rules の `HUMAN_FACE_KINDS`: regression・policy）を挙げなかった時だけ、人に聞かずに通す。それ以外は関所 `replan-gate` で人に聞く。役には決めさせず、コードが欄を比べて決める。決定 2（約束の欄の表）は欄の決まりで、2 つ目の条件（人に聞く種類の穴）は今の `policy-gate` と同じ扱いを残した物（外れ D2）。

**Files:**
- Modify: `works/.shared/core/replan.py`
- Modify: `works/.shared/core/report.py`・`works/darkfactory/lib/line_edge.py`（`lines` を並べる）
- Test: `works/tests/test_replan.py`（class `TestGateRule`・`TestAnswer`）

**Interfaces:**
- Consumes: Task 1 の `planmarks.contract_diff`・`amend`、Task 3 の `conflict.set_replan`・`AMENDED`・`GAVE_UP`、Task 4 の `close`、Task 5 の `hand_held`、Task 6 の `TRIP_FILE`・`PLAN_NODE`・`REVIEW_NODE`、`rolekit.given_up_reason`、写しの rules の `HUMAN_FACE_KINDS`（`board.rules_module(pathlib.Path(b.state["graph"]))` から読む）
- Produces:
  - `GATE_FILE = "replan-gate.md"`・`NOTES_FILE = "replan-notes.md"`・`HUMAN_KIND = "replan"`（`process.human_items` の行の kinds。node は `STOP_BY`）・`GATE_BY = "human:replan-gate"`（stop で止めた盤面の by。頭が `human:` なので報告の結末は `stopped_by_human`）
  - `PLAN_GAVE_UP_WHY = "修正案の役の直しが 3 回とも拒まれた: {reason}"`・`REVIEW_GAVE_UP_WHY = "事前審査の役の返答が 3 回とも拒まれた: {reason}"`・`NO_GATE_WHY = "人に聞く直しなのに関所の答えが無い（関所が開かなかった）"`・`STOPPED_WHY = "人が関所 replan-gate で run を止めた: {text}"`
  - `AMEND_HEAD = "同じ run の中で直した修正案の項目"`
  - `gate(b, *, run_id: str) -> dict` — `{"ask": bool, "gate_text": str, "gate_file": str}`。`new` の無い項目と `review` の無い項目は、その場で諦める（`set_replan(…, GAVE_UP, why=PLAN_GAVE_UP_WHY / REVIEW_GAVE_UP_WHY)`。理由は `rolekit.given_up_reason`）。残りの項目ごとに `contract_changed`（`contract_diff(old, new)`。どちらも決め手の欄の無い形）・`human_faces`（その種類の穴の key）・`ask`（どちらかが在る）を `TRIP_FILE` に置く。`ask` の項目が 1 つでも在れば `GATE_FILE` を書く。文の頭の 3 行は字のまま次のとおり。
    1. `案の項目を run の中で直した（{k} 件。人に聞くのは {m} 件）。人に聞く理由: 約束の欄が変わった・事前審査が人に聞く穴を挙げた`
    2. `決めてほしいこと: 直した項目を使って修正に戻るか、run を止めるか（止めても 1 回目に直した単位の差分は報告に残る）`
    3. `答え方: continue "<一言>" で直した項目を使って修正に戻る。stop "<理由>" で run を止める。approve は continue、reject は stop と同じ`
    
    その後に、聞く項目ごとの節を置く。節が持つ物: 約束の欄の変化の名・人に聞く穴・申し出の文・裁定の文（字のまま）・前の項目と直した項目の JSON。
  - `answer(board_dir, repo, gate: dict | None) -> dict` — `{"returned": [単位…], "plan_file": str, "notes_file": str, "stop": bool, "why": str}`。
    - `gate` の decision が stop・reject: `process.human_items` に 1 行（answer は `"stop"`）を足し、待つ行を `STOPPED_WHY` で締め（`close`）、`hand_held(board_dir, repo)` で 1 回目の控えを盤面に渡してから、盤面を `b.stop(<一言か STOPPED_WHY>, by=GATE_BY)` で止める。返りは `stop: true`・`returned: []`。
    - そうでない時の項目ごとの扱い: `ask` が偽の項目は直しを採る。`ask` が真の項目は、`gate` の decision が continue・approve なら採り、`gate` が None なら `NO_GATE_WHY` で諦める。
    - 採った項目は、まとめて `planmarks.amend(b, {n: new に new_marks を戻した項目}, repo)` で差し替える。その項目の行は `set_replan(…, AMENDED)` に、`TRIP_FILE` の `result` は `"amended"` にする。
    - 関所が開いた時は `process.human_items` に 1 行を足す: `{round, kinds: [HUMAN_KIND], asked: [GATE_FILE], answer: "continue"|"stop", note: 一言, node: STOP_BY}`。
    - `NOTES_FILE` には、人の一言と、採った項目の事前審査の穴のうち人に聞く種類でない物を書く（無ければ書かずに ""）。
    - `plan_file` は盤面の今の周の `p2.fix_plan` の出力の絶対パス（事前審査の返答 `p2.plan_review.json` が隣に在り、修正役の決まり `blk-fix/rules/direct.md` の言うとおり。直した項目は切り直した brief と `NOTES_FILE` で届く）。採った項目が無ければ ""。
    - `TRIP_FILE` の全項目に `result` が在れば（stop の後も）、何も書き換えずに前の結果を返す（Archon の再開）。
  - `lines(b) -> list[str]` — `TRIP_FILE` の項目ごとに 1 行: `案の項目 {n}（単位 {units}）: {直した——人が承認した / 直した——聞かずに通した（手段の欄だけ） / 直さずに諦めた: {why}}`。最後の関所の文（`line_edge.final_edge`）と報告の冒頭 1 が、見出し `AMEND_HEAD` の下に並べる（関所を開ける理由には数えない）。

- [ ] **Step 1: 落ちる試験を書く**

```python
class TestGateRule(TripCase):
    def test_means_only_passes_without_asking(self):     # 224b・225 の型（red_kind・id のクラス）
        self.trip(new=red_kind_fixed(), review=no_faces())
        got = replan.gate(entry.open_board(self.board), run_id="r")
        self.assertFalse(got["ask"])

    def test_contract_change_asks(self):                 # 195b の型（allowed_paths を広げた）
        self.trip(new=wider_paths(), review=no_faces())
        got = replan.gate(entry.open_board(self.board), run_id="r")
        self.assertTrue(got["ask"])
        self.assertIn("allowed_paths", pathlib.Path(got["gate_file"]).read_text(encoding="utf-8"))
        self.assertTrue(got["gate_text"].startswith("案の項目を run の中で直した（1 件。人に聞くのは 1 件）"))

    def test_narrows_with_marks_is_not_a_contract_change(self): ...  # 前と同じ narrows に決め手の欄を足した返答 → 聞かない
    def test_human_kind_face_asks(self): ...             # 手段の欄だけの直しでも、事前審査が regression の穴を挙げたら聞く

class TestAnswer(TripCase):
    def test_approved_item_returns_units_and_swaps(self):
        self.trip(new=red_kind_fixed(), review=no_faces())
        replan.gate(entry.open_board(self.board), run_id="r")
        got = replan.answer(self.board, self.repo, None)
        self.assertEqual(got["returned"], [MEAN])
        b = entry.open_board(self.board)
        self.assertEqual(planmarks.approved_items(b)[0]["tests"][0]["red_kind"], "exception")
        self.assertNotIn(MEAN, conflict.held_by_rulings(b))
        self.assertEqual(got["plan_file"], str(b.dir / b.state["outputs"]["p2.fix_plan"]["file"]))

    def test_stop_stops_board_and_keeps_first_pass(self):
        self.trip(new=wider_paths(), review=no_faces())
        replan.gate(entry.open_board(self.board), run_id="r")
        got = replan.answer(self.board, self.repo, {"decision": "stop", "text": "範囲が広い"})
        self.assertTrue(got["stop"])
        b = entry.open_board(self.board, allow_halted=True)
        self.assertEqual(report.stop_outcome(b)[0], "stopped_by_human")
        self.assertEqual([c["unit_key"] for c in recount.fix_reply(b)[0]["changes"]], [CLAMP])   # 1 回目の直しは残る
        self.assertIn("人が関所 replan-gate で run を止めた", conflict.human_lines(b)[0])

    def test_gave_up_paths_reach_ask_human_verbatim(self):
        for case in ("no_gate", "plan_gave_up", "review_gave_up"):
            with self.subTest(case): ...   # どれも returned は空・行は gave_up・human_lines に PLAN_TEXT と why

    def test_answer_twice_is_idempotent(self): ...       # 2 度目の answer は同じ返り・AMEND_OP の行は増えない・human_items は 1 行
    def test_lines_name_each_item(self): ...
```

- [ ] **Step 2: 落ちることを確かめる**

Run: `cd works/tests && PYTHONDONTWRITEBYTECODE=1 python3 -m unittest test_replan.TestGateRule test_replan.TestAnswer`
Expected: FAIL（`AttributeError: … 'gate'`）

- [ ] **Step 3: 決まりと答えを書き、`final_edge` と報告の冒頭 1 に `lines` を並べる**

- [ ] **Step 4: 通ることを確かめる**

Run: `cd works/tests && PYTHONDONTWRITEBYTECODE=1 python3 -m unittest test_replan test_blk_fix_conflict.TestFixPlanItemReport test_report`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add works/.shared/core/replan.py works/.shared/core/report.py works/darkfactory/lib/line_edge.py works/tests/test_replan.py
git commit -m "feat(works): 直した項目を人に聞かずに通すのは約束の欄が同じで人に聞く穴が無い時だけ、の 1 つの決まりと関所の答え（stop は run を止める。226 Task 7）"
```

---

### Task 8: 2 回目の修正の段（`blk-fix` の回の印・控えの行・run の全部の輪の凍結）

この Task は形 A・B（Task 9）のどちらでも使う口だけを作る。YAML の配線は Task 9。

**Files:**
- Modify: `works/blk-fix/lib/fixrules.py`（回の印をファイルの名に通す・控えの節）
- Modify: `works/blk-fix/scripts/{fix_prep,accept,rule_prep,rule_accept,reads}.py`（`OPTIONAL` に `INPUTS_PASS_TAG`・`INPUTS_INCLUDE_ID`。無い・空は今どおり）
- Modify: `works/blk-fix/scripts/accept.py`（手順 -2 に控えの書き込みの申告、手順 2 の前に `conflict.with_held`、手順 1b・-2・1c・1d を run の全部の輪に）
- Modify: `works/blk-fix/lib/tddloop.py`（`states`・`suite_made_all`・`frozen_problems` の 2 つの keyword）
- Modify: `works/.shared/core/conflict.py`（`write_rulings`・`RULINGS_FILE`・`PARKED_REPLY` の名に回の印）
- Test: `works/tests/test_replan.py`（class `TestSecondPass`）・`works/tests/test_blk_fix_tdd.py`（新しい class `TestCrossLoopFreeze`）・`works/tests/test_blk_fix.py`（`OPTIONAL` の突き合わせ）

**Interfaces:**
- Consumes: Task 3 の `conflict.with_held`・`held_reply`・`held_writes`・`accepted_units`・`amended_keys`、Task 7 の `answer` の返り
- Produces:
  - 回の印: `fixrules.tagged(name: str, pass_tag: str) -> str` — `pass_tag` が空なら `name` のまま、在れば拡張子の前に `.<pass_tag>`（`prompt-p3_fix.md` → `prompt-p3_fix.refit.md`）。指示書・その隣の `.delivered.json`・`.variants.json`・`.full.md`・`.delta.md`・裁定の後の尾（`RULED_TAIL`）・拒否の理由の glob（`REJECT_GLOB`）・裁定の文（`conflict.RULINGS_FILE`）・申し出の回の控え（`conflict.PARKED_REPLY`）の名を、この 1 つの口で作る。2 回目の段は自分の数えから始まり、3 回の諦め（keep-essence 4）を回ごとに数える。2 回目の最初の指示書は、新しい役が見ていない会話への差分（delta）にならない。
  - `tddloop.states(board_dir) -> list[pathlib.Path]` — 盤面の根の `tdd-<k>/state.json` を番号順に。
  - `tddloop.suite_made_all(board_dir) -> set` — 全部の輪の `suite_made` の和。手順 -2・1c・1d はこれを読む。
  - `tddloop.frozen_problems(state_file, repo, allowed=(), *, since=None, skip_spans=())` — `since` が在れば、凍結の基準をその木（新しい輪の状態の `handoff`＝新しい輪が始まった時の木）のファイルにする（新しい輪が同じファイルに足したテストは、新しい輪の凍結で見る）。`skip_spans` は `[(パス, 関数の名)]` で、その関数の範囲（`tddloop._function_span`）の変更だけを通す。
  - 受け付けの手順 1b: 今の輪の状態は今どおり。古い輪の状態には `since=<今の輪の状態の handoff>`・`skip_spans=<直した項目の単位（conflict.amended_keys）の、古い輪の受け入れのテストの関数>` を渡す。
  - 受け付けの手順 -2: 役の `bash_writes` に `conflict.held_writes(b)` を足して突き合わせる（1 回目の Bash の書き込みを 2 回目で拒まない）。
  - 受け付けの手順 2 の前: `reply = conflict.with_held(b, reply)`（-3〜1d の検査は役の返答そのものに当てる。合わせた返答を手順 2・3 と盤面に渡す）。
  - `fixrules.HELD_HEAD = "## 1 回目の修正の段で受け付けた返答（機械が貼った）"`・`fixrules.HELD_ASK`（字のまま）: 「控え {path} を Read で読め。直す義務は下の『直す義務の単位』（案を直して戻った単位）だけで、控えの単位の行は機械が足す——changes と not_done に控えの単位を書くな。changes と not_done の外の欄（fix_closure・mechanism_changed・plan_faces など）は、1 回目と今回を合わせた差分の全体について書け（控えの値から始めよ）。」。`conflict.held_reply` が控えを返す時だけ、修正役の指示書（`fix_parts`）の brief の節の後に置く。
  - `INPUTS_INCLUDE_ID`（既定 `"fixing"`）: 読んだ証拠（`recount.READS` の include の段）をこの名で引く。

- [ ] **Step 1: 落ちる試験を書く**

```python
class TestSecondPass(TripCase):
    def test_second_pass_duty_is_returned_units_and_merges(self):
        self.approve(red_kind_fixed())                       # Task 7 の answer まで通した盤面
        owed, excused = conflict.fix_duty(entry.open_board(self.board))
        self.assertEqual(owed, {MEAN}); self.assertIn("1 回目の修正の段で受け付けた", excused[CLAMP])
        self.edit_tree(MEAN_FIX)
        r = self.accept_script(only_mean_reply(), pass_="first", pass_tag="refit")
        self.assertTrue(r["ok"], r)
        out, _ = recount._fix_output(entry.open_board(self.board))
        self.assertEqual(sorted(c["unit_key"] for c in out["changes"]), sorted([MEAN, CLAMP]))
        self.assertIn("len(xs)", (self.repo / "stats.py").read_text(encoding="utf-8"))   # 差分が空でない

    def test_second_pass_counts_its_own_tries(self): ...          # 1 回目の拒否の理由・delivered が在っても、回の印の付いた 1 回目は iteration 1・前の理由を名指さない
    def test_second_pass_rejects_rows_for_accepted_units(self): ...   # 役が CLAMP の行を書けば check_excused_units が拒む
    def test_first_pass_bash_writes_pass_second_check(self): ...  # 控えの bash_writes のファイルを 2 回目の突き合わせが拒まない
    def test_fix_prompt_names_held_reply(self): ...               # HELD_HEAD と控えのパス

class TestCrossLoopFreeze(LoopCase):
    def test_second_pass_cannot_touch_first_loop_frozen_tests(self): ...  # tdd-1 が凍らせた既存のテストを 2 回目で変える → 拒む
    def test_second_loop_may_add_test_to_first_loop_file(self): ...       # tdd-2 が tdd-1 の凍らせたファイルに新しいテストを足す → 通す
    def test_amended_units_old_test_span_is_not_frozen(self): ...         # 直した項目の単位の tdd-1 の受け入れのテストの関数だけは書き直してよい
```

- [ ] **Step 2: 落ちることを確かめる**

Run: `cd works/tests && PYTHONDONTWRITEBYTECODE=1 python3 -m unittest test_replan.TestSecondPass test_blk_fix_tdd.TestCrossLoopFreeze`
Expected: FAIL

- [ ] **Step 3: 書く**（`tdd-start` は変えない。2 回目の直す義務が戻った単位だけになるので、輪は戻った単位だけを振り分ける）

- [ ] **Step 4: 通ることを確かめる**

Run: `cd works/tests && PYTHONDONTWRITEBYTECODE=1 python3 -m unittest test_replan test_blk_fix test_blk_fix_tdd test_blk_fix_conflict test_tdd_suite test_script_contract`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add works/blk-fix works/.shared/core/conflict.py works/tests/test_replan.py works/tests/test_blk_fix_tdd.py works/tests/test_blk_fix.py
git commit -m "feat(works): 2 回目の修正の段は回の印で自分の数えから始め、戻った単位だけを直し、1 回目に受け付けた行を機械が合わせて渡す。凍結は run の全部の輪で効く（226 Task 8）"
```

---

### Task 9: 線に繋ぐ（Archon の測りで形を決める）と 224b・225 の型の筋書き

**始める前に（運び役の測り）:** 運び役が Archon v0.11.1 で、loop_group を持つブロックを 2 度 include する最小の工程を回し、結果を `.superpowers/sdd/2026-10-03-in-run-replan/progress.md` に書く。測る事:
1. 2 つ目の include の輪の中の節の出力の参照（例: `$fix-prep.output.prompt_file`）と出来事の `step_name` が、1 つ目の include の物と混ざらないか（`tests/test_line.py:73-84` の記録では、dry-run は輪の中の節に include の頭を付けない）。
2. include の最上段（輪の外）に置いた approval の節が、線の最上段の関所と同じに止まり、答えが `with: {from: …}` で後ろへ渡るか（形 B だけが使う。`blk-spec` の `spec-gate` と同じ置き方）。

測りの結果で形を選ぶ: 1 が混ざらないなら **形 A**。混ざるなら **形 B**（その時は 2 も確かめる。2 が止まらないなら、実装に入らずに運び役へ返す）。どちらの形でも、`replan`・`conflict`・`planmarks`・`planbrief`・`fixrules`・`accept` の口（Task 1〜8）はそのまま使う。

**Files（両方の形）:**
- Modify: `works/darkfactory/darkfactory.yaml`・`works/darkfactory/lib/line_edge.py`・`works/tests/linekit.py`（`LINE_ORDER` と `Line.run`）・`works/tests/test_line.py`（`LineShapeCase`、`stub_keys` の試験 :223・:227・:325、:404〜413 の fixtures の値の試験）・`works/tests/test_line_a.py`（:573 の trail の切り出し）・`works/darkfactory/fixtures/*.stubs.yaml`（13 本の全部。新しく走りうる節の stub と、走らない筋書きでの新しい節の go 偽）
- Test: `works/tests/test_replan.py`（class `TestLineReplay`）・`works/tests/test_edge.py`（形 A の新しい at の配線）

**形 A（測り 1 が混ざらない時）: 線に 6 節を足し、`blk-plan` と `blk-fix` を 2 度目の include で使う**
- 新しい境の節は、どれも今の境の節と同じ形: `script: edge`・`runtime: uv`・`timeout: 1728000000`・`trigger_rule: none_failed_min_one_success`・`with` に 7 つ（`at`・`judged: "null"`・`premised: "null"`・`gate`（下以外は `"null"`）・`tests: "null"`・`adapter: $start.output.adapter`・`final_gate: $INPUTS.final_gate`）・出口の型は今の境の節と同じ欄の全部。
  - `h-replan`: `at: "replan"`・`depends_on: [start, h-fix, fixing]`。中身は `go = replan.material(b)["go"]`。
  - `replanning`: `include: blk-plan`・`depends_on: [h-replan]`・`when: "$h-replan.output.go == true"`・`with: {judgment_file: $h-replan.output.judgment_file, base_rev: $start.output.base_rev, policy_paste: $start.output.policy_paste, policy_path: $start.output.policy_path, include_id: replanning, replan: "true"}`。
  - `h-regate`: `at: "regate"`・`depends_on: [start, h-replan, replanning]`。中身は `replan.gate(b, run_id=…)`（`ask`・`gate_text`・`gate_file`）。`TRIP_FILE` が無い周は何もせず ask 偽。
  - `replan-gate`: approval。`depends_on: [h-regate]`・`when: "$h-regate.output.ask == true"`・decisions は approve・continue・stop・reject。message（字のまま）:
    ```
    修正の段で誤りと裁いた修正案の項目を、run の中で直した。約束の欄が変わったか、事前審査が人に聞く穴を挙げた。
    全文と答え方: $h-regate.output.gate_file（Read して答える）。
    continue "<一言>" で直した項目を使って修正に戻る。stop "<理由>" で run を止める（1 回目に直した単位の差分は報告に残る）。approve は continue、reject は stop と同じ。
    ```
  - `h-refit`: `at: "refit"`・`depends_on: [start, h-regate, replan-gate]`・`gate: {from: $replan-gate.output, if_skipped: null}`。中身は `replan.answer(board_dir, repo, gate)`。返りの `stop` が真なら（盤面は `answer` が止めた）`stop: true`・`go: false`・`why`。そうでなければ `go` は「`returned` が空でない」かつ「`p3.fix` が盤面で待っている」。`open_units` は `returned` の JSON。ほかに `plan_file`・`notes_file` と、h-plan の控えからの `judgment_file` を返す。`TRIP_FILE` が無い周は go 偽。
  - `refitting`: `include: blk-fix`・`depends_on: [h-refit]`・`when: "$h-refit.output.go == true"`。`with` は `fixing` と同じ鍵で、`open_units`・`plan_file`・`notes_file`・`judgment_file` は `$h-refit.output.*`。足すのは `include_id: refitting`・`pass_tag: refit`（`blk-fix` の入力に `include_id`（既定 `fixing`）・`pass_tag`（既定 `""`）を足し、Task 8 の script の `OPTIONAL` へ渡す）。
  - `h-rejudge` の `depends_on: [start, h-fix, fixing, h-refit, refitting]`（`replan.settle` は Task 4 のまま）。
- 役の印: 2 つ目の include の役の節は 1 つ目と同じ印（`works-node: plan`・`fix` など）を持つ。`test_role_marks_unique` は「印の名はブロックをまたいで一意」を縛るので、同じブロックを 2 度 include した時に同じ印が 2 度数えられないよう、ブロックごとに 1 度数える形に直す。包みが印の名で会話を置くので、`fix-ruled`（`continue=fix`）が 2 回目の段では 2 回目の `fix` の会話を継ぐことを、筋書きの試験で確かめる（包みの会話の置き場の中身を読む）。
- `stub_keys` は、測りで分かった名前空間の形（輪の中の節に include の頭が付くか）に合わせて直す。

**形 B（測り 1 が混ざる時）: 2 度目の include をやめ、`blk-fix` の 1 つの include に案の直しと 2 回目の段を、回の入力で載せる**
- 線は今のまま（`fixing` の 1 つの include。新しい線の節は無い）。`h-rejudge` の `replan.settle` は Task 4 のまま。
- `blk-fix.yaml` の `fix-ruled-loop` の後、`clean` の前に、輪の中の id がブロックの中で一意な節を足す。どれも今の script を、`with` の回の入力（`stage`・`pass_tag: refit`）で回す:
  1. `replan-material`（新しい script `replan_step`・`stage: material`）: `replan.material` の go。
  2. `replan-snap` → `replan-loop`（輪の中: `replan-prep`・役 `replan`（印 `works-node: replan`。`plan` の節と同じ型・道具・柵）・`replan-accept`）。
  3. `replan-review-snap` → `replan-review-loop`（輪の中: `replan-review-prep`・役 `replan-review`（印 `works-node: replan-review`。`plan-review` の節と同じ model・effort・型）・`replan-review-accept`）。
  4. `replan-ask`（`stage: gate`）: `replan.gate` の `ask`・`gate_file`。
  5. `replan-gate`: approval（ブロックの最上段。輪の外）。message は形 A と同じ字。
  6. `replan-answer`（`stage: answer`・`gate: {from: $replan-gate.output, if_skipped: null}`）: `replan.answer` の返り。`stop` なら後ろの 2 回目の節は `when` で飛ぶ。
  7. 2 回目の段: `tdd2-start`・`tdd2-loop`・`fix2-loop`・`conflict2-check`・`rule2-loop`・`fix2-ruled-loop`。中身は 1 回目の節と同じ script・同じ型で、`with` に `pass_tag: refit` と `open_units: $replan-answer.output.open_units`。役の印は `tdd2`・`fix2`・`fix2-ruled continue=fix2`・`rule2`。
  8. `clean`・`assert-changed`・`fix-reads`・`collect` は 2 回目の節の出力も `if_skipped: null` で読む。
- 指示書の頭: `replan` の 2 つの役の頭（`planblk.head`・`planblk.design_only` の中身）は、blk-fix の script から blk-plan の lib を呼べないので、`planblk` の 2 つの関数の中身を core の `replan.role_head(b, role, repo, excluded_file="") -> str`・`replan.design_only(b) -> str` に移し、`planblk` はそれを呼ぶ形にする（使う部品 `gatemarks`・`libdocs`・`design`・`structmark`・`rolekit` はどれも core なので層は崩れない）。Task 6 の `replan.prep` の `head`・`design_part` は、blk-fix の支度がこの 2 つで組んで渡す。
- 表: `test_yaml_rules.py` の `EXCEPTIONS`（書く役 `fix2`・`fix2-ruled`）・`WEB_READERS`（`replan`・`replan-review`）、`test_tool_parity.py` の役と model の表、包みの書く役の名の表に、新しい印を足す。`stub_keys` と 13 本の fixtures に新しい id を足す。
- 境の節の 3 つの at（`replan`・`regate`・`refit`）は作らない。止め札は今どおり後ろの境の節が見る。

**Interfaces（両方の形）:**
- Consumes: Task 4〜8 の全部
- Produces:
  - 形 A: `line_edge.AT` に `"replan"`・`"regate"`・`"refit"`。`GATE_AT` に `"refit"`。`edge` の gate の分かれは at ごとに明示する（`fix` は `_answer_policy_gate`、`eyes` は `_answer_final_gate`、`refit` は `replan.answer`。今の「fix でなければ最後の関所」の書き方では `final-gate-answer.json` を上書きするので使わない）。止めた時は `answer` が止めた盤面を `_halted_out` で返す。
  - 線の description の並びの文に「修正 →（裁定が案の項目の誤りなら）案の直し → 案の直しの関所（要る時だけ）→ 2 回目の修正」を足す（形 B では `blk-fix` の description に同じ並びを足す）。
  - 無人の run（`unattended`）・設計だけの run（`design_only`）に特別な分かれを作らない。設計だけの run は修正に入らないので案の直しも起きない。無人の run の `replan-gate` は `policy-gate` と同じに開き、`dev/use.sh` は人の関所に stop で答える（今の :718〜723）ので、無人の run は `replan-gate` で止まって報告へ進む（1 回目に直した単位の差分は報告に残る）。

- [ ] **Step 1: 落ちる試験を書く**（形 B では `e("replan")` などの境の節の代わりに、同じ中身の script を `run_script` で回す helper `step(stage, **inputs)` を使う。試験の言う事は同じ）

```python
class TestLineReplay(ReplanCase):
    """224b・225 の型: 唯一直す項目の受け入れのテストの赤の種類・id の形が誤りと裁かれても、同じ run で直して差分が空でない"""
    def run_trip(self, new_item, gate=None):
        self.replanned(); self.accept_script(only_clamp_reply(), pass_="ruled")
        e = lambda at, **kw: line_edge.edge(self.board, at, self.repo, run_id="r", adapter_mode="optional",
                                            final_gate="", **kw)
        self.assertTrue(e("replan")["go"])
        self.play_role("plan", {"plan": [new_item]}); self.play_role("plan-review", no_faces())
        g = e("regate")
        r = e("refit", gate=gate if g["ask"] else None)
        return g, r

    def test_means_only_fix_same_run(self):
        g, r = self.run_trip(red_kind_fixed())
        self.assertFalse(g["ask"]); self.assertTrue(r["go"]); self.assertEqual(json.loads(r["open_units"]), [MEAN])
        self.edit_tree(MEAN_FIX)
        self.assertTrue(self.accept_script(only_mean_reply(), pass_="first", pass_tag="refit")["ok"])
        line_edge.edge(self.board, "rejudge", self.repo, run_id="r", adapter_mode="optional", final_gate="")
        self.assertNotEqual(linekit.git(self.repo, "diff", "--", "stats.py"), "")
        b = entry.open_board(self.board)
        self.assertEqual(conflict.asked(b), [])
        self.assertTrue(any("直した" in x for x in replan.lines(b)))

    def test_contract_change_stop_stops_run_keeps_first_pass(self):
        g, r = self.run_trip(wider_paths(), gate={"decision": "stop", "text": "範囲が広い"})
        self.assertTrue(g["ask"]); self.assertEqual((r["stop"], r["go"]), (True, False))
        b = entry.open_board(self.board, allow_halted=True)
        self.assertEqual(report.stop_outcome(b)[0], "stopped_by_human")
        self.assertIn(CLAMP, [c["unit_key"] for c in recount.fix_reply(b)[0]["changes"]])
        self.assertFalse(pathlib.Path(b.work(line_edge.FINAL_GATE_ANSWER)).exists())   # 最後の関所の答えを上書きしない

    def test_contract_change_continue_fixes_same_run(self): ...   # continue で戻り、2 回目で直して差分が空でない
    def test_second_ruling_in_refit_gives_up(self): ...   # 2 回目で同じ単位が再び fix_plan_item → h-rejudge の settle が CLOSE_WHY で諦める
    def test_ruled_continuation_follows_second_fix_session(self): ...   # 2 回目の fix-ruled が 2 回目の fix の会話を継ぐ（包みの会話の置き場）

# test_line.py の LineShapeCase: 選んだ形の節の順・replan-gate が輪の外の approval・（形 A なら）h-rejudge の depends_on
```

- [ ] **Step 2: 落ちることを確かめる**

Run: `cd works/tests && PYTHONDONTWRITEBYTECODE=1 python3 -m unittest test_replan.TestLineReplay test_line.LineShapeCase`
Expected: FAIL（形 A: `BoardGap: 知らない at`。形 B: 節が無い）

- [ ] **Step 3: 選んだ形の YAML・境の節（か script）・linekit・fixtures を書く**

- [ ] **Step 4: 通ることを確かめる**

Run: `cd works/tests && PYTHONDONTWRITEBYTECODE=1 python3 -m unittest test_replan test_line test_line_a test_edge test_yaml_rules test_tool_parity test_blk_fix test_blk_plan` と `WORKS_TESTS=fast nice -n 19 sh works/tests/run.sh` と `sh ~/.cache/works-dogfood/rootfences.sh`
Expected: PASS・失敗 0

- [ ] **Step 5: Commit**

```bash
git add works/darkfactory works/blk-fix works/blk-plan works/.shared/core works/tests
git commit -m "feat(works): 修正の後に案の直し・その関所・2 回目の修正を繋ぐ（Archon の測りで選んだ形。224b・225 の型が同じ run で直る。226 Task 9）"
```

---

### Task 10: 役の決まりと記述を新しい意味に合わせる・CHANGELOG

**Files:**
- Modify: `works/blk-fix/rules/principles.md:15`・`works/blk-fix/rules/ruler.md:38`（`fix_plan_item` は「同じ run の中で修正案の役がこの項目だけを直し、事前審査と関所の決まりを通ってから 2 回目の修正の段で直す」。`text` には項目のどこをどう直すかを書く——修正案の役に字のまま渡る）
- Modify: `works/.shared/core/conflict.py`（docstring の頭 :6〜8・`REPLAN` の注記・`held_by_rulings` の docstring :371〜373・`write_rulings` の `REPLAN` の約束・`NOTHING_OWED`）・`works/.shared/core/entry.py:142-143`・`works/.shared/core/deltamarks.py:126`・`works/blk-refix/rules/refix.md:9`・`works/blk-delta/commands/delta-review.md`（「次の run の修正案で決める」→「最後の人の関所で人が決める」）・`works/blk-fix/blk-fix.yaml:18,726` の記述
- Modify: `works/CHANGELOG.md`（`[Unreleased]` の `### Changed`）
- Test: `works/tests/test_conflict_kinds.py`（class `TestReplanWords`）

**Interfaces:**
- Consumes: Task 3〜9 の振る舞い
- Produces:
  - `write_rulings` の `REPLAN` の約束（字のまま）: 「案の項目そのものが誤りと裁いた。この単位も「項目の単位」に並べた同じ項目の単位も、今は直すな（機械が直す義務から外した）。この run の中で修正案の役がこの項目だけを直し、事前審査と人の関所の決まりを通ってから、2 回目の修正の段で直す。changes に書くな。1 回目に直した項目の単位の直しは作業ツリーから戻す（機械も戻す）」
  - CHANGELOG の 1 項目（下書き）: 「修正役の申し出を裁定役が `fix_plan_item`（承認済みの修正案の項目そのものの誤り）と裁いた時、その項目を次の run に持ち越さず、同じ run の中で修正案の役に戻す。役に渡すのはその項目・申し出の文・裁定の文だけで、返答はその項目に限り、差し替えは機械がする。直した項目は事前審査に掛かり、約束の欄（単位・狭め・消す物・書いてよいパス・触らない物・既存テストの書き換え・受け入れのテストの振る舞い）が同じで人に聞く種類の穴が無ければ聞かずに、そうでなければ新しい関所 `replan-gate` で人に聞いてから、2 回目の修正の段で直す。`replan-gate` の stop はほかの関所と同じく run を止め、1 回目に直した単位の差分は報告に残る。案の段に戻るのは 1 run に 1 回。直せなかった単位は ask_human と同じく最後の関所と次の run の依頼に、裁定の文を字のまま載せる。報告の『案の項目の誤りと裁いて直さずに残した単位』の節と、それだけで結末を round_limit にする分かれは消した」

- [ ] **Step 1: 落ちる試験を書く**（行をまたいだ字も見るため、ファイルの文から空白・改行と `"` を除いてから探す）

```python
class TestReplanWords(unittest.TestCase):
    @staticmethod
    def flat(p):
        return re.sub(r'[\s"]', "", p.read_text(encoding="utf-8"))

    def test_no_carry_over_words_left(self):
        for p in (CORE / "conflict.py", CORE / "entry.py", CORE / "deltamarks.py", BLK_FIX / "rules" / "principles.md",
                  BLK_FIX / "rules" / "ruler.md", BLK_FIX / "blk-fix.yaml", BLK_REFIX / "rules" / "refix.md",
                  BLK_DELTA / "commands" / "delta-review.md"):
            with self.subTest(p.name):
                self.assertNotIn("次のrunの修正案", self.flat(p))

    def test_ruler_says_same_run(self):
        self.assertIn("同じ run の中で修正案の役", fixrules.sections(fixrules.RULER)["ruler-reply"])
```

- [ ] **Step 2: 落ちることを確かめる**

Run: `cd works/tests && PYTHONDONTWRITEBYTECODE=1 python3 -m unittest test_conflict_kinds.TestReplanWords`
Expected: FAIL

- [ ] **Step 3: 文を直し、CHANGELOG を書く**

- [ ] **Step 4: 通ることを確かめる**

Run: `WORKS_TESTS=fast nice -n 19 sh works/tests/run.sh` と `sh ~/.cache/works-dogfood/rootfences.sh` と `cd works/tests && PYTHONDONTWRITEBYTECODE=1 python3 -m unittest test_replan test_blk_fix_conflict test_blk_plan test_line`
Expected: PASS・失敗 0

- [ ] **Step 5: Commit**

```bash
git add works/blk-fix works/.shared/core works/blk-refix works/blk-delta works/CHANGELOG.md works/tests/test_conflict_kinds.py
git commit -m "docs(works): fix_plan_item の意味を同じ run の案の直しに合わせ、持ち越しの語を消す。CHANGELOG（226 Task 10）"
```

---

## 持ち主の決定: 無人の run で範囲を広げるだけの直しは関所を飛ばす（2026-10-08）

Task 7 の決まり（約束の欄が同じで人に聞く穴が無い直しだけを聞かずに通す）と Task 9 の「無人の run に特別な分かれを作らない」の上に、1 つだけ分かれを足した。canary の run 54d81ef1 は、計画役が `CHANGELOG.md` を `out_of_scope` に名指した項目を案の直しで外しただけなのに、無人の run が `replan-gate` で止まり、項目は直らずに終わった。

- 決まり: 無人の run（start の控えの `unattended`。`gatemarks.unattended`）で、範囲の欄を持つ承認済みの項目と直した項目の違いが `allowed_paths` に足した行と `out_of_scope` から外した行だけ（どちらかが 1 行以上）で、事前審査が人に聞く種類の穴を挙げなければ、関所を開かずに直した項目で修正に戻る。決めるのはコード（`planmarks.widened(old, new)`。純粋。関所の決め手の欄を外した形で比べ、`contract_diff` と同じく `unit_keys`・`tests` の並べ替えと `rewrite_tests` の範囲 `limit` は数えない）。
- 今どおり関所で止まる物: `rewrite_tests` を足した直し（テストを変えると「直った」の意味が変わるので人が見る）・ほかの欄（`red_kind`・テストの id・`behavior`・`adds`・`removes`・`narrows`・`approach`・`route`・`refactor`・`unit_keys` など、手段の欄も含む）を 1 つでも変えた直し・`allowed_paths` から外した・`out_of_scope` に足したか行を書き換えた直し・人に聞く種類の穴が在る直し。人の居る run は範囲を広げるだけの直しも今どおり聞く。手段の欄だけの直しを聞かずに通すのは前のまま。
- 残す物: `replan.json` の行の欄 `widened`（`{allowed_paths: [足した glob], out_of_scope: [外した glob]}`）、盤面の trace の行 `replan_widened_unattended`（`{round, item, units, allowed_paths, out_of_scope}`。`answer` が項目を採った時だけ書く——ほかの項目が関所を開けて stop で諦めた時は書かない。再開で当て直しても 1 行）、報告の冒頭 1 と最後の関所の文の「同じ run の中で直した修正案の項目」の行（`直した——無人の run なので人に聞かずに範囲を広げた（allowed_paths に足した: …／out_of_scope から外した: …）`）。広げた範囲で作った差分は、後の差分の審査がいつもどおり見る。
- 線（`darkfactory.yaml`）の節は変えない（`h-regate` の上のコメントだけ直した）。`h-regate` の `ask` が偽なら `replan-gate` は `when:` で飛び、`h-refit` は答え無しで聞かない項目を採る（前からの道）。

## この計画が扱わない物

- (b)「案の段で誤りを機械で先に弾く」: 採らない（run 226 の ■6。誤りの種類ごとに検査が増え、`test_tiers` の決まりを 2 か所に書き、持ち越しの道も残る）。
- 開発の殻 `works/dev/fixmeasure.py` の節の数え（`fixing__` の頭）は、2 回目の段の節（形 A の `refitting__`、形 B の `fix2` など）を数えない。測る要が出たら別の依頼にする。
- 自分食いの run の pack の写し（`.archon/workflows/works`）は、版を固める段の物で、この計画では触らない。
