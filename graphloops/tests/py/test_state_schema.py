"""盤面の loop の形（graph の最上位の state_schema）——graphcheck が loop の読みを最後の欄まで照らすこと、rules の LOOP_KEYS と
両向きでそろうこと、engine が保存の時に照らして痕跡（state.loop_drift）を残し止めないこと。"""
import copy
import json
import shutil

import pytest

from conftest import PLUGIN, REPO, REVIEW_GRAPH_PATH, REVIEW_VALIDATOR, graphcheck, run_graphcheck
from engine import board as board_mod
from engine.schema import load_graph, schema_at
from engine.validator import TRACES, traces

GRAPH = json.loads(REVIEW_GRAPH_PATH.read_text(encoding="utf-8"))
TDD = json.loads((PLUGIN / "graphs" / "review-loop-tdd.json").read_text(encoding="utf-8"))
RESEARCH = json.loads((PLUGIN / "graphs" / "research-loop.json").read_text(encoding="utf-8"))


# ---------------------------------------------------------------- schema_at（path を宣言の木で辿る）
TREE = {"type": "object", "properties": {
    "a": {"type": "object", "properties": {"b": {"type": "string"}}},
    "m": {"type": "object", "patternProperties": {"^[0-9]+$": {"type": "object", "properties": {"x": {"type": "integer"}}}}},
    "l": {"type": "array", "items": {"type": "object", "properties": {"k": {"type": "string"}}}},
    "opaque": {"type": "object"}}}


@pytest.mark.parametrize("path,ok", [
    ("a.b", True), ("a.c", False), ("m.3.x", True), ("m.x", False), ("m.3.y", False), ("l.0.k", True), ("l.0.z", False),
    ("opaque", True), ("opaque.anything", False), ("zz", False)])
def test_schema_at_follows_the_declared_tree(path, ok):
    at, why = schema_at(TREE, path.split("."))
    assert (at is not None and not why) is ok, why


def test_schema_at_says_why_a_path_is_undeclared():
    assert "下の欄を持たない" in schema_at(TREE, ["opaque", "x"])[1]
    assert "'c'" in schema_at(TREE, ["a", "c"])[1]
    # 宣言が schema（object）でない欄（true・配列）の下は辿らず、落ちずに理由を返す
    assert schema_at({"properties": {"t": True}}, ["t", "x"]) == (None, "t の宣言が schema でない")


# ---------------------------------------------------------------- graphcheck（review の graph を 1 か所ずつ壊す）
def prompt_copy(sandbox, name, old, new):
    """指示書の写しを 1 語だけ変えて置き、節の prompt_file の名前を返す（元の置き場は変えない）"""
    src = sandbox / "prompts" / "review-loop" / f"{name}.md"
    dst = sandbox / "prompts" / "review-loop" / f"{name}.bad.md"
    text = src.read_text(encoding="utf-8")
    assert old in text
    dst.write_text(text.replace(old, new), encoding="utf-8")
    return f"../prompts/review-loop/{name}.bad.md"


def nested_reads(g, sandbox):
    g["nodes"]["p3.delta_review"]["reads"][0] = "loop.fix_delta.filez"


def nested_outputs(g, sandbox):
    g["nodes"]["p3.fix_delta"]["outputs"] = ["loop.fix_delta.revv"]


def nested_required_hole(g, sandbox):
    g["nodes"]["p3.delta_fix"]["prompt_file"] = prompt_copy(sandbox, "p3.delta_fix", "{{loop.delta_owed.rows}}", "{{loop.delta_owed.rowz}}")


def nested_optional_hole(g, sandbox):
    g["nodes"]["p2.diagnose"]["prompt_file"] = prompt_copy(sandbox, "p2.diagnose", "{{?loop.escalated}}", "{{?loop.escalated.whyy}}")


