---
name: works
description: 人の修正依頼を、直しを出荷する工場 darkfactory（works の生産ライン。Archon の上で動く）に、今いるリポジトリを対象にして回す。「darkfactory に回して」「works で直して」と言われたときに使う。入れ方・依頼の JSON の書き方・起動の 1 行（プラグインの中の dev/use.sh）・人の関所での答え方・報告と差分の取り込み方を書く。
---

# works

works は直しを出荷する工場 darkfactory に、人の修正依頼を今いるリポジトリを対象にして回す。

流れ: 入れる（1 回だけ）→ 依頼の JSON を書く → 対象リポジトリで起動する → 関所で答える → 報告を読む → 差分を対象へ取り込む。
回すと費用が掛かる（AI を起こすのは 2 節の `start` と、関所で進めた後だけ）。

## 0. 入れる（1 回だけ）

要る物: macOS（Apple silicon。Archon は固定した版の darwin-arm64 の実行ファイル）・git・uv・gh（初回に Archon の実行ファイルを GitHub の release から落とす）・Claude Code の `claude`・認証（普段の `claude` のログインで足りる。殻は `WORKS_KEYCHAIN_ITEM` の名の keychain の項目 → 共有の認証の部品の段（受け継いだ `CLAUDE_CODE_OAUTH_TOKEN` など・`CLAUDE_KEYCHAIN_SERVICE` の項目・設定の置き場から導く `claude-code-oauth-<名>`）→ Claude Code 自身が macOS の keychain に置いた項目（`CLAUDE_CONFIG_DIR` から導く）の順に、あなた自身の認証だけを拾い、拾った出どころの名を出す。ログインの項目は数時間で切れる短い物なので、長い run には `claude setup-token` で作るトークンを置く）。run の中の gh はあなたの gh のログインを継ぐ（トークンは gh 自身の置き場のまま。並行 PR の確かめが run の中で gh を打つ）。AI の役は包みが gh を読む形だけに絞り、PR への投稿・`git push` を拒む（事故の柵で、堅い境ではない）。git の資格は渡さない。あなたの gh がログインしていなければ、並行 PR の確かめは人に回る。

1. プラグインを Claude Code に入れる。このスキル（works）と、works の AI の役が借りる 2 つ（coldwrite のフック・pr-review-toolkit の agent）。借りる 2 つは works の依存なので、works を入れると一緒に入る。ただし依存の marketplace（raiki61・claude-plugins-official）が先に足されていないと入らず、works は「will not load without it」と言って読まれない。だから marketplace を 2 つ足してから works を入れる。起動の殻 `dev/use.sh` と pack は works のプラグインの中に在り、Claude Code が入れたプラグインの置き場から使う。coldwrite・pr-review-toolkit は、入った版をそのまま使う。superpowers のスキルは works に写した固定の版（`.shared/borrow/superpowers/<版>/`）を使うので、入れなくてよい（入れてあっても run には使わない）。リポジトリの clone は要らない。

   ```
   claude plugin marketplace add anthropics/claude-plugins-official   # 登録済みなら要らない
   claude plugin marketplace add raiki61/claude-plugins               # 登録済みなら: claude plugin marketplace update raiki61
   claude plugin install works@raiki61                                 # 依存の coldwrite・pr-review-toolkit も入る
   ```

2. 対象リポジトリで、AI を起こさずに確かめる（費用なし）。

   ```
   sh "${CLAUDE_PLUGIN_ROOT}/dev/use.sh" check <対象リポジトリ>
   ```

   uv・claude・認証・対象の条件で足りない物があれば、入れ方つきで全部並べて 0 以外で終わる。最後の行が `Results: 1 valid, 0 with errors, …` なら入っている。その上に出る `WARNING [skills]` の 3 行（`code-review`・`simplify`・`security-review`）は Claude Code に組み込みのスキルで、出てよい。coldwrite・pr-review-toolkit のどちらかが入っていない（か、works が名前で使う agent・hook が無い）と、`toolset.py: 借りる物が足りない` の下に足りない物ごとの 1 行と入れるコマンドを出して止まる。そのコマンドで入れてから打ち直す（`start` も AI を起こす前に同じ所で止まる）。`superpowers の写し（…）が borrow.json の pin と合わない` の行が出たら、works のプラグインの中の superpowers の写しが壊れているので、`claude plugin install works@raiki61` で works を入れ直す。

このスキルの行の `use.sh`・`stop.sh`・`report.sh` のパスは、Claude Code がこのスキルを読む時に、入れたプラグインの置き場の絶対パス（`~/.claude/plugins/cache/raiki61/works/<版>/` の形。設定の置き場を変えていればその下）へ置き換えてある。元の文はプラグインのスキルの置き換え CLAUDE_PLUGIN_ROOT で、Bash の環境変数には無い。手で打つ時は、その置き場のパスで打つ。

