---
name: works
description: 人の修正依頼を works の生産ライン darkfactory（Archon の上で 判定 → 修正案と事前審査 → 修正 → 差分の審査 → 手直し → 最後のテスト → 人の最後の関所 → 独立の目 → 報告 の順に流す）に回す。「darkfactory に回して」「works で直して」と言われたときに使う。依頼の JSON の書き方・起動の 1 行・人の関所で何を見てどう答えるかだけを書く。誤字・コメント・文言の直しは回さない（手で直す方が早い）。起動・待つ・承認・再開の一般は Archon の archon-cli スキルに任せる。
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

- `request` は依頼の JSON の**絶対パス**。`test_cmd` は最後のテスト（と修正の前のテスト）のコマンド（例: `python3 -m unittest -q`）。空なら対象の `.review-checks.json` の宣言を回し、宣言も無ければ CI の任せ先の役が走らせ方を探す。
- ほかの入力（どれも省ける）: `final_gate`（`always` 既定・`when_needed`＝最後のテストが緑でない・盤面が人に聞いている・異議が残った時だけ最後の関所を開く）・`adapter`（空は Claude の包みを通した run だけを受ける。包み無しで回すなら `optional`。報告に出る）・`tdd_suite`（JUnit XML を書くテストの実行器。在れば修正の段で単位ごとの TDD の輪を回す）・`policy_md`・`gates`・`thickness`（標準だけ）。
- どこが直されるか: Archon（v0.11.1）は run ごとに worktree を切り、既定ではその元を **remote の既定の枝**（`origin/<既定の枝>`）にする。今いる枝でも、手元の commit していない変更でもない。だから依頼を対象の中に置いて commit していなければ、run の worktree には無い（相対パスは run の worktree の根から読まれる）。remote の無いリポジトリでは worktree を切れず、run が始まらない。
  - 元を替える: `--from <枝や ref>`（例: `--from origin/my-branch`。remote に在る物を渡す）。worktree の枝の名前を決める: `--branch <名>`。
  - 今の作業ツリーでそのまま回す: `--no-worktree`（隔離しない。`--branch`・`--from` とは一緒に使えない）。
- 修正は commit されない。Archon の run ごとの worktree の中に、commit していない変更として残る。場所は `archon workflow runs --json` の、その run の `working_path`。
- 最初に起動の関所（`launch`）で止まる。`archon workflow approve <run-id>` で越える（`--detach` を付けると背景で続き、`archon workflow cancel <run-id>` で木ごと止められる）。
- works の開発中（`works/dev/archon.sh` で project pack として回すとき）は、ラインの名前は `darkfactory` だけ。AI の役は、開発の殻が組む選んだ物だけの Claude の設定（`dev/toolset.py`）を読む。

## 3. 人の関所で見て答える

関所は 3 つ。どれも文言に「全文のファイルのパス」が載るので、そのファイルを読んで答える。

1. 起動の関所 `launch`: `archon workflow approve <run-id>` で始まる。
2. 修正の前の関所 `policy-gate`（要る時だけ）: 修正案が能力を狭める・事前審査が後退や方針の穴を挙げた・方針の文書が変わった時に開く。全文は盤面の `r1/gate.md`。
   - 通す: `archon workflow respond <run-id> continue "<通す範囲と条件>"`（一言は修正役にファイルで届く）。`approve` も通す。
   - 止める: `archon workflow respond <run-id> stop "<理由>"`（`reject --reason` も止める）。止めても報告は出る。
3. 最後の関所 `final-gate`（`final_gate: always` ならいつも）: 最後のテストの緑赤・ログ・差分の置き場・残った異議が全文 `r1/final-gate.md` に在る。
   - 進める: `archon workflow respond <run-id> continue "<一言>"`（独立の目 R1〜R4 が回ってから報告へ）。止める: `stop "<理由>"`（目は回さずに報告へ）。
   - 独立の目の R4 が人に聞く物（消えた能力・方針とのぶつかり）を挙げたら、run は止めずに報告へ進み、結末は `needs_human`。問いは報告の冒頭と次の run の依頼の下書きに載る。

修正の差分そのものは、Archon の run ごとの worktree にある（2 節の `working_path`。`git -C <working_path> diff` で見る）。
関所で待っている run は `cancel` でなく `respond … stop` で止める。

判定が直す物を 1 つも残さなかった（依頼の件が再現しない・直す義務の無い単位だけ）ときは、修正案・修正・審査・手直しを飛ばし、最後のテストで周を締めて報告へ行く（結末は `no_fix_needed`）。

## 4. run の後に見る物

run の出口（最後の節 `report` の出力）に、見るファイルのパスが載る。

- `outcome`: `fixed`・`no_fix_needed`・`stopped_by_human`（関所で止めた）・`stopped_by_request`（止め札 `dev/stop.sh`）・`stopped_by_line`（機械が止めた）・`needs_human`（盤面が人に聞いたまま）・`record_invalid`（周の記録が検証器を通らない）。
- `report_file`: 機械が組む短い報告（冒頭に決めてほしいこと・入口・止めた理由・読んだ証拠・置き場）。`next_request_file`: 次の run に渡す依頼の下書き（残った穴・赤）。
- `judgment_file`・`review_file`・`diff_file`・`faces`: 1 本目と同じ欄（判定・差分の審査の返答・審査した差分・穴の数）。
- 修正そのもの: Archon の run ごとの worktree（`archon workflow runs --json` の `working_path`）。commit していないので、取り込むかは人が決める。

## 5. 止めて続ける

- 止め札: `sh works/dev/stop.sh <run-id> "<理由>"`。走っている AI の節は最後まで走り、次の境の節で止まる（報告は出る）。
- 前景の run は Ctrl-C（端末が SIGINT を送る）で止まる。関所で待っている run は `respond … stop`。
- 続ける: `archon workflow resume <run-id>` で、済んだ節の続きから回る。
- ブロックの中の出し直しが上限（3 回）を超えたときは run が失敗で止まり、報告の節まで届かない。`dev/report.sh` で盤面から報告を組む（結末 `interrupted`）。
