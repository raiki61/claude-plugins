"""役を起こす関数——節 1 つ分を、子プロセスの起動から受け付けまで 1 回の呼び出しで完結させる。

**盤面（Board）も graph も import しない。** 受け取るのは起こす語（argv）・材料のファイル・返答の置き場・
受け付けの検査（呼び出し側が渡す関数）・要約の書き先だけで、どれも値かファイルのパスである。今の engine
（commands.cmd_launch）も、将来の実行の核（例えば LangGraph の節）も、同じこの関数を呼ぶ——核を載せ替えても
役の起こし方・待ち方・続きの頼み方・要約の残し方を写し直さないため（docs の作り直しの設計「手順 1」）。

流れ:
  1. argv を子プロセスで起こし、材料を標準入力で渡す（貼る上限に当たらない）。
  2. **子の終了を直接待つ。** 完了の知らせ（通知・中継の AI の『書いた』）には頼らない——知らせは入れ子や上限落ちで
     消えた（実測 2026-09-24〜25: 局所レビューの入れ子の起動で知らせが届かず 7 時間止まった）。**時間の上限は付けない**
     ——所要時間を実測で決めていない値が上限を兼ねると、長く考える役を途中で打ち切る（2026-09-25 に外した。理由は
     docs/graphloops-rearchitecture.md の「期限を外した」）。子を起こすたびに、そのプロセスグループの番号を返答の置き場の
     隣（pgid_path）に書き、子が終わったら消す——別のプロセス（loop.py relaunch）が古い試行を木ごと止める口
     （前置の層 with-auth.py が子の claude を孫として起こすので、層だけを止めると claude が孤児で走り続ける）。
  3. 標準出力が `--output-format json` の包み（result・session_id・num_turns・duration_ms・total_cost_usd・usage）なら
     解いて返答の本文だけを、包みでなければ標準出力の全文を本文として out_path に書く（unwrap）。要約は log_path
     （engine は盤面の trace.jsonl）に JSON Lines で 1 起動 1 行残す。
  4. accept(本文) で受け付けを検査する。拒まれたら、理由を添えて**同じ会話**に続きを頼む（resume_argv の
     {session_id} を埋めて起こし、理由の文を標準入力で渡す）。新しい会話で起こし直すと、役は前の返答を
     覚えておらず、同じ判定を出し直す保証が無い。

返り値は呼び出し側が盤面に写す値だけ（本文は含めない——回す側の会話に役の返答を流し込まないため）。

役でなく**コマンドを走らせるだけの節**（対象リポジトリが宣言したテスト一式など）も同じ起こし方で走らせる（run_steps）。
"""
import datetime
import json
import os
import pathlib
import shutil
import signal
import subprocess
import sys
import threading
import time

RESUME_NOTE = ("受け付けの検査がこの返答を拒んだ。理由:\n{why}\n\n"
               "理由が返答の形（JSON として読めない・型に合わない）なら、判定も中身も変えずに形だけ直せ。"
               "理由が中身の整合（記録の整合・項目の過不足など）なら、理由が指す所だけを直せ。"
               "どちらも、最初の指示が求めた形の返答だけを出し直せ（前後に文を付けない）。")
KILL_GRACE = 5  # 止める信号の間の猶予（秒）
STOP_SIGNALS = (signal.SIGTERM, signal.SIGKILL) if os.name == "posix" else ()  # 試行の木を止める信号の列（_kill と stop_group）
SUPERSEDED = "起こし直された古い試行——次の手は要らない（新しい試行は relaunch が作った物）"
# engine の中から起こす子に持たせない道具（ファイルを書く道具）。道具つきの役の**能力の上限**——道具ゼロの役が
# 「何も実行できない」と言えるのと同じく、engine が起こす子は「ファイルを書く道具を持たない」と言える形にする。
# 役の定義にこれが在れば engine は起こさない（回す側が Agent で起こす）。値は graph でなく engine が持つ——graph の書き換えで
# 起こせる物が広がらないように（commands.launch_refusal の注記）
WRITE_TOOLS = ("Write", "Edit", "MultiEdit", "NotebookEdit")
# コマンドを走らせる道具。これを持つ役には、道具ごとでなくコマンドの形ごとに許す（READ_COMMANDS）
COMMAND_TOOLS = ("Bash",)
# コマンドを走らせる役に先に許す、読むだけのコマンドの前置。**書く旗を持たないサブコマンドだけ**を入れる——前置の許可は
# 後ろの引数を縛れない。gh api は入れない（引数を付けると既定が POST になり、-X で任意のメソッドを指せる。gh の公式マニュアル）。
# git remote get-url は組み込みの読むだけの git に入らず拒まれた（実測 2026-09-25）ので名指しする（gh の -R をそこから導く）。
# 値は graph でなく engine が持つ——graph の書き換えで許すコマンドが広がらないように。前置にカンマを入れない（柵が --allowedTools を
# カンマで割って比べる）
READ_COMMANDS = ("gh issue list", "gh issue view", "gh pr list", "gh pr view", "gh pr diff", "gh search", "gh repo view",
                 "git remote get-url")