def pick_field(g, sandbox):
    g["nodes"]["p3.delta_fix"]["prompt_file"] = prompt_copy(sandbox, "p3.delta_fix", "{{loop.delta_owed.rows}}",
                                                            "{{loop.delta_owed.rows | pick key,fromm}}")


def nested_cond(g, sandbox):
    rules = sandbox / "rules" / "review-loop.py"
    src = rules.read_text(encoding="utf-8")
    if "bad_nested_loop" not in src:
        rules.write_text(src + "\n\nCONDS['bad_nested_loop'] = cond_reads('loop.last_material.main_path_observation.statuz')"
                         "(lambda v: (True, 'x'))\n", encoding="utf-8")
    g["nodes"]["p1.external_standards"]["cond"] = "bad_nested_loop"


def material_name_typo(g, sandbox):
    g["nodes"]["p3.delta_review"]["reads"].append("loop.last_material.main_path_observatoin.status")


@pytest.mark.parametrize("breaks,want", [
    pytest.param(nested_reads, "'loop.fix_delta.filez' を graph の state_schema で辿れない", id="reads-nested"),
    pytest.param(nested_outputs, "'loop.fix_delta.revv' を graph の state_schema で辿れない", id="outputs-nested"),
    pytest.param(nested_required_hole, "'loop.delta_owed.rowz' を graph の state_schema で辿れない", id="required-hole-nested"),
    pytest.param(nested_optional_hole, "'loop.escalated.whyy' を graph の state_schema で辿れない", id="optional-hole-nested"),
    pytest.param(pick_field, "pick の欄 'fromm'", id="hole-pick-field"),
    pytest.param(nested_cond, "'loop.last_material.main_path_observation.statuz' を graph の state_schema で辿れない", id="cond-reads-nested"),
    pytest.param(material_name_typo, "欄 'main_path_observatoin'", id="map-key-typo"),
    pytest.param(lambda g, s: g["state_schema"]["properties"].pop("gates"), "LOOP_KEYS の鍵 'gates' が graph の state_schema.properties に無い",
                 id="loop-keys-only"),
    pytest.param(lambda g, s: g["state_schema"]["properties"].__setitem__("ghost", {"type": "string"}),
                 "state_schema.properties の鍵 'ghost' が rules の LOOP_KEYS に無い", id="state-schema-only"),
    pytest.param(lambda g, s: g["state_schema"]["properties"]["gates"].__setitem__("oneOf", []), "state_schema: schema に engine が読まない語",
                 id="unknown-keyword"),
    pytest.param(lambda g, s: g["state_schema"]["properties"]["head_revs"]["patternProperties"].__setitem__("^[0-9+$", {}),
                 "state_schema: schema の正規表現", id="broken-regex"),
    pytest.param(lambda g, s: g["state_schema"].__setitem__("additionalProperties", True), "additionalProperties: false", id="open-top"),
    pytest.param(lambda g, s: g.pop("state_schema"), "state_schema（盤面の loop の形）が無い", id="missing-standalone"),
])
def test_graphcheck_rejects_loop_shape(sandbox, breaks, want):
    g = copy.deepcopy(GRAPH)
    breaks(g, sandbox)
    ok, out = run_graphcheck(sandbox, g)
    assert not ok and want in out, out[-400:]


def test_graphcheck_passes_the_shipped_loop_shapes():
    for name, validator in (("review-loop", "review"), ("review-loop-tdd", "review"), ("research-loop", "research")):
        lines = []
        assert graphcheck.check(PLUGIN / "graphs" / f"{name}.json", str(REPO / "scripts" / f"{validator}-record.py"), emit=lines.append), \
            [l for l in lines if str(l).startswith("NG")]


