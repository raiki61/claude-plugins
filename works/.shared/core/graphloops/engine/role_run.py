"""役を起こす関数——節 1 つ分を、子プロセスの起動から受け付けまで 1 回の呼び出しで完結させる。

**盤面（Board）も graph も import しない。** 受け取るのは起こす語（argv）・材料のファイル・返答の置き場・期限・
受け付けの検査（呼び出し側が渡す関数）・要約の書き先だけで、どれも値かファイルのパスである。今の engine
（commands.cmd_launch）も、将来の実行の核（例えば LangGraph の節）も、同じこの関数を呼ぶ——核を載せ替えても
役の起こし方・待ち方・続きの頼み方・要約の残し方を写し直さないため（docs の作り直しの設計「手順 1」）。

流れ:
  1. argv を子プロセスで起こし、材料を標準入力で渡す（貼る上限に当たらない）。
  2. **子の終了を直接待つ。** 完了の知らせ（通知・中継の AI の『書いた』）には頼らない——知らせは入れ子や上限落ちで
     消えた（実測 2026-09-24〜25: 局所レビューの入れ子の起動で知らせが届かず 7 時間止まった）。期限を過ぎたら
     子をプロセスグループごと止め、期限切れとして返す（前置の層 with-auth.py が子の claude を孫として起こすので、
     層だけを止めると claude が孤児で走り続ける）。
  3. 標準出力が `--output-format json` の包み（result・session_id・num_turns・duration_ms・total_cost_usd・usage）なら
     解いて返答の本文だけを、包みでなければ標準出力の全文を本文として out_path に書く（unwrap）。要約は log_path
     （engine は盤面の trace.jsonl）に JSON Lines で 1 起動 1 行残す。
  4. accept(本文) で受け付けを検査する。拒まれたら、理由を添えて**同じ会話**に続きを頼む（resume_argv の
     {session_id} を埋めて起こし、理由の文を標準入力で渡す）。新しい会話で起こし直すと、役は前の返答を
     覚えておらず、同じ判定を出し直す保証が無い。

返り値は呼び出し側が盤面に写す値だけ（本文は含めない——回す側の会話に役の返答を流し込まないため）。
"""
import datetime
import json
import os
import pathlib
import signal
import subprocess
import threading
import time

RESUME_NOTE = ("受け付けの検査がこの返答を拒んだ。理由:\n{why}\n\n"
               "理由が返答の形（JSON として読めない・型に合わない）なら、判定も中身も変えずに形だけ直せ。"
               "理由が中身の整合（記録の整合・項目の過不足など）なら、理由が指す所だけを直せ。"
               "どちらも、最初の指示が求めた形の返答だけを出し直せ（前後に文を付けない）。")
KILL_GRACE = 5  # SIGTERM から SIGKILL までの猶予（秒）
# engine の中から起こす子に持たせない道具（ファイルを書く道具）。道具つきの役の**能力の上限**——道具ゼロの役が
# 「何も実行できない」と言えるのと同じく、engine が起こす子は「ファイルを書く道具を持たない」と言える形にする。
# 役の定義にこれが在れば engine は起こさない（回す側が Agent で起こす）。値は graph でなく engine が持つ——graph の書き換えで
# 起こせる物が広がらないように（commands.launch_refusal の注記）
WRITE_TOOLS = ("Write", "Edit", "MultiEdit", "NotebookEdit")
# コマンドを走らせる道具。これを持つ役は分類器（auto）に掛け、先に許す一覧（--allowedTools）から外す
COMMAND_TOOLS = ("Bash",)
LIVE = set()  # いま生きている子（Popen）。launch のプロセスが止められたとき kill_all が木ごと止める
_LIVE_LOCK = threading.Lock()


