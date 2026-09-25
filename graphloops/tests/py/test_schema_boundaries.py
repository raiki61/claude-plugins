"""graphloops/engine/schema.py の境界。mutmut で schema.py を撃ち、bash の台本の全件でも赤にならなかった変異 12 本を殺すために
足した（2026-09-25）: minimum を見ない／maximum を見ない／maximum の >=／数の検査を丸ごと外す／maxItems の >=／const が値を見ない
／null の判定の反転／知らない型を合格にする／patternProperties の再帰結果を = で上書き／$ref の解決条件を or にする（2 本）
／$ref に並べてよい語（note・description）を拒む。同じ形の見逃し（items の再帰結果を = で上書き）も 1 本足した。どれも「ちょうど」と「1 つ外」の組で置く。"""
import pytest

from engine.schema import expand_refs, validate_schema
from engine.util import ENGINE_DEFS


def rejected(value, schema):
    return bool(validate_schema(value, schema))


# --- 数の上下限（ちょうどは通り、1 つ外は落ちる）
@pytest.mark.parametrize("value,schema,want", [
    pytest.param(0, {"type": "integer", "minimum": 0}, False, id="minimum-exact"),
    pytest.param(-1, {"type": "integer", "minimum": 0}, True, id="minimum-below"),
    pytest.param(2, {"type": "integer", "maximum": 2}, False, id="maximum-exact"),
    pytest.param(3, {"type": "integer", "maximum": 2}, True, id="maximum-above"),
    pytest.param(0.5, {"type": "number", "minimum": 1}, True, id="float-is-checked"),
    pytest.param(True, {"minimum": 2}, False, id="bool-is-not-a-number"),
])
def test_number_bounds(value, schema, want):
    assert rejected(value, schema) is want


# --- 要素の数の上限
@pytest.mark.parametrize("value,want", [
    pytest.param([1, 2], False, id="maxItems-exact"),
    pytest.param([1, 2, 3], True, id="maxItems-above"),
])
def test_max_items(value, want):
    assert rejected(value, {"type": "array", "maxItems": 2}) is want


# --- const は値そのものを比べる（真偽値の区別は test_schema.py の写しが見る）
def test_const_rejects_other_value():
    assert rejected("b", {"const": "a"}) and not rejected("a", {"const": "a"})


# --- type の名前
@pytest.mark.parametrize("value,want", [
    pytest.param(None, False, id="null-accepts-None"),
    pytest.param(0, True, id="null-rejects-0"),
])
def test_type_null(value, want):
    assert rejected(value, {"type": "null"}) is want


def test_unknown_type_name_rejects():
    # 知らない型の名前（綴り違い）を合格にすると、その欄の型検査が消える
    assert rejected(1, {"type": "integr"})


# --- properties と patternProperties の誤りは全部残る（後の鍵の結果で前の誤りを上書きしない）
def test_errors_from_every_key_are_kept():
    schema = {"type": "object", "properties": {"a": {"type": "integer"}, "x_b": {"type": "integer"}},
              "patternProperties": {"^x_[a-z]+$": {"type": "integer"}}}
    errs = validate_schema({"a": "s", "x_b": "t"}, schema)
    # a の誤り 1 件と、x_b の properties 側と patternProperties 側の誤りの 2 件
    assert len(errs) == 3 and sum("$.a:" in e for e in errs) == 1 and sum("$.x_b:" in e for e in errs) == 2, errs


def test_errors_from_every_item_are_kept():
    # items の再帰も同じ（mutmut が同じ形の見逃しとして挙げた。12 本の外の 1 本）
    errs = validate_schema(["a", "b"], {"type": "array", "items": {"type": "integer"}})
    assert len(errs) == 2 and "$[0]:" in errs[0] and "$[1]:" in errs[1], errs


# --- $ref の解決は 2 つの綴り（#/$defs/<名前> と engine#/<名前>）の組み合わせだけ
ENGINE_NAME = sorted(ENGINE_DEFS)[0]


def expand(node):
    return expand_refs({"$defs": {"a": {"type": "string"}}, "nodes": {"n": {"schema": node}}})["nodes"]["n"]["schema"]


@pytest.mark.parametrize("ref", [
    pytest.param("other#/$defs/a", id="other-source-with-defs"),
    pytest.param(f"other#/{ENGINE_NAME}", id="other-source-with-engine-name"),
    pytest.param(f"#/{ENGINE_NAME}", id="local-source-with-engine-name"),
])
def test_ref_mixed_spellings_are_rejected(ref):
    with pytest.raises(ValueError, match="引けない"):
        expand({"$ref": ref})


@pytest.mark.parametrize("extra", ["note", "description"])
def test_ref_may_carry_explanations(extra):
    assert expand({"$ref": "#/$defs/a", extra: "説明"}) == {"type": "string"}
