# gates 0.44.1 の直し 2 つを、Linux と Windows で入れて試す（2026-10-27）

- 何の記録か: [2026-10-26-cross-os.md](2026-10-26-cross-os.md) の詰まりの 2 と 3 を、gates を受け持つ点検の部署が gates 0.44.1 で直した（main の 86b1c6a9・4341c7c4。頼み da9321）。その直しを、今の main の版（gates 0.44.2）で実機の Linux と Windows に入れて試した結果。
- 分かった事: どちらの OS でも、2 つの直しが狙った物が画面に出た。
  - 読み手が起動しないとき、ログイン（`claude auth login`）へ導く 1 行が出た。
  - 知らせが打たせる読み直しのコマンドは `bash …/run-python.sh …/coldread-gate.py read` の形になり、Windows の Git Bash でも動いた。
  - 新しい詰まりは 0 件。今壊れている所は無い。
- 読み手に求める物: 無い。

[docs/standards/cross-os.md](../standards/cross-os.md) の決まり 6（フックが出す知らせと、スキルの本文が打たせるコマンドは CI が起動しないので、変えたら実機で試す）のとおり試した（頼み 20261027-065500-ce762b）。試しの部署は見つけた事を記録するだけで、プラグインのファイルは直していない。macOS は持ち主が手元で使っているので試していない。

この記録の言葉:

- 初見読み・読み手: gates の、文脈を持たない別の claude（読み手）に、外へ出す文や書いた文書を読ませて詰まりを返させる仕組み。ターンの終わりのフック（Stop）は、会話の中で書いた 300 字を超える文書を読み手に読ませる。
- 鍵を環境変数でだけ渡す形: Claude Code の鍵を `claude setup-token` で作り、環境変数 `CLAUDE_CODE_OAUTH_TOKEN` に置いて渡す形。ログインの保存先のファイル（`~/.claude/.credentials.json`）は無い。コンテナや VM でよく使う。
- 代わりの物: Windows に初めから在る「アプリ実行エイリアス」の `python3.exe`・`python.exe`（`%LOCALAPPDATA%\Microsoft\WindowsApps` の中）。Python を入れていない人を Microsoft Store へ誘う物で、Python としては動かない。
- 試しの会話: 下の「試しの環境」で起動した `claude -p` の会話。

## 結果のあらまし

| OS | ログインへ導く 1 行 | 読み直しのコマンドの形 | そのコマンドを打った結果 |
|---|---|---|---|
| Linux | 出た | run-python.sh | Python が動いた |
| Windows | 出た | run-python.sh | Python が動いた |

- 「そのコマンドを打った結果」は、知らせの読み直しのコマンドを、知らせの字のまま手で打った結果。どちらの OS でも、Python は起動し、読み手の起動まで進んだ。読み手はログインが無いので読めず、ログインへ導く 1 行を出して終了の値 1 で終わった。手の読みでもこの 1 行が出るのは、gates の README の「When the reader is not logged in」が書くとおり。
- 直す前の版（gates 0.44.0）は、前の試し（[2026-10-26-cross-os.md](2026-10-26-cross-os.md) の詰まりの 2 と 3）で次のように動いた。今回は走らせ直していない。
  - ログインへ導く 1 行が無く、「読み手が読めなかった文書」とだけ出た。
  - 読み直しのコマンドは素の `python3 <パス> read` で、Windows では代わりの物に当たって終了の値 49 で終わった。

## 試しの環境

| | Linux | Windows |
|---|---|---|
| 機械 | Colima の Docker | VM（[windows-vm.md](windows-vm.md)） |
| OS | Debian 13（`debian:trixie-slim`） | Windows 11 ARM64 |
| Python | 3.13.5 | 3.15.0（python.org の物） |
| git | 2.47.3 | 2.56.0.windows.2 |
| Claude Code | 2.1.311 | 2.1.311（2.1.310 から上げた） |

- 入れた版: marketplace は main の 812f569a。gates 0.44.2・convergence-loops 0.52.3・graphloops 0.45.2。依存の pr-review-toolkit（claude-plugins-official の物）も一緒に入った。
- Linux の土台は `debian:trixie-slim` に ca-certificates・curl・git・python3・bash・jq・procps・less を足した物。試しの間だけの利用者で動かした。
- Windows の PATH の `python3` は代わりの物のまま（Git Bash の `command -v python3` は `…/WindowsApps/python3`、起動すると終了の値 49）。
- 鍵: どちらの OS も、鍵を環境変数でだけ渡す形にした。`.credentials.json` が無いことを、試しの前と後に確かめた。Linux は `docker exec -e` で、Windows は vm.sh の ssh で渡した。どちらもコマンドの引数には値を出していない。
- 試しの会話に渡した頼みの文は「guide.md に、このフォルダの使い方を 400 字ほどの日本語で Write のツールで書く。知らせが出たら、その文をそのまま引く」。`--permission-mode acceptEdits --max-budget-usd 1` を付け、フックの出力は `--output-format stream-json --verbose --include-hook-events` の hook_response の行で見た。
- `claude -p` は Linux で 2 回、Windows で 1 回回した。
  - Linux の 1 回目は `--permission-mode` を付け忘れた。Write が許されず、Stop のフックが読む文書ができなかったので捨てた（0.05 ドル）。
  - Linux の 2 回目は 0.03 ドル、Windows は 0.05 ドル。
  - アカウントは使用率の控えのいちばん低い p3。試しの会話のモデルはアカウントの既定。

