#!/usr/bin/env python3
"""StopFailure のフック（matcher は rate_limit）: 常設の会話が使用上限で止まったら、ほかのアカウントで起こし直す（37f8b1）。

Claude Code は、API の誤りで番が終わると Stop の代わりに StopFailure を走らせ、誤りの種類を error に渡す（使用上限は rate_limit）。
会話の場所が常設の部署（属性 company.residency が resident）か、本社の窓口（--desk。属性の会話 company.session がこの会話）なら、
dispatch.py --move <名前> --if-limited を、この会話から切り離して（POSIX は nodes/wake.py の detached の殻で、親を init に替えて）裏で走らせる（--move はこの会話を止めてから起こし直すので、
この会話の子として待たない）。都度の部署（作業）は移さない（頼みの区切りで畳まれ、次の頼みは空いたアカウントで立つ）。
同じ場所で 10 分の間に 2 度は走らせない（上限の後の自動の続き〔autoContinueAtUsageLimit〕で、同じ誤りが続けて来ることがある）。
走らせた出力は受付箱の moves/ に残す。何も出さず、0 で終わる（StopFailure はフックの出力を読まない）。
"""

import json
import os
import pathlib
import subprocess
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
try:
    import gitx  # noqa: E402
    from nodes import deliver, wake  # noqa: E402
except (ImportError, SyntaxError):
    sys.exit(0)

DISPATCH_PY = str(pathlib.Path(__file__).resolve().parent / "dispatch.py")
AGAIN = 600   # 同じ場所で続けて走らせない秒数
MOVES = "moves"   # 受付箱の下の、走らせた出力の置き場


def plan(payload, attrs_of=gitx.worktree_attrs):
    """走らせる命令の並びと、走らせる場所と出力の置き場の (argv, cwd, 出力のファイル)。移さないなら None。"""
    if payload.get("error") != "rate_limit":
        return None
    cwd = payload.get("cwd") or os.getcwd()
    attrs = attrs_of(cwd)
    name = attrs.get("name")
    if not (attrs.get("role") and name):
        return None
    here, common = gitx.git_dir(cwd), gitx.common_dir(cwd)
    if not here or not common:
        return None
    head = os.path.realpath(here) == os.path.realpath(common)
    if head and attrs.get("session") != payload.get("session_id"):
        return None   # 本社の、窓口でない会話
    if not head and attrs.get("residency") != "resident" and not (attrs.get("ask") and attrs.get("delivered") != attrs["ask"]):
        return None   # 都度の部署は、頼みを受けている間だけ移す（頼まれたときだけ立てる受け持ちの部署は、頼みの途中で枠が尽きうる）
    argv = [sys.executable, DISPATCH_PY, "--move", name, "--if-limited"] + (["--config", attrs["config"]] if attrs.get("config") else [])
    out = os.path.join(deliver.inbox_of(common), MOVES, f"{''.join(c for c in name if c.isalnum())}-{int(time.time())}.log")
    return argv, cwd, out


def _recent(out_dir, name, now):
    prefix = "".join(c for c in name if c.isalnum()) + "-"
    try:
        stamps = [int(n[len(prefix):-4]) for n in os.listdir(out_dir) if n.startswith(prefix) and n.endswith(".log")
                  and n[len(prefix):-4].isdigit()]
    except OSError:
        return False
    return any(now - t < AGAIN for t in stamps)


def main(stdin=sys.stdin, spawn=subprocess.Popen, now=time.time):
    try:
        payload = json.loads(stdin.read() or "{}") or {}
    except ValueError:
        return 0
    got = plan(payload) if isinstance(payload, dict) else None
    if not got:
        return 0
    argv, cwd, out = got
    out_dir = os.path.dirname(out)
    if _recent(out_dir, argv[3], int(now())):
        return 0
    os.makedirs(out_dir, exist_ok=True)
    if os.name != "nt" and spawn is subprocess.Popen:
        # 会話から切り離す（--move はこの会話を止める。会話を止めると Claude Code はフックの子孫も止め、--move が何も書かずに消えた。
        # 2026-10-17 の点検・説明書の moves/ の出力が 0 バイト。nodes/wake.py の detached）
        open(out, "w", encoding="utf-8").close()
        spawn(wake.detached([argv[0], "-u", *argv[1:]], out, out[:-len(".log")] + ".done"), cwd=cwd, stdin=subprocess.DEVNULL,
              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True).wait()
        return 0
    with open(out, "w", encoding="utf-8") as f:
        spawn(argv, cwd=cwd, stdin=subprocess.DEVNULL, stdout=f, stderr=subprocess.STDOUT, start_new_session=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
