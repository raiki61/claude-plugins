#!/usr/bin/env python3
"""Claude Code のフックから、herdr のサイドバーへ「今なにをしているか」を 1 行で送る（任意）。

PR ごとの作業場がいくつも並ぶと、サイドバーの作業場の名前だけでは、どの会話が何をしているかが分からない。
herdr の端末のタイトルは会話の始めに一度だけ付く名前で、そのあと変わらないので、見分けには使えない。
作業中は動いているツール、ターンが終わったら直前に頼まれた内容を、herdr のペインの印（カスタムのトークン $act）として送る。

使い方: Claude Code の設定（settings.json）の hooks の UserPromptSubmit・PreToolUse・Stop・Notification に
`python3 <このファイル>` を置き、herdr の設定の [ui.sidebar.agents.rows_by_agent] の claude の行に $act を置く（SKILL.md）。
herdr の外で動く会話では何もしない。herdr への送信は待たずに手放し、ツールの呼び出しを待たせない。
"""

import json
import os
import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import herdr  # noqa: E402

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


def handle(text, env, send=herdr.report_activity):
    """1 回のフックの入力を処理する。頼まれた内容はペインごとの控えに残し、ターンの終わり（Stop など）にそこへ戻す。"""
    pane = env.get("HERDR_PANE_ID")
    if env.get("HERDR_ENV") != "1" or not pane:
        return
    try:
        payload = json.loads(text)
    except ValueError:
        return
    if not isinstance(payload, dict):
        return
    ask = pathlib.Path(env.get("TMPDIR") or "/tmp") / f"herdr-ask-{pane.replace(':', '_')}"
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


if __name__ == "__main__":
    try:
        handle(sys.stdin.read(), os.environ)
    except Exception:  # noqa: BLE001 — サイドバーの表示のために、Claude Code の作業を止めない
        pass
    sys.exit(0)
