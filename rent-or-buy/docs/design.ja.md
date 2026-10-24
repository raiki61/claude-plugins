# rent-or-buy の設計

rent-or-buy は、費用を渡すと `rent`（もう少し払う）か `buy`（1 回で払う）を返す Claude Code のプラグインで、会話の中の keepalive と compact の 2 つの判断に使う（1 で詳しく書く。keepalive はキャッシュが切れないよう送る短い要求、compact は会話を要約して縮める Claude Code の操作）。呼ぶ側は、このコマンドを起動して答えに従うプログラム（スクリプト・フック・ほかのプラグイン）。この文書は rent-or-buy の設計書の日本語訳。正本は英語の [design.md](design.md) で、2 つが食い違うときは英語の版が正しい。2 つのファイルは見出しの数と並びが同じで、`tests/test_docs.py` がそれを確かめる。

読む人: プラグインを保守する人、呼ぶ側を書く人、プラグインをこのリポジトリの外へ切り出す人。どれでもなければここで読み終えてよい。コマンドの呼び方は [README.md](../README.md)（英語）にあり、この文書はなぜその作りなのかを書く。

## 1. 解く問題

Claude Code の会話には、少しずつ払い続ける（借りる）か、まとめて 1 回払う（買う）かを、いつまで要るか分からないまま決める場面が 2 つある。

- keepalive: 会話が何か（裏の処理の結果や知らせ）を待っている間、プロンプトのキャッシュは最後の要求から 5 分か 1 時間で切れる。切れる前に短い要求を送ればキャッシュは保たれる（借りる: 要求 1 本）。止めれば、次の本物の要求が文脈の全体をキャッシュに書き直す（買う: その書き直しで余分にかかる額）。
- compact: 会話を要約して文脈を縮める Claude Code の操作。大きな文脈のままの要求は、compact した後より多くのキャッシュを毎回読む（借りる: この要求で余分に読む額）。compact は要約とキャッシュの書き直しの費用を 1 回払う（買う）。

