"""graphloops/tests/simulate_review.py の test_graphcheck_review_shapes のうち、schema.py（$ref の展開と語の走査）で落ちる
4 件の写し（mutations.json の ER1・ER2・SR1・WS1 の腕が当てにする検査）。bash 側は graphcheck.py を別のプロセスで走らせるが、
ここは graphcheck.check を同じプロセスで呼ぶ——変異の道具（mutmut）が差し替えた engine.schema を見るため。"""
import copy
import json

import pytest

from conftest import REVIEW_GRAPH_PATH, run_graphcheck

GRAPH = json.loads(REVIEW_GRAPH_PATH.read_text(encoding="utf-8"))


def class_query(g):
    return g["$defs"]["class_query"]["properties"]


def self_ref(g):
    g["$defs"]["loop"] = {"type": "object", "properties": {"x": {"$ref": "#/$defs/loop"}}}
    g["nodes"]["p4.ci"]["schema"]["properties"]["x"] = {"$ref": "#/$defs/loop"}


def typo_under_pattern_properties(g):
    pp = g["nodes"]["p3.fix"]["schema"]["properties"]["x_scalars"]["patternProperties"]
    pp["^x_[a-z0-9_]+$"]["minimun"] = 0


@pytest.mark.parametrize("breaks,want", [
    pytest.param(lambda g: class_query(g).__setitem__("how", {"$ref": "engine#/count_hwo"}), "が引けない", id="unresolvable-ref"),
    pytest.param(lambda g: class_query(g).__setitem__("how", {"$ref": "engine#/count_how", "type": "string"}), "他の語が並んでいる",
                 id="ref-overridden-by-siblings"),
    pytest.param(self_ref, "自分を引いている", id="self-ref"),
    pytest.param(typo_under_pattern_properties, "'minimun'", id="typo-under-pattern-properties"),
])
def test_graphcheck_rejects(sandbox, breaks, want):
    g = copy.deepcopy(GRAPH)
    breaks(g)
    ok, out = run_graphcheck(sandbox, g)
    assert not ok and want in out, out[-300:]
