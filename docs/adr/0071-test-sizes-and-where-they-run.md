# 0071. 試験は使う資源の大きさで分け、大きさで回す場所を決める（重い試験と変異テストは手元で回さない）

- 状態: 採用
- 日付: 2026-09-29
- 決めた人: 人（09-29「変異試験とか重い試験をローカルであてると負荷が一気にあがるので、それはクラウドであてるようにしておいてね」「ADR にまとめておいて。さらにしっかりテストはわけたり実行場所を変えるような修正をしておいて」）。大きさの境目・回す場所の割り当て・揺れる試験の出口は、人が指した Google の一次情報に沿った回す側の推し（覆せる）。3 の 3（PR ごとの差分の変異テスト）は人が決めた（09-29「撃っていいよ、クラウドでやって」）
- 実装: 一部（手元で回す既定を速い段にした——dogfood の起こし方と引き継ぎの手順。修正の受け付けの試験の選びは、変えた・足した試験のファイルだけを実行器の後ろに足し、届いただけの段の外の試験は手元で回さずに『CI に任せた』として盤面の記録と最後の人の関所に名前で並べる。TDD の輪と受け付けの実行器は nice -n 19 と機械の試験の枠（同時 4 本）を通す。works の全段の CI の job・大きさの宣言と柵・run の最後の試験の重い分を CI に任せる口・差分の変異の PR への指摘・隔離の一覧は未）

## 文脈

- 試験の種類が増え、どれをどこで回すかを 1 か所で決めた物が無かった。決まりは README・ADR（[0019](0019-mutation-testing-google-style.md)・[0020](0020-mutation-after-merge.md)・[0042](0042-ci-skip-allowlist-per-os.md)・[0062](0062-test-migration-policy.md)）・works の段の一覧（`works/tests/tiers.py`）に散らばっていた。
- その結果、手元で重い試験が重なった。2026-09-29、darkfactory の run を 11 本並べたとき、各 run が最初の段と最後の段で test_cmd（works の全段とリポジトリ全体の試験、1 本約 27 分）を手元で回し、load average が 1 分平均で 57 まで上がった。前にも 6〜7 本の並びで 475 まで上がり、役が最初の出力を返せずに落ちている（`first_event_timeout`）。
- 大きさの印は本流の pytest に small・medium だけ在り（`graphloops/README.md` の「大きさの印」）、印の無いファイルが 46 本中 32 本あった（2026-09-29 に数えた）。works の段 fast・heavy は「使う物の形で分ける」考え方で Google の大きさと同じ筋だが、境目が違い、fast にも子プロセスを起こすモジュールが在る。
- works の試験は手元でしか回っておらず、GitHub の CI に job が無かった。

## 決定

### 1. 軸を 2 つに分ける

- **大きさ**（何の資源を使うか）で回す場所と頻度を決める。
- **範囲**（確かめるコードの量: 単体・結合・端から端まで）は、配分と設計の話で、回す場所は決めない。本流の層の印（layer2 など）は範囲の軸に当たる。

### 2. 大きさの定義

- **small**: 1 つのプロセスの中で終わる。子プロセス・sleep・網（socket）を使わない。ディスクは試験ごとの一時の置き場だけ。
- **medium**: 1 台の機械の中で終わる。子プロセス・git・uv・localhost・偽の claude と偽の Archon・手本（golden）の再生・盤面を回す台本を使ってよい。外の網と本物の LLM は使わない。
- **large**: 機械の外に出るか、お金がかかるか、結果が毎回変わる物。本物の Claude（LLM）・本物の Archon での実走（`works/dev/use.sh`・`works/dev/canary.sh`・自分食い）・外の網（GitHub の API など）。
- どの試験も大きさを宣言する。宣言の無い試験は赤にする（黙って既定の大きさに入れない）。small と宣言した試験が子プロセス・sleep・網を使ったら失敗にする（本流の `glharness.py` が子プロセスと sleep で既にしている形を、網にも広げる）。

