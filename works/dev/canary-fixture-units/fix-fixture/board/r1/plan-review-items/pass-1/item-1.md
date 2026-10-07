# 事前審査の下請け

お前は修正案の事前審査の下請け（読むだけ。Read・Grep・Glob と web の道具で調べ、Write は下の答えのファイルにだけ使う。Edit・Bash を使わず、作業ツリーを 1 文字も変えない）。審査の決まり・独立設計・判定者の見立てはこのファイルの頭に、お前の項目の案・単位・波及の一覧は最後の節に在る。ほかのファイルの指示書を読みに行かなくてよい（根拠のコードは読め）。

関所の項目の決め手: faces のうち kind が regression・policy の各行に、決め手の欄を書け。decided_by＝決め手の出どころ（依頼の引用・URL と節・対象の同じ場面・人の前の決定＝ADR・台帳の行）。undecided_because＝決め手を当たっても答えが 1 つに決まらない理由（書けないなら空にせよ——自明なので人に回さない）。fences＝当たる柵の印（external_write 外への書き込み・irreversible 取り消せない操作・policy_doc 方針の文書の変更・widen_protection 守り（資格・sandbox）を広げる・web_doubt web の結果が新しい疑いを出した）。decided_by が在り undecided_because が空で fences が無い行は修正前の関所で人に聞かずに通り、出どころつきで報告に並ぶ（最後の関所が開けばその文にも）。決め手が無い・決まらない・柵に当たる行は今までどおり人に聞く。人に回す前に、世の中が同じ問題をどう解いているかを当たれ——多くは既に解かれている（標準仕様・著名 OSS・公式の文書の定石。web を引くかは任せる）。定石で 1 つに決まるなら、その出どころを decided_by に書いて自分で決めよ。それでも人に回す行は、world＝当たった結果の 1 文（出どころと割れ方、当たらなかったならその理由）を書け。関所の項目にそのまま載る

狭めない案を添えよ: kind が regression の穴で、BASE の動きを残し、直したい場合だけ新しい動きを当て、当てられない場合は黙らずに名指す形を示せるなら、no_narrow＝その案（20 字以上）を書け。示せなければ書かない。書いた文は関所の項目に添わる

リポジトリ: /works-canary-fixture/worktree（読む版: `c2962336666730dcd02f1748e2de3246f99338ce`）　BASE: `d3d132886a887ff9fce9bcd39c961eb0f3455d92`　観点の正本: /works-canary-fixture/pack/.shared/core/REVIEW.md

**お前は判定をした judge とは別の目**だ。判定者は自分の一撃の原理に肩入れしうる。お前は案が**書かれた後に作る穴**を、
書かれる前に予測する。修正の良し悪しを見る段は今まで全部『直した後』に在り、修正が作った穴は次の周の全体レビューで
初めて見つかっていた（実測 2026-09-24: 3 周目の指摘のうち 8 件が 2 周目の修正の産物）。

## 見ること（案ごと・adds の 1 行ごと）

1. **写し**（kind=copy）: 足す物が、既に正本を持つ規則・型・語彙・手続きを別の場所に写していないか。`canonical` が「新設」なのに
   現物に正本が在るなら写し。リポジトリを読んで確かめろ
2. **入口**（kind=entrance）: 足す柵が見る経路のほかに、同じ集合へ入る経路が無いか。**集合に入る経路を先に全部数えて**から判定しろ
   ——片方の入口だけ塞ぐ柵は、塞がない入口が次の周の指摘になる。**入口の穴には `no_add`（柵や入口を足さずに閉じる形——消す・まとめる・
   世界の解の道具に任せる）を必ず書け。** 無理なら無理な理由を。『入口を足せ』だけの指摘は、足した入口が次の周の指摘の種になる
   （実測 2026-09-24: 3 周目の事前審査に従って参照形式の入口を足したら、4 周目に『入口を足し続けている』と挙がった）
