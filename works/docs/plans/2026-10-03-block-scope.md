# 部品の置き場を include の単位で分け、宣言した物だけを外に出す（依頼 239）Implementation Plan

状態: 入れた（works 0.2.23。`.shared/core/scopes.py`・`flow_adapter.py`・部品ごとの `manifest.json`）。

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

## この文書の読み方（初めて読む人向け。本文の語はここで全部定める）

読み手: この計画を 1 Task ずつ実装する役。リポジトリ（claude-plugins）を手元に持ち、名指したファイルを開いて確かめられる。「今の〜」は枝 `wip/sdd-239`（起点 b8783d8c = works 0.2.20）のコードのまま、の意味で、名指したファイルが正本。パスは断りが無ければリポジトリの根からの相対。文書の構成: 下の Goal〜Spec が全体、「設計からの外れ」が設計と違えた 5 点（外れ D1〜D5 と呼ぶ）、「Global Constraints」が全 Task に効く決まり、そのあと Task 1〜9 が実装の単位で、1 つの Task は前の Task の Interfaces（Produces）だけを頼りに読める。

依頼と番号:
- 依頼: works の直しを works 自身の工程（darkfactory の run）に流す頼みごとの 1 件。番号で呼ぶ。
- 依頼 239: この計画。部品（下のブロック）が決まりの外に盤面へ状態を持つため、同じ部品を 1 run で 2 度 include するとファイルがぶつかる。それを、部品ごとの置き場の分けと宣言した入出力の 1 つの決まりで直す。
- 依頼 226: 先に入った「同じ run の中で修正案の項目を直す道」。修正のブロック `blk-fix` を線に 2 度目に include し（`refitting`）、ぶつかりを下の回の印で避けた。この計画はその印を消して置き換える。

置き場と道具:
- works: `works/` のプラグイン。Archon（AI の作業の流れを YAML で回す外の道具。版 v0.11.1）の上で修正依頼を直す工程を回す。run は 1 回の実行。
- 線: `works/darkfactory/darkfactory.yaml`。節（YAML の nodes の 1 つ）の並び。線の最上段の script の節（`start`・境の節 `h-*`）は線そのものの仕事。
- ブロック（部品）: `works/blk-*/`。線が `include` の節で差し込む節の束。`include` の節の id（`fixing`・`refitting`・`planning`・`replanning` など）を **include の名** と呼ぶ。今の線は `blk-plan`（`planning`・`replanning`）と `blk-fix`（`fixing`・`refitting`）を 2 度 include する。
- 盤面: run ごとの状態の置き場 `$ARTIFACTS_DIR/board/`（Archon が run ごとに渡す置き場の下）。周（round）ごとの作業ファイルは `b.work(名)` が返す `board/r<N>/<名>`（`works/.shared/core/board.py:1710-1714`）。盤面の根には ほかに `state.json`・`record.json`・`trace.jsonl`・`out/`・`runs/`・`rounds/` などの記録と、受け付けの拒否の理由 `reject-<関数>-<連番>.txt`（`works/.shared/core/script_io.py` の `_write_reason`）が在る。
- 共通の口: ブロックのスクリプトが盤面に触る時に必ず通る core の関数。盤面を開く `entry.open_board`（`works/.shared/core/entry.py:172`）、受け付けの入口 `script_io.main`・`emit_result`、役の入口 `rolekit.script_main`、読んだ証拠の入口 `reads.main_for`。この計画は scope の処理をここにだけ置く。
- 回の印（pass tag）: 依頼 226 が足した場当たりの分け。2 度目の `blk-fix` の include（`refitting`）に YAML の入力 `pass_tag: "refit"` を渡し、`script_io.tagged(名, 印)` でファイルの名に `.refit` を足す。配線はスクリプト 8 本・lib 4 本・core 4 本に散り、`blk-fix/lib/ruling.py:41` の `rule-tree.json` は印を通らない（2 度目が 1 度目を上書きする穴）。
- 写し: `works/.shared/core/graphloops/`・`gl-prompts/` は本流 `graphloops/` のバイト単位の写し。手直しは台帳 `works/.shared/core/COPIED_FROM` の `!` 行だけ。この計画は写しを変えない。
- 試験の段: `works/tests/tiers.py` の FAST（速い段）と HEAVY（git・盤面・子のプロセスを使う段）。新しい試験の模块はどちらかに書く。

この計画の語:
- scope: 今の script が居る include の名。線の最上段なら空。値を返すのは `flow_adapter.current_scope()` だけ。
- scope の根: `board/<scope>/`（scope が空なら `board/` そのもの）。部品の私物（周ごとの物は `board/<scope>/r<N>/<名>`、周をまたぐ拒否の理由などは `board/<scope>/` の直下）を全部ここに置く。設計の S に当たる（外れ D1）。
- 公開の置き場: `board/r<N>/<名>`。今の作業ファイルの置き場そのもの。宣言した出力と、線の最上段の作業ファイルはここに置く（外れ D2）。
- 共有の記録: core が書き、どの scope の窓でも変わってよい盤面の物（`state.json`・`record.json`・`trace.jsonl`・`out/` など。全部は測り M2 で決める）。
- manifest: 部品ごとの宣言のファイル `works/<blk>/manifest.json`（線は `works/darkfactory/manifest.json`）。鍵は 3 つ: `consumes`（読む物。ほかの部品の出力を名と出どころの部品の名で指す。設計の Consumes）・`produces`（外に出す物。名と形 md か json。設計の Produces）・`private`（任意。書かなければ scope の根の中は全部私物）。形の正本は `works/.shared/core/manifest.schema.json`。
- per_include: Produces の 1 つの欄。真なら、その出力は公開の置き場でなく各 include の scope の根に残る（同じブロックの 2 つの include がそれぞれ出す読んだ証拠 `reads-<役>.json` のような物）。読む側は core の `scopes.each`・`scopes.all_rounds` で全部を集める。偽（既定）なら公開の置き場に置き、周ごとに書き手の scope は 1 つ。
- 窓: 1 つの scope が盤面を開いてから、別の scope（か線）が盤面を開くまでの間。照らし（Task 8・9）は窓の間の盤面の変化を見る。
- 適合テスト: `works/tests/test_block_scope.py`。同じブロックを 1 run で 2 度 include し、片方の include のファイルを他方が上書きしないことを見る（Task 2）。
- 測り M1〜M5: 設計が仮説のまま残した事を、実装の前に確かめる作業。M1〜M4 は Task 1、M5 は Task 9 の中。
- 運び役: 会話で SDD（superpowers の subagent-driven-development）を回す controller。台帳は `.superpowers/sdd/2026-10-03-block-scope/progress.md`（測りの結果もここ）。

---

**Goal:** 部品が盤面で読み書きしてよいのを「自分の scope の根・宣言した入力・宣言した出力」の 3 つに絞り、分けるのも照らすのも core の共通の口が 1 か所でやる。依頼 226 の回の印を、この置き場の分けに置き換えて消す。

**Architecture:**

- 置き場は根で分ける。`DiskBoard` に `scope` と、公開する名の集合 `published` を持たせ、`b.work(名)` は名が公開なら `board/r<N>/<名>`、そうでなければ `board/<scope>/r<N>/<名>` を返す。部品のコードは今のまま `b.work("rule-tree.json")` と書くだけで、2 度の include は自動で別の置き場に行く（印の付け忘れが構造上起きない）。scope が空なら全部今のパス。
- scope の出どころは `works/.shared/core/flow_adapter.py`（新しい core の模块。Archon に触る所を集める 1 つの口。口は current_scope・artifact_root・input・session_handle・resume の 5 つ）。Archon が include の名を script に渡すかは未測定なので Task 1 で測り、渡すならアダプタがそれを読み、渡さないなら include の節の YAML の入力 `include_id`（226 が `blk-fix`・`blk-plan` に足した物）を読む。どちらでも部品からは同じに見える。
- 宣言は manifest に書く。Produces は既定で公開の置き場に置き、持ち主は周ごとに 1 つの scope（`board/r<N>/scopes.json` に core が記録。2 つ目の書き手は落とす）。同じブロックの各 include がそれぞれ出す物は per_include で scope の根に残し、読む側（報告）は core の `scopes.each`・`scopes.all_rounds` で集める。
- 照らし: `entry.open_board` が開くたびに、開いている窓の scope の書き込みを照らす（scope の根・自分の公開の Produces・共有の記録の外の変化、持ち主の重なり、無い必須の Produces、Schema に合わない JSON の Produces を BoardGap で落とす）。全部品の manifest が揃った後（Task 9）にだけ繋ぐ。
- 回の印は、置き場の分けが効いた後（Task 5）に恒等にし、呼び出しを 1 本ずつ消し（Task 6）、YAML と本体を消す（Task 7）。印が持っていた意味「2 回目の修正の段か」は盤面の事実 `conflict.second_pass(b)`（今の周の裁定の行に案を直した印 amended が在るか）で引く。
- 聞き直しの道は塞がないが作らない: アダプタの session_handle・resume は NotImplementedError、`session.json`・`questions/`・`answers/` の形は文書と Schema だけ。新しい state の仕組みも、LangGraph 型の型つき state と reducer も作らない（設計 §8）。

