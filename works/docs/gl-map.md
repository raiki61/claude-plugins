# accept.py から本線の gl.py への対応表

works の受け付けの口 `works/.shared/core/accept.py` を、本線 graphloops の `graphloops/scripts/gl.py` へ載せ替える日のための対応表。表の本体は `works/.shared/core/gl_map.json`、試験は `works/tests/test_gl_map.py`。

## なぜ在るか

- 受け付けの口は、本線の 3-8 が版に入るまで `accept.py` のまま（線 A の裁定 TA25）。`accept.py` に検査を足さない。works だけの検査は各ブロックの受け付けのスクリプトに置き、この表に載せる。
- 本線の返答（2026-09-27）で、gl に足りない物は 4 つ: 依頼に依らない検査の口・役の schema から注記を外す口・判定の受け付け・差分を切る段。3-6 の続きで一部が入り、残りは 3-8 で入る。ブロックの名前は 3-7 の後に決まる。

## 表の形

1 行 = `{works, gl, status, note}`。

- `works`: works の側の関数。`accept.<関数>` は `accept.py` の公開の関数。ほかは `entry.take` やブロックのスクリプトの `<パス>:<関数>`。
- `gl`: 本線の相手の口（`gl accept <節>` など）。相手が無ければ空。
- `status`:
  - `ready`: gl に同じ口が在る（載せ替えの条件は note）。
  - `missing`: gl に無い。
  - `works-only`: graphloops に無い works だけの検査。gl へ移さない。
- `note`: 違いと、入る段。読んだ本線の版（d1b863f など）を書く。

## 試験が見ること

- `accept.py` の公開の関数（名前が `_` で始まらない一番外の `def`）の全部が、表に 1 度ずつ在る。関数を足しても消しても赤になる。
- 足りない 4 つが `missing`、works だけの検査（`snapshot_tree`・`tree_state`・`tree_change`・`check_claims`・`check_no_post`）と修正役の後始末（`leftovers.py` の 3 つ）が `works-only`。

## 読んだ版と残り

- 表は 3853b9a の `accept.py` を写した。本線は `wip/fn-shape` の d1b863f（gl.py 208 行）と、`wip/fn-shape2` の commit 前の差分（`gl request`・`gl exit --strip-notes`）を読んだ。
- `wip/archon-pack` が足した 3 つ（`ignored_files`・`record_ignored`・`remove_new_ignored`）は、合流の時には `accept.py` から `blk-fix/scripts/leftovers.py` へ移っていた（0b851c8）。表では `blk-fix/scripts/leftovers.py:<関数>` の 3 行（`works-only`）に分けた。
- `wip/works-a27` が足した 2 つ（`tree_state`・`tree_change`。読むだけの任せ先の役の前後の作業ツリーの姿と違いの文。裁定 R47）は、`accept.py` の共通の部品として `works-only` の行に載せた。
- 線 B の行（`judge2.check`・`close.final_gate_reply`・`rounds_validator`）は、線 B が最後の共有の commit で足す。
