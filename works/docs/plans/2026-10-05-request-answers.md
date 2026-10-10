# 依頼に答えの欄 answers を足し、依頼者の答えた問いを人に聞き直さない（依頼 240 の核）Implementation Plan

状態: 入れた（works 0.2.27。依頼の欄 `answers` と `gatemarks.answered`）。

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** works（このリポジトリの `works/` に在るプラグイン。外の道具 Archon の上で、人の修正依頼を AI の役に直させる工程 darkfactory を回す）の依頼のファイルに欄 `answers`（問いの key か出どころ → 依頼者の答え。手元で測ったなら命令と出力つき）を足し、入口から盤面へ届け、問いの台帳の「答えたか」を 1 つの述語で読む。答えた問いは修正前の関所に載らず、保留の件数に数えず、報告と最後の関所には「依頼者の答え: …」と出どころつきで並ぶ。

**Architecture:** 依頼の型の正本 `ghreads.request_parts` が `answers` を解き、`entry.check_inputs` が start の控え `r1/start.json` に残す（読み手は今ある `gatemarks.start_doc` の 1 つ）。`gatemarks.answered(b, q)` は「関所の continue で答えた」か「依頼の answers に q の key か出どころと同じ question が在る」の 1 つの述語になり、関所の項目・直す義務から外す集合・戻す集合・保留の行・答えた行が全部これを読む。写しの graphloops と問いの台帳の行の型は変えない（台帳の行は残り、印は works の側で付ける）。

**Tech Stack:** Python 3.12（`ghreads.py` は 3.9 で動く形のまま）、標準ライブラリだけ、unittest

**Spec:** 依頼 240。本文と、それを設計だけで回した run 175a5a0e（2026-10-05）の出力のうち要る所は、この文書の「この文書の読み方」「根本の原因」「決めたこと」に全部書き写した。元の置き場（持ち主の機械の上）: 依頼 `~/.cache/works-dogfood/req-240.json`、独立設計 `~/.cache/works-dogfood/carry/240/design.json`、事前審査 `~/.cache/works-dogfood/carry/240/plan-converge/pass-1/` と `pass-2/`（`p2.plan_review.json`・`p2.fix_plan.json`）。同じ置き場の `carry/240/p2.fix_plan.json`・`judgment.json` は 10-03 の古い run の物で、この計画は使わない。

## この文書の読み方（初めて読む人向け。本文の語はここで全部定める）

読み手: この計画の Task を 1 つずつ実装する AI の役（実装役）と審査する役。どちらも作業ツリー `/Users/p03623/src/claude-plugins-work1-sdd20`（枝 `wip/sdd-240`。起点の commit 0ce37ed5 = works の版 0.2.26）を手元に持つ。「今」は起点の commit の振る舞い。パスは断りが無ければ `works/` からの相対、`gatemarks.py:467` はそのファイルの 467 行目（起点の版）。

番号と名:
- 依頼 240: 持ち主が works を外の Go のリポジトリに 9 回回して出た弱い所 4 つを、works 自身で直す「自分食い」の依頼の連番 240 番。4 つは (1) run をまたぐと前の run の失敗を忘れる (2) 依頼者が依頼に書いた事実（並行する PR が無い等）を毎回問いに戻す (3) 作業場所（Archon が役を閉じ込める sandbox）で測れない物の扱い (4) 同じ依頼の run を重ねる費用と時間。
- 依頼 239: 別の自分食いの依頼。部品の状態を宣言した置き場に寄せ、部品の間の引き継ぎを宣言した文書で渡す形にする（まだ入っていない）。
- run 175a5a0e: 依頼 240 を「設計だけ」で回した run。独立設計（依頼の目的だけから別の役が作った設計）と、修正案と、修正案の事前審査（審査役が穴を key つきで挙げる。重さ block は直すまで通さない、suggest は勧め）を 2 往復（pass-1・pass-2）残した。本文の「事前審査の block `<key>`」はこの審査の穴の名。
- SDD: superpowers（Claude Code のプラグイン）の subagent-driven-development。会話の中で計画を Task ごとに AI に実装させる進め方。持ち主の今の運用の決まりは「同じ依頼が 3 回落ちたら SDD に切り替える」。
- keep-essence: `docs/keep-essence.md` の、どの作りでも残す works の 11 の仕組み。この計画はどれにも触れない。

