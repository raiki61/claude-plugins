"""止め時の決め方の表と、最初の決め方 fixed。

決め方は、入力 Inputs を受けて (action, why) を返す関数。名前で引き、register で外から足せる。
強制の上限・延期の上限・問い合わせ口は決め方の外で、core.py が重ねる。
"""
from dataclasses import dataclass
from typing import Callable, Optional, Tuple


@dataclass(frozen=True)
class Inputs:
    """decide の入力（鍵の意味は docs/specs/2026-10-24-rent-or-buy-design.md の 2.1）。"""
    rent: float
    buy: float
    spent: float
    certain: bool
    miss: float = 0
    hazard: Optional[float] = None
    deferred: int = 0
    defer_limit: int = 0
    forced: bool = False
    ask: bool = False
    answer: Optional[dict] = None
    policy: str = "fixed"


Policy = Callable[[Inputs], Tuple[str, str]]


def fixed(x: Inputs) -> Tuple[str, str]:
    """決定的な止め方。次の 1 回を借りても累計が避けられる買いの費用に届かない間だけ借りる。"""
    avoidable = (1 - x.miss) * x.buy
    within = x.spent + x.rent < avoidable
    detail = "累計 %g + 次の 1 回 %g、避けられる買い %g" % (x.spent, x.rent, avoidable)
    if x.certain:
        if within:
            return "rent", "確かに来る。累計が買いに届かない: %s" % detail
        return "buy", "確かに来る。累計が買いに届く: %s" % detail
    if x.hazard is None:
        return "buy", "来るか分からず、来る確率も無い"
    if avoidable <= 0 or x.hazard <= x.rent / avoidable:
        return "buy", "来る確率 %g が費用の比 %g 以下" % (x.hazard, x.rent / avoidable if avoidable > 0 else float("inf"))
    if within:
        return "rent", "来る確率 %g が費用の比を超え、累計も届かない: %s" % (x.hazard, detail)
    return "buy", "来る確率は高いが、累計が買いに届く: %s" % detail


POLICIES: dict = {"fixed": fixed}


def register(name: str, policy: Policy) -> None:
    """決め方を名前で足す。同じ名前は置き換える。"""
    POLICIES[name] = policy
