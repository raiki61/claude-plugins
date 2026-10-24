# 借りるか買うかの部品（rentbuy）の設計

状態: 設計書（2026-10-24。持ち主と話して決めた形。実装の段は持ち主が見てから）

頼み: my_notes（持ち主のノートのリポジトリ）の受付 20261024-044835-ea3e82。受付は頼みに付く番号。取り下げた前の頼み 20261024-033714-c5f1de の言葉も同じ件。

読んだ後に要るもの: この形で実装の段に進めてよいかの判断。

## 0. 何を作るか

Claude Code の会話には、少しずつ払い続ける（借りる）か、まとめて 1 回払う（買う）かを、先が分からないまま決める場面が 2 つある。

- keepalive: 会話が待っている間、プロンプトのキャッシュが切れないよう短い要求を送り続ける仕組み（送る要求 1 回を 1 本と数える）。送り続けるのが借りる、止めて切れたら書き直すのが買う。
- compact: 会話を要約して縮める操作。縮めずに大きな文脈を読み続けるのが借りる、縮める 1 回の費用が買う。

この形の問題は ski rental と呼ばれる（https://en.wikipedia.org/wiki/Ski_rental_problem ）。今はどちらも決まった数で決めている（以下、この 3 つを「今の決まった数」と呼ぶ）。

- keepalive: works-dispatch（このリポジトリ claude-plugins のプラグイン）が、寿命 − 90 秒おきに送り、読みが 0.05 倍のモデル（Opus 5.5・Sonnet 5.5）なら寿命 5 分で 25 本・1 時間で 40 本まで送る（`works-dispatch/dispatch/nodes/role.py` の `keepalive_for`）
- compact: works-dispatch の `COMPACT_FLOOR = 100000`（`works-dispatch/dispatch/nodes/wake.py`）と、my_notes の役（会話に与える役割の本文）「相談」の「10 万トークンを超えていそうなら」の目安
- 単価: works-dispatch の `claudex.py` の倍率（`CACHE_READ_RATES` の表に無いモデルは読み 0.1 倍に落ちる）、my_notes の `claude_call.py` の `PRICES`。同じ値段を 2 か所に写している

作るのは、この判断の計算だけを持つ小さな部品 `rentbuy`。部署（works-dispatch が仕事ごとに立てる、役を持った別の会話）の仕組みは知らず、どこからでも呼べる形にして、部品として使い回す（持ち主 2026-10-24「綺麗な部品としてアセット化しておきたいので、できるだけ綺麗な形で」）。

式と記号の表の正本は my_notes の指南（`notes/knowledge/llm-agent-workflow-cost-design-guide.md` の 3.5。my_notes の master 368e3842 で、keepalive・寿命・compact を 1 つの借りるか買うかの形にまとめた）。この設計書は式を写さず、部品の作りだけを決める（持ち主 2026-10-24「ほとんどは計算式なので、自明に決まります。なので、mynotes内でほぼ詰めれるはずで」）。

## 1. 層の分け方

```
  呼ぶ側
  ├─ works-dispatch（指針と実行: いつ送る・いつ聞く・どう打つ）
  ├─ my_notes のスクリプト・works-factory（計算だけ使う）
  │
  ▼  関数呼び出し、または JSON を受けて JSON を返すコマンド
  rentbuy（計算だけ。hook を持たない。部署の言葉を知らない）
  ├─ 中心 decide（場面を知らない）
  ├─ 翻訳（場面の事実 → 中心の入力）: keepalive・compact
  ├─ 値段の表（prices.toml）
  └─ 判断の記録（JSONL）と、記録を読む道具
```

- 依存は呼ぶ側 → rentbuy の一方向だけ。rentbuy は呼ぶ側の名前・ファイル・振る舞いを書かない。
- rentbuy は状態を持たない。呼ぶ側が毎回、その回の累計を渡す。
- 指針（いつ keepalive を送るか、いつエージェントに聞くか、`/compact` をどう打つか、Claude Code の自動の compact の線をどこに置くか）は呼ぶ側の層に置く（持ち主 2026-10-24「ただコンパクトの指針は、ディスパッチ層だよね」）。
- rentbuy が無い・落ちたら、呼ぶ側は今の決まった数で動く。費用の最適化で、止めるゲートではない。

