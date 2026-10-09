<!-- coldwrite:skip 内部の作業計画。語は 2 節と計画 docs/plans/2026-10-09-clean-whole.md・docs/concepts.md で定義 -->
# 設計を決める前に、世の中の解き方を必ず当たる段（世界の解の段の計画）

## 平たく言うと（3 行）

- 何の話か: works（修正の依頼を受けて直しを出す AI の工場）が、依頼に書かれた解き方をそのまま前提にして、世の中で決まった解き方（定石）を調べずに設計してしまう穴の直し方。2026-10-09 の run では 64 分・約 24 USD を使って誤った設計を固め、持ち主が 1 行で正した。
- 分かったこと: 役は世の中を調べてはいたが、「依頼が示した仕組みの部品」を調べ、「この種の作業を世の中はどうやっているか」を調べなかった。依頼の解き方が目的の文にまで写り、全部の役がその枠の中で考えた。調べは任意の助言で、確かめる機械も、定石に従ったかを問う受け付けも無い。
- 決めたこと: 判定の前に 1 つのブロック `blk-world` を必ず通す。依頼を「解き方と対象の名を外した問題の類」に言い直し、定石を出どころと原文つきで集めて機械が照らし、依頼の解き方と比べて違えば名指して定石を推す。修正案は定石に従うか外れの訳を書き、外れは人の関所に上がる。持ち主に聞くことは無い（11 節）。

状態: 計画だけ（コードは変えていない）。2026-10-09、版 0.2.56（枝 `wip/integ-0256` の 09df8cfe）の事実で書いた。並行の枝 `wip/phase2-loop`（計画 `docs/plans/2026-10-09-clean-whole.md` の段 2）が入った後に入る（6 節）。

> **実装する者へ:** superpowers:subagent-driven-development で Task ごとに opus の実装役と審査役で回す。手順は `- [ ]` で追う。入る前に `wip/phase2-loop` が `wip/integ-*` に合わさったかを確かめ、6 節の「つなぎ目」の名を今の版で照らし直す。

**目的:** 設計の決め（判定の処方・構造の目の避け方・修正案の作り・独立設計・事前審査・関所）がどれも、世の中の定石を見てから、従うか訳つきで外れるかの形でしか進まないようにする。

**作り:** 新しいブロック `blk-world` を、目的の役の後・判定の前に 1 回だけ差し込む。中は「問題の類に言い直す役（opus）→ 集める役（軽い模型）→ 抜き書きの機械の照らし → 判断する役（opus）」。出力の行（`world.jsonl`）の読み口は core の 1 つのモジュール `.shared/core/worldmark.py` に置き、判定・構造の目・修正案・事前審査・関所・報告はそこから読む。従う／外れの答えは、段 2 で入った修正案の欄 `structure` に種を 1 つ足して使い回す。

**道具:** Python 3.12（標準ライブラリだけ）・unittest・git・Archon v0.11.1 の YAML。

**仕様:** この文書の 4 節・5 節と、構造の目の設計書 `docs/specs/2026-09-29-structure-block-design.md` の 5 節（先例の調べ）。

## 1. 何が起きたか（run 167e14c3）

- 依頼: TDD の輪の「赤」の判定を言語に依らない形にする。依頼の本文は解き方まで書いていた（読むだけの役を足し、生のログから「準備の失敗か機能が無いか」を引用つきで判じさせる。出どころは計画 `docs/plans/2026-10-09-lang-neutral-red.md` の手順 3。この手順は運び役が書いた案で、持ち主が決めたのは「言語に依らない方がいい」という目的だけ）
- 目的の役（`blk-purpose`）: 目的の文 `purpose_text` に、依頼の解き方をそのまま写した。出典は「計画・タスク記述」
- 判定役（`blk-judge`）: 先例の行 `precedents` を書き、ある TDD の手順書の「error なら直して、正しく落ちるまで回し直せ」まで引いていた。しかし問題の名 `problem` を「テストの結末の出力で failure と error の分け方が実行器ごとに違う」と、依頼の示した仕組みの部品の言葉で立て、結論を adapt（手を入れて採る）にして依頼の案を残した。処方の決め手は、依頼と案の計画の文を「人の前の決定」として引いた
- 構造の目（`blk-structure`）: 世の中を見ずに、案の中での責務の置き場だけを判じた（避け方 `chosen` は「赤の判定を 1 つの関数に」）
- 修正案と事前審査（`blk-plan`）: 読み役の別名・引用の結び・読みの hash の持ち越しを設計し、3 往復しても block が 3 つ残った（`missing-red-killed-by-others`・`gate-read-hash-broken-by-later-unit`・`read-carry-over-check-is-vacuous`）
- 人に回した問い 2 件（コンパイルの単位ごと落ちる時の「名指しの外は元のまま」の読み方と、実行器ごとの出方の実地の確かめ）は、どちらも誤った設計から生まれた問い
- 持ち主の答え（修正前の関所で stop）: 「設計を世界の解（コンパイル・読み込みの失敗は赤に数えず、最小の仮の実装で走らせてから期待違いの失敗を赤とする TDD の定石）に直した依頼で回し直すため」。持ち主の言葉: 「かなりの穴じゃない？」「私が聞いたら1発なのはなんで」「今の私の解法をエッセンスとしていれないといけないのでは」

盤面: `/Users/p03623/.local/state/works/use-ed6883c1/archon-home/workspaces/raiki61/claude-plugins/artifacts/runs/167e14c3-7ba7-46c0-b79b-58af6a10ebdf/board`（`purpose.json`・`judgment.json` の `precedents`・`../structure/design.jsonl`・`planning/precedent-checks.json`・`report.md`）。

## 2. 語

- 定石（世界の解）: ある種類の問題を、世の中の実務家が決まってどう解いているか。実践・慣習・標準の形で言える物。道具の出力の形や、依頼が示した仕組みの部品の話ではない
- 問題の類: 依頼の 1 行を、依頼が示した解き方と対象の名（パス・関数・環境変数・ブロックの名）を外して、実務家がする作業の言葉で言い直した 1 文。例の形: 「テストを先に書く開発で、まだ無い機能を呼ぶテストを、コンパイルの要る対象でどう赤にするか」
- 依頼の解き方: 依頼が「こう直せ」と示した手段。目的とは別の物で、工場が定石と比べて疑う対象
- 世界の解の行: `blk-world` が出す 1 行（問題の類ごと）。欄は 5.2 節
- 上に上がって世界に聞く: この計画で名を付ける works の原則（4 節）
- そのほかの語（run・盤面・役・関所・ブロック・線・構造の目・事前審査・R1〜R4・独立設計 r2.design・考えの住処・柵）は計画 `docs/plans/2026-10-09-clean-whole.md` の 2 節のとおり

