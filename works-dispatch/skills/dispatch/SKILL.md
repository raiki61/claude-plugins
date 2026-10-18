---
name: dispatch
description: "自分の番の PR（attention の /whose-turn が並べる物）や issue をブランチごとの作業場（git worktree と herdr）に開き、使用枠に空きのあるアカウントの Claude Code に /catchup を送る。作業ごとの部署（別の作業場の会話。「作業」などの役を持つ）を起動して頼みのファイルを渡すこともできる（--task）。「自分の番を全部開いて」「PR を展開して」「#1234 を開いて catchup して」「issue #1300 を始めて」「この作業を「作業」に回して」と言われたときに使う。初めては「/works-dispatch:dispatch setup」。"
---

# dispatch

このファイル（SKILL.md）は、このスキルを呼ばれた Claude Code の会話が読む指示。「自分」と「持ち主」は、このスキルを使う人（この会話に打つ人）を指す。急ぎの操作は無い。下の「打ち方」のとおりにスクリプトを打ち、出力を持ち主に見せる。

2 つの仕事を、AI を使わないスクリプトでやる。1 つは、自分の番の PR を作業場で開き、使用枠に空きのあるアカウントの Claude Code に `/catchup` を送ること。もう 1 つは、会社に部署を立て、頼み・納品・メインブランチ（origin の既定のブランチ）に入れることを回すこと。部署を立てる引数が `--task`、部署の成果をメインブランチに入れる引数が `--land`。

言葉: attention は `/whose-turn`（自分の番の PR を並べる）と `/catchup`（前に触ってから何が起きたかを出す）を持つ、同じリポジトリのプラグイン。herdr は端末を作業場とペインに分け、中の Claude Code の会話を外から操作するツール。git worktree は 1 つのリポジトリから切る、ブランチごとの別の作業フォルダ。作業場は git worktree と、それを開いた herdr の作業場の組。会社は部署を置いて回すリポジトリで、会社の形はその設定ファイル `.claude/company.toml`。部署は作業ごとの git worktree と、そこで働く裏の会話（`claude --bg` で起動した、画面を持たない会話）の組で、その会話を映す herdr のペインが部署の窓。窓口は持ち主と話し、部署に仕事を配る長く生きる会話。役は部署と窓口の会話の決まり（会社の形に書く）、受け持ちは部署ごとの仕事の範囲で、会社の形に 1 つずつ書き、その名前の部署を立てる（「受け持ちを立てる・起動する」は、その受け持ちの部署を立てること）。頼みは部署に渡す仕事の文、納品は部署が結果の要約を頼み元へ返すこと。受付箱は頼みと納品を置くフォルダ（`.git/company/inbox/`）。待ち受けは、会話のターンの終わりにフックが受付箱を見て会話を再開させる処理。使用枠はアカウントごとの Claude の使用量の上限。ほかの言葉は [references/setup.md](references/setup.md) の「言葉」。

## 打ち方（毎回）

このスキルは下のスクリプトを走らせ、出力をそのまま見せる。スクリプトの出した結果を言い換えたり、代わりに判断したりしない。`${CLAUDE_PLUGIN_ROOT}` は、Claude Code がこのプラグインの入ったフォルダのパス（例 `~/.claude/plugins/cache/raiki61/works-dispatch/<版>/`）を入れる変数で、自分で置き換えずにそのまま打つ。どの引数を打つかは、頼まれた事から読む別ファイルを引く対応の表（下の「何をいつ読むか」の並び。1 行が 1 つの別ファイルで、行の頭に引数と頼まれる事を並べる）で行を選び、その別ファイルを読んで決める。コマンドは `python3` でなく、このプラグインの `hooks/run-python.sh` を通して起動する（`python3`・`python`・`py -3` の順に、実際に起きて 3.11 以上の物を選ぶ。Windows の `python3` が Microsoft Store へ誘う代わりの物でも動く）。下のコマンドの形をそのまま打ち、Python の名前を替えない。

```
bash "${CLAUDE_PLUGIN_ROOT}/hooks/run-python.sh" "${CLAUDE_PLUGIN_ROOT}/dispatch/dispatch.py" <引数>
```

- `setup` はスクリプトの引数ではない。`/works-dispatch:dispatch setup` と呼ばれたら、[references/setup.md](references/setup.md) の「初めて」の手順を上から持ち主と進める。
- PR を開く回（引数なし・`--pr`・`--issue`）と `--land` は、Bash のツールの `run_in_background` で走らせ、終わりの知らせが来てから出力を見せる。PR を開く回は各 PR の `/catchup` が終わるのを待ってから 2 ターン目を送るので数分かかり、`--land` はゲート（CI など）を待つ間は戻らない。前景で（`run_in_background` を付けずに）走らせると、Bash のツールの時間の上限で止められ、2 ターン目も報告も出ない。
- `--dry-run`・`--check`・`--clean`・`--init`・`--todo` はすぐ終わり、`--task` は部署の会話が起きて attach するまでで終わり、`--ask`・`--deliver`・`--take`・`--withdraw`・`--first`・`--nudge`・`--note` は相手の作業の終わりを待たないので、前景で走らせてよい。

