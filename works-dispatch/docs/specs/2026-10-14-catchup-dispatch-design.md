# 自分の番の PR ごとに作業場を作って会話を起こすライン（dispatch）の設計（2026-10-14・下書き）

状態: 下書き。持ち主はまだ通していない。作り手役（計画を立てるのに足りない問いを出す役）に一度読ませ、出た問いと持ち主の答えを入れてある。

## 平易版（3 行）

- 持ち主（このリポジトリの作者で、この道具の利用者）は毎回、`/whose-turn` で自分の番の PR を探し、空いている作業場を 1 つずつ選んで Claude Code を起こし、`/catchup <番号>` と決まった 2 ターン目の文を手で打っている。
- この手作業を機械にやらせる。PR を集める、開いている会話と重ならないものに絞る、アカウントを選ぶ、PR ごとの作業場（clone）を作る、起こして 2 ターン分を打つ、までをスクリプトがやり、AI は起こした会話の中でしか動かない。
- 置き場は works の中の、darkfactory と並ぶ 2 本目のライン。手順を、入力と出力を JSON で決めたノードに分け、ほかの流れからもノード単位で使えるようにする。作業場は、蓄えた固定の作業場を使い回さず、PR ごとに元の clone から clone を作る。

## 0. 語

- **持ち主**: このリポジトリの作者で、この道具を使う人。決めるのは持ち主。
- **herdr**: AI のコーディングエージェント向けの端末の管理の道具（https://herdr.dev）。端末を workspace（作業場の単位）とペインに分けて並べ、各ペインで動くエージェントの状態（`idle`・`working`・`blocked`・`done`）を画面から判定して出す。外からはコマンド（`herdr pane run`、`herdr agent prompt` など）で動かせる。版は 0.x で、互換を約束していない。
- **attention**: このリポジトリの別のプラグイン。GitHub だけを見る。`/whose-turn` は、開いている PR と issue を全件取り、誰の番かを機械で分けて出す（本体は `attention/scripts/whose-turn.py`）。`/catchup <番号>` は、その PR の枝へ作業フォルダを移し、何の PR で前回からどうなったかを説明する。
- **Archon**: AI の処理の流れをグラフにして YAML で書き、機械が順に回す道具。
- **works-factory**: 持ち主の別のリポジトリ（raiki61/works-factory）にある、Archon の上で動く修正の工場。流れはグラフの YAML だけが持ち、各ノードは引数と JSON のファイルで入出力し、ノードが呼ぶ Python の助け手は流れも Archon も知らない、という作りをとる。この設計はその作りに倣う。
- **作業場**: 1 つの Claude Code の会話を走らせる端末と、その中の clone の組。PR ごとに作る（3 節）。持ち主はこれまで、herdr の workspace `work0`〜`work10` と、それぞれの clone `~/src/guided-resolver-work0` 〜 `-work10` を蓄えて使い回していた。
- **アカウント**: Claude のサブスクの 1 つ。今は `main`・`p1`・`p2`・`p3` の 4 つ。持ち主のシェルに、アカウントごとに Claude Code を起こす関数（`claude`・`claude-p1`〜`claude-p3`）がある。
- **使用率の控え**: `~/.cache/claude-limits/<アカウント>.json`。持ち主の `~/.claude/statusline.sh` と `~/.config/herdr/limits.sh` が書く。形は `{"five_hour": {"used_percentage", "resets_at"}, "seven_day": {...}, "updated_at"}` で、`resets_at` は Unix 時刻。
- **2 ターン目の文**: `/catchup` の返事の後に、持ち主がいつも打つ決まった文。
- **ライン**: works の中で、1 つの仕事を端から端まで回す流れ。今は darkfactory（ソフトの修正を Archon の上で回すライン）だけがある。
- **ノード**: 流れの 1 段。入力と出力を JSON で決め、単独でも呼べるコマンドにする。

## 1. 持ち主が決めたこと

2026-10-14 に持ち主が決めた。記録はこの節が正。