def test_graph_without_state_schema_keeps_the_old_checks_and_warns_on_init(sandbox):
    """持ち込み・旧い版の graph（state_schema が無い）は init で止めない: loop の読みは鍵の 1 段目だけで照らし、無いことを知らせる"""
    g = copy.deepcopy(GRAPH)
    g.pop("state_schema")
    g["nodes"]["p3.fix_delta"]["outputs"] = ["loop.fix_delta.revv"]   # 入れ子は照らせない（BASE と同じ）
    path = sandbox / "graphs" / "review-loop.json"
    path.write_text(json.dumps(g, ensure_ascii=False), encoding="utf-8")
    lines = []
    ok = graphcheck.check(path, str(REVIEW_VALIDATOR), emit=lines.append, node_keys="warn")
    assert ok and any(str(l).startswith("WARN ") and "state_schema" in str(l) for l in lines), lines[-5:]
    g["nodes"]["p3.fix_delta"]["outputs"] = ["loop.fix_deltaa"]   # 1 段目の綴り違いは今までどおり落ちる
    path.write_text(json.dumps(g, ensure_ascii=False), encoding="utf-8")
    lines = []
    assert not graphcheck.check(path, str(REVIEW_VALIDATOR), emit=lines.append, node_keys="warn")
    assert any("LOOP_KEYS に無い" in str(l) for l in lines)


# ---------------------------------------------------------------- 差し替えの版（extends）と research
@pytest.fixture()
def place(tmp_path):
    for d in ("prompts", "rules"):
        shutil.copytree(PLUGIN / d, tmp_path / d)
    (tmp_path / "graphs").mkdir()
    return tmp_path


def check_at(place, name, g, validator):
    p = place / "graphs" / f"{name}.json"
    p.write_text(json.dumps(g, ensure_ascii=False), encoding="utf-8")
    lines = []
    ok = graphcheck.check(p, str(REPO / "scripts" / f"{validator}-record.py"), emit=lines.append)
    return ok, "\n".join(map(str, lines))


@pytest.mark.parametrize("breaks,want", [
    pytest.param(lambda t: t["nodes"]["p3.tdd_tests"]["reads"].append("loop.tdd.redd"), "'loop.tdd.redd' を graph の state_schema で辿れない",
                 id="tdd-nested"),
    pytest.param(lambda t: t["state_schema"]["properties"].pop("tdd_gave_up"),
                 "LOOP_KEYS の鍵 'tdd_gave_up' が graph の state_schema.properties に無い", id="tdd-key-not-overlaid"),
])
def test_graphcheck_rejects_tdd_overlay(place, breaks, want):
    check_at(place, "review-loop", GRAPH, "review")
    t = copy.deepcopy(TDD)
    breaks(t)
    ok, out = check_at(place, "review-loop-tdd", t, "review")
    assert not ok and want in out, out[-400:]


def test_research_keeps_the_readable_loop_keys(place):
    """research の条件が読んでよい loop の鍵は LOOP_READS（stuck_hint）に絞ったまま——盤面の他の鍵を読む条件は落ちる"""
    rules = place / "rules" / "research-loop.py"
    rules.write_text(rules.read_text(encoding="utf-8") + "\n\nCONDS['reads_stuck_ids'] = cond_reads('loop.stuck_ids')(lambda v: (True, 'x'))\n",
                     encoding="utf-8")
    g = copy.deepcopy(RESEARCH)
    g["nodes"]["p1.refuter"]["cond"] = "reads_stuck_ids"
    ok, out = check_at(place, "research-loop", g, "research")
    assert not ok and "LOOP_READS" in out, out[-400:]
    g = copy.deepcopy(RESEARCH)   # 書き先の名乗り（outputs）は絞りの外の盤面の鍵でもよく、節の reads は絞りで落ちる
    g["nodes"]["p1.record_check"]["outputs"] = [*(g["nodes"]["p1.record_check"].get("outputs") or []), "loop.stuck_ids"]
    ok, out = check_at(place, "research-loop", g, "research")
    assert "loop.stuck_ids" not in out, out[-400:]
    g["nodes"]["p1.refuter"]["reads"] = [*g["nodes"]["p1.refuter"]["reads"], "loop.stuck_ids"]
    ok, out = check_at(place, "research-loop", g, "research")
    assert not ok and "節 p1.refuter.reads: 読む欄 'loop.stuck_ids' の鍵が rules の LOOP_READS" in out, out[-400:]
    rules.write_text(rules.read_text(encoding="utf-8") + "\nLOOP_READS = LOOP_READS | {'ghost'}\n", encoding="utf-8")
    ok, out = check_at(place, "research-loop", copy.deepcopy(RESEARCH), "research")
    assert not ok and "LOOP_READS の鍵 ['ghost'] が LOOP_KEYS に無い" in out, out[-400:]


