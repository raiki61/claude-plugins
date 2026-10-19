# review-loop のツールと正本の場所（始める前に 1 度読む）

## ツールと正本の場所

- **スクリプト**: プラグイン同梱。以降 `review-record.py` / `comment-ratio.sh` と書いたものは `${CLAUDE_PLUGIN_ROOT}/scripts/` 配下を指す（実行例は P4 と P-R の R1 に書いてある）。
- **ラウンド記録**: `.claude/review-rounds/round-<N>.json`。**書き方の実例は `${CLAUDE_PLUGIN_ROOT}/templates/round-1.example.json`〜`round-3.example.json`**（3 つ並べて読むと、問いが立って・ループが決めて・人へ回るまでの 3 周の推移が分かる。フィールドと値の正本は `review-record.py`）。`<N>` は 1 から 1 ずつ増やす**ラウンド番号**（P4 の「1ラウンド = P1→P4 を1周」の定義に一致させろ）。ディレクトリは無ければ作れ（`mkdir -p .claude/review-rounds`）。**前ラウンド分を消すな**——連続 2 ラウンドの突合・defer 台帳・問いの台帳がこれで成立している。**同じリポジトリで次のレビューを始めるときは、前のレビューの記録を消さずに別ディレクトリへ退避しろ**（例: `.claude/review-rounds/archive-<前の BASE>/`。下位ディレクトリは読まれない）。ツールはディレクトリの中の `round-<N>.json` を全部読むので、基準点の違う記録が混ざっていると 1 ラウンド目から `exit 2` で止まる。実測: このプラグイン自身のレビューで、8 月の別レビューの記録 5 件が残っていて止まった。
- **レビュー観点の正本**: `${CLAUDE_PLUGIN_ROOT}/REVIEW.md`（言語・フレームワークに依存しない観点）。対象リポジトリのルートに `REVIEW.md` があれば**それも読み、そのチームが事故から足した固有の追加観点として併用しろ**。無くても走る。**観点の写しをこの手順書に持ち込むな**（二重管理は片方が stale 化する）。
- **役割 agent**: subagent はプラグイン同梱の役割定義で起動する。以降 `inspector` / `investigator` / `cold-reader` / `judge` / `blind-judge` と書いたものは `subagent_type: convergence-loops:<役割>` を指す。モデル・effort・持てるツールは `${CLAUDE_PLUGIN_ROOT}/agents/<役割>.md` が正本で、**この手順書にモデル名を書くな**（写しは腐る）。遮断系（`cold-reader` / `blind-judge`）はツールを一切持たないので、読ませたい本文はプロンプトに貼って渡せ。**ただし「道具を持たない」ことは遮断の保証ではない**——ハーネスは Agent ツールで起動した subagent に CLAUDE.md 階層を注入し、それを止める設定が公式に存在しない（code.claude.com/docs/en/sub-agents、2026-09-12 取得: 『Explore and Plan are the only subagents that omit CLAUDE.md and git status. There is no frontmatter field or per-agent setting to change which agents skip them.』）。実測 2026-09-12: ツールゼロの `cold-reader` が利用者の CLAUDE.md の 1 項目を逐語で引用した。設定ごと外せるのは CLI（`claude -p --setting-sources ""`）だけなので、**判定の独立と CLAUDE.md の非流出が要る場面では、このコマンドの遮断は『ツールの不在ぶんだけ』と読め**（機械が外す形は graphloops の cli モード＝`/research-graph` に在る）。**Read を持つ役（`inspector` / `investigator` / `judge`）には貼るな——本文をファイルに落として path を渡せ**（`git diff` や `cat` の出力を自分の文脈に出さず `> file` に落とす）。回す側の文脈を通る本文は読む・貼るで 2 回数え、圧縮で失われる。自分が既に受け取った返答を次の役や次の手順に貼り直すのも同じ——置き場の path と 1 行の要約で指し、要る所だけ読み直せ。どの役も書くツール（Edit / Write）を持たないが、`investigator` だけは Bash を持つ——起動する `investigator` のプロンプトには一人称の自己禁止（「ファイルの作成・編集・削除を自らに禁じる」）を書け。書き換えを塞ぐのは定義でも自制でもなく、P1 前後の作業ツリー突合（P1「局所」の項）である。
- **固有の規約**: どちらの `REVIEW.md` にも書かせず、対象リポジトリの一次情報（README・lint 設定・パッケージマニフェスト・CI 定義・近傍コード）から毎回把握しろ——手順は `REVIEW.md`「固有規約の把握」のとおり。**固有の技術名を観点側に書き写した時点で、それは複製で、リポジトリが変わっても古いまま残る。** 把握した内容は次ラウンドへ**参照として**引き継いでよいが、**文脈遮断 grader（P1）と R2（P-R）には渡すな**——渡した時点で隔離が壊れ、「このリポジトリではこうなっている」を所与にした追認になる。疑う役の入力は、対象差分と観点本文だけに保て。

## 依存

局所レビューに使う `pr-review-toolkit` は `plugin.json` の `dependencies` で宣言してあり、このプラグインの導入時に実体ごと入る（機構と入手経路の制約は `README.md`「依存と入手経路」が正本）。**導入コマンドを手順として実行するな**——宣言が解決できない環境ではこのプラグイン自体がロードされないので、`/review-loop` が動いている時点で `review-pr` は在る。

`/simplify` と `/security-review` は Claude Code 本体の組み込みなので、導入は要らない。

`review-pr` の呼び出し自体が失敗したら（権限・実行時エラー）そこで止めるな。素材 `local_review` を `awaiting_human` として記録し理由を書いて進め——**無かったことを `not_applicable` にするな。**
