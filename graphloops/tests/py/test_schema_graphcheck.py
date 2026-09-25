"""graphloops/tests/simulate_review.py の test_graphcheck_review_shapes のうち、schema.py（$ref の展開と語の走査）で落ちる
4 件の写し（mutations.json の ER1・ER2・SR1・WS1 の腕が当てにする検査）。bash 側は graphcheck.py を別のプロセスで走らせるが、
ここは graphcheck.check を同じプロセスで呼ぶ——変異の道具（mutmut）が差し替えた engine.schema を見るため。"""
import copy
import importlib.util
import json
import shutil

import pytest

from conftest import PLUGIN, REPO

_spec = importlib.util.spec_from_file_location("graphcheck", PLUGIN / "scripts" / "graphcheck.py")
graphcheck = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(graphcheck)
GRAPH = json.loads((PLUGIN / "graphs" / "review-loop.json").read_text(encoding="utf-8"))
VALIDATOR = REPO / "scripts" / "review-record.py"


@pytest.fixture(scope="module")
def sandbox(tmp_path_factory):
    """graphcheck はプロンプトと rules を graph の隣から読むので、graph を差し替える置き場に写しておく"""
    tmp = tmp_path_factory.mktemp("graphcheck")
    (tmp / "graphs").mkdir()
    shutil.copytree(PLUGIN / "prompts", tmp / "prompts")
    shutil.copytree(PLUGIN / "rules", tmp / "rules")
    return tmp


def class_query(g):
    return g["$defs"]["class_query"]["properties"]


def self_ref(g):
    g["$defs"]["loop"] = {"type": "object", "properties": {"x": {"$ref": "#/$defs/loop"}}}
    g["nodes"]["p4.ci"]["schema"]["properties"]["x"] = {"$ref": "#/$defs/loop"}


def typo_under_pattern_properties(g):
    pp = g["nodes"]["p4.scalars"]["schema"]["properties"]["scalars"]["patternProperties"]
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
    path = sandbox / "graphs" / "review-loop.json"
    path.write_text(json.dumps(g, ensure_ascii=False), encoding="utf-8")
    lines = []
    ok = graphcheck.check(path, str(VALIDATOR), emit=lines.append)
    out = "\n".join(map(str, lines))
    assert not ok and want in out, out[-300:]
