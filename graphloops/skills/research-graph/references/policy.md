# research-graph の人の方針（置き場・届く先・書き換え）

## 人の方針

research-graph を回す会話が、方針がどのノードに届くかと、人が方針の文書を書き換えたときに run がどう扱うかを確かめるときに読む。方針の文書は人が書き、回す側（あなた）は書かず直さない。run を回す手順は SKILL.md のとおり。

人が決めた、どの run にも効く決まり（例: 今ある能力を減らさない・期限を足さない）は、依頼文に毎回書き写さず、1 つの文書に置く。既定の置き場は対象リポジトリの共有の git ディレクトリ（`git rev-parse --git-common-dir` が指す所。worktree からも本体の `.git`）の下の `graphloops/policy.md` で、在れば `init` が拾う。別の文書を使うなら `init --input policy_md=<パス>`（無いファイルを名指しすると init が止まる）。置き場の決め方の正本は `rules/policy_input.py`。

- **作業ツリーの外に置く理由**: 調べる版・作業ツリーの突合に入らない。同じリポジトリの worktree の run は全部同じ文書を読む。リポジトリの中の決定記録（ADR など、個々の論点の決着）とは別物——方針は run をまたいで効く人の決まり
- **届く先**: 問いの確定・反証・統合・内部照合・適用のノードに届く。役のノード（反証の `p1.refuter` と内部照合の `p5.internal`）には、ノードを出す時点の本文が貼られる（run の途中の人の書き足しも後のノードに届く）。段落は `prompts/policy-paste.md`（本文を貼る）と `prompts/policy.md`（規則）で、graph（`graphs/research-loop.json`）のそのノードの `prompt_append` が足す。回す側のノード（問いの確定の `p0.question`・統合の `p2.integrate`・適用の `p5.adapt`）は、`reads` の `record.process.policy.path` で置き場を受け取る（在れば先に全部読む）。コマンドを走らせる子（engine が `claude -p` で起動する、Bash を持つ子）には、graph の `launch.append` が `prompts/policy-path.md`（置き場を渡す）と `prompts/policy.md` を、ノードの名前でなく子の形で足す——届くのは方針の置き場だけで、依頼の本文は貼らない
- **手元で回さない一式のチェック**: 対象リポジトリが Claude Code の標準の置き場（リポジトリの `.claude/settings.json`）の `permissions.deny` に置いた規則は、engine が起動する Bash を持つ子（ツールつきの役・回す側のノードの子）の `--settings` に写る（子は利用者の設定を読まないので engine が写す。allow・ask・ほかの鍵は写さない）。その置き場は対話の会話にも効く。読めない・形が壊れているときは Bash を持つ子を起動せず、`launch` の `why` が直すファイルを名指す。前置の照合なので別の綴りでは抜けうる——主な手当ては方針の段で、deny は第二の安全網
- **書き換え**: 方針は人が書く。init の時点の版（sha と写しの置き場）を記録の `process.policy` に固定する。この loop には周の途中のゲートが無いので、文書が init の後に変わっても周の途中では人に聞かない。報告の前の仕上げで比べて、変わっていれば `process.policy_change`（前後の写しと差分の置き場）に残し、報告の冒頭に出す
- **中身は engine と graph に書かない**: 比べる元（init で固定した版）の写しは盤面の `policy/` に sha256 の名前で置き、変化を見つけたら差分のファイルも同じ置き場に置く。記録の行には置き場だけを載せる（本文を載せると、記録を通って回す側のノードに貼られる）
