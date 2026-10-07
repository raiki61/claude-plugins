"""範囲の相談の機械（blk-fix。持ち主 2026-10-06・2026-10-07。設計 docs/plans/2026-10-06-ask-planner.md）。

修正役（1 回目の fix と裁定の後の fix-ruled）は、承認済みの修正案の項目の範囲（allowed_paths）の外のファイルや、凍ったテストの
書き換えが要る時、返答の任意の欄 consult（conflict.CONSULT_SCHEMA。項目ごとに 1 件）に頼みを書いて周を終える。修正の輪
（blk-fix.yaml の fix-loop・fix-ruled-loop）は、その周の受け付けを回さずに次の 3 つの節で答える:

1. 頼みの節（scripts/consult_prep.py → ask）: 機械の先の確かめ（screen）で断る頼みを断り、残りを答えの節への指示書
   （QUESTION）に書く。相手の会話（入力 plan_session の印の名で包みが記録した会話の id）を、ブロックの中の名 PEER の id として
   包みの置き場へ写す（alias。ブロックはほかのブロックの節の名を YAML に書かない）。
2. 答えの節（AI。印 `works-node: <答えの節> continue=PEER`）: 修正案を書いた役の会話の続きで、読むだけの道具で答える
   （ANSWER_SCHEMA）。包みが PEER の id で `--resume` する。
3. 確かめの節（scripts/consult_check.py → settle）: 答えを確かめ（judge。許すのは頼んだ物の中だけ）、1 頼み 1 行を盤面の
   trace（conflict.ASKED_OP）に書き、修正役が読む答えのファイルを書く。合意（allow の行）は conflict.agreed が読み、範囲の
   照らし（planscope.with_agreed）とテストの変更の許し（conflict.test_permits）に入る。
修正案の項目の out_of_scope（案を書いた役が明示に外したパス）に当たる頼みも断らずに答えの節へ回す（持ち主 2026-10-07「相談で
考え直させる」。前は先の確かめで断り、run 54d81ef1 は CHANGELOG.md の 1 行で scope_needed → fix_plan_item → 修正案の直しの関所に
止まった）。指示書はその項目の out_of_scope の glob と外した理由を引き、ほかの項目の out_of_scope に当たるならその項目を名指して、
考え直して決めさせる。許せば、行の overrode_out_of_scope に外した物が残り、範囲の照らし（planscope.with_agreed）は許したパスと
字のまま同じパスに限ってその項目の out_of_scope を外す（ほかの項目の out_of_scope と守りのファイルは変えない）。
次の周の支度（fixrules.prep）は答えのファイルを名指す短い続きの指示書で、修正役を同じ会話の続きで起こす（印の旗 self-resume。
修正役の 2 回目は continue=fix）。どれも sandbox の外の機械の節で、役の Bash から claude を起こさない（Claude Code は Bash の子
から認証を外す。前の形 askplan.py が run 195h で 1 度も答えを得られなかった訳。設計の「前の形と退けた訳」）。

語:
- 状態（STATE。今の scope の周の作業ファイル、段ごと）: {turns, turn_state: asked|answered|delivered, rows, question_file,
  answer_file, session}。turns はこの段・この周の相談の回数（輪の周を 1 つずつ使う）
- 回数の枠（BUDGET）: 1 段の輪で相談に使える周の数。輪の上限 max_iterations は受け付けの 3 回（accept.GIVE_UP_AFTER）とこの枠の
  和で、枠を使い切った後の consult は受け付けが拒否の行にする（輪の上限で run を落とさない。R50）
- 相談の控え（CONFIG。run ごとの置き場の今の scope の下の PLACE）: 支度の節が書く {board, repo, scope, pass, base_rev, tdd_state,
  items}。修正役と下請けが Bash で回す事前の確かめ（factchecks.py）が読み、受け付けの拒否の文が相談を言うか（offered）を決める

口:
- items_doc(items)・items_of(b): 承認済みの修正案の項目 → 頼みを照らす表（番号の文字列 → {unit_keys, allowed_paths,
  out_of_scope（{glob, why} の並び）, tests}）
- requests(reply): 返答の consult の頼みの並び（欄が無ければ None）
- screen(items, item, paths, tests, why): 先の確かめ（断る文か None）
- oos_hits(items, item, paths, tests): 頼んだパスが当たる out_of_scope（その項目の物を先に、ほかの項目の物を後に）
- overrides(hits, item, granted_paths, granted_tests): 許した物のうち、その項目の out_of_scope を外した物
- judge(answer, paths, tests): 答えの 1 件の確かめ（(行の欄 | None, 注記)）
- question(items, asks): 答えの節の指示書の本文
- alias(repo, node, home_dir): 相手の会話の id を PEER の名で写す（読めなければ理由の文）
- ask(b, repo, reply, plan_session, pass_, node): 頼みの節の中身。返り {consulted, go, prompt_file, turn, spent}
- settle(b, answer, pass_, node): 確かめの節の中身。返り {consulted, turn, answer_file, counts}
- take(b, pass_): 支度の節が、まだ渡していない答えを引く（渡した印を付ける）。返り {turn, answer_file, left} か None
- write_config・load_config・place_of・offered: 相談の控え（事前の確かめのコマンドと受け付けの拒否の文）
"""
import collections
import datetime
import json
import os
import pathlib
import posixpath
import sys

