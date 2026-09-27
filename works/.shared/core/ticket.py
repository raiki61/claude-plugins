"""包みの切符: 包み（.shared/adapter/claude-adapter）が、盤面の場所と役に書かせない場所を知るための小さなファイル（標準ライブラリだけ）。

線の `start` が run ごとに 1 回だけ `write` で書き、包みが起動のたびに `read(cwd)` で引く。置き場は包みの家
`home()` の下の `tickets/<cwd の realpath の sha256 の先頭 16 桁>.json`。cwd は run ごとの worktree なので、run の間で混ざらない。
中身は `{run_id, board, cwd, protected, written_at}`。`protected` は `protected_paths` の値で、包みが
`sandbox.filesystem.denyWrite` と `permissions.deny` に写す。守る場所は git から引く:
- 共通の .git（`--git-common-dir`）と、この worktree の gitdir の実体（`--absolute-git-dir`）
- `git worktree list` のほかの worktree と元の作業ツリー。**役の cwd の worktree 自身は除く**（役はそこに書く）
- 盤面・包みの家・pack の置き場（works 自身）
- git とシェルの設定（`~/.gitconfig`・`~/.config/git`・`~/.bashrc`・`~/.zshrc`・`~/.profile`）と Claude の設定の置き場
  （`~/.claude`）。環境変数で置き場を替えている時は、その先（`$XDG_CONFIG_HOME/git`・`$CLAUDE_CONFIG_DIR`）も足す
どの場所も綴り（渡された・git が返した形）と realpath の両方を入れ（macOS の /var と /private/var のように、
symlink を通した綴りで書かれても外さないため）、重複を除いて並べる。git が引けなければ TicketError。
"""
import datetime
import hashlib
import json
import os
import pathlib
import subprocess
import tempfile

PACK = pathlib.Path(__file__).resolve().parents[2]   # works/（.shared/core/ticket.py の 2 つ上）
HOME_FILES = (".gitconfig", ".config/git", ".bashrc", ".zshrc", ".profile", ".claude")
GIT_ENV_DROP = ("GIT_DIR", "GIT_WORK_TREE", "GIT_COMMON_DIR", "GIT_INDEX_FILE")   # 外から漏れると -C の先でなく別のリポジトリを見る


class TicketError(Exception):
    """守る場所を git から引けない（git でない cwd・git が無い）。"""


def home() -> pathlib.Path:
    """包みの家: ${WORKS_ADAPTER_HOME:-${XDG_STATE_HOME:-$HOME/.local/state}/works/adapter}（空は無いと同じ）。"""
    own = os.environ.get("WORKS_ADAPTER_HOME")
    if own:
        return pathlib.Path(own)
    state = os.environ.get("XDG_STATE_HOME") or os.path.join(os.path.expanduser("~"), ".local", "state")
    return pathlib.Path(state) / "works" / "adapter"


def _key(cwd) -> str:
    return hashlib.sha256(os.path.realpath(cwd).encode("utf-8")).hexdigest()[:16]


def ticket_path(cwd: pathlib.Path) -> pathlib.Path:
    return home() / "tickets" / f"{_key(cwd)}.json"


def _git(cwd, *args) -> str:
    env = {k: v for k, v in os.environ.items() if k not in GIT_ENV_DROP}
    try:
        done = subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True, text=True, env=env)
    except (OSError, subprocess.CalledProcessError) as e:
        detail = getattr(e, "stderr", None) or str(e)
        raise TicketError(f"git {' '.join(args)} が引けない（{cwd}）: {detail.strip()}") from e
    return done.stdout


def protected_paths(repo_cwd: pathlib.Path, board_dir: pathlib.Path) -> list[str]:
    cwd = os.path.abspath(repo_cwd)
    common = _git(cwd, "rev-parse", "--git-common-dir").strip()
    gitdir = _git(cwd, "rev-parse", "--absolute-git-dir").strip()
    own = os.path.realpath(_git(cwd, "rev-parse", "--show-toplevel").strip())
    trees = [line[len("worktree "):] for line in _git(cwd, "worktree", "list", "--porcelain").splitlines()
             if line.startswith("worktree ")]
    places = [os.path.join(cwd, common), gitdir]
    places += [t for t in trees if os.path.realpath(t) != own]
    places += [os.path.abspath(board_dir), str(home()), str(PACK)]
    user = os.path.expanduser("~")
    places += [os.path.join(user, name) for name in HOME_FILES]
    if os.environ.get("XDG_CONFIG_HOME"):
        places.append(os.path.join(os.environ["XDG_CONFIG_HOME"], "git"))
    if os.environ.get("CLAUDE_CONFIG_DIR"):
        places.append(os.environ["CLAUDE_CONFIG_DIR"])
    out = set()
    for p in places:
        spelled = os.path.normpath(os.path.abspath(p))
        out.add(spelled)
        out.add(os.path.realpath(spelled))
    return sorted(out)


def write(board_dir: pathlib.Path, repo_cwd: pathlib.Path, run_id: str) -> pathlib.Path:
    doc = {
        "run_id": run_id,
        "board": os.path.abspath(board_dir),
        "cwd": os.path.abspath(repo_cwd),
        "protected": protected_paths(repo_cwd, board_dir),
        "written_at": datetime.datetime.now().astimezone().isoformat(timespec="seconds"),
    }
    path = ticket_path(repo_cwd)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".ticket-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(doc, f, ensure_ascii=False, indent=2)
            f.write("\n")
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except FileNotFoundError:
            pass
        raise
    return path


def read(cwd: pathlib.Path) -> dict | None:
    """cwd の切符。無い・読めない・JSON のオブジェクトでなければ None。"""
    try:
        doc = json.loads(ticket_path(cwd).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return doc if isinstance(doc, dict) else None
