"""包みの切符: 包み（.shared/adapter/claude-adapter）が、盤面の場所と役に書かせない場所を知るための小さなファイル（標準ライブラリだけ）。

線の `start` が run ごとに 1 回だけ `write` で書き、包みが起動のたびに `read(cwd)` で引く。置き場は包みの家
`home()` の下の `tickets/<cwd の realpath の sha256 の先頭 16 桁>.json`。cwd は run ごとの worktree なので、run の間で混ざらない。
中身は `{run_id, board, cwd, protected, written_at}`。`protected` は `protected_paths` の値で、包みが
`sandbox.filesystem.denyWrite` と `permissions.deny` に写す。守る場所は git から引く:
- 共通の .git（`--git-common-dir`）と、この worktree の gitdir の実体（`--absolute-git-dir`）
- `git worktree list` のほかの worktree と元の作業ツリー。**役の cwd の worktree 自身は除く**（役はそこに書く）
- 盤面・包みの家・pack の置き場（works 自身）
- git とシェルの設定（`~/.gitconfig`・`~/.config/git`・`~/.bashrc`・`~/.zshrc`・`~/.profile`）と Claude の設定の置き場
  （`~/.claude`）。一覧は HOME_FILES（シェルの起動ファイル・`~/.claude.json`・`~/.config/gh` も入る）。環境変数で置き場を
  替えている時は、その先（`$XDG_CONFIG_HOME/{git,gh}`・`$CLAUDE_CONFIG_DIR`）も足す
- 役の worktree 自身の `.git`（linked worktree では gitdir を指す 1 行のファイル）
- Archon の家（`$ARCHON_HOME`、無ければ `~/.archon`）の設定・DB・env・家の workflows/commands/scripts（ARCHON_FILES。家
  そのものは run の worktree を中に持つので守らない）
どの場所も綴り（渡された・git が返した形）と realpath の両方、さらに macOS の /var・/tmp・/etc は /private の有る無しの
両方を入れ（git は realpath で返すので、/var の綴りは機械で足す）、重複を除いて並べる。git を呼ぶときは
`git rev-parse --local-env-vars` の環境変数を外す。git が引けなければ TicketError。役の worktree が守る場所の中に
入れ子（守る場所が worktree の祖先か同じ）なら、黙って塞がずに TicketError（理由 1 行）。
"""
import datetime
import hashlib
import json
import os
import pathlib
import subprocess
import tempfile

PACK = pathlib.Path(__file__).resolve().parents[2]   # works/（.shared/core/ticket.py の 2 つ上）
# HOME の下で守る物（データの一覧。試験が 1 つずつ在るかを見る）。Edit・Write の道具には OS の柵が掛からないので、
# ここが permissions.deny の唯一の守りになる。シェルの起動ファイルは、書き換えると持ち主の次のシェルで柵の外で走る
HOME_FILES = (
    ".gitconfig", ".config/git", ".config/gh",                                  # git と gh の設定（gh は別名と認証）
    ".bashrc", ".bash_profile", ".bash_login", ".zshrc", ".zshenv", ".zprofile", ".profile",   # シェルの起動ファイル
    ".claude", ".claude.json",                                                  # Claude の設定（.claude.json は MCP の登録）
)
XDG_FILES = ("git", "gh")   # $XDG_CONFIG_HOME が在る時、その下で守る物
# Archon の家（$ARCHON_HOME、無ければ ~/.archon。Archon の getArchonHome と同じ）の下で守る物。設定（claudeBinaryPath を
# 書き換えると次の run から包みが外れる）・DB・env・家の workflows/commands/scripts と archon plugin install で入れた pack の
# 置き場 plugins（どのリポジトリの run にも効く。同じ家のほかの pack・ほかの commit の works も入る）・鍵。
# 家そのものは守らない: run の worktree・盤面が家の workspaces・worktrees の下に在り、塞ぐと役が自分の worktree に書けない
ARCHON_FILES = ("config.yaml", "archon.db", "archon.db-wal", "archon.db-shm", "archon.db-journal", ".env",
                "workflows", "commands", "scripts", "plugins", "credential-key", "install.json", ".archon")