- 置き場は works。works は「環境の上で仕事を回す」くくりで、darkfactory はその中のソフトの修正のライン。今回のものは並ぶ 2 本目のラインとする。既存のプラグイン（attention など）は GitHub にしか寄らないまま保ち、組み合わせて herdr と持ち主の環境に寄る部分を works に置く。
- できる作業はスクリプトでやり、AI を使う所は最小にする。
- 対象は、`/whose-turn` の「自分の番」の PR 全部（人の PR のレビューを頼まれたものも含む）のうち、今開いているどの会話にも無いもの。
- アカウントは、週の枠の切り替わりがいちばん近いものを選ぶ。週の使用率が 95% を超えたアカウントは選ばない。
- その PR の作業場で、選んだアカウントの Claude Code を起こし、1 ターン目に `/catchup <番号>`、その返事が終わってから 2 ターン目に決まった文を打つ。そこで止める。
- 開いている会話は、入力待ちでも勝手に閉じない。持ち主が置いている可能性がある。
- herdr を使うのは、端末ごとに別のアカウントで Claude Code を走らせるため。
- 作業場は、固定の work0〜10 を蓄えず、PR ごとに作る（「0~10個たくわえるんじゃなくて」）。同じ枝を複数の場所で開けるように、worktree でなく clone にする。作業場の名前は、フォルダも herdr の作業場も `<リポジトリの名前>-pr-<番号>` でそろえる（「一緒かなとか思っただけ」。PR の番号とタイトルは、持ち主の statusline がすでに herdr に出している）。
- 作り方は、works-factory の作りに倣い、ノードに分けて入出力をしっかり決め、ほかからも使いやすくする形でよい。

## 2. 流れとノード

```
[prs] 自分の番の PR ─────┐
[sessions] 開いている会話 ─┤
[accounts] アカウントの順 ─┴─► [assign] 割り振りの案 ─► [provision] 作業場 ─► [launch] 起こす ─► [turn] 1 ターン目 ─► [turn] 2 ターン目 ─► [report]
                          └ （--dry-run はここで report へ）
```

| ノード | 外に書くか | 入力 | 出力 |
| --- | --- | --- | --- |
| prs | しない | リポジトリ | PR の並び |
| sessions | しない | 設定 | 会話の並び |
| accounts | しない | 設定 | アカウントの順 |
| assign | しない | 上の 3 つ | 割り振りの案 |
| provision | する | 案の 1 行、設定 | 作業場 |
| launch | する | 案の 1 行、作業場 | 起こした結果 |
| turn | する | ペイン、文 | ターンの結果 |
| report | しない | 全部の結果 | 報告の行 |

各ノードの中身:

1. **prs**: `whose-turn.py` に足す機械向けの出力（`--json`）を読み、「自分の番」の節の PR を全部取る。出力の 1 件は、番号、URL、タイトル、head の枝、役割（実装者かレビュアーか）、日数。
2. **sessions**: 開いている会話を、Claude Code 自身から機械で集める。設定のアカウントごとに、その設定のフォルダを `CLAUDE_CONFIG_DIR` に入れて `claude agents --json` を呼ぶ。Claude Code の文書は、これを外から会話の状態を読む公式の口としている。返る 1 件は、会話のプロセスの作業フォルダ（`cwd`）、会話の ID、状態など（2026-10-14 に 2.1.299 で、対話の会話も出ることを確かめた）。各会話の `cwd` から、git で origin のリポジトリ（`OWNER/NAME`）と今の枝を読み、`(リポジトリ, 枝)` の組にする。herdr にも持ち主の設定にも頼らない。出力の 1 件は、アカウント、会話の ID、`cwd`、状態、リポジトリ、枝。持ち主の言葉は「リポジトリ, ブランチ（ＰＲ）とかそういう組み合わせがいいかな。できればclaudeからとれるのがいいかな。機械で。」（2026-10-14）。
3. **accounts**: 設定のアカウントごとに使用率の控えを読み、選べるかと順を決める。
   - `seven_day.used_percentage` が上限（既定 95）を超えるものは外す（持ち主の決め）。
   - `five_hour.used_percentage` が上限を超えるものも外す。5 時間の枠が尽きていると、起こしても最初の返事で止まる（判断）。
   - `resets_at` が過ぎた枠は、切り替わった後なので使用率 0 とみなす（判断）。
   - 残りを `seven_day.resets_at` の近い順に並べる（持ち主の決め）。同じ時刻なら週の使用率が低い順（判断）。
   - 出力の 1 件は、名前、起動のコマンド、2 つの枠の値、選べるか、外した訳。
