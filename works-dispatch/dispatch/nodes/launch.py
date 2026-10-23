#!/usr/bin/env python3
"""launch ノード: 割り振りの案の 1 行と作業場のペインを受け、そのペインでアカウントの Claude Code を起動する（設計書のセクション 2 の 6）。外に書く。

ペインのシェルに、アカウントの起動のコマンド（設定の accounts の command）を打ち込む。最初のプロンプトは付けない。
`CLAUDE_CONFIG_DIR=… claude` の形は使わない。持ち主の claude はシェル関数で、既定のアカウントのトークンを入れてから起動するので、
設定のフォルダを替えても既定のアカウントで動いてしまう。herdr の agent start も使わない（素の claude を起動し、アカウントを選べない）。
起動した後に、そのペインに会話が見えることを herdr から読み戻してから返す（送ったつもりで起きていない、を返さない）。
打ち込む前に、ペインの前にシェルだけが居ることを確かめる。vim・dev server・別の会話が残っていれば打ち込まない（pane_busy）。
起動した後に確認の画面（フォルダの信頼・ログインなど）で止まったら、blocked で返し、/catchup は送らない。
POSIX のシェルでは、コマンドの前に `ATTENTION_CATCHUP_OPEN=0` を置く。attention の /catchup は書いたページを VS Code の窓に
開くが、dispatch は何件も一度に起動するので、窓にタブが一気に開かないようにする（ページは書かれ、一覧のページに載る）。
シェル関数のアカウントのコマンドにも、この前置きは関数の間だけ環境変数として渡る（bash・zsh で確かめた）。
PR・issue の会話には `--settings <templates/session-settings.json>` を付け、選択肢の画面で問うツール（AskUserQuestion）を外す。その画面で
問われると、窓を開いてキーを押すまで会話が進まず、窓口の会話からは答えられない（2026-10-23、guided-resolver の issue #1895）。
各アカウントの settings.json の deny（tiers の段 2 が点検する前提。docs/prerequisites.md の 13）を満たしていない人の環境でも、
dispatch が開く会話では止まらないようにする。--settings の permissions の並びは、アカウントの設定の並びと合わさる（置き換えない。
https://code.claude.com/docs/en/settings の「Lists merge instead of overriding」）。部署の会話は会社の形の役の設定が同じ deny を持つ。
部署（入口の --task）は start_background が、Claude Code の裏の会話（`claude --bg`）として部署の作業場で起動し、attach が同じ
ペインでその会話につなぐ（会社の形の設計 9.1）。持ち主のアカウントのコマンドはシェル関数のことがあり、鍵はその関数が入れる
（関数を通さずに打った回は blocked のまま進まなかった）ので、裏の会話も herdr のペインに打ち込んで起動する。

使い方: python3 nodes/launch.py --plan <plan の JSON> --number <PR 番号> --pane <ペイン ID> [--out <パス>]
"""

import argparse
import os
import pathlib
import shlex
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from ports import chat, term  # noqa: E402
import jsonio  # noqa: E402


QUIET_CATCHUP = "ATTENTION_CATCHUP_OPEN=0"
# PR・issue の会話にだけ効かせる設定のファイル（--settings。選択肢の画面で問うツールを外す）
SESSION_SETTINGS = str(pathlib.Path(__file__).resolve().parent.parent / "templates" / "session-settings.json")


def _quote(text, posix):
    """シェルに 1 語で渡す形。POSIX のシェルは shlex の形、それ以外（Windows の PowerShell・cmd）は二重引用符で囲む。"""
    return shlex.quote(text) if posix else '"' + text.replace('"', '') + '"'


BUSY = "作業場のペインの前で、シェルではない物が動いている（打ち込まない。そのペインを空けてから打ち直す）"


