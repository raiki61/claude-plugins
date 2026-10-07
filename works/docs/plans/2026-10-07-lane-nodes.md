<!-- coldwrite:skip 内部の設計書。語は「目的と語」の節と works/README.md で定義 -->
# TDD の輪の並べの枝を、Archon の節にする（依頼 243 の並べ・4 段目）

状態: 入れた（TDD の輪）。修正役の並べも同じ形で入れ（docs/plans/2026-10-07-fix-lane-nodes.md）、共通の部分を並べの枝の部品 blk-fix/lib/lanekit.py に切り出した（7 節）。残りは本物の run での確かめ（8 節）。
2 段目・3 段目のまとめ役と下請け（1 つの AI の節が Agent で単位の下請けを起こし、下請けが段のコマンドを Bash で走らせる形）は外した。

## 平たく言うと（3 行）

- 前は、TDD の輪の並べを 1 つの AI の節（まとめ役）が持ち、まとめ役が Claude の Agent の道具で枝ごとの下請けを起こしていた。下請けは会話の記録も模型の宣言も持たず、続きから起こし直せなかった。
- 今は、枝ごとに Archon の輪（`tdd-lane-loop-<n>`。支度 → 役 → 確かめ）を 1 つずつ置き、3 本までを同時に走らせる。役は Archon の普通の AI の節なので、会話の記録・続き・認証・模型と effort の宣言を、ほかの役と同じに持つ。
- 包み（claude-adapter）は印の旗 `lane` を見て、その役を枝の小さい worktree を cwd に起こし、run の作業ツリーとほかの枝の worktree を書かせない。

## 目的と語

読む前提: works の全体は works/README.md と works/docs/darkfactory-flow.md。前の段は works/docs/plans/2026-10-06-tdd-parallel.md（2 段目。範囲の重ならない単位の並べ）と works/docs/plans/2026-10-07-overlap-lanes.md（3 段目。範囲が重なる枝も並べ、機械が 3 方向で合わせる）。分け方・締め（赤の確かめ直し・3 方向の当て・合わせた木の緑・意味の食い違いの逃げ道・書き込みの記録の写し）は 3 段目のまま使う。

この文書の語（2 段目・3 段目の語はそのまま使う。枝・単位の worktree・run ごとの置き場・包み・柵・書き込みの記録・当てる・戻す・単位の控え・目録）:

- 枝の輪: `blk-fix/blk-fix.yaml` の `tdd-lane-loop-<n>`（n は 1〜3）。中は支度 `tdd-lane-prep-<n>`（script）→ 役 `tdd-lane-<n>`（AI）→ 確かめ `tdd-lane-step-<n>`（script）
- 枝の役: 枝の輪の AI の節。印は `works-node: tdd-lane-<n> lane`
- 単位の決まりのファイル: 枝の今の単位の決まりの全文（盤面の `tdd-<k>/lane-<n>-<j>.md`。単位の間は同じ中身）
- 回ごとの指示書: 枝の今の段・前の回を拒んだ理由・返す JSON（盤面の `tdd-<k>/lane-<n>.next.md`）
- 順の輪: 並べの後に残った単位を回す `tdd-rest-loop`（役 `tdd-rest`。輪 `tdd-loop` と同じ支度・確かめ）

## 1. 前の形が残した物

2 段目・3 段目は Archon の fan_out が子ごとに cwd を向けられないので、1 つの AI の節の中で Agent の下請けを並べた。その形には次が残った:

1. 下請けは Archon の節でないので、会話の id が包みの記録に無く、`continue=` で続きから起こせない。落ちた下請けは捨てて順に回し直すしかない
2. 模型と effort は親の段を継ぐが、下請けの effort が継がれるかは Claude Code の文書に無い（README の模型の節）
3. 下請けは赤・緑を確かめるために Bash で段のコマンドを走らせた。コマンドは役の sandbox の中で走るので、共通の .git を書けず、git の object を単位の置き場に書く env（GIT_OBJECT_DIRECTORY）と、試験へそれを渡さない印を tree_run に置いていた
4. 下請けが段のコマンドを走らせずに終わる・まとめ役が下請けを起こさない、を機械が止められない（締めで戻すだけ）

持ち主の測り（2026-10-07）: 兄弟の loop_group の節は同時に走る。層（依る節の深さ）に `mutates_checkout: false` の節が混ざると、Archon v0.11.1 はその層を順に回す。

