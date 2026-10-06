"""小さな字の道具（詰める・真ん中に置く・語に分ける・切り詰める）。"""

ELLIPSIS = "…"


def pad_left(s, width, fill=" "):
    """s の左に fill を詰めて width 字にする。s が width 字以上ならそのまま返す"""
    return s + fill * (width - len(s))


def center(s, width, fill=" "):
    """s を width 字の真ん中に置く（余りの 1 字は右に）"""
    gap = width - len(s)
    if gap <= 0:
        return s
    left = gap // 2
    return fill * left + s + fill * (gap - left)


def words(s):
    """空白で区切った語の並び（連なった空白は 1 つの区切り）"""
    return s.split()


def initials(s):
    """各語の頭の 1 字を大文字にして連ねる"""
    return "".join(w[0].upper() for w in words(s))


def strip_margin(text, marker="|"):
    """各行の頭の空白と marker を 1 つ取る（marker の無い行はそのまま）"""
    out = []
    for line in text.splitlines():
        head = line.lstrip()
        out.append(head[len(marker):] if head.startswith(marker) else line)
    return "\n".join(out)


def count_lines(text):
    """行の数（末尾の改行の後の空の行は数えない）"""
    return len(text.splitlines())


def squeeze(s, ch=" "):
    """ch の連なりを 1 つにする"""
    out = []
    for c in s:
        if c == ch and out and out[-1] == ch:
            continue
        out.append(c)
    return "".join(out)


def truncate(s, limit):
    """s を limit 字以内にする。切った時は末尾を省略の印 ELLIPSIS（1 字）にし、印を含めて limit 字にする"""
    if len(s) <= limit:
        return s
    return s[:limit] + ELLIPSIS
