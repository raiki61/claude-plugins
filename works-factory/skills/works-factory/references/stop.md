# 走っている run を止めた後

承認ノードの間で走っている run を `WF workflow cancel <run> --cwd <対象>` で止めた後の扱い。`WF` はこのプラグインの `bin/works-factory`。`<run>` は起動した run（子の run でなく、周の鎖なら鎖の run）の id で、`WF workflow runs --cwd <対象>` の頭 8 字でもよい。cancel で止めた run は報告を出さない。

`--detach` は `WF workflow run` に付ける旗で、run を裏で走らせて起動のコマンドをすぐ返す。スキルの「2. 起動する」の形（Bash の run_in_background で起動し、`--detach` を付けない）で起動した run は、下の「`--detach` を付けずに起動した run」に当たる。

- 殻は cancel の後に、その run と子の run が起動した AI のプロセスも止め、止めた物と残った物を 1 行ずつ（pid とコマンド名）出す。追えなかった時は訳を、環境変数を読めない時は手で探す 1 行のコマンドを出す。
- `--detach` を付けて起動した run は cancelled になり、resume できない。やり直すなら新しい run を起動する。`WF workflow abandon <run> --cwd <対象>` は run と子の run の作業ツリーを消すだけ。作業ツリーに残った変更も消えるので、要るなら先に対象へ当てる。
- `--detach` を付けずに起動した run は、殻が起動元のプロセスを止めて failed にする。その後、running のまま残った子の run を abandon し、cancelled にして作業ツリーと未コミットの変更を消す。止めた周の鎖は resume しても続かないので、新しい run を起動する。親もやめるなら `WF workflow abandon <run> --cwd <対象>`。子を abandon できなければ、殻がその id とコマンドを出す。起動元のプロセスが既に消えていた時は子が running のまま残るので、子ごとに abandon を打つ。
- Ctrl-C で止めた run（`--detach` を付けずに起動した run）は AI のプロセスが残るので、cancel を打って止める。
