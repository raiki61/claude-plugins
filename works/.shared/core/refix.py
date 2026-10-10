"""差分の審査（blk-delta）と 2 往復の手直し（blk-refix）の口（線 A の仕様 3.3・3.4。計画 Task 13）。

版を固める・差分を切る・義務を組むのは盤面の機械の節（写しの RL の fix_delta・delta_owed。DELTA_PASSES の cut・owed）で、
役の返答を受けた後の settle が回す。ここは盤面が書いた物を役に見せ、役の返答を盤面に渡し、盤面から出口を組むだけ。
節の名前は写しの RL の DELTA_PASSES からだけ引く（passes()。works に名前の写しを持たない。仕様 7 節）。

- passes():                  {n: {cut, review, owed, fix, state_key, owed_key}}（写しの DELTA_PASSES から）
- fix_delta(b):              今の周の修正の差分（盤面の loop.<1 回目の state_key>。{file, files, rev, …}）か None
- cut(board, n, repo):      n 回目の審査役を起こす前の支度。盤面の loop.<state_key>（今の周）の差分のファイルと触ったファイルを
                             返し、役に見せる材料（brief）を書き、読むだけの役の前の作業ツリーの写しを撮り、起こした印を置く
- prep_fix(board, n, repo):  n 回目の手直しの役を起こす前の支度。義務（loop.<owed_key>）と差分のパスと穴ごとの枝の名札（ties）を brief に書き、呼び手の
                             組み立て（prompt）で指示書を書き、印を置く
- accept_review・accept_fix: 役の返答を盤面に渡す（entry.take。審査は読むだけの役の写しと比べる。手直しは先に修正案の項目の
                             範囲で変更を照らして外れを拒み（planrange.check_paths。修正の段と同じ決まり）、書き込みの
                             記録と申告（欄 bash_writes）に突き合わせ、どちらにも無い変更を拒む）。1 回目の審査は準拠と品質の 2 判定の欄
                             （deltamarks）を承認済みの修正案の項目（_plan_items）と照らし、欠けと誤りは盤面へ渡さずに拒み、
                             通れば欄を外して渡し、受けた時だけ欄を今の周の delta-verdicts.json に控える
- main_accept_review・main_accept_fix: 受け付けのスクリプトの入口（rolekit.main_accept。3 回目の拒否で done・give_up。R50）
- hole_ties(b, n)・tie_items(b)・brief_ties(ties): n 回目の手直しの穴ごとの枝の名札（holeties.tie。線の木の段 4a）・名札に使う項目・brief の欄
- route(board):              blk-refix の分かれ道 {review2, refix2, owed, owed2}（盤面の待っている節と義務の数）
- collect_delta・collect_refix: 出口（1 本目の欄を全部残して足す）。役が 3 回とも拒まれて輪を抜けたら、最後の拒否の文で
                             盤面を止めて ok: false（rolekit.gave_up。by は stopby.DELTA・stopby.REFIX）
- must(board, role):         読んだ証拠（reads）に渡す「機械が渡したパス」（brief と差分のファイルと、組んだ指示書）
- script_main(fn, inputs):   ブロックのスクリプトの入口（配線の誤りは標準エラーに 1 行で 2。TA19）

作業ファイル（b.work。今の周の r<N>/。周の番号を仮定しない。TA17）: review<n>-snapshot.json（計画の予約の名）・
review<n>-brief.json・refix<n>-brief.json（役に見せる材料: graph がその節に読ませる盤面の値と、人の方針 policy.brief の
{paste, path}。審査役の brief には、変わったファイルのうち守りのファイル（protect.hits）の protected_files も、1 回目の審査役の brief には修正の差分に当てたレンズの行（lens.brief_rows）の lens も
（graph の reads は写しなので足せない。手直しの差分にはレンズが当たらないので 2 回目には載せない）。1 本目の blk-delta の YAML は入口 policy_paste を持たないので、審査役へは方針の本文をこの brief で届ける。
1 回目の審査役の brief には範囲の欄の在る承認済みの修正案の項目 plan_items（_plan_items。無ければ空。裁定で外れた項目は held
つき）と直す裁定が広げたパス ruled_paths と直した側の報告 fix_report（今の周の修正の出力の changes・not_done。無ければ空）も、
1 回目の手直しの役の brief には同じ plan_items・ruled_paths と、審査の 2 判定の控えの準拠の落ちた行 compliance
（deltamarks.fail_rows）も載せる。2 回目の往復には載せない）・手直しの役の指示書
prompt-<節>.md（呼び手のブロックが組む）・審査役の座 review<n>-seat.md（brief の seat_file。座の在る審査役は 1 回目だけ（seat.SEATS）で、
座の無い役は空）。
支度は前の試みの自分の出力（brief・指示書・reads-<役>.json・1 回目の審査の 2 判定の控え delta-verdicts.json）を先に消す——新しい
審査の出口が前の審査の穴を数えない（darkfactory の自分食いで 1 本目の blk-delta が踏んだ形）。出口は盤面の今の周の出力（output_of_round）だけを読む。
"""
import functools
import json
import os
import pathlib
import sys