sys.dont_write_bytecode = True   # 下の import が pack の中に __pycache__ を作らないように（必ず import より前）

_CORE = pathlib.Path(__file__).resolve().parents[2] / ".shared" / "core"
if str(_CORE) not in sys.path:
    sys.path.append(str(_CORE))

from board import BoardGap  # noqa: E402
import adapter  # noqa: E402   L2。包みの会話の id の置き場（session_path）と run ごとの置き場（run_place_of）
import conflict  # noqa: E402   範囲の相談の trace の行（ASKED_OP）と頼みの欄（CONSULT_FIELD）
import node_marker  # noqa: E402   答えの節の印
import planmarks  # noqa: E402   glob の当て方の正本・承認済みの修正案の項目
import script_io  # noqa: E402   L1。今の scope の根

PEER = "fix-planner"        # 答えの節が継ぐ会話のブロックの中の名（alias が入力 plan_session の会話の id をこの名で写す）
STATE = "consult-{pass_}.json"
QUESTION_FILE = "consult-{pass_}-{turn}-ask.md"
ANSWER_FILE = "consult-{pass_}-{turn}.md"
BUDGET = 9                  # 1 段の輪で相談に使える周の数（輪の max_iterations = 受け付けの 3 回 + BUDGET）
ASKED, ANSWERED_TURN, DELIVERED = "asked", "answered", "delivered"   # 状態の turn_state
REFUSED, ANSWERED, INVALID, UNAVAILABLE = "refused", "answered", "invalid", "unavailable"   # 行の status
ALLOW, DENY, DEFER = "allow", "deny", "defer"
DECISIONS = (ALLOW, DENY, DEFER)
MIN_WHY = conflict.CONSULT_MIN_WHY
CONFIG = "consult.json"
PLACE = "consult"           # run ごとの置き場の今の scope の下
NO_PEER = "相談の相手の会話が無い run（入力 plan_session が空）"

ANSWER_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "required": ["answers"],
    "properties": {
        "answers": {
            "type": "array", "minItems": 1,
            "items": {
                "type": "object", "additionalProperties": False,
                "required": ["ask", "decision", "paths", "tests", "spec", "reason"],
                "properties": {
                    "ask": {"type": "integer", "minimum": 1},
                    "decision": {"type": "string", "enum": list(DECISIONS)},
                    "paths": {"type": "array", "items": {"type": "string", "minLength": 1}},
                    "tests": {"type": "array", "items": {"type": "string", "minLength": 1}},
                    "spec": {"type": "string"},
                    "reason": {"type": "string", "minLength": MIN_WHY},
                },
            },
        },
    },
}


