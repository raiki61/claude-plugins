# 自分の番の PR（と指した issue）の枝ごとに作業場を作って会話を起こすライン（dispatch）の設計（2026-10-14・下書き）

状態: 下書き。持ち主はまだ通していない。作り手役（計画を立てるのに足りない問いを出す役）に一度読ませ、出た問いと持ち主の答えを入れてある。

## 平易版（3 行）

- 持ち主（このリポジトリの作者で、この道具の利用者）は毎回、`/whose-turn` で自分の番の PR を探し、空いている作業場を 1 つずつ選んで Claude Code を起こし、`/catchup <番号>` と決まった 2 ターン目の文を手で打っている。
- この手作業を機械にやらせる。PR を集める、開いている会話と重ならないものに絞る、アカウントを選ぶ、枝ごとの作業場（git worktree）を作る、起こして 2 ターン分を打つ、までをスクリプトがやり、AI は起こした会話の中でしか動かない。issue から始める作業も、issue に結んだ枝の作業場を作って起こせる。
- 置き場は works の中の、darkfactory と並ぶ 2 本目のライン。手順を、入力と出力を JSON で決めたノードに分け、ほかの流れからもノード単位で使えるようにする。作業場は、蓄えた固定の作業場を使い回さず、枝ごとに元の clone から worktree を作る。作る・並べる・消すは herdr の worktree の口に任せ、herdr を呼ぶのは 1 つの口（herdr アダプタ）だけにする。

## 0. 語

- **持ち主**: このリポジトリの作者で、この道具を使う人。決めるのは持ち主。
- **herdr**: AI のコーディングエージェント向けの端末の管理の道具（https://herdr.dev）。端末を workspace（作業場の単位）とペインに分けて並べ、各ペインで動くエージェントの状態（`idle`・`working`・`blocked`・`done`）を画面から判定して出す。外からはコマンド（`herdr pane run`、`herdr agent prompt` など）で動かせる。版は 0.x で、互換を約束していない。
- **attention**: このリポジトリの別のプラグイン。GitHub だけを見る。`/whose-turn` は、開いている PR と issue を全件取り、誰の番かを機械で分けて出す（本体は `attention/scripts/whose-turn.py`）。`/catchup <番号>` は、その PR の枝へ作業フォルダを移し、何の PR で前回からどうなったかを説明する。
- **Archon**: AI の処理の流れをグラフにして YAML で書き、機械が順に回す道具。
- **works-factory**: 持ち主の別のリポジトリ（raiki61/works-factory）にある、Archon の上で動く修正の工場。流れはグラフの YAML だけが持ち、各ノードは引数と JSON のファイルで入出力し、ノードが呼ぶ Python の助け手は流れも Archon も知らない、という作りをとる。この設計はその作りに倣う。
- **作業場**: 1 つの Claude Code の会話を走らせる端末（herdr の workspace）と、その中の checkout（元の clone の git worktree）の組。枝ごとに 1 つ作る（3 節）。持ち主はこれまで、herdr の workspace `work0`〜`work10` と、それぞれの clone `~/src/guided-resolver-work0` 〜 `-work10` を蓄えて使い回していた。
- **アカウント**: Claude Code を起こす 1 つの名義。持ち主は今、Claude のサブスクの `main`・`p1`・`p2`・`p3` の 4 つを使い、シェルにアカウントごとに Claude Code を起こす関数（`claude`・`claude-p1`〜`claude-p3`）がある。設定には、使用率の枠の無いアカウント（Ollama で起こすものなど。5 節の例の `local`）も並べられる。
- **使用率の控え**: `~/.cache/claude-limits/<アカウント>.json`。持ち主の `~/.claude/statusline.sh` と `~/.config/herdr/limits.sh` が書く。形は `{"five_hour": {"used_percentage", "resets_at"}, "seven_day": {...}, "updated_at"}` で、`resets_at` は Unix 時刻。
- **2 ターン目の文**: `/catchup` の返事の後に、持ち主がいつも打つ決まった文。
- **ライン**: works の中で、1 つの仕事を端から端まで回す流れ。今は darkfactory（ソフトの修正を Archon の上で回すライン）だけがある。
- **ノード**: 流れの 1 段。入力と出力を JSON で決め、単独でも呼べるコマンドにする。

## 1. 持ち主が決めたこと

2026-10-14 に持ち主が決めた。記録はこの節が正。

- 置き場は works。works は「環境の上で仕事を回す」くくりで、darkfactory はその中のソフトの修正のライン。今回のものは並ぶ 2 本目のラインとする。既存のプラグイン（attention など）は GitHub にしか寄らないまま保ち、組み合わせて herdr と持ち主の環境に寄る部分を works に置く。
- できる作業はスクリプトでやり、AI を使う所は最小にする。
- 対象は、`/whose-turn` の「自分の番」の PR 全部（人の PR のレビューを頼まれたものも含む）のうち、今開いているどの会話にも無いもの。
- アカウントは、週の枠の切り替わりがいちばん近いものを選ぶ。週の使用率が 95% に達したアカウントは選ばない。
- その PR の作業場で、選んだアカウントの Claude Code を起こし、1 ターン目に `/catchup <番号>`、その返事が終わってから 2 ターン目に決まった文を打つ。そこで止める。
- ~~開いている会話は、入力待ちでも勝手に閉じない。持ち主が置いている可能性がある。~~ 2026-10-15 に下の決めで置き換えた。
- herdr を使うのは、端末ごとに別のアカウントで Claude Code を走らせるため。
- 作業場は、固定の work0〜10 を蓄えず、作業ごとに作る（「0~10個たくわえるんじゃなくて」）。~~同じ枝を複数の場所で開けるように、worktree でなく clone にする。作業場の名前は、フォルダも herdr の作業場も `<リポジトリの名前>-pr-<番号>` でそろえる。~~ 2026-10-15 に下の決めで置き換えた。
- 作り方は、works-factory の作りに倣い、ノードに分けて入出力をしっかり決め、ほかからも使いやすくする形でよい。

2026-10-15 に持ち主が足した決め（PR ごとの場所の一生を 1 つのコマンドで回す。「そのライフサイクルを極力ひとつのコマンドで自動化したほうがいい」）:

