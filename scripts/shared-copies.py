#!/usr/bin/env python3
"""プラグインへ写した共有の本文を、確かめる・配る。

**なぜ写しなのか。** プラグインは 1 つずつ配られ、インストール後の実体は自分のサブディレクトリだけになる
(実測 2026-09-15: `~/.claude/plugins/cache/raiki61/gates/<版>/` に在るのは `hooks/ README.md skills/` だけで、
リポジトリの他の場所は無い)。だから実行時に 1 か所を共有する道が無く、**写して配るしかない**。
代わりに、写しが割れたら赤くなる柵をここに置く。

**走査対象は印から導く**(名前を手で並べない)。docstring に `MARK` の 1 文を持つ `.py` を集め、
同じファイル名のものを 1 組として見る。3 つ目の写しを作った周に、誰も見ない写しが増える形にしない。

使い方:
    python3 scripts/shared-copies.py                     # 確かめる(tests/run.sh がこれを呼ぶ)
    python3 scripts/shared-copies.py --sync <直した写し>  # その 1 本を組の全員へ配る

終了コード: 0 = 揃っている / 1 = 割れている・写し先が無い・走査が空回り / 2 = 使い方が違う
"""
import hashlib
import pathlib
import shutil
import sys

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8")

ROOT = pathlib.Path(__file__).resolve().parents[1]
SELF = pathlib.Path(__file__).resolve()  # 印を**データとして**持つのはこの道具だけ——走査からは外す
MARK = "この本文は複数のプラグインに写しで在る"


def groups():
    """印を持つ本文を、ファイル名ごとの組にして返す。"""
    out = {}
    for p in sorted(ROOT.rglob("*.py")):
        if ".git" in p.parts or "__pycache__" in p.parts or p.resolve() == SELF:
            continue
        try:
            if MARK in p.read_text(encoding="utf-8"):
                out.setdefault(p.name, []).append(p)
        except (OSError, UnicodeDecodeError):
            continue
    return out


def rel(p):
    return str(p.relative_to(ROOT))


def check(gs):
    if not gs:
        print("NG 写しだと名乗る本文が 1 つも無い(走査が空回り——この柵は何も測っていない)")
        return 1
    bad = 0
    for name, ps in sorted(gs.items()):
        where = [rel(p) for p in ps]
        if len(ps) < 2:
            print(f"NG {where[0]}: 写しだと名乗っているのに写し先が無い(配られていない。印を外すか、配れ)")
            bad = 1
            continue
        if len({hashlib.sha256(p.read_bytes()).hexdigest() for p in ps}) > 1:
            print(f"NG {name}: 写しが割れている({where})——1 か所で直して配れ: "
                  f"python3 scripts/shared-copies.py --sync {where[0]}")
            bad = 1
    if bad:
        return 1
    print("SHARED_COPIES_OK(" + "・".join(f"{n}×{len(ps)}" for n, ps in sorted(gs.items())) + ")")
    return 0


def sync(src, gs):
    src = pathlib.Path(src).resolve()
    ps = gs.get(src.name, [])
    if src not in ps:
        print(f"NG {src} は写しの組に無い(印『{MARK}』を持つ .py を指せ)")
        return 2
    wrote = [p for p in ps if p != src and p.read_bytes() != src.read_bytes()]
    for p in wrote:
        shutil.copyfile(src, p)
    print("SHARED_COPIES_SYNCED(%s → %s)" % (rel(src), "・".join(rel(p) for p in wrote) or "差分なし"))
    return 0


def main(argv):
    gs = groups()
    if not argv:
        return check(gs)
    if argv[0] == "--sync" and len(argv) == 2:
        return sync(argv[1], gs)
    print(__doc__.split("使い方:")[1].strip())
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
