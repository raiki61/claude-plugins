"""台帳（ledger.py）の柵: 台本の check ごとに行き先が在り、名乗りが台本の check にちょうど 1 件で当たり、MIGRATION.md の刷った塊が
今の台帳と同じ。前の版で見張っていた台本は、「外した台本」に 1 行を足さない限り見張りから消えない。

名乗りは pytest が集めた item の印から読むので、置き場のテストを全部集めた回で見る（``pytest graphloops/tests/py -k test_ledger``）。"""
import ast
import textwrap

import fence
import ledger
import pytest

pytestmark = pytest.mark.small


def _found(request):
    assert fence.collected_all(request.config), "台帳は置き場のテストを全部集めた回で見る（pytest graphloops/tests/py -k test_ledger）"
    return ledger.entries(request.config)


def _text():
    return ledger.MIGRATION.read_text(encoding="utf-8")


def _build(found):
    text = _text()
    return ledger.build(found, ledger.watched_before(text), ledger.removed(text))


def test_every_script_check_has_exactly_one_named_destination(request):
    _, problems = _build(_found(request))
    assert not problems, "\n".join(problems[:10])


def test_migration_block_is_exactly_the_ledger(request):
    table, _ = _build(_found(request))
    assert ledger.block(_text()) == ledger.render_md(table), \
        "MIGRATION.md の刷った塊（ledger:begin と ledger:end の間）が古い——python3 graphloops/tests/py/ledger.py で刷り直して貼れ"


def test_ledger_reports_every_check_without_a_destination(request):
    scripts = {e["script"] for e in _found(request)}
    table, problems = ledger.build([], scripts)
    total = sum(len(rows) for rows in table.values())
    assert total and len([p for p in problems if "行き先が空" in p]) == total


def _entry(script="simulate_review.test_rejections", head="先行例: ", nodeid="x::t"):
    return {"nodeid": nodeid, "file": "x.py", "script": script, "head": head, "kept": None}


@pytest.mark.parametrize("head, count", [("先行例: ", "件数が 2 以上"), ("台本に無い頭", "0 件")], ids=["ambiguous", "unknown"])
def test_ledger_rejects_a_head_that_does_not_hit_exactly_one_check(head, count):
    _, problems = ledger.build([_entry(head=head)])
    assert any("x::t: 頭" in p for p in problems), (count, problems[:3])


def test_a_script_watched_before_stays_watched_without_its_marks():
    """印を全部消しても、前の版の塊に載った台本は見張りから外れず赤（外すのは「外した台本」の 1 行だけ）"""
    _, problems = ledger.build([], {"simulate.test_gate_arms"})
    assert any("前の版で見張っていた台本を名乗るテストが無い" in p for p in problems), problems[:3]
    table, problems = ledger.build([], {"simulate.test_gate_arms"}, {"simulate.test_gate_arms"})
    assert not table and not problems


def test_marks_naming_a_removed_script_are_reported():
    _, problems = ledger.build([_entry(script="simulate.test_gate_arms", head="止まった周")], (), {"simulate.test_gate_arms"})
    assert any("外した台本 simulate.test_gate_arms を名乗る" in p for p in problems), problems[:3]


@pytest.mark.parametrize("script", ["simulate.no_such_function", "no_such_module.test_x", "no-dot"], ids=["function", "module", "spelling"])
def test_a_misspelled_script_is_a_named_problem_not_an_exception(script):
    _, problems = ledger.build([_entry(script=script, head="x")])
    assert any(f"台帳が読めない台本 {script} を名乗る" in p and "x::t" in p for p in problems), problems[:3]


def test_removed_and_watched_before_are_read_from_the_document():
    text = "\n".join(["# t", ledger.BEGIN, "#### simulate.a", "", "| x |", "", "#### simulate_review.b", ledger.END, "",
                      "## 外した台本", "", "- `simulate.c`: 消した（検査用）", "- `simulate.d`:", "", "## 次の節", "- `simulate.e`: 別の節"])
    assert ledger.watched_before(text) == {"simulate.a", "simulate_review.b"}
    assert ledger.removed(text) == {"simulate.c"}


def _checks(src):
    return ledger.checks_in(ast.parse(textwrap.dedent(src)).body[0])


def test_f_string_head_draws_its_holes_as_a_template():
    rows, _ = _checks('''
        def t():
            check(ok, f"{th}: {k} は残る——{g[k]!r}")
    ''')
    assert rows[0]["head"] == "{th}: {k} は残る——{g[k]}" and rows[0]["times"] is None


@pytest.mark.parametrize("src, times", [
    ("for th in ('a', 'b'):\n        check(x, f'{th}: y')", {"n": 2, "why": None}),
    ("xs = ['a', 'b', 'c']\n    for th in xs:\n        check(x, f'{th}: y')", {"n": 3, "why": None}),
    ("for a in (1, 2):\n        for b in (1, 2, 3):\n            check(x, f'{a}{b}: y')", {"n": 6, "why": None}),
    ("for th in ('a', 'b'):\n        if th == 'a':\n            check(x, f'{th}: y')", {"n": None, "why": "if の下に在る"}),
    ("for th in ('a', 'b'):\n        if th == 'a':\n            pass\n        check(x, f'{th}: y')", {"n": 2, "why": None}),
    ("for th in ('a', 'b'):\n        def f():\n            return 1\n        check(x, f'{th}: y')", {"n": 2, "why": None}),
    ("for th in ('a', 'b'):\n        if th:\n            continue\n        check(x, f'{th}: y')",
     {"n": None, "why": "ループの中に continue・break・return・raise が在る"}),
    ("ks = ('a', 'b') if z else ('a',)\n    for k in ks:\n        check(x, f'{k}: y')", {"n": None, "why": "条件式の両腕で回数が違う"}),
    ("ks = ('a',) if z else ('b',)\n    for k in ks:\n        check(x, f'{k}: y')", {"n": 1, "why": None}),
], ids=["tuple", "list-bound-once", "nested-product", "under-if", "if-beside", "nested-def-return", "continue", "ifexp-uneven",
        "ifexp-even"])
def test_loop_times_are_read_from_the_literal(src, times):
    rows, unreadable = _checks(f"def t():\n    {src}\n")
    assert rows[0]["times"] == times and not unreadable


@pytest.mark.parametrize("src", [
    "for th in names():\n        check(x, 'y')",
    "xs = (1,)\n    xs = (1, 2)\n    for th in xs:\n        check(x, 'y')",
    "while z:\n        check(x, 'y')",
    "for th in (*a, 1):\n        check(x, 'y')",
], ids=["call", "bound-twice", "while", "starred"])
def test_a_loop_whose_count_is_not_literal_is_red(src):
    rows, unreadable = _checks(f"def t():\n    {src}\n")
    assert unreadable == [rows[0]["line"]]


def test_a_bound_loop_needs_exactly_its_count_of_destinations(monkeypatch):
    rows = [{"line": 9, "head": "{th}: y", "times": {"n": 2, "why": None}}]
    monkeypatch.setattr(ledger, "script_checks", lambda script: ([dict(r) for r in rows], []))
    _, problems = ledger.build([_entry(script="s.t", head="{th}: y")])
    assert any("ループで 2 回走る check の行き先が 1 本" in p for p in problems), problems
    _, problems = ledger.build([_entry(script="s.t", head="{th}: y", nodeid=f"x::t[{i}]") for i in range(2)])
    assert not problems
