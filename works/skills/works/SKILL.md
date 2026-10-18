---
name: works
description: 人の修正依頼を、直しを出荷する工場 darkfactory（works の生産ライン。Archon の上で動く）に、今いるリポジトリを対象にして回す。「darkfactory に回して」「works で直して」と言われたときに使う。入れ方・依頼の JSON の書き方・起動の 1 行（プラグインの中の dev/use.sh）・人の関所での答え方・報告と差分の取り込み方を書く。
---

# works

works は直しを出荷する工場 darkfactory に、人の修正依頼を今いるリポジトリを対象にして回す。

流れ: 入れる（1 回だけ）→ 依頼の JSON を書く → 対象リポジトリで起動する → 関所で答える → 報告を読む → 差分を対象へ取り込む。
回すと費用が掛かる（AI を起こすのは `start` と、関所で進めた後だけ）。

## 先に守ること（踏むと壊れる所）

- **人が決める関所（修正の前の関所と最後の関所）は、あなた（/works を回す Claude）が自分で通さない。** 必ず依頼者に聞き、依頼者の言葉をそのまま一言にして、答えた者の名を最後に付けて `answer` を打つ（答えた者が空だと殻が拒む）。
- 依頼の `text` には問題と目的を書き、解き方は書かない（考えが在れば「案（工場が定石と比べて疑う）: …」と分けて添える）。
- `--pr`・`--base` は変更の全体の審査を足し、費用が増える。依頼の指摘を直したいだけなら付けない。
- 対象に remote の `origin` が無いと起動できない。あなたは自分で remote を足さず、預ける先の URL か手元の裸のリポジトリかを依頼者に決めてもらう。
- `WORKS_USE_ALLOW_TESTCMD=1`（手元を走らせる形の test_cmd を通す）・`WORKS_USE_ALLOW_DELETE=1`（ファイルを消す差分を当てる）・`WORKS_USE_ALLOW_STOPPED=1`（止めた run の差分を当てる）は、依頼者が決めた時だけ前に付ける（自分で付けない）。
- `approve`・`answer`・関所で待つ run の `stop` はすぐ戻る。成否は `wait` を前景で打って見る。
- 関所の問いの「測り方」の命令は AI の役が書いた物なので、打つ前に読み、読み取りだけの測りの時だけ打つ。

## 命令

下の `use.sh`・`stop.sh`・`report.sh` のパスは、Claude Code がこのスキルを読む時に、入れたプラグインの置き場の絶対パス（`~/.claude/plugins/cache/raiki61/works/<版>/` の形。設定の置き場を変えていればその下）へ置き換えてある。元の文はプラグインのスキルの置き換え CLAUDE_PLUGIN_ROOT で、Bash の環境変数には無い。手で打つ時は、その置き場のパスで打つ。別ファイルの命令の頭の `<works の置き場>` も、この置き場（下の `use.sh` の行の `/dev/` の手前）で読み替えて打つ。

```
claude plugin marketplace add anthropics/claude-plugins-official   # 登録済みなら要らない
claude plugin marketplace add raiki61/claude-plugins               # 登録済みなら: claude plugin marketplace update raiki61
claude plugin install works@raiki61                                 # 依存の gates・pr-review-toolkit も入る
sh "${CLAUDE_PLUGIN_ROOT}/dev/use.sh" check <対象リポジトリ>         # AI を起こさずに確かめる（費用なし）
sh "${CLAUDE_PLUGIN_ROOT}/dev/use.sh" start [--base <版> | --pr <番号>] [--spec] [--rounds <N> [--budget-usd <X>]] [--] [<対象リポジトリ>] <依頼の JSON か -> ["<test_cmd>" [<tdd_suite>]]
sh "${CLAUDE_PLUGIN_ROOT}/dev/use.sh" answer <対象リポジトリ> <run-id> continue "<通す範囲と条件>" "<答えた者>"
sh "${CLAUDE_PLUGIN_ROOT}/dev/use.sh" wait <対象リポジトリの根> <run-id>
sh "${CLAUDE_PLUGIN_ROOT}/dev/use.sh" show <対象リポジトリの根> [<run-id か鎖の id>]
sh "${CLAUDE_PLUGIN_ROOT}/dev/use.sh" apply <対象リポジトリの根> <run-id か鎖の id>
sh "${CLAUDE_PLUGIN_ROOT}/dev/use.sh" clean <対象リポジトリの根> <run-id か鎖の id>
sh "${CLAUDE_PLUGIN_ROOT}/dev/use.sh" stop <対象リポジトリ> <run-id> "<理由>"
sh "${CLAUDE_PLUGIN_ROOT}/dev/stop.sh" <run-id> "<理由>"     # 走っている run の中に止め札を置く
sh "${CLAUDE_PLUGIN_ROOT}/dev/report.sh" <run-id>          # 取り消した run の報告を盤面から組む
```

起動の関所は `start` が出す「殻で進める」の行（`use.sh approve <対象リポジトリ> <run-id>`）で越える。打つ行は殻が出した物をそのまま使う（`show` でいつでも出し直せる）。

## 場面ごとに読む別ファイル

1 つの場面で読むのは 1〜2 本。
- 初めて入れる時と、`check` か `start` が足りない物を並べて止まった時: [references/install.md](references/install.md)（要る物・認証の拾い方・`check` の出力の読み方・入れ直し方）
- 依頼の JSON を書く時と、前の run の `next-request.json` から次の依頼を作る時: [references/request.md](references/request.md)（`findings` の欄・`pr`・`issue`・`answers`・`prior_failures`・CI の赤の運び方）
- `start` を打つ前: [references/start.md](references/start.md)（入口と旗・対象の条件・手元の変更・`origin`・`test_cmd` の形・`.review-checks.json`・`.works-checks.json`・`tdd_suite`・最後の関所の既定・環境変数・無人の run・周の鎖）
- 関所で止まった時と、`approve`・`answer` の後に `wait` を打つ時: [references/gates.md](references/gates.md)（3 つの関所ごとの答え方・保留の問い・`wait` の終了コード）
- run が終わって報告を読む時と、`apply`・`clean` を打つ時: [references/report.md](references/report.md)（`show` の出力・報告と次の依頼の下書き・結末の名・差分の当て方と止まる訳・片付け）
- run を止める・取り消す・続ける時: [references/stop.md](references/stop.md)（止め札・取り消し・`abandon`・`resume`・止めた run の報告の組み方）

## 依頼者に聞く・伝える時の書き方

関所で聞く時も、報告を読んで結果を伝える時も同じ。聞く物を増やす決まりではなく、聞くと決まった時・伝える時の書き方で、自明な分かれ目は今どおり推しで決める。

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
