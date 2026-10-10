"""事後の関門の束（計画 220 Task 4。修正の受け付け fix-accept・fix-ruled-accept の最後の段）。

TDD の輪の中にだけ在った 2 つの関門を、base（修正前の版。writes.base_rev）から今の作業ツリーまでを相手にもう 1 度当てる。
輪で direct に回った単位・輪の後の修正役が通した物も、ここで同じ決まりで見る。
束が見つけた行は抜け（腕の中の流れが通したのに外側の関門で落ちた物）として帳面に積み、受け付けは行を全部並べて拒む。

関門（GATES）:
- red_green: 承認済みの修正案の欄（conflict.frozen_fields）の route が tdd の項目の受け入れのテスト tests[].id ごとに、今の木で
  一式を走らせて passed、base の木で failure（輪と同じ赤の判定 tddloop.red_check が返す事実の文: 言語に依らず、error・一式の結末に
  居ない・もう通る・飛ばされたを拒む。文は『base で 』を頭に付けて行の detail に並べる）。輪が赤を確かめた単位（盤面の根の
  輪の状態の units で、route が tdd・red が ok・赤の木 red_tree が在り、今の木のテストのファイルが輪が終わった時の hash（輪の
  状態の frozen）と同じ物）の名指しは、赤の判定を輪の記録した赤の木（仮の実装を含む）で走らせ直して見る（tddloop.red_rerun。
  並べの締めと同じ口。文は RED_TREE_HEAD を頭に付ける）。test の段は走る前の失敗を最小の仮の実装で直してよいので、base の木に
  テストのファイルだけを写すと組み立てで落ちる正しい赤を拒むため（持ち主の直す前の関所の答え (3) A）。その名指しも base の木では
  今どおり走らせ、passed（直す前から通る）の時だけ拒む（仮の実装の名目で既存の実装を壊して作った偽の赤を拒む。error・一式の
  結末に居ないは仮の実装が無いだけなので拒まない）。赤の木を読めない時は base の木で見る。欄の無い run は
  見ない。直す義務の単位（conflict.owed_units_but_asked）を 1 つも名指さない項目も見ない（最後の回に ask_human に止めて直しを
  戻した単位のテストを、通し直しで抜けに数えない。見なかった項目と単位は skipped に OUT_OF_DUTY で残す）。行には項目の単位
  （unit_keys）を載せ、拒否の文にも書く（最後の回の受け付けが行を unit_key で単位に結んで止められる）。base の木は一時の git worktree（--detach。フックは切る）に作り、今の木で
  base から変わったテストのファイル（tddloop.is_test_file: 名指しのパスか名の慣習）と名指しのファイルだけを写して走らせる。今の木で走らせて出来た
  ファイルは消す（書き込みの出どころの突き合わせに載せない）。base の木の結末は名指しごとの鍵（base の版・実行器・名指し・その
  テストのファイルと写す conftest.py の今の中身。_base_keys）で盤面の根の周の置き場の BASE_CACHE に残し、控えに無い名指しだけを
  base の木で走らせる（base は run の中で動かないので、受け付けの回・最後の回の通し直し・2 回目の修正の段をまたいで使い回す。
  決まりは変えない）。今の木の側は回ごとに走らせる（実行器の約束では名指しを足しても既定の一式も走る。名指しだけを走らせる口が
  実行器に出来れば、ここで now の一式を名指しだけに絞れる）。実行器（入力 tdd_suite）が無ければ帳面の skipped に NO_SUITE。
  実行器が走らない・base の木を作れない時も skipped に理由（拒まない。輪の実行器が走らない時と同じく、回す側の事情で
  受け付けの回数を使わない）
- test_edits: base から今の木で変わったテストのファイル（tddloop.is_test_file: 修正案の受け入れのテスト・書き換えの名指しのパスか名の慣習）のうち、base に在ったテストの関数
  （tddloop.test_functions）の源が変わった・消えた物（tddloop.unnamed_edits）。許すのはテストの変更の許し（conflict.test_permits）の
  行だけ: 承認済みの修正案の rewrite_tests の id（行の test）と、範囲の相談の合意・裁定 fix_test_scope の範囲（裁定は裁定の後の
  受け付けだけ）の中だけを変えた関数。ほかに、修正案の項目の removes（消す名）を base の本体で名指す関数も許す（_removes_ids。
  消す仕組みを縛るテストは変えざるを得ない。run 6a51125d）。案の直しの単位の行は見ない（前の輪が足したテストは base に無く、ここでは照らさない）。範囲の読みは輪の凍結の検査（tddloop.frozen_problems）と同じ: 1 行の指しの .py はその行を
  含む関数の全体に広げ、`<行>-<行>` は書いたとおり（base との差分の塊の旧い側の行が範囲の外なら、その塊に掛かる関数は
  許さない。tddloop.hunks_outside）。ファイルだけの範囲はそのファイルの全部

帳面（LEDGER。今の周の作業ファイル）: {"rows": [{pass, attempt, gate, id, detail, unit_keys}], "skipped": [{pass, attempt, why}]}。
受け付けの回の印は (pass, attempt)（裁定の後の輪は回を 1 から数え直す）。2 回目の修正の段（依頼 226。同じブロックの 2 度目の
include）の帳面と一式のログはその scope の周の置き場の物で、1 回目の段の物と分かれる。2 回目の修正の段（conflict.second_pass）の test_edits は、base からの
差分に 1 回目の段で裁定 fix_test_scope の範囲として直したテストが在るので、裁定の範囲をいつも許す（受け付けの凍結の検査の前の輪と同じ）。最後の回の通し直し（accept_fix が自分を呼び直す）で
束が同じ回に 2 度走っても、同じ行・同じ skipped は 1 度だけ積む（preflight F23）。積む物が無ければ書かない。
飛ばした理由は拒まない（受け付けの回数を使わない）が、見えなくしない: 受け付けが受けた時に unchecked(…)（skipped から
OUT_OF_DUTY を除いた物。義務の外の項目は確かめる物でなく、ほかの項目は確かめた）を盤面の trace の SKIPPED_OP の行に載せ、
報告（report.gates_lines）と最後の人の関所の文が「確かめずに通した」回を数える。OUT_OF_DUTY は帳面にだけ残る。
期限は持たない（実行器の枠と nice は tddloop.run_suite が付ける）。
"""
from __future__ import annotations

