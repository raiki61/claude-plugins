"""TDD の輪の単位を、枝ごとの単位の worktree で並べる（blk-fix。依頼 243 の並べの 2 段目・3 段目と、枝を Archon の節にした 4 段目。
設計 docs/plans/2026-10-06-tdd-parallel.md・docs/plans/2026-10-07-overlap-lanes.md・docs/plans/2026-10-07-lane-nodes.md）。
分け方・枝ごとの支度と確かめ・締めるを機械が持ち、AI は枝ごとの役の節（tdd-lane-<n>。枝の単位の worktree を cwd に包みが起こす）が
単位の段を 1 回の返答で 1 つずつ返す。赤・緑の確かめは tddloop.step をそのまま単位の worktree で回す（決まりを写さない）。

語:
- 枝: 並べの 1 本。修正案の項目を共にする tdd の単位の組（groups。単位が項目に無ければ 1 単位 1 枝）。枝ごとに単位の worktree を
  1 本切り、枝の中の単位は振り分けの順に 1 つずつ直す。単位が替わると包みが新しい会話で起こす（支度が書く単位の鍵。前の単位の物は
  指示書の引き継ぎの節で渡る）。範囲（ranges）の引けない単位を含む枝は順。範囲が重なる枝も並べ、当てる所で食い違った枝だけ順に戻す。
  枝は MAX_LANES 本まで（YAML の枝の輪 tdd-lane-1..MAX_LANES と同じ数）で、それより後の枝の単位は順
- 枝の輪: YAML の loop_group tdd-lane-<n>（支度 tdd-lane-prep-<n> → 役 tdd-lane-<n> → 確かめ tdd-lane-step-<n>）。枝どうしは同時に走る
- 単位の控え: 枝ごとの tddloop の状態（枝の単位だけ）。run ごとの置き場の <tdd-<k>>/lanes/lane-<n>/state.json。単位ごとの頭の木を
  unit_heads に、枝の頭を lane_base に持つ
- 目録（manifest）: 盤面の tdd-<k>/lanes.json {repo, base, place, rows: [{n, unit_keys, tree, git, state, files}]}。git は
  単位の worktree の `.git` の 1 行、files は枝の単位ごとの決まりのファイル（盤面の tdd-<k>/lane-<n>-<j>.md）。役は書けない
- 重なりのファイル（shared）: 当てた枝のうち 2 本以上の差分に出たファイル。合わせの結末（merge）は枝ごとに clean・union（試験の
  ファイルの挿しだけの食い違いを合わせた）・conflict（字の食い違い）・semantic（合わせた木で赤くなり後の枝を落とした）
- 戻す: 並べで済まなかった単位を順の単位として最初の段から回し直す（direct にしない）

口:
- ranges(board_dir, keys): 単位 → 範囲（単位を持つ修正案の項目の範囲 fixrules.item_ranges の和。項目が無い・範囲の無い項目が在る・
  空なら None）。盤面が開けなければ {}
- items_of(board_dir, keys): 単位 → 単位を持つ修正案の項目の番号の並び（planbrief.by_unit_at）。盤面が開けなければ {}
- groups(queue, items): 単位を項目を共にする物どうしの組に（純粋。振り分けの順）
- plan(st, repo): 振り分けの後（tddloop.step）。並べる枝が 2 本以上なら（MAX_LANES 本まで）単位の worktree と単位の控えと目録を置き、
  状態の段を lanes にして真（輪 tdd-loop はこの段で抜ける）。ほかは見送りの理由（SKIP_UNITS・SKIP_LANES）を状態の lanes_skipped に
  置いて偽（tddloop.step が出口の lanes_skipped に載せ、節 tdd-step が盤面の trace に SKIP_OP の行で積む）
- fork(state_file): 節 tdd-fork。枝の輪を起こすか {go, lanes, lane_1..lane_<MAX_LANES>}（状態の段が lanes の時だけ go）
- lane_prep(state_file, n, values): 節 tdd-lane-prep-<n>。枝 n の今の単位の決まりのファイルと回ごとの指示書を書き、包みが読む
  2 つの印（単位の鍵 adapter.session_key_path は run ごとの置き場、単位の worktree adapter.lane_tree_path は盤面の下）を置く。
  {prompt_file, go: true}。枝が済んでいれば（締めが済んだ・枝の控えが done。Archon の resume が済みと記録していない枝の輪を 1 周目から
  回し直した）何も書かずに {prompt_file: "", go: false}（役の節は when: で飛ぶ）
- lane_step(state_file, n, reply, repo): 節 tdd-lane-step-<n>。役の返答で単位の worktree の段を tddloop.step で確かめる（書き込みの
  出どころは run の作業ツリーの記録 writes.sink(repo) と突き合わせる）。食い違いの申し出は確かめずに控えに書く（盤面を読む確かめは
  settle）。{ok, done（枝の単位が全部済んだ）, phase, reason, unit_key}。枝が済んでいて返答が None（役が飛ばされた周）なら何も動かさずに
  done
- join(state_file, repo, try_query): 節 tdd-join。settle で締め、輪の呼びの記録を 1 行足して状態を保存する。{go（順に回す単位が残る）,
  done, phase, merged, back, conflicts（盤面に積む申し出）}。出口は状態の lanes.joined にも残し、締めた後にもう 1 度呼ばれたら（resume）
  それを申し出を空にして返す（盤面・作業ツリーを動かさない）
- settle(st, repo, try_query): 目録の順に枝を締める（単位ごとの申し出の確かめ・direct・赤の確かめ直し（_red_again。控えの赤の記録は
  確かめの節の外でも書き換えうるので、単位の頭の木と赤の時のテストのファイルで名指しを回し直す）・書き込みの記録の突き合わせ・
  3 方向で当てる（試験のファイルの挿しだけの食い違いは合わせる）・当てた中身と名指しのテストの照らし）、当てた後の木で緑をもう 1 度
  確かめ（重なりのファイルを起点に広げる。赤なら後の枝を落として 1 回だけ確かめ直す）、記録を写し、単位の worktree を片付けて順の段へ
  進める。run の作業ツリーに書かれた物は戻す（枝の役は包みの柵で書けないが、受け止めとして）。盤面に積む申し出の一覧を返す
- unit_text(st, row, j): 枝 n の j 番目の単位の決まりのファイルの「この単位の決まり」の節（lane_prep が fixrules.tdd_lane_render に渡す）。
  枝の後の単位のうち同じ修正案の項目で一緒に直す単位（tddloop.together）は「今は手を付けるな」に並べず、一緒に直す節に並べる
  （緑に届けば枝の控えの tddloop.step が閉じ、締めの赤の確かめ直しは枝で緑に届いた単位の名指しで見たものとする）
"""
from __future__ import annotations

