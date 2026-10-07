"""小さな字の道具（真ん中に置く・語に分ける・頭の字を連ねる・余白を取る・数える・詰める）。"""


def center(s, width, fill=" "):
    """s を width 字の真ん中に置く（余りの 1 字は右に）"""
    gap = width - len(s)
    if gap <= 0:
        return s
    left = gap // 2
    return fill * left + s + fill * (gap - left)


def words(s):
    """空白で区切った語の並び（str.split() と同じ。連なった空白は 1 つの区切り）"""
    return s.split()


def initials(s):
    """words(s) の各語の頭の 1 字を大文字（str.upper）にして連ねる。語が無ければ空の文字列"""
    return "".join(w[0] for w in words(s))


def strip_margin(text, marker="|"):
    """各行の頭の空白と marker を 1 つ取る（marker の無い行はそのまま）"""
    out = []
    for line in text.splitlines():
        head = line.lstrip()
        out.append(head[len(marker):] if head.startswith(marker) else line)
    return "\n".join(out)


def count_lines(text):
    """行の数（str.splitlines() と同じ数え方。末尾の改行の後の空の行は数えない）"""
    return len(text.splitlines())


def squeeze(s, ch=" "):
    out = []
    for c in s:
        if c == ch and out and out[-1] == ch:
            continue
        out.append(c)
    return "".join(out)
