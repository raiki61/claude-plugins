"""報告のブロック（blk-report）の芯。本線の R13（report＋finalize）を、works の盤面（DiskBoard）の上で役として回す。
本線の頭だけの書き手（report.human_items）と初見検査の節（report.cold_check）はこのラインの表で absent（2026-10-09 の片付け:
後の書き手が頭を書き直し、初見検査は 56 本とも redesign-needed で、AI の起動 2 回を使うだけだった）。頭は report の書き手が
本文と一度に書き、書き手の輪の中の初見の読み手（道具なし・新しい会話）が頭だけを読んで確かめる。どの節をいつ回すか・
検証器の関所（pre: finalize）・記録への書き込みは盤面と写しの規則が決め、works は描く・起こした印・受け付け・出口だけを持つ。

- route:   盤面を settle し、書き手の節が ready か。ready でなければ理由（止めた盤面・検証器の関所・まだ周の途中・済んだ）
- prep:    本線の指示書を盤面の今の値で描く（engine の emit_instance と同じ ctx に検証器の結果 validation を足す）
           → 拒否の後なら前の拒否の文を頭に → 作業ツリーの写し → 起こした印（mark_launched）。
           書き手には、数の出どころ（盤面から機械が組んだ事実。線 A の機械の報告が在ればそれ）のファイルを渡す
- write_cold_prep: 書き手の返答の頭（平易な冒頭と人が決めること）と、その後ろに機械が付けた語の定義の節だけを、
           初見の読み手の指示書（写しの report.cold_check の指示書）に入れて描く（書き手の輪の中）
- accept:  返答を読み、書き手の run ごとの語（terms）は型を見て作業ファイルに控えて外し（盤面には {text} だけ。語の定義の節は
           pack の一覧とこの控えから描く）、本文は表のセルの書式を機械で見て（持ち主の決まり。works だけの検査）、頭を読んだ
           初見の読み手の返答を COLD_RESULT_NAME に控え、pass でなければ書き手に返し（上限の回は受け取って印を残す）、
           entry.take で盤面へ。拒否は GIVE_UP_AFTER 回目で諦めの印（done）
- collect: 出口。report を受けていれば 来歴の 1 行＋（初見の確かめを通らずに受け取った時はその 1 行）＋書き手の本文＋
           語の定義の節（本文と機械の事実に現れる語）＋機械の事実（書き換えずに最後に付ける）を盤面の REPORT_NAME に。
           受けていなければ、なぜ無いか・検証器の出力の末尾・機械の事実を付けた報告を書いて ok: false（黙らない）

指示書は本線 a1202d0 の写し（blk-report/prompts/。台帳 COPIED_FROM の手直しのほかはバイト単位で同じ）。描き方は engine と同じ
（rolekit.render_body。reads の柵・cap なし）。
"""
import functools
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
from engine.rules import validator_module  # noqa: E402
from engine.schema import validate_schema  # noqa: E402
from engine.util import now, safe_name  # noqa: E402
import accept as _accept  # noqa: E402
import entry  # noqa: E402
import node_marker  # noqa: E402
import rolekit  # noqa: E402

# 役の名（YAML の節 id・包みの印の名）→ 写しの graph の節
WRITE = "report-write"
ROLES = (WRITE,)
NODE_OF = {WRITE: "report"}
# 写しの graph の報告の節の全部（このラインでは頭と初見検査が absent）。拒否の控えの数え（count_rejects）はこの全部を数える
# （頭と初見検査が回っていた前の版の run の控えも、run をまたぐ集計 dev/report_rejects.py が数えられるように）
REPORT_NODES = ("report.human_items", "report.cold_check", "report")
COLD_NODE = "report.cold_check"   # 初見の読み手の指示書と返答の型を借りる写しの節（盤面では回さない）
HEAD_SLOT = "report.human_items"   # 写しの report.cold_check の指示書が読む本文の穴（ここに書き手の頭を入れる）
# 書き手の出した物を確かめる初見の読み手（盤面の節ではない。書き手の輪の中で、書き手の返答の頭だけを読む）
WRITE_COLD = "report-write-cold"
COMMANDS = _BLK / "commands"
COLD_PASTE = f"${WRITE_COLD}-prep.output.prompt"   # commands/report-write-cold.md の描いた本文を貼る所
DECISIONS_HEAD = "人が決めること"
NOT_PASSED = "初見の確かめを通っていない"
PROMPTS = _BLK / "prompts"
# 本文を返す節（graph の text: true）の返答の型。盤面は本文の節の返答を {text} だけで受けるので、run ごとの語 terms は
# 受け付けが外して TERMS_NAME に控える
TERM_SCHEMA = {"type": "object", "required": ["term", "definition"], "additionalProperties": False,
               "properties": {"term": {"type": "string", "minLength": 1}, "definition": {"type": "string", "minLength": 1}}}
