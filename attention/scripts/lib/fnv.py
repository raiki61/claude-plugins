"""Workflow（my-turn-dig.js・dig-world.js）の fnv と同じ値を Python で出す。my-turn-prep.py・steps-prep.py・world-excerpts.py で共用。"""


def fnv32(s):
    """FNV-1a の 32 bit を UTF-16 の単位で（my-turn-dig.js と dig-world.js の fnv と同じ）。写しの段が写し違えた行を見つける印。"""
    h = 0x811c9dc5
    b = s.encode("utf-16-le", "surrogatepass")
    for i in range(0, len(b), 2):
        h ^= b[i] | (b[i + 1] << 8)
        h = (h * 0x01000193) & 0xffffffff
    return "%08x" % h
