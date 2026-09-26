"""差分を切る節。修正が触った物を、審査役が読む形で盤面（$ARTIFACTS_DIR/board/）に置く。

- fix.diff: git diff <base_rev>（--binary）と、未追跡のファイル 1 本ずつの git diff --no-index /dev/null <名>
  （未追跡のフォルダ＝入れ子の git リポジトリは差分に載せず、files に `sub/` の 1 本で出す）
- delta-snapshot.json: 切った時の作業ツリーの写し（accept.snapshot_tree。受け付けが突き合わせる。Ruling R3）
出口: {"ok": true, "files": [触ったファイル], "diff_file": <fix.diff のパス>} を 1 行。
base_rev が空なら repo の HEAD（Ruling R2）。版が引けない・git が効かないときは標準エラーに理由を出して 1
（審査役を起こさずに run を止める）。環境変数が欠けたときは 2。
"""
import sys
from pathlib import Path

sys.dont_write_bytecode = True   # 下の import が pack の中に __pycache__ を作らないように。必ず import より前
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / ".shared" / "core"))   # 頭に入れる（Ruling R7）
import os  # noqa: E402
import subprocess  # noqa: E402

import accept  # noqa: E402
import script_io  # noqa: E402

DIFF_FILE = "fix.diff"


def cut(board: Path, base_rev: str, repo: Path) -> dict:
    rev = accept._rev(repo, base_rev)
    files = accept.touched_files(repo, rev)
    diff = accept._git(repo, "diff", "--binary", "--no-ext-diff", "--no-renames", rev, binary=True)
    untracked = accept._git(repo, "ls-files", "--others", "--exclude-standard", "--full-name", "-z", "--", ":/", binary=True)
    for name in sorted(os.fsdecode(n) for n in untracked.split(b"\0") if n):
        if name.endswith("/"):
            continue   # 入れ子の git リポジトリ。差分には載せない（files に 1 本で出る）
        # --no-index は差が在れば 1 で終わるので _git（0 以外は Reject）を通さない
        r = subprocess.run(["git", "diff", "--no-index", "--binary", "--no-ext-diff", "--", "/dev/null", name],
                           cwd=str(repo), capture_output=True, stdin=subprocess.DEVNULL, timeout=accept.GIT_TIMEOUT)
        if r.returncode not in (0, 1):
            raise accept.Reject(f"git diff --no-index {name} が失敗した（{r.stderr.decode('utf-8', 'replace').strip()[-300:]}）")
        diff += r.stdout
    board.mkdir(parents=True, exist_ok=True)
    path = board / DIFF_FILE
    path.write_bytes(diff)
    accept._write_board(board, accept.SNAPSHOT_FILE, accept.snapshot_tree(repo))
    return {"ok": True, "files": files, "diff_file": str(path)}


def main() -> int:
    missing = [n for n in (script_io.BASE_REV_ENV, script_io.ARTIFACTS_ENV) if n not in os.environ]
    if script_io.ARTIFACTS_ENV not in missing and not os.environ[script_io.ARTIFACTS_ENV]:
        missing.append(script_io.ARTIFACTS_ENV)   # 空だと盤面が対象リポジトリの board/ になる
    if missing:
        print(f"環境変数が無い: {', '.join(missing)}", file=sys.stderr)
        return 2
    board = Path(os.environ[script_io.ARTIFACTS_ENV]) / script_io.BOARD_DIR
    try:
        out = cut(board, os.environ[script_io.BASE_REV_ENV], Path.cwd())
    except accept.Reject as e:
        print(f"差分を切れない: {e}", file=sys.stderr)
        return 1
    script_io._emit(out)
    return 0


sys.exit(main())