# sandbox の形の設定のうち、起こす場所に依らない値。書き込みを止める場所（filesystem.denyWrite）は protected_paths が起こす時に足す。
# - autoAllowBashIfSandboxed: sandbox の中のコマンドは dontAsk の下でも聞かずに通す（計器を前置で列挙しても任意のコードを許すのと
#   同じなので、守りは OS の境界に置く）
# - allowUnsandboxedCommands false・failIfUnavailable true: sandbox の外へ出る口を閉じ、sandbox が起きなければ起動時に誤りで終わる
#   （既定の false では警告だけ出して sandbox の外で走る——claude 2.1.282 の設定の説明文）
# - excludedCommands に gh: gh は sandbox の外で走り、権限の流れ（dontAsk ＋ READ_COMMANDS）に落ちるので書く gh は拒まれる。
#   つないだ gh（gh pr diff | head・cd x && gh …）は除外に当たらず sandbox の中で走り、通信が無いので止まる
# - 通信の許可は空・strictAllowlist: sandbox の中のコードは既定でディスク全体を読める（~/.config/gh の token も）ので、GitHub の宛先を
#   許すと READ_COMMANDS を迂回して書く gh が打てる。gh は sandbox の外に出したので、中に GitHub への通信は要らない
SANDBOX_BASE = {"enabled": True, "autoAllowBashIfSandboxed": True, "allowUnsandboxedCommands": False, "failIfUnavailable": True,
                "excludedCommands": ["gh:*"], "network": {"allowedDomains": [], "strictAllowlist": True}}
LIVE = set()  # いま生きている子（Popen）。loop.py が止める信号を受けたとき kill_all が木ごと止める
_LIVE_LOCK = threading.RLock()   # 信号の口（kill_all）が、錠を持つ最中の同じスレッドに割り込んでも止まらないよう再入可能に
_STOPPING = threading.Event()     # 止める信号を受けた——以後に起こした子はすぐ止める（止め始めた後に子を増やさない）


def sandbox_available():
    """この環境で claude の sandbox が起きるか。macOS は sandbox-exec が在るとき。Linux（WSL2 を含む）は bwrap と socat が在り、
    bwrap が実際に名前空間を作れるとき——PATH に在るだけでは足りない（Ubuntu 24.04 以降の既定の AppArmor は bwrap に名前空間を
    作らせず、sandbox を選ぶと failIfUnavailable で役が 1 本も起きなくなる）。ほか（Windows）は偽。偽なら読むだけの形に落ちる。"""
    if sys.platform == "darwin":
        return bool(shutil.which("sandbox-exec"))
    if not sys.platform.startswith("linux") or not (shutil.which("bwrap") and shutil.which("socat")):
        return False
    try:
        r = subprocess.run(["bwrap", "--ro-bind", "/", "/", "--unshare-user", "--unshare-net", "true"],
                           capture_output=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return False
    return r.returncode == 0


def _git(cwd, *args):
    """cwd で git を走らせる。返すのは (成功か, 行, 標準エラー)。git が無い・時間切れは (False, [], 理由)。
    role_run は盤面も graph も import しないので、engine の util.git を使わない。"""
    try:
        r = subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=30)
    except (OSError, subprocess.SubprocessError) as e:
        return False, [], str(e)
    return r.returncode == 0, r.stdout.splitlines(), r.stderr


def protected_paths(cwd, board_dir=None):
    """sandbox の中の書き込みを止める場所（filesystem.denyWrite）。**cwd 自身を含む**作業ツリーの根の全部（git worktree list）・
    共有の .git の実体（git rev-parse --git-common-dir。linked worktree の gitdir と既定の盤面の置き場を含む）・盤面の置き場。
    書けるのは sandbox の既定の TMPDIR だけになる——cwd を書ける場所に残すと、役が計器を動かしてレビュー対象の未コミットの変更を
    壊せ、前後の作業ツリーの突合は事故の検知で中身を戻さない（.gitignore の対象は突合にも映らない）。祖先の作業ツリー
    （<repo>/.claude/worktrees/<名前> の本体）も根ごと名指しできる。git の作業ツリーでない cwd は cwd と盤面だけ。
    git が読めない（git が無い・時間切れ）なら None——守る場所が決まらないので sandbox の形を選ばない。"""
    cwd = os.path.realpath(cwd or os.getcwd())
    paths = {cwd} | ({os.path.realpath(board_dir)} if board_dir else set())
    ok, common, err = _git(cwd, "rev-parse", "--path-format=absolute", "--git-common-dir")
    if not ok:
        return sorted(paths) if "not a git repository" in err else None
    ok, trees, _err = _git(cwd, "worktree", "list", "--porcelain")
    if not ok or not common:
        return None
    paths.add(os.path.realpath(common[0]))
    paths |= {os.path.realpath(x[len("worktree "):]) for x in trees if x.startswith("worktree ")}
    return sorted(paths)


