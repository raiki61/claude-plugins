"""役の節を回す共通の口（P1 計画 Task 13。C13・〔振〕10.3）。本線（graphloops）の指示書を engine と同じ描き方で描く式と、
ブロックのスクリプトの入口の約束を 1 か所に置く（前は rejudge・refix に写しが在った）。

- render_body:    engine の emit_instance と同じ描き方（node_prompt → ctx → pointers.snapshot → Renderer。cap なし・graph の
                  reads だけ・ref・schema の断り）で本文を描き、(本文, 番号の控え) を返す。描けなければ BoardGap
- render_prompt:  render_body の本文の頭に head（役の定義など）を置き、今の周の作業ファイル prompt-<節>.md に書く。この周に
                  この節の拒否が在れば、最後の拒否の理由のファイルのパスを頭の 1 行で名指す（文は貼らない。裁定 R44）
- lang_line:      役に言語を縛る 1 行（LANG_RULE に盤面の inputs.lang）。render_body と rulebook.render の呼び手が指示書に置く
- compose:        指示書の部分を繋ぎ、前の拒否の理由のファイルを頭の 1 行で名指す（render_prompt と、本線の写しでない指示書を
                  スクリプトが組むブロックが使う）
- role_definition: 役の定義の本文を指示書の頭に置くための (本文, ファイル, 無い時の知らせ)。写しの plugin の役が引けなければ BoardGap
- with_reject:    道具ゼロの役の指示書の頭に前の拒否の文を貼る（ファイルを名指さない。裁定 R44）
- agent_def:      engine の agent_def（役の定義 agents/<役>.md）を、写しの plugin の役は pack の写し（core/agents/）から引く
- accept_role:    出し直しの輪の受け付け（entry.take）。拒否は理由の本文を盤面の reject-take_<節>-<連番>.txt に書き
                  （script_io が理由の本文を書く名）、この周の拒否の控え role-rejects.json に積み、give_up_after 回目で done・give_up
                  （輪を max_iterations で落とさない。裁定 R50）
- main_accept:    accept_role の節の入口（INPUTS_REPLY・ARTIFACTS_DIR。after で出口の欄を足せる）
- gave_up:        出口（collect）の諦めの腕: この周のこの節の拒否が give_up_after 件あれば、最後の拒否の文で盤面を止める
                  （止まっていなければ）。返りは止めた理由（届いていなければ空。呼び手は配線の誤りとして扱う）
- with_done:      盤面の節でない受け付け（script_io.main の finish）に done を足す。拒否は盤面の根の控え rejects-<名>.json に
                  積み、通った時か give_up_after 回目の拒否で done（控えは intake が clear_rejects で消す）
- given_up_reason・stop_line: 盤面の節でない受け付けの出口が、控えの最後の拒否の文を引き、ラインの盤面なら止める
- script_main:    ブロックのスクリプトの入口（ARTIFACTS_DIR と INPUTS_* を読み、fn の返りを 1 行の JSON で出す。fence なら
                  盤面のパスに $ の柵、take なら受け付けの返りに reason_file を足す）
- parse_reply:    役の返答（$<役>.output の JSON の文字列）を dict に
- skill_overlay:  借りたスキルを読める役（道具に Skill を持つ役）の指示書に足す、無人の読み替え .shared/borrow/unattended.md の段

層は L3（盤面と受け付け）。ライン・include の id・ブロックの名前を書かない（tests/test_layers.py）。
"""
import datetime
import json
import os
import pathlib
import sys

sys.dont_write_bytecode = True   # 下の import が pack の中に __pycache__ を作らないように（必ず import より前）

_CORE = pathlib.Path(__file__).resolve().parent
if str(_CORE) not in sys.path:
    sys.path.insert(0, str(_CORE))

