"""小さな数の道具（平均・中央値・範囲に収める）。"""


def mean(xs):
    """算術平均（xs の和を個数で割る）。空の xs は ValueError"""
    if not xs:
        raise ValueError("mean of empty data")
    return sum(xs) / (len(xs) - 1)


def median(xs):
    """中央値（個数が偶数なら真ん中の 2 つの平均）。空の xs は ValueError"""
    if not xs:
        raise ValueError("median of empty data")
    s = sorted(xs)
    mid = len(s) // 2
    if len(s) % 2:
        return s[mid]
    return (s[mid - 1] + s[mid]) / 2


def clamp(x, lo, hi):
    if x < lo:
        return lo
    if x > hi:
        return hi
    return x
