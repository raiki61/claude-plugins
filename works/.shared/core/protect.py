"""守りのファイル: works 自身の試験・柵・受け付けの口の一覧（MANIFEST）と、run の差分がそれに触ったかの機械の確かめ。

ASF の .factory/locks/floor.json に倣う（工場は自分の床を下げない・自分の検査を緩めない。下げるのは人だけ）。自分食いの修正役は
works 自身の試験・柵を書き換えられる（run 24 の修正役は Bash で test_yaml_rules.py を書き換えた）。一覧に当たるファイルを
触った run は、最後の人の関所を final_gate が when_needed でも必ず開き、関所の文の頭に「守りのファイルを触った」を並べる。
通すのは人の continue だけ（ラインの境の節が使う）。差分の審査役にも材料（brief）で見せる（refix.cut）。

一覧は run の作業ツリーでなく、走っている pack の物を読む（修正役が作業ツリーの一覧を空にしても、確かめは緩まない）。
一覧の行のパスはリポジトリの根からの相対（works の元のリポジトリの形）。別のリポジトリの run では、ふつうどの行にも当たらない。

- MANIFEST:            一覧のファイル（これ自身も一覧に入る）
- load(path=None):     一覧を読んで形を確かめる。崩れていれば Broken（黙って空にしない）
- rules(doc):          当てる行（rules と copies）の並び
- match(path, pattern): git の :(glob) と同じ当たり方（** は 0 個以上のフォルダ・* と ? と [..] は / を跨がない）
- hits(paths, doc=None): パスごとに最初に当たった行 [{path, id, glob, why}]（差分を切った後の変わったファイルの一覧に当てる）
- touched(repo, rev, doc=None): 数える版 rev から今の作業ツリーまで（commit・消した物・未追跡を含む）の差分のうち一覧に当たる物と
                       行数 [{path, id, glob, why, added, deleted}]（added・deleted はバイナリ・入れ子の git なら None）
- lines(rows):         関所の文と盤面の問いに載せる 1 行ずつの文
標準ライブラリだけ。git は repo を cwd にして呼ぶ（期限は足さない）。
"""
import json
import pathlib
import re
import subprocess
import sys

sys.dont_write_bytecode = True

_CORE = pathlib.Path(__file__).resolve().parent
if str(_CORE) not in sys.path:
    sys.path.insert(0, str(_CORE))

import accept  # noqa: E402

MANIFEST = _CORE / "protected.json"
RULE_KEYS = {"id", "glob", "why"}
COPY_KEYS = RULE_KEYS | {"made_by"}


class Broken(Exception):
    """一覧が読めない・形が崩れている"""


def _problems(doc) -> list:
    if not isinstance(doc, dict):
        return [f"一覧が JSON のオブジェクトでない（{type(doc).__name__}）"]
    out = []
    rules = doc.get("rules")
    copies = doc.get("copies", [])
    if not isinstance(rules, list) or not rules:
        out.append("rules が空でない配列でない")
        rules = []
    if not isinstance(copies, list):
        out.append("copies が配列でない")
        copies = []
    seen_id, seen_glob = set(), set()
    for kind, rows, keys in (("rules", rules, RULE_KEYS), ("copies", copies, COPY_KEYS)):
        for i, r in enumerate(rows):
            where = f"{kind}[{i}]"
            if not isinstance(r, dict) or set(r) != keys or not all(isinstance(r[k], str) and r[k].strip() for k in keys):
                out.append(f"{where} の鍵が {sorted(keys)} の空でない文字列でない")
                continue
            g = r["glob"]
            if g.startswith("/") or g.endswith("/") or ".." in g.split("/") or "" in g.split("/") or "\\" in g:
                out.append(f"{where} の glob {g!r} はリポジトリの根からの相対のファイルの型でない（/ で始めない・終えない・.. を使わない）")
            if r["id"] in seen_id:
                out.append(f"{where} の id {r['id']!r} が重なる")
            if g in seen_glob:
                out.append(f"{where} の glob {g!r} が重なる")
            seen_id.add(r["id"])
            seen_glob.add(g)
    return out


def load(path=None) -> dict:
    """一覧を読んで形を確かめる。読めない・崩れていれば Broken"""
    p = pathlib.Path(path) if path is not None else MANIFEST
    try:
        doc = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise Broken(f"守りのファイルの一覧 {p} が読めない（{type(e).__name__}: {e}）") from None
    bad = _problems(doc)
    if bad:
        raise Broken(f"守りのファイルの一覧 {p} の形が崩れている: {'／'.join(bad)}")
    return doc


def rules(doc) -> list:
    return list(doc["rules"]) + list(doc.get("copies") or [])


