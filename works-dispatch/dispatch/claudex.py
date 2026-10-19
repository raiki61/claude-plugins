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
import time

import filex


NAME = "Claude Code"   # 使う人に見せる文で、この口の向こうのツールを呼ぶ名前（口の外の文はこれを差し込み、ツールの名前を書かない）
COMMAND = "claude"     # アカウントに起動のコマンドを書かないときの、会話を起動するコマンド
AGENT = "claude"       # 端末の口（herdr）が、ペインの前のこのツールの会話に付ける名前（ペインの agent）
CLEAR = "/clear"       # 会話を空にする打ち込み
EXIT = "/exit"         # 前の会話を終えてシェルに戻す打ち込み
RELOAD = "/reload-plugins"   # 起きている会話にプラグインを読み直させる打ち込み
CONFIG_ENV = "CLAUDE_CONFIG_DIR"   # アカウントの設定のフォルダを渡す環境変数
SESSION_ENV = "CLAUDE_CODE_SESSION_ID"   # Bash のツールの子に渡る、打った会話の id
JOB_ENV = "CLAUDE_JOB_DIR"   # 裏の会話の処理に渡る、その処理の置き場（名前が短い id）
EFFORT_ENV = "CLAUDE_EFFORT"   # Bash のツールの子に渡る、打った会話の今の effort
ENV_FILE = "CLAUDE_ENV_FILE"   # SessionStart のフックに渡る、Bash のツールのコマンドごとに先に走らせるシェルのファイル
PLUGINS_FILE = "installed_plugins.json"   # 設定のフォルダの plugins/ の下の、入れたプラグインの控え
LIST_COMMAND = "claude agents --json"   # 開いている会話の一覧を読むコマンド（使う人に見せる文で名指す）
REMOVE_COMMAND = "claude rm"            # 裏の会話を消すコマンド（同じ）
# 部署の裏の会話の設定に必ず重ねる値（会話に worktree を作らせず、先に作った作業場で働かせる）
FIXED_SETTINGS = {"worktree": {"bgIsolation": "none"}}
LOCAL_SETTINGS = ".claude/settings.local.json"   # リポジトリの中の、会話が書く手元だけの設定（許可の記録など。commit しない）
# フックの入力の、会話の始まり・人の文・ツールの呼び出しの出来事の名前（hook_event_name）
START, PROMPT, TOOL = "SessionStart", "UserPromptSubmit", "PreToolUse"


class ClaudeError(Exception):
    pass


Error = ClaudeError   # 口の外が受ける名前（ports.chat.Error）


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


# 会話の一覧の 1 件の status（対話の会話のターン）と state（裏の会話）の、読み方を知っている値。None はフィールドの無い物（対話の会話に
# state は無く、終わった裏の会話に status は無い）。2026-10-19 に 2.1.303 で見た値（tests/samples/claude-agents.json）
KNOWN_STATUS = ("busy", "idle", None)
KNOWN_STATE = ("working", "blocked", "done", "failed", "stopped", None)


def unknown_values(listed):
    """会話の一覧（sessions の返り）の、読み方を知らない status と state の値の {"status=値": 件数}。コードは知っている値だけを
    名指しで比べるので、知らない値の会話は止まっても動いてもいないように見える（壊れの見つけ方の標準の決まり 3）。"""
    out = {}
    for item in listed:
        for key, known in (("status", KNOWN_STATUS), ("state", KNOWN_STATE)):
            v = item.get(key) if isinstance(item, dict) else None
            if v not in known:
                out[f"{key}={v}"] = out.get(f"{key}={v}", 0) + 1
    return out


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
    filex.replace(path_of_file, json.dumps(data, ensure_ascii=False, indent=2))   # 前のファイルの権限を引き継ぐ
    return "inherited"


# /catchup のコマンドのファイルの置き場。どちらでも呼び名は /<プラグイン名>:catchup で変わらない
CATCHUP_FILES = (("skills", "catchup", "SKILL.md"), ("commands", "catchup.md"))


