"""並べの枝の部品（blk-fix。依頼 243 の並べ。設計 docs/plans/2026-10-07-fix-lane-nodes.md の「枝の部品」の節）。
TDD の輪の並べ（tddlanes。docs/plans/2026-10-07-lane-nodes.md）と修正役の並べ（fixlanes）が同じ形で使う、段に依らない部分だけを
持つ。どちらの段も Archon の節の形は同じ:

  <段>-fork（枝を切る）→ <段>-lane-loop-<n>（支度 → 枝の役（旗 lane）→ … → 確かめ）×MAX_LANES → <段>-join（締める）→ 順の輪

段が持つのは、何を枝に分けるか（TDD は項目を共にする単位の組、修正役は単位を共にする修正案の項目の組）・枝の役の指示書・枝の
確かめ（TDD は tddloop.step の赤・緑、修正役は受け付けと同じ事実の確かめと範囲の相談）・当てた後の確かめ（TDD は合わせた木の緑と
意味の食い違いの逃げ道、修正役は修正の輪の受け付け）だけ。ここはそれ以外を持つ:

口:
- MAX_LANES: 枝の輪の数（両方の段の YAML の <段>-lane-loop-1..3 と包みの adapter.KEYED_NODES。試験が縛る）
- fork_out(ns): 節 <段>-fork の出口 {go, lanes, lane_1..lane_<MAX_LANES>}（ns は切った枝の番号。1..k の連番でなければ ValueError）
- plant(repo, ns, place, manifest, union=()): 前の単位の worktree を片付け、run の作業ツリーの今の姿を base に枝ごとの単位の
  worktree（place/item-<n>）を切る（unitlanes.plant）。{n: {tree, git, base}}
- tree_ok(tree, git): 単位の worktree の `.git` の 1 行が切った時と同じなら空、違えば理由（役が指しを書き換えた枝は当てない）
- mark(board_dir, node, key, tree): 包みが読む 2 つの印を書く: 単位の鍵（adapter.session_key_path。替われば包みが新しい会話で
  起こす）と単位の worktree（adapter.lane_tree_path。盤面の下。包みの旗 lane が子の cwd にする）
- revert_strays(repo, base, keep=()): 枝の間に run の作業ツリーで変わったファイル（keep の外）を base の姿に戻す（枝の役は包みの
  柵で書けない。受け止め）。戻したパス
- merge(repo, tree, *, since, base, log, declared, made, kept, union, earlier): 枝の差分を run の作業ツリーへ 3 方向で当てる
  （書き込みの記録の無い変更・当たらない差分・当てた中身が単位の worktree と違う物は当てない）。Merge（why・patch・names・unioned・
  clash）
- shared(patches): 2 本以上の枝の差分に出たファイル
- carry(log, repo, applied, shared): 当てた枝の書き込みの記録を run の作業ツリーへ写す（unitlanes.carry_records）
- claim_problems(claims, repo, board_dir, owed, try_query, briefs): 食い違いの申し出（1 件か並び）の機械の確かめ（conflict.problems）
- park(board, claims, source): 確かめた申し出を盤面の控えに積む（conflict.park。裁定の輪が読む）
- remove(repo, trees): 単位の worktree と守りの参照を片付ける
"""
from __future__ import annotations

import pathlib
import sys
from typing import NamedTuple

sys.dont_write_bytecode = True   # 下の import が pack の中に __pycache__ を作らないように（必ず import より前）

_HERE = pathlib.Path(__file__).resolve().parent
for _p in (_HERE.parents[1] / ".shared" / "core", _HERE):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import adapter  # noqa: E402  （L2。包みが読む 2 つの印の置き場）
import conflict  # noqa: E402
import tddloop  # noqa: E402  （木の固め・戻し・印の書き）
import unitlanes  # noqa: E402
import unittrees  # noqa: E402
import writes  # noqa: E402

MAX_LANES = 3


class Merge(NamedTuple):
    why: str          # 当てなかった理由（当てたら空）
    patch: str        # 控えた枝の差分のファイル（差分を作る前に戻した時は空）
    names: list       # 当てた差分のパス（当てなかったら []）
    unioned: list     # 試験のファイルの挿しだけの食い違いを合わせたパス
    clash: bool       # 字の食い違いで当たらなかった


def fork_out(ns) -> dict:
    """節 <段>-fork の出口（頭の注記）"""
    ns = list(ns)
    if ns != list(range(1, len(ns) + 1)) or len(ns) > MAX_LANES:
        raise ValueError(f"枝の番号が 1..{MAX_LANES} の連番でない（{ns}）")
    return {"go": bool(ns), "lanes": len(ns), **{f"lane_{n}": n in ns for n in range(1, MAX_LANES + 1)}}


