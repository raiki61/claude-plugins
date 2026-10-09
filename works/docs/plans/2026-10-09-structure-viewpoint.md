<!-- coldwrite:skip 内部の設計書。語は「語」の節と works/docs/concepts.md で定義 -->
# 考えの住処の観点を、works の線と開発の流れに組み込む（実装計画）

状態: Task 1 は済み（枝 wip/concept-fences）。Task 2〜7 と決め事 10・4.2 節（CLAUDE.md の 4 行）・5 節の順は、計画 `docs/plans/2026-10-09-clean-whole.md` の 7 節のとおり直した（Task 2〜4 は同じ計画の Task 2.1・2.7、Task 5 は Task 2.8、Task 7 は Task 3.4 に置き換え。CLAUDE.md の 4 行は取り下げ）。以下は元の本文。設計と計画だけ（コードは変えていない）。並行の片付けの 5 束が出荷した後に入れる（Task 3・4 が触る `blk-plan/lib/planblk.py`・`blk-eyes/lib/eyes.py` を束が直しているため）。決め事は持ち主の原則（CLAUDE.md の「判断の線」）に沿って自分で決めた。持ち主の承認が要るのは Task 6 の CLAUDE.md の 4 行だけ。Task は 7 つ。

> **実装する者へ:** CLAUDE.md の決まりで、works の直しは darkfactory 自身に流す（Task ごとに 1 つの依頼。依頼の本文はその Task の節）。手で回す時は superpowers:subagent-driven-development か superpowers:executing-plans で Task ごとに進める。手順は `- [ ]` で追う。

**目的:** works の設計の考えごとに住処（1 か所で持つ部品）を持たせ、直しが考えを知る所を増やした時に、線の役（事前審査・R1・R3）と安い試験（柵）と開発の流れのどれかが必ず気づく形にする。

**作り:** 観点の文と地図の探し方は新しい core のモジュール `concepthome` 1 つが持ち、既にある役の指示書の頭（works が足す節）に貼る。写しの指示書は 1 バイトも変えない。見つけた物は既にある型（事前審査の穴の kind `copy`、目の `redesign-needed`）に、頭の語「考えの住処: 」を付けて載せる。柵は試験の道具 1 つと表 1 つ（`docs/concepts.json`）で、地図 `docs/concepts.md` と食い違えば赤にする。

**道具:** Python 3（標準ライブラリだけ）・unittest・git。

**仕様:** この文書の 1〜6 節と地図 `works/docs/concepts.md`（同じ commit で足した）。

## 平たく言うと（3 行）

- 持ち主の見立て（2026-10-09）: works は育つほど綺麗にならない。考えが名前の付いた単位にならず、条件分岐や写した欄の名として散らばる。どの段も「この考えはどこに住むか・単位は在るか」を問わず、「最小の直し」の決まりがその場の継ぎ当てを褒め、全体の絵を持たない役が 1 件ずつ直し、整える段も無い。
- 案: (a) 線の 3 つの役（事前審査・R1・R3）に「考えの住処を使うか、知る所を増やすか」を問わせ、R1 の「最小」を行数でなく「考えを知る所が増えない」に読み替える。(b) 住処の在る考えには、住処の外に漏れたら赤になる安い柵を、道具 1 つと表 1 つで掛ける。(c) 開発の流れの計画の型に「考えの棚卸し」の節、緑の後の整え、出荷の前の地図の直し、10 版ごとの構造の監査を足す。
- 新しい目（役）は足さない。費用の増えは役の指示書の頭の数段落と、地図を読む分だけ。

## 語

- 考え・住処・約束・知ってよい所・漏れ・散らばり・柵: `works/docs/concepts.md` の「語」の節
- 知る所: ある考えの語・欄の名・値・判定の式を書いている所（住処を含む）。「知る所が増える」は、直しの後にそれを書く所が直しの前より多いこと
- 地図: 対象のリポジトリの `docs/concepts.md`（根の、またはどのフォルダの下でもよい）。works 自身の地図は `works/docs/concepts.md`
- 事前審査: 修正案を、書く前に別の目が叩く役（写しの節 `p2.plan_review`。works のブロック `blk-plan`）
- R1・R3: 修正の後の独立の目（ブロック `blk-eyes`）。R1 は「直しが最小か」（写しの節 `r1.minimality`、役 judge）、R3 は「前提と全体の筋」（写しの節 `r3.coherence`、役 inspector）
- 頭の節: works が写しの指示書の前に足す節（`---` で区切る。前例: `blk-eyes/lib/eyes.py` の `PREMISE_HEAD`・`gatemarks.carried_section`、`blk-plan/lib/planblk.py` の `REUSE_REVIEW`）
- 写し: `works/.shared/core/graphloops/` と `works/.shared/core/gl-prompts/`。本流のバイト一致で縛られ、works は直さない（`tests/test_core_verbatim.py`・`tests/test_rejudge.py`）

パスは断りが無ければ `works/` からの相対。

## 1. 決め事

