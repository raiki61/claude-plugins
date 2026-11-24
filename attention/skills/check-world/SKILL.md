---
name: check-world
description: PR が選んだ解き方を、世の中の解（依存の部品・同じ種類の製品・標準・差分を見ない目が描いた一般の構造）と層ごとに比べる小さな Workflow（attention:dig-world）を 1 回回す。人が /attention:check-world と打ったときだけ動く。依頼の行・目的・手段は /attention:my-turn-deep の前の記録から写す。投稿はしない。`--headless` を付けると、設定・フック・CLAUDE.md を読まない別の会話（`claude -p`）で回す。
argument-hint: "[PR 番号] [--record <重い版の記録>] [--headless]"
disable-model-invocation: true
---

持ち主はこの会話の相手。これは世界の解（世の中の実務家がその種類の問題をどう解いているか）だけを問う小さな Workflow を回す手順で、人が名前で打ったときだけ動く。/my-turn・/attention:my-turn-deep から呼ばない。設計は `attention/docs/small-workflows-design.md` のセクション 3。

## 守ること

- 比べる段（言い直し・探す・抜き書きの取り直し・比べ）はこの会話で回さず、Workflow に回させる。Workflow が返さなかった行（`missing`）を、この会話が代わりに調べて埋めない。返らなかったと報告する。
- Workflow に渡す args は、下ごしらえ（2）が書いたファイルの JSON をそのまま渡す。値を書き換えない・文字列にしない。args の `sum` が中身と合わないと、Workflow はエージェントを立てずに止まる。
- GitHub へは書き込まない。PR へのコメントも下書きも作らない。

## 手順

以下、機械は `bash "${CLAUDE_PLUGIN_ROOT}/scripts/run-python.sh" "${CLAUDE_PLUGIN_ROOT}/scripts/<台本>"` で打ち、`python3` に替えない。PR の作業場（PR の head のブランチを開いた作業場）で打つ。

1. 対象を決める。引数の番号を使い、無ければ `gh pr view --json number` で今のブランチの PR を引く。どちらも無ければ、PR 番号を聞いて止まる。記録は引数の `--record` を使い、無ければ `"$(git rev-parse --git-common-dir)/attention/my-turn/<番号>.json"`（/attention:my-turn-deep の記録）を使う。在らなければ、/attention:my-turn-deep を先に回すよう言って止まる（依頼の行と目的を作る小さな Workflow はまだ無い）。
2. 下ごしらえを打つ: `steps-prep.py --next world <番号> --record <記録>`。
   - 出力の JSON の `ok` が偽なら、`message` を言って止まる（`head-mismatch`: 作業場の head が記録の head と違う。`record`: 記録を読めない・別の PR の物。`no-lines`: 記録に仕組みの一覧が無い）。
   - `argsFile` が Workflow の args のファイル。`depsNote` が空でなければ、依存を全部のマニフェストから取った訳なので、報告に 1 行書く。
3. Workflow を起動して、ターンを終える。待ち続けない。
   - 既定の形: `argsFile` を読み、Workflow のツールを名前 `dig-world`（一覧に `attention:dig-world` と出ていればその名）で呼び、その JSON の値を args に渡す。convergence-loops の `blind-judge`（ツールを持たず、渡された問いだけから考える役）が使えるなら、args に `"blindJudge": "convergence-loops:blind-judge"` を 1 つだけ足してよい（`sum` に入らない）。終わりの知らせが来たら、知らせの出力のファイルを渡して `steps-prep.py --save world <番号> <出力のファイル>` を打つ。
   - ヘッドレスの形: Bash の run_in_background で `steps-headless.py world <番号>` を打つ（`--budget-usd` の既定は 40。走らせるアカウントの設定のフォルダは `--config-dir`。`nohup` や `&` で切り離さない）。終わりの知らせが来たら、台本が出した 1 行の JSON を読む。`saved` が null なら、`message` と `output`（`claude -p` の出力のファイル）の中身を言って止まる。
4. Workflow のツールが無い・呼べないなら、その訳を言って止まる（`/config` の Dynamic workflows を入れるか、`--headless` で打ち直す）。返った値に `stopped` が在れば、Workflow が途中で止めたので、その値と訳を言って止まる。
   - `caller`: この手順からの起動の合図が無い。
   - `sum`: args が下ごしらえの出力から変わった。2 から打ち直す。
   - `args`: 入力が足りない（`missing` の一覧）。
   - `leak model equals restate model`: 言い直しの段と、その漏れを照合する段が同じモデルになった。
5. 保存した `<番号>-steps/world.json` を読み、持ち主に報告する。報告は日本語。
   - 頭に、`differs`（PR の解き方が世の中の解と違う）の比べを、層（`architecture`: 誰が何をするか・`contract`: 境界を何が渡るか・`implementation`: 1 つの部品の中のやり方）ごとに並べる。1 件ずつ、依頼の行（`where`）・比べた相手（`against`）・世の中の解（`practice`）・問い直し（`challenge`）・根拠（`sources` の URL。`basis` が `knowledge` なら「抜き書きの照合なし」）。
   - 次に、`same`（PR の解き方が世の中の解と同じ）と `none`（比べる物が無い。依頼の行が解き方を持たないか、世の中の解が見つからなかった）の件数と、`missing`（返らなかった依頼の行と訳）を書く。黙って落とさない。
   - `restate_unchecked` が空でない行（言い直しの 3 回で、機械と 2 人目の読み手の検査に通りきらなかったが、柔らかい問題だけが残ったので、その直近の答えで比べた行。`restate_unchecked` は残った問題の文の一覧）は、依頼の行（`where`）と残った問題を 1 行ずつ書く。その行の比べは、依頼の行の言い直しに、解き方そのものを指す語（手段の語）が残るなど、問題が解き方を前提にした形のまま探した物なので、確かさが下がると添える。
   - 最後に、抜き書き（`excerpts`）の残った・落ちた・照合できなかった数を書く。`reason`（` / ` で区切った訳の並び）が空でなければ、`status` が `ok` のときも 1 件ずつ書く。`ok` でも、抜き書きを照合できなかった類（`<類の id>: excerpts not checked (<訳>)`。取り直しの台本が 2 回とも打たれなかった）や、取り直しがどのページにも届かなかった類が載る。照合できなかった類の行は、根拠の印が `knowledge`（抜き書きの照合なし）になる。