def tooled_permission(tools, cwd=None, board_dir=None):
    """道具つきの役を起こす形——{form, permission_mode, allowed_tools, settings}。**起こす側（launch_spec）と柵（launch_refusal）が
    同じここを引く**。graph は穴（{permission_mode}・{allowed_tools}・{settings}）を持つだけで、値は役の定義の道具から engine が決める。

    -p の開始の権限は起こした側の設定を継ぐ（回す側が bypassPermissions なら子も）ので、必ず明示する。形は先に許した物だけが
    通る dontAsk の 1 つ（Read・Glob・Grep は許さなくても通り、WebFetch・WebSearch は許さないと拒まれる。実測 2026-09-25・haiku）。
    分類器（auto）に掛けていたときは読むだけの gh issue list まで拒まれた（実測 2026-09-25）。

    form は 3 つ:
    - plain: Bash を持たない役。settings は {}。
    - sandbox: Bash を持ち、sandbox_available() が真で、protected_paths が決まった役。Bash を丸ごと許さず READ_COMMANDS の前置だけを
      Bash(<前置>:*) で許し（sandbox の外で走る gh の関門）、sandbox の中のコマンド（テスト一式・計器の台本）は OS の境界の中で
      聞かずに通す（SANDBOX_BASE）。前置の一覧だけで計器を許さなかったのは、pytest を許すと conftest.py から任意のコードが走り、
      git diff --output= も作業ディレクトリの外や .git に書けたから（実測 2026-09-25・haiku・claude 2.1.282）。
    - read_only: Bash を持つが sandbox を使えない環境。READ_COMMANDS の前置だけを許し、settings は {}（今の読むだけの形。計器の実行は
      権限で拒まれる）。

    read_only の形の実測（2026-09-25・haiku・claude 2.1.282・--permission-prompts none）: 通った——gh issue list・gh pr view・
    gh repo view・gh search issues・gh pr diff | head・引数の無い gh issue list・git remote get-url（許可に足した後）・組み込みの
    git log・git diff・git show・git rev-parse。permission_denials に載り実行されなかった——gh issue create・gh pr merge・
    gh api -X POST・読むだけの gh api・bash -c・python3 -c・git diff --output=・git log --output=・読むだけの gh に > を付けた物・
    && / ; でつないだ物・$(…) を挟んだ物・git -C <別の場所>・cd <別の場所> && git log。
    sandbox の形の実測（2026-09-25・haiku・claude 2.1.282・macOS 26.6.2。使い捨ての clone の linked worktree を cwd にし、もう 1 本の
    worktree・clone の本体・盤面の置き場を名指し）: 通った——python3 -m pytest graphloops/tests/py（102 件緑）・bash tests/run.sh と
    bash graphloops/tests/run.sh（下の 1 件のほか緑）・git status・git log・単独の gh issue list と gh pr view（sandbox の外）・WebFetch。
    止まった——cwd・共有の .git・もう 1 本の worktree・clone の本体・盤面への touch（Operation not permitted）・curl で example.com と
    api.github.com（deny network-outbound）・テストの中からの .git への書き込みと urlopen・gh pr diff | head と cd /tmp && gh issue create
    （除外に当たらず sandbox の中で通信が無い）・uv run --with（~/.cache/uv に書けない）・macOS の型なし mktemp -d（TMPDIR を見ず
    /var/folders に作る。tests/run.sh は型を渡す）・別のプロセスグループへの信号（simulate.py の stop_group の台本 1 件が EPERM）。
    permission_denials に載った——gh issue create・python3 -c・git diff --output=・git commit。前後で git status は変わらなかった。
    作業ディレクトリの外の git は dontAsk が拒むので、子は対象の作業ツリーで起こす（commands.launch_one）。"""
    allowed = [t for t in tools if t not in COMMAND_TOOLS]
    if len(allowed) == len(tools):
        return {"form": "plain", "permission_mode": "dontAsk", "allowed_tools": allowed, "settings": "{}"}
    allowed += [f"Bash({c}:*)" for c in READ_COMMANDS]
    deny = protected_paths(cwd, board_dir) if sandbox_available() else None
    if deny is None:
        return {"form": "read_only", "permission_mode": "dontAsk", "allowed_tools": allowed, "settings": "{}"}
    settings = {"sandbox": {**SANDBOX_BASE, "filesystem": {"denyWrite": deny}}}
    return {"form": "sandbox", "permission_mode": "dontAsk", "allowed_tools": allowed,
            "settings": json.dumps(settings, ensure_ascii=False, sort_keys=True)}


# 任せ先（graph の delegate を持つ回す側の節）に渡す道具。ファイルを書く道具（WRITE_TOOLS）は渡さない——任せ先が書くのは
# 作業ディレクトリの外に作る写しで、Edit(./**) のように作業ディレクトリに縛った書く道具はそこへ届かない。書くのは Bash だけで、
# Bash は OS の sandbox の中でだけ走る（delegate_settings）
DELEGATE_TOOLS = ("Bash", "Read", "Glob", "Grep", "WebFetch", "WebSearch")


