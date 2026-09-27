"""台帳: 台本（graphloops/tests/simulate.py・simulate_review.py）の check ごとの行き先を、移した先のテストの印から機械で組む。

- 行き先の名乗りは pytest の印 1 本: ``@pytest.mark.moved_from("<台本のモジュール>.<関数>", "<check の説明の頭>", kept=None)``。
  parametrize の行は ``pytest.param(..., marks=pytest.mark.moved_from(...))``。node id は pytest が振った物を集める段で拾う
  （pytest_itemcollected。-k などで選び外す前）。``kept`` は同じプロセスの検査では見えない物を通し（台本）に残す理由
- 台本→移し先の対応の正本はこの印 1 つ。見張る台本は、印が名乗る台本と、**基の git の版**の MIGRATION.md の刷った塊に載っていた
  台本の和から、今の文書の「外した台本」の一覧に在る物を引いた集合。基の版と比べるのは、同じ変更で書き換えられる今の文書と比べると、
  塊の節を消すか刷り直して貼るだけで見張りから外れるから（buf breaking の against と同じ向き）。基は GL_LEDGER_BASE（CI が PR の基か
  push の直前の版を渡す）、無ければ HEAD と main との merge-base の両方。基を引けない checkout と変異の実行器の写しの中では、見張りの
  突合を見送り、見送りの行（SKIP ledger-base）を出す
- 台本の側の正本は台本の本文: 名指しした関数の中の ``check(条件, 説明)`` を ast で全部並べ、説明の頭（字列の定数か、f 字列の
  穴を ``{式}`` と描いた型紙）を持つ。印の頭は、その頭で始まる check がちょうど 1 つだけのときに当たる（0 は名乗りの誤り、2 以上は曖昧）
- ループの中の check は、回数を字面で読めるループ（字面の tuple・list か、関数の中でちょうど 1 度だけ字面の tuple に束ね、ほかに
  束ね直さない名前。条件式の両腕が字面なら読めるが、長さが違えば回数は決まらない）に限って型紙の 1 行として載せる。if の下に無い
  check は、入れ子の回数の積と行き先の本数が一致しないと赤。回数が決まらない check は 1 本以上で通し、表に出す。回数を字面で読めない
  ループ（while・関数の呼び出し・list に束ねた名前など）の中の check は赤のまま

使い方（表を刷る）: ``python3 graphloops/tests/py/ledger.py`` —— 置き場のテストを pytest で全部集めるだけ（走らせない）して、
MIGRATION.md の ``<!-- ledger:begin -->`` と ``<!-- ledger:end -->`` の間に貼る塊を出す。塊が今の台帳と違えば test_ledger.py が赤になる。
"""
import ast
import os
import pathlib
import re
import subprocess
import sys

import pytest

HERE = pathlib.Path(__file__).resolve().parent
TESTS = HERE.parent
MIGRATION = HERE / "MIGRATION.md"
MARK = "moved_from"
BEGIN, END = "<!-- ledger:begin -->", "<!-- ledger:end -->"
# ループ（回数を字面で読めるかは _times が決める）
LOOPS = (ast.For, ast.AsyncFor, ast.While, ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)
ENTRIES = pytest.StashKey[list]()
BASE_ENV = "GL_LEDGER_BASE"
# 変異の実行器の写しの中の回に立つ環境変数（名前の正本は tests/mutate.py の COPY_MARK。揃いは test_mutate_mark.py が縛る）
MUTATE_COPY = "GL_MUTATE_COPY"


def pytest_configure(config):
    config.addinivalue_line("markers", f"{MARK}(script, head, kept=None): 台本の check からこのテストへ移した印（台帳は ledger.py）")
    config.stash[ENTRIES] = []


def pytest_itemcollected(item):
    for m in item.iter_markers(MARK):
        item.config.stash[ENTRIES].append({"nodeid": item.nodeid, "file": item.path.name, "script": m.args[0], "head": m.args[1],
                                           "kept": m.kwargs.get("kept")})


