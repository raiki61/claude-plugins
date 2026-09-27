"""役の節を回す共通の口（P1 計画 Task 13。C13・〔振〕10.3）。本線（graphloops）の指示書を engine と同じ描き方で描く式と、
ブロックのスクリプトの入口の約束を 1 か所に置く（前は rejudge・refix に写しが在った）。

- render_body:    engine の emit_instance と同じ描き方（node_prompt → ctx → pointers.snapshot → Renderer。cap なし・graph の
                  reads だけ・ref・schema の断り）で本文を描き、(本文, 番号の控え) を返す。描けなければ BoardGap
- render_prompt:  render_body の本文の頭に head（役の定義など）を置き、今の周の作業ファイル prompt-<節>.md に書く。この周に
                  この節の拒否が在れば、最後の拒否の理由のファイルのパスを頭の 1 行で名指す（文は貼らない。裁定 R44）
- accept_role:    出し直しの輪の受け付け（entry.take）。拒否は理由の本文を盤面の reject-take_<節>-<連番>.txt に書き
                  （entry.main_take と同じ名）、この周の拒否の控え role-rejects.json に積み、give_up_after 回目で done・give_up
                  （輪を max_iterations で落とさない。裁定 R50）
- main_accept:    accept_role の節の入口（INPUTS_REPLY・ARTIFACTS_DIR）
- script_main:    ブロックのスクリプトの入口（ARTIFACTS_DIR と INPUTS_* を読み、fn の返りを 1 行の JSON で出す。fence なら
                  盤面のパスに $ の柵、take なら受け付けの返りに reason_file を足す）
- parse_reply:    役の返答（$<役>.output の JSON の文字列）を dict に

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

from board import BoardGap  # noqa: E402  （board が写しの engine を sys.path に足す。engine より先に）
from engine import pointers as _pointers  # noqa: E402
from engine.render import ReadsViolation, Renderer, node_prompt  # noqa: E402
from engine.util import Reject, dump, safe_name  # noqa: E402
import entry  # noqa: E402
import script_io  # noqa: E402

PROMPTS_COPY = _CORE / "gl-prompts"   # 写しと同じ commit から写した本線の指示書（graphloops/ と同じ並び）
SCHEMA_NOTE = ("\n\n---\n返答はこの JSON Schema に合う JSON だけ（前後に文を付けない）。"
               '文字列値の中の " は必ず \\" にエスケープしろ——生のまま入れると返答まるごとが'
               "読めずに捨てられる:\n")
PROMPT_PREFIX = "prompt-"               # render_prompt が書く今の周の作業ファイルの名の頭
REJECTS_NAME = "role-rejects.json"      # accept_role が積むこの周の拒否の控え [{node, attempt, at, reason_file}]
GIVE_UP_AFTER = 3                       # 輪の max_iterations と同じ数（ブロックの試験が YAML と突き合わせる）
REJECT_LINE = ("前の回の返答は受け付けで拒まれた。理由はファイル {path} に在る。先に Read で読み、そこを直した返答を丸ごと"
               "出し直せ（直した所だけを返すな）。")


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
                template: str | None = None, ctx_hook=None) -> tuple:
    """engine の emit_instance と同じ描き方の本文（cap なし。指示書は役がファイルで読む）と番号の控え（pointers.snapshot の
    名前の列。mark_launched の pointers= に渡す形。pointers を持たない節は空の列）。reads_only が偽なら graph の reads で
    穴を絞らない。template は graph の指示書（node_prompt）の代わりに描く本文（ブロックが別の置き場に持つ本線の写し）。
    ctx_hook(ctx) は描く前に ctx を足す口（engine が足す欄——検証器の結果 validation・ラインに無い節の出力の代わり など）。
    この周に待っている instance が無い・描けない（reads に無い穴・盤面の欄の欠け・番号の穴の欠け）は BoardGap"""
    n = b.nodes[nid]
    inst = b.rd["instances"].get(nid)
    if not inst or inst.get("status") != "pending":
        raise BoardGap(f"この周に節 {nid} の待っている instance が無い")
    tpl = node_prompt(prompt_graph_path(b, n, prompts_dir), n) if template is None else template
    ctx = b.ctx()
    ctx["node"] = {"skills": inst.get("skills") or []}   # engine と同じく、出した時点の applies を持つ写し（settle が置いた物）
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
    if n.get("schema"):
        text += SCHEMA_NOTE + dump(n["schema"])
    return text, snap


def prompt_name(nid: str) -> str:
    return f"{PROMPT_PREFIX}{safe_name(nid)}.md"


def render_prompt(b, nid: str, *, prompts_dir: pathlib.Path = PROMPTS_COPY, head: str = "",
                  reads_only: bool = True) -> pathlib.Path:
    """本線の指示書を render_body で描き、head（役の定義など）を頭に置いて b.work(prompt-<節>.md) に書き、パスを返す。
    この周にこの節の拒否（accept_role の控え）が在れば、最後の拒否の理由のファイルのパスを 1 行目で名指す（理由の文そのものは
    貼らない——役が Read で読む。裁定 R44）"""
    body, _ = render_body(b, nid, prompts_dir=prompts_dir, reads_only=reads_only)
    parts = []
    last = last_reject_file(b, nid)
    if last:
        parts.append(REJECT_LINE.format(path=last))
    if head:
        parts.append(head.rstrip("\n"))
    parts.append(body)
    p = b.work(prompt_name(nid))
    p.write_text("\n\n".join(parts), encoding="utf-8")
    return p


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
                give_up_after: int = GIVE_UP_AFTER) -> dict:
    """役の返答 raw（JSON の文字列）を entry.take で盤面に渡す。返り {ok, done, give_up, reason, reason_file, node} と、通れば
    entry.take の欄（ready・asking・halted・out_file）。拒否（読めない返答・写しの AnswerReject・読むだけの役の作業ツリーの変化）は
    理由の本文を盤面の reject-take_<節>-<連番>.txt に字のまま書き、この周の拒否の控えに積む。この周のこの節の拒否が
    give_up_after 回に達したら done・give_up（輪はそこで抜け、出口が盤面を止める）。board_dir は script_io.board_dir が
    返した値（$ の柵を当てた後）。BoardGap・ほかの Reject（止めた run など）は投げる"""
    reply, why = parse_reply(raw)
    out = {"ok": False, "reason": why} if reply is None else entry.take(board_dir, nid, reply, repo, snapshot_name=snapshot_name)
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
                reply_env: str = "INPUTS_REPLY") -> int:
    """accept_role の節の入口。INPUTS_REPLY と ARTIFACTS_DIR（盤面は $ARTIFACTS_DIR/board。script_io.board_dir の柵）を読み、
    1 行の JSON を出して 0（拒否も 0）。環境変数の欠け・BoardGap・Reject・思わぬ誤りは標準出力に何も出さず標準エラーに 1 行で 2"""
    if reply_env not in os.environ:
        print(f"環境変数が無い: {reply_env}", file=sys.stderr)
        return 2
    board = script_io.board_dir()
    if board is None:
        return 2
    try:
        out = accept_role(board, nid, os.environ[reply_env], pathlib.Path.cwd(), snapshot_name=snapshot_name,
                          give_up_after=give_up_after)
    except (BoardGap, Reject) as e:
        print(f"{nid} の受け付けを回せない（{type(e).__name__}）: {' '.join(str(e).split())}", file=sys.stderr)
        return 2
    except Exception as e:   # 思わぬ誤りも 1 行と 2（traceback を出さない）
        print(f"{nid} の受け付けの内部の誤り: {type(e).__name__}: {' '.join(str(e).split())}", file=sys.stderr)
        return 2
    script_io._emit(out)
    return 0


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
