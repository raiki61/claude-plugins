# 借りるか買うかの部品が効いたかの集計（`--rent-effect`）

借りるか買うかの部品（rent-or-buy。keepalive を送り続けるか止めるか、compact を打つかを費用で決める部品）が、費用を下げたかを、毎回同じ数え方で出すための定義。打つ人と、数え方を直す人向け。数え方は `dispatch/rentfx.py` に在り、変えるときはこの文書も直す。パスは works-dispatch のフォルダからの物。

この文書の言葉:
- 部署: works-dispatch が仕事ごとに立てる、役を持った Claude Code の会話（README の冒頭）。待ち受けは、部署の会話の外で動き、会話が止まっている間に文を送るフック（`dispatch/wake_hook.py`）。
- 要求: Claude の API への 1 回の呼び出し。会話の記録に、使ったトークン（入力・キャッシュへの書き込み・キャッシュからの読み・出力）が残る。文脈は、要求が読んだトークンの全部（入力 + 書き込み + 読み）。新しい部分は、そのうちキャッシュから読まなかった分（入力 + 書き込み）。
- 寿命: キャッシュが読める間（5 分か 1 時間）。過ぎた後の要求は、文脈を書き直す（読みの単価でなく書き込みの単価を払う）。要求の読みが文脈の半分以上なら、読めた（キャッシュが残っていた）と見る。半分未満なら、書き直した（読めなかった）と見る（寿命を過ぎても読めることがあるので、時間でなく読みの量で見分ける）。
- keepalive: 部署の会話が裏の処理を待つ間に、キャッシュを切らさないよう待ち受けが送る短い文（`dispatch/nodes/role.py` の `KEEPALIVE_TEXT`）。
- 問い: compact の前に、待ち受けが会話に、要約に残す物を問う文（`dispatch/wake_hook.py` の `CONSULT_TEXT`・`TURN_CONSULT_TEXT`）。問いのターンの要求もキャッシュを読むので、keepalive と同じくキャッシュを温める。
- 本当の要求: keepalive と問いで始まったターンの要求を除いた要求。待ちは、本当の要求から次の本当の要求までの間。
- 区切り: 部署か窓口が、同じ仕事の前の部分が済んだと `dispatch.py --compact` で印した所。そのターンの終わりに、works-dispatch が会話へ compact を打たせる。文脈が `wake.COMPACT_FLOOR`（10 万トークン）より小さいときは、打つかを部品に問う。
- 自動の compact の線: 文脈がこの大きさに着くと、Claude Code が自分で compact を打つ（会社の形〔`.claude/company.toml`。部署の役ごとの設定〕の `autoCompactWindow` で役ごとに変えられる）。
- 基準の世界: 部品の無かった世界。下の「比べる世界」。

## 打ち方

```
python3 dispatch/dispatch.py --rent-effect [--since 2026-10-24T00:00:00Z] [--until 2026-10-28T00:00:00Z] [--json]
```

- 期間は `--since` 以上 `--until` 未満（UTC）。省けば 7 日前から今まで。
- 読むのは、期間の始まりより後に書いた会話の記録のうち、下の「見分け方」の印のどれかを含む物（サブエージェントの記録は読まない）。
- 部品の判断の記録（`~/.cache/rent-or-buy/decisions.jsonl`）は 10MB を超えると、今の記録が `decisions.1.jsonl` に改名され（前の `decisions.1.jsonl` は消える）、新しい記録が始まる。つまり読めるのは今の記録と、1 つ前の記録だけ。4 日で約 6.6MB なので、切れるのは約 6 日ごとで、残っている最も古い判断は 6〜12 日前の物。結果の行を足すには、判断から 6 日ほどの内に打てば確実で、10 日ほどは目安。

## 比べる世界

同じ会話の記録の上で、実際の世界と基準の世界の費用を比べる。基準の世界は、部品を入れる前の決め打ちの世界:
- keepalive は送らない。問いもしない。
- compact は、区切りで文脈が `wake.COMPACT_FLOOR` 以上のときと、自動の compact だけ。
- キャッシュの寿命と、自動の compact の線の設定（会社の形の `promptCacheTtl`・`autoCompactWindow`）は、記録のときのまま。これらは部品より前に決めた設定で、部品の効き目に入れない。
- 人が打った compact と /clear は、両方の世界で同じ所で打つ。

差はどれも「基準の世界の額 − 実際の額」で、正なら部品が安くした。額は、部品の `rent-or-buy prices <モデル>` が返す、モデルごとの API の単価（1 トークンのドル）で出す。この仕組みを使う持ち主は定額の契約なので、使用枠の減り方の目安として読む。

## 見分け方

