"""loop.py run——回す側の LLM の代わりに、run を回し続けるプログラム（手順 H1）。

**薄い外側の層。** 回し手は engine の中身を呼ばず、今の CLI（loop.py next・launch・done・relaunch）を子として打ち、盤面
（state.json）を読むだけで止まり所を決める。外側を別の実行の仕組みに差し替えるときは、このモジュールごと捨てられる。
engine が持つ受け付け・起こし方・柵はここに写さない。

2 つの役に分かれる:
- **回し手**（`loop.py run --foreground`）: 盤面の置き場の run.lock を待たずに取れた 1 本だけがなる。next を打ち、engine が起こせる
  節があれば `loop.py launch`（その波をまとめて 1 本。同時に起こす本数の上限は launch が持つ）を子として立てて終わりを待ち、
  また next を打つ。起こせる物が尽き、自分の子が全部終わったら抜ける。止める信号を受けたら、起こし済みの子の終わりを待ち、
  新しい子を起こさずに 128+n で抜ける（一時停止。盤面から run か next で続けられる）
- **見守り**（`loop.py run`）: 会話が前景で打つ。錠が空いていれば回し手を切り離して立て、空いていなければ付き添う。会話に返す節が
  出たら回し手が走っていてもすぐ戻り、回し手が居なくなったら盤面から止まった種類を決めて戻り、上限（WATCH_LIMIT_S）に
  達したら『まだ回っている』で戻る。回し手と子は止めない

止まった種類は盤面だけから決める（classify）。回し手の要約ファイル（runner.json）は回し手の pid・起動時刻と、最後に抜けた
理由の補足（detail）しか持たない——前の回し手の結果を読んで戻る競りを作らない。背景の線（delegate.background）は回し手が
立てず、会話に返す（受領の done と背景の launch は今の手順書どおり会話がする）。
"""
import json
import os
import pathlib
import signal
import subprocess
import sys
import time

from . import filelock
from .role_run import pgid_path, probe_group
from .util import Reject, now, waiting

LOOP = pathlib.Path(__file__).resolve().parent.parent / "scripts" / "loop.py"
WATCH_LIMIT_S = 540   # 見守りが会話へ戻る上限（人の決定 2026-09-25 ①）。回し手と子は止めない
POLL_S = 1.0          # 盤面と子を見に行く間隔
RUN_LOCK = "run.lock"
RUNNER_JSON = "runner.json"
RUN_LOG = "run.log"
MARKS = "runner-launch"   # 回し手が立てた launch の子の印（role_run の .pgid と同じ形に ids を足す）
TERMINAL = ("converged", "stopped")
# run だけが返す終了コード（人の決定 2026-09-25 ④）。今の 0/1/2 の意味は run 以外で変えない
CODES = {"done": 0, "awaiting_human": 10, "round_limit": 11, "stuck": 12, "handoff": 13, "needs_human": 14, "still_running": 20}
# 日常の流れで返る値——入口（loop.py）が踏んだ問題として利用者の環境に残さない
QUIET_CODES = frozenset({10, 11, 13, 20})
HOW = {
    "done": "run は終わった（status・halted・stop_reason を見よ）。報告の節が書いた本文は盤面の report.md",
    "awaiting_human": "ask を人に見せ（手順書の『聞き方』）、答えを loop.py answer で返してから run を打ち直せ",
    "round_limit": "init --stop-after-round の周で止めた。続けるなら loop.py resume --reason <理由> --stop-after-round <N>",
    "stuck": "detail を読め——直してから run を打ち直す（作業ツリーの突合なら next --accept-tree-change、回し手の信号なら打ち直すだけ）",
    "handoff": "handoff の節を手順書どおりにこなし（背景の線は受領を done してから launch --node を背景で立て、待たない）、done してから run を打ち直せ。回し手は起こせる節を回し続けている",
    "needs_human": "needs_human を人に見せよ（起こし直すなら loop.py relaunch、置き場の返答を受け付けるなら done、起こせない役は人に渡す）",
    "still_running": "回し手が回している。何もせずに run を打ち直せ",
}


