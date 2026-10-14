#!/usr/bin/env python3
"""accounts ノード: 使用率の控えから、選べるアカウントとその順を決める（設計書 2 節の 3）。外には書かない。

- 週の枠（seven_day）か 5 時間の枠（five_hour）の使用率が上限に達したアカウントは選ばない。使用率は 1% 刻みの整数で届き、ちょうど上限の値は上限を超えている見込みがあるので、上限ちょうども選ばない。
- 切り替わりの時刻（resets_at）が過ぎた枠は、切り替わった後なので使用率 0 とみなす。
- 選べるものを、週の枠の切り替わりの近い順 → 週の使用率の低い順 → 設定の順に並べる。
- 控えが無い・読めないアカウントは、使用率が分からないものとして選べる側に残し、順の最後に置く（D7）。
- 使用率の枠の無いアカウント（設定の limits = false。Ollama・Foundry など）は控えを読まず、控えの無いものと同じに扱う。

使い方: python3 nodes/accounts.py [--config <パス>] [--out <パス>] [--now <Unix 時刻>]
"""

import argparse
import json
import math
import os
import pathlib
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
import config  # noqa: E402
import jsonio  # noqa: E402

WINDOWS = ("seven_day", "five_hour")


def _window(raw, now):
    """控えの 1 つの枠を {used, resets_at} にする。切り替わりの過ぎた枠は used 0・resets_at None。"""
    if not isinstance(raw, dict):
        return {"used": None, "resets_at": None}
    used, at = raw.get("used_percentage"), raw.get("resets_at")
    if isinstance(at, (int, float)) and at <= now:
        return {"used": 0, "resets_at": None}
    return {"used": used if isinstance(used, (int, float)) else None,
            "resets_at": int(at) if isinstance(at, (int, float)) else None}


def rank(accounts, limits, limit_percent, now):
    rows = []
    for i, a in enumerate(accounts):
        raw = limits.get(a.name) if a.limits else None
        known = isinstance(raw, dict)
        w = {k: _window(raw.get(k) if known else None, now) for k in WINDOWS}
        over = [k for k in WINDOWS if w[k]["used"] is not None and w[k]["used"] >= limit_percent]
        rows.append({
            "name": a.name,
            "command": a.command,
            "config_dir": a.config_dir,
            "seven_day": w["seven_day"],
            "five_hour": w["five_hour"],
            "known": known,
            "eligible": not over,
            "reason": "、".join(f"{k} が {w[k]['used']}% で上限 {limit_percent}% に達した" for k in over) or None,
            "_order": i,
        })
    rows.sort(key=lambda r: (
        not r["eligible"],
        not r["known"],
        r["seven_day"]["resets_at"] if r["seven_day"]["resets_at"] is not None else math.inf,
        r["seven_day"]["used"] if r["seven_day"]["used"] is not None else math.inf,
        r["_order"],
    ))
    for r in rows:
        del r["_order"]
    return rows


def read_limits(limits_dir, names):
    """<limits_dir>/<名>.json を読む。無い・JSON でない・枠が表でないものは None。"""
    out = {}
    for n in names:
        try:
            raw = json.loads((pathlib.Path(limits_dir) / f"{n}.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            raw = None
        if not isinstance(raw, dict) or not all(isinstance(raw.get(k, {}), dict) for k in WINDOWS):
            raw = None
        out[n] = raw
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config")
    ap.add_argument("--out")
    ap.add_argument("--now", type=float, help="時刻を固定する（試験用）。省くと今")
    a = ap.parse_args(argv)
    cfg = config.load(a.config, os.environ)
    lim = read_limits(cfg.limits_dir, [x.name for x in cfg.accounts if x.limits])
    jsonio.dump({"accounts": rank(cfg.accounts, lim, cfg.limit_percent, a.now or time.time())}, a.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
