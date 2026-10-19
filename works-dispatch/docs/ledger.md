# 受付箱の台帳の形と、頼みの状態の読み方

頼み（`--ask` で部署に出す仕事の依頼）が済んだか・動いているか・答え待ちかを一覧で出す口が無く、手で数えると数が合わなかった。そこで、頼みごとの今の状態と頼みの木を台帳から毎回作り直して出す `dispatch.py --todo` を足した。台帳（受付箱の `log.jsonl`）は正本のまま置き、行にフィールドを 2 つと種類を 2 つ足しただけで、今ある台帳は書き換えずに読める。`--todo` の出力を読むだけなら、「頼みの状態」と「見せ方」のセクションで足りる。台帳に新しい種類の行を書くコードを足す人は、下の「種類を足すときの決まり」を読む（足し忘れると試験が落ちる）。

語の中身は次のとおり。

- 会社: works-dispatch が部署を置いて回す、1 つの git のリポジトリ。
- 部署: 会社の中で、仕事ごとに立てる作業場（git worktree）と、そこで働く Claude Code の会話の組。部署が預かる仕事の範囲を受け持ちと呼ぶ。
- メインブランチ: 会社のリポジトリの main のブランチ。部署はブランチで作業し、`--land`（部署のブランチをメインブランチに入れる `dispatch.py` のコマンド）でメインブランチに入れる。
- 受付箱: 会社のリポジトリの `.git/company/inbox/`。頼みと納品の本文を 1 件 1 ファイルで置き、台帳 `log.jsonl` に出来事を 1 行 1 件の JSON で末尾に足す。
- 受付番号: 頼みや納品の 1 件ずつに付く番号（例 `20261018-014838-3cd0d2`）。末尾の 6 文字（`3cd0d2`）で呼ぶことが多い。この文書に出る受付番号は、my_notes（持ち主のメモのリポジトリで、これも会社の 1 つ）か claude-plugins（works-dispatch が入っているこのリポジトリで、これも会社の 1 つ）の受付箱で引ける。
- 納品: 頼みを受けた部署が、結果の要約を返すこと（`--deliver`）。残った疑問は、要約の頭書き（1 行目と閉じの行が `+++` の TOML）の `[[open]]` に 1 件ずつ、疑問（`question`）と担当者（`holder`。その疑問を最後まで追う者で、受付番号・`owner:choose`・`owner:confirm`・頼み元の名前のどれか）で書く。
- 回す: 受けた頼みを自分で済ませず、ほかの部署へ頼んで閉じること（`--ask … --forward`）。
- 足し: 頼んだ後で、受けている頼みに打つ追記（`--note`）。
- 射影: 正本の出来事の列から、読むための形（ここでは頼みの状態と木）を組み立てた物。イベントソーシングの語（projection）。
- 機械窓口: AI の会話を起動せずに、決まった台本（`--call` で呼ぶツール。`calls.py`）を動かして頼みを片づける役。片づいたら `call` の行、片づかなければ `miss` の行を台帳に書く。

作り直す所は `dispatch/nodes/ledger.py`、出すコマンドは `dispatch/todo.py`、行の形は `dispatch/schemas/ledger.schema.json`、`--todo --json` の形は `dispatch/schemas/todo.schema.json`。決めたのは 2026-10-18、受付 20261018-014838-3cd0d2（持ち主の頼みを、my_notes の社長室〔持ち主への中継の部署〕と段取り〔部署への頼みを配る部署〕が中継した物）。

## 困っていたこと

- 頼みが済んだ・動いている・答え待ち・取り下げのどれかを出す口が無かった。社長室が 2026-10-18 の朝に my_notes の台帳を `ask` の行と `deliver`・`forwarded` の行の突き合わせで数えると、頼み 527 件のうち閉じて見えたのは 345 件だけだった。取り下げ（`withdrawn`）、何段もの回し、別の会社の受付箱での納品を拾えないためである。今の読み方で同じ台帳を同じ日の夕方に読むと、my_notes が打った頼み 632 件（朝より後に増えた分を含む）は、済 592・取り下げ 18・順番待ち 17・動いている 3・届かず 2 で、どれにも当たらない物は無い。
- 回して閉じた頼みに足しを打つと「もう納品した」で止まり、回した先を台帳から手で探していた（my_notes の受付 730760 から 66374c へ回した例）。
- 残った疑問の担当者は、要約のファイルの文の中にしか無く、台帳から項目どうしでたどれなかった（受付 8482db）。

## 決めたこと

