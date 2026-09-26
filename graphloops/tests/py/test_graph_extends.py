"""graph の差し替えの版（"extends"）の読み方——engine/schema.py の load_graph が元の graph に RFC 7396（JSON Merge Patch）で重ねる。
TDD の流れ（graphs/review-loop-tdd.json）はこの口で今の流れ（graphs/review-loop.json）を写さずに差し替える。"""
import importlib.util
import json
import shutil
import types

import pytest

from conftest import PLUGIN, REPO
from engine.schema import graph_text, load_graph, merge_patch

_spec = importlib.util.spec_from_file_location("graphcheck", PLUGIN / "scripts" / "graphcheck.py")
graphcheck = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(graphcheck)


def write(p, obj):
    p.write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")
    return p


def test_merge_patch_replaces_arrays_and_merges_objects():
    got = merge_patch({"a": {"x": 1, "y": [1, 2]}, "b": 1}, {"a": {"y": [3]}, "c": 2})
    assert got == {"a": {"x": 1, "y": [3]}, "b": 1, "c": 2}


def test_merge_patch_null_removes_key():
    assert merge_patch({"a": 1, "b": 2}, {"a": None}) == {"b": 2}


def test_merge_patch_does_not_touch_the_base():
    base = {"n": {"deps": ["x"]}}
    merge_patch(base, {"n": {"deps": ["x", "y"]}})
    assert base == {"n": {"deps": ["x"]}}


def test_extends_overlays_nodes_on_the_base(tmp_path):
    write(tmp_path / "base.json", {"loop": "demo", "nodes": {"a": {"deps": [], "does": "元"}, "b": {"deps": ["a"]}}})
    over = write(tmp_path / "over.json", {"extends": "base.json", "nodes": {"b": {"deps": ["a", "c"]}, "c": {"deps": ["a"]}}})
    g, why = load_graph(over)
    assert why == ""
    assert g["loop"] == "demo" and "extends" not in g
    assert g["nodes"]["a"]["does"] == "元"
    assert g["nodes"]["b"]["deps"] == ["a", "c"] and g["nodes"]["c"]["deps"] == ["a"]


def test_extends_refs_resolve_against_the_merged_defs(tmp_path):
    write(tmp_path / "base.json", {"nodes": {"a": {"schema": {"$ref": "#/$defs/x"}}}, "$defs": {"x": {"type": "string"}}})
    over = write(tmp_path / "over.json", {"extends": "base.json", "nodes": {"b": {"schema": {"$ref": "#/$defs/y"}}},
                                          "$defs": {"y": {"type": "integer"}}})
    g, why = load_graph(over)
    assert why == ""
    assert g["nodes"]["a"]["schema"] == {"type": "string"} and g["nodes"]["b"]["schema"] == {"type": "integer"}


@pytest.mark.parametrize("ref,words", [
    pytest.param("sub/base.json", "同じ置き場", id="other-directory"),
    pytest.param("over.json", "輪", id="self"),
    pytest.param("missing.json", "が無い", id="missing-base"),
    pytest.param(5, "同じ置き場", id="not-a-string"),
    pytest.param("", "同じ置き場", id="empty"),
])
def test_extends_rejects(tmp_path, ref, words):
    (tmp_path / "sub").mkdir()
    write(tmp_path / "sub" / "base.json", {"nodes": {}})
    write(tmp_path / "base.json", {"nodes": {}})
    write(tmp_path / "mid.json", {"extends": "base.json", "nodes": {}})
    over = write(tmp_path / "over.json", {"extends": ref, "nodes": {}})
    g, why = load_graph(over)
    assert g is None and words in why


def test_extends_chain_overlays_every_level(tmp_path):
    """差し替えの版の上にまた差し替えの版を重ねられる（仕様の版を TDD の版の上に置く形）——根元から順に重ね、後の段が勝つ"""
    write(tmp_path / "base.json", {"loop": "demo", "nodes": {"a": {"deps": [], "does": "元"}, "b": {"deps": ["a"], "does": "元"}}})
    write(tmp_path / "mid.json", {"extends": "base.json", "nodes": {"b": {"does": "中"}, "c": {"deps": ["a"], "does": "中"}}})
    leaf = write(tmp_path / "leaf.json", {"extends": "mid.json", "nodes": {"c": {"does": "葉"}, "d": {"deps": ["c"]}}})
    g, why = load_graph(leaf)
    assert why == ""
    assert "extends" not in g and g["loop"] == "demo"
    assert [g["nodes"][k].get("does") for k in "abcd"] == ["元", "中", "葉", None]


