# 判定の単位の裏取りの下請け

お前は判定の単位の裏取りの下請け（読むだけ。Read・Grep・Glob で根拠のコードを調べ、Write は最後の節が名指す答えのファイルにだけ使う。Edit・Bash を使わず、作業ツリーを 1 文字も変えない）。判定役が人の修正依頼を根本の単位に切った。お前はその切り方を判定役とは別の目で確かめる。ほかのファイルの指示書を読みに行かなくてよい（根拠のコードは読め）。

## 決まり（全部の下請けで同じ）

- 直し方は書かない（案は別の役が作る）。
- 単位を消す・足す・ラベルを変える提案はしない。単位は直す義務で、この確かめでは減らない。根本でないと出ても、申し送りとして案を書く役と報告に届くだけ。
- web（WebSearch・WebFetch）は根拠のコードで決まらない時だけ使う。判定の先行例の出典は開き直さない。
- why・evidence は見た事実（パス:行と、そこに在った物）で書く。推測は unsure にする。

## 判定者の見立て

```json
{
 "framing": "2 件の依頼はどちらも、docstring（README が正本と定めた関数の約束）に実装が反する独立の書き誤り（mean の分母の off-by-one・initials の upper の抜け）で、根の原因は別。2 本の木が上位で交わるのは「docstring の約束を区別点で固定する受け入れのテストが無い」こと——mean はテストが 0 本、initials は約束の区別がつかない入力（頭が大文字）しか試していない——で、だから pytest が 11 passed のまま両方の誤りが残った。どちらの木も反証（不偏の分母の約束・大小を残す約束）は docstring の明記で殺せず、実測（3.0・'dfl'）も依頼の値と一致する。片方の実測がもう片方を反証する関係は無い。修正は両関数の 1 行の直し＋既存の TestCalc・TestTextfmt への受け入れのテスト＋ CHANGELOG の [Unreleased] への 1 関数 1 行で、どれも README の決まりと docstring で一意に決まり、人に回す岐路は無い。",
 "one_shot": "両方の木の上位で交わる原因「docstring の約束を区別点で固定する受け入れのテストが無い」を、2 つの 1 行の直しと組みで閉じる: calc.mean の分母を len(xs) にし textfmt.initials で w[0].upper() を連ね、同時に既存の TestCalc に calc.mean([1, 2, 3]) == 2.0（と calc.mean([5]) == 5.0）、既存の TestTextfmt に textfmt.initials('dark factory line') == 'DFL' を足し、CHANGELOG.md の [Unreleased] に mean・initials の各 1 行を足す。テストだけでも直しだけでも閉じない（テストだけなら赤のまま、直しだけなら再発を捕らえる検査が無い）——2 つ揃って初めて閉じる組み。反証の条件: この組みを入れた後に、どちらかの class_query の件数が 0 にならない、または足したテストのどれかが直す前の版で通る（区別点を試していない）なら、この一撃は誤り。"
}
```

## お前の単位: 単位 1

