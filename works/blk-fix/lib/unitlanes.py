"""単位の worktree で項目・枝を並べる共通の部品（blk-fix。依頼 243 の並べ。設計 docs/plans/2026-10-06-parallel-units.md・
docs/plans/2026-10-07-overlap-lanes.md）。分け方・切る・合わせの照らし・書き込みの記録の写しを機械が持つ。使い手は TDD の輪の並べの
枝（tddlanes。docs/plans/2026-10-07-lane-nodes.md）と修正役の並べの枝（fixlanes。docs/plans/2026-10-07-fix-lane-nodes.md）で、
どちらも差分を当てるのは sandbox の外の機械の節（締めの節）。前の形の、修正役が役の sandbox の中の Bash で走らせた当てるコマンド
（merge・command）と修正の輪の締めの節 fix-units（settle・settled）は、修正役の並べが Archon の節になった時に外した。

語:
- 範囲: 項目の書いてよいパスの glob と受け入れのテストのファイル（planmarks の allowed_paths・test_paths）。引けなければ None
- 重なりのファイル（shared）: 当てた項目・枝のうち 2 つ以上の差分に出たファイル。範囲の重なりの見込み（expect）とは別に数える
  （依頼 243 の並べの 3 段目。範囲が重なる項目も並べ、当てる所で食い違った物だけ順に戻す）
- 合わせる試験のファイル（union）: 2 つの枝が同じ所に行を足しただけの食い違いは、先の枝の行の後に後の枝の行を置いて当てる
  （unittrees.apply の union）。合わせた中身に同じ名のテストの定義が 2 つ在れば合わせない（tests_unique）
- 単位の worktree: unittrees が run の作業ツリーの今の姿を base にして切る worktree。置き場は run ごとの置き場の下（包みの旗 lane が
  枝の役の cwd にする所。adapter.lane_cwd）

口:
- overlap(a, b): 2 つの範囲が重なりうるか（字のままの頭で比べる。広く重なりと見る側に倒す）
- lanes(items): [(n, 範囲 | None)] のうち並べる項目の番号（範囲の在る物。範囲が重なってもよい。2 つ未満なら []）
- expect(items): 並べる項目のうち範囲が重なりうる組 [[n, m]]（重なりの見込み。測りに出す）
- tests_unique(path, text): 合わせた中身の照らし（.py なら同じ本体に同じ名の test・Test の定義が 2 つ無いか。読めなければ偽）
- plant(repo, items, place, manifest, union=()): 前の単位の worktree を片付け、今の姿を base にして項目ごとに place/item-<n> を
  切り、控えを書く（使い手が自分の控えで上書きしてよい）。{n: {tree, base}}
- carry_records(log, repo, applied, shared): 当てた枝の単位の worktree の書き込みの記録を run の作業ツリーへ写す（重なりでない
  ファイルは writes.carry、重なりのファイルは writes.carry_merged）。applied は [(単位の worktree, 当てた差分のファイル)]
"""
from __future__ import annotations

import ast
import json
import os
import pathlib
import sys

sys.dont_write_bytecode = True   # 下の import が pack の中に __pycache__ を作らないように（必ず import より前）

_CORE = pathlib.Path(__file__).resolve().parents[2] / ".shared" / "core"
if str(_CORE) not in sys.path:
    sys.path.insert(0, str(_CORE))

import unittrees  # noqa: E402

TREE = "item-{n}"
_GLOB = "*?["


def _head(pattern: str) -> str:
    """glob の字のままの頭（最初の * ? [ の前まで）"""
    cut = min((pattern.index(c) for c in _GLOB if c in pattern), default=len(pattern))
    return pattern[:cut]


def overlap(a, b) -> bool:
    """範囲 a と b（glob の並び）が同じパスに当たりうるか。頭の片方がもう片方の頭で始まれば重なると見る"""
    for x in a:
        for y in b:
            hx, hy = _head(x), _head(y)
            if hx.startswith(hy) or hy.startswith(hx):
                return True
    return False


