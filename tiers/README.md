# tiers

プラグインが要る外の道具（Claude Code・gh・herdr・Archon など、利用者の PC に別に入れる道具）を段に分けて点検し、足りない物と入れ方を返す、共通の部品のプラグイン。何も入れない。ほかのプラグインが依存として入れ、使い始めに呼ぶ。人は `/tiers:check` で同じ点検を走らせる。

設計の正本は、このリポジトリ（claude-plugins）の根の `docs/specs/2026-10-16-company-shape-design.md` の 4.11（要る道具の段と、点検と準備）。世間の形の調べは、持ち主のノートのリポジトリ my_notes の `reference/secondary/architecture/extension-hosts-declare-sibling-extensions-but-not-individual-outside-tools.md`。

変更の記録: [CHANGELOG.md](CHANGELOG.md)。

## 段

上の段は下の段を含む（段 2 を点検すると段 0 と段 1 も点検する）。

- 段 0: Claude Code だけ。`claude --version` が通るか。
- 段 1: gh（GitHub の CLI）。入っているか（`gh --version`）、ログイン済みか（`gh auth status`）。
- 段 2: herdr（端末を作業場ごとに分けて、中の AI の会話を外から操作できる道具）。入っているか（`herdr --version`）、server が動いているか（`herdr status server` の `status: running`）。それと、アカウントの起こし方の命令（`--launcher` で渡す。省けば `claude`）が、利用者のログインのシェルで見つかるか（Linux・macOS はログインのシェルの `command -v` で探し、シェルの関数と別名も数える。Windows は PATH の上を探し、無ければ PowerShell の起動時に読む設定のファイル `$PROFILE` に書いた関数（と別名）を、PowerShell の `Get-Command` で探す）。
- 段 3: Archon（AI の工程を順に回す道具）。`archon` が PATH に在るか。

足りない物ごとに、入れ方を返す。入れ方の命令は各道具の公式の README の install の節から写した（2026-10-16 に読んだ。OS ごと: macOS・Linux・Windows）。

段 2 は、初めての人が自分で準備できるように、足りない項目にだけ、入れ方の命令に加えて案内（`guide`）も返す（そろっている項目には出さない）。

- herdr が無い: OS ごとの入れ方の補い（Linux・macOS は、インストーラが herdr を `~/.local/bin` に置くこと（環境変数 `HERDR_INSTALL_DIR` で替えられる）と、ほかの入れ方の Homebrew・mise・Nix。Windows は WSL を通さないネイティブで一般提供であること、ARM64 は x86_64 の版をエミュレーションで動かすこと、インストーラが版ごとのフォルダを `%USERPROFILE%\.herdr\packages\standalone\releases` の下に置き、今の版のフォルダを PATH に入れること、エンドポイントのセキュリティが PowerShell のインストーラを止めたときにコマンドプロンプトで `https://herdr.dev/install.cmd` を落として走らせる入れ方、GitHub の releases から手で落とす zip は中の `herdr.exe` だけを写さず展開したフォルダごと置くこと。同じフォルダに在る、Windows の疑似端末の仕組み ConPTY の実行時のファイルが要る。このファイルは点検しない）と、Claude Code の連携（`herdr integration install claude`。Claude Code の会話を herdr に知らせるフックを、Claude Code の設定のフォルダ（既定は `~/.claude`）に足す。アカウントごとに設定のフォルダを分けているなら、フォルダごとに、そのフォルダを指す環境変数 `CLAUDE_CONFIG_DIR` を替えて入れる。連携が入っているかは点検せず、案内に出すだけ）。
- herdr が入っているが server が動いていない: 入れ方の命令は「作業するフォルダで `herdr` を打って起こす」。案内は、herdr を初めて起こすと herdr 自身が初回の案内（onboarding）を出し、進めると設定の integrations のタブから連携を入れられることと、上と同じ連携の案内。
- 起こし方の命令が見つからない（`--launcher` で渡した命令が見つからなければ、足りない物に数える）: 先に「アカウントが 1 つなら命令は作らなくてよい（`--launcher` を省けば `claude` だけを見る）」と書き、分けるなら、アカウントごとに設定のフォルダを分けて `CLAUDE_CONFIG_DIR` に入れて `claude` を起こす関数か別名を、bash・zsh・PowerShell の 3 つで示す。名前（`claude-p2`）とフォルダ（`~/.claude-p2`）は例で、点検は `--launcher` で渡された名前を探すだけで決め打ちしない。

