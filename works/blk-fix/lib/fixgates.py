"""事後の関門の束（計画 220 Task 4。修正の受け付け fix-accept・fix-ruled-accept の最後の段）。

TDD の輪の中にだけ在った 2 つの関門を、修正の形（fixshape）に依らず、base（修正前の版。writes.base_rev）から今の作業ツリーまでを
相手にもう 1 度当てる。輪を飛ばす形（g1）・輪で direct に回った単位・輪の後の修正役が通した物も、ここで同じ決まりで見る。
束が見つけた行は抜け（腕の中の流れが通したのに外側の関門で落ちた物）として帳面に積み、受け付けは行を全部並べて拒む。

関門（GATES）:
- red_green: 承認済みの修正案の欄（conflict.frozen_fields）の route が tdd の項目の受け入れのテスト tests[].id ごとに、今の木で
  一式を走らせて passed、base の木で failure で、赤の種類が輪と同じ決まり（tddloop.kind_problems: 名前・import の失敗と、案が
  exception なのに断言の失敗を拒む。ほかの例外の型・unknown は通す。preflight F11）。平の run（fixshape.plain）・欄の無い run は
  見ない。直す義務の単位（conflict.owed_units_but_asked）を 1 つも名指さない項目も見ない（最後の回に ask_human に止めて直しを
  戻した単位のテストを、通し直しで抜けに数えない）。base の木は一時の git worktree（--detach。フックは切る）に作り、今の木で
  base から変わったテストのファイル（tddloop.TEST_FILE の名）と名指しのファイルだけを写して走らせる。今の木で走らせて出来た
  ファイルは消す（書き込みの出どころの突き合わせに載せない）。実行器（入力 tdd_suite）が無ければ帳面の skipped に NO_SUITE。
  実行器が走らない・base の木を作れない時も skipped に理由（拒まない。輪の実行器が走らない時と同じく、回す側の事情で
  受け付けの回数を使わない）
- test_edits: base から今の木で変わったテストのファイル（tddloop.TEST_FILE の名）のうち、base に在ったテストの関数
  （tddloop.test_functions）の源が変わった・消えた物（tddloop.unnamed_edits）。許すのは承認済みの修正案の rewrite_tests の id
  （planmarks.rewrites）と、裁定 fix_test_scope の範囲（裁定の後の受け付けだけ。conflict.ruled_test_limits から修正案の行を
  外した物）に掛かる関数（関数の幅は tddloop.function_span と同じ読み）。平の run は修正の段に修正案の欄を渡さないので、
  修正案の名指しを許しにしない（current の腕の比べの条件。preflight F15）

帳面（LEDGER。今の周の作業ファイル）: {"rows": [{pass, attempt, shape, gate, id, detail}], "skipped": [{pass, attempt, why}]}。
受け付けの回の印は (pass, attempt)（裁定の後の輪は回を 1 から数え直す）。最後の回の通し直し（accept_fix が自分を呼び直す）で
束が同じ回に 2 度走っても、同じ行・同じ skipped は 1 度だけ積む（preflight F23）。積む物が無ければ書かない。
期限は持たない（実行器の枠と nice は tddloop.run_suite が付ける）。
"""
from __future__ import annotations

import json
import os
import pathlib
import posixpath
import shutil
import tempfile

import conflict  # noqa: E402  （.shared/core。修正案の欄の控え・直す義務・テストの変更の許し）
import entry  # noqa: E402  （.shared/core。盤面の入口）
import fixshape  # noqa: E402  （.shared/core。盤面の修正の形）
import planmarks  # noqa: E402  （.shared/core。修正案の書き換えの名指し・テストの定義の行）
import tddloop  # noqa: E402  （同じブロックの lib。輪の関門の読み口をそのまま使う）
import writes  # noqa: E402  （.shared/core。修正前の版）
from leftovers import Unreadable, git  # noqa: E402

LEDGER = "fix-gates.json"
GATES = ("red_green", "test_edits")
NO_SUITE = "テストの実行器（入力 tdd_suite）が無い run——受け入れのテストの事後の赤緑は確かめない"
REJECT = "修正の後の木に、輪の中の関門が通さない物が在る（事後の関門の束）: "
REDO = ("——並べた行を全部直してから、返答を丸ごと出し直せ（受け入れのテストは base で案の種類の赤・今の木で緑。名指しの外の"
        "既存のテストの本体は変えない。案の前提が誤りなら conflicts で申し出よ）")
