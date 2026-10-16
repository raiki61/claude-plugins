#!/usr/bin/env python3
"""このリポジトリの marketplace のプラグインを、手元の全アカウントに配る（会社の形 .claude/company.toml の役「配布」の道具）。

works-dispatch の機械窓口の道具として、`dispatch.py --call 配布 spread-plugins` か、本流に入れた後の合図（[[land.after]]）で
呼ばれる。入力の JSON（`{"dry_run": true}` で、することだけを出す）を標準入力で受ける。片づいたら 0、1 つでも失敗したら 1 で
終わり、works-dispatch がその仕事を AI の部署（役「作業」）に回す。

すること:
1. アカウントごとに（works-dispatch の設定の accounts。設定のフォルダ config_dir ごとに Claude Code を起こす）、
   `claude plugin marketplace update <このリポジトリの marketplace>` を打ち、入っているこの marketplace のプラグインだけ
   `claude plugin update <id>` を打つ。
2. herdr に開いている Claude Code の会話のうち、部署と窓口の会話（場所の git の設定に company.role が在る物）にだけ
   `/reload-plugins` を打つ。持ち主の作業の会話に打つと herdr で done に替わり、ノイズになるため（この決まりは組織の物なので、
   works-dispatch でなくここに置く）。入力欄に字が入っている会話は飛ばす。
3. その人だけの除外は手元の設定 `~/.config/claude-plugins/spread.toml` の `skip`（herdr の作業場の名前の並び）に置く。
   持ち主の値を配布物に書かない。

使い方: python3 scripts/spread-plugins.py < 入力の JSON（省けば {}）
終了の値: 0 = 配った（飛ばした会話は数えない）/ 1 = 失敗が在る / 2 = 入力か設定が読めない
"""

import json
import os
import pathlib
import subprocess
import sys
import tomllib

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8")

ROOT = pathlib.Path(__file__).resolve().parents[1]
DISPATCH_CONFIG = "~/.config/works-dispatch/dispatch.toml"   # works-dispatch の設定の既定の場所（WORKS_DISPATCH_CONFIG で替わる）
LOCAL = "~/.config/claude-plugins/spread.toml"             # その人だけの除外
RELOAD = "/reload-plugins"


def run(argv, env=None):
    p = subprocess.run(argv, capture_output=True, text=True, encoding="utf-8", errors="replace", env=env)
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def marketplace_name(root=ROOT):
    return json.loads((root / ".claude-plugin" / "marketplace.json").read_text(encoding="utf-8"))["name"]


def accounts(env=os.environ):
    """works-dispatch の設定のアカウントの並び [(名前, 設定のフォルダか None)]。設定が無ければ既定の 1 つ。"""
    path = pathlib.Path(os.path.expanduser(env.get("WORKS_DISPATCH_CONFIG") or DISPATCH_CONFIG))
    if not path.is_file():
        return [("default", None)]
    raw = tomllib.loads(path.read_text(encoding="utf-8"))
    return [(a.get("name") or "?", a.get("config_dir")) for a in raw.get("accounts", [])] or [("default", None)]


def skips(path=LOCAL):
    p = pathlib.Path(os.path.expanduser(path))
    if not p.is_file():
        return []
    got = tomllib.loads(p.read_text(encoding="utf-8")).get("skip", [])
    return [x for x in got if isinstance(x, str)]


def claude_env(config_dir, env=os.environ):
    out = {k: v for k, v in env.items() if k != "CLAUDE_CONFIG_DIR"}
    if config_dir:
        out["CLAUDE_CONFIG_DIR"] = os.path.expanduser(config_dir)
    return out