sys.dont_write_bytecode = True

_CORE = pathlib.Path(__file__).resolve().parent
if str(_CORE) not in sys.path:
    sys.path.insert(0, str(_CORE))

from board import BoardGap, pending_instance as _pending, rules_module  # noqa: E402
import engine.util as _util  # noqa: E402
from engine.schema import validate_schema  # noqa: E402
import accept  # noqa: E402
import conflict  # noqa: E402
import deltamarks  # noqa: E402
import entry  # noqa: E402
import holeties  # noqa: E402
import lens  # noqa: E402
import marks  # noqa: E402
import node_marker  # noqa: E402
import planmarks  # noqa: E402
import planrange  # noqa: E402
import policy  # noqa: E402
import protect  # noqa: E402
import promptsection  # noqa: E402
import reads  # noqa: E402
import recount  # noqa: E402
import rolekit  # noqa: E402
import seat  # noqa: E402
import stopby  # noqa: E402  （L1。止めの理由の住処）
import writes  # noqa: E402

PASS_KEYS = ("cut", "review", "owed", "fix", "state_key", "owed_key")
REVIEW_ROLE = {1: "review", 2: "review2"}   # 審査役の名（印 works-node の名・reads-<役>.json）
FIX_ROLE = {1: "refix", 2: "refix2"}        # 手直しの役の名
# 1 回目の審査役の座（cut が review1-seat.md に書いて brief の seat_file と must で名指す。2 回目の審査役 review2 には座が無い）
RECEIVES = [promptsection.Receive(REVIEW_ROLE[1], head) for head in (seat.HEAD, seat.PROMPT_HEAD, seat.WORDS_HEAD)]
# 読んだ証拠の節（reads.main_for の引数: 役・輪・節。Task 6 の reads.py の口。include の名は reads が今の scope から引く）
READS = {"review": ("review", "delta-loop", "review"),
         "refix": ("refix", "refix-loop", "refix"),
         "review2": ("review2", "review2-loop", "review2"),
         "refix2": ("refix2", "refix2-loop", "refix2")}
# 手直しの変更が承認済みの修正案の項目の範囲から外れた時の拒否の頭（planrange.check_paths の行を続ける。修正の段と同じ決まり）
SCOPE_REJECT = ("手直しが承認済みの修正案の項目の範囲から外れた（項目の範囲の外で変えてよいのは、材料の ruled_paths と、範囲の相談で"
                "合意したパス・テストの変更の許しのパスだけ。外れた変更を戻して返答を丸ごと出し直せ。試験を回して出来たファイル"
                "（キャッシュ・結果の XML）も消せ。範囲の外が要る穴は直さずに declared で残し、how に理由を書け）: ")


@functools.lru_cache(maxsize=1)
def _table() -> tuple:
    """写しの RL の DELTA_PASSES の (n, ((鍵, 値), …)) の並び（RL の読み込みは 1 回 40 ミリ秒ほどなので、プロセスに 1 回）"""
    return tuple((n, tuple((k, getattr(p, k)) for k in PASS_KEYS)) for n, p in rules_module().DELTA_PASSES.items())


def passes() -> dict:
    """写しの RL の DELTA_PASSES を {n: {cut, review, owed, fix, state_key, owed_key}} にする（節の名前はここ 1 か所で引く）"""
    return {n: dict(kv) for n, kv in _table()}


def _pass(n) -> dict:
    ps = passes()
    if n not in ps:
        raise BoardGap(f"差分の往復 {n!r} は写しの DELTA_PASSES に無い（{sorted(ps)}）")
    return ps[n]


def snapshot_name(n: int) -> str:
    """n 回目の審査役を起こす前の作業ツリーの写し（計画の予約の名 review1-snapshot.json・review2-snapshot.json）"""
    return f"review{n}-snapshot.json"


def output_format(role: str) -> dict:
    """役の節の output_format（T17 で YAML に貼る値。TA20）: mark(role_schema(節), 役の名)。書く役（手直し）には works の欄
    bash_writes（Bash で書いたファイルの申告。writes.BASH_WRITES_SCHEMA）を足す（受け付けが盤面へ渡す前に外す。修正の段の書く役と同じ）"""
    node = {**{r: _pass(n)["review"] for n, r in REVIEW_ROLE.items()},
            **{r: _pass(n)["fix"] for n, r in FIX_ROLE.items()}}.get(role)
    if node is None:
        raise BoardGap(f"役 {role!r} は差分の往復の役でない（{sorted(REVIEW_ROLE.values()) + sorted(FIX_ROLE.values())}）")
    # 足すのは足し欄の住処 marks（種 writes。表に無い審査役はそのまま返る）
    return marks.add("writes", role, node_marker.mark(accept.role_schema(node), role), {writes.FIELD: writes.BASH_WRITES_SCHEMA})