@pytest.mark.parametrize("mid,words", [
    pytest.param({"extends": "missing.json", "nodes": {}}, "mid.json: extends 'missing.json' が無い", id="missing-base-in-the-middle"),
    pytest.param({"extends": "leaf.json", "nodes": {}}, "mid.json: extends が輪になっている（leaf.json → mid.json → leaf.json）", id="cycle"),
    pytest.param(["not", "an", "object"], "mid.json: graph が object でない", id="middle-not-an-object"),
])
def test_extends_chain_names_the_level_that_is_wrong(tmp_path, mid, words):
    """鎖の途中の誤りは、それを書いた段のファイル名で言う（葉のパスだけでは直す先を取り違える）。輪は例外の素通りでなく理由で返る"""
    write(tmp_path / "base.json", {"nodes": {}})
    write(tmp_path / "mid.json", mid)
    leaf = write(tmp_path / "leaf.json", {"extends": "mid.json", "nodes": {}})
    g, why = load_graph(leaf)
    assert g is None and words in why, why


def test_graph_text_covers_the_root_of_a_chain(tmp_path):
    """根元の graph の編集も、2 段上の葉の sha に映る"""
    base = write(tmp_path / "base.json", {"nodes": {}})
    write(tmp_path / "mid.json", {"extends": "base.json", "nodes": {}})
    leaf = write(tmp_path / "leaf.json", {"extends": "mid.json", "nodes": {}})
    before = graph_text(leaf)
    write(base, {"nodes": {"a": {}}})
    assert graph_text(leaf) != before


@pytest.mark.parametrize("mid_text", [
    pytest.param('{"extends": "base.json", "nodes": {', id="broken-json"),
    pytest.param('["not an object"]', id="not-an-object"),
    pytest.param('{"extends": "leaf.json"}', id="cycle"),
])
def test_graph_text_does_not_die_on_a_broken_level(tmp_path, mid_text):
    """run の途中に鎖の段が書きかけで壊れても、graph の変化の検知（graph_changed）は落ちずに変化として記録する——止めると直せない"""
    write(tmp_path / "base.json", {"nodes": {}})
    mid = write(tmp_path / "mid.json", {"extends": "base.json", "nodes": {}})
    leaf = write(tmp_path / "leaf.json", {"extends": "mid.json", "nodes": {}})
    before = graph_text(leaf)
    mid.write_text(mid_text, encoding="utf-8")
    after = graph_text(leaf)
    assert after != before and mid_text in after


def test_graph_text_covers_the_base(tmp_path):
    """init 後の graph の変化の検知（graph_sha）は、元の graph の編集も拾う。extends の無い graph は本文そのまま"""
    base = write(tmp_path / "base.json", {"nodes": {}})
    over = write(tmp_path / "over.json", {"extends": "base.json", "nodes": {}})
    before = graph_text(over)
    write(base, {"nodes": {"a": {}}})
    assert graph_text(over) != before
    assert graph_text(base) == base.read_text(encoding="utf-8")


@pytest.mark.parametrize("patch,words", [
    pytest.param({"p3.fix": {"post_check": None}}, "post_check を消した", id="null-removes-a-key"),
    pytest.param({"p3.fix": {"deps": ["p2.history"]}}, "deps を落とした", id="array-drops-items"),
    pytest.param({"p4.ci": None}, "nodes.p4.ci を消した", id="null-removes-a-node"),
    pytest.param({"p3.fix": {"schema": {"required": ["changes"]}}}, "schema.required を落とした", id="nested-array-drops-items"),
])
def test_graphcheck_rejects_an_overlay_that_drops_base_items(tmp_path, patch, words):
    """差し替えの版は元の節から何も落とさない——配列の置き換えと null の削除は重ね方（RFC 7396）の正規の形なので、graphcheck が止める"""
    for d in ("graphs", "prompts", "rules"):
        shutil.copytree(PLUGIN / d, tmp_path / d)
    over = json.loads((tmp_path / "graphs" / "review-loop-tdd.json").read_text(encoding="utf-8"))
    for nid, v in patch.items():   # null も字面のまま書く（重ねるのは load_graph の仕事）
        over["nodes"][nid] = v if v is None or nid not in over["nodes"] else {**over["nodes"][nid], **v}
    write(tmp_path / "graphs" / "review-loop-tdd.json", over)
    lines = []
    ok = graphcheck.check(tmp_path / "graphs" / "review-loop-tdd.json", REPO / "scripts" / "review-record.py", emit=lines.append)
    assert not ok and any(words in l for l in lines)


