<!-- coldwrite:skip 内部の設計書。語は「目的と語」の節と works/README.md で定義 -->
# 全体の確かめで出た穴を枝へ戻す（線の木の段 4）

状態: 段 4a（名札と見せる所。8 の Task 1〜3）を入れた（wip/tree4）。下の段 4b の形が使う当てるコマンド（`unitlanes.merge`）・締め（`unitlanes.settle` と修正の段の fix-units）・`fixrules.side_on` は、修正役の並べを Archon の節にした時（works/docs/plans/2026-10-07-fix-lane-nodes.md）に外した。段 4b を作る時は並べの枝の部品（`blk-fix/lib/lanekit.py`）の上に組み直す。7 の決め事 1〜7 は推しのとおり承認（2026-10-07）。段 4b（木の形。Task 4〜12）は作らずに置く（9 の測りの結論）。親の設計は works/docs/plans/2026-10-06-tree-line.md（以下「線の木」）の 2.1・2.2 の統合の行と補足・6 の段 4。

## 平たく言うと（3 行）

- 今の工場は、直した後の全体の審査で見つかった穴を、手直し役 1 人がまとめて直している。どの穴がどの直しの件（枝）から出たかを見ていない。
- 案: 機械が穴を 1 件ずつ、触ったファイルと修正案の「書いてよいパス」から枝に結び、穴の在る枝だけに新しい会話の手直し役を立てる（範囲が重ならない枝は同時に）。穴の無い枝は触らない。2 つ以上の枝にまたがる穴と、どの枝にも結べない穴は、最後に 1 人の「相乗りの手直し」がまとめて直す。
- 人が決める所（関所）は変えない。最初に、記録の残る run で穴の結ばれ方を測り、2 つ以上の枝に穴が出る run が無ければ、並べの部分は作らずに「枝の名札」だけ入れる（7 の決め事 1）。

## 目的と語

読む前提: works の全体は works/README.md と works/docs/darkfactory-flow.md、語の多くは線の木の「目的と語」に在る（darkfactory・線・ブロック・単位・項目・枝・相乗り・Agent の道具での並べ・fan_out）。

持ち主の言葉（2026-10-06。線の木から）: 木探索の形で枝ごとに深く見て、最後に枝どうしの相乗りを見る。線の木の 6 の段 4 は「差分の審査と目の穴を、ファイルと項目の allowed_paths で枝に結び、手直しで関わる枝だけの下請けを起こす」。

この文書で足す語:

- 差分の審査: ブロック `blk-delta`。修正が全部済んだ後、修正の差分の全体を 1 度見る審査役（盤面の節 `p3.delta_review`）。
- 手直し: ブロック `blk-refix`。差分の審査の穴に、同じ周のうちに答える書く役（盤面の節 `p3.delta_fix`。2 回目は `p3.delta_fix2`）。
- 独立の目: ブロック `blk-eyes`。最後のテストの後に変更の全体を見る R1〜R4。
- 穴: 差分の審査が挙げた 1 件（faces の 1 行）か、塞いだと言われたのに塞がっていなかった検算（checks の closed=false）。手直しが答える義務の 1 行（`loop.delta_owed.rows` の `{key, from, text}`）になる。
- 枝の名札: この文書の語。1 つの穴を、それが属する枝（修正案の項目の番号。どの項目にも無い単位はその単位の key）の組に結んだ物。機械が付ける。
- 枝の組・相乗りの組: この文書の語。名札が枝 1 つだけの穴を枝ごとに集めた物が枝の組、名札が枝 2 つ以上か 0 の穴を集めた物が相乗りの組。
- 枝の手直し役・相乗りの手直し役: この文書の語。手直しの役（束ね役）が Agent の道具で起こす下請け。枝の手直し役は 1 つの枝の組だけを直し、相乗りの手直し役は相乗りの組を最後に 1 度直す。
- 1 本の形・木の形: この文書の語。手直しの段の 2 つの回し方。1 本の形は今の手直し（役 1 人が義務の全部に答える）。木の形はこの案（束ね役が枝の手直し役と相乗りの手直し役を起こし、機械が答えをまとめる）。

## 1. 今の流れ（コードで確かめた事）

### 1.1 差分の審査から手直しへ

線 `works/darkfactory/darkfactory.yaml` の並び: `lensing`（レンズ）→ `reviewing`（`blk-delta`）→ `h-refix` → `refixing`（`blk-refix`）→ `h-tests` → `testing`（最後のテスト）→ `h-look` → `eyeing`（`blk-eyes`）→ `h-final` → `final-gate`（最後の人の関所）→ `report`。