from board import LANG_DEFAULT, BoardGap  # noqa: E402  （board が写しの engine を sys.path に足す。engine より先に）
from engine import pointers as _pointers  # noqa: E402
from engine.advance import agent_type_of  # noqa: E402
from engine.render import ReadsViolation, Renderer, node_prompt  # noqa: E402
from engine.util import Reject, dump, safe_name  # noqa: E402
from engine.validator import agent_def as _engine_agent_def, env_root  # noqa: E402
import entry  # noqa: E402
import script_io  # noqa: E402

PROMPTS_COPY = _CORE / "gl-prompts"   # 写しと同じ commit から写した本線の指示書（graphloops/ と同じ並び）
AGENTS_PLUGIN = "convergence-loops"    # core/agents/ に写した役の定義の plugin（写しの graph の plugin。tests/test_core_copy.py）
SCHEMA_NOTE = ("\n\n---\n返答はこの JSON Schema に合う JSON だけ（前後に文を付けない）。"
               '文字列値の中の " は必ず \\" にエスケープしろ——生のまま入れると返答まるごとが'
               "読めずに捨てられる:\n")
PROMPT_PREFIX = "prompt-"               # render_prompt が書く今の周の作業ファイルの名の頭
REJECTS_NAME = "role-rejects.json"      # accept_role が積むこの周の拒否の控え [{node, attempt, at, reason_file}]
GIVE_UP_AFTER = 3                       # 輪の max_iterations と同じ数（ブロックの試験が YAML と突き合わせる）
REJECT_LINE = ("前の回の返答は受け付けで拒まれた。理由はファイル {path} に在る。先に Read で読み、そこを直した返答を丸ごと"
               "出し直せ（直した所だけを返すな）。")
# 役の文は関所と報告に機械が字のまま載せるので、書き手に言語を縛る（本線 blk-report の report.md:12 と同じ形。機械で訳さない）
LANG_RULE = ("人が読む文の欄（reason・how・what・why・異議・所見・申し出の文など、関所と報告に載る文）は {lang} で書け。"
             "key・enum の値・コード識別子・パス・コマンド・エラー文はそのまま（key は周をまたいで突き合わせるので訳さない）。")
OVERLAY_FILE = _CORE.parent / "borrow" / "unattended.md"   # 借りたスキルを無人の役で読むときの読み替え（正本）
OVERLAY_HEAD = ("借りたスキル（superpowers）を読む時は、下の読み替えに従え。これは役への直の指示で、スキルの文より勝つ。"
                "Agent で下請けを起こすなら、その prompt に、このファイル {path} を Read せよと書け。")


def skill_overlay() -> str:
    """借りたスキルを読める役の指示書に足す段: 頭の 1 行と、読み替えの正本の全文（字のまま。写しを持たない）。superpowers の
    using-superpowers は、直の指示（CLAUDE.md・直の依頼）がスキルに勝つと定める"""
    return OVERLAY_HEAD.format(path=OVERLAY_FILE) + "\n\n" + OVERLAY_FILE.read_text(encoding="utf-8")


# ---------------------------------------------------------------- 描く
def prompt_graph_path(b, n, prompts_dir: pathlib.Path = PROMPTS_COPY) -> pathlib.Path:
    """node_prompt に渡す graph のパス（指示書は graph の置き場からの相対）。写しが指示書を持てば写しの graph、無ければ
    prompts_dir（本線の graphloops/ と同じ並び。親が prompts/ でも ../prompts/<…> は同じ所に届く）"""
    own = pathlib.Path(b.state["graph"])
    parts = [n["prompt_file"], *(n.get("prompt_append") or [])]
    if all((own.parent / p).is_file() for p in parts):
        return own
    alt = pathlib.Path(prompts_dir) / "prompts" / own.name
    missing = [p for p in parts if not (alt.parent / p).is_file()]
    if missing:
        raise BoardGap(f"指示書 {missing} が写しにも {prompts_dir} にも無い")
    return alt