## 2. 形

```
tdd-start → tdd-loop（振り分け。枝を切った周は tdd-step が done・phase lanes で抜ける）
          → tdd-fork（go・lanes・lane_1..3）
          → tdd-lane-loop-1 / -2 / -3（when: lane_<n>。同時に走る）
          → tdd-join（all_done。when: go）
          → tdd-rest-loop（when: tdd-join の go）
          → fix-loop …
```

- 振り分け（輪 `tdd-loop`）: 今どおり。形 g3 で枝が 2 本以上なら `tddlanes.plan` が枝の worktree と単位の控えと目録を置いて状態の段を `lanes` にする。`tdd-step` の出口は done が真・phase が lanes で、輪はそこで抜ける（状態の done は偽のまま）。枝は `tddlanes.MAX_LANES`（3）本までで、後ろの枝の単位は順の単位に残る
- `tdd-fork`（`tddlanes.fork`）: 状態の段が lanes なら go と `lane_<n>`。実行器の無い run（`tdd-loop` が飛ぶ）でも `none_failed_min_one_success` で走って go: false を返す（`tdd-join` の when: がいつも引ける）
- 枝の輪（`tddlanes.lane_prep`・`lane_step`）:
  - 支度は単位の決まりのファイル（TDD の輪の役の決まりの全文・その単位の brief・座・test・fix・refactor の約束と返す形・この単位の決まり。2 番目からの単位は前の単位の引き継ぎ）と回ごとの指示書を書き、包みが読む 2 つの印を書く: 単位の鍵（`adapter.session_key_path`。run ごとの置き場。値は `tdd-<k>:lane-<n>:<単位>`）と単位の worktree（`adapter.lane_tree_path`。盤面の `tdd-lane-trees/`）
  - 役は回ごとの指示書を読み、今の段の JSON を返す（前の形の「返答のファイルを書いて段のコマンドを走らせる」は無い）
  - 確かめは `tddloop.step` を単位の worktree で回す（赤・緑・凍結・名指しの外の書き換え・消えたテスト・test_cmd・整えは輪と同じ関数）。書き込みの出どころは run の作業ツリーの記録（`writes.sink(repo)`。包みは Archon の cwd の鍵で記録し、単位の worktree の実パスで載る）と突き合わせる（step の口 `log`）。食い違いの申し出は欄と単位だけ見て控えに書く（盤面を読む確かめは締め）。欄・単位の違う申し出は拒否に数える
  - 単位が済むと枝は次の単位の段 test へ進み（単位ごとの頭の木を `unit_heads` に残す）、枝の単位が全部済むか諦めると done で輪を抜ける。単位の worktree の `.git` の指しが切った時と違えば、枝を済みにして抜ける（輪を落とさず、締めが順に戻す）
- `tdd-join`（`tddlanes.join`）: 3 段目の `settle` のまま締め、輪の calls に lanes の 1 行を足す。食い違いの申し出は盤面に積む。残りが在れば go
- 順の輪（`tdd-rest-loop`）: 輪 `tdd-loop` と同じ支度（`tdd_prep`）・確かめ（`tdd_step`）で、役 `tdd-rest` は役 `tdd` と同じ形（YAML のアンカー）。戻した単位の指示書には並べで済まなかった理由と前の試みの差分が載る（今どおり）

## 3. 包みの旗 lane（adapter.py の頭の 6c）