def test_shipped_tdd_graph_keeps_every_base_dep_and_read():
    """同梱の TDD 版は、差し替えた節の deps・reads から元の要素を落とさない（配列は置き換えなので、元に足された要素を黙って落としうる）"""
    base, _ = load_graph(PLUGIN / "graphs" / "review-loop.json")
    tdd, why = load_graph(PLUGIN / "graphs" / "review-loop-tdd.json")
    assert why == ""
    for nid, n in base["nodes"].items():
        for key in ("deps", "reads"):
            assert set(n.get(key) or []) <= set(tdd["nodes"][nid].get(key) or []), f"{nid}.{key}"


@pytest.mark.parametrize("patch,words", [
    pytest.param({}, None, id="plain-chain-passes"),
    pytest.param({"p4.ci": {"deps": []}}, "元の review-loop-tdd.json の nodes.p4.ci.deps を落とした", id="drops-an-item-the-middle-inherited"),
])
def test_graphcheck_takes_a_chain_on_the_tdd_graph(tmp_path, patch, words):
    """TDD の版の上にもう 1 段重ねた版を graphcheck が受け、根元から中間が継いだ要素を葉が落とせば止める（突合は直接の親の重ねた姿と）"""
    for d in ("graphs", "prompts", "rules"):
        shutil.copytree(PLUGIN / d, tmp_path / d)
    leaf = write(tmp_path / "graphs" / "review-loop-chain.json", {"extends": "review-loop-tdd.json", "nodes": patch})
    lines = []
    ok = graphcheck.check(leaf, REPO / "scripts" / "review-record.py", emit=lines.append)
    if words is None:
        assert ok, [l for l in lines if l.startswith("NG")][:5]
    else:
        assert not ok and any(words in l for l in lines), [l for l in lines if l.startswith("NG")][:5]


@pytest.mark.parametrize("patch,words", [
    pytest.param({"tree_guard_roles": []}, "tree_guard_roles を落とした", id="top-level-array"),
    pytest.param({"$defs": {"lane_reply": {"required": ["rev"]}}}, "p4.final_gates.schema.required を落とした", id="def-required-drops-items"),
    pytest.param({"inputs": {"review_md": None}}, "inputs.review_md を消した", id="null-removes-an-input"),
])
def test_graphcheck_rejects_an_overlay_that_drops_top_level_items(tmp_path, patch, words):
    """節の外（最上位の配列・$defs・inputs）も同じ重ね方で黙って消えうる——graph の全体を元と突き合わせる"""
    for d in ("graphs", "prompts", "rules"):
        shutil.copytree(PLUGIN / d, tmp_path / d)
    over = json.loads((tmp_path / "graphs" / "review-loop-tdd.json").read_text(encoding="utf-8"))
    for k, v in patch.items():   # 版が既に持つ object の鍵には 1 段だけ重ねる（版の $defs を丸ごと差し替えない）
        over[k] = {**over[k], **v} if isinstance(v, dict) and isinstance(over.get(k), dict) else v
    write(tmp_path / "graphs" / "review-loop-tdd.json", over)
    lines = []
    ok = graphcheck.check(tmp_path / "graphs" / "review-loop-tdd.json", REPO / "scripts" / "review-record.py", emit=lines.append)
    assert not ok and any(words in l for l in lines), lines[-5:]


