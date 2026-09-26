"""使い捨ての対象リポジトリの種。試作と同じ 2 つのバグをわざと仕込んである。

- mean: 分母が len(xs) - 1 になっている（正しくは len(xs)）。
- clamp: 上限を超えたときに lo を返している（正しくは hi）。
"""


def mean(xs):
    return sum(xs) / (len(xs) - 1)


def clamp(x, lo, hi):
    if x < lo:
        return lo
    if x > hi:
        return lo
    return x