`archon plugin install` で pack を入れて Archon を直に打つ形は、まだ使わない。AI の役が利用者の本物の `~/.claude`（CLAUDE.md・hooks・プラグイン）を読んでしまうため。`use.sh` は Archon を隔離した家で起こし、役には選んだ物だけの設定を読ませる。

## 1. 依頼の JSON を書く

findings（指摘）の JSON の配列か、`{"findings": [...], "pr": [<番号>…], "issue": [<番号>…], "answers": [...], "prior_failures": [...]}` の形を 1 つのファイルにする。置き場所はどこでもよい（起動のときに写して渡す）。

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
- `text` には問題（何が困っているか）と目的（どうなってほしいか）を書き、解き方（どう直すか）は書かない。解き方の考えが在るなら、`text` の中に「案（工場が定石と比べて疑う）: …」と分けて添える。工場は案を目的から外して解き方の欄 `means` に置き、同じ種類の問題を世の中がどう解いているか（定石）と比べ、違えば違いを名指して定石を推す。案は依頼者が前に決めた事として扱わない（決め手にならない）。案と定石の違いは報告の節「世界の解」に並び、案を理由に定石から外れる修正案は修正前の関所で依頼者に聞く。欄は足さない（依頼の型は同じ）。
- 任意: `mechanism`（なぜ起きるか）・`measured`（何で確かめたか）・`false_positive_if`（どうなら誤りか）
- これ以外の欄は拒まれる。型の確かめはラインの入口で、AI を起こす前に止まる。
- object の形の `pr`・`issue`（省ける）は、対象の GitHub の PR・issue の番号（正の整数）の配列。名指した物の本文とコメントは、run の入口（start の節）が利用者の gh のログインを継いで 1 回だけ読み、run の盤面の `github.json` に置く（読めない物は読めないと記録して進む。`--pr` の base・head が読めなければ start で止まる）。この版では役はまだそれを読まない。`findings` を省くと空の配列。

```json
{"findings": [{"where": "src/app/parse.py:42", "text": "空の行で IndexError が出る"}], "pr": [12], "issue": [34]}
```

- object の形の `answers`（省ける）は、前の run の報告に並んだ問いへの依頼者の答え `[{question, text, command?, output?}]`。`question` は問いの key か出どころ（並行する PR の確かめなら `parallel_pr`）、`text` は答え。手元で測ったなら打った命令 `command` と出力 `output` を両方添える。`question` と `text` は空でない文字列が要り、`command` と `output` は両方か無し、同じ `question` は 1 度だけ（違えば入口で拒む）。当たった問いは修正前の関所に載らず、保留にも数えず、報告と最後の関所に「依頼者の答え: …」と並ぶ。どの問いにも当たらなかった答えも名指しで並ぶ。`question` が run の中で測れなかった素材の名（並行する PR の確かめ `parallel_pr`・主な経路を動かした観測 `main_path_observation` など。報告の「残り」の「素材 '<名>' が未実施」の名）なら、判定役がその素材について問いを立てていなくても当たる。その答えが `command` と `output` を両方持てば、素材の未実施は残りに数えず、報告に「人が手元で確かめた（実測とは書かない）」と命令と出力つきで並ぶ。両方が無い答えは測りの代わりにならず、未実施は残りに数えたまま。前の run の報告が `next-request.json` の `answers` に置いた答えの下書き（`draft: true` と出どころ `source` の在る行。保留のままの問いや測れなかった素材が残った時と、無人の run が関所で止まった時）はそのままでは入口が拒む。依頼者に見せて、台帳の問いと素材の行（`question` が問いの key か素材の名）は採るなら `draft` と `source` を消し（`text` は依頼者の言葉に直してよい）、採らないなら行を消す。関所の項目の行（`question` が関所の項目の文）は依頼ではどの問いにも当たらないので、次の run の関所の `continue` の一言に写してから行を消す。

```json
{"findings": [{"where": "src/app/parse.py:42", "text": "空の行で IndexError が出る"}],
 "answers": [{"question": "parallel_pr", "text": "並行する PR は無い"}]}
```

- object の形の `prior_failures`（省ける）は、前の run で最後まで通らなかった物 `[{where, text}]`（どちらも空でない文字列）。前の run の報告が `next-request.json` に書くので、手で書くことは少ない。判定役と修正案の役の材料に「直す穴ではない注意」として貼られ、目的の役と独立設計の役には渡らない。直してほしい穴は `findings` に書く。
- run の後の CI（run の外で回る重い試験）が赤だった試験は、`python3 -I "${CLAUDE_PLUGIN_ROOT}/.shared/core/carry.py" carry-ci --request <next-request.json> --failed <赤の試験の id を 1 行に 1 つ書いたファイルか -> --out <次の依頼のファイル>` で `prior_failures` に足せる（行の where は `run の後の CI`。同じ行は 2 度足さない）。id は CI の記録（例: `gh run view <run の番号> --log-failed`）から写す。

