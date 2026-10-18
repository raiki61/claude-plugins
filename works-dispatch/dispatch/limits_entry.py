#!/usr/bin/env python3
"""herdr のタブバーが呼ぶ、版に依らない入口。limits.py herdr-config が、使用率の控えの置き場（limits_dir）に limits-entry.py として
写す（Python を選ぶ hooks/run-python.sh も同じ所に写す）。

プラグインの置き場は版ごとのフォルダ（<設定のフォルダ>/plugins/cache/<マーケット>/works-dispatch/<版>/）で、プラグインを上げると
前の版のフォルダには .orphaned_at が付き、Claude Code が 14 日で消す。タブバーの行が版のフォルダの limits.py を直に指すと、上げた
後も前の版を呼び続け、消えた日から表示が出なくなる（2026-10-18 に、.orphaned_at の付いた 0.1.3 を呼び続けていた）。

この入口は起動のたびに、アカウントの写し（--accounts）の各アカウントの設定のフォルダの plugins/installed_plugins.json から
works-dispatch の入った場所（installPath）を読み、在って .orphaned_at の付いていない場所の dispatch/limits.py を、同じ引数で
起動する（user の scope を先にする。rbenv・asdf の shim と同じ形）。見つからなければ、show はその旨の短い字を出して 1 で終わる。

タブバーから呼ぶ道なので 3.9 の文法で書き、プラグインのほかのファイルを import しない（写した先で動く）。
"""

import json
import os
import pathlib
import subprocess
import sys

PLUGIN = "works-dispatch@"
ORPHANED = ".orphaned_at"


def config_dirs(snapshot, env=os.environ):
    """写しのアカウントの設定のフォルダの並び（書いていないアカウントは CLAUDE_CONFIG_DIR、無ければ ~/.claude）。"""
    with open(snapshot, encoding="utf-8") as f:
        accounts = json.load(f).get("accounts") or []
    default = env.get("CLAUDE_CONFIG_DIR") or "~/.claude"
    dirs = [a.get("config_dir") or default for a in accounts if isinstance(a, dict)] or [default]
    return list(dict.fromkeys(os.path.expanduser(d) for d in dirs))


def install_paths(config_dir):
    """その設定のフォルダに works-dispatch の入った場所の並び（user の scope が先）。読めなければ空。"""
    try:
        with open(os.path.join(config_dir, "plugins", "installed_plugins.json"), encoding="utf-8") as f:
            plugins = json.load(f).get("plugins") or {}
    except (OSError, ValueError, AttributeError):
        return []
    entries = []
    for name, got in plugins.items():
        if name.startswith(PLUGIN):
            entries += [e for e in (got if isinstance(got, list) else [got]) if isinstance(e, dict) and e.get("installPath")]
    return [e["installPath"] for e in sorted(entries, key=lambda e: e.get("scope") != "user")]


def gone_installs(config_dir):
    """その設定のフォルダの入れた物の控えのうち、置き場（installPath）が無い項目の (プラグイン, 範囲, 置き場) の並び（どのプラグインも見る）。
    project の範囲の項目は、そのプロジェクトで開き直すまで控えに残り、どの項目が効くかが分からなくなる。"""
    try:
        with open(os.path.join(config_dir, "plugins", "installed_plugins.json"), encoding="utf-8") as f:
            plugins = json.load(f).get("plugins") or {}
    except (OSError, ValueError, AttributeError):
        return []
    out = []
    for name, got in plugins.items() if isinstance(plugins, dict) else ():
        for e in got if isinstance(got, list) else [got]:
            if isinstance(e, dict) and isinstance(e.get("installPath"), str) and not os.path.isdir(e["installPath"]):
                out.append((name, e.get("scope") or "?", e["installPath"]))
    return out


def target(snapshot, env=os.environ):
    """起動する limits.py。見つからなければ None。"""
    for d in config_dirs(snapshot, env):
        for root in install_paths(d):
            script = pathlib.Path(root) / "dispatch" / "limits.py"
            if script.is_file() and not (pathlib.Path(root) / ORPHANED).exists():
                return str(script)
    return None


def main(argv, env=os.environ):
    snapshot = argv[argv.index("--accounts") + 1] if "--accounts" in argv[:-1] else None
    try:
        script = target(snapshot, env) if snapshot else None
    except (OSError, ValueError, AttributeError) as e:
        script, why = None, f"アカウントの写し {snapshot} が読めない（{e}）"
    else:
        why = "--accounts が無い" if not snapshot else "入っている works-dispatch の limits.py が見つからない"
    if script:
        return subprocess.call([sys.executable, script] + argv)
    if "show" in argv:
        print("works-dispatch ?")   # タブバーに出る字。訳は下の stderr
    print(f"works-dispatch: {why}（limits.py herdr-config を打ち直す）", file=sys.stderr)
    return 1


if __name__ == "__main__":
    # Windows の既定の標準出力は cp1252 などで、日本語を書くと UnicodeEncodeError で落ちる。UTF-8 に直す
    for _s in (sys.stdout, sys.stderr):
        if hasattr(_s, "reconfigure"):
            _s.reconfigure(encoding="utf-8")
    sys.exit(main(sys.argv[1:]))