**Tech Stack:** Python 3.12 以降の標準ライブラリ（`json`・`fnmatch`・`fcntl`・`hashlib`・`pathlib`・`os`）、写しの engine の `engine.schema.validate_schema`（JSON Schema の照らし）、Archon v0.11.1 の YAML（include・loop_group・approval）、unittest（`works/tests`）、線を本物のスクリプトで回す試験の器 `works/tests/scriptline.py`。

**Spec:** `/Users/p03623/.cache/works-dogfood/carry/239/spec.md`（darkfactory の設計だけの run 239 の独立設計。節を §0〜§10 で呼ぶ）。持ち主の決め（2026-10-03 の会話）は Global Constraints に書き写した。

## 設計からの外れ（どれも 1 つの軸「場合分けを足さず全体がより簡潔か」で選んだ。持ち主が退ければ Task 3・4 の前に戻す）

- **外れ D1（私物の並び）: 設計の `r<周>/<scope>/<名>` を `<scope>/r<周>/<名>` にする。** scope の根 `board/<scope>` を 1 つ決めれば、周ごとの作業ファイル（`<根>/r<N>/`）も周をまたぐ拒否の理由（`<根>/reject-*.txt`）も同じ根の下に入り、scope が空なら `board/""` = `board/` で今の置き場とバイトまで同じになる（分岐が無い）。設計どおりの並びでは、拒否の理由を周の置き場へ移すために `script_io` が周を知る必要が出て、空の scope の時だけ今の置き場に残す分岐も要る。盤面の根の物（`out`・`runs`・`r<N>`）と名がぶつかる危険は、scope の名の形の決まり（Task 3）と登録の確かめ（Task 5）で拒む。
- **外れ D2（Produces の置き場）: 設計の「Produces は S に書き、受け手の Consumes を YAML で scope に結び付け、rules の旧パスへは core が写しかリンクで公開する」を「Produces は初めから公開の置き場 `board/r<N>/<名>` に書き、持ち主を周ごとに 1 つ記録する」にする。** 受け手は今の `b.work(名)` のまま読め、YAML の結び付けも写しの手順も写す時刻の問題も要らない。rules・線の境の節・報告が今読んでいるパスもそのまま残る（設計 §4 の公開を全部の Produces に広げた形）。2 つの scope が同じ名を出せば持ち主の照らしが落とすので、設計 §1 の「黙った上書きでなく機械が止める」は保つ。同じブロックの各 include が出す物だけ per_include で scope の根に残す（報告が集める）。
- **外れ D3（照らしの単位と比べ方）: 窓ごと（`entry.open_board` の 1 か所）に、パス・大きさ・mtime_ns で比べる。ハッシュは取らない。** 設計 §2 の「prep で写し・accept で差」は prep と accept が部品ごとに違う関数で、共通の口にならない。`open_board` はどの部品のスクリプトも通るので、ここで窓を開け閉めすれば 1 か所で済む。ハッシュは盤面の全部を毎回読むので取らない（Task 9 の測り M5 で 1 回の写しの時間を控える）。窓の最後の script の書き込みは、次に盤面を開く節が照らす。線の最後の include（`reporting`）の最後の script の書き込みは照らさない（扱わない物）。
- **外れ D4（読みの照らし）: 宣言の外の読みは落とさず、trace と報告に載せるだけにする。** 読んだ証拠（`reads-<役>.json`）は受け付けの条件にしない、が今の決まり（`works/.shared/core/reads.py` の冒頭。本流 graphloops と同じ）。設計 §2 の 5 の「落とす」はこの決まりを変えるので、持ち主の決めを待つ（運び役の報告に上げる）。
- **外れ D5（線は照らさない）: 線の最上段（scope が空）は窓の照らしの外。** 決まりの相手は部品で、線の境の節は core の取りまとめ。線が書く作業ファイルは `darkfactory/manifest.json` の Produces に並べ、持ち主の照らし（部品が線の物を書き換えたら落とす）だけを効かせる。

## 設計の「未測定・仮説」の受け持ち（事実として扱わず、測ってから使う）

- Archon が script に include の名を渡すか・include の入力が輪の中の節まで届くか・ARTIFACTS_DIR が再開をまたいで同じか → Task 1 の M1。
- `rule-tree.json` のほかにぶつかるファイル・盤面の共有の記録（`state.json`・`record.json`・trace）の線引き・部品の外に読まれる名の全部 → Task 1 の M2、Task 2 の赤の一覧、Task 9 の M5（照らしを繋いだ時に落ちた物が実際の一覧）。
- rules（写しの graphloops と works の差し替え CORE_OVERRIDES）が前提にする盤面のパス → Task 1 の M3。
- 前例（Bazel・Nix・GitHub Actions・Mastra・LangGraph・superpowers）の内容 → Task 1 の M4（一次情報。食い違いは台帳に書き、採るかは持ち主）。
- Archon の会話の手がかり（provider_session_id）が session.json に当たるか → この計画では測らない。アダプタの session_handle の中に閉じ込め、作る時に測る（扱わない物）。

## Global Constraints

- 新しい state の仕組みを作らない。Archon の run の置き場（`$ARTIFACTS_DIR/board/`）に固め、その中を include の名で分け、部品の間は宣言したファイルで渡す（AI が読む物は `.md`、機械が照らす物は `.json` と JSON Schema）。LangGraph 型の型つき state・reducer は採らない（設計 §8）。
- scope の根は run の中で片付けない（後で調べるためと、将来の聞き直しのため。設計 §1）。撤収は run の置き場を丸ごと消すだけで、scope ごとに消す処理を作らない。
- 置き場の分け・登録・照らしは core の共通の口（`entry.open_board`・`script_io`・`reads.main_for`・`flow_adapter`・`scopes`）に 1 度だけ配線する。ブロックのコード（`works/blk-*/lib/`・`works/blk-*/scripts/`）には scope の処理を 1 行も書かない（Task 5 の `test_block_code_has_no_scope_code` が縛る）。
- 聞き直しのエッジは塞がないが今は作らない（session_handle・resume は NotImplementedError。形は Schema と文書だけ）。
- Archon に触る新しいコードは `flow_adapter` だけを通す。今ある INPUTS_* の読みの全部を寄せるのはこの計画の外（扱わない物に件数を書く）。
- superpowers（MIT）から型を写す時は表示を残す。manifest の Consumes／Produces は superpowers の writing-plans の Interfaces の節の型を写す。`works/.shared/core/manifest.schema.json` の description に出どころと `works/.shared/borrow/superpowers/6.4.2/LICENSE` を名指す。
- 本流 graphloops と写しは変えない。どうしても要れば `COPIED_FROM` の `!` 行（path・old・new・why）と `python3 works/dev/core-sync.py --check` の緑。この計画の Task はどれも写しを変えない。
- 言語ごとの表を作らない（manifest も照らしもファイルの名と形だけを見る）。
- 判断は 1 つの軸: 目的と keep-essence（`works/docs/keep-essence.md` の 11 項目）を保って、場合分けを足さずに全体がより簡潔か。
- 動いている途中の古い形の run は移し替えない（scope の在る開き方で古い盤面を開けば BoardMismatch。Task 5）。
- 期限・タイムアウトを足さない。`scopes.json` の読み書きの `fcntl.flock` は待つだけで期限を持たない。新しい script の節は足さない。
- 層（`works/tests/test_layers.py` の表 MOD）: `flow_adapter` は層 1（標準ライブラリだけ。works の物を何も知らない）、`scopes` は層 3。`script_io`（層 1）は `flow_adapter` だけを import し、`scopes` を import しない。`board` は `flow_adapter`・`scopes` を import しない（scope と公開の名は引数で受ける）。
- 新しい試験の模块は `works/tests/tiers.py` の FAST か HEAVY に書く（`test_scopes` は FAST、`test_block_scope` は HEAVY）。試験は `unittest.TestCase` のクラスの中（id は `<パス>::<クラス>::<名>`）。
- 新しい模块は `from __future__ import annotations` で始め、注記・docstring・エラー文は日本語。Python 3.12 が下限。
- この文書と `works/docs` に、まだ無い定数・消す定数を逆引用符で囲んだ大文字の名で書かない（根の `tests/run.sh` の doc-symbols の柵が赤になる。226 で起きた）。
- 焦点の試験: `cd works/tests && PYTHONDONTWRITEBYTECODE=1 python3 -m unittest <module>[.<Class>]`。YAML を変えた Task（5・7）と最後（9）の仕上げ: `WORKS_TESTS=fast nice -n 19 sh works/tests/run.sh`、`sh ~/.cache/works-dogfood/rootfences.sh`（根の `tests/run.sh` の速い柵だけを当てる殻）、`sh works/dev/check.sh`（Archon の模擬実行。赤の数が Task 1 で控えた起点の数を超えない）。重い段の全部は GitHub の CI。
- CHANGELOG は `works/CHANGELOG.md` の `[Unreleased]` だけに足す（Task 9）。版は上げない。commit のメッセージは日本語で、末尾に `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`。push しない。