## 2. 起動する

前景で打つ（最初の関所で戻る）。

```
sh "${CLAUDE_PLUGIN_ROOT}/dev/use.sh" start [--base <版> | --pr <番号>] [--spec] [--] [<対象リポジトリ>] <依頼の JSON か -> ["<test_cmd>" [<tdd_suite>]]
```

- 入口: どの入口（依頼の JSON・`--base`・`--pr`）も、ラインの入口のブロックが 1 つの入力の形（差分の根・差分・依頼の行・PR の題と本文）に揃え、後ろは中身だけで決まる。差分（差分の根から run の作業ツリーまで）が空の run は判定から入る（依頼の指摘を判定して直す。P1 の局所の審査の役は起こさない）。差分も依頼の行も無ければ AI の前で止まる。人が変更（枝・PR）の審査を頼んだ時だけ `--base <版>`（base と HEAD の merge-base から HEAD まで）か `--pr <番号>`（GitHub の PR と同じ差分。殻が Archon を起こす前に利用者の gh で読むだけで投稿しない。読めなければ起動しない。対象の HEAD が PR の head であること）を足し、差分に局所の審査の目を回す（起動の時に「差分の根: …」の行が出る。差分が空なら目は回らない）。**`--pr`・`--base` は変更の全体の審査を足し、費用が増える**: 名指した差分の全体（PR なら全部の commit）に局所レビューのレンズ（`/code-review`・`/simplify`・pr-review-toolkit の agent）が 1 本ずつ回り、所見は判定に流れる。2026-10-09 の利用者の run（Terraform の対象・13 commit の PR）では、`--pr` で回った局所レビューが約 2.90 USD で、`--pr` の無い run より約 3 USD 多かった。依頼の指摘を直したいだけなら `--pr` を付けない（依頼の `pr` に番号を書くのは差分の審査を足さない）。変更だけなら依頼の JSON を `-` にする（ここの `-` は標準入力でなく依頼を省く意味。`--base`・`--pr` が無ければ拒む）。両方を渡すと、差分の目と依頼を一緒に判定へ流す（依頼の文と PR の題・本文は両方とも判定と目的の役に届く）。`--spec` は判定の前に仕様の段（仕様の書き手が要件と受け入れ条件のテストを書き、別の目が審査し、人が関所で承認する）を挟む。どの入口とも組めるが、依頼の文（依頼の JSON か PR の題と本文）が要り、無人の run（`WORKS_USE_UNATTENDED=1`）と固定材料とは組めない。この版の限り: 修正が受け入れ条件のテストのファイルを変えると、その問い（承認し直すか）に run の中で答える道がまだ無く、差分の審査・最後のテスト・独立の目を回さずに、問いを最後の関所と報告の冒頭・次の run の依頼に載せて終わる（直しを確かめたいなら、テストを直さずに直す依頼にするか、次の run で答える）。`--base` と `--pr` はどちらか 1 つ。旗は対象より前に置き、`--` の後は旗として読まない。手元に commit していない変更が在ると、下の「手元の変更」のとおり殻が包んだ commit が run の HEAD になるので、`--pr` は PR の head と違うとして拒まれ（commit してから打つ）、`--base` の差分には包んだ手元の変更も入る。
- 対象: リポジトリの下のフォルダでもよく、その git の根で回す。省けば今いるフォルダの git の根。`/private/tmp` の下は使えない。
- 手元の変更: commit していない変更・未追跡のファイルが在っても止めない。殻がそれを一時の commit に包み（`.gitignore` の物は入れない）、run はそこから切る。対象の作業ツリー・index・枝は動かさない（包んだ commit を守る参照を `refs/works/wraps/` にだけ置く。`clean` が消すのは run の控えか、結べなかった起動の控えに `wrap_ref` が在る時だけ。`start` が run を結べなかった時は、起動が 0 で終わり生きた候補の run が在れば run が使うので外さずに候補と一緒に `<家>/unbound/` に控え、候補の run の `clean` が消す（ほかの候補が生きている間は消さず、最後の候補の `clean` で消す）。起動が落ちたか、読めた一覧で候補が無ければその場で外す。run の一覧が読めない時は生きた run が在るか分からないので外さず、候補の無い控えに残して 1 で終わる（その対象の生きた run が無くなった後の `clean` が消す）。控えに `wrap_ref` の無い前の run の参照は残るので、要らなければ `git update-ref -d` で外す）。包んだことと commit・ファイルを「包んだ（wrapped）」の行に出す（`show` も出す）。差分はその姿との差なので、今の手元にそのまま当たる。
- remote の `origin` が要る（Archon v0.11.1 は `--from` を渡しても、origin の無い対象では run の worktree を切れずに終了コード 1 で落ちる）。無ければ `check` が並べ、`start` は Archon を起こす前に 1 行で止まり、入れ方（`git remote add origin <URL>`。手元だけなら対象の外に `git init --bare <対象>.origin.git` を作って origin にし、`git push origin HEAD` の後に `git remote set-head origin <push した枝>` で `origin/HEAD` を置く）を出す。殻は remote を足さない。あなた（Claude）も自分で remote を足さず、預ける先の URL か手元の裸のリポジトリかを依頼者に尋ねて、依頼者に決めてもらう。
- `start` は origin の既定の枝（`origin/HEAD` が指す枝、無ければ `origin/main`、次に `origin/master`）を Archon の土台（`--base`）に毎回渡す（Archon は対象を最初に登録した時の枝を覚えて更新しないので、登録した時の枝が消えても止まらない）。どれも無ければ枝を推さず、Archon を起こす前に `git fetch origin` と、それでも無い時の `git remote set-head origin -a`（または `git remote set-head origin <枝>`）を案内して止まる（裸の origin に機能の枝だけを push した対象は、fetch しても `origin/HEAD` ができない）。`origin/HEAD` が消えた枝を指す時（改名の後の `git fetch --prune`）は、それを渡さずに `origin/main`・`origin/master` へ進む。
- `test_cmd`（省ける）: 修正の前と最後に回すテストのコマンド（例: Python は `python3 -m unittest -q`・`uv run pytest -q`、Go は `go test ./...`、Rust は `cargo test`、Java は `mvn -q test` か `./gradlew test`、Terraform のような IaC は `terraform init -backend=false && terraform validate`（整形も見るなら `&& terraform fmt -check -recursive` を足す）。どの言語でも、対象の検査を対象の根から 1 行で回す形）。**`test_cmd` は機械が役の sandbox の外で直に走らせる**（網も使える）。一方、run の中の AI の役の Bash は sandbox の中で走り、多くの役は網も閉じている——依存・provider・モジュールを網から取りに行く検査（`terraform init`・`go mod download`・`cargo fetch` など）は役の中では回らないので、`test_cmd` に入れる。雲の資格や state の置き場が要る検査（`terraform plan`・`apply` など）はどちらの道でも run の中では回らない。それが確かめの素材に残れば結末は `fixed_needs_check` になるので、手元で確かめて次の run の依頼の `answers` に `command`・`output` を添えて返す。在れば、対象の `.review-checks.json` の宣言が在っても宣言の一式に加えて回し、両方が緑の時だけ緑（宣言の段と同じコマンドなら 1 度だけ回す）。省くか空なら対象の `.review-checks.json` の宣言を回し、宣言も無ければ CI の任せ先の役が走らせ方を探す。run の worktree と単位の worktree は commit から切るので、対象の git が無視する物（`.venv`・`node_modules`・`.env` など）は無い。`test_cmd` は worktree の中で環境を作る形（uv の対象は `uv run pytest -q`、npm は `npm ci && npm test`）にし、`.venv/bin/python` のような相対のパスや、対象の `.venv` の絶対パス・立てた（activate した）`.venv` に頼る形にしない（相対は走らず、絶対・立てた環境は editable で入れた対象なら worktree の直しでなく手元のコードを試す）。`start` は手元を走らせる形（対象の手元の在る物を絶対パスで指す・対象を editable で入れた外の環境を絶対パスか `PATH=` で指す・editable で入れた立てた環境を掴む。直しの正誤に関わらず緑になり得る）を見つけると、`止める（test_cmd）` の行を出して Archon を起こさずに止まる（終了コード 2。形の確かめそのものが落ちた時も、落ちた終了コードを名指す 1 行で止まる）。その時は依頼者に `test_cmd` を `uv run pytest -q` のような worktree の中で環境を作る形へ書き直してもらう。依頼者が形を知った上でそのまま回すと決めた時だけ `WORKS_USE_ALLOW_TESTCMD=1` を前に付けて打ち直す（自分で付けない）。相対のパスのように worktree で走らない形は `注意（test_cmd）` の行だけで止まらないので、その時も依頼者に `test_cmd` を確かめてから進める（詳しくは README の「test_cmd と worktree」）。
- `.review-checks.json` の段（`suite` の `{"name", "argv"}`）は任意の `junit`（段が書く JUnit XML の、対象の根からの相対パス）を持てる。持つ段は報告の試験の件数で走ったかを見て、報告が無い・段の起動より古い・試験が 0 件・全部 error なら、赤でなく「基準の検査が走らなかった（コードの赤ではない）」に回す。持たない段の赤は赤のまま、走ったかは確かめていないと添える。
- `tdd_suite`（省ける）: JUnit XML の書き先を第 1 引数に受ける実行ファイル（対象の根から走る）。機械は後ろに試験のファイル・node id（絶対パス）と `-k` を足して呼ぶことがある（既定の一式に足して集める。解けない実行器は無視してよい。TDD の輪の赤・緑の回は env `TDD_SUITE_ONLY=1` を付けて呼び、その時は後ろに足した試験だけを走らせてよい）。在れば修正の段で単位ごとの TDD の輪を回す。省くと、`test_cmd` が pytest の 1 コマンドなら殻がそれに `--junitxml` を足す実行器を書いて渡し、そうでなければ輪を飛ばして直に直す（どちらにしたかを 1 行出す）。
- 最後の関所は既定で守りのファイルを触った時だけ開く（`protected_only`）。テストの赤・独立の目の阻害・残った異議は報告の冒頭に並ぶので、差分を当てる（`use.sh apply`）前に読む。それらでも止めるなら `WORKS_USE_FINAL_GATE=when_needed`、いつも開くなら `always` を前に付ける。
- Claude の包み（`claude-adapter`）は既定で通す。外すなら `WORKS_DEV_ADAPTER=0`（起動の 1 行目に「包み無し」と出て、報告にも出る）。
- ラインの入力 `policy_md`・`gates`・`thickness` は `WORKS_USE_POLICY_MD`・`WORKS_USE_GATES`・`WORKS_USE_THICKNESS` で渡す。`thickness` は空（自動。単位ごとに機械が深さを決める）・`標準`（今の工程を全部）・`軽量`（全部の単位を軽量に固定）。
- 木・枝の形の機能を切る・入れて比べるなら `WORKS_USE_FEATURES_OFF`・`WORKS_USE_FEATURES_ON`（入力 `features_off`・`features_on`。語 `judge_verify`・`review_tree`・`tdd_lanes`・`fix_lanes`・`graph_map` をカンマで区切る）。既定は `judge_verify` が off（判定の裏取りを回さない）、`review_tree` が auto（開いた項目が 2 つ以上の往復だけ事前審査を木にする）、ほかは on。名指した語が既定に勝つ（判定の裏取りを回すなら `WORKS_USE_FEATURES_ON=judge_verify`、項目の数に依らず木にするなら `review_tree` を足す）。同じ語を両方に名指すと start が止める。on でない機能は報告の冒頭 2 に、入力は `versions.json` の `settings` に残る。
- 無人で回すなら `WORKS_USE_UNATTENDED=1`: 起動の関所を越え、人が決める関所に着いたら止めて報告へ進める（関所に出た、能力を狭める・方針とぶつかる修正は通さない。関所に出ずに決め手で通る行は 3 節の `policy-gate` の項。判定の保留の問いだけでは関所を開かず、問いの出どころだけを飛ばして直し、問いを報告の冒頭に並べる）。値は 1 か空だけで、ほかの値（`on` など）なら start が何も作らずに止まる。
- 殻がすること: pack を利用の家（`WORKS_USE_HOME`。既定は `~/.local/state/works/use-<対象の clone の実際のパスの sha256 の頭 8 字>`。clone ごとに分かれる）に置き、Archon をその家に隔離して起こす。AI の役はその家に組んだ選んだ物だけの Claude の設定を読み、あなたの `~/.claude` は読まない。対象の作業ツリーには何も書かない。
- AI の役の子には `GRAPHLOOPS_ENGINE_CHILD=1` が立つ（役の Bash から起こすコマンドにも継がれる）。対象の重い一式（e2e・変異の撃ち）は、これを見て AI の役からの起動を拒める。名は graphloops の engine と同じにしてある。線の節が走らせる最後のテストには立たない。Claude の包みを通さない run（包み無し）でも立たない。
- Archon がすること: 対象の `.git` に run の worktree と枝を足す（worktree は利用の家の下）。worktree は `origin` の在る対象でだけ切れる（v0.11.1 で測った）。対象の枝を早送りするかは Archon の版に依る（v0.11.1 で測っていない）。
- 最初に起動の関所（`launch`）で止まって戻り、run id・状態・run の worktree・次に打つ行（進める・待つ・取り消す・答える・止める・続ける）・報告の置き場を出す。

