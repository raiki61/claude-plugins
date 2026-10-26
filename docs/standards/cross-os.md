# OS をまたいで動かす標準（macOS でしか動かない書き方を作らない）

プラグインのコード（Python・シェル・フック）と、スキルとコマンドの本文が打たせるコマンドを、macOS・Linux・Windows のどれでも動く形で書くための決まり。1 つの OS でしか動かない物は、その OS の外で黙って壊れずに、訳を出して止まる形にする。
読むのは、プラグインのコード・フック・スキルの本文が打たせるコマンド・ルートの `scripts/`・`tests/` を書く・直す各担当。書く・直すときは下の「決まり」に合わせる。

この文書の語:

- 部署・担当・点検・受付は [README](README.md) の頭と同じ（会社の形 `.claude/company.toml` が決める、受け持ちを持つ Claude Code の会話。頼むと受付番号が付く）。
- 代わりの物: Windows に初めから在る「アプリ実行エイリアス」の `python3.exe`・`python.exe`（`%LOCALAPPDATA%\Microsoft\WindowsApps` の中）。Python を入れていない機械で起動すると、Microsoft Store へ誘う案内を出して終わる。`command -v python3` はこれを見つける。
- 試し: 実機の Linux・Windows でプラグインを入れて確かめる部署の名前（会社の形の受け持ちの 1 つ）。
- POSIX: シェルのコマンドの振る舞いを OS をまたいで決めた規格（[The Open Group の POSIX.1-2024 のユーティリティの一覧](https://pubs.opengroup.org/onlinepubs/9799919799/idx/utilities.html)）。macOS（BSD のツール）と Linux（GNU のツール）で同じに動くのは、ここに書かれた形とオプションだけ。

対象は [README](README.md) の「対象」の 6 つのプラグインに、rent-or-buy・works・works-factory と、ルートの `scripts/`・`tests/`・CI（`.github/workflows/`）を足した物。works と works-factory は誰の受け持ちでもないので、直しは一度きりの直しを受ける作業に頼む（[スキルの書き方の標準](skill-authoring.md)と同じ扱い）。

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

1. **Python は「在るか」でなく「起きて、要る版か」で選ぶ。** フック（`hooks/hooks.json`）・スキルとコマンドの本文が打たせるコマンド・シェルの殻から Python を起動するときは、`python3`・`python`・`py -3` を順に実際に起動し、要る版以上の物を選ぶ。どれも起きなければ、何を試したかと入れ方を 1 行出して止まる。
   - 素の `python3` と、`command -v python3 || command -v python` は使わない。Windows の python.org の入れ方は `python3` を勧めず（[Python の文書の Using Python on Windows](https://docs.python.org/3/using/windows.html)「A `python3` command is also included that mimics the `python` command. It is intended to catch accidental uses of the typical POSIX command on Windows, but is not meant to be widely used or recommended.」）、PATH の `python3` は代わりの物に当たる。macOS 付属の `python3` は 3.9 で、3.11 を要る台本が動かない。
   - 今の形の手本は works-dispatch の `hooks/run-python.sh`（版も見る）と rent-or-buy の `bin/rent-or-buy` の頭（`#!/bin/sh` の後に `''':'` で `python3`・`python`・`py -3` を順に試し、3.11 以上かも見る形）。tiers の `bin/` の頭は同じ形だが、起きるかだけを見て版を見ない。プラグインは 1 つずつ配られ、ほかのプラグインのファイルを実行時に読めないので、各プラグインが自分の中に持つ。同じ処理を写すときは [機械が読む値の受け渡しの標準](machine-readable-values.md)の決まり 6 に従い、`scripts/shared-copies.py` が見張る写しにする（`.py` の docstring か `.md` の frontmatter に「この本文は複数のプラグインに写しで在る」の一文を書いた物を、同じ名前の組として見張る。シェルの殻を写すなら、見張り方を点検に頼む）。
2. **シェルのツールは POSIX の形とオプションだけで書く。POSIX に無い物を使うなら、もう一方の OS の形への落ち方を持ち、どちらも無ければ止まる。**
   - POSIX に無い物の例: `shasum`・`sha256sum`・`md5`・`md5sum`・`date -j`・`date -v`・`date -d`・`stat -f`・`stat -c`・`readlink -f`・`grep -P`・`sed -i`・`base64 -D`・`xargs -r`・`timeout`。
   - 手本は tiers の `statusline/bg-count.sh` の起動の時刻（macOS は `date -j -f`、効かなければ Linux の `ps -o etimes`）。
   - 値を作るツールが起きなかったときに、空の値で先へ進まない（空の鍵で控えを共有する、など）。ハッシュは POSIX の `cksum` か Python で作れば落ち方が要らない。
3. **一時の置き場・家の場所は、言語の標準の関数で引く。** Python は `tempfile.gettempdir()`（[tempfile の文書](https://docs.python.org/3/library/tempfile.html#tempfile.gettempdir)。`TMPDIR`・`TEMP`・`TMP` と OS の既定を順に見る）と `pathlib.Path.home()`。`env.get("TMPDIR") or "/tmp"` のように 1 つの OS の既定を書かない。 シェルの殻は、Windows でも Git Bash の中で動く（Git Bash は `/tmp` を持つ）ので `${TMPDIR:-/tmp}` でよい。
4. **OS の形を一覧や型で持つ所は、OS ごとに持つか、持たない OS で効かないことを出す。** 例: 広すぎる探しのルートの一覧（macOS の `/Users`・`/System` だけでなく、Linux の `/home`・`/usr`、Windows のドライブのルート）、プロセスの名前の形（Linux の `ps -o comm` はパスを持たず 15 字で切れる）、パスの書き方（`C:\x` を相対として扱わない）。
5. **1 つの OS でしか動かない物は、入口で OS（と要るなら CPU）を確かめ、ほかの OS では「どの OS だけか」を 1 行出して止まる。** 説明書に書くだけでは足りない。例: works の Archon の実行ファイルは macOS の Apple silicon だけ、works/dev の keychain（`security`）は macOS だけ、tiers の statusline は macOS と Linux だけ。macOS の keychain を読む共有の認証の部品（各プラグインの `claude_auth.py`）は、`sys.platform == "darwin"` の時だけ読み、ほかの OS では試した物を並べた訳を返す形で、この決まりを満たしている。
6. **確かめは CI の Linux と Windows に載せる。載らない物は試しに頼む。**
   - ルートの `tests/run.sh` と pytest は CI（`.github/workflows/test.yml`）で ubuntu と windows で回り、見送りは OS ごとの許しの一覧（`SKIP_ALLOW`）に無ければ赤になる。OS で分かれるコードは、ここで回る試験で両方の道を通す。
   - フックの起動の行・ステータスラインの殻・スキルの本文が打たせるコマンドは CI の試験が通らないので、変えたら試し（実機の Linux と Windows で入れて試す部署）に頼む。前の試しの記録は [docs/trials/README.md](../trials/README.md)。

## 直さないと決めた物

- works の試験の全段は CI の macOS でだけ回る。ubuntu と windows に足さない訳は `.github/workflows/test.yml` の works の job の注に書いてある（ubuntu は試験の側に macOS の一時の置き場の前提が残り、windows は全段を実機で回して測っていない）。works は macOS の Apple silicon を要る物と書いているので、決まり 5 の止まり方が入れば足りる。
- `.github/workflows/mutation.yml` の `mapfile`（bash 4 から）は ubuntu の job の中でだけ回るので直さない。
- gates の `coldread-gate.py` の `/tmp` と `/private/tmp` の扱い、works-dispatch の `claudex.py` の信頼の鍵の扱いは、macOS の記号のリンクをほかの OS でも崩さずに揃える物で、macOS 専用の書き方ではない。
