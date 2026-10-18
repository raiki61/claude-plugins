# works: 入れる（1 回だけ）と、入ったかの確かめ

/works のスキルの本文（このフォルダの 1 つ上の SKILL.md）から指される別ファイルで、初めて入れる時と、`check` か `start` が足りない物を並べて止まった時に読む。殻・run・役などの語は SKILL.md の「語」に在る。命令の頭の `<works の置き場>` は、SKILL.md の「命令」の行の `${CLAUDE_PLUGIN_ROOT}` と同じ物（入れたプラグインの置き場の絶対パス。SKILL.md では置き換わって見える）で読み替えて打つ。

要る物: macOS（Apple silicon。Archon は固定した版の darwin-arm64 の実行ファイル）・git・uv・gh（初回に Archon の実行ファイルを GitHub の release から落とす）・Claude Code の `claude`・認証（普段の `claude` のログインで足りる。殻は次の 3 段の順に拾う。1) 環境変数 `WORKS_KEYCHAIN_ITEM` の値を名にした keychain の項目。2) 共有の認証の部品の段（受け継いだ `CLAUDE_CODE_OAUTH_TOKEN` など・環境変数 `CLAUDE_KEYCHAIN_SERVICE` の値を名にした keychain の項目・Claude Code の設定の置き場から導く `claude-code-oauth-<名>`。名は `~/.claude` なら `default`、`~/.claude-p3` なら `p3`）。3) Claude Code 自身が macOS の keychain に置いた項目（項目の名は Claude Code の設定の置き場 `CLAUDE_CONFIG_DIR` から導く）。この順に、あなた自身の認証だけを拾い、拾った出どころの名を出す。普段のログインで拾う項目は数時間で切れる短い物なので、長い run には `claude setup-token` で作るトークンを `CLAUDE_CODE_OAUTH_TOKEN` か `WORKS_KEYCHAIN_ITEM` の項目に置く）。run の中の gh はあなたの gh のログインを継ぐ（トークンは gh 自身の置き場のまま。並行 PR の確かめ（対象に同時に開いている PR とぶつからないかの確かめ）が run の中で gh を打つ）。AI の役は包み（役の `claude` を起こす Claude の包み `claude-adapter`）が gh を読む形だけに絞り、PR への投稿・`git push` を拒む（事故の柵で、堅い境ではない）。git の資格は渡さない。あなたの gh がログインしていなければ、並行 PR の確かめは人に回る。

1. プラグインを Claude Code に入れる。このスキル（works）と、works の run の中の AI の役が使うために借りる、ほかのプラグイン 2 つ（gates の文書の初見検査のフック・pr-review-toolkit の agent）。借りる 2 つは works の依存なので、works を入れると一緒に入る。ただし依存の marketplace（raiki61・claude-plugins-official）が先に足されていないと入らず、works は「will not load without it」と言って読まれない。だから marketplace を 2 つ足してから works を入れる。起動の殻 `dev/use.sh` と pack は works のプラグインの中に在り、Claude Code が入れたプラグインの置き場から使う。gates・pr-review-toolkit は、入った版をそのまま使う。superpowers のスキルは works に写した固定の版（`.shared/borrow/superpowers/<版>/`）を使うので、入れなくてよい（入れてあっても run には使わない）。リポジトリの clone は要らない。

   打つのは SKILL.md の「命令」の頭の 3 行（`claude plugin marketplace add` で marketplace を 2 つ足し、`claude plugin install works@raiki61` で works を入れる）。

2. 対象リポジトリ（直したいリポジトリ）で、AI を起こさずに確かめる（費用なし）。

   打つのは SKILL.md の「命令」の `check` の行（`sh "<works の置き場>/dev/use.sh" check <対象リポジトリ>`）。

   uv・claude・認証・対象の条件で足りない物があれば、入れ方つきで全部並べて 0 以外で終わる。最後の行が `Results: 1 valid, 0 with errors, …` なら入っている。その上に出る `WARNING [skills]` の 3 行（`code-review`・`simplify`・`security-review`）は Claude Code に組み込みのスキルで、出てよい。gates・pr-review-toolkit のどちらかが入っていない（か、works が名前で使う agent・hook が無い）と、`toolset.py: 借りる物が足りない` の下に足りない物ごとの 1 行と入れるコマンドを出して止まる。そのコマンドで入れてから打ち直す（`start` も AI を起こす前に同じ所で止まる）。`superpowers の写し（…）が borrow.json の pin と合わない` の行が出たら、works のプラグインの中の superpowers の写しが壊れているので、`claude plugin install works@raiki61` で works を入れ直す。

`archon plugin install` で pack を入れて Archon を直に打つ形は、今の works の版では使わない。AI の役が利用者の本物の `~/.claude`（CLAUDE.md・hooks・プラグイン）を読んでしまうため。`use.sh` は Archon を隔離した家で起こし、役には選んだ物だけの設定を読ませる。