## 3. 人の関所で見て答える

関所は 3 つ。どれも文言に「全文のファイルのパス」が載るので、そのファイルを読んで答える。打つ行は殻が出した物をそのまま使う（`use.sh show <対象>` でいつでも出し直せる）。関所の全文の答えの行も、この殻の `answer` の行で書いてある。

**人が決める関所（修正の前の関所と最後の関所）は、あなた（/works を回す Claude）が自分で通さない。** 必ず依頼者に聞く。聞く時は 4 節の「依頼者に聞く・伝える時の書き方」の並びで冒頭にまとめる: 何が止まったか（何を決めるのか）・なぜ止まったか（背景）・答えごとに何が起きるか（`continue` なら何が通り、`stop` なら報告だけ出る）・あなたの推奨とその理由・答えの後にあなたが何をするか。依頼者の言葉をそのまま一言にして、答えた者の名を最後に付けて打つ（殻が `<利用の家>/answers.jsonl` に残す）。答えた者は必須で、省くか空白だけだと殻が拒む。関所の全文の答えの行の末尾の `"<答えた者>"` も埋めてから打つ。

```
sh "${CLAUDE_PLUGIN_ROOT}/dev/use.sh" answer <対象リポジトリ> <run-id> continue "<通す範囲と条件>" "<答えた者>"
```

