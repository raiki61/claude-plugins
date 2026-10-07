"""修正の受け付けの事実の確かめ（blk-fix。受け付け scripts/accept.py と、修正役の事前の確かめが同じ口で回す。設計
docs/plans/2026-10-06-ask-planner.md）。規則はここ 1 か所で、受け付けはここから import する（確かめの手順の番号と説明は
accept.py の頭）。

口（受け付けの手順の番号）:
- named_reply・resolved_changes・fix_unit_keys: 返答の番号を盤面の控えで名前に戻す（手順 0）
- check_writes: 書き込みの出どころ（-2）
- check_frozen: TDD の輪で凍ったテストのファイル（1b）。agreed は範囲の相談の合意の行（None は盤面の trace。conflict.agreed）
- check_plan_scope: 承認済みの修正案の範囲（1d）。agreed は同じ。ask は拒否の頭で相談を先の道に言うか（None は置き場の控えで決める）
- precheck(cfg, reply): 修正役が sandbox の中の Bash で返答の前に回す事前の確かめ。上の 3 つ（凍結・書き込み・範囲）だけを、
  試験を回さずに当てる（変更に当たる試験と事後の関門の束は受け付けだけ）。修正役の並べの枝の控え（fixlanes が書く）は repo が単位の
  worktree で、log_repo（書き込みの記録の鍵の run の作業ツリー）と since（枝の base の木）を持つ（枝の確かめと同じ照らし）。盤面は読むだけ（entry.PEEK_ENV。scope は相談の控えの
  値で立てる）。範囲の相談の合意は、修正の輪の確かめの節が盤面の trace に書いた物（conflict.agreed）を受け付けと同じに読む。
  返り {ok, rejects: [{check, text}]}
- main(argv): `<python> factchecks.py <相談の控え> [--reply <下書きの返答の JSON>]`。終了コード 0（通る）・1（拒否の行が在る）・
  2（回す側の誤り）。出力は precheck の返りの 1 行
"""
import argparse
import copy
import json
import os
import posixpath
import sys
from pathlib import Path

sys.dont_write_bytecode = True   # 下の import が pack の中に __pycache__ を作らないように（必ず import より前）
_CORE = Path(__file__).resolve().parents[2] / ".shared" / "core"
if str(_CORE) not in sys.path:
    sys.path.insert(0, str(_CORE))
_LIB = str(Path(__file__).resolve().parent)
if _LIB not in sys.path:
    sys.path.append(_LIB)

import consult  # noqa: E402   範囲の相談の控え（同じブロックの lib）
import conflict  # noqa: E402
import entry  # noqa: E402
import planscope  # noqa: E402
import recount  # noqa: E402
import tddloop  # noqa: E402
import writes  # noqa: E402
from engine import pointers  # noqa: E402  （recount が import した board が写しの engine を sys.path に足す）


def named_reply(reply: dict, board: Path):
    """盤面が p3.fix を待っていれば、返答の番号（changes・not_done の unit_key と plan_faces の key）を盤面の控えで名前に戻した写し
    （resolved_changes と同じ engine の pointers.resolve の 1 本）。待っていない・番号を名前に戻せないときは None（盤面に渡して
    盤面に拒ませる）"""
    b = entry.open_board(board)
    inst = b.rd["instances"].get(recount.FIX_NODE)
    if not inst or inst["status"] != "pending" or not inst.get("launched_at") or not b.deps_met(recount.FIX_NODE):
        return None
    out = copy.deepcopy(reply)
    if pointers.resolve(out, b.nodes[recount.FIX_NODE].get("pointers"), inst.get("pointers")):
        return None
    return out


def resolved_changes(reply: dict, board: Path):
    """盤面が p3.fix を待っていれば、changes の行（番号の unit_key を盤面の控えで名前に戻した写し）。待っていない・changes の形が
    崩れている・番号を名前に戻せないときは None。番号を名前に戻す仕事は engine の pointers.resolve の 1 本で、ここに別の戻しを書かない"""
    rows = reply.get("changes") if isinstance(reply, dict) else None
    if not isinstance(rows, list) or not all(isinstance(c, dict) for c in rows):
        return None
    out = named_reply({"changes": rows}, board)
    return None if out is None else out["changes"]


def fix_unit_keys(reply: dict, board: Path):
    """盤面が p3.fix を待っていれば (changes[].unit_key を名前に戻した列（changes と同じ順）, 直す義務の key の集合,
    直す義務から外れた単位 {key: 理由})（conflict.fix_duty）。待っていない・changes の形が崩れている・番号を名前に戻せない
    ときは None（検査せず entry.take に任せる）"""
    rows = resolved_changes(reply, board)
    if rows is None:
        return None
    keys = [c.get("unit_key") for c in rows]
    if not all(isinstance(k, str) for k in keys):
        return None
    return (keys, *conflict.fix_duty(entry.open_board(board)))


