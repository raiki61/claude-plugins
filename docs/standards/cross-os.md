# OS をまたいで動かす標準（macOS でしか動かない書き方を作らない）

プラグインのコード（Python・シェル・フック）と、スキルとコマンドの本文が打たせるコマンドを、macOS・Linux・Windows のどれでも動く形で書くための決まり。1 つの OS でしか動かない物は、その OS の外で黙って壊れずに、訳を出して止まる形にする。
読むのは、プラグインのコード・フック・スキルの本文が打たせるコマンド・ルートの `scripts/`・`tests/` を書く・直す各担当。書く・直すときは下の「決まり」に合わせる。

この文書の語:

- 部署・担当・点検・作業・受付は [README](README.md) の頭と同じ（会社の形 `.claude/company.toml` が決める、受け持ちを持つ Claude Code の会話。頼むと受付番号が付く）。「各担当」はプラグインやファイルごとの受け持ちの会話、点検は CI とルートの `tests/` の受け持ち、作業は受け持ちの無い一度きりの直しを受ける部署。
- 代わりの物: Windows に初めから在る「アプリ実行エイリアス」の `python3.exe`・`python.exe`（`%LOCALAPPDATA%\Microsoft\WindowsApps` の中）。Python を入れていない機械で起動すると、Microsoft Store へ誘う案内を出して終わる。`command -v python3` はこれを見つける。
- 試し: 実機の Linux・Windows でプラグインを入れて確かめる部署の名前（会社の形の受け持ちの 1 つ）。
- POSIX: シェルのコマンドの振る舞いを OS をまたいで決めた規格（[The Open Group の POSIX.1-2024 のユーティリティの一覧](https://pubs.opengroup.org/onlinepubs/9799919799/idx/utilities.html)）。macOS（BSD のツール）と Linux（GNU のツール）で同じに動くのは、ここに書かれた形とオプションだけ。

対象は [README](README.md) の「対象」の 6 つのプラグイン（attention・convergence-loops・gates・graphloops・tiers・works-dispatch）に、rent-or-buy・works・works-factory と、ルートの `scripts/`・`tests/`・CI（`.github/workflows/`）を足した物。works と works-factory は誰の受け持ちでもないので、直しは一度きりの直しを受ける作業に頼む（[スキルの書き方の標準](skill-authoring.md)も、works と works-factory の直しを作業に頼む）。

## なぜ要るか

Claude Code は macOS・Linux・Windows で動く（[Claude Code の Advanced setup の System requirements](https://code.claude.com/docs/en/setup#system-requirements)）。marketplace から入れる人は、持ち主と同じ macOS とは限らない。
Windows では、Git for Windows が在れば Bash のツールは Git Bash で動き、無ければ PowerShell で動く（同じ文書の「Install on native Windows」）。

2026-10-26 の洗い出し（受付 20261026-062135-00c4c3）では、BSD と GNU で振る舞いの違うコマンド（`sed -i ''`・`date -j`・`stat -f`・`readlink -f`・`grep -P`・`base64 -D` など）を落ち方無しに使う所は 0 件だった。残っていたのは次の類で、どれも macOS で書いて macOS で確かめた所に出た。

- Python を「在るか」で選び、「起きるか」を見ない。docs/trials/2026-10-16-clean-env-3.md の 7 で、Windows の works-dispatch のフックが毎回落ちた原因。works-dispatch は直したが、gates・graphloops のフックと、attention・gates・graphloops のスキルの本文が打たせるコマンドに同じ形が残っていた。
- POSIX に無いツール（`shasum`）を落ち方無しに使い、無い機械で値が黙って空になる。
- 一時の置き場を `TMPDIR` か `/tmp` の決め打ちで引き、Windows で落ちて例外が捨てられる。
- OS の形を一覧で持つ所が macOS の形だけを持ち、ほかの OS では守りが黙って薄い。
- 1 つの OS でしか動かない物が、入口で OS を見ずに、ほかの OS で分かりにくい失敗（`Exec format error`・traceback）を出す。

## 決まり

1. **Python は「在るか」でなく「起きて、要る版か」で選ぶ。** フック（`hooks/hooks.json`）・スキルとコマンドの本文が打たせるコマンド・シェルの殻から Python を起動するときは、`python3`・`python`・版の付いた名前（`python3.N`）・`py -3` を順に実際に起動し、要る版（プラグインごとに、台本が要ると書いた最低の版。例は 3.11）以上の物を選ぶ。どれも起きなければ、何を試したかと、入れ方と、入っているのに PATH に無いときの直し方（入れた場所を PATH に足す）を 1 行出して止まる。
   - 版の付いた名前は `python3.20` から要る版（3.11 を要るなら `python3.11`、3.9 なら `python3.9`）まで、新しい順に 1 つずつ試す。上の端の 3.20 は決めた値で、今出ている最新の版（2026-10 に 3.15）より先まで含め、新しい版が出るたびに直さずに済むようにする。数は POSIX の sh でも動く `while` と算術展開（`n=20; while [ "$n" -ge "${min#*.}" ]; do …; n=$((n - 1)); done`）で回してよく、名前を並べて書いてもよい（`seq` と bash の `{20..11}` は sh に無いことがあるので使わない）。止まるときの 1 行は、試した物を「python3・python・python3.20〜python3.11・py -3」のように範囲で書いてよい。
   - 版の付いた名前を足す訳: 3.11 以上の Python が版の付いた名前でだけ PATH に在り、PATH の `python3` が macOS 付属の 3.9 のとき、`python3`・`python` だけでは入っている物を見つけられない。uv で入れた Python はこの形になる（[uv の文書の Installing Python](https://docs.astral.sh/uv/guides/install-python/)「uv only installs a _versioned_ executable by default.」）。2026-10-26 の試しで、works の入口がこの形で「python 3.11 以上を入れる」と案内して止まった（試しの部署の記録。受付 20261026-123944-c55c33）。版の付いた名前を候補に持つのは、Python 自身のビルド（[CPython の configure.ac](https://github.com/python/cpython/blob/main/configure.ac) の `python$PACKAGE_VERSION python3.16 python3.15 … python3.11 python3.10 python3 python`）と Node.js のビルド（[Node.js の configure](https://github.com/nodejs/node/blob/main/configure) の `command -v python3.15 … && exec python3.15`）も同じ。
   - 順の訳: この 2 つは版の付いた名前を先に試すが、ここでは `python3`・`python` の後に置き、今動いている機械で選ばれる Python を変えない。`py -3` は Windows の Python の起動の入口（py launcher）で、ほかの名前で見つからないときの最後の手として最後に置く（前の決まりの順のまま）。
   - 素の `python3` と、`command -v python3 || command -v python` は使わない。Windows の python.org の入れ方は `python3` を勧めず（[Python の文書の Using Python on Windows](https://docs.python.org/3/using/windows.html)「A `python3` command is also included that mimics the `python` command. It is intended to catch accidental uses of the typical POSIX command on Windows, but is not meant to be widely used or recommended.」）、PATH の `python3` は代わりの物に当たる。macOS 付属の `python3` は 3.9 で、3.11 を要る台本が動かない。
   - 今の形の手本は works-dispatch の `hooks/run-python.sh`（`--min` で要る版を受ける）と、rent-or-buy の `bin/rent-or-buy` と tiers の `bin/` の頭（`#!/bin/sh` の後に `''':'` で `python3`・`python`・版の付いた名前・`py -3` を順に試し、要る版以上かも見る形。tiers は `tiers`・`tiers-settings` が 3.8、`tiers-statusline` が 3.11）。この 3 つは版の付いた名前まで試す（受付 20261026-124803-1cb61e）。gates の `hooks/run-python.sh` も版の付いた名前まで試す（頼み 82bde8）。graphloops の `hooks/run-python.sh` と convergence-loops の `scripts/run-python.sh` も版の付いた名前まで試し（main の 193b31b7。頼み 967fa3）、実機の Linux と Windows で、uv で入れた `python3.13` だけが PATH に在る形でも選ばれることを試しで確かめた（[docs/trials/2026-10-26-python-versioned-names.md](../trials/2026-10-26-python-versioned-names.md)。頼み b1a128）。attention の `scripts/run-python.sh`（main の 3789206e。頼み 3422e3）と works の `dev/run-python.sh`（main の 94341638。頼み 9b86a4）も版の付いた名前まで試す形になったが、実機の試しはまだ通していない。プラグインは 1 つずつ配られ、ほかのプラグインのファイルを実行時に読めないので、各プラグインが自分の中に持つ。同じ処理を写すときは [機械が読む値の受け渡しの標準](machine-readable-values.md)の決まり 6 に従い、`scripts/shared-copies.py` が見張る写しにする（印は「この本文は複数のプラグインに写しで在る」の一文。`.py` は docstring、`.md` は frontmatter に書き、同じ名前の組として見張る。シェルの殻は印の書き場所がまだ決まっていないので、写す前に書き場所を点検に頼む）。
2. **OS で違う処理は Python の標準ライブラリに寄せ、シェルは薄く保つ**（持ち主 2026-10-26。窓口の足し 20261026-064421-ed26a1）。ファイルとパスは `pathlib`・`shutil`、一時の置き場は `tempfile`、時刻は `datetime`、外のコマンドの起動は shell を通さない `subprocess`（引数を一覧で渡す）で書く。シェルの殻は Python を選んで起動する所（決まり 1）と、POSIX の形とオプションだけで足りる所に留める。
   - BSD（macOS）と GNU（Linux）で振る舞いの違う外のコマンドは、OS ごとの書き分けで直さず、その処理を Python に移して直す。例: `shasum`・`sha256sum`・`md5`・`md5sum`（→ `hashlib`）、`date -j`・`date -v`・`date -d`（→ `datetime`）、`stat -f`・`stat -c`・`readlink -f`（→ `pathlib`・`os.stat`）、`sed -i`・`grep -P`（→ ファイルを読んで `re` で直して書く）、`base64 -D`（→ `base64`）、`timeout`（→ `subprocess` の `timeout`）。
   - 今ある書き分けの例は tiers の `statusline/bg-count.sh` がプロセスの起動の時刻を求める所（macOS は `date -j -f`、効かなければ Linux の `ps -o etimes`）。動いている物はそのまま残してよいが、新しく書く・直すときは書き分けを足さず Python に移す。
   - 値を作るツールが起きなかったときに、空の値で先へ進まない（空の値をキャッシュの鍵にして、全ブランチが同じキャッシュを使う、など）。
   - 標準ライブラリで吸収できない OS の違いは、プラグインの中で 1 つの関数かモジュールに置き、使う所はそれを呼ぶ（OS ごとの書き分けを使う所ごとに写さない）。今の例は各プラグインの `claude_auth.py`（keychain は macOS だけ）と `run-python.sh`（決まり 1）。OS を見る分岐（`sys.platform`）そのものを 1 か所に閉じることまでは求めない。手本にした OSS も、違いの処理は互換のモジュールに置くが、OS を見る分岐は外にも残している。pip は互換のモジュール [`utils/compat.py`](https://raw.githubusercontent.com/pypa/pip/main/src/pip/_internal/utils/compat.py)（頭に「Stuff that differs in different Python versions and platform distributions.」）に `WINDOWS` と `get_path_uid` を置き、[`utils/misc.py`](https://raw.githubusercontent.com/pypa/pip/main/src/pip/_internal/utils/misc.py) では型の検査（mypy）のために `sys.platform` を直に見る。pre-commit は Windows が shebang を読まない違いを [`parse_shebang.py`](https://raw.githubusercontent.com/pre-commit/pre-commit/main/pre_commit/parse_shebang.py) の `normalize_cmd` 1 か所で直す。
   - 標準ライブラリに寄せる裏付けとして、置き場の違いを層でまとめる外のライブラリ（[platformdirs](https://platformdirs.readthedocs.io/en/latest/)「Convention-compliant XDG Base Directory Spec on Linux, ~/Library on macOS, AppData on Windows.」）も在るが、外のライブラリを足すかは決まり 5 と同じく、足す前に持ち主に問う。
3. **一時の置き場・家の場所は、言語の標準の関数で引く。** Python は `tempfile.gettempdir()`（[tempfile の文書](https://docs.python.org/3/library/tempfile.html#tempfile.gettempdir)。`TMPDIR`・`TEMP`・`TMP` と OS の既定を順に見る）と `pathlib.Path.home()`。`env.get("TMPDIR") or "/tmp"` のように 1 つの OS の既定を書かない。 シェルの殻は、Windows でも Git Bash の中で動く（Git Bash は `/tmp` を持つ）ので `${TMPDIR:-/tmp}` でよい。
4. **OS の形を一覧や型で持つ所は、OS ごとに持つか、持たない OS で効かないことを出す。** 例: 広すぎる探しのルートの一覧（macOS の `/Users`・`/System` だけでなく、Linux の `/home`・`/usr`、Windows のドライブのルート）、プロセスの名前の形（Linux の `ps -o comm` はパスを持たず 15 字で切れる）、パスの書き方（`C:\x` を相対として扱わない）。
5. **1 つの OS でしか動かない物は、入口で OS（と要るなら CPU）を確かめ、ほかの OS では「どの OS だけか」を 1 行出して止まる。** 説明書に書くだけでは足りない。rustup の入れる台本も、入口で OS と CPU を見て、知らない物は訳を出して止まる（[rustup-init.sh](https://raw.githubusercontent.com/rust-lang/rustup/master/rustup-init.sh) の `err "unrecognized OS type: $_ostype"`・`err "unknown CPU type: $_cputype"`）。例: works の Archon（AI の段を順に回すツール）の実行ファイルは macOS の Apple silicon だけ、works/dev の keychain（`security`）は macOS だけ、tiers の statusline は macOS と Linux だけ。keychain のように OS ごとに仕組みの違う物は、ほかの OS の仕組みに合わせるための外のライブラリを足さず、macOS 専用と分かる形にして、ほかの OS では訳を出して止まる（外のライブラリが要ると判断したら、足す前に持ち主に問う）。macOS の keychain を読む共有の認証の部品（各プラグインの `claude_auth.py`）は、`sys.platform == "darwin"` の時だけ読み、ほかの OS では試した物を並べた訳を返す形で、この決まりを満たしている。
6. **確かめは CI の Linux と Windows に載せる。載らない物は試しに頼む。**
   - ルートの `tests/run.sh` と pytest は CI（`.github/workflows/test.yml`）で ubuntu と windows で回り、見送りは OS ごとの許しの一覧（test.yml が環境変数 SKIP_ALLOW で渡す）に無ければ赤になる。OS で分かれるコードは、ここで回る試験で両方の道を通す。
   - フックの起動の行・ステータスラインの殻・スキルの本文が打たせるコマンドは、CI の試験が実際には起動しない（試験は Python のコードを回すだけ）ので、変えたら試し（実機の Linux と Windows で入れて試す部署）に頼む。前の試しの記録は [docs/trials/README.md](../trials/README.md)。
   - OS ごとの job は、遅さを理由に絞ってよい。絞ったら、絞った job の注か下の「直さないと決めた物」に訳を書く。調べた OSS も絞っている。pip は Windows の Python の版を一番古い物と新しい物だけにし（[ci.yml](https://raw.githubusercontent.com/pypa/pip/main/.github/workflows/ci.yml)「# Commented out, since Windows tests are expensively slow, # only test the oldest and newest Python supported by pip」）、pre-commit は Windows を 1 版だけで回し（[main.yml](https://raw.githubusercontent.com/pre-commit/pre-commit/main/.github/workflows/main.yml)）、Deno は Web Platform tests を Linux だけで回す（[ci.ts](https://raw.githubusercontent.com/denoland/deno/main/.github/workflows/ci.ts)「Because CI is so slow on for OSX and Windows, we // currently run the Web Platform tests only on Linux.」）。ただし、ある OS でしか通らないコードの道は、その OS の job で通す。rustup も、Linux の job が `cfg(windows)` のコードを見ないので、Windows の job で検査する（[ci.yaml](https://raw.githubusercontent.com/rust-lang/rustup/master/.github/workflows/ci.yaml)「The Linux check job only sees `cfg(unix)` code, so lint the `cfg(windows)` code here too.」）。
   - 書き方を字で見る検査（静的検査）は、決まり 1 の素の `python3` の起動を見る `tests/python-launch-case.py` だけを持つ（点検 20261026-084925-095e52）。決まり 2・3 の書き方（`TMPDIR` の決め打ち・`shasum` など）を字で見る検査は、足すと決めていない。OSS が OS の違いを静的検査で見ているかは、調べ（my_notes の受付 20261026-070426-75f475）で原典に当たれず決まらなかったので、足すかは当たりが出たときに点検に頼んで決める。

## 直さないと決めた物

- works の試験の全段は CI の macOS でだけ回る。ubuntu と windows に足さない訳は `.github/workflows/test.yml` の works の job の注に書いてある（ubuntu は試験の側に macOS の一時の置き場の前提が残り、windows は全段を実機で回して測っていない）。works は macOS の Apple silicon を要る物と書いているので、決まり 5 の止まり方が入れば足りる。
- `.github/workflows/mutation.yml` の `mapfile`（bash 4 から）は ubuntu の job の中でだけ回るので直さない。
- gates の `coldread-gate.py` の `/tmp` と `/private/tmp` の扱い、works-dispatch の `claudex.py` の信頼の鍵（claude の設定ファイルが信頼済みのフォルダを覚えるときの、フォルダの path の鍵）の扱いは、macOS の `/tmp` と `/private/tmp` のようなシンボリックリンクをほかの OS でも崩さずに揃える物で、macOS 専用の書き方ではない。
