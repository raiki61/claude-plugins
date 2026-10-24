# 借りるか買うかの部品（rent-or-buy）の設計

何の文書か: Claude Code の会話の費用を下げるため、「キャッシュを保つ短い要求を送り続けるか止めるか」と「会話を要約して縮めるか」を計算で決める小さな部品の設計書。
読む人に求めること: 部品の作り（置き場・入出力・値段の取り方・呼ぶ側とのつなぎ方）を知り、呼ぶ側を作る部署はつなぎ方の 6 を読む。持ち主の判断は 12 のとおり済んでいる。
急ぎ: 急がない。今の決め打ちの数（keepalive の間隔・compact の目安）は壊れていない。部品は入れただけでは何も変わらず、呼ぶ側が 6 のとおりにつないだときに効く。

状態: 設計書（2026-10-24。持ち主と話して決めた形。部品の本体はこの設計で作り始めた）

切り出し先でも読める設計書は、プラグインのフォルダに同梱した `rent-or-buy/docs/design.md`（英語の正本）と `rent-or-buy/docs/design.ja.md`（日本語の訳）。そちらには受付番号と決めの経緯を書かず、節の番号もずれている（この文書の 2 がそちらの 3 など）。この文書は、決めた経緯と根拠の記録として残す。

頼み: my_notes（持ち主のノートのリポジトリ）の受付 20261024-044835-ea3e82。受付は頼みに付く番号。前に出して取り下げた頼み 20261024-033714-c5f1de も同じ用件で、その文面もこの設計に入れた。

## 0. 何を作るか

Claude Code の会話には、少しずつ払い続ける（借りる）か、まとめて 1 回払う（買う）かを、先が分からないまま決める場面が 2 つある。

- keepalive: 会話が待っている間、プロンプトのキャッシュが切れないよう短い要求を送り続ける仕組み（送る要求 1 回を 1 本と数える）。送り続けるのが借りる、止めて切れたら書き直すのが買う。
- compact: 会話を要約して縮める操作。縮めずに大きな文脈を読み続けるのが借りる、縮める 1 回の費用が買う。

この形の問題は ski rental（rent-or-buy problem とも呼ぶ）と呼ばれる（https://en.wikipedia.org/wiki/Ski_rental_problem ）。今はどちらも決まった数で決めている（以下、次の 3 つ〔keepalive・compact・単価〕の数をまとめて「今の決まった数」と呼ぶ）。

- keepalive: works-dispatch（このリポジトリ claude-plugins のプラグイン）が、寿命 − 90 秒おきに送り、読みが 0.05 倍のモデル（Opus 5.5・Sonnet 5.5）なら寿命 5 分で 25 本・1 時間で 40 本まで送る（`works-dispatch/dispatch/nodes/role.py` の `keepalive_for`）
- compact: works-dispatch の `COMPACT_FLOOR = 100000`（`works-dispatch/dispatch/nodes/wake.py`）と、my_notes の役（会話に与える役割の本文）「相談」の「10 万トークンを超えていそうなら」の目安
- 単価: works-dispatch の `claudex.py` の倍率（`CACHE_READ_RATES` の表に無いモデルは黙って読み 0.1 倍に落ちる）、my_notes の `claude_call.py` の PRICES。同じ値段を 2 か所に写している

作るのは、この判断の計算だけを持つ小さな部品 `rent-or-buy`。部署（works-dispatch が仕事ごとに立てる、役を持った別の会話）の仕組みは知らず、どこからでも呼べる形にして、部品として使い回す（持ち主 2026-10-24「綺麗な部品としてアセット化しておきたいので、できるだけ綺麗な形で」）。

式と記号の表の正本は my_notes の指南（`notes/knowledge/llm-agent-workflow-cost-design-guide.md` の 3.5。my_notes の master 8709d0c9 で、keepalive・寿命・compact を 1 つの借りるか買うかの形にまとめた）。この設計書は式を写さず、部品の作りだけを決める（持ち主 2026-10-24「ほとんどは計算式なので、自明に決まります。なので、mynotes内でほぼ詰めれるはずで」）。

## 1. 層の分け方

1 つのプラグインの中を 2 つのモジュールに分ける（モジュラモノリス。配るのは 1 つで、中の境目は試験で守る）。

```
  呼ぶ側（works-dispatch・my_notes のスクリプト・works-factory）
  │  コマンド bin/rent-or-buy を呼ぶ（JSON を渡して JSON を受け取る）。Python の import はしない
  ▼
  prompt_cache/   Claude のプロンプトキャッシュへの当てはめ
  │  値段の表・モデル名の揃え・会話の記録の読み取り・翻訳（場面の事実 → 中心の入力）
  ▼  rent_or_buy の表の口（__init__.py に並べた名前）だけを使う
  rent_or_buy/    借りるか買うかのアルゴリズム。Claude もトークンも知らない
     中心 decide・決め方の表・判断の記録
```