## Review Focus

1. Archon の再開で、落ちた include が同じ周にもう一度走る → 同じ scope・同じブロックの登録は通り、窓の写しを取り直さない（1 回目の書き込みも窓に残る）。（Task 5 の `test_claim_same_scope_same_block_twice_is_ok`、Task 9 の `test_enter_same_scope_again_keeps_window`）
2. この版より前に始まった run の盤面を、新しい版で scope を持って開く → 移し替えずに BoardMismatch で止まる（scope が空の開き方は今どおり通る）。（Task 5 の `test_old_board_refused_when_scoped`）
3. 2 つの include が同じ scope を名乗る（YAML の写し間違い・別のブロックが同じ名）→ 線の形の試験と登録が止める。（Task 5 の `test_every_include_names_its_own_scope`・`test_claim_other_block_same_scope_refused`）
4. 公開の名を 2 つ目の scope が書く（2 回目の修正の段が 1 回目の控えを書き直す）→ 窓の照らしが両方の scope とパスを名指して落とす。（Task 8 の `test_second_owner_of_published_name_refused`）
5. scope の名が盤面の根の物とぶつかる・パスを抜ける（`r2`・`out`・`a/b`・`..`）→ 盤面を開く前に拒む。（Task 3 の `test_bad_scope_names_refused`、Task 5 の `test_claim_refuses_root_entry_that_is_not_a_scope`）

## ファイルの地図

- 作る: `works/.shared/core/flow_adapter.py`（Archon の口）・`works/.shared/core/scopes.py`（manifest の読み・登録・集め・照らし）・`works/.shared/core/manifest.schema.json`・`works/.shared/core/session.schema.json`（形だけ）・`works/blk-*/manifest.json`（16 個）・`works/darkfactory/manifest.json`・JSON の Produces の Schema `works/<blk>/schemas/<名>.schema.json`・`works/tests/test_scopes.py`・`works/tests/test_block_scope.py`。
- 変える（主な物）: `works/.shared/core/board.py`（scope・published・work）・`entry.py`（open_board・start）・`script_io.py`（拒否の置き場・回の印を消す）・`reads.py`・`recount.py`・`refix.py`・`prcheck.py`（READS から include の名を消す）・`report.py`（全周の集め）・`leftovers.py`・`conflict.py`・`works/blk-fix/lib/{fixrules,ruling,fixgates}.py`・`works/blk-fix/scripts/*.py`・`works/blk-fix/blk-fix.yaml`・`works/darkfactory/darkfactory.yaml`・各 `works/blk-*/blk-*.yaml`（測り M1 の形 B・C の時）・`works/tests/scriptline.py`・`works/tests/test_layers.py`・`works/tests/tiers.py`・`works/docs/darkfactory-flow.md`・`works/CHANGELOG.md`。

---

### Task 1: 測り M1〜M4 と起点の控え（運び役。pack のコードを変えない）

**Files:**
- Create（台帳の置き場。commit しない）: `.superpowers/sdd/2026-10-03-block-scope/progress.md`・同じ置き場の `inventory.json`
- 測りの器: 依頼 226 の測り P4 で使った pack の写し（`<scratchpad>/p4/repo/.archon/workflows/p4pack`。起こし方は同じ置き場の `ar.sh`。P4 の記録は `/Users/p03623/src/claude-plugins-work1-sdd10/.superpowers/sdd/2026-10-03-in-run-replan/progress.md` の節「P4 measurement」。P4 は script の節だけの小さなブロック `blkx` を線 `p4line` が 2 度 include し、step の名が `<include>__<輪>.<節>` になること・include の最上段の関所が include ごとに止まって答えが届くことを確かめた）

**Interfaces:**
- Consumes: なし
- Produces（後の Task が台帳から読む）:
  - M1 の決め: 形 A（Archon が include の名か `<include>__…` の step の名を env で渡す。その変数の名と値の形）・形 B（include の節の `with:` の値がブロックの全部の節に INPUTS_* で届く。include の節に `include_id` を 1 つ書けば足りる）・形 C（どちらも無い。ブロックの全部の script の節の `with:` に `include_id: $INPUTS.include_id` を書く。今の `blk-fix` の形）のどれか 1 つ
  - M2 の表と `inventory.json`: `{"names": [{"name", "where": "work"|"root", "writers": [...], "readers": [...], "class": "private"|"published"|"per_include"|"shared"}]}`
  - M3 の一覧・M4 の照合・`sh works/dev/check.sh` の起点の赤の数

- [ ] **Step 1: M1（Archon v0.11.1）を測る**

P4 の pack の `blkx` に入力 `include_id`（default は空）と、全部の env を書き出す script の節（ブロックの最上段・輪の中・関所の後の 3 つ）を足し、線の最上段にも同じ節を 1 つ足す。`p4line` は `blkx` を 2 度 include し、1 度目は include の節の `with:` に `include_id: inc1` だけを渡し（節ごとの `with:` には書かない）、2 度目は何も渡さない。env は名を全部、値は名に TOKEN・KEY・SECRET・AUTH・PASS を含まない物だけを控える。1 度目の関所で止まった所で答えて再開させる。P4 の記録（env の頭で絞った控え）では、節の `with:` に無い INPUTS_ROUNDS が輪の中の節にも見えている。形 B の手がかりだが、確かめるまでは前提にしない。

確かめる事（台帳に字のまま）:
(a) include の名か `<include>__<輪>.<節>` の形を持つ env が在るか（在れば名と値）。
(b) include の節の `with:` の `include_id` が、節ごとの `with:` に無い節（最上段・輪の中）にも INPUTS_INCLUDE_ID で届くか。
(c) 渡さなかった 2 度目で、ブロックの入力の default（空）が届くか、変数ごと無いか。
(d) ARTIFACTS_DIR が止まる前と再開の後で同じ値か。
決め: (a) が在れば形 A、無くて (b) が真なら形 B、どちらも無ければ形 C。

- [ ] **Step 2: M2（盤面の名の棚卸し）を作る**

`works/.shared/core`・`works/blk-*/lib`・`works/blk-*/scripts`・`works/darkfactory` の全部の `b.work(…)` の名（式なら形 `prompt-*.md` のように）と、`b.dir /`・`board /`・`pathlib.Path(board_dir) /`・`leftovers._board_path` で盤面の根に書く名と、`report._all_rounds` の形を列挙する。名ごとに書き手（どの模块の、どのブロックか線から呼ばれる関数か）と読み手を grep で引き、class を 1 つの基準で振る: 書き手の include の外（ほかのブロック・線・報告・engine・rules）が読まない → `private`。読み、書く scope が周に 1 つ → `published`。同じブロックの各 include が書き、報告などが全部を集める → `per_include`。core が書き、複数の scope の窓で変わる記録（`state.json`・`record.json`・`trace.jsonl`・`out/**`・`runs/**`・`rounds/**`・`conflicts.json` の候補）→ `shared`。設計 §3 の予想（trace は追記式の共有の口・`state.json`・`record.json` は core が scope をキーに書く）はこの基準で確かめ、違えば違ったと書く。

- [ ] **Step 3: M3（rules の前提）を測る**

写しの `graphloops/engine`・`graphloops/rules` と `entry.CORE_OVERRIDES`・`darkfactory/board_hook.py` が盤面のどのパスを読み書きするかを列挙し、M2 で `private` に振った名を読む所が無いことを確かめる。在れば、その名を `published` に振り直す（rules は書き換えない）。

- [ ] **Step 4: M4（前例）を集めて照らす**

集める役（Sonnet）に URL と抜き書きだけを集めさせる: Bazel（宣言していない出力が失敗になるか・出力の置き場）、Nix（入力の宣言・`$out`・サンドボックス）、GitHub Actions（step・job の outputs・名前つき artifact・再利用 workflow の outputs）、Mastra（step の inputSchema・outputSchema・stateSchema・suspend と resume）、LangGraph（state の channel・reducer・subgraph・checkpointer）、superpowers（writing-plans の Interfaces の節・LICENSE）。判断（opus）は外れ D1〜D5 と設計 §8 に照らし、食い違いを台帳に書く。Task 2〜8 はこれを待たない。

