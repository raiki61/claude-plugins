# /my-turn の掘る段を Workflow で回す設計（案）

/my-turn（attention のコマンド `commands/my-turn.md`。持ち主のターンの PR を進める）の、構造をとらえて木を掘る段を、Claude Code の Workflow（JavaScript の script が裏のエージェントを決まった順に回す仕組み。https://code.claude.com/docs/en/workflows ）に移す設計。
状態: 案（2026-11-16）。承認されるまで `commands/my-turn.md` は変えない。

呼び方: この文書のまとまりは「セクション N」、今の `commands/my-turn.md` の手順は「手順 N」、Workflow の段は「W1」〜「W10」。木の 1 つの問いを「ノード」、掘る出発点の問いを「ルート」と呼ぶ。head は PR のブランチの最新 commit。

語（今の手順と同じ意味）: 末端は、実物で確かめて答えが 1 つに決まる問い。正本は、同じ値が何か所かに在るときの元になる 1 か所。台帳は、既知の制約・判断・例外を書き並べた記録。自作は、世の中の定番で足りるのに手で作っている部分。世の中の解は、同じ問題を OSS・定番のツール・定番の手順がどう解いているか。相乗りは、1 つの直しで別の指摘も片づくことと、PR の外の issue・PR に乗れること。

## 1. ねらい

今の /my-turn の形（構造をとらえる → 一般の構造と比べる → 木を掘る → 反証 → 報告）は変えない。変えるのは回し方だけで、手順 11 の木の探索を、1 つの会話で順に回す形から、ノードごとに別のエージェントを立てる形にする。1 つの会話で回すと文脈は 1 つで、ノードが増えるほど 1 つあたりに割ける読みが減り、後ろのノードほど浅くなる。

あわせて次の 3 つを足す。

- コードの臭いを問う段（W4）。今の手順は設計の構造だけを問い、同じ事実の重なり・説明の量・台帳の中身・試験の重なり・育つ一覧を見る段が無い
- 数を機械に出させる（`my-turn-facts.py`。`attention/scripts/catchup.py` と同じく「事実は機械、判断は AI」）
- 前の回の結果の使い回しを、読んだファイルの指紋で機械が決める（セクション 7）

ノードは読むだけで、試験を回す・写しで試す・ツールを入れることはしない。Anthropic の Code Review も「a review works from reading the diff and the surrounding code, without building or running your code」（https://code.claude.com/docs/en/code-review ）。動かさないと決まらない問いは「未確認」とし、何を動かせば決まるかを報告に書く。

## 2. 全体の形

```
会話（/my-turn）                          Workflow（attention:my-turn-dig）
 手順 1-5  前提を取り直す
           my-turn-facts.py で事実を出す ─┐
           Workflow を起動してターンを終える ──→ W1 構造 → W2 一般の構造 → W3 比べる
                                          W4 コードの臭い
                                          W5 ルートを組む（コード）
                                          W6 木を掘る（深さごとに W7 で束ねる）
                                          W8 直し方の案と相乗り
                                          W9 反証
                                          W10 記録を書き、報告の材料を返す
 手順 16   持ち主への報告 ←───────────────┘（終わりの知らせで再開）
 手順 17/18 作者への下書き（持ち主とやり取り）
 手順 19   一時のファイルの片付け
 手順 20   見せる前の確かめ
```