置き場と道具:
- 依頼のファイル: 人が書く JSON。findings（指摘）の配列か `{"findings": [...], "pr": [...], "issue": [...]}`。形の正本は `.shared/core/ghreads.py` の `KEYS`（27 行）と `request_parts`（35-52 行）。入口 `entry._read_request`（`.shared/core/entry.py:383-403`）と、判定のブロックと前提のブロックの依頼の受け口（`blk-judge/scripts/intake.py:65`・`blk-premises/scripts/intake.py:79`）が `request_parts(doc)["findings"]` だけを取る。
- ブロック: `blk-*/` の部品（役の指示書・受け付けのスクリプト）。ブロックの間の配線は `darkfactory/darkfactory.yaml` だけが持つ。
- 盤面: run ごとの状態の置き場。start の控えは盤面の `r1/start.json` で、書き手は `entry.start`（`_kept(inp)` を書く。`entry.py:808`）、読み手は `gatemarks.start_doc(board_dir)`（`.shared/core/gatemarks.py:422`。conflict・report も使う）。
- 写し: `.shared/core/graphloops/` は本流 graphloops（別のプラグイン。審査の工程の規則と検証器）のバイト単位の写し。この計画は変えない。
- 問いの台帳: 盤面の `record.questions`。判定役（依頼を直す単位に切る AI の役）が書く。行の欄は写しの graph で閉じている（key・kind・status・reason・resolution・options・depends・origin だけ）。kind は fork（設計の岐路。options が要る）・field（人が実地で確かめるまで決まらない）・awaiting（素材が人待ち）など。awaiting の問いの origin は素材の名（例 `parallel_pr` = 並行する PR の検査）で、素材が awaiting_human の間は写しの検証器が台帳にこの問いを求める（`graphloops/rules/review-loop.py:2595-2598`）。
- 人に聞く問い: `gatemarks.asks(b)`（fork と status escalate の問い）。`answered(b, q)`（467 行）が答えたかの述語で、`plan_gate_items`（373 行。修正前の関所の項目）・`pending`・`withheld_by`（答えが無いので直す義務から外す単位）・`returned`（答えで義務に戻す単位）・`unread_hold_lines` がこれを読む。保留の行 `held_lines`（602 行）と答えた行 `answered_lines`（611 行）は別の述語 `_gate_answered`（593 行）を読む。
- 修正前の関所・最後の関所: 人が答える止まり所。直す前に開く物（記録の名 p2.human_gate）と、報告の前に開く物（final-gate）。

## 根本の原因（読む版のコードと盤面で確かめた）

1. 依頼に答えを書く口が無い。`request_parts` は `findings`・`pr`・`issue` のほかの鍵を「知らない鍵」で拒む（`ghreads.py:40-42`）。依頼者が「並行する PR は無い」と書けるのは findings の文の中だけで、機械は問いと結べない。
2. 問いの key は run ごとに字が変わる。自分食いの盤面（`~/.cache/works-dogfood/boards/*/runs/*/board/record.json`）の並行 PR の awaiting の問いの key は 20 通りを超える（`awaiting: parallel_pr（並行 PR の有無が未観測）` 15 回・`awaiting:parallel_pr` 11 回・`awaiting-parallel_pr` 8 回 …）。変わらないのは出どころ `origin: parallel_pr` だけ。答えを key だけで結ぶと次の run で外れる。
3. 答えたかを読む述語が 2 つある。`answered`（関所の項目と直す義務）と `_gate_answered`（保留と答えた行）。片方だけを広げると、報告は「答えた」と並べるのに関所は聞き直し、単位は直されない（事前審査 pass-2 の block `request_answer_skips_gate_and_duty`）。
4. 依頼 240 の誤りの条件「前の run の拒否と作り直しの理由が既に次の run の材料に載っているなら (1) は誤り」は当たらない: 次の run の依頼の下書きを作る `report.next_request`（`.shared/core/report.py:486-556`）が積むのは手直しの穴・修正がやらなかった単位・テストの赤・残り・レンズ・再審・人に回した単位・関所の問いだけで、受け付けの拒否の理由も R2（独立設計と修正の構造を突き合わせる目）の作り直しの理由も積まない。(1) は実在する。ただし節「この計画が扱わない物」に回す。

## 決めたこと（1 つの軸「目的と keep-essence を保って全体がより簡潔か」で選んだ）

