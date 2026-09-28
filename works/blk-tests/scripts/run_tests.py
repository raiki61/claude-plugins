# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""テストを走らせる節（blk-tests の run）。形は INPUTS_MODE で選ぶ: plain（既定）・mid・final（仕様 3.5・裁定 TA4・TA5）。

plain（既定。1 本目と線 C の mutgate の約束のまま。INPUTS_MODE が無い・空の呼び出しもこれ）:
  INPUTS_CMD（節の with: の cmd）を対象リポジトリの根（cwd）で `bash -c` に渡し、標準出力と標準エラーを
  $ARTIFACTS_DIR/board/tests.log に置き、標準入力は閉じる（入力待ちで止まらない）。盤面は開かない。コマンドは本文に
  差し込まず環境変数のまま渡すので、値がシェルの記号を含んでもデータのまま届く。
  出口: {"ok": true, "green": <終了コードが 0 か>, "log": <tests.log のパス>} を 1 行。bash を起こせない（exit None）・
  シェルの予約値 126・127（起こせなかった疑い）の時だけ launch に tree_run.launch_kind の "broken"・"suspect" を足す（どちらも
  green: false。普通の赤・緑の鍵は ok・green・log のまま）。コマンドが空・空白だけなら何も走らせずに 1（緑と言わない）。
mid（中の関所のためのテスト。盤面の節には書かない）:
  盤面（$ARTIFACTS_DIR/board）を entry.open_board で開き、対象の根の宣言 .review-checks.json（写しの engine/declared.py の
  読み方）の suite が読めれば段を 1 つずつ shell を通さずに、宣言が無ければ cmd を `bash -c` で走らせる。宣言が在るのに
  読めなければ engine と同じく走らせない（cmd にも落とさない）。ログは b.work("mid-tests.log")、結果は
  b.work("mid-tests.json")。走れなかった回（読めない宣言・宣言も cmd も無い）は green: false で理由をログと結果に残す。
final（最後のテスト。盤面の p4.ci）:
  entry.run_ci(b, "p4.ci", test_cmd=cmd)（engine が宣言を走らせ、cmd が在れば宣言の段の後に cmd の段も足して両方が緑の時だけ
  clean。cmd が宣言の段と同じコマンドなら 1 度だけ走らせ、出口の test_cmd_same_as にその段の名。任せ先に落ちたら cmd を
  走らせた素材を done）→ settle。
  green は p4.ci が置いた素材 materials.local_checks の status が clean か。ログは run_ci の返りの log（周の番号を組み立てない）。
  任せ先に落ちて cmd も空（run_ci の role_needed）なら、素材を読まずに green: false・by: role_needed・log は空——p4.ci は
  任せ先に落ちたまま待ち、ラインが blk-ci（CI の任せ先の役）を回す（裁定 R52）。run_ci が拒んだ（CiRefused）は終了コード 1 で理由を stderr。
mid・final の出口は plain の欄に suites（段ごとの {name, exit}。起こせない（exit None）・起こせなかった疑いの段には段の
argv で見た launch も）と by（mid・engine・role・role_needed）を足す。どの形も赤で止めない
（ok: true・green: false）——赤を人の関所に見せるのがこの段の仕事。