- 会話に残すのは手順 1〜5 と 16〜20。報告と作者への下書きは、持ち主と何度もやり取りして詰めるので、報告を書いた文脈が会話に要る。
- Workflow はプラグインの `workflows/` に置き、`/attention:my-turn-dig` で呼べる（Workflow の文書の「Distribute a workflow in a plugin」）。会話は名前で呼び、入力を `args` で渡す。
- Workflow は裏で走る。会話は待ち続けずにターンを終え、終わりの知らせで手順 16 から続ける（Workflow の文書の「Watch the run」）。
- Workflow は途中で人の入力を受けない（Workflow の文書の「No mid-run user input」）。手順 13 の「それでも決まらなければ持ち主に聞く」は「決まらなかった問い」として返し、会話が手順 16 で持ち主に上げる。
- Workflow が使えない環境（`disableWorkflows` が真など）では、/my-turn は訳と直し方（`/config` の Dynamic workflows）を言って止まる。会話だけで回す道は残さない。2 つの道を持つと文が別々に直されてずれる。今の能力（Workflow 無しで回せる）を落とすので、セクション 13 に挙げる。
- /catchup との違いを `commands/my-turn.md` の頭に 1 文で書く: /catchup は持ち主がその場で答えを待つので裏のエージェントを立てない（一般の構造の 1 回を除く。`attention/skills/catchup/SKILL.md` の守ること 5）。/my-turn は待てる手順なので、掘る段を裏の Workflow で回す。

## 3. 置くファイル

```
attention/
  commands/my-turn.md          直す。手順 1〜5・16〜20 と守ること。手順 5 の後で facts を出し、Workflow を呼ぶ
  workflows/my-turn-dig.js     新規。Workflow の本体（1 本）
  scripts/my-turn-facts.py     新規。セクション 4 の数を JSON で出す（標準ライブラリだけ。run-python.sh から起動）
tests/
  my-turn-facts-case.py        新規。一時の git リポジトリで facts の数を見る
  my-turn-dig-dry.mjs          新規。script を偽物の agent() で空回しする
  my-turn-dig-map.json         新規。今の手順 6〜15 の文 → 移した先の段（セクション 9）
<PR の作業場の git dir>/attention/my-turn/   PR のリポジトリには commit しない
  <PR番号>.json                 記録。W10 が書き、次の回の --prior に渡す
  <PR番号>-diff.patch           会話が書く。差分の本文
  <PR番号>-thread.md            会話が書く。PR の本文・コメント・レビュー
```

- Workflow の script はファイルもモジュールも読めない（Workflow の文書の「Behavior and limits」）。段の指示の文・返す形（JSON Schema）・上限の既定は、全部 `my-turn-dig.js` の中に書く。
- script の中の指示の文は AI だけが読むので英語で書く。今の手順 6〜15 の文を訳して移し、元の手順の番号を文のそばにコメントで残す（`tests/my-turn-dig-map.json` と照合する）。
- script が受け取る物は `args` だけ。差分と PR の会話の本文は載せず、ファイルの path を渡してエージェントに読ませる。

## 4. 機械が出す事実（my-turn-facts.py）

`my-turn-facts.py <PR番号> [--prior <記録>]` が、手元の git から次を JSON で出す。AI はこの数を見て判断し、数え直さない。数えられなかった物は「数えていない」と出す（黙って 0 にしない）。

- 範囲: base…head と、前の回の head…今の head。変えたファイルと、足した行・消した行の数
- 説明の量: 足した行をファイルごとにコード・コメント・docstring に分けた行数と、コードに対する説明の比。言語は拡張子で見分け、分けられない言語は「分けていない」と出す
- 重なる文: 変えたファイルの間（同じファイルの中の離れた所を含む）で、正規化して 40 字以上が一致する文と、その箇所数（閾値は実装で決め直す）
- 足した一覧: 同じ形の行が続く塊（表・辞書・列挙・台帳の項目・無視の設定）と行数、その塊を触った commit の数
- 試験の期待値に出る外の名前: 試験の比べの式（`assert` など）に出る、リポジトリの外のパッケージの型・項目の名前
- この PR が足した正当化: 台帳・例外の一覧・無視の設定・コメントの「なぜ」に当たる足した行のうち、`git blame` が PR の commit を指す物
- 前の回の指紋の照合（`--prior` のとき）: 前の回の各ノードが読んだファイルについて、記録の blob の hash（以下「指紋」）と今の head の指紋

## 5. Workflow の段

