# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""構造の実測（AI なし・名前にも言語にも依らない）。パスの一覧を git の公式の口だけで測り、JSON 1 つを標準出力に出して 0。

    measure.py --paths P [P ...] [--repo DIR] [--since YYYY-MM-DD | --window-days N] [--max-bytes N]

- 行数と伸び: 今の行数と、窓の始まりの commit（`git rev-list -1 --before=<since> HEAD`）の行数とその差。窓の始まりの行数は
  `git log --follow --name-status` の改名の行をたどった、その時の名前で数える
- 変更の頻度: 窓の中の `git log --follow` の回数（主）・`--follow` 無しの回数（素の値）・`--follow` 無しに `--no-merges` を
  掛けた回数をパスごとに出す。複数のパスの和集合は、`--follow` が 1 本のパスにしか効かないので 1 本ずつ集めた commit の和で取り、
  素の値と --no-merges は全部のパスを渡した 1 度の git log で数える
- 浅い clone（`git rev-parse --is-shallow-repository`）では、頻度も伸びも数を出さず「測れない」と書く
- 写しの在りか: 空行を落とし空白を正規化した 6 行の塊のハッシュを、追跡ファイル全体で引く
- 入口の数: ファイルの名を名指す追跡ファイルの数と、そのうち実行できる物（mode 100755）の数
- 環境変数と設定の口: 大文字とアンダースコアの名を集め、一番多い接頭辞を割り出し（同数は辞書順で先の物）、3 つの数え方と
  消す・上書きする所の数を並べる
