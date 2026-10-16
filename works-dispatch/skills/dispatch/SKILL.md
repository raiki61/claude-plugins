---
name: dispatch
description: 自分の番の PR（attention プラグインの /whose-turn が「自分の番」に並べるもの）を、枝ごとの作業場（代表の clone の git worktree と herdr の作業場）に開き、使用率に余裕のあるアカウントの Claude Code を起こして、/catchup（その PR のどこで止まっていたかを出す attention の命令）と、設定のファイルに書いた 2 ターン目の文を送る。issue から始める作業は、issue に結んだ枝の作業場を開いて /catchup まで送る。「自分の番を全部開いて」「PR を展開して」「#1234 を開いて catchup して」「issue #1300 を始めて」と言われたときに使う。初めて使う人は「/works-dispatch:dispatch setup」。
---

# dispatch

自分の番の PR を、枝ごとの作業場で開くところまでを機械でやる。「自分の番の PR」は、attention プラグインの `/whose-turn` が「自分の番」の節に並べる PR（直す番の自分の PR と、レビューする番の PR）である。

1. PR の枝ごとに作業場を用意する。代表の clone から、その枝の git worktree を herdr に作らせ（置き場は herdr の設定の `worktrees.directory`）、herdr の作業場を開く。その枝の worktree が既にあれば開き直す。どちらでも、origin の今の head へ早送りしてから渡す（手元にしか無い commit が有れば動かさない）。代表の clone 自身がその枝を開いていれば作らない（`branch_busy`）。
2. 週の使用率のリセットが近いアカウントから順に、使用率が 95% に届かない件数まで PR を割り振り、Claude Code を起こす。件数は、1 件あたりの使用率（dispatch が毎回の前後で測って覚える）から決める。まだ測っていなければ、選べるアカウントに 1 件ずつ順に配る。
3. attention の `/catchup <番号>` を送る。これは、その PR で前回自分が触ってから何が起きたかを出す命令である。それが終わったら、設定のファイルに書いた 2 ターン目の文を送る。
4. 会話が開いている PR は、前に送った後に相手の新しい返事（コメント・レビュー・commit。Bot は数えない）が有り、会話が手すきで手元の作業も無ければ、古い会話を終えてペインを畳み、同じ場所に新しい作業場と会話を立てて 3 から送り直す。2 回目も前の会話を持たない新しい目で見るためである。
5. 閉じた（merge・close した）PR の枝の場所は片付ける（worktree と手元の枝を消す）。会話が手すきで手元の作業も無ければ、会話を終えてから消す。見るのは代表の clone の worktree だけで、ほかのリポジトリには触らない。PR の無い枝（issue から始めてまだ PR を作っていないもの）は消さない。

AI は使わない。このスキルは下のスクリプトを走らせ、出力をそのまま見せるだけで、判断も言い換えもしない。

```
python3 "${CLAUDE_PLUGIN_ROOT}/dispatch/dispatch.py" <引数>
```

PR を開く回（引数なし・`--pr`・`--issue`）は、Bash の道具の `run_in_background` で走らせ、終わりの知らせが来てから出力を見せる。dispatch は各 PR の `/catchup` が終わるのを待ってから 2 ターン目を送るので、数分かかる。前で走らせると、Bash の道具の時間の上限で止められ、2 ターン目も報告も出ない。`--dry-run`・`--check`・`--clean`・`--init` はすぐ終わるので、前で走らせてよい。

## 前提（`--check` が全部確かめる）