import json
import pathlib
import sys
import time

sys.dont_write_bytecode = True   # 下の import が pack の中に __pycache__ を作らないように（必ず import より前）

_HERE = pathlib.Path(__file__).resolve().parent
for _p in (_HERE.parents[1] / ".shared" / "core", _HERE):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import adapter  # noqa: E402  （L2。run ごとの置き場 run_place_of・包みが読む 2 つの印の置き場）
import conflict  # noqa: E402
import entry  # noqa: E402
import fixrules  # noqa: E402  （項目の範囲 item_ranges・決まりのファイルの組み立て）
import lanekit  # noqa: E402  （並べの枝の部品: 切る・印・指しの確かめ・当てる・記録の写し・片付け。修正役の並べと共通）
import planbrief  # noqa: E402
import promptsection  # noqa: E402
import seat  # noqa: E402  （借りたスキルの座）
import tddloop  # noqa: E402
import unitlanes  # noqa: E402  （分け方 lanes・切る plant・patch の行先 _names・中身の比べ _same。1 段目の物をそのまま）
import unittrees  # noqa: E402
import writes  # noqa: E402
from board import BoardGap  # noqa: E402

MAX_LANES = lanekit.MAX_LANES   # 枝の輪の数（YAML の tdd-lane-1..3 と包みの adapter.KEYED_NODES の tdd-lane-<n>。試験が縛る）
LANE_NODE = "tdd-lane-{n}"  # 枝 n の役の節の印の名（包みが単位の worktree を cwd に起こし、単位の切れ目で会話を切る）
MANIFEST = "lanes.json"     # 目録（盤面の tdd-<k>/。共有の記録 tdd-*/**）
LANE_FILE = "lane-{n}-{j}.md"   # 枝 n の j 番目の単位の決まりのファイル（盤面の tdd-<k>/。単位の間は書き直さない）
LANE_NEXT = "lane-{n}.next.md"  # 枝 n の回ごとの指示書（盤面の tdd-<k>/。今の段・前の回を拒んだ理由）
KEPT = "lanes"              # 戻した枝の前の試みの差分の置き場（盤面の tdd-<k>/lanes/item-<n>.patch）
PLACE = "lanes"             # 単位の worktree と控えの置き場（run ごとの置き場の <tdd-<k>>/lanes）
LANE_DIR = "lane-{n}"
MERGED, BACK = lanekit.MERGED, lanekit.BACK   # 締めた後の単位の結末（当てた・順に戻した。修正役の並べと同じ語）
DIRECT, PARKED = "direct", "parked"
CLEAN, UNION, CLASH, SEMANTIC = "clean", "union", "conflict", "semantic"   # 枝ごとの合わせの結末（頭の語）
# 並べの見送り: 振り分けを受けた周で枝を切らなかった時の trace の行 {op: SKIP_OP, reason, why, loop}（節 tdd-step が積む）と理由の語。
# switch: 入力 tdd_lanes が off（tddloop.start が状態の lanes_off に置く）・units: tdd の単位が 2 つに
# 満たない・lanes: 範囲の引ける枝が 2 本に満たない（plan が状態の lanes_skipped に置く）
SKIP_OP = "lanes_skipped"
SKIP_SWITCH, SKIP_UNITS, SKIP_LANES = "switch", "units", "lanes"
JOINED = lanekit.JOINED   # 状態の lanes の欄: 締めの出口（締めた印。resume で回し直された締めはこれを返し、枝の輪は役を起こさずに抜ける）