- 依存は上から下への一方向だけ。下は上の名前・ファイル・振る舞いを書かない。
- アルゴリズムを Claude から切り離すのは、変わる頻度が違うから。アルゴリズムは理論で決まり、ほぼ変わらない。値段とモデル名と会話の記録の形は、Anthropic と Claude Code の都合で変わる。
- プラグインを 2 つに分けない訳: 呼ぶ側が今は works-dispatch だけで、アルゴリズムだけを使う 2 つ目の利用者がいない。分けても版の固定と配る手間が倍になるだけで、境目は試験で守れる。境目を守っておけば、2 つ目の利用者が出たときにフォルダを外へ出すだけで分けられる。
- 部品は状態を持たない。呼ぶ側が毎回、その回の累計を渡す。
- 指針（いつ keepalive を送るか、いつエージェントに聞くか、`/compact` をどう打つか、Claude Code の自動の compact の線をどこに置くか）は呼ぶ側の層に置く（持ち主 2026-10-24「ただコンパクトの指針は、ディスパッチ層だよね」）。
- 部品が無い・落ちたら、呼ぶ側は今の決まった数で動く。費用の最適化で、止めるゲートではない。

### 1.1 境目の守り方

次の 4 つを `rent-or-buy/tests/test_boundary.py` が照合し、外れたら赤にする。

1. `rent_or_buy/` が読み込むのは、標準ライブラリ（Python の `sys.stdlib_module_names`）と自分だけ。
2. `prompt_cache/` は `rent_or_buy` の表の口（`rent_or_buy/__init__.py` に並べた名前）だけを使い、中のファイル（`rent_or_buy.policies` など）を直に読み込まない。中を作り替えても外が壊れないようにするため。
3. プラグインの外から `rent_or_buy`・`prompt_cache` を Python で読み込まない。外はコマンドを通す。
4. `rent_or_buy/` に Claude の語（claude・token・cache・compact・keepalive と、キャッシュ・トークン・要約）を書かない。import の照合だけでは、Claude の事情を名前や文で書き込めば Claude を知ってしまえるため、語の照合で塞ぐ。ただし塞げるのは語だけで、Claude の単価などの数を素の数で書き込む形は見つけられない（数は書かないという守りは、キャッシュの層に置いて見直す）。works の「考えの住処のチェック」（設計の考えが決めた 1 か所の外に漏れたら赤にする試験）と同じ考え方。

フレームワークは入れない。業界の定石は import-linter（Python の import の向きを決まりとして書いて検査する道具）の layers の契約（https://import-linter.readthedocs.io/en/stable/contract_types.html#layers ）で、Spring Modulith や Packwerk も同じ種類の道具。どれもモジュールが数十あるコードのための物で、ここは 2 つしかない。決まり 4 を持つ道具も無いので、入れても自前の試験は残る。moon（モノレポの道具）は、宣言した依存をプロジェクトの単位で照合する物で、Python の import も 1 つのプラグインの中の境目も見ない（https://moonrepo.dev/docs/config/workspace の `constraints`）。モジュールが 4 つ以上に増えるか、アルゴリズムを別のリポジトリから使う人が出たら、import-linter に移す。境目の守り方は my_notes に調べを頼み（受付 20261024-074314-98bc8f）、答えも自前の試験を勧めた。決まり 1（標準ライブラリと自分だけ）を許す側で書ける道具は見つからず、決まり 3・4 は import のグラフを見る道具の範囲の外だからである（import-linter・Tach・PyTestArch・Deply を比べた）。試験が拾う形: 関数の中や条件の中の import（ast で全部の節点を見る）、相対の import（`rent_or_buy` の中は 1 段まで）、`importlib.import_module` と `__import__`・`getattr` で読む形。拾わない形: 文字列を組み立てて読む形と、`exec`・`eval` の中。`sys.stdlib_module_names` は Python 3.10 から在り、部品は 3.11 以上を求める（`bin/rent-or-buy`）。

## 2. 中心: decide（`rent_or_buy/`）

### 2.1 入力

| 鍵 | 型 | 意味 |
|---|---|---|
| rent | 数 | 次の 1 回を借りる費用 |
| buy | 数 | 買う費用 |
| spent | 数 | この回で借りに払った累計（回は、keepalive なら 1 つの待ち、compact なら前の compact から後） |
| certain | 真偽 | 借りるのを終わらせる出来事（keepalive なら、会話が待っている裏の処理の結果や知らせ）が来ることが確かか |
| miss | 数・既定 0 | 借り続けても買いを避けられない割合（外れ率。keepalive なら、送っていたのにキャッシュが切れた割合） |
| hazard | 数・省略可 | 次の区間でその出来事が来る確率 |
| deferred | 整数・既定 0 | 「買う」と出た後に延期した回数 |
| defer_limit | 整数・既定 0 | 延期を受ける上限の回数 |
| forced | 真偽・既定 false | 呼ぶ側の強制の上限に着いたか |
| ask | 真偽・既定 false | 買う前に問い合わせ口（2.4）で相手に聞くか |
| answer | 表・省略可 | コマンドで呼ぶときの 2 回目に渡す、相手の答え（形は 2.4 の関数の返事と同じで、`go` と、`prep` か `why`） |
| policy | 字・既定 fixed | 止め時の決め方の名前 |

費用の単位は呼ぶ側が決める（キャッシュの層はドルで渡す）。形が違う入力（負の数・型の違い・知らない鍵の型）は黙って直さず、止めて訳を返す（docs/standards/machine-readable-values.md の「黙って崩さない」）。