def answer_format(name: str) -> dict:
    """答えの節 name の output_format（ANSWER_SCHEMA に印 `works-node: <name> continue=PEER`。blk-fix.yaml に貼る物）"""
    return node_marker.mark(ANSWER_SCHEMA, name, cont=PEER)


QUESTION = """\
# 範囲の相談（修正の段から）

あなたがこの会話で書いた修正案を、別の役が直している。直している側から、範囲の相談が {n} 件来た。範囲を広げるかは仕様の判断で、
決めるのはあなた。案を書いた時の考えと、今のリポジトリ（Read・Grep・Glob で読める。書く道具は無い）で決めよ。
頼んだパスが out_of_scope（触らない物）に当たる相談には、当たる glob と外した理由を並べてある。あなたがこの項目の out_of_scope に
書いた物なら、外した理由が今も立つかを直している側の理由と比べて考え直せ: allow なら、この項目ではそのパスだけ out_of_scope から
外れて範囲に入る。理由が今も立つなら deny。ほかの項目の out_of_scope に当たる物を allow すると、この項目の単位の変更としてだけ
通る（その項目の out_of_scope は変わらない）。

{asks}

答えは次の JSON だけ（`answers` に相談の番号ごとに 1 件。番号は上の「相談 <番号>」）:
- ask: 相談の番号
- decision: allow（範囲に足してよい）・deny（足さない。範囲の中で直せ）・defer（今の run では直さない。次の run の仕事）
- paths: 足してよいパス（頼まれた物の中から。allow の時だけ。頼まれていない物は機械が捨てる）
- tests: 書き換えてよいテストの範囲（頼まれた物の中から。allow の時だけ。期待を実装に合わせるための書き換えは許すな）
- spec: 直す側が従う仕様の補い（無ければ空）
- reason: 決めた理由（{min_why} 字以上）
"""

ASK_TEXT = """\
## 相談 {n}: 項目 {item}（単位: {units}）

- 項目の今の範囲（allowed_paths）: {allowed}
- 触らない物（out_of_scope）: {oos}
- 足したいパス: {paths}
- 書き換えたい既存のテストの範囲（<パス> か <パス>:<行>）: {tests}
{oos_hits}- 理由（直している側の文）:
{why}
"""

ANSWER_HEAD = """\
# 範囲の相談の答え（相談の周 {turn}）

前の返答の consult に、修正案を書いた役が答えた（機械が確かめて盤面に残した）。相談ごとの答え:
"""


def _now() -> str:
    return datetime.datetime.now().astimezone().isoformat(timespec="seconds")


def _norm(p: str) -> str:
    return posixpath.normpath(str(p).strip())


def _limit_path(lim: str) -> str:
    """テストの範囲 <パス>[:<行>[-<行>]] のパス"""
    head, sep, tail = lim.rpartition(":")
    return _norm(head) if sep and tail.replace("-", "").isdigit() else _norm(lim)


def _oos_rows(it: dict) -> list:
    """項目の out_of_scope の (glob, 外した理由) の並び（items_doc の {glob, why} の行。glob だけの文字列の行も読む）"""
    out = []
    for r in it.get("out_of_scope") or []:
        g, why = (r.get("glob"), r.get("why")) if isinstance(r, dict) else (r, "")
        if isinstance(g, str) and g:
            out.append((g, why if isinstance(why, str) else ""))
    return out


def _write_json(path: pathlib.Path, doc) -> None:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(doc, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    os.replace(str(tmp), str(path))


def _read_json(path: pathlib.Path):
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError):
        return None
    return doc if isinstance(doc, dict) else None


