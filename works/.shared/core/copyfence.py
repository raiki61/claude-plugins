"""写しの柵の道具（works 自身の試験が自分の表に当てる。表の置き場は呼び手が渡す）。

考えの柵（conceptfence。地図に名の在る考えの語を数える）の隣で、名の無い中身の写しを言語に依らずに数える:
- 正規化した行: 行の頭と尾の空白を落とし、空行と、注記だけの行（頭が COMMENT_HEADS のどれか）を飛ばした行
- 写し: 正規化した行の window 行の並び（窓）が、見る所の 2 か所以上（別のファイルでも同じファイルでも）に在る物
- ファイルの写しの数: そのファイルの正規化した行のうち、写しの窓に掛かった行の数
表は {about, window, exclude: {グロブ: 理由}, known: {パス: [行の数, 理由]}}。グロブは fnmatch の形で `*` は `/` もまたぐ。
既知とちょうど揃うかは conceptfence と同じ verdict で見る（増えた・減った・表に無いファイル）。表そのものは main の表より
既知の行の数の和が増えない（growth）。

- load(path)・tracked(root)・hit(path, globs)・normalize(text)・scan(root, paths, window, exclude)・verdict(found, known)
- main_table(root, rel, ref=MAIN_REF) -> ref の rel（root からの相対）の表か None（ref に表が無い）・growth(main, now)
標準ライブラリと conceptfence（追跡されたファイルの一覧・既知とのずれの文・テキストの読み）だけを使う。
"""
from __future__ import annotations

import fnmatch
import hashlib
import json
import pathlib
import subprocess
from collections import defaultdict

import conceptfence

MAIN_REF = conceptfence.MAIN_REF
COMMENT_HEADS = ("#", "//", "/*", "*", "<!--", "-->", "--")   # 注記の頭の印（言語を名指さない、よく在る形）

tracked = conceptfence.tracked
verdict = conceptfence.verdict


def load(path):
    """写しの柵の表（path の JSON）"""
    return json.loads(pathlib.Path(path).read_text(encoding="utf-8"))


def hit(path, globs):
    return any(fnmatch.fnmatch(path, g) for g in globs)


def normalize(text):
    """正規化した行の一覧（元の行の番号は持たない）"""
    out = []
    for line in text.splitlines():
        s = line.strip()
        if s and not s.startswith(COMMENT_HEADS):
            out.append(s)
    return out


def scan(root, paths, window, exclude):
    """{パス: 写しの窓に掛かった正規化した行の数}（写しの無いファイルは載せない）"""
    root = pathlib.Path(root)
    where = defaultdict(list)   # 窓の印 → [(パス, 窓の頭の位置)]
    for rel in paths:
        if hit(rel, exclude):
            continue
        text = conceptfence._text(root / rel)
        if text is None:
            continue
        lines = normalize(text)
        for k in range(len(lines) - window + 1):
            key = hashlib.blake2b("\n".join(lines[k:k + window]).encode("utf-8"), digest_size=16).digest()
            where[key].append((rel, k))
    covered = defaultdict(set)
    for spots in where.values():
        if len(spots) < 2:
            continue
        for rel, k in spots:
            covered[rel].update(range(k, k + window))
    return {rel: len(v) for rel, v in sorted(covered.items())}


def main_table(root, rel, ref=MAIN_REF):
    """ref の写しの柵の表（rel は root からの相対）。ref にその表が無ければ None（引けない ref も None。ref の在るなしは呼び手が先に見る）"""
    got = subprocess.run(["git", "-C", str(root), "show", f"{ref}:./{rel}"],
                         capture_output=True, text=True, encoding="utf-8")
    return json.loads(got.stdout) if got.returncode == 0 else None


def growth(main, now):
    """main の表より既知の行の数の和が増えた時の文の一覧（空なら増えていない）。main に表が無ければ初めて掛ける柵なので比べない"""
    if not main:
        return []
    old = sum(n for n, _ in main["known"].values())
    new = sum(n for n, _ in now["known"].values())
    return [f"既知の写しの行の数の和が main の {old} から {new} に増えた（新しい写しは寄せる）"] if new > old else []