def lane_nodes() -> list:
    """枝の役の節の印の名の全部（tdd-lane-1..MAX_LANES）"""
    return lanekit.node_names(LANE_NODE)


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
    """queue の単位を、修正案の項目を共にする物どうしの組に（項目でつながる単位は全部 1 組。組の中と組の並びは queue の順。lanekit.groups）"""
    return lanekit.groups([(k, items.get(k)) for k in queue])


def _span(got: dict, keys) -> list | None:
    """枝の範囲（単位の範囲の和）。範囲の引けない単位が在れば None"""
    spans = [got.get(k) for k in keys]
    return None if any(x is None for x in spans) else sorted({g for x in spans for g in x})


def plan(st: dict, repo) -> bool:
    """振り分けの後に並べる枝を選び、切る（頭の注記）。切らなければ状態の lanes_skipped に {reason, why}（SKIP_UNITS・SKIP_LANES）"""
    queue = list(st.get("queue") or [])
    if len(queue) < 2:
        st["lanes_skipped"] = {"reason": SKIP_UNITS, "why": f"TDD の輪で直す単位が {len(queue)} つ（並べは 2 つから）"}
        return False
    work = pathlib.Path(st["work"])
    got = ranges(work.parent, queue)
    grps = groups(queue, items_of(work.parent, queue))
    spans = [(i, _span(got, g)) for i, g in enumerate(grps, 1)]
    picked = unitlanes.lanes(spans)[:MAX_LANES]   # 枝の輪の数まで。後ろの枝の単位は順
    if not picked:
        known = sum(1 for _, p in spans if p is not None)
        st["lanes_skipped"] = {"reason": SKIP_LANES,
                               "why": f"単位 {len(queue)} つを修正案の項目でまとめた枝が {len(grps)} 本で、範囲の引ける枝が "
                                      f"{known} 本（並べは 2 本から）"}
        return False
    chosen = [grps[i - 1] for i in picked]
    place = pathlib.Path(adapter.run_place_of({"board": str(work.parent)})) / work.name / PLACE
    manifest = work / MANIFEST
    ns = list(range(1, len(chosen) + 1))
    trees = lanekit.plant(repo, ns, place, manifest)
    base = trees[ns[0]]["base"]
    rows = []
    for n, keys in zip(ns, chosen):
        tree = pathlib.Path(trees[n]["tree"])
        lane = place / LANE_DIR.format(n=n)
        lane.mkdir(parents=True, exist_ok=True)
        state = lane / tddloop.STATE
        tddloop._save(state, _lane_state(st, repo, keys, tree, lane))
        rows.append({"n": n, "unit_keys": list(keys), "tree": str(tree), "git": trees[n]["git"], "state": str(state),
                     "files": [str(work / LANE_FILE.format(n=n, j=j)) for j in range(1, len(keys) + 1)]})
    tddloop.save_json(manifest, {"repo": str(repo), "base": base, "place": str(place), "rows": rows})
    expect = unitlanes.expect([(n, spans[i - 1][1]) for n, i in zip(ns, picked)])
    st["lanes"] = {"manifest": str(manifest), "place": str(place), "base": base, "rows": rows, "expect": expect}
    st["phase"] = "lanes"
    return True


def _lane_state(st: dict, repo, keys, tree: pathlib.Path, lane: pathlib.Path) -> dict:
    """枝の控え: 輪の状態と同じ形で、枝の単位だけ・段 test から。実行器が run の作業ツリーの中なら単位の worktree の同じ物"""
    exe = lanekit.relocate(st["exe"], repo, tree)
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
            "contract": contract, "test_cmd": st.get("test_cmd", ""),
            "test_cmd_gate": st.get("test_cmd_gate", tddloop.GATE_OFF), "test_cmd_note": st.get("test_cmd_note", ""),
            "light": [k for k in keys if k in light], "calls": [], "head_run": tddloop._head_run(st),
            "declared": [], "conflict": None, "lanes_on": False, "lane_base": head, "unit_heads": {keys[0]: head}}