TEXT_SCHEMA = {"type": "object", "required": ["text"], "additionalProperties": False,
               "properties": {"text": {"type": "string", "minLength": 1},
                              "terms": {"type": "array", "items": TERM_SCHEMA}}}
# 輪（loop_group）の max_iterations と同じ数。受け付けがこの数だけ拒んだら諦めの印（done）を出し、輪を失敗で抜けさせずに
# 後ろへ渡す（裁定 R50）。tests/test_blk_report.py が YAML の max_iterations と同じかを見る
GIVE_UP_AFTER = 3
REJECT_HEADING = "## 前の回の受け付けが拒んだ理由"
MACHINE_HEADING = "## 機械が盤面から組んだ事実（AI は書き換えていない）"
CELL_LIMIT = 50   # 表のセルの字数の上限（`コード` の部分を除く）。持ち主の決まり「セルには数語だけ」
REPORT_NAME = "report-ai.md"            # 盤面の根。線 A の機械の報告（report.md）とは別の名前
FACTS_NAME = "report-facts.md"          # 今の周の作業ファイル: 書き手に渡した数の出どころ
REJECTS_NAME = "report-rejects.json"    # 今の周の作業ファイル: 拒否の文の控え（輪の数え・次の指示書の頭・種類ごとの回数）
# 拒否の種類: cold＝書き手の頭を読んだ初見の読み手が pass でない（redesign-needed・読めない返答）／format＝表のセル／
# answer＝返答の型・take の拒否
REJECT_KINDS = ("cold", "format", "answer")
# 読むときだけの種類: kind の無い行（kind が入る前の run）・知らない kind の行を捨てずに数える先。_reject は書かない
UNKNOWN_KIND = "unknown"
COLD_REJECTS_LINE = "- 初見の読み手の拒否（この周）:"
INVALID_NAME = "report-record-invalid.json"   # 今の周の作業ファイル: 検証器の関所が通らなかった事実
COLD_MARK_NAME = "report-cold-unpassed.json"  # 今の周の作業ファイル: 上限の回に初見の確かめを通らないまま受け取った事実
COLD_UNPASSED = "cold_unpassed"         # count_round_rejects が書き手の節に並べる COLD_MARK_NAME の件数の鍵
COLD_RESULT_NAME = "report-cold-check.json"   # 今の周の作業ファイル: 書き手の頭を読んだ初見の読み手の最後の返答（出口の cold_check）
TERMS_NAME = "report-terms.json"        # 今の周の作業ファイル: 書き手が返した run ごとの語（{節: [{term, definition}]}）
SNAPSHOT_PREFIX = "report-snapshot-"    # 書き手を起こす前の作業ツリーの写し（読むだけの役の比べ）
# pack の語の定義の一覧（terms: [{term, definition}]）
GLOSSARY = _BLK / "glossary.json"
GLOSSARY_HEADING = "## 語の定義（機械が付けた。本文の外）"
CELL_REASON = ("表のセルに説明の文を入れない（書式の決まり: 表は状態・件数・日付など数語の値の一覧だけ。端末の表は列ごとに"
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
    """役の output_format: 書き手を確かめる初見の読み手は写しの report.cold_check の schema、書き手は本文の型に印 works-node: <役>"""
    if role == WRITE_COLD:
        return node_marker.mark(_accept.role_schema(COLD_NODE), role)
    _node(role)
    # 書き手の輪には初見の読み手（context: fresh の新しい会話）が挟まり、Archon は次の周の書き手にその会話を継がせる。
    # 旗 self-resume で包みが 2 周目から書き手自身の会話に戻す（adapter の 1）
    return node_marker.mark(TEXT_SCHEMA, role, flags=("self-resume",))


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


# ---------------------------------------------------------------- 語の定義
def _pack_terms() -> list:
    return list(_read_json(GLOSSARY, {}).get("terms") or [])


def glossary_section(text, terms=()) -> str:
    """pack の一覧と terms（同じ語は pack を採る）のうち text に現れる語だけを並べた語の定義の節。現れる語が無ければ空文字"""
    seen, rows = set(), []
    for t in _pack_terms() + list(terms or []):
        term = t.get("term") if isinstance(t, dict) else None
        if not term or term in seen:
            continue
        seen.add(term)
        if term in str(text or ""):
            rows.append(f"- {term}: {t.get('definition')}")
    return f"{GLOSSARY_HEADING}\n\n" + "\n".join(rows) + "\n" if rows else ""


def _with_glossary(text, terms=()) -> str:
    sec = glossary_section(text, terms)
    return f"{text.rstrip()}\n\n{sec}" if sec else text


# ---------------------------------------------------------------- 描く・印
def render(b, nid, extra=None, hook=None) -> str:
    """engine の emit_instance と同じ描き方（rolekit.render_body: ctx・節の skills・reads の柵・ref・cap なし・schema の断り）。
    指示書は写しの prompts/ から（prompt_append・pointers を持つ節は描けない）。extra は ctx に足す欄（report の validation）、
    hook は足した後の ctx を差し替える口。描けない（待っていない・reads に無い穴・盤面の欄の欠け）は BoardGap"""
    n = b.nodes[nid]
    if n.get("prompt_append") or n.get("pointers"):
        raise BoardGap(f"{nid}: prompt_append・pointers を持つ節は blk-report の描き方の外（写し直しで増えた？）")

    def ctx_hook(ctx):
        ctx.update(extra or {})
        if hook:
            hook(ctx)
    return rolekit.render_body(b, nid, prompts_dir=_BLK, ctx_hook=ctx_hook, lang=False)[0]


def _terms_problems(reply) -> list:
    """書き手の返答の terms の欄の型の破れ（欄が無ければ空）"""
    if "terms" not in reply:
        return []
    return validate_schema(reply["terms"], TEXT_SCHEMA["properties"]["terms"], "$.terms")


def _run_terms(b, *nids) -> list:
    kept = _read_json(b.work(TERMS_NAME), {})
    return [t for nid in nids for t in kept.get(nid) or []]


def _snap_name(role) -> str:
    return f"{SNAPSHOT_PREFIX}{role}.json"


def prep(board_dir, role, repo, machine_report="") -> dict:
    """書き手を起こす前の支度。{prompt_file, attempt, node, facts_file, already}。待っている instance が無ければ BoardGap"""
    nid = _node(role)
    b = open_board(board_dir)
    inst = b.rd["instances"].get(nid)
    if not inst or inst.get("status") != "pending":
        raise BoardGap(f"この周に節 {nid} の待っている instance が無い（rp-route が ready と言った節だけを支度する）")
    v = b.run_validator()   # engine は出す時の検証器の結果を validation として描く（関所は settle の pre: finalize が通した）
    fp = b.work(FACTS_NAME)
    fp.write_text(facts_text(b, machine_report, v), encoding="utf-8")
    facts_file = str(fp)
    prompt = render(b, nid, {"validation": v}) + WRITE_NOTE.format(path=facts_file)
    last = _rejects(b, nid)[-1:]
    if last:
        # 拒否の文は指示書に書く。$LOOP_PREV で貼ると文の中の $<節>.output.<欄> を Archon が置き換え直す（裁定 R44）
        prompt = (f"{REJECT_HEADING}\n\n前の回の返答は受け付けで拒まれた。下の理由のところを直した返答を丸ごと出し直せ"
                  f"（直した所だけを返すな）:\n\n```text\n{last[0]['reason']}\n```\n\n---\n\n" + prompt)
    path = b.dir / "prompts" / f"r{b.round}" / (safe_name(nid) + ".md")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(prompt, encoding="utf-8")
    entry.snapshot(pathlib.Path(board_dir), _snap_name(role), pathlib.Path(repo))
    m = b.mark_launched(nid, inst.get("attempts", 1))
    return {"prompt_file": str(path), "attempt": m["attempt"], "node": nid, "facts_file": facts_file, "already": m["already"]}


def head_of(text) -> str:
    """報告の頭: 最初の見出し（## ）より前の冒頭と、見出しに『人が決めること』を持つ節。見出しが無ければ全文"""
    head, keep, found = [], True, False
    for line in str(text or "").splitlines():
        if line.startswith("## "):
            found = True
            keep = DECISIONS_HEAD in line
        if keep:
            head.append(line)
    return "\n".join(head).strip() if found else str(text or "").strip()


def write_cold_prep(board_dir, raw) -> dict:
    """書き手の返答の頭（head_of）を、初見の読み手の指示書（report.cold_check の写し）で描き、初見の読み手の決まり
    （commands/report-write-cold.md の、描いた本文を貼る所 COLD_PASTE）で包む。{prompt, prompt_file}。
    描き方は rolekit.render_body（ctx・schema の断りは report.cold_check の物）で、読み手の材料の穴（HEAD_SLOT の本文）に
    書き手の頭を入れる。待っている節は report（書き手の輪の中）。
    全文は渡さない（読み手が確かめるのは報告の頭。全文を読ませると出し直しの枠を使い切る）。頭の後ろに語の定義の節を
    付ける（head_of は見出しの付いた節を落とすので、書き手が本文に書いた定義は届かない）。書き手の返答が読めなければ、
    読めない事実を本文にする。貼る所が決まりに無ければ BoardGap（黙って貼らない物を出さない）"""
    b = open_board(board_dir, allow_halted=True)
    reply, why = rolekit.parse_reply(raw)
    text = reply.get("text") if isinstance(reply, dict) else None
    terms = reply.get("terms") if isinstance(reply, dict) and not _terms_problems(reply) else []
    body = (_with_glossary(head_of(text), terms) if isinstance(text, str) and text.strip()
            else f"（書き手の返答を読めない: {why or '本文が無い'}）")
    cold = b.nodes[COLD_NODE]
    template = rolekit.node_prompt(rolekit.prompt_graph_path(b, cold, _BLK), cold)
    drawn = rolekit.render_body(b, NODE_OF[WRITE], prompts_dir=_BLK, template=template, schema_of=COLD_NODE,
                                ctx_hook=lambda ctx: ctx["out"].update({HEAD_SLOT: {"text": body}}))[0]
    command = (COMMANDS / f"{WRITE_COLD}.md").read_text(encoding="utf-8")
    if COLD_PASTE not in command:
        raise BoardGap(f"commands/{WRITE_COLD}.md に描いた本文を貼る所 {COLD_PASTE} が無い")
    prompt = command.replace(COLD_PASTE, drawn)
    path = b.dir / "prompts" / f"r{b.round}" / f"{WRITE_COLD}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(prompt, encoding="utf-8")
    return {"prompt_file": str(path), "prompt": prompt}


# ---------------------------------------------------------------- 受け付け
def _cold_reply(cold) -> tuple:
    """初見の読み手の返答（JSON の文字列）→ (判定の語の在る dict か None, 読めない理由)"""
    got, why = rolekit.parse_reply(cold)
    if got is None or got.get("verdict") not in ("pass", "redesign-needed"):
        return None, why or "判定の語が無い"
    return got, ""


def _cold_block(cold) -> dict | None:
    """書き手を確かめた初見の読み手の返答（JSON の文字列）が pass でなければ {verdict, stops, guessed, reason}。pass なら None。
    読めない・形が違う返答は確かめを通っていない扱い（fail-closed）"""
    got, why = _cold_reply(cold)
    if got is None:
        return {"verdict": "", "stops": [], "guessed": [], "reason": f"初見の読み手の返答を読めない（{why}）"}
    if got["verdict"] == "pass":
        return None
    stops, guessed = list(got.get("stops") or []), list(got.get("guessed") or [])
    lines = [f"- 止まった所: {s}" for s in stops] + [f"- 推測で埋めた所: {g}" for g in guessed]
    return {"verdict": got["verdict"], "stops": stops, "guessed": guessed,
            "reason": "初見の読み手（道具なし・報告の頭だけを読む）が redesign-needed を返した。次の所を、頭だけで意味が取れるように"
                      "直した本文を丸ごと出し直せ:\n" + ("\n".join(lines) or "- （止まった所・推測の欄が空）")}



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


def _reject(board_dir, nid, reason, kind) -> dict:
    """拒否の文を種類 kind（REJECT_KINDS のどれか）と共に REJECTS_NAME に積み {ok: False, done, give_up, reason} を返す。
    この周のこの節の拒否が GIVE_UP_AFTER 回に達したら諦めの印（done。種類を問わず数える）。盤面の層のファイルは書かない"""
    if kind not in REJECT_KINDS:
        raise BoardGap(f"拒否の種類 {kind!r} は {' / '.join(REJECT_KINDS)} のどれでもない")
    b = open_board(board_dir, allow_halted=True)
    rows = _read_json(b.work(REJECTS_NAME), [])
    inst = b.rd["instances"].get(nid) or {}
    rows.append({"node": nid, "attempt": inst.get("attempts", 1), "at": now(), "kind": kind, "reason": reason})
    _write_json(b.work(REJECTS_NAME), rows)
    give_up = sum(1 for r in rows if r.get("node") == nid) >= GIVE_UP_AFTER
    return {"ok": False, "done": give_up, "give_up": give_up, "reason": reason, "node": nid, "record_invalid": False}


def _keep_cold(board_dir, cold) -> None:
    """初見の読み手の返答を COLD_RESULT_NAME に控える（出口の cold_check。読めない返答は判定の語を空に）"""
    got, _ = _cold_reply(cold)
    got = got or {}
    _write_json(open_board(board_dir, allow_halted=True).work(COLD_RESULT_NAME),
                {"verdict": got.get("verdict", ""), "stops": list(got.get("stops") or []),
                 "guessed": list(got.get("guessed") or []), "decidable": bool(got.get("decidable", False))})


def accept(board_dir, role, raw, repo, cold=None) -> dict:
    """書き手の返答（Archon の $<役>.output の JSON の文字列）を受け付ける。{ok, done, give_up, reason, node, record_invalid}。
    順: 読む → terms の型（崩れていれば拒否。通れば TERMS_NAME に控えて返答から外す——盤面は {text} だけを受ける）
    → 本文のセルの書式（works だけの検査）→ 頭を読んだ初見の読み手の返答 cold（COLD_RESULT_NAME に控える。None は配線しない
    直の呼び出しで確かめない。scripts/accept.py はいつも文字列を渡し、空は読めない返答として通さない）→ entry.take（作業ツリーの
    写しと比べる → 盤面の done）。初見の読み手が pass でなければ書き手に返す。上限の回（この周のこの節の拒否が
    GIVE_UP_AFTER - 1 回）は受け取り、COLD_MARK_NAME に通っていない事実を残す（受け取らないと collect が報告を出せない）。
    写しの AnswerReject と読むだけの役の変化は拒否（役に返す）。ほかの Reject・BoardGap は投げる（回す側の誤り）"""
    nid = _node(role)
    reply, why = rolekit.parse_reply(raw)
    if reply is None:
        return _reject(board_dir, nid, why, "answer")
    bad = _terms_problems(reply)
    if bad:
        return _reject(board_dir, nid, "返答の terms の欄が型に合わない（各要素は空でない term と definition の 2 つだけ）:\n"
                       + "\n".join(f"- {x}" for x in bad), "answer")
    b = open_board(board_dir, allow_halted=True)
    kept = _read_json(b.work(TERMS_NAME), {})
    kept[nid] = reply.get("terms") or []
    _write_json(b.work(TERMS_NAME), kept)
    reply = {k: v for k, v in reply.items() if k != "terms"}
    if isinstance(reply.get("text"), str):
        bad = format_problems(reply["text"])
        if bad:
            return _reject(board_dir, nid, CELL_REASON + "\n".join(f"- {x}" for x in bad), "format")
    if cold is not None:
        _keep_cold(board_dir, cold)
    blocked = _cold_block(cold) if cold is not None else None
    if blocked and len(_rejects(open_board(board_dir, allow_halted=True), nid)) < GIVE_UP_AFTER - 1:
        return _reject(board_dir, nid, blocked["reason"], "cold")
    try:
        got = entry.take(pathlib.Path(board_dir), nid, reply, pathlib.Path(repo), snapshot_name=_snap_name(role))
    except RecordInvalid as e:
        # 返答は受けて保存された後、settle が次を出す前の関所で止まった（記録が検証器を通らない）
        _note_invalid(open_board(board_dir, allow_halted=True), e)
        return {"ok": True, "done": True, "give_up": False, "node": nid, "record_invalid": True,
                "reason": f"受け付けた。ただし記録が検証器を通らない（exit {e.exit}）ので {e.node} は出ない"}
    if not got["ok"]:
        return _reject(board_dir, nid, got["reason"], "answer")
    if blocked:
        _write_json(open_board(board_dir, allow_halted=True).work(COLD_MARK_NAME), {**blocked, "at": now()})
        return {"ok": True, "done": True, "give_up": False, "node": nid, "record_invalid": False,
                "reason": f"上限の回なので受け取った。ただし{NOT_PASSED}（報告の冒頭に出す）"}
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


def count_rejects(rows) -> dict:
    """拒否の行の回数 {節: {種類: 回数}}（kind を数える。文は読まない）。kind の無い行・知らない kind の行は UNKNOWN_KIND に
    数え、REPORT_NODES の節でない行は数えない"""
    got = {nid: dict.fromkeys((*REJECT_KINDS, UNKNOWN_KIND), 0) for nid in REPORT_NODES}
    for r in rows:
        if r.get("node") in got:
            kind = r.get("kind") if r.get("kind") in REJECT_KINDS else UNKNOWN_KIND
            got[r["node"]][kind] += 1
    return got


def count_round_rejects(round_dir) -> dict:
    """盤面の周のディレクトリ r<N> の拒否の回数（count_rejects）に、書き手の節の COLD_UNPASSED（上限の回に初見の確かめを
    通らないまま受け取った件数。COLD_MARK_NAME の有無で 0 か 1）を並べる"""
    round_dir = pathlib.Path(round_dir)
    got = count_rejects(_read_json(round_dir / REJECTS_NAME, []))
    got[NODE_OF[WRITE]][COLD_UNPASSED] = int((round_dir / COLD_MARK_NAME).is_file())
    return got


def _reject_counts(b) -> dict:
    """この周の拒否の回数 {節: {種類: 回数}}（このラインで回す節 NODE_OF だけ）。種類は REJECT_KINDS だけを写す（_reject は
    不明な kind を書かないので、この周の UNKNOWN_KIND はいつも 0）"""
    got = count_rejects(_read_json(b.work(REJECTS_NAME), []))
    return {nid: {k: got[nid][k] for k in REJECT_KINDS} for nid in NODE_OF.values()}


def collect(board_dir, machine_report="") -> dict:
    """出口 {ok, reason, report_file, text_file, facts_file, cold_check, record_invalid, rejects}。cold_check は書き手の頭を
    読んだ初見の読み手の最後の返答（COLD_RESULT_NAME。無ければ空の判定）、rejects は節ごと・種類ごとの拒否の回数。report を
    受けていれば 来歴＋本文＋語の定義の節＋機械の事実（見出しの直後に初見の読み手の拒否の回数の 1 行）を REPORT_NAME に書いて
    ok。受けていなければ、報告の節が 1 つも出ていない（ready でない）ときは書かずに ok: false、出ていれば理由と機械の事実を
    付けた報告を書いて ok: false"""
    b = open_board(board_dir, allow_halted=True)
    invalid = _read_json(b.work(INVALID_NAME))
    cold = _read_json(b.work(COLD_RESULT_NAME), {}) or {}
    out = {"ok": NODE_OF[WRITE] in b.rd["done"], "reason": "", "report_file": "", "text_file": _file_of(b, NODE_OF[WRITE]),
           "facts_file": "",
           "cold_check": {"verdict": cold.get("verdict", ""), "stops": cold.get("stops", []), "guessed": cold.get("guessed", []),
                          "decidable": bool(cold.get("decidable", False))},
           "record_invalid": bool(invalid), "rejects": _reject_counts(b)}
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
        if invalid:
            tail = "\n".join(str(invalid.get("out") or "").splitlines()[-30:])
            parts.append(f"## 検証器の出力の末尾（exit {invalid.get('exit')}）\n\n```text\n{tail}\n```")
        body = "\n\n".join(parts)
    mark = _read_json(b.work(COLD_MARK_NAME))
    if out["ok"] and mark:
        body = f"{NOT_PASSED}: {' '.join(str(mark.get('reason') or '').split())}\n\n{body}"
    # 機械の事実の固定の行の語も拾う
    sec = glossary_section(f"{body}\n{facts}", _run_terms(b, NODE_OF[WRITE]))
    sec = f"{sec}\n" if sec else ""
    colds = sum(c["cold"] for c in out["rejects"].values())
    report = f"{stamp(b)}\n\n{body}\n\n{sec}---\n\n{MACHINE_HEADING}\n\n{COLD_REJECTS_LINE} {colds} 回\n\n{facts}"
    p = b.dir / REPORT_NAME
    p.write_text(report, encoding="utf-8")
    out["report_file"] = str(p)
    return out


# ---------------------------------------------------------------- スクリプトの入口
# blk-report のスクリプトの入口（rolekit.script_main。盤面のパスに $ の柵）。受け付けは take="report" を渡し、拒否の文を
# 盤面の reject-report_<節>-<連番>.txt に書いて reason_file を足す（script_io.emit_result）。0 でないのは配線の誤りだけ:
# 環境変数の欠け・盤面のパスの $・BoardGap・写しの Reject・思わぬ誤りは標準エラーに 1 行出して 2（標準出力には何も出さない）
script_main = functools.partial(rolekit.script_main, fence=True)