- 穴の形: 差分の審査の穴は `{key, kind, where, cite, why, lens?}`。`where` は「この周の修正が触ったファイル」のパスだけを受ける（写しの規則 `graphloops/rules/review-loop.py` の `delta_review_output`。`loop.fix_delta.files` に無い where は拒む）。検算 checks の key は、修正が absorbed と答えた事前審査の穴の key（同じ所の `_claimed_closed`・`_closed_keys`）。事前審査の穴は `unit_keys` を持つ（写しの graph の `p2.plan_review` の型）。
- 義務: 盤面の機械の節 `p3.delta_owed`（`delta_owed`・`_owed_rows`）が faces と closed=false の checks を `{key, from, text}` の並びに組む。`text` は `"<kind> <where>:「<cite>」——<why>"` の 1 行で、where を別の欄では持たない。
- 2 判定の欄: 1 回目の差分の審査は、修正案の項目への準拠（compliance の行 `{item, kind, face_key, why}`）と品質を役の型にだけ持ち、受け付けが外して今の周の `delta-verdicts.json` に置く（`.shared/core/deltamarks.py`）。準拠の落ちた行は face_key で穴に結ばれ、**項目の番号を字で持つ**。
- 手直しの段（`works/blk-refix/blk-refix.yaml`）: refix-prep → refix-loop（役 refix と受け付け refix-accept。拒否 3 回まで）→ route1 → cut2 → review2-loop（2 回目の審査。読むだけ。手直しだけの差分）→ route2 → refix2-prep → refix2-loop → refix-reads → collect。
  - 支度 `refix.prep_fix`（`.shared/core/refix.py`）が `refix<n>-brief.json` に義務 owed・差分のパス・方針を書き、1 回目は承認済みの修正案の項目 `plan_items`（`refix._plan_items`。裁定で外れた項目に `held`、単位の一部が外れた項目に `held_units`）・直す裁定が広げたパス `ruled_paths`（`conflict.ruled_paths`）・準拠の落ちた行 `compliance`（`deltamarks.fail_rows`）も載せる。指示書は `blk-refix/lib/refixrules.py` が書く役の決まりの正本の全節と `rules/refix.md` から組む。
  - 役 refix は run の作業ツリーを直接書き、`handled: [{key, handled: fixed|declared, how, files}]` を返す。受け付け `refix.accept_fix` は書き込みの記録と突き合わせ（`writes.check` の strict=False。記録の無い変更は拒まずに trace へ）、写しの規則 `delta_fix_output`（義務の全部に key ごとに 1 度・fixed は files が要る）で照らす。
  - 範囲の縛り: 手直しは指示書で「項目の範囲の外で変えてよいのは ruled_paths だけ」と言われるが、受け付けは範囲を機械で照らさない。
  - 修正の形: 役 refix は g3 で座（receiving-code-review の Skill）を持つ。Agent の道具は持たない（allowed_tools に無い）。
- 出口 `refix.collect_refix`: `{ok, handled_file, review2_file, owed2, fixed2, files, reads_file, reads_files}`。2 回目の手直しが fixed と言った穴と declared の穴は、報告の次の run の依頼の下書きへ（`report.next_request` の `REFIX_NODES`）。

### 1.2 独立の目の穴は手直しへ行かない（線の木の補足の読み違いの訂正）

独立の目は手直しと最後のテストの**後**に走る。目の結果は手直しの義務にならず、最後の関所の文（`darkfactory/lib/line_edge.py` の `_eyes`・`_final_text`）と、報告の検証器の残り（`report.carry_left`）と次の run の依頼の下書き（`report.next_request`）へ行く。目の出力の形も穴の並びではない:

- R1（`r1.minimality`）: status と削除候補 `deletions[].where`。
- R2（`r2.compare`）: status と違い `differences[]`（kind・text だけ。場所が無い）。
- R3（`r3.coherence`）: status と reason だけ。
- R4（`r4.hidden_scope`）: status と浮かんだ物 `surfaced[].where`・失った能力 `capability_inventory`。

つまり「目の穴を手直しで直す」口は今の線に無い。この設計は目の穴を**枝に結んで見せる**ところまでにし（2.6）、目の後に直す段を足すのは作らない（7 の決め事 2）。

### 1.3 枝の材料（盤面に既に在る物）

- 項目: `planmarks.approved_items`（`.shared/core/planmarks.py`）が `{item, unit_keys, allowed_paths, tests, rewrite_tests, out_of_scope, …}` を項目の番号の順に返す。範囲は `allowed_paths` の glob と `planmarks.test_paths`（tests・rewrite_tests の id のファイル）。blk-fix は同じ物を `fixrules.item_ranges` で組む。
- どの項目にも無い単位: 修正役は 1 単位 1 項目の下請けにする（`fixrules.g1_values` の rest）。番号は blk-fix の中で振るので、線の外からは単位の key で呼ぶ。
- 修正が触ったファイル: 修正の返答 `p3.fix` の `changes[].{unit_key, files}`（写しの型で files は 1 つ以上）と、`loop.fix_delta.files`（修正の差分の全部のファイル）。
- 裁定で外れた項目・単位: `conflict.held_by_rulings`・`held_item`・`held_units`。

### 1.4 並べの土台

