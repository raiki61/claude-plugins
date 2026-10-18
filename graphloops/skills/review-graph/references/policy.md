# review-graph の人の方針（置き場・届く先・書き換え）

## 人の方針

人が決めた、どの run にも効く決まり（例: 今ある能力を減らさない・期限を足さない）は、依頼文に毎回書き写さず、1 つの文書に置く。既定の置き場は対象リポジトリの共有の git ディレクトリ（`git rev-parse --git-common-dir` が指す所。worktree からも本体の `.git`）の下の `graphloops/policy.md` で、在れば `init` が拾う。別の文書を使うなら `init --input policy_md=<パス>`（無いファイルを名指しすると init が止まる）。置き場の決め方の正本は `rules/policy_input.py`。

- **作業ツリーの外に置く理由**: 採点する版・差分・作業ツリーの突合に入らず、run の途中に人が書き足しても P1 の撃ち直しにならない。同じリポジトリの worktree の run は全部同じ文書を読む。リポジトリの中の決定記録（先行議論の突合 `p0.prior_decisions` が洗う物）とは別物——方針は run をまたいで効く人の決まりで、決定記録はリポジトリの中の個々の論点の決着
- **届く先**: 役の節には、節を出す時点の本文が貼られる（run の途中の人の書き足しも後の節に届く）——判定（`p2.diagnose`・`p2.history`・再判定）・審査（`p2.plan_review`・`p3.delta_review`・`p3.delta_review2`）・R1・R2 の設計・R3・R4。回す側の節には置き場が渡る（在れば先に全部読む）——修正案（`p2.fix_plan`）・修正（`p3.fix`）・手直し（`p3.delta_fix`・`p3.delta_fix2`）。段落の正本は `prompts/policy-paste.md`（本文を貼る）・`prompts/policy-path.md`（置き場を渡す）・`prompts/policy.md`（規則）で、graph の `prompt_append` が各節に足す。research-graph の判定と適用の節にも同じ段落が届く。コマンドを走らせる子（回す側の節の全部・任せ先・Bash を持つ役）には、graph の `launch.append` が方針の置き場と手元で走らせてよい範囲の段を、節の名前でなく子の形で足す（依頼の本文は貼らない）
- **手元で回さない一式の柵**: 対象リポジトリが Claude Code の標準の置き場（リポジトリの `.claude/settings.json`）の `permissions.deny` に置いた規則は、engine が起こす Bash を持つ子（道具つきの役・回す側の節の子・任せ先）の `--settings` に写る（子は利用者の設定を読まないので engine が写す。allow・ask・ほかの鍵は写さない）。その置き場は対話の会話にも効く。読めない・形が壊れているときは Bash を持つ子を起こさず、`launch` の `why` が直すファイルを名指す。前置の照合なので別の綴りでは抜けうる——主な手当ては方針の段で、deny は第二の網
- **書き換え**: 方針は人が書く。init の時点の版を `record.process.policy` に固定し（sha と写しの置き場）、変わっていれば「手順」の 3 の「周の途中の関所」で人に聞く（通せば新しい版を固定し、履歴は `amendments`）。最後の関所の後に変わったまま終わった run は、記録の `process.policy_change` と報告に出る
- **中身は engine と graph に書かない**: 比べる元（init と関所で固定した版）の写しは盤面の `policy/` に sha256 の名前で置き、変化を見つけたら差分のファイルも同じ置き場に置く。記録と関所の行には置き場だけを載せる（本文を載せると、人の答えの台帳を通って回す側の節に貼られる）
