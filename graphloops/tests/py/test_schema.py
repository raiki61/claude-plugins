"""graphloops/engine/schema.py の単体の検査のうち、bash の台本（graphloops/tests/simulate.py）に在る物の写し。
check 1 件をテスト 1 件に写した（test_schema_pattern_properties 4・test_schema_end_anchored 9・test_schema_refs_fail_closed 6・
test_units の型検査 7 の計 26 件）。bash 側はまだ消していない——消すときは同じ変更で消し、件数の定数を両側で直す。"""
import pytest

from engine.schema import end_anchored, expand_refs, unknown_keywords, validate_schema
from engine.util import ENGINE_DEFS

# --- simulate.py test_schema_pattern_properties（4 件）
PP = {"type": "object", "additionalProperties": False, "properties": {"a": {"type": "integer"}},
      "patternProperties": {"^x_[a-z0-9_]+$": {"type": "number"}}}


def test_pattern_properties_accepts_matching_name():
    assert validate_schema({"a": 1, "x_n": 2.5}, PP) == []


def test_pattern_properties_other_name_goes_to_additional():
    assert any("知らない欄 'y'" in e for e in validate_schema({"y": 1}, PP))


def test_pattern_properties_checks_value_type():
    assert any("x_n" in e for e in validate_schema({"x_n": "1"}, PP))


def test_pattern_properties_keywords_are_walked():
    assert unknown_keywords({"patternProperties": {"^x_": {"typo": 1}}}) != []


# --- simulate.py test_schema_end_anchored（9 件）: pattern の $ は ECMA-262 の意味（入力の末尾だけ）
def matches(pat, s):
    return bool(end_anchored(pat).search(s))


@pytest.mark.parametrize("pat,hit,miss", [
    pytest.param("^a$", ["a"], ["a\n"], id="dollar-not-before-final-newline"),
    pytest.param("^a\\$$", ["a$"], ["a"], id="escaped-dollar-stays"),
    pytest.param("^[$]$", ["$"], ["a"], id="dollar-in-class-stays"),
    pytest.param("^[ab$]$", ["$"], [], id="class-runs-to-bracket"),
    pytest.param("^[]$]+$", ["]$"], ["]$\n"], id="bracket-first-in-class"),
    pytest.param("^[a]$", ["a"], ["a\n"], id="dollar-after-class"),
    pytest.param("^[\\[]a$", ["[a"], ["[a\n"], id="escaped-open-bracket-then-close"),
    pytest.param("^[^]$]$", ["a"], ["$", "a\n"], id="bracket-first-in-negated-class"),
    pytest.param("^[^]a]$", ["b"], ["b\n"], id="dollar-after-negated-class"),
])
def test_end_anchored(pat, hit, miss):
    assert all(matches(pat, s) for s in hit) and not any(matches(pat, s) for s in miss)


# --- simulate.py test_schema_refs_fail_closed（6 件）
ENGINE_NAME = sorted(ENGINE_DEFS)[0]


def expand(ref):
    return expand_refs({"$defs": {"a": {"type": "string"}}, "nodes": {"n": {"schema": {"$ref": ref}}}})["nodes"]["n"]["schema"]


def test_unexpanded_ref_is_rejected():
    assert any("展開されていない" in e for e in validate_schema({"x": 1}, {"$ref": "#/$defs/a"}))


def test_engine_ref_resolves():
    assert expand(f"engine#/{ENGINE_NAME}") == ENGINE_DEFS[ENGINE_NAME]


def test_local_ref_resolves():
    assert expand("#/$defs/a") == {"type": "string"}


@pytest.mark.parametrize("ref", [f"engine#/$defs/{ENGINE_NAME}", "#/a", "other#/a"])
def test_ref_outside_the_two_spellings_is_rejected(ref):
    with pytest.raises(ValueError, match="引けない"):
        expand(ref)


# --- simulate.py test_units の型検査（7 件）: 真偽値と数値を同一視しない・minLength は空白を除く・maxLength は素の長さ
@pytest.mark.parametrize("value,schema,rejected", [
    pytest.param(True, {"enum": [0, 1]}, True, id="enum-true-is-not-1"),
    pytest.param(1, {"enum": [0, 1]}, False, id="enum-1-passes"),
    pytest.param(True, {"const": 1}, True, id="const-true-is-not-1"),
    pytest.param("   ", {"type": "string", "minLength": 1}, True, id="minLength-strips-spaces"),
    pytest.param("xxx", {"type": "string", "maxLength": 2}, True, id="maxLength-over"),
    pytest.param("xx", {"type": "string", "maxLength": 2}, False, id="maxLength-exact"),
    pytest.param(" x ", {"type": "string", "maxLength": 2}, True, id="maxLength-counts-spaces"),
])
def test_types(value, schema, rejected):
    assert bool(validate_schema(value, schema)) is rejected