## 確かめた物

### 1. ログインへ導く 1 行（4341c7c4・86b1c6a9）

- どちらの OS でも、Stop のフックが guide.md を読み手に読ませ、読み手は「Not logged in · Please run /login」で起動しなかった（知らせに「認証: none」と添えてある）。Claude Code 2.1.311 でも、フックの環境には `CLAUDE_CODE_OAUTH_TOKEN` が渡っていない。
- 知らせ（Stop の additionalContext と systemMessage の両方）に、次の 1 行が足された。Windows ではパスが `C:/Users/dev/.claude/.credentials.json` になった。

  > coldread の読み手は、ログインの認証が無いので読めなかった(フックの環境に鍵が無く、/home/tester/.claude/.credentials.json も無い)。鍵を環境変数 CLAUDE_CODE_OAUTH_TOKEN でだけ渡していると、Claude Code はフックにその値を渡さない(`claude setup-token` で作り直しても直らない)。`claude auth login` でログインして、このファイルを作る(gates の README の「When the reader is not logged in」)。持ち主に 1 行で伝える。

- 試しの会話の主は、どちらの OS でもこの知らせを受けて、`claude auth login` でログインすれば直ると答えた。
- 外部投稿ゲート（gh の投稿の前の読み）と `branch-check` は、同じ部品（`_no_login`）を通るが、今回は試していない。

### 2. 読み直しのコマンドの形（86b1c6a9）

- 知らせの「手で読ませるなら」の後のコマンドは、どちらの OS でも `bash <gates のフォルダ>/hooks/run-python.sh <gates のフォルダ>/hooks/coldread-gate.py read <パス>` の形だった。Windows では、パスが Git Bash でそのまま打てる `C:/Users/dev/.claude/plugins/cache/raiki61/gates/0.44.2/hooks/…` の形で書かれた。
- Windows の Git Bash で、このコマンドを知らせの字のまま打った。入口（`run-python.sh`）が本物の Python 3.15 を選んで `coldread-gate.py` が動き、上の 1 の 1 行を出して終了の値 1 で終わった。同じ機械の素の `python3` は代わりの物に当たり、終了の値 49 で終わった。
- Linux でも同じコマンドを打ち、同じ結果だった。
- 「メインブランチに入れる前の読み」と「初見読みの待ちの一覧が残っている」の知らせも同じ関数（`read_cmd`）でコマンドを作るが、知らせとして出るのは試していない。

### 足し: README の手順でシェルから入れる（頼み 20261026-112324-bf6693 の直しの確かめ）

convergence-loops の README の「Dependencies and how you obtain them」の手順を、モデルを呼ばない `claude plugin` のコマンドだけで試した。

- 入れる手順（公式の marketplace を登録 → raiki61 を登録 → install）: Linux のまっさらなコンテナと、公式の marketplace が未登録の Windows の VM の両方で、pr-review-toolkit も一緒に入った。`claude plugin list` で convergence-loops・graphloops・gates・pr-review-toolkit が全部 enabled だった。
- 入れて失敗した後の直し方（Linux だけで試した）: 公式の marketplace を消してから convergence-loops と graphloops を入れ、2 つとも「failed to load」になる形を作った。
  - 登録の前の `claude plugin install pr-review-toolkit@claude-plugins-official` は、README が書くとおり「not found in marketplace」で失敗した（終了の値 1）。
  - README の 3 行（公式を登録 → pr-review-toolkit を入れる → `claude plugin list`）で、convergence-loops と graphloops が enabled に戻った。
  - Claude Code 2.1.311 では、1 行目の `marketplace add` が欠けていた依存をその場で入れた（「+ 1 dependency: pr-review-toolkit」）。2 行目は「already installed」と出て、害は無い。新しい会話を開いて読み込まれるか（README の「start a new Claude Code session」）は、モデルを呼ぶので試していない。

## 片付けと鍵

- Linux: 試しのコンテナ `gates-trial-linux` とイメージ `gates-trial` を、名前を指して消した。`.credentials.json` は最後まで無かった。鍵の頭の字（`sk-ant-`）で家のフォルダを探した当たりは、見えた物がプラグインの台本（`claude_auth.py` など）だった。当たり 21 件の全部の場所を確かめる前にコンテナを消した。鍵はコンテナの外へは出していないので、今は残っていない。
- Windows:
  - 消す前に、家のフォルダの下のファイル（`AppData\Local\Microsoft` を除く）を鍵の形（`sk-ant-<種類>-` の後に 40 字以上）で探し、当たりは 0 だった。
  - 入れた 4 つのプラグインを外し、marketplace の raiki61 と claude-plugins-official を消した。プラグインのキャッシュとデータ、gates の状態（`coldread-gate`）、試しのリポジトリ `~\proj` とその会話の記録、持ち込んだ頼みの文・台本・出力も消した。
  - `~\.claude\settings.json` は試しの前の形（`env` の `HTTPS_PROXY` と `NO_PROXY` だけ）に戻した。
  - Claude Code は 2.1.311 に上げたまま残した。VM は動いたまま。
- 鍵の値は画面にもファイルにも出していない。gh の鍵は使っていない。
- Colima の Docker のふつうのネットワーク（bridge）からは外へ出られなかった（github.com・deb.debian.org とも時間切れ）。そのため、コンテナは `--network host` で動かし、apt と Claude Code は Mac の `HTTPS_PROXY` を通した。この Mac のネットワークの事情で、プラグインの詰まりではない。