入力（`args`）: PR の番号（`pr`）・リポジトリ（`repo`）・作業場の path（`workdir`）・立場（`stance`。レビュアーか作者か）・facts（`facts`）・ファイルの path（`files`）・前の回の記録の指紋の照合（`priorRecord`）・手順 4 で控えた前の指摘と前の回の発見とその状態（`priorFindings`）・手順 5 で読めなかった物（`unread`）・上限（`limits`）・遮断の目（ツールを持たず、渡した文だけで答える役。convergence-loops の `blind-judge`）の役の名前（`blindJudge`）・記録の日時（`now`）。

どの段も結果を JSON Schema で返す。どの段の指示にも、GitHub へ書き込まない（`gh` は読むだけ）と、作者の返事に書いた理由とこの PR が足した正当化を根拠にしない、を入れる。

- **W1 構造**（手順 6・10）: PR が触るシステムの構造（部品・流れ・正本・依存の向き・境目）を描き、種類を 1 文で言う。PR が作る仕組みと、それが補う前提も出す。自作の部品の一覧も出す（facts の追加行の集まり方を入口に、主目的でない所〔検査・試験・つなぎ〕に多ければ自作の候補として先に挙げる）。部品の言えない PR なら、その旨を返し、W2・W3 を飛ばす。
- **W2 一般の構造**（手順 7・8）: 遮断の目に W1 の最後の 1 文だけを渡して描かせる。一般論しか返らなければ、伏せた問い（この PR が選んだ所を、答えを伏せて問う文。「正本をどちらに置くか」「境目をどこに引くか」など）を足して 1 回だけ問い直す。それでも出なければ、出なかったことを返す。遮断の目の役が入っていなければ、ツールを使うなと頼んだ既定の役（general-purpose）で立てる。
- **W3 比べる**（手順 8・9）: W1 と W2 を並べ、違いごとに寄せるか外れてよいかを外の基準で決める。理由にリポジトリの今の状態を使わせない。外れてよいとした違いごとに、同じ問題があと 3 回来たとき何が積み上がるかを言わせる。
- **W4 コードの臭い**: セクション 8 の 5 つの問いを 1 問ずつ別の 1 体が、facts の数を入口に答える。W2・W3 と並べて走らせる。
- **W5 ルートを組む**（コード）: 前提を消す形はあるか（必ず 1 本・先頭）・W3 で寄せると決めた違い・W4 で臭いと答えた所・受けた指摘か前に出した指摘・前の回の発見で残っている物と未確認の物・PR が作る部品の全体への「世の中の解」（手順 13）・この PR より前から在る、本物のツール（パーサ・コンパイラなど）に処理させる検証の洗い出しと、この PR が足した物がその経路に乗っているか（手順 13。乗っていなければ穴）・W1 の自作の部品ごとの「世の中の解」と「自作を疑う」（手順 15）。PR の本文の枠と作者が頼んだ観点だけで組まない。
- **W6 木を掘る**（手順 11・13・15）: ノード 1 つに 1 体。{答え・確かめた物・決まったか（末端／子に分ける／未確認）・子の問い} を返す。末端か深さの上限まで掘る。根拠にできる出典は公式の一次の文書までで、二次の記事しか無ければ「未確認」に下げる。世の中の解を当てるノードは、ツールが一般の構造（W2）のどの部品を受け持つかを言い、PR が作る部品と同じ部品を受け持つ物だけを数え、「代わり」（まるごと置き換えられる）か「土台」（その上に作れば自前の処理が要らない）に分ける。上限で掘らなかった問いは「未確認」で残し、その上に乗る「消える」「要らなくなる」も「未確認」にする（守ること 5）。
- **W7 束ねる**（新しい段。今の手順には無い）: 深さごとに全部のノードを待ち、1 体に、違う親の下の同じ問いを 1 つのノードにさせる（親を複数持つ）。すべての子の問いがどれか 1 つの組にちょうど 1 回入っているかを script のコードが確かめる。畳んだ問いと捨てた問いも覚え、次の深さで同じ問いを立て直さない。深さの区切りで待つのは W7 だけで、1 つの深さの中のノードは待たずに流す。
- **W8 直し方の案と相乗り**（手順 12・14）: 決まった末端の全部から、直し方の案を手順 14 の順（要らなくする → 型で縛る → 出来合いのツール → 自作）で作り、案ごとに世の中の解を当て（手順 13 の「指摘の 1 件ずつとこちらの直し方の案に当てる」）、1 つの直しで片づく組と、壊し合う組を挙げる。PR の外の open な issue・PR を `gh` で探し、探した語と、乗れるかを書く。
- **W9 反証**: 決まった末端の全部（指摘の根拠・「問題無い」と閉じた物・「消える」の根拠）と、W8 の案と組ごとに、別の 1 体が反証を試みる。渡すのは問い・答え・確かめた物だけで、親の見立てと兄弟の答えは渡さない。判定は「残る／崩れた／確かめられない」で、確かめられない物は崩れた扱いにせず「未確認」で残す。崩れた末端に乗る案と組は外す。「残る」は正しいと確かめた印として報告に書かない。
- **W10 記録と報告の材料**: 記録の中身は script のコードが組み、1 体がそれを記録のファイルに書き出す（中身をエージェントに組ませると形が揺れる）。会話には手順 16 と 20 に要る物だけを返す: W1 の構造と W2・W3 で使った問いの文・仕組みと前提・ルートごとの末端で分かったこと・案と組と判定・相乗り・W2 で一般の構造が出なかったか・決まらなかった問い・未確認・件数・記録の path。

