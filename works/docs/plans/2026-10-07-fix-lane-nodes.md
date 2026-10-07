<!-- coldwrite:skip 内部の設計書。語は「目的と語」の節と works/README.md で定義 -->
# 修正役の並べを、Archon の節にする（依頼 243 の並べ・5 段目）

状態: 入れた。残りは本物の run での確かめ（9 節）。前の形（修正役が Agent で範囲の在る項目の下請けを同時に起こし、役の sandbox の中で
当てるコマンドを走らせ、締めの節 fix-units が残りを当てた形）は外した。並べの枝の部品（`blk-fix/lib/lanekit.py`）を切り出し、TDD の輪の
並べ（4 段目。docs/plans/2026-10-07-lane-nodes.md）もその上に載せ直した。

## 平たく言うと（3 行）

- 前は、修正役 1 つが Agent の道具で項目ごとの下請けを同時に起こしていた。下請けは会話の記録も模型の宣言も持たず、範囲の相談もできず、受け付けの確かめは全部の項目を合わせた後の 1 回だけだった。
- 今は、修正の輪の前に、項目の組ごとに Archon の輪（`fix-lane-loop-<n>`）を置き、3 本までを同時に走らせる。枝の役は普通の AI の節なので、会話・続き・模型と effort の宣言をほかの役と同じに持ち、範囲の相談と受け付けと同じ事実の確かめを枝の中で回す。
- 締めの節が枝の差分を run の作業ツリーへ 3 方向で当て、当たらない枝・諦めた項目・枝に入らなかった項目は、今までどおり修正の輪の修正役が順に直す。修正役は枝の返答の行を写して、全部の項目の返答を受け付けに渡す。

## 目的と語

読む前提: works の全体は works/README.md と works/docs/darkfactory-flow.md。前の段は docs/plans/2026-10-06-parallel-units.md（1 段目。項目の下請けの並べ）・
docs/plans/2026-10-07-overlap-lanes.md（3 段目。範囲が重なる項目も並べ、機械が 3 方向で合わせる）・docs/plans/2026-10-07-lane-nodes.md（4 段目。TDD の輪の並べを
Archon の節にした）。範囲の相談の節は docs/plans/2026-10-06-ask-planner.md。

この文書の語（前の段の語はそのまま使う。枝・単位の worktree・run ごとの置き場・包み・柵・書き込みの記録・当てる・戻す）:

- 項目: 承認済みの修正案の項目（planbrief の brief の行）。枝で直すのは、修正役が下請けを起こす単位（`fixrules.dispatched`。g3 は TDD の輪が緑にした単位を除く）を持ち、範囲（`fixrules.item_ranges`）の在る項目だけ。項目の単位は今の直す義務と重なる物だけ
- 組: 単位を共にする項目どうし（1 つの単位を 2 本の枝が直さない）。組は 1 本の枝に入る
- 修正役の並べの枝（枝）: 単位の worktree 1 本と、その中で順に直す項目の並び（3 つまで。`fixlanes.MAX_ITEMS`）。枝は 3 本まで（`lanekit.MAX_LANES`）
- 枝の輪: `blk-fix/blk-fix.yaml` の `fix-lane-loop-<n>`。中は支度 `fix-lane-prep-<n>` → 枝の役 `fix-lane-<n>` → 範囲の相談の 3 節（頼み `fix-lane-consult-<n>`・答え `plan-answer-lane-<n>`・確かめ `fix-lane-consult-check-<n>`）→ 枝の確かめ `fix-lane-step-<n>`
- 項目の決まりのファイル: 枝の今の項目の決まりの全文（盤面の今の scope の周の `fix-lane-<n>-<j>.md`。項目の間は同じ中身）。回ごとの指示書は `fix-lane-<n>.next.md`
- 枝の結末: 締めの節 `fix-join` が書く `fix-lanes-out.json`（機械が読む）と `fix-lanes.md`（修正役が読む）。項目ごとに merged（当てた）か serial（修正の輪に戻した）
- 並べの枝の部品（lanekit）: TDD の輪の並べと修正役の並べが共に使う、段に依らない部分（4 節）

## 1. 前の形が残した物

1. 下請けは Archon の節でないので、会話の id が包みの記録に無く、模型と effort は親の段を継ぐだけだった（4 段目の 1 節と同じ）
2. 下請けは自分で範囲の相談ができず、まとめ役に「相談が要る」と報告するしかなかった。まとめ役は全部の下請けの後に 1 つの consult で頼む
3. 受け付けは全部の項目を合わせた後の 1 回だけで、下請けの誤りを項目の会話の中で直させる口が無かった
4. 当てるコマンドは役の sandbox の中で走るので、共通の .git を書けず、object の置き場の env（GIT_OBJECT_DIRECTORY）が要った。まとめ役が当てるコマンドを走らせない・下請けを起こさない、を機械が止められなかった（締めの節 fix-units が受け止めていた）

