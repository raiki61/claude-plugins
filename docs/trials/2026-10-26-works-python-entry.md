# works 0.7.4 の Python の選び方を、macOS 付属の 3.9 が先頭の PATH で試す（2026-10-26）

- 何の記録か: works（コードの直しを AI の段の流れで回すプラグイン）0.7.4 を、PATH の `python3` が macOS 付属の古い 3.9 の Mac で試した結果。影響するのは、Python 3.11 以上を入れていないか、入れても PATH の `python3` が 3.9 のままの macOS の works の利用者。
- 分かった事: 前の版 0.7.3 は落ちていたが、0.7.4 は「3.11 以上が見つからない」の 1 行で止まり、3.11 以上を PATH の `python3` に置けば先へ進む。今壊れている所は無い。版の付いた名前（`python3.14` など）でだけ入れた人には見つけられない件が 1 つ残り、標準の側は決まりを直し済みで、works の入口の直しはこれから。
- 読み手に求める物: 無い。works の入口の直しは、標準の部署が受け持ちの担当に頼んである（下の「新しく見つけた詰まり」）。

works 0.7.4（main の a7d6a575）で、works の殻（`works/dev/*.sh`）とスキルの本文（`works/skills/works/references/request.md` の `carry.py` の行）が、Python を素の `python3` でなく入口 `works/dev/run-python.sh` で選んで起動する形になった。入口は `python3`・`python`・`py -3` の 3 つの名前を順に起動し、3.11 以上の物を選ぶ。3 つの名前のどれも 3.11 以上でなければ、次の 1 行を出して止まる（入口を直に打ったときは終了の値 1、殻が入口を通して止まったときは 2）。

> works: python 3.11 以上が見つからない（python3・python・py -3 を試した）。python 3.11 以上を入れる（macOS 付属の /usr/bin/python3 は 3.9 で足りない。例: brew install python）

以下、この 1 行を「版の訳」と呼ぶ。

スキルの本文が打たせるコマンドを変えたので、このリポジトリの OS をまたぐ書き方の標準 [docs/standards/cross-os.md](../standards/cross-os.md) の決まり 6（スキルの本文が打たせるコマンドは CI が起動しないので、変えたら実機で試す）のとおり試した（頼み 20261026-123510-e15796）。works は macOS の Apple silicon だけで動き、ほかの機械では入口で止まる（同じ標準の決まり 5）ので、Linux と Windows では試していない。試しの部署は、見つけた事を記録するだけで、works のファイルは直していない。

この記録の言葉:

- 見どころ: 頼みが確かめてほしいと書いた 2 つの事。1 は「PATH の `python3` が macOS 付属の 3.9 のとき、前の版のように TypeError で落ちず、版の訳で止まる」。2 は「3.11 以上の Python を PATH に置くと、それが選ばれて先へ進む」。
- 決まり 1: 同じ標準の、Python を `python3`・`python`・`py -3` の順に起動して要る版以上の物を選ぶ決まり。
- 標準の部署: このリポジトリの書き方の標準（docs/standards/）を受け持つ部署。部署は works-dispatch が立てる、受け持ちを持った Claude Code の会話。受付はその部署への頼みの番号。
- toolset install: `archon.sh` が Archon を起動する前に、隔離した Claude Code の設定にスキルとプラグインを入れる段（`works/dev/toolset.py`）。
- 認証の道・認証の要らない道: `archon.sh` は既定で、Claude Code のログインの鍵（macOS の keychain）を読み、`claude` の実行ファイルを探してから Archon を起動する（認証の道）。環境変数 `WORKS_DEV_NO_AUTH=1` を付けると、鍵も `claude` も使わない道を通る（認証の要らない道）。
- 利用の家・開発の家: works の殻が、Archon の実行ファイルや run の記録を置くフォルダ。`use.sh` は利用の家（既定は `XDG_STATE_HOME` か `~/.local/state` の下の `works/`）を、`archon.sh` を直に打つと開発の家（`WORKS_DEV_HOME`）を使う。
- 「人だけなら止まる」: 利用者が、説明書と画面の言葉のとおりに手を打つだけでは先へ進めない詰まり。AI の助けや作り手への問い合わせが要る物（試しの記録の一覧 [README.md](README.md) と同じ意味）。

## 結果のあらまし