件数（立てた数・返った数・落ちたノード・上限で掘らなかった問い）は script のコードが数える。`agent()` が `null` を返したノードは「該当なし」でなく「未確認」とし、1 体の失敗で run 全体を止めない（Workflow の文書の「Behavior and limits」）。落ちたノードと掘らなかった問いは、問いの文も返す。

## 6. ノードからノードへの受け渡し

1 つの会話の木の探索では、親で読んだ物が文脈に残り、子がそのまま使えた。ノードごとに別のエージェントにすると、子は親の文脈を持たない。何も渡さなければ子は同じファイルを読み直し、全部渡せば文脈が膨らんで元の問題に戻る。そこで、親から子へは「要る物を短く、本文でなく在り処で」渡す。Anthropic の調べの仕組みも、子が結果を外に置き、軽い参照だけを親に返す（https://www.anthropic.com/engineering/multi-agent-research-system 「store their work in external systems, then pass lightweight references back to the coordinator」）。同じ記事は、子への頼みに「an objective, an output format, guidance on the tools and sources to use, and clear task boundaries」を書くよう求める。子どうしは直に話さず、script を通す。

ノードへの指示は次の順に組む。1 と 2 は全部のノードで同じ字にし、プロンプトのキャッシュを分け合わせる（Workflow の文書の「Cost」）。

1. 決まりの文
2. PR の土台: W1 の構造の要約・W2 の一般の構造の要約・facts の要約・ファイルの path
3. 通ってきた道: ルートからこのノードまでの、問いと答えの 1 行ずつ（祖先が決めた事を決め直さないため）。W7 で親を複数持ったノードは、親ごとの道を全部渡す
4. 親が確かめた物の在り処: ファイルと行の範囲・指紋・URL。本文は貼らない
5. このノードの問いと、受け持つ範囲の境（ここで決める事と、子に回す事）

子が返す物も短くする。答えは数行まで、確かめた物は在り処で返す。子の問いには、問う訳と見るとよい在り処を 1 行ずつ添え、孫への指示の項目 4 に使う。兄弟の答えは渡さない（重なりは W7 が束ねる）。

ノードの数の上限は深さごとに割り当てる。残りの数を親の数で均等に分け（親を複数持つノードは、W5 の順で先のルートに属す親に数える）、切るときは来た順でなく、属すルートの W5 の順、同じルートの中では親の順で、後ろから切る。後ろのルートほど浅くなるのを防ぐため。

