#!/usr/bin/env python3
"""小さな Workflow（DW）の間の受け渡しの台本。今の DW は世界の解（attention/workflows/dig-world.js）の 1 本だけ。

使い方（PR の作業場〔cwd〕で打つ）:
  steps-prep.py --next world <PR 番号> --record <重い版の記録.json> [--lang Japanese] [--caller <起動の合図>]
      世界の解の DW の args を組み、<git の共通の dir>/attention/my-turn/<PR>-steps/world-args.json に書く。
      依頼の行・目的・手段は、重い版の記録（版 3）の structure.mechanisms・purpose.purpose・purpose.means から写す。
      lines と purpose の DW がまだ無いので、--record は要る（無ければ止める）。依存の一覧は、記録の head の
      マニフェストとロックファイルから機械が取る。
  steps-prep.py --save world <PR 番号> <Workflow の出力のファイル>
      DW の返りの形を照合してから <PR>-steps/world.json に書く。外れたら書かずに止める。

出力は JSON 1 つ。終了の値は、続けてよいとき 0、止めるとき 1（ok: false）、使い方の誤りは 2。
設計は attention/docs/small-workflows-design.md の 2.2・3.2・8.1。
"""

import argparse
import json
import os
import posixpath
import re
import subprocess
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "steps", "world", "copied"))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "lib"))
import atomic  # noqa: E402 — 書きかけを残さない書き方。/catchup と共用
from fnv import fnv32  # noqa: E402 — Workflow の fnv と同じ値
import excerpts  # noqa: E402 — 依頼の行の識別子の取り出し（工場の excerpts.banned_tokens の字のままの写し）

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

# dig-world.js の CALLERS と、sum を掛けるキー（SUM_KEYS）と同じ値
CALLERS = ["attention:check-world"]
SUM_KEYS = ["lines", "purpose", "means", "deps", "deps_note", "lang", "own_names"]
CODE_EXT = (".py", ".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs")