## 3. なぜ大きな穴か

- 誤った設計の費用が一番高い所で出る: 判定・構造の目・修正案・事前審査の 4 段が同じ誤った前提の上で磨き合うので、往復を重ねるほど誤りが固くなる。今回は 64 分・約 24 USD を使い、関所で人が止めるまで誰も前提を疑わなかった
- 人の手間が増える: 誤った設計から生まれた問いが人に回る（今回 2 件）。持ち主の決め「人に上げるのは、考えても決まらない時だけ」に反する
- 直しが残れば、再発明と保守の負債になる: 定石なら小さな仮の実装 1 つで済む所に、読み役・引用の照らし・hash の持ち越しという新しい仕組みが入るところだった
- 世の中を見ずに決めている所（今の版）:
  1. 目的の役 `blk-purpose`: 依頼の解き方を目的の文に写す。以後の全部の役がそれを目的として読む
  2. 判定の処方 `prescriptions`（`blk-judge/commands/diagnose.md` の 7 項）: 決め手 4 つの順が「人の前の決定 → 方針 → 対象の同じ場面 → 世界の解」で、依頼や案の計画の文が「前の決定」として先に勝つ。世界の解は 4 番目で、web を引くかは役に任される
  3. 判定の先例の行 `precedents`（同 8 項）: 問題の名の立て方の決まりが無い。adapt の結論は、何を変えて採ったかを機械が見ない
  4. 構造の目の避け方 `chosen`（`blk-structure/lib/eye.py`）: 実測と単位の要約だけを見る。先例の調べ（設計書 5 節）は作られていない
  5. 修正案の作り `approach`（`blk-plan`）: 頭に構造の目の行と判定の処方が貼られるが、定石は貼られない
  6. 独立設計 `r2.design`: 目的の文だけから設計する。目的の文に依頼の解き方が入っていたので、独立にならなかった
  7. 事前審査 `p2.plan_review`: 案を依頼と行に照らすが、定石には照らさない
  8. 関所の欄 `world`（`.shared/core/gatemarks.py` の `FIELDS` と `_RULE`）: 人に回す行に役が書く 1 文。空でも通り、「web を引くかは任せる」

## 4. 根の原因と、持ち主の解き方の本質

### 4.1 根の原因

1. 世界の調べが任意の助言で、2 か所（判定役の指示書の 7・8 項と、関所の決め手の文 `gatemarks._RULE`）にしか無い。引いた抜き書きが本文に在るかも、結論が依頼の案を残したかも、機械が見ない
2. 問題と解き方を分ける所が無い。目的の役が解き方を目的に写し、判定役は依頼の解き方を「人の前の決定」として最上位の決め手に使えた
3. 設計した先例の調べの節（構造の目の設計書 5 節・10 節の S4）が作られず、計画 clean-whole でも段 6 の 6.8 に置かれたまま
4. 設計が定石を引いたかを確かめる所が無い。修正案の受け付け・構造の目・関所のどれも「定石に従ったか、外れの訳は何か」を問わない

### 4.2 持ち主が 1 行で解けた訳（本質）

1. 仕組みの中に留まらず、1 段上の「作業の種類」に上がった（「コンパイルの要る言語で TDD を世の中はどうやるか」）
2. 依頼に埋め込まれた解き方を受け入れなかった。役たちの「世界の調べ」は、依頼の案の部品（テストの結末の出力の形）に向いていた

この 2 つを、この順で工程にする。これがこの段の芯で、ほかの部品（照らし・控え・関所）はこれを外せなくするための物。

- (a) 言い直す: 各単位を、依頼の解き方と対象の名を外した問題の類・作業の言葉に言い直す
- (b) 世界に聞く: 世の中の実務家がその類をどう解くか（実践・慣習・標準。道具の出力の形ではない）を問う
- (c) 前提を疑う: 依頼の解き方と今の設計を定石と比べ、違えば「依頼は X、定石は Y。…でない限り Y を選ぶ」と名指す

### 4.3 works の原則にする（`step-up` 上に上がって世界に聞く）

- 観点の地図 `docs/owner-decisions.md` に観点 `step-up` を足す（持ち主の言葉は 1 節の 10-09 の 3 つ。強さは W9 の後に「機械で強制」）。既存の `world`・`web-split`・`doubt-always` の住処と隙間の「→ 段 6」を、この計画の段 2W に直す
- keep-essence（`docs/keep-essence.md`）に 12 を足す。文は次のとおり（言語・道具の名を書かない）:

  > 12. 世界の解に照らす: 設計を決める前に、依頼の各行を、依頼が示した解き方と対象の名を外した問題の類に言い直し、世の中がその類をどう解いているか（実践・慣習・標準）を出どころと原文の抜き書きつきで集め、抜き書きが出どころに在ることを機械が確かめる。依頼の解き方か設計が定石と違えば、違いを名指して定石を推す。修正案は定石ごとに従うか外れの訳を書き、欠けは受け付けが拒む。依頼そのものを出どころにした外れは人の関所に上がる。

  一覧の頭の「11 の仕組み」の数も 12 に直す。この文は振る舞いと同じ commit で入れる（W9。文だけ先に入れると文書が動きと食い違う）
- 依頼の書き方の教え（`skills/works/SKILL.md` の 1 節「依頼の JSON を書く」に 1 項）: 「`text` には問題と目的を書き、解き方は書かない。解き方の案を添えるなら『案（工場が定石と比べて疑う）』と書く。工場は案を目的と分け、定石と違えば定石を推す」。依頼の型に欄は足さない（入口は 1 つの入力の形のまま。分けるのは目的の役の仕事で、5.3 節の 1）

## 5. 設計

### 5.1 置き場と流れ

```
依頼 → 前提の実測 → 目的の役（目的と依頼の解き方 means を分ける）
     → 世界の解の段 blk-world（1 回だけ）
         言い直す役（opus・対象を読まない）→ 控えを引く（機械）
         → 集める役（軽い模型・web だけ）→ 照らす（機械）→ 判断する役（opus）
     → 判定（行を材料に・先例は行を引く）→ 構造の目（単位の要約に行の要点）
     → 修正案（行ごとに従う／外れの訳）・独立設計・事前審査（外れの訳を照らす）
     → 修正前の関所（依頼を出どころにした外れは人へ）→ …… → 報告（世界の解の節）
```