def delegate_permission():
    """任せ先の権限の形 (permission_mode, allowed_tools)。起こす側（advance.delegate_launch_spec）と柵（commands.launch_refusal）が
    同じここを引く。**Bash は先に許さない**——sandbox の中で走るコマンドは sandbox の自動の許し（autoAllowBashIfSandboxed）で
    通り、sandbox の外に落ちるコマンドは聞く先が無い（--permission-prompts none）ので拒まれる。実測 2026-09-25・haiku: この形で
    sandbox の中の python3・git status・作業ディレクトリへの書き込みは通り、sandbox を切った設定（enabled: false。管理者の設定が
    切った場を写した）では Bash が全部拒まれた。dontAsk は sandbox の中のコマンドまで拒むので採らない（同日の実測）"""
    return "default", [t for t in DELEGATE_TOOLS if t not in COMMAND_TOOLS]


def delegate_settings(protected):
    """任せ先の sandbox の設定（--settings に渡す JSON の文字列。並びを固定して、柵が起こす瞬間に組み直して突き合わせる）。

    - denyWrite: protected（util.protected_paths——本物の作業ツリー・gitdir の実体・共通の .git・他の作業ツリー・盤面・
      git とシェルの設定・engine 自身）。allowWrite より優先される（公式の設定の説明: 'takes precedence over allowWrite'）
    - allowWrite ['/']: 名指しした場所の外は今までどおり書ける——依存の置き場（~/.cache 等）・写し。狭めると、今の任せ先が
      できていた依存の導入が落ちる（実測 2026-09-25: 既定の範囲では uv が ~/.cache/uv を開けなかった）
    - allowUnsandboxedCommands: false と failIfUnavailable: true——sandbox の外で走る道と、sandbox が立たない場で黙って素通しになる道を閉じる
    - network.allowedDomains ['*']・enableWeakerNetworkIsolation・allowLocalBinding: 網（依存の導入・gh の読み）と手元のサーバを
      今までどおり使う（実測 2026-09-25・macOS: gh は enableWeakerNetworkIsolation が無いと TLS の検証で落ち、localhost の bind は
      allowLocalBinding で通った）"""
    return json.dumps({"sandbox": {
        "enabled": True, "autoAllowBashIfSandboxed": True, "allowUnsandboxedCommands": False, "failIfUnavailable": True,
        "enableWeakerNetworkIsolation": True,
        "network": {"allowedDomains": ["*"], "allowLocalBinding": True},
        "filesystem": {"allowWrite": ["/"], "denyWrite": list(protected)}}}, sort_keys=True, separators=(",", ":"))


def kill_all():
    """生きている子を全部木ごと止める（loop.py が SIGTERM・SIGHUP・SIGINT を受けたとき。install_stop_handlers）。
    止め切れなかった木は理由を標準エラーに出す（黙って止めたことにしない）"""
    with _LIVE_LOCK:
        live = list(LIVE)
    for p in live:
        why = _kill(p)
        if why:
            print(f"NG 子の木を止め切れない（pid {p.pid}）: {why}", file=sys.stderr)


class StopSignal(KeyboardInterrupt):
    """loop.py が止める信号を受けた（生きている子は kill_all で止めてある）。KeyboardInterrupt の派生にするのは、
    engine の中で SystemExit・Exception を捕まえる口（rules・検証器の読み込み、受け付けの検査、盤面の締め）に飲まれず、
    入口（loop.py の main）まで抜けるため"""

    def __init__(self, signum):
        super().__init__(signum)
        self.signum = signum


def install_stop_handlers():
    """止める信号（SIGTERM・SIGHUP・SIGINT）を受けたら、生きている子を木ごと止めてから StopSignal を上げる。loop.py の main が
    全コマンドの前に 1 度だけ呼ぶ——子は別のプロセスグループに切り離してあるので、loop.py に届いた信号は子に届かず、
    next・done の中の builtin が run_tree で起こしたテスト一式も launch の役の子も、ここで止めないと作業ツリーに書き続ける"""
    import signal as _signal

    def stop(signum, _frame):
        _STOPPING.set()
        kill_all()
        raise StopSignal(signum)
    for name in ("SIGTERM", "SIGHUP", "SIGINT"):
        if hasattr(_signal, name):
            _signal.signal(getattr(_signal, name), stop)


# 包みの欄のうち要約に残すもの（--output-format json の result の行）。本文（result）は残さない
SUMMARY_KEYS = ("session_id", "num_turns", "duration_ms", "duration_api_ms", "total_cost_usd", "usage",
                "subtype", "is_error", "stop_reason")


def pgid_path(out_path):
    """試行の子のグループの番号の印の置き場（<out_path>.pgid）。書く run_role と、読んで止める relaunch が同じここを引く"""
    return str(out_path) + ".pgid"