def render_body(b, nid: str, *, prompts_dir: pathlib.Path = PROMPTS_COPY, reads_only: bool = True,
                template: str | None = None, ctx_hook=None, schema_note: bool = True, schema_of: str = "",
                ahead: bool = False, lang: bool = True) -> tuple:
    """engine の emit_instance と同じ描き方の本文（cap なし。指示書は役がファイルで読む）と番号の控え（pointers.snapshot の
    名前の列。mark_launched の pointers= に渡す形。pointers を持たない節は空の列）。reads_only が偽なら graph の reads で
    穴を絞らない。template は graph の指示書（node_prompt）の代わりに描く本文（ブロックが別の置き場に持つ本線の写し）。
    ctx_hook(ctx) は描く前に ctx を足す口（engine が足す欄——検証器の結果 validation・ラインに無い節の出力の代わり など）。
    schema_note が偽なら本文の後ろに graph の schema を足さない（指示書の一部だけを材料として描く時。返答の型は役の output_format）。
    schema_of は足す schema を別の節の物にする（待っている節の輪の中で、別の節の指示書を描く時）。
    ahead が真なら節がまだ待っていなくても描く（graph の依存より前に先に役を起こす時。skills は空）。
    lang が真なら本文の末尾（schema の前）に言語の 1 行（lang_line）を置く（指示書が自分で inputs.lang を描く役は偽）。
    この周に待っている instance が無い（ahead でない時）・描けない（reads に無い穴・盤面の欄の欠け・番号の穴の欠け）は BoardGap"""
    n = b.nodes[nid]
    inst = b.rd["instances"].get(nid)
    pending = bool(inst) and inst.get("status") == "pending"
    if not (pending or ahead):
        raise BoardGap(f"この周に節 {nid} の待っている instance が無い")
    tpl = node_prompt(prompt_graph_path(b, n, prompts_dir), n) if template is None else template
    ctx = b.ctx()
    ctx["node"] = {"skills": (inst.get("skills") if pending else None) or []}   # engine と同じく、出した時点の applies を持つ写し（settle が置いた物）
    if ctx_hook is not None:
        ctx_hook(ctx)
    snap, offsets = _pointers.snapshot(ctx, n.get("pointers"))
    r = Renderer(ctx, n.get("reads") if reads_only else None, ref=b.ref, cap=None, numbered=offsets)
    try:
        text = r.render(tpl)
    except (KeyError, ReadsViolation, ValueError) as e:
        raise BoardGap(f"{nid} の指示書を描けない: {e}") from None
    unseen = sorted(set(offsets) - r.numbered_seen)
    if unseen:
        raise BoardGap(f"{nid}: pointers の from {unseen} を貼る穴が指示書に無い")
    if lang:
        text = text.rstrip("\n") + "\n\n" + lang_line(ctx.get("inputs")) + "\n"
    schema = b.nodes[schema_of or nid].get("schema")
    if schema_note and schema:
        text += SCHEMA_NOTE + dump(schema)
    return text, snap


def lang_line(inputs) -> str:
    """役に言語を縛る 1 行（LANG_RULE）。言語は盤面の inputs.lang（空なら board.LANG_DEFAULT＝依頼文の言語）"""
    got = (inputs or {}).get("lang") if isinstance(inputs, dict) else None
    return LANG_RULE.format(lang=str(got or "").strip() or LANG_DEFAULT)


def prompt_name(nid: str) -> str:
    return f"{PROMPT_PREFIX}{safe_name(nid)}.md"


def render_prompt(b, nid: str, *, prompts_dir: pathlib.Path = PROMPTS_COPY, head: str = "",
                  reads_only: bool = True) -> pathlib.Path:
    """本線の指示書を render_body で描き、head（役の定義など）を頭に置いて b.work(prompt-<節>.md) に書き、パスを返す。
    この周にこの節の拒否（accept_role の控え）が在れば、最後の拒否の理由のファイルのパスを 1 行目で名指す（理由の文そのものは
    貼らない——役が Read で読む。裁定 R44）"""
    body, _ = render_body(b, nid, prompts_dir=prompts_dir, reads_only=reads_only)
    p = b.work(prompt_name(nid))
    p.write_text(compose([head.rstrip("\n"), body], reject_file=last_reject_file(b, nid)), encoding="utf-8")
    return p