- 差し込む所: 線 `darkfactory/darkfactory.yaml` の `purposing` の後・`gathering` の前に include 1 行（節 `worlding`）と、出口を控えに写す境の節 `h-world` 1 つ（`structure-state.json` を書く境の節と同じ型）
- 判定の前に置く訳: 最初の設計の決めは判定の処方で、ここより後に置くと判定が依頼の解き方の枠で単位・問い・処方を作ってしまう（今回の 2 件の問いがそれ）。判定の前には単位が無いので、類は依頼の行（findings の 1 行）ごとに立てる。類は作業の種類の言葉なので、単位より上の粒度で足りる
- ブロックの入力の契約（形で述べ、他のブロックを名指さない）: 依頼のファイル・目的の文のファイル（解き方 means の欄つき。任意）・run をまたぐ控えの置き場（任意）。出力は 2 本だけ: 行のファイル `world.jsonl` と控えの 1 行（status・reason・wall_s・数）

### 5.2 ブロック blk-world の中

1. 言い直す役 `world-classes`（opus。段の組 `plan_writer`。道具は Read だけで、読んでよいのは依頼と目的の文のファイルだけ。対象の木は読まない＝上に上がるため、独立設計の隔てと同じ型）
   - 依頼の行ごとに 1 つ: `finding`（行の番号）・`class_id`（控えの類を使うならその id、新しい類なら空）・`problem`（問題の類の 1 文）・`activity`（作業の種類の名）・`proposed`（依頼の解き方。目的の文の means から写す。無ければ空）・`queries`（3 本まで）・`wording`（語の直しだけの行なら真）
   - 指示書の芯は 4.2 節の (a)・(b): 「依頼の示した仕組みの部品や出力の形を問うな。実務家がこの作業をどうするかを問え」
   - 受け付け（機械。`blk-world/scripts/classes_accept.py`）: 依頼の全部の行に 1 つずつ在る。`problem`・`queries` に対象の識別子が無い（構造の目の設計書 5 節の検索語の検査を使い回す: 依頼の where のパスの成分・字の中の英数の識別子とバッククォートの字・大文字とアンダースコアの名・`blk-` の名・run の id）。`wording` が真の行は、その行の where が全部文書のファイルの時だけ通す（5.4 節）。外れは同じ会話で出し直させる（上限 3。今の役の輪と同じ）
2. 控えを引く（機械）: `class_id` の在る類と、`problem` が控えの類と字で一致する類は、run をまたぐ控え（5.4 節）から定石の部分を読み、集める役と照らしを飛ばす
3. 集める役 `world-collect`（段の組 `light`＝軽い模型。道具は web の検索と取得だけ。対象の木を読まない）: 控えに無い類ごとに `queries` で引き、`{class, url, excerpt}` の並びだけを返す。要約も評価もしない（持ち主「WEBからとってきてまとめるところは」sonnet でよい・判断は opus）
4. 照らす（機械。`blk-world/lib/worldcheck.py`）
   - URL ごとに、集める役が本当に取得したかを Archon の出来事（`reads.web_fetches`。W2）で確かめる
   - 抜き書きは、機械が同じ URL を自分で取り直した本文（`webget.http_get`。W1）を正規化した中に、正規化した字のまま在るかで照らす。役の取得の道具は本文を要約して返すので、役が見た字は原文の記録にならない。そのため照らしは機械の取り直しで行う
   - 外れた抜き書きは落とし、落とした数と訳を残す。網に出られない・全部の取り直しが落ちた時は 5.5 節
5. 判断する役 `world-judge`（opus。段の組 `plan_writer`。道具は Read だけで、照らした抜き書きのファイルと、言い直す役の出力を読む。web は持たない）: 類ごとに 1 行を返す
   - `practice`: 定石（1〜3 文。対象の名を書かない）
   - `sources`: 使った抜き書きの id の並び
   - `applies`: この依頼にどう当たるか。`not_applies`: どこには当たらないか
   - `versus`: `{proposed, verdict: same|differs|none, challenge}`。`differs` なら `challenge` に「依頼は X、定石は Y。…でない限り Y を選ぶ」の形の文（4.2 節の (c)）
   - `basis`: `web`（照らした抜き書きが 1 つ以上）か `knowledge`（抜き書きが残らなかった）
   - 受け付け（機械。`blk-world/scripts/judge_accept.py`）: `sources` の id が照らしで残った物だけ。`basis: web` は `sources` が 1 つ以上。`verdict: differs` は `challenge` が 20 字以上。`practice` に対象の識別子が無い
6. 書く（機械。`blk-world/scripts/collect.py`）: 行を `world.jsonl` に書き、定石の部分（`problem`・`activity`・`practice`・`sources` と抜き書き・`basis`・時刻）を控えに足す。`applies`・`versus` は依頼ごとの物なので控えない

### 5.3 使う側（どれも worldmark から読む）

1. 目的の役 `blk-purpose`: 目的の文に解き方を書かず、依頼の解き方は足し欄 `means`（`.shared/core/marks.py` の `KINDS` に種を 1 つ足す。写しの型は変えない）に分ける。指示書 `blk-purpose/commands/purpose.md` の頭に 1 項。独立設計（r2.design）には目的の文だけが渡り、`means` は渡らない（keep-essence の 9「依頼の目的だけから別の役が設計」を、解き方の混ざらない目的で守る）。独立設計に世界の解の行は渡さない（訳: 独立設計の値は修正案と独立なことで、同じ行を見ると同じ誤りに揃う。目的から解き方が抜ければ、独立設計は自分で定石に届ける）
2. 判定役 `blk-judge`: 入力に行のファイル（任意）を足し、支度の script が `worldmark.section` を指示書の頭に貼る。指示書 `diagnose.md` の 7 項（d）と 8 項を「世界の解の行を先に使え。先例の行の出どころは `world:<類の id>` で引け。行の無い問いだけ自分で引け」に直す。7 項（a）の「人の前の決定」に「依頼と目的の文が示した解き方は、人の前の決定に数えない（工場が疑う案）」を足す
3. 構造の目 `blk-structure`: 入力の契約は 3 つのまま。線の側の写しの節 `darkfactory/lib/line_edge.py` の `structure_units` が、単位の where のパスと類の依頼の行の where が重なる行の要点（`worldmark.unit_note`）を単位の要約 summary の尾に足す。目の指示書に「避け方 chosen は定石の作りに沿わせ、沿わないならその訳を chosen_reason に書け」を足す（構造の目の設計書 5 節の先例の調べは、ここで置き換える。5.6 節）
4. 修正案 `blk-plan`: 頭に `worldmark.section` を貼る（`blk-plan/lib/planblk.py` の頭の組み立てに 1 行）。修正案の欄 `structure`（段 2 の Task 2.4。`.shared/core/planmarks.py`）に種 `world` を足す: `{world: <類の id>, follows: true}` か `{world: <類の id>, deviation: <訳>}`。受け付けは 2 つを拒む: 類の依頼の行の where と項目のパスが重なるのに答えが無い項目と、`applies` が空でない行にどの項目も答えていない案。足し方は `structure_gaps` を「答えの要る行の表」を受ける形に広げて使い回し、`world` の行の表は `worldmark.required` が作る（2 つ目の答えの仕組みを作らない）
5. 事前審査: 外れの訳の並び（`planmarks.deviations` と `DEVIATION_HEAD`）に `world` の外れも並べ、その行の `challenge` を添える
6. 関所（段 2 の Task 2.6 の後）: 世界の解の外れは修正前の関所の項目になる（`gatemarks.plan_gate_items`。`KIND_WORDS` に「世界の解」）。4 つの軸の「世界の解か」は、役が書く `world` の文でなく `worldmark.world_ok` で機械が決める: 答えの要る行が無い・従う・外れの `decided_by` の出どころが現物に在り、しかも依頼のファイルと目的の文の出典（`purpose.json` の `source_files`）のどれでもない、のどれかなら真。依頼を出どころにした外れは人に回る（今回の形はここで止まる）。関所の項目の `world` の欄は worldmark が行から埋める。`gatemarks._RULE` の「web を引くかは任せる」の文は「世界の解の行を使え」に直す
7. 報告（`.shared/core/report.py`）: 節「世界の解」に `worldmark.report_lines`（類ごとの定石・依頼との比べ・basis・控えから使った類・飛ばした行・落とした抜き書きの数・増えた時間）