1. **新しい目を足さない。** 観点は既にある 3 つの役に頭の節で足す（持ち主の指示）。役が起きる回数は変わらない
2. **写しの指示書は変えない。** `p2.plan_review.md`・`r1.minimality.md`・`r3.coherence.md` は写しで、`COPIED_FROM` の `!` 行を足す道もあるが、works は頭の節で足すのが前例（上の「頭の節」）。頭と本文がぶつかる所（R1 の「最小」）は、頭が「下の指示書の X はこの意味で読め」と読み替えを名指す（前例 `.shared/core/seat.py` の `G1_SUB_HEAD_OF`「上の型の文にも…勝つ」）
3. **観点の文の住処は 1 つ。** 新しい core のモジュール `.shared/core/concepthome.py`（層 L3・持ち主なし。`blk-plan` と `blk-eyes` の 2 つのブロックが使うので L4 に置けない）。文・頭の語・地図の探し方はここだけが持ち、ブロックは定数と関数を呼ぶだけ。この計画自身が考え「考えの住処の観点」を 1 か所に置く
4. **見つけた物の型は今の型を使う。** 欄も kind も足さない:
   - 事前審査: 穴（`faces`）の kind `copy`（写しの指示書の「見ること 1. 写し」——既に正本を持つ規則・型・語彙を別の場所に写していないか——が同じ問いの小さい形）。`why` を「考えの住処: 」で始める（前例: 独立設計との食い違いの穴は `why` を「独立設計との構造の食い違い: 」で始める。`planblk.DESIGN_ASK`）。修正役は今どおり穴ごとに取り込んだ（absorbed）か残すと宣言した（declared）かを答える
   - R1: 住処を名指せる漏れは `status: redesign-needed`、`reason` を「考えの住処: 」で始め、増えた所を `deletions` に 1 行ずつ。住処の無い考えを散らした物は `increments` に「考えの住処: 」で始まる 1 行（status は変えない）
   - R3: 住処を名指せる漏れは `status: redesign-needed`、`reason` を「考えの住処: 」で始める。住処の無い物は `pass` のまま `reason` に書く
   - 区別の理由: 1 周の線では独立の目の `redesign-needed` が結末を `round_limit` に下げる（`skills/works/SKILL.md` の結末の節）。住処を名指せない指摘で結末を下げない
5. **住処を名指せない物は挙げない。** パスと行を書けない「住処」は推測なので、事前審査は穴にせず、目は `redesign-needed` にしない（対象のリポジトリでの雑音の主な防ぎ。7 節）
6. **地図の探し方は汎用。** 役はほかのリポジトリも審査するので、works を名指さない。地図は「読む版の木に在る `docs/concepts.md`（根か、どのフォルダの下でも）」。機械が `git ls-tree` で探してパスを頭の節に並べ、役が Read で読む。無ければ役は対象のリポジトリ自身の構造（README・モジュールの境・同じ語を定数で持つ所）から住処を探す。名前の決め方は `.editorconfig` や `CODEOWNERS` と同じ「決まった名のファイルが在れば読む」形。works は自分の地図を `works/docs/concepts.md` に置くので、このリポジトリを対象にした run で見つかる
7. **柵は道具 1 つと表 1 つ。** 表は地図の隣の `docs/concepts.json`、道具は `tests/conceptfence.py`、試験は `tests/test_concept_fences.py`（速い段）。表に書くのは「知ってよい所の外での語の形」と既知の漏れだけ（語の一覧を全部書かない）。既知の漏れは「ファイル → 件数と理由」で、減らす向きにだけ動かす（`tests/blockblind.py` の許可表と同じ型。ESLint の bulk suppressions と同じ）。地図と表は id と状態が揃うことを試験が見る（地図が古くなるのを防ぐ一番安い同期）
8. **今ある柵は移さない。** `tests/test_layers.py`（層）・`tests/test_block_blind.py`（ブロックの独立）・`tests/test_duty_owner.py`（直す義務の持ち主）は、それぞれ考えの柵として地図から名指すだけにする。移すのは、それらを別の理由で触る時（作り替えのついでの取りこぼしを避ける）
9. **入切の語（`features_off`）は足さない。** 測りは前の版の canary の run と比べる（Task 5）。雑音が多ければ `concepthome` の文を 1 か所で直すか外す
10. **開発の流れの決まりは CLAUDE.md に書く**（このリポジトリで作業する AI が読む所。superpowers のスキルは借り物で直さない）。CLAUDE.md は持ち主の決まりなので、Task 6 の 4 行は持ち主の承認を得てから入れる
11. **構造の監査は 10 版ごと。** 出荷は 1 日に 5〜10 版（CHANGELOG 0.2.39〜0.2.51 が 2026-10-08〜09）なので、1〜2 日に 1 回。目安は「版の下の桁が 0 になる版を出す前」。`/doctor-loop` は人が打つ時だけの決まりなので、監査は AI が手で回す手順（Task 7）にし、深く見たい時に `/doctor-loop` を持ち主に 1 行で勧める

## 2. 線の中の変え方（a）

### 2.1 観点の文（`concepthome` の定数。字のまま）

`PREFIX = "考えの住処: "`

`PLAN_RULE`（修正案の役の頭。`planblk.HEAD["plan"]` の末尾）:

> 考えの住処を使え: 案が触る考え（設計の決まりごと。例: 結末の語・止めの理由・無人の時の方針）ごとに、それを 1 か所で持つ所（住処）が対象のリポジトリに在るかを先に探せ（下の『考えの住処の地図』の節に地図が在ればその行、無ければ README・モジュールの境・同じ語を定数で持つ所を Grep で）。住処が在れば案はそこを変え、ほかの所に同じ語・欄の名・値・判定の式を写さない。それでも adds の行が考えを新しい所に知らせるなら、その行の canonical に「考えの住処: <考え> の住処は <パス>」と、住処を使わない理由を書け。住処の無い考えに足す時は、既にその考えを知っている所に寄せ、知る所を増やさない形を先に選べ。

`REVIEW_ASK`（事前審査の役の頭と、項目ごとの下請けの共通の頭。`planblk.HEAD["plan-review"]` と `planblk.brief_head`）:

> 考えの住処を見よ: 案の adds と approach が触る考えごとに、対象のリポジトリにその考えの住処（1 か所で持つ所）が在るかを確かめよ（下の『考えの住処の地図』の節に地図が在ればその行、無ければ自分で Grep）。案が住処を使わずに、別の所にその考えを知らせる（語・欄の名・値・判定の式を写す）なら kind copy の穴に挙げ、why を「考えの住処: 」で始めて、考えの名・住処のパスと行・新しく知る所を書け。住処が在るのに使わない案は severity block、住処の無い考えの知る所を増やす案は suggest。住処のパスと行を書けない物は挙げない。構造の目の行がその単位で「責務を 2 か所に割る」を既に挙げ、案がその避け方（chosen）に従っているなら挙げ直さない。

`R1_HEAD`（R1 の頭。`{section}` に地図の節）:

> ## 最小の意味（works が足した読み替え。下の指示書の「累積差分が最小か」と観点の正本の「処方の最小性」の大きさは、この意味で読め）
>
> 最小は行数でなく、考え（設計の決まりごと）を知る所の数で量る。累積差分の後、どの考えも、それを知る所（語・欄の名・値・判定の式を書く所）が差分の前より増えていなければ最小である。考えを住処（1 か所で持つ所）へ移すために行が増えた差分は最小に数え、数行で済ませたが同じ考えを別の所にもう 1 つ知らせた差分は最小でない。零処方から並べる順は保ち、処方の大きさをこの数で量れ。住処のパスと行を名指せる考えの知る所が増えていれば status を redesign-needed にし、reason を「考えの住処: 」で始めて考えの名と増えた所を書き、増えた所を deletions に 1 行ずつ（where は増えた所、why は住処のパスと行）置け。住処の無い考えの知る所が増えただけなら status は変えず、increments に「考えの住処: 」で始まる 1 行を置け。
>
> {section}

`R3_HEAD`（R3 の頭）:

> ## 考えの住処（works が足した観点）
>
> 差分が触る考えごとに、対象のリポジトリの中での住処（1 か所で持つ所）を確かめよ。下の地図の節に地図が在ればその行を正とし、無ければリポジトリ自身の構造（README・モジュールの境・同じ語を定数で持つ所）から住処を見つけよ。差分が考えを住処の外に書き足している、または住処と違う形で同じ考えを持ち直していて、住処のパスと行を名指せるなら、status を redesign-needed にし、reason を「考えの住処: 」で始めて考えの名・住処・外の所を書け。名指せない物は pass のまま reason に書け。読んだ地図（地図が無ければ構造から見つけた住処）を seen に、住処を見つけられなかった考えを unseen に含めよ。
>
> {section}

地図の節（`concepthome.section` の返り）:

- 見つかった時: `## 考えの住処の地図（機械が読む版の木から探した。先に Read で読め）` と、パスを 1 行ずつ（深さの浅い順、同じ深さは名の順。最大 5。超えた分は「ほか N 件」）。続けて 1 行「審査するファイルを含むフォルダの地図を正とする」
- 見つからない時: `## 考えの住処の地図` と 1 行「無い（探した形: 読む版の木の docs/concepts.md。根とどのフォルダの下でも）。住処はリポジトリ自身の構造から探せ」
- 木を読めない時（git が落ちた）: 見つからない時と同じ文に「（木を読めなかった: <理由>）」を足す。役を止めない

### 2.2 どこに貼るか

| 役 | 貼る所 | 文 |
| --- | --- | --- |
| 修正案 | `planblk.HEAD["plan"]` と `head` の新しい引数 | `PLAN_RULE`・地図の節 |
| 事前審査 | `planblk.HEAD["plan-review"]`・`brief_head`・`head` の新しい引数 | `REVIEW_ASK`・地図の節 |
| R1 | `eyes.prep` の頭の節 | `R1_HEAD` |
| R3 | `eyes.prep` の頭の節 | `R3_HEAD` |

- `planblk.prep` の 2 つの道（いつもの道と、同じ run の中の案の直し `replan_mod.prep`）はどちらも `head(...)` を通るので、地図の節は `head` の引数で 1 回渡せば両方に載る
- 読む版は盤面の `inputs.review_rev`、対象の根は `inputs.cwd`（写しの rules の `on_init` が置く）
- R2・R4・差分の審査・レンズには足さない（R2 は文脈を遮断した独立設計なので地図を渡すと隔離が壊れる——`REVIEW.md` の「ゼロベースで疑う役には渡すな」。R4 は範囲の目で問いが違う）
- 構造の目（`blk-structure`。道具ゼロ）には足さない。形 2「責務を 2 か所に割る」が同じ考えの単位ごとの形で、事前審査の文が重ねて挙げない決まりを持つ

### 2.3 記録と報告

新しい欄・置き場は作らない。事前審査の穴は今の `faces` の道（修正役の答え・報告の事前審査の節）、R1・R3 は今の目の行（最後の関所の目の行・報告の独立の目の節・`reason` が報告にそのまま写る）を通る。頭の語「考えの住処: 」で、測り（Task 5）と人が数えられる。

## 3. 柵（b）

### 3.1 表 `docs/concepts.json`

```json
{"about": "考えの住処の地図（docs/concepts.md）の柵の表。読むのは tests/conceptfence.py だけ",
 "exclude": ["tests/**", "docs/**", "CHANGELOG.md", "README.md", "skills/**", "**/fixtures/**",
             "dev/canary-fixture-units/**", "dev/board-goldens/**", ".shared/core/graphloops/**",
             ".shared/core/gl-prompts/**", ".shared/borrow/**", "darkfactory/darkfactory.graph.json"],
 "concepts": {
   "outcome": {"status": "住処あり", "fences": [
     {"what": "結末の語", "pattern": "\"(no_fix_needed|stopped_by_line|stopped_by_request|stopped_by_human|needs_human|round_limit)\"",
      "allowed": [".shared/core/report.py", "darkfactory/darkfactory.yaml", "dev/**"], "known": {}}]},
   "carry-over": {"status": "散らばり", "fences": []}}}
```

