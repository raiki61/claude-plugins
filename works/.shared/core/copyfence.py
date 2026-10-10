"""写しの柵の道具（works 自身の試験が自分の表に当てる。表の置き場は呼び手が渡す）。

考えの柵（conceptfence。地図に名の在る考えの語を数える）の隣で、名の無い中身の写しを言語に依らずに数える:
- 正規化した行: 行の頭と尾の空白を落とし、空行と、注記だけの行（頭が COMMENT_HEADS のどれか）を飛ばした行
- 写し: 正規化した行の window 行の並び（窓）が、見る所の 2 か所以上（別のファイルでも同じファイルでも）に在る物
- ファイルの写しの数: そのファイルの正規化した行のうち、写しの窓に掛かった行の数
表は {about, window, exclude: {グロブ: 理由}, known: {パス: [行の数, 理由]}}。グロブは fnmatch の形で `*` は `/` もまたぐ。
既知とちょうど揃うかは conceptfence と同じ verdict で見る（増えた・減った・表に無いファイル）。表そのものは main の表より
既知の行の数の和が増えない（growth）。

- normalize(text)・scan(root, paths, window, exclude)・peers(root, paths, window, exclude)・growth(main, now)
- peers は {パス: [写しの相手のパス]}（scan と同じ窓の印の表から出す。表は相手を持たず、赤の文がここから出す）
- load・tracked・hit・verdict・main_table は conceptfence の物をそのまま借りる（main_table は (ref の表, None) か (None, 引けない理由)）
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

tracked = conceptfence.tracked
verdict = conceptfence.verdict
load = conceptfence.read_table
hit = conceptfence.hit
main_table = conceptfence.main_table


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
    """main の表より既知の行の数の和が増えた時の文の一覧（空なら増えていない）。main に表が無ければ初めて掛ける柵なので比べない"""
    if not main:
        return []
    old = sum(n for n, _ in main["known"].values())
    new = sum(n for n, _ in now["known"].values())
    return [f"既知の写しの行の数の和が main の {old} から {new} に増えた（新しい写しは寄せる）"] if new > old else []