### 5.4 費用の抑え

- 1 回だけ: 判定の前の 1 か所。構造の目のための 2 回目は置かない（5.6 節）
- run をまたぐ控え: 定石の部分を問題の類ごとに、利用の家の下の置き場に持つ（`libdocs` の run をまたぐ控えと同じ形。W1 で core の `webget` に寄せた物を使う）。期限は 90 日（構造の実測の窓と同じ）。類は対象の名を持たないので、対象のリポジトリをまたいで使ってよい。言い直す役には控えの類の一覧（id と 1 文）を渡し、同じ類なら id で選ばせる。控えに当たった類は集める役と照らしを飛ばす
- 飛ばす行: 語の直しだけの行（`wording` が真）で、where が全部文書のファイル（`.shared/core/impact.py` の文書の見分け。今は内向きの `_lang` なので、`impact.is_doc(path)` を口として出す）の時だけ。AI の申告と機械の確かめの両方が要る（持ち主「AI の選択に任せず常に回す」）。依頼が渡した「機械の深さ」（`darkfactory/lib/depth.py`）は修正案の欄から決まるので、判定の前のこの段には間に合わない。深さの決まりの代わりに同じ種類の機械の確かめ（触るファイルの種類）を使う。全部の行が飛ぶ run は、言い直す役 1 回だけで終わる
- 上限: 類は 5 つ・検索語は類ごとに 3 本・抜き書きは類ごとに 6 つ（越えた分は頭から取り、取らなかった数を控えに残す）
- 目安（W11 で測って決め直す）: 控えに当たらない run で 5 分・2 USD まで。控えに当たる run で 1 分まで。飛ぶ run で 10 秒まで

### 5.5 web が使えない時

- 網に出られない run（集める役が何も返さない・機械の取り直しが全部落ちる）でも段は止めない。判断する役は抜き書き無しで、模型の知識だけから行を書き、`basis: knowledge` にする（持ち主「モデルの集合知でわかる場合もある」）
- `basis: knowledge` の行は、報告・修正案の頭・関所の項目に「web で確かめていない」と名指して並べる。従う／外れの答えと関所の決まりは `web` の行と同じに掛ける（知識だけの定石に従うのは自明側、外れは人へ）
- `basis: knowledge` の行は控えに足さない（確かめていない定石を次の run に持ち越さない）

### 5.6 構造の目の先例の調べとの合流

- 構造の目の設計書 5 節は「汚れると見た時だけ、集める役 → 抜き書きの照合 → 判断する役」を blk-structure の中に置く設計だった。同じ 3 段の仕組みを 2 か所に作らない。仕組みは `blk-world` 1 つにし、構造の目はその行を単位の要約で受ける（5.3 節の 3）
- 2 回目の差し込み（構造の目が汚れると見た単位だけ、構造の形の問いで blk-world をもう 1 回回す）は今は作らない。W11 の測りで、定石の行が構造の形を語らずに目が決めきれなかった単位（目の行き先が「人に上げる」で訳が定石の欠け）が出た時に決める
- 設計書 5 節の検索語の検査（対象から取った識別子を含む問いを捨てる）と抜き書きの照合（読んだ記録を広げる）は、そのまま blk-world の照らしになる（W2・W3）
- 設計書 10 節の S4 と、計画 clean-whole の段 6 の 6.8 は、この計画で置き換える（8 節）

### 5.7 考えの住処（`docs/concepts.md` に足す行の案）

- id: `world`。考え: 世界の解（問題の類ごとの定石と、依頼の解き方との比べ）。状態: 住処あり（W4 で入る。それまでは地図に「予定」と書く）
- 住処: `.shared/core/worldmark.py`（行の欄の名・ファイルの名 `WORLD_FILE`・控えの名 `STATE_FILE`・`VERDICTS`・`BASES`・読み口 `rows`・`read`・頭の節 `section`・単位の要点 `unit_note`・答えの要る行 `required`・関所の軸 `world_ok`・関所の行 `gate_line`・報告 `report_lines`）
- 約束: `blk-world/world-row.schema.json`
- 知ってよい所: 住処・約束・ブロック `blk-world/` の中・線 `darkfactory/`（境の節 `h-world` と `structure_units`）
- 柵の語の形（`docs/concepts.json`）: 行のファイルの名 `world.jsonl` と控えの名 `world-state.json`。知ってよい所の外で現れたら赤
- web の取得と run をまたぐ控え（`.shared/core/webget.py`）: `libdocs` と `blk-world` の 2 か所が使う（W1 で寄せる）。W1 を入れた時に、網の素の口が住処の外に出ない柵を持つ行 `web-get` として地図に足した（部品だが、柵で寄せた形を守れるため）

### 5.8 捨てた案

