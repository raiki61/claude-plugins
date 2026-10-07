"""URL の部品の小さな道具。"""
import re


def slugify(s):
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


def join_path(*parts):
    """parts を / でつなぐ（各部品の頭と尾の / は取り、/ だけか空の部品は飛ばす）"""
    return "/".join(p.strip("/") for p in parts if p.strip("/"))