# ---------------------------------------------------------------- 盤面の読み
def _in_round(b, v):
    """周に属する loop 値（{round, …}）を今の周の物だけ（前の周の値は None）"""
    return v if isinstance(v, dict) and v.get("round") == b.round else None


def fix_delta(b) -> dict | None:
    return _in_round(b, b.loop_state.get(_pass(1)["state_key"]))


def _owed_rows(b, n) -> list:
    return (_in_round(b, b.loop_state.get(_pass(n)["owed_key"])) or {}).get("rows") or []


def _out_file(b, nid) -> str:
    """今の周に受けた nid の出力のファイル（絶対パス）。今の周に受けていなければ空"""
    info = b.state["outputs"].get(nid) or {}
    if info.get("round") != b.round or b.output_of_round(nid, b.round) is None:
        return ""
    return str(b.dir / info["file"])


def _read_value(b, path):
    """graph の reads の 1 行（out.<節>[.<欄>]・loop.<鍵>[.<欄>]）の今の周の値（無ければ None）"""
    head, _, rest = path.partition(".")
    if head == "out":
        nid = max((x for x in b.nodes if rest == x or rest.startswith(x + ".")), key=len, default=None)
        if nid is None:
            return None
        v = b.output_of_round(nid, b.round)
        sub = rest[len(nid) + 1:]
    elif head == "loop":
        key, _, sub = rest.partition(".")
        v = _in_round(b, b.loop_state.get(key))
    else:
        return None
    if v is None or not sub:
        return v
    try:
        return _util.get_path(v, sub)
    except KeyError:
        return None


def _brief(b, nid) -> dict:
    """役に見せる材料: graph がその節に読ませる盤面の値（inputs.* を除く reads）の今の周の姿"""
    return {p: _read_value(b, p) for p in b.nodes[nid].get("reads") or [] if not p.startswith("inputs.")}


def _write_text(path: pathlib.Path, text: str) -> pathlib.Path:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)
    return path


def _write_json(path: pathlib.Path, doc) -> pathlib.Path:
    return _write_text(path, json.dumps(doc, ensure_ascii=False, indent=2) + "\n")


def _drop_stale(b, *names):
    """前の試みの自分の出力を消す（今の周の作業ファイルの names）"""
    for p in [b.work(x) for x in names]:
        p.unlink(missing_ok=True)


# ---------------------------------------------------------------- 支度（役を起こす前）
def cut(board: pathlib.Path, n: int, repo: pathlib.Path) -> dict:
    """n 回目の差分の審査役を起こす前の支度。盤面の loop.<state_key> が今の周に無い・審査の節が待っていないなら
    {ok: False, reason}（配線の誤り。スクリプトは 2）。在れば、前の試みの自分の出力を消し、役に見せる材料を
    review<n>-brief.json に書き、作業ツリーの写し（review<n>-snapshot.json）を撮り、起こした印を置いて
    {ok: True, files, diff_file, rev, brief_file, must} を返す。名前は盤面の値のまま（組み立てない）。審査役の座が
    載る（seat.carries。1 回目の審査役）なら、task-review の型を埋めた座（seat.section。穴は brief・人の方針の文書・
    直した側の出力・差分の起点と修正後の版・差分のファイル。無い物は seat.NONE）を review<n>-seat.md に書いて brief の
    seat_file と must に名指す（載らなければ seat_file は空。写しが固定と違えば何も書かずに ValueError）。1 回目は修正案の欄の
    控えが凍結の印と食い違えば、差分の審査の段の印 stopby.DELTA で盤面を止めて控えを名指す BoardGap（conflict.fields_broken）"""
    p = _pass(n)
    b = entry.open_board(board)
    d = _in_round(b, b.loop_state.get(p["state_key"]))
    if not d or not d.get("file"):
        return {"ok": False, "reason": f"盤面に今の周の loop.{p['state_key']} が無い（{p['cut']} が差分を切っていない）"}
    inst = _pending(b, p["review"])
    if inst is None:
        return {"ok": False, "reason": f"この周に {p['review']} が待っていない（盤面の ready に無い節の役は起こさない）"}
    role = REVIEW_ROLE[n]
    brief_name, seat_name = f"review{n}-brief.json", f"review{n}-seat.md"
    pol = policy.brief(b)
    seat_text = ""
    if seat.carries(role):   # 座は 1 回目の審査役だけ（2 回目の review2 には座が無い。seat の頭）。穴の値も 1 回目の物
        seat_text = seat.section(role, {   # 写しの照合（pinned）を書き込みの前に
            "[BRIEF_FILE]": str(b.work(brief_name)), "[GLOBAL_CONSTRAINTS]": pol["path"] or seat.NONE,
            "[REPORT_FILE]": _out_file(b, recount.FIX_NODE) or seat.NONE,
            "[BASE_SHA]": _cut_base(b) or seat.NONE, "[HEAD_SHA]": d.get("rev") or seat.NONE, "[DIFF_FILE]": d["file"]})
    _drop_stale(b, brief_name, seat_name, reads.evidence_name(role), *((deltamarks.VERDICTS_FILE,) if n == 1 else ()))
    seat_file = str(_write_text(b.work(seat_name), seat_text)) if seat_text else ""
    doc = {"node": p["review"], "diff_file": d["file"], "files": d.get("files") or [], "rev": d.get("rev"),
           "reads": _brief(b, p["review"]), "policy": pol, "seat_file": seat_file}
    try:   # 変わったファイルのうち守りのファイル（protect）。審査役が検査を緩める変更を見る材料（最後の人の関所にも必ず出る）
        doc["protected_files"] = protect.hits(doc["files"])
    except protect.Broken as e:
        doc["protected_files"], doc["protected_files_error"] = [], str(e)
    if n == 1:
        try:
            doc["lens"] = lens.brief_rows(b)
        except ValueError as e:
            doc["lens"], doc["lens_error"] = [], str(e)
        doc["plan_items"] = _plan_items(b)
        doc["ruled_paths"] = conflict.ruled_paths(b)
        doc["fix_report"] = _fix_report(b)
    brief =_write_json(b.work(brief_name), doc)
    entry.snapshot(board, snapshot_name(n), repo)
    b.mark_launched(p["review"], inst.get("attempts", 1))
    return {"ok": True, "files": list(d.get("files") or []), "diff_file": d["file"], "rev": d.get("rev") or "",
            "brief_file": str(brief), "must": [str(brief), d["file"]] + ([seat_file] if seat_file else [])}