### 2.2 出力

```json
{"action": "rent", "reason": "within_buy_cost", "why": "…", "consult": false, "prep": null, "policy": "fixed"}
```

- `action` は `rent`（借りる）か `buy`（買う）。
- `consult` は、まだ聞いていない相手に聞くべきとき true（コマンドで呼ぶときの 1 回目）。true になるのは、決め方が `buy` を出し、`forced` が false で、`ask` が true で、`deferred < defer_limit` で、`answer` が無いときだけ。それ以外は false。
- `prep` は、相手が進めると答えたときの準備の情報（compact なら焦点〔`/compact` の後ろに付けて、要約に残す話題を指す 1 行〕）。無ければ null。
- `reason` は機械の読む短い鍵（`within_buy_cost`・`reached_buy_cost`・`hazard_above_ratio`・`hazard_below_ratio`・`no_hazard`・`forced`・`defer_limit_reached`・`consult_go`・`consult_deferred`・`consult_unreadable`・`unknown_policy_fallback`）、`why` は英語の訳（人が読む）。決め方の関数は `(action, reason, why)` を返す。
- 部品の版は、キャッシュの層が出力に足す（3）。

### 2.3 決め方

決め方は名前で選ぶ。中心は名前から関数を引く表を持ち、外から足せる（`register`）。知らない名前なら `fixed` で決め、`why` にそう書く。

- `fixed`（最初の版）: 決定的な止め方。買いの費用のうち避けられる分を `(1 − miss)·buy` とし、次の 1 回を借りても累計がそれに届かない間（`spent + rent < (1 − miss)·buy`）だけ借りる。
  - `certain` が true ならこの規則だけで決める。借り賃が一定なら `K = ceil(ρ) − 1` 回で止まり（`ρ = buy / rent`）、最悪で後から見た最適の 2 倍未満（指南 3.5 の「決まった回数」）。compact も同じ規則になる。前の compact から、縮めずに大きな文脈を読んで余分に払った費用の累計（`spent`）が、compact 1 回の費用（`buy`。3.4 の要約を書く費用）に届いたら打つ。
  - 指南は `ρ` が整数でないとき `floor(ρ) − 1` とも比べて比の小さいほうを採る。最初の版はこの比べを入れない。差は 1 回で、どちらも 2 倍未満のため。借り賃が回ごとに変わる compact では回数で数えられないので、1 つの規則で両方を扱うほうを採った。
  - `certain` が false なら、`hazard` が有り、来る確率が費用の比を超え（`hazard > rent / ((1 − miss)·buy)`）、かつ上の規則で借りられる間だけ借りる（指南 3.5 の「来るか分からないとき」。上限は来る見込みがある間も外さない）。`hazard` が無ければ `buy`。
- `random`（後の段）: 買う時点を確率で選ぶ（最悪 e/(e−1) ≈ 1.58 倍。出典は 0 の ski rental の原典と同じ）。乱数の種を記録に残す。
- `learned`（後の段）: 記録から待ちの長さや残りの要求の数の見込みを出し、見込みを信じる度合いを付けて止め時を決める（予測つきの ski rental。https://proceedings.neurips.cc/paper/2018/hash/73a427badebe0e32caa2e1fc7530b7f3-Abstract.html ）。

どの決め方にも、次の 2 つを中心で重ねる。

- 強制の上限: `forced` が true なら、決め方の結果によらず `buy`（`reason` は `forced`。聞かない）。compact では、Claude Code の自動の compact より前に打つための呼ぶ側の線に当たる。
- 延期の上限: 決め方が `buy` を出しても、`deferred < defer_limit` の間は、問い合わせ口（2.4。買う前に相手に聞く口）の答えが延期なら `rent` を返す。上限に着いたら、聞かずに `buy` を返す。延期した分だけ最悪の倍率は悪くなる。その幅は指南の式で出す。

### 2.4 問い合わせ口

買う前に、呼ぶ側が渡した相手（compact ならエージェント）に聞く口。中心は相手が誰かを知らない（持ち主 2026-10-24「匿名メソッド的に問い合わせる窓口だけ用意しておいてあげてもいいかな」）。

- 関数として呼ぶとき: `decide(inputs, consult=関数)`。中心は聞くべきとき（2.2 の `consult` が true になる条件）だけ関数を呼ぶ。関数の返事は次の 3 つのどれか。渡さなければ、1 回目のコマンドと同じく `consult: true` を返す。
  - `{"go": true, "prep": {...}}`: 進める。`prep` は買いの準備の情報で、compact なら焦点。
  - `{"go": false, "why": "…"}`: 延期する。
  - 例外か、形の違う返事: 聞かなかったのと同じに扱い、`buy` を返して `why` にそう書く。
- コマンドとして呼ぶとき: 関数を渡せないので 2 回に分ける。1 回目は `{"action": "buy", "consult": true}` を返し、呼ぶ側が相手に聞く。2 回目に、答えを `answer` に入れて渡す。延期なら、呼ぶ側が次の回から `deferred` を 1 つ足して渡す。中心が状態を持たない形は崩れない。コマンドで渡された `answer` の形が違うときは、黙って買いにせず入力の形の違いとして止める（黙って買いにするのは、関数の返事の形が違うときだけ）。