- **決め 1（答えの形）:** `answers` は `[{question, text, command?, output?}]`。`question` と `text` は空でない文字列。`command` と `output` は両方か、どちらも無い（片方だけは拒む）。同じ `question` を 2 度書けば拒む。依頼に書いた物なので出どころはいつも「依頼者」で、欄 `by` は持たない（独立設計が言う by=依頼者／人 の区別は、命令と出力の有無で同じことが言える）。配列の形の依頼は `answers` が空。
- **決め 2（結び方は 1 つ）:** 答えは、台帳の問いの `key` か `origin` が `question` と字のまま等しい問いに当たる。kind で分けない。awaiting の問いは素材の名（`parallel_pr`）で、ほかの問いは key で答えられる。判定役には「依頼の answers が答えた問いを台帳に載せるなら key を question の字のままにせよ」と指示書で頼む（節「根本の原因」の 2）。
- **決め 3（答えたかの述語は 1 つ）:** `answered(b, q)` = 依頼の答えが当たる、または今の関所の continue の決まり。`_gate_answered(b, q)` = 依頼の答えが当たる、または「q が asks に在り answered」。これで関所の項目・直す義務から外す集合・戻す集合・保留の行・答えた行が同じ答えを読む。答えた問いの台帳の行は残す（写しの検証器と型は変えない）。
- **決め 4（出どころを名乗る）:** 答えた行の印は、関所の答えなら今の「・関所で continue を受けた」、依頼の答えなら「・依頼者の答え: <text>」に「（人が手元で実行: `<command>`・出力: <output>）」を添える。修正役への約束 `returned_lines` にも同じ文を添える（推しでなく答えで直させる）。見出しは「答えた問い（関所の continue か依頼の answers）」にする。実測とは書かない。前提の役の 実測／仮説 の区分は変えない（依頼者の言明は人に聞く代わりにはなるが、測りの代わりにはならない）。
- **決め 5（黙って落とさない）:** どの台帳の問いにも当たらない答えは、報告の冒頭と最後の関所の文に 1 件 1 行で出す（保留の件数には数えない）。保留の行が在る時は、その下に答え方の 1 行（`ANSWER_HOW`）を出す。次の run の依頼の下書き `next-request.json` は今の配列のまま（空欄の雛形は書かない。事前審査 pass-2 の block `blank_answers_count_as_answered`・`next_request_schema_oneof_ignored` と、同じ審査の縮める案 `drop_answer_blank_template` を採る）。
- **決め 6（測れない物）:** 判定役は field・awaiting の問いの `reason` に、人が手元で打てば決まる命令を「測り方: `<命令>`」で書く（命令が在る時だけ）。`options` は選択肢の欄なので使わない（事前審査の suggest `options_overloaded_as_command`）。人は命令を打ち、次の依頼の answers に `command`・`output` つきで返す。関所も期限も足さない。sandbox の許可を広げるかは works で決めない（隔離を弱める判断は持ち主の物で、設定の正本は Archon・Claude Code の側）。
- **決め 7（置き場）:** 答えは start の控え `r1/start.json` の欄 `answers` に置く。新しい state の置き場を作らない（依頼 239 が部品の状態を宣言した置き場に寄せる時は、start の控えと一緒に動く）。固定材料（盤面の写しから途中を再現する道 `fixture`）の照らし `entry.adopt_inputs` は `answers` を除く（依頼の文全体の sha256 を固定材料がもう照らしているので二重に照らさない。前の版の固定材料も読める）。

### 事前審査で 2 往復残った block `design_drift_carried_rows_to_judge` の解き方

block の中身: 修正案は、前の run の拒否の理由と run が裁いた問いを findings の行として次の依頼に積む。すると判定役が直す穴として読み直し、目的の役・独立設計の役も生の依頼を読むので、決着済みの論点が独立の目に渡って追認になる。独立設計は「拒否・作り直しは同じ節を作る役へ、裁いた問いは人に問う関所だけへ」と渡し分けを求めた。

解き方: この計画は run が作った行（拒否・作り直し・run が裁いた問い）を次の依頼に 1 行も積まない。積むのは依頼者が自分で書いた `answers` だけで、これは依頼の文と同じく人の入力であり、今もどの役も生の依頼として読んでいる物と同じ立場にある（run の決定を独立の目に渡すのではない）。機械が答えを使うのは人に問う所（関所の項目・保留・直す義務の外し）だけ。run が作った行を渡し分ける口は、依頼 239 の形に乗せて別の計画で作る（節「この計画が扱わない物」）。だから食い違いはこの計画の中に生じない。

## Global Constraints

- 写し `.shared/core/graphloops/` と本流の graphloops を変えない。台帳の行の型・`REQUEST_SCHEMA`・`darkfactory/schemas/next-request.schema.json` を変えない。
- 期限・タイムアウト・回数のしきい値を足さない。関所を足さない。今ある能力を減らさない（`answers` の無い依頼の振る舞いは今と同じ）。
- `blk-*` の文書とコードに、ほかのブロックの名や中身を書かない（`blk-judge/commands/diagnose.md` が書くのは自分の入力＝依頼の `answers` のことだけ）。`darkfactory/darkfactory.yaml` はこの計画では変えない。
- トークン・資格情報を読まない・書かない・出さない。Archon の開発元へ連絡しない。
- `ghreads.py` は Python 3.9 で動く形のまま・標準ライブラリだけ（殻が `python3 -I` で呼ぶ）。
- 新しいモジュールも試験のモジュールも足さない（`tests/tiers.py` を変えない）。試験は `unittest.TestCase` の class の中に置く。
- 注記・docstring・文・報告の文は日本語。
- 各 Task では触ったモジュールだけを回す: `works/` から `PYTHONDONTWRITEBYTECODE=1 WORKS_TESTSLOT= python3 -m unittest tests.<module>[.<Class>]`。速い段（`WORKS_TESTS=fast sh tests/run.sh`）と根の柵（リポジトリの根の試験の一式 `sh ~/.cache/works-dogfood/rootfences.sh`）は最後の Task で 1 回だけ。
- CHANGELOG は `CHANGELOG.md` の `[Unreleased]` だけ。版は上げない。commit は日本語で、末尾に `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`。push しない。