- [ ] **Step 5: 起点を控える**

Run: `sh works/dev/check.sh 2>&1 | tail -5`
台帳に赤の数を書く（Task 5・7・9 の仕上げの上限）。

---

### Task 2: 適合テスト（今は赤。expectedFailure で入れる）

**Files:**
- Create: `works/tests/test_block_scope.py`（HEAVY。`works/tests/tiers.py` の HEAVY に足す）
- Modify: `works/tests/scriptline.py`（`ScriptLine` に include の節の前後の呼び返し `watch`）

**Interfaces:**
- Consumes: `scriptline.ScriptLine`・`scriptline.default_reply`、案の直しまで進む返答の組み手（`works/tests/test_replan.py` の `TestLineReplay`・`TripCase` が使う返答の関数。`import test_replan as tr` で引き、クラスを名で import しない）、M2 の `shared` の名
- Produces:
  - `ScriptLine.__init__(…, watch: Callable[[str, str], None] | None = None)` — 線の最上段の include の節ごとに、走らせる直前に `watch(<節の id>, "start")`、出口が ok の直後に `watch(<節の id>, "done")` を呼ぶ（`_include` の前後。飛ばした節では呼ばない）
  - 試験の中の共有の記録の形の組（M2 の `shared` を fnmatch の形で字のまま。Task 9 で `scopes` の定数に替える）
  - `snapshot(board: Path) -> dict[str, str]`（盤面の下の全部のファイルの相対パス → sha256）と `clobbered(snaps, first: str, second: str, shared) -> list[str]`（`first` の窓で作った・変えたファイルのうち、共有の記録の外で、`second` の窓の前後で中身が違う物の相対パス。名の順）

- [ ] **Step 1: 落ちる試験を書く**

```python
class TwoIncludesCase(unittest.TestCase):
    """同じブロックを 1 run で 2 度 include する偽の run（線 darkfactory を本物のスクリプトで回す）。
    修正役が申し出を返し → 裁定 fix_plan_item → 案の直し（replanning）→ 関所 replan-gate は continue → 2 回目の修正（refitting）→ 報告"""

    @classmethod
    def setUpClass(cls):
        ...  # 一時の置き場で ScriptLine(..., watch=記録する関数).run() を 1 度だけ回し、cls.got と cls.snaps[(節, "start"|"done")] に置く

    def test_run_reaches_report(self):
        self.assertTrue(self.got["completed"], self.got["failure"])
        self.assertIn("darkfactory/reporting", self.got["trail"])
        self.assertIn(("refitting", "done"), self.snaps)      # 2 度目の blk-fix まで走った
        self.assertIn(("replanning", "done"), self.snaps)     # 2 度目の blk-plan まで走った

    @unittest.expectedFailure   # Task 5 で外す（置き場の分けが効くまでは rule-tree.json を上書きする）
    def test_second_include_overwrites_nothing_of_first(self):
        for first, second in (("planning", "replanning"), ("fixing", "refitting")):
            with self.subTest(first=first, second=second):
                self.assertEqual(clobbered(self.snaps, first, second, SHARED), [],
                                 f"{second} が {first} のファイルを上書きした")
```

- [ ] **Step 2: 赤の中身を確かめる**

Run: `cd works/tests && PYTHONDONTWRITEBYTECODE=1 python3 -m unittest test_block_scope -v`
Expected: `test_run_reaches_report` は ok。`test_second_include_overwrites_nothing_of_first` は expected failure で、`fixing` の組の一覧に `r1/rule-tree.json` を含む（ほかの名が出れば台帳の M2 の表と照らし、`private` に振った名なら表のとおり、表に無い名なら表に足す）。一時に `expectedFailure` を外して回し、一覧を台帳に字のまま写してから戻す。

- [ ] **Step 3: 段の一覧を通す**

Run: `cd works/tests && PYTHONDONTWRITEBYTECODE=1 python3 -m unittest test_tiers test_script_contract`
Expected: PASS（`watch` を渡さない今の使い方は変わらない）

- [ ] **Step 4: Commit**

```bash
git add works/tests/test_block_scope.py works/tests/scriptline.py works/tests/tiers.py
git commit -m "test(works): 同じブロックを 1 run で 2 度 include して上書きを見る適合テストを足す（今は rule-tree.json で落ちるので expectedFailure。239 Task 2）"
```

---

### Task 3: 盤面の scope（既定は空。振る舞いを変えない）

**Files:**
- Modify: `works/.shared/core/board.py`（`DiskBoard.__init__`・`open`・`scratch` の keyword、`work`、`scope_root`、`_write_trace`）
- Test: `works/tests/test_board_open.py`（新しい class `ScopeCase`）

**Interfaces:**
- Consumes: 今の `DiskBoard`・`Board.work`・写しの engine の `Board._write_trace(row)`
- Produces:
  - `DiskBoard.__init__(d, *, state, record, table, overrides=None, validator_runner=None, allow_halted=False, scratch=False, scope: str = "", published: frozenset[str] = frozenset())`。`DiskBoard.open(…)` も同じ 2 つの keyword を受けて渡す。`scratch` は渡された盤面の scope を継がない（空）
  - `DiskBoard.scope: str`・`DiskBoard.published: frozenset[str]`（fnmatch の形の名の集合）
  - `DiskBoard.scope_root -> pathlib.Path`（property。`self.dir / self.scope`）
  - `DiskBoard.work(name: str) -> pathlib.Path` — 名が `published` のどれかの形に合う（`fnmatch.fnmatchcase`）か scope が空なら `dir/r<N>/<name>`、そうでなければ `dir/<scope>/r<N>/<name>`。親を作るのは今どおり
  - scope の名の形: 空か、`^[A-Za-z][A-Za-z0-9_-]*$` に合い `^r\d+$` に合わない字。外れれば `ValueError`（文に名と決まりを載せる）
  - `DiskBoard._write_trace(row)` — scope が空でなければ行に鍵 `scope` を足してから写しの `_write_trace` を呼ぶ（空なら今のバイトのまま。盤面の golden を変えない）

- [ ] **Step 1: 落ちる試験を書く**

```python
class ScopeCase(TmpCase):
    def test_empty_scope_keeps_today_paths(self):
        b = ...  # 今の試験の型で開いた盤面（scope を渡さない）
        self.assertEqual(b.work("rule-tree.json"), b.dir / "r1" / "rule-tree.json")
        self.assertEqual(b.scope_root, b.dir)
        b.trace("probe"); self.assertNotIn("scope", last_trace_row(b))

    def test_scoped_private_name_goes_under_scope_root(self):
        b = ...  # scope="fixing"
        self.assertEqual(b.work("rule-tree.json"), b.dir / "fixing" / "r1" / "rule-tree.json")
        self.assertEqual(b.scope_root, b.dir / "fixing")

    def test_published_name_stays_in_round_place(self):
        b = ...  # scope="fixing", published=frozenset({"fix-held-reply.json", "prompt-*.md"})
        self.assertEqual(b.work("fix-held-reply.json"), b.dir / "r1" / "fix-held-reply.json")
        self.assertEqual(b.work("prompt-p3.fix.md"), b.dir / "r1" / "prompt-p3.fix.md")

    def test_trace_row_carries_scope_when_scoped(self):
        b = ...  # scope="refitting"
        b.trace("probe"); self.assertEqual(last_trace_row(b)["scope"], "refitting")

    def test_bad_scope_names_refused(self):
        for s in ("r2", "a/b", "..", "x y", "-x", "1fix"):
            with self.subTest(s=s), self.assertRaises(ValueError):
                ...  # scope=s で開く
```

- [ ] **Step 2: 落ちることを確かめる**

Run: `cd works/tests && PYTHONDONTWRITEBYTECODE=1 python3 -m unittest test_board_open.ScopeCase`
Expected: FAIL（`TypeError: … unexpected keyword argument 'scope'`）

- [ ] **Step 3: `DiskBoard` に scope と published を足す**（`board` は `flow_adapter`・`scopes` を import しない）

- [ ] **Step 4: 通ることと、今の盤面が変わらないことを確かめる**

Run: `cd works/tests && PYTHONDONTWRITEBYTECODE=1 python3 -m unittest test_board_open test_board_goldens_fixture test_board_replay test_block_scope`
Expected: PASS（`test_block_scope` の上書きの試験は expected failure のまま）

- [ ] **Step 5: Commit**

```bash
git add works/.shared/core/board.py works/tests/test_board_open.py
git commit -m "feat(works): 盤面に scope と公開の名を足す（既定は空で今の置き場のまま。239 Task 3）"
```