4. **assign**: 純粋な関数。PR ごとに結末を 1 つ決める。
   - `(対象のリポジトリ, PR の head の枝)` の組が sessions にあるか、その PR の clone のフォルダ（3 節）かその下を作業フォルダにする会話があれば `already_open`（会話が開いている）。リポジトリまで見るので、`main` のような同じ名前の枝を別のリポジトリの会話と取り違えない。
   - 選べるアカウントが無ければ `no_account`。1 回の実行の PR は全部、順の先頭のアカウントに入れる。控えは実行の途中で更新されず、持ち主の決め（切り替わりの近い枠から使い切る）とも同じ向きなので、散らさない。
   - どれにも当たらなければ `assigned` で、アカウントと、その PR の clone のフォルダを付ける。
   - PR の並びは prs の順のまま。
5. **provision**: 案の 1 行を受け、その PR の作業場（clone と herdr の作業場）を、無ければ作り、有れば使い直す（3 節）。作業場のペイン ID を返す。作れなければ `provision_failed`。
6. **launch**: 案の 1 行と作業場を受け、作業場のペインのシェルに、アカウントの起動のコマンド（例 `claude-p1`）を `herdr pane run <ペイン> <コマンド>` で打ち込む。最初のプロンプトは付けない。herdr が会話を見つけて `idle` になったことを読み戻してから返す。
   - `CLAUDE_CONFIG_DIR=… claude` の形は使わない。持ち主の `claude` はシェル関数で、Keychain の既定のアカウントのトークンを `CLAUDE_CODE_OAUTH_TOKEN` に入れてから起こすので、設定のフォルダを替えても既定のアカウントで動いてしまう。アカウントごとの関数は、設定のフォルダとトークンの両方をそのアカウントのものにする（2026-10-14 に持ち主の `~/.zshrc` の関数を読んで確かめた）。
   - herdr の `agent start` も使わない。素の `claude` を起こすので、アカウントを選べない。
7. **turn**: ペインと文を受け、`herdr agent prompt <対象> <文>` で送る。`--wait` を付けたときは、送った後に動き出したのを見てから、`idle`・`done`・`blocked` のどれかになるまで待ち、その状態を返す。
   - 1 ターン目は `/catchup <番号>` を `--wait` 付きで送る。`herdr agent wait` だけで待たないのは、help が「It does not track turns」と書く通り、ターンの区切りを追わず、始まる前の `idle` に当たりうるため。
   - 2 ターン目は、1 ターン目が `idle` か `done` のときだけ、2 ターン目の文を `--wait` 無しで送って終える。`blocked`（許可の確認などで止まっている）なら送らない。
   - こちらの手では期限を付けない。このリポジトリで作業する決まりの文書（直下の `CLAUDE.md`）が、期限とタイムアウトを新しく足すことを禁じているため。herdr に組み込みの見張り（`--wait` は、送って 5000ms 以内に動き出さなければ `agent_prompt_stalled` で返す）は、こちらが足すものではないので、そのまま受けて結末にする（判断）。
8. **report**: PR ごとに 1 行。番号、タイトル、作業場、アカウント、結末（`sent` 2 ターン目まで送った・`blocked` 止まっている・`stalled` 動き出さなかった・`already_open`・`no_account`・`provision_failed` 作業場を作れなかった・`launch_failed` 起こせなかった・`send_failed` 送る命令が誤りを返した）。

PR が複数あるときは、provision と launch を PR ごとに順に全部先に済ませてから、turn を PR ごとに並べて走らせる。1 件の `/catchup` が長くても、ほかの件が遅れないようにするため。

## 3. 作業場（PR ごとの clone）

持ち主が 2026-10-14 に決めた（「0~10個たくわえるんじゃなくて」）。固定の作業場（work0〜10）を蓄えて空きを探す形はやめ、PR ごとに作業場を作る。

- **なぜ worktree でなく clone か。** git worktree は、同じ枝を 1 つの worktree でしか checkout できない。持ち主は同じ PR・同じ枝を複数の場所で開きたい。手元の clone から `git clone` すると、git は中身（`.git/objects/`）をハードリンクで共有するので、作る速さと場所は worktree とほぼ同じで、枝などの参照はそれぞれが持つ（git の公式の手引き `git-clone` の `--local` の節）。
- **なぜ蓄えないか。** 並行作業の道具を調べた範囲では、作業ごとに隔離した作業場を作って消す形が大半で、決まった数の作業場を使い回す形を勧める文書は無かった。作業場が足りないこと、前の作業の残り（未コミットの変更・別の枝）、枝を移す手間が、まとめて無くなる。

作業場を用意するのは provision のノードで、外に書く（フォルダを作る・herdr の作業場を開く）。

