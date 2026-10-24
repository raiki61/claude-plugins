"""借りるか買うかの判断の部品（rent-or-buy プラグインの bin/rent-or-buy）への口。

keepalive をあと何本送るか・いつ送るかと、compact を打つかを、部品に JSON を渡して決める（設計は
docs/specs/2026-10-24-rent-or-buy-design.md。つなぎ方は 6）。計算は部品が持ち、ここは呼んで JSON を読むだけ。
部品は works-dispatch の依存にしない（入れていなくても今の決まった数で動く。費用の最適化で、止めるゲートではない）。
置き場は、リポジトリの checkout の隣（試験・開発）か、このプラグインと同じ入れた物の控えの、同じマーケットプレイスの rent-or-buy。
見つからない・0 以外で終わった・出力が読めないときは、訳を返し、呼んだ側は今の決まった数で動く。
"""

import json
import os
import pathlib
import subprocess
import sys

from ports import chat

NAME = "rent-or-buy"


def _plugin_root(here=None):
    return pathlib.Path(here or __file__).resolve().parent.parent


def locate(here=None):
    """部品の入口のパス（無ければ None）。探す順:
    1. リポジトリの checkout の隣の rent-or-buy/bin/rent-or-buy（試験・開発）
    2. このプラグインの置き場（<設定のフォルダ>/plugins/cache/<マーケット>/<プラグイン>/<版>）の入れた物の控えの、同じマーケットの
       rent-or-buy の置き場の bin/rent-or-buy（アカウント全体に入れた物〔scope が user〕を先にする）"""
    root = _plugin_root(here)
    sibling = root.parent / NAME / "bin" / NAME
    if sibling.is_file():
        return str(sibling)
    parts = root.parts
    if len(parts) < 5 or parts[-4] != "cache":
        return None
    record = pathlib.Path(*parts[:-4]) / chat.PLUGINS_FILE
    try:
        entries = (json.loads(record.read_text(encoding="utf-8")).get("plugins") or {}).get(f"{NAME}@{parts[-3]}") or []
    except (OSError, ValueError, AttributeError):
        return None
    entries = [e for e in (entries if isinstance(entries, list) else [entries]) if isinstance(e, dict) and e.get("installPath")]
    for e in sorted(entries, key=lambda e: e.get("scope") != "user"):
        there = pathlib.Path(e["installPath"]) / "bin" / NAME
        if there.is_file():
            return str(there)
    return None


def ask(scene, facts, transcript=None, here=None, runner=subprocess.run, env=None):
    """部品の場面（keepalive か compact）に facts を渡した答え。(答えの dict, None) か、答えられなければ (None, 訳)。
    transcript は会話の記録のファイル（部品がモデル・文脈の量・最後の要求の時刻などを読む）。"""
    entry = locate(here)
    if entry is None:
        return None, f"借りるか買うかの部品（{NAME}）が入っていない"
    argv = [sys.executable, entry, scene] + (["--transcript", transcript] if transcript else [])
    try:
        p = runner(argv, input=json.dumps(facts, ensure_ascii=False), capture_output=True, text=True, encoding="utf-8",
                   errors="replace", env=dict(os.environ if env is None else env))
    except (OSError, subprocess.SubprocessError, ValueError) as e:
        return None, f"{NAME} を起動できない（{type(e).__name__}: {e}）"
    try:
        got = json.loads(p.stdout)
    except (TypeError, ValueError):
        return None, f"{NAME} の出力が JSON でない（終了コード {p.returncode}）: {(p.stdout or p.stderr or '').strip()[:200]}"
    if not isinstance(got, dict):
        return None, f"{NAME} の出力が表でない（終了コード {p.returncode}）"
    if p.returncode != 0 or got.get("error"):
        return None, f"{NAME} が答えなかった（終了コード {p.returncode}、{got.get('error')}: {str(got.get('why') or '')[:200]}）"
    if got.get("action") not in ("rent", "buy"):
        return None, f"{NAME} の答えの action が rent・buy のどちらでもない（{got.get('action')!r}）"
    return got, None