# ---------------------------------------------------------------- 項目と頼み
def items_doc(items) -> dict:
    """承認済みの修正案の項目 → 頼みを照らす表（番号の文字列 → {unit_keys, allowed_paths, out_of_scope の glob, tests の
    ファイル（planmarks.test_paths）}）"""
    return {str(it["item"]): {"unit_keys": [k for k in it.get("unit_keys") or [] if isinstance(k, str)],
                              "allowed_paths": [g for g in it.get("allowed_paths") or [] if isinstance(g, str) and g],
                              "out_of_scope": [{"glob": g, "why": w} for g, w in _oos_rows(it)],
                              "tests": planmarks.test_paths(it)}
            for it in items or []}


def items_of(b) -> dict:
    """盤面の今の周の承認済みの修正案の項目の表（items_doc）。案の無い run・控えが壊れていれば {}（頼みは全部断る）"""
    try:
        return items_doc(planmarks.approved_items(b) or [])
    except (planmarks.FieldsBroken, BoardGap, OSError, ValueError):
        return {}


def requests(reply):
    """返答の consult の頼みの並び [{item, paths, tests, why}]（欄が無い・空の配列なら None）。形の崩れた行は欄を空にして残す
    （screen が断る）"""
    rows = reply.get(conflict.CONSULT_FIELD) if isinstance(reply, dict) else None
    if rows is None or rows == []:
        return None
    if not isinstance(rows, list):
        rows = [rows]
    out = []
    for r in rows:
        r = r if isinstance(r, dict) else {}
        strs = lambda v: [str(x).strip() for x in v if isinstance(x, (str, int)) and str(x).strip()] if isinstance(v, list) else []  # noqa: E731
        item = r.get("item")
        out.append({"item": str(item) if isinstance(item, (str, int)) and not isinstance(item, bool) else "",
                    "paths": strs(r.get("paths")), "tests": strs(r.get("tests")),
                    "why": r.get("why").strip() if isinstance(r.get("why"), str) else ""})
    return out


def _inside(path: str, it: dict) -> bool:
    """path が項目の範囲（tests のファイル・allowed_paths）に入り、その項目の out_of_scope に当たらない（当たれば受け付けが拒むので、
    範囲の中に数えない）"""
    if any(planmarks.glob_match(path, g) for g, _ in _oos_rows(it)):
        return False
    return path in [_norm(t.split("::")[0]) for t in it.get("tests") or []] or \
        any(planmarks.glob_match(path, g) for g in it.get("allowed_paths") or [])


def screen(items: dict, item: str, paths: list, tests: list, why: str = "x" * MIN_WHY):
    """AI に聞く前に断る文（通れば None）: 知らない項目・頼む物が無い・理由が短い・根の外のパス・足したいパスがもう範囲の中。
    out_of_scope に当たるパスは断らない（答えの節が考え直す。oos_hits が指示書と行に当たりを名指す）"""
    it = items.get(str(item))
    if it is None:
        return f"項目 {item or '（無し）'} は承認済みの修正案に無い（在る項目: {sorted(items)}）"
    if not paths and not tests:
        return "足したいパスも書き換えたいテストも無い（何も頼んでいない）"
    if len((why or "").strip()) < MIN_WHY:
        return f"理由（why）が無いか {MIN_WHY} 字に満たない（相手が仕様として判断できる理由を書け）"
    for p in [_norm(x) for x in paths] + [_limit_path(x) for x in tests]:
        if planmarks.climbs(p) or p.startswith("/"):
            return f"{p} はリポジトリの根の外（根からの相対パスで頼め）"
    inside = [p for p in (_norm(x) for x in paths) if _inside(p, it)]
    if inside and not tests and len(inside) == len(paths):
        return f"{inside} はもう項目 {item} の範囲の中（聞かずに直してよい）"
    return None


def _asked_paths(paths: list, tests: list) -> list:
    """頼んだパスとテストの範囲のパス（整えて重ねない）"""
    return list(dict.fromkeys([_norm(x) for x in paths] + [_limit_path(x) for x in tests]))


