"""台帳（ledger.py）の柵: 台本の check ごとに行き先が在り、名乗りが台本の check にちょうど 1 件で当たり、MIGRATION.md の刷った塊が
今の台帳と同じ。基の版で見張っていた台本は、「外した台本」に 1 行を足さない限り見張りから消えない。

名乗りは pytest が集めた item の印から読むので、置き場のテストを全部集めた回で見る（``pytest graphloops/tests/py -k test_ledger``）。"""
import ast
import pathlib
import subprocess
import textwrap
import warnings

import fence
import ledger
import pytest


def _found(request):
    assert fence.collected_all(request.config), "台帳は置き場のテストを全部集めた回で見る（pytest graphloops/tests/py -k test_ledger）"
    return ledger.entries(request.config)


def _text():
    return ledger.MIGRATION.read_text(encoding="utf-8")


@pytest.mark.small
def test_every_script_check_has_exactly_one_named_destination(request):
    _, problems = ledger.build(_found(request), (), ledger.removed(_text()))
    assert not problems, "\n".join(problems[:10])


@pytest.mark.small
def test_migration_block_is_exactly_the_ledger(request):
    table, _ = ledger.build(_found(request), (), ledger.removed(_text()))
    assert ledger.block(_text()) == ledger.render_md(table), \
        "MIGRATION.md の刷った塊（ledger:begin と ledger:end の間）が古い——python3 graphloops/tests/py/ledger.py で刷り直して貼れ"


@pytest.mark.medium
def test_scripts_watched_at_the_base_stay_watched(request):
    """基の git の版の塊に載っていた台本は、今の印が名乗らなくても見張る（外すのは「外した台本」の 1 行だけ）"""
    found = _found(request)
    before, why = ledger.watched_before()
    if before is None:
        warnings.warn(ledger.skip_line(why))
        return
    _, problems = ledger.build(found, before, ledger.removed(_text()))
    assert not problems, "\n".join(problems[:10])


@pytest.mark.small
def test_ledger_reports_every_check_without_a_destination(request):
    scripts = {e["script"] for e in _found(request)}
    table, problems = ledger.build([], scripts)
    total = sum(len(rows) for rows in table.values())
    assert total and len([p for p in problems if "行き先が空" in p]) == total


def _entry(script="simulate_review.test_rejections", head="先行例: ", nodeid="x::t"):
    return {"nodeid": nodeid, "file": "x.py", "script": script, "head": head, "kept": None}


@pytest.mark.small
@pytest.mark.parametrize("head, count", [("先行例: ", "件数が 2 以上"), ("台本に無い頭", "0 件")], ids=["ambiguous", "unknown"])
def test_ledger_rejects_a_head_that_does_not_hit_exactly_one_check(head, count):
    _, problems = ledger.build([_entry(head=head)])
    assert any("x::t: 頭" in p for p in problems), (count, problems[:3])


@pytest.mark.small
def test_a_script_watched_before_stays_watched_without_its_marks():
    """印を全部消しても、基の版の塊に載った台本は見張りから外れず赤（外すのは「外した台本」の 1 行だけ）"""
    _, problems = ledger.build([], {"simulate.test_gate_arms"})
    assert any("前の版で見張っていた台本を名乗るテストが無い" in p for p in problems), problems[:3]
    table, problems = ledger.build([], {"simulate.test_gate_arms"}, {"simulate.test_gate_arms"})
    assert not table and not problems


@pytest.mark.small
def test_marks_naming_a_removed_script_are_reported():
    _, problems = ledger.build([_entry(script="simulate.test_gate_arms", head="止まった周")], (), {"simulate.test_gate_arms"})
    assert any("外した台本 simulate.test_gate_arms を名乗る" in p for p in problems), problems[:3]