- 自分が作者でレビュアーの付いていない PR は、開くが `/catchup` だけを送る（2026-10-15 は「自分のレビュワーついてない作業のやつはたてなくていい」で開かなかったが、2026-10-16 に「いつも開くようにして、my-turn はいらない」に変わった）。レビュアーは人へのレビューの依頼か、作者のほかの人のレビュー。Bot（copilot など）は数えない。`--pr` で指したものは開く。
- 相手の新しい返事が有れば、同じ場所でもう一度レビューする（「新しい返事があったらその場所を使う」）。会話は新しくする（2 回目も前の会話を持たない新しい目で見る）。使い直すのはフォルダ（checkout）だけで、ペインは残さない（「どうせ閉じるって行為が発生するなら、ペインは置いておかなくてもいい」）。古い会話を終えてペインの作業場を畳み、同じフォルダに新しい作業場と会話を立てる。
- 閉じた PR の場所は、同じコマンドで片付ける。関係ないリポジトリの clone を巻き込まない（「関係ないリポジトリのCloneを巻き込まないように注意してね掃除するときは」）。

2026-10-15 に持ち主が足した決め（場所の決め方を作り直す。「もっと仕様の最適化したほうがいいんじゃない。その周り。汚いのだけは嫌だよ」）:

- 場所の鍵は PR 番号でなく枝にする。issue から始める作業は、まだ PR 番号が無いので、PR 番号では場所の名前を決められない（「PR番号まだわかってないんじゃないの。issueしかないから」）。枝の名前は issue の番号を持つ形にする（「ブランチ名は代表issue番号とかの方がいいのでは」）。PR の番号とタイトルは、herdr のペインに出ている（「PRはherdrのpaneに出てるので」）。
- 作業場は git worktree にする。調べた並行作業の道具（Orca・Conductor・Vibe Kanban・Sculptor・Claude Squad）は、どれも作業場を枝の worktree にし、issue と PR をそこへの入口として結ぶ。GitHub は `gh issue develop` で issue と枝を結ぶ。同じ枝を 2 か所で開けない worktree の縛りは、送り直しも同じ場所を使い直す今の決めでは当たらない（3 節）。持ち主「いいですよ」。
- 作る・並べる・消すは herdr の worktree の口（`herdr worktree create`・`list`・`remove`）に任せ、自作を減らす（「herdrの機能を使っちゃってもいいし。すでにherdrロックインなので」）。herdr を呼ぶのは herdr アダプタ（`herdr.py`）の 1 か所だけにし、ノードは場所と枝の言葉だけで書く（「herdrアダプタみたいなのを作ってそこから通信すればよいかな」）。
- 道具は herdr のまま。SSH 越し（VS Code の Remote-SSH で、Mac の画面には誰もログインしていない）で使えるかを比べ、herdr を採った。比べた記録は持ち主のノートの側にある。

2026-10-15 に持ち主が足した決め（返事待ちの PR を開き直さない）:

- 前に送った控え（`dispatch-sent.json`）が有り、その送った時刻より後に自分以外の人の動き（コメント・レビュー・commit。Bot は数えない。fresh の `no_news` と同じ見方）が無い PR は、会話が開いていなくても開き直さない。結末は `no_news`。それまでは会話が無ければ何でも作っていたので、返事待ちの PR を、持ち主が会話を閉じただけでもう一度レビューしていた。
- 控えの head が今の PR の head と違う（作者が push した）なら、動きとして数える。commit の時刻を見れば同じになるはずだが、force-push で古い時刻の commit が来ることがあるので、head の違いでも動きとする。
- `--pr N` で名指したときは、今までどおり開く（持ち主の明示）。

## 2. 流れとノード

入口は `dispatch.py` の 1 つで、引数で 3 通りに分かれる。流れの順を持つのは入口だけ（D3）。

- **一覧で回す**（引数なし）: `[prs]` で自分の番の PR を集め、送り直し（fresh）と片付け（clean）もする。
- **`--pr N`**: `[prs]` の代わりに、指した PR を gh で読む。fresh と片付けはしない。送った控えに一覧の回の印（`via: listing`）を付けないので、後の一覧の回で自分の番でない PR として閉じない。
- **`--issue N`**: `[prs]` の代わりに、issue に結んだ枝を読む（3 節の「issue から始める」）。fresh と片付けはせず、turn は 1 ターン目で止める。

```
[prs] 自分の番の PR ──┐（--pr: 指した PR／--issue: issue に結んだ枝）
[sessions] 開いている会話 ┤
                       ├─► [fresh] 外す PR・送り直す PR（一覧だけ）
[cost] 1 件あたりの見積もり ┤
[accounts] アカウントの順 ─┴─► [assign] 割り振りの案 ──► （--dry-run はここで report へ）
   ──► [turn の close_session・clean の release] 送り直す PR の古い会話と作業場を畳む（一覧だけ）
   ──► [provision] 枝の作業場 ─► [launch] 起こす ─► [turn] 1 ターン目 ─► [turn] 2 ターン目（--issue・--no-second は送らない）
   ──► [cost] 1 件あたりを測って覚える ─► [clean] 自分の番でない PR の会話を閉じ、閉じた PR の場所を片付ける（一覧だけ）─► [report]
```

| ノード | 外に書くか | いつ | 入力 | 出力 |
| --- | --- | --- | --- | --- |
| prs | しない | 一覧だけ | リポジトリ | PR の並び |
| sessions | しない | 毎回 | 設定 | 会話の並び |
| fresh | しない | 一覧だけ | 会話・PR の動き・送った時刻 | 外す PR・送り直す PR |
| accounts | しない | 毎回 | 設定・使用率の控え | アカウントの順 |
| cost | 控えだけ書く | 始める前（読む）と turn の後（書く） | 使用率の前後 | 1 件あたりの見積もり |
| assign | しない | 毎回 | 上の並び・枝の場所 | 割り振りの案 |
| provision | する | 案の行ごと | 案の 1 行、設定 | 作業場 |
| launch | する | 案の行ごと | 案の 1 行、作業場 | 起こした結果 |
| turn | する | 起きた会話ごと（並べて） | ペイン、文 | ターンの結果 |
| clean | する | 一覧の最後・`--clean --apply` | 元の clone の worktree | 閉じた・片付けた結果 |
| report | しない | 最後 | 全部の結果 | 報告の行 |

cost が書くのは、dispatch の控え（`<limits_dir>/dispatch-cost.json`）だけで、GitHub にも herdr にも書かない。

各ノードの中身:

1. **prs**: `whose-turn.py` に足す機械向けの出力（`--json`）を読み、「自分の番」の節の PR を全部取る。出力の 1 件は、番号、URL、タイトル、head の枝、役割（実装者かレビュアーか）、日数。
2. **sessions**: 開いている会話を、Claude Code 自身から機械で集める。設定のアカウントごとに、その設定のフォルダを `CLAUDE_CONFIG_DIR` に入れて `claude agents --json` を呼ぶ。Claude Code の文書は、これを外から会話の状態を読む公式の口としている。返る 1 件は、会話のプロセスの作業フォルダ（`cwd`）、会話の ID、状態など（2026-10-14 に 2.1.299 で、対話の会話も出ることを確かめた）。各会話の `cwd` から、git で origin のリポジトリ（`OWNER/NAME`）と今の枝を読み、`(リポジトリ, 枝)` の組にする。herdr にも持ち主の設定にも頼らない。出力の 1 件は、アカウント、会話の ID、`cwd`、状態、リポジトリ、枝。持ち主の言葉は「リポジトリ, ブランチ（ＰＲ）とかそういう組み合わせがいいかな。できればclaudeからとれるのがいいかな。機械で。」（2026-10-14）。
3. **accounts**: 設定のアカウントごとに使用率の控えを読み、選べるかと順を決める。
   - `seven_day.used_percentage` が上限（既定 95）に達したものは外す（持ち主の決め）。使用率は 1% 刻みの整数で届くので、95 は 95.0〜95.9% のどれかで、上限を超えている見込みがある。初めは「超える」としてちょうど 95 を選べる側に置いていたが、持ち主が、95% を超えた p2 が選ばれたのを見て直させた（2026-10-15）。
   - `five_hour.used_percentage` が上限に達したものも外す。5 時間の枠が尽きていると、起こしても最初の返事で止まる（判断）。
   - `resets_at` が過ぎた枠は、切り替わった後なので使用率 0 とみなす（判断）。
   - 残りを次の順に並べる（持ち主の決め 2026-10-16）。初めは `seven_day.resets_at` の近い順、同じなら週の使用率の低い順だった。どのアカウントも週の切り替わりが 6 日以上先でも、十数時間早いだけのアカウントに毎回寄せ、その 5 時間の枠を先に食い潰した（2026-10-16 に、5 時間 74% の p2 に全部が寄り、5 時間 2%・週 1% の main はほぼ使われなかった）。
     1. 週の枠の切り替わりが近い（設定の `reset_soon_hours` 以内。既定 24 時間。ちょうども含む）ものを先に、切り替わりの近い順。使わずに切り替わる分を無駄にしないため。
     2. それ以外は、5 時間の枠と週の枠のうち高い方の使用率の低い順。
     3. 同じなら、そのアカウントで動いている会話の数の少ない順、次に設定の順。数えるのは sessions と同じ `claude agents --json` の並びのうち、背景の会話は `state` が `working`・`blocked` のもの、`state` の無い対話の会話は `status` が `busy` のもの（2026-10-16 に、対話の会話には `state` が無く `status` だけが入るのを見た）。読めないアカウントは 0 件とみなし、注記を出す。
   - 出力の 1 件は、名前、起動のコマンド、2 つの枠の値、選べるか、外した訳、切り替わりが近いか（`soon`）、高い方の使用率（`peak`）、動いている会話の数（`running`）。
   - 単独でも呼べる（`python3 nodes/accounts.py --pick [--json]`）。順の頭の 1 つの名前と起こし方の命令と選んだ訳を出す。人が手で会話を立てるときも、同じ選び方を通すため（持ち主 2026-10-16）。dispatch の中と違い、古い控えだけを取り直す（`limits.py` の probe と同じ）。
4. **assign**: 純粋な関数。PR ごとに結末を 1 つ決める。
   - `(対象のリポジトリ, PR の head の枝)` の組が sessions にあるか、その枝の場所のフォルダ（3 節）かその下を作業フォルダにする会話があれば `already_open`（会話が開いている）。リポジトリまで見るので、`main` のような同じ名前の枝を別のリポジトリの会話と取り違えない。
   - 開く PR を、選べるアカウントに順の頭から割り振る。全部の PR の `/catchup` は同時に走るので、始める前に件数を決める（持ち主 2026-10-15「並列で全部開けないかな」に、件数を残りから決める案 A で答え、持ち主が「おしで」と決めた。AI は使わない）。
     - 1 件あたりの使用率の見積もり（cost ノード）があれば、各アカウントに、週と 5 時間のどちらの枠も「使用率 + 件数 × 1 件あたり < 上限」を満たす最大の件数まで入れ、あふれた分を次のアカウントへ回す（切り替わりの近い枠から使い切る）。使用率の分からないアカウントは件数で縛らない。
     - まだ測っていなければ、選べるアカウントに 1 件ずつ順に配る。値の無いうちは、1 つのアカウントを使い切らない側に倒す。
     - どのアカウントにも入らない PR は `no_account`。
     - 初めは全部を順の先頭のアカウントに入れていた。持ち主が、週 89% の main に 10 件が入る案を見て直させた。
   - 使用率は、dispatch が始める前と全部の `/catchup` の後に、入口が `limits.py` の probe で問い合わせる。各アカウントの鍵で Anthropic の Messages API（`https://api.anthropic.com/v1/messages`）に `max_tokens` 0 の要求を 1 つ投げ（出力 0 トークン）、応答のヘッダ `anthropic-ratelimit-unified-{5h,7d}-*` から 2 つの枠の使用率を読んで、使用率の控えに書く。cost ノードは、その前後の控えの差から、アカウントごとに「見えた差 + 1」を開いた件数で割って覚える（使用率は 1% 刻みなので、少なく見積もらないよう上の端を採る）。見積もりは新しい 10 回の中央値。2 ターン目の続きの使用は入らない。測るのは 1 ターン目の終わりまで待った件だけで、待たずに送る `--no-second` と `--issue` の件は数えない（測る時にまだ使っていないため）。
   - どれにも当たらなければ `assigned` で、アカウントを付ける。
   - PR の並びは prs の順のまま。
5. **provision**: 案の 1 行を受け、その枝の作業場（worktree と herdr の作業場）を、無ければ作り、有れば使い直す（3 節）。作業場のペイン ID を返す。作れなければ `provision_failed`、その枝を元の clone が開いていて worktree を作れなければ `branch_busy`。
6. **launch**: 案の 1 行と作業場を受け、作業場のペインのシェルに、アカウントの起動のコマンド（例 `claude-p1`）を `herdr pane run <ペイン> <コマンド>` で打ち込む。最初のプロンプトは付けない。herdr が会話を見つけて `idle` になったことを読み戻してから返す。
   - `CLAUDE_CONFIG_DIR=… claude` の形は使わない。持ち主の `claude` はシェル関数で、Keychain の既定のアカウントのトークンを `CLAUDE_CODE_OAUTH_TOKEN` に入れてから起こすので、設定のフォルダを替えても既定のアカウントで動いてしまう。アカウントごとの関数は、設定のフォルダとトークンの両方をそのアカウントのものにする（2026-10-14 に持ち主の `~/.zshrc` の関数を読んで確かめた）。
   - herdr の `agent start` も使わない。素の `claude` を起こすので、アカウントを選べない。