この形の問題は ski rental（rent-or-buy problem とも呼ぶ）と呼ばれる（[Wikipedia: Ski rental problem](https://en.wikipedia.org/wiki/Ski_rental_problem)）。先の見込みが無いときのふつうの答えは決め打ちの数で、N 秒おきに M 本まで keepalive を送る、トークン数がしきい値を超えたら compact する、といった形になる。この数は、値段・モデル・文脈の大きさが変わっても動かない。

rent-or-buy は、この判断を費用だけから出す小さな部品。状態を持たず、呼ぶ側のプロセスを知らず、JSON を渡して JSON を受け取るコマンドとして呼ぶ。

## 2. 層

1 つのプラグインに Python のモジュール（パッケージ。フォルダ単位で数え、中のファイルは数えない）を 2 つ置く（モジュラモノリス。1 つにまとめて配り、中の境目は試験で守る）。

```
  呼ぶ側（スクリプト・フック・ほかのプラグイン）
  │  コマンド bin/rent-or-buy を起動する（標準入力に JSON、標準出力に JSON）。Python のモジュールは import しない
  ▼
  prompt_cache/   Claude のプロンプトキャッシュへの当てはめ（Claude の事実を素の費用に直す）
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

決まりごとに見る形: 決まり 1 と 2 は構文木を `ast` で全部たどるので、関数や条件の中の import も数える。決まり 1 は `import` と `from ... import` の文を見る（相対の import は同じフォルダのファイルを指す `from .x import y` の形だけで、`from ..x` は禁止）。決まり 2 は `rent_or_buy` に対する `__import__` と `getattr` も見る。決まり 3 は、プラグインの外の、プラグインを置いたリポジトリ（プラグインの 1 つ上のフォルダ）の Python のファイル全部で、import の文と `import_module("...")` を文字列として照合する。見ない形: `rent_or_buy/` の中の `importlib` や `__import__`（決まり 1）、`prompt_cache/` からの `importlib.import_module`（決まり 2）、実行時に文字列を組み立てる import、`exec`・`eval` の中の物。プラグインを単独のリポジトリに移したら、決まり 3 の照合先を新しいリポジトリに向け直す。

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
| hazard | 数か null・既定 null | 次の区間で終わりの出来事が来る確率 |
| deferred | 整数・既定 0 | 買うと決まった後に延期した回数 |
| defer_limit | 整数・既定 0 | 延期してよい回数 |
| forced | 真偽・既定 false | 呼ぶ側の強制の上限に着いたか |
| ask | 真偽・既定 false | 買う前に相手に聞くか（3.4） |
| answer | オブジェクト・省略可 | 2 回目の呼び出しで渡す相手の答え（3.4） |
| policy | 文字列・既定 fixed | 止め時の決め方の名前 |

区間は、続く 2 つの判断の間で、借りを 1 回払う間。`t` 区間は借り `t` 回に当たる。回は、keepalive なら 1 つの待ち、compact なら前の compact から後。keepalive の終わりの出来事は次の本物の要求（会話が待っている結果や知らせ）で、`miss` は keepalive を送っていたのにキャッシュが切れた待ちの割合。

`rent`・`buy`・`spent`・`certain` は必須で、ほかは省ける。数は有限で 0 以上、`miss` と `hazard` は 1 以下、整数のキーは整数、`policy` は文字列。

費用の単位は呼ぶ側が決める（キャッシュの層はドル）。形の違う入力（必須のキーが無い・知らないキー・型や範囲の違い・形の違う `answer`）は黙って直さず、訳を付けて止める。

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

決め方は名前で表から引き、アルゴリズムを import する Python のコードは自分の物を足せる（`register`）。コマンドを呼ぶ側は足せない。知らない名前なら `fixed` で決め、`why` にそう書く。

`fixed`（最初の版の唯一の決め方）は決定的な規則。買いのうち、借りることで避けられる分は `(1 - miss) * buy`。もう 1 回借りても累計がそれを下回る間（`spent + rent < (1 - miss) * buy`）だけ借りる。`spent` はここまで借りて払った額、`rent` は次の 1 回の借り賃。これを累計の上限と呼ぶ。コードは累計の上限を書いたとおりに比べ、`rent` で割る `rho = buy / rent` を求めないので、`rent = 0` でも壊れない。`miss = 1` なら右辺が 0 で、避けられる買いが無いので `buy`。（`rho` は証明にだけ出る。）

- `certain` が true なら、この規則だけで決める。借り賃が一定で `miss = 0` なら、`K = ceil(rho) - 1` 回借りてから買う（`rho = buy / rent`）。2 倍未満の上限の証明: 終わりの出来事が `t` 区間の後に来るとする。`t <= K` なら費用は `t * rent` で、これが最適。そうでなければ `t >= K + 1 >= rho` なので、後から見た最適は `buy` で、費用は `K * rent + buy < buy + buy`。よって費用はいつも最適の 2 倍未満で、これは ski rental の決定的な規則の古典的な上限（[Wikipedia](https://en.wikipedia.org/wiki/Ski_rental_problem)）。`tests/test_core.py` が多くの値段と長さで確かめる。
- `rho` が整数でないとき、候補がもう 1 つある。`K` 回でなく `K - 1` 回借りて止める規則。最良の決定的な規則は、この 2 つの候補のうち、最悪の場合の倍率（費用を最適で割った値）が小さい方を採る。`fixed` は常に `K` 回の規則を使い、この比べをしない。理由は 2 つ。2 つの候補の差は借り 1 回分で、最悪の倍率はどちらも 2 倍未満に収まる。もう 1 つは、compact の借り賃が回ごとに変わるので、1 回短くする元になる決まった回数 `K` が無いこと。累計を比べる 1 つの規則で両方の場面を扱う。
- compact も同じ規則で、前の compact から余分に読んだ額（`spent`）に、この要求で余分に読む額（`rent`）を足した額が、compact 1 回の費用（`buy`）に届いたら compact する。
- `certain` が false なら、`hazard` が渡され、`hazard > rent / ((1 - miss) * buy)` で、かつ上の規則で借りられる間だけ借りる。比の確かめは、もう 1 回借りる費用と、それで平均して浮く額 `hazard * (1 - miss) * buy` を比べる物（確率 `hazard` で次の区間に出来事が来て、避けられる分の買いが浮く）。借りるのが得なのは `rent < hazard * (1 - miss) * buy` の間だけで、これは比の確かめの式 `hazard > rent / ((1 - miss) * buy)` を移項した物。両方の確かめが通るときだけ借りる。出来事が来そうでも、累計の上限は外さない。`hazard` が無ければ買う。

後の版で足す決め方（最初の版には無い）:

- `random`: 買う時点を確率で選ぶ。期待の費用は最適の `e / (e - 1) ≈ 1.58` 倍以下で、ski rental の確率的な規則の上限（[Wikipedia](https://en.wikipedia.org/wiki/Ski_rental_problem)）。乱数の種は判断の記録に残す。
- `learned`: 判断の記録から待ちの長さや残りの要求の数を見込み、見込みをどれだけ信じるかを付けて止め時を決める（予測つきの ski rental: [Purohit, Svitkina, Kumar, NeurIPS 2018](https://proceedings.neurips.cc/paper/2018/hash/73a427badebe0e32caa2e1fc7530b7f3-Abstract.html)）。

どの決め方にも、中心が次の 2 つを重ねる。

- 強制の上限: `forced` が true なら、決め方によらず `buy`（`reason` は `forced`。聞かない）。compact では、Claude Code の自動の compact より手前に呼ぶ側が置く線に当たる。
- 延期の上限: 決め方が `buy` を出し、`ask` が true で `deferred < defer_limit` なら、相手に聞く（3.4）。「今は待って」の答えなら `rent`。上限に着いたら、聞かずに買う（`defer_limit_reached`）。延期した借りは、規則が買えと言った時点より後に払うので、上の証明は当てはまらない。延期 1 回ごとに最悪の場合へ借り 1 回分が足され、最適の 2 倍を超えうる。その増えは呼ぶ側が `defer_limit` で抑える。

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

- ファイルは呼ぶ側が決める。コマンドの既定は `<キャッシュのフォルダ>/decisions.jsonl` で、キャッシュのフォルダは `RENT_OR_BUY_CACHE_DIR` が無ければ `~/.cache/rent-or-buy`。`RENT_OR_BUY_RECORD` で置き場を替え、`off` で止める。
- 記録は増え続けるので上限を持つ。1 行を足す前にファイルが 10 MiB を超えていたら、 `decisions.1.jsonl` に名前を替えて新しく始め、古いファイルは 1 つだけ残す。
- 書けない（フォルダが無い・権限が無い）ときも判断は出し、出力の `record` に訳を書く。

## 4. キャッシュの層（`prompt_cache/`）

### 4.1 値段

手本は ccusage（Claude Code の会話の記録から使った額を出すツール。同じ記録を読み、値段とモデル名の同じ問題を解いている）。ccusage は LiteLLM の値段表の写しを本体に埋め込み、動くときに最新の表を取りに行き、取れなければ写しで計算する（[ccusage の pricing.rs](https://github.com/ryoppippi/ccusage/blob/main/rust/crates/ccusage-core/src/pricing.rs) の `load_with_overrides`）。rent-or-buy も同じ形にする。

- 同梱の写し: `prompt_cache/snapshot.json`。[LiteLLM の値段表](https://raw.githubusercontent.com/BerriAI/litellm/main/model_prices_and_context_window.json)から、Anthropic に直に繋ぐときの項目（名前が `claude-` で始まり、提供元の前置きが無い物）の、下のフィールドだけを残した物。写しには、取った LiteLLM の commit と日付を書く。
- 使うフィールド（1 トークンあたりのドル）: 入力 `input_cost_per_token`、5 分のキャッシュの書き込み `cache_creation_input_token_cost`、1 時間のキャッシュの書き込み `cache_creation_input_token_cost_above_1hr`、キャッシュの読み `cache_read_input_token_cost`、出力 `output_cost_per_token`。要求の大きさで値段が上がるモデル（10 万トークン超）は、`..._above_100k_tokens` のフィールド（単価の段階）も持つ。値は写しを取ったときに [Anthropic の料金表](https://platform.claude.com/docs/en/about-claude/pricing)と照合した。
- 最新: LiteLLM の main ブランチから 1 日に 1 回まで取り、`<キャッシュのフォルダ>/latest.json` に控える（`<キャッシュのフォルダ>` は 3.6 で決めた物）。1 日 1 回の制限は印のファイル `<キャッシュのフォルダ>/latest.tried` の更新時刻で掛け、印は取る前に付けるので、取れなかったときも 24 時間は取り直さない。使える項目が 1 つも無ければ何も書かない。ccusage は人がときどき打つので毎回取るが、この部品は keepalive のたびに裏で呼ばれるので、1 日 1 回までにする。取った項目は確かめ（5 つの単価、つまり入力・5 分の書き込み・1 時間の書き込み・読み・出力が正の有限の数で、読み < 入力 < 書き込みの順か。単価の段階（10 万トークン超）のフィールドは正の有限の数で、基の単価以上か）、外れた項目やフィールドは捨てる。2 回の取得（LiteLLM の最新の commit の hash〔表の出どころとして控える〕と、値段表そのもの）は合わせて 5 秒まで。どんな失敗でも写しで計算する。最新の値段は最適化で、判断を止めない。控えた最新の表が写しより古いか、取ってから今まで 7 日を超えていれば使わず、出力に `prices.latest_skipped: "stale"` と書く。`RENT_OR_BUY_OFFLINE=1` なら取りに行かない（ccusage の `--offline` に当たる）。
- 上書き: 値段のファイル（置き場は `RENT_OR_BUY_PRICES`）と、呼ぶときの `prices` のキーが最後に重なり、勝つ。
- 写しを新しくする: 保守する人が `bin/rent-or-buy snapshot` を打つ。ccusage は CI が毎日 commit して写しを新しくする（[update-pricing.yaml](https://github.com/ryoppippi/ccusage/blob/main/.github/workflows/update-pricing.yaml)）。ここで手で打つのは、同梱の値段が変わればプラグインの版も変わるべきで、人の手を通らない commit は版を出さずに値段を変えてしまうため。
- 出力の `prices` に、どの層の値段で計算したか（`snapshot`・`latest`・`override`）と出どころ（LiteLLM の commit か取った日）を書く。

データの所在の地域を指定する料金（`inference_geo`、1.1 倍）と Fast mode（Claude Code の速度の設定で、料金表に倍率が書かれている）は、どのフィールドにも同じ倍率で掛かる（Anthropic の料金表）。判断は値段の比だけで決まるので、最初の版はどちらも入れない。

### 4.2 実測の値と既定

`prompt_cache/prices.toml` に、LiteLLM に無い値を置く。どれも呼ぶ側が上書きできる。

- keepalive: 1 本でキャッシュに 380 トークン書き、5 トークン出力する。1 つの keepalive の文で測った値で、文が違えば変わる。測ったときの文は残していないので、自分の文で測り直して値を渡す。
- keepalive: キャッシュが切れる 60 秒前を余裕 `m` とする（5 分のキャッシュなら 4 分おきに送る）。今ある keepalive のプラグインの既定の間隔 240 秒に合わせた（[cache-keepalive](https://www.claudepluginhub.com/plugins/yujiachen-y-cache-keepalive-plugins-cache-keepalive)）。要求が実際にどれだけ遅れて出るかを判断の記録で見てから詰める。
- compact: compact の後の文脈 25,000 トークン。例の値で、測った値ではない。
- compact: 要約の出力 9,000 トークン。見積もりの値で、要約の要求の出力は記録に残らないので測れない（要約の要求は [Claude Code の prompt caching](https://code.claude.com/docs/en/prompt-caching#compacting-the-conversation) が書いている）。2 つの部分の和にした:
  - 要約の本文: 8 日分の会話の記録の compact の要約（2026-10-25 までの 8 日に書かれた記録のファイルの 613 件。`isCompactSummary` の行）は、中央 13,279 字。大半が英語（日本語の字の割合の中央 8%）。字をトークンに直す率は、同じ記録の、本文だけの応答（`output_tokens` が本文だけの量になる。4,304 件）から測った。日本語でない字 1 字が 0.364 トークン、日本語の字 1 字が 1.118 トークン（外れ方の中央 3.5%）。要約の本文は中央で 5,800 トークン（四分位で 4,800〜7,000）。
  - 下書き: Claude Code の compact の指示文は、`<summary>` の前に `<analysis>` を書かせ、`<analysis>` を会話から捨てる。大きさは見えない。無い場合と本文と同じ長さの場合の間をとって、本文の半分（3,000 トークン）と見る。
  - 会話ごとにはしない: 会話の次の要約の大きさは前もって分からないので、固定の値にする（持ち主 2026-10-25）。会話の前の要約から次を当てると外れ方は中央 15%（340 組）で、全体の中央の固定では 22%。要約の大きさは、縮める前の文脈の大きさと連動しない（`preTokens` との相関 0.03）。

### 4.3 モデル名

会話の記録に書かれるモデル名は、値段表の名前と同じとは限らない（クラウドの前置き、1M 文脈の印 `[1m]`、日付付きの版、社内の中継が付けた名前）。ccusage はそのまま照合し、次に小文字にして `.` と `@` を `-` に替え、最後に、渡された名前が含む表の名前のうち一番長い物を採る（曖昧な照合）。使う人は ccusage の環境変数で対応表を足せる（[ccusage の model_aliases.rs](https://github.com/ryoppippi/ccusage/blob/main/rust/crates/ccusage-core/src/model_aliases.rs)）。rent-or-buy は次の順にする。

1. 使う人の対応表（`RENT_OR_BUY_MODEL_ALIASES`。`名前=モデル` をカンマで区切るか JSON のオブジェクト。ccusage と同じ形）でそのまま引く。
2. 正規化する: 小文字にし、末尾の `[...]` を削り、`claude-` より前（`us.anthropic.` などの前置き）を削り、`.` と `@` を `-` に替え、末尾の日付（`-20261001`）と版（`-v1:0`）を削る。その名前で値段表と対応表を引く。
3. どれにも当たらなければ「知らないモデル」（終了コード 3）を返す。呼ぶ側は決め打ちの数で動く。当たらなかった名前は判断の記録に残り、写しか対応表に足す手がかりになる。

曖昧な照合はしない。ccusage は過去の使用額を足し合わせるので、近い値段で数えても害が小さい。この部品は値段から自動の判断を出すので、別のモデルの値段を拾うと判断がずれる。

正規化の試験は実物の名前を見本にする。Anthropic に直に繋いだ会話の記録の名前（`claude-opus-5-5`）と、LiteLLM の表のクラウドの項目（`us.anthropic.claude-opus-5-5` など）。ほかの環境の名前は、見つかったら見本に足す。

### 4.4 翻訳

翻訳は、場面の事実を中心の入力に直す。値段は 1 トークンあたりで、`read` はキャッシュの読みの値段、`write` は使うキャッシュの寿命に合う書き込みの値段。

keepalive:

- 受ける物: モデル、キャッシュの寿命（300 か 3600 秒）、文脈の大きさ、この待ちで借りに払った累計（`spent`）、待っている出来事が確かに来るか（分かれば `hazard` と `miss` も）、最後の要求の時刻。keepalive 1 本が書くトークン数と出力のトークン数、余裕 `m` の既定は 4.2。
- 当てはめ: 借りる = keepalive 1 本 = `read * context + write * keepalive_write + output * keepalive_output`。買う = キャッシュが切れたときに余分にかかる額 = `(write - read) * context`。`keepalive_write` と `keepalive_output` は、呼ぶ側が別の値を渡さなければ 4.2 の 380 と 5 トークン。
- 返す物: 中心の出力に、`next_at`（次の keepalive を送る時刻）・`rent`・`buy`・`prices`・`version` を足した物。`turn_end_at` を渡せば、判断の記録のためにそのまま返す。keepalive の `buy` は止めることなので、問い合わせはしない。
- `next_at` = 最後の要求の時刻 + 寿命 - `m`。キャッシュの寿命は要求の開始から数える（[Claude Code の prompt caching](https://code.claude.com/docs/en/prompt-caching)）。記録の時刻は要求が手元を出る前に付くので、この数え方は安全側に寄る。ターンの終わりから数えると、答えを作る時間まで数えてしまう。

compact:

- 受ける物: モデル、compact が書くキャッシュの寿命、文脈の大きさ、前の compact の後の文脈の大きさ（`post_compact_context`。既定は 4.2）、要約の大きさ、前の compact から余分に読んだ額（`spent`）、キャッシュが温かいか、問い合わせ 1 往復の費用、中心の `forced`・`ask`・`deferred`・`defer_limit`・`answer`。
- 当てはめ: 借りる = この要求で余分に読む額 = `(context - post_compact_context) * read`（負なら 0）。買う = `post_compact_context * write + summary * output + consult_cost`。`certain` は true。`post_compact_context` は前の compact の後の大きさで、今回の compact の後の大きさの見積りに使う。
- キャッシュが温かいか冷えているかは、全部の書き込みが同じ寿命なら判断を変えない。会話のキャッシュが 1 時間で compact が 5 分の環境では、冷えているなら早めに compact する方が得になりうる（次の要求がどのみち文脈の全体を書き直すので、先に compact すればその書き直しが小さくなる）が、測った値が無いので、最初の版は記録に残すだけにする。
- 返す物: 中心の出力（`buy` なら今 compact する）に、`rent`・`buy`・`warm`（受けた値をそのまま）・`prices`・`version` を足した物。呼ぶ側は `rent` を累計に足し、次の回に渡す。

10 万トークンを超えると上がる値段は、要求の大きさで選ぶ。keepalive の読み・書き込み・出力は文脈の大きさで、compact の書き込みは compact の後の大きさで、要約の出力は compact の前の文脈の大きさで選ぶ。

### 4.5 会話の記録の読み取り

呼ぶ側が数えなくてよいよう、会話の記録（Claude Code の JSON Lines のファイル）から事実を出す。コマンドでは `--transcript FILE` で渡す。

- 応答: `"type": "assistant"` の行。ただし、サイドチェーンの行（`isSidechain` が真）、モデル名が `<` で始まる行（`<synthetic>` など、本物の応答でない物）、文脈が 0 の行は除く。
- 文脈の大きさ: 最後の応答の `message.usage` の `input_tokens`・`cache_read_input_tokens`・`cache_creation_input_tokens` の和。1 つの応答は内容のブロックごとに行が分かれ、同じ `message.id` を持つので、id でまとめる。
- モデル: 最後の応答の `message.model`。
- 最後の要求の時刻: `"type": "api-request"` で `querySource` が `repl_main_thread`（会話の本体の要求だけ）の最後の行の `timestamp`（UTC の ISO 8601）。
- compact の後の文脈: `"type": "system"` で `"subtype": "compact_boundary"` の最後の行の `compactMetadata.postTokens`。その行より前の応答は忘れる。
- 前の compact から余分に読んだ額: その後の応答ごとに `(context - post_compact_context) * read`（負なら 0）を足した物。
- この形は Claude Code 2.1.310 の記録で確かめた物で、文書に書かれた形ではない。形の違う行は飛ばして数える（出力の `transcript.skipped_lines`）。値が 1 つも読めなければ「記録を読めない」を返し、呼ぶ側は決め打ちの数で動く。
- 場面に要る事実（モデルと文脈の大きさ、keepalive なら最後の要求の時刻も）が記録にも標準入力にも無いとき（compact の直後でまだ応答が無いときなど）、コマンドは既定で埋めず、終了コード 4 で終わる。文脈の大きさを compact の後の大きさで代えることもしない。モデルも分からないため。

### 4.6 compact の直す項（後の版）

この項は、今の版（0.2.1）の次の版で `compact` の式を直すための設計メモで、直す作業は次の抜けを埋めること。実装の順は計画のセクション 7 にある。compact の翻訳（4.4 の、場面の事実を中心の入力に直す部分）を項ごとに、会話の記録から計った実測値と照合した（2026-10-25。計画は [works-dispatch/docs/specs/2026-10-25-compact-restart-plan.md](https://github.com/raiki61/claude-plugins/blob/main/works-dispatch/docs/specs/2026-10-25-compact-restart-plan.md) のセクション 3「compact の損得の式を、項ごとに見直す」）。次の抜けが在り、どれもまだ作っていない。`C` は今の文脈、`C'` は compact の後の文脈（その後の最初の要求が書き込む分が `C'_w`、読む分が `C'_r`）、`F' = C'_w * write + C'_r * read + summary * output` は、compact が要約の要求のほかに足す費用。`write`・`read`・`output` は 4.4 の 1 トークンあたりの単価、`summary` は要約の出力のトークン数、`spent` は前の compact から余分に読んだ額、`rent` は今の要求で余分に読む額、`buy` は今の規則での compact 1 回の費用（直した規則では `F' + rent`）。

- 要約の要求は、キャッシュが温かい間、今の文脈 `C` の全部をキャッシュから読む（[Claude Code の prompt caching](https://code.claude.com/docs/en/prompt-caching#compacting-the-conversation)）。正しく数えると buy は `F' + rent`（要約の要求が 1 本分の rent を食う）で、規則は `spent >= F' + consult_cost` になる。今の規則 `spent + rent >= buy` は、この要求を数えていない。
- compact の後の大きさ: 記録の `postTokens`（compact の区切りの行にある、直後の文脈のトークン数。約 1 万）は要約だけの大きさ。compact の後の最初の要求は 2.7〜4.5 万トークンを書き込む（7 日分の中央値。役、つまり担当・相談など会話の種類で違う）。その要求の書き込みと読みを記録から読んで `C'_w`・`C'_r` にし、会話にまだ compact が無いうちは `prices.toml` の既定（7 日分の全体の中央値。書き込み 4 万・読み 1 万）を使う。rent-or-buy は役を知らないので、役ごとの既定は持たない。
- 要約の出力 `summary`（トークン数）: 既定は 2026-10-25 に 9,000 にした。要約の本文に、Claude Code が捨てる下書きを足した見積もり（4.2）。要約の要求の出力は記録に残らず、測れない。
- `consult_cost`: 呼ぶ側が `Q_each / (1 - w) + Q_answer` を渡す。口は、問いを会話に届ける道（単独の要求・どのみち起きる要求に添える注記・keepalive と差し替える問い）で、`Q_each` はその口で問うたびに払う分、`Q_answer` は焦点が返った時だけ払う分、`w` はその口で焦点（compact の要約で残す話題の指定）が返らない割合。
- キャッシュを切らせる直前の compact のための入力 `expiring`（真偽。呼ぶ側が keepalive の止め時に立てる）: その時は `C * (write - read) > C' * write + summary * output + consult_cost` で buy。

これらの項で 7 日分の記録を流すと、compact が初めて得になる文脈は、中央値で約 8 万トークンから約 13 万に移る（Opus、寿命 1 時間。1 時間は Claude Code がサブスクリプションの枠の中で会話の本体に付ける寿命）。

## 5. コマンド

`bin/rent-or-buy`（Claude Code は、有効なプラグインの `bin/` を Bash のツールの PATH に入れる）。標準入力に JSON のオブジェクトを受け、標準出力に JSON のオブジェクトを 1 つ返す。Python 3.11 以上で、標準ライブラリだけを使う（Claude Code のプラグインには、使う人の機械に pip の依存を入れる段が無いため）。

- `rent-or-buy decide`: 中心をそのまま呼ぶ。
- `rent-or-buy keepalive [--transcript FILE]`: 4.4 の keepalive。記録を渡せば、モデル・文脈の大きさ・最後の要求の時刻を記録から埋める（標準入力の値が勝つ）。
- `rent-or-buy compact [--transcript FILE]`: 4.4 の compact。記録を渡せば、モデル・文脈の大きさ・compact の後の大きさ・余分に読んだ額を記録から埋める。
- `rent-or-buy prices MODEL`: 正規化した名前と、使う値段と、その出どころ（調べるとき用）。
- `rent-or-buy snapshot`: LiteLLM の main ブランチから同梱の写しを作り直す（保守する人が打つ）。

終了コード: 0 は判断できた、1 は `snapshot` の失敗、2 は入力の形の誤り、3 は知らないモデル、4 は記録を読めない。0 以外でも、出力は `{"error": "<キー>", "why": "<英語>"}`。`decide`・`keepalive`・`compact` の失敗は、入力ごと判断の記録に足す。知らないモデル名を集めるため（`prices` の失敗は記録しない）。出力の `version` は、プラグインの `plugin.json` の `version`。

## 6. 判断の記録のフィールド

今の全部の行: 時刻・場面（`decide`・`keepalive`・`compact`）・標準入力で受けたままの入力・出力。キャッシュの層の出力は `rent`・`buy`・`prices`・`version` を持ち、式と部品のずれを後で見つけられるようにする。`--transcript` から埋めた事実は行の入力に入らず、出力に載る物（keepalive なら `next_at` と `turn_end_at`）だけが残る。

下のフィールドは、記録で測りたい物。記録から埋めた事実と結果のフィールドは、後の段（10 の段 4）で足す。

- keepalive の行:
  - 時刻: 最後の要求と、判断した時（行の時刻）、呼ぶ側が渡せばターンの終わり。送った要求が実際に出た時刻は、後で会話の記録から埋める。
  - ここから、最後の答えを作る時間（ターンの終わり - 最後の要求）と、判断から要求が出るまでの遅れが出る。
  - keepalive の後のキャッシュの書き込みが大きければ（keepalive 自身が書く数百トークンを十分に超える額。しきい値は段 4 で作るときに決める）、外れと数える。多くの待ちで集めると、余裕 `m` ごとの外れの割合 `q(m)` が出る。
- compact の行: キャッシュが温かかったか冷えていたか、前と後の文脈の大きさ、compact の要求と次の要求の使用量（どの寿命の書き込みの値段だったかを含む）。冷えた compact と温かい compact を実測で比べるため。
- 結果のフィールド（外れたか、次に何を書いたか、要求がいつ出たか）は、判断の時点では分からない。部品は状態を持たないので、後で会話の記録から埋めるツールを、`m` を詰める段（10 の段 4）で作る。

## 7. 呼ぶ側

部品は指針を決めない。会話を回す仕組みに部品をつなぐ呼ぶ側は、次のようにする。

- keepalive: `next_at` に送る。送るたびに `rent` を累計に足し、次の呼び出しで `spent` として渡す。すると決め打ちの M 本の上限は、中心の `action` に替わる。`certain` は呼ぶ側が渡す（待っている出来事が確かに来ると分かっているとき true。たとえば自分が起動した処理）。`hazard` と `miss` は省けて、部品は求めないので、測るまでは渡さない（`certain` が false で `hazard` が無ければ `buy`、つまり止める）。送る直前に、待っている出来事がもう届いていないかを見て、届いていれば送らない（見ないと、待っていた結果と同じ秒に keepalive を送ることがある）。
- compact:
  1. 判断するのは、待ちの間で会話の入力ボックスが空のとき（人が何も打っていないとき）で、keepalive の時刻と、待ちに入るターンの終わり。`spent` は要求ごとに増えるので、どの待ちもキャッシュの寿命より短い会話は keepalive の時刻が来ず、費用だけでは compact しない。keepalive の時刻には先に compact の判断を聞き、compact するなら keepalive は送らない（compact の要求がキャッシュを読むので、キャッシュは保たれる）。しないなら keepalive の判断を聞く。ターンの終わりは人が次を打とうとしている間でありうるので、問わずに compact するのは `forced` が true のときだけにし、延期の上限を超えた compact は keepalive の時刻に回す。
  2. compact の判断が `consult: true` を返したら、その回の keepalive の文を問いに替える。問いは「compact する時です。残す焦点を 1 行で返すか、今は困るなら skip: と訳を返してください。ツールは使わないでください」の形。要求は 1 本のままで、足すのは数十トークン。ターンの終わりには問いだけを送り、人がすぐ次を打ちそうなら skip を返すよう添える。
  3. 答えを会話の記録の最後の応答から読み、2 回目の呼び出しの `answer` に入れる。進めるなら、呼ぶ側が会話に `/compact <焦点>` を打つ。skip なら延期と数え、上限を超えたら焦点なしで compact する。答えが 1 行の焦点でも `skip:` でもなければ、`{"go": true}` を渡す（焦点なしで compact。3.4 の関数の呼び出しが、読めない答えを買いにするのに合わせる）。
  4. 部品があるときは、決め打ちのしきい値（「10 万トークンを超えたら compact」など）を中心の `action` に替え、しきい値は部品が無いときの代わりにだけ残す。
- Claude Code の自動の compact: 歯止めとして残すが、動き出す文脈の大きさ（書いた時点の Claude Code の設定 `autoCompactWindow`。今の名前・単位・既定値は [Claude Code の設定](https://code.claude.com/docs/en/settings)で確かめる）を文脈の上限の近くまで上げる。自動の compact は時を選べず、ターンの途中でも動くので、ふだんの道にはしない。
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
- 呼ぶ側は部品の版を commit の SHA で固定する。プラグインが生まれたリポジトリは git のタグを作らない。単独のリポジトリではタグを足してよい。

## 9. 試験

試験は部品の約束だけを見る。

- 借り賃が一定で延期が無ければ、`fixed` の費用は、どの待ちの長さでも後から見た最適の 2 倍未満。
- 2 回に分けた問い合わせ: 1 回目が `consult: true`、2 回目が `buy`（進める）か `rent`（延期）。
- 境目の 4 つの決まり（2.1）。
- モデル名の正規化（4.3）を実物の見本で。
- 設計書と訳の見出しの数と並びが同じで、引いている URL も同じ。

## 10. 前例と段

同じことをするツールは、設計した時の web 検索の範囲では見つからなかった。下はその検索で見た物で、出典があるのはリンクを付けた物だけ。

- keepalive: 間隔の損益分岐の式や、keepalive のプラグイン（240 秒おき・7 本まで）はあるが、どれも決め打ちの数で、止め時は決めない（例: [cache-keepalive](https://www.claudepluginhub.com/plugins/yujiachen-y-cache-keepalive-plugins-cache-keepalive)）。
- compact: OpenHands・Codex・Cline・Aider・Letta は、どれも大きさか割合のしきい値で compact する。費用の式で時を選ぶ物は見つからなかった。
- 推論サーバーのキャッシュの保持: Continuum は期待の得で保持の時間を決めるが、対象は GPU のメモリで、最悪の場合の上限は無い。費用で決める保持の時間を、最悪の費用が最適の 2 倍までに収まる ski rental とみる論文がある（[arXiv:2309.03521](https://arxiv.org/pdf/2309.03521)）。
- 値段とモデル名は ccusage に倣った（4.1・4.3）。

段。各段の効き目を判断の記録で測ってから次へ進む。

1. 設計（この文書）。
2. 中心・キャッシュの層・コマンド・記録と、呼ぶ側への keepalive のつなぎ込み。
3. 呼ぶ側の compact の指針（問い合わせ・skip の上限・自動の compact の線を上げる）。
4. 結果のフィールドを埋めるツール、`m` を詰めること、ステータスラインの表示。
5. `random`・`learned`・3 つ以上の手、キャッシュの寿命（5 分か 1 時間）の選び方、「前の会話を続けるか新しく始めるか」の翻訳。

最初の版の範囲は段 2 と 3。
