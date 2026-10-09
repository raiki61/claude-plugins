"""波及の一覧（設計 docs/plans/2026-10-06-tree-line.md の 2.3 の 1。機械）。

修正案の項目が変える名（単位の key の `+` の後から `:` までの ASCII の名と、項目の adds の名の ASCII の語のうち、対象に在る物）を
`git grep -n -w` で引き、当たりを本体（呼び出し元・文書）と試験に分ける。Python の試験は当たりを含む試験の関数の id
（`path::Class::test_x`。ast）まで引き、試験でない関数・ほかの言語はファイルと行（`path:line`）。当たりを項目の allowed_paths
（glob）・tests と rewrite_tests の id とそのファイルに照らし、覆っていない当たりに項目ごとの id（h1・h2…）を振って名指す。
試験の id・パス・試験の名（test_・Test で始まる）は変える名に数えず、呼び出し元でない文書と生成物（NON_CODE_DIRS・
NON_CODE_FILES）の当たりは捨てる（run 68f35d6b: adds の試験の id の断片 works・tests・test_report・HeadCase と、設計書の行が
覆っていない当たりの大半で、下請けが全部 no_effect と答えていた）。
当たりのファイルが多い名（COMMON_FILES を超える）は数だけを載せ、覆っていない当たりに入れない（下請けが判断する。持ち主の決定
2026-10-06）。2 つ以上の項目の allowed_paths・当たりに出たファイルを「項目どうしの重なり」として並べる（相乗りの審査が読む）。

- names(unit_keys, adds)・build(repo, fields, common_files=)・for_units(repo, unit_keys)・uncovered(doc, n):
  一覧を作る・読む（fields は盤面の plan-fields.json の項目の欄の並び。planmarks.split の形）
- section(doc, n=None)・units_section(doc): 指示書に貼る節

例外で止めない: git が無い・リポジトリでない時は一覧の error に理由を書き、項目の行を持たない（受け付けは答えを求めない）。
"""
from __future__ import annotations

import ast
import pathlib
import re
import subprocess
import sys

_CORE = pathlib.Path(__file__).resolve().parents[2] / ".shared" / "core"
if str(_CORE) not in sys.path:
    sys.path.insert(0, str(_CORE))

import impact  # noqa: E402  （.shared/core。テストのファイルの名の慣習 is_test の正本）
import planmarks  # noqa: E402

# 当たりのファイルがこの数を超える名は数だけ（run 195g の一番広い本物の波及は edge.py の入力の組を共有する 17 の節と試験で、
# それは全部並べる。境は段 1 の run の当たりの数を見て直す。設計の 7 の 3）
COMMON_FILES = 25
_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_TEST_NAME = re.compile(r"^(test_|Test[A-Z_])")   # 試験の関数・クラスの名（足す試験の名で、呼び出し元を引く名でない）
# 呼び出し元でない文書と生成物（当たりに数えない小さな一覧）: 設計書・古い文書の置き場（段の並びがパスのどこに在っても）と、
# Archon の pack の写し（.archon/。dogfood が作り直す物）。README など振る舞いを書く文書は契約のずれの元なので数える
_FILE_EXT = re.compile(r"\.(py|md|json|ya?ml|sh|js|ts|toml|txt)$")   # adds のファイルの名（変える名でない）
NON_CODE_DIRS = (("docs", "plans"), ("docs-archive",), (".archon",))   # パスの段の並び（パスのどこに在っても）
NON_CODE_FILES = ("CHANGELOG.md", "HANDOFF.md")
HEAD = "## 波及の一覧（機械が git grep で引いた。項目が変える名の呼び出し元と試験）"
UNITS_HEAD = "## 波及の一覧（機械が git grep で引いた。単位の key が名指す名の呼び出し元と試験。案を書く前に読め）"
SCOPE_ASK = ("覆っていない当たりは、項目の書いてよいパス（allowed_paths）・受け入れの試験（tests）・書き換える試験（rewrite_tests）の"
             "どれにも入っていない当たり。直しが触る物（呼び出し元を合わせる・字のままの値を断言する試験を書き換える）は、今その項目の"
             "allowed_paths か rewrite_tests に入れよ。案に入れた物は修正の時に範囲の相談なしで書ける（範囲の外は修正役が計画役に"
             "相談して許しを得る道しか無い）。触らない物は入れない（事前審査が当たりごとに、覆っている・影響しない・穴のどれかを確かめる）。")
COMMON_NOTE = "当たりのファイルが多い名（数だけ。呼び出し元を全部は並べない。直しが触るかは読んで決めよ）"
ERROR_NOTE = "波及の一覧を作れなかった（{error}）。呼び出し元と試験は自分で引け"


