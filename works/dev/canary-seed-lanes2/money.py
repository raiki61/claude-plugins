"""お金の小さな道具（円を整数で数える）。"""


def split_even(total, n):
    if n <= 0:
        raise ValueError("n must be positive")
    q, r = divmod(total, n)
    return [q + 1] * r + [q] * (n - r)


def format_yen(amount):
    """amount（整数の円）を 3 桁ごとのカンマ区切りで ¥1,234 の形にする。負なら頭に -（-¥1,234）"""
    sign = "-" if amount < 0 else ""
    return f"{sign}¥{abs(amount):,}"
