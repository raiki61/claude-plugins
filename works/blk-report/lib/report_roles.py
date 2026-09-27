"""報告と初見検査のブロック（blk-report）の芯。本線の R13（report.human_items → report.cold_check → report＋finalize）を、
works の盤面（DiskBoard）の上で役として回す。どの節をいつ回すか・検証器の関所（pre: finalize）・記録への書き込みは盤面と
写しの規則が決め、works は描く・起こした印・受け付け・出口だけを持つ。

- route:   盤面を settle し、役の節が ready か。ready でなければ理由（止めた盤面・検証器の関所・まだ周の途中・済んだ）
- prep:    本線の指示書を盤面の今の値で描く（engine の emit_instance と同じ ctx。report には検証器の結果 validation を足す）
           → 拒否の後なら前の拒否の文を頭に → 書き手は作業ツリーの写し → 起こした印（mark_launched）。
           初見の読み手は道具を持たないので、描いた本文そのものを出口の prompt で返す（指示が貼る。盤面の置き場を渡さない）。
           report の書き手には、数の出どころ（盤面から機械が組んだ事実。線 A の機械の報告が在ればそれ）のファイルを渡す
- accept:  返答を読み、書き手の本文は表のセルの書式を機械で見て（持ち主の決まり。works だけの検査）、entry.take で盤面へ。
           拒否は GIVE_UP_AFTER 回目で諦めの印（done）。初見検査を受けた後の settle が検証器の関所で止まったら（RecordInvalid）、
           初見検査は受けた扱いにして、その事実を作業ファイルに残す（report の節は出ない）
- collect: 出口。report を受けていれば 来歴の 1 行＋書き手の本文＋機械の事実（書き換えずに最後に付ける）を盤面の REPORT_NAME に。
           受けていなければ、なぜ無いか・受けた分の本文・検証器の出力の末尾・機械の事実を付けた報告を書いて ok: false（黙らない）

指示書は本線 a1202d0 の写し（blk-report/prompts/。バイト単位で同じ）。描き方は engine と同じ（Renderer・reads の柵・cap なし）。
"""
import json
import os
import pathlib
import re
import sys

sys.dont_write_bytecode = True   # 下の import が pack の中に __pycache__ を作らないように（必ず import より前）

_BLK = pathlib.Path(__file__).resolve().parents[1]
_CORE = _BLK.parent / ".shared" / "core"
if str(_CORE) not in sys.path:
    sys.path.insert(0, str(_CORE))

from board import BoardGap, RecordInvalid  # noqa: E402  （写しの engine を sys.path に入れる。engine より先に）
import engine.util as _util  # noqa: E402
from engine.render import ReadsViolation, Renderer  # noqa: E402
from engine.rules import validator_module  # noqa: E402
from engine.util import dump, now, safe_name  # noqa: E402
import accept as _accept  # noqa: E402
import entry  # noqa: E402
import node_marker  # noqa: E402
import script_io  # noqa: E402

# 役の名（YAML の節 id・包みの印の名）→ 写しの graph の節。並びは graph の依存の並び（human_items → cold_check → report）
ROLES = ("report-items", "report-cold", "report-write")
NODE_OF = dict(zip(ROLES, ("report.human_items", "report.cold_check", "report")))
COLD = "report-cold"
WRITE = "report-write"
PROMPTS = _BLK / "prompts"
# 本文を返す節（graph の text: true）の返答の型。盤面は本文の節の返答を {text} だけで受ける
TEXT_SCHEMA = {"type": "object", "required": ["text"], "additionalProperties": False,
               "properties": {"text": {"type": "string", "minLength": 1}}}
