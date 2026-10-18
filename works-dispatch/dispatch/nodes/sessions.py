#!/usr/bin/env python3
"""sessions ノード: 開いている会話を、Claude Code 自身から機械で集める（設計書のセクション 2 の 2）。外には書かない。

アカウントごとに `claude agents --json` を呼び、各会話の作業フォルダ（cwd）から git で origin のリポジトリと今のブランチを読んで、
(リポジトリ, ブランチ) の組にする。herdr にも持ち主の設定にも頼らない。リポジトリまで見るので、同じ名前のブランチを別のリポジトリと取り違えない。
会話の状態は、対話の会話は status、背景の会話は state のフィールドに入る（2026-10-14 に 2.1.299 で見た）。

使い方: python3 nodes/sessions.py [--config <パス>] [--out <パス>]
"""

import argparse
import os
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
import claudex  # noqa: E402
import config  # noqa: E402
import gitx  # noqa: E402
import jsonio  # noqa: E402


def collect(listed, branch_of, origin_of):
    """listed: アカウントの名 → そのアカウントの `claude agents --json` の並び。"""
    out = []
    for account, items in listed.items():
        for s in items:
            cwd = s.get("cwd")
            out.append({
                "account": account,
                "session_id": s.get("sessionId"),
                "cwd": cwd,
                "status": s.get("status") or s.get("state"),
                "started": s["startedAt"] / 1000 if isinstance(s.get("startedAt"), (int, float)) else None,
                "repo": origin_of(cwd) if cwd else None,
                "branch": branch_of(cwd) if cwd else None,
            })
    return out


def open_keys(rows):
    return {(r["repo"], r["branch"]) for r in rows if r["repo"] and r["branch"]}


def gather(cfg, list_sessions=claudex.sessions):
    return {a.name: list_sessions(a.config_dir) for a in cfg.accounts}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config")
    ap.add_argument("--out")
    a = ap.parse_args(argv)
    cfg = config.load(a.config, os.environ)
    jsonio.dump({"sessions": collect(gather(cfg), gitx.branch, gitx.origin_repo)}, a.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