### 2.5 3 つ以上の手（後の段）

keepalive を送る時刻には、手が 3 つある。送る（借りる）、compact する（払ってから、借りる額を下げる）、止める（買う）。借りる・リースする・買うのように手が 3 つ以上ある形は multislope ski rental と呼ばれる（Lotker, Patt-Shamir, Rawitz「Rent, Lease or Buy」STACS 2008。https://ar5iv.labs.arxiv.org/html/0802.2832 ）。compact で文脈が縮むと keepalive 1 本の額が下がるので、ちょうどこの形になる。最初の版は 2 つの手だけにし、手の一覧（送る・compact する・止めるなど）を入力 `options` として受ける形は、記録で効き目を測ってから足す。

### 2.6 判断の記録

判断ごとに JSONL を 1 行足す関数を、中心の側に置く（中身を問わない記録で、Claude を知らない）。

- 置き場は呼ぶ側が決める。コマンドの既定は `~/.cache/rent-or-buy/decisions.jsonl` で、環境変数 `RENT_OR_BUY_RECORD` で置き場を替え、`off` で止める。
- 足し続ける物なので、上限を持つ（docs/standards/breakage-detection.md の「足し続ける物の上限」）。10 MB を超えたら `decisions.1.jsonl` に名前を替えて新しく始め、古い物は 1 つだけ残す。
- 書けないとき（置き場が無い・権限が無い）は判断を止めず、出力の `record` に訳を書く。

## 3. キャッシュの層（`prompt_cache/`）

### 3.1 値段の表

手本は ccusage（Claude Code の会話の記録から使用額を出すツールで、同じ記録を読み、値段とモデル名を同じ問題として解いている）。ccusage は、LiteLLM（LLM の呼び出しをまとめる道具）の値段表の写しを本体に埋め込み、動くたびに LiteLLM の最新を取りに行き、取れなければ写しで計算する（https://github.com/ryoppippi/ccusage/blob/main/rust/crates/ccusage-core/src/pricing.rs の `load_with_overrides`）。ここも同じ形にする。

- 同梱の写し: `prompt_cache/snapshot.json`。LiteLLM の値段表（https://raw.githubusercontent.com/BerriAI/litellm/main/model_prices_and_context_window.json ）から、Anthropic に直に繋ぐときの `claude-` で始まる項目と、使う単価の欄だけを抜いた物。どの commit から取ったかと、取った日を写しに書く。
- 使う欄（1 トークンあたりのドル）: 入力 `input_cost_per_token`・5 分の書き込み `cache_creation_input_token_cost`・1 時間の書き込み `cache_creation_input_token_cost_above_1hr`・読み `cache_read_input_token_cost`・出力 `output_cost_per_token`。送る文の大きさで単価が上がるモデル（Haiku 5.5 は 10 万トークンを超えると上がる）は、`…_above_100k_tokens` の形の欄も持つ。2026-10-24 に、Opus 5.5・Sonnet 5.5・Haiku 5.5・Fable 5.1 の値が公式の料金表（https://platform.claude.com/docs/en/about-claude/pricing ）と一致することを確かめた。
- 最新: 1 日に 1 回まで LiteLLM の main から取り、`~/.cache/rent-or-buy/latest.json` に控える。ccusage は人が打つたびに 1 回動くので毎回取るが、この部品は keepalive のたびに裏で呼ばれるので、1 日 1 回に抑える。取れたら照合し（5 つの単価が揃って正の有限の数か、読み < 入力 < 書き込みの順か。`…_above_100k_tokens` の欄も正の有限の数で基の単価以上か）、外れた項目と欄は使わない。2 回の取得（commit と値段表）は合わせて 5 秒で打ち切り、取れない・照合に落ちた・どんな失敗でもときは写しで計算する（最新は費用の最適化で、判断を止めない）。控えの取得日が写しより古いか、7 日より前なら使わず、出力の `prices.latest_skipped` に `stale` と書く。環境変数 `RENT_OR_BUY_OFFLINE=1` で取りに行かない（ccusage の `--offline`）。
- 上書き: 使う人の値段のファイル（環境変数 `RENT_OR_BUY_PRICES` に置き場）と、呼ぶときに渡す JSON の `prices` が、最後に勝つ。
- 写しを新しくする: `bin/rent-or-buy snapshot` を受け持ちの部署が打つ。ccusage は CI が毎日 main に commit して写しを新しくする（https://github.com/ryoppippi/ccusage/blob/main/.github/workflows/update-pricing.yaml ）が、このリポジトリは main に入れるときに版を上げる決まりで、CI の commit とぶつかるため、手で打つ。
- 出力の `prices` に、どの値段で計算したか（`snapshot`・`latest`・`override`）と、その出どころ（LiteLLM の commit か取った日）を書く。

データの所在と同じ地域で処理させる指定（`inference_geo`）の 1.1 倍と、Fast mode の倍の単価は、どの欄にも同じ倍率で掛かる（公式の料金表の Data residency pricing と Fast mode pricing）。判断は単価の比で決まるので、最初の版は入れない。

### 3.2 実測の値と既定

