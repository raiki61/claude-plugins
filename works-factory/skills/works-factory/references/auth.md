# 認証の道と「認証が無い」で止まった時

殻（このプラグインの `bin/works-factory`。スキルの `WF`）が工場の中の AI の役（子のプロセスの claude。以下「子」）を起こす時に使う Claude の認証の選び方と、止まった時の直し方。Archon は工場が載る外の実行基盤。要求の同時数の上限と、会話のキャッシュの寿命の変え方もここに置く。

## ログインか keychain の項目で動く人

- 普段の `claude` と `gh` のログインのまま動く。Claude のアカウントを macOS の keychain の項目で選ぶ時は、`WORKS_FACTORY_KEYCHAIN_ITEM=<項目の名>` を付ける（値は表示も保存もしない）。
  - 毎回付けずに済ませるなら、使う Claude Code の設定の置き場（既定は `~/.claude`）の `settings.json` の `env` に `WORKS_FACTORY_KEYCHAIN_ITEM=<項目の名>` に当たる組を書く。Claude Code が Bash の子に渡すので、殻がそのまま拾う。
  - `CLAUDE_KEYCHAIN_SERVICE`（Claude Code 側の、keychain の項目の名を入れる変数）に項目の名を置いても拾う。
  - ログインの資格は数時間で切れる。長い run（工場の 1 回の実行）は、`claude setup-token` で作ったトークンを `CLAUDE_CODE_OAUTH_TOKEN` に置いて起こす。
  - 殻が「認証が無い」で止まったら、macOS では `security find-generic-password -s <項目の名>` で項目が在るかを確かめる（`-w` を付けず、値を出さない）。項目の名を推して試さず、人に聞く。`security` は macOS のコマンドで、ほかの OS には無い。

## API キーかゲートウェイで動く人