def oos_hits(items: dict, item: str, paths: list, tests: list) -> list:
    """頼んだパス（paths とテストの範囲のパス）が当たる out_of_scope の行 [{path, item, glob, why}]。パスごとに、頼んだ項目の物を
    先に、ほかの項目の物を項目の順に、項目ごとに最初の glob で 1 行"""
    item = str(item)
    order = [item] + [k for k in items if k != item]
    out = []
    for p in _asked_paths(paths, tests):
        for k in order:
            hit = next(((g, w) for g, w in _oos_rows(items.get(k) or {}) if planmarks.glob_match(p, g)), None)
            if hit:
                out.append({"path": p, "item": k, "glob": hit[0], "why": hit[1]})
    return out


def overrides(hits: list, item: str, granted_paths: list, granted_tests: list) -> list:
    """許した物（granted_paths とテストの範囲のパス）のうち、頼んだ項目 item の out_of_scope に当たっていた物
    [{path, glob, why}]（答えの節が考え直して外した物。ほかの項目の out_of_scope の当たりは入れない）"""
    got = set(_asked_paths(granted_paths, granted_tests))
    return [{"path": h["path"], "glob": h["glob"], "why": h["why"]} for h in hits
            if h.get("item") == str(item) and h.get("path") in got]


def _hits_text(hits: list, item: str) -> str:
    """指示書の相談の節の out_of_scope の当たりの行（無ければ空）"""
    if not hits:
        return ""
    lines = ["- out_of_scope に当たる頼み（外した理由が今も立つかを考え直して決めよ）:"]
    for h in hits:
        why = h.get("why") or "（記録なし）"
        if h["item"] == str(item):
            lines.append(f"  - {h['path']}: あなたがこの項目の out_of_scope に書いた物（glob {h['glob']}。外した理由: {why}）")
        else:
            lines.append(f"  - {h['path']}: 項目 {h['item']} の out_of_scope（{h['glob']}。外した理由: {why}）——ほかの項目が"
                         "触らないとした物")
    return "\n".join(lines) + "\n"


def judge(answer, paths: list, tests: list):
    """答えの 1 件の確かめ。返り (行の欄 {decision, granted_paths, granted_tests, spec, reason} | None, 注記の文の列)。
    allow は頼んだ物の中だけを許し（足した物は捨てて注記）、何も残らなければ形の崩れ。deny・defer は何も許さない"""
    if not isinstance(answer, dict):
        return None, ["答えが無いか JSON のオブジェクトでない"]
    d, reason = answer.get("decision"), answer.get("reason")
    notes = []
    if d not in DECISIONS:
        notes.append(f"decision が {list(DECISIONS)} のどれでもない: {d!r}")
    if not isinstance(reason, str) or len(reason.strip()) < MIN_WHY:
        notes.append(f"reason が無いか {MIN_WHY} 字に満たない")
    if notes:
        return None, notes
    out = {"decision": d, "granted_paths": [], "granted_tests": [], "spec": answer.get("spec") or "", "reason": reason}
    if d != ALLOW:
        return out, []
    want_p, want_t = [_norm(p) for p in paths], [str(t).strip() for t in tests]
    for field, want, key in (("paths", want_p, "granted_paths"), ("tests", want_t, "granted_tests")):
        for x in answer.get(field) or []:
            x = _norm(x) if field == "paths" else str(x).strip()
            if x in want:
                if x not in out[key]:
                    out[key].append(x)
            else:
                notes.append(f"頼んでいない {field} の {x} を許した答え（捨てた）")
    if not out["granted_paths"] and not out["granted_tests"]:
        return None, notes + ["allow なのに頼んだ物の中で許した物が無い"]
    return out, notes


