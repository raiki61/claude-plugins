"""herdr への口。dispatch で herdr を呼ぶのはこの 1 か所だけ（設計書のセクション 4）。

herdr は版が 0.x で互換を約束していない。herdr の文書は、手元の版の API を `herdr api schema` で確かめるよう求めている。
出力の形が変わって壊れたら、直すのはこのファイルだけになる。出力の形は 2026-10-14 と 2026-10-15 に herdr 0.9.3 の実物で読んだ。

作業場の場所（元の clone の git worktree）も、作る・並べる・開く・消すをここに寄せる（worktrees・create_worktree・open_worktree・
remove_worktree）。ノードは「ブランチの場所」の言葉だけで書き、herdr の worktree の口の形を知らない。

書く関数は run・prompt・send_keys・rename_pane・rename_workspace・report_pane_metadata・report_workspace_metadata・move_workspace・create_worktree・open_worktree・remove_worktree・close_workspace・
report_activity で、
呼んでよいノードはチェック（tests/fences.py の D4 の表 WRITES）が構文木で見る。
"""

import json
import os
import socket
import subprocess
import time

STALLED = "agent_prompt_stalled"


class HerdrError(Exception):
    def __init__(self, argv, detail):
        super().__init__(f"{' '.join(argv[:3])}: {detail}")
        self.argv = argv
        self.detail = detail


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


def panes(runner=_default_runner):
    out = []
    for p in _call(["herdr", "pane", "list"], runner).get("panes", []):
        out.append({**p, "agent": p.get("agent")})
    return out


def place_of(path):
    """場所のルート（path から上へたどって最初に .git の在るフォルダ。git の作業場のルート）。無ければ path 自身。git を呼ばずに字と
    ファイルだけで決める（ペインの数だけ呼ぶので）。"""
    here = os.path.realpath(path)
    up = here
    while True:
        if os.path.exists(os.path.join(up, ".git")):
            return up
        parent = os.path.dirname(up)
        if parent == up:
            return here
        up = parent


def own_pane(cwd, sid=None, listed=None):
    """会話の居るペイン。場所のルート（place_of）がこの会話と同じペインのうち、会話の印〔agent_session〕がこの会話の id の物が 1 つなら
    それ、無ければ場所の同じ物が 1 つならそれ。決まらなければ None。listed は panes() の並び（省けば読む）。
    場所の違うペインは、印がこの会話の id でも選ばない（herdr の印は前にそのペインに居た会話や別の部署の会話の id のまま残ることが
    あり、2026-10-17 に my_notes で、ノートの手入れの待ち受けが印の合った調べものの窓に /clear を打った）。
    環境変数 HERDR_PANE_ID は使わない（裏の会話〔claude --bg〕は前もって起動した控えの処理の値を継ぎ、別のペインを指していた。
    2026-10-17 に見た）。"""
    if not cwd:
        return None
    here = place_of(cwd)
    talking = [p for p in (panes() if listed is None else listed) if p.get("agent")]
    hits = [p for p in talking if p.get("cwd") and place_of(p["cwd"]) == here]
    mine = [p for p in hits if sid and (p.get("agent_session") or {}).get("value") == sid]
    if len(mine) == 1:
        return mine[0]["pane_id"]
    return hits[0]["pane_id"] if len(hits) == 1 else None


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
    """1 つのペインのエージェントの情報（agent・agent_status など）。"""
    return _call(["herdr", "agent", "get", target], runner).get("agent", {})


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
    （2026-10-16 に herdr 0.9.3 で見た）。ansi なら色と薄字の制御の字（SGR）を付けたまま返す（deliver.typed が薄字を見分ける）。"""
    argv = ["herdr", "pane", "read", pane, "--lines", str(lines)] + (["--ansi"] if ansi else [])
    p = runner(argv)
    if p.returncode != 0:
        raise HerdrError(argv, _error_code(p.stdout) or (p.stderr or p.stdout).strip()[:300])
    return p.stdout


def foreground(pane, runner=_default_runner):
    """ペインの前で動いているプロセスの起動したコマンドの並び（herdr pane process-info の foreground_processes の cmdline）。読む口。"""
    info = _call(["herdr", "pane", "process-info", "--pane", pane], runner).get("process_info", {})
    return [p.get("cmdline") or " ".join(p.get("argv") or []) for p in info.get("foreground_processes") or []]


def front_processes(pane, runner=_default_runner):
    """ペインの前で動いているプロセスの並び（herdr pane process-info の foreground_processes。pid と argv を持つ）。読む口。"""
    info = _call(["herdr", "pane", "process-info", "--pane", pane], runner).get("process_info", {})
    return info.get("foreground_processes") or []


def holds_talk(processes, pids, jobs):
    """ペインの前のプロセス（front_processes）に、この会話が居るか。会話の処理そのもの（pids のどれか。前で開いた会話）か、
    この会話へ attach した claude（argv の attach の次の字が jobs のどれか。裏の会話〔claude --bg〕を開いた窓）が居れば真。
    会話の印〔agent_session〕は古いまま残ることがあるので見ない。"""
    for p in processes:
        if p.get("pid") in pids:
            return True
        argv = p.get("argv") or []
        if any(a == "attach" and i + 1 < len(argv) and argv[i + 1] in jobs for i, a in enumerate(argv)):
            return True
    return False


def talk_window(cwd, h, pids=(), jobs=()):
    """会話を消す打ち込み（/clear）の打ち先。場所がこの会話の場所のペインのうち、前のプロセスにこの会話が居ると確かめられた物
    （holds_talk。jobs は attach の短い id の候補で、clear_now は属性 company.job・CLAUDE_JOB_DIR の名前・会話の id の頭を渡す）が
    1 つならそれ、ほかは None。会話の印（agent_session）も、場所だけでの代わりも使わない（印は前に居た会話や
    別の部署の会話の id のまま残り、2026-10-17 に my_notes で別の部署の窓に /clear を打った。持ち主の決め: 自分の会話だと確かめ
    られなければ打たずに残す）。"""
    here = place_of(cwd)
    hits = [p["pane_id"] for p in h.panes() if p.get("agent") and p.get("cwd") and place_of(p["cwd"]) == here]
    mine = [x for x in hits if holds_talk(h.front_processes(x), {p for p in pids if p is not None}, {j for j in jobs if j})]
    return mine[0] if len(mine) == 1 else None


def job_of(env=os.environ):
    """この会話の裏の処理の短い id（`claude attach` に渡す物）。Claude Code は裏の会話（claude --bg）の処理に、置き場
    <設定のフォルダ>/jobs/<短い id> を CLAUDE_JOB_DIR で渡し、フックはそれを継ぐ。短い id は会話の id の頭と同じとは限らない
    （2026-10-17 に割り振りで、会話 081f72dd を短い id 8c4a1102 の処理が続けていた）。裏の会話でなければ None。"""
    d = (env.get("CLAUDE_JOB_DIR") or "").rstrip("/\\")
    return os.path.basename(d) or None


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
