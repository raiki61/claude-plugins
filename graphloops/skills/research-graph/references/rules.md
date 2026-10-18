# research-graph の人の方針と守ること

## 人の方針

人が決めた、どの run にも効く決まりは、対象リポジトリの共有の git ディレクトリ（`git rev-parse --git-common-dir` が指す所）の下の `graphloops/policy.md` に置けば、`init` が拾う（別の文書なら `init --input policy_md=<パス>`）。問いの確定・反証・統合・内部照合・適用のノードに、役には本文が、回す側には置き場が届く。置き場の決め方と文書の変化の扱いは [review-graph の「人の方針」](../../review-graph/references/policy.md#人の方針) と同じ——ただしこの loop には周の途中のゲートが無いので、文書が init の後に変わっても周の途中では人に聞かない。init の時点の版（sha と写しの置き場）を記録の `process.policy` に固定し、報告の前の仕上げで比べて、変わっていれば `process.policy_change`（前後の写しと差分の置き場）に残し、報告の冒頭に出す。

## 守ること

- **run の途中でプラグインの版を上げても、走っている run の graph は init の時の版のまま**: 盤面は init の時の graph を、その置き場（インストールされた版のディレクトリ）の絶対パスで持ち、graph・指示書・rules・検証器をそこから読み続ける。置き場のファイルそのものが書き換わる形（`--plugin-dir` などでその場から読み込んだプラグイン）では graph も変わり、変わった周は `next` の `notes` と `process.graph_changes` に出る。engine（`loop.py`）は今インストールされている版で動き、役の定義（convergence-loops の `agents/<役>.md` のツール・モデル・effort・system prompt に足す本文）はノードを描くたび（`next` がノードを出すとき）に今見つかる版から読む——どの engine が周を回したかは、替わった周の `next` の `notes` に出る。新しい版の graph や指示書の動きが要るなら、走っている run を仕上げてから新しい run を始めよ。盤面を別の版の graph へ付け替える手順は用意していない（`loop.py patch` で state を書き換えれば変わるが、それは手当ての口で、この用途には案内しない）。更新で置き換わった古い版のディレクトリは後で掃除されることがあり（公式の plugins の読み込みの文書『Cleanup of previous versions』）、消えるとその run は開けなくなる。古い版の graph が役を `--output-format text` で起動しても、engine は包みでない標準出力を本文として読むので、返答は受け付けまで届く。
- 置き場は `git rev-parse --git-dir` の下（作業ツリーの外）。investigator の前後で engine が `git status --porcelain` と作業ツリーの中身の木の id を突き合わせ、差があれば `done` を拒む（investigator の区間に、作業ツリーへ書きうる手——graph の `launch.runner.edits` のノードか、対象リポジトリの宣言の語を engine が走らせるノード——が重なっていれば、帰属を断定せずに痕跡だけ残して通す）。自分の変更なら `--accept-tree-change "<理由>"` で痕跡付きで通す。
- 報告は依頼者の言語で書く。この手順書が日本語なのは理由にならない。