3'. **fresh**（一覧で回すときだけ。ただし最初の文は名指しでも同じ）: 自分が作者でレビュアーの付いていない PR（`own_unreviewed`）は開くが、1 ターン目の `/catchup` だけを送り、2 ターン目の文は送らない（2026-10-16 の持ち主の決め「いつも開くようにして、my-turn はいらない」。2 ターン目の文はレビューの進め方なので、レビュアーのいない自分の作業には合わない）。会話がどこにも開いていない PR は、前に送った控えが有り、送った時刻より後に自分以外の人の動きが無く、PR の今の head（`ghx.pr_activity` が読む `headRefOid`）も控えの head のままなら、開かずに `no_news` にする（1 節の 2026-10-15 の決め。アカウントも作業場も取らない）。控えが無い・動きが有る・head が違う・PR の動きが読めないなら、今までどおり assign へ渡す。`--pr` で名指したときはこの判断をしない。PR の枝の場所で会話が開いている PR は、次の全部を満たせば送り直す（`refresh`）。満たさなければ、その理由を結末にして触らない。
   - 会話が手すき（`claude agents --json` の status が `idle`）。作業中は `busy`。
   - 場所に未コミットの変更も git に足していないファイルも無い（`dirty`）、手元にしか無い commit もその枝の上の stash も無い（`unpushed`）。worktree は枝と stash を元の clone と共有するので、数えるのはその場所の HEAD とその枝の物だけ。
   - 前に送った時と会話を起こした時の遅い方より後に、自分以外の人の動き（コメント・レビュー・commit。Bot は数えない）が PR に有る。PR の今の head が前に送った時の控えの head と違えば（作者の push）、時刻に依らず動きが有るとする（会話の開いていない PR の判断と同じ見方。force-push で古い時刻の commit が来ることがあるため）。どちらも無ければ相手の返事を待っている途中なので `no_news`。前に送った時は `<limits_dir>/dispatch-sent.json` の控えで、入口（`dispatch.py`）が書く。書くのは PR の 1 ターン目を送れた回（結末が `sent`。2 ターン目まで送った回も、`--no-second` で 1 ターン目だけ送った回も）で、中身は PR ごとに、1 ターン目を送る直前の時刻と、その時の場所の head の commit（`{"at", "head"}`。前の版の時刻だけの控えも読む）。送った後の動きを「新しい返事」と数えるため、時刻は送る前に取る。issue から始めた件は書かない。
   - 場所の HEAD が控えの head のままなら、どの remote の枝にも無い commit は作者の force-push で origin から消えた物で、手元で積んだ物ではない。そのときは `unpushed` を、その枝の stash だけで決める。
   送り直す PR は assign で新しくアカウントを選び直す。provision の前に、その場所で herdr が Claude Code の会話を見ているペイン（agent が claude）に `/exit` を送ってペインの前がシェルに戻るのを読み戻し（turn の close_session）、その場所の worktree の作業場（herdr がその場所に返す `open_workspace_id`）を閉じる（clean の release。checkout は残る）。provision は同じ場所の作業場を開き直す。
   - herdr にその場所の会話のペインが無ければ（会話が herdr の外の端末に居るなど）終えず、`close_failed`。
   - release は、その作業場の全部のペインの前がシェルかを確かめてから閉じる。シェルでない物（別の会話・エディタ・dev server）が居れば閉じず `close_failed`。同じフォルダに cd しただけのほかの作業場は閉じない（ペインの作業フォルダで探すと、持ち主の別の作業場ごと閉じてしまう）。
   - herdr や Claude Code を読めないときも、その PR の `close_failed` にして、ほかの PR は続ける。
7. **turn**: ペインと文を受け、`herdr agent prompt <対象> <文>` で送る。`--wait` を付けたときは、送った後に動き出したのを見てから、`idle`・`done`・`blocked` のどれかになるまで待ち、その状態を返す。
   - 1 ターン目は `/catchup <番号>` を `--wait` 付きで送る。`herdr agent wait` だけで待たないのは、help が「It does not track turns」と書く通り、ターンの区切りを追わず、始まる前の `idle` に当たりうるため。
   - 2 ターン目は、1 ターン目が `idle` か `done` のときだけ、2 ターン目の文を `--wait` 無しで送って終える。`blocked`（許可の確認などで止まっている）なら送らない。
   - こちらの手では期限を付けない。このリポジトリで作業する決まりの文書（直下の `CLAUDE.md`）が、期限とタイムアウトを新しく足すことを禁じているため。herdr に組み込みの見張り（`--wait` は、送って 5000ms 以内に動き出さなければ `agent_prompt_stalled` で返す）は、こちらが足すものではないので、そのまま受けて結末にする（判断）。
   - 1 ターン目の終わりは、Claude Code 自身が返す会話の状態（`claude agents --json` の status）で見る（2026-10-15 から）。herdr は画面の下の行で作業中かを決めるので、会話が裏に待ちのコマンドを残すと、ターンが終わっても作業中と見続ける。2026-10-15 に #2003 で `/catchup` の返事の後 54 分止まり、2 ターン目も報告も出なかった。動き出したことは herdr の `--wait --until working --until blocked` で見て、その後 Claude Code が `idle` を返すまで 5 秒おきに問う。herdr が `blocked` を返せば `blocked`。会話が Claude Code から見えない回は、herdr の見立てを使う。
   - 会話を終える close_session は、`/exit` を送り、ペインの前がシェルに戻ったのを 1 秒おきに 30 回まで読み戻す。戻らなければ `close_failed` で、その PR は送り直さない・消さない。走っている仕事を打ち切る期限ではなく、送った操作が効いたかの読み戻しの回数である（D5 の外。判断）。
8. **report**: PR ごとに 1 行。番号、タイトル、枝（作業場の鍵。3 節）、アカウント、結末（`sent` 2 ターン目まで送った・`refreshed` 古い会話を畳んで送り直した・`blocked` 止まっている・`stalled` 動き出さなかった・`already_open`・`no_news`（前に送った後に相手の動きが無い。会話が開いていれば送り直さず、開いていなければ開き直さない）・`busy`・`dirty`・`unpushed`（会話が開いていて送り直さなかった理由）・`close_failed` 古い会話を終えられなかった・`no_account`・`provision_failed` 作業場を作れなかった・`branch_busy` 元の clone がその枝を開いている・`launch_failed` 起こせなかった・`send_failed` 送る命令が誤りを返した・`issue_closed` 閉じた issue を `--issue` で指した）。issue から始めたものは、行を `issue #<番号>` で始めて issue の番号と枝を出し、1 ターン目まで送れば `sent`（`--dry-run` でまだ枝が無ければ枝の欄は `-`）。頭の注記に、片付けた・残した場所を 1 行ずつ置く。