import contextlib
import hashlib
import json
import os
import pathlib
import posixpath
import shutil
import tempfile

import cite  # noqa: E402  （.shared/core。名指しの形）
import conflict  # noqa: E402  （.shared/core。修正案の欄の控え・直す義務・テストの変更の許し）
import entry  # noqa: E402  （.shared/core。盤面の入口）
import impact  # noqa: E402  （.shared/core。受け付けの盤面の trace の行の名）
import planmarks  # noqa: E402  （.shared/core。修正案の書き換えの名指し・テストの定義の行・案の項目の removes）
import planscope  # noqa: E402  （同じブロックの lib。removes の名の探す語の読み口をそのまま使う）
import tddloop  # noqa: E402  （同じブロックの lib。輪の関門の読み口をそのまま使う）
import writes  # noqa: E402  （.shared/core。修正前の版）
from leftovers import Unreadable, git  # noqa: E402

LEDGER = "fix-gates.json"
GATES = ("red_green", "test_edits")
NO_SUITE = "テストの実行器（入力 tdd_suite）が無い run——受け入れのテストの事後の赤緑は確かめない"
REJECT = "修正の後の木に、輪の中の関門が通さない物が在る（事後の関門の束）: "
REDO = ("——並べた行を全部直してから、返答を丸ごと出し直せ（受け入れのテストは base で failure の赤・今の木で緑。名指しの外の"
        "既存のテストの本体は変えない。案の前提が誤りなら conflicts で申し出よ）")
NO_RUN = "受け入れのテストの事後の赤緑を確かめられない"   # skipped の頭（実行器が走らない・base の木を作れない）
EDITED = "名指しの外の既存のテストの本体を変えた・消した（変えてよいのは修正案の rewrite_tests の名指しと裁定 fix_test_scope の範囲だけ）"
OUT_OF_DUTY = "直す義務の外の単位（止めた・答え待ち・人に回した）だけを名指す項目——受け入れのテストの事後の赤緑は確かめない"
SKIPPED_OP = impact.ACCEPT_GATES_SKIPPED_OP   # 受けた受け付けの回に飛ばした理由を載せる盤面の trace の行（報告が数える）
BASE_CACHE = "fixgates-base.json"   # base の木の結末の控え {鍵: JUnit の行か null}（_base_keys。周の置き場の根）
RUN = "gates"   # 一式のログ・JUnit の名（suite-gates-<回>-now.log・…-base.log・…-red-<n>.log）
RED_TREE_HEAD = "輪の赤の木で "   # 赤の木で走らせ直した名指しの行の detail の頭（base の木の行は『base で 』）


