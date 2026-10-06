<!-- coldwrite:skip 内部の設計書。語は「目的と語」の節と works/README.md で定義 -->
# 修正役の下請けを、範囲の重ならない項目だけ単位の worktree で並べる（依頼 243 の並べ）

状態: 入れた（既定の形 g3 の修正役の 1 回目だけ）。残りは本物の run での確かめ（下の「残り」）。

## 目的と語

読む前提: works（このリポジトリの works/ にある、修正依頼を直して出荷する仕組み）の全体は works/README.md と works/docs/specs/2026-09-27-darkfactory-single-run-design.md に在る。前の一切れ（修正役が項目ごとに新しい会話の下請けを起こす）は works/docs/plans/2026-10-06-fresh-session.md。依頼の番号は works を works 自身で直す自分食いの依頼の通し番号、run の名はその試験運用の 1 回の実行の名。

依頼 243（darkfactory の遅さの根本対策）の「単位を小さい作業ツリーで並べる」の一切れ。run 195g の修正の段は 5 単位を全部順に直した（修正役 86 分・TDD の輪 67 分・裁定の後の修正役 41 分）。前の一切れで修正役は項目ごとに新しい会話の下請けを起こすようになったが、下請けは 1 つずつ順に起きる。この一切れは、互いに触るファイルが重ならない項目の下請けを、項目ごとの小さい worktree で同時に回し、機械がその差分を決まった順で run の作業ツリーへ当てる。

この文書の語:

- 修正役・下請け: 修正のブロック（`works/blk-fix/blk-fix.yaml`）の AI の節 fix と、修正役が Claude の Agent の道具で起こす実装役・審査役（`works/.shared/core/seat.py` の `g1_section` の節）
- 項目: 下請けを起こす単位。修正案の項目（brief）か、どの項目にも無い直す義務の単位 1 つ（`works/blk-fix/lib/fixrules.py` の `g1_values`）
- 項目の範囲: 修正案の項目の「書いてよいパス」（allowed_paths の glob）と受け入れのテストのファイル（`planmarks.test_paths`）。修正の受け付け（`works/blk-fix/lib/planscope.py`）は、変更がこの範囲の外に出た行を拒む
- run の作業ツリー: Archon が run ごとに切る worktree。役の cwd で、受け付けと後の段はここを見る
- 単位の worktree: `works/.shared/core/unittrees.py`（0.2.25 の土台）が run の作業ツリーの今の姿（未 commit を含む）を base の commit にして切る、小さい git worktree。守りの参照（共通の .git の refs/works/units の下）を持つ
- run ごとの置き場: 盤面の隣の run-place（`adapter.run_place_of`）。包みが役の sandbox の書ける所に足す
- 包み・柵: Archon が起こす claude の前に挟まる `works/.shared/core/claude-adapter` と `adapter.py`。柵は役に掛ける書き込みの制限（sandbox の denyWrite と permissions.deny）
- 書き込みの記録: 包みのフックが Edit・Write の後の中身の sha を残す記録（`works/.shared/core/writes.py`）。受け付けは記録も申告（返答の bash_writes）も無い変更を拒む
- 並べる項目・順の項目: この一切れで機械が分ける 2 組。並べる項目は単位の worktree で同時に、順の項目は今どおり run の作業ツリーで 1 つずつ
- 当てる: 単位の worktree の差分を run の作業ツリーへ 3 方向で当てること（`unittrees.apply`）。当たらない（食い違う）差分は作業ツリーを変えない

## 前の道が止まった所（fan_out）

0.2.25 は Archon の `fan_out`（include の子を同時に走らせる）で単位ごとに AI を起こす道を作りかけ、止めた。Archon は起動の前に、どの子の起動かを包みに渡さない（`works/docs/darkfactory-flow.md` の fan_out の段・merge e654b0c2）。包みは子ごとに cwd を単位の worktree へ向けられない。

この一切れは Archon の外の並べを使う: 修正役は 1 つの起動のまま、Claude の Agent の道具の呼びを 1 つのメッセージに並べる（Claude Code は同じメッセージの道具の呼びを同時に走らせる）。どの下請けがどの worktree で働くかは、機械が書いた下請けのファイルが名指す。Archon にも包みの起動の見分けにも依らない。

## 柵との突き合わせ（止めになるかを先に見た）

修正役は sandbox の中で走る。調べた結果と、それぞれの決め:

1. 包みは起動の時の `git worktree list` の全部（役の worktree 自身を除く）を書かせない所に足す（`adapter.live_worktrees` → `protected_now`）。単位の worktree を修正役の起動より前に切ると、そのままでは下請けが書けない。さらに、run ごとの置き場の下に守る所が在ると、包みは置き場そのものを足さない（`with_run_place` の keep_out）。
   - 決め: 単位の worktree は run ごとの置き場の下に切り、包みは「run ごとの置き場の下に在り、この作業ツリーの守りの参照（`unittrees` の u- の参照）を持つ worktree」だけを守る所から外す。参照は共通の .git の中で、役は書けない（作れない）ので、役が自分で worktree を足して柵を外すことはできない。外すのは書く場所だけで、共通の .git・盤面・pack の守りは今のまま。
   - 単位の worktree の `.git`（共通の .git を指す 1 行のファイル）は役が書き換えうる。機械は単位の worktree で git を走らせる前に、その 1 行が切った時の物と同じかを確かめ、違えばその項目を当てずに名指す（壊れた指しで別のリポジトリに git を走らせない）。