1. 正本は台帳のまま。形は変えず、フィールドと種類を足すだけにする。
2. 頼みの状態と木は射影で、ファイルに書かない。開くたびに全部の台帳を頭から読む（Fowler の Complete Rebuild〔射影を捨てて出来事の列から作り直す〕、Marten の Live の射影〔読むたびに出来事から組み、保存しない〕と同じ）。2026-10-18 に my_notes から打つと、4 つの会社の台帳の 3,684 行を読み、台帳を探すのに 1 秒、組むのに 0.6 秒、コマンドの全体で 3 秒ほどだった。待つのが苦になる長さ（10 秒ほど）になったら、射影を保存する形を考え直す。
3. 状態は、頼みに当たる行を時刻の順に当て、最後に当たった物にする（Linear の Agent Session が状態を「最後に出した activity」で決めるのと同じ考え）。ただし済・取り下げ・回したの 3 つは終わりで、後の行で戻さない。これは Linear には無い、works-dispatch の足しである（納品の後に来る足しや知らせの行で、済んだ頼みが動いているに戻らないため）。
4. 親子は、行のフィールドで項目どうしを結ぶ（iCalendar の RELATED-TO、JSCalendar の relatedTo と同じく、人や部署を経ずに受付番号で指す）。残った疑問の担当者は、要約の頭書き（TOML）の `[[open]]` の `holder` から、納品の行のフィールド `holders` に写す（文から拾わない。頭書きの無い古い要約だけは、下の「古い行の扱い」のとおり「残った疑問」の文から拾う）。
5. 見せ方は個人の仕事の一覧に寄せる。誰のターンかは出さない（部署の様子は今までどおり `--tree`〔会社ごとの部署の一覧〕が出す）。

5 は持ち主の言葉による。「ようは、個人のタスク管理ツールに収束すると思う最終的な見た目は。だから誰の番とかないし、そういう最終系を見据えた設計がいると思う」（2026-10-18。my_notes の受付箱の、社長室が受けた受付 5f4b05 への足し cf11c9）。

## 行の形

### よく出るフィールド

- `id`: 受付番号。頼み・要約・足しのどれの受付番号かは種類で違う（下の表と表の補い）。頼みを指さない種類（`moved`・`retired`・`call`・`miss`）の行には無い。
- `kind`: 出来事の種類。
- `at`: 時刻（UNIX 時刻の秒）。
- `status`: `ask` の行では結果で、`sent`（届いた）・`queued`（順番待ちに積んだ）・`failed`（届かなかった）。`deliver` の行では `sent`（頼み元に届けた）・`posted`（頼み元の会話が無く、台帳に置いた）・`failed`（届かなかった）。ほかの行にも別の値（`noticed` など）が付くことがあるが、状態には使わない。
- `to`: 宛先。ふつうの行（知らせでない行）では宛先の部署を表す辞書（`to.path` が宛先の作業場のパス）。知らせの行（宛先の待ち受け〔会話の裏で台帳を読み、自分宛ての行で会話を再開させる台本〕に宛てた行）では、宛先の作業場のパスの文字列。
- `from`: 打った側。`from.place` が打った作業場のパス、`from.name` が打った部署の名前。
- `place`: 行を書いた作業場のパス（`handed` などの行）。
- `file`: 頼みや納品の本文のファイルのパス。パスの中の受付箱のフォルダで、どの会社の受付箱かが分かる。
- `boss`: 頼み元。`boss.inbox` が頼み元の会社の受付箱のパス。
- `child`: `forwarded` の行の、回した先の頼みの受付番号。
- `for`: 回して閉じた頼みへの返しの納品の行で、返す先の頼みの受付番号。
- `why`: `waiting` の行の、答え待ちの訳。

### 種類

`id` と、頼みの受付番号の入るフィールドは、種類によって違う。下の表の「頼みのフィールド」がそのフィールドで、`ledger.KINDS`（種類からフィールドの名前への辞書）に書いてあり、`ledger.subject(row)` で引く。「状態」は、その行が頼みの状態をどう変えるか（「—」は変えない）。

| 種類 | 頼みのフィールド | 中身 | 状態 |
| --- | --- | --- | --- |
| ask | id | 頼んだ | status で決まる |
| queued | id | 順番待ちに積んだ（知らせの行。下の補い） | — |
| handed | id | 部署に渡した | 動いている |
| held | id | 渡さず待った | — |
| taken | id | 順番待ちから取った | — |
| reordered | id | 先頭に回した | — |
| withdrawn | id | 取り下げた | 取り下げ |
| forwarded | id | 回して閉じた | 済（回した） |
| deliver | ask | 納品した | 済 |
| note | ask | 足した | —（数える） |
| waiting | id | 答え待ちにした | 答え待ち |
| resumed | id | 答え待ちが外れた | 動いている |
| nudged | id | 止まった部署を動かした | — |
| knot | id | 互いの返事を待ち合う頼みの輪をほどいた | — |
| start | id | 受け持ちの部署を、起動方法のとおりに起動した | — |
| moved | 無し | 部署か窓口の会話を起動し直した（`status` が `skipped` なら、区切り〔次の頼みを渡す前か `--rest` を印したターンの終わり〕で、使用上限に当たる前にほかのアカウントへ移そうとして移さなかった。訳は `skills/dispatch/references/move.md`） | — |
| retired | 無し | 部署を畳んだ | — |
| call | 無し | 機械窓口が頼みを片づけた | — |
| miss | 無し | 機械窓口が片づけられなかった | — |

