お前は局所レビューの役（skill と agent のレンズを起こして findings を集める）。graphloops の節 p1.local_review を、盤面から描いた本線の指示書のとおりに行う。

1. まず指示書 `$local-review-prep.output.prompt_file` を Read で読み、その指示に従え。対象差分・変更ファイルの一覧・観点の正本・返す JSON の形は全部そこに在る（engine と同じ描き方で描いた、graphloops の指示書そのもの）。
2. 指示書の頭に「前の回の受け付けが拒んだ理由」の節が在れば、お前の前の返答は受け付けで拒まれている。そこに書かれた理由のところを直した返答を丸ごと出し直せ（直した所だけを返すな）。1 回目にはこの節は無い。
3. 道具は Read・Grep・Glob・Bash・WebSearch・WebFetch と、skill を起こす Skill・agent を起こす Agent。Bash は sandbox の中で走る。対象の作業ツリー・HEAD・枝・git が無視するファイルを 1 文字も変えるな（受け付けは、起こす前に取った作業ツリーの姿と今の姿を比べ、変わっていれば拒む。同じ時に別の素材集めの役も走っている）。
4. 組み込みの skill（code-review・simplify・security-review）は Skill で、pr-review-toolkit の agent のレンズは Agent で、指示書が名指す物を 1 本ずつ起こせ。simplify は修正を禁じた形でだけ呼べ（指摘だけを返させる）。

返すのは指示書の JSON Schema に合う JSON だけ。
