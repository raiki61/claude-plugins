"""herdr への口。dispatch で herdr を呼ぶのはこの 1 か所だけ（設計書のセクション 4）。

herdr は版が 0.x で互換を約束していない。herdr の文書は、手元の版の API を `herdr api schema` で確かめるよう求めている。
出力の形が変わって壊れたら、直すのはこのファイルだけになる。出力の形は 2026-10-14 と 2026-10-15 に herdr 0.9.3 の実物で読んだ。

作業場の場所（元の clone の git worktree）も、作る・並べる・開く・消すをここに寄せる（worktrees・create_worktree・open_worktree・
remove_worktree）。ノードは「ブランチの場所」の言葉だけで書き、herdr の worktree の口の形を知らない。

書く関数は run・prompt・send_keys・rename_pane・rename_workspace・report_pane_metadata・report_workspace_metadata・move_workspace・create_worktree・open_worktree・remove_worktree・close_workspace・
report_activity で、
呼んでよいノードはチェック（tests/fences.py の D4 の表 WRITES）が構文木で見る。

読む口が返す値は、herdr の JSON をそのまま渡さず、ここで works-dispatch の形に組み直す（口の外は herdr の JSON の形を知らない）。
herdr がフィールドの名前や入れ子を変えても、直すのはこのファイルの中だけ（組み直す _pane・agent・front_processes・workspaces・
_place・_opened と、herdr の答えのフィールドを中で読む wait_ready・prompt・shell_in_front・foreground・workspace_labels・remove_worktree）。
形（鍵の名前は、--tree --json が部署のペインを出す名前〔nodes/tree.py の build が組む pane_id・label・agent・agent_status・
agent_session〕にそろえた。herdr の名前と同じ字の鍵も、herdr から読んだ値をここで 1 つずつ入れた物で、herdr の JSON の素通しではない）:
- ペイン（panes）: pane_id・workspace_id・cwd・label・agent（ペインで動く会話のツールの名前。会話の口の AGENT と比べる。無ければ
  None）・agent_status（会話の状態。idle・working・blocked・done・unknown）・agent_session（ペインに居る会話の id の字。無ければ None）
- 会話の情報（agent）: agent・agent_status（ペインと同じ意味）
- 前のプロセス（front_processes）: pid・argv
- 作業場（workspaces）・ブランチの場所（worktrees）・開いた場所（create_worktree・open_worktree）・消した場所（remove_worktree）は、各関数の説明
"""

import json
import os
import socket
import subprocess
import time

STALLED = "agent_prompt_stalled"


NAME = "herdr"   # 使う人に見せる文で、この口の向こうのツールを呼ぶ名前（口の外の文はこれを差し込み、ツールの名前を書かない）
PANE_ENV = "HERDR_PANE_ID"   # ペインの中の処理に渡る、そのペインの id（裏の会話では別のペインを指すことがある）


class HerdrError(Exception):
    def __init__(self, argv, detail):
        super().__init__(f"{' '.join(argv[:3])}: {detail}")
        self.argv = argv
        self.detail = detail


Error = HerdrError   # 口の外が受ける名前（ports.term.Error）


def _default_runner(argv, env=None):
    return subprocess.run(argv, capture_output=True, text=True, encoding="utf-8", errors="replace", env=env)


def _error_code(text):
    try:
        obj = json.loads(text)
    except (TypeError, ValueError):
        return None
    err = obj.get("error") if isinstance(obj, dict) else None
    return err.get("code") if isinstance(err, dict) else None


def _call(argv, runner, quiet_ok=False):
    """herdr を呼び、成功なら result を返す。失敗は (code, 文) を持つ HerdrError。
    quiet_ok は、成功しても何も出さない書く口（pane run・workspace close）のためのもの。"""
    p = runner(argv)
    if p.returncode != 0:
        code = _error_code(p.stdout) or _error_code(p.stderr)
        raise HerdrError(argv, code or (p.stderr or p.stdout).strip()[:300])
    if quiet_ok and not p.stdout.strip():
        return {}
    try:
        return json.loads(p.stdout).get("result", {})
    except (ValueError, AttributeError):
        raise HerdrError(argv, f"JSON でない出力: {p.stdout[:200]!r}")