- `exclude` の理由: 文書・利用者への説明・写し（直せない）・生成物（`darkfactory.graph.json` は YAML から作る）・試験の材料。役の指示書（`blk-*/commands`・`rules`）は見る（役に考えを焼き付けるのも漏れ）
- `allowed` と `exclude` の照らしは `fnmatch.fnmatch`（`*` は `/` もまたぐ）
- `known` は `{"<パス>": [件数, "理由"]}`。件数は「語の形に当たる行の数」

最初に掛ける柵（住処ありの 11 の考え。`pattern`・`allowed` は字のまま。`known` は Task 1 の手順 3 で走らせた結果を理由つきで置く）:

| id | pattern | allowed |
| --- | --- | --- |
| `outcome` | 上の例 | 上の例 |
| `depth` | `"depth\.json"\|\bdepth\.(unit_depth\|run_depth\|decide_doc\|raise_doc)\b` | `darkfactory/**` |
| `features` | `"(fix_lanes\|tdd_lanes\|judge_verify\|review_tree\|graph_map)"` | `.shared/core/entry.py`・`darkfactory/darkfactory.yaml`・`dev/use.sh`・`dev/dogfood.sh` |
| `hinge` | `\bh-(entry\|judge\|mat\|plan\|structure\|gate\|fix\|depth\|replan\|regate\|refit\|rejudge\|mid\|redepth\|review\|refix\|tests\|look\|final\|eyes)\b` | `darkfactory/**`・`dev/**` |
| `halt` | `"STOP"` | `.shared/core/halt.py`・`dev/stop.sh`・`darkfactory/lib/line_edge.py` |
| `scope` | `"manifest\.json"` | `.shared/core/scopes.py`・`.shared/core/entry.py` |
| `reads` | `"reads-\|reads\.jsonl` | `.shared/core/reads.py`・`.shared/core/adapter.py`・`.shared/core/record-read.py`・`blk-*/scripts/reads.py`・`blk-*/manifest.json` |
| `conflict` | `why_both_cannot_hold\|which_is_right` | `.shared/core/conflict.py`・`blk-fix/**` |
| `injectors` | `--append-system-prompt` | `.shared/core/adapter.py`・`.shared/core/claude-adapter` |
| `replycontract` | `--json-schema\|StructuredOutput` | `.shared/core/replycontract.py`・`.shared/core/adapter.py`・`.shared/core/diverted.py` |
| `writes` | `\bWRITE_OPS\b\|\bapply_writes\b` | `.shared/core/board.py` |

（表の `\|` は Markdown の表の中の `|` の書き方。JSON には `|` で書く。）

既知の漏れの件数は 22d98fdc の測りで、`outcome` は 0（結末の語を持つ `.py` は住処だけ）、`features` は `adapter.py` 2・`fixlanes.py` 1・`tddloop.py` 1・`planblk.py` 1・`judgeverify.py` 1（`TRACE_OP` の同名の別の語）・`dev/canary_check.py` 4（`dev/**` を allowed にしないので既知に置く）。

### 3.2 決まり

1. 理由を 1 文で書けない既知の漏れは表に置かず、その考えを散らばりに戻して地図に計画のリンクを書く（柵は住処の在る考えにだけ掛ける）
2. 同名の別の語（`TRACE_OP = "judge_verify"`、`lanes` の 2 つの意味、`unattended` の 2 つの意味）は理由に「同名の別の語」と書いて既知に置き、名前を替えるのは散らばりをまとめる計画の仕事にする
3. 散らばりを住処へまとめた計画は、最後の Task で地図の状態を `住処あり` にし、柵を表に足す

## 4. 開発の流れ（c）

### 4.1 計画の型（新しく `docs/plans/README.md`）

計画（`docs/plans/*.md`）は次の節をこの順で持つ。今の計画の書き方（状態の行・平たく言うと・語・決め事・Task・危うさ）を型にし、「考えの棚卸し」を足す。

1. 状態の行
2. 平たく言うと（3 行）
3. 語
4. **考えの棚卸し**: 計画が触る考えを 1 行ずつ。書く物は id（地図 `docs/concepts.md` の id。無ければ新しい id）・今の住処（無ければ「散らばり」）・計画の後の住処・知る所の増減（例「-2」「0」「+1（理由）」）。増える行には理由を書く。全部の行が 0 以下の計画が既定
5. 決め事
6. Task（superpowers:writing-plans の形）
7. 危うさ

### 4.2 CLAUDE.md に足す 4 行（持ち主の承認が要る）

「## 試験」の後に節「## 設計の観点（考えの住処）」を足す:

- 計画は「考えの棚卸し」の節から始める（型は `works/docs/plans/README.md`、地図は `works/docs/concepts.md`）。触る考えの住処を使い、知る所を増やさない形を先に選ぶ。
- 試験が緑になった後、commit の前に整える: 触った考えの知る所が増えていれば、試験を緑のまま住処へ寄せる（寄せられなければ計画の棚卸しに理由を書く）。
- 出荷（works の版）の 1 の前に: 触った考えの地図の行（住処・知ってよい所・状態）と柵の表を直した。
- 版の下の桁が 0 になる版を出す前に、構造の監査（`works/docs/concepts.md` の「この地図の育て方」の手順）を回す。

あわせて「## 出荷（works の版）」の 1 の頭に「（地図と柵の表を直してから）」を足す（上の 3 行目と同じ中身を出荷の手順の側からも辿れるように）。