def start(row, pane, h=term, posix=None, settings=SESSION_SETTINGS):
    """PR・issue の会話を、/catchup の窓を開かない前置き（POSIX のシェルだけ）と、その会話にだけ効く設定（--settings）を付けて起動する。"""
    posix = os.name != "nt" if posix is None else posix
    command = f"{row['account']['command']} --settings {_quote(settings, posix)}"
    if posix:
        command = f"{QUIET_CATCHUP} {command}"
    result = {"number": row["number"], "pane": pane, "status": "launch_failed", "detail": None}
    try:
        if not h.shell_in_front(pane):
            result.update(status="pane_busy", detail=BUSY)
            return result
        h.run(pane, command)
        state = h.wait_ready(pane)
        seen = h.agent(pane)
    except h.Error as e:
        result["detail"] = str(e)
        return result
    if state == "blocked":
        result.update(status="blocked", detail="起動した後に確認の画面で止まっている（フォルダの信頼・ログインなど）。"
                                               "そのペインで答えてから最初の文を送る")
        return result
    if seen.get("agent") != chat.AGENT:
        result["detail"] = f"起動した後のペインに会話が見えない（agent={seen.get('agent')}, status={seen.get('agent_status')}）"
        return result
    result["status"] = "ready"
    return result


def start_background(row, pane, name, settings, text, h=term, posix=None, pause=lambda: time.sleep(1), model=None, effort=None):
    """部署の会話を裏で起動する: ペインに名前（row の label）を付け、`<アカウントのコマンド> --bg --name <名前> --settings <ファイル>
    [--model <モデル>] [--effort <段>] <最初の文>` を打ち込み、シェルが前に戻る（--bg は起動してすぐ戻る）のを待つ。{pane, status, detail}。status は
    sent（打ち込んで戻った。会話が在るかは入口が会話の一覧で確かめる）・pane_busy・blocked（確認の画面で止まった）・launch_failed。
    model と effort は役の項目から入口が決めた値（会社の形の設計 4.8。role.launch_flags）。gh のアカウントの鍵は、ここで環境変数として前に置いても裏の会話に届かない
    （--bg の会話は起動したシェルの環境を継がない。2026-10-16 に 2.1.301 で見た）ので、部署の属性から SessionStart のフックが入れる。
    確認の画面（フォルダの信頼など）で止まると、--bg も戻らない（2026-10-16 に信頼していないフォルダで見た）。herdr がその会話を
    blocked と見たら返す。期限は足さない（D5）。"""
    posix = os.name != "nt" if posix is None else posix
    command = (f"{row['account']['command']} --bg --name {_quote(name, posix)} --settings {_quote(settings, posix)} "
               + (f"--model {_quote(model, posix)} " if model else "") + (f"--effort {_quote(effort, posix)} " if effort else "")
               + _quote(text, posix))
    result = {"pane": pane, "status": "launch_failed", "detail": None}
    try:
        if not h.shell_in_front(pane):
            result.update(status="pane_busy", detail=BUSY)
            return result
        if row.get("label"):
            try:
                h.rename_pane(pane, row["label"])
            except h.Error as e:
                result["detail"] = f"ペインに名前を付けられなかった（{e}）"
        h.run(pane, command)
        pause()
        while not h.shell_in_front(pane):
            if h.agent(pane).get("agent_status") == "blocked":
                result.update(status="blocked", detail="起動するときに確認の画面で止まっている（フォルダの信頼・ログインなど）。"
                                                       "そのペインで答えると会話が裏で始まる")
                return result
            pause()
    except h.Error as e:
        result["detail"] = str(e)
        return result
    result["status"] = "sent"
    return result


def attach(row, pane, session_id, h=term):
    """同じペインで `<アカウントのコマンド> attach <id>` を打ち込み、裏の会話の画面をペインに出す。ペインを閉じても会話は続く
    （2026-10-16 に試した）。{pane, status: attached|launch_failed, detail}。"""
    try:
        h.run(pane, f"{row['account']['command']} attach {session_id}")
    except h.Error as e:
        return {"pane": pane, "status": "launch_failed", "detail": str(e)}
    return {"pane": pane, "status": "attached", "detail": None}