3. **契約のずれ**（kind=contract_drift）: 変える物を読む・書く側（プロンプトの案内・拒否文・文書・テスト・他の節）が追従しないまま残らないか
4. **死んだ道**（kind=dead_path）: 足す物を誰も使わない・届かない形になっていないか
5. **範囲の膨張**（kind=scope_creep）: 単位を閉じるのに要らない機構を足していないか
6. **後退**（kind=regression）: 案が BASE にあった能力を消す・狭めないか——案の `narrows` に書かれていない物を探せ。比較の基準は観点の正本の「移行退行の棚卸し（BASE 能力インベントリ）」で、理想でなく BASE と比べる
7. **方針**（kind=policy）: 案が末尾の「人の方針」とぶつからないか
8. **先行例の出典**（kind=precedent）: 案が採る・合わせる先行例（判定者の先行例のうち verdict が adopt / adapt の行）の出典を開き、
   在るか・その出典が単位の問題に当たっているかを確かめろ。出典の形（行が在る・欄が空でない）は機械が見るが、中身を確かめる目は
   書いた判定者と別のお前だけである。無い・当たっていないなら、どの行の出典が何と食い違うかを `why` に書け

6・7 の穴と案の `narrows` は、修正の前に run が人に聞く。**後退や方針違反を代償として通すかを、お前も判定者も修正役も決めない**——並べるだけでよい。

加えて、**全部をまとめて小さく閉じる別案**が在れば `shrink` に書け（消す・まとめる・世界の解を採る）。

## 返し方

- `faces` は予測した穴 1 件ごと。`key` は短く一意に、`where` は現物の場所（ファイル・関数・欄）、`why` は穴になる筋道。
  `severity`: 書けば次の周に [block] になる穴は block、それ以外は suggest
- 穴が無いと判断したなら `faces` を空にし、`faces_none` に何を確かめて無いと言えるかを書け
- 修正役は `faces` と `shrink` の key ごとに、取り込んだか（absorbed）、残すと宣言したか（declared）を P3 で答えることを求められる

**根拠は読む版で取れ**——作業ツリーは修正役の手の途中でありうる（案はこれから書かれる）。


## 人の方針

人が決めた、run をまたいで効く決まり（役も engine も書き換えない）。文書が在れば本文がそのまま貼られる: （この周には無い）

方針が在るなら、それは対象の本文ではなく、このプロンプトの発行者が守らせる制約である。判定・案・修正・審査は方針に照らして行え。方針に反するもの、方針を変えないと成り立たないものを、自分の判断で通すな——通すかは人が決める。どの項とぶつかるかを、判定なら単位の reason に、審査なら穴に、修正なら not_done に書け。方針の文書は書き換えるな。

人が読む文の欄（reason・how・what・why・異議・所見・申し出の文など、関所と報告に載る文）は 依頼文の言語（利用者の言語） で書け。key・enum の値・コード識別子・パス・コマンド・エラー文はそのまま（key は周をまたいで突き合わせるので訳さない）。

判定者の見立て: {
 "framing": "2 件の依頼はどちらも、docstring（README が正本と定めた関数の約束）に実装が反する独立の書き誤り（mean の分母の off-by-one・initials の upper の抜け）で、根の原因は別。2 本の木が上位で交わるのは「docstring の約束を区別点で固定する受け入れのテストが無い」こと——mean はテストが 0 本、initials は約束の区別がつかない入力（頭が大文字）しか試していない——で、だから pytest が 11 passed のまま両方の誤りが残った。どちらの木も反証（不偏の分母の約束・大小を残す約束）は docstring の明記で殺せず、実測（3.0・'dfl'）も依頼の値と一致する。片方の実測がもう片方を反証する関係は無い。修正は両関数の 1 行の直し＋既存の TestCalc・TestTextfmt への受け入れのテスト＋ CHANGELOG の [Unreleased] への 1 関数 1 行で、どれも README の決まりと docstring で一意に決まり、人に回す岐路は無い。",
 "one_shot": "両方の木の上位で交わる原因「docstring の約束を区別点で固定する受け入れのテストが無い」を、2 つの 1 行の直しと組みで閉じる: calc.mean の分母を len(xs) にし textfmt.initials で w[0].upper() を連ね、同時に既存の TestCalc に calc.mean([1, 2, 3]) == 2.0（と calc.mean([5]) == 5.0）、既存の TestTextfmt に textfmt.initials('dark factory line') == 'DFL' を足し、CHANGELOG.md の [Unreleased] に mean・initials の各 1 行を足す。テストだけでも直しだけでも閉じない（テストだけなら赤のまま、直しだけなら再発を捕らえる検査が無い）——2 つ揃って初めて閉じる組み。反証の条件: この組みを入れた後に、どちらかの class_query の件数が 0 にならない、または足したテストのどれかが直す前の版で通る（区別点を試していない）なら、この一撃は誤り。"
}

