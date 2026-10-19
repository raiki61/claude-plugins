# 初めての設定と前提: `setup`・`--check`・`--init`

初めて dispatch（このプラグインの、AI を使わないスクリプト）を使う人と上から進める手順と、`--check` が確かめる前提の訳。持ち主は、このスキルを呼んだ会話の相手（dispatch を使う人）。`<…>` は自分の値に置き換える置き字。コマンドの `${CLAUDE_PLUGIN_ROOT}` は置き字ではなく、Claude Code がこのプラグインの入ったフォルダのパスを入れる変数で、置き換えずにそのまま打つ。このファイルは、dispatch のスキル（このスクリプトの打ち方を書いたスキル。`/works-dispatch:dispatch`）を動かす Claude Code の会話が読む。`/works-dispatch:dispatch setup` と呼ばれたら下の「初めて」のセクションの手順を持ち主と上から進め、`--check`（前提がそろっているかを確かめる引数）・`--init`（dispatch の設定ファイルの下書きを書く引数）を打つときや、前提が足りないと出たときは、当たるセクションだけを参照として読む。

言葉: 会社は、部署を置いて回す git のリポジトリ 1 つ。本社はその代表の clone。部署は、作業ごとの git worktree 1 つと、そこで働く Claude Code の裏の会話 1 つの組。役は部署の会話の決まりで、窓口（本社で持ち主と話し、部署に頼みを配る会話）・担当（受け持ち〔受ける仕事の範囲〕ごとに永続で立つ部署）・作業（一度きりの部署）・相談（持ち主が直接話して考えを詰める永続の部署。要る会社だけ足す）の 4 つ。部署の寿命は 2 つで、永続の部署（persistent。頼みが無くても残り、次の頼みを同じ部署で受ける）とエフェメラルの部署（ephemeral。頼みのために立て、済んだら畳む）。永続の部署の会話は、頼みごとに `/clear` で空にする「毎回クリア」（役の `fresh = true`）か、前の頼みの会話を残す「引き継ぎ」のどちらか。オンデマンドの受け持ち（会社の形の `on_demand = true`）は、永続の部署を置かず、頼まれたときだけエフェメラルの部署を立てる。属性は、代表の clone や部署の worktree の git の設定に `git config --worktree` で書いた `company.*` の値。herdr は、端末を作業ごとの作業場とペインに分け、中の Claude Code の会話を外から操作できるツール。tiers は要るツールがそろっているかを点検するプラグイン、attention は `/catchup`（PR や issue で前回自分が触ってから何が起きたかを出すコマンド）と `/whose-turn` を持つプラグイン。

## 前提（`--check` が全部確かめる）

`--check` は最初に、要るツール（gh・herdr・アカウントの起動コマンド）を共通の点検の部品 tiers（依存として入るプラグイン）で確かめ、足りなければ入れ方と案内を出して止まる。入れ方は持ち主に見せ、自分では走らせない（詳しい案内は、持ち主が `/tiers:check` で、会話が Bash のツールの `tiers --tier 2` で見られる。`/tiers:check` は会話からは呼べない）。tiers は、Claude Code の会話の中では依存の `bin/` が PATH に入るので名前で探し、会話の外から打ったときは、プラグインの置き場の隣（`<マーケットプレイス>/tiers/<版>/bin/tiers` のいちばん新しい版）を探す。見つからなければ、段の点検を飛ばして「足りない物は無い」とは言わず、止まって入れ方を出す。Windows では、herdr の連携を入れるコマンドを PowerShell で打てる形（`$env:CLAUDE_CONFIG_DIR='…'; herdr integration install claude`）で出す。