def check_writes(reply: dict, board: Path, base_rev: str, repo: Path, state: str, *, log_repo=None, since=None,
                 made=()) -> dict:
    """書き込みの出どころ（writes.check。欄 bash_writes を外した返答は reply に）。実行器が作ったファイルは run の全部の輪の物を
    外す（tddloop.suite_made_all）。1 回目に受け付けた返答の控えの bash_writes（conflict.held_writes）を役の申告に足す（役の欄の
    形が崩れていれば足さずに形の拒否に任せる）。盤面は書かない（申告の記録は writes.check が足す）。
    修正役の並べの枝（fixlanes）は repo に単位の worktree を渡し、log_repo（記録の鍵の run の作業ツリー。包みは単位の worktree の
    書き込みも run の作業ツリーの記録に載せる）と since（見る変更の起点。枝の base の木。前の段が run の作業ツリーで書いた物は
    単位の worktree の実パスの記録を持たないので見ない）と made（枝の実行器が作ったファイル）を渡す"""
    made = set(tddloop.suite_made(state)) | tddloop.suite_made_all(board) | set(made)
    b = entry.open_board(board)
    rev = since or writes.base_rev(b, base_rev)
    held, own = conflict.held_writes(b), reply.get(writes.FIELD)
    if held and (own is None or isinstance(own, list)):
        reply = {**reply, writes.FIELD: [*(own or []), *(w for w in held if w not in (own or []))]}
    return writes.check(reply, repo, [p for p in writes.changed(repo, rev) if p not in made],
                        writes.sink(repo if log_repo is None else log_repo))


def _loop_states(board, state) -> list:
    """run の全部の輪の状態のファイル（盤面の tdd-<k> の番号の順。今の輪 state は最後。無ければ空）"""
    if not state:
        return tddloop.states(board)
    return [p for p in tddloop.states(board) if p.resolve() != Path(state).resolve()] + [state]


def check_frozen(board: Path, state: str, repo: Path, pass_: str, agreed=None) -> list:
    """手順 1b: 凍ったテストのファイル（tddloop.frozen_problems）を run の全部の輪で見た拒否の文。今の輪（state）は今どおり、前の輪
    （1 回目の修正の段の輪）は今の輪の状態の handoff の木（since）からの変更で見て、直した項目の単位（conflict.amended_keys）の前の
    輪の受け入れのテストの関数（tddloop.test_spans）の中の変更は通す。テストの変更の許し（conflict.ruled_test_limits）は輪ごとに、
    凍結の検査が比べる木で修正案の行を引き直す（今の輪は輪の後の木、前の輪は since の木。tddloop.frozen_source）。輪が赤→緑を
    確かめた書き換えは、どの輪の物でも許しから外す。今の輪が無い（2 回目の段の輪が走らなかった）時、前の輪は輪の後の木で見る。
    裁定の範囲は今の輪だけ pass_ で決め（1 回目の受け付けは含めない）、前の輪はいつも含める（前の段で裁いた fix_test_scope の
    直しは、今の段の受け付けが first でも許し）。輪が 1 つも無ければ空。盤面は書かない"""
    loops = _loop_states(board, state)
    if not loops:
        return []
    b = entry.open_board(board)
    skip = [i for p in loops for i in tddloop.verified_rewrites(p)]

    def allowed(source, rulings):
        return conflict.ruled_test_limits(b, rulings=rulings, source=source, skip_ids=skip, agreed_rows=agreed)
    out = tddloop.frozen_problems(state, repo, allowed(tddloop.frozen_source(state, repo), pass_ == "ruled")) if state else []
    old = loops[:-1] if state else loops
    if old:
        since = tddloop.load_state(state).get("handoff") if state else None
        amended = conflict.amended_keys(b)
        for p in old:
            out += tddloop.frozen_problems(p, repo, allowed(tddloop.frozen_source(p, repo, since=since), True), since=since,
                                           skip_spans=tddloop.test_spans(p, amended))
    return out


def _loop_freeze(board, state) -> tuple:
    """(一番後の輪の frozen_tree, run の全部の輪が凍らせたファイル)。輪が無ければ (None, [])"""
    tree, files = None, set()
    for p in _loop_states(board, state):
        st = tddloop.load_state(p)
        files |= set(st.get("frozen") or {})
        tree = st.get("frozen_tree") or tree
    return tree, sorted(files)