def plant(repo, ns, place, manifest, union=()) -> dict:
    """枝ごとの単位の worktree を切る（頭の注記）"""
    trees = unitlanes.plant(repo, list(ns), place, manifest, union)
    return {n: {**row, "git": unitlanes._git_line(row["tree"])} for n, row in trees.items()}


def tree_ok(tree, git: str) -> str:
    """単位の worktree の指しの確かめ（頭の注記）"""
    if git and unitlanes._git_line(tree) == git:
        return ""
    return f"単位の worktree {tree} の .git の指しが切った時と違う（この枝は当てず、順に戻す）"


def mark(board_dir, node: str, key: str, tree) -> None:
    """包みが読む 2 つの印（頭の注記）"""
    tddloop.write_key(adapter.session_key_path(str(board_dir), node), key)
    tddloop.write_key(adapter.lane_tree_path(str(board_dir), node), str(tree))


def revert_strays(repo, base: str, keep=()) -> list:
    """枝の間に run の作業ツリーで変わったファイルを戻す（頭の注記）"""
    stray = sorted(set(tddloop.touched(repo, base, tddloop.snapshot(repo))) - set(keep))
    if stray:
        tddloop.restore_paths(repo, base, stray)
    return stray


def merge(repo, tree, *, since: str, base: str, log, declared=(), made=(), kept, union=(), earlier=(), check=None) -> Merge:
    """枝の差分を当てる（頭の注記）。since は枝の役が書いた変更の起点（書き込みの記録と突き合わせる）、base は差分の起点（切った時の
    run の作業ツリーの姿）、kept は差分を控えるファイル、earlier は前に当てた枝の差分のパス（そのファイルは中身の照らしから外す）。
    check（段の照らし。当てたパスの並び → 戻す理由か空）が理由を返せば、当てた物を戻して当てない"""
    repo, tree, log = pathlib.Path(repo), pathlib.Path(tree), pathlib.Path(log)
    moved = sorted(set(tddloop.touched(tree, since, tddloop.snapshot(tree))) - set(made))
    if log.is_file():
        left = writes.unrecorded(tree, moved, log, list(declared))
        if left:
            return Merge(writes.REJECT + ", ".join(left[:10]), "", [], [], False)
        writes.keep_declared(log, tree, list(declared))
    patch = unittrees.diff(tree, base)
    kept = pathlib.Path(kept)
    kept.parent.mkdir(parents=True, exist_ok=True)
    kept.write_text(patch, encoding="utf-8", errors="surrogateescape")
    before = tddloop.snapshot(repo)
    got = []
    ok, why = unittrees.apply(repo, patch, union=union, unioned=got, check=unitlanes.tests_unique)
    if not ok:
        return Merge(f"差分が run の作業ツリーに当たらない（{' '.join(why.split())[:300]}）", str(kept), [], [], True)
    names = unitlanes._names(patch)
    differ = [n for n in names if n not in set(earlier) and not unitlanes._same(repo / n, tree / n)]
    why = f"当てた中身が単位の worktree と違う（{differ[:5]}）" if differ else (check(names) if check else "")
    if why:
        tddloop.restore_paths(repo, before, names)
        return Merge(why, str(kept), [], [], False)
    return Merge("", str(kept), names, got, False)


def shared(patches) -> list:
    """2 本以上の枝の差分に出たファイル（patches は差分のファイルの並び）"""
    seen = {}
    for patch in patches:
        for n in unitlanes._names(pathlib.Path(patch).read_text(encoding="utf-8", errors="surrogateescape")):
            seen[n] = seen.get(n, 0) + 1
    return sorted(n for n, c in seen.items() if c > 1)


def carry(log, repo, applied, shared_files) -> None:
    """当てた枝の書き込みの記録を写す（applied は [(単位の worktree, 差分のファイル)]）"""
    unitlanes.carry_records(log, repo, applied, shared_files)


def claim_problems(claims, repo, board_dir, owed, try_query=None, briefs=None) -> list:
    """食い違いの申し出（1 件の dict か並び）の機械の確かめの文（通れば空。並びは 2 度申し出た単位も見る）"""
    return conflict.problems([claims] if isinstance(claims, dict) else claims, repo=repo, board_dir=board_dir, owed=set(owed),
                             try_query=try_query, briefs=briefs)


def park(board, claims, source: str) -> list:
    """確かめた申し出を盤面の控えに積む（無ければ何もしない）。積んだ・在った行の id"""
    return conflict.park(board, list(claims), source=source) if claims else []


def remove(repo, trees) -> None:
    """単位の worktree を片付ける"""
    for t in trees:
        unittrees.remove(repo, t)