def _cut_base(b) -> str:
    """1 回目の審査の差分の起点の版（写しの RL の fix_delta と同じ決まり。.shared/core/graphloops/rules/review-loop.py:1578 の
    rev の行の 1 回目: 周の頭に固めた版 reviewed_revision）。無ければ空。座の載る審査役は 1 回目だけなので 2 回目の起点は作らない"""
    return b.loop_state.get("reviewed_revision") or ""


def prep_fix(board: pathlib.Path, n: int, repo: pathlib.Path, *, prompt=None, values=None) -> dict:
    """n 回目の手直しの役を起こす前の支度。手直しの節が待っていない・義務が今の周に無いなら {ok: False, reason}
    （配線の誤り）。在れば前の試みの自分の出力を消し、義務と差分のパスを refix<n>-brief.json に書き、起こした印を置いて
    {ok: True, owed, diff_file, brief_file, must} を返す。prompt（呼び手のブロックの組み立て prompt(n, 値) -> 指示書の字）を
    渡せば、{brief_file, diff_file, lang（言語の 1 行。rolekit.lang_line）} と values（run の値）で組んだ指示書を今の周の prompt-<節>.md に書き、prompt_file を足す
    （must にも。core は決まりの中身を知らない）。1 回目は修正案の欄の控えが凍結の印と食い違えば、手直しの段の印 stopby.REFIX で
    盤面を止めて控えを名指す BoardGap（conflict.fields_broken）"""
    p = _pass(n)
    b = entry.open_board(board)
    inst = _pending(b, p["fix"])
    if inst is None:
        return {"ok": False, "reason": f"この周に {p['fix']} が待っていない（盤面の ready に無い節の役は起こさない）"}
    rows = _owed_rows(b, n)
    if not rows:
        return {"ok": False, "reason": f"盤面に今の周の loop.{p['owed_key']} の義務が無い（{p['owed']} が組んでいない）"}
    d = _in_round(b, b.loop_state.get(p["state_key"])) or {}
    role = FIX_ROLE[n]
    brief_name = f"refix{n}-brief.json"
    prompt_file = b.work(rolekit.prompt_name(p["fix"]))
    _drop_stale(b, brief_name, reads.evidence_name(role), prompt_file.name)
    doc = {"node": p["fix"], "diff_file": d.get("file") or "", "owed": rows, "reads": _brief(b, p["fix"]),
           "policy": policy.brief(b)}
    try:   # 穴ごとの枝の名札（線の木の段 4a。材料だけで、答え方は変えない。組めなければ理由を置いて手直しは起こす）
        doc["ties"] = brief_ties(hole_ties(b, n))
    except Exception as e:
        doc["ties"], doc["ties_error"] = [], f"{type(e).__name__}: {' '.join(str(e).split())}"
    if n == 1:   # 1 回目の審査の 2 判定の控えの準拠の落ちた行（face_key が owed の key と同じ行が、その項目への準拠の外れ）
        doc["plan_items"] = _plan_items(b, by=stopby.REFIX)
        doc["ruled_paths"] = conflict.ruled_paths(b)
        doc["compliance"] = deltamarks.fail_rows(deltamarks.read(b))
    brief = _write_json(b.work(brief_name), doc)
    out = {"ok": True, "owed": len(rows), "diff_file": d.get("file") or "", "brief_file": str(brief),
           "must": [str(brief)] + ([d["file"]] if d.get("file") else [])}
    if prompt is not None:
        _write_text(prompt_file, prompt(n, {**(values or {}), "brief_file": str(brief), "diff_file": out["diff_file"],
                                            "lang": rolekit.lang_line(b.state.get("inputs"))}))
        out["prompt_file"] = str(prompt_file)
        out["must"].append(str(prompt_file))
    b.mark_launched(p["fix"], inst.get("attempts", 1))
    return out


