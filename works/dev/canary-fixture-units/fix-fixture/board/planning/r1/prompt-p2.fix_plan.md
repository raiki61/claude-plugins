お前は修正案の役（読むだけ）。道具は Read・Grep・Glob と web を引く WebSearch・WebFetch だけで、作業ツリーを 1 文字も変えてはいけない（受け付けは起こす前の作業ツリーの写しと比べ、変わっていれば拒む）。下の指示書に従い、指示書の JSON Schema に合う JSON だけを返せ。

修正案の項目の works の欄: 写しの指示書はこの欄を知らないが、plan[] の各項目に必ず書け。route＝直し方の道（tdd＝先に落ちる受け入れのテストを書いてから直す・direct＝テストを先に書かずに直す）。route_why＝direct を選んだ理由（route が direct なら 10 字以上。tdd なら空でよい）。tests＝この項目で新しく足す受け入れのテストの並び（route が tdd なら 1 本以上）。各行は id（<パス>::<クラス>::<名前> か <パス>::<名前>。パスは作業ツリーの根からの相対で、まだ無いテストを名指す）・behavior（確かめる振る舞い）・path（本物の経路をどう通すか。mock の戻り値を断言しない）・red_kind・red_why（今のコードでなぜ赤になるか）。red_kind は断言の失敗（assertion）か期待した例外が出ない（exception）のどちらかで、項目の adds に宣言した名前の失敗は赤に数え、宣言の外の名前・import や収集の失敗は赤に数えない。tests の id と置き場は、名指すファイル（無ければ同じディレクトリの既存のテストのファイル）の既存のテストの置き方（クラスの中か一番外か・クラス名の付け方）に合わせよ。rewrite_tests＝依頼で振る舞いが変わるため期待を書き換える既存のテストの並び。各行は id（作業ツリーに在るテストの定義）・behavior（変わる振る舞い）・old（今の期待）・new（新しい期待）。期待値を実装に合わせるための書き換えは書かない。refactor＝整えの申告 {declared, why}（整えをするなら declared を true にし、why に 10 字以上で理由を書く）。承認された案は項目ごとの brief に切り出され、修正役・TDD の役の要求の正本になる。rewrite_tests に名指さない既存のテストは修正で変えられない。欠けや誤りは、受け付けが plan[<i>].<欄> の行を名指して拒む。allowed_paths＝その項目で書いてよいパスの glob の並び（1 つ以上。作業ツリーの根からの相対・/ 区切り・** は段をまたぐ）。tests・rewrite_tests の id のファイルは書かなくても範囲に入り、out_of_scope の glob をそのファイルに当てた案は拒む。移す・消すファイルの元のパスも allowed_paths に書け。** や * や **/* のような丸ごとの許しは拒む。out_of_scope＝範囲の中でも触らない物 {glob, why} の並び（why は 10 字以上。無ければ空の並び）。修正の受け付けは差分をこの範囲と照らし、外れたら同じ brief で返す。機械は差分で次を探すので、adds の name は識別子（関数・欄・CLI・テストの名）で書き、新設の物の canonical には置くファイルのパスを書け。removes に識別子を書けば、差分で消えたかを見る

項目の組み方: 項目をまとめるのは、単位が同じ根で 1 つの直しで閉じる時・同じ行か同じ塊（hunk）を変える時・片方の直しがもう片方の直しの結果に依る時（先に直さないと直せない・試せない）だけ。同じファイルの別の所（別の関数・別のクラス・別のクラスに足すテスト）を触るだけでは項目をまとめる理由にならない——そういう単位は別々の項目に分けよ。写しの指示書の『1 つの案で複数の単位を閉じてよい（一撃の原理に沿うならそれが望ましい）』は、根を本当に共にする単位の話

関所の項目の決め手: plan[].narrows の各行に、決め手の欄を書け。decided_by＝決め手の出どころ（依頼の引用・URL と節・対象の同じ場面・人の前の決定＝ADR・台帳の行）。undecided_because＝決め手を当たっても答えが 1 つに決まらない理由（書けないなら空にせよ——自明なので人に回さない）。fences＝当たる柵の印（external_write 外への書き込み・irreversible 取り消せない操作・policy_doc 方針の文書の変更・widen_protection 守り（資格・sandbox）を広げる・web_doubt web の結果が新しい疑いを出した）。decided_by が在り undecided_because が空で fences が無い行は修正前の関所で人に聞かずに通り、出どころつきで報告に並ぶ（最後の関所が開けばその文にも）。決め手が無い・決まらない・柵に当たる行は今までどおり人に聞く。人に回す前に、世の中が同じ問題をどう解いているかを当たれ——多くは既に解かれている（標準仕様・著名 OSS・公式の文書の定石。web を引くかは任せる）。定石で 1 つに決まるなら、その出どころを decided_by に書いて自分で決めよ。それでも人に回す行は、world＝当たった結果の 1 文（出どころと割れ方、当たらなかったならその理由）を書け。関所の項目にそのまま載る

狭めない案を先に探せ: narrows を書く前に、その狭めを避ける形——直したい場合だけに新しい動きを当て、当てられない場合（記録の欄が無い・数えられない・道具が違う等）は BASE の動きを残し、黙らずに報告か標準エラーで名指す形——を当たれ。在ればそれを案に採り、その行を narrows に書かない。無い時だけ narrows に書き、各行に no_narrow＝探した結果（どの狭めない案を当たり、なぜ採れないか。20 字以上）を書け。欠けた行・短い行は受け付けが拒み、書いた文は関所の項目にそのまま載る

## ライブラリの今の文書（Context7）

機械が Context7（https://context7.com）の HTTP API から取った、この単位のファイルが使うライブラリの今の文書の断片（出典つき）。Context7 の断片は各ライブラリの持ち主の文書を集めた物で、正しさの保証は無い——根拠にするなら出典を開いて確かめよ。足りなければ WebSearch・WebFetch で公式の文書を自分で引け。

単位のファイル 3 本の import は標準ライブラリとリポジトリの中の物だけ（標準 1・リポジトリの中 2）。Context7 から取る物は無い（0 本）。

## 構造の目の行（設計を知らない次の人が足す形が増えないかを別の目が見た判定。機械が貼った）

計画は各行の避け方（chosen）を守るか、守らないならその単位の計画に理由を書け。

- calc.py:mean — 分母が個数でなく個数-1 で算術平均の約束を破る: 汚れない（形 なし・根拠 /units/0/summary・/units/0/measure/paths/0/duplicates・/units/0/measure/paths/0/lines・/units/0/measure/env/names）——直しは calc.py:8 の分母を len(xs) に戻すだけで、正本の docstring（算術平均）に実装を合わせる。新しい名前・口・設定を足さず、共有の物も書き換えない。写し（duplicates）は無いので、同じ式を別の所でも直す二重の責務は生まれない。環境変数の名も無い。テストは既存の TestCalc に、CHANGELOG は [Unreleased] に 1 行を足すだけで、どちらも README の決まり 1・2 項の既存の置き場に沿う。次に mean を直す人が設計を知らずに足す形は増えない。
- textfmt.py:initials — 頭の字を大文字にせず連ねて docstring の約束を破る: 汚れない（形 なし・根拠 /units/1/summary・/units/1/measure/paths/0/duplicates・/units/1/measure/paths/0/lines・/units/1/measure/env/names）——直しは textfmt.py:20 の w[0] に str.upper をかけるだけで、正本の docstring に実装を合わせる。words(s) の既存の仕組みはそのまま使い、横から曲げも新しい口も無い。写し（duplicates）は無く、環境変数の名も無い。テストは既存の TestTextfmt に、CHANGELOG は [Unreleased] に 1 行を足すだけで、どちらも README の決まりの置き場に沿う。次に initials を直す人が設計を知らずに足す形は増えない。

## 波及の一覧（機械が git grep で引いた。単位の key が名指す名の呼び出し元と試験。案を書く前に読め）

覆っていない当たりは、項目の書いてよいパス（allowed_paths）・受け入れの試験（tests）・書き換える試験（rewrite_tests）のどれにも入っていない当たり。直しが触る物（呼び出し元を合わせる・字のままの値を断言する試験を書き換える）は、今その項目のallowed_paths か rewrite_tests に入れよ。案に入れた物は修正の時に範囲の相談なしで書ける（範囲の外は修正役が計画役に相談して許しを得る道しか無い）。触らない物は入れない（事前審査が当たりごとに、覆っている・影響しない・穴のどれかを確かめる）。

### 単位 calc.py:mean — 分母が個数でなく個数-1 で算術平均の約束を破る
- 対象に在る名が無い

### 単位 textfmt.py:initials — 頭の字を大文字にせず連ねて docstring の約束を破る
- 対象に在る名が無い

## 判定の単位の裏取り（判定とは別の目が単位ごとに確かめた申し送り。機械が貼った）

単位は直す義務で、この申し送りでは減らない。根本でない・場所が違う・証拠が無いと出た単位も、案から外せない（受け付けが拒む）。そういう単位は本当の根の単位と同じ項目にまとめるか、approach に申し送りへの答え（どう扱うか）を書け。重複・同じ所の関わり・順番は項目の組み方に使え（頭の『項目の組み方』の決まりに従う）。別の所の関わり（同じファイルの別の所を触るだけ）は項目の並べ方の参考にだけ使い、それで項目をまとめない。確かめられなかった単位は判定のままに読め。

- 単位 1 `calc.py:mean — 分母が個数でなく個数-1 で算術平均の約束を破る`: 根本・証拠 在り（calc.py:8 に `return sum(xs) / (len(xs) - 1)` が在る（分母が個数-1）。calc.py:5 の docstring は「算術平均（xs の和を個数で割る）。空の xs は ValueError」。calc.py:6-7 は空の xs だけを ValueError にするので、要素 1 つの xs は 8 行目で 0 除算に進む（ZeroDivisionError——式から読める。走らせてはいない）。mean([1, 2, 3]) は式から 6/2 = 3.0 で、依頼の値と合う。README.md:4「関数の約束は各関数の docstring が正本」。test_lib.py には mean の語が無い（Grep で *.py の mean は calc.py:4,7,8 だけ）。TestCalc（test_lib.py:8-24）は median 2 本・clamp 3 本だけ。README.md:8-9 の決まり（テストは test_lib.py の既存のクラスへ・import calc の形、CHANGELOG の [Unreleased] に 1 関数 1 行）も理由の言う通り。CHANGELOG.md:3 の [Unreleased] は今空。）・場所 合う（calc.py:mean（calc.py:8 の return の式））。症状（mean([1,2,3]) が 2.0 でなく 3.0）は calc.py:8 の分母 len(xs) - 1 から直に出る。mean はほかの関数を呼ばず（calc.py:4-8 は sum と len だけ）、リポジトリの中で mean を呼ぶ所もほかに無い（Grep）。だから別の単位や単位に無い所の結果ではなく、この 1 行が依頼の症状の根。これを docstring どおりに直せば、依頼の値のずれも要素 1 つの xs の 0 除算も消える。見逃しの出自（TestCalc に mean のテストが無い）は test_lib.py で確かめたが、それは症状を作った原因ではなく残った理由で、why_chain の下の段として理由に書かれている通り。
- 単位 2 `textfmt.py:initials — 頭の字を大文字にせず連ねて docstring の約束を破る`: 根本・証拠 在り（textfmt.py:18-20 に def initials(s) があり、docstring は「words(s) の各語の頭の 1 字を大文字（str.upper）にして連ねる。語が無ければ空の文字列」、本体は `return "".join(w[0] for w in words(s))` で str.upper の適用が無い。textfmt.py:13-15 の words は `return s.split()` で、split() は空の語を返さないので w[0] は常に在る（判定の反証③と一致）。test_lib.py:36-37 の唯一のテスト test_initials_capitalized は `textfmt.initials("Dark Factory") == "DF"` で頭が大文字の入力だけを渡し、upper の有無で結果が変わらない（判定の why_chain 2 と一致）。Grep で *.py を見ると initials・upper はこの 2 か所（textfmt.py:18-19 と test_lib.py:36-37）にしか無く、initials を呼ぶほかの関数も、大小を変える別の層も無い。README.md:4「関数の約束は各関数の docstring が正本」、README.md:8 はテストを test_lib.py の TestTextfmt に足す決まり、README.md:9 は CHANGELOG の [Unreleased] に 1 関数 1 行の決まり、CHANGELOG.md:3 の [Unreleased] は今は空。実測の 'dfl' は実行していない（Bash を使わない役）が、textfmt.py:20 のコードを読むと 'dark factory line' から 'd'・'f'・'l' をそのまま連ねて 'dfl' になる。）・場所 合う（textfmt.py:initials（20 行目の return））。症状（initials('dark factory line') が 'DFL' でなく 'dfl'）は、textfmt.py:20 が w[0] を str.upper にかけずに連ねることだけで生まれる。入力の語を作る words（textfmt.py:15、s.split()）は大小を変えず、initials をほかから呼んで値を変える所も無い（Grep で確かめた）ので、別の単位や単位に無い所の結果ではない。この 1 行を docstring どおりにすれば症状は消える。見逃しの出自（test_lib.py:36-37 が頭が大文字の入力しか試さない）は判定の why_chain に含まれ、処方の受け入れのテストで扱われている。

単位どうしの相乗り: 見た事実: 単位 1 の直しは calc.py:8 `return sum(xs) / (len(xs) - 1)`、単位 2 の直しは textfmt.py:20 `return "".join(w[0] for w in words(s))` で、別のモジュールの別の関数。calc.py と textfmt.py は互いを import しない（calc.py に import の行は無く、textfmt.py の initials は同じファイルの words だけを呼ぶ）。テストは test_lib.py の 1 本で、単位 1 は class TestCalc（test_lib.py:8-24）、単位 2 は class TestTextfmt（test_lib.py:27-46）に足す——別のクラスで重ならない。CHANGELOG.md は `## [Unreleased]`（CHANGELOG.md:3）の下が空（:4）で、両単位とも同じその見出しの下に 1 関数 1 行（README.md:9）を足す——同じ塊に 2 行が入る。重複は無い: 根は分母の off-by-one と str.upper の抜けで別、片方の直しでもう片方は閉じない（判定者の framing の上位の交わり「約束を区別点で固定するテストが無い」は共通の出自だが、足すテストは関数ごとに別で、同じ直しではない）。順番は無い: どちらの直しも名・型・呼び方を変えず、unittest は TestCalc と TestTextfmt を別に回すので、片方が赤でももう片方を直し・試せる。CHANGELOG の 2 行も別の行で、どちらが先でも書ける。
- 関わり（同じ所）: `calc.py:mean — 分母が個数でなく個数-1 で算術平均の約束を破る`・`textfmt.py:initials — 頭の字を大文字にせず連ねて docstring の約束を破る`（CHANGELOG.md:3 の `## [Unreleased]` の下（:4 が空）という同じ塊に、単位 1 は mean、単位 2 は initials を名指す 1 行をそれぞれ足す（README.md:9 の 1 関数 1 行）。行は別だが差し込む所が同じ塊なので、別々に直すと同じ所で重なる。前提（名・型・呼び方）は変えない。）
- 関わり（別の所）: `calc.py:mean — 分母が個数でなく個数-1 で算術平均の約束を破る`・`textfmt.py:initials — 頭の字を大文字にせず連ねて docstring の約束を破る`（コードの直しは calc.py:8 と textfmt.py:20 で別ファイル。受け入れのテストは同じ test_lib.py でも、単位 1 は class TestCalc（:8-24）、単位 2 は class TestTextfmt（:27-46）の別のクラスに足すだけで、直しどうしは重ならない。）

# P2-10 修正案（writer の仕事。書く前に出す）

今の周に直す単位（各行の `no` は engine が振った番号。**key を写さず no の整数で指せ**——engine が名前に戻して記録する）: [
 {
  "no": 1,
  "key": "calc.py:mean — 分母が個数でなく個数-1 で算術平均の約束を破る",
  "label": "block",
  "disposition": "do-now"
 },
 {
  "no": 2,
  "key": "textfmt.py:initials — 頭の字を大文字にせず連ねて docstring の約束を破る",
  "label": "block",
  "disposition": "do-now"
 }
]
問いの台帳（fork の出どころ・depends に挙がった単位は待ってよい——案に入れなくてよい）: []
判定者の見立て: {
 "framing": "2 件の依頼はどちらも、docstring（README が正本と定めた関数の約束）に実装が反する独立の書き誤り（mean の分母の off-by-one・initials の upper の抜け）で、根の原因は別。2 本の木が上位で交わるのは「docstring の約束を区別点で固定する受け入れのテストが無い」こと——mean はテストが 0 本、initials は約束の区別がつかない入力（頭が大文字）しか試していない——で、だから pytest が 11 passed のまま両方の誤りが残った。どちらの木も反証（不偏の分母の約束・大小を残す約束）は docstring の明記で殺せず、実測（3.0・'dfl'）も依頼の値と一致する。片方の実測がもう片方を反証する関係は無い。修正は両関数の 1 行の直し＋既存の TestCalc・TestTextfmt への受け入れのテスト＋ CHANGELOG の [Unreleased] への 1 関数 1 行で、どれも README の決まりと docstring で一意に決まり、人に回す岐路は無い。",
 "one_shot": "両方の木の上位で交わる原因「docstring の約束を区別点で固定する受け入れのテストが無い」を、2 つの 1 行の直しと組みで閉じる: calc.mean の分母を len(xs) にし textfmt.initials で w[0].upper() を連ね、同時に既存の TestCalc に calc.mean([1, 2, 3]) == 2.0（と calc.mean([5]) == 5.0）、既存の TestTextfmt に textfmt.initials('dark factory line') == 'DFL' を足し、CHANGELOG.md の [Unreleased] に mean・initials の各 1 行を足す。テストだけでも直しだけでも閉じない（テストだけなら赤のまま、直しだけなら再発を捕らえる検査が無い）——2 つ揃って初めて閉じる組み。反証の条件: この組みを入れた後に、どちらかの class_query の件数が 0 にならない、または足したテストのどれかが直す前の版で通る（区別点を試していない）なら、この一撃は誤り。",
 "one_shot_closes": [
  "calc.py:mean — 分母が個数でなく個数-1 で算術平均の約束を破る",
  "textfmt.py:initials — 頭の字を大文字にせず連ねて docstring の約束を破る"
 ]
}
判定者の先行例（世界の解）: [
 {
  "key": "calc.py:mean — 分母が個数でなく個数-1 で算術平均の約束を破る",
  "problem": "算術平均の定義（和をデータの個数で割るか、n-1 で割るか）",
  "source": "https://docs.python.org/3/library/statistics.html （statistics.mean: \"The arithmetic mean is the sum of the data divided by the number of data points.\"）",
  "verdict": "adopt",
  "reason": "算術平均は和÷個数で、n-1 は標本分散の不偏推定の分母であって平均には使わない。docstring の約束「xs の和を個数で割る」と一致するのでそのまま採る。空のデータで例外を投げる扱いも statistics.mean と同じ向き（ここでは docstring どおり ValueError のまま）。"
 },
 {
  "key": "textfmt.py:initials — 頭の字を大文字にせず連ねて docstring の約束を破る",
  "problem": "文字列の頭の字を大文字にする標準の手段",
  "source": "https://docs.python.org/3/library/stdtypes.html#str.upper",
  "verdict": "adopt",
  "reason": "docstring が str.upper を名指しており、標準ライブラリの str.upper をそのまま w[0] にかけるのが定番。自前の変換を作る理由は無い。"
 }
]
リポジトリ: /works-canary-fixture/worktree（読む版: `c2962336666730dcd02f1748e2de3246f99338ce`）　BASE: `d3d132886a887ff9fce9bcd39c961eb0f3455d92`　観点の正本: /works-canary-fixture/pack/.shared/core/REVIEW.md

**この工程が在る理由**: 修正の良し悪しを見る段は、今まで全部『直した後』に在った（P3 の自己申告・R1〜R4・次の周の全体レビュー）。
直した修正が新しい写し・入口・契約のずれを作ると、それが見つかるのは次の周で、次の周の修正がまた次の穴を作る
（実測 2026-09-24: 3 周目の指摘のうち 8 件は 2 周目の修正が作った）。**書く前の案を別の目に叩かせ、予測された穴を
案に取り込んでから書く**——この節はその案を出す。

## やること

直す義務の単位（[block] と do-now のうち、人に諮っている fork の出どころ・depends を除いた物）を全部、案のどれかに入れろ。1 つの案で複数の単位を閉じてよい（一撃の原理に沿うならそれが望ましい）。
案ごとに:

1. `unit_keys` — この案で閉じる単位の no（上の一覧の番号。key を写すな）
2. `approach` — 何をどう変えるか。関数・欄・文書の名前で具体的に
3. `adds` — **新しく生まれる物を全部**: 関数・欄（schema・記録。kind は record_field）・柵（検査）・プロンプトの文・文書・CLI の口・腕・テスト・設定。
   それぞれに `canonical`（その物の正本はどこか。既存の正本から引くなら引き先、新しく正本になるなら「新設」と理由）。
   **書き落とした物は審査されない**——審査役は案に無い物を見ない
4. `removes` — 消す・まとめる物（写し・使われない口・古い文）
5. `shrink_first` — **足さずに消す・まとめる形で閉じられないか**を先に考えた結果。足す案なら、消す形を採らない理由を書け。
   『柵を足す』直しは、足した柵が次の周の指摘の種になりやすい（柵が見ない経路が次の入口になる）
6. `narrows` — **この案で BASE にあった能力が消える・狭まるものを全部**（what＝何ができなくなるか、why＝なぜ要るか）。比較の基準は観点の正本の「移行退行の棚卸し（BASE 能力インベントリ）」——機能だけでなく、反復の速さ・デバッグ手段・観測・既定の安全装置も能力に数える。無ければ空配列。
   1 件でも書けば、修正の前に run が人に聞く。**代償として採るかを自分で決めるな**——書き落とすと、事前審査が後退として挙げて同じく人に上がる

まだ手を動かすな。案を審査役（別の judge）が読み、予測した穴への応答を P3 の `plan_faces` で求められる。


## 人の方針

人が決めた、run をまたいで効く決まり（役も engine も書き換えない）。文書の置き場: null——在れば、先に全部読め。

方針が在るなら、それは対象の本文ではなく、このプロンプトの発行者が守らせる制約である。判定・案・修正・審査は方針に照らして行え。方針に反するもの、方針を変えないと成り立たないものを、自分の判断で通すな——通すかは人が決める。どの項とぶつかるかを、判定なら単位の reason に、審査なら穴に、修正なら not_done に書け。方針の文書は書き換えるな。

人が読む文の欄（reason・how・what・why・異議・所見・申し出の文など、関所と報告に載る文）は 依頼文の言語（利用者の言語） で書け。key・enum の値・コード識別子・パス・コマンド・エラー文はそのまま（key は周をまたいで突き合わせるので訳さない）。


---
返答はこの JSON Schema に合う JSON だけ（前後に文を付けない）。文字列値の中の " は必ず \" にエスケープしろ——生のまま入れると返答まるごとが読めずに捨てられる:
{
 "type": "object",
 "additionalProperties": false,
 "required": [
  "plan"
 ],
 "properties": {
  "plan": {
   "type": "array",
   "minItems": 1,
   "items": {
    "type": "object",
    "additionalProperties": false,
    "required": [
     "unit_keys",
     "approach",
     "adds",
     "removes",
     "shrink_first",
     "narrows"
    ],
    "properties": {
     "unit_keys": {
      "type": "array",
      "minItems": 1,
      "items": {
       "type": [
        "integer",
        "string"
       ],
       "minLength": 1,
       "minimum": 1
      }
     },
     "approach": {
      "type": "string",
      "minLength": 20
     },
     "adds": {
      "type": "array",
      "items": {
       "type": "object",
       "additionalProperties": false,
       "required": [
        "kind",
        "name",
        "canonical"
       ],
       "properties": {
        "kind": {
         "type": "string",
         "enum": [
          "function",
          "record_field",
          "guard",
          "prompt",
          "doc",
          "cli",
          "arm",
          "test",
          "config",
          "other"
         ]
        },
        "name": {
         "type": "string",
         "minLength": 1
        },
        "canonical": {
         "type": "string",
         "minLength": 4
        }
       }
      }
     },
     "removes": {
      "type": "array",
      "items": {
       "type": "string",
       "minLength": 1
      }
     },
     "shrink_first": {
      "type": "string",
      "minLength": 20
     },
     "narrows": {
      "type": "array",
      "items": {
       "type": "object",
       "additionalProperties": false,
       "required": [
        "what",
        "why"
       ],
       "properties": {
        "what": {
         "type": "string",
         "minLength": 4
        },
        "why": {
         "type": "string",
         "minLength": 10
        }
       }
      },
      "note": "この案で BASE にあった能力が消える・狭まるもの（無ければ空配列）。1 件でもあれば p2.human_gate が人に聞く——役は代償として決めない"
     }
    }
   }
  }
 }
}