"""修正役の並べを Archon の節にする（blk-fix。依頼 243 の並べの 5 段目。設計 docs/plans/2026-10-07-fix-lane-nodes.md）。
前の形（修正役が Agent で範囲の在る項目の下請けを同時に起こし、役の sandbox の中で当てるコマンドを走らせた）の代わりに、修正役の
輪（fix-loop）の前に、範囲の在る修正案の項目を枝ごとの Archon の輪（fix-lane-loop-<n>）で同時に直し、締めの節が run の作業ツリーへ
3 方向で当て、残りと戻した項目を修正役の輪が順に直す。分け方・支度・確かめ・締めは機械が持ち、AI は枝の役の節（fix-lane-<n>。包みが
枝の単位の worktree を cwd に起こす。旗 lane と self-resume）が項目を 1 つずつ直して修正役の返答の形で返す。

語:
- 項目: 承認済みの修正案の項目（planbrief の brief の行）。枝で直すのは、修正役が下請けを起こす単位（fixrules.dispatched。TDD の
  輪が緑にした単位を除く）を持ち、範囲（fixrules.item_ranges）の在る項目だけ。項目の単位は今の直す義務と重なる物だけ
- 組（groups）: 単位を共にする項目どうし（1 つの単位を 2 本の枝が直さない）。組は 1 本の枝に入る
- 枝: 単位の worktree 1 本と、そこで順に直す項目の並び（MAX_ITEMS まで）。枝は MAX_LANES 本まで（YAML の枝の輪の数）。枝に入らない
  組の項目は修正役の輪が順に直す。枝の中の項目が替わると包みが新しい会話で起こす（支度が書く単位の鍵。adapter.KEYED_NODES）
- 目録（MANIFEST）: 今の scope の周の作業ファイル {repo, base, place, union, expect, lanes: [{n, tree, git, state, items}], rest, why}
- 枝の控え（LANE_STATE）: 今の scope の周の作業ファイル（盤面。役は書けない）{n, tree, git, base, head, items: [{item, units, brief,
  rules, review, patch}], cur, tries, iterations, reason, done, note, results, claims, declared, tests, ask, ask_config}。head は今の項目の頭の
  木（切った時は base の木。項目を受けた・諦めた後に取り直す）。枝の確かめの書き込みの出どころと範囲は head から照らす（同じ枝の前の
  項目が変えたファイルを後の項目のせいにしない。run 97fd532f）。ask_config は範囲の相談の控え（事前の確かめの since を支度が head に揃える）
- 項目の決まりのファイル（RULES_FILE）: 修正役の決まり（fixrules.fix_parts。この項目の単位・brief・座 implementer・範囲の相談）と
  枝の役の節（rules/direct.md の fix-lane）。項目の間は書き直さない。回ごとの指示書（NEXT_FILE）は今の回の拒否の理由と決まりの名指し
- 結末（締め）: merged（枝の差分を当てた項目）・serial（戻した。修正役の輪が直す）。食い違いの申し出で止めた単位は盤面に積む

口:
- groups(rows)・assign(groups): 分け方（純粋）
- candidates(b, values, green): 枝で直してよい項目の行と、直す義務に揃えた値
- fork(board_dir, repo, values, green, switch): 節 fix-fork。並べる枝が 2 本以上なら単位の worktree を切り、枝の控え・項目の決まりの
  ファイル・審査役のファイル・範囲の相談の控えを書いて {go, lanes, lane_<n>, why}。前に切った枝の締めの結末は消す
- lane_prep(board_dir, n): 節 fix-lane-prep-<n>。回ごとの指示書（範囲の相談の答えが来た周は consult の続きの指示書）と包みが読む
  2 つの印（単位の鍵・単位の worktree）。{prompt_file, go: true}。枝が済んでいれば（締めが止めた枝を含む。Archon の resume が済みと
  記録していない枝の輪を回し直した）何も書かずに {prompt_file: "", go: false}（役と相談の節は飛ぶ）
- lane_step(board_dir, n, reply, repo, ...): 節 fix-lane-step-<n>。範囲の相談の周は数えるだけ。ほかは受け付けと同じ事実の確かめ
  （check）を単位の worktree に当て、通れば次の項目へ、同じ項目の GIVE_UP_AFTER 回目の拒否で項目を諦める（差分を控えて木を項目の頭に
  戻す）。{ok, done, consulted, reason, item}。枝が済んでいて返答が None（役が飛ばされた周）なら何も動かさずに done
- check(...): 枝の確かめの中身（拒否の行 [(id, 文)]・bash_writes と consult と conflicts を外した返答・通った申し出）
- join(board_dir, repo, try_query): 節 fix-join。枝ごとに差分を run の作業ツリーへ 3 方向で当て（試験のファイルの挿しだけの食い違いは
  合わせる）、書き込みの記録を写し、申し出を確かめ直して盤面に積み、結末（fixrules.LANES_RECORD・LANES_SUMMARY）と trace を書いて
  単位の worktree を片付ける。{ok, merged, back, parked, shared, union}。出口は結末の joined にも残し、結末が在れば（締めた後に resume が
  もう 1 度呼んだ）作業ツリーを戻さず、残った単位の worktree だけ片付けてそれを返す
"""
from __future__ import annotations

import json
import os
import pathlib
import sys

sys.dont_write_bytecode = True   # 下の import が pack の中に __pycache__ を作らないように（必ず import より前）

_HERE = pathlib.Path(__file__).resolve().parent
for _p in (_HERE.parents[1] / ".shared" / "core", _HERE):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import adapter  # noqa: E402  （L2。run ごとの置き場・包みが読む 2 つの印の置き場）
import conflict  # noqa: E402
import consult  # noqa: E402  （範囲の相談の枠・控え・答えの引き）
import entry  # noqa: E402
import factchecks  # noqa: E402  （受け付けと同じ事実の確かめの口）
import fixrules  # noqa: E402  （修正役の決まりの組み立て・直す義務・項目の範囲）
import lanekit  # noqa: E402  （並べの枝の部品: 切る・印・指しの確かめ・当てる・記録の写し・申し出・片付け。TDD の輪の並べと共通）
import planbrief  # noqa: E402
import planmarks  # noqa: E402
import promptsection  # noqa: E402
import recount  # noqa: E402  （修正役の印の名 ROLE・裁定の後の修正役の印の名 RULED_ROLE）
import rolekit  # noqa: E402
import script_io  # noqa: E402
import seat  # noqa: E402
import tddloop  # noqa: E402  （木の固め・戻し・試験を選んで回す）
import unitlanes  # noqa: E402
import unittrees  # noqa: E402
import writes  # noqa: E402
from board import BoardGap  # noqa: E402