- 単位の worktree: `.shared/core/unittrees.py`（`snapshot`・`add`・`diff`・`apply`・`applied`・`remove`・`sweep`。共通の .git を書かない objects の口つき）。
- 分け方と当て方: `works/blk-fix/lib/unitlanes.py`（`overlap`・`lanes`・`plant`・`merge`・`command`・`settle`）。**ブロックの lib に在る**ので、ほかのブロックからは使えない（ブロックはほかのブロックを名指さない）。TDD の輪の並べ（`blk-fix/lib/tddlanes.py`）も同じ物を使う。
- 下請けの起こし方: 修正役（`seat.g1_section`。下請けのファイルは `fixrules.g1_values`）・TDD の輪の並べの枝の支度（`tddlanes.lane_prep`。単位の決まりのファイルは `fixrules.tdd_lane_render`。枝は Archon の節）・事前審査の束ね役（`blk-plan/lib/planblk.py` の `answers_dir`・`tree_merge`）。事前審査の木（線の木の 8 節）で、下請けは答えを盤面の外の答えのファイルに書き、機械がまとめる形に直した（束ね役が答えを写すと遅く、写しの誤りで拒まれた）。
- 道具の柵: `fixshape.DENY`・`denied_tools`。Agent は修正役（fix・fix-ruled）が g1・g3 で、TDD の輪の役（tdd）が g3 でだけ持つ。

### 1.5 時間の実測

run 195g では手直しの段（refixing）は壁の時計で 1.4 分（works/docs/plans/2026-10-06-review-once.md の 1）。この段 4 で縮む時間は小さい。値は時間ではなく次の 3 つ:

1. 穴がどの枝から出たかが、報告と最後の関所で分かる（人が見る所が絞れる）。
2. 手直し役が 1 つの枝の材料だけを持って深く見る（今の役は全部の項目と全部の穴を 1 つの会話に積む）。
3. 穴の無い枝を手直しが触らない（触った時は機械が名指す）。

## 2. 案

### 2.1 全体の絵

```
修正（枝ごと）→ レンズ → 差分の審査（全体に 1 度。今のまま）
 └ 手直しの支度（機械）: 穴に枝の名札を付け、枝の組と相乗りの組に分ける
     ├ 組が 1 つだけ・木の形を持たない修正の形 → 1 本の形（今の手直しのまま）
     └ 組が 2 つ以上 → 木の形
         ├ 枝 1 の手直し役（範囲が重ならない枝は単位の worktree で同時に）
         ├ 枝 3 の手直し役（穴の無い枝 2 は起こさない）
         ├ 機械が当てる（当たらない枝の穴は相乗りの組へ）
         └ 相乗りの手直し役（run の作業ツリーで最後に 1 度）
     → 受け付け（機械が答えをまとめ、写しの型の handled にして盤面へ）
 └ 2 回目の審査（全体に 1 度。今のまま）→ 2 回目の手直し（同じ口）
 └ 最後のテスト → 独立の目（全体に 1 度。今のまま。穴に枝の名札だけ付ける）→ 最後の関所 → 報告
```

### 2.2 穴を枝に結ぶ（機械。純粋な関数）

新しい core の模块 `.shared/core/holeties.py` の `tie(...)` が、穴 1 件ごとに枝の組（集合）と、結んだ理由（どの規則で結んだか）を返す。規則（上から順に全部当て、枝の和を取る）:

1. 準拠の行: `delta-verdicts.json` の準拠の落ちた行の face_key が穴の key と同じなら、その行の `item`。
2. 検算: checks の key が事前審査の穴の key なら、その穴の `unit_keys` を含む項目（項目に無い単位はその単位の枝）。2 回目は、1 回目の手直しでその key に答えた枝（2.4 の控え）。
3. ファイル: 穴の where（faces の欄。義務の行の text からは引かない）が、
   - 項目の `allowed_paths` の glob に当たる（`planmarks.glob_match`）か、`planmarks.test_paths` に在る → その項目。
   - 修正の `changes` で、その files に where を持つ行の `unit_key` → その単位を持つ項目（無ければ単位の枝）。
   - 2 回目は、1 回目の手直しで where を変えた枝（2.4 の控えの patch のファイル）。
4. どれにも当たらない → 枝 0（相乗りの組）。

裁定で外れた項目（held）にだけ結ばれた穴は、枝の手直し役を起こさずに相乗りの組へ入れ、行に held の理由を添える（今の決まり「held の項目に向けて直すな、declared で残し how に held を写せ」を相乗りの手直し役が守る）。

入力は全部、盤面の今の周の物（`p3.delta_review` の faces・checks、`p2.plan_review` の faces、`p3.fix` の changes、`delta-verdicts.json`、凍結した項目）。手直しのブロックは盤面の節の名を写しの DELTA_PASSES から引く今の口（`refix.passes`）で読み、ほかのブロックを名指さない。

### 2.3 組に分ける（機械）

`holeties.groups(ties)` が:

- 名札が枝 1 つの穴を枝ごとに集める（枝の組）。
- 名札が枝 2 つ以上か 0 の穴を集める（相乗りの組）。
- 枝の組のうち、範囲が互いに重ならない物を並べる枝にする（範囲は 1.3 の項目の範囲。重なりの見方は `unitlanes.lanes` をそのまま使う。2 つ未満なら並べない）。重なる枝・範囲の引けない枝（どの項目にも無い単位・範囲の欄の無い古い案）は順の枝（run の作業ツリーで 1 つずつ。新しい会話であることは同じ）。

