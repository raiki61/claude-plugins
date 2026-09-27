---
name: works
description: 人の修正依頼を works の生産ライン darkfactory（Archon の上で 前提の実測 → 目的の文 → 素材集め → 判定 → 修正案と事前審査 → 修正 → 差分の審査 → 手直し → 最後のテスト → 人の最後の関所 → 独立の目 → 報告 の順に流す）に、今いるリポジトリを対象にして回す。「darkfactory に回して」「works で直して」と言われたときに使う。入れ方・依頼の JSON の書き方・起動の 1 行（works/dev/use.sh）・人の関所での答え方・報告と差分の取り込み方だけを書く。誤字・コメント・文言の直しは回さない（手で直す方が早い）。
---

# works

darkfactory に回すのは、原因を調べて直し、テストで確かめる必要のある不具合の依頼。誤字・コメント・文言の直しは回さず手で直す。

流れ: 入れる（1 回だけ）→ 依頼の JSON を書く → 対象リポジトリで起動する → 関所で答える → 報告を読む → 差分を対象へ取り込む。
回すと費用が掛かる（AI を起こすのは 2 節の `start` と、関所で進めた後だけ）。

## 0. 入れる（1 回だけ）

要る物: macOS（Apple silicon。Archon は固定した版の darwin-arm64 の実行ファイル）・git・uv・gh（初回に Archon の実行ファイルを GitHub の release から落とす）・Claude Code の `claude`・認証（`claude setup-token` で作るトークンを `CLAUDE_CODE_OAUTH_TOKEN` に置くか、それを入れた macOS の keychain の項目名を `WORKS_KEYCHAIN_ITEM` に置く）。

1. works のリポジトリを clone し、場所を `WORKS_REPO` に置く。起動の殻と pack はこの clone から使う（Claude Code のプラグインの置き場の写しからは起動できない。隔離した設定に入れる coldwrite をリポジトリから写すため）。

   ```
   git clone https://github.com/raiki61/claude-plugins "$HOME/src/claude-plugins"
   export WORKS_REPO="$HOME/src/claude-plugins"
   ```

2. このスキルを Claude Code に入れる。

   ```
   claude plugin marketplace add raiki61/claude-plugins   # 登録済みなら: claude plugin marketplace update raiki61
   claude plugin install works@raiki61
   ```

   marketplace の works の行が GitHub に届く前は、その回だけ `claude --plugin-dir "$WORKS_REPO/works"` で読める。

3. 対象リポジトリで、AI を起こさずに確かめる（費用なし）。`darkfactory  ok` が出れば入っている。

   ```
   sh "$WORKS_REPO/works/dev/use.sh" check <対象リポジトリの根>
   ```

`archon plugin install` で pack を入れて Archon を直に打つ形は、まだ使わない。AI の役が利用者の本物の `~/.claude`（CLAUDE.md・hooks・プラグイン）を読んでしまうため。`use.sh` は Archon を隔離した家で起こし、役には選んだ物だけの設定を読ませる。

## 1. 依頼の JSON を書く

findings（指摘）の JSON の配列を 1 つのファイルにする。置き場所はどこでもよい（起動のときに写して渡す）。

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

前景で打つ。

```
sh "$WORKS_REPO/works/dev/use.sh" start <対象リポジトリの根> <依頼の JSON> "<test_cmd>" [<tdd_suite>]
```

- 対象の条件: commit していない変更・未追跡のファイルが無い（run は対象の今の HEAD から切り、差分はここへ当てる）。remote の `origin` が在る（Archon が worktree を切る前に fetch する）。`/private/tmp` の下でない。どれかに当たると、何もせずに 1 行で止まる。
- `test_cmd`: 修正の前と最後に回すテストのコマンド（例: `python3 -m unittest -q`・`uv run pytest -q`）。空なら対象の `.review-checks.json` の宣言を回し、宣言も無ければ CI の任せ先の役が走らせ方を探す。
- `tdd_suite`（省ける）: JUnit XML の書き先を第 1 引数に受ける実行ファイル（対象の根から走る）。在れば修正の段で単位ごとの TDD の輪を回す。省くと、`test_cmd` が pytest の 1 コマンドなら殻がそれに `--junitxml` を足す実行器を書いて渡し、そうでなければ輪を飛ばして直に直す（どちらにしたかを 1 行出す）。
- 最後の関所は既定でいつも開く。要る時だけにするなら `WORKS_USE_FINAL_GATE=when_needed` を前に付ける。
- 殻がすること: pack を利用の家（`WORKS_USE_HOME`。既定は `~/.local/state/works/use`）に置き、Archon をその家に隔離して起こす。AI の役はその家に組んだ選んだ物だけの Claude の設定を読み、あなたの `~/.claude` は読まない。対象の作業ツリーには何も書かない。
- Archon がすること: 対象の `.git` に run の worktree と枝を足す（worktree は利用の家の下）。起動の前に `origin` を fetch し、対象で今いる枝が既定の枝で `origin` より遅れていれば早送りする。
- 最初に起動の関所（`launch`）で止まって戻り、run id・状態・run の worktree・次に打つ行（進める・答える・止める・続ける）・報告の置き場を出す。

