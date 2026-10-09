<!-- coldwrite:skip 内部の設計書。語は works/docs/concepts.md で定義 -->
# 並べの枝（考え `lanes`）の住処を 1 つにする（実装計画）

> **実装する者へ:** superpowers:executing-plans で Task ごとに進める。手順は `- [ ]` で追う。

**目的:** TDD の輪の並べ（`blk-fix/lib/tddlanes.py`）と修正役の並べ（`blk-fix/lib/fixlanes.py`）が同じ形で持つ枝の仕組みを `blk-fix/lib/lanekit.py` に寄せ、段のモジュールには段にしか無い差し替え口だけを残す。振る舞いは変えない（枝は本番で既定 on。canary (k) と修正役の枝の canary で確かめ済み）。

**作り:** lanekit に純粋な部品を足し、段のモジュールの写しをその呼び出しに置き換える。段の骨組み（支度・確かめ・締め）は段ごとに控えの置き場・誤りの型・出口の形が違うので、枠（template）にはしない。

**道具:** Python 3（標準ライブラリだけ）・unittest。

**仕様:** `works/docs/concepts.md` の `lanes` の行。

## 二重の物と行き先

| 二重の物（tddlanes / fixlanes） | 行き先 |
| --- | --- |
| `lane_nodes()` / `lane_nodes()` | `lanekit.node_names(pattern)` |
| `groups(queue, items)` / `groups(rows)` | `lanekit.groups(rows)` |
| `_lane_state` の実行器の読み替え / `_tests_state` の同じ物 | `lanekit.relocate(path, repo, tree)` |
| `fork` の空の出口の手組み / `lanekit.fork_out([])` | `lanekit.fork_out([])` |
| `_tree_ok(row)` / `_tree_ok(lst)` | `lanekit.tree_ok(row)`（行の `tree`・`git` を読む形に） |
| `_apply_lanes`＋`_merge` の順の当て / `join` の中の同じ輪 | `lanekit.merge_in_order(lanes, merge_one)` |
| `JOINED`・`MERGED`・`BACK` / 同じ 3 語 | `lanekit.JOINED`・`MERGED`・`BACK`（段は別名で持つ） |

段に残す差し替え口: 何を枝に分けるか（`plan`・`candidates`・`assign`）・枝の控えの形と置き場・枝の役の指示書（`lane_prep`・`_next_text`・`unit_text`・`_item`）・枝の確かめ（`lane_step`・`check`・`_park`）・当てる時の段の照らし（TDD の `_moved_tests`、修正役の git の誤りの受け止め）・当てた後の確かめ（TDD の `_green_after`・`_retry_without_later`、修正役の結末の文 `summary_text`）。

枝の数の写し（`blk-fix/blk-fix.yaml` の `<段>-lane-loop-1..3`・`.shared/core/adapter.py` の `KEYED_NODES`・`.shared/core/seat.py` の `SEATS`・`SKILL_NODES`・`AGENT_NODES`）: YAML は Archon が字で並べる物、包みと座は core でブロックを読めない（ブロックの独立）。どれも試験が `lanekit.MAX_LANES` と縛る（`test_tdd_lane_wiring`・`test_fix_lane_wiring`・`test_adapter_lane`・`test_seat`）。座の表の縛りが「含む」だけだったので、ちょうど揃うことを縛る試験を足す。

## Task 1: lanekit に部品を足す（試験が先）

- [ ] `tests/test_lanekit.py` に `node_names`・`groups`（項目でつながる物は 1 組・順を保つ・タグの無い物は 1 つで 1 組）・`relocate`（中なら木の下・外ならそのまま）・`tree_ok(row)`・`merge_in_order`（前の枝の `names` が後の枝の `earlier` に入る・拒んだ枝の物は入らない）・`fork_out([])` を書いて赤を見る
- [ ] `lanekit.py` に実装して緑

## Task 2: 段のモジュールを置き換える

- [ ] tddlanes・fixlanes の上の表の物を lanekit の呼び出しに。既存の試験 `test_tdd_lanes`・`test_fix_lanes`・`test_fix_lane_wiring`・`test_tdd_lane_wiring`・`test_blk_fix*`・`test_adapter_lane` を緑のまま
- [ ] 座の表の枝の名がちょうど `tddlanes.lane_nodes()`・`fixlanes.lane_nodes()` と揃う試験を足す

## Task 3: 地図と柵

- [ ] `docs/concepts.md` の `lanes` を住処あり（住処 `blk-fix/lib/lanekit.py`）に、`docs/concepts.json` に柵（union-find の `parent[parent[`・枝の数の輪 `range(1, MAX_LANES + 1)`・出口の鍵 `lane_{n}"`・`.git` の 1 行の読み `_git_line(`・`MAX_LANES = <数>`）。知ってよい所は lanekit と unitlanes
- [ ] `test_concept_fences` を緑。CHANGELOG の `## [Unreleased]` に 1 行

## 見るべき所（試験が直に当たらない物）

- 修正役の締めで git が効かない枝: `merge_one` の中で受け止めて戻す（前と同じ。TDD の段は前どおり受け止めない）
- 段の `groups` の入力の形の違い（TDD は単位 → 項目、修正役は項目 → 単位）: どちらも `(id, タグ)` の並びに直して渡す