表の補い:

- 知らせの行は、`to` が文字列の行（上の `to` の説明のとおり、宛先の待ち受けに宛てた行）で、種類のフィールド `kind` とは別に、`to` の形で見分ける。知らせの行は、どの種類でも `id` が頼み（足しの知らせなら足し）の受付番号である（`--land` や `--move` が部署に送る、頼みを指さない知らせでは `null`）。
- 知らせでない `deliver` の行は、`id` が要約のファイルの受付番号で、頼みはフィールド `ask` にある（種類の `ask` とは別の物）。知らせでない `note` の行も、`id` が足しの受付番号で、頼みはフィールド `ask` にある。
- `start` の行の受け持ちは、会社の形（`.claude/company.toml`）の `[[skills]]` に書く、部署ごとの仕事の範囲で、起動方法はその受け持ちに書いた、部署を立てるコマンド（`--start`・`--due` が打つ）。
- `forwarded` の行は、`id` が回した元の頼み、`child` が回した先の頼みである。
- `ask` の行の `status`: `sent` なら動いている、`queued` なら順番待ち、`failed` なら届かず。順番待ちの頼みは、待ち受けが部署に渡すと `handed` の行で動いているになる（待ち受けが居なくて渡らないときは `--nudge` で動かす。`skills/dispatch/references/ask.md`）。届かずの頼みを works-dispatch は送り直さない。打った会話が打ち直すと、新しい受付番号の別の頼みになり、届かずの頼みはそのまま残る。
- `deliver` の行のうち、ふつうの行（知らせでない行）の届かなかった物（`status: failed`）と、回して閉じた頼みへの返し（`for` の有る行）は当てない。知らせの `deliver` の行は、そのまま済にする。
- `resumed` は、答え待ちのときだけ動いているに戻す。
- `note` は状態を変えず、射影のフィールド `notes` に足しの数を数える（終わった頼みへの足しも数える）。

### 足したフィールドと種類

- `ask` の行の `cause`: その頼みを打った作業場（打った部署の git worktree）が、そのとき受けていて、まだ納品していない頼みの受付番号（無ければ `null`）。イベントソーシングの言う causation id（その出来事を起動した元の出来事の id）に当たる。機械窓口（上の語の一覧のとおり、AI の会話を起動せずに決まったツールで頼みを片づける役）が `--land` の合図（メインブランチに入れた後に、会社の形の `[[land.after]]` のツールを呼ぶ決まり）で回す頼み（`dispatch/calls.py` の関数 `fire` が出す）は、`--land` でメインブランチ（main）に入れた部署が受けていた頼みを `cause` にする。
- `ask` の行の `title`: `--todo` に出す 1 行の題（頼みの本文の頭書きの `title` か、1 行だけの本文）。60 文字を超えれば切って「…」を付ける。`--take`（順番待ちの頼みを 1 件取り出し、打った部署が受けるか、ほかの部署に頼み直すコマンド）で回し直した行は、順番待ちの件に残した題を引き継ぐ。頭書きの入る前に積まれた件のように題を持たなければ `null`（そのときは上の古い行と同じく本文のファイルから読む）。
- `deliver` の行の `holders`: 残った疑問の担当者の並び `[{"holder": 担当者の文字列, "ask": 受付番号か null}]`。頭書きの `holder` が受付番号なら `ask` にそれを入れ、ほかは `null`。頭書きの無い古い要約から作った行では、`ask` に入るのは担当者の文字列の中の長い形の受付番号（`20261018-120448-b6778d` の形の全部）だけ。末尾の 6 文字だけで書いた担当者は `null` で書き、射影が読むときに頼みへ引く（読んだ台帳の頼みのうち、ちょうど 1 件に当たるときだけ）。
- `waiting`: 部署が頼みを人の答え待ちと印した（`--wait`。答え待ちの訳〔理由の文〕を `why` に書く）。打った作業場の会社と頼み元の受付箱の両方に書く。
- `resumed`: 人が文を打って答え待ちの印が外れた（`wake_hook.resume_from_wait`）。`waiting` と同じ 2 か所に書く。