## 2. 中心: decide

### 2.1 入力

| 鍵 | 型 | 意味 |
|---|---|---|
| rent | 数 | 次の 1 回を借りる費用 |
| buy | 数 | 買う費用 |
| spent | 数 | この回で借りに払った累計（回は、keepalive なら 1 つの待ち、compact なら前の compact から後） |
| certain | 真偽 | 待っている物が来ることが確かか |
| miss | 数・既定 0 | 借り続けても買いを避けられない割合（外れ率。keepalive なら、送っていたのにキャッシュが切れた割合） |
| hazard | 数・省略可 | 次の区間で待っている物が来る確率 |
| deferred | 整数・既定 0 | 「買う」と出た後に延期した回数 |
| defer_limit | 整数・既定 0 | 延期を受ける上限の回数 |
| forced | 真偽・既定 false | 呼ぶ側の強制の上限に着いたか |
| ask | 真偽・既定 false | 買う前に問い合わせ口（2.4）で相手に聞くか |
| answer | 表・省略可 | コマンドで呼ぶときの 2 回目に渡す、相手の答え（形は 2.4 の返事と同じ） |
| policy | 字・既定 fixed | 止め時の決め方の名前 |

費用の単位はドル。翻訳が値段の表から出す。

### 2.2 出力

```json
{"action": "rent", "why": "…", "consult": false, "prep": null,
 "policy": "fixed", "version": "<rentbuy の commit>", "guide": "<指南の commit>"}
```

- `action` は `rent`（借りる）か `buy`（買う）。
- `consult` は、まだ聞いていない相手に聞くべきとき true（コマンドで呼ぶときの 1 回目）。true になるのは、決め方が `buy` を出し、`forced` が false で、`ask` が true で、`deferred < defer_limit` で、`answer` が無いときだけ。それ以外は false。
- `prep` は、相手が進めると答えたときの準備の情報（compact なら焦点〔`/compact` の後ろに付けて、要約に残す話題を指す 1 行〕）。無ければ null。
- `version` は rentbuy の版、`guide` はコードが合わせた指南の版。どちらも commit の SHA で、式と部品のずれを後で見つけるために記録にも残す。

### 2.3 決め方

決め方は名前で選ぶ。中心は名前から関数を引く表を持ち、外から足せる。知らない名前なら `fixed` で決め、`why` にそう書く。

- `fixed`（最初の版）: 指南 3.5 の決定的な止め方。最悪で後から見た最適の 2 倍以内。`certain` が true なら累計と買いの費用（`miss` の分を引いた物）を比べ、`hazard` は使わない。`certain` が false なら、`hazard` が有れば来る確率と費用の比で決め、無ければ `buy`。
- `random`（後の段）: 買う時点を確率で選ぶ（最悪 e/(e−1) ≈ 1.58 倍。同じ原典）。乱数の種を記録に残す。
- `learned`（後の段）: 記録から待ちの長さや残りの要求の数の見込みを出し、見込みを信じる度合いを付けて止め時を決める（予測つきの ski rental。https://proceedings.neurips.cc/paper/2018/hash/73a427badebe0e32caa2e1fc7530b7f3-Abstract.html ）。

どの決め方にも、次の 2 つを中心で重ねる。

- 強制の上限: `forced` が true なら、決め方の結果によらず `buy`。compact では、Claude Code の自動の compact より前に打つための呼ぶ側の線に当たる。
- 延期の上限: 決め方が `buy` を出しても、`deferred < defer_limit` の間は、問い合わせ口（2.4。買う前に相手に聞く口）の答えが延期なら `rent` を返す。上限に着いたら、聞かずに `buy` を返す。延期した分だけ最悪の倍率は悪くなる。その幅は指南の式で出す。

### 2.4 問い合わせ口

買う前に、呼ぶ側が渡した相手（compact ならエージェント）に聞く口。中心は相手が誰かを知らない（持ち主 2026-10-24「匿名メソッド的に問い合わせる窓口だけ用意しておいてあげてもいいかな」）。