1. 起動の関所 `launch`: 「殻で進める」の行（`use.sh approve <対象リポジトリ> <run-id>`）で始まる。
2. 修正の前の関所 `policy-gate`（要る時だけ）: 修正案が能力を狭める・事前審査が後退や方針の穴を挙げた・方針の文書が変わった・判定の役が問いの台帳に人に聞く問い（held・escalate の fork・escalate）を残した時に開く。全文は盤面の `r1/gate.md`。
   - 問いの行には選択肢と判定の役の推しが載る。`continue` の一言に問いごとに選んだ選択肢を書く。一言が問いに触れなければ、修正役は推しで直す（`continue` でその問いの出どころは直す義務に戻る）。保留を続ける問いは一言に `保留: <問いの key>` と書く（その出どころはこの run では直さず、報告の冒頭に並ぶ）。
   - 狭めと穴の行のうち、役が決め手の出どころを書き、決め手を当たっても答えが割れず、柵（外への書き込み・取り消せない操作・方針の文書の変更・守り（資格・sandbox）を広げる・web の結果が新しい疑いを出した）に当たらない行は、関所に出さずに通す。通した行は出どころつきで報告の冒頭にいつも並び、最後の関所が開いた時はその文にも並ぶ（通した行だけでは最後の関所は開かない（既定の `protected_only` でも `when_needed` でも）。関所で必ず見るなら `WORKS_USE_FINAL_GATE=always`）。
   - 通す: `answer … continue "<通す範囲と条件>" "<答えた者>"`。一言は修正役にファイルで届く。依頼者がこの周で直さない単位を名指ししたら、その単位と理由を一言に書く（修正役に届くが、直す義務の数からは外れない。単位を外す口はこの関所に無い）。
   - 止める: `answer … stop "<理由>"`。止めても報告は出る。
   - 保留の問いには、次の run の依頼の `answers` でも答えられる（報告の冒頭の答え方の行）。作業場所で測れない物は、問いの「測り方」の命令を手元で打ち、`command` と `output` を添えて返す。命令は対象リポジトリを読んだ AI の役が書いた物なので、打つ前に読み、読み取りだけの測り（書き込み・外への送信・取り消せない操作をしない）の時だけ打つ。
