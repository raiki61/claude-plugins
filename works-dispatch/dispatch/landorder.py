#!/usr/bin/env python3
"""入口の --land-order（メインブランチへ入れる列の順を、判断役が見て決める）。dispatch.py の一部で、landing.py と同じ入口の層に置く。

列（会社の形の [land] の queue。nodes/landqueue.py）は、ふだんは申し出た順に 1 本ずつ通す。判断役（頼みを配る会話。段取りなど）は
- 名前を渡さずに打つと、待っている札を今の入れる順に出す。--land の札には、部署の名前・ブランチ・待った分・変えたファイルの数・
  ほかの待ちと重なるファイルを添える（順の決め手。docs/land.md の「入れる順を決める」）。
- 部署の名前かブランチを並べて打つと、その順を置き場の order に書く。書いた部署が前に出て、残りはその後に申し出た順で通る。
  今ゲートを回している 1 本は止めない（次から効く）。
- `-` だけを渡すと order を消し、申し出た順に戻す。
判断役が何もしなければ、列は今までどおり申し出た順に通る。
"""

import os
import tempfile
import time

import config
import gitx
from nodes import land, landqueue, tree

SHOWN = 5   # 重なるファイルを名前で出す数


def _queue(repo, ports, config_path):
    """(列の置き場, メインブランチ) か、読めなければ (None, 訳)。"""
    g = ports.git
    info = tree.read_info(repo.source, os.path.dirname(config.path_of(config_path, os.environ)),
                          committed=lambda root: tree.committed_info(root, g))
    rules = land.read_rules(info.get("path"), None, info.get("text"))
    if rules["problems"]:
        return None, "取り込みの決まりが読めない: " + " / ".join(rules["problems"])
    if not rules["queue"]:
        return None, "会社の形の [land] に queue が無い（列が無いので、入れる順は打った順に決まる）"
    return os.path.join(g.common_dir(repo.source), rules["queue"]), rules["main"] or ports.default_branch(repo)


def write(queue, names):
    """入れる順 names を order に書く（途中で読まれても半端な中身を見せないよう、置き換えで書く）。names が空なら消す。"""
    path = os.path.join(queue, landqueue.ORDER)
    if not names:
        if os.path.exists(path):
            os.remove(path)
        return
    os.makedirs(queue, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=queue, prefix=".order-")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write("# 判断役が --land-order で書いた入れる順（上から先に入る）\n" + "".join(n + "\n" for n in names))
    os.replace(tmp, path)


def rows(queue, source, main, g, now=None):
    """待っている札ごとの行の並び（今の入れる順）。"""
    now = time.time() if now is None else now
    names = landqueue.alive(queue) if os.path.isdir(queue) else []
    seen = {}
    for n in names:
        w = landqueue.who(queue, n)
        files = "no-branch"
        if w and w[1]:
            try:
                files = set(g.forked_paths(source, f"origin/{main}", w[1]))
            except gitx.GitError:
                files = None
        seen[n] = (w, files)
    out = []
    for i, n in enumerate(names, 1):
        w, files = seen[n]
        try:
            waited = int((now - int(n[:20]) / 1e9) // 60)
        except ValueError:
            waited = None
        head = f"{i}. " + (f"部署 {w[0] or '-'}（ブランチ {w[1] or '-'}）" if w else "名乗りの無い札（my_notes の collect など、--land でない処理）")
        bits = [f"待って {waited} 分" if waited is not None else "待った分は読めない"]
        if w and files == "no-branch":
            bits.append("名乗りにブランチが無い（変えたファイルを読めない）")
        elif w and files is None:
            bits.append("変えたファイルを読めない")
        elif w:
            others = [f for m, (v, f) in seen.items() if m != n and isinstance(f, set)]
            shared = sorted(set().union(*others) & files) if files else []
            bits.append(f"変えたファイル {len(files)} 件")
            if shared:
                bits.append(f"ほかの待ちと重なる {len(shared)} 件（{', '.join(shared[:SHOWN])}{' ほか' if len(shared) > SHOWN else ''}）")
        out.append(head + ": " + "、".join(bits))
    return out


def main(repo, names, ports, config_path=None):
    """--land-order [部署 ...]。名前が無ければ列を出し、有れば入れる順を書き、`-` だけなら消す。"""
    if "-" in names and names != ["-"]:
        print("止めた: - は指定を消すときに 1 つだけ渡す（ほかの名前と混ぜない）")
        return 2
    try:
        return _main(repo, names, ports, config_path)
    except (OSError, gitx.GitError) as e:
        print(f"止めた: 列を読めないか書けない（{e}）")
        return 1


def _main(repo, names, ports, config_path):
    queue, main_ = _queue(repo, ports, config_path)
    if queue is None:
        print(f"止めた: {main_}")
        return 1
    if names:
        write(queue, [] if names == ["-"] else names)
        print("入れる順を消した（申し出た順に戻した）" if names == ["-"] else f"入れる順を書いた: {' → '.join(names)}（書いていない札はその後に申し出た順）")
    want = landqueue.order(queue)
    listed = rows(queue, repo.source, main_, ports.git)
    print(f"列 {queue}: 待っているのは {len(listed)} 本（上から入る順）。入れる順の指定: {' → '.join(want) if want else '無し（申し出た順）'}")
    for line in listed:
        print(line)
    if not names:
        print("入れる順を決める: --land-order <部署> [<部署> ...]（書いた順に先に入る）。消す: --land-order -。決め手は works-dispatch の docs/land.md の「入れる順を決める」")
    return 0