# ---------------------------------------------------------------- 盤面を読む（書かない）
def read_state(d):
    return json.loads((pathlib.Path(d) / "state.json").read_text(encoding="utf-8"))


def _read_json(p, default):
    try:
        return json.loads(pathlib.Path(p).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def classify(st):
    """盤面から止まった種類と、その材料を組む ——{kind, handoff, needs_human, launchable, running}。
    kind が busy なら止まる所ではない（起こせる節か走っている節が在る）。材料は汎用の印だけ（節の名前・段を持たない）"""
    rd = st["rounds"][-1]
    pending = [i for i in rd["instances"].values() if i.get("status") == "pending"]
    launch = lambda i: i.get("launch") or {}   # noqa: E731
    handoff = [i for i in pending if not i.get("launch") or launch(i).get("background")]
    launchable = [i for i in pending if i.get("launch") and not launch(i).get("background") and not i.get("launched_at")]
    running = [i for i in pending if i.get("launch") and i.get("launch_state") == "running"]
    # 起こして終わったのに受け付けていない試行（柵の拒否・子が落ちた・拒否が上限まで続いた・盤面の競りで書けなかった）
    needs = [{"id": i["id"], "why": ((i.get("attempt_log") or [{}])[-1]).get("reason") or "起こしたが受け付けていない"}
             for i in pending if i.get("launch") and i.get("launch_state") == "ended"]
    halted = st.get("halted") or {}
    if st.get("pending_human"):
        kind = "awaiting_human"
    elif halted.get("by") == "stop_after_round":
        kind = "round_limit"
    elif halted.get("by") == "unattended":
        kind = "needs_human"
        needs.append({"id": halted.get("node"), "why": f"無人の run が人に聞く所で止めた（{halted.get('reason')}）"})
    elif halted:
        kind = "done"
    elif handoff:
        kind = "handoff"
    elif needs:
        kind = "needs_human"
    elif launchable or running:
        kind = "busy"
    elif st.get("status") in TERMINAL:
        kind = "done"
    else:
        kind = "stuck"
    return {"kind": kind, "handoff": handoff, "needs_human": needs, "launchable": launchable, "running": running}


def _group_alive(mark):
    """印（{pgid} の JSON）の子のグループが生きているか。True・False、確かめられなければ None"""
    pgid, why = probe_group(mark)
    if why:
        return None
    if pgid is None:
        return False
    if os.name != "posix":
        return True
    try:
        os.killpg(pgid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def _runner_alive(d):
    h = filelock.try_hold(pathlib.Path(d) / RUN_LOCK)
    if h is None:
        return True
    filelock.release(h)
    return False


def _trace(d, event, **kw):
    with open(pathlib.Path(d) / "trace.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps({"t": now(), "op": "run", "event": event, "pid": os.getpid(), **kw}, ensure_ascii=False) + "\n")


def _detached():
    """子を呼んだ側の端末・プロセスグループから切り離す引数（信号が子へ届かない）"""
    if os.name == "posix":
        return {"start_new_session": True}
    return {"creationflags": getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)}


def _cli(d, *args):
    """loop.py <args> --dir d を子として打ち、終わりを待つ（上限なし）——(exit, stdout, stderr)"""
    r = subprocess.run([sys.executable, str(LOOP), *args, "--dir", str(d)], capture_output=True, text=True, encoding="utf-8",
                       errors="replace", stdin=subprocess.DEVNULL, **_detached())
    return r.returncode, r.stdout, r.stderr


# ---------------------------------------------------------------- 回し手
class _Runner:
    def __init__(self, d):
        self.d = pathlib.Path(d)
        self.marks = self.d / MARKS
        self.child = None        # (Popen, ids, 印のパス)
        self.signum = None
        self.recovered = set()   # この回し手が一度起こし直した instance（同じ物が 2 度落ちたら人に渡す）
        self.detail = None
        self.attempts = {}       # 立てた launch に渡した試行の番号（launch の後も同じ番号のまま印が無ければ、起こしていない）

    def on_signal(self, signum, _frame):
        self.signum = signum   # 起こし済みの子は待つ。新しい子は起こさない

    def spawn_launch(self, insts):
        ids = [i["id"] for i in insts]
        self.attempts = {i["id"]: i.get("attempts", 1) for i in insts}
        self.marks.mkdir(exist_ok=True)
        with open(self.d / RUN_LOG, "ab") as log:
            p = subprocess.Popen([sys.executable, str(LOOP), "launch", "--dir", str(self.d)], stdin=subprocess.DEVNULL,
                                 stdout=log, stderr=log, **_detached())
        mark = self.marks / f"{p.pid}.json"
        mark.write_text(json.dumps({"pgid": p.pid, "ids": ids}), encoding="utf-8")   # 形は role_run.probe_group が読む印と同じ
        self.child = (p, ids, mark)
        _trace(self.d, "launch", child=p.pid, ids=ids)

    def orphans(self, ids):
        """ids のうち、起こした launch が居なくなったのに running のまま残った試行（launch が締めの前に落ちた）"""
        insts = read_state(self.d)["rounds"][-1]["instances"]
        return [insts[i] for i in ids if i in insts and insts[i].get("status") == "pending" and insts[i].get("launch_state") == "running"]

    def recover(self, inst):
        """落ちた launch の試行を拾い直す: 置き場に返答が在れば受け付け、無ければ起こし直す（次の next の後に起こす）。
        同じ試行が 2 度落ちたら拾わず人に渡す。返すのは拾えなかった理由（拾えたら None）"""
        iid = inst["id"]
        if iid in self.recovered:
            return f"'{iid}' は回し手が起こし直した後も launch が締めの前に落ちた"
        self.recovered.add(iid)
        out = pathlib.Path(inst.get("out_path") or "")
        if inst.get("mode") != "engine_run" and out.is_file() and out.stat().st_size:
            rc, _o, _e = _cli(self.d, "done", "--node", iid)
            _trace(self.d, "recover", instance=iid, how="done", exit=rc)
            if rc == 0:
                return None
        rc, _o, err = _cli(self.d, "relaunch", "--node", iid, "--reason", "回し手が起こした launch が受け付けの前に落ちた（loop.py run が拾い直す）")
        _trace(self.d, "recover", instance=iid, how="relaunch", exit=rc)
        return None if rc == 0 else f"'{iid}' を起こし直せない（relaunch exit {rc}: {err.strip()[-400:]}）"

    def settle_child(self):
        """終わった launch の後始末。launch が 1 つも起こさずに終わった（起こした印が付かない）なら偽——起こし直しの輪を回さない"""
        p, ids, mark = self.child
        self.child = None
        mark.unlink(missing_ok=True)
        _trace(self.d, "launched", child=p.pid, exit=p.returncode, ids=ids)
        insts = read_state(self.d)["rounds"][-1]["instances"]
        unmarked = [i for i in ids if (insts.get(i) or {}).get("status") == "pending" and not insts[i].get("launched_at")
                    and insts[i].get("attempts", 1) == self.attempts.get(i)]
        if unmarked and len(unmarked) == len(ids):
            self.detail = f"loop.py launch が節を起こさずに終わった（exit {p.returncode}。{unmarked}。出力は run.log）"
            return False
        for inst in self.orphans(ids):
            why = self.recover(inst)
            if why:
                self.detail = why
        return True

    def inherited(self):
        """前の回し手が立てた launch の印——生きている物は待ち、居なくなった物はその試行を拾い直す。待つ物が在れば True"""
        if not self.marks.is_dir():
            return False
        wait = False
        for mark in sorted(self.marks.glob("*.json")):
            if self.child and mark == self.child[2]:
                continue
            alive = _group_alive(mark)
            if alive is not False:
                wait = True   # 生きている（か確かめられない）——止めずに待つ
                continue
            ids = _read_json(mark, {}).get("ids") or []
            mark.unlink(missing_ok=True)
            for inst in self.orphans(ids):
                why = self.recover(inst)
                if why:
                    self.detail = why
        return wait

    def others_running(self, c):
        """回し手の印を持たない running の試行（会話が打った launch）。起こした子の印（.pgid）が生きていれば待つ。
        印が無ければ、読み直してもまだ running のときだけ人に渡す（続きの往復の合間は印が無い）——(待つか, 人に渡す理由)"""
        mine = set(self.child[1]) if self.child else set()
        for mark in self.marks.glob("*.json") if self.marks.is_dir() else ():
            mine |= set(_read_json(mark, {}).get("ids") or [])
        wait, whys = False, []
        for inst in c["running"]:
            if inst["id"] in mine:
                continue
            if _group_alive(pgid_path(inst["out_path"])) is not False:
                wait = True
                continue
            cur = read_state(self.d)["rounds"][-1]["instances"].get(inst["id"]) or {}
            if cur.get("status") == "pending" and cur.get("launch_state") == "running" and cur.get("out_path") == inst["out_path"] \
                    and _group_alive(pgid_path(inst["out_path"])) is False:
                whys.append(f"'{inst['id']}' は回し手の外で起こした launch が running のまま、子が見当たらない"
                            "——起こした launch が生きていれば待ち、居なければ relaunch")
        return wait, whys

    def drive(self):
        """回し手の本体。返すのは止まった種類（信号なら signal）"""
        while True:
            if self.child:
                if self.child[0].poll() is None:
                    time.sleep(POLL_S)
                    continue
                if not self.settle_child():
                    return "stuck"
                continue
            if self.inherited():
                time.sleep(POLL_S)
                continue
            if self.signum:
                return "signal"
            rc, _out, err = _cli(self.d, "next")
            if rc != 0:
                self.detail = f"loop.py next が exit {rc}: {err.strip()[-800:]}"
                return "stuck"
            c = classify(read_state(self.d))
            if c["launchable"]:
                self.spawn_launch(c["launchable"])
                continue
            wait, whys = self.others_running(c)
            if whys:
                self.detail = "; ".join(whys)
                return "needs_human"
            if wait:
                time.sleep(POLL_S)
                continue
            return c["kind"] if c["kind"] != "busy" else "stuck"


def run_as_runner(d):
    """run.lock を待たずに取れたら回し手として回し、止まった種類を返す。取れなければ None（別の回し手が居る）"""
    d = pathlib.Path(d)
    h = filelock.try_hold(d / RUN_LOCK)
    if h is None:
        return None
    r = _Runner(d)
    old = {s: signal.signal(s, r.on_signal) for s in (getattr(signal, n, None) for n in ("SIGTERM", "SIGINT", "SIGHUP")) if s}
    started = {"pid": os.getpid(), "started_at": now()}
    kind = "stuck"
    try:
        _write_atomic(d / RUNNER_JSON, started)
        _trace(d, "start")
        kind = r.drive()
    finally:
        last = {"kind": kind, "signal": r.signum, "detail": r.detail, "at": now(), "at_epoch": time.time()}
        _write_atomic(d / RUNNER_JSON, {**started, "last": last})
        _trace(d, "stop", kind=kind, detail=r.detail)
        for s, f in old.items():
            signal.signal(s, f)
        filelock.release(h)
    return kind, r


def _write_atomic(path, obj):
    tmp = pathlib.Path(str(path) + f".{os.getpid()}.tmp")   # 書き手ごとに一意の一時ファイル
    tmp.write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)


# ---------------------------------------------------------------- 見守り
def _spawn_runner(d):
    with open(pathlib.Path(d) / RUN_LOG, "ab") as log:
        return subprocess.Popen([sys.executable, str(LOOP), "run", "--foreground", "--dir", str(d)], stdin=subprocess.DEVNULL,
                                stdout=log, stderr=log, **_detached())


def watch(d):
    """見守りの本体——止まった種類を返す"""
    d = pathlib.Path(d)
    t0, since = time.monotonic(), time.time()
    for _ in range(3):   # 錠が空いていたのに立てた回し手が取れなかった（別の見守りが先に立てた）ときだけ、もう一度見る
        h = filelock.try_hold(d / RUN_LOCK)
        if h is None:
            break
        filelock.release(h)
        p = _spawn_runner(d)
        while _read_json(d / RUNNER_JSON, {}).get("pid") != p.pid and p.poll() is None:
            time.sleep(0.05)
        if _read_json(d / RUNNER_JSON, {}).get("pid") == p.pid:
            break
    while True:
        c = classify(read_state(d))
        if c["kind"] == "handoff":
            return "handoff", c, None
        if not _runner_alive(d):
            c = classify(read_state(d))   # 回し手が抜ける前に書いた盤面で決め直す
            last = _read_json(d / RUNNER_JSON, {}).get("last") or {}
            detail = last.get("detail") if (last.get("at_epoch") or 0) >= since else None
            kind = c["kind"]
            if kind == "busy":
                kind = "stuck"
                detail = (detail + "。" if detail else "") + ("回し手は信号で止まった（一時停止）——続けるなら run を打ち直せ" if last.get("signal")
                                                             else "回し手が居ないのに、起こせる節か走っている節が残っている——run を打ち直せ（run.log に回し手の出力）")
            return kind, c, detail
        if time.monotonic() - t0 >= WATCH_LIMIT_S:
            return "still_running", c, None
        time.sleep(POLL_S)


def report(d, kind, c, detail=None, code=None):
    """標準出力の最後の 1 行の JSON（会話が読む物）。役の返答の本文は出さない"""
    d = pathlib.Path(d)
    st = read_state(d)
    rec = _read_json(d / "record.json", {})
    info = _read_json(d / RUNNER_JSON, {})
    strip = lambda i: {k: v for k, v in i.items() if k != "tree_before"}   # noqa: E731
    out = {"stop": kind, "code": CODES.get(kind, code), "status": st.get("status"), "round": st.get("round"),
           "run_id": st.get("run_id"), "dir": str(d), "halted": st.get("halted"),
           "stop_reason": (rec.get("process") or {}).get("stop_reason") if isinstance(rec.get("process"), dict) else None,
           "ask": st.get("pending_human"), "handoff": [{**strip(i), **waiting(i)} for i in c["handoff"]],
           "needs_human": c["needs_human"], "running": [{"id": i["id"], "launched_at": i.get("launched_at"), **waiting(i)} for i in c["running"]],
           "engine": st.get("engine"), "runner": {k: info.get(k) for k in ("pid", "started_at")}, "detail": detail,
           "how": HOW.get(kind, "回し手が信号で止まった（一時停止）——続けるなら run を打ち直せ")}
    print(json.dumps(out, ensure_ascii=False))


def cmd_run(a, d):
    """loop.py run の入口。d は入口が解決した盤面の置き場"""
    if not (pathlib.Path(d) / "state.json").is_file():
        raise Reject(f"{d} に盤面（state.json）が無い——init の出力の dir を渡せ")
    if a.foreground:
        got = run_as_runner(d)
        if got is not None:
            kind, r = got
            c = classify(read_state(d))
            if kind == "signal":
                report(d, "signal", c, "回し手は信号で止まった（起こし済みの子の終わりを待った。新しい子は起こしていない）", code=128 + r.signum)
                sys.exit(128 + r.signum)
            report(d, kind, c, r.detail)
            sys.exit(CODES[kind])
    kind, c, detail = watch(d)
    report(d, kind, c, detail)
    sys.exit(CODES[kind])