## 2. 形

```
… tdd-join → tdd-rest-loop
  → fix-fork（go・lanes・lane_1..3・why）
  → fix-lane-loop-1 / -2 / -3（when: lane_<n>。同時に走る）
  → fix-join（all_done。when: go）
  → fix-loop（fix-prep → fix → fix-consult → plan-answer → fix-consult-check → fix-accept）
  → conflict-check → rule-loop → fix-ruled-loop → …
```

- `fix-fork`（`fixlanes.fork`）: 形 g3・入力 `fix_lanes` が on（空も on）・書き込みの記録の在る run で、枝で直してよい項目（`fixlanes.candidates`）を組に分け（`groups`）、枝に配る（`assign`。組の順に、入る余地の在る枝のうち項目の一番少ない枝へ。1 本の枝に入らない組と、3 本 × 3 項目に入らない組は修正の輪へ）。枝が 2 本以上なら単位の worktree を切り、枝の控え・項目の決まりのファイル・審査のファイル・範囲の相談の控えを書く。並べない時も理由を出口の `why` と盤面の trace（`fix_lanes_planted` の lanes 0）に残す。盤面が開けない・brief の控えが壊れていれば並べず（修正の輪の支度が今どおり止める）
- 枝の輪（`fixlanes.lane_prep`・`lane_step`）:
  - 支度は回ごとの指示書（前の回を拒んだ理由と、項目の決まりのファイルの名指し。範囲の相談の答えが来た回は答えのファイルを名指す続きの指示書 `fixrules.resume`）を書き、包みが読む 2 つの印（`lanekit.mark`: 項目ごとの単位の鍵と単位の worktree）を置く
  - 枝の役は修正役と同じ返答の形（`recount.FIX_OUTPUT_FORMAT` の欄）で、この項目の単位だけを返す。実装の下請けは起こさず（自分が項目の実装役）、審査の下請け（216 の task-review の型。差分のコマンドは単位の worktree を根にする `seat.g1_diff_cmd`）を Agent で起こす（3 回まで）
  - 範囲の相談は修正の輪と同じ 3 節（`consult.ask`・答えの節・`consult.settle`）で、段の名は枝ごとの `lane-<n>`（状態・答えのファイル・枠 9 回を枝ごとに分ける）。合意は盤面の trace に載り、後の修正の輪の受け付けも同じ合意を読む
  - 確かめ（`fixlanes.check`）は受け付けと同じ事実の確かめを単位の worktree に当てる（5 節）。通れば項目の返答を控え（`fix-lane-<n>-<j>-reply.json`）、次の項目へ。同じ項目の 3 回目の拒否で項目を諦め（項目の頭からの差分を盤面に控え、木を項目の頭に戻す）、次の項目へ。範囲の相談の周は数えるだけ。項目が尽きるか、回数の上限（`MAX_ITERATIONS` = 3 項目 × 3 回 + 相談の枠 9 = 18）で done
- `fix-join`（`fixlanes.join`）: 枝の間に run の作業ツリーで変わった物を戻し、枝ごとに通った項目の差分（単位の worktree と切った時の姿の差分）を目録の順に 3 方向で当て（`lanekit.merge`。同じ試験のファイルに足しただけの食い違いは枝の順に並べて合わせる）、書き込みの記録を写し、枝の食い違いの申し出を当てた後の作業ツリーで確かめ直して盤面に積み（`lanekit.park`、source fix）、結末と trace（`fix_lanes_settled`）を書いて単位の worktree を片付ける。回り切らなかった枝（輪が落ちた）は今の項目の書きかけを戻して当てない
- 修正の輪（`fixrules.prep`）: 枝の結末が在れば、枝が当てた単位（`fixrules.lanes_merged`: 当てた項目の返答の changes に行の在る単位）を TDD の輪が緑にした単位と同じく下請けから外し、指示書に節 `lanes`（結末の本文を名指し、当てた単位の行は枝の返答から写す・周の全体の欄は全部の差分について書く・戻した項目と not_done の単位は直す義務のまま、を言う）を置く。出し直しの周の頭の 1 行（`OVERLAP_LINE`）は結末の重なりのファイルを名指す。受け付け（`fix-accept`）は変えない（全部の項目を合わせた作業ツリーで、試験・事後の関門の束・写しの型を含む全部を回す）