3. 最後の関所 `final-gate`（既定の `protected_only` では守りのファイルが変わった時だけ開く。`when_needed` では、テストが緑でない・独立の目が阻害を返した・問いや異議が残った時・修正役が人に回した物（壊すと分かって通した理由）が在る時・守りのファイルが変わった時に開く。修正役が人に回した物は報告の冒頭 1 にもいつも並ぶ。`final_gate: always` ならいつも）: 最後のテストと独立の目 R1〜R4 の後に開く。テストの緑赤・ログ・差分の置き場・残った異議・目の判定が全文 `r1/final-gate.md` に在る。`continue` でも `stop` でも報告へ進む。`stop` と答えた run の差分は、`apply` が当てずに止まる（4 節）。
   - 独立の目の R4 が人に聞く物（消えた能力・方針とのぶつかり）を挙げたら、その問いも関所の全文に載る。関所の `continue` は問いに答えない。問いは報告の冒頭と次の run の依頼の下書きに載り、結末は `needs_human`。

殻の `approve`・`answer`・関所で待つ run の `stop` は、残りの工程（次の関所か終わりまで）を殻が切り離して回し、すぐ戻る（出力は `<利用の家>/logs/<run-id>-<時刻>.log`。終了コードは起こせたかだけ）。成否と状態は次の行を前景で打って見る。決まった時間（既定 540 秒。`WORKS_USE_WAIT_SECONDS` で変える）のうちに戻り、状態を 1 行と終了コードで返す（0 = 関所で待つ・3 = まだ走っている・5 = 終わった・1 = 落ちた）。3 なら同じ行を打ち直し、0 なら `show` で関所の文を読んで答える。止めるなら 5 節の `stop` を使う。