MAX_LANES = lanekit.MAX_LANES   # 枝の輪の数（YAML の fix-lane-loop-1..3・包みの adapter.KEYED_NODES の fix-lane-<n>。試験が縛る）
MAX_ITEMS = 3        # 1 本の枝が順に直す項目の数の上限（後ろの組は修正役の輪が順に直す）
GIVE_UP_AFTER = 3    # 同じ項目の何回目の拒否で諦めるか（scripts/accept.py の GIVE_UP_AFTER と同じ。試験が縛る）
MAX_ITERATIONS = MAX_ITEMS * GIVE_UP_AFTER + consult.BUDGET   # 枝の輪の max_iterations（項目ごとの拒否の回と範囲の相談の枠の和）
LANE_NODE = "fix-lane-{n}"            # 枝 n の役の節の印の名
ANSWER_NODE = "plan-answer-lane-{n}"  # 枝 n の範囲の相談の答えの節の名
PASS = "lane-{n}"                      # 枝 n の範囲の相談の段の名（consult の状態・答えのファイルの名と枠を枝ごとに分ける）
MANIFEST = "fix-lanes.json"
LANE_STATE = "fix-lane-{n}.json"
RULES_FILE = "fix-lane-{n}-{j}.md"
BRIEFS_FILE = "fix-lane-{n}-{j}-briefs.md"   # 座の型の [BRIEF_FILE]（fixrules.implementer_values）
REVIEW_FILE = "fix-lane-{n}-{j}-review.md"   # 審査役の下請けのファイル（fixrules.review_text）
NEXT_FILE = "fix-lane-{n}.next.md"
JOINED = lanekit.JOINED   # 結末（fixrules.LANES_RECORD）の欄: 締めの出口（resume で回し直された締めはこれを返す）
REPLY_FILE = "fix-lane-{n}-{j}-reply.json"   # 通った枝の返答（修正役が changes の行を写す）
TESTS_FILE = "fix-lane-{n}-tests.json"       # 枝の確かめが試験を選んで回す輪の状態の写し（実行器は単位の worktree の物）
KEPT_FILE = "fix-lane-{n}-{j}.patch"         # 諦めた項目の差分（修正役が読む前の試み）
LANE_PATCH = "fix-lane-{n}.patch"            # 締めが当てた・当てられなかった枝の差分
PLACE = "fix-lanes"   # run ごとの置き場の今の scope の下（単位の worktree item-<n>・枝の試験の置き場 lane-<n>・審査の差分）
PLANTED_OP, SETTLED_OP = "fix_lanes_planted", "fix_lanes_settled"   # 盤面の trace の行（canary_check・報告が読む）
ACCEPTED, GAVE_UP, NOT_RUN = "accepted", "gave_up", "not_run"       # 枝の控えの項目の結末
MERGED, BACK = lanekit.MERGED, lanekit.BACK                         # 締めた後の項目の結末
# 枝の確かめの id → 拒否の見出しの短い名（受け付けの scripts/accept.py の CHECKS の部分集合と、枝だけの units）
CHECKS = {
    "shape": "返答の形",
    "consult": "範囲の相談の枠",
    "frozen": "TDD の輪で凍ったテストのファイル",
    "writes": "書き込みの出どころ",
    "conflict": "食い違いの申し出の形",
    "units": "この項目の直す義務の単位",
    "scope": "承認済みの修正案の範囲",
    "tests": "変更に当たる試験の赤",
}
REJECT_HEAD = "枝の確かめ（受け付けと同じ事実の確かめを単位の worktree に当てた）。見出しごとの行を全部直した返答を丸ごと出し直せ:"
OFF = "入力 fix_lanes が off"
CONSULTED = "範囲の相談の周（返答の consult に答えの節が答えた）。確かめは回さず、次の回の指示書が答えのファイルを名指す"
CONSULT_SPENT = ("範囲の相談の枠（この枝で {n} 回）を使い切った後の consult を受けない。consult の欄を外し、範囲の中で直すか、"
                 "変えずに食い違いの申し出（kind は scope_needed）で返せ")


class Broken(Exception):
    """枝の控え・目録が読めない・呼ぶ番でない（回す側の誤り。節は 2 で落ちる）"""


def lane_nodes() -> list:
    """枝の役の節の印の名の全部（fix-lane-1..MAX_LANES）"""
    return lanekit.node_names(LANE_NODE)


def _read(path) -> dict:
    try:
        doc = json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise Broken(f"修正役の並べの控えが読めない（{path}: {e}）") from None
    if not isinstance(doc, dict):
        raise Broken(f"修正役の並べの控えの形が違う（{path}）")
    return doc