def _pane(p):
    """herdr のペインの 1 件を、口の形のペイン（冒頭の「形」）にする。herdr は会話の id を {value: …} の入れ子で持つので、
    字だけを取り出す。"""
    session = p.get("agent_session")
    return {"pane_id": p.get("pane_id"), "workspace_id": p.get("workspace_id"), "cwd": p.get("cwd"), "label": p.get("label"),
            "agent": p.get("agent"), "agent_status": p.get("agent_status"),
            "agent_session": session.get("value") if isinstance(session, dict) else None}


def panes(runner=_default_runner):
    """ペインの並び（口の形のペイン）。読む口。"""
    return [_pane(p) for p in _call(["herdr", "pane", "list"], runner).get("panes", [])]


def workspace_labels(runner=_default_runner):
    ws = _call(["herdr", "workspace", "list"], runner).get("workspaces", [])
    return {w["workspace_id"]: w.get("label") for w in ws}


def workspaces(runner=_default_runner):
    """作業場の並び（herdr の並びの順）。1 件は {workspace_id, label, repo_root, path, linked, tokens}。repo_root は herdr がその作業場に
    持つリポジトリの元の clone のルート（linked worktree の作業場でも元の clone）で、herdr が git の印を持たない作業場（git worktree から
    でなく開いたもの）は None。path はその作業場の worktree の場所、linked は元の clone でない worktree（部署の作業場）か。
    tokens は作業場の印（workspace report-metadata で付けた物。出どころを混ぜた 名前 → 値）。
    形は 2026-10-16 に herdr 0.9.3 で読んだ（workspace list の worktree フィールドの repo_root。tokens は 2026-10-17 に同じ版で見た）。"""
    out = []
    for w in _call(["herdr", "workspace", "list"], runner).get("workspaces", []):
        wt = w.get("worktree") if isinstance(w.get("worktree"), dict) else {}
        out.append({"workspace_id": w["workspace_id"], "label": w.get("label"), "repo_root": _norm(wt.get("repo_root")),
                    "path": _norm(wt.get("checkout_path")), "linked": bool(wt.get("is_linked_worktree")),
                    "tokens": w.get("tokens") if isinstance(w.get("tokens"), dict) else {}})
    return out


def agent(target, runner=_default_runner):
    """1 つのペインの会話の情報（口の形の {agent, agent_status}）。読む口。"""
    got = _call(["herdr", "agent", "get", target], runner).get("agent") or {}
    return {"agent": got.get("agent"), "agent_status": got.get("agent_status")}


def methods(runner=_default_runner):
    """手元の herdr の API のメソッドの名の集合（始める前の確かめに使う）。"""
    p = runner(["herdr", "api", "schema", "--json"])
    if p.returncode != 0:
        raise HerdrError(["herdr", "api", "schema"], (p.stderr or p.stdout).strip()[:300])
    found = set()

    def walk(x):
        if isinstance(x, dict):
            m = x.get("method")
            if isinstance(m, dict) and isinstance(m.get("const"), str):
                found.add(m["const"])
            for v in x.values():
                walk(v)
        elif isinstance(x, list):
            for v in x:
                walk(v)

    walk(json.loads(p.stdout))
    return found


def claude_integration(config_dir, env, runner=_default_runner):
    """その設定のフォルダの Claude Code に、herdr の連携のフックが入っているか（`herdr integration status` の claude の行の状態）。

    herdr は CLAUDE_CONFIG_DIR に従って <フォルダ>/hooks/herdr-agent-state.sh を見る。返すのは "current (v10)" や "not installed" の字。
    """
    argv = ["herdr", "integration", "status"]
    p = runner(argv, env={**env, "CLAUDE_CONFIG_DIR": config_dir})
    if p.returncode != 0:
        raise HerdrError(argv, (p.stderr or p.stdout).strip()[:300])
    for line in p.stdout.splitlines():
        if line.startswith("claude:"):
            return line[len("claude:"):].split(" (/")[0].strip()
    raise HerdrError(argv, f"claude の行が無い: {p.stdout[:200]!r}")


def _spawn(argv):
    subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     start_new_session=True)


def report_activity(pane, text, ttl_ms, spawn=_spawn):
    """ペインのサイドバーの印 $act に text を送る。終わりを待たずに手放す（フックから呼ぶので、ツールの呼び出しを待たせない）。"""
    spawn(["herdr", "pane", "report-metadata", pane, "--source", "claude-activity",
           "--ttl-ms", str(ttl_ms), "--token", f"act={text}"])


def run(pane, command, runner=_default_runner):
    """ペインのシェルにコマンドを打ち込み、Enter まで送る。書く口その 1。"""
    _call(["herdr", "pane", "run", pane, command], runner, quiet_ok=True)


