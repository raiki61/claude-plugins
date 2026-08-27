# coldread — 外部投稿の門番

gh で issue / PR へ本文を投稿するコマンドを PreToolUse フックで捕まえ、**フック自身が
文脈ゼロの読み手(別プロセスの headless Claude)を走らせて**本文を初見検査する。
理解を妨げる「詰まり」があれば、その指摘を deny 理由に載せて投稿を止める。
「疑問」(理解はできたが答えが本文に無いもの)は止めずに申し送る。

- 検査の実行を書き手の申告に頼らない——「検査した印だけ押して通す」穴が構造的に無い
- 再実行のたびに新しい読み手が直した本文を読む——収束をフックが機械的に駆動する
- 逃げ道は `COLDREAD_SKIP=1` の 1 本(`$CLAUDE_CONFIG_DIR/coldread-gate/skip.log` に記録が残る)
- 400 文字未満の定型返信・読み取り系の gh コマンドには掛からない
- 読み役が起動できない環境でも投稿不能にはならない(deny + 逃げ道の案内)

設定は環境変数(すべて任意): `COLDREAD_MODEL`(既定 sonnet)・`COLDREAD_EFFORT`(既定
medium)・`COLDREAD_MIN_LEN`(既定 400)・`COLDREAD_KEYCHAIN_SERVICE`(macOS で OAuth
トークンを Keychain から読むときのサービス名)・`COLDREAD_READER_CMD`(読み役の差し替え)。

リポジトリ全体の文書の初読検査は convergence-loops の `/firstread-loop`(重い姉)。
こちらは単体で読まれる短文向けの軽い妹で、フックなので呼ばなくても効く。