def compose(parts, *, reject_file: str = "") -> str:
    """役に読ませる指示書の組み立て（AI を通さない）: 空でない部分を字のまま空行 1 つで繋ぐ。reject_file（前の拒否の理由の
    ファイル）が在れば 1 行目でそのパスを名指す（理由の文そのものは貼らない。裁定 R44）。同じ入力からは同じバイト"""
    out = [REJECT_LINE.format(path=reject_file)] if reject_file else []
    return "\n\n".join(out + [s for s in parts if s])


def agent_def(agent_type: str):
    """engine の agent_def と同じ返り（無ければ None）。本線の engine は隣に並ぶ plugin の agents/<役>.md を読むが、pack の engine の
    隣は plugin でないので、写しの plugin（AGENTS_PLUGIN）の役は、置き場 <PLUGIN>_ROOT が明示されていなければ pack の写し
    （core/agents/。COPIED_FROM）を指して引く——利用者の plugin のキャッシュに依らない（run 31: 隔離した CLAUDE_CONFIG_DIR に
    convergence-loops が無く、独立の目の支度が BoardGap で落ちた）。明示された置き場と別 plugin の役は engine の探し方のまま。
    置き場の環境変数はこの呼びの間だけ置く（後で起こす子のプロセス——対象の試験など——へ漏らさない）"""
    plugin = agent_type.rpartition(":")[0]
    key = env_root(plugin) if plugin else ""
    if plugin != AGENTS_PLUGIN or os.environ.get(key):
        return _engine_agent_def(agent_type)
    os.environ[key] = str(_CORE)
    try:
        return _engine_agent_def(agent_type)
    finally:
        os.environ.pop(key, None)


def role_definition(b, nid) -> tuple:
    """(役の定義の本文, 定義のファイル, 無い時の知らせ)。graph の plugin の役の定義が見つからなければ BoardGap（engine の die と同じ——
    遮断系かどうかが決まらないので起こさない）。別 plugin の役は止めずに知らせを返す（engine の role_def_missing）"""
    atype = agent_type_of(b, b.nodes[nid])
    d = agent_def(atype)   # 写しの plugin の役は pack の写し（core/agents/）から
    if d is None:
        if atype.rpartition(":")[0] == b.plugin:
            raise BoardGap(f"{nid}: 役 {atype!r} の定義（agents/<役>.md）が解決できない——遮断系かどうかが決まらないので起こさない"
                           "（pack の写し .shared/core/agents/・明示した <PLUGIN>_ROOT を確かめよ）")
        return "", "", f"{atype} の定義がこの環境に無い（別 plugin）。役の定義なしで起こす"
    return d["body"], d["file"], ""


def with_role_definition(b, nid, prompt: str) -> tuple:
    """描いた指示書の頭に役の定義を置く。返り (指示書, 定義のファイル, 無い時の知らせ)"""
    body, def_file, missing = role_definition(b, nid)
    if body:
        prompt = f"## お前の役の定義（{agent_type_of(b, b.nodes[nid])}）\n\n{body}\n\n---\n\n{prompt}"
    return prompt, def_file, missing


REJECT_HEADING = "## 前の回の受け付けが拒んだ理由"


def with_reject(prompt: str, reason: str) -> str:
    """道具ゼロの役の指示書の頭に、前の拒否の文を貼る（役はファイルを読めない。$LOOP_PREV で貼ると Archon が文の中の $… を
    置き換え直す。裁定 R44）"""
    return (f"{REJECT_HEADING}\n\n前の回の返答は受け付けで拒まれた。下の理由のところを直した返答を丸ごと出し直せ"
            f"（直した所だけを返すな）:\n\n```text\n{reason}\n```\n\n---\n\n{prompt}")