def problems(board_dir, repo, base_rev: str, suite: str, attempt: int, *, pass_: str = "first") -> list[dict]:
    """束の行 [{gate, id, detail, unit_keys（red_green は項目の単位・test_edits は空）}]（GATES の順）。行と飛ばした理由を
    帳面（LEDGER）に積む（飛ばした理由は skipped で読み直す）。盤面の欄の控えが凍結の印と食い違えば conflict.frozen_fields が
    盤面を止めて BoardGap（受け付けの入口が 2 にする）"""
    b = entry.open_board(board_dir)
    repo = pathlib.Path(repo)
    rev = writes.base_rev(b, base_rev)
    fields = conflict.frozen_fields(b)   # 先に読む（食い違いは BoardGap。下の conflict.test_permits はもう投げない）
    tests, gaps = _accept_tests(b, fields)
    rows = []
    if tests and not suite:
        gaps.append(NO_SUITE)
    elif tests:
        got, why = _red_green(repo, rev, suite, tests, b.work(f"{RUN}-{pass_}-{attempt}"), _base_cache(b),
                              _red_units(b.dir, repo))
        rows += got
        gaps += why
    rows += _test_edits(b, repo, rev, pass_ == "ruled" or conflict.second_pass(b), [t["id"] for t in tests])
    _record(b, _mark(pass_, attempt), rows, gaps)
    return rows


def _base_cache(b) -> pathlib.Path:
    """base の木の結末の控え（盤面の根の今の周の置き場。scope に依らないので 1 回目と 2 回目の修正の段が同じ物を読む）"""
    p = pathlib.Path(b.dir) / f"r{b.round}" / BASE_CACHE
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def reject_lines(rows: list[dict]) -> list[str]:
    """行ごとの拒否の文『REJECT<gate> <id>: <detail>（項目の単位 …）』。最後の文の末に出し直しの頼み REDO。受け付けはこの並びを
    そのまま拒否に渡す（理由は " / " でつないだ 1 つの文で全部の行が並ぶ。最後の回は文ごとに単位に結んで止める）"""
    out = [f"{REJECT}{r['gate']} {r['id']}: {r['detail']}"
           + (f"（項目の単位 {'、'.join(r['unit_keys'])}）" if r.get("unit_keys") else "") for r in rows]
    if out:
        out[-1] += REDO
    return out


def reject_text(rows: list[dict]) -> str:
    """行を全部並べた 1 つの文（reject_lines を " / " でつないだ物。1 行ずつ直させて受け付けの回数を使い切らない）"""
    return " / ".join(reject_lines(rows))


def _mark(pass_: str, attempt: int) -> dict:
    """帳面の行の受け付けの回の印"""
    return {"pass": pass_, "attempt": attempt}


def skipped(board_dir, *, pass_: str, attempt: int) -> list[str]:
    """今の scope の帳面の、受け付けの回 (pass_, attempt) に飛ばした理由（帳面が無い・その回の行が無ければ空）"""
    path = entry.open_board(board_dir, allow_halted=True).work(LEDGER)
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return []
    want = _mark(pass_, attempt)
    return [r["why"] for r in doc.get("skipped") or [] if {k: v for k, v in r.items() if k != "why"} == want]


def unchecked(board_dir, *, pass_: str, attempt: int) -> list[str]:
    """受け付けの回 (pass_, attempt) に、確かめるはずの受け入れのテストの赤緑を確かめなかった理由（skipped から OUT_OF_DUTY を
    除いた物）。受け付けが受けた回の盤面の trace に載せる"""
    return unchecked_whys(skipped(board_dir, pass_=pass_, attempt=attempt))


def unchecked_whys(whys) -> list[str]:
    """飛ばした理由のうち、確かめるはずの赤緑を確かめなかった物（OUT_OF_DUTY を除く。義務の外の項目は確かめる物でない）。
    受け付けの trace（unchecked）と測る関数（dev/fixmeasure.py の red_green_checked）が同じ決まりで読む"""
    return [w for w in whys if isinstance(w, str) and not w.startswith(OUT_OF_DUTY)]


