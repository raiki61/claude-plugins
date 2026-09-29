# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""構造の実測（AI なし・名前にも言語にも依らない）。パスの一覧を git の公式の口だけで測り、JSON 1 つを標準出力に出して 0。

    measure.py --paths P [P ...] [--repo DIR] [--since YYYY-MM-DD | --window-days N] [--max-bytes N] [--diff FILE]

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
- 差分の形（--diff）: 案の patch を一時の後の像に当てて前後の増減を出し、新しい名の現れる場所を並べる。名の一覧なら場所だけ
"""
import argparse
import datetime
import hashlib
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

SCHEMA = "measure/1"
MAX_BYTES = 1_000_000
WINDOW_DAYS = 90
BLOCK_LINES = 6
UNMEASURABLE = "測れない"
NAME_RE = re.compile(r"(?<![A-Za-z0-9_])[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)+(?![A-Za-z0-9_])")
TEST_DOC_DIRS = frozenset({"test", "tests", "doc", "docs"})
DOC_SUFFIXES = frozenset({".md", ".rst", ".adoc"})
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
DIFF_RULE = ("--diff のファイルは、diff --git で始まる行が在るか、--- の行の次の行が +++ なら patch、そうでなければ名の一覧"
             "（1 行 1 名。前後の空白を落とし、空行と重複を捨てる）。patch の後の像は、追跡ファイルのうち mode 100644・100755 の物を"
             "作業ツリーの今の中身のまま一時の場所に写し、git init・git add -A -f・git apply・git add -A -f で作る"
             "（対象のリポジトリには何も当てない。当てられなければ git apply の理由で止まる）。touched は git apply --numstat のパス。"
             "paths は --paths と touched の各パスの lines・duplicates の件数・entrypoints を前の像と後の像で同じ数え方で数え、"
             "before・after・delta を並べる（無い側は null、delta も null）。env は測るパスの名と新しい名について env の数え方を前後の像に"
             "1 度ずつ掛けた物。frequency・growth・union は履歴に依るので測り直さない。新しい名は patch の + の行（+++ の行を除く）の"
             "名のうち前の像のどの追跡ファイルにも語として現れない物、名の一覧なら一覧の名そのもの。sites は後の像（名の一覧なら今の木）の"
             "追跡ファイルで名が語として現れる行で、access はその行が読み書きの形に当たるか。access_files は access の在るファイル。"
             "prefix_readers は前の像で同じ接頭辞の別の名を読み書きの形で読むファイル。prior_readers は access_files のうち prefix_readers に"
             "在る物。名の一覧の時は kind と names だけを出す")


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


def word_re(name: str):
    return re.compile(r"(?<![A-Za-z0-9_])" + re.escape(name) + r"(?![A-Za-z0-9_])")


def access_res(name: str) -> list:
    return [re.compile(f.format(n=re.escape(name))) for f in ACCESS_FORMS]


def env(names: set, texts: dict) -> dict:
    by_prefix = {}
    for n in names:
        by_prefix.setdefault(n.split("_", 1)[0] + "_", set()).add(n)
    top = max((len(v) for v in by_prefix.values()), default=0)
    tied = sorted(p for p, v in by_prefix.items() if len(v) == top)
    report = {}
    for n in sorted(names):
        word, access = word_re(n), access_res(n)
        writes = [re.compile(f.format(n=re.escape(n))) for f in WRITE_FORMS]
        hit = [f for f, t in texts.items() if word.search(t)]
        report[n] = {
            "counts": {"all": len(hit), "excluding_tests_docs": sum(1 for f in hit if not is_test_or_doc(f)),
                       "access": sum(1 for f in hit if any(a.search(texts[f]) for a in access))},
            "writes": sum(len(w.findall(texts[f])) for f in hit for w in writes),
        }
    return {"prefix": {"top": tied[0] if tied else None, "tied": tied}, "names": report}


def scan_tree(repo: Path, max_bytes: int) -> dict:
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
    return {"modes": modes, "texts": texts, "index": index}


def static_entry(repo: Path, path: str, tree: dict, max_bytes: int) -> tuple:
    if path not in tree["modes"]:
        return None, "untracked"
    text, why = read_text(repo / path, max_bytes)
    if text is None:
        return None, why
    return {"lines": count_lines(text), "duplicates": duplicates(path, blocks(text), tree["index"]),
            "entrypoints": entrypoints(repo, path, tree["modes"])}, text


def read_diff_input(text: str) -> tuple:
    rows = text.splitlines()
    if any(r.startswith("diff --git ") for r in rows) or any(
            a.startswith("--- ") and b.startswith("+++ ") for a, b in zip(rows, rows[1:])):
        return "patch", None
    return "names", list(dict.fromkeys(r.strip() for r in rows if r.strip()))


def after_image(repo: Path, modes: dict, patch_path: Path, tmp: Path) -> list:
    git(tmp, "init", "-q")
    for f, mode in modes.items():
        src = repo / f
        if mode in ("100644", "100755") and src.is_file():
            dst = tmp / f
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(src, dst)
            if mode == "100755":
                dst.chmod(0o755)
    git(tmp, "add", "-A", "-f")
    touched = []
    rows = git(tmp, "apply", "--numstat", "-z", str(patch_path)).split("\0")
    i = 0
    while i < len(rows):
        cols = rows[i].split("\t")
        if len(cols) == 3 and cols[2]:
            touched.append(cols[2])
        elif len(cols) == 3 and i + 2 < len(rows):
            touched += [rows[i + 1], rows[i + 2]]
            i += 2
        i += 1
    git(tmp, "apply", str(patch_path))
    git(tmp, "add", "-A", "-f")
    return list(dict.fromkeys(touched))


def new_names(patch_text: str, before_texts: dict) -> list:
    added = "\n".join(r[1:] for r in patch_text.splitlines() if r.startswith("+") and not r.startswith("+++ "))
    fresh = []
    for n in dict.fromkeys(NAME_RE.findall(added)):
        word = word_re(n)
        if not any(word.search(t) for t in before_texts.values()):
            fresh.append(n)
    return fresh


def name_sites(name: str, texts: dict, before_texts: dict) -> dict:
    word, access = word_re(name), access_res(name)
    sites = []
    for f in sorted(texts):
        for i, row in enumerate(texts[f].splitlines(), 1):
            if word.search(row):
                sites.append({"path": f, "line": i, "access": any(a.search(row) for a in access)})
    access_files = sorted({s["path"] for s in sites if s["access"]})
    prefix = name.split("_", 1)[0] + "_"
    readers = []
    for f in sorted(before_texts):
        others = {n for n in NAME_RE.findall(before_texts[f]) if n.startswith(prefix) and n != name}
        if any(a.search(before_texts[f]) for n in sorted(others) for a in access_res(n)):
            readers.append(f)
    return {"name": name, "sites": sites, "access_files": access_files, "prefix_readers": readers,
            "prior_readers": [f for f in access_files if f in readers]}


def pair(before, after) -> dict:
    return {"before": before, "after": after,
            "delta": None if before is None or after is None else after - before}


def counts(entry) -> dict:
    if entry is None:
        return {}
    return {"lines": entry["lines"], "duplicates": len(entry["duplicates"]), **entry["entrypoints"]}


def diff_entry(path: str, before, after) -> dict:
    b, a = counts(before), counts(after)
    return {"path": path, "lines": pair(b.get("lines"), a.get("lines")),
            "duplicates": pair(b.get("duplicates"), a.get("duplicates")),
            "entrypoints": {k: pair(b.get(k), a.get(k)) for k in ("named_by", "executable")}}


def diff_section(repo: Path, paths: list, tree: dict, diff: tuple, max_bytes: int) -> dict:
    kind, payload = diff
    if kind == "names":
        return {"kind": "names", "names": [name_sites(n, tree["texts"], tree["texts"]) for n in payload]}
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        touched = after_image(repo, tree["modes"], payload, tmp)
        after = scan_tree(tmp, max_bytes)
        entries, names = [], set()
        for p in dict.fromkeys([*paths, *touched]):
            b, _ = static_entry(repo, p, tree, max_bytes)
            a, _ = static_entry(tmp, p, after, max_bytes)
            entries.append(diff_entry(p, b, a))
            for texts in (tree["texts"], after["texts"]):
                names |= set(NAME_RE.findall(texts.get(p, "")))
    fresh = new_names(payload.read_text(encoding="utf-8"), tree["texts"])
    names |= set(fresh)
    return {"kind": "patch", "touched": touched, "paths": entries,
            "env": {"before": env(names, tree["texts"]), "after": env(names, after["texts"])},
            "names": [name_sites(n, after["texts"], tree["texts"]) for n in fresh]}


def measure(repo: Path, paths: list, since: str, max_bytes: int, diff=None) -> dict:
    shallow = is_shallow(repo)
    base = window_base(repo, since)
    tree = scan_tree(repo, max_bytes)

    measured, skipped, names = [], [], set()
    union_follow = set()
    for p in dict.fromkeys(paths):
        static, text = static_entry(repo, p, tree, max_bytes)
        if static is None:
            skipped.append({"path": p, "reason": text})
            continue
        entry = {"path": p, "growth": growth(repo, p, static["lines"], base, shallow), **static}
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
    out = {
        "schema": SCHEMA,
        "rules": dict(RULES, max_bytes=max_bytes, block_lines=BLOCK_LINES),
        "repo_head": git(repo, "rev-parse", "HEAD").strip(),
        "shallow": shallow,
        "window": {"since": since, "base": base},
        "paths": measured,
        "union": union,
        "env": env(names, tree["texts"]),
        "skipped": skipped,
    }
    if diff is not None:
        out["rules"]["diff"] = DIFF_RULE
        out["diff"] = diff_section(repo, list(dict.fromkeys(paths)), tree, diff, max_bytes)
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="パスの一覧の構造を git で実測し、JSON 1 つを出す")
    ap.add_argument("--paths", nargs="+", required=True, help="測るパス（リポジトリの根から）")
    ap.add_argument("--repo", default=".", help="測るリポジトリ（既定は今のフォルダ）")
    win = ap.add_mutually_exclusive_group()
    win.add_argument("--since", help="窓の始まりの日付（YYYY-MM-DD）")
    win.add_argument("--window-days", type=int, default=WINDOW_DAYS, help="HEAD の日時から遡る窓の日数（既定 90）")
    ap.add_argument("--max-bytes", type=int, default=MAX_BYTES, help="これを超えるファイルは測らない（skipped の too_large）")
    ap.add_argument("--diff", help="案の patch（git の unified diff）か、新しく足す名の一覧（1 行 1 名）のファイル")
    a = ap.parse_args(argv)
    diff = None
    if a.diff:
        patch = Path(a.diff).resolve()
        try:
            kind, names = read_diff_input(patch.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError) as e:
            print(f"measure.py: --diff: {e}", file=sys.stderr)
            return 1
        diff = (kind, patch if kind == "patch" else names)
    try:
        repo = Path(git(Path(a.repo), "rev-parse", "--show-toplevel").strip())
        out = measure(repo, a.paths, window_since(repo, a.since, a.window_days), a.max_bytes, diff)
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