- 印 `works-node: tdd-lane-<n> lane` の起動は、切符の board の下の `tdd-lane-trees/<節の名>` の 1 行を読み（盤面は切符の守る場所なので、枝の役はほかの枝の印を書き換えられない。run ごとの置き場は役が書けるので置かない）、そのパスを子の cwd にする（`adapter.lane_cwd`）。通すのは run ごとの置き場の下に在り、run の worktree の作業ツリーの単位の守りの参照（`refs/works/units/<印>/u-<印>`。共通の .git の中なので役は作れない）を持つ worktree だけ。役の文からは取らない
- 柵: run の worktree の根とほかの単位の worktree（全部の綴り）を permissions.deny と denyWrite に足し、単位の worktree を allowWrite に足す。17 の run ごとの置き場・14 の対象の禁止・18 の形ごとの道具・19 の明示の模型は今どおり
- 会話: 会話の id・起動の記録・読んだ記録・書き込みの記録の鍵は Archon の cwd（run の worktree）のまま。claude の会話の置き場は cwd ごとなので、包みは単位の worktree を `sessions/<cwd の hash>/<節>.lane` に記録し、`continue=X` は X と同じ cwd の起動だけを起こす。SDK の続き（`--resume`）で記録の worktree が今と違えば新しい会話にする（`lane_cut`）
- 単位の切れ目: `KEYED_NODES` に `tdd-rest`・`tdd-lane-1..3` を足した。枝の中で単位が替わると支度の鍵が替わり、包みが新しい会話で起こす（新しい会話の決まり。works/docs/plans/2026-10-06-fresh-session.md）。同じ単位の段は Archon の `fresh_context: false` の続きで同じ会話を継ぐ
- 起こさない: 切符が無い・印が無い・読めない・絶対パスでない・フォルダでない・置き場の外・run の worktree に掛かる・単位の守りの参照が無い・旗 isolated と一緒・SDK の sandbox が enabled・allowUnsandboxedCommands: false・failIfUnavailable: true でない（Bash を sandbox の外で走らせると denyWrite が効かない。旗 no-tree-write と同じ確かめ。枝の役の YAML は failIfUnavailable: true を書く）。起動の記録の `fence.lane` に単位の worktree、`fence.lane_deny` に柵に足した worktree

## 4. 決定（設計に無かった所。既存の設計に一番近い物を選んだ）

- 枝の輪は 3 本で固定（YAML は数を変えられない）。4 本目からの枝は順に回す（`plan` が切らない）。数は `tddlanes.MAX_LANES`・YAML・`KEYED_NODES`・stage-models.json・座の表を試験が揃える
- `tdd-loop` は残し、振り分けの周で抜ける。並べの後の単位は同じ支度・確かめの別の輪 `tdd-rest-loop` で回す（Archon の DAG は前へ戻れない）。並べない run の節の並びと会話は今と 1 つも変わらない（`tdd-fork` が go: false を足すだけ）
- 輪を抜ける印は `tdd-step` の出口の done（並べの周も真）。until_bash は今の 1 つの形のまま（全部の輪が受け付けの done で抜ける決まり。tests/test_role_give_up.py）
- `tdd-join` は `all_done`: 枝の輪が 1 本落ちても締めて残りを順に回す（落ちた枝の単位は済んでいないので戻る）。Archon は落ちた節の在る run を落ちたまま残す（docs/archon-feedback.md）が、修正と報告は進む
- 枝の確かめは Archon の script の節（sandbox の外）で走るので、共通の .git に書いてよい。前の形の object の置き場の env と、試験へそれを渡さない印は外した
- 枝の役は Agent を持たない。役 `tdd` も持たなくなった（形ごとの柵の行を外した）
- 指示書の全文版と差分版（包みの 9）は枝の役には使わない: 単位の決まりのファイルは単位の間は同じ中身で、回ごとの指示書だけが替わる（最初の回だけ全部読ませる）
- 盤面に足すファイルは `tdd-<k>/` と `tdd-lane-trees/` の下（どちらも共有の記録 `tdd-*/**`）なので柵の表は変えない。単位の鍵と単位の控えは run ごとの置き場（役が書けるが、書き換えて起きるのは会話の切れ目のずれと、締めが確かめ直す控えだけ）

## 5. 今と同じに保つ物

- 並べない run（形 g3 の外・枝が 2 本未満・範囲の引けない単位・実行器の無い run）の段と会話
- 枝の中の赤・緑・凍結・名指しの外の書き換え・消えたテスト・軽量の単位・test_cmd の関門・拒否 3 回の諦め（同じ `tddloop.step`）
- 締めの赤の確かめ直し・3 方向の当て・重なりのファイルの照らし・合わせた木の緑と意味の食い違いの逃げ道・書き込みの記録の写し（3 段目の `settle`）
- 出口の lanes（単位ごとの結末・枝の段の呼び（枝の番号つき）・重なりのファイル・重なりの見込み）。輪の calls は tdd・tdd-rest の起動に 1 行と、締めの lanes の 1 行

## 6. 危険

今壊れている物は無い（試験は緑）。入れた後に起こりうる物:

1. Archon が同じ層の節の前に作業ツリーのやり直し用の checkpoint を作る時、3 本の枝の輪が同じ run の worktree に同時に触る。持ち主の測りは「同時に走る」までで、checkpoint の錠の取り合いは見ていない（8 節で見る）
2. 枝の役の AI の節が落ちる（包みが起こさない・Archon が上限まで起こし直して落ちる）と run は落ちた節を持つ。締めと順の輪は進む
3. 単位の worktree には git が無視するファイル（.venv など）が無いので、実行器が走らない・試験が環境で落ちうる。その枝は諦めて順に戻る（時間だけの害。2 段目と同じ）
4. 枝の輪は 3 本で、4 本目からの枝は順。単位の多い run では並べの効きが頭打ちになる
5. 単位の控え（赤の記録・単位ごとの頭の木）は run ごとの置き場に在り、役の sandbox からも書ける。締めが赤を確かめ直すのは今どおり（3 段目の危険 6 と同じ度合い）

## 7. 修正役の並べへ使い回す形（入れた。docs/plans/2026-10-07-fix-lane-nodes.md。下は入れる前に書いた見込みで、実際の形と部品の口は
その設計の 2〜4 節。見込みとの違い: 印の置き場の名は tdd-lane-trees/ のまま共有した・答えの節は旗 fork で相談の相手の会話の写しで答える・
締めは unitlanes.settle（fix-units）でなく lanekit の部品の上の fixlanes.join で、fix-units は外した）

修正役の並べ（`fixrules.g1_values` の side・`unitlanes`。修正役が Agent で項目ごとの下請けを起こし、当てるコマンドを走らせる）は今のまま。同じ形へ移す時は次の部品をそのまま使う:

- 包みの旗 lane と 2 つの印（`adapter.lane_tree_path`・`session_key_path`）。節の名を `fix-lane-<n>` にして `KEYED_NODES` と stage-models.json と座の表に足し、支度が印を書く
- 枝の輪の 3 つ組（支度 → 役 → 確かめ）を同じ YAML の形で置き、`fork` に当たる節が `unitlanes.plant` の行から `lane_<n>` を出す。層の決まり（同じ層に `mutates_checkout: false` を置かない）も同じ
- 確かめの節は受け付け（`fix-accept` の決まり）を単位の worktree で回す口を持つ必要がある（今の受け付けは run の作業ツリーの盤面の周を前提にする）。書き込みの記録は `tddloop.step` の口 `log` と同じく run の作業ツリーの記録に突き合わせる
- 締めは今の `unitlanes.settle`（`fix-units`）をそのまま使う。範囲の相談は既に修正の輪の中の Archon の節（`fix-consult`・`plan-answer`・`fix-consult-check`。`blk-fix/lib/consult.py`）なので、枝の役の相談も役の会話の外の節として sandbox の外で回せる。相談の節を枝の輪の中にどう置くかは、移す時に決める

## 8. 本物の run での確かめ

1. 形 g3（既定）で、実行器（`tdd_suite`）を渡し、互いに別の修正案の項目に載る 2〜3 単位の依頼（どれも先にテストを書ける。例: 別々のファイルの関数の誤りを 2〜3 件）を回す。振り分けが 2 単位以上を tdd に振り、修正案の項目が書いてよい範囲（allowed_paths）を持てば枝が 2 本以上になる
2. Archon の出来事で、`fixing__tdd-lane-loop-1`・`-2`（・`-3`）の節の始まりの時刻が重なること（同時に走った）。`python3 works/dev/fixmeasure.py wait <archon.db> <run_id>` の段 `tdd-lanes` に枝の輪の束（n が枝の数）が出ること
3. 包みの起動の記録（`<家>/launches/<run の worktree の hash>.jsonl`）で、節 `tdd-lane-<n>` の行の `fence.lane` が枝ごとに別の単位の worktree（`<run-place>/tdd-<k>/lanes/item-<n>`）で、`fence.lane_deny` に run の worktree とほかの枝が在ること。同じ単位の 2 回目からの行の `session.mode` が続き（sdk-resume か sdk-fork）、単位が替わった行の `session.unit.cut` が真であること
4. 盤面の `tdd-<k>/state.json` の `lanes.out`（単位ごとの結末）と `lanes.calls`（枝ごとの段の呼び）、出口の `tdd.lanes`
5. run の後に `git -C <run の worktree> worktree list` と `git for-each-ref refs/works/units` に枝の worktree と守りの参照が残っていないこと（締めの `unittrees.remove`。残っても次の `plant` の `sweep` が消す）