# 輪（loop_group）の max_iterations と同じ数。受け付けがこの数だけ拒んだら諦めの印（done）を出し、輪を失敗で抜けさせずに
# 後ろへ渡す（裁定 R50）。tests/test_blk_report.py が YAML の max_iterations と同じかを見る
GIVE_UP_AFTER = 3
REJECT_HEADING = "## 前の回の受け付けが拒んだ理由"
MACHINE_HEADING = "## 機械が盤面から組んだ事実（AI は書き換えていない）"
CELL_LIMIT = 50   # 表のセルの字数の上限（`コード` の部分を除く）。持ち主の決まり「セルには数語だけ」
REPORT_NAME = "report-ai.md"            # 盤面の根。線 A の機械の報告（report.md）とは別の名前
FACTS_NAME = "report-facts.md"          # 今の周の作業ファイル: 書き手に渡した数の出どころ
REJECTS_NAME = "report-rejects.json"    # 今の周の作業ファイル: 拒否の文の控え（輪の数え・次の指示書の頭）
INVALID_NAME = "report-record-invalid.json"   # 今の周の作業ファイル: 検証器の関所が通らなかった事実
SNAPSHOT_PREFIX = "report-snapshot-"    # 書き手を起こす前の作業ツリーの写し（読むだけの役の比べ）
CELL_REASON = ("表のセルに説明の文を入れない（持ち主の決まり: 表は状態・件数・日付など数語の値の一覧だけ。端末の表は列ごとに"
               f"幅を割るので、長いセルは細切れに折り返されて読めない）。「。」を含むか {CELL_LIMIT} 字を超えるセルが在る——"
               "表をやめて箇条書きか散文にするか、セルを数語に縮めて説明は表の外に書け:\n")
WRITE_NOTE = ("\n\n---\n## works: 数の出どころ（盤面から機械が組んだ事実）\n\n"
              "事実のファイル: {path}\n\n"
              "- 報告に書く数（周・単位・問い・検証器の終了コード・初見検査の件数など）は、このファイルに在る物はこのファイルと同じ値にしろ。"
              "このファイルに無い数を書くなら、記録のどの欄から数えたかを添えろ\n"
              "- このファイルは報告の最後に機械がそのまま付ける。写し直すな（同じ数の一覧を本文に並べ直さない）。本文は、その事実の上に"
              "何が起きたか・何を決めればよいかを足す\n")


def _node(role) -> str:
    if role not in NODE_OF:
        raise BoardGap(f"役 {role!r} は blk-report の役に無い（{' / '.join(ROLES)} のどれか）")
    return NODE_OF[role]


def output_format(role) -> dict:
    """役の output_format: 写しの schema（report.cold_check）か本文の型（report.human_items・report）に印 works-node: <役>"""
    nid = _node(role)
    schema = _accept.role_schema(nid) if nid == NODE_OF[COLD] else TEXT_SCHEMA
    return node_marker.mark(schema, role)


def open_board(board_dir, *, allow_halted=False):
    return entry.open_board(pathlib.Path(board_dir), allow_halted=allow_halted)


def _write_json(path, obj):
    path = pathlib.Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    os.replace(tmp, path)
    return path


def _read_json(path, default=None):
    path = pathlib.Path(path)
    if not path.is_file():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise BoardGap(f"{path} を読めない: {e}") from None


def _note_invalid(b, e: RecordInvalid) -> None:
    _write_json(b.work(INVALID_NAME), {"node": e.node, "exit": e.exit, "out": e.out, "at": now()})


# ---------------------------------------------------------------- 経路
def _why_not(b, nid, progress) -> str:
    rd = b.rd
    for box, word in (("done", "この周に既に済んだ"), ("na", "条件に当たらない"), ("skipped", "省いた"),
                      ("stopped", "止めた")):
        if nid in (rd.get(box) or {}):
            v = rd[box][nid]
            return f"{nid} は{word}（{v if isinstance(v, str) else box}）"
    if progress.get("asking"):
        return f"人に聞いている間（{progress['asking'].get('node')}）で、{nid} は ready でない"
    notes = "・".join(progress.get("notes") or [])
    return f"{nid} は ready でない（周 {b.round}・状態 {b.state.get('status')}・待ち {progress.get('ready')}" + (
        f"・{notes}" if notes else "") + "）"


def route(board_dir, role) -> dict:
    """{next: 役 | "", node, why}。盤面を settle し、役の節が ready なら next に役。止めた盤面（halted）・検証器の関所が
    通らない（RecordInvalid。その事実は INVALID_NAME に残す）・まだ ready でないなら next は空"""
    nid = _node(role)
    b = open_board(board_dir, allow_halted=True)
    h = b.state.get("halted")
    if h:
        return {"next": "", "node": nid, "why": f"盤面は止まっていて報告の節を出せない（halted: {h.get('by')}・{h.get('reason')}）"}
    try:
        p = b.settle()
    except RecordInvalid as e:
        _note_invalid(b, e)
        return {"next": "", "node": nid, "why": f"記録が検証器を通らない（exit {e.exit}）——{e.node} を出さない（本線の pre: finalize の関所）"}
    if nid in p["ready"]:
        return {"next": role, "node": nid, "why": f"{nid} が ready"}
    return {"next": "", "node": nid, "why": _why_not(b, nid, p)}