PR が複数あるときは、provision と launch を PR ごとに順に全部先に済ませてから、turn を PR ごとに並べて走らせる。1 件の `/catchup` が長くても、ほかの件が遅れないようにするため。

## 3. 作業場（枝ごとの worktree）

持ち主が 2026-10-14 に決めた（「0~10個たくわえるんじゃなくて」）。固定の作業場（work0〜10）を蓄えて空きを探す形はやめ、作業ごとに作業場を作る。2026-10-15 に、作業場の単位を PR から枝に替え、clone から worktree に替えた（1 節）。

- **なぜ枝が鍵か。** issue から始める作業には PR の番号がまだ無い。枝は issue からも PR からも決まり、PR を後から作っても同じ場所のままでいられる。
- **なぜ worktree か。** 調べた並行作業の道具が揃ってとる形で、herdr が作る・並べる・消すの口を持つので、自分で書くものが減る。元の clone と中身（objects）を共有するので、作る速さと場所は小さい。git worktree は同じ枝を 2 か所で開けない（2026-10-14 に clone を選んだ訳）。今は送り直しも同じ場所を使い直すので、1 つの枝に場所は 1 つで足りる。当たるのは、元の clone 自身がその枝を開いているときだけで、そのときは作らずに `branch_busy` で知らせる（元の clone の枝を勝手に替えない。持ち主が使っている見込みがある）。
- **なぜ蓄えないか。** 並行作業の道具を調べた範囲では、作業ごとに隔離した作業場を作って消す形が大半で、決まった数の作業場を使い回す形を勧める文書は無かった。作業場が足りないこと、前の作業の残り（未コミットの変更・別の枝）、枝を移す手間が、まとめて無くなる。

作業場を用意するのは provision のノードで、外に書く（worktree を作る・herdr の作業場を開く）。herdr とのやりとりは herdr アダプタ（`herdr.py`）の場所の関数だけが持ち、ノードは「枝の場所を探す・作る・開く・消す」の言葉で書く。

- 場所を探す: 元の clone（`source`）の worktree を `herdr worktree list --cwd <source>` で並べ、その枝を開いている linked worktree があれば、それがその枝の場所。フォルダの名前では探さない。
- 会話の作業フォルダが場所の中かは、assign・fresh・clean のどれでも、リンクを辿った実際のパスで比べる（`~/src` がリンクでも、`claude agents --json` が実際のパスを返しても見落とさない）。
- 無ければ作る: `git fetch origin <枝>` の後、`herdr worktree create --cwd <source> --branch <枝> --base origin/<枝> --label <リポジトリの名前>/<枝> --no-focus` で作る。`--trust-repository` は付けない（2026-10-15 に手元の herdr 0.9.3 で、自分の持ち物の一時の git リポジトリに付けずに打って通った。herdr の文書は、持ち主が確かめたリポジトリにだけ付けるよう求めている）。元の clone が herdr で開いていなければ、herdr は create のときにその作業場も開く（list は開かない）。置き場は herdr の既定（設定の `worktrees.directory` の下の `<リポジトリ>/<枝の slug>`）に任せ、こちらで決めない。herdr は、手元に同じ名前の枝が有ればそれを開き、無ければ `--base` から作る。名前（label）は人が見るためだけで、探すのには使わない（herdr の作業場の名前は重なっても止められない。Discussion #3567「not unique by contract」）。名前を `<リポジトリの名前>/` で始めるのは、issue の番号で始まる枝の名前でも、数字で始まらないようにするため（herdr はチケットの番号で始まる表示名を受け付けなかった、という報告がある。Discussion #3284）。
- 設定の `copy_files`（git が追わない手元だけのファイル。例 `frontend/.env.local`）を、`copy_from` のフォルダ（省けば元の clone）から作った場所へ写す。依存（仮想環境・`node_modules`）は入れない。`/catchup` と 2 ターン目は主に読む仕事で、試験を走らせる段になってから、その会話の中で入れれば足りる。
- 有れば使い直す: `git fetch origin <枝>` の後、`herdr worktree open --cwd <source> --path <場所> --label <リポジトリの名前>/<枝> --no-focus` で作業場を開く（`--path` だけでは `worktree_not_found` が返り、元の clone を `--cwd` で渡すと通った。開いている場所に打てば、その作業場をそのまま返す。2026-10-15 に 0.9.3 で見た）。
- 作る・使い直すのどちらでも、手元の枝が origin の枝の祖先なら早送り（`git merge --ff-only`）だけする。作るときも、手元に同じ名前の古い枝が残っていれば herdr はそれを開くので、同じく揃える。
- 祖先でないときは、作者の force-push か、手元で積んだ commit かを見分ける。HEAD が前に送った時の head（`dispatch-sent.json` の控え）と同じで、場所に未コミットの変更も git に足していないファイルも無ければ、作者の force-push とみなして `git reset --keep origin/<枝>` で揃え、注記に書く（`--keep` は未コミットの変更と重なれば git が断る）。それ以外は手元にしか無い commit があるとみなして動かさず、報告の注記に書く（fresh の `unpushed` と同じ扱い）。
- 手元の枝が古いまま `/catchup` に渡さない。`/catchup` は枝を移るときも pull や merge をしないので、作る・使い直すのどちらでも、origin の今の head に揃えてから渡す。
- その場所かその下を作業フォルダにする会話が、どのアカウントにも有れば、2 節の 3' の fresh で送り直すかを決める。送り直すときは古い会話を終え、herdr の作業場を閉じ（checkout は残る）、同じ場所を開き直す。送り直さないものは作業場に触らない。
- fork の PR（head が別のリポジトリ）は、origin に枝が無いので作らず `provision_failed` で知らせる（判断。guided-resolver では起きていない）。

**issue から始める**（`dispatch.py --issue <番号>`）:

- `gh issue develop --list <番号>` で issue に結んだ枝を探し、有ればその枝の場所を使う（2 本以上なら最初の 1 本で、残りを報告の注記に並べる）。
- 結んだ枝が見えなければ、その issue を閉じる PR（`gh issue view --json closedByPullRequestsReferences` のうち、このリポジトリの開いた PR。fork の PR は除く）の枝を使う。GitHub の文書は、issue に結んだ枝から PR を作ると、枝の結びつきを外して PR に置き換えると書く。PR を作った後の issue に枝を作り直さないため（判断）。
- どちらも無ければ `gh issue develop <番号> --base <既定の枝>` で GitHub に枝を作って issue に結び、`--list` で読み戻した枝を使う。枝の名前は gh の既定に任せる。この操作は GitHub に枝を作る外への書き込みで、持ち主が `--issue` で指したときだけ、`--dry-run` でないときだけ行う（`--dry-run` は「枝を作って結ぶ」と注記に書くだけ）。
- その枝の場所を上と同じに作り、会話を起こして 1 ターン目に `/catchup <番号>` を送って止める。`/catchup` に issue の番号を渡すと、attention はその issue で前回自分が触ってから何が起きたかを出す（PR がまだ無いので、PR の指摘・CI の材料は無い。枝は、名前にその番号を持つ手元の枝が 1 本のときだけ移るが、会話はもうその枝の場所で起きている）。2 ターン目の文はレビューの文なので送らない。PR を作るのは起こした会話の中の仕事。
- issue が閉じていれば、枝を探しも作りもせず、`issue_closed` を結末にして止める（閉じた作業のために GitHub に枝を作らない。判断）。
- `--issue` は `--pr` と一緒には使えない（1 回に 1 つの入口）。送り直しも片付けもしない。