- 関数として呼ぶとき: `decide(inputs, consult=関数)`。中心は `buy` と出たときだけ関数を呼ぶ。関数の返事は次の 3 つのどれか。渡さなければ聞かずに決める。
  - `{"go": true, "prep": {...}}`: 進める。`prep` は買いの準備の情報で、compact なら焦点。
  - `{"go": false, "why": "…"}`: 延期する。
  - 例外か時間切れ: 聞かなかったのと同じに扱う。
- コマンドとして呼ぶとき: 関数を渡せないので 2 回に分ける。1 回目は `{"action": "buy", "consult": true}` を返し、呼ぶ側が相手に聞く。2 回目に、答えを `answer` に入れ、`deferred` を数え直して渡す。中心が状態を持たない形は崩れない。

### 2.5 3 つ以上の手（後の段）

keepalive を送る時刻には、手が 3 つある。送る（借りる）、compact する（払ってから、借りる額を下げる）、止める（買う）。借りる・リースする・買うのように手が 3 つ以上ある形は multislope ski rental と呼ばれる（Lotker, Patt-Shamir, Rawitz「Rent, Lease or Buy」STACS 2008。https://ar5iv.labs.arxiv.org/html/0802.2832 ）。compact で文脈が縮むと keepalive 1 本の額が下がるので、ちょうどこの形になる。最初の版は 2 つの手だけにし、`options` の並びを受ける形は、記録で効き目を測ってから足す。

## 3. 翻訳

翻訳は場面の事実を中心の入力に直す関数。何をどれに当てるかの式は指南 3.5 に従う。ここで決めるのは、受ける物と返す物だけ。

### 3.1 keepalive

- 受ける物:
  - モデル
  - 寿命: 今その会話で使っている値
  - 文脈の量: 会話の記録（transcript の JSONL）の最後の usage の `input_tokens`・`cache_read_input_tokens`・`cache_creation_input_tokens` の和
  - この待ちで送った本数の費用の累計
  - 待っている物が来ることが確かか
  - 最後の `api-request` の行の時刻
  - 1 本のキャッシュの書き込みと出力のトークン数: 値段の表の既定（実測で書き込み 335〜380・出力 5）。呼ぶ側が上書きできる
- 返す物: 中心の出力に、送る時刻 `next_at` を足した物。keepalive の `buy` は「止める」なので、問い合わせはしない（`ask` は常に false）。
- 送る時刻: 最後の `api-request` の行の時刻 + 寿命 − 余裕 `m`。`api-request` の行は、会話の記録の `"type": "api-request"` の行で、時刻は `timestamp`（UTC の ISO 8601）。Claude Code が要求を出すたびに 1 行書く（2026-10-24 の Claude Code 2.1.310 の記録で確かめた。公式の文書に書かれた形ではないので、形が変わったら読めなかったと記録して今の決まった数に戻る）。
  - キャッシュの寿命は要求の開始から数える（https://code.claude.com/docs/en/prompt-caching ）。記録の時刻は手元で要求を出す前に付くので、この測り方は安全側に寄る。
  - 今の 90 秒は、ターンの終わりから数えていたので、応答を作る時間も含んでいた。最後の要求から数えれば、その分は要らない。
  - `m` の最初の値は、記録で測った遅れから出す。遅れは、待ち受け（works-dispatch の、知らせを待って会話を起こすフックのプロセス）の見る間 1 秒と、送ってから要求が出るまでの遅れ（実測 0.3 秒）。下げるか戻すかは、記録で数えた外れの増えを指南 3.5 の境と比べて決める。

### 3.2 compact

- 受ける物:
  - モデルと寿命
  - 文脈の量
  - キャッシュが温かいか
  - 前の compact の後の文脈の量: 無ければ値段の表の既定（指南の例の値 2.5 万）
  - 前の compact から後に余分に読んだ費用の累計
  - 問い合わせの費用: 1 往復の額。買いの費用に足す
- 返す物: 中心の出力（`buy` なら打つ）。

## 4. 値段の表

`prices.toml` に置く。

- モデルごとの単価: 入力・出力・5 分の書き込み・1 時間の書き込み・読み。
- 原典の URL（https://platform.claude.com/docs/en/about-claude/pricing ）と、確かめた日。
- 実測の値と既定: keepalive 1 本の書き込みと出力、外れ率、compact の後の文脈の量と要約の出力の量。測った日と出どころ（受付番号か指南の節）を付ける。