def _popen(argv, **kw):
    """子を新しいプロセスグループで起こし、生きている子の集合（LIVE）に載せる。木ごと止めるため（_kill・stop_group）。
    外すのは _forget（待ち終えた後）"""
    grp = ({"start_new_session": True} if os.name == "posix"
           else {"creationflags": getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)})
    p = subprocess.Popen(argv, **kw, **grp)
    with _LIVE_LOCK:
        LIVE.add(p)
    if _STOPPING.is_set():   # 止める信号の後に起こした子（並列の launch の続きの往復など）——kill_all はもう走った
        _kill(p)
        _forget(p)
        raise StopSignal(0)
    return p


def _forget(p):
    with _LIVE_LOCK:
        LIVE.discard(p)


def _stop_tree(pgid, leader=None):
    """プロセスグループ pgid を止める。返すのは止め切れなかった理由（None なら止まった・居なかった）。

    POSIX は STOP_SIGNALS を順にグループへ送り、**長でなくグループの消滅**まで KILL_GRACE ずつ待ち、残れば次の信号へ
    （systemd の KillMode=control-group と同じ形——長が先に終わっても、SIGTERM を無視する孫には SIGKILL が届く）。
    長の Popen（leader）を持つなら待つ間に回収する（回収しない長はゾンビのままグループに残り、消滅が見えない）。
    Windows はグループへの信号が無いので taskkill /T /F（親子の鎖で木を辿る）。"""
    if os.name != "posix":
        r = subprocess.run(["taskkill", "/T", "/F", "/PID", str(pgid)], capture_output=True, text=True, encoding="utf-8", errors="replace")
        if leader is not None:
            try:
                leader.wait(KILL_GRACE)
            except subprocess.TimeoutExpired:
                pass
        if r.returncode != 0 and (leader.poll() is None if leader is not None else _started_at(pgid) != GONE):
            return f"taskkill が {pgid} を止められない（exit {r.returncode}: {(r.stdout + r.stderr).strip()[-200:]}）"
        return None

    def alive():
        if leader is not None:
            leader.poll()
        try:
            os.killpg(pgid, 0)
            return True
        except ProcessLookupError:
            return False
        except PermissionError:
            return True

    for sig in STOP_SIGNALS:
        try:
            os.killpg(pgid, sig)
        except ProcessLookupError:
            return None
        except PermissionError as e:
            return f"グループ {pgid} に信号を送れない（{e}）"
        t = time.monotonic() + KILL_GRACE
        while time.monotonic() < t:
            if not alive():
                return None
            time.sleep(0.05)
    return f"グループ {pgid} が SIGKILL の後も残っている"


def _kill(p):
    """起こした子を**木ごと**止める（_stop_tree）。前置の層（with-auth.py）は claude を subprocess.run で起こす殻なので、
    直下の子だけを殺すと孫の claude が out の fd を継いだまま走り続ける（同じ形の事故の先例と解き方はリポジトリの
    tests/mutate.py の run_group）。SIGTERM を先に送るのは、claude -p が SIGTERM で自分の子（Bash の木）を止めて終わるため"""
    why = _stop_tree(p.pid, leader=p)
    try:
        p.wait(KILL_GRACE)
    except subprocess.TimeoutExpired:
        pass
    return why   # 止め切れなかった理由（None なら止まった）


def run_tree(argv, *, cwd, timeout, shell=False):
    """1 回走らせて終わりを待つ（rules がテストの実行器を走らせる口。INJECT で渡る）。返すのは subprocess.CompletedProcess
    （stdout・stderr は UTF-8 の文字列、読めない字は置き換え）。**時間切れ・止める信号・例外のどれで抜けても木ごと止める**
    （_kill）——subprocess.run の timeout は直下の子（シェル・実行器）だけを止め、その子や孫が作業ツリーに書き続ける。
    標準入力は閉じる（対話を待つ実行器が loop.py の標準入力を継いで止まらないように）"""
    p = _popen(argv, cwd=cwd, shell=shell, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
               text=True, encoding="utf-8", errors="replace")
    try:
        out, err = p.communicate(timeout=timeout)
    except subprocess.TimeoutExpired as e:
        # 時間切れの例外に『木が残った』理由を添える（呼び元が起動の失敗と区別して理由の文に載せる）
        e.tree_left = _kill(p)
        raise
    except BaseException:
        _kill(p)
        raise
    finally:
        _forget(p)
    return subprocess.CompletedProcess(argv, p.returncode, out, err)


class Superseded(Exception):
    """起こした直後に、この試行が起こし直されていた（still_mine が偽を返した）。子は木ごと止めてある。"""