```
sh "${CLAUDE_PLUGIN_ROOT}/dev/use.sh" wait <対象リポジトリの根> <run-id>
```

判定が直す物を 1 つも残さなかったときは、修正の段を飛ばして報告へ行く（結末は `no_fix_needed`）。

## 4. 報告を読み、差分を取り込む

```
sh "${CLAUDE_PLUGIN_ROOT}/dev/use.sh" show <対象リポジトリの根>
```

その対象で start が結んだ（控え `<家>/runs/<run-id>.json` の在る）一番新しい run について、状態・報告の置き場・差分のファイルを出す（run id を後ろに足せば、その run について出す）。start は起動の直後に、この起動の依頼を盤面に持つ run を 1 つに結ぶ。結べなければ候補の run id と show の行だけを出すので、その run id を名指しして show する（依頼を `-` で省いた start は結ぶ依頼が無いので、いつもこの形で終わる）。状態の下には `launched_min`（起こしてからの分）が出る。走っている run なら、今走っている節・`alive`（最後の動きから 30 分以内なら true）・節ごとの費用 `cost_usd` も出る（止まって見えるのか走っているのかはこれで見分ける）。試験の段が機械全体の試験の枠（同時に 4 本まで）の空きを待っている間は `試験の枠: 待っている（N 分・置き場 …）` の 1 行も出る（期限なしで待つので、止まった run と見分けるための行。枠の中なら `試験の枠: 中`）。

- 報告: 盤面の `report.md`（冒頭に決めてほしいこと・入口・止めた理由・読んだ証拠・置き場）と `next-request.json`（次の run に渡す依頼の下書き `{"findings": [...], "prior_failures": [...]}`。下書きの印の無い行はそのまま次の run の依頼に使える。判定が凍結した目的の外として単位にしなかった材料の所見（最後の周の分）も、材料の行の全部の欄で `findings` に載るが、`draft: true`・`source` の印つきで、依頼の入口が拒む——依頼者に見直してもらい、次の run の目的に入れる行は印を消し、入れない行は消す（人が決めることではなく次の run に回すかの材料なので、報告の「1. 人が決めること」には件数と置き場だけが載り、1 件ずつの中身は本文の節「判定が目的の外とした所見」に在る）。保留のままの問い（人の居る run でも）・問いの立っていない run の中で測れなかった素材・無人の run が関所で止めた項目を残した時だけ、答えの下書き `answers`（`draft: true`・`source` つき。推しの無い行は `text` が空で、材料は `note`）が足され、それは依頼者が見直すまで使えない。下書きの `question` は答える時に字のまま書く名で、報告の保留の行の尾「答える時の answers の question: "…"」と同じ）と `prior-failures.json`（この run で最後まで通らなかった受け付けの理由と R2 の作り直しの理由）。
- 結末（run の出口の `outcome`）: `fixed`・`fixed_needs_check`（直しは受け付けを通り最後のテストも緑で、残ったのが run の中で測れなかった確かめ——網の拒否で回らなかった並行 PR の確かめや、雲の資格が要る主な経路の観測など、素材の未実施・人の起動待ち——だけ。報告の冒頭 1 に「人が確かめる物」として各行が並び、次の run の依頼の下書きにも今と同じく載る。手元で確かめたら、次の run の依頼の `answers` に素材の名と `command`・`output` を添えて返す。`use.sh apply` は `fixed` と同じく当てる）・`no_fix_needed`・`round_limit`（直しは受け付けを通ったが、検証器の阻害・最後のテストの赤・独立の目の block が残った。冒頭 1 に残りの各行。本線 graphloops の runner の `round_limit`＝`--stop-after-round` の周で止めた、とは別の意味）・`stopped_by_human`（関所で止めた）・`stopped_by_request`（止め札）・`stopped_by_line`（機械が止めた）・`needs_human`（盤面が人に聞いたまま）・`record_invalid`（周の記録が検証器を通らない）・`interrupted`（run が途中で終わった。冒頭 3 に落ちた節）。
- 差分: run の worktree と周の頭の版の差（手直しと未追跡も入る）を、利用の家の `diffs/run-<id>.diff` に書く。修正は commit されない。取り込むかは人が決め、`sh "${CLAUDE_PLUGIN_ROOT}/dev/use.sh" apply <対象リポジトリの根> <run-id>` で当ててから、手元でテストを回して commit する。殻は差分を書き直し、`git apply --check` で当たるかを先に見る。対象のファイルを消す差分は、消すファイルを並べて止まる（消してよければ `WORKS_USE_ALLOW_DELETE=1` を前に付けて打ち直す）。記録が止まりを示す run（人が最後の関所で `stop` と答えた・止め札・ラインの止め）の差分は、止まった結末と一言を 1 行で出して止まる。当てるのは依頼者が当てると決めた時だけで、`WORKS_USE_ALLOW_STOPPED=1` を前に付けて打ち直す。止まりかどうかを記録で確かめられない run（途中で終わった・関所で待つ run など）は、その 1 行を出して当てる。
- 片付け: run の worktree・枝・控え（包んだ基を守る参照）と、修正の段がその worktree から切った単位の worktree・守りの参照（`refs/works/units/` の下）は自動で片付く。正常に終わった・取り消した run（状態 completed・cancelled）は `wait`・`show` が差分を書き終えた後に消し、落ちた run（failed）などの生きていない run は次の `start` が差分を書いてから消し、落ちた run の Archon の記録も abandon で閉じる。差分を書けなかった run と、走っている・関所で待つ run は残す。差分のファイルと盤面は残るので、取り込みは片付けの後でも `apply` で当たる（片付けた run は Archon の resume で続けられない）。`start` が片付けた run の id と状態は、`start` の出力と報告の冒頭 2 に出る。手で消すのは `sh "${CLAUDE_PLUGIN_ROOT}/dev/use.sh" clean <対象リポジトリの根> <run-id>`（走っている・関所で待つ run は拒む。落ちた run は Archon の記録も abandon で閉じるので resume できなくなる。worktree がもう無い run でも閉じる）。
- `report_file`: 最後の報告。盤面が報告の節を出した run（人か止め札で止めた・収束した）では AI が書いて初見の読み手が確かめた `report-ai.md`（最後に機械の報告が字のまま付く）、そうでなければ機械の `report.md`。機械の報告はいつも `machine_report_file`。

