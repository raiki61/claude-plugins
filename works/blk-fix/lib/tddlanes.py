"""TDD の輪の単位を、範囲の重ならない物だけ単位の worktree で並べる（blk-fix。依頼 243 の並べの 2 段目。設計
docs/plans/2026-10-06-tdd-parallel.md）。分け方・切る・段のコマンド・締めるを機械が持ち、AI（まとめ役）は単位の下請けを同時に
起こすだけ。赤・緑の確かめは tddloop.step をそのまま単位の worktree で回す（決まりを写さない）。

語:
- 並べる単位: 振り分けで tdd に振られた単位のうち、範囲（ranges）が引けて、ほかのどの tdd の単位とも重ならない物（unitlanes.lanes）
- 単位の控え: 単位ごとの tddloop の状態（単位 1 つだけ）。run ごとの置き場の <tdd-<k>>/lanes/lane-<n>/state.json（下請けの
  sandbox が書ける所）。隣に objects（段のコマンドが書く git の object）と reply.json（下請けが段の返答を書く）
- 目録（manifest）: 盤面の tdd-<k>/lanes.json {repo, base, place, rows: [{n, unit_key, tree, git, state, reply, file}]}。git は
  単位の worktree の `.git` の 1 行、file は下請けのファイル（盤面の tdd-<k>/lane-<n>.md）。役は書けない
- 戻す: 並べで済まなかった単位を順の単位として最初の段から回し直す（direct にしない）

口:
- ranges(board_dir, keys): 単位 → 範囲（単位を持つ修正案の項目の範囲 fixrules.item_ranges の和。項目が無い・範囲の無い項目が在る・
  空なら None）。盤面が開けなければ {}
- plan(st, repo): 振り分けの後（tddloop.step）。並べる単位が 2 つ以上なら単位の worktree と単位の控えと目録を置き、状態の段を
  lanes にして真。ほかは何もせず偽
- command_line(manifest, n, reply): 下請けが Bash で走らせる段のコマンドの 1 行（この節の python の絶対パス）
- run(manifest, n, reply): 段のコマンドの中身（下請けの sandbox の中）。単位の worktree の `.git` の 1 行を確かめ、git の新しい
  object を単位の置き場に書く env の下で tddloop.step を単位の控えに回す。食い違いの申し出は確かめずに控えに書く（盤面を読む
  確かめは settle）。{ok, done, phase, reason}
- settle(st, repo, try_query): lanes の段の tdd-step（sandbox の外）。まとめ役が run の作業ツリーに書いた物を戻し、目録の順に
  単位を締め（申し出の確かめ・direct・赤の確かめ直し（_red_again。控えの赤の記録は偽れるので、単位の頭の木と赤の時の
  テストのファイルで名指しを回し直す）・書き込みの記録の突き合わせ・3 方向で当てる・当てた中身と凍結の照らし・記録を写す）、
  当てた後の木で緑をもう 1 度確かめ、単位の worktree を片付けて順の段へ進める。盤面に積む申し出の一覧を返す
- unit_text(st, row): 下請けのファイルの「この単位の下請けの決まり」の節（支度 tddloop.prep が fixrules.tdd_lane_render に渡す）
"""
from __future__ import annotations

import contextlib
import json
import os
import pathlib
import shlex
import subprocess
import sys

sys.dont_write_bytecode = True   # 下の import が pack の中に __pycache__ を作らないように（必ず import より前）

_HERE = pathlib.Path(__file__).resolve().parent
for _p in (_HERE.parents[1] / ".shared" / "core", _HERE):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import adapter  # noqa: E402  （L2。run ごとの置き場 run_place_of）
import conflict  # noqa: E402
import entry  # noqa: E402
import fixrules  # noqa: E402  （項目の範囲 item_ranges）
import planbrief  # noqa: E402
import tddloop  # noqa: E402
import tree_run  # noqa: E402  （試験へ渡さない git の object の置き場の印 LANE_GIT_ENV）
import unitlanes  # noqa: E402  （分け方 lanes・切る plant・patch の行先 _names・中身の比べ _same。1 段目の物をそのまま）
import unittrees  # noqa: E402
import writes  # noqa: E402
from board import BoardGap  # noqa: E402