木の形にするのは、空でない組（枝の組と相乗りの組）が 2 つ以上で、修正の形が木の形を持つ時だけ（7 の決め事 3・4）。ほかは 1 本の形（今のまま）で、支度は brief に名札の表 `ties` を足すだけ（役が穴の出どころを知る材料。答え方は変えない）。

### 2.4 手直しの段の木の形

節の並びは今の `blk-refix.yaml` のまま。refix-loop の中に、修正の段の fix-units と同じ締めの節を 1 つ足す（refix → refix-units → refix-accept）。

1. **支度（refix-prep。機械）**: `refix.prep_fix` が今の brief を書いた後、名札と組を作り（2.2・2.3）、今の周の作業ファイル `refix<n>-lanes.json`（組・名札・理由・並べる枝・順の枝。役は書けない）に置く。木の形なら:
   - 並べる枝に単位の worktree を切る（`unitlanes.plant`。置き場は run ごとの置き場の今の scope の下の `refix<n>-units/`。控えは今の周の作業ファイル `refix<n>-units.json`）。
   - 組ごとの下請けのファイル（今の周の作業ファイル `refix<n>-lanes/lane-<枝>.md`・`synergy.md`）を書く。頭（全部の下請けで同じバイト）に手直しの役の決まり（`refixrules.parts` の正本の全節・読み替え・手直しだけの決まり・座）と方針の置き場、後ろにその組の物だけ: 義務の行・その枝の項目（`plan_items` の 1 行と held_units）・その枝の準拠の行・`ruled_paths`・単位の worktree（並べる枝だけ。「その worktree の中だけで読む・書く・試験を回す」）・答えのファイルのパス（2 の形）。相乗りのファイルは、組の全部の行と名札（どの枝にまたがるか・どの枝にも結べないか）と、全部の項目を持つ。
   - 束ね役の指示書（今の `prompt-<節>.md`）に、木の手順の節（rules/refix.md の新しい節 `refix-tree`）を載せる。
2. **束ね役（役 refix。AI）**: 手順は 3 つ。
   1. 並べる枝の手直し役を 1 つのメッセージで全部 Agent で起こす（下請けの型は general-purpose 1 つ。prompt は「下請けのファイルを Read で全部読み、その指示に従え」の 1 行）。全部が済んだら当てるコマンド（2.4 の 3）を 1 度走らせる。
   2. 順の枝の手直し役を 1 つずつ起こす（run の作業ツリーで）。
   3. 当てるコマンドの出力が相乗りのファイルを名指していれば、相乗りの手直し役を 1 つ起こす（run の作業ツリーで）。
   束ね役の返答は組ごとの状態の要約 `lanes: [{lane, state: done|stopped}]` だけ（答えを写さない。線の木の 8 節の 1 と同じ理由）。
3. **下請けの答え（AI → ファイル）**: 下請けは答えの JSON を run ごとの置き場の `refix<n>-answers/<組>.json` に Write で書く（盤面は守る場所で書けない。`planblk.answers_dir` と同じ置き場の決め方）。行は `{key, handled: fixed|declared|escalate, how, files}`。`escalate` は枝の手直し役だけが使える「この枝の範囲では閉じない（範囲の外のファイルが要る・ほかの枝と食い違う）」で、how に要る所を書く。
4. **当てるコマンド（機械。束ね役が Bash で走らせる）**: `unitlanes.merge` で並べた枝の差分を run の作業ツリーへ枝の番号の順に 3 方向で当て、続けて相乗りのファイルを書き足す: escalate の行と、当たらなかった枝（conflict・broken）の全部の行（差分は「当たらなかった前の試み」として添える。直しを捨てない）。相乗りの組が空のままなら相乗りのファイルを名指さない。
5. **締め（refix-units。機械。sandbox の外）**: `unitlanes.settle` と同じ（記録の無い当て・書き込みの記録の写し `writes.carry`・当たらない差分を盤面に残す・worktree の片付け）。加えて、枝ごとに変えたファイルが自分の範囲（項目の範囲 ∪ ruled_paths）の外に在れば、trace の `refix_lanes` 行と `refix<n>-lanes.json` に名指す（拒まない。7 の決め事 5）。
6. **受け付け（refix-accept。機械）**: `refix.accept_fix` の前に、木の形なら答えのファイルをまとめる（新しい `refixtree.merge`）:
   - 組ごとに型（key・how の長さ・fixed の files）と、組の義務の全部に 1 度ずつ答えたかを確かめる。escalate の行は相乗りの答えが同じ key で在れば相乗りの答えを採り、無ければ拒む。
   - 束ね役の要約が答えのファイルと食い違えば拒む。
   - 誤りはその組の下請けのファイルの隣に機械の読める誤りの一覧（`{lane, file, errors}`）として書き、拒否の理由はそれを名指す。出し直しの束ね役は誤りの在る組の下請けだけを起こし直す（通った組は起こし直さない。線の木の 8 節の 1 と同じ）。出し直しは run の作業ツリーで（単位の worktree は締めで片付いている。並べるのは輪の 1 回目だけ＝`fixrules.side_on` と同じ決まり）。
   - 全部が揃えば、組の答えを義務の順の `handled`（写しの型のまま）に組み、束ね役の欄 `lanes` を外して `refix.accept_fix` に渡す（書き込みの記録との突き合わせ・写しの `delta_fix_output` は今のまま）。受けたら答えのファイルを今の周の控え `refix<n>-lanes/answers/` に写す。
   - 3 回目の拒否で諦めるのは今のまま（`rolekit.main_accept`）。