def rename_pane(pane, label, runner=_default_runner):
    """ペインに名前（label）を付ける。書く口。名前は 1 つの argv で渡す（herdr は残りの引数を空白でつなぐが、1 つなら字のまま）。"""
    _call(["herdr", "pane", "rename", pane, label], runner)


def rename_workspace(workspace, label, runner=_default_runner):
    """作業場に名前（label）を付ける。書く口。herdr のサイドバーの 1 行目は、ペインの名前でなくこの名前（2026-10-16 に 0.9.3 で見た）。"""
    _call(["herdr", "workspace", "rename", workspace, label], runner)


def report_pane_metadata(pane, source, display_agent, title, tokens, clear_tokens=(), runner=_default_runner):
    """ペインの表示名（--display-agent）・題名（--title）・札（--token 名=値）を、出どころ source の分として付ける。書く口。
    herdr は出どころごとに値を持ち、同じ出どころで打ち直すと置き換わる。値が None の表示名・題名と、clear_tokens の札は消す
    （正本から消えた物を表示に残さない。何度打っても同じ結果）。成功しても何も出さない（2026-10-16 に herdr 0.9.3 で見た。
    --token と --clear-token、--clear-display-agent・--clear-title は 1 回の呼び出しに混ぜられた）。"""
    argv = ["herdr", "pane", "report-metadata", pane, "--source", source]
    argv += ["--display-agent", display_agent] if display_agent else ["--clear-display-agent"]
    argv += ["--title", title] if title else ["--clear-title"]
    for name, value in sorted(tokens.items()):
        argv += ["--token", f"{name}={value}"]
    for name in clear_tokens:
        argv += ["--clear-token", name]
    _call(argv, runner, quiet_ok=True)


def report_workspace_metadata(workspace, source, tokens, clear_tokens=(), runner=_default_runner):
    """作業場の印（--token 名=値。サイドバーの作業場の行に $名前 で出す）を、出どころ source の分として付ける。書く口。
    同じ出どころで打ち直すと置き換わり、clear_tokens の印は消す（2026-10-17 に herdr 0.9.3 で、--clear-token が同じ出どころの
    印を消すのを見た）。"""
    argv = ["herdr", "workspace", "report-metadata", workspace, "--source", source]
    for name, value in sorted(tokens.items()):
        argv += ["--token", f"{name}={value}"]
    for name in clear_tokens:
        argv += ["--clear-token", name]
    _call(argv, runner, quiet_ok=True)


def read(pane, lines, runner=_default_runner, ansi=False):
    """ペインの画面の終わりの lines 行（読むだけ。起動できなかった訳を報告に添えるのに使う）。JSON でなく画面の字のまま返る
    （2026-10-16 に herdr 0.9.3 で見た）。ansi なら色と薄字の制御の字（SGR）を付けたまま返す（claudex.typed が薄字を見分ける）。"""
    argv = ["herdr", "pane", "read", pane, "--lines", str(lines)] + (["--ansi"] if ansi else [])
    p = runner(argv)
    if p.returncode != 0:
        raise HerdrError(argv, _error_code(p.stdout) or (p.stderr or p.stdout).strip()[:300])
    return p.stdout


PROC_READ_TRIES = 20   # 前の処理のコマンド行を読む処理（cat）が終わったかを見に行く回数（_proc_argv。間は PROC_READ_PAUSE 秒）
PROC_READ_PAUSE = 0.1
_STUCK_STATES = (b"D", b"Z", b"X", b"x")   # コマンド行を読まない処理の状態（herdr の process_state_allows_remote_memory_read と同じ）