- clone のフォルダは `<clone_root>/<リポジトリの名前>-pr-<番号>`（例 `~/src/guided-resolver-pr-1234`）。フォルダの名前だけで、どの PR の作業場かが決まる。
- 無ければ作る: 設定の元の clone（`source`）から `git clone` し、origin を元の clone の origin の URL へ向け直し、`git fetch origin` する。設定の `copy_files`（git が追わない手元だけのファイル。例 `frontend/.env.local`）を、`copy_from` のフォルダ（省けば元の clone）から写す。依存（仮想環境・`node_modules`）は入れない。`/catchup` と 2 ターン目は主に読む仕事で、試験を走らせる段になってから、その会話の中で入れれば足りる。
- 有れば使い直す: そのフォルダが同じリポジトリの clone なら、`git fetch origin` だけして使う。PR が開いている間は、レビューで返した後の再レビューなども同じ作業場に戻る。
- 枝を PR の枝へ移すのは `/catchup` に任せる（`/catchup <番号>` は、その PR の枝へ移り、手元に無ければ origin から取って作る）。
- herdr の作業場は、その clone のフォルダを作業フォルダにするペインを探して使う。無ければ `herdr workspace create --cwd <フォルダ> --label <フォルダの名前> --no-focus` で開く。名前（label）は人が見るためだけのもので、探すのには使わない。herdr の作業場の名前は重なっても止められず（利用者の報告 Discussion #3567「not unique by contract」）、作業場の ID は herdr を立ち上げ直すたびに変わるため。名前は数字で始めない（herdr はエージェントの表示名にチケットの番号で始まる名前を受け付けなかった、という報告がある。Discussion #3284）。
- その clone のフォルダかその下を作業フォルダにする会話が、どのアカウントにも有れば、その PR は `already_open` で、作業場には触らない。会話を閉じるのは持ち主だけ。

片付けは別の命令（`dispatch.py --clean`）にする。

- 対象は `<clone_root>/<リポジトリの名前>-pr-<番号>` のフォルダ。その PR が閉じている（マージ済みか閉じた）こと、そのフォルダかその下を作業フォルダにする会話がどのアカウントにも無いこと、未コミットの変更も push していない commit も無いこと、を全部満たすものだけを候補にする。
- 既定は候補を並べるだけ。`--apply` を付けた時だけ、そのフォルダを消し、そのフォルダのペインに会話が無ければ herdr の作業場も閉じる。消すのは取り消せない操作なので、既定で消さない。

## 4. ノードの作りの決まり

倣う先は works-factory で、同じリポジトリの darkfactory（旧 works）の作りではない。持ち主の言葉は「works と新工場は少し作り方が違うので、引っ張られないようにしてね旧に」（2026-10-14）。決まりは 1 つずつ試験と対にし、試験で縛れないものは「人が見る」と書く。

- **D1 旧 works の部品に頼らない。** `works-dispatch/dispatch/` は、`works/.shared/`・`works/dev/`・`works/darkfactory/`・`works/blk-*` のファイルを読まず、import もしない。darkfactory は works-factory に置き換わったら外されるので、頼ると一緒に壊れる。機械: `works-dispatch/dispatch/` の字にそれらのパスが無い。
- **D2 処理は Python に置き、シェルの文字列に Python を埋めない。** 旧 works は起動の処理を sh の関数と、sh の文字列に埋めた Python に持ち、写しが食い違った。入口も Python にする。機械: `works-dispatch/dispatch/` に `.sh` が無い。
- **D3 ノードは流れを知らない。** ノードは引数と JSON のファイルのパスで受け、JSON で返す。どのノードの次に何を呼ぶかは、入口の `works-dispatch/dispatch/dispatch.py` だけが持つ（works-factory の、流れはグラフだけが持ち助け手は流れを知らない、の形）。機械: `works-dispatch/dispatch/nodes/` のファイルがほかのノードを import しない。
- **D4 外に書くのは決まったノードだけで、書いた後に読み戻す。** provision・launch・turn と、片付けの clean。機械: Python の構文木で見る。`subprocess` を import するのは外への口（`herdr.py`・`gitx.py`・`claudex.py`・`ghx.py`）と、whose-turn を呼ぶ prs のノードと、始める前の確かめを持つ入口だけ。herdr に書く関数（`run`・`prompt`・`create_workspace`・`close_workspace`）と、git に書く関数（`clone`・`set_origin`・`fetch`）を呼ぶのは、その 4 つのノードだけ（どのノードがどれを呼ぶかは柵の表に書く）。字の書き方を変えても逃げられないようにするため、字では探さない。読み戻しは人が見る。
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
limit_percent = 95                      # 使用率がこれを超えたアカウントは選ばない
limits_dir = "~/.cache/claude-limits"   # 使用率の控えの置き場