NO_RUN = "受け入れのテストの事後の赤緑を確かめられない"   # skipped の頭（実行器が走らない・base の木を作れない）
EDITED = "名指しの外の既存のテストの本体を変えた・消した（変えてよいのは修正案の rewrite_tests の名指しと裁定 fix_test_scope の範囲だけ）"
RUN = "gates"   # 一式のログ・JUnit の名（suite-gates-<回>-now.log・…-base.log）


def problems(board_dir, repo, base_rev: str, suite: str, attempt: int, *, pass_: str = "first") -> list[dict]:
    """束の行 [{gate, id, detail}]（GATES の順）。行と飛ばした理由を帳面（LEDGER）に積む。盤面の欄の控えが凍結の印と
    食い違えば conflict.frozen_fields が盤面を止めて BoardGap（受け付けの入口が 2 にする）"""
    b = entry.open_board(board_dir)
    repo = pathlib.Path(repo)
    rev = writes.base_rev(b, base_rev)
    plain = fixshape.plain(board_dir)
    fields = conflict.frozen_fields(b)   # 先に読む（食い違いは BoardGap。下の planmarks.rewrites はもう投げない）
    tests = [] if plain else _accept_tests(b, fields)
    rows, skipped = [], []
    if tests and not suite:
        skipped.append(NO_SUITE)
    elif tests:
        got, why = _red_green(repo, rev, suite, tests, b.work(f"{RUN}-{pass_}-{attempt}"))
        rows += got
        skipped += why
    rows += _test_edits(b, repo, rev, plain, pass_ == "ruled")
    _record(b, {"pass": pass_, "attempt": attempt}, fixshape.shape_at(board_dir), rows, skipped)
    return rows


def reject_text(rows: list[dict]) -> str:
    """REJECT と、行ごとの『<gate> <id>: <detail>』を全部（1 行ずつ直させて受け付けの回数を使い切らない）と、出し直しの頼み"""
    return REJECT + " / ".join(f"{r['gate']} {r['id']}: {r['detail']}" for r in rows) + REDO


def _accept_tests(b, fields) -> list[dict]:
    """route が tdd の項目のうち直す義務の単位を名指す物（unit_keys の無い項目も）の受け入れのテスト [{id, red_kind}]（項目の順・
    id の重複は最初の物）"""
    owed = conflict.owed_units_but_asked(b) if fields else set()
    out = {}
    for f in fields or []:
        if not isinstance(f, dict) or f.get("route") != "tdd":
            continue
        keys = f.get("unit_keys")
        if isinstance(keys, list) and keys and not set(keys) & owed:
            continue
        for t in f.get("tests") or []:
            if isinstance(t, dict) and isinstance(t.get("id"), str) and t["id"].strip():
                out.setdefault(t["id"], t.get("red_kind"))
    return [{"id": i, "red_kind": k} for i, k in out.items()]


def _test_files(repo, rev: str, tree: str) -> list[str]:
    """base から木 tree で変わったテストのファイル（tddloop.TEST_FILE の名）"""
    return [f for f in tddloop.touched(repo, rev, tree) if tddloop.TEST_FILE.match(posixpath.basename(f))]


def _red_green(repo: pathlib.Path, rev: str, suite: str, tests: list, work: pathlib.Path) -> tuple[list, list]:
    """(行, 飛ばした理由)。今の木で一式（名指しを絶対パスの node id で後ろに足す）を 1 回、base の木で 1 回走らせて比べる"""
    work.mkdir(parents=True, exist_ok=True)
    ids = [t["id"] for t in tests]
    tree = tddloop.snapshot(repo)
    try:
        now, _, why = tddloop.run_suite(suite, repo, work, f"{RUN}-now", tddloop.abs_ids(repo, ids))
    finally:
        tddloop.restore_paths(repo, tree, tddloop.touched(repo, tree, tddloop.snapshot(repo)))   # 走らせて出来た物を消す
    if now is None:
        return [], [f"{NO_RUN}（今の木で実行器が走らない: {'; '.join(why)}）"]
    copy = sorted(set(_test_files(repo, rev, tree)) | {posixpath.normpath(i.partition("::")[0]) for i in ids})
    base, why = _base_run(repo, rev, suite, ids, copy, work)
    if base is None:
        return [], [f"{NO_RUN}（base の木: {'; '.join(why)}）"]
    rules = tddloop.rules()
    rows = []
    for t in tests:
        c = rules.match_case(t["id"], now)
        if c is None or c["outcome"] != "passed":
            rows.append(_row("red_green", t["id"], f"今の木で {c['outcome'] if c else '一式の結末に居ない'}（受け入れのテストが緑でない）"))
        c = rules.match_case(t["id"], base)
        if c is None:
            rows.append(_row("red_green", t["id"], "base で一式の結末に居ない（読み込みで落ちたか、名指しが実行器の識別子と違う）"))
        elif c["outcome"] == "passed":
            rows.append(_row("red_green", t["id"], "base で緑（直す前に赤でないテストは修正の証拠にならない）"))
        elif c["outcome"] != "failure":
            rows.append(_row("red_green", t["id"], f"base で {c['outcome']}（テストの中の検査で落ちる赤でない）"))
        elif tddloop.kind_problems([t], base):
            rows.append(_row("red_green", t["id"], f"base で {tddloop.red_kind(c)}（案は {t.get('red_kind')}）"))
    return rows, []