def entries(config):
    return list(config.stash.get(ENTRIES, []))


def _head(node):
    """check の説明の頭: 字列の定数ならそのまま、f 字列なら穴を {式} と描いた型紙"""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        return "".join(v.value if isinstance(v, ast.Constant) else "{" + ast.unparse(v.value) + "}" for v in node.values)
    return None


def _is_check(n):
    return isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "check"


def _literal_len(node):
    """字面の tuple・list の長さ（* の展開を含むなら None）"""
    if isinstance(node, (ast.Tuple, ast.List)) and not any(isinstance(e, ast.Starred) for e in node.elts):
        return len(node.elts)
    return None


def _bindings(func, name):
    """関数の中で name を束ねる・消す所の数（代入・+= などの的・for と内包と with の的・:=・引数・except の as・match の捕まえ・
    def と class の名前・global・nonlocal・import の別名）"""
    n = 0
    for x in ast.walk(func):
        n += ((isinstance(x, ast.Name) and x.id == name and isinstance(x.ctx, (ast.Store, ast.Del)))
              or (isinstance(x, ast.arg) and x.arg == name)
              or (isinstance(x, (ast.ExceptHandler, ast.MatchAs, ast.MatchStar)) and x.name == name)
              or (isinstance(x, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and x.name == name and x is not func)
              or (isinstance(x, (ast.Global, ast.Nonlocal)) and name in x.names)
              or (isinstance(x, (ast.Import, ast.ImportFrom)) and any((a.asname or a.name.split(".")[0]) == name for a in x.names)))
    return n


def _tuple_like(node):
    """束ねた名前の中身を読むのは tuple だけ（長さを変えられない。list は名前の上の append・添字・別名・受け渡しで長さが変わる）"""
    return isinstance(node, ast.Tuple) or (isinstance(node, ast.IfExp) and isinstance(node.body, ast.Tuple) and isinstance(node.orelse, ast.Tuple))


def _times(iterable, func):
    """ループの回数 ——(回数, 読めたか)。回数 None で読めた＝字面だが長さが決まらない（条件式の両腕の長さが違う）"""
    if isinstance(iterable, ast.Name):
        bound = [a.value for a in ast.walk(func) if isinstance(a, ast.Assign)
                 for t in a.targets if isinstance(t, ast.Name) and t.id == iterable.id]
        if len(bound) != 1 or _bindings(func, iterable.id) != 1 or not _tuple_like(bound[0]):
            return None, False
        iterable = bound[0]
    if isinstance(iterable, ast.IfExp):
        a, b = _literal_len(iterable.body), _literal_len(iterable.orelse)
        return (a if a == b else None), a is not None and b is not None
    n = _literal_len(iterable)
    return n, n is not None


def checks_in(func):
    """関数の ast の check を並べる ——([{line, head, times}], [字面で読めないループの中の check の行])。

    times はループの外なら None、ループの中なら {"n": 回数（決まらなければ None）, "why": 決まらない理由}"""
    parents = {}
    for p in ast.walk(func):
        for c in ast.iter_child_nodes(p):
            parents[c] = p
    rows, unreadable = [], []
    for call in sorted((n for n in ast.walk(func) if _is_check(n)), key=lambda n: n.lineno):
        n, why, readable, looped, pending_if = 1, None, True, False, False
        node = call
        while node in parents and node is not func:
            up = parents[node]
            if isinstance(up, (ast.If, ast.IfExp)) and node is not up.test:
                pending_if = True   # 外側にループが見つかれば、その回の中の分かれ
            if isinstance(up, LOOPS) and node is not getattr(up, "iter", None):
                looped = True
                if pending_if:
                    why, pending_if = why or "if の下に在る", False
                gens = up.generators if hasattr(up, "generators") else [up]
                for g in gens:
                    k, ok = (None, False) if isinstance(g, ast.While) else _times(g.iter, func)
                    readable = readable and ok
                    if getattr(g, "ifs", None):
                        why = why or "if の下に在る"
                    if k is None and ok:
                        why = why or "条件式の両腕で回数が違う"
                    n = None if (k is None or n is None) else n * k
            node = up
        if looped and not readable:
            unreadable.append(call.lineno)
            why = why or "回数を字面で読めない"
        rows.append({"line": call.lineno, "head": _head(call.args[1]) if len(call.args) > 1 else None,
                     "times": {"n": None if why else n, "why": why} if looped else None})
    return rows, unreadable


def script_checks(script):
    """(check の一覧, 字面で読めないループの中の check の行) —— script は "<モジュール>.<関数>"。読めなければ ValueError"""
    try:
        mod, fn = script.split(".")
        tree = ast.parse((TESTS / f"{mod}.py").read_text(encoding="utf-8"))
    except (ValueError, OSError, SyntaxError) as e:
        raise ValueError(f"台本のファイルが読めない（{e}）") from e
    func = next((n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == fn), None)
    if func is None:
        raise ValueError(f"{mod}.py に関数 {fn} が無い")
    return checks_in(func)


# MIGRATION.md の刷った塊の中の台本の見出しと、「外した台本」の節の 1 行（- `<台本>`: <理由>）
SCRIPT_HEADING = re.compile(r"^#### (\S+)$", re.M)
REMOVED_ROW = re.compile(r"^- `([^`]+)`: \S", re.M)


def block(text):
    """MIGRATION.md の刷った塊（印の間。無ければ None）"""
    if BEGIN not in text or END not in text:
        return None
    return text.split(BEGIN, 1)[1].split(END, 1)[0].strip("\n")


def _git(root, *args):
    return subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, encoding="utf-8", errors="replace")