- [herdr](https://herdr.dev)（端末を作業場ごとに分けて、中の AI の会話を外から操作できるツール）が動いている。
- Claude Code が、開いている会話を読む `claude agents --json` を持つ版である。
- 使う各アカウントに、attention プラグインがアカウント全体（user）に入っている。
- 部署の回は、herdr の設定（`~/.config/herdr/config.toml`）の作業場の行（`[ui.sidebar.spaces]` の `rows`）のどこかに `{ token = "$kind" }` がある。部署の作業場の行に、永続・毎回クリア／永続・引き継ぎ／エフェメラルの印を出すため（`$kind` は dispatch が部署の作業場に付ける herdr の印の名前）。無ければ `--check` が足す行を出し、部署を立てる回は止める（PR を開く回は注記だけ）。足したら `herdr server reload-config` を打つ。
- gh でそのリポジトリを読める（PR を開く回だけ。部署の回は GitHub を読まない）。普段の gh のアカウントで読めなければ、設定の `gh_user` に読めるアカウントを書く。
- リポジトリごとに代表の clone（ブランチごとの worktree を作る元にする、ふつうの clone。設定の `source` に書く）がある。どれか 1 つのアカウントで一度そこで Claude Code を起動し、フォルダを信頼しておく（dispatch がほかのアカウントにも信頼の印を広げる）。どのアカウントも信頼していないと、ブランチごとの作業場で毎回、信頼の確認が出る。代表の clone は既定のブランチ（main など）に置いておく。linked worktree（`git worktree add` で作った側）は代表の clone にできない（`--check` が止める）。代表の clone が開いているブランチの PR は、作業場を作れない（`branch_busy`）。

## 初めて: `/works-dispatch:dispatch setup`

`setup` はスクリプトの引数ではない。そう呼ばれたら、このセクションの手順を上から持ち主と進める。下書きを書く `--init`（dispatch の設定）と `--init-company`（会社の形）は、もうあれば上書きしない。

部署（作業ごとの git worktree と裏の Claude Code の会話の組。`--task` で立て、`--ask` で頼み、`--land` でメインブランチに入れる。「部署を立てる」）だけを使うなら、ふつうは dispatch の設定のファイルは要らない（要るときは、手順 2 の終わりの `[[repos]]` の段）。部署を立てるリポジトリ（会社）は、`--repo` に渡した代表の clone のパスか、コマンドを打ったフォルダのリポジトリで決まる。

1. 会社の形（`.claude/company.toml`。会社の名前・役・メインブランチへの入れ方）の下書きを書き、名前・説明・役の本文を直す。下書きの役は、受け持ちごとに永続の `担当`（`persistent = true`。頼みごとに空の会話で受ける `fresh = true`）と、一度きりの `作業`（`--role` を省いたときの役。`default_role`）と、`窓口`（代表の clone で `--desk` を打った会話に、組織の決まりを役の本文として届ける）の 3 つ。担当と作業はコードの直しなので、納品の項目を `結論・差分・試験・残った疑問・ブランチ` にする（既定の項目「決め手」〔結論の根拠にした原典の一句と URL〕を求めない）。担当の本文は、ブランチを切った後に触るファイルをメインブランチから読み直すこと（前の頼みで覚えた中身で書かない）を言う。受け持ちは受ける仕事（`[[skills]]`）の項目で書き、担当の部署の名前を受け持ちの名前にすると、その説明が担当の会話に足される。組織の決まり（役は窓口・担当・作業・相談の 4 つ・名前は herdr で読んで分かる短い日本語で、作業は `<受け持ち>：<何をするか>`・会社の名前は herdr の親の作業場（代表の clone の作業場。部署の作業場はその下に子として並ぶ）にだけ出し部署の名前に付けない・ブランチの名前は英小文字とハイフン・担当への頼みは部署の名前で宛てる・納品の後に判断が要れば、もう一度 `--deliver`〔部署が結果の要約を頼み元へ返す、納品のコマンド〕で頼み元へ返す）はコメントで書く。`<…>` の置き字（受け持ちの名前と中身）を直す。下書きの会社の名前は origin の `OWNER/NAME` の `NAME`（origin が無ければ代表の clone のフォルダの名前）、`gh_user` は、dispatch の設定の `[[repos]]` の `gh_user`、origin の持ち主のアカウント、`--init-company` を打った時の gh の今のアカウントの順に、`gh auth token --user` で鍵を取り出せる最初の物（どれも取り出せなければ書かない）。作業の本文は、納品し、ブランチがメインブランチに入ったら（commit の無い頼みなら納品の後に）`--done` で畳むことまで言い、窓口の本文は納品の後も残った部署を `--retire` で畳むことを言う。役の本文のブランチの名前・試験の回し方・メインブランチへの入れ方は既定の例なので、そのリポジトリの決まりに合わせて直す。一度きりの仕事を並べて、仕事の種類でモデルを替えたいなら、受け持ちでなく役で分ける（[roles.md](roles.md) と、下書きのコメントの例）。窓口は最初から代表の clone に立てる（手順 5）。既定はリポジトリの中に書くので、同じリポジトリを使う人にも効かせるなら commit する。commit しないなら `--local` を付けて、dispatch の設定のフォルダ（既定は `~/.config/works-dispatch/`）の `companies/` に書く。

   ```
   bash "${CLAUDE_PLUGIN_ROOT}/hooks/run-python.sh" "${CLAUDE_PLUGIN_ROOT}/dispatch/dispatch.py" --init-company [--local] [--repo <代表の clone>]
   ```

2. PR を開く回（引数なし・`--pr`・`--issue`）も使う人は、dispatch の設定（既定は `~/.config/works-dispatch/dispatch.toml`）の下書きを書く。隣に空の `dispatch-second-prompt.md` ができるので、`/catchup` の後に送る文（2 ターン目の文）を書く。`--init` は設定がもうあると書かずに止まるので、手順 3 で設定を書くより先に打つ（もうあるなら `[[repos]]` を手で足す）。

   ```
   bash "${CLAUDE_PLUGIN_ROOT}/hooks/run-python.sh" "${CLAUDE_PLUGIN_ROOT}/dispatch/dispatch.py" --init --repo OWNER/NAME --source <代表の clone>
   ```

   設定の `[[repos]]` が要るのは、PR を開く回のほかは、`--repo` を `OWNER/NAME` の形で指すとき、git の外から `--repo` 無しで打つとき、部署の gh を会社の形と違うアカウント（`gh_user`）にするとき、新しい worktree へ手元だけのファイルを写す（`copy_files`）ときだけ。
3. アカウントを切り替える人だけ、dispatch の設定に `accounts` を書く（下の「アカウントの書き方」）。書かなければ `claude` 1 つで動く。
4. `--check` を、足りない物が出なくなるまで走らせる（`[[repos]]` が無ければ、部署の前提だけを見る）。`[[repos]]` は有るがこのリポジトリが書かれていないときは、`--check --repo <代表の clone>` で、その clone の部署の前提だけを見る（部署の回のために `[[repos]]` を足さなくてよい）。
5. 窓口（持ち主と話し、部署を立てる会話）は、持ち主が名前を付けて起動する（`claude --name 窓口`。アカウントを切り替える人は、そのアカウントのコマンドに `--name 窓口` を足す）。部署はその名前を SendMessage（Claude Code の、同じアカウントのほかの会話へ名前で文を送るツール）の宛先にする。名前が無いと `my-notes-31` のような自動の名前になる。起動した窓口の会話から `--desk`（打った会話を、この会社の窓口として記録する引数）を打つと、代表の clone の属性に窓口（役・名前・アカウント・会話の id）を書き、herdr のペインと作業場の名前・表示を属性に合わせて付け直す（[reorg.md](reorg.md) の「組み直す」）。会社の形の窓口の役に起動の設定（`[roles.settings]`。その会話にだけ効く Claude Code の設定〔権限・プラグインの有効と無効など〕）が有れば、`--desk` はそれをファイルに書き、そのファイルを `--settings <ファイル>` で渡す起動コマンドを出す。そのコマンドで窓口を起動し直すと、役の設定が窓口の会話に効く。

### アカウントの書き方

アカウントの数に決まりは無く、1 つでも 7 つでも同じ形で書く（herdr のタブバーに使用率を並べられるのは 15 個まで）。持ち方は人で違うので、次の 3 通りを 1 つの設定に混ぜてよい。

- **`claude` をそのまま使う。** `accounts` を書かない。`claude` 1 つで動き、鍵は Claude Code 自身が保存したものを使う。
- **設定のフォルダを分ける。** アカウントごとに、`name`（使用率の控えの名前）、`command`（そのアカウントで Claude Code を起動するシェルのコマンド）、`config_dir`（そのアカウントの Claude Code が使う設定のフォルダ。`CLAUDE_CONFIG_DIR` の値）を書く。`config_dir` を書くかは、dispatch がそのフォルダを自分で見つけられるかで決まる。dispatch は、走らせている会話の環境の値を使わず、`config_dir` を書かなければ、作業場のペインで新しく起きるログインのシェルが設定ファイル（`~/.zshrc` など）で入れる `CLAUDE_CONFIG_DIR`、それも無ければ `~/.claude` を見る（Windows はシェルの値を読めないので、いつも `~/.claude`）。だから、`command` が `CLAUDE_CONFIG_DIR` を入れる人（例 `CLAUDE_CONFIG_DIR=~/.claude-p1 claude`）と、端末で手で `export` を打ってから `claude` を起動する人は、そのフォルダを `config_dir` に書く。どこでも入れない人と、シェルの設定ファイルで入れる人は書かなくてよい。書くべき所で書かないと、dispatch が読み書きする信頼の印（Claude Code が設定のフォルダの `.claude.json` の `projects` に書く、そのフォルダを信頼したという記録）・会話の一覧・使用率の控えが、そのアカウントの物でなく別のフォルダの物になる（`docs/prerequisites.md` の 3）。鍵を自分で決めた名前の Keychain の項目に置いたなら、その名前を `keychain_service` に書く。setup-token の鍵だけで動かすアカウントは、`limits.py plan`（アカウントごとのサブスクのプランを出すコマンド）がプランを読めない（読むのは Claude Code がログインのときに書く記録で、setup-token の鍵はプランを問い合わせられない）。ログインしないなら、プランを `plan` に書く（例 `plan = "default_claude_max_20x"`。形はログインの記録の `organizationRateLimitTier` と同じ）。書いた値は、記録が読めないときだけ使い、`limits.py plan` は記録から引いた値と分けて出す。
- **使用率の枠が無い（Ollama、Foundry など）。** `limits = false` を足す。dispatch は会話を起動するアカウントを選ぶとき、使用率が上限（設定の `limit_percent`）に届いたアカウントを候補から外し、残りを、週の枠の切り替わりが近い物、次に使用率（5 時間と週の枠の高い方）の低い物の順に並べて先頭を使う。`limits = false` のアカウントは使用率が分からないので、上限で候補から外すことはせず、使用率の分かるアカウントの後ろに並べる（使用率の分かるアカウントがどれも上限に届いたときに選ばれる）。
- **使える時間帯が決まっている（1 日の決まった時間だけ要求を受ける API など）。** `hours = "08:00-16:00 UTC"` のように、始まりと終わりの時刻と時刻の基準を書く。時刻の基準は必ず書く（`UTC` か `Asia/Tokyo` などの IANA の地域の名前。`JST`・`EST` のような略は読まない。書き落とすと設定を読む所で止まる。Windows は地域の時刻の表が無いので `UTC` で書く）。日をまたぐ時間帯は、終わりを始まりより前（`"17:00-01:00 Asia/Tokyo"`）か 24 時より後（`"17:00-25:00 Asia/Tokyo"`）に書く。dispatch は、時間帯の外のアカウントと、終わりまで `hours_margin_minutes`（設定の上の段。既定 30 分）を切ったアカウントを、部署の起動にも移し先にも選ばない。動いている会話の扱いは [move.md](move.md) の「使える時間帯が終わるとき」。

## 任意: herdr の見た目を整える

dispatch はこれが無くても動く。ブランチごとの作業場が増えたときに、どのアカウントに余裕があり、どの会話が何をしているかを見やすくする。

1. **herdr の連携を、アカウントごとに入れる。** `--check` が、入っていないアカウントについて、入れるコマンド（`CLAUDE_CONFIG_DIR=<フォルダ> herdr integration install claude`）を出す。herdr を立ち上げ直したときに、会話を戻すのに使われる。
2. **タブバーに、アカウントごとの使用率を出す。** 次のコマンドが出す行を、herdr の設定（`~/.config/herdr/config.toml`）の `[ui]` に貼る。アカウントごとに表示が 1 つ（例: `p1 5h 38% 1h4m  7d 32% 2d4h`。`5h` は 5 時間の枠、`7d` は週の枠で、使用率と切り替わりまでの時間）と、5 分ごとに控えを取り直す行が 1 つ並ぶ。取り直しは、使っていないアカウントの控えが古くなったときだけ、出力 0 トークンの問い合わせを 1 回投げる。

   ```
   bash "${CLAUDE_PLUGIN_ROOT}/hooks/run-python.sh" "${CLAUDE_PLUGIN_ROOT}/dispatch/limits.py" herdr-config
   ```

   行は版に依らない入口（`~/.cache/claude-limits/limits-entry.py`。このコマンドが写す）を指す。入口は起動のたびに、今入っている版の `limits.py` を探して起動するので、プラグインを上げても行を貼り直さなくてよい。入口を写し直す要る版（入口の中身が変わった版）では、`--check` と `--tree` が知らせる。

   このコマンドは、アカウントの一覧の写し（`~/.cache/claude-limits/accounts.json`）も書く。タブバーの行は設定のファイルではなくこの写しを読むので、設定のアカウントを足したり変えたりしたら、このコマンドを走らせ直して行を貼り直す。

   使用率の控えは、dispatch がアカウントを選ぶのにも使う。Claude Code の statusline のコマンドから、受けた JSON を `bash "${CLAUDE_PLUGIN_ROOT}/hooks/run-python.sh" --min 3.9 "${CLAUDE_PLUGIN_ROOT}/dispatch/limits.py" record` の標準入力にも渡すと、使っているアカウントの 5 時間の枠がすぐ動く。社内のプロキシの内側では、herdr を起動するシェルに `HTTPS_PROXY` が要る。失敗は `~/.cache/claude-limits/probe.log` に残り、取れるまで、タブバーのそのアカウントの表示に「取り直し失敗」が、`--tree` と `--check` に訳が出る。控えが 3 時間より古ければ、表示に「古い」が付き、アカウントを選ぶ順の最後に置く。
3. **サイドバーに、会話ごとの作業内容を出す。** 作業中は動いているツールを、ターンが終わると直前に頼んだ内容を出す。次のコマンドが出す `hooks` の塊を、各アカウントの Claude Code の設定（`settings.json`）に足す。すでに `hooks` があれば、出来事ごとの並びに足す。

   ```
   bash "${CLAUDE_PLUGIN_ROOT}/hooks/run-python.sh" "${CLAUDE_PLUGIN_ROOT}/dispatch/activity.py" settings
   ```

   そのうえで、herdr の設定の `[ui.sidebar.agents.rows_by_agent]` にある `claude` の行のどこかに、`{ token = "$act" }` を置く（`$act` は、上のフックが作業内容を送る herdr の印の名前）。

2 と 3 の行（2 で貼るタブバーの行と、3 で足すフックの行）は、Python をフックと同じ決まり（`hooks/run-python.sh`。`python3`・`python`・`py -3` の順に、実際に起きる物を選び、Windows の Microsoft Store へ誘う代わりの物を飛ばす。TOML を読まない台本なので下限は 3.9）で選ぶ。3 の行は、プラグインの入った場所（版ごとのフォルダ）を指す。プラグインを更新すると、前の版のフォルダには `.orphaned_at` が付き、14 日で消える。前の版・今入っていない版・消えた場所を指していれば `--check` と `--tree` が知らせるので、そのときは行を出し直す（2 の行の前の形〔版のフォルダの `limits.py` を直に指す行〕も同じく知らせる）。
