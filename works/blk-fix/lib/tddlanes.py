"""TDD の輪の単位を、枝ごとの単位の worktree で並べる（blk-fix。依頼 243 の並べの 2 段目と 3 段目。設計
docs/plans/2026-10-06-tdd-parallel.md・docs/plans/2026-10-07-overlap-lanes.md）。分け方・切る・段のコマンド・締めるを機械が持ち、
AI（まとめ役）は単位の下請けを起こすだけ。赤・緑の確かめは tddloop.step をそのまま単位の worktree で回す（決まりを写さない）。

語:
- 枝: 並べの 1 本。修正案の項目を共にする tdd の単位の組（groups。単位が項目に無ければ 1 単位 1 枝）。枝ごとに単位の worktree を
  1 本切り、枝の中の単位は振り分けの順に 1 つずつ、単位ごとに新しい下請けで直す（新しい会話の決まり。前の単位の物は機械が書く
  引き継ぎのファイルで渡る）。範囲（ranges）の引けない単位を含む枝は順。範囲が重なる枝も並べ、当てる所で食い違った枝だけ順に戻す
- 単位の控え: 枝ごとの tddloop の状態（枝の単位だけ）。run ごとの置き場の <tdd-<k>>/lanes/lane-<n>/state.json（下請けの
  sandbox が書ける所）。隣に objects（段のコマンドが書く git の object）・reply.json（下請けが段の返答を書く）・handoff-<j>.md
  （枝の j 番目の単位への引き継ぎ。段のコマンドが前の単位の済んだ時に書く）。単位ごとの頭の木を unit_heads に、枝の頭を lane_base に持つ
- 目録（manifest）: 盤面の tdd-<k>/lanes.json {repo, base, place, rows: [{n, unit_keys, tree, git, state, reply, files}]}。git は
  単位の worktree の `.git` の 1 行、files は枝の単位ごとの下請けのファイル（盤面の tdd-<k>/lane-<n>-<j>.md）。役は書けない
- 重なりのファイル（shared）: 当てた枝のうち 2 本以上の差分に出たファイル。合わせの結末（merge）は枝ごとに clean・union（試験の
  ファイルの挿しだけの食い違いを合わせた）・conflict（字の食い違い）・semantic（合わせた木で赤くなり後の枝を落とした）
- 戻す: 並べで済まなかった単位を順の単位として最初の段から回し直す（direct にしない）

口:
- ranges(board_dir, keys): 単位 → 範囲（単位を持つ修正案の項目の範囲 fixrules.item_ranges の和。項目が無い・範囲の無い項目が在る・
  空なら None）。盤面が開けなければ {}
- items_of(board_dir, keys): 単位 → 単位を持つ修正案の項目の番号の並び（planbrief.by_unit_at）。盤面が開けなければ {}
- groups(queue, items): 単位を項目を共にする物どうしの組に（純粋。振り分けの順）
- plan(st, repo): 振り分けの後（tddloop.step）。並べる枝が 2 本以上なら単位の worktree と単位の控えと目録を置き、状態の段を
  lanes にして真。ほかは何もせず偽
- command_line(manifest, n, reply, j): 下請けが Bash で走らせる段のコマンドの 1 行（この節の python の絶対パス。j は枝の中の単位の番）
- run(manifest, n, reply, j=None): 段のコマンドの中身（下請けの sandbox の中）。単位の worktree の `.git` の 1 行を確かめ、git の新しい
  object を単位の置き場に書く env の下で tddloop.step を単位の控えに回す。j の単位が枝の今の単位でなければ回さない。単位が済んで
  枝の次の単位へ移ったら、次の単位の頭を控えに残し、引き継ぎのファイルを書く。食い違いの申し出は確かめずに控えに書く（盤面を読む
  確かめは settle）。{ok, done（この下請けの単位が済んだ）, phase, reason}
- settle(st, repo, try_query): lanes の段の tdd-step（sandbox の外）。まとめ役が run の作業ツリーに書いた物を戻し、目録の順に
  枝を締める（単位ごとの申し出の確かめ・direct・赤の確かめ直し（_red_again。控えの赤の記録は偽れるので、単位の頭の木と赤の時の
  テストのファイルで名指しを回し直す）・書き込みの記録の突き合わせ・3 方向で当てる（試験のファイルの挿しだけの食い違いは合わせる）・
  当てた中身と名指しのテストの照らし）、当てた後の木で緑をもう 1 度確かめ（重なりのファイルを起点に広げる。赤なら後の枝を落として
  1 回だけ確かめ直す）、記録を写し、単位の worktree を片付けて順の段へ進める。盤面に積む申し出の一覧を返す
- unit_text(st, row, j): 下請けのファイルの「この単位の下請けの決まり」の節（支度 tddloop.prep が fixrules.tdd_lane_render に渡す）
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
LANE_FILE = "lane-{n}-{j}.md"   # 下請けのファイル（盤面の tdd-<k>/。枝 n の j 番目の単位）
HANDOFF = "handoff-{j}.md"  # 枝の j 番目の単位への引き継ぎ（単位の控えの隣。段のコマンドが書く）
KEPT = "lanes"              # 戻した枝の前の試みの差分の置き場（盤面の tdd-<k>/lanes/item-<n>.patch）
PLACE = "lanes"             # 単位の worktree と控えの置き場（run ごとの置き場の <tdd-<k>>/lanes）
LANE_DIR, REPLY, OBJECTS = "lane-{n}", "reply.json", "objects"
MERGED, DIRECT, PARKED, BACK = "merged", "direct", "parked", "serial"
CLEAN, UNION, CLASH, SEMANTIC = "clean", "union", "conflict", "semantic"   # 枝ごとの合わせの結末（頭の語）
NOT_YET = "この枝の前の単位がまだ済んでいない（段を回さない。この単位は機械が順に戻す）"
PASSED = "この単位の段はもう済んでいる（もう走らせるな）"


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


def items_of(board_dir, keys) -> dict:
    """単位 → 単位を持つ修正案の項目の番号の並び（頭の注記）"""
    by = planbrief.by_unit_at(board_dir)
    return {k: [r.get("item") for r in by.get(k) or [] if r.get("item") is not None] for k in keys}


def groups(queue, items) -> list:
    """queue の単位を、修正案の項目を共にする物どうしの組に（項目でつながる単位は全部 1 組。組の中と組の並びは queue の順）"""
    parent = {k: k for k in queue}

    def find(k):
        while parent[k] != k:
            parent[k] = parent[parent[k]]
            k = parent[k]
        return k
    first = {}
    for k in queue:
        for it in items.get(k) or []:
            if it in first:
                parent[find(k)] = find(first[it])
            else:
                first[it] = k
    out = {}
    for k in queue:
        out.setdefault(find(k), []).append(k)
    return list(out.values())


def _span(got: dict, keys) -> list | None:
    """枝の範囲（単位の範囲の和）。範囲の引けない単位が在れば None"""
    spans = [got.get(k) for k in keys]
    return None if any(x is None for x in spans) else sorted({g for x in spans for g in x})


def plan(st: dict, repo) -> bool:
    """振り分けの後に並べる枝を選び、切る（頭の注記）"""
    queue = list(st.get("queue") or [])
    if len(queue) < 2:
        return False
    work = pathlib.Path(st["work"])
    got = ranges(work.parent, queue)
    grps = groups(queue, items_of(work.parent, queue))
    spans = [(i, _span(got, g)) for i, g in enumerate(grps, 1)]
    picked = unitlanes.lanes(spans)
    if not picked:
        return False
    chosen = [grps[i - 1] for i in picked]
    place = pathlib.Path(adapter.run_place_of({"board": str(work.parent)})) / work.name / PLACE
    manifest = work / MANIFEST
    ns = list(range(1, len(chosen) + 1))
    trees = unitlanes.plant(repo, ns, place, manifest)
    base = trees[ns[0]]["base"]
    rows = []
    for n, keys in zip(ns, chosen):
        tree = pathlib.Path(trees[n]["tree"])
        lane = place / LANE_DIR.format(n=n)
        (lane / OBJECTS).mkdir(parents=True, exist_ok=True)
        state = lane / tddloop.STATE
        tddloop._save(state, _lane_state(st, repo, keys, tree, lane))
        rows.append({"n": n, "unit_keys": list(keys), "tree": str(tree), "git": unitlanes._git_line(tree), "state": str(state),
                     "reply": str(lane / REPLY),
                     "files": [str(work / LANE_FILE.format(n=n, j=j)) for j in range(1, len(keys) + 1)]})
    tddloop.save_json(manifest, {"repo": str(repo), "base": base, "place": str(place), "rows": rows})
    expect = unitlanes.expect([(n, spans[i - 1][1]) for n, i in zip(ns, picked)])
    st["lanes"] = {"manifest": str(manifest), "place": str(place), "base": base, "rows": rows, "expect": expect}
    st["phase"] = "lanes"
    return True


def _lane_state(st: dict, repo, keys, tree: pathlib.Path, lane: pathlib.Path) -> dict:
    """枝の控え: 輪の状態と同じ形で、枝の単位だけ・段 test から。実行器が run の作業ツリーの中なら単位の worktree の同じ物"""
    exe = pathlib.Path(st["exe"])
    try:
        exe = tree / exe.absolute().relative_to(pathlib.Path(repo).absolute())
    except ValueError:
        pass
    keys = list(keys)
    head = tddloop.snapshot(tree)
    contract = {}
    for k in keys:
        c = tddloop._contract(st, k)
        if c:
            contract[k] = c
    light = set(st.get("light") or [])
    return {"suite": st["suite"], "exe": str(exe), "work": str(lane), "open_units": keys, "excused": {},
            "baseline": st["baseline"], "baseline_exit": st["baseline_exit"], "handoff": head,
            "suite_made": list(st.get("suite_made") or []), "phase": "test", "tries": 0, "reason": "", "iterations": 0,
            "runs": 1, "order": keys, "units": {k: tddloop._unit(k, "tdd") for k in keys}, "queue": list(keys), "cur": 0,
            "unit_head": head, "green_tree": "", "done": False, "note": "", "frozen": {}, "parked": [], "parked_why": {},
            "contract": contract, "plain": bool(st.get("plain")), "test_cmd": st.get("test_cmd", ""),
            "test_cmd_gate": st.get("test_cmd_gate", tddloop.GATE_OFF), "test_cmd_note": st.get("test_cmd_note", ""),
            "light": [k for k in keys if k in light], "calls": [], "head_run": tddloop._head_run(st),
            "declared": [], "conflict": None, "lanes_on": False, "lane_base": head, "unit_heads": {keys[0]: head}}


def command_line(manifest, n, reply, j=1) -> str:
    """下請けが Bash で走らせる 1 行。python は支度の節の物（役の sandbox の python3 は 3.9 のことがある）"""
    return " ".join(shlex.quote(str(x)) for x in (sys.executable, pathlib.Path(__file__).resolve(), manifest, n, reply, j))


def _row(manifest, n) -> dict:
    try:
        doc = json.loads(pathlib.Path(manifest).read_text(encoding="utf-8"))
        return next(r for r in doc["rows"] if str(r["n"]) == str(n))
    except (OSError, ValueError, KeyError, TypeError, StopIteration) as e:
        raise LaneBroken(f"目録 {manifest} に枝 {n} が読めない（{type(e).__name__}: {e}）") from None


@contextlib.contextmanager
def _env(want: dict):
    """want の env の下で回し（ARTIFACTS_DIR は落とす。盤面の待ちの印を書かない）、出る時に元に戻す"""
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


def _lane_git(tree: pathlib.Path, objects: pathlib.Path):
    """この中の git は新しい object を objects に書き、共通の objects を代わりの置き場として読む（共通の .git を書かない）。
    試験には渡さない（印 tree_run.LANE_GIT_ENV）"""
    common = subprocess.run(["git", "-C", str(tree), "rev-parse", "--path-format=absolute", "--git-path", "objects"],
                            capture_output=True, text=True, encoding="utf-8", check=True).stdout.strip()
    return _env({"GIT_OBJECT_DIRECTORY": str(objects), "GIT_ALTERNATE_OBJECT_DIRECTORIES": common, tree_run.LANE_GIT_ENV: "1"})


def _lane_read(row: dict):
    """締め（sandbox の外）の中の git が、段のコマンドが単位の置き場に書いた object（枝の 2 つ目からの単位の頭の木など）も
    読めるようにする。新しい object は共通の objects に書く。試験には渡さない（印 tree_run.LANE_GIT_ENV）"""
    objects = pathlib.Path(row["state"]).parent / OBJECTS
    return _env({"GIT_ALTERNATE_OBJECT_DIRECTORIES": str(objects), tree_run.LANE_GIT_ENV: "1"})


def run(manifest, n, reply_file, j=None) -> dict:
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
        if j is not None:
            j = int(j)
            if not 1 <= j <= len(lst["queue"]):
                raise LaneBroken(f"枝 {n} に {j} 番目の単位は無い（単位は {len(lst['queue'])} つ）")
            if lst["done"] or lst["cur"] > j - 1:
                return {"ok": False, "done": True, "phase": "done", "reason": PASSED}
            if lst["cur"] < j - 1:
                return {"ok": False, "done": True, "phase": "done", "reason": NOT_YET}
        elif lst["done"]:
            return {"ok": False, "done": True, "phase": "done", "reason": PASSED}
        if isinstance(reply, dict) and reply.get("phase") == "conflict":
            return _park(state, lst, reply, tree)
        items = reply.get(writes.FIELD) if isinstance(reply, dict) else None
        cur = lst["cur"]
        out = tddloop.step(state, reply, tree)
        lst = tddloop._load(state)
        if out["ok"] and items and not writes.shape_problems(items):
            lst["declared"] = [*lst.get("declared", []), *items]
        moved = lst["cur"] != cur
        if moved and not lst["done"]:   # 枝の次の単位へ: 頭の木を残し、次の下請けへの引き継ぎを書く
            lst.setdefault("unit_heads", {})[lst["queue"][lst["cur"]]] = lst["unit_head"]
            _write_handoff(state.parent, lst["cur"] + 1, lst)
        tddloop._save(state, lst)
    finished = moved or lst["done"]
    return {"ok": out["ok"], "done": finished, "phase": "done" if finished else out["phase"], "reason": out["reason"]}


def _write_handoff(lane: pathlib.Path, j: int, lst: dict) -> None:
    """枝の j 番目の単位の下請けへの引き継ぎ（前の単位の key・直したファイル・緑にしたテスト。tddloop.handoff_lines）"""
    lines = tddloop.handoff_lines(lst) or [tddloop.HANDOFF_HEAD, "", "（前の単位の記録は無い）", ""]
    (lane / HANDOFF.format(j=j)).write_text("\n".join(lines) + "\n", encoding="utf-8")


def _park(state: pathlib.Path, lst: dict, reply: dict, tree: pathlib.Path) -> dict:
    """食い違いの申し出: 欄と単位だけ見て控えに書き、木を今の単位の頭に戻して枝を済みにする（枝の後の単位は締めが順に戻す。
    盤面を読む確かめは settle）"""
    k = lst["queue"][lst["cur"]]
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
    log = writes.sink(repo)
    stray = sorted(set(tddloop.touched(repo, st["handoff"], tddloop.snapshot(repo))) - set(st["suite_made"]))
    if stray:   # 並べの周のまとめ役は run の作業ツリーを書かない約束。機械が戻す（拒んで出し直させない）
        tddloop.restore_paths(repo, st["handoff"], stray)
    lanes["reverted"] = stray
    pre = st["handoff"]
    out, back, items, calls, ready, how = {}, {}, [], [], [], {}
    for row in lanes["rows"]:
        keys, tree = row["unit_keys"], pathlib.Path(row["tree"])
        try:
            if not row.get("git") or unitlanes._git_line(tree) != row["git"]:
                raise tddloop.Broken("単位の worktree の .git の指しが切った時と違う")
            lst = tddloop._load(row["state"])
        except tddloop.Broken as e:
            for k in keys:
                back[k] = {"why": f"単位の控えが読めない（{e}）"}
            continue
        calls += [{**c, "lane": row["n"]} for c in lst.get("calls") or []]
        with _lane_read(row):
            green = _close_units(st, row, lst, keys, back, out, items, try_query, work)
            if green:
                why = next((w for w in (_red_again(st, row, lst, k, work) for k in green) if w), "")
                if why:
                    for k in green:
                        back[k] = {"why": why}
                else:
                    ready.append((row, lst, green))
    applied = _apply_lanes(st, repo, ready, log, work, back, how)
    shared = _shared(applied)
    if applied:
        probs = _green_after(st, repo, pre, [lst["units"][k] for _, lst, g, _ in applied for k in g], shared)
        if probs and shared:   # 意味の食い違いかもしれない: 重なりの組の後の枝を落として 1 回だけ確かめ直す
            applied, probs = _retry_without_later(st, repo, pre, applied, back, how, probs)
            shared = _shared(applied)
        if probs:
            tddloop.restore(repo, pre)
            for row, _, green, patch in applied:
                for k in green:
                    back[k] = {"why": "当てた後の木の緑の確かめが赤: " + probs[0][:300], "patch": patch}
                how[row["n"]] = SEMANTIC if shared else how.get(row["n"], CLEAN)
            applied = []
    _carry(log, repo, applied, shared)
    for _, lst, green, _ in applied:
        for k in green:
            st["units"][k] = _record(lst["units"][k])
            out[k] = (MERGED, "")
    for k in back:
        st["units"][k] = tddloop._unit(k, "tdd")
        out[k] = (BACK, back[k]["why"])
    for row in lanes["rows"]:
        unittrees.remove(repo, row["tree"])
    lanes.update(back=back, calls=calls, shared=shared,
                 done_keys=[k for r in lanes["rows"] for k in r["unit_keys"] if out[k][0] != BACK],
                 out=[{"unit_key": k, "outcome": out[k][0], "why": out[k][1], "lane": r["n"], "merge": how.get(r["n"], "")}
                      for r in lanes["rows"] for k in r["unit_keys"]])
    done = set(lanes["done_keys"])
    st["queue"] = [k for k in st["order"] if st["units"][k]["route"] == "tdd" and k not in done]
    st["cur"] = 0
    st["handoff"] = tddloop.snapshot(repo)
    tddloop._next_unit(st, repo)
    return items


def _close_units(st, row, lst, keys, back, out, items, try_query, work) -> list:
    """枝の単位を 1 つずつ締める（申し出・direct・済まなかった）。緑まで済んだ単位の並びを返す。枝の今の単位が途中なら、単位の
    worktree をその単位の頭に戻す（書きかけを当てない）"""
    tree = pathlib.Path(row["tree"])
    board_dir = work.parent
    green = []
    for i, k in enumerate(keys):
        u = lst["units"][k]
        c = lst.get("conflict")
        if c and c.get("unit_key") == k:
            probs = conflict.problems([c], repo=tree, board_dir=board_dir, owed={k}, try_query=try_query,
                                      briefs=planbrief.by_unit_at(board_dir))
            if probs:
                back[k] = {"why": "並べの食い違いの申し出が確かめを通らない: " + probs[0][:300]}
                continue
            st.setdefault("parked", []).append(k)
            st.setdefault("parked_why", {})[k] = c["why_both_cannot_hold"]
            st["units"][k].update(route="parked", why=c["why_both_cannot_hold"])
            items.append(c)
            out[k] = (PARKED, "")
        elif u.get("route") == "direct":
            if u.get("gave_up") == "writer":
                st["units"][k] = _record(u)
                out[k] = (DIRECT, u.get("why", ""))
            else:
                back[k] = {"why": f"並べで段の確かめを諦めた（{u.get('gave_up')}）: {(u.get('why') or '')[:300]}"}
        elif u.get("green") == "ok":
            green.append(k)
        elif not lst.get("done") and i >= lst.get("cur", 0):
            back[k] = {"why": "並べの段が済まなかった（下請けが段のコマンドを最後まで走らせなかった）"}
        else:
            back[k] = {"why": "並べで緑に届かなかった"}
    if not lst.get("done") and lst.get("cur", 0) < len(lst["queue"]):
        tddloop.restore(tree, lst["unit_head"])
    return green


def _record(u: dict) -> dict:
    """単位の控えの行を輪の状態の行に（赤の回の結末は持ち込まない）"""
    return {f: v for f, v in u.items() if f != "red_run"}


def _red_again(st, row, lst, k, work) -> str:
    """単位 k の赤を sandbox の外で確かめ直す（控えの赤の記録は下請けが書ける所に在る）。単位の worktree を、単位の頭の木に
    赤の時のテストのファイルだけを置いた姿にして名指しだけを回し、写しの red_problems と記録の赤の種類で照らす。赤の時の
    テストのファイルは、枝の次の単位の頭の木（無ければ今の姿）の中身で、凍結の記録と同じ物。回した後は worktree を元の姿に
    戻す。通れば空、記録どおりに落ちなければ戻す理由"""
    tree = pathlib.Path(row["tree"])
    u = lst["units"][k]
    keys = list(lst["queue"])
    i = keys.index(k)
    heads = lst.get("unit_heads") or {}
    head = (lst.get("lane_base") or lst["unit_head"]) if i == 0 else heads.get(k)
    tests, files = list(u.get("tests") or []), list(u.get("test_files") or [])
    if not tests:
        return "赤の記録に名指しのテストが無い（赤を確かめ直せない）"
    if not head:
        return "単位の頭の木が控えに無い（赤を確かめ直せない）"
    final = tddloop.snapshot(tree)
    src = heads.get(keys[i + 1]) if i + 1 < len(keys) else None
    then = tddloop._tree_hashes(tree, src, files) if src else tddloop.hashes(tree, files)
    if any(then[f] != (u.get("test_hashes") or {}).get(f) for f in files):
        return "テストのファイルの中身が赤の記録と違う（赤を確かめ直せない）"
    try:
        tddloop.restore_paths(tree, head, set(tddloop.touched(tree, head, final)) - set(files))
        if src:
            tddloop.restore_paths(tree, src, files)
        cases, code, why = tddloop.run_suite(lst["exe"], tree, work, f"lane-{row['n']}-red-{i + 1}", tddloop.abs_ids(tree, tests),
                                             only=True)
    finally:
        tddloop.restore(tree, final)
    if cases is None:
        return "赤を確かめ直す実行器が走らない（" + "; ".join(why)[:300] + "）"
    probs = tddloop.rules().red_problems(tests, cases, code, st["baseline"])
    if not probs:
        kinds = {t: tddloop.red_kind(tddloop.rules().match_case(t, cases) or {}) for t in tests}
        probs = [f"{t}: 赤の種類 {kinds[t]}（記録は {kk}）" for t, kk in (u.get("red_kinds") or {}).items() if kinds.get(t) != kk]
    return ("赤の記録を機械が確かめ直すと再現しない（単位の頭の木に赤の時のテストだけを置いて名指しを回した）: "
            + probs[0][:300]) if probs else ""


def _apply_lanes(st, repo, ready, log, work, back, how) -> list:
    """緑まで済んだ枝を目録の順に当てる。当てた枝の [(row, lst, green, patch)]。当たらない枝の単位は back へ"""
    union = sorted({f for _, lst, green in ready for k in green for f in lst["units"][k].get("test_files") or []})
    earlier, applied = set(), []
    for row, lst, green in ready:
        with _lane_read(row):
            why, patch, names, mode = _merge(st, repo, row, lst, green, log, work, earlier, union)
        how[row["n"]] = mode
        if why:
            for k in green:
                back[k] = {"why": why, **({"patch": patch} if patch else {})}
            continue
        earlier |= set(names)
        applied.append((row, lst, green, patch))
    return applied


def _merge(st, repo, row, lst, green, log, work, earlier: set, union) -> tuple:
    """枝の差分を当てる。(戻す理由（当てたら空）, 前の試みの差分のファイル, 差分のパス, 合わせの結末)。前に当てた枝の差分に
    出ていないファイルは中身が単位の worktree と同じか、重なりのファイルは名指しのテストの関数の源が同じかを見る"""
    tree = pathlib.Path(row["tree"])
    since = lst.get("lane_base") or lst["unit_head"]
    moved = sorted(set(tddloop.touched(tree, since, tddloop.snapshot(tree))) - set(lst.get("suite_made") or []))
    declared = lst.get("declared") or []
    if log.is_file():
        left = writes.unrecorded(tree, moved, log, declared)
        if left:
            return writes.REJECT + ", ".join(left[:10]), "", [], ""
        writes.keep_declared(log, tree, declared)
    patch = unittrees.diff(tree, st["lanes"]["base"])
    kept = work / KEPT / f"item-{row['n']}.patch"
    kept.parent.mkdir(parents=True, exist_ok=True)
    kept.write_text(patch, encoding="utf-8", errors="surrogateescape")
    before = tddloop.snapshot(repo)
    got = []
    ok, why = unittrees.apply(repo, patch, union=union, unioned=got, check=unitlanes.tests_unique)
    if not ok:
        return f"差分が run の作業ツリーに当たらない（{' '.join(why.split())[:300]}）", str(kept), [], CLASH
    names = unitlanes._names(patch)
    differ = [n for n in names if n not in earlier and not unitlanes._same(pathlib.Path(repo) / n, tree / n)]
    moved_tests = _moved_tests(repo, tree, [lst["units"][k] for k in green], set(names) & earlier)
    if differ or moved_tests:
        tddloop.restore_paths(repo, before, names)
        return (f"当てた中身が単位の worktree と違う（{differ[:5]}）" if differ
                else f"当てた後の名指しのテストの中身が単位の worktree と違う（{moved_tests[:5]}）"), str(kept), [], ""
    return "", str(kept), names, UNION if got else CLEAN


def _moved_tests(repo, tree, units, shared: set) -> list:
    """重なりのファイルに在る名指しのテストのうち、関数の源が単位の worktree と run の作業ツリーで違う・消えた物"""
    out = []
    for u in units:
        for f in sorted(set(u.get("test_files") or []) & shared):
            mine = _bodies(pathlib.Path(tree) / f, f)
            now = _bodies(pathlib.Path(repo) / f, f)
            out += [t for t in u.get("tests") or [] if tddloop._norm_id(t).startswith(f + "::")
                    and (mine.get(tddloop._id_base(t)) is None or mine.get(tddloop._id_base(t)) != now.get(tddloop._id_base(t)))]
    return out


def _bodies(path: pathlib.Path, rel: str) -> dict:
    """ファイルの test 関数の id（_id_base）→ 源（tddloop.test_functions）。読めなければ {}"""
    try:
        src = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return {}
    return {tddloop._id_base(i): body for i, body in tddloop.test_functions(src, rel).items()}


def _shared(applied) -> list:
    """当てた枝のうち 2 本以上の差分に出たファイル"""
    seen = {}
    for _, _, _, patch in applied:
        for n in unitlanes._names(pathlib.Path(patch).read_text(encoding="utf-8", errors="surrogateescape")):
            seen[n] = seen.get(n, 0) + 1
    return sorted(n for n, c in seen.items() if c > 1)


def _retry_without_later(st, repo, pre, applied, back, how, probs) -> tuple:
    """重なりの組の後の枝（前に当てた枝とファイルを共にする枝）を落とし、残りを当て直して緑を 1 回だけ確かめ直す。
    緑なら (残した枝, [])、落とした枝の単位は back へ（理由は意味の食い違い）。赤・当て直せなければ (applied, 赤の文)"""
    seen, keep, drop = set(), [], []
    for item in applied:
        names = set(unitlanes._names(pathlib.Path(item[3]).read_text(encoding="utf-8", errors="surrogateescape")))
        (drop if names & seen else keep).append(item)
        seen |= names
    if not drop:
        return applied, probs
    tddloop.restore(repo, pre)
    union = sorted({f for _, lst, green, _ in keep for k in green for f in lst["units"][k].get("test_files") or []})
    for _, _, _, patch in keep:
        text = pathlib.Path(patch).read_text(encoding="utf-8", errors="surrogateescape")
        ok, _ = unittrees.apply(repo, text, union=union, check=unitlanes.tests_unique)
        if not ok:
            tddloop.restore(repo, pre)
            for _, _, _, p2 in applied:
                unittrees.apply(repo, pathlib.Path(p2).read_text(encoding="utf-8", errors="surrogateescape"),
                                union=union, check=unitlanes.tests_unique)
            return applied, probs
    again = _green_after(st, repo, pre, [lst["units"][k] for _, lst, g, _ in keep for k in g], _shared(keep))
    if again:
        return keep, again
    first = [r["n"] for r, _, _, _ in keep]
    for row, _, green, patch in drop:
        how[row["n"]] = SEMANTIC
        for k in green:
            back[k] = {"why": (f"意味の食い違い: 先の枝 {first} と同じファイルを変え、字では合ったが合わせた木の試験が赤（"
                               + probs[0][:300] + "）。合わせた木の上で直し直す"), "patch": patch}
    return keep, []


def _carry(log: pathlib.Path, repo, applied, shared) -> None:
    """当てた枝の書き込みの記録を run の作業ツリーへ写す（重なりでないファイルは writes.carry、重なりのファイルは
    writes.carry_merged。受けた枝が決まった後に 1 度だけ）"""
    if not applied or not log.is_file():
        return
    shared = set(shared)
    pairs, srcs = [], {}
    for row, _, _, patch in applied:
        tree = pathlib.Path(row["tree"])
        for n in unitlanes._names(pathlib.Path(patch).read_text(encoding="utf-8", errors="surrogateescape")):
            if n in shared:
                srcs.setdefault(n, []).append(tree / n)
            else:
                pairs.append((tree / n, pathlib.Path(repo) / n))
    if pairs:
        writes.carry(log, pairs)
    for n, src in srcs.items():
        writes.carry_merged(log, pathlib.Path(repo) / n, src)


def _green_after(st, repo, pre: str, units: list, shared=()) -> list:
    """当てた後の木で、当てた単位の名指し全部と変更に直に関わる試験を 1 回走らせた緑の確かめ（重なりのファイルが在れば、それを
    起点に地図が届く試験の全部も足す。地図が一式を求める時は足さない（一式は線の最後のテストの段）。test_cmd の関門が on で軽量で
    ない単位が在れば test_cmd も 1 回）。赤・走らなければ文の一覧。緑なら次の単位の頭の回を進める"""
    tests = [t for u in units for t in u["tests"]]
    st["unit_head"] = pre
    files, full = tddloop._reached(st, repo)
    if shared and not full:
        wide, everything = tddloop._reached(st, repo, seeds=shared, direct_only=False)
        if not everything:
            files = sorted(set(files) | set(wide))
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
def unit_text(st: dict, row: dict, j: int = 1) -> str:
    """下請けのファイルの「この単位の下請けの決まり」の節（機械が書く。fixrules.tdd_lane_render の lane_text）。j は枝の中の単位の番"""
    lst = tddloop._load(row["state"])
    k = row["unit_keys"][j - 1]
    cmd = command_line(st["lanes"]["manifest"], row["n"], row["reply"], j)
    lines = ["## この単位の下請けの決まり（機械が書いた）", "",
             f"- 単位: {k}",
             f"- 単位の worktree: {row['tree']}（読む・書く・試験を回すのは全部この中。Bash は最初に cd し、Edit・Write のパスも"
             "この下。名指しのパスはこの根からの相対。修正役の作業ツリー（cwd）は書かない）",
             f"- 段の返答の置き場: {row['reply']}（作業ツリーの外。Write で段の返答の JSON を丸ごと書く）",
             f"- 段のコマンド: `{cmd}`（Bash で走らせる。出力の 1 行の JSON {{ok, done, phase, reason}} に従え）"]
    if j > 1:
        hand = pathlib.Path(row["state"]).parent / HANDOFF.format(j=j)
        lines += [f"- この枝の前の単位の引き継ぎ: {hand}（前の単位の下請けが済んだ時に機械が書く。最初に Read で全部読め。"
                  "前の単位の直しは単位の worktree に在る。戻したり作り直したりするな。ファイルが無ければ前の単位が済んでいないので、"
                  "何もせずに最後のメッセージに「前の単位が済んでいない」と書いて終わる）"]
    lines += ["",
              "## 段の進め方", "",
              "1. 段 test から始める。段の仕事をしたら、その段の返す JSON を返答の置き場に書き、段のコマンドを走らせる。",
              "2. ok が false で done が false なら reason を直して、同じ段の返答を丸ごと書き直して走らせ直す（同じ段の 3 回目の拒否で"
              "機械が諦める）。",
              "3. ok が true なら phase が次の段を言う（fix・refactor）。その段の仕事をして 1 に戻る。",
              "4. done が true になったら終わり（この単位の段が済んだ。枝の次の単位は別の下請けが直す）。最後のメッセージに、"
              "何をしたかを 3 行以内で書く（報告はファイルに書かない）。", "",
              "## 段ごとの仕事と返す JSON", ""]
    for p in ("test", "fix", "refactor"):
        lines += [f"### 段 {p}", "", tddloop.DO[p], "", tddloop.RETURN[p], ""]
    lines += ["### 食い違いの申し出（どの段でも）", "", tddloop.RETURN_CONFLICT.replace("（振り分けの段なら義務の単位のどれか、ほかの段なら今の単位）", ""), "",
              "## テストの回し方", "",
              f"単位の worktree の根で `{lst['exe']} <JUnit XML の書き先>`（書き先は worktree の外に）。"
              "機械は名指しを実行器の後ろに絶対パスの node id で足して回す。", ""]
    return "\n".join(lines)


def main(argv) -> int:
    if len(argv) not in (4, 5):
        print("使い方: python3 tddlanes.py <目録 lanes.json> <枝の番号> <段の返答の JSON のファイル> [<枝の中の単位の番>]",
              file=sys.stderr)
        return 2
    try:
        out = run(argv[1], argv[2], argv[3], argv[4] if len(argv) == 5 else None)
    except (LaneBroken, tddloop.Broken, OSError, subprocess.CalledProcessError, ValueError) as e:
        print(f"tddlanes: {' '.join(str(e).split())}", file=sys.stderr)
        return 2
    sys.stdout.reconfigure(encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
