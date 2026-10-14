#!/usr/bin/env python3
"""作業場のノード（固定の作業場の実装）: 設定に並べた作業場ごとに、空いているかを出す（設計書 3 節）。外には書かない。

差し替える所はこのノードで、同じ出力の形と空きの意味（試験 test_sessions_slots.contract）を守れば中身を替えてよい。
空きとみなすのは、次の全部を満たす作業場だけ。
- herdr にその名の workspace とペインがあり、ペインの作業フォルダが設定の path と同じ
- そのペインに herdr が会話を見ていない。入力待ちの会話も空きとみなさない（会話を閉じるのは持ち主だけ）
- どのアカウントの会話も、その path かその下を作業フォルダに持たない（herdr が会話を見落としても、空きと誤らないため）
- 追跡しているファイルに未コミットの変更が無い

使い方: python3 nodes/slots.py --sessions <sessions の JSON> [--config <パス>] [--repo OWNER/NAME] [--out <パス>]
"""

import argparse
import os
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
import config  # noqa: E402
import gitx  # noqa: E402
import herdr  # noqa: E402
import jsonio  # noqa: E402


def _under(cwd, path):
    c, p = pathlib.PurePath(cwd), pathlib.PurePath(path)
    return c == p or p in c.parents


def fixed(repo, panes, labels, session_cwds, branch_of, is_clean):
    by_label = {}
    for p in panes:
        by_label.setdefault(labels.get(p.get("workspace_id")), p)
    rows = []
    for s in repo.slots:
        pane = by_label.get(s.workspace)
        reason = None
        if pane is None:
            reason = "no_pane"
        elif os.path.realpath(pane.get("cwd") or "") != os.path.realpath(s.path):
            reason = "path_mismatch"
        elif pane.get("agent"):
            reason = "agent"
        elif any(_under(c, s.path) for c in session_cwds if c):
            reason = "session"
        elif not is_clean(s.path):
            reason = "dirty"
        rows.append({
            "workspace": s.workspace,
            "pane": pane.get("pane_id") if pane else None,
            "path": s.path,
            "branch": branch_of(s.path),
            "free": reason is None,
            "reason": reason,
        })
    return rows


def pick_repo(cfg, name):
    if name is None:
        return cfg.repos[0]
    for r in cfg.repos:
        if r.repo == name:
            return r
    raise config.ConfigError(f"設定の repos に {name} が無い")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config")
    ap.add_argument("--repo")
    ap.add_argument("--sessions", required=True)
    ap.add_argument("--out")
    a = ap.parse_args(argv)
    cfg = config.load(a.config, os.environ)
    cwds = {s["cwd"] for s in jsonio.load(a.sessions)["sessions"]}
    rows = fixed(pick_repo(cfg, a.repo), herdr.panes(), herdr.workspace_labels(), cwds, gitx.branch, gitx.is_clean)
    jsonio.dump({"slots": rows}, a.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
