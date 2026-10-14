# coldwrite — 退いた plugin

coldwrite は、Write で書かれる文書を書き込みの前に初見の読み手（coldreader）に読ませ、詰まりが直るまで書き込みを止める門番だった。この役は gates の coldread に移り、coldwrite は 0.2.0 でフックを持たない最後の版になった。入れているなら外し、gates を入れる。

```sh
claude plugin uninstall coldwrite@raiki61
claude plugin install gates@raiki61
```

移った先の振る舞い（詳しくは [gates/README.md](../gates/README.md) の「coldread — 手元の文書」）:

- 書き込みは止めない。Write・Edit で書いた文書の名前を記録し、ターンの終わりに 1 本 1 回だけ読ませて、詰まりが在れば指摘を返す。
- Edit で書いた文書も、書いた後のファイル全体を読む。coldwrite は prompt 型フックで道具に渡した中身だけを見ていたので、Edit では差し替えた数行しか読めず、Write だけを見ていた。
- 1 行目の `coldwrite:skip` の印は、移った先でもそのまま効く。

版ごとの変更は [CHANGELOG.md](CHANGELOG.md) に在る。