相関の id（頼みの木のルートの受付番号）は行に持たない。親を `cause` でたどればルートは決まるので、行に重ねて書くと食い違う元になるだけだからである。今はどの会社の台帳も 1 台の機械に在り、全部を読める。会社ごとに別の機械に分かれ、親の行を読めなくなったら、ルートの受付番号を行に持つかを考え直す。

### 行の形の版

台帳の行そのものには版のフィールドが無い。`ledger.schema.json` は、試験で照合するときに台帳を `{"schema": 版, "rows": [行]}` の包みに入れて読む形で、`schema` の版はこの包みにだけ在る（今は 1）。

## 会社をまたぐ読み方

頼んだ会社と受けた会社は、同じ受付番号の行をそれぞれの台帳に書く。`--todo` は打った作業場の会社の受付箱から始め、読んだ行が指すほかの会社の受付箱を順にたどって、全部の台帳を読む（`todo.inboxes_from`）。ほかの受付箱は、次の 2 つの手で見つける。

1. 行の `file` と `boss.inbox` のパスの中の受付箱のフォルダ。
2. 行の `to.path`・`from.place`・`place` の作業場のパスを `git rev-parse --git-common-dir` で引いて、その会社の受付箱を出す。

2 が要るのは、相手の会社にだけ頼んだ（相手からはこちらに頼んでいない）とき、本文のファイルが頼んだ側の受付箱に在るので、1 では相手の受付箱が出てこないからである。在る場所だけ読む。

読んだ行は、全部のフィールドが同じ物を 1 つにまとめ（同じ行が両方の台帳に在るため）、時刻の順に並べる（`ledger.merge`）。会社が開いていなくても（herdr〔端末の画面を作業場に分けて会話を並べるツール〕に作業場が無くても）、台帳だけで組む。回した元の頼みの `ask` の行が、読んだ台帳のどこにも無いとき（読めない会社の台帳にだけ在るとき）は、`forwarded` の行から頼みの行を組み立て、回した先をたどれるようにする。

## 頼みの状態

| 状態 | 画面の字 | JSCalendar | iCalendar | 開いている |
| --- | --- | --- | --- | --- |
| queued | 順番待ち | needs-action | NEEDS-ACTION | はい |
| working | 動いている | in-process | IN-PROCESS | はい |
| waiting | 答え待ち | in-process | IN-PROCESS | はい |
| done | 済 | completed | COMPLETED | いいえ |
| dropped | 取り下げ | cancelled | CANCELLED | いいえ |
| failed | 届かず | failed | 無し | いいえ |

JSCalendar の列は Task の progress、iCalendar の列は VTODO の STATUS の値。「開いている」は頼み自身の値で、子か続きのどれかが開いていれば、その頼みも開いていると見る（射影のフィールド `open`）。届かずを開いている物に数えないのは、打った会話がその場で届かなかったと知るからである。回して閉じた頼みは、状態を済にし、`forwarded: true` を付ける（別の状態にはしない）。

## 頼みの木

ある頼み（子）の親は、次の順で 1 つだけ決める（射影のフィールド `parent_by` に、どれで決めたかを残す）。輪になる親はつながない。

1. `forwarded`: 子が、回した行の `child` に当たれば、その行の `id`（回した元の頼み）が親。
2. `cause`: 子の頼みの行の `cause` が指す頼み。フィールドが有れば、値が `null` か、読んだ台帳に無い頼みでも、下の 3 で補わない（親は無い）。
3. `inferred`: `cause` のフィールドの無い古い行だけ、打った作業場から親を推す。
   1. 子を打った時（同じ時刻を含む）までに作業場が受けた頼み（`ask` の `sent` の行の宛先か、`handed` の行の作業場が受けた物）のうち、子を打った作業場（`from.place`）のパスが、受けた作業場のパスと同じか、その下のフォルダである物を集める。
   2. 受けた部署の名前が分かる物は、子を打った部署の名前（`from.name`）と同じ物だけに絞る。
   3. 子を打った時にまだ閉じて（済・取り下げ・回したのどれかになって）いなかった物のうち、最後に受けた物を親と見る。

3-3 で閉じた物を外すのは、窓口（持ち主と話して仕事を配る、頼みを受けては返す常設の会話）が、前に受けて閉じた頼みの子として新しい頼みを出したと読まないためである。

続き（射影のフィールド `follows`）: 頼み A の納品の残った疑問の担当者が受付番号 B なら、A の続きに B を結ぶ（A → B）。担当者が部署の名前や持ち主の物は、射影のフィールド `questions` に残すだけで、開いている物には数えない。その疑問を閉じる出来事が台帳に無いからである。`holders` のフィールドの無い古い納品の行は、要約のファイルを読んで担当者を拾う（`todo.questions`）。