def _accept_tests(b, fields) -> tuple[list[dict], list[str]]:
    """(route が tdd の項目のうち直す義務の単位を名指す物（unit_keys の無い項目も）の受け入れのテスト [{id, unit_keys}]
    （項目の順・id の重複は最初の物。単位は名指した項目の全部）, 義務の外の項目を見なかった理由)"""
    owed = conflict.owed_units_but_asked(b) if fields else set()
    out, why = {}, []
    for n, f in enumerate(fields or [], 1):
        if not isinstance(f, dict) or f.get("route") != "tdd":
            continue
        keys = [k for k in f.get("unit_keys") or [] if isinstance(k, str)] if isinstance(f.get("unit_keys"), list) else []
        if keys and not set(keys) & owed:
            why.append(f"{OUT_OF_DUTY}: 修正案の項目 {n}（単位 {'、'.join(keys)}）")
            continue
        for t in f.get("tests") or []:
            if isinstance(t, dict) and isinstance(t.get("id"), str) and t["id"].strip():
                got = out.setdefault(t["id"], {"id": t["id"], "unit_keys": []})
                got["unit_keys"] += [k for k in keys if k not in got["unit_keys"]]
    return list(out.values()), why


def _test_files(repo, rev: str, tree: str, ids=()) -> list[str]:
    """base から木 tree で変わったテストのファイル（tddloop.is_test_file。宣言は名指し ids のパス）"""
    declared = {tddloop.id_path(i) for i in ids}
    return [f for f in tddloop.touched(repo, rev, tree) if tddloop.is_test_file(f, declared)]


def _red_units(board_dir, repo: pathlib.Path) -> dict:
    """名指しの id（tddloop._norm_id）→ 輪が赤を確かめた単位の記録（盤面の根の全部の輪の状態 tddloop.states。route が tdd・red が ok・
    諦めていない・赤の木 red_tree が在り、今の木のテストのファイルが輪が終わった時の hash（その輪の状態の frozen）と同じ単位。
    後の単位が同じファイルに足しただけなら赤の木を使う（赤の木の中のファイルが赤の記録と同じかは red_rerun が照らす）。同じ名指しは
    先の輪の物）。読めない輪の状態は飛ばす（その名指しは base の木で見る。緩めない側）"""
    out = {}
    for path in tddloop.states(board_dir):
        try:
            st = tddloop.load_state(path)
        except tddloop.Broken:
            continue
        frozen = st.get("frozen") or {}
        for u in (st.get("units") or {}).values():
            if not (isinstance(u, dict) and u.get("route") == "tdd" and u.get("red") == "ok" and not u.get("gave_up")
                    and u.get("red_tree") and u.get("test_files")):
                continue
            if any(f not in frozen for f in u["test_files"]) \
                    or tddloop.hashes(repo, u["test_files"]) != {f: frozen[f] for f in u["test_files"]}:
                continue   # 輪の後（やり直し・裁定）にテストのファイルが変わった: 赤の木は今のテストを表さない
            for t in u.get("tests") or []:
                out.setdefault(tddloop._norm_id(t), u)
    return out