### 4.3 構造の監査の手順（`docs/concepts.md` の「この地図の育て方」に足す）

1. 散らばりの各行の「今」に挙げた所を grep し直し、増えた・減った所で行を直す
2. 前の監査からの CHANGELOG の版で足した欄・定数・入力の語を拾い、どの考えに属するかを決める。属さなければ新しい行を足す
3. 2 か所以上が同じ語を定数で持つ物（`git grep -c` で 2 ファイル以上）を拾い、住処ありの考えなら柵の既知に、散らばりなら行の「今」に足す
4. 結果は地図と表の差分 1 つの commit（メッセージに監査の版）。直す仕事は散らばりをまとめる計画（5 節）の順に足す
5. 1〜3 で見切れない時は、持ち主に `/doctor-loop` を 1 行で勧める

## 5. 散らばりをまとめる順

それぞれ別の計画にする（この計画では立てない）。順は「漏れの数を減らす量 ÷ 手間」と、前の計画への乗りやすさで決めた。

1. `entry-kind`・`start-record`: 計画 `docs/plans/2026-10-09-one-entry-shape.md`（枝 `wip/one-entry-plan`）が既に在る。最後の Task で地図の 2 行を住処ありにし、柵（入口の種の語は `blk-entry` の中だけ）を足す
2. `stop-reasons`: 止めの理由の表を core に 1 つ（語・結末・説明）にし、26 の `.py` の `STOP_BY` 定数はそこを引く。機械的で小さい
3. `carry-over`: `next-request.json` の欄の名を書き手（`report`）と読み手（`ghreads`）が 1 つのモジュールから引く。約束の schema は在る
4. `marks`: 「役の型にだけ欄を足し、盤面へ渡す前に外して置く」の手順を 1 つの助け手にし、`gatemarks`・`planmarks`・`deltamarks`・`converge.with_fields` が呼ぶ
5. `human-gates`: 無人の時に変える振る舞いと最後の関所の方針を 1 つの方針の口に。語 `unattended` の 2 つの意味を分ける
6. `prompt-assembly`: 「頭の節 → `---` → 写しの本文 → 役の定義 → 前の拒否」の並べを `rolekit` の 1 つの口にする
7. `ai-launch`: 模型・effort・道具・隔離の表を 1 つにし、YAML の値はそこから確かめる（今の `test_tool_parity` を表の側へ）
8. `lanes`: `adapter.KEYED_NODES` を `lanekit.MAX_LANES` から導く。`blk-eyes` の `LANES` を別の名（筋）にする
9. `ledger`: 費用と時間の読み口を 1 つに
10. `core-seams`: `CORE_OVERRIDES` を自分のモジュールへ移し、`CORE_OVERRIDES` と `COPIED_FROM` の `!` 行の使い分けを書く

## 6. Task

順と大きさ: Task 1（中）→ Task 2（小）→ Task 3（小〜中）→ Task 4（小）→ Task 5（測り。run 4 本）→ Task 6（小。CLAUDE.md は承認の後）→ Task 7（10 版ごと）。Task 1 は今すぐ入れられる（試験と表と文書だけで、束が触るファイルに触らない）。Task 3・4 は束の出荷の後。Task 2 は Task 3 の直前でよい。

### Task 1: 柵の表と道具（地図との同期を含む）

**Files:**
- Create: `works/docs/concepts.json`
- Create: `works/tests/conceptfence.py`
- Create: `works/tests/test_concept_fences.py`
- Modify: `works/tests/tiers.py`（FAST に `"test_concept_fences"`。理由の注記は「git ls-files と追跡されたファイルを読むだけ」）

**Interfaces:**
- Produces: `conceptfence.load(root: Path) -> dict`（表）・`conceptfence.tracked(root: Path) -> list[str]`（`git ls-files -z --cached --others --exclude-standard` の works からのパス）・`conceptfence.scan(root: Path, paths: list[str], fence: dict, exclude: list[str]) -> dict[str, int]`（`allowed` と `exclude` の外のファイルで `pattern` に当たる行の数。0 のファイルは入れない。読めないファイル・バイナリは飛ばす）・`conceptfence.verdict(found: dict[str, int], known: dict[str, list]) -> list[str]`（`blockblind.verdict` に `{k: tuple(v)}` で渡す）・`conceptfence.map_ids(md: str) -> dict[str, str]`（見出し `### \`<id>\`` と、その下の最初の `- 状態: ` の行の最初の語）・`conceptfence.map_paths(md: str) -> list[str]`（行のうち「予定」も「枝 `」も含まない行の、`` ` `` で囲まれ `.shared/`・`blk-`・`darkfactory/`・`dev/`・`tests/`・`skills/` で始まる語。末尾の `/` は落とす。`*` を含む語は glob で照らす）

- [ ] **Step 1: 落ちる試験を書く**（`tests/test_concept_fences.py`。木を読む試験と、一時のフォルダの試験。一時のフォルダは git を使わず、`scan` にパスの一覧を渡す）

