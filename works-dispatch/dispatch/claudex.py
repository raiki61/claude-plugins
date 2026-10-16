"""Claude Code への口。dispatch で Claude Code を呼ぶ・その設定を触るのはこの 1 か所だけ。書くのは、フォルダの信頼の印と、
裏の会話（claude --bg）を消す rm の 2 つ。

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
    return subprocess.run(argv, capture_output=True, text=True, encoding="utf-8", errors="replace", env=env)


def _env(config_dir, base_env):
    env = dict(os.environ if base_env is None else base_env)
    # config_dir が無い（アカウントを切り替えない人）なら、その人の CLAUDE_CONFIG_DIR（有れば）をそのまま使う
    if config_dir:
        env["CLAUDE_CONFIG_DIR"] = os.path.expanduser(config_dir)
    return env


def sessions(config_dir, runner=_default_runner, base_env=None, include_done=False):
    """そのアカウントの会話の並び。include_done なら、終わった裏の会話（claude --bg）も入れる（--all）。
    裏の会話の 1 件は id（短い id）と state（working・blocked・done・failed・stopped）も持つ（2026-10-16 に 2.1.301 で見た）。"""
    env = _env(config_dir, base_env)
    argv = ["claude", "agents", "--json"] + (["--all"] if include_done else [])
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


def _same_folder(a, b):
    """2 つのパスが同じフォルダか。Claude Code が .claude.json の projects に書く字は、区切りや記号のリンクの解き方が dispatch の
    持つ字と違うことがある（Windows は区切りを / で書き、dispatch は逆スラッシュで書いた物を持つ。macOS の /tmp は
    /private/tmp の記号のリンク）。リンクを解き、OS の決まりで大文字小文字と区切りを揃えて比べる。"""
    def norm(p):
        return os.path.normcase(os.path.realpath(os.path.expanduser(p)))
    return norm(a) == norm(b)


def _project(projects, folder):
    """projects の中の、そのフォルダの (鍵, 項目)。字が同じ物を先に、無ければ同じフォルダを指す物（_same_folder）。無ければ (None, None)。"""
    if folder in projects:
        return folder, projects[folder]
    for key, entry in projects.items():
        if isinstance(key, str) and _same_folder(key, folder):
            return key, entry
    return None, None


def _key_like(found_key, path):
    """新しく書く鍵の字を、見つけた鍵（Claude Code が書いた物）の区切りに揃える（Windows で / の物なら / にする）。"""
    if found_key and "/" in found_key and "\\" not in found_key and "\\" in path:
        return path.replace("\\", "/")
    return path


def inherit_trust(path_of_file, source, clone):
    """元の clone が信頼済みなら、そこから作った作業場（clone は、元の clone の worktree のパス）にも信頼の印を付ける。結末の語を返す:
    inherited（付けた）・already（もう付いている）・source_untrusted（元が信頼されていない。確認がふつうに出る）・no_file。

    Claude Code の文書は、確認を出さずに信頼する手として、.claude.json の projects["<リポジトリの根>"].hasTrustDialogAccepted を
    true にすることを書いている。信頼はリポジトリの根ごとで、親のフォルダの信頼は中の checkout に効かない。
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
    found, entry = _project(projects, source)
    if not (entry or {}).get("hasTrustDialogAccepted"):
        return "source_untrusted"
    mine, have = _project(projects, clone)
    if (have or {}).get("hasTrustDialogAccepted"):
        return "already"
    # 新しく書く鍵は、記号のリンクを解いた形（Claude Code は解いた形で引く。macOS で /tmp/… の鍵は効かず、/private/tmp/… の
    # 鍵は効いた。2026-10-16 に 2.1.301 で確かめた）を、Claude Code が書いた区切りに揃えて書く
    key = mine or _key_like(found, os.path.realpath(clone))
    projects[key] = {**(have or {}), "hasTrustDialogAccepted": True}
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


def catchup_commands(config_dir):
    """そのアカウントで /catchup を受ける命令の名前（例 /attention:catchup）を、入っているプラグインから組み立てて返す。

    プラグインの命令は「/<plugin.json の名前>:<命令のファイル名>」で呼ぶ。人が画面で /catchup と打つと補完がプラグイン名を足すが、
    herdr は文字をそのまま送るので、名前を組み立てて送る。プラグイン名を固定の文字で持たず、commands/catchup.md を持つものを探す。
    数えるのはアカウント全体に入れたもの（scope が user）だけ。project の入れ方は、その projectPath の中の会話にしか効かない。
    """
    try:
        with open(os.path.join(os.path.expanduser(config_dir), "plugins", "installed_plugins.json"), encoding="utf-8") as f:
            record = json.load(f)
    except (OSError, ValueError, TypeError):
        return []
    found = set()
    for entries in (record.get("plugins") or {}).values() if isinstance(record, dict) else ():
        for e in entries if isinstance(entries, list) else [entries]:
            if not isinstance(e, dict) or e.get("scope") != "user":
                continue
            path = e.get("installPath") or ""
            if not os.path.isfile(os.path.join(path, "commands", "catchup.md")):
                continue
            try:
                with open(os.path.join(path, ".claude-plugin", "plugin.json"), encoding="utf-8") as f:
                    name = json.load(f).get("name")
            except (OSError, ValueError, AttributeError):
                continue
            if name:
                found.add(f"/{name}:catchup")
    return sorted(found)