## 7. 前の回の結果の使い回し

Workflow の resume は使わない。resume は同じ会話の中でしか効かず（Workflow の文書の「Resume after you leave the session」）、最初にプロンプトが変わった agent から後ろを全部回し直す（「Which agents run again」）。/my-turn の 2 回目は別の会話で回すことが多く、head が変われば W1 から後ろが全部回し直しになる。

代わりに script が明示で持つ。

- 記録（`<git dir>/attention/my-turn/<PR番号>.json`）に、ノードごとの問い・答え・確かめた物（読んだファイルと指紋・打ったコマンド・URL）・判定を残す。
- 次の回、会話は `my-turn-facts.py --prior <記録>` で今の指紋を出して `args` に載せる。script は、同じ問いのノードで、読んだファイルの指紋が全部同じで、コマンドを打っていないときだけ前の答えを使い、エージェントを立てない。
- URL を根拠にしたノード（世の中の解）は、その部品のファイルの指紋が全部同じときだけ使う。
- W1・W3・W4 は head が変われば必ず立て直す。W2 は W1 の最後の 1 文が前の回と同じときだけ使う（手順 7）。
- 使ったノードは、報告の「確かめた前提」に「前の回の確かめを使った（何が同じか）」と書く（手順 4）。

## 8. 手順の文の直し

- 手順 2: head が手元と違えば、`/catchup <番号>` で PR のブランチへ移ってから呼び直すよう言って止まる。
- 手順 4: push の後は、前の指摘の確かめとは別に、前の回の head から今の head までの差分を、初めて見る PR として構造の段から回す。差分は全部読む。
- コードの臭いの 5 つの問い（W4。答えを木のルートにする）:
  1. 同じ事実を何か所に書いているか。2 か所以上なら、1 か所から作れないか
  2. ファイルごとのコードと説明の比はどうか。説明が多い所は、コードが何を言えていないから補っているのか
  3. 足した例外・台帳・無視の設定の項目は、受け入れたリスクと、気づける事象で書いた見直す条件を持つか
  4. 足した試験は、既存の試験と重なっていないか。外のツールの中身に縛られていないか
  5. 版や事例が増えるたびに 1 行ずつ足す一覧を作っていないか。足し続けずに済む出どころは無いか
- 手順 13: 前の回の比べは、該当の部品が変わっていないときだけ使う（セクション 7 の指紋で機械が決める）。
- 手順 15: 手で並べた一覧（番号・型・特例の表）も自作に数える。
- 手順 17: 作者への文に直し方もヒントも書かない。文脈（作者自身の前の返事・台帳などの決まり）から入り、「こうなったとき、このコードだとこう困る」で止める。「ここはどう考えていますか」で揃えず、リポジトリのレビューのラベルの決まり（REVIEW.md など）があれば中身で選ぶ。直し方の案は持ち主への報告（手順 16）にだけ書く。根拠は Google の eng-practices（https://google.github.io/eng-practices/review/reviewer/comments.html 「Pointing out problems and letting the developer make a decision often helps the developer learn」）。
- 手順 19: 試験を動かさないので、会話が作った一時のファイルの片付けだけにする。
- 手順 20: W4 の答え・W9 の判定・落ちたノードと掘らなかった問いが報告に在るか、を足す。「入れたツール」の確かめは外す。
- 守ること 3: 作者の返事に書いた理由も、この PR が足した正当化に数える。

## 9. 今の手順の行き先

移し替えで元の能力を気づかずに削らないよう、今の手順の文を 1 つも落とさない。

