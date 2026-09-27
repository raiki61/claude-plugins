"""道具ゼロの役に Read を 1 本だけ渡す形（graph の launch.isolated_read・節の read_file）——起こす側（advance.grant_read・
launch_spec）が組んだ argv を柵（commands.launch_refusal）が通し、読める範囲を広げた argv・置き場を撥ねることを見る"""
import os
import types

import pytest

from conftest import PLUGIN
from engine import advance, commands, role_run
from engine.schema import load_graph
from engine.validator import agent_def

GRAPH = load_graph(PLUGIN / "graphs" / "review-loop.json")[0]
ROLE = "convergence-loops:cold-reader"


@pytest.fixture
def emitted(tmp_path):
    """盤面の prompts/r1/ に指示書を置き、節の read_file の値（全文の写し）をその隣へ写して、launch_spec で argv を組む"""
    board = tmp_path / "board"
    pfile = board / "prompts" / "r1" / "p1.hygiene.md"
    pfile.parent.mkdir(parents=True)
    pfile.write_text("指示書", encoding="utf-8")
    src = board / "diff-r1.patch"
    src.write_bytes(b"diff --git a/x b/x\n")
    grant, why = advance.grant_read({"hist": {"snapshot": {"diff_file": str(src)}}}, "hist.snapshot.diff_file", pfile)
    assert why is None and grant == str(role_run.read_grant_path(pfile))
    d = agent_def(ROLE)
    b = types.SimpleNamespace(graph=GRAPH, dir=board, state={})
    inst = {"id": "p1.hygiene", "agent_type": ROLE, "prompt_file": str(pfile), "out_path": str(board / "out.json")}
    inst["launch"] = advance.launch_spec(b, inst, d, read_grant=grant)
    return types.SimpleNamespace(board=board, pfile=pfile, grant=grant, inst=inst, d=d)


def link(src, dst, **kw):
    """リンクを作れたか（Windows の権限の無い場では作れない——そのときはリンクの腕だけが空になる）"""
    try:
        os.symlink(src, dst, **kw)
        return True
    except OSError:
        return False


def refusal(e, **launch):
    return commands.launch_refusal({**e.inst, "launch": {**e.inst["launch"], **launch}}, board_dir=e.board)


def test_engine_built_argv_passes_the_fence(emitted):
    argv = emitted.inst["launch"]["argv"]
    assert emitted.inst["launch"]["kind"] == "isolated_read"
    assert argv[argv.index("--tools") + 1] == "Read" and argv[argv.index("--permission-mode") + 1] == "dontAsk"
    assert argv[argv.index("--allowedTools") + 1] == role_run.read_rule(emitted.grant)
    assert refusal(emitted) is None


@pytest.mark.parametrize("flag,value,words", [
    ("--allowedTools", "Read(//etc/passwd)", "--allowedTools"),     # 別のファイルを許す
    ("--tools", "Read,Grep", "--tools"),                              # 読む道具を足す
    ("--permission-mode", "default", "--permission-mode"),            # 聞く形に戻す
])
def test_fence_refuses_widened_argv(emitted, flag, value, words):
    argv = list(emitted.inst["launch"]["argv"])
    argv[argv.index(flag) + 1] = value
    why = refusal(emitted, argv=argv, resume_argv=None) or ""
    assert words in why, why


def test_fence_refuses_read_when_the_copy_is_not_the_engine_named_file(emitted, tmp_path):
    os.remove(emitted.grant)                                          # 写しが無い——Read を渡す形は起こさない
    assert "旗" in (refusal(emitted) or "")
    if link(str(tmp_path / "board" / "diff-r1.patch"), emitted.grant):  # 写しがリンク（読める先を差し替える）
        assert "旗" in (refusal(emitted) or "")


def test_fence_refuses_prompt_outside_the_board(emitted, tmp_path):
    other = tmp_path / "elsewhere" / "prompts" / "r1" / "p1.hygiene.md"
    other.parent.mkdir(parents=True)
    other.write_text("指示書", encoding="utf-8")
    role_run.read_grant_path(other).write_bytes(b"x")
    why = commands.launch_refusal({**emitted.inst, "prompt_file": str(other),
                                   "launch": {**emitted.inst["launch"], "stdin": str(other)}}, board_dir=emitted.board)
    assert "旗" in (why or ""), why


def test_plain_isolated_still_passes_without_a_copy(emitted):
    """read_file を持たない道具ゼロの節は今と同じ形（--tools ""）で起きる"""
    b = types.SimpleNamespace(graph=GRAPH, dir=emitted.board, state={})
    inst = {**emitted.inst, "id": "r2.compare", "prompt_file": str(emitted.pfile.with_name("r2.compare.md"))}
    emitted.pfile.with_name("r2.compare.md").write_text("指示書", encoding="utf-8")
    inst["launch"] = advance.launch_spec(b, inst, emitted.d)
    argv = inst["launch"]["argv"]
    assert inst["launch"]["kind"] == "isolated" and argv[argv.index("--tools") + 1] == ""
    assert commands.launch_refusal(inst, board_dir=emitted.board) is None


def test_read_rule_uses_the_real_path_and_refuses_rule_characters(tmp_path):
    real = tmp_path / "real"
    real.mkdir()
    (real / "f.read").write_text("x", encoding="utf-8")
    rule = role_run.read_rule(real / "f.read")
    assert rule.startswith("Read(//") and rule.endswith("f.read)") and "\\" not in rule
    if link(real, tmp_path / "link", target_is_directory=True):   # 祖先がリンクの綴りでも、規則は解決した先で組む
        assert role_run.read_rule(tmp_path / "link" / "f.read") == rule
    for bad in ("a b", "a,b", "a(b"):
        (tmp_path / bad).write_text("x", encoding="utf-8")
        assert role_run.read_rule(tmp_path / bad) is None


def test_grant_read_refuses_a_missing_source(tmp_path):
    pfile = tmp_path / "p.md"
    grant, why = advance.grant_read({"loop": {}}, "loop.diff_file", pfile)
    assert grant is None and "普通のファイルでない" in why and not role_run.read_grant_path(pfile).exists()