# ---------------------------------------------------------------- 枝の輪を起こすか（節 tdd-fork）
def fork(state_file) -> dict:
    """{go, lanes, lane_1..lane_<MAX_LANES>}。状態のファイルが空（実行器の無い run）・段が lanes でなければ go: false"""
    out = lanekit.fork_out([])
    if not state_file:
        return out
    st = tddloop._load(state_file)
    if st.get("done") or st.get("phase") != "lanes":
        return out
    rows = (st.get("lanes") or {}).get("rows") or []
    ns = [r.get("n") for r in rows]
    try:
        return lanekit.fork_out(ns, empty_ok=False)
    except ValueError as e:
        raise tddloop.Broken(f"並べの目録の{e}") from None


# ---------------------------------------------------------------- 枝の輪の中（節 tdd-lane-prep-<n>・tdd-lane-step-<n>）
def _lane(st: dict, n) -> dict:
    """状態の目録の枝 n の行。段が lanes でない・枝が無ければ Broken"""
    if st.get("phase") != "lanes" or not st.get("lanes"):
        raise tddloop.Broken(f"並べの周でない（段 {st.get('phase')!r}）——枝の輪は tdd-fork が起こした時だけ回る")
    row = next((r for r in st["lanes"]["rows"] if str(r["n"]) == str(n)), None)
    if row is None:
        raise tddloop.Broken(f"並べの目録に枝 {n} が無い")
    return row


def _over(st: dict, n) -> bool:
    """枝 n が済んでいるか: 締め（join）が済んだ（目録に枝 n が在る時だけ）か、枝の控えが done。Archon の resume は済みと記録して
    いない枝の輪を 1 周目から回し直す（枝の輪が落ちても all_done の締めは走る・控えの done の保存と輪の済みの記録の間に止まる）。
    その時の支度と確かめはここで役を起こさずに抜ける。並べの周でない・枝が無ければ Broken（_lane）"""
    joined = (st.get("lanes") or {}).get(JOINED)
    if joined is not None:
        if not any(str(r["n"]) == str(n) for r in st["lanes"]["rows"]):
            raise tddloop.Broken(f"並べの目録に枝 {n} が無い")
        return True
    return bool(tddloop._load(_lane(st, n)["state"])["done"])


def lane_prep(state_file, n, values: dict | None = None) -> dict:
    """節 tdd-lane-prep-<n>（頭の注記）。{prompt_file, go}。枝が済んでいれば（_over）{"prompt_file": "", "go": False}"""
    st = tddloop._load(state_file)
    if _over(st, n):   # resume で回し直された済んだ枝の輪: 役を起こさない（YAML の役の when: が go を読む）
        return {"prompt_file": "", "go": False}
    row = _lane(st, n)
    why = lanekit.tree_ok(row)
    if why:
        raise tddloop.Broken(why)
    lst = tddloop._load(row["state"])
    work = pathlib.Path(st["work"])
    board_dir = work.parent
    j = lst["cur"] + 1
    k = lst["queue"][lst["cur"]]
    vals = {**{x: "" for x in fixrules.TDD_VALUES}, **(values or {}), "open_units": json.dumps([k], ensure_ascii=False)}
    briefs = tddloop._briefs(board_dir)
    try:
        seat_text = seat.section("tdd")
    except ValueError as e:
        raise tddloop.Broken(f"TDD の輪の座を組めない: {e}") from None
    brief_file = pathlib.Path(row["files"][j - 1])
    text = fixrules.tdd_lane_render(vals, unit_text(st, row, j, lst),
                                    title=UNIT_TITLE.format(n=row['n'], j=j, k=k),
                                    brief=planbrief.head_text(planbrief.for_units(briefs, [k]), [k, *tddloop.together(lst, k)]),
                                    seat=seat_text,
                                    lang=fixrules.lang_at(board_dir))
    brief_file.write_text(text, encoding="utf-8")
    prompt = work / LANE_NEXT.format(n=row["n"])
    prompt.write_text(_next_text(row, lst, j, k, brief_file), encoding="utf-8")
    lanekit.mark(board_dir, LANE_NODE.format(n=row["n"]), f"{work.name}:lane-{row['n']}:{k}", row["tree"])
    return {"prompt_file": str(prompt), "go": True}


NEXT_REJECT_HEAD = promptsection.Section("## 前の回の返答を機械が拒んだ理由（直して、この段の返答を丸ごと出し直せ）", source="fn:tddlanes._next_text")
READ_HEAD = promptsection.Section("## 読む物", source="fn:tddlanes._next_text")
NOW_HEAD = promptsection.Section("## 今の単位と段", source="fn:tddlanes._next_text")
DO_HEAD = promptsection.Section("## この段ですること", source="fn:tddlanes._next_text")
REPLY_HEAD = promptsection.Section("## 返す JSON", source="fn:tddlanes._next_text")
STEP_TITLE = promptsection.Section("# TDD の輪の並べの回ごとの指示書（枝 {n} の {j} 番目の単位・{count} 回目・段 {phase}）",
                                   source="fn:tddlanes._next_text")