どの形も走らせるのは tree_run（.shared/core）——自分のプロセスグループで起こし、run が止められたら（SIGINT・SIGTERM・
SIGHUP、直下の親の uv が消えた）テストが背景に起こした孫まで木ごと止める。止められた回は木を止め終えてから、出口を出さずに
128+信号で終わる。テストには uv run の外の環境を渡す（tree_run.outside_env。PYTHONDONTWRITEBYTECODE=1 も立てる。決まりの
正本はそこ）。Archon は script の節を `uv run <このファイル>` で起こすので、そのまま渡すと `python3 -m pytest` が uv の
python を掴んで偽の赤になる。
ARTIFACTS_DIR が欠け・空、知らない形、盤面の口が読めない・盤面の誤り（BoardGap・止めた run への書き込み）は 2（回す側の誤り）。
"""
import sys
from pathlib import Path

sys.dont_write_bytecode = True   # 下の import が pack の中に __pycache__ を作らないように。必ず import より前
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / ".shared" / "core"))   # 頭に入れる（Ruling R7）
import json  # noqa: E402
import os  # noqa: E402
import subprocess  # noqa: E402

import script_io  # noqa: E402
import tree_run  # noqa: E402

CMD_ENV = "INPUTS_CMD"
MODE_ENV = "INPUTS_MODE"
INPUTS = (CMD_ENV, MODE_ENV)   # 裁定 TA16: 読む INPUTS_* の組（Task 17 の試験が YAML の with: の鍵と突き合わせる）
MODES = ("plain", "mid", "final")
LOG_NAME = "tests.log"
MID_LOG = "mid-tests.log"
MID_RESULT = "mid-tests.json"
CI_NODE = "p4.ci"


class Refused(Exception):
    """final が走らせられない（終了コード 1。文は人に向けた 1 行）"""


def _run(argv, log_f, cwd=None) -> int | None:
    """argv を tree_run で走らせ、標準出力と標準エラーを log_f に。起こせなければ（OSError）ログに『起こせない』を書いて None
    （engine の tree_runner の exit None と同じ）。止められたら tree_run.Stopped が上がる"""
    try:
        return tree_run.run(argv, stdin=subprocess.DEVNULL, stdout=log_f, stderr=subprocess.STDOUT, cwd=cwd,
                            env=tree_run.outside_env(os.environ))
    except OSError as e:
        log_f.write(f"起こせない: {e}\n".encode("utf-8"))
        log_f.flush()
        return None


def _suite(name, argv, code) -> dict:
    """mid・final の段 {name, exit}。clean・red 以外（起こせない・起こせなかった疑い）の時だけ launch に argv で見た
    tree_run.launch_kind（entry の suites_line・env_only_red は名で決めずにこれを読む）"""
    kind = tree_run.launch_kind(code, argv)
    return {"name": name, "exit": code, **({"launch": kind} if kind in ("broken", "suspect") else {})}


def run_plain(cmd: str, artifacts: Path) -> dict:
    board = artifacts / script_io.BOARD_DIR
    board.mkdir(parents=True, exist_ok=True)
    log = board / LOG_NAME
    argv = ["bash", "-c", cmd]
    with open(log, "wb") as f:
        code = _run(argv, f)
    kind = tree_run.launch_kind(code, argv)
    out = {"ok": True, "green": kind == "clean", "log": str(log)}
    if kind in ("broken", "suspect"):
        out["launch"] = kind
    return out


def _repo_root(b) -> Path:
    """対象の根（engine の run_engine と同じ引き方。盤面を開いた時に inputs.cwd へ向いた git）。引けなければ inputs.cwd"""
    from engine import util
    return Path(util.repo_root() or b.state["inputs"]["cwd"])


def run_mid(b, cmd: str) -> dict:
    """中の関所のためのテスト。盤面の state・record・trace は書かない（作業ファイルは今の周の b.work の 2 つだけ）"""
    from engine import declared
    root = _repo_root(b)
    log, res = b.work(MID_LOG), b.work(MID_RESULT)
    d = declared.read(root)
    suites, doc = [], {"by": "mid"}
    with open(log, "wb") as f:
        def note(text):
            f.write((text + "\n").encode("utf-8"))
            f.flush()   # 子が同じファイルに書く前に

        if d is not None and "error" in d:
            doc.update(source="none", reason=f"宣言が読めないので走らせない（engine と同じ。cmd にも落とさない）: {d['error']}")
            note(doc["reason"])
        elif d is not None:
            doc.update(source="declared", sha=d["sha"])
            for s in d["steps"]:
                note(f"== {s['name']}: {json.dumps(s['argv'], ensure_ascii=False)}")
                code = _run(list(s["argv"]), f, cwd=str(root))
                note(f"== {s['name']}: exit {code}")
                suites.append(_suite(s["name"], s["argv"], code))
        elif cmd.strip():
            doc["source"] = "cmd"
            argv = ["bash", "-c", cmd]
            suites.append(_suite("cmd", argv, _run(argv, f, cwd=str(root))))
        else:
            doc.update(source="none", reason=f"走らせる物が無い: 対象の根に {declared.DECL_NAME} が無く、テストのコマンドも空")
            note(doc["reason"])
    green = bool(suites) and all(s["exit"] == 0 for s in suites)
    doc.update(green=green, suites=suites, log=str(log))
    tmp = res.with_name(res.name + ".tmp")
    tmp.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, res)
    return {"ok": True, "green": green, "log": str(log), "suites": suites, "by": "mid"}


def run_final(b, cmd: str, *, run_ci, refused=()) -> dict:
    """最後のテスト（盤面の p4.ci）→ settle。run_ci の拒否（refused）は Refused。
    run_ci が role_needed（任せ先に落ちて cmd も空。宣言が無い時も、宣言が在るのに engine が落ちた時も）なら、盤面の素材を
    読まずに green: false・by: role_needed を返す（ラインが blk-ci を回して p4.ci を渡す。裁定 R52）——素材はまだ修正前の
    周の頭の物で、それを最後の結果にすると修正後のテストを走らせずに緑と言う（Task 7 の審査 I2）"""
    try:
        ci = run_ci(b, CI_NODE, test_cmd=cmd)
    except refused as e:
        raise Refused(f"最後のテスト（{CI_NODE}）を走らせられない: {e}") from None
    if ci["by"] == "role_needed":
        return {"ok": True, "green": False, "log": "", "suites": [], "by": "role_needed"}
    material = b.record.get("materials", {}).get("local_checks") or {}
    check = b.record.get("process", {}).get("checks", {}).get(CI_NODE) or {}
    suites = [_suite(r["name"], r.get("argv") or (), r["exit"]) for r in check.get("runs") or []] if ci["by"] == "engine" else []
    b.settle()
    same = {"test_cmd_same_as": ci["same_as"]} if ci.get("same_as") else {}
    return {"ok": True, "green": material.get("status") == "clean", "log": ci["log"], "suites": suites, "by": ci["by"], **same}


def main() -> int:
    if not os.environ.get(script_io.ARTIFACTS_ENV):
        print(f"環境変数が無い: {script_io.ARTIFACTS_ENV}", file=sys.stderr)
        return 2
    artifacts = Path(os.environ[script_io.ARTIFACTS_ENV])
    mode = os.environ.get(MODE_ENV) or "plain"
    if mode not in MODES:
        print(f"知らない形 {MODE_ENV}={mode!r}（{' / '.join(MODES)}）", file=sys.stderr)
        return 2
    cmd = os.environ.get(CMD_ENV, "")
    try:
        if mode == "plain":
            if not cmd.strip():
                print("テストのコマンドが空", file=sys.stderr)
                return 1
            out = run_plain(cmd, artifacts)
        else:
            try:
                import entry
            except ImportError as e:
                print(f"盤面の口 entry が読めない（mid・final は盤面を使う）: {e}", file=sys.stderr)
                return 2
            from board import BoardGap
            from engine.util import Reject
            try:
                b = entry.open_board(artifacts / script_io.BOARD_DIR)
                if mode == "mid":
                    out = run_mid(b, cmd)
                else:
                    out = run_final(b, cmd, run_ci=entry.run_ci, refused=entry.CiRefused)
            except Refused as e:
                print(str(e), file=sys.stderr)
                return 1
            except (BoardGap, Reject) as e:
                print(f"盤面の誤り: {e}", file=sys.stderr)
                return 2
    except tree_run.Stopped as e:
        print(f"止められた（信号 {e.signum}）。テストのコマンドは木ごと止めた", file=sys.stderr)
        return 128 + e.signum
    script_io._emit(out)
    return 0


if __name__ == "__main__":
    for _s in (sys.stdout, sys.stderr):   # Windows の既定 cp1252 で日本語の出力が落ちないように
        if hasattr(_s, "reconfigure"):
            _s.reconfigure(encoding="utf-8")
    sys.exit(main())