会話の記録（Claude Code が書く、会話ごとの JSON Lines。`dispatch/claudex.py` の `talk_events` が、要求・ターンを始めた文・compact の出来事に読み替える）の、ターンを始めた文に、次の印を探す（`rentfx.py` の定数。`dispatch/tests/test_rentfx.py` の `Marks` が、今の待ち受けの文に含まれることを確かめる）。探す字は括弧の中。
- `ASK_MARK`（`good time to compact`）: 問いのターン。
- `PING_HEAD`（`keepalive`）: 文の頭（頭の「（」を除く）が keepalive なら keepalive のターン。今の文は `keepalive ping, no action needed. …` で始まる（10-23 の版は `（keepalive: …` と括弧付きで始まったので、「（」を除いて見る）。
- `JUDGED_MARK`（`費用の判断で会話を compact した`）: 部品の判断で打った compact の後の続きの文。その文の直前の compact 1 回が、部品の判断の物。
- `CUT_MARK`（`区切り〔--compact〕で会話を compact した`）: 区切りで打った compact の後の続きの文。
- ほかの compact は、Claude Code の記録の trigger が auto なら自動、manual なら人の物。

## 指標

### keepalive

待ちごとに、待ちの長さ（5 分以下・5 分〜1 時間・1〜12 時間・12 時間超・終わらなかった〔次の本当の要求が記録に無い〕）と、温めた物（keepalive を 1 本でも送ったか、問いだけか）で分ける。寿命は、待ちの前の要求までで最後に書き込みをした要求の、書き込みの寿命。待ちの間に compact か /clear が在れば、次の要求は作り直した文脈を書くので、その待ちは送った数と額だけ数え、下の寿命の比べ（避けた書き直し・両方払った・書き直した割合）に入れない。
- 送った額（`sent_cost`）: 待ちの間の keepalive のターンの要求の額の全部。
- 避けた書き直し（`avoided`）: 待ちが寿命より長く、次の本当の要求が実際は読めた（読みが文脈の半分以上）とき、読んだトークン ×（書き込みの単価 − 読みの単価）。上の端。
- 下の端（`avoided_low`）: 避けた書き直し × 温めずに寿命を超えた待ち（全部の行を通した数）のうち、実際に書き直した割合（`keepalive.expired_without_warming` の `share`。寿命を過ぎてもキャッシュが残ることがあるので）。
- 両方払った待ち（`failed`・`failed_sent_cost`）: 寿命を超えた待ちで、温めたのに次の要求が書き直した数と、その待ちで送った keepalive の額（問いだけの待ちは 0）。
- 文脈に残った分（`linger`）: keepalive と問いのターンが文脈に足したトークンを、後の本当の要求が compact か /clear まで読み続けた額（書き直した要求は書き込みの単価）。

### compact

基準の世界の文脈を、実際の文脈との差（delta）で、会話の頭から追う。
- 実際だけが打った compact（部品の判断の物・基準の文脈が `COMPACT_FLOOR` 未満の区切り・基準では線にまだ着かない自動）は、delta に縮めた分（前 − 後）を足す。
- 両方で打つ compact（人の物・基準の文脈が `COMPACT_FLOOR` 以上の区切り・delta が 0 以上の自動）と /clear は、delta を 0 に戻す。
- 基準の文脈（実際の文脈 + delta）が自動の compact の線に着いた本当の要求の前で、基準だけが自動の compact を打つ。その後の基準の文脈は、読んだ会話の全部の実際の自動の compact の後の文脈の中央値（期間の外の行も使う。自動の compact が 1 つも無ければ、読んだ会話の compact の全部の後の文脈の中央値）と、その要求の新しい部分にする。delta は負になりうる（早く縮めた世界は、次も早く縮める）。

数える額:
- 要約の見積もり（`summary`・`base_summary`）: 実際だけ・基準だけが打った compact ごとに、前の文脈 × 読みの単価 + 後の文脈 × 出力の単価。要約の要求そのものは記録に残らないので見積もる。
- 縮めた後の最初の要求（`first`・`base_first`）: 実際だけが縮めた後は、基準の額（前の文脈を、寿命の内なら読み、過ぎていれば書き、新しい部分を書く）− 実際の入力の側の額。基準だけが縮めた後は、基準の額（全部を書く）− 実際の入力の側の額。実際の入力の側の額は、その要求の入力・書き込み・読みを実際の単価で払った額（出力は含まない）。
- 文脈の大きさの差（`kept`）: ほかの本当の要求ごとに delta × 単価（実際に読めた要求は読み、書き直した要求は書き込みの単価）。delta は compact の差でだけ動き、keepalive と問いのターンが足した分は入らない（それは `linger`）ので、二重には数えない。
- 問いのターンの額（`asks`）。
- compact の差（`net`）= kept + first + base_first + base_summary − summary − asks。

自動の compact の線は、会話ごとに幅で持つ（会社の形の `autoCompactWindow` は役ごとで、記録からは読めない）:
- 会話に実際の自動の compact が在れば、その前の文脈の中央値（下の端も上の端も同じ）。
- 無ければ、下の端は、読んだ会話の全部の自動の compact の前の文脈の中央値（期間の外の行も使う。1 つも無ければ `BASE_AUTO_LINE` の 20 万。測った値でなく、下の端として置いた値）と、その会話で縮まずに着いた最大の文脈の大きい方。上の端は `DEFAULT_LINE`（線を書いていない 1M の窓のモデルの既定の約 96.7 万。Claude Code の設定の文書の値で、出典は `dispatch/claudex.py` の `AUTO_COMPACT_SETTING` の注）と、その最大の文脈の大きい方。