ルートは親の無い頼みで、多くは持ち主か人が会話から出した頼みである。古い行で 3 の推しが当たらなかった頼みもルートになる。

## 見せ方（`--todo`）

- `dispatch.py --todo`: 開いているブランチ（頼みの木で、ルートから分かれた部分。git のブランチではない）だけを、ルートを更新の新しい順に、字下げの木で出す。行は `- [状態] 題  受付番号  更新の日時`。更新の日時は、台帳の行のうちその頼みの受付番号についての行（頼み・納品・答え待ちなど）の、最後の行の時刻で、子の頼みの行は含めない。答え待ちには訳を、続き（納品の残った疑問の担当者になった頼み。子の頼みとは別。上の「頼みの木」の続き）には `→ 続き: 受付番号` を添える。
- `--todo <受付番号>`: その頼みから下だけ（済んだ物も出す）。末尾の 6 文字でもよい。
- `--all`: 閉じたブランチ（済・取り下げ・届かず）も出す。
- `--json`: `todo.schema.json` の形で、読んだ受付箱の並び `inboxes` と、上と同じ絞り込みをした木 `forest` を出す（全部の頼みの辞書は出さない）。
- `--html <ファイル>`: 1 枚の HTML のページに書く。CSS とスクリプトはページの中に在り、ブランチは HTML の details 要素で畳む。`--all` も受付番号も付けなければ、済んだブランチを初めは隠し、ページの「済んだ物も出す」で出す。続きの印は、ページの中のその頼みへ飛ぶ。

題は頼みの行のフィールド `title`（頼みの本文の頭書き〔1 行目と閉じの行が `+++` の TOML〕の `title`、頭書きが無ければ 1 行だけの本文そのもの。`--ask` が書き、60 文字を超えれば切って「…」を付ける）。`title` の無い古い行だけ、`deliver.task_title`（`dispatch/nodes/deliver.py` の関数）が本文のファイルから決める。次の順に見て、最初に取れた物を題にする。どちらも 60 文字を超えれば切って「…」を付ける。誰のターンか・どの部署が持つかは出さない。

1. 持ち主の言葉: 本文に「## 持ち主の言葉」のセクションか、「持ち主の言葉（そのまま）:」で始まる行があれば、持ち主の言葉を題にする。セクションなら、見出しの次の、字の在る最初の行。行の形なら、「:」の後ろに字があればそれを、無ければ次の字の在る行を取る。取った行の箇条の印（`- ` や `1.`）は外す。
   - 取った行が「で始まり、対になる」のすぐ後ろが行の終わり・次の「・（・、・。のどれかなら、その「」の中だけを題にする（「「都度が何個か」（補足）」なら「都度が何個か」）。
   - 」の後ろにほかの字が続けば、「」は言葉の一部なので外さず、行をそのまま題にする（「「困りごと」が題になる」はそのまま）。
2. 本文の最初の文（`deliver.ask_title`）: 持ち主の言葉が無ければ、本文を文（括弧の外の「。」で切った単位）に分け、次を飛ばした最初の文を題にする。
   - 回した側の添え書き（「…が回した:」から区切りの `---` まで）と、決まり文句の行（「前提が違う」で始まる行など）
   - 見出し（`#` で始まる行）
   - 誰からの何かだけを言う文（「社長室からの頼みです（穴の直し）。」「知らせです（返事は要りません）。」「段取りから社長室へ。」）

   文の頭の項目名（「困っていること:」「頼み:」など）は外す。飛ばした後に何も残らなければ、最初の行の頭の `#` を外して題にする。

見出しを題にしないのは、段取りの頼みが「## 困りごと」「## 困っていること」のような中身を言わない見出しから始まり、題が見出しの名前で並んだため（2026-10-19、my_notes の受付箱の頼み 679 件のうち 141 件）。見出しの名前の一覧を足して飛ばす形にしなかったのは、見出しの書き方が替わるたびに一覧を直すことになるため。部署の名前（`--task`）を題にしなかったのは、その場で立てる部署の名前が役の名前（「作業」など）とブランチの受付番号で、中身を言わないため。

木を文字から HTML 1 枚に出して畳む形は markmap（Markdown から mindmap を描くツール）と details 要素に倣い、済んだブランチを隠す切り替えは Workflowy・Dynalist・MindNode（アウトライナー）に倣った。ただし、それらのアウトライナーのように保存を自分で持つ形にはしない（正本は台帳だけ）。

## 足しを回した先へ送る

