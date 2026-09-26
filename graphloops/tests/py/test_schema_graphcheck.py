"""graphcheck.check を同じプロセスで呼ぶ検査: graphloops/tests/simulate_review.py の test_graphcheck_review_shapes のうち
schema.py（$ref の展開と語の走査）で落ちる 4 件の写し（mutations.json の ER1・ER2・SR1・WS1 の腕が当てにする検査）と、節の鍵の
閉じた集合（検査 15）。bash 側は graphcheck.py を別のプロセスで走らせるが、ここは同じプロセスで呼ぶ——変異の道具（mutmut）が
差し替えた engine.schema を見るため。"""
import copy
import json
import shutil

import pytest

from conftest import PLUGIN, REVIEW_GRAPH_PATH, REVIEW_VALIDATOR as VALIDATOR, graphcheck, run_graphcheck

GRAPH = json.loads(REVIEW_GRAPH_PATH.read_text(encoding="utf-8"))


def class_query(g):
    return g["$defs"]["class_query"]["properties"]


def self_ref(g):
    g["$defs"]["loop"] = {"type": "object", "properties": {"x": {"$ref": "#/$defs/loop"}}}
    g["nodes"]["p4.ci"]["schema"]["properties"]["x"] = {"$ref": "#/$defs/loop"}


def typo_under_pattern_properties(g):
    pp = g["nodes"]["p3.fix"]["schema"]["properties"]["x_scalars"]["patternProperties"]
    pp["^x_[a-z0-9_]+$"]["minimun"] = 0


def typo_node_key(g):
    g["nodes"]["p4.ci"]["cnod"] = "after_first_round"


def write_graph(dirpath, g):
    path = dirpath / "graphs" / "review-loop.json"
    path.write_text(json.dumps(g, ensure_ascii=False), encoding="utf-8")
    return path


@pytest.mark.parametrize("breaks,want", [
    pytest.param(lambda g: class_query(g).__setitem__("how", {"$ref": "engine#/count_hwo"}), "が引けない", id="unresolvable-ref"),
    pytest.param(lambda g: class_query(g).__setitem__("how", {"$ref": "engine#/count_how", "type": "string"}), "他の語が並んでいる",
                 id="ref-overridden-by-siblings"),
    pytest.param(self_ref, "自分を引いている", id="self-ref"),
    pytest.param(typo_under_pattern_properties, "'minimun'", id="typo-under-pattern-properties"),
    pytest.param(typo_node_key, "節 p4.ci に知らない鍵 ['cnod']", id="unknown-node-key"),
])
def test_graphcheck_rejects(sandbox, breaks, want):
    g = copy.deepcopy(GRAPH)
    breaks(g)
    ok, out = run_graphcheck(sandbox, g)
    assert not ok and want in out, out[-300:]


# ---------------------------------------------------------------- 節の鍵の閉じた集合（検査 15）
def test_init_only_warns_on_unknown_node_key(sandbox):
    from engine import commands
    g = copy.deepcopy(GRAPH)
    typo_node_key(g)
    lines = []
    assert graphcheck.check(write_graph(sandbox, g), str(VALIDATOR), emit=lines.append, node_keys="warn")
    assert any(str(l).startswith("WARN 節 p4.ci に知らない鍵") for l in lines)
    notes = commands.check_graph(str(write_graph(sandbox, g)), str(VALIDATOR))
    assert len(notes) == 1 and "p4.ci に知らない鍵 ['cnod']" in notes[0]


def test_graphcheck_requires_rules_node_keys(tmp_path):
    """rules が節の鍵の宣言を持たないと照らせない——黙って外さず NG（LOOP_KEYS と同じ fail-closed）"""
    (tmp_path / "graphs").mkdir()
    shutil.copytree(PLUGIN / "prompts", tmp_path / "prompts")
    shutil.copytree(PLUGIN / "rules", tmp_path / "rules")
    rp = tmp_path / "rules" / "review-loop.py"
    src = rp.read_text(encoding="utf-8")
    rp.write_text(src.replace("NODE_KEYS = frozenset({", "NODE_KEYS_GONE = frozenset({", 1), encoding="utf-8")
    lines = []
    ok = graphcheck.check(write_graph(tmp_path, copy.deepcopy(GRAPH)), str(VALIDATOR), emit=lines.append)
    assert not ok and "NODE_KEYS / NODE_NOTE_KEYS" in "\n".join(map(str, lines))


def test_node_keys_are_read():
    """許す鍵の集合に、誰も読まなくなった鍵が残っていない（説明の鍵は除く）。engine の鍵は engine か graphcheck の本文に、
    rules の鍵は rules か graphcheck の本文に、宣言の外で現れる"""
    from engine.rules import load_rules
    from engine.schema import ENGINE_NODE_KEYS, load_graph
    check_src = (PLUGIN / "scripts" / "graphcheck.py").read_text(encoding="utf-8")
    engine_src = "".join(p.read_text(encoding="utf-8") for p in sorted((PLUGIN / "engine").glob("*.py")) if p.name != "schema.py")
    assert not [k for k in ENGINE_NODE_KEYS if f'"{k}"' not in engine_src + check_src]
    rules = load_rules(PLUGIN / "graphs" / "review-loop.json", load_graph(PLUGIN / "graphs" / "review-loop.json")[0])
    body = "\n".join(l for l in (PLUGIN / "rules" / "review-loop.py").read_text(encoding="utf-8").splitlines()
                     if not l.startswith("NODE_KEYS = ")) + check_src
    assert not [k for k in rules.NODE_KEYS if f'"{k}"' not in body and f"'{k}'" not in body]