def check_plan_scope(reply: dict, keys: list, board: Path, base_rev: str, repo: Path, state: str, pass_: str,
                     agreed=None, ask=None, since=None, made=()) -> tuple:
    """承認済みの修正案の項目と差分の照らし（planscope.check）。行は changes と keys（単位の名前）を並べ、files を根からの相対に
    揃えた物。変わったパスは版からの変更（writes.changed）から実行器が作ったファイル（tddloop.suite_made）を除いた物。TDD の輪が
    凍らせたファイル（輪の状態の frozen と frozen_tree）は planscope.check に渡し、欠けは版からの
    差分の全部で、修正役に問う外れと余分は凍った後に変えた分だけで見させる。
    返り (拒否の行（最初の行の頭に planscope.reject_head）, 記録)。盤面は書かない（控えの食い違いで止めるのは planscope.check）。
    頭は、範囲の相談がこの段に在れば相談を先の道に言う。ask が None なら今の scope の置き場の控えで決める（consult.offered）。
    凍らせたファイルと実行器が作ったファイルは run の全部の輪の物（_loop_freeze・tddloop.suite_made_all）で、凍った後は一番後の
    輪の frozen_tree から見る（前の輪の後に 1 回目の段と後の輪が書いた物を、2 回目の修正役のせいにしない）。
    修正役の並べの枝（fixlanes）は repo に単位の worktree を、since に枝の base の木を渡す: 照らす変わったパスは枝が変えた物だけ
    （版との比べの中身は今どおり版から）。made は枝の実行器が作ったファイル"""
    b = entry.open_board(board)
    rows = [{"unit_key": k, "files": sorted(declared_files([c], repo))} for c, k in zip(reply.get("changes") or [], keys)]
    tree, frozen = _loop_freeze(board, state)
    made = set(tddloop.suite_made(state)) | tddloop.suite_made_all(board) | set(made)
    rev = writes.base_rev(b, base_rev)
    paths = [p for p in writes.changed(repo, since or rev) if p not in made]
    problems, note = planscope.check(rows, b, repo, rev, paths, pass_=pass_, loop_tree=tree, frozen=frozen,
                                     agreed=agreed)
    if problems:
        if ask is None:
            ask = consult.offered(consult.place_of(board), pass_)
        problems = [planscope.reject_head(ask) + problems[0], *problems[1:]]
    return problems, note


def declared_files(rows, repo) -> set:
    """changes の行の files を、リポジトリの根からの相対パスに揃えた集合"""
    out = set()
    for c in rows:
        for f in c.get("files") or []:
            if isinstance(f, str) and f.strip():
                f = f.strip()
                out.add(posixpath.normpath(os.path.relpath(f, repo) if os.path.isabs(f) else f))
    return out


def precheck(cfg: dict, reply=None) -> dict:
    """事前の確かめ（模块の頭）"""
    entry.peek_as(cfg.get("scope") or "")   # 役の Bash には節の env が無い。控えの置き場の印で読むだけに開く
    board, repo = Path(cfg["board"]), Path(cfg["repo"])
    state, pass_, base_rev = cfg.get("tdd_state") or "", cfg.get("pass") or "first", cfg.get("base_rev") or ""
    log_repo, since = cfg.get("log_repo") or None, cfg.get("since") or None   # 修正役の並べの枝の控え（fixlanes が書く）
    reply = reply if isinstance(reply, dict) else {"changes": []}
    agreed = conflict.agreed(entry.open_board(board, allow_halted=True))
    found = [("frozen", t) for t in check_frozen(board, state, repo, pass_ if pass_ in ("first", "ruled") else "first",
                                                 agreed=agreed)]
    wrote = check_writes(reply, board, base_rev, repo, state, log_repo=log_repo, since=since)
    found += [("writes", t) for t in wrote["problems"]]
    got = fix_unit_keys(wrote["reply"], board) if since is None else None   # 枝の返答は単位の名前で書く（番号の控えは修正役の物）
    keys = got[0] if got is not None else [c.get("unit_key") for c in wrote["reply"].get("changes") or [] if isinstance(c, dict)]
    scope, _ = check_plan_scope(wrote["reply"], keys, board, base_rev, repo, state,
                                pass_ if pass_ in ("first", "ruled") else "first", agreed=agreed, ask=True, since=since)
    found += [("scope", t) for t in scope]
    return {"ok": not found, "rejects": [{"check": c, "text": t} for c, t in found]}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="factchecks.py", description="受け付けの事実の確かめ（凍結・書き込み・範囲）を試験なしで回す")
    ap.add_argument("config", help="相談の控え（指示書に書かれたパス）")
    ap.add_argument("--reply", default="", help="下書きの返答の JSON のファイル（無ければ changes の無い返答として見る）")
    a = ap.parse_args(argv)
    try:
        cfg = consult.load_config(a.config)
        reply = json.loads(Path(a.reply).read_text(encoding="utf-8")) if a.reply else None
        out = precheck(cfg, reply)
    except (ValueError, OSError, KeyError) as e:
        print(f"factchecks: {e}", file=sys.stderr)
        return 2
    print(json.dumps(out, ensure_ascii=False))
    return 0 if out["ok"] else 1


if __name__ == "__main__":
    for _s in (sys.stdout, sys.stderr):
        if hasattr(_s, "reconfigure"):
            _s.reconfigure(encoding="utf-8")
    sys.exit(main())