UNIT_TITLE = promptsection.Section("# TDD の輪の並べの 1 単位（枝 {n} の {j} 番目・単位 {k}）", source="fn:tddlanes.lane_prep")
PHASE_HEAD = promptsection.Section("### 段 {phase}", source="fn:tddlanes.unit_text")


def _next_text(row: dict, lst: dict, j: int, k: str, brief_file: pathlib.Path) -> str:
    """回ごとの指示書（今の段・前の回を拒んだ理由・決まりのファイルの名指し）"""
    phase = lst["phase"]
    u = lst["units"][k]
    fresh = phase == "test" and not lst["tries"] and not u.get("tests")
    lines = [STEP_TITLE.format(n=row['n'], j=j, count=lst['iterations'] + 1, phase=phase), ""]
    if lst["reason"]:
        lines += [NEXT_REJECT_HEAD, "", lst["reason"].rstrip("\n"), ""]
    lines += [READ_HEAD, "",
              f"- この単位の決まり: {brief_file}——" + ("この単位の最初の回。Read で全部読め" if fresh else
                                                     "この単位の間は書き直さない（この会話で読んでいなければ Read で全部読め）"),
              "", NOW_HEAD, "", f"- 単位: {k}", f"- 段: {phase}", "",
              DO_HEAD, "", tddloop.DO[phase], ""]
    if phase in ("fix", "refactor") and lst.get("test_cmd_gate") == tddloop.GATE_ON and k not in lst.get("light", []):
        lines += [f"緑の後に機械が run の test_cmd（`{lst['test_cmd']}`）も単位の worktree で走らせる。これも緑にせよ。", ""]
    if u.get("tests"):
        lines += [f"- 名指しのテスト: {', '.join(u['tests'])}", f"- テストのファイル（凍っている）: {', '.join(u['test_files'])}", ""]
    lines += [REPLY_HEAD, "", tddloop.RETURN[phase], "",
              tddloop.RETURN_CONFLICT.replace("（振り分けの段なら義務の単位のどれか、ほかの段なら今の単位）", "（今の単位）"), "",
              "返すのは上の形の JSON だけ。"]
    return "\n".join(lines) + "\n"


def lane_step(state_file, n, reply, repo) -> dict:
    """節 tdd-lane-step-<n>（頭の注記）"""
    st = tddloop._load(state_file)
    if reply is None and _over(st, n):   # 支度が go: false を返して役が飛ばされた周（resume）: 何も動かさずに輪を抜ける
        return {"ok": True, "done": True, "phase": "done", "reason": "", "unit_key": ""}
    row = _lane(st, n)
    why = lanekit.tree_ok(row)
    lst_file = pathlib.Path(row["state"])
    if why:   # 枝を済みにして抜ける（輪を落とさない。締めが枝の単位を順に戻す）
        try:
            lst = tddloop._load(lst_file)
            lst.update(done=True, note=why)
            tddloop._save(lst_file, lst)
        except tddloop.Broken:
            pass
        return {"ok": False, "done": True, "phase": "done", "reason": why, "unit_key": ""}
    lst = tddloop._load(lst_file)
    if lst["done"]:
        raise tddloop.Broken(f"枝 {n} の単位は全部済んでいる（tdd-lane-step を呼ぶ番でない）")
    tree = pathlib.Path(row["tree"])
    k = lst["queue"][lst["cur"]]
    if isinstance(reply, dict) and reply.get("phase") == "conflict":
        return {**_park(lst_file, lst, reply, tree), "unit_key": k}
    items = reply.get(writes.FIELD) if isinstance(reply, dict) else None
    cur = lst["cur"]
    out = tddloop.step(lst_file, reply, tree, log=writes.sink(repo))
    lst = tddloop._load(lst_file)
    if out["ok"] and items and not writes.shape_problems(items):
        lst["declared"] = [*lst.get("declared", []), *items]
    _mark_head(lst, cur)
    tddloop._save(lst_file, lst)
    return {"ok": out["ok"], "done": lst["done"], "phase": out["phase"], "reason": out["reason"], "unit_key": k}


def _mark_head(lst: dict, cur: int) -> None:
    """枝が次の単位へ移ったら、その単位の頭の木を残す（締めの赤の確かめ直しが単位ごとに使う）"""
    if lst["cur"] != cur and not lst["done"]:
        lst.setdefault("unit_heads", {})[lst["queue"][lst["cur"]]] = lst["unit_head"]


