# works が対象のリポジトリを Python（pytest）と決め打ちしている所の棚卸し

- 調べた版: `/Users/p03623/src/claude-plugins-work1-next`（枝 wip/works-next）の `works/`。読むだけ。
- 除いた所: `works/tests/**`・`.shared/core/graphloops/**`・`gl-prompts/**`・`.shared/borrow/**`・fixtures・CHANGELOG・docs/plans|specs|archive。
- 目的: 2026-10-03 の持ち主の方針（works は言語ごとの知識の表・言語ごとのプラグインを持たない。JUnit XML・git の差分・終了コード・hash など言語をまたぐ標準は使ってよい。言語の知識が要る判断は、生の出力と案の宣言を読む「読むだけの AI の役」に回す）に合わせるため、外す所を並べる。

## この文書の語

- **(A)・(B)・(C)**: 各項目の頭の印。(A) は対象を Python や特定の道具と決め打ちしていて直す対象。(B) は works 自身の実装の都合で、この一覧には載せない。(C) は直すかどうかに判断が要る物で、理由を添える。
- **手間 S・M・L**: S は 1 ファイル・数十行。M は複数ファイルと試験の作り直し。L は考え方から作り直す。
- **保つ強み 1〜11**: `works/docs/keep-essence.md` が並べる、修正の工程を作り替えても残す 11 の仕組み。番号の中身は次のとおり。1 赤緑の機械の判定（直す前のテストが JUnit XML で failure（error でない）で落ち、直した後に通る）。2 元から赤のテストの区別。3 テストの凍結（hash で控え、変わっていないかを見る）。4 3 回拒まれたら諦めて TDD を使わない直しに回す。5 書き込みの出どころの突き合わせ（Edit・Write の記録と shell の申告に無い書き込みを拒む）。6 受け付けで変更に当たる試験を選んで回し、回さなかった試験を名前で残す。7 判定役の欠陥の探し方（class_query＝git grep の型）で修正の前後の件数を数え直す。8 食い違いの申し出と読むだけの裁定役。9 独立設計。10 守るファイル（protected.json）に触れたら最後の人の関所を開く。11 直す単位ごとの記録が報告と最後の関所に届く。
- **graphloops の写し**: works が `.shared/core/graphloops/` に丸ごと写して持つ、別のプラグイン graphloops の engine と規則。写しの元のファイルは除外の範囲だが、works の `tddloop.py` がそこの関数（`match_case`・`red_problems` など）を呼び、それが決め打ちの元になっている所は (C) か (A) として載せた。
- **COPIED_FROM**: `works/.shared/core/COPIED_FROM`。写しの元と、works が写しに当てた手直しを `!` で始まる 1 行ずつ書いた台帳。写しの関数を works の都合で変える時は、ここに `!` の行を足す決まり。
- **`.review-checks.json`**: 対象のリポジトリの根に置く、テストの段の宣言（段ごとに名前と argv）。works は段に任意の鍵 `junit`（段が書く JUnit XML の相対パス）を足してある（COPIED_FROM の `!` の行、`graphloops/engine/declared.py` の手直し）。
- **依頼 228b**: 赤の種類の見分け（下の 4-1）を作り直す、進行中の依頼の番号。**依頼 218**: 修正案の項目と修正の差分を機械が照らす仕組み（`blk-fix/lib/planscope.py`）を入れた依頼の番号。
- **TDD の輪**: 修正の段で、単位ごとに「テストを書く→赤を確かめる→直す→緑を確かめる」を機械が回す作り（`blk-fix/lib/tddloop.py`）。**実行器（tdd_suite）**: JUnit XML の書き先を第 1 引数に受け、対象の根で一式を走らせる実行ファイル。線の入力で渡す。
- **単位**: 判定役が切った 1 つの欠陥。**direct**: TDD の輪を使わずに直す道。

## 平易版（3 行）

1. 今の works は、対象が Python で pytest を使うときだけ「テストを先に書いて赤→緑を機械で確かめる」輪が既定で回る。Go・TypeScript・Rust・Java では、利用者が自分で実行器を渡さない限り、その輪も「変更に当たる試験を選んで回す」確かめも黙って止まる。
2. 実行器を渡しても、テストの名前の照らし方・既存テストの書き換えの検出・赤の理由の見分けが Python の作法で書かれていて、Go・Java などでは正しいテストを拒んだり、守りが黙って外れたりする。
3. 直し方は 5 つの束に分けられる。言語に依らない事実（JUnit XML・git の差分・終了コード・hash）は機械が見て、言語の知識が要る判断だけを読むだけの AI の役に回す形にそろえる。

## 一番の危険（今壊れている所）

- 既定の起動（`dev/use.sh`）は pytest の 1 コマンドにしか実行器を作らない。ほかの言語では TDD の輪が回らず（保つ強み 1〜4 が丸ごと off）、受け付けの試験の選び（6）も輪の状態が無いので回らない。残るのは最後の blk-tests の終了コードだけ。知らせは 1 行だけ。
- 実行器を渡しても、名指しのテストと JUnit の行の照らし（`match_case`）が pytest の classname（点で区切ったモジュールのパス）を前提にしている。Go（classname がパッケージの import パス）・Jest（describe の題）・Java（`<パス>::<クラス>::<名前>` の名指し）では「一式の結末に居ない」で 3 回拒まれ、単位が direct に落ちる。
- 消えたテスト・名指しの外のテストの書き換えの検査は、テストのファイルを `.py` の名前の型で拾うので、ほかの言語では範囲が空の集合になり、黙って何も見ない。
- 試験の選び（`impact.py`）は、表に無い拡張子（Zig・OCaml・F#・Julia・Erlang・Nim など）を「文書」と見なすので、そのコードを直しても「当たる試験が無い」となって受け付けで何も回さない。