根拠は、herdr の v0.9.5 の文書とソースを写した持ち主のノート（my_notes の `reference/primary/ai/herdr-install-and-config.md`、2026-10-16。v0.9.5 は読んだ版。点検は herdr の版の番号を見ないが、`herdr status server` の出力の形は 0.9.3 で読んだ物を前提にする）、Claude Code の環境変数の文書（`CLAUDE_CONFIG_DIR`）、PowerShell の `Set-Alias` の文書（別名は引数を持てないので関数にする）。

## 使い方

```bash
tiers --tier <0〜3> [--launcher <命令> ...] [--json]
```

- 終了コード: 0 = そろっている、1 = 足りない物がある、2 = 使い方が違う。
- `--json` の形（`schema: 1`）は [`lib/tiers_check.py`](lib/tiers_check.py) の頭に在る。足りない物は `checks[]` の `ok: false` の項目で、`problem`（足りない訳）と `fix`（入れ方の行）と `guide`（案内の行。無ければ空）を持つ。人の読む形は、同じ `guide` の行を「案内:」の下に出す。

## 決めたこと

### 点検は入れ方を示して止まり、何も入れない

設計の 4.11 は「準備は、足りない物を入れる手順を案内する（手で入れる物は、入れ方を示して止まる）」とする。今の段の道具は、どれも手で入れる物と決めた。gh・herdr・Archon・Claude Code は OS に道具を入れる操作で、gh のログインはアカウントを結ぶ対話の操作だから、利用者に断らずに走らせてよい物が無い。Claude Code の文書が勧める「初めて使うときに確かめ、無ければ入れる」（hooks の文書の practical pattern）は、例が言語のパッケージ（`npm install`）で、OS の道具まで含むとは書いていない。自動で入れる物が出てきたら、項目の `manual` を false にして足す。

### 置き場: 共通のプラグインにし、各プラグインが `dependencies` で依存する

置き場の候補は 2 つあった。

1. 共通のプラグイン（これ）を 1 つ作り、各プラグインが `plugin.json` の `dependencies` で依存する。
2. このリポジトリの今の共有の形（`scripts/claude_auth.py` を各プラグインの中へ写し、`scripts/shared-copies.py` が写しの一致を CI で縛る）に載せ、点検の本文を各プラグインへ写す。

1 を選んだ。2 の形は、Claude Code のプラグインが入った後に自分のフォルダしか持たず、実行時に 1 か所を共有する道が無かった頃（2026-09-15 の実測）の答えである。依存として入れたプラグインの `bin/` が PATH に入ると確かめられたので（下）、点検の本文を 1 か所に置いて呼べる。1 なら、点検の中身を直すと全部のプラグインに 1 回で効き、写しの割れを縛る柵も要らない。人が走らせる入口（`/tiers:check`）も同じ所に置ける。設計の 4.11 が挙げる Neovim の `:checkhealth`（点検の枠を共有する）と `brew doctor`・`flutter doctor`（1 つの命令が環境を点検する）の後者の形に近い。各プラグインの点検（works-dispatch の設定や `/catchup` の命令など、そのプラグインだけが知る物）は、各プラグインが続けて持つ。

依存の範囲（`version`）は書かない。範囲は依存先の git のタグで解くが、このリポジトリはタグを作らない（持ち主の決定）。同じ marketplace の相対パスのプラグインは、marketplace の今の写しで入る。そのため `--json` の形は `schema` の番号で守り、形を変えるときは番号を上げ、呼ぶ側は知らない番号を誤りとして扱う。欄を足すだけ（知らない欄を読まない呼び手がそのまま動く変え方。`guide` がそれ）は番号を上げない。上げると、`schema` が 1 であることを確かめる呼び手（このリポジトリの別のプラグイン works-dispatch が tiers を呼ぶ所 `dispatch/tierx.py`。下の「ほかのプラグインから使う形」）が、足した欄を使わないのに止まる。

