# rent-or-buy の設計

rent-or-buy の設計書の日本語訳。正本は英語の [design.md](design.md) で、2 つが食い違うときは英語の版が正しい。2 つのファイルは見出しの数と並びが同じで、`tests/test_docs.py` がそれを確かめる。

読む人: プラグインを保守する人、呼ぶ側を書く人、プラグインをこのリポジトリの外へ切り出す人。コマンドの呼び方は [README.md](../README.md)（英語）にあり、この文書はなぜその作りなのかを書く。

## 1. 解く問題

Claude Code の会話には、少しずつ払い続ける（借りる）か、まとめて 1 回払う（買う）かを、いつまで要るか分からないまま決める場面が 2 つある。

- keepalive: 会話が何か（裏の処理の結果や知らせ）を待っている間、プロンプトのキャッシュは最後の要求から 5 分か 1 時間で切れる。切れる前に短い要求を送ればキャッシュは保たれる（借りる: 要求 1 本）。止めれば、次の本物の要求が文脈の全体をキャッシュに書き直す（買う: その書き直しで余分にかかる額）。
- compact: 会話を要約して文脈を縮める Claude Code の操作。大きな文脈のままの要求は、compact した後より多くのキャッシュを毎回読む（借りる: この要求で余分に読む額）。compact は要約とキャッシュの書き直しの費用を 1 回払う（買う）。

