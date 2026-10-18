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