片付けは、一覧で回す dispatch の最後に同じコマンドがする（2026-10-15 から。`--pr`・`--issue` で指したときと `--dry-run` は消さない。`--dry-run` は片付ける物を並べる）。`dispatch.py --clean`（並べる）と `--clean --apply`（消す）も残す。

- 対象は、元の clone の linked worktree（元の clone 自身は対象にしない。herdr が linked と返しても、元の clone と同じ実際のパスの物は必ず外す）。対象を元の clone の worktree に限るので、関係ないリポジトリの場所は並びにも入らない。
- 候補にするのは、その枝の PR が閉じている（マージ済みか閉じた）こと、その場所かその下を作業フォルダにする会話がどのアカウントにも無いこと、未コミットの変更も git に足していないファイルも無いこと、手元の枝の先頭が PR の head の commit と同じ（手元にしか無い commit が無い）こと、設定の `copy_files` に書いたファイルのうち写し元と中身が違うもの（その場所で書き換えた手元だけのファイル）が無いこと、を全部満たすものだけ。git が追わないファイルのうち、それ以外（依存・生成物など）は場所と一緒に捨ててよい（作り直せる。持ち主 2026-10-15 の決め）。写し元と違う `copy_files` が有れば消さずに残し、そのファイルを報告に出す。PR の無い枝（issue から始めて PR をまだ作っていないもの）は消さない。
- 枝の PR は `gh pr list --head <枝> --state all` で読む（fork の PR は除き、開いたものが有ればそれ、無ければいちばん新しいもの）。手元の作業の判定は、その場所の HEAD とその枝の上の stash だけを見る（worktree は枝と stash を元の clone と共有する）。
- `--clean` は候補を並べるだけで、`--apply` を付けた時だけ消す。消すのは `herdr worktree remove --workspace <ID>`（未コミットの変更か git に足していないファイルがあれば、herdr は `dirty_worktree_requires_force` で断る。`--force` は付けない）。herdr の remove は作業場の ID で指すので、開いていない場所は `herdr worktree open` で開いてから消す。消えたことを herdr の並びで読み戻してから、手元の枝も消す（herdr の remove は手元の枝を残す。消す直前に、先頭が PR の head と同じことをもう一度確かめ、違えば残して注記に書く）。
- 一覧で回す dispatch は、閉じた PR の場所のうち、会話が開いていても、会話が 1 つだけで手すきで手元の作業も無いものは、会話を終えてから消す。会話を終えるのは送り直しと同じ形（herdr で会話を見ているペインに `/exit`。herdr の外の会話は終えない）で、終えた後に会話の一覧を取り直し、その場所に会話が無いことを確かめてから消す。作業中・会話が 2 つ以上・手元の作業の有るものは残し、注記で名指す。会話や herdr を読めないときは、片付けを飛ばすか、その場所を残して注記に書き、traceback で止めない。
- 一覧で回す dispatch は、開いている PR のうち自分の番の一覧に無い物（自分の番でなくなった PR）の場所も見る（2026-10-19 から。頼み 0ac81f）。閉じる会話は、引数なしの dispatch がその PR に `/catchup` を送った相手と言い切れる物に限る。言い切れるのは、次の 2 つを両方満たすとき。1 つ目は、その PR の送った控え（`dispatch-sent.json`。最後に `/catchup` を送った時刻と head を持つ）に、引数なしの回で送った印 `via: listing` が有ること（印は 2026-10-19 から書くので、それより前の控えは満たさない）。2 つ目は、会話の起動の時刻（`claude agents --json` の `startedAt`）が、控えの送った時刻より前であること（送った後に起動した会話は、持ち主が自分で開いた物）。その会話が 1 つだけ開いていて、手すきで、未コミットの変更も手元にしか無い commit も無ければ（送り直しと同じ見方）、会話を終えて herdr の作業場を閉じる（clean の release）。worktree と枝は残す。自分の番に戻れば、一覧の回が同じ場所に新しい会話を立てる（送り直しと同じく、古い会話は使わない）。作業中・手元の作業の有るものは残して注記で名指す。持ち主が自分で開いた会話・`--pr` で見に行った会話には触らない。同じ PR の worktree（ブランチの checkout）の中で会話が 2 つ以上開いているときは、どれにも触らない。自分の番の一覧（whose-turn）を読めなければ dispatch ごと止まり、`--pr`・`--issue` の回は一覧を読まないので、どちらも閉じない。whose-turn は PR ごとのコメントなどを上限の件数までしか取らず、上限に当たった PR を画面の出力の「走査の上限に当たったもの」に並べるが、`--json` の出力にはこの並びを出さない。そのため、取りこぼしで自分の番から外れた PR を dispatch は見分けられず、その会話を閉じうる。閉じても worktree・枝・会話の記録は残り、自分の番に戻れば開き直す。
- 前の版が作った PR ごとの clone（前の版の設定の `clone_root` の下の `<リポジトリの名前>-pr-<番号>`）は、この版では扱わない。元の clone の worktree ではないので、並びにも入らない。移る時に持ち主の前で 1 回だけ手で片付ける（判断。同じ片付けを 2 通り持たない）。設定に `clone_root` が残っていても、ほかの知らない鍵と同じく読み飛ばす（止めない）。

## 4. ノードの作りの決まり

倣う先は works-factory で、同じリポジトリの darkfactory（旧 works）の作りではない。持ち主の言葉は「works と新工場は少し作り方が違うので、引っ張られないようにしてね旧に」（2026-10-14）。決まりは 1 つずつ試験と対にし、試験で縛れないものは「人が見る」と書く。

