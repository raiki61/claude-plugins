"""小さな字の道具（真ん中に置く・左を埋める・語に分ける・詰める）。"""


def center(s, width, fill=" "):
    """s を width 字の真ん中に置く（余りの 1 字は右に。s が width 字以上ならそのまま）"""
    gap = width - len(s)
    if gap <= 0:
        return s
    left = gap // 2
    return fill * left + s + fill * (gap - left)


def pad_left(s, width, fill=" "):
    """s の左を fill で埋めて width 字にする（右寄せ。s が width 字以上ならそのまま）"""
    gap = width - len(s)
    if gap <= 0:
        return s
    return fill * gap + s


def words(s):
    """空白で区切った語の並び（str.split() と同じ。連なった空白は 1 つの区切り）"""
    return s.split()


def squeeze(s, ch=" "):
    """s の中の ch の連なりを 1 つに詰める"""
    out = []
    for c in s:
        if c == ch and out and out[-1] == ch:
            continue
        out.append(c)
    return "".join(out)
