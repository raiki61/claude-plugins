"""VS Code への口。dispatch が送り終えた PR の /catchup のページを、生きている VS Code の窓にタブで開く。

dispatch は会話を何件も一度に起動するので、起動した会話には /catchup のページを開かせない（launch の
ATTENTION_CATCHUP_OPEN=0）。その代わり、全件を送り終えた後にここで 1 回だけ、送った件のページを開く。
ページの置き場は attention の /catchup の決まり（~/.cache/attention/catchup/<owner>-<name>/<番号>.html）で、
attention の中は読まない（vendor の決まり）。書かれていないページは開かない。

窓の探し方は attention の catchup_html と同じ考え方: PATH の code（無ければ Remote の server が置いた
remote-cli の code の新しいもの）を、窓が CLI に開く socket（vscode-ipc-*.sock）ごとに呼ぶ。herdr の中の
会話は古い VSCODE_IPC_HOOK_CLI を継いでいることがあるので、見つけた socket を全部試す。死んだ socket は
すぐ失敗で返る。開けなくても dispatch は失敗にしない（人に見せる 1 行を返すだけ）。
"""

import glob
import os
import pathlib
import shutil
import subprocess

OPEN_ENV = "ATTENTION_CATCHUP_OPEN"  # 0 なら開かない（attention の /catchup と同じ旗）


def page_path(repo, number, home=None):
    """/catchup が PR #number について書くページ。repo は OWNER/NAME。"""
    owner, name = repo.split("/", 1)
    return pathlib.Path(home or pathlib.Path.home()) / ".cache" / "attention" / "catchup" / f"{owner}-{name}" / f"{number}.html"


def _mtime(p):
    try:
        return os.path.getmtime(p)
    except OSError:
        return 0.0


def code_cli(home=None, which=shutil.which):
    exe = which("code")
    if exe:
        return exe
    home = pathlib.Path(home or pathlib.Path.home())
    found = glob.glob(str(home / ".vscode-server" / "cli" / "servers" / "*" / "server" / "bin" / "remote-cli" / "code"))
    found += glob.glob(str(home / ".vscode-server" / "bin" / "*" / "bin" / "remote-cli" / "code"))
    return max(found, key=_mtime) if found else None


def sockets(env):
    """窓の socket を新しい順に。TMPDIR（無ければ /tmp）と XDG_RUNTIME_DIR を探し、環境の VSCODE_IPC_HOOK_CLI も足す。"""
    found = set()
    for d in (env.get("TMPDIR") or "/tmp", env.get("XDG_RUNTIME_DIR") or ""):
        if d:
            found.update(glob.glob(os.path.join(d, "vscode-ipc-*.sock")))
    hook = env.get("VSCODE_IPC_HOOK_CLI")
    if hook and os.path.exists(hook):
        found.add(hook)
    return sorted(found, key=_mtime, reverse=True)


def _run(argv, env):
    """終了コード。起動できなければ None。"""
    try:
        return subprocess.run(argv, env=env, capture_output=True, encoding="utf-8", errors="replace",
                              stdin=subprocess.DEVNULL).returncode
    except OSError:
        return None


def open_pages(paths, env=None, home=None, run=_run, which=shutil.which):
    """paths（書かれているページ）を、見つけた窓すべてにタブで開く。戻り値は人に見せる 1 行。"""
    env = dict(os.environ if env is None else env)
    paths = [str(p) for p in paths]
    if not paths:
        return None
    where = "、".join(paths)
    if env.get(OPEN_ENV) == "0":
        return f"/catchup のページは開いていない（{OPEN_ENV}=0）: {where}"
    try:
        cli = code_cli(home, which)
        if not cli:
            return f"/catchup のページは開いていない（VS Code の CLI の code が見つからない）: {where}"
        ok = sum(1 for s in sockets(env) if run([cli, "--reuse-window", *paths], {**env, "VSCODE_IPC_HOOK_CLI": s}) == 0)
        if not ok:
            return f"/catchup のページは開いていない（VS Code が繋がっていない）: {where}"
        return f"/catchup のページ {len(paths)} 件を VS Code の窓 {ok} 個に開いた"
    except Exception as e:  # noqa: BLE001 — 開けないことで dispatch を落とさない
        return f"/catchup のページは開いていない（{type(e).__name__}: {e}）: {where}"