役の型: 写しの `p3.delta_fix` の型（handled は 1 つ以上）に、束ね役の欄 `lanes` を足し、handled を任意にした役の型を `refixtree.with_lanes(node, schema)` が作る（`deltamarks.with_verdicts` と同じ重ね方）。受け付けは形で見分ける: 支度が木の形を選んだ周は lanes が要り handled は空、1 本の形の周は handled が要り lanes は無い。YAML の output_format はこの役の型を貼る（`refix.output_format` が重ねる。`tests/test_line.py` の一致の試験はそのまま効く）。

### 2.5 2 回目（review2 と refix2）

- 2 回目の審査（review2）は今のまま全体に 1 度（手直しだけの差分を 1 人が見る）。線の木の「全体の確かめは 1 度」の形と同じ。
- 2 回目の手直し（refix2）は 1 回目と同じ口で名札を付ける（2.2 の規則 2・3 の 2 回目の行。1 回目の控え `refix1-lanes.json` と答えの控えから引く）。組が 1 つなら 1 本の形。

### 2.6 独立の目の穴に枝の名札を付ける（見せるだけ）

- 最後の関所の文（`line_edge._final_text` の目の行）と報告の目の行に、場所を持つ目の行（R1 の deletions・R4 の surfaced）の where を 2.2 の規則 3 で枝に結んだ名札を添える（例「R4: works/x.py（枝: 項目 2）」）。場所の無い R2・R3 の行は「全体」。
- 次の run の依頼の下書き（`report.next_request`）の目と手直しの行の text の終わりに、名札（項目の番号と unit_keys）を添える。次の run の判定役が、どの枝の続きかを知る材料（直す義務の形は変えない）。
- 手直しの段の名札の要約（枝ごとの穴の数・起こした枝・触らなかった枝・範囲の外の書き込み）を、最後の関所の文と報告の手直しの行に 1〜2 行で載せる。

### 2.7 今と同じに保つ物（能力の一覧）

今の手直しができる事は、木の形でも全部できる:

| 今の手直しの事 | 木の形での置き場 |
|---|---|
| 義務の全部に fixed か declared | 組の答えを機械がまとめ、写しの規則が照らす |
| 範囲の外を直す（ruled_paths・指示書の決まりだけで縛る） | 相乗りの手直し役（範囲の縛りなし）と escalate |
| held の項目・単位を直さずに declared | 下請けのファイルに held を載せる。held だけの穴は相乗りの組 |
| 方針・座（g3 の receiving-code-review） | 全部の下請けのファイルの頭 |
| 記録の無い変更を trace に | 締めの writes.carry の後、accept_fix が今どおり |
| 3 回目の拒否で諦める | 今どおり（出し直しは誤りの組だけ） |
| fixed の穴に 2 回目の審査 | 今どおり（盤面が手直しの全体の差分を切る） |
| 読んだ証拠 | `refix.must` に下請けのファイルと答えのファイルを足す |

1 本の形に落ちる場合（組が 1 つ・修正の形が木の形を持たない・項目の無い run）は、今のコードの道を通る（brief に ties が増えるだけ）。

## 3. 置き場（ブロックの独立と写し）

- core:
  - `.shared/core/holeties.py`（新）: 名札（tie）と組（groups）。純粋な関数と、盤面から入力を集める薄い口。手直しのブロックと報告・関所の文の両方が使うので core。
  - `.shared/core/unitlanes.py`（`blk-fix/lib/` から移す）: 手直しのブロックが並べに使うため。blk-fix と tddlanes は core の物を import する。当てるコマンドのパス（`unitlanes.command`）が core を指すようになる。7 の決め事 6。
  - `.shared/core/refix.py`: `prep_fix` に名札・組・木の形の支度の口、`must` に下請けと答えのファイル、`collect_refix` に `lanes_file`。
  - `.shared/core/fixshape.py`: DENY に ("Agent", {"refix", "refix2"}, {g3}) を足す（g3 の外の手直しは今と同じ道具）。
  - `.shared/core/report.py`・`darkfactory/lib/line_edge.py`: 名札の行（2.6）。
- `blk-refix`:
  - `lib/refixtree.py`（新）: 下請けのファイルの組み立て・答えのファイルのまとめ・役の型の重ね。
  - `rules/refix.md`: 節 `refix-tree`（束ね役の手順）・`refix-lane`（枝の手直し役の決まり）・`refix-synergy`（相乗りの手直し役の決まり）。
  - `blk-refix.yaml`: 役 refix・refix2 の allowed_tools に Agent、output_format を役の型に、refix-units・refix2-units の節。手直しの役は書く役なので、別の枝（per-node の model・effort）の決まりの sonnet+high を付ける（束ね役が 1 本の形では自分で直すため）。
  - `manifest.json`: produces に `refix-lanes.json`（2.6 の報告と関所が読む要約。per_include）。作業ファイル（`refix<n>-units.json`・`refix<n>-lanes/`）は scope の根の私物で公開しない。答えのファイルは run ごとの置き場（盤面の外）。
