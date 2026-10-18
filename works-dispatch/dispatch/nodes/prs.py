#!/usr/bin/env python3
"""prs ノード: 自分の番の PR を集める（設計書のセクション 2 の 1）。外には書かない。

attention の whose-turn を works へ写した `vendor/whose-turn.py` を `--json` で走らせ、「自分の番」のセクションの PR を全部取る。
集合と並びは whose-turn の報告と同じ。写しは scripts/shared-copies.py が正本と同じかを見張る。
あわせて limited（判定の材料が走査の上限に当たった open な PR の番号。prs に無い PR も含む）を取る。

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
    return subprocess.run(argv, capture_output=True, text=True, encoding="utf-8", errors="replace", env=env)


def read(repo, runner=_default_runner, env=None):
    """(自分の番の PR の並び, limited の番号の集合) を返す。env は gh のアカウントを替えるときだけ渡す（GH_TOKEN 入り）。None はこの
    プロセスの環境のまま。limited が番号の並びでなければ読めないとして止める（無いのを空と読むと、取りこぼしの上の判定で会話を閉じる）。"""
    argv = [sys.executable, str(WHOSE_TURN), "--repo", repo, "--json"]
    p = runner(argv, env=env)
    try:
        out = json.loads(p.stdout) if p.returncode == 0 else None
    except ValueError:
        out = None
    if not isinstance(out, dict) or out.get("schema") != jsonio.SCHEMA_VERSION:
        raise PrsError(f"whose-turn --json（{repo}）が読めない: {(p.stderr or p.stdout).strip()[:300]}")
    limited = out.get("limited")
    if not isinstance(limited, list) or not all(isinstance(n, int) and not isinstance(n, bool) for n in limited):
        raise PrsError(f"whose-turn --json（{repo}）の limited が番号の並びでない: {limited!r}"[:300])
    return out["prs"], set(limited)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--repo", required=True)
    ap.add_argument("--out")
    a = ap.parse_args(argv)
    got, limited = read(a.repo)
    jsonio.dump({"prs": got, "limited": sorted(limited)}, a.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
