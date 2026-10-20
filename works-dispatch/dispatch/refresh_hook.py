#!/usr/bin/env python3
"""Stop のフック（裏で走る）: 部署と窓口の会話が、読み込んだ後に更新されたプラグインのまま動いていたら、ターンの終わりの手の空いた
時に、自分の窓に /reload-plugins を打って新しい版へ替える（仕組みは nodes/refresh.py）。

プラグインを配った後も、起きている会話は前の版のスキルとフックのまま動き続けた（2026-10-17 の朝、持ち主が段取りの窓で手で
/reload-plugins を 2 回打った）。配るツール（リポジトリの scripts/spread-plugins.py）は配った時に手の空いた会話にだけ打ち、ターンの途中の
会話と入力フィールドに字が在る会話は飛ばす。飛ばした会話は、このフックがそのターンの終わりに替える。どの会社の会話でも、どの道でプラグインが
更新されても（配るツール・手の claude plugin update・Claude Code の自動の更新）同じに効く。

部署か窓口（その場所の git の設定に company.role が在る）でなければ、すぐ 0 で終わる。窓口（代表の clone）では、--desk が書いた
会話の処理（company.pid）の会話だけを見る（代表の clone には持ち主のほかの会話も居る）。窓は、待ち受けのフックが /clear を打つ窓と
同じ決め方（windows.talk_window。場所が同じペインのうち、窓の前のプロセスにこの会話が居ると確かめた物）で 1 つに決め、決まらなければ（herdr の
外の会話など）何もしない。環境変数 HERDR_PANE_ID は使わない（裏の会話〔claude --bg〕は前もって起動した控えの処理で動き、その値が
別のペインを指していた。2026-10-17 に見た）。打ったら属性 company.reloaded に処理の番号と時刻を控え、同じ更新で打ち直さない。
裏で走るのでターンの終わりを待たせない。誤りは stderr に 1 行出し、会話は止めない。
"""

import json
import os
import pathlib
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
try:
    from ports import chat, term  # noqa: E402
    import windows  # noqa: E402
    import gitx  # noqa: E402
    from nodes import provision, refresh  # noqa: E402
except (ImportError, SyntaxError) as _e:
    # 裏で走るので、古い Python でも会話を止めない。知らせは止まる前のフック（orders.py stop）が会話ごとに 1 回出す
    sys.exit(0)

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8")

PLUGIN_ROOT = str(pathlib.Path(__file__).resolve().parent.parent)


def _attrs(cwd):
    """場所の部署の属性。git の口はこのモジュールの gitx を呼ぶ時に引く（試験は gitx を偽物に替える。tests/fakegit.wire）。"""
    return gitx.worktree_attrs(cwd)


def run(payload, env=os.environ, h=term, host=chat.host, same=chat.in_process, attrs_of=_attrs,
        pause=lambda: time.sleep(1), now=time.time, mark=provision.mark, plugin_root=PLUGIN_ROOT, window=None):
    """古ければ替える。結末の語（refresh.reload_when_free の物）か、見るまでもなければ None。"""
    cwd = payload.get("cwd") or os.getcwd()
    attrs = attrs_of(cwd)
    if not attrs.get("role"):
        return None
    common, place = gitx.common_dir(cwd), gitx.git_dir(cwd)
    if not common or not place:
        return None
    if provision.desk_seat(place, common, attrs) and not same(attrs.get("pid")):
        return None   # 窓口の席（本社か、本社の属性が写った作業場）の、窓口でない会話
    path = refresh.installed_file(plugin_root)   # 読み込んだこの版の置き場の、入れた物の控え
    if not path:
        return None
    pid, started = host()
    if not refresh.stale(refresh.newest_update(path, cwd), started, refresh.reloaded_at(attrs.get(refresh.ATTR), pid)):
        return None
    try:
        if window is not None:
            pane = window(cwd, h, payload.get("session_id"))
        else:
            # 打ち先は、/clear と同じく、窓の前のプロセスにこの会話が居ると確かめた窓だけ（会話の印と場所だけでは、前に居た会話や別の
            # 部署の会話の窓に打ちうる。c52730 の 5）。会話の処理の番号か、この会話の裏の処理へ attach した claude で確かめる
            jobs = (attrs.get("job"), chat.job_of(env), chat.attach_id(None, payload.get("session_id")))
            pane = windows.talk_window(cwd, h, [pid], jobs)
    except h.Error:
        return "unseen"
    if not pane:
        return None
    status = refresh.reload_when_free(pane, h, pause, lambda: refresh.clearing(attrs_of(cwd)))
    if status == "sent":
        mark(cwd, gitx.root_of(common), {refresh.ATTR: refresh.mark_value(pid, now())}, gitx)
    return status


def main(stdin=sys.stdin, env=os.environ):
    try:
        payload = json.loads(stdin.read() or "{}") or {}
    except ValueError:
        payload = {}
    try:
        status = run(payload if isinstance(payload, dict) else {}, env)
    except Exception as e:  # フックの誤りで会話を止めない
        status = str(e)
    if status == "failed" or status not in (None, "sent", "busy", "typing", "clearing", "unseen"):
        print(f"works-dispatch: 古い版のプラグインのまま動いている会話を替えられなかった（{status}。次のターンの終わりにもう一度見る。"
              f"手でなら {refresh.RELOAD}）", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