PLAN_REVIEW = "p2.plan_review"   # 事前審査の節（穴の unit_keys。塞がっていない検算を枝に結ぶ）


def tie_items(b) -> list[dict]:
    """名札に使う承認済みの修正案の項目（planmarks.approved_items）に、裁定で外れた項目の held（conflict.held_item）を足した物。
    引けない・控えが壊れている・食い違いの控えが読めない時は []（名札は材料で、盤面を止めない。止めるのは _plan_items の道）"""
    try:
        items = planmarks.approved_items(b) or []
        held = conflict.held_by_rulings(b) if items else {}
    except (planmarks.FieldsBroken, BoardGap, OSError, ValueError):
        return []
    for it in items:
        why = conflict.held_item(it.get("unit_keys"), held)
        if why:
            it["held"] = why
    return items


def hole_ties(b, n: int) -> list[dict]:
    """n 回目の手直しの義務（loop.<owed_key>）の穴ごとの枝の名札（holeties.tie）。義務が今の周に無ければ []。
    where は n 回目の差分の審査の faces から（義務の行の text からは引かない）。1 回目は準拠の落ちた行（deltamarks）・事前審査の穴の
    unit_keys・修正の changes を、2 回目は 1 回目の名札と 1 回目の手直しの handled（holeties.earlier）を使う。盤面は読むだけ"""
    p = _pass(n)
    rows = _owed_rows(b, n)
    if not rows:
        return []
    rv = b.output_of_round(p["review"], b.round) or {}
    where = {f.get("key"): f.get("where") for f in rv.get("faces") or [] if isinstance(f, dict)}
    holes = [{"key": r.get("key"), "from": r.get("from") or "", "where": where.get(r.get("key")) or "",
              "check": str(r.get("from") or "").endswith(".checks")} for r in rows if isinstance(r, dict)]
    items = tie_items(b)
    if n == 1:
        return holeties.tie(holes, items, compliance=deltamarks.fail_rows(deltamarks.read(b)),
                            plan_faces=(b.output_of_round(PLAN_REVIEW, b.round) or {}).get("faces") or [],
                            changes=(b.output_of_round(recount.FIX_NODE, b.round) or {}).get("changes") or [])
    handled = (b.output_of_round(_pass(n - 1)["fix"], b.round) or {}).get("handled") or []
    return holeties.tie(holes, items, earlier=holeties.earlier(hole_ties(b, n - 1), handled))


def brief_ties(ties: list) -> list[dict]:
    """手直しの役の brief の ties の欄: 穴ごとの {key, branches（人が読む枝の名）, note（holeties.note）, via}"""
    return [{"key": t["key"], "branches": [holeties.label(x) for x in t["branches"]], "note": holeties.note(t),
             "via": t["via"]} for t in ties]


# ---------------------------------------------------------------- 受け付け
def _plan_items(b, by: str = stopby.DELTA) -> list[dict]:
    """今の周の範囲の欄の在る承認済みの修正案の項目（planmarks.scoped_items。修正案の無い run・217 番の形の控えは空）。全部の
    項目を番号のまま返し、裁定で外れた項目（conflict.held_item）には held（外した裁定の理由）を、単位の一部だけが外れた項目には
    held_units（conflict.held_units の {単位: 理由}）を足す。控えが
    凍結の印と食い違えば conflict.fields_broken の道（呼んだ段の印 by で盤面を止めて控えを名指す BoardGap。差分の審査の支度と
    受け付けは stopby.DELTA、手直しの支度は stopby.REFIX）"""
    try:
        items = planmarks.scoped_items(b) or []
    except planmarks.FieldsBroken as e:
        raise conflict.fields_broken(b, e, by=by) from None
    held = conflict.held_by_rulings(b) if items else {}
    for it in items:   # 番号は保つ（準拠の行の番号の照らし）。外れた項目は照らさず直させない（conflict.held_item の 1 つの決まり）
        why = conflict.held_item(it.get("unit_keys"), held)
        some = conflict.held_units(it.get("unit_keys"), held)
        if why:
            it["held"] = why
        elif some:   # 単位の一部だけが外れた項目: 外れた単位の分は照らさない・直さない
            it["held_units"] = some
    return items


