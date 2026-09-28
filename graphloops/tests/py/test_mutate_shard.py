"""変異の実行器（リポジトリの根の tests/mutate.py）の組（--shard）と和の検算（--merge）。CI の mutation.yml は腕を OS ごとに組に
分けて撃ち、組の報告をまとめてから関門と --same-as に渡すので、欠け・食い違い・重なりを健全と言わないことと、まとめた報告が
1 本で撃った報告と同じ欄を持つことを縛る"""
import importlib.util

import conftest
import pytest

_spec = importlib.util.spec_from_file_location("mutate_shard_under_test", conftest.REPO / "tests" / "mutate.py")
mutate = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mutate)

SEL = ["a", "b", "c", "d", "e"]


def _shard(k, n=2, sel=SEL, rev="r1", **over):
    ids = mutate.shard_of(sel, k, n)
    rep = {"schemaVersion": "1", "rev": rev, "at": f"2026-09-28T0{k}:00:00+00:00", "pruned": [],
           "shard": {"k": k, "n": n, "selected": sel},
           "arms": [{"id": i, "title": i, "status": "Killed", "evidence": "印"} for i in ids],
           "control": {"root": {"rc": 0}}, "marker": {"rc": 0, "placed": ids, "seen": ids, "cover": {i: ["s~t"] for i in ids}, "skipped": {}},
           "summary": {"control_ok": True, "green": [], "uncovered": [], "pytest_control_ok": True, "pruned": 0,
                       "pytest_how": {"nodes": len(ids)}, "copies": {"made": 1, "reused": len(ids), "discarded": {"x": 1}}}}
    rep.update(over)
    return (f"s{k}.json", rep)


@pytest.mark.small
@pytest.mark.parametrize("text, want", [("0/1", (0, 1)), ("3/4", (3, 4)), ("4/4", None), ("1/0", None), ("a/2", None), ("", None)])
def test_parse_shard_reads_k_of_n(text, want):
    assert mutate.parse_shard(text) == want


@pytest.mark.small
def test_shards_cover_the_selection_once_round_robin():
    """組の割り当ては i % n の round-robin で、全部の組の和が選別をちょうど 1 回ずつ覆う"""
    parts = [mutate.shard_of(SEL, k, 3) for k in range(3)]
    assert parts == [["a", "d"], ["b", "e"], ["c"]] and sorted(x for p in parts for x in p) == SEL


@pytest.mark.small
def test_merge_of_all_shards_reads_like_one_report():
    """全部の組がそろえば健全で、腕は選別の順・copies と数の辞書は和・真偽は all（--same-as が使い回しを読める）"""
    res = mutate.merge_reports([_shard(1), _shard(0)])
    assert "merge_problems" not in res and mutate.healthy(res)
    assert [a["id"] for a in res["arms"]] == SEL and res["at"].startswith("2026-09-28T00")
    s = res["summary"]
    assert s["copies"] == {"made": 2, "reused": 5, "discarded": {"x": 2}} and s["pytest_how"] == {"nodes": 5}
    assert s["pytest_control_ok"] is True and s["control_ok"] is True and s["uncovered"] == []
    assert sorted(res["marker"]["seen"]) == SEL and res["marker"]["rc"] == 0 and set(res["control"]) == {"0:root", "1:root"}
    assert mutate.gate_efficacy(res)["material"]["status"] == "clean"


@pytest.mark.small
@pytest.mark.parametrize("reports, want", [
    ([_shard(0)], "組が欠けた"),
    ([_shard(0), _shard(1, n=3)], "組の数 n が揃わない"),
    ([_shard(0), _shard(0), _shard(1)], "同じ組の報告が 2 つ以上"),
    ([_shard(0), _shard(1, sel=SEL[::-1])], "selected が揃わない"),
    ([_shard(0), _shard(1, rev="r2")], "rev が揃わない"),
    ([_shard(0), _shard(1, arms=[])], "割り当てと一致しない"),
    ([_shard(0), _shard(1, partial=True)], "撃ち切っていない"),
    ([_shard(0), ("x.json", {"arms": []})], "組の身元"),
], ids=["missing", "n", "dup-k", "selected", "rev", "assignment", "partial", "not-a-shard"])
def test_merge_names_every_broken_sum(reports, want):
    """和の検算の外れは merge_problems に理由が載り、健全と言わない（終了コード・--gate-efficacy・--same-as が同じ判定を読む）"""
    res = mutate.merge_reports(reports)
    assert any(want in p for p in res["merge_problems"]) and not mutate.healthy(res)


