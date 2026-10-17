#!/usr/bin/env python3
"""このリポジトリの marketplace のプラグインを、手元の全アカウントに配る（会社の形 .claude/company.toml の役「配布」の道具）。

works-dispatch の機械窓口の道具として、`dispatch.py --call 配布 spread-plugins` か、本流に入れた後の合図（[[land.after]]）で
呼ばれる。入力の JSON（`{"dry_run": true}` で、することだけを出す）を標準入力で受ける。片づいたら 0、1 つでも失敗したら 1 で
終わり、works-dispatch がその仕事を AI の部署（役「作業」）に回す。

すること:
1. アカウントごとに（works-dispatch の設定の accounts と、手元の設定 `~/.config/claude-plugins/spread.toml` の accounts。
   設定のフォルダ config_dir ごとに Claude Code を起こす）、`claude plugin marketplace update <このリポジトリの marketplace>`
   を打ち、入っているこの marketplace のプラグインだけ `claude plugin update <id>` を打つ。marketplace の clone の作業ツリーから
   消えたファイルは戻し、入った写しに .claude-plugin/plugin.json が無ければ失敗に数える。works-dispatch の設定に載るのは
   部署を起こす先のアカウントだけなので、Claude Code を使うが部署は起こさないアカウントは手元の設定の accounts に書く
   （書き方は works-dispatch の設定と同じ `{ name = "…", config_dir = "…" }`。同じ設定のフォルダは 1 回だけ配る）。
   配った後に、入ったプラグインの版が本流（origin/main。先に git fetch する）の plugin.json の版と同じかを照らし、
   違えば失敗に数える。全アカウントが本流の版に合えば、版はそろっている（会話が installed_plugins.json を手で見なくて済む）。
2. herdr に開いている Claude Code の会話のうち、部署と窓口の会話（場所の git の設定に company.role が在る物）にだけ
   `/reload-plugins` を打つ。持ち主の作業の会話に打つと herdr で done に替わり、ノイズになるため（この決まりは組織の物なので、
   works-dispatch でなくここに置く）。入力欄に字が入っている会話は飛ばす。
3. その人だけの除外は手元の設定の `skip`（herdr の作業場の名前の並び）に置く。持ち主の値を配布物に書かない。

使い方: python3 scripts/spread-plugins.py < 入力の JSON（省けば {}）
終了の値: 0 = 配った（飛ばした会話は数えない）/ 1 = 失敗が在る（失敗の行を出力の終わりに並べ直す）/ 2 = 入力か設定が読めない
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
LOCAL = "~/.config/claude-plugins/spread.toml"             # その人だけの配る先の足しと除外
RELOAD = "/reload-plugins"


def run(argv, env=None):
    p = subprocess.run(argv, capture_output=True, text=True, encoding="utf-8", errors="replace", env=env)
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def marketplace_name(root=ROOT):
    return json.loads((root / ".claude-plugin" / "marketplace.json").read_text(encoding="utf-8"))["name"]


def read_toml(path):
    p = pathlib.Path(os.path.expanduser(path))
    return tomllib.loads(p.read_text(encoding="utf-8")) if p.is_file() else {}


def accounts(env=os.environ, local=LOCAL):
    """配る先のアカウントの並び [(名前, 設定のフォルダか None)]。works-dispatch の設定の物に手元の設定の物を足し、
    同じ設定のフォルダは先の 1 つだけ残す。works-dispatch の設定が無いか accounts が空なら、既定の 1 つから始める。"""
    raw = read_toml(env.get("WORKS_DISPATCH_CONFIG") or DISPATCH_CONFIG).get("accounts") or [{"name": "default"}]
    out, seen = [], set()
    for a in raw + read_toml(local).get("accounts", []):
        if not isinstance(a, dict):
            continue
        d = a.get("config_dir")
        key = os.path.realpath(os.path.expanduser(d)) if d else None
        if key not in seen:
            seen.add(key)
            out.append((a.get("name") or "?", d))
    return out


def skips(path=LOCAL):
    return [x for x in read_toml(path).get("skip", []) if isinstance(x, str)]


def claude_env(config_dir, env=os.environ):
    out = {k: v for k, v in env.items() if k != "CLAUDE_CONFIG_DIR"}
    if config_dir:
        out["CLAUDE_CONFIG_DIR"] = os.path.expanduser(config_dir)
    return out


def mend_clone(name, market, env, dry, runner=run):
    """その設定のフォルダの marketplace の clone で、作業ツリーから消えた tracked のファイルを index から戻す。行の並び。
    clone のやり直しが途中で切れると、作業ツリーが欠けたまま marketplace update は済になり、その後の plugin update は
    欠けた写しを入れるか（plugin.json の無い写しは版でなく commit の名前の版で入る）「destination is empty after copy」で
    失敗する（2026-10-17 に p2 で実測）。marketplace update は欠けを戻さないので、ここで戻す。"""
    code, out = runner(["claude", "plugin", "marketplace", "list", "--json"], env)
    try:
        loc = next((m.get("installLocation") for m in json.loads(out) if isinstance(m, dict) and m.get("name") == market),
                   None) if code == 0 else None
    except ValueError:
        loc = None
    if not loc:
        return []   # 戻せないときも、入った写しの検査（update_account）が欠けを失敗に数える
    code, out = runner(["git", "-C", loc, "ls-files", "--deleted"])
    gone = out.splitlines() if code == 0 else []
    if not gone:
        return []
    what = f"{name}: marketplace の clone の作業ツリーに {len(gone)} 個のファイルが無いので戻す"
    if dry:
        return [what + "（空打ち）"]
    code, out = runner(["git", "-C", loc, "checkout", "--", "."])
    return [what + (" 済" if code == 0 else f" 失敗（{out.strip()[:200]}）")]


def expected_versions(market, root=ROOT, runner=run):
    """(本流の {id: 版}, 読めなかったときの行か None)。本流は origin/main で、先に fetch する（fetch が切れても手元の
    origin/main で照らす。--land の push の後なら手元の origin/main も入れた commit を指す）。"""
    runner(["git", "-C", str(root), "fetch", "--quiet", "origin", "main"])
    def show(path):
        code, out = runner(["git", "-C", str(root), "show", f"origin/main:{path}"])
        if code != 0:
            raise ValueError(out.strip()[:200])
        return json.loads(out)
    try:
        out = {}
        for p in show(".claude-plugin/marketplace.json").get("plugins", []):
            src = p.get("source")
            if isinstance(src, str) and src.startswith("./"):
                out[f"{p['name']}@{market}"] = show(f"{src[2:]}/.claude-plugin/plugin.json").get("version")
        return out, None
    except (ValueError, KeyError, AttributeError) as e:
        return {}, f"本流の版を読めない（{e}）"


def installed_ids(name, market, env, runner=run):
    """(入っているこの marketplace のプラグインの {id: (入った場所, 版)}, 読めなかったときの行か None)。user の scope の物だけ。"""
    code, out = runner(["claude", "plugin", "list", "--json"], env)
    try:
        got = json.loads(out) if code == 0 else None
    except ValueError:
        got = None
    if not isinstance(got, list):
        return {}, f"{name}: 入っているプラグインを読めない（{out.strip()[:200]}）"
    return {p["id"]: (p.get("installPath"), p.get("version")) for p in got if isinstance(p, dict) and str(p.get("id", "")).endswith("@" + market)
            and p.get("scope", "user") == "user"}, None


def update_account(name, config_dir, market, dry, want, runner=run):
    """1 つのアカウントの marketplace とプラグインを更新する。(行の並び, 失敗の行の並び)。want は本流の {id: 版}。
    「済」と出すのは、入った写しに .claude-plugin/plugin.json が在り、版が本流と同じときだけ（欠けた写しや古い版を済と数えない）。
    本流に無いプラグイン（marketplace から外した物）は版を照らさない。"""
    env = claude_env(config_dir)
    lines, bad = [], []

    def note(line, failed):
        lines.append(line)
        if failed:
            bad.append(line)

    argv = ["claude", "plugin", "marketplace", "update", market]
    if dry:
        note(f"{name}: {' '.join(argv)}（空打ち）", False)
    else:
        code, out = runner(argv, env)
        note(f"{name}: {' '.join(argv)} " + ("済" if code == 0 else f"失敗（{out.strip()[:200]}）"), code != 0)
    for line in mend_clone(name, market, env, dry, runner):
        note(line, "失敗（" in line)
    ids, err = installed_ids(name, market, env, runner)
    if err:
        note(err, True)
    done = []
    for i in sorted(ids):
        argv = ["claude", "plugin", "update", i]
        if dry:
            note(f"{name}: {' '.join(argv)}（空打ち）", False)
            continue
        code, out = runner(argv, env)
        if code != 0:
            note(f"{name}: {' '.join(argv)} 失敗（{out.strip()[:200]}）", True)
        else:
            done.append(i)
    if done:
        after, err = installed_ids(name, market, env, runner)
        for i in done:
            head = f"{name}: claude plugin update {i} "
            where, version = after.get(i, (None, None))
            if err:
                note(head + "失敗（入った写しを確かめられない）", True)
            elif not where or not (pathlib.Path(where) / ".claude-plugin" / "plugin.json").is_file():
                note(head + f"失敗（入った写しに .claude-plugin/plugin.json が無い: {where}）", True)
            elif i in want and version != want[i]:
                note(head + f"失敗（版が本流とそろわない: 入った版 {version}・本流 {want[i]}）", True)
            else:
                note(head + f"済（{version}）", False)
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
    """部署と窓口の会話に /reload-plugins を打つ。(行の並び, 失敗の行の並び)。"""
    try:
        labels = {w["workspace_id"]: w.get("label") for w in herdr_json(["workspace", "list"], runner).get("workspaces", [])}
        panes = herdr_json(["pane", "list"], runner).get("panes", [])
    except (RuntimeError, ValueError) as e:
        line = [f"herdr を読めない（{e}）"]
        return line, line
    lines, bad = [], []
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
            bad.append(lines[-1])
            continue
        if not input_empty(screen):
            lines.append(f"{where}: 入力欄に字が在るので飛ばす")
            continue
        if dry:
            lines.append(f"{where}: {RELOAD}（空打ち）")
            continue
        code, out = runner(["herdr", "agent", "prompt", p["pane_id"], RELOAD])
        lines.append(f"{where}: {RELOAD} " + ("済" if code == 0 else f"失敗（{out.strip()[:200]}）"))
        if code != 0:
            bad.append(lines[-1])
    return lines, bad


def main(stdin=sys.stdin, runner=run, env=os.environ, local=LOCAL):
    try:
        value = json.loads(stdin.read() or "{}")
        if not isinstance(value, dict):
            raise ValueError("JSON の物で無い")
        dry = bool(value.get("dry_run"))
        market = marketplace_name()
        accs, skip = accounts(env, local), skips(local)
    except (OSError, ValueError, KeyError, tomllib.TOMLDecodeError) as e:
        print(f"止めた: 入力か設定を読めない（{e}）")
        return 2
    lines, bad = [], []
    want = {}
    if not dry:
        want, err = expected_versions(market, runner=runner)
        if err:
            lines.append(err)
            bad.append(err)
    for name, config_dir in accs:
        got, fails = update_account(name, config_dir, market, dry, want, runner)
        lines += got
        bad += fails
    got, fails = reload_talks(skip, dry, runner)
    lines += got
    bad += fails
    # 失敗の行は終わりに並べ直す（works-dispatch が作業に回す頼みには出力の終わりしか載らない）
    print("\n".join(lines + ([f"失敗 {len(bad)} 件:"] + [f"- {x}" for x in bad] if bad else ["配った"])))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