- **D1 旧 works の部品に頼らない。** `works-dispatch/dispatch/` は、`works/.shared/`・`works/dev/`・`works/darkfactory/`・`works/blk-*` のファイルを読まず、import もしない。darkfactory は works-factory に置き換わったら外されるので、頼ると一緒に壊れる。機械: `works-dispatch/dispatch/` の字にそれらのパスが無い。
- **D2 処理は Python に置き、シェルの文字列に Python を埋めない。** 旧 works は起動の処理を sh の関数と、sh の文字列に埋めた Python に持ち、写しが食い違った。入口も Python にする。機械: `works-dispatch/dispatch/` に `.sh` が無い。
- **D3 ノードは流れを知らない。** ノードは引数と JSON のファイルのパスで受け、JSON で返す。どのノードの次に何を呼ぶかは、入口の `works-dispatch/dispatch/dispatch.py` だけが持つ（works-factory の、流れはグラフだけが持ち助け手は流れを知らない、の形）。後で、入口の流れの一部をぶつかりを減らすために別のファイル（`orders.py`・`landing.py`・`calls.py`・`move.py`・`reorg.py`・`retire.py`・`starts.py`）に分け、Claude Code が起こすフック（`*_hook.py`）も足したので、流れを持つのはこの入口の側の全部になった（層の全体は [internals.md](../internals.md) の「形」）。機械: `works-dispatch/dispatch/nodes/` のファイルが、ほかのノードも、入口の側のファイルも import しない（`from nodes import x`・`import nodes.x` の形も数える）。今在る破れは柵の `D3_KNOWN` に載せて外し、増やさない。ノードを足す・ノードに import を足す人は、この決まりに従い、ほかのノードの物が要るならノードの外へ出す。
- **D4 外に書くのは決まったノードだけで、書いた後に読み戻す。** provision・launch・turn と、片付けの clean。機械: Python の構文木で見る。`subprocess` を import するのは外への口（`herdr.py`・`gitx.py`・`claudex.py`・`ghx.py`・送り終えた PR の /catchup のページを VS Code の窓に開く `vscode.py`）と、whose-turn を呼ぶ prs のノードと、始める前の確かめを持つ入口だけ（後で入口から分けた流れのファイルとフックにも許した。どのファイルに許したかと許した理由は、柵の表 `SUBPROCESS_OK` と、その上の注記にファイルごとに書く）。herdr に書く関数（`run`・`prompt`・場所を作る・開く・消す `create_worktree`・`open_worktree`・`remove_worktree`・`close_workspace`）と、git に書く関数（`fetch`・早送りの `fast_forward`・作者の force-push に揃える `reset_keep`・手元の枝を消す `delete_branch`）と、gh に書く関数（issue に枝を結ぶ `issue_develop`。`gh issue develop`）を呼ぶのは、初めはその 4 つのノードだけだった。後で書く関数とノードが増えた（部署の表示の sync、頼みと納品の deliver、本流に入れる land・bump、機械窓口の tools、古い版の会話を入れ替える refresh）ので、どのノードがどれを呼ぶかの正は柵の表（`works-dispatch/dispatch/tests/fences.py` の `WRITES`）にする。外に書く関数やそれを呼ぶノードを足す人は、先にこの表に足す（足さないと柵が誤りにする）。字の書き方を変えても逃げられないようにするため、字では探さない。読み戻しは人が見る。
- **D5 こちらから期限を足さない。** 機械: `works-dispatch/dispatch/` に `timeout` の字が無い（herdr の組み込みの見張りの結末の語 `agent_prompt_stalled` は除く）。
- **D6 持ち主の環境の値をリポジトリに書かない。** アカウントの名前、起動のコマンド、置き場のパス、使用率の控えの場所は、設定のファイルで渡す（works-factory の「既定の道は普通の利用者の環境でそのまま動く」と同じ）。機械: `works-dispatch/dispatch/` に `raiki61`・`claude-code-oauth-`・`/Users/`・`claude-p` の字が無い。
- **D7 普通の利用者の環境でもそのまま動く。** 設定にアカウントが無ければ、`claude` 1 つだけのアカウントとして扱う。使用率の控えが無いアカウントは、使用率が分からないものとして選べる側に残し、順の最後に置く（判断）。人が見る。
- **D8 出力の形は schema に書き、試験がそれで照らす。** 機械: 各ノードの試験の出力が `works-dispatch/dispatch/schemas/<名>.schema.json` に合う。

ほかの決まり:

- 各ノードは `works-dispatch/dispatch/nodes/<名>.py` の単独のコマンド。入力は引数と JSON のファイルのパス、出力は JSON を標準出力か `--out <パス>` に書く。標準ライブラリだけで書く。
- 各出力の頭に `schema: 1` を置き、読む側は知らない版を読んだら止まる。
- herdr を呼ぶのは `works-dispatch/dispatch/herdr.py` の 1 か所だけ。git と Claude Code（`claude agents --json`）も同じく 1 か所ずつ（`gitx.py`・`claudex.py`）に寄せる。herdr は互換を約束していない（herdr の文書は、手元の版の API を `herdr api schema` で確かめるよう求めている）ので、壊れたら直すのはこの 1 か所になる。
- `works/skills/dispatch/SKILL.md`: `/works-dispatch:dispatch` の入口。`dispatch.py` を 1 回走らせ、出た報告をそのまま見せるだけ。判断はさせない。`dispatch.py` は端末から直に打っても同じに動く。
- `whose-turn.py` の場所: works は attention をそのまま呼べない（プラグインは 1 つずつ配られ、ほかのプラグインのフォルダは手元に無いことがある）。このリポジトリの写しの仕組み（`scripts/shared-copies.py`。正本を 1 つ持ち、写しが割れたら試験が赤になる）で、正本の attention から works へ写す。写すのは `whose-turn.py` と、それが読む部品（`attention/scripts/lib/outfile.py`）。

## 5. 設定

`~/.config/works-dispatch/dispatch.toml`（パスは環境変数 `WORKS_DISPATCH_CONFIG` で替えられる）。スクリプトに環境の値を書かない。