## 落とし穴

- 部署の会話が打つ `--land` が、Claude Code の自動の権限の判定（auto mode）に止められたら、打ち直さずに納品で知らせ、窓口が `--land <部署の名前>` を打つ。
- 納品の要約の既定の項目「決め手」（結論の根拠にした原典の一句と URL。調べものの役のための項目）が要らない役（コードを直す役など）の部署が、検査を通すために、在りもしない URL や決め手の根拠でない URL を要約に書き足してはいけない（要らない役は、会社の形〔`.claude/company.toml`〕のその役の `deliver` から決め手を外す）。
- 頼んだ後で頼みを変える・足す・取り下げるときは、部署の窓に直に打たず `--note` で足す（取り下げも、その旨を `--note` で足す。部署がまだ受けていない順番待ちの頼みを取り除くのは `--withdraw`）。持ち主に部署の窓へ打たせない。
- 部署の会話を止める前に、[references/clean.md](references/clean.md) の「部署の会話を止める」を読む（attach の画面を開いたまま `claude stop` を打つと、attach が会話を再開させる）。

## 何をいつ読むか

手順は 3 つ。1. 下の並びから、頼まれた事（例「PR を開いて」なら引数なしの行、「部署を立てて」なら `--task` の行、「この作業を「作業」に回して」なら `--ask` の行。「作業」は一度きりの部署の役の名前で、`--ask <会社>/作業` で頼む）に当たる行を 1〜2 本選ぶ。2. その行の別ファイルを読む。3. 別ファイルに書いてあるコマンドの形で打つ。別ファイルの中の「」の名前（例「役の中身と起動方法」）は、ほかの別ファイルのセクションを指す。そのセクションが要るときは、下の並びからそのファイルを開く。

- `setup`・`--check`・`--init`・`--init-company`、「前提」「初めて」「アカウントの書き方」「herdr の見た目を整える」: [references/setup.md](references/setup.md)
- 自分の番の PR を開く（引数なし・`--dry-run`・`--pr N`・`--issue N`・`--no-second`）と「しないこと」: [references/pr.md](references/pr.md)
- 片付ける `--clean`・部署の会話を止める・都度の部署の終わり `--done` と畳む `--retire`: [references/clean.md](references/clean.md)
- 部署を立てる `--task`・会社のツリー図 `--tree`・頼まれたときだけ立てる受け持ち（`standing = false`）・会社の形をどこから読むか（origin の既定のブランチ。変えた会社の形は既定のブランチに入れてから効く）: [references/department.md](references/department.md)
- 会社の形（`.claude/company.toml`）の役 `[[roles]]`・受け持ちごとの model と effort・`gh_user`・`fresh`・`settings`・`default_role`・`desk_role`・`former_names`・`machine`（「役の中身と起動方法」）: [references/roles.md](references/roles.md)
- herdr の表示を付け直す `--sync`・組み直す `--reorg` と `--desk`・手で会話を立てるときにアカウントを 1 つ選ぶ `accounts.py --pick`（`dispatch.py` と同じフォルダの `nodes/accounts.py`。打ち方は別ファイルに在る）: [references/reorg.md](references/reorg.md)
- ほかのアカウントで起動し直す `--move`（使用上限や会社の形の起動の設定が替わったときの自動の起動し直しも）: [references/move.md](references/move.md)
- 頼む `--ask`（宛先・待ち受け・順番待ち・`--take`・`--withdraw`・`--first`・`--nudge`・`--note`・`--forward` と、回した先の結果を頼み元へ返す `--deliver --for`・頼みの一覧 `--todo`・落ちた部署の会話・受付箱）: [references/ask.md](references/ask.md)
- 納品する `--deliver`（要約の項目・納品の検査 `deliver_check`）・答え待ち `--wait`・区切り `--rest`・止める前の差し戻し: [references/deliver.md](references/deliver.md)
- 機械窓口 `--call` と合図（`[[roles.tools]]`）: [references/call.md](references/call.md)
- 受け持ちを起動する `--start`・`--due`（`[skills.start]`）: [references/start.md](references/start.md)
- メインブランチに入れる `--land 部署`（`[land]`・リベース・版上げ・書き換えの取り合いのゲート・`[[land.after]]`）: [references/land.md](references/land.md)