class Stop(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code
        self.message = message


def git(*args):
    try:
        r = subprocess.run(["git", *args], capture_output=True, encoding="utf-8", errors="replace", timeout=120)
    except (OSError, subprocess.TimeoutExpired):
        return -1, ""
    return r.returncode, r.stdout


def must_git(*args):
    rc, out = git(*args)
    if rc != 0:
        raise Stop("git-failed", "git %s が失敗しました。PR の作業場で打ってください" % " ".join(args[:2]))
    return out


def show(head, path):
    rc, out = git("show", "%s:%s" % (head, path))
    return out if rc == 0 else None


def args_sum(args):
    """dig-world.js の sumOf と同じ値（キーで並べ、U+0080 から上を \\uXXXX にした JSON の FNV）"""
    picked = {k: args.get(k) for k in SUM_KEYS}
    return fnv32(json.dumps(picked, sort_keys=True, ensure_ascii=True, separators=(",", ":")))


def steps_dir(pr):
    common = must_git("rev-parse", "--git-common-dir").strip()
    return os.path.join(os.path.realpath(common), "attention", "my-turn", "%s-steps" % pr)


def write_json(path, val):
    """書きかけのファイルを残さずに書く（lib/atomic.py）"""
    atomic.write_text(path, json.dumps(val, ensure_ascii=False, indent=1) + "\n")


# ---- 依存の一覧（設計の 3.2）----
# TOML を読む口（tomllib）は Python 3.11 からで、attention の台本は 3.9 で動かす（scripts/run-python.sh）ので、
# 要る所（[project] の dependencies の配列と、uv.lock の [[package]] の name・version・source）だけを読む

def norm(name):
    """名前の照合の形（PEP 503 の正規化。npm の名もこれで比べる）"""
    return re.sub(r"[-_.]+", "-", name).lower()


def toml_section(text, header):
    """[header] の本文（次の [ の行まで）"""
    m = re.search(r"(?m)^\[%s\]\s*$" % re.escape(header), text)
    if not m:
        return ""
    rest = text[m.end():]
    n = re.search(r"(?m)^\[", rest)
    return rest[:n.start()] if n else rest


def toml_strings(body, key):
    """key = [ "...", ... ] の文字列の配列（複数行でも）"""
    m = re.search(r"(?m)^%s\s*=\s*\[" % re.escape(key), body)
    if not m:
        return []
    depth, i, out, cur, quote = 1, m.end(), [], None, None
    while i < len(body) and depth:
        ch = body[i]
        if quote:
            if ch == "\\" and quote == '"':
                cur.append(body[i + 1] if i + 1 < len(body) else "")
                i += 2
                continue
            if ch == quote:
                out.append("".join(cur))
                quote, cur = None, None
            else:
                cur.append(ch)
        elif ch in "\"'":
            quote, cur = ch, []
        elif ch == "#":
            while i < len(body) and body[i] != "\n":
                i += 1
        elif ch == "[":
            depth += 1
        elif ch == "]":
            depth -= 1
        i += 1
    return out


PEP508 = re.compile(r"^\s*([A-Za-z0-9][A-Za-z0-9._-]*)\s*(?:\[[^\]]*\])?\s*(.*)$")


def py_deps(text):
    """pyproject.toml の [project] の dependencies。(名, 版か None, 指定の文)"""
    out = []
    for spec in toml_strings(toml_section(text, "project"), "dependencies"):
        m = PEP508.match(spec)
        if not m:
            continue
        rest = m.group(2).split(";")[0].strip()
        pin = re.match(r"^===?\s*([^,\s]+)$", rest)
        out.append((m.group(1), pin.group(1) if pin else None, rest))
    return out


def uv_lock(text):
    """uv.lock の [[package]]。{正規化の名: (版, 自前か)}。自前は source が editable・virtual・workspace の物"""
    out = {}
    for block in re.split(r"(?m)^\[\[package\]\]\s*$", text)[1:]:
        block = re.split(r"(?m)^\[", block)[0]
        name = re.search(r'(?m)^name\s*=\s*"([^"]+)"', block)
        ver = re.search(r'(?m)^version\s*=\s*"([^"]+)"', block)
        src = re.search(r"(?m)^source\s*=\s*\{([^}]*)\}", block)
        if name:
            own = bool(src and re.search(r"\b(editable|virtual|workspace)\s*=", src.group(1)))
            out[norm(name.group(1))] = (ver.group(1) if ver else None, own)
    return out


def npm_deps(text):
    try:
        d = json.loads(text)
    except ValueError:
        return []
    deps = d.get("dependencies") if isinstance(d, dict) else None
    return [(k, v) for k, v in (deps or {}).items() if isinstance(k, str) and isinstance(v, str)]


def npm_lock(text):
    try:
        d = json.loads(text)
    except ValueError:
        return {}
    pk = d.get("packages") if isinstance(d, dict) else None
    out = {}
    for k, v in (pk or {}).items():
        if k.startswith("node_modules/") and isinstance(v, dict) and isinstance(v.get("version"), str):
            out.setdefault(k[len("node_modules/"):], v["version"])
    return out


def nearest(files, start, names):
    """start（フォルダ）から上へ、names のどれかの在る最初のフォルダの (フォルダ, 名)。無ければ None"""
    d = start
    while True:
        for n in names:
            p = posixpath.join(d, n) if d else n
            if p in files:
                return p
        if not d:
            return None
        d = posixpath.dirname(d)


def import_names(text, path):
    """変えたコードのファイルが import している頭の名（Python はモジュール、JS は包みの名）"""
    if path.endswith(".py"):
        return {m.group(2) for m in re.finditer(r"(?m)^\s*(from|import)\s+([A-Za-z0-9_]+)", text)}
    out = set()
    for m in re.finditer(r"""(?:from|import|require\()\s*['"]([^'"./][^'"]*)['"]""", text):
        spec = m.group(1)
        parts = spec.split("/")
        out.add("/".join(parts[:2]) if spec.startswith("@") else parts[0])
    return out


def collect_deps(head, touched):
    """(依存の一覧, deps_note)"""
    files = set(must_git("ls-tree", "-r", "--name-only", head).splitlines())
    manifests = sorted(p for p in files if posixpath.basename(p) in ("pyproject.toml", "package.json")
                       and "node_modules/" not in p)
    near = sorted({m for t in touched for m in [nearest(files, posixpath.dirname(t), ["pyproject.toml"]),
                                                  nearest(files, posixpath.dirname(t), ["package.json"])] if m})

    def read(manifest_list):
        rows = []
        for m in manifest_list:
            text = show(head, m) or ""
            d = posixpath.dirname(m)
            if m.endswith("pyproject.toml"):
                lockp = nearest(files, d, ["uv.lock"])
                lock = uv_lock(show(head, lockp) or "") if lockp else {}
                for name, pin, _ in py_deps(text):
                    ver, own = lock.get(norm(name), (None, False))
                    if own:
                        continue
                    rows.append({"name": name, "version": pin or ver or "", "ecosystem": "pypi", "manifest": m})
            else:
                lockp = nearest(files, d, ["package-lock.json"])
                lock = npm_lock(show(head, lockp) or "") if lockp else {}
                for name, spec in npm_deps(text):
                    if spec.startswith(("file:", "workspace:", "link:")):
                        continue
                    rows.append({"name": name, "version": lock.get(name) or spec.lstrip("^~"), "ecosystem": "npm",
                                 "manifest": m})
        return rows

    rows = read(near)
    note = ""
    if not rows:
        rows = read(manifests)
        # terms: english-begin
        note = ("The changed files' nearest manifests (%s) declare no direct dependencies, so these are the direct "
                "dependencies (not dev) of every manifest in the repository (%d manifests). Versions come from the "
                "lock files where they exist." % (", ".join(near) or "none", len(manifests)))
        # terms: english-end
    imported = set()
    for t in touched:
        if t.endswith(CODE_EXT) and t in files:
            imported |= {norm(n) for n in import_names(show(head, t) or "", t)}
    seen, out = set(), []
    for r in rows:
        key = (r["ecosystem"], norm(r["name"]))
        if key in seen:
            continue
        seen.add(key)
        out.append({"name": r["name"], "version": r["version"], "ecosystem": r["ecosystem"],
                    "imported_by_touched": norm(r["name"]) in imported})
    out.sort(key=lambda r: (r["ecosystem"], norm(r["name"])))
    return out, note


# ---- PR の中の名前（設計の 3.2・3.7）----
# 依頼の行の識別子（excerpts.banned_tokens）のうち、PR の差分かリポジトリの中で定義された物だけを、PR の中の名前に数える。
# 依頼の行に書かれた世の中の製品・標準の名前（PostgreSQL・pg_stat_activity など）は、依存の一覧に無くても数えない
# （#2637 の 1 回目で、探す役の行 2・行 12 が PostgreSQL で 3 周差し戻されて落ちた。attention/docs/measures/2637-world-result.md）。
# 定義の形は、ファイルのパス（とその後ろの部分）・コードの定義の文（def・class・const など）・行の頭のキーか代入・SQL の CREATE。
# 文書（.md・.mdx・.markdown・.adoc・.rst・.txt）の中の言及と、コードのコメントの行の言及は定義に数えない。
DOC_EXCLUDE = [":(exclude)*.md", ":(exclude)*.mdx", ":(exclude)*.markdown", ":(exclude)*.adoc", ":(exclude)*.rst",
               ":(exclude)*.txt"]
COMMENT_LINE = re.compile(r"^\s*(#|//|/\*|\*|--|<!--)")


def defined_patterns(token):
    e = re.escape(token)
    end = r"(?![\w$])"
    return [
        re.compile(r"\b(def|class|function|func|fn|const|let|var|type|interface|enum|struct)\s+" + e + end),
        re.compile(r"^\s*(export\s+)?[\"']?" + e + r"[\"']?\s*(:|=(?!=))"),
        re.compile(r"(?i:\bcreate\s+(or\s+replace\s+)?(table|view|function|index|type|schema)\s+(if\s+not\s+exists\s+)?)"
                   + e + end),
    ]


def own_names(lines, base, head):
    """依頼の行の識別子のうち、PR の差分（base と head）かリポジトリの中で定義された物（並べた一覧）"""
    tokens = sorted(excerpts.banned_tokens(lines))
    paths = set()
    for rev in (base, head):
        for f in must_git("-c", "core.quotepath=off", "ls-tree", "-r", "--name-only", rev).splitlines():
            parts = [x for x in f.split("/") if x]
            paths |= {"/".join(parts[i:]) for i in range(len(parts))} | set(parts)
    top = posixpath.basename(must_git("rev-parse", "--show-toplevel").strip().replace("\\", "/"))
    rc, url = git("remote", "get-url", "origin")
    repo = {top.lower()} | ({x.lower() for x in re.split(r"[/:]", re.sub(r"\.git$", "", url.strip()))[-2:] if x}
                            if rc == 0 else set())
    out = []
    for t in tokens:
        if t in paths or t.lower() in repo:
            out.append(t)
            continue
        pats = defined_patterns(t)
        for rev in (head, base):
            rc, found = git("grep", "-I", "-h", "-F", "-w", "-e", t, rev, "--", ".", *DOC_EXCLUDE)
            if rc == 0 and any(p.search(ln) for ln in found.splitlines() if not COMMENT_LINE.match(ln) for p in pats):
                out.append(t)
                break
    return out


# ---- 世界の解の DW の args（設計の 3.2・8.1）----

def lines_from_record(rec):
    mech = ((rec.get("structure") or {}).get("mechanisms")) if isinstance(rec, dict) else None
    if not isinstance(mech, list) or not mech:
        raise Stop("no-lines", "記録に structure.mechanisms が無いので、依頼の行を組めません")
    out = []
    for i, m in enumerate(mech, 1):
        text = str((m or {}).get("mechanism") or "").strip()
        premise = str((m or {}).get("premise") or "").strip()
        if premise:
            text = "%s Premise: %s" % (text, premise)
        out.append({"n": i, "where": "mechanism %d" % i, "text": text, "kind": "mechanism"})
    return out


def next_world(pr, record, lang, caller):
    try:
        with open(record, encoding="utf-8") as f:
            rec = json.load(f)
    except (OSError, ValueError):
        raise Stop("record", "記録 %s を読めません" % record)
    head, base = rec.get("head"), rec.get("base")
    if not (isinstance(head, str) and isinstance(base, str)):
        raise Stop("record", "記録に head と base がありません")
    now = must_git("rev-parse", "HEAD").strip()
    if now != head:
        raise Stop("head-mismatch", "作業場の HEAD（%s）が記録の head（%s）と違います。記録の head を出してから打ってください"
                   % (now[:7], head[:7]))
    if str(rec.get("pr")) != str(pr):
        raise Stop("record", "記録の PR（%s）が引数の PR（%s）と違います" % (rec.get("pr"), pr))
    purpose = rec.get("purpose") or {}
    touched = [p for p in must_git("-c", "core.quotepath=off", "diff", "--name-only", base, head).splitlines() if p]
    deps, note = collect_deps(head, touched)
    lines = lines_from_record(rec)
    args = {
        "caller": caller, "pr": int(pr), "head": head,
        "lines": lines,
        "purpose": str(purpose.get("purpose") or ""),
        "means": [m for m in (purpose.get("means") or []) if isinstance(m, str)],
        "deps": deps, "deps_note": note, "lang": lang,
        "own_names": own_names(lines, base, head),
        "excerptCheck": {"runPython": os.path.join(HERE, "run-python.sh"),
                         "script": os.path.join(ROOT, "steps", "world", "world-excerpts.py")},
    }
    args["sum"] = args_sum(args)
    path = os.path.join(steps_dir(pr), "world-args.json")
    write_json(path, args)
    return {"ok": True, "argsFile": path, "lines": len(args["lines"]), "means": len(args["means"]),
            "deps": len(deps), "depsImported": sum(1 for d in deps if d["imported_by_touched"]),
            "ownNames": len(args["own_names"]),
            "depsNote": note, "touched": len(touched)}


# ---- 返りの形の照合（設計の 2.2・3.8）----
ROW_KEYS = {"n": int, "where": str, "class_id": str, "problem": str, "proposed": str, "comparisons": list}
CMP_KEYS = {"against": dict, "layer": str, "practice": str, "sources": list, "basis": str, "applies": str,
            "not_applies": str, "verdict": str, "challenge": str, "level": str}


def shape_problems(val):
    if not isinstance(val, dict):
        return ["返りが JSON のオブジェクトでありません"]
    if "stopped" in val:
        return ["DW が止まった回です（stopped: %s）" % val.get("stopped")]
    out = []
    for k, t in {"ok": bool, "status": str, "rows": list, "missing": list, "excerpts": dict, "counts": dict}.items():
        if not isinstance(val.get(k), t):
            out.append("%s が無いか形が違います" % k)
    if val.get("status") not in ("ok", "partial", "failed"):
        out.append("status は ok・partial・failed のどれか")
    for i, r in enumerate(val.get("rows") or []):
        for k, t in ROW_KEYS.items():
            if not isinstance((r or {}).get(k), t):
                out.append("rows[%d].%s が無いか形が違います" % (i, k))
        af = (r or {}).get("arises_from")
        if af is not None and not (isinstance(af, int) and not isinstance(af, bool) and af > 0):
            out.append("rows[%d].arises_from は null か依頼の行の番号" % i)
        for j, c in enumerate((r or {}).get("comparisons") or []):
            for k, t in CMP_KEYS.items():
                if not isinstance((c or {}).get(k), t):
                    out.append("rows[%d].comparisons[%d].%s が無いか形が違います" % (i, j, k))
            if (c or {}).get("verdict") not in ("same", "differs", "none"):
                out.append("rows[%d].comparisons[%d].verdict は same・differs・none のどれか" % (i, j))
            if (c or {}).get("level") not in ("line", "origin"):
                out.append("rows[%d].comparisons[%d].level は line・origin のどれか" % (i, j))
            if (c or {}).get("basis") not in ("web", "knowledge"):
                out.append("rows[%d].comparisons[%d].basis は web・knowledge のどれか" % (i, j))
    for i, m in enumerate(val.get("missing") or []):
        if not (isinstance(m, dict) and isinstance(m.get("n"), int) and isinstance(m.get("why"), str)):
            out.append("missing[%d] は {n, why}" % i)
    return out


def unwrap(val):
    """Workflow の出力のファイルの包み（result を持つ物）を外す"""
    if isinstance(val, dict) and "result" in val and "rows" not in val and "stopped" not in val:
        val = val["result"]
        if isinstance(val, str):
            try:
                val = json.loads(val)
            except ValueError:
                return None
    return val


def save_world(pr, out_file):
    try:
        with open(out_file, encoding="utf-8") as f:
            val = unwrap(json.load(f))
    except (OSError, ValueError):
        raise Stop("output", "出力のファイル %s を読めません" % out_file)
    bad = shape_problems(val)
    if bad:
        raise Stop("shape", "返りの形が違うので書きません: %s" % " / ".join(bad[:10]))
    path = os.path.join(steps_dir(pr), "world.json")
    write_json(path, val)
    return {"ok": True, "saved": path, "status": val["status"], "rows": len(val["rows"]), "missing": len(val["missing"])}


def main(argv):
    ap = argparse.ArgumentParser(prog="steps-prep.py")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--next", choices=["world"])
    g.add_argument("--save", choices=["world"])
    ap.add_argument("pr")
    ap.add_argument("output", nargs="?")
    ap.add_argument("--record")
    ap.add_argument("--lang", default="Japanese")
    ap.add_argument("--caller", default=CALLERS[0], choices=CALLERS)
    a = ap.parse_args(argv)
    if not a.pr.isdigit():
        ap.error("PR 番号は数字")
    try:
        if a.next:
            if not a.record:
                raise Stop("no-record", "lines と purpose の DW がまだ無いので、--record <重い版の記録.json> が要ります")
            out = next_world(a.pr, a.record, a.lang, a.caller)
        else:
            if not a.output:
                ap.error("--save world <PR> <出力のファイル>")
            out = save_world(a.pr, a.output)
    except Stop as e:
        print(json.dumps({"ok": False, "code": e.code, "message": e.message}, ensure_ascii=False))
        return 1
    print(json.dumps(out, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
