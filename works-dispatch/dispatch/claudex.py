"""Claude Code への口。dispatch で Claude Code を呼ぶ・その設定を触るのはこの 1 か所だけ。書くのは、フォルダの信頼の印と、
裏の会話（claude --bg）を消す rm の 2 つ。

開いている会話は `claude agents --json` で読む。Claude Code の文書は、これを外から会話の状態を読む公式の口としている。
返る 1 件の形は、2026-10-14 に 2.1.299 で見た `{"pid", "cwd", "kind", "startedAt", "sessionId", "name", "status"}`。
アカウントごとの一覧は、そのアカウントの設定のフォルダを CLAUDE_CONFIG_DIR に入れて呼ぶ。
起動するのはシェルの関数ではなく PATH の claude の実体（subprocess はシェルを通らない）。一覧を読むだけなので、認証のラッパは要らない。
"""

import json
import os
import re
import subprocess
import tempfile
import time


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


# Claude Code の Bash のツールが起動するシェルの印（コマンドの頭で、会話ごとのシェルの写しを読み込む。2026-10-17 に 2.1.301 で見た）
SNAPSHOT = "/shell-snapshots/snapshot-"


def _is_claude(command):
    head = (command.split() or [""])[0]
    return os.path.basename(head) == "claude" or "/claude/versions/" in head


def background_shells(me=None, runner=_default_runner):
    """このフックを起動した Claude Code の会話が、裏で走らせている Bash（run_in_background）の数。分からなければ None。
    Stop フックの入力に裏の処理の一覧（background_tasks）の無い版のための代わり（一覧が在れば orders.in_flight がそちらを使う）。
    ターンが終わった時に会話のプロセスの子に残っている Bash のツールのシェル（コマンドに SNAPSHOT を含む）を数える。ターンの終わりには前で走らせた Bash は
    終わっているので、残っているのは裏の物。プロセスの一覧は ps で読むので、ps の無い Windows では None。"""
    if os.name == "nt":
        return None
    p = runner(["ps", "-A", "-o", "pid=,ppid=,command="])
    if p.returncode != 0:
        return None
    procs = {}
    for line in p.stdout.splitlines():
        parts = line.split(None, 2)
        if len(parts) >= 2 and parts[0].isdigit() and parts[1].isdigit():
            procs[int(parts[0])] = (int(parts[1]), parts[2] if len(parts) > 2 else "")
    chain, pid = [], me or os.getpid()
    while pid in procs and pid not in chain and pid > 1:
        chain.append(pid)
        pid = procs[pid][0]
    host = next((x for x in chain if _is_claude(procs[x][1])), None)
    if host is None:
        return None
    return sum(1 for pid, (ppid, command) in procs.items() if ppid == host and SNAPSHOT in command and pid not in chain)