def _park(state: pathlib.Path, lst: dict, reply: dict, tree: pathlib.Path) -> dict:
    """食い違いの申し出: 欄と単位だけ見て控えに書き、木を今の単位の頭に戻して枝を済みにする（枝の後の単位は締めが順に戻す。
    盤面を読む確かめは settle）。欄・単位が違えば拒む（同じ段の拒否に数える）"""
    k = lst["queue"][lst["cur"]]
    extra = sorted(set(reply) - {"phase", *conflict.FIELDS, conflict.CORRECT})
    if extra or reply.get("unit_key") != k:
        why = (f"食い違いの申し出の欄は phase と {list(conflict.FIELDS)}（query なら {conflict.CORRECT} も）だけ（{extra}）" if extra
               else f"この枝の今の単位は '{k}'（申し出の unit_key は {reply.get('unit_key')!r}）")
        cur = lst["cur"]
        lst["tries"] += 1
        lst["reason"] = f"- {why}"
        lst["iterations"] += 1
        lst["calls"].append({"n": lst["iterations"], "phase": "conflict", "unit_key": k, "ok": False, "runs": 0, "secs": 0.0})
        if lst["tries"] >= tddloop.retry_max():
            tddloop._give_up(lst, tree, [why])
        if not lst["done"] and lst["iterations"] >= tddloop.MAX_ITERATIONS:   # 回数の上限で輪を落とさない（R50。step と同じ）
            tddloop._abort(lst, tree, f"TDD の輪の回数の上限（{tddloop.MAX_ITERATIONS} 回）に届いた", "budget")
        if lst["done"]:
            tddloop._finish(lst, tree)
        _mark_head(lst, cur)
        tddloop._save(state, lst)
        return {"ok": False, "done": lst["done"], "phase": "done" if lst["done"] else lst["phase"], "reason": why}
    item = {f: reply.get(f) for f in conflict.FIELDS}
    if conflict.CORRECT in reply:
        item[conflict.CORRECT] = reply[conflict.CORRECT]
    tddloop.restore(tree, lst["unit_head"])
    lst["iterations"] += 1
    lst.update(conflict=item, done=True)
    lst["calls"].append({"n": lst["iterations"], "phase": "conflict", "unit_key": k, "ok": True, "runs": 0, "secs": 0.0})
    tddloop._save(state, lst)
    return {"ok": True, "done": True, "phase": "done", "reason": ""}


# ---------------------------------------------------------------- 締める（節 tdd-join）
def join(state_file, repo, try_query=None, park=None) -> dict:
    """節 tdd-join（頭の注記）。park は確かめを通った申し出の並びを盤面に積む口（無ければ積まずに出口の conflicts に残す）。
    出口を保存してから積み、積んだら出口の conflicts を空にして保存し直す: 保存と積みの間で落ちても、resume の締めが積んでいない
    申し出を積む（conflict.park は同じ申し出を積み増さない）"""
    st = tddloop._load(state_file)
    joined = (st.get("lanes") or {}).get(JOINED)
    if joined is not None:   # resume で回し直された締め: 締めた時の出口をそのまま返す（盤面・作業ツリーを動かさない。積み終えた
        out = dict(joined)   # 申し出は空で積み直さない）。節の出力は同じなので Archon は後ろの節の済みを使い続ける
        _park_claims(state_file, st, out["conflicts"], park)
        return out
    if st.get("done") or st.get("phase") != "lanes" or not st.get("lanes"):
        raise tddloop.Broken(f"並べの周でない（段 {st.get('phase')!r}）——tdd-join は枝の輪の後に 1 回だけ回る")
    t0, runs0 = time.monotonic(), st["runs"]
    items = settle(st, repo, try_query)
    st["iterations"] += 1
    if not st["done"] and st["iterations"] >= tddloop.MAX_ITERATIONS:
        tddloop._abort(st, repo, f"TDD の輪の回数の上限（{tddloop.MAX_ITERATIONS} 回）に届いた", "budget")
    if st["done"]:
        tddloop._finish(st, repo)
    st.setdefault("calls", []).append({"n": st["iterations"], "phase": "lanes", "unit_key": "", "ok": True,
                                       "runs": st["runs"] - runs0, "secs": round(time.monotonic() - t0, 1)})
    rows = st["lanes"]["out"]
    out = {"go": not st["done"], "done": st["done"], "phase": "done" if st["done"] else st["phase"],
           "merged": sum(1 for r in rows if r["outcome"] == MERGED), "back": sum(1 for r in rows if r["outcome"] == BACK),
           "conflicts": items}
    st["lanes"][JOINED] = dict(out)   # 積み終えるまで申し出を出口に残す（積んだら空にする。節の出力に申し出は載らない）
    tddloop._save(state_file, st)
    _park_claims(state_file, st, items, park)
    return dict(out)


def _park_claims(state_file, st: dict, items: list, park) -> None:
    """申し出を積む口に渡し、渡せたら保存した出口の申し出を空にする（再生は積まない）"""
    if not items or park is None:
        return
    park(list(items))
    st["lanes"][JOINED]["conflicts"] = []
    tddloop._save(state_file, st)


