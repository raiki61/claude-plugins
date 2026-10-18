#!/usr/bin/env python3
"""refresh ノード: 古い版のプラグインで動いている会話を、手の空いた時に新しい版へ替える（自分の窓に /reload-plugins を打つ）。
流れ（いつ呼ぶか）はターンの終わりのフック refresh_hook.py が持つ。

起きている会話は、起きた時か最後の /reload-plugins の時に読んだプラグインのまま動く。/clear では替わらない（2026-10-17 に
Claude Code 2.1.302 の実物で、版を上げた後の /clear の SessionStart のフックが前の版の置き場から走るのを見た）。替えるのは
/reload-plugins か起動し直し（Claude Code の文書 plugins/loading の「Loaded, in the running session」）。

古いかは時刻で決める。会話の処理（Claude Code）が起きた時刻と、この会話に前に /reload-plugins を打った時刻（属性 company.reloaded。
処理の番号と組で控える）の遅い方より後に、入れた物の控え（installed_plugins.json）のどれかのプラグインが更新されていれば古い。
どのプラグインの版を読んだかは外から読めないので、更新の時刻で比べる。人や配るツールが手で打った /reload-plugins は控えに無いので、
その後のターンの終わりにもう 1 度打つことがある（害は無い）。

打つのは、herdr が会話の手が空いたと見ていて（idle・done）、入力フィールドが空のときだけ。ターンの途中・入力フィールドに字が在る（人が書いている）
ときは打たず、次のターンの終わりにもう一度見る。同じターンの終わりに待ち受けのフック（wake_hook.clear_now）が窓に /clear を打つ会話
（納品し終えた fresh の部署・区切りの印 company.rest の在る会話）では、/clear が済んで属性に印が付くのを待ってから打つ（2 つの
打ち込みを重ねない）。/reload-plugins は裏で待っているフック（asyncRewake の待ち受け）を止めない
（2026-10-17 に 2.1.302 で、待ち受けの最中に打っても、待ち受けが終わって会話を再開させるのを見た）。
"""

import datetime
import json
import os

from nodes import deliver, role, wake

RELOAD = "/reload-plugins"
ATTR = "reloaded"           # 属性 company.reloaded = "<会話の処理の番号> <打った時刻（秒）>"
IDLE = ("idle", "done")     # herdr が会話の手が空いたと見る状態（done はターンを終えたまま見られていない物）
BUSY = ("working", "blocked")
LOOKS = 15                  # ターンの終わりのすぐ後は、まだ動いていると出ることがある。/clear が済むのも待つ。この回数だけ見直す


def installed_file(plugin_root):
    """このプラグインの置き場（<設定のフォルダ>/plugins/cache/<マーケット>/<プラグイン>/<版>）から、入れた物の控えのパス。
    置き場の外（リポジトリの checkout から読んだ物など）なら None。"""
    parts = os.path.normpath(plugin_root or "").split(os.sep)
    if len(parts) < 5 or parts[-4] != "cache":
        return None
    return os.sep.join(parts[:-4] + ["installed_plugins.json"])


def _epoch(text):
    try:
        return datetime.datetime.fromisoformat(str(text).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def _applies(entry, cwd):
    """その控えの 1 件が、この場所の会話に読み込まれる物か（user の物か、この場所を含むプロジェクトの物）。"""
    if entry.get("scope", "user") == "user":
        return True
    project = entry.get("projectPath")
    if not project:
        return False
    here, there = os.path.realpath(cwd), os.path.realpath(project)
    return here == there or here.startswith(there.rstrip(os.sep) + os.sep)


def newest_update(path, cwd):
    """控えのうち、この場所の会話に効くプラグインの、いちばん新しい更新の時刻（秒）。読めなければ None。"""
    try:
        with open(path, encoding="utf-8") as f:
            plugins = json.load(f).get("plugins") or {}
    except (OSError, ValueError, AttributeError):
        return None
    times = [_epoch(e.get("lastUpdated") or e.get("installedAt"))
             for entries in plugins.values() if isinstance(entries, list)
             for e in entries if isinstance(e, dict) and _applies(e, cwd)]
    return max((t for t in times if t is not None), default=None)


def reloaded_at(mark, pid):
    """属性の控えのうち、この処理に打った時刻。別の処理（起動し直す前の会話）の控えなら None。"""
    parts = (mark or "").split()
    if len(parts) == 2 and parts[0] == str(pid):
        try:
            return float(parts[1])
        except ValueError:
            return None
    return None


def stale(newest, started, reloaded=None):
    """読み込んだ後に更新されたプラグインが在るか。"""
    if newest is None or started is None:
        return False
    return newest > max(started, reloaded or 0)


def clearing(attrs):
    """このターンの終わりに、待ち受けのフックが窓に /clear を打つ会話か（打ち終えると属性の印が替わり、偽になる）。"""
    ask = attrs.get("ask")
    return bool(attrs.get(wake.REST) or ask and attrs.get("fresh") == role.FRESH and attrs.get("delivered") == ask
                and attrs.get("cleared") != ask)


def reload_when_free(pane, h, pause, hold=lambda: False):
    """手が空いていて入力フィールドが空なら、窓に /reload-plugins を打つ。hold() が真の間（ほかのフックが窓に打つ途中）は待つ。書く口。
    結末の語を返す: sent（打った）・busy（ターンが続いている）・typing（入力フィールドに字が在る）・clearing（/clear が済まない）・
    unseen（窓を読めない・形が見えない）・failed（herdr が受け付けない）。"""
    status = "unseen"
    for _ in range(LOOKS):
        pause()
        if hold():
            status = "clearing"
            continue
        try:
            state = (h.agent(pane) or {}).get("agent_status")
            if state not in IDLE:
                status = "busy" if state in BUSY else "unseen"
                continue
            box = deliver.typed(h.read(pane, 40, ansi=True))
        except h.HerdrError:
            status = "unseen"
            continue
        if box is None:
            status = "unseen"
            continue
        if box:
            return "typing"   # 人が書いている文を壊さない（薄字の候補は数えない）
        try:
            h.prompt(pane, RELOAD, False)
        except h.HerdrError:
            return "failed"
        return "sent"
    return status


def mark_value(pid, now):
    return f"{pid} {int(now)}"