def trust_file(config_dir, env):
    """Claude Code がフォルダの信頼を記録するファイル（全体の設定のファイル .claude.json）。
    CLAUDE_CONFIG_DIR を入れて起動するなら <そのフォルダ>/.claude.json、入れなければ ~/.claude.json
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


def inherit_trust(path_of_file, source, clone, vouchers=()):
    """元の clone が信頼済みなら、そこから作った作業場（clone は、元の clone の worktree のパス）にも信頼の印を付ける。結末の語を返す:
    inherited（付けた）・already（もう付いている）・source_untrusted（元が信頼されていない。確認がふつうに出る）・no_file。

    元の clone の信頼は、このアカウントの物（path_of_file）か、vouchers（同じ持ち主のほかのアカウントの .claude.json のパス）の
    どれかの物を数える。ほかのアカウントでだけ信頼済みなら、このアカウントにも元の clone の印を写してから作業場に付ける（持ち主が
    どこかで一度信頼したリポジトリは、アカウントを替えても確認を出さない。2026-10-17 に p3 が元の clone の印を持たず、作業場ごとに
    確認が出た）。どのアカウントも信頼していない元には付けない（確認は、知らないリポジトリの設定やフックが動くのを止める安全の確認）。

    Claude Code の文書は、確認を出さずに信頼する手として、.claude.json の projects["<リポジトリのルート>"].hasTrustDialogAccepted を
    true にすることを書いている。信頼はリポジトリのルートごとで、親のフォルダの信頼は中の checkout に効かない。
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
    vouched = not (entry or {}).get("hasTrustDialogAccepted")
    if vouched:
        if not any(is_trusted(v, source) for v in vouchers if v != path_of_file):
            return "source_untrusted"
        found = found or _key_like(next(iter(projects), None), os.path.realpath(source))
        projects[found] = {**(entry or {}), "hasTrustDialogAccepted": True}
    mine, have = _project(projects, clone)
    if (have or {}).get("hasTrustDialogAccepted"):
        if not vouched:
            return "already"
    else:
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
    """そのアカウントで /catchup を受けるコマンドの名前（例 /attention:catchup）を、入っているプラグインから組み立てて返す。

    プラグインのコマンドは「/<plugin.json の名前>:<コマンドのファイル名>」で呼ぶ。人が画面で /catchup と打つと補完がプラグイン名を足すが、
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
    """そのアカウントがフォルダ（リポジトリのルート）を信頼済みか。ファイルが読めなければ偽。"""
    try:
        with open(path_of_file, encoding="utf-8") as f:
            projects = json.load(f).get("projects") or {}
    except (OSError, ValueError, AttributeError):
        return False
    return bool((_project(projects, folder)[1] or {}).get("hasTrustDialogAccepted"))


TASK_FLAGS = ("--name", "--bg", "--settings")


def missing_flags(runner=_default_runner, flags=TASK_FLAGS):
    """PATH の claude の `claude --help` に無い旗の並び。部署（--task）は、会話に名前を付け（--name。SendMessage の宛先になる）、
    裏の会話として起動し（--bg）、その会話にだけ効く設定を渡す（--settings）。起動できなければ全部。"""
    try:
        p = runner(["claude", "--help"])
    except OSError:
        return list(flags)
    text = p.stdout or "" if p.returncode == 0 else ""
    return [f for f in flags if f not in text]


def attach_id(entry, session_id=None):
    """`claude attach` に渡す会話の id。会話の一覧（claude agents --json）の短い `id`（8 字）を使う。Claude Code 2.1.301 の attach は
    長い id（sessionId。UUID）を「No job matching」と断る（まっさらな環境での 6 回目の試し）。一覧に無ければ、長い id の頭の 8 字
    （短い id は長い id の頭と同じ字だった）。"""
    if entry and entry.get("id"):
        return entry["id"]
    full = (entry or {}).get("sessionId") or session_id or ""
    return full.split("-")[0][:8] if full else None


def remove_session(config_dir, session_id, runner=_default_runner, base_env=None):
    """そのアカウントの裏の会話を消す（`claude rm <id>`）。書く口。(消えたか, claude の言葉)。
    rm は、どのリモートにも無い commit や確かめられないファイルのある worktree なら、消さずに断る（2026-10-16 に 2.1.301 で見た。
    会話が作った worktree でなければ、worktree は残して会話だけを消した）。鍵は要らず、設定のフォルダだけで通った。"""
    p = runner(["claude", "rm", session_id], env=_env(config_dir, base_env))
    return p.returncode == 0, ((p.stdout or "") + (p.stderr or "")).strip()[:500]


def stop_session(config_dir, job, runner=_default_runner, base_env=None):
    """そのアカウントの裏の会話を止める（`claude stop <id>`。会話の記録は残り、attach で戻せる）。書く口。(止まったか, claude の言葉)。
    窓に attach の画面が開いたままだと、attach が会話を再開させるので、先に窓をシェルに戻す（launch.to_shell）。"""
    p = runner(["claude", "stop", job], env=_env(config_dir, base_env))
    return p.returncode == 0, ((p.stdout or "") + (p.stderr or "")).strip()[:500]


def job_tmp(config_dir, session_id, env=None):
    """裏の会話の一時の置き場（<設定のフォルダ>/jobs/<短い id>/tmp）。会話が残すと書いた物もここに在り、claude rm は会話と一緒に
    ここも消す（2026-10-17 に 2.1.301 で、--clean が消した部署の測りのツールがここと一緒に消えた）。設定のフォルダの決め方は
    trust_file と同じ（config_dir、無ければ env の CLAUDE_CONFIG_DIR、無ければ ~/.claude）。"""
    env = os.environ if env is None else env
    folder = config_dir or env.get("CLAUDE_CONFIG_DIR") or os.path.join(env.get("HOME") or os.path.expanduser("~"), ".claude")
    return os.path.join(os.path.expanduser(folder), "jobs", attach_id({"sessionId": session_id}), "tmp")


def newest_talk(config_dir, cwd, env=None):
    """その作業フォルダの会話の記録（<設定のフォルダ>/projects/<フォルダの字の英数字でない字を - にした物>/<会話の id>.jsonl）のうち、
    いちばん新しく書かれた物の (名前, 書いた時刻)。無ければ None。裏の会話（claude --bg）は /clear で会話を空にしても、会話の一覧の
    sessionId が替わらないことがある（2026-10-17 の試し。一覧は 98d8f057 のまま、記録は f20ea13c から新しいファイルに移った）ので、
    空になったかを記録のファイルが替わったかで見る。設定のフォルダの決め方は job_tmp と同じ。"""
    env = os.environ if env is None else env
    folder = config_dir or env.get("CLAUDE_CONFIG_DIR") or os.path.join(env.get("HOME") or os.path.expanduser("~"), ".claude")
    d = os.path.join(os.path.expanduser(folder), "projects", re.sub(r"[^A-Za-z0-9]", "-", os.path.abspath(cwd)))
    try:
        found = [(e.stat().st_mtime, e.name) for e in os.scandir(d) if e.name.endswith(".jsonl") and e.is_file()]
    except OSError:
        return None
    return (max(found)[1], max(found)[0]) if found else None


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


def running_claude(pid, runner=_default_runner):
    """その番号の処理が今動いている Claude Code か（ps -p でコマンドを読む。番号が使い回されたほかの処理は数えない）。ps が通らない所
    （Windows）では分からないので False。"""
    if not str(pid or "").isdigit():
        return False
    try:
        p = runner(["ps", "-p", str(pid), "-o", "command="])
    except OSError:
        return False
    return p.returncode == 0 and _is_claude((p.stdout or "").strip())


def _elapsed(text):
    """ps の etime（[[日-]時:]分:秒）を秒に。読めなければ None。"""
    days, _, rest = text.strip().rpartition("-")
    try:
        nums = [int(x) for x in rest.split(":")]
        return (int(days) if days else 0) * 86400 + sum(n * 60 ** i for i, n in enumerate(reversed(nums)))
    except ValueError:
        return None


def host(runner=_default_runner, me=None, now=None):
    """このフックを起動した Claude Code の会話の (処理の番号, 起きた時刻〔秒〕)。分からなければ (None, None)。
    起きた時刻は ps の etime（起きてからの時間）から出す（ps の lstart は言語の設定で字が替わるので読まない）。ps の無い Windows では
    (None, None)。"""
    if os.name == "nt":
        return None, None
    try:
        p = runner(["ps", "-A", "-o", "pid=,ppid=,etime=,command="])
    except OSError:
        return None, None
    if p.returncode != 0:
        return None, None
    now = time.time() if now is None else now
    procs = {}
    for line in p.stdout.splitlines():
        parts = line.split(None, 3)
        if len(parts) >= 3 and parts[0].isdigit() and parts[1].isdigit():
            procs[int(parts[0])] = (int(parts[1]), parts[2], parts[3] if len(parts) > 3 else "")
    chain, pid = [], me or os.getpid()
    while pid in procs and pid not in chain and pid > 1:
        chain.append(pid)
        pid = procs[pid][0]
    found = next((x for x in chain if _is_claude(procs[x][2])), None)
    if found is None:
        return None, None
    elapsed = _elapsed(procs[found][1])
    return found, (None if elapsed is None else now - elapsed)


def in_process(pid, chain=ancestors, parent=os.getppid):
    """pid（字でもよい）が、この処理の親をたどった中に在るか。--desk が書いた会話の処理の番号を、フックが同じ会話の処理か見分けるのに
    使う（フックは会話の処理〔Claude Code〕の子で走る）。ps が通らない所（Windows）では親の 1 つだけを見る。"""
    return bool(pid) and str(pid) in {str(p) for p in [parent(), *chain()]}


def latest(items, session_id, ancestors=()):
    """一覧のうち、その識別子の 1 件か None。同じ会話を一時停止したまま --resume で開き直すと、同じ sessionId の項目が古い処理と
    今の処理の 2 つ並ぶ（2026-10-16 に 2.1.301 で見た。古い方は状態 T のまま古い名前を持つ）。そのときは ancestors（呼んだ
    処理の親の pid）に当たる方、当たらなければ startedAt の新しい方を取る。"""
    hits = [s for s in items if s.get("sessionId") == session_id]
    mine = [s for s in hits if s.get("pid") in ancestors]
    return max(mine or hits, key=lambda s: s.get("startedAt") or 0, default=None)


def caller_pid(listed, session_id, ancestors=()):
    """呼んだ会話の処理（Claude Code）の番号（一覧の 1 件の pid）。見つからなければ None。選び方は caller と同じ。"""
    for items in listed.values() if session_id else ():
        s = latest(items, session_id, ancestors)
        if s:
            return s.get("pid") if isinstance(s.get("pid"), int) else None
    return None


def caller(listed, session_id, ancestors=()):
    """呼んだ会話（このコマンドを走らせている Claude Code の会話）の (アカウントの名, 会話の名前)。見つからなければ (None, None)。

    listed は アカウントの名 → そのアカウントの `claude agents --json` の並び。session_id は Claude Code が Bash のツールの子に渡す
    CLAUDE_CODE_SESSION_ID（文書は、フックに渡す session_id と同じ値で、外のツールと会話を結ぶのに使うと書く）。一覧はアカウントの
    設定のフォルダごとなので、その識別子が載っている一覧のアカウントが、呼んだ会話のアカウントである。同じ識別子が複数並ぶときの
    選び方は latest。"""
    if not session_id:
        return None, None
    for account, items in listed.items():
        s = latest(items, session_id, ancestors)
        if s:
            return account, s.get("name") or None
    return None, None
