# tiers の決めたこと

tiers（プラグインが要る外のツールがそろっているかを点検し、入れ方を出すプラグイン）の決めたことと、その根拠の記録。tiers を直す人・つなぐ人向けで、使うだけなら読まなくてよい。使い方と、段（要るツールを 0〜3 に分けた区切り）・herdr・起動コマンドの意味は [README](../README.md)。

設計の正本は、このリポジトリ（claude-plugins）のルートの `docs/specs/2026-10-16-company-shape-design.md` の 4.11（要るツールの段と、点検と準備）。世間の形の調べ（拡張の土台は、同じ土台の上の別の拡張への依存はフィールドで宣言させるが、gh のような個別の外のツールを要る物として宣言するフィールドは、調べた範囲では持たない。点検のコマンドは `flutter doctor`・`brew doctor`・Neovim の `:checkhealth` の形）の原典は、[Claude Code の Plugin dependencies](https://code.claude.com/docs/en/plugins/dependencies)・[Plugin manifest reference](https://code.claude.com/docs/en/plugins/manifest-reference)・[Agent Skills の仕様](https://agentskills.io/specification)・[MCPB の MANIFEST.md](https://github.com/modelcontextprotocol/mcpb/blob/main/MANIFEST.md)・[gh extension](https://cli.github.com/manual/gh_extension)・[VS Code の Extension Manifest](https://code.visualstudio.com/api/references/extension-manifest)・[Neovim の health](https://neovim.io/doc/user/health/)・[flutter の CLI](https://docs.flutter.dev/reference/flutter-cli)・[Homebrew の Formula Cookbook](https://docs.brew.sh/Formula-Cookbook) と [Manpage](https://docs.brew.sh/Manpage)・[npm の package.json](https://docs.npmjs.com/cli/v12/configuring-npm/package-json/)・[Debian Policy の 7 章](https://www.debian.org/doc/debian-policy/ch-relationships.html)・[pyproject.toml の仕様](https://packaging.python.org/en/latest/specifications/pyproject-toml/)（2026-10-16 に読んだ）。

## 段 2 の案内

段 2 は、初めての人が自分で準備できるように、足りない項目にだけ、入れ方のコマンドに加えて案内（`guide`）も返す（そろっている項目には出さない）。中身は次の 3 つ。

- herdr が無い: OS ごとの入れ方の補い（Linux・macOS は、インストーラが herdr を `~/.local/bin` に置くこと（環境変数 `HERDR_INSTALL_DIR` で替えられる）と、ほかの入れ方の Homebrew・mise・Nix。Windows は WSL を通さないネイティブで一般提供であること、ARM64 は x86_64 の版をエミュレーションで動かすこと、インストーラが版ごとのフォルダを `%USERPROFILE%\.herdr\packages\standalone\releases` の下に置き、今の版のフォルダを PATH に入れること、エンドポイントのセキュリティが PowerShell のインストーラを止めたときにコマンドプロンプトで `https://herdr.dev/install.cmd` を落として走らせる入れ方、GitHub の releases から手で落とす zip は中の `herdr.exe` だけを写さず展開したフォルダごと置くこと。同じフォルダに在る、Windows の疑似端末の仕組み ConPTY の実行時のファイルが要る。このファイルは点検しない）と、Claude Code の連携（`herdr integration install claude`。Claude Code の会話を herdr に知らせるフックを、Claude Code の設定のフォルダ（既定は `~/.claude`）に足す。アカウントごとに設定のフォルダを分けているなら、フォルダごとに、そのフォルダを指す環境変数 `CLAUDE_CONFIG_DIR` を替えて入れる。連携が入っているかは点検せず、案内に出すだけ）。
- herdr が入っているが server が動いていない: 入れ方のコマンドは「作業するフォルダで `herdr` を打って起動する」。案内は、herdr を初めて起動すると herdr 自身が初回の案内（onboarding）を出し、進めると設定の integrations のタブから連携を入れられることと、上と同じ連携の案内。
- 起動コマンドが見つからない（`--launcher` で渡したコマンドが見つからなければ、足りない物に数える）: 先に「アカウントが 1 つならコマンドは作らなくてよい（`--launcher` を省けば `claude` だけを見る）」と書き、分けるなら、アカウントごとに設定のフォルダを分けて `CLAUDE_CONFIG_DIR` に入れて `claude` を起動する関数か別名を、bash・zsh・PowerShell の 3 つで示す。名前（`claude-p2`）とフォルダ（`~/.claude-p2`）は例で、点検は `--launcher` で渡された名前を探すだけで決め打ちしない。

根拠は、herdr の v0.9.5 の文書とソース（2026-10-16 に読んだ。[install](https://raw.githubusercontent.com/herdrdev/herdr/v0.9.5/docs/next/website/src/content/docs/install.mdx)・[windows-beta](https://raw.githubusercontent.com/herdrdev/herdr/v0.9.5/docs/next/website/src/content/docs/windows-beta.mdx)・[configuration](https://raw.githubusercontent.com/herdrdev/herdr/v0.9.5/docs/next/website/src/content/docs/configuration.mdx)・[integrations](https://raw.githubusercontent.com/herdrdev/herdr/v0.9.5/docs/next/website/src/content/docs/integrations.mdx)・[install.sh](https://herdr.dev/install.sh)・[src/integration/claude_settings.rs](https://raw.githubusercontent.com/herdrdev/herdr/v0.9.5/src/integration/claude_settings.rs)。v0.9.5 は読んだ版。点検は herdr の版の番号を見ないが、`herdr status server --json` の出力の形〔`running` と `socket` の鍵〕は 0.9.3 で読んだ物を前提にする）、Claude Code の環境変数の文書（`CLAUDE_CONFIG_DIR`）、PowerShell の `Set-Alias` の文書（別名は引数を持てないので関数にする）。

## 点検は入れ方を示して止まり、何も入れない

設計の 4.11 は「準備は、足りない物を入れる手順を案内する（手で入れる物は、入れ方を示して止まる）」とする。今の段のツールは、どれも手で入れる物と決めた。gh・herdr・Archon・Claude Code は OS にツールを入れる操作で、gh のログインはアカウントを結ぶ対話の操作だから、利用者に断らずに走らせてよい物が無い。Claude Code の文書が勧める「初めて使うときに確かめ、無ければ入れる」（hooks の文書の practical pattern）は、例が言語のパッケージ（`npm install`）で、OS のツールまで含むとは書いていない。自動で入れる物が出てきたら、項目の `manual` を false にして足す。

## 置き場: 共通のプラグインにし、各プラグインが `dependencies` で依存する

置き場の候補は 2 つあった。

1. 共通のプラグイン（tiers 自身）を 1 つ作り、各プラグインが `plugin.json` の `dependencies` で依存する。
2. このリポジトリの今の共有の形（`scripts/claude_auth.py` を各プラグインの中へ写し、`scripts/shared-copies.py` が写しの一致を CI で縛る）に載せ、点検の本文を各プラグインへ写す。

1 を選んだ。2 の形は、Claude Code のプラグインが入った後に自分のフォルダしか持たず、実行時に 1 か所を共有する道が無かった時（2026-09-15 の実測。記録は `scripts/shared-copies.py` の頭）の答えである。その後、依存として入れたプラグインの `bin/` が PATH に入ると確かめられたので（下の「試して確かめたこと」）、点検の本文を 1 か所に置いて呼べる。1 なら、点検の中身を直すと全部のプラグインに 1 回で効き、写しの割れを縛るチェックも要らない。人が走らせる入口（`/tiers:check`）も同じ所に置ける。設計の 4.11 が挙げる Neovim の `:checkhealth`（点検の枠を共有する）と `brew doctor`・`flutter doctor`（1 つのコマンドが環境を点検する）のうち、`brew doctor`・`flutter doctor` の形に近い。各プラグインの点検（works-dispatch の設定や `/catchup` のコマンドなど、そのプラグインだけが知る物）は、各プラグインが続けて持つ。

依存の範囲（`version`）は書かない。同じ marketplace の相対パスの依存は、タグが無くても marketplace の今の写しで入る。範囲を書くと、Claude Code は依存先の git のタグ（`<名前>--v<版>`）から範囲に合う版を探し、合うタグが無ければ今の写しで入れて、範囲は読み込むときに確かめる（外れていれば、呼ぶ側のプラグインが切られたままになる。[Plugin dependencies](https://code.claude.com/docs/en/plugin-dependencies) の「How a constraint resolves against tags」）。このリポジトリはタグを作らない（持ち主の決定）ので、範囲を書いても効くのは読み込むときの確かめだけで、tiers の版を上げたときに呼ぶ側が切られうる。呼ぶ側と tiers の版がずれうるので、 `--json` の形は `schema` の番号で守り、形を変えるときは番号を上げ、呼ぶ側は知らない番号を誤りとして扱う。フィールドを足すだけ（知らないフィールドを読まない呼び手がそのまま動く変え方。`guide` がそれ）は番号を上げない。上げると、`schema` が 1 であることを確かめる呼び手（このリポジトリの別のプラグイン works-dispatch が tiers を呼ぶ所 `dispatch/tierx.py`。[from-other-plugins.md](from-other-plugins.md)）が、足したフィールドを使わないのに止まる。

## 試して確かめたこと（2026-10-16、Claude Code 2.1.301、使い捨ての marketplace）

文書（Plugin dependencies と Plugin manifest reference）に書かれていない 2 点を、使い捨ての marketplace（手元のフォルダの git のリポジトリ）に、`bin/` とスキルを持つプラグイン `base` と、それに依存する `user` を置いて確かめた。隔離した `CLAUDE_CONFIG_DIR` に `claude plugin install user@<marketplace>` で `user` だけを入れると、`base` も依存として入った（`+ 1 dependency: base`）。その上で `claude -p` に次を走らせた。

- 依存として入ったプラグインの `bin/` は、Bash のツールの PATH に入る。PATH に `base/bin` が載り、`command -v base-probe` が見つかり、走った。
- 依存先のスキルは、依存する側の会話から `<依存先のプラグイン>:<スキル>`（例 `base:probe`）の名前で一覧に載り、Skill のツールで呼べた。

確かめていないこと（要確認）: GitHub から足した marketplace（キャッシュに写る形）でも同じか。Windows の Claude Code で、拡張子の無い `bin/tiers` を Bash のツール（Git Bash）から名前で起動できるか（Python の台本としては、試験が `python bin/tiers` の形で Windows の CI でも走らせる）。

## 常に載る文脈を 0 にする（2026-10-19）

持ち主の「tiers は全部うまいことコンテキストを食べずに設定できるか」を受けて、スキル `check` に `disable-model-invocation: true` を付けた。tiers が持つスキルは `check` 1 つで、コマンドもエージェントも持たないので、全部の会話に常に載るのはこのスキルの説明だけだった。Claude Code の文書の表（[Skills](https://code.claude.com/docs/en/skills) の「Control who invokes a skill」）は、この指定のスキルを「人は呼べる・Claude は自分では呼ばない・説明は文脈に載らない」とする。Claude Code 2.1.303 の本体でも、会話に載るスキルの一覧を作る所がこの指定の物を外していた。人は今までどおり `/tiers:check` で打てる。ほかのプラグインは `bin/tiers` を呼ぶので（このリポジトリの別のプラグイン works-dispatch〔作業ごとに Claude Code の会話を別に立てて仕事を頼むプラグイン〕の `dispatch/tierx.py`）、スキルの説明が無くても困らない。会話の中で点検が要るときは、Bash のツールで `tiers --tier N` を打つ（works-dispatch の `--check` が止まったときの案内にも、この形を書いた）。

`claude plugin details tiers@raiki61` が出す「Always-on」（常に載る文脈）の見積もりは、0 にならない（付けた後の見積もりは約 30 トークン。実際に載る量ではない。付ける前は約 47 トークン）。2.1.303 の見積もりはこの指定を見ず、名前と説明の長さだけから数えるためで、2.1.303 の本体で計算の所を読んだ。本当に載っているかは、会話の記録（`~/.claude*/projects/` の下の `.jsonl`）の `skill_listing` の行に `tiers:check` が在るかで見る。

採らなかった形:

- コマンド（`commands/`）に移す: コマンドもスキルと同じ一覧に説明が載り、文書もスキルの方を勧めている。
- スキルを消す: 人が `/tiers:check` で打てなくなる。
- 説明を短くする: 減るが 0 にならない。
- works-dispatch のスキルの中に移す: 載る所が移るだけで、0 にならない。

足した部品（statusline・`bin/tiers-statusline`・SessionStart のフック）は、どれも会話に字を出さない（フックは出力が空。`claude plugin details` も hooks を「harness-only — no model context cost」と出す）。

## 裏の処理の印（statusline。2026-10-19）

herdr（端末を作業場とペインに分けて並べ、中の AI の会話の状態を見せるツール）は、会話がターンを閉じて裏の処理（`run_in_background` の Bash・Monitor・裏で立てたサブエージェント）の終わりを待つ間、その会話を done（終わった）と見せる。持ち主は手元の 3 つのファイル（`~/.claude/statusline.sh`・`~/.claude/herdr-bg-hold.sh`・`~/.config/herdr/agent-detection/claude.toml`）で、画面の下に印「⧖ バックグラウンド作業中 N 本」を出し、herdr の判定ルールでその印を作業中と見分けさせていた。これを tiers の `statusline/` に移し、プラグインの版の管理と、直したプラグインを全アカウントに配るスクリプト（ルートの `scripts/spread-plugins.py`）に載せた。tiers に置いたのは、持ち主の「準備用のやつが入ってるとこに入れていい」による（準備用の物＝要るツールの点検と支度を持つプラグインで、それが tiers）。

決めたこと:

- **ツールで入れる。** プラグインは statusLine を入れられない（[plugins reference](https://code.claude.com/docs/en/plugins-reference) の settings: プラグインの `settings.json` で効くのは `agent` と `subagentStatusLine` だけ）。herdr の判定ルールも、手元の上書き（`~/.config/herdr/agent-detection/claude.toml`）に置くしかない。そこで `tiers-statusline setup` が、アカウントごとの `settings.json` の `statusLine` と herdr の上書きを書く。点検（`tiers`）は今までどおり何も入れず、段 2 で支度がそろっているかを見るだけ。
- **使うかは利用者が決める。** statusLine はアカウントに 1 つなので、プラグインを入れただけでは利用者の statusLine を押しのけない。`setup` を打ったアカウントだけ、前の `settings.json` を `.bak` で残して `statusLine` を書き替える。点検は、statusLine が tiers を指すアカウントだけ見る。
- **版が上がっても書き直さない。** プラグインの置き場は版ごとに替わり、置き場の名前に commit の印の物も混ざる（持ち主のアカウントの 1 つ p2 では `tiers/922c475075de`）ので、名前の並びで最新を選べない。SessionStart のフックが、会話を始めるたびに `${CLAUDE_PLUGIN_DATA}/current` を今の版（`${CLAUDE_PLUGIN_ROOT}`）へのリンクに張り替え、statusLine はリンクの下を指す（2 つの環境変数は [plugins reference](https://code.claude.com/docs/en/plugins-reference) の「Environment variables」）。`setup` は、リンクが無い間のために、`installed_plugins.json`（Claude Code の、入れたプラグインの記録）で user の範囲（アカウント全体に入れた物。`scope` が `user`）の置き場へ先に張る。
- **herdr の上書きは作って保つ。** herdr の上書きは配られたルールに足す物でなく丸ごとの置き換えで、在る間は配り直したルールが効かない（[herdr の agents](https://raw.githubusercontent.com/herdrdev/herdr/v0.9.5/docs/next/website/src/content/docs/agents.mdx)）。手元の上書きは 2026.09.11.1 のまま、herdr が配った 2026.10.11.1 を隠していて、配られた規則 `live_blocked_form_named_session`（名前を付けた会話の、答えを待つ入力のフィールドを待機と見分ける）が効いていなかった。そこで上書きは、herdr が取ってきた配られたルール（`~/.local/state/herdr/agent-detection/remote/claude.toml`）を写し、その後ろに tiers の足す規則 `statusline/claude-rule.toml` を付けて作る。statusline.sh は、配られたルールか足す規則の方が新しければ `tiers-statusline refresh` を裏で起動して作り直す。tiers の作った上書きは 1 行目の印（`# tiers-statusline が作った herdr の判定ルールの上書き。` で始まる）で見分ける。手で書いた上書きは、`setup` でだけ（`.bak` を残して）置き換える。
- **works-dispatch の印は外した（DRY）。** works-dispatch の Stop のフックも、部署の会話（works-dispatch が仕事ごとに立てる作業場で動く会話）の herdr の表示名に「・裏の処理待ち」を添えていた。statusline の印は、全部の会話に効く・herdr の状態そのものを作業中にする・30 秒ごとに描き直す・サブエージェントと Monitor も数える。表示名の字は、部署の会話だけ・ターンの終わりにだけ書き替わる。同じ事を 2 か所で出さないよう、表示名の字を外した。Stop のフックには、もう 1 つの働きがある。部署の会話が受けた頼みを納品（頼み元へ結果を返すこと）せずに止まろうとすると、止まるのを差し戻して納品を促す。裏の処理の数を見て、待っている間はこの差し戻しをしない所は残す（印でなく、差し戻すかの判定なので）。

採らなかった形:

- herdr の組み込みの字（「MCP tasks still running」など、配られた規則が作業中と見る字）を statusline に出して真似る: 規則を足さずに済むが、画面に事実でない字が出る。
- herdr に作業中を報告し続ける（`herdr pane report-agent` の繰り返し。元の `herdr-bg-hold.sh --hook`）: 2026-10-12 から herdr の Claude の連携が、会話の状態の報告元を `herdr:claude`（herdr 自身の Claude の連携）に登録し、報告元が違う報告を捨てる。
- statusLine のコマンドで、置き場の名前を並べて最新の版を選ぶ: 置き場の名前に commit の印の物が混ざり、古い版を選ぶ。
- 足す規則だけを配り、上書きは人が手で作る: herdr が配り直すたびに古くなる（今回の不具合の形そのもの）。

手元の 3 つのファイルは、プラグインの版で印が出るのを確かめるまで残す（消すかは持ち主に確かめる）。`~/.claude/herdr-activity.sh`（今見ている PR の番号を控えるフック）は、今回の移し替えの外なので手元に残る。

## フィードバックの下書きを切る設定（feedbackDrafts。2026-10-23）

tiers が段 2 でこの設定を点検し、書く側のコマンド `tiers-settings setup` を別に持つと決めた理由の記録。利用者がすること（足りないと出たら `tiers-settings setup` を打つか `/config` で切る）は README の「Account settings」。

Claude が SendFeedback のツールでフィードバックの下書きをためた会話は、`/exit` の前に送るか捨てるかの確認を出して止まる（[tools reference](https://code.claude.com/docs/en/tools-reference) の「SendFeedback tool behavior」: 「When you run /exit with drafts from the session still in the queue, Claude Code asks whether to review them or discard them before exiting.」）。2026-10-23 に、持ち主（このリポジトリの作者）の勤め先のリポジトリ guided-resolver で、works-dispatch（Claude Code の会話を作業ごとに開き、要らなくなった会話を `/exit` で閉じるプラグイン）が、自分の番でなくなった PR の会話を `/exit` で閉じられなかった。持ち主はフィードバックを送らないので、確認の画面に答える作りにせず、下書きをためない設定を前提の環境にして、その点検を tiers が持つ（持ち主の決め。works-dispatch の部署への頼み 20261023-043724-0b4b8b〔頼みのファイルの名前〕で決めた）。

- **何を見るか。** 各アカウントの `settings.json` の `feedbackDrafts` が `"off"` か（[settings reference](https://code.claude.com/docs/en/settings-reference) の feedbackDrafts: 範囲は User か managed〔管理者が配る設定〕、`"off"` で SendFeedback のツールが外れる）。環境変数の `CLAUDE_CODE_SEND_FEEDBACK=0` は 1 つの会話にしか効かず、`DISABLE_FEEDBACK_COMMAND=1` は人が打つ `/feedback` も止めるので見ない。
- **どのフォルダを見るか。** 段 2 の起動コマンドは、シェルの関数が `CLAUDE_CONFIG_DIR` を入れて claude を起動する物が多く、tiers からはフォルダが見えない。ログインの点検で打つ `<起動コマンド> auth status --json` の答えに `configDirectory` が在る（2.1.309 で見た。公式の文書には書かれていない）ので、そこから引く。無ければ足りない物として出し、`--config-dir` で渡す手を示す（`--config-dir` を渡したときは、どのフォルダの物かは引けないので、渡したフォルダを見たことで通す）。管理者の managed settings はアカウントの値より先に効くが、点検は読まない（持ち主の手元に無く、置き場が OS と配り方で分かれるため）。`--config-dir` で渡したフォルダも見て、同じフォルダは 1 つにまとめる。
- **段。** 外から会話を閉じるツール（works-dispatch）の前提なので、起動コマンドを見る段 2 に置いた。
- **書く側を statusline の setup と分けた。** `tiers-statusline setup` は、使うかを利用者が決める statusLine を書く（アカウントに 1 つの statusLine を押しのける）。feedbackDrafts は段 2 の前提で、statusLine を使わないアカウントにも要る。相乗りさせると、片方だけ欲しい人が書けない。そこで `tiers-settings setup` を別に置き、`.bak` の残し方と書き方（`tiers_statusline.backup`〔前の `settings.json` を `settings.json.bak.<日時>-tiers` に写す〕・`write_file`〔ファイルを書く〕）は同じ物を使う。ほかのキーは残し、`feedbackDrafts` だけを足すか書き換える。打つのは利用者で、点検は書かない。

## 選択肢の画面で問うツールを外す設定（permissions.deny の AskUserQuestion。2026-10-23）

上の feedbackDrafts と同じ作り（段 2 の点検は読むだけ・書くのは `tiers-settings setup`）で、2 つ目の設定を足した理由の記録。利用者がすることは README の「Account settings」。

Claude が AskUserQuestion のツール（選択肢の画面で問う）で問うと、その問いは答えるまで開いたまま（[tools reference](https://code.claude.com/docs/en/tools-reference) の「AskUserQuestion tool behavior」）で、会話は窓を開いてキーを押すまで進まない。2026-10-23 に guided-resolver の issue #1895 で、works-dispatch が開いた会話がこの画面で止まり、窓口の会話（持ち主と話し、ほかの会話に仕事を配る会話）からは答えられなかった。持ち主は、手で起動する会話も含めて全アカウントでこのツールを使えなくすると決め、tiers の前提にも入れると決めた（works-dispatch の部署への頼み 20261023-054557-7a51b7）。tiers はほかの人にも配る。段 2 の点検がこの設定を求めると、tiers を使う人は点検を通すために自分のアカウントでもこのツールを外すことになり、画面の前で選択肢から選べる問い方を手放す。この見立ては持ち主が聞いたうえでの決め。

- **何を見るか。** `settings.json` の `permissions.deny` の並びに、括弧の付かない `"AskUserQuestion"` が在るか。tools reference は、ツールの名前を権限の決まりに書く字そのものとし、決まりの書き方の表に無いツールは括弧の付かない名前だけを受けると書く。括弧付きの `AskUserQuestion(...)` は通さない。
- **書き方。** `tiers-settings setup` が、並びの末尾に足す（既に在れば触らない）。ほかの deny・allow などは消さない。設定のファイルごとの並びは置き換えでなく合わさる（[settings](https://code.claude.com/docs/en/settings) の「Lists merge instead of overriding」）ので、ほかの場所の deny とも食い違わない。`permissions` が JSON のオブジェクト（`{...}`）でない（並びや文字など、型が違う）か、`deny` が並び（`[...]`）でない `settings.json` は、何をどう直すべきか機械では決められないので、setup は何も書かずに止まる。点検はその項目の直し方の 1 行目に「その形を手で直してから」を出し、2 行目から setup のコマンドと手で書く場所を出す。中身の在る `permissions` や空の `permissions` は型が合っているので止めず、`deny` を足す。feedbackDrafts と 1 回の setup で書き、`.bak` は 1 つ残す。
- **採らない方。** `askUserQuestionTimeout`（答えないまま置いた問いを閉じる設定）は、裏の会話（`--bg`）では時計が動かない（同じ tools reference の「Question auto-continue timeout」）。works-dispatch の部署は裏の会話なので効かない。