def names(unit_keys, adds) -> list[str]:
    """変える名の候補（現れた順・重なりは 1 つ）: 単位の key の `+` の後から `:` までの ASCII の名と、adds の名の ASCII の語。
    adds の試験の id（`::` を含む）・パス（`/` を含むかファイルの拡張子 _FILE_EXT で終わる）は丸ごと飛ばし、試験の名（_TEST_NAME）は数えない"""
    out = []
    for k in unit_keys or []:
        if isinstance(k, str) and "+" in k:
            out += _NAME.findall(k.split("+", 1)[1].split(":", 1)[0])
    for a in adds or []:
        if isinstance(a, str) and not ("::" in a or "/" in a or _FILE_EXT.search(a)):
            out += _NAME.findall(a)
    return list(dict.fromkeys(n for n in out if len(n) >= 3 and not _TEST_NAME.match(n)))


def non_code(path: str) -> bool:
    """呼び出し元でない文書・生成物のパスか（NON_CODE_DIRS の並びがパスのどこかに在る・名が NON_CODE_FILES）"""
    parts = pathlib.PurePosixPath(path).parts
    dirs = parts[:-1]
    return (any(dirs[i:i + len(seq)] == seq for seq in NON_CODE_DIRS for i in range(len(dirs)))
            or (parts[-1] if parts else "") in NON_CODE_FILES)


def _git_grep(repo: pathlib.Path, name: str) -> list[tuple[str, int]]:
    p = subprocess.run(["git", "-C", str(repo), "grep", "-n", "-w", "-I", "-F", "-e", name],
                       capture_output=True, text=True, encoding="utf-8", errors="replace", stdin=subprocess.DEVNULL)
    if p.returncode not in (0, 1):
        raise OSError(p.stderr.strip() or f"git grep が {p.returncode} で落ちた")
    out = []
    for line in p.stdout.splitlines():
        parts = line.split(":", 2)
        if len(parts) >= 2 and parts[1].isdigit() and not non_code(parts[0]):
            out.append((parts[0], int(parts[1])))
    return out


def is_test(path: str) -> bool:
    """試験の側のファイルか（テストのモジュールか、テストのフォルダの下の支え。名の慣習は impact.is_test の 1 か所）"""
    return impact.is_test(path) is not None


def _test_id(repo: pathlib.Path, path: str, line: int, cache: dict) -> str:
    """当たりの行を含む試験の関数の id（.py の test で始まる関数。クラスの中ならクラスも）。引けなければ path:line"""
    if path.endswith(".py"):
        if path not in cache:
            try:
                cache[path] = ast.parse((repo / path).read_text(encoding="utf-8"))
            except (OSError, SyntaxError, UnicodeDecodeError, ValueError):
                cache[path] = None
        tree = cache[path]
        if tree is not None:
            best = None
            for owner in [tree, *(n for n in ast.walk(tree) if isinstance(n, ast.ClassDef))]:
                for fn in owner.body:
                    if (isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)) and fn.name.startswith("test")
                            and fn.lineno <= line <= (fn.end_lineno or fn.lineno)):
                        best = f"{path}::{owner.name}::{fn.name}" if isinstance(owner, ast.ClassDef) else f"{path}::{fn.name}"
            if best:
                return best
    return f"{path}:{line}"


def _name_row(repo: pathlib.Path, name: str, common_files: int, cache: dict) -> dict | None:
    hits = _git_grep(repo, name)
    if not hits:
        return None
    files = sorted({p for p, _ in hits})
    row = {"name": name, "files": len(files), "common": len(files) > common_files, "code": [], "tests": []}
    if row["common"]:
        return row
    for path, line in hits:
        if is_test(path):
            tid = _test_id(repo, path, line, cache)
            if tid not in row["tests"]:
                row["tests"].append(tid)
        else:
            row["code"].append(f"{path}:{line}")
    return row


def _path_of(at: str) -> str:
    return at.split("::", 1)[0] if "::" in at else at.rsplit(":", 1)[0]


def _covered(f: dict, kind: str, at: str) -> bool:
    path = _path_of(at)
    ids = {r.get("id") for key in ("tests", "rewrite_tests") for r in f.get(key) or [] if isinstance(r, dict)}
    if kind == "test" and "::" in at:
        return at in ids
    if path in planmarks.test_paths(f):
        return True
    return any(isinstance(g, str) and planmarks.glob_match(path, g) for g in f.get("allowed_paths") or [])


def _item(repo: pathlib.Path, n: int, f: dict, common_files: int, cache: dict) -> dict:
    rows = [r for r in (_name_row(repo, nm, common_files, cache) for nm in names(f.get("unit_keys"), f.get("adds")))
            if r is not None]
    out, seen = [], set()
    for r in rows:
        for kind, key in (("code", "code"), ("test", "tests")):
            for at in r[key]:
                if (kind, at) in seen or _covered(f, kind, at):
                    continue
                seen.add((kind, at))
                out.append({"id": f"h{len(out) + 1}", "name": r["name"], "kind": kind, "at": at})
    return {"item": n, "unit_keys": list(f.get("unit_keys") or []), "names": rows, "uncovered": out}


