# 判定の材料（盤面から描いた物）

本線の判定の指示書（graphloops の p2.diagnose.md）の「入力」の節と問いの台帳の段を、この run の盤面から engine と同じ描き方で描いた物。値が貼ってある欄はそのまま読め。パス（対象差分・観点の正本など）は Read で読め。手順と返す JSON の形は、お前を起こした指示書のとおり。

## 入力（素材は観点名でなく欄名で並べてある。起動しなかった欄は status がそう言っている。所見が空欄なら、その節はこの周に走っていない——素材の status と reason を見よ）
素材（15 欄）: {
 "base_determination": {
  "status": "found",
  "count": 0,
  "detail": "HEAD（base_rev の名指し。空なら HEAD）"
 },
 "local_checks": {
  "status": "clean",
  "count": 0,
  "checked": "python3 -m pytest -q（起こし方 direct）を対象の根で走らせた: exit 0（ログ /works-canary-fixture/artifacts/runs/245042a7-d99c-420e-9706-572b5ddca2bc/board/r1/p0.local_checks.log）",
  "detail": "slotwrap.sh: 重いテストの枠を待つ（置き場 /works-canary-fixture/tmp/testslots・4 枠。空くまで期限なし）\ntestslot: slot-1 を取った（4 枠）\n...........                                                              [100%]\n11 passed in 0.01s"
 },
 "prior_decisions": {
  "status": "found",
  "count": 3,
  "detail": "ADR・保留台帳・issue/PR 棄却一覧は無い。決着済みの論点として、README の決まり 2 件と docstring が正本という方針を拾った。calc.mean と textfmt.initials の docstring の約束（mean は和÷個数・空は ValueError、initials は各語頭の字を upper で連ねる）が決まりに当たる。"
 },
 "parallel_pr": {
  "status": "not_applicable",
  "reason": "no_forge: local_path（remote 'origin' はローカルのパス /works-canary-fixture/place/origin.git。PR を持つホストが無いので、PR を前提にする確かめは条件に当たらない）"
 },
 "local_review": {
  "status": "not_applicable",
  "reason": "判定から入る run（出どころ: works/darkfactory。この周の判定に届く人の依頼 2 件）のため、P1 の役を起こしていない——依頼の外を見る目はこの周に無い（判定役と修正前後の審査だけが見る）"
 },
 "consistency": {
  "status": "not_applicable",
  "reason": "判定から入る run（出どころ: works/darkfactory。この周の判定に届く人の依頼 2 件）のため、P1 の役を起こしていない——依頼の外を見る目はこの周に無い（判定役と修正前後の審査だけが見る）"
 },
 "bypass": {
  "status": "not_applicable",
  "reason": "判定から入る run（出どころ: works/darkfactory。この周の判定に届く人の依頼 2 件）のため、P1 の役を起こしていない——依頼の外を見る目はこの周に無い（判定役と修正前後の審査だけが見る）"
 },
 "hygiene": {
  "status": "not_applicable",
  "reason": "判定から入る run（出どころ: works/darkfactory。この周の判定に届く人の依頼 2 件）のため、P1 の役を起こしていない——依頼の外を見る目はこの周に無い（判定役と修正前後の審査だけが見る）"
 },
 "external_standards": {
  "status": "not_applicable",
  "reason": "判定から入る run（出どころ: works/darkfactory。この周の判定に届く人の依頼 2 件）のため、P1 の役を起こしていない——依頼の外を見る目はこの周に無い（判定役と修正前後の審査だけが見る）"
 },
 "procedure_trace": {
  "status": "not_applicable",
  "reason": "対象差分に手順書・スクリプト・CI 定義の変更が無い（差分に手順書・スクリプト・CI 定義が無い）"
 },
 "gate_efficacy": {
  "status": "not_applicable",
  "reason": "判定から入る run（出どころ: works/darkfactory。この周の判定に届く人の依頼 2 件）のため、P1 の役を起こしていない——依頼の外を見る目はこの周に無い（判定役と修正前後の審査だけが見る）"
 },
 "test_double_fidelity": {
  "status": "not_applicable",
  "reason": "判定から入る run（出どころ: works/darkfactory。この周の判定に届く人の依頼 2 件）のため、P1 の役を起こしていない——依頼の外を見る目はこの周に無い（判定役と修正前後の審査だけが見る）"
 },
 "main_path_observation": {
  "status": "not_applicable",
  "reason": "判定から入る run（出どころ: works/darkfactory。この周の判定に届く人の依頼 2 件）のため、P1 の役を起こしていない——依頼の外を見る目はこの周に無い（判定役と修正前後の審査だけが見る）"
 },
 "provenance": {
  "status": "not_applicable",
  "reason": "判定から入る run（出どころ: works/darkfactory。この周の判定に届く人の依頼 2 件）のため、P1 の役を起こしていない——依頼の外を見る目はこの周に無い（判定役と修正前後の審査だけが見る）"
 },
 "fix_closure": {
  "status": "not_applicable",
  "reason": "P1 時点。修正は P3 でこれから行う"
 }
}
局所の findings: （この周には無い）
隔離フレームからの観察——整合性: （この周には無い） ／ 標準機構の迂回: （この周には無い） ／ 外部標準: （この周には無い） ／ 手順トレース: （この周には無い）
修正依頼の入口（この周に積まれた分。バッチごとに origin が出どころ、round が積まれた周。多くは人の依頼で役の観察ではないが、仕様の道の受け入れ条件と並行の線の見逃しも同じ入口で届き、その 2 つは 1 件ごとの本文の頭に出どころを書いてある。どれもほかの findings と同じく反証の対象——依頼の頼み方のずれも殺しにいけ）: [
 {
  "round": 1,
  "origin": "works/darkfactory",
  "findings": [
   {
    "where": "calc.py:mean",
    "text": "mean([1, 2, 3]) が 2.0 でなく 3.0 を返す（docstring の約束は算術平均）。受け入れのテストは README の決まりどおり test_lib.py の TestCalc の中に足す。この直しは利用者に見える振る舞いを変えるので、README の決まりどおり CHANGELOG.md の [Unreleased] に mean を名指す 1 行も要る。修正案の決め（canary）: CHANGELOG.md はこの項目の allowed_paths にも out_of_scope にも書かない（どちらの欄にも CHANGELOG.md を名指さない）。out_of_scope は allowed_paths の中で触らない物の欄で、そこに名指したパスは範囲の相談が『修正案が明示に外したパス』として断るので、CHANGELOG.md を名指せばこの 1 行が書けなくなる。CHANGELOG.md の 1 行は、修正役が範囲の相談で足しを頼み、許しを得てから書く（この依頼は範囲の相談の道を確かめる canary を兼ねる）",
    "mechanism": "分母が len(xs) - 1 になっている（正しくは len(xs)）",
    "measured": "python3 -c 'import calc; print(calc.mean([1, 2, 3]))' が 3.0 を出した",
    "false_positive_if": "mean が標本の不偏の分散の分母を使う約束なら誤り（docstring は和を個数で割ると言う）"
   },
   {
    "where": "textfmt.py:initials",
    "text": "initials('dark factory line') が 'DFL' でなく 'dfl' を返す（docstring の約束は各語の頭の 1 字を大文字にして連ねる。今の test_lib.py の test_initials_capitalized は頭が大文字の語しか渡さないので通っている）。受け入れのテストは README の決まりどおり test_lib.py の TestTextfmt の中に足す。この直しも利用者に見える振る舞いを変えるので、README の決まりどおり CHANGELOG.md の [Unreleased] に initials を名指す 1 行も要る。修正案の決め（canary）: CHANGELOG.md はこの項目の allowed_paths にも out_of_scope にも書かない（どちらの欄にも CHANGELOG.md を名指さない）。out_of_scope は allowed_paths の中で触らない物の欄で、そこに名指したパスは範囲の相談が『修正案が明示に外したパス』として断るので、CHANGELOG.md を名指せばこの 1 行が書けなくなる。CHANGELOG.md の 1 行は、修正役が範囲の相談で足しを頼み、許しを得てから書く",
    "mechanism": "頭の字 w[0] を str.upper にかけずに連ねている",
    "measured": "python3 -c 'import textfmt; print(textfmt.initials(\"dark factory line\"))' が dfl を出した",
    "false_positive_if": "initials が頭の字の大小をそのまま残す約束なら誤り（docstring は大文字にすると言う）"
   }
  ]
 }
]
ゲートの実効性確認: （この周には無い） ／ 代役の忠実性: （この周には無い） ／ 主経路の実行観測: （この周には無い） ／ 根拠の出所検査: （この周には無い）
先行議論の突合（決着済み論点）: {
 "material": {
  "status": "found",
  "count": 3,
  "detail": "ADR・保留台帳・issue/PR 棄却一覧は無い。決着済みの論点として、README の決まり 2 件と docstring が正本という方針を拾った。calc.mean と textfmt.initials の docstring の約束（mean は和÷個数・空は ValueError、initials は各語頭の字を upper で連ねる）が決まりに当たる。"
 },
 "checked": true,
 "searched": [
  "git ls-files（README.md, CHANGELOG.md, calc.py, test_lib.py, textfmt.py, .gitignore の 6 件）",
  "git log（コミット 1 件のみ）・git branch -a・git stash list",
  "README.md 全文",
  "CHANGELOG.md 全文（[Unreleased] は空）",
  "calc.py・textfmt.py 全文（docstring・コメント）",
  "test_lib.py の mean/initials 関連の grep",
  "docs/・doc/・adr/ ディレクトリ（無い）",
  "ADR・決定・保留・棄却の語での全文 grep（README 以外に該当なし）",
  "外部の issue/PR は未確認（works-gh で見ていない。ローカルに remote の issue 情報は無く、リポジトリ名が要るため）"
 ],
 "settled": [
  {
   "topic": "関数の約束の正本",
   "decision": "関数の振る舞いの約束は各関数の docstring が正本",
   "reason": "README が明記している",
   "revisit": "README の方針を変えるとき",
   "where": "README.md 冒頭"
  },
  {
   "topic": "テストの置き場と書き方",
   "decision": "テストは test_lib.py 1 本の、モジュールごとのクラス（TestCalc・TestTextfmt）に足す。新しいテストのファイルやクラスは作らない。モジュールは import calc の形で読み calc.mean のように呼ぶ（from calc import は書かない）",
   "reason": "README の決まり",
   "revisit": "README の決まりを改めるとき",
   "where": "README.md「決まり」1 項目目"
  },
  {
   "topic": "CHANGELOG の記録",
   "decision": "利用者に見える振る舞いを変えた直しは CHANGELOG.md の [Unreleased] に 1 行足す（関数の名で書く、1 関数 1 行）。calc.mean と textfmt.initials を直すなら各 1 行",
   "reason": "README の決まり",
   "revisit": "README の決まりを改めるとき",
   "where": "README.md「決まり」2 項目目、CHANGELOG.md"
  }
 ]
}
凍結した元の目的: calc.mean([1, 2, 3]) が 3.0 でなく算術平均の 2.0 を返し（分母が len(xs) - 1）、textfmt.initials('dark factory line') が 'dfl' でなく各語の頭を大文字にした 'DFL' を返す（頭の字を str.upper にかけていない）よう、両関数の誤りを直し、README の決まりどおり受け入れのテストを test_lib.py の TestCalc と TestTextfmt の中にそれぞれ足し（新しいファイルやクラスは作らない）、利用者に見える振る舞いが変わるので CHANGELOG.md の [Unreleased] に mean と initials を名指す各 1 行を足す（CHANGELOG.md は修正案の allowed_paths にも out_of_scope にも名指さず、修正役が範囲の相談で足しを頼み許しを得てから書く）。　実測した制約: [
 {
  "text": "calc.py:mean — mean([1, 2, 3]) は この作業ツリーで 3.0 を返す（依頼の値と一致）。原因は calc.py の `sum(xs) / (len(xs) - 1)`。docstring は「xs の和を個数で割る」。",
  "measured_how": "python3 を実行し、calc.py を cat",
  "kind": "実測",
  "measured_output": "$ python3 -c 'import calc; print(calc.mean([1, 2, 3]))'\n3.0\n$ cat calc.py (抜粋)\n    return sum(xs) / (len(xs) - 1)"
 },
 {
  "text": "textfmt.py:initials — initials('dark factory line') は この作業ツリーで 'dfl' を返す（依頼の値と一致）。原因は textfmt.py の `\"\".join(w[0] for w in words(s))`（upper なし）。docstring は「各語の頭の 1 字を大文字（str.upper）にして連ねる」。",
  "measured_how": "python3 を実行し、textfmt.py を cat",
  "kind": "実測",
  "measured_output": "$ python3 -c 'import textfmt; print(textfmt.initials(\"dark factory line\"))'\ndfl\n$ cat textfmt.py (抜粋)\n    return \"\".join(w[0] for w in words(s))"
 },
 {
  "text": "README の決まり: テストは test_lib.py の TestCalc（calc.py 用）・TestTextfmt（textfmt.py 用）の中に足し、新しいファイルやクラスは作らない。`import calc` の形で読み `calc.mean` と呼ぶ（from import は書かない）。利用者に見える振る舞いを変える直しは CHANGELOG.md の `[Unreleased]` に 1 関数 1 行、関数の名で足す。",
  "measured_how": "README.md を cat",
  "kind": "実測",
  "measured_output": "$ cat README.md (抜粋)\n- テストは `test_lib.py` の 1 本に置く。モジュールごとのクラス（calc.py は `TestCalc`、textfmt.py は `TestTextfmt`）の中に足し、新しいテストのファイルやクラスは作らない。...\n- 利用者に見える振る舞いを変えた直しは、CHANGELOG.md の `[Unreleased]` に 1 行足す（何を直したかを関数の名で書く。1 関数 1 行）。"
 },
 {
  "text": "CHANGELOG.md は実在し、`## [Unreleased]` の節は今は空（項目 0 行）。test_lib.py には TestCalc（8行目）と TestTextfmt（27行目）があり、initials の既存テストは test_initials_capitalized（頭が大文字の \"Dark Factory\" のみ）。mean の既存テストの名前は grep に出ない（mean の語を含む行なし）。",
  "measured_how": "cat CHANGELOG.md と grep -n test_lib.py",
  "kind": "実測",
  "measured_output": "$ cat CHANGELOG.md\n# Changelog\n\n## [Unreleased]\n\n## [0.1.0]\n\n- 最初の版（calc.py・textfmt.py）\n$ grep -n \"class \\|initials\\|mean\" test_lib.py\n8:class TestCalc(unittest.TestCase):\n27:class TestTextfmt(unittest.TestCase):\n36:    def test_initials_capitalized(self):\n37:        self.assertEqual(textfmt.initials(\"Dark Factory\"), \"DF\")"
 }
]
目的の監査（writer が目的を自書したときの inspector の判定。「狭めている」なら目的の内側／外側の線をそのまま信用するな）: （この周には無い）
対象差分: /works-canary-fixture/artifacts/runs/245042a7-d99c-420e-9706-572b5ddca2bc/board/diff-r1.patch（Read せよ。`git diff d3d132886a887ff9fce9bcd39c961eb0f3455d92 c2962336666730dcd02f1748e2de3246f99338ce`——周に固めた版との差。未追跡の新規ファイルも入る）　変更ファイル: []　リポジトリ: /works-canary-fixture/worktree（読む版: `c2962336666730dcd02f1748e2de3246f99338ce`）
観点の正本: /works-canary-fixture/pack/.shared/core/REVIEW.md（対象リポジトリ側: null）。ラベルと「対応の判断」「処方の最小性」「導線を作る手段の優先順位」はここが正本。
前の周の独立の目が返したもの（この周が初めてなら「無い」と出る）——R1 最小性: （この周には無い）（削除候補 deletions は各行に no を振って別に貼る: （この周には無い）） ／ R3 全体整合: （この周には無い） ／ R4 見えていない範囲: （この周には無い）（capability_inventory.lost は BASE から消えたと R4 が見た能力、policy_conflicts は人の方針とのぶつかり。どちらも人が関所で決める——答えは process.human_items）
defer 台帳（前の周までに受容したキー。今ラウンドの判定に使うのは「同じ欠陥なら同じキー文字列を使う」ためだけ）: （この周には無い）