```python
class MapAndTable(unittest.TestCase):
    def test_ids_and_status_agree(self):
        self.assertEqual(cf.map_ids(MD), {k: v["status"] for k, v in TABLE["concepts"].items()})
    def test_homed_concepts_have_fence(self):
        for k, v in TABLE["concepts"].items():
            if v["status"] == "住処あり":
                self.assertTrue(v["fences"], k)
    def test_map_paths_exist(self):
        missing = [p for p in cf.map_paths(MD) if not (glob.glob(str(ROOT / p)) if "*" in p else (ROOT / p).exists())]
        self.assertEqual(missing, [])
    def test_known_rows_have_reason(self):
        for k, v in TABLE["concepts"].items():
            for f in v["fences"]:
                for path, (n, why) in f["known"].items():
                    self.assertGreater(n, 0, (k, path)); self.assertTrue(why.strip(), (k, path))

class FencesHold(unittest.TestCase):
    def test_every_fence(self):
        paths = cf.tracked(ROOT)
        for k, v in TABLE["concepts"].items():
            for f in v["fences"]:
                found = cf.scan(ROOT, paths, f, TABLE["exclude"])
                self.assertEqual(cf.verdict(found, f["known"]), [], f"{k}: {f['what']}")

class Synthetic(unittest.TestCase):   # 一時のフォルダに a.py（語 2 行）・home.py（語 1 行）・tests/t.py（語 1 行）
    def test_counts_only_outside_allowed_and_exclude(self):
        self.assertEqual(cf.scan(tmp, ["a.py", "home.py", "tests/t.py"], FENCE, ["tests/**"]), {"a.py": 2})
    def test_ratchet(self):
        self.assertEqual(cf.verdict({"a.py": 2}, {"a.py": [2, "理由"]}), [])
        self.assertTrue(cf.verdict({"a.py": 1}, {"a.py": [2, "理由"]}))   # 減ったのに表が残る
        self.assertTrue(cf.verdict({"a.py": 2, "b.py": 1}, {"a.py": [2, "理由"]}))   # 表に無い漏れ
```

- [ ] **Step 2: 走らせて落ちることを見る**
  Run: `cd works && python3 -m unittest tests.test_concept_fences -v`
  Expected: FAIL（`conceptfence` が無い）

- [ ] **Step 3: `tests/conceptfence.py` と `docs/concepts.json` を書く。** 表は 3.1 節の 11 の柵と、散らばりの 11 の考え（`fences: []`）。`known` は空で置く
- [ ] **Step 4: 柵を走らせ、出た漏れを 1 件ずつ読む。** 理由を 1 文で書ける物だけ `known` に置き、書けない物は 3.2 節の決まり 1 でその考えを散らばりに戻す（地図の状態の行と「今」の行を直し、表の `fences` を空に）。`features` は 3.1 節の件数と揃うこと
- [ ] **Step 5: 走らせて通ることを見る**
  Run: `cd works && python3 -m unittest tests.test_concept_fences -v && python3 tests/tiers.py list fast | grep -c test_concept_fences`
  Expected: OK と `1`
- [ ] **Step 6: 地図の「この地図の育て方」の最後の行の「（予定。同じ計画の Task 1）」と、`docs/concepts.json` の「予定」を外す**
- [ ] **Step 7: Commit**（`test(works): 考えの住処の柵の表と道具を足し、地図と表の食い違い・住処の外の漏れを赤にする`）

### Task 2: 観点の住処 `concepthome`

**Files:**
- Create: `works/.shared/core/concepthome.py`
- Modify: `works/tests/test_layers.py`（`MOD` に `"concepthome": (3, None)` と注記「考えの住処の観点の文と地図の探し方（blk-plan・blk-eyes が使う）」）
- Create: `works/tests/test_concepthome.py`
- Modify: `works/tests/tiers.py`（FAST に `"test_concepthome"`。注記「文字列と名前の一覧だけ（git・子のプロセスなし）」）

**Interfaces:**
- Produces: 定数 `MAP_NAME = "docs/concepts.md"`・`PREFIX = "考えの住処: "`・`MAX_MAPS = 5`・`PLAN_RULE`・`REVIEW_ASK`・`R1_HEAD`・`R3_HEAD`（2.1 節の字のまま。`R1_HEAD`・`R3_HEAD` は `{section}` を 1 つ持つ）。関数 `pick_maps(names: list[str]) -> tuple[list[str], int]`（名が `MAP_NAME` か `"/" + MAP_NAME` で終わる物を、`/` の数の少ない順・同じなら名の順に並べ、先頭 `MAX_MAPS` 件と全件の数）・`tree_names(repo: Path, rev: str) -> tuple[list[str], str]`（`git -C repo ls-tree -r --name-only <rev>` の行と、落ちた時の理由。投げない）・`section(repo: Path, rev: str) -> str`（2.1 節の地図の節）

- [ ] **Step 1: 落ちる試験を書く**

```python
def test_pick_root_and_nested(self):
    self.assertEqual(ch.pick_maps(["docs/x.md", "works/docs/concepts.md", "docs/concepts.md", "a/docs/concepts.md.bak"]),
                     (["docs/concepts.md", "works/docs/concepts.md"], 2))
def test_pick_caps(self):
    names = [f"p{i}/docs/concepts.md" for i in range(7)]
    self.assertEqual(ch.pick_maps(names), (names[:5], 7))
def test_section_without_map(self):   # tree_names を差し替えて [] を返す
    s = ch.section(pathlib.Path("/x"), "HEAD")
    self.assertIn("無い", s); self.assertIn(ch.MAP_NAME, s)
def test_section_lists_maps_and_rest(self):   # 7 件を返す差し替え
    self.assertIn("ほか 2 件", ch.section(pathlib.Path("/x"), "HEAD"))
def test_texts_carry_prefix_and_slot(self):
    for t in (ch.PLAN_RULE, ch.REVIEW_ASK, ch.R1_HEAD, ch.R3_HEAD):
        self.assertIn(ch.PREFIX.strip(), t)
    for t in (ch.R1_HEAD, ch.R3_HEAD):
        self.assertEqual(t.count("{section}"), 1)
```

