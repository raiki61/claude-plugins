"""差分の審査（blk-delta）と 2 往復の手直し（blk-refix）の口（線 A の仕様 3.3・3.4。計画 Task 13）。

版を固める・差分を切る・義務を組むのは盤面の機械の節（写しの RL の fix_delta・delta_owed。DELTA_PASSES の cut・owed）で、
役の返答を受けた後の settle が回す。ここは盤面が書いた物を役に見せ、役の返答を盤面に渡し、盤面から出口を組むだけ。
節の名前は写しの RL の DELTA_PASSES からだけ引く（passes()。works に名前の写しを持たない。仕様 7 節）。

- passes():                  {n: {cut, review, owed, fix, state_key, owed_key}}（写しの DELTA_PASSES から）
- cut(board, n, repo):       n 回目の審査役を起こす前の支度。盤面の loop.<state_key>（今の周）の差分のファイルと触ったファイルを
                             返し、役に見せる材料（brief）を書き、読むだけの役の前の作業ツリーの写しを撮り、起こした印を置く
- prep_fix(board, n, repo):  n 回目の手直しの役を起こす前の支度。義務（loop.<owed_key>）と差分のパスを brief に書き、印を置く
- accept_review・accept_fix: 役の返答を盤面に渡す（entry.take。審査は読むだけの役の写しと比べる）
- route(board):              blk-refix の分かれ道 {review2, refix2, owed, owed2}（盤面の待っている節と義務の数）
- collect_delta・collect_refix: 出口（1 本目の欄を全部残して足す）
- must(board, role):         読んだ証拠（reads）に渡す「機械が渡したパス」（brief と差分のファイル）
- script_main(fn, inputs):   ブロックのスクリプトの入口（配線の誤りは標準エラーに 1 行で 2。TA19）

作業ファイル（b.work。今の周の r<N>/。周の番号を仮定しない。TA17）: review<n>-snapshot.json（計画の予約の名）・
review<n>-brief.json・refix<n>-brief.json（役に見せる材料: graph がその節に読ませる盤面の値と、人の方針 policy.brief の
{paste, path}。審査役の brief には、変わったファイルのうち守りのファイル（protect.hits）の protected_files も。1 本目の blk-delta の YAML は入口 policy_paste を持たないので、審査役へは方針の本文をこの brief で届ける）。
支度は前の試みの自分の出力（brief・reads-<役>.json・1 本目の blk-delta が盤面の根に書いた delta-review.json・fix.diff・
delta-snapshot.json）を先に消す——新しい審査の出口が前の審査の穴を数えない（darkfactory の自分食いで 1 本目の blk-delta が
踏んだ形）。出口は盤面の今の周の出力（output_of_round）だけを読む。
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

from board import BoardGap, rules_module  # noqa: E402
import engine.util as _util  # noqa: E402
import accept  # noqa: E402
import entry  # noqa: E402
import node_marker  # noqa: E402
import policy  # noqa: E402
import protect  # noqa: E402
import rolekit  # noqa: E402

PASS_KEYS = ("cut", "review", "owed", "fix", "state_key", "owed_key")
REVIEW_ROLE = {1: "review", 2: "review2"}   # 審査役の名（印 works-node の名・reads-<役>.json）
FIX_ROLE = {1: "refix", 2: "refix2"}        # 手直しの役の名
# blk-refix の中の輪（T17 で YAML に書く。輪の中の id は全部の include をまたいで一意。台帳 R19）
LOOPS = {"refix-loop": ("refix", "refix-accept"), "review2-loop": ("review2", "review2-accept"),
         "refix2-loop": ("refix2", "refix2-accept")}
# 読んだ証拠の節（reads.main_for の引数: 役・ラインの include の id・輪・節。Task 6 の reads.py の口。include の id は仕様 2 節の
# ライン（reviewing・refixing）の名）
READS = {"review": ("review", "reviewing", "delta-loop", "review"),
         "refix": ("refix", "refixing", "refix-loop", "refix"),
         "review2": ("review2", "refixing", "review2-loop", "review2"),
         "refix2": ("refix2", "refixing", "refix2-loop", "refix2")}
# 1 本目の blk-delta が盤面の根に書いた物（2 本目は書かない。残っていれば前の試みの出力なので支度が消す）
V1_OUTPUTS = (accept.DELTA_REVIEW_FILE, accept.DIFF_FILE, accept.SNAPSHOT_FILE)


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
    """役の節の output_format（T17 で YAML に貼る値。TA20）: mark(role_schema(節), 役の名)"""
    node = {**{r: _pass(n)["review"] for n, r in REVIEW_ROLE.items()},
            **{r: _pass(n)["fix"] for n, r in FIX_ROLE.items()}}.get(role)
    if node is None:
        raise BoardGap(f"役 {role!r} は差分の往復の役でない（{sorted(REVIEW_ROLE.values()) + sorted(FIX_ROLE.values())}）")
    return node_marker.mark(accept.role_schema(node), role)


# ---------------------------------------------------------------- 盤面の読み
def _in_round(b, v):
    """周に属する loop 値（{round, …}）を今の周の物だけ（前の周の値は None）"""
    return v if isinstance(v, dict) and v.get("round") == b.round else None


def _pending(b, nid):
    return next((i for i in b.rd["instances"].values() if i["node"] == nid and i["status"] == "pending"), None)


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


def _write_json(path: pathlib.Path, doc) -> pathlib.Path:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)
    return path


def _drop_stale(b, *names, root=()):
    """前の試みの自分の出力を消す（今の周の作業ファイルの names と、盤面の根の root）"""
    for p in [b.work(x) for x in names] + [b.dir / x for x in root]:
        p.unlink(missing_ok=True)


# ---------------------------------------------------------------- 支度（役を起こす前）
def cut(board: pathlib.Path, n: int, repo: pathlib.Path) -> dict:
    """n 回目の差分の審査役を起こす前の支度。盤面の loop.<state_key> が今の周に無い・審査の節が待っていないなら
    {ok: False, reason}（配線の誤り。スクリプトは 2）。在れば、前の試みの自分の出力を消し、役に見せる材料を
    review<n>-brief.json に書き、作業ツリーの写し（review<n>-snapshot.json）を撮り、起こした印を置いて
    {ok: True, files, diff_file, rev, brief_file, must} を返す。名前は盤面の値のまま（組み立てない）"""
    p = _pass(n)
    b = entry.open_board(board)
    d = _in_round(b, b.loop_state.get(p["state_key"]))
    if not d or not d.get("file"):
        return {"ok": False, "reason": f"盤面に今の周の loop.{p['state_key']} が無い（{p['cut']} が差分を切っていない）"}
    inst = _pending(b, p["review"])
    if inst is None:
        return {"ok": False, "reason": f"この周に {p['review']} が待っていない（盤面の ready に無い節の役は起こさない）"}
    role = REVIEW_ROLE[n]
    brief_name = f"review{n}-brief.json"
    _drop_stale(b, brief_name, f"reads-{role}.json", root=V1_OUTPUTS if n == 1 else ())
    doc = {"node": p["review"], "diff_file": d["file"], "files": d.get("files") or [], "rev": d.get("rev"),
           "reads": _brief(b, p["review"]), "policy": policy.brief(b)}
    try:   # 変わったファイルのうち守りのファイル（protect）。審査役が検査を緩める変更を見る材料（最後の人の関所にも必ず出る）
        doc["protected_files"] = protect.hits(doc["files"])
    except protect.Broken as e:
        doc["protected_files"], doc["protected_files_error"] = [], str(e)
    brief = _write_json(b.work(brief_name), doc)
    entry.snapshot(board, snapshot_name(n), repo)
    b.mark_launched(p["review"], inst.get("attempts", 1))
    return {"ok": True, "files": list(d.get("files") or []), "diff_file": d["file"], "rev": d.get("rev") or "",
            "brief_file": str(brief), "must": [str(brief), d["file"]]}


def prep_fix(board: pathlib.Path, n: int, repo: pathlib.Path) -> dict:
    """n 回目の手直しの役を起こす前の支度。手直しの節が待っていない・義務が今の周に無いなら {ok: False, reason}
    （配線の誤り）。在れば前の試みの自分の出力を消し、義務と差分のパスを refix<n>-brief.json に書き、起こした印を置いて
    {ok: True, owed, diff_file, brief_file, must} を返す"""
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
    _drop_stale(b, brief_name, f"reads-{role}.json")
    brief = _write_json(b.work(brief_name), {"node": p["fix"], "diff_file": d.get("file") or "", "owed": rows,
                                             "reads": _brief(b, p["fix"]), "policy": policy.brief(b)})
    b.mark_launched(p["fix"], inst.get("attempts", 1))
    return {"ok": True, "owed": len(rows), "diff_file": d.get("file") or "", "brief_file": str(brief),
            "must": [str(brief)] + ([d["file"]] if d.get("file") else [])}


# ---------------------------------------------------------------- 受け付け
def accept_review(reply: dict, board: pathlib.Path, base_rev: str, repo: pathlib.Path, *, n: int) -> dict:
    """n 回目の審査役の返答（読むだけの役。cut が撮った写しと今の作業ツリーを比べる）。entry.take の返り"""
    return entry.take(board, _pass(n)["review"], reply, repo, snapshot_name=snapshot_name(n))


def accept_fix(reply: dict, board: pathlib.Path, base_rev: str, repo: pathlib.Path, *, n: int) -> dict:
    """n 回目の手直しの役の返答（書く役）。entry.take の返り"""
    return entry.take(board, _pass(n)["fix"], reply, repo)


def main_accept_review(n: int) -> int:
    """審査の受け付けのスクリプトの入口（entry.main_take と同じ約束。中身の拒否は 0 と 1 行、配線の誤りは 2）"""
    return entry.main_take(_pass(n)["review"], snapshot_name=snapshot_name(n))


def main_accept_fix(n: int) -> int:
    """手直しの受け付けのスクリプトの入口"""
    return entry.main_take(_pass(n)["fix"])


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
    p = b.work(f"reads-{role}.json")
    return str(p) if p.is_file() else ""


def collect_delta(board: pathlib.Path) -> dict:
    """blk-delta の出口。1 本目の {ok, faces, review_file, diff_file} に owed（手直しが答える義務の数）・fix_rev（修正後に固めた版）・
    reads_file を足す。審査の返答が今の周に受けられていなければ BoardGap（輪は受け付けが通った時だけ抜ける＝壊れた run）"""
    p = _pass(1)
    b = entry.open_board(board, allow_halted=True)
    out = b.output_of_round(p["review"], b.round)
    if out is None:
        raise BoardGap(f"今の周に {p['review']} の受け付けた返答が無い（前の周・前の試みの返答は数えない）")
    d = _in_round(b, b.loop_state.get(p["state_key"])) or {}
    return {"ok": True, "faces": len(out.get("faces") or []), "review_file": _out_file(b, p["review"]),
            "diff_file": d.get("file") or "", "owed": len(_owed_rows(b, 1)), "fix_rev": d.get("rev") or "",
            "reads_file": _reads_file(b, REVIEW_ROLE[1])}


def collect_refix(board: pathlib.Path) -> dict:
    """blk-refix の出口 {ok, handled_file, review2_file, owed2, fixed2, files, reads_file}。review2_file は 2 回目の審査を
    回さなかった run では空。fixed2 は 2 回目の手直しが fixed と言った穴の数（次の run の依頼の下書きへ。T15）。files は
    手直し 2 回が fixed と言った行の files の和。reads_file は手直しの役の読んだ証拠（無ければ空）で、全部の役の分は
    reads_files。手直しの返答が今の周に受けられていなければ BoardGap"""
    p1, p2 = _pass(1), _pass(2)
    b = entry.open_board(board, allow_halted=True)
    h1 = b.output_of_round(p1["fix"], b.round)
    if h1 is None:
        raise BoardGap(f"今の周に {p1['fix']} の受け付けた返答が無い")
    h2 = b.output_of_round(p2["fix"], b.round) or {}
    fixed = [r for h in (h1, h2) for r in h.get("handled") or [] if r.get("handled") == "fixed"]
    roles = [REVIEW_ROLE[2], FIX_ROLE[1], FIX_ROLE[2]]
    return {"ok": True, "handled_file": _out_file(b, p1["fix"]), "review2_file": _out_file(b, p2["review"]),
            "owed2": len(_owed_rows(b, 2)),
            "fixed2": sum(1 for r in h2.get("handled") or [] if r.get("handled") == "fixed"),
            "files": sorted({f for r in fixed for f in r.get("files") or []}),
            "reads_file": _reads_file(b, FIX_ROLE[1]),
            "reads_files": {r: _reads_file(b, r) for r in roles if _reads_file(b, r)}}


def must(board: pathlib.Path, role: str) -> list:
    """役 role に機械が渡したパス（支度が書いた brief と、その差分のファイル）。支度が走っていなければ空"""
    b = entry.open_board(board, allow_halted=True)
    name = next((f"review{n}-brief.json" for n, r in REVIEW_ROLE.items() if r == role), None) \
        or next((f"refix{n}-brief.json" for n, r in FIX_ROLE.items() if r == role), None)
    if name is None:
        raise BoardGap(f"役 {role!r} は差分の往復の役でない")
    p = b.work(name)
    if not p.is_file():
        return []
    diff = json.loads(p.read_text(encoding="utf-8")).get("diff_file") or ""
    return [str(p)] + ([diff] if diff else [])


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
        _, include, loop, node = READS[role]
        got = reads_mod.collect(board, role, reads_mod.node_path(include, loop, node), must(board, role), events)
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