- blk-structure の中に先例の調べを作る（設計書 5 節の形）: 構造の目は判定の後なので、判定の処方と問いが依頼の枠のまま作られる。調べの仕組みも 2 つに割れる
- 判定役の指示書の文を強めるだけ: 今もある 7・8 項が働かなかった。問題の類の立て方・依頼の案との比べ・抜き書きの実在を機械が見ない限り、同じ形で外れる
- 判定の後に置く: 単位ごとに類を立てられるが、判定の問いと処方が依頼の解き方で作られた後になる（今回の 2 件の誤った問いを防げない）
- 依頼の型に解き方の欄 `suggestion` を足す: 人が本文に解き方を書くのは止まらないので、分けるのは結局目的の役になる。欄を足すと入口の形が増える（観点「入口は 1 つの入力の形」）。教えは SKILL.md に書く
- 独立設計にも世界の解の行を渡す: 5.3 節の 1 の訳
- 外れを全部人に回す: 持ち主「鵜呑みにせず最適を考えて」。依頼の外の出どころ（人の前の決定の原文など）で訳が立つ外れは、4 つの軸のとおりグラフの中で決める

## 6. Task（順と依存）

```
wip/phase2-loop が合わさる（段 2 の Task 2.2〜2.4。2.6 は W9 の前）
  └─ W1 web の取得と控えを core へ ─┐
     W2 読んだ記録に web の取得 ───┼─ W3 照らし ─ W4 worldmark ─ W5 blk-world ─ W6 目的の分け ─ W7 線へ ─ W8 使う側 ─┐
                                    │                                                                                    ├─ W9 関所と keep-essence 12 ─ W10 報告と文書 ─ W11 測り
     段 2 の Task 2.6（gatemarks.decided の出どころの確かめ）──────────────────────────────────────────────────────────┘
```

- W1・W2 は今すぐ並べてよい（段 2 と触るファイルが分かれる）。W4 以降は `wip/phase2-loop` が合わさった後
- 段 4（入口ブロック）は `blk-plan/lib/planblk.py` を触るので、W8 の後に置く（8 節の 1）
- 版の目安: W1〜W5 で 1 版、W6〜W9 で 1 版、W10・W11 で 1 版

### 段 2 とのつなぎ目（入る時に今の版で名を照らし直す）

- `planmarks.structure_gaps`・`STRUCTURE_HEAD`・`deviations`・`DEVIATION_HEAD`（Task 2.4。W8 が種 `world` を足す）
- `structmark.plan_section` と `planblk` の頭の組み立て（Task 2.4。W8 が並べて `worldmark.section` を貼る）
- `blk-structure/lib/eye.py` の行き先 `route` と目の指示書（Task 2.3。W8 が chosen の決まりを 1 項足す）
- `gatemarks.decided` と出どころの実在の確かめ（Task 2.6。W9 が世界の解の軸を足す。`conflict.cite_problem` を使い回す）
- `concepthome.EYE_ASK`・`PLAN_RULE`（Task 2.1。世界の解の文は足さない。軸の文は今のまま）

### W1: web の取得と run をまたぐ控えを core へ寄せる（振る舞いは変えない）

**Files:** Create `works/.shared/core/webget.py`・`works/tests/test_webget.py`。Modify `works/.shared/core/libdocs.py`（`FetchError`・`SafeRedirect`・`http_get`・`shared_dir`・`_shared_get`・`_shared_put`・`_fresh` を webget から引く）・`works/tests/test_layers.py`・`works/tests/tiers.py`（速い段）

**Interfaces（Produces）:**
- `FetchError`・`SafeRedirect`・`http_get(url: str, headers: dict, max_body: int) -> tuple[int, bytes]`（転送は `libdocs_web.safe_url` の決まりを webget に移した `safe_url`）
- `Store(root: pathlib.Path | None, schema: str, ttl: float)`、`Store.get(name: str, now: float, statuses: tuple) -> dict | None`・`Store.put(name: str, doc: dict) -> str`（書けなければ理由の 1 行）、`shared_root(env: dict, sub: str) -> pathlib.Path | None`

- [ ] 赤: `test_store_put_then_get_within_ttl`・`test_store_get_expired_is_none`・`test_store_put_unwritable_returns_reason`・`test_redirect_to_unsafe_host_is_not_followed`。`tests/test_libdocs.py` は緑のまま
- [ ] 入れる・緑・commit（`refactor(works): web の取得と run をまたぐ控えを core の webget に寄せる（世界の解の段と文書の取得が同じ口を使うため）`）

### W2: 読んだ記録に web の取得を足す

**Files:** Modify `works/.shared/core/reads.py`。Create `works/tests/events/db-rows-web.json`（run 167e14c3 の判定役の web の取得の行を archon.db から写した見本。出来事の形を実物で確かめた印を `reads.py` の頭に書く。`EVENTS_VERIFIED` と同じ扱い）。Test `works/tests/test_reads.py`

**Interfaces（Produces）:** `web_fetches(events, node_path: str) -> list[str]`（節が取得した URL の並び。`tool_inputs` を使う）・`web_searches(events, node_path: str) -> list[str]`（検索の問い）

- [ ] 赤: `test_web_fetches_from_real_rows`・`test_web_searches_from_real_rows`・`test_no_events_returns_empty`
- [ ] 入れる・緑・commit（`feat(works): 読んだ記録の口に、節が取得した URL と検索の問いを出来事から引く口を足す`）

### W3: 抜き書きの照らしと検索語の検査

**Files:** Create `works/blk-world/lib/worldcheck.py`・`works/tests/test_world_check.py`

**Interfaces（Produces）:**
- `banned_tokens(findings: list[dict]) -> set[str]`（where のパスの成分・字の中の英数の識別子とバッククォートの字・大文字とアンダースコアの名・`blk-` の名・run の id）
- `text_problems(text: str, banned: set[str]) -> list[str]`（問題の類・検索語・定石の文に当たる識別子）
- `normalize(body: bytes | str) -> str`（HTML の札を外し、NFKC・空白の詰め・大小を揃える）
- `verify(excerpts: list[dict], fetched: set[str], get) -> dict`（`{kept: [...], dropped: [{url, why}], offline: bool}`。抜き書きは 20 字以上。役が取得していない URL・取り直せない URL・本文に無い抜き書きは落とす。全部の取り直しが網に届かなければ `offline` を真）

- [x] 赤: `test_excerpt_found_in_body_is_kept`・`test_paraphrase_is_dropped`・`test_url_not_fetched_by_role_is_dropped`・`test_query_with_target_identifier_is_refused`・`test_all_fetch_errors_mark_offline`
- [x] 入れる・緑・commit（`feat(works): 世界の解の抜き書きを機械が取り直した本文で照らし、対象の名の入った問いを拒む`）
- 入れた形（2026-10-10）: 識別子と見るのは識別子の形の語（_ . / - か数字を含む・小文字の後に大文字。3 字以上）・パスの最後の段・バッククォートの字。普通の語（作業の名・略語・フォルダの名）は数えない。残った抜き書きの id は `x<n>`