def catchup_commands(config_dir):
    """そのアカウントで /catchup を受けるコマンドの名前（例 /attention:catchup）を、入っているプラグインから組み立てて返す。

    プラグインのコマンドは「/<plugin.json の名前>:<コマンドのファイル名>」で呼ぶ。人が画面で /catchup と打つと補完がプラグイン名を足すが、
    herdr は文字をそのまま送るので、名前を組み立てて送る。プラグイン名を固定の文字で持たず、/catchup のコマンドのファイル（スキルの skills/catchup/SKILL.md か、
    コマンドの commands/catchup.md。attention は 2026-10-18 に前者へ移した）を持つものを探す。
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
            if not any(os.path.isfile(os.path.join(path, *p)) for p in CATCHUP_FILES):
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


def running(pid, runner=_default_runner):
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


def start_times(runner=_default_runner, now=None):
    """動いている処理の {番号: 起きた時刻〔秒〕}（ps の etime から。host と同じ読み方）。ps の無い Windows や、ps が通らなければ空。"""
    if os.name == "nt":
        return {}
    try:
        p = runner(["ps", "-A", "-o", "pid=,etime="])
    except OSError:
        return {}
    if p.returncode != 0:
        return {}
    now = time.time() if now is None else now
    out = {}
    for line in p.stdout.splitlines():
        parts = line.split()
        if len(parts) == 2 and parts[0].isdigit():
            elapsed = _elapsed(parts[1])
            if elapsed is not None:
                out[int(parts[0])] = now - elapsed
    return out


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


def session_of(env):
    """打った会話の id（SESSION_ENV）。Claude Code の外から打てば None。"""
    return env.get(SESSION_ENV)


def effort_of(env):
    """打った会話の今の effort（EFFORT_ENV）。分からなければ None。"""
    return env.get(EFFORT_ENV) or None


def job_of(env=os.environ):
    """この会話の裏の処理の短い id（`claude attach` に渡す物）。Claude Code は裏の会話（claude --bg）の処理に、置き場
    <設定のフォルダ>/jobs/<短い id> を CLAUDE_JOB_DIR で渡し、フックはそれを継ぐ。短い id は会話の id の頭と同じとは限らない
    （2026-10-17 に割り振りで、会話 081f72dd を短い id 8c4a1102 の処理が続けていた）。裏の会話でなければ None。"""
    d = (env.get(JOB_ENV) or "").rstrip("/\\")
    return os.path.basename(d) or None


def attached(argv, jobs):
    """その処理（起動の argv）が、jobs のどれかの裏の会話を開いた `claude attach <短い id>` か。"""
    return any(a == "attach" and i + 1 < len(argv) and argv[i + 1] in jobs for i, a in enumerate(argv))


def attach_command(command, job):
    """そのアカウントの起動のコマンド（アカウントが無く None なら COMMAND）で、裏の会話 job を窓に開く 1 行。"""
    return f"{COMMAND if command is None else command} attach {job}"


def config_dirs(home):
    """home の下の、このツールの設定のフォルダ（入れたプラグインの控え PLUGINS_FILE を持つ ~/.claude*）を ~/ からの名前で並べる。"""
    return sorted("~/" + n for n in os.listdir(home)
                  if n.startswith(".claude") and os.path.isfile(os.path.join(home, n, "plugins", PLUGINS_FILE)))


def accounts_draft(found):
    """dispatch の設定の下書き（--init）の、アカウントの書き方の行。found は config_dirs の並び。"""
    return [
        "# アカウントを切り替えないなら accounts は書かない（claude を 1 つだけ使う）。",
        "# 切り替えるなら、名前・そのアカウントで Claude Code を起動するコマンド・そのコマンドが CLAUDE_CONFIG_DIR に入れるフォルダを並べる。",
        "# 鍵を自分で決めた名前の Keychain の項目に置いたなら keychain_service、使用率の枠の無いアカウント（Ollama など）は limits = false。",
        "# setup-token の鍵だけで動かすアカウントは、プランを plan に書く（例 plan = \"default_claude_max_20x\"。limits.py plan がログインの記録からプランを読めないため）。",
        "# CLAUDE_CONFIG_DIR をシェルの環境でだけ入れて claude を起動する人も、そのフォルダを config_dir に書く（書かないと ~/.claude を見る）:",
        "# accounts = [",
        '#   { name = "main", command = "claude" },',
        '#   { name = "sub",  command = "<別のアカウントで起動するコマンド>", config_dir = "~/.claude-sub" },',
        '#   { name = "mine", command = "<コマンド>", config_dir = "~/.claude-mine", keychain_service = "<Keychain の項目の名前>" },',
        '#   { name = "local", command = "<Ollama などで起動するコマンド>", limits = false },',
        "# ]",
        f"# この機械で見つかった Claude Code の設定のフォルダ: {', '.join(found) or '無し'}",
    ]


def account_env(env, found):
    """アカウントの設定のフォルダを決めるための環境。CONFIG_ENV だけを found（ペインの新しいログインのシェルの値。無ければ消す）に替える。"""
    out = {k: v for k, v in env.items() if k != CONFIG_ENV}
    if found:
        out[CONFIG_ENV] = os.path.expanduser(found)
    return out


# ---- 会話の画面（端末の口の read の字）の読み方。Claude Code の入力フィールドの描き方に縛られるので、ここに置く ----

def _rule(x):
    """会話の画面の横の罫線の行か（入力フィールドの上と下に引かれる「────」。上の罫線には部署の名前が入ることがある）。"""
    return x.count("─") >= 10


def input_box(screen):
    """会話の画面の入力フィールドの字（下から 2 本の罫線の間の行をつないだ物）。罫線が 2 本無ければ None（字を受けられる形でない）。"""
    lines = (screen or "").splitlines()
    rules = [i for i, x in enumerate(lines) if _rule(x)]
    if len(rules) < 2:
        return None
    return " ".join(" ".join(lines[rules[-2] + 1:rules[-1]]).split())


_ESC = re.compile(r"\x1b\[([0-9;:?<=>]*)[ -/]*([@-~])|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)|\x1b[()][0-9A-Za-z]|[\x0e\x0f]")


def _solid(screen):
    """ANSI の画面の字を、行ごとに (制御の字を除いた字, そのうち薄字〔SGR 2〕でない字) の組にする。薄字は Claude Code が入力フィールドに
    出す次の文の候補と、空の入力フィールドの例の字（打てば消える。https://code.claude.com/docs/en/interactive-mode#prompt-suggestions ）。
    人が打った字と貼った字（[Pasted text …]）は薄字でない（2026-10-18 に claude を端末で起動して見た）。"""
    out, faint = [], False
    for line in (screen or "").splitlines():
        plain, solid, at = [], [], 0
        for m in _ESC.finditer(line):
            piece = line[at:m.start()]
            plain.append(piece)
            if not faint:
                solid.append(piece)
            at = m.end()
            if m.group(2) == "m":
                codes = (m.group(1) or "0").split(";")
                while codes:
                    code = codes.pop(0)
                    if code in ("38", "48", "58"):   # 色の指定の続き（5;n か 2;r;g;b）は薄字の 2 と読まない
                        del codes[:2 if codes[:1] == ["5"] else 4]
                    elif code in ("", "0", "22"):
                        faint = False
                    elif code == "2":
                        faint = True
        plain.append(line[at:])
        if not faint:
            solid.append(line[at:])
        out.append(("".join(plain), "".join(solid)))
    return out


def typed(screen):
    """会話の画面（herdr.read の ansi の字）の入力フィールドに、人が打った字（薄字の候補と頭の ❯ を除く）。入力フィールドが空なら ""、
    罫線が 2 本無ければ None（字を受けられる形でない）。打ちかけの字を消さないための見分け（/clear・/exit・1 行を打つ前に見る）。
    2026-10-18 に my_notes の段取りで、入力フィールドの候補「消していいよ」を打ちかけと見て、区切りの /clear と起動し直しを 1 時間打たなかった。"""
    rows = _solid(screen)
    rules = [i for i, (x, _) in enumerate(rows) if _rule(x)]
    if len(rules) < 2:
        return None
    return " ".join(" ".join(x for _, x in rows[rules[-2] + 1:rules[-1]]).split()).lstrip("❯").strip()


def ready(screen):
    """会話の画面が字を受けられる形か（入力フィールドが出ている）。"""
    return input_box(screen) is not None


def above_box(screen):
    """入力フィールドより上の画面の字（会話に届いた字が載る所）。"""
    lines = (screen or "").splitlines()
    rules = [i for i, x in enumerate(lines) if _rule(x)]
    return " ".join(" ".join(lines[:rules[-2]] if len(rules) >= 2 else lines).split())



def left_in_field(lines, head):
    """画面の終わりの行（lines）の入力フィールド（行の頭が ❯ の行）に、送った文の頭（head）が残っているか。"""
    return any(x.startswith("❯") and head in " ".join(x.split()) for x in lines)


# ---- フックの入出力（Claude Code のフックが標準入力に渡す JSON と、会話に字を足す答えの形） ----

def event(payload):
    """フックの出来事の名前（START・PROMPT・TOOL・Stop など）。"""
    return payload.get("hook_event_name")


def transcript(payload):
    """会話の記録のファイルの場所（無ければ None）。"""
    return payload.get("transcript_path")


def added_context(event_name, text):
    """会話に text を足すフックの答え（標準出力に 1 行で出す JSON）。"""
    return json.dumps({"hookSpecificOutput": {"hookEventName": event_name, "additionalContext": text}}, ensure_ascii=False)