def _spawn(argv, stdin_bytes, cwd=None, env=None, pgid_file=None, still_mine=None):
    """1 回起こして終了を待つ（上限なし）。返すのは (exit, stdout, stderr)。

    **どの道で抜けても子を残さない**（finally）——待っている間に例外・SystemExit・KeyboardInterrupt で抜けた回も
    木ごと止める。子は別のプロセスグループに切り離してあるので、親のグループに届く信号はもう子に届かない。

    pgid_file を渡されたら、起こした直後に子のグループの番号を書き、子が終わったら消す。**書いてから still_mine を
    聞く**——relaunch は新しい試行を盤面に書いてから、この印を読んで止める。どちらの順で交わっても、古い試行の子は
    どちらか一方が止める（印を書いたのが先なら relaunch が、盤面が先に進んでいたら still_mine が）。"""
    p = _popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, cwd=cwd, env=env)
    ended = False
    try:
        if pgid_file:
            # 印の更新時刻が『この子を起こした後』の目印になる（stop_group が番号の再利用を開始時刻で見分ける）
            pathlib.Path(pgid_file).write_text(json.dumps({"pgid": p.pid}), encoding="utf-8")
        if still_mine is not None and not still_mine():
            raise Superseded
        out, err = p.communicate(stdin_bytes)
        ended = True
        return p.returncode, out, err
    finally:
        if not ended:
            why = _kill(p)
            if why:
                print(f"NG 子の木を止め切れない（pid {p.pid}）: {why}", file=sys.stderr)
        _forget(p)
        if pgid_file:
            pathlib.Path(pgid_file).unlink(missing_ok=True)


GONE = "gone"   # _started_at の『その番号のプロセスは居ない』
REUSE_SLACK = 2.0   # 開始時刻の読みの誤差（ps の etime は秒の切り捨て）。印より後にこれを超えて始まったプロセスは別物


def _started_at(pid):
    """pid のプロセスの開始時刻（エポック秒）。居なければ GONE、確かめられなければ None。
    POSIX は ps の etime（経過。[[dd-]hh:]mm:ss でロケールに依らない）から、Windows は Win32_Process の CreationDate
    （ToFileTimeUtc の整数）から出す。開始時刻で見分けるのは psutil の Process と同じ形（番号＋作成時刻で同一性を持つ）
    ——コマンド行の語で見ると、同じ engine が起こした兄弟の試行（同じ python・同じ with-auth.py）を見分けられない"""
    if os.name == "posix":
        argv = ["ps", "-o", "etime=", "-p", str(pid)]
    else:
        argv = ["powershell", "-NoProfile", "-Command",
                f"$p = Get-CimInstance Win32_Process -Filter 'ProcessId={int(pid)}'; "
                "if ($p) { 'alive:' + $p.CreationDate.ToFileTimeUtc() } else { 'gone' }"]
    try:
        r = subprocess.run(argv, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30)
    except (OSError, subprocess.SubprocessError):
        return None
    if os.name != "posix":
        return parse_cim(r.stdout)
    out = r.stdout.strip()
    if not out:
        return GONE if not r.stderr.strip() else None   # 居ない番号は出力も誤りの文も無い（exit 1）
    secs = parse_etime(out)
    return None if secs is None else time.time() - secs


def parse_etime(s):
    """ps の etime（[[dd-]hh:]mm:ss）を秒に。読めなければ None"""
    try:
        days, _, rest = s.strip().rpartition("-")
        parts = [int(x) for x in rest.split(":")]
        if not 2 <= len(parts) <= 3:
            return None
        h, m, sec = ([0] + parts)[-3:]
        return (int(days) if days else 0) * 86400 + h * 3600 + m * 60 + sec
    except ValueError:
        return None


def parse_cim(out):
    """Windows の問い（'alive:<FILETIME>' か 'gone'）を _started_at の値に読む: gone → GONE、FILETIME → エポック秒、
    それ以外（居るのに読めない・空）→ None（確かめられない）"""
    out = (out or "").strip()
    if out == "gone":
        return GONE
    if not out.startswith("alive:"):
        return None
    try:
        return (int(out[len("alive:"):].strip()) - 116444736000000000) / 1e7   # 1601-01-01 からの 100ns → 1970 からの秒
    except ValueError:
        return None


def probe_group(pgid_file):
    """印（<out_path>.pgid）が指す試行の子のグループを、**信号を送らずに**確かめる ——(pgid, why)。
    pgid が None なら止める物が無い（印が無い・番号が別のプロセスに再利用されていた——そのときは印を消す）。
    why は確かめられない理由（印が読めない・開始時刻が取れない）。relaunch は新しい試行を書く前にこれだけを呼ぶ
    （止められない試行の上に新しい試行を作らない）。

    **番号の再利用は開始時刻で見分ける**: 印は子を起こした直後に書くので、印の更新時刻より後に始まったプロセスは別物
    （REUSE_SLACK は読みの誤差）。POSIX で長が居ないなら止める側に倒す——グループが在る限りその番号は再利用されないので、
    残っているのは古い試行の孫である。Windows で長が居ないなら止める物は無い（taskkill /T は親子の鎖で木を辿る）。"""
    path = pathlib.Path(pgid_file)
    try:
        mark = json.loads(path.read_text(encoding="utf-8"))
        pgid = int(mark["pgid"])
        written = path.stat().st_mtime
    except FileNotFoundError:
        return None, None
    except (OSError, ValueError, KeyError, TypeError) as e:
        return None, f"{path}: 読めない（{e}）"
    started = _started_at(pgid)
    if started is None:
        return None, f"プロセス {pgid} の開始時刻を確かめられない（番号が再利用されていれば無関係な木を止めるので、止めない）"
    if started == GONE:
        if os.name != "posix":
            path.unlink(missing_ok=True)
            return None, None
        return pgid, None
    if started > written + REUSE_SLACK:
        path.unlink(missing_ok=True)   # 番号が印より後に始まった別のプロセスに再利用されている——古い試行はもう居ない
        return None, None
    return pgid, None