### W4: 世界の解の行の住処 worldmark

**Files:** Create `works/.shared/core/worldmark.py`・`works/blk-world/world-row.schema.json`・`works/tests/test_worldmark.py`。Modify `works/tests/test_layers.py`

**Interfaces（Produces）:**
- 定数 `WORLD_FILE = "world.jsonl"`・`STATE_FILE = "world-state.json"`・`VERDICTS = ("same", "differs", "none")`・`BASES = ("web", "knowledge")`・`NOT_WEB = "web で確かめていない"`
- `rows(path) -> list[dict]`（読めない・形が違えば ValueError）・`read(board_dir) -> dict | None`（控え）
- `section(world_file: str) -> str`（判定・修正案・事前審査の頭に貼る節。行が無ければ ""）
- `unit_note(rows: list, paths: list[str]) -> str`（単位のパスと類の where が重なる行の要点）
- `required(rows: list, item: dict) -> list[str]`（項目が答える要る類の id）・`unanswered(rows: list, items: list) -> list[str]`（どの項目も答えていない `applies` の在る類）
- `world_ok(answer: dict | None, row: dict, own_sources: set[str], cite_ok) -> tuple[bool, str]`（5.3 節の 6 の決まり）
- `gate_line(row: dict, answer: dict) -> str`・`report_lines(board_dir) -> list[str]`

- [x] 赤: `test_section_marks_knowledge_rows`・`test_unit_note_only_overlapping_rows`・`test_required_by_path_overlap`・`test_unanswered_applies_row`・`test_world_ok_follow`・`test_world_ok_deviation_cited_to_request_is_false`・`test_world_ok_deviation_cited_elsewhere_is_true`
- [x] 入れる・緑・commit（`feat(works): 世界の解の行の住処 worldmark を core に置く`）
- 入れた形（2026-10-10）: `required(rows, item, inside)`・`unanswered(rows, items)`。項目の範囲の当て方 `inside` は呼び手が `planrange.inside` を渡す（worldmark が planrange を import すると planrange → conflict → gatemarks の鎖で、W9 の gatemarks → worldmark と輪になる）。答えの要る行は `applies` が空でない行（`needs`）。場所の字のパスの口 `where_paths` を足した。行に `where`（依頼の行の字のまま）と `cached` を持つ。控えは段の時間を持たない（考え `ledger` の散らばりを増やさない。時間は流れの道具の出来事から作る）

### W5: ブロック blk-world

**Files:** Create `works/blk-world/blk-world.yaml`・`manifest.json`・`commands/world-classes.md`・`commands/world-collect.md`・`commands/world-judge.md`・`scripts/intake.py`・`scripts/classes_accept.py`・`scripts/cache.py`・`scripts/verify.py`・`scripts/judge_accept.py`・`scripts/collect.py`・`fixtures/{pass,offline,cache-hit,wording}.stubs.yaml`・`works/tests/test_blk_world.py`。Modify `works/.shared/core/stage-models.json`（`blk-world/world-classes`・`blk-world/world-judge` は `plan_writer`、`blk-world/world-collect` は `light`）・`works/.shared/core/impact.py`（`is_doc(path) -> bool` を出す）・`works/tests/tiers.py`

**Interfaces:**
- Consumes: W1 の `Store`・`http_get`、W2 の `web_fetches`、W3 の全部、W4 の `WORLD_FILE`・`STATE_FILE`・行の型
- Produces: ブロックの入力 `request`・`purpose_file`（任意）・`cache_root`（任意）と出口 `world_file`・`state`（`{status, reason, wall_s, classes, cached, skipped, dropped}`）

- [x] 赤: `test_inputs_described_by_shape`（他のブロックの名を書かない。`tests/blockblind.py` の柵）・`test_every_finding_needs_a_class`・`test_wording_needs_doc_only_where`・`test_cache_hit_skips_collect`・`test_differs_needs_challenge`・`test_knowledge_rows_not_cached`と、4 つの筋書きの模擬実行。指示書 3 本に言語・道具の名が無いことは、計画 clean-whole の Task 3.8 の柵（考え `lang-names`）が見る所に `blk-world/commands` を入れて縛る（柵がまだ無ければ Task 3.8 と一緒に入れる。試験の中に別の語の表を持たない）
- [x] 入れる・緑（模擬実行は CI）・commit（`feat(works): 世界の解のブロック blk-world（問題の類に言い直し、定石を集めて照らし、依頼の解き方と比べる）`）
- 入れた形（2026-10-10）: 言い直す役と判断する役は道具ゼロ・旗 isolated の blind-judge（独立設計と同じ隔て。模型と effort は前付けの opus・high）で、依頼の行・目的の文・控えの類・抜き書きは支度の節（`classes_prep`・`judge_prep`）が貼る。表 stage-models には集める役 `blk-world/world-collect`（light）だけを足した。中身は `blk-world/lib/worldblk.py`。入力に web の切り替え `web`（on・off）を足した。出口は平の欄 {ok, world_file, status, reason, classes, cached, skipped, dropped}（段の時間は持たない）。core に `webget.Store.names`・`reads.top_here`・`impact.is_doc` を足した。柵 `lang-names`（計画 clean-whole の Task 3.8）を同じ commit で入れた。言い直す役と判断する役の effort は計画の plan_writer（medium）でなく blind-judge の high（持ち主 2026-10-10: 道具ゼロの役を新しい表の行で作らず既にある役を使い、費用は W11 で測って決め直す）。AI の段を持つ YAML が 1 本増えて考え `ai-launch` の数の歯止めが main を越えたので、柵の結んだ写し（`conceptfence` の bound。`tests/test_tool_parity.py` が縛る model:・effort: の全部と、本線の定義とちょうど同じ道具だけのファイルの allowed_tools:）を数えない形にした（230 行・37 ファイル → 107 行・32 ファイル）

### W6: 目的の役が依頼の解き方を分ける

**Files:** Modify `works/blk-purpose/commands/purpose.md`（頭に 1 項）・`works/.shared/core/marks.py`（`KINDS` に `p0.purpose` の種 `means`）・`works/blk-purpose/scripts/accept.py`（足し欄を外して控える）・独立設計に貼る節の並び（`works/.shared/core/design.py` の `premises`。`means` を貼らないことを縛るだけで、中身は変えない）。Test `works/tests/test_blk_purpose.py`・`works/tests/test_blk_plan.py`（`design.premises` の今の試験の置き場）

