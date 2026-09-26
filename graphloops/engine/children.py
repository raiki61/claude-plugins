"""盤面の印から、この run が起こした子のグループを一覧する・止める口（loop.py children）。

**引くのは盤面の置き場の下の印（role_run.pgid_path が名付ける *.pgid）だけ**——プロセスの名前やコマンド行の文字列では
探さない（同じ機械の別の run に当たる）。印は engine が launch で起こした試行の子にだけ在るので、印を持たない子（台本の
固定具・変異の実行器の腕）はここに映らない。graph が線の結果の置き場（result_to）を盤面の外に置いた run の印も拾えない。

受け付けの前の試行は relaunch・stop が止める（盤面を先に書いてから印を読む順序を守る）。この口の役目は、受け付けの後に
止め切れずに残った印（_end_attempt が書き直した印）と、launch のプロセスが先に死んで残った印を引くこと。そのため
**止める既定は、印を書いたプロセス（owner）がもう居ず、instance が受け付けの前（pending）でもない印だけ**——いま走って
いる試行（owner が生きている）・owner を持たない古い印・pending の instance の印は、明示の旗（include_running）を付けたとき
だけ止める。別の回す側が動いている盤面を誤って止めないため。

一覧は信号を送らないが、止める物が無いと確かめた印（番号が全部再利用されていた・Windows で長が居ない）は消す
（relaunch の確かめと同じ読み、role_run._probe）。Windows は木の仲間を数える口が無いので、長が居るかだけを返し、
長が終わった後の木の残りは止められない（taskkill /T は親子の鎖で辿る）。
"""
import json
import os
import pathlib

from . import role_run
from .commands import attempt_marks, resolve_dir
from .util import Reject, dump, now, read_json

RUNNING = "running"        # 印を書いたプロセス（launch）が生きている——いま走っている試行
LEFT = "left"              # owner がもう居ない——止め残し（受け付けの後の残り・launch が先に死んだ残り）
UNKNOWN = "owner_unknown"  # owner を確かめられない（古い engine の印・開始時刻が読めない）——走っている側に倒す


def marks(board_dir):
    """盤面の置き場の下の印の全部（盤面の外は見ない）"""
    return sorted(pathlib.Path(board_dir).rglob("*" + role_run.pgid_path("")))


def _instances(board_dir):
    """印の置き場 → (周, instance の id, status)。印の置き場の正本は commands.attempt_marks（今と前の試行）と、背景の線の
    置き場（commands.launch_one が result_path + ".tmp" に書かせる）"""
    path = pathlib.Path(board_dir) / "state.json"
    if not path.is_file():
        return {}
    try:
        state = read_json(path)
    except SystemExit:   # 読めない盤面でも印の一覧と止める口は使える（instance を名指さないだけ）
        return {}
    found = {}
    for rd in state.get("rounds") or []:
        for inst in (rd.get("instances") or {}).values():
            launch = inst.get("launch") or {}
            paths = attempt_marks(inst) if inst.get("out_path") else []
            if launch.get("background") and launch.get("result_path"):
                paths.append(role_run.pgid_path(launch["result_path"] + ".tmp"))
            for m in paths:
                found[os.path.realpath(m)] = (rd.get("round"), inst.get("id"), inst.get("status"))
    return found


def _owner_state(owner, written):
    if owner is None:
        return UNKNOWN
    started = role_run._started_at(owner)
    if started is None:
        return UNKNOWN
    if started == role_run.GONE or role_run.number_reused(started, written):
        return LEFT
    return RUNNING


def survey(board_dir):
    """印ごとに 1 行: 盤面相対の置き場・周と instance・状態（running / left / owner_unknown / unreadable / gone）・owner・
    木ごとの生きた仲間（POSIX。Windows は長が居るかだけ）。信号は送らない"""
    d = pathlib.Path(board_dir)
    insts = _instances(d)
    rows = []
    for m in marks(d):
        rnd, iid, status = insts.get(os.path.realpath(m), (None, None, None))
        row = {"mark": str(m.relative_to(d)), "round": rnd, "instance": iid, "instance_status": status}
        trees, owner, written, why = role_run.read_mark(m)
        if why:
            rows.append({**row, "state": "unreadable", "why": why})
            continue
        row.update(owner=owner, state=_owner_state(owner, written))
        keep, why = role_run._probe(m)
        if why:
            row["why"] = why
        elif not keep:
            row["state"] = "gone"   # 止める物が無い（_probe が印を消した）
        row["trees"] = [_tree_row(pgid, born) for pgid, born in keep]
        rows.append(row)
    return rows


def _tree_row(pgid, born):
    if os.name != "posix":
        return {"pgid": pgid, "leader_alive": role_run._started_at(pgid) not in (None, role_run.GONE)}
    members, why = role_run._tree_members(pgid, born=born)
    live = role_run._live(members or {})
    return {"pgid": pgid, "live": [{"pid": x.pid, "pgid": x.pgid, "stat": x.stat} for x in live.values()],
            **({"why": why} if why else {})}


def stop(board_dir, reason, include_running=False):
    """印の子を木ごと止める（role_run.stop_group——数え上げ→送る→数え直し・番号の再利用を born で見分ける・ゾンビだけの
    グループ）。既定は止め残し（left で instance が pending でない）だけで、ほかは include_running のときだけ止める。
    止めた事実は盤面の trace.jsonl に op=children_stop の 1 行で残す。返すのは survey の行に結果（stopped / skipped / left）を足した物"""
    if not (reason or "").strip():
        raise Reject("止める理由が空——--reason に、なぜ止めるかを書け（盤面の trace に残る）")
    rows = survey(board_dir)
    for row in rows:
        if row["state"] in ("gone", "unreadable") or row.get("why"):
            row["result"] = "skipped"
            continue
        if (row["state"] != LEFT or row["instance_status"] == "pending") and not include_running:
            row.update(result="skipped", skip_why=f"{row['state']}・instance {row['instance_status']} の印は --include-running のときだけ止める"
                                                  "（受け付けの前の試行は relaunch・stop の持ち分——盤面を先に書いてから止める）")
            continue
        why = role_run.stop_group(pathlib.Path(board_dir) / row["mark"])
        row.update(result="left" if why else "stopped", **({"stop_why": why} if why else {}))
    with open(pathlib.Path(board_dir) / "trace.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps({"t": now(), "op": "children_stop", "reason": reason, "include_running": include_running,
                            "rows": [{k: r.get(k) for k in ("mark", "instance", "state", "result", "stop_why")} for r in rows]},
                           ensure_ascii=False) + "\n")
    return rows


def cmd_children(a):
    """loop.py children: 一覧（既定・信号なし）か、--stop --reason で止める。止め切れなかった印があれば exit 1"""
    d = resolve_dir(a)
    if not a.stop:
        if a.include_running or a.reason:
            raise Reject("--include-running と --reason は --stop と一緒にだけ使う")
        print(dump({"children": survey(d)}))
        return
    rows = stop(d, a.reason, a.include_running)
    print(dump({"children": rows}))
    left = [r["mark"] for r in rows if r.get("result") == "left"]
    if left:
        raise Reject(f"止め切れない印が {len(left)} 個ある（{left[:3]}）——印は残した。理由は各行の stop_why")