# ---------------------------------------------------------------- 数の出どころ
def _count(items, key):
    got = {}
    for it in items:
        k = it.get(key) if isinstance(it, dict) else None
        got[k or "未指定"] = got.get(k or "未指定", 0) + 1
    return "・".join(f"{k} {v}" for k, v in got.items()) or "なし"


def board_facts(b, validation=None) -> str:
    """盤面から機械が数えた事実（Markdown の箇条書き。表を使わない）。書き手に渡し、報告の最後にそのまま付ける"""
    st, ls, rec = b.state, b.loop_state, b.record
    units = rec.get("units") or []
    qs = rec.get("questions") or []
    V = validator_module(b)
    lines = [f"- run: {st.get('run_id')}（ライン {(st.get('works') or {}).get('line')}）",
             f"- 周: {b.round}",
             f"- 盤面の状態: {st.get('status')}・結末 {ls.get('outcome') or 'なし'}・止めた理由 {ls.get('stop_reason') or 'なし'}"]
    stop = st.get("stop")
    if stop:
        lines.append(f"- 止めた: {stop.get('by')}（周 {stop.get('round')}）: {' '.join(str(stop.get('reason') or '').split())}")
    if st.get("pending_human"):
        lines.append(f"- 人に聞いたまま: {st['pending_human'].get('node')}")
    if validation is not None:
        lines.append(f"- 検証器の終了コード: {validation.get('exit')}")
    lines += [f"- 根本の単位: {len(units)} 件（ラベル: {_count(units, 'label')}／対応: {_count(units, 'disposition')}）",
              f"- 開いたままの単位: {sum(1 for u in units if V.is_open(u))} 件",
              f"- 問いの台帳: {len(qs)} 件（{_count(qs, 'status')}）",
              f"- 人に聞いた回数: {len((rec.get('process') or {}).get('human_items') or [])}"]
    cc = ls.get("cold_check")
    if isinstance(cc, dict):
        lines.append(f"- 初見検査: {cc.get('verdict')}・止まった所 {cc.get('stops')}・推測で埋めた所 {cc.get('guessed')}・"
                     f"この本文だけで決められる {cc.get('decidable')}")
    absent = b.table.absent() if b.table is not None else []
    lines.append(f"- このラインに無い節: {len(absent)} 個（一覧は盤面の rounds/works/round-<周>.json の not_in_line）")
    return "\n".join(lines) + "\n"


def facts_text(b, machine_report="", validation=None) -> str:
    """数の出どころの本文。線 A の機械の報告のパスが在ればその中身を字のまま、無ければ board_facts。読めなければ
    board_facts に読めなかった事実を足す"""
    if machine_report:
        p = pathlib.Path(machine_report)
        p = p if p.is_absolute() else pathlib.Path.cwd() / p
        try:
            return p.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as e:
            return board_facts(b, validation) + f"- 機械の報告: {machine_report} を読めない（{type(e).__name__}）\n"
    return board_facts(b, validation)


# ---------------------------------------------------------------- 描く・印
def render(b, nid, extra=None) -> str:
    """engine の emit_instance と同じ描き方（ctx・節の skills・reads の柵・ref・cap なし・schema の断り）。指示書は写しの
    prompts/ から（prompt_append を持つ節は描けない）。描けない（reads に無い穴・盤面の欄の欠け）は BoardGap"""
    n = b.nodes[nid]
    inst = b.rd["instances"].get(nid) or {}
    if n.get("prompt_append") or n.get("pointers"):
        raise BoardGap(f"{nid}: prompt_append・pointers を持つ節は blk-report の描き方の外（写し直しで増えた？）")
    tpl = (PROMPTS / n["prompt_file"].removeprefix("../prompts/")).read_text(encoding="utf-8")
    ctx = b.ctx()
    ctx["node"] = {"skills": inst.get("skills") or []}
    ctx.update(extra or {})
    r = Renderer(ctx, n.get("reads"), ref=b.ref, cap=None)
    try:
        prompt = r.render(tpl)
    except (KeyError, ReadsViolation, ValueError) as e:
        raise BoardGap(f"{nid} の指示書を描けない: {e}") from None
    if n.get("schema"):
        prompt += ("\n\n---\n返答はこの JSON Schema に合う JSON だけ（前後に文を付けない）。"
                   '文字列値の中の " は必ず \\" にエスケープしろ——生のまま入れると返答まるごとが'
                   "読めずに捨てられる:\n" + dump(n["schema"]))
    return prompt