def settle(st: dict, repo, try_query=None) -> list:
    """頭の注記。st を書き換え、盤面に積む申し出の一覧を返す"""
    repo = pathlib.Path(repo)
    lanes = st["lanes"]
    work = pathlib.Path(st["work"])
    log = writes.sink(repo)
    # 枝の役は run の作業ツリーを書けない（包みの柵）。書かれていれば機械が戻す（受け止め）
    lanes["reverted"] = lanekit.revert_strays(repo, st["handoff"], st["suite_made"])
    pre = st["handoff"]
    out, back, items, calls, ready, how = {}, {}, [], [], [], {}
    for row in lanes["rows"]:
        keys = row["unit_keys"]
        try:
            why = lanekit.tree_ok(row)
            if why:
                raise tddloop.Broken(why)
            lst = tddloop._load(row["state"])
        except tddloop.Broken as e:
            for k in keys:
                back[k] = {"why": f"単位の控えが読めない（{e}）"}
            continue
        calls += [{**c, "lane": row["n"]} for c in lst.get("calls") or []]
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
    lanekit.carry(log, repo, [(row["tree"], patch) for row, _, _, patch in applied], shared)
    for _, lst, green, _ in applied:
        for k in green:
            st["units"][k] = _record(lst["units"][k])
            out[k] = (MERGED, "")
    for k in back:
        st["units"][k] = tddloop._unit(k, "tdd")
        out[k] = (BACK, back[k]["why"])
    lanekit.remove(repo, [row["tree"] for row in lanes["rows"]])
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
            probs = lanekit.claim_problems(c, tree, board_dir, {k}, try_query, planbrief.by_unit_at(board_dir))
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
            back[k] = {"why": "並べの段が済まなかった（枝の輪が単位を最後まで回さなかった）" + (f": {lst['note'][:300]}" if lst.get("note") else "")}
        elif lst.get("note") and u.get("green") != "ok":
            back[k] = {"why": f"並べで緑に届かなかった: {lst['note'][:300]}"}
        else:
            back[k] = {"why": "並べで緑に届かなかった"}
    if not lst.get("done") and lst.get("cur", 0) < len(lst["queue"]):
        tddloop.restore(tree, lst["unit_head"])
    return green


def _record(u: dict) -> dict:
    """単位の控えの行を輪の状態の行に（赤の回の結末は持ち込まない）"""
    return {f: v for f, v in u.items() if f != "red_run"}


def _red_again(st, row, lst, k, work) -> str:
    """単位 k の赤を確かめ直す（控えの赤の記録は run ごとの置き場に在り、役の sandbox からも書ける）。単位の worktree を、単位の頭の木に
    赤の時のテストのファイルだけを置いた姿にして名指しだけを回し、写しの red_problems と記録の赤の種類で照らす。赤の時の
    テストのファイルは、枝の次の単位の頭の木（無ければ今の姿）の中身で、凍結の記録と同じ物。回した後は worktree を元の姿に
    戻す。通れば空、記録どおりに落ちなければ戻す理由"""
    tree = pathlib.Path(row["tree"])
    u = lst["units"][k]
    if u.get("covered_by"):   # 段を回さずに閉じた単位: 赤は枝で緑に届いた単位の名指しに在り、その単位の確かめ直しが見る
        seen = {tddloop._norm_id(t) for v in lst["units"].values() if v.get("route") == "tdd" and v.get("green") == "ok"
                and not v.get("covered_by") for t in v.get("tests") or []}
        if {tddloop._norm_id(t) for t in u.get("tests") or []} <= seen:
            return ""
        return "枝で緑に届いた単位の赤の記録に、閉じた単位の名指しが無い（赤を確かめ直せない）"
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
    src = next((heads[q] for q in keys[i + 1:] if q in heads), None)   # 閉じた単位は頭の木を持たない（木を変えない）ので飛ばす
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
    applied = []
    for (row, lst, green), got in lanekit.merge_in_order(
            ready, lambda lane, earlier: _merge(st, repo, *lane, log, work, earlier, union)):
        if got.why:
            how[row["n"]] = CLASH if got.clash else ""
            for k in green:
                back[k] = {"why": got.why, **({"patch": got.patch} if got.patch else {})}
            continue
        how[row["n"]] = UNION if got.unioned else CLEAN
        applied.append((row, lst, green, got.patch))
    return applied


def _merge(st, repo, row, lst, green, log, work, earlier, union) -> lanekit.Merge:
    """枝の差分を当てる（lanekit.merge）。TDD の段だけの照らし: 前に当てた枝と重なるファイルの名指しのテストの関数の源が単位の
    worktree と同じか（_moved_tests）"""
    tree = pathlib.Path(row["tree"])

    def tests_moved(names):
        moved = _moved_tests(repo, tree, [lst["units"][k] for k in green], set(names) & earlier)
        return f"当てた後の名指しのテストの中身が単位の worktree と違う（{moved[:5]}）" if moved else ""
    return lanekit.merge(repo, tree, since=lst.get("lane_base") or lst["unit_head"], base=st["lanes"]["base"], log=log,
                         declared=lst.get("declared") or [], made=lst.get("suite_made") or [],
                         kept=work / KEPT / f"item-{row['n']}.patch", union=union, earlier=earlier, check=tests_moved)


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
    """当てた枝のうち 2 本以上の差分に出たファイル（lanekit.shared）"""
    return lanekit.shared([patch for _, _, _, patch in applied])


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