`prompt_cache/prices.toml` に置く。3.1 の LiteLLM の値段表に無い値（トークン数や秒数の既定）を置く。測った日と出どころ（受付番号か指南の節）は `prices.toml` には書かず、この節に残す。

- keepalive 1 本のキャッシュの書き込み 380・出力 5（my_notes の受付 20261024-031615-3eafaa の測り。works-dispatch の keepalive の文で測った値なので、ほかの文では違う。呼ぶ側が上書きできる）
- 寿命までの余裕 `m` 60 秒（4 分おきに送る。外の keepalive のプラグイン https://www.claudepluginhub.com/plugins/yujiachen-y-cache-keepalive-plugins-cache-keepalive の既定の間隔 240 秒と同じ。今の works-dispatch の 90 秒は早すぎると持ち主が判断した〔2026-10-24〕。記録で遅れの分布を測ってから詰める）
- compact の後の文脈 2.5 万・要約の出力 5,000（指南 3.5 の C の例の値で、実測ではない。指南の commit は 8709d0c90728029d55985a72548170e591298d59）

出どころは `prices.toml` には書かず（部品を、このリポジトリの外の文脈から切り離すため）、ここに残す。keepalive の 380 と 5 は受付 20261024-031615-3eafaa の測り、余裕 60 秒は外の keepalive のプラグインの既定の間隔に合わせた値（works-dispatch の今の値は 90 秒）。

### 3.3 モデル名の揃え

使う人の環境で記録に書かれるモデル名は、値段表の名前と同じとは限らない（クラウド経由の前置き、1M 文脈版の `[1m]`、日付付きの版、社内の中継が付けた名前など）。ccusage は、そのまま照合し、合わなければ小文字にして `.` と `@` を `-` に替え、それでも合わなければ名前を含む項目のうち一番長い物を採る（曖昧な照合）。使う人の対応表を環境変数 CCUSAGE_MODEL_ALIASES で足せる（https://github.com/ryoppippi/ccusage/blob/main/rust/crates/ccusage-core/src/model_aliases.rs ）。ここは次の順にする。

1. 使う人の対応表（環境変数 `RENT_OR_BUY_MODEL_ALIASES`。`名前=モデル` をカンマで区切るか JSON。ccusage と同じ形）でそのまま引く。
2. 揃える: 小文字にし、末尾の `[…]` を削り、`claude-` より前（`us.anthropic.` などの前置き）を削り、`.` と `@` を `-` に替え、末尾の日付（`-20261001` など）と版（`-v1:0` など）を削る。揃えた名前で値段表と対応表を引く。
3. 引けなければ「知らないモデル」と返す。呼ぶ側は今の決まった数で動く。知らなかった名前は記録に残し、写しか対応表に足す手がかりにする。

曖昧な照合はしない。ccusage は使った額の集計なので近い値段で数えても害が小さいが、この部品は値段で自動の判断を下すので、違うモデルの値段を拾うと判断がずれる。ccusage の値段の部分が 6,000 行を超えるのは、曖昧な照合が別のモデルの値段を拾わないための守りの大半で、それも要らなくなる。

揃える処理の試験は、実物の名前を見本にする（docs/standards/breakage-detection.md の「外の形は実物の見本で試験する」）。2026-10-24 に確かめた実物は、Anthropic に直に繋いだ会話の記録の `claude-opus-5-5` と、LiteLLM の値段表のクラウド経由の項目名（`us.anthropic.claude-opus-5-5` など）だけ。ほかの環境で Claude Code の記録に何が書かれるかは、見本が集まったら試験に足す。

### 3.4 翻訳

翻訳は場面の事実を中心の入力に直す関数。何をどれに当てるかの式は指南 3.5 に従う。

keepalive:

- 受ける物: モデル・寿命（300 か 3600 秒）・文脈の量・この待ちで送った本数の費用の累計・待っている物が来ることが確かか（と、分かれば来る確率と外れ率）・最後の要求の時刻。1 本の書き込みと出力のトークン数と余裕 `m` は、3.2 の既定を呼ぶ側が上書きできる。
- 当てはめ: 借りる＝1 本の費用（読み × 文脈 + 寿命に合う書き込み × 1 本の書き込み + 出力 × 1 本の出力）、買う＝切れの上乗せ（(寿命に合う書き込み − 読み) × 文脈）。
- 返す物: 中心の出力に、送る時刻 `next_at`、借りる・買うの額、`prices`・`version` を足した物。記録だけに残す `turn_end_at`（受けたらそのまま添える）もある。keepalive の `buy` は「止める」なので、問い合わせはしない（`ask` は常に false）。
- 送る時刻: 最後の要求の時刻 + 寿命 − 余裕 `m`。
  - キャッシュの寿命は要求の開始から数える（https://code.claude.com/docs/en/prompt-caching ）。記録の時刻は手元で要求を出す前に付くので、この測り方は安全側に寄る。
  - 今の 90 秒は、ターンの終わりから数えていたので、応答を作る時間も含んでいた。最後の要求から数えれば、その分は要らない。

compact:

