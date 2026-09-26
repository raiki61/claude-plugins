---
name: works
description: 人の修正依頼を works の生産ライン darkfactory（Archon の上で 判定 → 修正 → テスト → 人の承認 → 修正差分の審査 の順に流す）に回す。「darkfactory に回して」「works で直して」と言われたときに使う。依頼の JSON の書き方・起動の 1 行・人の関所で何を見てどう答えるかだけを書く。誤字・コメント・文言の直しは回さない（手で直す方が早い）。起動・待つ・承認・再開の一般は Archon の archon-cli スキルに任せる。
---

# works

darkfactory に回すのは、原因を調べて直し、テストで確かめる必要のある不具合の依頼。誤字・コメント・文言の直しは回さず手で直す。

起動・待つ・承認・再開の一般（run-id の探し方、`wait`、`--json` を付けたときの二段の承認など）は Archon の `archon-cli` スキル（Archon のリポジトリの `.claude/skills/archon-cli/`）に任せる。ここには darkfactory に固有の事だけを書く。

## 1. 依頼の JSON を書く

findings（指摘）の JSON の配列を 1 つのファイルにする。置き場所は対象リポジトリの外でよい（下の 2 節のとおり、起動では絶対パスで渡す）。

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
archon workflow run raiki61/works:darkfactory --input request=<依頼の JSON の絶対パス> --input test_cmd="<テストのコマンド>"
```

- `request` は依頼の JSON の**絶対パス**。`test_cmd` は修正の後に回すテストのコマンド（例: `python3 -m unittest -q`）。
- どこが直されるか: Archon（v0.11.1）は run ごとに worktree を切り、既定ではその元を **remote の既定の枝**（`origin/<既定の枝>`）にする。今いる枝でも、手元の commit していない変更でもない。だから依頼を対象の中に置いて commit していなければ、run の worktree には無い（相対パスは run の worktree の根から読まれる）。remote の無いリポジトリでは worktree を切れず、run が始まらない。
  - 元を替える: `--from <枝や ref>`（例: `--from origin/my-branch`。remote に在る物を渡す）。worktree の枝の名前を決める: `--branch <名>`。
  - 今の作業ツリーでそのまま回す: `--no-worktree`（隔離しない。`--branch`・`--from` とは一緒に使えない）。
- 修正は commit されない。Archon の run ごとの worktree の中に、commit していない変更として残る。場所は `archon workflow runs --json` の、その run の `working_path`。
- 人の関所を持つラインなので `--detach` は使えない。Claude Code から回すときは、前景のコマンドをハーネスの背景タスクとして回す。
- works の開発中（`works/dev/archon.sh` で project pack として回すとき）は、ラインの名前は `darkfactory` だけ。

## 3. 人の関所で見て答える

テストの後で run が止まる。関所の文面に次の 4 つが出る。

1. 判定の一手（`one_shot`）: 判定役が選んだ最も効く一手。修正がその一手に沿っているかを見る。
2. 判定のファイル（`judgment.json` のパス）: 単位の一覧と、一手で閉じると見込む単位（`one_shot_closes`）。
3. テストが緑か（`true` が緑・`false` が赤）。
4. テストのログのパス。

修正の差分そのものは、Archon の run ごとの worktree にある（2 節の `working_path`。`git -C <working_path> diff` で見る）。

答え方:

- 進める: `archon workflow approve <run-id>` → 修正差分の審査へ進む。
- 止める: `archon workflow reject <run-id> "<理由>"` → 審査へ進まない。理由は決まりとして書く（Archon は空でも受け付け、空なら `Rejected` を入れる）。

判定が直す物を 1 つも残さなかった（依頼の件が再現しない・直す義務の無い単位だけ）ときは、修正・テスト・関所・審査を飛ばして run が成功で終わる（結末は `no_fix_needed`）。関所では止まらない。

## 4. run の後に見る物

run の出口（最後の節 `finish` の出力）に、見るファイルのパスが載る。

- `outcome`: `fixed`（修正から審査まで回った）か `no_fix_needed`（直す物が無い判定で終わった）。
- `judgment_file`: 判定（単位・ラベル・一手）。
- `review_file`: 修正差分の審査の返答（見つけた穴 `faces` と、塞がったかの確かめ `checks`）。`fixed` のときだけ。
- `diff_file`: 審査した修正の差分。`fixed` のときだけ。
- 修正そのもの: Archon の run ごとの worktree（`archon workflow runs --json` の `working_path`）。commit していないので、取り込むかは人が決める。

## 5. 止めて続ける

- 止める: 前景の run を Ctrl-C（端末が SIGINT を送る）で止める。人の関所を持つラインは外から `cancel` できない。
- 続ける: `archon workflow resume <run-id>` で、済んだ節の続きから回る。
- 受け付けの出し直しが上限（3 回）を超えたときも run は失敗で止まる。原因を直してから同じく `resume` で続ける。
