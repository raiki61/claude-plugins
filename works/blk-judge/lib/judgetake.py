"""blk-judge の受け付けと出口の芯（run 27 の再発防止）。ラインの盤面（$ARTIFACTS_DIR/board/state.json）が在れば、判定役の返答を
本線と同じ受け付け——盤面の p2.diagnose の done（写しの judge_output・writes・check_record。rolekit.accept_role → entry.take）——
に通す。前は記憶の中の空の記録（check_judge）で受け、盤面の受け付けは後ろの境の節 h-plan が初めて当てていたので、素材を読む
決まり（awaiting_human の素材には kind=awaiting）に外れた返答が判定役に返らず、線が止まった（run 27）。

- accept(board, raw, repo): ラインの盤面の受け付け。拒否は理由の本文を盤面の reject-take_p2.diagnose-<連番>.txt に書き、
  判定役へはパスだけを返す（R44）。この周の 3 回目の拒否で done・give_up（輪を max_iterations で落とさない。R50）。
  通れば盤面が受けた返答（judge_output が正規化した物）を盤面の judgment.json に写し、open_units を足す
- take(board, reply, repo): ラインの盤面の受け付けの前に、class_query の例（hits・misses。querytest）で問いそのものを試す。
  例は外して写しの受け付けに渡し、通れば盤面の query-examples.json に置く（単独の run は core の check_judge が同じことをする）
- finish(board, out): accept の後ろ半分（rolekit.main_accept の after）。例を judgment.json に戻す
- with_done(board, out): 盤面の無い単独の run（check_judge）の受け付けに輪を抜ける旗 done を足す（この run の拒否の数で数える）
- collect(board): 出口 {ok, open_units, need_fix, judgment_file, one_shot}。judgment.json が無い時、ラインの盤面なら最後の拒否の
  文で盤面を止めて（by works:judge）ok false、単独なら Unreadable（スクリプトは 1）
"""
import json
import pathlib
import sys

sys.dont_write_bytecode = True

_CORE = pathlib.Path(__file__).resolve().parents[2] / ".shared" / "core"
if str(_CORE) not in sys.path:
    sys.path.insert(0, str(_CORE))

import accept as core_accept  # noqa: E402
import entry  # noqa: E402
import querytest  # noqa: E402
import rolekit  # noqa: E402
import script_io  # noqa: E402
from engine.rules import validator_module  # noqa: E402  （board が写しの engine を sys.path に足した後）

NODE = "p2.diagnose"
TREE_FILE = "judge-tree.json"            # 判定役を起こす前の作業ツリーの姿（b.work。judge-brief が entry.snapshot で置く）
GIVE_UP_AFTER = rolekit.GIVE_UP_AFTER    # 輪 judge-loop の max_iterations と同じ（tests/test_blk_judge.py が YAML と突き合わせる）
STOP_BY = "works:judge"                  # 受け付けを通った判定が無いまま輪を抜けた盤面の state.stop.by
STANDALONE_FN = "check_judge"            # 単独の run の拒否の理由のファイルの名の頭（script_io が fn の名で付ける）


class Unreadable(Exception):
    """出口を組めない（単独の run で受け付けを通った判定が無い・judgment.json の形が崩れた）。文は 1 行にして標準エラーへ"""


def on_line(board) -> bool:
    """board がラインの盤面か（state.json が在る）。無ければブロックを単独で回した"""
    return (pathlib.Path(board) / "state.json").is_file()


def finish(board, out: dict) -> dict:
    """rolekit.accept_role の返りに出口の欄を足す。通れば盤面が受けた返答に class_query の例（query-examples.json）を戻して
    judgment.json に写し、open_units は検証器の is_open"""
    if out.get("ok") is not True:
        return {**out, "open_units": [], "judgment_file": ""}
    b = entry.open_board(pathlib.Path(board), allow_halted=True)
    doc = json.loads((b.dir / out["out_file"]).read_text(encoding="utf-8"))
    path = core_accept.write_board(board, core_accept.JUDGMENT_FILE, querytest.restore(doc, board))
    V = validator_module(b)
    return {**out, "open_units": [u["key"] for u in doc["units"] if V.is_open(u)], "judgment_file": str(path)}