```toml
limit_percent = 95                      # 使用率がこれに達したアカウントは選ばない
reset_soon_hours = 24                   # 週の枠の切り替わりがこの時間以内のアカウントを先に使う（省けば 24）
move_early_percent = 90                 # 区切りで、今のアカウントの枠がこの使用率に達していれば、空いているアカウントへ早めに移す（省けば 90）
move_early_reset_hours = 1              # 達した枠がこの時間以内に戻るなら移さない（省けば 1）
limits_dir = "~/.cache/claude-limits"   # 使用率の控えの置き場

# name は使用率の控えのファイル名、command はそのアカウントで claude を起こすシェルのコマンド、
# config_dir はそのコマンドが CLAUDE_CONFIG_DIR に入れるフォルダ（会話を集めるのと、信頼の記録と attention を
# 探すのに使う。入れないコマンドなら書かない。そのときは作業場のペインの新しいログインのシェルの値か ~/.claude）。
# keychain_service は鍵を置いた Keychain の項目の名前（省けば共通の scripts/claude_auth.py の決まりで探す）。
# limits = false は使用率の枠の無いアカウント（Ollama・Foundry など）で、控えを読まず使用率で外さない
accounts = [
  { name = "main", command = "claude" },
  { name = "p1",   command = "claude-p1", config_dir = "~/.claude-p1" },
  { name = "p2",   command = "claude-p2", config_dir = "~/.claude-p2" },
  { name = "p3",   command = "claude-p3", config_dir = "~/.claude-p3" },
  { name = "local", command = "claude-ollama", config_dir = "~/.claude-ollama", limits = false },
]

[[repos]]
repo = "<owner>/guided-resolver"
second_prompt_file = "~/.config/works-dispatch/dispatch-second-prompt.md"   # 2 ターン目の文（複数行）
source = "~/src/guided-resolver"        # 元の clone。枝ごとの worktree はここから作る（置き場は herdr の worktrees.directory）
copy_files = [                          # git が追わない手元だけのファイル（リポジトリの中の相対パス）
  "frontend/.env.local",
  "deploy/local/secrets.local.yaml",
  "deploy/local/real-data.local.yaml",
]
copy_from = "~/.config/claude/repos/guided-resolver"   # copy_files を写す元のフォルダ。省けば元の clone から写す
gh_user = "<会社の GitHub のログイン名>"   # このリポジトリを読む gh のアカウント。省けばその人の今の設定。鍵は gh auth token --user で取り出して子の GH_TOKEN にだけ入れ、gh auth switch はしない
```

2 ターン目の文は複数行なので、別のファイルに置く。持ち主の今の文は、木を探るように指摘を深掘りすること、世の中の解と照らすこと、自作の領域に踏み込んでいないかを疑うこと、未確認の領域を残さないこと、を求める 4 段の文。

## 6. 始める前の確かめ

`dispatch.py` は、何かを起こす前に次を確かめ、足りない物を全部並べて止まる。

- herdr があり、サーバに届き、`herdr api schema` に使うメソッドがある。
- 設定のファイルと 2 ターン目の文のファイルがあり、形が合う。
- 使用率の控えが無いアカウントがあれば、止めずに 1 行出す（D7）。
- アカウントの起動のコマンドが、作業場のシェルで見つかる（利用者のログインのシェルに `command -v <コマンド>` を対話の形で聞く。シェルの関数も数える）。
- `/catchup` を持つ attention が、各アカウントの設定のフォルダに入っている（`<設定のフォルダ>/plugins/installed_plugins.json` に `attention@` で始まる名がある）。2026-10-14 には 4 つとも入っていた。
- `gh` が使える（whose-turn と、片付けの PR の状態の確かめが使う）。
- 元の clone（`source`）が、対象のリポジトリの clone である（origin が `repo` と同じ）。linked worktree でなく本体の checkout である（`git rev-parse` の `--git-dir` と `--git-common-dir` が同じ）。herdr が元の clone の worktree を並べられる。`copy_files` が写す元（`copy_from`、省けば元の clone）に有る（無いものは止めずに 1 行出す）。gh が `repo` を読める（`gh_user` が有れば、そのアカウントの鍵で `gh repo view` が通る）。

`--dry-run` を付けると、assign まで走らせて report を出し、何も起こさずに終わる。作業場を作るか（`create`）使い直すか（`reuse`）、元の clone がその枝を開いているか（`branch_busy`）も、元の clone の worktree の並び（`herdr worktree list`。読むだけで作業場は開かない）から報告する。fork の PR かを gh に問うのと、片付けの候補の PR を読むのも、読むだけ。

## 7. 作らないもの

- 依存（仮想環境・`node_modules`）を入れること（3 節）。
- 片付けで、作業中の会話のある作業場・閉じていない PR の作業場・手元にしか無い変更のある作業場を消すこと（ここの作業場は worktree。自分の番でない開いている PR は、herdr の作業場を閉じても worktree は消さない）。
- 作業中の会話を閉じる・止めること、`/clear` を打つこと（送り直しも片付けも、手すきの会話に `/exit` を送るだけ）。
- 一覧で回すときの issue への割り振り（一覧は PR だけ。issue は `--issue` で指したときだけ）。
- 元の clone の枝を替えること（`branch_busy` で知らせるだけ）。
- こちらが足す期限・タイムアウト。
- 2 ターン目より後の操作。

## 8. 確かめ方

- 試験は `works-dispatch/dispatch/tests/` に置き、旧 works の試験の殻（`works/tests/run.sh`）には載せない（D1）。CI で回す道は、リポジトリの根の試験の殻から呼ぶ形にし、計画で決める。
- 判断のノード（accounts・assign・report と、片付けの候補の判定）は、速い段の単体テストで確かめる。外とのやりとりは偽物に差し替える。出力は schema で照らす。
- provision と clean は、一時のフォルダに作った小さな git のリポジトリを元の clone に見立てて、本物の git で試す（herdr だけ偽物。偽物の worktree の口は本物の `git worktree` で作り・並べ・消し、herdr アダプタと同じ形（場所の言葉）で返す）。herdr アダプタの場所の関数は、手元の herdr の実物の出力（2026-10-15 に 0.9.3 で読んだ `worktree create`・`list`・`remove` の JSON）を写した試験で縛る。
- 外とのやりとりは、手元の herdr で `--dry-run` を走らせ、持ち主の今の作業場の一覧と照らして確かめる。実際に起こすのは、持ち主が見ている前で 1 件だけ試す。

## 9. 作り手に任せること

- ファイルの分け方の細部、関数の名前、schema の細部。
- 報告の行の形の細部（1 PR 1 行は守る）。
- herdr の対象（TARGET）にはペイン ID を渡す（2026-10-14 に `herdr agent get <ペイン ID>` が通ることを確かめた）。
- launch で、herdr が会話を見つけて `idle` になるまでをどう待つか（会話が見つかる前のペインに `herdr agent wait` が効くか）。手元の版で、持ち主が見ている前で、PR 1 件の作業場で確かめてから決める。
- 既定のアカウントで、`CLAUDE_CONFIG_DIR=~/.claude` と明示した時と何も付けない時に、`claude agents --json` が同じ一覧を返すか。2026-10-14 にはどちらも空で一致した。
- `claude agents --json` の `cwd` は会話を起こした時のフォルダで、会話の途中で別のフォルダへ移ったことは追えない。作業場は枝ごとに分かれているので実害は小さいと見るが、持ち主の前の確かめで、起こした会話が選んだアカウントの一覧に出るかと合わせて見る。
- 複数行の 2 ターン目の文を `herdr agent prompt` で送ったときに、途中の改行で送信されずに 1 つの文として届くか。同じく持ち主の前で確かめる。届かなければ、herdr の貼り付けの口か、改行の送り方を探す。