def _write(path, doc) -> None:
    path = pathlib.Path(path)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(doc, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    os.replace(tmp, path)


# ---------------------------------------------------------------- 分け方（純粋）
def groups(rows) -> list:
    """[(項目, 単位の並び)] を単位を共にする項目どうしの組に（組の中と組の並びは rows の順。lanekit.groups）。返りは項目の番号の並びの並び"""
    return lanekit.groups(rows)


def assign(grps, lanes: int = MAX_LANES, per: int = MAX_ITEMS) -> tuple:
    """組を枝に配る: 組の順に、入る余地の在る枝のうち項目の一番少ない枝（同じなら番号の小さい枝）へ。per より大きい組と、どの枝にも
    入らない組は残り。返り (枝ごとの項目の並び（空の枝は除く。番号は 1 から詰まる）, 残りの項目)"""
    out, rest = [[] for _ in range(lanes)], []
    for g in grps:
        room = [i for i in range(lanes) if len(out[i]) + len(g) <= per]
        if not room:
            rest += g
            continue
        out[min(room, key=lambda i: (len(out[i]), i))] += g
    return [x for x in out if x], rest


# ---------------------------------------------------------------- 枝を切る（節 fix-fork）
def candidates(b, values: dict, green) -> tuple:
    """(枝で直してよい項目の行 [{item, units, brief, range}], 直す義務に揃えた値（fixrules.owed_values）)。行は修正案の項目の順"""
    values = fixrules.owed_values(b, values)
    owed = json.loads(values["open_units"])
    subs = fixrules.dispatched(owed, green)
    ranges = fixrules.item_ranges(b)
    out = []
    for r in planbrief.for_units(fixrules.briefs_or_halt(b), subs):
        units = [k for k in r.get("unit_keys") or [] if k in subs]
        if units and ranges.get(r["item"]) is not None:
            out.append({"item": r["item"], "units": units, "brief": r["file"], "range": ranges[r["item"]]})
    return out, values


def fork(board_dir, repo, values: dict, green=frozenset(), switch: str = "") -> dict:
    """節 fix-fork（頭の注記）。並べない時も trace に理由の 1 行（PLANTED_OP の lanes 0）。盤面が開けない・brief の控えが壊れている時は
    並べずに go: false（修正役の支度が今どおり止める）"""
    on = script_io.switch_on(switch, "fix_lanes")   # 知らない語は ValueError（節は 2）
    out = {**lanekit.fork_out([]), "why": ""}
    why, cands, lanes, rest = ("" if on else OFF), [], [], []
    try:
        b = entry.open_board(pathlib.Path(board_dir))
    except BoardGap as e:
        return {**out, "why": why or f"盤面が開けない（{' '.join(str(e).split())}）"}
    repo = pathlib.Path(repo)
    for name in (fixrules.LANES_RECORD, fixrules.LANES_SUMMARY):   # 前に切った枝の締めの結末は、切り直す（か並べない）周に持ち込まない
        b.work(name).unlink(missing_ok=True)
    if why:
        pass
    elif not writes.sink(repo).is_file():
        why = "書き込みの記録が無い run（包みの無い起動。旗 lane の役を単位の worktree で起こせない）"
    else:
        try:
            cands, values = candidates(b, values, green)
        except BoardGap as e:
            return {**out, "why": f"直す義務か brief が引けない（{' '.join(str(e).split())}）"}
        lanes, rest = assign(groups([(c["item"], c["units"]) for c in cands]))
        if len(lanes) < 2:
            why = f"並べる枝が 2 本に満たない（範囲の在る項目 {len(cands)}・枝 {len(lanes)}）"
    if why:
        b.trace(PLANTED_OP, node="fix-fork", lanes=0, why=why)
        return {**out, "why": why}
    try:
        rows = _plant(b, repo, values, cands, lanes, rest)
    except Exception as e:   # 枝を切れない・項目のファイルを組めない: 並べずに修正の輪へ（切った worktree は片付ける）
        why = f"枝を切れない（{type(e).__name__}: {' '.join(str(e).split())[:300]}）——修正の輪が順に直す"
        try:
            unittrees.sweep(repo)
        except (unittrees.UnitTreeError, OSError):
            pass
        b.trace(PLANTED_OP, node="fix-fork", lanes=0, why=why)
        return {**out, "why": why}
    b.trace(PLANTED_OP, node="fix-fork", lanes=len(rows), items={str(r["n"]): r["items"] for r in rows}, rest=rest,
            expect=_expect(cands, lanes))
    return {**lanekit.fork_out([r["n"] for r in rows]), "why": ""}


def _expect(cands, lanes) -> list:
    """範囲が重なりうる枝の組 [[n, m]]（unitlanes.expect。測りに出す）"""
    by = {c["item"]: c["range"] for c in cands}
    return unitlanes.expect([(n, sorted({g for i in items for g in by[i]})) for n, items in enumerate(lanes, 1)])


def _plant(b, repo: pathlib.Path, values: dict, cands, lanes, rest) -> list:
    """単位の worktree を切り、枝の控え・項目の決まりのファイル・審査役のファイル・範囲の相談の控え・試験の状態の写しと目録を書く"""
    place = script_io.scope_dir(pathlib.Path(adapter.run_place_of({"board": str(b.dir)}))) / PLACE
    ns = list(range(1, len(lanes) + 1))
    picked = [i for items in lanes for i in items]
    union = fixrules.test_files(b, picked)
    manifest = b.work(MANIFEST)
    trees = lanekit.plant(repo, ns, place, manifest, union)
    base = trees[ns[0]]["base"]
    by = {c["item"]: c for c in cands}
    seat.pinned()   # 写しの照合を、項目のファイルの書き込みとライブラリの文書の引き（lib_section）より前に
    docs = fixrules.lib_section(b, repo, values)
    lang = rolekit.lang_line(b.state.get("inputs"))
    tdd_state = values.get("tdd_state") or ""
    rows = []
    for n, items in zip(ns, lanes):
        tree = pathlib.Path(trees[n]["tree"])
        ask, ask_config = _ask(b, repo, values, n, tree, base)
        entries = [_item(b, repo, values, by[i], n, j, items[:j - 1], items[j:], tree, base, docs, lang, ask, place)
                   for j, i in enumerate(items, 1)]
        tests = _tests_state(b, repo, tdd_state, n, tree, place)
        state = b.work(LANE_STATE.format(n=n))
        _write(state, {"n": n, "tree": str(tree), "git": trees[n]["git"], "base": base,
                       "head": tddloop.snapshot(tree), "items": entries, "cur": 0, "tries": 0, "iterations": 0, "reason": "",
                       "done": False, "note": "", "results": [], "claims": [], "declared": [], "tests": tests, "ask": bool(ask),
                       "ask_config": ask_config})
        rows.append({"n": n, "tree": str(tree), "git": trees[n]["git"], "state": str(state), "items": list(items)})
    _write(manifest, {"repo": str(repo), "base": base, "place": str(place), "union": union, "expect": _expect(cands, lanes),
                      "lanes": rows, "rest": rest})
    return rows


def _ask(b, repo, values: dict, n: int, tree: pathlib.Path, base: str) -> tuple:
    """(枝 n の範囲の相談と事前の確かめの節（fixrules.ask_text）, 控えのパス)。控えは run ごとの置き場の今の scope の相談の置き場の
    lane-<n>/ に書き、repo は単位の worktree・log_repo は run の作業ツリー・since は枝の base（factchecks.precheck が枝の確かめと同じに
    照らす。項目が進めば支度が今の項目の頭に書き直す。_sync_since）。相談の相手（plan_session）か承認済みの修正案の項目が無い run は
    ("", "")"""
    if not (values.get("plan_session") or "").strip():
        return "", ""
    try:
        items = planmarks.approved_items(b)
    except (planmarks.FieldsBroken, BoardGap, OSError, ValueError):
        items = None
    if not items:
        return "", ""
    doc = {"board": str(b.dir), "repo": str(tree), "log_repo": str(repo), "since": base, "scope": entry.peek_here(),
           "pass": PASS.format(n=n), "base_rev": values.get("base_rev") or "", "tdd_state": values.get("tdd_state") or "",
           "items": consult.items_doc(items)}
    path = consult.write_config(consult.place_of(b.dir) / f"lane-{n}", doc)
    ripple = (values.get("ripple_file") or "").strip()
    return fixrules.ask_text(path, sys.executable) + (f"\n\n{fixrules.RIPPLE_LINE.format(path=ripple)}" if ripple else ""), str(path)


LANE_TITLE = promptsection.Section("# 修正役の並べの枝 {n} の {j} 番目の項目（修正案の項目 {item}）", source="fn:fixlanes._item")


def _item(b, repo, values, c, n, j, earlier, later, tree, base, docs, lang, ask, place) -> dict:
    """枝 n の j 番目の項目の決まりのファイルと審査役のファイルを書き、枝の控えの項目の行を返す。earlier・later は同じ枝の前・後の項目
    （審査の差分は枝の base からなので、前の項目の直しも入ると決まりと審査のファイルに書く）"""
    units, item = c["units"], c["item"]
    vals = {**values, "open_units": json.dumps(units, ensure_ascii=False)}
    head = planbrief.head_text(planbrief.for_units(fixrules.briefs_or_halt(b), units), units)
    seat_text = seat.section("fix", fixrules.implementer_values(b, vals, tree, units, BRIEFS_FILE.format(n=n, j=j)))
    patch = str(place / f"lane-{n}-{j}.patch")
    review = b.work(REVIEW_FILE.format(n=n, j=j))
    review.write_text(fixrules.review_text(c["brief"], values, base, patch, str(tree), earlier), encoding="utf-8")
    lane = fixrules.lane_text({"item": str(item), "units": "・".join(units), "tree": str(tree), "run_tree": str(repo),
                               "diff_cmd": seat.g1_diff_cmd(base, patch, str(tree)), "review_file": str(review),
                               "give_up": str(GIVE_UP_AFTER)}, later, earlier)
    title = LANE_TITLE.format(n=n, j=j, item=item)
    text = fixrules.render("fix", 1, fixrules.fix_parts(vals, fixrules.kinds_now(vals, repo), docs, seat_text, "", ask, "", lane),
                           before=[title, head] if head else [title], lang=lang)["text"]
    rules = b.work(RULES_FILE.format(n=n, j=j))
    rules.write_text(text, encoding="utf-8")
    return {"item": item, "units": list(units), "brief": c["brief"], "rules": str(rules), "review": str(review), "patch": patch}


def _tests_state(b, repo: pathlib.Path, tdd_state: str, n: int, tree: pathlib.Path, place: pathlib.Path) -> str:
    """枝の確かめが試験を選んで回す輪の状態の写し（盤面の作業ファイル TESTS_FILE）。実行器が run の作業ツリーの中なら単位の worktree
    の同じ物、置き場は run ごとの置き場の lane-<n>/。輪の状態が無い（実行器の無い run）なら空"""
    if not tdd_state or not pathlib.Path(tdd_state).is_file():
        return ""
    st = tddloop.load_state(tdd_state)
    exe = lanekit.relocate(st["exe"], repo, tree)
    work = place / f"lane-{n}" / "suite"   # 版の写しの結末の控え（work の親）も枝ごと（同時に走る枝が同じ控えを書かない）
    work.mkdir(parents=True, exist_ok=True)
    path = b.work(TESTS_FILE.format(n=n))
    _write(path, {**st, "exe": str(exe), "work": str(work), "suite_made": [], "final_left": [], "final_far": [], "ci_left": []})
    return str(path)


# ---------------------------------------------------------------- 枝の輪の中（節 fix-lane-prep-<n>・fix-lane-step-<n>）
def _state(b, n) -> tuple:
    path = b.work(LANE_STATE.format(n=n))
    return path, _read(path)


def lane_prep(board_dir, n) -> dict:
    """節 fix-lane-prep-<n>（頭の注記）"""
    b = entry.open_board(pathlib.Path(board_dir))
    _, lst = _state(b, n)
    if lst["done"]:   # 済んだ枝（締めが止めた枝を含む）を Archon の resume が回し直した: 役を起こさない（YAML の役の when: が go を読む）
        return {"prompt_file": "", "go": False}
    why = lanekit.tree_ok(lst)
    if why:
        raise Broken(why)
    it = lst["items"][lst["cur"]]
    _sync_since(lst)
    pass_ = PASS.format(n=n)
    got = consult.take(b, pass_)
    if got is not None:   # 範囲の相談の答えの後の回: 同じ会話の続きに答えのファイルを名指すだけ
        prompt = fixrules.resume(b, pathlib.Path(it["rules"]), got, pass_)
    else:
        prompt = b.work(NEXT_FILE.format(n=n))
        prompt.write_text(_next_text(lst, it), encoding="utf-8")
    lanekit.mark(b.dir, LANE_NODE.format(n=n), f"{entry.peek_here() or '-'}:r{b.round}:lane-{n}:item-{it['item']}", lst["tree"])
    return {"prompt_file": str(prompt), "go": True}


def _sync_since(lst: dict) -> None:
    """範囲の相談の控え（事前の確かめが読む）の since を今の項目の頭（lst の head）に揃える（項目が進んだ後と、resume で支度が回し
    直された時。同じなら書かない）。控えが無い run は何もしない"""
    path = lst.get("ask_config") or ""
    if not path:
        return
    try:
        doc = json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise Broken(f"枝 {lst['n']} の範囲の相談の控えが読めない（{path}: {e}）") from None
    if isinstance(doc, dict) and doc.get("since") != lst["head"]:
        _write(path, {**doc, "since": lst["head"]})


NEXT_REJECT_HEAD = promptsection.Section("## 前の回の返答を機械が拒んだ理由（直して、返答を丸ごと出し直せ）", source="fn:fixlanes._next_text")
READ_HEAD = promptsection.Section("## 読む物", source="fn:fixlanes._next_text")
STEP_TITLE = promptsection.Section("# 修正役の並べの枝 {n} の {j} 番目の項目（修正案の項目 {item}・この項目の {tries} 回目）",
                                   source="fn:fixlanes._next_text")


def _next_text(lst: dict, it: dict) -> str:
    """回ごとの指示書（前の回を拒んだ理由と、項目の決まりのファイルの名指し）"""
    j = lst["cur"] + 1
    first = not lst["tries"] and not lst["reason"]
    lines = [STEP_TITLE.format(n=lst['n'], j=j, item=it['item'], tries=lst['tries'] + 1), ""]
    if lst["reason"]:
        lines += [NEXT_REJECT_HEAD, "", lst["reason"].rstrip("\n"), ""]
    lines += [READ_HEAD, "",
              f"- この項目の決まり: {it['rules']}——" + ("この項目の最初の回。Read で全部読み、その指示に従え" if first else
                                                     "この項目の間は同じ中身（この会話で読んでいなければ Read で全部読め）"),
              "", "返すのは決まりの「返答の欄」の形の JSON だけ。"]
    return "\n".join(lines) + "\n"


def lane_step(board_dir, n, reply, repo, *, consulted: bool = False, base_rev: str = "", tdd_state: str = "",
              try_query=None) -> dict:
    """節 fix-lane-step-<n>（頭の注記）"""
    b = entry.open_board(pathlib.Path(board_dir))
    path, lst = _state(b, n)
    if lst["done"] and reply is None:   # 支度が go: false を返して役が飛ばされた周（resume）: 何も動かさずに輪を抜ける
        return {"ok": True, "done": True, "consulted": False, "reason": "", "item": lst["items"][-1]["item"] if lst["items"] else 0}
    if lst["done"]:
        raise Broken(f"枝 {n} の項目は全部済んでいる（fix-lane-step を呼ぶ番でない）")
    it = lst["items"][lst["cur"]]
    tree = pathlib.Path(lst["tree"])
    lst["iterations"] += 1
    why = lanekit.tree_ok(lst)
    if why:   # 枝を済みにして抜ける（輪を落とさない。締めが枝の項目を順に戻す）
        _stop(lst, None, why)
        _write(path, lst)
        return {"ok": False, "done": True, "consulted": False, "reason": why, "item": it["item"]}
    if consulted:
        out = {"ok": False, "consulted": True, "reason": CONSULTED}
    else:
        over = []
        found, clean, claims = check(b, lst, it, reply, pathlib.Path(repo), base_rev, tdd_state, try_query, overflow=over)
        if found:
            lst["tries"] += 1
            lst["reason"] = render_rejects(found)
            out = {"ok": False, "consulted": False, "reason": lst["reason"]}
            if lst["tries"] >= GIVE_UP_AFTER:
                _give_up(b, lst, tree, f"同じ項目の {GIVE_UP_AFTER} 回目の拒否: " + " / ".join(t for _, t in found)[:600])
        else:
            _accept(b, lst, tree, reply, clean, claims, over)
            out = {"ok": True, "consulted": False, "reason": ""}
    if not lst["done"] and lst["iterations"] >= MAX_ITERATIONS:   # 回数の上限で輪を落とさない（R50）
        _stop(lst, tree, f"枝の輪の回数の上限（{MAX_ITERATIONS} 回）に届いた", b)
    _write(path, lst)
    return {**out, "done": lst["done"], "item": it["item"]}


def note(found: list, check_id: str, texts) -> None:
    """found に (確かめの id, 文) を足す（表 CHECKS に無い id は ValueError。空の文は足さない）"""
    if check_id not in CHECKS:
        raise ValueError(f"枝の確かめの表 CHECKS に無い id: {check_id!r}")
    for t in [texts] if isinstance(texts, str) else texts:
        if t and t.strip():
            found.append((check_id, t))


CHECK_HEAD = promptsection.Section("## {head}（確かめ {cid}・{count} 件）", source="fn:fixlanes.render_rejects")


def render_rejects(found: list) -> str:
    """拒否の本文（REJECT_HEAD の後に、表 CHECKS の順に見出しと行）"""
    lines = [REJECT_HEAD]
    for cid, head in CHECKS.items():
        texts = list(dict.fromkeys(t for c, t in found if c == cid))
        if texts:
            lines.append(CHECK_HEAD.format(head=head, cid=cid, count=len(texts)))
            lines += ["  - " + t.replace("\n", "\n    ") for t in texts]
    return "\n".join(lines)


def _made(lst: dict) -> list:
    """枝の実行器が単位の worktree に作ったファイル（試験の状態の写しの suite_made）"""
    try:
        return list(_read(lst["tests"]).get("suite_made") or []) if lst.get("tests") else []
    except Broken:
        return []


def check(b, lst: dict, it: dict, reply, repo: pathlib.Path, base_rev: str, tdd_state: str, try_query=None, overflow=None) -> tuple:
    """枝の確かめ（受け付けの -4〜1d と 1c を単位の worktree に当てる。事後の関門の束と写しの型の照らしは修正役の輪の受け付けが、全部の
    項目を合わせた作業ツリーで回す）。返り (拒否の行 [(id, 文)], bash_writes・consult・conflicts を外した返答, 通った申し出)。
    はみ出しの行のうち案の外のテストと凍ったファイルの関数の中の書き換えは枝の拒否に積まず、overflow（list を渡せば）に足す——枝は
    案の外のテストで項目を諦めず、本線の修正の輪の受け付けが合わせた作業ツリーで相談に回す。範囲の外のファイルは枝の役が範囲の
    相談の節で頼めるので、今どおり拒む"""
    found = []
    if not isinstance(reply, dict):
        note(found, "shape", "返答が JSON のオブジェクトでない（決まりの「返答の欄」の形で返せ）")
        return found, {}, []
    reply = dict(reply)
    if conflict.CONSULT_FIELD in reply:   # 相談の周でないのに consult を持つのは枠を使い切った後の頼み（consult.ask の spent）
        note(found, "consult", CONSULT_SPENT.format(n=consult.BUDGET))
        reply.pop(conflict.CONSULT_FIELD)
    # 書き込みの出どころと範囲は今の項目の頭から（同じ枝の前の項目が変えたファイルは、その項目の確かめが見た。run 97fd532f）
    tree, since, made, units = pathlib.Path(lst["tree"]), lst.get("head") or lst["base"], _made(lst), list(it["units"])
    asks = []
    frozen = factchecks.check_frozen(b.dir, tdd_state, tree, "first", asks=asks, base_rev=base_rev)
    frozen, over_frozen = factchecks.split_overflow(frozen, asks)
    note(found, "frozen", frozen)
    wrote = factchecks.check_writes(reply, b.dir, base_rev, tree, tdd_state, log_repo=repo, since=since, made=made)
    note(found, "writes", wrote["problems"])
    reply = wrote["reply"]
    items = reply.pop("conflicts", None) or []
    if items:
        note(found, "conflict", lanekit.claim_problems(items, tree, b.dir, units, try_query, planbrief.by_unit_at(b.dir)))
    keys = [c.get("unit_key") if isinstance(c, dict) else None for c in reply.get("changes") or []]
    rest = [r.get("unit_key") if isinstance(r, dict) else None for r in reply.get("not_done") or []]
    claimed = [i.get("unit_key") for i in items if isinstance(i, dict)] if isinstance(items, list) else []
    dup = [k for k in dict.fromkeys(keys) if keys.count(k) > 1]
    note(found, "units", [f"同じ unit_key を changes の 2 行以上に書いた: {k}" for k in dup])
    note(found, "units", [f"この項目の直す義務の単位でない unit_key: {k!r}（直す義務の単位は {units}）"
                          for k in dict.fromkeys(keys + rest + claimed) if k not in units])
    note(found, "units", [f"直す義務の単位 {k} が changes にも not_done にも食い違いの申し出にも無い"
                          for k in units if k not in keys + rest + claimed])
    note(found, "units", [f"申し出た単位を changes か not_done にも書いた: {k}（申し出た単位は直さない）"
                          for k in dict.fromkeys(claimed) if k in keys + rest])
    scope, scope_note = factchecks.check_plan_scope(reply, keys, b.dir, base_rev, tree, tdd_state, "first", ask=bool(lst.get("ask")),
                                                    since=since, made=made)
    # 枝が拒まずに残すのは案の外のテスト（new_tests）だけ。範囲の外のファイルは枝の役が範囲の相談の節で頼める（fix-lane-consult）ので今どおり拒む
    scope, over_scope = factchecks.split_overflow(scope, [o for o in (scope_note or {}).get("overflow") or [] if o.get("new_tests")])
    note(found, "scope", scope)
    if overflow is not None:
        overflow += [{k: v for k, v in o.items() if k != "ref"} for o in [*over_scope, *over_frozen]]
    if lst.get("tests"):
        # 版は枝の base（切った時の run の作業ツリー）: 枝の差分に当たる試験だけを選び、枝の base で既に赤い試験を新しい赤に数えない。
        # 項目の頭でなく枝の base なのは、同じ枝の前の項目の直しに当たる試験も回すため（後の項目が前の項目の試験を赤にすれば拒む）
        red, _ = tddloop.selected_problems(lst["tests"], tree, lst["base"])
        note(found, "tests", red)
    return found, reply, (items if not found else [])


def _next(lst: dict, tree: pathlib.Path) -> None:
    """次の項目へ（項目の頭の木を取り直す）。項目が尽きれば済み"""
    lst.update(cur=lst["cur"] + 1, tries=0, reason="")
    if lst["cur"] >= len(lst["items"]):
        lst["done"] = True
    else:
        lst["head"] = tddloop.snapshot(tree)


def _accept(b, lst: dict, tree: pathlib.Path, reply: dict, clean: dict, claims: list, overflow=()) -> None:
    """通った返答を控え（REPLY_FILE。consult を外した役の返答そのもの）、項目の結末（overflow に、枝の確かめが拒まずに残したはみ出し）を
    積んで次の項目へ"""
    j = lst["cur"] + 1
    it = lst["items"][lst["cur"]]
    out = b.work(REPLY_FILE.format(n=lst["n"], j=j))
    _write(out, {k: v for k, v in reply.items() if k != conflict.CONSULT_FIELD})
    items = reply.get(writes.FIELD)
    if isinstance(items, list) and not writes.shape_problems(items):
        lst["declared"] = [*lst.get("declared", []), *items]
    lst["claims"] = [*lst.get("claims", []), *claims]
    lst["results"].append({
        "item": it["item"], "outcome": ACCEPTED, "reply": str(out), "tries": lst["tries"] + 1,
        "changed": [c["unit_key"] for c in clean.get("changes") or [] if isinstance(c, dict)],
        "not_done": [r["unit_key"] for r in clean.get("not_done") or [] if isinstance(r, dict)],
        "claimed": [c["unit_key"] for c in claims],
        "files": sorted(factchecks.declared_files(clean.get("changes") or [], tree)), "overflow": list(overflow)})
    _next(lst, tree)


def _give_up(b, lst: dict, tree: pathlib.Path, why: str) -> None:
    """今の項目を諦める: 項目の頭からの差分を盤面に控え（KEPT_FILE）、木を項目の頭に戻して次の項目へ"""
    j = lst["cur"] + 1
    it = lst["items"][lst["cur"]]
    kept = b.work(KEPT_FILE.format(n=lst["n"], j=j))
    try:
        kept.write_text(unittrees.diff(tree, lst["head"]), encoding="utf-8", errors="surrogateescape")
        patch = str(kept)
    except unittrees.UnitTreeError:
        patch = ""
    tddloop.restore(tree, lst["head"])
    lst["results"].append({"item": it["item"], "outcome": GAVE_UP, "why": why, "patch": patch, "tries": lst["tries"]})
    _next(lst, tree)


def _stop(lst: dict, tree, why: str, b=None) -> None:
    """枝を済みにする: 今の項目は、書きかけが在れば（tree と b が在る時）差分を控えて頭に戻して諦め、残りの項目は回さなかった
    （NOT_RUN）"""
    if tree is not None and b is not None and lst["cur"] < len(lst["items"]) \
            and tddloop.touched(tree, lst["head"], tddloop.snapshot(tree)):
        _give_up(b, lst, tree, why)
    for it in lst["items"][lst["cur"]:]:
        lst["results"].append({"item": it["item"], "outcome": NOT_RUN, "why": why})
    lst.update(cur=len(lst["items"]), done=True, note=why)


# ---------------------------------------------------------------- 締める（節 fix-join）
def join(board_dir, repo, try_query=None) -> dict:
    """節 fix-join（頭の注記）"""
    b = entry.open_board(pathlib.Path(board_dir))
    man = _read(b.work(MANIFEST))
    repo = pathlib.Path(repo)
    done = fixrules.lanes_record(b)
    if done is not None and isinstance(done.get(JOINED), dict):   # 締めが済んだ後に Archon の resume が締めを回し直した: 当てた差分と
        lanekit.remove(repo, [row["tree"] for row in man["lanes"]])   # 後の修正の輪の直しを戻さず、前の出口をそのまま返す（残った
        return dict(done[JOINED])                                     # worktree だけ片付ける）
    log = writes.sink(repo)
    base = man["base"]
    stray = lanekit.revert_strays(repo, base)   # 枝の役は run の作業ツリーを書けない（包みの柵）。書かれていれば戻す（受け止め）
    results, ready, back = {}, [], {}
    for row in man["lanes"]:
        n = row["n"]
        try:
            lst = _read(row["state"])
        except Broken as e:
            for i in row["items"]:
                back[i] = {"why": f"枝の控えが読めない（{e}）", "lane": n}
            continue
        tree = pathlib.Path(lst["tree"])
        broken = lanekit.tree_ok(lst)
        if not lst["done"] and not broken:   # 枝の輪が最後まで回らなかった（落ちた）: 書きかけを当てない
            _stop(lst, tree, "枝の輪が項目を最後まで回さなかった（落ちたか止まった）", b)
            _write(row["state"], lst)
        for r in lst["results"]:
            results[r["item"]] = {**r, "lane": n}
        acc = [r for r in lst["results"] if r["outcome"] == ACCEPTED]
        if broken:
            for i in row["items"]:
                back[i] = {"why": broken, "lane": n}
        elif acc:
            ready.append((row, lst, acc))

    def merge_one(lane, earlier):
        row, lst, _ = lane
        try:
            return lanekit.merge(repo, lst["tree"], since=lst["base"], base=man["base"], log=log, declared=lst.get("declared") or [],
                                 made=_made(lst), kept=b.work(LANE_PATCH.format(n=row["n"])), union=man.get("union") or (),
                                 earlier=earlier)
        except (unittrees.UnitTreeError, OSError) as e:   # git が効かない枝は戻す（締めを落とさない）
            return lanekit.Merge(f"枝の差分を作れない・当てられない（{' '.join(str(e).split())[:300]}）", "", [], [], False)
    applied, union_got, patched = [], [], {}
    for (row, lst, acc), got in lanekit.merge_in_order(ready, merge_one):
        if got.why:
            for r in acc:
                back[r["item"]] = {"why": got.why, "patch": got.patch, "lane": row["n"]}
            continue
        union_got += [p for p in got.unioned if p not in union_got]
        applied.append((lst["tree"], got.patch))
        patched[row["n"]] = list(got.names)
    shared = lanekit.shared([patch for _, patch in applied])
    lanekit.carry(log, repo, applied, shared)
    parked, refused = _park(b, repo, [lst for _, lst, acc in ready if not any(r["item"] in back for r in acc)], try_query)
    items = _outcomes(man, results, back, refused, patched)
    merged = [i["item"] for i in items if i["outcome"] == MERGED]
    backs = [i["item"] for i in items if i["outcome"] == BACK]
    out = {"ok": True, "merged": merged, "back": backs, "parked": len(parked), "shared": shared, "union": union_got}
    doc = {"lanes": len(man["lanes"]), "base": base, "shared": shared, "union": union_got, "reverted": stray,
           "parked": [c["unit_key"] for c in parked], "rest": man.get("rest") or [], "items": items, JOINED: out}
    b.work(fixrules.LANES_SUMMARY).write_text(summary_text(doc), encoding="utf-8")
    _write(b.work(fixrules.LANES_RECORD), doc)   # 結末は最後に（在れば締めた印。resume の締めはこれを返す）
    b.trace(SETTLED_OP, node="fix-join", lanes=len(man["lanes"]), merged=merged, back=backs, parked=doc["parked"],
            shared=shared, union=union_got, reverted=stray,
            outcomes=[{k: i.get(k) for k in ("item", "lane", "outcome", "why")} for i in items])
    left = lanekit.remove(repo, [row["tree"] for row in man["lanes"]])
    if left:
        b.trace(SETTLED_OP + "_left", node="fix-join", trees=left)
    return dict(out)


def _park(b, repo, lanes, try_query) -> tuple:
    """当てた枝の食い違いの申し出を、当てた後の run の作業ツリーで確かめ直し、通った物を盤面に積む（conflict.park。source fix。
    裁定の輪が読む）。返り (積んだ申し出, 通らなかった申し出 {単位: 理由})"""
    claims = [c for lst in lanes for c in lst.get("claims") or []]
    if not claims:
        return [], {}
    owed = conflict.owed_units_but_asked(b)
    briefs = planbrief.by_unit_at(b.dir)
    good, refused = [], {}
    for c in claims:
        probs = lanekit.claim_problems(c, repo, b.dir, owed, try_query, briefs)
        if probs:
            refused[c["unit_key"]] = probs[0][:300]
        else:
            good.append(c)
    lanekit.park(b, good, "fix")
    return good, refused


def _outcomes(man: dict, results: dict, back: dict, refused: dict, patched=None) -> list:
    """目録の順に項目ごとの結末 [{item, lane, outcome, units, changed, not_done, claimed, files, patched, reply, why, patch, refused}]。
    patched は当てた枝の差分のパス（同じ枝の項目は同じ並び）"""
    patched = patched or {}
    out = []
    for row in man["lanes"]:
        for i in row["items"]:
            r = results.get(i) or {"outcome": NOT_RUN, "why": "枝の控えに結末が無い"}
            row_out = {"item": i, "lane": row["n"], "units": [], "changed": [], "not_done": [], "claimed": [], "files": [],
                       "patched": [], "reply": "", "why": "", "patch": "", "refused": {}}
            if r.get("outcome") == ACCEPTED and i not in back:
                row_out.update(outcome=MERGED, changed=r.get("changed") or [], not_done=r.get("not_done") or [],
                               claimed=[k for k in r.get("claimed") or [] if k not in refused], files=r.get("files") or [],
                               patched=patched.get(row["n"], []),
                               reply=r.get("reply") or "",
                               refused={k: refused[k] for k in r.get("claimed") or [] if k in refused})
            else:
                got = back.get(i) or {}
                row_out.update(outcome=BACK, why=got.get("why") or r.get("why") or "", patch=got.get("patch") or r.get("patch") or "",
                               reply=r.get("reply") or "")
            out.append(row_out)
    return out


SUMMARY_TITLE = promptsection.Section("# 修正役の並べの枝の結末（機械が書いた。締めの節 fix-join）", source="fn:fixlanes.summary_text")
MERGED_HEAD = promptsection.Section("## 当てた項目（直しは run の作業ツリーに在る。changes に枝の返答の行を写す）", source="fn:fixlanes.summary_text")
BACK_HEAD = promptsection.Section("## 順に戻した項目（この周で直す。下請けの項目に載る）", source="fn:fixlanes.summary_text")

# 枝の役は自分の枝の指示書を、締めの後の修正役は結末の文を受ける。枝の役と範囲の相談の答えの節の役の名は lanekit から引き、
# 相談・brief・ライブラリの文書・工程の地図の節の行も、それぞれの持ち主の口で組む
RECEIVES = [
    *consult.receives(lanekit.node_names(ANSWER_NODE), lane_nodes()),
    *fixrules.receives(lane_nodes()),
    *planbrief.receives(lane_nodes()),
    *(promptsection.Receive(role, head) for role in lane_nodes()
      for head in (LANE_TITLE, NEXT_REJECT_HEAD, READ_HEAD, STEP_TITLE, CHECK_HEAD, seat.HEAD, seat.PROMPT_HEAD)),
    *(promptsection.Receive(role, head) for role in (recount.ROLE, recount.RULED_ROLE)
      for head in (SUMMARY_TITLE, MERGED_HEAD, BACK_HEAD)),
    # 修正の受け付け（scripts/accept.py）の拒否の理由のファイル。次の回の修正役の指示書がパスを名指す
    *(promptsection.Receive(role, CHECK_HEAD, "fixrules.last_reject") for role in (recount.ROLE, recount.RULED_ROLE)),
]


def summary_text(doc: dict) -> str:
    """修正役が読む結末の本文（fixrules.LANES_SUMMARY）"""
    lines = [SUMMARY_TITLE, ""]
    merged = [i for i in doc["items"] if i["outcome"] == MERGED]
    back = [i for i in doc["items"] if i["outcome"] == BACK]
    lines += [MERGED_HEAD, ""]
    for i in merged or []:
        lines.append(f"- 項目 {i['item']}（枝 {i['lane']}）: 直した単位 {'・'.join(i['changed']) or '（無し）'}。枝の返答 {i['reply']}"
                     f"・変えたファイル {'・'.join(i['files']) or '（無し）'}")
        if i["not_done"]:
            lines.append(f"  - 枝が直さなかった単位（not_done。直す義務のまま）: {'・'.join(i['not_done'])}")
        if i["claimed"]:
            lines.append(f"  - 止めた単位（食い違いの申し出。機械が盤面に積んだ）: {'・'.join(i['claimed'])}")
        for k, why in (i.get("refused") or {}).items():
            lines.append(f"  - 申し出が当てた後の作業ツリーで確かめを通らなかった単位（直す義務のまま）: {k}（{why}）")
    if not merged:
        lines.append("- 無い")
    lines += ["", BACK_HEAD, ""]
    for i in back or []:
        lines.append(f"- 項目 {i['item']}（枝 {i['lane']}）: {i['why'] or '理由の記録が無い'}"
                     + (f"。前の試みの差分（作業ツリーには当たっていない）: {i['patch']}" if i["patch"] else ""))
    if not back:
        lines.append("- 無い")
    if doc.get("rest"):
        lines += ["", f"枝に入らなかった範囲の在る項目（修正役が順に直す）: {'・'.join(str(x) for x in doc['rest'])}"]
    if doc.get("shared"):
        lines += ["", f"重なりのファイル（2 本以上の枝の差分を機械が 3 方向で合わせた）: {'・'.join(doc['shared'])}"]
    if doc.get("union"):
        lines += ["", f"試験のファイルの挿しを機械が枝の順に並べた（union）: {'・'.join(doc['union'])}"]
    if doc.get("reverted"):
        lines += ["", f"枝の間に run の作業ツリーで変わっていたので戻したファイル: {'・'.join(doc['reverted'])}"]
    return "\n".join(lines) + "\n"
