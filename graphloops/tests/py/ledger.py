"""台帳: 台本（graphloops/tests/simulate.py・simulate_review.py）の check ごとの行き先を、移した先のテストの印から機械で組む。

- 行き先の名乗りは pytest の印 1 本: ``@pytest.mark.moved_from("<台本のモジュール>.<関数>", "<check の説明の頭>", kept=None)``。
  parametrize の行は ``pytest.param(..., marks=pytest.mark.moved_from(...))``。node id は pytest が振った物を集める段で拾う
  （pytest_itemcollected。-k などで選び外す前）。``kept`` は同じプロセスの検査では見えない物を通し（台本）に残す理由
- 台本の側の正本は台本の本文: 名指しした関数の中の ``check(条件, 説明)`` を ast で全部並べ、説明の頭（字列の定数か、f 字列の
  最初の穴までの字）を持つ。印の頭は、その頭で始まる check がちょうど 1 つだけのときに当たる（0 は名乗りの誤り、2 以上は曖昧）
- 1 つの check 呼び出しが 1 本の ok 行になる前提で数える——ループの中の check は赤にする（静的な 1 行が複数の ok 行になる）

使い方（表を刷る）: ``python3 graphloops/tests/py/ledger.py`` —— pytest で集めるだけ（走らせない）して、MIGRATION.md に貼る表を出す。
表が MIGRATION.md の中身と食い違えば test_ledger.py が赤になる。
"""
import ast
import pathlib
import sys

import pytest

HERE = pathlib.Path(__file__).resolve().parent
TESTS = HERE.parent
# 台帳が見張る台本の関数（移す段ごとに足す）と、移した先のテストのファイル
SCRIPTS = ("simulate_review.test_rejections", "simulate.test_rejections")
MOVED_FILES = ("test_rejections_review.py", "test_rejections_research.py")
MARK = "moved_from"
LOOPS = (ast.For, ast.AsyncFor, ast.While, ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)
ENTRIES = pytest.StashKey[list]()


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
    """check の説明の頭: 字列の定数ならそのまま、f 字列なら最初の穴までの字"""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        out = ""
        for v in node.values:
            if not isinstance(v, ast.Constant):
                break
            out += v.value
        return out
    return None


def script_checks(script):
    """(check の一覧 [{line, head}], ループの中の check の行) —— script は "<モジュール>.<関数>" """
    mod, fn = script.split(".")
    tree = ast.parse((TESTS / f"{mod}.py").read_text(encoding="utf-8"))
    func = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == fn)
    calls = [n for n in ast.walk(func) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "check"]
    looped = sorted({c.lineno for loop in ast.walk(func) if isinstance(loop, LOOPS)
                     for c in ast.walk(loop) if isinstance(c, ast.Call) and isinstance(c.func, ast.Name) and c.func.id == "check"})
    rows = sorted(({"line": c.lineno, "head": _head(c.args[1]) if len(c.args) > 1 else None} for c in calls), key=lambda r: r["line"])
    return rows, looped


def build(found):
    """台帳 —— ({script: [行]}, [問題])。行は {line, head, tests: [node id], kept: [理由]}"""
    problems, table = [], {}
    for script in SCRIPTS:
        rows, looped = script_checks(script)
        if looped:
            problems.append(f"{script}: ループの中に check が在る（行 {looped}）——1 行 1 件の数え方が崩れる")
        for r in rows:
            r["tests"], r["kept"] = [], []
            if not r["head"]:
                problems.append(f"{script}:{r['line']}: 説明の頭が取れない（字列の定数か f 字列で書く）")
        table[script] = rows
    for e in found:
        rows = table.get(e["script"])
        if rows is None:
            problems.append(f"{e['nodeid']}: 台帳が見張らない台本 {e['script']} を名乗る")
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
            if not r["tests"]:
                problems.append(f"{script}:{r['line']}: 行き先が空（{r['head']}）")
    return table, problems


def _cell(s):
    return s.replace("|", "\\|").replace("\n", " ")


def render_md(table):
    """MIGRATION.md に貼る check ごとの対応の表（台本ごとに 1 つ）"""
    out = []
    for script, rows in table.items():
        out += [f"#### {script}", "", "| 行 | 元の check（説明の頭） | 移した先 | 通しに残す |", "|---|---|---|---|"]
        for r in rows:
            short = (r["head"] or "")[:60] + ("…" if len(r["head"] or "") > 60 else "")
            out.append(f"| {r['line']} | {_cell(short)} | {'<br>'.join(_cell(t) for t in r['tests'])} | {_cell(' / '.join(r['kept']))} |")
        out.append("")
    return "\n".join(out)


def main(argv):
    """移した先のファイルを pytest で集めるだけ（走らせない）して、表と問題を出す。conftest.py が載せた方の本 module
    （import 名 ledger）の登録物から読む——__main__ として読んだこの module とは別物"""
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
        code = pytest.main(["-q", "--collect-only", "-p", "no:cacheprovider", *[str(HERE / f) for f in MOVED_FILES]], plugins=[Collect()])
    if code != pytest.ExitCode.OK:
        print(log.getvalue()[-2000:], file=sys.stderr)
        print(f"集める段が {code} で終わった", file=sys.stderr)
        return 1
    table, problems = plugin.build(found)
    print(plugin.render_md(table))
    for p in problems:
        print("台帳の問題: " + p, file=sys.stderr)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