- 見どころの 1（3.9 だけの PATH で落ちずに訳を出す）: 済み。0.7.4 の `use.sh check`・`archon.sh`・入口・`carry.py` の行は、全部が版の訳の 1 行で止まった。前の版 0.7.3 で同じ 3.9 だけの PATH を使うと、`archon.sh` は `TypeError: unsupported operand type(s) for |` で落ちた。
- 見どころの 2（3.11 以上を PATH に置くと、それが選ばれて先へ進む）: 済み。版の訳は消えた。`use.sh check` は Archon の validate まで進んで終了の値 0、認証の要らない道の `archon.sh version` は toolset install を通って Archon の版を出し、0 だった。
- 新しく見つけた詰まりは 1 件で、人だけなら止まる物ではない。3.11 以上の Python が版の付いた名前（`python3.14` など）でだけ PATH に在ると、入口は選べずに版の訳で止まる（下の「新しく見つけた詰まり」）。決まり 1 の候補の並びの話なので標準の部署に問いを回し（受付 20261026-123944-c55c33）、標準の部署は決まり 1 に版の付いた名前を足した（main の 397103eb）。

## 試しの環境

- 機械: macOS 26.6.2 の Apple silicon（arm64）。`/usr/bin/python3` は 3.9.6。
- 入れた版: このアカウントの Claude Code に main の marketplace から入った works 0.7.4（プラグインのキャッシュの `works/0.7.4`）。比べた前の版は同じキャッシュの 0.7.3。
- 3.11 以上の Python: Homebrew の 3.14.7（`/opt/homebrew/bin/python3.14`）。試しのフォルダに `python3` の名前でリンクを置き、そのフォルダを PATH の先頭に足した。
- 殻は `env -i` で、HOME・USER・LANG・TMPDIR・PATH・CLAUDE_CONFIG_DIR だけを渡して起動した。利用の家（`XDG_STATE_HOME`）と開発の家（`WORKS_DEV_HOME`）は、組み合わせごとに試しのフォルダの下の新しい場所にした。
- 対象: 試しのフォルダに `git init` した空のリポジトリ。`use.sh check` を最後まで通す回だけ、手元の bare リポジトリを origin にした。
- Archon の実行ファイル: `PATH=/usr/bin:/bin` には `gh` が無く落とせないので、開発の家の `bin/` に、この機械のキャッシュの物を写した（`archon.sh` が sha256 を確かめる）。
- PATH は次の 2 つ。0.7.4 の `use.sh check` を最後まで通す回と `carry.py` の行の回だけ、`use.sh check` が要る `gh`・`uv`・`claude` のリンクを置いたフォルダも、どちらの PATH にも足した。
  - 3.9 だけの PATH: `PATH=/usr/bin:/bin`
  - 3.11 以上を足した PATH: `PATH=<python3 → 3.14 のリンクのフォルダ>:/usr/bin:/bin`
- `claude -p` は起動していない。AI は呼んでいない。PATH に置いた `claude` は実物へのリンクで、`use.sh check` は在るかを確かめるだけで起動しない。

## 確かめた物

下の表の「版の訳」は上の 1 行。「前提の不足」は origin・`uv`・`claude` が無いという `use.sh` の訳、「claude が無い」は `claude` の実行ファイルが PATH に無いという `archon.sh` の訳。数は終了の値。PATH の列は上の 2 つの PATH で、`gh`・`uv`・`claude` のリンクを足した回は「試しの環境」に書いた回。

| 打った物 | 版 | 3.9 だけ | 3.11 以上を足した |
|---|---|---|---|
| 入口 `run-python.sh -c …` | 0.7.4 | 版の訳・1 | 3.14.7 を選んだ・0 |
| `use.sh check <対象>` | 0.7.4 | 版の訳・2 | validate まで・0 |
| `use.sh check <対象>` | 0.7.3 | 前提の不足・2 | 前提の不足・2 |
| `WORKS_DEV_NO_AUTH=1 archon.sh version` | 0.7.4 | 版の訳・2 | Archon の版・0 |
| `WORKS_DEV_NO_AUTH=1 archon.sh version` | 0.7.3 | TypeError・1 | Archon の版・0 |
| `archon.sh version`（認証の道） | 0.7.4 | 版の訳・2 | claude が無い・2 |
| `archon.sh version`（認証の道） | 0.7.3 | claude が無い・2 | claude が無い・2 |
| `carry.py` の行（入口を通す。`carry-ci --help`） | 0.7.4 | 版の訳・1 | 使い方・0 |
| `carry.py` の行（素の `python3`。`carry-ci --help`） | 0.7.3 | 使い方・0 | 使い方・0 |

### 3.9 だけの PATH