- 手順 1〜5・16〜20 と守ること: `commands/my-turn.md` に残す（セクション 8 のとおり直す）。
- 手順 6〜15: 英語に訳して段の指示に移す。手順 6・10 → W1。手順 7 → W2。手順 8 → W2・W3。手順 9 → W3。手順 11 → W5（ルートの決め方）・W6（掘り方。動かして確かめる道は外す）。手順 12 → W8。手順 13 → W5・W6。手順 14 → W8。手順 15 → W5・W6。
- 照合: `tests/my-turn-dig-map.json` に、手順 6〜15 の文の 1 つずつと移した先の段を書き、表に無い文があれば赤にする。訳した文の中身が移った先に在るかは、作った会話と別の目が表を見て照合する。

## 10. モデルと上限

段ごとに `agent()` の `model` と `effort` を書く（script が書いたモデルは呼び出しごとの指定として効く。Workflow の文書の「Cost」）。誤りを後ろで止める仕組みがあれば sonnet、無ければ opus。反証は書いた段と別のモデルにする（https://www.greptile.com/blog/model-inversion ）。

| 段 | model | effort |
|---|---|---|
| W1 構造・W3 比べる | opus | high |
| W2 一般の構造 | 遮断の目の定義 | 定義のまま |
| W4 コードの臭い | sonnet | medium |
| W6 木のノード | sonnet | medium |
| W7 束ねる・W10 記録 | sonnet | low |
| W8 案と相乗り | opus | high |
| W9 反証（W4・W6 の答え） | opus | high |
| W9 反証（W8 の案と組） | sonnet | high |

- W4 と木のノードを sonnet にできるのは、決まった答えの全部を W9（opus）が反証するため。
- 上限の既定は深さ 4・ノード 80。`args` と /my-turn の引数で替えられる。
- 1 回の体数の見込みは 70〜185 体（W1〜W4 で 8〜9・ノードで 30〜80・反証で 30〜90〔決まった答えは多くてもノードと W4 の数で、そこに W8 の案と組が足される〕・束ねと W8・W10 で 3〜6）。Workflow の上限（1 回 1,000 体・同時に 16 体）の中に入る。25 体を超えると進み具合の行に `Large workflow` の警告が出るが、止めはしない（Workflow の文書の「Cost」）。
- トークンは未測定。

## 11. script の骨組み

形を見るための骨組みで、指示の文と返す形は省いてある。

```js
export const meta = {
  name: 'my-turn-dig',
  description: 'Dig the /my-turn question tree for one PR and return report materials',
  whenToUse: 'Called by /attention:my-turn after steps 1-5; not for direct use',
  phases: [
    { title: 'Structure' }, { title: 'Compare' }, { title: 'Dig' },
    { title: 'Fix options' }, { title: 'Refute' }, { title: 'Record' },
  ],
}

const A = args            // { pr, repo, workdir, stance, facts, files, priorRecord, priorFindings,
                          //   unread, limits, blindJudge, now }
const RULES = `...`       // shared rules: read-only, never write to GitHub, never cite the
                          // author's reasons or PR-added justifications ...
const ask = (stage, body, opts) =>       // same head for every node: RULES first, the node's own text last
  agent(`${RULES}\n\n## Stage ${stage}\n${body}`, opts).catch(() => null)

phase('Structure')
const structure = await ask('W1', W1_PROMPT(A), { schema: STRUCTURE, model: 'opus', effort: 'high' })
if (!structure) return { failed: 'W1' }

phase('Compare')                         // W2/W3 and W4 run side by side
const [compare, smells] = await parallel([
  async () => {
    if (structure.noParts) return null
    const general = await ask('W2', W2_PROMPT(structure.oneLine), { schema: GENERAL, agentType: A.blindJudge || 'general-purpose' })
    return general && { general, diff: await ask('W3', W3_PROMPT(structure, general),
                                                 { schema: COMPARE, model: 'opus', effort: 'high' }) }
  },
  () => parallel(SMELL_QUESTIONS.map(q => () =>
          ask('W4', W4_PROMPT(q, A.facts), { schema: NODE, model: 'sonnet', effort: 'medium' }))),
])

const roots = buildRoots(structure, compare, smells, A)   // W5: plain code, no agent