def _copy_shape_errors(nid: str, bare: dict) -> list[str]:
    """2 判定の欄を外した返答を写しの graph の型（役の型から deltamarks の欄を除いた物）で照らした誤りの行"""
    return validate_schema(bare, deltamarks.without_verdicts(nid, accept.role_schema(nid)))


def _fix_report(b) -> dict:
    """直した側の報告（今の周の修正の出力の changes・not_done）。今の周に受けていなければ空"""
    out = b.output_of_round(recount.FIX_NODE, b.round)
    return {k: out.get(k) or [] for k in ("changes", "not_done")} if isinstance(out, dict) else {}


def accept_review(reply: dict, board: pathlib.Path, base_rev: str, repo: pathlib.Path, *, n: int) -> dict:
    """n 回目の審査役の返答（読むだけの役。cut が撮った写しと今の作業ツリーを比べる）。entry.take の返り。節が
    deltamarks.NODES に在れば、先に 2 判定の欄を承認済みの修正案の項目と照らし、欠けと誤りが在れば盤面へ渡さずに
    {ok: False, reason: deltamarks.REJECT と行}。無ければ欄を外した返答を渡し、受けた時だけ欄を控える（置けなければ
    rolekit.halt_unsaved の道: 盤面を止めて控えを名指す BoardGap）。拒む時は、欄を外した返答の写しの型の誤りも同じ拒否に並べる
    （1 つの返答の誤りを 1 回で返す）。修正案の欄の控えが凍結の印と食い違えば conflict.fields_broken の道（差分の審査の段の印
    stopby.DELTA で盤面を止めて控えを名指す BoardGap）。faces が穴の並びの形でない返答は照らさずに、欄を外して渡す
    （写しの型が faces を拒む。守る 2 つの欄を知らない欄と言わせない）"""
    nid = _pass(n)["review"]
    if nid not in deltamarks.NODES:
        return entry.take(board, nid, reply, repo, snapshot_name=snapshot_name(n))
    if deltamarks.malformed(reply):
        return entry.take(board, nid, deltamarks.split(reply)[0], repo, snapshot_name=snapshot_name(n))
    b = entry.open_board(board)
    gaps = deltamarks.gaps(reply, _plan_items(b))
    bare, verdicts = deltamarks.split(reply)
    if gaps:   # 欄を外した返答の写しの型の誤りも同じ拒否に（1 つの返答の誤りを 1 回で返す。224 と同じ形）
        gaps += [f"返答の形: {e}" for e in _copy_shape_errors(nid, bare)]
        return {"ok": False, "reason": deltamarks.REJECT + "\n" + "\n".join(f"  - {g}" for g in gaps)}
    out = entry.take(board, nid, bare, repo, snapshot_name=snapshot_name(n))
    if out.get("ok") is True:   # 受けた時だけ（拒否では盤面の外の控えも前のまま）
        try:
            deltamarks.save(b, verdicts)
        except Exception as e:   # 書けない・形にできない: 受けた審査に欄が無いまま進ませない
            raise BoardGap(rolekit.halt_unsaved(board, deltamarks.VERDICTS_FILE, e, by=stopby.DELTA)) from None
    return out


def accept_fix(reply: dict, board: pathlib.Path, base_rev: str, repo: pathlib.Path, *, n: int) -> dict:
    """n 回目の手直しの役の返答（書く役）。entry.take の返り。先に、版 base_rev からの変更のうち修正の段が触ったファイル（修正の
    差分の files。その段の受け付けが照らした）の外を、承認済みの修正案の項目の範囲で照らす（planrange.check_paths。修正の段と
    同じ決まり。この役は単位を申告しないので全部の項目の範囲の和と out_of_scope で見る。修正案の範囲の欄が無い run は照らさない）。
    外れが在れば盤面へ渡さずに {ok: False, reason}（同じ会話で直させる）。次に変更を書き込みの記録（Edit・Write）と申告（欄
    bash_writes）に突き合わせ（writes.check。起点は盤面の review_rev）、どちらにも無い変更を拒む（keep-essence の 5。修正の段と同じ）。
    通れば欄 bash_writes を外した返答を盤面に渡し、記録の無い run は知らせを trace に残す"""
    b = entry.open_board(board)
    rev = writes.base_rev(b, base_rev)
    paths = writes.changed(repo, rev)
    fixed = set((fix_delta(b) or {}).get("files") or [])
    bad, _note = planrange.check_paths(b, [p for p in paths if p not in fixed], ruled=True, by=stopby.REFIX)
    if bad:
        return {"ok": False, "reason": SCOPE_REJECT + "\n" + "\n".join(f"  - {x}" for x in bad)}
    got = writes.check(reply, repo, paths, writes.sink(repo))
    if got["problems"]:
        return {"ok": False, "reason": "\n".join(got["problems"])}
    out = entry.take(board, _pass(n)["fix"], got["reply"], repo)
    if out.get("ok") is True:   # 受けた時だけ（拒否では盤面を前のままにする）
        writes.trace(entry.open_board(board, allow_halted=True), FIX_ROLE[n], got)
    return out


