# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""テストのコマンドを 1 回走らせる節（blk-tests の run）。

INPUTS_CMD（節の with: の cmd）を対象リポジトリの根（cwd）で `bash -c` に渡し、標準出力と標準エラーを盤面の
tests.log に置き、標準入力は閉じる（入力待ちで止まらない）。コマンドは本文に差し込まず環境変数のまま渡すので、
値がシェルの記号を含んでもデータのまま届く。PYTHONDONTWRITEBYTECODE=1 を立て、テストが作業ツリーに __pycache__ を
作って修正の差分に紛れ込むのを止める。
走らせるのは tree_run（.shared/core）——コマンドを自分のプロセスグループで起こし、run が止められたら（SIGINT・SIGTERM・
SIGHUP、直下の親の uv が消えた）テストが背景に起こした孫まで木ごと止める。
テストのコマンドには uv run の外の環境を渡す（outside_env）。Archon は script の節を `uv run <このファイル>` で起こし、
uv は PATH の頭に自分の python の bin（PEP 723 の塊が作る ~/.cache/uv の下の環境。塊が外れて対象が pyproject.toml を
持てば対象の .venv/bin）を足し、VIRTUAL_ENV・UV_RUN_RECURSION_DEPTH を立てる。そのまま渡すと `python3 -m pytest` が uv の python を掴んで偽の赤になる
（bash の節だった頃は Archon の素の環境で走った）。

出口: {"ok": true, "green": <終了コードが 0 か>, "log": <tests.log のパス>} を 1 行。赤（信号で死んだ回も）でも ok: true
——赤を人の関所に見せるのがこの段の仕事で、赤で run を止めない。
コマンドが空・空白だけなら何も走らせずに 1（緑と言わない）。ARTIFACTS_DIR が欠け・空なら 2。
止められた回は木を止め終えてから、出口を出さずに 128+信号で終わる。
"""
import sys
from pathlib import Path

sys.dont_write_bytecode = True   # 下の import が pack の中に __pycache__ を作らないように。必ず import より前
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / ".shared" / "core"))   # 頭に入れる（Ruling R7）
import os  # noqa: E402
import subprocess  # noqa: E402

import script_io  # noqa: E402
import tree_run  # noqa: E402

CMD_ENV = "INPUTS_CMD"
LOG_NAME = "tests.log"


def outside_env(environ):
    """uv run が足した物を外した環境（PYTHONDONTWRITEBYTECODE=1 は立てる）。外すのは:
    - PATH の頭の、この python の bin（dirname(sys.executable) か sys.prefix/bin。実体のパスで比べる）。uv は頭に足すので
      頭だけを見て、同じフォルダは 1 度だけ外す（元の PATH に同じフォルダが在っても後ろの物は残る）
    - UV_RUN_RECURSION_DEPTH と、sys.prefix を指す VIRTUAL_ENV（uv が起こした環境。対象の .venv もここ）
    uv run の外で起こされた（UV_RUN_RECURSION_DEPTH が無い）ときは、下の UV_NO_CONFIG のほかは外さない。
    - UV_NO_CONFIG はいつも外す。利用者が Archon の環境に立てていても、テストのコマンド（`uv run pytest` など）には対象の
      [tool.uv]（私的な index など）を読ませる。渡すと公開の PyPI から解決して、偽の赤と依存の取り違えの口になる
    限界: 節に deps: を足すと uv は --with の層の bin も足し、それは外れない（今の節は deps を持たない）"""
    env = dict(environ)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env.pop("UV_NO_CONFIG", None)
    if env.pop("UV_RUN_RECURSION_DEPTH", None) is None:
        return env
    ours = {os.path.realpath(d) for d in (os.path.dirname(sys.executable), os.path.join(sys.prefix, "bin"))}
    parts = env.get("PATH", "").split(os.pathsep)
    while parts and parts[0] and os.path.realpath(parts[0]) in ours:
        ours.discard(os.path.realpath(parts.pop(0)))
    env["PATH"] = os.pathsep.join(parts)
    venv = env.get("VIRTUAL_ENV")
    if venv and os.path.realpath(venv) == os.path.realpath(sys.prefix):
        del env["VIRTUAL_ENV"]
    return env


def main() -> int:
    if not os.environ.get(script_io.ARTIFACTS_ENV):
        print(f"環境変数が無い: {script_io.ARTIFACTS_ENV}", file=sys.stderr)
        return 2
    cmd = os.environ.get(CMD_ENV, "")
    if not cmd.strip():
        print("テストのコマンドが空", file=sys.stderr)
        return 1
    board = Path(os.environ[script_io.ARTIFACTS_ENV]) / script_io.BOARD_DIR
    board.mkdir(parents=True, exist_ok=True)
    log = board / LOG_NAME
    env = outside_env(os.environ)
    try:
        with open(log, "wb") as f:
            code = tree_run.run(["bash", "-c", cmd], stdin=subprocess.DEVNULL, stdout=f, stderr=subprocess.STDOUT, env=env)
    except tree_run.Stopped as e:
        print(f"止められた（信号 {e.signum}）。テストのコマンドは木ごと止めた", file=sys.stderr)
        return 128 + e.signum
    script_io._emit({"ok": True, "green": code == 0, "log": str(log)})
    return 0


sys.exit(main())
