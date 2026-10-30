"""判断の記録。JSONL を 1 行足し、大きくなったら古い物を 1 つだけ残して切る。足す所は中身を問わない。

結果の行（scene が outcome）は、前に記録した判断の鍵（key）に、実際に払った額と選ばなかった手の見積もりを結ぶ。
"""
import json
import math
import os
from pathlib import Path
from typing import Iterator, Optional

from .core import InputError

MAX_BYTES = 10 * 1024 * 1024
KEY_CHARS = 200   # 鍵の字数の上限（呼ぶ側の識別の字で、長い文を入れる所ではない）


def _old(p: Path) -> Path:
    return p.with_name(p.stem + ".1" + p.suffix)


def append_record(path, row: dict, max_bytes: int = MAX_BYTES) -> Optional[str]:
    """row を 1 行足す。成功なら None、書けなければ訳の文を返す（判断は止めない）。

    max_bytes を超えていたら、名前を `<名前>.1<拡張子>` に替えて新しく始める（古い 1.1 は消える）。
    """
    p = Path(path)
    try:
        line = json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n"
        p.parent.mkdir(parents=True, exist_ok=True)
        if p.exists() and p.stat().st_size > max_bytes:
            # 並行して呼ばれると、別の呼び出しが先に切った新しい記録を古い物として動かしうる。ロックは持たない
            # （記録は失っても判断に響かない）
            os.replace(p, _old(p))
        with p.open("a", encoding="utf-8") as f:
            f.write(line)
    except (OSError, TypeError, ValueError) as e:
        return "cannot write the record: %s" % e
    return None


def read_records(path, since: Optional[str] = None, until: Optional[str] = None) -> Iterator[dict]:
    """記録の行を古い順に返す（切った古い物 `<名前>.1<拡張子>` が先）。since ≤ ts < until の行だけ（時刻は記録と同じ
    `YYYY-MM-DDTHH:MM:SSZ` の字で比べる）。読めない行と ts の無い行は飛ばす。ファイルが無ければ何も返さない。"""
    p = Path(path)
    for f in (_old(p), p):
        try:
            data = f.read_bytes()
        except FileNotFoundError:
            continue
        for line in data.splitlines():
            try:
                # 字の読みは行ごと（書きかけで多バイト字の途中で切れた行も、その行だけ飛ばす。UnicodeDecodeError も ValueError）
                row = json.loads(line.decode("utf-8"))
            except ValueError:
                continue
            ts = row.get("ts") if isinstance(row, dict) else None
            if not isinstance(ts, str) or (since and ts < since) or (until and ts >= until):
                continue
            yield row


def _amount(item: dict, name: str, nullable: bool):
    v = item.get(name)
    if v is None and nullable:
        return
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or v < 0:
        raise InputError("%s must be a number >= 0%s" % (name, " or null" if nullable else ""))


def check_outcome(item) -> dict:
    """結果の 1 件を確かめて返す。key（判断に渡した鍵）・paid（選んだ手で実際に払った額）は要る。alternative（選ばなかった手の
    見積もり。null は見積もれない）・detail（呼ぶ側の表。中は問わない）は省ける。ほかの鍵は InputError。"""
    if not isinstance(item, dict):
        raise InputError("an outcome must be a JSON object")
    unknown = sorted(set(item) - {"key", "paid", "alternative", "detail"})
    if unknown:
        raise InputError("unknown keys in an outcome: %s" % ", ".join(unknown))
    if not isinstance(item.get("key"), str) or not 0 < len(item["key"]) <= KEY_CHARS:
        raise InputError("key must be a string of 1 to %d characters" % KEY_CHARS)
    _amount(item, "paid", False)
    _amount(item, "alternative", True)
    if "detail" in item and not isinstance(item["detail"], dict):
        raise InputError("detail must be a JSON object")
    return item