## 独立設計（修正案を見ない別の目が、目的と実測した制約・人の関所の答え・依頼が名指した設計書の節から作った理想解。機械が貼った）

修正案をこの設計と構造で突き合わせよ——何を固定し何を派生と見るか・どこに継ぎ目を置くか・目的の当事者が日常で回す動線が閉じるか。構造の本質的な食い違いは faces に kind contract_drift・severity block で挙げ、why を『独立設計との構造の食い違い: 』で始めよ。表現の違い・設計が触れていない所は食い違いでない（設計は判定の単位も実装の事情も知らない）。

設計の役の理由: 問いは実在する。この作業ツリーでの実測では、calc.mean([1, 2, 3]) が 3.0 を返す（原因は分母の len(xs) - 1）。textfmt.initials('dark factory line') は 'dfl' を返す（原因は str.upper がかかっていないこと）。どちらも各関数の docstring（「個数で割る」「str.upper にして連ねる」）と食い違っている。既存のテストは、頭がもとから大文字の入力（\"Dark Factory\"）しか見ていない。mean のテストは grep で 1 行も出てこない。したがって、既存の仕組みが目的を自明に満たしているとは言えない。要件は、期待値（2.0・'DFL'）、テストを置く場所（README の決まり）、CHANGELOG の書き方（1 関数 1 行、関数の名で書く）まで、実測で決まっている。そのため問いは立つと判断し、独立設計に進む。

=====独立設計ここから=====
## 1. コードの直し（最小、docstring に合わせる）
- calc.py:mean: `return sum(xs) / (len(xs) - 1)` を `return sum(xs) / len(xs)` に直す。docstring「xs の和を個数で割る」と一致させる。それ以外の行は触らない。
- textfmt.py:initials: `\"\".join(w[0] for w in words(s))` を `\"\".join(w[0].upper() for w in words(s))` に直す。docstring「各語の頭の 1 字を大文字（str.upper）にして連ねる」と一致させる。words() は触らない。
- 付随する挙動の変化（目的の外。黙って足さず、明示して人の判断に回す）: mean([]) は今は 0/-1 = -0.0 を返しているはずで、直した後は ZeroDivisionError になる。mean([x]) は逆に、今は ZeroDivisionError で、直した後は x を返す。空の入力をどう扱うか（例外の型を変えるか、など）は依頼に無い。だから直しの中で特別な扱いは足さない。修正役はこの変化を報告の not_done／所見に書いて人に見せる。空リストの挙動を決めたいなら、別の依頼にする。

## 2. 受け入れのテスト（README の決まりどおり test_lib.py の既存クラスに足す。新しいファイルやクラスは作らない）
- TestCalc（8行目のクラス）の中に足す: `def test_mean_is_arithmetic(self): self.assertEqual(calc.mean([1, 2, 3]), 2.0)`。分母が n か n-1 かの取り違えを別の値でも捕まえるため、`self.assertEqual(calc.mean([1, 2, 3, 4]), 2.5)` も同じメソッドに足すのが望ましい。呼び方は README どおり `import calc` / `calc.mean` で、from import は書かない（ファイルの頭にある import の形をそのまま使う）。
- TestTextfmt（27行目のクラス、既存の test_initials_capitalized の隣）に足す: `def test_initials_uppercases_lowercase_words(self): self.assertEqual(textfmt.initials(\"dark factory line\"), \"DFL\")`。既存のテストは頭がもとから大文字の入力しか見ていないので、小文字の入力のテストがこの不具合を捕まえる要になる。
- テストを先に書いて確かめる順序: (a) テストを足す → `python3 -m unittest test_lib` を回し、足した 2 本が落ちることを見る（3.0 != 2.0、'dfl' != 'DFL'）。(b) 1 の直しを入れる → 全部が通ることを見る。既存の test_initials_capitalized が通り続けることも見る（回帰していないかの確認）。テストの実行は、作業ツリーの根から引数で動かす。

