"""graphloops/engine/role_run.py の unwrap（役の標準出力を解く）。包みかどうかを出力の形で分けること——type が result の
object だけが包みで、それ以外は全文が本文になり、受け付け（commands.parse_output）がそれを読めること。子プロセスを
通す端から端までの形は tests/simulate.py の test_role_run が見る。"""
import json

import pytest

from engine.commands import parse_output
from engine.role_run import SUMMARY_KEYS, unwrap


def envelope(**kw):
    env = {"type": "result", "subtype": "success", "is_error": False, "result": '{"ok": 1}', "session_id": "s-1",
           "num_turns": 2, "duration_ms": 10, "total_cost_usd": 0.001}
    env.update(kw)
    return json.dumps(env, ensure_ascii=False).encode("utf-8")


# --- 包みでない出力（--output-format text の形）: 全文が本文になり、受け付けが読む
@pytest.mark.parametrize("body", [
    pytest.param('{"findings": []}', id="bare-json"),
    pytest.param('```json\n{"findings": []}\n```', id="fenced"),
    pytest.param('{"findings": []}\n\n以上が判定です。', id="trailing-prose"),
])
def test_text_output_is_the_body(body):
    text, summary, bad = unwrap(body.encode("utf-8"))
    assert (text, summary, bad) == (body, {"envelope": False}, None)
    assert parse_output(text) == {"findings": []}


@pytest.mark.parametrize("raw", [
    pytest.param(b'[1, 2]', id="array"),
    pytest.param(b'null', id="null"),
    pytest.param(b'{"type": "assistant", "result": "x"}', id="object-not-result"),
])
def test_json_that_is_not_an_envelope_is_the_body(raw):
    text, summary, bad = unwrap(raw)
    assert text == raw.decode("utf-8") and summary == {"envelope": False} and bad is None


def test_empty_output_is_not_a_body():
    assert unwrap(b"  \n ") == (None, {}, "標準出力が空（包みも本文も無い）")


# --- 包み: 要約を残し、subtype を result より先に見る
def test_success_envelope_gives_result_and_summary():
    text, summary, bad = unwrap(envelope())
    assert text == '{"ok": 1}' and bad is None
    assert summary["envelope"] is True and summary["session_id"] == "s-1" and summary["total_cost_usd"] == 0.001
    assert set(summary) <= set(SUMMARY_KEYS) | {"envelope", "permission_denials"}


def test_error_envelope_without_result_names_subtype_and_errors():
    raw = json.dumps({"type": "result", "subtype": "error_max_turns", "is_error": True, "session_id": "s-2",
                      "errors": ["Reached maximum number of turns (9)"], "num_turns": 9}).encode("utf-8")
    text, summary, bad = unwrap(raw)
    assert text is None and bad == "役が誤りで終わった（error_max_turns: Reached maximum number of turns (9)）"
    assert summary["session_id"] == "s-2" and summary["num_turns"] == 9


@pytest.mark.parametrize("kw,want", [
    pytest.param({"is_error": True, "result": "API Error"}, "（success: API Error）", id="is_error-with-success"),
    pytest.param({"subtype": "error_during_execution", "errors": []}, "（error_during_execution: API Error）", id="empty-errors-fall-back"),
    pytest.param({"subtype": "error_during_execution", "errors": "boom"}, "（error_during_execution: API Error）", id="non-list-errors-fall-back"),
])
def test_error_envelope_is_not_accepted(kw, want):
    text, _summary, bad = unwrap(envelope(**{"result": "API Error", **kw}))
    assert text is None and bad.endswith(want)


def test_success_envelope_without_result_is_broken():
    raw = json.dumps({"type": "result", "subtype": "success", "session_id": "s-3"}).encode("utf-8")
    text, summary, bad = unwrap(raw)
    assert text is None and bad == "包みに result が無い（subtype=success）" and summary["session_id"] == "s-3"
