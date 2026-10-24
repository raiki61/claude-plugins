"""判断の記録。JSONL を 1 行足し、大きくなったら古い物を 1 つだけ残して切る。中身は問わない。"""
import json
import os
from pathlib import Path
from typing import Optional

MAX_BYTES = 10 * 1024 * 1024


def append_record(path, row: dict, max_bytes: int = MAX_BYTES) -> Optional[str]:
    """row を 1 行足す。成功なら None、書けなければ訳の文を返す（判断は止めない）。

    max_bytes を超えていたら、名前を `<名前>.1<拡張子>` に替えて新しく始める（古い 1.1 は消える）。
    """
    p = Path(path)
    try:
        line = json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n"
        p.parent.mkdir(parents=True, exist_ok=True)
        if p.exists() and p.stat().st_size > max_bytes:
            os.replace(p, p.with_name(p.stem + ".1" + p.suffix))
        with p.open("a", encoding="utf-8") as f:
            f.write(line)
    except (OSError, TypeError, ValueError) as e:
        return "記録を書けない: %s" % e
    return None
