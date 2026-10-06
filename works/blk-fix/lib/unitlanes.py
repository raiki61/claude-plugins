"""修正役の下請けを、範囲の重ならない項目だけ単位の worktree で並べる（blk-fix。依頼 243 の並べ。設計
docs/plans/2026-10-06-parallel-units.md）。分け方・切る・当てる・締めるを機械が持ち、AI は下請けを同時に起こすだけ。

語:
- 項目: 修正役が下請けを起こす単位（修正案の項目か、どの項目にも無い単位 1 つ）。番号は fixrules.g1_values の item
- 範囲: 項目の書いてよいパスの glob と受け入れのテストのファイル（planmarks の allowed_paths・test_paths）。引けなければ None
- 単位の worktree: unittrees が run の作業ツリーの今の姿を base にして切る worktree。置き場は run ごとの置き場の下（包みが
  下請けに書かせる所。adapter.live_worktrees）
- 控え（manifest）: 切った物の JSON {repo, base, place, record, items: [{item, tree, git}]}。git は単位の worktree の `.git` の
  1 行（共通の .git を指す）。盤面の作業ファイルに置く（役は書けない）
- 当てた記録（record）: 置き場の merged.json {items: {"<n>": {state, why?, patch?}}}。state は applied・conflict・broken・empty

口:
- overlap(a, b): 2 つの範囲が重なりうるか（字のままの頭で比べる。広く重なりと見る側に倒す）
- lanes(items): [(n, 範囲 | None)] のうち並べる項目の番号（範囲が在り、ほかのどの項目とも重ならない物。2 つ未満なら []）
- plant(repo, items, place, manifest): 前の単位の worktree を片付け、今の姿を base にして項目ごとに place/item-<n> を切り、
  控えを書く。{n: {tree, base}}
- merge(manifest): 当てるコマンドの中身（修正役が sandbox の中の Bash で走らせる）。項目の番号の順に、`.git` の 1 行を確かめ、
  差分を place/item-<n>.patch に書いて run の作業ツリーへ 3 方向で当てる。新しい object は一時の置き場に書く（共通の .git を
  書かない）。当てた記録に積み、記録に在る項目は当て直さない。{applied, conflict, broken, empty, differ}（differ は当てた項目の
  ファイルのうち、run の作業ツリーの中身が単位の worktree の中身と違う物。役が bash_writes に書く）
- command(manifest): 修正役の指示書に載せる当てるコマンドの 1 行
- settle(manifest, repo, log, keep): 修正役の後・受け付けの前の機械（節 fix-units）。記録の applied（と、記録に無く既に当たって
  いる・機械が当てた項目）の書き込みの記録を writes.carry で写し、当たらない項目と conflict の項目の差分を keep に残し、単位の
  worktree を片付けて控えを <名>.done.json に移す。控えが無ければ {"ran": False}

当てるコマンドは役の sandbox の python3（3.9 でよい）で走る。頭の import は標準ライブラリと unittrees だけにする（writes は settle の
中で引く）。
"""
from __future__ import annotations

import json
import os
import pathlib
import sys
import tempfile

sys.dont_write_bytecode = True   # 下の import が pack の中に __pycache__ を作らないように（必ず import より前）

_CORE = pathlib.Path(__file__).resolve().parents[2] / ".shared" / "core"
if str(_CORE) not in sys.path:
    sys.path.insert(0, str(_CORE))

import unittrees  # noqa: E402

TREE = "item-{n}"
PATCH = "item-{n}.patch"
RECORD = "merged.json"
DONE = ".done.json"
APPLIED, CONFLICT, BROKEN, EMPTY = "applied", "conflict", "broken", "empty"
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
    """[(n, 範囲 | None)] のうち並べる項目の番号（並びのまま）。範囲が None の項目と、ほかのどれかと重なる項目は順"""
    known = [(n, list(p)) for n, p in items if p is not None]
    out = [n for n, p in known if not any(m != n and overlap(p, q) for m, q in known)]
    return out if len(out) >= 2 else []


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


def _read_json(path) -> dict:
    try:
        doc = json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return doc if isinstance(doc, dict) else {}


def plant(repo, items, place, manifest) -> dict:
    """前にこの作業ツリーから切った単位の worktree を片付け、今の姿を base にして項目ごとに place/item-<n> を切り、控えを書く"""
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
    _write_json(manifest, {"repo": str(repo), "base": base, "place": str(place), "record": str(place / RECORD), "items": rows})
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