呼ぶ側は JSON で値を上書きできる。works-dispatch の `claudex.py` の倍率と、my_notes の `claude_call.py` の `PRICES` は、この表を読む形に替える。

## 5. 判断の記録

判断ごとに JSONL を 1 行足す。置き場は `~/.cache/rentbuy/decisions.jsonl`。足し続ける物なので、上限を持つ（docs/standards/breakage-detection.md の「足し続ける物の上限」）。10 MB を超えたら `decisions.1.jsonl` に名前を替えて新しく始め、古い物は 1 つだけ残す。

- 全部の行: 時刻・場面・入力・出力・`version`・`guide`。
- keepalive の行: 指南の未測定の値を出すための欄を持つ（my_notes の受付 20261024-053049-2f6453）。
  - 4 つの時刻: 最後の要求・ターンの終わり・送ると決めた時・送った要求が出た時。
  - ここから、最後の応答を作る時間（ターンの終わり − 最後の要求）と、送ってから要求が出るまでの遅れ（要求が出た時 − 送ると決めた時）が出る。
  - 送った後の書き込みの量が大きければ外れと数える。集めると、余裕 `m` ごとの外れの割合 q(m) が出る。
- compact の行: 打った時のキャッシュが温かいか冷えているか、縮める前と後の文脈の量、compact の要求と直後の要求の使用量（どの寿命の単価で書いたかを含む）。冷えた compact と温かい compact を実測で比べるため。
- 結果の欄の埋め方: 判断の時点では、結果（外れたか・直後に何を書いたか）はまだ分からない。部品は状態を持たないので、結果の欄は記録を読む道具が、後で会話の記録と突き合わせて埋める。

## 6. 呼ぶ側の層: works-dispatch が持つこと

rentbuy の外。works-dispatch を受け持つ割り振りの部署が作る。

- keepalive: 送る時刻を 3.1 の `next_at` にし、何本まで送るかを中心の `action` に替える。送る直前に、待っている物の知らせが届いていないか（台帳・裏の処理の終わり）を見て、届いていれば送らない。台帳は、works-dispatch が知らせを 1 行ずつ足す受付箱の `log.jsonl`。my_notes の調べものの部署の 04:30〜04:38 の 1 本目は、裏の処理の終わりと同じ秒に送っていた。
- compact の指針:
  1. 判断するのは、待ちに入って入力欄（Claude Code の、人が文を打つ欄）が空の時、つまり keepalive を送る時刻だけ。同じ時刻には、先に compact の判断を聞き、打つなら keepalive は送らない（compact の要求がキャッシュを読むので、keepalive の代わりになる）。打たないなら keepalive の判断を聞く。
  2. compact の判断が `consult: true` を返したら、その時刻の keepalive の文を問いに替えて送る。問いは「compact を打つ時です。残す焦点を 1 行で返すか、今は困るなら skip: と訳を返してください。ツールは使わないでください」の形。要求は 1 回のままで、足すのは数十トークン。
  3. 返事は待ち受けが会話の記録の最後の応答から読み、2 回目の判断の `answer` に入れる。会話にコマンドを打たせない。進めるなら、今ある `--compact` の打ち方で、機械が会話の窓（その会話を映す端末の画面）に `/compact <焦点>` を打つ。skip なら延期と数え、上限を超えたら焦点なしで打つ。
  4. 役の本文から「10 万トークンを超えていそうなら」の目安を外す。`wake_hook.py` が `COMPACT_FLOOR` より小さい文脈では打たない判定は、rentbuy が在れば中心の `action` に替え、無いときだけ今のまま残す。
- Claude Code の自動の compact: 消さずに、線を文脈の上限に近い所まで上げて歯止めに残す。打つ時を選べず、ターンの途中でも打つので、ふだんの担い手にはしない。

## 7. 置き場と版

- コードと値段の表は、このリポジトリの新しいプラグイン `rentbuy/`（marketplace に載せる）。Python の標準ライブラリだけで書く。