### 3. 回す場所

1. **手元**（人の端末、darkfactory の run の中の試験、修正役の TDD の輪、取り込みの前の確かめ）: small 全部と、変えた・足した試験（large を除き、大きさを問わない）。`nice -n 19` と機械の枠（同時 4 本）を通す。
   - 手元では回さない: medium の一式（works の全段・heavy、リポジトリ全体の `tests/run.sh`、本流の pytest 一式）、変異テスト（`tests/mutate.py` の本撃ち・mutmut）。
   - 経過の措置: 大きさの宣言が入るまでは、手元の一式は works の `WORKS_TESTS=fast` とする（fast には今 medium に当たるモジュールも在るが、宣言が入るまで入れ替えない）。
2. **push と PR の CI**（GitHub、3 OS）: small と medium の全部。works の全段・リポジトリ全体の試験・本流の pytest 一式。取り込んでよいかは、この緑で決める。
3. **PR の CI の、止めない指摘**: 差分の行の変異テスト（[0019](0019-mutation-testing-google-style.md) の撃ち方）を PR に指摘として出す。取り込みは止めない。
   - 補足（09-29、人）: 09-28 の「変異 CI はしなくていい」（[0067](0067-test-migration-layer2-and-removal-conditions.md) の文脈）は、この答えで置き換わる。試験の CI と枠を奪い合わないよう別の workflow で起こし、同じ PR の新しい push で前の回を止める。手元では撃たない。
4. **合流の後と週 1 回の CI**: mutmut の一式（今の `.github/workflows/mutation.yml` のまま）。
5. **版の関門**: 2 の緑、[0019](0019-mutation-testing-google-style.md) の関門の変異テスト（CI で撃つ）、large の実走（本物の Claude で darkfactory を 1 本以上、最後の関所と報告まで通す）。
6. **large は取り込みの前に回さない。** お金がかかり結果が揺れるので、合否は 1 回の緑でなく通る率で見る（Anthropic の agent の評価の考え方。k 回とも通る率 pass^k など）。率の決め方と回す頻度は別の ADR で決める。

### 4. darkfactory の run の中の試験

- run が最初の段（`p0.local_checks`）と最後の段（`p4.ci`）で回す test_cmd は、手元の一式（上の 3 の 1）にする。重い一式は、取り込んだ後に作業枝（`wip/*`）を push して CI で見る。
- run の最後の試験の重い分を、run の中から CI に任せる口（run の枝を push して CI の結果を待つ）は、依頼として darkfactory に流して作る。できるまでは、取り込んだ後の CI の緑を取り込みの条件にする。

### 5. 揺れる試験

- 自動の再試行は入れない（[0062](0062-test-migration-policy.md) の Q6 のまま）。期限も足さない（[0007](0007-no-deadlines.md) のまま）。
- 代わりに隔離の出口を持つ: 揺れを見つけた試験は、置き場ごとの隔離の一覧に理由と起票先を書いて載せる。CI は隔離した試験を別の job で回して結果を出すだけにし、取り込みは止めない。一覧から外すのは、揺れを直した commit で行う。一覧は減らす向きにだけ使う。

## 比べた案

- **今のまま全段を手元でも回す**（捨てた案）: 並べた run の数だけ全段が重なり、負荷で役が落ちる。実測で 57 と 475。
- **大きさを秒で決める**（捨てた案）: 負荷の高い機械では同じ試験が何倍も遅れるので、秒の境目は揺れる。Google も大きさを資源で決め、秒は目安にとどめている（2010 年の Test Sizes の表・Bazel の既定の時間）。
- **Google と同じく、大きさごとに時間切れを持つ**（捨てた案）: 期限を持たない決まり（[0007](0007-no-deadlines.md)）とぶつかる。負荷の高い機械で遅れて落ちる揺れも増える。
- **Google と同じく、揺れる試験は再試行する**（捨てた案）: Google 自身が「根本原因の先送り」と書いている（Micco 2016・SWE book 23 章）。隔離の出口だけを取る。
- **変異テストの関門をやめ、PR への指摘だけにする**（今回は採らない）: Google は関門にせず指摘に使うが、関門は人が決めた [0019](0019-mutation-testing-google-style.md) の一部なので残す。指摘は足すだけにする。
- **宣言の無い試験は medium と見なす**（Bazel の既定。捨てた案）: 黙って既定に入ると、small のつもりの重い試験が見えない。赤にして宣言させる。