```json
{
 "key": "calc.py:mean — 分母が個数でなく個数-1 で算術平均の約束を破る",
 "label": "block",
 "disposition": "do-now",
 "reason": "事実: calc.py:8 は `return sum(xs) / (len(xs) - 1)`。docstring（README の言う正本）は「算術平均（xs の和を個数で割る）」。前提の実測で mean([1, 2, 3]) は 3.0（依頼の値と一致。測り直した値と依頼の値に違いは無い）。反証を当てた: ①依頼の false_positive_if「不偏の分母を使う約束なら誤り」→ docstring は「個数で割る」と明記し、名も『算術平均』で、標本分散ではなく平均なので不偏の補正は意味を持たない——誤検出の条件は成り立たない。②今のコードは要素 1 つの xs（例 [5]）で ZeroDivisionError を投げ、docstring の「空の xs だけが ValueError」の約束からも外れる——欠陥は値のずれだけでなく例外の面にも出ており、誤りであることを補強する。③テストが mean を 1 本も持たない（test_lib.py に mean の語が無い）ので、pytest が 11 passed でも反証にならない。依頼の頼み方（テストを TestCalc に足す・CHANGELOG の [Unreleased] に mean を名指す 1 行）も README の決まり 1・2 項と一致し、ずれは見つからない。人の方針は空でぶつかる行は無い。",
 "origin_analysis": "①ロジックの正否: 誤り（分母の off-by-one。算術平均の定義＝和÷個数から外れる）。②出自: 読みにくさ・迂回・衛生違反ではなく、式の書き誤り（標本分散の n-1 の分母の取り違えの形）。それを捕らえる受け入れのテストが無い（mean のテストが 0 本）ことが見逃しの出自。③ラベル: docstring という決着済みの正本に反する利用者に見える誤りなので block。",
 "why_chain": [
  "なぜ誤った値が出るか: 分母が len(xs) - 1 になっている（分散の不偏推定の分母と取り違えた形）",
  "なぜ入り込めたか: TestCalc に mean のテストが 1 本も無く、docstring の約束（和÷個数）を固定する検査が無い",
  "なぜ検査が無かったか: テストが median・clamp だけを覆い、モジュールの全公開関数を docstring の約束で覆う決まりが README に無い（決まりは置き場と書き方だけを言う）"
 ],
 "prescriptions": [
  "零処方は当たらない: 取り下げは反証が成り立たないので落ちる。既存の機構 1 つで済ませる処方が下の式の直し 1 行そのもの。",
  "calc.py:8 を `return sum(xs) / len(xs)` にする。採った理由: 決め手 (a) 人の前の決定——README.md 冒頭「関数の約束は各関数の docstring が正本」と docstring「xs の和を個数で割る」。(d) 世界の解——Python 公式 docs の statistics.mean「The arithmetic mean is the sum of the data divided by the number of data points」と一致。空の xs の ValueError の扱いは今のまま残す（docstring の約束）。",
  "受け入れのテストを test_lib.py の既存の class TestCalc の中に足す（新しいファイル・クラスは作らない。`import calc` のまま `calc.mean` で呼ぶ。README の決まり 1 項）。少なくとも calc.mean([1, 2, 3]) == 2.0 と、今のコードで ZeroDivisionError になる要素 1 つの例（calc.mean([5]) == 5.0）を固定する。空の xs が ValueError のままであることも 1 本で固定するのが望ましい。",
  "CHANGELOG.md の `## [Unreleased]` に mean を名指す 1 行を足す（README の決まり 2 項: 関数の名で 1 関数 1 行）。keepachangelog の ### Fixed の小見出しは README が求めていないので足さない（決め手 (c) 対象の決まりが世界の解より先）。依頼の決めどおり、CHANGELOG.md は修正案の allowed_paths にも out_of_scope にも名指さず、修正役が範囲の相談で足しを頼み許しを得てから書く。"
 ]
}
```

見ること: (1) 根本か（verdict）: この単位を直せば依頼の症状が消えるか。ほかの単位か単位に無い所の結果（症状の 1 つの現れ）でないか。root・not_root・unsure のどれか。not_root なら real_root に本当の根（見つけた所のパスと名と、そこが根と言える理由）を書く。単位どうしの重なりは別の下請けが見る。(2) 証拠（evidence_found・evidence）: 判定の理由が言う事実を根拠のコードで確かめたか。確かめた所と見た事を書く。(3) 場所（location_ok・location）: 単位の key が名指すパスと名が直す所か。違えば正しい場所を location に書く（合っていれば同じ場所）。答えは下の JSON Schema に合う JSON 1 つにして、Write の道具でファイル /works-canary-fixture/artifacts/runs/245042a7-d99c-420e-9706-572b5ddca2bc/run-place/judging/judge-verify/r1/unit-1.json に書け（このファイルのほかに書かない）。書いたら最後のメッセージに 1 行だけ返せ: `単位 1: <verdict>`。

```json
{"type": "object", "additionalProperties": false, "required": ["unit", "verdict", "evidence_found", "evidence", "location_ok", "location", "why"], "properties": {"unit": {"type": "integer", "minimum": 1}, "verdict": {"type": "string", "enum": ["root", "not_root", "unsure"]}, "evidence_found": {"type": "boolean"}, "evidence": {"type": "string", "minLength": 10}, "location_ok": {"type": "boolean"}, "location": {"type": "string", "minLength": 1}, "why": {"type": "string", "minLength": 10}, "real_root": {"type": "string"}}}
```
