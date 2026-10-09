# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""抜き書きを照らす（lib/worldblk.verify・lib/worldcheck.verify）。集める役の返答（INPUTS_REPLY。走らなかった・落ちた周は空か null）の
抜き書きを、類ごとに上限まで取り、役が本当に取得した URL（流れの道具の出来事から引いた、同じ include の集める役の節の取得の記録）だけを
機械が取り直した本文で照らす。{kept, dropped, offline} を 1 行出して 0。集める類が無い周は返答も出来事も見ない。
出来事が読めない時は取得の記録が無いとして抜き書きを全部落とし、その旨を控えに残す（知識だけの行で進む）。
控えが無い（配線の誤り）: 1。ARTIFACTS_DIR が欠けた: 2
"""
import json
import os
import sys
from pathlib import Path

sys.dont_write_bytecode = True   # 下の import が pack の中に __pycache__ を作らないように。必ず import より前
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))
import worldblk  # noqa: E402
import reads  # noqa: E402  （役の web の取得の記録の読み口。worldblk が core を sys.path に足した後）
import webget  # noqa: E402

REPLY_ENV = "INPUTS_REPLY"
INPUTS = (REPLY_ENV,)   # 裁定 TA16: 読む INPUTS_* の組
RUN_ID_ENV = "WORKFLOW_ID"   # 出来事を読む run
COLLECT_NODE = "world-collect"   # 同じ include の集める役の節（取得の記録を引く）


def get(url):
    return webget.http_get(url, worldblk.HEADERS, worldblk.MAX_BODY)


def main() -> int:
    art = os.environ.get("ARTIFACTS_DIR")
    if not art:
        print("環境変数が無い: ARTIFACTS_DIR", file=sys.stderr)
        return 2
    out_dir = Path(art) / worldblk.OUT_DIR
    try:
        due = bool(worldblk.collect_classes(out_dir))
        reply, fetched = None, set()
        if due:
            try:
                reply = json.loads(os.environ.get(REPLY_ENV, "") or "null")
            except json.JSONDecodeError:
                reply = None
            events = reads.events_for(os.environ.get(RUN_ID_ENV, ""))
            fetched = None if events is None else set(reads.web_fetches(events, reads.top_here(COLLECT_NODE)))
        out = worldblk.verify(out_dir, reply, fetched, get)
    except worldblk.WorldGap as e:
        print(f"verify.py: {e}", file=sys.stderr)
        return 1
    sys.stdout.reconfigure(encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
