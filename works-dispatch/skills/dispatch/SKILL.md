---
name: dispatch
description: 自分の番の PR（attention プラグインの /whose-turn が「自分の番」に並べるもの）を、PR ごとの作業場（git の clone と herdr の作業場）に開き、使用率に余裕のあるアカウントの Claude Code を起こして、/catchup（その PR のどこで止まっていたかを出す attention の命令）と、設定のファイルに書いた 2 ターン目の文を送る。「自分の番を全部開いて」「PR を展開して」「#1234 を開いて catchup して」と言われたときに使う。初めて使う人は「/works-dispatch:dispatch setup」。
---

# dispatch

自分の番の PR を、PR ごとの作業場で開くところまでを機械でやる。「自分の番の PR」は、attention プラグインの `/whose-turn` が「自分の番」の節に並べる PR（直す番の自分の PR と、レビューする番の PR）である。

1. PR ごとに作業場を用意する。代表の clone から `<名前>-pr-<番号>` の clone を作り、同じ名前の herdr の作業場を開く。どちらも既にあれば使い直す。
2. 週の使用率のリセットが近いアカウント（使用率が 95% を超えるものは外す）で、Claude Code を起こす。
3. attention の `/catchup <番号>` を送る。これは、その PR で前回自分が触ってから何が起きたかを出す命令である。それが終わったら、設定のファイルに書いた 2 ターン目の文を送る。

AI は使わない。このスキルは下のスクリプトを走らせ、出力をそのまま見せるだけで、判断も言い換えもしない。

```
python3 "${CLAUDE_PLUGIN_ROOT}/dispatch/dispatch.py" <引数>
```

## 前提（`--check` が全部確かめる）

- [herdr](https://herdr.dev)（端末を作業場ごとに分けて、中の AI の会話を外から操作できる道具）が動いている。
- Claude Code が、開いている会話を読む `claude agents --json` を持つ版である。
- 使う各アカウントに、attention プラグインがアカウント全体（user）に入っている。
- gh でそのリポジトリを読める。普段の gh のアカウントで読めなければ、設定の `gh_user` に読めるアカウントを書く。
- リポジトリごとに代表の clone がある。各アカウントで一度そこで Claude Code を起こし、フォルダを信頼しておく。信頼していないと、PR ごとの作業場で毎回、信頼の確認が出る。

## 初めて: `/works-dispatch:dispatch setup`

1. 今いるリポジトリについて、設定の下書きを書く。`--repo` は origin の `OWNER/NAME`、`--source` は今いる clone の根にする。

   ```
   python3 "${CLAUDE_PLUGIN_ROOT}/dispatch/dispatch.py" --init --repo OWNER/NAME --source <代表の clone>
   ```

2. 書かれた設定（既定は `~/.config/works-dispatch/dispatch.toml`）を、利用者が埋める。埋めるのは、2 ターン目の文のファイルと、アカウントを切り替える人だけ `accounts` である。
3. `--check` を、足りない物が出なくなるまで走らせる。

## 使い方: `/works-dispatch:dispatch <引数>`

- 引数なし: 自分の番の PR を全部開く。
- `--dry-run`: 何も起こさず、どの PR をどのアカウント・どの作業場で開くかだけを出す。
- `--pr N`: 指した番号の PR だけを開く。複数なら `--pr` を重ねる。止めている実装や、見に行くだけの PR に使う。
- `--no-second`: `/catchup` だけで止め、2 ターン目の文を送らない。
- `--clean`: 消してよい作業場を並べる。消してよいのは、PR が閉じていて、会話が無く、push していない変更も無いものだけ。`--clean --apply` で本当に消す。
- `--check`: 前提だけを確かめる。

## しないこと

- 開いている会話は閉じない。同じリポジトリとブランチの会話が開いていれば、その PR は飛ばす。
- 依存（`.venv`・`node_modules`）は入れない。試験を走らせる段になってから、その会話の中で入れる。