def question(items: dict, asks: list) -> str:
    """答えの節の指示書の本文（asks は screen を通った頼みの行 {n, item, paths, tests, why}。out_of_scope の当たり（oos_hits の行）を
    持たなければ、ここで引く）"""
    show = lambda xs: "・".join(xs) if xs else "（無し）"   # noqa: E731
    parts = []
    for a in asks:
        it = items.get(a["item"]) or {}
        oos = [f"{g}（{w}）" if w else g for g, w in _oos_rows(it)]
        hits = a.get("out_of_scope")
        hits = oos_hits(items, a["item"], a["paths"], a["tests"]) if hits is None else hits
        parts.append(ASK_TEXT.format(n=a["n"], item=a["item"], units=show(it.get("unit_keys") or []),
                                     allowed=show(it.get("allowed_paths") or []), oos=show(oos),
                                     paths=show(a["paths"]), tests=show(a["tests"]), oos_hits=_hits_text(hits, a["item"]),
                                     why="\n".join("  " + line for line in a["why"].splitlines())))
    return QUESTION.format(n=len(asks), asks="\n".join(parts).rstrip("\n"), min_why=MIN_WHY)


# ---------------------------------------------------------------- 相手の会話
def alias(repo, node: str, home_dir=None):
    """包みが記録した会話 node の id（adapter.session_path(repo, node)）を、PEER の名で同じ置き場に写す（答えの節の印は
    continue=PEER）。写せれば (None, id)、node が空・id が無い・写せなければ (理由の文, None)"""
    node = (node or "").strip()
    if not node:
        return NO_PEER, None
    src = adapter.session_path(repo, node, home_dir)
    sid = adapter.read_session_id(src)
    if sid is None:
        return f"相談の相手の会話 {node} の id が包みの置き場に無い（{src}）", None
    dest = adapter.session_path(repo, PEER, home_dir)
    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_name(f"{dest.name}.{os.getpid()}.tmp")
        tmp.write_text(sid + "\n", encoding="utf-8")
        os.replace(str(tmp), str(dest))
    except OSError as e:
        return f"相談の相手の会話の id を {dest} に写せない（{e}）", None
    return None, sid


# ---------------------------------------------------------------- 状態
def state_path(b, pass_: str) -> pathlib.Path:
    return b.work(STATE.format(pass_=pass_))


def state(b, pass_: str) -> dict:
    """段 pass_ の今の周の状態（無ければ {turns: 0}）"""
    return _read_json(state_path(b, pass_)) or {"turns": 0}


def left(b, pass_: str) -> int:
    """この段・この周で相談に使える残りの周の数"""
    return max(0, BUDGET - int(state(b, pass_).get("turns") or 0))


# ---------------------------------------------------------------- 3 つの節の中身
def ask(b, repo, reply, plan_session: str, pass_: str, node: str, home_dir=None) -> dict:
    """頼みの節。返答に consult が無ければ {consulted: false, go: false}。枠を使い切っていれば {consulted: false, spent: true}
    （受け付けが拒否の行にする）。在れば頼みごとに先の確かめをして状態に積み、聞く頼みが在れば相手の会話を写して答えの節の指示書を
    書く（go: true）。聞く頼みが無い・相手の会話を写せなければ go: false（確かめの節が断った・聞けなかった行を書く）"""
    asks = requests(reply)
    if asks is None:
        return {"consulted": False, "go": False, "prompt_file": "", "turn": 0, "spent": False}
    st = state(b, pass_)
    turns = int(st.get("turns") or 0)
    if turns >= BUDGET:
        return {"consulted": False, "go": False, "prompt_file": "", "turn": turns, "spent": True}
    turn = turns + 1
    items = items_of(b)
    rows = []
    for n, a in enumerate(asks, 1):
        why = screen(items, a["item"], a["paths"], a["tests"], a["why"])
        hits = oos_hits(items, a["item"], a["paths"], a["tests"]) if a["item"] in items else []
        rows.append({**a, "n": n, "out_of_scope": hits,
                     **({"status": REFUSED, "why_refused": why} if why else {"status": ASKED})})
    asked = [r for r in rows if r["status"] == ASKED]
    session, qfile = None, ""
    if asked:
        err, sid = alias(repo, plan_session, home_dir)
        if err:
            for r in asked:
                r.update(status=UNAVAILABLE, why_unavailable=err)
            asked = []
        else:
            session = {"of": plan_session.strip(), "id": sid, "as": PEER}
    if asked:
        path = b.work(QUESTION_FILE.format(pass_=pass_, turn=turn))
        path.write_text(question(items, asked), encoding="utf-8")
        qfile = str(path)
    _write_json(state_path(b, pass_), {"turns": turn, "turn_state": ASKED, "rows": rows, "question_file": qfile,
                                       "session": session, "node": node, "items": items})
    return {"consulted": True, "go": bool(asked), "prompt_file": qfile, "turn": turn, "spent": False}