def _snap_name(role) -> str:
    return f"{SNAPSHOT_PREFIX}{role}.json"


def prep(board_dir, role, repo, machine_report="") -> dict:
    """役を起こす前の支度。{prompt_file, prompt, attempt, node, facts_file, already}。prompt は初見の読み手にだけ描いた本文
    （道具が無いので指示に貼る）、ほかは空。待っている instance が無ければ BoardGap"""
    nid = _node(role)
    b = open_board(board_dir)
    inst = b.rd["instances"].get(nid)
    if not inst or inst.get("status") != "pending":
        raise BoardGap(f"この周に節 {nid} の待っている instance が無い（rp-route が ready と言った節だけを支度する）")
    extra, facts_file = {}, ""
    if role == WRITE:
        v = b.run_validator()   # engine は出す時の検証器の結果を validation として描く（関所は settle の pre: finalize が通した）
        extra["validation"] = v
        fp = b.work(FACTS_NAME)
        fp.write_text(facts_text(b, machine_report, v), encoding="utf-8")
        facts_file = str(fp)
    prompt = render(b, nid, extra)
    if facts_file:
        prompt += WRITE_NOTE.format(path=facts_file)
    last = _rejects(b, nid)[-1:]
    if last:
        # 拒否の文は指示書に書く。$LOOP_PREV で貼ると文の中の $<節>.output.<欄> を Archon が置き換え直す（裁定 R44）
        prompt = (f"{REJECT_HEADING}\n\n前の回の返答は受け付けで拒まれた。下の理由のところを直した返答を丸ごと出し直せ"
                  f"（直した所だけを返すな）:\n\n```text\n{last[0]['reason']}\n```\n\n---\n\n" + prompt)
    path = b.dir / "prompts" / f"r{b.round}" / (safe_name(nid) + ".md")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(prompt, encoding="utf-8")
    if role != COLD:
        entry.snapshot(pathlib.Path(board_dir), _snap_name(role), pathlib.Path(repo))
    m = b.mark_launched(nid, inst.get("attempts", 1))
    return {"prompt_file": str(path), "prompt": prompt if role == COLD else "", "attempt": m["attempt"], "node": nid,
            "facts_file": facts_file, "already": m["already"]}


# ---------------------------------------------------------------- 受け付け
def format_problems(text) -> list:
    """表のセルの書式の破れ（「。」を含むか CELL_LIMIT 字を超えるセル。`コード` の部分とコードの囲みの中は数えない）。
    1 行につき 1 つの文"""
    out, fence = [], False
    for i, line in enumerate(str(text or "").splitlines(), 1):
        s = line.strip()
        if s.startswith("```") or s.startswith("~~~"):
            fence = not fence
            continue
        if fence or not s.startswith("|"):
            continue
        body = re.sub(r"`[^`]*`", "", s).strip().strip("|")
        cells = [c.strip() for c in re.split(r"(?<!\\)\|", body)]
        if all(re.fullmatch(r":?-{3,}:?", c) or not c for c in cells):
            continue
        bad = [c for c in cells if "。" in c or len(c) > CELL_LIMIT]
        if bad:
            out.append(f"{i} 行目のセル「{bad[0][:30]}{'…' if len(bad[0]) > 30 else ''}」（{len(bad[0])} 字）")
    return out


def _rejects(b, nid):
    return [r for r in _read_json(b.work(REJECTS_NAME), []) if r.get("node") == nid]


def _reject(board_dir, nid, reason) -> dict:
    """拒否の文を REJECTS_NAME に積み {ok: False, done, give_up, reason} を返す。この周のこの節の拒否が GIVE_UP_AFTER 回に
    達したら諦めの印（done）。盤面の層のファイルは書かない"""
    b = open_board(board_dir, allow_halted=True)
    rows = _read_json(b.work(REJECTS_NAME), [])
    inst = b.rd["instances"].get(nid) or {}
    rows.append({"node": nid, "attempt": inst.get("attempts", 1), "at": now(), "reason": reason})
    _write_json(b.work(REJECTS_NAME), rows)
    give_up = sum(1 for r in rows if r.get("node") == nid) >= GIVE_UP_AFTER
    return {"ok": False, "done": give_up, "give_up": give_up, "reason": reason, "node": nid, "record_invalid": False}


