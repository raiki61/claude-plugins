# 機械が読む値の受け渡しの標準（構造で渡す・黙って崩さない・自作も写しもしない）

プログラムどうし、モデルとプログラム、外のツールとプログラムの間で、機械が読んで分岐や数え上げに使う値（以下「機械が読む値」）をどう渡し、どう読むか。
読むのは、プラグインのコード（Python・シェル・フック）とスキルの出力の形を書く・直す各担当と、この標準を機械で守らせる検査を書く点検。

対象は [README](README.md) の「対象」の 6 つのプラグイン（attention・convergence-loops・gates・graphloops・tiers・works-dispatch）と、ルートの `scripts/`・`tests/`。

急ぐのは、下の「なぜ要るか」の例のうち今壊れている 1 件（attention）だけで、ほかは壊れる余地。新しく書くコードは今日からこの標準に合わせ、今ある物は [README](README.md) の台帳に載せた頼みで各担当が順に直す。

## なぜ要るか

2026-10-19 の洗い出し（標準の担当が持ち主の頼み〔受付 20261018-204600-6563b9。受付は works-dispatch の頼みの番号〕を受けて、読み取り専用のサブエージェント 5 本にコードを読ませた物）で、6 つのプラグインとルートの scripts・tests から、同じ形の作りを 114 件見つけた。
works-dispatch が頼みと納品の題・担当者を日本語の語の正規表現で拾い、想定の外の書き方を黙って崩していた件（受付 20261018-204211-b0df65 が直している）と同じ種類の物が、ほかのプラグインにも広く在る。
どれも、書き方を少し変える・英語で書く・外のツールの版が上がる・ファイルが途中で切れる、のどれかで、知らせずに結果が変わる。

例（どれも洗い出しの時点の main の物）:

- attention の `/what-am-i-doing` は、会話の記録の置き場の名前を、作業場のパスの `/` だけを `-` に替えて作る。Claude Code は英数字以外を全部 `-` に替えるので、`.herdr` を含む作業場では記録が見つからない（今壊れている。手元の `~/.claude-p3/projects/` の名前で確かめた）。
- graphloops の review-loop は、convergence-loops の review-record.py が人向けに出す日本語の行（「前提不成立が確定（escalate）」）を探して、ループの行き先を決める。文言を直すと、黙ってほかの行き先に進む。
- gates の初見読みのゲートは、読み手のモデルの答えを「詰まり:」などの日本語の見出しと「なし」の語で読み、`claude -p` を構造化出力なしで起動する。
- works-dispatch の台帳（`log.jsonl`）を読む 4 か所は、読めない行を黙って飛ばし、読み終えた位置を先へ進める。途中で切れた 1 行で、納品の知らせが誰にも気づかれずに消える。

## 決まり