def is_trusted(path_of_file, folder):
    """そのアカウントがフォルダ（リポジトリの根）を信頼済みか。ファイルが読めなければ偽。"""
    try:
        with open(path_of_file, encoding="utf-8") as f:
            projects = json.load(f).get("projects") or {}
    except (OSError, ValueError, AttributeError):
        return False
    return bool((_project(projects, folder)[1] or {}).get("hasTrustDialogAccepted"))


TASK_FLAGS = ("--name", "--bg", "--settings")


def missing_flags(runner=_default_runner, flags=TASK_FLAGS):
    """PATH の claude の `claude --help` に無い旗の並び。部署（--task）は、会話に名前を付け（--name。SendMessage の宛先になる）、
    裏の会話として起こし（--bg）、その会話にだけ効く設定を渡す（--settings）。起こせなければ全部。"""
    try:
        p = runner(["claude", "--help"])
    except OSError:
        return list(flags)
    text = p.stdout or "" if p.returncode == 0 else ""
    return [f for f in flags if f not in text]


def remove_session(config_dir, session_id, runner=_default_runner, base_env=None):
    """そのアカウントの裏の会話を消す（`claude rm <id>`）。書く口。(消えたか, claude の言葉)。
    rm は、どのリモートにも無い commit や確かめられないファイルのある worktree なら、消さずに断る（2026-10-16 に 2.1.301 で見た。
    会話が作った worktree でなければ、worktree は残して会話だけを消した）。鍵は要らず、設定のフォルダだけで通った。"""
    p = runner(["claude", "rm", session_id], env=_env(config_dir, base_env))
    return p.returncode == 0, ((p.stdout or "") + (p.stderr or "")).strip()[:500]


def ancestors(runner=_default_runner, pid=None):
    """この処理（pid を渡せばその処理）から親をたどった pid の並び（自分を含む）。ps が通らなければ空。"""
    try:
        p = runner(["ps", "-A", "-o", "pid=,ppid="])
    except OSError:
        return []
    parent = {}
    for line in (p.stdout or "").splitlines() if p.returncode == 0 else []:
        cols = line.split()
        if len(cols) == 2 and cols[0].isdigit() and cols[1].isdigit():
            parent[int(cols[0])] = int(cols[1])
    chain, cur = [], os.getpid() if pid is None else pid
    while cur and cur not in chain:
        chain.append(cur)
        cur = parent.get(cur)
    return chain


def latest(items, session_id, ancestors=()):
    """一覧のうち、その識別子の 1 件か None。同じ会話を一時停止したまま --resume で開き直すと、同じ sessionId の項目が古い処理と
    今の処理の 2 つ並ぶ（2026-10-16 に 2.1.301 で見た。古い方は状態 T のまま古い名前を持つ）。そのときは ancestors（呼んだ
    処理の親の pid）に当たる方、当たらなければ startedAt の新しい方を取る。"""
    hits = [s for s in items if s.get("sessionId") == session_id]
    mine = [s for s in hits if s.get("pid") in ancestors]
    return max(mine or hits, key=lambda s: s.get("startedAt") or 0, default=None)


def caller(listed, session_id, ancestors=()):
    """呼んだ会話（この命令を走らせている Claude Code の会話）の (アカウントの名, 会話の名前)。見つからなければ (None, None)。

    listed は アカウントの名 → そのアカウントの `claude agents --json` の並び。session_id は Claude Code が Bash の道具の子に渡す
    CLAUDE_CODE_SESSION_ID（文書は、フックに渡す session_id と同じ値で、外の道具と会話を結ぶのに使うと書く）。一覧はアカウントの
    設定のフォルダごとなので、その識別子が載っている一覧のアカウントが、呼んだ会話のアカウントである。同じ識別子が複数並ぶときの
    選び方は latest。"""
    if not session_id:
        return None, None
    for account, items in listed.items():
        s = latest(items, session_id, ancestors)
        if s:
            return account, s.get("name") or None
    return None, None