def tooled_permission(tools):
    """道具つきの役の権限の形 (permission_mode, allowed_tools)。**起こす側（launch_spec）と柵（launch_refusal）が同じここを引く**。

    -p の開始の権限は起こした側の設定を継ぐ（回す側が bypassPermissions なら子も）ので、必ず明示する。
    既定は先に許した道具だけが通る dontAsk（Read・Glob・Grep は許さなくても通り、WebFetch・WebSearch は許さないと拒まれる。
    実測 2026-09-25・haiku）。コマンドを走らせる道具を持つ役は auto にして、その道具を先に許す一覧から外し、分類器に掛ける
    （実測 2026-09-25・haiku: auto と --permission-prompts none で git log は通り、touch・gh issue list・curl -X POST は拒まれた）。"""
    if any(t in COMMAND_TOOLS for t in tools):
        return "auto", [t for t in tools if t not in COMMAND_TOOLS]
    return "dontAsk", list(tools)


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
    """生きている子を全部木ごと止める（launch のプロセスが SIGTERM・SIGHUP・SIGINT を受けたとき）。"""
    with _LIVE_LOCK:
        live = list(LIVE)
    for p in live:
        _kill(p)
# 包みの欄のうち要約に残すもの（--output-format json の result の行）。本文（result）は残さない
SUMMARY_KEYS = ("session_id", "num_turns", "duration_ms", "duration_api_ms", "total_cost_usd", "usage",
                "subtype", "is_error", "stop_reason")
# 権限で拒まれた道具の呼び出し。件数と道具の名前だけ残す——auto が使えない場では黙って聞く形に落ち、聞く先が無いので
# 全部拒まれたまま exit 0 で返る（公式の permission-modes 文書）。効いた権限は包みに無いので、拒まれた数で見えるようにする


def _kill(p):
    """子を**木ごと**止める。前置の層（with-auth.py）は claude を subprocess.run で起こす殻なので、直下の子だけを
    殺すと孫の claude が out の fd を継いだまま走り続ける（Python 公式: run の timeout は直下の子だけを kill する。
    同じ形の事故の先例と解き方はリポジトリの tests/mutate.py の run_group）。

    POSIX はプロセスグループに SIGTERM → 猶予の後に SIGKILL（coreutils の timeout -k と同じ形）。SIGTERM を先に送るのは、
    claude -p が SIGTERM で自分の子（Bash の木）を止めて終わるため。Windows はグループへの信号が無いので taskkill /T /F。

    **止めたと数えるのはグループが空になった時**（systemd の KillMode=control-group と同じ）。直下の子の終了で数えていたとき、
    SIGTERM をすぐに処理しない孫が残ったまま戻り、SIGKILL も送らなかった（実測: CI の ubuntu で負荷の高い回に孫が生きて見えた）。
    猶予は SIGTERM から数えて KILL_GRACE の 1 つだけ。刈り取る親の居ない環境の孤児のゾンビも kill(2) の sig 0 には
    『在る』ので、その環境ではこの猶予を使い切ってから戻る（有限）。"""
    try:
        if os.name == "posix":
            os.killpg(p.pid, signal.SIGTERM)
            end = time.monotonic() + KILL_GRACE
            try:
                p.wait(KILL_GRACE)
                while _group_alive(p.pid) and time.monotonic() < end:
                    time.sleep(0.05)
            except subprocess.TimeoutExpired:
                pass
            if not _group_alive(p.pid):
                return
            os.killpg(p.pid, signal.SIGKILL)
        else:
            subprocess.run(["taskkill", "/T", "/F", "/PID", str(p.pid)], capture_output=True)
    except OSError:
        pass  # 既に居ない（ProcessLookupError は OSError の派生）
    try:
        p.wait(KILL_GRACE)
    except subprocess.TimeoutExpired:
        pass


def _group_alive(pgid):
    """プロセスグループにまだ誰か居るか（kill(2) の sig 0）。信号を送る権限が無いだけの回も『居る』と数える"""
    try:
        os.killpg(pgid, 0)
    except ProcessLookupError:
        return False
    except OSError:
        return True
    return True


def _spawn(argv, stdin_bytes, timeout_s, cwd=None, env=None):
    """1 回起こして終了を待つ。返すのは (exit, stdout, stderr, expired)。timeout_s が None なら期限なしで待つ。

    **どの道で抜けても子を残さない**（finally）——期限切れだけでなく、待っている間に例外・SystemExit・
    KeyboardInterrupt で抜けた回も木ごと止める。子は別のプロセスグループに切り離してあるので、親のグループに
    届く信号はもう子に届かない。"""
    # 新しいプロセスグループで起こす——期限で木ごと止めるため（_kill）
    kw = ({"start_new_session": True} if os.name == "posix"
          else {"creationflags": getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)})
    p = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, cwd=cwd, env=env, **kw)
    with _LIVE_LOCK:
        LIVE.add(p)
    ended = False
    try:
        try:
            out, err = p.communicate(stdin_bytes, timeout=None if timeout_s is None else max(0.1, timeout_s))
            ended = True
            return p.returncode, out, err, False
        except subprocess.TimeoutExpired:
            _kill(p)
            ended = True
            try:
                out, err = p.communicate(timeout=KILL_GRACE)
            except (subprocess.TimeoutExpired, ValueError, OSError):
                out, err = b"", b""
            return None, out or b"", err or b"", True
    finally:
        if not ended:
            _kill(p)
        with _LIVE_LOCK:
            LIVE.discard(p)


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