def _base_run(repo: pathlib.Path, rev: str, suite: str, ids: list, copy: list, work: pathlib.Path) -> tuple:
    """(base の木で走らせた結末か None, 問題)。一時の git worktree（--detach）に base を出し、copy のパスを今の木の姿に揃えて
    （今の木に無ければ消して）走らせる。実行器が repo の中に在れば worktree の中の同じ物を走らせる。worktree は成否に
    関わらず消す（作業ツリー・index・枝は動かさない）"""
    td = pathlib.Path(tempfile.mkdtemp(prefix="works-fixgates-"))
    wt = td / "base"
    try:
        try:
            git(repo, "-c", "core.hooksPath=/dev/null", "worktree", "add", "--detach", "--quiet", str(wt), rev)
        except Unreadable as e:
            return None, [str(e)]
        for f in copy:
            src, dst = repo / f, wt / f
            if src.is_file():
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(src, dst)
            elif dst.is_file() or dst.is_symlink():
                dst.unlink()
        exe = pathlib.Path(suite)
        try:
            inner = wt / exe.absolute().relative_to(repo.absolute())
            exe = inner if inner.is_file() else exe
        except ValueError:
            pass
        cases, _, why = tddloop.run_suite(str(exe), wt, work, f"{RUN}-base", tddloop.abs_ids(wt, ids))
        return cases, why
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


def _test_edits(b, repo: pathlib.Path, rev: str, plain: bool, ruled: bool) -> list[dict]:
    files = _test_files(repo, rev, tddloop.snapshot(repo))
    if not files:
        return []
    plan = [r["id"] for r in planmarks.rewrites(b) if isinstance(r.get("id"), str)]
    limits = conflict.ruled_test_limits(b, rulings=ruled, skip_ids=plan)   # 修正案の行を外した裁定の範囲（1 回目は空）
    allowed = (set() if plain else set(plan)) | _ruled_ids(repo, rev, files, limits)
    return [_row("test_edits", i, EDITED) for i in tddloop.unnamed_edits(repo, rev, files, allowed)]


def _ruled_ids(repo, rev: str, files: list, limits: list) -> set:
    """裁定の範囲（`<パス>` か `<パス>:<行>[-<行>]`）に掛かる、base のテストの関数の id。ファイルだけの範囲はそのファイルの全部。
    関数の幅（デコレータ・直前のコメントから本体の終わり）は tddloop.function_span で引き、範囲と重なる関数を許す。
    定義の行が引けない id（入れ子のクラスなど）は許さない（拒む側）"""
    out = set()
    for lim in limits:
        got = conflict.parse_limit(lim)
        if not got or got[0] not in files:
            continue
        path, span = got
        try:
            old = git(repo, "show", f"{rev}:{path}")
        except Unreadable:
            continue
        lines = old.splitlines()
        for tid in tddloop.test_functions(old, path):
            if span is None:
                out.add(tid)
                continue
            line = planmarks.line_in(old, tid)
            wide = tddloop.function_span(lines, line) if line else None
            if wide and wide[0] <= span[1] and span[0] <= wide[1]:
                out.add(tid)
    return out


def _row(gate: str, test_id: str, detail: str) -> dict:
    return {"gate": gate, "id": test_id, "detail": detail}


def _record(b, mark: dict, shape: str, rows: list, skipped: list) -> None:
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
        row = {**mark, "shape": shape, **r}
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