## Review Focus

1. 答えの `question` が台帳のどの問いにも当たらない（打ち間違い・判定が別の key を選んだ）→ 問いは保留のまま件数に数え、当たらなかった答えを報告の冒頭と最後の関所に名指す（黙って答えた扱いにしない）。（Task 2 の `test_unmatched_answer_is_shown_and_question_stays_held`）
2. 依頼の答えが fork の問いに当たる → 修正前の関所に載せず、出どころの単位は直す義務に戻り、修正役への約束に答えの文が載る（報告と関所と義務がずれない）。（Task 2 の `test_requester_answer_by_key_skips_gate_and_returns_origin`）
3. 本物の入口を通した run（依頼のファイル → start → 盤面 → 判定の awaiting → 報告）で、答えが報告まで届く（入口で落ちる死んだ道を緑で隠さない）。（Task 3 の `test_requester_answer_closes_awaiting_without_asking`）
4. `command` だけ・空の `text`・同じ question の 2 度書き・知らない欄 → 盤面を作る前に 1 行で拒む。（Task 1 の `test_request_answers_bad_shape_refused`）
5. `answers` の無い前の版の盤面・固定材料（start の控えに欄が無い）→ 今と同じに動き、固定材料の照らしも通る。（Task 1 の `test_request_answers_reach_start_doc` の `adopt_inputs` の断言と、Task 1 の Step 4 の `tests.test_fixture`）

---

### Task 1: 依頼の型に answers を足し、入口から start の控えへ届ける

**Files:**
- Modify: `.shared/core/ghreads.py`（`KEYS`・`request_parts`・モジュールの docstring の 4-6 行と 12 行）
- Modify: `.shared/core/entry.py`（`_read_request` 383-403 行・`check_inputs` の 315 行の受けと 328-331 行の `out`・docstring 266-277 行・`adopt_inputs` 813-816 行）
- Test: `tests/test_entry.py`（`CheckInputsCase`。`test_inputs_defaults` の直しと新しい 2 本。頭の import に `gatemarks` を足す）

**Interfaces:**
- Consumes: なし
- Produces:
  - `ghreads.KEYS = ("findings", "pr", "issue", "answers")`
  - `ghreads.ANSWER_KEYS = ("question", "text", "command", "output")`
  - `ghreads.request_parts(doc) -> {"findings": list, "pr": [int], "issue": [int], "answers": [dict]}` — 配列の形は `answers: []`。形が決め 1 に合わなければ `ValueError`（1 行。どの行のどの欄かを名指す）
  - `entry._read_request(rel, repo, rules) -> (path, text, items, answers)`
  - `entry.check_inputs(...)` の返りに `"answers": list`（依頼が無ければ `[]`）。`entry.start` は `_kept` のまま start の控えに書くので、控えに `answers` が載る
  - `entry.adopt_inputs(inp)` は `base_rev` と `answers` を除く

- [ ] **Step 1: 落ちる試験を書く（`tests/test_entry.py` の `CheckInputsCase`）**

```python
    ANSWERS = [{"question": "parallel_pr", "text": "並行する PR は無い"},
               {"question": "q-sock", "text": "通った", "command": "go test ./internal/sock/...", "output": "ok  sock 0.2s"}]

    def test_request_answers_reach_start_doc(self):
        """object の形の依頼の answers は check_inputs の返りと start の控えに字のまま載り、固定材料の照らしには入らない"""
        repo = self.seed()
        rows = json.loads((linekit.SEED / "request_ok.json").read_text(encoding="utf-8"))
        req = request_file(self.tmp / "ans.json", {"findings": rows, "answers": self.ANSWERS})
        got = entry.check_inputs({"request": str(req)}, repo)
        self.assertEqual((got["items"], got["answers"]), (rows, self.ANSWERS))
        self.assertNotIn("answers", entry.adopt_inputs(got))
        self.start(repo, raw=self.raw(request=str(req)))
        self.assertEqual(gatemarks.start_doc(self.board)["answers"], self.ANSWERS)

    def test_request_answers_bad_shape_refused(self):
        repo = self.seed()
        rows = json.loads((linekit.SEED / "request_ok.json").read_text(encoding="utf-8"))
        one = {"question": "x", "text": "y"}
        for name, ans in (("not-list", one), ("empty-text", [{**one, "text": ""}]), ("no-question", [{"text": "y"}]),
                          ("command-only", [{**one, "command": "ls"}]), ("output-only", [{**one, "output": "a"}]),
                          ("extra", [{**one, "by": "人"}]), ("dup", [one, {**one, "text": "z"}]), ("not-dict", ["x"])):
            with self.subTest(name):
                req = request_file(self.tmp / f"{name}.json", {"findings": rows, "answers": ans})
                with self.assertRaises(entry.InputRefused) as cm:
                    entry.check_inputs({"request": str(req)}, repo)
                self.assertIn("answers", str(cm.exception))
                self.assertNotIn("\n", str(cm.exception))
```