---

### Task 4: アダプタ・manifest・公開の名（まだ配線しない）

**Files:**
- Create: `works/.shared/core/flow_adapter.py`・`works/.shared/core/scopes.py`・`works/.shared/core/manifest.schema.json`・`works/.shared/core/session.schema.json`・`works/blk-*/manifest.json`（16 個）・`works/darkfactory/manifest.json`・`works/<blk>/schemas/<名>.schema.json`（JSON の Produces ごと）
- Modify: `works/tests/test_layers.py`（MOD に `"flow_adapter": (1, None)`・`"scopes": (3, None)`）・`works/tests/tiers.py`（FAST に `test_scopes`）
- Test: `works/tests/test_scopes.py`（class `AdapterCase`・`ManifestCase`）

**Interfaces:**
- Consumes: 台帳の M1 の形・`inventory.json`（M2）・M3 の一覧、`engine.schema.validate_schema`、`board.BoardGap`
- Produces:
  - `flow_adapter.current_scope() -> str` — 形 A は M1 で見た env の値から include の名を取り出す。形 B・C は env INPUTS_INCLUDE_ID の値。無い・空は `""`
  - `flow_adapter.artifact_root() -> pathlib.Path | None` — env ARTIFACTS_DIR（無い・空は None）
  - `flow_adapter.input(name: str) -> str | None` — env `INPUTS_<NAME の大文字>`
  - `flow_adapter.session_handle() -> dict`・`flow_adapter.resume(handle: dict, prompt: str) -> str` — どちらも `NotImplementedError("聞き直しはまだ作らない（依頼 239 の §5。形は session.schema.json）")`。docstring に設計 §5 の形（`<scope の根>/r<N>/session.json`・`questions/<相手 scope>/<連番>.md`・`answers/<問いの scope>/<連番>.md`）と、口の内に入れる物・外に残る物（設計 §6 の列挙）を書く
  - manifest の形（`manifest.schema.json`。additionalProperties は false）: `{"owner": <ブロックか線のフォルダの名>, "consumes": [{"name": <名か fnmatch の形>, "from": <ブロックか線のフォルダの名>}], "produces": [{"name", "format": "md"|"json", "schema"?: <owner のフォルダからの相対パス>, "per_include"?: bool（既定 false）, "required"?: bool（既定 false）}], "private"?: [<名>]}`。`format` が json の Produces は `schema` 必須（Schema の条件で縛る）
  - `session.schema.json`: `{"tool": str, "handle": object}`（形だけ。誰も書かない）
  - `scopes.PACK: pathlib.Path`（`works/`）
  - `scopes.ManifestBroken(BoardGap)`
  - `scopes.manifest(owner_dir: pathlib.Path) -> dict` — 読んで Schema に当てる。無い・読めない・合わない・`owner` がフォルダの名と違うは `ManifestBroken`（パスと誤りを全部載せる）
  - `scopes.manifests(pack: pathlib.Path = PACK) -> dict[str, dict]` — `blk-*/` と `nodes.json` を持つ線のフォルダの全部（owner の名 → manifest）
  - `scopes.published(pack: pathlib.Path = PACK) -> frozenset[str]` — per_include でない Produces の名の和
  - `scopes.owner_of(name: str, pack: pathlib.Path = PACK) -> str | None` — その名を per_include でなく出す owner

- [ ] **Step 1: 落ちる試験を書く**

```python
class AdapterCase(unittest.TestCase):
    def test_current_scope_reads_measured_source(self):
        # 形 B・C: {"INPUTS_INCLUDE_ID": "refitting"} → "refitting"、変数が無い → ""、空 → ""
        # 形 A: M1 で見た変数と値の形 → include の名、無い → ""
    def test_artifact_root_none_when_missing_or_empty(self): ...
    def test_input_reads_inputs_env(self):
        # {"INPUTS_JUDGMENT_FILE": "/x"} → input("judgment_file") == "/x"、無い → None
    def test_ask_back_mouths_not_built(self):
        with self.assertRaises(NotImplementedError): flow_adapter.session_handle()
        with self.assertRaises(NotImplementedError): flow_adapter.resume({}, "q")
    def test_ask_back_mouths_have_no_callers(self):
        # works/ の .py（tests を除く）に session_handle( と resume( を呼ぶ所が flow_adapter.py の外に無い

class ManifestCase(unittest.TestCase):
    def test_every_owner_has_valid_manifest(self):
        # blk-* の 16 個と darkfactory の全部で scopes.manifest が通り、owner がフォルダの名
    def test_published_name_has_one_owner(self):
        # per_include でない Produces の名（形）が 2 つの owner に出ない
    def test_consumes_point_at_a_producer(self):
        # どの consumes {name, from} も、from の manifest の produces に同じ name が在る
    def test_json_produces_have_schema(self):
        # format json の Produces の schema のファイルが在り、JSON Schema として読める
    def test_inventory_names_are_declared(self):
        # 試験の中に字のまま写した M2 の published・per_include の名が、どれかの manifest の produces に在る
    def test_borrowed_shape_keeps_notice(self):
        # manifest.schema.json の description が writing-plans と ".shared/borrow/superpowers/6.4.2/LICENSE" を名指し、そのファイルが在る
    def test_broken_manifest_names_path_and_errors(self):
        # 一時のフォルダに owner の違う・鍵の足りない manifest → ManifestBroken の文にパスと誤りの全部
```

- [ ] **Step 2: 落ちることを確かめる**

Run: `cd works/tests && PYTHONDONTWRITEBYTECODE=1 python3 -m unittest test_scopes`
Expected: FAIL（`ModuleNotFoundError: No module named 'flow_adapter'`）

- [ ] **Step 3: アダプタと `scopes` の読み口を書き、M2 の表から manifest と Schema を書く**

Produces・Consumes に載せるのは M2 で `published`・`per_include` に振った名だけ（`private` は書かない。既定で私物）。線の境の節が書いてブロックが読む名は `darkfactory/manifest.json` の Produces。JSON の Produces の Schema は書き手の今の形（docstring と書く所の鍵）から起こし、`additionalProperties` は閉じない（今の書き手を落とさない）。条件つきでしか出ない物（控え `fix-held-reply.json` など）は `required` を書かない。

- [ ] **Step 4: 通ることを確かめる**