# ---------------------------------------------------------------- engine の保存の時の照らし
def make_board(tmp_path, graph, loop):
    gp = tmp_path / "g.json"
    gp.write_text(json.dumps(graph, ensure_ascii=False), encoding="utf-8")
    d = tmp_path / "run"
    d.mkdir()
    (d / "state.json").write_text(json.dumps({"graph": str(gp), "round": 1, "rounds": [], "loop": loop, "rev": 0}), encoding="utf-8")
    (d / "record.json").write_text("{}", encoding="utf-8")
    return board_mod.Board(d)


SHAPE = {"type": "object", "additionalProperties": False, "properties": {
    "n": {"type": "integer"}, "d": {"$ref": "#/$defs/delta"}}}


def test_save_leaves_a_trace_and_does_not_stop(tmp_path):
    b = make_board(tmp_path, {"nodes": {}, "$defs": {"delta": {"type": "object", "properties": {"file": {"type": "string"}}}},
                              "state_schema": SHAPE}, {"n": "x", "d": {"file": 3}, "ghost": 1})
    b.save()
    b.save()   # 同じ周の同じ外れは 1 行だけ
    st = json.loads((b.dir / "state.json").read_text(encoding="utf-8"))
    errs = [r["error"] for r in st["loop_drift"]]
    assert len(errs) == 3 and any("loop.n" in e for e in errs) and any("loop.d.file" in e for e in errs) and any("ghost" in e for e in errs), errs
    rows = [json.loads(line) for line in (b.dir / "trace.jsonl").read_text(encoding="utf-8").splitlines()]
    assert sum(r["op"] == "loop_drift" for r in rows) == 3
    assert st["rev"] == 2   # 保存そのものは通った


def test_save_without_state_schema_does_not_check(tmp_path):
    b = make_board(tmp_path, {"nodes": {}}, {"anything": {"goes": 1}})
    b.save()
    assert "loop_drift" not in json.loads((b.dir / "state.json").read_text(encoding="utf-8"))


def test_save_records_a_check_that_could_not_run(tmp_path, monkeypatch):
    b = make_board(tmp_path, {"nodes": {}, "state_schema": {"type": "object"}}, {})
    def broken(*a):
        raise RuntimeError("検査用に落とす")
    monkeypatch.setattr(board_mod, "validate_schema", broken)
    b.save()
    st = json.loads((b.dir / "state.json").read_text(encoding="utf-8"))
    assert "照らせなかった" in st["loop_drift"][0]["error"] and st["rev"] == 1


def test_loop_drift_reaches_the_record_and_the_report():
    assert ("loop_drift", "loop_drift") in TRACES
    assert traces({"process": {"loop_drift": [{"round": 1, "error": "x"}]}}) == {"loop_drift": 1}


def test_shipped_state_schema_expands():
    for name in ("review-loop", "review-loop-tdd", "research-loop"):
        g, why = load_graph(PLUGIN / "graphs" / f"{name}.json")
        assert not why and g["state_schema"]["type"] == "object" and g["state_schema"]["additionalProperties"] is False
    g, _ = load_graph(PLUGIN / "graphs" / "review-loop-tdd.json")
    assert {"tdd", "tdd_gave_up", "fix_delta"} <= set(g["state_schema"]["properties"])