MANIFEST = "lanes.json"     # 目録（盤面の tdd-<k>/。共有の記録 tdd-*/**）
LANE_FILE = "lane-{n}.md"   # 下請けのファイル（盤面の tdd-<k>/）
KEPT = "lanes"              # 戻した単位の前の試みの差分の置き場（盤面の tdd-<k>/lanes/item-<n>.patch）
PLACE = "lanes"             # 単位の worktree と控えの置き場（run ごとの置き場の <tdd-<k>>/lanes）
LANE_DIR, REPLY, OBJECTS = "lane-{n}", "reply.json", "objects"
MERGED, DIRECT, PARKED, BACK = "merged", "direct", "parked", "serial"


class LaneBroken(Exception):
    """段のコマンドを回せない（目録・控えが読めない・単位の worktree の `.git` の指しが切った時と違う）。コマンドは 2 で落ちる"""


def ranges(board_dir, keys) -> dict:
    """単位 → 範囲の glob の並び（頭の注記）。盤面が開けない・項目が引けなければ {}"""
    try:
        b = entry.open_board(pathlib.Path(board_dir), allow_halted=True)
    except (BoardGap, OSError, ValueError):
        return {}
    items = fixrules.item_ranges(b)
    by = planbrief.by_unit_at(board_dir)
    out = {}
    for k in keys:
        rows = by.get(k) or []
        got = [items.get(r.get("item")) for r in rows]
        out[k] = sorted({g for r in got for g in r}) if rows and all(got) else None
    return out


def plan(st: dict, repo) -> bool:
    """振り分けの後に並べる単位を選び、切る（頭の注記）"""
    queue = list(st.get("queue") or [])
    if len(queue) < 2:
        return False
    work = pathlib.Path(st["work"])
    got = ranges(work.parent, queue)
    picked = unitlanes.lanes([(i, got.get(k) or None) for i, k in enumerate(queue, 1)])
    if not picked:
        return False
    keys = [queue[i - 1] for i in picked]
    place = pathlib.Path(adapter.run_place_of({"board": str(work.parent)})) / work.name / PLACE
    manifest = work / MANIFEST
    ns = list(range(1, len(keys) + 1))
    trees = unitlanes.plant(repo, ns, place, manifest)
    base = trees[ns[0]]["base"]
    rows = []
    for n, k in zip(ns, keys):
        tree = pathlib.Path(trees[n]["tree"])
        lane = place / LANE_DIR.format(n=n)
        (lane / OBJECTS).mkdir(parents=True, exist_ok=True)
        state = lane / tddloop.STATE
        tddloop._save(state, _lane_state(st, repo, k, tree, lane))
        rows.append({"n": n, "unit_key": k, "tree": str(tree), "git": unitlanes._git_line(tree), "state": str(state),
                     "reply": str(lane / REPLY), "file": str(work / LANE_FILE.format(n=n))})
    tddloop.save_json(manifest, {"repo": str(repo), "base": base, "place": str(place), "rows": rows})
    st["lanes"] = {"manifest": str(manifest), "place": str(place), "base": base, "rows": rows}
    st["phase"] = "lanes"
    return True


def _lane_state(st: dict, repo, k: str, tree: pathlib.Path, lane: pathlib.Path) -> dict:
    """単位 k の控え: 輪の状態と同じ形で、単位 1 つ・段 test から。実行器が run の作業ツリーの中なら単位の worktree の同じ物"""
    exe = pathlib.Path(st["exe"])
    try:
        exe = tree / exe.absolute().relative_to(pathlib.Path(repo).absolute())
    except ValueError:
        pass
    head = tddloop.snapshot(tree)
    contract = tddloop._contract(st, k)
    return {"suite": st["suite"], "exe": str(exe), "work": str(lane), "open_units": [k], "excused": {},
            "baseline": st["baseline"], "baseline_exit": st["baseline_exit"], "handoff": head,
            "suite_made": list(st.get("suite_made") or []), "phase": "test", "tries": 0, "reason": "", "iterations": 0,
            "runs": 1, "order": [k], "units": {k: tddloop._unit(k, "tdd")}, "queue": [k], "cur": 0, "unit_head": head,
            "green_tree": "", "done": False, "note": "", "frozen": {}, "parked": [], "parked_why": {},
            "contract": {k: contract} if contract else {}, "plain": bool(st.get("plain")), "test_cmd": st.get("test_cmd", ""),
            "test_cmd_gate": st.get("test_cmd_gate", tddloop.GATE_OFF), "test_cmd_note": st.get("test_cmd_note", ""),
            "light": [k] if k in (st.get("light") or []) else [], "calls": [], "head_run": tddloop._head_run(st),
            "declared": [], "conflict": None, "lanes_on": False}