依頼者に聞く・伝える時の書き方（3 節の関所で聞く時も、報告を読んで結果を伝える時も同じ。聞く物を増やす決まりではなく、聞くと決まった時・伝える時の書き方で、自明な分かれ目は今どおり推しで決める）:

- 依頼者はこの run も会話の前の文脈も見ていない前提で、初見で決められるように書く。決めてほしい事が在れば、それを最初に置く。
- 決めてほしい事は 1 件ずつ、次の順に書く。
  1. 何を決めるのか（1 文）
  2. 背景: 出てくる PR・issue・ファイルが何かを 1 行ずつ
  3. 選べる答えごとに起きること（具体の作業・手間・壊れる物）
  4. あなたの推しとその理由
  5. 答えの後にあなたが何をするか
- 結果だけを伝える時は、何が起きたか・何が変わったか・依頼者に求めること（無ければ次に大事な事実）を先に言う。`report.md` の決めてほしいことは、上の並びで言い直す。
- run の中の語（R1〜R4・`needs_human` などの結末の名・block・do-now・節の名・run id など）は使わない。使うなら中身を先に書く（例: 「最後に差分を見る独立の目（R4）」）。
- 費用・直しの中身・置き場（報告や差分のパス）は、その後ろに畳む。

## 5. 止めて続ける

止め方は 1 つ:

```
sh "${CLAUDE_PLUGIN_ROOT}/dev/use.sh" stop <対象リポジトリ> <run-id> "<理由>"
```

- 関所で待っている run には `respond … stop` を、走っている run には止め札（中で `sh "${CLAUDE_PLUGIN_ROOT}/dev/stop.sh" <run-id> "<理由>"` を、利用の家を埋めて打つ）を置く。止め札では、走っている AI の節は最後まで走り、次の境の節で止まる。どちらも報告は出る。
- すぐ止めたい時だけ、`show` が出した「取り消す」の行（`cancel <run-id>`）を使う（報告の節まで届かない。下の report.sh で組む）。
- 続ける: 殻が出した「続ける」の行（`resume <run-id>`）で、済んだ節の続きから回る。
- 節が落ちた run（ブロックの中の出し直しが上限（3 回）を超えたときを含む）でも報告の節は走り、結末 `interrupted` の `report.md` と `next-request.json` が盤面に残る。冒頭 3 に落ちた節とその誤りの文が出る。run の出口は報告を書いてから 0 でない終了コードで終わるので、Archon の run の状態は失敗のまま。start で落ちた run は盤面が無く、報告も無い。
- 取り消し・abandon で止めた run は報告の節まで届かない。対象の根で、止め札と同じ `WORKS_DEV_HOME=…` を前に付けて `sh "${CLAUDE_PLUGIN_ROOT}/dev/report.sh" <run-id>` を打つと、盤面から報告を組む（結末 `interrupted`）。