## 3. 包み（adapter.py の頭の 1 と 6c）

- 枝の役の印は `works-node: fix-lane-<n> lane self-resume`。旗 lane は TDD の輪の枝と同じ（単位の worktree を cwd に起こし、run の worktree とほかの枝を柵に足す。印の置き場は盤面の `tdd-lane-trees/<節の名>`。名は TDD の段の物のままで、共有の記録 `tdd-*/**` に当たるので柵の表を変えない）
- 旗 self-resume: 輪の中に答えの節が挟まっても、次の回の枝の役は自分の会話に戻る（修正役と同じ）
- 単位の切れ目: `KEYED_NODES` に `fix-lane-1..3` を足した。支度が書く鍵は `<scope>:r<周>:lane-<n>:item-<項目>` で、枝の中の項目が替わると新しい会話になる。旗 self-resume の続きの起動でも鍵が替われば切るようにした（前は self-resume の起動は鍵を見なかった。self-resume と鍵を持つ節は今まで無かったので、ほかの節の振る舞いは変わらない）
- 旗 fork（新しい）: 答えの節の印は `works-node: plan-answer-lane-<n> continue=fix-planner fork`。continue=X を `--resume <X の id> --fork-session --session-id=<新しい uuid>` で起こし（SDK の sdk-fork の起動と同じ旗の組）、新しい id をこの節の名で記録する。同時に走る 3 本の枝の答えの節が同じ修正案を書いた役の会話を同時に `--resume` すると、1 つの会話の記録に 2 つの続きが混ざる（後の修正の輪の答えの節や案の直しが、どちらの続きを継ぐか決まらない）ので、枝の答えは写しで答えて元の会話を変えない。continue の無い fork の起動は起こさない

## 4. 並べの枝の部品（lanekit）の口

TDD の輪の並べと修正役の並べは、Archon の節の形（`<段>-fork` → `<段>-lane-loop-<n>`（支度 → 枝の役（旗 lane）→ … → 確かめ）→ `<段>-join` → 順の輪）と、
単位の worktree・包みの印・当て方・記録の写し・申し出の積み・片付けが同じ。段が持つのは、何を枝に分けるか・枝の役の指示書・枝の確かめ・当てた後の確かめだけ。
共通の部分を `blk-fix/lib/lanekit.py` に置き、`tddlanes` と `fixlanes` はその上の段の部品にした（TDD の振る舞いと試験は変えていない）。

- `MAX_LANES`: 枝の輪の数（両方の段の YAML の 3 本・包みの `KEYED_NODES`）
- `fork_out(ns)`: `<段>-fork` の出口 `{go, lanes, lane_1..3}`（ns が 1..k の連番でなければ ValueError）
- `plant(repo, ns, place, manifest, union)`: 前の単位の worktree を片付け、run の作業ツリーの今の姿を base に枝ごとの単位の worktree を切る。`{n: {tree, git, base}}`
- `tree_ok(tree, git)`: 単位の worktree の `.git` の指しが切った時と同じか（違えば理由）
- `mark(board_dir, node, key, tree)`: 包みが読む 2 つの印（単位の鍵・単位の worktree）
- `revert_strays(repo, base, keep)`: 枝の間に run の作業ツリーで変わった物を戻す
- `merge(repo, tree, since, base, log, declared, made, kept, union, earlier, check)`: 枝の差分を 3 方向で当てる（記録の無い変更・当たらない・中身が違う物は当てない。check は段の照らし）。`Merge(why, patch, names, unioned, clash)`
- `shared(patches)`: 2 本以上の枝の差分に出たファイル
- `carry(log, repo, applied, shared)`: 当てた枝の書き込みの記録を run の作業ツリーへ写す
- `claim_problems(claims, repo, board_dir, owed, try_query, briefs)`: 食い違いの申し出の機械の確かめ
- `park(board, claims, source)`: 確かめた申し出を盤面の控えに積む（裁定の輪が読む）
- `remove(repo, trees)`: 単位の worktree を片付ける

段ごとの差し込み:

- 枝に分ける物: TDD は 項目を共にする tdd の単位の組（振り分けの後）、修正役は 単位を共にする修正案の項目の組（TDD の輪の後）
- 枝の中の順: TDD は 単位（単位ごとに新しい会話）、修正役は 項目（項目ごとに新しい会話）
- 枝の役: TDD は `tdd-lane-<n> lane`（段 test・fix・refactor の返答）、修正役は `fix-lane-<n> lane self-resume`（修正役の返答。審査の下請け）
- 枝の輪の中: TDD は 支度 → 役 → 確かめ、修正役は 支度 → 役 → 相談の 3 節 → 確かめ
- 枝の確かめ: TDD は `tddloop.step`（赤・緑・凍結・書き込み）、修正役は `fixlanes.check`（受け付けと同じ事実の確かめ）
- 締めの後: TDD は 合わせた木の緑・意味の食い違いの逃げ道（`_green_after`）・名指しのテストの源（`merge` の check）、修正役は 修正の輪の受け付け（全部の確かめ）
- 順の輪: TDD は `tdd-rest-loop`、修正役は `fix-loop`（今の修正の輪）

YAML の節は Archon の中で部品にできない（include はブロックの単位で、輪の形を引数にできない）ので、両方の段に同じ形を書き、試験（`tests/test_tdd_lane_wiring.py`・`tests/test_fix_lane_wiring.py`）が形と層の決まりを縛る。

## 5. 枝の確かめ（受け付けのどの確かめを単位の worktree に当てるか）

- 範囲の相談の枠（consult）: 当てる。枝ごとの枠を使い切った後の consult を拒む
- 凍ったテストのファイル（frozen）: 当てる。`factchecks.check_frozen` を単位の worktree で
- 書き込みの出どころ（writes）: 当てる。記録の鍵は run の作業ツリー（包みは単位の worktree の書き込みもそこへ載せる）、見る変更は枝の base から（`factchecks.check_writes` の log_repo・since）
- 食い違いの申し出の形（conflict）: 当てる。申し出は通れば枝の控えに積み、締めが当てた後の作業ツリーで確かめ直して盤面に積む
- 直す義務の単位（duplicate・not_opened・excused の枝の形）: 当てる。この項目の単位だけ・どれも changes・not_done・申し出のどれか 1 つに 1 回
- 承認済みの修正案の範囲（scope）: 当てる。照らす変わったパスは枝が変えた物だけ（`factchecks.check_plan_scope` の since）
- 変更に当たる試験（tests）: 当てる（実行器の在る run）。輪の状態の写し（盤面の `fix-lane-<n>-tests.json`。実行器は単位の worktree の物・置き場は run ごとの置き場の `fix-lanes/lane-<n>/`）で `tddloop.selected_problems`
- .archon/ の下・1 回目に受け付けた単位・事後の関門の束・写しの型: 当てない。盤面が p3.fix を待つ形と全部の単位の返答が要る（修正の輪の受け付けが全部の項目を合わせた作業ツリーで回す）

事前の確かめ（修正役が Bash で回す `factchecks.py`）も、枝の相談の控え（run ごとの置き場の `consult/lane-<n>/consult.json`。repo は単位の worktree、log_repo と since を持つ）で同じ照らしになる。

## 6. 決定（設計に無かった所。既存の設計に一番近い物を選んだ）

- 枝は修正の輪の前の節（TDD の並べと同じ「枝 → 締め → 順の輪」）。修正役が返す 1 つの返答（盤面の p3.fix）はそのままで、修正の輪の修正役が枝の返答の行を写して全部の項目の返答を組む（TDD の輪が緑にした単位の行を書くのと同じ形）。機械が行を合わせる形（2 回目の修正の段の控えの合わせ）は、受け付けの大きな変更になり、周の全体の欄（interactions・plan_faces・fix_closure）を機械が合わせる規則を新しく決めることになるので採らなかった
- 枝の数は 3 本で固定（YAML は数を変えられない）。項目の数は無制限だった前の形の並べを減らさないよう、1 本の枝が 3 項目まで順に直す（3 × 3 = 9 項目まで並べる。その先は修正の輪）
- 枝の役は項目の実装役そのもの（前の形の実装の下請けの代わりに、Archon の節が項目ごとの新しい会話を持つ）。審査の下請けは残した（前の形の項目ごとの審査を減らさない）
- 1 項目しか無い run・単位を共にする項目しか無い run（枝 1 本）は並べない（枝 1 本は修正の輪と同じで、節が増えるだけ）
- 包みの無い run（書き込みの記録が無い）は並べない: 旗 lane が効かず、枝の役が run の作業ツリーで書く。前の形は包みが無くても下請けに worktree の中で書かせたが、柵が無く、確かめは同じに通らない。修正の輪が順に直すので、run は今どおり通る
- 入力 `fix_lanes`（off で並べない）は節 `fix-fork` が読む。修正の輪の支度（`fix-prep`）からは外した
- 枝の控えは盤面（役は書けない）、単位の worktree・審査の差分・試験の置き場は run ごとの置き場。盤面に足すファイルは今の scope の周の作業ファイル（include ごとの私物）なので、柵の表を変えない
- 範囲の相談の番号（trace の `plan_scope_asked` の id）は、同時に走る枝の確かめの節が同じ番号を振らないよう、今の scope の周の作業ファイル `consult.lock` の錠の中で振る