## 件数（工程ごと）

| 工程 | (A) | (C) |
|---|---|---|
| 1 起動・入力 | 2 | 0 |
| 2 判定の前の実測 | 1 | 0 |
| 3 修正案 | 3 | 0 |
| 4 TDD の輪 | 6 | 1 |
| 5 修正の受け付け | 8 | 0 |
| 6 指示書と道具 | 3 | 0 |
| 7 数値・表示・その他 | 0 | 8 |
| 計 | 23 | 9 |

---

## 1. 起動・入力（use.sh・線の入力の約束）

### 1-1 (A) 実行器を作るのは pytest の時だけ — S〜M
- 場所: `works/dev/use.sh:43-45`, `works/dev/use.sh:575-594`。`README.md:38`、`skills/works/SKILL.md:78` も同じことを書く。
- 決め打ち: `test_cmd` が `(uv|poetry) run |python3 -m` + `pytest` の 1 コマンドの時だけ、`--junitxml="$1"` を足した実行器を書いて `tdd_suite` に渡す。ほかは空（TDD の輪を飛ばす）。
- Go/TS/Rust/Java: 黙って弱くなる。TDD の輪が回らず、`tddloop.selected_problems` も輪の状態が無いので `NO_SUITE`（受け付けで試験を選んで回さない）。知らせは 1 行。
- 保つ強み: 1・2・3・4・6 の入口。
- 中立の置き換え: `.review-checks.json` の段の任意の鍵 `junit` を実行器の出どころにする。「段の argv を走らせ、段が宣言した JUnit XML のパスを読む」だけの汎用の実行器を works が 1 本持ち、`tdd_suite` を省いた時はそれを使う。言語ごとの判別をしない。宣言の無い対象には、CI の任せ先の役（blk-ci）と同じ読むだけの役に「JUnit XML を書く段の宣言の案」を出させ、人が承認する形も考えられる（その場合は承認の関所が 1 つ増える）。

### 1-2 (A) 実行器に足す引数の約束が pytest の形 — 束 D1 と一緒に M
- 場所: `skills/works/SKILL.md:78`、`blk-fix/blk-fix.yaml:40-44`、`darkfactory/darkfactory.yaml:58`、`README.md:61`、`blk-fix/lib/tddloop.py:187-197`（`run_suite` が後ろに付ける）、`tddloop.py:276-279`（`_abs_ids` が `<絶対パス>::<名>` を作る）。
- 決め打ち: 実行器の後ろに「試験のファイルの絶対パス・pytest の node id・`-k <式>`」を足して呼ぶ。約束には「解けない実行器は無視してよい」とある。
- Go/TS/Rust/Java: 実行器が `"$@"` をそのまま渡すと `go test -k …` などで落ちる → 走らない扱い（輪を抜ける・受け付けは知らせだけ）。無視する実行器なら、名指しを絞れず毎回一式を回す（遅いが正しい）。
- 保つ強み: 1・6。
- 中立の置き換え: 実行器には書き先の 1 引数だけを渡し、絞り込みは宣言に任せる（宣言に絞りの型 `select_argv: ["…", "{ids}"]` を任意で持たせる程度。中身は対象が書く）。絞れない時は一式を回し、結末の JUnit から名指しの行を拾う。

## 2. 判定の前の実測（blk-premises）

### 2-1 (A) 作業ツリーの見張りが Python のバイトコードだけを特別扱い — S〜M
- 場所: `.shared/core/accept.py:342`（`_NO_BYTECODE`）, `accept.py:343-367`（`snapshot_tree(bytecode=False)`）, `.shared/core/premises.py:46-63`, `blk-premises/scripts/intake.py:86`, `blk-premises/commands/premises.md:7`（「Python を走らせるなら PYTHONDONTWRITEBYTECODE=1」）。
- 決め打ち: 実測役が試験を走らせて出来る物は `__pycache__/` と `.pyc` だけ、と見ている。
- Go/TS/Rust/Java: `.gitignore` に無い生成物（`coverage/`・`*.tsbuildinfo`・tsc の出力・`target/` を無視していない repo など）が出来ると「読むだけの役が作業ツリーを変えた」で誤って拒む。
- 保つ強み: なし（読むだけの役が作業ツリーを変えていないかの見張り）。
- 中立の置き換え: 「git が無視する物は数えない」（既に `--exclude-standard`）＋「機械が走らせたコマンドの前後の差で出来た物を、そのコマンドの産物として控える」（tddloop の `suite_made`・`_cmd_run` と同じ手）。役が自分で走らせた分は、役の申告（`measured_how` のコマンド）を機械が写しの上で走らせ直して産物を引くか、作業ツリーの外で走らせる決まりに寄せる。言語ごとの産物の表は持たない。

## 3. 修正案（blk-plan の欄。planmarks）