phase('Dig')
const seen = new Map()      // question key -> node, including folded and dropped ones
let level = roots, depth = 0, used = 0
while (level.length && depth < A.limits.depth) {
  const share = allot(level, A.limits.nodes - used)      // even share per parent, root order on cut
  const answers = await pipeline(share.kept, n =>
    reuse(n, A.priorRecord) ?? ask('W6', W6_PROMPT(structure, n), { schema: NODE, model: 'sonnet', effort: 'medium' }))
  used += share.kept.length
  markUnverified(seen, share.cut)                         // never silently dropped
  const merged = await ask('W7', W7_PROMPT(answers), { schema: CLUSTERS, model: 'sonnet', effort: 'low' })
  level = checkClusters(merged, answers, seen)            // every child exactly once; seen stops re-asks
  depth++
}
markUnverified(seen, level)                               // stopped by the depth limit

phase('Fix options')
const fixes = await ask('W8', W8_PROMPT(decidedLeaves(seen)), { schema: FIXES, model: 'opus', effort: 'high' })

phase('Refute')                       // only question + answer + evidence; no parent, no siblings
const verdicts = await parallel(refutable(seen, smells, fixes).map(x => () =>   // refuter model != writer model
  ask('W9', W9_PROMPT(x), { schema: VERDICT, model: x.fromFix ? 'sonnet' : 'opus', effort: 'high' })))

phase('Record')
const record = buildRecord(A, structure, compare, smells, seen, fixes, verdicts)
const wrote = await ask('W10', W10_PROMPT(record, A.files.record), { schema: WROTE, model: 'sonnet', effort: 'low' })
return materials(record, wrote, counts(seen, verdicts))   // counts: started / returned / null / cut
```

- `buildRoots`・`allot`・`reuse`・`markUnverified`・`checkClusters`・`decidedLeaves`・`refutable`・`buildRecord`・`materials`・`counts` は、エージェントを立てない普通の関数で、同じ入力に同じ答えを返す。
- `Date.now()` と `Math.random()` は script の中で使えない（Workflow の文書の「Behavior and limits」）。記録の日時は `args` の `now` で受け取る。

## 12. 試験

- `tests/my-turn-facts-case.py`: 一時の git リポジトリに、説明の多いファイル・重なる文・育つ表・外の型に縛られた試験を作り、セクション 4 の数が期待どおりに出るかを見る。分けられない言語で「分けていない」と出るか、`--prior` の指紋の照合も見る。
- `tests/my-turn-dig-dry.mjs`: script を、`agent()` などを偽物に替えて node で空回しする。偽物の `agent()` は、渡された JSON Schema に合う決まった答えを返す。深さごとの割り当て・束ねの検証・使い回し・`null` を「未確認」にする扱い・件数を、エージェントを立てずに毎回同じ答えで確かめる。JSON Schema の自己矛盾（`required` が `properties` の外）もここで見る。
- `tests/run.sh` に、上の 2 本と `tests/my-turn-dig-map.json` の照合を足す。
- エージェントの答えの中身は手元の試験では見られない。実装の後に、同じ PR を前の版と直した版で 1 回ずつ回して比べる。

## 13. 承認で見てほしい点

1. 今の /my-turn の形は変えず、手順 6〜15 の木の探索を、ノードごとに別のエージェントを立てる Workflow に移す（セクション 1・2）
2. Workflow が使えない環境では止まり、会話だけで回す道を残さない。今の能力を 1 つ落とす（セクション 2）
3. ノードは読むだけで試験を動かさない。今の手順 11 の「読むだけで決まらなければ動かして確かめる」を外す（セクション 1）
4. 親から子へは本文でなく在り処と通ってきた道を渡す（セクション 6）
5. 前の回の使い回しは resume でなく、読んだファイルの指紋で script が決める（セクション 7）
6. 上限の既定は深さ 4・ノード 80、1 回 70〜185 体の見込み（セクション 10）
