---
name: dispatch
description: "自分の番の PR（attention の /whose-turn が並べる物）や issue を枝ごとの作業場（git worktree と herdr）に開き、使用枠に空きのあるアカウントの Claude Code に /catchup を送る。作業ごとの部署（別の作業場の会話。「作業」などの役を持つ）を起こして頼みのファイルを渡すこともできる（--task）。「自分の番を全部開いて」「PR を展開して」「#1234 を開いて catchup して」「issue #1300 を始めて」「この作業を作業に回して」と言われたときに使う。初めては「/works-dispatch:dispatch setup」。"
---

# dispatch

2 つの仕事を、AI を使わないスクリプトでやる。1 つは、自分の番の PR（attention プラグインの `/whose-turn` が「自分の番」に並べる PR）を枝ごとの作業場（git worktree と、herdr〔端末の画面を作業場とペインに分けて Claude Code の会話を並べる道具〕の作業場）で開き、使用枠に空きのあるアカウントの Claude Code に `/catchup` を送ること。もう 1 つは、リポジトリ（会社）に部署（作業ごとの git worktree 1 つと、そこで働く Claude Code の裏の会話 1 つの組）を立て、頼み・納品・本流（origin の既定の枝）に入れることを回すこと。部署に仕事を配るのは窓口（持ち主〔このスキルを使う人〕と話す、長く生きる Claude Code の会話）で、部署の画面を出した herdr のペインを部署の窓と呼ぶ。

## 打ち方（毎回）

このスキルは下のスクリプトを走らせ、出力をそのまま見せる。スクリプトの出した結果を言い換えたり、代わりに判断したりしない。`${CLAUDE_PLUGIN_ROOT}` は、Claude Code がこのプラグインの入ったフォルダのパスを入れる変数である。命令は `python3` でなく、このプラグインの `hooks/run-python.sh` を通して起こす（`python3`・`python`・`py -3` の順に、実際に起きて 3.11 以上の物を選ぶ。Windows の `python3` が Microsoft Store へ誘う代わりの物でも動く）。下の命令の形をそのまま打ち、Python の名前を替えない。

```
bash "${CLAUDE_PLUGIN_ROOT}/hooks/run-python.sh" "${CLAUDE_PLUGIN_ROOT}/dispatch/dispatch.py" <引数>
```

- `setup` はスクリプトの引数ではない。`/works-dispatch:dispatch setup` と呼ばれたら、[references/setup.md](references/setup.md) の「初めて」の手順を上から持ち主と進める。
- PR を開く回（引数なし・`--pr`・`--issue`）と `--land` は、Bash の道具の `run_in_background` で走らせ、終わりの知らせが来てから出力を見せる。PR を開く回は各 PR の `/catchup` が終わるのを待ってから 2 ターン目を送るので数分かかり、`--land` は関門（CI など）を待つ間は戻らない。前景で（`run_in_background` を付けずに）走らせると、Bash の道具の時間の上限で止められ、2 ターン目も報告も出ない。
- `--dry-run`・`--check`・`--clean`・`--init`・`--todo` はすぐ終わり、`--task` は部署の会話が起きて attach するまでで終わり、`--ask`・`--deliver`・`--take`・`--withdraw`・`--first`・`--nudge`・`--note` は相手の作業の終わりを待たないので、前景で走らせてよい。

## 落とし穴

- 部署の会話が打つ `--land` が、Claude Code の自動の権限の判定（auto mode）に止められたら、打ち直さずに納品で知らせ、窓口が `--land <部署の名前>` を打つ。
- 納品の要約の既定の項目「決め手」（結論の根拠にした原典の一句と URL。調べものの役のための項目）が要らない役（コードを直す役など）の部署が、検査を通すために、在りもしない URL や決め手の根拠でない URL を要約に書き足してはいけない（要らない役は、会社の形〔`.claude/company.toml`〕のその役の `deliver` から決め手を外す）。
- 頼んだ後で頼みを変える・足す・取り下げるときは、部署の窓に直に打たず `--note` で足す。持ち主に部署の窓へ打たせない。
- 部署の会話を止める前に、[references/clean.md](references/clean.md) の「部署の会話を止める」を読む（attach の画面を開いたまま `claude stop` を打つと、attach が会話を起こし直す）。

## 何をいつ読むか

頼まれた事に当たる別ファイルを 1〜2 本だけ読んでから打つ。別ファイルの中の「」の名前（例「役の中身と起こし方」）は、ほかの別ファイルの節を指す。その節が要るときは、下の並びからそのファイルを開く。

- `setup`・`--check`・`--init`・`--init-company`、「前提」「初めて」「アカウントの書き方」「herdr の見た目を整える」: [references/setup.md](references/setup.md)
- 自分の番の PR を開く（引数なし・`--dry-run`・`--pr N`・`--issue N`・`--no-second`）と「しないこと」: [references/pr.md](references/pr.md)
- 片付ける `--clean`・部署の会話を止める・都度の部署の終わり `--done` と畳む `--retire`: [references/clean.md](references/clean.md)
- 部署を立てる `--task`・会社のツリー図 `--tree`・頼まれたときだけ立てる受け持ち（`standing = false`）・会社の形をどこから読むか（origin の既定の枝。変えた会社の形は既定の枝に入れてから効く）: [references/department.md](references/department.md)
- 会社の形（`.claude/company.toml`）の役 `[[roles]]`・受け持ちごとの model と effort・`gh_user`・`fresh`・`settings`・`default_role`・`desk_role`・`former_names`・`machine`（「役の中身と起こし方」）: [references/roles.md](references/roles.md)
- herdr の表示を付け直す `--sync`・組み直す `--reorg` と `--desk`・手で会話を立てるときにアカウントを 1 つ選ぶ `accounts.py --pick`: [references/reorg.md](references/reorg.md)
- ほかのアカウントで起こし直す `--move`（使用上限や会社の形の起動の設定が替わったときの自動の起こし直しも）: [references/move.md](references/move.md)
- 頼む `--ask`（宛先・待ち受け・順番待ち・`--take`・`--withdraw`・`--first`・`--nudge`・`--note`・`--forward` と、回した先の結果を頼み元へ返す `--deliver --for`・頼みの一覧 `--todo`・落ちた部署の会話・受付箱）: [references/ask.md](references/ask.md)
- 納品する `--deliver`（要約の項目・納品の検査 `deliver_check`）・答え待ち `--wait`・区切り `--rest`・止める前の差し戻し: [references/deliver.md](references/deliver.md)
- 機械窓口 `--call` と合図（`[[roles.tools]]`）: [references/call.md](references/call.md)
- 受け持ちを起こす `--start`・`--due`（`[skills.start]`）: [references/start.md](references/start.md)
- 本流に入れる `--land 部署`（`[land]`・載せ直し・版上げ・書き換えの取り合いの関門・`[[land.after]]`）: [references/land.md](references/land.md)
