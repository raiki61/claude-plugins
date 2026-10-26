# graphloops と convergence-loops の Python の入口が版の付いた名前も試す形を、Linux と Windows で入れて試す（2026-10-26）

- 何の記録か: graphloops 0.45.2 と convergence-loops 0.52.3 の Python の入口（`run-python.sh`）は、`python3`・`python` の後に版の付いた名前（`python3.20` から `python3.12` まで新しい順）も試し、`py -3` を最後に試す形になった（直しは main の 193b31b7。graphloops・convergence-loops を受け持つ部署への頼み 967fa3 の物）。この形を、実機の Linux と Windows（Git Bash）に入れて試した結果。
- 分かった事: どちらの OS でも、ふつうに入れた Python でも、uv で入れた版の付いた名前（`python3.13`）だけが PATH に在る形でも、入口は 3.12 以上の Python を選び、graphloops の読んだ記録のフックと `/graphloops:intake` のコマンドが動いた。新しい詰まりは 0 件。今壊れている所は無い。
- 直しが効く所: 直す前の版は、Linux の uv の `python3.13` だけの形で「見つからない」と止まり、今の版は通った。Windows は `py`（Windows の Python のランチャー。PATH の外に入れた Python も見つける）が在ると、直す前の版も `py -3` で通る。Windows で直しが効くのは `py` が無いときで、その形は入口を直に打って確かめた。
- 読み手に求める物: 無い。

[docs/standards/cross-os.md](../standards/cross-os.md) の決まり 6（フックの起動の行とスキル・コマンドの本文が打たせるコマンドは CI が起動しないので、変えたら実機で試す）のとおり試した（頼み 20261026-131909-b1a128）。CI の試験は POSIX の上で偽の python を並べて入口を回すだけで、Windows では見送っている。試しの部署は見つけた事を記録するだけで、プラグインのファイルは直していない。macOS は持ち主が手元で使っているので試していない。

この記録の言葉:

- 入口: 各プラグインが Python の台本を起動するときに通す殻。graphloops は `hooks/run-python.sh`、convergence-loops は `scripts/run-python.sh`。候補の名前を順に起動し、3.12 以上の物を選ぶ。選べなければ訳を 1 行出して止まる（graphloops は終了の値 1、convergence-loops は 127）。
- 読んだ記録のフック: graphloops の PostToolUse のフック（`hooks/record-read.py`）。Read のたびに入口を通して起き、回っている run（graphloops のループの 1 回の実行）が在れば、その盤面（run ごとの状態のフォルダ）の `reads.jsonl` に 1 行足す。入口を `--once` 付きで起動し、Python を選べないときは一時の置き場に印のファイル `graphloops-no-python-<会話の id>` を作る。
- 形 1・形 2: 頼みが確かめてほしいと書いた 2 つの形。形 1 は「ふつうに入っている Python」。形 2 は「3.12 以上の Python が版の付いた名前でだけ PATH に在る」。uv は既定で版の付いた名前だけを入れる（[uv の文書の Installing Python](https://docs.astral.sh/uv/guides/install-python/)「uv only installs a _versioned_ executable by default.」）ので、`uv python install 3.13` で作った。
- PostToolUse: Claude Code がツールを使った直後に起動するフックの場面。`hook_started`・`hook_response` は、`claude -p --include-hook-events` が出す、フックの起動と終わり（終了の値を含む）の行。
- `/graphloops:intake`: graphloops を使っていて踏んだ問題を、利用者の手元の `intake.jsonl` に 1 行残すコマンド。本文は、入口を通して `scripts/loop.py intake` を打たせる。
- 試しの会話の主: 試しで起動した `claude -p` の会話の中の AI。`/graphloops:intake` の本文を読んで、そこに書かれたコマンドを打つのはこの AI。
- 代わりの物: Windows に初めから在る「アプリ実行エイリアス」の `python3.exe`・`python.exe`（`%LOCALAPPDATA%\Microsoft\WindowsApps` の中）。Python を入れていない人を Microsoft Store へ誘う物で、Python としては動かない。

## 結果のあらまし

| OS | 形 | 入口が選んだ物 | フック | intake |
|---|---|---|---|---|
| Linux | 1 | `/usr/bin/python3` 3.13.5 | 起きた・0 | ok |
| Linux | 2 | `python3.13` 3.13.17 | 起きた・0 | ok |
| Windows | 1 | `python`（python.org）3.15.0 | 起きた・0 | ok |
| Windows | 2 | `python3.13` 3.13.17 | 起きた・0 | ok |

- 「フック」の列は、読んだ記録のフックが起きたかと終了の値。4 つとも、盤面の `reads.jsonl` に、読んだ README の 1 行が足された。Python を選べなかった印のファイルは、どの形でも作られなかった。
- 「intake」の列は `/graphloops:intake <1 行>` の返事。4 つとも「ok 1 行を …/intake.jsonl に残した」で、残った行の `python` のフィールドは入口が選んだ物の版と同じだった。
- convergence-loops の入口も、4 つの形で graphloops と同じ物を選んだ。
- 比べとして、直す前の版（graphloops 0.45.1）の入口は、Linux の形 2 で「Python 3.12 以上が見つからない（python3・python・py -3 を試した）」の 1 行で止まった（終了の値 1）。Windows の形 2 では、py を PATH から外した形でだけ同じ 1 行で止まった（下の「Windows」）。今の版はどちらも `python3.13` を選んだ。この試しが、直した所を通っていることの裏付け。
- 版の付いた名前の候補（`python3.20`〜`python3.12`）のうち、試したのは `python3.13` だけ。ほかの名前も同じ並びの中で同じ仕方で起動されるので、1 つで足りるとした。
- 表の 4 行のほかに、Windows で `py` も PATH から外した形を、入口を直に打つ形でだけ確かめた（下の「Windows」の「py も外した形」）。
- 新しく見つけた詰まりは 0 件。

## 試しの環境

| | Linux | Windows |
|---|---|---|
| 機械 | Colima の Docker | VM（[windows-vm.md](windows-vm.md)） |
| OS | Debian 13（`debian:trixie-slim`） | Windows 11 ARM64 |
| 形 1 の Python | apt の python3 3.13.5 | python.org の 3.15.0 |
| 形 2 の Python | uv 0.13.5 の 3.13.17 | uv 0.13.5 の 3.13.17 |
| Claude Code | 2.1.310 | 2.1.310 |

- 入れた版: main の marketplace 0.282.7（直しの後に版を上げた main の caa2edb9）から、ターミナルで `claude plugin marketplace add anthropics/claude-plugins-official`・`claude plugin marketplace add raiki61/claude-plugins`・`claude plugin install graphloops@raiki61` を打った。graphloops 0.45.2 と、依存の convergence-loops 0.52.3・pr-review-toolkit が一緒に入った。
- Linux は、Python を入れない土台のイメージ（ca-certificates・curl・git・bash・procps・less・jq と Claude Code）から、2 つのコンテナを作った。形 1 は apt で python3 を足した。形 2 は Python を入れず、uv を入れて `uv python install 3.13` を打った。形 2 の PATH の Python の類は `~/.local/bin/python3.13` だけで、`python3`・`python`・`py` は無い。
- Windows は 1 台の VM で、形 1 の後に形 2 を作った。
  - 形 1 の PATH の Python の類: `python3` は代わりの物だけ。`python` は python.org の物が代わりの物より前に在る。`py` は `C:\WINDOWS\py.exe`。
  - 形 2: uv を入れて `uv python install 3.13` を打った。uv は `~\.local\bin\python3.13.exe` だけを置いた。そのうえで、PowerShell で PATH から python.org のフォルダ（`C:\Program Files\Python315-arm64` と、その `Scripts`）を外してから claude を起動した。`python3` と `python` は代わりの物だけになった。`py`（`C:\WINDOWS` の中）は残した。`C:\WINDOWS` は PATH から外せないため。py を外した形は、入口を直に打つ確かめでだけ試した（下の「Windows」）。
- 盤面: 試しのリポジトリで、graphloops の research-graph のスキルの本文の行（`bash <graphloops>/hooks/run-python.sh <graphloops>/scripts/loop.py init --loop research-loop …`）を打って run を 1 つ立てた。読んだ記録のフックは、回っている run が無いと何も書かないので、この run は、フックが Python の台本まで動いたかを見るために立てた。4 つの形とも、この行は終了の値 0。
- `claude -p` は、形ごとに 2 回、合わせて 8 回起動した。1 回目は「README.md を Read して OK と返す」頼みで、2 回目は `/graphloops:intake 試し: …` で、どちらも `--output-format stream-json --verbose --include-hook-events --max-budget-usd 1` を付けた。フックが起きたかは hook_started・hook_response の行で見た。モデルは Sonnet 5.5（アカウントの既定）。かかった額は 1 回 0.005〜0.049 ドル、8 回の合計は約 0.29 ドル。
- 鍵: Claude Code の鍵は環境変数 `CLAUDE_CODE_OAUTH_TOKEN` だけで渡した。Linux は `docker exec -e` で、Windows は vm.sh の ssh で渡した。ファイルには書いていない。

## 確かめた物

### Linux

- 入口を直に `bash <入口> -c 'import sys; print(sys.executable)'` で打った。
  - 形 1: 両プラグインとも `/usr/bin/python3` を選んだ（終了の値 0）。
  - 形 2: 両プラグインとも `/home/tester/.local/bin/python3.13` を選んだ（終了の値 0）。
- 読んだ記録のフック: 2 つの形とも hook_response は PostToolUse:Read で終了の値 0、標準出力と標準エラーは空。盤面の `reads.jsonl` に、README の path・sha・`partial: false` の 1 行が足された。
- `/graphloops:intake`: 試しの会話の主は、コマンドの本文のとおり `bash "<graphloops>/hooks/run-python.sh" "<graphloops>/scripts/loop.py" intake --data-dir "<プラグインのデータ>" --what "…"` を打った。返事は「ok 1 行を /home/tester/.claude/plugins/data/graphloops-raiki61/intake.jsonl に残した」。残った行の `python` は、形 1 で 3.13.5、形 2 で 3.13.17。
- convergence-loops のスキルの本文が打たせる行も、2 つの形で打った。
  - `bash <convergence-loops>/scripts/comment-ratio.sh --json HEAD~1` は数を出した（終了の値 0）。この殻は中で同じフォルダの入口を通して Python を起動する。
  - `bash <convergence-loops>/scripts/run-python.sh <convergence-loops>/scripts/review-record.py rec.json` は「記録が不正: …」を返した（終了の値 2）。`rec.json` は `{}` だけを書いたファイルで、わざと渡した。`review-record.py`（レビューの記録の検証器）は記録を `round-<N>.json` をまとめたフォルダで受け取るので、ファイルを渡すと「記録が不正」で止まる。見たかったのは、入口が Python を選んで検証器まで届くこと。終了の値は、入口が選べなかったときの 127 でなく、検証器の返した 2 だった。

### Windows

- 入口は、Claude Code が起動するのと同じ Git Bash（`C:\Program Files\Git\bin\bash.exe`）で、直に打った。
  - 形 1: 両プラグインとも `C:\Program Files\Python315-arm64\python.exe` を選んだ。先頭の `python3` は代わりの物で、それを飛ばした。
  - 形 2: 両プラグインとも `C:\Users\dev\AppData\Roaming\uv\python\cpython-3.13-windows-aarch64-none\python.exe` を選んだ。これは `python3.13.exe` が起動する本体。`python3`・`python` の代わりの物を飛ばし、`py -3` より前に版の付いた名前で選んだ。
- py も外した形: 形 2 の PATH をさらに絞り、`~/.local/bin`・代わりの物の在るフォルダ・Git Bash の `/usr/bin`・`/mingw64/bin` だけにした。その PATH で入口を打った。
  - 今の版: 両プラグインとも上と同じ uv の 3.13.17 を選んだ。
  - 直す前の版（0.45.1）: 「Python 3.12 以上が見つからない（python3・python・py -3 を試した）」で止まった。
  - py を残した形 2 の PATH では、直す前の版も `py -3` で python.org の 3.15.0 を選んだ。py は PATH の外に入れた Python も見つけるため。つまり、版の付いた名前が要るのは、この VM の形では py の無いときだけ。
- 読んだ記録のフック: 2 つの形とも hook_response は PostToolUse:Read で終了の値 0、標準出力と標準エラーは空。盤面の `reads.jsonl` に README の 1 行が足された。印のファイルは `%TEMP%` に無かった。
- `/graphloops:intake`: 試しの会話の主は、Linux と同じ形の行を `C:/Users/dev/...` のパスで打った。返事は「ok 1 行を C:\Users\dev\.claude\plugins\data\graphloops-raiki61\intake.jsonl に残した」。残った行の `python` は、形 1 で 3.15.0、形 2 で 3.13.17。
- 1 つの注: 残った `intake.jsonl` を Windows PowerShell 5.1 の `Get-Content` で表示すると、日本語が化けて見えた。Git Bash の `cut` で読むと正しい UTF-8 だった。ファイルは壊れておらず、PowerShell 5.1 が BOM の無いファイルを UTF-8 として読まないための表示の化け。graphloops の利用者がこのファイルを読むのは export を通すときなので、詰まりにしていない。

## 新しく見つけた詰まり

無い。

## 片付けと鍵

- Linux: 2 つのコンテナ `gl-pyentry-a`・`gl-pyentry-b` と、土台のイメージ `gl-pyentry-base` を、名前を指して消した。鍵は環境変数でだけ渡したので、コンテナのファイルには書いていない。
- Windows:
  - 消す前に、家のフォルダの下のファイル（名前が `Microsoft` と `cache` のフォルダの中を除く）を、鍵の形（`sk-ant-` で始まり 40 字以上続く値）の正規表現で `grep` し、当たったファイルが 0 本なのを確かめた。`cache` を除いたのはプラグインのキャッシュで、プラグインの台本が鍵を見分けるための `sk-ant-` の文字を持つため。
  - 入れた 3 つのプラグインを外し、marketplace の raiki61 と claude-plugins-official を消し、プラグインのキャッシュとデータも消した。
  - uv の Python 3.13 を `uv python uninstall` で外し、uv の本体（`~\.local\bin` の `uv.exe`・`uvx.exe`・`uvw.exe`）と `%APPDATA%\uv` も消した。試しのリポジトリ `~\proj-a`・`~\proj-b` と、持ち込んだ台本も消した。
  - `~\.claude\settings.json` は試しの前の形（`env` の `HTTPS_PROXY` と `NO_PROXY` だけ）に戻した。プラグインを外した後も、中身の空の `enabledPlugins` と `extraKnownMarketplaces` が残っていたため。
  - VM は動いたまま。
- 鍵の値は画面にもファイルにも出していない。gh の鍵は使っていない。