1. **機械が読む値は構造で渡し、人向けの文から拾わない。**
   - プログラムの出力を別のプログラムが読むときは、JSON（または決めたフィールドを持つ JSON Lines）で渡す。人向けの文は、その構造から最後に作って表示するだけにする。自分が出した人向けの文を、後で正規表現や語で読み直さない。
   - モデルの答えをプログラムが読むときは、`claude -p --output-format json --json-schema <schema>` で起動し、答えの `structured_output` を読む（[Run Claude Code programmatically の Get structured output](https://code.claude.com/docs/en/headless#get-structured-output)「To get output conforming to a specific schema, use `--output-format json` with `--json-schema` … with the structured output in the `structured_output` field.」）。答えの文から見出し・語・コードブロック・最初の `{` を探して拾わない。
   - 前の回の物か、どの行の事か、のような印は、文に添えた語でなくフィールド（`carried: true`・`ref_id` など）で持つ。
   - 読むのは入口の 1 か所にし、そこで構造に直してから中へ渡す（[Parse, don't validate](https://lexi-lambda.github.io/blog/2019/11/05/parse-don-t-validate/)「Ideally, this should happen at the boundary of your system, before any of the data is acted upon.」）。
2. **外のツールの出力は、機械向けの形で読む。**
   - git は `--porcelain`・`-z` の形を使う。人向けの形は版や設定で変わり、porcelain の形は変わらないと git が約束している（[git-status の Porcelain Format Version 1](https://git-scm.com/docs/git-status#_porcelain_format_version_1)「guaranteed not to change in a backwards-incompatible way between Git versions or based on user configuration」）。`git config --get-regexp`・`git ls-tree`・`git log --name-status`・`git diff --numstat` も、値に空白や改行が入りうるときは `-z` を付ける。
   - gh は `--json`（と `--jq`）か `gh api` を使い、表の形の出力を列で切らない（[gh help formatting](https://cli.github.com/manual/gh_help_formatting)）。
   - Claude Code は `--output-format json`、入れたプラグインの一覧は `claude plugin list --json` を使う。
   - 機械向けの形が無く、人向けの出力やエラーの文を読むしかないときは、`LC_ALL=C` を付けて訳されない形で読み、読めなかったときは決まり 4 に従う。その場に「機械向けの形が無い」訳をコメントで書く。
3. **機械が比べる値は言語に依らないキーにし、表示の語と分ける。**
   - 種類・判定・状態・役の既定などの列挙は、ASCII のキー（`accept`・`reject`・`dirty` など）で持ち、日本語の表示の語はキーから引く表を別に持つ。日本語の語・全角の括弧を含む文字列を `==`・`in`・`startswith`・正規表現で比べて分岐しない。W3C は、文の中身のうち機械が読む物（syntactic content）と、訳す物（localizable text）を分けるよう求めている（[Internationalization Best Practices for Spec Developers の 2.4](https://www.w3.org/TR/international-specs/#bp_separate_localizable)「Specifications SHOULD be careful to distinguish syntactic content, including user-supplied values, from localizable text.」）。
   - スキーマの `enum` もキーで書き、モデルには表示の語でなくキーを選ばせる。
   - 英語の利用者が使うプラグインなので、利用者が打つ語（コマンドの引数など）は、日本語だけでなく英語のキーでも受ける。
   - 人が書いた文を「読み物として」扱う物（語の置き換えの `scripts/terms.py` など、日本語の文を見るのが仕事の物）はこの決まりの外。
4. **読めない・壊れた入力を、黙って既定値にしない。**
   - 読めなかった・形が違った・途中で切れた入力は、止めるか、何を読めなかったかを出力に出す。後の処理が読めた物だけで正しく進められる（一覧の表示など）なら出力に出して続け、そうでない（ゲート・分岐・台帳の更新など）なら止める。`except: pass`・`except ...: continue`・空の値を返す、で済ませると、「読めなかった」が「何も無かった」と同じに見える（[PEP 20](https://peps.python.org/pep-0020/)「Errors should never pass silently. Unless explicitly silenced.」）。
   - 黙らせると決めた所は、その場に訳をコメントで書く（PEP 20 の「explicitly silenced」）。
   - 読んだ位置を覚えて続きから読む物（台帳のカーソルなど）は、読めない行の先へ位置を進めない。
   - ゲートとフックは、入力を読めなかったら通さない側に倒す（gates の dest-gate の「検査できないものを黙って通さない」と同じ向き）。
5. **世間の解が使えるものは自作しない。使えないときは 1 か所にまとめる。**
   - プラグインは入れた後に自分のフォルダしか持たず（`scripts/shared-copies.py` の冒頭の実測）、実行時に pip の物を入れられない。だから世間の解は、まず Python の標準ライブラリ（TOML を読む `tomllib`、`json`、`argparse`、`ast` など。[tomllib](https://docs.python.org/3/library/tomllib.html) は Python 3.11 から）と、外のツールの機械向けの口（決まり 2）から選ぶ。
   - 標準ライブラリに無い物（YAML の frontmatter・ファイルのロック・原子的な書き込み・JSON Schema の検査など）は、プラグインの中で 1 か所の実装にし（2 つ以上のプラグインで要るなら決まり 6 の写しの仕組みに載せる）、知らない形を受けたら黙って読み飛ばさずに止める。
   - CI と手元の試験の中（`tests/`）は pip の物を使ってよい（CI は PyYAML を入れている）。試験で YAML を読むときは `yaml.safe_load` を使い、行と字下げで読まない。
6. **プラグインをまたいで同じ処理を写すときは、写しの仕組みに載せる。**
   - 2 つ以上のプラグイン（とルートの `scripts/`）で同じ処理が要るときは、`scripts/shared-copies.py` の印を付けた写しにし、割れたら赤になる検査に載せる。印の無い写しを新しく作らない。
   - 洗い出しでは、印の無い写しが割れて、片方だけ直った物が在った（gates の dest-gate の `owner_repo` と attention の `REPO_TAIL`、ルートの `scripts/spread-plugins.py` の `input_empty` と works-dispatch の入力フィールドの判定）。

## 守らせ方

決まり 3 と 4 の一部は、ルートの `tests/` の検査で、数が増える差分を赤にする。今ある物を一度に直せないので、ファイルごとの数を基準のファイルに置き、増えたら赤・減ったら基準を書き直させる（`scripts/terms.py` と基準の `scripts/terms-baseline.json` と同じ形。基準のファイルの名前と置き場は検査を書く点検が決める）。

- 見るファイル: 対象の 6 つのプラグインとルートの `scripts/`・`tests/` の、git に載った `.py`。シェルは見ない（構文木で読めないので、レビューで見る）。works・works-factory は見ない。
- 決まり 3 の数: Python の構文木（`ast`）で、CJK の字（ひらがな・カタカナ・漢字・全角の記号）を含む文字列の定数が、次のどれかに入る所を 1 件と数える。
  - 比べる式（`==`・`!=`・`in`・`not in`）の左右のどちらか。右がタプル・リスト・集合のときは、その中の定数も数える。
  - `startswith`・`endswith` の引数（タプルの中も）。
  - `re` のモジュールの関数（`re.compile`・`re.search`・`re.match`・`re.fullmatch`・`re.findall`・`re.sub`・`re.split`）の 1 つ目の引数。
  - f-string・変数に入れてから使う物・`match` 文は数えない（構文木だけで決まらないので、レビューで見る）。
- 決まり 3 の外の物（日本語の文を読むのが仕事の `scripts/terms.py` など）は、検査の側で外さず、基準の数に載せる。
- 決まり 4 の数: 本体が `pass` か `continue` の 1 文だけの `except` を 1 件と数える。`except` の行の行末か、本体の文の行末に `#` のコメントがあれば数えない（中身は問わない。中身はレビューで見る）。空の値を返す・カーソルを進める・ゲートを通す側に倒す、は構文木で見分けにくいので数えず、レビューで見る。

検査は点検に頼む（[README](README.md) の「ずれの台帳」の 3 回目の 3-3）。決まり 1・2・5・6 と、上で数えない物（英語のキーでも受けるか、など）は、各担当が直すときにこの標準を読んで合わせ、レビューで見る。

## 直さないと決めた物

洗い出しで見つけた物のうち、次は直しを頼まない。

- gates の初見読みのゲートの、シェルの構文を自分で読む所（heredoc・`$(...)` など）。自作を選んだ訳が docs/coldread-gate-next.md に在り、ほかの解（bashlex など）は実行時に入れられない（決まり 5）。
- graphloops の JSON Schema の検査・テンプレート・プロセスの見張りの自作（engine/schema.py・engine/render.py・engine/role_run.py）。実行時に pip の物を入れられないので自作は決まり 5 に合う。決まり 5 が求める「知らない形を受けたら止める」も、スキーマの知らない keyword を graphloops/scripts/graphcheck.py が赤にするので満たしている。
- Claude Code の会話の記録（`projects/*/<id>.jsonl`）を読む所。記録の形は公開の約束が無いが、ほかに読む口が無い。ただし置き場は、フックの入力の `transcript_path` が取れる所ではそれを使い、取れない所は 1 か所の写しにまとめる（attention と graphloops の 2 か所を、attention の担当〔見渡し〕と graphloops の担当〔見直し〕への頼みに入れた）。
- ルートの `tests/run.sh` の自作の試験の枠組み。pytest への移し替えが進んでいる（tests/py/MIGRATION.md）ので、別に頼まない。
- 標準出力を UTF-8 にする 2 行（`reconfigure(encoding="utf-8")`）が約 70 本に写っている物。壊れる余地が無く、まとめると各スクリプトが写しの仕組みに依るようになる。
- works と works-factory の中の写し（review-record.py の写しが割れている物など）。2 つは誰の受け持ちでもない（[README](README.md) の「対象」）。
- 受付 20261018-204211-b0df65（works-dispatch の頼みと納品を構造で受け取る）と受付 20261018-191631-f0a028（works-dispatch の herdr と Claude Code への縛りを層で切り分ける）が触っている所。2 つに任せる。