@pytest.mark.parametrize("node,patch,words", [
    pytest.param("p3.fix_delta2", {"cond": "delta_fixd"}, "CONDS の名前でない", id="driver-cond-typo"),
    pytest.param("spec.approve", {"cond": "spec_flw"}, "CONDS の名前でない", id="driver-cond-typo-spec"),
    pytest.param("p3.fix", {"prompt_append": ["../prompts/review-loop/tdd/no-such.md"]}, "prompt_append のファイルが無い", id="prompt-append-missing"),
    pytest.param("p2.history", {"engine_run": {"builtin": "declared_checks", "why": "検査用"}}, "engine_run は回す側の節",
                 id="engine-run-on-a-role-node"),
    pytest.param("p4.ci", {"engine_run": {"builtin": "declared_checks"}}, "engine_run は {builtin", id="engine-run-without-why"),
])
def test_graphcheck_rejects_broken_nodes(tmp_path, node, patch, words):
    """足した静的検査は、赤くなる例を 1 つずつ持つ（driver の節の条件名・prompt_append・読む欄の節）"""
    for d in ("graphs", "prompts", "rules"):
        shutil.copytree(PLUGIN / d, tmp_path / d)
    g = json.loads((tmp_path / "graphs" / "review-loop.json").read_text(encoding="utf-8"))
    g["nodes"][node].update({k: v for k, v in patch.items() if v is not None})
    write(tmp_path / "graphs" / "review-loop.json", g)
    lines = []
    ok = graphcheck.check(tmp_path / "graphs" / "review-loop.json", REPO / "scripts" / "review-record.py", emit=lines.append)
    assert not ok and any(words in l for l in lines), lines[-5:]


def test_graphcheck_rejects_a_cond_reading_an_unknown_node(tmp_path):
    """条件の関数が宣言した読む欄の節が graph に無い——綴り違いの節名は実行の前に落ちる"""
    for d in ("graphs", "prompts", "rules"):
        shutil.copytree(PLUGIN / d, tmp_path / d)
    rules = tmp_path / "rules" / "review-loop.py"
    rules.write_text(rules.read_text(encoding="utf-8") + (
        "\n\n@cond_reads(\"out.p9.nowhere\")\ndef _bad_cond(v):\n    return True, \"検査用\"\n\n\nCONDS[\"bad_cond\"] = _bad_cond\n"), encoding="utf-8")
    g = json.loads((tmp_path / "graphs" / "review-loop.json").read_text(encoding="utf-8"))
    g["nodes"]["p4.ci"]["cond"] = "bad_cond"
    write(tmp_path / "graphs" / "review-loop.json", g)
    lines = []
    ok = graphcheck.check(tmp_path / "graphs" / "review-loop.json", REPO / "scripts" / "review-record.py", emit=lines.append)
    assert not ok and any("読む欄 'out.p9.nowhere' の節が無い" in l for l in lines), lines[-5:]


def test_dropped_names_where_an_object_became_a_value():
    assert graphcheck.dropped({"a": {"b": 1}}, {"a": 5}) == ["a を object でない値に差し替えた"]
    assert graphcheck.dropped({"a": 1}, 5) == ["節 を object でない値に差し替えた"]


def test_read_path_needs_loop_keys_and_defaults_round_keys():
    """loop.<鍵> は rules の LOOP_KEYS が無ければ落とす。rd.<鍵> は rules が ROUND_KEYS を持たなくても engine の周の鍵で照らす"""
    errs = []
    graphcheck.check_read_path("loop.x", "w", {"nodes": {}}, types.SimpleNamespace(), errs)
    graphcheck.check_read_path(f"rd.{next(iter(graphcheck.empty_round(0)))}", "w", {"nodes": {}}, types.SimpleNamespace(), errs)
    assert len(errs) == 1 and "LOOP_KEYS" in errs[0], errs


@pytest.mark.parametrize("write,schema,ok", [
    pytest.param({"to": "x"}, {"properties": {"f": {}}}, True, id="node-schema"),
    pytest.param({"to": "x", "from": "$"}, {"properties": {"f": {}}}, True, id="from-root"),
    pytest.param({"to": "x", "from": "sub.y"}, {"properties": {"sub": {"properties": {"f": {}}}}}, True, id="from-field"),
    pytest.param({"to": "x", "from": "gone"}, {"properties": {"sub": {}}}, False, id="from-missing-field"),
    pytest.param({"to": "x", "from": "sub"}, {"type": "object"}, False, id="from-without-properties"),
    pytest.param({"to": "x"}, {"type": "object"}, False, id="schema-without-properties"),
    pytest.param({"to": "x"}, None, False, id="no-schema"),
])
def test_record_path_under_writes_to_follows_the_written_schema(write, schema, ok):
    """record.<writes.to>.<欄> は、書く節の schema（from が在ればその欄の schema）の properties に在る欄だけ通す"""
    node = {"writes": [write], **({} if schema is None else {"schema": schema})}
    assert graphcheck._record_ok("x.f", {"nodes": {"n": node}}, types.SimpleNamespace()) is ok