`test_inputs_defaults`（634 行）の鍵の集合に `"answers"` を足し、`self.assertEqual(got["answers"], [])` を足す（配列の形の依頼）。

- [ ] **Step 2: 落ちることを確かめる**

Run: `works/` から `PYTHONDONTWRITEBYTECODE=1 WORKS_TESTSLOT= python3 -m unittest tests.test_entry.CheckInputsCase`
Expected: 新しい 2 本と `test_inputs_defaults` が FAIL（「知らない鍵 ['answers']」の InputRefused・返りに `answers` が無い）

- [ ] **Step 3: `ghreads.request_parts` と入口を直す**

`request_parts` は決め 1 の確かめを足し、拒む文は `answers[<i>] の <欄> …` の形にする。`_read_request` は `request_parts` の返りを 1 度だけ取って `items` と `answers` を返す。`check_inputs` は依頼が無い時 `answers=[]`、`out` に `"answers": answers`。`_read_request` の型の誤りの文（401 行）の `{findings, pr, issue}` を `{findings, pr, issue, answers}` に。`adopt_inputs` の docstring に「answers は依頼の文の sha256 が照らす」を 1 句足す。`ghreads.py` の docstring の 4-6・12 行に answers を書く（graphloops の規則へ渡すのは findings だけ、は今のまま）。

- [ ] **Step 4: 通ることを確かめる**

Run: `works/` から `PYTHONDONTWRITEBYTECODE=1 WORKS_TESTSLOT= python3 -m unittest tests.test_entry tests.test_ghreads tests.test_entry_inputs tests.test_fixture tests.test_blk_judge`
Expected: PASS・失敗 0

- [ ] **Step 5: Commit**

```bash
git add works/.shared/core/ghreads.py works/.shared/core/entry.py works/tests/test_entry.py
git commit -m "feat(works): 依頼のファイルに欄 answers（問いの key か出どころへの依頼者の答え・手元で測った命令と出力）を足し、入口が start の控えに残す（依頼 240 Task 1）"
```

---

### Task 2: 答えたかを 1 つの述語で読み、出どころを名乗って並べる

**Files:**
- Modify: `.shared/core/gatemarks.py`（`answered` 467-471 行・`returned_lines` 579-584 行・`_gate_answered` 593-594 行・`answered_lines` 611-613 行・新しい関数と定数。モジュールの docstring の 44-46 行の辺りに 1 項）
- Modify: `.shared/core/report.py`（`head_decisions` の 662-669 行。docstring 612 行の名指し）
- Modify: `darkfactory/lib/line_edge.py`（`_final_text` の 528-537 行と「盤面の問い: 無い」の条件 538 行。docstring 484 行の名指し）
- Test: `tests/test_plan_gate.py`（新しい class `RequestAnswersCase(GateBase)`）

**Interfaces:**
- Consumes: Task 1 の start の控えの欄 `answers`（`gatemarks.start_doc(b.dir)["answers"]`。無い・配列でなければ空とみなす）
- Produces:
  - `gatemarks.request_answers(b) -> list[dict]`
  - `gatemarks.request_answer(b, q) -> dict | None` — `question` が `q["key"]` か `q["origin"]` と等しい最初の答え
  - `gatemarks.answer_note(a: dict) -> str` — `依頼者の答え: <text>` と、`command` が在れば `（人が手元で実行: `<command>`・出力: <output>）`（空白は 1 つに詰め、切らない）
  - `gatemarks.unmatched_answer_lines(b) -> list[str]` — どの台帳の問いの key にも origin にも当たらない答えごとに `依頼の答えに当たる問いが台帳に無い（判定が問いを立てなかったか、字が違う）: <question>——<answer_note>`
  - `gatemarks.ANSWERED_HEAD = "答えた問い（関所の continue か依頼の answers）"`
  - `gatemarks.ANSWER_HOW` — 1 行: `答え方: 次の run の依頼を {"findings": [...], "answers": [{"question": "<問いの key か出どころ>", "text": "<答え>"}]} の形にすれば、その問いを人に聞き直さない（手元で測ったなら "command" と "output" も書く）`
  - `answered(b, q)`・`_gate_answered(b, q)` は決め 3、`answered_lines` の印と `returned_lines` の文は決め 4

- [ ] **Step 1: 落ちる試験を書く（`tests/test_plan_gate.py`）**