### 3-1 (A) テストの名指しの形が pytest の node id — 束 D1、M
- 場所: `.shared/core/planmarks.py:61-67`（`tests`・`rewrite_tests` の `id` は `"::"` を含む文字列）, `planmarks.py:84-86`（`<パス>::<クラス>::<名前>`）, `planmarks.py:126`（`_parse_id`）, `blk-fix/lib/tddloop.py:469-470`（返答の見本）, `blk-fix/rules/tdd.md:37`。
- 決め打ち: 1 本のテストは「ファイルのパス＋クラス＋関数名」で名指せて、それが JUnit の classname・name と後ろ側で一致する（pytest の形）。
- Go/TS/Rust/Java: 宣言そのものは書けるが、後段の照らし（4-2）で外れる。Jest のテスト名は空白入りの文、Go はサブテスト `TestX/case`、Rust は `mod::tests::name`。
- 保つ強み: 1（名指しのテストの赤緑）・3（凍らせるファイル）。
- 中立の置き換え: 名指しは「実行器が JUnit に書く (classname, name) の組」を正本にする。案では「ファイルのパス＋テストの名前（実行器が出す名前のまま）」を宣言し、テストを書いた段の後に、機械が JUnit の結末で「元に無かった行」を引いて名指しと結ぶ（言語に依らない集合の差）。パスは JUnit の `file` 属性が在れば照らし、無ければ役の申告 `test_files` と git の差分で照らす。

### 3-2 (A) テストの定義の行を ast で引き、ほかは「名前を含む最初の行」 — M
- 場所: `planmarks.py:217-230`（`_py_line`）, `planmarks.py:233-242`（`line_in`）, `planmarks.py:245-258`（`find_test`）, `planmarks.py:321-`（`gaps` が `tests` は「まだ無い」、`rewrite_tests` は「在る」を `find_test` で見る）。
- 決め打ち: `.py` だけ構文で引ける。ほかは字の部分一致。
- Go/TS/Rust/Java: `tests` に `TestParse` を書くと、既に `TestParseEmpty` が在るだけで「もう在る」と誤って拒む。`rewrite_tests` の範囲が、名前を含むコメントや呼び出しの行に誤って結ばれる。
- 保つ強み: 3（書き換えの許しの範囲）。
- 中立の置き換え: 在る／無いは、元の版で実行器を回した JUnit の結末（元の結末。既に取っている）に (classname, name) が在るかで見る。行の範囲は案に `<パス>:<行>-<行>` で明示させる（裁定役には既にそうさせている。`blk-fix/rules/ruler.md:31`）。

### 3-3 (A) 書き換えの許しが「定義の 1 行」 — 束 D3、S〜M
- 場所: `planmarks.py:274-277`（`_limit` が `<パス>:<def の行>`）, `.shared/core/conflict.py:577-583`（`_plan_limit` が `line_in` で引き直す）, `blk-fix/rules/principles.md:9`。
- 決め打ち: 1 行の指しは、`.py` なら関数の全体に広がる（5-1）。ほかは 1 行のまま。
- Go/TS/Rust/Java: 承認した既存テストの書き換えが、輪の確かめを経ずに後の修正役の手に回った時、本体の行を 1 行でも変えると「許しの範囲の外」で誤って拒む。
- 保つ強み: 3。
- 中立の置き換え: 3-2 と同じく範囲は明示の行で宣言させる。関数の幅が要るなら、git の `diff -W`（git 自身の関数の境の見分け。`.gitattributes` の diff ドライバで対象が調整できる）か、読むだけの役に範囲を引かせて、機械はその範囲が実在の行かだけを確かめる。

## 4. 修正の TDD の輪（blk-fix/lib/tddloop.py）

### 4-1 (A) 赤の種類の見分けが CPython の例外の名前（既知・依頼 228b）— M
- 場所: `tddloop.py:234-239`（`KIND_UNKNOWN`・`_ASSERT_NAMES`・`_NOT_RAISED`・`NAME_KINDS`・`_HEAD_NAME`・`_MISSING`）, `tddloop.py:242-257`（`red_kind`）, `tddloop.py:825-856`（`_declared_hit`・`_kind_problems`）, `blk-fix/rules/tdd.md:37-41`。
- 決め打ち: 「機能が無い」赤は `NameError`・`AttributeError`・`ImportError`・`ModuleNotFoundError`、無い名前は CPython の message の形 `has no attribute 'x'` などから引く。
- Go/TS/Rust/Java: Go の `undefined: Foo`・TS の TS2305（名前が無いという意味のエラー番号）・Java の `cannot find symbol` は名前で見分けられず、`unknown` か例外名のまま「記録だけで通す」側に落ちる（綴りの誤りの拒否が黙って効かない）。
- 保つ強み: 1。
- 中立の置き換え: 機械は「名指しのテストが通っていない・ほかは元のまま」という JUnit の事実だけを見る。赤の理由（機能が無い／綴りの誤り／準備の失敗）は、読むだけの赤の読み手の役に、生のログ・JUnit の failure の本文・案の宣言（`red_kind`・`red_why`・`adds` の名前）を渡して判定させ、根拠の 1 行を引用させる。機械はその引用がログに字のまま在るかを確かめる（食い違いの申し出の指しの確かめと同じ型）。superpowers の test-driven-development の「失敗の理由が想定どおりか（機能が無い、綴りでない）」を役の判断に置く形。

