"""台帳（ledger.py）の柵: 台本の check ごとに行き先が在り、名乗りが台本の check にちょうど 1 件で当たり、MIGRATION.md の表が今の台帳と同じ。

名乗りは pytest が集めた item の印から読むので、移した先のファイル（ledger.MOVED_FILES）と一緒に集めた回で見る。"""
import pathlib

import ledger
import pytest

pytestmark = pytest.mark.small
HERE = pathlib.Path(__file__).resolve().parent


def _found(request):
    found = ledger.entries(request.config)
    missing = sorted(set(ledger.MOVED_FILES) - {e["file"] for e in found})
    assert not missing, f"台帳は移した先のファイルと一緒に集めた回で見る（名乗りが集まっていないファイル: {missing}）"
    return found


def test_every_script_check_has_exactly_one_named_destination(request):
    _, problems = ledger.build(_found(request))
    assert not problems, "\n".join(problems[:10])


def test_migration_table_matches_the_ledger(request):
    table, _ = ledger.build(_found(request))
    assert ledger.render_md(table) in (HERE / "MIGRATION.md").read_text(encoding="utf-8"), \
        "MIGRATION.md の T1 の表が古い——python3 graphloops/tests/py/ledger.py で刷り直して貼れ"


def test_ledger_reports_every_check_without_a_destination():
    table, problems = ledger.build([])
    total = sum(len(rows) for rows in table.values())
    assert total and len([p for p in problems if "行き先が空" in p]) == total


@pytest.mark.parametrize("head, count", [("先行例: ", "件数が 2 以上"), ("台本に無い頭", "0 件")], ids=["ambiguous", "unknown"])
def test_ledger_rejects_a_head_that_does_not_hit_exactly_one_check(head, count):
    _, problems = ledger.build([{"nodeid": "x::t", "file": "x.py", "script": ledger.SCRIPTS[0], "head": head, "kept": None}])
    assert any("x::t: 頭" in p for p in problems), (count, problems[:3])
