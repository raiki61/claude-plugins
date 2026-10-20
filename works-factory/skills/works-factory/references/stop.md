# 走っている run を止めた後

承認ノードの間で走っている run を `WF workflow cancel <run> --cwd <対象>` で止めた後の扱い。`WF` はこのプラグインの `bin/works-factory`。`<run>` は起動した run（子の run でなく、周の鎖なら鎖の run）の id で、`WF workflow runs --cwd <対象>` の頭 8 字でもよい。cancel で止めた run は報告を出さない。

`--detach` は `WF workflow run` に付ける旗で、run を裏で走らせて起動のコマンドをすぐ返す。スキルの「2. 起動する」の形（Bash の run_in_background で起動し、`--detach` を付けない）で起動した run は、下の「`--detach` を付けずに起動した run」に当たる。

- 殻は cancel の後に、その run と子の run が起動した AI のプロセスも止め、止めた物と残った物を 1 行ずつ（pid とコマンド名）出す。追えなかった時は訳を、環境変数を読めない時は手で探す 1 行のコマンドを出す。
- `--detach` を付けて起動した run は cancelled になり、resume できない。やり直すなら新しい run を起動する。`WF workflow abandon <run> --cwd <対象>` は run と子の run の作業ツリーを消すだけ。作業ツリーに残った変更も消えるので、要るなら先に対象へ当てる。
- `--detach` を付けずに起動した run も cancel で止まり、failed になる。続けるなら `WF workflow resume <run> --cwd <対象>`、やめるなら `WF workflow abandon <run> --cwd <対象>`。
- Ctrl-C で止めた run（`--detach` を付けずに起動した run）は AI のプロセスが残るので、cancel を打って止める。