RULES_HEAD = promptsection.Section("## この単位の決まり（機械が書いた）", source="fn:tddlanes.unit_text")
STEPS_HEAD = promptsection.Section("## 段の進め方", source="fn:tddlanes.unit_text")
PHASES_HEAD = promptsection.Section("## 段ごとの仕事と返す JSON", source="fn:tddlanes.unit_text")
CONFLICT_HEAD = promptsection.Section("### 食い違いの申し出（どの段でも）", source="fn:tddlanes.unit_text")
RUN_HEAD = promptsection.Section("## テストの回し方", source="fn:tddlanes.unit_text")

# 並べの枝の輪の役は、枝の指示書と単位の決まりのファイルと brief を受ける
# （役の名は lanekit から引く）
RECEIVES = [
    *planbrief.receives(lane_nodes()),
    *(promptsection.Receive(role, head) for role in lane_nodes() for head in (
        NEXT_REJECT_HEAD, READ_HEAD, NOW_HEAD, DO_HEAD, REPLY_HEAD, STEP_TITLE, UNIT_TITLE, PHASE_HEAD, RULES_HEAD, STEPS_HEAD,
        PHASES_HEAD, CONFLICT_HEAD, RUN_HEAD, tddloop.HANDOFF_HEAD, tddloop.TOGETHER_HEAD, seat.HEAD)),
]


# ---------------------------------------------------------------- 単位の決まりのファイル（節 tdd-lane-prep-<n>）
def unit_text(st: dict, row: dict, j: int = 1, lst: dict | None = None) -> str:
    """単位の決まりのファイルの「この単位の決まり」の節（機械が書く。fixrules.tdd_lane_render の lane_text）。j は枝の中の単位の番"""
    lst = tddloop._load(row["state"]) if lst is None else lst
    k = row["unit_keys"][j - 1]
    both = tddloop.together(lst, k)
    later = [q for q in row["unit_keys"][j:] if q not in both]
    lines = [RULES_HEAD, "",
             f"- 単位: {k}（並べの枝 {row['n']} の {j} 番目）",
             f"- 作業ツリー: あなたの cwd（単位の worktree {row['tree']}）。読む・書く・試験を回すのは全部この中。名指しのパスはこの"
             f"根からの相対。run の作業ツリー（{lanes_repo(st)}）とほかの枝の worktree は書かない（包みの柵が拒む）"]
    if later:
        lines.append("- この枝の後の単位（今は手を付けるな。この単位が済んだ後に新しい会話で直す）: " + " / ".join(later))
    lines.append("")
    lines += tddloop._together_lines(lst, k)
    if j > 1:
        hand = tddloop.handoff_lines(lst)
        lines += [ln.replace("作業ツリーに在る（緑の木）", "この worktree に在る（緑の木）") for ln in hand] if hand else []
    lines += [STEPS_HEAD, "",
              "1. 段は test → fix →（申告した時と brief で申告した単位だけ）refactor。回ごとに機械が回ごとの指示書（今の段・前の回を"
              "拒んだ理由）を書く。その段の仕事をして、その段の返す JSON だけを返せ。",
              "2. 機械が拒めば、次の回の指示書に理由が載る。直して同じ段の返答を丸ごと出し直せ（同じ段の 3 回目の拒否で機械が諦める）。",
              "3. 単位が済めば、この会話は終わる（枝の次の単位は新しい会話で直す）。", "",
              PHASES_HEAD, ""]
    for p in fixrules.LANE_PHASES:
        lines += [PHASE_HEAD.format(phase=p), "", tddloop.DO[p], "", tddloop.RETURN[p], ""]
    lines += [CONFLICT_HEAD, "",
              tddloop.RETURN_CONFLICT.replace("（振り分けの段なら義務の単位のどれか、ほかの段なら今の単位）", "（今の単位）"), "",
              RUN_HEAD, "",
              f"cwd（単位の worktree の根）で `{lst['exe']} <JUnit XML の書き先>`（書き先は worktree の外の /tmp の下など）。"
              "機械は名指しを実行器の後ろに絶対パスの node id で足して回す。", ""]
    return "\n".join(lines)


def lanes_repo(st: dict) -> str:
    """並べの目録の run の作業ツリー（目録が読めなければ状態の置き場の名）"""
    try:
        return json.loads(pathlib.Path(st["lanes"]["manifest"]).read_text(encoding="utf-8"))["repo"]
    except (OSError, ValueError, KeyError, TypeError):
        return "cwd の外"
