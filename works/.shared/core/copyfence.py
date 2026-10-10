"""写しの柵の道具（works 自身の試験が自分の表に当てる。表の置き場は呼び手が渡す）。

考えの柵（conceptfence。地図に名の在る考えの語を数える）の隣で、名の無い中身の写しを言語に依らずに数える:
- 正規化した行: 行の頭と尾の空白を落とし、空行と、注記だけの行（頭が COMMENT_HEADS のどれか）を飛ばした行
- 写し: 正規化した行の window 行の並び（窓）が、見る所の 2 か所以上（別のファイルでも同じファイルでも）に在る物
- ファイルの写しの数: そのファイルの正規化した行のうち、写しの窓に掛かった行の数
表は {about, window, exclude: {グロブ: 理由}, known: {パス: [行の数, 理由] か [行の数, 理由, [寄せ元のパス…]]}}。グロブは
fnmatch の形で `*` は `/` もまたぐ。既知とちょうど揃うかは conceptfence と同じ verdict で見る（増えた・減った・表に無いファイル）。
表そのものは main の表より増えない（growth）: 既知の行の数の和が増えない。main の既知に無いパスは、3 つ目の欄（寄せ元 from）が
どれも main の既知に在り、寄せ元の main からの減りがそのパスの行の数を埋める時だけ通す。減りは 1 度だけ配る: 寄せ元を分け合う
新しいパスは 1 つの組にし、組の行の和が組の寄せ元の減りの和以下の時だけ通す（写しを寄せて新しいパスに移す時の明示の
付け替え。それ以外の新しいパスは数の増減に関わらず赤）。

- normalize(text)・scan(root, paths, window, exclude)・peers(root, paths, window, exclude)・growth(main, now)
- peers は {パス: [写しの相手のパス]}（scan と同じ窓の印の表から出す。表は相手を持たず、赤の文がここから出す）
- 表の読み・追跡されたファイル・グロブ当て・既知とのずれ・main の表は conceptfence の口（read_table・tracked・hit・verdict・main_table）を呼び手が直に使う
標準ライブラリと conceptfence（追跡されたファイルの一覧・既知とのずれの文・テキストの読み）だけを使う。
"""
from __future__ import annotations

import hashlib
import pathlib
from collections import defaultdict

import conceptfence

MAIN_REF = conceptfence.MAIN_REF
COMMENT_HEADS = ("#", "//", "/*", "*", "<!--", "-->", "--")   # 注記の頭の印（言語を名指さない、よく在る形）
SAME_FILE = "同じファイルの中"   # peers が、写しの相手が同じファイル自身であることを示す印

def normalize(text):
    """正規化した行の一覧（元の行の番号は持たない）"""
    out = []
    for line in text.splitlines():
        s = line.strip()
        if s and not s.startswith(COMMENT_HEADS):
            out.append(s)
    return out


def _windows(root, paths, window, exclude):
    """{窓の印: [(パス, 窓の頭の位置)]}（見ない所と読めないファイルは飛ばす。2 か所以上に在る印が写し）"""
    root = pathlib.Path(root)
    where = defaultdict(list)
    for rel in paths:
        if conceptfence.hit(rel, exclude):
            continue
        text = conceptfence._text(root / rel)
        if text is None:
            continue
        lines = normalize(text)
        for k in range(len(lines) - window + 1):
            key = hashlib.blake2b("\n".join(lines[k:k + window]).encode("utf-8"), digest_size=16).digest()
            where[key].append((rel, k))
    return where


def scan(root, paths, window, exclude):
    """{パス: 写しの窓に掛かった正規化した行の数}（写しの無いファイルは載せない）"""
    covered = defaultdict(set)
    for spots in _windows(root, paths, window, exclude).values():
        if len(spots) < 2:
            continue
        for rel, k in spots:
            covered[rel].update(range(k, k + window))
    return {rel: len(v) for rel, v in sorted(covered.items())}


def peers(root, paths, window, exclude):
    """{パス: [写しの相手のパス]}（scan が載せるパスと同じ。同じファイルの中の写しは SAME_FILE で示す）"""
    out = defaultdict(set)
    for spots in _windows(root, paths, window, exclude).values():
        if len(spots) < 2:
            continue
        for i, (rel, _) in enumerate(spots):
            out[rel].update(SAME_FILE if other == rel else other for j, (other, _) in enumerate(spots) if j != i)
    return {rel: sorted(v) for rel, v in sorted(out.items())}


def growth(main, now):
    """main の表より増えた所の文の一覧（空なら増えていない）: 既知の行の数の和が増えた・main に無いパスが寄せ元で埋まらない。
    main に表が無ければ初めて掛ける柵なので比べない"""
    if not main:
        return []
    was, known = main["known"], now["known"]
    old, new = sum(v[0] for v in was.values()), sum(v[0] for v in known.values())
    out = [f"既知の写しの行の数の和が main の {old} から {new} に増えた（新しい写しは寄せる）"] if new > old else []
    groups = []   # [(新しいパスの集合, 寄せ元の集合)]。寄せ元を分け合うパスは 1 つの組（減りは組に 1 度だけ配る）
    for path, row in sorted(known.items()):
        if path in was:
            continue
        sources = set(row[2] if len(row) > 2 else [])
        missing = sorted(s for s in sources if s not in was)
        if not sources:
            out.append(f"main の表に無い既知の写し {path}（{row[0]} 行。寄せ元 from が無い。新しい写しは寄せる）")
        elif missing:
            out.append(f"main の表に無い既知の写し {path} の寄せ元 {'・'.join(missing)} が main の既知に無い")
        else:
            touching = [g for g in groups if g[1] & sources]
            paths = {path}.union(*(g[0] for g in touching))
            groups = [g for g in groups if g not in touching] + [(paths, sources.union(*(g[1] for g in touching)))]
    for paths, sources in groups:
        need = sum(known[p][0] for p in paths)
        freed = sum(was[s][0] - (known[s][0] if s in known else 0) for s in sources)
        if freed < need:
            out.append(f"main の表に無い既知の写し {'・'.join(sorted(paths))}（{need} 行）を寄せ元 {'・'.join(sorted(sources))} の"
                       f"減り {freed} 行で埋められない")
    return out