## 7. 今と同じに保つ物（外した物と残した物）

- 外した: 修正役の g3 の 1 回目の周の項目の下請けの並べ（`fixrules.side_on`・`merge_line`・`seat.G1_PARALLEL_OF`・`unitlanes.merge`・`command`・`settle`・`settled`・節 `fix-units` と `scripts/units.py`）
- 残した: 修正役の項目ごとの新しい会話の下請け（順に、run の作業ツリーで。依頼 243 の 2）・入力 `fix_lanes`・g1（比べの腕）の形・裁定の後の 2 回目の修正の輪（並べない）・受け付けの全部の確かめ・包みの無い run の通り方
- TDD の輪の並べは振る舞いを変えず、共通の部分だけを `lanekit` に移した（`tests/test_tdd_lanes.py` が緑のまま）

## 8. 危険

今壊れている物は無い（試験は緑）。入れた後に起こりうる物:

1. 本物の run でまだ回していない。特に、同時に走る枝の輪の層の作業ツリーの checkpoint（4 段目の 6 節の 1）、旗 fork の起動（`--resume X --fork-session --session-id=Y`。SDK の sdk-fork の起動と同じ旗の組だが、包みが自分で組んだ形は本物で確かめていない）、旗 self-resume と単位の鍵の組み合わせ
2. 修正の輪の修正役が枝の返答の行を写し違える（受け付けが拒み、修正役が出し直す。行を合わせる機械は持たない）
3. 単位の worktree には git が無視するファイル（.venv など）が無いので、枝の確かめの試験が環境で落ちうる（その項目は 3 回で諦めて修正の輪に戻る。時間だけの害）
4. 枝の試験の置き場（run ごとの置き場）は役の sandbox からも書ける。枝の確かめの試験の結末を役が曲げても、修正の輪の受け付けが全部を合わせた作業ツリーで盤面の置き場の控えから確かめ直す
5. 同じファイルの別の所を変えた枝は字では合っても意味で食い違いうる。TDD の締めのような合わせた木の緑の確かめは枝の締めに持たず、修正の輪の受け付け（変更に当たる試験と事後の関門の束）が拾い、修正役が作業ツリーで直す

## 9. 本物の run での確かめ

1. 形 g3（既定）で、範囲（allowed_paths）を持つ別々の修正案の項目に載る 2〜3 単位の依頼を回す（canary の (a)(b) の依頼でよい）。TDD の実行器の有る run と無い run の両方
2. 盤面の trace の `fix_lanes_planted` が lanes 2 以上（並べなければ why）。Archon の出来事で `fixing__fix-lane-loop-1`・`-2` の始まりの時刻が重なること。`python3 works/dev/canary_check.py <置き場>` の (a) が「修正役の並べの枝 N 本・枝の輪の同時の最大 N」で yes
3. 包みの起動の記録（`<家>/launches/<run の worktree の hash>.jsonl`）で、節 `fix-lane-<n>` の行の `fence.lane` が枝ごとに別の単位の worktree（`<run-place>/<scope>/fix-lanes/item-<n>`）で、`fence.lane_deny` に run の worktree とほかの枝が在ること。2 回目からの行の `session.mode` が continued（self-resume）、枝の 2 つ目の項目の行の `session.unit.cut` が真であること
4. 範囲の相談を起こした枝が在れば、`plan-answer-lane-<n>` の行の `session` が `{mode: continued, fork: true, from: <修正案を書いた役の id>}` で、修正案を書いた役の記録の id が変わっていないこと。盤面の trace の `plan_scope_asked` の id が重ならないこと
5. 盤面の今の scope の周の `fix-lanes-out.json`・`fix-lanes.md` と trace の `fix_lanes_settled`（merged・back・shared・union）。修正の輪の指示書（`prompt-p3.fix.md`）に節 lanes が在り、当てた単位に下請けの項目が無いこと。受け付けが通ること
6. run の後に `git -C <run の worktree> worktree list` と `git for-each-ref refs/works/units` に枝の worktree と守りの参照が残っていないこと
7. 入力 `features_off=fix_lanes` の run で `fix_lanes_planted` が lanes 0・why「入力 fix_lanes が off」で、修正の輪が今どおり全部の項目を直すこと