```
rentbuy/
  .claude-plugin/plugin.json
  rentbuy/core.py        中心 decide・決め方の表・強制と延期・問い合わせ口
  rentbuy/policies.py    fixed（後で random・learned）
  rentbuy/translate.py   keepalive・compact
  rentbuy/prices.py      値段の表を読む・上書きを重ねる
  rentbuy/record.py      記録を足す・上限で切る・結果を埋める
  prices.toml
  bin/rentbuy            decide・keepalive・compact・fill（結果を埋める）のコマンド
  skills/rentbuy/SKILL.md  判断の読み方と記録の見方（薄く）
  tests/test_core.py     約束 1 本（8）
```

- 版の固定はタグでなく commit の SHA にする。このリポジトリはタグを作らない（持ち主 2026-09-29）。works-factory の `PIN`（使う版の commit の SHA を 1 行書いたファイル）と同じ形。
- works-dispatch は、Claude Code が入れたプラグインの控え（`installed_plugins.json`）から `rentbuy` の置き場を引き、関数として読み込む。見つからなければ今の決まった数で動く。
- 受け持ち: 割り振り（works-dispatch と tiers の部署）に足す。いちばんよく呼ぶのが works-dispatch のため。会社の形（`.claude/company.toml`）の受け持ちの表に足すのは、実装の段で行う。

## 8. 試験

置くのは、部品の約束 1 本。`fixed` の決め方は、どんな待ちの長さでも、延期が 0 なら費用が後から見た最適の 2 倍以内（持ち主 2026-10-24「テストは最小に」）。

## 9. 前例との差

前例の調べ（my_notes の受付 20261024-042909-7b5d39 と 20261024-051714-5bc31c）では、同じ物は見つからなかった。

- keepalive: 間隔の損益分岐の式や、keepalive のプラグイン（間隔 240 秒・7 本まで）はある。ただ、どれも決まった数で、止め時を決めていない。
- compact: OpenHands・Codex・Cline・Aider・Letta は、どれも文脈のサイズか割合の線で打つ。費用の式で打ち時を決める例は見つからなかった。
- 推論サーバーのキャッシュの保持: 期待の得で保持の時間を決める研究（Continuum）がある。ただし対象は GPU のメモリで、最悪の倍率の保証は無い。費用だけで決めた保持の時間を ski rental の最悪 2 倍とみる論文（https://arxiv.org/pdf/2309.03521 ）もある。
- 費用の判断を会話の外の部品に置き、keepalive と compact を 1 つの形にまとめたものは見つからなかった（web 検索の範囲）。

## 10. 段

各段の効きを記録で測ってから次へ進む。

1. 設計書（これ）
2. rentbuy の中心・翻訳・値段の表・記録と、works-dispatch の keepalive のつなぎ込み
3. compact の指針（問い合わせ・skip の上限・自動の compact の線）
4. 余裕 `m` の詰めと、statusline（画面の下の行）の表示
5. `random`・`learned` と 3 つ以上の手、寿命（5 分か 1 時間）の選び方の翻訳、works-factory の「前の会話を続けるか新しく始めるか」の翻訳

最初の版の範囲は 2 と 3。

## 11. 実装の割り振り

- rentbuy はこの設計書を書いた作業の部署で作る。
- works-dispatch の側（6）は割り振りに頼む。works-dispatch のファイルは割り振りの受け持ちのため（会社の形 `.claude/company.toml`）。
- my_notes の側は、my_notes の部署へ一覧で渡す。中身は、役「相談」の目安を消す、`autoCompactWindow`（Claude Code の自動の compact が打つ文脈の量の設定）を上げる、`claude_call.py` の `PRICES` を値段の表に替える、の 3 つ。

## 12. 持ち主と決めたこと（2026-10-24、この部署の窓で）

- 判断は全部プログラムから出す。人やエージェントに数を決めさせない。
- 指針は works-dispatch の層に置き、rentbuy は部署と切る。
- compact は待ちの時刻にだけ打ち、その前にエージェントに焦点か skip かを聞く（損の少ない方）。聞く口は中心に匿名の問い合わせ口として置く。
- Claude Code の自動の compact は、線を上げて歯止めに残す。
- 綺麗な部品として使い回せる形にする。