def command_line(manifest, n, reply) -> str:
    """下請けが Bash で走らせる 1 行。python は支度の節の物（役の sandbox の python3 は 3.9 のことがある）"""
    return " ".join(shlex.quote(str(x)) for x in (sys.executable, pathlib.Path(__file__).resolve(), manifest, n, reply))


def _row(manifest, n) -> dict:
    try:
        doc = json.loads(pathlib.Path(manifest).read_text(encoding="utf-8"))
        return next(r for r in doc["rows"] if str(r["n"]) == str(n))
    except (OSError, ValueError, KeyError, TypeError, StopIteration) as e:
        raise LaneBroken(f"目録 {manifest} に単位 {n} が読めない（{type(e).__name__}: {e}）") from None


@contextlib.contextmanager
def _lane_git(tree: pathlib.Path, objects: pathlib.Path):
    """この中の git は新しい object を objects に書き、共通の objects を代わりの置き場として読む（共通の .git を書かない）。
    試験には渡さない（印 tree_run.LANE_GIT_ENV）。盤面の待ちの印は書かない（ARTIFACTS_DIR を落とす）。出る時に env を戻す"""
    common = subprocess.run(["git", "-C", str(tree), "rev-parse", "--path-format=absolute", "--git-path", "objects"],
                            capture_output=True, text=True, encoding="utf-8", check=True).stdout.strip()
    want = {"GIT_OBJECT_DIRECTORY": str(objects), "GIT_ALTERNATE_OBJECT_DIRECTORIES": common, tree_run.LANE_GIT_ENV: "1"}
    keep = {k: os.environ.get(k) for k in (*want, "ARTIFACTS_DIR")}
    os.environ.update(want)
    os.environ.pop("ARTIFACTS_DIR", None)
    try:
        yield
    finally:
        for k, v in keep.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def run(manifest, n, reply_file) -> dict:
    """段のコマンドの中身（頭の注記）"""
    row = _row(manifest, n)
    tree = pathlib.Path(row["tree"])
    if not row.get("git") or unitlanes._git_line(tree) != row["git"]:
        raise LaneBroken(f"単位の worktree {tree} の .git の指しが切った時と違う（段を回さない）")
    try:
        reply = json.loads(pathlib.Path(reply_file).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        reply = None   # 読めない返答は step が拒む（出し直しの回数に数える）
    state = pathlib.Path(row["state"])
    with _lane_git(tree, state.parent / OBJECTS):
        lst = tddloop._load(state)
        if lst["done"]:
            return {"ok": False, "done": True, "phase": "done", "reason": "この単位の段はもう済んでいる（もう走らせるな）"}
        if isinstance(reply, dict) and reply.get("phase") == "conflict":
            return _park(state, lst, reply, tree)
        items = reply.get(writes.FIELD) if isinstance(reply, dict) else None
        out = tddloop.step(state, reply, tree)
        if out["ok"] and items and not writes.shape_problems(items):
            lst = tddloop._load(state)
            lst["declared"] = [*lst.get("declared", []), *items]
            tddloop._save(state, lst)
    return {"ok": out["ok"], "done": out["done"], "phase": out["phase"], "reason": out["reason"]}


def _park(state: pathlib.Path, lst: dict, reply: dict, tree: pathlib.Path) -> dict:
    """食い違いの申し出: 欄と単位だけ見て控えに書き、木を単位の頭に戻して済みにする（盤面を読む確かめは settle）"""
    k = lst["queue"][0]
    extra = sorted(set(reply) - {"phase", *conflict.FIELDS, conflict.CORRECT})
    if extra or reply.get("unit_key") != k:
        why = (f"食い違いの申し出の欄は phase と {list(conflict.FIELDS)}（query なら {conflict.CORRECT} も）だけ（{extra}）" if extra
               else f"この下請けの単位は '{k}'（申し出の unit_key は {reply.get('unit_key')!r}）")
        return {"ok": False, "done": False, "phase": lst["phase"], "reason": why}
    item = {f: reply.get(f) for f in conflict.FIELDS}
    if conflict.CORRECT in reply:
        item[conflict.CORRECT] = reply[conflict.CORRECT]
    tddloop.restore(tree, lst["unit_head"])
    lst.update(conflict=item, done=True)
    lst["calls"].append({"n": lst["iterations"] + 1, "phase": "conflict", "unit_key": k, "ok": True, "runs": 0, "secs": 0.0})
    tddloop._save(state, lst)
    return {"ok": True, "done": True, "phase": "done", "reason": ""}


# ---------------------------------------------------------------- 締める（lanes の段の tdd-step）
def settle(st: dict, repo, try_query=None) -> list:
    """頭の注記。st を書き換え、盤面に積む申し出の一覧を返す"""
    repo = pathlib.Path(repo)
    lanes = st["lanes"]
    work = pathlib.Path(st["work"])
    board_dir = work.parent
    log = writes.sink(repo)
    stray = sorted(set(tddloop.touched(repo, st["handoff"], tddloop.snapshot(repo))) - set(st["suite_made"]))
    if stray:   # 並べの周のまとめ役は run の作業ツリーを書かない約束。機械が戻す（拒んで出し直させない）
        tddloop.restore_paths(repo, st["handoff"], stray)
    lanes["reverted"] = stray
    pre = st["handoff"]
    out, back, merged, items, calls = {}, {}, [], [], []
    for row in lanes["rows"]:
        k, tree = row["unit_key"], pathlib.Path(row["tree"])
        try:
            if not row.get("git") or unitlanes._git_line(tree) != row["git"]:
                raise tddloop.Broken("単位の worktree の .git の指しが切った時と違う")
            lst = tddloop._load(row["state"])
        except tddloop.Broken as e:
            back[k] = {"why": f"単位の控えが読めない（{e}）"}
            continue
        calls += [{**c, "unit_key": k} for c in lst.get("calls") or []]
        u = lst["units"][k]
        if lst.get("conflict"):
            item = lst["conflict"]
            probs = conflict.problems([item], repo=tree, board_dir=board_dir, owed={k}, try_query=try_query,
                                      briefs=planbrief.by_unit_at(board_dir))
            if probs:
                back[k] = {"why": "並べの食い違いの申し出が確かめを通らない: " + probs[0][:300]}
                continue
            st.setdefault("parked", []).append(k)
            st.setdefault("parked_why", {})[k] = item["why_both_cannot_hold"]
            st["units"][k].update(route="parked", why=item["why_both_cannot_hold"])
            items.append(item)
            out[k] = (PARKED, "")
        elif not lst.get("done"):
            back[k] = {"why": "並べの段が済まなかった（下請けが段のコマンドを最後まで走らせなかった）"}
        elif u.get("route") == "direct":
            if u.get("gave_up") == "writer":
                st["units"][k] = _record(u)
                out[k] = (DIRECT, u.get("why", ""))
            else:
                back[k] = {"why": f"並べで段の確かめを諦めた（{u.get('gave_up')}）: {(u.get('why') or '')[:300]}"}
        elif u.get("green") == "ok":
            why = _red_again(st, row, lst, u, work)
            why, patch = (why, "") if why else _merge(st, repo, row, lst, u, log, work)
            if why:
                back[k] = {"why": why, **({"patch": patch} if patch else {})}
            else:
                merged.append((k, u, patch))
        else:
            back[k] = {"why": "並べで緑に届かなかった"}
    if merged:
        probs = _green_after(st, repo, pre, [u for _, u, _ in merged])
        if probs:
            tddloop.restore(repo, pre)
            for k, _, patch in merged:
                back[k] = {"why": "当てた後の木の緑の確かめが赤: " + probs[0][:300], "patch": patch}
            merged = []
    for k, u, _ in merged:
        st["units"][k] = _record(u)
        out[k] = (MERGED, "")
    for k in back:
        st["units"][k] = tddloop._unit(k, "tdd")
        out[k] = (BACK, back[k]["why"])
    for row in lanes["rows"]:
        unittrees.remove(repo, row["tree"])
    lanes.update(back=back, calls=calls, done_keys=[r["unit_key"] for r in lanes["rows"] if out[r["unit_key"]][0] != BACK],
                 out=[{"unit_key": r["unit_key"], "outcome": out[r["unit_key"]][0], "why": out[r["unit_key"]][1]}
                      for r in lanes["rows"]])
    done = set(lanes["done_keys"])
    st["queue"] = [k for k in st["order"] if st["units"][k]["route"] == "tdd" and k not in done]
    st["cur"] = 0
    st["handoff"] = tddloop.snapshot(repo)
    tddloop._next_unit(st, repo)
    return items


def _record(u: dict) -> dict:
    """単位の控えの行を輪の状態の行に（赤の回の結末は持ち込まない）"""
    return {f: v for f, v in u.items() if f != "red_run"}


def _red_again(st, row, lst, u, work) -> str:
    """赤を sandbox の外で確かめ直す（控えの赤の記録は下請けが書ける所に在る）。単位の worktree を、単位の頭の木に赤の時の
    テストのファイル（凍結で今の中身と同じ）だけを置いた姿にして名指しだけを回し、写しの red_problems と記録の赤の種類で照らす。
    回した後は worktree を元の姿に戻す。通れば空、記録どおりに落ちなければ戻す理由"""
    tree = pathlib.Path(row["tree"])
    tests, files = list(u.get("tests") or []), list(u.get("test_files") or [])
    if not tests:
        return "赤の記録に名指しのテストが無い（赤を確かめ直せない）"
    now = tddloop.hashes(tree, files)
    if any(now[f] != (u.get("test_hashes") or {}).get(f) for f in files):
        return "テストのファイルの中身が赤の記録と違う（赤を確かめ直せない）"
    final = tddloop.snapshot(tree)
    try:
        tddloop.restore_paths(tree, lst["unit_head"], set(tddloop.touched(tree, lst["unit_head"], final)) - set(files))
        cases, code, why = tddloop.run_suite(lst["exe"], tree, work, f"lane-{row['n']}-red", tddloop.abs_ids(tree, tests),
                                             only=True)
    finally:
        tddloop.restore(tree, final)
    if cases is None:
        return "赤を確かめ直す実行器が走らない（" + "; ".join(why)[:300] + "）"
    probs = tddloop.rules().red_problems(tests, cases, code, st["baseline"])
    if not probs:
        kinds = {t: tddloop.red_kind(tddloop.rules().match_case(t, cases) or {}) for t in tests}
        probs = [f"{t}: 赤の種類 {kinds[t]}（記録は {k}）" for t, k in (u.get("red_kinds") or {}).items() if kinds.get(t) != k]
    return ("赤の記録を機械が確かめ直すと再現しない（単位の頭の木に赤の時のテストだけを置いて名指しを回した）: "
            + probs[0][:300]) if probs else ""


def _merge(st, repo, row, lst, u, log, work) -> tuple[str, str]:
    """緑まで済んだ単位の差分を当てる。(戻す理由（当てたら空）, 前の試みの差分のファイル)"""
    tree = pathlib.Path(row["tree"])
    moved = sorted(set(tddloop.touched(tree, lst["unit_head"], tddloop.snapshot(tree))) - set(lst.get("suite_made") or []))
    declared = lst.get("declared") or []
    if log.is_file():
        left = writes.unrecorded(tree, moved, log, declared)
        if left:
            return writes.REJECT + ", ".join(left[:10]), ""
        writes.keep_declared(log, tree, declared)
    patch = unittrees.diff(tree, st["lanes"]["base"])
    kept = work / KEPT / f"item-{row['n']}.patch"
    kept.parent.mkdir(parents=True, exist_ok=True)
    kept.write_text(patch, encoding="utf-8", errors="surrogateescape")
    before = tddloop.snapshot(repo)
    ok, why = unittrees.apply(repo, patch)
    if not ok:
        return f"差分が run の作業ツリーに当たらない（{' '.join(why.split())[:300]}）", str(kept)
    names = unitlanes._names(patch)
    differ = [n for n in names if not unitlanes._same(pathlib.Path(repo) / n, tree / n)]
    now = tddloop.hashes(repo, u["test_files"])
    moved_tests = [f for f in u["test_files"] if now[f] != u["test_hashes"][f]]
    if differ or moved_tests:
        tddloop.restore_paths(repo, before, names)
        return (f"当てた中身が単位の worktree と違う（{differ[:5]}）" if differ
                else f"当てた後の凍ったテストの中身が赤の時と違う（{moved_tests[:5]}）"), str(kept)
    if log.is_file():
        writes.carry(log, [(tree / n, pathlib.Path(repo) / n) for n in names])
    return "", str(kept)


def _green_after(st, repo, pre: str, units: list) -> list:
    """当てた後の木で、当てた単位の名指し全部と変更に直に関わる試験を 1 回走らせた緑の確かめ（test_cmd の関門が on で軽量で
    ない単位が在れば test_cmd も 1 回）。赤・走らなければ文の一覧。緑なら次の単位の頭の回を進める"""
    tests = [t for u in units for t in u["tests"]]
    st["unit_head"] = pre
    files, full = tddloop._reached(st, repo)
    try:
        cases, code = tddloop._run(st, repo, tests, files, full)
    except tddloop._RunnerDown as e:
        return [f"{e.head}: {e}"]
    probs = tddloop.rules().green_problems(tests, cases, code, st["baseline"], st["baseline_exit"])
    light = set(st.get("light") or [])
    if not probs and st.get("test_cmd_gate") == tddloop.GATE_ON and any(u["unit_key"] not in light for u in units):
        log = pathlib.Path(st["work"]) / f"test-cmd-{st['runs']}.log"
        mat, made = tddloop._cmd_run(repo, st["test_cmd"], log)
        st["runs"] += 1
        st["suite_made"] = sorted(set(st["suite_made"]) | set(made))
        if mat["status"] != "clean":
            probs = [f"run の test_cmd（{st['test_cmd']}）が当てた後の木で緑でない（ログ {log}）"]
    if not probs:
        st["head_run"] = tddloop._next_head(tddloop._head_run(st), st["last_run"])
    return probs


# ---------------------------------------------------------------- 下請けのファイル（支度 tddloop.prep）
def unit_text(st: dict, row: dict) -> str:
    """下請けのファイルの「この単位の下請けの決まり」の節（機械が書く。fixrules.tdd_lane_render の lane_text）"""
    lst = tddloop._load(row["state"])
    cmd = command_line(st["lanes"]["manifest"], row["n"], row["reply"])
    lines = ["## この単位の下請けの決まり（機械が書いた）", "",
             f"- 単位: {row['unit_key']}",
             f"- 単位の worktree: {row['tree']}（読む・書く・試験を回すのは全部この中。Bash は最初に cd し、Edit・Write のパスも"
             "この下。名指しのパスはこの根からの相対。修正役の作業ツリー（cwd）は書かない）",
             f"- 段の返答の置き場: {row['reply']}（作業ツリーの外。Write で段の返答の JSON を丸ごと書く）",
             f"- 段のコマンド: `{cmd}`（Bash で走らせる。出力の 1 行の JSON {{ok, done, phase, reason}} に従え）", "",
             "## 段の進め方", "",
             "1. 段 test から始める。段の仕事をしたら、その段の返す JSON を返答の置き場に書き、段のコマンドを走らせる。",
             "2. ok が false なら reason を直して、同じ段の返答を丸ごと書き直して走らせ直す（同じ段の 3 回目の拒否で機械が諦める）。",
             "3. ok が true なら phase が次の段を言う（fix・refactor）。その段の仕事をして 1 に戻る。",
             "4. done が true になったら終わり。最後のメッセージに、何をしたかを 3 行以内で書く（報告はファイルに書かない）。", "",
             "## 段ごとの仕事と返す JSON", ""]
    for p in ("test", "fix", "refactor"):
        lines += [f"### 段 {p}", "", tddloop.DO[p], "", tddloop.RETURN[p], ""]
    lines += ["### 食い違いの申し出（どの段でも）", "", tddloop.RETURN_CONFLICT.replace("（振り分けの段なら義務の単位のどれか、ほかの段なら今の単位）", ""), "",
              "## テストの回し方", "",
              f"単位の worktree の根で `{lst['exe']} <JUnit XML の書き先>`（書き先は worktree の外に）。"
              "機械は名指しを実行器の後ろに絶対パスの node id で足して回す。", ""]
    return "\n".join(lines)


def main(argv) -> int:
    if len(argv) != 4:
        print("使い方: python3 tddlanes.py <目録 lanes.json> <単位の番号> <段の返答の JSON のファイル>", file=sys.stderr)
        return 2
    try:
        out = run(argv[1], argv[2], argv[3])
    except (LaneBroken, tddloop.Broken, OSError, subprocess.CalledProcessError) as e:
        print(f"tddlanes: {' '.join(str(e).split())}", file=sys.stderr)
        return 2
    sys.stdout.reconfigure(encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