足しを打った頼みが順番待ちに無く、その頼みを受けている部署が無いか、その部署がもう納品していれば、`orders._forwarded_to` が射影の回した線（`parent_by` が `forwarded` の親子）だけをたどり、まだ終わっていない（済・取り下げ・届かずでない）頼みを探す（`ledger.forwarded_open`。回した先が済んでいれば、さらにその回した先をたどる）。

- 1 件: 「回して閉じた頼みなので、回した先の受付 … に足す」と出して、そちらに足す。
- 0 件: 「回した先もみな閉じた」で止める（新しい頼みで `--ask` する）。
- 2 件以上: 並べて止め、打つ人にどれかの受付番号で打ち直させる。

読む台帳は、打った作業場の会社と herdr に開いている会社の受付箱から、`--todo` と同じく行が指すほかの会社の受付箱へたどった物（`todo.inboxes_from`）で、開いていない会社にだけ在る回した先も見つける。

`cause` や推した親（`inferred`）の線はたどらない。回した先と違い、子の頼みは元の頼みの代わりではないからである。

## 採った物と採らなかった案

採ったのは、自前の小さな射影（Python の標準ライブラリだけ）である。ツールは借りず、考え方だけを借りた。

- イベントソーシングの射影と作り直し（Fowler、Microsoft、Marten）: 採った。正本は追記だけのログで、読む形は作り直す。台帳はもとからこの形に近い（追記だけ・頭から読む）。
- causation id（Marten と KurrentDB が出来事の付け足しのフィールドに持つ）: `cause` として採った。
- 状態を最後の出来事で決める（Linear）: 採った（終わりの状態を戻さない足しは「決めたこと」の 3）。
- 状態の名前（JSCalendar の progress、iCalendar の STATUS）: 対応を持つ形で採った。答え待ちは標準に無いので、in-process の中の 1 つとした。
- 項目どうしをフィールドで結ぶ（iCalendar の RELATED-TO、JSCalendar の relatedTo、Beads の依存）: `cause`・`forwarded` の `child`・`holders` の `ask` として採った。
- 個人の仕事の一覧の見た目（todo.txt の 1 行 1 仕事と済の印、Taskwarrior の端末の一覧）: 見せ方の形として採った。書式そのものは採らない（台帳の行は出来事で、仕事 1 件の今の値ではない）。

採らなかった案と訳:

- KurrentDB（出来事を貯めるデータベースのサーバー）: 常駐のサーバーが要る。works-dispatch は手元で打つたびに動く Python の台本で、常駐させる物を増やさない。
- Marten（.NET の、PostgreSQL に出来事を貯めるライブラリ）: 使う言語と置き場が違う。
- Python の eventsourcing ライブラリ: 保存の置き場をライブラリの物（SQLite・PostgreSQL など）に置き換えることになり、今の JSONL の台帳と、それを読む待ち受けを作り直すことになる。得る物は射影の作り直しの決まりだけで、それは数十行で書ける。
- MCP Agent Mail（エージェントどうしの受信箱を MCP のサーバーで出すツール）: 訳は 2 つある。1 つ目はライセンスで、MIT に付けた但し書き（rider）が、OpenAI と Anthropic とその関連会社と、それらのために動く者にどの権利も与えず、さらに、それらに向けてこのソフトウェアを使わせること（make available・permit access）も禁じる。works-dispatch の部署は Claude Code の会話で、モデルは Anthropic のサーバーで動き、ツールを通して受信箱を読み書きする。これが Anthropic に使わせることに当たるかは読み方が割れうるが、破れば許しがその場で切れる条項なので、当たるおそれのある使い方はしない。2 つ目は中身で、仕事の状態を自分では持たない（仕事の置き場には Beads を勧めている）ので、ライセンスを抜きにしても、頼みの状態の正本にはならない。
- Linear（課題管理のクラウドのサービス）をツールとして使う: 台帳を外のサービスに置くことになる。考え方（最後の出来事で状態を決める）だけ採った。
- Gas Town（多数のエージェントを束ねるツール）の problems の画面: 止まったエージェントを見つけて人に見せる、誰のターンかの画面である。部署の様子は `--tree` が持ち、`--todo` は誰のターンを出さないと決めた（「決めたこと」の 5）ので、重ねない。
- Beads（エージェント向けの課題の置き場）・Taskwarrior（端末の仕事の一覧のツール）を仕事の置き場にする: 正本が二重になる（台帳と別の置き場）。Taskwarrior の公式の文書は、ファイル共有で同期したときに仕事が merge されないと書く。
- 楽観的な並行制御（読んだ後に列が変わっていれば追記を断る。イベントソーシングの書き込みの定石）: 台帳の書き手は、書く前に台帳の中身を条件にしない（読んで確かめてから書く決まりが無い）ので、断る理由になる食い違いが起きない。同時の書き込みは、追記の形で開いたファイルに 1 行を 1 回で書くことで、行が混ざらないようにしている（`deliver.log`）。書きかけの行は、読む側の `deliver.records` が飛ばす。
- 相関の id を行に持つ（CloudEvents の拡張、W3C Trace Context の trace-id、Correlation Identifier の型）: 「足したフィールドと種類」のとおり、親からルートが決まるので持たない。
- 古い行を書き換えて移す（移行）: 古い行はフィールドが無いだけで、読み方の側で補える（`inferred` と `todo.questions`）。正本を書き換えると、ほかの会社の台帳と食い違い、取り消せない。
- 射影をファイルに保存する（スナップショット）: 毎回の読み直しで足り（「決めたこと」の 2）、保存すると正本との食い違いの元が増える。