def main_accept_review(n: int) -> int:
    """審査の受け付けのスクリプトの入口（rolekit.main_accept。中身の拒否は 0 と 1 行、3 回目の拒否で done・give_up、
    配線の誤りは 2）。盤面へは accept_review（2 判定の欄の照らしと控えつき。読むだけの役の写しの比べもここ）で渡す"""
    return rolekit.main_accept(_pass(n)["review"], take=lambda board, reply, repo: accept_review(
        reply, board, os.environ.get("INPUTS_BASE_REV", ""), repo, n=n))


def main_accept_fix(n: int) -> int:
    """手直しの受け付けのスクリプトの入口（rolekit.main_accept。3 回目の拒否で done・give_up。R50）。盤面へは accept_fix
    （書き込みの記録との突き合わせつき）で渡す。版は節の入力 INPUTS_BASE_REV（空なら盤面の review_rev）"""
    return rolekit.main_accept(_pass(n)["fix"], take=lambda board, reply, repo: accept_fix(
        reply, board, os.environ.get("INPUTS_BASE_REV", ""), repo, n=n))


# ---------------------------------------------------------------- 分かれ道・出口
def route(board: pathlib.Path) -> dict:
    """blk-refix の分かれ道。review2・refix2 は盤面にその節の待っている instance が在るか（settle が条件で出した物）。
    owed・owed2 は今の周の義務の数。止めた run・人に聞いている run はどちらも偽"""
    b = entry.open_board(board, allow_halted=True)
    live = not b.state.get("halted") and not b.state.get("pending_human")
    return {"review2": bool(live and _pending(b, _pass(2)["review"])),
            "refix2": bool(live and _pending(b, _pass(2)["fix"])),
            "owed": len(_owed_rows(b, 1)), "owed2": len(_owed_rows(b, 2))}


def _reads_file(b, role) -> str:
    p = b.work(reads.evidence_name(role))
    return str(p) if p.is_file() else ""


def collect_delta(board: pathlib.Path) -> dict:
    """blk-delta の出口。1 本目の {ok, faces, review_file, diff_file} に owed（手直しが答える義務の数）・fix_rev（修正後に固めた版）・
    reads_file を足す。審査の返答が今の周に受けられていないのは、3 回とも拒まれた時（rolekit.gave_up が盤面を止め、ok: false・
    faces 0）か、配線の誤り（拒否が足りない。BoardGap）"""
    p = _pass(1)
    b = entry.open_board(board, allow_halted=True)
    out = b.output_of_round(p["review"], b.round)
    d = _in_round(b, b.loop_state.get(p["state_key"])) or {}
    if out is None:
        if not rolekit.gave_up(board, p["review"], by=stopby.DELTA):
            raise BoardGap(f"今の周に {p['review']} の受け付けた返答が無い（前の周・前の試みの返答は数えない）")
        return {"ok": False, "faces": 0, "review_file": "", "diff_file": d.get("file") or "", "owed": 0,
                "fix_rev": d.get("rev") or "", "reads_file": _reads_file(b, REVIEW_ROLE[1])}
    return {"ok": True, "faces": len(out.get("faces") or []), "review_file": _out_file(b, p["review"]),
            "diff_file": d.get("file") or "", "owed": len(_owed_rows(b, 1)), "fix_rev": d.get("rev") or "",
            "reads_file": _reads_file(b, REVIEW_ROLE[1])}