この形の問題は ski rental（rent-or-buy problem とも呼ぶ）と呼ばれる（[Wikipedia: Ski rental problem](https://en.wikipedia.org/wiki/Ski_rental_problem)）。先の見込みが無いときのふつうの答えは決め打ちの数で、N 秒おきに M 本まで keepalive を送る、トークン数がしきい値を超えたら compact する、といった形になる。この数は、値段・モデル・文脈の大きさが変わっても動かない。

rent-or-buy は、この判断を費用だけから出す小さな部品。状態を持たず、呼ぶ側のプロセスを知らず、JSON を渡して JSON を受け取るコマンドとして呼ぶ。

## 2. 層

1 つのプラグインに Python のモジュールを 2 つ置く（モジュラモノリス。1 つにまとめて配り、中の境目は試験で守る）。

```
  呼ぶ側（スクリプト・フック・ほかのプラグイン）
  │  コマンド bin/rent-or-buy を起動する（標準入力に JSON、標準出力に JSON）。Python のモジュールは import しない
  ▼
  prompt_cache/   Claude のプロンプトキャッシュへの当てはめ
  │  値段の表・モデル名の正規化・会話の記録（transcript）の読み取り・翻訳（場面の事実 → 中心の入力）
  ▼  rent_or_buy の公開する名前（__init__.py に並べた物）だけを使う
  rent_or_buy/    借りるか買うかのアルゴリズム。Claude もトークンも知らない
     中心の decide・決め方の表・判断の記録
```

- 依存は上から下への一方向だけ。下の層は、上の層のファイル・名前・振る舞いを書かない。
- アルゴリズムを Claude から切り離すのは、変わる速さが違うから。アルゴリズムは理論から決まり、ほとんど変わらない。値段・モデル名・会話の記録の形は、Anthropic と Claude Code が変えるたびに変わる。
- プラグインを 2 つに分けない訳: 今の呼ぶ側は 1 種類で、アルゴリズムだけを使う利用者はいない。2 つに分けると版の固定と配る手間が倍になり、境目は試験で守れる。2 つ目の利用者が出たら、`rent_or_buy/` のフォルダをそのまま外へ出せる。
- 部品は状態を持たない。呼ぶ側が毎回、その時点の累計を渡す。
- 指針（いつ keepalive を送るか、いつエージェントに聞くか、`/compact` をどう打つか、Claude Code の自動の compact をどこに置くか）は呼ぶ側が持つ（7）。
- 部品が無い・失敗したときは、呼ぶ側は自分の決め打ちの数で動く。部品は費用の最適化で、止めるゲートではない。

### 2.1 境目の守り方

`tests/test_boundary.py` が次の 4 つの決まりを確かめ、1 つでも外れたら失敗にする。

1. `rent_or_buy/` が import するのは、標準ライブラリ（Python の `sys.stdlib_module_names`）と自分だけ。
2. `prompt_cache/` は `rent_or_buy` の公開する名前（`rent_or_buy/__init__.py` に並べた物）だけを使い、`rent_or_buy.policies` などの中のファイルを直に import しない。中を作り替えても外が壊れないようにするため。
3. プラグインの外から `rent_or_buy`・`prompt_cache` を import しない。外からはコマンドを通す。
4. `rent_or_buy/` に Claude の語（claude・token・cache・compact・keepalive と、日本語のキャッシュ・トークン・要約）を書かない。import の確かめだけでは、名前や文に書き込んだ Claude の知識を止められないため。止められるのは語だけで、Claude の単価を素の数で書き込んだ物は見つけられない。

試験が見つける形: 関数や条件の中の import（構文木を `ast` で全部たどる）、相対の import（`rent_or_buy` の中で 1 段まで）、`importlib.import_module`・`__import__`・`getattr` を通した import。見つけない形: 実行時に文字列を組み立てる import と、`exec`・`eval` の中の物。

フレームワークは入れない。import の向きを守る定番のツールは import-linter の layers の契約（[import-linter: layers](https://import-linter.readthedocs.io/en/stable/contract_types.html#layers)）で、Spring Modulith や Packwerk も同じ種類のツール。どれも数十のモジュールを持つコード向けで、ここは 2 つしかない。決まり 1（標準ライブラリだけを許す一覧）も決まり 3・4 もどのツールでも書けないので、入れても手元の試験は残る。モジュールが 4 つ以上になるか、アルゴリズムを別のリポジトリから使う人が出たら、import-linter に移す。

## 3. 中心: decide（`rent_or_buy/`）

### 3.1 入力

| キー | 型 | 意味 |
|---|---|---|
| rent | 数 | もう 1 回借りる費用 |
| buy | 数 | 買う費用 |
| spent | 数 | この回で借りるのに払った累計 |
| certain | 真偽 | 借りるのを終わらせる出来事が確かに来るか |
| miss | 数・既定 0 | 借りても買いを避けられなかった割合 |
| hazard | 数か null | 次の区間で終わりの出来事が来る確率 |
| deferred | 整数・既定 0 | 買うと決まった後に延期した回数 |
| defer_limit | 整数・既定 0 | 延期してよい回数 |
| forced | 真偽・既定 false | 呼ぶ側の強制の上限に着いたか |
| ask | 真偽・既定 false | 買う前に相手に聞くか（3.4） |
| answer | オブジェクト・省略可 | 2 回目の呼び出しで渡す相手の答え（3.4） |
| policy | 文字列・既定 fixed | 止め時の決め方の名前 |

回は、keepalive なら 1 つの待ち、compact なら前の compact から後。keepalive の終わりの出来事は次の本物の要求（会話が待っている結果や知らせ）で、`miss` は keepalive を送っていたのにキャッシュが切れた待ちの割合。

費用の単位は呼ぶ側が決める（キャッシュの層はドル）。形の違う入力（負の数・型の違い・知らないキー・形の違う `answer`）は黙って直さず、訳を付けて止める。

### 3.2 出力

```json
{"action": "rent", "reason": "within_buy_cost", "why": "...", "consult": false, "prep": null, "policy": "fixed"}
```

- `action`: `rent`（借りる）か `buy`（買う）。
- `consult`: 決め方が `buy` を出し、`forced` が false で、`ask` が true で、`deferred < defer_limit` で、`answer` が無いときだけ true。呼ぶ側は相手に聞いて、もう 1 回呼ぶ（3.4）。
- `prep`: 相手が進めると答えたときの準備の情報（compact なら焦点。要約に残す話題を指す 1 行）。それ以外は null。
- `reason`: 機械の読む短いキー。`within_buy_cost`・`reached_buy_cost`・`hazard_above_ratio`・`hazard_below_ratio`・`no_hazard`・`forced`・`defer_limit_reached`・`consult_go`・`consult_deferred`・`consult_unreadable`・`unknown_policy_fallback`。
- `why`: 人が読む英語の理由。
- `policy`: 実際に使った決め方。

決め方の関数は `(action, reason, why)` を返す。プラグインの版は、キャッシュの層が出力に足す（4.4）。

### 3.3 決め方

決め方は名前で表から引き、呼ぶ側が自分の物を足せる（`register`）。知らない名前なら `fixed` で決め、`why` にそう書く。

`fixed`（最初の版の唯一の決め方）は決定的な規則。買いのうち、借りることで避けられる分は `(1 - miss) * buy`。もう 1 回借りても累計がそれを下回る間（`spent + rent < (1 - miss) * buy`）だけ借りる。

- `certain` が true なら、この規則だけで決める。借り賃が一定で `miss = 0` なら、`K = ceil(rho) - 1` 回借りてから買う（`rho = buy / rent`）。上限の証明: 終わりの出来事が `t` 区間の後に来るとする。`t <= K` なら費用は `t * rent` で、これが最適。そうでなければ `t >= K + 1 >= rho` なので、後から見た最適は `buy` で、費用は `K * rent + buy < buy + buy`。よって費用はいつも最適の 2 倍未満で、これは ski rental の決定的な規則の古典的な上限（[Wikipedia](https://en.wikipedia.org/wiki/Ski_rental_problem)）。`tests/test_core.py` が多くの値段と長さで確かめる。
- `rho` が整数でないとき、最良の決定的な規則は 1 回早く止める場合とも比べて、比の小さい方を採る。`fixed` はこの比べをしない。差は借り 1 回分で、どちらも 2 倍未満に収まり、compact の借り賃は回ごとに変わって回数で数えられないため。累計を比べる 1 つの規則で両方の場面を扱う。
- compact も同じ規則で、前の compact から余分に読んだ額（`spent`）が compact 1 回の費用（`buy`）に届いたら compact する。
- `certain` が false なら、`hazard` が渡され、`hazard > rent / ((1 - miss) * buy)` で、かつ上の規則で借りられる間だけ借りる。比の確かめは、もう 1 回借りる費用と、それで平均して浮く額を比べる物（確率 `hazard` で次の区間に出来事が来て、避けられる分の買いが浮く）。出来事が来そうでも、累計の上限は外さない。`hazard` が無ければ買う。

後の版で足す決め方（最初の版には無い）:

- `random`: 買う時点を確率で選ぶ。期待の費用は最適の `e / (e - 1) ≈ 1.58` 倍以下で、ski rental の確率的な規則の上限（[Wikipedia](https://en.wikipedia.org/wiki/Ski_rental_problem)）。乱数の種は判断の記録に残す。
- `learned`: 判断の記録から待ちの長さや残りの要求の数を見込み、見込みをどれだけ信じるかを付けて止め時を決める（予測つきの ski rental: [Purohit, Svitkina, Kumar, NeurIPS 2018](https://proceedings.neurips.cc/paper/2018/hash/73a427badebe0e32caa2e1fc7530b7f3-Abstract.html)）。

どの決め方にも、中心が次の 2 つを重ねる。

- 強制の上限: `forced` が true なら、決め方によらず `buy`（`reason` は `forced`。聞かない）。compact では、Claude Code の自動の compact より手前に呼ぶ側が置く線に当たる。
- 延期の上限: 決め方が `buy` を出し、`ask` が true で `deferred < defer_limit` なら、相手に聞く（3.4）。「今は待って」の答えなら `rent`。上限に着いたら、聞かずに買う（`defer_limit_reached`）。延期 1 回ごとに最悪の場合は最適の 2 倍より悪くなりうる。その幅は呼ぶ側が `defer_limit` で抑える。

### 3.4 問い合わせ口

買う前に相手（compact なら、会話を要約されるエージェント）に聞く口。中心は相手が誰かを知らない。

- 関数として呼ぶとき: `decide(inputs, consult=fn)`。中心は聞くべきとき（3.2 の `consult: true` の条件）だけ `fn` を呼ぶ。返事は次のどれか。
  - `{"go": true, "prep": {...}}`: 進める。`prep` はそのまま出力に渡す（compact なら焦点）。
  - `{"go": false, "why": "..."}`: 延期する。
  - 例外か、形の違う返事: 聞かなかったのと同じに扱い、買う（`consult_unreadable`）。
  `fn` を渡さなければ、コマンドと同じく `consult: true` を返す。
- コマンドとして呼ぶとき: 関数を渡せないので 2 回に分ける。1 回目は `{"action": "buy", "consult": true}` を返し、呼ぶ側が相手に聞いて、答えを `answer` に入れてもう 1 回呼ぶ。延期したら、呼ぶ側は次の回から `deferred` を 1 つ足して渡す。中心は状態を持たないまま。コマンドに渡した `answer` の形が違うときは、黙って買いにせず入力の誤りとして止める（買いにするのは、関数の返事の形が違うときだけ）。

### 3.5 3 つ以上の手（後の版）

keepalive を送る時刻の手は、実は 3 つある。送る（借りる）、compact する（今払って、後の借り賃を下げる）、止める（買う）。手が 3 つ以上ある問題は multislope ski rental と呼ばれる（[Lotker, Patt-Shamir, Rawitz, "Rent, Lease or Buy", STACS 2008](https://arxiv.org/abs/0802.2832)）。compact で文脈が縮むと keepalive 1 本の値段が下がるので、ちょうどこの形になる。最初の版は手を 2 つにし、手の一覧を入力（`options`）で受ける形は、判断の記録で効くと分かってから足す。

### 3.6 判断の記録

中心の関数が、判断ごとに JSON Lines を 1 行足す。中身を見ないので、Claude を知らない。

- ファイルは呼ぶ側が決める。コマンドの既定は `<キャッシュのフォルダ>/decisions.jsonl` で、`RENT_OR_BUY_RECORD` で置き場を替え、`off` で止める。
- 記録は増え続けるので上限を持つ。10 MB を超えたら `decisions.1.jsonl` に名前を替えて新しく始め、古いファイルは 1 つだけ残す。
- 書けない（フォルダが無い・権限が無い）ときも判断は出し、出力の `record` に訳を書く。

## 4. キャッシュの層（`prompt_cache/`）

### 4.1 値段

手本は ccusage（Claude Code の会話の記録から使った額を出すツール。同じ記録を読み、値段とモデル名の同じ問題を解いている）。ccusage は LiteLLM の値段表の写しを本体に埋め込み、動くときに最新の表を取りに行き、取れなければ写しで計算する（[ccusage の pricing.rs](https://github.com/ryoppippi/ccusage/blob/main/rust/crates/ccusage-core/src/pricing.rs) の `load_with_overrides`）。rent-or-buy も同じ形にする。

- 同梱の写し: `prompt_cache/snapshot.json`。[LiteLLM の値段表](https://raw.githubusercontent.com/BerriAI/litellm/main/model_prices_and_context_window.json)から、Anthropic に直に繋ぐときの項目（名前が `claude-` で始まり、提供元の前置きが無い物）の、下のフィールドだけを残した物。写しには、取った LiteLLM の commit と日付を書く。
- 使うフィールド（1 トークンあたりのドル）: 入力 `input_cost_per_token`、5 分のキャッシュの書き込み `cache_creation_input_token_cost`、1 時間のキャッシュの書き込み `cache_creation_input_token_cost_above_1hr`、キャッシュの読み `cache_read_input_token_cost`、出力 `output_cost_per_token`。要求の大きさで値段が上がるモデル（10 万トークン超）は、`..._above_100k_tokens` のフィールドも持つ。値は写しを取ったときに [Anthropic の料金表](https://platform.claude.com/docs/en/about-claude/pricing)と照合した。
- 最新: LiteLLM の main ブランチから 1 日に 1 回まで取り、`<キャッシュのフォルダ>/latest.json` に控える。ccusage は人がときどき打つので毎回取るが、この部品は keepalive のたびに裏で呼ばれるので、1 日 1 回までにする。取った項目は確かめ（5 つの単価が正の有限の数で、読み < 入力 < 書き込みの順か。段のフィールドは正の有限の数で、基の単価以上か）、外れた項目やフィールドは捨てる。2 回の取得（commit と表）は合わせて 5 秒まで。どんな失敗でも写しで計算する。最新の値段は最適化で、判断を止めない。控えた最新の表が写しより古いか 7 日より前なら使わず、出力に `prices.latest_skipped: "stale"` と書く。`RENT_OR_BUY_OFFLINE=1` なら取りに行かない（ccusage の `--offline` に当たる）。
- 上書き: 値段のファイル（置き場は `RENT_OR_BUY_PRICES`）と、呼ぶときの `prices` のキーが最後に重なり、勝つ。
- 写しを新しくする: 保守する人が `bin/rent-or-buy snapshot` を打つ。ccusage は CI が毎日 commit して写しを新しくする（[update-pricing.yaml](https://github.com/ryoppippi/ccusage/blob/main/.github/workflows/update-pricing.yaml)）。ここで手で打つのは、変更を取り込むときに版を上げるリポジトリでは、自動の commit とぶつかるため。
- 出力の `prices` に、どの層の値段で計算したか（`snapshot`・`latest`・`override`）と出どころ（LiteLLM の commit か取った日）を書く。

データの所在の地域を指定する料金（`inference_geo`、1.1 倍）と Fast mode は、どのフィールドにも同じ倍率で掛かる（Anthropic の料金表）。判断は値段の比だけで決まるので、最初の版はどちらも入れない。

### 4.2 実測の値と既定

`prompt_cache/prices.toml` に、LiteLLM に無い値を置く。どれも呼ぶ側が上書きできる。

- keepalive: 1 本でキャッシュに 380 トークン書き、5 トークン出力する。1 つの keepalive の文で測った値で、文が違えば変わる。
- keepalive: キャッシュが切れる 60 秒前を余裕 `m` とする（5 分のキャッシュなら 4 分おきに送る）。今ある keepalive のプラグインの既定の間隔 240 秒に合わせた（[cache-keepalive](https://www.claudepluginhub.com/plugins/yujiachen-y-cache-keepalive-plugins-cache-keepalive)）。要求が実際にどれだけ遅れて出るかを判断の記録で見てから詰める。
- compact: compact の後の文脈 25,000 トークン、要約 5,000 トークン。例の値で、測った値ではない。

### 4.3 モデル名

会話の記録に書かれるモデル名は、値段表の名前と同じとは限らない（クラウドの前置き、1M 文脈の印 `[1m]`、日付付きの版、社内の中継が付けた名前）。ccusage はそのまま照合し、次に小文字にして `.` と `@` を `-` に替え、最後に、渡された名前が含む表の名前のうち一番長い物を採る（曖昧な照合）。使う人は `CCUSAGE_MODEL_ALIASES` で対応表を足せる（[ccusage の model_aliases.rs](https://github.com/ryoppippi/ccusage/blob/main/rust/crates/ccusage-core/src/model_aliases.rs)）。rent-or-buy は次の順にする。

1. 使う人の対応表（`RENT_OR_BUY_MODEL_ALIASES`。`名前=モデル` をカンマで区切るか JSON のオブジェクト。ccusage と同じ形）でそのまま引く。
2. 正規化する: 小文字にし、末尾の `[...]` を削り、`claude-` より前（`us.anthropic.` などの前置き）を削り、`.` と `@` を `-` に替え、末尾の日付（`-20261001`）と版（`-v1:0`）を削る。その名前で値段表と対応表を引く。
3. どれにも当たらなければ「知らないモデル」（終了コード 3）を返す。呼ぶ側は決め打ちの数で動く。当たらなかった名前は判断の記録に残り、写しか対応表に足す手がかりになる。

曖昧な照合はしない。ccusage は過去の使用額を足し合わせるので、近い値段で数えても害が小さい。この部品は値段から自動の判断を出すので、別のモデルの値段を拾うと判断がずれる。

正規化の試験は実物の名前を見本にする。Anthropic に直に繋いだ会話の記録の名前（`claude-opus-5-5`）と、LiteLLM の表のクラウドの項目（`us.anthropic.claude-opus-5-5` など）。ほかの環境の名前は、見つかったら見本に足す。

### 4.4 翻訳

翻訳は、場面の事実を中心の入力に直す。値段は 1 トークンあたりで、`read` はキャッシュの読みの値段、`write` は使うキャッシュの寿命に合う書き込みの値段。

keepalive:

- 受ける物: モデル、キャッシュの寿命（300 か 3600 秒）、文脈の大きさ、この待ちで借りに払った累計（`spent`）、待っている出来事が確かに来るか（分かれば `hazard` と `miss` も）、最後の要求の時刻。keepalive 1 本が書くトークン数と出力のトークン数、余裕 `m` の既定は 4.2。
- 当てはめ: 借りる = keepalive 1 本 = `read * context + write * keepalive_write + output * keepalive_output`。買う = キャッシュが切れたときに余分にかかる額 = `(write - read) * context`。
- 返す物: 中心の出力に、`next_at`（次の keepalive を送る時刻）・`rent`・`buy`・`prices`・`version` を足した物。`turn_end_at` を渡せば、判断の記録のためにそのまま返す。keepalive の `buy` は止めることなので、問い合わせはしない。
- `next_at` = 最後の要求の時刻 + 寿命 - `m`。キャッシュの寿命は要求の開始から数える（[Claude Code の prompt caching](https://code.claude.com/docs/en/prompt-caching)）。記録の時刻は要求が手元を出る前に付くので、この数え方は安全側に寄る。ターンの終わりから数えると、答えを作る時間まで数えてしまう。

compact:

- 受ける物: モデル、compact が書くキャッシュの寿命、文脈の大きさ、前の compact の後の文脈の大きさ（既定は 4.2）、要約の大きさ、前の compact から余分に読んだ額（`spent`）、キャッシュが温かいか、問い合わせ 1 往復の費用、中心の `forced`・`ask`・`deferred`・`defer_limit`・`answer`。
- 当てはめ: 借りる = この要求で余分に読む額 = `(context - post_compact_context) * read`（負なら 0）。買う = `post_compact_context * write + summary * output + consult_cost`。`certain` は true。
- キャッシュが温かいか冷えているかは、全部の書き込みが同じ寿命なら判断を変えない。会話のキャッシュが 1 時間で compact が 5 分の環境では、冷えているなら早めに compact する方が得になりうるが、測った値が無いので、最初の版は記録に残すだけにする。
- 返す物: 中心の出力（`buy` なら今 compact する）に、`rent`・`buy`・`prices`・`version` を足した物。呼ぶ側は `rent` を累計に足し、次の回に渡す。

10 万トークンを超えると上がる値段は、要求の大きさで選ぶ。keepalive の読み・書き込み・出力は文脈の大きさで、compact の書き込みは compact の後の大きさで、要約の出力は compact の前の文脈の大きさで選ぶ。

### 4.5 会話の記録の読み取り

呼ぶ側が数えなくてよいよう、会話の記録（Claude Code の JSON Lines のファイル）から事実を出す。コマンドでは `--transcript FILE` で渡す。

- 文脈の大きさ: 最後の応答の `message.usage` の `input_tokens`・`cache_read_input_tokens`・`cache_creation_input_tokens` の和。1 つの応答は内容のブロックごとに行が分かれ、同じ `message.id` を持つので、id でまとめる。
- モデル: 最後の応答の `message.model`。
- 最後の要求の時刻: `"type": "api-request"` で `querySource` が `repl_main_thread`（会話の本体の要求だけ）の最後の行の `timestamp`（UTC の ISO 8601）。
- compact の後の文脈: `"subtype": "compact_boundary"` の最後の行の `compactMetadata.postTokens`。
- 前の compact から余分に読んだ額: その後の応答ごとに `(context - post_compact_context) * read`（負なら 0）を足した物。
- この形は Claude Code 2.1.310 の記録で確かめた物で、文書に書かれた形ではない。形の違う行は飛ばして数える（出力の `transcript.skipped_lines`）。値が 1 つも読めなければ「記録を読めない」を返し、呼ぶ側は決め打ちの数で動く。
- 場面に要る事実（モデルと文脈の大きさ、keepalive なら最後の要求の時刻も）が記録にも標準入力にも無いとき（compact の直後でまだ応答が無いときなど）、コマンドは既定で埋めず、終了コード 4 で終わる。文脈の大きさを compact の後の大きさで代えることもしない。モデルも分からないため。

## 5. コマンド

`bin/rent-or-buy`（Claude Code は、有効なプラグインの `bin/` を Bash のツールの PATH に入れる）。標準入力に JSON のオブジェクトを受け、標準出力に JSON のオブジェクトを 1 つ返す。Python 3.11 以上で、標準ライブラリだけを使う（Claude Code のプラグインには、使う人の機械に pip の依存を入れる段が無いため）。

- `rent-or-buy decide`: 中心をそのまま呼ぶ。
- `rent-or-buy keepalive [--transcript FILE]`: 4.4 の keepalive。記録を渡せば、モデル・文脈の大きさ・最後の要求の時刻を記録から埋める（標準入力の値が勝つ）。
- `rent-or-buy compact [--transcript FILE]`: 4.4 の compact。記録を渡せば、モデル・文脈の大きさ・compact の後の大きさ・余分に読んだ額を記録から埋める。
- `rent-or-buy prices MODEL`: 正規化した名前と、使う値段と、その出どころ（調べるとき用）。
- `rent-or-buy snapshot`: LiteLLM の main ブランチから同梱の写しを作り直す（保守する人が打つ）。

終了コード: 0 は判断できた、1 は `snapshot` の失敗、2 は入力の形の誤り、3 は知らないモデル、4 は記録を読めない。0 以外でも、出力は `{"error": "<キー>", "why": "<英語>"}`。`decide`・`keepalive`・`compact` の失敗は、入力ごと判断の記録に足す。知らないモデル名を集めるため（`prices` の失敗は記録しない）。出力の `version` は、プラグインの `plugin.json` の `version`。

## 6. 判断の記録のフィールド

全部の行: 時刻・場面（`decide`・`keepalive`・`compact`）・入力・出力。キャッシュの層の行は `prices` と `version` も持ち、式と部品のずれを後で見つけられるようにする。

- keepalive の行は、まだ見積もりのままの値を測るために置く。
  - 時刻: 最後の要求と、判断した時（行の時刻）、呼ぶ側が渡せばターンの終わり。送った要求が実際に出た時刻は、後で会話の記録から埋める。
  - ここから、最後の答えを作る時間（ターンの終わり - 最後の要求）と、判断から要求が出るまでの遅れが出る。
  - keepalive の後のキャッシュの書き込みが大きければ、外れと数える。多くの待ちで集めると、余裕 `m` ごとの外れの割合 `q(m)` が出る。
- compact の行: キャッシュが温かかったか冷えていたか、前と後の文脈の大きさ、compact の要求と次の要求の使用量（どの寿命の書き込みの値段だったかを含む）。冷えた compact と温かい compact を実測で比べるため。
- 結果のフィールド（外れたか、次に何を書いたか、要求がいつ出たか）は、判断の時点では分からない。部品は状態を持たないので、後で会話の記録から埋めるツールを、`m` を詰める段（10 の段 4）で作る。

## 7. 呼ぶ側

部品は指針を決めない。会話を回す仕組みに部品をつなぐ呼ぶ側は、次のようにする。元のリポジトリの最初の呼ぶ側の計画がこれ。

- keepalive: `next_at` に送り、何本まで送るかを中心の `action` に替える。送る直前に、待っている出来事がもう届いていないかを見て、届いていれば送らない（見ないと、待っていた結果と同じ秒に keepalive を送ることがある）。
- compact:
  1. 判断するのは、待ちの間で入力フィールドが空のとき、つまり keepalive の時刻だけ。その時刻には先に compact の判断を聞き、compact するなら keepalive は送らない（compact の要求がキャッシュを読むので、キャッシュは保たれる）。しないなら keepalive の判断を聞く。
  2. compact の判断が `consult: true` を返したら、その回の keepalive の文を問いに替える。問いは「compact する時です。残す焦点を 1 行で返すか、今は困るなら skip: と訳を返してください。ツールは使わないでください」の形。要求は 1 本のままで、足すのは数十トークン。
  3. 答えを会話の記録の最後の応答から読み、2 回目の呼び出しの `answer` に入れる。進めるなら、呼ぶ側が会話に `/compact <焦点>` を打つ。skip なら延期と数え、上限を超えたら焦点なしで compact する。
  4. 部品があるときは、決め打ちのしきい値（「10 万トークンを超えたら compact」など）を中心の `action` に替え、しきい値は部品が無いときの代わりにだけ残す。
- Claude Code の自動の compact: 歯止めとして残すが、その線（設定 `autoCompactWindow`）を文脈の上限の近くまで上げる。自動の compact は時を選べず、ターンの途中でも動くので、ふだんの道にはしない。
- 部品の見つけ方: Claude Code が入れたプラグインの控え（`installed_plugins.json`）から `rent-or-buy` を引き、その `bin/rent-or-buy` を起動する。無いか 0 以外で終わったら、決め打ちの数で動く。

## 8. 置き場と版

```
rent-or-buy/
  .claude-plugin/plugin.json
  README.md, CHANGELOG.md
  docs/design.md, docs/design.ja.md   この文書と訳
  bin/rent-or-buy             コマンド（5）
  rent_or_buy/                アルゴリズム（3）
    __init__.py               公開する名前: decide, InputError, register, append_record
    core.py                   decide、強制の上限、延期、問い合わせ口
    policies.py               決め方の表と fixed
    record.py                 判断の記録を足す・上限で切り替える
  prompt_cache/               キャッシュの層（4）
    __init__.py
    prices.py                 写し・最新・上書きを重ねて単価を引く
    names.py                  モデル名の正規化
    translate.py              keepalive と compact の翻訳
    transcript.py             会話の記録の読み取り
    snapshot.json             LiteLLM の値段表の写し
    prices.toml               実測の値と既定
  tests/
    test_core.py              fixed の約束（9）
    test_translate.py         翻訳・会話の記録・コマンドを、ネットワーク無しで
    test_boundary.py          境目の 4 つの決まり（2.1）
    test_names.py             モデル名の正規化を実物の見本で
    test_docs.py              英語と日本語の設計書がそろっているか
```

- スキルは置かない。呼ぶのはプログラムで、会話の中から使う場面がまだ無い。
- 部品の版はタグでなく commit の SHA で固定する（元のリポジトリはタグを作らない）。

## 9. 試験

試験は部品の約束だけを見る。

- 借り賃が一定で延期が無ければ、`fixed` の費用は、どの待ちの長さでも後から見た最適の 2 倍未満。
- 2 回に分けた問い合わせ: 1 回目が `consult: true`、2 回目が `buy`（進める）か `rent`（延期）。
- 境目の 4 つの決まり（2.1）。
- モデル名の正規化（4.3）を実物の見本で。
- 設計書と訳の見出しの数と並びが同じで、引いている URL も同じ。

## 10. 前例と段

同じことをするツールは見つからなかった（web 検索の範囲）。

- keepalive: 間隔の損益分岐の式や、keepalive のプラグイン（240 秒おき・7 本まで）はあるが、どれも決め打ちの数で、止め時は決めない。
- compact: OpenHands・Codex・Cline・Aider・Letta は、どれも大きさか割合のしきい値で compact する。費用の式で時を選ぶ物は見つからなかった。
- 推論サーバーのキャッシュの保持: Continuum は期待の得で保持の時間を決めるが、対象は GPU のメモリで、最悪の場合の上限は無い。費用で決める保持の時間を、最悪 2 倍の ski rental とみる論文がある（[arXiv:2309.03521](https://arxiv.org/pdf/2309.03521)）。
- 値段とモデル名は ccusage に倣った（4.1・4.3）。

段。各段の効き目を判断の記録で測ってから次へ進む。

1. 設計（この文書）。
2. 中心・キャッシュの層・コマンド・記録と、呼ぶ側への keepalive のつなぎ込み。
3. 呼ぶ側の compact の指針（問い合わせ・skip の上限・自動の compact の線を上げる）。
4. 結果のフィールドを埋めるツール、`m` を詰めること、ステータスラインの表示。
5. `random`・`learned`・3 つ以上の手、キャッシュの寿命（5 分か 1 時間）の選び方、「前の会話を続けるか新しく始めるか」の翻訳。

最初の版の範囲は段 2 と 3。