def base_revs(root):
    """前の版として読む基の版: GL_LEDGER_BASE（すべて 0 の sha は無いと読む——新しい枝の最初の push）、無ければ HEAD と main との merge-base。
    merge-base を origin/main からも main からも引けなければ空（HEAD だけを基にすると、作業ツリーを HEAD と比べるだけの自己比較になり、
    commit 済みの外しを赤にも見送りにもせず黙って通す——呼び元が見送りの行を出す）"""
    named = os.environ.get(BASE_ENV, "").strip()
    if named and named.strip("0"):
        return [named]
    for ref in ("origin/main", "main"):
        r = _git(root, "merge-base", "HEAD", ref)
        if r.returncode == 0:
            return ["HEAD", r.stdout.strip()]
    return []


def _format(src):
    """基の版の ledger.py が定める塊の印と台本の見出しの形 ——(BEGIN, END, 見出しの正規表現)。塊の約束を持たない版（BEGIN が無い）は None。
    今の版の定数で読まない——同じ変更で印か見出しの形を変えると、基の塊が『無い』と読めて見張りが空になる"""
    got = {}
    for n in ast.parse(src).body:
        if isinstance(n, ast.Assign):
            names = [t.id for t in n.targets if isinstance(t, ast.Name)] or \
                    [e.id for t in n.targets if isinstance(t, ast.Tuple) for e in t.elts if isinstance(e, ast.Name)]
            vals = n.value.elts if isinstance(n.value, ast.Tuple) else [n.value]
            for k, v in zip(names, vals):
                got[k] = v
    if "BEGIN" not in got:
        return None
    heading = got.get("SCRIPT_HEADING")
    parts = [got.get("BEGIN"), got.get("END"), heading.args[0] if isinstance(heading, ast.Call) and heading.args else None]
    if not all(isinstance(p, ast.Constant) and isinstance(p.value, str) for p in parts):
        raise ValueError("基の版の ledger.py の BEGIN・END・SCRIPT_HEADING が字面で読めない")
    return parts[0].value, parts[1].value, re.compile(parts[2].value, re.M)


