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
import signal
import subprocess
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


def pgid_path(out_path):
    """試行の子のグループの番号の印の置き場（<out_path>.pgid）。書く run_role と、読んで止める relaunch が同じここを引く"""
    return str(out_path) + ".pgid"


def _kill(p):
    """子を**木ごと**止める。前置の層（with-auth.py）は claude を subprocess.run で起こす殻なので、直下の子だけを
    殺すと孫の claude が out の fd を継いだまま走り続ける（Python 公式: run の timeout は直下の子だけを kill する。
    同じ形の事故の先例と解き方はリポジトリの tests/mutate.py の run_group）。

    POSIX はプロセスグループに STOP_SIGNALS を順に、猶予（KILL_GRACE）を挟んで送る（coreutils の timeout -k と同じ形。
    stop_group も同じ列を送る）。SIGTERM を先に送るのは、claude -p が SIGTERM で自分の子（Bash の木）を止めて終わるため。
    Windows はグループへの信号が無いので taskkill /T /F。"""
    try:
        if os.name == "posix":
            for sig in STOP_SIGNALS:
                os.killpg(p.pid, sig)
                try:
                    p.wait(KILL_GRACE)
                    return
                except subprocess.TimeoutExpired:
                    continue
        else:
            subprocess.run(["taskkill", "/T", "/F", "/PID", str(p.pid)], capture_output=True)
    except OSError:
        pass  # 既に居ない（ProcessLookupError は OSError の派生）
    try:
        p.wait(KILL_GRACE)
    except subprocess.TimeoutExpired:
        pass


def run_tree(argv, *, cwd, timeout, shell=False):
    """1 回走らせて終わりを待つ（rules がテストの実行器を走らせる口。INJECT で渡る）。返すのは subprocess.CompletedProcess
    （stdout・stderr は UTF-8 の文字列、読めない字は置き換え）。**時間切れなら木ごと止めて**（_kill）から TimeoutExpired を上げる
    ——subprocess.run の timeout は直下の子（シェル・実行器）だけを止め、その子や孫が作業ツリーに書き続ける。
    標準入力は閉じる（対話を待つ実行器が loop.py の標準入力を継いで止まらないように）"""
    kw = ({"start_new_session": True} if os.name == "posix"
          else {"creationflags": getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)})
    p = subprocess.Popen(argv, cwd=cwd, shell=shell, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                         text=True, encoding="utf-8", errors="replace", **kw)
    try:
        out, err = p.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        _kill(p)
        raise
    except BaseException:
        _kill(p)
        raise
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
    # 新しいプロセスグループで起こす——木ごと止めるため（_kill・stop_group）
    kw = ({"start_new_session": True} if os.name == "posix"
          else {"creationflags": getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)})
    p = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, cwd=cwd, env=env, **kw)
    with _LIVE_LOCK:
        LIVE.add(p)
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
            _kill(p)
        with _LIVE_LOCK:
            LIVE.discard(p)
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
    居なかった）。確かめ方は probe_group、送る信号の列は _kill と同じ STOP_SIGNALS で、Popen を持たないのでグループの生存を
    kill(-pgid, 0) で見る。印は子が終わると launch の側が消すので、印が無ければ止める物は無い。"""
    path = pathlib.Path(pgid_file)
    pgid, why = probe_group(pgid_file)
    if why or pgid is None:
        return why
    if os.name != "posix":
        r = subprocess.run(["taskkill", "/T", "/F", "/PID", str(pgid)], capture_output=True, text=True, encoding="utf-8", errors="replace")
        if r.returncode != 0 and _started_at(pgid) != GONE:
            return f"taskkill が {pgid} を止められない（exit {r.returncode}: {(r.stdout + r.stderr).strip()[-200:]}）"
        path.unlink(missing_ok=True)
        return None

    def alive():
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
            path.unlink(missing_ok=True)
            return None
        except PermissionError as e:
            return f"グループ {pgid} に信号を送れない（{e}）"
        t = time.monotonic() + KILL_GRACE
        while time.monotonic() < t:
            if not alive():
                path.unlink(missing_ok=True)
                return None
            time.sleep(0.1)
    return f"グループ {pgid} が SIGKILL の後も残っている"


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
