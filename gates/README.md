# gates — 門番フック集

外に出る操作を、検査が通るまで止める PreToolUse フックを配る。現在の門番は 1 本。

## coldread — 外部投稿の門番

gh で GitHub へ本文を投稿するコマンド(issue/PR のコメント・本文、release notes、gist 等)を
PreToolUse フックで捕まえ、**フック自身が
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

## 網の射程(正直な限界)

判定は「本文を運ぶ旗が gh 自身の引数列にあるか」で行う(単純コマンド単位で帰属を見る。
方式の経緯と次段の PATH シム案は [docs/coldread-gate-next.md](../docs/coldread-gate-next.md))。
次は原理的に対象外・または内容を読まずに止める形で受容している:

- 旗を持たない投稿は対象外: `gh pr create --fill`(本文はコミットメッセージ由来)・エディタ起動(人が対話で書く)
- graphql は `mutation` キーワード検出——`-f query=@file` のようにクエリをファイルで渡す形は素通し
  (`--input file` の方はファイル指定として止まる)
- `gh` がコマンドとして現れない形は判定外: `xargs -I{} gh ...`・`sh -c "gh ..."`・引用の中の gh。
  **判定できない側は素通し(allow)に倒れる**——`env`・`command`・`exec`・`nohup` の前置は判定内だが、
  `sudo`・`timeout` 等それ以外の前置は網に入らない
- 実ファイル・パイプ・変数で渡る本文は内容を読めないため「検査できない」として止める(fail-closed)。
  読める本文が同居していても止める
- 引用が閉じていない・解析が例外で落ちる・上限(既定 10 万字)を超えるコマンドも、投稿かどうか
  確かめられないので止める(fail-closed)
- 1 つのコマンドが複数の本文を運ぶときは、最長の 1 本だけを読み役に渡す
- 本文旗と同じ綴りを持つが投稿でないもの(`gh secret set -b`・`gh variable set -b`・
  `gh workflow run -F`)は表ごと除外している——値を読み役(外部プロセス)へ送らないため

リポジトリ全体の文書の初読検査は convergence-loops の `/firstread-loop`(重い姉)。
こちらは単体で読まれる短文向けの軽い妹で、フックなので呼ばなくても効く。
