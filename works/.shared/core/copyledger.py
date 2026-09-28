"""写しの台帳（COPIED_FROM・COPIED_FROM.<名>）の読み口。写し直しの道具と、写しの一致を見る試験が同じここから読む。

台帳の形:
- 1 行目: 写した commit（頭の語）と、写し元の系統・版の説明
- 2 行目から: 写しのパス（台帳の置き場から）。2 列目が在れば元のパス（写し元の根から）。空行と # の行は注記
- `! {"path", "old", "new", "why"}` の行: works の手直し。path の写しは、元の中身に old がちょうど 1 度だけ在り、それを new に
  替えた物とバイト単位で同じ。台帳に載せた手直しのほかは 1 バイトも変えない（why は空にしない）
works の物を何も知らない（標準ライブラリだけ）。
"""
import json
import pathlib
import subprocess
from dataclasses import dataclass, field

CORE = pathlib.Path(__file__).resolve().parent
MARK = "! "


class LedgerError(Exception):
    """台帳が読めない・手直しが当たらない"""


@dataclass
class Ledger:
    path: pathlib.Path
    commit: str
    head: str                                    # 1 行目（丸ごと）
    rows: list = field(default_factory=list)     # [(写しのパス, 元のパス か None)]
    deviations: dict = field(default_factory=dict)   # {写しのパス: [(元のバイト, 写しのバイト)]}

    @property
    def base(self) -> pathlib.Path:
        """写しの置き場（台帳の在るフォルダ）"""
        return self.path.parent


def read(path) -> Ledger:
    path = pathlib.Path(path)
    lines = path.read_text(encoding="utf-8").splitlines()
    if not lines or not lines[0].split():
        raise LedgerError(f"{path}: 1 行目に写した commit が無い")
    led = Ledger(path=path, commit=lines[0].split()[0], head=lines[0])
    for n, ln in enumerate(lines[1:], 2):
        if not ln.strip() or ln.startswith("#"):
            continue
        if ln.startswith(MARK):
            try:
                d = json.loads(ln[len(MARK):])
            except json.JSONDecodeError as e:
                raise LedgerError(f"{path}:{n}: 手直しの行が JSON でない（{e}）") from None
            if not isinstance(d, dict) or not all(isinstance(d.get(k), str) and d[k] for k in ("path", "old", "new", "why")):
                raise LedgerError(f"{path}:{n}: 手直しの行は path・old・new・why（どれも空でない文字列）を持つ")
            led.deviations.setdefault(d["path"], []).append((d["old"].encode("utf-8"), d["new"].encode("utf-8")))
            continue
        cols = ln.split("#", 1)[0].split()
        led.rows.append((cols[0], cols[1] if len(cols) > 1 else None))
    listed = {r for r, _ in led.rows}
    stray = sorted(set(led.deviations) - listed)
    if stray:
        raise LedgerError(f"{path}: 手直しの行の path が写しの一覧に無い: {stray}")
    return led


def apply(led: Ledger, rel: str, src: bytes) -> bytes:
    """元の中身 src に rel の手直しを当てた、写しが持つべきバイト（元のバイトが 1 度でなければ LedgerError）"""
    for old, new in led.deviations.get(rel, ()):
        if src.count(old) != 1:
            raise LedgerError(f"{rel}: 手直しの元 {old!r} が元の中身に {src.count(old)} 度在る（1 度だけのはず）")
        src = src.replace(old, new)
    return src


def show(repo, rev: str, path: str):
    """git show <rev>:<path> のバイト（無ければ None）"""
    r = subprocess.run(["git", "-C", str(repo), "show", f"{rev}:{path}"], capture_output=True)
    return r.stdout if r.returncode == 0 else None


def core_commit() -> str:
    """写しの graphloops の commit（.shared/core/COPIED_FROM の 1 行目）"""
    return read(CORE / "COPIED_FROM").commit
