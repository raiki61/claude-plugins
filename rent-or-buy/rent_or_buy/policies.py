"""止め時の決め方の表と、最初の決め方 fixed。

決め方は、入力 Inputs を受けて (action, reason, why) を返す関数。名前で引き、register で外から足せる。
強制の上限・延期の上限・問い合わせ口は決め方の外で、core.py が重ねる。
"""
from dataclasses import dataclass
from typing import Callable, Optional, Tuple


@dataclass(frozen=True)
class Inputs:
    """decide の入力（鍵の意味はプラグインの docs/design.md の 3.1）。"""
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


Policy = Callable[[Inputs], Tuple[str, str, str]]


def fixed(x: Inputs) -> Tuple[str, str, str]:
    """決定的な止め方。次の 1 回を借りても累計が避けられる買いの費用に届かない間だけ借りる。

    返すのは (action, reason, why)。reason は機械の読む短い鍵、why は英語の訳。
    """
    avoidable = (1 - x.miss) * x.buy
    within = x.spent + x.rent < avoidable
    detail = "spent %g + next rental %g vs avoidable buy cost %g" % (x.spent, x.rent, avoidable)
    if x.certain:
        if within:
            return "rent", "within_buy_cost", "the ending event is certain and the total stays below the buy cost: %s" % detail
        return "buy", "reached_buy_cost", "the ending event is certain and the total reaches the buy cost: %s" % detail
    if x.hazard is None:
        return "buy", "no_hazard", "the ending event is not certain and no probability was given"
    if avoidable <= 0 or x.hazard <= x.rent / avoidable:
        ratio = x.rent / avoidable if avoidable > 0 else float("inf")
        return "buy", "hazard_below_ratio", "probability %g is at most the cost ratio %g" % (x.hazard, ratio)
    if within:
        return "rent", "hazard_above_ratio", "probability %g exceeds the cost ratio and the total stays below the buy cost: %s" % (x.hazard, detail)
    return "buy", "reached_buy_cost", "probability is high but the total reaches the buy cost: %s" % detail


POLICIES: dict = {"fixed": fixed}


def register(name: str, policy: Policy) -> None:
    """決め方を名前で足す。同じ名前は置き換える。"""
    POLICIES[name] = policy