### 4-2 (A) 名指しと JUnit の行の照らしが pytest の classname 前提 — 束 D1、M〜L
- 場所: graphloops の写し `review-loop-tdd.py:52-68`（`_id_parts`・`match_case`）, `tddloop.py:260-261`（`_key`）, `tddloop.py:653-657`（`_norm_id`）, `tddloop.py:716-718`（`_id_base` が parametrize の `[…]` を落とす）, `tddloop.py:797`・`845`・`901`・`906`・`925`（`rules().match_case`・`red_problems`・`green_problems` を呼ぶ所）。
- 決め打ち: 名指し `a/b/test_x.py::T::t` を「パスの段（拡張子を除く）＋クラス」に割り、JUnit の classname を点で割った末尾と突き合わせる。pytest の classname（`a.b.test_x.T`）の形。
- Go/TS/Rust/Java（実行器を渡した場合）: Go は classname が `github.com/o/r/pkg`（点で割ると `github` と `com/o/r/pkg`）で一致しない。Jest は classname が describe の題。Java は `<パス>::<クラス>::<名前>` で書くとクラスが 2 度数えられ一致しない（クラスを省けば一致する）。結果は「一式の結末に居ない——読み込みで落ちたか、名指しが違う」で誤って拒み、3 回で諦めて direct に回る（保つ強み 4 の諦めの道が言語のせいで発火する）。
- 保つ強み: 1・2・4。
- 中立の置き換え: 3-1 の「(classname, name) を正本にする」に寄せ、照らしは完全一致の集合の比べだけにする（後ろ側の一致という言語の推測をやめる）。名指しと行の結びは、テストを書いた段の前後の JUnit の行の差で機械が作る。写しの関数を使い続けるなら COPIED_FROM の `!` 行で works 側を上書きする。

### 4-3 (C) 「failure で落ちる（error でない）」の決まりが pytest の分け方 — 束 D2
- 場所: graphloops の写し `review-loop-tdd.py:107-130`（`red_problems`）, 保つ強み 1 の文そのもの。
- 判断が要る理由: 保つ強み 1 は「failure（error でない）」と書いている。pytest では未定義の名前も failure になるが、Maven・Gradle の JUnit では断言の外の例外は error、Go・Java・TS・Rust の「関数がまだ無い」はコンパイルの失敗で、testcase の行が出ないか一式ごと落ちる。今の決まりのままだと、コンパイル言語では「機能が無いので落ちる」正しい赤を必ず拒む。
- 中立の置き換え: 機械が見る事実を「名指しが passed でない（failure か error か、一式に居ないで終了コードが 0 でない）・名指しの外は元のまま」に広げ、「準備の失敗か、機能が無いか」は 4-1 の赤の読み手に回す。**保つ強み 1 の文面を変えるので持ち主に聞く。**

### 4-4 (A) 名指しの外の既存テストの本体の書き換え検査が .py だけ（既知）— 束 D3、M
- 場所: `tddloop.py:669-694`（`test_functions`。ast で `test*` 関数を引く）, `tddloop.py:698-713`（`_unnamed_edits`。`.py` でないファイルは見ない）, `tddloop.py:748-761`（`_syntax_problems`）, `blk-fix/rules/tdd.md:41-45`。
- Go/TS/Rust/Java: テストを書く段で、同じファイルの既存のテストの断言を緩めても機械は見ない（黙って弱くなる）。
- 保つ強み: 3（凍結）。
- 中立の置き換え: git の差分の塊（hunk）で「元から在ったテストのファイルの、足すだけでない塊（消した・置き換えた行が在る）」を機械が拾い、その塊と許した書き換えの名指しを読むだけの役に渡して「既存のテストの本体・強さを変えたか」を判定させる。機械は塊の在処が実物と合うかを確かめる。足すだけの塊は今どおり通す。

### 4-5 (A) テストのファイルの見分けが pytest の名前の型 — 束 D3、S〜M
- 場所: `tddloop.py:739`（`TEST_FILE = ^(test_.*|.*_test|conftest)\.py$`）, `tddloop.py:742-745`（`_moved_test_files`）, `tddloop.py:764-775`（`_other_test_edits`）。
- Go/TS/Rust/Java: `*_test.go`・`*.test.ts`・`FooTest.java`・`tests/*.rs` はどれも当たらず、直す段・整える段で「名指しの外のテストのファイルを変えた」検査が黙って止まる。
- 保つ強み: 3。
- 中立の置き換え: テストのファイルは宣言から決める——案の `tests`・`rewrite_tests` のパス、役の `test_files`、JUnit の `file` 属性、`.review-checks.json` に任意の `test_paths` の glob。どれにも無ければ「テストのファイルを知らない」と報告に書く（黙らない）。

### 4-6 (A) 消えた・飛ばしたテストの検査の範囲が空になる — 束 D1/D3、S
- 場所: `tddloop.py:778-782`（`_vanish_scope`。`conftest.py` に触れたら全部、ほかは `TEST_FILE` に当たるファイルのモジュール名）, `tddloop.py:785-807`（`_vanished` が `impact._junit_module` で classname からモジュールを引く）, `tddloop.py:810-822`。
- Go/TS/Rust/Java: 範囲が `None` でなく空の集合になるので、全部の行が「範囲の外」で読み飛ばされる。setUp で skip する・一式から外す抜け道が黙って開く。
- 保つ強み: 3・1（名指しの外を壊さない）。
- 中立の置き換え: 範囲は「単位の頭の回の JUnit に在って passed だった (classname, name) の全部」にする（ファイルとモジュールの対応を使わない）。言語に依らない集合の差で足りる。範囲を絞りたいなら JUnit の `file` 属性が在る時だけ使う。