## 理由

- 回す場所を大きさで決めると、手元に来る試験が軽い物だけになり、並べる run の数を増やしても負荷が跳ねない。
- Google の一次情報と同じ向きにそろう: 取り込みの前には速くて揺れない試験だけ、大きく遅い試験は取り込みの後（SWE book 23 章・Memon ら 2017）。大きさは資源で決め、範囲とは別の軸（SWE book 11 章）。変異テストは差分の行だけをレビューの場に指摘として出す（Petrović・Ivanković 2018）。
- このリポジトリは小さく、変更が並んでぶつかる心配も小さいので、Google と違って medium の全部を push と PR の CI に置ける。

## 結果

- 楽になる: run を並べても手元の負荷が跳ねない。どの試験をどこで回すかを、この ADR 1 か所で引ける。
- 難しくなる: 重い一式の結果は push の後にしか分からない。取り込みから緑の確認まで、CI の時間（3 OS で約 10 分〜。works の全段を足すと延びる）を待つ。
- works の全段の CI の job が入るまでは、works の medium の一式を回す場所が無い。その job（自分食い 86 件目）が 0.2.3 の出荷の道の上に乗る。
- fast を small に絞ると、修正役の TDD の輪で回る試験が減る。変えた・足した試験を必ず回す直し（自分食い 87 件目）と組で入れる。

## 見直す条件

- push と PR の CI が 1 つの OS で 30 分を超えたら、medium の一部を合流の後へ移すかを決め直す。
- 揺れる試験の隔離の一覧が 3 本を超えたら、揺れの元（負荷・時間・順序）を調べ、この ADR の出口で足りるかを決め直す。
- large の実走の率の決め方が決まったら、3 の 5 と 6 をその ADR に合わせて直す。

## 出どころ

- 人の指示（2026-09-29 の会話）: 上の「決めた人」の 2 つの言葉。
- 実測（2026-09-29）: 11 本を全段の test_cmd で起こしたときの load average 57。本流の pytest の印の数（`graphloops/tests/py/` の 46 ファイルのうち small 10・medium 9・印なし 32）。
- Google の一次情報:
  - Winters・Manshreck・Wright 編『Software Engineering at Google』（2020）11 章「Testing Overview」<https://abseil.io/resources/swe-book/html/ch11.html>・14 章「Larger Testing」<https://abseil.io/resources/swe-book/html/ch14.html>・23 章「Continuous Integration」<https://abseil.io/resources/swe-book/html/ch23.html>
  - Simon Stewart「Test Sizes」Google Testing Blog（2010-12-13）<https://testing.googleblog.com/2010/12/test-sizes.html>
  - Memon ら「Taming Google-Scale Continuous Testing」ICSE-SEIP 2017 <https://research.google.com/pubs/archive/45861.pdf>
  - John Micco「Flaky Tests at Google and How We Mitigate Them」Google Testing Blog（2016-05-27）<https://testing.googleblog.com/2016/05/flaky-tests-at-google-and-how-we.html>
  - Petrović・Ivanković「State of Mutation Testing at Google」ICSE-SEIP 2018 <https://research.google.com/pubs/archive/46584.pdf>
  - Bazel Test Encyclopedia <https://bazel.build/reference/test-encyclopedia>（Google 由来の OSS の公式文書）
- LLM を使う系の試験: Anthropic「Demystifying evals for AI agents」（2026-01-09）<https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents>。Google の LLM 向けの一次情報は見つからなかった。