- 受ける物: モデル・compact が書く寿命・文脈の量・前の compact の後の文脈の量（無ければ 3.2 の既定）・要約の出力の量・前の compact から後に余分に読んだ費用の累計・キャッシュが温かいか・問い合わせの費用（1 往復の額）と、中心の入力の `forced`・`ask`・`deferred`・`defer_limit`・`answer`。
- 当てはめ: 借りる＝この 1 回で余分に読む額（(文脈 − compact の後の文脈) × 読み。負なら 0）、買う＝縮める費用（compact の後の文脈 × 書き込み + 要約の出力 × 出力 + 問い合わせの費用）。`certain` は true。
- キャッシュが温かいかは、全部の書き込みが同じ寿命なら判断に入らない（指南 3.5 の C）。会話の本体が 1 時間・compact が 5 分の環境で冷えているときは早く打ってよいが、実測が無いので、最初の版は記録に残すだけにする。
- 返す物: 中心の出力（`buy` なら打つ）に、借りる・買うの額、`prices`・`version` を足した物。呼ぶ側は借りる額を累計に足して次の回に渡す。

### 3.5 会話の記録の読み取り

呼ぶ側が自分で数えなくてよいよう、会話の記録（transcript の JSONL）から翻訳の事実を出す関数を置く。コマンドでは `--transcript <ファイル>` で渡す。

- 文脈の量: 最後の応答の `message.usage` の `input_tokens`・`cache_read_input_tokens`・`cache_creation_input_tokens` の和。応答は内容のブロックごとに行が分かれ、同じ `message.id` を持つので、id でまとめる。
- モデル: 最後の応答の `message.model`。
- 最後の要求の時刻: `"type": "api-request"` の行の `timestamp`（UTC の ISO 8601）。会話の本体の要求（`querySource` が `repl_main_thread`）だけを見る。
- compact の後の文脈の量: 最後の `"subtype": "compact_boundary"` の行の `compactMetadata.postTokens`。
- 前の compact から後に余分に読んだ費用の累計: 最後の compact の後の応答ごとに、(その応答の文脈 − compact の後の文脈) × 読み を足した物（負は 0）。
- この形は 2026-10-24 の Claude Code 2.1.310 の記録で確かめた物で、公式の文書に書かれた形ではない。読めない行（`model` が文字列でない行を含む）は飛ばし、必要な値が 1 つも読めなければ「記録を読めない」と返して、呼ぶ側は今の決まった数で動く。
- 場面に要る事実（モデル・文脈の量、keepalive は最後の要求の時刻も）が、記録と標準入力を合わせても揃わないとき（compact の直後でまだ応答が無いときなど）は、既定で埋めず「記録を読めない」（終わりのコード 4）と返す。文脈の量を compact の後の量で代えることはしない（モデルも分からないため）。

## 4. コマンド

`bin/rent-or-buy`（Claude Code は、有効なプラグインの `bin/` を Bash のツールの PATH に入れる）。標準入力に JSON を受け、標準出力に JSON を返す。

- `rent-or-buy decide`: 中心をそのまま呼ぶ。
- `rent-or-buy keepalive [--transcript <ファイル>]`: 3.4 の keepalive。記録を渡せば、モデル・文脈の量・最後の要求の時刻を記録から埋める（標準入力の値が勝つ）。
- `rent-or-buy compact [--transcript <ファイル>]`: 3.4 の compact。記録から、モデル・文脈の量・compact の後の文脈の量・余分に読んだ累計を埋める。
- `rent-or-buy prices <モデル>`: 揃えた名前と、使う単価と、その出どころを返す（調べるとき用）。
- `rent-or-buy snapshot`: LiteLLM の main から同梱の写しを作り直す（受け持ちの部署が打つ）。

終わりのコード: 0 は判断できた、1 は `snapshot` の取得の失敗、2 は入力の形が違う、3 は知らないモデル、4 は記録を読めない。0 以外でも標準出力に `{"error": "<機械の読む鍵>", "why": "…（英語）"}` を返す。`decide`・`keepalive`・`compact` の失敗は、入力ごと判断の記録に足す（知らないモデル名を機械で拾い、写しか対応表に足す手がかりにするため。`prices` の失敗は記録しない）。部品の版 `version` は、プラグインの `plugin.json` の `version`（main に入れるたびに上がる）。

## 5. 判断の記録の欄

全部の行: 時刻・場面（`decide`・`keepalive`・`compact`）・入力・出力。キャッシュの層の行は `prices`・`version` も持つ（式と部品のずれを後で見つけるため）。

- keepalive の行: 指南の未測定の値を出すための欄を持つ（my_notes の受付 20261024-053049-2f6453）。
  - 時刻: 最後の要求・送ると決めた時（行の時刻）。呼ぶ側が渡せばターンの終わりも持つ。送った要求が出た時は、後で記録から埋める。
  - ここから、最後の応答を作る時間（ターンの終わり − 最後の要求）と、送ってから要求が出るまでの遅れ（要求が出た時 − 送ると決めた時）が出る。
  - 送った後の書き込みの量が大きければ外れと数える。集めると、余裕 `m` ごとの外れの割合 q(m) が出る。