- [ ] **Step 2: 走らせて落ちることを見る**（`cd works && python3 -m unittest tests.test_concepthome -v` → import の誤り）
- [ ] **Step 3: `concepthome.py` を書く。** 頭の docstring は他の core のモジュールと同じ形（何を持つか・口の一覧）。標準ライブラリだけ
- [ ] **Step 4: 走らせて通ることを見る**（同じコマンドと `python3 -m unittest tests.test_layers -v` が OK）
- [ ] **Step 5: Commit**（`feat(works): 考えの住処の観点の文と地図の探し方を core の concepthome に置く`）

### Task 3: 修正案と事前審査に観点を貼る

**Files:**
- Modify: `works/blk-plan/lib/planblk.py`（`HEAD["plan"]`・`HEAD["plan-review"]` の末尾・`brief_head` の `HANDOFF_REVIEW` の後・`head` の引数・`prep` の 2 つの道）
- Test: `works/tests/test_blk_plan.py`

**Interfaces:**
- Consumes: Task 2 の `concepthome.PLAN_RULE`・`REVIEW_ASK`・`section(repo, rev)`
- Produces: `planblk.head(role: str, excluded_file: str = "", lib_docs: str = "", design_part: str = "", concept_part: str = "") -> str`（`concept_part` は `lib_docs` の後に置く）

- [ ] **Step 1: 落ちる試験を書く**（`test_blk_plan.py` の今の盤面の作り方に従う）
  - `test_plan_head_has_concept_rule`: `concepthome.PLAN_RULE in planblk.HEAD["plan"]`
  - `test_review_head_and_brief_have_ask`: `REVIEW_ASK` が `HEAD["plan-review"]` と、木の道の `brief_head(b, main)` の返りの両方に在る
  - `test_prep_prompt_has_map_section`: 種のリポジトリに `docs/concepts.md` を commit してから `prep` を走らせ、指示書のファイルに `docs/concepts.md` の行と節の見出しが在る。置かない種では「無い」の文が在る
  - `test_replan_prep_has_map_section`: 同じ run の中の案の直しの道の指示書にも地図の節が在る
- [ ] **Step 2: 走らせて落ちることを見る**（`cd works && python3 -m unittest tests.test_blk_plan -v`）
- [ ] **Step 3: 貼る。** `prep` は `concepthome.section(pathlib.Path(b.state["inputs"]["cwd"]), b.state["inputs"]["review_rev"])` を `head(..., concept_part=…)` に渡す。`brief_head` は `REVIEW_ASK` を足し、地図の節は同じ関数で作る
- [ ] **Step 4: 走らせて通ることを見る**（同じコマンドと `python3 -m unittest tests.test_layers tests.test_block_blind -v`）
- [ ] **Step 5: Commit**（`feat(works): 修正案と事前審査に、考えの住処を使うか・知る所を増やすかを問わせる（穴は kind copy、why の頭は「考えの住処: 」）`）

### Task 4: R1・R3 に観点を貼る

**Files:**
- Modify: `works/blk-eyes/lib/eyes.py`（定数 `CONCEPT_HEADS = {"r1.minimality": concepthome.R1_HEAD, "r3.coherence": concepthome.R3_HEAD}` と `prep` の頭の節）
- Test: `works/tests/test_blk_eyes.py`

**Interfaces:**
- Consumes: Task 2 の `concepthome.R1_HEAD`・`R3_HEAD`・`section(repo, rev)`

- [ ] **Step 1: 落ちる試験を書く**
  - `test_r1_prompt_has_concept_head`: R1 の指示書が `## 最小の意味` で始まり、`---` の後に写しの本文が続く
  - `test_r3_prompt_has_concept_head`: R3 の指示書が `## 考えの住処` で始まる
  - `test_other_eyes_unchanged`: `r2.compare`・`r4.hidden_scope`・`r1.comment_candidates` の頭は今のまま（R2 に地図の語が無い）
  - 今の `FrozenReadCase` が緑のまま
- [ ] **Step 2: 走らせて落ちることを見る**（`cd works && python3 -m unittest tests.test_blk_eyes -v`）
- [ ] **Step 3: 貼る。** `prep` の `elif nid == R4_NODE …` の並びに `elif nid in CONCEPT_HEADS:` を足し、`CONCEPT_HEADS[nid].format(section=concepthome.section(pathlib.Path(repo), b.state["inputs"]["review_rev"]))` を `---` で前に置く
- [ ] **Step 4: 走らせて通ることを見る**（同じコマンド）
- [ ] **Step 5: Commit**（`feat(works): R1 の最小を「考えを知る所が増えない」に読み替え、R1・R3 に考えの住処を確かめさせる`）

### Task 5: 測り（雑音と費用）

**Files:** なし（測りの結果をこの文書の 8 節の台帳に足す）

- [ ] **Step 1: 前の版の基準を引く。** Task 4 の前の版で回した canary の run（`dev/canary.sh` の依頼 `canary-request.json` と `canary-request-large.json`）の報告と費用を `dev/canary_check.py` の出力から控える
- [ ] **Step 2: Task 4 の後の版で同じ 2 本を回す**（works を対象にした run 1 本と、地図の無い種 `dev/canary-seed` の run 1 本ずつ。計 4 本で比べる）
- [ ] **Step 3: 数える。** 報告と盤面から「考えの住処: 」で始まる穴・目の理由・`increments` の行を数え、1 件ずつ「住処のパスと行が在るか」「人が読んで直す価値があるか」を書く
- [ ] **Step 4: 決める。** 次のどれかに当たれば文（`concepthome` の定数）を直して Step 2 から回し直す: 地図の無い種で、住処を名指さない指摘が 1 件でも `redesign-needed` か block になった・直す価値の無い指摘が半分を超えた・run の費用が基準より 10% を超えて増えた
- [ ] **Step 5: 台帳に残して commit**（`docs(works): 考えの住処の観点の測り（雑音と費用）を台帳に残す`）