@pytest.mark.small
@pytest.mark.parametrize("script", ["simulate.no_such_function", "no_such_module.test_x", "no-dot"], ids=["function", "module", "spelling"])
def test_a_misspelled_script_is_a_named_problem_not_an_exception(script):
    _, problems = ledger.build([_entry(script=script, head="x")])
    assert any(f"台帳が読めない台本 {script} を名乗る" in p and "x::t" in p for p in problems), problems[:3]


@pytest.mark.small
def test_removed_is_read_from_the_document():
    text = "\n".join(["# t", "## 外した台本", "", "- `simulate.c`: 消した（検査用）", "- `simulate.d`:", "", "## 次の節", "- `simulate.e`: 別の節"])
    assert ledger.removed(text) == {"simulate.c"}


# ---- 基の版の見張り（tmp の git リポジトリの 2 版） ---------------------------------------------------------------------

HERE_REL = "graphloops/tests/py"
S = "simulate.test_gate_arms"
LEDGER_SRC = pathlib.Path(ledger.__file__).read_text(encoding="utf-8")


def _doc(*scripts, removed_rows=(), begin=ledger.BEGIN, end=ledger.END):
    blocks = "\n\n".join(f"#### {s}\n\n| x |" for s in scripts)
    return "\n".join(["# 移し替え", "", "## 外した台本", "", *removed_rows, "", "## 対応", "", begin, blocks, end, ""])


def _git(root, *args):
    return subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t", *args], cwd=root, capture_output=True, text=True, check=True)


def _repo(tmp_path, base, work, base_ledger=LEDGER_SRC):
    """基の版（1 commit）に base の MIGRATION.md と base_ledger の ledger.py を置き、作業ツリーを work に書き換えた git リポジトリ"""
    d = tmp_path / "r" / HERE_REL
    d.mkdir(parents=True)
    _git(tmp_path / "r", "init", "-q", "-b", "main")
    if base_ledger is not None:
        (d / "ledger.py").write_text(base_ledger, encoding="utf-8")
    (d / "MIGRATION.md").write_text(base, encoding="utf-8")
    _git(tmp_path / "r", "add", "-A")
    _git(tmp_path / "r", "commit", "-qm", "base")
    (d / "MIGRATION.md").write_text(work, encoding="utf-8")
    return tmp_path / "r"


@pytest.fixture
def no_base_env(monkeypatch):
    monkeypatch.delenv(ledger.BASE_ENV, raising=False)
    monkeypatch.delenv(ledger.MUTATE_COPY, raising=False)


@pytest.mark.medium
@pytest.mark.parametrize("work", [
    _doc("simulate.test_stop_midway"),                    # 基の塊に在った台本の節を消した
    _doc(),                                               # 印を全部消して塊を刷り直した
    _doc(begin="<!-- other:begin -->", end="<!-- other:end -->"),   # 同じ変更で塊の印の形を変えた
    "# 塊の無い文書\n",                                   # 塊ごと消した
], ids=["section-removed", "reprinted-empty", "format-changed", "block-removed"])
def test_the_watch_is_read_from_the_base_not_from_the_working_document(tmp_path, no_base_env, work):
    """今の文書をどう書き換えても、基の版の塊に在った台本は見張りに残り、名乗るテストが無ければ赤"""
    root = _repo(tmp_path, _doc(S, "simulate.test_stop_midway"), work)
    before, why = ledger.watched_before(root, HERE_REL)
    assert before == {S, "simulate.test_stop_midway"} and why is None
    _, problems = ledger.build([], before, ledger.removed(work))
    assert any(f"{S}: 前の版で見張っていた台本を名乗るテストが無い" in p for p in problems), problems[:3]


@pytest.mark.medium
def test_only_a_removed_row_takes_a_script_off_the_watch(tmp_path, no_base_env):
    work = _doc(removed_rows=[f"- `{S}`: 検査用に外す", "- `simulate.test_stop_midway`: 検査用に外す"])
    root = _repo(tmp_path, _doc(S, "simulate.test_stop_midway"), work)
    before, _ = ledger.watched_before(root, HERE_REL)
    table, problems = ledger.build([], before, ledger.removed(work))
    assert not table and not problems