def stop_group(pgid_file):
    """別のプロセスから、試行の子を木ごと止める（loop.py relaunch が使う）。返すのは止め切れなかった理由（None なら止まった・
    居なかった）。確かめ方は probe_group、止め方は _kill と同じ _stop_tree（Popen を持たないので長の回収はしない）。
    印は子が終わると launch の側が消すので、印が無ければ止める物は無い。"""
    pgid, why = probe_group(pgid_file)
    if why or pgid is None:
        return why
    why = _stop_tree(pgid)
    if why is None:
        pathlib.Path(pgid_file).unlink(missing_ok=True)
    return why


def unwrap(stdout):
    """標準出力を解く。返すのは (本文, 要約, 読めない理由)。

    **包みかどうかは出力の形で見る**（起こした語の --output-format は見ない）: type が result の object だけが
    `--output-format json` の包み（公式の headless 文書・SDKResultMessage）。盤面は init の時の graph の語で役を
    起こすので、古い版の graph で始めた run では --output-format text の素の本文が返る（実測 2026-09-25: 包みしか
    読まなかった版が、exit 0 で返った所見を 3 回捨てた）。包みでなければ全文を本文にして受け付け
    （commands.parse_output の 3 候補）に任せる。そのときの要約は envelope=false だけで、会話の番号・往復数・
    所要時間・費用・トークンは取れない——会話の番号が無いので、拒まれても同じ会話に続きを頼まない。

    包みでは **subtype を result より先に見る**——誤りの種類（error_max_turns・error_during_execution 等）は result を
    持たず errors を持つ。result の有無を先に見ると、誤りで終わった回が『result が無い』に潰れて種類が消える。"""
    text = stdout.decode("utf-8", "replace").strip()
    if not text:
        return None, {}, "標準出力が空（包みも本文も無い）"
    try:
        env = json.loads(text)
    except ValueError:
        env = None
    if not (isinstance(env, dict) and env.get("type") == "result"):
        return text, {"envelope": False}, None
    summary = {"envelope": True, **{k: env[k] for k in SUMMARY_KEYS if k in env}}
    denied = env.get("permission_denials") or []
    if denied:
        summary["permission_denials"] = [str((d or {}).get("tool_name")) for d in denied if isinstance(d, dict)]
    if env.get("is_error") or env.get("subtype", "success") != "success":
        errors = env.get("errors")
        said = "; ".join(map(str, errors)) if isinstance(errors, list) and errors else env.get("result", "result も errors も無し")
        return None, summary, f"役が誤りで終わった（{env.get('subtype')}: {str(said)[:160]}）"
    if "result" not in env:
        return None, summary, f"包みに result が無い（subtype={env.get('subtype')}）"
    return env["result"] if isinstance(env["result"], str) else json.dumps(env["result"], ensure_ascii=False), summary, None


TAIL_LINES = 20      # 走らせた語の出力のうち、返答に写す末尾の行数（全体は置き場のファイルに残す）
TAIL_BYTES = 2000    # その上限（バイト）。1 行が長い出力で返答が膨らまないように


def _tail(data):
    text = data.decode("utf-8", "replace").rstrip()
    return "\n".join(text.splitlines()[-TAIL_LINES:])[-TAIL_BYTES:]


def run_steps(steps, cwd, log_dir, pgid_file=None, still_mine=None):
    """走らせる節（launch の kind=engine_run）の語を 1 本ずつ起こし、終わりを待つ。**役と同じ _spawn** で起こす——別の
    プロセスグループ・期限なし・どの道で抜けても木ごと止める・pgid の印で relaunch が止める、を写さずに使う。

    shell を通さない（argv をそのまま）。標準入力は空。標準出力と標準エラーは log_dir に丸ごと置き、返り値には末尾だけ載せる。
    返すのは段ごとの {name, argv, exit, wall_s, out, err, tail}（exit が None なら起こせなかった——error に理由）。
    起こし直されていれば（still_mine が偽）Superseded を上げる。"""
    log_dir = pathlib.Path(log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)
    runs = []
    for i, s in enumerate(steps):
        started = time.time()
        base = log_dir / f"{i + 1}"
        row = {"name": s["name"], "argv": list(s["argv"]), "out": str(base) + ".out", "err": str(base) + ".err"}
        try:
            rc, out, err = _spawn(list(s["argv"]), b"", cwd=cwd, pgid_file=pgid_file, still_mine=still_mine)
        except OSError as e:
            rc, out, err = None, b"", str(e).encode("utf-8")
            row["error"] = str(e)
        pathlib.Path(row["out"]).write_bytes(out)
        pathlib.Path(row["err"]).write_bytes(err)
        row.update(exit=rc, wall_s=round(time.time() - started, 1), tail=_tail(out + b"\n" + err))
        runs.append(row)
    return runs