def run_role(argv, prompt_file, out_path, *, timeout_s, accept=None, resume_argv=None, max_resumes=0,
             log_path=None, meta=None, cwd=None, env=None):
    """役を起こし、返答を out_path に書き、受け付けまで済ませる。

    argv        起こす語の全部（前置の層・claude・旗）。同じ会話を続ける節ならここが既に --resume を含む
    prompt_file 指示書（標準入力で渡す）
    out_path    返答の本文の置き場
    timeout_s   期限までの秒（続きを頼む往復も含めた全体の上限）。None なら期限なし（背景の線——期限で止めない節）
    accept      accept(本文) -> None（受け付けた）| str（拒んだ理由——役に返して出し直させる）。
                役のせいでない失敗（盤面が読めない等）は例外で投げよ——続きを頼まずに止まり、why に載る
    resume_argv 拒まれたときに同じ会話を続ける語。'{session_id}' の語を会話の番号で埋める。None なら続けない
    max_resumes 続きを頼む回数の上限
    log_path    実行の要約を JSON Lines で足す先（1 起動 1 行・op は role_run。engine は盤面の trace.jsonl を渡す）
    meta        要約の各行に添える値（instance・周など。呼び出し側の語彙で、この関数は読まない）
    cwd / env   子の作業ディレクトリと環境（None なら呼び出し側のもの）

    返り値: {"ok", "why", "session_id", "expired", "accepted", "runs": [要約…], "rejections": [理由…]}
    """
    deadline = None if timeout_s is None else time.monotonic() + timeout_s
    with open(prompt_file, "rb") as fh:
        stdin = fh.read()
    got = {"ok": False, "why": None, "session_id": None, "expired": False, "accepted": None, "runs": [], "rejections": []}
    cur = list(argv)
    for turn in range(max_resumes + 1):
        started = time.time()
        try:
            rc, out, err, expired = _spawn(cur, stdin, None if deadline is None else deadline - time.monotonic(), cwd=cwd, env=env)
        except OSError as e:
            rc, out, err, expired = None, b"", str(e).encode("utf-8"), False
        text, summary, bad = (None, {}, None) if expired else unwrap(out)
        if summary.get("session_id"):
            got["session_id"] = summary["session_id"]
        run = {"turn": turn + 1, "kind": "first" if turn == 0 else "resume", "exit": rc, "expired": expired,
               "wall_s": round(time.time() - started, 1), **summary,
               "stderr": err.decode("utf-8", "replace").strip()[-600:]}
        if bad or rc not in (0, None):
            # 受け付けに回らなかった回（解けなかった・子が exit 0 以外で終わった）は、何が返ったかを後から読めるように
            # 標準出力の頭を残す。包みでない出力が exit 0 以外と重なる回は、ここにしか残らない（out_path に書かず why にも載らない）
            run["stdout_head"] = out.decode("utf-8", "replace").strip()[:600]
        stop = True
        if expired:
            got.update(expired=True, why=f"期限（{timeout_s:.0f} 秒）を過ぎたので子を木ごと止めた")
        elif rc is None:
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
        # 続きを頼むのは「役が返したが拒まれた」ときだけ。期限切れ・起動の失敗・受け付けの検査の失敗は、
        # 同じ会話に頼んでも直らない（続ける会話が無いか、役のせいでない）
        if stop or not (resume_argv and got["session_id"]) or turn == max_resumes or (deadline is not None and time.monotonic() >= deadline):
            break
        cur = [a.replace("{session_id}", got["session_id"]) for a in resume_argv]
        stdin = RESUME_NOTE.format(why=got["rejections"][-1]).encode("utf-8")
    return got