def settle(b, answer, pass_: str, node: str) -> dict:
    """確かめの節。状態が asked でなければ {consulted: false}（頼みの無い周）。答え（答えの節の出力。飛ばされたら None）を頼みごとに
    確かめ、1 頼み 1 行を trace（conflict.ASKED_OP）に書き、答えのファイルを書いて状態を answered にする"""
    st = state(b, pass_)
    if st.get("turn_state") != ASKED:
        return {"consulted": False, "turn": 0, "answer_file": "", "counts": {}}
    turn = int(st.get("turns") or 0)
    got = answer.get("answers") if isinstance(answer, dict) else None
    by_n = {}
    for a in got if isinstance(got, list) else []:
        if isinstance(a, dict) and isinstance(a.get("ask"), int) and a["ask"] not in by_n:
            by_n[a["ask"]] = a
    known = [r.get("id") for r in conflict.plan_asks(b) if isinstance(r.get("id"), int)]
    next_id = 1 + max(known, default=0)
    out_rows = []
    for r in st.get("rows") or []:
        it = (st.get("items") or {}).get(r.get("item")) or {}
        row = {"id": next_id, "at": _now(), "turn": turn, "pass": pass_, "round": b.round, "node": node,
               "item": r.get("item"), "unit_keys": list(it.get("unit_keys") or []), "paths": r.get("paths") or [],
               "tests": r.get("tests") or [], "why": r.get("why") or "", "status": r.get("status"), "decision": None,
               "granted_paths": [], "granted_tests": [], "spec": "", "reason": "", "notes": [],
               "out_of_scope": list(r.get("out_of_scope") or []), "overrode_out_of_scope": [],
               "session": st.get("session")}
        next_id += 1
        if r.get("status") == ASKED:
            if answer is None:
                row.update(status=UNAVAILABLE, why_unavailable="答えの節が答えを返さなかった（飛ばされたか落ちた）")
            else:
                fields, notes = judge(by_n.get(r["n"]), row["paths"], row["tests"])
                row.update(notes=notes)
                row.update({**fields, "status": ANSWERED} if fields is not None else {"status": INVALID})
                if fields is not None and fields["decision"] == ALLOW:
                    row["overrode_out_of_scope"] = overrides(row["out_of_scope"], row["item"], fields["granted_paths"],
                                                             fields["granted_tests"])
        else:
            row.update({k: r[k] for k in ("why_refused", "why_unavailable") if r.get(k)})
        b.trace(conflict.ASKED_OP, **row)
        out_rows.append(row)
    path = b.work(ANSWER_FILE.format(pass_=pass_, turn=turn))
    path.write_text(answer_text(turn, out_rows), encoding="utf-8")
    _write_json(state_path(b, pass_), {**st, "turn_state": ANSWERED_TURN, "answer_file": str(path),
                                       "ids": [r["id"] for r in out_rows]})
    counts = collections.Counter(r["decision"] if r["status"] == ANSWERED else r["status"] for r in out_rows)
    return {"consulted": True, "turn": turn, "answer_file": str(path), "counts": dict(counts)}


