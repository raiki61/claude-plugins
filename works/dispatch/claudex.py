"""Claude Code への口。dispatch で Claude Code を呼ぶ・その設定を触るのはこの 1 か所だけ。書くのは、フォルダの信頼の印 1 つだけ。

開いている会話は `claude agents --json` で読む。Claude Code の文書は、これを外から会話の状態を読む公式の口としている。
返る 1 件の形は、2026-10-14 に 2.1.299 で見た `{"pid", "cwd", "kind", "startedAt", "sessionId", "name", "status"}`。
アカウントごとの一覧は、そのアカウントの設定のフォルダを CLAUDE_CONFIG_DIR に入れて呼ぶ。
起こすのはシェルの関数ではなく PATH の claude の実体（subprocess はシェルを通らない）。一覧を読むだけなので、認証のラッパは要らない。
"""

import json
import os
import subprocess
import tempfile


class ClaudeError(Exception):
    pass


def _default_runner(argv, env=None):
    return subprocess.run(argv, capture_output=True, text=True, env=env)


def sessions(config_dir, runner=_default_runner, base_env=None):
    env = dict(os.environ if base_env is None else base_env)
    # config_dir が無い（アカウントを切り替えない人）なら、その人の CLAUDE_CONFIG_DIR（有れば）をそのまま使う
    if config_dir:
        env["CLAUDE_CONFIG_DIR"] = os.path.expanduser(config_dir)
    argv = ["claude", "agents", "--json"]
    p = runner(argv, env=env)
    try:
        listed = json.loads(p.stdout)
    except ValueError:
        listed = None
    if p.returncode != 0 or not isinstance(listed, list):
        raise ClaudeError(f"claude agents --json（{config_dir or '既定のフォルダ'}）: "
                          f"{(p.stderr or p.stdout).strip()[:300]}")
    return listed


def trust_file(config_dir, env):
    """Claude Code がフォルダの信頼を記録するファイル（全体の設定のファイル .claude.json）。
    CLAUDE_CONFIG_DIR を入れて起こすなら <そのフォルダ>/.claude.json、入れなければ ~/.claude.json
    （2026-10-14 に手元の 4 アカウントで、信頼したフォルダの記録がこの形で分かれているのを見た）。"""
    folder = config_dir or env.get("CLAUDE_CONFIG_DIR")
    if folder:
        return os.path.join(os.path.expanduser(folder), ".claude.json")
    return os.path.join(env.get("HOME") or os.path.expanduser("~"), ".claude.json")


def inherit_trust(path_of_file, source, clone):
    """元の clone が信頼済みなら、そこから作った clone にも信頼の印を付ける。結末の語を返す:
    inherited（付けた）・already（もう付いている）・source_untrusted（元が信頼されていない。確認がふつうに出る）・no_file。

    Claude Code の文書は、確認を出さずに信頼する手として、.claude.json の projects["<リポジトリの根>"].hasTrustDialogAccepted を
    true にすることを書いている。信頼はリポジトリの根ごとで、親のフォルダの信頼は中の clone に効かない。
    同じアカウントのほかの会話もこのファイルを書くので、一時ファイルに書いてから差し替える（壊さない）。
    ほかの会話が古い中身で上書きして印が消えても、確認がふつうに出るだけで済む。"""
    try:
        with open(path_of_file, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return "no_file"
    projects = data.get("projects") if isinstance(data, dict) else None
    if not isinstance(projects, dict):
        return "no_file"
    if not (projects.get(source) or {}).get("hasTrustDialogAccepted"):
        return "source_untrusted"
    if (projects.get(clone) or {}).get("hasTrustDialogAccepted"):
        return "already"
    projects[clone] = {**(projects.get(clone) or {}), "hasTrustDialogAccepted": True}
    mode = os.stat(path_of_file).st_mode & 0o777
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path_of_file), prefix=".claude.json.")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.chmod(tmp, mode)
        os.replace(tmp, path_of_file)
    except OSError:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise
    return "inherited"