def _red_green(repo: pathlib.Path, rev: str, suite: str, tests: list, work: pathlib.Path, cache: pathlib.Path,
               loop: dict | None = None) -> tuple[list, list]:
    """(行, 飛ばした理由)。今の木で一式（名指しを絶対パスの node id で後ろに足す）を 1 回走らせ、base の木の結末は控え（cache。
    _base_keys の鍵ごと）に無い名指しだけを base の木で走らせて控えに足し、比べる。loop（_red_units）に在る名指しは赤を輪の
    赤の木で走らせ直して見て（_red_tree_probs。結末は同じ控えに _red_key の鍵で残す）、base の木では passed の時だけ拒む。赤の判定は輪と同じ
    tddloop.red_check の事実の文（行の detail は『base で 』か RED_TREE_HEAD を頭に付けて並べる）"""
    work.mkdir(parents=True, exist_ok=True)
    ids = [t["id"] for t in tests]
    tree = tddloop.snapshot(repo)
    try:
        now, _, why = tddloop.run_suite(suite, repo, work, f"{RUN}-now", tddloop.abs_ids(repo, ids))
    finally:
        tddloop.restore_paths(repo, tree, tddloop.touched(repo, tree, tddloop.snapshot(repo)))   # 走らせて出来た物を消す
    if now is None:
        return [], [f"{NO_RUN}（今の木で実行器が走らない: {'; '.join(why)}）"]
    red, why = _red_tree_probs(repo, rev, suite, [i for i in ids if tddloop._norm_id(i) in (loop or {})], loop or {}, work, cache)
    if red is None:
        return [], [f"{NO_RUN}（輪の赤の木: {'; '.join(why)}）"]
    copy = sorted(set(_test_files(repo, rev, tree, ids)) | {tddloop.id_path(i) for i in ids})
    keys = _base_keys(repo, rev, suite, ids, copy)
    seen = tddloop.load_json(cache, {})
    need = [i for i in ids if keys[i] not in seen]
    rules = tddloop.rules()
    if need:
        base, why = _base_run(repo, rev, suite, need, copy, work)
        if base is None:
            return [], [f"{NO_RUN}（base の木: {'; '.join(why)}）"]
        seen = {**tddloop.load_json(cache, {}), **{keys[i]: rules.match_case(i, base) for i in need}}
        tddloop.save_json(cache, seen)
    rows = []
    for t in tests:
        c = rules.match_case(t["id"], now)
        if c is None or c["outcome"] != "passed":
            rows.append(_row("red_green", t["id"], f"今の木で {c['outcome'] if c else '一式の結末に居ない'}（受け入れのテストが緑でない）",
                             t["unit_keys"]))
        base = [seen[keys[t["id"]]]] if seen.get(keys[t["id"]]) else []   # base の木の結末のうちこのテストに当たる行（無ければ空）
        probs, _ = tddloop.red_check([t["id"]], base, None, None)
        if t["id"] in red:   # 赤は赤の木で見る。base の木では直す前から通る時だけ拒む
            if red[t["id"]]:
                rows.append(_row("red_green", t["id"], RED_TREE_HEAD + "；".join(red[t["id"]]), t["unit_keys"]))
            if base and base[0].get("outcome") == "passed":
                rows.append(_row("red_green", t["id"], "base で " + "；".join(probs), t["unit_keys"]))
            continue
        if probs:
            rows.append(_row("red_green", t["id"], "base で " + "；".join(probs), t["unit_keys"]))
    return rows, []


def _red_key(repo: pathlib.Path, suite: str, test_id: str, u: dict) -> str:
    """赤の木の結末の控えの鍵: 赤の木（中身を決める sha）・実行器・名指し・赤の記録のテストのファイルの中身。赤の木は run の中で
    動かないので、回・1 回目と 2 回目の修正の段をまたいで使い回せる"""
    raw = json.dumps(["red", u["red_tree"], tddloop.exe_id(repo, suite), test_id, sorted((u.get("test_hashes") or {}).items())],
                     ensure_ascii=False)
    return "red:" + hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _red_tree_probs(repo: pathlib.Path, rev: str, suite: str, ids: list, loop: dict, work: pathlib.Path,
                    cache: pathlib.Path) -> tuple:
    """(名指し → 赤の木での red_check の問題の文（空なら赤）か None, 実行器が走らない理由)。控えに無い名指しだけを、一時の
    worktree（base の版から作る。_temp_tree）で tddloop.red_rerun に回す（名指しは 1 本ずつ。その名指しだけの事実にする）。
    赤の木を読めない（オブジェクトが無い）名指しは返さない（呼び手が base の木で見る）"""
    seen = tddloop.load_json(cache, {})
    keys = {i: _red_key(repo, suite, i, loop[tddloop._norm_id(i)]) for i in ids}
    out = {i: seen[keys[i]] for i in ids if isinstance(seen.get(keys[i]), list)}
    need = [i for i in ids if i not in out]
    if not need:
        return out, []
    with _temp_tree(repo, rev) as (wt, why):
        if wt is None:
            return None, why
        exe = _inner_exe(repo, wt, suite)
        for n, i in enumerate(need, 1):
            u = {**loop[tddloop._norm_id(i)], "tests": [i]}
            try:
                probs, why = tddloop.red_rerun(wt, u, exe, work, f"{RUN}-red-{n}")
            except Unreadable:
                continue
            if probs is None:
                return None, why
            out[i] = probs
            seen = {**tddloop.load_json(cache, {}), keys[i]: probs}
            tddloop.save_json(cache, seen)
    return out, []