def accept(board_dir, role, raw, repo) -> dict:
    """役の返答（Archon の $<役>.output の JSON の文字列）を受け付ける。{ok, done, give_up, reason, node, record_invalid}。
    順: 読む → 書き手の本文のセルの書式（works だけの検査）→ entry.take（書き手は作業ツリーの写しと比べる → 盤面の done）。
    写しの AnswerReject と読むだけの役の変化は拒否（役に返す）。ほかの Reject・BoardGap は投げる（回す側の誤り）"""
    nid = _node(role)
    try:
        reply = json.loads(raw)
    except json.JSONDecodeError as e:
        return _reject(board_dir, nid, f"返答が JSON として読めない: {e}（頭: {raw[:200]!r}）")
    if not isinstance(reply, dict):
        return _reject(board_dir, nid, f"返答が JSON のオブジェクトでない（{type(reply).__name__}）")
    if role != COLD and isinstance(reply.get("text"), str):
        bad = format_problems(reply["text"])
        if bad:
            return _reject(board_dir, nid, CELL_REASON + "\n".join(f"- {x}" for x in bad))
    try:
        got = entry.take(pathlib.Path(board_dir), nid, reply, pathlib.Path(repo),
                         snapshot_name=None if role == COLD else _snap_name(role))
    except RecordInvalid as e:
        # 返答は受けて保存された後、settle が report の節を出す前の関所で止まった（記録が検証器を通らない）
        _note_invalid(open_board(board_dir, allow_halted=True), e)
        return {"ok": True, "done": True, "give_up": False, "node": nid, "record_invalid": True,
                "reason": f"受け付けた。ただし記録が検証器を通らない（exit {e.exit}）ので {e.node} は出ない"}
    if not got["ok"]:
        return _reject(board_dir, nid, got["reason"])
    return {"ok": True, "done": True, "give_up": False, "reason": "", "node": nid, "record_invalid": False}


# ---------------------------------------------------------------- 出口
def stamp(b) -> str:
    """報告の頭の来歴の 1 行（機械が刻む。書き手に写させない——本線の save_text_as と同じ考え）"""
    st = b.state
    return " / ".join([f"works {(st.get('works') or {}).get('line')}", f"run {st.get('run_id')}", f"round {b.round}",
                       f"graph {st.get('graph_sha')}", f"table {(st.get('works') or {}).get('table_sha')}"])


def _text_of(b, nid):
    out = b.output_of_round(nid, b.round) or {}
    return out.get("text") if isinstance(out, dict) else None


def _file_of(b, nid):
    o = b.state["outputs"].get(nid)
    return str(b.dir / o["file"]) if o and o.get("round") == b.round else ""


def _missing_reason(b, invalid):
    if invalid:
        return (f"記録が検証器を通らない（exit {invalid.get('exit')}）——本線の関所（pre: finalize）どおり report の節を"
                "出さなかった。記録（record.json）と trace.jsonl を見て直す")
    for nid in NODE_OF.values():
        if nid in b.rd["done"]:
            continue
        rej = _rejects(b, nid)
        inst = b.rd["instances"].get(nid)
        if rej and len(rej) >= GIVE_UP_AFTER:
            return f"{nid} の返答が {len(rej)} 回とも受け付けで拒まれた（最後の拒否: {rej[-1]['reason']}）"
        if not inst:
            return f"報告の節 {nid} が ready でない（盤面の状態 {b.state.get('status')}・周 {b.round}）"
        return f"{nid} が待ちのまま（役の返答を受けていない。試行 {inst.get('attempts', 1)}）"
    return ""