```python
AWAITING_PR = {"key": "q-awaiting-pr", "kind": "awaiting", "status": "held", "origin": "parallel_pr",
               "reason": "人が確かめる。測り方: `gh pr list --state open`"}


class RequestAnswersCase(GateBase):
    """依頼の answers が台帳の問いの key か出どころに当たれば、関所の continue と同じ 1 つの述語で答えたと読む"""
    answer, owed, final_text, head = (LedgerAsksCase.answer, LedgerAsksCase.owed, LedgerAsksCase.final_text,
                                      LedgerAsksCase.head)

    def answers(self, *rows):
        (self.tmp / "r1").mkdir(exist_ok=True)
        (self.tmp / "r1" / "start.json").write_text(json.dumps({"answers": list(rows)}, ensure_ascii=False), encoding="utf-8")

    def test_requester_answer_by_origin_moves_awaiting_out_of_held(self):
        self.answers({"question": "parallel_pr", "text": "並行する PR は無い"})
        _, b = self.gate(questions=[AWAITING_PR], units=UNITS)
        self.assertEqual(gatemarks.held_lines(b), [])
        done = "\n".join(gatemarks.answered_lines(b))
        self.assertIn("依頼者の答え: 並行する PR は無い", done)
        self.assertNotIn("関所で continue を受けた", done)
        for name, text in (("最後の関所", self.final_text(b)), ("報告の冒頭", self.head(b))):
            with self.subTest(name):
                self.assertIn(gatemarks.ANSWERED_HEAD, text)
                self.assertNotIn("保留にしたままの問い", text)

    def test_requester_answer_by_key_skips_gate_and_returns_origin(self):
        self.answers({"question": FORK["key"], "text": "例外のまま"})
        got, b = self.gate(questions=[FORK], units=UNITS)
        self.assertEqual(got, {"ok": True}, "答えた問いは修正前の関所に載せない")
        self.assertEqual(gatemarks.pending(b), [])
        self.assertEqual(self.owed(b), {FORK_UNIT, OTHER_UNIT})
        self.assertIn("依頼者の答え: 例外のまま", "\n".join(gatemarks.returned_lines(b)))

    def test_measured_answer_shows_command_and_output(self):
        self.answers({"question": "parallel_pr", "text": "一覧は空", "command": "gh pr list --state open",
                      "output": "no open pull requests"})
        _, b = self.gate(questions=[AWAITING_PR], units=UNITS)
        line = gatemarks.answered_lines(b)[0]
        self.assertIn("人が手元で実行: `gh pr list --state open`", line)
        self.assertIn("no open pull requests", line)

    def test_unmatched_answer_is_shown_and_question_stays_held(self):
        self.answers({"question": "parallel-pr", "text": "無い"})
        _, b = self.gate(questions=[AWAITING_PR], units=UNITS)
        self.assertEqual(len(gatemarks.held_lines(b)), 1)
        self.assertIn("parallel-pr", "\n".join(gatemarks.unmatched_answer_lines(b)))
        for text in (self.final_text(b), self.head(b)):
            self.assertIn("依頼の答えに当たる問いが台帳に無い", text)
            self.assertIn(gatemarks.ANSWER_HOW, text)
```

- [ ] **Step 2: 落ちることを確かめる**

Run: `works/` から `PYTHONDONTWRITEBYTECODE=1 WORKS_TESTSLOT= python3 -m unittest tests.test_plan_gate.RequestAnswersCase`
Expected: FAIL（`gatemarks.ANSWERED_HEAD` が無い AttributeError、ほかは held_lines に awaiting が残る・関所が fork を聞く）

- [ ] **Step 3: gatemarks の述語と行を直す**

決め 3・4・5 のとおり。`answered` は先に `request_answer` を見る。`_gate_answered` は `request_answer(b, q) is not None or (q in asks(b) and answered(b, q))`。`answered_lines` の印は `request_answer` が在れば `"・" + answer_note(a)`、無ければ今の印。`returned_lines` は依頼の答えの問いの行を「依頼で答えた<ASK_HEAD> <key> の出どころ・depends は直す義務に戻った: …——答え: <answer_note>」にし、関所で答えた問いの行は今の文のまま。

- [ ] **Step 4: 報告の冒頭と最後の関所の文に並べる**

`report.head_decisions` と `line_edge._final_text` の両方で: 保留の行の直後に、行が在れば `ANSWER_HOW` を 1 行。答えた行の見出しは `ANSWERED_HEAD`（件数と「保留の件数には数えない」は今のまま）。その後に `unmatched_answer_lines` の行（在れば）。`_final_text` の「盤面の問い: 無い」の条件に当たらなかった答えの行も入れる。

- [ ] **Step 5: 通ることを確かめる**

Run: `works/` から `PYTHONDONTWRITEBYTECODE=1 WORKS_TESTSLOT= python3 -m unittest tests.test_plan_gate tests.test_fix_duty tests.test_duty_sets tests.test_gate_head tests.test_report tests.test_report_head tests.test_edge`
Expected: PASS・失敗 0（`test_duty_sets` の `KNOWN_DIFF` は答えの無い盤面なので今のまま）