## 古い行の扱い

移行は要らない。台帳は書き換えない。

- `cause` のフィールドの無い `ask` の行: 上の「頼みの木」の 3 の `inferred`（親の決め方の 1 つで、打った作業場が受けていた頼みから親を推す。どれで決めたかは射影のフィールド `parent_by` に残る）で親を推す。`cause` のように打った時に書いた値ではなく、`cause` の無い行に限って読む側が推して補う物である。推した親は台帳に書かず、読むたびに推す。
- `title` のフィールドの無い `ask` の行: 本文のファイルから題を読む（上の「題」）。
- `holders` のフィールドの無い `deliver` の行: 要約のファイルの「残った疑問」から担当者を拾う。ファイルが無ければ続きは無い物として読む。
- `waiting`・`resumed` の行が無かった頃の答え待ち: 印が部署の属性（worktree ごとの git の設定の `company.waiting`）にしか無かったので、台帳からは動いているに見える。知った上で残す。開いている物に数える側に寄るので、仕事は漏れず、その頼みが納品されれば済になるからである。

## 種類を足すときの決まり

台帳に新しい種類（`kind`）の行を書くときは、次の 2 か所に足す。

1. `dispatch/nodes/ledger.py` の `KINDS` に、種類の名前と、頼みの受付番号の入るフィールドの名前（頼みを指さなければ `None`）を足す。例: `"paused": "id",`。状態を変える種類なら、`build` の中の、行を時刻の順に当てる `for` の `elif kind == …` の並びにも足す（状態は `STATES` に在る物から選ぶ。新しい状態を足すなら、`STATES` と `todo.schema.json` の `state` と `progress` の `enum` にも足す）。
2. `dispatch/schemas/ledger.schema.json` の `rows` の行の `kind` の `enum`。

行のフィールドの意味を変える（今のフィールドを別の意味で使う・フィールドを消す）ときは、行に版のフィールドを足して `ledger.schema.json` の `schema` の版を上げ、`build` が版の無い古い行も読めるようにする。フィールドを足すだけなら版は上げない。

`dispatch/tests/test_ledger.py` の Catalog の試験が、次を照合する。

- コードの中で台帳に書く行（`kind` と `at` を持つ辞書と、知らせを書く `wake.notice` に渡す種類）の種類が、全部 `KINDS` に在るか。
- `ledger.schema.json` の `kind` の `enum` と `KINDS` が同じか。
- `todo.schema.json` の状態の値（`state` と `progress`）が `STATES` と同じか。

## 出典

my_notes の reference/ のノート（my_notes のコミット 1b116af1 の物）:

- [イベントソーシング（Fowler と Microsoft）](https://github.com/raiki61/my_notes/blob/1b116af12b63bfbd0ec00c6916584aea64f46044/reference/primary/architecture/event-sourcing.md)
- [Kreps のログ](https://github.com/raiki61/my_notes/blob/1b116af12b63bfbd0ec00c6916584aea64f46044/reference/primary/architecture/kreps-the-log.md)
- [KurrentDB](https://github.com/raiki61/my_notes/blob/1b116af12b63bfbd0ec00c6916584aea64f46044/reference/primary/architecture/kurrentdb.md)
- [Python の eventsourcing](https://github.com/raiki61/my_notes/blob/1b116af12b63bfbd0ec00c6916584aea64f46044/reference/primary/architecture/python-eventsourcing-library.md)
- [Marten](https://github.com/raiki61/my_notes/blob/1b116af12b63bfbd0ec00c6916584aea64f46044/reference/primary/architecture/marten-event-store.md)
- [MCP Agent Mail](https://github.com/raiki61/my_notes/blob/1b116af12b63bfbd0ec00c6916584aea64f46044/reference/primary/ai/mcp-agent-mail.md)
- [Gas Town](https://github.com/raiki61/my_notes/blob/1b116af12b63bfbd0ec00c6916584aea64f46044/reference/primary/ai/gastown.md)
- [Linear のエージェント](https://github.com/raiki61/my_notes/blob/1b116af12b63bfbd0ec00c6916584aea64f46044/reference/primary/task-management/linear-agents.md)
- [Beads](https://github.com/raiki61/my_notes/blob/1b116af12b63bfbd0ec00c6916584aea64f46044/reference/primary/task-management/beads.md)
- [todo.txt](https://github.com/raiki61/my_notes/blob/1b116af12b63bfbd0ec00c6916584aea64f46044/reference/primary/task-management/todo-txt.md)
- [Taskwarrior](https://github.com/raiki61/my_notes/blob/1b116af12b63bfbd0ec00c6916584aea64f46044/reference/primary/task-management/taskwarrior.md)
- [iCalendar の VTODO と RELATED-TO](https://github.com/raiki61/my_notes/blob/1b116af12b63bfbd0ec00c6916584aea64f46044/reference/primary/schema/icalendar-vtodo-related-to.md)
- [JSCalendar の Task](https://github.com/raiki61/my_notes/blob/1b116af12b63bfbd0ec00c6916584aea64f46044/reference/primary/schema/jscalendar-task.md)
- [CloudEvents](https://github.com/raiki61/my_notes/blob/1b116af12b63bfbd0ec00c6916584aea64f46044/reference/primary/schema/cloudevents.md)
- [W3C Trace Context](https://github.com/raiki61/my_notes/blob/1b116af12b63bfbd0ec00c6916584aea64f46044/reference/primary/schema/w3c-trace-context.md)
- [Correlation Identifier](https://github.com/raiki61/my_notes/blob/1b116af12b63bfbd0ec00c6916584aea64f46044/reference/primary/design-patterns/correlation-identifier.md)
- [エージェントの仕事の台帳の競合の比べ](https://github.com/raiki61/my_notes/blob/1b116af12b63bfbd0ec00c6916584aea64f46044/reference/secondary/ai/agent-work-trackers-rarely-document-rebuilding-views-from-an-event-log.md)
- [受付箱の台帳と保存の形の比べ](https://github.com/raiki61/my_notes/blob/1b116af12b63bfbd0ec00c6916584aea64f46044/reference/secondary/task-management/works-dispatch-ledger-is-append-only-event-log-not-columnar-file.md)
- [木を畳んで見せるツールの比べ](https://github.com/raiki61/my_notes/blob/1b116af12b63bfbd0ec00c6916584aea64f46044/reference/secondary/visualization/tree-views-that-fold-from-text-lack-done-marks-and-outliners-that-hide-done-keep-their-own-storage.md)
- [仕事の項目どうしをフィールドかコマンドで結ぶ標準の比べ](https://github.com/raiki61/my_notes/blob/1b116af12b63bfbd0ec00c6916584aea64f46044/reference/secondary/schema/task-standards-link-items-to-items-in-fields-or-commands-not-in-prose.md)

原典:

- https://martinfowler.com/eaaDev/EventSourcing.html
- https://learn.microsoft.com/en-us/azure/architecture/patterns/event-sourcing
- https://engineering.linkedin.com/distributed-systems/log-what-every-software-engineer-should-know-about-real-time-datas-unifying
- https://martendb.io/events/projections/
- https://docs.kurrent.io/server/latest/features/projections/system.html
- https://eventsourcing.readthedocs.io/en/stable/topics/persistence.html
- https://linear.app/developers/agent-interaction
- https://raw.githubusercontent.com/gastownhall/gastown/649b832b7672bc7a2dbef26f5983aba6198b819b/README.md
- https://raw.githubusercontent.com/Dicklesworthstone/mcp_agent_mail/fd9c518458daa1ac7cf74500aa37ed7bd72b8dd0/LICENSE
- https://www.rfc-editor.org/rfc/rfc8984.txt
- https://www.rfc-editor.org/rfc/rfc5545.txt
- https://raw.githubusercontent.com/todotxt/todo.txt/1d90c086533a2574f6039a756ada760ec672a53e/README.md
- https://raw.githubusercontent.com/GothenburgBitFactory/taskwarrior/53a315fa49d72198ddda7f28b9d5d9c25143ae10/doc/man/task-sync.5.in
- https://raw.githubusercontent.com/cloudevents/spec/v1.0.2/cloudevents/spec.md
- https://www.w3.org/TR/2021/REC-trace-context-1-20211123/
- https://www.enterpriseintegrationpatterns.com/patterns/messaging/CorrelationIdentifier.html