def answer_text(turn: int, rows: list) -> str:
    """修正役が読む答えのファイルの本文（相談ごとに 1 節）"""
    lines = [ANSWER_HEAD.format(turn=turn)]
    for r in rows:
        head = f"## 相談（項目 {r.get('item') or '（無し）'}・パス {('・'.join(r.get('paths') or [])) or '（無し）'}・テスト " \
               f"{('・'.join(r.get('tests') or [])) or '（無し）'}）"
        if r["status"] == ANSWERED:
            body = [f"- 答え: {r['decision']}"]
            if r["decision"] == ALLOW:
                body.append(f"- 範囲に入った物: パス {('・'.join(r['granted_paths'])) or '（無し）'}・テスト "
                            f"{('・'.join(r['granted_tests'])) or '（無し）'}（受け付けはこれを範囲に入れる。頼んだ物の残りは入らない）")
            if r.get("overrode_out_of_scope"):
                body.append("- out_of_scope を外した（この項目ではこのパスだけ範囲に入る）: " + "・".join(
                    f"{h['path']}（{h['glob']}）" for h in r["overrode_out_of_scope"]))
            elif r["decision"] != ALLOW and any(h.get("item") == r.get("item") for h in r.get("out_of_scope") or []):
                body.append("- out_of_scope は外したまま（変えるな）")
            if r.get("spec"):
                body.append(f"- 仕様の補い（従え）: {r['spec']}")
            body.append(f"- 理由: {r['reason']}")
        else:
            why = r.get("why_refused") or r.get("why_unavailable") or " / ".join(r.get("notes") or [])
            body = [f"- 答え: なし（{r['status']}）", f"- 理由: {why}"]
        if r.get("notes") and r["status"] == ANSWERED:
            body.append(f"- 機械の注記: {' / '.join(r['notes'])}")
        lines.append(head + "\n\n" + "\n".join(body) + "\n")
    return "\n".join(lines)


def take(b, pass_: str):
    """支度の節: まだ修正役に渡していない答え（状態が answered）が在れば、渡した印（delivered）を付けて {turn, answer_file, left}
    を返す。無ければ None"""
    st = state(b, pass_)
    if st.get("turn_state") != ANSWERED_TURN or not st.get("answer_file"):
        return None
    _write_json(state_path(b, pass_), {**st, "turn_state": DELIVERED})
    return {"turn": int(st.get("turns") or 0), "answer_file": st["answer_file"],
            "left": max(0, BUDGET - int(st.get("turns") or 0))}


# ---------------------------------------------------------------- 相談の控え（事前の確かめと受け付けの拒否の文）
def place_of(board_dir) -> pathlib.Path:
    """盤面 board_dir の今の scope の相談の置き場（run ごとの置き場の今の scope の下の PLACE。作らない）"""
    return script_io.scope_dir(pathlib.Path(adapter.run_place_of({"board": str(board_dir)}))) / PLACE


def write_config(place, doc: dict) -> pathlib.Path:
    """控えを place/CONFIG に書く（一時のファイルから置き換える）。返りはそのパス"""
    place = pathlib.Path(place)
    place.mkdir(parents=True, exist_ok=True)
    path = place / CONFIG
    _write_json(path, doc)
    return path


def load_config(path) -> dict:
    """控えを読み、置き場（place。控えの在るフォルダ）を足す。読めなければ ValueError"""
    path = pathlib.Path(path)
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise ValueError(f"相談の控え {path} を読めない: {e}") from None
    if not isinstance(doc, dict) or not isinstance(doc.get("items"), dict):
        raise ValueError(f"相談の控え {path} の形が違う（items が無い）")
    return {**doc, "place": str(path.parent)}


def offered(place, pass_: str) -> bool:
    """置き場 place にこの段（pass_）の相談の控えが在り、項目が在るか（支度の節が相談の節を指示書に載せた段）。控えに段の名が
    無ければどの段にも効く。受け付けが拒否の文で相談を先の道に言うかを決める（planscope.reject_head）"""
    if not place:
        return False
    doc = _read_json(pathlib.Path(place) / CONFIG)
    if not doc or not isinstance(doc.get("items"), dict) or not doc["items"]:
        return False
    return doc.get("pass") in (None, "", pass_)