- 線 `darkfactory.yaml`: 変えない（手直しの入力は今の盤面の物だけで足りる。refixing の with も今のまま）。
- 写しの graph（`graphloops/`）: 変えない。束ね役の欄は役の型にだけ在り、受け付けが外す。`p3.delta_fix` の型と規則はそのまま照らす。COPIED_FROM の `!` 行は増えない。
- ブロックの独立: 手直しのブロックは差分の審査・修正・目のブロックを名指さない。読むのは盤面の節（写しの graph の名）と core の口だけ。

### 走っている枝との関係

- 重なりの並べ（同じファイルを持つ単位も並べる。別の枝で設計中）: この設計は並べる枝を `unitlanes.lanes` で選ぶだけで、重なりの見方を自分で持たない。重なりの並べが `lanes` か新しい口を変えれば、手直しもそのまま従う。unitlanes を core へ移すのはどちらか先に入る方がやり、後の方が import を付け替える（7 の決め事 6）。
- per-node の model・effort（wip/model-effort）: 新しい AI の節は足さない。役 refix・refix2 に付ける値は 3 の blk-refix の行のとおり。下請けは Agent の道具で起こすので節の値を持たず、束ね役の model を継ぐ。
- 線の木の段 1〜3: 段 1 の答えのファイルの形（`planblk.answers_dir`・`tree_merge`）を手本にする。段 2（修正の段の枝）が単位の worktree の形を変えても、この設計は unitlanes の口だけを使う。

## 4. 人の関所の決まり（変えない）

- 関所は増やさない・減らさない・並びを変えない。手直しの段には今も関所が無い。
- 最後の関所の文に名札の行（2.6）が増えるだけ。答え方（continue・stop・approve・reject）と開く条件（`final_gate` の always・when_needed・protected_only）は今のまま。
- 枝の手直し役が閉じなかった穴は、今どおり declared として次の run の依頼の下書きへ（名札つき）。人の答え無しに穴を消す道は作らない。
- 期限・時間切れは足さない（裁定 R50）。

## 5. 測り方

1. 名札の分布（Task 1。実装の前）: 記録の残る run（195g の efc0e05d・68f35d6b と、works-dev の archon-home の workspaces に残るほかの盤面）で、`holeties.tie` を盤面に当て、run ごとに「穴の数・枝 1 つに結ばれた穴・相乗りの組の穴・空でない組の数」を出す。
2. 木の形が効いたか: 木の形の run で、trace の `refix_lanes`（起こした組・並べた枝・当たらなかった枝・escalate の数・範囲の外の書き込み）と、手直しの段の壁の時計（refixing の頭から collect まで）。
3. 手直しの質: 2 回目の審査の closed=false の数（手直しが塞いだと言って塞いでいなかった穴）を、1 本の形の run と比べる。

## 6. 時間と費用の見込み

- 時間: 195g の手直しは 1.4 分。木の形は下請けを起こす手間（1 つ 20〜40 秒ほど）が乗るので、穴が少ない run では遅くなりうる。並べで縮むのは、穴の多い枝が 2 つ以上ある時だけ。
- 費用: 下請けはそれぞれ手直しの決まりの全文（頭）を読むので、読みの分は組の数だけ増える（頭は同じバイトにしてプロンプトのキャッシュに乗せる）。
- 見込みは測っていない。5 の 1 の分布で、木の形に当たる run が無いか少なければ、7 の決め事 1 のとおり並べは作らない。

## 7. 開いている決め事（推しつき）

1. **作る範囲を測りで決めるか**: 推しは「Task 1〜3（名札と見せる所）を先に入れ、5 の 1 の分布を見てから Task 4 以降（木の形）を作るか決める」。理由: 手直しの段は 1.4 分で、木の形の得は質と見通しの方。2 つ以上の組に穴が出る run が無ければ、木の形は手間と費用だけになる。名札は単独で人の見る所を絞れる。
2. **独立の目の穴を同じ run で直す段を足すか**: 推しは「足さない。名札だけ付ける（2.6）」。理由: 目は最後のテストの後で、直すとテストと 2 回目の審査と目をもう 1 度回す新しい輪になり、線の並びが変わる。R2・R3 の多くは場所の無い設計の判定で、人の関所と次の run の判定役が扱う物。直す段は、名札の分布で「場所を持つ目の穴が枝に結べる」run が多いと分かってから別の設計にする。
3. **組が 1 つの時**: 推しは「1 本の形（今のまま）」。下請けを 1 つ起こす手間に見合う得が無い。枝の組 1 つだけの時も同じ（今の役でも、その枝の材料は brief に在る）。
4. **木の形を持つ修正の形**: 推しは「g3 だけ」（`fixrules.side_on` と同じ。g1 は比べの腕なので変えない、af・current は Agent を持たせない）。
5. **枝の手直し役が自分の範囲の外を書いた時**: 推しは「拒まずに名指す（trace と最後の関所の文）」。今の手直しは範囲を機械で照らしておらず、拒むと今できる直しができなくなる（能力を減らす）。範囲の外が要る時は escalate で相乗りへ回すよう決まりに書く。測りで外の書き込みが多ければ、拒む形を別に決める。
6. **unitlanes を core へ移す時期**: 推しは「重なりの並べの枝が先に入るなら、その枝の上で移す。この段 4 が先なら段 4 の Task 4 で移す」。どちらでも口（`lanes`・`plant`・`merge`・`settle`・`command`）の名は変えない。写して 2 つ持つ形は採らない（直しが片方にしか入らない）。
7. **相乗りの手直し役を下請けにするか、束ね役が自分で直すか**: 推しは「下請け」。束ね役は 1 本の形への落ちと同じ節なので書く道具を持つが、木の形では枝の答えと相乗りの答えを同じ答えのファイルの形にそろえ、機械のまとめを 1 つにする。