@pytest.mark.medium
def test_a_base_that_promises_a_block_but_has_none_is_red(tmp_path, no_base_env):
    """塊の約束を持つ基（ledger.py が BEGIN を持つ）の塊の印が読めなければ、空と読まずに赤"""
    root = _repo(tmp_path, "# 塊の無い基\n", _doc())
    with pytest.raises(ValueError, match="塊の約束を持つ"):
        ledger.watched_before(root, HERE_REL)


@pytest.mark.medium
def test_the_base_block_is_read_with_the_base_format(tmp_path, no_base_env):
    """基の塊は基の版の ledger.py の印で読む（今の版の印で読むと、同じ変更で印を変えただけで基の塊が『無い』に見える）"""
    old = LEDGER_SRC.replace(repr(ledger.BEGIN), repr("<!-- old:begin -->"), 1).replace('"<!-- ledger:begin -->"', '"<!-- old:begin -->"', 1)
    assert "<!-- old:begin -->" in old
    root = _repo(tmp_path, _doc(S, begin="<!-- old:begin -->"), _doc(), base_ledger=old)
    assert ledger.watched_before(root, HERE_REL) == ({S}, None)


@pytest.mark.medium
@pytest.mark.parametrize("base_ledger", [None, "SCRIPTS = ('simulate.test_rejections',)\n"], ids=["no-ledger", "ledger-without-block"])
def test_a_base_without_the_block_promise_watches_nothing_yet(tmp_path, no_base_env, base_ledger):
    root = _repo(tmp_path, "# まだ塊が無い\n", _doc(), base_ledger=base_ledger)
    assert ledger.watched_before(root, HERE_REL) == (set(), None)


@pytest.mark.medium
def test_the_named_base_wins_over_head(tmp_path, no_base_env, monkeypatch):
    """CI が渡す基（PR の基・push の直前の版）を読む——HEAD が同じ変更で塊を書き換えていても"""
    root = _repo(tmp_path, _doc(S), _doc())
    first = _git(root, "rev-parse", "HEAD").stdout.strip()
    _git(root, "commit", "-qam", "塊を消した")
    monkeypatch.setenv(ledger.BASE_ENV, first)
    assert ledger.watched_before(root, HERE_REL) == ({S}, None)
    monkeypatch.setenv(ledger.BASE_ENV, "0" * 40)   # 新しい枝の最初の push（直前の版が無い）は HEAD と merge-base に戻る
    assert ledger.watched_before(root, HERE_REL) == (set(), None)


@pytest.mark.medium
def test_no_base_or_a_mutation_copy_skips_with_a_skip_line(tmp_path, no_base_env, monkeypatch):
    """基を引けない checkout（git の無い置き場）と変異の実行器の写しの中では、赤にも黙った緑にもせず見送りの行を出す"""
    before, why = ledger.watched_before(tmp_path, HERE_REL)
    assert before is None and "基の版を引けない" in why
    assert " # SKIP ledger-base: 基を引けないので見張りの突合を見送った" in ledger.skip_line(why)
    monkeypatch.setenv(ledger.MUTATE_COPY, "1")
    before, why = ledger.watched_before(_repo(tmp_path, _doc(S), _doc()), HERE_REL)
    assert before is None and "変異の実行器の写し" in why


def _checks(src):
    return ledger.checks_in(ast.parse(textwrap.dedent(src)).body[0])


@pytest.mark.small
def test_f_string_head_draws_its_holes_as_a_template():
    rows, _ = _checks('''
        def t():
            check(ok, f"{th}: {k} は残る——{g[k]!r}")
    ''')
    assert rows[0]["head"] == "{th}: {k} は残る——{g[k]}" and rows[0]["times"] is None


