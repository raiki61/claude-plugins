"""被覆の道具（cover_moved.py）の台本ごとの選び: 台本を名乗る node id の本体と、そのテストが使った波の作りだけを数える
（別の台本の移し先や、使っていない波の作りが通した行で『含まれる』と出さない）。道具そのものの撃ちは手で撃つ（MIGRATION.md）。
coverage を入れていない回（CI の pytest の job）でも import できる——道具は coverage を main の中で読む。"""
import cover_moved
import pytest
import waves

pytestmark = pytest.mark.small

A, B = ("graphloops/engine/a.py", 1), ("graphloops/engine/a.py", 2)
NEW = {"t.py::mine|run": {A}, "t.py::other|run": {B}, "t.py::mine|setup": {B}, "": set()}
WAVE = {"wave:x/used/end": {B}, "wave:x/unused/end": {B}}


def test_select_new_counts_only_the_named_tests_and_their_waves():
    got = cover_moved.select_new(NEW, WAVE, {"t.py::mine"}, set())
    assert set(got) == {"t.py::mine|run", ""}
    assert cover_moved.compare({"old:s": {A, B}}, got)["not_covered"] == 1


def test_select_new_counts_the_used_wave_as_setup():
    got = cover_moved.select_new(NEW, WAVE, {"t.py::mine"}, {"x/used/end"})
    assert set(got) == {"t.py::mine|run", "", "wave:x/used/end|setup"}
    r = cover_moved.compare({"old:s": {A, B}}, got)
    assert r["not_covered"] == 0 and r["covered_only_by_setup"] == 1


def test_used_waves_reads_the_junit_properties():
    xml = ('<testsuites><testsuite><testcase classname="test_scenarios_review" name="test_runaway[stops-at-round-5]">'
           '<properties><property name="gl_wave" value="review/runaway/end"/><property name="other" value="x"/></properties>'
           '</testcase><testcase classname="test_ledger" name="test_x"/></testsuite></testsuites>')
    assert cover_moved.used_waves(xml) == {"test_scenarios_review.py::test_runaway[stops-at-round-5]": {"review/runaway/end"}}


def test_lineage_follows_parents_and_borrowed_waves():
    got = waves.lineage("review/gate-empty-max/asked")
    assert {"review/gate-empty-max/init", "review/gate-empty/asked", "review/gate-empty/init"} <= set(got)