**Interfaces（Produces）:** 盤面の控え（`marks.path_of` の置き場）に `means: [str]`。目的の文の型は写しのまま

- [ ] 赤: `test_purpose_means_split_to_mark`・`test_independent_design_input_has_no_means`・`test_purpose_without_means_passes`
- [ ] 入れる・緑・commit（`feat(works): 目的の役が依頼の示した解き方を目的の文から分けて足し欄 means に置く`）

### W7: 線へ差し込む

**Files:** Modify `works/darkfactory/darkfactory.yaml`（節 `worlding`・境の節 `h-world`）・`works/darkfactory/lib/line_edge.py`（控えを盤面の根に写す・`structure_units` が `worldmark.unit_note` を要約の尾に足す）・`works/.shared/core/entry.py`（`FEATURES` に `world`。測りの比べのため。既定は on）・`works/darkfactory/darkfactory.graph.json`（地図の作り直し）。Test `works/tests/test_line_wiring.py`・`works/tests/test_edge.py`・`works/tests/test_line_inputs.py`

- [ ] 赤: `test_world_block_between_purpose_and_judge`・`test_feature_world_off_skips_block_and_reports_it`・`test_structure_unit_summary_carries_world_note`・`test_world_output_has_readers`（段 1 の Task 1.5 の読み手の柵に当たる）
- [ ] 入れる・緑（線の模擬実行は CI）・commit（`feat(works): 世界の解の段を目的の後・判定の前に差し込む`）

### W8: 使う側（判定・構造の目・修正案・事前審査）

**Files:** Modify `works/blk-judge/commands/diagnose.md`（7 項の (a)・(d)、8 項）・判定の支度の script（`worldmark.section` を貼る）・`works/blk-judge/blk-judge.yaml`（入力 `world_file`）・`works/blk-structure/commands/structure-eye.md`（chosen の 1 項）・`works/.shared/core/planmarks.py`（種 `world`・`structure_gaps` を答えの要る行の表を受ける形に）・`works/blk-plan/lib/planblk.py`（頭に `worldmark.section`）・`works/.shared/core/gatemarks.py`（`_RULE` の文だけ）。Test `works/tests/test_blk_judge.py`・`works/tests/test_structure_eye.py`・`works/tests/test_plan_fields.py`・`works/tests/test_blk_plan.py`

- [ ] 赤: `test_judge_head_has_world_rows`・`test_proposed_means_not_counted_as_prior_decision`（指示書の文の在りか）・`test_plan_item_overlapping_world_row_needs_answer`・`test_plan_unanswered_world_row_refused`・`test_world_deviation_listed_for_review`・`test_structure_gaps_shared_by_world_and_structure`
- [ ] 入れる・緑・commit（`feat(works): 判定・構造の目・修正案・事前審査が世界の解の行を読み、修正案は行ごとに従うか外れの訳を書く`）

### W9: 関所の世界の解の軸と keep-essence の 12（段 2 の Task 2.6 の後）

**Files:** Modify `works/.shared/core/gatemarks.py`（`plan_gate_items` に世界の解の外れ・`KIND_WORDS`・`decided` に `worldmark.world_ok`）・`works/docs/keep-essence.md`（12 と数）。Test `works/tests/test_plan_gate.py`・`works/tests/test_gate_drafts.py`

- [ ] 赤: `test_world_deviation_becomes_gate_item`・`test_deviation_cited_to_request_goes_to_human`・`test_following_world_row_passes_without_asking`・`test_unattended_world_deviation_stops_with_draft`・`test_knowledge_row_named_in_gate_item`
- [ ] 入れる・緑・commit（`feat(works): 依頼を出どころにした世界の解の外れを修正前の関所に上げ、keep-essence に 12 を足す`）

### W10: 報告と文書

**Files:** Modify `works/.shared/core/report.py`（節「世界の解」）・`works/docs/concepts.md`・`works/docs/concepts.json`（5.7 節の行と柵）・`works/docs/owner-decisions.md`（`step-up` と 3 行の住処・強さ・隙間）・`works/skills/works/SKILL.md`（4.3 節の教え）・`works/docs/specs/2026-09-29-structure-block-design.md`（状態の行に「5 節と S4 は計画 world-solution が置き換えた」の 1 行）・`works/README.md`（段の並び）。Test `works/tests/test_report.py`・`works/tests/test_concept_fences.py`

- [ ] 赤: `test_report_has_world_section`・柵の表の `world` の行が在る・観点の地図の名指すパスが在る（計画 clean-whole の Task 3.7 が入っていればその試験）
- [ ] 入れる・緑・commit（`docs(works): 世界の解の段を報告・考えの地図・観点の地図・依頼の書き方に入れる`）

### W11: 測り

1. 版を固め（W10 の後の版）、run 167e14c3 と同じ依頼のファイル（`/Users/p03623/.local/state/works/use-ed6883c1/requests/20261009-190709-87136.json`。依頼の解き方が入ったまま）で、`features_off world` の run と既定の run を 2 本ずつ起こす（run 167e14c3 は前の版の「無し」の 1 本として並べる）。どれも修正前の関所で止めて測る（設計の決めは関所の前で済む）
2. 比べる物: 世界の解の行の `practice` が「コンパイル・読み込みの失敗は赤に数えず、最小の仮の実装で走らせてから期待違いの失敗を赤とする」形に当たるか（人が読んで判じる）・`versus` が `differs` で読み役の案を名指すか・修正案が定石に従うか、外れが関所の項目に上がるか・事前審査の block の数と往復・人に回した問いの数・関所までの時間と費用・世界の解の段だけの時間と費用
3. 雑音の見張り（各 1 本）: 依頼の解き方が定石と同じ依頼（関所の項目が増えないこと）・文書の語の直しだけの依頼（段が言い直す役 1 回で終わり、10 秒程度）・網を閉じた run（`basis: knowledge` と名指しが出ること）
4. 決める: 定石に当たらない・目安（5.4 節）を越える・雑音で関所の項目が増える、のどれかなら言い直す役の指示書か上限を直して回し直す。構造の目が定石の欠けで決めきれなかった単位が出たら、5.6 節の 2 回目の差し込みを決める
5. この文書の末尾に台帳として残す

run は前景で待たず、`run_in_background` で起こして知らせを受ける（運び役の決まり）。

## 7. 見落としやすい所（試験が直に打たないが、使う人が踏みやすい物）

