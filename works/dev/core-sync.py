# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""写しの取り直しと確かめ（写しの台帳 COPIED_FROM から写し、台帳の手直しを当てる。vendir の sync・pip の vendoring と同じ形）。

使い方:
  python3 works/dev/core-sync.py --check
      台帳（下の LEDGERS）に並ぶ写しが、台帳の 1 行目の commit の元に手直しを当てた物とバイト単位で同じか、graphloops を
      元にする台帳の commit が揃っているかを見る。書かない。ずれが在れば 1 行ずつ出して 1
  python3 works/dev/core-sync.py sync <rev> --version <graphloops の版> [--skip-goldens]
      graphloops を元にする台帳の写しを <rev> から取り直し、手直しを当て、台帳の 1 行目を <rev> に替え、盤面の手本を
      board-goldens/make.py で撮り直す。写しの .py の import と graph の $ref・extends がたどる物が台帳に無ければ、
      動かなくなるまでたどって同じバイトで写し、頭の当たる最初の台帳に「<版> で足した」の注記つきの行で足し、足した行を出す
      （go mod vendor が推移閉包を解いて modules.txt に書くのと同じ形）。手直しが当たらない・足す物の写し先に、どの台帳にも
      載らない works 自身のファイルが在る、のどちらかなら何も書かずに 1。終わりに、works の中で前の commit を名指しする所を
      出す（書き換えない）
  --works <置き場>（既定はこの道具の在る works）・--upstream <git の置き場>（既定は works を含むリポジトリの根）