def _proc_argv(pid, tries=PROC_READ_TRIES, pause=lambda: time.sleep(PROC_READ_PAUSE)):
    """前の処理の起動の argv を、手元の /proc/<pid>/cmdline から読む（Linux だけ。/proc の無い所と、読めない・読み終わらないときは []）。

    herdr 0.9.5 は WSL の上で、会話のツールと名前で分かる処理（name が claude など）の argv も cmdline も返さない（読むと、終わりかけの
    処理で止まったままになることがあるため。herdr の src/platform/linux.rs の foreground_job_from_members と、変更履歴の 0.9.5 の
    「Linux process discovery stays responsive around stuck WSL agents」）。それでは窓の前の `claude attach` を見分けられず、
    --retire・待ち受け・--take が窓をシェルに戻せなかった（受付 36ea2a）。
    ここは herdr と同じく、状態（/proc/<pid>/stat。読んでも止まらない）が止まりかけ（D・Z・X）なら読まない。それでも読むと止まる
    隙は残るので、読むのは別の処理（cat）にさせ、終わったかを pause の間を置いて tries 回まで見に行き、終わっていなければ止めて
    諦める（待たずに離れる。この処理は止まらない）。回数と間で決まる上限（2 秒）は実質の期限で、D5 の狭い例外として設計書に書いた
    （docs/specs/2026-10-14-catchup-dispatch-design.md の 4 の D5。打ち切るのは自分で起動した読み手の cat だけで、部署の会話の仕事は
    打ち切らない。上限が無いと、読みが止まったとき dispatch の処理ごと止まる）。
    macOS と Windows の herdr は argv を返すので、ここへは来ない（src/platform/macos.rs・windows.rs）。"""
    if not str(pid or "").isdigit():
        return []
    try:
        with open(f"/proc/{pid}/stat", "rb") as f:
            state = f.read().rpartition(b")")[2].split()[:1]   # 2 番目のフィールド（処理の名前）は括弧の中に空白を含みうる
    except OSError:
        return []
    if not state or state[0] in _STUCK_STATES:
        return []
    try:
        p = subprocess.Popen(["cat", f"/proc/{pid}/cmdline"], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    except OSError:
        return []
    for _ in range(tries):
        if p.poll() is not None:
            break
        pause()
    else:
        p.kill()   # 止まった読み手は待たない（待つとこちらも止まる）。口だけ閉じる
        p.stdout.close()
        return []
    out = p.stdout.read()   # 終わった後に読む（コマンド行が管の大きさ〔Linux は 64KiB〕を超えると cat が終われず、上で諦めて [] になる）
    p.stdout.close()
    return [part.decode("utf-8", "replace") for part in out.split(b"\0") if part] if p.returncode == 0 else []


def _argv(proc, read_argv):
    """herdr の foreground_processes の 1 件の argv。argv も cmdline も無ければ（herdr 0.9.5 の WSL）、pid から read_argv で読む。"""
    if proc.get("argv"):
        return list(proc["argv"])
    if proc.get("cmdline"):
        return proc["cmdline"].split()
    return read_argv(proc.get("pid"))


def foreground(pane, runner=_default_runner, read_argv=None):
    """ペインの前で動いているプロセスの起動したコマンドの並び（herdr pane process-info の foreground_processes の cmdline。herdr が
    返さなければ _proc_argv で読む）。読む口。"""
    info = _call(["herdr", "pane", "process-info", "--pane", pane], runner).get("process_info", {})
    return [p.get("cmdline") or " ".join(_argv(p, read_argv or _proc_argv)) for p in info.get("foreground_processes") or []]


def front_processes(pane, runner=_default_runner, read_argv=None):
    """ペインの前で動いているプロセスの並び（herdr pane process-info の foreground_processes を、口の形の {pid, argv} に。argv を
    herdr が返さなければ _proc_argv で読む）。読む口。"""
    info = _call(["herdr", "pane", "process-info", "--pane", pane], runner).get("process_info", {})
    return [{"pid": p.get("pid"), "argv": _argv(p, read_argv or _proc_argv)} for p in info.get("foreground_processes") or []]


def send_keys(pane, *keys, runner=_default_runner):
    """ペインにキーを送る（herdr pane send-keys。例 ctrl+c・enter）。書く口。"""
    _call(["herdr", "pane", "send-keys", pane, *keys], runner, quiet_ok=True)


def shell_in_front(pane, runner=_default_runner):
    """ペインの前にシェルだけが居るか（起動したコマンドがまだ始まっていない・もう終わった）。"""
    info = _call(["herdr", "pane", "process-info", "--pane", pane], runner).get("process_info", {})
    return info.get("foreground_process_group_id") == info.get("shell_pid")


def wait_ready(pane, runner=_default_runner, pause=lambda: time.sleep(0.5)):
    """起動した直後に、会話が見つかって入力を待つか、確認の画面（フォルダの信頼・ログインなど）で止まるまで待ち、状態を返す。

    agent wait に --until を付けないと、idle・done・blocked のどれでも返る（herdr agent wait --help）。idle だけを待つと、
    確認の画面で止まった会話を永久に待ち、後ろの PR の起動まで止まる。

    herdr の agent wait は、まだ会話を見つけていないペインでは待たずに agent_not_found を返す（2026-10-14 に herdr 0.9.3 で見た）。
    そのときはペインの前のプロセスを見て、起動するコマンドが動いている間か、まだ始まっていない間は待ち直す。
    一度動いた後にシェルだけに戻ったら、会話が始まらなかったとして止める。期限は足さない。
    """
    started = False
    while True:
        try:
            got = _call(["herdr", "agent", "wait", pane], runner)
            return got.get("agent", {}).get("agent_status", "idle")
        except HerdrError as e:
            if e.detail != "agent_not_found":
                raise
        if shell_in_front(pane, runner):
            if started:
                raise HerdrError(["herdr", "agent", "wait", pane], "起動するコマンドが終わり、会話が始まらなかった")
        else:
            started = True
        pause()


def prompt(target, text, wait, runner=_default_runner, until=()):
    """会話にプロンプトを送る。書く口その 2。文は argv の 1 つでそのまま渡し、シェルを通さない。

    wait が真なら、送った後に動き出したのを見てから止まるまで待ち、その状態（idle・done・blocked）を返す。
    until を渡すと、止まるまでではなく、その状態のどれかを見た所で返す（herdr agent prompt --until。例: 動き出したのだけを待つ
    ("working", "blocked")）。herdr の組み込みの見張りが返す agent_prompt_stalled は、誤りではなく "stalled" の状態として返す。
    wait が偽なら "sent"。
    """
    argv = ["herdr", "agent", "prompt", target, text] + (["--wait"] if wait else []) + \
        [x for s in (until if wait else ()) for x in ("--until", s)]
    try:
        result = _call(argv, runner)
    except HerdrError as e:
        if e.detail == STALLED:
            return "stalled"
        raise
    if not wait:
        return "sent"
    return result.get("agent", {}).get("agent_status", "idle")


def _norm(path):
    """herdr から受け取ったパスを、ここで 1 回だけ os.path.normpath にそろえる。中ではそろえた形だけを使う。
    herdr が返すのは git の worktree list と同じ `/` 区切りで、Windows では os.path.join で作るパス（`\\` 区切り）と字が
    食い違い、同じ場所を別物とみなしていた（2026-10-15 の CI の windows の組）。比べる所は realpath を使うので、それとも矛盾しない。"""
    return os.path.normpath(path) if path else path


def _place(worktree):
    """herdr の worktree の 1 件を、場所の言葉（path・branch・linked・workspace・prunable）にする。"""
    return {"path": _norm(worktree.get("path")), "branch": None if worktree.get("is_detached") else worktree.get("branch"),
            "linked": bool(worktree.get("is_linked_worktree")), "workspace": worktree.get("open_workspace_id"),
            "prunable": bool(worktree.get("is_prunable"))}


def worktrees(source, runner=_default_runner):
    """元の clone（source）の worktree を全部（元の clone 自身も linked=False で入る）。読むだけで、作業場は開かない
    （2026-10-15 に herdr 0.9.3 で、herdr で開いていないリポジトリに打っても作業場が増えないことを見た）。"""
    got = _call(["herdr", "worktree", "list", "--cwd", source], runner)
    return [_place(w) for w in got.get("worktrees", [])]


def _opened(result):
    """worktree create・open の結果から {path, branch, workspace_id, pane_id}。"""
    wt = result.get("worktree", {})
    return {"path": _norm(wt.get("path")), "branch": wt.get("branch"),
            "workspace_id": (result.get("workspace") or {}).get("workspace_id") or wt.get("open_workspace_id"),
            "pane_id": (result.get("root_pane") or {}).get("pane_id")}


def create_worktree(source, branch, base, label, runner=_default_runner):
    """元の clone からブランチの worktree を作り、herdr の作業場を開く（前に出さない）。書く口。

    置き場は herdr の既定（設定の worktrees.directory の下の <リポジトリ>/<ブランチの slug>）に任せる。手元に同じ名前のブランチが有ればそれを開き、
    無ければ base から作る。元の clone が herdr で開いていなければ、herdr はその作業場も開く（2026-10-15 に 0.9.3 で見た）。
    --trust-repository は付けない。自分の持ち物のリポジトリでは要らなかった（2026-10-15 に 0.9.3 で見た）。herdr の文書は、
    持ち主が確かめたリポジトリにだけ付けるよう求めている。"""
    return _opened(_call(["herdr", "worktree", "create", "--cwd", source, "--branch", branch, "--base", base,
                          "--label", label, "--no-focus"], runner))


def open_worktree(source, path, label, runner=_default_runner):
    """在る worktree の herdr の作業場を開く（もう開いていれば、その作業場を返す）。書く口。
    --path だけでは worktree_not_found になり、元の clone を --cwd で渡すと通った（2026-10-15 に 0.9.3 で見た）。"""
    return _opened(_call(["herdr", "worktree", "open", "--cwd", source, "--path", path, "--label", label, "--no-focus"],
                         runner))


def remove_worktree(source, path, label, runner=_default_runner):
    """worktree の checkout を消し、その作業場も閉じる。書く口。herdr の remove は作業場の ID で指すので、開いていなければ開いてから消す。
    --force は付けない。未コミットの変更か git に足していないファイルが有れば、herdr は dirty_worktree_requires_force で断る
    （2026-10-15 に 0.9.3 で見た）。手元のブランチは消さない（herdr も残す）。{path, workspace_id} を返す。"""
    ws = _opened(_call(["herdr", "worktree", "open", "--cwd", source, "--path", path, "--label", label, "--no-focus"],
                       runner))["workspace_id"]
    got = _call(["herdr", "worktree", "remove", "--workspace", ws], runner)
    return {"path": _norm(got.get("path")), "workspace_id": got.get("workspace_id")}


def _socket_path(env=os.environ, runner=_default_runner):
    """herdr のソケットの場所。herdr のペインの中なら環境変数 HERDR_SOCKET_PATH（herdr が渡す）、無ければ herdr status server --json の
    socket（0.9.3 で見た形: {"status": …, "running": …, "socket": "<パス>"}。人向けの「socket:」の行は読まない）。"""
    if env.get("HERDR_SOCKET_PATH"):
        return env["HERDR_SOCKET_PATH"]
    argv = ["herdr", "status", "server", "--json"]
    p = runner(argv)
    try:
        sock = json.loads(p.stdout or "").get("socket")
    except (ValueError, AttributeError):
        sock = None
    if not isinstance(sock, str) or not sock:
        raise HerdrError(argv, f"ソケットの場所が分からない（答えの JSON に socket が無い: {(p.stdout or p.stderr or '').strip()[:200]}）")
    return sock


def _request(method, params, env=os.environ, runner=_default_runner, connect=None):
    """CLI に口の無いメソッドを、herdr のソケットの API に 1 行の JSON で頼む（herdr 0.9.3 の CLI に作業場を並べ替えるコマンドが無い）。
    答えの result を返す。失敗は HerdrError。形は 2026-10-17 に herdr 0.9.3（protocol 22）の実物で見た（頼み {id, method, params} の
    1 行に、答え {id, result} か {id, error: {code, message}} の 1 行が返る）。"""
    argv = ["herdr", "api", method]
    if connect is None:
        if not hasattr(socket, "AF_UNIX"):
            raise HerdrError(argv, "この Python では herdr のソケットにつなげない（AF_UNIX が無い）")

        def connect(path):
            s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            s.connect(path)
            return s
    try:
        s = connect(_socket_path(env, runner))
        try:
            s.sendall((json.dumps({"id": "works-dispatch", "method": method, "params": params}) + "\n").encode("utf-8"))
            buf = b""
            while b"\n" not in buf:
                chunk = s.recv(65536)
                if not chunk:
                    break
                buf += chunk
        finally:
            s.close()
    except OSError as e:
        raise HerdrError(argv, f"ソケットにつなげない（{e}）")
    try:
        got = json.loads(buf.split(b"\n", 1)[0].decode("utf-8"))
    except ValueError:
        raise HerdrError(argv, f"JSON でない答え: {buf[:200]!r}")
    if isinstance(got.get("error"), dict):
        raise HerdrError(argv, got["error"].get("code") or got["error"].get("message") or "失敗")
    return got.get("result", {})


def move_workspace(workspace_id, insert_index, request=_request):
    """作業場を、herdr の並びの insert_index の位置へ動かす（workspace.move）。insert_index は動かす前の並びで数え、その位置に
    今いる作業場の前に入る（自分の位置か、その次を渡すと動かない。2026-10-17 に herdr 0.9.3 で確かめた）。"""
    request("workspace.move", {"workspace_id": workspace_id, "insert_index": insert_index})


def close_workspace(workspace_id, runner=_default_runner):
    """herdr の作業場を閉じる。書く口。"""
    _call(["herdr", "workspace", "close", workspace_id], runner, quiet_ok=True)