- [ ] **Step 6: Commit**

```bash
git add works/.shared/core/gatemarks.py works/.shared/core/report.py works/darkfactory/lib/line_edge.py works/tests/test_plan_gate.py
git commit -m "feat(works): 問いの台帳の答えたかを、関所の continue と依頼の answers（問いの key か出どころで結ぶ）の 1 つの述語で読み、報告と最後の関所に依頼者の答えと当たらなかった答えを名乗って並べる（依頼 240 Task 2）"
```

---

### Task 3: 本物の線で答えが報告まで届く・判定役と利用者への文

**Files:**
- Modify: `tests/linekit.py`（`run_line` 698 行と `LineRun.__init__` 309-319 行に引数 `request=None`。在れば `json.dumps(request, ensure_ascii=False)` を依頼のファイルに書く。無ければ今どおり種の `request_ok.json`）
- Modify: `blk-judge/commands/diagnose.md`（「入力」の依頼の項 7 行・「問いの台帳」の節 48-57 行）
- Modify: `skills/works/SKILL.md`（「1. 依頼の JSON を書く」40-62 行・修正前の関所の答え方 100 行）
- Test: `tests/test_line_a.py`（`JudgeAwaitingCase` に 1 本）

**Interfaces:**
- Consumes: Task 1 の入口、Task 2 の `gatemarks.answer_note` の文（「依頼者の答え: 」）
- Produces: `linekit.run_line(tmp, *, replies, gates=None, inputs=None, stop_at=None, edits=None, sessions=False, request=None)`

- [ ] **Step 1: 落ちる試験を書く（`tests/test_line_a.py` の `JudgeAwaitingCase`）**

```python
    def test_requester_answer_closes_awaiting_without_asking(self):
        """依頼の answers が素材の名 parallel_pr で答えると、判定の awaiting の問いは台帳に残ったまま、報告は依頼者の答えとして並べ、
        保留に数えない（依頼のファイル → start → 盤面 → 判定 → 報告の本物の道）"""
        rows = json.loads((linekit.SEED / "request_ok.json").read_text(encoding="utf-8"))
        ans = [{"question": "parallel_pr", "text": "並行する PR は無い（依頼者が GitHub の一覧で確かめた）"}]
        got = self.run_line(replies={**replies(), "pr-check": PR_AWAITING, "judge": judge_awaiting()},
                            request={"findings": rows, "answers": ans})
        text = pathlib.Path(got["report"]["report_file"]).read_text(encoding="utf-8")
        self.assertIn("依頼者の答え: 並行する PR は無い", text)
        self.assertNotIn("保留にしたままの問い", text)
        b = entry.open_board(got["board_dir"], allow_halted=True)
        self.assertIn(("awaiting", "parallel_pr"), [(q["kind"], q.get("origin")) for q in b.record["questions"]],
                      "台帳の行は残る（写しの検証器は変えない）")
```

- [ ] **Step 2: 落ちることを確かめる**

Run: `works/` から `PYTHONDONTWRITEBYTECODE=1 WORKS_TESTSLOT= python3 -m unittest tests.test_line_a.JudgeAwaitingCase.test_requester_answer_closes_awaiting_without_asking`
Expected: FAIL（`run_line` が `request` を受けない TypeError）。`linekit` を直した後、Task 1・2 が入っていれば PASS になることを確かめる（落ちたら、入口から報告までのどこで答えが消えるかを直す）。

- [ ] **Step 3: 判定役の指示書と利用者の文**

`diagnose.md` の「入力」の依頼の項に、object の形の任意の欄 `answers: [{question, text, command?, output?}]` を足す: 依頼者が前の run の問いに答えた物で、出どころは人。question が台帳の問いの key か出どころに当たる問いは機械が答え済みにし、人に聞き直さない。「問いの台帳」の節に 2 項: (a) answers が答えた問いと同じ問いを台帳に載せるなら key を question の字のままにせよ（awaiting の問いは素材が awaiting_human の間は今どおり載せる）。(b) field・awaiting の問いで、人が手元で打てば決まる命令が在れば、`reason` に「測り方: `<命令>`」で書け（`options` は選択肢の欄なので命令を書くな）。ほかのブロックの名は書かない。

`SKILL.md` の 1 節に `answers` の形と例（`{"findings": [...], "answers": [{"question": "parallel_pr", "text": "並行する PR は無い"}]}`）と、決め 1 の決まり（question と text は要る・command と output は両方か無し・同じ question は 1 度）を足す。100 行の答え方の後に「保留の問いには、次の run の依頼の answers でも答えられる（報告の冒頭の答え方の行）。作業場所で測れない物は、問いの『測り方』の命令を手元で打ち、command と output を添えて返す」を 1 項。