- キーを環境変数 `ANTHROPIC_API_KEY` に置いて起こす（`ANTHROPIC_AUTH_TOKEN` も同じく拾う）。ゲートウェイを通すなら `ANTHROPIC_BASE_URL` も置く。どちらも殻を起動する環境か、下の Claude Code の設定の `env` に置く。
- Claude Code の設定の `env`（利用者の `settings.json`、その上に会社が配る managed settings のファイル）に書いた接続の値は、子に運ばれる: 接続先・資格・proxy・証明書・モデルの別名（`ANTHROPIC_DEFAULT_*_MODEL`）と、選んだ provider（Bedrock・Mantle・Vertex）の決まった名の変数。設定の `env` に書いた直の資格（`ANTHROPIC_API_KEY`・`ANTHROPIC_AUTH_TOKEN`）は環境の物より勝つが、provider を選んだ時は運ばれない。hook・permissions・プラグインは運ばれない。
- Bedrock・Mantle・Vertex は、`CLAUDE_CODE_USE_BEDROCK`・`CLAUDE_CODE_USE_MANTLE`・`CLAUDE_CODE_USE_VERTEX` を殻を起動する環境か設定の `env` に置く（両方に在れば環境が勝つ）。環境で選んだ時は、設定の `env` のほかの接続の値は運ばれず、殻が標準エラーに名だけを 1 行出す。殻が止まる場合（設定の `env` で Foundry を選ぶ・資格のファイルを相対パスで書く・設定のファイルが壊れているなど）と、`~/.aws`・gcloud の資格の渡し方は、[工場の README](https://github.com/raiki61/works-factory/blob/bb05cb34875b839ba14e02bb683e181b8e5070c7/README.md) の `WORKS_FACTORY_KEYCHAIN_ITEM` の次の項目に在る。
- 殻は「認証は ANTHROPIC_API_KEY から拾う」と出して、そのキーで AI の役を起こす。
- 上の `WORKS_FACTORY_KEYCHAIN_ITEM=<項目の名>` は付けない。付けると殻はその項目のログインを使い、`ANTHROPIC_API_KEY`・`ANTHROPIC_AUTH_TOKEN`・Bedrock や Vertex の設定を子から外す。API キーの入った項目を名指しても読めずに止まる。

## apiKeyHelper で動く人

`apiKeyHelper` は、Claude Code の設定で API キーを標準出力に返すコマンドを書く欄。

- 殻が読む設定は、会社が配る設定のファイル（managed settings。macOS は `/Library/Application Support/ClaudeCode/`、Linux と WSL は `/etc/claude-code/` の `managed-settings.json` の後に `managed-settings.d/*.json` を名前順に読み、後に読んだファイルが勝つ。読む権限の無いファイルは Claude Code と同じく飛ばす）が先で、そのどれにも `apiKeyHelper` の欄が無ければ利用者の `settings.json`（`CLAUDE_CONFIG_DIR`、無ければ `~/.claude`）。対象のリポジトリの `.claude/settings.json` は読まない。
- 殻は起動ごとに 1 回、Archon を起こす直前にそのコマンドを利用者の HOME・XDG・`CLAUDE_CONFIG_DIR` で起こし、出たキーを `ANTHROPIC_API_KEY` として中の AI の役に渡す。キーは表示も保存もしない。コマンドの待ちに期限は無い（止めるのは Ctrl-C）。コマンドの標準エラーは端末に流れる。
- `apiKeyHelper` が在る時は、保存済みの Claude Code のログインへ落ちない。コマンドが失敗した時・設定のファイルが JSON として壊れている時・`apiKeyHelper` の値が文字列でない時は、それを名指して止まる。
- 環境に置いた `ANTHROPIC_API_KEY`・`ANTHROPIC_AUTH_TOKEN`・Bedrock か Vertex の設定、`WORKS_FACTORY_KEYCHAIN_ITEM`、`CLAUDE_KEYCHAIN_SERVICE` は `apiKeyHelper` より先に使われる（環境の `CLAUDE_CODE_OAUTH_TOKEN` だけは `apiKeyHelper` より後）。
- 会社の設定を remote（claude.ai の server-managed settings）か MDM（構成プロファイル・レジストリ）で配っている機械では、殻はそれを読まない。そういう機械の Claude Code は会社の設定のファイルの `apiKeyHelper` を使わないのに、殻はファイルの物を使うので、普段と違うキーで工場が動きうる。その時は `ANTHROPIC_API_KEY` を環境に置いて起こす。
- キーは起動の時に 1 回だけ取り、run の間ずっと同じ値を使う（Claude Code 自身は 5 分ごとと 401/403 の時に起こし直すが、殻はしない）。期限の短いキーを出すコマンドだと、長い run の途中で認証が切れうる。その時は長く使えるキーを `ANTHROPIC_API_KEY` に置いて起こす。

## キーが同時に受ける要求の数が少ない時

- 工場は 1 回の run の中で AI のノードを並べて起こす（判定の段は観点のノードを一度に最大 11、修正の段は組を同時に最大 5 つ）。同時に受ける要求の数が少ないキーやゲートウェイだと、余った要求に 429 が返ってノードが落ちる。
- その時は `WORKS_FACTORY_CLAUDE_CONCURRENCY=<1 以上の整数>` を付けて殻を起こす。Archon が上限を超えた要求を空きが出るまで待たせる。1 以上の整数でない値は Archon を起こす前に止まる（空の値は付けていないのと同じ）。
- 上限は、殻が対象ごとの Archon の家（`$WORKS_FACTORY_HOME/archon-home`、`WORKS_FACTORY_HOME` が無ければ `${XDG_STATE_HOME:-~/.local/state}/works-factory/targets/<対象のパスから作る 16 進 8 桁>/archon-home`）の `config.yaml` に書き込み、消すまで残る。付けずに起こした続きの命令（`WF workflow resume`・`WF workflow approve` など）も消さない。動いている run にもすぐ効く。効いている時は `claude の同時数の上限 <n> が効いている（<config.yaml のパス>）` の 1 行が出る。外すには、その行が名指した `config.yaml` から `concurrency.providers.claude` の行を消す。`config.yaml` が Archon の `ai tier set` などで 1 行の `{...}` の形に書き換わっていると、変数を付けた起動は止まる。その時は `concurrency: {providers: {claude: <n>}}` を手で書くか、変数を付けずに起こす（どちらも上限を置く・残す手で、外す手ではない）。
- 上限が数えるのはその家を通る要求だけ。同じキーを使うほかの会話・ツール・ほかの対象の run の要求は、上限に数えられずにキーの枠を食う。上限 1 なら、ほかの要求が 1 つでも在れば 429 に当たる。ほかの使い手を止めるか、run に専用のキーを渡す。
- それでも 429 で落ちたノードはrun の報告（`report.md`）に名前と誤りの 1 行目が出る。修正の段は組ごとに下位の run（子の run）を起こすので、その中で落ちた物は報告に 429 の字が出ず、子の run を起こしたノードの英語の失敗の文だけが出る。429 かは `WF workflow status` と家の下の run の記録で見る。

## 残ったログイン

- 既定の設定の置き場（`~/.claude`）に Claude のログインが残っていると（macOS は keychain、Linux は `.credentials.json`）、キーも `apiKeyHelper` も `WORKS_FACTORY_KEYCHAIN_ITEM` も `CLAUDE_CODE_OAUTH_TOKEN` も無い時は止まらずにそのログインのアカウントで起こす。殻の出す「認証は … から拾う」の行で確かめる。

## 会話のキャッシュの寿命を変える時

- 工場は、中の AI の役の会話のキャッシュの寿命を既定で 5 分にする（殻が、Archon の run ごとの設定〔`--config` と同じ層〕の `env:` に `CLAUDE_CODE_PROMPT_CACHE_TTL=5m` を載せる）。Claude の加入（Pro・Max など）でログインした人では Claude Code の既定は 1 時間で、1 時間のキャッシュは書き込みが 5 分の物の 2 倍の単価で、使用枠を多く使う。工場の役の会話は要求の間が 5 分を超えることが少なく、1 時間にしても得にならないため、5 分にする（[工場の docs/design/archon.md](https://github.com/raiki61/works-factory/blob/bb05cb34875b839ba14e02bb683e181b8e5070c7/docs/design/archon.md)）。API キーの人の Claude Code の既定は元から 5 分。
- 寿命の値は `5m` か `1h`（Claude Code はほかの値を無視する）。変えるには、殻に渡す `--config <YAML のファイル>` か、修正を頼むリポジトリの `.archon/config.yaml` の、いちばん上の `env:` に書く（どちらも同じ run の設定の層に入る）。ほかの場所では変わらない。そこに寿命の変数が在れば、工場の 5 分は載らない。1 時間に戻すなら `env:` の下に `ENABLE_PROMPT_CACHING_1H: '1'`。`CLAUDE_CODE_PROMPT_CACHE_TTL`・`FORCE_PROMPT_CACHING_5M` も書ける。
- 次に書いた寿命は効かず、工場の 5 分が勝つ: 殻を起動する環境（`CLAUDE_CODE_PROMPT_CACHE_TTL=1h WF workflow run ...` の形。Archon が役に渡さない）、対象の `.archon/.env`、Claude Code の設定の `promptCacheTtl`（会社が配る managed settings の物も）、Archon の DB に保存した、対象のリポジトリごとの環境変数の設定。
- `--adopt`（前の run を引き継ぐ起動）は工場の 5 分を載せない。PIN が 99b6cfdb より前の工場で始めた run を `resume` で続けると、寿命はその時のまま。
