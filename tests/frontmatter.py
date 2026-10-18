"""試験が手順書・役の定義の頭の YAML（frontmatter）を読む 1 か所。

フィールドは YAML の読み手（yaml.safe_load）で読み、行と字下げで読まない（docs/standards/machine-readable-values.md の決まり 5。
前は `^key:(.*)$` の正規表現で読み、`description: >` の畳む書き方や複数行の一覧を取り違えた）。正規表現で切るのは、頭の YAML を
本文から分ける `---` の行だけ。読めない頭は黙って空にせず ValueError で止める（決まり 4）。
PyYAML の無い環境は、呼ぶ側（tests/run.sh）が先に見て見送り（# SKIP pyyaml）にする。
"""
import re

import yaml

FRONT_RE = re.compile(r"---\r?\n(.*?)\r?\n---\r?\n(.*)", re.S)


def split(text):
    """(頭の YAML の dict, 本文) を返す。頭が無い・YAML として読めない・dict でないときは ValueError。"""
    m = FRONT_RE.match(text.lstrip("﻿"))
    if not m:
        raise ValueError("frontmatter が無い")
    try:
        data = yaml.safe_load(m.group(1))
    except yaml.YAMLError as exc:
        raise ValueError(f"frontmatter を YAML として読めない: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError(f"frontmatter が鍵と値の組でない: {type(data).__name__}")
    return data, m.group(2)