def lanes(items) -> list:
    """[(n, 範囲 | None)] のうち並べる項目の番号（並びのまま）。範囲が None の項目は順。範囲が重なっても並べる（当てる所で
    食い違った項目だけ順に戻す。依頼 243 の並べの 3 段目）"""
    out = [n for n, p in items if p is not None]
    return out if len(out) >= 2 else []


def expect(items) -> list:
    """[(n, 範囲 | None)] のうち範囲の在る項目どうしで、範囲が重なりうる組 [[n, m]]（n < m の並びの順）"""
    known = [(n, list(p)) for n, p in items if p is not None]
    return [[n, m] for i, (n, p) in enumerate(known) for m, q in known[i + 1:] if overlap(p, q)]


def tests_unique(path: str, text: bytes) -> bool:
    """合わせた中身 text（path のファイル）の照らし: .py なら、モジュールとクラスの本体ごとに test・Test で始まる定義の名が
    2 つ無いか（後の定義が前を隠す）。読めない（構文の誤り・文字の誤り）なら偽。.py でなければ真"""
    if not str(path).endswith(".py"):
        return True
    try:
        tree = ast.parse(text.decode("utf-8"))
    except (SyntaxError, ValueError):
        return False
    kinds = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
    bodies = [tree.body] + [n.body for n in ast.walk(tree) if isinstance(n, ast.ClassDef)]
    for body in bodies:
        names = [n.name for n in body if isinstance(n, kinds) and n.name.lower().startswith("test")]
        if len(names) != len(set(names)):
            return False
    return True


def _git_line(tree) -> str:
    try:
        return (pathlib.Path(tree) / ".git").read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def _write_json(path: pathlib.Path, doc) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(doc, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def plant(repo, items, place, manifest, union=()) -> dict:
    """前にこの作業ツリーから切った単位の worktree を片付け、今の姿を base にして項目ごとに place/item-<n> を切り、控えを書く
    （union は合わせる試験のファイルの並び。頭の語）"""
    repo, place, manifest = pathlib.Path(repo), pathlib.Path(place), pathlib.Path(manifest)
    unittrees.sweep(repo)
    base = unittrees.snapshot(repo)
    rows, out = [], {}
    for n in items:
        tree = place / TREE.format(n=n)
        if tree.exists():   # 前の run の残り（登録は sweep が外した）
            import shutil
            shutil.rmtree(tree)
        unittrees.add(repo, base, tree)
        rows.append({"item": n, "tree": str(tree), "git": _git_line(tree)})
        out[n] = {"tree": str(tree), "base": base}
    _write_json(manifest, {"repo": str(repo), "base": base, "place": str(place), "union": sorted(set(union)), "items": rows})
    return out


def _names(patch: str) -> list:
    """patch の行先のパス（`diff --git a/x b/x` の b 側。--no-renames なので a と同じ）"""
    out = []
    for ln in patch.splitlines():
        if ln.startswith("diff --git a/") and " b/" in ln:
            name = ln.rsplit(" b/", 1)[1]
            if name not in out:
                out.append(name)
    return out


def _same(a: pathlib.Path, b: pathlib.Path) -> bool:
    try:
        return a.read_bytes() == b.read_bytes()
    except OSError:
        return not a.exists() and not b.exists()


def carry_records(log, repo, applied, shared) -> None:
    """当てた枝の書き込みの記録を run の作業ツリーへ写す（頭の注記。受けた枝が決まった後に 1 度だけ）。記録が無ければ何もしない"""
    import writes   # .shared/core（L3）

    log = pathlib.Path(log)
    if not applied or not log.is_file():
        return
    shared = set(shared)
    pairs, srcs = [], {}
    for tree, patch in applied:
        tree = pathlib.Path(tree)
        for n in _names(pathlib.Path(patch).read_text(encoding="utf-8", errors="surrogateescape")):
            if n in shared:
                srcs.setdefault(n, []).append(tree / n)
            else:
                pairs.append((tree / n, pathlib.Path(repo) / n))
    if pairs:
        writes.carry(log, pairs)
    for n, src in srcs.items():
        writes.carry_merged(log, pathlib.Path(repo) / n, src)
