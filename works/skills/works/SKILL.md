---
name: works
description: 人の修正依頼を works の生産ライン darkfactory（Archon の上で 判定 → 修正 → テスト → 人の承認 → 修正差分の審査 の順に流す）に回す。「darkfactory に回して」「works で直して」と言われたときに使う。依頼の JSON の書き方・起動の 1 行・人の関所で何を見てどう答えるかだけを書く。誤字・コメント・文言の直しは回さない（手で直す方が早い）。起動・待つ・承認・再開の一般は Archon の archon-cli スキルに任せる。
---

# works

darkfactory に回すのは、原因を調べて直し、テストで確かめる必要のある不具合の依頼。誤字・コメント・文言の直しは回さず手で直す。

起動・待つ・承認・再開の一般（run-id の探し方、`wait`、`--json` を付けたときの二段の承認など）は Archon の `archon-cli` スキル（Archon のリポジトリの `.claude/skills/archon-cli/`）に任せる。ここには darkfactory に固有の事だけを書く。

## 1. 依頼の JSON を書く

findings（指摘）の JSON の配列を 1 つのファイルにし、対象リポジトリの中に置く。

```json
[
  {
    "where": "src/app/parse.py:42",
    "text": "空の行で IndexError が出る",
    "mechanism": "split() の結果が空のとき [0] を読む",
    "measured": "空行を 1 つ含む入力で再現した",
    "false_positive_if": "呼び出し元が空行を必ず除いているなら誤り"
  }
]
```

- 必須: `where`（どこ）・`text`（何が悪いか）
- 任意: `mechanism`（なぜ起きるか）・`measured`（何で確かめたか）・`false_positive_if`（どうなら誤りか）
- これ以外の欄は拒まれる。型の確かめはラインの入口で、AI を起こす前に止まる。

## 2. 起動する

対象リポジトリの直下で、前景で打つ。

```
archon workflow run raiki61/works:darkfactory --input request=<依頼の JSON のパス> --input test_cmd="<テストのコマンド>"
```

- `request` は対象リポジトリの中のパス、`test_cmd` は修正の後に回すテストのコマンド（例: `python3 -m unittest -q`）。
- 人の関所を持つラインなので `--detach` は使えない。Claude Code から回すときは、前景のコマンドをハーネスの背景タスクとして回す。
- works の開発中（`works/dev/archon.sh` で project pack として回すとき）は、ラインの名前は `darkfactory` だけ。

## 3. 人の関所で見て答える

テストの後で run が止まる。見る物は 2 つ。

1. テストの結果: 緑か赤かと、そのログ。
2. 判定の `one_shot`: 判定役が選んだ最も効く一手と、それで閉じると見込む単位（`one_shot_closes`）。修正がその一手に沿っているかを見る。

答え方:

- 進める: `archon workflow approve <run-id>` → 修正差分の審査へ進む。
- 止める: `archon workflow reject <run-id> "<理由>"` → 審査へ進まない。理由は必須。

## 4. 止めて続ける

- 止める: 前景の run を Ctrl-C（SIGTERM）で止める。人の関所を持つラインは外から `cancel` できない。
- 続ける: `archon workflow resume <run-id>` で、済んだ節の続きから回る。
- 受け付けの出し直しが上限（3 回）を超えたときも run は失敗で止まる。原因を直してから同じく `resume` で続ける。