- 読めない・大きすぎる・追跡されていないパスは、skipped に理由つきで並べて続ける。閾値では止めない（値だけ返す）
"""
import argparse
import datetime
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

SCHEMA = "measure/1"
MAX_BYTES = 1_000_000
WINDOW_DAYS = 90
BLOCK_LINES = 6
UNMEASURABLE = "測れない"
NAME_RE = re.compile(r"(?<![A-Za-z0-9_])[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)+(?![A-Za-z0-9_])")
# 試験と文書と見なす物: この名のフォルダの下か、この拡張子
TEST_DOC_DIRS = frozenset({"test", "tests", "doc", "docs"})
DOC_SUFFIXES = frozenset({".md", ".rst", ".adoc"})
# 読み書きの形（{n} に名が入る）
ACCESS_FORMS = (
    r"\$\{{?{n}(?![A-Za-z0-9_])",
    r"environ\s*\[\s*['\"]{n}['\"]",
    r"environ\.(?:get|pop|setdefault)\(\s*['\"]{n}['\"]",
    r"(?:getenv|putenv|unsetenv|Getenv|Setenv|Unsetenv|env::var)\(\s*['\"]{n}['\"]",
    r"process\.env(?:\.{n}(?![A-Za-z0-9_])|\[\s*['\"]{n}['\"])",
    r"ENV\[\s*['\"]{n}['\"]",
    r"(?m)^\s*(?:export\s+)?{n}=",
    r"\bunset\s+(?:-v\s+)?{n}(?![A-Za-z0-9_])",
)
# 消す・上書きする形（出現の数を数える）
WRITE_FORMS = (
    r"(?m)^\s*(?:export\s+)?{n}=",
    r"\bunset\s+(?:-v\s+)?{n}(?![A-Za-z0-9_])",
    r"environ\s*\[\s*['\"]{n}['\"]\s*\]\s*=(?!=)",
    r"environ\.(?:pop|setdefault)\(\s*['\"]{n}['\"]",
    r"\bdel\s+[\w.]*environ\s*\[\s*['\"]{n}['\"]",
    r"(?:putenv|unsetenv|Setenv|Unsetenv)\(\s*['\"]{n}['\"]",
    r"process\.env\.{n}\s*=(?!=)",
    r"\bdelete\s+process\.env\.{n}(?![A-Za-z0-9_])",
)

RULES = {
    "lines": "改行の数（最後の行に改行が無ければ 1 足す）",
    "growth": "窓の始まりの commit は git rev-list -1 --before=<since> HEAD。その時の名前は窓の中の git log --follow --name-status の"
              "改名（と写し）の行を新しい方からたどって求め、git show <commit>:<その時の名前> の行数を数える。delta は今の行数との差",
    "frequency": "窓の中（--since）の commit の数。follow は git log --follow（git の改名と写しの検出でたどる。マージは出さない）、"
                 "raw は --follow 無し、no_merges は --follow 無しに --no-merges。raw と no_merges の差はそのパスを触るマージの数",
    "union": "follow はパスごとの git log --follow の commit の集合の和（--follow は 1 本のパスにしか効かない）。"
             "raw と no_merges は全部のパスを渡した 1 度の git log",
    "shallow": "git rev-parse --is-shallow-repository が true なら、frequency・union・growth は数を出さず status を測れないにする",
    "duplicates": f"空行を落とし、各行の空白を 1 つに詰めた連続 {BLOCK_LINES} 行の塊の sha1 を、git ls-files の追跡ファイル全体で引く。"
                  "同じ塊の在る自分以外の場所を並べる。言語の文法は見ない",
    "entrypoints": "named_by は自分の外でファイルの名（basename）を文字どおり含む追跡ファイルの数（git grep -l -F -I）。"
                   "executable はそのうち git ls-files -s の mode が 100755 の物",
    "env": "名は測るパスの中の [A-Z][A-Z0-9]*(_[A-Z0-9]+)+。接頭辞は最初の _ までで、異なる名の数が一番多い物。"
           "同数は辞書順で並べ、先の物を top にする。counts の all は名を含む追跡ファイルの数（散らばり）、"
           "excluding_tests_docs はそのうち test・tests・doc・docs のフォルダの下と .md・.rst・.adoc を除いた数、"
           "access は読み書きの形（$NAME・${NAME}・environ・getenv・process.env・NAME= の代入・export・unset など）で"
           "現れるファイルの数。writes は消す・上書きする形（代入・export・unset・environ への代入・pop・del など）の出現の数",
    "skipped": "追跡されていない（untracked）・utf-8 で読めないか NUL を含む（unreadable）・max_bytes を超える（too_large）パスは"
               "測らずに理由つきで並べる。写しと環境変数の数えでは、同じ理由の追跡ファイルを黙って読み飛ばす",
}


class GitError(Exception):
    pass


def git(repo: Path, *args: str, check: bool = True) -> str:
    r = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, encoding="utf-8",
                       errors="replace")
    if check and r.returncode != 0:
        raise GitError(f"git {' '.join(args)}: {r.stderr.strip()}")
    return r.stdout


def count_lines(text: str) -> int:
    return text.count("\n") + (1 if text and not text.endswith("\n") else 0)


def read_text(path: Path, max_bytes: int):
    """(本文, None) か (None, 理由)"""
    try:
        size = path.stat().st_size
        if size > max_bytes:
            return None, "too_large"
        data = path.read_bytes()
    except OSError:
        return None, "unreadable"
    if b"\0" in data:
        return None, "unreadable"
    try:
        return data.decode("utf-8"), None
    except UnicodeDecodeError:
        return None, "unreadable"


def is_shallow(repo: Path) -> bool:
    return git(repo, "rev-parse", "--is-shallow-repository").strip() == "true"


def window_since(repo: Path, since, days: int) -> str:
    """窓の始まりの日付。--since が無ければ HEAD の commit の日時から days 日前（同じ版なら同じ値）"""
    if since:
        return since
    head = datetime.datetime.fromisoformat(git(repo, "log", "-1", "--format=%cI", "HEAD").strip())
    return (head - datetime.timedelta(days=days)).date().isoformat()


def window_base(repo: Path, since: str):
    return git(repo, "rev-list", "-1", f"--before={since}", "HEAD").strip() or None


def commits(repo: Path, since: str, paths, *opts: str) -> list:
    return git(repo, "log", *opts, f"--since={since}", "--format=%H", "--", *paths).split()


def name_at(repo: Path, path: str, base: str) -> str:
    """base の時の path の名前。base より後の改名（と写し）を新しい方からたどる"""
    name = path
    out = git(repo, "log", "--follow", "--name-status", "--format=", f"{base}..HEAD", "--", path)
    for line in out.splitlines():
        cols = line.split("\t")
        if len(cols) == 3 and cols[0][:1] in ("R", "C") and cols[2] == name:
            name = cols[1]
    return name


def growth(repo: Path, path: str, lines: int, base, shallow: bool) -> dict:
    if shallow:
        return {"status": UNMEASURABLE, "reason": "shallow"}
    if base is None:
        return {"status": UNMEASURABLE, "reason": "窓の始まりより前の commit が無い"}
    name = name_at(repo, path, base)
    r = subprocess.run(["git", "-C", str(repo), "show", f"{base}:{name}"], capture_output=True)
    if r.returncode != 0:
        return {"base_name": None, "base_lines": 0, "delta": lines}
    n = count_lines(r.stdout.decode("utf-8", errors="replace"))
    return {"base_name": name, "base_lines": n, "delta": lines - n}


def frequency(repo: Path, path: str, since: str) -> tuple:
    follow = commits(repo, since, [path], "--follow")
    freq = {"follow": len(follow), "raw": len(commits(repo, since, [path])),
            "no_merges": len(commits(repo, since, [path], "--no-merges"))}
    return freq, set(follow)


def blocks(text: str) -> list:
    """(始まりの行番号, 塊のハッシュ) の一覧。空行を落とし、各行の空白を詰める"""
    rows = [(i, " ".join(ln.split())) for i, ln in enumerate(text.splitlines(), 1)]
    rows = [(i, s) for i, s in rows if s]
    out = []
    for k in range(len(rows) - BLOCK_LINES + 1):
        chunk = "\n".join(s for _, s in rows[k:k + BLOCK_LINES])
        out.append((rows[k][0], hashlib.sha1(chunk.encode("utf-8")).hexdigest()))
    return out


def duplicates(path: str, own: list, index: dict) -> list:
    found = set()
    for line, h in own:
        for other, other_line in index.get(h, ()):
            if (other, other_line) != (path, line):
                found.add((line, other, other_line))
    return [{"line": a, "path": b, "other_line": c} for a, b, c in sorted(found)]


def entrypoints(repo: Path, path: str, modes: dict) -> dict:
    name = Path(path).name
    out = git(repo, "grep", "-l", "-z", "-F", "-I", "-e", name, check=False)
    files = sorted(f for f in out.split("\0") if f and f != path)
    return {"named_by": len(files), "executable": sum(1 for f in files if modes.get(f) == "100755")}


def is_test_or_doc(path: str) -> bool:
    p = Path(path)
    return bool(set(p.parts[:-1]) & TEST_DOC_DIRS) or p.suffix.lower() in DOC_SUFFIXES


def env(names: set, texts: dict) -> dict:
    by_prefix = {}
    for n in names:
        by_prefix.setdefault(n.split("_", 1)[0] + "_", set()).add(n)
    top = max((len(v) for v in by_prefix.values()), default=0)
    tied = sorted(p for p, v in by_prefix.items() if len(v) == top)
    report = {}
    for n in sorted(names):
        word = re.compile(r"(?<![A-Za-z0-9_])" + re.escape(n) + r"(?![A-Za-z0-9_])")
        access = [re.compile(f.format(n=re.escape(n))) for f in ACCESS_FORMS]
        writes = [re.compile(f.format(n=re.escape(n))) for f in WRITE_FORMS]
        hit = [f for f, t in texts.items() if word.search(t)]
        report[n] = {
            "counts": {"all": len(hit), "excluding_tests_docs": sum(1 for f in hit if not is_test_or_doc(f)),
                       "access": sum(1 for f in hit if any(a.search(texts[f]) for a in access))},
            "writes": sum(len(w.findall(texts[f])) for f in hit for w in writes),
        }
    return {"prefix": {"top": tied[0] if tied else None, "tied": tied}, "names": report}


def measure(repo: Path, paths: list, since: str, max_bytes: int) -> dict:
    shallow = is_shallow(repo)
    base = window_base(repo, since)
    modes = {}
    for row in git(repo, "ls-files", "-s", "-z").split("\0"):
        if row:
            meta, name = row.split("\t", 1)
            modes[name] = meta.split()[0]
    texts = {}
    for f in sorted(modes):
        if modes[f] in ("100644", "100755"):
            text, _why = read_text(repo / f, max_bytes)
            if text is not None:
                texts[f] = text
    index = {}
    for f, text in texts.items():
        for line, h in blocks(text):
            index.setdefault(h, []).append((f, line))

    measured, skipped, names = [], [], set()
    union_follow = set()
    for p in dict.fromkeys(paths):
        if p not in modes:
            skipped.append({"path": p, "reason": "untracked"})
            continue
        text, why = read_text(repo / p, max_bytes)
        if text is None:
            skipped.append({"path": p, "reason": why})
            continue
        lines = count_lines(text)
        entry = {"path": p, "lines": lines, "growth": growth(repo, p, lines, base, shallow),
                 "duplicates": duplicates(p, blocks(text), index), "entrypoints": entrypoints(repo, p, modes)}
        if shallow:
            entry["frequency"] = {"status": UNMEASURABLE, "reason": "shallow"}
        else:
            entry["frequency"], follow = frequency(repo, p, since)
            union_follow |= follow
        names |= set(NAME_RE.findall(text))
        measured.append(entry)

    kept = [e["path"] for e in measured]
    if shallow:
        union = {"status": UNMEASURABLE, "reason": "shallow"}
    elif kept:
        union = {"follow": len(union_follow), "raw": len(commits(repo, since, kept)),
                 "no_merges": len(commits(repo, since, kept, "--no-merges"))}
    else:
        union = {"follow": 0, "raw": 0, "no_merges": 0}
    return {
        "schema": SCHEMA,
        "rules": dict(RULES, max_bytes=max_bytes, block_lines=BLOCK_LINES),
        "repo_head": git(repo, "rev-parse", "HEAD").strip(),
        "shallow": shallow,
        "window": {"since": since, "base": base},
        "paths": measured,
        "union": union,
        "env": env(names, texts),
        "skipped": skipped,
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="パスの一覧の構造を git で実測し、JSON 1 つを出す")
    ap.add_argument("--paths", nargs="+", required=True, help="測るパス（リポジトリの根から）")
    ap.add_argument("--repo", default=".", help="測るリポジトリ（既定は今のフォルダ）")
    win = ap.add_mutually_exclusive_group()
    win.add_argument("--since", help="窓の始まりの日付（YYYY-MM-DD）")
    win.add_argument("--window-days", type=int, default=WINDOW_DAYS, help="HEAD の日時から遡る窓の日数（既定 90）")
    ap.add_argument("--max-bytes", type=int, default=MAX_BYTES, help="これを超えるファイルは測らない（skipped の too_large）")
    a = ap.parse_args(argv)
    try:
        repo = Path(git(Path(a.repo), "rev-parse", "--show-toplevel").strip())
        out = measure(repo, a.paths, window_since(repo, a.since, a.window_days), a.max_bytes)
    except GitError as e:
        print(f"measure.py: {e}", file=sys.stderr)
        return 1
    print(json.dumps(out, ensure_ascii=False, sort_keys=True, indent=1))
    return 0


if __name__ == "__main__":
    for _s in (sys.stdout, sys.stderr):   # Windows の既定 cp1252 で日本語の出力が落ちないように
        if hasattr(_s, "reconfigure"):
            _s.reconfigure(encoding="utf-8")
    sys.exit(main())