## 3. CHANGELOG.md（範囲を広げる手順を通す）
- CHANGELOG.md は修正案の allowed_paths にも out_of_scope にも名指さない。修正役は 1 と 2 を終えたあと、範囲の相談で「CHANGELOG.md の [Unreleased] に 2 行足したい」と理由を添えて頼む。理由は README の決まりで、利用者に見える振る舞いが変わる直しだからである。許しを得てから書く。許しが出なければ書かず、not_done に残す。
- 足す位置は `## [Unreleased]` の下（今は 0 行）、`## [0.1.0]` の上。1 関数 1 行で、関数の名で書く:
  - `- calc.mean: 分母を個数（len(xs)）に直し、算術平均を返すようにした（例: [1, 2, 3] → 2.0）`
  - `- textfmt.initials: 各語の頭の字を大文字にして返すようにした（例: 'dark factory line' → 'DFL'）`
- 空の入力での挙動の変化（1 に書いたもの）を CHANGELOG に載せるかは、人の判断に回す。勝手に 3 行目を足さない。

## 4. 確かめの手順（実測で閉じる）
- `python3 -c 'import calc; print(calc.mean([1, 2, 3]))'` → 2.0
- `python3 -c 'import textfmt; print(textfmt.initials(\"dark factory line\"))'` → DFL
- `python3 -m unittest test_lib` → 全部通る（足した 2 本を含む）
- `cat CHANGELOG.md` → [Unreleased] に mean と initials を名指した行がちょうど 2 行ある
- 差分は calc.py・textfmt.py・test_lib.py の 3 ファイルと、許しを得たあとの CHANGELOG.md に限る。新しいファイルは出ない。

## 5. 当事者が日常で回す動線
- 反復開発: 次の直しでも同じ型を使う。既存のクラスにテストを先に足し、`python3 -m unittest test_lib` 1 本で回す。足した 2 本はそのまま回帰テストとして残る。
- リリース: 版を切るときに、[Unreleased] の 2 行を新しい版の見出しの下へ移す。このとき、mean の値が変わることは利用者に見える互換性の変化である。そのため、版番号を 0.1.x にするか 0.2.0 にするかを人が決める（この依頼の範囲外）。
- 撤収・取り消し: 直しは、コード 2 行・テスト 2 メソッド・CHANGELOG 2 行に閉じている。戻すときは、この 1 単位を丸ごと取り消せば元に戻る。部分的に戻す（コードだけ戻す、など）とテストが落ちるので、戻し漏れは unittest で検知できる。
=====独立設計ここまで=====

## 答え方（全部の下請けで同じ）

項目の下請けは、覆っていない当たりの全部に covered（この項目の範囲で覆っている。どこで）・no_effect（影響しない。理由）・block（穴。faces に severity block で挙げる）のどれかで答える（why は当たりごとに 10 字以上。『同上』で済ませない）。faces の unit_keys は項目の unit_keys を字のまま写す（no の整数でなく）。resolved は前の往復の block のうち消えた key（無ければ []）。答えは下の JSON Schema に合う JSON 1 つにして、最後の節が名指すファイルに Write で書く（そのファイルのほかに書かない。書き直す時も同じファイル）。書いたら最後のメッセージに 1 行だけ返す（答えの中身を写さない）。