2. sandbox は共通の .git（objects を含む）を書かせない。`unittrees.diff`・`apply` は一時の index で今の姿の木を作るので、object を書く。
   - 決め: 修正役が走らせる「当てる」コマンドは、新しい object を一時の置き場（TMPDIR。sandbox が書ける）に書き、元の objects を代わりの置き場として読む（git の GIT_OBJECT_DIRECTORY と GIT_ALTERNATE_OBJECT_DIRECTORIES）。`git apply` は作業ツリーにだけ書く。共通の .git に何も書かない（試験は共通の .git を読み取りだけにして当てる）。
3. 書き込みの記録は実パスと中身の sha で突き合わせる。下請けが単位の worktree に Edit で書いた記録は、run の作業ツリーの同じ相対パスの物に当たらない。修正役の Bash は記録（包みの家の下。守る所）に書けない。
   - 決め: 修正役の後、受け付けの前に script の節 fix-units を置く（sandbox の外）。当てた項目のファイルのうち、run の作業ツリーの中身が単位の worktree の中身と同じで、その中身に単位の worktree での記録が在る物だけ、記録に 1 行（tool_name `unit-merge`・元の実パス）を足す。中身が違う（2 つの差分を 3 方向で合わせた）ファイルは足さない。「当てる」コマンドがそのパスを differ として出し、修正役が返答の bash_writes に書く（Bash で書いた物と同じ扱い。受け付けの決まりは変えない）。

止めになる物は無かった。

## 案

### 分け方（機械）

`works/blk-fix/lib/unitlanes.py` の `lanes`（純粋な関数）:

- 項目の範囲が引けない項目（修正案の無い run の項目・どの項目にも無い単位の項目・allowed_paths の欄の無い古い案の項目）は順。
- 範囲の引ける項目どうしで、範囲が重なるかを見る。glob は字のままの頭（最初の `*`・`?`・`[` の前まで）で比べ、片方の頭がもう片方の頭の頭になっていれば重なると見る（広く重なりと見る側に倒す。重なりを見落とすと当てる所で食い違い、順に戻すだけなので害は時間だけ）。
- どの項目とも重ならない項目が並べる項目。2 つ未満なら並べない（単位の worktree を切る手間だけになる）。

範囲の正しさは受け付けが既に縛る（範囲の外の変更は拒む）。並べる項目は、受け付けを通る限り互いのファイルに触らない。

### 切る（機械。fix-prep）

並べるのは、既定の形 g3 の修正役の 1 回目（pass first の輪の 1 回目）だけ。fixrules.prep が `g1_values` に切る口を渡し、`unitlanes.plant` が:

1. この作業ツリーから前に切った単位の worktree を片付け（`unittrees.sweep`）、run の作業ツリーの今の姿（TDD の輪の直しを含む）を base にし、並べる項目ごとに `<run ごとの置き場>/<scope>/units/item-<n>` に単位の worktree を切る。
2. 控え（盤面の今の周の作業ファイル units.json。役は書けない）に、run の作業ツリー・base・項目ごとの worktree と `.git` の 1 行・「当てた」記録の置き場（run ごとの置き場の下）を書く。

並べる項目の実装役のファイルは、作業の置き場（型の [directory]）を単位の worktree にし、「その worktree の中だけで読む・書く・試験を回す。run の作業ツリーを書かない」の決まりを足す。審査役の差分のコマンドは単位の worktree と base の差分（その項目だけ）を書く。

### 回す（AI。修正役）

`seat.g1_section` に、並べる項目が在る時だけ並べの段落を載せる:

1. 並べる項目の実装役を 1 つのメッセージで全部起こす（同時に走る）。審査役も、出し直しも同じ。
2. 並べる項目が全部済んだら、当てるコマンド（`python3 <pack>/blk-fix/lib/unitlanes.py <控え>`）を 1 回走らせる。
3. conflict と出た項目は、順の項目と同じに run の作業ツリーで直し直させる（機械が書いた差分のファイルを「当たらなかった前の試み」として添える。直しを捨てない）。
4. それから順の項目を今どおり 1 つずつ。前の項目の引き継ぎの節には、並べた項目も書く。

### 当てる（機械。当てるコマンド）

`unitlanes.merge`: 控えの項目の番号の順に、`.git` の 1 行を確かめ、差分を取って `<置き場>/item-<n>.patch` に書き、run の作業ツリーへ 3 方向で当てる。項目ごとに applied・conflict・broken（`.git` の指しが違う）・empty（差分が無い）を記録（run ごとの置き場の merged.json）に積み、同じ控えで 2 度走っても当てた項目は当て直さない（修正役の起こし直しに耐える）。

### 締める（機械。fix-units）

修正役の後・受け付けの前の script の節。`unitlanes.settle`:

- 控えが無い（並べなかった周）: 何もしない。
- 記録が applied の項目: 書き込みの記録を足す（上の 3）。
- 記録の無い項目（修正役が当てるコマンドを走らせなかった）: 差分が既に当たっていれば（逆向きに当たる）applied と同じ。当たっていなければ機械が当てる。当たらなければ unmerged として差分を盤面に残し、trace に名指す（その単位の変更の欠けは、今の受け付けと変更の確かめ（申告したファイルが変わったか）が見る。直しは盤面の差分に残る）。
- 記録が conflict の項目: 修正役が順で直し直した物とみなし、差分を盤面に残すだけ。
- 最後に単位の worktree と参照を全部片付け、控えを済みの名に移す（同じ周の出し直しで 2 度締めない）。

受け付け（fix-accept）と後の段は今のまま、当てた後の run の作業ツリーを見る。

## 決定（設計に無かった所。既存の設計に一番近い物を選んだ）

- 並べるのは g3 だけ。g1 は前の一切れでも「比べの腕を変えない」として残りの単位のまとめ方を変えなかったので、同じ理由で今どおり順（口は形の名 1 つで足せる）。
- 並べるのは pass first の輪の 1 回目だけ。出し直しの回と裁定の後（fix-ruled）は、拒否や裁定が名指す項目だけを起こし直す今の手順が、前の直しの在る run の作業ツリーを前提にしている。単位の worktree を切り直すと、その前提と食い違う。
- 単位の worktree は機械（fix-prep の script）が切る。修正役の sandbox は共通の .git に書けず `git worktree add` が走らない。Claude の Agent の道具の worktree の隔離（isolation）は、Claude Code が対象のリポジトリの中に worktree を切る物で、置き場も片付けも機械が決められず、柵の外し方も無いので使わない。
- 当てる順は項目の番号の順。並べる項目は範囲が重ならないので順は結果を変えないはずで、食い違った時に後の番号の項目が順に戻る、と決まっていれば十分。
- 当てる前に作業ツリーが base から動いていても（下請けが誤って run の作業ツリーを書いた）、止めずに 3 方向で当てる。動いた分と食い違えば conflict で順に戻る。
- 範囲の重なりの見方は字のままの頭の比べ。glob どうしの交わりを正しく解くより広く重なりと見る側が安い（見落としの害は順に戻る時間だけ）。
- 期限・時間切れは足さない（R50 と同じく、上限で落とす形を作らない）。

## 危険

- 単位の worktree は base の commit を checkout した物で、git が無視するファイル（.venv・node_modules など）は入らない。試験がそれに依る対象リポジトリでは、下請けが単位の worktree で試験を回せない。その時は下請けが BLOCKED を返し、修正役は食い違いの申し出に回す（今の決まり）。
- 修正役が段落を読み飛ばして当てるコマンドを走らせなくても、fix-units が機械で当てる。ただし conflict の項目を直し直さずに返答した時は、その単位の変更が作業ツリーに欠ける。欠けは今の受け付けと変更の確かめが見る物で、この一切れは新しい関門を足していない（本物の run で確かめる。下の「残り」）。
- 下請けが単位の worktree の外（run の作業ツリー）を書くのは柵で止めていない（run の作業ツリーは修正役が書く所）。止めずに 3 方向で当て、食い違えば順に戻す。

## 入れた物

- `works/.shared/core/unittrees.py`: diff・apply に objects（新しい object の一時の置き場）を足し、共通の .git を書かずに回せる。逆向きに当たるかを見る口
- `works/.shared/core/adapter.py`・`claude-adapter`: run ごとの置き場の下の、この作業ツリーの単位の worktree を守る所から外す
- `works/.shared/core/writes.py`: 単位の worktree の記録を run の作業ツリーへ写す口
- `works/blk-fix/lib/unitlanes.py`: 分け方・切る・当てる（コマンド）・締める
- `works/blk-fix/lib/fixrules.py`・`works/.shared/core/seat.py`: 並べる項目の下請けのファイルと、修正役の節の並べの段落
- `works/blk-fix/scripts/units.py` と `blk-fix.yaml` の節 fix-units

## 残り

- 本物の run での確かめ: 修正役が並べる項目の Agent を 1 つのメッセージで起こし、同時に走ること（起動の記録と下請けの書き込みの時刻）。下請けの Edit・Bash が単位の worktree に書けること（包みの柵の外し）。当てるコマンドが sandbox の中で共通の .git を書かずに通ること（試験は共通の .git を読み取りだけにして見た）。conflict の項目を直し直さなかった返答を、今の受け付けが拒むこと。fix-units が記録を写し、受け付けが記録の無い変更で拒まないこと。
- 止まった run が残した単位の worktree は、同じ run の次の fix-prep が片付ける。run の外の片付けは、dev の殻（`works/dev/use.sh`）の run の片付け（clean・終わった run の自動の片付け・start の前の run の掃除）が、run の worktree を消す前にその worktree の単位の worktree と守りの参照（refs/works/units/<印>/ の下の base-*・u-*）を `unittrees.sweep` で消す（0.2.30）。