def _overlaps(fields: list, items: list) -> list[dict]:
    seen: dict[str, list] = {}
    for f, it in zip(fields, items):
        paths = {g for g in f.get("allowed_paths") or [] if isinstance(g, str) and not any(c in g for c in "*?[")}
        paths |= {_path_of(at) for r in it["names"] for key in ("code", "tests") for at in r[key]}
        for p in paths:
            seen.setdefault(p, []).append(it["item"])
    return [{"at": p, "items": sorted(set(ns))} for p, ns in sorted(seen.items()) if len(set(ns)) >= 2]


def build(repo, fields: list, *, common_files: int = COMMON_FILES) -> dict:
    """項目ごとの波及の一覧 {"items": [{item, unit_keys, names, uncovered}], "overlaps": [{at, items}], "error": ""}。
    fields は項目の欄の並び（番号は 1 始まりの並びの順）。git が引けなければ items は空で error に理由"""
    repo = pathlib.Path(repo)
    rows = [f if isinstance(f, dict) else {} for f in fields or []]
    cache: dict = {}
    try:
        items = [_item(repo, n, f, common_files, cache) for n, f in enumerate(rows, 1)]
    except OSError as e:
        return {"items": [], "overlaps": [], "error": str(e) or type(e).__name__}
    return {"items": items, "overlaps": _overlaps(rows, items), "error": ""}


def for_units(repo, unit_keys: list, *, common_files: int = COMMON_FILES) -> dict:
    """案の前の一覧 {"units": [{unit_key, names}], "error": ""}（照らす範囲が無いので覆っていない当たりを持たない）"""
    repo = pathlib.Path(repo)
    cache: dict = {}
    try:
        units = [{"unit_key": k, "names": [r for r in (_name_row(repo, nm, common_files, cache) for nm in names([k], []))
                                           if r is not None]} for k in unit_keys or [] if isinstance(k, str)]
    except OSError as e:
        return {"units": [], "error": str(e) or type(e).__name__}
    return {"units": units, "error": ""}


def uncovered(doc: dict, n: int) -> list[dict]:
    """項目 n（1 始まり）の覆っていない当たり（一覧に項目が無ければ []）"""
    for it in (doc or {}).get("items") or []:
        if it.get("item") == n:
            return list(it.get("uncovered") or [])
    return []


def _names_text(rows: list) -> list[str]:
    out = []
    for r in rows:
        if r.get("common"):
            out.append(f"- {r['name']}: 当たり {r['files']} ファイル（{COMMON_NOTE}）")
            continue
        out.append(f"- {r['name']}: 当たり {r['files']} ファイル")
        out += [f"  - 本体 {at}" for at in r.get("code") or []]
        out += [f"  - 試験 {at}" for at in r.get("tests") or []]
    return out


def item_text(doc: dict, n: int) -> str:
    it = next((x for x in (doc or {}).get("items") or [] if x.get("item") == n), None)
    if it is None:
        return f"### 項目 {n}\n\n変える名は対象に見つからなかった（当たり無し）"
    lines = [f"### 項目 {n}（unit_keys: {'、'.join(map(str, it['unit_keys']))}）", "", "変える名と当たり:"]
    lines += _names_text(it["names"]) or ["- 対象に在る名が無い"]
    lines += ["", "覆っていない当たり:"]
    lines += [f"- {h['id']}: {h['kind']} {h['at']}（名 {h['name']}）" for h in it["uncovered"]] or ["- 無い"]
    return "\n".join(lines)


def section(doc: dict, n: int | None = None) -> str:
    """指示書に貼る節（n なら項目 n だけ。無ければ全部の項目と重なりと SCOPE_ASK）"""
    if (doc or {}).get("error"):
        return f"{HEAD}\n\n" + ERROR_NOTE.format(error=doc["error"])
    items = [x["item"] for x in doc.get("items") or []]
    if n is not None:
        return f"{HEAD}\n\n{item_text(doc, n)}"
    parts = [HEAD, SCOPE_ASK, *(item_text(doc, k) for k in items)]
    if doc.get("overlaps"):
        parts.append("項目どうしの重なり（2 つ以上の項目の範囲・当たりに出たファイル）:\n"
                     + "\n".join(f"- {o['at']}: 項目 {', '.join(map(str, o['items']))}" for o in doc["overlaps"]))
    return "\n\n".join(parts)


def units_section(doc: dict) -> str:
    """修正案の役の指示書に貼る節（単位ごと）"""
    if (doc or {}).get("error"):
        return f"{UNITS_HEAD}\n\n" + ERROR_NOTE.format(error=doc["error"])
    parts = [UNITS_HEAD, SCOPE_ASK]
    for u in doc.get("units") or []:
        parts.append("\n".join([f"### 単位 {u['unit_key']}", *(_names_text(u["names"]) or ["- 対象に在る名が無い"])]))
    return "\n\n".join(parts)