### 4-7 (A) 役への指示が Python の作法 — S
- 場所: `blk-fix/rules/tdd.md:28`（PYTHONDONTWRITEBYTECODE）, `tdd.md:37`（名指しの形）, `tdd.md:42-43`（「受け入れのテストが無い単位は、今の版に在る名前だけで再現するか、import をテストの中に入れる」＝ImportError を収集の失敗でなく failure にする Python の手）。
- Go/TS/Rust/Java: import を関数の中に書けない言語では従えず、4-3 の決まりと合わせて赤を作れない。
- 保つ強み: 1。
- 中立の置き換え: 4-3 を変えた後に文を「実行器が結末に名指しの行を出す形で落とせ。出ない言語（コンパイルの失敗）は理由を赤の読み手が判定する」に替える。

## 5. 修正の受け付け（blk-fix/scripts/accept.py が呼ぶ物）

### 5-1 (A) 許しの 1 行を関数の幅に広げるのが .py だけ — 束 D3、S〜M
- 場所: `tddloop.py:1196-1221`（`_hunks_outside`。`path.endswith(".py")` の時だけ広げる）, `tddloop.py:1224-1245`（`_function_span`。ast）, `ruler.md:31`・`principles.md:9`（裁定役には「.py 以外は始めと終わりの行で書け」と言ってある）。
- Go/TS/Rust/Java: 修正案の書き換えの許し（3-3 の機械が作る 1 行）を受けた凍ったファイルでは、本体を直すと誤って拒む。裁定役の許しは役が範囲で書くので通る。
- 保つ強み: 3。
- 中立の置き換え: 3-3 と同じ（範囲は明示、関数の幅が要るなら `git diff -W` か読むだけの役）。

### 5-2 (A) 受け付けが実行器に pytest の `-k` とモジュールの絶対パスを渡す — 束 D1/D4、M
- 場所: `tddloop.py:1253`（`PYTEST_FILE`）, `tddloop.py:1256-1261`（`_args`）, `tddloop.py:1264-1306`（`selected_problems`。`kexpr = " or ".join(modules)`）, `tddloop.py:1322-1343`（`_base_reds` も同じ引数）, `.shared/core/writerules/common.md:65`。
- Go/TS/Rust/Java: 実行器が `-k` を解けずに落ちる → 「走らせられない」の知らせだけで、新しい赤の確かめが黙って止まる。無視する実行器なら一式を回すが、変えたテストのファイルは `PYTEST_FILE` に当たらないので名指されない（段の外の試験は走らない）。
- 保つ強み: 6・2（元から赤の区別は `_base_reds` が同じ引数で走らせる）。
- 中立の置き換え: 1-2 と同じ。受け付けは宣言した一式（か宣言の絞りの型）を回し、結末の JUnit で「元で赤でなかった行が赤」を見る（JUnit の集合の差。今の後半の作りのまま）。

### 5-3 (A) 試験の選び（impact.py）が Python の import の地図 — 束 D4、L
- 場所: `.shared/core/impact.py:72`（`PY_EXT`）, `impact.py:81-84`（`OTHER_CODE_EXT`＝「import を読まない言語」の表）, `impact.py:92-93`（`MANIFESTS`）, `impact.py:166-180`（`_lang`）, `impact.py:232-277`（`_py_facts`。ast で import・sys.path・動的 import）, `impact.py:491-560`（`_Modules`。`__init__.py` のパッケージ解決）, `impact.py:760-786`（読めない物 → `all_tests_required`）。
- 決め打ち: Python だけ依存の辺を引き、表に在るほかの言語のコードは「読めない」→ 近くに在れば一式全部、表に無い拡張子は「文書」。
- Go/TS/Rust/Java: 表に在る言語のコードを直すと毎回一式を回す（正しいが遅い・選びの意味が無い）。**表に無い言語（.zig・.ml・.fs・.jl・.erl・.nim・.cr・.sol など）は「文書」扱いで `all_tests_required` が立たず、当たる試験も無いので `NO_SELECTED`＝受け付けで何も回さない（黙って止まる）。**
- 保つ強み: 6。
- 中立の置き換え: 選びの正本を「一式を回す」にし、絞りは `.review-checks.json` の宣言（段・絞りの型）だけで行う。言語の地図は持たない。地図を残すなら「Python は地図で絞る」は言語ごとの知識の表そのものなので、今の方針では外す側。表に無い拡張子を文書と見なす既定は、少なくとも「分からない＝全部回す」に反転する（S。方針に関わらずすぐ直せる穴）。

### 5-4 (A) テストのモジュールの名前の型 — 束 D4、S（5-3 に吸収）
- 場所: `impact.py:86-88`（`TEST_DIRS`・`TEST_NAME`。`test_*.py`・`*_test.(py|go)`・`*.bats`・`*.(test|spec).[jt]sx?`・`conftest.py`）, `impact.py:157-163`（`is_test`）。
- Go/TS/Rust/Java: Java の `FooTest.java`・Kotlin・C#・Rust の `tests/*.rs` はテストと見なされない。設定や文書だけを直した run では、それらに当たる試験が選ばれず `NO_SELECTED`。
- 保つ強み: 6。
- 中立の置き換え: 5-3 と同じ。テストのファイルは宣言・JUnit の `file` 属性から。