def _base_keys(repo: pathlib.Path, rev: str, suite: str, ids: list, copy: list) -> dict:
    """名指し → base の木の結末の控えの鍵。base の木は base の版に copy（今の木で base から変わったテストのファイルと名指しの
    ファイル）を写した物なので、1 件の結末を決めるのは base の版（commit の sha）・実行器（tddloop.exe_id）・名指し・そのテストの
    ファイルの今の中身・写す conftest.py の中身。ほかの写すテストのファイルは鍵に入れない（テストのファイルが別のテストの
    ファイルを import する形は見ない。入れると修正役がどれか 1 つのテストのファイルを触るたびに全部を走らせ直す）"""
    head = [tddloop.rev_id(repo, rev), tddloop.exe_id(repo, suite),
            sorted(tddloop.hashes(repo, [f for f in copy if posixpath.basename(f) == "conftest.py"]).items())]
    out = {}
    for i in ids:
        f = tddloop.id_path(i)
        raw = json.dumps([*head, i, tddloop.hashes(repo, [f])[f]], ensure_ascii=False)
        out[i] = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    return out


def _base_run(repo: pathlib.Path, rev: str, suite: str, ids: list, copy: list, work: pathlib.Path) -> tuple:
    """(base の木で走らせた結末か None, 問題)。一時の git worktree（--detach）に base を出し、copy のパスを今の木の姿に揃えて
    （今の木に無ければ消して）走らせる。実行器が repo の中に在れば worktree の中の同じ物を走らせる。worktree は成否に
    関わらず消す（作業ツリー・index・枝は動かさない）"""
    with _temp_tree(repo, rev) as (wt, why):
        if wt is None:
            return None, why
        for f in copy:
            src, dst = repo / f, wt / f
            if src.is_file():
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(src, dst)
            elif dst.is_file() or dst.is_symlink():
                dst.unlink()
        cases, _, why = tddloop.run_suite(_inner_exe(repo, wt, suite), wt, work, f"{RUN}-base", tddloop.abs_ids(wt, ids))
        return cases, why


def _inner_exe(repo: pathlib.Path, wt: pathlib.Path, suite: str) -> str:
    """実行器が repo の中に在れば worktree の中の同じ物（在れば）、ほかは suite のまま"""
    exe = pathlib.Path(suite)
    try:
        inner = wt / exe.absolute().relative_to(repo.absolute())
        return str(inner if inner.is_file() else exe)
    except ValueError:
        return suite


@contextlib.contextmanager
def _temp_tree(repo: pathlib.Path, rev: str):
    """(一時の git worktree（--detach。フックは切る）か None, 作れない理由)。成否に関わらず消す（作業ツリー・index・枝は動かさない）"""
    td = pathlib.Path(tempfile.mkdtemp(prefix="works-fixgates-"))
    wt = td / "base"
    try:
        try:
            git(repo, "-c", "core.hooksPath=/dev/null", "worktree", "add", "--detach", "--quiet", str(wt), rev)
        except Unreadable as e:
            yield None, [str(e)]
            return
        yield wt, []
    finally:   # この worktree だけを外す。外せなければ置き場を消して prune（git の控え .git/worktrees/ の行を残さない）
        try:
            git(repo, "worktree", "remove", "--force", str(wt))
        except Unreadable:
            shutil.rmtree(wt, ignore_errors=True)
            try:
                git(repo, "worktree", "prune")
            except Unreadable:
                pass
        shutil.rmtree(td, ignore_errors=True)


def _test_edits(b, repo: pathlib.Path, rev: str, ruled: bool, ids=()) -> list[dict]:
    """ids は修正案の受け入れのテストの名指し（そのパスもテストのファイルと見る。書き換えの名指しのパスも同じ）"""
    permits = conflict.test_permits(b, rulings=ruled)   # テストの変更の許しの唯一の元（keep-essence の 3）
    plan = [p["test"] for p in permits if isinstance(p.get("test"), str)]   # 修正案の名指しは id で許し、そのパスはテストのファイルの宣言
    files = _test_files(repo, rev, tddloop.snapshot(repo), [*ids, *plan])
    if not files:
        return []
    limits = [p["limit"] for p in permits if "limit" in p and "test" not in p]   # 合意と裁定の範囲（裁定は 1 回目は空）
    allowed = set(plan) | _ruled_ids(repo, rev, files, limits) | _removes_ids(b, repo, rev, files)
    return [_row("test_edits", i, EDITED) for i in tddloop.unnamed_edits(repo, rev, files, allowed)]