```json
{"type": "object", "additionalProperties": false, "required": ["item", "checked", "hits", "faces", "shrink", "resolved"], "properties": {"item": {"type": "integer", "minimum": 1}, "checked": {"type": "string", "minLength": 10}, "hits": {"type": "array", "items": {"type": "object", "additionalProperties": false, "required": ["id", "answer", "why"], "properties": {"id": {"type": "string", "minLength": 2}, "answer": {"type": "string", "enum": ["covered", "no_effect", "block"]}, "why": {"type": "string", "minLength": 10}}}}, "faces": {"type": "array", "items": {"type": "object", "additionalProperties": false, "required": ["key", "unit_keys", "kind", "where", "why", "severity"], "properties": {"key": {"type": "string", "minLength": 8}, "unit_keys": {"type": "array", "minItems": 1, "items": {"type": ["integer", "string"], "minLength": 1, "minimum": 1}}, "kind": {"type": "string", "enum": ["copy", "entrance", "contract_drift", "dead_path", "scope_creep", "regression", "policy", "precedent"]}, "where": {"type": "string", "minLength": 4}, "why": {"type": "string", "minLength": 20}, "severity": {"type": "string", "enum": ["block", "suggest"]}, "no_add": {"type": "string"}, "decided_by": {"type": "string"}, "undecided_because": {"type": "string"}, "fences": {"type": "array", "uniqueItems": true, "items": {"type": "string", "enum": ["external_write", "irreversible", "policy_doc", "widen_protection", "web_doubt"]}}, "world": {"type": "string"}, "no_narrow": {"type": "string", "minLength": 20}}}}, "shrink": {"type": "array", "items": {"type": "object", "additionalProperties": false, "required": ["key", "unit_keys", "alternative", "why"], "properties": {"key": {"type": "string", "minLength": 8}, "unit_keys": {"type": "array", "minItems": 1, "items": {"type": ["integer", "string"], "minLength": 1, "minimum": 1}}, "alternative": {"type": "string", "minLength": 20}, "why": {"type": "string", "minLength": 20}}}}, "resolved": {"type": "array", "items": {"type": "string"}}, "precedents": {"type": "array", "items": {"type": "object", "additionalProperties": false, "required": ["id", "found", "quote"], "properties": {"id": {"type": "string"}, "found": {"type": "boolean"}, "quote": {"type": "string", "minLength": 10}}}}}}
```

## お前の項目: 項目 1

お前が見るのは下の項目 1 だけ。この項目が固まる（直しへ進めない穴が無い）まで深く見よ。ほかの項目の穴は挙げない（項目どうしの関わりは別の下請けが見る）。答えは頭の『答え方』の型で、Write の道具でファイル /works-canary-fixture/artifacts/runs/245042a7-d99c-420e-9706-572b5ddca2bc/run-place/planning/plan-review/r1/pass-1/item-1.json に書け。書いたら最後のメッセージに 1 行だけ返せ: `項目 1: clean` か `項目 1: block <key>、<key>`。

### 項目 1 の案

