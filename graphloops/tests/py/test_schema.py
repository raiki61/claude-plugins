"""graphloops/engine/schema.py の単体の検査の正本。S2b で bash の台本（graphloops/tests/simulate.py）の test_schema_pattern_properties・
test_schema_end_anchored・test_schema_refs_fail_closed と test_units の型検査を移し、bash 側を消した。台本の check 1 件をテスト 1 件
（parametrize の 1 行）に写し、対応は MIGRATION.md。拒む綴りのうち #/<engine の表の名前> は test_schema_boundaries.py に在る。"""
import pytest

from engine.schema import end_anchored, expand_refs, unknown_keywords, validate_schema
from engine.util import ENGINE_DEFS

# --- patternProperties: 型で決めた名前の外は、名前の形に合うものだけを受ける（OpenAPI の x- 拡張と同じ口）
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


# --- pattern の $ は ECMA-262 の意味（入力の末尾だけ）。エスケープした \$ と文字クラスの中の $ は字のまま。クラスの閉じは位置で決める
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


# --- 未展開の $ref は型検査が拒み、引ける綴りは docstring の名乗り（#/$defs/<名前> と engine#/<名前>）だけ。知らない語として無視して
# いたとき、未展開の {"$ref": …} は何でも合格にした。engine#/$defs/<名前> は演算子の優先順位で受け付けていた
ENGINE_NAME = sorted(ENGINE_DEFS)[0]


def expand(ref):
    return expand_refs({"$defs": {"a": {"type": "string"}}, "nodes": {"n": {"schema": {"$ref": ref}}}})["nodes"]["n"]["schema"]


def test_unexpanded_ref_is_rejected():
    assert any("展開されていない" in e for e in validate_schema({"x": 1}, {"$ref": "#/$defs/a"}))


def test_engine_ref_resolves():
    assert expand(f"engine#/{ENGINE_NAME}") == ENGINE_DEFS[ENGINE_NAME]


def test_local_ref_resolves():
    assert expand("#/$defs/a") == {"type": "string"}


# 拒む綴りは、条件の項を 1 つ外すと別の表の鍵に当たる形を選ぶ（engine の表の $defs/・局所の表の名前・局所の $defs/ を外した頭 6 字）。
# #/xxxxxxa は、局所の側の「$defs/ で始まる」の項を外すと name[6:] が a になって局所の a に当たる——この綴りだけが殺す変異がある
@pytest.mark.parametrize("ref", [
    pytest.param(f"engine#/$defs/{ENGINE_NAME}", id="engine-defs-engine-name"),
    pytest.param("engine#/$defs/a", id="engine-defs-local-name"),
    pytest.param("#/a", id="local-without-defs"),
    pytest.param("#/xxxxxxa", id="local-six-chars-then-local-name"),
    pytest.param("other#/a", id="other-source"),
])
def test_ref_outside_the_two_spellings_is_rejected(ref):
    with pytest.raises(ValueError, match="引けない"):
        expand(ref)


# --- 型検査: 真偽値と数値を同一視しない（bool は int の部分型）・minLength は空白を除く・maxLength は素の長さ（削って測らない）
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