- 0.7.4 では、`use.sh check`・`archon.sh`（認証の道と、認証の要らない道 `WORKS_DEV_NO_AUTH=1` の両方）が、ほかのどの確かめよりも先に版の訳で止まった。認証（keychain）も Archon の実行ファイルも触らなかった。
- 0.7.3 で `WORKS_DEV_NO_AUTH=1 archon.sh version` を打つと、頼みに書かれた落ち方がそのまま出た。toolset install の入口 `dev/toolset.py` が `.shared/core/spseam.py` を読み込む所で落ちる:

  ```
  File ".../works/0.7.3/.shared/core/spseam.py", line 63, in <module>
    def _bad_path(src: pathlib.Path, rel: str) -> str | None:
  TypeError: unsupported operand type(s) for |: 'type' and 'NoneType'
  ```

- 0.7.3 の `use.sh check` は、origin・`uv`・`claude` が無い訳で先に止まり、TypeError には届かなかった。0.7.3 の認証の道の `archon.sh` も、3.9 のまま認証の確かめを通り、`claude` が PATH に無い訳で止まった。どちらも Python の版とは別の所で止まった。
- 0.7.3 の `carry.py` の行（素の `python3 -I …/carry.py carry-ci --help`）は 3.9 でも使い方を出した。`--help` は依頼のファイルを読まないので、3.9 で本当に動くかはこの試しでは分からない。0.7.4 は 3.9 なら打つ前に止まる。

### 3.11 以上を足した PATH

- 入口は `/opt/homebrew/opt/python@3.14/bin/python3.14`（3.14.7）を選んだ。
- `use.sh check` は、origin・`gh`・`uv`・`claude` を揃えた回で Archon の validate まで進み、「Results: 1 valid, 0 with errors, 1 with warnings」で終了の値 0。警告は、`code-review`・`simplify`・`security-review` のスキルがディスクに無いという Archon の validate の物。Claude Code の組み込みのスキルとプラグインのスキルは Claude Code が名前から探すので、validate はディスクに無くても有効として数える（validate の文に「expected for built-in and plugin-qualified skills」とある）。
- `WORKS_DEV_NO_AUTH=1 archon.sh version` は toolset install（0.7.3 が 3.9 で落ちた所）を通り、「Archon CLI v0.11.1」を出して終了の値 0。
- 認証の道の `archon.sh version` は版の訳を出さずに認証の確かめまで進み、`claude` が PATH に無い訳で止まった（PATH を絞ったため。Python とは別の所）。

## 新しく見つけた詰まり

1. 3.11 以上の Python が版の付いた名前でだけ PATH に在ると、入口は選べずに版の訳で止まる。訳は「入れる」と言うが、Python はもう入っている。人だけなら止まる物ではない。版の訳の「python3・python・py -3 を試した」から、利用者は「PATH の `python3` が 3.9 に当たっている」と分かり、3.11 以上の `python3` が先に当たるように PATH を直せば通る。下の 2 つの例は、どちらもこの直しの前の、止まる形。
   - 例 1: `PATH=<python3.14 だけを置いたフォルダ>:/usr/bin:/bin`。
   - 例 2: `PATH=/usr/bin:/opt/homebrew/bin:/bin`。Homebrew の 3.14 の `python3` が `/usr/bin` より後ろに在るので、先に当たるのは `/usr/bin/python3`（3.9）。`/opt/homebrew/bin` を `/usr/bin` より前に置けば通る。
   - 版の付いた名前だけになる入れ方は実在する。uv は既定で版の付いた名前だけを入れる（[uv の文書の Installing Python](https://docs.astral.sh/uv/guides/install-python/)「uv only installs a _versioned_ executable by default.」）。この機械も `~/.local/bin` に `python3.14` だけが在った。
   - 候補の並びは決まり 1 が決め、works-dispatch の `hooks/run-python.sh` などの手本も同じ並びなので、works だけの話ではない。候補に版の付いた名前を足すか、訳の文を直すか、今のままにするかを、標準の部署に問いとして回した（受付 20261026-123944-c55c33）。
   - 標準の部署は、決まり 1 の候補に版の付いた名前（`python3.20` から要る版まで）を足し、止まるときの 1 行に「入っているなら入れた場所を PATH に足す」を加えた（main の 397103eb）。works の `dev/run-python.sh` を含む各プラグインの入口はまだ版の付いた名前を試さず、標準の部署が各担当に足しを頼んだ（cross-os.md の決まり 1 の手本の項）。直した版が出たら、この記録の例 1 で選ばれるかを試す。

## 片付け

- 試しの物は全部、試しの会話の一時のフォルダの下に置いた（対象のリポジトリ・origin・利用の家・開発の家・Python とツールへのリンク）。会話を片付けるときに一緒に消える。利用者の家（`~/.local/state/works`）と Claude Code の設定には書いていない。
- 認証の道の `archon.sh` は、認証の確かめで keychain の項目の名前だけを出した（「認証は keychain の項目 … から拾う（値は出さない）」）。鍵の値は出ておらず、ファイルにも書いていない。