# name は使用率の控えのファイル名、command はそのアカウントで claude を起こすシェルのコマンド、
# config_dir はそのアカウントの Claude Code の設定のフォルダ（会話を集めるのと、始める前の確かめで attention を
# 探すのに使う。省くと Claude Code の既定のフォルダ）
accounts = [
  { name = "main", command = "claude",    config_dir = "~/.claude" },
  { name = "p1",   command = "claude-p1", config_dir = "~/.claude-p1" },
  { name = "p2",   command = "claude-p2", config_dir = "~/.claude-p2" },
  { name = "p3",   command = "claude-p3", config_dir = "~/.claude-p3" },
]

[[repos]]
repo = "<owner>/guided-resolver"
second_prompt_file = "~/.config/works-dispatch/dispatch-second-prompt.md"   # 2 ターン目の文（複数行）
source = "~/src/guided-resolver"        # 元の clone。PR ごとの clone はここから作る（中身をハードリンクで共有する）
clone_root = "~/src"                    # PR ごとの clone を置く場所（<clone_root>/guided-resolver-pr-<番号>）
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
- 元の clone（`source`）が、対象のリポジトリの clone である（origin が `repo` と同じ）。`clone_root` が有る。`copy_files` が写す元（`copy_from`、省けば元の clone）に有る（無いものは止めずに 1 行出す）。gh が `repo` を読める（`gh_user` が有れば、そのアカウントの鍵で `gh repo view` が通る）。

`--dry-run` を付けると、assign まで走らせて report を出し、何も起こさずに終わる。作業場を作るか使い直すかも、フォルダの有無から報告する。

## 7. 作らないもの

- 依存（仮想環境・`node_modules`）を入れること（3 節）。
- 片付けで、会話のある作業場・閉じていない PR の作業場・手元にしか無い変更のある作業場を消すこと。
- 会話を閉じる・止めること、`/clear` を打つこと。
- issue への割り振り（PR だけ）。
- こちらが足す期限・タイムアウト。
- 2 ターン目より後の操作。

## 8. 確かめ方

- 試験は `works-dispatch/dispatch/tests/` に置き、旧 works の試験の殻（`works/tests/run.sh`）には載せない（D1）。CI で回す道は、リポジトリの根の試験の殻から呼ぶ形にし、計画で決める。
- 判断のノード（accounts・assign・report と、片付けの候補の判定）は、速い段の単体テストで確かめる。外とのやりとりは偽物に差し替える。出力は schema で照らす。
- provision と clean は、一時のフォルダに作った小さな git のリポジトリを元の clone に見立てて、本物の git で試す（herdr だけ偽物）。
- 外とのやりとりは、手元の herdr で `--dry-run` を走らせ、持ち主の今の作業場の一覧と照らして確かめる。実際に起こすのは、持ち主が見ている前で 1 件だけ試す。

## 9. 作り手に任せること

- ファイルの分け方の細部、関数の名前、schema の細部。
- 報告の行の形の細部（1 PR 1 行は守る）。
- herdr の対象（TARGET）にはペイン ID を渡す（2026-10-14 に `herdr agent get <ペイン ID>` が通ることを確かめた）。
- launch で、herdr が会話を見つけて `idle` になるまでをどう待つか（会話が見つかる前のペインに `herdr agent wait` が効くか）。手元の版で、持ち主が見ている前で、PR 1 件の作業場で確かめてから決める。
- 既定のアカウントで、`CLAUDE_CONFIG_DIR=~/.claude` と明示した時と何も付けない時に、`claude agents --json` が同じ一覧を返すか。2026-10-14 にはどちらも空で一致した。
- `claude agents --json` の `cwd` は会話を起こした時のフォルダで、会話の途中で別のフォルダへ移ったことは追えない。作業場は clone ごとに分かれているので実害は小さいと見るが、持ち主の前の確かめで、起こした会話が選んだアカウントの一覧に出るかと合わせて見る。
- 複数行の 2 ターン目の文を `herdr agent prompt` で送ったときに、途中の改行で送信されずに 1 つの文として届くか。同じく持ち主の前で確かめる。届かなければ、herdr の貼り付けの口か、改行の送り方を探す。