def collect(board_dir, machine_report="") -> dict:
    """出口 {ok, reason, report_file, text_file, human_items_file, facts_file, cold_check, record_invalid}。
    report を受けていれば 来歴＋本文＋機械の事実 を REPORT_NAME に書いて ok。受けていなければ、報告の節が 1 つも出ていない
    （ready でない）ときは書かずに ok: false、出ていれば受けた分と理由と機械の事実を付けた報告を書いて ok: false"""
    b = open_board(board_dir, allow_halted=True)
    invalid = _read_json(b.work(INVALID_NAME))
    cold = b.output_of_round(NODE_OF[COLD], b.round) if NODE_OF[COLD] in b.rd["done"] else None
    cold = cold if isinstance(cold, dict) else {}
    out = {"ok": NODE_OF[WRITE] in b.rd["done"], "reason": "", "report_file": "", "text_file": _file_of(b, NODE_OF[WRITE]),
           "human_items_file": _file_of(b, NODE_OF["report-items"]), "facts_file": "",
           "cold_check": {"verdict": cold.get("verdict", ""), "stops": cold.get("stops", []), "guessed": cold.get("guessed", []),
                          "decidable": bool(cold.get("decidable", False))},
           "record_invalid": bool(invalid)}
    if not out["ok"]:
        out["reason"] = _missing_reason(b, invalid)
        if not any(nid in b.rd["instances"] for nid in NODE_OF.values()):
            return out   # 報告の節が 1 つも出ていない（配線の時点の誤り）。報告は書かない
    fp = b.work(FACTS_NAME)
    if not fp.is_file():
        fp.write_text(facts_text(b, machine_report, b.run_validator()), encoding="utf-8")
    facts = fp.read_text(encoding="utf-8")
    out["facts_file"] = str(fp)
    if out["ok"]:
        body = _text_of(b, NODE_OF[WRITE]).strip()
    else:
        parts = [f"# 報告（AI の報告を最後まで作れなかった）\n\n{out['reason']}"]
        items = _text_of(b, NODE_OF["report-items"])
        if items:
            parts.append("## 人が決めること（書き手の本文。" + ("初見検査を通した" if cold else "初見検査はまだ") + "）\n\n" + items.strip())
        if cold:
            parts.append(f"## 初見検査\n\n- 判定: {cold.get('verdict')}\n- 止まった所: {len(cold.get('stops') or [])} 件\n"
                         f"- 推測で埋めた所: {len(cold.get('guessed') or [])} 件\n- この本文だけで決められる: {cold.get('decidable')}")
        if invalid:
            tail = "\n".join(str(invalid.get("out") or "").splitlines()[-30:])
            parts.append(f"## 検証器の出力の末尾（exit {invalid.get('exit')}）\n\n```text\n{tail}\n```")
        body = "\n\n".join(parts)
    report = f"{stamp(b)}\n\n{body}\n\n---\n\n{MACHINE_HEADING}\n\n{facts}"
    p = b.dir / REPORT_NAME
    p.write_text(report, encoding="utf-8")
    out["report_file"] = str(p)
    return out


# ---------------------------------------------------------------- スクリプトの入口
def script_main(fn, inputs=(), *, take=False) -> int:
    """blk-report のスクリプトの入口。環境変数 ARTIFACTS_DIR（空も欠け）と inputs（INPUTS_* の名前）を読み、
    fn(盤面の置き場, repo=cwd, {名前: 値}) の返りを 1 行の JSON で出して 0。take なら受け付けの出口（script_io.emit_result。
    拒否の文を盤面のファイルに書き reason_file を足す）を通す。0 でないのは配線の誤りだけ: 環境変数の欠け・盤面のパスの $・
    BoardGap・写しの Reject（止めた run への書き込み・git が効かない など）は標準エラーに 1 行出して 2（標準出力には何も出さない）"""
    missing = [n for n in (script_io.ARTIFACTS_ENV, *inputs) if n not in os.environ]
    if script_io.ARTIFACTS_ENV not in missing and not os.environ[script_io.ARTIFACTS_ENV]:
        missing.append(script_io.ARTIFACTS_ENV)
    if missing:
        print(f"環境変数が無い: {', '.join(missing)}", file=sys.stderr)
        return 2
    board = script_io.board_dir()
    if board is None:
        return 2
    try:
        out = fn(board, pathlib.Path.cwd(), {n: os.environ[n] for n in inputs})
    except (BoardGap, _util.Reject) as e:
        print(f"{type(e).__name__}: {' '.join(str(e).split())}", file=sys.stderr)
        return 2
    if take:
        return script_io.emit_result(board, f"report_{out.get('node', 'take')}", out)
    line = json.dumps(out, ensure_ascii=False) + "\n"
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    sys.stdout.write(line)
    sys.stdout.flush()
    return 0