def update_account(name, config_dir, market, dry, runner=run):
    """1 つのアカウントの marketplace とプラグインを更新する。(行の並び, 失敗の数)。"""
    env = claude_env(config_dir)
    lines, bad = [], 0
    steps = [["claude", "plugin", "marketplace", "update", market]]
    code, out = runner(["claude", "plugin", "list", "--json"], env)
    try:
        installed = json.loads(out) if code == 0 else []
    except ValueError:
        installed = []
    if code != 0:
        lines.append(f"{name}: 入っているプラグインを読めない（{out.strip()[:200]}）")
        bad += 1
    ids = sorted({p["id"] for p in installed if isinstance(p, dict) and str(p.get("id", "")).endswith("@" + market)
                  and p.get("scope", "user") == "user"})
    steps += [["claude", "plugin", "update", i] for i in ids]
    for argv in steps:
        if dry:
            lines.append(f"{name}: {' '.join(argv)}（空打ち）")
            continue
        code, out = runner(argv, env)
        lines.append(f"{name}: {' '.join(argv)} " + ("済" if code == 0 else f"失敗（{out.strip()[:200]}）"))
        bad += code != 0
    return lines, bad


def herdr_json(argv, runner=run):
    code, out = runner(["herdr", *argv])
    if code != 0:
        raise RuntimeError(out.strip()[:200])
    return json.loads(out).get("result", {})


def is_company_place(cwd, runner=run):
    """その場所が部署か窓口か（git の設定 company.role が在る）。"""
    code, out = runner(["git", "-C", cwd, "config", "--worktree", "--get", "company.role"])
    return code == 0 and bool(out.strip())


def input_empty(screen):
    """会話の画面の入力欄（下から 2 本の横の罫線の間）が空か。罫線が見えなければ空と見ない。"""
    lines = (screen or "").splitlines()
    rules = [i for i, x in enumerate(lines) if x.count("─") >= 10]
    if len(rules) < 2:
        return False
    box = " ".join(" ".join(lines[rules[-2] + 1:rules[-1]]).split())
    return not box.lstrip("❯").strip()


def reload_talks(skip, dry, runner=run):
    """部署と窓口の会話に /reload-plugins を打つ。(行の並び, 失敗の数)。"""
    try:
        labels = {w["workspace_id"]: w.get("label") for w in herdr_json(["workspace", "list"], runner).get("workspaces", [])}
        panes = herdr_json(["pane", "list"], runner).get("panes", [])
    except (RuntimeError, ValueError) as e:
        return [f"herdr を読めない（{e}）"], 1
    lines, bad = [], 0
    for p in panes:
        if p.get("agent") != "claude" or not p.get("cwd"):
            continue
        where = f"{labels.get(p.get('workspace_id')) or p.get('workspace_id')}（{p['pane_id']}）"
        if labels.get(p.get("workspace_id")) in skip:
            lines.append(f"{where}: 手元の設定で除く")
            continue
        if not is_company_place(p["cwd"], runner):
            continue   # 持ち主の作業の会話（部署でも窓口でもない）には打たない
        code, screen = runner(["herdr", "pane", "read", p["pane_id"], "--lines", "40"])   # 画面の字がそのまま出る
        if code != 0:
            lines.append(f"{where}: 画面を読めない（{screen.strip()[:200]}）")
            bad += 1
            continue
        if not input_empty(screen):
            lines.append(f"{where}: 入力欄に字が在るので飛ばす")
            continue
        if dry:
            lines.append(f"{where}: {RELOAD}（空打ち）")
            continue
        code, out = runner(["herdr", "agent", "prompt", p["pane_id"], RELOAD])
        lines.append(f"{where}: {RELOAD} " + ("済" if code == 0 else f"失敗（{out.strip()[:200]}）"))
        bad += code != 0
    return lines, bad


def main(stdin=sys.stdin, runner=run, env=os.environ, local=LOCAL):
    try:
        value = json.loads(stdin.read() or "{}")
        if not isinstance(value, dict):
            raise ValueError("JSON の物で無い")
        dry = bool(value.get("dry_run"))
        market = marketplace_name()
        accs, skip = accounts(env), skips(local)
    except (OSError, ValueError, KeyError, tomllib.TOMLDecodeError) as e:
        print(f"止めた: 入力か設定を読めない（{e}）")
        return 2
    lines, bad = [], 0
    for name, config_dir in accs:
        got, n = update_account(name, config_dir, market, dry, runner)
        lines += got
        bad += n
    got, n = reload_talks(skip, dry, runner)
    lines += got
    bad += n
    print("\n".join(lines + [f"失敗 {bad} 件" if bad else "配った"]))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