def watched_at(root, rev, here=None):
    """基の版 rev の塊に載っていた台本（here はリポジトリの根からこの置き場への道）。rev を引けなければ None。塊の約束を持つ版
    （ledger.py が BEGIN を持つ）なのに MIGRATION.md の塊の印が読めなければ ValueError（『まだ約束が無い』と『読めない』を分ける。
    見出しは基の版の形で読むので、印の間に見出しが 0 なのは台本を全部外した後の本当に空の塊）"""
    if _git(root, "rev-parse", "--verify", "-q", f"{rev}^{{commit}}").returncode != 0:
        return None
    here = here or HERE.relative_to(pathlib.Path(_git(root, "rev-parse", "--show-toplevel").stdout.strip()).resolve()).as_posix()
    src = _git(root, "show", f"{rev}:{here}/ledger.py")
    fmt = _format(src.stdout) if src.returncode == 0 else None
    if fmt is None:
        return set()
    begin, end, heading = fmt
    doc = _git(root, "show", f"{rev}:{here}/{MIGRATION.name}").stdout
    if begin not in doc or end not in doc:
        raise ValueError(f"基の版 {rev[:12]} は塊の約束を持つ（ledger.py の BEGIN）のに、MIGRATION.md の塊の印が読めない")
    return set(heading.findall(doc.split(begin, 1)[1].split(end, 1)[0]))


def watched_before(root=HERE, here=None):
    """前の版で見張っていた台本（基の版ごとの和）と、見送る理由 ——(台本の集合 か None, 見送る理由 か None)"""
    if os.environ.get(MUTATE_COPY):
        return None, "変異の実行器の写しの中の回（写しの素のリポジトリには前の版が無い）"
    revs = base_revs(root)
    if not revs:
        return None, f"基の版を引けない（{BASE_ENV} が無く、HEAD と origin/main・main の merge-base も引けない。浅い clone・main の無い clone など）"
    got = [watched_at(root, rev, here) for rev in revs]
    if all(g is None for g in got):
        return None, f"基の版を引けない（{', '.join(revs)}。浅い clone・git の無い写しなど）"
    return set().union(*(g for g in got if g is not None)), None


def skip_line(why):
    """見送りの行（台本の見送りと同じ書き方。能力の名前は ledger-base）"""
    import parallel
    return parallel.skip_line("台帳の見張りの突合（前の版で見張っていた台本）", "ledger-base", f"基を引けないので見張りの突合を見送った——{why}")


def removed(text):
    """「外した台本」の節に 1 行を持つ台本（追記だけの一覧。見張りから外す唯一の口）"""
    part = text.split("\n## 外した台本", 1)
    if len(part) < 2:
        return set()
    return set(REMOVED_ROW.findall(part[1].split("\n## ", 1)[0]))


def build(found, before=(), gone=()):
    """台帳 —— ({script: [行]}, [問題])。行は {line, head, times, tests: [node id], kept: [理由]}。

    見張る台本は、found（集めた印）の台本と before（前の版で見張っていた台本）の和から gone（外した台本）を引いた物"""
    problems, table = [], {}
    named = {}
    for e in found:
        named.setdefault(e["script"], []).append(e["nodeid"])
    for script in sorted((set(named) | set(before)) - set(gone)):
        try:
            rows, unreadable = script_checks(script)
        except ValueError as err:
            problems.append(f"台帳が読めない台本 {script} を名乗る（{err}）: {', '.join(named.get(script, [])[:3]) or '基の版の塊'}")
            continue
        if script not in named:
            problems.append(f"{script}: 前の版で見張っていた台本を名乗るテストが無い——見張りから外すなら MIGRATION.md の"
                            f"「外した台本」に台本と理由を 1 行足す")
        if unreadable:
            problems.append(f"{script}: 回数を字面で読めないループの中に check が在る（行 {unreadable}）——1 行 1 件の数え方が崩れる")
        for r in rows:
            r["tests"], r["kept"] = [], []
            if not r["head"]:
                problems.append(f"{script}:{r['line']}: 説明の頭が取れない（字列の定数か f 字列で書く）")
        table[script] = rows
    for e in found:
        rows = table.get(e["script"])
        if rows is None:
            if e["script"] in gone:
                problems.append(f"{e['nodeid']}: 外した台本 {e['script']} を名乗る")
            continue
        hit = [r for r in rows if r["head"] and r["head"].startswith(e["head"])]
        if len(hit) != 1:
            problems.append(f"{e['nodeid']}: 頭「{e['head']}」で始まる check が {len(hit)} 件（ちょうど 1 件で当たる）")
            continue
        hit[0]["tests"].append(e["nodeid"])
        if e["kept"]:
            hit[0]["kept"].append(e["kept"])
    for script, rows in table.items():
        for r in rows:
            n = (r["times"] or {}).get("n")
            if not r["tests"]:
                problems.append(f"{script}:{r['line']}: 行き先が空（{r['head']}）")
            elif n is not None and len(r["tests"]) != n:
                problems.append(f"{script}:{r['line']}: ループで {n} 回走る check の行き先が {len(r['tests'])} 本（回数と同じ本数で当たる）")
    return table, problems


