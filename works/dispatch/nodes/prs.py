#!/usr/bin/env python3
"""prs ノード: 自分の番の PR を集める（設計書 2 節の 1）。外には書かない。

attention の whose-turn を works へ写した `vendor/whose-turn.py` を `--json` で走らせ、「自分の番」の節の PR を全部取る。
集合と並びは whose-turn の報告と同じ。写しは scripts/shared-copies.py が正本と同じかを見張る。

使い方: python3 nodes/prs.py --repo OWNER/NAME [--out <パス>]
"""

import argparse
import json
import pathlib
import subprocess
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
import jsonio  # noqa: E402

WHOSE_TURN = pathlib.Path(__file__).resolve().parent.parent / "vendor" / "whose-turn.py"


class PrsError(Exception):
    pass


def _default_runner(argv, env=None):
    return subprocess.run(argv, capture_output=True, text=True, env=env)


def fetch(repo, runner=_default_runner):
    argv = [sys.executable, str(WHOSE_TURN), "--repo", repo, "--json"]
    p = runner(argv)
    try:
        out = json.loads(p.stdout) if p.returncode == 0 else None
    except ValueError:
        out = None
    if not isinstance(out, dict) or out.get("schema") != jsonio.VERSION:
        raise PrsError(f"whose-turn --json（{repo}）が読めない: {(p.stderr or p.stdout).strip()[:300]}")
    return out["prs"]


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--repo", required=True)
    ap.add_argument("--out")
    a = ap.parse_args(argv)
    jsonio.dump({"prs": fetch(a.repo)}, a.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