### 5-5 (A) 「手元で回さなかった試験」の名前が誤る — 束 D1、S〜M
- 場所: `impact.py:985-998`（`_mod`・`select_tests`）, `impact.py:1001-1008`（`_junit_module`。classname の段が `test_*.py` の名前の型に当たる時だけモジュールを返す）, `tddloop.py:1309-1319`（`_left_to_ci`・`ci_left`）, `darkfactory/lib/line_edge.py:211`（最後の関所が読む）。
- Go/TS/Rust/Java: 結末からモジュールが引けず（全部 None）、選んだテストを全部「手元で回さなかった」と最後の関所と報告に並べる（誤った知らせ）。
- 保つ強み: 6（回さなかった試験を名前で残す）・11。
- 中立の置き換え: 「回した」は JUnit に出た (classname, name)・`file` 属性の集合、「選んだ」は宣言のファイルで言う。照らせない時は「照らせない」と書く（全部を回さなかったと言わない）。

### 5-6 (A) 案に無いテストを足したかの検査が pytest の型と ast — 束 D3、M
- 場所: `blk-fix/lib/planscope.py:83-96`（`_test_ids`）, `planscope.py:99-108`（`new_test_ids`。`tddloop.PYTEST_FILE` に当たるファイルだけ）, `planscope.py:360-366`（案に無いテストの行）。
- Go/TS/Rust/Java: 案に無いテストを足しても見ない（黙って弱くなる）。
- 保つ強み: なし（依頼 218 の範囲の照らし。記録は保つ強み 11 に載る）。
- 中立の置き換え: 新しく現れたテストは、輪の後・受け付けの一式の JUnit の結末と元の結末の (classname, name) の差で引く。案の `tests` との照らしは 3-1 の結びを使う。

### 5-7 (A) adds・removes の「定義」の見分けが Python と JS の形 — 束 D3、M
- 場所: `planscope.py:144-147`（`_definition`＝`def|class`・`name =`・`function name()`）, `planscope.py:157-177`（`_defined_names`。ast）, `planscope.py:200-220`（`_remains`。`.py` だけ ast）。
- Go/TS/Rust/Java: Go の `func Name(`・Rust の `fn name(`・Java のメソッド・TS の `export const name = (…) =>` は定義と見なされず、「消すと言った名が足した行に定義として残る」「canonical の外に同名の定義を足した」の検査が黙って弱くなる（語の境の出現だけは見る）。
- 保つ強み: なし（依頼 218）。
- 中立の置き換え: 機械は「消した行に名が在る・足した行に名が在る」の字の事実だけを見る（今の前半）。それが定義か使用かは、塊と名前を読むだけの役に判定させ、根拠の行を引用させて機械が実在を確かめる。

### 5-8 (A) 修正の差分から Python のバイトコードだけを除く — 束 D5、M
- 場所: `.shared/core/accept.py:342`, `accept.py:443-455`（`_is_bytecode`・`_touched`）, `accept.py:458-`（`touched_files`・`cut_delta`）, `writerules/common.md:65`（「git が無視する生成物（`__pycache__` など）」）, `blk-fix/scripts/assert_changed.py:13`。
- Go/TS/Rust/Java: `.gitignore` に無い生成物（`coverage/`・`*.tsbuildinfo`・tsc が隣に出す `.js` など）を修正役が試験を回して作ると、修正の差分（`fix.diff`）に載り、書き込みの出どころの突き合わせで「記録も申告も無い」と拒む／修正案の範囲の外と拒む。役が `bash_writes` に申告すれば通るが、差分の審査に紛れる。
- 保つ強み: 5。
- 中立の置き換え: 2-1 と同じ。言語の表を持たず「git が無視する物は数えない」＋「機械が走らせたコマンドの前後の差で出来た物は産物として控えて外す（`suite_made` の形）」。修正役が自分で走らせる分は、作業ツリーの外に出させる（JUnit の書き先と同じ決まり）か、産物を申告させる。Python の `.pyc` 除外を残すなら、それも「機械が走らせたコマンドの産物」の一例として同じ口に寄せる。

## 6. 役の指示書と道具（fixrules・libdocs・決まりの文）

### 6-1 (A) 決まりの文の例が Python だけ — S
- 場所: `.shared/core/writerules/common.md:6`（「Python の標準・git…」）, `common.md:65`（「pytest の node id か `-k`、unittest の `-k` かモジュール名」「Python は PYTHONDONTWRITEBYTECODE=1」）, `common.md:66`（`python3 -`）, `blk-premises/commands/premises.md:7`, `blk-fix/rules/tdd.md:28`。
- Go/TS/Rust/Java: AI は読み替えるので壊れはしないが、絞り方の手がかりが Python だけ。
- 保つ強み: なし。
- 中立の置き換え: 「`.review-checks.json` か CI の定義・README にある絞り方を使え」に替え、言語名を出さない。