### 試して確かめたこと（2026-10-16、Claude Code 2.1.301、使い捨ての marketplace）

文書（Plugin dependencies と Plugin manifest reference）に書かれていない 2 点を、使い捨ての marketplace（手元のフォルダの git のリポジトリ）に、`bin/` とスキルを持つプラグイン `base` と、それに依存する `user` を置いて確かめた。隔離した `CLAUDE_CONFIG_DIR` に `claude plugin install user@<marketplace>` で `user` だけを入れると、`base` も依存として入った（`+ 1 dependency: base`）。その上で `claude -p` に次を走らせた。

- 依存として入ったプラグインの `bin/` は、Bash の道具の PATH に入る。PATH に `base/bin` が載り、`command -v base-probe` が見つかり、走った。
- 依存先のスキルは、依存する側の会話から `<依存先のプラグイン>:<スキル>`（例 `base:probe`）の名前で一覧に載り、Skill の道具で呼べた。

確かめていないこと（要確認）: GitHub から足した marketplace（キャッシュに写る形）でも同じか。Windows の Claude Code で、拡張子の無い `bin/tiers` を Bash の道具（Git Bash）から名前で起こせるか（Python の台本としては、試験が `python bin/tiers` の形で Windows の CI でも走らせる）。

## ほかのプラグインから使う形

works-dispatch が最初につないだ（`--check`）。ほかのプラグインは、次の形でつなぐ。

1. 自分の要る段を決め、README に「要る段: N」と書く。段は、使う外の道具のうち最も上の物で決める（gh だけなら 1、herdr を操るなら 2、Archon を起こすなら 3）。
2. `plugin.json` の `dependencies` に `{"name": "tiers", "marketplace": "raiki61"}` を足す（`version` は書かない。上の「置き場」）。
3. 使い始めの確かめ（`--check` のような入口か、スキルの最初の手順）で `tiers --tier N --json` を呼ぶ。Python から呼ぶなら、PATH の上の拡張子の無い `tiers` を探して `sys.executable` で起こす（Windows の `shutil.which` は拡張子で探すので見つけない）。リポジトリの checkout から走らせる試験と開発のために、隣の `tiers/bin/tiers` も探す。works-dispatch の [`dispatch/tierx.py`](../works-dispatch/dispatch/tierx.py) がその形。
4. `ok` が false なら、`checks[]` の `ok: false` の項目の `problem` と `fix` を出して止まる。`tiers` が見つからない・形が違うときは、止めずに注記にし、そのプラグインの今までの確かめを続ける（依存が入っていない古い入れ方でも、今ある確かめを減らさない）。
5. スキルだけのプラグイン（スクリプトを持たない）は、スキルの最初の手順に「`tiers --tier N` を走らせ、足りなければ出力の入れ方を見せて止まる」と書く。

まだつないでいないプラグインと、つなぐときの注意:

- works（darkfactory）: 要る段は 3 に見えるが、works は Archon を自分で取ってきて隔離した家に置く（`works/dev/archon.sh`）ので、PATH の `archon` を要らない。つなぐときは段 1（gh。Archon を gh release で取るため）と works の自前の確かめ（uv と claude）にするか、tiers に「Archon を自分で取る」場合の点検を足すかを、works の側で決める。
- attention（whose-turn・catchup）: gh を使うので段 1。
- convergence-loops・graphloops・gates: gh で PR を読む・投稿する所が有る。段 0 か 1 かは、gh が無いときに何が止まるかを各プラグインで見て決める。

## 試験

```bash
python3 -B -m unittest discover -s tiers/tests
```

外の道具は起こさず、口（`Probe`）を偽物に替える。全体の試験（`tests/run.sh`）にも載っている。