## 8. Task（TDD の大きさ）

各 Task は試験を先に書いて赤を見てから直す。新しい試験の模块は `works/tests/tiers.py` の FAST か HEAVY に載せる。

段 4a（名札と見せる所。7 の決め事 1 の承認の前でも入れられる）:

1. **名札の純粋な関数**（`holeties.tie`・`groups`）: 規則 1〜4 と held と 2 回目の行を、盤面を使わない見本の入力で赤から緑に。見本: 準拠の行だけで結ばれる穴・検算の key から unit_keys で結ばれる穴・where が 2 つの項目の glob に当たる穴（相乗り）・どれにも当たらない穴・held の項目だけに当たる穴・項目に無い単位の changes で結ばれる穴。
2. **盤面から入力を集める口と分布の測り**: `holeties.from_board(b, n)` を盤面の見本（tests の盤面の手本）で緑に。dev の測りの口（`works/dev/` に、盤面のパスを受けて 5 の 1 の表を出す script）を足し、記録の残る run に当てて結果をこの文書に書く。
3. **見せる所**: 手直しの支度の brief に `ties`、最後の関所の文と報告の目・手直しの行に名札、次の run の依頼の下書きの text に名札（2.6）。関所の文と報告の見本（golden）を同じ commit で直す。

段 4b（木の形。7 の決め事 1 の後）:

4. **unitlanes を core へ移す**（7 の決め事 6）: 口と振る舞いは変えず、blk-fix・tddlanes の import と当てるコマンドのパスを付け替える。今の unitlanes の試験がそのまま緑であること。
5. **道具の柵**: `fixshape.DENY` に手直しの役の Agent の行。g3 で拒まず・af・current・g1 で拒む試験。
6. **役の型と YAML**: `refixtree.with_lanes` と `refix.output_format` の重ね、`blk-refix.yaml` の allowed_tools と output_format（`tests/test_line.py` の一致）、refix-units・refix2-units の節。
7. **支度の木の形**: `refix.prep_fix` が組を作り、並べる枝に worktree を切り、下請けのファイルと束ね役の節を書く。見本の git リポジトリと盤面で、組が 1 つなら今と同じバイトの指示書（1 本の形）、2 つ以上なら下請けのファイルの頭が同じバイトで後ろが組ごと、を確かめる。
8. **当てるコマンドの相乗りの書き足し**: escalate の行と当たらなかった枝の行が相乗りのファイルに載ること、相乗りの組が空なら名指さないこと。
9. **受け付けのまとめ**（`refixtree.merge`）: 欠け・重なり・escalate の行き先・要約の食い違いで拒み、誤りの一覧をその組にだけ書くこと。揃えば写しの型の handled になり `delta_fix_output` を通ること。
10. **締めの範囲の名指し**: 範囲の外の書き込みを trace と `refix-lanes.json` に名指し、拒まないこと。
11. **線の模擬実行**: stub と fixtures（`blk-refix/fixtures/pass.stubs.yaml` に木の形の場面）、YAML の形の試験を同じ commit で直す。
12. **本物の run**: 2 つ以上の項目に差分の審査の穴が出る依頼で回し、5 の 2・3 を測ってこの文書に書く（束ね役が下請けを 1 つのメッセージで起こしたか・下請けに残る道具（Skill の座が効くか）・単位の worktree に書けたか、を起動の記録で見る）。

## 9. 段 4a で入れた物と、名札の分布の測り（2026-10-07）

### 入れた物

- `.shared/core/holeties.py`: `tie`・`earlier`・`groups`・`spread`・`note`・`lines`・`count_line`・`unit_path`・`lead_path`（純粋な関数）。
- `.shared/core/refix.py`: `hole_ties(b, n)`（盤面の今の周から入力を集める。読むだけ）・`tie_items(b)`（項目に裁定の held を足す。
  引けなければ []。盤面を止めない）・`brief_ties`。手直しの支度 `prep_fix` が 1 回目・2 回目とも brief に `ties` を載せる（組めなければ
  `ties_error`）。`blk-refix/rules/refix.md` の頭の節 2 つに `ties` の読み方を足した（答え方は変えない）。