# ---------------------------------------------------------------- 受け付け（出し直しの輪）
def _read_json(path: pathlib.Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return default
    except (OSError, ValueError) as e:
        raise BoardGap(f"{path} が読めない: {e}") from None


def _write_json(path: pathlib.Path, doc) -> None:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def rejects(b, nid: str) -> list:
    """この周のこの節の拒否の控え（古い順）"""
    rows = _read_json(b.work(REJECTS_NAME), [])
    return [r for r in rows if isinstance(r, dict) and r.get("node") == nid]


def last_reject_file(b, nid: str) -> str:
    rows = rejects(b, nid)
    return str(rows[-1].get("reason_file") or "") if rows else ""


def accept_role(board_dir: pathlib.Path, nid: str, raw: str, repo: pathlib.Path, *, snapshot_name: str | None = None,
                give_up_after: int = GIVE_UP_AFTER, take=None) -> dict:
    """役の返答 raw（JSON の文字列）を entry.take で盤面に渡す。返り {ok, done, give_up, reason, reason_file, node} と、通れば
    entry.take の欄（ready・asking・halted・out_file）。拒否（読めない返答・写しの AnswerReject・読むだけの役の作業ツリーの変化）は
    理由の本文を盤面の reject-take_<節>-<連番>.txt に字のまま書き、この周の拒否の控えに積む。この周のこの節の拒否が
    give_up_after 回に達したら done・give_up（輪はそこで抜け、出口が盤面を止める）。board_dir は script_io.board_dir が
    返した値（$ の柵を当てた後）。take(board_dir, reply, repo) -> dict は entry.take の代わりに盤面へ渡す口（ブロックだけの
    検査を前に置く時。返りは entry.take と同じ形）。BoardGap・ほかの Reject（止めた run など）は投げる"""
    reply, why = parse_reply(raw)
    if reply is None:
        out = {"ok": False, "reason": why}
    elif take is not None:
        out = take(board_dir, reply, repo)
    else:
        out = entry.take(board_dir, nid, reply, repo, snapshot_name=snapshot_name)
    if out.get("ok") is True:
        return {**out, "done": True, "give_up": False, "reason_file": "", "node": nid}
    b = entry.open_board(board_dir)
    rf = script_io._write_reason(pathlib.Path(board_dir), f"take_{nid}", str(out.get("reason", "")))
    inst = b.rd["instances"].get(nid) or {}
    path = b.work(REJECTS_NAME)
    rows = _read_json(path, [])
    rows.append({"node": nid, "attempt": inst.get("attempts", 1),
                 "at": datetime.datetime.now(datetime.timezone.utc).isoformat(), "reason_file": rf})
    _write_json(path, rows)
    give_up = sum(1 for r in rows if isinstance(r, dict) and r.get("node") == nid) >= give_up_after
    return {**out, "ok": False, "done": give_up, "give_up": give_up, "reason_file": rf, "node": nid}


def main_accept(nid: str, *, snapshot_name: str | None = None, give_up_after: int = GIVE_UP_AFTER,
                reply_env: str = "INPUTS_REPLY", after=None, take=None) -> int:
    """accept_role の節の入口。INPUTS_REPLY と ARTIFACTS_DIR（盤面は $ARTIFACTS_DIR/board。script_io.board_dir の柵）を読み、
    1 行の JSON を出して 0（拒否も 0）。after(盤面, 返り) -> 返り は出す前に当てる（ブロックが出口の欄を足す）。
    環境変数の欠け・BoardGap・Reject・思わぬ誤りは標準出力に何も出さず標準エラーに 1 行で 2"""
    if reply_env not in os.environ:
        print(f"環境変数が無い: {reply_env}", file=sys.stderr)
        return 2
    board = script_io.board_dir()
    if board is None:
        return 2
    try:
        out = accept_role(board, nid, os.environ[reply_env], pathlib.Path.cwd(), snapshot_name=snapshot_name,
                          give_up_after=give_up_after, take=take)
        if after is not None:
            out = after(board, out)
    except (BoardGap, Reject) as e:
        print(f"{nid} の受け付けを回せない（{type(e).__name__}）: {' '.join(str(e).split())}", file=sys.stderr)
        return 2
    except Exception as e:   # 思わぬ誤りも 1 行と 2（traceback を出さない）
        print(f"{nid} の受け付けの内部の誤り: {type(e).__name__}: {' '.join(str(e).split())}", file=sys.stderr)
        return 2
    script_io._emit(out)
    return 0


def _reason_text(path: str) -> str:
    try:
        return " ".join(pathlib.Path(path).read_text(encoding="utf-8").split())
    except OSError as e:
        return f"理由のファイル {path} が読めない（{type(e).__name__}）"


def gave_up(board_dir: pathlib.Path, nid: str, *, by: str, give_up_after: int = GIVE_UP_AFTER) -> str:
    """出口の諦めの腕（受けた返答の無い節の出口が呼ぶ）。この周のこの節の拒否が give_up_after 件あれば、最後の拒否の文で
    盤面を止め（もう止まっていれば止め直さない）、止めた理由を返す。届いていなければ空（輪を抜けた理由が拒否でない＝配線の誤り）"""
    b = entry.open_board(pathlib.Path(board_dir), allow_halted=True)
    rows = rejects(b, nid)
    if len(rows) < give_up_after:
        return ""
    reason = _gave_up_text(nid, len(rows), _reason_text(str(rows[-1].get('reason_file') or '')))
    _stop_once(b, reason, by)
    return reason


def _gave_up_text(name: str, count: int, last: str) -> str:
    """諦めた理由の 1 行（gave_up と given_up_reason が共に使う文の正本）"""
    return f"{name} の返答が {count} 回とも受け付けで拒まれた（最後の拒否: {' '.join(str(last).split())}）"


def _stop_once(b, reason: str, by: str) -> None:
    """盤面を reason で止める（もう止まっていれば止め直さない。gave_up と stop_line が共に使う）"""
    if not (b.state.get("halted") or b.state.get("stop")):
        b.stop(reason, by=by)


# ---------------------------------------------------------------- 盤面の節でない受け付けの done
def rejects_path(board: pathlib.Path, name: str) -> pathlib.Path:
    """盤面の節でない受け付け name の拒否の控え（盤面の根。[{at, reason}]）"""
    return pathlib.Path(board) / f"rejects-{safe_name(name)}.json"


def clear_rejects(board: pathlib.Path, name: str) -> None:
    """控えを消す（ブロックの intake が役を起こす前に。前の呼び出しの拒否を数えない）"""
    rejects_path(board, name).unlink(missing_ok=True)


def with_done(board: pathlib.Path, name: str, out: dict, *, give_up_after: int = GIVE_UP_AFTER) -> dict:
    """script_io.main の finish: 通れば done。拒否は控えに積み、give_up_after 回目で done（輪はそこで抜け、出口が諦めを扱う）"""
    if out.get("ok") is True:
        return {**out, "done": True}
    path = rejects_path(board, name)
    rows = _read_json(path, [])
    rows.append({"at": datetime.datetime.now(datetime.timezone.utc).isoformat(), "reason": str(out.get("reason", ""))})
    _write_json(path, rows)
    return {**out, "done": len(rows) >= give_up_after}


def given_up_reason(board: pathlib.Path, name: str, *, give_up_after: int = GIVE_UP_AFTER) -> str:
    """控えの拒否が give_up_after 件あれば、諦めた理由の 1 行（最後の拒否の文）。届いていなければ空"""
    rows = _read_json(rejects_path(board, name), [])
    if not isinstance(rows, list) or len(rows) < give_up_after:
        return ""
    last = rows[-1].get("reason", "") if isinstance(rows[-1], dict) else ""
    return _gave_up_text(name, len(rows), last)


def on_line(board: pathlib.Path) -> bool:
    """board がラインの盤面か（state.json が在る）。無ければブロックを単独で回した"""
    return (pathlib.Path(board) / "state.json").is_file()


def line_stopped(board: pathlib.Path) -> str:
    """ラインの盤面がもう止まっていれば止めた理由（止まっていない・単独の run なら空）"""
    if not on_line(board):
        return ""
    st = entry.open_board(pathlib.Path(board), allow_halted=True).state
    info = st.get("stop") or st.get("halted")
    return str((info or {}).get("reason") or "盤面が止まっている") if info else ""


def stop_line(board: pathlib.Path, reason: str, *, by: str) -> None:
    """ラインの盤面を reason で止める（もう止まっていれば止め直さない）。単独の run（盤面が無い）では何もしない"""
    if not on_line(board):
        return
    _stop_once(entry.open_board(pathlib.Path(board), allow_halted=True), reason, by)


# ---------------------------------------------------------------- スクリプトの入口
def script_main(fn, inputs=(), *, not_ok_is_wiring: bool = False, fence: bool = False, take: str = "") -> int:
    """ブロックのスクリプトの入口。環境変数 ARTIFACTS_DIR（空も欠け）と inputs（INPUTS_* の名前）を読み、
    fn(盤面の置き場 $ARTIFACTS_DIR/board, repo=cwd, {名前: 値}) の返りを 1 行の JSON で出して 0。予定の状態（拒否・止めた・
    回す物が無い）は fn が dict で返す。0 でないのは配線の誤りだけ: 環境変数の欠け・BoardGap・写しの Reject（止めた run への
    書き込み・git が効かない など）・思わぬ誤りは標準出力に何も出さずに標準エラーに 1 行出して 2（Archon が起こし直す道に
    乗せない。TA19）。not_ok_is_wiring なら返りの {ok: False} も配線の誤りとして 2（支度が盤面に要る物を見つけない節）。
    fence なら盤面の置き場は script_io.board_dir の値（resolve 済み。解決したパスが $ を含めば 2——reason_file のパスが
    Archon の置き換えに通らないように）。take（名の頭）を与えると、返りが done を持つ時（受け付けの返り）は
    script_io.emit_result を通す（拒否は理由の本文を盤面の reject-<take>_<節>-<連番>.txt に書き reason_file を足す。裁定 R44）"""
    missing = [n for n in (script_io.ARTIFACTS_ENV, *inputs) if n not in os.environ]
    if script_io.ARTIFACTS_ENV not in missing and not os.environ[script_io.ARTIFACTS_ENV]:
        missing.append(script_io.ARTIFACTS_ENV)
    if missing:
        print(f"環境変数が無い: {', '.join(missing)}", file=sys.stderr)
        return 2
    if fence:
        board_dir = script_io.board_dir()
        if board_dir is None:
            return 2
    else:
        board_dir = pathlib.Path(os.environ[script_io.ARTIFACTS_ENV]) / script_io.BOARD_DIR
    try:
        out = fn(board_dir, pathlib.Path.cwd(), {n: os.environ[n] for n in inputs})
    except (BoardGap, Reject) as e:
        print(f"{type(e).__name__}: {' '.join(str(e).split())}", file=sys.stderr)
        return 2
    except Exception as e:   # 思わぬ誤りも 1 行と 2（traceback を出さない）
        print(f"内部の誤り: {type(e).__name__}: {' '.join(str(e).split())}", file=sys.stderr)
        return 2
    if not_ok_is_wiring and isinstance(out, dict) and out.get("ok") is False:
        print(f"配線の誤り: {' '.join(str(out.get('reason', '')).split())}", file=sys.stderr)
        return 2
    if take and isinstance(out, dict) and "done" in out:
        return script_io.emit_result(board_dir, f"{take}_{out.get('node', 'take')}", out)
    script_io._emit(out)   # 1 行の出し方は受け付けのスクリプトと同じ
    return 0


def parse_reply(raw):
    """役の返答（Archon が $<役>.output を JSON の文字列で渡す）を dict に。読めなければ (None, 理由)。文は script_io.main と同じ"""
    try:
        reply = json.loads(raw)
    except (TypeError, json.JSONDecodeError) as e:
        return None, f"返答が JSON として読めない: {e}（頭: {str(raw)[:200]!r}）"
    if not isinstance(reply, dict):
        return None, f"返答が JSON のオブジェクトでない（{type(reply).__name__}）"
    return reply, ""