def end_stale_attach(pane, h=term):
    """部署の窓の前に残った attach の画面を、Ctrl+Z でシェルに戻す。裏の処理が止まって会話が落ちた後も、attach は「Waking
    session …」のまま前に残る（Linux で見た。まっさらな環境での 7 回目の試しの 2）。`claude attach --help` は「Ctrl+Z drops back
    to your shell. The session keeps running either way.」と書き、Ctrl-C は attach を終わらせない（Linux の 2.1.301 で、生きた
    attach も止まった attach も確かめた。8 回目の試しの 3）。前に居るのが attach のときだけ送る。送ったら True。"""
    try:
        front = h.foreground(pane)
    except h.Error:
        return False
    if not any(" attach " in f" {c} " for c in front):
        return False
    h.send_keys(pane, "ctrl+z")
    return True


# 窓の前をシェルに戻すまでに見る回数（1 回ごとに pause）
SHELL_LOOKS = 10


def to_shell(pane, h=term, pause=lambda: time.sleep(1), looks=SHELL_LOOKS):
    """窓の前の attach の画面を終わらせ、シェルが前に戻ったら True。Ctrl+Z の後、Claude Code 2.1.302 はシェルでなく会話の一覧の
    画面（claude agents）を出し、そこで Esc を押すとシェルに戻った（d7d50c。2.1.301 までは Ctrl+Z でシェルに戻った）ので、
    シェルが戻らなければ Esc を 1 回足す。前に attach が居なければ、シェルが居るかだけを返す。"""
    try:
        if h.shell_in_front(pane):
            return True
    except h.Error:
        return False
    if not end_stale_attach(pane, h):
        return False
    escaped = False
    for i in range(looks):
        pause()
        try:
            if h.shell_in_front(pane):
                return True
            if not escaped and i >= 1:
                h.send_keys(pane, "escape")
                escaped = True
        except h.Error:
            return False
    return False


def start_named(command, pane, name, text, h=term, posix=None, settings=None, model=None, effort=None):
    """前の会話（持ち主の前で動く会話。窓口など）を、そのペインのシェルで `<アカウントのコマンド> --name <名前> [--model <値>]
    [--effort <値>] [--settings <ファイル>] <最初の文>` で起動する。settings は役の起動の設定のファイル（role.write_desk_settings）、
    model・effort は役の値（None なら旗を付けない）。{pane, status: ready|pane_busy|blocked|launch_failed, detail}。"""
    posix = os.name != "nt" if posix is None else posix
    result = {"pane": pane, "status": "launch_failed", "detail": None}
    try:
        if not h.shell_in_front(pane):
            result.update(status="pane_busy", detail=BUSY)
            return result
        h.run(pane, f"{command} --name {_quote(name, posix)} "
                    + "".join(f"--{k} {_quote(v, posix)} " for k, v in (("model", model), ("effort", effort)) if v)
                    + (f"--settings {_quote(settings, posix)} " if settings else "") + _quote(text, posix))
        state = h.wait_ready(pane)
        seen = h.agent(pane)
    except h.Error as e:
        result["detail"] = str(e)
        return result
    if state == "blocked":
        result.update(status="blocked", detail="起動した後に確認の画面で止まっている（フォルダの信頼・ログインなど）")
        return result
    if seen.get("agent") != chat.AGENT:
        result["detail"] = f"起動した後のペインに会話が見えない（agent={seen.get('agent')}, status={seen.get('agent_status')}）"
        return result
    result["status"] = "ready"
    return result


def bring_back(pane, command, h=term):
    """起動し直せなかったとき、ペインのシェルで command（前の会話へ戻るコマンド。`<コマンド> --resume <id>` か `<コマンド> attach <短い id>`）を
    打ち、会話が戻るのを待つ。戻れば None、ほかは訳。"""
    try:
        if not h.shell_in_front(pane):
            return f"窓 {pane} の前にシェルが居ない"
        h.run(pane, command)
        state = h.wait_ready(pane)
        seen = h.agent(pane)
    except h.Error as e:
        return str(e)
    if state == "blocked" or seen.get("agent") != chat.AGENT:
        return f"打った後に会話が見えない（{state}）"
    return None


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--plan", required=True)
    ap.add_argument("--number", type=int, required=True)
    ap.add_argument("--pane", required=True)
    ap.add_argument("--out")
    a = ap.parse_args(argv)
    row = next(r for r in jsonio.load(a.plan)["plan"] if r["number"] == a.number and r["outcome"] == "assigned")
    jsonio.dump({"launch": start(row, a.pane)}, a.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
