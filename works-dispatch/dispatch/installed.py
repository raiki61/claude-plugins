"""今入っている版の dispatch.py へ乗り換える。

頼みの行と納品の返し方は、送った側の dispatch.py のパス（プラグインの版の置き場 cache/<マーケット>/<プラグイン>/<版>/ の中）を
そのまま書く（orders.RUN）。プラグインを上げた後も、Claude Code は前の版の置き場を 14 日残すので、部署がその字で打つと古い版が
動く。古い版は新しい版で足した決まり（会社の形の [[land.after]] など）を知らずに黙って飛ばす（2026-10-17、0.25.0 を入れた
--land を 0.23.0 の dispatch.py で打ち、配布の合図が走らなかった）。

版の置き場の中で動いていて、Claude Code の入れた物の控え（置き場のルートの installed_plugins.json）が、このプラグインの今の置き場を
別の所と言っていれば、そちらの dispatch.py を同じ引数で起動して、その終了の値で終わる。控えを読めない・置き場の外（リポジトリの
checkout など）・乗り換えた先から起動された（HOPPED）ときは乗り換えない。"""

import json
import os
import pathlib
import subprocess
import sys

HOPPED = "WORKS_DISPATCH_HOPPED"   # 乗り換えた先の印（行ったり来たりを止める）


def _same(a, b):
    return os.path.normcase(os.path.realpath(a)) == os.path.normcase(os.path.realpath(b))


def target(script, env=os.environ):
    """script（動いている dispatch.py）の代わりに起動する dispatch.py のパス。乗り換えないなら None。"""
    if env.get(HOPPED):
        return None
    here = pathlib.Path(script).resolve()
    if len(here.parents) < 6 or here.parents[4].name != "cache":
        return None
    version_dir, plugin, market, root = here.parents[1], here.parents[2].name, here.parents[3].name, here.parents[5]
    try:
        with open(root / "installed_plugins.json", encoding="utf-8") as f:
            entries = (json.load(f).get("plugins") or {}).get(f"{plugin}@{market}") or []
    except (OSError, ValueError, AttributeError):
        return None
    entries = [e for e in (entries if isinstance(entries, list) else [entries]) if isinstance(e, dict) and e.get("installPath")]
    if any(_same(e["installPath"], version_dir) for e in entries):
        return None
    # 同じプラグインを user と project の両方に入れていれば、アカウント全体に効く user の物を先にする
    for e in sorted(entries, key=lambda e: e.get("scope") != "user"):
        there = pathlib.Path(e["installPath"]) / here.parent.name / here.name
        if there.is_file():
            return str(there)
    return None


def hop(script, argv, env=os.environ):
    """乗り換えるなら、今の版を起動して終了の値を返す。乗り換えないなら None。exec でなく子として起動するのは、Windows の os.execv が
    呼んだ側のシェルに先に戻ってしまうため。"""
    there = target(script, env)
    if not there:
        return None
    print(f"works-dispatch: {script} は前の版なので、今入っている版 {there} で打ち直す", file=sys.stderr)
    return subprocess.call([sys.executable, there, *argv], env={**env, HOPPED: "1"})