- compact の行: 打った時のキャッシュが温かいか冷えているか、縮める前と後の文脈の量、compact の要求と直後の要求の使用量（どの寿命の単価で書いたかを含む）。冷えた compact と温かい compact を実測で比べるため。
- 結果の欄（外れたか・直後に何を書いたか・送った要求が出た時）は判断の時点では分からない。部品は状態を持たないので、後で会話の記録と突き合わせて埋める道具を、余裕 `m` を詰める段（10 の 4）で作る。

## 6. 呼ぶ側の層: works-dispatch が持つこと

部品の外。works-dispatch を受け持つ割り振りの部署（会社の形 `.claude/company.toml` で works-dispatch・tiers・rent-or-buy の直しを受け持つ部署）が作る。

- keepalive: 送る時刻を 3.4 の `next_at` にし、何本まで送るかを中心の `action` に替える。送る直前に、待っている物の知らせが届いていないか（台帳・裏の処理の終わり）を見て、届いていれば送らない。台帳は、works-dispatch が知らせを 1 行ずつ足す受付箱の `log.jsonl`。この確かめが要る例として、my_notes の調べものの部署の 04:30〜04:38 の 1 本目は、裏の処理の終わりと同じ秒に送っていた（待っている物が届いた時に送った、要らない 1 本）。
- compact の指針:
  1. 判断するのは、待ちに入って入力欄（Claude Code の、人が文を打つ欄）が空の時、つまり keepalive を送る時刻と、待ちに入ったターンの終わり（持ち主 2026-10-25「compactを知らせてくれるのがkeepaliveのタイミングは遅すぎる可能性があるよね」。keepalive の時刻は、最後の要求の開始からキャッシュの寿命 − 余裕で測るので、要求（ターン）が来るたびに先へ送られる。寿命より短い待ちで次のターンが来る会話は、その時刻に着く前に必ず時刻が送られて判断が走らない。その間も、縮めずに大きな文脈を読む費用の累計 `spent`〔2.1 の表〕は増え続けるので、compact が得になる線を越えても縮まない）。keepalive の時刻には、先に compact の判断を聞き、打つなら keepalive は送らない（compact の要求がキャッシュを読むので、keepalive の代わりになる）。打たないなら keepalive の判断を聞く。ターンの終わりは人が次の文を打とうとしている間でありうるので、問わずに打つのは強制の線に着いた時だけにし、延期の上限を超えた打ちは keepalive の時刻に回す（works-dispatch の受付の設計 3.4 の「ターンの終わりの compact」）。
  2. compact の判断が `consult: true` を返したら、その時刻の keepalive の文を問いに替えて送る（ターンの終わりなら、人がすぐ次の文を打ちそうなら skip を返すよう添えた問いを送る）。問いは「compact を打つ時です。残す焦点を 1 行で返すか、今は困るなら skip: と訳を返してください。ツールは使わないでください」の形。要求は 1 回のままで、足すのは数十トークン。
  3. 返事は待ち受け（works-dispatch の、知らせを待って会話を起こすフックのプロセス）が会話の記録の最後の応答から読み、2 回目の判断の `answer` に入れる。会話にコマンドを打たせない。進めるなら、今ある `--compact` の打ち方（works-dispatch の `dispatch.py --compact [焦点]`。会話が区切りを印し、待ち受けが compact を打つ）で、機械が会話の窓（その会話を映す端末の画面）に `/compact <焦点>` を打つ。skip なら延期と数え、上限を超えたら焦点なしで打つ。
  4. 役の本文から「10 万トークンを超えていそうなら」の目安を外す。`wake_hook.py` が `COMPACT_FLOOR` より小さい文脈では打たない判定は、部品が在れば中心の `action` に替え、無いときだけ今のまま残す。
- Claude Code の自動の compact: 消さずに、線（設定 `autoCompactWindow`。Claude Code の自動の compact が打つ文脈の量）を文脈の上限に近い所まで上げて歯止めに残す。打つ時を選べず、ターンの途中でも打つので、ふだんの担い手にはしない。
- 部品の置き場は、Claude Code が入れたプラグインの控え（`installed_plugins.json`）から `rent-or-buy` を引き、`bin/rent-or-buy` を呼ぶ。見つからない・0 以外で終わったら今の決まった数で動く。

## 7. 置き場と版

このリポジトリの新しいプラグイン `rent-or-buy/`（marketplace に載せる）。Python の標準ライブラリだけで書く（Claude Code のプラグインには、使う人の機械で pip の依存を入れる段が無いため）。

```
rent-or-buy/
  .claude-plugin/plugin.json
  README.md・CHANGELOG.md
  bin/rent-or-buy             コマンド（4）
  rent_or_buy/                アルゴリズム（2）
    __init__.py               表の口: decide・InputError・register・append_record
    core.py                   中心 decide・強制と延期・問い合わせ口
    policies.py               決め方の表と fixed
    record.py                 判断の記録を足す・上限で切る
  prompt_cache/               キャッシュの層（3）
    __init__.py
    prices.py                 写し・最新・上書きを重ねて単価を引く
    names.py                  モデル名の揃え
    translate.py              keepalive・compact の翻訳
    transcript.py             会話の記録の読み取り
    snapshot.json             LiteLLM の値段表の写し
    prices.toml               実測の値と既定
  tests/
    test_core.py              fixed の約束（8）
    test_translate.py         翻訳・会話の記録・コマンドを、ネットワークなしで
    test_boundary.py          境目の 4 つの決まり（1.1）
    test_names.py             モデル名の揃えを実物の見本で
```