def _segment(seg: str) -> str:
    """1 区切りの型を正規表現に（* と ? と [..] は / を跨がない。[! は否定）"""
    out, i = [], 0
    while i < len(seg):
        c = seg[i]
        k = -1
        if c == "[":
            j = i + 1 + (seg[i + 1:i + 2] == "!")
            j += seg[j:j + 1] == "]"
            k = seg.find("]", j)
        if c == "*":
            out.append("[^/]*")
        elif c == "?":
            out.append("[^/]")
        elif k > 0:
            body = seg[i + 1:k]
            out.append("[" + ("^" + body[1:] if body.startswith("!") else body).replace("\\", "\\\\") + "]")
            i = k
        else:
            out.append(re.escape(c))
        i += 1
    return "".join(out)


def _regex(pattern: str):
    parts = pattern.split("/")
    out = []
    for i, seg in enumerate(parts):
        last = i == len(parts) - 1
        if seg == "**":
            out.append(".*" if last else "(?:[^/]+/)*")
        else:
            out.append(_segment(seg) + ("" if last else "/"))
    return re.compile("".join(out) + r"\Z")


def match(path: str, pattern: str) -> bool:
    return _regex(pattern).match(path) is not None


def hits(paths, doc=None) -> list:
    """パスごとに最初に当たった行（パスの名前の順）。doc が無ければ MANIFEST を読む"""
    doc = load() if doc is None else doc
    rows = rules(doc)
    out = []
    for p in sorted(set(paths)):
        r = next((r for r in rows if match(p, r["glob"])), None)
        if r is not None:
            out.append({"path": p, "id": r["id"], "glob": r["glob"], "why": r["why"]})
    return out


def _git(repo, *args) -> bytes:
    try:
        r = subprocess.run(["git", "-c", "core.quotePath=false", *args], cwd=str(repo), capture_output=True,
                           stdin=subprocess.DEVNULL)
    except OSError as e:
        raise Broken(f"git {' '.join(args)} を呼べない（{e}）") from None
    if r.returncode != 0:
        raise Broken(f"git {' '.join(args)} が失敗した（{r.stderr.decode('utf-8', 'replace').strip()[-300:]}）")
    return r.stdout


def _numstat(repo, rev, names) -> dict:
    """追跡しているファイルの {パス: (足した行, 消した行)}。バイナリは (None, None)"""
    if not names:
        return {}
    raw = _git(repo, "diff", "--numstat", "-z", "--no-renames", "--no-ext-diff", rev, "--",
               *[f":(top,literal){n}" for n in names]).decode("utf-8", "replace")
    out = {}
    for rec in raw.split("\0"):
        if not rec:
            continue
        a, d, name = rec.split("\t", 2)
        out[name] = (None, None) if a == "-" else (int(a), int(d))
    return out


def _new_file_lines(path: pathlib.Path):
    try:
        data = path.read_bytes()
    except OSError:
        return None
    if b"\0" in data[:8000]:
        return None
    return data.count(b"\n") + (0 if not data or data.endswith(b"\n") else 1)


def touched(repo, rev: str, doc=None) -> list:
    """数える版 rev（commit）から今の作業ツリーまでの差分（accept.touched_files と同じ集め方: 追跡の変更・消した物・
    commit した物・未追跡。バイトコードは除く）のうち一覧に当たる物と行数。git が呼べなければ Broken"""
    repo = pathlib.Path(repo)
    try:
        names = accept.touched_files(repo, rev)
    except accept.Reject as e:
        raise Broken(f"差分のファイルを git から引けない: {e}") from None
    found = hits(names, doc)
    stats = _numstat(repo, rev, [r["path"] for r in found if not r["path"].endswith("/")])
    out = []
    for r in found:
        if r["path"] in stats:
            added, deleted = stats[r["path"]]
        else:   # 数える版に無く git diff に載らない物は未追跡（新しいファイル。入れ子の git は sub/ の 1 本で行数なし）
            n = None if r["path"].endswith("/") else _new_file_lines(repo / r["path"])
            added, deleted = (n, 0) if n is not None else (None, None)
        out.append({**r, "added": added, "deleted": deleted})
    return out


def lines(rows) -> list:
    """1 行ずつ: 「<パス>（+足した −消した）: 規則 <id>（<glob>）——<理由>」。行数が無ければ「バイナリか中身の数えられない物」"""
    out = []
    for r in rows:
        stat = f"+{r['added']} −{r['deleted']}" if r.get("added") is not None else "行数なし（バイナリ・フォルダ）"
        out.append(f"{r['path']}（{stat}）: 規則 {r['id']}（{r['glob']}）——{r['why']}")
    return out
