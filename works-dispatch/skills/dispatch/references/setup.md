# 初めての設定と前提: `setup`・`--check`・`--init`

## 前提（`--check` が全部確かめる）

`--check` は最初に、要る道具（gh・herdr・アカウントの起こし方の命令）を共通の点検の部品 tiers（依存として入るプラグイン）で確かめ、足りなければ入れ方と案内を出して止まる。入れ方は持ち主に見せ、自分では走らせない（詳しい案内は、持ち主が `/tiers:check` で見られる）。tiers は、Claude Code の会話の中では依存の `bin/` が PATH に入るので名前で探し、会話の外から打ったときは、プラグインの置き場の隣（`<マーケットプレイス>/tiers/<版>/bin/tiers` のいちばん新しい版）を探す。見つからなければ、段の点検を飛ばして「足りない物は無い」とは言わず、止まって入れ方を出す。Windows では、herdr の連携を入れる命令を PowerShell で打てる形（`$env:CLAUDE_CONFIG_DIR='…'; herdr integration install claude`）で出す。


- [herdr](https://herdr.dev)（端末を作業場ごとに分けて、中の AI の会話を外から操作できる道具）が動いている。
- Claude Code が、開いている会話を読む `claude agents --json` を持つ版である。
- 使う各アカウントに、attention プラグインがアカウント全体（user）に入っている。
- 部署の回は、herdr の設定（`~/.config/herdr/config.toml`）の作業場の行（`[ui.sidebar.spaces]` の `rows`）のどこかに `{ token = "$kind" }` がある。部署の作業場の行に、常設・毎回空／常設・持ち越し／都度の印を出すため（`$kind` は dispatch が部署の作業場に付ける herdr の印の名前）。無ければ `--check` が足す行を出し、部署を立てる回は止める（PR を開く回は注記だけ）。足したら `herdr server reload-config` を打つ。
- gh でそのリポジトリを読める（PR を開く回だけ。部署の回は GitHub を読まない）。普段の gh のアカウントで読めなければ、設定の `gh_user` に読めるアカウントを書く。
- リポジトリごとに代表の clone（枝ごとの worktree を作る元にする、ふつうの clone。設定の `source` に書く）がある。どれか 1 つのアカウントで一度そこで Claude Code を起こし、フォルダを信頼しておく（dispatch がほかのアカウントにも信頼の印を広げる）。どのアカウントも信頼していないと、枝ごとの作業場で毎回、信頼の確認が出る。代表の clone は既定の枝（main など）に置いておく。linked worktree（`git worktree add` で作った側）は代表の clone にできない（`--check` が止める）。代表の clone が開いている枝の PR は、作業場を作れない（`branch_busy`）。

## 初めて: `/works-dispatch:dispatch setup`

`setup` はスクリプトの引数ではない。そう呼ばれたら、この節の手順を上から持ち主と進める。下書きを書く `--init`（dispatch の設定）と `--init-company`（会社の形）は、もうあれば上書きしない。

部署（作業ごとの git worktree と裏の Claude Code の会話の組。`--task` で立て、`--ask` で頼み、`--land` で本流に入れる。「部署を立てる」）だけを使うなら、ふつうは dispatch の設定のファイルは要らない（要るときは手順 2 の終わり）。部署を立てるリポジトリ（会社）は、`--repo` に渡した代表の clone のパスか、コマンドを打ったフォルダのリポジトリで決まる。

1. 会社の形（`.claude/company.toml`。会社の名前・役・本流への入れ方）の下書きを書き、名前・説明・役の本文を直す。下書きの役は、受け持ちに常設の `担当`（`resident = true`。頼みごとに空の会話で受ける `fresh = true`）と、一度きりの `作業`（`--role` を省いたときの役。`default_role`）と、`窓口`（代表の clone で `--desk` を打った会話に、組織の決まりを役の本文として届ける）の 3 つ。担当と作業はコードの直しなので、納品の項目を `結論・差分・試験・残った疑問・枝` にする（既定の「決め手」の原典の URL を求めない）。担当の本文は、枝を切った後に触るファイルを本流から読み直すこと（前の頼みで覚えた中身で書かない）を言う。受け持ちは受ける仕事（`[[skills]]`）の項目で書き、担当の部署の名前を受け持ちの名前にすると、その説明が担当の会話に足される。組織の決まり（役は窓口・担当・作業・相談の 4 つ・名前は herdr で読んで分かる短い日本語で、作業は `<受け持ち>：<何をするか>`・会社の名前は herdr の親の作業場にだけ出し部署の名前に付けない・枝の名前は英小文字とハイフン・担当への頼みは部署の名前で宛てる・納品の後に判断が要れば、もう一度 `--deliver` で返す）はコメントで書く。`<…>` の置き字（受け持ちの名前と中身）を直す。既定はリポジトリの中に書くので、同じリポジトリを使う人にも効かせるなら commit する。commit しないなら `--local` を付けて、dispatch の設定のフォルダ（既定は `~/.config/works-dispatch/`）の `companies/` に書く。

   ```
   bash "${CLAUDE_PLUGIN_ROOT}/hooks/run-python.sh" "${CLAUDE_PLUGIN_ROOT}/dispatch/dispatch.py" --init-company [--local] [--repo <代表の clone>]
   ```

2. PR を開く回（引数なし・`--pr`・`--issue`）も使う人は、dispatch の設定（既定は `~/.config/works-dispatch/dispatch.toml`）の下書きを書く。隣に空の `dispatch-second-prompt.md` ができるので、`/catchup` の後に送る文（2 ターン目の文）を書く。`--init` は設定がもうあると書かずに止まるので、手順 3 で設定を書くより先に打つ（もうあるなら `[[repos]]` を手で足す）。

   ```
   bash "${CLAUDE_PLUGIN_ROOT}/hooks/run-python.sh" "${CLAUDE_PLUGIN_ROOT}/dispatch/dispatch.py" --init --repo OWNER/NAME --source <代表の clone>
   ```

   設定の `[[repos]]` が要るのは、PR を開く回のほかは、`--repo` を `OWNER/NAME` の形で指すとき、git の外から `--repo` 無しで打つとき、部署の gh を会社の形と違うアカウント（`gh_user`）にするとき、新しい worktree へ手元だけのファイルを写す（`copy_files`）ときだけ。
3. アカウントを切り替える人だけ、dispatch の設定に `accounts` を書く（下の「アカウントの書き方」）。書かなければ `claude` 1 つで動く。
4. `--check` を、足りない物が出なくなるまで走らせる（`[[repos]]` が無ければ、部署の前提だけを見る）。
5. 窓口（持ち主と話し、部署を立てる会話）は、持ち主が名前を付けて起こす（`claude --name 窓口`。アカウントを切り替える人は、そのアカウントのコマンドに `--name 窓口` を足す）。部署はその名前を SendMessage の宛先にする。名前が無いと `my-notes-31` のような自動の名前になる。起こした窓口の会話から `--desk` を打つと、代表の clone の属性に窓口（役・名前・アカウント・会話の id）を書き、herdr の表示を付け直す（「組み直す」）。窓口の役に起動の設定（`[roles.settings]`）が有れば、`--desk` が出す命令（`--settings <ファイル>` 付き）で起こすと、その設定が窓口の会話に効く。

### アカウントの書き方

アカウントの数に決まりは無く、1 つでも 7 つでも同じ形で書く（herdr のタブ欄に使用率を並べられるのは 15 個まで）。持ち方は人で違うので、次の 3 通りを 1 つの設定に混ぜてよい。

- **`claude` をそのまま使う。** `accounts` を書かない。`claude` 1 つで動き、鍵は Claude Code 自身が保存したものを使う。
- **設定のフォルダを分ける。** アカウントごとに、`name`（使用率の控えの名前）、`command`（そのアカウントで Claude Code を起こすシェルのコマンド）、`config_dir`（そのコマンドが `CLAUDE_CONFIG_DIR` に入れるフォルダ）を書く。コマンドが `CLAUDE_CONFIG_DIR` を入れないなら、`config_dir` は書かない。鍵を自分で決めた名前の Keychain の項目に置いたなら、その名前を `keychain_service` に書く。`CLAUDE_CONFIG_DIR` をシェルの環境（`export` など）でだけ入れて `claude` を起こす人も、そのフォルダを `config_dir` に書く。dispatch は、走らせている会話の環境の値を使わず、書かなければ `~/.claude` を見るので、信頼の印・会話の一覧・使用率の控えが別のフォルダの物になる（`docs/prerequisites.md` の 3）。
- **使用率の枠が無い（Ollama、Foundry など）。** `limits = false` を足す。使用率では外さず、使用率の分かるアカウントの後ろに並べる。

## 任意: herdr の見た目を整える

dispatch はこれが無くても動く。枝ごとの作業場が増えたときに、どのアカウントに余裕があり、どの会話が何をしているかを見やすくする。

1. **herdr の連携を、アカウントごとに入れる。** `--check` が、入っていないアカウントについて、入れるコマンド（`CLAUDE_CONFIG_DIR=<フォルダ> herdr integration install claude`）を出す。herdr を立ち上げ直したときに、会話を戻すのに使われる。
2. **タブ欄に、アカウントごとの使用率を出す。** 次のコマンドが出す行を、herdr の設定（`~/.config/herdr/config.toml`）の `[ui]` に貼る。アカウントごとに表示が 1 つ（例: `p1 5h 38% 1h4m  7d 32% 2d4h`。`5h` は 5 時間の枠、`7d` は週の枠で、使用率と切り替わりまでの時間）と、5 分ごとに控えを取り直す行が 1 つ並ぶ。取り直しは、使っていないアカウントの控えが古くなったときだけ、出力 0 トークンの問い合わせを 1 回投げる。

   ```
   bash "${CLAUDE_PLUGIN_ROOT}/hooks/run-python.sh" "${CLAUDE_PLUGIN_ROOT}/dispatch/limits.py" herdr-config
   ```

   このコマンドは、アカウントの一覧の写し（`~/.cache/claude-limits/accounts.json`）も書く。タブ欄の行は設定のファイルではなくこの写しを読むので、設定のアカウントを足したり変えたりしたら、このコマンドを走らせ直して行を貼り直す。

   使用率の控えは、dispatch がアカウントを選ぶのにも使う。Claude Code の statusline のコマンドから、受けた JSON を `bash "${CLAUDE_PLUGIN_ROOT}/hooks/run-python.sh" --min 3.9 "${CLAUDE_PLUGIN_ROOT}/dispatch/limits.py" record` の標準入力にも渡すと、使っているアカウントの 5 時間の枠がすぐ動く。社内のプロキシの内側では、herdr を起こすシェルに `HTTPS_PROXY` が要る。失敗は `~/.cache/claude-limits/probe.log` に残る。
3. **サイドバーに、会話ごとの作業内容を出す。** 作業中は動いているツールを、ターンが終わると直前に頼んだ内容を出す。次のコマンドが出す `hooks` の塊を、各アカウントの Claude Code の設定（`settings.json`）に足す。すでに `hooks` があれば、出来事ごとの並びに足す。

   ```
   bash "${CLAUDE_PLUGIN_ROOT}/hooks/run-python.sh" "${CLAUDE_PLUGIN_ROOT}/dispatch/activity.py" settings
   ```

   そのうえで、herdr の設定の `[ui.sidebar.agents.rows_by_agent]` にある `claude` の行のどこかに、`{ token = "$act" }` を置く（`$act` は、上のフックが作業内容を送る herdr の印の名前）。

2 と 3 の行は、Python をフックと同じ決まり（`hooks/run-python.sh`。`python3`・`python`・`py -3` の順に、実際に起きる物を選び、Windows の Microsoft Store へ誘う代わりの物を飛ばす。TOML を読まない台本なので下限は 3.9）で選ぶ。2 と 3 の行は、プラグインの入った場所（版ごとのフォルダ）を指す。プラグインを更新すると、そのフォルダが消えることがある。消えた場所を指していれば `--check` が知らせるので、そのときは行を出し直す。