### 全体

部品が無かった世界との差 = keepalive の差（避けた書き直し − 送った額）− 文脈に残った分 + compact の差。下の端 = keepalive の下の端 − 文脈に残った分 + compact の差の `low`（線の下の端で数えた物）と `high`（線の上の端で数えた物）のうち小さい方。上の端 = keepalive の上の端 − 文脈に残った分 + 大きい方（線が高いほど compact の差が小さくなるとは限らないため、どちらが小さいかは数えてから決める）。keepalive の下の端・上の端は、上の `avoided_low`・`avoided` を使った keepalive の差。

## 判断の記録と結果の行

待ち受けは、keepalive と compact の判断ごとに、鍵（`key`。`<会話の id>/<8 桁の hex>`）を部品に渡し、部品は判断の記録に残す（`wake_hook.decision_key`）。`--rent-effect` は、期間の判断の記録を読み、鍵の付いた判断のうち、判断の時刻を含む待ちが閉じた物に、結果の行を足す（`rent-or-buy outcome`。同じ鍵の結果が在れば足さない）。鍵の無い昔の判断は結べず、その数を出す。

結果の行の `paid` は選んだ手で実際に払った額、`alternative` は選ばなかった手の見積もり（見積もれなければ null）、`detail` は判断の手（`action`）と待ちの長さ（`gap`。秒）:
部品の keepalive の判断の答えは、送る（`action` が rent。借り続ける）か止める（buy。書き直しを買う）かと、送る 1 本の額（`rent`）を持つ。間に compact か /clear が在った待ちの keepalive の判断には、結果の行を足さない。
- 送ると決めた判断: `paid` は判断の後に最初に送った keepalive のターンの額。`alternative` は、送らなかった場合に、判断の直前の要求（判断の時刻以前で最後の要求。本当の要求・keepalive・問いのどれでもよい）から寿命が過ぎた後に次の本当の要求が来るなら、その要求が読んだトークン ×（書き込みの単価 − 読みの単価）、来ないなら 0。
- 止めると決めた判断: `paid` は次の本当の要求が書き直したならその額、読めたなら 0。`alternative` は、要った本数（判断の直前の要求から次の本当の要求までの間 ÷ 寿命。切り捨て）× `rent`。
- compact の判断: `paid` は 0、`alternative` は null（compact の得失は、上の compact の数え方で会話ごとに出す）。

## 見積もれない物と前提

- compact の後のやり直し（要約に残らなかった事を読み直す・やり直す仕事）は、記録から割れない。出力に「部品の compact 1 回あたり、これを超えるやり直しがあれば損」の額（compact の差 ÷ 実際だけが打った compact のうち、部品の判断の物と区切りの物の数）を出す。compact の差には自動の compact の分も入るが、分母には自動の compact の数を入れない。
- 長い待ちで、基準の世界が delta の分も書き直す額（keepalive と compact の掛け合わせ）は数えない。
- 要約の要求と、両方の世界の出力の違い（keepalive と問いのターンの出力は、送った額に入る）は、上の見積もりのとおり。
- サブエージェントの要求は数えない。入力が一定のトークンを超えると単価が上がるモデルでも、上がる前の単価で数える。
- 単価を引けないモデルの要求は 0 ドルで数え、そのモデルの名前を出す。

## 出力

`--json` の形（どの額もドル）:
- `since`・`until`・`sessions`（読んだ会話の数）
- `keepalive.rows`（`<待ちの長さ>・<温めた物>` ごとに `waits`・`sent`・`sent_cost`・`avoided`・`avoided_low`・`failed`・`failed_sent_cost`）・`keepalive.total`・`keepalive.net`（`low`・`high`）・`keepalive.expired_without_warming`（温めずに寿命を超えた待ちの、`waits` 本のうち書き直した `rewrote` 本と、その割合 `share` = `rewrote` ÷ `waits`。`waits` が 0 なら null。`avoided_low` に掛ける）
- `asks`（`turns`・`cost`）・`linger`
- `compact.low`・`compact.high`（`count`〔`judged`・`cut`・`auto`〕・`shared`・`summary`・`base_auto`・`base_summary`・`first`・`base_first`・`kept`・`net`・`break_even_redo`）・`compact.seen_line`（読んだ会話の全部の自動の compact の前の文脈の中央値。1 つも無ければ `BASE_AUTO_LINE`）・`compact.auto_post`（基準だけが打つ自動の compact の後の文脈）・`compact.auto_seen`（読んだ自動の compact の数）。`compact.low`・`compact.high` の `shared` は両方で打った compact の数、`base_auto` は基準だけが打った自動の compact の数、`break_even_redo` は「見積もれない物と前提」の最初の額
- `net`（`low`・`high`）・`unknown_models`・`outcomes`（`recorded`・`duplicates`・`keyless`・`why`。`why` は部品の記録を読めなかったか書けなかった訳で、無ければ null。そのとき `recorded` は 0）