### 6-2 (A) ライブラリの文書（手元の版・公式・Context7）の見つけ方と引き方が Python と JS だけ — M
- 場所: `.shared/core/libdocs.py` の `PY_SUFFIXES`・`JS_SUFFIXES`・`MANIFESTS`・`REQ_RE`・`PY_DIST`・`NODE_BUILTINS`・`JS_IMPORT`・`manifests`（pyproject・requirements・package.json）・`_own_names`（`__init__.py`）・`detect`, `blk-fix/lib/fixrules.py` の `lib_section`。2026-10-08 に足した手元の版（`.shared/core/libdocs_local.py`。`.venv`・`site-packages`・`dist-info`・`node_modules`・`.d.ts`）と公式（`.shared/core/libdocs_web.py`。PyPI・npm の registry）も Python と JS/TS だけを知る（設計 `docs/plans/2026-10-08-libdocs-sources.md`）。
- Go/TS/Rust/Java: TS は拾う。Go（go.mod）・Rust（Cargo.toml）・Java（pom.xml・build.gradle）は 0 件で、指示書に文書の節が出ない（黙って弱くなる。節の頭に数は出る）。
- 保つ強み: なし。
- 中立の置き換え: 依存の宣言のファイルを読んでライブラリを名指すのは、言語ごとの表そのもの。機械が先に引くのをやめて、修正役（Context7 の MCP を既に持つ）か、読むだけの支度役に「単位のファイルと依存の宣言を読み、引くライブラリと版を返せ」と頼む形にする。機械は返った名前が依存の宣言のファイルに字のまま在るかだけを確かめる。

### 6-3 (A) 変更の種類（code）の見分けが拡張子の表 — S
- 場所: `blk-fix/lib/fixrules.py:84-85`（`CODE_SUFFIXES`）, `fixrules.py:119`。
- Go/TS/Rust/Java: 主な言語は表に在る。Elixir・Haskell・Zig・Dart・OCaml などは種類なし → 指示書に `evidence-code` の節が出ない（黙って弱くなる）。
- 保つ強み: なし。
- 中立の置き換え: 文書・プロンプト・設定を形で見分け、残りを全部 code にする（既定を反転）。言語の表を持たない。

## 7. 規模の数値・表示・その他（判断が要る物）

### 7-1 (C) 注釈の比率が Python の tokenize と C 系のコメントだけ — S
- 場所: `.shared/core/scripts/comment-ratio.sh:1-4`・`63-71`・`195-210`。graphloops の写しで、`darkfactory/nodes.json:39` の `p4.scalars`（builtin）が走らせる。
- 判断が要る理由: graphloops の写し（直すなら写しの元ごと）。数値は記録と報告だけで関門には使わない。`#` 系の言語（Ruby・Shell・Elixir）は数えず 0% と出る。
- 案: 写しの元の扱いに合わせる。works だけで直すなら「数えられない言語のファイルは数えなかったと出す」までに留める。

### 7-2 (C) 変更の枠の表示の表（changemap）— S
- 場所: `.shared/core/changemap.py:111-149`（`file_head`。`.py` の docstring）, `changemap.py:151-166`（`OUTLINE_PATTERNS`）, `changemap.py:240-300`（`COMMENT_BY_EXT`・`PROSE_EXT`・`FENCE_BY_EXT`）。
- 判断が要る理由: 別のプラグイン attention の部品の写し（`COPIED_FROM.changemap`）で、表示（色付け・コメント記号・骨組み）だけ。合否に効かない。言語ごとの表だが維持の重さは写しの元にある。
- 案: 触らない（写しの元に任せる）。

### 7-3 (C) 環境変数の読み書きの形の表（measure.py）— S
- 場所: `blk-structure/scripts/measure.py:36-55`（`ACCESS_FORMS`・`WRITE_FORMS`。`environ`・`getenv`・`env::var`・`process.env`・`ENV[`）。
- 判断が要る理由: 冒頭で「言語に依らない」と名乗る物の中の、小さな言語の表。C#・Elixir などは拾わない。数は判定役の材料で、関門ではない。
- 案: 表を捨てて「名を含む行」の数だけにするか、名を含む行を読むだけの役に分類させる。

### 7-4 (C) works の起動の都合で Python の変数を立てる — 変えない
- 場所: `.shared/core/tree_run.py:64-77`（`outside_env`）。
- 判断が要る理由: uv の変数を外し `PYTHONDONTWRITEBYTECODE=1` を立てる。works が `uv run` で起きる都合（B 寄り）。ほかの言語には害が無い。

### 7-5 (C) 対象の uv の設定が works の起動に読まれる — 変えない
- 場所: `README.md:47`。
- 判断が要る理由: 対象が `[tool.uv]`・`uv.toml` を持つ時だけ起きる、works の起動の側の既知の限界。言語の決め打ちではなく逆向きの衝突。

### 7-6 (C) `.py` の実行器は今の Python で起こす — 変えない
- 場所: `tddloop.py:194`・`376`。
- 判断が要る理由: 実行器の起こし方の便宜（Windows で `.py` を直に起こせない）。対象の言語は問わない。

### 7-7 (C) 名指しの節の囲みと列の見分け（design.py）— 変えない
- 場所: `.shared/core/design.py` の `_heads`・`_md_heads`・`MD_SUFFIXES`。
- 決め打ち: `.md`・`.markdown` は写しの rules の `_md_lines`（囲いの外の行）の `#` 見出しだけを数える（`_md_heads`）。ほかの文書は形の推測（`_heads`）: 記号だけの行の対を囲み、隣り合う同じ前置きの行を列とみなし、同じ記号の行が 1 行だけを挟めば上線と下線の題とみなす。形式の名前は Markdown の拡張子だけ持つ。
- 判断が要る理由: Markdown でない文書では推測のまま。1 行だけの囲み（AsciiDoc の `----` で 1 行を挟むなど）は題に数え、1 行だけの箇条・引用・表の行は見出しに数えうる。