Run: `cd works/tests && PYTHONDONTWRITEBYTECODE=1 python3 -m unittest test_scopes test_layers test_tiers`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add works/.shared/core/flow_adapter.py works/.shared/core/scopes.py works/.shared/core/manifest.schema.json works/.shared/core/session.schema.json works/blk-*/manifest.json works/blk-*/schemas works/darkfactory/manifest.json works/tests/test_scopes.py works/tests/test_layers.py works/tests/tiers.py
git commit -m "feat(works): 流れの道具の口 flow_adapter と、部品ごとの宣言 manifest・公開の名の読み口を足す（まだ配線しない。239 Task 4）"
```

---

### Task 5: 共通の口に scope を配線する（適合テストが通る）

**Files:**
- Modify: `works/.shared/core/entry.py`（`open_board`・`start`）・`scopes.py`（`claim`・`running_block`・`all_rounds`・`each`）・`script_io.py`（`board_dir`・拒否の置き場・`scope_dir`）・`leftovers.py`（盤面の根の物を scope の根へ）・`reads.py`（`main_for` から include の引数を消す）・`recount.py`・`refix.py`・`prcheck.py`（READS の include の名を消す）・`report.py`（`_all_rounds` を `scopes.all_rounds` に）・`works/blk-fix/scripts/{reads,rule_prep,rule_accept,fix_prep,accept}.py`（INPUTS_INCLUDE_ID を消す）・`works/blk-fix/blk-fix.yaml`・`works/blk-plan/blk-plan.yaml`・`works/darkfactory/darkfactory.yaml`・形 B・C なら全部の `works/blk-*/blk-*.yaml`・`works/tests/scriptline.py`・`works/tests/linekit.py`（直に呼ぶ口に scope を渡す所が在れば）
- Test: `works/tests/test_scopes.py`（class `ClaimCase`）・`test_entry.py`・`test_script_io.py`・`test_line.py`・`test_report.py`・`test_layers.py`（KNOWN の V5・V6・V7 を消す。どれも READS に書いた include の名の当座の許し）・`test_block_scope.py`（expectedFailure を外す）

**Interfaces:**
- Consumes: Task 3 の `DiskBoard(scope=, published=)`・`scope_root`、Task 4 の `flow_adapter.current_scope`・`artifact_root`・`scopes.published`・`scopes.manifests`
- Produces:
  - `script_io.scope_dir(board: pathlib.Path) -> pathlib.Path` — `board / flow_adapter.current_scope()`（盤面の根に書く私物の置き場。拒否の理由と `leftovers` の控えはここ）。`board_dir()` は ARTIFACTS_DIR を `flow_adapter.artifact_root()` で読む（柵は今どおり）
  - `scopes.running_block() -> str` — `sys.argv[0]` が `<pack>/<名>/scripts/<x>.py` なら `<名>`、ほかは `""`
  - `scopes.claim(board_dir: pathlib.Path, round_: int, scope: str, block: str) -> None` — `board/r<N>/scopes.json`（`{<scope>: {"block": <名>, "order": <登録の順>}}`）に `fcntl.flock`（`scopes.json.lock`）の下で足す。同じ scope・同じ block は何もしない。同じ scope・別の block は BoardGap（両方の block の名）。盤面の根に scope の名の物が在り、どの周の `scopes.json` にも無ければ BoardGap（根の物とぶつかる）
  - `scopes.all_rounds(board_dir: pathlib.Path, pattern: str) -> list[pathlib.Path]` — `board/r*/<pattern>` と `board/<scope>/r*/<pattern>` の全部（周の順、同じ周は登録の順）
  - `scopes.each(b, name: str) -> list[pathlib.Path]` — 今の周の `scopes.json` の登録の順に、各 scope の根の `r<N>/<name>` で在る物
  - `entry.open_board(board_dir, *, allow_halted=False) -> DiskBoard` — scope = `flow_adapter.current_scope()`。空でなければ、`state.works.layout` が `"scope-1"` でない盤面は BoardMismatch（「この版より前の盤面。移し替えない」）、そうでなければ `scopes.claim(d, state["round"], scope, scopes.running_block())`。`DiskBoard.open(…, scope=scope, published=scopes.published())`
  - `entry.start` が作る盤面の `state.works.layout = "scope-1"`
  - `reads.main_for(role: str, loop: str, node: str, *, more=None) -> int` — 出来事を引く include の名は `flow_adapter.current_scope()`（空なら標準エラーに 1 行で 2）。`recount.READS`・`refix.READS` の値・`prcheck.READS` は (役, 輪, 節) の 3 つ
  - YAML（M1 の形で 1 つ）: 形 A は変えない。形 B は全部のブロックに入力 `include_id`（default は空）を置き、線の全部の include の節が `include_id: "<自分の id>"` を渡し、節ごとの `include_id: $INPUTS.include_id` を消す。形 C は形 B に加えて、全部の script の節の `with:` に `include_id: $INPUTS.include_id`
  - `ScriptLine`: Archon と同じ形で scope を渡す（形 A は M1 の変数を include の中の節にだけ、形 B・C は今の INPUTS_* の解き方のまま）

- [ ] **Step 1: 落ちる試験を書く**

```python
# test_scopes.py
class ClaimCase(unittest.TestCase):
    def test_claim_same_scope_same_block_twice_is_ok(self): ...      # 2 度目も通り、scopes.json は 1 行
    def test_claim_other_block_same_scope_refused(self): ...         # BoardGap の文に "blk-fix" と "blk-plan"
    def test_claim_refuses_root_entry_that_is_not_a_scope(self): ... # board/out が在る盤面で scope "out" → BoardGap
    def test_all_rounds_covers_scoped_files(self): ...               # r1/reads-x.json・fixing/r1/reads-fix.json・refitting/r1/reads-fix.json の 3 つを周と登録の順で

# test_entry.py
    def test_open_board_scoped_places_private_names_under_scope(self):
        # env に scope（M1 の形）を置いて open_board → b.work("rule-tree.json") が board/<scope>/r1/、
        # 公開の名 fix-held-reply.json は board/r1/、board/r1/scopes.json に scope と block
    def test_old_board_refused_when_scoped(self):
        # state.works から layout を消した盤面を scope つきで開く → BoardMismatch。scope なしでは開ける

# test_script_io.py
    def test_reject_goes_to_scope_dir(self):
        # scope つきの env で拒否 → reason_file が board/<scope>/reject-…-1.txt。scope なしは board/reject-…-1.txt（今どおり）

# test_line.py
    def test_every_include_names_its_own_scope(self):
        # 形 B・C: 線の全部の include の節の with.include_id が自分の id と同じ（形 A: 試験は Archon の include の id の一意だけを見る）
    def test_block_code_has_no_scope_code(self):
        # works/blk-*/lib・works/blk-*/scripts の .py に "flow_adapter"・"import scopes"・"INCLUDE_ID" が無い

# test_report.py
    def test_reads_lines_cover_scoped_reads(self):
        # fixing と refitting の scope の根に reads-fix.json を置いた盤面 → report.head_reads の行に両方
```

`test_block_scope.TwoIncludesCase.test_second_include_overwrites_nothing_of_first` の `@unittest.expectedFailure` を外す。

- [ ] **Step 2: 落ちることを確かめる**

Run: `cd works/tests && PYTHONDONTWRITEBYTECODE=1 python3 -m unittest test_scopes.ClaimCase test_entry test_script_io test_line test_report test_block_scope`
Expected: FAIL（`AttributeError: module 'scopes' has no attribute 'claim'` ほか。`test_block_scope` は `r1/rule-tree.json` を名指して落ちる）

- [ ] **Step 3: 共通の口を配線する**（ブロックのコードには scope を書かない。印 `pass_tag` はまだ残す）

- [ ] **Step 4: 通ることを確かめる**

Run: `cd works/tests && PYTHONDONTWRITEBYTECODE=1 python3 -m unittest test_scopes test_entry test_script_io test_line test_report test_reads test_layers test_replan test_blk_fix test_blk_fix_conflict test_blk_fix_tdd test_blk_plan test_script_contract test_block_scope`
Expected: PASS（`test_block_scope` の 2 つとも ok）

- [ ] **Step 5: 組の仕上げ**

Run: `WORKS_TESTS=fast nice -n 19 sh works/tests/run.sh` と `sh ~/.cache/works-dogfood/rootfences.sh` と `sh works/dev/check.sh`
Expected: 前の 2 つは緑。`check.sh` の赤は Task 1 の起点の数以下

- [ ] **Step 6: Commit**

```bash
git add works/.shared/core works/blk-*/ works/darkfactory works/tests
git commit -m "feat(works): 盤面を開く口で include の名を scope にし、私物を scope の根へ分ける（適合テストが通る。239 Task 5）"
```

---

### Task 6: 回の印を恒等にし、呼び出しを 1 本ずつ消す

**Files:**
- Modify: `works/.shared/core/script_io.py`・`conflict.py`・`recount.py`・`works/blk-fix/lib/{fixrules,ruling,fixgates}.py`・`works/blk-fix/scripts/{accept,clean,ignored_before,collect,reads,fix_prep,rule_prep,rule_accept}.py`
- Test: `works/tests/test_replan.py`（class `TestSecondPass` に 1 つ。回の印の名を見ている試験は scope の根のパスに替える）・`test_fix_gates.py`・`test_fix_rules.py`・`test_blk_fix_conflict.py`・`test_script_io.py`

**Interfaces:**
- Consumes: Task 5 の scope の根の分け（印が無くても 2 度目の include は別の置き場に書く）
- Produces（印の引数を消した後の形）:
  - `conflict.second_pass(b) -> bool` — 今の周の裁定の行に `replan_state(行) == AMENDED` が 1 つでも在る。印が持っていた意味の置き換えで、`fixgates.problems` の `_test_edits` の第 5 引数（`pass_ == "ruled" or conflict.second_pass(b)`）と `conflict.write_rulings` の遅い案の直しの約束の条件（`second_pass(b) and state == WAITING`）が読む
  - `script_io.reject_name(fn, n) -> str`・`script_io.last_reject(board, fn) -> str`（`scope_dir(board)` の下を見る）・`script_io.emit_result(board, fn, out) -> int`・`script_io.main(fn, reply_env="INPUTS_REPLY", *, finish=None) -> int`
  - `recount.main_accept(fn=accept_fix, *, finish=None) -> int`・`recount.collect(board, accepted: dict, changed: dict) -> dict`（読んだ証拠は今の scope の `reads-fix.json`）
  - `fixrules.prompt_path(b) -> Path`・`fixrules.last_reject(board_dir) -> str`・`fixrules.implementer_values(b, values, repo, owed) -> dict[str, str]`・`fixrules.g1_values(b, values, repo, owed, base_rev) -> list[dict]`・`fixrules.prep(board_dir, repo, values, pass_=PASSES[0]) -> dict`・`fixrules.reads_more(board) -> list`
  - `ruling.prep(board_dir, repo, values) -> dict`
  - `conflict.apply_rulings(b, rulings, *, by) -> Path`・`conflict.write_rulings(b) -> Path`
  - `fixgates.problems(board_dir, repo, base_rev, suite, attempt, *, pass_="first") -> list[dict]`・`fixgates.skipped(board_dir, *, pass_, attempt) -> list[str]`・`fixgates.unchecked(board_dir, *, pass_, attempt) -> list[str]`（帳面の行の鍵 `tag` は書かない。帳面は scope ごとに分かれる）

- [ ] **Step 1: 落ちる試験を書く**

```python
class TestSecondPass(TripCase):
    def test_second_pass_fact_follows_amended_rows(self):
        b = ...  # 裁定の行が無い盤面
        self.assertFalse(conflict.second_pass(b))
        ...      # fix_plan_item の行を WAITING で置く
        self.assertFalse(conflict.second_pass(b))
        ...      # その行を AMENDED にする（今の replan.answer の道）
        self.assertTrue(conflict.second_pass(b))
