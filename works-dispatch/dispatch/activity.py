#!/usr/bin/env python3
"""Claude Code のフックから、herdr のサイドバーへ「今なにをしているか」を 1 行で送る（任意）。

PR ごとの作業場がいくつも並ぶと、サイドバーの作業場の名前だけでは、どの会話が何をしているかが分からない。
herdr の端末のタイトルは会話の始めに一度だけ付く名前で、そのあと変わらないので、見分けには使えない。
作業中は動いているツール、ターンが終わったら直前に頼まれた内容を、herdr のペインの印（カスタムのトークン $act）として送る。

使い方: `python3 <このファイル> settings` が、Claude Code の設定（settings.json）に足す hooks の塊（UserPromptSubmit・PreToolUse・
Stop・Notification で、Python をフックと同じ決まり〔hooks/run-python.sh〕で選んでこのファイルを呼ぶ）を JSON で出す。herdr の設定の [ui.sidebar.agents.rows_by_agent] の claude の行に
$act を置く（SKILL.md）。引数なしで起こすと、フックとして標準入力の 1 回ぶんを処理する。
herdr の外で動く会話では何もしない。herdr への送信は待たずに手放し、ツールの呼び出しを待たせない。印を送るペインは、会話の id か
場所で herdr のペインから引く（pane_of）。
"""

import json
import os
import pathlib
import re
import shlex
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import herdr  # noqa: E402

# Windows の既定の標準入出力は cp1252 などで、日本語を書くと UnicodeEncodeError で落ちる。UTF-8 に直す
for _s in (sys.stdin, sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8")

TTL_MS = 3600000  # 送った印が消えるまで。会話が止まったまま 1 時間たてば、古い作業内容を出し続けない
INJECTED = re.compile(r"<(system-reminder|task-notification)>.*?</\1>", re.S)


def _flat(text, n):
    text = " ".join(str(text).split())
    return text[:n] + "…" if len(text) > n else text


def _target(tool, inp):
    if tool == "Bash":
        return inp.get("command", "")
    if tool in ("Read", "Edit", "Write", "NotebookEdit"):
        return os.path.basename(inp.get("file_path", ""))
    if tool in ("Grep", "Glob"):
        return inp.get("pattern", "")
    if tool == "WebFetch":
        return inp.get("url", "")
    if tool == "WebSearch":
        return inp.get("query", "")
    if tool in ("Agent", "Task"):
        return inp.get("description", "")
    if tool == "Skill":
        return inp.get("skill", "")
    return ""


def label(payload):
    """フックの入力から 1 行を作る。頼まれた内容（UserPromptSubmit）とツール（PreToolUse）のほかは None。

    頼まれた内容からは、機械が足した塊（system-reminder・task-notification）を落とす。人が打った文字ではないため。
    """
    event = payload.get("hook_event_name")
    if event == "UserPromptSubmit":
        return _flat(INJECTED.sub("", payload.get("prompt") or ""), 30)
    if event == "PreToolUse":
        tool = payload.get("tool_name") or "?"
        inp = payload.get("tool_input") if isinstance(payload.get("tool_input"), dict) else {}
        target = _flat(_target(tool, inp), 22)
        return f"{tool} {target}" if target else tool
    return None


def confirmed_pane(cwd, sid, env=os.environ):
    """この会話の居るペインのうち、窓の前のプロセスにこの会話が居ると確かめた物（/clear の打ち先と同じ確かめ方。wake_hook.talk_window）。
    会話の印と場所だけで決めると、前に居た会話や別の部署の会話の窓に札を付けた（2026-10-17、割り振りの窓にほかの会話の作業内容が
    出た。c52730 の 5）。決まらなければ None。"""
    import claudex   # noqa: E402  ここだけで使う（ツールのたびに読み込まない）
    import wake_hook   # noqa: E402
    return wake_hook.talk_window(cwd, herdr, [claudex.host()[0]], (wake_hook.job_of(env), claudex.attach_id(None, sid)))


def pane_of(payload, tmp, find=None):
    """この会話の居るペイン（herdr.own_pane の決め方。環境変数 HERDR_PANE_ID は裏の会話では別のペインを指すことがあるので使わない）。
    決まったら会話の id ごとの控えに残し、次からは herdr を読まない。ツールの呼び出し（PreToolUse）では控えだけを見て、決まって
    いなければ印を送らない（ツールのたびに herdr を待たせない）。"""
    sid = payload.get("session_id")
    memo = tmp / f"herdr-pane-{sid}" if sid else None
    try:
        return memo.read_text(encoding="utf-8").strip() or None
    except (AttributeError, OSError):
        pass
    if payload.get("hook_event_name") == "PreToolUse":
        return None
    try:
        pane = find(payload.get("cwd"), sid) if find else confirmed_pane(payload.get("cwd"), sid)
    except herdr.HerdrError:
        return None
    if pane and memo:
        memo.write_text(pane, encoding="utf-8")
    return pane


def handle(text, env, send=herdr.report_activity, find=None):
    """1 回のフックの入力を処理する。頼まれた内容はペインごとの控えに残し、ターンの終わり（Stop など）にそこへ戻す。"""
    if env.get("HERDR_ENV") != "1":
        return
    try:
        payload = json.loads(text)
    except ValueError:
        return
    if not isinstance(payload, dict):
        return
    tmp = pathlib.Path(env.get("TMPDIR") or "/tmp")
    pane = pane_of(payload, tmp, find)
    if not pane:
        return
    ask = tmp / f"herdr-ask-{pane.replace(':', '_')}"
    event = payload.get("hook_event_name")
    line = label(payload)
    if event == "UserPromptSubmit" and line:
        ask.write_text(line, encoding="utf-8")
    elif event in ("Stop", "SubagentStop", "Notification"):
        try:
            line = ask.read_text(encoding="utf-8")
        except OSError:
            line = None
    if line and line.strip():
        send(pane, line, TTL_MS)


EVENTS = ("UserPromptSubmit", "PreToolUse", "Stop", "Notification")


def settings(script):
    """settings.json に足す hooks の塊。PreToolUse は全部のツールに当てる（matcher は空）。"""
    # Python はフックと同じ決まりで選ぶ（hooks/run-python.sh。Windows の Store へ誘う代わりの物を飛ばす）。この台本は TOML を読まないので下限は 3.9
    script = pathlib.Path(script).resolve()   # 台本と選ぶ台本を同じ形で書く（Windows で片方だけドライブ名が付かない）
    picker = script.parent.parent / "hooks" / "run-python.sh"
    hook = [{"type": "command", "command": f"bash {shlex.quote(picker.as_posix())} --min 3.9 {shlex.quote(script.as_posix())}"}]
    return {"hooks": {e: [{"matcher": "", "hooks": hook} if e == "PreToolUse" else {"hooks": hook}] for e in EVENTS}}


if __name__ == "__main__":
    if sys.argv[1:] == ["settings"]:
        print(json.dumps(settings(str(pathlib.Path(__file__).resolve())), ensure_ascii=False, indent=2))
        sys.exit(0)
    try:
        handle(sys.stdin.read(), os.environ)
    except Exception:  # noqa: BLE001 — サイドバーの表示のために、Claude Code の作業を止めない
        pass
    sys.exit(0)