def take(board, reply: dict, repo) -> dict:
    """rolekit.accept_role の take: 例で問いを試し、例を外した返答を entry.take に渡す（写しの型は例の欄を持たない）。
    通れば例を盤面の query-examples.json に置く（finish が judgment.json に戻す）"""
    is_open = validator_module(_Validator).is_open
    errs = querytest.problems(reply.get("units"), is_open)
    if errs:
        return {"ok": False, "reason": "class_query の例が問いと合わない: " + "; ".join(errs)}
    bare, examples = querytest.split(reply, is_open)
    out = entry.take(pathlib.Path(board), NODE, bare, pathlib.Path(repo), snapshot_name=TREE_FILE)
    if out.get("ok") is True:
        querytest.save(board, examples, replace=True)
    return out


def accept(board, raw: str, repo) -> dict:
    """ラインの盤面の受け付け（judge-accept）。返り {ok, done, give_up, reason, reason_file, node, open_units, judgment_file}
    （通れば entry.take の欄も）。BoardGap・止めた盤面への Reject は投げる（回す側の誤り）"""
    return finish(board, rolekit.accept_role(pathlib.Path(board), NODE, raw, pathlib.Path(repo), snapshot_name=TREE_FILE,
                                             give_up_after=GIVE_UP_AFTER, take=take))


def with_done(board, out: dict) -> dict:
    """単独の run の受け付けの返りに done を足す: 通った時か、この run の拒否（盤面の reject-check_judge-<連番>.txt。
    この返りの拒否はまだ書かれていないので 1 を足す）が GIVE_UP_AFTER 回に達した時"""
    if out.get("ok") is True:
        return {**out, "done": True}
    n = len(list(script_io.scope_dir(board).glob(f"reject-{STANDALONE_FN}-*.txt"))) + 1   # 拒否の理由の置き場（script_io）
    return {**out, "done": n >= GIVE_UP_AFTER}


def _give_up(board) -> dict:
    """ラインの盤面で受け付けを通った判定が無いまま輪を抜けた: 最後の拒否の文で盤面を止め（止まっていなければ）、ok false の出口"""
    b = entry.open_board(pathlib.Path(board), allow_halted=True)
    if not (b.state.get("halted") or b.state.get("stop")):
        rows = rolekit.rejects(b, NODE)
        if rows:
            last = pathlib.Path(str(rows[-1].get("reason_file") or ""))
            try:
                text = " ".join(last.read_text(encoding="utf-8").split())
            except OSError as e:
                text = f"理由のファイル {last} が読めない（{type(e).__name__}）"
            reason = f"{NODE} の返答が {len(rows)} 回とも受け付けで拒まれた（最後の拒否: {text}）"
        else:
            reason = f"受け付けを通った判定が無いまま判定の輪を抜けた（{NODE} は {b.node_state(NODE)}）"
        b.stop(reason, by=STOP_BY)
    return {"ok": False, "open_units": [], "need_fix": False, "judgment_file": "", "one_shot": ""}


def collect(board) -> dict:
    """判定のブロックの出口。judgment.json（この呼び出しの受け付けが書いた物。前の残りは intake が消す）から
    {ok, open_units, need_fix, judgment_file, one_shot}。無ければ、ラインの盤面は _give_up、単独は Unreadable"""
    board = pathlib.Path(board)
    path = board / core_accept.JUDGMENT_FILE
    try:
        judgment = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        if isinstance(e, FileNotFoundError) and on_line(board):
            return _give_up(board)
        raise Unreadable(f"盤面の {core_accept.JUDGMENT_FILE} が読めない（{path}: {type(e).__name__}: {e}）"
                         "——受け付けを通った判定が無い") from None
    units = judgment.get("units") if isinstance(judgment, dict) else None
    one_shot = judgment.get("one_shot") if isinstance(judgment, dict) else None
    if not isinstance(units, list) or not all(isinstance(u, dict) and "key" in u and "label" in u for u in units) \
            or not isinstance(one_shot, str):
        raise Unreadable(f"盤面の {core_accept.JUDGMENT_FILE} の形が崩れている（units[].key・label と one_shot が要る）: {path}")
    V = validator_module(_Validator)
    open_units = [u["key"] for u in units if V.is_open(u)]
    return {"ok": True, "open_units": open_units, "need_fix": bool(open_units), "judgment_file": str(path),
            "one_shot": one_shot}


class _Validator:
    """validator_module に渡す入れ物（写しの検証器のパスだけを持つ。盤面を開かずに is_open を引く）"""
    state = {"validator": str(core_accept.VALIDATOR)}