### 7-8 (C) 根拠の名指し（パス:行）に数える拡張子（design.py）— 変えない
- 場所: `.shared/core/design.py` の `ANCHOR_EXT`（`impact.py` の `PY_EXT`・`PATHREF_EXT`・`DOC_EXT`・`OTHER_CODE_EXT` の和）。
- 決め打ち: 拡張子が表に無い `<名>.<字>:<数>`（`db.internal:5432` などの host:port）は名指しに数えない。
- 判断が要る理由: 表に無い拡張子の実在のファイルを名指した根拠は、検算されずに「根拠の実物の名指しなし」と出る。表は 5-3 の impact の表と同じ物。

## 確かめて中立だった所（載せない）

- class_query（`.shared/core/querytest.py`・`recount.py`）: `git grep` で数える。中立（保つ強み 7）。
- blk-tests（`blk-tests/scripts/run_tests.py`）: 終了コードで緑赤。宣言の段は `junit` の件数も見る。中立。
- blk-ci（`ci_role.py`・`blk-ci/prompts/*.md`）: AI が CI の定義を読む。例に `package.json`・`Makefile`・`tox.ini`・`noxfile.py` が並ぶだけ。
- 凍結の hash（`tddloop.hashes`・`specblk` の `tests: [{file, sha}]`）、守りのファイル（`protect.py`・`protected.json` の glob）、差分の審査（`blk-delta`）、食い違いの申し出の指し（`conflict.py`）、書き込みの出どころ（`writes.py`。5-8 の除外を除く）、後始末（`clean.py`・`leftovers.py`。.gitignore で決める）、構造の実測の本体（`measure.py`。7-3 を除く）、`blk-structure`・`blk-eyes`・`blk-material`・`blk-lens`・`blk-report`・`blk-spec`・`blk-rejudge`・`blk-refix`・`blk-pr`。
- `dev/tdd-suite.sh`・`dev/selfcheck.py`・`dev/target-seed/`・`dev/mktarget.sh`: works 自身の試験と自分食いの対象（B）。

---

## 設計の run に分ける束（継ぎ目の同じ物）

1. **D1 実行器の約束とテストの名（JUnit の (classname, name) を正本にする）**: 1-1・1-2・3-1・4-2・4-6・5-2・5-5。継ぎ目は「実行器に何を渡し、結末の行を何で名指すか」。`.review-checks.json` の `junit` を実行器の出どころにし、名指しは JUnit の行の集合の差で結ぶ。照らしは完全一致だけ。graphloops の写しの `match_case` を works 側で上書きするかもここで決める。最初にやる（ほかの束がこの名指しの形に乗る）。
2. **D2 赤の理由の読み手（依頼 228b）**: 4-1・4-3・4-7。機械は「名指しが passed でない・ほかは元のまま・終了コードが 0 でない」だけ。理由は読むだけの役が生のログと案の宣言から判定し、根拠の行を引用、機械が引用の実在を確かめる。保つ強み 1 の文面（failure であって error でない）を変えるので、持ち主の承認が要る。
3. **D3 既存のテストと範囲の守り（git の塊＋読み手）**: 3-2・3-3・4-4・4-5・5-1・5-6・5-7。継ぎ目は「塊（hunk）が既存のテストの本体・定義に当たるか」。機械は git の塊と宣言のパス・範囲を出し、言語の構文が要る判断（本体を変えたか・定義か使用か・関数の幅）は読むだけの役に回す。在る／無い・新しいテストは JUnit の集合の差（D1）で引く。
4. **D4 試験の選び（impact.py の扱い）**: 5-3・5-4（5-2・5-5 は D1 と共有）。選びの正本を「宣言の一式を回す」に替えるか、宣言の絞りの型だけを許すか。先にすぐ直せる穴（表に無い拡張子を文書と見なす既定を「分からない＝全部回す」に反転）を小さな run で出してよい。
5. **D5 生成物と周辺の言語の表**: 2-1・5-8（機械が走らせたコマンドの産物の控えに寄せる）、6-1・6-2・6-3（文の言い換え・既定の反転・Context7 の見つけ方を役へ）、7-1〜7-3（写しの元に合わせる）。互いの継ぎ目は弱いので、2-1＋5-8 と 6-x を別の小さな run に割ってよい。

## 中立にすると失う力（持ち主に聞く物）

- **Python の import の地図で試験を絞る力**（`impact.py` の `_py_facts`・`_Modules`）: 一式を回すか宣言の絞りに替えると、Python の対象で受け付けが遅くなり、「手元で回さなかった試験」の名前の精度も落ちる。
- **「failure であって error でない」を機械だけで決める力**（保つ強み 1 の文面）: 理由の判定が AI の読み手に移る。pytest の対象では今より AI への依りが増える（引用の実在の確かめで自己申告には戻らない）。
- **綴りの誤りを機械が名前で弾く力**（`NAME_KINDS`＋案の `adds` との完全一致）: 読み手の判定に替わる。
- **1 行の指しを関数の全体に広げる力**（`_function_span`）と、**既存のテストの本体の書き換えを関数の単位で正確に見る力**（`test_functions`・`_unnamed_edits`）: 塊の単位＋読み手に替わる。明示の範囲を案に書かせる手間が増える。
- **adds・removes の定義を ast で正確に見る力**（`_defined_names`）: 字の事実＋読み手に替わる。
- **ライブラリの文書を機械が先に引く力**（libdocs の Python・JS の部分）: 役に引かせる形にすると、支度の段の決まった取り方（同じ入力で同じ節）が失われる。
- **Python の docstring を注釈として数える力**（comment-ratio の tokenize）: graphloops の写しなので、外すなら写しの元と揃える。