- スキルは置かない。呼ぶのはプログラムで、会話から使う場面がまだ無いため。
- 版の固定はタグでなく commit の SHA にする。このリポジトリはタグを作らない（持ち主 2026-09-29）。works-factory の PIN（使う版の commit の SHA を 1 行書いたファイル）と同じ形。
- 受け持ち: 割り振り（works-dispatch・tiers・rent-or-buy の直しを受け持つ部署）。いちばんよく呼ぶのが works-dispatch のため（my_notes の司令塔の答え。足しの受付 20261024-081622-55075a）。会社の形（`.claude/company.toml`）の割り振りの説明は、この部品を main に入れるブランチで直した。

## 8. 試験

持ち主 2026-10-24「テストは最小に」に沿い、部品の約束だけを置く。

- `fixed` の決め方は、借り賃が一定なら、どんな待ちの長さでも、延期が 0 なら費用が後から見た最適の 2 倍未満。
- 問い合わせ口の 2 回に分けた呼び方で、1 回目が `consult: true`、2 回目の答えで `buy`（進める）か `rent`（延期）になる。
- 境目の 4 つの決まり（1.1）。
- モデル名の揃え（3.3）を実物の見本で。

## 9. 前例との差

前例の調べ（my_notes の受付 20261024-042909-7b5d39 と 20261024-051714-5bc31c）では、同じ物は見つからなかった。

- keepalive: 間隔の損益分岐の式や、keepalive のプラグイン（間隔 240 秒・7 本まで）はある。ただ、どれも決まった数で、止め時を決めていない。
- compact: OpenHands・Codex・Cline・Aider・Letta は、どれも文脈のサイズか割合の線で打つ。費用の式で打ち時を決める例は見つからなかった。
- 推論サーバーのキャッシュの保持: 期待の得で保持の時間を決める研究（Continuum）がある。ただし対象は GPU のメモリで、最悪の倍率の保証は無い。費用だけで決めた保持の時間を ski rental の最悪 2 倍とみる論文（https://arxiv.org/pdf/2309.03521 ）もある。
- 値段とモデル名の扱いは ccusage に前例があり、写した（3.1・3.3）。
- 費用の判断を会話の外の部品に置き、keepalive と compact を 1 つの形にまとめたものは見つからなかった（web 検索の範囲）。

## 10. 段

各段の効きを記録で測ってから次へ進む。

1. 設計書（これ）
2. 部品の中心・キャッシュの層・コマンド・記録（この作業の部署）と、works-dispatch の keepalive のつなぎ込み（割り振り）
3. compact の指針（問い合わせ・skip の上限・自動の compact の線）
4. 結果の欄を埋める道具と余裕 `m` の詰め、statusline（画面の下の行）の表示
5. `random`・`learned` と 3 つ以上の手、寿命（5 分か 1 時間）の選び方の翻訳、works-factory の「前の会話を続けるか新しく始めるか」の翻訳

最初の版の範囲は 2 と 3。

## 11. 実装の割り振り

- 部品（`rent-or-buy/`）はこの設計書を書いた作業の部署で作る。
- works-dispatch の側（6）は割り振りに頼む。works-dispatch のファイルは割り振りの受け持ちのため（会社の形 `.claude/company.toml`）。
- my_notes の側は、my_notes の部署へ一覧で渡す。中身は、役「相談」の目安を消す、`autoCompactWindow` を上げる、`claude_call.py` の PRICES を部品の値段に替える、の 3 つ。

## 12. 持ち主と決めたこと（2026-10-24、この部署の窓で）

- 判断は全部プログラムから出す。人やエージェントに数を決めさせない。エージェントが答えるのは、問い合わせ口（2.4）での進めるか延期かと焦点だけで、延期を受ける回数の上限と、いつ聞くかはプログラムが決める。
- 指針は works-dispatch の層に置き、部品は部署と切る。
- compact は keepalive の時刻に打ち、その前にエージェントに焦点か skip かを聞く（損の少ない方）。聞く口は中心に匿名の問い合わせ口として置く。2026-10-25 に、待ちに入ったターンの終わりにも聞くと決めた（6 の compact の指針 1。持ち主「おｋ」、my_notes の受付 20261024-202139-f3f867）。
- Claude Code の自動の compact は、線を上げて歯止めに残す。
- 綺麗な部品として使い回せる形にする。名前は `rent-or-buy`（ほかのプラグインと同じハイフンでつなぐ形で、論文の呼び名 rent-or-buy problem に合わせる）。
- 1 つのプラグインの中をアルゴリズムとキャッシュの層に分け、境目は試験で守る（モジュラモノリス）。フレームワークは入れない。守り方の一番よい形は my_notes に調べを頼む。
- keepalive の寿命までの余裕の既定は 60 秒（90 秒では 3 分半で送り、早すぎる）。
- 値段とモデル名は、世の中の解き方（ccusage）を写す。写しを同梱し、最新は 1 日 1 回まで取りに行き、モデル名は揃えて引き、曖昧な照合はしない。