def _cell(s):
    return s.replace("|", "\\|").replace("\n", " ")


def _times_cell(t):
    if t is None:
        return ""
    return f"型紙 ×{t['n']}" if t["n"] is not None else f"型紙・1 本以上（{t['why']}）"


def render_md(table):
    """MIGRATION.md の刷った塊に貼る check ごとの対応の表（台本ごとに 1 つ）"""
    out = []
    for script, rows in table.items():
        out += [f"#### {script}", "", "| 行 | 元の check（説明の頭） | ループ | 移した先 | 通しに残す |", "|---|---|---|---|---|"]
        for r in rows:
            short = (r["head"] or "")[:60] + ("…" if len(r["head"] or "") > 60 else "")
            out.append(f"| {r['line']} | {_cell(short)} | {_times_cell(r['times'])} | {'<br>'.join(_cell(t) for t in r['tests'])} "
                       f"| {_cell(' / '.join(r['kept']))} |")
        out.append("")
    return "\n".join(out).rstrip("\n")


def collect(paths=(HERE,)):
    """置き場のテストを pytest で集めるだけ（走らせない）して、印の一覧を返す ——(集めた印, 終わりのコード, 出力)。conftest.py が
    載せた方の本 module（import 名 ledger）の登録物から読む——__main__ として読んだこの module とは別物"""
    import contextlib
    import io
    sys.path.insert(0, str(HERE))
    import ledger as plugin

    found = []

    class Collect:
        def pytest_collection_finish(self, session):
            found.extend(plugin.entries(session.config))

    log = io.StringIO()
    with contextlib.redirect_stdout(log):
        code = pytest.main(["-q", "--collect-only", "-p", "no:cacheprovider", *map(str, paths)], plugins=[Collect()])
    return found, code, log.getvalue()


def main(argv):
    found, code, log = collect()
    if code != pytest.ExitCode.OK:
        print(log[-2000:], file=sys.stderr)
        print(f"集める段が {code} で終わった", file=sys.stderr)
        return 1
    gone = removed(MIGRATION.read_text(encoding="utf-8"))
    table, problems = build(found, (), gone)
    print(render_md(table))
    before, why = watched_before()
    if before is None:
        print(skip_line(why), file=sys.stderr)
    else:
        problems += [p for p in build(found, before, gone)[1] if p not in problems]
    for p in problems:
        print("台帳の問題: " + p, file=sys.stderr)
    return 1 if problems else 0


if __name__ == "__main__":
    for _s in (sys.stdout, sys.stderr):   # Windows の既定 cp1252 で日本語の出力が落ちないように
        if hasattr(_s, "reconfigure"):
            _s.reconfigure(encoding="utf-8")
    sys.exit(main(sys.argv[1:]))