def run_role(argv, prompt_file, out_path, *, accept=None, resume_argv=None, max_resumes=0,
             log_path=None, meta=None, cwd=None, env=None, still_mine=None):
    """役を起こし、返答を out_path に書き、受け付けまで済ませる。

    argv        起こす語の全部（前置の層・claude・旗）。同じ会話を続ける節ならここが既に --resume を含む
    prompt_file 指示書（標準入力で渡す）
    out_path    返答の本文の置き場
    accept      accept(本文) -> None（受け付けた）| str（拒んだ理由——役に返して出し直させる）。
                役のせいでない失敗（盤面が読めない等）は例外で投げよ——続きを頼まずに止まり、why に載る
    resume_argv 拒まれたときに同じ会話を続ける語。'{session_id}' の語を会話の番号で埋める。None なら続けない
    max_resumes 続きを頼む回数の上限
    log_path    実行の要約を JSON Lines で足す先（1 起動 1 行・op は role_run。engine は盤面の trace.jsonl を渡す）
    meta        要約の各行に添える値（instance・周など。呼び出し側の語彙で、この関数は読まない）
    cwd / env   子の作業ディレクトリと環境（None なら呼び出し側のもの）
    still_mine  still_mine() -> bool。子を起こすたびに聞き、偽なら（起こし直された）その子を止めて返る。None なら聞かない

    返り値: {"ok", "why", "session_id", "superseded", "accepted", "runs": [要約…], "rejections": [理由…]}
    """
    with open(prompt_file, "rb") as fh:
        stdin = fh.read()
    got = {"ok": False, "why": None, "session_id": None, "superseded": False, "accepted": None, "runs": [], "rejections": []}
    cur = list(argv)
    for turn in range(max_resumes + 1):
        started = time.time()
        try:
            rc, out, err = _spawn(cur, stdin, cwd=cwd, env=env, pgid_file=pgid_path(out_path), still_mine=still_mine)
        except OSError as e:
            rc, out, err = None, b"", str(e).encode("utf-8")
        except Superseded:
            got.update(superseded=True, why=SUPERSEDED)
            break
        text, summary, bad = unwrap(out)
        if summary.get("session_id"):
            got["session_id"] = summary["session_id"]
        run = {"turn": turn + 1, "kind": "first" if turn == 0 else "resume", "exit": rc,
               "wall_s": round(time.time() - started, 1), **summary,
               "stderr": err.decode("utf-8", "replace").strip()[-600:]}
        if bad or rc not in (0, None):
            # 受け付けに回らなかった回（解けなかった・子が exit 0 以外で終わった）は、何が返ったかを後から読めるように
            # 標準出力の頭を残す。包みでない出力が exit 0 以外と重なる回は、ここにしか残らない（out_path に書かず why にも載らない）
            run["stdout_head"] = out.decode("utf-8", "replace").strip()[:600]
        stop = True
        if rc is None:
            got["why"] = f"起こせない: {run['stderr']}"
        elif bad or rc != 0:
            got["why"] = bad or f"子が exit {rc} で終わった"
        else:
            pathlib.Path(out_path).parent.mkdir(parents=True, exist_ok=True)
            pathlib.Path(out_path).write_text(text, encoding="utf-8")
            run["bytes"] = len(text.encode("utf-8"))
            try:
                reason = accept(text) if accept else None
            except (Exception, SystemExit) as e:  # 役のせいでない失敗——続きを頼んでも直らない
                reason, got["why"] = None, f"受け付けの検査が落ちた（{type(e).__name__}: {e}）"
            else:
                if reason is None:
                    got.update(ok=True, why=None, accepted=True)
                else:
                    got["rejections"].append(reason)
                    got.update(accepted=False, why=f"受け付けが拒んだ: {reason}")
                    stop = False
            run["accepted"] = got["accepted"]
        run["why"] = got["why"]
        got["runs"].append(run)
        if log_path:
            with open(log_path, "a", encoding="utf-8") as f:
                f.write(json.dumps({"t": datetime.datetime.now().astimezone().isoformat(timespec="seconds"),
                                    "op": "role_run", **(meta or {}), **run}, ensure_ascii=False) + "\n")
        # 続きを頼むのは「役が返したが拒まれた」ときだけ。起動の失敗・受け付けの検査の失敗は、
        # 同じ会話に頼んでも直らない（続ける会話が無いか、役のせいでない）
        if stop or not (resume_argv and got["session_id"]) or turn == max_resumes:
            break
        cur = [a.replace("{session_id}", got["session_id"]) for a in resume_argv]
        stdin = RESUME_NOTE.format(why=got["rejections"][-1]).encode("utf-8")
    return got