"""
import argparse
import ast
import json
import pathlib
import posixpath
import re
import subprocess
import sys

HERE = pathlib.Path(__file__).resolve().parent
WORKS = HERE.parent
sys.dont_write_bytecode = True   # 下の import が pack の中に __pycache__ を作らないように。必ず import より前
sys.path.insert(0, str(WORKS / ".shared" / "core"))
import copyledger  # noqa: E402

# 台帳（works の根から）と、行の写しのパスに足す元のパスの頭。None の台帳は別の系統（行の 2 列目が元のパス）で、sync は触らない
LEDGERS = (
    (".shared/core/COPIED_FROM", ""),
    (".shared/core/gl-prompts/COPIED_FROM", "graphloops/"),
    ("blk-spec/prompts/COPIED_FROM", "graphloops/prompts/review-loop/"),
    ("blk-report/prompts/COPIED_FROM", "graphloops/prompts/"),
    (".shared/core/COPIED_FROM.changemap", None),
)
GRAPH_REFS = ("$ref", "extends")


def git(repo, *args) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, encoding="utf-8",
                          check=True).stdout.strip()


def resolve(repo, rev):
    r = subprocess.run(["git", "-C", str(repo), "rev-parse", "--verify", "--quiet", f"{rev}^{{commit}}"],
                       capture_output=True, text=True, encoding="utf-8")
    return r.stdout.strip() if r.returncode == 0 else None


def source(prefix, rel, src):
    return src if prefix is None else prefix + rel


def check(works, up) -> list:
    out = []
    commits = {}
    for name, prefix in LEDGERS:
        try:
            led = copyledger.read(works / name)
        except (OSError, copyledger.LedgerError) as e:
            out.append(f"{name}: {e}")
            continue
        full = resolve(up, led.commit)
        if full is None:
            out.append(f"{name}: 1 行目の commit {led.commit} を {up} から引けない")
            continue
        if prefix is not None:
            commits[name] = full
        for rel, src in led.rows:
            where = f"{pathlib.PurePosixPath(name).parent / rel}"
            data = copyledger.show(up, full, source(prefix, rel, src))
            if data is None:
                out.append(f"{where}: 元 {led.commit}:{source(prefix, rel, src)} が無い")
                continue
            try:
                want = copyledger.apply(led, rel, data)
            except copyledger.LedgerError as e:
                out.append(f"{where}: {e}")
                continue
            p = led.base / rel
            if not p.is_file() or p.read_bytes() != want:
                out.append(f"{where}: 写しが {led.commit} の元（と台帳の手直し）と違う"
                           f"（直し方: git show {led.commit}:{source(prefix, rel, src)} で戻すか、sync で取り直す）")
    if len(set(commits.values())) > 1:
        first = next(iter(commits.values()))
        for name, c in commits.items():
            if c != first:
                out.append(f"{name}: 1 行目の commit {c[:7]} が {LEDGERS[0][0]} の {first[:7]} と割れている"
                           f"（graphloops を元にする台帳は同じ commit から写す。直し方: sync <rev> で揃える）")
    return out


def _module_paths(src, node):
    """写しの .py の import の先の候補（元の根から）"""
    here = posixpath.dirname(src)
    if isinstance(node, ast.ImportFrom) and node.level:
        base = here
        for _ in range(node.level - 1):
            base = posixpath.dirname(base)
        mods = [f"{node.module}"] if node.module else [a.name for a in node.names]
        return [posixpath.join(base, *m.split(".")) for m in mods]
    names = [node.module] if isinstance(node, ast.ImportFrom) and node.module else \
        [a.name for a in node.names] if isinstance(node, ast.Import) else []
    out = []
    for m in names:
        parts = m.split(".")
        out += [posixpath.join("graphloops", *parts), posixpath.join(here, *parts)]
    return out


def needs(src, data) -> set:
    """写しの 1 本がたどる元のパス（import の先・graph の $ref と extends）"""
    out = set()
    if src.endswith(".py"):
        try:
            tree = ast.parse(data)
        except SyntaxError:
            return out
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                for m in _module_paths(src, node):
                    out |= {m + ".py", m + "/__init__.py"}
    elif src.endswith(".json"):
        try:
            doc = json.loads(data)
        except ValueError:
            return out
        stack = [doc]
        while stack:
            x = stack.pop()
            if isinstance(x, dict):
                for k, v in x.items():
                    if k in GRAPH_REFS and isinstance(v, str):
                        out.add(posixpath.normpath(posixpath.join(posixpath.dirname(src), v)))
                    else:
                        stack.append(v)
            elif isinstance(x, list):
                stack += x
    return out


def exists(up, rev, path) -> bool:
    return subprocess.run(["git", "-C", str(up), "cat-file", "-e", f"{rev}:{path}"], capture_output=True).returncode == 0


def new_head(head, short, version, old):
    """台帳の 1 行目を <short>  graphloops <version>（前の写しは <old>） に替える（版の後ろの説明は残す）"""
    parts = head.split(None, 1)
    rest = re.sub(r"（前の写しは [^）]*）", "", parts[1] if len(parts) > 1 else "")
    tag = f"graphloops {version}（前の写しは {old}）"
    rest, n = re.subn(r"graphloops [0-9][^\s（]*", tag, rest, count=1)
    return f"{short}  {rest if n else (tag + ' ' + rest).rstrip()}"


def sync(works, up, rev, version, skip_goldens) -> int:
    full = resolve(up, rev)
    if full is None:
        print(f"core-sync: {rev} を {up} から引けない", file=sys.stderr)
        return 1
    short = git(up, "rev-parse", "--short=7", full)
    problems, writes, fetched, heads, listed = [], {}, {}, {}, set()
    for name, prefix in LEDGERS:
        led = copyledger.read(works / name)
        listed |= {led.base / rel for rel, _ in led.rows}
        if prefix is None:
            continue
        heads[name] = (led, new_head(led.head, short, version, led.commit))
        for rel, src in led.rows:
            s = source(prefix, rel, src)
            data = copyledger.show(up, full, s)
            if data is None:
                problems.append(f"{name}: {rel} の元 {s} が {short} に無い（台帳の行を直す）")
                continue
            fetched[s] = data
            try:
                writes[led.base / rel] = copyledger.apply(led, rel, data)
            except copyledger.LedgerError as e:
                problems.append(f"{name}: {e}（台帳の手直しの行を {short} の中身に合わせて直す）")
    added = {}   # 台帳の名 → [足す行]
    queue = sorted(fetched.items())
    while queue:
        s, data = queue.pop(0)
        for n in sorted(needs(s, data)):
            if n in fetched or not exists(up, full, n):
                continue
            fetched[n] = copyledger.show(up, full, n)
            queue.append((n, fetched[n]))
            name, prefix = next((nm, px) for nm, px in LEDGERS if px is not None and n.startswith(px))
            led, rel = heads[name][0], n[len(prefix):]
            p = led.base / rel
            if p in writes or (p.exists() and p not in listed):
                problems.append(f"{s} がたどる {n} の写し先 {p.relative_to(works)} に、台帳に無い works のファイルが在る"
                                f"（ぶつかる。どちらを残すかを決めて台帳か works のファイルを直す）")
                continue
            writes[p] = fetched[n]
            how = "import する" if s.endswith(".py") else "$ref・extends でたどる"
            added.setdefault(name, []).append(f"{rel}  # {version} で足した: {s} が {how}")
    if problems:
        print("core-sync: 何も書かずに止めた", file=sys.stderr)
        for p in problems:
            print(f"  {p}", file=sys.stderr)
        return 1
    for p, data in writes.items():
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
    olds = set()
    for name, (led, head) in heads.items():
        olds.add(led.commit)
        lines = led.path.read_text(encoding="utf-8").splitlines(keepends=True)
        lines[0] = head + "\n"
        if lines[-1:] and not lines[-1].endswith("\n"):
            lines[-1] += "\n"
        lines += [a + "\n" for a in added.get(name, ())]
        led.path.write_text("".join(lines), encoding="utf-8")
    print(f"core-sync: {len(writes)} 本を {short}（graphloops {version}）から写した")
    for name, rows in added.items():
        print(f"core-sync: 台帳に無い物を {name} に足した:")
        for a in rows:
            print(f"  {a}")
    if not skip_goldens:
        make = HERE / "board-goldens" / "make.py"
        r = subprocess.run(["uv", "run", str(make), "--graphloops-rev", short])
        if r.returncode != 0:
            print(f"core-sync: 手本の撮り直しが {r.returncode} で落ちた（写しと台帳は書いた。{make} を直して撮り直す）",
                  file=sys.stderr)
            return 1
    olds.discard(short)
    for old in sorted(olds):
        r = subprocess.run(["git", "-C", str(works), "grep", "-n", "-F", old, "--", "."], capture_output=True, text=True,
                           encoding="utf-8")
        if r.stdout.strip():
            print(f"core-sync: 前の commit {old} を名指しする所（手で直すか、履歴なら残す）:")
            print(r.stdout.rstrip())
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--works", default=str(WORKS))
    p.add_argument("--upstream")
    p.add_argument("--check", action="store_true")
    p.add_argument("cmd", nargs="?", choices=["sync"])
    p.add_argument("rev", nargs="?")
    p.add_argument("--version")
    p.add_argument("--skip-goldens", action="store_true")
    a = p.parse_args(argv)
    works = pathlib.Path(a.works).resolve()
    up = pathlib.Path(a.upstream).resolve() if a.upstream else pathlib.Path(git(works, "rev-parse", "--show-toplevel"))
    if a.check == bool(a.cmd):
        p.error("--check か sync <rev> のどちらか 1 つ")
    if a.check:
        bad = check(works, up)
        for b in bad:
            print(b)
        return 1 if bad else 0
    if not a.rev or not a.version:
        p.error("sync は <rev> と --version を取る")
    return sync(works, up, a.rev, a.version, a.skip_goldens)


if __name__ == "__main__":
    for _s in (sys.stdout, sys.stderr):
        if hasattr(_s, "reconfigure"):
            _s.reconfigure(encoding="utf-8")
    sys.exit(main())