@pytest.mark.small
def test_merge_names_an_arm_shot_by_two_shards():
    _, a = _shard(0)
    _, b = _shard(1)
    b["arms"].append(dict(a["arms"][0]))
    assert any("2 つ以上の組に在る腕" in p for p in mutate.merge_reports([("s0", a), ("s1", b)])["merge_problems"])


@pytest.mark.small
def test_merge_keeps_red_marker_and_uncountable_coverage():
    """1 組の印の写しが赤なら全体も赤（rc は最初の 0 でない値）、1 組が覆いを数えられない（None）なら全体も数えられない"""
    s0, s1 = _shard(0), _shard(1)
    s1[1]["marker"]["rc"] = "timeout"
    s1[1]["summary"]["uncovered"] = None
    res = mutate.merge_reports([s0, s1])
    assert res["marker"]["rc"] == "timeout" and res["summary"]["uncovered"] is None and not mutate.healthy(res)


@pytest.mark.small
def test_red_control_pytest_of_a_shard_does_not_fail_the_whole_run():
    """組の control の pytest が赤でも、まとめた回は健全のまま（evaluate と同じく pytest の赤だけを証拠から外す——組ごとに外してある）。
    台本の control の赤は全体を赤にする"""
    s0, s1 = _shard(0), _shard(1)
    s1[1]["control"]["pytest"] = {"rc": 1}
    s1[1]["summary"]["pytest_control_ok"] = False
    res = mutate.merge_reports([s0, s1])
    assert mutate.healthy(res) and res["summary"]["control_ok"] and res["summary"]["pytest_control_ok"] is False
    s1[1]["control"]["root"] = {"rc": 1}
    assert not mutate.healthy(mutate.merge_reports([s0, s1]))


@pytest.mark.small
def test_empty_shards_are_left_out_of_the_sums():
    """割り当て 0 本の組は control と印の写しを持たないので母数から外す（欠けとは見分ける）。全体の選別が 0 本なら empty"""
    sel = ["a"]
    res = mutate.merge_reports([_shard(0, sel=sel), _shard(1, sel=sel, control=None, marker=None, summary=None)])
    assert "merge_problems" not in res and set(res["control"]) == {"0:root"} and [x["assigned"] for x in res["shards"]] == [1, 0]
    empty = mutate.merge_reports([_shard(0, sel=[], arms=[]), _shard(1, sel=[], arms=[])])
    assert empty.get("empty") and not empty["arms"]


@pytest.mark.small
def test_one_shard_is_read_as_the_whole_only_through_the_sum():
    """組の報告 1 本を直に --gate-efficacy・--same-as に渡しても、n 分の 1 を全部として読まない"""
    _, one = _shard(0)
    assert mutate.gate_efficacy(one)["material"]["status"] == "found"
    assert any("control か印の写しが赤" in x for x in mutate.same_as_diff(one, {"arms": []}))


@pytest.mark.small
@pytest.mark.parametrize("vals, key, want", [
    ([0, 0], "rc", 0), ([0, -9, 1], "rc", -9), ([1, None], None, None), ([True, False], None, False),
    ([1, 2], None, 3), ([[1], [2]], None, [1, 2]), ([{"a": 1}, {"a": 2, "b": [1]}], None, {"a": 3, "b": [1]}), (["x", "y"], None, "x"),
])
def test_merge_values_has_one_rule_per_type(vals, key, want):
    assert mutate.merge_values(vals, key) == want