### Task 6: 開発の流れ

**Files:**
- Create: `works/docs/plans/README.md`（4.1 節の型）
- Modify: `works/docs/concepts.md`（「この地図の育て方」に 4.3 節の手順）
- Modify: `CLAUDE.md`（4.2 節の 4 行と出荷の 1 行。**持ち主の承認の後**）

- [ ] **Step 1: `docs/plans/README.md` を書く。** 型の節の並びと、考えの棚卸しの書き方の例 1 つ（この計画の 7 節を例に引く）
- [ ] **Step 2: 地図に監査の手順を足す**
- [ ] **Step 3: 持ち主に CLAUDE.md の 5 行を見せて承認を得る。** 得たら足す。得られなければこの Step だけ残して commit する
- [ ] **Step 4: 確かめる。** `cd works && python3 -m unittest tests.test_concept_fences -v`（地図のパスが在る）が緑で、`docs/plans/README.md` から地図と計画への相対リンクが開ける
- [ ] **Step 5: Commit**（`docs(works): 計画の型に考えの棚卸しを足し、構造の監査の手順を地図に置く`。CLAUDE.md は別の commit）

### Task 7: 構造の監査（10 版ごと）

**Files:** `works/docs/concepts.md`・`works/docs/concepts.json`

- [ ] **Step 1:** 0.2.60 を出す前に、4.3 節の手順 1〜3 を回す
- [ ] **Step 2:** `cd works && python3 -m unittest tests.test_concept_fences -v` が緑
- [ ] **Step 3: Commit**（`docs(works): 構造の監査（0.2.60 の前）で考えの住処の地図を今の姿に直す`）

## 7. 考えの棚卸し（この計画自身）

| id | 今の住処 | 計画の後 | 知る所 |
| --- | --- | --- | --- |
| 考えの住処の観点（新） | 無い | `concepthome` | +1（新しい考え） |
| `marks` | 散らばり | 散らばり | 0（欄を足さない） |
| `prompt-assembly` | 散らばり | 散らばり | +2（`planblk`・`eyes` が頭を組む。今の組み方に乗るだけで、並べの口は 5 節の 6 で 1 つにする） |

## 8. 測りの台帳

（Task 5 が埋める）

## 9. 危うさ

1. **対象のリポジトリで目がうるさくなる**（壊れる余地）。地図の無いリポジトリで、役が住処を推して指摘を量産し、R1・R3 の `redesign-needed` が結末を `round_limit` に下げる。防ぎ: 住処のパスと行を名指せない物は block・`redesign-needed` にしない（決め事 5）、住処の無い考えは suggest・`increments` に留める（決め事 4）、Task 5 で地図の無い種を測り、当たれば文を直す
2. **費用**（壊れる余地）。足すのは 4 つの役の頭の数段落と地図を読む分。works の地図は約 12 KB で、事前審査を木で回すと項目ごとの下請けがそれぞれ地図を読むので、項目の数だけ掛かる。防ぎ: 下請けは自分の項目が触る考えの行だけを読めばよいと文が言う（地図の行は id の見出しで引ける）、Task 5 の 10% の線
3. **柵の誤検知**（壊れる余地）。正規表現は同名の別の語に当たる（`record_invalid` は報告の役の欄の名で結末の語ではない。`judge_verify` は trace の語でもある）。防ぎ: 語の形を引用符・語の境で狭める、当たった物は理由つきで既知に置く（決め事 7、3.2 節の 2）
4. **帳簿の手間**（壊れる余地）。既知の件数はファイルごとの行の数なので、同じファイルに語を 1 つ足すだけで赤になる。それは柵の狙いどおりだが、直す人が理由も読まずに件数だけ上げると柵が死ぬ。防ぎ: 件数を上げる差分は事前審査と R1 が「考えの住処: 」で見る（この計画の (a) が (b) を見張る）
5. **地図が古くなる**（壊れる余地）。防ぎ: 地図と表の id・状態の同期とパスの在りかを試験が見る（Task 1）、出荷の前の手順（Task 6）、10 版ごとの監査（Task 7）
6. **写しの本文と頭の節がぶつかる**（壊れる余地）。R1 の本文は「累積差分が最小か」を行と記述の量でも語る。防ぎ: 頭が読み替えを名指す（決め事 2）。本流が文を変えたら写し直しの時に頭を読み直す
7. **並行の 5 束とのぶつかり**（今は無い。入れる時に起きうる）。Task 3・4 は束が触るファイルを直す。防ぎ: 束の出荷の後に入れる（状態の行）

## 見落としやすい所（試験が見ていない入力）

1. 対象のリポジトリが `docs/concepts.md` を持つが、中身が works の地図の形でない（ただの用語集）: 役は地図を「読む物」として読むだけなので、形を問わず読んで使えばよい。`section` は名だけで探し、形を確かめない（Task 2 の試験はパスの一覧だけを見る）
2. 読む版の木に地図が 6 つ以上ある大きな monorepo: 5 件と「ほか N 件」に切る（Task 2 の `test_pick_caps`）。役が自分の審査するファイルのフォルダの地図を選べること（節の 1 行の決まり）
3. `review_rev` が無い盤面（入口が古い run の resume）: `tree_names` が落ちても役を止めず「木を読めなかった」と書く（Task 2 の Step 3。`section` は投げない）
4. 地図が commit されておらず作業ツリーにだけ在る: 読む版の木で探すので見つからない（版で読む目と揃える）。works の開発では地図を commit してから run を回す
5. 柵の試験で、まだ追跡されていない新しいファイル: `tracked` は `--others --exclude-standard` も拾う（足したファイルを commit の前から数える。`blockblind.tracked` と同じ）