## 3. 人の関所で見て答える

関所は 3 つ。どれも文言に「全文のファイルのパス」が載るので、そのファイルを読んで答える。打つ行は殻が出した物をそのまま使う（`use.sh show <対象>` でいつでも出し直せる）。

1. 起動の関所 `launch`: 「進める」の行（`… workflow approve <run-id>`）で始まる。
2. 修正の前の関所 `policy-gate`（要る時だけ）: 修正案が能力を狭める・事前審査が後退や方針の穴を挙げた・方針の文書が変わった時に開く。全文は盤面の `r1/gate.md`。
   - 通す: 「答えて進める」の行（`respond <run-id> continue "<通す範囲と条件>"`）。一言は修正役にファイルで届く。`approve` も通す。
   - 止める: 「関所で止める」の行（`respond <run-id> stop "<理由>"`）。止めても報告は出る。
3. 最後の関所 `final-gate`: 最後のテストの緑赤・ログ・差分の置き場・残った異議が全文 `r1/final-gate.md` に在る。`continue` でも `stop` でも報告へ進む。
3. 最後の関所 `final-gate`（`final_gate: always` ならいつも）の続き:
   - `continue` なら独立の目 R1〜R4 が回ってから報告へ。`stop` なら目は回さずに報告へ。
   - 独立の目の R4 が人に聞く物（消えた能力・方針とのぶつかり）を挙げたら、run は止めずに報告へ進み、結末は `needs_human`。問いは報告の冒頭と次の run の依頼の下書きに載る。

関所で待っている run は `cancel` でなく `respond … stop` で止める。判定が直す物を 1 つも残さなかったときは、修正の段を飛ばして報告へ行く（結末は `no_fix_needed`）。

## 4. 報告を読み、差分を取り込む

```
sh "$WORKS_REPO/works/dev/use.sh" show <対象リポジトリの根>
```

一番新しい run について、状態・報告の置き場・差分のファイルを出す。

- 報告: 盤面の `report.md`（冒頭に決めてほしいこと・入口・止めた理由・読んだ証拠・置き場）と `next-request.json`（次の run に渡す依頼の下書き）。
- 結末（run の出口の `outcome`）: `fixed`・`no_fix_needed`・`stopped_by_human`（関所で止めた）・`stopped_by_request`（止め札）・`stopped_by_line`（機械が止めた）・`needs_human`（盤面が人に聞いたまま）・`record_invalid`（周の記録が検証器を通らない）。
- 差分: run の worktree と周の頭の版の差（手直しと未追跡も入る）を、利用の家の `diffs/run-<id>.diff` に書く。修正は commit されない。取り込むかは人が決め、殻が出す `git -C <対象> apply <diff>` の行で当ててから、手元でテストを回して commit する。
- 片付け: 取り込んだ後、run の worktree と枝は `git -C <対象> worktree remove <worktree>` と `git -C <対象> branch -D <枝>` で消せる（Archon 自身の片付けは `complete <枝>`）。
- `report_file`: 最後の報告。盤面が報告の節を出した run（人か止め札で止めた・収束した）では AI が書いて初見の読み手が確かめた `report-ai.md`（最後に機械の報告が字のまま付く）、そうでなければ機械の `report.md`。機械の報告はいつも `machine_report_file`。

## 5. 止めて続ける

- 止め札: 対象の根で `WORKS_DEV_HOME="${WORKS_USE_HOME:-$HOME/.local/state/works/use}" sh "$WORKS_REPO/works/dev/stop.sh" <run-id> "<理由>"`。走っている AI の節は最後まで走り、次の境の節で止まる（報告は出る）。
- 前景の run は Ctrl-C で止まる。関所で待っている run は `respond … stop`。
- 続ける: 殻が出した「続ける」の行（`resume <run-id>`）で、済んだ節の続きから回る。
- ブロックの中の出し直しが上限（3 回）を超えたときは run が失敗で止まり、報告の節まで届かない。対象の根で、止め札と同じ `WORKS_DEV_HOME=…` を前に付けて `sh "$WORKS_REPO/works/dev/report.sh" <run-id>` を打つと、盤面から報告を組む（結末 `interrupted`）。

works 自身の直しは、この殻でなく `works/dev/dogfood.sh` で回す（README の「自分食い」）。