- `.shared/core/report.py`: `branch_rows(b)`・`eye_ties(b)`。報告の冒頭 1（`head_decisions`）と最後の関所の文（`line_edge._final_text`
  の差分の審査の穴の行の次）が同じ行を出す。穴も目の場所の行も無ければ行を足さない。次の run の依頼の下書きは、手直しが declared で
  残した穴と 2 回目の fixed の穴の text の終わりに `（枝: 項目 1）` を添える。
- `dev/holespread.py`: 記録の残る盤面を開かずに読み（読むだけの入れ物）、名札の分布を出す測りの殻。
- 試験: `tests/test_holeties.py`（FAST）と `tests/test_plan_gate.py` の 1 本（関所の文と冒頭 1 に名札の行が出る）。`tests/test_blk_refix.py`
  （HEAVY）の brief の欄の試験に `ties` を足した。

設計からの差:

- 規則に `unit`（単位の key の頭のパスが where と同じ）を足した。195g の系の run は修正の `changes` が空の盤面が在り（単位が全部
  裁定で外れた run）、範囲の欄の無い盤面でも単位の key は `<パス>: <一言>` の形でパスを持つので、それで結べる。
- 2.3 の「並べる枝・順の枝」の分けは段 4b の物なので入れていない（`groups` は枝の組と相乗りの組だけ。unitlanes は blk-fix の lib の
  ままで、core からは呼べない）。
- 2.6 の「次の run の依頼の下書きの目の行に名札」は入れていない。目の行は検証器の残り（`carry_left`）の形で来て場所を持たないので、
  名札は最後の関所の文と報告の冒頭 1 に出す（R1 の削除候補は次の run の判定役が `prev.r1.minimality` で読むので、そこは今のまま）。

### 測り（`python3 works/dev/holespread.py <盤面>…`）

works-dev の archon-home の workspaces に残る盤面 13 本（run-195g の 6 本・240・244〜249）。穴は 1 回目の手直しの義務の行
（差分の審査の faces と塞がっていない検算）:

| run | 項目 | 穴 | 枝 1 つ | 2 つ以上 | 結べない | held だけ | 穴の在る組 | 2 回目の穴 | 目の場所の行 |
|---|---|---|---|---|---|---|---|---|---|
| 195g 03734200 | 1 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| 195g 2a39a6da | 1 | 4 | 4 | 0 | 0 | 0 | 1 | 0 | 2 |
| 195g 68f35d6b | 2 | 1 | 0 | 0 | 0 | 1 | 1 | 0 | 6 |
| 195g 904584b2 | 2 | 6 | 0 | 0 | 0 | 6 | 1 | 0 | 1 |
| 195g ade64af0 | 1 | 1 | 1 | 0 | 0 | 0 | 1 | 0 | 4 |
| 195g efc0e05d | 3 | 1 | 0 | 0 | 0 | 1 | 1 | 0 | 4 |
| 240 175a5a0e | 2 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| 244 7d915b24 | 1 | 3 | 3 | 0 | 0 | 0 | 1 | 0 | 4 |
| 245 9f91d15f | 1 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 1 |
| 246 63fffb26 | 1 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 1 |
| 247・248・249 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |

読めた事:

- 穴は 13 本で 16 件。全部がどれかの枝に結べた（結べないは 0）。結んだ規則は path が 13 件、change 7 件、check 3 件、compliance 2 件、
  unit 3 件（1 件に複数が当たる）。
- **穴の在る組が 2 つ以上の run は 0 本**。項目が 2 つ以上の run（68f35d6b・904584b2・efc0e05d・240）の穴は、どれも裁定で外れた項目に
  当たる穴だけか、穴が無い。木の形（2.4）が起きる run は 1 本も無かった。
- 唯一の近い例は 904584b2: held を無視すれば項目 1 に 2 件・項目 2 に 3 件・両方にまたがる検算 1 件で組が 3 つになる。ただしこの run の
  項目は 2 つとも裁定で外れていて、今の手直しの決まりでは全部 declared で残す穴（直さない）。
- 2 回目の審査の穴は 13 本とも 0 件。
- 手直しの段の時間は 195g で 1.4 分（1.5）。木の形で縮む時間はもともと小さい。

### 段 4b を作るか（推し: 今は作らない）

推しは「段 4b（木の形）は作らずに置き、名札だけを使う」。理由:

1. 測った 13 本で木の形に当たる run が 0 本。作っても今の run では 1 本の形に落ちるだけで、試験と保守の量（役の型の重ね・YAML・
   支度・当てるコマンド・受け付けのまとめ・模擬実行の stub）だけが増える。
2. 時間の得が小さい（手直しは 1.4 分）。質の得（枝ごとに材料を絞る）は、名札を brief に載せたことで 1 本の形の役にも一部届く。
3. 再び考える引き金: `dev/holespread.py` を新しい run の盤面に当て、held でない穴の在る組が 2 つ以上の run が出たら（特に、組ごとの
   穴が多く、手直しの段が数分を超える run）、その盤面を見本にして段 4b を作る。重なりの並べの枝が unitlanes を core へ移した後なら、
   Task 4 は要らない。