- [ ] **Step 4: 通ることを確かめる**

Run: `works/` から `PYTHONDONTWRITEBYTECODE=1 WORKS_TESTSLOT= python3 -m unittest tests.test_line_a tests.test_blk_judge`
Expected: PASS・失敗 0

- [ ] **Step 5: Commit**

```bash
git add works/tests/linekit.py works/tests/test_line_a.py works/blk-judge/commands/diagnose.md works/skills/works/SKILL.md
git commit -m "feat(works): 判定役に依頼の answers と測り方の命令の書き方を、利用者に answers の書き方を伝え、本物の線で依頼者の答えが報告まで届くことを試験で縛る（依頼 240 Task 3）"
```

---

### Task 4: CHANGELOG と仕上げ

**Files:**
- Modify: `CHANGELOG.md`（`[Unreleased]` の `### Added`）

**Interfaces:**
- Consumes: Task 1-3 の全部
- Produces: CHANGELOG の 1 項目（下書き）: 「依頼のファイルに欄 `answers`（`[{question, text, command?, output?}]`）を足した。question が問いの台帳の問いの key か出どころ（awaiting の問いは素材の名。例 `parallel_pr`）に当たる問いは、関所の continue と同じく答えたものとして扱い、修正前の関所に載せず、保留の件数に数えず、出どころの単位を直す義務に戻す。報告の冒頭と最後の関所には『依頼者の答え: …』（手元で測った物は命令と出力つき）と並べ、どの問いにも当たらなかった答えも名指す。保留の問いが在る時は答え方を 1 行出す。判定役は、人が手元で打てば決まる命令を問いの理由に『測り方: `<命令>`』で書く。今までは、依頼者が依頼の文に書いた事実（並行する PR が無い等）も毎回人に聞く問いとして戻った」

- [ ] **Step 1: CHANGELOG に上の項目を足す**

- [ ] **Step 2: 速い段と根の柵を 1 回だけ通す**

Run: `works/` から `WORKS_TESTS=fast sh tests/run.sh`、根から `sh ~/.cache/works-dogfood/rootfences.sh`
Expected: どちらも失敗 0

- [ ] **Step 3: Commit**

```bash
git add works/CHANGELOG.md
git commit -m "docs(works): 依頼の answers を CHANGELOG に書く（依頼 240 Task 4）"
```

---

## この計画が扱わない物（理由つき）

- **(1) run が作った行の引き継ぎ（受け付けの拒否の理由・R2 の作り直しの理由・run が裁いた問い）。** 理由: 渡し先が決まっていない。独立設計は「同じ節を作る役へ・人に問う関所だけへ」と渡し分けを求め、findings に積むと判定役と独立の目に渡る（事前審査で 2 往復残った block）。渡し分けの口は、役の指示書への新しい入力と `darkfactory.yaml` の配線を要し、依頼 239 の形（部品の間の引き継ぎを宣言した文書で渡す）そのものなので、239 の形が入った後にその形で作る。あわせて事前審査 pass-2 が挙げた 2 つの穴も同じ計画で解く: 拒否のファイルは include（ブロックを線に差し込む単位）の置き場ごとに在り、報告の節の置き場からは見えない（`reject_reasons_read_from_report_scope_only`）・出し直して通った拒否まで積むと雑音になる（`carried_rejects_include_recovered_retries`。最後まで通らなかった節の最後の拒否だけを積む）。人が書く `answers` は、この口ができるまでの人の手の引き継ぎとして今すぐ効く。
- **(4) 同じ失敗が続いたら SDD・人の直書きへ渡す勧め。** 理由: 独立設計の決まり「今回の拒否・作り直しの行と同じ key・同じ理由の行が、前の run から引き継いだ依頼に既に在る」は (1) の引き継いだ行が前提で、(1) より先に作れない。回数のしきい値は独立設計と事前審査が退けた。さらに節「根本の原因」の 2 のとおり役の key は run ごとに字が変わるので、照らしの字を何に固定するかは (1) と一緒に決める。それまでは持ち主の運用の決まり「3 回落ちたら SDD」のまま。
- **答えを次の依頼の下書きへ機械が写すこと（`next-request.json` に answers を書く）。** 理由: 空欄の雛形が答え済みと読まれる穴と、engine が `oneOf` を読まない schema の穴を生む（事前審査 pass-2）。次の依頼は人が書き、答えも人が書く。
- **sandbox の許可を広げること（Unix ソケット等）。** 理由: 隔離を弱める判断は持ち主の物で、設定の正本は works の外。works は測れない物を「測り方」の命令と人の答えで受けるだけにする。
- **前提の役の 実測／仮説 の区分に「依頼者」を足すこと。** 理由: 依頼者の言明は人に聞く代わりにはなるが測りの代わりにはならない（独立設計）。区分は今のまま、依頼の実測を測り直せなかった行（`report._premise_hypotheses`）も今どおり出す。