# git rev-parse --local-env-vars が引けない時に外す物。外から漏れると -C の先でなく別のリポジトリを見る
GIT_ENV_FALLBACK = ("GIT_DIR", "GIT_WORK_TREE", "GIT_COMMON_DIR", "GIT_INDEX_FILE")


class TicketError(Exception):
    """守る場所を git から引けない（git でない cwd・git が無い）、または役の worktree が守る場所の中にある。"""


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


def _local_env_vars() -> tuple:
    """git が「リポジトリに固有」とする環境変数の名前（git rev-parse --local-env-vars）。引けなければ GIT_ENV_FALLBACK。"""
    try:
        done = subprocess.run(["git", "rev-parse", "--local-env-vars"], check=True, capture_output=True, text=True)
    except (OSError, subprocess.CalledProcessError):
        return GIT_ENV_FALLBACK
    names = tuple(done.stdout.split())
    return names or GIT_ENV_FALLBACK


def _git(cwd, env, *args) -> str:
    try:
        done = subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True, text=True, env=env)
    except (OSError, subprocess.CalledProcessError) as e:
        detail = getattr(e, "stderr", None) or str(e)
        raise TicketError(f"git {' '.join(args)} が引けない（{cwd}）: {detail.strip()}") from e
    return done.stdout


def _spellings(path: str) -> set:
    """同じ場所を指す綴り: そのもの・realpath と、macOS の /var・/tmp・/etc（/private の下への symlink）の
    /private の有る無しの両方。/private を足す・落とすのは、足した・落とした綴りの realpath が同じ時だけ。"""
    out = {path, os.path.realpath(path)}
    for q in list(out):
        alt = q[len("/private"):] if q.startswith("/private/") else "/private" + q
        if os.path.realpath(alt) == os.path.realpath(q):
            out.add(alt)
    return out


def protected_paths(repo_cwd: pathlib.Path, board_dir: pathlib.Path) -> list[str]:
    cwd = os.path.abspath(repo_cwd)
    drop = set(_local_env_vars())
    env = {k: v for k, v in os.environ.items() if k not in drop}
    common = _git(cwd, env, "rev-parse", "--git-common-dir").strip()
    gitdir = _git(cwd, env, "rev-parse", "--absolute-git-dir").strip()
    top = _git(cwd, env, "rev-parse", "--show-toplevel").strip()
    own = os.path.realpath(top)
    trees = [line[len("worktree "):] for line in _git(cwd, env, "worktree", "list", "--porcelain").splitlines()
             if line.startswith("worktree ")]
    places = [os.path.join(cwd, common), gitdir, os.path.join(top, ".git")]   # 最後は役の worktree の .git（ファイル）
    places += [t for t in trees if os.path.realpath(t) != own]
    places += [os.path.abspath(board_dir), str(home()), str(PACK)]
    user = os.path.expanduser("~")
    places += [os.path.join(user, name) for name in HOME_FILES]
    if os.environ.get("XDG_CONFIG_HOME"):
        places += [os.path.join(os.environ["XDG_CONFIG_HOME"], name) for name in XDG_FILES]
    if os.environ.get("CLAUDE_CONFIG_DIR"):
        places.append(os.environ["CLAUDE_CONFIG_DIR"])
    archon = os.path.expanduser(os.environ.get("ARCHON_HOME") or os.path.join(user, ".archon"))
    places += [os.path.join(archon, name) for name in ARCHON_FILES]
    out = set()
    for p in places:
        out |= _spellings(os.path.normpath(os.path.abspath(p)))
    for p in sorted(out):
        real = os.path.realpath(p)
        if own == real or own.startswith(real.rstrip("/") + "/"):
            raise TicketError(f"役の worktree {own} が守る場所 {real} の中にある（塞ぐと役が自分の worktree に書けない）")
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
