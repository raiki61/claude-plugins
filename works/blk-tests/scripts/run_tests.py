# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""最後のテストの節（blk-tests の run。盤面の p4.ci。仕様 3.5・裁定 TA4・TA5）。

INPUTS_CMD（節の with: の cmd。空でよい）で entry.run_ci(b, "p4.ci", test_cmd=cmd)（engine が宣言 .review-checks.json を走らせ、
cmd が在れば宣言の段の後に cmd の段も足して両方が緑の時だけ clean。cmd が宣言の段と同じコマンドなら 1 度だけ走らせ、出口の
test_cmd_same_as にその段の名。任せ先に落ちたら cmd を走らせた素材を done）→ settle。cmd を宣言の段と別に走らせた回は、出口の
test_cmd_how に走った時の起こし方（run_ci の返り）。
green は p4.ci が置いた素材 materials.local_checks の status が clean か。ログは run_ci の返りの log（周の番号を組み立てない）。
任せ先に落ちて cmd も空（run_ci の role_needed）なら、素材を読まずに green: false・by: role_needed・log は空——p4.ci は
任せ先に落ちたまま待つ（任せ先の役を回すのはラインの仕事。裁定 R52）。run_ci が拒んだ（CiRefused）は終了コード 1 で理由を stderr。
出口: {ok, green, log, suites（段ごとの {name, exit, how}。起こせない（exit None）段には launch も）, by（engine・role・role_needed）}
と、在れば test_cmd_same_as・test_cmd_how。赤で止めない（ok: true・green: false）——赤を人の関所に見せるのがこの段の仕事。

走らせるのは engine の tree_runner と tree_run（.shared/core）——自分のプロセスグループで起こし、run が止められたら（SIGINT・
SIGTERM・SIGHUP、直下の親の uv が消えた）テストが背景に起こした孫まで木ごと止める。止められた回は木を止め終えてから、出口を
出さずに 128+信号で終わる。テストには uv run の外の環境を渡す（tree_run.outside_env。決まりの正本はそこ）。
ARTIFACTS_DIR が欠け・空、盤面の口が読めない・盤面の誤り（BoardGap・止めた run への書き込み）は 2（回す側の誤り）。

2026-10-09 の整理で、盤面を開かない形 plain（線 C の mutgate の約束。線 C は棚上げ）と中の関所の形 mid（中の関所は C18 で
やめた）を消し、入力 mode も消した。
"""
import sys
from pathlib import Path

sys.dont_write_bytecode = True   # 下の import が pack の中に __pycache__ を作らないように。必ず import より前
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / ".shared" / "core"))   # 頭に入れる（Ruling R7）
import os  # noqa: E402

import script_io  # noqa: E402
import tree_run  # noqa: E402

CMD_ENV = "INPUTS_CMD"
INPUTS = (CMD_ENV,)   # 裁定 TA16: 読む INPUTS_* の組（Task 17 の試験が YAML の with: の鍵と突き合わせる）
CI_NODE = "p4.ci"


class Refused(Exception):
    """final が走らせられない（終了コード 1。文は人に向けた 1 行）"""


def _suite(name, how, code) -> dict:
    kind = tree_run.launch_kind(code)
    return {"name": name, "exit": code, **({"how": how} if how else {}), **({"launch": kind} if kind == "broken" else {})}


def run_final(b, cmd: str, *, run_ci, refused=()) -> dict:
    """最後のテスト（盤面の p4.ci）→ settle。run_ci の拒否（refused）は Refused。
    run_ci が role_needed（任せ先に落ちて cmd も空。宣言が無い時も、宣言が在るのに engine が落ちた時も）なら、盤面の素材を
    読まずに green: false・by: role_needed を返す（p4.ci は任せ先に落ちたまま待つ。裁定 R52）——素材はまだ修正前の
    周の頭の物で、それを最後の結果にすると修正後のテストを走らせずに緑と言う（Task 7 の審査 I2）。
    最後のテストは同じ run の中の控え（tree_run.slotted_run の結果の使い回し）を引かない——同じ木と命令でも環境の不具合で
    結末が変わった前例が在り、省くとその赤を見逃すため。控えには書き続ける（旗 RERUN_ENV を run_ci の間だけ立てる）"""
    had = os.environ.get(tree_run.RERUN_ENV)
    os.environ[tree_run.RERUN_ENV] = "1"
    try:
        ci = run_ci(b, CI_NODE, test_cmd=cmd)
    except refused as e:
        raise Refused(f"最後のテスト（{CI_NODE}）を走らせられない: {e}") from None
    finally:
        if had is None:
            del os.environ[tree_run.RERUN_ENV]
        else:
            os.environ[tree_run.RERUN_ENV] = had
    if ci["by"] == "role_needed":
        return {"ok": True, "green": False, "log": "", "suites": [], "by": "role_needed"}
    material = b.record.get("materials", {}).get("local_checks") or {}
    from entry import TEST_CMD_STEP
    runs = (ci.get("runs") or []) if ci["by"] == "engine" else []
    suites = [_suite(r["name"], r.get("how"), r["exit"]) for r in runs]
    b.settle()
    same = {"test_cmd_same_as": ci["same_as"]} if ci.get("same_as") else {}
    cmd_how = next((r.get("how") for r in runs if r["name"] == TEST_CMD_STEP), None) if ci["by"] == "engine" else ci.get("how")
    how = {"test_cmd_how": cmd_how} if cmd_how and not same else {}
    return {"ok": True, "green": material.get("status") == "clean", "log": ci["log"], "suites": suites, "by": ci["by"],
            **same, **how}


def main() -> int:
    if not os.environ.get(script_io.ARTIFACTS_ENV):
        print(f"環境変数が無い: {script_io.ARTIFACTS_ENV}", file=sys.stderr)
        return 2
    artifacts = Path(os.environ[script_io.ARTIFACTS_ENV])
    cmd = os.environ.get(CMD_ENV, "")
    try:
        try:
            import entry
        except ImportError as e:
            print(f"盤面の口 entry が読めない: {e}", file=sys.stderr)
            return 2
        from board import BoardGap
        from engine.util import Reject
        try:
            b = entry.open_board(artifacts / script_io.BOARD_DIR)
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
