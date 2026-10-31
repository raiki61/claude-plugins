# 部署の寿命・会話・rent-or-buy の鍵（2026-10-31）

会社の形（`.claude/company.toml`）で、部署の寿命・次の頼みのときの会話・keepalive を決める鍵を、3 つにまとめ直した記録。頼み 755c1f。持ち主の決め（2026-10-31「おｋ」「しばらく読めるように残さなくていいよ。全部入れ替えたらいいでしょ？」）。使い方は `skills/dispatch/references/roles.md` の「部署の寿命と会話の引き継ぎ」と「仕事が終わるまでの keepalive」に在る。

会社の形を書く人は、2 の鍵で書く。前の鍵を書いた会社の形は、そのままでは前の鍵が効かないので、2 の後の置き換え（roles.md の「部署の寿命と会話の引き継ぎ」に表が在る）で書き直す。works-dispatch を直す人は、3 の、鍵を役と受け持ちのどちらに置くかの決めに合わせる。

## 1. 前の形で困っていたこと

- 鍵が 5 つ（役の `persistent`・`fresh`・`keepalive`、受け持ちの `on_demand`・`per_ask`）に散り、同じ軸を役と受け持ちの別々の鍵で書いていた（寿命を役は `persistent`、受け持ちは `on_demand`・`per_ask` の組で書く）。`per_ask` は `on_demand = true` と組でしか効かず、組の 4 通りのうち 1 つは意味が無かった。
- 表示の語（「keep」「tmp」「clear」「continue」）が鍵の名前と別で、表示から鍵を引けなかった。
- keepalive は書いた部署だけに効き、claude-plugins も my_notes も、会話を持つ役の全部に `keepalive = true` を書いていた。書き忘れた役の部署はキャッシュが切れるまで放っておかれる。

## 2. 新しい鍵

- `lifetime`（部署の寿命）: `per-ask`（頼みごとに部署を立て、済んだら畳む）・`on-demand`（受け持ちごとに 1 つ、頼まれたときに立て、手が空いたら畳む）・`always`（立ち続ける）。
- `context`（次の頼みのときの会話）: `carry`（同じ会話を続ける。既定）・`new`（頼みごとに空の会話で受ける）。
- `rent_or_buy`（keepalive と compact を費用で決める）: 既定で有効。切るのは `rent_or_buy = false` だけ。送る間と文は定数で、`every`・`text` は無くした（設定で替えた会社は無く、送る時刻は rent-or-buy の部品が決める）。

表示（herdr の作業場の印・`--tree`）は `<lifetime> · <context>`（例 `always · carry`・`on-demand · new`）。per-ask は次の頼みが無いので `per-ask` だけ。`rent_or_buy = false` の部署にだけ ` · rent-or-buy off` を足す。機械が比べる値は「.」でつないだ ASCII のキー（`always.new` など。docs/standards/machine-readable-values.md の決まり 3）で、表示の語は表示にだけ使う。

前の鍵は読まない（読み替えの期間を置かない。持ち主の決め）。書いてあれば外した鍵として注記に出し、新しい鍵を添える（`known_keys.COMPANY_RETIRED`）。部署の属性（`company.lifecycle` の `persistent`・`ephemeral` と `company.fresh`）は git の設定に残る正本なので、名前を替えずに新しい鍵から書く。部署の寿命が `always` なら `company.lifecycle` は `persistent`、`per-ask` と `on-demand` なら `ephemeral`。役の `context` が `new` なら `company.fresh` は `true`、`carry` なら書かない。属性の名前を替えると、立っている部署の全部が読めなくなるため。

## 3. 役に書くか、受け持ちに書くか

今の重なり（前の鍵がどちらに書かれていたか）から決めた。

- `lifetime` は両方。役には `per-ask`（既定）と `always` だけを書ける。受け持ちは 3 つとも書け、省けば役の寿命を継ぐ。前の形でも、寿命は役（`persistent`）と受け持ち（`on_demand`・`per_ask`）の両方に在り、受け持ちの値が先に効いていた（担当の役は常設でも、受け持ちを on-demand にして畳む部署で立てる）。on-demand は「受け持ちごとに 1 つ」の寿命なので、受け持ちを持たない役には意味が無く、役に書けば問題として注記に出す。
- `context` は役だけ。前の `fresh` も役にしか無く、会話を空にするかは役の仕事の仕方（担当は頼みごとに空、窓口は引き継ぐ）で決まり、受け持ちごとに違う場面が無かった。
- `rent_or_buy` は両方で、受け持ちの値が先に効く。前の `keepalive` も両方に書けた。切りたいのは、ほとんど待たない受け持ち（機械的な短い仕事）のように受け持ちごとに分かれうるので、受け持ちでも切れるように残した。

## 4. 振る舞いの違い（前の鍵からの読み替えで揃わない所）

- 会社の形に無い役の部署と、会社の形の無いリポジトリの部署にも keepalive が効くようになった（既定で有効のため）。
- per-ask の役（`作業` など）の下で `lifetime` を省いた受け持ちは、役の寿命を継いで per-ask になり、`--ask <会社>/<受け持ち>` で直に宛てられる（頼みごとに「<受け持ち>：<受付番号の終わり 6 字>」の部署が立つ）。前は `on_demand` を書かない受け持ちは宛てられず、役で宛てて `--task` で名付けていた。claude-plugins の「一度きりの直し」がこれに当たる。