def _ruled_ids(repo, rev: str, files: list, limits: list) -> set:
    """裁定の範囲（`<パス>` か `<パス>:<行>[-<行>]`）の中だけを変えた、base のテストの関数の id。範囲の組み方は輪の凍結の検査
    （tddloop.frozen_problems）と同じ（1 行の指しだけが関数の幅に広がる）。ファイルだけの範囲はそのファイルの関数の全部。
    ほかは base との差分の塊のうち範囲の外の物（tddloop.hunks_outside の旧い側の行）に関数の幅（tddloop.function_span）が
    掛からない関数を許す。定義の行が引けない id（入れ子のクラスなど）・外の塊が読めないファイルは許さない（拒む側）"""
    scope = {}
    for lim in limits:
        got = conflict.parse_limit(lim)
        if not got or got[0] not in files:
            continue
        m = cite.CITE.match(lim.strip())
        scope.setdefault(got[0], []).append(got[1] and (*got[1], bool(m) and not m["b"]))
    out = set()
    for path, spans in scope.items():
        try:
            old = git(repo, "show", f"{rev}:{path}")
        except Unreadable:
            continue
        ids = tddloop.test_functions(old, path)
        if None in spans:
            out |= set(ids)
            continue
        bad = _old_spans(tddloop.hunks_outside(repo, rev, path, spans))
        if bad is None:
            continue
        lines = old.splitlines()
        for tid in ids:
            line = planmarks.line_in(old, tid)
            wide = tddloop.function_span(lines, line) if line else None
            if wide and not any(a <= wide[1] and wide[0] <= b for a, b in bad):
                out.add(tid)
    return out


def _removes_ids(b, repo, rev: str, files: list) -> set:
    """修正案の項目の removes（消す名）を base の本体で名指す、base のテストの関数の id（消す仕組みを縛るテストは変えざるを
    得ない。run 6a51125d）。名は案の照らしと同じ探す語（planscope._lookup）を語の境（planscope._word）で探す"""
    words = [planscope._word(n) for it in planmarks.plan_items(b) or [] if isinstance(it, dict)
             for n in map(planscope._lookup, it.get("removes") or []) if n]
    out = set()
    for path in files if words else []:
        try:
            old = git(repo, "show", f"{rev}:{path}")
        except Unreadable:
            continue
        out |= {i for i, body in tddloop.test_functions(old, path).items() if any(w.search(body) for w in words)}
    return out


def _old_spans(bad: list):
    """tddloop.hunks_outside の『a-b』『a』の並び → [(a, b)]。ほかの文（旧い姿が読めない）が在れば None"""
    out = []
    for text in bad:
        a, sep, b = text.partition("-")
        if not a.isdigit() or (sep and not b.isdigit()):
            return None
        out.append((int(a), int(b) if sep else int(a)))
    return out


def _row(gate: str, test_id: str, detail: str, keys=()) -> dict:
    return {"gate": gate, "id": test_id, "detail": detail, "unit_keys": list(keys)}


def _record(b, mark: dict, rows: list, skipped: list) -> None:
    """帳面に積む（同じ回の印・同じ中身の行と skipped は積み増さない）。積む物が無ければ書かない"""
    if not rows and not skipped:
        return
    path = b.work(LEDGER)
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        doc = {}
    doc = {"rows": list(doc.get("rows") or []), "skipped": list(doc.get("skipped") or [])}
    before = (len(doc["rows"]), len(doc["skipped"]))
    for r in rows:
        row = {**mark, **r}
        if row not in doc["rows"]:
            doc["rows"].append(row)
    for why in skipped:
        row = {**mark, "why": why}
        if row not in doc["skipped"]:
            doc["skipped"].append(row)
    if (len(doc["rows"]), len(doc["skipped"])) == before:
        return
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(doc, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    os.replace(tmp, path)
