#!/usr/bin/env python3
"""StopFailure のフック: 永続の部署の会話が使用上限で止まったら、ほかのアカウントで起動し直す（37f8b1）。

Claude Code は、API の誤りでターンが終わると Stop の代わりに StopFailure を走らせ、誤りの種類を error に渡す（使用上限は rate_limit）。
使用上限のほかの誤りでも、会話のアカウントが使える時間帯（設定の hours）の外か終わる手前なら、同じに移す（時間帯の外の要求を
提供元がどの誤りで断るかは決まっていないので、誤りの種類で絞らない。matcher は空で、誤りの種類はここで見る）。
会話の場所が永続の部署（属性 company.lifecycle が persistent）か、本社の窓口（--desk。属性の会話 company.session がこの会話）なら、
dispatch.py --move <名前> --if-limited を、この会話から切り離して（POSIX は nodes/wake.py の detached の殻で、親を init に替えて）裏で走らせる（--move はこの会話を止めてから起動し直すので、
この会話の子として待たない）。エフェメラルの部署（作業）は移さない（頼みの区切りで畳まれ、次の頼みは空いたアカウントで立つ）。
同じ場所で 10 分の間に 2 度は走らせない（上限の後の自動の続き〔autoContinueAtUsageLimit〕で、同じ誤りが続けて来ることがある）。
走らせた出力は受付箱の moves/ に残す。何も出さず、0 で終わる（StopFailure はフックの出力を読まない）。
--move は、移さないときと移る先が無いときも、待って見直し、移すか同じ会話に続きの 1 行を打つ（move.py の --if-limited。待つ最短の
move.WAIT はこの AGAIN と同じにする: 打った 1 行がまた断られたら、このフックがまた走る）。
"""

import json
import os
import pathlib
import subprocess
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
try:
    import config  # noqa: E402
    import gitx  # noqa: E402
    from nodes import accounts, deliver, provision, wake  # noqa: E402
except (ImportError, SyntaxError):
    sys.exit(0)

DISPATCH_PY = str(pathlib.Path(__file__).resolve().parent / "dispatch.py")
AGAIN = 600   # 同じ場所で続けて走らせない秒数
MOVES = "moves"   # 受付箱の下の、走らせた出力の置き場


def _attrs(cwd):
    """場所の部署の属性。git の口はこのモジュールの gitx を呼ぶ時に引く（試験は gitx を偽物に替える。tests/fakegit.wire）。"""
    return gitx.worktree_attrs(cwd)


def closed(attrs, now=time.time, env=os.environ):
    """会話のアカウント（属性 company.account）が、使える時間帯の外か終わる手前か。設定を読めなければ偽（使用上限の外の誤りでは移さない）。"""
    try:
        cfg = config.load(attrs.get("config"), env, missing_ok=True)
    except (config.ConfigError, OSError, ValueError):
        return False   # 設定を読めなければ、時間帯で止まったとは言えない。移さない（使用上限の誤りは設定に依らず移す）
    acc = next((x for x in cfg.accounts if x.name == attrs.get("account")), None)
    return bool(acc and acc.hours and accounts.shut(acc.hours, now(), cfg.hours_margin_minutes))


def plan(payload, attrs_of=_attrs, closed_of=closed):
    """走らせるコマンドの並びと、走らせる場所と出力の置き場の (argv, cwd, 出力のファイル)。移さないなら None。"""
    if not payload.get("error"):
        return None
    cwd = payload.get("cwd") or os.getcwd()
    attrs = attrs_of(cwd)
    name = attrs.get("name")
    if not (attrs.get("role") and name):
        return None
    if payload["error"] != "rate_limit" and not closed_of(attrs):
        return None   # 使用上限でも時間帯でもない誤り（混み合い・要求の誤りなど）は、アカウントを替えても直らない
    here, common = gitx.git_dir(cwd), gitx.common_dir(cwd)
    if not here or not common:
        return None
    head = provision.desk_seat(here, common, attrs)
    if head and attrs.get("session") != payload.get("session_id"):
        return None   # 窓口の席（本社か、本社の属性が写った作業場）の、窓口でない会話
    if not head and attrs.get("lifecycle") != gitx.PERSISTENT and not (attrs.get("ask") and attrs.get("delivered") != attrs["ask"]):
        return None   # エフェメラルの部署は、頼みを受けている間だけ移す（オンデマンドの受け持ちの部署は、頼みの途中で枠が尽きうる）
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