素材のどれかが明示返答（有無・または「対象外」）を欠いているなら、1〜9 に入らず materials_missing にその欄名を返せ（無言のスキップを「なし」と誤認すると見逃しが構造完備の見た目で再発する）。

## 問いの台帳（本線の判定の指示書の同じ段。kind・status・書ける欄はここが正本）

問いの台帳（questions）: kind は——fork（origin は当該ユニットの key・options が要る）: 設計の岐路——処方が機構の新設・共有面の拡大に及び、候補が複数で、世界の解（標準仕様・著名 OSS の定番）を当たっても決まらない（手順書 P2「処方の列挙」・REVIEW.md「処方の最小性」）。世界の解で決まるなら岐路ではなく処方として採る。選択肢は 2 つ以上、帰結まで書く。零処方（取り下げ・既存の機構 1 つ）が落ちる理由は reason に／split（origin は当該ユニットの key）: 修正が露呈させた既存の欠陥で、凍結した目的の外。別 PR に積むかを人が決める。露呈の回収は既定のまま（REVIEW.md「別 Issue への先送りを既定にするな」）で、これは例外の申請／rule（origin は当該ユニットの key）: 同じ指摘が新証拠なく再燃し、原因がコードでなく観点の誤発火。REVIEW.md のどの観点かを reason に書く／stuck（origin は当該ユニットの key）: 処方の誤りか設計の問題か（発火の条件と要求は stuck_unlisted が持つ）／thrash（origin も depends も持てない）: 新規 [block] が出続けて収束に向かわない。件数の推移で見えるもので、特定のユニットに紐づかない／premise（origin は R1〜R4）: R2 が premise-invalid。別 context の judge が仮定を実態で検算したかが再審の中身／unverifiable（origin は R1〜R4）: R が独立に確かめる材料を取れない／awaiting（origin は素材名）: 素材が awaiting_human（未観測・打ち切られた一覧・洗えなかった決定記録・走らせられない CI）／field（origin も depends も持てない）: 人が実地で確かめるまで決まらない（実機・外部の環境・権限の要る操作）で、どの素材も awaiting_human でない。素材の欄を借りるな——CI の欄を借りると、CI を再実行する工程が毎周上書きする。周を止めず、最終報告の冒頭に載る

split・rule は [block]・do-now のユニットを origin にも depends にもできない（人に聞く前に直す義務が消える。defer にして構造的理由を書け）。素材が awaiting_human なら awaiting を必ず載せろ。status は——held: 未決——次の周の judge が再審する（fork で出どころの [block] を待たせられるのは 1 周だけ）／decided（resolution が要る）: ループが決めたが、出どころの欠陥がまだ開いている／resolved（resolution が要る）: ループが決め、出どころも閉じた——次の周の台帳から落としてよい／escalate: 再審の結果、人でないと決められない（好み・方針・可逆性の低い合意・目的の書き換え）。この周に立てるなら held。**問いは阻害要因を消さない**——当のユニットは [block] のまま。**書けるのは** key／kind／status／reason／resolution／options／depends／origin だけ。

人が読む文の欄（reason・how・what・why・異議・所見・申し出の文など、関所と報告に載る文）は 依頼文の言語（利用者の言語） で書け。key・enum の値・コード識別子・パス・コマンド・エラー文はそのまま（key は周をまたいで突き合わせるので訳さない）。