1. 依頼の 1 行が 2 つの作業の種類にまたがる: 言い直す役は 1 行に 1 つの類しか返せないので、上の種類で 1 つに言い直す。2 つ要るなら依頼を分ける（測りで件数を数える）
2. 判定が依頼の where を別の行へ向け直す（今回も 265 行から呼び出し 2 か所へ向け直した）: 項目と類の重なりはパス（ファイル）で見るので、同じファイルなら外れない。別のファイルへ向け直した時は「どの項目も答えていない行」の拒みで拾う（W8 の 2 本目の試験）
3. 控えの類が古い定石を持つ: 期限 90 日で切れる。期限の内でも、判断する役が `not_applies` に「この依頼の版では当たらない」を書けば、従う答えは要らない
4. 対象のリポジトリが網に出られない環境（社内の閉じた網など）: 5.5 節のとおり知識だけの行で進み、毎回名指しが出る。止まらない
5. 依頼の解き方が人の前の決定の原文そのもの（観点の地図の持ち主の言葉など）: その原文を `decided_by` に引いた外れは、依頼と目的の文の出典でなければグラフの中で通る。目的の文の出典にその原文が入っていれば人に回る（安全側）

## 8. 既存の計画への変更

### 計画 clean-whole（`docs/plans/2026-10-09-clean-whole.md`）

この計画では、その文書の状態の行の下に 1 行の追記（この計画を指す）だけを足す。本文は次に書き直す時に、次の 9 点に合わせる。

1. 段 6 の 6.8（web の調べを割る）を前へ出し、この計画の段 2W（W1〜W11）にする。置き場は段 2 の後・段 4 の前（段 4 と W8 が同じ `blk-plan/lib/planblk.py` を触るため）。5 節の図と版の目安も直す
2. 1 節の決め 1 の「世界の解か」の軸: 「world に定石の出どころが在る」を、`worldmark.world_ok`（従う・依頼の外の出どころで訳の立つ外れ・答えの要る行が無い）に置き換える（W9）
3. 1 節の決め 2 の「決まった形」: 「準備の失敗か機能が無いかは読むだけの役が生のログから引用つきで判じ」は依頼の解き方で、持ち主が run 167e14c3 の関所で止めた。持ち主の答えの定石（コンパイル・読み込みの失敗は赤に数えず、最小の仮の実装で走らせてから期待違いの失敗を赤とする）に書き直す。段 1 の言語中立の直しは、この計画を待たずに直した依頼で入れる
4. 2 節の語に「世界の解の段」「問題の類」を足す
5. 3.2 節の 1 歩の輪の図に、判定の前の「世界の解（言い直す → 集める → 照らす → 比べる）」を足す
6. 6 節の「今やる」に「上に上がって世界に聞く（`step-up`）」を足し、観点の地図の `world`・`web-split`・`doubt-always` の隙間の「→ 段 6」を「→ 段 2W」にする
7. 7 節に構造の目の設計書の行を足す: 5 節（先例の調べ）と 10 節の S4 を blk-world が置き換える。目の 2 回目の差し込みは W11 の測りで決める
8. 8 節の棚卸しに 2 行: 世界の解（新。住処 `worldmark`。知る場所 +1）・web の取得と控え（`libdocs` の中から core の `webget` へ。0）
9. Task 2.8 の測りに W11 を並べる（同じ版で回せば run の数を減らせる）

### ほかの文書

- 計画 `docs/plans/2026-10-09-lang-neutral-red.md` の手順 3: 定石の形に書き直す（言語中立の直しを入れる枝が行う）
- 構造の目の設計書: 状態の行に置き換えの 1 行（W10）

## 9. 危うさ

1. **言い直しが浅い**（壊れる余地）: 言い直す役がまた仕組みの部品の言葉で類を立てると、今回と同じ形で外れる。機械が見られるのは対象の識別子だけで、「作業の言葉か」は見られない。防ぎ: 指示書の芯を 4.2 節の (a)・(b) の 1 つに絞り、対象を読ませない。W11 で今回の依頼に当てて確かめ、外れたら指示書を直す
2. **関所がうるさくなる**（壊れる余地）: 定石と違う案が多い対象では外れが増え、無人の run が止まりやすくなる。これは狙いどおり（前提を疑う所で人が要る）だが、W11 の雑音の見張りで「同じ解き方の依頼で項目が増えない」ことを確かめる
3. **費用**（壊れる余地）: 役が 3 つ増える。控えと飛ばす行と上限で抑え、W11 の目安で見張る。今回の誤った設計の費用（64 分・約 24 USD）より十分小さいことを測りで示す
4. **網の取り直しの失敗で抜き書きが落ちすぎる**（壊れる余地）: 取り直しを拒むサイト・中身を後から描くページでは、正しい抜き書きも落ちる。落ちた数と訳は控えと報告に出る。全部落ちれば知識だけの行として名指しで進む（止まらない）
5. **並行の枝とのぶつかり**（今は無い。入れる時に起きうる）: `wip/phase2-loop` が `planmarks`・`structmark`・`planblk`・`blk-structure` を、段 2 の Task 2.6 が `gatemarks.decided` を触る。6 節の順（W4 以降は合わさった後、W9 は 2.6 の後）で避ける

## 10. 考えの棚卸し（この計画自身）

| 考え | 今の住処 | 計画の後 | 知る場所 |
| --- | --- | --- | --- |
| 世界の解（新） | 判定の指示書と関所の文 | `worldmark` | +1 |
| web の取得と控え | `libdocs` | core の `webget` | 0 |
| 依頼の解き方（新） | 無い | 目的の足し欄 `means` | +1（足し欄 `marks` の種） |
| 従う／外れの答え | 修正案の欄 `structure` | 同じ欄に種 `world` | 0 |
| 先例の調べ | 設計書だけ | `blk-world` | 0 |

## 11. まだ決めていないこと

- 持ち主に聞くことは無い。迷いそうな所は前の決定で 1 つに決まった
  - 判定の前に置くか・後に置くか: 持ち主の 10-09 の解き方（依頼の解き方を受け入れる前に上へ上がる）で前
  - 外れを全部人へ回すか: 決め 1 の 4 つの軸の組み合わせ（依頼の外の出どころの立つ外れはグラフの中）
  - 独立設計に行を渡すか: keep-essence の 9（目的だけから設計）で渡さない
  - web が無い時に止めるか: 持ち主「web は Option」「モデルの集合知でわかる場合もある」で止めない
  - 集める役の模型: 持ち主「WEBからとってきてまとめるところは」sonnet でよい・判断は opus
- 測りで決める物（W11）: 構造の目のための 2 回目の差し込み・上限の値・費用の目安