```

Run: `cd works/tests && PYTHONDONTWRITEBYTECODE=1 python3 -m unittest test_replan.TestSecondPass.test_second_pass_fact_follows_amended_rows`
Expected: FAIL（`AttributeError: … 'second_pass'`）

- [ ] **Step 2: `conflict.second_pass` を書き、印の意味の 2 か所をそれに替える**

Run: `cd works/tests && PYTHONDONTWRITEBYTECODE=1 python3 -m unittest test_replan test_fix_gates test_block_scope`
Expected: PASS → Commit（`refactor(works): 2 回目の修正の段かを回の印でなく裁定の行の事実で引く（239 Task 6）`）

- [ ] **Step 3: `script_io.tagged` を恒等（名をそのまま返す）にする**

印の名（`reads-fix.refit.json`・`prompt-p3.fix.refit.md` など）を見ている試験を、`refitting` の scope の根の同じ名に替える（中身の期待は変えない）。
Run: `cd works/tests && PYTHONDONTWRITEBYTECODE=1 python3 -m unittest test_replan test_blk_fix_conflict test_blk_fix_tdd test_fix_rules test_fix_gates test_script_io test_block_scope`
Expected: PASS → Commit（`refactor(works): 回の印を恒等にする（置き場の分けが 2 回目の段のファイルを分ける。239 Task 6）`）

- [ ] **Step 4: 呼び出しを組ごとに消す。組ごとに焦点の試験と `test_block_scope` を回し、緑で commit する**

組（この順）:
1. 拒否の理由（`script_io.reject_name`・`last_reject`・`_write_reason`・`emit_result`・`main` の `tag`、`recount.main_accept` の `tag`、`ruling._last_reject`・`fixrules.last_reject` の印）
2. 修正役の支度（`fixrules.prompt_path`・`implementer_values`・`g1_values`・`prep`・`reads_more` の印）
3. 裁定の輪（`ruling.prep` と `accept_rule` の印、`conflict.apply_rulings`・`write_rulings` の `pass_tag`）
4. 受け付け（`blk-fix/scripts/accept.py` の `_tag()` と、申し出の回の控え・裁定の文・git が無視するファイルの控えの名を包む印）
5. 片付け（`clean.py`・`ignored_before.py` の印。名は `leftovers` の既定のまま、置き場は `script_io.scope_dir`）
6. 読んだ証拠（`recount.collect` の `tag`・`recount.reads_role` の呼び出し・`blk-fix/scripts/{collect,reads}.py` の印）
7. 試験の帳面（`fixgates.problems`・`skipped`・`unchecked`・`_mark` の `tag`、一式のログの名の印）

各組の Run: `cd works/tests && PYTHONDONTWRITEBYTECODE=1 python3 -m unittest <組の試験の模块> test_block_scope`
Expected: PASS。commit のメッセージは `refactor(works): 回の印の呼び出しを消す——<組の名>（239 Task 6）`

---

### Task 7: 回の印の残り（YAML の入力・環境変数・本体）を消す

**Files:**
- Modify: `works/blk-fix/blk-fix.yaml`（入力 `pass_tag` と 10 か所の `pass_tag: $INPUTS.pass_tag`、description の印の文）・`works/darkfactory/darkfactory.yaml`（`refitting` の `pass_tag: "refit"` と注記）・`works/blk-fix/scripts/*.py`（INPUTS と OPTIONAL の組から INPUTS_PASS_TAG）・`works/.shared/core/script_io.py`（`tagged` と印の字の決まりを消す）・`works/.shared/core/recount.py`（`reads_role` を消す）・`works/blk-fix/lib/fixrules.py`（`tagged` の別名と docstring）・`works/.shared/core/leftovers.py`・`conflict.py` の docstring の印の文
- Test: `works/tests/test_line.py`・`test_script_contract.py`・`test_blk_fix_tdd.py`・`test_blk_fix_conflict.py`・`test_replan.py`（印を env に置く helper）・`tests/linekit.py`・`tests/scriptline.py`（在れば）・新しい試験 `test_line.LineShapeCase.test_no_pass_tag_left`

**Interfaces:**
- Consumes: Task 6 の後の印の無い口
- Produces: 印の無い pack（下の試験が縛る）

- [ ] **Step 1: 落ちる試験を書く**

```python
    def test_no_pass_tag_left(self):
        # works/ の .py と .yaml（docs/・CHANGELOG.md・tests/ を除く）に "pass_tag"・"PASS_TAG"・"tagged(" が無い
    def test_refitting_passes_only_scope(self):
        # refitting の with: に pass_tag が無く、fixing と refitting の with: の違いは渡す値（判定・未直しの単位・案・覚え書き）と scope の名だけ
```

Run: `cd works/tests && PYTHONDONTWRITEBYTECODE=1 python3 -m unittest test_line`
Expected: FAIL（名指したファイルと行の一覧）

- [ ] **Step 2: 残りを消し、表の試験（`test_script_contract`・`test_line.LineShapeCase`・`tests/linekit.py` の線の節の並び・`test_blk_fix` の YAML の突き合わせ）を合わせる**

- [ ] **Step 3: 通ることを確かめる**

Run: `cd works/tests && PYTHONDONTWRITEBYTECODE=1 python3 -m unittest test_line test_script_contract test_blk_fix test_blk_fix_tdd test_blk_fix_conflict test_replan test_block_scope`
Expected: PASS

- [ ] **Step 4: 組の仕上げ**（Task 5 の Step 5 と同じ 3 つ。期待も同じ）

- [ ] **Step 5: Commit**

```bash
git add works/
git commit -m "refactor(works): 回の印の YAML の入力・環境変数・本体を消す（2 度目の include は置き場の分けだけで分かれる。239 Task 7）"
```

---

### Task 8: 宣言の外の書き込みの照らし（関数と試験だけ。まだ繋がない）

**Files:**
- Modify: `works/.shared/core/scopes.py`
- Test: `works/tests/test_scopes.py`（class `GateCase`。一時の置き場に偽の盤面と偽の pack を作る）

**Interfaces:**
- Consumes: Task 4 の `manifests`・`published`・`owner_of`、Task 5 の `scopes.json` の形、`engine.schema.validate_schema`
- Produces:
  - 共有の記録の形の組（モジュールの定数。M2 の `shared` を fnmatch の形で。`scopes.json`・`scopes.json.lock`・`scope-window.json` を含む）
  - `scopes.snapshot(board_dir: pathlib.Path) -> dict[str, list[int]]` — 盤面の下の全部のファイルの相対パス（posix）→ `[大きさ, mtime_ns]`
  - `scopes.check_window(board_dir: pathlib.Path, window: dict, pack: pathlib.Path = PACK) -> list[str]` — `window` は `{"scope", "block", "round", "files": snapshot}`。今の盤面と比べ、変わった・増えた・消えたパスごとに: scope の根の下 → 可。共有の記録 → 可。`board/r<N>/<名>` で、名が `window["block"]` の manifest の per_include でない Produces → 可で、`r<N>/scopes.json` の `owns`（`{<名>: <scope>}`）に持ち主を記録し、別の scope が持ち主なら誤り。ほか → 誤り。窓の scope の `required` の Produces が無い・`format` が json の Produces が Schema に合わない → 誤り。誤りの 1 行は「<パス>: scope <名>（<block>）が宣言の外に書いた。宣言: <Produces の名の並び>」の形（持ち主の重なりは両方の scope を名指す）。scope が空の窓は照らさず `[]`
  - `scopes.reads_outside(board_dir: pathlib.Path, window: dict, pack: pathlib.Path = PACK) -> list[str]` — 窓の scope の `reads-*.json` の行のうち、盤面の下のパスで、scope の根・Consumes の名・自分の Produces・共有の記録・`out/` のどれでもない物（外れ D4: 落とさない。呼び手が trace の行 `scope_read_outside` と報告に載せる）

- [ ] **Step 1: 落ちる試験を書く**

```python
class GateCase(unittest.TestCase):
    def test_write_in_own_scope_root_passes(self): ...            # board/fixing/r1/x.json を足す → []
    def test_write_in_other_scope_refused(self): ...              # fixing の窓で board/refitting/r1/x.json → 1 行。パス・"fixing"・宣言の並びを含む
    def test_write_to_shared_record_passes(self): ...             # state.json・trace.jsonl・out/r1/p3.fix.json の変化 → []
    def test_published_name_records_owner(self): ...              # fixing の窓で board/r1/fix-held-reply.json → []、scopes.json の owns に fixing
    def test_second_owner_of_published_name_refused(self): ...    # 続く refitting の窓で同じ名を書き直す → 1 行に "fixing" と "refitting"
    def test_undeclared_round_place_write_refused(self): ...      # fixing の窓で board/r1/rule-tree.json（Produces でない）→ 1 行
    def test_line_window_not_checked(self): ...                   # scope "" の窓で何を書いても []
    def test_missing_required_produce_refused(self): ...          # required の Produces が無い → 1 行。required でない物は無くても []
    def test_json_produce_schema_mismatch_refused(self): ...      # Schema に合わない JSON の Produces → 1 行に Schema の誤り
    def test_reads_outside_listed_not_refused(self): ...          # reads-<役>.json に board/refitting/r1/y.md → reads_outside が 1 行。check_window は []
```

- [ ] **Step 2: 落ちることを確かめる**

Run: `cd works/tests && PYTHONDONTWRITEBYTECODE=1 python3 -m unittest test_scopes.GateCase`
Expected: FAIL（`AttributeError: module 'scopes' has no attribute 'snapshot'`）

- [ ] **Step 3: 照らしの関数を書く**（`check_window` は誤りを全部並べて返し、最初の 1 つで止まらない）

- [ ] **Step 4: 通ることを確かめる**

Run: `cd works/tests && PYTHONDONTWRITEBYTECODE=1 python3 -m unittest test_scopes`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add works/.shared/core/scopes.py works/tests/test_scopes.py
git commit -m "feat(works): 窓の間の盤面の変化を宣言に照らす関数を足す（宣言の外の書き込み・持ち主の重なり・必須の出力と Schema。まだ繋がない。239 Task 8）"
```

---

### Task 9: 照らしを盤面を開く口に繋いで有効にし、文書を合わせる

**Files:**
- Modify: `works/.shared/core/entry.py`（`open_board` が `scopes.enter` を呼ぶ）・`works/.shared/core/scopes.py`（`enter`）・`works/.shared/core/report.py`（宣言の外の読みの行）・測り M5 で落ちた名の書き手（manifest・Schema・共有の記録の組、か私物の書き先を `b.work`・`script_io.scope_dir` へ移す）・`works/tests/test_block_scope.py`（共有の記録の組を `scopes` の定数に替える）・`works/docs/darkfactory-flow.md`（節「部品の置き場と宣言」）・`works/CHANGELOG.md`
- Test: `works/tests/test_entry.py`・`test_block_scope.py`・`test_report.py`

**Interfaces:**
- Consumes: Task 8 の `snapshot`・`check_window`・`reads_outside`、Task 5 の `claim`
- Produces:
  - `scopes.enter(board_dir: pathlib.Path, round_: int, scope: str, block: str) -> None` — `fcntl.flock` の下で、盤面の根の `scope-window.json`（`{"scope", "block", "round", "files"}`）を読み、`check_window` が誤りを返せば BoardGap（誤りの全行）。窓の scope が今の scope と違えば、前の窓の `reads_outside` を trace の行 `scope_read_outside`（`{scope, paths}`）に書き、今の scope の窓を `snapshot` で開き直す。同じ scope なら窓を開き直さない（Archon の再開で同じ include が走り直しても 1 回目の書き込みを照らし続ける）
  - `entry.open_board` は `claim` の後に `scopes.enter` を呼ぶ（scope が空でも呼ぶ。前の部品の窓を閉じるため）
  - 報告の冒頭の読んだ証拠の行に、trace の `scope_read_outside` の数とパス（無ければ行を出さない）

- [ ] **Step 1: 落ちる試験を書く**

```python
# test_entry.py
    def test_enter_checks_previous_window_on_scope_change(self):
        # scope fixing で開く → board/refitting/r1/x.json を手で書く → 線（scope 空）で開く → BoardGap の文にパスと "fixing"
    def test_enter_same_scope_again_keeps_window(self):
        # fixing で開く → board/fixing/r1/a.json を書く → fixing でもう一度開く → scope-window.json の files が 1 回目のまま
    def test_reads_outside_reach_trace(self):
        # fixing の窓の reads-fix.json に宣言の外のパス → 次の窓へ移る時に trace の scope_read_outside の行

# test_block_scope.py
    def test_undeclared_write_stops_run(self):
        # ScriptLine の edits で fixing の窓の中に board/planning/r1/z.json を書かせる → run が止まり、failure の文に z.json と "fixing"
```

- [ ] **Step 2: 落ちることを確かめる**

Run: `cd works/tests && PYTHONDONTWRITEBYTECODE=1 python3 -m unittest test_entry test_block_scope`
Expected: FAIL（`AttributeError: … 'enter'`）

- [ ] **Step 3: `scopes.enter` を書いて `open_board` に繋ぐ**

- [ ] **Step 4: 測り M5 — 落ちた物を全部並べて振り分ける**

Run: `cd works/tests && PYTHONDONTWRITEBYTECODE=1 python3 -m unittest test_block_scope test_script_contract test_line_a test_replan test_report`
落ちた行（BoardGap の文）を全部台帳に写し、名ごとに 1 つに振る: 部品の外が読む → manifest の Produces（JSON なら Schema も）。core が書く記録 → 共有の記録の組。部品の私物なのに盤面の根や公開の置き場に書いている → 書き先を `b.work`（周ごと）か `script_io.scope_dir`（周をまたぐ）へ移す。書き先を移す名が 10 を超えたら、移さずに運び役へ一覧を返して止まる（次の依頼に割る。報告の状態は DONE_WITH_CONCERNS）。あわせて、本物の dogfood の盤面 1 つで `scopes.snapshot` の 1 回の時間を測って台帳に書く（外れ D3）。

- [ ] **Step 5: 通ることを確かめる**

Run: `cd works/tests && PYTHONDONTWRITEBYTECODE=1 python3 -m unittest test_scopes test_entry test_block_scope test_script_contract test_line_a test_replan test_report`
Expected: PASS

- [ ] **Step 6: 文書と CHANGELOG**

`works/docs/darkfactory-flow.md` に節「部品の置き場と宣言」を足す: 1 つの決まり（部品が読み書きしてよい 3 つ）、置き場の絵（`board/<scope>/r<N>/`・`board/r<N>/`・共有の記録）、manifest の書き方、照らしのエラー文の読み方、部品を足す・廃止する時の手順（設計 §10 の動線）、聞き直しの形（作っていない）、外れ D1〜D5。`works/CHANGELOG.md` の `[Unreleased]` に Added（scope・manifest・照らし・flow_adapter）と Removed（回の印 pass_tag）を書く。

- [ ] **Step 7: 組の仕上げ**（Task 5 の Step 5 と同じ 3 つ。期待も同じ）

- [ ] **Step 8: Commit**

```bash
git add works/
git commit -m "feat(works): 盤面を開く口で窓を照らし、宣言の外の書き込みと持ち主の重なりで run を止める（全部品の manifest が揃った後に有効化。239 Task 9）"
```

---

## この計画が扱わない物

- 聞き直し・役どうしの会話の実装（session_handle・resume の中身、Archon の DB の provider_session_id を測る事）。形だけを決めた。
- 今ある INPUTS_* の読みの全部を `flow_adapter.input` に寄せる事（Task 1 の M2 と同じ grep で数を台帳に書き、次の依頼の候補にする）。
- 依頼 226 のほかの名の分け（`replan` の読んだ証拠の頭 `reads-replan-*`・`replan.json` など、案の直しの段が 1 度目の `blk-plan` と名を分けている所）。置き場の分けで要らなくなるかを Task 9 の後に見て、次の依頼の候補にする。
- AI の役の節が盤面に直に書く物の照らし（外れ D3。役の書き込みは包みのフックと `writes` の突き合わせが見る）と、線の最後の include の最後の script の書き込み。
- 宣言の外の読みを落とす条件にするか（外れ D4。持ち主の決め）。
- LangGraph 型の型つき state・reducer（設計 §8。採り直す条件は同じ値を 2 つ以上の部品が避けられずに書き換えると測れた時）。
- 動いている途中の古い形の run の移し替え。