@pytest.mark.small
@pytest.mark.parametrize("src, times", [
    ("for th in ('a', 'b'):\n        check(x, f'{th}: y')", {"n": 2, "why": None}),
    ("for th in ['a', 'b']:\n        check(x, f'{th}: y')", {"n": 2, "why": None}),
    ("xs = ('a', 'b', 'c')\n    for th in xs:\n        check(x, f'{th}: y')", {"n": 3, "why": None}),
    ("for a in (1, 2):\n        for b in (1, 2, 3):\n            check(x, f'{a}{b}: y')", {"n": 6, "why": None}),
    ("for th in ('a', 'b'):\n        if th == 'a':\n            check(x, f'{th}: y')", {"n": None, "why": "if の下に在る"}),
    ("for th in ('a', 'b'):\n        if th == 'a':\n            pass\n        check(x, f'{th}: y')", {"n": 2, "why": None}),
    ("for th in ('a', 'b'):\n        if th:\n            continue\n        check(x, f'{th}: y')", {"n": 2, "why": None}),
    ("ks = ('a', 'b') if z else ('a',)\n    for k in ks:\n        check(x, f'{k}: y')", {"n": None, "why": "条件式の両腕で回数が違う"}),
    ("ks = ('a',) if z else ('b',)\n    for k in ks:\n        check(x, f'{k}: y')", {"n": 1, "why": None}),
], ids=["tuple", "literal-list", "tuple-bound-once", "nested-product", "under-if", "if-beside", "continue-still-counts", "ifexp-uneven",
        "ifexp-even"])
def test_loop_times_are_read_from_the_literal(src, times):
    rows, unreadable = _checks(f"def t():\n    {src}\n")
    assert rows[0]["times"] == times and not unreadable


@pytest.mark.small
@pytest.mark.parametrize("src", [
    "def t():\n    for th in names():\n        check(x, 'y')",
    "def t():\n    xs = (1,)\n    xs = (1, 2)\n    for th in xs:\n        check(x, 'y')",
    "def t():\n    while z:\n        check(x, 'y')",
    "def t():\n    for th in (*a, 1):\n        check(x, 'y')",
    "def t():\n    xs = ['a', 'b']\n    xs.append('c')\n    for th in xs:\n        check(x, 'y')",
    "def t():\n    xs = ('a', 'b')\n    xs += ('c',)\n    for th in xs:\n        check(x, 'y')",
    "def t():\n    xs = ('a', 'b')\n    for xs in ((1, 2, 3),):\n        pass\n    for th in xs:\n        check(x, 'y')",
    "def t():\n    xs = ('a', 'b')\n    with f() as xs:\n        pass\n    for th in xs:\n        check(x, 'y')",
    "def t():\n    xs = ('a', 'b')\n    if (xs := g()):\n        pass\n    for th in xs:\n        check(x, 'y')",
    "def t(xs=()):\n    xs = ('a', 'b')\n    for th in xs:\n        check(x, 'y')",
    "def t():\n    xs = ('a', 'b')\n    try:\n        pass\n    except E as xs:\n        pass\n    for th in xs:\n        check(x, 'y')",
    "def t():\n    global xs\n    xs = ('a', 'b')\n    for th in xs:\n        check(x, 'y')",
], ids=["call", "bound-twice", "while", "starred", "list-bound", "augmented", "for-target", "with-as", "walrus", "argument", "except-as",
        "global"])
def test_a_loop_whose_count_is_not_literal_is_red(src):
    rows, unreadable = _checks(src)
    assert unreadable == [rows[0]["line"]]


@pytest.mark.small
def test_a_bound_loop_needs_exactly_its_count_of_destinations(monkeypatch):
    rows = [{"line": 9, "head": "{th}: y", "times": {"n": 2, "why": None}}]
    monkeypatch.setattr(ledger, "script_checks", lambda script: ([dict(r) for r in rows], []))
    _, problems = ledger.build([_entry(script="s.t", head="{th}: y")])
    assert any("ループで 2 回走る check の行き先が 1 本" in p for p in problems), problems
    _, problems = ledger.build([_entry(script="s.t", head="{th}: y", nodeid=f"x::t[{i}]") for i in range(2)])
    assert not problems