def collect_refix(board: pathlib.Path) -> dict:
    """blk-refix の出口 {ok, handled_file, review2_file, owed2, fixed2, files, reads_file}。review2_file は 2 回目の審査を
    回さなかった run では空。fixed2 は 2 回目の手直しが fixed と言った穴の数（次の run の依頼の下書きへ。T15）。files は
    手直し 2 回が fixed と言った行の files の和。reads_file は手直しの役の読んだ証拠（無ければ空）で、全部の役の分は
    reads_files。手直し 1・審査 2・手直し 2 のどれかが 3 回とも拒まれて輪を抜けたら、rolekit.gave_up が盤面を止めて ok: false。
    手直しの返答が今の周に受けられておらず、拒否も足りなければ BoardGap（配線の誤り）"""
    p1, p2 = _pass(1), _pass(2)
    b = entry.open_board(board, allow_halted=True)
    h1 = b.output_of_round(p1["fix"], b.round)
    gave = [nid for nid in (p1["fix"], p2["review"], p2["fix"])
            if b.output_of_round(nid, b.round) is None and rolekit.gave_up(board, nid, by=stopby.REFIX)]
    if h1 is None and not gave:
        raise BoardGap(f"今の周に {p1['fix']} の受け付けた返答が無い")
    h2 = b.output_of_round(p2["fix"], b.round) or {}
    fixed = [r for h in (h1 or {}, h2) for r in h.get("handled") or [] if r.get("handled") == "fixed"]
    roles = [REVIEW_ROLE[2], FIX_ROLE[1], FIX_ROLE[2]]
    return {"ok": not gave, "handled_file": _out_file(b, p1["fix"]), "review2_file": _out_file(b, p2["review"]),
            "owed2": len(_owed_rows(b, 2)),
            "fixed2": sum(1 for r in h2.get("handled") or [] if r.get("handled") == "fixed"),
            "files": sorted({f for r in fixed for f in r.get("files") or []}),
            "reads_file": _reads_file(b, FIX_ROLE[1]),
            "reads_files": {r: _reads_file(b, r) for r in roles if _reads_file(b, r)}}


def must(board: pathlib.Path, role: str) -> list:
    """役 role に機械が渡したパス（支度が書いた brief と、その差分のファイルと、審査役の座のファイル・組んだ指示書が在ればそれ）。
    支度が走っていなければ空"""
    b = entry.open_board(board, allow_halted=True)
    name = next((f"review{n}-brief.json" for n, r in REVIEW_ROLE.items() if r == role), None) \
        or next((f"refix{n}-brief.json" for n, r in FIX_ROLE.items() if r == role), None)
    if name is None:
        raise BoardGap(f"役 {role!r} は差分の往復の役でない")
    p = b.work(name)
    if not p.is_file():
        return []
    doc = json.loads(p.read_text(encoding="utf-8"))
    diff, seat_file = doc.get("diff_file") or "", doc.get("seat_file") or ""
    fix = next((_pass(n)["fix"] for n, r in FIX_ROLE.items() if r == role), None)
    composed = b.work(rolekit.prompt_name(fix)) if fix else None
    return ([str(p)] + ([diff] if diff else []) + ([seat_file] if seat_file else [])
            + ([str(composed)] if composed and composed.is_file() else []))


def reads_all(board: pathlib.Path, reads_mod, run_id: str) -> dict:
    """blk-refix の節 refix-reads: この周に受けた手直し・2 回目の審査の役ごとに、読んだ証拠を reads_mod（Task 6 の reads）の
    collect で書く（受け付けの条件にはしない）。機械が渡したパスは must（支度の brief と差分）。出来事は run_id が在れば
    reads_mod.events_for。返り {ok: True, reads_files: {役: reads_file}}（回さなかった役は載らない）"""
    b = entry.open_board(board, allow_halted=True)
    p1, p2 = _pass(1), _pass(2)
    ran = [role for role, nid in ((FIX_ROLE[1], p1["fix"]), (REVIEW_ROLE[2], p2["review"]), (FIX_ROLE[2], p2["fix"]))
           if b.output_of_round(nid, b.round) is not None]
    events = reads_mod.events_for(run_id) if run_id else None
    files = {}
    for role in ran:
        _, loop, node = READS[role]
        got = reads_mod.collect(board, role, reads_mod.node_here(loop, node), must(board, role), events)
        files[role] = got.get("reads_file", "")
    return {"ok": True, "reads_files": files}


def own_module(mod, script: str) -> bool:
    """import した reads が core の物でなくスクリプト自身か（core に reads.py が無いと、スクリプトのフォルダの reads.py を拾う。
    台帳 R7 の罠）。真なら呼び手は 2 で止まる"""
    return pathlib.Path(getattr(mod, "__file__", "") or "").resolve() == pathlib.Path(script).resolve()


# ---------------------------------------------------------------- スクリプトの入口
# blk-delta・blk-refix の受け付けでないスクリプトの入口（rolekit.script_main）。返りが {ok: False}（支度が盤面に要る物を
# 見つけない＝配線の誤り）も 2（役に返しても直らない。TA19）
script_main = functools.partial(rolekit.script_main, not_ok_is_wiring=True)


def pass_of(raw: str) -> int:
    """INPUTS_PASS の値（"1" か "2"）を往復の番号に。読めなければ BoardGap（配線の誤り）"""
    try:
        n = int(str(raw).strip())
    except ValueError:
        raise BoardGap(f"INPUTS_PASS {raw!r} が往復の番号でない（{sorted(passes())}）") from None
    _pass(n)
    return n