def merge(manifest) -> dict:
    """当てるコマンドの中身（頭の注記）"""
    doc = _read_json(manifest)
    repo, place, base = pathlib.Path(doc["repo"]), pathlib.Path(doc["place"]), doc["base"]
    record = _read_json(doc["record"])
    done = record.setdefault("items", {})
    with tempfile.TemporaryDirectory(prefix="works-unitlanes-") as objects:
        for row in doc["items"]:
            n, key = row["item"], str(row["item"])
            if key in done:
                continue
            tree = pathlib.Path(row["tree"])
            if not row.get("git") or _git_line(tree) != row["git"]:
                done[key] = {"state": BROKEN, "why": "単位の worktree の .git の指しが切った時と違う（当てない）"}
                _write_json(pathlib.Path(doc["record"]), record)
                continue
            patch = unittrees.diff(tree, base, objects=objects)
            path = place / PATCH.format(n=n)
            path.write_text(patch, encoding="utf-8", errors="surrogateescape")
            if not patch.strip():
                done[key] = {"state": EMPTY}
            else:
                ok, why = unittrees.apply(repo, patch, objects=objects)
                done[key] = {"state": APPLIED, "patch": str(path)} if ok else {"state": CONFLICT, "why": why, "patch": str(path)}
            _write_json(pathlib.Path(doc["record"]), record)
    return _summary(doc, done)


def _summary(doc: dict, done: dict) -> dict:
    out = {APPLIED: [], CONFLICT: [], BROKEN: [], EMPTY: [], "differ": []}
    for row in doc["items"]:
        got = done.get(str(row["item"])) or {}
        state = got.get("state")
        if state == APPLIED:
            out[APPLIED].append(row["item"])
            patch = pathlib.Path(got["patch"]).read_text(encoding="utf-8", errors="surrogateescape")
            for name in _names(patch):
                if not _same(pathlib.Path(doc["repo"]) / name, pathlib.Path(row["tree"]) / name) and name not in out["differ"]:
                    out["differ"].append(name)
        elif state in (CONFLICT, BROKEN):
            out[state].append({"item": row["item"], "why": got.get("why", ""), "patch": got.get("patch", "")})
        elif state == EMPTY:
            out[EMPTY].append(row["item"])
    return out


def command(manifest) -> str:
    """修正役が Bash で走らせる当てるコマンドの 1 行（役の sandbox の python3）"""
    return f"python3 {pathlib.Path(__file__).resolve()} {manifest}"


def settle(manifest, repo, log, keep) -> dict:
    """修正役の後・受け付けの前の機械（頭の注記）"""
    import writes   # .shared/core（L3）。当てるコマンドの python3 では読まない

    manifest, repo, keep = pathlib.Path(manifest), pathlib.Path(repo), pathlib.Path(keep)
    doc = _read_json(manifest)
    if not doc.get("items"):
        return {"ran": False}
    done = _read_json(doc["record"]).get("items") or {}
    out = {"ran": True, "applied": [], "machine": [], "conflict": [], "unmerged": [], "carried": 0}
    pairs = []
    for row in doc["items"]:
        n, tree = row["item"], pathlib.Path(row["tree"])
        state = (done.get(str(n)) or {}).get("state")
        if state in (CONFLICT, BROKEN, EMPTY):
            if state == CONFLICT:
                out["conflict"].append(n)
                _keep(keep, n, doc, tree)
            continue
        if not row.get("git") or _git_line(tree) != row["git"]:
            out["unmerged"].append({"item": n, "why": "単位の worktree の .git の指しが切った時と違う"})
            continue
        patch = unittrees.diff(tree, doc["base"])
        if state != APPLIED and not unittrees.applied(repo, patch):
            ok, why = unittrees.apply(repo, patch)
            if not ok:
                out["unmerged"].append({"item": n, "why": why})
                _keep(keep, n, doc, tree, patch)
                continue
            out["machine"].append(n)
        out["applied"].append(n)
        pairs += [(tree / name, repo / name) for name in _names(patch)]
    out["carried"] = len(writes.carry(pathlib.Path(log), pairs)) if pairs else 0
    unittrees.sweep(repo)
    os.replace(manifest, manifest.with_name(manifest.stem + DONE))
    return out


def _keep(keep: pathlib.Path, n, doc: dict, tree: pathlib.Path, patch: str | None = None) -> None:
    """当たらなかった項目の差分を keep/item-<n>.patch に残す（直しを捨てない）"""
    if patch is None:
        try:
            patch = unittrees.diff(tree, doc["base"])
        except unittrees.UnitTreeError:
            patch = (pathlib.Path(doc["place"]) / PATCH.format(n=n)).read_text(encoding="utf-8", errors="surrogateescape")
    keep.mkdir(parents=True, exist_ok=True)
    (keep / PATCH.format(n=n)).write_text(patch, encoding="utf-8", errors="surrogateescape")


def main(argv) -> int:
    if len(argv) != 2:
        print("使い方: python3 unitlanes.py <控えの units.json>", file=sys.stderr)
        return 2
    try:
        out = merge(argv[1])
    except (OSError, KeyError, unittrees.UnitTreeError) as e:
        print(f"unitlanes: {' '.join(str(e).split())}", file=sys.stderr)
        return 1
    print(json.dumps(out, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