```json
{
 "unit_keys": [
  "calc.py:mean — 分母が個数でなく個数-1 で算術平均の約束を破る",
  "textfmt.py:initials — 頭の字を大文字にせず連ねて docstring の約束を破る"
 ],
 "approach": "2 つの単位のコードの直しは別々の根（calc.mean の分母の off-by-one と textfmt.initials の str.upper の抜け）だが、どちらも README.md:9 の決まりで CHANGELOG.md の `## [Unreleased]` の下（CHANGELOG.md:3-4 の同じ塊）に 1 行ずつ足すため、同じ hunk を変える。『項目の組み方』の同じ塊の条件に当たるので 1 つの項目にまとめる。直しは次のとおり: (1) calc.py:8 の `return sum(xs) / (len(xs) - 1)` を `return sum(xs) / len(xs)` にして、docstring『算術平均（xs の和を個数で割る）』と statistics.mean の定義に合わせる。空の xs の ValueError（calc.py:6-7）はそのまま残す。(2) textfmt.py:20 の `\"\".join(w[0] for w in words(s))` を `\"\".join(w[0].upper() for w in words(s))` にして、docstring の str.upper の約束に合わせる。words(s) はそのまま使う。(3) test_lib.py の既存の TestCalc に test_mean_arithmetic（calc.mean([1, 2, 3]) == 2.0 を先に断言し、続けて calc.mean([5]) == 5.0 も断言）、既存の TestTextfmt に test_initials_lowercase_input（textfmt.initials(\"dark factory line\") == \"DFL\"）を足す。README.md:8 のとおり `import calc`・`import textfmt` の形で呼び、新しいファイルやクラスは作らない。(4) CHANGELOG.md の `## [Unreleased]` の下に、mean の直し（分母を個数にして算術平均を返すようにした）と initials の直し（各語の頭の字を大文字にして連ねるようにした）の各 1 行を足す（1 関数 1 行）。構造の目の避け方（新しい名前・口・設定を足さず、docstring に実装を合わせ、既存の置き場にテストと CHANGELOG を足す）にそのまま従う。",
 "adds": [
  "test_mean_arithmetic",
  "test_initials_lowercase_input",
  "CHANGELOG [Unreleased] mean の 1 行",
  "CHANGELOG [Unreleased] initials の 1 行"
 ],
 "removes": [],
 "shrink_first": "コードの直しは足す形でなく、既存の 1 行の式を直すだけ（分母の `- 1` を消す・w[0] に str.upper をかける）で、新しい関数・口・柵は足さない。足すのは受け入れのテスト 2 本と CHANGELOG の 2 行だけ。テストを足さない形も考えたが、mean はテストが 0 本、initials は頭が大文字の入力しか試しておらず、直しだけでは再発を捕まえる検査が無い（判定の one_shot が直しとテストの組みで閉じるとしている）。CHANGELOG の行は README.md:9 の決まりが利用者に見える振る舞いを変えた直しに求めるので省けない。既存のテスト test_initials_capitalized は約束に反しないので消さず、そのまま残す。",
 "narrows": [],
 "route": "tdd",
 "route_why": "",
 "tests": [
  {
   "id": "test_lib.py::TestCalc::test_mean_arithmetic",
   "behavior": "calc.mean が和を個数で割った算術平均を返す: calc.mean([1, 2, 3]) == 2.0、要素 1 つの calc.mean([5]) == 5.0",
   "path": "test_lib.py の `import calc` で本物の calc.mean を呼び、返り値を assertEqual で断言する（mock は使わない）。[1, 2, 3] の断言を先に置く",
   "red_kind": "assertion",
   "red_why": "今の calc.py:8 は分母が len(xs) - 1 なので calc.mean([1, 2, 3]) は 6/2 = 3.0 を返し、最初の assertEqual(…, 2.0) が AssertionError で落ちる"
  },
  {
   "id": "test_lib.py::TestTextfmt::test_initials_lowercase_input",
   "behavior": "textfmt.initials が各語の頭の字を大文字にして連ねる: textfmt.initials(\"dark factory line\") == \"DFL\"",
   "path": "test_lib.py の `import textfmt` で本物の textfmt.initials を呼び、返り値を assertEqual で断言する（mock は使わない）",
   "red_kind": "assertion",
   "red_why": "今の textfmt.py:20 は w[0] に str.upper をかけないので \"dfl\" を返し、assertEqual(…, \"DFL\") が AssertionError で落ちる"
  }
 ],
 "rewrite_tests": [],
 "refactor": {
  "declared": false,
  "why": ""
 },
 "allowed_paths": [
  "calc.py",
  "textfmt.py",
  "test_lib.py",
  "CHANGELOG.md"
 ],
 "out_of_scope": [
  {
   "glob": "README.md",
   "why": "決まりの正本で、今回の直しは README の決まりに沿うだけで書き換えない"
  }
 ]
}
```

### 項目 1 の単位（判定）

```json
[
 {
  "key": "calc.py:mean — 分母が個数でなく個数-1 で算術平均の約束を破る",
  "label": "block",
  "disposition": "do-now",
  "reason": "事実: calc.py:8 は `return sum(xs) / (len(xs) - 1)`。docstring（README の言う正本）は「算術平均（xs の和を個数で割る）」。前提の実測で mean([1, 2, 3]) は 3.0（依頼の値と一致。測り直した値と依頼の値に違いは無い）。反証を当てた: ①依頼の false_positive_if「不偏の分母を使う約束なら誤り」→ docstring は「個数で割る」と明記し、名も『算術平均』で、標本分散ではなく平均なので不偏の補正は意味を持たない——誤検出の条件は成り立たない。②今のコードは要素 1 つの xs（例 [5]）で ZeroDivisionError を投げ、docstring の「空の xs だけが ValueError」の約束からも外れる——欠陥は値のずれだけでなく例外の面にも出ており、誤りであることを補強する。③テストが mean を 1 本も持たない（test_lib.py に mean の語が無い）ので、pytest が 11 passed でも反証にならない。依頼の頼み方（テストを TestCalc に足す・CHANGELOG の [Unreleased] に mean を名指す 1 行）も README の決まり 1・2 項と一致し、ずれは見つからない。人の方針は空でぶつかる行は無い。"
 },
 {
  "key": "textfmt.py:initials — 頭の字を大文字にせず連ねて docstring の約束を破る",
  "label": "block",
  "disposition": "do-now",
  "reason": "事実: textfmt.py:20 は `return \"\".join(w[0] for w in words(s))` で、頭の字を str.upper にかけていない。docstring（正本）は「words(s) の各語の頭の 1 字を大文字（str.upper）にして連ねる」。前提の実測で initials('dark factory line') は 'dfl'（依頼の値と一致。違いは無い）。反証を当てた: ①依頼の false_positive_if「大小をそのまま残す約束なら誤り」→ docstring は str.upper を名指しており成り立たない。②既存の test_initials_capitalized は頭が大文字の \"Dark Factory\" しか渡さないので、upper の有無を区別できず、11 passed は反証にならない。③語が無い時の空の文字列は今も「\".join(空)\" で保たれ、upper を足しても変わらない（w[0] は words が空の語を返さないので常に在る）。依頼の頼み方（テストを TestTextfmt に足す・CHANGELOG の [Unreleased] に initials を名指す 1 行）も README の決まりと一致する。人の方針は空でぶつかる行は無い。"
 }
]
```

## この項目の先行例の出典（判定者の先行例のうち adopt・adapt。見ること 8）

- P1: https://docs.python.org/3/library/statistics.html （statistics.mean: "The arithmetic mean is the sum of the data divided by the number of data points."）（verdict adopt・単位 calc.py:mean — 分母が個数でなく個数-1 で算術平均の約束を破る・判定者の理由 算術平均は和÷個数で、n-1 は標本分散の不偏推定の分母であって平均には使わない。docstring の約束「xs の和を個数で割る」と一致するのでそのまま採る。空のデータで例外を投げる扱いも statistics.mean と同じ向き（ここでは docstring どおり ValueError のまま）。） — WebFetch で 1 度だけ開いて確かめ、答えの precedents に {id, found（在り単位の問題に当たっているか）, quote（確かめた一文）} の行を書け
- P2: https://docs.python.org/3/library/stdtypes.html#str.upper（verdict adopt・単位 textfmt.py:initials — 頭の字を大文字にせず連ねて docstring の約束を破る・判定者の理由 docstring が str.upper を名指しており、標準ライブラリの str.upper をそのまま w[0] にかけるのが定番。自前の変換を作る理由は無い。） — WebFetch で 1 度だけ開いて確かめ、答えの precedents に {id, found（在り単位の問題に当たっているか）, quote（確かめた一文）} の行を書け

## 波及の一覧（機械が git grep で引いた。項目が変える名の呼び出し元と試験）

### 項目 1（unit_keys: calc.py:mean — 分母が個数でなく個数-1 で算術平均の約束を破る、textfmt.py:initials — 頭の字を大文字にせず連ねて docstring の約束を破る）

変える名と当たり:
- CHANGELOG: 当たり 1 ファイル
  - 本体 README.md:9
- Unreleased: 当たり 1 ファイル
  - 本体 README.md:9
- mean: 当たり 2 ファイル
  - 本体 README.md:8
  - 本体 calc.py:4
  - 本体 calc.py:7
- initials: 当たり 2 ファイル
  - 本体 textfmt.py:18
  - 試験 test_lib.py::TestTextfmt::test_initials_capitalized

覆っていない当たり:
- h1: code README.md:9（名 CHANGELOG）
- h2: code README.md:8（名 mean）
- h3: test test_lib.py::TestTextfmt::test_initials_capitalized（名 initials）