- [herdr](https://herdr.dev)（端末を作業場ごとに分けて、中の AI の会話を外から操作できる道具）が動いている。
- Claude Code が、開いている会話を読む `claude agents --json` を持つ版である。
- 使う各アカウントに、attention プラグインがアカウント全体（user）に入っている。
- gh でそのリポジトリを読める。普段の gh のアカウントで読めなければ、設定の `gh_user` に読めるアカウントを書く。
- リポジトリごとに代表の clone がある。各アカウントで一度そこで Claude Code を起こし、フォルダを信頼しておく。信頼していないと、枝ごとの作業場で毎回、信頼の確認が出る。代表の clone は既定の枝（main など）に置いておく。`source` には本体の clone を書く（linked worktree なら `--check` が止める）。代表の clone が開いている枝の PR は、作業場を作れない（`branch_busy`）。

## 初めて: `/works-dispatch:dispatch setup`

1. 今いるリポジトリについて、設定の下書きを書く。`--repo` は origin の `OWNER/NAME`、`--source` は今いる clone の根にする。

   ```
   python3 "${CLAUDE_PLUGIN_ROOT}/dispatch/dispatch.py" --init --repo OWNER/NAME --source <代表の clone>
   ```

2. 書かれた設定（既定は `~/.config/works-dispatch/dispatch.toml`）を、利用者が埋める。埋めるのは、2 ターン目の文のファイルと、アカウントを切り替える人だけ `accounts` である。
3. `--check` を、足りない物が出なくなるまで走らせる。

### アカウントの書き方

アカウントの数に決まりは無く、1 つでも 7 つでも同じ形で書く（herdr のタブ欄に使用率を並べられるのは 15 個まで）。持ち方は人で違うので、次の 3 通りを 1 つの設定に混ぜてよい。

- **`claude` をそのまま使う。** `accounts` を書かない。`claude` 1 つで動き、鍵は Claude Code 自身が保存したものを使う。
- **設定のフォルダを分ける。** アカウントごとに、`name`（使用率の控えの名前）、`command`（そのアカウントで Claude Code を起こすシェルのコマンド）、`config_dir`（そのコマンドが `CLAUDE_CONFIG_DIR` に入れるフォルダ）を書く。コマンドが `CLAUDE_CONFIG_DIR` を入れないなら、`config_dir` は書かない。鍵を自分で決めた名前の Keychain の項目に置いたなら、その名前を `keychain_service` に書く。
- **使用率の枠が無い（Ollama、Foundry など）。** `limits = false` を足す。使用率では外さず、使用率の分かるアカウントの後ろに並べる。

## 任意: herdr の見た目を整える

dispatch はこれが無くても動く。枝ごとの作業場が増えたときに、どのアカウントに余裕があり、どの会話が何をしているかを見やすくする。

1. **herdr の連携を、アカウントごとに入れる。** `--check` が、入っていないアカウントについて、入れるコマンド（`CLAUDE_CONFIG_DIR=<フォルダ> herdr integration install claude`）を出す。herdr を立ち上げ直したときに、会話を戻すのに使われる。
2. **タブ欄に、アカウントごとの使用率を出す。** 次のコマンドが出す行を、herdr の設定（`~/.config/herdr/config.toml`）の `[ui]` に貼る。アカウントごとに表示が 1 つ（例: `p1 5h 38% 1h4m  7d 32% 2d4h`）と、5 分ごとに控えを取り直す行が 1 つ並ぶ。取り直しは、使っていないアカウントの控えが古くなったときだけ、出力 0 トークンの問い合わせを 1 回投げる。

   ```
   python3 "${CLAUDE_PLUGIN_ROOT}/dispatch/limits.py" herdr-config
   ```

   このコマンドは、アカウントの一覧の写し（`~/.cache/claude-limits/accounts.json`）も書く。タブ欄の行は設定のファイルではなくこの写しを読むので、設定のアカウントを足したり変えたりしたら、このコマンドを走らせ直して行を貼り直す。

   使用率の控えは、dispatch がアカウントを選ぶのにも使う。Claude Code の statusline のコマンドから、受けた JSON を `limits.py record` の標準入力にも渡すと、使っているアカウントの 5 時間の枠がすぐ動く。社内のプロキシの内側では、herdr を起こすシェルに `HTTPS_PROXY` が要る。失敗は `~/.cache/claude-limits/probe.log` に残る。
3. **サイドバーに、会話ごとの作業内容を出す。** 作業中は動いているツールを、ターンが終わると直前に頼んだ内容を出す。次のコマンドが出す `hooks` の塊を、各アカウントの Claude Code の設定（`settings.json`）に足す。すでに `hooks` があれば、出来事ごとの並びに足す。

   ```
   python3 "${CLAUDE_PLUGIN_ROOT}/dispatch/activity.py" settings
   ```

   そのうえで、herdr の設定の `[ui.sidebar.agents.rows_by_agent]` にある `claude` の行のどこかに、`{ token = "$act" }` を置く。

2 と 3 の行は、プラグインの入った場所（版ごとのフォルダ）を指す。プラグインを更新すると、そのフォルダが消えることがある。消えた場所を指していれば `--check` が知らせるので、そのときは行を出し直す。

## 使い方: `/works-dispatch:dispatch <引数>`

- 引数なし: 自分の番の PR を全部開き、返事の有った PR を送り直し、閉じた PR の作業場を片付ける。自分が作者でレビュアーの付いていない PR も開くが、`/catchup` だけを送り、2 ターン目の文は送らない（`--pr` で指したときも同じ）。
- `--dry-run`: 何も起こさず、どの PR をどのアカウント・どの作業場で開くか、どれを送り直すか（`refresh`）、どれを片付けるかだけを出す。
- `--pr N`: 指した番号の PR だけを開く。複数なら `--pr` を重ねる。止めている実装や、見に行くだけの PR に使う。レビュアーの有無では外さず、送り直しも片付けもしない。
- `--issue N`: issue から始める。issue に結んだ枝（`gh issue develop --list`）の作業場を開き、1 ターン目の `/catchup N` まで送って止める（2 ターン目のレビューの文は送らない）。枝が見えなければ、その issue を閉じる開いた PR の枝を使い、それも無ければ既定の枝から GitHub に枝を作って issue に結ぶ（`gh issue develop`。GitHub に書く）。閉じた issue なら枝を作らずに止める（`issue_closed`）。`--pr` とは一緒に使えない。送り直しも片付けもしない。
- `--no-second`: `/catchup` だけで止め、2 ターン目の文を送らない。
- `--clean`: 代表の clone の worktree のうち、消してよい場所を並べる。消してよいのは、枝の PR が閉じていて、会話が無く、未コミットの変更・git に足していないファイル・その枝の stash が無く、手元の枝の先頭が PR の head と同じものだけ。設定の `copy_files` のうち写し元と中身が違うファイルが有る場所も残し、そのファイルを出す（依存や生成物などほかの git が追わないファイルは一緒に捨てる）。`--clean --apply` で本当に消す（worktree と手元の枝を消す。未コミットの変更が有れば herdr も消さない）。
- `--check`: 前提だけを確かめる。

## しないこと

- 作業中の会話・未コミットの変更や push していない commit の有る会話は、送り直しにも片付けにも使わない（`busy`・`dirty`・`unpushed`）。相手の新しい返事が無い会話もそのまま（`no_news`）。前に送った後に相手の動き（コメント・レビュー・commit・head の変化）が無い PR は、会話を閉じてあっても開き直さない（`no_news`。`--pr N` で名指せば開く）。PR の作業場の外で同じブランチの会話が開いていれば、その PR は飛ばす（`already_open`）。
- シェルではない物（エディタ・dev server・別の会話）が前に居るペインには打ち込まない（`pane_busy`）。起こした Claude Code が信頼やログインの確認の画面で止まったら、`/catchup` を送らずに `blocked` と報告する。
- 依存（`.venv`・`node_modules`）は入れない。試験を走らせる段になってから、その会話の中で入れる。
- 起こした会話の `/catchup` のページを、会話ごとには VS Code の窓に開かない（起こすコマンドの前に `ATTENTION_CATCHUP_OPEN=0` を置く）。全件を送り終えた後に、送った PR のページをまとめて、生きている VS Code の窓にタブで開く（`ATTENTION_CATCHUP_OPEN=0` で dispatch を走らせれば開かない。窓が無ければページの path を報告に出す）。
